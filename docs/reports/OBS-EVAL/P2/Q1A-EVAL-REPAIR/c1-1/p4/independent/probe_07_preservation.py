"""必测 7：冻结与保全 —— C 冻结 12/12、Q1a-1/1b、合同 v1/v2、P3 模块与契约、15 tracked modified、
既有 untracked、暂存/HEAD/分支/commit 数。基线来自前轮已记录的公开证据（只作比对，不作事实来源）。
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from harness import Checks

REPO = Path(__file__).resolve().parents[8]
EVIDENCE = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR"

AXES_BASELINE = EVIDENCE / "axes/evidence/04-protected-hashes-before.json"
R2_BASELINE = EVIDENCE / "rescore/evidence-r2/04-protected-before.json"
P2_AFTER = EVIDENCE / "c1-1/p2/evidence/protected-after.json"
P1_ACCEPTANCE = EVIDENCE / "c1-1/p1/manager-acceptance.json"
P3_DEV_REPORT = EVIDENCE / "c1-1/p3/dev-report.md"

SENSITIVE_PATTERNS = (
    re.compile(r"(^|/)\.env($|\.)"),
    re.compile(r"\.fernet$"),
    re.compile(r"(^|/)(id_rsa|id_ed25519)(\.|$)"),
    re.compile(r"\.(pem|p12|pfx|key)$"),
    re.compile(r"custody", re.IGNORECASE),
    re.compile(r"holdout.*(secret|private)", re.IGNORECASE),
)

ALLOWED_NEW_PREFIXES = (
    "backend/src/mktkb/evaluation/p2_empty_scope_proof.py",
    "backend/src/mktkb/evaluation/p2_evidence_snapshot_v03.py",
    "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py",
    "backend/tests/evaluation/test_p2_empty_scope_proof.py",
    "backend/tests/evaluation/test_p2_evidence_snapshot_v03.py",
    "backend/tests/evaluation/test_p2_evidence_axes_adapter_v2.py",
    "docs/evaluation/p2-hard-evidence-capture-v0_3.md",
    "docs/evaluation/q1a-scope-targets-contract-v2.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/manager-receipt.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/manager-receipt.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-aggregate-v2.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-report-v2.md",
    "docs/superpowers/plans/2026-11-14-q1a-c1-1-instrument-taskbook.md",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    import os

    environment = dict(os.environ)
    environment["GIT_PAGER"] = "cat"
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def resolve(relative: str) -> Path:
    if relative.startswith("%SystemDrive%"):
        return Path("C:/") / relative[len("%SystemDrive%") :].lstrip("/")
    return REPO / relative


def group_hashes(group: dict[str, Any]) -> dict[str, str]:
    rows = group.get("rows") or {}
    hashes: dict[str, str] = {}
    for path, value in rows.items():
        if isinstance(value, dict):
            hashes[path] = value.get("expected_sha256") or value.get("sha256")
        elif isinstance(value, str):
            hashes[path] = value
    return hashes


def compare_group(name: str, expected: dict[str, str], checks: Checks) -> dict[str, Any]:
    changed: list[dict[str, Any]] = []
    missing: list[str] = []
    skipped: list[str] = []
    for path, want in sorted(expected.items()):
        if any(pattern.search(path) for pattern in SENSITIVE_PATTERNS):
            skipped.append(path)
            continue
        target = resolve(path)
        if not target.is_file():
            missing.append(path)
            continue
        got = sha256(target)
        if got != want:
            changed.append({"path": path, "expected": want, "actual": got})
    checks.eq(f"{name}_changed", changed, [])
    checks.eq(f"{name}_missing", missing, [])
    return {"item_count": len(expected), "changed": changed, "missing": missing, "skipped_sensitive": skipped}


def main() -> dict:
    checks = Checks("07-preservation")
    report: dict[str, Any] = {}

    axes = json.loads(AXES_BASELINE.read_text(encoding="utf-8"))
    p2_after = json.loads(P2_AFTER.read_text(encoding="utf-8"))
    r2 = json.loads(R2_BASELINE.read_text(encoding="utf-8"))
    p1 = json.loads(P1_ACCEPTANCE.read_text(encoding="utf-8"))
    p3_report = P3_DEV_REPORT.read_text(encoding="utf-8")

    groups_p2 = {group["name"]: group for group in p2_after["hash_groups"]}

    # ---- git 状态 ---------------------------------------------------------- #
    head = git("rev-parse", "HEAD").strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    staged = [line for line in git("diff", "--cached", "--name-only").splitlines() if line.strip()]
    commit_count = int(git("rev-list", "--count", "HEAD").strip())
    status = git("status", "--porcelain")
    status_lines = len([line for line in status.splitlines() if line.strip()])
    tracked_modified = sorted(
        line[3:].strip() for line in status.splitlines() if line[:2] == " M" or line[:2] == "M "
    )
    report["git"] = {
        "head": head,
        "branch": branch,
        "staged": staged,
        "commit_count": commit_count,
        "status_lines": status_lines,
        "tracked_modified_count": len(tracked_modified),
        "tracked_modified": tracked_modified,
    }
    checks.eq("head_unchanged", head, "97b0066726e5b8d6f94cbc0b63a890084550c106")
    checks.eq("branch_unchanged", branch, "codex/p2-e2e")
    checks.eq("staged_empty", staged, [])
    checks.eq("commit_count_unchanged", commit_count, 172)
    checks.eq("tracked_modified_count", len(tracked_modified), 15)

    # ---- 四个保护组 -------------------------------------------------------- #
    report["c_freeze_12"] = compare_group("c_freeze_12", axes["c_freeze_12"], checks)
    report["tracked_modified_15"] = compare_group("tracked_modified_15", axes["tracked_modified_15"], checks)
    report["q1a1_protected_38"] = compare_group(
        "q1a1_protected_38", group_hashes(groups_p2["q1a1_protected_38"]), checks
    )
    report["r2_protected_28"] = compare_group("r2_protected_28", group_hashes(groups_p2["r2_protected_28"]), checks)
    report["readonly_references_2"] = compare_group(
        "readonly_references_2", axes["readonly_references"], checks
    )

    # ---- 合同 v2 / P3 产物 -------------------------------------------------- #
    v2_schema = p1["deliverables"]["schema"]["sha256"]
    v2_aggregate = p1["deliverables"]["aggregate"]["sha256"]
    v2_report = p1["deliverables"]["report"]["sha256"]
    actual_v2 = sha256(REPO / p1["deliverables"]["schema"]["path"])
    actual_aggregate = sha256(REPO / p1["deliverables"]["aggregate"]["path"])
    actual_report = sha256(REPO / p1["deliverables"]["report"]["path"])
    checks.eq("contract_v2_schema_unchanged", actual_v2, v2_schema)
    checks.eq("contract_v2_aggregate_unchanged", actual_aggregate, v2_aggregate)
    checks.eq("contract_v2_report_unchanged", actual_report, v2_report)

    p3_hashes: dict[str, str] = {}
    for line in p3_report.splitlines():
        if "`" not in line:
            continue
        match = re.search(r"`([0-9a-f]{64})`", line)
        path_match = re.search(r"`([^`]+\.(?:py|md))`", line)
        if match and path_match:
            p3_hashes[path_match.group(1)] = match.group(1)
    p3_subset = {path: want for path, want in p3_hashes.items() if path.startswith("backend/src/mktkb/evaluation/p2_evidence_snapshot_v03.py") or path.startswith("docs/evaluation/p2-hard-evidence-capture-v0_3.md")}
    report["p3_artifacts"] = compare_group("p3_artifacts", p3_subset, checks)
    checks.eq("p3_artifact_hashes_recorded", len(p3_subset), 2, p3_subset)

    # ---- 全仓 untracked 基线（R2 2086 文件） ------------------------------- #
    baseline_files = r2["foreign_tree"]["files"]
    changed: list[dict[str, Any]] = []
    missing: list[str] = []
    skipped: list[str] = []
    for path, want in baseline_files.items():
        if any(pattern.search(path) for pattern in SENSITIVE_PATTERNS):
            skipped.append(path)
            continue
        target = resolve(path)
        if not target.is_file():
            missing.append(path)
            continue
        got = sha256(target)
        if got != want:
            changed.append({"path": path, "expected": want, "actual": got})
    report["foreign_untracked"] = {
        "item_count": len(baseline_files),
        "changed": changed,
        "missing": missing,
        "skipped_sensitive": skipped,
    }
    checks.eq("foreign_untracked_changed", changed, [])
    checks.eq("foreign_untracked_missing", missing, [])
    checks.eq("foreign_untracked_item_count", len(baseline_files), 2086)

    # ---- 新增 untracked 是否都在允许前缀内 -------------------------------- #
    untracked = [line.strip() for line in git("ls-files", "--others", "--exclude-standard").splitlines() if line.strip()]
    added = sorted(set(untracked) - set(baseline_files))
    unexpected = [
        path for path in added if not any(path == prefix or path.startswith(prefix) for prefix in ALLOWED_NEW_PREFIXES)
    ]
    report["untracked"] = {
        "current_count": len(untracked),
        "added_count": len(added),
        "unexpected_added": unexpected,
        "added": added,
    }
    checks.eq("untracked_added_all_within_allowed_prefixes", unexpected, [])

    # ---- 本包自己的新增只落在 p4/independent ------------------------------ #
    own_prefix = "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/independent/"
    own_added = [path for path in added if path.startswith(own_prefix)]
    outside = [
        path
        for path in added
        if path.startswith("docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/")
        and not path.startswith(own_prefix)
        and path
        not in {
            "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/dev-report.md",
            "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/independent-review.md",
            "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/review-aggregate.json",
        }
        and not path.startswith("docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/evidence/")
    ]
    report["own_files"] = {"count": len(own_added), "outside_independent": outside}
    checks.eq("own_files_only_under_independent", outside, [])

    # ---- 未创建 worktree、未切分支 ---------------------------------------- #
    worktrees = git("worktree", "list", "--porcelain")
    report["worktrees"] = worktrees
    checks.record(
        "no_extra_worktree",
        worktrees.count("worktree ") == 1,
        {"count": worktrees.count("worktree ")},
    )

    return checks.write(report)


if __name__ == "__main__":
    main()
