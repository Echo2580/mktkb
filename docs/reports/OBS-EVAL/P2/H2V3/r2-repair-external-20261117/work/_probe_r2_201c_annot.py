"""201C 标注探针（第 5 号）：``bundle.annotation.payload['cases']`` 的逐案轴标注结构。

只导：每案出现的轴名、轴 payload 的键集、``target_refs`` 的 (collection,index)、``targets``
的个数与过滤键名、``as_of`` / ``temporal_intent`` 的码值。绝不导实体值/文档名/题面。
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any, Mapping

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r2_safe_project as base  # noqa: E402

BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-single-01\bindings"
    r"\run2-pre_v05_without_v07.binding.json"
)
OUT = _WORK / "out" / "probe-201c-annot.txt"


def safe(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value if base.CODE_RE.fullmatch(value) else f"<str:{len(value)}>"
    if value is None:
        return "None"
    if isinstance(value, Mapping):
        return "{" + ",".join(sorted(str(k) for k in value))[:220] + "}"
    if isinstance(value, (list, tuple)):
        return f"<seq:{len(value)}>"
    return f"<{type(value).__name__}>"


def main() -> int:
    guard = base.NetGuard()
    guard.install()
    guard.positive_control()
    lines: list[str] = []
    binding = base._read_json(BINDING)
    run_entry = binding["runs"][0]
    entry = base._load_module(
        "p2_h2_v3_controlled_execute_probeannot",
        base.TOOLS / "p2_h2_v3_controlled_execute.py",
    )
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    payload = bundle.annotation.payload
    cases = payload.get("cases")
    lines.append(f"cases n={len(cases)}")
    lines.append(f"cases[0] type={type(cases[0]).__name__} keys={sorted(cases[0]) if isinstance(cases[0], Mapping) else 'na'}")
    wanted = {"H2V3-C25", "H2V3-C29", "H2V3-C14"}
    for index, row in enumerate(cases):
        if not isinstance(row, Mapping):
            continue
        case_id = str(row.get("case_id") or "")
        if index < 2:
            lines.append(f"  [{index}] case_id={safe(row.get('case_id'))} keys={sorted(row)}")
        if case_id not in wanted:
            continue
        lines.append("=" * 66)
        lines.append(f"CASE {case_id} keys={sorted(row)}")
        axes = row.get("axes") or row.get("axis") or {}
        if isinstance(axes, Mapping):
            lines.append(f"  axes={sorted(axes)}")
            for axis_name, axis_payload in axes.items():
                if not isinstance(axis_payload, Mapping):
                    lines.append(f"    {axis_name}: {safe(axis_payload)}")
                    continue
                lines.append(f"    {axis_name}: keys={sorted(axis_payload)}")
                for field in (
                    "applicability",
                    "criterion",
                    "reason",
                    "as_of",
                    "temporal_intent",
                ):
                    if field in axis_payload:
                        lines.append(f"      {field}={safe(axis_payload[field])}")
                refs = axis_payload.get("target_refs")
                if isinstance(refs, (list, tuple)):
                    lines.append(f"      target_refs n={len(refs)}")
                    for r_index, ref in enumerate(refs):
                        if isinstance(ref, Mapping):
                            lines.append(
                                f"        target_refs[{r_index}] keys={sorted(ref)} "
                                f"collection={safe(ref.get('collection'))} index={safe(ref.get('index'))}"
                            )
                tgts = axis_payload.get("targets")
                if isinstance(tgts, (list, tuple)):
                    lines.append(f"      targets n={len(tgts)}")
                    for t_index, tgt in enumerate(tgts):
                        if isinstance(tgt, Mapping):
                            lines.append(
                                f"        targets[{t_index}] keys={sorted(tgt)} "
                                f"entity_type={safe(tgt.get('entity_type'))} "
                                f"entity_key={safe(tgt.get('entity_key'))} "
                                f"filters_keys={sorted(dict(tgt.get('filters') or {}))}"
                            )
        else:
            lines.append(f"  axes(fallback)={safe(axes)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} lines={len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
