"""S2-J2 定向测试：正式受控执行入口的 plan/GO 绑定与调用边界（无 HTTP、无 app）。

覆盖：
- 条件预算 plan 的派生金额/请求数/哈希与非法 plan 拒绝；
- GO scope.bindings 逐字段绑定核对（缺失/类型/不一致在首个预留前拒绝，不回显 GO 原文）；
- 同一共享账本/阶段额度/请求上限/历史 0.03 的闸门一致性检查；
- 受控调用边界：计划计数、串行、失败即停（后续调用在预留/发送前拒绝）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from mktkb.controlled_execution import (
    PLAN_HISTORY_CNY,
    ControlledBindingError,
    ControlledExecution,
    ControlledRefused,
    ControlledRequestPlan,
    _assert_gate_limits,
    _plan_bindings,
    _verify_fields,
)
from mktkb.live_authorization import LiveAuthorization, LiveGate, project_total_limit_cny
from mktkb.rag.budget import BudgetLedger
from mktkb.rag.settlement_policy import (
    CHAT_COMPLETION_TOKENS_CAP,
    CHAT_INPUT_PRICE_FLOOR,
    CHAT_OUTPUT_PRICE_FLOOR,
    CHAT_PROMPT_TOKENS_CAP,
    EMBEDDING_TOTAL_TOKENS_CAP,
    EMBEDDING_UNIT_PRICE_FLOOR,
    RERANK_TOTAL_TOKENS_CAP,
    RERANK_UNIT_PRICE_FLOOR,
)

SECRET = "sk-S2J2-PLAN-SYNTH-SECRET-DO-NOT-LEAK-0123456789"
STAGE = "S2-J2-PLAN-TEST"
_MILLION = Decimal(1_000_000)
_AMOUNT_QUANTUM = Decimal("0.00000001")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_AMOUNT_QUANTUM)


def _chat_cap_charge() -> Decimal:
    """单次 chat 准入 cap 结算：必须由 settlement_policy 的当前常量派生。"""
    return _money(
        (
            Decimal(CHAT_PROMPT_TOKENS_CAP) * CHAT_INPUT_PRICE_FLOOR
            + Decimal(CHAT_COMPLETION_TOKENS_CAP) * CHAT_OUTPUT_PRICE_FLOOR
        )
        / _MILLION
    )



def _authorization(*, bindings=None) -> LiveAuthorization:
    now = datetime.now(timezone.utc)
    requested_plan = ControlledRequestPlan(stage=STAGE)
    return LiveAuthorization(
        stage=STAGE,
        service="chat",
        issued_by="s2j2-test",
        nonce="s2j2-test-nonce-0123456789",
        issued_utc=now - timedelta(minutes=1),
        expires_utc=now + timedelta(hours=1),
        stage_limit_cny=float(requested_plan.peak_include_history_cny),
        max_requests=400,
        max_request_cny=2.11,
        ledger_sha256="a" * 64,
        source_path="docs/evidence/LOCAL-R1-20261101/PM/S2-J2-MOCK-GO.json",
        bindings=bindings,
    )


def _gate(
    tmp_path: Path,
    *,
    stage_limit: float | None = None,
    max_requests: int = 400,
    total_limit: float | None = None,
    bindings=None,
) -> LiveGate:
    """构造闸门；阶段额度/总上限默认取“计划峰值 + 当前项目上限”。

    计划峰值随 settlement_policy 的 chat cap 常数变化（6144/800 → 11.48496 元），
    所以这里按 plan 派生，不写死历史数字。
    """
    plan = ControlledRequestPlan(stage=STAGE)
    if stage_limit is None:
        stage_limit = float(plan.peak_include_history_cny)
    if total_limit is None:
        total_limit = float(project_total_limit_cny())
    ledger_path = tmp_path / "live-ledger.jsonl"
    budget_path = tmp_path / "budget.json"
    if not ledger_path.is_file():
        ledger_path.write_text(
            json.dumps({"event": "historical_import", "accounted_cny": 0.03}) + "\n",
            encoding="utf-8",
        )
    budget_path.write_text(
        json.dumps({"limit_cny": total_limit, "stages": {STAGE: stage_limit}}) + "\n",
        encoding="utf-8",
    )
    return LiveGate(
        stage=STAGE,
        service="chat",
        ledger_path=ledger_path,
        budget_path=budget_path,
        go_path=tmp_path / "S2-J2-MOCK-GO.json",
        stage_limit_cny=stage_limit,
        max_requests=max_requests,
        max_request_cny=2.11,
        total_limit_cny=total_limit,
        authorization=_authorization(bindings=bindings),
    )


def _rag_budget(tmp_path: Path, *, stage_limit: float | None = None, max_requests: int = 400) -> BudgetLedger:
    if stage_limit is None:
        stage_limit = float(ControlledRequestPlan(stage=STAGE).peak_include_history_cny)
    return BudgetLedger(
        tmp_path / "live-ledger.jsonl",
        tmp_path / "budget.json",
        stage=STAGE,
        stage_limit_cny=stage_limit,
        max_requests=max_requests,
    )


class _RagConfig:
    max_request_cny = 2.11


def _bindings(plan: ControlledRequestPlan) -> dict:
    expected = _plan_bindings(plan)
    return {
        "chat": dict(expected["chat"]),
        "rag": dict(expected["rag"]),
    }


# ---------------------------------------------------------------- plan


def test_plan_derived_amounts_match_manager_conditional_route():
    plan = ControlledRequestPlan(stage=STAGE)
    chat_cap = _chat_cap_charge()
    embedding_cap = _money(Decimal(EMBEDDING_TOTAL_TOKENS_CAP) * EMBEDDING_UNIT_PRICE_FLOOR / _MILLION)
    rerank_cap = _money(Decimal(RERANK_TOTAL_TOKENS_CAP) * RERANK_UNIT_PRICE_FLOOR / _MILLION)
    assert plan.total_calls == 354
    assert plan.chat_cap_charge_cny == chat_cap
    assert plan.embedding_cap_charge_cny == embedding_cap
    assert plan.rerank_cap_charge_cny == rerank_cap
    assert plan.ocr_charge_cny == Decimal("6.15000000")
    assert plan.conservative_settlement_cny == _money(
        Decimal(plan.chat_requests) * chat_cap
        + Decimal(plan.embedding_requests) * embedding_cap
        + Decimal(plan.rerank_requests) * rerank_cap
        + plan.ocr_charge_cny
    )
    assert plan.chat_reserve_cny == Decimal("2.10355200")
    # 峰值 = 保守结算 + 历史 − 单次 chat cap + 单次 chat 全额预留（串行路线）。
    assert plan.peak_include_history_cny == _money(
        plan.conservative_settlement_cny + PLAN_HISTORY_CNY - chat_cap + plan.chat_reserve_cny
    )
    assert len(plan.request_plan_sha256) == 64
    assert plan.request_plan_sha256 == ControlledRequestPlan(stage=STAGE).request_plan_sha256


def test_plan_rejects_weaker_bounds_or_parallel_route():
    with pytest.raises(ValueError):
        ControlledRequestPlan(serial=False)
    with pytest.raises(ValueError):
        ControlledRequestPlan(ocr_max_attempts=2)
    with pytest.raises(ValueError):
        ControlledRequestPlan(ocr_max_tiles_per_page=2)
    # 弱于当前准入 cap（6144）必须拒绝：caps 只能精确等于 settlement_policy 常量。
    with pytest.raises(ValueError):
        ControlledRequestPlan(chat_prompt_tokens_cap=CHAT_PROMPT_TOKENS_CAP - 1)
    with pytest.raises(ValueError):
        ControlledRequestPlan(chat_requests=0)
    plan = ControlledRequestPlan(stage=STAGE)
    assert plan.plan_dict()["settlement_version"] == "usage-conservative-v1"
    assert plan.plan_dict()["ocr_max_calls"] == 13


# ---------------------------------------------------------------- GO 绑定


def test_plan_bindings_pass_and_field_names_are_stable():
    plan = ControlledRequestPlan(stage=STAGE)
    expected = _plan_bindings(plan)
    authorization = _authorization(bindings=_bindings(plan))
    assert _verify_fields(authorization, "chat", expected["chat"])["serial"] is True
    assert _verify_fields(authorization, "rag", expected["rag"])["ocr_max_attempts"] == 1


def test_missing_plan_binding_field_refused_before_any_reserve():
    plan = ControlledRequestPlan(stage=STAGE)
    bindings = _bindings(plan)
    bindings["rag"].pop("request_plan_sha256")
    authorization = _authorization(bindings=bindings)
    with pytest.raises(ControlledBindingError) as caught:
        _verify_fields(authorization, "rag", _plan_bindings(plan)["rag"])
    assert "request_plan_sha256" in str(caught.value)
    assert SECRET not in str(caught.value)


def test_tampered_plan_binding_refused_without_echoing_go_raw_values():
    plan = ControlledRequestPlan(stage=STAGE)
    bindings = _bindings(plan)
    bindings["chat"]["request_plan_sha256"] = "Authorization: Bearer " + SECRET
    authorization = _authorization(bindings=bindings)
    with pytest.raises(ControlledBindingError) as caught:
        _verify_fields(authorization, "chat", _plan_bindings(plan)["chat"])
    message = str(caught.value)
    assert "request_plan_sha256" in message
    assert SECRET not in message
    assert "Authorization" not in message


def test_bool_type_confusion_in_binding_refused():
    plan = ControlledRequestPlan(stage=STAGE)
    bindings = _bindings(plan)
    bindings["rag"]["serial"] = 1  # int 不是 bool
    authorization = _authorization(bindings=bindings)
    with pytest.raises(ControlledBindingError):
        _verify_fields(authorization, "rag", _plan_bindings(plan)["rag"])


# ---------------------------------------------------------------- 闸门限制


def test_gate_limits_pass_with_isolated_ledger(tmp_path):
    plan = ControlledRequestPlan(stage=STAGE)
    gate = _gate(tmp_path)
    budget = _rag_budget(tmp_path)
    _assert_gate_limits(
        plan,
        chat_gate=gate,
        rag_budget=budget,
        rag_config=_RagConfig(),
        chat_reserve_cny=plan.chat_reserve_cny,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_requests": 100},
        {"stage_limit": 9.0},
        {"total_limit": 11.0},
    ],
)
def test_gate_limits_refuse_unprovable_capacity_or_budget(tmp_path, overrides):
    plan = ControlledRequestPlan(stage=STAGE)
    gate = _gate(tmp_path, **overrides)
    budget = _rag_budget(tmp_path)
    with pytest.raises(ControlledBindingError):
        _assert_gate_limits(
            plan,
            chat_gate=gate,
            rag_budget=budget,
            rag_config=_RagConfig(),
            chat_reserve_cny=plan.chat_reserve_cny,
        )


def test_gate_limits_refuse_stage_mismatch_or_bad_history(tmp_path):
    plan = ControlledRequestPlan(stage=STAGE)
    gate = _gate(tmp_path)

    class WrongStage:
        stage = "OTHER-STAGE"
        stage_limit_cny = 9.66
        max_requests = 400

    with pytest.raises(ControlledBindingError):
        _assert_gate_limits(
            plan,
            chat_gate=gate,
            rag_budget=WrongStage(),
            rag_config=_RagConfig(),
            chat_reserve_cny=plan.chat_reserve_cny,
        )
    # 历史不是 0.03（账本被改）⇒ 拒绝
    ledger_path = tmp_path / "live-ledger.jsonl"
    ledger_path.write_text(json.dumps({"event": "historical_import", "accounted_cny": 0.02}) + "\n", encoding="utf-8")
    with pytest.raises(ControlledBindingError):
        _assert_gate_limits(
            plan,
            chat_gate=gate,
            rag_budget=_rag_budget(tmp_path),
            rag_config=_RagConfig(),
            chat_reserve_cny=plan.chat_reserve_cny,
        )


def test_gate_limits_refuse_rag_single_bound_below_ocr_price(tmp_path):
    plan = ControlledRequestPlan(stage=STAGE)
    gate = _gate(tmp_path)
    budget = _rag_budget(tmp_path)

    class TinyRagConfig:
        max_request_cny = 0.4

    with pytest.raises(ControlledBindingError):
        _assert_gate_limits(
            plan,
            chat_gate=gate,
            rag_budget=budget,
            rag_config=TinyRagConfig(),
            chat_reserve_cny=plan.chat_reserve_cny,
        )


# ---------------------------------------------------------------- 调用边界


class _FakeEmbedder:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls = 0

    def embed(self, texts, *, purpose="document"):
        self.calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return {"texts": list(texts), "purpose": purpose}


class _FakeOCR:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def recognize(self, page, *, mode):
        self.calls.append(mode)
        return {"mode": mode}


def _executor(plan, *, embedder=None, reranker=None, ocr=None) -> ControlledExecution:
    return ControlledExecution(
        plan=plan,
        chat_gate=None,  # 调用边界测试不经过 GO/chat
        rag_gate=None,
        chat_gateway=None,
        rag_config=None,
        rag_budget=None,
        embedding_provider=embedder or _FakeEmbedder(None),
        rerank_provider=reranker or _FakeEmbedder(None),
        ocr_gateway=ocr or _FakeOCR(),
        chat_policy=None,
        embedding_policy=None,
        rerank_policy=None,
    )


def test_executor_counts_and_refuses_beyond_plan():
    plan = ControlledRequestPlan(stage=STAGE, embedding_requests=1)
    executor = _executor(plan)
    executor.run_embedding(["a"])
    assert executor.stats()["counts"]["embedding"] == 1
    with pytest.raises(ControlledRefused):
        executor.run_embedding(["b"])


def test_executor_serial_route_refuses_concurrent_boundary():
    plan = ControlledRequestPlan(stage=STAGE)
    executor = _executor(plan)
    executor._begin("embedding")  # 模拟在途
    with pytest.raises(ControlledRefused):
        executor._begin("chat")
    executor._finish("embedding")


def test_executor_failure_stops_and_never_retries():
    plan = ControlledRequestPlan(stage=STAGE)
    embedder = _FakeEmbedder(RuntimeError(SECRET))
    executor = _executor(plan, embedder=embedder)
    with pytest.raises(RuntimeError):
        executor.run_embedding(["a"])
    assert executor.stopped is True
    assert embedder.calls == 1
    with pytest.raises(ControlledRefused):
        executor.run_embedding(["b"])
    assert embedder.calls == 1


def test_executor_ocr_modes_have_separate_plan_counts():
    plan = ControlledRequestPlan(stage=STAGE, ocr_text_requests=1, ocr_table_requests=1)
    ocr = _FakeOCR()
    executor = _executor(plan, ocr=ocr)

    class _Page:
        page = 1

    executor.run_ocr(_Page(), mode="text")
    executor.run_ocr(_Page(), mode="table")
    with pytest.raises(ControlledRefused):
        executor.run_ocr(_Page(), mode="text")
    assert ocr.calls == ["text", "table"]
