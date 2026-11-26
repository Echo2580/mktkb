"""C1-P2 独立验收：受控只读快照。

只做 hash/大小/路径集合/git 状态核对，不打印任何文件内容。
外部私密项（合同密文、holdout、保管标注、旧 run 树、R1 私有明细）
只计算 SHA256 与字节数，不解密、不读取语义内容。

用法：
    python 10-snapshot.py start|end
输出：
    10-snapshot-<phase>.json
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
R2_BASELINE = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r2/04-protected-before.json"
AXES_BASELINE = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json"
OUT_DIR = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/independent"

REPO_TREE_ROOTS = {
    "not_run_evidence_tree": REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence",
    "r1_evidence_tree": REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr}")
    return completed.stdout


def file_fact(path: Path) -> dict[str, object]:
    return {"bytes": path.stat().st_size, "sha256": sha256_file(path)}


def compare_file_map(root: Path, expected: dict[str, str]) -> dict[str, object]:
    rows: dict[str, object] = {}
    missing: list[str] = []
    changed: list[str] = []
    for rel, expected_sha in expected.items():
        full = root / rel.replace("/", os.sep)
        if not full.is_file():
            missing.append(rel)
            rows[rel] = {"expected": expected_sha, "actual": None, "match": False, "bytes": None}
            continue
        actual = sha256_file(full)
        row = {
            "expected": expected_sha,
            "actual": actual,
            "match": actual == expected_sha,
            "bytes": full.stat().st_size,
        }
        rows[rel] = row
        if not row["match"]:
            changed.append(rel)
    present = {
        str(path.relative_to(root)).replace(os.sep, "/")
        for path in root.rglob("*")
        if path.is_file()
    }
    extra = sorted(present - set(expected))
    return {
        "root": str(root),
        "expected_count": len(expected),
        "present_count": len(present),
        "rows": rows,
        "missing": missing,
        "changed": changed,
        "extra": extra,
        "all_match": not missing and not changed,
    }


def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else "start"
    r2 = json.loads(R2_BASELINE.read_text(encoding="utf-8"))
    axes = json.loads(AXES_BASELINE.read_text(encoding="utf-8"))

    # ---- git ----
    head = git("rev-parse", "HEAD").strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    porcelain = [line for line in git("status", "--porcelain=v1").splitlines() if line]
    staged = sorted(line[3:] for line in porcelain if line[:2].strip() and line[0] in "MADRCU")
    tracked_modified = sorted(line[3:] for line in porcelain if line[:2] == " M")
    untracked_entries = sorted(line[3:] for line in porcelain if line[:2] == "??")
    untracked_files = sorted(git("ls-files", "--others", "--exclude-standard").splitlines())
    commit_count = int(git("rev-list", "--count", "HEAD").strip())

    # ---- 28 repo protected files（R2 基线）----
    repo_files: dict[str, object] = {}
    for rel, exp in r2["repo_files"].items():
        full = REPO / rel.replace("/", os.sep)
        actual = file_fact(full) if full.is_file() else None
        match = bool(actual and actual["sha256"] == exp["sha256"] and actual["bytes"] == exp["bytes"])
        repo_files[rel] = {"expected": exp, "actual": actual, "match": match}

    # ---- C 冻结 12（axes 基线，独立于开发自报）----
    c_freeze: dict[str, object] = {}
    for rel, expected_sha in axes["c_freeze_12"].items():
        full = REPO / rel.replace("/", os.sep)
        actual = sha256_file(full) if full.is_file() else None
        c_freeze[rel] = {"expected": expected_sha, "actual": actual, "match": actual == expected_sha}

    # ---- 15 tracked modified（axes 基线）----
    tracked15: dict[str, object] = {}
    for rel, expected_sha in axes["tracked_modified_15"].items():
        full = REPO / rel.replace("/", os.sep)
        actual = sha256_file(full) if full.is_file() else None
        tracked15[rel] = {
            "expected": expected_sha,
            "actual": actual,
            "match": actual == expected_sha,
        }

    # ---- 外部 / 保管项：只 hash 字节，不解密 ----
    external: dict[str, object] = {}
    for name, spec in r2["external"].items():
        if "files" in spec:
            root = Path(REPO_TREE_ROOTS[name]) if name in REPO_TREE_ROOTS else Path(spec["root"])
            external[name] = {
                "kind": "tree",
                **compare_file_map(root, spec["files"]),
                "baseline_bytes": spec.get("bytes"),
                "baseline_tree_sha256": spec.get("tree_sha256"),
            }
        else:
            path = Path(spec["root"])
            fact = file_fact(path) if path.is_file() else None
            external[name] = {
                "kind": "file",
                "root": str(path),
                "expected": {"sha256": spec["sha256"], "bytes": spec["bytes"]},
                "actual": fact,
                "match": bool(
                    fact and fact["sha256"] == spec["sha256"] and fact["bytes"] == spec["bytes"]
                ),
            }

    # ---- 外来 untracked：与 R2 基线逐文件 hash 对比 ----
    foreign_expected = r2["foreign_tree"]["files"]
    foreign_rows: dict[str, object] = {}
    foreign_missing: list[str] = []
    foreign_changed: list[str] = []
    for rel, expected_sha in foreign_expected.items():
        full = REPO / rel.replace("/", os.sep)
        if not full.is_file():
            foreign_missing.append(rel)
            foreign_rows[rel] = {"expected": expected_sha, "actual": None, "match": False}
            continue
        actual = sha256_file(full)
        foreign_rows[rel] = {"expected": expected_sha, "actual": actual, "match": actual == expected_sha}
        if actual != expected_sha:
            foreign_changed.append(rel)
    baseline_set = set(foreign_expected)
    added_since_baseline = sorted(set(untracked_files) - baseline_set)
    removed_since_baseline = sorted(baseline_set - set(untracked_files))

    payload = {
        "schema_version": "c1p2-independent-snapshot/v0.1",
        "phase": phase,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(REPO),
        "git": {
            "head": head,
            "branch": branch,
            "staged": staged,
            "tracked_modified": tracked_modified,
            "untracked_entries": len(untracked_entries),
            "untracked_files": len(untracked_files),
            "commit_count": commit_count,
            "baseline_axes": {
                "head": axes.get("head"),
                "branch": axes.get("branch"),
                "tracked_modified": len(axes.get("tracked_modified_15") or {}),
            },
        },
        "repo_files": {
            "count": len(repo_files),
            "mismatch": sorted(rel for rel, row in repo_files.items() if not row["match"]),
            "rows": repo_files,
        },
        "c_freeze_12": {
            "count": len(c_freeze),
            "mismatch": sorted(rel for rel, row in c_freeze.items() if not row["match"]),
            "rows": c_freeze,
        },
        "tracked_modified_15": {
            "count": len(tracked15),
            "mismatch": sorted(rel for rel, row in tracked15.items() if not row["match"]),
            "rows": tracked15,
        },
        "external": external,
        "foreign_tree": {
            "baseline_count": len(baseline_set),
            "current_untracked_files": len(untracked_files),
            "missing": foreign_missing,
            "changed": foreign_changed,
            "added_since_baseline": added_since_baseline,
            "removed_since_baseline": removed_since_baseline,
            "all_baseline_files_match": not foreign_missing and not foreign_changed,
            "rows": foreign_rows,
        },
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"10-snapshot-{phase}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    summary = {
        "phase": phase,
        "head": head,
        "branch": branch,
        "staged": len(staged),
        "tracked_modified": len(tracked_modified),
        "commit_count": commit_count,
        "repo_files_mismatch": payload["repo_files"]["mismatch"],
        "c_freeze_mismatch": payload["c_freeze_12"]["mismatch"],
        "tracked15_mismatch": payload["tracked_modified_15"]["mismatch"],
        "external": {
            name: row.get("all_match", row.get("match"))
            for name, row in external.items()
        },
        "external_detail": {
            name: {
                key: row.get(key)
                for key in ("match", "all_match", "missing", "changed", "extra", "root")
                if key in row
            }
            for name, row in external.items()
        },
        "foreign": {
            "baseline_count": len(baseline_set),
            "missing": len(foreign_missing),
            "changed": len(foreign_changed),
            "added_since_baseline": len(added_since_baseline),
            "added_sample": added_since_baseline[:40],
            "all_baseline_files_match": not foreign_missing and not foreign_changed,
        },
        "out": str(out),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
