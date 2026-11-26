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
    "p2_h2_v3_controlled_execute_probe5", REPO / "tools" / "p2_h2_v3_controlled_execute.py"
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


class DispatchContract:
    """诊断用：只在内存里把 v3 已授权的 index_embedding 批次差按 scenario 分派给执行期子类。"""

    def __init__(self, inner, wrappers):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_wrappers", wrappers)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def validate_run(self, plan, dataset, ingest):
        scenario = str(dict(plan.scenario_binding or {}).get("scenario_id") or "")
        return self._wrappers[scenario].validate_run(plan, dataset, ingest)


wrappers = {}
parts = []
for index, document in enumerate(documents):
    run_entry = document["runs"][0]
    run_entry["run_index"] = index
    plan = module.v2._load_plan_for_run(document, run_entry)
    scenario = str(run_entry["scenario_id"])
    authorized = dict(run_entry["contract_validate_run"]["authorized_delta"])
    wrappers[scenario] = module._wrap_v3_contract(contract, authorized=authorized)
    parts.append(
        {
            "plan": plan,
            "aggregate": cards[scenario],
            "status": "succeeded",
            "run_id": str(run_entry["run_id"]),
            "turns_executed": int(run_entry["turn_count"]),
            "binding": {"scenario_binding": contract.binding(scenario)},
        }
    )

proxy = DispatchContract(contract, wrappers)
out = {}
try:
    payload = scenarios.compose_hard_evidence_runs(proxy, parts)
    out["compose_hard_evidence_runs_after_delta_adapter"] = {"ok": True, "keys": sorted(payload)}
except Exception as exc:  # noqa: BLE001
    out["compose_hard_evidence_runs_after_delta_adapter"] = {
        "ok": False,
        "error_type": type(exc).__name__,
        "error_code": str(getattr(exc, "code", "") or exc),
    }
print(json.dumps(out, ensure_ascii=False))

target = WORK / "compose-work" / "compose-attempt-after-delta.json"
target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
