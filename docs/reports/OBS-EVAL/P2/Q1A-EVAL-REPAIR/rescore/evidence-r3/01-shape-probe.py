"""R3 shape probe over all 36 old-evidence turns.

PRIVACY: aggregate counts and coarse shapes only. No document names, unit keys,
record keys, question text, answers or target values are printed.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
OLD_RUN = Path(r"D:\mktkb-p2-t207-h2-20261114")
for path in (REPO / "backend" / "src", REPO / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: E402
from mktkb.evaluation.p2_evidence_rescore import _used_layers  # noqa: E402

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
HEX_RE = re.compile(r"[0-9a-fA-F]{16,}")


def main() -> int:
    scenario = json.loads((REPO / "docs/evaluation/p2-h2-scenarios-v0_2.json").read_bytes())
    ingest = json.loads((REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json").read_bytes())
    source_map = json.loads((REPO / "docs/evaluation/p2-holdout-v2.source-map.json").read_bytes())
    base_codes = {row["base_doc_code"] for row in source_map["sources"].values()}
    file_codes = {
        Path(row["path"].replace("\\", "/")).name.split("_", 1)[0]
        for row in ingest["sources"]
    }
    product_names = {
        (row.get("name") or Path(row["path"].replace("\\", "/")).name)
        for row in ingest["sources"]
    }
    scenario_rows = {row["scenario_id"]: row for row in scenario["scenarios"]}

    out: dict = {
        "runs": {},
        "totals": {
            "turns": 0,
            "units": 0,
            "unit_key_present": 0,
            "unit_key_shape": Counter(),
            "unit_key_prefix_in_base_codes": 0,
            "unit_key_prefix_in_file_codes": 0,
            "document_name_present": 0,
            "document_name_in_product_names": 0,
            "document_name_prefix_in_file_codes": 0,
            "document_name_prefix_in_base_codes": 0,
            "document_name_prefix_other": 0,
            "version_number_values": Counter(),
            "locator_key_sets": Counter(),
            "locator_kind_hint": Counter(),
            "entity_type_values": Counter(),
            "entity_key_shape": Counter(),
            "raw_field_key_sets": Counter(),
            "date_fields_empty": 0,
            "date_fields_nonempty": 0,
            "published_at_present": 0,
            "version_state_values": Counter(),
            "active_values": Counter(),
            "document_id_present": 0,
            "version_id_present": 0,
            "message_source_doc_version_present": 0,
            "plan_as_of_present": 0,
            "rag_business_date_present": 0,
            "completeness_complete": 0,
            "completeness_other": 0,
            "unit_ids_in_projection": 0,
            "unit_ids_not_in_projection": 0,
            "used_layer_refs": 0,
        },
        "scenario_shapes": {},
    }

    for index in range(4):
        run = OLD_RUN / "runs" / f"r{index}"
        plan = json.loads((run / "out" / "controlled" / "case-plan.json").read_bytes())
        ev_key = (run / "ev.key").read_bytes()
        ev_dir = next(p for p in (run / "evidence").iterdir() if p.is_dir())
        run_counts = Counter()
        for case in plan.get("cases") or []:
            scenario_id = case.get("scenario_id")
            for turn in case.get("turns") or []:
                if turn.get("status") != "executed":
                    continue
                env = read_encrypted_evidence(ev_dir / turn["evidence_file"], key=ev_key)
                projection = env.get("db_projection") or {}
                units = projection.get("units") or []
                rows = {str(u.get("unit_id")): u for u in units if isinstance(u, dict)}
                events = (env.get("capture") or {}).get("events") or []
                used_ids = set(_used_layers(events))
                out["totals"]["used_layer_refs"] = out["totals"].get("used_layer_refs", 0) + len(used_ids)
                for uid in used_ids:
                    row = rows.get(uid)
                    if row is None:
                        out["totals"]["unit_ids_not_in_projection"] += 1
                        continue
                    out["totals"]["unit_ids_in_projection"] += 1
                    out["totals"]["units"] += 1
                    document_name = row.get("document_name")
                    if isinstance(document_name, str) and document_name.strip():
                        out["totals"]["document_name_present"] += 1
                        if document_name in product_names:
                            out["totals"]["document_name_in_product_names"] += 1
                        prefix = document_name.split("_", 1)[0]
                        if prefix in file_codes:
                            out["totals"]["document_name_prefix_in_file_codes"] += 1
                        elif prefix in base_codes:
                            out["totals"]["document_name_prefix_in_base_codes"] += 1
                        else:
                            out["totals"]["document_name_prefix_other"] += 1
                    unit_key = row.get("unit_key")
                    if isinstance(unit_key, str) and unit_key.strip():
                        out["totals"]["unit_key_present"] += 1
                        has_uuid = UUID_RE.search(unit_key) is not None
                        has_hex = HEX_RE.search(unit_key) is not None
                        pipes = unit_key.count("|")
                        length_bucket = "<=16" if len(unit_key) <= 16 else "17-32" if len(unit_key) <= 32 else "33-64" if len(unit_key) <= 64 else ">64"
                        out["totals"]["unit_key_shape"][
                            f"pipes={pipes}|len={length_bucket}|uuid={has_uuid}|hex={has_hex}"
                        ] += 1
                        prefix = unit_key.split("|", 1)[0].split("_", 1)[0]
                        if prefix in base_codes:
                            out["totals"]["unit_key_prefix_in_base_codes"] += 1
                        if prefix in file_codes:
                            out["totals"]["unit_key_prefix_in_file_codes"] += 1
                    version = row.get("version_number")
                    out["totals"]["version_number_values"][str(version)] += 1
                    locator = row.get("locator") or {}
                    out["totals"]["locator_key_sets"][",".join(sorted(locator))] += 1
                    out["totals"]["locator_kind_hint"][
                        "sheet,row" if isinstance(locator, dict) and locator.get("sheet") and type(locator.get("row")) is int
                        else "other"
                    ] += 1
                    out["totals"]["entity_type_values"][str(row.get("entity_type"))] += 1
                    entity_key = row.get("entity_key")
                    if isinstance(entity_key, str):
                        shape = (
                            "uuid" if UUID_RE.search(entity_key) else
                            "hex" if HEX_RE.search(entity_key) else
                            "pipes" if "|" in entity_key else
                            "plain"
                        )
                        out["totals"]["entity_key_shape"][shape] += 1
                    raw_fields = row.get("raw_fields") or {}
                    out["totals"]["raw_field_key_sets"][",".join(sorted(raw_fields))] += 1
                    date_fields = row.get("date_fields") or {}
                    if date_fields:
                        out["totals"]["date_fields_nonempty"] += 1
                    else:
                        out["totals"]["date_fields_empty"] += 1
                    if row.get("published_at") is not None:
                        out["totals"]["published_at_present"] += 1
                    out["totals"]["version_state_values"][str(row.get("version_state"))] += 1
                    out["totals"]["active_values"][str(row.get("active"))] += 1
                    if row.get("document_id") is not None:
                        out["totals"]["document_id_present"] += 1
                    if row.get("version_id") is not None:
                        out["totals"]["version_id_present"] += 1
                for source in projection.get("message_sources") or []:
                    if isinstance(source, dict) and source.get("document_id") and source.get("version_id"):
                        out["totals"]["message_source_doc_version_present"] += 1
                for event in events:
                    if isinstance(event, dict) and event.get("kind") == "plan_observed":
                        payload = event.get("payload") or {}
                        if payload.get("as_of") is not None:
                            out["totals"]["plan_as_of_present"] += 1
                if projection.get("rag_business_date") is not None:
                    out["totals"]["rag_business_date_present"] += 1
                status = (env.get("completeness") or {}).get("status")
                if status == "complete":
                    out["totals"]["completeness_complete"] += 1
                else:
                    out["totals"]["completeness_other"] += 1
                out["totals"]["turns"] += 1
                run_counts["turns"] += 1
                run_counts["units"] += len(used_ids)
        out["runs"][f"r{index}"] = dict(run_counts)

    for scenario_id, row in scenario_rows.items():
        out["scenario_shapes"][scenario_id] = {
            "source_indices": row["source_indices"],
            "ingest_batches": row.get("ingest_batches"),
            "group_sizes": dict(Counter(
                source_map["sources"].get(
                    Path(ingest["sources"][i]["path"].replace("\\", "/")).name.split("_", 1)[0],
                    {},
                ).get("base_doc_code",
                      Path(ingest["sources"][i]["path"].replace("\\", "/")).name.split("_", 1)[0])
                for i in row["source_indices"]
            )),
        }

    for key in ("unit_key_shape", "version_number_values", "locator_key_sets", "locator_kind_hint",
                "entity_type_values", "entity_key_shape", "raw_field_key_sets", "version_state_values",
                "active_values"):
        out["totals"][key] = {k: v for k, v in sorted(out["totals"][key].items())}
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
