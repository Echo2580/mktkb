"""P2-T205：8 项既有硬门禁逐类正反例 + gate_v0_3 fail-closed 判定（离线）。

覆盖任务书 T205 第二/五条：

- security_leak / cross_entity / stale_bypass / conflict_not_rejected /
  exact_value_contract / pagination_contract / citation_required / trace_integrity
  每项都有正例与反例；缺 trace / 缺来源 / 缺身份 → fail closed；
- 「没有该类 case」= not_applicable，「缺必要数据」= unknown，两者不混同；
- 阈值未批准 / 样本不足 / 跨 scope / 同 gate_version 改配置 / 旧 gate / 不完整 run
  都不能放行；
- 执行退出码与质量门禁码分开记录（gate_v0_3 初始 unapproved）。

全部用合成 RunResult + 真实 TraceRepository（tmp_path），零真实模型 / OCR / 网络。
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from mktkb.evaluation import gate as gate_module
from mktkb.evaluation.dataset import CaseSpec, write_cases
from mktkb.evaluation.gate import (
    EXIT_HARD_FAILURE,
    EXIT_PASS,
    EXIT_QUALITY_REGRESSION,
    EXIT_UNKNOWN,
    GATE_STATUS_FAIL,
    GATE_STATUS_NOT_APPLICABLE,
    GATE_STATUS_PASS,
    GATE_STATUS_UNKNOWN,
    GATE_VERSION_V0_3,
    HARD_GATE_IDS,
    GateConfig,
    GateProposal,
    evaluate_gate,
    write_gate_proposal,
)
from mktkb.evaluation.p2_scoring import (
    CASE_STATUS_FAIL,
    CASE_STATUS_PASS,
    EXECUTION_MODE_LIVE,
    P2_B0_EXACT_IDS,
    P2_B0_IDS,
    P2_B0_OCR_IDS,
    P2_BOUNDARY_IDS,
    P2_HOLDOUT_STRATA,
    P2_NEGATIVE_IDS,
    P2_UPDATE_DELETE_IDS,
    P2CaseScore,
    P2GateConfig,
    P2HoldoutCaseScore,
    P2ScoringError,
    SEVERITY_HARD,
    aggregate_holdout,
    build_gate_rows,
    build_gate_run,
    evaluate_p2_gate,
    evaluate_p2_hard_gates,
    load_p2_gate_config,
    normalize_product_outcome,
    score_public_case,
    score_public_suites,
)
from mktkb.observability.contracts import SpanRecord, TraceRecord
from mktkb.observability.store import TraceRepository

ROOT = Path(__file__).resolve().parents[3]
UNIT_KEY = "sheet:物品位置:row:8"
UNIT_ID = "11111111-1111-4111-8111-111111111111"
DOC_NAME = "D01_物品位置表.xlsx"
DOCUMENT_CODES = {DOC_NAME: "D01"}
SOURCE_INDEX = {UNIT_ID: {"doc_code": "D01", "unit_key": UNIT_KEY, "locator": {}}}
LEGACY_SPANS = ("intent_parse", "retrieve", "model_answer", "answer_validate", "commit")

SHIPPED = load_p2_gate_config()
LEGACY = load_p2_gate_config(ROOT / "docs" / "evaluation" / "gate_v0_2.json")


def make_case(
    case_id: str = "Q01",
    *,
    suite: str = "b0",
    stratum: str = "exact",
    expected_values: tuple[str, ...] = ("B区1号货架第二层",),
    expected_kind: str = "answer",
    should_refuse: bool = False,
    forbidden_values: tuple[str, ...] = (),
    forbidden_sources: tuple[dict, ...] = (),
    expected_pagination: dict | None = None,
    requires_ocr: bool = False,
    question: str = "城东店的宣传海报在哪里？",
) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        suite=suite,
        split="dev",
        stratum=stratum,
        business_date="2026-10-28",
        question=question,
        expected_kind=expected_kind,
        expected_values=expected_values,
        expected_sources=({"doc_code": "D01", "unit_key": UNIT_KEY},),
        labeler="lead",
        label_version="dev-1",
        should_refuse=should_refuse,
        forbidden_values=forbidden_values,
        forbidden_sources=forbidden_sources,
        expected_pagination=expected_pagination,
        requires_ocr=requires_ocr,
    )


def make_manifest(
    *,
    case_count: int = 1,
    dataset_path: str = "dataset.jsonl",
    gate_config_hash: str = "f" * 64,
    gate_version: str = GATE_VERSION_V0_3,
    **overrides,
) -> dict:
    payload = {
        "run_id": "run-p2",
        "mode": "end_to_end",
        "scope": "end_to_end",
        "suite": "b0",
        "dataset_version": "b0:dev-1:deadbeef",
        "dataset_sha256": "a" * 64,
        "corpus_manifest_sha256": "b" * 64,
        "business_date": "2026-10-28",
        "index_revision": 6,
        "pipeline_version": "pipeline1234",
        "gate_version": gate_version,
        "label_version": "dev-1",
        "created_at": "2026-11-10T00:00:00.000+00:00",
        "case_count": case_count,
        "config_hash": "c" * 12,
        "dataset_path": dataset_path,
        "gate_config_hash": gate_config_hash,
    }
    payload.update(overrides)
    return payload


def product(
    *,
    text: str = "B区1号货架第二层",
    kind: str = "answer",
    trace_id: str = "trace-1",
    sources: tuple[dict, ...] | None = None,
    pagination: dict | None = None,
    path: str = "legacy",
) -> dict:
    if sources is None:
        sources = (
            {
                "source_id": UNIT_ID,
                "document_name": DOC_NAME,
                "version_number": 1,
                "status": "active",
                "locator": {"sheet": "物品位置", "row": 8},
            },
        )
    return {
        "kind": kind,
        "text": text,
        "trace_id": trace_id,
        "trace_path": path,
        "sources": [dict(item) for item in sources],
        "http_status": 200,
        "pagination": pagination or {},
    }


def write_trace(
    repo: TraceRepository,
    manifest,
    case_id: str,
    *,
    spans: tuple[str, ...] = LEGACY_SPANS,
    path: str = "legacy",
    outcome: str = "answer",
    trace_id: str | None = None,
    annotate_identity: bool = True,
    **overrides,
) -> str:
    resolved = trace_id or f"trace-{case_id}"
    fields = {
        "trace_id": resolved,
        "http_request_id": f"{manifest.run_id}:{case_id}",
        "mode": manifest.mode,
        "scope": manifest.scope,
        "path": path,
        "case_id": case_id,
        "outcome_kind": outcome,
        "status": "ok",
        "latency_ms": 1,
    }
    if annotate_identity:
        fields.update(
            dataset_version=manifest.dataset_version,
            run_id=manifest.run_id,
            index_revision=str(manifest.index_revision),
            manifest_sha256=manifest.corpus_manifest_sha256,
            pipeline_version=manifest.pipeline_version,
            config_hash=manifest.config_hash,
        )
    fields.update(overrides)
    record = TraceRecord(**fields)
    repo.write(
        record,
        [
            SpanRecord(span_id=f"{resolved}-{name}", trace_id=resolved, name=name, status="ok")
            for name in dict.fromkeys(spans)
        ],
    )
    return resolved


def build_run(
    tmp_path: Path,
    cases: list[CaseSpec],
    products: list[dict | None],
    *,
    evidence: dict[str, list[dict]] | None = None,
    default_evidence: bool = True,
    manifest_overrides: dict | None = None,
    trace_specs: dict[str, dict | None] | None = None,
    trace_store: bool = True,
    raw_rows: bool = False,
):
    """写出 dataset/rows/traces，返回 (RunResult, scored)。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = tmp_path / "dataset.jsonl"
    write_cases(dataset_path, cases)
    manifest_map = make_manifest(
        case_count=len(cases), dataset_path=str(dataset_path), **(manifest_overrides or {})
    )
    if default_evidence:
        merged = {
            case.case_id: [{"doc_code": "D01", "unit_ids": [UNIT_ID]}] for case in cases
        }
        merged.update(evidence or {})
        evidence = merged
    scored = []
    raw_by_id: dict[str, dict] = {}
    for case, item in zip(cases, products):
        turns = [] if item is None else [
            {"turn": 1, "status": "ok", "error_code": None, "product": item}
        ]
        case_row = {
            "case_id": case.case_id,
            "suite": case.suite,
            "stratum": case.stratum,
            "conversation_id": f"conv-{case.case_id}",
            "status": "ok",
            "error_code": None,
            "planned_turns": 1,
            "turns_executed": len(turns),
            "turns": turns,
        }
        raw_by_id[case.case_id] = case_row
        scored.append(
            score_public_case(
                case,
                case_row,
                document_codes=DOCUMENT_CODES,
                source_index=SOURCE_INDEX,
                allowed_doc_codes={"D01"},
                evidence=(evidence or {}).get(case.case_id, ()),
            )
        )
    rows = build_gate_rows(cases, scored, case_rows=raw_by_id if raw_rows else None)
    run = build_gate_run(
        run_dir=run_dir,
        manifest=manifest_map,
        cases=cases,
        rows=rows,
        summary={"status": "succeeded"},
    )
    if trace_store:
        repo = TraceRepository(run_dir / "traces.sqlite3")
        try:
            if trace_specs is None:
                trace_specs = {
                    case.case_id: {"trace_id": (item or {}).get("trace_id")}
                    for case, item in zip(cases, products)
                }
            for case_id, spec in trace_specs.items():
                if spec is None:
                    continue
                write_trace(repo, run.manifest, case_id, **spec)
        finally:
            repo.close()
    return run, scored, manifest_map


def config_for(
    *,
    status: str = "approved",
    min_sample: int = 1,
    gate_version: str = GATE_VERSION_V0_3,
    schema_version: str = "mktkb.gate.config.v0.3",
    config_hash: str = "f" * 64,
) -> P2GateConfig:
    gate_config = GateConfig(
        gate_version=gate_version,
        schema_version=schema_version,
        status=status,
        hard_gates=HARD_GATE_IDS,
        min_sample={"b0": min_sample},
        metrics=SHIPPED.config.metrics,
        sensitive_patterns=(),
        suites=("b0", "regression"),
        source_path=str(gate_module.P2_GATE_CONFIG_PATH),
        config_hash=config_hash,
    )
    return P2GateConfig(config=gate_config, standards=SHIPPED.standards, raw={})


def public_card(
    *,
    run_id: str | None = None,
    execution_mode: str | None = None,
    real_calls: int = 0,
    config_hash: str | None = None,
) -> object:
    scores = []
    for case_id in P2_B0_IDS:
        scores.append(
            P2CaseScore(
                case_id=case_id,
                suite="b0",
                stratum="ocr" if case_id in P2_B0_OCR_IDS else "exact",
                status=CASE_STATUS_PASS,
                requires_ocr=case_id in P2_B0_OCR_IDS,
                planned_turns=1,
                executed_turns=1,
            )
        )
    for case_id in P2_NEGATIVE_IDS + P2_BOUNDARY_IDS + P2_UPDATE_DELETE_IDS:
        scores.append(
            P2CaseScore(
                case_id=case_id,
                suite="other",
                stratum="other",
                status=CASE_STATUS_PASS,
                requires_ocr=False,
                planned_turns=1,
                executed_turns=1,
            )
        )
    if execution_mode is not None:
        scores = [
            dataclasses.replace(item, execution_mode=execution_mode, real_calls=real_calls)
            for item in scores
        ]
    return score_public_suites(scores, run_id=run_id, config_hash=config_hash)


def holdout_card(
    *,
    approved: bool = True,
    run_id: str | None = None,
    execution_mode: str = "local_mock",
    real_calls: int = 0,
    config_hash: str | None = None,
):
    items = []
    for index, (stratum, count) in enumerate(P2_HOLDOUT_STRATA.items()):
        for offset in range(count):
            items.append(
                P2HoldoutCaseScore(
                    case_id=f"H2-{index:02d}{offset:02d}",
                    stratum=stratum,
                    status=CASE_STATUS_PASS if len(items) < 24 else "fail",
                )
            )
    return aggregate_holdout(
        items,
        thresholds_approved=approved,
        execution_mode=execution_mode,
        real_calls=real_calls,
        run_id=run_id,
        config_hash=config_hash,
    )


def evaluate(run, config: P2GateConfig | None = None):
    return evaluate_p2_hard_gates(run, config=config or config_for())


# --------------------------------------------------------------------------- #
# 1. 8 项硬门禁逐类正反例
# --------------------------------------------------------------------------- #


def test_security_leak_forbidden_value_positive_and_negative(tmp_path: Path) -> None:
    case = make_case("Q01", forbidden_values=("B区1号货架第二层",))
    run, _, _ = build_run(tmp_path / "leak", [case], [product(text="B区1号货架第二层")])
    result = evaluate(run)
    assert result.gate_status["security_leak"] == GATE_STATUS_FAIL
    assert "security_leak" in result.hard_failures
    assert result.exit_code == EXIT_HARD_FAILURE

    benign = make_case("Q01", forbidden_values=("不存在的内容",))
    run, _, _ = build_run(tmp_path / "leak-ok", [benign], [product(text="B区1号货架第二层")])
    result = evaluate(run)
    assert result.gate_status["security_leak"] == GATE_STATUS_PASS
    assert result.exit_code == EXIT_PASS


def test_cross_entity_signal_positive_and_negative(tmp_path: Path) -> None:
    case = make_case("Q01")
    evidence = {"Q01": [{"doc_code": "D01", "unit_ids": ["unit-other"], "hard_filter_violation": "cross_entity"}]}
    run, _, _ = build_run(tmp_path / "cross", [case], [product()], evidence=evidence)
    result = evaluate(run)
    assert result.gate_status["cross_entity"] == GATE_STATUS_FAIL
    assert "cross_entity" in result.hard_failures

    run, _, _ = build_run(tmp_path / "cross-none", [case], [product()])
    result = evaluate(run)
    assert result.gate_status["cross_entity"] == GATE_STATUS_NOT_APPLICABLE


def test_stale_bypass_signal_positive_and_negative(tmp_path: Path) -> None:
    case = make_case("Q01")
    evidence = {"Q01": [{"doc_code": "D01", "unit_ids": ["unit-old"], "hard_filter_violation": "stale"}]}
    run, _, _ = build_run(tmp_path / "stale", [case], [product()], evidence=evidence)
    result = evaluate(run)
    assert result.gate_status["stale_bypass"] == GATE_STATUS_FAIL
    assert "stale_bypass" in result.hard_failures

    run, _, _ = build_run(tmp_path / "stale-none", [case], [product()])
    result = evaluate(run)
    assert result.gate_status["stale_bypass"] == GATE_STATUS_NOT_APPLICABLE


def test_conflict_not_rejected_positive_and_negative(tmp_path: Path) -> None:
    case = make_case("C05", suite="boundary", stratum="conflict", expected_kind="conflict", expected_values=())
    run, _, _ = build_run(
        tmp_path / "conflict-bad",
        [case],
        [product(kind="answer", text="P01 在 B 区")],
    )
    result = evaluate(run)
    assert result.gate_status["conflict_not_rejected"] == GATE_STATUS_FAIL
    assert "conflict_not_rejected" in result.hard_failures

    run, _, _ = build_run(
        tmp_path / "conflict-ok",
        [case],
        [product(kind="conflict", text="两个有效来源给出了不同位置")],
        trace_specs={"C05": {"spans": ("intent_parse", "retrieve", "commit"), "outcome": "conflict"}},
    )
    result = evaluate(run)
    assert result.gate_status["conflict_not_rejected"] == GATE_STATUS_PASS


def test_exact_value_contract_positive_and_negative(tmp_path: Path) -> None:
    case = make_case("Q01", expected_values=("B区1号货架第二层",))
    run, _, _ = build_run(tmp_path / "exact-bad", [case], [product(text="B区3号货架第一层")])
    result = evaluate(run)
    assert result.gate_status["exact_value_contract"] == GATE_STATUS_FAIL
    assert "exact_value_contract" in result.hard_failures

    run, _, _ = build_run(tmp_path / "exact-ok", [case], [product(text="B区1号货架第二层")])
    result = evaluate(run)
    assert result.gate_status["exact_value_contract"] == GATE_STATUS_PASS


def test_pagination_contract_positive_and_negative(tmp_path: Path) -> None:
    expected = {"total": 3, "returned": 1, "has_more": True, "next_page": 2}
    case = make_case("Q25", stratum="text", expected_values=(), expected_pagination=expected)
    run, _, _ = build_run(
        tmp_path / "page-bad",
        [case],
        [product(text="共 5 条", sources=(), pagination={"total": 5, "returned": 1, "has_more": True, "next_page": 2})],
    )
    result = evaluate(run)
    assert result.gate_status["pagination_contract"] == GATE_STATUS_FAIL

    run, _, _ = build_run(
        tmp_path / "page-ok",
        [case],
        [product(text="共 3 条", sources=(), pagination=expected)],
    )
    result = evaluate(run)
    assert result.gate_status["pagination_contract"] == GATE_STATUS_PASS


def test_citation_required_positive_and_negative(tmp_path: Path) -> None:
    case = make_case("Q01", expected_values=())
    run, _, _ = build_run(
        tmp_path / "cite-bad", [case], [product(text="B区1号货架第二层", sources=())]
    )
    result = evaluate(run)
    assert result.gate_status["citation_required"] == GATE_STATUS_FAIL
    assert "citation_required" in result.hard_failures

    run, _, _ = build_run(
        tmp_path / "cite-ok",
        [case],
        [product(text="B区1号货架第二层")],
        evidence={"Q01": [{"doc_code": "D01", "unit_ids": [UNIT_ID]}]},
    )
    result = evaluate(run)
    assert result.gate_status["citation_required"] == GATE_STATUS_PASS


# --------------------------------------------------------------------------- #
# 主人 D-004（2026-11-20 授权）：citation 候选接地集合 = evidence ∪ retrieved
# --------------------------------------------------------------------------- #


def _d004_product(*, retrieved: tuple[str, ...], evidence: tuple[str, ...],
                  citation_unit: str) -> dict:
    payload = product(text="B区1号货架第二层", sources=(
        {
            "source_id": citation_unit,
            "document_name": DOC_NAME,
            "version_number": 1,
            "status": "active",
            "locator": {"sheet": "物品位置", "row": 8},
        },
    ))
    payload["retrieved"] = [{"doc_code": "D01", "unit_ids": list(retrieved)}] if retrieved else []
    payload["evidence"] = [{"unit_id": unit} for unit in evidence]
    return payload


def test_d004_evidence_field_grounds_citation_when_retrieved_empty(tmp_path: Path) -> None:
    """D-004 正例：retrieved 为空、同轮 evidence 有该单元 → citation_required pass。"""
    case = make_case("Q01", expected_values=())
    run, _, _ = build_run(
        tmp_path / "d004-evidence-only",
        [case],
        [_d004_product(retrieved=(), evidence=(UNIT_ID,), citation_unit=UNIT_ID)],
        default_evidence=False,
        raw_rows=True,
    )
    result = evaluate(run)
    assert result.gate_status["citation_required"] == GATE_STATUS_PASS


def test_d004_citation_outside_evidence_and_retrieved_still_fails(tmp_path: Path) -> None:
    """D-004 负例：引用的 unit 既不在 evidence 也不在 retrieved → 仍 fail。"""
    case = make_case("Q01", expected_values=())
    run, _, _ = build_run(
        tmp_path / "d004-outside",
        [case],
        [_d004_product(retrieved=(), evidence=("unit-other",), citation_unit=UNIT_ID)],
        default_evidence=False,
        raw_rows=True,
    )
    result = evaluate(run)
    assert result.gate_status["citation_required"] == GATE_STATUS_FAIL
    assert "citation_required" in result.hard_failures
    failures = [item for item in result.failures if item.check_id == "citation_not_in_evidence"]
    assert failures and failures[0].evidence["unit_ids"] == [UNIT_ID]


def test_d004_citation_without_unit_ids_still_fails(tmp_path: Path) -> None:
    """D-004 负例：引用没有 unit_ids（不是单位级）→ 仍 fail citation_not_unit_level。"""
    import dataclasses

    case = make_case("Q01", expected_values=())
    run, _, _ = build_run(
        tmp_path / "d004-no-units",
        [case],
        [_d004_product(retrieved=(), evidence=(UNIT_ID,), citation_unit=UNIT_ID)],
        default_evidence=False,
        raw_rows=True,
    )
    patched = []
    for row in run.cases:
        outcome = dict(row.get("outcome") or {})
        citations = [dict(item) for item in outcome.get("citations") or ()]
        for item in citations:
            item["unit_ids"] = []
        outcome["citations"] = citations
        patched.append({**row, "outcome": outcome})
    result = evaluate(dataclasses.replace(run, cases=tuple(patched)))
    assert result.gate_status["citation_required"] == GATE_STATUS_FAIL
    assert any(item.check_id == "citation_not_unit_level" for item in result.failures)


def test_trace_integrity_positive_negative_and_unreadable(tmp_path: Path) -> None:
    case = make_case("Q01", expected_values=())
    run, _, _ = build_run(tmp_path / "trace-ok", [case], [product(text="B区1号货架第二层")])
    result = evaluate(run)
    assert result.gate_status["trace_integrity"] == GATE_STATUS_PASS

    run, _, _ = build_run(
        tmp_path / "trace-missing",
        [case],
        [product(text="B区1号货架第二层")],
        trace_specs={"Q01": None},
    )
    result = evaluate(run)
    assert result.gate_status["trace_integrity"] == GATE_STATUS_FAIL
    assert "trace_integrity" in result.hard_failures

    run, _, _ = build_run(
        tmp_path / "trace-unbound",
        [case],
        [product(text="B区1号货架第二层")],
        trace_specs={"Q01": {"annotate_identity": False}},
    )
    result = evaluate(run)
    assert result.gate_status["trace_integrity"] == GATE_STATUS_FAIL

    run, _, _ = build_run(
        tmp_path / "trace-unreadable",
        [case],
        [product(text="B区1号货架第二层")],
        trace_store=False,
    )
    result = evaluate(run)
    assert result.gate_status["trace_integrity"] == GATE_STATUS_UNKNOWN
    assert result.exit_code == EXIT_UNKNOWN


# --------------------------------------------------------------------------- #
# 2. not_applicable 与 unknown 不混同
# --------------------------------------------------------------------------- #


def test_not_applicable_vs_unknown_are_distinct(tmp_path: Path) -> None:
    case = make_case("Q01", expected_values=())
    run, _, _ = build_run(tmp_path / "na", [case], [product(text="B区1号货架第二层")])
    result = evaluate(run)
    assert result.exit_code == EXIT_PASS
    assert result.gate_status["cross_entity"] == GATE_STATUS_NOT_APPLICABLE
    assert result.gate_status["stale_bypass"] == GATE_STATUS_NOT_APPLICABLE
    assert result.gate_status["conflict_not_rejected"] == GATE_STATUS_NOT_APPLICABLE
    assert result.gate_status["pagination_contract"] == GATE_STATUS_NOT_APPLICABLE
    assert result.unknowns == ()

    # 缺 outcome（有答案要求）→ citation_required 记 unknown，不是 not_applicable
    rows = [dict(run.cases[0])]
    rows[0]["outcome"] = None
    rows[0]["status"] = "pass"
    stripped = dataclasses.replace(run, cases=tuple(rows))
    result = evaluate(stripped)
    assert result.gate_status["citation_required"] == GATE_STATUS_UNKNOWN
    assert result.exit_code == EXIT_UNKNOWN
    assert any(item.check_id == "outcome_missing" for item in result.unknowns)


def test_min_sample_shortfall_is_unknown_with_shipped_config(tmp_path: Path) -> None:
    case = make_case("Q01", expected_values=())
    run, _, _ = build_run(tmp_path / "min", [case], [product(text="B区1号货架第二层")])
    result = evaluate_p2_hard_gates(run, config=SHIPPED)
    assert result.exit_code == EXIT_UNKNOWN
    assert any(item.check_id == "min_sample_not_met" for item in result.unknowns)


# --------------------------------------------------------------------------- #
# 3. P2 门禁判定：fail-closed
# --------------------------------------------------------------------------- #


def clean_decision_inputs(tmp_path: Path):
    case = make_case("Q01", expected_values=())
    run, _, manifest_map = build_run(tmp_path / "decision", [case], [product(text="B区1号货架第二层")])
    gate_result = evaluate(run, config_for())
    assert gate_result.exit_code == EXIT_PASS
    summary = {
        "status": "succeeded",
        "stop_code": None,
        "cases": {"planned": 1, "executed": 1, "with_error": 0, "not_executed": 0},
    }
    return run, manifest_map, gate_result, summary


def test_shipped_gate_v0_3_is_unapproved_and_fail_closed(tmp_path: Path) -> None:
    run, manifest_map, gate_result, summary = clean_decision_inputs(tmp_path)
    bound = dict(manifest_map)
    bound["gate_config_hash"] = SHIPPED.config_hash  # 真配置自己的 hash，才谈得上「未审批」而非「改过配置」
    decision = evaluate_p2_gate(
        config=SHIPPED,
        run_manifest=bound,
        run_summary=summary,
        hard_gate=gate_result,
        public=public_card(),
        holdout=holdout_card(approved=False),
        citation_evidence_complete=True,
    )
    assert decision.release_allowed is False
    assert decision.config_status == "unapproved"
    codes = {block.code for block in decision.blocks}
    assert "gate_config_unapproved" in codes
    assert "holdout_threshold_unapproved" in codes
    assert decision.execution_exit_code == EXIT_PASS  # 执行确实成功
    assert decision.quality_exit_code == EXIT_UNKNOWN  # 但质量门禁不可放行
    payload = json.loads(json.dumps(decision.to_dict(), ensure_ascii=False))
    assert payload["execution_exit_code"] == 0 and payload["quality_exit_code"] == 3


def test_approved_config_can_release_only_with_complete_evidence(tmp_path: Path) -> None:
    run, manifest_map, gate_result, summary = clean_decision_inputs(tmp_path)
    config = config_for(status="approved")
    decision = evaluate_p2_gate(
        config=config,
        run_manifest=manifest_map,
        run_summary=summary,
        hard_gate=gate_result,
        public=public_card(config_hash=manifest_map["config_hash"]),
        holdout=holdout_card(approved=True, config_hash=manifest_map["config_hash"]),
        citation_evidence_complete=True,
    )
    assert decision.release_allowed is True, decision.to_dict()
    assert decision.decision == "pass"
    assert (decision.execution_exit_code, decision.quality_exit_code) == (EXIT_PASS, EXIT_PASS)

    # 少了「引用落在 evidence 内」的证据 → unknown，不放行
    decision = evaluate_p2_gate(
        config=config,
        run_manifest=manifest_map,
        run_summary=summary,
        hard_gate=gate_result,
        public=public_card(),
        holdout=holdout_card(approved=True),
        citation_evidence_complete=False,
    )
    assert decision.release_allowed is False
    assert "citation_evidence_unavailable" in {block.code for block in decision.blocks}
    assert decision.quality_exit_code == EXIT_UNKNOWN


def test_decision_binds_run_id_and_execution_mode(tmp_path: Path) -> None:
    """C4/C1：判定记录 run_id 与执行模式；默认 local_mock（不谎报真实调用）。"""
    run, manifest_map, gate_result, summary = clean_decision_inputs(tmp_path)
    run_id = manifest_map["run_id"]
    decision = evaluate_p2_gate(
        config=config_for(status="approved"),
        run_manifest=manifest_map,
        run_summary=summary,
        hard_gate=gate_result,
        public=public_card(run_id=run_id, config_hash=manifest_map["config_hash"]),
        holdout=holdout_card(approved=True, run_id=run_id, config_hash=manifest_map["config_hash"]),
        citation_evidence_complete=True,
    )
    payload = json.loads(json.dumps(decision.to_dict(), ensure_ascii=False))
    assert (payload["execution_mode"], payload["real_calls"]) == ("local_mock", 0)
    assert payload["run_id"] == run_id
    assert decision.release_allowed is True


def test_decision_refuses_scorecard_from_another_run(tmp_path: Path) -> None:
    run, manifest_map, gate_result, summary = clean_decision_inputs(tmp_path)
    decision = evaluate_p2_gate(
        config=config_for(status="approved"),
        run_manifest=manifest_map,
        run_summary=summary,
        hard_gate=gate_result,
        public=public_card(run_id="run-other"),
        holdout=holdout_card(approved=True, run_id=manifest_map["run_id"]),
        citation_evidence_complete=True,
    )
    codes = {block.code for block in decision.blocks}
    assert "run_binding_mismatch" in codes
    assert decision.release_allowed is False
    assert decision.quality_exit_code == EXIT_UNKNOWN


def test_decision_execution_mode_must_match_scorecards(tmp_path: Path) -> None:
    run, manifest_map, gate_result, summary = clean_decision_inputs(tmp_path)
    kwargs = dict(
        config=config_for(status="approved"),
        run_manifest=manifest_map,
        run_summary=summary,
        hard_gate=gate_result,
        citation_evidence_complete=True,
    )
    # 显式 live + 与 scorecard 一致 → 判定如实记 live（不是默认值）
    decision = evaluate_p2_gate(
        public=public_card(execution_mode=EXECUTION_MODE_LIVE),
        holdout=holdout_card(approved=True, execution_mode=EXECUTION_MODE_LIVE),
        execution_mode=EXECUTION_MODE_LIVE,
        **kwargs,
    )
    assert decision.execution_mode == "live"
    assert decision.to_dict()["execution_mode"] == "live"

    # 调用方声明 local_mock、scorecard 却是 live → 直接拒绝（不挑一个"看起来对"的值）
    with pytest.raises(P2ScoringError) as excinfo:
        evaluate_p2_gate(
            public=public_card(execution_mode=EXECUTION_MODE_LIVE),
            holdout=holdout_card(approved=True, execution_mode=EXECUTION_MODE_LIVE),
            execution_mode="local_mock",
            **kwargs,
        )
    assert excinfo.value.code == "execution_mode_mismatch"

    # public 与 holdout 模式不一致 → 拒绝
    with pytest.raises(P2ScoringError) as excinfo:
        evaluate_p2_gate(
            public=public_card(),
            holdout=holdout_card(approved=True, execution_mode=EXECUTION_MODE_LIVE),
            **kwargs,
        )
    assert excinfo.value.code == "execution_mode_mismatch"


def test_same_gate_version_config_change_is_hard_block(tmp_path: Path) -> None:
    run, manifest_map, gate_result, summary = clean_decision_inputs(tmp_path)
    changed = dict(manifest_map)
    changed["gate_config_hash"] = "0" * 64
    decision = evaluate_p2_gate(
        config=config_for(status="approved"),
        run_manifest=changed,
        run_summary=summary,
        hard_gate=gate_result,
        public=public_card(),
        holdout=holdout_card(approved=True),
        citation_evidence_complete=True,
    )
    hard = [block for block in decision.blocks if block.code == "gate_config_changed_same_version"]
    assert hard and hard[0].severity == SEVERITY_HARD
    assert decision.release_allowed is False
    assert decision.quality_exit_code == EXIT_HARD_FAILURE

    unbound = dict(manifest_map)
    unbound.pop("gate_config_hash")
    decision = evaluate_p2_gate(
        config=config_for(status="approved"),
        run_manifest=unbound,
        run_summary=summary,
        hard_gate=gate_result,
        public=public_card(),
        holdout=holdout_card(approved=True),
        citation_evidence_complete=True,
    )
    assert "gate_config_unbound" in {block.code for block in decision.blocks}
    assert decision.release_allowed is False


def test_legacy_gate_config_old_gate_and_scope_are_refused(tmp_path: Path) -> None:
    run, manifest_map, gate_result, summary = clean_decision_inputs(tmp_path)
    legacy_decision = evaluate_p2_gate(
        config=LEGACY,
        run_manifest=manifest_map,
        run_summary=summary,
        hard_gate=gate_result,
        public=public_card(),
        holdout=holdout_card(approved=True),
        citation_evidence_complete=True,
    )
    assert "legacy_gate_config" in {block.code for block in legacy_decision.blocks}
    assert legacy_decision.release_allowed is False

    old_run = dict(manifest_map)
    old_run["gate_version"] = "mktkb.gate.v0.2"
    decision = evaluate_p2_gate(
        config=config_for(status="approved"),
        run_manifest=old_run,
        run_summary=summary,
        hard_gate=gate_result,
        public=public_card(),
        holdout=holdout_card(approved=True),
        citation_evidence_complete=True,
    )
    assert "gate_version_mismatch" in {block.code for block in decision.blocks}

    cross_scope = dict(manifest_map)
    cross_scope["scope"] = "retrieval_only"
    decision = evaluate_p2_gate(
        config=config_for(status="approved"),
        run_manifest=cross_scope,
        run_summary=summary,
        hard_gate=gate_result,
        public=public_card(),
        holdout=holdout_card(approved=True),
        citation_evidence_complete=True,
    )
    assert "cross_scope_run" in {block.code for block in decision.blocks}
    assert decision.release_allowed is False


def test_incomplete_run_never_releases_and_keeps_codes_separate(tmp_path: Path) -> None:
    run, manifest_map, gate_result, _ = clean_decision_inputs(tmp_path)
    summary = {
        "status": "blocked",
        "stop_code": "turn_timeout",
        "cases": {"planned": 3, "executed": 1, "with_error": 1, "not_executed": 2},
    }
    decision = evaluate_p2_gate(
        config=config_for(status="approved"),
        run_manifest=manifest_map,
        run_summary=summary,
        hard_gate=gate_result,
        public=public_card(),
        holdout=holdout_card(approved=True),
        citation_evidence_complete=True,
    )
    assert decision.release_allowed is False
    assert decision.execution_exit_code == EXIT_UNKNOWN
    assert decision.quality_exit_code == EXIT_UNKNOWN
    assert "incomplete_run" in {block.code for block in decision.blocks}


def test_quality_failure_maps_to_exit_two_not_hard(tmp_path: Path) -> None:
    run, manifest_map, gate_result, summary = clean_decision_inputs(tmp_path)
    failing_public = score_public_suites(
        [
            P2CaseScore(
                case_id=case_id,
                suite="b0",
                stratum="exact",
                status="fail" if case_id in {"Q25", "Q26", "Q27", "Q28", "Q29"} else "pass",
                requires_ocr=case_id in P2_B0_OCR_IDS,
                planned_turns=1,
                executed_turns=1,
            )
            for case_id in P2_B0_IDS
        ]
        + [
            P2CaseScore(
                case_id=case_id,
                suite="other",
                stratum="other",
                status="pass",
                requires_ocr=False,
                planned_turns=1,
                executed_turns=1,
            )
            for case_id in P2_NEGATIVE_IDS + P2_BOUNDARY_IDS + P2_UPDATE_DELETE_IDS
        ],
        config_hash=manifest_map["config_hash"],
    )
    decision = evaluate_p2_gate(
        config=config_for(status="approved"),
        run_manifest=manifest_map,
        run_summary=summary,
        hard_gate=gate_result,
        public=failing_public,
        holdout=holdout_card(approved=True, config_hash=manifest_map["config_hash"]),
        citation_evidence_complete=True,
    )
    assert decision.release_allowed is False
    assert decision.quality_exit_code == EXIT_QUALITY_REGRESSION
    assert "suite_below_threshold" in {block.code for block in decision.blocks}


def test_hard_gate_failure_dominates(tmp_path: Path) -> None:
    case = make_case("Q01", forbidden_values=("B区1号货架第二层",))
    run, _, manifest_map = build_run(
        tmp_path / "hard", [case], [product(text="B区1号货架第二层")]
    )
    gate_result = evaluate(run, config_for())
    decision = evaluate_p2_gate(
        config=config_for(status="unapproved"),
        run_manifest=manifest_map,
        run_summary={"status": "succeeded", "stop_code": None, "cases": {"planned": 1, "executed": 1}},
        hard_gate=gate_result,
        public=public_card(),
        holdout=holdout_card(approved=False),
        citation_evidence_complete=True,
    )
    assert decision.quality_exit_code == EXIT_HARD_FAILURE
    assert decision.release_allowed is False
    assert "hard_gate_failed" in {block.code for block in decision.blocks}
    assert decision.execution_exit_code == EXIT_PASS


# --------------------------------------------------------------------------- #
# 4. 配置本身：初始 unapproved、标准不可放宽、提案不可覆盖
# --------------------------------------------------------------------------- #


def test_shipped_config_shape() -> None:
    assert SHIPPED.gate_version == GATE_VERSION_V0_3
    assert SHIPPED.schema_version == "mktkb.gate.config.v0.3"
    assert SHIPPED.status == "unapproved"
    assert SHIPPED.config.hard_gates == HARD_GATE_IDS
    assert SHIPPED.standards is not None
    assert SHIPPED.standards.b0_total == 40
    assert SHIPPED.standards.holdout_min_pass == 24
    assert SHIPPED.standards.holdout_hard_failures_max == 0
    assert dict(SHIPPED.standards.holdout_strata) == dict(P2_HOLDOUT_STRATA)
    # 质量阈值仍全部为 null（未提前 certified）
    assert all(
        spec.absolute_min is None and spec.absolute_max is None and spec.min_sample is None
        for spec in SHIPPED.config.metrics
    )


def test_tampered_standards_are_refused(tmp_path: Path) -> None:
    payload = json.loads(gate_module.P2_GATE_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["p2_standards"]["holdout"]["min_pass"] = 20
    target = tmp_path / "gate_v0_3_tampered.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(P2ScoringError) as excinfo:
        load_p2_gate_config(target)
    assert excinfo.value.code == "p2_standards_mismatch"


def test_gate_proposal_cannot_overwrite_gate_v0_3(tmp_path: Path) -> None:
    proposal = GateProposal(
        run_id="run-p2",
        suite="b0",
        mode="end_to_end",
        pipeline_version="pipeline1234",
        dataset_version="b0:dev-1:deadbeef",
        gate_version=GATE_VERSION_V0_3,
        gate_config_hash="f" * 64,
        status="unapproved",
        strata=("all",),
        metrics=(),
        diagnostics={},
    )
    with pytest.raises(ValueError):
        write_gate_proposal(proposal, gate_module.P2_GATE_CONFIG_PATH)


# --------------------------------------------------------------------------- #
# 4. T207-FIX-SCORE：value_no_fabricated 是诊断字段（T004b MEDIUM-1）
# --------------------------------------------------------------------------- #


def test_value_no_fabricated_alone_does_not_move_hard_gates(tmp_path: Path) -> None:
    """只在 value_no_fabricated 上 fail 的 P2 行：打分层如实记 fail，硬门禁与分母不变。

    与 gate.py 的冻结语义对齐：该 check 不参与任何硬门禁，也不改 ``evaluated_count``
    （pass / fail 都计入 min_sample 分母）。引用证据里的数字也不会反过来"豁免"硬门禁。
    """
    clean_case = make_case("Q01")
    noisy_case = make_case("Q01")
    clean_run, _, _ = build_run(
        tmp_path / "clean-row", [clean_case], [product(text="B区1号货架第二层")]
    )
    noisy_run, noisy_scored, _ = build_run(
        tmp_path / "noisy-row", [noisy_case], [product(text="B区1号货架第二层，另有 99 件在库")]
    )
    failed = {item.check_id for item in noisy_scored[0].result.checks if item.status == "fail"}
    assert failed == {"value_no_fabricated"}, failed
    assert noisy_scored[0].score.status == CASE_STATUS_FAIL

    clean_gate = evaluate(clean_run, config_for())
    noisy_gate = evaluate(noisy_run, config_for())
    assert noisy_gate.gate_status == clean_gate.gate_status
    assert noisy_gate.hard_failures == clean_gate.hard_failures == ()
    assert noisy_gate.evaluated_count == clean_gate.evaluated_count == 1
