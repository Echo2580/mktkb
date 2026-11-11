"""Independent probe #5: no ingest plan -> fail closed (all error, stable block code)."""
import sys, json
sys.path.insert(0, r"backend/src")
from mktkb.evaluation import p2_runner as runner
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.p2_runner import P2RunLedger
from mktkb.evaluation.product_adapter import P2RunDataset

STRATA = (("paraphrase", 10), ("multi_turn", 5), ("negative", 5), ("stale_conflict", 5), ("cross_doc_security", 5))
ATOK = "PROBE-ANSWER-51d0"
cases = []
n = 0
for stratum, count in STRATA:
    for off in range(count):
        n += 1
        cases.append(CaseSpec(case_id=f"PRB-{n:02d}", suite="p2-holdout", split="holdout", stratum=stratum,
                              business_date="2026-10-28", question=f"PROBE-Q {n:02d}", expected_kind="answer",
                              expected_values=(ATOK,),
                              expected_sources=({"doc_code": "D01", "unit_key": "sheet:\u7269\u54c1\u4f4d\u7f6e:row:8"},),
                              reference_answer=ATOK, label_version="probe"))
cases = tuple(cases)
def row(case):
    return {"case_id": case.case_id, "suite": case.suite, "stratum": case.stratum, "status": "ok",
            "error_code": None,
            "turns": [{"turn": 1, "status": "ok", "product": {
                "kind": "answer", "text": ATOK,
                "sources": [{"source_id": "u1", "document_name": "D01_\u7269\u54c1\u4f4d\u7f6e\u8868.xlsx"}],
                "evidence": [{"unit_id": "u1", "unit_key": "sheet:\u7269\u54c1\u4f4d\u7f6e:row:8", "locator": {"sheet": "\u7269\u54c1\u4f4d\u7f6e", "row": 8}}]}}],
            "planned_turns": 1, "turns_executed": 1}
led = P2RunLedger(run_id="p2run-noplan", plan_id="p", plan_sha256="a" * 64, execution="dry_run", production_ready=False)
led.cases = [row(c) for c in cases]
ds = P2RunDataset(visibility="holdout", cases=cases, identity={
    "dataset_version": "v", "label_version": "v", "suite": "p2-holdout",
    "manifest_sha256": "c" * 64, "case_count": len(cases), "strata": dict(STRATA)})
card = runner._holdout_scorecard(led, ds, ingest_plan=None, execution="dry_run", real_calls=0,
                                 binding={}, gate_config=None)
print(json.dumps({"passed": card["passed"], "failed": card["failed"], "errors": card["errors"],
                  "blocks": [b["code"] for b in card["blocks"]],
                  "release_ready": card["release_ready"]}, ensure_ascii=False))
