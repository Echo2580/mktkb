"""R1 跨实体探针（保管侧；只输出计数/布尔，不回显实体值）。"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r1_safe_project as base  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    for name in ("key", "binding", "evidence-root", "receipt", "seal-manifest", "case-plan"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    guard = base.NetGuard()
    guard.install()
    guard.positive_control()

    key = pathlib.Path(args.key).read_bytes().strip()
    binding = base._read_json(pathlib.Path(args.binding))
    receipt = base._read_json(pathlib.Path(args.receipt))
    seal_manifest = base._read_json(pathlib.Path(args.seal_manifest))
    case_plan = base._read_json(pathlib.Path(args.case_plan))
    plan_rows = case_plan["cases"]
    turn_files = [str(t["evidence_file"]) for r in plan_rows for t in (r.get("turns") or ()) if str(t.get("status")) == "executed"]
    base._verify_custody(binding, pathlib.Path(args.case_plan), case_plan, receipt, seal_manifest, pathlib.Path(args.evidence_root), turn_files)

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415

    wanted = {x.strip() for x in args.cases.split(",") if x.strip()}
    out: dict[str, object] = {}
    for row in plan_rows:
        case_id = str(row.get("case_id"))
        if case_id not in wanted:
            continue
        turns = []
        for turn in row.get("turns") or ():
            env = read_encrypted_evidence(pathlib.Path(args.evidence_root) / str(turn["evidence_file"]), key=key)
            events = ((env.get("capture") or {}).get("events") or [])
            projection = env.get("db_projection") or {}
            messages = [m for m in (projection.get("messages") or []) if isinstance(m, dict)]
            question = next((str(m.get("text") or "") for m in messages if str(m.get("role")) == "user"), "")
            answer = next((str(m.get("text") or "") for m in messages if str(m.get("role")) == "assistant"), "")
            plan_payloads = [e.get("payload") or {} for e in events if str(e.get("kind")) == "plan_observed"]
            plan = plan_payloads[0] if plan_payloads else {}
            filters = plan.get("filters") if isinstance(plan.get("filters"), dict) else {}
            states = [e.get("payload") or {} for e in events if str(e.get("kind")) == "query_state_saved"]
            state = (states[0].get("state_json") or {}) if states else {}
            stores = [str(s) for s in (state.get("stores") or []) if str(s)]
            store = str(state.get("store") or "") or (str(filters.get("store") or ""))
            units = [u for u in (projection.get("units") or []) if isinstance(u, dict)]
            unit_stores = []
            for unit in units:
                ef = unit.get("entity_filters") if isinstance(unit.get("entity_filters"), dict) else {}
                unit_stores.append(str(ef.get("store") or ""))
            target = store
            same = sum(1 for s in unit_stores if target and s == target)
            other = sum(1 for s in unit_stores if target and s and s != target)
            unknown = sum(1 for s in unit_stores if not s)
            other_only = sorted({s for s in unit_stores if target and s and s != target})
            answer_mentions_other = sum(answer.count(s) for s in other_only)
            turns.append(
                {
                    "turn_index": turn.get("turn_index"),
                    "question_chars": len(question),
                    "plan_mode": plan.get("mode"),
                    "plan_path": plan.get("path"),
                    "plan_enumerate": bool(plan.get("enumerate")),
                    "filter_keys": sorted(str(k) for k in filters),
                    "state_store_count": len(stores),
                    "state_has_store": bool(store),
                    "units": len(units),
                    "units_same_store": same,
                    "units_other_store": other,
                    "units_unknown_store": unknown,
                    "distinct_other_stores": len(other_only),
                    "answer_mentions_other_store": answer_mentions_other,
                    "answer_chars": len(answer),
                }
            )
        out[case_id] = turns

    pathlib.Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "cases": sorted(out), "netguard": guard.as_dict()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
