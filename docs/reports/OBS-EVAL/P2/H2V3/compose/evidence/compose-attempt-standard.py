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
    "p2_h2_v3_controlled_execute_probe4", REPO / "tools" / "p2_h2_v3_controlled_execute.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from mktkb.evaluation import p2_holdout_scenarios as scenarios  # noqa: E402

recomputed = json.loads((WORK / "compose-work" / "recompute-four-runs.json").read_text(encoding="utf-8"))
cards = {run["scenario_id"]: run["card"] for run in recomputed["runs"]}
binding_names = [
    "run0-base_b0.binding.json",
    "run1-base_b0_plus_v01.binding.json",
    "run2-pre_v05_without_v07.binding.json",
    "run3-post_v05_without_v01.binding.json",
]
documents = [
    json.loads((WORK / "regen-1160c" / "bindings" / name).read_text(encoding="utf-8"))
    for name in binding_names
]
inputs = {name: {"path": record["path"]} for name, record in documents[0]["inputs"].items()}
bundle = module.load_v3_bundle(inputs)
contract = bundle.contract

plans = []
parts = []
for index, document in enumerate(documents):
    document["runs"][0]["run_index"] = index
    plan = module.v2._load_plan_for_run(document, document["runs"][0])
    scenario = str(document["runs"][0]["scenario_id"])
    plans.append(plan)
    parts.append(
        {
            "plan": plan,
            "aggregate": cards[scenario],
            "status": "succeeded",
            "run_id": str(document["runs"][0]["run_id"]),
            "turns_executed": int(document["runs"][0]["turn_count"]),
            "binding": {"scenario_binding": contract.binding(scenario)},
        }
    )

out = {}
for name, func in (
    ("compose_scenario_runs", scenarios.compose_scenario_runs),
    ("compose_hard_evidence_runs", scenarios.compose_hard_evidence_runs),
):
    try:
        payload = func(contract, parts)
        out[name] = {"ok": True, "keys": sorted(payload)}
    except Exception as exc:  # noqa: BLE001 - 记录固定码
        out[name] = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error_code": str(getattr(exc, "code", "") or exc),
        }
    print(name, json.dumps(out[name], ensure_ascii=False))

(WORK / "compose-work" / "compose-attempt.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
