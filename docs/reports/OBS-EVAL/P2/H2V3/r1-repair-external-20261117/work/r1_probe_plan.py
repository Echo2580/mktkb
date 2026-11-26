"""R1 计划/证据形状探针（保管侧，只输出固定码与计数）。

目的：为 C05/C07/C13/C22/C28 采集“计划面”可用于合成复现的最小事实：
- plan_observed 的字段/过滤键名是否出现（只输出现有 schema 键名与计数，不输出值）；
- 是否存在 entity_filters 及其实体类型计数；
- 引用单元的 role_values 角色键集合（只输出角色名，是否属于 phone/address）；
- 答案 kind/长度/引用数。
所有字符串输出前只保留匹配 ``^[A-Za-z_][A-Za-z0-9_:.\\-]{0,40}$`` 的“码形”字符串，
其余一律记 ``<non_code>`` 计数，绝不回显正文/实体值/路径。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r1_safe_project as base  # noqa: E402

CODE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_:.\-]{0,40}$")
ROLE_HINTS = ("phone", "address", "contact", "price", "spec", "validity", "quantity", "date", "name", "code")


def _shape(value: object, depth: int = 0) -> object:
    if depth > 3:
        return "<depth>"
    if isinstance(value, dict):
        return {str(k): _shape(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_shape(v, depth + 1) for v in value[:6]]
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value if CODE_RE.fullmatch(value) else "<non_code>"
    return f"<{type(value).__name__}>"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--seal-manifest", required=True)
    parser.add_argument("--case-plan", required=True)
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
    turn_files = [
        str(t["evidence_file"]) for row in plan_rows for t in (row.get("turns") or ()) if str(t.get("status")) == "executed"
    ]
    base._verify_custody(binding, pathlib.Path(args.case_plan), case_plan, receipt, seal_manifest, pathlib.Path(args.evidence_root), turn_files)

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415

    wanted = {item.strip() for item in args.cases.split(",") if item.strip()}
    out: dict[str, object] = {}
    for row in plan_rows:
        case_id = str(row.get("case_id"))
        if case_id not in wanted:
            continue
        turns = []
        for turn in row.get("turns") or ():
            env = read_encrypted_evidence(
                pathlib.Path(args.evidence_root) / str(turn["evidence_file"]), key=key
            )
            events = ((env.get("capture") or {}).get("events") or [])
            kinds: dict[str, int] = {}
            plan_shapes: list[object] = []
            for event in events:
                kind = str(event.get("kind"))
                kinds[kind] = kinds.get(kind, 0) + 1
                if kind in ("plan_observed", "claim_observed", "query_state_saved"):
                    plan_shapes.append({"kind": kind, "payload": _shape(event.get("payload"))})
            projection = env.get("db_projection") or {}
            units = [u for u in (projection.get("units") or []) if isinstance(u, dict)]
            role_keys: dict[str, int] = {}
            for unit in units:
                for role in ((unit.get("role_values") or {}) if isinstance(unit.get("role_values"), dict) else {}):
                    role_keys[str(role)] = role_keys.get(str(role), 0) + 1
            turns.append(
                {
                    "turn_index": turn.get("turn_index"),
                    "event_kinds": kinds,
                    "plan_shapes": plan_shapes[:6],
                    "unit_count": len(units),
                    "role_keys": role_keys,
                    "role_hint_count": sum(v for k, v in role_keys.items() if any(h in k.lower() for h in ROLE_HINTS)),
                }
            )
        out[case_id] = turns

    text = json.dumps(out, ensure_ascii=False, indent=2)
    pathlib.Path(args.out).write_text(text, encoding="utf-8")
    print(json.dumps({"ok": True, "cases": sorted(out), "netguard": guard.as_dict()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
