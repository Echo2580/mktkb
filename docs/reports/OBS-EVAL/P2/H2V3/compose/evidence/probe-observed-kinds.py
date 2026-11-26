import importlib.util
import json
import pathlib
import sys

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
WORK = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115")
for entry in (str(REPO / "backend" / "src"), str(REPO / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

spec = importlib.util.spec_from_file_location(
    "p2_h2_v3_controlled_execute_probe3", REPO / "tools" / "p2_h2_v3_controlled_execute.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: E402

key = (WORK / "runs" / "r0" / "ev.key").read_bytes().strip()
bindings_names = [
    "run0-base_b0.binding.json",
    "run1-base_b0_plus_v01.binding.json",
    "run2-pre_v05_without_v07.binding.json",
    "run3-post_v05_without_v01.binding.json",
]
for run_index, binding_name in enumerate(bindings_names):
    document = json.loads((WORK / "regen-1160c" / "bindings" / binding_name).read_text(encoding="utf-8"))
    inputs = {name: {"path": record["path"]} for name, record in document["inputs"].items()}
    bundle = module.load_v3_bundle(inputs)
    run_entry = document["runs"][0]
    scenario = str(run_entry["scenario_id"])
    subset = bundle.contract.subset(scenario)
    case_plan = json.loads(
        (WORK / "runs" / f"r{run_index}c" / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8")
    )
    evidence_dir = WORK / "runs" / f"r{run_index}c" / "evidence" / str(run_entry["run_id"])
    by_case = {str(case.case_id): case for case in subset.cases}
    for row in case_plan["cases"]:
        case = by_case[str(row["case_id"])]
        if row["quality_status"] != "fail":
            continue
        last = row["turns"][-1]
        envelope = read_encrypted_evidence(
            evidence_dir / str(last["evidence_file"]), key=key, expected_bindings=dict(case_plan["bindings"])
        )
        events = list((envelope.get("capture") or {}).get("events") or [])
        final = module.hard._final_outcome(events)
        projection = envelope.get("db_projection") or {}
        states = projection.get("query_states") or []
        last_kind = None
        if states:
            last_kind = ((states[-1] or {}).get("state_json") or {}).get("last_kind")
        messages = projection.get("messages") or []
        assistant = [m for m in messages if str(m.get("role")) == "assistant"]
        print(
            json.dumps(
                {
                    "run": run_index,
                    "case_id": str(case.case_id),
                    "stratum": str(case.stratum),
                    "expected_kind": str(case.expected_kind),
                    "should_refuse": bool(case.should_refuse),
                    "observed_final_kind": None if final is None else final.get("kind"),
                    "observed_final_keys": None if final is None else sorted(final.keys()),
                    "observed_last_kind": last_kind,
                    "assistant_error_code": assistant[-1].get("error_code") if assistant else None,
                    "event_kinds": [str(e.get("kind")) for e in events],
                    "completeness": str((envelope.get("completeness") or {}).get("status")),
                    "turn_completeness_missing": list((envelope.get("completeness") or {}).get("missing_event_kinds") or []),
                },
                ensure_ascii=False,
            )
        )
