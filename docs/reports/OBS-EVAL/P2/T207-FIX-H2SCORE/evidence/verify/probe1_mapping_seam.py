
"""Independent probe #1: mapping rules, aggregation seam with real scoring, leak audit,
threshold semantics, schema parity. Zero network. Reads only repo fixtures."""
from __future__ import annotations
import json, sys, traceback
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, r"backend/src")
from mktkb.evaluation import p2_runner as runner
from mktkb.evaluation import p2_score_run
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.product_adapter import P2RunDataset, P2IngestPlan, IngestSource, ingest_plan_from_document
from mktkb.evaluation.p2_runner import P2RunError, P2RunLedger, holdout_document_codes

ROOT = Path(".")
D01 = ROOT / "fixtures/acceptance/normal/D01_物品位置表.xlsx"
D04 = ROOT / "fixtures/acceptance/normal/D04_活动策划流程.docx"
OUT = {}
def rec(section, **kw):
    OUT.setdefault(section, {}).update(kw)

PASS = "pass"; FAIL = "fail"; ERROR = "error"

STRATA = (("paraphrase",10),("multi_turn",5),("negative",5),("stale_conflict",5),("cross_doc_security",5))
QTOK = "VERIFY-Q-3f81c2d7"
QSHORT = "五点差"            # 5 chars: below the 8-char audit threshold
ATOK = "VERIFY-ANSWER-9a4e"
SHORT_ATOK = "乙九"           # 2 chars

def cases_30():
    out=[]; n=0
    for stratum,count in STRATA:
        for off in range(count):
            n+=1
            out.append(CaseSpec(
                case_id=f"H2V-{n:02d}", suite="p2-holdout", split="holdout", stratum=stratum,
                business_date="2026-10-28", question=f"{QTOK} {stratum} {off:02d}",
                expected_kind="answer", expected_values=(ATOK,),
                expected_sources=({"doc_code":"D01","unit_key":"sheet:物品位置:row:8"},),
                relevant_units=({"doc_code":"D01","locator":{"sheet":"物品位置","row":8}},),
                reference_answer=f"{ATOK} 合成参考 答案正文", label_version="verify-v1",
            ))
    return tuple(out)

def dataset_30(cases):
    strata={}
    for c in cases: strata[c.stratum]=strata.get(c.stratum,0)+1
    return P2RunDataset(visibility="holdout", cases=cases, identity={
        "dataset_version":"verify-v1","label_version":"verify-v1","suite":"p2-holdout",
        "manifest_sha256":"c"*64,"case_count":len(cases),"strata":strata})

def ledger_with(rows, run_id="p2run-verify-01"):
    led = P2RunLedger(run_id=run_id, plan_id="p2-verify", plan_sha256="a"*64,
                      execution="dry_run", production_ready=False)
    led.cases = list(rows)
    return led

def row(case, *, text="", kind="answer", status="ok", doc_name="D01_物品位置表.xlsx",
        with_text=True, source_status=None, unit_key="sheet:物品位置:row:8", src_id="u-row-8"):
    product = {
        "kind": kind,
        "sources": [dict({"source_id": src_id, "document_name": doc_name},
                         **({} if source_status is None else {"status": source_status}))],
        "evidence": [{"unit_id": src_id, "unit_key": unit_key, "locator": {"sheet":"物品位置","row":8}, "verified": True}],
    }
    if with_text:
        product["text"] = text
    return {"case_id": case.case_id, "suite": case.suite, "stratum": case.stratum,
            "status": status, "error_code": (None if status=="ok" else "product_service_error"),
            "turns": [{"turn":1,"status":"ok","product":product}], "planned_turns":1, "turns_executed":1}

def plan_d01():
    return P2IngestPlan(sources=(IngestSource(path=D01),), label="verify")

def card(rows, cases=None, *, plan=None, gate_config=None, execution="dry_run", real_calls=0,
         binding=None):
    cases = cases or cases_30()
    return runner._holdout_scorecard(
        ledger_with(rows), dataset_30(cases), ingest_plan=(plan if plan is not None else plan_d01()),
        execution=execution, real_calls=real_calls,
        binding=(binding if binding is not None else {"config_hash":"d"*64}),
        gate_config=gate_config)

# ---------------------------------------------------------------- S1 mapping (real plan)
try:
    payload = json.loads(Path("docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json").read_text(encoding="utf-8"))
    plan = ingest_plan_from_document(payload)
    codes = holdout_document_codes(plan)
    per_source = []
    for s in plan.sources:
        name = s.document_ref or s.name
        per_source.append({"path": Path(s.path).name, "canonical": name,
                           "code_of_path": codes.get(Path(s.path).name),
                           "code_of_canonical": codes.get(name)})
    rec("s1_mapping_real_plan", mapping_size=len(codes), per_source=per_source,
        distinct_codes=sorted(set(codes.values())))
except Exception as exc:
    rec("s1_mapping_real_plan", error=repr(exc), tb=traceback.format_exc())

# ---------------------------------------------------------------- S2 mapping fail-closed
s2 = {}
class _Src:
    def __init__(self, p, name=None, ref=None):
        self.path=Path(p); self.name=name; self.document_ref=ref
class _Plan:
    def __init__(self, *s): self.sources=tuple(s)
def expect_code(fn):
    try:
        fn(); return {"raised": False}
    except P2RunError as exc:
        return {"raised": True, "code": exc.code}
s2["ambiguous"] = expect_code(lambda: holdout_document_codes(_Plan(_Src("x/D09_a.xlsx"), _Src("x/D09_a.xlsx", name="V02_b"))))
s2["no_prefix"] = expect_code(lambda: holdout_document_codes(_Plan(_Src("x/notes.txt"))))
s2["no_plan"] = expect_code(lambda: holdout_document_codes(None))
s2["empty_plan"] = expect_code(lambda: holdout_document_codes(_Plan()))
s2["separator_required"] = {"code_for_D09xlsx": runner._doc_code_of("D09x.xlsx"),
                             "code_for_D09_dash": runner._doc_code_of("D09-x.xlsx"),
                             "code_for_D09_us": runner._doc_code_of("D09_x.xlsx")}
rec("s2_mapping_fail_closed", **s2)

# gold doc code not covered by corpus -> block, no pass
cases = cases_30()
missing_gold = tuple(CaseSpec(**{**c.__dict__, "expected_sources":({"doc_code":"D09","unit_key":"sheet:物品位置:row:8"},)}) for c in cases[:1]) + cases[1:]
try:
    c_missing = card([row(c, text=ATOK) for c in missing_gold], missing_gold)
    blocks = {b["code"]: b for b in c_missing["blocks"]}
    rec("s2_gold_missing_block", present="holdout_document_code_unmapped" in blocks,
        evidence=blocks.get("holdout_document_code_unmapped",{}).get("evidence"),
        passed=c_missing["passed"])
except Exception as exc:
    rec("s2_gold_missing_block", error=repr(exc), tb=traceback.format_exc())

# ---------------------------------------------------------------- S3 seam: H2-style rows WITH text
cases = cases_30()
rows_ok = [row(c, text=f"{ATOK} 记录一致") for c in cases[:23]]
rows_fail = [row(cases[23], text="答非所问的内容")]
rows_ok = rows_ok + rows_fail                     # 23 pass + 1 fail; 6 未执行（无行）
c3 = card(rows_ok, cases)
rec("s3_rows_with_text_23_1_6",
    total=c3["total"], executed=c3["executed"], passed=c3["passed"], failed=c3["failed"],
    errors=c3["errors"], hard_failures=c3["hard_failures"],
    by_stratum={k:dict(v) for k,v in c3["by_stratum"].items()},
    blocks=[b["code"] for b in c3["blocks"]],
    thresholds_approved=c3["thresholds_approved"], release_ready=c3["release_ready"],
    threshold_met=c3["threshold_met"], min_pass=c3["min_pass"])

# ---------------------------------------------------------------- S4 seam: same rows WITHOUT text (H2 writer behaviour)
rows_notext = [row(c, text=f"{ATOK} 记录一致", with_text=False) for c in cases[:23]]
rows_notext.append(row(cases[23], text="答非所问的内容", with_text=False))
c4 = card(rows_notext, cases)
rec("s4_rows_without_text_23_1_6",
    total=c4["total"], executed=c4["executed"], passed=c4["passed"], failed=c4["failed"],
    errors=c4["errors"], blocks=[b["code"] for b in c4["blocks"]])

# ---------------------------------------------------------------- S5 hard-failure / unclassified / source status
rows_src = [row(c, text=f"{ATOK} 记录一致") for c in cases[:23]]
rows_src[0] = row(cases[0], text=f"{ATOK} 记录一致", source_status="superseded")
c5 = card(rows_src, cases)
blocks5 = {b["code"]: b for b in c5["blocks"]}
rec("s5_source_status_unclassified",
    passed=c5["passed"], failed=c5["failed"], errors=c5["errors"],
    hard_failures=c5["hard_failures"],
    unclassified_present="holdout_hard_failure_unclassified" in blocks5,
    unclassified_evidence=blocks5.get("holdout_hard_failure_unclassified",{}).get("evidence"))

# ---------------------------------------------------------------- S6 threshold semantics
class _Gate:
    def __init__(self, status): self.status=status
c6_none = card([row(c, text=ATOK) for c in cases], cases, gate_config=None)
c6_unapproved = card([row(c, text=ATOK) for c in cases], cases, gate_config=_Gate("unapproved"))
c6_approved = card([row(c, text=ATOK) for c in cases], cases, gate_config=_Gate("approved"))
rec("s6_thresholds",
    none={"approved": c6_none["thresholds_approved"], "blocks":[b["code"] for b in c6_none["blocks"]], "passed": c6_none["passed"], "release_ready": c6_none["release_ready"]},
    unapproved={"approved": c6_unapproved["thresholds_approved"], "blocks":[b["code"] for b in c6_unapproved["blocks"]], "passed": c6_unapproved["passed"], "release_ready": c6_unapproved["release_ready"]},
    approved={"approved": c6_approved["thresholds_approved"], "blocks":[b["code"] for b in c6_approved["blocks"]], "passed": c6_approved["passed"], "threshold_met": c6_approved["threshold_met"], "release_ready": c6_approved["release_ready"]})

# ---------------------------------------------------------------- S7 leak audit
dataset = dataset_30(cases)
s7 = {}
def audit(payload):
    try:
        runner._assert_holdout_scorecard_payload(payload, dataset); return {"raised": False}
    except P2RunError as exc:
        return {"raised": True, "code": exc.code}
s7["case_id"] = audit({"blocks":[{"code":"x","evidence":{"note":cases[0].case_id}}]})
s7["long_question"] = audit({"blocks":[{"code":"x","evidence":{"note":cases[0].question}}]})
s7["reference_answer"] = audit({"blocks":[{"code":"x","evidence":{"note":cases[0].reference_answer}}]})
s7["H2_prefix"] = audit({"blocks":[{"code":"H2-01"}]})
s7["detail_key"] = audit({"blocks":[{"code":"x","evidence":{"question":"?"}}]})
short_case = CaseSpec(case_id="H2V-S1", suite="p2-holdout", split="holdout", stratum="paraphrase",
                      business_date="2026-10-28", question=QSHORT, expected_kind="answer",
                      expected_values=(SHORT_ATOK,), reference_answer=SHORT_ATOK, label_version="verify-v1")
short_ds = dataset_30((short_case,))
try:
    runner._assert_holdout_scorecard_payload({"blocks":[{"code":"x","evidence":{"note":QSHORT}}]}, short_ds)
    s7["short_question_below_8"] = {"raised": False, "note": "5-char question is NOT caught (audit threshold len>=8)"}
except P2RunError as exc:
    s7["short_question_below_8"] = {"raised": True, "code": exc.code}
try:
    runner._assert_holdout_scorecard_payload({"blocks":[{"code":"x","evidence":{"note":SHORT_ATOK}}]}, short_ds)
    s7["short_answer_below_8"] = {"raised": False, "note": "2-char answer is NOT caught"}
except P2RunError as exc:
    s7["short_answer_below_8"] = {"raised": True, "code": exc.code}

# builder-level fail-closed (A): leak comes from the builder (_holdout_scorecard) -> blocked card
orig_builder = runner._holdout_scorecard
def leaky_builder(ledger, dataset, **kw):
    payload = orig_builder(ledger, dataset, **kw)
    payload["blocks"] = list(payload["blocks"]) + [{
        "code":"injected","severity":"unknown","detail":"probe",
        "evidence":{"case_id":cases[0].case_id,"question":cases[0].question}}]
    return payload
runner._holdout_scorecard = leaky_builder
try:
    blocked = runner._holdout_scorecard_artifact(
        ledger_with([]), dataset, ingest_plan=plan_d01(), execution="dry_run", real_calls=0,
        binding={"config_hash":"d"*64}, gate_config=None)
    raw = json.dumps(blocked, ensure_ascii=False)
    s7["builder_leak_fail_closed"] = {
        "escaped": False, "total": blocked["total"], "passed": blocked["passed"],
        "failed": blocked["failed"], "errors": blocked["errors"],
        "blocks":[b["code"] for b in blocked["blocks"]],
        "contains_case_id": cases[0].case_id in raw,
        "contains_question": QTOK in raw, "contains_answer": ATOK in raw,
        "contains_detail_key": '"case_id"' in raw,
    }
except Exception as exc:  # noqa: BLE001
    s7["builder_leak_fail_closed"] = {"escaped": True, "error": repr(exc)}
finally:
    runner._holdout_scorecard = orig_builder

# builder-level fail-closed (B): leak comes from the aggregator (_aggregate_marks) itself
orig_agg = runner._aggregate_marks
def leaky_agg(marks, **kw):
    payload = orig_agg(marks, **kw)
    payload["blocks"] = list(payload["blocks"]) + [{
        "code":"injected","severity":"unknown","detail":"probe",
        "evidence":{"case_id":cases[0].case_id,"question":cases[0].question}}]
    return payload
runner._aggregate_marks = leaky_agg
try:
    blocked2 = runner._holdout_scorecard_artifact(
        ledger_with([]), dataset, ingest_plan=plan_d01(), execution="dry_run", real_calls=0,
        binding={"config_hash":"d"*64}, gate_config=None)
    raw2 = json.dumps(blocked2, ensure_ascii=False)
    s7["aggregator_leak_fail_closed"] = {
        "escaped": False, "blocks":[b["code"] for b in blocked2["blocks"]],
        "contains_case_id": cases[0].case_id in raw2, "contains_question": QTOK in raw2,
    }
except Exception as exc:  # noqa: BLE001
    s7["aggregator_leak_fail_closed"] = {"escaped": True, "error": type(exc).__name__, "code": getattr(exc,"code",None)}
finally:
    runner._aggregate_marks = orig_agg
rec("s7_leak_audit", **s7)

# ---------------------------------------------------------------- S8 schema parity vs p2-score path
marks = []
for c in cases[:23]:
    marks.append(p2_score_run.P2HoldoutCaseScore(case_id=c.case_id, stratum=c.stratum, status=PASS))
marks.append(p2_score_run.P2HoldoutCaseScore(case_id=cases[23].case_id, stratum=cases[23].stratum, status=FAIL))
for c in cases[24:]:
    marks.append(p2_score_run.P2HoldoutCaseScore(case_id=c.case_id, stratum=c.stratum, status=ERROR))
score_path = p2_score_run.aggregate_holdout_bundle(
    marks, expected_strata=dict(dataset.identity["strata"]), thresholds_approved=False,
    execution_mode="local_mock", real_calls=0, run_id="p2run-verify-01", config_hash="d"*64).to_dict()
runner_card = card(rows_ok, cases)
rec("s8_schema_parity",
    key_sets_equal=sorted(score_path)==sorted(runner_card),
    types_equal={k: type(score_path[k]).__name__ for k in score_path}=={k: type(runner_card[k]).__name__ for k in runner_card},
    scorecard_keys=sorted(score_path),
    value_diffs={k: [score_path[k], runner_card[k]] for k in score_path if score_path[k]!=runner_card[k]})

print(json.dumps(OUT, ensure_ascii=False, indent=2))
