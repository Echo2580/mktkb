"""Reviewer-side verification of the frozen candidate material on a clean checkout.

Checks, with the reviewer's own hashing:
  1. every `frozen_artifacts` entry of candidate-freeze.json (47) -> sha256/bytes/missing
  2. the two append-only ledger prefixes (sha256 over the first `bytes_at_freeze` bytes)
  3. approved gate config sha256
  4. real-NCU gate result sha256
  5. B0 admission file: clean-checkout vs working-tree bytes + the frozen
     `admission_evidence_sha256` recomputed over the normalised payload

Usage: python clean_checkout_check.py --freeze-root <REPO_WITH_FREEZE> --clean <CLEAN> --worktree <REPO> --out <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-root", required=True)
    parser.add_argument("--clean", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    args = _args()
    freeze_root = Path(args.freeze_root).resolve()
    clean = Path(args.clean).resolve()
    worktree = Path(args.worktree).resolve()
    freeze = json.loads(
        (freeze_root / "docs/reports/OBS-EVAL/P2/candidate-freeze.json").read_text("utf-8")
    )
    report: dict[str, Any] = {
        "probe": "reviewer-clean-checkout",
        "freeze_head": freeze.get("head"),
        "clean_root": str(clean),
        "worktree_root": str(worktree),
    }

    artifacts = []
    missing = 0
    mismatch = 0
    for item in freeze["frozen_artifacts"]:
        rel = item["path"]
        target = clean / rel
        exists = target.is_file()
        digest = _sha(target) if exists else None
        size = target.stat().st_size if exists else None
        ok = exists and digest == item["sha256"] and size == item.get("bytes")
        if not exists:
            missing += 1
        elif not ok:
            mismatch += 1
        artifacts.append(
            {
                "path": rel,
                "exists": exists,
                "sha256_match": digest == item["sha256"],
                "bytes_match": size == item.get("bytes"),
                "ok": ok,
            }
        )
    report["frozen_artifacts"] = {
        "total": len(artifacts),
        "verified": sum(1 for a in artifacts if a["ok"]),
        "missing": missing,
        "mismatch": mismatch,
        "rows": artifacts,
    }

    ledgers = []
    for item in freeze["records_append_only"]:
        rel = item["path"]
        prefix = int(item["bytes_at_freeze"])
        row: dict[str, Any] = {"path": rel, "prefix_bytes": prefix}
        for label, base in (("clean", clean), ("worktree", worktree)):
            target = base / rel
            if not target.is_file():
                row[label] = "missing"
                continue
            raw = target.read_bytes()
            row[f"{label}_size"] = len(raw)
            row[f"{label}_prefix_sha256"] = hashlib.sha256(raw[:prefix]).hexdigest()
            row[f"{label}_prefix_ok"] = row[f"{label}_prefix_sha256"] == item["sha256_at_freeze"]
            row[f"{label}_grew"] = len(raw) > prefix
        row["ok"] = bool(row.get("clean_prefix_ok"))
        ledgers.append(row)
    report["records_append_only"] = {
        "total": len(ledgers),
        "ok": sum(1 for r in ledgers if r["ok"]),
        "rows": ledgers,
    }

    gate_cfg = freeze["gate_config"]
    cfg_path = clean / gate_cfg["path"]
    report["approved_config"] = {
        "path": gate_cfg["path"],
        "exists": cfg_path.is_file(),
        "sha256": _sha(cfg_path) if cfg_path.is_file() else None,
        "recorded": gate_cfg["sha256"],
        "match": cfg_path.is_file() and _sha(cfg_path) == gate_cfg["sha256"],
    }

    formal = freeze["formal_gate"]
    formal_path = clean / formal["path"]
    report["formal_gate"] = {
        "path": formal["path"],
        "exists": formal_path.is_file(),
        "sha256": _sha(formal_path) if formal_path.is_file() else None,
        "recorded": formal["sha256"],
        "match": formal_path.is_file() and _sha(formal_path) == formal["sha256"],
    }

    baseline = freeze["baseline"]
    admission_rel = f"var/eval/baselines/{baseline['id']}/b0-admission.json"
    admission_clean = clean / admission_rel
    admission_worktree = worktree / admission_rel
    payload_probe: dict[str, Any] = {}
    if admission_clean.is_file():
        sys.path.insert(0, str(clean / "backend" / "src"))
        try:
            from mktkb.evaluation import p2_b0

            payload = json.loads(admission_clean.read_text(encoding="utf-8"))
            for name in dir(p2_b0):
                if "sha256" not in name.lower() or not callable(getattr(p2_b0, name)):
                    continue
                func = getattr(p2_b0, name)
                try:
                    value = func(payload)
                except Exception:
                    continue
                if isinstance(value, str):
                    payload_probe[name] = value
        except Exception as exc:  # noqa: BLE001
            payload_probe["error"] = f"{type(exc).__name__}: {exc}"[:200]
    report["b0_admission"] = {
        "path": admission_rel,
        "clean_exists": admission_clean.is_file(),
        "worktree_exists": admission_worktree.is_file(),
        "clean_sha256": _sha(admission_clean) if admission_clean.is_file() else None,
        "worktree_sha256": _sha(admission_worktree) if admission_worktree.is_file() else None,
        "byte_identical": (
            admission_clean.is_file()
            and admission_worktree.is_file()
            and admission_clean.read_bytes() == admission_worktree.read_bytes()
        ),
        "recorded_admission_evidence_sha256": baseline.get("admission_evidence_sha256"),
        "payload_digest_candidates": payload_probe,
    }

    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "frozen": [
                    report["frozen_artifacts"]["total"],
                    report["frozen_artifacts"]["verified"],
                    report["frozen_artifacts"]["missing"],
                    report["frozen_artifacts"]["mismatch"],
                ],
                "ledgers_ok": report["records_append_only"]["ok"],
                "config_match": report["approved_config"]["match"],
                "formal_gate_match": report["formal_gate"]["match"],
                "b0_identical": report["b0_admission"]["byte_identical"],
                "b0_payload_probe": payload_probe,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
