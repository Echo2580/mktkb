"""S2-J1-R1（J1 独立验收 D-1 定点返工）：拒绝结算路径不得外泄 usage 原文。

背景（`S2-IA/S2-J1-report.md` D-1）：
未知 usage 字段名被拼入拒绝 reason，并在拒绝 result 的 ``usage`` 与 ``error_code``
原文持久化，可绕过白名单落盘凭据形态串。

本文件是**新增独立定向回归**，只覆盖 D-1 修复面与必要边界（全部隔离账本、Mock-only）：
1. chat / embedding / rerank 未知 usage 键（键名本身就是合成 secret 形态）不得进入
   reason、``error_code``、``settlement_rejected.reason``、事件 ``usage`` 或异常文本；
2. 校验先失败（http_status）等**所有拒绝路径**同样按白名单过滤持久化 usage；
3. 嵌套结构、允许键的非计数值、非 Mapping usage、非字符串键、legacy 预留、
   非法 policy 快照等拒绝路径不持久化未知键/值，且仍产生稳定拒绝码与全额占用；
4. 正常白名单成功结算与旧规则（无版本 settle）行为不变。

所有 secret 均为**人工合成测试串，不是真实凭据**。测试不导入 app/provider/support，
账本全部在 pytest ``tmp_path`` 隔离；socket 熔断由本轮 pytest 插件
``socket_guard_plugin`` 在进程级提供，不在本文件内修改全局网络。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from mktkb.rag.budget import BudgetLedger, SettlementNotReleasable
from mktkb.rag.errors import BudgetLedgerInvalid
from mktkb.rag.settlement_policy import (
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_RERANK,
    UsageEvidence,
    build_policy,
    evaluate_settlement,
)

REQ_SHA = "d" * 64
CHAT_MODEL = "deepseek-flash"
EMBEDDING_MODEL = "text-embedding-v4"
RERANK_MODEL = "gte-rerank-v2"
CHAT_RESERVE = 2.103552
EMBEDDING_RESERVE = 0.04096
RERANK_RESERVE = 0.024

CHAT_POLICY = build_policy(KIND_CHAT, model=CHAT_MODEL)
EMBEDDING_POLICY = build_policy(KIND_EMBEDDING, model=EMBEDDING_MODEL)
RERANK_POLICY = build_policy(KIND_RERANK, model=RERANK_MODEL)

# 人工合成测试串（不是真实凭据）；故意采用 secret 形态与已知 redactor 模式。
SECRET_KEY = "api_key=sk-SYNTHETIC-R1-NOT-REAL-00000000"
SECRET_VALUE = "sk-SYNTHETIC-R1-NOT-REAL-11111111"
SECRET_NESTED = "SYNTHETIC-R1-NESTED-NOT-REAL-22222222"
SYNTHETIC_MARKERS = (SECRET_KEY, SECRET_VALUE, SECRET_NESTED)

CHAT_USAGE_KEYS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
        "reasoning_tokens",
    }
)
TOTAL_USAGE_KEYS = frozenset(
    {
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    }
)
STABLE_CODE = re.compile(r"^[a-z0-9_]+(:[a-z0-9_]+)?$")


# ---------------------------------------------------------------- 装配与证据


def make_ledger(tmp_path: Path) -> BudgetLedger:
    budget_path = tmp_path / "budget.json"
    budget_path.write_text(
        json.dumps({"limit_cny": 10.0, "stages": {"S1-DEV": 10.0}}, ensure_ascii=False),
        encoding="utf-8",
    )
    ledger_path = tmp_path / "live-ledger.jsonl"
    ledger_path.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": 0.03}) + "\n",
        encoding="utf-8",
    )
    return BudgetLedger(
        ledger_path,
        budget_path,
        stage="S1-DEV",
        stage_limit_cny=10.0,
        max_requests=1000,
    )


def reserve_with_policy(ledger: BudgetLedger, kind: str, amount: float) -> Any:
    if kind == KIND_CHAT:
        provider, model, policy = "deepseek", CHAT_MODEL, CHAT_POLICY
    elif kind == KIND_EMBEDDING:
        provider, model, policy = "bailian", EMBEDDING_MODEL, EMBEDDING_POLICY
    else:
        provider, model, policy = "bailian", RERANK_MODEL, RERANK_POLICY
    return ledger.reserve(
        kind=kind,
        provider=provider,
        model=model,
        max_cny=amount,
        request_sha256=REQ_SHA,
        settlement_policy=policy,
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


def total_evidence(kind: str, total: int, **overrides: Any) -> UsageEvidence:
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
        "usage": {"total_tokens": total},
    }
    values.update(overrides)
    return UsageEvidence(**values)


def read_events(ledger: BudgetLedger) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in ledger.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def ledger_text(ledger: BudgetLedger) -> str:
    return ledger.ledger_path.read_text(encoding="utf-8")


def assert_no_synthetic_marker(text: Any) -> None:
    for marker in SYNTHETIC_MARKERS:
        assert marker not in str(text), f"合成 secret 形态串出现在禁止落盘通道：{marker}"


def allowed_keys(kind: str) -> frozenset[str]:
    return CHAT_USAGE_KEYS if kind == KIND_CHAT else TOTAL_USAGE_KEYS


def last_result(ledger: BudgetLedger) -> dict[str, Any]:
    results = [event for event in read_events(ledger) if event.get("event") == "result"]
    assert len(results) == 1
    return results[0]


def assert_rejected_result_shape(
    ledger: BudgetLedger,
    *,
    kind: str,
    reserve_cny: float,
    expected_reason: str,
) -> dict[str, Any]:
    result = last_result(ledger)
    assert result["status"] == "unknown"
    assert result["conservative_charge_cny"] == pytest.approx(round(reserve_cny, 8))
    assert result["provider_billed_cny"] is None
    assert result["error_code"] == f"SETTLEMENT_NOT_RELEASABLE:{expected_reason}"
    assert result["settlement_rejected"]["reason"] == expected_reason
    # 拒绝事件的 usage 只允许该 kind 白名单字段；未知键/非计数值一律不落盘。
    usage = result["usage"] or {}
    assert set(usage) <= allowed_keys(kind), usage
    assert_no_synthetic_marker(ledger_text(ledger))
    assert_no_synthetic_marker(result)
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.03 + reserve_cny)
    assert summary.stage_accounted_cny == pytest.approx(reserve_cny)
    return result


# ------------------------------------------------- 未知键：chat / embedding / rerank


@pytest.mark.parametrize(
    "kind,model,amount,base_total",
    [
        (KIND_CHAT, CHAT_MODEL, CHAT_RESERVE, None),
        (KIND_EMBEDDING, EMBEDDING_MODEL, EMBEDDING_RESERVE, 4096),
        (KIND_RERANK, RERANK_MODEL, RERANK_RESERVE, 6000),
    ],
    ids=["chat", "embedding", "rerank"],
)
def test_unknown_usage_key_never_persisted_or_reasoned(
    tmp_path: Path, kind: str, model: str, amount: float, base_total: int | None
) -> None:
    """D-1 主缺陷：未知键名（含合成 secret 形态）不得进入 reason/error_code/usage/日志。"""
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, kind, amount)
    if kind == KIND_CHAT:
        evidence = chat_evidence(usage=chat_usage(**{SECRET_KEY: 1}))
    else:
        assert base_total is not None
        evidence = total_evidence(
            kind, base_total, usage={"total_tokens": base_total, SECRET_KEY: 1}
        )
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=evidence)
    assert caught.value.reason == "unknown_usage_field"
    assert STABLE_CODE.match(str(caught.value.reason)), caught.value.reason
    assert_no_synthetic_marker(str(caught.value))
    result = assert_rejected_result_shape(
        ledger, kind=kind, reserve_cny=amount, expected_reason="unknown_usage_field"
    )
    assert SECRET_KEY not in json.dumps(result, ensure_ascii=False)
    # 拒绝后仍不可二次结算/释放。
    with pytest.raises(BudgetLedgerInvalid):
        ledger.settle_usage(reservation, evidence=evidence)


def test_http_failure_before_usage_check_still_filters_usage(tmp_path: Path) -> None:
    """http_status 校验先失败：usage 尚未被校验，仍不得原文落盘未知键。"""
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, KIND_CHAT, CHAT_RESERVE)
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(
            reservation,
            evidence=chat_evidence(http_status=500, usage=chat_usage(**{SECRET_KEY: 1})),
        )
    assert caught.value.reason == "http_status_invalid"
    result = assert_rejected_result_shape(
        ledger, kind=KIND_CHAT, reserve_cny=CHAT_RESERVE, expected_reason="http_status_invalid"
    )
    assert SECRET_KEY not in json.dumps(result, ensure_ascii=False)


def test_unknown_usage_key_with_nested_value_not_persisted(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, KIND_CHAT, CHAT_RESERVE)
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(
            reservation,
            evidence=chat_evidence(usage=chat_usage(**{SECRET_KEY: {"nested": SECRET_NESTED}})),
        )
    assert caught.value.reason == "unknown_usage_field"
    assert_rejected_result_shape(
        ledger, kind=KIND_CHAT, reserve_cny=CHAT_RESERVE, expected_reason="unknown_usage_field"
    )


def test_non_mapping_usage_rejects_cleanly_without_persisting_value(tmp_path: Path) -> None:
    """usage 不是 Mapping：必须稳定拒绝 + 追加保守 result，而不是未捕获 ValueError。"""
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, KIND_CHAT, CHAT_RESERVE)
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=chat_evidence(usage=SECRET_VALUE))
    assert caught.value.reason == "usage_not_mapping"
    assert_no_synthetic_marker(str(caught.value))
    result = assert_rejected_result_shape(
        ledger, kind=KIND_CHAT, reserve_cny=CHAT_RESERVE, expected_reason="usage_not_mapping"
    )
    assert result["usage"] is None


def test_non_string_usage_key_not_rewritten_into_ledger(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, KIND_CHAT, CHAT_RESERVE)
    usage = chat_usage()
    usage[1] = 5
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=chat_evidence(usage=usage))
    assert caught.value.reason == "usage_key_not_string"
    result = assert_rejected_result_shape(
        ledger, kind=KIND_CHAT, reserve_cny=CHAT_RESERVE, expected_reason="usage_key_not_string"
    )
    assert "1" not in (result["usage"] or {})


def test_allowed_key_non_count_value_not_persisted(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, KIND_CHAT, CHAT_RESERVE)
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(
            reservation,
            evidence=chat_evidence(usage=chat_usage(prompt_tokens={"nested": SECRET_NESTED})),
        )
    assert caught.value.reason == "usage_not_int:prompt_tokens"
    result = assert_rejected_result_shape(
        ledger, kind=KIND_CHAT, reserve_cny=CHAT_RESERVE, expected_reason="usage_not_int:prompt_tokens"
    )
    assert "prompt_tokens" not in (result["usage"] or {})


def test_secret_shaped_value_under_allowed_key_not_persisted(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, KIND_CHAT, CHAT_RESERVE)
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(
            reservation,
            evidence=chat_evidence(usage=chat_usage(prompt_cache_hit_tokens=SECRET_VALUE)),
        )
    assert caught.value.reason == "usage_not_int:prompt_cache_hit_tokens"
    assert_rejected_result_shape(
        ledger,
        kind=KIND_CHAT,
        reserve_cny=CHAT_RESERVE,
        expected_reason="usage_not_int:prompt_cache_hit_tokens",
    )


# ------------------------------------------- 其他拒绝路径：legacy / 非法 policy 快照


def test_legacy_reservation_rejection_filters_usage(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = ledger.reserve(
        kind=KIND_EMBEDDING,
        provider="bailian",
        model=EMBEDDING_MODEL,
        max_cny=0.5,
        request_sha256=REQ_SHA,
    )
    evidence = total_evidence(
        KIND_EMBEDDING, 4000, usage={"total_tokens": 4000, SECRET_KEY: 1}
    )
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=evidence)
    assert caught.value.reason == "legacy_reservation_without_policy"
    assert_rejected_result_shape(
        ledger,
        kind=KIND_EMBEDDING,
        reserve_cny=0.5,
        expected_reason="legacy_reservation_without_policy",
    )


def test_invalid_policy_snapshot_rejection_filters_usage(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, KIND_CHAT, CHAT_RESERVE)
    events = read_events(ledger)
    for event in events:
        if event.get("event") == "reserved":
            event["settlement_policy"]["extra_secret_field"] = "forged"
    ledger.ledger_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(
            reservation, evidence=chat_evidence(usage=chat_usage(**{SECRET_KEY: 1}))
        )
    assert caught.value.reason == "invalid_policy_snapshot"
    result = last_result(ledger)
    assert result["status"] == "unknown"
    assert result["error_code"] == "SETTLEMENT_NOT_RELEASABLE:invalid_policy_snapshot"
    assert set(result["usage"] or {}) <= CHAT_USAGE_KEYS
    assert_no_synthetic_marker(ledger_text(ledger))
    # 非法快照必须 fail closed：summary 重放拒绝，不能凭保守 result 继续信任账本。
    with pytest.raises(BudgetLedgerInvalid):
        ledger.summary()


# ------------------------------------------------------ 直接 policy 决策与白名单件


def test_evaluate_settlement_rejection_usage_fields_sanitized() -> None:
    policy = CHAT_POLICY
    reserved = {
        "kind": KIND_CHAT,
        "provider": "deepseek",
        "model": CHAT_MODEL,
        "request_sha256": REQ_SHA,
    }
    evidence = chat_evidence(usage=chat_usage(**{SECRET_KEY: 1}))
    decision = evaluate_settlement(
        policy, reserved=reserved, evidence=evidence, reserve_cny=CHAT_RESERVE
    )
    assert decision.accepted is False
    assert decision.reason == "unknown_usage_field"
    assert STABLE_CODE.match(str(decision.reason))
    assert set(decision.usage_fields) <= CHAT_USAGE_KEYS
    assert SECRET_KEY not in json.dumps(dict(decision.usage_fields), ensure_ascii=False)
    assert_no_synthetic_marker(str(decision.reason))


def test_sanitize_usage_for_kind_whitelist_and_value_bounds() -> None:
    # 该 helper 属于 D-1 修复新增的公开过滤入口；在函数内导入，
    # 让返工前的收集阶段仍能运行其余行为用例（改前行为失败证据见本轮日志）。
    from mktkb.rag.settlement_policy import sanitize_usage_for_kind

    usage = {
        "prompt_tokens": 12,
        "total_tokens": 34,
        "completion_tokens": True,  # bool 不算计数
        "prompt_cache_hit_tokens": -1,  # 负数不落盘
        "prompt_cache_miss_tokens": 1.5,  # 浮点不落盘
        SECRET_KEY: 1,  # 未知键（含 secret 形态）不落盘
        "nested": {"secret": SECRET_NESTED},  # 嵌套不落盘
    }
    # chat 白名单包含 prompt/completion/total/cache 计数；此处预期的合法计数只有
    # prompt_tokens 与 total_tokens（其余为 bool/负/浮点/未知键/嵌套，均须丢弃）。
    assert sanitize_usage_for_kind(KIND_CHAT, usage) == {
        "prompt_tokens": 12,
        "total_tokens": 34,
    }
    assert sanitize_usage_for_kind(KIND_EMBEDDING, usage) == {
        "prompt_tokens": 12,
        "total_tokens": 34,
    }
    assert sanitize_usage_for_kind("ocr", usage) == {}
    assert sanitize_usage_for_kind(KIND_RERANK, "not-a-mapping") == {}


# -------------------------------------------------- 正常白名单 / 旧规则必要回归


def test_normal_accepted_settlement_keeps_whitelist_and_release(tmp_path: Path) -> None:
    ledger = make_ledger(tmp_path)
    reservation = reserve_with_policy(ledger, KIND_CHAT, CHAT_RESERVE)
    decision = ledger.settle_usage(reservation, evidence=chat_evidence())
    assert decision.accepted is True
    assert float(decision.charge_cny) == pytest.approx(0.0036)
    assert float(decision.release_cny) == pytest.approx(CHAT_RESERVE - 0.0036)
    result = last_result(ledger)
    expected_usage = sorted(CHAT_USAGE_KEYS - {"reasoning_tokens"})
    assert sorted(result["usage"]) == expected_usage
    assert sorted(result["settlement"]["usage"]) == expected_usage
    assert result["error_code"] is None
    assert "settlement_rejected" not in result
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.0036)
    assert_no_synthetic_marker(ledger_text(ledger))


def test_old_settle_path_unchanged_full_amount(tmp_path: Path) -> None:
    """旧规则（无版本 settle）不因 succeeded+极小 usage 释放，语义与 D-1 前一致。"""
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
    assert ledger.summary().accounted_cny == pytest.approx(0.53)
    assert ledger.summary().stage_accounted_cny == pytest.approx(0.5)
    result = last_result(ledger)
    assert result["conservative_charge_cny"] == pytest.approx(0.5)
    assert result["usage"] == {"total_tokens": 1}
