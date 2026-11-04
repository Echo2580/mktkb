"""S2-J1-R2 定点返工：F-1 异常文本回显 + F-2 拒绝 reason 白名单兜底 定向回归。

背景（`S2-IA/S2-J1-R1-report.md` §5）：
- F-1：非法预留 policy 快照被 ``settle_usage`` / ``summary`` 拒绝时，异常文本把快照里的
  ``version``/``model`` 等不可信原文回显出来（可能含凭据形态串）；
- F-2：``_rejected_result_event`` 的 docstring 声称 reason 有白名单兜底，实现却直接
  f-string 拼接，任意 reason 会原文进入 ``error_code``/``settlement_rejected.reason``。

本文件只覆盖这两项的定点修复面与必要回归（全部隔离账本、Mock-only）：
1. 非法快照的 version/model/kind/schema_version/rates/caps/未知字段等拒绝路径，经
   ``settle_usage``、``summary``、``policy_from_snapshot``、重放静态入口拒绝时，异常文本
   （含嵌套异常链）不回显快照原文；reason/error_code 仍是稳定码；仍 fail closed、全额保留、
   不改写已有账本事件；已储存在账本里的旧数据不被擦除（只保证新写通道不回显）。
2. 拒绝 reason 走显式白名单：合法稳定码与受控参数化后缀原样保留；任意/非白名单输入
   （含合成 secret 形态串、非字符串、空串、超长串）一律兜底为
   ``UNCLASSIFIED_REJECTION_REASON``，不进入 ``error_code``、事件或异常文本。
3. D-1 拒绝白名单、正常成功结算、旧规则全额、重复结算、summary 重放不被动摇。

所有 secret 均为**人工合成测试串，不是真实凭据**；测试不导入 support；账本全部在 pytest
``tmp_path`` 隔离；socket 熔断/T09 核验/资源门由本轮 pytest 插件 ``socket_guard_plugin``
在进程级提供。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import mktkb.rag.budget as budget_module
from mktkb.rag.budget import BudgetLedger, SettlementNotReleasable
from mktkb.rag.errors import BudgetLedgerInvalid
from mktkb.rag.settlement_policy import (
    KIND_CHAT,
    KIND_EMBEDDING,
    UNCLASSIFIED_REJECTION_REASON,
    SettlementDecision,
    SettlementPolicyError,
    UsageEvidence,
    build_policy,
    policy_from_snapshot,
    policy_to_snapshot,
    sanitize_settlement_reason,
)

REQ_SHA = "d" * 64
CHAT_MODEL = "deepseek-flash"
EMBEDDING_MODEL = "text-embedding-v4"
CHAT_RESERVE = 2.103552
EMBEDDING_RESERVE = 0.04096
HIST_CNY = 0.03
FALLBACK = UNCLASSIFIED_REJECTION_REASON

CHAT_POLICY = build_policy(KIND_CHAT, model=CHAT_MODEL)
EMBEDDING_POLICY = build_policy(KIND_EMBEDDING, model=EMBEDDING_MODEL)

# 人工合成测试串（不是真实凭据）；故意采用 secret 形态与已知 redactor 模式。
MARKER = "J1R2PYTSYNTH"
S_VERSION = f"usage-conservative-{MARKER}VERSION01"
S_MODEL = f"deepseek-{MARKER}MODEL02"
S_KIND = f"{MARKER}KIND03"
S_KEY = f"api_key=sk-{MARKER}KEYNAME04"
S_VALUE = f"sk-{MARKER}VALUE05"
S_SCHEMA = f"{MARKER}SCHEMA06"
S_REASON = f"api_key=sk-{MARKER}REASON07"
SENTINELS = (MARKER, S_VERSION, S_MODEL, S_KIND, S_KEY, S_VALUE, S_SCHEMA, S_REASON)

GOOD_CHAT_USAGE: dict[str, Any] = {
    "prompt_tokens": 1000,
    "completion_tokens": 200,
    "total_tokens": 1200,
    "prompt_cache_hit_tokens": 600,
    "prompt_cache_miss_tokens": 400,
}
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
LEGIT_REASON_CODES = (
    "usage_not_mapping",
    "usage_key_not_string",
    "unknown_usage_field",
    "total_mismatch",
    "cache_split_mismatch",
    "reasoning_over_completion",
    "over_cap_prompt",
    "over_cap_completion",
    "http_status_invalid",
    "streamed_not_false",
    "finish_reason_not_stop",
    "content_incomplete",
    "content_not_parsed",
    "output_invalid",
    "total_tokens_zero",
    "usage_contradiction",
    "over_cap_total",
    "binding_kind_mismatch",
    "binding_provider_mismatch",
    "binding_model_mismatch",
    "binding_request_sha256_mismatch",
    "binding_evidence_kind_mismatch",
    "binding_evidence_provider_mismatch",
    "binding_evidence_model_mismatch",
    "binding_evidence_host_mismatch",
    "binding_evidence_region_mismatch",
    "binding_evidence_pricing_source_mismatch",
    "reservation_request_sha256_missing",
    "legacy_reservation_without_policy",
    "invalid_policy_snapshot",
)
STABLE_CODE = re.compile(r"^[a-z0-9_]+(:[a-z0-9_]+)?$")


# ---------------------------------------------------------------- 装配与工具


def make_ledger(tmp_path: Path) -> BudgetLedger:
    budget_path = tmp_path / "budget.json"
    budget_path.write_text(
        json.dumps({"limit_cny": 10.0, "stages": {"J1-R2": 10.0}}, ensure_ascii=False),
        encoding="utf-8",
    )
    ledger_path = tmp_path / "live-ledger.jsonl"
    ledger_path.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": HIST_CNY}) + "\n",
        encoding="utf-8",
    )
    return BudgetLedger(
        ledger_path,
        budget_path,
        stage="J1-R2",
        stage_limit_cny=10.0,
        max_requests=1000,
    )


def reserve_chat(ledger: BudgetLedger) -> Any:
    return ledger.reserve(
        kind=KIND_CHAT,
        provider="deepseek",
        model=CHAT_MODEL,
        max_cny=CHAT_RESERVE,
        request_sha256=REQ_SHA,
        settlement_policy=CHAT_POLICY,
    )


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
        "usage": dict(GOOD_CHAT_USAGE),
    }
    values.update(overrides)
    return UsageEvidence(**values)


def read_events(ledger: BudgetLedger) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in ledger.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_events(ledger: BudgetLedger, events: list[dict[str, Any]]) -> None:
    ledger.ledger_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def tamper_snapshot(ledger: BudgetLedger, mutate) -> None:  # noqa: ANN001
    events = read_events(ledger)
    for event in events:
        if event.get("event") == "reserved":
            mutate(event["settlement_policy"])
    write_events(ledger, events)


def reserved_line_text(ledger: BudgetLedger) -> str:
    for line in ledger.ledger_path.read_text(encoding="utf-8").splitlines():
        if '"event":"reserved"' in line or '"event": "reserved"' in line:
            return line
    raise AssertionError("no reserved line")


def result_events(ledger: BudgetLedger, reservation_id: str | None = None) -> list[dict[str, Any]]:
    rows = [event for event in read_events(ledger) if event.get("event") == "result"]
    if reservation_id is not None:
        rows = [event for event in rows if event.get("reservation_id") == reservation_id]
    return rows


def assert_no_synthetic_marker(value: Any) -> None:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    for marker in SENTINELS:
        assert marker not in text, f"合成 secret 形态串出现在禁止通道：{marker}"
    for pattern in (
        re.compile(r"api[_-]?key\s*[:=]", re.IGNORECASE),
        re.compile(r"authorization\s*[:=]", re.IGNORECASE),
        re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    ):
        assert not pattern.search(text), f"凭据形态串出现在禁止通道：{pattern.pattern}"


def exception_texts(exc: BaseException) -> str:
    parts = [type(exc).__name__, str(exc), repr(exc)]
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current!r}")
        current = current.__cause__ or current.__context__
    return " || ".join(parts)


# --------------------------------------------------------------- F-1 定向


@pytest.mark.parametrize(
    "field,payload",
    [
        ("version", S_VERSION),
        ("model", S_MODEL),
        ("kind", S_KIND),
    ],
    ids=["version", "model", "kind"],
)
def test_invalid_snapshot_exception_text_does_not_echo_value(
    tmp_path: Path, field: str, payload: str
) -> None:
    """F-1 主缺陷：非法快照的 version/model/kind 原文不得进入结算/summary 异常文本。"""
    ledger = make_ledger(tmp_path)
    reservation = reserve_chat(ledger)
    tamper_snapshot(ledger, lambda snapshot: snapshot.__setitem__(field, payload))
    reserved_before = reserved_line_text(ledger)
    count_before = len(read_events(ledger))

    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=chat_evidence())
    assert caught.value.reason == "invalid_policy_snapshot"
    assert caught.value.conservative_charge_cny == pytest.approx(round(CHAT_RESERVE, 8))
    assert_no_synthetic_marker(exception_texts(caught.value))

    with pytest.raises(BudgetLedgerInvalid) as summary_caught:
        ledger.summary()
    assert_no_synthetic_marker(exception_texts(summary_caught.value))

    results = result_events(ledger, reservation.reservation_id)
    assert len(results) == 1
    event = results[0]
    assert event["status"] == "unknown"
    assert event["error_code"] == "SETTLEMENT_NOT_RELEASABLE:invalid_policy_snapshot"
    assert event["settlement_rejected"]["reason"] == "invalid_policy_snapshot"
    assert event["conservative_charge_cny"] == pytest.approx(round(CHAT_RESERVE, 8))
    assert_no_synthetic_marker(event)

    # 不修改/删除已有账本事件：reserved 行逐字节不变、只追加 1 条。
    assert reserved_line_text(ledger) == reserved_before
    assert len(read_events(ledger)) == count_before + 1
    # 如实声明：非法快照本就驻留在账本里，本轮不擦除既有旧数据，只拒绝新写通道回显。
    assert MARKER in ledger.ledger_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "mutate,label",
    [
        (lambda snapshot: snapshot.__setitem__("schema_version", S_SCHEMA), "schema_version"),
        (
            lambda snapshot: snapshot["rates"].__setitem__("input_per_million_cny", S_KEY),
            "rates",
        ),
        (lambda snapshot: snapshot["caps"].__setitem__("prompt_tokens", S_VALUE), "caps"),
        (lambda snapshot: snapshot.__setitem__(f"extra_{MARKER}", "forged"), "extra_field"),
    ],
    ids=["schema_version", "rates", "caps", "extra_field"],
)
def test_invalid_snapshot_other_fields_do_not_echo(tmp_path: Path, mutate, label: str) -> None:  # noqa: ANN001
    """F-1 其余快照字段/结构异常的异常文本同样不回显原文。"""
    ledger = make_ledger(tmp_path)
    reservation = reserve_chat(ledger)
    tamper_snapshot(ledger, mutate)
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=chat_evidence())
    assert caught.value.reason == "invalid_policy_snapshot"
    assert_no_synthetic_marker(exception_texts(caught.value))
    with pytest.raises(BudgetLedgerInvalid) as summary_caught:
        ledger.summary()
    assert_no_synthetic_marker(exception_texts(summary_caught.value))


def test_nested_exception_propagation_does_not_echo(tmp_path: Path) -> None:
    """F-1 嵌套异常传播：policy_from_snapshot 原文经 build/replay 包装层也不得回显。"""
    snapshot = policy_to_snapshot(CHAT_POLICY)
    snapshot["version"] = S_VERSION
    with pytest.raises(SettlementPolicyError) as direct:
        policy_from_snapshot(snapshot)
    assert_no_synthetic_marker(exception_texts(direct.value))

    ledger = make_ledger(tmp_path)
    reservation = reserve_chat(ledger)
    tamper_snapshot(ledger, lambda item: item.__setitem__("version", S_VERSION))
    reserved = next(event for event in read_events(ledger) if event.get("event") == "reserved")
    fake_result = {
        "event": "result",
        "reservation_id": reservation.reservation_id,
        "status": "succeeded",
        "settlement": {},
    }
    with pytest.raises(BudgetLedgerInvalid) as replay_caught:
        BudgetLedger._replay_versioned_result(reserved, fake_result, CHAT_RESERVE)
    assert_no_synthetic_marker(exception_texts(replay_caught.value))

    with pytest.raises(SettlementPolicyError) as build_caught:
        build_policy(S_KIND, model="x")
    assert_no_synthetic_marker(exception_texts(build_caught.value))


def test_settlement_modules_have_no_logging_surface() -> None:
    """F-1 日志面：结算相关模块不主动记录快照/usage 原文。"""
    import mktkb.rag.settlement_policy as settlement_module

    for module in (budget_module, settlement_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for token in ("logging", "logger", "print("):
            assert token not in source, f"{module.__name__} 出现日志面 token {token!r}"


# --------------------------------------------------------------- F-2 定向


def test_rejected_result_event_arbitrary_reason_uses_fallback(tmp_path: Path) -> None:
    """F-2 主缺陷：内部 helper 收到任意 reason 时必须白名单兜底。"""
    ledger = make_ledger(tmp_path)
    reserved = {
        "reservation_id": "r-synth",
        "stage": "J1-R2",
        "kind": KIND_CHAT,
        "provider": "deepseek",
        "model": CHAT_MODEL,
    }
    event = ledger._rejected_result_event(
        reserved,
        reserve_cny=CHAT_RESERVE,
        reason=S_REASON,
        usage={**GOOD_CHAT_USAGE, S_KEY: 1},
        request_id=None,
        elapsed_seconds=None,
        dimensions=None,
    )
    assert event["error_code"] == f"SETTLEMENT_NOT_RELEASABLE:{FALLBACK}"
    assert event["settlement_rejected"]["reason"] == FALLBACK
    assert STABLE_CODE.match(event["settlement_rejected"]["reason"])
    assert set(event["usage"]) <= CHAT_USAGE_KEYS
    assert_no_synthetic_marker(event)


@pytest.mark.parametrize(
    "reason",
    [None, 123, 1.5, {"seed": S_VALUE}, ["x"], b"bytes"],
    ids=["none", "int", "float", "dict", "list", "bytes"],
)
def test_rejected_result_event_non_string_reason_falls_back(
    tmp_path: Path, reason: Any
) -> None:
    """F-2：非字符串/畸形 reason 不抛错、不原文进入事件。"""
    ledger = make_ledger(tmp_path)
    reserved = {
        "reservation_id": "r-synth",
        "stage": "J1-R2",
        "kind": KIND_CHAT,
        "provider": "deepseek",
        "model": CHAT_MODEL,
    }
    event = ledger._rejected_result_event(
        reserved,
        reserve_cny=CHAT_RESERVE,
        reason=reason,
        usage=dict(GOOD_CHAT_USAGE),
        request_id=None,
        elapsed_seconds=None,
        dimensions=None,
    )
    assert event["error_code"] == f"SETTLEMENT_NOT_RELEASABLE:{FALLBACK}"
    assert event["settlement_rejected"]["reason"] == FALLBACK
    assert_no_synthetic_marker(event)


def test_sanitize_settlement_reason_whitelist_table() -> None:
    """F-2 白名单真值表：合法稳定码保留、参数化后缀受限、其余兜底。"""
    for code in LEGIT_REASON_CODES:
        assert sanitize_settlement_reason(code) == code
    for prefix in ("usage_missing", "usage_not_int", "usage_negative"):
        for field in sorted(CHAT_USAGE_KEYS | TOTAL_USAGE_KEYS):
            parameterized = f"{prefix}:{field}"
            assert sanitize_settlement_reason(parameterized) == parameterized
    assert sanitize_settlement_reason(f"usage_not_int:{S_KEY}") == FALLBACK
    assert sanitize_settlement_reason(f"unknown_code_{MARKER}") == FALLBACK
    assert sanitize_settlement_reason(S_REASON) == FALLBACK
    assert sanitize_settlement_reason("") == FALLBACK
    assert sanitize_settlement_reason("x" * 20000) == FALLBACK
    for value in (None, 0, False, 1.5, {"a": 1}, ["x"], b"x"):
        assert sanitize_settlement_reason(value) == FALLBACK


@pytest.mark.parametrize(
    "kind,usage,expected_reason",
    [
        (KIND_CHAT, {**GOOD_CHAT_USAGE, S_KEY: 1}, "unknown_usage_field"),
        (KIND_CHAT, {**GOOD_CHAT_USAGE, "prompt_tokens": S_VALUE}, "usage_not_int:prompt_tokens"),
        (
            KIND_EMBEDDING,
            {"total_tokens": 4096, S_KEY: 1},
            "unknown_usage_field",
        ),
    ],
    ids=["chat-unknown-key", "chat-secret-value", "embedding-unknown-key"],
)
def test_reachable_rejection_paths_keep_stable_reasons(
    tmp_path: Path, kind: str, usage: dict[str, Any], expected_reason: str
) -> None:
    """F-2 实际可达路径：既有合法稳定 reason 原样保留（不因兜底被改写）。"""
    ledger = make_ledger(tmp_path)
    if kind == KIND_CHAT:
        reservation = reserve_chat(ledger)
        evidence = chat_evidence(usage=usage)
        reserve_cny = CHAT_RESERVE
    else:
        reservation = ledger.reserve(
            kind=KIND_EMBEDDING,
            provider="bailian",
            model=EMBEDDING_MODEL,
            max_cny=EMBEDDING_RESERVE,
            request_sha256=REQ_SHA,
            settlement_policy=EMBEDDING_POLICY,
        )
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
            usage=usage,
        )
        reserve_cny = EMBEDDING_RESERVE
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=evidence)
    assert caught.value.reason == expected_reason
    assert STABLE_CODE.match(str(caught.value.reason))
    event = result_events(ledger, reservation.reservation_id)[0]
    assert event["error_code"] == f"SETTLEMENT_NOT_RELEASABLE:{expected_reason}"
    assert event["settlement_rejected"]["reason"] == expected_reason
    assert_no_synthetic_marker(event)
    assert ledger.summary().accounted_cny == pytest.approx(HIST_CNY + reserve_cny)


def test_settle_usage_sanitizes_non_whitelisted_decision_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-2 纵深：若未来 decision 出现非白名单 reason，settle_usage 边界必须兜底。"""
    ledger = make_ledger(tmp_path)
    reservation = reserve_chat(ledger)
    original = budget_module.evaluate_settlement

    def fake_evaluate(policy, *, reserved, evidence, reserve_cny):  # noqa: ANN001
        base = original(policy, reserved=reserved, evidence=evidence, reserve_cny=reserve_cny)
        return SettlementDecision(
            accepted=False,
            reason=S_REASON,
            stop_required=True,
            boundary_anomaly=False,
            charge_cny=base.charge_cny,
            estimated_list_price_cny=base.estimated_list_price_cny,
            release_cny=base.release_cny,
            usage_fields=base.usage_fields,
            evidence_snapshot=base.evidence_snapshot,
        )

    monkeypatch.setattr(budget_module, "evaluate_settlement", fake_evaluate)
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=chat_evidence())
    assert caught.value.reason == FALLBACK
    assert_no_synthetic_marker(exception_texts(caught.value))
    event = result_events(ledger, reservation.reservation_id)[0]
    assert event["error_code"] == f"SETTLEMENT_NOT_RELEASABLE:{FALLBACK}"
    assert event["settlement_rejected"]["reason"] == FALLBACK
    assert_no_synthetic_marker(event)
    assert ledger.summary().accounted_cny == pytest.approx(HIST_CNY + CHAT_RESERVE)


def test_replay_exception_reason_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-2 纵深：重放路径的拒绝异常文本同样不回显非白名单 reason。"""
    ledger = make_ledger(tmp_path)
    reservation = reserve_chat(ledger)
    ledger.settle_usage(reservation, evidence=chat_evidence())
    reserved = next(event for event in read_events(ledger) if event.get("event") == "reserved")
    result_event = result_events(ledger, reservation.reservation_id)[0]
    original = budget_module.evaluate_settlement

    def fake_evaluate(policy, *, reserved, evidence, reserve_cny):  # noqa: ANN001
        base = original(policy, reserved=reserved, evidence=evidence, reserve_cny=reserve_cny)
        return SettlementDecision(
            accepted=False,
            reason=S_REASON,
            stop_required=True,
            boundary_anomaly=False,
            charge_cny=base.charge_cny,
            estimated_list_price_cny=base.estimated_list_price_cny,
            release_cny=base.release_cny,
            usage_fields=base.usage_fields,
            evidence_snapshot=base.evidence_snapshot,
        )

    monkeypatch.setattr(budget_module, "evaluate_settlement", fake_evaluate)
    with pytest.raises(BudgetLedgerInvalid) as caught:
        BudgetLedger._replay_versioned_result(reserved, result_event, CHAT_RESERVE)
    assert FALLBACK in str(caught.value)
    assert_no_synthetic_marker(exception_texts(caught.value))


# ------------------------------------------------------- 必要回归（不退化）


def test_normal_success_settlement_unchanged(tmp_path: Path) -> None:
    """正常成功结算语义不变：白名单 usage、重算金额、无拒绝块。"""
    ledger = make_ledger(tmp_path)
    reservation = reserve_chat(ledger)
    decision = ledger.settle_usage(reservation, evidence=chat_evidence())
    assert decision.accepted is True
    assert float(decision.charge_cny) == pytest.approx(0.0036)
    assert float(decision.release_cny) == pytest.approx(CHAT_RESERVE - 0.0036)
    event = result_events(ledger, reservation.reservation_id)[0]
    assert event["status"] == "succeeded"
    assert event["error_code"] is None
    assert "settlement_rejected" not in event
    assert set(event["usage"]) <= CHAT_USAGE_KEYS
    assert event["provider_billed_cny"] is None
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(HIST_CNY + 0.0036)
    assert summary.as_dict() == ledger.summary().as_dict()  # 重放幂等


def test_rejection_event_replay_fails_closed_but_stable(tmp_path: Path) -> None:
    """拒绝 result 的 summary 重放：全额计入、两次一致，不盲信低 charge。"""
    ledger = make_ledger(tmp_path)
    reservation = reserve_chat(ledger)
    usage = {**GOOD_CHAT_USAGE, S_KEY: 1}
    with pytest.raises(SettlementNotReleasable):
        ledger.settle_usage(reservation, evidence=chat_evidence(usage=usage))
    first = ledger.summary().as_dict()
    second = ledger.summary().as_dict()
    assert first == second
    assert first["accounted_cny"] == pytest.approx(HIST_CNY + CHAT_RESERVE)
    assert_no_synthetic_marker(read_events(ledger))


def test_old_settle_path_unchanged_full_amount(tmp_path: Path) -> None:
    """旧规则（无版本 settle）仍按 max(reserve, charge) 全额保留。"""
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
    assert summary.accounted_cny == pytest.approx(HIST_CNY + 0.5)
    assert summary.stage_accounted_cny == pytest.approx(0.5)


def test_duplicate_settlement_still_rejected(tmp_path: Path) -> None:
    """重复结算仍被拒绝且不追加事件。"""
    ledger = make_ledger(tmp_path)
    reservation = reserve_chat(ledger)
    ledger.settle_usage(reservation, evidence=chat_evidence())
    count_before = len(read_events(ledger))
    with pytest.raises(BudgetLedgerInvalid):
        ledger.settle_usage(reservation, evidence=chat_evidence())
    assert len(read_events(ledger)) == count_before


def test_d1_unknown_usage_key_still_whitelisted(tmp_path: Path) -> None:
    """D-1 回归：未知 usage 键（键名即合成 secret 形态）仍不落盘、reason 稳定、全额保留。"""
    ledger = make_ledger(tmp_path)
    reservation = reserve_chat(ledger)
    usage = {**GOOD_CHAT_USAGE, S_KEY: 1}
    with pytest.raises(SettlementNotReleasable) as caught:
        ledger.settle_usage(reservation, evidence=chat_evidence(usage=usage))
    assert caught.value.reason == "unknown_usage_field"
    event = result_events(ledger, reservation.reservation_id)[0]
    assert set(event["usage"]) <= CHAT_USAGE_KEYS
    assert_no_synthetic_marker(event)
    assert ledger.summary().accounted_cny == pytest.approx(HIST_CNY + CHAT_RESERVE)
