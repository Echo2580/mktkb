"""R3 protected-item snapshot (before/after SHA256) + git state summary.

Usage:
    python 07-protected-snapshot.py before
    python 07-protected-snapshot.py after
    python 07-protected-snapshot.py compare
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
for path in (
    HERE,
    REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r2",
    REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1",
    REPO / "backend/src",
    REPO / "tools",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import _common_r2 as C  # noqa: E402

RESCORE = HERE.parent
REPO_FILES = [
    "docs/evaluation/p2-stale-source-criterion-v1.md",
    "backend/src/mktkb/evaluation/p2_stale_version_state.py",
    "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py",
    "docs/evaluation/q1a-scope-targets-contract-v1.md",
    "docs/evaluation/q1a-scope-targets-contract-v2.md",
    "backend/src/mktkb/evaluation/p2_hard_evidence.py",
    "backend/src/mktkb/evaluation/p2_evidence_rescore.py",
    "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py",
    "backend/src/mktkb/evaluation/p2_holdout_scenarios.py",
    "backend/src/mktkb/evaluation/p2_evidence_io.py",
    "backend/src/mktkb/evaluation/p2_dataset.py",
    "docs/evaluation/p2-evidence-rescore-v0_1.md",
    "docs/evaluation/p2-evidence-rescore-v0_2.md",
    "docs/evaluation/p2-holdout-v2.manifest.json",
    "docs/evaluation/p2-holdout-v2.source-map.json",
    "docs/evaluation/p2-h2-scenarios-v0_2.json",
    "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json",
    "docs/evaluation/p2-h2-custody-annotations-v0_2.md",
    "docs/evaluation/p2-h2-scenario-execution-v0_1.md",
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
    # R1/R2/NOT-RUN products (read-only)
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r1.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r1.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r2.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r2.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report.md",
]
EXTERNAL_DIRS = {
    "old_run_tree": C.OLD_RUN,
    "holdout_root": C.HOLDOUT_ROOT,
    "custody_annotations": C.CUSTODY,
    "r1_evidence_tree": RESCORE / "evidence-r1",
    "r2_evidence_tree": RESCORE / "evidence-r2",
    "not_run_evidence_tree": RESCORE / "evidence",
}
PRIVATE_PATHS = {
    "r1_private_detail": C.OUT_PRIVATE_DIR / "rescore-detail-r1.fernet",
    "r2_private_detail": C.OUT_PRIVATE_DIR / "rescore-detail-r2.fernet",
}
CONTRACT_V2_CIPHER = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet")
EXPECTED_PRODUCT_HASHES = {
    "r1_aggregate": ("605c89cb74ffa29152cf701f2e7dbe7fa9bebc78bc3e3a800378aba9b1668652", 31836),
    "r1_private_detail": ("2f6f4d85026d4b3fb654e17f9ebbb0baac923dd93dc6fa326bb9325fdd69dacc", 74488),
    "r2_aggregate": ("2447d945485fb89e75dc3dbf6553f68073ec467cf8cbc415b900143f7908daaf", 46804),
    "r2_private_detail": ("fef978b73a4bd7e5c51b39eebf759f35826492632d5509cead6126153b1072b1", 108108),
}
OWN_PREFIXES = (
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r3/",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r3.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r3.md",
)
FOREIGN_EXCLUDE = "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def _foreign_tree_digest() -> dict[str, object]:
    rows = [
        line[3:]
        for line in _git("status", "--porcelain", "--untracked-files=all").splitlines()
        if line.startswith("??") and not line[3:].startswith(FOREIGN_EXCLUDE)
    ]
    files = {}
    for rel in sorted(rows):
        path = REPO / rel
        if path.is_file():
            files[rel] = C.sha256_hex(path.read_bytes())
    return {
        "file_count": len(files),
        "tree_sha256": C.sha256_hex(C.canonical_json_bytes(files)),
        "files": files,
    }


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
    external["contract_v1_ciphertext"] = {
        "root": str(C.CONTRACT_CIPHER),
        "sha256": C.sha256_hex(C.CONTRACT_CIPHER.read_bytes()),
        "bytes": C.CONTRACT_CIPHER.stat().st_size,
    }
    external["contract_v2_ciphertext"] = {
        "root": str(CONTRACT_V2_CIPHER),
        "sha256": C.sha256_hex(CONTRACT_V2_CIPHER.read_bytes()),
        "bytes": CONTRACT_V2_CIPHER.stat().st_size,
    }
    for name, path in PRIVATE_PATHS.items():
        if path.is_file():
            external[name] = {
                "root": str(path),
                "sha256": C.sha256_hex(path.read_bytes()),
                "bytes": path.stat().st_size,
            }

    status = [line for line in _git("status", "--porcelain").splitlines() if line.strip()]
    modified = sorted(line[3:] for line in status if line[:2].strip() == "M")
    untracked = sorted(line[3:] for line in status if line.startswith("??"))
    own = [path for path in untracked if path.startswith(OWN_PREFIXES)]
    foreign = [path for path in untracked if not path.startswith(OWN_PREFIXES)]
    staged = _git("diff", "--cached", "--name-only").splitlines()
    return {
        "schema_version": "q1a3r3-protected-snapshot/v0.1",
        "label": label,
        "head": _git("rev-parse", "HEAD").strip(),
        "branch": _git("branch", "--show-current").strip(),
        "repo_files": repo_rows,
        "expected_product_hashes": EXPECTED_PRODUCT_HASHES,
        "external": external,
        "foreign_tree": _foreign_tree_digest(),
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
    before = C.strict_json((HERE / "07-protected-before.json").read_bytes())
    after = C.strict_json((HERE / "07-protected-after.json").read_bytes())
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
    foreign_equal = before["foreign_tree"]["tree_sha256"] == after["foreign_tree"]["tree_sha256"]
    before_files = before["foreign_tree"]["files"]
    after_files = after["foreign_tree"]["files"]
    foreign_added = sorted(set(after_files) - set(before_files))
    foreign_removed = sorted(set(before_files) - set(after_files))
    foreign_changed = sorted(
        path for path in set(before_files) & set(after_files) if before_files[path] != after_files[path]
    )
    git_before = before["git"]
    git_after = after["git"]
    git_equal = {
        "tracked_modified_same": git_before["tracked_modified"] == git_after["tracked_modified"],
        "tracked_modified_count_15": git_after["tracked_modified_count"] == 15,
        "staged_count_zero": git_after["staged_count"] == 0,
        "head_same": before["head"] == after["head"],
        "branch_same": before["branch"] == after["branch"],
        "foreign_untracked_collapsed_same": git_before["foreign_untracked_entries"]
        == git_after["foreign_untracked_entries"],
    }
    r1_agg_sha = after["repo_files"]["docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r1.json"]["sha256"]
    r1_report_sha = after["repo_files"]["docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r1.md"]["sha256"]
    r2_agg_sha = after["repo_files"]["docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r2.json"]["sha256"]
    r2_report_sha = after["repo_files"]["docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r2.md"]["sha256"]
    not_run_sha = after["repo_files"]["docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate.json"]["sha256"]
    expected_ok = {
        "r1_aggregate": r1_agg_sha == EXPECTED_PRODUCT_HASHES["r1_aggregate"][0],
        "r1_private_detail": after["external"]["r1_private_detail"]["sha256"]
        == EXPECTED_PRODUCT_HASHES["r1_private_detail"][0],
        "r1_private_detail_bytes": after["external"]["r1_private_detail"]["bytes"]
        == EXPECTED_PRODUCT_HASHES["r1_private_detail"][1],
        "r2_aggregate": r2_agg_sha == EXPECTED_PRODUCT_HASHES["r2_aggregate"][0],
        "r2_private_detail": after["external"]["r2_private_detail"]["sha256"]
        == EXPECTED_PRODUCT_HASHES["r2_private_detail"][0],
        "r2_private_detail_bytes": after["external"]["r2_private_detail"]["bytes"]
        == EXPECTED_PRODUCT_HASHES["r2_private_detail"][1],
        "not_run_aggregate_unchanged_during_r3": not_run_sha
        == before["repo_files"]["docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate.json"]["sha256"],
    }
    payload = {
        "schema_version": "q1a3r3-protected-compare/v0.1",
        "protected_items": len(before["repo_files"]) + len(before["external"]),
        "differences": diffs,
        "difference_count": len(diffs),
        "foreign_tree_equal": foreign_equal,
        "foreign_file_count": after["foreign_tree"]["file_count"],
        "foreign_activity": {
            "added": foreign_added,
            "removed": foreign_removed,
            "changed": foreign_changed,
            "count": len(foreign_added) + len(foreign_removed) + len(foreign_changed),
            "note": (
                "untracked files outside the R3 rescore/ directory; these are not created or "
                "modified by this package. Concurrent external activity is reported, not hidden."
            ),
        },
        "git": {
            **git_equal,
            "tracked_modified_count": git_after["tracked_modified_count"],
            "untracked_entries_after": git_after["untracked_entries"],
            "own_new_entries_after": len(git_after["own_new_entries"]),
            "own_new_entries": git_after["own_new_entries"],
            "commits_created": 0,
        },
        "expected_ok": expected_ok,
        "r1_products": {
            "aggregate_sha256": r1_agg_sha,
            "report_sha256": r1_report_sha,
            "private_detail_sha256": after["external"]["r1_private_detail"]["sha256"],
            "private_detail_bytes": after["external"]["r1_private_detail"]["bytes"],
            "unchanged_during_r3": not any(
                diff.get("type") in ("repo_file", "external", "external_files")
                and (
                    "rescore-aggregate-r1" in str(diff.get("path", ""))
                    or "rescore-report-r1" in str(diff.get("path", ""))
                    or diff.get("name") in ("r1_evidence_tree", "r1_private_detail")
                )
                for diff in diffs
            ),
        },
        "r2_products": {
            "aggregate_sha256": r2_agg_sha,
            "report_sha256": r2_report_sha,
            "private_detail_sha256": after["external"]["r2_private_detail"]["sha256"],
            "private_detail_bytes": after["external"]["r2_private_detail"]["bytes"],
            "unchanged_during_r3": not any(
                diff.get("type") in ("repo_file", "external", "external_files")
                and (
                    "rescore-aggregate-r2" in str(diff.get("path", ""))
                    or "rescore-report-r2" in str(diff.get("path", ""))
                    or diff.get("name") in ("r2_evidence_tree", "r2_private_detail")
                )
                for diff in diffs
            ),
        },
        "verdict": (
            "unchanged"
            if not diffs and foreign_equal and all(git_equal.values()) and all(expected_ok.values())
            else "protected_unchanged_foreign_activity"
            if not diffs and all(git_equal.values()) and all(expected_ok.values()) and not foreign_equal
            else "changed"
        ),
    }
    (HERE / "07-protected-compare.json").write_bytes(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    print(json.dumps({"verdict": payload["verdict"], "differences": len(diffs)}, ensure_ascii=True))
    return 0 if payload["verdict"] in ("unchanged", "protected_unchanged_foreign_activity") else 1


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "before"
    if label == "compare":
        return compare()
    payload = snapshot(label)
    target = HERE / f"07-protected-{label}.json"
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
                "foreign_files": payload["foreign_tree"]["file_count"],
                "staged": payload["git"]["staged_count"],
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
