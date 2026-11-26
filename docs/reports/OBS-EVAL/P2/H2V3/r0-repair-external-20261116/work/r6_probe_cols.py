"""R0 第六轮列形状探针：只打印角色码 / 列序号 / 整数，绝不打印任何值。

离线；只读私有输入。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

RUN_ROOT = pathlib.Path(r"D:\mktkb-p2-h2v3-r0fix6-20261116\r0")
BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-final5\bindings\run0-base_b0.binding.json"
)
KEY_PATH = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key")
ID = "p2-h2v3-20261115-r0-base_b0"
CASE = "H2V3-C27"


def _repo_root() -> pathlib.Path:
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "backend" / "src" / "mktkb").is_dir():
            return parent
    raise SystemExit("repo_root_not_found")


REPO = _repo_root()
sys.path.insert(0, str(REPO / "backend" / "src"))
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))

from mktkb.rag.chunking import field_role  # noqa: E402


def main() -> int:
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    run_entry = json.loads((RUN_ROOT / "v3-entry-p2-h2v3-20261115-r0-base_b0.json").read_text(encoding="utf-8"))
    case_plan = json.loads((RUN_ROOT / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8"))
    key = KEY_PATH.read_bytes()

    spec = importlib.util.spec_from_file_location("p2h2v3_entry", TOOLS / "p2_h2_v3_controlled_execute.py")
    entry = importlib.util.module_from_spec(spec)
    sys.modules["p2h2v3_entry"] = entry
    spec.loader.exec_module(entry)

    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    cases = tuple(bundle.contract.subset(str(run_entry.get("scenario_id"))).cases)
    case = next(item for item in cases if str(item.case_id) == CASE)

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence

    row = next(item for item in case_plan["cases"] if str(item.get("case_id")) == CASE)
    env = read_encrypted_evidence(
        RUN_ROOT / "evidence" / ID / str(row["turns"][-1]["evidence_file"]),
        key=key,
        expected_bindings=dict(case_plan["bindings"]),
    )
    proj = env["db_projection"]
    units = {str(u.get("unit_id")): u for u in (proj.get("units") or [])}
    events = (env.get("capture") or {}).get("events") or []
    dra = [ev["payload"] for ev in events if ev.get("kind") == "direct_rag_answer"][0]
    plan_obs = [ev["payload"] for ev in events if ev.get("kind") == "plan_observed"][0]
    ans = [ev["payload"] for ev in events if ev.get("kind") == "answer_result"][0]

    print("plan_field_roles=", list(plan_obs.get("field_roles") or ()))
    print("plan_field_role=", plan_obs.get("field_role"))
    print("plan_mode=", plan_obs.get("mode"), "enumerate=", plan_obs.get("enumerate"))
    print("answer_kind=", ans.get("kind"), "answer_reason=", ans.get("reason"))
    print("dra_kind=", dra.get("kind"), "dra_reason=", dra.get("reason"), "fact_count=", dra.get("fact_count"))
    print("dra_cited_units=", len(dra.get("cited_unit_ids") or ()))
    print("facts_type=", type(dra.get("facts")).__name__, "len=", len(dra.get("facts") or ()))
    if dra.get("facts"):
        print("fact0_keys=", sorted(dra["facts"][0].keys()) if isinstance(dra["facts"][0], dict) else "scalar")
        print("fact_roles=", [f.get("field_role") for f in dra["facts"] if isinstance(f, dict)])

    cited = [units[str(uid)] for uid in (dra.get("cited_unit_ids") or ()) if str(uid) in units]
    print("cited_rows=", len(cited))
    for unit in cited:
        raw_fields = unit.get("raw_fields") or {}
        print("row_raw_field_count=", len(raw_fields))
        print("row_role_sequence=", [field_role(name) for name in raw_fields])
        loc = unit.get("locator") or {}
        cells = loc.get("cells")
        print("locator_cells_type=", type(cells).__name__, "len=", (len(cells) if hasattr(cells, "__len__") else -1))
        header = loc.get("header_row")
        print("header_row_type=", type(header).__name__, "len=", (len(header) if hasattr(header, "__len__") else -1))
        print("locator_row=", loc.get("row"), "header_index=", loc.get("header_index"))
        print("text_len=", len(str(unit.get("text") or "")))
        print("date_fields=", unit.get("date_fields"))
        print("entity_type=", unit.get("entity_type"), "kind=", unit.get("kind"))

    print("case_expected_values_type=", type(case.expected_values).__name__, "len=", len(case.expected_values))
    print("case_expected_kind=", case.expected_kind)
    print("case_relevant_units=", len(case.relevant_units or ()))
    print("case_expected_sources=", len(case.expected_sources or ()))
    print("turn_count=", len(case.turns or ()))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - 只出固定码，绝不回显
        print("probe_failed")
        raise SystemExit(1) from None
