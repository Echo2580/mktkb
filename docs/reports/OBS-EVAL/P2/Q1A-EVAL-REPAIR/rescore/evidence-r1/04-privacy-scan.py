"""公开产物隐私自查（R1）：用冻结题面/答案/目标值/题号/实体键/记录码做 needles 扫描。

needles 只在进程内存构造；命中只报「文件 + 数量」，绝不打印 needle 本身。
扫描范围：本包三个公开产物 + evidence-r1 下的脚本/JSON（不含 .fernet）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
for path in (HERE, REPO / "backend" / "src", REPO / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import _common_r1 as C  # noqa: E402

TARGETS = [
    HERE.parent / "rescore-aggregate-r1.json",
    HERE.parent / "rescore-report-r1.md",
]
SCAN_DIRS = [HERE]
SKIP_SUFFIX = (".fernet",)


def build_needles(bundle: object) -> set[str]:
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
                record_code = ref.get("record_code")
                if isinstance(record_code, str) and len(record_code) >= 3:
                    needles.add(record_code)
        for turn in getattr(case, "turns", ()) or ():
            if isinstance(turn, dict):
                question = turn.get("question")
                if isinstance(question, str) and len(question) >= 8:
                    needles.add(question.strip())
    for row in bundle.annotation["cases"]:
        for axis in row["axes"].values():
            for target in axis.get("targets") or ():
                entity_key = target.get("entity_key")
                if isinstance(entity_key, str) and len(entity_key) >= 3:
                    needles.add(entity_key)
    needles.discard("")
    return needles


def main() -> int:
    bundle = C.load_bundle()
    needles = build_needles(bundle)
    paths: list[Path] = [path for path in TARGETS if path.is_file()]
    for directory in SCAN_DIRS:
        paths.extend(
            path
            for path in sorted(directory.rglob("*"))
            if path.is_file() and not path.name.endswith(SKIP_SUFFIX)
        )
    results = []
    total = 0
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = sum(1 for needle in needles if needle in text)
        total += hits
        results.append({"file": str(path.relative_to(HERE.parent)), "hits": hits})
    payload = {
        "schema_version": "q1a3r1-privacy-scan/v0.1",
        "needle_count": len(needles),
        "files_scanned": len(results),
        "total_hits": total,
        "per_file": results,
        "verdict": "clean" if total == 0 else "hits_present",
        "calls": {"network": 0, "socket": 0, "dns": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
    }
    (HERE / "04-privacy-scan.json").write_bytes(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    print(json.dumps({"verdict": payload["verdict"], "files": len(results), "hits": total}, ensure_ascii=True))
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
