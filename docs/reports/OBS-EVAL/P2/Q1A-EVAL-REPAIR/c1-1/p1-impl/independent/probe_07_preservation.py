"""End-of-round preservation check against out/00-snapshot-start.json.

Reads only paths already recorded in the start snapshot; sensitive-name entries
are compared by size only (never by content), per the session boundary.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
OUT = Path(__file__).resolve().parent / "out"
START = OUT / "00-snapshot-start.json"


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def main() -> int:
    start = json.loads(START.read_text(encoding="utf-8"))
    end: dict[str, Any] = {
        "schema_version": "c1p1impl-snapshot-end/v0.1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "head": git("rev-parse", "HEAD").strip(),
        "branch": git("branch", "--show-current").strip(),
        "commit_count": int(git("rev-list", "--count", "HEAD").strip()),
        "staged": [x for x in git("diff", "--cached", "--name-only").splitlines() if x.strip()],
        "tracked_modified": [
            line[3:].replace("\\", "/")
            for line in git("status", "--porcelain").splitlines()
            if line.startswith(" M ")
        ],
        "status_lines": len([x for x in git("status", "--porcelain").splitlines() if x.strip()]),
        "status_lines_uall": len(
            [x for x in git("status", "--porcelain", "-uall").splitlines() if x.strip()]
        ),
        "targets": {},
        "protected": {},
        "untracked": {"same": 0, "changed": [], "missing": [], "added_outside_own": [], "sensitive_size_changed": []},
        "own_files": [],
    }
    for rel, row in start["targets"].items():
        path = ROOT / rel
        actual = sha256(path)
        end["targets"][rel] = {
            "exists": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else None,
            "sha256": actual,
            "match": actual == row["sha256"],
        }
    for group, row in start["protected"].items():
        mismatches = []
        for rel, expected in row["rows"].items():
            if sha256(ROOT / rel) != expected["expected"]:
                mismatches.append(rel)
        end["protected"][group] = {"count": row["count"], "mismatches": mismatches}
    current: dict[str, dict[str, Any]] = {}
    for line in git("status", "--porcelain", "-uall").splitlines():
        if not line.startswith("?? "):
            continue
        rel = line[3:].strip().replace("\\", "/")
        path = ROOT / rel
        if rel.startswith("docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/"):
            end["own_files"].append(rel)
            continue
        start_row = start["untracked"]["files"].get(rel)
        if start_row is None:
            end["untracked"]["added_outside_own"].append(rel)
            continue
        if start_row.get("sensitive_skipped"):
            if path.stat().st_size != start_row.get("bytes"):
                end["untracked"]["sensitive_size_changed"].append(rel)
            continue
        current[rel] = {"sha256": sha256(path)}
        if current[rel]["sha256"] != start_row.get("sha256"):
            end["untracked"]["changed"].append(rel)
    for rel in start["untracked"]["files"]:
        if rel.startswith("docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/"):
            continue
        if not (ROOT / rel).is_file():
            end["untracked"]["missing"].append(rel)
    end["untracked"]["same"] = len(set(current) - set(end["untracked"]["changed"]))
    end["verdict"] = (
        "unchanged"
        if not (
            end["staged"]
            or end["untracked"]["changed"]
            or end["untracked"]["missing"]
            or end["untracked"]["added_outside_own"]
            or end["untracked"]["sensitive_size_changed"]
            or any(not row["match"] for row in end["targets"].values())
            or any(row["mismatches"] for row in end["protected"].values())
            or end["head"] != start["head"]
            or end["branch"] != start["branch"]
            or end["commit_count"] != start["commit_count"]
        )
        else "changed"
    )
    (OUT / "00-snapshot-end.json").write_text(json.dumps(end, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / "07-preservation.json").write_text(
        json.dumps(
            {
                "schema_version": "c1p1impl-preservation/v0.1",
                "start": str(START.relative_to(ROOT)),
                "end": str((OUT / "00-snapshot-end.json").relative_to(ROOT)),
                "head": end["head"],
                "branch": end["branch"],
                "commit_count": end["commit_count"],
                "baseline_commit_count": start["commit_count"],
                "staged_count": len(end["staged"]),
                "tracked_modified_count": len(end["tracked_modified"]),
                "tracked_modified": end["tracked_modified"],
                "targets": end["targets"],
                "protected": end["protected"],
                "untracked": {
                    **end["untracked"],
                    "baseline_count": start["untracked"]["count"],
                    "sensitive_skipped": len(start["untracked"]["sensitive_skipped"]),
                    "own_new_files": len(end["own_files"]),
                },
                "own_files": end["own_files"],
                "verdict": end["verdict"],
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "verdict": end["verdict"],
                "head_equal": end["head"] == start["head"],
                "staged": len(end["staged"]),
                "tracked_modified": len(end["tracked_modified"]),
                "target_mismatches": [rel for rel, row in end["targets"].items() if not row["match"]],
                "protected_mismatches": {group: row["mismatches"] for group, row in end["protected"].items()},
                "untracked_changed": end["untracked"]["changed"],
                "untracked_missing": end["untracked"]["missing"],
                "added_outside_own": end["untracked"]["added_outside_own"],
                "sensitive_size_changed": end["untracked"]["sensitive_size_changed"],
                "own_new_files": len(end["own_files"]),
                "same_hashed": end["untracked"]["same"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if end["verdict"] == "unchanged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
