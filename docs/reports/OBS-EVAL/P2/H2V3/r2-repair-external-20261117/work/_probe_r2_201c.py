"""201C 结构探针：只导结构（键名/类型/计数/固定码短值），绝不导题干、答案、实体值、私有路径。

用途：在为 r2_boundary_ext.py 写层表之前，确认 R2 事件协议里到底有没有
``field_role`` / ``as_of`` / ``retrieval_observed`` / ``facts[]`` / ``units[]`` 这些面，
以及 C29/C25 的 expected target ref 形态。探针结果只落到 ``work/out/probe-201c.txt``。
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys
from typing import Any, Mapping, Sequence

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r2_safe_project as base  # noqa: E402

KEY = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key")
BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-single-01\bindings"
    r"\run2-pre_v05_without_v07.binding.json"
)
EVIDENCE_ROOT = pathlib.Path(
    r"D:\mktkb-p2-h2v3-fullverify-20261116\r2\evidence\p2-h2v3-20261115-r2-pre_v05_without_v07"
)
RECEIPT = pathlib.Path(
    r"D:\mktkb-p2-h2v3-fullverify-20261116\r2\seal"
    r"\p2-h2v3-20261115-r2-pre_v05_without_v07\run-receipt.json"
)
SEAL = pathlib.Path(
    r"D:\mktkb-p2-h2v3-fullverify-20261116\r2\seal"
    r"\p2-h2v3-20261115-r2-pre_v05_without_v07\seal-manifest.json"
)
CASE_PLAN = (
    base.REPO
    / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"
)
OUT = _WORK / "out" / "probe-201c.txt"


def short(value: Any) -> str:
    """只在值像固定码/短标量时回显；长字符串只回长度。"""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        if base.CODE_RE.fullmatch(value):
            return value
        return f"<str:{len(value)}>"
    if value is None:
        return "None"
    if isinstance(value, Mapping):
        return f"<map:{len(value)}>"
    if isinstance(value, (list, tuple)):
        return f"<seq:{len(value)}>"
    return f"<{type(value).__name__}>"


def keydump(value: Any, label: str) -> list[str]:
    lines = [f"-- {label}: {type(value).__name__}"]
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            lines.append(f"   {key} = {short(value[key])}")
    elif isinstance(value, (list, tuple)):
        lines.append(f"   len={len(value)}")
        if value and isinstance(value[0], Mapping):
            lines.append(f"   [0] keys = {sorted(value[0], key=str)}")
    return lines


def main() -> int:
    guard = base.NetGuard()
    guard.install()
    guard.positive_control()
    lines: list[str] = []
    key = KEY.read_bytes().strip()
    binding = base._read_json(BINDING)
    receipt = base._read_json(RECEIPT)
    seal = base._read_json(SEAL)
    case_plan = base._read_json(CASE_PLAN)
    run_entry = binding["runs"][0]
    plan_rows = case_plan["cases"]
    ordered = [str(row["case_id"]) for row in plan_rows]

    entry = base._load_module(
        "p2_h2_v3_controlled_execute_probe",
        base.TOOLS / "p2_h2_v3_controlled_execute.py",
    )
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415
    import mktkb.evaluation.p2_scoring as scoring  # noqa: PLC0415
    import mktkb.evaluation.p2_score_run as score_run  # noqa: PLC0415
    import mktkb.evaluation.p2_runner as runner  # noqa: PLC0415
    import mktkb.evaluation.scorers as scorers_mod  # noqa: PLC0415

    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    scenario = str(run_entry.get("scenario_id"))
    lines.append(f"scenario={scenario} manifest_cases={len(ordered)}")
    cases = tuple(bundle.contract.subset(scenario).cases)
    document_codes = runner.holdout_document_codes(bundle.contract._ingest)  # noqa: SLF001
    static_bindings = {
        str(name): value
        for name, value in dict(run_entry.get("evidence_bindings") or {}).items()
        if str(name) != "index_revision"
    }
    plan = entry.v2._validate_case_plan_document(
        dict(case_plan), cases=cases, static_bindings=static_bindings
    )
    rows, envelopes_by_case = base._build_rows(
        cases,
        plan["cases"],
        EVIDENCE_ROOT,
        key,
        plan["bindings"],
        document_codes,
        read_encrypted_evidence,
        scoring._lookup_document_code,  # noqa: SLF001
        collections.defaultdict(int),
    )

    source_map = score_run.load_holdout_source_map()
    for case in cases:
        case_id = str(case.case_id)
        mapped = score_run.remap_holdout_case(case, source_map)
        envelopes = envelopes_by_case.get(case_id) or ()
        lines.append("=" * 70)
        lines.append(f"CASE {case_id} turns={len(envelopes)}")
        lines.append(f"expected_values={len(getattr(mapped, 'expected_values', ()) or ())}")
        refs = list(getattr(mapped, "expected_sources", ()) or ())
        lines.append(f"expected_sources={len(refs)}")
        for index, ref in enumerate(refs):
            ref_map = dict(ref)
            lines.append(
                f"  ref[{index}] keys={sorted(ref_map, key=str)} "
                f"doc_code={short(ref_map.get('doc_code'))} "
                f"unit_key={short(ref_map.get('unit_key'))} "
                f"locator_keys={sorted(dict(ref_map.get('locator') or {}), key=str)}"
            )
        kinds = getattr(mapped, "expected_kinds", None)
        lines.append(f"  expected_kinds={short(kinds)}")
        for turn_index, envelope in enumerate(envelopes):
            lines.append(f"  -- turn[{turn_index}] top_keys={sorted(envelope, key=str)}")
            for section in ("turn", "completeness"):
                block = envelope.get(section)
                if isinstance(block, Mapping):
                    lines.extend(keydump(block, f"turn[{turn_index}].{section}"))
            capture = envelope.get("capture")
            if isinstance(capture, Mapping):
                lines.extend(keydump(capture, f"turn[{turn_index}].capture"))
                events = [item for item in (capture.get("events") or ()) if isinstance(item, Mapping)]
                counts = collections.Counter(
                    str(item.get("kind")) for item in events
                )
                lines.append(f"     event_kinds={dict(sorted(counts.items()))}")
                seen: set[str] = set()
                for item in events:
                    kind = str(item.get("kind"))
                    if kind in seen:
                        continue
                    seen.add(kind)
                    payload = item.get("payload")
                    if isinstance(payload, Mapping):
                        lines.extend(keydump(payload, f"turn[{turn_index}].event[{kind}].payload"))
            projection = envelope.get("db_projection")
            if isinstance(projection, Mapping):
                lines.extend(keydump(projection, f"turn[{turn_index}].db_projection"))
                units = projection.get("units") or ()
                if units:
                    lines.append(f"     units.len={len(units)}")
                    lines.append(f"     units[0].keys={sorted(units[0], key=str) if isinstance(units[0], Mapping) else type(units[0]).__name__}")
                    for index, unit in enumerate(units):
                        if not isinstance(unit, Mapping):
                            continue
                        lines.append(
                            f"     units[{index}] unit_key={short(unit.get('unit_key'))} "
                            f"doc_name={short(unit.get('document_name'))} "
                            f"ver={short(unit.get('version_number'))} "
                            f"status={short(unit.get('status'))} "
                            f"locator_keys={sorted(dict(unit.get('locator') or {}), key=str)} "
                            f"text_chars={len(unit.get('text')) if isinstance(unit.get('text'), str) else 'na'} "
                            f"raw_field_keys={sorted(dict(unit.get('raw_fields') or {}), key=str)} "
                            f"date_field_keys={sorted(dict(unit.get('date_fields') or {}), key=str)}"
                        )
                msgs = projection.get("message_sources") or ()
                lines.append(f"     message_sources.len={len(msgs)}")
                req = projection.get("request")
                if isinstance(req, Mapping):
                    lines.extend(keydump(req, f"turn[{turn_index}].db_projection.request"))
                state = projection.get("query_state")
                if isinstance(state, Mapping):
                    lines.extend(keydump(state, f"turn[{turn_index}].db_projection.query_state"))
                for extra in ("messages", "claims"):
                    block = projection.get(extra)
                    if isinstance(block, Sequence) and not isinstance(block, (str, bytes)):
                        lines.append(f"     {extra}.len={len(block)}")
                        if block and isinstance(block[0], Mapping):
                            lines.append(f"     {extra}[0].keys={sorted(block[0], key=str)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} lines={len(lines)} netguard_blocked={guard.blocked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
