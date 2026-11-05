"""T006b：质量门禁层 + 校准提案 + 质量 waiver 测试（设计 §8.2 / §8.3 / §8.4）。

覆盖 handoff §5 六条：

1. 质量指标按 ``stratum`` + ``all`` 报告，不设综合分，缺失指标显式 unknown；
2. 阈值语义完整：``absolute_min``/``absolute_max``、同 ``pipeline_version`` 的
   ``max_regression_pp``、按指标各自分母的 ``min_sample``（检索=有 gold、答案=scored、
   拒答=适用样本；OCR 与 error 行一律排除，不复用 ``hard_gate_min_sample``）；
3. ``calibrate_gate`` 只产出 ``GateProposal``（run_id + 观测值 + 建议阈值 +
   ``gate_config_hash``），不写回 ``gate_v0_1.json``；未审批 → unknown → exit 3；
4. 退出码 2 只由质量失败触发，硬门禁失败仍 1；样本不足/未审批 3；通过 0；
5. 质量 waiver 必须带 ``reason`` + ``approver``，缺一拒绝；硬门禁豁免被拒绝；
6. 默认配置仍是 ``unapproved`` + 空阈值，质量层必须显式 ``quality=True`` 才评估
   （否则 T006a 硬门禁语义不变，exit=0 只代表硬门禁通过）。

全部用合成 ``RunResult`` + 真实 ``TraceRepository``（tmp_path），零真实模型 / OCR /
embedding / rerank 调用，不读 ``.env``，不写 ``var/``。
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import math
from pathlib import Path

import pytest

from mktkb.evaluation.dataset import CaseSpec, write_cases
from mktkb.evaluation.gate import (
    EXIT_HARD_FAILURE,
    EXIT_PASS,
    EXIT_QUALITY_REGRESSION,
    EXIT_UNKNOWN,
    HARD_GATE_IDS,
    QUALITY_METRIC_GROUPS,
    GateConfig,
    GateProposal,
    QualityPolicy,
    QualityWaiver,
    calibrate_gate,
    evaluate_gate,
    load_gate_config,
    write_gate_proposal,
)
from mktkb.evaluation.runner import RunManifest, RunResult
from mktkb.observability.contracts import (
    GATE_SCHEMA_VERSION,
    SpanRecord,
    TraceRecord,
)
from mktkb.observability.store import TraceRepository

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = ROOT / "docs" / "evaluation" / "gate_v0_1.json"

UNIT_KEY = "sheet:A:row:8"
UNIT_ID = "D01-0"

DEFAULT_ROW_METRICS = {
    "Recall@10": 1.0,
    "MRR@10": 1.0,
    "nDCG@10": 1.0,
    "hard_filter_violations": 0,
    "retrieved_units": 1,
    "empty_recall": 0.0,
    "gold_units": 1,
    "value_hit": 1.0,
    "source_hit": 1.0,
    "kind_correct": 1.0,
    "citation_precision": 1.0,
    "citation_recall": 1.0,
}


# --------------------------------------------------------------------------- #
# 合成产物 helper（manifest / 数据集 / cases 行 / trace / summary）
# --------------------------------------------------------------------------- #


def make_manifest(**overrides) -> RunManifest:
    payload = {
        "run_id": "run-b0",
        "mode": "local",
        "scope": "end_to_end",
        "suite": "b0",
        "dataset_version": "b0:dev-1:deadbeefcafe",
        "dataset_sha256": "a" * 64,
        "corpus_manifest_sha256": "b" * 64,
        "business_date": "2026-10-28",
        "index_revision": 6,
        "pipeline_version": "pipeline1234",
        "gate_version": GATE_SCHEMA_VERSION,
        "label_version": "dev-1",
        "created_at": "2026-11-05T00:00:00.000+00:00",
        "case_count": 1,
        "config_hash": "c" * 12,
        "dataset_path": "",
    }
    payload.update(overrides)
    return RunManifest(**payload)


def make_case(case_id: str = "Q01", **overrides) -> CaseSpec:
    payload = {
        "case_id": case_id,
        "suite": "b0",
        "split": "dev",
        "stratum": "exact",
        "business_date": "2026-10-28",
        "question": "物品 P01 在哪里？",
        "expected_kind": "answer",
        "expected_values": ("P01",),
        "expected_sources": ({"doc_code": "D01", "unit_key": UNIT_KEY},),
        "labeler": "lead",
        "label_version": "dev-1",
    }
    payload.update(overrides)
    return CaseSpec(**payload)


def make_row(case: CaseSpec, **overrides) -> dict:
    """与 runner 同形的 ``cases.jsonl`` 行；``metrics`` 默认全 1.0。"""
    outcome = {
        "kind": "answer",
        "text": "P01 位于 A 区 8 号",
        "path": "rag",
        "trace_id": f"trace-{case.case_id}",
        "pagination": {},
        "citations": [
            {
                "doc_code": "D01",
                "unit_key": UNIT_KEY,
                "unit_ids": [UNIT_ID],
                "locator": {},
                "text": "P01 位于 A 区 8 号",
                "kind": "table_row",
            }
        ],
        "facts": [],
        "retrieved": [
            {
                "doc_code": "D01",
                "unit_ids": [UNIT_ID],
                "unit_key": UNIT_KEY,
                "locator": {},
                "chunk_id": "chunk-1",
                "hard_filter_violation": None,
            }
        ],
    }
    row = {
        "case_id": case.case_id,
        "suite": case.suite,
        "status": "pass",
        "trace_id": f"trace-{case.case_id}",
        "previous_trace_id": None,
        "replayed": False,
        "checks": [],
        "metrics": dict(DEFAULT_ROW_METRICS),
        "refused": False,
        "should_refuse": bool(case.should_refuse),
        "path": "rag",
        "latency_ms": 10,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_cny": None,
        "duration_ms": 10,
        "turns_executed": 1,
        "multi_turn_claimed": False,
        "outcome": outcome,
        "gold": {
            "case_id": case.case_id,
            "requires_ocr": bool(case.requires_ocr),
            "skipped": False,
            "sources": [
                {
                    "doc_code": "D01",
                    "doc_id": "D01",
                    "unit_ids": [UNIT_ID],
                    "unit_keys": [UNIT_KEY],
                }
            ],
            "unit_ids": [UNIT_ID],
            "relevant_unit_ids": [UNIT_ID],
        },
        "error": None,
    }
    for key, value in overrides.items():
        if key == "outcome":
            outcome = None if value is None else {**outcome, **value}
        elif key == "metrics":
            row["metrics"] = value
        elif key == "pagination":
            outcome = {**outcome, "pagination": value}
        else:
            row[key] = value
    row["outcome"] = outcome
    return row


def write_trace(repo: TraceRepository, manifest: RunManifest, case_id: str) -> None:
    trace_id = f"trace-{case_id}"
    record = TraceRecord(
        trace_id=trace_id,
        request_id=None,
        http_request_id=f"{manifest.run_id}:{case_id}",
        mode=manifest.mode,
        scope=manifest.scope,
        path="rag",
        case_id=case_id,
        replayed=False,
        outcome_kind="answer",
        reason=None,
        latency_ms=1,
        status="ok",
        dataset_version=manifest.dataset_version,
        run_id=manifest.run_id,
        index_revision=str(manifest.index_revision),
        manifest_sha256=manifest.corpus_manifest_sha256,
        pipeline_version=manifest.pipeline_version,
        config_hash=manifest.config_hash,
    )
    spans = [
        SpanRecord(span_id=f"{trace_id}-{name}", trace_id=trace_id, name=name, status="ok")
        for name in ("parse", "recall", "fuse", "answer", "commit")
    ]
    repo.write(record, spans)


def _write_json(path: Path, payload: dict) -> None:
    path.write_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    )


def build_run(
    tmp_path: Path,
    *,
    cases: list[CaseSpec],
    rows: list[dict],
    summary: dict | None = None,
    manifest: RunManifest | None = None,
    traces: bool = True,
) -> RunResult:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = tmp_path / "dataset.jsonl"
    write_cases(dataset_path, cases)
    base = manifest or make_manifest(suite=cases[0].suite if cases else "b0")
    manifest = dataclasses.replace(base, dataset_path=str(dataset_path), case_count=len(cases))

    repo = TraceRepository(run_dir / "traces.sqlite3")
    try:
        if traces:
            for case, row in zip(cases, rows):
                if row.get("status") == "skipped_requires_ocr" or row.get("error"):
                    continue
                write_trace(repo, manifest, case.case_id)
    finally:
        repo.close()

    _write_json(run_dir / "run_manifest.json", manifest.to_dict())
    (run_dir / "cases.jsonl").write_bytes(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
        ).encode("utf-8")
    )
    summary_payload = summary if summary is not None else {}
    _write_json(run_dir / "summary.json", summary_payload)
    return RunResult(
        manifest=manifest,
        out_dir=run_dir,
        cases=tuple(rows),
        summary=summary_payload,
    )


def _mean(values) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return sum(numbers) / len(numbers) if numbers else None


def _pct(values, fraction: float):
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def summarize(cases: list[CaseSpec], rows: list[dict], **overrides) -> dict:
    """独立于 gate 实现的 summary.json 口径（runner 全量指标）。"""
    eligible = [
        (case, row)
        for case, row in zip(cases, rows)
        if row.get("status") in {"pass", "fail"} and row.get("status") != "skipped_requires_ocr"
    ]
    gold = [(case, row) for case, row in eligible if case.expected_sources or case.relevant_units]
    retrieved = sum(int(row["metrics"].get("retrieved_units") or 0) for _, row in gold)
    violations = sum(int(row["metrics"].get("hard_filter_violations") or 0) for _, row in gold)
    tp = sum(1 for case, row in eligible if case.should_refuse and row.get("refused"))
    fn = sum(1 for case, row in eligible if case.should_refuse and not row.get("refused"))
    fp = sum(1 for case, row in eligible if not case.should_refuse and row.get("refused"))
    tn = sum(1 for case, row in eligible if not case.should_refuse and not row.get("refused"))
    latencies = sorted(
        int(row["latency_ms"]) for _, row in eligible if row.get("latency_ms") is not None
    )
    costs = [float(row["cost_cny"]) for _, row in eligible if row.get("cost_cny") is not None]
    metrics = {
        "case_count": len(rows),
        "scored_count": len(eligible),
        "Recall@10": _mean(row["metrics"].get("Recall@10") for _, row in gold),
        "MRR@10": _mean(row["metrics"].get("MRR@10") for _, row in gold),
        "nDCG@10": _mean(row["metrics"].get("nDCG@10") for _, row in gold),
        "hard_filter_violation_rate": (violations / retrieved) if retrieved else None,
        "empty_recall_rate": _mean(row["metrics"].get("empty_recall") for _, row in gold),
        "value_hit": _mean(row["metrics"].get("value_hit") for _, row in eligible),
        "source_hit": _mean(row["metrics"].get("source_hit") for _, row in eligible),
        "kind_correct": _mean(row["metrics"].get("kind_correct") for _, row in eligible),
        "citation_precision": _mean(row["metrics"].get("citation_precision") for _, row in eligible),
        "citation_recall": _mean(row["metrics"].get("citation_recall") for _, row in eligible),
        "refusal_recall": tp / (tp + fn) if (tp + fn) else None,
        "false_refusal_rate": fp / (fp + tn) if (fp + tn) else None,
        "refusal_precision": tp / (tp + fp) if (tp + fp) else None,
        "p50_latency_ms": _pct(latencies, 0.50),
        "p95_latency_ms": _pct(latencies, 0.95),
        "cost_per_case_cny": (sum(costs) / len(costs)) if costs else None,
    }
    metrics.update(overrides)
    return {"suite": cases[0].suite if cases else "b0", "metrics": metrics}


def metric_spec(
    name: str,
    group: str,
    direction: str,
    *,
    min_sample: int | None = 1,
    absolute_min: float | None = None,
    absolute_max: float | None = None,
    max_regression_pp: float | None = None,
) -> dict:
    return {
        "name": name,
        "group": group,
        "direction": direction,
        "min_sample": min_sample,
        "absolute_min": absolute_min,
        "absolute_max": absolute_max,
        "max_regression_pp": max_regression_pp,
    }


def config_payload(**overrides) -> dict:
    payload = {
        "schema_version": "mktkb.gate.config.v0.1",
        "gate_version": GATE_SCHEMA_VERSION,
        "status": "approved",
        "hard_gates": list(HARD_GATE_IDS),
        "hard_gate_min_sample": {"b0": 1, "badcase": 1},
        "sensitive_patterns": [],
        "metrics": [
            metric_spec(
                "Recall@10",
                "retrieval",
                "higher_is_better",
                min_sample=1,
                absolute_min=0.5,
            )
        ],
        "notes": "T006b 测试配置",
    }
    payload.update(overrides)
    return payload


def make_config(tmp_path: Path, *, name: str = "gate_config.json", **overrides) -> GateConfig:
    path = tmp_path / name
    _write_json(path, config_payload(**overrides))
    return load_gate_config(path)


def evaluate_quality(run: RunResult, config: GateConfig, *, baseline=None, **kwargs):
    kwargs.setdefault("require_trace", False)
    return evaluate_gate(run, baseline, config, quality=True, **kwargs)


def quality_rows(result, metric: str, stratum: str):
    return [
        item
        for item in result.quality.metrics
        if item.metric == metric and item.stratum == stratum
    ]


def single_quality_metric(result, metric: str, stratum: str):
    items = quality_rows(result, metric, stratum)
    assert len(items) == 1, (metric, stratum, [item.to_dict() for item in result.quality.metrics])
    return items[0]


# --------------------------------------------------------------------------- #
# 1. 指标清单 / stratum + all / 不设综合分
# --------------------------------------------------------------------------- #


def test_default_config_declares_full_catalog_and_stays_unapproved() -> None:
    config = load_gate_config(DEFAULT_CONFIG_PATH)
    assert config.status == "unapproved"
    names = {item.name for item in config.metrics}
    assert {
        "Recall@10",
        "MRR@10",
        "nDCG@10",
        "hard_filter_violation_rate",
        "empty_recall_rate",
        "value_hit",
        "source_hit",
        "kind_correct",
        "citation_precision",
        "citation_recall",
        "refusal_recall",
        "false_refusal_rate",
        "refusal_precision",
        "p95_latency_ms",
        "cost_per_case_cny",
    } <= names
    assert {item.group for item in config.metrics} == QUALITY_METRIC_GROUPS
    for item in config.metrics:
        assert item.absolute_min is None
        assert item.absolute_max is None
        assert item.max_regression_pp is None
        assert item.min_sample is None


def test_quality_layer_is_off_by_default_and_t006a_semantics_unchanged(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    config = make_config(tmp_path)

    # quality=False（默认）：只跑 T006a 硬门禁，exit 0 只代表硬门禁通过。
    result = evaluate_gate(run, None, config)
    assert result.exit_code == EXIT_PASS
    assert result.quality is None
    assert result.quality_status == "not_evaluated"
    # evaluate_gate 仍不接受 waiver 参数（T006a 断言保持）。
    parameters = inspect.signature(evaluate_gate).parameters
    assert "waiver" not in parameters and "waivers" not in parameters


def test_quality_reports_stratum_and_all_without_composite_score(tmp_path: Path) -> None:
    cases = [
        make_case("Q01", stratum="exact"),
        make_case("Q02", stratum="text", expected_values=()),
        make_case(
            "Q03",
            stratum="ocr",
            requires_ocr=True,
            expected_values=(),
            expected_sources=({"doc_code": "D07", "locator": {"page": 3}},),
        ),
    ]
    rows = [
        make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 1.0}),
        make_row(cases[1], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.5}),
        make_row(cases[2], status="skipped_requires_ocr", outcome=None),
    ]
    summary = summarize(cases, rows)
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summary)
    config = make_config(
        tmp_path,
        metrics=[
            metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.4),
            metric_spec("value_hit", "answer", "higher_is_better", absolute_min=0.4),
            metric_spec("p95_latency_ms", "runtime", "lower_is_better", absolute_max=100.0),
        ],
    )
    result = evaluate_quality(run, config)
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.quality.strata == ("all", "exact", "text")
    assert "ocr" not in {item.stratum for item in result.quality.metrics}
    assert set(result.quality.stratum_status) == {"all", "exact", "text"}
    payload = result.quality.to_dict()
    assert "score" not in payload and "composite" not in payload
    for item in result.quality.metrics:
        assert item.group in QUALITY_METRIC_GROUPS
        assert item.stratum in {"all", "exact", "text"}
        assert item.denominator_basis
    # all 级观测来自 summary.json
    assert single_quality_metric(result, "Recall@10", "all").source == "summary.json"
    assert single_quality_metric(result, "Recall@10", "exact").observed == 1.0
    assert single_quality_metric(result, "Recall@10", "text").observed == 0.5
    assert single_quality_metric(result, "Recall@10", "all").observed == pytest.approx(0.75)


def test_missing_summary_metric_is_unknown_not_zero(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    rows = [make_row(cases[0])]
    summary = summarize(cases, rows)
    summary["metrics"].pop("Recall@10")
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summary)
    config = make_config(tmp_path)
    result = evaluate_quality(run, config)
    assert result.exit_code == EXIT_UNKNOWN
    item = single_quality_metric(result, "Recall@10", "all")
    assert item.status == "unknown"
    assert item.observed is None
    assert any(check.kind == "metric_missing" for check in item.checks)
    assert any(u.gate_id == "quality:Recall@10" for u in result.unknowns)
    # 该指标在子 stratum 中仍按行重算（不是 0）
    assert single_quality_metric(result, "Recall@10", "exact").observed == 1.0


def test_quality_unknown_when_metrics_list_is_empty(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    config = make_config(tmp_path, metrics=[])
    result = evaluate_quality(run, config)
    assert result.exit_code == EXIT_UNKNOWN
    assert result.quality.status == "unknown"
    assert any(u.check_id == "no_metrics_configured" for u in result.unknowns)


# --------------------------------------------------------------------------- #
# 2. 分母严格分离
# --------------------------------------------------------------------------- #


def test_quality_denominators_follow_metric_group(tmp_path: Path) -> None:
    cases = [
        make_case("Q01", stratum="exact"),
        make_case("Q02", stratum="text", expected_values=()),
        make_case(
            "Q03",
            stratum="text",
            expected_values=(),
            expected_sources=(),
            relevant_units=(),
        ),
        make_case(
            "Q04",
            stratum="ocr",
            requires_ocr=True,
            expected_values=(),
            expected_sources=({"doc_code": "D07", "locator": {"page": 3}},),
        ),
    ]
    rows = [
        make_row(cases[0]),
        make_row(cases[1], metrics={**DEFAULT_ROW_METRICS, "value_hit": 0.0}),
        make_row(cases[2]),
        make_row(cases[3], status="skipped_requires_ocr", outcome=None),
    ]
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summarize(cases, rows))
    config = make_config(
        tmp_path,
        metrics=[
            metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.5),
            metric_spec("value_hit", "answer", "higher_is_better", absolute_min=0.5),
        ],
    )
    result = evaluate_quality(run, config)
    recall_all = single_quality_metric(result, "Recall@10", "all")
    value_all = single_quality_metric(result, "value_hit", "all")
    # 检索只算有 gold 的非 OCR 行（Q03 无 gold → 排除），答案算全部 scored 非 OCR 行。
    assert recall_all.denominator == 2
    assert recall_all.denominator_basis == "gold_cases_non_ocr"
    assert value_all.denominator == 3
    assert value_all.denominator_basis == "scored_cases_non_ocr"
    assert recall_all.dataset_sample == 2
    assert value_all.dataset_sample == 3
    # 硬门禁 evaluated_count 是 3（含空 gold 的非 OCR 行），质量分母与它不同。
    assert result.evaluated_count == 3
    assert recall_all.denominator != result.evaluated_count


def test_refusal_denominators_exclude_error_service_and_knowledge_changed(
    tmp_path: Path,
) -> None:
    cases = [
        make_case("N01", suite="badcase", stratum="safety", should_refuse=True,
                  refusal_reason="cross_user", expected_values=(), expected_sources=()),
        make_case("N02", suite="badcase", stratum="safety", should_refuse=True,
                  refusal_reason="cross_user", expected_values=(), expected_sources=()),
        make_case("N03", suite="badcase", stratum="price", expected_values=(), expected_sources=()),
        make_case("N04", suite="badcase", stratum="price", expected_values=(), expected_sources=()),
        make_case("N05", suite="badcase", stratum="price", expected_values=(), expected_sources=()),
        make_case("N06", suite="badcase", stratum="price", expected_values=(), expected_sources=()),
        make_case("N07", suite="badcase", stratum="price", expected_values=(), expected_sources=()),
        make_case("N08", suite="badcase", stratum="price", expected_values=(), expected_sources=()),
    ]
    rows = [
        make_row(cases[0], refused=True, outcome={"kind": "not_found", "text": "", "citations": []}),
        make_row(cases[1], refused=False),
        make_row(cases[2], refused=True),
        make_row(cases[3], refused=False),
        make_row(cases[4], refused=True, outcome={"kind": "service_error", "text": ""}),
        make_row(cases[5], refused=True, outcome={"kind": "knowledge_changed", "text": ""}),
        make_row(cases[6], status="error", error={"code": "runner_error"}, outcome=None),
        make_row(cases[7], refused=True, outcome={"kind": "error", "text": ""}),
    ]
    run = build_run(
        tmp_path,
        cases=cases,
        rows=rows,
        summary=summarize(cases, rows),
        manifest=make_manifest(suite="badcase"),
    )
    config = make_config(
        tmp_path,
        hard_gate_min_sample={"badcase": 1},
        metrics=[
            metric_spec("refusal_recall", "refusal", "higher_is_better", absolute_min=0.5),
            metric_spec("false_refusal_rate", "refusal", "lower_is_better", absolute_max=1.0),
            metric_spec("refusal_precision", "refusal", "higher_is_better", absolute_min=0.0),
        ],
    )
    result = evaluate_quality(run, config)
    recall = single_quality_metric(result, "refusal_recall", "all")
    false_rate = single_quality_metric(result, "false_refusal_rate", "all")
    precision = single_quality_metric(result, "refusal_precision", "all")
    # 应拒答 2 条（服务错误/知识变更/error 行不参与）；可答 2 条（N03/N04，排除 N05-N08）。
    assert recall.denominator_basis == "should_refuse_cases"
    assert recall.denominator == 2
    assert false_rate.denominator_basis == "answerable_cases"
    assert false_rate.denominator == 2
    assert precision.denominator_basis == "refused_cases"
    assert precision.denominator == 2  # N01 真拒 + N03 误拒；service_error/knowledge_changed 被排除
    assert recall.observed == pytest.approx(0.5)
    assert false_rate.observed == pytest.approx(0.5)
    assert precision.observed == pytest.approx(0.5)


def test_quality_min_sample_uses_metric_denominator_not_hard_gate_count(tmp_path: Path) -> None:
    cases = [make_case("Q01"), make_case("Q02", stratum="text", expected_values=())]
    rows = [make_row(cases[0]), make_row(cases[1])]
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summarize(cases, rows))
    config = make_config(
        tmp_path,
        hard_gate_min_sample={"b0": 1},
        metrics=[
            metric_spec("Recall@10", "retrieval", "higher_is_better", min_sample=5,
                        absolute_min=0.5)
        ],
    )
    result = evaluate_quality(run, config)
    assert result.exit_code == EXIT_UNKNOWN
    all_item = single_quality_metric(result, "Recall@10", "all")
    assert all_item.status == "unknown"
    sample_check = next(check for check in all_item.checks if check.kind == "min_sample")
    assert sample_check.status == "unknown"
    assert sample_check.denominator == 2
    assert sample_check.threshold == 5
    assert result.min_sample == 1  # 硬门禁 min_sample 保持独立
    assert result.evaluated_count == 2


def test_ocr_and_error_rows_never_enter_quality_denominators(tmp_path: Path) -> None:
    cases = [
        make_case("Q01"),
        make_case(
            "Q02",
            stratum="ocr",
            requires_ocr=True,
            expected_values=(),
            expected_sources=({"doc_code": "D07", "locator": {"page": 3}},),
        ),
        make_case("Q03", stratum="text", expected_values=()),
    ]
    rows = [
        make_row(cases[0]),
        make_row(cases[1], status="skipped_requires_ocr", outcome=None),
        make_row(cases[2], status="error", error={"code": "gold_unresolved"}, outcome=None),
    ]
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summarize(cases, rows))
    config = make_config(
        tmp_path,
        metrics=[metric_spec("value_hit", "answer", "higher_is_better", absolute_min=0.5)],
    )
    result = evaluate_quality(run, config)
    item = single_quality_metric(result, "value_hit", "all")
    assert item.denominator == 1
    assert item.dataset_sample == 2  # Q01 + Q03（OCR 不算），error 行不入分母
    assert item.observed == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# 3. 校准提案
# --------------------------------------------------------------------------- #


def test_calibrate_gate_proposal_records_observations_and_never_writes_config(
    tmp_path: Path,
) -> None:
    cases = [make_case("Q01"), make_case("Q02", stratum="text", expected_values=())]
    rows = [
        make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.9}),
        make_row(cases[1], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.7}),
    ]
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summarize(cases, rows))
    config = make_config(
        tmp_path,
        status="unapproved",
        metrics=[
            metric_spec("Recall@10", "retrieval", "higher_is_better", min_sample=None,
                        absolute_min=None),
            metric_spec("p95_latency_ms", "runtime", "lower_is_better", min_sample=None,
                        absolute_max=None),
        ],
    )
    before = Path(config.source_path).read_bytes()
    proposal = calibrate_gate(run, config)
    assert isinstance(proposal, GateProposal)
    assert proposal.run_id == run.manifest.run_id
    assert proposal.gate_config_hash == config.config_hash
    assert proposal.status == "unapproved"
    assert proposal.pipeline_version == run.manifest.pipeline_version
    rows_by_key = {(item["metric"], item["stratum"]): item for item in proposal.metrics}
    assert ("Recall@10", "all") in rows_by_key
    assert rows_by_key[("Recall@10", "all")]["observed"] == pytest.approx(0.8)
    assert rows_by_key[("Recall@10", "all")]["denominator"] == 2
    assert rows_by_key[("Recall@10", "all")]["denominator_basis"] == "gold_cases_non_ocr"
    suggested = rows_by_key[("Recall@10", "all")]["suggested"]
    assert suggested["absolute_min"] == pytest.approx(0.78)
    assert suggested["max_regression_pp"] == pytest.approx(2.0)
    assert suggested["min_sample"] == 2
    runtime = rows_by_key[("p95_latency_ms", "all")]
    assert runtime["observed"] == 10
    assert runtime["suggested"]["absolute_max"] is None
    assert runtime["suggested"]["max_regression_pp"] is None

    target = tmp_path / "gate_proposal.json"
    written = write_gate_proposal(proposal, target)
    assert written == target
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["gate_config_hash"] == config.config_hash
    assert payload["run_id"] == run.manifest.run_id
    assert payload["status"] == "unapproved"
    assert Path(config.source_path).read_bytes() == before


def test_calibrate_proposal_suggestion_rule_is_documented(tmp_path: Path) -> None:
    case = make_case("N01", suite="badcase", stratum="price", expected_values=(),
                     expected_sources=())
    rows = [make_row(case, metrics={**DEFAULT_ROW_METRICS, "false_refusal_rate": 0.0})]
    run = build_run(
        tmp_path,
        cases=[case],
        rows=rows,
        summary=summarize([case], rows),
        manifest=make_manifest(suite="badcase"),
    )
    config = make_config(
        tmp_path,
        metrics=[
            metric_spec("false_refusal_rate", "refusal", "lower_is_better", min_sample=None)
        ],
    )
    proposal = calibrate_gate(run, config)
    row = next(item for item in proposal.metrics
               if item["metric"] == "false_refusal_rate" and item["stratum"] == "all")
    assert row["suggested"]["absolute_max"] == pytest.approx(0.02)
    assert row["suggested"]["absolute_min"] is None
    assert row["suggested"]["max_regression_pp"] == pytest.approx(2.0)
    assert row["rationale"]


def test_write_gate_proposal_refuses_to_overwrite_gate_config(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])],
                    summary=summarize(cases, [make_row(cases[0])]))
    config = make_config(tmp_path)
    proposal = calibrate_gate(run, config)
    before = DEFAULT_CONFIG_PATH.read_bytes()
    with pytest.raises(ValueError, match="gate_v0_1|配置"):
        write_gate_proposal(proposal, DEFAULT_CONFIG_PATH)
    assert DEFAULT_CONFIG_PATH.read_bytes() == before


def test_proposal_does_not_change_unapproved_evaluation(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    rows = [make_row(cases[0])]
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summarize(cases, rows))
    config = make_config(
        tmp_path,
        status="unapproved",
        metrics=[metric_spec("Recall@10", "retrieval", "higher_is_better", min_sample=None)],
    )
    calibrate_gate(run, config)
    result = evaluate_quality(run, config)
    assert result.exit_code == EXIT_UNKNOWN
    assert all(item.status in {"unknown", "not_applicable"} for item in result.quality.metrics)


# --------------------------------------------------------------------------- #
# 4. 退出码矩阵
# --------------------------------------------------------------------------- #


def test_approved_quality_pass_exit_0_with_full_trace_gate(tmp_path: Path) -> None:
    cases = [make_case("Q01"), make_case("Q02", stratum="text", expected_values=())]
    rows = [make_row(cases[0]), make_row(cases[1])]
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summarize(cases, rows))
    config = make_config(
        tmp_path,
        metrics=[metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.9)],
    )
    result = evaluate_gate(run, None, config, quality=True)  # require_trace 默认 True
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.quality.status == "pass"
    assert result.unknowns == ()
    assert not result.quality.failures


def test_quality_absolute_threshold_fail_exit_2(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    rows = [make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.6})]
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summarize(cases, rows))
    config = make_config(
        tmp_path,
        metrics=[metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.9)],
    )
    result = evaluate_quality(run, config)
    assert result.exit_code == EXIT_QUALITY_REGRESSION
    assert result.quality.status == "fail"
    assert result.quality.failures
    failure = result.quality.failures[0]
    assert failure.gate_id == "quality:Recall@10"
    assert failure.check_id == "absolute_min"
    assert failure.evidence["observed"] == pytest.approx(0.6)
    assert failure.evidence["threshold"] == pytest.approx(0.9)


def test_unapproved_thresholds_are_unknown_exit_3_not_pass(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    rows = [make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.95})]
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summarize(cases, rows))
    config = make_config(
        tmp_path,
        status="unapproved",
        metrics=[
            metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.5)
        ],
    )
    result = evaluate_quality(run, config)
    assert result.exit_code == EXIT_UNKNOWN
    assert result.exit_code != EXIT_PASS
    assert result.quality.status == "unknown"
    assert not result.quality.failures
    item = single_quality_metric(result, "Recall@10", "all")
    assert item.status == "unknown"
    assert any(check.kind == "approval" and check.status == "unknown" for check in item.checks)
    assert any(u.check_id == "thresholds_unapproved" for u in result.unknowns)


def test_quality_regression_same_pipeline_version_exit_2(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    cases = [make_case("Q01")]
    baseline_rows = [make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 1.0})]
    baseline = build_run(
        baseline_dir,
        cases=cases,
        rows=baseline_rows,
        summary=summarize(cases, baseline_rows),
        manifest=make_manifest(run_id="run-baseline"),
    )
    current_rows = [make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.95})]
    run = build_run(tmp_path, cases=cases, rows=current_rows,
                    summary=summarize(cases, current_rows),
                    manifest=make_manifest(run_id="run-current"))
    config = make_config(
        tmp_path,
        metrics=[
            metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.5,
                        max_regression_pp=1.0)
        ],
    )
    result = evaluate_quality(run, config, baseline=baseline)
    assert result.exit_code == EXIT_QUALITY_REGRESSION
    failure = next(item for item in result.quality.failures
                   if item.check_id == "max_regression_pp")
    assert failure.evidence["delta_pp"] == pytest.approx(5.0)
    assert failure.evidence["baseline_observed"] == pytest.approx(1.0)
    assert result.quality.baseline_run_id == "run-baseline"


def test_cross_pipeline_version_baseline_rejects_regression_and_is_unknown(
    tmp_path: Path,
) -> None:
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    cases = [make_case("Q01")]
    baseline_rows = [make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 1.0})]
    baseline = build_run(
        baseline_dir,
        cases=cases,
        rows=baseline_rows,
        summary=summarize(cases, baseline_rows),
        manifest=make_manifest(run_id="run-old", pipeline_version="pipeline-old"),
    )
    current_rows = [make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.95})]
    run = build_run(tmp_path, cases=cases, rows=current_rows,
                    summary=summarize(cases, current_rows))
    config = make_config(
        tmp_path,
        metrics=[
            metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.5,
                        max_regression_pp=0.1)
        ],
    )
    result = evaluate_quality(run, config, baseline=baseline)
    assert result.exit_code == EXIT_UNKNOWN
    assert not result.quality.failures
    item = single_quality_metric(result, "Recall@10", "all")
    assert item.status == "unknown"
    regression = next(check for check in item.checks if check.kind == "max_regression_pp")
    assert regression.status == "unknown"
    assert regression.detail["reason"] == "cross_pipeline_version"
    assert any(u.check_id == "cross_pipeline_version" for u in result.unknowns)


def test_without_baseline_regression_check_is_skipped_not_unknown(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    rows = [make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.95})]
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summarize(cases, rows))
    config = make_config(
        tmp_path,
        metrics=[
            metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.5,
                        max_regression_pp=1.0)
        ],
    )
    result = evaluate_quality(run, config)
    assert result.exit_code == EXIT_PASS
    item = single_quality_metric(result, "Recall@10", "all")
    regression = next(check for check in item.checks if check.kind == "max_regression_pp")
    assert regression.status == "skipped"
    assert regression.detail["reason"] == "no_baseline"


def test_hard_failure_outranks_quality_regression(tmp_path: Path) -> None:
    case = make_case("Q01")
    rows = [
        make_row(
            case,
            outcome={"citations": []},
            metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.1},
        )
    ]
    run = build_run(tmp_path, cases=[case], rows=rows, summary=summarize([case], rows))
    config = make_config(
        tmp_path,
        metrics=[metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.9)],
    )
    result = evaluate_quality(run, config)
    assert result.exit_code == EXIT_HARD_FAILURE
    assert result.hard_failures == ("citation_required",)
    assert result.quality.failures  # 质量确实失败，但退出码仍是 1


# --------------------------------------------------------------------------- #
# 5. waiver
# --------------------------------------------------------------------------- #


def _failing_config(tmp_path: Path) -> GateConfig:
    return make_config(
        tmp_path,
        metrics=[metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.9)],
    )


def _failing_run(tmp_path: Path) -> RunResult:
    cases = [make_case("Q01")]
    rows = [make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.5})]
    return build_run(tmp_path, cases=cases, rows=rows, summary=summarize(cases, rows))


def test_waiver_requires_reason_and_approver() -> None:
    with pytest.raises(ValueError, match="reason"):
        QualityWaiver(reason="", approver="lead")
    with pytest.raises(ValueError, match="approver"):
        QualityWaiver(reason="known regression", approver="  ")
    waiver = QualityWaiver(reason="known regression", approver="lead")
    assert waiver.metric is None and waiver.stratum is None


def test_hard_gate_waiver_is_rejected() -> None:
    for gate_id in HARD_GATE_IDS:
        with pytest.raises(ValueError, match="硬门禁"):
            QualityWaiver(reason="x", approver="lead", metric=gate_id)


def test_quality_waiver_recorded_in_warnings_and_report(tmp_path: Path) -> None:
    run = _failing_run(tmp_path)
    config = _failing_config(tmp_path)
    waiver = QualityWaiver(
        metric="Recall@10", stratum="all", reason="标注口径变更", approver="master"
    )
    result = evaluate_gate(
        run, None, config,
        require_trace=False,
        quality=QualityPolicy(waivers=(waiver,)),
    )
    assert result.exit_code == EXIT_QUALITY_REGRESSION
    assert result.quality.status == "fail"
    assert result.quality.waived
    entry = result.quality.waived[0]
    assert entry["metric"] == "Recall@10"
    assert entry["stratum"] == "all"
    assert entry["reason"] == "标注口径变更"
    assert entry["approver"] == "master"
    assert any("标注口径变更" in warning and "master" in warning for warning in result.warnings)
    # 只有 all 级被豁免，exact 级仍失败 → 退出码仍是 2；豁免范围精确，不外溢。
    exact_failures = [
        item for item in result.quality.failures
        if item.evidence.get("stratum") == "exact"
    ]
    assert exact_failures


def test_quality_waiver_can_cover_all_strata_of_a_metric(tmp_path: Path) -> None:
    run = _failing_run(tmp_path)
    config = _failing_config(tmp_path)
    waiver = QualityWaiver(metric="Recall@10", reason="口径变更", approver="master")
    result = evaluate_gate(
        run, None, config, require_trace=False,
        quality=QualityPolicy(waivers=(waiver,)),
    )
    assert result.exit_code == EXIT_PASS
    assert result.quality.status == "pass_with_waivers"
    assert len(result.quality.waived) == len(result.quality.metrics)
    assert any("waiver" in warning for warning in result.warnings)


def test_quality_waiver_does_not_change_hard_failure(tmp_path: Path) -> None:
    case = make_case("Q01")
    rows = [
        make_row(case, outcome={"citations": []},
                 metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.5})
    ]
    run = build_run(tmp_path, cases=[case], rows=rows, summary=summarize([case], rows))
    config = _failing_config(tmp_path)
    waiver = QualityWaiver(metric="Recall@10", reason="已知", approver="lead")
    result = evaluate_gate(
        run, None, config, require_trace=False,
        quality=QualityPolicy(waivers=(waiver,)),
    )
    assert result.exit_code == EXIT_HARD_FAILURE
    assert result.hard_failures == ("citation_required",)
    assert result.quality.waived


def test_quality_policy_validation(tmp_path: Path) -> None:
    run = _failing_run(tmp_path)
    config = _failing_config(tmp_path)
    with pytest.raises(TypeError):
        evaluate_gate(run, None, config, quality="yes")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="QualityWaiver"):
        evaluate_gate(
            run, None, config,
            quality=QualityPolicy(waivers=("not-a-waiver",)),  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------- #
# 6. 诊断字段 / 读取 baseline
# --------------------------------------------------------------------------- #


def test_value_no_fabricated_is_diagnostic_only(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    row = make_row(
        cases[0],
        checks=[{"check_id": "value_no_fabricated", "status": "fail", "evidence": {}}],
    )
    run = build_run(tmp_path, cases=cases, rows=[row], summary=summarize(cases, [row]))
    config = make_config(
        tmp_path,
        metrics=[metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.5)],
    )
    result = evaluate_quality(run, config)
    assert result.exit_code == EXIT_PASS
    diagnostics = result.quality.diagnostics["value_no_fabricated"]
    assert diagnostics["status"] == "diagnostic_only"
    assert diagnostics["fail_cases"] == ["Q01"]
    assert diagnostics["participates_in_gate"] is False
    assert all(item.metric != "value_no_fabricated" for item in result.quality.metrics)


def test_baseline_can_be_loaded_from_a_run_directory(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "baseline"
    baseline_dir.mkdir()
    cases = [make_case("Q01")]
    baseline_rows = [make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 1.0})]
    baseline = build_run(
        baseline_dir,
        cases=cases,
        rows=baseline_rows,
        summary=summarize(cases, baseline_rows),
        manifest=make_manifest(run_id="run-baseline"),
    )
    current_rows = [make_row(cases[0], metrics={**DEFAULT_ROW_METRICS, "Recall@10": 0.95})]
    run = build_run(tmp_path, cases=cases, rows=current_rows,
                    summary=summarize(cases, current_rows))
    config = make_config(
        tmp_path,
        metrics=[
            metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.5,
                        max_regression_pp=1.0)
        ],
    )
    result = evaluate_quality(run, config, baseline=baseline.out_dir)
    assert result.exit_code == EXIT_QUALITY_REGRESSION
    assert result.quality.baseline_run_id == "run-baseline"


def test_unapproved_waiver_is_not_allowed_to_fake_pass(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    rows = [make_row(cases[0])]
    run = build_run(tmp_path, cases=cases, rows=rows, summary=summarize(cases, rows))
    config = make_config(
        tmp_path,
        status="unapproved",
        metrics=[
            metric_spec("Recall@10", "retrieval", "higher_is_better", absolute_min=0.5)
        ],
    )
    waiver = QualityWaiver(metric="Recall@10", reason="x", approver="lead")
    result = evaluate_gate(
        run, None, config, require_trace=False,
        quality=QualityPolicy(waivers=(waiver,)),
    )
    assert result.exit_code == EXIT_UNKNOWN
    assert not result.quality.waived
