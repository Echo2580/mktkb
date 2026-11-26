"""C1-P5 independent key-space cross-check.

Re-implements the alignment test **without** importing the P4 adapter: contract v2 role
filters + `mktkb.rag.chunking.normalize_field` (the contract-allowed normalization) vs the
old evidence's used-unit entity rows. Prints counts only; no values.
"""
from __future__ import annotations

import hashlib
import json
import os
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
from mktkb.rag import chunking  # noqa: E402

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

ROLES = ("store", "item", "product", "channel", "price_type", "identifier")
USE_EVENTS = ("model_input", "model_output", "direct_rag_answer", "answer_result",
              "commit_observed", "entity_inheritance")


def norm(value) -> str:
    return chunking.normalize_field(value)


def role_names_for(field_name: str) -> str | None:
    name = str(field_name)
    if name in ROLES:
        return name
    return chunking.field_role(name)


def target_matchable(target: dict) -> bool:
    entity_type = target.get("entity_type")
    entity_key = target.get("entity_key")
    filters = target.get("filters")
    if entity_type not in ("item", "store", "record"):
        return False
    if not isinstance(entity_key, str) or not entity_key:
        return False
    if not isinstance(filters, dict):
        return False
    return all(role_names_for(key) == key for key in filters)


def canonical(entity_type: str, filters: dict) -> str | None:
    if entity_type == "item":
        store, item = filters.get("store"), filters.get("item")
        if isinstance(store, str) and isinstance(item, str):
            return f"item|{norm(store)}|{norm(item)}"
        return None
    if entity_type == "store":
        store = filters.get("store")
        return f"store|{norm(store)}" if isinstance(store, str) else None
    if entity_type == "record":
        identifier = filters.get("identifier")
        return f"record|{norm(identifier)}" if isinstance(identifier, str) else None
    return None


def used_refs(events: list) -> set:
    refs: set = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind"))
        payload = event.get("payload") or {}
        if kind not in USE_EVENTS or not isinstance(payload, dict):
            continue
        if kind == "model_input":
            for row in payload.get("evidence") or ():
                if isinstance(row, dict) and isinstance(row.get("source_id"), str):
                    refs.add(row["source_id"])
        elif kind == "model_output":
            refs.update(str(v) for v in payload.get("source_ids") or () if isinstance(v, str))
        elif kind == "direct_rag_answer":
            for row in payload.get("facts") or ():
                if isinstance(row, dict) and isinstance(row.get("source_unit_id"), str):
                    refs.add(row["source_unit_id"])
            refs.update(str(v) for v in payload.get("cited_unit_ids") or () if isinstance(v, str))
        elif kind in ("answer_result", "commit_observed"):
            refs.update(str(v) for v in payload.get("source_ids") or () if isinstance(v, str))
        elif kind == "entity_inheritance":
            value = payload.get("source_unit_id")
            if isinstance(value, str):
                refs.add(value)
    return refs


def main() -> int:
    key = p2_dataset._read_key(Path(r"D:/mktkb-p2-holdout/keys/v2.key"))
    bundle = ce.load_private_bundle({}, PATHS, runtime=RUNTIME)
    contract = json.loads(Fernet(key).decrypt(CONTRACT.read_bytes()).decode("utf-8"))
    case_index = {str(c["case_id"]): int(c["case_index"]) for c in contract["cases"]}

    # used unit rows per case, straight from the old envelopes
    case_rows: dict[str, dict] = {}
    for run_dir in sorted(OLD_RUN.glob("runs/r*")):
        ev_key = (run_dir / "ev.key").read_bytes()
        plan = json.loads((run_dir / "out/controlled/case-plan.json").read_text(encoding="utf-8"))
        for case in plan.get("cases") or ():
            rows = case_rows.setdefault(str(case["case_id"]), {})
            for turn in case.get("turns") or ():
                if turn.get("status") != "executed" or not turn.get("evidence_file"):
                    continue
                name = Path(str(turn["evidence_file"])).name
                matches = sorted((run_dir / "evidence").glob(f"*/{name}"))
                envelope = p2_evidence_io.read_encrypted_evidence(matches[0], key=ev_key)
                events = list((envelope.get("capture") or {}).get("events") or ())
                by_id = {
                    str(unit.get("unit_id")): unit
                    for unit in (envelope.get("db_projection") or {}).get("units") or ()
                    if isinstance(unit, dict)
                }
                for ref in used_refs(events):
                    unit = by_id.get(ref)
                    if unit is None:
                        rows.setdefault(ref, None)
                        continue
                    rows.setdefault(ref, unit)

    results = []
    counts: Counter = Counter()
    used_total = 0
    for case in contract["cases"]:
        axis = case["axes"]["cross_entity"]
        targets = [t for t in axis["targets"] if target_matchable(t)]
        rows = case_rows.get(str(case["case_id"]), {})
        used_total += len(rows)
        classes: Counter = Counter()
        for ref, unit in rows.items():
            if unit is None or not unit.get("entity_type") or not unit.get("entity_key"):
                classes["absent"] += 1
                continue
            entity_type = str(unit["entity_type"])
            entity_key = str(unit["entity_key"])
            filters = {str(k): str(v) for k, v in (unit.get("entity_filters") or {}).items()}
            if entity_type == "document":
                classes["document"] += 1
                continue
            hit = False
            same_type = [t for t in targets if t["entity_type"] == entity_type]
            for target in same_type:
                if target["entity_key"] == entity_key and all(
                    filters.get(k) == v for k, v in target["filters"].items()
                ):
                    hit = True
                    break
            if not hit:
                key_value = canonical(entity_type, filters)
                for target in same_type:
                    if key_value is not None and key_value == target["entity_key"] and all(
                        filters.get(k) == v for k, v in target["filters"].items()
                    ):
                        hit = True
                        break
            classes["matched" if hit else "unmatched"] += 1
        if targets:
            if not rows:
                verdict = "missing_v03_field"
            elif classes["unmatched"]:
                verdict = "entity_key_space_incompatible"
            elif classes["absent"] or classes["document"]:
                verdict = "other_fixed_code"
            else:
                verdict = "aligned"
            counts[verdict] += 1
            results.append(
                {
                    "label": f"AX{int(case['case_index']) + 1:02d}",
                    "matchable_targets": len(targets),
                    "target_entity_types": sorted({t["entity_type"] for t in targets}),
                    "used_rows": len(rows),
                    "classes": dict(sorted(classes.items())),
                    "verdict": verdict,
                }
            )
    report = {
        "probe": "02-independent-keycheck",
        "contract_sha256": hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
        "used_rows_total": used_total,
        "matchable_axes": len(results),
        "counts": dict(sorted(counts.items())),
        "axes": results,
    }
    (OUT / "02-independent-keycheck.out.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
