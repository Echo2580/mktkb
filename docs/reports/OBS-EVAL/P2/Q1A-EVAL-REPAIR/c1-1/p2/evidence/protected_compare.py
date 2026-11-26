"""C1-P2 保护件对比：公开可读文件逐字节；私密/保管树只引用基线 hash，不重读。

基线来自（均为只读、会话开始前已存在）：
- `axes/evidence/04-protected-hashes-before.json`：15 tracked modified、C 冻结 12、
  Q1a-1 保护 38、只读参考 2；
- `rescore/evidence-r2/04-protected-before.json`：R2 保护 28 文件、外部树、untracked 树。

本脚本不读 `.env`、真实 H2 题面/标签/答案、私有密文/key/保管会话。对可能含 H2
敏感内容的 untracked 树只做 **路径集合 + mtime 守卫**，不读字节；对公开的
evidence-r1 / NOT-RUN evidence 树重算逐文件 hash。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
REPAIR = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "Q1A-EVAL-REPAIR"
Q1A1_BASELINE = REPAIR / "axes" / "evidence" / "04-protected-hashes-before.json"
R2_BASELINE = REPAIR / "rescore" / "evidence-r2" / "04-protected-before.json"
RESCORE = REPAIR / "rescore"
FOREIGN_EXCLUDE = "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/"
OWN_PREFIXES = (
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/",
    "backend/src/mktkb/evaluation/p2_empty_scope_proof.py",
    "backend/tests/evaluation/test_p2_empty_scope_proof.py",
)
#: 并行 C1-P1 / 经理在本包会话开始后新增的公开产物；不是本包写入。
CONCURRENT_PREFIXES = (
    "docs/evaluation/q1a-scope-targets-contract-v2.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/manager-receipt.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/manager-receipt.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-aggregate-v2.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-report-v2.md",
    "docs/superpowers/plans/2026-11-14-q1a-c1-1-instrument-taskbook.md",
)
SESSION_START = datetime.fromisoformat("2026-11-14T20:46:48+08:00").timestamp()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def _tree(root: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            files[rel] = _sha256(path)
            total += path.stat().st_size
    joined = "\n".join(f"{rel}:{files[rel]}" for rel in sorted(files))
    return {
        "file_count": len(files),
        "bytes": total,
        "tree_sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        "files": files,
    }


def _hash_group(name: str, expected: dict[str, str]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    mismatches: list[str] = []
    for rel, expected_sha in sorted(expected.items()):
        path = ROOT / rel
        actual = _sha256(path) if path.is_file() else None
        rows[rel] = {
            "expected_sha256": expected_sha,
            "actual_sha256": actual,
            "match": actual == expected_sha,
            "mtime_before_session_start": path.is_file() and path.stat().st_mtime <= SESSION_START,
        }
        if actual != expected_sha:
            mismatches.append(rel)
    return {"name": name, "item_count": len(expected), "mismatches": mismatches, "rows": rows}


def _untracked_paths() -> list[str]:
    rows = []
    for line in _git("status", "--porcelain", "--untracked-files=all").splitlines():
        if line.startswith("?? "):
            rows.append(line[3:])
    return sorted(rows)


def _untracked_entries() -> list[str]:
    rows = []
    for line in _git("status", "--porcelain").splitlines():
        if line.startswith("?? "):
            rows.append(line[3:])
    return sorted(rows)


def _is_external_path(path: str) -> bool:
    return path.startswith(("%SystemDrive%", "C:", "D:", "/"))


def _foreign_paths(paths: list[str]) -> list[str]:
    return [
        path
        for path in paths
        if not _is_external_path(path)
        and not path.startswith(FOREIGN_EXCLUDE)
        and not path.startswith(OWN_PREFIXES)
        and not path.startswith(CONCURRENT_PREFIXES)
    ]


def _foreign_entries(paths: list[str]) -> list[str]:
    """status 条目计数保留外部 ``%SystemDrive%/`` 条目，与 R2 基线同口径。"""

    return [
        path
        for path in paths
        if not path.startswith(FOREIGN_EXCLUDE)
        and not path.startswith(OWN_PREFIXES)
        and not path.startswith(CONCURRENT_PREFIXES)
    ]


def _own_paths(paths: list[str]) -> list[str]:
    return [path for path in paths if path.startswith(OWN_PREFIXES)]


def _concurrent_paths(paths: list[str]) -> list[str]:
    return [path for path in paths if path.startswith(CONCURRENT_PREFIXES)]


def run() -> tuple[dict[str, Any], dict[str, Any]]:
    q1a1 = json.loads(Q1A1_BASELINE.read_text(encoding="utf-8"))
    r2 = json.loads(R2_BASELINE.read_text(encoding="utf-8"))

    groups = [
        _hash_group("tracked_modified_15", q1a1["tracked_modified_15"]),
        _hash_group("c_freeze_12", q1a1["c_freeze_12"]),
        _hash_group("q1a1_protected_38", q1a1["q1a1_protected"]),
        _hash_group("readonly_references_2", q1a1["readonly_references"]),
        _hash_group("r2_protected_28", {rel: row["sha256"] for rel, row in r2["repo_files"].items()}),
    ]

    public_external: dict[str, Any] = {}
    for name in ("r1_evidence_tree", "not_run_evidence_tree"):
        expected = r2["external"][name]
        current = _tree(Path(expected["root"]))
        public_external[name] = {
            "root": expected["root"],
            "baseline_file_count": expected["file_count"],
            "baseline_bytes": expected["bytes"],
            "baseline_tree_sha256": expected["tree_sha256"],
            "actual_file_count": current["file_count"],
            "actual_bytes": current["bytes"],
            "actual_tree_sha256": current["tree_sha256"],
            "files_equal": current["files"] == expected["files"],
            "bytes_equal": current["bytes"] == expected["bytes"],
        }

    private_external: dict[str, Any] = {}
    for name, row in sorted(r2["external"].items()):
        if name in public_external:
            continue
        private_external[name] = {
            "root": row.get("root"),
            "baseline_sha256": row.get("sha256") or row.get("tree_sha256"),
            "baseline_bytes": row.get("bytes"),
            "baseline_file_count": row.get("file_count"),
            "recomputed": False,
            "reason": "custody_or_h2_sensitive_boundary_normal_developer_must_not_read",
        }

    current_untracked = _untracked_paths()
    current_entries = _untracked_entries()
    own = _own_paths(current_untracked)
    own_entries = _own_paths(current_entries)
    concurrent = _concurrent_paths(current_untracked)
    concurrent_entries = _concurrent_paths(current_entries)
    foreign = _foreign_paths(current_untracked)
    foreign_entries = _foreign_entries(current_entries)
    baseline_foreign = {
        path
        for path in r2["foreign_tree"]["files"]
        if not _is_external_path(path)
    }
    current_foreign_set = set(foreign)
    missing = sorted(baseline_foreign - current_foreign_set)
    added = sorted(current_foreign_set - baseline_foreign)
    mtimes = [
        (ROOT / path).stat().st_mtime
        for path in foreign
        if (ROOT / path).is_file()
    ]
    foreign_after_session = [
        path
        for path in foreign
        if (ROOT / path).is_file() and (ROOT / path).stat().st_mtime > SESSION_START
    ]

    status = [line for line in _git("status", "--porcelain").splitlines() if line.strip()]
    modified = sorted(line[3:] for line in status if line[:2].strip() == "M")
    staged = _git("diff", "--cached", "--name-only").splitlines()
    current_head = _git("rev-parse", "HEAD").strip()
    current_branch = _git("branch", "--show-current").strip()

    git_after = {
        "head": current_head,
        "branch": current_branch,
        "head_same": current_head == r2["head"],
        "branch_same": current_branch == r2["branch"],
        "tracked_modified": modified,
        "tracked_modified_same": modified == sorted(r2["git"]["tracked_modified"]),
        "tracked_modified_count": len(modified),
        "staged_count": len(staged),
        "staged": staged,
        "commits_created": 0,
        "untracked_entries": len(current_entries),
        "own_new_entries": own_entries,
        "own_new_files": own,
        "concurrent_new_entries": concurrent_entries,
        "concurrent_new_files": concurrent,
        "foreign_untracked_entries": len(foreign_entries),
        "foreign_untracked_entries_same": len(foreign_entries) == r2["git"]["foreign_untracked_entries"],
    }

    after = {
        "schema_version": "c1p2-protected-after/v0.1",
        "verified_at": datetime.now().astimezone().isoformat(),
        "session_start": "2026-11-14T20:46:48+08:00",
        "head": current_head,
        "branch": current_branch,
        "hash_groups": groups,
        "public_external": public_external,
        "private_external": private_external,
        "foreign_tree": {
            "baseline_file_count": r2["foreign_tree"]["file_count"],
            "baseline_tree_sha256": r2["foreign_tree"]["tree_sha256"],
            "content_hash_recomputed": False,
            "reason": "untracked_tree_may_contain_h2_sensitive_artifacts_path_set_and_mtime_only",
            "baseline_repo_relative_paths": len(baseline_foreign),
            "current_repo_relative_paths": len(current_foreign_set),
            "path_set_equal": not missing and not added,
            "missing_paths": missing[:20],
            "added_paths": added[:20],
            "missing_path_count": len(missing),
            "added_path_count": len(added),
            "concurrent_paths_excluded": len(concurrent),
            "concurrent_entries_excluded": concurrent_entries,
            "max_mtime": max(mtimes) if mtimes else None,
            "max_mtime_before_session_start": bool(mtimes) and max(mtimes) <= SESSION_START,
            "paths_modified_after_session_start": foreign_after_session[:20],
            "paths_modified_after_session_start_count": len(foreign_after_session),
        },
        "git": git_after,
    }

    differences: list[dict[str, Any]] = []
    for group in groups:
        for rel in group["mismatches"]:
            differences.append({"type": "hash_group", "group": group["name"], "path": rel})
    for name, row in public_external.items():
        if not row["files_equal"]:
            differences.append({"type": "public_external_tree", "name": name})
    if not after["foreign_tree"]["path_set_equal"]:
        differences.append({"type": "foreign_tree_path_set"})
    if not after["foreign_tree"]["max_mtime_before_session_start"]:
        differences.append({"type": "foreign_tree_mtime"})
    if not git_after["head_same"]:
        differences.append({"type": "head"})
    if not git_after["branch_same"]:
        differences.append({"type": "branch"})
    if not git_after["tracked_modified_same"]:
        differences.append({"type": "tracked_modified_paths"})
    if git_after["staged_count"] != 0:
        differences.append({"type": "staged"})
    if not git_after["foreign_untracked_entries_same"]:
        differences.append({"type": "foreign_untracked_entries"})

    compare = {
        "schema_version": "c1p2-protected-compare/v0.1",
        "verdict": "unchanged" if not differences else "changed",
        "difference_count": len(differences),
        "differences": differences,
        "groups": {
            group["name"]: {
                "item_count": group["item_count"],
                "mismatch_count": len(group["mismatches"]),
                "mismatches": group["mismatches"],
            }
            for group in groups
        },
        "public_external": {
            name: {
                "files_equal": row["files_equal"],
                "bytes_equal": row["bytes_equal"],
                "baseline_tree_sha256": row["baseline_tree_sha256"],
                "actual_tree_sha256": row["actual_tree_sha256"],
            }
            for name, row in public_external.items()
        },
        "private_external": {
            name: {
                "baseline_sha256": row["baseline_sha256"],
                "recomputed": False,
                "reason": row["reason"],
            }
            for name, row in private_external.items()
        },
        "foreign_tree": {
            "path_set_equal": after["foreign_tree"]["path_set_equal"],
            "max_mtime_before_session_start": after["foreign_tree"]["max_mtime_before_session_start"],
            "content_hash_recomputed": False,
        },
        "git": {
            "head_same": git_after["head_same"],
            "branch_same": git_after["branch_same"],
            "tracked_modified_same": git_after["tracked_modified_same"],
            "staged_count_zero": git_after["staged_count"] == 0,
            "foreign_untracked_entries_same": git_after["foreign_untracked_entries_same"],
            "own_new_entries": own_entries,
            "concurrent_new_entries": concurrent_entries,
            "foreign_untracked_entries": len(foreign_entries),
        },
    }
    return after, compare


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    after, compare = run()
    (out / "protected-after.json").write_text(
        json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "protected-compare.json").write_text(
        json.dumps(compare, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verdict": compare["verdict"], "difference_count": compare["difference_count"]}))
    return 0 if compare["verdict"] == "unchanged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
