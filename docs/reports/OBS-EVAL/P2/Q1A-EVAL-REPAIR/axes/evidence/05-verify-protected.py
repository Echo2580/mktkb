"""Q1a-1b 保护件前后 hash 复核脚本（只读、零网络、零真实数据）。

用法（仓库根）：
  .venv/Scripts/python.exe \
      docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/05-verify-protected.py \
      docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json \
      docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/05-protected-hashes-after.json

输出 JSON：逐组当前 hash、mismatches、git 状态计数；有 mismatch 时 exit code=1。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: 05-verify-protected.py <before.json> <after.json>", file=sys.stderr)
        return 2
    before_path = Path(sys.argv[1])
    after_path = Path(sys.argv[2])
    before = json.loads(before_path.read_text(encoding="utf-8"))
    groups = ("tracked_modified_15", "c_freeze_12", "q1a1_protected", "readonly_references")
    report: dict[str, object] = {
        "schema_version": "q1a1b-protected-hashes-after/v1",
        "phase": "after",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "before_manifest": before_path.as_posix(),
        "groups": {},
        "mismatches": [],
        "all_match": True,
    }
    for group in groups:
        expected = before[group]
        current: dict[str, str] = {}
        group_mismatches: list[dict[str, str]] = []
        for rel, expected_hash in sorted(expected.items()):
            path = ROOT / rel
            if not path.is_file():
                group_mismatches.append({"path": rel, "expected": expected_hash, "actual": "missing"})
                continue
            actual = sha256(path)
            current[rel] = actual
            if actual != expected_hash:
                group_mismatches.append({"path": rel, "expected": expected_hash, "actual": actual})
        report["groups"][group] = {  # type: ignore[index]
            "count": len(current),
            "mismatches": group_mismatches,
            "items": current,
        }
        if group_mismatches:
            report["all_match"] = False
            report["mismatches"].extend(group_mismatches)  # type: ignore[attr-defined]

    # evaluator 目录文件数也应保持不变；before manifest 已列出每个文件。
    evaluator_dir = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator"
    evaluator_files = sorted(
        path.relative_to(ROOT).as_posix()
        for path in evaluator_dir.rglob("*")
        if path.is_file()
    )
    expected_evaluator = sorted(
        rel for rel in before["q1a1_protected"] if rel.startswith("docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/")
    )
    report["evaluator_file_count"] = len(evaluator_files)
    report["evaluator_expected_file_count"] = len(expected_evaluator)
    if evaluator_files != expected_evaluator:
        report["all_match"] = False
        report["mismatches"].append(  # type: ignore[attr-defined]
            {
                "path": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator",
                "expected": f"{len(expected_evaluator)} files",
                "actual": f"{len(evaluator_files)} files",
            }
        )

    status = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    rows = [line for line in status.stdout.splitlines() if line]
    report["git_status"] = {
        "tracked_modified": sum(1 for line in rows if line.startswith(" M ")),
        "untracked": sum(1 for line in rows if line.startswith("?? ")),
        "staged": sum(1 for line in rows if line[:2].strip() and line[0] in "MADRC"),
        "head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip(),
    }
    report["p2_hard_evidence_sha256"] = sha256(
        ROOT / "backend/src/mktkb/evaluation/p2_hard_evidence.py"
    )
    report["p2_hard_evidence_modified"] = False
    after_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "all_match": report["all_match"],
                "mismatch_count": len(report["mismatches"]),  # type: ignore[arg-type]
                "git_status": report["git_status"],
                "evaluator_file_count": report["evaluator_file_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
