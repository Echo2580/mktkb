"""T004b independent reviewer probe (outside the repository).

Reads only the delivered public API; does not write to the repo, does not call any
provider, does not use pytest.  Every line is a self-contained assertion result.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import fields
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.gold import ResolvedGold, ResolvedSource
from mktkb.evaluation import scorers as S
from mktkb.evaluation.scorers import CaseResult  # noqa: F401  (import check)
from mktkb.observability.contracts import TraceRecord

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS " if condition else "FAIL ") + name + ((" | " + detail) if detail else ""))
    if not condition:
        FAILURES.append(name)


def section(name: str) -> None:
    print("\n== " + name + " ==")


def mk_case(case_id: str = "C01", **overrides) -> CaseSpec:
    values = dict(
        case_id=case_id,
        suite="probe",
        split="dev",
        stratum="exact",
        business_date="2026-10-28",
        question="合成测试问题",
        expected_kind="answer",
        expected_values=(),
        expected_sources=(),
        relevant_units=(),
        reference_answer="",
        should_refuse=False,
        refusal_reason=None,
        forbidden_values=(),
        forbidden_sources=(),
        expected_pagination=None,
        requires_ocr=False,
        labeler="reviewer",
        label_version="probe-1",
    )
    values.update(overrides)
    return CaseSpec(**values)


def mk_resolved(case_id: str = "C01", **overrides) -> ResolvedGold:
    values = dict(
        case_id=case_id,
        requires_ocr=False,
        skipped=False,
        sources=(),
        unit_ids=(),
        relevant_unit_ids=(),
    )
    values.update(overrides)
    return ResolvedGold(**values)


def mk_outcome(**overrides) -> S.EvalOutcome:
    values = dict(kind="answer", text="", citations=(), facts=(), pagination={}, trace_id="tr-1", path="rag", retrieved=())
    values.update(overrides)
    return S.EvalOutcome(**values)


def status(result: CaseResult, check_id: str) -> str:
    item = result.check(check_id)
    assert item is not None, check_id
    return item.status


def evidence(result: CaseResult, check_id: str) -> dict:
    item = result.check(check_id)
    assert item is not None, check_id
    return dict(item.evidence)


# ---------------------------------------------------------------------------
section("A. CHECK_IDS inventory, evidence, JSON stability")
# ---------------------------------------------------------------------------
expected_ids = (
    "value_hit", "value_forbidden", "value_no_fabricated", "source_hit", "source_forbidden",
    "kind_correct", "refusal_expected", "refusal_unexpected",
    "pagination_total", "pagination_returned", "pagination_has_more", "pagination_next_page",
)
check("CHECK_IDS is exactly 12 and ordered", tuple(S.CHECK_IDS) == expected_ids, repr(tuple(S.CHECK_IDS)))
check("PAGINATION_CHECK_IDS is exactly 4", tuple(S.PAGINATION_CHECK_IDS) == expected_ids[-4:])

sink_case = mk_case(
    expected_values=("12",),
    expected_sources=({"doc_code": "D01", "unit_key": "k1"},),
    reference_answer="共12件",
    expected_pagination={"total": 25, "returned": 10, "has_more": True, "next_page": 2},
)
sink_resolved = mk_resolved(
    unit_ids=("u1",),
    relevant_unit_ids=("u1",),
    sources=(ResolvedSource(doc_code="D01", doc_id="D01", unit_ids=("u1",), unit_keys=("k1",)),),
)
sink_outcome = mk_outcome(
    text="共12件",
    citations=(S.EvalCitation(doc_code="D01", unit_key="k1", unit_ids=("u1",)),),
    pagination={"total": 25, "returned": 10, "has_more": True, "next_page": 2},
    retrieved=(S.EvalRetrieved(doc_code="D01", unit_ids=("u1",)),),
)
sink_trace = TraceRecord(
    trace_id="tr-1", latency_ms=5, token_usage_json='{"input": 1, "output": 2}', cost_json='{"cny": 0.01}'
)
sink = S.score_case(sink_case, sink_resolved, sink_outcome, sink_trace)
ids = [item.check_id for item in sink.checks]
check("normal case has 12 unique checks", len(ids) == 12 and len(set(ids)) == 12, repr(ids))
check("normal case check ids equal CHECK_IDS", set(ids) == set(S.CHECK_IDS))
check("normal case status pass", sink.status == "pass", sink.status)
allowed_status = {"pass", "fail", "skipped", "skipped_requires_ocr"}
check("every check status is a declared status", all(item.status in allowed_status for item in sink.checks))
check("every check evidence is a JSON object", all(isinstance(item.evidence, dict) and (json.dumps(dict(item.evidence), ensure_ascii=False) is not None) for item in sink.checks))
check("every non-skipped check carries evidence keys or explicit checked count", all(item.evidence for item in sink.checks if item.status != "skipped"))
print("SINK_STATUSES " + json.dumps({item.check_id: item.status for item in sink.checks}, ensure_ascii=False))

# Every check must be able to fail on an input; no permanent PASS.
triggers: dict[str, CaseResult] = {}
triggers["value_hit"] = S.score_case(mk_case(expected_values=("12",), reference_answer="12"), mk_resolved(), mk_outcome(text="没有"))
triggers["value_forbidden"] = S.score_case(mk_case(forbidden_values=("停售",)), mk_resolved(), mk_outcome(text="已停售"))
triggers["value_no_fabricated"] = S.score_case(mk_case(expected_values=("12",), reference_answer="12"), mk_resolved(), mk_outcome(text="12 和 13"))
triggers["source_hit"] = S.score_case(
    mk_case(expected_sources=({"doc_code": "D01", "unit_key": "k1"},)),
    mk_resolved(
        unit_ids=("u1",),
        relevant_unit_ids=("u1",),
        sources=(ResolvedSource(doc_code="D01", doc_id="D01", unit_ids=("u1",), unit_keys=("k1",)),),
    ),
    mk_outcome(citations=(S.EvalCitation(doc_code="D01", unit_key="k9", unit_ids=("u9",)),)),
)
triggers["source_forbidden"] = S.score_case(
    mk_case(forbidden_sources=({"doc_code": "D08"},)),
    mk_resolved(),
    mk_outcome(citations=(S.EvalCitation(doc_code="D08", unit_key="page:3"),)),
)
triggers["kind_correct"] = S.score_case(mk_case(expected_kind="answer"), mk_resolved(), mk_outcome(kind="ambiguous"))
triggers["refusal_expected"] = S.score_case(
    mk_case(expected_kind="no_answer", should_refuse=True, refusal_reason="safety"), mk_resolved(), mk_outcome(kind="answer")
)
triggers["refusal_unexpected"] = S.score_case(mk_case(expected_kind="answer"), mk_resolved(), mk_outcome(kind="no_answer"))
p_expected = {"total": 25, "returned": 10, "has_more": True, "next_page": 2}
triggers["pagination_total"] = S.score_case(mk_case(expected_pagination=p_expected), mk_resolved(), mk_outcome(pagination={"returned": 10, "has_more": True, "next_page": 2}))
triggers["pagination_returned"] = S.score_case(mk_case(expected_pagination=p_expected), mk_resolved(), mk_outcome(pagination={"total": 25, "has_more": True, "next_page": 2}))
triggers["pagination_has_more"] = S.score_case(mk_case(expected_pagination=p_expected), mk_resolved(), mk_outcome(pagination={"total": 25, "returned": 10, "next_page": 2}))
triggers["pagination_next_page"] = S.score_case(mk_case(expected_pagination=p_expected), mk_resolved(), mk_outcome(pagination={"total": 25, "returned": 10, "has_more": True}))
for check_id, result in triggers.items():
    check("check can fail: " + check_id, status(result, check_id) == "fail", str(evidence(result, check_id)))
check("all 12 check ids are covered by a failing probe", set(triggers) == set(S.CHECK_IDS))

# A refusal case and a no-gold case still expose the full 12 ids.
refusal_case = mk_case("R1", expected_kind="no_answer", should_refuse=True, refusal_reason="safety")
refusal_case_result = S.score_case(refusal_case, mk_resolved("R1"), mk_outcome(kind="no_answer"))
no_gold = S.score_case(mk_case("N1"), mk_resolved("N1"), mk_outcome())
check("refusal case still has 12 checks", len(refusal_case_result.checks) == 12)
check("no-gold case still has 12 checks", len(no_gold.checks) == 12)
ocr = S.score_case(mk_case("O1", requires_ocr=True), mk_resolved("O1", requires_ocr=True, skipped=True), mk_outcome())
check("OCR case is explicit skipped_requires_ocr with one scored check", ocr.status == "skipped_requires_ocr" and [c.check_id for c in ocr.checks] == ["scored"] and ocr.metrics == {})

# ---------------------------------------------------------------------------
section("B. Value normalization and number token boundaries")
# ---------------------------------------------------------------------------
value_cases = [
    ("Ｂ区１号货架", "B区1号货架", True),
    ("b区1号货架", "B区1号货架", True),
    ("B区 1 号货架", "B区1号货架", True),
    ("B区  1   号货架", "B区1号货架", True),
    ("单价 １．５ 元", "1.5", True),
    ("共120件", "12", False),
    ("120", "12", False),
    ("12.5元", "12", False),
    ("B区12号货架", "B区1号货架", False),
    ("1 2", "12", False),
    ("温度-12度", "12", False),
    ("价格 － 5 元", "5元", False),
    ("温度-12度", "-12", True),
    ("012", "12", True),
    ("价格12.5元", "价格12", False),
    ("价格12.5元", "价格12.5", True),
]
for text, value, wanted in value_cases:
    got = S.check_value(text, value)
    check(f"check_value({text!r}, {value!r}) == {wanted}", got is wanted, f"got={got}")
check("normalize_text NFKC/casefold/space", S.normalize_text("  Ｂ\u00a0区\u3000１ 号 ") == "b 区 1 号", S.normalize_text("  Ｂ\u00a0区\u3000１ 号 "))
check("normalize_text removes invisible", S.normalize_text("a\u200bb\ufeffc") == "abc")

# Mutation: remove normalization; the full-width value check must flip pass -> fail.
norm_before = S.score_case(mk_case(expected_values=("B区1号货架",)), mk_resolved(), mk_outcome(text="Ｂ区１号货架"))
norm_before_status = status(norm_before, "value_hit")
orig_normalize = S.normalize_text
try:
    S.normalize_text = lambda value: value  # type: ignore[assignment]
    norm_after = S.score_case(mk_case(expected_values=("B区1号货架",)), mk_resolved(), mk_outcome(text="Ｂ区１号货架"))
    norm_after_status = status(norm_after, "value_hit")
finally:
    S.normalize_text = orig_normalize  # type: ignore[assignment]
check("normalization mutation flips value_hit pass->fail", norm_before_status == "pass" and norm_after_status == "fail", f"{norm_before_status}->{norm_after_status}")

# ---------------------------------------------------------------------------
section("C. value_no_fabricated strictness / false-positive surface")
# ---------------------------------------------------------------------------
fabrication_cases = [
    ("extra layer/count", mk_case(expected_values=("B区1号货架",), reference_answer="B区1号货架", question="海报在哪"), mk_outcome(text="B区1号货架第2层，共3张")),
    ("doc code", mk_case(expected_values=("12",), reference_answer="12", question="数量多少"), mk_outcome(text="12件，见D09")),
    ("version string", mk_case(expected_values=("12",), reference_answer="12", question="数量多少"), mk_outcome(text="12（v2.1）")),
    ("page number", mk_case(expected_values=("B区1号货架",), reference_answer="B区1号货架", question="海报在哪"), mk_outcome(text="见第8页")),
    ("thousands separator", mk_case(expected_values=("1000",), reference_answer="1000", question="数量多少"), mk_outcome(text="1,000")),
]
for label, case, outcome in fabrication_cases:
    result = S.score_case(case, mk_resolved(), outcome)
    print("FABRICATION " + label + " value_hit=" + status(result, "value_hit") + " no_fab=" + status(result, "value_no_fabricated") + " evidence=" + json.dumps(evidence(result, "value_no_fabricated"), ensure_ascii=False))
    check("false-positive surface records extra numbers: " + label, status(result, "value_no_fabricated") == "fail", json.dumps(evidence(result, "value_no_fabricated"), ensure_ascii=False))
negative = S.score_case(mk_case(expected_values=("12",), reference_answer="12", question="数量多少"), mk_resolved(), mk_outcome(text="-12"))
check("sign-blind no_fabricated: -12 passes when 12 is allowed", status(negative, "value_no_fabricated") == "pass" and status(negative, "value_hit") == "fail", str(evidence(negative, "value_no_fabricated")))

# ---------------------------------------------------------------------------
section("D. Source matching and citation precision/recall with unit dedup")
# ---------------------------------------------------------------------------
source_case = mk_case(
    expected_sources=({"doc_code": "D01", "unit_key": "k1"},),
)
source_resolved = mk_resolved(
    unit_ids=("u1", "u2"),
    relevant_unit_ids=("u1", "u2"),
    sources=(ResolvedSource(doc_code="D01", doc_id="D01", unit_ids=("u1", "u2"), unit_keys=("k1",)),),
)
cit_dedup = S.score_case(
    source_case,
    source_resolved,
    mk_outcome(citations=(
        S.EvalCitation(doc_code="D01", unit_key="k1", unit_ids=("u1",)),
        S.EvalCitation(doc_code="D01", unit_key="k1", unit_ids=("u1",)),
        S.EvalCitation(doc_code="D01", unit_key="k3", unit_ids=("u3",)),
    )),
)
check("citation dedup precision == 0.5", cit_dedup.metrics["citation_precision"] == 0.5, repr(cit_dedup.metrics))
check("citation dedup recall == 0.5", cit_dedup.metrics["citation_recall"] == 0.5, repr(cit_dedup.metrics))
manual_no_dedup = 2 / 3  # u1,u1,u3 citations; two hits (u1 twice) / three chunks
check("counterfactual no-dedup precision would be 2/3, so dedup changes the metric", manual_no_dedup != cit_dedup.metrics["citation_precision"], repr(manual_no_dedup))
# Mutation: replace citation metric with a no-dedup implementation; precision must change.
orig_citation_metrics = S._citation_case_metrics


def _no_dedup_citation_metrics(case, outcome, resolved, refused):
    relevant = {("unit", str(item)) for item in resolved.relevant_unit_ids}
    if not relevant or resolved.skipped or case.should_refuse or refused:
        return None, None
    cited = [identity for citation in outcome.citations for identity in S._citation_identities(citation)]
    hits = sum(1 for identity in cited if identity in relevant)
    return (hits / len(cited) if cited else 0.0), hits / len(relevant)


try:
    S._citation_case_metrics = _no_dedup_citation_metrics  # type: ignore[assignment]
    mutated_cit = S.score_case(
        source_case,
        source_resolved,
        mk_outcome(citations=(
            S.EvalCitation(doc_code="D01", unit_key="k1", unit_ids=("u1",)),
            S.EvalCitation(doc_code="D01", unit_key="k1", unit_ids=("u1",)),
            S.EvalCitation(doc_code="D01", unit_key="k3", unit_ids=("u3",)),
        )),
    )
    mutated_precision = mutated_cit.metrics["citation_precision"]
finally:
    S._citation_case_metrics = orig_citation_metrics  # type: ignore[assignment]
check("citation unit-dedup mutation flips precision 0.5 -> 2/3", cit_dedup.metrics["citation_precision"] == 0.5 and mutated_precision == 2 / 3, repr(mutated_precision))
multi_unit = S.score_case(
    mk_case(expected_sources=({"doc_code": "D01", "unit_key": "k1"},)),
    source_resolved,
    mk_outcome(citations=(S.EvalCitation(doc_code="D01", unit_ids=("u1", "u2")),)),
)
check("multi-unit citation precision/recall == 1.0", multi_unit.metrics["citation_precision"] == 1.0 and multi_unit.metrics["citation_recall"] == 1.0)
no_cit = S.score_case(mk_case(expected_sources=({"doc_code": "D01", "unit_key": "k1"},)), source_resolved, mk_outcome())
check("no citations -> precision/recall 0.0", no_cit.metrics["citation_precision"] == 0.0 and no_cit.metrics["citation_recall"] == 0.0)
no_gold_cit = S.score_case(mk_case(), mk_resolved(), mk_outcome(citations=(S.EvalCitation(doc_code="D01", unit_ids=("u1",)),)))
check("no gold -> citation metrics None", no_gold_cit.metrics["citation_precision"] is None and no_gold_cit.metrics["citation_recall"] is None)

# Fail closed when unit_ids are missing but a matching stable unit_key is present.
missing_ids = S.score_case(
    mk_case(expected_sources=({"doc_code": "D01", "unit_key": "k1"},)),
    source_resolved,
    mk_outcome(citations=(S.EvalCitation(doc_code="D01", unit_key="k1"),)),
)
check("missing citation unit_ids: source_hit can still pass via unit_key", status(missing_ids, "source_hit") == "pass")
check("missing citation unit_ids: citation precision/recall fail closed to 0.0", missing_ids.metrics["citation_precision"] == 0.0 and missing_ids.metrics["citation_recall"] == 0.0, repr(missing_ids.metrics))
# Conflicting unit_ids + matching unit_key (input inconsistency) -> source_hit is lenient.
conflict_ids = S.score_case(
    mk_case(expected_sources=({"doc_code": "D01", "unit_key": "k1"},)),
    source_resolved,
    mk_outcome(citations=(S.EvalCitation(doc_code="D01", unit_key="k1", unit_ids=("u9",)),)),
)
print("CONFLICT_IDS source_hit=" + status(conflict_ids, "source_hit") + " precision=" + repr(conflict_ids.metrics["citation_precision"]))
check("conflicting unit_ids + matching key: source_hit passes while citation metric fails closed", status(conflict_ids, "source_hit") == "pass" and conflict_ids.metrics["citation_precision"] == 0.0)

# ---------------------------------------------------------------------------
section("E. Retrieval metrics: unit dedup, top-10, no-gold, hard filter, empty")
# ---------------------------------------------------------------------------
ret_case = mk_case("G01")
ret_resolved = mk_resolved("G01", unit_ids=("u1", "u2"), relevant_unit_ids=("u1", "u2"))
retrieved = (
    S.EvalRetrieved(doc_code="D01", unit_ids=("u9",)),
    S.EvalRetrieved(doc_code="D01", unit_ids=("u1",), chunk_id="c1"),
    S.EvalRetrieved(doc_code="D01", unit_ids=("u1",), chunk_id="c2"),
    S.EvalRetrieved(doc_code="D01", unit_ids=("u2",), chunk_id="c3"),
)
ret = S.score_case(ret_case, ret_resolved, mk_outcome(retrieved=retrieved))
expected_ndcg = (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
check("dedup Recall@10 == 1.0", ret.metrics["Recall@10"] == 1.0, repr(ret.metrics))
check("dedup MRR@10 == 0.5", ret.metrics["MRR@10"] == 0.5, repr(ret.metrics))
check("dedup nDCG@10 hand value", abs(ret.metrics["nDCG@10"] - expected_ndcg) < 1e-12, f"{ret.metrics['nDCG@10']} vs {expected_ndcg}")
# Counterfactual: duplicate chunk of a relevant unit would be counted twice.
no_dedup_dcg = 1.0 + 1 / math.log2(3) + 1 / math.log2(4)  # u1 at 1, duplicate u1 at 2, u2 at 3
ideal = 1 + 1 / math.log2(3)
print("NO_DEDUP_NDCG " + repr(no_dedup_dcg / ideal) + " (>1 would be invalid)")
check("unit dedup is necessary: counterfactual no-dedup nDCG > 1", no_dedup_dcg / ideal > 1.0)
same_unit_ranks = S.score_case(
    mk_case("G02"), mk_resolved("G02", unit_ids=("u1", "u2"), relevant_unit_ids=("u1", "u2")),
    mk_outcome(retrieved=(
        S.EvalRetrieved(doc_code="D01", unit_ids=("u1",), chunk_id="a"),
        S.EvalRetrieved(doc_code="D01", unit_ids=("u1",), chunk_id="b"),
        S.EvalRetrieved(doc_code="D01", unit_ids=("u2",), chunk_id="c"),
    )),
)
check("same unit at different chunk ranks does not inflate MRR/nDCG", same_unit_ranks.metrics["MRR@10"] == 1.0 and same_unit_ranks.metrics["nDCG@10"] == 1.0, repr(same_unit_ranks.metrics))
noise = tuple(S.EvalRetrieved(doc_code="D02", unit_ids=(f"n{i}",)) for i in range(10))
cut = S.score_case(
    mk_case("G03"), mk_resolved("G03", unit_ids=("u1",), relevant_unit_ids=("u1",)),
    mk_outcome(retrieved=noise + (S.EvalRetrieved(doc_code="D01", unit_ids=("u1",)),)),
)
check("unit after top-10 does not count", cut.metrics["Recall@10"] == 0.0 and cut.metrics["MRR@10"] == 0.0 and cut.metrics["nDCG@10"] == 0.0)
empty = S.score_case(mk_case("G04"), mk_resolved("G04", unit_ids=("u1",), relevant_unit_ids=("u1",)), mk_outcome(retrieved=()))
check("empty recall case -> Recall 0, empty_recall 1", empty.metrics["Recall@10"] == 0.0 and empty.metrics["empty_recall"] == 1.0)
gold_result = S.score_case(mk_case("G05"), mk_resolved("G05", unit_ids=("u1",), relevant_unit_ids=("u1",)), mk_outcome(retrieved=(S.EvalRetrieved(doc_code="D01", unit_ids=("u1",)),)))
no_gold_ret = S.score_case(mk_case("N05"), mk_resolved("N05"), mk_outcome(retrieved=(S.EvalRetrieved(doc_code="D02", unit_ids=("u9",), hard_filter_violation="stale"),)))
agg_ret = S.retrieval_metrics([gold_result, no_gold_ret])
check("no-gold case excluded from all retrieval denominators", agg_ret["Recall@10"] == 1.0 and agg_ret["empty_recall_rate"] == 0.0 and agg_ret["hard_filter_violation_rate"] == 0.0 and no_gold_ret.metrics["Recall@10"] is None, repr(agg_ret))
hf_case = mk_case("G06", forbidden_sources=({"doc_code": "D08"},))
hf_resolved = mk_resolved("G06", unit_ids=("u1",), relevant_unit_ids=("u1",))
hf = S.score_case(hf_case, hf_resolved, mk_outcome(retrieved=(
    S.EvalRetrieved(doc_code="D01", unit_ids=("u1",)),
    S.EvalRetrieved(doc_code="D08", unit_ids=("u9",), unit_key="page:3"),
    S.EvalRetrieved(doc_code="D01", unit_ids=("u2",), hard_filter_violation="stale"),
)))
check("hard filter violations count explicit + forbidden units", hf.metrics["retrieved_units"] == 3 and hf.metrics["hard_filter_violations"] == 2, repr(hf.metrics))
check("hard filter rate 2/3", abs(S.retrieval_metrics([hf])["hard_filter_violation_rate"] - 2 / 3) < 1e-12)
missing_ret_ids = S.score_case(
    mk_case("G07"), mk_resolved("G07", unit_ids=("u1",), relevant_unit_ids=("u1",)),
    mk_outcome(retrieved=(S.EvalRetrieved(doc_code="D01", unit_key="k1"),)),
)
check("missing retrieved unit_ids: fail closed to 0, not crash", missing_ret_ids.metrics["Recall@10"] == 0.0 and missing_ret_ids.metrics["MRR@10"] == 0.0 and missing_ret_ids.metrics["nDCG@10"] == 0.0 and missing_ret_ids.metrics["retrieved_units"] == 1, repr(missing_ret_ids.metrics))
check("missing retrieved unit_ids: empty_recall is 0 (not unknown)", missing_ret_ids.metrics["empty_recall"] == 0.0, repr(missing_ret_ids.metrics))

# ---------------------------------------------------------------------------
section("F. Pagination contract")
# ---------------------------------------------------------------------------
p_ok = {"total": 25, "returned": 10, "has_more": True, "next_page": 2}
ok = S.score_case(mk_case(expected_pagination=p_ok), mk_resolved(), mk_outcome(pagination=dict(p_ok)))
check("consistent pagination all pass", all(status(ok, cid) == "pass" for cid in S.PAGINATION_CHECK_IDS), repr({c: status(ok, c) for c in S.PAGINATION_CHECK_IDS}))
for missing in p_ok:
    actual = {k: v for k, v in p_ok.items() if k != missing}
    r = S.score_case(mk_case(expected_pagination=p_ok), mk_resolved(), mk_outcome(pagination=actual))
    check("missing " + missing + " fails its own check", status(r, "pagination_" + missing) == "fail" and evidence(r, "pagination_" + missing).get("reason") == "missing", repr(evidence(r, "pagination_" + missing)))
type_actual = {"total": "25", "returned": 10.0, "has_more": 1, "next_page": "2"}
type_r = S.score_case(mk_case(expected_pagination=p_ok), mk_resolved(), mk_outcome(pagination=type_actual))
for cid in S.PAGINATION_CHECK_IDS:
    check("type error fails " + cid, status(type_r, cid) == "fail" and evidence(type_r, cid).get("reason") == "type", repr(evidence(type_r, cid)))
contradict = S.score_case(mk_case(expected_pagination={"total": 10, "returned": 10, "has_more": True, "next_page": 2}), mk_resolved(), mk_outcome(pagination={"total": 10, "returned": 10, "has_more": True, "next_page": 2}))
check("total==returned + has_more true fails has_more", status(contradict, "pagination_has_more") == "fail", repr(evidence(contradict, "pagination_has_more")))
overflow = S.score_case(mk_case(expected_pagination=None), mk_resolved(), mk_outcome(pagination={"total": 10, "returned": 12, "has_more": True, "next_page": 2}))
check("returned>total fails total and returned", status(overflow, "pagination_total") == "fail" and status(overflow, "pagination_returned") == "fail")
no_more = S.score_case(mk_case(expected_pagination={"total": 10, "returned": 10, "has_more": False, "next_page": None}), mk_resolved(), mk_outcome(pagination={"total": 10, "returned": 10, "has_more": False, "next_page": 2}))
check("next_page non-null when has_more false fails", status(no_more, "pagination_next_page") == "fail", repr(evidence(no_more, "pagination_next_page")))
has_more_missing_next = S.score_case(mk_case(expected_pagination=p_ok), mk_resolved(), mk_outcome(pagination={"total": 25, "returned": 10, "has_more": True}))
check("next_page missing when has_more true fails", status(has_more_missing_next, "pagination_next_page") == "fail", repr(evidence(has_more_missing_next, "pagination_next_page")))
no_exp = S.score_case(mk_case(), mk_resolved(), mk_outcome())
check("no expected/actual pagination -> four skipped", all(status(no_exp, cid) == "skipped" and evidence(no_exp, cid).get("reason") == "no_expected_pagination" for cid in S.PAGINATION_CHECK_IDS))
min_total = S.score_case(mk_case(expected_pagination={"min_total": 40}), mk_resolved(), mk_outcome(pagination={"total": 39, "returned": 10, "has_more": True, "next_page": 2}))
check("min_total lower bound fails", status(min_total, "pagination_total") == "fail", repr(evidence(min_total, "pagination_total")))
# Mutation: force the has_more check to pass; the contradictory input must no longer fail.
orig_has_more = S._pagination_has_more
try:
    S._pagination_has_more = lambda *args, **kwargs: S._pass("pagination_has_more")  # type: ignore[assignment]
    mutated = S.score_case(mk_case(expected_pagination={"total": 10, "returned": 10, "has_more": True, "next_page": 2}), mk_resolved(), mk_outcome(pagination={"total": 10, "returned": 10, "has_more": True, "next_page": 2}))
    mutated_status = status(mutated, "pagination_has_more")
finally:
    S._pagination_has_more = orig_has_more  # type: ignore[assignment]
check("pagination contract mutation flips has_more fail->pass", status(contradict, "pagination_has_more") == "fail" and mutated_status == "pass", f"baseline=fail mutated={mutated_status}")

# ---------------------------------------------------------------------------
section("G. Refusal 2x2 hand computation and independence")
# ---------------------------------------------------------------------------
def refusal_result(case_id: str, should_refuse: bool, kind: str) -> tuple[CaseSpec, CaseResult]:
    case = mk_case(case_id, expected_kind="no_answer" if should_refuse else "answer", should_refuse=should_refuse, refusal_reason="safety" if should_refuse else None)
    return case, S.score_case(case, mk_resolved(case_id), mk_outcome(kind=kind))

cases: list[CaseSpec] = []
results: list[CaseResult] = []
for i in (1, 2, 3, 4):
    c, r = refusal_result(f"R{i}", True, "no_answer" if i == 1 else "answer")
    cases.append(c); results.append(r)
for i in (1, 2, 3):
    c, r = refusal_result(f"A{i}", False, "no_answer" if i == 1 else "answer")
    cases.append(c); results.append(r)
base = S.refusal_metrics(cases, results)
check("2x2 hand: TP=1 FN=3 FP=1 TN=2", (base["refusal_recall"], base["false_refusal_rate"], base["refusal_precision"]) == (0.25, 1 / 3, 0.5), repr(base))
check("three refusal values differ", len({round(v, 12) for v in base.values()}) == 3, repr(base))
# Add one TN: only the answerable denominator changes.
tn_case, tn_result = refusal_result("A4", False, "answer")
tn_metrics = S.refusal_metrics(cases + [tn_case], results + [tn_result])
check("add TN: false_refusal_rate changes, recall/precision unchanged", tn_metrics["false_refusal_rate"] == 0.25 and tn_metrics["refusal_recall"] == base["refusal_recall"] and tn_metrics["refusal_precision"] == base["refusal_precision"], repr(tn_metrics))
# Add one FN: only the should-refuse denominator changes.
fn_case, fn_result = refusal_result("R5", True, "answer")
fn_metrics = S.refusal_metrics(cases + [fn_case], results + [fn_result])
check("add FN: refusal_recall changes, false_refusal/precision unchanged", fn_metrics["refusal_recall"] == 0.2 and fn_metrics["false_refusal_rate"] == base["false_refusal_rate"] and fn_metrics["refusal_precision"] == base["refusal_precision"], repr(fn_metrics))
# Add one FP: both false-refusal (FP denominator) and precision (refused denominator) change.
fp_case, fp_result = refusal_result("A5", False, "no_answer")
fp_metrics = S.refusal_metrics(cases + [fp_case], results + [fp_result])
check("add FP: false_refusal_rate and precision change, recall unchanged", fp_metrics["false_refusal_rate"] == 0.5 and abs(fp_metrics["refusal_precision"] - 1 / 3) < 1e-12 and fp_metrics["refusal_recall"] == 0.25, repr(fp_metrics))
only_answerable = S.refusal_metrics([cases[-1]], [results[-1]])
check("no should-refuse denominator: recall/precision None, false_refusal 0", only_answerable == {"refusal_recall": None, "false_refusal_rate": 0.0, "refusal_precision": None}, repr(only_answerable))
only_refusal = S.refusal_metrics([cases[0]], [results[0]])
check("no answerable denominator: false_refusal None", only_refusal["false_refusal_rate"] is None and only_refusal["refusal_recall"] == 1.0 and only_refusal["refusal_precision"] == 1.0, repr(only_refusal))
for kind, wanted in (("no_answer", True), ("not_found", True), ("refusal", True), ("clarification", False), ("conflict", False), ("ambiguous", False), ("error", False), ("service_error", False), ("knowledge_changed", False)):
    check("is_refusal(" + kind + ") == " + str(wanted), S.is_refusal(kind) is wanted)
err_case, err_result = refusal_result("E1", False, "error")
before_error = S.refusal_metrics([cases[4], cases[5]], [results[4], results[5]])
err_metrics = S.refusal_metrics([cases[4], cases[5], err_case], [results[4], results[5], err_result])
print("ERROR_CASE refused=" + repr(err_result.refused) + " kind_correct=" + status(err_result, "kind_correct") + " before=" + json.dumps(before_error, ensure_ascii=False) + " after=" + json.dumps(err_metrics, ensure_ascii=False))
check("execution error is counted as TN and dilutes false_refusal_rate", err_result.refused is False and before_error["false_refusal_rate"] == 0.5 and err_metrics["false_refusal_rate"] == 1 / 3, repr(err_metrics))

# ---------------------------------------------------------------------------
section("H. Determinism, trace fields, and EvalOutcome surface")
# ---------------------------------------------------------------------------
first = S.score_case(sink_case, sink_resolved, sink_outcome, sink_trace)
second = S.score_case(sink_case, sink_resolved, sink_outcome, sink_trace)
check("same input twice -> equal CaseResult", first == second)
check("same input twice -> byte-identical JSON", json.dumps(first.to_dict(), ensure_ascii=False, sort_keys=True) == json.dumps(second.to_dict(), ensure_ascii=False, sort_keys=True))
check("trace latency/tokens/cost extracted", (first.latency_ms, first.tokens_in, first.tokens_out, first.cost_cny) == (5, 1, 2, 0.01), repr((first.latency_ms, first.tokens_in, first.tokens_out, first.cost_cny)))
check("outcome path and trace id carried", first.trace_id == "tr-1" and first.path == "rag")
outcome_fields = [field.name for field in fields(S.EvalOutcome)]
check("EvalOutcome plan fields present plus documented retrieved", set(outcome_fields) == {"kind", "text", "citations", "facts", "pagination", "trace_id", "path", "retrieved"}, repr(outcome_fields))
check("EvalOutcome can be constructed without retrieved", S.EvalOutcome(kind="answer").retrieved == ())
check("retrieved field is an ordered tuple of EvalRetrieved", isinstance(S.EvalOutcome(kind="answer", retrieved=(S.EvalRetrieved(doc_code="D01"),)).retrieved, tuple))
try:
    S.score_case(mk_case("A"), mk_resolved("B"), mk_outcome())
    cross_case_raised = False
except ValueError:
    cross_case_raised = True
check("cross-case resolved raises ValueError", cross_case_raised)

# ---------------------------------------------------------------------------
section("I. End-to-end aggregate smoke and summary")
# ---------------------------------------------------------------------------
agg = S.aggregate_metrics([sink_case, refusal_case], [sink, refusal_case_result])
required_metric_keys = {
    "case_count", "scored_count", "skipped_count", "value_hit", "source_hit", "kind_correct",
    "citation_precision", "citation_recall", "Recall@10", "MRR@10", "nDCG@10",
    "hard_filter_violation_rate", "empty_recall_rate", "refusal_recall", "false_refusal_rate",
    "refusal_precision", "p50_latency_ms", "p95_latency_ms", "tokens_in_total", "tokens_out_total",
    "cost_total_cny", "cost_per_case_cny",
}
check("aggregate exposes the full metric key set", set(agg) == required_metric_keys, repr(sorted(set(agg) ^ required_metric_keys)))
check("aggregate counts 2/2/0", (agg["case_count"], agg["scored_count"], agg["skipped_count"]) == (2, 2, 0))
print("AGG " + json.dumps(agg, ensure_ascii=False, sort_keys=True))

print("\nRESULT " + ("ALL_PASS" if not FAILURES else "FAILURES=" + repr(FAILURES)))
sys.exit(0 if not FAILURES else 1)
