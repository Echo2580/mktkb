"""T900 phase-2 freeze v0.2 check (read-only).

Rules:
- frozen_artifacts: SHA-256 + byte size must match exactly.
- records_append_only: current bytes >= bytes_at_freeze and
  sha256(current[:bytes_at_freeze]) == sha256_at_freeze.
Exit 2 on any drift / prefix violation / missing file.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
FREEZE = ROOT / "docs/reports/OBS-EVAL/P2/candidate-freeze.json"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    freeze = json.loads(FREEZE.read_text("utf-8"))
    missing: list[str] = []
    drift: list[dict] = []
    artifacts: list[dict] = []
    for item in freeze["frozen_artifacts"]:
        path = ROOT / item["path"]
        if not path.exists():
            missing.append(item["path"])
            artifacts.append({"path": item["path"], "status": "missing"})
            continue
        raw = path.read_bytes()
        actual_sha = sha_bytes(raw)
        ok = actual_sha == item["sha256"] and len(raw) == item["bytes"]
        if not ok:
            drift.append({
                "path": item["path"],
                "expected_sha256": item["sha256"],
                "actual_sha256": actual_sha,
                "expected_bytes": item["bytes"],
                "actual_bytes": len(raw),
            })
        artifacts.append({
            "path": item["path"],
            "expected_sha256": item["sha256"],
            "actual_sha256": actual_sha,
            "expected_bytes": item["bytes"],
            "actual_bytes": len(raw),
            "same": ok,
        })

    records: list[dict] = []
    prefix_violations: list[dict] = []
    for item in freeze["records_append_only"]:
        path = ROOT / item["path"]
        if not path.exists():
            missing.append(item["path"])
            records.append({"path": item["path"], "status": "missing"})
            continue
        raw = path.read_bytes()
        n = int(item["bytes_at_freeze"])
        prefix = raw[:n]
        prefix_sha = sha_bytes(prefix)
        current_sha = sha_bytes(raw)
        ok = len(raw) >= n and prefix_sha == item["sha256_at_freeze"]
        if not ok:
            prefix_violations.append({
                "path": item["path"],
                "bytes_at_freeze": n,
                "current_bytes": len(raw),
                "sha256_at_freeze": item["sha256_at_freeze"],
                "prefix_sha256_now": prefix_sha,
                "current_sha256": current_sha,
            })
        records.append({
            "path": item["path"],
            "bytes_at_freeze": n,
            "current_bytes": len(raw),
            "appended_bytes": max(0, len(raw) - n),
            "prefix_same": prefix_sha == item["sha256_at_freeze"],
            "current_sha256": current_sha,
            "ok": ok,
        })

    gate_path = ROOT / freeze["formal_gate"]["path"]
    gate_raw = gate_path.read_bytes() if gate_path.exists() else b""
    gate = {
        "path": freeze["formal_gate"]["path"],
        "expected_sha256": freeze["formal_gate"]["sha256"],
        "actual_sha256": sha_bytes(gate_raw),
        "expected_bytes": freeze["formal_gate"]["bytes"],
        "actual_bytes": len(gate_raw),
    }
    gate["same"] = gate["actual_sha256"] == gate["expected_sha256"] and gate["actual_bytes"] == gate["expected_bytes"]
    config_path = ROOT / freeze["gate_config"]["path"]
    config_raw = config_path.read_bytes() if config_path.exists() else b""
    config = {
        "path": freeze["gate_config"]["path"],
        "expected_sha256": freeze["gate_config"]["sha256"],
        "actual_sha256": sha_bytes(config_raw),
        "same": sha_bytes(config_raw) == freeze["gate_config"]["sha256"],
    }

    result = {
        "schema_version": freeze["schema_version"],
        "freeze_path": str(FREEZE.relative_to(ROOT)),
        "freeze_frozen_at_local": freeze["frozen_at_local"],
        "freeze_file_mtime": FREEZE.stat().st_mtime_ns,
        "artifacts_checked": len(freeze["frozen_artifacts"]),
        "artifact_drift_count": len(drift),
        "artifact_drift": drift,
        "records_checked": len(freeze["records_append_only"]),
        "prefix_violation_count": len(prefix_violations),
        "prefix_violations": prefix_violations,
        "records": records,
        "missing": missing,
        "missing_count": len(missing),
        "formal_gate": gate,
        "gate_config": config,
        "artifacts": artifacts,
    }
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out is not None:
        out.write_text(payload + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "artifacts_checked", "artifact_drift_count", "artifact_drift",
        "records_checked", "prefix_violation_count", "prefix_violations",
        "missing_count", "formal_gate", "gate_config", "records")}, ensure_ascii=False, indent=2))
    return 0 if not drift and not prefix_violations and not missing and gate["same"] and config["same"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
