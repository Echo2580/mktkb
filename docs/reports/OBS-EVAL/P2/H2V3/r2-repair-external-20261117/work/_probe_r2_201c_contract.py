"""201C 契约探针（第 4 号）：只导 contract / annotation 的**结构**与固定码。

需要拿到：``contract.refs`` 的集合名与每个 ref 的 locator 键集、``contract.version_bindings``
的 basis 码（版本身份是否解析）、``annotation`` 每案 cross_entity 的 target_refs / targets /
as_of / temporal_intent。绝不导 ref 值、实体值、文档名。
"""
from __future__ import annotations

import collections
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
CASE_PLAN = (
    base.REPO
    / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"
)
OUT = _WORK / "out" / "probe-201c-contract.txt"


def safe(value: Any, depth: int = 0) -> str:
    if depth > 2:
        return "..."
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value if base.CODE_RE.fullmatch(value) else f"<str:{len(value)}>"
    if value is None:
        return "None"
    if isinstance(value, Mapping):
        return "{" + ",".join(sorted(str(k) for k in value))[:300] + "}"
    if isinstance(value, (list, tuple)):
        return f"<seq:{len(value)}>"
    return f"<{type(value).__name__}>"


def main() -> int:
    guard = base.NetGuard()
    guard.install()
    guard.positive_control()
    lines: list[str] = []
    binding = base._read_json(BINDING)
    case_plan = base._read_json(CASE_PLAN)
    run_entry = binding["runs"][0]
    entry = base._load_module(
        "p2_h2_v3_controlled_execute_probecontract",
        base.TOOLS / "p2_h2_v3_controlled_execute.py",
    )
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    contract = bundle.contract
    lines.append(f"contract type={type(contract).__name__}")
    lines.append(
        "contract attrs=" + str([n for n in dir(contract) if not n.startswith("_")])[:1200]
    )
    refs = getattr(contract, "refs", None)
    if isinstance(refs, Mapping):
        for collection, rows in refs.items():
            lines.append(f"  refs[{collection}] n={len(rows) if hasattr(rows, '__len__') else 'na'}")
            for index, row in enumerate(list(rows)[:4]):
                if isinstance(row, Mapping):
                    loc = dict(row.get("locator") or {})
                    lines.append(
                        f"    refs[{collection}][{index}] keys={sorted(row)}"
                        f" locator_keys={sorted(loc)}"
                        f" record_code_present={isinstance(row.get('record_code'), str)}"
                        f" unit_key_present={isinstance(row.get('unit_key'), str)}"
                        f" doc_code={safe(row.get('doc_code'))}"
                    )
    vb = getattr(contract, "version_bindings", None)
    if isinstance(vb, Mapping):
        bases = collections.Counter(
            str(getattr(value, "basis", "unknown")) for value in vb.values()
        )
        lines.append(f"  version_bindings n={len(vb)} bases={dict(sorted(bases.items()))}")
    targets = getattr(contract, "targets", None)
    if targets is not None:
        lines.append(f"  targets n={len(targets) if hasattr(targets,'__len__') else 'na'}")
        for index, item in enumerate(list(targets)[:4]):
            lines.append(
                f"    targets[{index}] attrs="
                + str([n for n in dir(item) if not n.startswith("_")])[:300]
            )
            for name in ("entity_type", "entity_key", "filters"):
                if hasattr(item, name):
                    lines.append(f"      {name}={safe(getattr(item, name))}")

    annotation = bundle.annotation
    lines.append(f"annotation type={type(annotation).__name__}")
    payload = getattr(annotation, "payload", None)
    lines.append(f"annotation.payload type={type(payload).__name__}")
    if isinstance(payload, Mapping):
        lines.append(f"annotation.payload keys={sorted(payload)[:20]}")
        for key in list(sorted(payload))[:3]:
            value = payload[key]
            lines.append(f"  payload[{key}] type={type(value).__name__} keys={safe(value)}")
            if isinstance(value, Mapping):
                for sub in list(sorted(value))[:6]:
                    inner = value[sub]
                    lines.append(f"    payload[{key}][{sub}] -> {safe(inner)}")
                    if isinstance(inner, Mapping):
                        lines.append(f"      keys={sorted(inner)}")
    case_index = getattr(annotation, "case_index", None)
    lines.append(f"annotation.case_index type={type(case_index).__name__}")
    if isinstance(case_index, Mapping):
        lines.append(f"  case_index keys={sorted(case_index)[:12]}")
        for key in list(sorted(case_index))[:2]:
            value = case_index[key]
            lines.append(f"  case_index[{key}] type={type(value).__name__} {safe(value)}")
            if isinstance(value, Mapping):
                lines.append(f"    keys={sorted(value)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} lines={len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
