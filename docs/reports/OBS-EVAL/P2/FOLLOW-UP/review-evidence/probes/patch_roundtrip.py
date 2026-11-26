"""Reviewer-side clean-room re-application of `candidate.patch`.

Creates a throw-away git repo OUTSIDE the project (D:\\mktkb-fu-review\\patchtest), materialises
the seven pre-fix files exactly as `git cat-file blob HEAD:<path>` bytes, applies
`FOLLOW-UP/candidate.patch`, then hashes all thirteen files and compares them with
`candidate-fingerprint.json`.

Nothing inside the project repository is written or modified.

Usage: python patch_roundtrip.py --repo <PROJECT> --out <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

SCRATCH = Path(r"D:\mktkb-fu-review\patchtest")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    follow = repo / "docs/reports/OBS-EVAL/P2/FOLLOW-UP"
    fingerprint = json.loads((follow / "candidate-fingerprint.json").read_text("utf-8"))
    patch = follow / "candidate.patch"

    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    SCRATCH.mkdir(parents=True)
    init = _git(SCRATCH, "init", "-q")
    # Match the project repo's own setting (repo-local core.autocrlf=false overrides the
    # machine-wide core.autocrlf=true); otherwise the scratch apply would rewrite line endings.
    _git(SCRATCH, "config", "core.autocrlf", "false")
    report: dict = {"scratch": str(SCRATCH), "git_init_exit": init.returncode}

    modified = [f["path"] for f in fingerprint["files"] if f["status"] == "modified"]
    for rel in modified:
        blob = _git(repo, "cat-file", "blob", f"HEAD:{rel}")
        assert blob.returncode == 0, rel
        target = SCRATCH / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob.stdout)

    check = _git(SCRATCH, "apply", "--check", "-p1", "--whitespace=nowarn", str(patch))
    report["apply_check_exit"] = check.returncode
    report["apply_check_stderr"] = check.stderr.decode("utf-8", "replace")[-800:]

    applied = _git(SCRATCH, "apply", "-p1", "--whitespace=nowarn", str(patch))
    report["apply_exit"] = applied.returncode
    report["apply_stderr"] = applied.stderr.decode("utf-8", "replace")[-800:]

    rows = []
    for entry in fingerprint["files"]:
        path = SCRATCH / entry["path"]
        exists = path.is_file()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if exists else None
        rows.append(
            {
                "path": entry["path"],
                "status": entry["status"],
                "exists": exists,
                "sha256": digest,
                "expected": entry["after_sha256"],
                "byte_identical": digest == entry["after_sha256"],
            }
        )
    report["files"] = rows
    report["identical"] = sum(1 for r in rows if r["byte_identical"])
    report["total"] = len(rows)
    report["differing"] = [r["path"] for r in rows if not r["byte_identical"]]
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "apply_check": report["apply_check_exit"],
                "apply": report["apply_exit"],
                "identical": f"{report['identical']}/{report['total']}",
                "differing": report["differing"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
