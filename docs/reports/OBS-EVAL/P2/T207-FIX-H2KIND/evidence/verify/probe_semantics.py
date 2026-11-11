
import json
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.gold import ResolvedGold
from mktkb.evaluation.scorers import EvalCitation, EvalOutcome, score_case, is_refusal, REFUSAL_KINDS, CHECK_IDS

GOLD = ResolvedGold(case_id="x", requires_ocr=False, skipped=False, sources=(), unit_ids=(), relevant_unit_ids=())
CIT = EvalCitation(doc_code="D01", unit_key="sheet:物品位置:row:8", unit_ids=("u1",))

def case(cid, expected_kind, should_refuse, values=(), sources=()):
    return CaseSpec(case_id=cid, suite="badcase", split="dev", stratum="negative",
                    business_date="2026-10-28", question="城南店的联系人是谁？",
                    expected_kind=expected_kind, expected_values=tuple(values),
                    expected_sources=tuple(sources), reference_answer="", labeler="lead",
                    label_version="dev-1", should_refuse=should_refuse)

def run(c, kind, *, compat, text="", citations=()):
    g = ResolvedGold(case_id=c.case_id, requires_ocr=False, skipped=False, sources=(), unit_ids=(), relevant_unit_ids=())
    r = score_case(c, g, EvalOutcome(kind=kind, text=text, citations=citations), compat_refusal_kind=compat)
    return r

ref = case("R01", "refusal", True)
nf = case("R02", "not_found", False)
ans = case("R03", "answer", False, ("合成答案甲",), ({"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"},))
ref_noshould = case("R04", "refusal", False)

rows = []
def rec(label, r, expect_status, expect_kind, expect_compat=None):
    kc = r.check("kind_correct")
    ok = (r.status == expect_status and kc.status == expect_kind
          and (expect_compat is None or kc.evidence.get("compat") == expect_compat))
    rows.append({"label": label, "status": r.status, "kind_correct": kc.status,
                 "compat": kc.evidence.get("compat"), "refusal_expected": r.check("refusal_expected").status,
                 "refusal_unexpected": r.check("refusal_unexpected").status,
                 "ok": ok, "expect": [expect_status, expect_kind, expect_compat]})

for kind in ("not_found", "no_answer"):
    rec(f"refusal+{kind}+compat", run(ref, kind, compat=True), "pass", "pass", "refusal")
    rec(f"refusal+{kind}+strict", run(ref, kind, compat=False), "fail", "fail")
rec("refusal+refusal+compat", run(ref, "refusal", compat=True), "pass", "pass")
rec("refusal+refusal+strict", run(ref, "refusal", compat=False), "pass", "pass")
rec("refusal+answer+compat", run(ref, "answer", compat=True, text="城南店的联系人是张三。"), "fail", "fail")
rec("refusal+conflict+compat", run(ref, "conflict", compat=True), "fail", "fail")
rec("refusal+clarification+compat", run(ref, "clarification", compat=True), "fail", "fail")
rec("refusal+error+compat", run(ref, "error", compat=True), "fail", "fail")
rec("not_found+no_answer+compat", run(nf, "no_answer", compat=True), "fail", "fail")
rec("not_found+refusal+compat", run(nf, "refusal", compat=True), "fail", "fail")
rec("no_answer+not_found+compat", run(case("R05","no_answer",False), "not_found", compat=True), "fail", "fail")
rec("answer_gold_vs_not_found+compat", run(ans, "not_found", compat=True), "fail", "fail")
rec("answer_gold_vs_answer+compat", run(ans, "answer", compat=True, text="资料写着：合成答案甲", citations=(CIT,)), "pass", "pass")
rec("refusal_noshould+not_found+compat", run(ref_noshould, "not_found", compat=True), "fail", "pass")

print(json.dumps({
    "all_ok": all(r["ok"] for r in rows),
    "rows": rows,
    "check_ids": list(CHECK_IDS),
    "check_count": len(CHECK_IDS),
    "refusal_kinds": sorted(REFUSAL_KINDS),
    "is_refusal": {k: is_refusal(k) for k in ("not_found","no_answer","refusal","answer","conflict","error","service_error","clarification")},
}, ensure_ascii=False, indent=1))
