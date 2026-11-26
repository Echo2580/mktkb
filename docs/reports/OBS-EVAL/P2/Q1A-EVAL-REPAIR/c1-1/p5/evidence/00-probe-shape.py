"""C1-P5 probe 00: shape census of the frozen contract v2 + old v0.2 evidence (aggregate only).

Reads private artifacts in-process only. Prints **no** question text, answers, target values,
entity keys, record keys, doc codes, ids or dates. Only counts, fixed codes and key names.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
OUT = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p5/evidence"
CUSTODY = Path(
    r"C:/Users/dell1712/.codex/visualizations/2026/11/12/01a1cd24-bccf-7e00-80df-0b75f57f7d1c/t207-custody"
)
CONTRACT = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet")
OLD_RUN = Path(r"D:\mktkb-p2-t207-h2-20261114")

sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["MKTKB_NO_DOTENV"] = "1"
os.environ["MKTKB_P2_HOLDOUT_ROOT"] = r"D:/mktkb-p2-holdout/v2"
os.environ["MKTKB_P2_HOLDOUT_KEY_FILE"] = r"D:/mktkb-p2-holdout/keys/v2.key"

from cryptography.fernet import Fernet  # noqa: E402

import p2_h2_controlled_execute as ce  # noqa: E402
from mktkb.evaluation import p2_dataset, p2_evidence_io  # noqa: E402

PATHS = ce.InputPaths(
    holdout_manifest=Path(r"D:/mktkb-p2-holdout/v2/manifest.json"),
    annotation_ciphertext=CUSTODY / "annotations-v0_2.fernet",
    review_ciphertext=CUSTODY / "review-v0_2.fernet",
    scenario_key_file=Path(r"D:/mktkb-p2-holdout/keys/v2.key"),
    addendum_ciphertext=CUSTODY / "annotations-gapaddendum-v0_3.fernet",
    scenario_contract=ROOT / "docs/evaluation/p2-h2-scenarios-v0_2.json",
    ingest_plan=ROOT / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json",
    source_map=ROOT / "docs/evaluation/p2-holdout-v2.source-map.json",
    annotation_schema=ROOT / "docs/evaluation/p2-h2-custody-annotations-v0_2.md",
    manager_acceptance_v2=ROOT / "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/manager-acceptance.json",
    review_aggregate_v2=ROOT / "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/review-aggregate.json",
    addendum_acceptance_v3=ROOT / "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V3/manager-acceptance.json",
)
RUNTIME = ce.RuntimeOptions(
    holdout_root=Path(r"D:/mktkb-p2-holdout/v2"),
    holdout_key_file=Path(r"D:/mktkb-p2-holdout/keys/v2.key"),
    project_total_limit_cny=ce.PROJECT_TOTAL_LIMIT_CNY,
)

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
LONG_HEX_RE = re.compile(r"[0-9a-fA-F]{16,}")
ID_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*\|id:", re.IGNORECASE)


def key_space(entity_type, entity_key) -> str:
    if not entity_type or not entity_key:
        return "absent"
    if entity_type == "document" or entity_key.startswith("document|"):
        return "document"
    if UUID_RE.search(entity_key) or LONG_HEX_RE.search(entity_key):
        return "document"
    if ID_KEY_RE.match(entity_key):
        return "id_key"
    return "corpus_name_or_opaque"


def main() -> int:
    key = p2_dataset._read_key(Path(r"D:/mktkb-p2-holdout/keys/v2.key"))
    bundle = ce.load_private_bundle({}, PATHS, runtime=RUNTIME)

    report: dict = {"probe": "00-shape"}

    # ---- contract v2 (in-process only) --------------------------------------
    raw = CONTRACT.read_bytes()
    import hashlib

    contract = json.loads(Fernet(key).decrypt(raw).decode("utf-8"))
    case_turn_hist: Counter = Counter()
    turn_total = 0
    for case in bundle.dataset.cases:
        n = len(ce.case_questions(case))
        case_turn_hist[n] += 1
        turn_total += n
    report["contract"] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "schema_version": contract.get("schema_version"),
        "top_keys": sorted(contract),
        "case_count": contract.get("case_count"),
        "run_scenarios": sorted({str(r.get("scenario_id")) for r in contract.get("runs") or ()}),
        "projection_keys": sorted((contract.get("projection") or {})),
        "target_count": sum(
            len(axis.get("targets") or ())
            for case in contract.get("cases") or ()
            for axis in (case.get("axes") or {}).values()
        ),
    }
    report["dataset"] = {
        "cases": len(bundle.dataset.cases),
        "turns": turn_total,
        "case_turn_histogram": {str(k): v for k, v in sorted(case_turn_hist.items())},
        "business_date_present": bool(getattr(bundle.dataset.manifest, "business_date", None)),
    }

    # ---- old evidence census -------------------------------------------------
    runs = []
    for run_dir in sorted(OLD_RUN.glob("runs/r*")):
        ev_key = (run_dir / "ev.key").read_bytes()
        plan_path = run_dir / "out/controlled/case-plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        files = sorted((run_dir / "evidence").glob("*/*.fernet"))
        schema_versions: Counter = Counter()
        top_keys: Counter = Counter()
        event_kinds: Counter = Counter()
        unit_total = 0
        units_with_record_code = 0
        entity_type_counts: Counter = Counter()
        space_counts: Counter = Counter()
        filter_key_names: Counter = Counter()
        used_refs = 0
        unresolved_refs = 0
        turn_refs: list = []
        completeness: Counter = Counter()
        has_runtime_snapshot = 0
        plan_observed_as_of = 0
        for path in files:
            payload = p2_evidence_io.read_encrypted_evidence(path, key=ev_key)
            schema_versions[str(payload.get("schema_version"))] += 1
            for k in payload:
                top_keys[k] += 1
            completeness[str((payload.get("completeness") or {}).get("status"))] += 1
            if "runtime_snapshot" in payload:
                has_runtime_snapshot += 1
            if isinstance(payload.get("run_binding"), dict):
                turn_refs.append(1)
            capture = payload.get("capture") or {}
            events = list(capture.get("events") or ())
            for event in events:
                event_kinds[str(event.get("kind"))] += 1
            proj = payload.get("db_projection") or {}
            for unit in proj.get("units") or ():
                unit_total += 1
                if "record_code" in unit:
                    units_with_record_code += 1
                et = unit.get("entity_type")
                entity_type_counts[str(et)] += 1
                space_counts[key_space(et, unit.get("entity_key"))] += 1
                for name in (unit.get("entity_filters") or {}):
                    filter_key_names[str(name)] += 1
            # use-layer refs (v0.3 semantics) as a sanity count
            refs = set()
            for event in events:
                kind = str(event.get("kind"))
                pl = event.get("payload") or {}
                if kind == "model_input":
                    for row in pl.get("evidence") or ():
                        if isinstance(row, dict) and row.get("source_id"):
                            refs.add(str(row["source_id"]))
                if kind == "model_output":
                    for sid in pl.get("source_ids") or ():
                        refs.add(str(sid))
                if kind == "direct_rag_answer":
                    for row in pl.get("facts") or ():
                        if isinstance(row, dict) and row.get("source_unit_id"):
                            refs.add(str(row["source_unit_id"]))
                    for sid in pl.get("cited_unit_ids") or ():
                        refs.add(str(sid))
                if kind in ("answer_result", "commit_observed"):
                    for sid in pl.get("source_ids") or ():
                        refs.add(str(sid))
                if kind == "entity_inheritance" and pl.get("source_unit_id"):
                    refs.add(str(pl["source_unit_id"]))
            for row in proj.get("message_sources") or ():
                if isinstance(row, dict) and row.get("source_id"):
                    refs.add(str(row["source_id"]))
            used_refs += len(refs)
            unresolved_refs += len(proj.get("unresolved_unit_ids") or ())
            if any(str(e.get("kind")) == "plan_observed" for e in events):
                plan_observed_as_of += 1
        runs.append(
            {
                "run": run_dir.name,
                "turn_files": len(files),
                "case_plan_cases": len(plan.get("cases") or ()),
                "schema_versions": dict(schema_versions),
                "completeness": dict(completeness),
                "top_key_names": {k: v for k, v in sorted(top_keys.items())},
                "has_runtime_snapshot": has_runtime_snapshot,
                "has_run_binding": len(turn_refs),
                "event_kinds": {k: v for k, v in sorted(event_kinds.items())},
                "unit_rows": unit_total,
                "units_with_record_code_field": units_with_record_code,
                "entity_type_counts": {k: v for k, v in sorted(entity_type_counts.items())},
                "entity_key_space_counts": {k: v for k, v in sorted(space_counts.items())},
                "entity_filter_key_names": {k: v for k, v in sorted(filter_key_names.items())},
                "used_refs": used_refs,
                "unresolved_refs": unresolved_refs,
                "turns_with_plan_observed": plan_observed_as_of,
            }
        )
    report["old_evidence"] = {"runs": runs}
    report["v03_field_presence"] = {
        "request_owner_block": sum(1 for r in runs if "request_owner" in r["top_key_names"]),
        "effective_temporal_block": sum(1 for r in runs if "effective_temporal" in r["top_key_names"]),
        "units_with_record_code_field": sum(r["units_with_record_code_field"] for r in runs),
        "plan_observed_present_turns": sum(r["turns_with_plan_observed"] for r in runs),
        "turns_total": sum(r["turn_files"] for r in runs),
    }

    out_path = OUT / "00-probe-shape.out.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
