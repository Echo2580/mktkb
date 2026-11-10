"""T007：run diff（new/fixed/still-failing + 按 stratum 指标差）与报告（handoff §5.4–§5.5）。

口径：

- ``new_failures`` / ``fixed_failures`` / ``still_failing`` 只看 ``status="fail"``，按
  ``case_id`` 排序；``error`` 单独成列（不混入失败集）；
- 指标差按 ``stratum`` + ``all`` 计算，分母沿用 gate 的指标口径（检索=有 gold 且非 OCR，
  答案=scored 且非 OCR/error，运行=有样本行）；``None`` 一律显示 unknown，**不补 0**；
- ``comparison="explicit_cross_version"`` 只能分析、不能放行（``release_allowed=False``，
  ``require_release_baseline`` 抛错）；同版本且已审批的 baseline 才是 ``release_baseline``；
- markdown / html 同源同数据；HTML 单文件、内联 CSS、无 ``<script``、无 http(s)/src/href。

全部合成产物（``tmp_path``），零真实模型 / OCR / 调用。
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
from pathlib import Path

import pytest

import mktkb.evaluation.gate as gate_module
from mktkb.evaluation.baseline import approve_baseline, load_baseline, save_baseline
from mktkb.evaluation.dataset import CaseSpec, write_cases
from mktkb.evaluation.gate import (
    DEFAULT_GATE_CONFIG_PATH,
    GateFailure,
    GateResult,
    GateUnknown,
    QualityCheck,
    QualityMetricResult,
    QualityResult,
    load_gate_config,
)
from mktkb.evaluation.report import (
    MetricDelta,
    RunDiff,
    diff_runs,
    render_html,
    render_markdown,
    require_release_baseline,
)
from mktkb.evaluation.runner import RunManifest, RunResult
from mktkb.observability.contracts import GATE_SCHEMA_VERSION

DS_VERSION = "b0:dev-1:0123456789ab"
CORPUS_SHA = "b" * 64
#: 当前默认 gate 配置（``diff_runs`` 不传 config 时加载它）的内容哈希；放行路径要求
#: gate 质量层 ``gate_config_hash`` 与它一致（P1 #59：同 gate_version 改内容也要拒绝）。
CURRENT_CONFIG_HASH = load_gate_config(DEFAULT_GATE_CONFIG_PATH).config_hash


# --------------------------------------------------------------------------- #
# 合成 run / gate
# --------------------------------------------------------------------------- #


def make_manifest(**overrides) -> RunManifest:
    payload = {
        "run_id": "run-b0-baseline",
        "mode": "local",
        "scope": "end_to_end",
        "suite": "b0",
        "dataset_version": DS_VERSION,
        "dataset_sha256": "a" * 64,
        "corpus_manifest_sha256": CORPUS_SHA,
        "business_date": "2026-10-28",
        "index_revision": 6,
        "pipeline_version": "pipeline1234",
        "gate_version": GATE_SCHEMA_VERSION,
        "label_version": "dev-1",
        "created_at": "2026-11-05T00:00:00.000+00:00",
        "case_count": 3,
        "config_hash": "c" * 12,
        "dataset_path": "",
    }
    payload.update(overrides)
    return RunManifest(**payload)


def make_case(case_id: str, stratum: str = "exact") -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        suite="b0",
        split="dev",
        stratum=stratum,
        business_date="2026-10-28",
        question=f"{case_id} 的问题",
        expected_kind="answer",
        expected_values=("P01",),
        expected_sources=({"doc_code": "D01", "unit_key": "sheet:A:row:8"},),
        labeler="lead",
        label_version="dev-1",
    )


def make_row(case: CaseSpec, *, status: str = "pass", value_hit: float = 1.0,
             latency_ms: int | None = 10, cost_cny: float | None = None) -> dict:
    return {
        "case_id": case.case_id,
        "suite": case.suite,
        "status": status,
        "trace_id": f"trace-{case.case_id}",
        "previous_trace_id": None,
        "replayed": False,
        "checks": [],
        "metrics": {
            "Recall@10": value_hit,
            "MRR@10": value_hit,
            "nDCG@10": value_hit,
            "hard_filter_violations": 0,
            "retrieved_units": 1,
            "empty_recall": 0.0 if value_hit else 1.0,
            "value_hit": value_hit,
            "source_hit": value_hit,
            "kind_correct": value_hit,
            "citation_precision": value_hit,
            "citation_recall": value_hit,
        },
        "refused": False,
        "should_refuse": False,
        "path": "rag",
        "latency_ms": latency_ms,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_cny": cost_cny,
        "duration_ms": int(latency_ms or 0),
        "turns_executed": 1,
        "multi_turn_claimed": False,
        "outcome": {"kind": "answer", "text": "P01", "citations": [], "retrieved": []},
        "gold": {"case_id": case.case_id, "sources": []},
        "error": {"code": "x"} if status == "error" else None,
    }


CASES = (make_case("Q01", "exact"), make_case("Q02", "text"), make_case("Q03", "exact"))


def write_run(
    tmp_path: Path,
    name: str,
    *,
    rows: list[dict],
    manifest: RunManifest | None = None,
    cases: tuple[CaseSpec, ...] = CASES,
) -> RunResult:
    run_dir = tmp_path / name
    run_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = tmp_path / f"{name}.dataset.jsonl"
    write_cases(dataset_path, list(cases))
    base = manifest or make_manifest()
    manifest = dataclasses.replace(base, dataset_path=str(dataset_path), case_count=len(cases))
    (run_dir / "run_manifest.json").write_bytes(
        (json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    (run_dir / "cases.jsonl").write_bytes(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows).encode("utf-8")
    )
    summary = {
        "run_id": manifest.run_id,
        "suite": manifest.suite,
        "mode": manifest.mode,
        "status_counts": {},
        "metrics_scope": {"cases_in_denominator": len(rows)},
    }
    (run_dir / "summary.json").write_bytes(
        (json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    return RunResult(manifest=manifest, out_dir=run_dir, cases=tuple(rows), summary=summary)


def write_gate_json(run: RunResult | object, gate: GateResult) -> Path:
    """把门禁结果写到 run 目录 ``gate.json``（与 CLI ``gate`` 命令同内容）。

    ``run`` 可以是 ``RunResult``（``out_dir``）或 ``Baseline``（``run_dir``）。
    放行路径会用它重核**审批时刻**的配置哈希：其 canonical JSON 的 SHA-256 必须等于
    审批绑定的 ``gate_result_sha256``（P1 #59）。
    """
    payload = json.dumps(
        gate.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    directory = getattr(run, "out_dir", None) or getattr(run, "run_dir", None)
    assert directory is not None, f"write_gate_json 需要 run_dir/out_dir，收到 {type(run).__name__}"
    path = Path(directory) / "gate.json"
    path.write_bytes(payload.encode("utf-8"))
    return path


def baseline_run(tmp_path: Path, **overrides) -> RunResult:
    rows = [
        make_row(CASES[0], status="fail", value_hit=1.0, latency_ms=10),
        make_row(CASES[1], status="fail", value_hit=0.0, latency_ms=20),
        make_row(CASES[2], status="pass", value_hit=0.5, latency_ms=30),
    ]
    return write_run(tmp_path, "run-baseline", rows=rows, manifest=make_manifest(**overrides))


def current_run(tmp_path: Path, **overrides) -> RunResult:
    rows = [
        make_row(CASES[0], status="pass", value_hit=1.0, latency_ms=10),
        make_row(CASES[1], status="fail", value_hit=0.0, latency_ms=20),
        make_row(CASES[2], status="fail", value_hit=1.0, latency_ms=40),
    ]
    return write_run(
        tmp_path,
        "run-current",
        rows=rows,
        manifest=make_manifest(run_id="run-b0-current", **overrides),
    )


def make_quality_metric(
    *, metric: str = "value_hit", group: str = "answer", stratum: str = "all",
    status: str = "unknown", observed: float | None = 0.9, denominator: int = 32,
) -> QualityMetricResult:
    return QualityMetricResult(
        metric=metric,
        group=group,
        stratum=stratum,
        direction="higher_is_better",
        observed=observed,
        denominator=denominator,
        dataset_sample=32,
        denominator_basis="scored_cases_non_ocr",
        source="summary.json",
        status=status,
        checks=(
            QualityCheck(
                "approval",
                status,
                observed=observed,
                denominator=denominator,
                detail={"reason": "thresholds_unapproved" if status == "unknown" else "within_tolerance"},
            ),
        ),
    )


def make_gate(
    exit_code: int = 3,
    *,
    quality: bool = True,
    quality_status: str = "unknown",
    run_id: str = "run-b0-current",
    hard_failures: tuple[str, ...] = (),
    failures: tuple[GateFailure, ...] = (),
    unknowns: tuple[GateUnknown, ...] = (),
    metrics: tuple[QualityMetricResult, ...] = (),
    gate_config_hash: str | None = None,
    gate_version: str = GATE_SCHEMA_VERSION,
    suite: str = "b0",
    mode: str = "local",
) -> GateResult:
    quality_result = (
        QualityResult(
            status=quality_status,
            metrics=metrics,
            strata=("all",),
            stratum_status={"all": quality_status},
            failures=(),
            unknowns=(),
            waived=(),
            diagnostics={},
            warnings=(),
            config_status="approved" if exit_code == 0 else "unapproved",
            gate_config_hash=(
                CURRENT_CONFIG_HASH if gate_config_hash is None else gate_config_hash
            ),
            baseline_run_id=None,
            baseline_pipeline_version=None,
        )
        if quality
        else None
    )
    return GateResult(
        exit_code=exit_code,
        gate_status={
            gate_id: ("fail" if gate_id in hard_failures else "pass")
            for gate_id in (
                "security_leak",
                "cross_entity",
                "stale_bypass",
                "conflict_not_rejected",
                "exact_value_contract",
                "pagination_contract",
                "citation_required",
                "trace_integrity",
            )
        },
        hard_failures=hard_failures,
        failures=failures,
        unknowns=unknowns,
        not_applicable=(),
        warnings=(),
        run_id=run_id,
        suite=suite,
        mode=mode,
        gate_version=gate_version,
        scored_count=3,
        min_sample=32,
        quality=quality_result,
    )


def delta(diff: RunDiff, metric: str, stratum: str) -> MetricDelta:
    matches = [item for item in diff.metric_deltas if item.metric == metric and item.stratum == stratum]
    assert len(matches) == 1, (metric, stratum)
    return matches[0]


# --------------------------------------------------------------------------- #
# §5.4 diff 完整
# --------------------------------------------------------------------------- #


def test_diff_identical_runs_is_empty_not_error(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = write_run(
        tmp_path,
        "run-current-same",
        rows=list(baseline.cases),
        manifest=make_manifest(run_id="run-other"),
    )
    diff = diff_runs(saved, current)
    assert diff.new_failures == ()
    assert diff.fixed_failures == ()
    assert diff.new_errors == () and diff.resolved_errors == ()
    assert diff.status_changes == ()
    assert diff.empty is True
    assert all(item.status in {"unchanged", "unknown"} for item in diff.metric_deltas)
    # 参数顺序兼容 handoff §5.4 的 (baseline, run)
    assert diff_runs(current, saved).to_dict() == diff.to_dict()


def test_diff_lists_new_fixed_still_failing_by_case_id(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)

    diff = diff_runs(saved, current)
    assert diff.new_failures == ("Q03",)
    assert diff.fixed_failures == ("Q01",)
    assert diff.still_failing == ("Q02",)
    assert diff.new_errors == () and diff.persistent_errors == ()
    changes = {item["case_id"]: (item["baseline_status"], item["current_status"]) for item in diff.status_changes}
    assert changes == {"Q01": ("fail", "pass"), "Q03": ("pass", "fail")}
    assert "Q03" in diff.to_dict()["new_failures"]


def test_diff_metric_deltas_by_stratum_and_all(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)
    diff = diff_runs(saved, current)

    assert diff.strata[0] == "all"
    assert set(diff.strata) == {"all", "exact", "text"}

    overall = delta(diff, "value_hit", "all")
    assert overall.baseline == pytest.approx(0.5)
    assert overall.current == pytest.approx(2.0 / 3.0)
    assert overall.delta == pytest.approx(0.5 / 3.0)
    assert overall.delta_pp == pytest.approx(50.0 / 3.0)
    assert overall.status == "improved"
    assert overall.baseline_denominator == 3 and overall.current_denominator == 3

    exact = delta(diff, "value_hit", "exact")
    assert exact.baseline == pytest.approx(0.75) and exact.current == pytest.approx(1.0)
    assert exact.baseline_denominator == 2

    text = delta(diff, "value_hit", "text")
    assert text.baseline == 0.0 and text.current == 0.0
    assert text.status == "unchanged"


def test_diff_unknown_samples_are_not_zero(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)
    diff = diff_runs(saved, current)

    cost = delta(diff, "cost_per_case_cny", "all")
    assert cost.baseline is None and cost.current is None
    assert cost.delta is None and cost.status == "unknown"
    assert cost.baseline_denominator == 0 and cost.current_denominator == 0
    assert cost.reason and "zero_sample" in cost.reason

    latency = delta(diff, "p95_latency_ms", "all")
    assert latency.baseline == 30.0 and latency.current == 40.0
    assert latency.status == "regressed"  # lower_is_better
    assert latency.threshold_configured is False

    html = render_html(current.summary, diff, make_gate(3, metrics=(make_quality_metric(),)))
    markdown = render_markdown(diff, make_gate(3, metrics=(make_quality_metric(),)), summary=current.summary)
    for text in (markdown, html):
        assert "cost_per_case_cny" in text
        assert "zero_sample" in text or "零样本" in text
        assert "无 SLA" in text
    cost_row = [line for line in markdown.splitlines() if "cost_per_case_cny" in line and "| all |" in line]
    assert cost_row and "unknown" in cost_row[0]
    assert "0.0" not in cost_row[0]


def test_diff_cross_version_is_rejected_by_default(tmp_path: Path):
    baseline = baseline_run(tmp_path, pipeline_version="pipeline-p1")
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path, pipeline_version="pipeline-p2")

    with pytest.raises(ValueError):
        diff_runs(saved, current)
    with pytest.raises(ValueError):
        diff_runs(saved, current, comparison="release")


def test_diff_cross_version_explicit_is_analysis_only(tmp_path: Path):
    baseline = baseline_run(tmp_path, pipeline_version="pipeline-p1")
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path, pipeline_version="pipeline-p2")

    diff = diff_runs(saved, current, compare_with=saved.baseline_id)
    assert diff.comparison == "explicit_cross_version"
    assert diff.release_allowed is False
    assert diff.release_blocked_reason == "explicit_cross_version_analysis_only"
    with pytest.raises(ValueError):
        require_release_baseline(diff)
    with pytest.raises(ValueError):
        diff_runs(saved, current, comparison="release", compare_with=saved.baseline_id)


def test_diff_release_path_requires_approved_same_version_baseline(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    root = tmp_path / "baselines"
    saved = save_baseline(baseline, root)
    current = current_run(tmp_path)

    unapproved = diff_runs(saved, current)
    assert unapproved.release_allowed is False
    assert unapproved.release_blocked_reason == "baseline_unapproved"

    approve_gate = make_gate(0, quality_status="pass", run_id=baseline.manifest.run_id)
    approve_baseline(
        baseline, approve_gate, root, approver="owner", reason="fixture",
    )
    write_gate_json(saved, approve_gate)  # 审批绑定的那份门禁结果（放行重核用）
    approved_baseline = load_baseline(saved.baseline_id, root)
    # P1 #59：放行还要求当前 gate 非空且绑定当前 run、配置哈希一致（缺 gate 不再放行）。
    current_gate = make_gate(0, quality_status="pass", run_id=current.manifest.run_id)
    approved = diff_runs(approved_baseline, current, gate=current_gate)
    assert approved.comparison == "release_baseline"
    assert approved.release_allowed is True
    require_release_baseline(approved)  # 同版本已审批 + 当前 gate 通过 → 可放行


def test_diff_release_path_blocks_failed_current_gate(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    root = tmp_path / "baselines"
    saved = save_baseline(baseline, root)
    approve_baseline(
        baseline, make_gate(0, quality_status="pass", run_id=baseline.manifest.run_id),
        root, approver="owner", reason="fixture",
    )
    current = current_run(tmp_path)
    diff = diff_runs(
        load_baseline(saved.baseline_id, root),
        current,
        gate=make_gate(1, hard_failures=("citation_required",), quality_status="pass"),
    )
    assert diff.release_allowed is False
    assert diff.release_blocked_reason == "current_gate_exit_1"
    with pytest.raises(ValueError):
        require_release_baseline(diff)


def test_diff_gate_exit_transition_is_explicit(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    root = tmp_path / "baselines"
    saved = save_baseline(baseline, root, gate=make_gate(3, run_id=baseline.manifest.run_id))
    current = current_run(tmp_path)
    diff = diff_runs(saved, current, gate=make_gate(0, quality_status="pass"))
    assert diff.baseline_exit_code == 3
    assert diff.current_exit_code == 0
    assert diff.gate_exit_transition == "3->0"
    assert diff.gate_exit_changed is True
    assert diff.release_allowed is False  # baseline 未审批，即使当前门禁 0


def test_diff_rejects_incomparable_dataset(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path, dataset_version="b0:dev-2:ffffffffffff")
    with pytest.raises(ValueError):
        diff_runs(saved, current)


# --------------------------------------------------------------------------- #
# §5.5 报告：硬门禁置顶 / 单文件无 JS 无外链 / 同源同数据
# --------------------------------------------------------------------------- #


def _gate_with_hard_failure() -> GateResult:
    failure = GateFailure(
        gate_id="citation_required",
        case_id="Q03",
        check_id="missing_citation",
        evidence={"reason": "answer 无 unit 级引用"},
    )
    unknown = GateUnknown(
        gate_id="quality:value_hit",
        case_id=None,
        check_id="thresholds_unapproved",
        reason="阈值未审批",
        evidence={"config_status": "unapproved"},
    )
    return make_gate(
        1,
        hard_failures=("citation_required",),
        failures=(failure,),
        unknowns=(unknown,),
        quality_status="unknown",
        metrics=(make_quality_metric(),),
    )


def test_markdown_puts_hard_gate_first_and_states_exit_semantics(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)
    diff = diff_runs(saved, current)

    markdown = render_markdown(diff, _gate_with_hard_failure(), summary=current.summary)
    assert "硬门禁" in markdown and "质量层" in markdown and "Diff" in markdown
    assert markdown.index("硬门禁") < markdown.index("质量层") < markdown.index("Diff")
    assert markdown.split("## ")[1].startswith("1. 硬门禁")
    assert "exit_code: 1" in markdown or "exit_code=1" in markdown
    assert "citation_required" in markdown
    assert "阈值未审批" in markdown
    assert "min_sample 提示" in markdown
    assert "报告只展示门禁结果" in markdown


def test_min_sample_hint_excludes_zero_sample_metric(tmp_path: Path):
    """R1-MEDIUM-1：零样本指标（分母 0）不得成为 min_sample 提示的“最小值”。"""
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)
    diff = diff_runs(saved, current)
    gate = make_gate(
        3,
        metrics=(
            make_quality_metric(metric="Recall@10", group="retrieval", stratum="all", denominator=32),
            make_quality_metric(metric="Recall@10", group="retrieval", stratum="text", denominator=8),
            make_quality_metric(metric="value_hit", group="answer", stratum="all", denominator=32),
            make_quality_metric(
                metric="cost_per_case_cny", group="runtime", stratum="all",
                denominator=0, observed=None,
            ),
        ),
    )
    markdown = render_markdown(diff, gate, summary=current.summary)
    hint = next(line for line in markdown.splitlines() if "min_sample 提示" in line)
    assert "retrieval=8（Recall@10/text）" in hint
    assert "answer=32（value_hit/all）" in hint
    assert "零样本指标（分母 0）" in hint and "cost_per_case_cny" in hint
    assert "= 0（" not in hint
    assert "cost_per_case_cny" not in hint.split("；零样本指标")[0]
    assert "retrieval=8（Recall@10/text）" in render_html(current.summary, diff, gate)


def test_min_sample_hint_uses_smallest_nonzero_denominator_per_group(tmp_path: Path):
    """R1-MEDIUM-1：按分组取最小非零 stratum 分母（badcase 形态：检索 2、答案 1）。"""
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)
    diff = diff_runs(saved, current)
    gate = make_gate(
        3,
        metrics=(
            make_quality_metric(metric="Recall@10", group="retrieval", stratum="all", denominator=10),
            make_quality_metric(metric="Recall@10", group="retrieval", stratum="text", denominator=2),
            make_quality_metric(
                metric="Recall@10", group="retrieval", stratum="exact", denominator=0, observed=None
            ),
            make_quality_metric(metric="value_hit", group="answer", stratum="all", denominator=4),
            make_quality_metric(metric="value_hit", group="answer", stratum="text", denominator=1),
            make_quality_metric(
                metric="p95_latency_ms", group="runtime", stratum="all", denominator=0, observed=None
            ),
        ),
    )
    markdown = render_markdown(diff, gate, summary=current.summary)
    hint = next(line for line in markdown.splitlines() if "min_sample 提示" in line)
    assert "retrieval=2（Recall@10/text）" in hint
    assert "answer=1（value_hit/text）" in hint
    assert "runtime=" not in hint  # 该分组只有零样本指标 → 不给提示
    assert "= 0（" not in hint


def test_diff_status_column_is_direction_not_gate_state(tmp_path: Path):
    """R1-LOW-2：Diff 表 regressed/improved 只是数值方向，不是质量/门禁状态。"""
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)
    diff = diff_runs(saved, current)
    markdown = render_markdown(diff, _gate_with_hard_failure(), summary=current.summary)
    assert "regressed/improved 只是数值方向" in markdown
    assert "regressed/improved 只是数值方向" in render_html(
        current.summary, diff, _gate_with_hard_failure()
    )


def test_html_is_single_file_inline_css_no_script_no_external(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)
    diff = diff_runs(saved, current)
    html = render_html(current.summary, diff, _gate_with_hard_failure())

    assert html.startswith("<!DOCTYPE html>")
    assert "<style>" in html and "</style>" in html
    assert len(html.encode("utf-8")) > 1000
    assert re.search(r"<script", html, re.IGNORECASE) is None
    assert re.search(r"https?://", html) is None
    assert re.search(r"\bsrc\s*=", html, re.IGNORECASE) is None
    assert re.search(r"\bhref\s*=", html, re.IGNORECASE) is None
    assert re.search(r"<link\b", html, re.IGNORECASE) is None
    assert "@import" not in html
    assert html.index("硬门禁") < html.index("质量层") < html.index("Diff")
    assert html.index("<section id='hard-gate'>") < html.index("<section id='identity'>")
    assert "min_sample 提示" in html
    # 兼容只给 (diff, gate) 的调用（handoff §5.5 未要求 summary）
    assert render_html(diff, _gate_with_hard_failure()).startswith("<!DOCTYPE html>")


def test_markdown_and_html_share_the_same_data(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)
    diff = diff_runs(saved, current)
    gate = _gate_with_hard_failure()
    markdown = render_markdown(diff, gate, summary=current.summary)
    html = render_html(current.summary, diff, gate)
    for token in (
        saved.baseline_id,
        current.manifest.run_id,
        "Q03",
        "citation_required",
        "explicit_cross_version" if diff.comparison == "explicit_cross_version" else "release_baseline",
    ):
        assert token in markdown, token
        assert token in html, token


def test_renderers_are_pure_and_gate_never_reads_report(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)
    diff = diff_runs(saved, current)
    before = sorted(path.name for path in current.out_dir.iterdir())
    render_markdown(diff, make_gate(3), summary=current.summary)
    render_html(current.summary, diff, make_gate(3))
    after = sorted(path.name for path in current.out_dir.iterdir())
    assert before == after
    assert "report" not in inspect.getsource(gate_module).lower()


def test_render_states_quality_not_evaluated(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)
    diff = diff_runs(saved, current)
    markdown = render_markdown(diff, make_gate(0, quality=False), summary=current.summary)
    assert "质量层未评估" in markdown
    assert "不代表质量达标" in markdown


def test_render_unapproved_thresholds_are_not_reported_as_pass(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    current = current_run(tmp_path)
    diff = diff_runs(saved, current)
    gate = make_gate(3, quality_status="unknown", metrics=(make_quality_metric(),))
    markdown = render_markdown(diff, gate, summary=current.summary)
    assert "thresholds_unapproved" in markdown
    assert "未审批" in markdown
    assert "质量通过" not in markdown


def test_empty_diff_renders_without_error(tmp_path: Path):
    baseline = baseline_run(tmp_path)
    saved = save_baseline(baseline, tmp_path / "baselines")
    same = write_run(
        tmp_path,
        "run-same",
        rows=list(baseline.cases),
        manifest=make_manifest(run_id="run-b0-same"),
    )
    diff = diff_runs(saved, same)
    markdown = render_markdown(diff, make_gate(0, quality_status="pass"), summary=same.summary)
    html = render_html(same.summary, diff, make_gate(0, quality_status="pass"))
    for text in (markdown, html):
        assert "无新增失败" in text or "无" in text
    assert diff.empty is True
