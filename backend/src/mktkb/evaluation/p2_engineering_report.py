"""Read-only assembly of already scored P2 observations for T209."""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

from .p2_candidate_report import CandidateReportError, SplitReport
from .p2_contracts import payload_sha256
from .p2_runner import EXECUTION_DRY_RUN, EXECUTION_LIVE, EXECUTION_MOCK_GATE
from .p2_score_run import BASIS_LOCAL, BASIS_REAL, U_LOCAL_IDS, U_REAL_IDS
from .p2_scoring import (
    EXECUTION_MODE_LIVE,
    EXECUTION_MODE_LOCAL_MOCK,
    P2_B0_EXACT_TOTAL,
    P2_B0_OCR_TOTAL,
    P2_B0_TOTAL,
    P2_BOUNDARY_TOTAL,
    P2_NEGATIVE_TOTAL,
    P2PublicScorecard,
)


_U_MEMBERS = {BASIS_REAL: U_REAL_IDS, BASIS_LOCAL: U_LOCAL_IDS}
_U_STATUS = {"pass": "passed", "fail": "failed", "error": "errors", "not_executed": "not_executed"}
_EXECUTION = {
    EXECUTION_DRY_RUN: EXECUTION_MODE_LOCAL_MOCK,
    EXECUTION_MOCK_GATE: EXECUTION_MODE_LOCAL_MOCK,
    EXECUTION_LIVE: EXECUTION_MODE_LIVE,
}
_RUNTIME_SCOPES = ("answer_turns", "all_attempts")
_TOKEN_FIELDS = ("prompt_tokens", "completion_tokens")
_MEASUREMENTS = (
    "p95_latency_ms", *_TOKEN_FIELDS, "conservative_held_cny", "provider_usage_estimate_cny",
)


def _identity(values: Mapping[str, Any], name: str, digest_key: str = "config_hash") -> dict[str, str]:
    if not isinstance(values, Mapping):
        raise CandidateReportError(f"{name} 需要身份对象")
    run_id, digest = values.get("run_id"), values.get(digest_key)
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", run_id):
        raise CandidateReportError(f"{name}.run_id 非法")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CandidateReportError(f"{name}.{digest_key} 需要 64 位 SHA-256")
    return {"run_id": run_id, digest_key: digest}


def _count(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise CandidateReportError(f"{name} 需要非负整数")
    return value


def _number(value: Any, name: str) -> int | float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not 0 <= value < math.inf:
        raise CandidateReportError(f"{name} 需要非负有限数值")
    return value


def _records(value: Any, name: str) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, (tuple, list)) or not all(isinstance(row, Mapping) for row in value):
        raise CandidateReportError(f"{name} 需要对象数组")
    return value


def _u_projection(matrix: Mapping[str, Any] | None) -> dict[str, Any]:
    groups = {
        basis: {"planned": len(ids), "passed": 0, "failed": 0, "errors": 0,
                "not_executed": 0, "missing": len(ids), "source": None}
        for basis, ids in _U_MEMBERS.items()
    }
    if matrix is None:
        return groups
    if not isinstance(matrix, Mapping):
        raise CandidateReportError("U 证据需要公开矩阵")
    expected = {case_id: basis for basis, ids in _U_MEMBERS.items() for case_id in ids}
    seen: set[str] = set()
    for row in _records(matrix.get("u_table"), "U 证据 u_table"):
        case_id, basis, status = row.get("case_id"), row.get("basis"), row.get("status")
        if not isinstance(case_id, str) or case_id not in expected or basis != expected[case_id] or case_id in seen:
            raise CandidateReportError("U 证据题号、L/R 口径或唯一性非法")
        seen.add(case_id)
        if status is None:
            continue
        if not isinstance(status, str) or status not in _U_STATUS:
            raise CandidateReportError(f"U 证据 {case_id} 状态非法")
        if basis == BASIS_REAL:
            runs = [item for item in _records(matrix.get("runs"), "U 证据 runs")
                    if item.get("run_id") == row.get("run_id")]
            cases = [item for item in _records(matrix.get("cases"), "U 证据 cases")
                     if item.get("case_id") == case_id]
            if (len(runs) != 1 or len(cases) != 1 or runs[0].get("execution_mode") != EXECUTION_MODE_LIVE
                    or cases[0].get("execution_mode") != EXECUTION_MODE_LIVE or cases[0].get("status") != status
                    or cases[0].get("duplicated_in")
                    or _identity(runs[0], case_id) != _identity(cases[0], case_id)):
                raise CandidateReportError(f"U 证据 {case_id} 缺同一真实运行的身份与评分")
            if _count(runs[0].get("real_calls"), f"U 证据 {case_id}.real_calls") == 0:
                raise CandidateReportError(f"U 证据 {case_id} 没有真实运行请求")
            groups[basis]["source"] = _identity(runs[0], case_id)
        else:
            source = row.get("source")
            if not isinstance(source, str) or source in {"", "None"} or row.get("run_id") is not None:
                raise CandidateReportError(f"U 证据 {case_id} 缺本地控制来源")
        groups[basis][_U_STATUS[status]] += 1
        groups[basis]["missing"] -= 1
    if groups[BASIS_LOCAL]["missing"] != len(U_LOCAL_IDS):
        groups[BASIS_LOCAL]["source"] = {"matrix_sha256": payload_sha256(matrix)}
    return groups


def _ragas_projection(ragas: Mapping[str, Any] | None) -> dict[str, Any]:
    if ragas is None:
        return {"status": "unknown", "auxiliary_only": True}
    if not isinstance(ragas, Mapping) or set(ragas) != {"run_id", "plan_sha256", "status", "counts", "metrics"}:
        raise CandidateReportError("ragas 仅接受安全聚合字段")
    status, counts, metrics = ragas["status"], ragas["counts"], ragas["metrics"]
    if (status not in ("scored", "unknown", "blocked") or not isinstance(counts, Mapping)
            or set(counts) != {"scored", "unknown", "expected_refusal"}):
        raise CandidateReportError("ragas 聚合状态或计数非法")
    counts = {key: _count(counts[key], f"ragas.counts.{key}") for key in counts}
    if counts["expected_refusal"] > counts["unknown"] or (status == "scored" and counts["scored"] == 0):
        raise CandidateReportError("ragas 拒答、未知、评分计数不一致")
    if (not isinstance(metrics, Mapping) or set(metrics) - {"faithfulness", "factual_correctness"}
            or (metrics and not counts["scored"])):
        raise CandidateReportError("ragas 指标字段或分母非法")
    scores = {
        key: _number(metrics.get(key), f"ragas.metrics.{key}")
        for key in ("faithfulness", "factual_correctness")
    }
    if any(value is not None and value > 1 for value in scores.values()):
        raise CandidateReportError("ragas 分数超出 0–1")
    return {**_identity(ragas, "ragas", "plan_sha256"), "status": status,
            "counts": counts, "metrics": scores, "auxiliary_only": True}


def _runtime_projection(rows: Sequence[Mapping[str, Any]], public_id: Mapping[str, str]) -> dict:
    output = {
        scope: {"coverage": "unknown", "sample": None, "eligible": None,
                **dict.fromkeys(_MEASUREMENTS)}
        for scope in _RUNTIME_SCOPES
    }
    seen: set[str] = set()
    for row in _records(rows, "runtime"):
        scope = row.get("scope")
        if set(row) - {"run_id", "config_hash", "scope", "sample", "eligible", *_MEASUREMENTS}:
            raise CandidateReportError("runtime 包含未知字段")
        if scope not in _RUNTIME_SCOPES or scope in seen or _identity(row, "runtime") != public_id:
            raise CandidateReportError("runtime 口径重复、非法或跨 run/config")
        seen.add(scope)
        sample, eligible = _count(row.get("sample"), "runtime.sample"), _count(row.get("eligible"), "runtime.eligible")
        values = {key: _number(row.get(key), f"runtime.{key}") for key in _MEASUREMENTS}
        for key in _TOKEN_FIELDS:
            if values[key] is not None:
                _count(values[key], f"runtime.{key}")
        if sample > eligible or (not sample and any(value is not None for value in values.values())):
            raise CandidateReportError("runtime.sample 与分母或观测值不一致")
        held, estimated = (values[key] for key in ("conservative_held_cny", "provider_usage_estimate_cny"))
        if estimated is not None and held is not None and estimated > held:
            raise CandidateReportError("runtime 供应商用量估算超过 conservative 保守占用")
        output[scope] = {"sample": sample, "eligible": eligible,
                         "coverage": ("unknown" if not sample else "complete" if sample == eligible else "partial"),
                         **values}
    return output


def build_engineering_report(
    *, public: P2PublicScorecard, public_manifest: Mapping[str, Any],
    u_matrix: Mapping[str, Any] | None = None, holdout: SplitReport | None = None,
    ragas: Mapping[str, Any] | None = None, measurements: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Project public matrix, E2 holdout, and bound measurements into an observation sidecar."""
    identity = _identity(public_manifest, "public manifest")
    execution = public_manifest.get("execution")
    if (not isinstance(public, P2PublicScorecard) or not isinstance(execution, str)
            or (public.run_id, public.config_hash, public.execution_mode) != (
                identity["run_id"], identity["config_hash"], _EXECUTION.get(execution))):
        raise CandidateReportError("public scorecard 与 run/config/执行方式不一致")
    public_groups = {}
    for suite, total in (("b0", P2_B0_TOTAL), ("negative", P2_NEGATIVE_TOTAL), ("boundary", P2_BOUNDARY_TOTAL)):
        tally = public.suites.get(suite)
        if tally is None or tally.suite != suite or tally.planned != total:
            raise CandidateReportError(f"public scorecard 缺正确分母的 {suite}")
        counts = {name: _count(getattr(tally, name), f"public.{suite}.{name}") for name in (
            "planned", "executed", "passed", "failed", "errors", "not_executed",
        )}
        if (counts["executed"] != counts["passed"] + counts["failed"]
                or total != counts["executed"] + counts["errors"] + counts["not_executed"]):
            raise CandidateReportError(f"public scorecard {suite} 计数不守恒")
        public_groups[suite] = counts
    b0 = public.suites["b0"]
    exact = {name: _count(getattr(b0, f"exact_{name}"), f"public.exact.{name}")
             for name in ("planned", "passed")}
    ocr = {name: _count(getattr(b0, f"ocr_{name}"), f"public.ocr.{name}")
           for name in ("planned", "executed", "passed")}
    non_exact = b0.planned - P2_B0_EXACT_TOTAL
    non_ocr = b0.planned - P2_B0_OCR_TOTAL
    # The frozen exact and OCR subsets are disjoint.
    subset_passed = exact["passed"] + ocr["passed"]
    other_planned = non_exact - P2_B0_OCR_TOTAL
    if (
        exact["planned"] != P2_B0_EXACT_TOTAL
        or not max(0, b0.passed - non_exact) <= exact["passed"] <= min(exact["planned"], b0.passed)
        or ocr["planned"] != P2_B0_OCR_TOTAL
        or not max(0, b0.passed - non_ocr) <= ocr["passed"] <= min(ocr["executed"], b0.passed)
        or not max(0, b0.executed - non_ocr) <= ocr["executed"] <= min(ocr["planned"], b0.executed)
        or ocr["executed"] - ocr["passed"] > b0.failed
        or not subset_passed <= b0.passed <= subset_passed + other_planned
    ):
        raise CandidateReportError("public scorecard 精确或 OCR 子分母不一致")
    public_groups.update(exact=exact, ocr=ocr)
    h2: dict[str, Any] = {"status": "unknown"}
    if holdout is not None:
        if not isinstance(holdout, SplitReport):
            raise CandidateReportError("H2 输入必须是 E2 安全聚合报告")
        # Use the existing E2 parser to preserve its round, privacy, and evidence checks.
        current = SplitReport.from_dict(holdout.to_dict())
        h2 = {key: getattr(current.quality, key) for key in (
            "round_id", "status", "total", "passed", "failed", "errors", "safety_violations", "verified",
        )}
        h2.update(code_version=current.reference.code_version, config_sha256=current.reference.config_sha256,
                  binding_sha256=current.reference.binding_sha256, unknown_total=current.evidence.unknown_total,
                  axis_violation_total=current.evidence.violation_total)
    return {
        "schema_version": "p2-engineering-report/v0.1", "publishable": False,
        "public": {**identity, "execution_mode": public.execution_mode,
                   "scorecard_real_calls": _count(public.real_calls, "public.scorecard_real_calls"),
                   **public_groups},
        "u": _u_projection(u_matrix), "holdout": h2, "ragas": _ragas_projection(ragas),
        "runtime": _runtime_projection(measurements, identity),
    }
