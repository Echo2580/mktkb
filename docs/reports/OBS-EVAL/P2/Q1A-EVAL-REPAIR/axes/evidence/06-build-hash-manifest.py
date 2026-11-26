"""Q1a-1b 新文件 hash 清单生成器（只读、零网络、零真实数据）。

用法（仓库根）：
  .venv/Scripts/python.exe \
      docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/06-build-hash-manifest.py \
      docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/06-hash-manifest.json
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
AXES_DIR = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes"
OUTPUT_NAME = "06-hash-manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: 06-build-hash-manifest.py <output.json>", file=sys.stderr)
        return 2
    output = Path(sys.argv[1])
    files: list[dict[str, object]] = []

    def add(path: Path, role: str) -> None:
        files.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "role": role,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )

    add(
        ROOT / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py",
        "new evaluator module (three axes + Q1a-2 adapter)",
    )
    add(
        ROOT / "backend/tests/evaluation/test_p2_evidence_rescore_axes.py",
        "synthetic tests",
    )
    add(
        ROOT / "docs/evaluation/p2-evidence-rescore-v0_2.md",
        "rescore contract v0.2",
    )
    add(AXES_DIR / "dev-report.md", "development report")
    for path in sorted((AXES_DIR / "evidence").iterdir()):
        if path.is_file() and path.name != OUTPUT_NAME:
            add(path, "axes evidence")

    before_path = AXES_DIR / "evidence/04-protected-hashes-before.json"
    after_path = AXES_DIR / "evidence/05-protected-hashes-after.json"
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    payload = {
        "schema_version": "q1a1b-hash-manifest/v1",
        "algorithm": "sha256",
        "analysis_id": "Q1A-RESCORE-20261114-r1",
        "evaluator_phase": "Q1a-1b/axes-v0.1",
        "branch": "codex/p2-e2e",
        "head": before["head"],
        "commit_or_stage_performed": False,
        "files": files,
        "protected_c_freeze": {
            "item_count": len(before["c_freeze_12"]),
            "all_match": after["all_match"],
            "mismatches": after["mismatches"],
            "p2_hard_evidence_sha256": after["p2_hard_evidence_sha256"],
            "reference": "docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/evidence/c-freeze.txt",
        },
        "protected_tracked_modified": {
            "item_count": len(before["tracked_modified_15"]),
            "all_match": after["all_match"],
        },
        "q1a1_protected": {
            "item_count": len(before["q1a1_protected"]),
            "all_match": after["all_match"],
        },
        "readonly_references": {
            "item_count": len(before["readonly_references"]),
            "all_match": after["all_match"],
        },
        "self_hash_excluded": True,
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"files": len(files), "all_match": after["all_match"]}))
    return 0 if after["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
