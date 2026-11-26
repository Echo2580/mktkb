"""C1-P1-IMPL independent verification: start-of-round preservation snapshot.

Writes a baseline (hashes + git state) that the end-of-round probe re-reads.
Read-only: never writes outside p1-impl/independent/out.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]
OUT = Path(__file__).resolve().parent / "out"
REPAIR = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "Q1A-EVAL-REPAIR"

TARGETS = (
    "backend/src/mktkb/evaluation/p2_stale_version_state.py",
    "backend/tests/evaluation/test_p2_stale_version_state.py",
    "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py",
    "backend/tests/evaluation/test_p2_evidence_axes_adapter_v2.py",
    "docs/evaluation/p2-stale-source-criterion-v1.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/independent-review.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/review-aggregate.json",
)

# The task's boundary forbids reading custody sessions / private keys / .env.
SENSITIVE_MARKERS = (
    ".env",
    ".fernet",
    "secret",
    "credential",
    "custody",
    "runbook",
    "private",
    "/key",
    "\\key",
    "holdout-private",
)


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


def is_sensitive(rel: str) -> bool:
    low = rel.lower().replace("\\", "/")
    return any(marker in low for marker in SENSITIVE_MARKERS)


def main() -> int:
    payload: dict = {
        "schema_version": "c1p1impl-snapshot-start/v0.1",
        "captured_at": datetime.now().astimezone().isoformat(),
        "head": git("rev-parse", "HEAD").strip(),
        "branch": git("branch", "--show-current").strip(),
        "commit_count": int(git("rev-list", "--count", "HEAD").strip()),
        "staged": [x for x in git("diff", "--cached", "--name-only").splitlines() if x.strip()],
        "status_lines": len([x for x in git("status", "--porcelain").splitlines() if x.strip()]),
        "status_lines_uall": len(
            [x for x in git("status", "--porcelain", "-uall").splitlines() if x.strip()]
        ),
        "targets": {},
        "criterion": {},
        "protected": {},
        "untracked": {"files": {}, "sensitive_skipped": [], "count": 0},
    }

    for rel in TARGETS:
        path = ROOT / rel
        payload["targets"][rel] = {
            "exists": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else None,
            "mtime_ns": path.stat().st_mtime_ns if path.is_file() else None,
            "sha256": sha256(path),
        }

    axes = json.loads(
        (REPAIR / "axes" / "evidence" / "04-protected-hashes-before.json").read_text(
            encoding="utf-8"
        )
    )
    for group in ("tracked_modified_15", "c_freeze_12", "q1a1_protected"):
        expected = axes[group]
        rows = {}
        for rel, digest in sorted(expected.items()):
            actual = sha256(ROOT / rel)
            rows[rel] = {
                "expected": digest,
                "actual": actual,
                "match": actual == digest,
            }
        payload["protected"][group] = {
            "count": len(rows),
            "mismatches": [rel for rel, row in rows.items() if not row["match"]],
            "rows": rows,
        }

    payload["criterion"] = {
        "path": "docs/evaluation/p2-stale-source-criterion-v1.md",
        "sha256": sha256(ROOT / "docs/evaluation/p2-stale-source-criterion-v1.md"),
        "p4_review_sha256": sha256(
            REPAIR / "c1-1" / "p4" / "independent-review.md"
        ),
        "p4_aggregate_sha256": sha256(
            REPAIR / "c1-1" / "p4" / "review-aggregate.json"
        ),
    }

    untracked: dict[str, dict] = {}
    sensitive: list[str] = []
    for line in git("status", "--porcelain", "-uall").splitlines():
        if not line.startswith("?? "):
            continue
        rel = line[3:].strip().replace("\\", "/")
        if rel.startswith("docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1-impl/"):
            continue
        if is_sensitive(rel):
            sensitive.append(rel)
            path = ROOT / rel
            untracked[rel] = {
                "sensitive_skipped": True,
                "bytes": path.stat().st_size if path.is_file() else None,
            }
            continue
        path = ROOT / rel
        untracked[rel] = {
            "sensitive_skipped": False,
            "bytes": path.stat().st_size if path.is_file() else None,
            "sha256": sha256(path),
        }
    payload["untracked"]["files"] = dict(sorted(untracked.items()))
    payload["untracked"]["sensitive_skipped"] = sorted(sensitive)
    payload["untracked"]["count"] = len(untracked)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "00-snapshot-start.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "head": payload["head"],
                "branch": payload["branch"],
                "staged": len(payload["staged"]),
                "untracked": payload["untracked"]["count"],
                "sensitive_skipped": len(sensitive),
                "target_hashes": {
                    Path(rel).name: row["sha256"] for rel, row in payload["targets"].items()
                },
                "protected_mismatches": {
                    group: payload["protected"][group]["mismatches"]
                    for group in payload["protected"]
                },
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
