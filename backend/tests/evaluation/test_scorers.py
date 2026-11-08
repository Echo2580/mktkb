"""T004b：确定性打分器 ``score_case`` 与各指标函数（设计 §7.1 / §7.2 / §8.2）。

口径（与模块 docstring 一致）：

- 所有比率是 **0–1**，不是 0–100；
- 每个 case 的 ``CaseCheck`` 有稳定 ``check_id`` / ``status`` / ``evidence``；
- 检索指标按 **chunk 排名**、**unit 去重**计算（同一 unit 的多个 chunk 只计一次；
  同一 chunk 的多个 unit 共享同一排名），无 gold 的 case 不进分母；
- 拒答三指标由同一张 2×2 混淆矩阵派生，但三个字段各自独立、互不替代。

测试全部使用合成/固定文本，不调用任何模型 / OCR / embedding / rerank。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from mktkb.evaluation.dataset import CaseSpec, load_cases
from mktkb.evaluation.gold import ResolvedGold, ResolvedSource
from mktkb.evaluation.scorers import (
    CaseCheck,
    CaseResult,
    EvalCitation,
    EvalOutcome,
    EvalRetrieved,
    aggregate_metrics,
    answer_metrics,
    check_source,
    check_value,
    cost_metrics,
    is_refusal,
    latency_metrics,
    normalize_text,
    refusal_metrics,
    retrieval_metrics,
    score_case,
)
from mktkb.observability.contracts import OutcomeKind, TraceRecord

EVAL_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "evaluation"
CHECK_IDS = frozenset(
    {
        "value_hit",
        "value_forbidden",
        "value_no_fabricated",
        "source_hit",
        "source_forbidden",
        "kind_correct",
        "refusal_expected",
        "refusal_unexpected",
        "pagination_total",
        "pagination_returned",
        "pagination_has_more",
        "pagination_next_page",
    }
)
PAGINATION_IDS = (
    "pagination_total",
    "pagination_returned",
    "pagination_has_more",
    "pagination_next_page",
)


# --------------------------------------------------------------------------- #
# 装配 helpers
# --------------------------------------------------------------------------- #


def _case(case_id: str = "C01", **overrides) -> CaseSpec:
    data: dict = {
        "case_id": case_id,
        "suite": "t",
        "split": "dev",
        "stratum": "exact",
        "business_date": "2026-10-28",
        "question": "合成测试问题",
        "expected_kind": "answer",
        "expected_values": (),
        "expected_sources": (),
        "relevant_units": (),
        "reference_answer": "",
        "should_refuse": False,
        "refusal_reason": None,
        "forbidden_values": (),
        "forbidden_sources": (),
        "expected_pagination": None,
        "requires_ocr": False,
        "label_version": "t-1",
    }
    data.update(overrides)
    return CaseSpec(**data)


def _resolved(
    case_id: str = "C01",
    *,
    unit_ids: tuple[str, ...] = (),
    relevant: tuple[str, ...] | None = None,
    skipped: bool = False,
    sources: tuple[ResolvedSource, ...] = (),
) -> ResolvedGold:
    return ResolvedGold(
        case_id=case_id,
        requires_ocr=skipped,
        skipped=skipped,
        sources=sources,
        unit_ids=unit_ids,
        relevant_unit_ids=unit_ids if relevant is None else relevant,
    )


def _outcome(
    kind: str = "answer",
    text: str = "",
    citations: tuple[EvalCitation, ...] = (),
    pagination: dict | None = None,
    retrieved: tuple[EvalRetrieved, ...] = (),
    *,
    trace_id: str = "tr-1",
    path: str = "rag",
) -> EvalOutcome:
    return EvalOutcome(
        kind=kind,
        text=text,
        citations=citations,
        facts=(),
        pagination={} if pagination is None else pagination,
        trace_id=trace_id,
        path=path,
        retrieved=retrieved,
    )


def _trace(
    latency: int | None = None,
    tokens: dict | None = None,
    cost: dict | None = None,
) -> TraceRecord:
    return TraceRecord(
        trace_id="tr-1",
        latency_ms=latency,
        token_usage_json=None if tokens is None else json.dumps(tokens),
        cost_json=None if cost is None else json.dumps(cost),
    )


def _check(result: CaseResult, check_id: str) -> CaseCheck:
    matches = [item for item in result.checks if item.check_id == check_id]
    assert len(matches) == 1, f"{result.case_id} 缺少唯一 check {check_id}"
    return matches[0]


# --------------------------------------------------------------------------- #
# §5.1 值命中：全角/大小写/空白归一化
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Ｂ区１号货架", "B区1号货架"),
        ("b区1号货架", "B区1号货架"),
        ("B区 1 号货架", "B区1号货架"),
        ("B区1号货架 ", " B区1号货架"),
        ("B区  1   号货架", "B区1号货架"),
        ("Ｂ区１号货架第二层", "B区1号货架"),
        ("单价 １．５ 元", "1.5"),
    ],
)
def test_check_value_normalizes_fullwidth_case_and_spaces(text: str, value: str) -> None:
    assert check_value(text, value) is True


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("共120件", "12"),
        ("120", "12"),
        ("12.5元", "12"),
        ("B区12号货架", "B区1号货架"),
        ("", "12"),
        ("1 2", "12"),
    ],
)
def test_check_value_never_matches_bigger_numbers(text: str, value: str) -> None:
    assert check_value(text, value) is False


def test_check_value_rejects_partial_decimal_inside_mixed_value() -> None:
    assert check_value("价格12.5元", "价格12") is False
    assert check_value("价格12.5元", "价格12.5") is True


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("温度-12度", "12"),
        ("-12", "12"),
        ("价格-5元", "5元"),
        ("价格 － 5 元", "5元"),
    ],
)
def test_check_value_rejects_negative_numbers(text: str, value: str) -> None:
    assert check_value(text, value) is False


def test_check_value_matches_negative_expected_value() -> None:
    assert check_value("温度-12度", "-12") is True


def test_normalize_text_collapses_invisible_and_repeated_spaces() -> None:
    assert normalize_text("  Ｂ\u00a0区\u3000１ 号 ") == "b 区 1 号"


def test_value_hit_and_no_fabricated_numbers_are_separate_checks() -> None:
    case = _case(expected_values=("12",), reference_answer="12")
    result = score_case(case, _resolved(), _outcome(text="共12件，另加13件"))

    assert _check(result, "value_hit").status == "pass"
    fabricated = _check(result, "value_no_fabricated")
    assert fabricated.status == "fail"
    assert fabricated.evidence["extra"] == ["13"]


def test_no_fabricated_numbers_passes_when_answer_stays_within_gold() -> None:
    case = _case(expected_values=("12",), reference_answer="共12件")
    result = score_case(case, _resolved(), _outcome(text="共12件"))

    assert _check(result, "value_no_fabricated").status == "pass"


def test_value_hit_fails_when_number_is_prefix_of_bigger_number() -> None:
    case = _case(expected_values=("12",), reference_answer="12")
    result = score_case(case, _resolved(), _outcome(text="120"))

    hit = _check(result, "value_hit")
    assert hit.status == "fail"
    assert hit.evidence["missing"] == ["12"]


def test_value_hit_failure_does_not_force_fabrication_failure() -> None:
    case = _case(expected_values=("12",), reference_answer="12")
    result = score_case(case, _resolved(), _outcome(text="没有找到相关数值"))

    assert _check(result, "value_hit").status == "fail"
    assert _check(result, "value_no_fabricated").status == "pass"


def test_forbidden_value_leak_is_a_separate_check() -> None:
    case = _case(
        expected_values=("B区1号货架",),
        reference_answer="B区1号货架",
        forbidden_values=("停售",),
    )
    result = score_case(case, _resolved(), _outcome(text="B区1号货架，已停售"))

    assert _check(result, "value_hit").status == "pass"
    assert _check(result, "value_forbidden").status == "fail"


def test_value_checks_are_skipped_for_refusal_cases() -> None:
    case = _case(
        expected_kind="no_answer",
        expected_values=("12",),
        should_refuse=True,
        refusal_reason="safety",
    )
    result = score_case(case, _resolved(), _outcome(kind="no_answer", text="无法回答"))

    assert _check(result, "value_hit").status == "skipped"
    assert _check(result, "value_no_fabricated").status == "skipped"


# --------------------------------------------------------------------------- #
# §5.2 来源命中：doc_code + unit_key / locator；unit 去重后的引用精确/召回
# --------------------------------------------------------------------------- #


def test_check_source_requires_document_and_unit_identity() -> None:
    ref = {"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}

    assert check_source(ref, EvalCitation(doc_code="D01", unit_key="sheet:物品位置:row:8"))
    assert not check_source(ref, EvalCitation(doc_code="D01", unit_key="sheet:物品位置:row:9"))
    assert not check_source(ref, EvalCitation(doc_code="D02", unit_key="sheet:物品位置:row:8"))


def test_check_source_supports_locator_and_document_level_refs() -> None:
    locator_ref = {"doc_code": "W01", "locator": {"paragraph": 13}}
    assert check_source(
        locator_ref, EvalCitation(doc_code="W01", locator={"paragraph": 13, "heading": "价格"})
    )
    assert not check_source(locator_ref, EvalCitation(doc_code="W01", locator={"paragraph": 14}))
    # 只给 doc_code 的整篇级 gold：同文档任意 unit 都算命中
    assert check_source({"doc_code": "E03"}, EvalCitation(doc_code="E03", unit_key="任何"))


def test_check_source_accepts_mapping_citation() -> None:
    ref = {"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}
    assert check_source(ref, {"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"})
    assert not check_source(ref, {"doc_code": "D01", "unit_key": "sheet:物品位置:row:9"})


def test_check_source_prefers_resolved_unit_identity() -> None:
    resolved = ResolvedSource(
        doc_code="D01", doc_id="D01", unit_ids=("D01-7",), unit_keys=("sheet:物品位置:row:7",)
    )
    ref = {"doc_code": "D01", "unit_key": "sheet:物品位置:row:7"}
    citation = EvalCitation(doc_code="D01", unit_ids=("D01-7",))

    assert check_source(ref, citation, resolved_source=resolved)


def test_source_hit_requires_expected_unit_not_any_unit_in_document() -> None:
    case = _case(
        expected_sources=({"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"},),
    )
    resolved = _resolved(
        unit_ids=("D01-8",),
        sources=(
            ResolvedSource(
                doc_code="D01",
                doc_id="D01",
                unit_ids=("D01-8",),
                unit_keys=("sheet:物品位置:row:8",),
            ),
        ),
    )

    wrong_unit = score_case(
        case,
        resolved,
        _outcome(citations=(EvalCitation(doc_code="D01", unit_key="sheet:物品位置:row:9"),)),
    )
    assert _check(wrong_unit, "source_hit").status == "fail"

    right_unit = score_case(
        case,
        resolved,
        _outcome(
            citations=(EvalCitation(doc_code="D01", unit_key="sheet:物品位置:row:8"),),
        ),
    )
    assert _check(right_unit, "source_hit").status == "pass"


def test_forbidden_source_catches_any_citation_in_that_document() -> None:
    case = _case(forbidden_sources=({"doc_code": "D08"},))
    result = score_case(
        case, _resolved(), _outcome(citations=(EvalCitation(doc_code="D08", unit_key="page:3"),))
    )

    assert _check(result, "source_forbidden").status == "fail"


def test_citation_metrics_use_unit_level_dedup() -> None:
    case = _case(expected_sources=({"doc_code": "D01", "unit_key": "k1"},))
    resolved = _resolved(unit_ids=("u1", "u2"), relevant=("u1", "u2"))
    citations = (
        EvalCitation(doc_code="D01", unit_key="k1", unit_ids=("u1",)),
        EvalCitation(doc_code="D01", unit_key="k1", unit_ids=("u1",)),  # 同 unit 的第二块 chunk
        EvalCitation(doc_code="D01", unit_key="k3", unit_ids=("u3",)),
    )
    result = score_case(case, resolved, _outcome(citations=citations))

    assert result.metrics["citation_precision"] == pytest.approx(0.5)
    assert result.metrics["citation_recall"] == pytest.approx(0.5)


def test_citation_with_multiple_units_counts_each_relevant_unit() -> None:
    case = _case()
    resolved = _resolved(unit_ids=("u1", "u2"), relevant=("u1", "u2"))
    result = score_case(
        case,
        resolved,
        _outcome(citations=(EvalCitation(doc_code="D01", unit_ids=("u1", "u2")),)),
    )

    assert result.metrics["citation_precision"] == 1.0
    assert result.metrics["citation_recall"] == 1.0


def test_citation_metrics_not_applicable_without_gold_or_on_refusal() -> None:
    no_gold = score_case(
        _case(), _resolved(), _outcome(citations=(EvalCitation(doc_code="D01", unit_ids=("u1",)),))
    )
    assert no_gold.metrics["citation_precision"] is None
    assert no_gold.metrics["citation_recall"] is None

    refusal = score_case(
        _case(expected_kind="no_answer", should_refuse=True, refusal_reason="safety"),
        _resolved(unit_ids=("u1",), relevant=("u1",)),
        _outcome(kind="no_answer"),
    )
    assert refusal.metrics["citation_precision"] is None
    assert refusal.metrics["citation_recall"] is None


def test_answer_without_citations_scores_zero_precision_and_recall() -> None:
    case = _case(expected_sources=({"doc_code": "D01", "unit_key": "k1"},))
    resolved = _resolved(unit_ids=("u1",), relevant=("u1",))
    result = score_case(case, resolved, _outcome(text="答案"))

    assert result.metrics["citation_precision"] == 0.0
    assert result.metrics["citation_recall"] == 0.0


# --------------------------------------------------------------------------- #
# §5.3 kind 正确 + 拒答样本按 should_refuse 判
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("actual", "expected", "status"),
    [
        ("answer", "answer", "pass"),
        ("answer", "ambiguous", "fail"),
        ("clarification", "clarification", "pass"),
        ("no_answer", "no_answer", "pass"),
        ("conflict", "conflict", "pass"),
        ("no_answer", "answer", "fail"),
    ],
)
def test_kind_correct_compares_expected_kind(actual: str, expected: str, status: str) -> None:
    case = _case(expected_kind=expected)
    result = score_case(case, _resolved(), _outcome(kind=actual))

    assert _check(result, "kind_correct").status == status


def test_kind_comparison_accepts_enum_and_plain_string() -> None:
    case = _case(expected_kind=OutcomeKind.ANSWER)
    result = score_case(case, _resolved(), _outcome(kind=OutcomeKind.ANSWER))

    assert _check(result, "kind_correct").status == "pass"


def test_refusal_checks_follow_should_refuse_flag() -> None:
    refusal_case = _case(
        expected_kind="no_answer", should_refuse=True, refusal_reason="safety"
    )
    refused = score_case(refusal_case, _resolved(), _outcome(kind="no_answer"))
    assert refused.refused is True
    assert _check(refused, "refusal_expected").status == "pass"
    assert _check(refused, "refusal_unexpected").status == "skipped"

    answerable = _case(expected_kind="answer")
    wrongly_refused = score_case(answerable, _resolved(), _outcome(kind="no_answer"))
    assert wrongly_refused.refused is True
    assert _check(wrongly_refused, "refusal_expected").status == "skipped"
    assert _check(wrongly_refused, "refusal_unexpected").status == "fail"


def test_is_refusal_covers_only_deliberate_non_answers() -> None:
    assert is_refusal("no_answer")
    assert is_refusal("not_found")
    assert is_refusal("refusal")
    for kind in ("answer", "clarification", "conflict", "ambiguous", "error", "service_error"):
        assert not is_refusal(kind)


# --------------------------------------------------------------------------- #
# §5.5 拒答三指标：混合样本下三者数值不同
# --------------------------------------------------------------------------- #


def test_refusal_metrics_are_three_independent_values() -> None:
    cases: list[CaseSpec] = []
    results: list[CaseResult] = []

    # 4 个应拒答案例：1 个真拒答（TP）、3 个未拒答（FN）
    for index in (1, 2, 3, 4):
        case = _case(
            f"S{index}",
            expected_kind="no_answer",
            should_refuse=True,
            refusal_reason="safety",
        )
        cases.append(case)
        results.append(
            score_case(
                case,
                _resolved(f"S{index}"),
                _outcome(kind="no_answer" if index == 1 else "answer"),
            )
        )

    # 3 个可答案例：1 个误拒（FP）、2 个正常回答（TN）
    for index in (1, 2, 3):
        case = _case(f"A{index}")
        cases.append(case)
        results.append(
            score_case(
                case,
                _resolved(f"A{index}"),
                _outcome(kind="no_answer" if index == 1 else "answer"),
            )
        )

    metrics = refusal_metrics(cases, results)

    assert metrics["refusal_recall"] == pytest.approx(0.25)
    assert metrics["false_refusal_rate"] == pytest.approx(1 / 3)
    assert metrics["refusal_precision"] == pytest.approx(0.5)
    assert len({round(value, 6) for value in metrics.values()}) == 3


def test_refusal_metrics_are_none_when_denominator_is_empty() -> None:
    case = _case("A1")
    result = score_case(case, _resolved("A1"), _outcome(kind="answer"))
    metrics = refusal_metrics([case], [result])

    assert metrics["refusal_recall"] is None
    assert metrics["false_refusal_rate"] == 0.0
    assert metrics["refusal_precision"] is None


# --------------------------------------------------------------------------- #
# §5.4 分页契约：total / returned / has_more / next_page 四项独立 check
# --------------------------------------------------------------------------- #


def test_pagination_contract_accepts_consistent_page() -> None:
    expected = {"total": 25, "returned": 10, "has_more": True, "next_page": 2}
    case = _case(expected_pagination=expected)
    result = score_case(case, _resolved(), _outcome(pagination=dict(expected)))

    for check_id in PAGINATION_IDS:
        assert _check(result, check_id).status == "pass"


def test_pagination_missing_fields_fail_each_check() -> None:
    case = _case(
        expected_pagination={"total": 25, "returned": 10, "has_more": True, "next_page": 2}
    )
    result = score_case(case, _resolved(), _outcome(pagination={}))

    for check_id in PAGINATION_IDS:
        check = _check(result, check_id)
        assert check.status == "fail"
        assert check.evidence["reason"] == "missing"


def test_pagination_type_errors_fail_each_check() -> None:
    case = _case(
        expected_pagination={"total": 25, "returned": 10, "has_more": True, "next_page": 2}
    )
    result = score_case(
        case,
        _resolved(),
        _outcome(pagination={"total": "25", "returned": 10.0, "has_more": 1, "next_page": "2"}),
    )

    for check_id in PAGINATION_IDS:
        check = _check(result, check_id)
        assert check.status == "fail"
        assert check.evidence["reason"] == "type"


def test_pagination_contract_beats_expectation_on_has_more() -> None:
    # total == returned 时 has_more 必须为 false；即使 case 期望 true 也不能算通过。
    expected = {"total": 10, "returned": 10, "has_more": True, "next_page": 2}
    case = _case(expected_pagination=expected)
    result = score_case(case, _resolved(), _outcome(pagination=dict(expected)))

    assert _check(result, "pagination_total").status == "pass"
    assert _check(result, "pagination_returned").status == "pass"
    assert _check(result, "pagination_has_more").status == "fail"
    assert _check(result, "pagination_next_page").status == "pass"


def test_pagination_next_page_must_be_null_when_no_more() -> None:
    expected = {"total": 10, "returned": 10, "has_more": False, "next_page": None}
    case = _case(expected_pagination=expected)
    result = score_case(
        case,
        _resolved(),
        _outcome(pagination={"total": 10, "returned": 10, "has_more": False, "next_page": 2}),
    )

    assert _check(result, "pagination_has_more").status == "pass"
    assert _check(result, "pagination_next_page").status == "fail"


def test_pagination_min_total_and_absent_expectation() -> None:
    case = _case(expected_pagination={"min_total": 40})
    ok = score_case(
        case,
        _resolved(),
        _outcome(pagination={"total": 40, "returned": 10, "has_more": True, "next_page": 2}),
    )
    assert _check(ok, "pagination_total").status == "pass"

    short = score_case(
        case,
        _resolved(),
        _outcome(pagination={"total": 39, "returned": 10, "has_more": True, "next_page": 2}),
    )
    assert _check(short, "pagination_total").status == "fail"

    no_expectation = score_case(
        _case(),
        _resolved(),
        _outcome(pagination={"total": 5, "returned": 5, "has_more": False, "next_page": None}),
    )
    for check_id in PAGINATION_IDS:
        assert _check(no_expectation, check_id).status == "pass"


def test_pagination_not_applicable_is_skipped() -> None:
    result = score_case(_case(), _resolved(), _outcome())

    for check_id in PAGINATION_IDS:
        check = _check(result, check_id)
        assert check.status == "skipped"
        assert check.evidence["reason"] == "no_expected_pagination"


# --------------------------------------------------------------------------- #
# §5.6 检索指标：unit 级去重、无 gold 不进分母、硬过滤违规、空召回
# --------------------------------------------------------------------------- #


def test_retrieval_metrics_dedupe_chunks_by_unit_and_compute_ndcg() -> None:
    case = _case(expected_sources=({"doc_code": "D01", "unit_key": "k1"},))
    resolved = _resolved(unit_ids=("u1", "u2"), relevant=("u1", "u2"))
    retrieved = (
        EvalRetrieved(doc_code="D01", unit_ids=("u9",)),
        EvalRetrieved(doc_code="D01", unit_ids=("u1",)),
        EvalRetrieved(doc_code="D01", unit_ids=("u1",)),  # 同 unit 的第二个 chunk
        EvalRetrieved(doc_code="D01", unit_ids=("u2",)),
    )
    result = score_case(case, resolved, _outcome(retrieved=retrieved))

    assert result.metrics["Recall@10"] == 1.0
    assert result.metrics["MRR@10"] == pytest.approx(0.5)
    # T110：排名按 chunk 计。重复 chunk 仍占第 3 位（不贡献 gain），u2 在第 4 位。
    assert result.metrics["retrieved_units"] == 3
    expected_ndcg = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
    assert result.metrics["nDCG@10"] == pytest.approx(expected_ndcg)


def test_retrieval_metrics_ignore_units_beyond_top_10() -> None:
    case = _case(expected_sources=({"doc_code": "D01", "unit_key": "k1"},))
    resolved = _resolved(unit_ids=("u1",), relevant=("u1",))
    noise = tuple(EvalRetrieved(doc_code="D02", unit_ids=(f"n{index}",)) for index in range(10))
    retrieved = noise + (EvalRetrieved(doc_code="D01", unit_ids=("u1",)),)
    result = score_case(case, resolved, _outcome(retrieved=retrieved))

    assert result.metrics["Recall@10"] == 0.0
    assert result.metrics["MRR@10"] == 0.0
    assert result.metrics["nDCG@10"] == 0.0


def test_retrieval_metrics_exclude_cases_without_gold() -> None:
    gold_case = _case("G01", expected_sources=({"doc_code": "D01", "unit_key": "k1"},))
    gold = score_case(
        gold_case,
        _resolved("G01", unit_ids=("u1",), relevant=("u1",)),
        _outcome(retrieved=(EvalRetrieved(doc_code="D01", unit_ids=("u1",)),)),
    )
    no_gold_case = _case("N01")
    no_gold = score_case(
        no_gold_case,
        _resolved("N01"),
        _outcome(
            retrieved=(
                EvalRetrieved(
                    doc_code="D02", unit_ids=("u9",), hard_filter_violation="stale"
                ),
            )
        ),
    )

    metrics = retrieval_metrics([gold, no_gold])

    assert metrics["Recall@10"] == 1.0
    assert metrics["MRR@10"] == 1.0
    assert metrics["nDCG@10"] == 1.0
    assert metrics["empty_recall_rate"] == 0.0
    # 无 gold 的 case 不进入检索指标分母（含硬过滤违规率）
    assert metrics["hard_filter_violation_rate"] == 0.0
    assert no_gold.metrics["Recall@10"] is None


def test_empty_recall_rate_counts_gold_cases_with_no_retrieved_units() -> None:
    case = _case("G01", expected_sources=({"doc_code": "D01", "unit_key": "k1"},))
    result = score_case(
        case, _resolved("G01", unit_ids=("u1",), relevant=("u1",)), _outcome(retrieved=())
    )

    metrics = retrieval_metrics([result])
    assert metrics["empty_recall_rate"] == 1.0
    assert metrics["Recall@10"] == 0.0


def test_hard_filter_violation_rate_counts_explicit_and_forbidden_units() -> None:
    case = _case(
        expected_sources=({"doc_code": "D01", "unit_key": "k1"},),
        forbidden_sources=({"doc_code": "D08"},),
    )
    resolved = _resolved(unit_ids=("u1",), relevant=("u1",))
    retrieved = (
        EvalRetrieved(doc_code="D01", unit_ids=("u1",)),
        EvalRetrieved(doc_code="D08", unit_ids=("u9",), unit_key="page:3"),
        EvalRetrieved(doc_code="D01", unit_ids=("u2",), hard_filter_violation="stale"),
    )
    result = score_case(case, resolved, _outcome(retrieved=retrieved))

    assert result.metrics["retrieved_units"] == 3
    assert result.metrics["hard_filter_violations"] == 2
    assert retrieval_metrics([result])["hard_filter_violation_rate"] == pytest.approx(2 / 3)


# --------------------------------------------------------------------------- #
# 延迟与成本
# --------------------------------------------------------------------------- #


def test_trace_latency_tokens_and_cost_are_extracted() -> None:
    trace = _trace(latency=120, tokens={"input": 100, "output": 20}, cost={"cny": 0.003})
    result = score_case(_case(), _resolved(), _outcome(), trace)

    assert result.latency_ms == 120
    assert result.tokens_in == 100
    assert result.tokens_out == 20
    assert result.cost_cny == pytest.approx(0.003)


def test_invalid_trace_values_are_ignored_without_crashing() -> None:
    trace = TraceRecord(
        latency_ms=-5, token_usage_json="not-json", cost_json='{"cny": -1}'
    )
    result = score_case(_case(), _resolved(), _outcome(), trace)

    assert result.latency_ms is None
    assert result.tokens_in is None
    assert result.tokens_out is None
    assert result.cost_cny is None


def test_latency_percentiles_use_nearest_rank() -> None:
    results = [
        score_case(
            _case(f"C{index}"),
            _resolved(f"C{index}"),
            _outcome(),
            _trace(latency=latency),
        )
        for index, latency in enumerate((10, 20, 30, 40, 100))
    ]
    metrics = latency_metrics(results)

    assert metrics["p50_latency_ms"] == 30
    assert metrics["p95_latency_ms"] == 100


def test_cost_metrics_sum_tokens_and_divide_by_reported_cases() -> None:
    results = [
        score_case(
            _case("C1"),
            _resolved("C1"),
            _outcome(),
            _trace(tokens={"input": 100, "output": 20}, cost={"cny": 0.003}),
        ),
        score_case(
            _case("C2"),
            _resolved("C2"),
            _outcome(),
            _trace(tokens={"input": 50, "output": 10}, cost={"cny": 0.002}),
        ),
    ]
    metrics = cost_metrics(results)

    assert metrics["tokens_in_total"] == 150
    assert metrics["tokens_out_total"] == 30
    assert metrics["cost_total_cny"] == pytest.approx(0.005)
    assert metrics["cost_per_case_cny"] == pytest.approx(0.0025)


# --------------------------------------------------------------------------- #
# §5.7 确定性、稳定 id、OCR 跳过与结果序列化
# --------------------------------------------------------------------------- #


def test_score_case_is_deterministic_with_stable_check_ids() -> None:
    case = _case(
        expected_values=("12",),
        expected_sources=({"doc_code": "D01", "unit_key": "k1"},),
        reference_answer="12",
        expected_pagination={"total": 25, "returned": 10, "has_more": True, "next_page": 2},
    )
    resolved = _resolved(
        unit_ids=("u1",),
        relevant=("u1",),
        sources=(
            ResolvedSource(
                doc_code="D01", doc_id="D01", unit_ids=("u1",), unit_keys=("k1",)
            ),
        ),
    )
    outcome = _outcome(
        text="共12件",
        citations=(EvalCitation(doc_code="D01", unit_key="k1", unit_ids=("u1",)),),
        pagination={"total": 25, "returned": 10, "has_more": True, "next_page": 2},
        retrieved=(EvalRetrieved(doc_code="D01", unit_ids=("u1",)),),
    )

    first = score_case(case, resolved, outcome, _trace(latency=5))
    second = score_case(case, resolved, outcome, _trace(latency=5))

    assert first == second
    assert json.dumps(first.to_dict(), ensure_ascii=False, sort_keys=True) == json.dumps(
        second.to_dict(), ensure_ascii=False, sort_keys=True
    )
    ids = [check.check_id for check in first.checks]
    assert len(ids) == len(set(ids))
    assert set(ids) == CHECK_IDS
    assert first.status in {"pass", "fail"}
    for check in first.checks:
        assert check.status in {"pass", "fail", "skipped"}
        json.dumps(dict(check.evidence), ensure_ascii=False)
    json.dumps(first.to_dict(), ensure_ascii=False)


def test_score_case_rejects_resolved_from_another_case() -> None:
    with pytest.raises(ValueError):
        score_case(_case("A"), _resolved("B"), _outcome())


def test_ocr_case_is_skipped_requires_ocr() -> None:
    case = _case("Q33", requires_ocr=True)
    result = score_case(case, _resolved("Q33", skipped=True), _outcome())

    assert result.status == "skipped_requires_ocr"
    assert result.metrics == {}
    assert all(check.status == "skipped" for check in result.checks)


def test_real_badcase_refusal_row_scores_without_gold() -> None:
    cases = {case.case_id: case for case in load_cases(EVAL_DIR / "badcase.jsonl")}
    case = cases["N12"]
    result = score_case(case, _resolved("N12"), _outcome(kind="no_answer"))

    assert result.status == "pass"
    assert _check(result, "refusal_expected").status == "pass"
    assert _check(result, "value_hit").status == "skipped"
    assert _check(result, "source_hit").status == "skipped"


def test_answer_metrics_are_mean_over_applicable_cases() -> None:
    cases = [
        _case("C1", expected_values=("12",), reference_answer="12"),
        _case("C2", expected_values=("12",), reference_answer="12"),
    ]
    results = [
        score_case(cases[0], _resolved("C1"), _outcome(text="12")),
        score_case(cases[1], _resolved("C2"), _outcome(text="99")),
    ]

    metrics = answer_metrics(results)

    assert metrics["value_hit"] == pytest.approx(0.5)
    assert metrics["kind_correct"] == 1.0


def test_aggregate_metrics_combines_all_metric_families() -> None:
    answer_case = _case(
        "A1",
        expected_values=("12",),
        expected_sources=({"doc_code": "D01", "unit_key": "k1"},),
        reference_answer="12",
    )
    answer_result = score_case(
        answer_case,
        _resolved(
            "A1",
            unit_ids=("u1",),
            relevant=("u1",),
            sources=(
                ResolvedSource(
                    doc_code="D01", doc_id="D01", unit_ids=("u1",), unit_keys=("k1",)
                ),
            ),
        ),
        _outcome(
            text="12",
            citations=(EvalCitation(doc_code="D01", unit_key="k1", unit_ids=("u1",)),),
            retrieved=(EvalRetrieved(doc_code="D01", unit_ids=("u1",)),),
        ),
        _trace(latency=10, tokens={"input": 100, "output": 20}, cost={"cny": 0.003}),
    )
    refusal_case = _case(
        "R1", expected_kind="no_answer", should_refuse=True, refusal_reason="safety"
    )
    refusal_result = score_case(
        refusal_case,
        _resolved("R1"),
        _outcome(kind="no_answer"),
        _trace(latency=30, tokens={"input": 50, "output": 10}, cost={"cny": 0.002}),
    )

    metrics = aggregate_metrics([answer_case, refusal_case], [answer_result, refusal_result])

    assert set(metrics) == {
        "case_count",
        "scored_count",
        "skipped_count",
        "value_hit",
        "source_hit",
        "kind_correct",
        "citation_precision",
        "citation_recall",
        "Recall@10",
        "MRR@10",
        "nDCG@10",
        "hard_filter_violation_rate",
        "empty_recall_rate",
        "refusal_recall",
        "false_refusal_rate",
        "refusal_precision",
        "p50_latency_ms",
        "p95_latency_ms",
        "tokens_in_total",
        "tokens_out_total",
        "cost_total_cny",
        "cost_per_case_cny",
    }
    assert metrics["case_count"] == 2
    assert metrics["scored_count"] == 2
    assert metrics["skipped_count"] == 0
    assert metrics["value_hit"] == 1.0
    assert metrics["kind_correct"] == 1.0
    assert metrics["refusal_recall"] == 1.0
    assert metrics["false_refusal_rate"] == 0.0
    assert metrics["refusal_precision"] == 1.0
    assert metrics["p50_latency_ms"] == 10
    assert metrics["p95_latency_ms"] == 30
    assert metrics["tokens_in_total"] == 150
    assert metrics["cost_per_case_cny"] == pytest.approx(0.0025)


def test_aggregate_metrics_counts_skipped_ocr_cases_separately() -> None:
    ocr_case = _case("Q33", requires_ocr=True)
    ocr_result = score_case(ocr_case, _resolved("Q33", skipped=True), _outcome())
    answer_case = _case("A1")
    answer_result = score_case(answer_case, _resolved("A1"), _outcome())

    metrics = aggregate_metrics([ocr_case, answer_case], [ocr_result, answer_result])

    assert metrics["case_count"] == 2
    assert metrics["scored_count"] == 1
    assert metrics["skipped_count"] == 1
    assert metrics["value_hit"] is None
    assert metrics["p50_latency_ms"] is None
