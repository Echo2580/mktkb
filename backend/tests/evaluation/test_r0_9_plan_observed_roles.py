"""R0-CAPTURE-ROLES：``plan_observed`` 补采枚举级字段角色码（``field_role`` / ``field_roles``）。

背景
----
R0 修一轮的 C02 / C12 / C21 / C27 在 SAFE 层缺 ``field_role_not_captured``：封存件里
``plan_observed`` 只有 ``state_keys``（键名，``field_role``/``field_roles`` 早就在
``QueryState.to_dict()`` 的键集里），没有角色码**值**，无法离线判定“计划里请求了哪些
字段角色”。本增量只补两个**可选**键：

- ``field_role``：单角色码（``str | None``）；
- ``field_roles``：角色码列表（``list[str]``，保持原顺序，不去重）。

不采正文 / 字段中文名 / 实体 / 值。旧 envelope 没有这两个键时清洗/校验结果逐键不变
（可选键缺省不合成任何键；``capture.schema_version`` 不动，理由见
``R0-CAPTURE-ROLES.md`` §3）。

约束（与派单一致）
------------------
- 零真实请求、零私有材料；题面/答复/角色码均为合成值；
- 不改冻结件（``p2_hard_evidence.py`` / ``p2_evidence_capture.py`` / ``p2_evidence_rescore*``
  / ``docs/evaluation/*``）、阈值、题集、标签；闭包只用其现有公开入口断言；
- 先红后绿：本文件在协议加键前必须失败（``EVENT_FIELDS["plan_observed"]`` 缺键 /
  ``clean_event_payload`` 回 ``unknown_event_fields`` / 空集闭包回 ``unknown_usage_field``）。
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_EVALUATION_TESTS = Path(__file__).resolve().parent
if str(_EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(_EVALUATION_TESTS))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.conversations import service  # noqa: E402
from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
from mktkb.observability import evaluation_capture as cap  # noqa: E402
from mktkb.rag.types import QueryPlan, QueryState, RagAnswer  # noqa: E402

import test_p2_empty_scope_proof as esp  # noqa: E402
import test_p2_hard_evidence as base  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

#: 加键前的 ``plan_observed`` 固定载荷（13 键，与 A1 协议逐键一致）。
PLAN_PAYLOAD_LEGACY: dict[str, Any] = {
    "request_id": "req-1",
    "path": "legacy",
    "mode": "record",
    "filters": {},
    "terms": [],
    "as_of": None,
    "include_future": False,
    "enumerate": False,
    "clarification": False,
    "state_keys": [],
    "state_as_of": None,
    "state_pending_slot": None,
    "state_last_kind": None,
}
ROLE_KEYS = ("field_role", "field_roles")
ROLE_PAYLOAD = {"field_role": "location", "field_roles": ["phone", "location", "phone"]}
OK = (True, "empty_use_scope_ok")


# --------------------------------------------------------------------------- #
# 1) 协议层：可选键已登记、旧载荷逐键不变
# --------------------------------------------------------------------------- #


def test_plan_observed_schema_registers_optional_role_fields() -> None:
    spec = cap.EVENT_FIELDS["plan_observed"]
    assert set(ROLE_KEYS) <= set(spec)
    assert spec["field_role"].kind == cap._OPT_STR
    assert spec["field_roles"].kind == cap._OPT_LIST_STR
    for key in ROLE_KEYS:
        assert spec[key].required is False, "新键必须可选：旧 envelope 不得因缺键被拒"
    for kind, fields in cap.EVENT_FIELDS.items():
        if kind == "plan_observed":
            continue
        assert not (set(ROLE_KEYS) & set(fields)), f"{kind} 不应登记角色码键"


def test_clean_plan_observed_keeps_role_codes_order_and_duplicates() -> None:
    cleaned = cap.clean_event_payload(
        "plan_observed", dict(PLAN_PAYLOAD_LEGACY, **ROLE_PAYLOAD)
    )
    assert cleaned["field_role"] == "location"
    assert type(cleaned["field_role"]) is str
    # 原顺序保留、不去重（去重不在采集层做）
    assert cleaned["field_roles"] == ["phone", "location", "phone"]
    assert all(type(item) is str for item in cleaned["field_roles"])
    assert set(cleaned) == set(PLAN_PAYLOAD_LEGACY) | set(ROLE_KEYS)


def test_clean_plan_observed_accepts_explicit_null_role_values() -> None:
    cleaned = cap.clean_event_payload(
        "plan_observed", dict(PLAN_PAYLOAD_LEGACY, field_role=None, field_roles=None)
    )
    assert cleaned["field_role"] is None
    assert cleaned["field_roles"] == []


def test_plan_observed_without_role_keys_is_valid_and_cleaned_identically() -> None:
    cleaned = cap.clean_event_payload("plan_observed", PLAN_PAYLOAD_LEGACY)
    # 可选键缺省 = 未观测：不合成任何键，清洗结果与加键前逐键逐值相同。
    assert cleaned == PLAN_PAYLOAD_LEGACY
    assert not (set(ROLE_KEYS) & set(cleaned))

    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event("plan_observed", **PLAN_PAYLOAD_LEGACY)
    assert sink.status == "active" and sink.errors == []
    assert set(sink.events[0]["payload"]) == set(PLAN_PAYLOAD_LEGACY)


@pytest.mark.parametrize(
    "bad",
    [
        {"field_role": 7},
        {"field_role": True},
        {"field_roles": "location"},
        {"field_roles": ["location", 7]},
        {"field_roles": ["location", None]},
        {"field_roles": {"location": 1}},
    ],
)
def test_plan_observed_rejects_non_role_codes(bad: dict[str, Any]) -> None:
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event("plan_observed", **dict(PLAN_PAYLOAD_LEGACY, **bad))
    assert sink.status == "failed" and sink.events == []
    assert sink.errors and sink.errors[0]["code"] == "capture_event_invalid"


# --------------------------------------------------------------------------- #
# 2) 产品发射点：从 rag_plan 取角色码，缺属性不抛 AttributeError
# --------------------------------------------------------------------------- #


class _NoDb:
    """rag 内核直接作答的轮次不得触库；触到即失败。"""

    def __call__(self) -> Any:  # pragma: no cover - 触发即测试失败
        raise AssertionError("rag 分支不得访问数据库")


class _FakeQa:
    def __init__(self, plan: Any, answer: RagAnswer) -> None:
        self.plan = plan
        self.answer_obj = answer
        self.calls: list[tuple[str, str]] = []

    def prepare(self, question: str, user_id: str, conversation_id: str):
        self.calls.append(("prepare", question))
        return QueryState(), self.plan

    def answer(self, question: str, user_id: str, conversation_id: str) -> RagAnswer:
        self.calls.append(("answer", question))
        return self.answer_obj


def _claim() -> service._Claim:
    return service._Claim(
        conversation_id=None,
        request_id=uuid.uuid4(),
        attempt=1,
        user_message_id=uuid.uuid4(),
        initial_revision=1,
    )


def _rag_plan(**overrides: Any) -> QueryPlan:
    """真实 QueryPlan：identifier 过滤 + record 模式 ⇒ ``_rag_owns_turn`` 为真。"""
    state = QueryState(field_role="location", field_roles=("location", "phone"))
    values: dict[str, Any] = dict(
        question="合成问句",
        mode="record",
        query_text="合成问句",
        field_role="location",
        field_label="location",
        filters={"identifier": "QF01"},
        terms=(),
        state=state,
        field_roles=("location", "phone"),
    )
    values.update(overrides)
    return QueryPlan(**values)


def _run_answer(plan: Any) -> tuple[cap.CaptureSink, service._Result]:
    sink = cap.CaptureSink()
    qa = _FakeQa(
        plan,
        # 内核 no_answer → 产品 not_found（``service._RAG_KIND_MAP`` 的既有映射）。
        RagAnswer(kind="no_answer", question="合成问句", text="合成无事实答复", state={}),
    )

    async def main() -> service._Result:
        with cap.capture_scope(sink):
            return await service._answer(
                _NoDb(),
                SimpleNamespace(id=uuid.uuid4()),
                _claim(),
                "合成问句",
                None,
                0.0,
                qa=qa,
            )

    return sink, asyncio.run(main())


def _plan_payload(sink: cap.CaptureSink) -> dict[str, Any]:
    rows = [event["payload"] for event in sink.events if event["kind"] == "plan_observed"]
    assert len(rows) == 1, rows
    return rows[0]


def test_service_emits_role_codes_from_rag_plan() -> None:
    sink, result = _run_answer(_rag_plan())
    assert sink.status == "active" and sink.errors == []
    assert result.kind == "not_found"
    payload = _plan_payload(sink)
    assert payload["path"] == "rag"
    assert payload["field_role"] == "location"
    assert type(payload["field_role"]) is str
    assert payload["field_roles"] == ["location", "phone"]
    assert all(type(item) is str for item in payload["field_roles"])
    # 事件仍是固定协议、只多这两个角色码键：不含正文/字段中文名/实体/值。
    assert set(payload) == set(cap.EVENT_FIELDS["plan_observed"])
    assert "question" not in payload and "text" not in payload


def test_service_emit_without_role_attributes_does_not_raise() -> None:
    plan = SimpleNamespace(
        mode="record",
        filters={"identifier": "QF01"},
        terms=(),
        as_of=None,
        include_future=False,
        enumerate=False,
        clarification=None,
        reason=None,
        state=QueryState(),
    )
    sink, result = _run_answer(plan)
    assert result.kind == "not_found"
    payload = _plan_payload(sink)
    assert payload["field_role"] is None
    assert payload["field_roles"] == []


# --------------------------------------------------------------------------- #
# 3) 空集闭包：带新角色键的事件不再被判 unknown_usage_field（冻结件不改）
# --------------------------------------------------------------------------- #


def _provable_envelope(**overrides: Any) -> dict[str, Any]:
    """可证明空用集的合成 envelope（默认 compat 与 v0.5 均 ``empty_use_scope_ok``）。"""
    values: dict[str, Any] = dict(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind="not_found",
        answer_text=base.real_no_fact_text("not_found"),
    )
    values.update(overrides)
    return base.build_evidence(**values)


def _with_roles(envelope: dict[str, Any]) -> dict[str, Any]:
    plan = base._event_payload(envelope, "plan_observed")
    plan.update(ROLE_PAYLOAD)
    return envelope


def test_empty_scope_closure_accepts_new_role_keys() -> None:
    control = _provable_envelope()
    assert hard._empty_use_scope_proof(control) == OK
    assert hard._structural_closure_violation(control) is None
    assert set(base._event_payload(control, "plan_observed")) == set(PLAN_PAYLOAD_LEGACY)

    with_roles = _with_roles(_provable_envelope())
    assert hard._empty_use_scope_proof(with_roles) != (False, "unknown_usage_field")
    assert hard._empty_use_scope_proof(with_roles) == OK
    assert hard._structural_closure_violation(with_roles) is None


def test_independent_empty_scope_proof_accepts_new_role_keys() -> None:
    """C1-P2 独立实现（``p2_empty_scope_proof``）同样只读共享白名单，不得判 unknown。"""
    envelope = esp.build_evidence()
    assert esp.empty_use_scope_proof(envelope) == (True, esp.EMPTY_USE_SCOPE_OK)
    plan = [
        event["payload"]
        for event in envelope["capture"]["events"]
        if event["kind"] == "plan_observed"
    ][0]
    plan.update(ROLE_PAYLOAD)
    assert esp.empty_use_scope_proof(envelope) == (True, esp.EMPTY_USE_SCOPE_OK)


@pytest.mark.parametrize(
    ("compat", "overrides", "expected"),
    [
        (None, {}, OK),
        ("p2-refusal-compat/v0.5", {}, OK),
        (None, {"plan": {"path": "legacy"}}, (False, "model_events_missing")),
        (
            None,
            {"units": [{"unit_id": "unit-1"}], "used_unit_ids": ["unit-1"]},
            (False, "empty_set_not_proven"),
        ),
        (
            "p2-refusal-compat/v0.5",
            {"plan": {"path": "legacy"}},
            (False, "model_events_missing"),
        ),
        (
            "p2-refusal-compat/v0.5",
            {"units": [{"unit_id": "unit-1"}], "used_unit_ids": ["unit-1"]},
            (False, "empty_set_not_proven"),
        ),
    ],
    ids=[
        "default_ok",
        "v0_5_ok",
        "default_legacy_missing_model",
        "default_nonempty_usage",
        "v0_5_legacy_missing_model",
        "v0_5_nonempty_usage",
    ],
)
def test_old_envelope_without_role_keys_is_value_identical(
    compat: str | None, overrides: dict[str, Any], expected: tuple[bool, str]
) -> None:
    """旧 envelope（无新键）抽样：结果仍逐值等于既定固定码。"""
    envelope = _provable_envelope(**overrides)
    kwargs = {} if compat is None else {"compat": compat}
    assert hard._empty_use_scope_proof(envelope, **kwargs) == expected
    assert not (set(base._event_payload(envelope, "plan_observed")) & set(ROLE_KEYS))
