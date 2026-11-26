"""Q1a-3-R1 保护件快照（before/after 逐项 SHA256）+ 仓库状态摘要。

用法：
    python 01-protected-snapshot.py before
    python 01-protected-snapshot.py after
    python 01-protected-snapshot.py compare   # 比对已存在的 before/after

只输出路径与 hash / 计数；不读内容语义、不打印任何题面/答案/目标值。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
for path in (HERE, REPO / "backend" / "src", REPO / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import _common_r1 as C  # noqa: E402

REPO_FILES = [
    "backend/src/mktkb/evaluation/p2_hard_evidence.py",
    "backend/src/mktkb/evaluation/p2_evidence_rescore.py",
    "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py",
    "backend/src/mktkb/evaluation/p2_holdout_scenarios.py",
    "backend/src/mktkb/evaluation/p2_evidence_io.py",
    "backend/src/mktkb/evaluation/p2_dataset.py",
    "docs/evaluation/p2-evidence-rescore-v0_1.md",
    "docs/evaluation/p2-evidence-rescore-v0_2.md",
    "docs/evaluation/q1a-scope-targets-contract-v1.md",
    "docs/evaluation/p2-holdout-v2.manifest.json",
    "docs/evaluation/p2-holdout-v2.source-map.json",
    "docs/evaluation/p2-h2-scenarios-v0_2.json",
    "docs/evaluation/p2-h2-custody-annotations-v0_2.md",
    "tools/p2_h2_controlled_execute.py",
    "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/manager-acceptance.json",
    "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/review-aggregate.json",
    "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V3/manager-acceptance.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/manager-acceptance.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-aggregate.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/review-aggregate.json",
    "docs/reports/OBS-EVAL/P2/T207-SAFETY-TRIAGE-20261114/manager-receipt.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/manager-receipt.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/manager-acceptance.json",
]

EXTERNAL_DIRS = {
    "old_run_tree": C.OLD_RUN,
    "holdout_root": C.HOLDOUT_ROOT,
    "custody_annotations": C.CUSTODY,
}

#: 本包新增产物（对比时排除，避免把自己算成"被改动"）。
OWN_PREFIXES = (
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r1.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r1.md",
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True
    ).stdout


def snapshot(label: str) -> dict[str, object]:
    import p2_h2_controlled_execute as entry

    repo_rows = {}
    for rel in REPO_FILES:
        path = REPO / rel
        repo_rows[rel] = {"sha256": C.sha256_hex(path.read_bytes()), "bytes": path.stat().st_size}

    external: dict[str, object] = {}
    for name, root in EXTERNAL_DIRS.items():
        digest = entry.tree_digest(root)
        external[name] = {
            "root": str(root),
            "file_count": digest["file_count"],
            "bytes": digest["bytes"],
            "tree_sha256": digest["tree_sha256"],
            "files": {row["path"]: row["sha256"] for row in digest["files"]},
        }
    external["contract_ciphertext"] = {
        "root": str(C.CONTRACT_CIPHER),
        "sha256": C.sha256_hex(C.CONTRACT_CIPHER.read_bytes()),
        "bytes": C.CONTRACT_CIPHER.stat().st_size,
    }

    status = [line for line in _git("status", "--porcelain").splitlines() if line.strip()]
    modified = sorted(line[3:] for line in status if line[:2].strip() == "M")
    untracked = sorted(line[3:] for line in status if line.startswith("??"))
    own = [path for path in untracked if path.startswith(OWN_PREFIXES)]
    foreign = [path for path in untracked if not path.startswith(OWN_PREFIXES)]
    staged = _git("diff", "--cached", "--name-only").splitlines()
    return {
        "schema_version": "q1a3r1-protected-snapshot/v0.1",
        "label": label,
        "head": _git("rev-parse", "HEAD").strip(),
        "branch": _git("branch", "--show-current").strip(),
        "repo_files": repo_rows,
        "external": external,
        "git": {
            "tracked_modified": modified,
            "tracked_modified_count": len(modified),
            "staged_count": len(staged),
            "staged": staged,
            "untracked_entries": len(untracked),
            "own_new_entries": own,
            "foreign_untracked_entries": len(foreign),
            "commits_created": 0,
        },
        "calls": {"network": 0, "socket": 0, "dns": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
    }


def compare() -> int:
    before = C.strict_json((HERE / "01-protected-before.json").read_bytes())
    after = C.strict_json((HERE / "01-protected-after.json").read_bytes())
    diffs: list[dict[str, object]] = []
    for rel, row in before["repo_files"].items():
        if after["repo_files"].get(rel) != row:
            diffs.append({"type": "repo_file", "path": rel})
    for name, row in before["external"].items():
        other = after["external"].get(name) or {}
        if other.get("tree_sha256") != row.get("tree_sha256") or other.get("sha256") != row.get("sha256"):
            diffs.append({"type": "external", "name": name})
        elif row.get("files") and other.get("files") != row.get("files"):
            diffs.append({"type": "external_files", "name": name})
    git_before = before["git"]
    git_after = after["git"]
    git_equal = {
        "tracked_modified_same": git_before["tracked_modified"] == git_after["tracked_modified"],
        "staged_count_zero": git_after["staged_count"] == 0,
        "head_same": before["head"] == after["head"],
        "branch_same": before["branch"] == after["branch"],
        "foreign_untracked_same": git_before["foreign_untracked_entries"]
        == git_after["foreign_untracked_entries"],
    }
    payload = {
        "schema_version": "q1a3r1-protected-compare/v0.1",
        "protected_items": len(before["repo_files"]) + len(before["external"]),
        "differences": diffs,
        "difference_count": len(diffs),
        "git": {
            **git_equal,
            "tracked_modified_count": git_after["tracked_modified_count"],
            "untracked_entries_after": git_after["untracked_entries"],
            "own_new_entries_after": len(git_after["own_new_entries"]),
            "own_new_entries": git_after["own_new_entries"],
        },
        "verdict": "unchanged"
        if not diffs and all(git_equal.values())
        else "changed",
    }
    (HERE / "01-protected-compare.json").write_bytes(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    print(json.dumps({"verdict": payload["verdict"], "differences": len(diffs)}, ensure_ascii=True))
    return 0 if payload["verdict"] == "unchanged" else 1


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "before"
    if label == "compare":
        return compare()
    payload = snapshot(label)
    target = HERE / f"01-protected-{label}.json"
    C.need(not target.exists(), "snapshot_exists")
    target.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    print(
        json.dumps(
            {
                "label": label,
                "path": str(target),
                "sha256": C.sha256_hex(target.read_bytes()),
                "tracked_modified": payload["git"]["tracked_modified_count"],
                "untracked_entries": payload["git"]["untracked_entries"],
                "staged": payload["git"]["staged_count"],
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
