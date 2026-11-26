"""Q1a-3-R2 保护件快照（before/after 逐项 SHA256）+ 仓库状态摘要。

用法：
    python 04-protected-snapshot.py before
    python 04-protected-snapshot.py after
    python 04-protected-snapshot.py compare

保护对象：
- 仓内冻结件：C 冻结、Q1a-1/1b 模块与契约、受控入口、manifest/source-map/scenario、
  T207-CUSTODY-V2/V3 acceptance/aggregate、Q1a 各阶段 receipt、旧 run binding。
- 外部树：旧 run 树（卡/evidence/seal/case-plan/台账/GO 均在树内）、holdout 根、custody。
- 合同密文。
- R1 产物（aggregate/report/evidence-r1 树）与更早 NOT-RUN 产物
  （aggregate/report/evidence 树）——**只读保护，不改不删**。

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

import _common_r2 as C  # noqa: E402

RESCORE = HERE.parent
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
    # R1 产物（只读保护）
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r1.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r1.md",
    # 更早 NOT-RUN 产物（只读保护）
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report.md",
]
EXTERNAL_DIRS = {
    "old_run_tree": C.OLD_RUN,
    "holdout_root": C.HOLDOUT_ROOT,
    "custody_annotations": C.CUSTODY,
    "r1_evidence_tree": RESCORE / "evidence-r1",
    "not_run_evidence_tree": RESCORE / "evidence",
}
EXPECTED_PRODUCT_HASHES = {
    "r1_aggregate": ("605c89cb74ffa29152cf701f2e7dbe7fa9bebc78bc3e3a800378aba9b1668652", 31836),
    "r1_private_detail": ("2f6f4d85026d4b3fb654e17f9ebbb0baac923dd93dc6fa326bb9325fdd69dacc", 74488),
}
PRIVATE_PATHS = {
    "r1_private_detail": C.OUT_PRIVATE_DIR / "rescore-detail-r1.fernet",
    "r2_private_detail": C.OUT_PRIVATE_DIR / "rescore-detail-r2.fernet",
}
OWN_PREFIXES = (
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r2/",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r2.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r2.md",
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
    external["contract_ciphertext"] = {
        "root": str(C.CONTRACT_CIPHER),
        "sha256": C.sha256_hex(C.CONTRACT_CIPHER.read_bytes()),
        "bytes": C.CONTRACT_CIPHER.stat().st_size,
    }
    external["r1_private_detail"] = {
        "root": str(PRIVATE_PATHS["r1_private_detail"]),
        "sha256": C.sha256_hex(PRIVATE_PATHS["r1_private_detail"].read_bytes()),
        "bytes": PRIVATE_PATHS["r1_private_detail"].stat().st_size,
    }
    if PRIVATE_PATHS["r2_private_detail"].is_file():
        external["r2_private_detail"] = {
            "root": str(PRIVATE_PATHS["r2_private_detail"]),
            "sha256": C.sha256_hex(PRIVATE_PATHS["r2_private_detail"].read_bytes()),
            "bytes": PRIVATE_PATHS["r2_private_detail"].stat().st_size,
        }

    status = [line for line in _git("status", "--porcelain").splitlines() if line.strip()]
    modified = sorted(line[3:] for line in status if line[:2].strip() == "M")
    untracked = sorted(line[3:] for line in status if line.startswith("??"))
    own = [path for path in untracked if path.startswith(OWN_PREFIXES)]
    foreign = [path for path in untracked if not path.startswith(OWN_PREFIXES)]
    staged = _git("diff", "--cached", "--name-only").splitlines()
    return {
        "schema_version": "q1a3r2-protected-snapshot/v0.1",
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
    before = C.strict_json((HERE / "04-protected-before.json").read_bytes())
    after = C.strict_json((HERE / "04-protected-after.json").read_bytes())
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
    not_run_sha = after["repo_files"]["docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate.json"]["sha256"]
    r1_changed = any(
        diff.get("type") in ("repo_file", "external", "external_files")
        and (
            "rescore-aggregate-r1" in str(diff.get("path", ""))
            or "rescore-report-r1" in str(diff.get("path", ""))
            or diff.get("name") == "r1_evidence_tree"
            or diff.get("name") == "r1_private_detail"
        )
        for diff in diffs
    )
    expected_ok = {
        "r1_aggregate": r1_agg_sha == EXPECTED_PRODUCT_HASHES["r1_aggregate"][0],
        "r1_private_detail": after["external"]["r1_private_detail"]["sha256"]
        == EXPECTED_PRODUCT_HASHES["r1_private_detail"][0],
        "r1_private_detail_bytes": after["external"]["r1_private_detail"]["bytes"]
        == EXPECTED_PRODUCT_HASHES["r1_private_detail"][1],
        "not_run_aggregate_unchanged_during_r2": not_run_sha
        == before["repo_files"]["docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate.json"]["sha256"],
    }
    payload = {
        "schema_version": "q1a3r2-protected-compare/v0.1",
        "protected_items": len(before["repo_files"]) + len(before["external"]),
        "differences": diffs,
        "difference_count": len(diffs),
        "foreign_tree_equal": foreign_equal,
        "foreign_file_count": after["foreign_tree"]["file_count"],
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
            "unchanged_during_r2": not r1_changed,
        },
        "verdict": "unchanged"
        if not diffs and foreign_equal and all(git_equal.values()) and all(expected_ok.values())
        else "changed",
    }
    (HERE / "04-protected-compare.json").write_bytes(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    print(json.dumps({"verdict": payload["verdict"], "differences": len(diffs)}, ensure_ascii=True))
    return 0 if payload["verdict"] == "unchanged" else 1


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "before"
    if label == "compare":
        return compare()
    payload = snapshot(label)
    target = HERE / f"04-protected-{label}.json"
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
