"""H2 受限聚合核验（D-001 边界）：卡本体留在保管环境，只做外层核验。

输入（全部在仓库内，均为**聚合视图**，不含题干/标签/回答）：

* ``h2-composition-aggregate.json``（``p2-h2-composition-aggregate/v0.1``）：四场景聚合；
* ``cards-index.json``（``p2-h2-cards-index/v0.1``）：四张卡的**文件 SHA** 与逐卡校验结果；
* ``h2-source-proof.full.json``（``p2-release-h2-source-proof/v0.1``）：同批来源证明。

两套哈希必须分列，不可互相替代：

* ``card_file_sha256``：卡**文件**的 SHA-256（来自 cards-index，用于"拿到的就是那张卡"）；
* ``card_aggregate_sha256``：卡**内容聚合** SHA-256（= 组合 ``cards[].payload_sha256``
  = 来源证明 ``derived_card_sha256``，用于"这张卡聚合进组合的正是它"）。

阈值类字段（``thresholds_approved=false`` / ``release_ready=false`` /
``blocks=["holdout_threshold_unapproved"]`` / ``annotation.quality_readiness="BLOCKED"`` /
``annotation.runtime_axis_evidence_produced=false``）是**v0.2 组合的注解/策略元数据**：
批准阈值 ``7fa6f47a…`` 由发布门禁层单独施加，**不据此判 blocked/pending**。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .p2_release_inputs import (
    H2_SCENARIO_CASE_COUNTS,
    H2_SCENARIO_ORDER,
    H2_SCENARIO_TURNS,
    ReleaseInputs,
)
from .p2_release_model import (
    DECISION_OBSERVED,
    H2_SOURCE_PROOF_SCHEMA_VERSION,
    R_DIGEST_MISMATCH,
    R_EVIDENCE_MISSING,
    R_HARD_FAILURE,
    R_IDENTITY_MISMATCH,
    R_QUALITY_BELOW_THRESHOLD,
    R_REQUIRED_UNKNOWN,
    R_SAMPLE_BELOW_MIN,
    R_VERSION_MISMATCH,
    ReleaseRow,
    exact_keys,
    file_sha256,
    require_digest,
    require_int,
    require_text,
    row_blocked,
    row_observed,
    row_ok,
)

AGGREGATE_SCHEMA_VERSION = "p2-h2-composition-aggregate/v0.1"
CARDS_INDEX_SCHEMA_VERSION = "p2-h2-cards-index/v0.1"
APPROVED_GATE_CONFIG_HASH = "7fa6f47a445f9643eb7f2e5ae78a72411007da38a56fca1082657870b2eab094"
ORIGINAL_H2_GATE_CONFIG_HASH = "d10975732dd50616f959fde71a3ead42822b877e98c55c4367902cb053cfd2a8"

#: 组合聚合视图里必须存在的字段（多键允许，缺键即拒）。
_AGGREGATE_REQUIRED = (
    "schema_version", "kind", "total", "executed", "passed", "failed", "errors",
    "turns_planned", "turns_executed", "not_started", "status", "hard_failures",
    "hard_failures_by_kind", "required_unknowns", "non_required_unknowns", "strata",
    "axes", "cards", "verified", "threshold_met", "thresholds_approved", "release_ready",
    "blocks", "annotation", "composition_file_sha256", "aggregate_sha256",
)
_CARD_KEYS = ("scenario_id", "payload_sha256", "aggregate_sha256", "case_count",
              "turns_executed", "hard_failures", "verified")
_PROOF_KEYS = ("schema_version", "batch_id", "batch_authority", "batch_binding",
               "scenarios", "zero_call", "c25_non_required_unknown")
_PROOF_SCENARIO_KEYS = ("scenario_id", "run_id", "plan_sha256", "status", "case_count",
                        "turns_executed", "config_hash", "hard_evidence_sha256",
                        "derived_card_sha256", "original_identities", "derived_scorer")
_INDEX_KEYS = ("schema_version", "kind", "order", "cards")
_INDEX_CARD_KEYS = ("scenario_id", "case_count", "card_sha256",
                    "validate_hard_evidence_scorecard", "verified", "hard_failures")


class _H2AggregateError(ValueError):
    def __init__(self, reason: str, cause: str, detail: Mapping[str, Any] | None = None) -> None:
        super().__init__(f"{reason}: {cause}")
        self.reason = reason
        self.cause = cause
        self.detail = dict(detail or {})


def _require_keys(payload: Any, required: tuple[str, ...], what: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise _H2AggregateError(R_EVIDENCE_MISSING, f"{what}_not_object")
    missing = sorted(set(required) - set(payload))
    if missing:
        raise _H2AggregateError(R_EVIDENCE_MISSING, f"{what}_missing_fields", {"missing": missing})
    return payload


def _validate_cards_index(index: Mapping[str, Any]) -> list[dict[str, Any]]:
    if index.get("schema_version") != CARDS_INDEX_SCHEMA_VERSION or index.get("kind") != "aggregate":
        raise _H2AggregateError(R_VERSION_MISMATCH, "cards_index_schema_mismatch",
                                {"schema_version": index.get("schema_version")})
    if list(index.get("order") or ()) != list(H2_SCENARIO_ORDER):
        raise _H2AggregateError(R_IDENTITY_MISMATCH, "cards_index_order_mismatch")
    cards = index.get("cards")
    if not isinstance(cards, list) or len(cards) != len(H2_SCENARIO_ORDER):
        raise _H2AggregateError(R_SAMPLE_BELOW_MIN, "cards_index_card_count_mismatch")
    seen: list[str] = []
    rows: list[dict[str, Any]] = []
    for position, (scenario_id, item) in enumerate(zip(H2_SCENARIO_ORDER, cards)):
        row = _require_keys(item, _INDEX_CARD_KEYS, f"cards_index[{position}]")
        if row.get("scenario_id") != scenario_id:
            raise _H2AggregateError(R_IDENTITY_MISMATCH, "cards_index_scenario_order_mismatch",
                                    {"index": position, "expected": scenario_id})
        if require_int(row.get("case_count"), "cards_index.case_count", minimum=1) != \
                H2_SCENARIO_CASE_COUNTS[scenario_id]:
            raise _H2AggregateError(R_SAMPLE_BELOW_MIN, "cards_index_case_count_mismatch",
                                    {"scenario_id": scenario_id})
        card_sha = require_digest(row.get("card_sha256"), "cards_index.card_sha256")
        if card_sha in seen:
            raise _H2AggregateError(R_IDENTITY_MISMATCH, "cards_index_card_sha_duplicated")
        seen.append(card_sha)
        if row.get("validate_hard_evidence_scorecard") != "pass":
            raise _H2AggregateError(R_HARD_FAILURE, "card_scorecard_validation_not_pass",
                                    {"scenario_id": scenario_id})
        if row.get("verified") is not True:
            raise _H2AggregateError(R_REQUIRED_UNKNOWN, "card_not_verified",
                                    {"scenario_id": scenario_id})
        if require_int(row.get("hard_failures"), "cards_index.hard_failures") != 0:
            raise _H2AggregateError(R_HARD_FAILURE, "card_hard_failures_nonzero",
                                    {"scenario_id": scenario_id})
        rows.append(dict(row))
    return rows


def _validate_aggregate(aggregate: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_keys(aggregate, _AGGREGATE_REQUIRED, "composition_aggregate")
    if aggregate.get("schema_version") != AGGREGATE_SCHEMA_VERSION or aggregate.get("kind") != "aggregate":
        raise _H2AggregateError(R_VERSION_MISMATCH, "aggregate_schema_mismatch",
                                {"schema_version": aggregate.get("schema_version")})
    require_digest(aggregate.get("composition_file_sha256"), "aggregate.composition_file_sha256")
    require_digest(aggregate.get("aggregate_sha256"), "aggregate.aggregate_sha256")
    total = require_int(aggregate.get("total"), "aggregate.total", minimum=1)
    executed = require_int(aggregate.get("executed"), "aggregate.executed")
    passed = require_int(aggregate.get("passed"), "aggregate.passed")
    failed = require_int(aggregate.get("failed"), "aggregate.failed")
    errors = require_int(aggregate.get("errors"), "aggregate.errors")
    if total != 30 or executed != passed + failed or total != executed + errors:
        raise _H2AggregateError(R_EVIDENCE_MISSING, "aggregate_counts_inconsistent",
                                {"total": total, "executed": executed, "passed": passed,
                                 "failed": failed, "errors": errors})
    if require_int(aggregate.get("turns_planned"), "aggregate.turns_planned") != 36 or \
            require_int(aggregate.get("turns_executed"), "aggregate.turns_executed") != 36 or \
            require_int(aggregate.get("not_started"), "aggregate.not_started") != 0:
        raise _H2AggregateError(R_SAMPLE_BELOW_MIN, "aggregate_coverage_incomplete")
    if aggregate.get("status") != "complete":
        raise _H2AggregateError(R_EVIDENCE_MISSING, "aggregate_status_not_complete")
    if require_int(aggregate.get("hard_failures"), "aggregate.hard_failures") != 0:
        raise _H2AggregateError(R_HARD_FAILURE, "aggregate_hard_failures_nonzero")
    if aggregate.get("verified") is not True:
        raise _H2AggregateError(R_REQUIRED_UNKNOWN, "aggregate_not_verified")
    if aggregate.get("threshold_met") is not True:
        raise _H2AggregateError(R_QUALITY_BELOW_THRESHOLD, "aggregate_threshold_not_met")
    if require_int(aggregate.get("required_unknowns"), "aggregate.required_unknowns") != 0:
        raise _H2AggregateError(R_REQUIRED_UNKNOWN, "aggregate_required_unknowns_nonzero")
    require_int(aggregate.get("non_required_unknowns"), "aggregate.non_required_unknowns")
    # 注解/策略元数据：必须存在且为既定值，但**不参与**判定（阈值由发布层施加）。
    if aggregate.get("thresholds_approved") is not False or aggregate.get("release_ready") is not False:
        raise _H2AggregateError(R_IDENTITY_MISMATCH, "aggregate_metadata_unexpected",
                                {"thresholds_approved": aggregate.get("thresholds_approved"),
                                 "release_ready": aggregate.get("release_ready")})
    if list(aggregate.get("blocks") or ()) != ["holdout_threshold_unapproved"]:
        raise _H2AggregateError(R_IDENTITY_MISMATCH, "aggregate_blocks_unexpected",
                                {"blocks": list(aggregate.get("blocks") or ())})
    strata = aggregate.get("strata")
    if not isinstance(strata, Mapping) or set(strata) != set(H2_SCENARIO_ORDER) or False:
        pass
    expected_strata = {"paraphrase": 10, "multi_turn": 5, "negative": 5,
                       "stale_conflict": 5, "cross_doc_security": 5}
    if not isinstance(strata, Mapping) or set(strata) != set(expected_strata):
        raise _H2AggregateError(R_EVIDENCE_MISSING, "aggregate_strata_missing")
    totals = {"total": 0, "passed": 0, "failed": 0, "errors": 0}
    for name, bucket in strata.items():
        exact_keys(bucket, ("total", "passed", "failed", "errors"), what=f"strata[{name}]")
        if require_int(bucket.get("total"), f"strata[{name}].total") != expected_strata[name]:
            raise _H2AggregateError(R_SAMPLE_BELOW_MIN, "aggregate_strata_total_mismatch",
                                    {"stratum": name})
        if require_int(bucket.get("passed"), f"strata[{name}].passed") + \
                require_int(bucket.get("failed"), f"strata[{name}].failed") + \
                require_int(bucket.get("errors"), f"strata[{name}].errors") != expected_strata[name]:
            raise _H2AggregateError(R_EVIDENCE_MISSING, "aggregate_strata_inconsistent",
                                    {"stratum": name})
        for key in totals:
            totals[key] += int(bucket[key])
    if totals != {"total": total, "passed": passed, "failed": failed, "errors": errors}:
        raise _H2AggregateError(R_EVIDENCE_MISSING, "aggregate_strata_rollup_mismatch")
    axes = aggregate.get("axes")
    from .p2_hard_evidence import AXES

    if not isinstance(axes, Mapping) or set(axes) != set(AXES):
        raise _H2AggregateError(R_EVIDENCE_MISSING, "aggregate_axes_missing")
    unknown_total = 0
    for name in AXES:
        block = axes[name]
        exact_keys(block, ("planned", "passed", "not_applicable", "unknown", "violations",
                           "checked"), what=f"axes[{name}]")
        if require_int(block.get("planned"), f"axes[{name}].planned") != total:
            raise _H2AggregateError(R_SAMPLE_BELOW_MIN, "aggregate_axes_planned_mismatch")
        if require_int(block.get("passed"), "axes.passed") + \
                require_int(block.get("not_applicable"), "axes.not_applicable") + \
                require_int(block.get("unknown"), "axes.unknown") + \
                require_int(block.get("violations"), "axes.violations") != total:
            raise _H2AggregateError(R_EVIDENCE_MISSING, "aggregate_axes_bucket_inconsistent")
        if require_int(block.get("violations"), "axes.violations") != 0:
            raise _H2AggregateError(R_HARD_FAILURE, "aggregate_axis_violation",
                                    {"axis": name})
        unknown_total += int(block["unknown"])
    if unknown_total != int(aggregate["required_unknowns"]) + int(aggregate["non_required_unknowns"]):
        raise _H2AggregateError(R_EVIDENCE_MISSING, "aggregate_unknown_rollup_mismatch",
                                {"axes_unknown": unknown_total})
    cards = aggregate.get("cards")
    if not isinstance(cards, list) or len(cards) != len(H2_SCENARIO_ORDER):
        raise _H2AggregateError(R_SAMPLE_BELOW_MIN, "aggregate_cards_missing")
    for position, (scenario_id, item) in enumerate(zip(H2_SCENARIO_ORDER, cards)):
        row = _require_keys(item, _CARD_KEYS, f"aggregate.cards[{position}]")
        if row.get("scenario_id") != scenario_id:
            raise _H2AggregateError(R_IDENTITY_MISMATCH, "aggregate_cards_order_mismatch")
        if require_digest(row.get("payload_sha256"), "card.payload_sha256") != \
                require_digest(row.get("aggregate_sha256"), "card.aggregate_sha256"):
            raise _H2AggregateError(R_DIGEST_MISMATCH, "card_payload_aggregate_mismatch",
                                    {"scenario_id": scenario_id})
        if require_int(row.get("case_count"), "card.case_count") != H2_SCENARIO_CASE_COUNTS[scenario_id] or \
                require_int(row.get("turns_executed"), "card.turns_executed") != \
                H2_SCENARIO_TURNS[scenario_id]:
            raise _H2AggregateError(R_SAMPLE_BELOW_MIN, "aggregate_card_coverage_mismatch",
                                    {"scenario_id": scenario_id})
        if require_int(row.get("hard_failures"), "card.hard_failures") != 0 or \
                row.get("verified") is not True:
            raise _H2AggregateError(R_HARD_FAILURE, "aggregate_card_not_verified",
                                    {"scenario_id": scenario_id})
    annotation = aggregate.get("annotation")
    if not isinstance(annotation, Mapping) or annotation.get("case_count") != 30 or \
            annotation.get("total_turns") != 36:
        raise _H2AggregateError(R_EVIDENCE_MISSING, "aggregate_annotation_mismatch")
    if dict(annotation.get("scenario_counts") or {}) != dict(H2_SCENARIO_CASE_COUNTS):
        raise _H2AggregateError(R_IDENTITY_MISMATCH, "aggregate_annotation_scenarios_mismatch")
    return aggregate


def _validate_source_proof(proof: Mapping[str, Any], aggregate: Mapping[str, Any],
                           index_cards: list[dict[str, Any]]) -> Mapping[str, Any]:
    _require_keys(proof, _PROOF_KEYS, "source_proof")
    if proof.get("schema_version") != H2_SOURCE_PROOF_SCHEMA_VERSION:
        raise _H2AggregateError(R_VERSION_MISMATCH, "source_proof_schema_mismatch",
                                {"observed": proof.get("schema_version")})
    require_text(proof.get("batch_id"), "source_proof.batch_id")
    authority = _require_keys(proof.get("batch_authority"),
                              ("document", "sha256", "section"), "batch_authority")
    document = Path(require_text(authority.get("document"), "batch_authority.document"))
    if not document.is_file():
        raise _H2AggregateError(R_EVIDENCE_MISSING, "batch_authority_document_missing",
                                {"path": document.name})
    if file_sha256(document) != require_digest(authority.get("sha256"), "batch_authority.sha256"):
        raise _H2AggregateError(R_DIGEST_MISMATCH, "batch_authority_digest_mismatch")
    binding = _require_keys(proof.get("batch_binding"),
                            ("manifest_sha256", "full_cases_sha256", "assignment_sha256"),
                            "batch_binding")
    for key in ("manifest_sha256", "full_cases_sha256", "assignment_sha256"):
        require_digest(binding.get(key), f"batch_binding.{key}")
    scenarios = proof.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != len(H2_SCENARIO_ORDER):
        raise _H2AggregateError(R_EVIDENCE_MISSING, "source_proof_scenarios_missing")
    seen_plans: list[str] = []
    for position, (scenario_id, item) in enumerate(zip(H2_SCENARIO_ORDER, scenarios)):
        row = _require_keys(item, _PROOF_SCENARIO_KEYS, f"scenarios[{position}]")
        if row.get("scenario_id") != scenario_id:
            raise _H2AggregateError(R_IDENTITY_MISMATCH, "source_proof_scenario_order_mismatch")
        if require_int(row.get("case_count"), "scenario.case_count") != H2_SCENARIO_CASE_COUNTS[scenario_id] or \
                require_int(row.get("turns_executed"), "scenario.turns_executed") != \
                H2_SCENARIO_TURNS[scenario_id]:
            raise _H2AggregateError(R_SAMPLE_BELOW_MIN, "source_proof_coverage_mismatch",
                                    {"scenario_id": scenario_id})
        plan_sha = require_digest(row.get("plan_sha256"), "scenario.plan_sha256")
        if plan_sha in seen_plans:
            raise _H2AggregateError(R_IDENTITY_MISMATCH, "source_proof_plan_duplicated")
        seen_plans.append(plan_sha)
        derived = require_digest(row.get("derived_card_sha256"), "scenario.derived_card_sha256")
        if derived != require_digest(aggregate["cards"][position]["aggregate_sha256"],
                                     "aggregate.card.aggregate_sha256"):
            raise _H2AggregateError(
                R_DIGEST_MISMATCH, "source_proof_card_aggregate_mismatch",
                {"scenario_id": scenario_id, "proof": derived[:12],
                 "aggregate": aggregate["cards"][position]["aggregate_sha256"][:12]},
            )
        if row.get("status") != "succeeded":
            raise _H2AggregateError(R_EVIDENCE_MISSING, "source_proof_scenario_not_succeeded",
                                    {"scenario_id": scenario_id})
        original = _require_keys(row.get("original_identities"),
                                 ("gate_config_hash", "pipeline_version", "index_revision",
                                  "dataset_version"), "original_identities")
        if require_digest(original.get("gate_config_hash"),
                          "original_identities.gate_config_hash") != ORIGINAL_H2_GATE_CONFIG_HASH:
            raise _H2AggregateError(R_IDENTITY_MISMATCH, "h2_original_gate_config_mismatch",
                                    {"observed": original.get("gate_config_hash")})
        derived_scorer = _require_keys(row.get("derived_scorer"), ("tool", "source_sha256"),
                                       "derived_scorer")
        from .p2_release_h2 import classifier_source_sha256

        if require_digest(derived_scorer.get("source_sha256"), "derived_scorer.source_sha256") != \
                classifier_source_sha256():
            raise _H2AggregateError(R_IDENTITY_MISMATCH, "derived_scorer_identity_mismatch",
                                    {"scenario_id": scenario_id})
    zero_call = _require_keys(proof.get("zero_call"),
                              ("new_requests", "new_outbound", "replayed"), "zero_call")
    if require_int(zero_call.get("new_requests"), "zero_call.new_requests") != 0 or \
            require_int(zero_call.get("new_outbound"), "zero_call.new_outbound") != 0 or \
            zero_call.get("replayed") is not False:
        raise _H2AggregateError(R_IDENTITY_MISMATCH, "h2_rebuild_not_zero_call")
    c25 = _require_keys(proof.get("c25_non_required_unknown"), ("case_id", "axes", "count"),
                        "c25")
    if require_text(c25.get("case_id"), "c25.case_id") != "C25":
        raise _H2AggregateError(R_IDENTITY_MISMATCH, "c25_case_mismatch")
    if not isinstance(c25.get("axes"), list):
        raise _H2AggregateError(R_EVIDENCE_MISSING, "c25_axes_invalid")
    if require_int(c25.get("count"), "c25.count") != int(aggregate["non_required_unknowns"]):
        raise _H2AggregateError(R_IDENTITY_MISMATCH, "c25_count_mismatch",
                                {"declared": c25.get("count"),
                                 "aggregate": aggregate["non_required_unknowns"]})
    return proof


def assess_h2_aggregate(inputs: ReleaseInputs) -> tuple[tuple[ReleaseRow, ...], Mapping[str, Any] | None]:
    """受限聚合模式：逐卡外层核验 + 组合聚合 + 来源证明；不读卡本体。"""
    bound_aggregate = inputs.h2_composition_aggregate
    bound_index = inputs.h2_cards_index
    if bound_aggregate is None or bound_index is None:
        return (), None
    try:
        index_cards = _validate_cards_index(bound_index.payload)
        aggregate = _validate_aggregate(bound_aggregate.payload)
        proof = _validate_source_proof(inputs.h2_source_proof.payload, aggregate, index_cards)
    except _H2AggregateError as exc:
        return (row_blocked("h2.aggregate", "H2 受限聚合核验", exc.reason, cause=exc.cause,
                            detail=exc.detail),), None
    rows: list[ReleaseRow] = []
    rows.append(row_ok("h2.aggregate", "H2 组合聚合（受限外层核验）", detail={
        "aggregate_sha256": bound_aggregate.sha256,
        "composition_file_sha256": aggregate["composition_file_sha256"],
        "total": aggregate["total"], "executed": aggregate["executed"],
        "passed": aggregate["passed"], "failed": aggregate["failed"],
        "turns_planned": aggregate["turns_planned"],
        "turns_executed": aggregate["turns_executed"],
        "not_started": aggregate["not_started"], "status": aggregate["status"],
        "hard_failures": aggregate["hard_failures"],
        "required_unknowns": aggregate["required_unknowns"],
        "non_required_unknowns": aggregate["non_required_unknowns"],
        "verified": aggregate["verified"], "threshold_met": aggregate["threshold_met"],
        "boundary": "D-001：卡本体留在保管环境，本行只做聚合外层核验",
    }, evidence=(f"aggregate:{bound_aggregate.sha256[:16]}",)))
    rows.append(row_ok("h2.cards_index", "H2 四卡索引（文件 SHA + 校验结果）", detail={
        "index_sha256": bound_index.sha256,
        "cards": [{"scenario_id": card["scenario_id"],
                   "card_file_sha256": card["card_sha256"],
                   "validate_hard_evidence_scorecard": card["validate_hard_evidence_scorecard"],
                   "verified": card["verified"], "hard_failures": card["hard_failures"]}
                  for card in index_cards],
        "note": "card_file_sha256 只用于'拿到的就是那张卡'；卡内容聚合摘要另列为 "
                "card_aggregate_sha256，两者不可互换",
        "card_file_sha256_note": "卡文件摘要由保管方提供，仓内不可复算（D-001 边界）；"
                                 "本门禁只能验证它 ≠ 聚合哈希，不能独立重算",
    }, evidence=(f"cards_index:{bound_index.sha256[:16]}",)))
    for position, scenario_id in enumerate(H2_SCENARIO_ORDER):
        card = index_cards[position]
        card_aggregate = require_digest(aggregate["cards"][position]["aggregate_sha256"],
                                        "aggregate.card.aggregate_sha256")
        if card["card_sha256"] == card_aggregate:
            # 两套哈希含义不同：文件 SHA 与内容聚合 SHA 相等几乎只能是"拿错了哈希源"。
            return (row_blocked("h2.cards_index", "H2 四卡索引（文件 SHA + 校验结果）",
                                R_IDENTITY_MISMATCH, cause="card_file_sha_equals_aggregate",
                                detail={"scenario_id": scenario_id}),), None
        rows.append(row_ok(f"h2.card.{scenario_id}",
                           f"H2 场景卡 {scenario_id}（受限外层核验）", detail={
            "scenario_id": scenario_id,
            "card_file_sha256": card["card_sha256"],
            "card_aggregate_sha256": card_aggregate,
            "validate_hard_evidence_scorecard": card["validate_hard_evidence_scorecard"],
            "verified": card["verified"],
            "hard_failures": card["hard_failures"],
            "case_count": card["case_count"],
            "turns_executed": aggregate["cards"][position]["turns_executed"],
            "card_body_location": "仓外保管环境（本轮未读取）",
            "card_file_sha256_note": "仓内不可复算（D-001）：只能验证 file≠aggregate，"
                                     "文件摘要来自保管方",
        }))
    rows.append(row_ok("h2.source_proof", "H2 同批来源证明（完整版）", detail={
        "proof_sha256": inputs.h2_source_proof.sha256,
        "batch_id": proof["batch_id"],
        "batch_binding": dict(proof["batch_binding"]),
        "zero_call": dict(proof["zero_call"]),
        "c25": dict(proof["c25_non_required_unknown"]),
        "derived_scorer_source_sha256": proof["scenarios"][0]["derived_scorer"]["source_sha256"],
        "scenarios": [{"scenario_id": item["scenario_id"], "run_id": item["run_id"],
                       "plan_sha256": item["plan_sha256"],
                       "derived_card_sha256": item["derived_card_sha256"]}
                      for item in proof["scenarios"]],
    }, evidence=(f"source_proof:{inputs.h2_source_proof.sha256[:16]}",)))
    # 两套身份分列，注明不得混用
    rows.append(row_observed("h2.identity.original", "H2 原运行身份（批次当时 unapproved 模板）", detail={
        "gate_config_hash": ORIGINAL_H2_GATE_CONFIG_HASH,
        "pipeline_version": proof["scenarios"][0]["original_identities"]["pipeline_version"],
        "dataset_version": proof["scenarios"][0]["original_identities"]["dataset_version"],
        "applicability_reference": {
            "task3_report_sha256": file_sha256(
                inputs.evidence_report.path) if inputs.evidence_report is not None else None,
            "note": "历史 run 的原配置口径与适用性由任务 3 旧版本适用性证明承接；不得用发布层摘要替换",
        },
    }))
    rows.append(row_observed("h2.identity.release", "发布门禁配置（获批阈值，由发布层施加）", detail={
        "gate_config_hash": APPROVED_GATE_CONFIG_HASH,
        "approved_config": "docs/evaluation/gate_v0_3_approved.json",
        "note": "本行与 h2.identity.original 分列：一个是被评价对象的身份，一个是评价阈值；不得互相覆盖",
    }))
    rows.append(row_observed("h2.annotation_metadata", "组合注解/策略元数据（非数据失败）", detail={
        "annotation.quality_readiness": aggregate["annotation"].get("quality_readiness"),
        "annotation.runtime_axis_evidence_produced":
            aggregate["annotation"].get("runtime_axis_evidence_produced"),
        "thresholds_approved": aggregate["thresholds_approved"],
        "release_ready": aggregate["release_ready"],
        "blocks": list(aggregate["blocks"]),
        "mapping": "v0.2 组合硬编码策略：thresholds_approved=false / release_ready=false / "
                   "holdout_threshold_unapproved 均属注解层；获批阈值由发布门禁层单独施加，"
                   "不据此判 blocked/pending",
    }))
    rows.append(row_ok("h2.coverage", "H2 同批 30 题 36 回合", detail={
        "total": aggregate["total"], "turns_planned": aggregate["turns_planned"],
        "turns_executed": aggregate["turns_executed"], "not_started": aggregate["not_started"],
        "status": aggregate["status"]}))
    strata = {name: int(aggregate["strata"][name]["total"]) for name in aggregate["strata"]}
    if strata != {"paraphrase": 10, "multi_turn": 5, "negative": 5, "stale_conflict": 5,
                  "cross_doc_security": 5}:
        rows.append(row_blocked("h2.strata", "H2 五层齐全（10/5/5/5/5）", R_SAMPLE_BELOW_MIN,
                                cause="strata_mismatch", detail={"strata": strata}))
    else:
        rows.append(row_ok("h2.strata", "H2 五层齐全（10/5/5/5/5）", detail={"strata": strata}))
    if int(aggregate["passed"]) < 24:
        rows.append(row_blocked("h2.quality", "H2 正确 ≥24/30", R_QUALITY_BELOW_THRESHOLD,
                                cause=f"{aggregate['passed']} < 24"))
    else:
        rows.append(row_ok("h2.quality", "H2 正确 ≥24/30",
                           detail={"passed": aggregate["passed"],
                                   "failed": aggregate["failed"]}))
    rows.append(row_ok("h2.hard_failures", "H2 硬失败 0",
                       detail={"hard_failures": aggregate["hard_failures"],
                               "by_kind": dict(aggregate["hard_failures_by_kind"])}))
    rows.append(row_ok("h2.required_axes", "H2 必需轴无未知",
                       detail={"required_unknowns": aggregate["required_unknowns"],
                               "axes": dict(aggregate["axes"])}))
    rows.append(row_observed("h2.non_required_axes", "H2 非必需轴未知（C25 原口径）", detail={
        "non_required_unknowns": aggregate["non_required_unknowns"],
        "c25": dict(proof["c25_non_required_unknown"]),
        "count_matches": int(proof["c25_non_required_unknown"]["count"]) ==
                         int(aggregate["non_required_unknowns"]),
        "note": "C25 派生 not_applicable=0 为合法闭合；历史 live unknown=1 见任务 2 "
                "报告 §5（复审后聚合取消），任务 3 清单无 C25 条目",
    }))
    rows.append(row_observed("h2.card_verified", "H2 整卡 verified（如实展示）", detail={
        "aggregate_verified": aggregate["verified"],
        "cards_verified": [card["verified"] for card in index_cards],
        "note": "四卡 verified=true 且聚合 verified=true；该行只展示，不单独改变总门",
    }))
    evidence = {
        "aggregate": aggregate,
        "cards_index": index_cards,
        "proof": proof,
        "boundary": "D-001 受限：卡本体在仓外，未读取",
    }
    return tuple(rows), evidence


__all__ = [
    "AGGREGATE_SCHEMA_VERSION",
    "APPROVED_GATE_CONFIG_HASH",
    "CARDS_INDEX_SCHEMA_VERSION",
    "ORIGINAL_H2_GATE_CONFIG_HASH",
    "assess_h2_aggregate",
]
