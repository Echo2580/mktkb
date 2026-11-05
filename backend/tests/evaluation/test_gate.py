"""T006a：Release Gate 硬门禁层测试（设计 §8.1 / §8.4；计划 Task 5 Step 1/3/5）。

覆盖 handoff §5 六条：

1. 8 项硬门禁逐项可达（构造失败样本 → 命中该 ID → ``exit_code=1``）；
2. ``trace_integrity`` 按 T003d 契约（reason-aware 必需 Span、replayed 跳过、
   ``*_json`` 非法 JSON fail closed、schema 版本不一致 fail）；
3. 不依赖内核对 ``mode=live`` 的拒绝（gate 自己判 → ``exit_code=4``）；
4. 退出码 0/1/3/4 互斥；2 保留不用；硬门禁不可豁免；
5. PM 裁决口径（``not_applicable`` vs ``unknown``；``min_sample`` 用 evaluated_count；
   ``value_no_fabricated`` 不进硬门禁；``citation_required`` 不靠 ``source_hit``；
   ``security_leak`` 按解析后 unit 映射比对；``record_code``-only gold fail closed）；
6. 配置骨架可解析且不含绝对阈值。

全部用合成 ``RunResult`` + 真实 ``TraceRepository``（tmp_path），
零真实模型 / OCR / embedding / rerank 调用，不读 ``.env``，不写 ``var/``。
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import sqlite3
from pathlib import Path

import pytest

from mktkb.evaluation import gate as gate_module
from mktkb.evaluation.dataset import CaseSpec, write_cases
from mktkb.evaluation.gate import (
    EXIT_HARD_FAILURE,
    EXIT_LIVE_UNAUTHORIZED,
    EXIT_PASS,
    EXIT_QUALITY_REGRESSION,
    EXIT_UNKNOWN,
    HARD_GATE_IDS,
    GateConfig,
    evaluate_gate,
    load_gate_config,
)
from mktkb.evaluation.runner import RunManifest, RunResult
from mktkb.observability.contracts import (
    GATE_SCHEMA_VERSION,
    TRACE_SCHEMA_VERSION,
    SpanRecord,
    TraceRecord,
)
from mktkb.observability.store import TraceRepository

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = ROOT / "docs" / "evaluation" / "gate_v0_1.json"

CHECK_IDS = (
    "value_hit",
    "value_forbidden",
    "value_no_fabricated",
    "source_hit",
    "source_forbidden",
    "kind_correct",
    "refusal_expected",
    "refusal_unexpected",
    "pagination_total",
    "pagination_returned",
    "pagination_has_more",
    "pagination_next_page",
)
PAGINATION_CHECK_IDS = CHECK_IDS[-4:]

UNIT_KEY = "sheet:A:row:8"
UNIT_ID = "D01-0"


# --------------------------------------------------------------------------- #
# 合成产物 helper（manifest / 数据集 / cases 行 / trace）
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


def make_checks(**overrides) -> list[dict]:
    statuses = {check_id: "pass" for check_id in CHECK_IDS}
    for check_id in PAGINATION_CHECK_IDS:
        statuses[check_id] = "skipped"
    statuses.update(overrides)
    return [
        {"check_id": check_id, "status": statuses[check_id], "evidence": {}}
        for check_id in CHECK_IDS
    ]


def make_citation(**overrides) -> dict:
    payload = {
        "doc_code": "D01",
        "unit_key": UNIT_KEY,
        "unit_ids": [UNIT_ID],
        "locator": {},
        "text": "P01 位于 A 区 8 号",
        "kind": "table_row",
    }
    payload.update(overrides)
    return payload


def make_retrieved(**overrides) -> dict:
    payload = {
        "doc_code": "D01",
        "unit_ids": [UNIT_ID],
        "unit_key": UNIT_KEY,
        "locator": {},
        "chunk_id": "chunk-1",
        "hard_filter_violation": None,
    }
    payload.update(overrides)
    return payload


def make_row(case: CaseSpec, **overrides) -> dict:
    """构造与 ``runner`` 相同形状的 ``cases.jsonl`` 行（gate 的唯一运行输入）。"""
    outcome = {
        "kind": "answer",
        "text": "P01 位于 A 区 8 号",
        "path": "rag",
        "trace_id": f"trace-{case.case_id}",
        "pagination": {},
        "citations": [make_citation()],
        "facts": [],
        "retrieved": [make_retrieved()],
    }
    row = {
        "case_id": case.case_id,
        "suite": case.suite,
        "status": "pass",
        "trace_id": f"trace-{case.case_id}",
        "previous_trace_id": None,
        "replayed": False,
        "checks": make_checks(),
        "metrics": {},
        "refused": False,
        "should_refuse": bool(case.should_refuse),
        "path": "rag",
        "latency_ms": 1,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_cny": 0.0,
        "duration_ms": 1,
        "turns_executed": 1,
        "multi_turn_claimed": False,
        "outcome": outcome,
        "gold": {
            "case_id": case.case_id,
            "requires_ocr": False,
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
        elif key == "checks":
            row["checks"] = value
        elif key == "pagination":
            outcome = {**outcome, "pagination": value}
        else:
            row[key] = value
    row["outcome"] = outcome
    return row


def write_trace(
    repo: TraceRepository,
    manifest: RunManifest,
    case_id: str,
    *,
    spans: tuple[str, ...] = ("parse", "recall", "fuse", "answer", "commit"),
    path: str | None = "rag",
    outcome: str | None = "answer",
    reason: str | None = None,
    replayed: bool = False,
    trace_status: str | None = None,
    annotate_identity: bool = True,
    trace_id: str | None = None,
    **overrides,
) -> str:
    """直接写一条可控 Trace（gate 把 trace 当不可信输入，测试要能构造任何形态）。"""
    resolved_id = trace_id or f"trace-{case_id}"
    fields = {
        "trace_id": resolved_id,
        "request_id": None,
        "http_request_id": f"{manifest.run_id}:{case_id}",
        "mode": manifest.mode,
        "scope": manifest.scope,
        "path": path,
        "case_id": case_id,
        "replayed": replayed,
        "outcome_kind": outcome,
        "reason": reason,
        "latency_ms": 1,
        "status": trace_status or ("replayed" if replayed else "ok"),
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
    span_records = [
        SpanRecord(span_id=f"{resolved_id}-{name}", trace_id=resolved_id, name=name, status="ok")
        for name in dict.fromkeys(spans)
    ]
    repo.write(record, span_records)
    return resolved_id


def build_run(
    tmp_path: Path,
    *,
    cases: list[CaseSpec],
    rows: list[dict],
    trace_specs: dict[str, dict] | None = None,
    manifest: RunManifest | None = None,
    summary: dict | None = None,
) -> RunResult:
    """写出三件套 + traces.sqlite3，返回与 ``run_suite`` 同形的 ``RunResult``。"""
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = tmp_path / "dataset.jsonl"
    write_cases(dataset_path, cases)
    base = manifest or make_manifest(suite=cases[0].suite if cases else "b0")
    manifest = dataclasses.replace(
        base, dataset_path=str(dataset_path), case_count=len(cases)
    )

    repo = TraceRepository(run_dir / "traces.sqlite3")
    try:
        if trace_specs is None:
            trace_specs = {
                case.case_id: {}
                for case in cases
                if not any(
                    row["case_id"] == case.case_id
                    and (row.get("status") == "skipped_requires_ocr" or row.get("error"))
                    for row in rows
                )
            }
        for case_id, spec in trace_specs.items():
            if spec is None:
                continue
            write_trace(repo, manifest, case_id, **spec)
    finally:
        repo.close()

    _write_json(run_dir / "run_manifest.json", manifest.to_dict())
    (run_dir / "cases.jsonl").write_bytes(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ).encode("utf-8")
    )
    _write_json(
        run_dir / "summary.json",
        summary
        if summary is not None
        else {
            "suite": manifest.suite,
            "scored_count": sum(
                1 for row in rows if row.get("status") in {"pass", "fail"}
            ),
        },
    )
    return RunResult(
        manifest=manifest,
        out_dir=run_dir,
        cases=tuple(rows),
        summary=summary or {},
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_bytes(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    )


def config_payload(**overrides) -> dict:
    payload = {
        "schema_version": "mktkb.gate.config.v0.1",
        "gate_version": GATE_SCHEMA_VERSION,
        "status": "unapproved",
        "hard_gates": list(HARD_GATE_IDS),
        "hard_gate_min_sample": {"b0": 1, "badcase": 1},
        "sensitive_patterns": [],
        "metrics": [
            {
                "name": "Recall@10",
                "group": "retrieval",
                "direction": "higher_is_better",
            }
        ],
        "notes": "T006a 测试配置",
    }
    payload.update(overrides)
    return payload


def make_config(tmp_path: Path, **overrides) -> GateConfig:
    path = tmp_path / "gate_config.json"
    _write_json(path, config_payload(**overrides))
    return load_gate_config(path)


def evaluate(run: RunResult, config: GateConfig, **kwargs):
    return evaluate_gate(run, None, config, **kwargs)


# --------------------------------------------------------------------------- #
# 触发器矩阵：8 项硬门禁逐项可达
# --------------------------------------------------------------------------- #


def _hard_failure_inputs(tmp_path: Path, kind: str):
    """为每个门禁构造一份"只看该门禁失败"的样本；其余门禁全绿或 not_applicable。"""
    if kind == "security_leak":
        case = make_case(stratum="text", expected_values=(), forbidden_values=("机密",))
        rows = [make_row(case, outcome={"text": "这是机密资料"})]
        traces = None
    elif kind == "cross_entity":
        case = make_case()
        rows = [
            make_row(
                case,
                outcome={"retrieved": [make_retrieved(hard_filter_violation="cross_entity")]},
            )
        ]
        traces = None
    elif kind == "stale_bypass":
        case = make_case()
        rows = [
            make_row(
                case,
                outcome={"retrieved": [make_retrieved(hard_filter_violation="stale")]},
            )
        ]
        traces = None
    elif kind == "conflict_not_rejected":
        case = make_case(
            expected_kind="conflict",
            expected_values=(),
            stratum="text",
            expected_sources=(),
        )
        rows = [make_row(case, outcome={"kind": "answer"})]
        traces = {"Q01": {"outcome": "answer"}}
    elif kind == "exact_value_contract":
        case = make_case()
        rows = [make_row(case, outcome={"text": "A 区 8 号有相关记录"})]
        traces = None
    elif kind == "pagination_contract":
        case = make_case(expected_pagination={"total": 2}, expected_values=())
        rows = [
            make_row(
                case,
                pagination={"total": 1, "returned": 1, "has_more": False, "next_page": None},
            )
        ]
        traces = None
    elif kind == "citation_required":
        case = make_case()
        rows = [make_row(case, outcome={"citations": []})]
        traces = None
    elif kind == "trace_integrity":
        case = make_case()
        rows = [make_row(case)]
        traces = {}
    else:  # pragma: no cover - 参数化列表固定
        raise AssertionError(kind)
    config = make_config(tmp_path)
    return build_run(tmp_path, cases=[case], rows=rows, trace_specs=traces), config


@pytest.mark.parametrize("kind", list(HARD_GATE_IDS))
def test_hard_gate_trigger_matrix(tmp_path: Path, kind: str) -> None:
    run, config = _hard_failure_inputs(tmp_path, kind)
    result = evaluate(run, config)
    assert result.exit_code == EXIT_HARD_FAILURE, (kind, result.to_dict())
    assert kind in result.hard_failures, (kind, result.hard_failures)
    assert result.gate_status[kind] == "fail"
    detail = [item for item in result.failures if item.gate_id == kind]
    assert detail, kind
    for item in detail:
        assert item.case_id == "Q01"
        assert item.check_id
        assert isinstance(item.evidence, dict) and item.evidence
    # 其余门禁不得因为该样本被误判为失败
    assert set(result.hard_failures) == {kind}, result.hard_failures


# --------------------------------------------------------------------------- #
# 配置骨架
# --------------------------------------------------------------------------- #


def test_default_gate_config_is_hard_skeleton_only() -> None:
    config = load_gate_config(DEFAULT_CONFIG_PATH)
    assert config.gate_version == GATE_SCHEMA_VERSION
    assert tuple(config.hard_gates) == HARD_GATE_IDS
    assert dict(config.hard_gate_min_sample) == {"b0": 32, "badcase": 13}
    assert config.min_sample is config.hard_gate_min_sample
    assert config.status == "unapproved"
    assert config.metrics, "指标骨架（名称 + 方向）必须存在"
    for metric in config.metrics:
        assert metric.direction in {"higher_is_better", "lower_is_better"}
        # 初版只放空阈值占位：绝对阈值由 T006b 的 --calibrate + 主人审批后填入
        assert metric.absolute_min is None
        assert metric.absolute_max is None
        assert metric.max_regression_pp is None
    assert len(config.config_hash) == 64


def test_load_gate_config_rejects_unknown_hard_gate(tmp_path: Path) -> None:
    payload = config_payload(hard_gates=[*HARD_GATE_IDS[:-1], "quality_regression"])
    path = tmp_path / "bad.json"
    _write_json(path, payload)
    with pytest.raises(ValueError, match="hard_gates"):
        load_gate_config(path)


def test_load_gate_config_requires_all_eight_hard_gates(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    _write_json(path, config_payload(hard_gates=list(HARD_GATE_IDS[:-1])))
    with pytest.raises(ValueError, match="hard_gates"):
        load_gate_config(path)


def test_load_gate_config_rejects_bad_metric_direction(tmp_path: Path) -> None:
    payload = config_payload(
        metrics=[{"name": "Recall@10", "group": "retrieval", "direction": "up"}]
    )
    path = tmp_path / "bad.json"
    _write_json(path, payload)
    with pytest.raises(ValueError, match="direction"):
        load_gate_config(path)


def test_load_gate_config_rejects_bad_min_sample(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    _write_json(path, config_payload(hard_gate_min_sample={"b0": 0}))
    with pytest.raises(ValueError, match="hard_gate_min_sample"):
        load_gate_config(path)


def test_load_gate_config_rejects_legacy_min_sample_key(tmp_path: Path) -> None:
    """JSON 字段必须是 ``hard_gate_min_sample``；旧 ``min_sample`` 不再被静默接受。"""
    payload = config_payload()
    payload["min_sample"] = payload.pop("hard_gate_min_sample")
    path = tmp_path / "legacy.json"
    _write_json(path, payload)
    with pytest.raises(ValueError, match="hard_gate_min_sample"):
        load_gate_config(path)


def test_load_gate_config_rejects_bad_sensitive_pattern(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    _write_json(path, config_payload(sensitive_patterns=["(unclosed"]))
    with pytest.raises(ValueError, match="sensitive_patterns"):
        load_gate_config(path)


def test_load_gate_config_rejects_gate_version_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    _write_json(path, config_payload(gate_version="mktkb.gate.v9.9"))
    with pytest.raises(ValueError, match="gate_version"):
        load_gate_config(path)


# --------------------------------------------------------------------------- #
# 干净集 / 退出码 0
# --------------------------------------------------------------------------- #


def test_clean_run_exits_zero(tmp_path: Path) -> None:
    cases = [make_case("Q01"), make_case("Q02")]
    rows = [make_row(cases[0]), make_row(cases[1])]
    run = build_run(tmp_path, cases=cases, rows=rows)
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.hard_failures == ()
    assert result.unknowns == ()
    assert result.scored_count == 2
    for gate_id in HARD_GATE_IDS:
        assert result.gate_status[gate_id] in {"pass", "not_applicable"}
    # PM 裁决：数据集没有该类 case → not_applicable，不进退出码
    assert result.gate_status["conflict_not_rejected"] == "not_applicable"
    assert result.gate_status["security_leak"] == "not_applicable"
    assert result.gate_status["cross_entity"] == "not_applicable"
    assert result.gate_status["stale_bypass"] == "not_applicable"
    assert {item.gate_id for item in result.not_applicable} >= {
        "security_leak",
        "cross_entity",
        "stale_bypass",
        "conflict_not_rejected",
    }


def test_exit_code_2_is_reserved_and_never_returned(tmp_path: Path) -> None:
    assert EXIT_QUALITY_REGRESSION == 2
    assert sorted({EXIT_PASS, EXIT_HARD_FAILURE, 2, EXIT_UNKNOWN, EXIT_LIVE_UNAUTHORIZED}) == [
        0,
        1,
        2,
        3,
        4,
    ]
    seen = set()
    for kind in HARD_GATE_IDS:
        case_dir = tmp_path / f"case-{kind}"
        case_dir.mkdir()
        run, config = _hard_failure_inputs(case_dir, kind)
        seen.add(evaluate(run, config).exit_code)
    assert 2 not in seen
    assert seen == {EXIT_HARD_FAILURE}


def test_baseline_argument_is_ignored_with_warning(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    result = evaluate_gate(run, object(), make_config(tmp_path))
    assert result.exit_code == EXIT_PASS
    assert any("baseline" in warning for warning in result.warnings)


def test_require_trace_false_skips_trace_gate(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])], trace_specs={})
    result = evaluate(run, make_config(tmp_path), require_trace=False)
    assert result.exit_code == EXIT_PASS
    assert result.gate_status["trace_integrity"] == "not_applicable"


# --------------------------------------------------------------------------- #
# security_leak
# --------------------------------------------------------------------------- #


def test_security_leak_forbidden_source_matched_at_unit_level(tmp_path: Path) -> None:
    """引用只带 unit_ids、forbidden 用 unit_key：必须按解析后的 unit 映射比对（T004b M-4）。"""
    forbidden = {"doc_code": "D01", "unit_key": UNIT_KEY}
    case = make_case(expected_sources=(), forbidden_sources=(forbidden,))
    citation = make_citation(unit_key=None, unit_ids=[UNIT_ID])
    row = make_row(
        case,
        outcome={"citations": [citation]},
        gold={
            "case_id": "Q01",
            "requires_ocr": False,
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
    )
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    assert "security_leak" in result.hard_failures
    failure = next(item for item in result.failures if item.gate_id == "security_leak")
    assert failure.check_id == "forbidden_source_citation"
    assert failure.evidence["forbidden_index"] == 0
    assert UNIT_ID in failure.evidence["citation_unit_ids"]


def test_security_leak_sensitive_pattern_from_config(tmp_path: Path) -> None:
    case = make_case(stratum="text", expected_values=(), forbidden_values=("机密",))
    rows = [make_row(case, outcome={"text": "手机号 13800138000"})]
    run = build_run(tmp_path, cases=[case], rows=rows)
    config = make_config(tmp_path, sensitive_patterns=[r"1[3-9]\d{9}"])
    result = evaluate(run, config)
    assert result.exit_code == EXIT_HARD_FAILURE
    assert result.hard_failures == ("security_leak",)
    failure = next(item for item in result.failures if item.gate_id == "security_leak")
    assert failure.check_id == "sensitive_pattern"


def test_security_leak_unresolvable_record_code_ref_is_unknown(tmp_path: Path) -> None:
    """无法解析的 forbidden 引用 → unknown → exit 3（不得默认通过）。"""
    case = make_case(
        expected_sources=(), forbidden_sources=({"doc_code": "D01", "record_code": "P01"},)
    )
    run = build_run(tmp_path, cases=[case], rows=[make_row(case)])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN, result.to_dict()
    unknown = next(item for item in result.unknowns if item.gate_id == "security_leak")
    assert unknown.check_id == "forbidden_ref_unresolved"
    assert unknown.case_id == "Q01"


def test_security_leak_forbidden_document_ref_matches_any_citation(tmp_path: Path) -> None:
    """doc_code-only 的 forbidden 引用 = 整篇禁用：同文档任何引用都算泄漏（fail closed）。"""
    case = make_case(
        stratum="text",
        expected_values=(),
        expected_sources=(),
        forbidden_sources=({"doc_code": "D01"},),
    )
    run = build_run(tmp_path, cases=[case], rows=[make_row(case)])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "security_leak")
    assert failure.evidence["matched_by"] == "document"


def test_security_leak_forbidden_locator_matches_citation_locator(tmp_path: Path) -> None:
    case = make_case(
        stratum="text",
        expected_values=(),
        expected_sources=(),
        forbidden_sources=({"doc_code": "D01", "locator": {"row": 8}},),
    )
    citation = make_citation(locator={"row": 8, "sheet": "A"})
    row = make_row(case, outcome={"citations": [citation]})
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "security_leak")
    assert failure.evidence["matched_by"] == "locator"


def test_security_leak_not_applicable_without_forbidden_refs(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    result = evaluate(run, make_config(tmp_path))
    note = next(item for item in result.not_applicable if item.gate_id == "security_leak")
    assert note.applicable_cases == 0
    assert "forbidden" in note.detail


def test_security_leak_missing_outcome_with_forbidden_values_is_unknown(
    tmp_path: Path,
) -> None:
    """R1-HIGH-1：有 forbidden 约束但 outcome 缺失 → unknown(3)，不得把缺失当空文本。"""
    case = make_case(
        stratum="text",
        expected_values=(),
        expected_sources=(),
        expected_kind="no_answer",
        should_refuse=True,
        refusal_reason="no_data",
        forbidden_values=("SECRET",),
    )
    row = make_row(case, outcome=None)
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN, result.to_dict()
    assert result.gate_status["security_leak"] == "unknown"
    unknown = next(item for item in result.unknowns if item.gate_id == "security_leak")
    assert unknown.check_id == "outcome_missing"
    assert unknown.case_id == "Q01"
    assert result.failures == ()


# --------------------------------------------------------------------------- #
# cross_entity / stale_bypass
# --------------------------------------------------------------------------- #


def test_cross_entity_not_applicable_without_case_class(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    result = evaluate(run, make_config(tmp_path))
    note = next(item for item in result.not_applicable if item.gate_id == "cross_entity")
    assert "entity" in note.detail
    assert result.exit_code == EXIT_PASS


def test_stale_bypass_not_applicable_without_case_class(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    result = evaluate(run, make_config(tmp_path))
    note = next(item for item in result.not_applicable if item.gate_id == "stale_bypass")
    assert "as_of" in note.detail or "effective" in note.detail
    assert result.exit_code == EXIT_PASS


# --------------------------------------------------------------------------- #
# conflict_not_rejected
# --------------------------------------------------------------------------- #


def test_conflict_rejected_by_clarification_passes(tmp_path: Path) -> None:
    case = make_case(
        expected_kind="conflict", expected_values=(), stratum="text", expected_sources=()
    )
    row = make_row(case, outcome={"kind": "clarification", "citations": []})
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[row],
        trace_specs={"Q01": {"outcome": "clarification", "spans": ("parse", "commit")}},
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.gate_status["conflict_not_rejected"] == "pass"


def test_conflict_not_applicable_without_conflict_case(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    result = evaluate(run, make_config(tmp_path))
    note = next(
        item for item in result.not_applicable if item.gate_id == "conflict_not_rejected"
    )
    assert note.applicable_cases == 0


# --------------------------------------------------------------------------- #
# exact_value_contract / value_no_fabricated
# --------------------------------------------------------------------------- #


def test_exact_value_contract_ignores_text_stratum(tmp_path: Path) -> None:
    """Q25/Q26 属 text stratum：value_hit 未命中是质量指标，不是硬门禁。"""
    case = make_case(stratum="text")
    row = make_row(case, checks=make_checks(value_hit="fail"))
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.gate_status["exact_value_contract"] == "not_applicable"


def test_value_no_fabricated_failure_is_not_a_hard_gate(tmp_path: Path) -> None:
    case = make_case(stratum="text", expected_values=())
    row = make_row(case, checks=make_checks(value_no_fabricated="fail"))
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.hard_failures == ()


# --------------------------------------------------------------------------- #
# pagination_contract
# --------------------------------------------------------------------------- #


def test_pagination_self_consistent_output_passes_with_warning(tmp_path: Path) -> None:
    """N05 形态：无期望值、有分页输出 → 只校契约自洽，并显式声明未覆盖期望口径。"""
    case = make_case(stratum="text", expected_values=(), expected_sources=())
    row = make_row(
        case,
        pagination={"total": 1, "returned": 1, "has_more": False, "next_page": None},
        checks=make_checks(
            pagination_total="pass",
            pagination_returned="pass",
            pagination_has_more="pass",
            pagination_next_page="pass",
        ),
    )
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.gate_status["pagination_contract"] == "pass"
    assert any("分页" in warning for warning in result.warnings)


def test_pagination_not_applicable_without_expected_or_output(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    result = evaluate(run, make_config(tmp_path))
    assert result.gate_status["pagination_contract"] == "not_applicable"


def test_pagination_malformed_output_is_unknown(tmp_path: Path) -> None:
    """R1-MEDIUM-2：outcome.pagination 非 mapping → unknown(3)，不得抛未捕获异常。"""
    case = make_case(expected_pagination={"total": 2}, expected_values=())
    row = make_row(case, pagination="not-a-mapping")
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN, result.to_dict()
    assert result.gate_status["pagination_contract"] == "unknown"
    unknown = next(item for item in result.unknowns if item.gate_id == "pagination_contract")
    assert unknown.check_id == "pagination_invalid"
    assert unknown.case_id == "Q01"


# --------------------------------------------------------------------------- #
# citation_required
# --------------------------------------------------------------------------- #


def test_citation_required_not_satisfied_by_source_hit(tmp_path: Path) -> None:
    """source_hit 通过不等于有引用：必须看 unit 级 citations。"""
    case = make_case()
    row = make_row(case, outcome={"citations": []})
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "citation_required")
    assert failure.check_id == "citation_missing"


def test_citation_required_citation_outside_evidence_fails(tmp_path: Path) -> None:
    case = make_case()
    row = make_row(
        case,
        outcome={
            "citations": [make_citation(unit_ids=["D01-9"])],
            "retrieved": [make_retrieved(unit_ids=[UNIT_ID])],
        },
    )
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "citation_required")
    assert failure.check_id == "citation_not_in_evidence"
    assert "D01-9" in failure.evidence["unit_ids"]


def test_citation_required_needs_unit_level_citation(tmp_path: Path) -> None:
    """引用必须带 unit_ids（unit 级）；只有 doc_code 的引用不得当通过。"""
    case = make_case()
    row = make_row(case, outcome={"citations": [make_citation(unit_ids=[])]})
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "citation_required")
    assert failure.check_id == "citation_not_unit_level"


def test_citation_required_non_answer_outcome_not_applicable(tmp_path: Path) -> None:
    case = make_case(
        expected_kind="no_answer",
        expected_values=(),
        expected_sources=(),
        stratum="text",
        should_refuse=True,
        refusal_reason="no_data",
    )
    row = make_row(case, outcome={"kind": "no_answer", "citations": [], "retrieved": []})
    row["status"] = "pass"
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[row],
        trace_specs={
            "Q01": {
                "outcome": "no_answer",
                "reason": "NO_RECORD_FOR_ENTITY",
                "spans": ("parse", "recall", "fuse", "commit"),
            }
        },
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.gate_status["citation_required"] == "not_applicable"


def test_citation_required_missing_kind_for_answer_is_unknown(tmp_path: Path) -> None:
    """R1-HIGH-2：期望作答但缺 outcome.kind → unknown(3)，不得按非作答跳过。"""
    case = make_case()
    row = make_row(case, outcome={"kind": None, "citations": []})
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN, result.to_dict()
    assert result.gate_status["citation_required"] == "unknown"
    unknown = next(item for item in result.unknowns if item.gate_id == "citation_required")
    assert unknown.check_id == "outcome_kind_missing"
    assert unknown.case_id == "Q01"
    assert result.failures == ()


# --------------------------------------------------------------------------- #
# trace_integrity
# --------------------------------------------------------------------------- #


def test_trace_integrity_missing_trace_fails(tmp_path: Path) -> None:
    case = make_case()
    run = build_run(tmp_path, cases=[case], rows=[make_row(case)], trace_specs={})
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "trace_integrity")
    assert failure.check_id == "trace_missing"


def test_trace_integrity_missing_required_span_fails(tmp_path: Path) -> None:
    case = make_case()
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[make_row(case)],
        trace_specs={"Q01": {"spans": ("parse", "commit")}},
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "trace_integrity")
    assert failure.check_id == "required_spans_missing"
    assert set(failure.evidence["missing"]) == {"recall", "fuse", "answer"}


def test_trace_integrity_reason_aware_spans_pass(tmp_path: Path) -> None:
    """rag + no_answer + reason=UNKNOWN_STORE → 必需集退化为 parse + commit（T003d §6.1.1）。"""
    case = make_case(
        expected_kind="no_answer",
        expected_values=(),
        expected_sources=(),
        stratum="text",
        should_refuse=True,
        refusal_reason="no_data",
    )
    row = make_row(case, outcome={"kind": "no_answer", "citations": [], "retrieved": []})
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[row],
        trace_specs={
            "Q01": {
                "outcome": "no_answer",
                "reason": "UNKNOWN_STORE",
                "spans": ("parse", "commit"),
            }
        },
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.gate_status["trace_integrity"] == "pass"


def test_trace_integrity_unknown_reason_requires_retrieval_spans(tmp_path: Path) -> None:
    """reason 缺省时仍按原表要求 recall/fuse（fail safe，不放宽）。"""
    case = make_case(
        expected_kind="no_answer",
        expected_values=(),
        expected_sources=(),
        stratum="text",
        should_refuse=True,
        refusal_reason="no_data",
    )
    row = make_row(case, outcome={"kind": "no_answer", "citations": [], "retrieved": []})
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[row],
        trace_specs={"Q01": {"outcome": "no_answer", "spans": ("parse", "commit")}},
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "trace_integrity")
    assert set(failure.evidence["missing"]) == {"recall", "fuse"}


def test_trace_integrity_replayed_skips_path_outcome_and_spans(tmp_path: Path) -> None:
    """replayed 记录只校版本绑定与 JSON 结构，不按产品路径 Span 校验（T003a/T003d 遗留）。"""
    case = make_case()
    row = make_row(case, replayed=True)
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[row],
        trace_specs={"Q01": {"replayed": True, "path": None, "outcome": None, "spans": ()}},
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.gate_status["trace_integrity"] == "pass"


def test_trace_integrity_replayed_still_checks_invalid_json(tmp_path: Path) -> None:
    case = make_case()
    row = make_row(case, replayed=True)
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[row],
        trace_specs={
            "Q01": {
                "replayed": True,
                "path": None,
                "outcome": None,
                "spans": (),
                "pagination_json": "{not-json",
            }
        },
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "trace_integrity")
    assert failure.check_id == "json_invalid"
    assert failure.evidence["fields"] == ["pagination_json"]


def test_trace_integrity_replayed_still_checks_version_binding(tmp_path: Path) -> None:
    case = make_case()
    row = make_row(case, replayed=True)
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[row],
        trace_specs={
            "Q01": {
                "replayed": True,
                "path": None,
                "outcome": None,
                "spans": (),
                "dataset_version": "b0:dev-1:tampered0000",
            }
        },
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "trace_integrity")
    assert failure.check_id == "version_binding"
    assert "dataset_version" in failure.evidence["mismatched"]


def test_trace_integrity_invalid_json_fails_closed(tmp_path: Path) -> None:
    """``*_json`` 非法 JSON → fail closed（不抛异常、不 fail-open）。"""
    case = make_case()
    row = make_row(case)
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[row],
        trace_specs={"Q01": {"citation_refs_json": "[]x"}},
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "trace_integrity")
    assert failure.check_id == "json_invalid"


def test_trace_integrity_schema_version_mismatch_fails(tmp_path: Path) -> None:
    case = make_case()
    row = make_row(case)
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[row],
        trace_specs={"Q01": {"trace_schema_version": "mktkb.trace.v9.9"}},
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "trace_integrity")
    assert failure.check_id == "schema_version_mismatch"
    assert failure.evidence["expected"] == TRACE_SCHEMA_VERSION


def test_trace_integrity_store_schema_meta_mismatch_fails(tmp_path: Path) -> None:
    """R1-HIGH-3：schema_meta.trace_schema_version 漂移 → exit 1（TraceRecord 仍是 v0.1）。"""
    case = make_case()
    run = build_run(tmp_path, cases=[case], rows=[make_row(case)])
    database = run.out_dir / "traces.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE schema_meta SET value = ? WHERE key = ?",
            ("mktkb.trace.v9.9", "trace_schema_version"),
        )
        connection.commit()
    finally:
        connection.close()

    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE, result.to_dict()
    assert result.hard_failures == ("trace_integrity",)
    failure = next(item for item in result.failures if item.gate_id == "trace_integrity")
    assert failure.check_id == "store_schema_version_mismatch"
    assert failure.case_id is None
    assert failure.evidence["expected"] == TRACE_SCHEMA_VERSION
    assert failure.evidence["actual"] == "mktkb.trace.v9.9"
    assert failure.evidence["source"] == "schema_meta.trace_schema_version"


def test_trace_integrity_missing_schema_meta_is_unknown(tmp_path: Path) -> None:
    """R1-HIGH-3：schema_meta 表缺失/不可读 → unknown(3)，不得默认通过。"""
    case = make_case()
    run = build_run(tmp_path, cases=[case], rows=[make_row(case)])
    database = run.out_dir / "traces.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("DROP TABLE schema_meta")
        connection.commit()
    finally:
        connection.close()

    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN, result.to_dict()
    assert result.gate_status["trace_integrity"] == "unknown"
    unknown = next(item for item in result.unknowns if item.gate_id == "trace_integrity")
    assert unknown.check_id == "trace_store_unreadable"


def test_trace_integrity_conditional_span_required(tmp_path: Path) -> None:
    case = make_case()
    row = make_row(case)
    flags = json.dumps({"vector_enabled": True})
    missing_run = build_run(
        tmp_path / "a",
        cases=[case],
        rows=[row],
        trace_specs={"Q01": {"filter_decisions_json": flags}},
    )
    result = evaluate(missing_run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "trace_integrity")
    assert failure.evidence["missing"] == ["vector_recall"]

    ok_run = build_run(
        tmp_path / "b",
        cases=[case],
        rows=[row],
        trace_specs={
            "Q01": {
                "filter_decisions_json": flags,
                "spans": ("parse", "recall", "fuse", "answer", "commit", "vector_recall"),
            }
        },
    )
    assert evaluate(ok_run, make_config(tmp_path)).exit_code == EXIT_PASS


def test_trace_integrity_missing_path_or_outcome_fails(tmp_path: Path) -> None:
    case = make_case()
    row = make_row(case)
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[row],
        trace_specs={"Q01": {"path": None, "outcome": None, "trace_status": "incomplete"}},
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in result.failures if item.gate_id == "trace_integrity")
    assert failure.check_id == "path_outcome_missing"


def test_trace_integrity_legacy_path_uses_legacy_span_table(tmp_path: Path) -> None:
    """legacy 路径按 legacy 表校验（path-aware，不套用 rag 的 parse/recall/fuse）。"""
    case = make_case(stratum="text", expected_values=(), expected_sources=())
    trace_spec = {
        "path": "legacy",
        "outcome": "answer",
        "spans": ("intent_parse", "retrieve", "model_answer", "answer_validate", "commit"),
    }
    run = build_run(
        tmp_path, cases=[case], rows=[make_row(case)], trace_specs={"Q01": trace_spec}
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.gate_status["trace_integrity"] == "pass"

    wrong_run = build_run(
        tmp_path / "wrong",
        cases=[case],
        rows=[make_row(case)],
        trace_specs={
            "Q01": {
                "path": "legacy",
                "outcome": "answer",
                "spans": ("parse", "recall", "fuse", "answer", "commit"),
            }
        },
    )
    wrong = evaluate(wrong_run, make_config(tmp_path))
    assert wrong.exit_code == EXIT_HARD_FAILURE
    failure = next(item for item in wrong.failures if item.gate_id == "trace_integrity")
    assert set(failure.evidence["missing"]) == {
        "intent_parse",
        "retrieve",
        "model_answer",
        "answer_validate",
    }


def test_trace_integrity_replayed_status_without_flag_skips_spans(tmp_path: Path) -> None:
    """``status=replayed``（即使 replayed 布尔未置位）也按重放口径跳过 Span 校验。"""
    case = make_case()
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[make_row(case, replayed=True)],
        trace_specs={
            "Q01": {
                "replayed": False,
                "trace_status": "replayed",
                "path": None,
                "outcome": None,
                "spans": (),
            }
        },
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.gate_status["trace_integrity"] == "pass"


def test_trace_integrity_trace_store_missing_is_unknown(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    (run.out_dir / "traces.sqlite3").unlink()
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN, result.to_dict()
    unknown = next(item for item in result.unknowns if item.gate_id == "trace_integrity")
    assert unknown.check_id == "trace_store_unreadable"


def test_trace_integrity_trace_store_schema_mismatch_is_unknown(tmp_path: Path) -> None:
    """trace 库列与 TraceRecord 不一致 → unknown（不得用默认值冒充 schema 版本）。"""
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])], trace_specs={})
    database = run.out_dir / "traces.sqlite3"
    database.unlink()
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE traces (trace_id TEXT)")
        connection.execute("CREATE TABLE spans (name TEXT)")
        connection.commit()
    finally:
        connection.close()
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN, result.to_dict()
    assert any(
        item.check_id == "trace_store_unreadable" for item in result.unknowns
    )


# --------------------------------------------------------------------------- #
# gold 形态（record_code 不是解析键）
# --------------------------------------------------------------------------- #


def test_record_code_only_gold_is_unknown(tmp_path: Path) -> None:
    case = make_case(expected_sources=({"doc_code": "D01", "record_code": "P01"},))
    run = build_run(tmp_path, cases=[case], rows=[make_row(case)])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN, result.to_dict()
    unknown = next(item for item in result.unknowns if item.gate_id == "gold")
    assert unknown.check_id == "record_code_only_gold"


def test_record_code_with_empty_locator_is_unknown(tmp_path: Path) -> None:
    case = make_case(
        expected_sources=({"doc_code": "D01", "record_code": "P01", "locator": {}},)
    )
    run = build_run(tmp_path, cases=[case], rows=[make_row(case)])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN, result.to_dict()
    unknown = next(item for item in result.unknowns if item.gate_id == "gold")
    assert unknown.check_id == "record_code_empty_locator"


def test_doc_code_only_range_gold_is_allowed_with_warning(tmp_path: Path) -> None:
    case = make_case(expected_sources=({"doc_code": "D01"},))
    run = build_run(tmp_path, cases=[case], rows=[make_row(case)])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert any("整篇" in warning for warning in result.warnings)


# --------------------------------------------------------------------------- #
# 退出码 3：样本 / 数据 / 配置
# --------------------------------------------------------------------------- #


def test_min_sample_insufficient_is_unknown(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    result = evaluate(run, make_config(tmp_path, hard_gate_min_sample={"b0": 4}))
    assert result.exit_code == EXIT_UNKNOWN
    unknown = next(item for item in result.unknowns if item.gate_id == "min_sample")
    assert unknown.evidence["evaluated_count"] == 1
    assert unknown.evidence["min_sample"] == 4
    assert unknown.evidence["basis"] == "evaluated_count"


def test_min_sample_uses_evaluated_count_not_case_count(tmp_path: Path) -> None:
    """OCR 行不进分母：2 条可评分 + 2 条 OCR，min_sample=2 必须通过。"""
    cases = [
        make_case("Q01"),
        make_case("Q02"),
        make_case("Q33", requires_ocr=True, stratum="ocr", expected_sources=()),
        make_case("Q34", requires_ocr=True, stratum="ocr", expected_sources=()),
    ]
    rows = [
        make_row(cases[0]),
        make_row(cases[1]),
        make_row(cases[2], status="skipped_requires_ocr", checks=[], outcome=None),
        make_row(cases[3], status="skipped_requires_ocr", checks=[], outcome=None),
    ]
    run = build_run(tmp_path, cases=cases, rows=rows, trace_specs={"Q01": {}, "Q02": {}})
    passing = evaluate(run, make_config(tmp_path, hard_gate_min_sample={"b0": 2}))
    assert passing.exit_code == EXIT_PASS, passing.to_dict()
    assert passing.scored_count == 2
    assert passing.evaluated_count == 2

    failing = evaluate(run, make_config(tmp_path, hard_gate_min_sample={"b0": 3}))
    assert failing.exit_code == EXIT_UNKNOWN


def test_evaluated_count_excludes_error_and_ocr_rows(tmp_path: Path) -> None:
    """evaluated_count = pass/fail 且非 OCR、非 error；error 行本身另走 exit 3。"""
    cases = [make_case("Q01"), make_case("Q02"), make_case("Q33", requires_ocr=True)]
    rows = [
        make_row(cases[0]),
        make_row(cases[1], status="error", outcome=None, checks=[], error={"code": "x"}),
        make_row(cases[2], status="skipped_requires_ocr", outcome=None, checks=[]),
    ]
    run = build_run(
        tmp_path, cases=cases, rows=rows, trace_specs={"Q01": {}}
    )
    result = evaluate(run, make_config(tmp_path, hard_gate_min_sample={"b0": 1}))
    assert result.evaluated_count == 1
    assert result.scored_count == 1
    # error 行仍会使本轮不完整 → exit 3（不是因为它没进分母）
    assert result.exit_code == EXIT_UNKNOWN
    assert any(item.gate_id == "run" for item in result.unknowns)


def test_badcase_evaluated_count_13_includes_empty_gold_rows(tmp_path: Path) -> None:
    """badcase 硬门禁分母 13 含 N10/N12/N13 空 gold 行；检索分母（10）属 T006b。"""
    cases = [make_case(f"B{index:02d}", suite="badcase", stratum="price") for index in range(13)]
    rows = [make_row(case) for case in cases]
    # 10 条有 gold、3 条空 gold（N10/N12/N13 形态），但都参与硬门禁评估
    for case in cases[10:]:
        row = make_row(case)
        row["gold"] = {
            "case_id": case.case_id,
            "requires_ocr": False,
            "skipped": False,
            "sources": [],
            "unit_ids": [],
            "relevant_unit_ids": [],
        }
        rows[cases.index(case)] = row
    run = build_run(
        tmp_path,
        cases=cases,
        rows=rows,
        trace_specs={case.case_id: {} for case in cases},
    )
    result = evaluate(run, make_config(tmp_path, hard_gate_min_sample={"badcase": 13}))
    assert result.exit_code == EXIT_PASS, result.to_dict()
    assert result.evaluated_count == 13
    # 质量层检索分母只算有 gold 的 10 条，不得复用硬门禁 13
    retrieval_denominator = sum(1 for row in rows if row["gold"]["sources"])
    assert retrieval_denominator == 10

    short = evaluate(run, make_config(tmp_path, hard_gate_min_sample={"badcase": 14}))
    assert short.exit_code == EXIT_UNKNOWN


def test_min_sample_missing_suite_is_unknown(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    result = evaluate(run, make_config(tmp_path, hard_gate_min_sample={"badcase": 1}))
    assert result.exit_code == EXIT_UNKNOWN
    unknown = next(item for item in result.unknowns if item.gate_id == "min_sample")
    assert unknown.check_id == "min_sample_missing"


def test_missing_dataset_is_unknown(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    result = evaluate(run, make_config(tmp_path), dataset_path=tmp_path / "nope.jsonl")
    assert result.exit_code == EXIT_UNKNOWN
    unknown = next(item for item in result.unknowns if item.gate_id == "dataset")
    assert unknown.check_id == "dataset_unreadable"


def test_corrupt_dataset_is_unknown(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])])
    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not json\n", encoding="utf-8")
    result = evaluate(run, make_config(tmp_path), dataset_path=broken)
    assert result.exit_code == EXIT_UNKNOWN
    assert any(item.gate_id == "dataset" for item in result.unknowns)


def test_gate_version_mismatch_is_unknown(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(
        tmp_path,
        cases=cases,
        rows=[make_row(cases[0])],
        manifest=make_manifest(gate_version="mktkb.gate.v9.9", case_count=1),
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN
    assert any(item.gate_id == "gate_config" for item in result.unknowns)


def test_error_row_is_unknown(tmp_path: Path) -> None:
    case = make_case()
    row = make_row(
        case,
        status="error",
        outcome=None,
        checks=[],
        error={"code": "gold_unresolved", "message": "Q01: gold 无法解析"},
    )
    run = build_run(tmp_path, cases=[case], rows=[row], trace_specs={})
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN, result.to_dict()
    unknown = next(item for item in result.unknowns if item.gate_id == "run")
    assert unknown.evidence["case_ids"] == ["Q01"]


# --------------------------------------------------------------------------- #
# 退出码 4：live 未授权
# --------------------------------------------------------------------------- #


def test_live_mode_exits_four(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(
        tmp_path,
        cases=cases,
        rows=[make_row(cases[0])],
        manifest=make_manifest(mode="live"),
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_LIVE_UNAUTHORIZED, result.to_dict()
    assert result.hard_failures == ()
    assert result.unknowns == ()
    assert set(result.gate_status.values()) == {"not_evaluated"}
    assert any("live" in warning for warning in result.warnings)


def test_live_mode_not_dependent_on_kernel_refusal(tmp_path: Path) -> None:
    """内核 ``_coerce_mode`` 接受 live（T003a 遗留）；gate 必须自己拒绝。"""
    assert "live" in {mode.value for mode in _trace_modes()}
    manifest = make_manifest(mode="live")
    cases = [make_case("Q01")]
    run = build_run(tmp_path, cases=cases, rows=[make_row(cases[0])], manifest=manifest)
    assert evaluate(run, make_config(tmp_path)).exit_code == EXIT_LIVE_UNAUTHORIZED


def _trace_modes():
    from mktkb.observability.contracts import TraceMode

    return tuple(TraceMode)


def test_live_mode_is_case_insensitive(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(
        tmp_path,
        cases=cases,
        rows=[make_row(cases[0])],
        manifest=make_manifest(mode="LIVE"),
        trace_specs={},
    )
    assert evaluate(run, make_config(tmp_path)).exit_code == EXIT_LIVE_UNAUTHORIZED


def test_unknown_mode_is_unknown(tmp_path: Path) -> None:
    cases = [make_case("Q01")]
    run = build_run(
        tmp_path,
        cases=cases,
        rows=[make_row(cases[0])],
        manifest=make_manifest(mode="hybrid"),
        trace_specs={},
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_UNKNOWN
    unknown = next(item for item in result.unknowns if item.gate_id == "gate_config")
    assert unknown.check_id == "mode_invalid"


# --------------------------------------------------------------------------- #
# 优先级 / 结构 / 豁免
# --------------------------------------------------------------------------- #


def test_hard_failure_priority_over_unknown(tmp_path: Path) -> None:
    case = make_case()
    row = make_row(case, outcome={"citations": []})
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path, hard_gate_min_sample={"b0": 4}))
    assert result.exit_code == EXIT_HARD_FAILURE
    assert result.hard_failures == ("citation_required",)


def test_failures_carry_case_check_and_evidence(tmp_path: Path) -> None:
    case = make_case()
    row = make_row(case, outcome={"citations": []})
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    failure = result.failures[0]
    payload = failure.to_dict()
    assert set(payload) == {"gate_id", "case_id", "check_id", "evidence"}
    assert payload["gate_id"] == "citation_required"
    assert payload["case_id"] == "Q01"
    assert payload["check_id"] == "citation_missing"
    assert payload["evidence"]["kind"] == "answer"
    assert "source_hit" in payload["evidence"]


def test_gate_result_to_dict_roundtrips_json(tmp_path: Path) -> None:
    cases = [make_case("Q01"), make_case("Q02", stratum="text", expected_values=())]
    rows = [
        make_row(cases[0]),
        make_row(cases[1], checks=make_checks(value_hit="fail")),
    ]
    run = build_run(tmp_path, cases=cases, rows=rows)
    result = evaluate(run, make_config(tmp_path))
    payload = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
    assert payload["exit_code"] == EXIT_PASS
    assert set(payload["gate_status"]) == set(HARD_GATE_IDS)
    assert payload["scored_count"] == 2
    assert payload["min_sample"] == 1


def test_hard_gate_waiver_api_absent() -> None:
    """硬门禁不可豁免：本包不提供 waiver API，也不接受 waiver 参数。"""
    assert not hasattr(gate_module, "waive")
    assert not hasattr(gate_module, "waive_hard_gate")
    assert not hasattr(GateConfig, "waivers")
    parameters = inspect.signature(evaluate_gate).parameters
    assert "waiver" not in parameters
    assert "waivers" not in parameters


def test_gate_treats_run_rows_as_the_only_runtime_evidence(tmp_path: Path) -> None:
    """gate 只读 cases.jsonl 行 + trace + 数据集；不得读取 summary 来替代判定。"""
    case = make_case()
    row = make_row(case, outcome={"text": "A 区 8 号有相关记录"})
    run = build_run(
        tmp_path,
        cases=[case],
        rows=[row],
        summary={"suite": "b0", "scored_count": 99, "metrics": {"Recall@10": 1.0}},
    )
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    assert result.scored_count == 1


def test_run_reported_checks_do_not_drive_hard_gates(tmp_path: Path) -> None:
    """run 行自报的 checks 不参与硬门禁：文本缺失 → fail；checks 说 pass 也没用。"""
    case = make_case()
    row = make_row(
        case,
        outcome={"text": "A 区 8 号有相关记录"},
        checks=make_checks(value_hit="pass"),
    )
    run = build_run(tmp_path, cases=[case], rows=[row])
    result = evaluate(run, make_config(tmp_path))
    assert result.exit_code == EXIT_HARD_FAILURE
    assert result.hard_failures == ("exact_value_contract",)

    good = make_row(case)
    good["outcome"]["text"] = "P01 位于 A 区 8 号"
    good["checks"] = make_checks(value_hit="fail")
    good_run = build_run(tmp_path / "good", cases=[case], rows=[good])
    assert evaluate(good_run, make_config(tmp_path)).exit_code == EXIT_PASS
