"""C1-P3 独立验收探针 6/6：冻结与保全（独立基线，不引用开发证据）。

基线（早于本包，来自 Q1a 阶段）：
- ``axes/evidence/04-protected-hashes-before.json``：C 冻结 12、15 tracked modified、
  Q1a-1 保护件、只读参考件；
- ``rescore/evidence-r2/04-protected-before.json``：外来 untracked 树（逐文件 sha256）。

核对：C 冻结 12/12、15 modified 逐条不变、外来 untracked 0 改动/0 缺失、
暂存 0、HEAD/分支/commit 数不变、合同 v1/v2 与旧卡/账本/GO/30 题/标签未被动。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = next(
    parent
    for parent in HERE.parents
    if (parent / "backend" / "src" / "mktkb").is_dir() and (parent / "docs").is_dir()
)


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    # 注意：不能对 porcelain 输出做 lstrip，否则首行 " M path" 的前导空格会被吃掉。
    return result.stdout.rstrip("\r\n")


def compare(expected: dict[str, str]) -> dict:
    changed, missing = [], []
    for rel, digest in expected.items():
        actual = sha256(REPO / rel)
        if actual is None:
            missing.append(rel)
        elif actual != digest:
            changed.append({"path": rel, "expected": digest, "actual": actual})
    return {
        "item_count": len(expected),
        "changed_count": len(changed),
        "missing_count": len(missing),
        "changed": changed[:10],
        "missing": missing[:10],
    }


def main() -> int:
    axes = json.loads(
        (REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json").read_text(
            encoding="utf-8"
        )
    )
    r2 = json.loads(
        (REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r2/04-protected-before.json").read_text(
            encoding="utf-8"
        )
    )
    status = git("status", "--porcelain")
    status_lines = [line for line in status.splitlines() if line.strip()]
    modified = [line[3:] for line in status_lines if line.startswith(" M ")]
    staged = [line for line in status_lines if line[:1] not in {" ", "?", "!"}]
    untracked_now = [
        line[3:]
        for line in status_lines
        if line.startswith("?? ")
    ]

    c_freeze = compare(axes["c_freeze_12"])
    tracked = compare(axes["tracked_modified_15"])
    q1a1 = compare(axes["q1a1_protected"])
    readonly = compare(axes["readonly_references"])
    repo_files = compare(
        {path: row["sha256"] for path, row in r2["repo_files"].items()}
    )

    foreign = r2["foreign_tree"]["files"]
    foreign_changed, foreign_missing = [], []
    for rel, digest in foreign.items():
        actual = sha256(REPO / rel)
        if actual is None:
            foreign_missing.append(rel)
        elif actual != digest:
            foreign_changed.append({"path": rel, "expected": digest, "actual": actual})
    # 现状 untracked 文件全集（git 视角），与基线差集 = 本包新增
    current_untracked_files = [
        item for item in git("ls-files", "--others", "--exclude-standard").splitlines() if item
    ]
    baseline_files = set(foreign)
    added = sorted(set(current_untracked_files) - baseline_files)
    # 允许的新增：Q1a 修复阶段产物 + C1-1 各包交付物 + 本单任务书 + 本次独立验收产物。
    allowed_prefixes = (
        "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/",
        "docs/evaluation/q1a-scope-targets-contract-v2.md",
        "docs/evaluation/p2-hard-evidence-capture-v0_3.md",
        "docs/superpowers/plans/2026-11-14-q1a-c1-1-instrument-taskbook.md",
        "backend/src/mktkb/evaluation/p2_empty_scope_proof.py",
        "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py",
        "backend/src/mktkb/evaluation/p2_evidence_snapshot_v03.py",
        "backend/tests/evaluation/test_p2_empty_scope_proof.py",
        "backend/tests/evaluation/test_p2_evidence_axes_adapter_v2.py",
        "backend/tests/evaluation/test_p2_evidence_snapshot_v03.py",
    )
    disallowed_added = [item for item in added if not item.startswith(allowed_prefixes)]
    independent_prefix = "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p3/independent/"
    my_own_files = {
        "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p3/independent-review.md",
        "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p3/review-aggregate.json",
    }
    my_artifacts = [
        item for item in added if item.startswith(independent_prefix) or item in my_own_files
    ]
    p3_dev = [
        item
        for item in added
        if item.startswith("docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p3/")
        and not item.startswith(independent_prefix)
        and item not in my_own_files
    ]
    earlier = [item for item in added if item not in set(my_artifacts) | set(p3_dev)]

    contract_v2 = json.loads(
        (
            REPO
            / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1/manager-acceptance.json"
        ).read_text(encoding="utf-8")
    )
    v2_expected = contract_v2["deliverables"]["schema"]["sha256"]
    v2_actual = sha256(REPO / "docs/evaluation/q1a-scope-targets-contract-v2.md")

    result = {
        "probe": "preservation",
        "git": {
            "head": git("rev-parse", "HEAD"),
            "branch": git("symbolic-ref", "--short", "HEAD"),
            "head_matches_taskbook": git("rev-parse", "HEAD")
            == "97b0066726e5b8d6f94cbc0b63a890084550c106",
            "branch_matches_taskbook": git("symbolic-ref", "--short", "HEAD") == "codex/p2-e2e",
            "commit_count": int(git("rev-list", "--count", "HEAD") or 0),
            "staged_count": len(staged),
            "tracked_modified_count": len(modified),
            "tracked_modified_paths_equal_baseline": sorted(modified)
            == sorted(axes["tracked_modified_15"]),
            "untracked_entries": len(untracked_now),
        },
        "c_freeze_12": c_freeze,
        "tracked_modified_15": tracked,
        "q1a1_protected": q1a1,
        "readonly_references": readonly,
        "repo_files_28": repo_files,
        "foreign_untracked": {
            "baseline_file_count": len(foreign),
            "changed_count": len(foreign_changed),
            "missing_count": len(foreign_missing),
            "changed": foreign_changed[:10],
            "missing": foreign_missing[:10],
            "added_count": len(added),
            "added": added,
            "my_artifacts": my_artifacts,
            "p3_dev_artifacts": p3_dev,
            "earlier_stage_artifacts": earlier,
            "disallowed_added": disallowed_added,
        },
        "contract_v2": {
            "expected_sha256": v2_expected,
            "actual_sha256": v2_actual,
            "unchanged": v2_expected == v2_actual,
        },
        "verdict": None,
    }
    result["verdict"] = "PASS" if (
        result["git"]["head_matches_taskbook"]
        and result["git"]["branch_matches_taskbook"]
        and result["git"]["staged_count"] == 0
        and result["git"]["tracked_modified_count"] == 15
        and result["git"]["tracked_modified_paths_equal_baseline"]
        and c_freeze["changed_count"] == 0
        and c_freeze["missing_count"] == 0
        and tracked["changed_count"] == 0
        and q1a1["changed_count"] == 0
        and readonly["changed_count"] == 0
        and repo_files["changed_count"] == 0
        and repo_files["missing_count"] == 0
        and not foreign_changed
        and not foreign_missing
        and not disallowed_added
        and result["contract_v2"]["unchanged"]
    ) else "FAIL"
    (HERE / "out" / "06-preservation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "git": result["git"],
                "c_freeze_12": {k: result["c_freeze_12"][k] for k in ("item_count", "changed_count", "missing_count")},
                "tracked_modified_15": {k: result["tracked_modified_15"][k] for k in ("item_count", "changed_count")},
                "q1a1_protected": {k: result["q1a1_protected"][k] for k in ("item_count", "changed_count")},
                "readonly_references": {k: result["readonly_references"][k] for k in ("item_count", "changed_count")},
                "repo_files_28": {k: result["repo_files_28"][k] for k in ("item_count", "changed_count", "missing_count")},
                "foreign_untracked": {
                    k: result["foreign_untracked"][k]
                    for k in ("baseline_file_count", "changed_count", "missing_count", "added_count", "disallowed_added")
                },
                "contract_v2": result["contract_v2"],
                "verdict": result["verdict"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
