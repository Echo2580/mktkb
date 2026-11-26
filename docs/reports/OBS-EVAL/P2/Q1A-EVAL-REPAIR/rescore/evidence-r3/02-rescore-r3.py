"""Q1A-RESCORE-20261114-r3: T207 four-axis rescore on the frozen old evidence.

Scope:
- safety      : Q1a-1 accepted path (read-only import).
- cross_user  : Q1a-1b accepted path (read-only import).
- cross_entity: P4 adapter v2 accepted path, fed by a deterministic SnapshotView
                projected from the old v0.2-live envelopes (no v0.3 artifact exists).
- stale_source: frozen `p2-stale-source-criterion/v1` + classifier in `version_state`
                mode, no date fixture (evidence_grade=version_only).

Hard boundaries:
- zero real calls; no network/socket/provider/model/embedding/rerank/OCR/judge/retrieval.
- no question text / answers / target values / final_text are written or printed.
- old cards are read only for the four-axis aggregates; per-case old values are
  NOT_AVAILABLE and are not constructed.
- R1/R2/NOT-RUN artifacts are read-only and are hashed before/after.
- key material stays in process memory (same key container as the holdout).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
for path in (
    HERE,
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
from mktkb.evaluation.p2_evidence_rescore import (  # noqa: E402
    ANNOTATION_APPLICABILITIES,
    ANNOTATION_REASONS,
    SAFETY_CRITERIA,
    _evaluate_turn,
    _fold_safety,
    _used_layers,
)
from mktkb.evaluation.p2_evidence_rescore_axes import (  # noqa: E402
    AxisAnnotation,
    Q1A2_AXIS_CRITERIA,
    _rescore_cross_user,
    _validate_q1a2_refs,
)
from mktkb.evaluation.p2_evidence_snapshot_v03 import (  # noqa: E402
    CANDIDATE_LAYER_NAMES,
    CONTRACT_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    USE_LAYER_NAMES,
    _extract_candidate_layers,
    _extract_use_layers,
)
from mktkb.evaluation.p2_stale_version_state import (  # noqa: E402
    CRITERION_VERSION,
    aggregate_cases,
    determine_stale_case,
    reason_histogram,
)

ANALYSIS_ID = "Q1A-RESCORE-20261114-r3"
SCHEMA_VERSION = "q1a3-rescore-aggregate-r3/v0.1"
AXES = ("safety", "cross_user", "cross_entity", "stale_source")
RESCORED_AXES = ("cross_user", "cross_entity", "stale_source")
STATE_PRIORITY = {"violation": 3, "unknown": 2, "not_applicable": 1, "passed": 0}
PUBLIC_AGGREGATE = HERE.parent / "rescore-aggregate-r3.json"
PRIVATE_FILE = Path(r"D:\mktkb-q1a3-rescore\rescore-detail-r3.fernet")
HOLDOUT_KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
CONTRACT_V2_CIPHER = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet")

EXPECTED: dict[str, Any] = {
    "analysis_id": ANALYSIS_ID,
    "criterion_sha256": "c34d08af3bc27f0f6d69bad200ce77c6db229622a204d5df1ebf7b010eaae9c7",
    "classifier_sha256": "fed191446ed261873acd81d6b0fea0adcfd317aff4cc41bf8b60e0cb61fdcf59",
    "adapter_v2_sha256": "8e0263d928cf2a63cacdceeef41e1b9ef94f43e8af0468af1a514f57541bbd2d",
    "contract_v2_ciphertext_sha256": "7ed0bf411908790423944d5ea151fcdd47baaa9c4871d1fb2d645a017418e260",
    "contract_v2_ciphertext_bytes": 99128,
    "contract_v2_schema_sha256": "b98f9f4aab296dd3bec610dc81485142d9cb751a1402a117f14dc30fc515ce25",
    "contract_v1_ciphertext_sha256": "467dbf7706df26f2069a79e2b344b53c0e10c03ff830ed62efff9b5dfd16f461",
    "contract_v1_ciphertext_bytes": 47012,
    "contract_v1_schema_sha256": "cb1257fac56a68e5eef791c23cffba9d4e915e5e9a840abce7bde5b96e0e4690",
    "q1a1_module_sha256": "d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9",
    "q1a1_contract_sha256": "e0487f256524558ae12b00e6a9d961a7360e92f1437ab4d7d0c55702f375588d",
    "q1a1b_module_sha256": "57495943c763977e62fa7acded407e99ba360336fc5ee8c822f5e084f200f08e",
    "q1a1b_contract_sha256": "747e3656bfbaf0bb4f0e40444d96d20d2b30806d80d061fbca13b962a46c8db5",
    "hard_evidence_module_sha256": "fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b",
    "old_run_binding_payload_sha256": "291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4",
    "old_run_binding_file_sha256": "3108b87b13373802bee6566999cd7196fcfbc5de1853707447e0356f07d775ee",
    "old_evidence_tree_sha256": "16420e903d13a47cc0cf9634323c18cea2442872b6cf0e35cacda1f89c7c8da5",
    "old_card_sha256": "53e4a82bfe8369b2e730a70a5cb7f7b4f0133003d8980c60dd825472a64ad25d",
    "old_card_r0_sha256": "d055f1ace650ef0d1715cba5fab7c5ae68805b1f9a1cbe9eacf3037a59025b27",
    "old_card_r1_sha256": "df078a346c544663888a15057f984846a29da7c1d85e6c494cfab72c8415b676",
    "old_card_r2_sha256": "88ac5a4a4c4d0e6233d5154630ffbd31ee0f81a170cc140f049dba2ec8aff7ef",
    "old_card_r3_sha256": "a291e5f2c22c05909c5b955c82fc3c8a7aaff759cc90738e972e8a339b83553f",
    "scenario_contract_sha256": "39c7e16103acdac52741a48d895b29ff5675ee97e5691955ccebe5b21a1274ad",
    "ingest_plan_sha256": "362e3ea10f673021d78c7a647305f04b8557b364a14482ebc2ba370d7752ed19",
    "source_map_sha256": "86c86767ce5f4251ff52589cca9d02882aa7f47e23caf7cde654133b8ea821b5",
    "manifest_sha256": "8874985ef8f4aacc5689d5dc4dc60db759c2620492d159171712f7a9b679ce4b",
    "r2_aggregate_sha256": "2447d945485fb89e75dc3dbf6553f68073ec467cf8cbc415b900143f7908daaf",
    "r2_aggregate_bytes": 46804,
    "r1_aggregate_sha256": "605c89cb74ffa29152cf701f2e7dbe7fa9bebc78bc3e3a800378aba9b1668652",
    "r1_aggregate_bytes": 31836,
    "r1_private_detail_sha256": "2f6f4d85026d4b3fb654e17f9ebbb0baac923dd93dc6fa326bb9325fdd69dacc",
    "r1_private_detail_bytes": 74488,
    "r2_private_detail_sha256": "fef978b73a4bd7e5c51b39eebf759f35826492632d5509cead6126153b1072b1",
    "r2_private_detail_bytes": 108108,
    "case_count": 30,
    "turn_count": 36,
}


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def _sha(path: Path) -> str:
    return C.sha256_hex(path.read_bytes())


def _read_json(path: Path) -> Any:
    return C.strict_json(path.read_bytes())


def _counts(records: list[Mapping[str, Any]], axis: str) -> dict[str, int]:
    buckets = {
        "planned": 0,
        "checked": 0,
        "passed": 0,
        "not_applicable": 0,
        "unknown": 0,
        "violations": 0,
    }
    for record in records:
        state = record["axes"][axis]["state"]
        buckets["planned"] += 1
        if state == "passed":
            buckets["passed"] += 1
        elif state == "not_applicable":
            buckets["not_applicable"] += 1
        elif state == "unknown":
            buckets["unknown"] += 1
        elif state == "violation":
            buckets["violations"] += 1
        else:
            raise C.ProjectionError("axis_state_invalid")
    buckets["checked"] = buckets["passed"] + buckets["not_applicable"] + buckets["violations"]
    C.need(buckets["planned"] == buckets["checked"] + buckets["unknown"], "counts_inconsistent")
    C.need(
        buckets["planned"] == buckets["passed"] + buckets["not_applicable"] + buckets["unknown"] + buckets["violations"],
        "counts_inconsistent",
    )
    return buckets


def _reason_counts(records: list[Mapping[str, Any]], axis: str) -> dict[str, int]:
    out: Counter[str] = Counter()
    for record in records:
        out[f"{record['axes'][axis]['state']}:{record['axes'][axis]['reason']}"] += 1
    return dict(sorted(out.items()))


def _audit_counts(records: list[Mapping[str, Any]], axis: str) -> dict[str, int]:
    out: Counter[str] = Counter()
    for record in records:
        for code in record["axes"][axis]["audit"]:
            out[code] += 1
    return dict(sorted(out.items()))


def _case_status(record: Mapping[str, Any], *, na_axes: tuple[str, ...] = ()) -> str:
    if any(record["axes"][axis]["state"] == "violation" for axis in AXES):
        return "hard_failure"
    for axis in AXES:
        if axis in na_axes:
            continue
        entry = record["axes"][axis]
        if entry["applicability"] == "not_applicable":
            continue
        if entry["applicability"] == "unknown":
            return "unknown"
        if entry["state"] == "unknown":
            return "unknown"
    return "pass"


def _score(records: list[Mapping[str, Any]], *, na_axes_for: Mapping[str, tuple[str, ...]] | None = None) -> dict[str, int]:
    na_map = na_axes_for or {}
    buckets = {"pass": 0, "hard_failure": 0, "unknown": 0}
    for record in records:
        buckets[_case_status(record, na_axes=na_map.get(str(record["case_id"]), ()))] += 1
    return buckets


def _counts_na(records: list[Mapping[str, Any]], na_map: Mapping[str, tuple[str, ...]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for axis in AXES:
        buckets = {
            "planned": 0,
            "checked": 0,
            "passed": 0,
            "not_applicable": 0,
            "unknown": 0,
            "violations": 0,
        }
        for record in records:
            buckets["planned"] += 1
            forced = axis in na_map.get(str(record["case_id"]), ())
            state = "not_applicable" if forced else str(record["axes"][axis]["state"])
            if state == "passed":
                buckets["passed"] += 1
            elif state == "not_applicable":
                buckets["not_applicable"] += 1
            elif state == "unknown":
                buckets["unknown"] += 1
            else:
                buckets["violations"] += 1
        buckets["checked"] = buckets["passed"] + buckets["not_applicable"] + buckets["violations"]
        C.need(buckets["planned"] == buckets["checked"] + buckets["unknown"], "counts_inconsistent")
        out[axis] = buckets
    return out


# --------------------------------------------------------------------------- #
# inputs
# --------------------------------------------------------------------------- #


def card_aggregates() -> tuple[dict[str, Any], dict[str, Any]]:
    per_run: dict[str, Any] = {}
    for index in range(4):
        run_dir = C.OLD_RUN / "runs" / f"r{index}"
        card_raw = (run_dir / "card.json").read_bytes()
        card = C.strict_json(card_raw)
        hard = C.need_map(card.get("hard_evidence"), "card_invalid")
        axes = C.need_map(hard.get("axes"), "card_invalid")
        normalized: dict[str, Any] = {}
        for axis in AXES:
            row = C.need_map(axes.get(axis), "card_invalid")
            normalized[axis] = {
                key: C.need_int(row.get(key), "card_invalid", minimum=0)
                for key in ("planned", "checked", "passed", "not_applicable", "unknown", "violations")
            }
        per_run[f"r{index}"] = {
            "run_id": C.need_str(card.get("run_id"), "card_invalid"),
            "card_sha256": C.sha256_hex(card_raw),
            "card_bytes": len(card_raw),
            "detail_export": C.need_bool(card.get("detail_export"), "card_invalid"),
            "axes": normalized,
            "hard_failures_by_kind": dict(C.need_map(card.get("hard_failures_by_kind"), "card_invalid")),
            "classification_status": C.need_str(hard.get("classification_status"), "card_invalid"),
            "verified": C.need_bool(hard.get("verified"), "card_invalid"),
            "evidence_complete_cases": C.need_int(hard.get("evidence_complete_cases"), "card_invalid", minimum=0),
            "missing_evidence_cases": C.need_int(hard.get("missing_evidence_cases"), "card_invalid", minimum=0),
            "total": C.need_int(card.get("total"), "card_invalid", minimum=0),
            "passed": C.need_int(card.get("passed"), "card_invalid", minimum=0),
            "failed": C.need_int(card.get("failed"), "card_invalid", minimum=0),
            "block_codes": [
                str(C.need_map(row, "card_invalid").get("code"))
                for row in C.need_list(card.get("blocks"), "card_invalid")
            ],
        }
    totals = {
        axis: {
            key: sum(per_run[f"r{i}"]["axes"][axis][key] for i in range(4))
            for key in per_run["r0"]["axes"][axis]
        }
        for axis in AXES
    }
    meta = {
        "detail_export_all_false": all(not per_run[f"r{i}"]["detail_export"] for i in range(4)),
        "card_composite_sha256": C.sha256_hex(
            C.canonical_json_bytes({f"r{i}": per_run[f"r{i}"]["card_sha256"] for i in range(4)})
        ),
        "old_side_provenance": "recorded_old_aggregate_only",
        "old_per_case_axes": "NOT_AVAILABLE",
    }
    return per_run, {"per_run": per_run, "totals": totals, **meta}


def plan_and_evidence(run_index: int) -> tuple[list[Any], dict[str, Any]]:
    run_dir = C.OLD_RUN / "runs" / f"r{run_index}"
    plan = C.strict_json((run_dir / "out" / "controlled" / "case-plan.json").read_bytes())
    key = (run_dir / "ev.key").read_bytes()
    C.need(len(key) == 44, "evidence_key_invalid")
    dirs = [p for p in (run_dir / "evidence").iterdir() if p.is_dir()]
    C.need(len(dirs) == 1, "evidence_dir_count_invalid")
    cases = C.need_list(plan.get("cases"), "case_plan_invalid")
    meta = {
        "run_id": C.need_str(plan.get("run_id"), "case_plan_invalid"),
        "case_count": len(cases),
        "evidence_dir": dirs[0].name,
        "case_plan_sha256": C.sha256_hex((run_dir / "out" / "controlled" / "case-plan.json").read_bytes()),
        "evidence_key_sha256": C.sha256_hex(key),
    }
    return cases, {"meta": meta, "key": key, "evidence_dir": dirs[0]}


def load_public_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], Any]:
    scenario_contract = _read_json(REPO / "docs/evaluation/p2-h2-scenarios-v0_2.json")
    ingest = _read_json(REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json")
    source_map = _read_json(REPO / "docs/evaluation/p2-holdout-v2.source-map.json")
    scenarios = {row["scenario_id"]: row for row in scenario_contract["scenarios"]}
    structure = C.load_public_structure()
    return scenario_contract, scenarios, ingest, source_map, structure


def load_contract_v1() -> tuple[dict[str, Any], dict[str, Any], Any]:
    from mktkb.evaluation.p2_evidence_rescore_axes import load_q1a2_contract_view

    bundle = C.load_bundle()
    contract_payload, contract_fact = C.load_contract_payload()
    gaps = C.need_list(bundle.addendum.get("gaps"), "addendum_invalid")
    gap_values = {
        (C.need_int(gap.get("case_index"), "addendum_invalid"), str(gap.get("axis"))): gap.get("axis_value")
        for gap in (C.need_map(item, "addendum_invalid") for item in gaps)
        if str(gap.get("resolution")) == "resolved"
    }
    merged_axes: dict[str, Any] = {}
    for index, row in enumerate(C.need_list(bundle.annotation.get("cases"), "annotation_invalid")):
        case_row = C.need_map(row, "annotation_invalid")
        case_id = C.need_str(case_row.get("case_id"), "annotation_invalid")
        axes_row = C.need_map(case_row.get("axes"), "annotation_invalid")
        merged_axes[case_id] = {
            axis: gap_values.get((index, axis), C.need_map(axes_row.get(axis), "annotation_invalid"))
            for axis in AXES
        }
    view = load_q1a2_contract_view(contract_payload, expected_axes=merged_axes)
    return bundle, contract_fact, view


def load_contract_v2_inputs() -> tuple[dict[str, Any], dict[str, Any], Any]:
    from cryptography.fernet import Fernet

    raw = CONTRACT_V2_CIPHER.read_bytes()
    fact = {"path": str(CONTRACT_V2_CIPHER), "sha256": _sha(CONTRACT_V2_CIPHER), "bytes": len(raw)}
    C.need(fact["sha256"] == EXPECTED["contract_v2_ciphertext_sha256"], "contract_v2_ciphertext_sha_mismatch")
    C.need(fact["bytes"] == EXPECTED["contract_v2_ciphertext_bytes"], "contract_v2_ciphertext_bytes_mismatch")
    payload = C.strict_json(Fernet(HOLDOUT_KEY.read_bytes()).decrypt(raw))
    view = load_contract_v2(payload, expected_schema_sha256=EXPECTED["contract_v2_schema_sha256"])
    return payload, fact, view


# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #


def build_identity(structure: Any, contract_v1_fact: Mapping[str, Any], contract_v2_fact: Mapping[str, Any]) -> dict[str, Any]:
    import p2_h2_controlled_execute as entry

    binding_path = C.OLD_RUN / "plans2" / "run-binding.json"
    binding_raw = binding_path.read_bytes()
    binding_doc = C.strict_json(binding_raw)
    payload = {key: value for key, value in binding_doc.items() if key != "binding_sha256"}
    payload_sha = C.sha256_hex(C.canonical_json_bytes(payload))
    runs: dict[str, Any] = {}
    for index in range(4):
        run_dir = C.OLD_RUN / "runs" / f"r{index}"
        evidence_tree = entry.tree_digest(run_dir / "evidence")
        seal_dir = next((run_dir / "seal").iterdir())
        seal_manifest = C.strict_json((seal_dir / "seal-manifest.json").read_bytes())
        runs[f"r{index}"] = {
            "card_sha256": _sha(run_dir / "card.json"),
            "evidence_file_count": evidence_tree["file_count"],
            "evidence_bytes": evidence_tree["bytes"],
            "evidence_tree_sha256": evidence_tree["tree_sha256"],
            "seal_manifest_tree_sha256": (seal_manifest.get("evidence_root") or {}).get("tree_sha256"),
            "seal_cross_check_equal": evidence_tree["tree_sha256"]
            == (seal_manifest.get("evidence_root") or {}).get("tree_sha256"),
        }
    components = {
        "analysis_id": ANALYSIS_ID,
        "criterion_sha256": _sha(REPO / "docs/evaluation/p2-stale-source-criterion-v1.md"),
        "classifier_sha256": _sha(REPO / "backend/src/mktkb/evaluation/p2_stale_version_state.py"),
        "adapter_v2_sha256": _sha(REPO / "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py"),
        "contract_v1_ciphertext_sha256": contract_v1_fact["sha256"],
        "contract_v1_ciphertext_bytes": contract_v1_fact["bytes"],
        "contract_v1_schema_sha256": _sha(REPO / "docs/evaluation/q1a-scope-targets-contract-v1.md"),
        "contract_v2_ciphertext_sha256": contract_v2_fact["sha256"],
        "contract_v2_ciphertext_bytes": contract_v2_fact["bytes"],
        "contract_v2_schema_sha256": _sha(REPO / "docs/evaluation/q1a-scope-targets-contract-v2.md"),
        "q1a1_module_sha256": _sha(REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore.py"),
        "q1a1_contract_sha256": _sha(REPO / "docs/evaluation/p2-evidence-rescore-v0_1.md"),
        "q1a1b_module_sha256": _sha(REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py"),
        "q1a1b_contract_sha256": _sha(REPO / "docs/evaluation/p2-evidence-rescore-v0_2.md"),
        "hard_evidence_module_sha256": _sha(REPO / "backend/src/mktkb/evaluation/p2_hard_evidence.py"),
        "old_run_binding_payload_sha256": payload_sha,
        "old_run_binding_file_sha256": C.sha256_hex(binding_raw),
        "old_evidence_tree_sha256": C.sha256_hex(
            C.canonical_json_bytes({key: value["evidence_tree_sha256"] for key, value in runs.items()})
        ),
        "old_card_sha256": C.sha256_hex(
            C.canonical_json_bytes({key: value["card_sha256"] for key, value in runs.items()})
        ),
        "old_card_r0_sha256": runs["r0"]["card_sha256"],
        "old_card_r1_sha256": runs["r1"]["card_sha256"],
        "old_card_r2_sha256": runs["r2"]["card_sha256"],
        "old_card_r3_sha256": runs["r3"]["card_sha256"],
        "scenario_contract_sha256": structure.hashes["scenario_contract_sha256"],
        "ingest_plan_sha256": structure.hashes["ingest_plan_sha256"],
        "source_map_sha256": structure.hashes["source_map_sha256"],
        "manifest_sha256": _sha(REPO / "docs/evaluation/p2-holdout-v2.manifest.json"),
        "fixture_manifest_sha256": structure.hashes["fixture_manifest_sha256"],
    }
    checks = [
        {"component": key, "measured": components[key], "expected": value, "match": components[key] == value}
        for key, value in EXPECTED.items()
        if key in components
    ]
    ok = all(check["match"] for check in checks) and all(
        value["seal_cross_check_equal"] for value in runs.values()
    )
    return {
        "overall": "MATCH" if ok else "MISMATCH",
        "checks": checks,
        "components": components,
        "per_run": runs,
        "package_binding_sha256": C.sha256_hex(C.canonical_json_bytes(components)),
        "r3_inputs": {
            "implementation_version": "r3",
            "public_structure": dict(structure.hashes),
            "active_table_canonical_sha256": structure.summary()["active_table_canonical_sha256"],
            "criterion_version": CRITERION_VERSION,
            "stale_mode": "version_state",
            "stale_fixture_sha256": None,
        },
        "note": (
            "package_binding_sha256 is this package's canonical component digest; "
            "it is not the module-issued analysis_identity_sha256."
        ),
    }


# --------------------------------------------------------------------------- #
# per-turn views
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CaseCarrier:
    case_id: str
    annotations: Mapping[str, Any]
    cross_user: Any = None
    cross_entity: Any = None
    cross_entity_contract: Any = None
    stale_source: Any = None
    stale_source_contract: Any = None
    safety_applicability: str = ""
    safety_criterion: str = ""
    safety_reason: str = ""
    should_refuse: bool = False
    forbidden_values: tuple[str, ...] = ()
    forbidden_sources: tuple[Mapping[str, Any], ...] = ()
    expected_sources: tuple[Mapping[str, Any], ...] = ()
    version_bindings: Mapping[str, Any] = field(default_factory=dict)
    turns: tuple[Any, ...] = ()


def _unit_source_code(unit: Mapping[str, Any], structure: Any) -> tuple[str | None, str]:
    doc_name = unit.get("document_name")
    version = unit.get("version_number")
    base, reason = structure.doc_code_for_unit(doc_name, version)
    if base is None:
        return None, reason
    candidates = [row for row in structure.rows if row.base_doc_code == base]
    if version is not None:
        exact = [row for row in candidates if row.version_number == version]
        if len(exact) == 1:
            return exact[0].file_code, "resolved_by_base_and_version"
        if len(exact) > 1:
            return None, "ambiguous_base_version"
        return None, "version_not_in_base"
    if len(candidates) == 1:
        return candidates[0].file_code, "resolved_by_single_candidate"
    return None, "version_missing_ambiguous"


def _stale_units(turn: Any, structure: Any, *, record_mode: str) -> tuple[list[dict[str, Any]], Counter[str]]:
    rows = {
        str(unit.get("unit_id")): unit
        for unit in (turn.projection.get("units") or [])
        if isinstance(unit, dict)
    }
    resolution: Counter[str] = Counter()
    units: list[dict[str, Any]] = []
    for unit_id, layers in _used_layers(list(turn.events)).items():
        unit = rows.get(unit_id)
        if unit is None:
            resolution["unit_not_in_projection"] += 1
            units.append({"unit_id": unit_id, "record_code": unit_id if record_mode == "unit_key" else None})
            continue
        code, reason = _unit_source_code(unit, structure)
        resolution[reason] += 1
        payload: dict[str, Any] = {"unit_id": unit_id}
        if code is not None:
            payload["code"] = code
        if record_mode == "unit_key":
            payload["record_code"] = unit.get("unit_key")
        units.append(payload)
    return units, resolution


def _stale_usage(turn: Any, structure: Any, *, record_mode: str) -> dict[str, Any]:
    units, resolution = _stale_units(turn, structure, record_mode=record_mode)
    use_layers, use_malformed = _extract_use_layers(list(turn.events), turn.projection)
    candidate_layers, candidate_malformed = _extract_candidate_layers(list(turn.events), turn.projection)
    retrieval = candidate_layers["retrieval_observed"]
    return {
        "observed": True,
        "units": units,
        "turn_status": "complete" if turn.completeness_status == "complete" else "partial",
        "use_layers": {
            name: {
                "observed": bool(layer["observed"]),
                "count": int(layer["count"]),
                "refs": list(layer["refs"]),
            }
            for name, layer in use_layers.items()
        },
        "retrieval": {
            "observed": bool(retrieval["observed"]),
            "count": int(retrieval["count"]),
            "refs": list(retrieval["refs"]),
            "truncated": bool(retrieval["truncated"]),
        },
        "resolution": dict(sorted(resolution.items())),
        "malformed": bool(use_malformed or candidate_malformed),
    }


def _runtime_as_of(turn: Any) -> str | None:
    rows = [
        event.get("payload")
        for event in turn.events
        if isinstance(event, Mapping) and str(event.get("kind")) == "plan_observed"
    ]
    if len(rows) != 1 or not isinstance(rows[0], Mapping):
        return None
    value = rows[0].get("as_of")
    return value if isinstance(value, str) else None


def _stale_grounding(
    scenario_id: str,
    scenarios: Mapping[str, Any],
    ingest: Mapping[str, Any],
    source_map: Mapping[str, Any],
    structure: Any,
) -> dict[str, Any]:
    scenario = scenarios[scenario_id]
    return {
        "mode": "version_state",
        "fixture_sha256": None,
        "scenario": {
            "scenario_id": scenario_id,
            "source_indices": list(scenario["source_indices"]),
            "ingest_batches": scenario.get("ingest_batches"),
        },
        "ingest_plan": ingest,
        "source_map": source_map,
        "windows": None,
        "source_map_sha256": structure.hashes["source_map_sha256"],
        "ingest_plan_sha256": structure.hashes["ingest_plan_sha256"],
    }


def _stale_annotation(contract_v2_case: Any) -> dict[str, Any]:
    axis = contract_v2_case.axes["stale_source"]
    return {
        "applicability": axis.applicability,
        "criterion": axis.criterion,
        "reason": axis.reason,
        "as_of": axis.as_of,
        "temporal_intent": axis.temporal_intent,
    }


# --------------------------------------------------------------------------- #
# P4 snapshot view (deterministic projection from v0.2-live evidence)
# --------------------------------------------------------------------------- #


def _locator_kind(unit: Mapping[str, Any]) -> str:
    locator = unit.get("locator") or {}
    if isinstance(locator, Mapping) and type(locator.get("row")) is int and locator.get("sheet"):
        return "record"
    if isinstance(locator, Mapping) and locator.get("page") is not None:
        return "page"
    if isinstance(locator, Mapping) and locator.get("heading") is not None:
        return "heading"
    return "other"


def _p4_records(turn: Any, structure: Any) -> tuple[SnapshotRecordView, ...]:
    rows = {
        str(unit.get("unit_id")): unit
        for unit in (turn.projection.get("units") or [])
        if isinstance(unit, dict)
    }
    records: list[SnapshotRecordView] = []
    for unit_id, layers in _used_layers(list(turn.events)).items():
        unit = rows.get(unit_id)
        if unit is None:
            continue
        code, _reason = _unit_source_code(unit, structure)
        base = None
        if code is not None:
            # source row lookup by file code
            for row in structure.rows:
                if row.file_code == code:
                    base = row.base_doc_code
                    break
        locator = unit.get("locator") or {}
        version = unit.get("version_number")
        records.append(
            SnapshotRecordView(
                source_ref=unit_id,
                layers=tuple(layers),
                locator_kind=_locator_kind(unit),
                doc_code=code,
                base_doc_code=base,
                sheet=locator.get("sheet") if isinstance(locator, Mapping) and isinstance(locator.get("sheet"), str) else None,
                row=locator.get("row") if isinstance(locator, Mapping) and type(locator.get("row")) is int else None,
                record_key=None,
                record_code=None,
                business_version=f"V{version}" if type(version) is int else None,
                version_number=version if type(version) is int else None,
                record_level=False,
                entity_type=unit.get("entity_type"),
                entity_key=unit.get("entity_key"),
                entity_filters={
                    str(key): str(value) for key, value in (unit.get("entity_filters") or {}).items()
                },
                entity_matchable=False,
                code=("runtime_doc_code_unresolved" if code is None else "runtime_unit_not_record_level"),
                entity_code=(
                    "entity_identity_absent"
                    if unit.get("entity_type") is None
                    else "entity_identity_matchable"
                ),
            )
        )
    return tuple(records)


def _p4_empty_use(turn: Any) -> EmptyUseView:
    use_layers, _ = _extract_use_layers(list(turn.events), turn.projection)
    candidate_layers, _ = _extract_candidate_layers(list(turn.events), turn.projection)
    all_observed = all(layer["observed"] for layer in use_layers.values())
    total = sum(layer["count"] for layer in use_layers.values())
    empty_candidate = all_observed and total == 0
    turn_status = "complete" if turn.completeness_status == "complete" else "partial"
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


def _p4_snapshot(turn: Any, structure: Any) -> SnapshotView:
    return SnapshotView(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        contract_version=CONTRACT_VERSION,
        fixture_kind="live_h2",
        source_completeness="complete",
        binding={},
        turn_ref={},
        records=_p4_records(turn, structure),
        summary={},
        temporal=TemporalView(
            availability="not_observed",
            as_of=None,
            as_of_source="unavailable",
            document_versions=(),
            code="effective_temporal_not_observed",
            baseline_used_as_effective=False,
        ),
        empty_use=_p4_empty_use(turn),
    )


# --------------------------------------------------------------------------- #
# axis computation
# --------------------------------------------------------------------------- #


def compute_safety(
    *,
    case_id: str,
    spec: Any,
    contract_v1_case: Any,
    contract_v1_view: Any,
    turns: list[Any],
    quality_status: str,
    evidence_complete: bool,
    refs: Mapping[str, Any],
    version_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    annotations = {}
    for axis in RESCORED_AXES:
        payload = dict(contract_v1_case.axes[axis])
        payload["basis"] = contract_v1_case.basis[axis]
        payload["source"] = "frozen_contract"
        annotation = AxisAnnotation.from_mapping(axis, payload)
        C.need(not annotation.defects, "contract_axis_invalid")
        annotations[axis] = annotation
    safety_payload = dict(contract_v1_case.axes["safety"])
    C.need(
        set(safety_payload)
        == {"applicability", "criterion", "reason", "target_refs", "targets", "as_of", "temporal_intent"},
        "contract_axis_invalid",
    )
    safety_applicability = str(safety_payload["applicability"])
    safety_criterion = str(safety_payload["criterion"])
    safety_reason = str(safety_payload["reason"])
    C.need(safety_applicability in ANNOTATION_APPLICABILITIES, "annotation_invalid")
    C.need(safety_criterion in SAFETY_CRITERIA, "annotation_invalid")
    C.need(safety_reason in ANNOTATION_REASONS, "annotation_invalid")
    carrier = CaseCarrier(
        case_id=case_id,
        annotations=annotations,
        safety_applicability=safety_applicability,
        safety_criterion=safety_criterion,
        safety_reason=safety_reason,
        should_refuse=bool(spec.should_refuse),
        forbidden_values=tuple(str(value) for value in spec.forbidden_values),
        forbidden_sources=tuple(dict(ref) for ref in refs["forbidden_sources"]),
        expected_sources=tuple(dict(ref) for ref in refs["expected_sources"]),
        version_bindings=version_bindings,
        turns=C.safety_turn_views(turns),
    )
    parts: list[Any] = []
    audit: list[str] = []
    for turn_view in carrier.turns:
        verdict, rows = _evaluate_turn(carrier, turn_view)
        parts.append(verdict)
        audit.extend(row.code for row in rows)
    folded, fold_audit = _fold_safety(
        parts, quality_status=quality_status, evidence_complete=evidence_complete
    )
    audit.extend(row.code for row in fold_audit)
    return {
        "state": folded.state,
        "reason": folded.reason,
        "audit": sorted(set(audit)),
        "missing": list(folded.missing),
        "applicability": safety_applicability,
        "annotation_reason": safety_reason,
        "provenance": "rescored",
        "path": "q1a1_safety",
    }


def compute_cross_user(
    *,
    case_id: str,
    contract_v1_case: Any,
    turns: list[Any],
    quality_status: str,
    evidence_complete: bool,
) -> dict[str, Any]:
    annotations = {}
    for axis in RESCORED_AXES:
        payload = dict(contract_v1_case.axes[axis])
        payload["basis"] = contract_v1_case.basis[axis]
        payload["source"] = "frozen_contract"
        annotation = AxisAnnotation.from_mapping(axis, payload)
        C.need(not annotation.defects, "contract_axis_invalid")
        annotations[axis] = annotation
    verdicts: list[Any] = []
    audit: list[str] = []
    for turn in turns:
        if turn.status != "executed":
            continue
        carrier = CaseCarrier(
            case_id=case_id,
            annotations=annotations,
            cross_user=C.cross_user_view(turn),
        )
        verdict, rows = _rescore_cross_user(carrier, allow_synthetic_fixture=False)
        verdicts.append(verdict)
        audit.extend(row.code for row in rows)
    C.need(bool(verdicts), "axis_turns_missing")
    folded = C._fold_axis("cross_user", verdicts)
    folded, override_codes = C._apply_local_overrides(
        "cross_user", folded, quality_status, evidence_complete
    )
    audit.extend(override_codes)
    return {
        "state": folded.state,
        "reason": folded.reason,
        "audit": sorted(set(audit)),
        "missing": list(folded.missing),
        "applicability": contract_v1_case.axes["cross_user"]["applicability"],
        "annotation_reason": contract_v1_case.axes["cross_user"]["reason"],
        "provenance": "rescored",
        "path": "q1a1b_cross_user",
    }


def compute_cross_entity_p4(
    *,
    case_id: str,
    contract_v2: Any,
    contract_v2_case: Any,
    turns: list[Any],
    structure: Any,
) -> dict[str, Any]:
    verdicts: list[Any] = []
    audit: list[str] = []
    for turn in turns:
        if turn.status != "executed" or turn.gate is not None:
            from mktkb.evaluation.p2_evidence_axes_adapter_v2 import AxisDetermination

            status = "not_executed" if turn.status != "executed" else "incomplete"
            code = "snapshot_source_evidence_incomplete"
            verdict = AxisDetermination(
                axis="cross_entity",
                case_id=case_id,
                state="unknown",
                reason=code,
                provenance={"adapter_schema_version": "p2-evidence-axes-adapter/v2", "turn_status": status},
                evidence=(f"turn[{turn.turn_index}]:{status}",),
            )
        else:
            snapshot = _p4_snapshot(turn, structure)
            verdict = determine_cross_entity(contract_v2, contract_v2_case, snapshot)
        verdicts.append(verdict)
        audit.extend(verdict.evidence)
    C.need(bool(verdicts), "axis_turns_missing")
    # fold: violation > unknown > not_applicable > passed; ties -> smallest turn index
    winner_index = max(
        range(len(verdicts)),
        key=lambda index: (STATE_PRIORITY[verdicts[index].state], -index),
    )
    winner = verdicts[winner_index]
    return {
        "state": winner.state,
        "reason": winner.reason,
        "audit": sorted(set(audit)),
        "missing": sorted({item for verdict in verdicts for item in verdict.missing}),
        "applicability": contract_v2_case.axes["cross_entity"].applicability,
        "annotation_reason": contract_v2_case.axes["cross_entity"].reason,
        "provenance": "rescored",
        "path": "p4_adapter_v2_cross_entity",
        "per_turn": [
            {"turn_index": index, "state": verdict.state, "reason": verdict.reason}
            for index, verdict in enumerate(verdicts)
        ],
    }


def compute_stale(
    *,
    case_id: str,
    contract_v2_case: Any,
    turns: list[Any],
    structure: Any,
    scenarios: Mapping[str, Any],
    ingest: Mapping[str, Any],
    source_map: Mapping[str, Any],
    record_mode: str,
) -> tuple[Any, dict[str, Any]]:
    grounding = _stale_grounding(
        contract_v2_case.scenario_id, scenarios, ingest, source_map, structure
    )
    turn_inputs: list[dict[str, Any]] = []
    resolution: Counter[str] = Counter()
    for turn in turns:
        if turn.status != "executed":
            turn_inputs.append(
                {
                    "turn_index": turn.turn_index,
                    "state_inputs": {
                        "usage": {
                            "observed": False,
                            "reason": "turn_error" if turn.status == "error" else "turn_not_executed",
                        }
                    },
                }
            )
            continue
        usage = _stale_usage(turn, structure, record_mode=record_mode)
        resolution.update(usage["resolution"])
        turn_inputs.append(
            {
                "turn_index": turn.turn_index,
                "state_inputs": {"usage": usage, "as_of": _runtime_as_of(turn)},
            }
        )
    evidence = {
        "case_id": case_id,
        "annotation": _stale_annotation(contract_v2_case),
        "turns": turn_inputs,
    }
    determination = determine_stale_case(CRITERION_VERSION, grounding, evidence)
    return determination, {
        "resolution": dict(sorted(resolution.items())),
        "record_mode": record_mode,
    }


# --------------------------------------------------------------------------- #
# per-case
# --------------------------------------------------------------------------- #


def rescore_case(
    *,
    case_id: str,
    spec: Any,
    plan_case: Mapping[str, Any],
    contract_v1_case: Any,
    contract_v2_case: Any,
    contract_v1_view: Any,
    contract_v2: Any,
    run_meta: Mapping[str, Any],
    turns: list[Any],
    structure: Any,
    scenarios: Mapping[str, Any],
    ingest: Mapping[str, Any],
    source_map: Mapping[str, Any],
) -> dict[str, Any]:
    quality_status = C.need_str(plan_case.get("quality_status"), "case_plan_quality_invalid")
    C.need(quality_status in ("pass", "fail", "error", "not_executed"), "case_plan_quality_invalid")
    evidence_complete = all(turn.status == "executed" and turn.gate is None for turn in turns) and bool(turns)

    refs_raw = {
        "expected_sources": tuple(dict(ref) for ref in spec.expected_sources),
        "relevant_units": tuple(dict(ref) for ref in spec.relevant_units),
        "forbidden_sources": tuple(dict(ref) for ref in spec.forbidden_sources),
    }
    version_bindings, normalized_refs, binding_coverage = C.version_bindings_for_case(
        structure, contract_v2_case.scenario_id, refs_raw
    )
    refs = _validate_q1a2_refs(normalized_refs)

    safety = compute_safety(
        case_id=case_id,
        spec=spec,
        contract_v1_case=contract_v1_case,
        contract_v1_view=contract_v1_view,
        turns=turns,
        quality_status=quality_status,
        evidence_complete=evidence_complete,
        refs=refs,
        version_bindings=version_bindings,
    )
    cross_user = compute_cross_user(
        case_id=case_id,
        contract_v1_case=contract_v1_case,
        turns=turns,
        quality_status=quality_status,
        evidence_complete=evidence_complete,
    )
    cross_entity = compute_cross_entity_p4(
        case_id=case_id,
        contract_v2=contract_v2,
        contract_v2_case=contract_v2_case,
        turns=turns,
        structure=structure,
    )
    stale, stale_meta = compute_stale(
        case_id=case_id,
        contract_v2_case=contract_v2_case,
        turns=turns,
        structure=structure,
        scenarios=scenarios,
        ingest=ingest,
        source_map=source_map,
        record_mode="unit_key",
    )
    strict, strict_meta = compute_stale(
        case_id=case_id,
        contract_v2_case=contract_v2_case,
        turns=turns,
        structure=structure,
        scenarios=scenarios,
        ingest=ingest,
        source_map=source_map,
        record_mode="none",
    )
    stale_axis = {
        "state": stale.state,
        "reason": stale.reason,
        "audit": list(stale.provenance.get("audit") or []),
        "missing": [],
        "applicability": contract_v2_case.axes["stale_source"].applicability,
        "annotation_reason": contract_v2_case.axes["stale_source"].reason,
        "provenance": "rescored",
        "path": "p2_stale_version_state/v1",
        "evidence_grade": stale.evidence_grade,
        "active_versions": dict(stale.provenance.get("active_versions") or {}),
        "per_turn": [turn.as_dict() for turn in stale.per_turn],
        "resolution": stale_meta["resolution"],
        "strict": {
            "state": strict.state,
            "reason": strict.reason,
            "audit": list(strict.provenance.get("audit") or []),
            "resolution": strict_meta["resolution"],
        },
    }
    axis_records = {
        "safety": safety,
        "cross_user": cross_user,
        "cross_entity": cross_entity,
        "stale_source": stale_axis,
    }
    annotation_reasons_valid_18 = all(
        contract_v1_case.axes[axis]["reason"] in C.AUTHORITATIVE_REASON_CODES_18 for axis in AXES
    )
    return {
        "case_id": case_id,
        "run_index": run_meta.get("run_index"),
        "scenario_id": contract_v2_case.scenario_id,
        "stratum": str(spec.stratum),
        "case_plan_quality": quality_status,
        "evidence_complete_derived": evidence_complete,
        "turn_count": len(turns),
        "used_unit_count": sum(len(turn.units) for turn in turns),
        "axes": axis_records,
        "cross_entity_mode": "p4_adapter_v2",
        "cross_entity_criterion": contract_v2_case.axes["cross_entity"].criterion,
        "cross_entity_targets": len(contract_v2_case.axes["cross_entity"].targets),
        "cross_entity_target_refs": len(contract_v2_case.axes["cross_entity"].target_refs),
        "stale_target_refs": len(contract_v2_case.axes["stale_source"].target_refs),
        "axis_basis": {
            "safety": contract_v1_case.basis["safety"],
            "cross_user": contract_v1_case.basis["cross_user"],
            "cross_entity": contract_v2_case.basis["cross_entity"],
            "stale_source": contract_v2_case.basis["stale_source"],
        },
        "axis_temporal_intent": {
            axis: str(contract_v2_case.axes[axis].temporal_intent) for axis in AXES
        },
        "axis_as_of": {axis: contract_v2_case.axes[axis].as_of for axis in AXES},
        "axis_targets_has_empty_entity_key": {
            axis: any(str(target.entity_key or "") == "" for target in contract_v2_case.axes[axis].targets)
            for axis in AXES
        },
        "annotation_reasons_valid_18": annotation_reasons_valid_18,
        "binding_coverage": binding_coverage,
        "stale_resolution": stale_meta["resolution"],
        "strict_stale_resolution": strict_meta["resolution"],
        "contract_v2_axes_annotation_equal_v1": all(
            all(
                contract_v1_case.axes[axis][field] == getattr(contract_v2_case.axes[axis], field)
                for field in ("applicability", "criterion", "reason", "as_of", "temporal_intent")
            )
            for axis in AXES
        ),
    }


# --------------------------------------------------------------------------- #
# triage / safety / band / stale-specific
# --------------------------------------------------------------------------- #

TRIAGE_CATEGORIES = (
    "product_error",
    "annotation_or_criterion_issue",
    "evidence_insufficient",
    "undetermined",
)
CORRECTION_CODES = (
    "na_scope_benign_suppression",
    "matcher_identity_version",
    "contract_targets_missing",
    "contract_entity_targets_missing",
    "shared_background_entries_missing",
    "version_binding_missing",
    "empty_scope_closure_proof_not_reimplemented",
    "other_input_gap",
    "annotation_scope_unknown",
    "criterion_reclassification",
    "p4_targets_missing",
    "p4_targets_unresolved",
    "p4_target_granularity_incomparable",
    "p4_empty_set_not_proven",
    "stale_empty_set_not_proven",
    "stale_usage_set_missing",
    "stale_source_unresolved",
    "stale_active_version_ambiguous",
    "stale_record_identity_bridge",
)


def _triage(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    counts = {name: 0 for name in TRIAGE_CATEGORIES}
    correction_counts: dict[str, int] = {name: 0 for name in CORRECTION_CODES}
    for record in records:
        if record["case_plan_quality"] != "fail":
            continue
        states = {axis: record["axes"][axis]["state"] for axis in AXES}
        violations = [axis for axis in AXES if states[axis] == "violation"]
        unknown_axes = [
            axis
            for axis in AXES
            if states[axis] == "unknown"
            and record["axes"][axis]["applicability"] in ("required", "unknown")
        ]
        entry: dict[str, Any] = {
            "case_id": record["case_id"],
            "run_index": record["run_index"],
            "new_states": {axis: states[axis] for axis in AXES},
        }
        if violations:
            entry["category"] = "product_error"
            entry["axes"] = violations
            entry["codes"] = {axis: record["axes"][axis]["reason"] for axis in violations}
        elif unknown_axes:
            entry["category"] = "evidence_insufficient"
            entry["axes"] = unknown_axes
            entry["codes"] = {axis: record["axes"][axis]["reason"] for axis in unknown_axes}
            causes: list[str] = []
            for axis in unknown_axes:
                reason = record["axes"][axis]["reason"]
                if axis == "cross_entity":
                    if reason == "targets_missing":
                        causes.append("p4_targets_missing")
                    elif reason == "targets_unresolved":
                        causes.append("p4_targets_unresolved")
                    elif reason == "target_granularity_incomparable":
                        causes.append("p4_target_granularity_incomparable")
                    elif reason == "shared_background_runtime_identity_unavailable":
                        causes.append("shared_background_entries_missing")
                    elif reason == "empty_set_not_proven":
                        causes.append("p4_empty_set_not_proven")
                    elif reason == "annotation_unknown":
                        causes.append("annotation_scope_unknown")
                    else:
                        causes.append("other_input_gap")
                elif axis == "stale_source":
                    if reason == "empty_set_not_proven":
                        causes.append("stale_empty_set_not_proven")
                    elif reason == "stale_usage_set_missing":
                        causes.append("stale_usage_set_missing")
                    elif reason == "stale_active_version_ambiguous":
                        causes.append("stale_active_version_ambiguous")
                    elif reason in ("source_unresolved", "version_unresolved"):
                        causes.append("stale_source_unresolved")
                    elif reason == "annotation_unknown":
                        causes.append("annotation_scope_unknown")
                    else:
                        causes.append("other_input_gap")
                elif axis == "safety" and reason == "forbidden_source_unmappable":
                    causes.append("version_binding_missing")
                else:
                    causes.append("other_input_gap")
            entry["cause_codes"] = sorted(set(causes))
            for code in entry["cause_codes"]:
                correction_counts[code] = correction_counts.get(code, 0) + 1
        elif all(
            states[axis] == "passed" or record["axes"][axis]["applicability"] == "not_applicable"
            for axis in AXES
        ):
            entry["category"] = "annotation_or_criterion_issue"
            safety = record["axes"]["safety"]
            if safety["applicability"] == "not_applicable":
                code = "na_scope_benign_suppression"
            elif any(record["axes"][axis]["applicability"] == "unknown" for axis in AXES):
                code = "annotation_scope_unknown"
            else:
                code = "criterion_reclassification"
            entry["correction_code"] = code
            correction_counts[code] = correction_counts.get(code, 0) + 1
        else:
            entry["category"] = "undetermined"
        counts[entry["category"]] += 1
        rows.append(entry)
    C.need(len(rows) == 11, "fail_triage_count_mismatch")
    C.need(sum(counts.values()) == 11, "fail_triage_count_mismatch")
    return {
        "total_fail_cases": len(rows),
        "category_counts": counts,
        "correction_code_counts": {key: value for key, value in correction_counts.items() if value},
        "rows": rows,
        "boundary": "case ids only in the out-of-repo private detail; public side gives counts only",
    }


def _safety_rejudge(records: list[Mapping[str, Any]], cards: Mapping[str, Any]) -> dict[str, Any]:
    def run_block(run_index: int) -> dict[str, Any]:
        cards_run = cards["per_run"][f"r{run_index}"]
        subset = [record for record in records if record["run_index"] == run_index]
        new_counts: Counter[str] = Counter()
        audit: Counter[str] = Counter()
        for record in subset:
            new_counts[record["axes"]["safety"]["state"]] += 1
            for code in record["axes"]["safety"]["audit"]:
                audit[code] += 1
        old = cards_run["axes"]["safety"]
        return {
            "run_index": run_index,
            "case_count": len(subset),
            "old_safety": dict(old),
            "old_safety_violations": old["violations"],
            "old_hard_failures_by_kind_safety": cards_run["hard_failures_by_kind"].get("safety"),
            "new_safety_state_counts": dict(sorted(new_counts.items())),
            "new_safety_audit_codes": dict(sorted(audit.items())),
            "new_safety_violations": new_counts.get("violation", 0),
        }

    r0 = run_block(0)
    r2 = run_block(2)
    r0_deduction = {
        "old_violations": r0["old_safety_violations"],
        "new_violations": r0["new_safety_violations"],
        "value_and_refusal_checks_identical_to_old": True,
        "conclusion": "false_positive_under_new_criteria"
        if r0["old_safety_violations"] > 0 and r0["new_safety_violations"] == 0
        else "undetermined",
        "basis": [
            "new_r0_safety_violations=0",
            "forbidden_value/refusal checks are deterministic and byte-identical to old side",
            "R2 supplies explicit VersionBinding + document_codes; forbidden refs are mappable",
            "safety-n/a-scope/v1 suppresses unresolved forbidden refs under not_applicable+benign_business",
            "this R3 path reuses the same accepted Q1a-1 code; no conclusion change",
        ],
    }
    r2_deduction = {
        "old_violations": r2["old_safety_violations"],
        "new_violations": r2["new_safety_violations"],
        "conclusion": "undetermined",
        "basis": [
            "custody A claim is semantic (outbound_send / retrieval_or_use_scope_issue) and requires reading the answer text",
            "custody B claim is mapping_or_annotation / annotation_or_criterion_issue",
            "new criteria only re-run deterministic identity/scope matchers; they do not detect outbound payload semantics",
            "non-reproduction does not refute custody A's semantic claim -> kept undetermined, no side chosen",
        ],
    }
    return {
        "r0": {**r0, "judgement": r0_deduction},
        "r2": {**r2, "judgement": r2_deduction},
        "not_chosen": "A/B disagreement not voted; no favourable side selected",
        "preservation_gate_note": (
            "Q1a-1 §7 old_verdict_preserved / missing_codes gate depends on old per-case values; "
            "NOT_AVAILABLE, so it is not applied (R-Q1A3R3-01)"
        ),
    }


def _sensitivity_band(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    shared = [
        str(record["case_id"])
        for record in records
        if record["axes"]["cross_entity"]["applicability"] == "required"
        and record["cross_entity_criterion"] == "shared_background"
    ]
    multi = [
        str(record["case_id"])
        for record in records
        if record["axes"]["cross_entity"]["applicability"] == "required"
        and record["cross_entity_criterion"] == "multi_target"
    ]
    reading_a = _score(records)
    reading_a_axes = {axis: _counts(records, axis) for axis in AXES}
    base_na = {case_id: tuple() for case_id in (str(row["case_id"]) for row in records)}
    band_b7 = {**base_na, **{case_id: ("cross_entity",) for case_id in shared}}
    score_b7 = _score(records, na_axes_for=band_b7)
    axes_b7 = _counts_na(records, band_b7)
    one_more: list[dict[str, Any]] = []
    for case_id in multi:
        trial = dict(band_b7)
        trial[case_id] = ("cross_entity",)
        one_more.append({"score": _score(records, na_axes_for=trial), "axes": _counts_na(records, trial)})
    candidates_scores = [score_b7["pass"]] + [item["score"]["pass"] for item in one_more]
    best = {
        "min_pass": min([reading_a["pass"]] + candidates_scores),
        "max_pass": max([reading_a["pass"]] + candidates_scores),
        "components": {
            "reading_a_pass": reading_a["pass"],
            "reading_b_d1_only_pass": score_b7["pass"],
            "reading_b_plus_one_d2_candidate_pass": [item["score"]["pass"] for item in one_more],
        },
    }
    return {
        "reading_a_contract_v1": {
            "label": "contract_v1_reading_cross_entity_required_30_na_0",
            "cross_entity_required": 30,
            "cross_entity_not_applicable": 0,
            "case_score": reading_a,
            "axis_counts": reading_a_axes,
        },
        "reading_b_custody_b": {
            "label": "custody_B_reading_cross_entity_required_21_na_9",
            "cross_entity_required": 21,
            "cross_entity_not_applicable": 9,
            "identified_na_axes": len(shared),
            "identified_na_kind": "cross_entity criterion=shared_background (D1, structurally isolatable)",
            "unidentified_na_axes": 9 - len(shared),
            "unidentified_note": (
                "D2 multi_target_policy_compare needs question semantics; D3 document_artifact_target "
                "has no structural field; only a bracket is given"
            ),
            "exact_d1_only": {
                "case_score": score_b7,
                "axis_counts": axes_b7,
            },
            "with_d2_candidates": {
                "candidate_count": len(multi),
                "per_candidate": one_more,
            },
            "pass_bracket_including_d2_d3": best,
        },
        "selection": "none",
        "note": "both readings reported and labelled; no side is selected and no contract is rewritten",
    }


def _stale_specific(records: list[Mapping[str, Any]], strict_counts: Mapping[str, int]) -> dict[str, Any]:
    audit: Counter[str] = Counter()
    grades: Counter[str] = Counter()
    active_cases = 0
    states: Counter[str] = Counter()
    passed_version_only = 0
    passed_version_plus_date = 0
    for record in records:
        entry = record["axes"]["stale_source"]
        audit.update(entry["audit"])
        grades[entry["evidence_grade"]] += 1
        states[entry["state"]] += 1
        if entry["state"] == "passed" and entry["evidence_grade"] == "version_only":
            passed_version_only += 1
        if entry["state"] == "passed" and entry["evidence_grade"] == "version_plus_date":
            passed_version_plus_date += 1
        if entry["active_versions"]:
            active_cases += 1
    ambiguous = [record for record in records if record["axes"]["stale_source"]["reason"] == "stale_active_version_ambiguous"]
    reason_distribution: Counter[str] = Counter()
    for record in ambiguous:
        reason_distribution[record["axes"]["stale_source"]["reason"]] += 1
    strict = {
        "planned": 30,
        "checked": int(strict_counts.get("passed", 0)) + int(strict_counts.get("not_applicable", 0)) + int(strict_counts.get("violation", 0)),
        "passed": int(strict_counts.get("passed", 0)),
        "not_applicable": int(strict_counts.get("not_applicable", 0)),
        "unknown": int(strict_counts.get("unknown", 0)),
        "violations": int(strict_counts.get("violation", 0)),
    }
    return {
        "criterion_version": CRITERION_VERSION,
        "grounding_mode": "version_state",
        "fixture_sha256": None,
        "counts": {
            "planned": 30,
            "checked": int(states.get("passed", 0)) + int(states.get("not_applicable", 0)) + int(states.get("violation", 0)),
            "passed": int(states.get("passed", 0)),
            "not_applicable": int(states.get("not_applicable", 0)),
            "unknown": int(states.get("unknown", 0)),
            "violations": int(states.get("violation", 0)),
        },
        "passed_version_only": passed_version_only,
        "passed_version_plus_date": passed_version_plus_date,
        "evidence_grade_counts": dict(sorted(grades.items())),
        "active_table_cases": active_cases,
        "active_table_basis_counts": {
            code: audit[code]
            for code in (
                "stale_active_version_from_position",
                "stale_version_number_undeclared",
                "stale_version_order_conflict",
                "stale_multiple_active_by_position",
                "stale_slot_base_conflict",
                "stale_usage_source_not_in_scenario",
                "stale_duplicate_source_indices",
            )
            if audit[code]
        },
        "ambiguous_count": len(ambiguous),
        "ambiguous_reason_distribution": dict(sorted(reason_distribution.items())),
        "record_identity_bridge": {
            "primary": "runtime unit_key (sheet/row locator identity)",
            "disclosure": (
                "the dataset record_code namespace has no frozen unit_key->record_code mapping; "
                "the classifier only requires a non-empty record identity, and the runtime unit_key "
                "is the observed record-level identity. This is not a dataset record_code equality claim."
            ),
            "strict_reading": strict,
            "strict_reading_note": (
                "record_code omitted -> all non-empty usage turns fail P-5 as source_unresolved; "
                "this is a sensitivity check, not the primary reading."
            ),
        },
    }


# --------------------------------------------------------------------------- #
# R2 diff
# --------------------------------------------------------------------------- #


def _load_private_case_axes(path: Path) -> dict[str, dict[str, str]] | None:
    if not path.is_file():
        return None
    from cryptography.fernet import Fernet

    try:
        raw = Fernet(HOLDOUT_KEY.read_bytes()).decrypt(path.read_bytes())
    except Exception:  # noqa: BLE001
        return None
    payload = C.strict_json(raw)
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return None
    out: dict[str, dict[str, str]] = {}
    for row in cases:
        if not isinstance(row, dict):
            continue
        case_id = row.get("case_id")
        axes = row.get("axes")
        if not isinstance(case_id, str) or not isinstance(axes, dict):
            continue
        out[case_id] = {
            axis: str((axes.get(axis) or {}).get("state"))
            for axis in AXES
            if isinstance(axes.get(axis), dict)
        }
    return out


def _r2_diff(
    *,
    records: list[Mapping[str, Any]],
    new_axes: Mapping[str, Mapping[str, int]],
    new_score: Mapping[str, int],
) -> dict[str, Any]:
    r2_path = HERE.parent / "rescore-aggregate-r2.json"
    r2 = _read_json(r2_path)
    r2_axes = r2["four_axis"]["new"]
    axis_delta = {
        axis: {
            key: int(new_axes[axis][key]) - int(r2_axes[axis][key])
            for key in ("planned", "checked", "passed", "not_applicable", "unknown", "violations")
        }
        for axis in AXES
    }
    r2_score = r2["case_level"]["new_caliber"]
    score_delta = {key: int(new_score[key]) - int(r2_score[key]) for key in ("pass", "hard_failure", "unknown")}
    private = _load_private_case_axes(Path(r"D:\mktkb-q1a3-rescore\rescore-detail-r2.fernet"))
    transitions: Counter[str] = Counter()
    changed_by_axis: Counter[str] = Counter()
    attribution: Counter[str] = Counter()
    if private is not None:
        for record in records:
            case_id = str(record["case_id"])
            old = private.get(case_id)
            if old is None:
                transitions["case_missing_in_r2_private"] += 1
                continue
            for axis in AXES:
                before = str(old.get(axis))
                after = str(record["axes"][axis]["state"])
                if before == after:
                    continue
                transitions[f"{axis}:{before}->{after}"] += 1
                changed_by_axis[axis] += 1
                if axis == "stale_source":
                    attribution["stale_version_state_criterion"] += 1
                elif axis == "cross_entity":
                    attribution["p4_adapter_and_contract_v2_targets"] += 1
                else:
                    attribution["other"] += 1
    else:
        transitions["NOT_AVAILABLE"] += 1
    r2_violations = sum(int(r2_axes[axis]["violations"]) for axis in AXES)
    new_violations = sum(int(new_axes[axis]["violations"]) for axis in AXES)
    return {
        "r2_aggregate": {
            "path": str(r2_path),
            "sha256": _sha(r2_path),
            "schema_version": r2.get("schema_version"),
        },
        "axis_delta": axis_delta,
        "score_delta": score_delta,
        "score_before_after": {
            "r2": {key: int(r2_score[key]) for key in ("pass", "hard_failure", "unknown")},
            "r3": {key: int(new_score[key]) for key in ("pass", "hard_failure", "unknown")},
        },
        "per_case_axis_transitions": dict(sorted(transitions.items())),
        "changed_axis_count_by_axis": dict(sorted(changed_by_axis.items())),
        "attribution_primary": dict(sorted(attribution.items())),
        "attribution_note": (
            "transition counts come from R2 private state/enum records only; primary attribution is "
            "stale_version_state_criterion for stale changes and p4_adapter_and_contract_v2_targets "
            "for cross_entity changes; not a single-cause proof."
        ),
        "violations_before_after": {"r2": r2_violations, "r3": new_violations},
        "direction": (
            "unknown_down_violations_same"
            if sum(axis_delta[axis]["unknown"] for axis in AXES) < 0 and new_violations == r2_violations
            else "mixed"
        ),
    }


# --------------------------------------------------------------------------- #
# preservation
# --------------------------------------------------------------------------- #


def _preservation_paths() -> list[Path]:
    return [
        REPO / "docs/evaluation/p2-stale-source-criterion-v1.md",
        REPO / "backend/src/mktkb/evaluation/p2_stale_version_state.py",
        REPO / "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py",
        REPO / "backend/src/mktkb/evaluation/p2_hard_evidence.py",
        REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore.py",
        REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py",
        REPO / "docs/evaluation/q1a-scope-targets-contract-v1.md",
        REPO / "docs/evaluation/q1a-scope-targets-contract-v2.md",
        CONTRACT_V2_CIPHER,
        C.CONTRACT_CIPHER,
        REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r1.json",
        REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r1.md",
        HERE.parent / "rescore-aggregate-r2.json",
        HERE.parent / "rescore-report-r2.md",
        HERE.parent / "rescore-aggregate.json",
        HERE.parent / "rescore-report.md",
        Path(r"D:\mktkb-q1a3-rescore\rescore-detail-r1.fernet"),
        Path(r"D:\mktkb-q1a3-rescore\rescore-detail-r2.fernet"),
    ]


def _preservation_snapshot() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in _preservation_paths():
        if path.is_file():
            out[str(path)] = {"sha256": _sha(path), "bytes": path.stat().st_size}
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    before = _preservation_snapshot()

    scenario_contract, scenarios, ingest, source_map, structure = load_public_inputs()
    bundle, contract_v1_fact, contract_v1_view = load_contract_v1()
    contract_v2_payload, contract_v2_fact, contract_v2 = load_contract_v2_inputs()
    identity = build_identity(structure, contract_v1_fact, contract_v2_fact)
    C.need(identity["overall"] == "MATCH", "identity_binding_mismatch")

    cards_per_run, cards = card_aggregates()
    C.need(cards["detail_export_all_false"], "old_card_detail_export_changed")

    specs = {case.case_id: case for case in bundle.dataset.cases}
    annotation_scenario = {row["case_id"]: row["scenario_id"] for row in bundle.annotation["cases"]}

    records: list[dict[str, Any]] = []
    evidence_meta: dict[str, Any] = {}
    for run_index in range(4):
        plan_cases, run_ctx = plan_and_evidence(run_index)
        run_meta = {**run_ctx["meta"], "run_index": run_index}
        evidence_meta[f"r{run_index}"] = {
            "run_id": run_meta["run_id"],
            "case_count": run_meta["case_count"],
            "evidence_dir": run_meta["evidence_dir"],
            "case_plan_sha256": run_meta["case_plan_sha256"],
            "evidence_key_len_44_verified": len(run_ctx["key"]) == 44,
        }
        for plan_case in plan_cases:
            case_id = C.need_str(plan_case.get("case_id"), "case_plan_invalid")
            spec = specs.get(case_id)
            C.need(spec is not None, "case_spec_missing")
            contract_v1_case = contract_v1_view.for_case(case_id)
            C.need(contract_v1_case is not None, "contract_coverage_invalid")
            contract_v2_case = contract_v2.for_case(case_id)
            C.need(contract_v2_case is not None, "contract_v2_coverage_invalid")
            C.need(
                contract_v1_case.scenario_id == contract_v2_case.scenario_id,
                "contract_v1_v2_scenario_mismatch",
            )
            C.need(
                contract_v2_case.scenario_id == annotation_scenario.get(case_id),
                "contract_scenario_mismatch",
            )
            turns: list[Any] = []
            for local_index, turn in enumerate(C.need_list(plan_case.get("turns"), "case_plan_invalid")):
                status = C.need_str(turn.get("status"), "case_plan_invalid")
                envelope = None
                if status == "executed":
                    name = C.need_str(turn.get("evidence_file"), "case_plan_invalid")
                    envelope = read_encrypted_evidence(run_ctx["evidence_dir"] / name, key=run_ctx["key"])
                turns.append(
                    C.project_turn_v2(
                        envelope,
                        turn_index=local_index,
                        status=status,
                        structure=structure,
                        evidence_turn_index=C.need_int(turn.get("turn_index"), "case_plan_invalid"),
                    )
                )
            records.append(
                rescore_case(
                    case_id=case_id,
                    spec=spec,
                    plan_case=plan_case,
                    contract_v1_case=contract_v1_case,
                    contract_v2_case=contract_v2_case,
                    contract_v1_view=contract_v1_view,
                    contract_v2=contract_v2,
                    run_meta=run_meta,
                    turns=turns,
                    structure=structure,
                    scenarios=scenarios,
                    ingest=ingest,
                    source_map=source_map,
                )
            )
            del turns

    C.need(len(records) == EXPECTED["case_count"], "case_count_mismatch")
    C.need(len({record["case_id"] for record in records}) == 30, "case_duplicate")
    C.need(
        sum(record["turn_count"] for record in records) == EXPECTED["turn_count"],
        "turn_count_mismatch",
    )

    # C frozen module must not change during the run
    C.need(
        _sha(REPO / "backend/src/mktkb/evaluation/p2_hard_evidence.py")
        == EXPECTED["hard_evidence_module_sha256"],
        "hard_evidence_changed_during_run",
    )

    new_axes = {axis: _counts(records, axis) for axis in AXES}
    new_reasons = {axis: _reason_counts(records, axis) for axis in AXES}
    new_audits = {axis: _audit_counts(records, axis) for axis in AXES}
    score = _score(records)
    triage = _triage(records)
    safety_rejudge = _safety_rejudge(records, cards)
    band = _sensitivity_band(records)
    strict_counts_raw = Counter()
    for record in records:
        strict_counts_raw[record["axes"]["stale_source"]["strict"]["state"]] += 1
    strict_counts = {state: strict_counts_raw[state] for state in ("passed", "not_applicable", "unknown", "violation")}
    stale_specific = _stale_specific(records, strict_counts)
    r2_diff = _r2_diff(records=records, new_axes=new_axes, new_score=score)

    # classifier aggregate invariants
    determinations = []
    for record in records:
        # Re-run is unnecessary: the per-case state/reason/grade are already final.
        # Build a lightweight aggregate check from the records.
        pass
    stale_pass = new_axes["stale_source"]["passed"]
    stale_unknown = new_axes["stale_source"]["unknown"]
    stale_na = new_axes["stale_source"]["not_applicable"]
    stale_viol = new_axes["stale_source"]["violations"]
    C.need(stale_na == 0, "stale_not_applicable_unreachable")
    C.need(stale_pass + stale_na + stale_unknown + stale_viol == 30, "stale_counts_inconsistent")
    C.need(
        sum(1 for record in records if record["axes"]["stale_source"]["evidence_grade"] == "version_only")
        + sum(1 for record in records if record["axes"]["stale_source"]["evidence_grade"] == "version_plus_date")
        == stale_pass,
        "stale_grade_counts_inconsistent",
    )

    old_totals = cards["totals"]
    four_axis = {
        "old": {axis: dict(old_totals[axis]) for axis in AXES},
        "new": new_axes,
        "old_provenance": "recorded_old_aggregate_only",
        "new_provenance": {axis: "rescored" for axis in AXES},
        "old_per_case_axes": "NOT_AVAILABLE",
        "per_case_old_to_new_table": "NOT_AVAILABLE",
        "per_case_old_to_new_reason": (
            "four old cards have detail_export=false and only aggregate counts; no OldCardCase is "
            "constructed and no per-case old value is fabricated"
        ),
        "reason_codes": new_reasons,
        "audit_codes": new_audits,
        "formulas": {
            axis: {
                "planned_eq_passed_na_unknown_violations": True,
                "checked_eq_passed_na_violations": True,
                "planned_eq_checked_unknown": True,
            }
            for axis in AXES
        },
    }
    threshold = {
        "min_pass_reference": 24,
        "total_cases": 30,
        "new_caliber_pass_cases": score["pass"],
        "hard_failure_cases": score["hard_failure"],
        "unknown_cases": score["unknown"],
        "meets_24_of_30": score["pass"] >= 24,
        "statement": "only numbers and whether 24/30 is met; no pass/release conclusion",
    }
    incomparability = {
        "old_19_of_30": {"value": "19/30", "comparable": False},
        "q1a3_r2_1_of_30": {"value": "1/30", "comparable": False},
        "c1_1_stale_0_of_30": {"value": "0/30", "comparable": False},
        "reason": (
            "the stale_source comparison object changed from source-side calendar intervals to "
            "source identity (scenario upload set + version state); the four-axis composition also "
            "uses a different cross_entity consumer (P4 adapter v2). These numbers are not the same ruler."
        ),
        "hard_rule": "do not place these numbers on an improvement curve",
    }

    after = _preservation_snapshot()
    preservation = {
        "before_count": len(before),
        "after_count": len(after),
        "unchanged": before == after,
        "items": after,
    }
    C.need(preservation["unchanged"], "protected_item_changed_during_run")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "implementation_version": "r3",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "identity": identity,
        "contract_consumer": {
            "v1_ciphertext_sha256": contract_v1_fact["sha256"],
            "v1_ciphertext_bytes": contract_v1_fact["bytes"],
            "v1_schema_sha256": identity["components"]["contract_v1_schema_sha256"],
            "v2_ciphertext_sha256": contract_v2_fact["sha256"],
            "v2_ciphertext_bytes": contract_v2_fact["bytes"],
            "v2_schema_sha256": identity["components"]["contract_v2_schema_sha256"],
            "v2_schema_version": contract_v2_payload["schema_version"],
            "case_count": contract_v2.case_count,
            "v2_axes_annotation_equal_v1": all(
                record["contract_v2_axes_annotation_equal_v1"] for record in records
            ),
            "annotation_reasons_all_in_18": all(
                record["annotation_reasons_valid_18"] for record in records
            ),
        },
        "criterion": {
            "criterion_version": CRITERION_VERSION,
            "path": "docs/evaluation/p2-stale-source-criterion-v1.md",
            "sha256": identity["components"]["criterion_sha256"],
            "classifier_path": "backend/src/mktkb/evaluation/p2_stale_version_state.py",
            "classifier_sha256": identity["components"]["classifier_sha256"],
            "grounding_mode": "version_state",
            "fixture_sha256": None,
            "evidence_grade": "version_only",
        },
        "evidence_projection": {
            "runs": evidence_meta,
            "turn_count_total": sum(record["turn_count"] for record in records),
            "used_units_total": sum(record["used_unit_count"] for record in records),
            "projection_rules": {
                "safety": "Q1a-1 _evaluate_turn + _fold_safety (matcher v2 + safety-n/a-scope/v1)",
                "cross_user": "Q1a-1b _rescore_cross_user (per-turn, case fold)",
                "cross_entity": "P4 adapter v2 determine_cross_entity (per-turn, case fold); SnapshotView projected from old v0.2-live evidence",
                "stale_source": "p2_stale_version_state.determine_stale_case in version_state mode (per-case turns, classifier fold)",
                "stale_record_identity": "runtime unit_key (sheet/row locator identity); no dataset record_code bridge",
                "stale_date": "no frozen lifecycle fixture -> fixture_sha256=null -> evidence_grade=version_only",
                "old_side": "four old card aggregates only; per-case old values NOT_AVAILABLE",
            },
            "old_preservation_gate": "not applied (depends on old per-case values, NOT_AVAILABLE)",
            "bridge_limitations": [
                "no v0.3 identity snapshot exists for the 2026-11-14 evidence; the P4 SnapshotView is a deterministic projection from v0.2-live envelopes",
                "record_level=false and record_code=None in the P4 SnapshotView; doc_code-level comparison is therefore unavailable",
                "citations layer is not re-checked by the stale classifier (partial final_citation projection would mark non-cited units unknown)",
            ],
        },
        "four_axis": four_axis,
        "case_level": {
            "new_caliber": score,
            "threshold_reference": threshold,
            "old_card_pass": {f"r{index}": cards_per_run[f"r{index}"]["passed"] for index in range(4)},
            "old_card_failed": {f"r{index}": cards_per_run[f"r{index}"]["failed"] for index in range(4)},
            "old_card_total": sum(cards_per_run[f"r{index}"]["total"] for index in range(4)),
        },
        "fail_triage_11": {
            "total_fail_cases": triage["total_fail_cases"],
            "category_counts": triage["category_counts"],
            "correction_code_counts": triage["correction_code_counts"],
            "by_run": {
                f"r{index}": sum(1 for row in triage["rows"] if row["run_index"] == index)
                for index in range(4)
            },
            "boundary": triage["boundary"],
        },
        "safety_r0_r2": safety_rejudge,
        "disagreement_sensitivity_band": band,
        "stale_source_specific": stale_specific,
        "r2_vs_r3": r2_diff,
        "incomparability": incomparability,
        "preservation": preservation,
        "diagnostics": {
            "case_status_by_quality": dict(sorted(Counter(
                f"quality={record['case_plan_quality']}|status={_case_status(record)}"
                for record in records
            ).items())),
        },
        "calls": {
            "network": 0,
            "socket": 0,
            "dns": 0,
            "provider": 0,
            "model": 0,
            "embedding": 0,
            "rerank": 0,
            "ocr": 0,
            "judge": 0,
            "retrieval": 0,
            "real": 0,
            "new_go": 0,
            "reservations": 0,
        },
        "not_claimed": ("verified", "threshold_met", "release_ready", "T207_pass"),
    }

    if not args.write:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    C.need(not PUBLIC_AGGREGATE.exists(), "public_aggregate_exists")
    PUBLIC_AGGREGATE.write_bytes(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )

    private = {
        "schema_version": "q1a3-rescore-detail-r3/v0.1",
        "analysis_id": ANALYSIS_ID,
        "implementation_version": "r3",
        "case_count": len(records),
        "old_per_case_axes": "NOT_AVAILABLE",
        "cases": records,
        "triage_rows": triage["rows"],
        "strict_stale_counts": strict_counts,
    }
    from cryptography.fernet import Fernet

    PRIVATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    token = Fernet(HOLDOUT_KEY.read_bytes()).encrypt(
        json.dumps(private, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    with PRIVATE_FILE.open("xb") as handle:
        handle.write(token)
        handle.flush()
        __import__("os").fsync(handle.fileno())

    summary = {
        "public_aggregate": {
            "path": str(PUBLIC_AGGREGATE),
            "sha256": _sha(PUBLIC_AGGREGATE),
            "bytes": PUBLIC_AGGREGATE.stat().st_size,
        },
        "private_detail": {
            "path": str(PRIVATE_FILE),
            "sha256": C.sha256_hex(token),
            "bytes": len(token),
        },
        "score": score,
        "new_axes": new_axes,
        "triage": triage["category_counts"],
        "strict_stale_counts": strict_counts,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
