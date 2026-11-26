"""Reviewer-side byte comparison: worktree files vs `git show HEAD:<path>` blobs.

Also runs an independent targeted scan of the new public artefacts (FOLLOW-UP docs +
FU2/FU4 evidence, excluding the audit scripts) for absolute paths / key names /
restricted markers, printing COUNTS ONLY (never the matched text).

Usage: python byte_and_scan.py --root <REPO> --out <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCAN_RE = {
    "windows_abs": re.compile(r"[A-Za-z]:\\\\?[^\s\"'<>|,;]{3,}"),
    "unc": re.compile(r"\\\\\\\\[^\s\"'<>|]+"),
    "key_or_cipher_name": re.compile(r"[\w.-]+\.(?:key|fernet)\b", re.IGNORECASE),
    "env_file": re.compile(r"(?<![\w.-])\.env(\.[\w.-]+)?", re.IGNORECASE),
    "restricted_marker": re.compile(r"mktkb-p2-holdout|mktkb-p2-h2v3|p2_h2_holdout"),
}
TEXT_SUFFIXES = {
    ".json", ".jsonl", ".md", ".log", ".txt", ".yaml", ".yml", ".py", ".csv", ".ts", ".js",
}


def _git_blob_sha(root: Path, spec: str) -> str | None:
    proc = subprocess.run(
        ["git", "cat-file", "blob", spec],
        cwd=str(root),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return hashlib.sha256(proc.stdout).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()

    # 1. H2-REBUILT-CARDS: every file must be byte-identical to HEAD.
    rebuilt = root / "docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS"
    rows: list[dict[str, Any]] = []
    for path in sorted(p for p in rebuilt.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        head = _git_blob_sha(root, f"HEAD:{rel}")
        worktree = _sha(path)
        rows.append(
            {
                "path": rel,
                "worktree_sha256": worktree,
                "head_sha256": head,
                "tracked": head is not None,
                "identical": head == worktree,
            }
        )

    # 2. Independent scan of the newly delivered public artefacts.
    scan_targets = [
        root / "docs/reports/OBS-EVAL/P2/FOLLOW-UP",
    ]
    findings: list[dict[str, Any]] = []
    totals = {name: 0 for name in SCAN_RE}
    files_scanned = 0
    for base in scan_targets:
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if "review-evidence" in path.parts:
                continue
            files_scanned += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            per_file = {}
            for name, regex in SCAN_RE.items():
                count = len(regex.findall(text))
                if count:
                    per_file[name] = count
                    totals[name] += count
            if per_file:
                findings.append(
                    {"path": path.relative_to(root).as_posix(), "counts": per_file}
                )
    new_water = [
        root / "docs/reports/OBS-EVAL/P2/FOLLOW-UP/FU2",
        root / "docs/reports/OBS-EVAL/P2/FOLLOW-UP/FU4",
    ]
    new_findings: list[dict[str, Any]] = []
    new_totals = {name: 0 for name in SCAN_RE}
    new_files = 0
    for base in new_water:
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if "scripts" in path.parts:  # audit scripts must contain the literals
                continue
            new_files += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            per_file = {}
            for name, regex in SCAN_RE.items():
                count = len(regex.findall(text))
                if count:
                    per_file[name] = count
                    new_totals[name] += count
            if per_file:
                new_findings.append(
                    {"path": path.relative_to(root).as_posix(), "counts": per_file}
                )

    report = {
        "probe": "reviewer-byte-and-scan",
        "root": str(root),
        "h2_rebuilt_cards": {
            "files": rows,
            "total": len(rows),
            "identical": sum(1 for r in rows if r["identical"]),
            "tracked": sum(1 for r in rows if r["tracked"]),
        },
        "followup_scan": {
            "files_scanned": files_scanned,
            "totals": totals,
            "files_with_findings": findings,
        },
        "fu2_fu4_data_scan": {
            "files_scanned": new_files,
            "totals": new_totals,
            "files_with_findings": new_findings,
        },
    }
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "h2_rebuilt": [report["h2_rebuilt_cards"]["total"], report["h2_rebuilt_cards"]["identical"], report["h2_rebuilt_cards"]["tracked"]],
                "followup_totals": totals,
                "fu2_fu4_totals": new_totals,
                "fu2_fu4_files_scanned": new_files,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
