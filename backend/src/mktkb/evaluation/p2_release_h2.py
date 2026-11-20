"""H2 严格校验与三视图分离：必需轴 / 非必需轴 / 整卡 verified / 总门。

严格性来源（全部复用既有校验器，不重写）：

* 逐卡：:func:`p2_hard_evidence.validate_hard_evidence_scorecard`（v0.2 全卡等式/词表/防篡改）。
* 组合：:func:`p2_holdout_scenarios.validate_hard_evidence_composition`（四场景唯一覆盖身份、
  block 集合、受限聚合）。
* 必需未知：用组合里的**冻结标注**（``annotation.axis_counts[*].required``）判断哪条轴是
  必需的；必需轴出现 unknown 即阻断，非必需轴（C25 口径）单列展示、不参与总门。

调用方自报的布尔/名称白名单一律不作为证据：``verified``、``threshold_met``、
``release_ready`` 都要与重算值一致（校验器内部已按等式推导）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .p2_release_inputs import H2_SCENARIO_CASE_COUNTS, H2_SCENARIO_ORDER, H2_SCENARIO_TURNS, ReleaseInputs
from .p2_release_model import (
    H2_SOURCE_PROOF_SCHEMA_VERSION,
    R_CROSS_PLAN_MERGE,
    R_DIGEST_MISMATCH,
    R_DUPLICATE_EVIDENCE,
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
    payload_sha256,
    require_digest,
    require_int,
    require_text,
    row_blocked,
    row_observed,
    row_ok,
    source_bundle_sha256,
)

#: H2 派生评分器/分类器身份绑定文件（任务 1 的实现；只读）。
H2_CLASSIFIER_SOURCES: tuple[str, ...] = ("p2_hard_evidence.py", "p2_holdout_scenarios.py")

_PROOF_KEYS = (
    "schema_version",
    "batch_id",
    "batch_authority",
    "batch_binding",
    "scenarios",
    "zero_call",
    "c25_non_required_unknown",
)
_BATCH_AUTHORITY_KEYS = ("document", "sha256", "section")
#: 同批绑定只认组合里可交叉核验的三个摘要（其余身份按记录展示，不冒充已核验）。
_BATCH_BINDING_KEYS = ("manifest_sha256", "full_cases_sha256", "assignment_sha256")
_SCENARIO_KEYS = (
    "scenario_id",
    "run_id",
    "plan_sha256",
    "status",
    "case_count",
    "turns_executed",
    "config_hash",
    "hard_evidence_sha256",
    "derived_card_sha256",
    "original_identities",
    "derived_scorer",
)
_ORIGINAL_IDENTITY_KEYS = ("gate_config_hash", "pipeline_version", "index_revision", "dataset_version")
_DERIVED_SCORER_KEYS = ("tool", "source_sha256")
_ZERO_CALL_KEYS = ("new_requests", "new_outbound", "replayed")
_C25_KEYS = ("case_id", "axes", "count")


@dataclass(frozen=True)
class H2Evidence:
    composition: Mapping[str, Any]
    proof: Mapping[str, Any]
    cards: tuple[Mapping[str, Any], ...]
    axis_counts: Mapping[str, Mapping[str, int]]
    annotation_axes: Mapping[str, Mapping[str, int]]
    card_verified: bool
    classification_status: str


class _H2Error(ValueError):
    def __init__(self, reason: str, cause: str, detail: Mapping[str, Any] | None = None) -> None:
        super().__init__(f"{reason}: {cause}")
        self.reason = reason
        self.cause = cause
        self.detail = dict(detail or {})


def classifier_source_sha256() -> str:
    """派生评分器/分类器身份：绑定任务 1 的离线重建实现（位置由本模块定位）。"""
    root = Path(__file__).resolve().parent
    return source_bundle_sha256([root / name for name in H2_CLASSIFIER_SOURCES])


def _validate_composition(payload: Mapping[str, Any], *, expected_strata: Mapping[str, int]) -> Mapping[str, Any]:
    from .p2_holdout_scenarios import (
        HARD_EVIDENCE_COMPOSITION_SCHEMA_VERSION,
        ScenarioError,
        validate_hard_evidence_composition,
    )

    if payload.get("schema_version") != HARD_EVIDENCE_COMPOSITION_SCHEMA_VERSION:
        raise _H2Error(R_VERSION_MISMATCH, "composition_schema_mismatch", {
            "expected": HARD_EVIDENCE_COMPOSITION_SCHEMA_VERSION,
            "observed": payload.get("schema_version"),
        })
    try:
        return validate_hard_evidence_composition(payload, total=30, expected_strata=expected_strata)
    except ScenarioError as exc:
        reason = R_REQUIRED_UNKNOWN if "block" in str(exc) else R_EVIDENCE_MISSING
        raise _H2Error(reason, f"composition_invalid:{exc}") from None


def _validate_card(card: Mapping[str, Any], *, total: int, run_id: str, config_hash: str) -> Mapping[str, Any]:
    from .p2_hard_evidence import HardEvidenceError, validate_hard_evidence_scorecard

    if card.get("schema_version") != "mktkb.p2.scoring.v0.2":
        raise _H2Error(R_VERSION_MISMATCH, "card_schema_mismatch", {
            "expected": "mktkb.p2.scoring.v0.2", "observed": card.get("schema_version"),
        })
    try:
        return validate_hard_evidence_scorecard(
            card, total=total, run_id=run_id, config_hash=config_hash
        )
    except HardEvidenceError as exc:
        raise _H2Error(R_EVIDENCE_MISSING, f"card_invalid:{exc}") from None


def _validate_source_proof(
    proof: Mapping[str, Any],
    composition: Mapping[str, Any],
    cards: Sequence[Mapping[str, Any]],
    *,
    project_root: Path | None = None,
) -> Mapping[str, Any]:
    """来源证明：同批身份、逐卡摘要、两套身份、零调用、C25 口径。"""
    exact_keys(proof, _PROOF_KEYS, what="h2.source_proof",
               code=R_EVIDENCE_MISSING)
    if proof.get("schema_version") != H2_SOURCE_PROOF_SCHEMA_VERSION:
        raise _H2Error(R_VERSION_MISMATCH, "source_proof_schema_mismatch",
                       {"observed": proof.get("schema_version")})
    require_text(proof.get("batch_id"), "source_proof.batch_id")
    authority = exact_keys(proof.get("batch_authority"), _BATCH_AUTHORITY_KEYS,
                           what="source_proof.batch_authority")
    document = Path(require_text(authority.get("document"), "batch_authority.document"))
    document = document if document.is_absolute() else (Path(project_root or ".") / document)
    if not document.is_file():
        raise _H2Error(R_EVIDENCE_MISSING, "batch_authority_document_missing",
                       {"path": str(document)})
    if file_sha256(document) != require_digest(authority.get("sha256"), "batch_authority.sha256"):
        raise _H2Error(R_DIGEST_MISMATCH, "batch_authority_digest_mismatch",
                       {"path": str(document)})
    require_text(authority.get("section"), "batch_authority.section")

    binding = exact_keys(proof.get("batch_binding"), _BATCH_BINDING_KEYS,
                         what="source_proof.batch_binding")
    for key in ("manifest_sha256", "full_cases_sha256", "assignment_sha256"):
        if binding.get(key) != composition.get(key):
            raise _H2Error(R_IDENTITY_MISMATCH, f"batch_binding_mismatch:{key}",
                           {"declared": binding.get(key), "composition": composition.get(key)})
    runs = composition.get("runs") or ()

    scenarios = proof.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != len(H2_SCENARIO_ORDER):
        raise _H2Error(R_EVIDENCE_MISSING, "scenarios_missing")
    if len(cards) != len(scenarios):
        raise _H2Error(R_EVIDENCE_MISSING, "cards_missing")
    seen_run_ids: list[str] = []
    seen_plans: list[str] = []
    total_cases = 0
    total_turns = 0
    for index, item in enumerate(scenarios):
        row = exact_keys(item, _SCENARIO_KEYS, what=f"source_proof.scenarios[{index}]")
        scenario_id = require_text(row.get("scenario_id"), "scenario.scenario_id")
        if scenario_id != H2_SCENARIO_ORDER[index]:
            raise _H2Error(R_IDENTITY_MISMATCH, "scenario_order_mismatch",
                           {"index": index, "expected": H2_SCENARIO_ORDER[index],
                            "observed": scenario_id})
        run = runs[index]
        run_id = require_text(row.get("run_id"), "scenario.run_id")
        if run_id != run.get("run_id"):
            raise _H2Error(R_IDENTITY_MISMATCH, f"scenario_run_id_mismatch:{scenario_id}",
                           {"declared": run_id, "composition": run.get("run_id")})
        if run_id in seen_run_ids:
            raise _H2Error(R_DUPLICATE_EVIDENCE, f"duplicate_run_id:{run_id}")
        seen_run_ids.append(run_id)
        plan_sha = require_digest(row.get("plan_sha256"), "scenario.plan_sha256")
        if plan_sha != run.get("plan_sha256"):
            raise _H2Error(R_IDENTITY_MISMATCH, f"scenario_plan_mismatch:{scenario_id}")
        if plan_sha in seen_plans:
            raise _H2Error(R_CROSS_PLAN_MERGE, f"duplicate_plan_sha256:{scenario_id}")
        seen_plans.append(plan_sha)
        if row.get("status") != run.get("status"):
            raise _H2Error(R_IDENTITY_MISMATCH, f"scenario_status_mismatch:{scenario_id}")
        if row.get("config_hash") != run.get("config_hash"):
            raise _H2Error(R_IDENTITY_MISMATCH, f"scenario_config_mismatch:{scenario_id}")
        if row.get("hard_evidence_sha256") != run.get("hard_evidence_sha256"):
            raise _H2Error(R_DIGEST_MISMATCH, f"scenario_hard_evidence_mismatch:{scenario_id}")
        if row.get("derived_card_sha256") != run.get("aggregate_sha256"):
            raise _H2Error(R_DIGEST_MISMATCH, f"scenario_card_digest_mismatch:{scenario_id}")
        case_count = require_int(row.get("case_count"), "scenario.case_count", minimum=1)
        turns = require_int(row.get("turns_executed"), "scenario.turns_executed", minimum=0)
        if case_count != H2_SCENARIO_CASE_COUNTS[scenario_id]:
            raise _H2Error(R_SAMPLE_BELOW_MIN, f"scenario_case_count_mismatch:{scenario_id}",
                           {"expected": H2_SCENARIO_CASE_COUNTS[scenario_id], "observed": case_count})
        if turns != H2_SCENARIO_TURNS[scenario_id]:
            raise _H2Error(R_SAMPLE_BELOW_MIN, f"scenario_turns_mismatch:{scenario_id}",
                           {"expected": H2_SCENARIO_TURNS[scenario_id], "observed": turns})
        total_cases += case_count
        total_turns += turns
        original = exact_keys(row.get("original_identities"), _ORIGINAL_IDENTITY_KEYS,
                              what="scenario.original_identities")
        require_digest(original.get("gate_config_hash"), "original_identities.gate_config_hash")
        require_int(original.get("index_revision"), "original_identities.index_revision")
        require_text(original.get("pipeline_version"), "original_identities.pipeline_version")
        require_text(original.get("dataset_version"), "original_identities.dataset_version")
        derived = exact_keys(row.get("derived_scorer"), _DERIVED_SCORER_KEYS,
                             what="scenario.derived_scorer")
        require_text(derived.get("tool"), "derived_scorer.tool")
        if derived.get("source_sha256") != classifier_source_sha256():
            raise _H2Error(R_IDENTITY_MISMATCH, f"derived_scorer_identity_mismatch:{scenario_id}",
                           {"declared": derived.get("source_sha256"),
                            "current": classifier_source_sha256()})
        card = cards[index]
        if payload_sha256(card) != row.get("derived_card_sha256"):
            raise _H2Error(R_DIGEST_MISMATCH, f"card_bytes_digest_mismatch:{scenario_id}")
        if require_int(card.get("total"), "card.total", minimum=1) != case_count:
            raise _H2Error(R_SAMPLE_BELOW_MIN, f"card_total_mismatch:{scenario_id}")
    if total_cases != 30 or total_turns != 36:
        raise _H2Error(R_SAMPLE_BELOW_MIN, "batch_coverage_mismatch",
                       {"cases": total_cases, "turns": total_turns})
    zero_call = exact_keys(proof.get("zero_call"), _ZERO_CALL_KEYS, what="source_proof.zero_call")
    if require_int(zero_call.get("new_requests"), "zero_call.new_requests") != 0 \
            or require_int(zero_call.get("new_outbound"), "zero_call.new_outbound") != 0 \
            or zero_call.get("replayed") is not False:
        raise _H2Error(R_IDENTITY_MISMATCH, "rebuild_not_zero_call", dict(zero_call))
    c25 = exact_keys(proof.get("c25_non_required_unknown"), _C25_KEYS,
                     what="source_proof.c25_non_required_unknown")
    require_text(c25.get("case_id"), "c25.case_id")
    if not isinstance(c25.get("axes"), list):
        raise _H2Error(R_EVIDENCE_MISSING, "c25_axes_invalid")
    require_int(c25.get("count"), "c25.count")
    return dict(proof)


def assess_h2(
    inputs: ReleaseInputs, *, project_root: Path | None = None
) -> tuple[tuple[ReleaseRow, ...], H2Evidence | None]:
    """H2：严格组合校验 + 三视图分离；任何必需未知/硬失败/覆盖缺失都阻断。"""
    standards = inputs.gate_config.standards
    expected_strata = dict(standards.holdout_strata) if standards is not None else {}
    composition = inputs.h2_composition.payload
    try:
        validated = _validate_composition(composition, expected_strata=expected_strata)
    except _H2Error as exc:
        return (_blocked_rows(exc), None)
    cards = [item.payload for item in inputs.h2_cards]
    try:
        proof = _validate_source_proof(dict(inputs.h2_source_proof.payload), validated, cards,
                                       project_root=project_root)
    except _H2Error as exc:
        return (_blocked_rows(exc), None)
    except Exception as exc:  # 契约/结构异常：缺证阻断，不猜
        return (_blocked_rows(_H2Error(R_EVIDENCE_MISSING, f"source_proof_invalid:{exc}")), None)

    rows: list[ReleaseRow] = []
    rows.append(row_ok("h2.composition", "H2 四场景组合严格校验", detail={
        "schema_version": validated["schema_version"],
        "status": validated["status"],
        "not_started": validated["not_started"],
        "total": validated["total"],
        "executed": validated["executed"],
    }, evidence=(f"composition:{inputs.h2_composition.sha256[:16]}",)))
    rows.append(row_ok("h2.source_proof", "H2 同批来源证明（两套身份）", detail={
        "batch_id": proof["batch_id"],
        "batch_binding": dict(proof["batch_binding"]),
        "scenarios": [
            {"scenario_id": item["scenario_id"], "run_id": item["run_id"],
             "plan_sha256": item["plan_sha256"],
             "derived_card_sha256": item["derived_card_sha256"],
             "original_gate_config_hash": item["original_identities"]["gate_config_hash"]}
            for item in proof["scenarios"]
        ],
        "zero_call": dict(proof["zero_call"]),
        "derived_scorer_source_sha256": classifier_source_sha256(),
    }, evidence=(f"source_proof:{inputs.h2_source_proof.sha256[:16]}",)))

    # 逐卡严格校验（v0.2）：任何一张卡不合规都不能靠组合汇总补救。
    for index, item in enumerate(proof["scenarios"]):
        try:
            _validate_card(cards[index], total=int(item["case_count"]),
                           run_id=item["run_id"], config_hash=item["config_hash"])
        except _H2Error as exc:
            rows.append(row_blocked(f"h2.card.{item['scenario_id']}",
                                    f"H2 场景卡 {item['scenario_id']}", exc.reason,
                                    cause=exc.cause, detail=exc.detail))
        else:
            rows.append(row_ok(f"h2.card.{item['scenario_id']}",
                               f"H2 场景卡 {item['scenario_id']}（v0.2 严格校验）",
                               detail={"case_count": item["case_count"],
                                       "turns_executed": item["turns_executed"],
                                       "derived_card_sha256": item["derived_card_sha256"]}))

    # 覆盖与回合：30 题 / 36 回合 / 五层 10-5-5-5-5。
    strata = {name: int(bucket["total"]) for name, bucket in validated["by_stratum"].items()}
    coverage_detail = {
        "total": validated["total"],
        "turns_planned": validated["turns_planned"],
        "turns_executed": validated["turns_executed"],
        "by_stratum": strata,
    }
    if validated["total"] != 30 or validated["turns_executed"] != 36 or validated["not_started"]:
        rows.append(row_blocked("h2.coverage", "H2 同批 30 题 36 回合", R_SAMPLE_BELOW_MIN,
                                cause="coverage_incomplete", detail=coverage_detail))
    else:
        rows.append(row_ok("h2.coverage", "H2 同批 30 题 36 回合", detail=coverage_detail))
    if strata != expected_strata:
        rows.append(row_blocked("h2.strata", "H2 五层齐全（10/5/5/5/5）", R_EVIDENCE_MISSING,
                                cause="strata_mismatch",
                                detail={"expected": expected_strata, "observed": strata}))
    else:
        rows.append(row_ok("h2.strata", "H2 五层齐全（10/5/5/5/5）", detail={"by_stratum": strata}))

    # 质量与硬失败。
    passed = int(validated["passed"])
    min_pass = int(standards.holdout_min_pass) if standards is not None else 24
    if passed < min_pass:
        rows.append(row_blocked("h2.quality", f"H2 正确 ≥{min_pass}/30",
                                R_QUALITY_BELOW_THRESHOLD, cause=f"{passed} < {min_pass}",
                                detail={"passed": passed, "failed": validated["failed"],
                                        "errors": validated["errors"]}))
    else:
        rows.append(row_ok("h2.quality", f"H2 正确 ≥{min_pass}/30", detail={
            "passed": passed, "failed": validated["failed"], "errors": validated["errors"]}))
    hard_failures = int(validated["hard_failures"])
    if hard_failures != 0:
        rows.append(row_blocked("h2.hard_failures", "H2 硬失败 0", R_HARD_FAILURE,
                                cause=f"hard_failures={hard_failures}",
                                detail={"hard_failures": hard_failures,
                                        "by_kind": dict(validated["hard_failures_by_kind"])}))
    else:
        rows.append(row_ok("h2.hard_failures", "H2 硬失败 0", detail={
            "hard_failures": 0, "by_kind": dict(validated["hard_failures_by_kind"])}))

    # 三视图分离：必需轴 / 非必需轴 / 整卡 verified。
    hard_evidence = validated["hard_evidence"]
    axes = {name: {key: int(value) for key, value in block.items()}
            for name, block in hard_evidence["axes"].items()}
    annotation_axes = {name: {key: int(value) for key, value in block.items()}
                       for name, block in validated["annotation"]["axis_counts"].items()}
    required_axes = {name: block for name, block in axes.items()
                     if annotation_axes.get(name, {}).get("required", 0) > 0}
    non_required_axes = {name: block for name, block in axes.items()
                         if annotation_axes.get(name, {}).get("required", 0) == 0}
    required_unknown = sum(block["unknown"] for block in required_axes.values())
    required_violations = sum(block["violations"] for block in required_axes.values())
    required_detail = {
        "required_axes": sorted(required_axes),
        "per_axis": required_axes,
        "annotation": {name: annotation_axes.get(name, {}) for name in required_axes},
        "required_unknown": required_unknown,
        "required_violations": required_violations,
    }
    if required_violations:
        rows.append(row_blocked("h2.required_axes", "H2 必需轴无违规", R_HARD_FAILURE,
                                cause="required_axis_violation", detail=required_detail))
    elif required_unknown:
        rows.append(row_blocked("h2.required_axes", "H2 必需轴无未知", R_REQUIRED_UNKNOWN,
                                cause="required_axis_unknown", detail=required_detail))
    else:
        rows.append(row_ok("h2.required_axes", "H2 必需轴无违规/无未知", detail=required_detail))

    non_required_unknown = sum(block["unknown"] for block in non_required_axes.values())
    c25 = dict(proof["c25_non_required_unknown"])
    rows.append(row_observed("h2.non_required_axes", "H2 非必需轴未知（C25 原口径）", detail={
        "non_required_axes": sorted(non_required_axes),
        "per_axis": non_required_axes,
        "annotation": {name: annotation_axes.get(name, {}) for name in non_required_axes},
        "non_required_unknown": non_required_unknown,
        "declared_c25": c25,
        "count_matches": non_required_unknown == int(c25.get("count") or 0),
    }))
    rows.append(row_observed("h2.card_verified", "H2 整卡 verified（如实展示）", detail={
        "verified": bool(hard_evidence["verified"]),
        "classification_status": "classified" if hard_evidence["verified"] else "unverified",
        "missing_evidence_cases": hard_evidence["missing_evidence_cases"],
        "evidence_complete_cases": hard_evidence["evidence_complete_cases"],
        "non_required_unknown": non_required_unknown,
        "note": "整卡 verified 受非必需 unknown 影响；总门按必需轴判定，两者分列",
    }))
    evidence = H2Evidence(
        composition=validated,
        proof=proof,
        cards=tuple(cards),
        axis_counts=axes,
        annotation_axes=annotation_axes,
        card_verified=bool(hard_evidence["verified"]),
        classification_status="classified" if hard_evidence["verified"] else "unverified",
    )
    return tuple(rows), evidence


def _blocked_rows(exc: _H2Error) -> tuple[ReleaseRow, ...]:
    base = row_blocked("h2", "H2 严格校验", exc.reason, cause=exc.cause, detail=exc.detail)
    return (
        base,
        row_blocked("h2.composition", "H2 四场景组合严格校验", exc.reason,
                    cause=exc.cause, detail=exc.detail),
        row_blocked("h2.required_axes", "H2 必需轴无未知", exc.reason,
                    cause=exc.cause, detail=exc.detail),
    )


__all__ = [
    "H2_CLASSIFIER_SOURCES",
    "H2Evidence",
    "assess_h2",
    "classifier_source_sha256",
]
