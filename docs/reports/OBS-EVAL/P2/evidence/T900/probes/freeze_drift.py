"""T900 phase-2 freeze drift check (read-only).

Compares every file in candidate-freeze.json against its on-disk SHA-256 and
byte size. Emits JSON; exit code 2 when any drift or missing file is found.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
FREEZE = ROOT / "docs/reports/OBS-EVAL/P2/candidate-freeze.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    freeze = json.loads(FREEZE.read_text("utf-8"))
    rows = []
    drift = []
    missing = []
    for item in freeze["files"]:
        path = ROOT / item["path"]
        if not path.exists():
            missing.append(item["path"])
            rows.append({"path": item["path"], "status": "missing"})
            continue
        actual_sha = sha(path)
        actual_bytes = path.stat().st_size
        ok = actual_sha == item["sha256"] and actual_bytes == item["bytes"]
        if not ok:
            drift.append({
                "path": item["path"],
                "expected_sha256": item["sha256"],
                "actual_sha256": actual_sha,
                "expected_bytes": item["bytes"],
                "actual_bytes": actual_bytes,
            })
        rows.append({
            "path": item["path"],
            "expected_sha256": item["sha256"],
            "actual_sha256": actual_sha,
            "expected_bytes": item["bytes"],
            "actual_bytes": actual_bytes,
            "same": ok,
        })
    gate_path = ROOT / freeze["formal_gate"]["path"]
    gate = {
        "path": freeze["formal_gate"]["path"],
        "expected_sha256": freeze["formal_gate"]["sha256"],
        "actual_sha256": sha(gate_path) if gate_path.exists() else None,
        "expected_bytes": freeze["formal_gate"]["bytes"],
        "actual_bytes": gate_path.stat().st_size if gate_path.exists() else None,
    }
    gate["same"] = gate["expected_sha256"] == gate["actual_sha256"] and gate["expected_bytes"] == gate["actual_bytes"]
    config = ROOT / freeze["gate_config"]["path"]
    config_check = {
        "path": freeze["gate_config"]["path"],
        "expected_sha256": freeze["gate_config"]["sha256"],
        "actual_sha256": sha(config) if config.exists() else None,
        "same": config.exists() and sha(config) == freeze["gate_config"]["sha256"],
    }
    result = {
        "freeze_path": str(FREEZE.relative_to(ROOT)),
        "freeze_frozen_at_local": freeze["frozen_at_local"],
        "freeze_file_mtime": FREEZE.stat().st_mtime_ns,
        "branch_expected": freeze["branch"],
        "head_expected": freeze["head"],
        "files_checked": len(rows),
        "drift": drift,
        "missing": missing,
        "drift_count": len(drift),
        "missing_count": len(missing),
        "formal_gate": gate,
        "gate_config": config_check,
        "rows": rows,
    }
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if out is not None:
        out.write_text(payload + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "files_checked", "drift_count", "missing_count", "drift", "missing", "formal_gate", "gate_config")},
        ensure_ascii=False, indent=2))
    return 0 if not drift and not missing and gate["same"] and config_check["same"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
