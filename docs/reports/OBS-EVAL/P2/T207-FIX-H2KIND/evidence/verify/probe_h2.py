
import json
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation import p2_score_run
from mktkb.evaluation import p2_scoring as ps
from mktkb.evaluation.p2_scoring import (
    P2_HOLDOUT_STRATA, P2_HOLDOUT_TOTAL, P2_HOLDOUT_MIN_PASS, P2_HOLDOUT_MAX_HARD_FAILURES,
    CASE_STATUS_PASS, CASE_STATUS_FAIL,
)

VALUE = "合成命中答案甲"
DOC_NAME = "D01_物品位置表.xlsx"
UNIT_ID = "33333333-3333-4333-8333-333333333333"
UNIT_KEY = "sheet:物品位置:row:8"
DOC_CODES = {DOC_NAME: "D01"}
SOURCE_INDEX = {UNIT_ID: {"doc_code": "D01", "unit_key": UNIT_KEY, "locator": {}}}
BUSINESS_DATE = "2026-10-28"
PLAN = (("paraphrase", 10), ("multi_turn", 5), ("negative", 5), ("stale_conflict", 5), ("cross_doc_security", 5))

def specs():
    out = []
    n = 0
    for stratum, count in PLAN:
        for off in range(count):
            n += 1
            refusal = stratum == "negative" or (stratum == "cross_doc_security" and off == 0)
            conflict = stratum == "stale_conflict" and off == 0
            out.append(CaseSpec(
                case_id=f"VH2-{n:02d}", suite="p2-holdout", split="holdout", stratum=stratum,
                business_date=BUSINESS_DATE, question=f"验收合成问句 {n:02d}",
                expected_kind="refusal" if refusal else ("conflict" if conflict else "answer"),
                expected_values=() if (refusal or conflict) else (VALUE,),
                expected_sources=() if (refusal or conflict) else ({"doc_code": "D01", "unit_key": UNIT_KEY},),
                reference_answer="" if (refusal or conflict) else f"{VALUE}（合成）",
                labeler="data-custodian", label_version="h2-verify",
                should_refuse=refusal,
                refusal_reason="验收合成负样本：语料无答案" if refusal else None,
            ))
    return tuple(out)

def rows(cases, *, answered=False):
    out = {}
    for c in cases:
        if c.expected_kind == "refusal" and not answered:
            product = {"kind": "not_found", "text": "", "sources": []}
        elif c.expected_kind == "conflict":
            product = {"kind": "conflict", "text": "两份资料不一致（验收合成）", "sources": []}
        else:
            product = {"kind": "answer", "text": f"资料写着：{VALUE}",
                       "sources": [{"source_id": UNIT_ID, "document_name": DOC_NAME,
                                    "version_number": 1, "status": "active",
                                    "locator": {"sheet": "物品位置", "row": 8}}]}
        out[c.case_id] = {"case_id": c.case_id, "status": "ok", "error_code": None, "planned_turns": 1,
                          "turns": [{"turn": 1, "status": "ok", "error_code": None,
                                     "product": {**product, "trace_id": f"trace-{c.case_id}"}}]}
    return out

def card(marks):
    return p2_score_run.aggregate_holdout_bundle(marks).to_dict()

cases = specs()
assert dict(P2_HOLDOUT_STRATA) == dict(PLAN), dict(P2_HOLDOUT_STRATA)
assert P2_HOLDOUT_TOTAL == 30 and P2_HOLDOUT_MIN_PASS == 24 and P2_HOLDOUT_MAX_HARD_FAILURES == 0
base_rows = rows(cases)
marks_after, unclassified_after = p2_score_run.holdout_case_scores_from_rows(
    cases, base_rows, document_codes=DOC_CODES, source_index=SOURCE_INDEX)
after = card(marks_after)

orig = ps.score_case
def no_compat(*args, **kwargs):
    kwargs = {**kwargs, "compat_refusal_kind": False}
    return orig(*args, **kwargs)
ps.score_case = no_compat
try:
    marks_before, unclassified_before = p2_score_run.holdout_case_scores_from_rows(
        cases, base_rows, document_codes=DOC_CODES, source_index=SOURCE_INDEX)
    before = card(marks_before)
finally:
    ps.score_case = orig

answered_rows = rows(cases, answered=True)
marks_answered, _ = p2_score_run.holdout_case_scores_from_rows(
    cases, answered_rows, document_codes=DOC_CODES, source_index=SOURCE_INDEX)
answered = card(marks_answered)

# 单题证据：after 的拒答题 kind_correct 标记 compat；answered 的拒答题 refusal_expected=fail
ref_case = next(c for c in cases if c.expected_kind == "refusal")
ref_id = ref_case.case_id
after_case = ps.score_public_case(ref_case, base_rows[ref_id], document_codes=DOC_CODES, source_index=SOURCE_INDEX)
answered_case = ps.score_public_case(ref_case, answered_rows[ref_id], document_codes=DOC_CODES, source_index=SOURCE_INDEX)
ref_checks = {c["check_id"]: (c["status"], c.get("evidence", {}).get("compat")) for c in after_case.score.checks}
ans_checks = {c["check_id"]: c["status"] for c in answered_case.score.checks}

before_by_id = {m.case_id: m.status for m in marks_before}
after_by_id = {m.case_id: m.status for m in marks_after}
flipped = {cid for cid in after_by_id if before_by_id[cid] != after_by_id[cid]}
refusal_ids = {c.case_id for c in cases if c.expected_kind == "refusal"}
print(json.dumps({
    "cases": len(cases),
    "expected_kind_dist": {k: sum(1 for c in cases if c.expected_kind == k) for k in ("answer","conflict","refusal")},
    "strata": {k: sum(1 for c in cases if c.stratum == k) for k in dict(PLAN)},
    "after_card": after,
    "before_card": before,
    "answered_card": answered,
    "after_unclassified": unclassified_after,
    "before_unclassified": unclassified_before,
    "flipped": sorted(flipped),
    "flipped_is_refusal_set": flipped == refusal_ids,
    "after_all_pass": after["passed"] == 30 and after["failed"] == 0,
    "before_24_6": (before["passed"], before["failed"]) == (24, 6),
    "answered_24_6": (answered["passed"], answered["failed"]) == (24, 6),
    "refusal_case_checks": ref_checks,
    "answered_checks": ans_checks,
    "thresholds": {"total": P2_HOLDOUT_TOTAL, "min_pass": P2_HOLDOUT_MIN_PASS, "hard_max": P2_HOLDOUT_MAX_HARD_FAILURES},
}, ensure_ascii=False, indent=1))
