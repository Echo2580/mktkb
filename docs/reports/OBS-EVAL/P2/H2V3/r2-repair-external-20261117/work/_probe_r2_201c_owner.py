"""201C 归属探针（第 7 号）：缺失 target 的值到底落在哪几层。

对每个 cross_entity target 只算 5 个布尔：
``in_plan_terms`` / ``in_plan_filters`` / ``in_served_unit_text`` /
``in_served_unit_raw`` / ``in_answer_text``。
用于区分「意图层丢作用域」与「该实体在本表里只是列、不可能有独立 unit」。
只输出布尔与计数。
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
OUT = _WORK / "out" / "probe-201c-owner.txt"


def value_of(entity_key: str) -> str:
    text = str(entity_key or "")
    if "id:" in text:
        return text.split("id:", 1)[1]
    if "|" in text:
        return text.split("|", 1)[1]
    return text


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
        "p2_h2_v3_controlled_execute_probeowner",
        base.TOOLS / "p2_h2_v3_controlled_execute.py",
    )
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415
    import mktkb.evaluation.p2_scoring as scoring  # noqa: PLC0415
    import mktkb.evaluation.p2_score_run as score_run  # noqa: PLC0415
    import mktkb.evaluation.p2_runner as runner  # noqa: PLC0415
    import mktkb.evaluation.scorers as scorers_mod  # noqa: PLC0415

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
    annotations = {
        str(row.get("case_id")): row
        for row in (bundle.annotation.payload.get("cases") or ())
        if isinstance(row, Mapping)
    }

    for case in cases:
        case_id = str(case.case_id)
        envelopes = envelopes_by_case.get(case_id) or ()
        cross = (annotations.get(case_id) or {}).get("axes", {}).get("cross_entity") or {}
        targets = [t for t in (cross.get("targets") or ()) if isinstance(t, Mapping)]
        last = envelopes[-1] if envelopes else {}
        events = [
            e for e in ((last.get("capture") or {}).get("events") or ()) if isinstance(e, Mapping)
        ]
        projection = last.get("db_projection") or {}
        units = [u for u in (projection.get("units") or ()) if isinstance(u, Mapping)]
        answers = [
            e["payload"]
            for e in events
            if str(e.get("kind")) == "answer_result" and isinstance(e.get("payload"), Mapping)
        ]
        answer_text = ""
        if answers and isinstance(answers[-1].get("text"), str):
            answer_text = answers[-1]["text"]
        plan_payload: Mapping[str, Any] = {}
        for e in events:
            if str(e.get("kind")) == "plan_observed" and isinstance(e.get("payload"), Mapping):
                plan_payload = e["payload"]
        terms = [str(t) for t in (plan_payload.get("terms") or ()) if str(t)]
        term_blob = scorers_mod.normalize_text("\n".join(terms))
        filters = dict(plan_payload.get("filters") or {})
        filter_blob = scorers_mod.normalize_text(
            "\n".join(str(v) for v in filters.values() if isinstance(v, str))
        )

        def unit_blob(block: str) -> str:
            parts: list[str] = []
            for unit in units:
                if block == "text" and isinstance(unit.get("text"), str):
                    parts.append(unit["text"])
                if block == "raw":
                    for key in ("raw_fields", "date_fields"):
                        row = unit.get(key)
                        if isinstance(row, Mapping):
                            parts.extend(
                                str(v) for v in row.values() if isinstance(v, (str, int, float))
                            )
            return scorers_mod.normalize_text("\n".join(parts))

        text_blob = unit_blob("text")
        raw_blob = unit_blob("raw")
        ans_blob = scorers_mod.normalize_text(answer_text)
        lines.append("=" * 68)
        lines.append(f"CASE {case_id} targets={len(targets)} units={len(units)}")
        for t_index, target in enumerate(targets):
            values = [str(v) for v in dict(target.get("filters") or {}).values() if isinstance(v, str)]
            raw_key_value = value_of(str(target.get("entity_key") or ""))
            probe_values = list(dict.fromkeys(values + ([raw_key_value] if raw_key_value else [])))
            hit = {
                "in_plan_terms": any(
                    scorers_mod.normalize_text(v) in term_blob for v in probe_values if v
                ),
                "in_plan_filters": any(
                    scorers_mod.normalize_text(v) in filter_blob for v in probe_values if v
                ),
                "in_served_unit_text": any(
                    scorers_mod.normalize_text(v) in text_blob for v in probe_values if v
                ),
                "in_served_unit_raw": any(
                    scorers_mod.normalize_text(v) in raw_blob for v in probe_values if v
                ),
                "in_answer_text": any(
                    scorers_mod.normalize_text(v) in ans_blob for v in probe_values if v
                ),
            }
            lines.append(
                f"  target[{t_index}] entity_type={target.get('entity_type')} "
                f"probe_values={len(probe_values)} {hit}"
            )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} lines={len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
