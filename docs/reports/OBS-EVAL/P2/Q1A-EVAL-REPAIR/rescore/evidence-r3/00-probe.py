"""R3 structural probe: contract v2 shape, old-evidence envelope shape, input hashes.

PRIVACY: prints only key names, enum/version strings, counts and SHA-256 values.
Never prints question text, answers, target values, unit ids, document names or keys.
Key material stays in process memory.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
OLD_RUN = Path(r"D:\mktkb-p2-t207-h2-20261114")
CONTRACT_V2 = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet")
KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
FORBIDDEN = ("verified", "threshold", "release")

for path in (REPO / "backend" / "src", REPO / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def shape(value, depth=0):
    """Return key/type shape only, never scalar values unless enum-ish."""
    if isinstance(value, dict):
        return {str(k): shape(v, depth + 1) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list):
        return [f"list[{len(value)}]", shape(value[0], depth + 1) if value else "empty"]
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "null"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def main() -> int:
    out: dict = {"hashes": {}, "contract_v2": {}, "envelopes": {}, "trees": {}}

    files = {
        "criterion": REPO / "docs/evaluation/p2-stale-source-criterion-v1.md",
        "classifier": REPO / "backend/src/mktkb/evaluation/p2_stale_version_state.py",
        "adapter_v2": REPO / "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py",
        "contract_v2_cipher": CONTRACT_V2,
        "contract_v2_schema": REPO / "docs/evaluation/q1a-scope-targets-contract-v2.md",
        "contract_v1_schema": REPO / "docs/evaluation/q1a-scope-targets-contract-v1.md",
        "q1a1": REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore.py",
        "q1a1b": REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py",
        "q1a1_contract": REPO / "docs/evaluation/p2-evidence-rescore-v0_1.md",
        "q1a1b_contract": REPO / "docs/evaluation/p2-evidence-rescore-v0_2.md",
        "hard_evidence": REPO / "backend/src/mktkb/evaluation/p2_hard_evidence.py",
        "scenario_v02": REPO / "docs/evaluation/p2-h2-scenarios-v0_2.json",
        "ingest_plan": REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json",
        "source_map": REPO / "docs/evaluation/p2-holdout-v2.source-map.json",
        "manifest_v2": REPO / "docs/evaluation/p2-holdout-v2.manifest.json",
        "old_run_binding": OLD_RUN / "plans2" / "run-binding.json",
    }
    for name, path in files.items():
        raw = path.read_bytes()
        out["hashes"][name] = {"sha256": sha(raw), "bytes": len(raw)}

    for index in range(4):
        run = OLD_RUN / "runs" / f"r{index}"
        out["hashes"][f"old_card_r{index}"] = {
            "sha256": sha((run / "card.json").read_bytes()),
            "bytes": (run / "card.json").stat().st_size,
        }
        ev = run / "evidence"
        out["trees"][f"r{index}"] = {
            "file_count": sum(1 for p in ev.rglob("*") if p.is_file()),
            "bytes": sum(p.stat().st_size for p in ev.rglob("*") if p.is_file()),
        }

    from cryptography.fernet import Fernet

    key = KEY.read_bytes()
    cipher = CONTRACT_V2.read_bytes()
    payload = json.loads(Fernet(key).decrypt(cipher).decode("utf-8"))
    cases = payload.get("cases") or []
    axis_counts: dict = {}
    target_shape: dict = {}
    for case in cases:
        for axis, row in (case.get("axes") or {}).items():
            key_name = (
                f"app={row.get('applicability')}|criterion={row.get('criterion')}|"
                f"reason={row.get('reason')}"
            )
            axis_counts.setdefault(axis, Counter())[key_name] += 1
            targets = row.get("targets") or []
            target_shape.setdefault(axis, Counter())[
                f"targets={len(targets)}|types={','.join(sorted({str(t.get('entity_type')) for t in targets}))}"
            ] += 1
    out["contract_v2"] = {
        "top_keys": sorted(payload),
        "schema_version": payload.get("schema_version"),
        "case_count": payload.get("case_count"),
        "bindings": {k: ("<sha256>" if len(str(v)) == 64 else str(v)) for k, v in (payload.get("bindings") or {}).items()},
        "runs": [
            {"run_index": r.get("run_index"), "scenario_id": r.get("scenario_id")}
            for r in (payload.get("runs") or [])
        ],
        "projection_keys": sorted((payload.get("projection") or {})),
        "axis_app_criterion_reason": {
            axis: {k: v for k, v in sorted(counter.items())} for axis, counter in sorted(axis_counts.items())
        },
        "axis_target_shapes": {
            axis: {k: v for k, v in sorted(counter.items())} for axis, counter in sorted(target_shape.items())
        },
        "case_axes_keys": sorted({tuple(sorted(c.get("axes") or {})) for c in cases}),
        "case_basis_keys": sorted({tuple(sorted(c.get("basis") or {})) for c in cases}),
    }

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence

    for index in range(4):
        run = OLD_RUN / "runs" / f"r{index}"
        plan = json.loads((run / "out" / "controlled" / "case-plan.json").read_bytes())
        ev_key = (run / "ev.key").read_bytes()
        ev_dir = next(p for p in (run / "evidence").iterdir() if p.is_dir())
        executed = [
            turn
            for case in plan.get("cases") or []
            for turn in (case.get("turns") or [])
            if turn.get("status") == "executed"
        ]
        sample = executed[0]
        env = read_encrypted_evidence(ev_dir / sample["evidence_file"], key=ev_key)
        projection = env.get("db_projection") or {}
        units = projection.get("units") or []
        unit_keys = sorted({k for u in units if isinstance(u, dict) for k in u})
        events = (env.get("capture") or {}).get("events") or []
        out["envelopes"][f"r{index}"] = {
            "schema_version": env.get("schema_version"),
            "top_keys": sorted(env),
            "turn_keys": sorted(env.get("turn") or {}),
            "capture_keys": sorted(env.get("capture") or {}),
            "projection_keys": sorted(projection),
            "completeness_keys": sorted(env.get("completeness") or {}),
            "completeness_status": (env.get("completeness") or {}).get("status"),
            "run_binding_present": isinstance(env.get("run_binding"), dict),
            "run_binding_keys": sorted(env.get("run_binding") or {}) if isinstance(env.get("run_binding"), dict) else [],
            "runtime_snapshot_keys": sorted(env.get("runtime_snapshot") or {}) if isinstance(env.get("runtime_snapshot"), dict) else [],
            "runtime_product_keys": sorted((env.get("runtime_snapshot") or {}).get("product_response") or {}) if isinstance(env.get("runtime_snapshot"), dict) else [],
            "runtime_use_keys": sorted((env.get("runtime_snapshot") or {}).get("retrieval_use") or {}) if isinstance(env.get("runtime_snapshot"), dict) else [],
            "unit_count": len(units),
            "unit_keys": unit_keys,
            "unit_nonnull_counts": {
                field: sum(1 for u in units if isinstance(u, dict) and u.get(field) is not None)
                for field in unit_keys
            },
            "unit_version_number_values": dict(Counter(
                int(u.get("version_number")) for u in units
                if isinstance(u, dict) and type(u.get("version_number")) is int
            )),
            "unit_version_state_values": dict(Counter(
                str(u.get("version_state")) for u in units if isinstance(u, dict)
            )),
            "unit_active_values": dict(Counter(
                str(u.get("active")) for u in units if isinstance(u, dict)
            )),
            "event_kind_counts": dict(Counter(str(e.get("kind")) for e in events if isinstance(e, dict))),
            "message_source_count": len(projection.get("message_sources") or []),
            "message_source_keys": sorted({
                k for row in (projection.get("message_sources") or []) if isinstance(row, dict) for k in row
            }),
            "plan_observed_count": sum(1 for e in events if isinstance(e, dict) and str(e.get("kind")) == "plan_observed"),
            "final_event_kinds": [
                str(e.get("kind")) for e in events[-3:] if isinstance(e, dict)
            ],
            "forbidden_token_hits": 0,
        }

    text = json.dumps(out, ensure_ascii=False, sort_keys=True)
    for token in FORBIDDEN:
        out["forbidden_token_hits"] = out.get("forbidden_token_hits", 0)
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
