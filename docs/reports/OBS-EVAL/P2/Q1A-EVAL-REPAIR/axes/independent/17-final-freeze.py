#!/usr/bin/env python
"""探针 17：现场/冻结复核（HEAD、暂存、C 冻结 12、15 tracked modified、evaluator 35、axes/**、
新增文件仅限本包）+ 验收前后 git status 差异。

输出：17-final-freeze.out.json
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from _common import HERE, ROOT

EVID_BEFORE = HERE / "00-git-status-before.txt"
AXES_PROTECTED = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json"
MY_PREFIX = "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/independent/"

RESULTS: list[dict[str, Any]] = []


def check(label: str, ok: bool, detail: Any = None) -> None:
    RESULTS.append({"label": label, "ok": bool(ok), "detail": detail})


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    return completed.stdout


def main() -> int:
    recorded = json.loads(AXES_PROTECTED.read_text(encoding="utf-8"))

    head = git("rev-parse", "HEAD").strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    staged = [line for line in git("diff", "--cached", "--name-only").splitlines() if line.strip()]
    status_lines = [line for line in git("status", "--porcelain", "-uall").splitlines() if line.strip()]
    worktrees = [line for line in git("worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]

    check("HEAD == 97b0066…", head == "97b0066726e5b8d6f94cbc0b63a890084550c106", head)
    check("branch == codex/p2-e2e", branch == "codex/p2-e2e", branch)
    check("staging area empty", staged == [], staged)
    check("worktrees unchanged (3: main + 2 pre-existing)", len(worktrees) == 3, worktrees)
    branches = [line.split("|") for line in git("for-each-ref", "refs/heads", "--format=%(refname:short)|%(creatordate:iso8601)").splitlines() if line.strip()]
    check("no branch created during acceptance (all creatordate before 2026-11-14)", all("2026-11-14" not in when for _, when in branches), branches)
    check("current branch is the only checked-out one", branch in {name for name, _ in branches})

    modified = [line[3:] for line in status_lines if line.startswith(" M") or line.startswith("M ")]
    untracked = [line[3:] for line in status_lines if line.startswith("??")]
    check("15 tracked modified", len(modified) == 15, len(modified))
    check("tracked modified paths == recorded 15", sorted(modified) == sorted(recorded["tracked_modified_15"]), sorted(set(modified) ^ set(recorded["tracked_modified_15"])))
    modified_mismatch = {path: sha(ROOT / path) for path in modified if sha(ROOT / path) != recorded["tracked_modified_15"].get(path)}
    check("15 tracked modified bytes unchanged vs captured-before", modified_mismatch == {}, modified_mismatch)

    c_mismatch = {path: sha(ROOT / path) for path in recorded["c_freeze_12"] if sha(ROOT / path) != recorded["c_freeze_12"][path]}
    check("C frozen 12/12 unchanged", c_mismatch == {} and len(recorded["c_freeze_12"]) == 12, c_mismatch)
    check("p2_hard_evidence.py == fba6e606…", sha(ROOT / "backend/src/mktkb/evaluation/p2_hard_evidence.py") == "fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b")

    q1a1 = recorded["q1a1_protected"]
    evaluator_files = {path: digest for path, digest in q1a1.items() if path.startswith("docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/")}
    q1a1_mismatch = {path: sha(ROOT / path) for path, digest in q1a1.items() if sha(ROOT / path) != digest}
    check("Q1a-1 protected files unchanged (all recorded)", q1a1_mismatch == {}, q1a1_mismatch)
    check("evaluator recorded files == 35", len(evaluator_files) == 35, len(evaluator_files))
    actual_evaluator = sorted(str(path.relative_to(ROOT)).replace("\\", "/") for path in (ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator").rglob("*") if path.is_file())
    check("evaluator directory still 35 files", len(actual_evaluator) == 35, len(actual_evaluator))
    check("evaluator file set unchanged", set(actual_evaluator) == set(evaluator_files), sorted(set(actual_evaluator) ^ set(evaluator_files)))
    check("p2_evidence_rescore.py == d8260256…", sha(ROOT / "backend/src/mktkb/evaluation/p2_evidence_rescore.py") == "d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9")

    readonly_mismatch = {path: sha(ROOT / path) for path, digest in recorded["readonly_references"].items() if sha(ROOT / path) != digest}
    check("readonly annotation schema v0.1/v0.2 unchanged", readonly_mismatch == {}, readonly_mismatch)

    # axes/**（除本包 independent/）在验收期间是否被改：用起始 baseline 比对
    start = json.loads((HERE / "01-baseline-hashes-start.json").read_text(encoding="utf-8"))
    axes_mismatch = {}
    for item in start["axes_files"]:
        path = ROOT / item["path"]
        if not path.is_file() or sha(path) != item["sha256"]:
            axes_mismatch[item["path"]] = None if not path.is_file() else sha(path)
    check("axes/** (excluding independent/) unchanged since acceptance baseline", axes_mismatch == {}, axes_mismatch)

    # 被验收三文件：验收开始 baseline vs 现在（字节稳定性）
    stability = {}
    for item in start["files"]:
        path = ROOT / item["path"]
        current = sha(path) if path.is_file() else None
        stability[item["path"]] = {"start": item["sha256"], "end": current, "stable": current == item["sha256"]}
    check("accepted bytes: module/test/contract stable during acceptance", all(item["stable"] for item in stability.values()), stability)

    # git status 前后差异：新增只能是本包文件
    before = [line for line in EVID_BEFORE.read_text(encoding="utf-8").splitlines() if line.strip()]
    before_set = set(before)
    after_set = set(status_lines)
    added = sorted(after_set - before_set)
    removed = sorted(before_set - after_set)
    added_paths = [line[3:] for line in added]
    added_package = [path for path in added_paths if path.startswith(MY_PREFIX)]
    deliverable_prefix = "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/"
    my_deliverables = sorted(
        path for path in added_paths if path.startswith(deliverable_prefix) and not path.startswith(MY_PREFIX)
    )
    other_additions = [path for path in added_paths if path not in added_package and path not in my_deliverables]
    check("git status: nothing removed during acceptance", removed == [], removed)
    independent_files = sorted(str(path.relative_to(ROOT)).replace("\\", "/") for path in HERE.rglob("*") if path.is_file())
    check("git status: added package files == files present in axes/independent/", sorted(added_package) == independent_files, {"added": len(added_package), "present": len(independent_files)})
    check(
        "git status: my additions in axes/ are only independent-review.md + review-aggregate.json",
        my_deliverables
        == [
            "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/independent-review.md",
            "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/review-aggregate.json",
        ],
        my_deliverables,
    )
    check(
        "git status: external concurrent write only scope-contract/manager-acceptance.json (not Q1a-1b package)",
        other_additions == ["docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/manager-acceptance.json"],
        other_additions,
    )
    check("git status: baseline had 15 modified + 2050 untracked", sum(1 for line in before if line.startswith(" M")) == 15 and sum(1 for line in before if line.startswith("??")) == 2050, {"modified": sum(1 for line in before if line.startswith(" M")), "untracked": sum(1 for line in before if line.startswith("??"))})
    check("git status: all 15 modified lines identical before/after", [line for line in before if line.startswith(" M")] == [line for line in status_lines if line.startswith(" M")])

    payload = {
        "probe": "17-final-freeze",
        "assertions_total": len(RESULTS),
        "assertions_failed": len([item for item in RESULTS if not item["ok"]]),
        "results": RESULTS,
        "status_counts": {"modified": len(modified), "untracked": len(untracked), "staged": len(staged), "head": head, "branch": branch},
        "added_during_acceptance": added_paths,
        "verdict": "PASS" if all(item["ok"] for item in RESULTS) else "FAIL",
    }
    (HERE / "17-final-freeze.out.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"assertions": len(RESULTS), "failed": payload["assertions_failed"], "added": len(added_paths), "verdict": payload["verdict"]}, ensure_ascii=False))
    if payload["assertions_failed"]:
        print(json.dumps([item for item in RESULTS if not item["ok"]], ensure_ascii=False, indent=2))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
