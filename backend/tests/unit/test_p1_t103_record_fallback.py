"""T103：记录路 overshoot 回落与诚实澄清的单元测试（不建库、不调真实模型）。

覆盖 handoff §6 的强制 truncated 分支：

- 正文型：limit=100 仍 truncated 时，逐检索词复用 ``_retrieve`` 扩大候选并保留
  原始命中总量/truncated 事实，再交既有正文排序；
- 记录型：不再返回零候选死路，澄清文本给出真实命中量与缩小方式，并尽量带候选；
- trace 降级标记只写既有 ``filter_decisions_json`` 数据字段，不新增 TraceRecord 字段。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from mktkb.conversations import intent as intent_module
from mktkb.conversations import service
from mktkb.observability.contracts import OutcomeKind, TraceMode, TracePath
from mktkb.observability.tracer import start_trace
from mktkb.retrieval.types import Candidate, EvidenceSet, QueryIntent

BANNED = "符合条件的记录过多"


class _SpyRepo:
    """内存 Trace 仓储替身：只捕获 finish 写出的记录。"""

    def __init__(self) -> None:
        self.records: list[object] = []

    def write_best_effort(self, record, spans) -> None:  # noqa: ANN001 - 与真实仓储同签名
        self.records.append(record)


def _unit(value: str, ordinal: int = 0):
    return SimpleNamespace(id=value, text=f"正文 {value}", ordinal=ordinal, fields={})


def test_document_overshoot_fallback_unions_term_evidence(monkeypatch) -> None:
    base = _unit("base")
    extra = _unit("extra", 1)
    evidence = EvidenceSet(
        units=[base],
        kind="matches",
        total_candidates=150,
        revision=3,
        candidates=[],
        truncated=True,
    )
    intent = QueryIntent(mode="document", terms=("物料", "归还"), entity_filters={"item": "宣传海报"})
    calls: list[QueryIntent] = []

    def fake_retrieve(db_factory, query_intent, revision, limit=20, *, candidate_ids=None):
        calls.append(query_intent)
        return EvidenceSet(
            units=[extra], kind="matches", total_candidates=9, revision=revision, candidates=[]
        )

    monkeypatch.setattr(service, "_retrieve", fake_retrieve)
    result = service._document_overshoot_evidence(object(), evidence, intent, 3)

    assert [unit.id for unit in result.units] == ["base", "extra"]
    assert result.total_candidates == 150 and result.truncated is True
    assert result.kind == "matches" and result.revision == 3
    assert [query.terms for query in calls] == [("物料",), ("归还",)]
    assert all(query.mode == "document" for query in calls)
    assert all(query.entity_filters == {"item": "宣传海报"} for query in calls)


def test_record_overshoot_result_reports_real_total_and_candidates() -> None:
    evidence = EvidenceSet(
        units=[_unit("row")],
        kind="ambiguous",
        total_candidates=150,
        revision=7,
        candidates=[
            Candidate(
                label="滨江店的宣传海报",
                entity_filters={"store": "滨江店", "item": "宣传海报"},
                source_ids=("row",),
            )
        ],
        truncated=True,
    )
    plan = intent_module.IntentPlan(
        mode="record",
        intent=QueryIntent(
            mode="record",
            entity_filters={"store": "滨江店", "item": "宣传海报"},
            requested_fields=("位置",),
        ),
        requested_fields=("位置",),
    )
    result = service._record_overshoot_result(evidence, 7, plan)

    assert result.kind == "clarification" and result.revision == 7
    assert "150" in result.text and "缩小范围" in result.text
    assert BANNED not in result.text and "该历史消息" not in result.text
    assert [candidate.label for candidate in result.candidates] == ["滨江店"]
    assert "滨江店" in result.candidates[0].followup_question
    assert "在哪里" in result.candidates[0].followup_question
    assert result.source_ids == ()


def test_record_overshoot_result_handles_row_truncation_honestly() -> None:
    """total<=100 但记录行超过 limit 时，不得谎称“候选记录超过 100 条”。"""
    evidence = EvidenceSet(
        units=[_unit(f"row-{index}", index) for index in range(100)],
        kind="ambiguous",
        total_candidates=2,
        revision=7,
        candidates=[
            Candidate(label="滨江店", entity_filters={"store": "滨江店"}, source_ids=("row-0",))
        ],
        truncated=True,
    )
    plan = intent_module.IntentPlan(
        mode="record",
        intent=QueryIntent(mode="record", entity_filters={"store": "滨江店"}, requested_fields=("位置",)),
        requested_fields=("位置",),
    )
    result = service._record_overshoot_result(evidence, 7, plan)

    assert result.kind == "clarification"
    assert "2 条候选记录" in result.text
    assert "记录行超过单次检索上限 100 行" in result.text
    assert "超过单次检索上限 100 条" not in result.text


def test_overshoot_annotation_is_a_trace_data_field_only() -> None:
    repo = _SpyRepo()
    with start_trace(
        http_request_id="http-t103",
        mode=TraceMode.LOCAL,
        scope="unit",
        path=TracePath.LEGACY,
        question="物料领用通知图片要求先填写什么",
        repo=repo,
    ) as trace:
        service._annotate_overshoot_fallback(
            total=104, strategy="document_term_union", term_queries=5
        )
        trace.set_outcome(OutcomeKind.CLARIFICATION, "OVERFLOW")

    assert len(repo.records) == 1
    record = repo.records[0]
    payload = json.loads(record.filter_decisions_json or "{}")
    assert payload["record_overshoot_fallback"] is True
    assert payload["record_overshoot_total"] == 104
    assert payload["record_overshoot_strategy"] == "document_term_union"
    assert payload["record_overshoot_term_queries"] == 5
    assert record.outcome_kind == OutcomeKind.CLARIFICATION.value
