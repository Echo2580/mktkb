"""正式门禁的公开证据核验：B0 准入、N/C/U 复算、八项硬门禁适用性。

复用而非重写：

* B0 直接调 :func:`p2_b0.check_b0_admission`（便携准入证明 + 原最小样本）；
* N/C/U 逐题分直接调 :func:`p2_score_run.score_run`（同一评分器、同一身份检查）；
* 八项硬门禁调 :func:`p2_scoring.evaluate_p2_hard_gates`（冻结配置 + 原最小样本）。

本模块不发起任何网络/模型/OCR 调用：只读既有 run 工件与冻结题集。
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .dataset import CaseSpec, cases_to_jsonl
from .gate import GATE_STATUS_NOT_APPLICABLE, GATE_STATUS_PASS, HARD_GATE_IDS
from .p2_b0 import B0_DOCUMENT_CODES, B0Error, check_b0_admission
from .p2_release_inputs import (
    FROZEN_TEMPLATE_CONFIG_HASH,
    FROZEN_TEMPLATE_PATH,
    FROZEN_TEMPLATE_SHA256,
    GATE_SUITE_NAME,
    ReleaseInputs,
    RunBinding,
)
from .p2_release_model import (
    APPLICABILITY_SCHEMA_VERSION,
    R_INPUTS_INVALID,
    DECISION_OBSERVED,
    R_APPLICABILITY_INVALID,
    R_CITATION_GROUNDING_MISSING,
    R_CROSS_PLAN_MERGE,
    R_DIGEST_MISMATCH,
    R_DUPLICATE_EVIDENCE,
    R_EVIDENCE_MISSING,
    R_GATE_CONFIG_UNAPPROVED,
    R_HARD_FAILURE,
    R_IDENTITY_MISMATCH,
    R_NOT_EXECUTED,
    R_QUALITY_BELOW_THRESHOLD,
    R_REQUIRED_UNKNOWN,
    R_SAMPLE_BELOW_MIN,
    R_VERSION_MISMATCH,
    ReleaseGateError,
    ReleaseRow,
    file_sha256,
    payload_sha256,
    row_blocked,
    row_observed,
    row_ok,
    sha256_bytes,
    source_bundle_sha256,
)
from .p2_scoring import (
    CASE_STATUS_ERROR,
    P2_BOUNDARY_IDS,
    P2_NEGATIVE_IDS,
    P2_UPDATE_DELETE_IDS,
    CASE_STATUS_NOT_EXECUTED,
    CASE_STATUS_PASS,
    P2GateConfig,
    build_gate_rows,
    build_gate_run,
    evaluate_p2_hard_gates,
    load_p2_gate_config,
)
from .p2_score_run import load_cases_file, load_document_codes, score_run

#: 派生评分器身份的绑定文件（改评分器即改摘要，历史适用性随之失效）。
SCORER_SOURCES: tuple[str, ...] = ("p2_scoring.py", "p2_score_run.py")

#: 参与"实质口径"比较的顶层键（status/approval/notes 属授权元数据，不参与）。
_SUBSTANTIVE_KEYS = (
    "gate_version",
    "schema_version",
    "hard_gates",
    "hard_gate_min_sample",
    "suites",
    "sensitive_patterns",
    "metrics",
)
#: p2_standards 里参与实质比较的子键（status/approver/approved_at/basis 是授权元数据）。
_STANDARDS_SUBSTANTIVE_KEYS = ("b0", "negative", "boundary", "update_delete", "holdout", "denominators")


# --------------------------------------------------------------------------- #
# 评分器身份与实质口径
# --------------------------------------------------------------------------- #


def scorer_source_sha256() -> str:
    """派生评分器身份：只绑实现逐题复算的那几个源文件（位置由本模块定位）。"""
    root = Path(__file__).resolve().parent
    return source_bundle_sha256([root / name for name in SCORER_SOURCES])


def substantive_projection(raw: Mapping[str, Any]) -> dict[str, Any]:
    """把配置投影成"实质口径"：准入阈值、硬门禁、最小样本、诊断指标。"""
    projection: dict[str, Any] = {key: raw.get(key) for key in _SUBSTANTIVE_KEYS}
    standards = raw.get("p2_standards")
    if isinstance(standards, Mapping):
        projection["p2_standards"] = {
            key: standards.get(key) for key in _STANDARDS_SUBSTANTIVE_KEYS
        }
    return projection


# --------------------------------------------------------------------------- #
# 适用性证明（新契约）：绑定原证据 + 目标配置 + 派生评分器身份
# --------------------------------------------------------------------------- #


def build_applicability_proof(
    binding: RunBinding,
    cases: Sequence[CaseSpec],
    statuses: Mapping[str, str],
    *,
    gate_config: P2GateConfig,
    gate_config_path: Path,
) -> dict[str, Any]:
    """按原证据重算一份适用性证明（与 B0 便携证明同构：声明值必须等于重算值）。"""
    template_path = FROZEN_TEMPLATE_PATH
    template_raw = json.loads(template_path.read_text(encoding="utf-8"))
    template = load_p2_gate_config(template_path)
    approved_raw = dict(gate_config.raw)
    return {
        "schema_version": APPLICABILITY_SCHEMA_VERSION,
        "run_id": binding.run_id,
        "original": {
            "gate_config_sha256": file_sha256(template_path),
            "gate_config_hash": template.config_hash,
            "gate_version": template.gate_version,
            "pipeline_version": binding.manifest.get("pipeline_version"),
            "index_revision": binding.manifest.get("index_revision"),
            "dataset_version": binding.manifest.get("dataset_version"),
            "artifact_sha256": dict(binding.artifacts),
        },
        "target": {
            "gate_config_sha256": file_sha256(gate_config_path),
            "gate_config_hash": gate_config.config_hash,
            "gate_version": gate_config.gate_version,
            "substantive_projection_sha256": payload_sha256(substantive_projection(approved_raw)),
            "original_substantive_projection_sha256": payload_sha256(substantive_projection(template_raw)),
        },
        "case_scope": {
            "case_ids": [case.case_id for case in cases],
            "cases_sha256": sha256_bytes(cases_to_jsonl(cases).encode("utf-8")),
        },
        "derivation": {
            "scorer": "p2_score_run.score_run",
            "scorer_source_sha256": scorer_source_sha256(),
            "statuses_sha256": payload_sha256({case.case_id: statuses[case.case_id] for case in cases}),
            "passed": sum(1 for case in cases if statuses[case.case_id] == CASE_STATUS_PASS),
            "total": len(cases),
        },
    }


def _validate_applicability(
    declared: Mapping[str, Any],
    rebuilt: Mapping[str, Any],
    *,
    binding: RunBinding,
) -> None:
    """旧版本适用性必须逐字段等于重算值；伪造/过期都在这里被拒。"""
    if declared.get("schema_version") != APPLICABILITY_SCHEMA_VERSION:
        raise _ApplicabilityError("schema 版本不符", {"observed": declared.get("schema_version")})
    original = declared.get("original") if isinstance(declared.get("original"), Mapping) else {}
    target = declared.get("target") if isinstance(declared.get("target"), Mapping) else {}
    if original.get("gate_config_sha256") != FROZEN_TEMPLATE_SHA256:
        raise _ApplicabilityError("原配置不是冻结模板", {"observed": original.get("gate_config_sha256")})
    if original.get("gate_config_hash") != FROZEN_TEMPLATE_CONFIG_HASH:
        raise _ApplicabilityError("原配置加载器摘要不是历史口径", {"observed": original.get("gate_config_hash")})
    if binding.manifest.get("gate_config_hash") != original.get("gate_config_hash"):
        raise _ApplicabilityError("run 并没有绑定该原配置")
    if target.get("substantive_projection_sha256") != target.get("original_substantive_projection_sha256"):
        raise _ApplicabilityError("新旧配置的实质口径不一致（阈值/硬门禁/最小样本被改过）")
    if target.get("gate_config_hash") != rebuilt["target"]["gate_config_hash"]:
        raise _ApplicabilityError("目标配置不是当前批准配置")
    if declared != rebuilt:
        differing = sorted(
            key for key in set(declared) | set(rebuilt) if declared.get(key) != rebuilt.get(key)
        )
        raise _ApplicabilityError("适用性证明与实算不等（伪造或过期）", {"fields": differing})


class _ApplicabilityError(ValueError):
    def __init__(self, cause: str, detail: Mapping[str, Any] | None = None) -> None:
        super().__init__(cause)
        self.cause = cause
        self.detail = dict(detail or {})


# --------------------------------------------------------------------------- #
# B0
# --------------------------------------------------------------------------- #

_B0_ERROR_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("b0_hard_gate_blocked", "hard_gate"), R_HARD_FAILURE),
    (("b0_score_threshold_not_met",), R_QUALITY_BELOW_THRESHOLD),
    (("b0_rows_incomplete", "case_not_executed", "not_executed"), R_NOT_EXECUTED),
    (("b0_evidence_file_missing", "b0_evidence_schema_invalid", "b0_source_changed"), R_EVIDENCE_MISSING),
    (("b0_gate_file_not_approved", "b0_gate_config_not_approved"), R_GATE_CONFIG_UNAPPROVED),
    (("b0_current_pipeline", "b0_portable_cases_not_frozen", "b0_formal_binding_mismatch"), R_VERSION_MISMATCH),
    (
        (
            "b0_run_identity_invalid",
            "b0_live_authorization_invalid",
            "b0_trace_binding_invalid",
            "b0_trace_path_mismatch",
            "b0_document_codes",
            "b0_corpus",
            "b0_answer_plan",
            "b0_query_plan",
            "b0_operation",
            "b0_private",
            "b0_citation_evidence_invalid",
            "b0_score_binding_mismatch",
            "b0_outbound_evidence_invalid",
        ),
        R_IDENTITY_MISMATCH,
    ),
    (("b0_portable_evidence_mismatch", "b0_portable_hard_gate_mismatch", "b0_source_changed"), R_DIGEST_MISMATCH),
)


def classify_b0_error(code: str) -> str:
    for prefixes, reason in _B0_ERROR_MAP:
        if any(prefix in code for prefix in prefixes):
            return reason
    return R_REQUIRED_UNKNOWN


@dataclass(frozen=True)
class B0Evidence:
    admission: Any
    config: P2GateConfig


def assess_b0(inputs: ReleaseInputs) -> tuple[tuple[ReleaseRow, ...], B0Evidence | None]:
    """B0：便携准入重算 + 40/40、≥36/40、24/24、8/8 执行 + 原最小样本。"""
    rows: list[ReleaseRow] = []
    try:
        admission = check_b0_admission(
            inputs.b0_run_dir,
            inputs.gate_config,
            portable_proof=inputs.b0_admission.payload,
            document_codes_path=B0_DOCUMENT_CODES,
        )
    except B0Error as exc:
        reason = classify_b0_error(exc.code)
        return (
            (
                row_blocked("b0.admission", "B0 准入重算", reason, cause=exc.code,
                            evidence=("var/eval/baselines/7981d4afc2d1/b0-admission.json",)),
                row_blocked("b0.execution", "B0 执行 40/40", reason, cause=exc.code),
                row_blocked("b0.quality", "B0 正确 ≥36/40", reason, cause=exc.code),
                row_blocked("b0.exact", "B0 精确 24/24", reason, cause=exc.code),
                row_blocked("b0.ocr", "B0 OCR 8/8 执行", reason, cause=exc.code),
            ),
            None,
        )
    proof = admission.proof
    tally = proof["b0"]
    standards = inputs.gate_config.standards
    hard = proof["hard_gate"]
    evidence = (
        f"b0-admission:{payload_sha256(proof)[:16]}",
        f"run:{proof['run_id']}",
    )
    rows.append(
        row_ok("b0.admission", "原 B0 准入留存（便携证明重算）", detail={
            "run_id": proof["run_id"],
            "gate_config_hash": proof["gate_config_hash"],
            "plan_sha256": proof["plan_sha256"],
            "real_calls": proof["real_calls"],
            "p2_release_status": proof["p2_release_status"],
        }, evidence=evidence)
    )
    rows.append(_threshold_row("b0.execution", "B0 执行 40/40",
                               got=tally["executed"], need=standards.b0_total,
                               detail={"planned": tally["planned"], "executed": tally["executed"]},
                               evidence=evidence))
    rows.append(_threshold_row("b0.quality", f"B0 正确 ≥{standards.b0_min_pass}/{standards.b0_total}",
                               got=tally["passed"], need=standards.b0_min_pass,
                               detail={"passed": tally["passed"], "failed": tally["failed"],
                                       "errors": tally["errors"], "not_executed": tally["not_executed"]},
                               evidence=evidence))
    rows.append(_threshold_row("b0.exact", f"B0 精确 {standards.b0_exact_total}/{standards.b0_exact_total}",
                               got=tally["exact_passed"], need=standards.b0_exact_total,
                               detail={"exact_planned": tally["exact_planned"],
                                       "exact_passed": tally["exact_passed"]},
                               evidence=evidence))
    rows.append(_threshold_row("b0.ocr", f"B0 OCR {standards.b0_ocr_total}/{standards.b0_ocr_total} 执行",
                               got=tally["ocr_executed"], need=standards.b0_ocr_total,
                               detail={"ocr_planned": tally["ocr_planned"],
                                       "ocr_executed": tally["ocr_executed"],
                                       "ocr_passed": tally["ocr_passed"]},
                               evidence=evidence))

    # 候选流水线必须就是 B0 绑定的那一份：跨版本需重新登记基线，不能"顺延"。
    bound_pipeline = str(proof.get("pipeline_version") or "")
    bound_source = bound_pipeline.split("+")[-1] if "+" in bound_pipeline else ""
    if bound_source != inputs.candidate_pipeline_sha256:
        rows.append(row_blocked(
            "candidate.pipeline", "候选流水线与 B0 绑定一致", R_VERSION_MISMATCH,
            cause="candidate_pipeline_mismatch",
            detail={"bound": bound_source, "candidate": inputs.candidate_pipeline_sha256},
        ))
    else:
        rows.append(row_ok("candidate.pipeline", "候选流水线与 B0 绑定一致", detail={
            "pipeline_source_sha256": bound_source,
            "pipeline_version": bound_pipeline,
        }))

    hard_row = _hard_gate_row("hard_gates.b0", "B0 八项硬门禁（原最小样本）", hard, suite="b0",
                              config=inputs.gate_config)
    rows.append(hard_row)
    return tuple(rows), B0Evidence(admission=admission, config=inputs.gate_config)


def _threshold_row(row_id: str, title: str, *, got: int, need: int, detail: Mapping[str, Any],
                   evidence: Sequence[str]) -> ReleaseRow:
    if got >= need:
        return row_ok(row_id, title, detail=dict(detail), evidence=evidence)
    reason = R_NOT_EXECUTED if row_id in {"b0.execution", "b0.ocr"} else R_QUALITY_BELOW_THRESHOLD
    return row_blocked(row_id, title, reason, cause=f"{got} < {need}",
                       detail=dict(detail), evidence=evidence)


_SUITE_STANDARDS_ATTR: Mapping[str, str] = {
    "b0": "b0_total",
    "negative": "negative_total",
    "boundary": "boundary_total",
    "update_delete": "update_delete_total",
}


def min_sample_coverage(
    *, standards: Any, gate_config: P2GateConfig, suite: str, run_level_evaluated: int
) -> dict[str, Any]:
    """D-011（主人授权）：min-sample 覆盖判定按 **suite 计划题数** 计。

    * ``suite_planned_cases`` 只从**已批准配置**的 ``p2_standards`` 读，不接受调用方/清单声明
      （伪造计划数会与 ``p2_standards.total`` 不符，直接拒）；
    * ``required_min_sample`` 仍取冻结配置的 ``hard_gate_min_sample``；
    * ``run_level_evaluated`` 只是**披露**：硬门禁实际仍在 run 级子集上评估。
    """
    attribute = _SUITE_STANDARDS_ATTR.get(suite)
    if attribute is None or standards is None:
        raise _SuiteError("", R_EVIDENCE_MISSING, f"min_sample_coverage_unsupported_suite:{suite}")
    planned = int(getattr(standards, attribute))
    required = gate_config.config.min_sample_for(GATE_SUITE_NAME.get(suite, suite))
    if required is None:
        raise _SuiteError("", R_SAMPLE_BELOW_MIN, f"min_sample_missing:{suite}")
    return {
        "suite": suite,
        "suite_planned_cases": planned,
        "required_min_sample": int(required),
        "run_level_evaluated": int(run_level_evaluated),
        "basis": "suite_planned_cases",
        "covered": planned >= int(required),
    }


def _hard_gate_row(row_id: str, title: str, proof: Mapping[str, Any], *, suite: str,
                   config: P2GateConfig) -> ReleaseRow:
    gate_status = dict(proof.get("gate_status") or {})
    min_sample = proof.get("min_sample")
    scored = proof.get("scored_count")
    expected_min = config.config.min_sample_for(GATE_SUITE_NAME.get(suite, suite))
    coverage = min_sample_coverage(
        standards=config.standards, gate_config=config, suite=suite,
        run_level_evaluated=int(scored) if isinstance(scored, int) else 0,
    )
    detail: dict[str, Any] = {
        "gate_status": gate_status,
        "min_sample": min_sample,
        "expected_min_sample": expected_min,
        "scored_count": scored,
        "min_sample_coverage": coverage,
        "source_hit_basis": proof.get("source_hit_basis", "frozen_case_gold"),
    }
    if proof.get("unknowns"):
        detail["unknowns"] = list(proof["unknowns"])[:8]
    if proof.get("resolved_unknowns"):
        detail["resolved_unknowns"] = list(proof["resolved_unknowns"])[:8]
    if proof.get("hard_failures") or proof.get("exit_code") == 1:
        return row_blocked(row_id, title, R_HARD_FAILURE, cause="hard_failures",
                           detail={**detail, "hard_failures": list(proof.get("hard_failures") or ())})
    if set(gate_status) != set(HARD_GATE_IDS):
        return row_blocked(row_id, title, R_EVIDENCE_MISSING, cause="hard_gate_status_incomplete",
                           detail=detail)
    bad = sorted(name for name, state in gate_status.items()
                 if state not in {GATE_STATUS_PASS, GATE_STATUS_NOT_APPLICABLE})
    unknown_ids = {str(item.get("check_id")) for item in proof.get("unknowns") or ()}
    disclosed_only = bool(unknown_ids) and unknown_ids <= {"min_sample_not_met"}
    if bad or (proof.get("unknowns") and not disclosed_only) or proof.get("exit_code") not in {0, 3}:
        return row_blocked(
            row_id, title, R_REQUIRED_UNKNOWN,
            cause="hard_gate_unresolved",
            detail={**detail, "unresolved": bad, "exit_code": proof.get("exit_code"),
                    "unknowns": unknown_ids},
        )
    if expected_min is not None and (not isinstance(min_sample, int) or min_sample != expected_min):
        return row_blocked(row_id, title, R_VERSION_MISMATCH, cause="hard_gate_min_sample_mismatch",
                           detail=detail)
    # D-011：覆盖判定用 suite 计划题数；run 级子集的实际评估数只披露。
    if not coverage["covered"]:
        return row_blocked(
            row_id, title, R_SAMPLE_BELOW_MIN, cause="suite_planned_below_min_sample",
            detail={**detail, "cause_detail": "suite_planned_cases < required_min_sample"},
        )
    if disclosed_only:
        detail["disclosed"] = {
            "check": "min_sample_not_met",
            "note": "run 级子集小于 hard_gate_min_sample；按 D-011 以 suite 计划题数判定覆盖，"
                    "该项只披露不阻断",
        }
    return row_ok(row_id, title, detail=detail)


# --------------------------------------------------------------------------- #
# 公开套件（N/C/U）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SuiteEvidence:
    suite: str
    cases: tuple[CaseSpec, ...]
    statuses: Mapping[str, str]
    run_ids: tuple[str, ...]
    selected_sha256: str
    gate_proof: Mapping[str, Any]
    min_sample: int
    scored_count: int
    #: 逐题 -> run_id 的冻结归属（适用性证明的范围只取该 run 自己跑的题）。
    assignment: Mapping[str, str] = None  # type: ignore[assignment]


def _load_run_cases(binding: RunBinding) -> tuple[CaseSpec, ...]:
    return load_cases_file(binding.run_dir / "dataset.jsonl")


def assert_single_plan(binding: RunBinding) -> None:
    """一个 run 目录只能含一份计划的逐题行；跨计划拼装在这里被拒。"""
    dataset_ids = [case.case_id for case in _load_run_cases(binding)]
    if len(dataset_ids) != len(set(dataset_ids)):
        raise _SuiteError(binding.run_id, R_DUPLICATE_EVIDENCE, "dataset_duplicate_case")
    rows = [json.loads(line) for line in binding.artifact_bytes("cases.jsonl").splitlines() if line.strip()]
    run_ids = {str(row.get("run_id") or "") for row in rows}
    if run_ids != {binding.run_id}:
        raise _SuiteError(binding.run_id, R_CROSS_PLAN_MERGE, "cases_rows_from_multiple_runs")
    row_ids = [str(row.get("case_id") or "") for row in rows]
    if len(row_ids) != len(set(row_ids)):
        raise _SuiteError(binding.run_id, R_DUPLICATE_EVIDENCE, "cases_rows_duplicated")
    # 缺行/多行不在这里判：交给评分器如实记 not_executed / outside_plan（不静默补题）。
    plan_ids = {
        str(((row.get("turns") or [{}])[0].get("ticket") or {}).get("plan_id") or "")
        for row in rows if row.get("turns")
    }
    plan_ids.discard("")
    if len(plan_ids) > 1:
        raise _SuiteError(binding.run_id, R_CROSS_PLAN_MERGE, "multiple_plan_ids")


def _score_binding(
    binding: RunBinding,
    *,
    cases: Sequence[CaseSpec],
    document_codes: Mapping[str, str],
) -> Mapping[str, Any]:
    try:
        bundle = score_run(binding.run_dir, cases=cases, document_codes=document_codes)
    except Exception as exc:  # RunScoreError / 结构异常都按缺证处理，不猜
        raise _SuiteError(binding.run_id, R_EVIDENCE_MISSING, f"score_run_failed:{exc}") from None
    return {item.score.case_id: item for item in bundle.scored}


class _SuiteError(ValueError):
    def __init__(self, run_id: str, reason: str, cause: str) -> None:
        super().__init__(f"{run_id}: {cause}")
        self.run_id = run_id
        self.reason = reason
        self.cause = cause


def collect_suite(
    suite: str,
    assignment: Mapping[str, str],
    runs: Mapping[str, RunBinding],
    *,
    document_codes: Mapping[str, str],
    gate_config: P2GateConfig,
    project_root: Path | None = None,
    rag_resolvers: Mapping[str, Path] | None = None,
) -> SuiteEvidence:
    """按冻结选题范围逐 run 复算，再做一次套件级硬门禁（不跨计划挑分数）。"""
    cases: list[CaseSpec] = []
    statuses: dict[str, str] = {}
    scored_rows: list[Any] = []
    lines: list[str] = []
    raw_by_id: dict[str, Mapping[str, Any]] = {}
    run_ids: list[str] = []
    cache: dict[str, tuple[tuple[CaseSpec, ...], Mapping[str, Any]]] = {}
    for case_id in assignment:
        run_id = assignment[case_id]
        binding = runs[run_id]
        if suite not in binding.suites:
            raise _SuiteError(run_id, R_IDENTITY_MISMATCH, f"run_suite_not_declared:{suite}")
        if run_id not in cache:
            assert_single_plan(binding)
            run_cases = _load_run_cases(binding)
            cache[run_id] = (run_cases, _score_binding(binding, cases=run_cases,
                                                       document_codes=document_codes))
        run_cases, scored = cache[run_id]
        case = next((item for item in run_cases if item.case_id == case_id), None)
        if case is None:
            raise _SuiteError(run_id, R_EVIDENCE_MISSING, f"case_not_in_run:{case_id}")
        if str(case.suite) != suite:
            raise _SuiteError(run_id, R_IDENTITY_MISMATCH, f"case_suite_mismatch:{case_id}")
        item = scored.get(case_id)
        if item is None:
            raise _SuiteError(run_id, R_EVIDENCE_MISSING, f"case_not_scored:{case_id}")
        cases.append(case)
        scored_rows.append(item)
        statuses[case_id] = item.score.status
        lines.append(_raw_dataset_line(binding, case_id))
        try:
            raw_by_id[case_id] = json.loads(_raw_product_row(binding, case_id))
        except (_SuiteError, ReleaseGateError):
            # 缺逐题产品行 = 未执行；不在这里造证据，交给评分器如实记 not_executed。
            raw_by_id[case_id] = {}
        if run_id not in run_ids:
            run_ids.append(run_id)
    selected_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    proof = _suite_hard_gates(suite, cases, scored_rows, runs[run_ids[0]], gate_config, selected_bytes,
                              rag_resolvers=rag_resolvers, raw_by_id=raw_by_id)
    return SuiteEvidence(
        suite=suite,
        cases=tuple(cases),
        statuses=statuses,
        run_ids=tuple(run_ids),
        selected_sha256=sha256_bytes(selected_bytes),
        gate_proof=proof,
        min_sample=int(proof["min_sample"]),
        scored_count=int(proof["scored_count"]),
        assignment=dict(assignment),
    )


def _raw_dataset_line(binding: RunBinding, case_id: str) -> str:
    """从原 dataset.jsonl 取该题的冻结 CaseSpec 行（用于套件级 dataset 视图）。"""
    return _find_line(binding, "dataset.jsonl", case_id, "raw_dataset_line_missing")


def _raw_product_row(binding: RunBinding, case_id: str) -> str:
    """从原 cases.jsonl 取该题的**产品行**（D-004 需要其中的 ``product.evidence``）。"""
    return _find_line(binding, "cases.jsonl", case_id, "raw_product_row_missing")


def _find_line(binding: RunBinding, artifact: str, case_id: str, missing: str) -> str:
    for line in binding.artifact_bytes(artifact).decode("utf-8").splitlines():
        if not line.strip():
            continue
        if json.loads(line).get("case_id") == case_id:
            return line
    raise _SuiteError(binding.run_id, R_EVIDENCE_MISSING, f"{missing}:{case_id}")


def _suite_hard_gates(
    suite: str,
    cases: Sequence[CaseSpec],
    scored: Sequence[Any],
    base: RunBinding,
    gate_config: P2GateConfig,
    selected_bytes: bytes,
    *,
    rag_resolvers: Mapping[str, Path] | None = None,
    raw_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> Mapping[str, Any]:
    """套件级硬门禁：行来自原 run，分母是冻结选题范围，最小样本按批准配置。"""
    suite_name = GATE_SUITE_NAME[suite]
    rows = build_gate_rows(cases, scored, case_rows=raw_by_id)
    with tempfile.TemporaryDirectory(prefix="p2-release-subset-") as directory:
        dataset = Path(directory) / "dataset.jsonl"
        dataset.write_bytes(selected_bytes)
        manifest = dict(base.manifest)
        manifest.update({"suite": suite_name, "case_count": len(cases), "dataset_path": str(dataset)})
        try:
            run = build_gate_run(run_dir=base.run_dir, manifest=manifest, cases=cases,
                                 rows=rows, summary=base.summary)
            hard = evaluate_p2_hard_gates(run, config=gate_config, dataset_path=dataset,
                                          require_trace=False)
        except Exception as exc:
            raise _SuiteError(base.run_id, R_EVIDENCE_MISSING, f"hard_gate_failed:{exc}") from None
    by_id = {case.case_id: case for case in cases}
    unresolved: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    for item in hard.unknowns:
        record = {"gate_id": item.gate_id, "case_id": item.case_id, "check_id": item.check_id,
                  "reason": item.reason}
        if (item.check_id == "record_code_only_gold" and item.case_id
                and rag_resolvers and item.case_id in rag_resolvers):
            case = by_id.get(str(item.case_id))
            codes = [str(ref.get("record_code") or "") for ref in (case.expected_sources if case else ())]
            codes = [code for code in codes if code]
            units: list[dict[str, Any]] = []
            for code in codes:
                from .p2_release_binding import record_code_units

                units.extend(record_code_units(rag_resolvers[item.case_id], code))
            unique = {unit["unit_key"]: unit for unit in units if unit.get("unit_key")}
            if len(unique) == 1:
                unit = next(iter(unique.values()))
                resolved.append({**record, "unit_key": unit["unit_key"], "sheet": unit.get("sheet"),
                                 "row": unit.get("row"),
                                 "basis": "record_reconstruction"})
                continue
        unresolved.append(record)
    return {
        "gate_status": dict(hard.gate_status),
        "exit_code": int(hard.exit_code),
        "hard_failures": list(hard.hard_failures),
        "unknowns": unresolved,
        "resolved_unknowns": resolved,
        "source_hit_basis": "record_reconstruction" if resolved else "frozen_case_gold",
        "min_sample": int(hard.min_sample if hard.min_sample is not None else -1),
        "scored_count": int(hard.scored_count),
    }


def _run_hard_gates_on_run(
    binding: RunBinding,
    *,
    cases: Sequence[CaseSpec],
    gate_config: P2GateConfig,
    document_codes: Mapping[str, str],
    index_revision: int,
    trace_store: Path | None = None,
) -> dict[str, Any]:
    """在**整份 run** 上跑一次硬门禁（可指定 manifest 修订与 trace 视图）。

    绑定适用性证明的"双跑"就靠它：原始视图与修正视图各调一次，两次结果都保留。
    """
    from .p2_score_run import score_run

    bundle = score_run(binding.run_dir, cases=cases, document_codes=document_codes)
    raw_by_id = {case.case_id: json.loads(_raw_product_row(binding, case.case_id))
                 for case in cases}
    rows = build_gate_rows(cases, bundle.scored, case_rows=raw_by_id)
    manifest = dict(binding.manifest)
    manifest.update({
        "index_revision": int(index_revision),
        "dataset_path": str(binding.run_dir / "dataset.jsonl"),
    })
    if trace_store is not None:
        manifest["trace_store"] = str(trace_store)
    try:
        run = build_gate_run(run_dir=binding.run_dir, manifest=manifest, cases=cases,
                             rows=rows, summary=binding.summary)
        hard = evaluate_p2_hard_gates(run, config=gate_config,
                                      dataset_path=binding.run_dir / "dataset.jsonl",
                                      require_trace=trace_store is not None)
    except Exception as exc:  # 结构异常：按缺证处理，不猜
        raise _SuiteError(binding.run_id, R_EVIDENCE_MISSING, f"binding_gate_failed:{exc}") from None
    failures = [item for item in hard.failures if item.check_id == "version_binding"]
    return {
        "gate_status": dict(hard.gate_status),
        "exit_code": int(hard.exit_code),
        "binding_failures": sorted({str(item.case_id) for item in failures if item.case_id}),
        "trace_integrity": hard.gate_status.get("trace_integrity"),
        "scored_count": int(hard.scored_count),
        "min_sample": None if hard.min_sample is None else int(hard.min_sample),
        "unknowns": [{"gate_id": item.gate_id, "check_id": item.check_id} for item in hard.unknowns],
    }


def cross_check_evidence_manifest(
    inputs: ReleaseInputs,
    *,
    suites: Mapping[str, SuiteEvidence],
    u_evidence: SuiteEvidence | None,
) -> tuple[ReleaseRow, ...]:
    """与任务 3 v3 清单交叉核对：SHA 清单、范围、身份、四档、两行 tally。

    关键纪律（经理 2026-11-21 要求）：

    * 四档状态**原样承接**：``ADOPTED`` 与 ``ADOPTED_WITH_BINDING_PROOF`` 分列，
      不折叠、不把 ``trace_integrity=fail`` 写成 pass；
    * ``ADOPTED_WITH_BINDING_PROOF`` 必须同时具备非空 ``binding_proof`` 与
      ``mechanical_gate_failures``（且失败项只能是 ``trace_integrity/version_binding``）；
      若 ``gates.trace_integrity.status`` 被改成 ``pass``，视为篡改并阻断；
    * 两行 tally 都出：无条件可采、正式可采（含 D-005）；两者都要求与清单逐组相等；
    * ``SHA256SUMS`` 逐行重算，任一文件缺失/不符即阻断。
    """
    from .p2_release_model import R_QUALITY_BELOW_THRESHOLD, row_blocked, row_observed

    bound = inputs.evidence_manifest
    if bound is None:
        return ()
    payload = bound.payload
    if not isinstance(payload, Mapping):
        return (row_blocked("evidence_manifest", "任务 3 清单交叉核对", R_INPUTS_INVALID,
                            cause="manifest_not_object"),)
    rows: list[ReleaseRow] = []
    problems: list[dict[str, Any]] = []

    # 0) SHA256SUMS 逐行重算
    sums_ok = sums_bad = sums_missing = 0
    if inputs.evidence_sums is not None:
        root = inputs.evidence_sums.path.parent
        for line in inputs.evidence_sums.path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            digest, _, relative = text.partition("  ")
            target = root / relative
            if not target.is_file():
                sums_missing += 1
                problems.append({"sha256sums": "missing", "path": relative})
                continue
            actual = file_sha256(target)
            if actual == digest:
                sums_ok += 1
            else:
                sums_bad += 1
                problems.append({"sha256sums": "mismatch", "path": relative,
                                 "declared": digest, "actual": actual})

    # 1) 冻结选题范围
    try:
        frozen = payload["selection_policy"]["frozen_scope"]
    except (KeyError, TypeError):
        frozen = None
    expected: dict[str, dict[str, str]] = {"negative": {}, "boundary": {}, "update_delete": {}}
    if isinstance(frozen, Mapping):
        group_suite = {"N": "negative", "C": "boundary", "U": "update_delete"}
        for run_key, groups in frozen.items():
            if not isinstance(groups, Mapping):
                continue
            for group, case_ids in groups.items():
                suite = group_suite.get(str(group))
                if suite is None:
                    continue
                for case_id in case_ids or ():
                    expected[suite][str(case_id)] = str(run_key)
    scope_cases = sum(len(ids) for ids in expected.values())
    if not scope_cases:
        problems.append({"scope": "frozen_scope_missing_or_empty"})
    else:
        run_id_by_key = {
            str(key): str((item or {}).get("run_id") or "")
            for key, item in (payload.get("runs") or {}).items()
        }
        for suite, ids in expected.items():
            for case_id, run_key in ids.items():
                binding_run_id = run_id_by_key.get(run_key, "")
                if not binding_run_id:
                    problems.append({"scope": f"unknown_run_key:{run_key}"})
                    continue
                if suite in suites:
                    got = suites[suite].assignment.get(case_id)
                elif suite == "update_delete" and u_evidence is not None:
                    got = u_evidence.assignment.get(case_id)
                else:
                    got = None
                if got != binding_run_id:
                    problems.append({"scope": case_id, "expected": binding_run_id, "got": got})

    # 2) 逐题身份 + 四档（原样承接）
    tiers: dict[str, dict[str, int]] = {tier: {"N": 0, "C": 0, "U": 0}
                                       for tier in _ADOPT_TIERS}
    runs = {item.run_id: item for item in inputs.public_runs}
    if inputs.u_real is not None:
        runs[inputs.u_real.run_id] = inputs.u_real
    statuses: dict[str, str] = {}
    for evidence in suites.values():
        statuses.update(evidence.statuses)
    if u_evidence is not None:
        statuses.update(u_evidence.statuses)
    for case in payload.get("cases") or ():
        if not isinstance(case, Mapping):
            continue
        case_id = str(case.get("case_id") or "")
        group = str(case.get("group") or "")
        adopt = str(case.get("adopt") or "")
        local_statuses = _u_local_statuses(inputs)
        if str(case.get("basis") or "") == "L":
            # 本地控制（pytest junit）不是 run 行：只核"该档位是否如声明那样无条件可采"，
            # 状态以 u-controls 为准（不拿清单自报当证据）。
            local = local_statuses.get(case_id)
            if adopt != "ADOPTED":
                problems.append({"case_id": case_id, "tier": adopt,
                                 "note": "本地控制只能是无条件可采档"})
            if local != CASE_STATUS_PASS:
                problems.append({"case_id": case_id, "control_status": local})
            if group in tiers.get(adopt, {}):
                tiers[adopt][group] += 1
            continue
        run_id = str(case.get("run_id") or "")
        binding = runs.get(run_id)
        if binding is None:
            problems.append({"case_id": case_id, "identity": f"run_not_bound:{run_id}"})
            continue
        manifest = binding.manifest
        plan = manifest.get("plan") if isinstance(manifest.get("plan"), Mapping) else {}
        pairs = (
            ("plan_sha256", plan.get("plan_sha256") or manifest.get("plan_sha256")),
            ("config_hash", manifest.get("config_hash")),
            ("gate_config_hash_original", manifest.get("gate_config_hash")),
            ("pipeline_version", manifest.get("pipeline_version")),
            ("index_revision_binding", manifest.get("index_revision")),
        )
        for key, observed in pairs:
            if case.get(key) != observed:
                problems.append({"case_id": case_id, "identity": key,
                                 "declared": case.get(key), "observed": observed})
        status = statuses.get(case_id)
        gates = case.get("gates") if isinstance(case.get("gates"), Mapping) else {}
        failing = sorted(name for name, item in gates.items()
                         if isinstance(item, Mapping)
                         and item.get("status") not in {"pass", "not_applicable"})
        mechanical = [item for item in (case.get("mechanical_gate_failures") or ())
                      if isinstance(item, Mapping)]
        if adopt == "ADOPTED":
            if status != CASE_STATUS_PASS or mechanical or failing:
                problems.append({"case_id": case_id, "tier": adopt, "recomputed": status,
                                 "mechanical": len(mechanical), "failing": failing})
        elif adopt == "ADOPTED_WITH_BINDING_PROOF":
            if status != CASE_STATUS_PASS:
                problems.append({"case_id": case_id, "tier": adopt, "recomputed": status})
            if not case.get("binding_proof"):
                problems.append({"case_id": case_id, "tier": adopt, "binding_proof": "missing"})
            if not mechanical:
                problems.append({"case_id": case_id, "tier": adopt, "mechanical_gate_failures": "empty"})
            bad_mechanical = [item for item in mechanical
                              if item.get("gate") != "trace_integrity"
                              or item.get("check") != "version_binding"]
            if bad_mechanical:
                problems.append({"case_id": case_id, "tier": adopt,
                                 "unexpected_mechanical": bad_mechanical[:3]})
            if set(failing) - {"trace_integrity"}:
                problems.append({"case_id": case_id, "tier": adopt, "failing": failing})
            if str((gates.get("trace_integrity") or {}).get("status")) != "fail":
                # 机械 FAIL 必须保留：把它写成 pass 就是掩盖。
                problems.append({"case_id": case_id, "tier": adopt,
                                 "trace_integrity": "not_preserved_as_fail"})
        elif adopt in {"FAIL", "UNKNOWN"}:
            problems.append({"case_id": case_id, "tier": adopt,
                             "note": "正式清单不应再出现该档（v3 应为 0）"})
        else:
            problems.append({"case_id": case_id, "adopt": f"unknown:{adopt}"})
        if group in tiers.get(adopt, {}):
            tiers[adopt][group] += 1

    # 3) 两行 tally：无条件 / 正式（含 D-005）
    tallies = payload.get("tallies") if isinstance(payload.get("tallies"), Mapping) else {}
    unconditional = tallies.get("adopted_unconditional")
    with_proof = tallies.get("adopted_with_binding_proof")
    formal = tallies.get("adopted_formal_total")
    judged = tallies.get("judged_pass") if isinstance(tallies.get("judged_pass"), Mapping) else {}
    n_statuses = suites["negative"].statuses if "negative" in suites else {}
    c_statuses = suites["boundary"].statuses if "boundary" in suites else {}
    u_statuses = dict(_u_local_statuses(inputs))
    u_statuses.update(u_evidence.statuses if u_evidence is not None else {})
    recomputed_pass = {
        "N": sum(1 for value in n_statuses.values() if value == CASE_STATUS_PASS),
        "C": sum(1 for value in c_statuses.values() if value == CASE_STATUS_PASS),
        "U": sum(1 for case_id in P2_UPDATE_DELETE_IDS
                 if u_statuses.get(case_id) == CASE_STATUS_PASS),
    }
    declared: dict[str, dict[str, int]] = {}
    for label, block in (("unconditional", unconditional), ("with_proof", with_proof),
                         ("formal", formal)):
        if not isinstance(block, Mapping):
            problems.append({"tally": label, "missing": True})
            continue
        declared[label] = {group: int(block.get(group) or 0) for group in ("N", "C", "U")}
    if declared:
        for group in ("N", "C", "U"):
            if declared.get("unconditional", {}).get(group) != tiers["ADOPTED"][group]:
                problems.append({"tally": f"unconditional.{group}",
                                 "declared": declared.get("unconditional", {}).get(group),
                                 "recomputed": tiers["ADOPTED"][group]})
            if declared.get("with_proof", {}).get(group) != tiers["ADOPTED_WITH_BINDING_PROOF"][group]:
                problems.append({"tally": f"with_proof.{group}",
                                 "declared": declared.get("with_proof", {}).get(group),
                                 "recomputed": tiers["ADOPTED_WITH_BINDING_PROOF"][group]})
            expected_formal = (tiers["ADOPTED"][group]
                               + tiers["ADOPTED_WITH_BINDING_PROOF"][group])
            if declared.get("formal", {}).get(group) != expected_formal:
                problems.append({"tally": f"formal.{group}",
                                 "declared": declared.get("formal", {}).get(group),
                                 "recomputed": expected_formal})
            if recomputed_pass[group] != expected_formal:
                problems.append({"tally": f"recomputed_pass.{group}",
                                 "declared": declared.get("formal", {}).get(group),
                                 "recomputed": recomputed_pass[group]})
            declared_judged = str(judged.get(group) or "")
            if declared_judged != f"{recomputed_pass[group]}/{len(_GROUP_TOTALS[group])}":
                problems.append({"tally": f"judged_pass.{group}", "declared": declared_judged,
                                 "recomputed": f"{recomputed_pass[group]}/{len(_GROUP_TOTALS[group])}"})

    if problems:
        rows.append(row_blocked("evidence_manifest", "任务 3 清单交叉核对", R_IDENTITY_MISMATCH,
                                cause="manifest_cross_check_failed",
                                detail={"problems": problems[:12], "count": len(problems),
                                        "sha256sums": {"ok": sums_ok, "bad": sums_bad,
                                                       "missing": sums_missing}},
                                evidence=(f"manifest:{bound.sha256[:16]}",)))
        return tuple(rows)
    rows.append(row_ok("evidence_manifest", "任务 3 清单交叉核对（v3）", detail={
        "manifest_sha256": bound.sha256,
        "report_sha256": None if inputs.evidence_report is None else inputs.evidence_report.sha256,
        "sha256sums": {"sha256": None if inputs.evidence_sums is None
                       else inputs.evidence_sums.sha256,
                       "verified": sums_ok, "mismatch": sums_bad, "missing": sums_missing},
        "scope_cases": scope_cases,
        "tiers": tiers,
        "tallies_declared": declared,
        "tallies_recomputed_pass": recomputed_pass,
    }, evidence=(f"manifest:{bound.sha256[:16]}",)))
    rows.append(row_observed("tallies.unconditional", "无条件可采（无任何机械 FAIL）",
                             detail={"counts": declared.get("unconditional"),
                                     "planned": {"N": 8, "C": 6, "U": 10},
                                     "label": (unconditional or {}).get("label")}))
    rows.append(row_ok("tallies.formal", "正式可采（含 D-005 绑定适用性证明）", detail={
        "counts": declared.get("formal"),
        "unconditional": declared.get("unconditional"),
        "with_binding_proof": declared.get("with_proof"),
        "recomputed_pass": recomputed_pass,
        "label": (formal or {}).get("label"),
        "note": "正式可采 = 无条件 + 证明档；证明档的 trace_integrity 机械 FAIL 原样保留",
    }))
    return tuple(rows)


_ADOPT_TIERS: tuple[str, ...] = ("ADOPTED", "ADOPTED_WITH_BINDING_PROOF", "FAIL", "UNKNOWN")


_GROUP_TOTALS: Mapping[str, tuple[str, ...]] = {
    "N": P2_NEGATIVE_IDS,
    "C": P2_BOUNDARY_IDS,
    "U": P2_UPDATE_DELETE_IDS,
}


def _u_local_statuses(inputs: ReleaseInputs) -> dict[str, str]:
    if inputs.u_controls is None:
        return {}
    cases = inputs.u_controls.payload.get("cases") if isinstance(inputs.u_controls.payload, Mapping) else {}
    if not isinstance(cases, Mapping):
        return {}
    return {str(case_id): str((item or {}).get("status")) for case_id, item in cases.items()}


def assess_suite(
    evidence: SuiteEvidence,
    *,
    title: str,
    row_prefix: str,
    required: int,
    gate_config: P2GateConfig,
) -> tuple[ReleaseRow, ...]:
    """套件判定：逐题状态 -> 通过数/未执行；再单列硬门禁。"""
    rows: list[ReleaseRow] = []
    statuses = evidence.statuses
    passed = sum(1 for value in statuses.values() if value == CASE_STATUS_PASS)
    errors = sum(1 for value in statuses.values() if value == CASE_STATUS_ERROR)
    not_executed = sum(1 for value in statuses.values() if value == CASE_STATUS_NOT_EXECUTED)
    detail = {
        "suite": evidence.suite,
        "total": len(statuses),
        "passed": passed,
        "errors": errors,
        "not_executed": not_executed,
        "run_ids": list(evidence.run_ids),
        "selected_sha256": evidence.selected_sha256,
    }
    if len(statuses) != required:
        rows.append(row_blocked(row_prefix, title, R_EVIDENCE_MISSING, cause="denominator_mismatch",
                                detail={**detail, "required": required}))
    elif not_executed or errors:
        rows.append(row_blocked(row_prefix, title, R_NOT_EXECUTED, cause="case_not_executed",
                                detail=detail))
    elif passed < required:
        rows.append(row_blocked(row_prefix, title, R_QUALITY_BELOW_THRESHOLD,
                                cause=f"{passed} < {required}", detail=detail))
    else:
        rows.append(row_ok(row_prefix, title, detail=detail))
    rows.append(_hard_gate_row(
        f"{row_prefix}.hard_gates", f"{title} · 八项硬门禁",
        evidence.gate_proof, suite=evidence.suite, config=gate_config,
    ))
    return tuple(rows)


def assess_applicability(
    runs: Mapping[str, RunBinding],
    scopes: Mapping[str, Sequence[CaseSpec]],
    statuses: Mapping[str, str],
    *,
    gate_config: P2GateConfig,
    gate_config_path: Path,
) -> tuple[ReleaseRow, ...]:
    """历史 run 的适用性：范围 = 该 run 在冻结选题里承担的全部题（跨 N/C 合并一次）。

    证明按 (run, 冻结范围) 一次性生成：先定范围再复算，不能在两个套件里各挑一份
    对自己有利的状态向量。
    """
    rows: list[ReleaseRow] = []
    for run_id, binding in runs.items():
        scope = tuple(scopes.get(run_id) or ())
        row_id = f"applicability.{run_id}"
        if not scope:
            continue
        if binding.manifest.get("gate_config_hash") == gate_config.config_hash:
            rows.append(row_ok(row_id, f"同版本 run（无需适用性证明）· {run_id}", detail={
                "gate_config_hash": gate_config.config_hash,
                "pipeline_version": binding.manifest.get("pipeline_version"),
            }))
            continue
        rebuilt = build_applicability_proof(binding, scope, statuses,
                                            gate_config=gate_config,
                                            gate_config_path=gate_config_path)
        if binding.applicability is None:
            rows.append(row_blocked(row_id, f"适用性证明缺失 · {run_id}", R_APPLICABILITY_INVALID,
                                    cause="proof_missing",
                                    detail={"gate_config_hash": binding.manifest.get("gate_config_hash")}))
            continue
        try:
            _validate_applicability(binding.applicability.payload, rebuilt, binding=binding)
        except _ApplicabilityError as exc:
            rows.append(row_blocked(row_id, f"适用性证明不可核 · {run_id}", R_APPLICABILITY_INVALID,
                                    cause=exc.cause, detail=exc.detail))
            continue
        rows.append(row_ok(row_id, f"旧版本适用性 · {run_id}", detail={
            "original_gate_config_hash": rebuilt["original"]["gate_config_hash"],
            "target_gate_config_hash": rebuilt["target"]["gate_config_hash"],
            "scorer_source_sha256": rebuilt["derivation"]["scorer_source_sha256"],
            "cases_sha256": rebuilt["case_scope"]["cases_sha256"],
            "statuses_sha256": rebuilt["derivation"]["statuses_sha256"],
        }, evidence=(f"applicability:{binding.applicability.sha256[:16]}",)))
    return tuple(rows)


# --------------------------------------------------------------------------- #
# U：1 真实 smoke + 9 本地控制（R/L 分列，不混用）
# --------------------------------------------------------------------------- #


def assess_u(
    inputs: ReleaseInputs,
    *,
    evidence: SuiteEvidence,
    project_root: Path | None = None,
) -> tuple[ReleaseRow, ...]:
    """U 10/10：真实 smoke（R）+ 可选本地控制（L）。归属逐题判定，不许混用/重复。"""
    rows: list[ReleaseRow] = []
    expected = list(P2_UPDATE_DELETE_IDS)
    real_basis = {case_id: "R" for case_id in evidence.statuses}
    local_basis: dict[str, str] = {}
    controls_label = None
    if inputs.u_controls is not None:
        controls = inputs.u_controls.payload
        control_cases = controls.get("cases") if isinstance(controls.get("cases"), Mapping) else {}
        controls_label = controls.get("source")
        if controls.get("basis") != "L":
            rows.append(row_blocked("u.source", "U 本地控制基准", R_IDENTITY_MISMATCH,
                                    cause="local_controls_basis_not_L",
                                    detail={"basis": controls.get("basis")}))
        for case_id in control_cases:
            if str(case_id) in expected:
                local_basis[str(case_id)] = str((control_cases.get(case_id) or {}).get("status"))
    overlap = sorted(set(real_basis) & set(local_basis))
    missing = [case_id for case_id in expected if case_id not in real_basis and case_id not in local_basis]
    unknown = sorted((set(real_basis) | set(local_basis)) - set(expected))
    detail: dict[str, Any] = {
        "real": {"run_id": evidence.run_ids[0] if evidence.run_ids else None,
                 "case_ids": sorted(real_basis),
                 "statuses": {case_id: evidence.statuses[case_id] for case_id in real_basis}},
        "local": {"case_ids": sorted(local_basis), "statuses": local_basis,
                  "source": controls_label},
        "basis": {case_id: ("R" if case_id in real_basis else "L") for case_id in expected
                  if case_id in real_basis or case_id in local_basis},
        "missing": missing,
        "unknown": unknown,
        "overlap": overlap,
    }
    if overlap:
        # 本地控制文件通常含全部 U 行（junit 口径）；R 优先、L 仅对照，不重复计入。
        rows.append(row_observed("u.overlap", "U 逐题归属（R 优先，L 仅对照）", detail={
            **detail,
            "rule": "同一题同时出现在真实 smoke 与本地控制时，bases 取 R（真实 smoke），L 记录但不计入",
        }))
    if unknown:
        rows.append(row_blocked("u.source", "U 证据 compose", R_IDENTITY_MISMATCH,
                                cause="unknown_u_case", detail=detail))
    if missing:
        rows.append(row_blocked("u.coverage", "U 逐题覆盖 U01–U10", R_EVIDENCE_MISSING,
                                cause="u_case_missing", detail=detail))
    else:
        rows.append(row_ok("u.coverage", "U 逐题覆盖 U01–U10（R/L 分列）", detail=detail))
    merged: dict[str, str] = {}
    for case_id in expected:
        if case_id in real_basis:
            merged[case_id] = evidence.statuses[case_id]
        elif case_id in local_basis:
            merged[case_id] = local_basis[case_id]
    bad = sorted(case_id for case_id, value in merged.items() if value != CASE_STATUS_PASS)
    if bad:
        reason = R_NOT_EXECUTED if any(merged[case_id] in
                                       {CASE_STATUS_NOT_EXECUTED, CASE_STATUS_ERROR,
                                        "skipped", "None"} for case_id in bad) else R_QUALITY_BELOW_THRESHOLD
        rows.append(row_blocked("u.local", "U 逐题通过", reason, cause="u_case_not_pass",
                                detail={**detail, "bad": bad}))
    else:
        rows.append(row_ok("u.local", "U 逐题通过（R/L 各自来源）", detail=detail))
    passed = sum(1 for value in merged.values() if value == CASE_STATUS_PASS)
    if len(merged) == len(expected) and passed == len(expected):
        rows.append(row_ok("u", "U 10/10（1 真实 smoke 起，其余按 R/L 分列）",
                           detail={**detail, "passed": passed},
                           evidence=(f"u-controls:{inputs.u_controls.sha256[:16]}" if inputs.u_controls else
                                     f"u-real:{evidence.run_ids[0]}",)))
    else:
        rows.append(row_blocked("u", "U 10/10（1 真实 smoke 起，其余按 R/L 分列）",
                                R_QUALITY_BELOW_THRESHOLD, cause="u_not_10_of_10",
                                detail={**detail, "passed": passed}))
    rows.append(_hard_gate_row("u.hard_gates", "U · 八项硬门禁", evidence.gate_proof,
                               suite="update_delete", config=inputs.gate_config))
    # U01：引用落在同轮 evidence、retrieved 为空 —— 门禁判 fail，交主人裁量（不得静默 pass）。
    gaps = citation_grounding_gaps(inputs, evidence)
    gate_status = evidence.gate_proof.get("gate_status") or {}
    if gaps and gate_status.get("citation_required") == "fail":
        from .p2_release_model import row_pending

        pending = row_pending(
            "u.citation", "U01 引用证据字段缺失（PENDING-MASTER-DECISION）",
            "PENDING-MASTER-DECISION", reason=R_CITATION_GROUNDING_MISSING,
            detail={
                "cases": gaps,
                "mechanical": "citation_required=fail（同轮 product.retrieved=[] 而 evidence 有单元）",
                "options": [
                    "改判据：正式裁决是否接受同轮 evidence 作为引用依据（需主人书面授权，不得由执行方自行放宽）",
                    "真实重跑：为 U01 补 product.retrieved 后按新 GO 重跑（需真实请求与配额）",
                    "接受阻断：U 保持 9/10，发布门禁记为阻断",
                ],
            },
        )
        rows = [row for row in rows if row.row_id != "u.hard_gates"] + [pending]
    elif gaps:
        rows.append(row_observed("u.citation", "U01 引用接地（D-004：evidence 字段）", detail={
            "cases": gaps,
            "mechanical_before": "citation_required=fail（retrieved=[]）",
            "after_d004": "citation_required=pass（候选接地集合 = evidence ∪ retrieved）",
            "decision": "D-004 已由主人授权；本行不再阻断",
        }))
    # D-011（主人授权）：min-sample 覆盖按 suite 计划题数计；run 级子集只披露。
    # 固定披露行（observed，不得省略）。
    coverage = min_sample_coverage(
        standards=inputs.gate_config.standards, gate_config=inputs.gate_config,
        suite="update_delete", run_level_evaluated=int(evidence.scored_count),
    )
    rows.append(row_observed(
        "hard_gate_min_sample.run_level_subset",
        "硬门禁最小样本：suite 计划题数口径（D-011）",
        detail={
            **coverage,
            "scored_count": int(evidence.scored_count),
            "disclosed_limit": "U 的八项硬门禁在 1 条 run 级样本上评估，其余 9 条为本地控制",
            "authority": "主人 D-011：按 suite 计划题数计覆盖，不改配置数值、不放宽判据",
        },
    ))
    hard_row = next((row for row in rows if row.row_id == "u.hard_gates"), None)
    if hard_row is not None and R_SAMPLE_BELOW_MIN in hard_row.reasons and not coverage["covered"]:
        from .p2_release_model import row_pending as _row_pending

        detail = dict(hard_row.detail.get("evidence") or {})
        rows = [row for row in rows if row.row_id != "u.hard_gates"]
        rows.append(_row_pending(
            "u.hard_gates", "U · 八项硬门禁（PENDING-MASTER-DECISION）",
            "PENDING-MASTER-DECISION", reason=R_SAMPLE_BELOW_MIN,
            detail={
                **detail,
                "pending_kind": "u_sample_scope",
                "approved_composition": "1 真实 smoke + 9 本地控制（u-controls.json）",
                "why": "本地控制不是 run 行，八项硬门禁只能在 run 级逐题上评估；"
                       "批准配置的 update_delete 最小样本是 10。",
                "options": [
                    "书面裁定：接受 1R+9L 作为 U 的八门口径（需主人授权，执行方不得自行放宽）",
                    "补证：为其余 9 题补真实 run 级证据（需真实请求、配额与新 GO）",
                    "接受阻断：U 八门记 1/10，发布门禁保持阻断",
                ],
            },
        ))
    return tuple(rows)


def citation_grounding_gaps(inputs: ReleaseInputs, evidence: SuiteEvidence) -> list[str]:
    """找出"同轮 retrieved 为空但 evidence 有单元"的题（机械口径下的引用缺失）。"""
    binding = inputs.u_real
    if binding is None:
        return []
    gaps: list[str] = []
    wanted = set(evidence.statuses)
    for line in binding.artifact_bytes("cases.jsonl").decode("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("case_id")) not in wanted:
            continue
        for turn in row.get("turns") or ():
            product = turn.get("product") if isinstance(turn.get("product"), Mapping) else {}
            retrieved = product.get("retrieved")
            proof = product.get("evidence")
            if not retrieved and isinstance(proof, Sequence) and not isinstance(proof, (str, bytes)) and proof:
                gaps.append(str(row.get("case_id")))
                break
    return sorted(set(gaps))


# --------------------------------------------------------------------------- #
# 八项硬门禁汇总（跨来源，各自适用性保留）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HardGateSource:
    source: str
    proof: Mapping[str, Any]


def aggregate_hard_gates(sources: Sequence[HardGateSource], *, config: P2GateConfig) -> ReleaseRow:
    """八项硬门禁汇总：判据必须与各来源行一致（含 unknowns）。

    * 任一来源 `gate_id` fail → 硬失败；
    * 任一来源 `gate_id` 为 missing/not_evaluated/unknown → 必需未知；
    * **任一来源存在非 `min_sample_not_met` 的 unknown（例如 gold/dataset 类）→ 必需未知**
      （T4-R3：汇总行不得忽略 unknowns，否则会与 `u.hard_gates` 矛盾）；
    * 某门禁在所有来源都 not_applicable 时单列明细，不视为缺证。
    """
    table: dict[str, dict[str, str]] = {gate: {} for gate in HARD_GATE_IDS}
    failures: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    disclosed: list[dict[str, Any]] = []
    for item in sources:
        for gate_id in HARD_GATE_IDS:
            state = str((item.proof.get("gate_status") or {}).get(gate_id) or "missing")
            table[gate_id][item.source] = state
            if state == "fail":
                failures.append({"source": item.source, "gate_id": gate_id})
            elif state in {"missing", "not_evaluated", "unknown"}:
                unresolved.append({"source": item.source, "gate_id": gate_id, "state": state})
        for unknown in item.proof.get("unknowns") or ():
            if not isinstance(unknown, Mapping):
                continue
            check_id = str(unknown.get("check_id") or "")
            record = {"source": item.source, "gate_id": unknown.get("gate_id"),
                      "case_id": unknown.get("case_id"), "check_id": check_id}
            if check_id == "min_sample_not_met":
                # D-011：覆盖成立时该项只披露、不阻断（与各来源行一致）。
                disclosed.append(record)
                continue
            unresolved.append(record)
    uncovered = sorted(
        gate for gate, states in table.items()
        if states and all(state == GATE_STATUS_NOT_APPLICABLE for state in states.values())
    )
    detail: dict[str, Any] = {
        "per_gate": table,
        "min_sample": dict(config.config.min_sample),
        # 全来源都不适用的门禁：数据集没有该类用例（批准配置允许），单独列出供 T900 复核。
        "not_applicable_gates": uncovered,
        "disclosed_unknowns": disclosed,
        "sources": [item.source for item in sources],
    }
    if failures:
        return row_blocked("hard_gates", "八项硬门禁汇总", R_HARD_FAILURE,
                           cause="hard_gate_failed", detail={**detail, "failures": failures})
    if unresolved:
        return row_blocked("hard_gates", "八项硬门禁汇总", R_REQUIRED_UNKNOWN,
                           cause="hard_gate_unknown", detail={**detail, "unresolved": unresolved})
    return row_ok("hard_gates", "八项硬门禁汇总", detail=detail)


__all__ = [
    "B0Evidence",
    "HardGateSource",
    "SCORER_SOURCES",
    "SuiteEvidence",
    "aggregate_hard_gates",
    "assess_applicability",
    "assess_b0",
    "assess_suite",
    "assess_u",
    "build_applicability_proof",
    "citation_grounding_gaps",
    "classify_b0_error",
    "collect_suite",
    "scorer_source_sha256",
    "substantive_projection",
]
