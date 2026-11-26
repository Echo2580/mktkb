"""C1-P5 privacy scan: prove no question text / answer / target value / key leaked into
the p5 deliverables. Reports counts and file names only; never echoes a sensitive needle.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
P5 = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p5"
CUSTODY = Path(
    r"C:/Users/dell1712/.codex/visualizations/2026/11/12/01a1cd24-bccf-7e00-80df-0b75f57f7d1c/t207-custody"
)
CONTRACT = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet")
OLD_RUN = Path(r"D:\mktkb-p2-t207-h2-20261114")

sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["MKTKB_NO_DOTENV"] = "1"
os.environ["MKTKB_P2_HOLDOUT_ROOT"] = "D:/mktkb-p2-holdout/v2"
os.environ["MKTKB_P2_HOLDOUT_KEY_FILE"] = "D:/mktkb-p2-holdout/keys/v2.key"

from cryptography.fernet import Fernet  # noqa: E402

import p2_h2_controlled_execute as ce  # noqa: E402
from mktkb.evaluation import p2_dataset  # noqa: E402

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
    holdout_root=Path("D:/mktkb-p2-holdout/v2"),
    holdout_key_file=Path("D:/mktkb-p2-holdout/keys/v2.key"),
    project_total_limit_cny=ce.PROJECT_TOTAL_LIMIT_CNY,
)


def shingles(text: str, size: int) -> set:
    clean = re.sub(r"\s+", "", str(text or ""))
    if len(clean) < size:
        return {clean} if len(clean) >= 6 else set()
    return {clean[i : i + size] for i in range(0, len(clean) - size + 1)}


def main() -> int:
    key = p2_dataset._read_key(Path("D:/mktkb-p2-holdout/keys/v2.key"))
    bundle = ce.load_private_bundle({}, PATHS, runtime=RUNTIME)
    contract = json.loads(Fernet(key).decrypt(CONTRACT.read_bytes()).decode("utf-8"))

    needles: dict[str, set] = {
        "case_id": set(),
        "question": set(),
        "reference_answer": set(),
        "expected_value": set(),
        "forbidden_value": set(),
        "target_entity_key": set(),
        "target_filter_value": set(),
        "record_key": set(),
        "key_material": set(),
    }
    for case in bundle.dataset.cases:
        needles["case_id"].add(str(case.case_id))
        needles["question"].add(str(case.question))
        needles["question"] |= shingles(case.question, 10)
        needles["reference_answer"].add(str(case.reference_answer))
        needles["reference_answer"] |= shingles(case.reference_answer, 12)
        for value in case.expected_values:
            needles["expected_value"].add(str(value))
        for value in case.forbidden_values:
            needles["forbidden_value"].add(str(value))
        for turn in case.turns:
            for field in ("question", "prompt", "text"):
                if isinstance(turn.get(field), str):
                    needles["question"].add(turn[field])
                    needles["question"] |= shingles(turn[field], 10)
    for case in contract["cases"]:
        for axis in case["axes"].values():
            for target in axis.get("targets") or ():
                value = str(target.get("entity_key") or "")
                if len(value) >= 4:
                    needles["target_entity_key"].add(value)
                for item in (target.get("filters") or {}).values():
                    text = str(item)
                    if len(text) >= 4:
                        needles["target_filter_value"].add(text)
    manifest = json.loads((ROOT / "fixtures/acceptance/manifest.json").read_text(encoding="utf-8"))
    for record_key in manifest.get("records") or ():
        if len(str(record_key)) >= 4:
            needles["record_key"].add(str(record_key))
    needles["key_material"].add(key.decode("utf-8", "ignore") if isinstance(key, bytes) else str(key))
    for key_path in sorted(OLD_RUN.glob("runs/r*/ev.key")):
        needles["key_material"].add(key_path.read_text(encoding="utf-8", errors="ignore").strip())
    needles = {name: {v for v in values if v and len(v) >= 4} for name, values in needles.items()}

    files = sorted(path for path in P5.rglob("*") if path.is_file() and path.name != "05-privacy-scan.out.json")
    hits: dict[str, list] = {}
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(P5).as_posix()
        for category, values in needles.items():
            matched = sum(1 for value in values if value in text)
            if matched:
                hits.setdefault(rel, {})[category] = matched
    embedded_key_pattern = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}=(?![A-Za-z0-9_-])")
    key_pattern_files = [path.relative_to(P5).as_posix() for path in files
                         if embedded_key_pattern.search(path.read_text(encoding="utf-8", errors="ignore"))]

    report = {
        "probe": "05-privacy-scan",
        "files_scanned": len(files),
        "needle_counts": {name: len(values) for name, values in sorted(needles.items())},
        "hits": hits,
        "embedded_fernet_key_pattern_files": key_pattern_files,
        "clean": not hits and not key_pattern_files,
    }
    (P5 / "evidence" / "05-privacy-scan.out.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(
        {k: report[k] for k in ("files_scanned", "needle_counts", "hits",
                                "embedded_fernet_key_pattern_files", "clean")},
        ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
