"""S2-J1：版本化“成功 usage 保守结算”核心定向测试（Mock-only，纯隔离账本）。

只导入 ``mktkb.rag.budget`` / ``mktkb.rag.settlement_policy`` / ``mktkb.rag.errors``，
不导入 app / provider / support / 真实服务；所有账本都在 ``tmp_path`` 隔离。

覆盖任务单“最小验证”：
- 旧 hist0.03 + 旧成功/失败/孤立 result 语义不变；新未结算保持原额；
- 新完整 chat 成功只释放差额；E/R 只按 total_tokens 释放；
- 缺字段/类型 bool/float/负值/NaN/矛盾/超 cap/wrong host/source/sha/低 charge 伪造等不减；
- 同 reservation 双结算、跨进程竞争只有一次结果；释放后新 reserve 同锁计算、
  请求数不重置；重启/重放幂等；summary 两次完全一致；
- 篡改低 charge / 未知策略 / 孤立版本化 result 均 fail closed；
- 重算额高于预留时不用 min 掩盖；provider_billed 仍 null；快照白名单无 secret。
"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from typing import Any, Mapping

import pytest

from mktkb.rag.budget import (
    BudgetLedger,
    Reservation,
    SettlementBoundaryAnomaly,
    SettlementNotReleasable,
)
from mktkb.rag.errors import BudgetExceeded, BudgetLedgerInvalid, RequestLimitExceeded
from mktkb.rag.settlement_policy import (
    CHAT_COMPLETION_TOKENS_CAP,
    CHAT_PROMPT_TOKENS_CAP,
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_RERANK,
    SettlementPolicyError,
    UsageEvidence,
    build_policy,
    policy_from_snapshot,
    policy_to_snapshot,
)

REQ_SHA = "a" * 64
OTHER_SHA = "b" * 64
CHAT_MODEL = "deepseek-flash"
EMBEDDING_MODEL = "text-embedding-v4"
RERANK_MODEL = "gte-rerank-v2"
CHAT_RESERVE = 2.103552  # 官方 context ceiling 1,048,576 输入 + 800 输出
EMBEDDING_RESERVE = 0.04096  # 10 × 8192 × 0.5/1e6
RERANK_RESERVE = 0.024  # 30000 × 0.8/1e6

CHAT_POLICY = build_policy(KIND_CHAT, model=CHAT_MODEL)
EMBEDDING_POLICY = build_policy(KIND_EMBEDDING, model=EMBEDDING_MODEL)
RERANK_POLICY = build_policy(KIND_RERANK, model=RERANK_MODEL)


# ---------------------------------------------------------------- 装配与证据


def make_ledger(
    tmp_path: Path,
    *,
    total_limit_cny: float = 10.0,
    stage_limit_cny: float = 10.0,
    max_requests: int = 1000,
    history_cny: float = 0.03,
) -> BudgetLedger:
    budget_path = tmp_path / "budget.json"
    budget_path.write_text(
        json.dumps(
            {"limit_cny": total_limit_cny, "stages": {"S1-DEV": stage_limit_cny}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ledger_path = tmp_path / "live-ledger.jsonl"
    ledger_path.write_text(
        json.dumps(
            {"event": "historical_import", "accounted_cny": history_cny, "note": "history"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return BudgetLedger(
        ledger_path,
        budget_path,
        stage="S1-DEV",
        stage_limit_cny=stage_limit_cny,
        max_requests=max_requests,
    )


def reserve_with_policy(
    ledger: BudgetLedger,
    *,
    kind: str,
    amount: float,
    request_sha256: str = REQ_SHA,
    policy: Any | None = None,
) -> Reservation:
    if kind == KIND_CHAT:
        provider, model, default_policy = "deepseek", CHAT_MODEL, CHAT_POLICY
    elif kind == KIND_EMBEDDING:
        provider, model, default_policy = "bailian", EMBEDDING_MODEL, EMBEDDING_POLICY
    else:
        provider, model, default_policy = "bailian", RERANK_MODEL, RERANK_POLICY
    return ledger.reserve(
        kind=kind,
        provider=provider,
        model=model,
        max_cny=amount,
        request_sha256=request_sha256,
        settlement_policy=default_policy if policy is None else policy,
    )


def chat_usage(**overrides: Any) -> dict[str, Any]:
    usage: dict[str, Any] = {
        "prompt_tokens": 1000,
        "completion_tokens": 200,
        "total_tokens": 1200,
        "prompt_cache_hit_tokens": 600,
        "prompt_cache_miss_tokens": 400,
    }
    usage.update(overrides)
    return usage


def chat_evidence(**overrides: Any) -> UsageEvidence:
    values: dict[str, Any] = {
        "kind": KIND_CHAT,
        "provider": "deepseek",
        "model": CHAT_MODEL,
        "host": "api.deepseek.com",
        "region": "global",
        "pricing_source": CHAT_POLICY.pricing_source,
        "request_sha256": REQ_SHA,
        "http_status": 200,
        "streamed": False,
        "finish_reason": "stop",
        "content_complete": True,
        "content_parse_ok": True,
        "output_valid": False,
        "usage": chat_usage(),
    }
    values.update(overrides)
    return UsageEvidence(**values)


def total_evidence(kind: str, total_tokens: int, **overrides: Any) -> UsageEvidence:
    policy = EMBEDDING_POLICY if kind == KIND_EMBEDDING else RERANK_POLICY
    values: dict[str, Any] = {
        "kind": kind,
        "provider": "bailian",
        "model": EMBEDDING_MODEL if kind == KIND_EMBEDDING else RERANK_MODEL,
        "host": "dashscope.aliyuncs.com",
        "region": "cn-beijing",
        "pricing_source": policy.pricing_source,
        "request_sha256": REQ_SHA,
        "http_status": 200,
        "output_valid": True,
        "usage": {"total_tokens": total_tokens},
    }
    values.update(overrides)
    return UsageEvidence(**values)


def read_events(ledger: BudgetLedger) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in ledger.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def rewrite_events(ledger: BudgetLedger, events: list[dict[str, Any]]) -> None:
    ledger.ledger_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


# ---------------------------------------------------------------- 旧语义不变


def test_old_succeeded_small_usage_does_not_release(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = ledger.reserve(
        kind=KIND_EMBEDDING,
        provider="bailian",
        model=EMBEDDING_MODEL,
        max_cny=0.5,
        request_sha256=REQ_SHA,
    )
    ledger.settle(
        reservation,
        status="succeeded",
        usage={"total_tokens": 1},
        estimated_list_price_cny=0.000001,
        http_status=200,
    )
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.53)
    assert summary.stage_accounted_cny == pytest.approx(0.5)
    assert summary.remaining_cny == pytest.approx(9.47)
    assert summary.success_estimated_list_price_cny == pytest.approx(0.000001)
    assert summary.provider_billed_cny is None


def test_old_failed_and_orphan_results_stay_conservative(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    failed = ledger.reserve(
        kind=KIND_RERANK,
        provider="bailian",
        model=RERANK_MODEL,
        max_cny=0.5,
        request_sha256=REQ_SHA,
    )
    ledger.settle(failed, status="failed", error_code="RERANK_UNAVAILABLE")
    orphan_id = "orphan-" + "0" * 32
    ledger._append(  # 探针：模拟没有 reserved 的孤立 result（旧语义必须保守计入）
        {
            "event": "result",
            "reservation_id": orphan_id,
            "stage": "S1-DEV",
            "status": "failed",
            "conservative_charge_cny": 0.004,
            "estimated_list_price_cny": 0.0,
        }
    )
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.03 + 0.5 + 0.004)
    assert summary.stage_accounted_cny == pytest.approx(0.504)
    assert summary.reservation_count == 1
    assert summary.result_count == 2


def test_new_unsettled_reservation_keeps_full_amount(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.03 + CHAT_RESERVE)
    assert summary.stage_accounted_cny == pytest.approx(CHAT_RESERVE)
    assert summary.remaining_cny == pytest.approx(10.0 - 0.03 - CHAT_RESERVE)
    assert summary.result_count == 0


def test_legacy_reservation_rejects_new_evidence_and_keeps_full(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = ledger.reserve(
        kind=KIND_EMBEDDING,
        provider="bailian",
        model=EMBEDDING_MODEL,
        max_cny=0.5,
        request_sha256=REQ_SHA,
    )
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=total_evidence(KIND_EMBEDDING, 4000))
    assert caught.value.reason == "legacy_reservation_without_policy"
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.53)
    assert summary.stage_accounted_cny == pytest.approx(0.5)
    # 追加的是保守 unknown result，不是释放；再次结算被拒（不会二次释放）。
    with pytest.raises(BudgetLedgerInvalid):
        ledger.settle_usage(reservation, evidence=total_evidence(KIND_EMBEDDING, 4000))
    assert len([event for event in read_events(ledger) if event["event"] == "result"]) == 1


def test_new_reservation_with_old_settle_keeps_full(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    ledger.settle(
        reservation,
        status="succeeded",
        usage=chat_usage(),
        estimated_list_price_cny=0.000001,
        http_status=200,
    )
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.03 + CHAT_RESERVE)
    assert summary.success_estimated_list_price_cny == pytest.approx(0.000001)


# ---------------------------------------------------------------- 合法释放


def test_chat_success_releases_only_unused_reserve(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    decision = ledger.settle_usage(
        reservation,
        evidence=chat_evidence(),
        request_id="req-chat-1",
        elapsed_seconds=0.25,
        dimensions=(1024,),
    )
    assert decision.accepted is True
    assert decision.stop_required is False
    assert decision.boundary_anomaly is False
    assert float(decision.charge_cny) == pytest.approx(0.0036)  # (1000*2+200*8)/1e6
    assert float(decision.release_cny) == pytest.approx(CHAT_RESERVE - 0.0036)

    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.03 + 0.0036)
    assert summary.stage_accounted_cny == pytest.approx(0.0036)
    assert summary.success_estimated_list_price_cny == pytest.approx(0.0036)
    assert summary.provider_billed_cny is None
    assert summary.reservation_count == 1
    assert summary.result_count == 1

    events = read_events(ledger)
    assert [event["event"] for event in events] == ["historical_import", "reserved", "result"]
    reserved = events[1]
    assert reserved["reserve_cny"] == pytest.approx(CHAT_RESERVE)  # 原额仍可审计
    assert reserved["settlement_policy"]["version"] == "usage-conservative-v1"
    result = events[2]
    assert result["status"] == "succeeded"
    assert result["provider_billed_cny"] is None
    assert result["conservative_charge_cny"] == pytest.approx(0.0036)
    assert result["settlement"]["usage"]["prompt_tokens"] == 1000
    assert not any(event["event"] in ("refund", "release") for event in events)


def test_embedding_releases_from_total_tokens_only(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(
        ledger, kind=KIND_EMBEDDING, amount=EMBEDDING_RESERVE
    )
    # 官方 text-embedding-v4 只返回 total_tokens：不得强制 prompt_tokens。
    evidence = UsageEvidence(
        kind=KIND_EMBEDDING,
        provider="bailian",
        model=EMBEDDING_MODEL,
        host="dashscope.aliyuncs.com",
        region="cn-beijing",
        pricing_source=EMBEDDING_POLICY.pricing_source,
        request_sha256=REQ_SHA,
        http_status=200,
        output_valid=True,
        usage={"total_tokens": 4096},
    )
    decision = ledger.settle_usage(reservation, evidence=evidence)
    assert decision.accepted is True
    assert float(decision.charge_cny) == pytest.approx(0.002048)  # 4096*0.5/1e6
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.032048)
    assert summary.stage_accounted_cny == pytest.approx(0.002048)


def test_rerank_releases_from_total_tokens_only(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_RERANK, amount=RERANK_RESERVE)
    decision = ledger.settle_usage(
        reservation, evidence=total_evidence(KIND_RERANK, 6000)
    )
    assert float(decision.charge_cny) == pytest.approx(0.0048)  # 6000*0.8/1e6
    assert ledger.summary().accounted_cny == pytest.approx(0.0348)


def test_higher_conservative_rate_allowed(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    policy = build_policy(
        KIND_CHAT,
        model=CHAT_MODEL,
        input_price_per_million_cny=2.5,
        output_price_per_million_cny=10,
    )
    reservation = reserve_with_policy(
        ledger, kind=KIND_CHAT, amount=CHAT_RESERVE, policy=policy
    )
    decision = ledger.settle_usage(reservation, evidence=chat_evidence())
    assert float(decision.charge_cny) == pytest.approx((1000 * 2.5 + 200 * 10) / 1_000_000)


def test_provider_billed_stays_null_in_versioned_result(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    ledger.settle_usage(reservation, evidence=chat_evidence())
    result = [event for event in read_events(ledger) if event["event"] == "result"][0]
    assert result["provider_billed_cny"] is None
    assert ledger.summary().provider_billed_cny is None


# ---------------------------------------------------------------- chat 负向表


CHAT_NEGATIVE_CASES = [
    ("missing_hit", dict(usage=chat_usage(prompt_cache_hit_tokens=None)), "usage_not_int:prompt_cache_hit_tokens"),
    (
        "missing_total",
        dict(usage={key: value for key, value in chat_usage().items() if key != "total_tokens"}),
        "usage_missing:total_tokens",
    ),
    ("total_mismatch", dict(usage=chat_usage(total_tokens=1201)), "total_mismatch"),
    ("cache_split", dict(usage=chat_usage(prompt_cache_miss_tokens=401)), "cache_split_mismatch"),
    ("bool_prompt", dict(usage=chat_usage(prompt_tokens=True)), "usage_not_int:prompt_tokens"),
    ("float_completion", dict(usage=chat_usage(completion_tokens=200.0)), "usage_not_int:completion_tokens"),
    ("negative_miss", dict(usage=chat_usage(prompt_cache_miss_tokens=-1)), "usage_negative:prompt_cache_miss_tokens"),
    ("nan_prompt", dict(usage=chat_usage(prompt_tokens=float("nan"))), "usage_not_int:prompt_tokens"),
    ("reasoning_over", dict(usage=chat_usage(reasoning_tokens=201)), "reasoning_over_completion"),
    ("reasoning_bool", dict(usage=chat_usage(reasoning_tokens=True)), "usage_not_int:reasoning_tokens"),
    ("finish_length", dict(finish_reason="length"), "finish_reason_not_stop"),
    ("streamed", dict(streamed=True), "streamed_not_false"),
    ("http_500", dict(http_status=500), "http_status_invalid"),
    ("http_bool", dict(http_status=True), "http_status_invalid"),
    ("content_incomplete", dict(content_complete=False), "content_incomplete"),
    ("content_not_parsed", dict(content_parse_ok=False), "content_not_parsed"),
    (
        "over_cap_prompt",
        dict(
            usage=chat_usage(
                prompt_tokens=CHAT_PROMPT_TOKENS_CAP + 1,
                total_tokens=CHAT_PROMPT_TOKENS_CAP + 1 + 200,
                prompt_cache_miss_tokens=CHAT_PROMPT_TOKENS_CAP + 1 - 600,
            )
        ),
        "over_cap_prompt",
    ),
    (
        "over_cap_completion",
        dict(
            usage=chat_usage(
                completion_tokens=CHAT_COMPLETION_TOKENS_CAP + 1,
                total_tokens=1000 + CHAT_COMPLETION_TOKENS_CAP + 1,
            )
        ),
        "over_cap_completion",
    ),
    ("wrong_host", dict(host="api.deepseek.evil.test"), "binding_evidence_host_mismatch"),
    ("wrong_region", dict(region="mars"), "binding_evidence_region_mismatch"),
    (
        "wrong_source",
        dict(pricing_source="official-list-price/forged-v1"),
        "binding_evidence_pricing_source_mismatch",
    ),
    ("wrong_sha", dict(request_sha256=OTHER_SHA), "binding_request_sha256_mismatch"),
    ("unknown_usage_field", dict(usage=chat_usage(forged_tokens=1)), "unknown_usage_field"),
]


@pytest.mark.parametrize("name,overrides,expected_reason", CHAT_NEGATIVE_CASES, ids=[case[0] for case in CHAT_NEGATIVE_CASES])
def test_chat_invalid_evidence_never_releases(
    tmp_path: Path, name: str, overrides: dict[str, Any], expected_reason: str
) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=chat_evidence(**overrides))
    assert caught.value.reason == expected_reason, name
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.03 + CHAT_RESERVE), name
    assert summary.stage_accounted_cny == pytest.approx(CHAT_RESERVE), name
    results = [event for event in read_events(ledger) if event["event"] == "result"]
    assert len(results) == 1, name
    assert results[0]["status"] == "unknown", name
    assert results[0]["conservative_charge_cny"] == pytest.approx(CHAT_RESERVE), name
    # 被拒后再次结算仍是重复拒绝，绝不补释放。
    with pytest.raises(BudgetLedgerInvalid):
        ledger.settle_usage(reservation, evidence=chat_evidence())


def test_new_reservation_evidence_kind_provider_model_mismatch_rejected(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    with pytest.raises(BudgetLedgerInvalid):
        ledger.settle_usage(reservation, evidence=chat_evidence(model="deepseek-chat"))
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + CHAT_RESERVE)
    embedding = reserve_with_policy(ledger, kind=KIND_EMBEDDING, amount=EMBEDDING_RESERVE)
    with pytest.raises(BudgetLedgerInvalid):
        ledger.settle_usage(
            embedding,
            evidence=total_evidence(KIND_EMBEDDING, 4000, model="text-embedding-v3"),
        )
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + CHAT_RESERVE + EMBEDDING_RESERVE)


# ---------------------------------------------------------------- E/R 负向表


TOTAL_NEGATIVE_CASES = [
    ("embedding", dict(usage={}), "usage_missing:total_tokens"),
    ("embedding", dict(usage={"total_tokens": True}), "usage_not_int:total_tokens"),
    ("embedding", dict(usage={"total_tokens": 4096.0}), "usage_not_int:total_tokens"),
    ("embedding", dict(usage={"total_tokens": -1}), "usage_negative:total_tokens"),
    ("embedding", dict(usage={"total_tokens": 0}), "total_tokens_zero"),
    ("embedding", dict(usage={"total_tokens": 4097}), "over_cap_total"),
    ("rerank", dict(usage={"total_tokens": 6001}), "over_cap_total"),
    ("embedding", dict(usage={"total_tokens": 4096, "prompt_tokens": 5000}), "usage_contradiction"),
    ("embedding", dict(usage={"total_tokens": 100, "completion_tokens": 5}), "usage_contradiction"),
    ("embedding", dict(usage={"total_tokens": 100, "forged_tokens": 1}), "unknown_usage_field"),
    ("embedding", dict(output_valid=False), "output_invalid"),
    ("rerank", dict(http_status=429), "http_status_invalid"),
    ("embedding", dict(host="dashscope-forged.example"), "binding_evidence_host_mismatch"),
    ("embedding", dict(request_sha256=OTHER_SHA), "binding_request_sha256_mismatch"),
]


@pytest.mark.parametrize(
    "kind,overrides,expected_reason",
    [case[:3] for case in TOTAL_NEGATIVE_CASES],
    ids=[f"{case[0]}-{index}" for index, case in enumerate(TOTAL_NEGATIVE_CASES)],
)
def test_total_token_invalid_evidence_never_releases(
    tmp_path: Path, kind: str, overrides: dict[str, Any], expected_reason: str
) -> None:
    ledger = make_ledger(tmp_path)
    amount = EMBEDDING_RESERVE if kind == KIND_EMBEDDING else RERANK_RESERVE
    reservation = reserve_with_policy(ledger, kind=kind, amount=amount)
    base_total = 4096 if kind == KIND_EMBEDDING else 6000
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=total_evidence(kind, base_total, **overrides))
    assert caught.value.reason == expected_reason
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.03 + amount)
    assert summary.stage_accounted_cny == pytest.approx(amount)


def test_extra_usage_never_overrides_total(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_EMBEDDING, amount=EMBEDDING_RESERVE)
    # prompt_tokens 只作一致性校验；即使出现，计价仍按 total_tokens=4096。
    evidence = total_evidence(
        KIND_EMBEDDING, 4096, usage={"total_tokens": 4096, "prompt_tokens": 4096}
    )
    decision = ledger.settle_usage(reservation, evidence=evidence)
    assert float(decision.charge_cny) == pytest.approx(0.002048)


# ---------------------------------------------------------------- policy 校验


def test_policy_rate_floor_rejected() -> None:
    with pytest.raises(SettlementPolicyError):
        build_policy(KIND_CHAT, model=CHAT_MODEL, input_price_per_million_cny=1.99)
    with pytest.raises(SettlementPolicyError):
        build_policy(KIND_CHAT, model=CHAT_MODEL, output_price_per_million_cny=7.99)
    with pytest.raises(SettlementPolicyError):
        build_policy(KIND_EMBEDDING, model=EMBEDDING_MODEL, unit_price_per_million_cny=0.49)
    with pytest.raises(SettlementPolicyError):
        build_policy(KIND_RERANK, model=RERANK_MODEL, unit_price_per_million_cny=0.79)


def test_policy_unknown_sources_rejected() -> None:
    with pytest.raises(SettlementPolicyError):
        build_policy(KIND_CHAT, model="deepseek-chat")
    with pytest.raises(SettlementPolicyError):
        build_policy(KIND_CHAT, model=CHAT_MODEL, host="api.deepseek.evil.test")
    with pytest.raises(SettlementPolicyError):
        build_policy(KIND_RERANK, model="gte-rerank-v1")
    with pytest.raises(SettlementPolicyError):
        build_policy("ocr", model="ocr-general")  # OCR 不在 J1 范围


def test_policy_snapshot_roundtrip_and_whitelist() -> None:
    for policy in (CHAT_POLICY, EMBEDDING_POLICY, RERANK_POLICY):
        snapshot = policy_to_snapshot(policy)
        assert json.loads(json.dumps(snapshot, ensure_ascii=False)) == snapshot
        rebuilt = policy_from_snapshot(snapshot)
        assert rebuilt == policy
        assert set(snapshot) == {
            "schema_version",
            "version",
            "kind",
            "provider",
            "model",
            "host",
            "region",
            "pricing_source",
            "caps",
            "rates",
        }
        text = json.dumps(snapshot, ensure_ascii=False)
        for secret in ("Bearer", "sk-", "Authorization", "api_key", "password"):
            assert secret not in text


def test_policy_snapshot_tampering_fails_closed() -> None:
    snapshot = policy_to_snapshot(CHAT_POLICY)
    bigger_caps = json.loads(json.dumps(snapshot))
    bigger_caps["caps"]["prompt_tokens"] = 2048
    with pytest.raises(SettlementPolicyError):
        policy_from_snapshot(bigger_caps)

    lower_rates = json.loads(json.dumps(snapshot))
    lower_rates["rates"]["input_per_million_cny"] = "1.5"
    with pytest.raises(SettlementPolicyError):
        policy_from_snapshot(lower_rates)

    extra = json.loads(json.dumps(snapshot))
    extra["secret"] = "x"
    with pytest.raises(SettlementPolicyError):
        policy_from_snapshot(extra)

    unknown_version = json.loads(json.dumps(snapshot))
    unknown_version["version"] = "usage-conservative-v999"
    with pytest.raises(SettlementPolicyError):
        policy_from_snapshot(unknown_version)


def test_reserve_rejects_mismatched_policy(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    with pytest.raises(BudgetLedgerInvalid):
        ledger.reserve(
            kind=KIND_CHAT,
            provider="deepseek",
            model=CHAT_MODEL,
            max_cny=CHAT_RESERVE,
            request_sha256=REQ_SHA,
            settlement_policy=EMBEDDING_POLICY,
        )


def test_snapshot_persists_counts_without_generic_redaction(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = ledger.reserve(
        kind=KIND_CHAT,
        provider="deepseek",
        model=CHAT_MODEL,
        max_cny=CHAT_RESERVE,
        request_sha256=REQ_SHA,
        settlement_policy=CHAT_POLICY,
        metadata={"Authorization": "Bearer sk-should-be-masked", "api_key": "sk-raw"},
    )
    reserved = [event for event in read_events(ledger) if event["event"] == "reserved"][0]
    snapshot = reserved["settlement_policy"]
    # 明确白名单公共字段：计数不被通用 redactor 遮成 ***，也不含任何 secret。
    assert snapshot["caps"]["prompt_tokens"] == CHAT_PROMPT_TOKENS_CAP
    assert snapshot["caps"]["completion_tokens"] == CHAT_COMPLETION_TOKENS_CAP
    assert snapshot["rates"]["input_per_million_cny"] == "2"
    assert snapshot["rates"]["output_per_million_cny"] == "8"
    assert "***" not in json.dumps(snapshot, ensure_ascii=False)
    assert reserved["metadata"]["Authorization"] == "***"
    assert reserved["metadata"]["api_key"] == "***"
    assert reservation.reserve_cny == pytest.approx(CHAT_RESERVE)


# ---------------------------------------------------------------- 原子性 / 并发


def test_duplicate_settlement_rejected_and_replay_stable(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    ledger.settle_usage(reservation, evidence=chat_evidence())
    with pytest.raises(BudgetLedgerInvalid):
        ledger.settle_usage(reservation, evidence=chat_evidence())
    results = [event for event in read_events(ledger) if event["event"] == "result"]
    assert len(results) == 1
    first = ledger.summary().as_dict()
    second = ledger.summary().as_dict()
    assert first == second
    reopened = BudgetLedger(
        ledger.ledger_path, ledger.budget_json_path, stage="S1-DEV", stage_limit_cny=10.0, max_requests=1000
    )
    assert reopened.summary().as_dict() == first


def test_restart_reopen_unsettled_keeps_full_then_releases(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    reopened = BudgetLedger(
        ledger.ledger_path, ledger.budget_json_path, stage="S1-DEV", stage_limit_cny=10.0, max_requests=1000
    )
    assert reopened.summary().accounted_cny == pytest.approx(0.03 + CHAT_RESERVE)
    # 重开后仍能凭同一 reservation / 合法证据结算，且释放只在同一锁内发生一次。
    decision = reopened.settle_usage(reservation, evidence=chat_evidence())
    assert float(decision.charge_cny) == pytest.approx(0.0036)
    assert reopened.summary().accounted_cny == pytest.approx(0.0336)


def _settle_worker(
    ledger_path: str,
    budget_path: str,
    reservation: Reservation,
    evidence: UsageEvidence,
    results: Any,
) -> None:
    try:
        ledger = BudgetLedger(
            ledger_path, budget_path, stage="S1-DEV", stage_limit_cny=10.0, max_requests=1000
        )
        decision = ledger.settle_usage(reservation, evidence=evidence)
        results.put(("ok", float(decision.charge_cny)))
    except BudgetLedgerInvalid:
        results.put(("duplicate", 0.0))
    except Exception as exc:  # noqa: BLE001 - 子进程汇总意外，避免静默
        results.put(("error", type(exc).__name__))


def test_cross_process_double_settlement_only_one_result(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    processes = [
        context.Process(
            target=_settle_worker,
            args=(
                str(ledger.ledger_path),
                str(ledger.budget_json_path),
                reservation,
                chat_evidence(),
                results,
            ),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=120)
        assert process.exitcode == 0
    outcomes = sorted(results.get(timeout=10) for _ in processes)
    assert [status for status, _value in outcomes].count("ok") == 1
    assert [status for status, _value in outcomes].count("duplicate") == 1
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.0336)
    assert summary.result_count == 1


def test_release_then_new_reserve_same_lock_accounting(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path, total_limit_cny=10.0, stage_limit_cny=10.0, max_requests=1000)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    ledger.settle_usage(reservation, evidence=chat_evidence())
    # 释放后可再预留 9.96：0.03 + 0.0036 + 9.96 < 10；同锁重算必须正确。
    second = ledger.reserve(
        kind=KIND_EMBEDDING,
        provider="bailian",
        model=EMBEDDING_MODEL,
        max_cny=9.96,
        request_sha256=OTHER_SHA,
    )
    assert second.reserve_cny == pytest.approx(9.96)
    with pytest.raises(BudgetExceeded):
        ledger.reserve(
            kind=KIND_EMBEDDING,
            provider="bailian",
            model=EMBEDDING_MODEL,
            max_cny=0.01,
            request_sha256="c" * 64,
        )
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.03 + 0.0036 + 9.96)
    assert summary.stage_accounted_cny == pytest.approx(0.0036 + 9.96)


def test_request_count_not_reset_by_settlement(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path, max_requests=2)
    first = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    ledger.settle_usage(first, evidence=chat_evidence())
    reserve_with_policy(ledger, kind=KIND_EMBEDDING, amount=EMBEDDING_RESERVE)
    with pytest.raises(RequestLimitExceeded):
        reserve_with_policy(ledger, kind=KIND_RERANK, amount=RERANK_RESERVE)
    summary = ledger.summary()
    assert summary.reservation_count == 2
    assert summary.result_count == 1


# ---------------------------------------------------------------- 边界 / fail closed


def test_recomputed_charge_above_reserve_kept_not_masked(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=0.001)
    with pytest.raises(SettlementBoundaryAnomaly):
        ledger.settle_usage(reservation, evidence=chat_evidence())
    summary = ledger.summary()
    # 不用 min 掩盖：按重算的 0.0036（> 预留 0.001）入账，绝不退回预算。
    assert summary.accounted_cny == pytest.approx(0.03 + 0.0036)
    result = [event for event in read_events(ledger) if event["event"] == "result"][0]
    assert result["boundary_anomaly"] is True
    assert result["conservative_charge_cny"] == pytest.approx(0.0036)
    # 重放同样接受更高保守额，不静默改回预留值。
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.0036)


def test_tampered_low_charge_fails_closed(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    ledger.settle_usage(reservation, evidence=chat_evidence())
    events = read_events(ledger)
    result = [event for event in events if event["event"] == "result"][0]
    result["conservative_charge_cny"] = 0.000001  # 伪造低 charge
    rewrite_events(ledger, events)
    with pytest.raises(BudgetLedgerInvalid):
        ledger.summary()


def test_tampered_settlement_declared_amount_fails_closed(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    ledger.settle_usage(reservation, evidence=chat_evidence())
    events = read_events(ledger)
    result = [event for event in events if event["event"] == "result"][0]
    result["settlement"]["recomputed_conservative_charge_cny"] = "0.0001"
    rewrite_events(ledger, events)
    with pytest.raises(BudgetLedgerInvalid):
        ledger.summary()


def test_unknown_policy_snapshot_fails_closed(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reserve_with_policy(ledger, kind=KIND_CHAT, amount=CHAT_RESERVE)
    events = read_events(ledger)
    reserved = [event for event in events if event["event"] == "reserved"][0]
    reserved["settlement_policy"]["version"] = "usage-conservative-v999"
    rewrite_events(ledger, events)
    with pytest.raises(BudgetLedgerInvalid):
        ledger.summary()


def test_orphan_versioned_result_fails_closed(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    ledger._append(
        {
            "event": "result",
            "reservation_id": "orphan-versioned",
            "stage": "S1-DEV",
            "kind": KIND_CHAT,
            "provider": "deepseek",
            "model": CHAT_MODEL,
            "status": "succeeded",
            "conservative_charge_cny": 0.000001,
            "estimated_list_price_cny": 0.000001,
            "settlement": {"version": "usage-conservative-v1"},
        }
    )
    with pytest.raises(BudgetLedgerInvalid):
        ledger.summary()
