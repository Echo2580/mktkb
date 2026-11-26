"""R0 第六轮结构探针：只打印 schema 形状（键名/事件 kind/计数），绝不打印任何私有值。

离线；只读私有输入；输出仅结构键名与整数计数。
"""
from __future__ import annotations

import json
import pathlib
import sys

def _repo_root() -> pathlib.Path:
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "backend" / "src" / "mktkb").is_dir():
            return parent
    raise SystemExit("repo_root_not_found")


REPO = _repo_root()
BACKEND_SRC = REPO / "backend" / "src"
TOOLS = REPO / "tools"
for path in (str(BACKEND_SRC), str(TOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

RUN_ROOT = pathlib.Path(r"D:\mktkb-p2-h2v3-r0fix6-20261116\r0")
BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-final5\bindings\run0-base_b0.binding.json"
)
KEY_PATH = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key")
ID = "p2-h2v3-20261115-r0-base_b0"


def main() -> int:
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    run_entry = json.loads((RUN_ROOT / "v3-entry-p2-h2v3-20261115-r0-base_b0.json").read_text(encoding="utf-8"))
    case_plan = json.loads((RUN_ROOT / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8"))
    key = KEY_PATH.read_bytes()

    import importlib.util

    spec = importlib.util.spec_from_file_location("p2h2v3_entry", TOOLS / "p2_h2_v3_controlled_execute.py")
    entry = importlib.util.module_from_spec(spec)
    sys.modules["p2h2v3_entry"] = entry
    spec.loader.exec_module(entry)

    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    scenario = str(run_entry.get("scenario_id"))
    cases = tuple(bundle.contract.subset(scenario).cases)

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence

    rows = {str(row.get("case_id")): row for row in case_plan["cases"]}
    cid = "H2V3-C27"
    row = rows[cid]
    print("case_turns=", len(row["turns"]))
    case = next(item for item in cases if str(item.case_id) == cid)
    print("case_type=", type(case).__name__)
    print("case_keys=", sorted(k for k in dir(case) if not k.startswith("_")))

    envelopes = []
    for turn_row in row["turns"]:
        env = read_encrypted_evidence(
            RUN_ROOT / "evidence" / ID / str(turn_row["evidence_file"]),
            key=key,
            expected_bindings=dict(case_plan["bindings"]),
        )
        envelopes.append(env)
    print("envelopes=", len(envelopes))
    env = envelopes[-1]
    print("envelope_keys=", sorted(env.keys()))
    proj = env.get("db_projection") or {}
    print("projection_keys=", sorted(proj.keys()))
    units = proj.get("units") or []
    print("units=", len(units))
    if units:
        print("unit0_keys=", sorted(units[0].keys()))
        print("unit0_locator_keys=", sorted((units[0].get("locator") or {}).keys()))
    print("message_sources=", len(proj.get("message_sources") or []))
    print("request_keys=", sorted((proj.get("request") or {}).keys()))
    capture = env.get("capture") or {}
    events = capture.get("events") or []
    print("event_kinds=", sorted({str(ev.get("kind")) for ev in events}))
    for ev in events:
        kind = str(ev.get("kind"))
        payload = ev.get("payload") or {}
        if isinstance(payload, dict):
            print(f"payload_keys[{kind}]=", sorted(payload.keys()))
        else:
            print(f"payload_keys[{kind}]=", type(payload).__name__)
    print("top_keys=", sorted(env.keys()))
    print("meta_keys=", sorted((env.get("meta") or {}).keys()) if isinstance(env.get("meta"), dict) else "none")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - 只出固定码，绝不回显
        print("probe_failed")
        raise SystemExit(1) from None
