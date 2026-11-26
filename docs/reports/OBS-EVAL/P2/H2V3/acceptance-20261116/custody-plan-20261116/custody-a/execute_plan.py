"""Review-only until B review and an explicit instruction to execute exactly once."""
import json
import pathlib
import sys
sys.dont_write_bytecode = True
from datetime import datetime, timezone
import prepare_plan as prep

HERE = pathlib.Path(__file__).resolve().parent
MARKER = HERE / "PLAN-ATTEMPTED.json"
RECEIPT = HERE / "SAFE-PLAN-RECEIPT.json"
EXPECTED_CENTERS = {"answer_retrieval": 8.5, "ocr": 6.5, "judge": 3.0, "independent": 2.0}
EXPECTED_DATES = ("2026-10-15", "2026-07-15")
EXPECTED_BATCHES = (9, 10, 13, 15)

def execute_once():
    initial = prep.prepare()
    prior = prep.load_prior()
    entry = prior.ENTRY
    old = entry.v2._read_json_mapping(prior.WORK / "regen-1500" / "bindings" / "run0-base_b0.binding.json", "old_binding_invalid")
    entry._validate_binding_document(old)
    root = pathlib.Path(old["inputs"]["holdout_manifest"]["path"]).parent.resolve()
    key = pathlib.Path(old["inputs"]["scenario_key_file"]["path"]).resolve()
    out = (prior.WORK / "custody-plan-20261116-single-01").resolve()
    ingest_hash = prep.sha(pathlib.Path(entry.contract_v3.V3_INGEST))
    if ingest_hash != old["inputs"]["ingest_plan"]["sha256"]:
        raise ValueError("ingest_binding_mismatch")
    if MARKER.exists() or RECEIPT.exists() or out.exists():
        raise ValueError("attempt_already_exists")
    created = datetime.now(timezone.utc).isoformat()
    entry.v2._validate_created_utc(created)
    with MARKER.open("x", encoding="utf-8") as stream:
        stream.write('{"status":"attempt_started"}\n')
    # Same CLI parser and handler, exactly one plan-private invocation.
    status = entry.main(["plan-private", "--root", str(root), "--key-file", str(key),
                         "--out-dir", str(out), "--created-utc", created, "--max-requests", "1500"])
    if status != 0:
        raise ValueError("plan_private_failed")
    index = entry.v2._read_json_mapping(out / "plan-index.json", "plan_index_invalid")
    if index.get("ok") is not True or index.get("code_version") != initial["code_version"] or index.get("created_utc") != created:
        raise ValueError("index_binding_mismatch")
    runs = index.get("runs")
    if not isinstance(runs, list) or len(runs) != 4:
        raise ValueError("run_count_mismatch")
    output_runs = []
    for i, scenario in enumerate(entry.v2.SCENARIO_ORDER):
        row = runs[i]
        if row.get("run_index") != i or row.get("scenario_id") != scenario:
            raise ValueError("run_order_mismatch")
        binding_path = out / "bindings" / f"run{i}-{scenario}.binding.json"
        plan_path = out / "plans" / f"run{i}-{scenario}.plan.json"
        binding = entry.v2._read_json_mapping(binding_path, "binding_invalid")
        entry._validate_binding_document(binding)
        run = binding["runs"][0]
        if pathlib.Path(run["plan_file"]).resolve() != plan_path.resolve() or prep.sha(plan_path) != run["plan_file_sha256"]:
            raise ValueError("plan_file_binding_mismatch")
        plan = entry.P2RunPlan.from_dict(entry.v2._read_json_mapping(plan_path, "plan_invalid"))
        if (binding["code_version"] != initial["code_version"] or binding["created_utc"] != created or
            run["plan_sha256"] != plan.plan_sha256 or row["plan_sha256"] != plan.plan_sha256 or
            run["plan_id"] != plan.plan_id or row["plan_id"] != plan.plan_id or
            run["run_id"] != row["run_id"] or run["run_index"] != i or
            run["ingest_batches"] != EXPECTED_BATCHES[i] or
            binding["inputs"]["ingest_plan"]["sha256"] != ingest_hash or
            run["evidence_bindings"]["code_version"] != initial["code_version"] or
            run["evidence_bindings"]["index_revision"] != "pending_post_ingest"):
            raise ValueError("plan_binding_mismatch")
        if plan.max_requests != 1500 or plan.project_total_limit_cny != 40.0 or plan.stage_limit_cny != 20.0 or dict(plan.cost_centers_cny) != EXPECTED_CENTERS:
            raise ValueError("plan_limits_mismatch")
        if set(plan.operations) != {"answer", "index_embedding", "query_embedding", "query_expansion", "rerank"}:
            raise ValueError("plan_operations_mismatch")
        if i < 2:
            if run["business_date"] != EXPECTED_DATES[i] or binding["business_date"] != EXPECTED_DATES[i] or plan.total_requests > (65, 50)[i]:
                raise ValueError("diagnostic_scope_mismatch")
            output_runs.append({"plan_id": plan.plan_id, "plan_sha256": plan.plan_sha256,
                                "total_requests": plan.total_requests, "max_requests": plan.max_requests,
                                "stage_limit_cny": plan.stage_limit_cny, "cost_centers_cny": dict(plan.cost_centers_cny),
                                "project_total_limit_cny": plan.project_total_limit_cny, "run_id": run["run_id"],
                                "business_date": run["business_date"]})
    if (prep.sha(prep.LEDGER) != prep.LEDGER_SHA or prep.sha(prep.BUDGET) != prep.BUDGET_SHA or
        entry.v2.code_digest() != initial["code_version"]):
        raise ValueError("protection_changed")
    from mktkb.live_authorization import historical_prefix_sha256
    if historical_prefix_sha256(prep.LEDGER) != prep.PREFIX_SHA:
        raise ValueError("ledger_prefix_mismatch")
    result = {"runs": output_runs, "code_version": initial["code_version"], "created_utc": created,
              "ingest_plan_sha256": ingest_hash, "index_batches": list(EXPECTED_BATCHES),
              "historical_prefix_sha256": prep.PREFIX_SHA}
    with RECEIPT.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

def main():
    if sys.argv[1:] != ["--execute-after-b-review"]:
        print('{"status":"blocked","code":"mode_not_authorized"}')
        return 2
    try:
        with prep.quiet():
            execute_once()
        print('{"status":"receipt_written"}')
        return 0
    except BaseException:
        print('{"status":"blocked","code":"plan_attempt_failed"}')
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
