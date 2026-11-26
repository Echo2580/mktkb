"""C1-P4 证据：保护件比对（逐字节 + 逐路径）。

三类基线（均为本包开工前已存在、只读）：
1. C 冻结与 15 tracked modified 参考 `axes/evidence/04-protected-hashes-before.json`；
2. 既有 untracked 文件树参考 `rescore/evidence-r2/04-protected-before.json`
   的 `foreign_tree.files`（path -> sha256），逐文件重算；
3. 当前 HEAD / 分支 / 暂存区与基线逐值比较。

排除项（不是本包写入，或本包新增产物）：
- 本包 `c1-1/p4/`、适配器模块、适配器测试（own）；
- P1/P2/P3/P4 并行产物与新增契约文档、rescore 产物（other）。
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
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/",
    "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py",
    "backend/tests/evaluation/test_p2_evidence_axes_adapter_v2.py",
)
OTHER_PREFIXES = (
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1/",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p3/",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/",
    "backend/src/mktkb/evaluation/p2_empty_scope_proof.py",
    "backend/tests/evaluation/test_p2_empty_scope_proof.py",
    "backend/src/mktkb/evaluation/p2_evidence_snapshot_v03.py",
    "backend/tests/evaluation/test_p2_evidence_snapshot_v03.py",
    "docs/evaluation/q1a-scope-targets-contract-v2.md",
    "docs/evaluation/p2-hard-evidence-capture-v0_3.md",
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


def run() -> dict:
    axes = json.loads(AXES_BASELINE.read_text(encoding="utf-8"))
    p2 = json.loads(P2_BASELINE.read_text(encoding="utf-8"))

    tracked = _hash_group(axes["tracked_modified_15"])
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
    other_files = [path for path in added if path.startswith(OTHER_PREFIXES)]
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
            or head != axes["head"]
            or branch != axes["branch"]
        )
        else "changed"
    )
    untracked_tree = hashlib.sha256(
        "\n".join(f"{path}:{_sha256(ROOT / path)}" for path in current_files).encode("utf-8")
    ).hexdigest()
    after = {
        "schema_version": "c1p4-protected-after/v0.1",
        "verified_at": datetime.now().astimezone().isoformat(),
        "head": head,
        "branch": branch,
        "status_lines": len(status),
        "staged_lines": len(staged),
        "tracked_modified": {rel: _sha256(ROOT / rel) for rel in sorted(axes["tracked_modified_15"])},
        "c_freeze_12": {rel: _sha256(ROOT / rel) for rel in sorted(axes["c_freeze_12"])},
        "untracked_count": len(current_files),
        "untracked_tree_sha256": untracked_tree,
        "own_new_files": own_files,
    }
    return {
        "schema_version": "c1p4-protected-compare/v0.1",
        "verified_at": datetime.now().astimezone().isoformat(),
        "baselines": {
            "tracked_and_c_freeze": "axes/evidence/04-protected-hashes-before.json",
            "untracked": "rescore/evidence-r2/04-protected-before.json#foreign_tree.files",
        },
        "tracked_modified_15": tracked,
        "c_freeze_12": c_freeze,
        "git": {
            "head": head,
            "baseline_head": axes["head"],
            "head_equal": head == axes["head"],
            "branch": branch,
            "baseline_branch": axes["branch"],
            "branch_equal": branch == axes["branch"],
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
            "other_added_count": len(other_files),
            "own_new_prefixes": list(OWN_PREFIXES),
            "excluded_prefixes": list(OTHER_PREFIXES),
        },
        "after": after,
        "verdict": verdict,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--after", required=True)
    args = parser.parse_args()
    payload = run()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    after = Path(args.after)
    after.write_text(
        json.dumps(payload["after"], ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
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
                "tracked_modified_count": payload["git"]["tracked_modified_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload["verdict"] == "unchanged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
