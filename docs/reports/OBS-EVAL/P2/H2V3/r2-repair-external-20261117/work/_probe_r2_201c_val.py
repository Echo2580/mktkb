"""201C 判据探针（第 3 号）：C29 的缺失值/缺失来源**到底在哪一层还有**。

只输出布尔与固定码：
- 每个 expected value 是否出现在「已服务 unit 正文 / raw_fields / fact.value / 答案正文」里；
- 每个 expected source 用**canonical matcher**（``p2_evidence_rescore.match_ref_to_unit``）
  对每个投影 unit 的 verdict/reason；
- annotation 的 target_refs / targets 形态（只导集合名、索引、码）。
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

KEY = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key")
BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-single-01\bindings"
    r"\run2-pre_v05_without_v07.binding.json"
)
EVIDENCE_ROOT = pathlib.Path(
    r"D:\mktkb-p2-h2v3-fullverify-20261116\r2\evidence\p2-h2v3-20261115-r2-pre_v05_without_v07"
)
CASE_PLAN = (
    base.REPO
    / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"
)
OUT = _WORK / "out" / "probe-201c-val.txt"


def payloads(events: Any, kind: str) -> list[Mapping[str, Any]]:
    out = []
    for event in events:
        if isinstance(event, Mapping) and str(event.get("kind")) == kind:
            payload = event.get("payload")
            if isinstance(payload, Mapping):
                out.append(payload)
    return out


def main() -> int:
    guard = base.NetGuard()
    guard.install()
    guard.positive_control()
    lines: list[str] = []
    key = KEY.read_bytes().strip()
    binding = base._read_json(BINDING)
    case_plan = base._read_json(CASE_PLAN)
    run_entry = binding["runs"][0]
    entry = base._load_module(
        "p2_h2_v3_controlled_execute_probeval",
        base.TOOLS / "p2_h2_v3_controlled_execute.py",
    )
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415
    import mktkb.evaluation.p2_scoring as scoring  # noqa: PLC0415
    import mktkb.evaluation.p2_score_run as score_run  # noqa: PLC0415
    import mktkb.evaluation.p2_runner as runner  # noqa: PLC0415
    import mktkb.evaluation.scorers as scorers_mod  # noqa: PLC0415
    from mktkb.evaluation import p2_evidence_rescore as rescore  # noqa: PLC0415

    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    cases = tuple(bundle.contract.subset(str(run_entry.get("scenario_id"))).cases)
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

    # annotation 结构
    annotation = bundle.annotation
    lines.append(f"annotation type={type(annotation).__name__}")
    lines.append(f"annotation attrs={[n for n in dir(annotation) if not n.startswith('_')][:20]}")
    axes_obj = getattr(annotation, "axes", None)
    if axes_obj is not None:
        lines.append(f"annotation.axes type={type(axes_obj).__name__}")
        try:
            keys = sorted(axes_obj) if isinstance(axes_obj, Mapping) else sorted(dir(axes_obj))
            lines.append(f"annotation.axes keys={keys[:12]}")
        except Exception:  # noqa: BLE001
            lines.append("annotation.axes keys=<unreadable>")

    for case in cases:
        case_id = str(case.case_id)
        lines.append("=" * 70)
        lines.append(f"CASE {case_id}")
        mapped = score_run.remap_holdout_case(case, source_map)
        values = [str(v) for v in (getattr(mapped, "expected_values", ()) or ())]
        refs = [dict(r) for r in (getattr(mapped, "expected_sources", ()) or ())]
        envelopes = envelopes_by_case.get(case_id) or ()
        last = envelopes[-1] if envelopes else {}
        events = [
            e for e in ((last.get("capture") or {}).get("events") or ()) if isinstance(e, Mapping)
        ]
        projection = last.get("db_projection") or {}
        units = [u for u in (projection.get("units") or ()) if isinstance(u, Mapping)]
        answers = payloads(events, "answer_result")
        answer_text = answers[-1].get("text") if answers and isinstance(answers[-1].get("text"), str) else ""
        commits = payloads(events, "commit_observed")
        commit_text = commits[-1].get("text") if commits and isinstance(commits[-1].get("text"), str) else ""
        direct = payloads(events, "direct_rag_answer")
        facts = [f for f in ((direct[-1].get("facts") or ()) if direct else ()) if isinstance(f, Mapping)]

        def all_text(unit: Mapping[str, Any]) -> str:
            parts = []
            if isinstance(unit.get("text"), str):
                parts.append(unit["text"])
            for key in ("raw_fields", "date_fields", "locator"):
                block = unit.get(key)
                if isinstance(block, Mapping):
                    for value in block.values():
                        if isinstance(value, str):
                            parts.append(value)
                        elif isinstance(value, (list, tuple)):
                            parts.extend(str(x) for x in value if isinstance(x, (str, int, float)))
                        elif isinstance(value, (int, float)):
                            parts.append(str(value))
            return "\n".join(parts)

        unit_texts = [all_text(u) for u in units]
        unit_raw = [
            "\n".join(
                str(value)
                for block in (u.get("raw_fields"), u.get("date_fields"))
                if isinstance(block, Mapping)
                for value in block.values()
                if isinstance(value, (str, int, float))
            )
            for u in units
        ]
        fact_vals = [str(f.get("value")) for f in facts if isinstance(f.get("value"), str)]
        for index, value in enumerate(values):
            row = {
                "in_unit_text": any(scorers_mod.check_value(t, value) for t in unit_texts),
                "in_unit_raw": any(scorers_mod.check_value(t, value) for t in unit_raw),
                "in_fact_value": any(scorers_mod.check_value(t, value) for t in fact_vals),
                "in_answer": scorers_mod.check_value(answer_text, value),
                "in_commit": scorers_mod.check_value(commit_text, value),
                "value_len": len(value),
            }
            lines.append(f"  value[{index}] {row}")
        for index, ref in enumerate(refs):
            lines.append(
                f"  ref[{index}] has_rec={isinstance(ref.get('record_code'), str)}"
                f" loc_keys={sorted(dict(ref.get('locator') or {}))}"
                f" doc_resolves={base._read_json is not None}"
            )
            for u_index, unit in enumerate(units):
                view = rescore.UnitView(
                    unit_id=str(unit.get("unit_id")),
                    layers=("direct_rag_fact",),
                    document_id=str(unit.get("document_id")) if unit.get("document_id") else None,
                    document_name=unit.get("document_name"),
                    doc_code=scoring._lookup_document_code(  # noqa: SLF001
                        unit.get("document_name"), document_codes
                    ),
                    version_id=str(unit.get("version_id")) if unit.get("version_id") else None,
                    version_number=unit.get("version_number")
                    if type(unit.get("version_number")) is int
                    else None,
                    unit_key=unit.get("unit_key"),
                    record_code=None,
                    locator=dict(unit.get("locator") or {}),
                )
                ref_doc = str(ref.get("doc_code") or "")
                ref_loc = dict(ref.get("locator") or {})
                clean_loc = {k: v for k, v in ref_loc.items() if k in rescore.LOCATOR_KEYS}
                clean_ref = {"doc_code": ref_doc, "locator": clean_loc}
                lines.append(
                    "     units[%d]/raw: doc_match=%s sheet_match=%s row_match=%s ver_match=%s"
                    % (
                        u_index,
                        view.doc_code == ref_doc,
                        view.locator.get("sheet") == ref_loc.get("sheet"),
                        view.locator.get("row") == ref_loc.get("row"),
                        view.version_number == ref_loc.get("version_number"),
                    )
                )
                for label, binding_arg in (
                    ("no_binding", None),
                    ("number_from_unit", rescore.VersionBinding(version_number=view.version_number, basis="source_map")),
                ):
                    try:
                        result = rescore.match_ref_to_unit(clean_ref, view, version_binding=binding_arg)
                        lines.append(
                            f"     units[{u_index}]/{label}: verdict={result.verdict} reason={result.reason}"
                        )
                    except Exception as exc:  # noqa: BLE001
                        lines.append(f"     units[{u_index}]/{label}: exc={type(exc).__name__}")
        # annotation per case
        axis_rows = getattr(annotation, "cases", None)
        lines.append(f"  annotation_cases_type={type(axis_rows).__name__ if axis_rows is not None else 'None'}")
        try:
            contract_case = axis_rows.get(case_id) if isinstance(axis_rows, Mapping) else None
            lines.append(f"  contract_case_type={type(contract_case).__name__ if contract_case else 'None'}")
            if contract_case is not None:
                lines.append(
                    f"  contract_case attrs={[n for n in dir(contract_case) if not n.startswith('_')][:24]}"
                )
        except Exception as exc:  # noqa: BLE001
            lines.append(f"  contract_case_probe_exc={type(exc).__name__}")
        lines.append(f"  units={len(units)} facts={len(facts)} answer_kind={answers[-1].get('kind') if answers else 'na'}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} lines={len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
