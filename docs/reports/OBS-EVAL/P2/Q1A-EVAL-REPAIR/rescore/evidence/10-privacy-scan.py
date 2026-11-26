"""公开产物隐私自查：用冻结 H2 题面/答案/目标值/题号做 needles，扫描公开文件。

needles 只在进程内存构造，命中只报「文件 + 数量」，绝不打印 needle 本身。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(REPO / "backend" / "src"))
sys.path.insert(0, str(REPO / "tools"))
HOLDOUT_ROOT = Path(r"D:\mktkb-p2-holdout\v2")
HOLDOUT_KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
CUSTODY = Path(
    r"C:\Users\dell1712\.codex\visualizations\2026\11\12\01a1cd24-bccf-7e00-80df-0b75f57f7d1c\t207-custody"
)
PUBLIC_DIRS = [REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore"]
SKIP_SUFFIX = (".fernet",)


def main() -> int:
    import p2_h2_controlled_execute as entry

    bundle = entry.load_private_bundle(
        {},
        entry.InputPaths(
            holdout_manifest=HOLDOUT_ROOT / "manifest.json",
            annotation_ciphertext=CUSTODY / "annotations-v0_2.fernet",
            review_ciphertext=CUSTODY / "review-v0_2.fernet",
            scenario_key_file=HOLDOUT_KEY,
            addendum_ciphertext=CUSTODY / "annotations-gapaddendum-v0_3.fernet",
            scenario_contract=entry.DEFAULT_SCENARIO_CONTRACT,
            ingest_plan=entry.DEFAULT_INGEST_PLAN,
            source_map=entry.DEFAULT_SOURCE_MAP,
            annotation_schema=entry.DEFAULT_ANNOTATION_SCHEMA,
            manager_acceptance_v2=entry.DEFAULT_MANAGER_V2,
            review_aggregate_v2=entry.DEFAULT_REVIEW_AGGREGATE_V2,
            addendum_acceptance_v3=entry.DEFAULT_ADDENDUM_ACCEPTANCE,
        ),
        runtime=entry.RuntimeOptions(
            holdout_root=HOLDOUT_ROOT,
            holdout_key_file=HOLDOUT_KEY,
            project_total_limit_cny=entry.PROJECT_TOTAL_LIMIT_CNY,
        ),
    )

    needles: set[str] = set()
    for case in bundle.dataset.cases:
        needles.add(str(case.case_id))
        for text in (case.question, case.reference_answer):
            if isinstance(text, str) and len(text) >= 8:
                needles.add(text.strip())
        for value in list(case.expected_values) + list(case.forbidden_values):
            if isinstance(value, str) and len(value) >= 4:
                needles.add(value.strip())
        for ref in list(case.expected_sources) + list(case.forbidden_sources) + list(case.relevant_units):
            if isinstance(ref, dict):
                for key in ("record_code",):
                    if isinstance(ref.get(key), str) and len(ref[key]) >= 3:
                        needles.add(ref[key])
        for target in getattr(case, "turns", ()) or ():
            if isinstance(target, dict):
                question = target.get("question")
                if isinstance(question, str) and len(question) >= 8:
                    needles.add(question.strip())
    # 目标身份（合同 targets 的 entity_key）
    for case in bundle.annotation["cases"]:
        for axis in case["axes"].values():
            for target in axis.get("targets") or ():
                key = target.get("entity_key")
                if isinstance(key, str) and len(key) >= 3:
                    needles.add(key)

    needles.discard("")
    results = []
    total_hits = 0
    for root in PUBLIC_DIRS:
        for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.name.endswith(SKIP_SUFFIX)):
            text = path.read_text(encoding="utf-8", errors="replace")
            hits = sum(1 for needle in needles if needle in text)
            total_hits += hits
            results.append({"file": path.name, "hits": hits})
    print(
        json.dumps(
            {
                "schema_version": "q1a3-privacy-scan/v0.1",
                "needles": len(needles),
                "files_scanned": len(results),
                "total_hits": total_hits,
                "per_file": results,
                "verdict": "clean" if total_hits == 0 else "hits_present",
                "calls": {"network": 0, "socket": 0, "dns": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if total_hits == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
