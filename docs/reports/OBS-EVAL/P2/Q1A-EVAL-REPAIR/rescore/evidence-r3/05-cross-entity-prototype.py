"""R3 prototype: P4 adapter v2 `cross_entity` on old evidence (aggregate-only).

Builds the P4 `SnapshotView` deterministically from old v0.2-live envelopes:
- used units -> SnapshotRecordView (record_level=False, record_code=None)
- use-layer/candidate-layer extraction -> EmptyUseView
No case ids or values are printed.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
OLD_RUN = Path(r"D:\mktkb-p2-t207-h2-20261114")
for path in (
    REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r2",
    REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1",
    REPO / "backend/src",
    REPO / "tools",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import _common_r2 as C  # noqa: E402
from mktkb.evaluation.p2_evidence_axes_adapter_v2 import (  # noqa: E402
    EmptyUseView,
    SnapshotRecordView,
    SnapshotView,
    TemporalView,
    determine_cross_entity,
    load_contract_v2,
)
from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: E402
from mktkb.evaluation.p2_evidence_rescore import _used_layers  # noqa: E402
from mktkb.evaluation.p2_evidence_snapshot_v03 import (  # noqa: E402
    CANDIDATE_LAYER_NAMES,
    EMPTY_USE_CODES,
    SNAPSHOT_SCHEMA_VERSION,
    CONTRACT_VERSION,
    USE_LAYER_NAMES,
    _extract_candidate_layers,
    _extract_use_layers,
)

STATE_PRIORITY = {"violation": 3, "unknown": 2, "not_applicable": 1, "passed": 0}


def _locator_kind(unit: dict) -> str:
    locator = unit.get("locator") or {}
    if isinstance(locator, dict) and type(locator.get("row")) is int and locator.get("sheet"):
        return "record"
    if isinstance(locator, dict) and locator.get("page") is not None:
        return "page"
    if isinstance(locator, dict) and locator.get("heading") is not None:
        return "heading"
    return "other"


def _records(events, projection, structure):
    rows = {str(u.get("unit_id")): u for u in projection.get("units") or [] if isinstance(u, dict)}
    layers_by_unit = _used_layers(events)
    records = []
    for unit_id, layers in layers_by_unit.items():
        unit = rows.get(unit_id)
        if unit is None:
            continue
        doc_name = unit.get("document_name")
        version = unit.get("version_number")
        candidates = [r for r in structure.rows if r.product_name == doc_name]
        exact = [r for r in candidates if r.version_number == version]
        source = exact[0] if len(exact) == 1 else (candidates[0] if len(candidates) == 1 and version is None else None)
        file_code = None if source is None else source.file_code
        base_code = None if source is None else source.base_doc_code
        locator = unit.get("locator") or {}
        records.append(
            SnapshotRecordView(
                source_ref=unit_id,
                layers=tuple(layers),
                locator_kind=_locator_kind(unit),
                doc_code=file_code,
                base_doc_code=base_code,
                sheet=locator.get("sheet") if isinstance(locator.get("sheet"), str) else None,
                row=locator.get("row") if type(locator.get("row")) is int else None,
                record_key=None,
                record_code=None,
                business_version=f"V{version}" if type(version) is int else None,
                version_number=version if type(version) is int else None,
                record_level=False,
                entity_type=unit.get("entity_type"),
                entity_key=unit.get("entity_key"),
                entity_filters={str(k): str(v) for k, v in (unit.get("entity_filters") or {}).items()},
                entity_matchable=False,
                code=("runtime_doc_code_unresolved" if file_code is None else "runtime_unit_not_record_level"),
                entity_code=("entity_identity_absent" if unit.get("entity_type") is None else "entity_identity_matchable"),
            )
        )
    return tuple(records)


def _empty_use(events, projection, completeness):
    use_layers, _ = _extract_use_layers(events, projection)
    candidate_layers, _ = _extract_candidate_layers(events, projection)
    all_observed = all(layer["observed"] for layer in use_layers.values())
    total = sum(layer["count"] for layer in use_layers.values())
    empty_candidate = all_observed and total == 0
    turn_status = "complete" if completeness == "complete" else "partial"
    if turn_status != "complete":
        code = "empty_use_input_turn_partial"
    elif empty_candidate:
        code = "empty_use_input_complete_empty"
    elif total > 0:
        code = "empty_use_input_nonempty"
    else:
        code = "empty_use_input_layers_not_observed"
    return EmptyUseView(
        turn_status=turn_status,
        all_use_layers_observed=all_observed,
        empty_set_candidate=empty_candidate,
        code=code,
        use_layers=use_layers,
        candidate_layers=candidate_layers,
    )


def _snapshot(records, empty_use) -> SnapshotView:
    return SnapshotView(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        contract_version=CONTRACT_VERSION,
        fixture_kind="live_h2",
        source_completeness="complete",
        binding={},
        turn_ref={},
        records=records,
        summary={},
        temporal=TemporalView(
            availability="not_observed",
            as_of=None,
            as_of_source="unavailable",
            document_versions=(),
            code="effective_temporal_not_observed",
            baseline_used_as_effective=False,
        ),
        empty_use=empty_use,
    )


def main() -> int:
    contract_payload = json.loads(
        __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet(
            Path(r"D:\mktkb-p2-holdout\keys\v2.key").read_bytes()
        ).decrypt(Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet").read_bytes()).decode("utf-8")
    )
    contract = load_contract_v2(contract_payload)
    structure = C.load_public_structure()
    cases: list[dict] = []
    for index in range(4):
        run = OLD_RUN / "runs" / f"r{index}"
        plan = json.loads((run / "out" / "controlled" / "case-plan.json").read_bytes())
        ev_key = (run / "ev.key").read_bytes()
        ev_dir = next(p for p in (run / "evidence").iterdir() if p.is_dir())
        for plan_case in plan["cases"]:
            contract_case = contract.for_case(plan_case["case_id"])
            verdicts = []
            turns = []
            for local_index, turn in enumerate(plan_case["turns"]):
                if turn["status"] != "executed":
                    turns.append({"status": turn["status"]})
                    continue
                env = read_encrypted_evidence(ev_dir / turn["evidence_file"], key=ev_key)
                events = (env.get("capture") or {}).get("events") or []
                projection = env.get("db_projection") or {}
                records = _records(events, projection, structure)
                empty_use = _empty_use(events, projection, (env.get("completeness") or {}).get("status"))
                snapshot = _snapshot(records, empty_use)
                verdict = determine_cross_entity(contract, contract_case, snapshot)
                verdicts.append(verdict)
                turns.append({"status": "executed", "records": len(records), "state": verdict.state, "reason": verdict.reason})
            if verdicts:
                winner = max(
                    verdicts,
                    key=lambda v: STATE_PRIORITY[v.state],
                )
            else:
                winner = None
            cases.append({
                "run_index": index,
                "case_id": plan_case["case_id"],
                "state": "unknown" if winner is None else winner.state,
                "reason": "turn_not_executed" if winner is None else winner.reason,
                "turn_states": [v.state for v in verdicts],
                "turn_reasons": [v.reason for v in verdicts],
                "records": sum(t.get("records", 0) for t in turns),
            })
    out = {
        "case_count": len(cases),
        "states": dict(Counter(c["state"] for c in cases)),
        "reasons": dict(sorted(Counter(c["reason"] for c in cases).items())),
        "by_run": {
            f"r{i}": {
                "cases": sum(1 for c in cases if c["run_index"] == i),
                "states": dict(Counter(c["state"] for c in cases if c["run_index"] == i)),
                "reasons": dict(sorted(Counter(c["reason"] for c in cases if c["run_index"] == i).items())),
            }
            for i in range(4)
        },
        "records": sum(c["records"] for c in cases),
        "turn_state_counts": dict(Counter(s for c in cases for s in c["turn_states"])),
        "turn_reason_counts": dict(sorted(Counter(r for c in cases for r in c["turn_reasons"]).items())),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
