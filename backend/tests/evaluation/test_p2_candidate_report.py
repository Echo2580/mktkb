"""P2-T209-PREP：报告分列 + candidate/blocked 归档/校验/恢复（离线、合成输入）。

覆盖任务书 E2 §6：

- A 报告分列：执行成功 / 质量 FAIL / 证据不可判 / 软评分 NOT-RUN 四个轴分开，
  不合成 overall success；单 scenario ``verified=true`` 不得外推；缺 scope 的 27 个
  unknown 不是「27 题答错」；``recorded_status`` 不冒充 rescored；跨轮分数不合并；
- A 资金行：当前账本 ca9d… / 当前 GO c72d… 与旧归档 f688… 分列，合法花费不写成
  源码篡改，不查询供应商余额；
- B candidate/blocked：archive→verify→restore→list/diff 全链；候选不可发布（不能成为
  release baseline、不写 approval、不改正式 gate approved）；坏输入 fail-closed；
- 全部合成产物（``tmp_path``），零真实产品/模型/网络调用；``t09_network_guard`` 断言
  外部出站尝试为 0；不读 ``.env`` / 真实 H2 逐题 / 私有密文 / 正式 registry。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.evaluation import p2_candidate_report as pr  # noqa: E402
from mktkb.evaluation.baseline import (  # noqa: E402
    APPROVAL_FILENAME,
    BaselineError,
    BaselineIdentity,
    approve_baseline,
    load_baseline,
    save_baseline,
)
from mktkb.evaluation.report import diff_runs, require_release_baseline  # noqa: E402
from mktkb.evaluation.runner import RunManifest, RunResult  # noqa: E402
from mktkb.observability.contracts import GATE_SCHEMA_VERSION  # noqa: E402

from .test_report import (  # noqa: E402
    CURRENT_CONFIG_HASH,
    make_case,
    make_gate,
    make_manifest,
    make_row,
    write_run,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROUND = "P2-T207-H2-20261114-r1"
OTHER_ROUND = "P2-T207-H2-20261115-other"
LEDGER_CURRENT = "ca9dceb9019790eb6ba4e25cfaf88232915b607d756d0eae21ad7cdf10c6fec9"
LEDGER_PREVIOUS = "4d80d776bcf25079817f5f7dd8863037c27bc01971b6fa0fe239b432ee55fcc6"
GO_CURRENT = "c72dc7abf6ba135fb6c53f77c35b40dda34e97cf535d3be212467c6734b27324"
GO_ARCHIVED = "f688ec7efb7e8ddc145ae9fd593a482a85a6e4a764a9d49a09eab4f3fc26ea98"
CODE_VERSION = "f6c118432a73aa2541c78b9b33c08314bee462b1e1aa70c4391933625b2892ea"
CONFIG_SHA = "9cb322863939522d5defb948b8739dd9385a3bf219c7291c5d1e916de3efbd65"
BINDING_SHA = "291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4"
REAL_DOC = "docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/real-h2.md"
SYNTH_DOC = "docs/reports/OBS-EVAL/P2/T209-PREP/evidence/synthetic-mirror.json"

AXES = ("safety", "cross_user", "cross_entity", "stale_source")


# --------------------------------------------------------------------------- #
# 合成数据：真实 H2 的安全聚合镜像（只含任务书已公开的计数，无逐题内容）
# --------------------------------------------------------------------------- #


def real_mirror_card() -> dict:
    return {
        "schema_version": "mktkb.p2.hard_evidence.scorecard.v0.2",
        "total": 30,
        "executed": 30,
        "errors": 0,
        "passed": 19,
        "failed": 11,
        "min_pass": 24,
        "threshold_met": False,
        "hard_failures": 2,
        "hard_failures_by_kind": {
            "safety": 2,
            "cross_user": 0,
            "cross_entity": 0,
            "stale_source": 0,
        },
        "thresholds_approved": False,
        "detail_export": False,
        "release_ready": False,
        "execution_mode": "live",
        "real_calls": 108,
        "hard_evidence": {
            "axes": {
                "safety": {
                    "planned": 30,
                    "checked": 27,
                    "passed": 1,
                    "not_applicable": 24,
                    "unknown": 3,
                    "violations": 2,
                },
                "cross_user": {
                    "planned": 30,
                    "checked": 27,
                    "passed": 27,
                    "not_applicable": 0,
                    "unknown": 3,
                    "violations": 0,
                },
                "cross_entity": {
                    "planned": 30,
                    "checked": 3,
                    "passed": 3,
                    "not_applicable": 0,
                    "unknown": 27,
                    "violations": 0,
                },
                "stale_source": {
                    "planned": 30,
                    "checked": 25,
                    "passed": 25,
                    "not_applicable": 0,
                    "unknown": 5,
                    "violations": 0,
                },
            },
            "missing_evidence_cases": 27,
            "evidence_complete_cases": 3,
            "verified": False,
        },
        "diagnostics": {"missing_evidence_cases": 27, "verified": False},
    }


def real_mirror_execution(round_id: str = ROUND) -> pr.ExecutionStatus:
    return pr.build_execution(
        round_id=round_id,
        runs=(
            pr.RunOutcome("r0", "base_b0", "succeeded", 26, 32),
            pr.RunOutcome("r1", "base_b0_plus_v01", "succeeded", 1, 1),
            pr.RunOutcome("r2", "pre_v05_without_v07", "succeeded", 2, 2),
            pr.RunOutcome("r3", "post_v05_without_v01", "succeeded", 1, 1),
        ),
    )


def real_mirror_unknown_reasons() -> dict[str, str]:
    return {
        "safety": "undetermined",
        "cross_user": "undetermined",
        "cross_entity": "real_scope_targets_contract_not_generated",
        "stale_source": "undetermined",
    }


def real_mirror_report(*, round_id: str = ROUND) -> pr.SplitReport:
    card = real_mirror_card()
    quality, evidence = pr.parse_card(
        card,
        round_id=round_id,
        scenario_verifications=(
            ("r0", False),
            ("r1", False),
            ("r2", False),
            ("r3", True),
        ),
        thresholds_approved=False,
        unknown_reasons=real_mirror_unknown_reasons(),
    )
    assert quality.total == 30 and evidence.missing_evidence_cases == 27
    return pr.build_split_report(
        reference=real_reference(),
        execution=real_mirror_execution(round_id),
        quality=quality,
        evidence=evidence,
        soft=(
            pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="真实 judge 未授权"),
            pr.SoftStatus.unknown(
                "auxiliary", recorded_status="unavailable", detail="辅助评分未执行"
            ),
        ),
        funding=real_funding(),
    )


def real_reference() -> pr.ReferenceSource:
    return pr.ReferenceSource.create(
        source_kind="real-h2-aggregate",
        document=REAL_DOC,
        plan_id=ROUND,
        code_version=CODE_VERSION,
        config_sha256=CONFIG_SHA,
        binding_sha256=BINDING_SHA,
    )


def synthetic_reference(round_id: str = ROUND) -> pr.ReferenceSource:
    return pr.ReferenceSource.create(
        source_kind="synthetic-mirror",
        document=SYNTH_DOC,
        plan_id=round_id,
        code_version="synthetic",
    )


def real_funding(**overrides) -> pr.FundingStatus:
    payload = {
        "ledger_current_sha256": LEDGER_CURRENT,
        "ledger_previous_sha256": LEDGER_PREVIOUS,
        "ledger_change_cause": "legitimate_spend",
        "go_current_sha256": GO_CURRENT,
        "go_archived_sha256": GO_ARCHIVED,
        "archived_line_moment": "2026-11-14 真实 H2 执行前归档（f688…）",
    }
    payload.update(overrides)
    return pr.FundingStatus.create(**payload)


def clean_axes(total: int = 30) -> tuple[pr.AxisEvidence, ...]:
    return tuple(
        pr.AxisEvidence.create(
            axis=axis,
            planned=total,
            passed=total,
            not_applicable=0,
            unknown=0,
            violations=0,
        )
        for axis in AXES
    )


def clean_report(
    *,
    round_id: str = ROUND,
    total: int = 30,
    passed: int = 30,
    thresholds_approved: bool = False,
) -> pr.SplitReport:
    """全部证据可判、无硬失败的合成候选报告（candidate 状态，仍不可发布）。"""
    quality = pr.build_quality(
        round_id=round_id,
        total=total,
        passed=passed,
        failed=total - passed,
        errors=0,
        safety_violations=0,
        min_pass=24,
        thresholds_approved=thresholds_approved,
        verified=True,
        scenario_verifications=(("s0", True),),
    )
    evidence = pr.build_evidence(
        round_id=round_id,
        total=total,
        missing_evidence_cases=0,
        axes=clean_axes(total),
        verified=True,
    )
    return pr.build_split_report(
        reference=synthetic_reference(round_id),
        execution=pr.build_execution(
            round_id=round_id,
            runs=(pr.RunOutcome("s0", "synthetic_clean", "succeeded", total, total),),
        ),
        quality=quality,
        evidence=evidence,
        soft=(pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="合成"),),
        funding=real_funding(),
    )


# --------------------------------------------------------------------------- #
# 合成 run / baseline（30 例，全部通过；用于候选归档）
# --------------------------------------------------------------------------- #


def candidate_cases(total: int = 30):
    return tuple(make_case(f"Q{index:03d}") for index in range(1, total + 1))


def make_candidate_baseline(
    tmp_path: Path,
    *,
    run_id: str = "run-b0-candidate",
    pipeline_version: str = "pipeline1234",
) -> dict:
    cases = candidate_cases()
    rows = [make_row(case, status="pass") for case in cases]
    run = write_run(
        tmp_path,
        run_id,
        rows=rows,
        manifest=make_manifest(run_id=run_id, pipeline_version=pipeline_version),
        cases=cases,
    )
    root = tmp_path / f"baselines-{run_id}"
    baseline = save_baseline(run, root)
    return {"run": run, "root": root, "baseline": baseline, "cases": cases, "rows": rows}


def make_current_run(tmp_path: Path, cases, rows, *, run_id: str = "run-b0-current") -> RunResult:
    return write_run(
        tmp_path,
        run_id,
        rows=list(rows),
        manifest=make_manifest(run_id=run_id),
        cases=cases,
    )


def archive_candidate(
    ctx: dict,
    report: pr.SplitReport,
    out_dir: Path,
    **overrides,
) -> pr.CandidateArchive:
    payload = {
        "baseline_id_value": ctx["baseline"].baseline_id,
        "root": ctx["root"],
        "out_dir": out_dir,
        "report": report,
        "reason": "T209-PREP 合成候选归档（不发布）",
    }
    payload.update(overrides)
    return pr.archive_candidate(**payload)


def rewrite_manifest(archive_dir: Path, mutate) -> None:
    path = archive_dir / pr.CANDIDATE_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def canonical_json(payload) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest_tree(directory: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(Path(directory).rglob("*")):
        if path.is_file():
            out[path.relative_to(directory).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return out


# --------------------------------------------------------------------------- #
# A. 报告分列
# --------------------------------------------------------------------------- #


def test_real_mirror_reports_quality_fail_not_ready_without_overall_success() -> None:
    report = real_mirror_report()

    # 四个轴分开存在；执行 succeeded 不代表质量通过。
    assert report.execution.status == "succeeded"
    assert report.execution.succeeded_runs == 4
    assert report.execution.total_questions == 30
    assert report.execution.total_turns == 36
    assert report.quality.status == "fail"
    assert report.quality.total == 30 and report.quality.passed == 19
    assert report.quality.failed == 11
    assert report.quality.safety_violations == 2
    assert report.quality.threshold_met is False
    assert report.quality.verified is False
    assert report.quality.release_ready is False
    assert report.evidence.missing_evidence_cases == 27

    data = report.to_dict()
    assert data["report_kind"] == "split_axes"
    assert [item["axis"] for item in data["axes"]] == [
        "execution",
        "quality",
        "evidence",
        "soft",
        "funding",
    ]
    # 没有单一总体成功/就绪字段。
    assert "overall" not in data and "overall_success" not in data
    assert data["publication"]["publishable"] is False
    assert data["publication"]["release_baseline"] is False

    text = pr.render_split_markdown(report)
    for needle in (
        "执行状态",
        "质量状态",
        "证据状态",
        "软评分状态",
        "资金与版本",
        "19/30",
        "11",
        "threshold_met: false",
        "verified: false",
        "release_ready: false",
        "succeeded",
    ):
        assert needle in text, needle
    for banned in ("总体通过", "overall_success", "全部通过", "release_ready: true"):
        assert banned not in text, banned
    assert "不合成" in text
    assert "执行成功" in text and "不代表质量" in text


def test_single_scenario_verified_true_cannot_be_extrapolated() -> None:
    with pytest.raises(pr.CandidateReportError, match="外推"):
        pr.build_quality(
            round_id=ROUND,
            total=30,
            passed=30,
            failed=0,
            errors=0,
            safety_violations=0,
            min_pass=24,
            thresholds_approved=True,
            verified=True,
            scenario_verifications=(("r0", False), ("r3", True)),
        )


def _outcomes(status: str, count: int) -> tuple[pr.RunOutcome, ...]:
    return tuple(
        pr.RunOutcome(
            f"{status}-{index}",
            "synthetic",
            status,
            1,
            1,
            errors=1 if status == "failed" else 0,
        )
        for index in range(1, count + 1)
    )


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        (_outcomes("succeeded", 4), "succeeded"),
        (_outcomes("failed", 4), "failed"),
        ((*_outcomes("succeeded", 2), *_outcomes("failed", 2)), "partial"),
        (_outcomes("not_run", 2), "not_run"),
        ((), "not_run"),
    ],
)
def test_execution_aggregate_status_mapping(runs, expected: str) -> None:
    """D1 回归：全部 failed 必须聚合为 failed，不得误述为 not_run；0 run 为 not_run。"""
    execution = pr.build_execution(round_id=ROUND, runs=runs)
    assert execution.status == expected
    payload = execution.to_dict()
    assert payload["status"] == expected
    if expected == "failed":
        assert execution.failed_runs == 4
        assert execution.succeeded_runs == 0
    if expected == "not_run":
        assert execution.succeeded_runs == 0 and execution.failed_runs == 0
        if not runs:
            assert execution.total_questions == 0 and execution.total_turns == 0


def test_failed_execution_report_renders_failed_not_not_run() -> None:
    """D1 回归：渲染层不得把执行失败写成未执行，且要写明聚合映射。"""
    template = clean_report()
    report = pr.build_split_report(
        reference=template.reference,
        execution=pr.build_execution(round_id=ROUND, runs=_outcomes("failed", 4)),
        quality=template.quality,
        evidence=template.evidence,
        soft=template.soft,
        funding=template.funding,
    )
    text = pr.render_split_markdown(report)
    assert "状态: failed（执行失败" in text
    assert "全部 failed→failed" in text
    assert "混合/部分→partial" in text
    assert "状态: not_run" not in text
    assert report.to_dict()["execution"]["status"] == "failed"
    assert report.to_dict()["axes"][0]["status"] == "failed"


def test_missing_scope_unknown_is_not_reported_as_wrong_answers() -> None:
    report = real_mirror_report()
    cross = {axis.axis: axis for axis in report.evidence.axes}["cross_entity"]
    assert cross.unknown == 27
    assert cross.unknown_reason == "real_scope_targets_contract_not_generated"
    # 11 是质量 fail；27 是缺证据/unknown，两者不得混成一个「答错」数。
    assert report.quality.failed == 11
    text = pr.render_split_markdown(report)
    assert "27 是缺失证据题数，不是 27 题答错" in text
    assert "unknown（不可判）不是答错" in text
    assert "答案错误 27" not in text


def test_recorded_status_is_not_passed_off_as_rescored() -> None:
    report = real_mirror_report()
    text = pr.render_split_markdown(report)
    assert "recorded_status=NOT-RUN" in text
    assert "未重评" in text
    assert "rescored" in text
    with pytest.raises(pr.CandidateReportError, match="rescored"):
        pr.SoftStatus.create(
            name="ragas",
            status="unknown",
            recorded_status="ok",
            detail="合成：recorded 不是 rescored",
            rescored=True,
            rescored_scores={},
            rescored_reason="",
        )


def test_scores_from_different_rounds_are_not_merged() -> None:
    with pytest.raises(pr.CandidateReportError, match="跨轮"):
        pr.build_split_report(
            reference=synthetic_reference(OTHER_ROUND),
            execution=real_mirror_execution(ROUND),
            quality=real_mirror_report(round_id=OTHER_ROUND).quality,
            evidence=real_mirror_report(round_id=OTHER_ROUND).evidence,
            soft=real_mirror_report().soft,
            funding=real_funding(),
        )


def test_funding_lines_separate_current_snapshot_and_archived_old_line() -> None:
    report = real_mirror_report()
    funding = report.funding
    assert funding.ledger_current_sha256 == LEDGER_CURRENT
    assert funding.go_current_sha256 == GO_CURRENT
    assert funding.go_archived_sha256 == GO_ARCHIVED
    assert funding.archived_scope == "historical_archive"
    assert funding.provider_balance_queried is False
    assert funding.ledger_change_cause == "legitimate_spend"

    text = pr.render_split_markdown(report)
    assert "ca9d" in text and "c72d" in text and "f688" in text
    assert "旧归档" in text
    assert "只代表其旧时刻" in text
    assert "合法" in text and "不是源码篡改" in text
    assert "不查询供应商余额" in text

    with pytest.raises(pr.CandidateReportError, match="余额"):
        real_funding(provider_balance_queried=True)
    with pytest.raises(pr.CandidateReportError, match="legitimate_spend"):
        real_funding(ledger_change_cause="source_tampering")


def test_card_release_ready_true_or_detail_export_is_rejected() -> None:
    card = real_mirror_card()
    card["release_ready"] = True
    with pytest.raises(pr.CandidateReportError, match="release_ready"):
        pr.parse_card(card, round_id=ROUND)

    card = real_mirror_card()
    card["detail_export"] = True
    with pytest.raises(pr.CandidateReportError, match="detail_export"):
        pr.parse_card(card, round_id=ROUND)


def test_card_threshold_met_must_match_counts() -> None:
    card = real_mirror_card()
    card["threshold_met"] = True  # 19/30 不可能是 threshold_met=true
    with pytest.raises(pr.CandidateReportError, match="threshold_met"):
        pr.parse_card(card, round_id=ROUND)


# --------------------------------------------------------------------------- #
# B. candidate/blocked archive → verify → restore → list/diff
# --------------------------------------------------------------------------- #


def test_candidate_archive_verify_restore_list_diff_roundtrip(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path)
    report = clean_report()
    out = tmp_path / "candidates" / "candidate-a"

    record = archive_candidate(ctx, report, out)
    assert record.state == "candidate"
    assert record.publishable is False
    assert record.release_baseline is False
    assert record.gate_approved is False
    assert record.has_approval is False

    manifest = json.loads((out / pr.CANDIDATE_FILENAME).read_text(encoding="utf-8"))
    assert manifest["state"] == "candidate"
    assert manifest["publishable"] is False
    assert manifest["release_baseline"] is False
    assert manifest["gate_approved"] is False
    assert manifest["has_approval"] is False
    assert manifest["payload"]["dir"] == pr.CANDIDATE_PAYLOAD_DIR
    assert manifest["report"]["quality"]["release_ready"] is False
    assert set(manifest) == pr.CANDIDATE_MANIFEST_KEYS

    verified = pr.verify_candidate_archive(out)
    assert verified.state == "candidate"
    assert verified.baseline_id == ctx["baseline"].baseline_id
    assert verified.identity == ctx["baseline"].identity

    archive_before_restore = digest_tree(tmp_path / "candidates")
    dst_root = tmp_path / "restore" / "baselines"
    restored = pr.restore_candidate(out, dst_root)
    assert digest_tree(tmp_path / "candidates") == archive_before_restore
    assert restored.state == "candidate"
    assert restored.publishable is False
    assert restored.baseline.approval is None
    assert restored.baseline.identity == ctx["baseline"].identity
    assert restored.run_id == ctx["baseline"].run_id
    assert not (dst_root / ctx["baseline"].baseline_id / APPROVAL_FILENAME).exists()
    reloaded = load_baseline(ctx["baseline"].baseline_id, dst_root)
    assert reloaded.approval is None

    # candidate 不能成为 release baseline：即便当前 gate 合法，也因 baseline 未审批被拒。
    current = make_current_run(tmp_path, ctx["cases"], ctx["rows"])
    diff = diff_runs(
        reloaded,
        current,
        gate=make_gate(0, quality_status="pass", run_id=current.manifest.run_id),
    )
    assert diff.release_allowed is False
    assert diff.release_blocked_reason == "baseline_unapproved"
    with pytest.raises(ValueError):
        require_release_baseline(diff)

    # list / diff 只读、确定性。
    before = digest_tree(tmp_path / "candidates")
    listing_first = pr.list_candidates(tmp_path / "candidates")
    listing_second = pr.list_candidates(tmp_path / "candidates")
    assert listing_first == listing_second
    assert [item.state for item in listing_first] == ["candidate"]
    assert listing_first[0].publishable is False
    assert listing_first[0].release_baseline is False

    same = pr.diff_candidates(out, out)
    assert same.same_identity is True
    assert same.same_round is True
    assert same.files_added == () and same.files_removed == () and same.files_changed == ()
    assert same.score_merge_allowed is False
    assert same.to_dict() == pr.diff_candidates(out, out).to_dict()
    assert digest_tree(tmp_path / "candidates") == before


def test_blocked_archive_keeps_quality_fail_and_is_never_publishable(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path, run_id="run-b0-blocked")
    report = real_mirror_report()
    out = tmp_path / "candidates" / "blocked-b"

    record = archive_candidate(ctx, report, out)
    assert record.state == "blocked"
    assert record.publishable is False
    assert record.report.quality.status == "fail"
    assert record.report.quality.release_ready is False
    manifest = json.loads((out / pr.CANDIDATE_FILENAME).read_text(encoding="utf-8"))
    assert manifest["state"] == "blocked"
    assert manifest["report"]["evidence"]["missing_evidence_cases"] == 27

    restored = pr.restore_candidate(out, tmp_path / "restore-blocked" / "baselines")
    assert restored.state == "blocked"
    assert restored.baseline.approval is None
    text = pr.render_split_markdown(restored.report)
    assert "质量状态" in text and "release_ready: false" in text


def test_diff_between_archives_of_different_rounds_is_not_score_comparable(
    tmp_path: Path,
) -> None:
    first_ctx = make_candidate_baseline(tmp_path, run_id="run-b0-diff-a")
    second_ctx = make_candidate_baseline(
        tmp_path, run_id="run-b0-diff-b", pipeline_version="pipeline5678"
    )
    first = tmp_path / "candidates" / "round-a"
    second = tmp_path / "candidates" / "round-b"
    archive_candidate(first_ctx, clean_report(round_id=ROUND), first)
    archive_candidate(second_ctx, clean_report(round_id=OTHER_ROUND), second)

    diff = pr.diff_candidates(first, second)
    assert diff.same_round is False
    assert diff.scores_comparable is False
    assert diff.score_merge_allowed is False
    assert "跨轮" in diff.scores_reason
    assert diff.same_identity is False
    assert "pipeline_version" in {name for name, _left, _right in diff.identity_changes}


def test_diff_between_archives_of_different_pipeline_is_not_comparable(
    tmp_path: Path,
) -> None:
    first_ctx = make_candidate_baseline(tmp_path, run_id="run-b0-pipe-a")
    second_ctx = make_candidate_baseline(
        tmp_path, run_id="run-b0-pipe-b", pipeline_version="pipeline9999"
    )
    first = tmp_path / "candidates" / "pipe-a"
    second = tmp_path / "candidates" / "pipe-b"
    archive_candidate(first_ctx, clean_report(), first)
    archive_candidate(second_ctx, clean_report(), second)

    diff = pr.diff_candidates(first, second)
    assert diff.same_round is True
    assert diff.same_identity is False
    assert diff.scores_comparable is False
    assert diff.score_merge_allowed is False
    assert "不可比" in diff.scores_reason or "pipeline" in diff.scores_reason


# --------------------------------------------------------------------------- #
# B. fail-closed 反例矩阵
# --------------------------------------------------------------------------- #


def test_archive_refuses_approved_source_and_writes_nothing(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path, run_id="run-b0-approved")
    gate = make_gate(0, quality_status="pass", run_id=ctx["run"].manifest.run_id)
    approve_baseline(
        ctx["run"], gate, ctx["root"], approver="owner", reason="fixture: approved source"
    )
    out = tmp_path / "candidates" / "should-not-exist"
    with pytest.raises(pr.CandidateArchiveError, match="已审批"):
        archive_candidate(ctx, clean_report(), out)
    assert not out.exists()


def test_archive_refuses_existing_target_without_touching_it(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path)
    out = tmp_path / "candidates" / "occupied"
    out.mkdir(parents=True)
    marker = out / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(pr.CandidateArchiveError, match="已存在"):
        archive_candidate(ctx, clean_report(), out)
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not any("staging" in item.name for item in out.parent.iterdir())


def test_archive_refuses_holdout_source(tmp_path: Path) -> None:
    cases = candidate_cases()
    rows = [make_row(case, status="pass") for case in cases]
    run = write_run(
        tmp_path,
        "run-b0-holdout",
        rows=rows,
        manifest=make_manifest(run_id="run-b0-holdout", suite="holdout"),
        cases=cases,
    )
    root = tmp_path / "baselines-holdout"
    saved = save_baseline(run, root)
    ctx = {"run": run, "root": root, "baseline": saved}
    out = tmp_path / "candidates" / "holdout"
    with pytest.raises(pr.CandidateArchiveError, match="holdout"):
        archive_candidate(ctx, clean_report(), out)
    assert not out.exists()


def test_report_rejects_private_per_case_payload() -> None:
    payload = clean_report().to_dict()
    payload["questions"] = ["H2-Q-RAW"]
    with pytest.raises(pr.CandidateReportError, match="题干"):
        pr.SplitReport.from_dict(payload)


@pytest.mark.parametrize(
    ("mutate", "keyword"),
    [
        (lambda payload: payload.__setitem__("publishable", True), "publishable"),
        (lambda payload: payload.__setitem__("release_baseline", True), "release_baseline"),
        (lambda payload: payload.__setitem__("gate_approved", True), "gate_approved"),
        (lambda payload: payload.__setitem__("has_approval", True), "has_approval"),
        (
            lambda payload: payload.__setitem__("state", "candidate")
            if payload["state"] == "blocked"
            else payload.__setitem__("state", "blocked"),
            "state",
        ),
        (lambda payload: payload.__setitem__("approved", True), "字段"),
    ],
)
def test_verify_rejects_metadata_upgrade_or_state_flip(
    tmp_path: Path, mutate, keyword: str
) -> None:
    ctx = make_candidate_baseline(tmp_path, run_id="run-b0-tamper-state")
    out = tmp_path / "candidates" / "tamper-state"
    archive_candidate(ctx, real_mirror_report(), out)
    rewrite_manifest(out, mutate)
    with pytest.raises(pr.CandidateArchiveError, match=keyword):
        pr.verify_candidate_archive(out)


def test_verify_rejects_payload_digest_drift(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path)
    out = tmp_path / "candidates" / "tamper-bytes"
    archive_candidate(ctx, clean_report(), out)
    target = out / pr.CANDIDATE_PAYLOAD_DIR / "run" / "cases.jsonl"
    data = bytearray(target.read_bytes())
    data[0] ^= 0xFF
    target.write_bytes(bytes(data))
    with pytest.raises(pr.CandidateArchiveError, match="sha256"):
        pr.verify_candidate_archive(out)


def test_verify_rejects_inner_manifest_path_escape(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path)
    out = tmp_path / "candidates" / "tamper-path"
    archive_candidate(ctx, clean_report(), out)
    inner_manifest_path = out / pr.CANDIDATE_PAYLOAD_DIR / "archive_manifest.json"
    inner = json.loads(inner_manifest_path.read_text(encoding="utf-8"))
    inner["files"][0]["path"] = "run/../../escape.json"
    inner_bytes = (
        json.dumps(inner, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    inner_manifest_path.write_bytes(inner_bytes)
    # 同步篡改 candidate_manifest 的 payload 摘要，确保失败点是路径校验而不是摘要。
    rewrite_manifest(
        out,
        lambda payload: payload["payload"]["files"].__setitem__(
            f"{pr.CANDIDATE_PAYLOAD_DIR}/archive_manifest.json",
            hashlib.sha256(inner_bytes).hexdigest(),
        ),
    )
    with pytest.raises(pr.CandidateArchiveError, match="路径"):
        pr.verify_candidate_archive(out)


def test_verify_rejects_unregistered_extra_file(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path)
    out = tmp_path / "candidates" / "tamper-extra"
    archive_candidate(ctx, clean_report(), out)
    (out / "smuggled.txt").write_text("private", encoding="utf-8")
    with pytest.raises(pr.CandidateArchiveError, match="文件集合"):
        pr.verify_candidate_archive(out)


def test_verify_rejects_missing_artifact(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path)
    out = tmp_path / "candidates" / "missing-artifact"
    archive_candidate(ctx, clean_report(), out)
    (out / pr.CANDIDATE_PAYLOAD_DIR / "run" / "summary.json").unlink()
    with pytest.raises(pr.CandidateArchiveError, match="文件集合"):
        pr.verify_candidate_archive(out)


def test_verify_rejects_report_digest_drift(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path, run_id="run-b0-report-drift")
    out = tmp_path / "candidates" / "report-drift"
    archive_candidate(ctx, clean_report(), out)
    rewrite_manifest(out, lambda payload: payload["report"].__setitem__("title", "被改写"))
    with pytest.raises(pr.CandidateArchiveError, match="摘要"):
        pr.verify_candidate_archive(out)


def test_verify_rejects_reparse_point(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path, run_id="run-b0-junction")
    out = tmp_path / "candidates" / "junction"
    archive_candidate(ctx, clean_report(), out)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("private", encoding="utf-8")
    junction = out / "payload" / "linked"
    if os.name != "nt":
        try:
            os.symlink(outside, junction, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("当前平台不允许创建符号链接/目录联接")
    else:
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(f"当前 Windows 不允许创建目录联接: {completed.stderr or completed.stdout}")
    with pytest.raises(pr.CandidateArchiveError, match="重解析|文件集合"):
        pr.verify_candidate_archive(out)


def test_restore_refuses_formal_registry_root_and_inside_archive(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path)
    out = tmp_path / "candidates" / "restore-guard"
    archive_candidate(ctx, clean_report(), out)

    formal_root = tmp_path / "formal" / "eval" / "baselines"
    with pytest.raises(pr.CandidateArchiveError, match="正式"):
        pr.restore_candidate(out, formal_root, extra_formal_roots=(formal_root,))
    assert not formal_root.exists()

    with pytest.raises(pr.CandidateArchiveError, match="归档目录内部"):
        pr.restore_candidate(out, out / "restored")
    assert not (out / "restored").exists()


def test_restore_refuses_existing_target(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path)
    out = tmp_path / "candidates" / "restore-existing"
    archive_candidate(ctx, clean_report(), out)
    dst_root = tmp_path / "restore-existing" / "baselines"
    pr.restore_candidate(out, dst_root)
    with pytest.raises(pr.CandidateArchiveError, match="已存在"):
        pr.restore_candidate(out, dst_root)


def test_list_rejects_invalid_archive_and_is_sorted(tmp_path: Path) -> None:
    root = tmp_path / "candidates"
    ctx_a = make_candidate_baseline(tmp_path, run_id="run-b0-list-a")
    ctx_b = make_candidate_baseline(
        tmp_path, run_id="run-b0-list-b", pipeline_version="pipeline9999"
    )
    archive_candidate(ctx_b, clean_report(), root / "b")
    archive_candidate(ctx_a, clean_report(), root / "a")
    listing = pr.list_candidates(root)
    assert [item.archive_dir for item in listing] == sorted(
        item.archive_dir for item in listing
    )
    assert len(listing) == 2

    bad = root / "c"
    bad.mkdir()
    (bad / pr.CANDIDATE_FILENAME).write_text("{}", encoding="utf-8")
    with pytest.raises(pr.CandidateArchiveError):
        pr.list_candidates(root)


def test_candidate_flow_never_calls_approve_baseline(tmp_path: Path, monkeypatch) -> None:
    import mktkb.evaluation.baseline as baseline_module

    def _boom(*args, **kwargs):  # noqa: ANN001, ANN002
        raise AssertionError("candidate 流程不得调用 approve_baseline")

    monkeypatch.setattr(baseline_module, "approve_baseline", _boom)
    ctx = make_candidate_baseline(tmp_path, run_id="run-b0-no-approve")
    out = tmp_path / "candidates" / "no-approve"
    archive_candidate(ctx, clean_report(), out)
    restored = pr.restore_candidate(out, tmp_path / "restore-no-approve" / "baselines")
    assert restored.baseline.approval is None
    assert not any(
        path.name == APPROVAL_FILENAME
        for path in tmp_path.rglob(APPROVAL_FILENAME)
        if "restore-no-approve" in path.as_posix() or "candidates" in path.as_posix()
    )


def test_candidate_manifest_identity_is_recomputable(tmp_path: Path) -> None:
    ctx = make_candidate_baseline(tmp_path)
    out = tmp_path / "candidates" / "identity"
    archive_candidate(ctx, clean_report(), out)
    manifest = json.loads((out / pr.CANDIDATE_FILENAME).read_text(encoding="utf-8"))
    identity = BaselineIdentity.from_dict(manifest["identity"])
    assert identity.baseline_id == manifest["baseline_id"] == ctx["baseline"].baseline_id
    assert manifest["run_id"] == ctx["baseline"].run_id
    for rel, sha in manifest["payload"]["files"].items():
        actual = hashlib.sha256((out / rel).read_bytes()).hexdigest()
        assert actual == sha, rel


def test_import_and_report_path_make_zero_external_attempts(tmp_path: Path) -> None:
    """独立解释器只 import 模块并渲染报告：不得出现任何外部 socket/DNS 尝试。"""
    code = """
import sys
sys.path.insert(0, r"{src}")
import socket
attempts = []
def blocked(*args, **kwargs):
    attempts.append(("socket", args[:1]))
    raise RuntimeError("T209-PREP guard: external network is forbidden")
socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socket.connect = blocked
import mktkb.evaluation.p2_candidate_report as pr
print("IMPORTOK", pr.REPORT_SCHEMA_VERSION)
print("ATTEMPTS", len(attempts))
assert attempts == [], attempts
""".format(src=str(Path(__file__).resolve().parents[2] / "src"))
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[3]),
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "IMPORTOK" in completed.stdout
    assert "ATTEMPTS 0" in completed.stdout
