"""C1-P3 证据：保护件比对（逐字节 + 逐路径）。

三类基线（均为会话开始前已存在、只读）：
1. 本包开工前探针 `protected-before.json`：15 tracked modified、C 冻结 12、
   暂存/HEAD/分支；
2. C 冻结参考 `axes/evidence/04-protected-hashes-before.json` 的 `c_freeze_12`；
3. C1-P2 基线 `rescore/evidence-r2/04-protected-before.json` 的 `foreign_tree.files`
   （2086 个既有 untracked 文件的 path -> sha256），用于逐文件重算。

排除项（不是本包写入，且已在基线之后出现）：
- C1-P2 产物与代码、C1-P1 并行产物、本包 `c1-1/p3/` 与 3 个新增文件。

对可能含 H2 敏感内容的 untracked 树只重算**已存在文件**的 sha256（不读新文件内容、
不 dump 内容），并对新增路径只做路径级判定。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]
REPAIR = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "Q1A-EVAL-REPAIR"
AXES_BASELINE = REPAIR / "axes" / "evidence" / "04-protected-hashes-before.json"
P2_BASELINE = REPAIR / "rescore" / "evidence-r2" / "04-protected-before.json"

OWN_PREFIXES = (
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p3/",
    "backend/src/mktkb/evaluation/p2_evidence_snapshot_v03.py",
    "backend/tests/evaluation/test_p2_evidence_snapshot_v03.py",
    "docs/evaluation/p2-hard-evidence-capture-v0_3.md",
)
#: 本包会话开始前/后由其它包写入、不属于本包的保护对象。
OTHER_PREFIXES = (
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1/",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/",
    "backend/src/mktkb/evaluation/p2_empty_scope_proof.py",
    "backend/tests/evaluation/test_p2_empty_scope_proof.py",
    "docs/evaluation/q1a-scope-targets-contract-v2.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/manager-receipt.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/manager-receipt.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-aggregate-v2.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-report-v2.md",
    "docs/superpowers/plans/2026-11-14-q1a-c1-1-instrument-taskbook.md",
)


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def _untracked_files() -> list[str]:
    rows = []
    for line in _git("status", "--porcelain", "--untracked-files=all").splitlines():
        if line.startswith("?? "):
            rows.append(line[3:].replace("\\", "/"))
    return sorted(rows)


def _excluded(path: str) -> bool:
    return path.startswith(OWN_PREFIXES + OTHER_PREFIXES) or path.startswith(
        ("%SystemDrive%", "C:", "D:", "/")
    )


def _hash_group(expected: dict[str, str]) -> dict:
    rows = {}
    mismatches = []
    for rel, expected_sha in sorted(expected.items()):
        actual = _sha256(ROOT / rel)
        match = actual == expected_sha
        rows[rel] = {"expected_sha256": expected_sha, "actual_sha256": actual, "match": match}
        if not match:
            mismatches.append(rel)
    return {"item_count": len(expected), "mismatch_count": len(mismatches), "mismatches": mismatches}


def run(before_path: Path) -> dict:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    axes = json.loads(AXES_BASELINE.read_text(encoding="utf-8"))
    p2 = json.loads(P2_BASELINE.read_text(encoding="utf-8"))

    tracked = _hash_group(before["modified"])
    c_freeze = _hash_group(axes["c_freeze_12"])

    baseline_foreign = {
        path: sha for path, sha in p2["foreign_tree"]["files"].items() if not _excluded(path)
    }
    current_files = _untracked_files()
    current_set = set(current_files)
    baseline_set = set(baseline_foreign)
    missing = sorted(baseline_set - current_set)
    added = sorted(current_set - baseline_set)
    added_unexpected = [path for path in added if not _excluded(path)]
    changed = []
    checked = 0
    for path in sorted(baseline_set & current_set):
        checked += 1
        if _sha256(ROOT / path) != baseline_foreign[path]:
            changed.append(path)
    own_files = [path for path in current_files if path.startswith(OWN_PREFIXES)]
    status = [line for line in _git("status", "--porcelain").splitlines() if line.strip()]
    staged = [line for line in _git("diff", "--cached", "--name-only").splitlines() if line.strip()]
    head = _git("rev-parse", "HEAD").strip()
    branch = _git("branch", "--show-current").strip()

    verdict = (
        "unchanged"
        if not (
            tracked["mismatch_count"]
            or c_freeze["mismatch_count"]
            or missing
            or added_unexpected
            or changed
            or staged
            or head != before["head"]
            or branch != before["branch"]
        )
        else "changed"
    )
    return {
        "schema_version": "c1p3-protected-compare/v0.1",
        "verified_at": datetime.now().astimezone().isoformat(),
        "before": str(before_path),
        "baselines": {
            "own_pre_work": "p3/evidence/protected-before.json",
            "c_freeze": "axes/evidence/04-protected-hashes-before.json#c_freeze_12",
            "untracked": "rescore/evidence-r2/04-protected-before.json#foreign_tree.files",
        },
        "tracked_modified_15": tracked,
        "c_freeze_12": c_freeze,
        "git": {
            "head": head,
            "branch": branch,
            "head_equal": head == before["head"],
            "branch_equal": branch == before["branch"],
            "status_lines_before": before["status_lines"],
            "status_lines_after": len(status),
            "tracked_modified_count": sum(1 for line in status if line.startswith(" M ")),
            "staged_count": len(staged),
        },
        "untracked": {
            "baseline_file_count": len(baseline_foreign),
            "current_untracked_file_count": len(current_files),
            "checked_existing_files": checked,
            "changed_count": len(changed),
            "changed": changed[:20],
            "missing_count": len(missing),
            "missing": missing[:20],
            "added_count": len(added),
            "added": added[:50],
            "added_unexpected_count": len(added_unexpected),
            "added_unexpected": added_unexpected[:50],
            "own_new_file_count": len(own_files),
            "own_new_prefixes": list(OWN_PREFIXES),
            "excluded_prefixes": list(OTHER_PREFIXES),
        },
        "verdict": verdict,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = run(Path(args.before))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "verdict": payload["verdict"],
                "tracked_mismatch": payload["tracked_modified_15"]["mismatch_count"],
                "cfreeze_mismatch": payload["c_freeze_12"]["mismatch_count"],
                "untracked_changed": payload["untracked"]["changed_count"],
                "untracked_missing": payload["untracked"]["missing_count"],
                "untracked_unexpected_added": payload["untracked"]["added_unexpected_count"],
                "staged": payload["git"]["staged_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload["verdict"] == "unchanged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
