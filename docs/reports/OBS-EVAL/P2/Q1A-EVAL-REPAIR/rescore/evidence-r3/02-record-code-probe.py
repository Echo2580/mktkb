"""R3 record-code bridge probe (private, aggregate-only output).

Checks whether old-evidence `unit_key` can be deterministically identified with a
frozen `record_code` in the dataset labels or the contract v2 refs.
No values are printed; only counts and coarse length/shape buckets.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
OLD_RUN = Path(r"D:\mktkb-p2-t207-h2-20261114")
CONTRACT_V2 = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet")
KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
for path in (REPO / "backend" / "src", REPO / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def bucket(value: str) -> str:
    n = len(value)
    return "<=8" if n <= 8 else "9-16" if n <= 16 else "17-32" if n <= 32 else "33-64" if n <= 64 else ">64"


def main() -> int:
    import p2_h2_controlled_execute as entry
    from cryptography.fernet import Fernet
    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence
    from mktkb.evaluation.p2_evidence_rescore import _used_layers

    paths = entry.InputPaths(
        holdout_manifest=Path(r"D:\mktkb-p2-holdout\v2\manifest.json"),
        annotation_ciphertext=Path(r"C:\Users\dell1712\.codex\visualizations\2026\11\12\01a1cd24-bccf-7e00-80df-0b75f57f7d1c\t207-custody\annotations-v0_2.fernet"),
        review_ciphertext=Path(r"C:\Users\dell1712\.codex\visualizations\2026\11\12\01a1cd24-bccf-7e00-80df-0b75f57f7d1c\t207-custody\review-v0_2.fernet"),
        scenario_key_file=Path(r"D:\mktkb-p2-holdout\keys\v2.key"),
        addendum_ciphertext=Path(r"C:\Users\dell1712\.codex\visualizations\2026\11\12\01a1cd24-bccf-7e00-80df-0b75f57f7d1c\t207-custody\annotations-gapaddendum-v0_3.fernet"),
        scenario_contract=entry.DEFAULT_SCENARIO_CONTRACT,
        ingest_plan=entry.DEFAULT_INGEST_PLAN,
        source_map=entry.DEFAULT_SOURCE_MAP,
        annotation_schema=entry.DEFAULT_ANNOTATION_SCHEMA,
        manager_acceptance_v2=entry.DEFAULT_MANAGER_V2,
        review_aggregate_v2=entry.DEFAULT_REVIEW_AGGREGATE_V2,
        addendum_acceptance_v3=entry.DEFAULT_ADDENDUM_ACCEPTANCE,
    )
    runtime = entry.RuntimeOptions(
        holdout_root=Path(r"D:\mktkb-p2-holdout\v2"),
        holdout_key_file=KEY,
        project_total_limit_cny=entry.PROJECT_TOTAL_LIMIT_CNY,
    )
    bundle = entry.load_private_bundle({}, paths, runtime=runtime)

    dataset_refs: list[dict] = []
    for case in bundle.dataset.cases:
        for collection in ("expected_sources", "relevant_units", "forbidden_sources"):
            for ref in getattr(case, collection):
                dataset_refs.append({"collection": collection, "ref": dict(ref)})

    contract = json.loads(Fernet(KEY.read_bytes()).decrypt(CONTRACT_V2.read_bytes()).decode("utf-8"))
    contract_refs: list[dict] = []
    for case in contract["cases"]:
        for axis, row in case["axes"].items():
            for ref in row.get("target_refs") or []:
                contract_refs.append({"axis": axis, "ref": dict(ref)})

    out: dict = {
        "dataset": {
            "cases": len(bundle.dataset.cases),
            "refs": len(dataset_refs),
            "by_collection": dict(Counter(row["collection"] for row in dataset_refs)),
            "ref_keys": dict(Counter(",".join(sorted(row["ref"])) for row in dataset_refs)),
            "record_code_present": sum(1 for row in dataset_refs if row["ref"].get("record_code")),
            "record_code_buckets": dict(Counter(bucket(str(row["ref"].get("record_code"))) for row in dataset_refs if row["ref"].get("record_code"))),
            "unit_key_present": sum(1 for row in dataset_refs if row["ref"].get("unit_key")),
            "unit_key_buckets": dict(Counter(bucket(str(row["ref"].get("unit_key"))) for row in dataset_refs if row["ref"].get("unit_key"))),
        },
        "contract_v2": {
            "case_top_keys": sorted({tuple(sorted(case)) for case in contract["cases"]}),
            "axis_row_keys": sorted({tuple(sorted(row)) for case in contract["cases"] for row in case["axes"].values()}),
            "target_refs": len(contract_refs),
            "by_axis": dict(Counter(row["axis"] for row in contract_refs)),
            "ref_keys": dict(Counter(",".join(sorted(row["ref"])) for row in contract_refs)),
        },
        "unit_keys": {
            "units": 0,
            "buckets": Counter(),
            "matches_dataset_record_code": 0,
            "matches_dataset_unit_key": 0,
            "matches_contract_ref_value": 0,
            "matches_dataset_record_code_anywhere": 0,
            "matches_contract_ref_anywhere": 0,
            "unique_units": 0,
        },
    }

    dataset_values = {
        str(row["ref"][key])
        for row in dataset_refs
        for key in ("record_code", "unit_key")
        if row["ref"].get(key)
    }
    dataset_record_codes = {
        str(row["ref"]["record_code"]) for row in dataset_refs if row["ref"].get("record_code")
    }
    dataset_unit_keys = {
        str(row["ref"]["unit_key"]) for row in dataset_refs if row["ref"].get("unit_key")
    }
    contract_values: set[str] = set()
    for case in contract["cases"]:
        for axis, row in case["axes"].items():
            for key in ("target_refs", "targets"):
                for item in row.get(key) or []:
                    if isinstance(item, dict):
                        for value in item.values():
                            if isinstance(value, str):
                                contract_values.add(value)

    seen: set[str] = set()
    for index in range(4):
        run = OLD_RUN / "runs" / f"r{index}"
        plan = json.loads((run / "out" / "controlled" / "case-plan.json").read_bytes())
        ev_key = (run / "ev.key").read_bytes()
        ev_dir = next(p for p in (run / "evidence").iterdir() if p.is_dir())
        for case in plan.get("cases") or []:
            for turn in case.get("turns") or []:
                if turn.get("status") != "executed":
                    continue
                env = read_encrypted_evidence(ev_dir / turn["evidence_file"], key=ev_key)
                projection = env.get("db_projection") or {}
                rows = {str(u.get("unit_id")): u for u in projection.get("units") or [] if isinstance(u, dict)}
                for uid in _used_layers((env.get("capture") or {}).get("events") or []):
                    row = rows.get(uid)
                    if row is None:
                        continue
                    out["unit_keys"]["units"] += 1
                    unit_key = row.get("unit_key")
                    if not isinstance(unit_key, str):
                        continue
                    out["unit_keys"]["buckets"][bucket(unit_key)] += 1
                    if unit_key not in seen:
                        seen.add(unit_key)
                        out["unit_keys"]["unique_units"] += 1
                    if unit_key in dataset_record_codes:
                        out["unit_keys"]["matches_dataset_record_code"] += 1
                    if unit_key in dataset_unit_keys:
                        out["unit_keys"]["matches_dataset_unit_key"] += 1
                    if unit_key in contract_values:
                        out["unit_keys"]["matches_contract_ref_value"] += 1
                    if any(unit_key in value for value in dataset_values):
                        out["unit_keys"]["matches_dataset_record_code_anywhere"] += 1
                    if any(unit_key in value for value in contract_values):
                        out["unit_keys"]["matches_contract_ref_anywhere"] += 1

    out["unit_keys"]["buckets"] = dict(out["unit_keys"]["buckets"])
    out["unit_keys"]["dataset_value_count"] = len(dataset_values)
    out["unit_keys"]["contract_value_count"] = len(contract_values)
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
