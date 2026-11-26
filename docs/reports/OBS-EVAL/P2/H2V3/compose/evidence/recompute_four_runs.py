import importlib.util
import json
import pathlib
import sys

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
WORK = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115")
OUT = WORK / "compose-work"
BACKEND_SRC = REPO / "backend" / "src"
TOOLS = REPO / "tools"
for entry in (str(BACKEND_SRC), str(TOOLS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

spec = importlib.util.spec_from_file_location(
    "p2_h2_v3_controlled_execute_probe2", TOOLS / "p2_h2_v3_controlled_execute.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

SCENARIOS = [
    ("run0-base_b0.binding.json", 0),
    ("run1-base_b0_plus_v01.binding.json", 1),
    ("run2-pre_v05_without_v07.binding.json", 2),
    ("run3-post_v05_without_v01.binding.json", 3),
]

evidence_key = (WORK / "runs" / "r0" / "ev.key").read_bytes().strip()

captured = {}
captured_cards = {}
original = module.hard.recompute_hard_evidence


def wrapper(cases, annotation, audits, **kwargs):
    card, results = original(cases, annotation, audits, **kwargs)
    captured[str(kwargs["plan_meta"]["run_id"])] = results
    captured_cards[str(kwargs["plan_meta"]["run_id"])] = card
    return card, results


module.hard.recompute_hard_evidence = wrapper

report = {"runs": [], "cards": {}}
for binding_name, run_index in SCENARIOS:
    binding_path = WORK / "regen-1160c" / "bindings" / binding_name
    document = json.loads(binding_path.read_text(encoding="utf-8"))
    inputs = {name: {"path": record["path"]} for name, record in document["inputs"].items()}
    bundle = module.load_v3_bundle(inputs)
    run_entry = document["runs"][0]
    if int(run_entry["run_index"]) != run_index:
        raise RuntimeError("binding run_index mismatch")
    plan = module.v2._load_plan_for_run(document, run_entry)
    scenario = str(run_entry["scenario_id"])
    subset = bundle.contract.subset(scenario)
    case_plan_path = WORK / "runs" / f"r{run_index}c" / "out" / "controlled" / "case-plan.json"
    case_plan = json.loads(case_plan_path.read_text(encoding="utf-8"))
    evidence_dir = WORK / "runs" / f"r{run_index}c" / "evidence" / str(run_entry["run_id"])
    receipt_path = (
        WORK / "runs" / f"r{run_index}c" / "seal" / str(run_entry["run_id"]) / "run-receipt.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    result = module.v2._recompute_loaded(
        document=document,
        run_entry=run_entry,
        plan=plan,
        cases=subset.cases,
        annotation=bundle.annotation,
        case_plan_payload=case_plan,
        evidence_dir=evidence_dir,
        key=evidence_key,
        receipt=receipt,
    )
    card = captured_cards[str(run_entry["run_id"])]
    validated = module.hard.validate_hard_evidence_scorecard(
        card,
        total=len(subset.cases),
        run_id=str(run_entry["run_id"]),
        config_hash=str(document["config_sha256"]),
        expected_strata=dict(case_plan["expected_strata"]),
    )
    results = captured[str(run_entry["run_id"])]
    cases = []
    for item in results:
        cases.append(
            {
                "case_id": item.case_id,
                "stratum": item.stratum,
                "quality_status": item.quality_status,
                "evidence_complete": bool(item.evidence_complete),
                "missing_codes": list(item.missing_codes),
                "axes": {
                    name: {
                        "state": item.axes[name].state,
                        "reason": item.axes[name].reason,
                        "missing": list(item.axes[name].missing),
                    }
                    for name in ("safety", "cross_user", "cross_entity", "stale_source")
                },
            }
        )
    report["runs"].append(
        {
            "run_index": run_index,
            "run_id": str(run_entry["run_id"]),
            "scenario_id": scenario,
            "case_count": len(subset.cases),
            "turns_executed": int(result["coverage"]["executed_turns"]),
            "coverage": result["coverage"],
            "card": card,
            "card_validated": validated == card,
            "cases": cases,
        }
    )
    report["cards"][scenario] = card
    print(
        scenario,
        "cases", card["total"],
        "pass", card["passed"], "fail", card["failed"],
        "hard", card["hard_failures"], card["hard_failures_by_kind"],
        "valid", validated == card,
    )

totals = {
    "cases": sum(run["card"]["total"] for run in report["runs"]),
    "passed": sum(run["card"]["passed"] for run in report["runs"]),
    "failed": sum(run["card"]["failed"] for run in report["runs"]),
    "errors": sum(run["card"]["errors"] for run in report["runs"]),
    "hard_failures": sum(run["card"]["hard_failures"] for run in report["runs"]),
    "hard_failures_by_kind": {
        name: sum(run["card"]["hard_failures_by_kind"][name] for run in report["runs"])
        for name in ("safety", "cross_user", "cross_entity", "stale_source")
    },
    "turns": sum(run["turns_executed"] for run in report["runs"]),
    "axes": {
        name: {
            key: sum(run["card"]["hard_evidence"]["axes"][name][key] for run in report["runs"])
            for key in ("planned", "passed", "not_applicable", "unknown", "violations", "checked")
        }
        for name in ("safety", "cross_user", "cross_entity", "stale_source")
    },
}
report["totals"] = totals
(OUT / "recompute-four-runs.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(totals, ensure_ascii=False, indent=2))
