"""Offline regressions for consuming P2 scorecard aggregates."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from mktkb.evaluation import p2_candidate_report as report
from mktkb.evaluation.p2_engineering_report import build_engineering_report
from mktkb.evaluation.p2_score_run import score_run
from mktkb.evaluation.p2_scoring import P2_B0_IDS, P2CaseScore, score_public_suites

from .test_p2_candidate_report import (
    ROUND,
    archive_candidate,
    clean_report,
    make_candidate_baseline,
    real_mirror_card,
    real_mirror_report,
    real_mirror_unknown_reasons,
    t09_network_guard,  # noqa: F401 (pytest fixture)
)
from .test_p2_gate import make_case, public_card


pytestmark = pytest.mark.usefixtures("t09_network_guard")


@pytest.fixture
def overlapping_axes_card() -> dict:
    card = real_mirror_card()
    card["hard_failures_by_kind"]["cross_user"] = 1
    cross_user = card["hard_evidence"]["axes"]["cross_user"]
    cross_user["passed"] -= 1
    cross_user["violations"] += 1
    return card


@pytest.mark.parametrize("union", [2, 3])
def test_overlapping_axes_allow_union_between_largest_axis_and_sum(overlapping_axes_card, union):
    overlapping_axes_card["hard_failures"] = union
    quality, evidence = report.parse_card(
        overlapping_axes_card, round_id=ROUND, unknown_reasons=real_mirror_unknown_reasons()
    )

    assert quality.safety_violations == 2
    assert quality.status == "fail"
    assert quality.release_ready is False
    assert evidence.violation_total == 3
    assert evidence.unknown_total == 38


@pytest.mark.parametrize("union", [1, 4, 31, True])
def test_impossible_hard_failure_union_is_rejected(overlapping_axes_card, union):
    overlapping_axes_card["hard_failures"] = union

    with pytest.raises(report.CandidateReportError, match=r"card\.hard_failures"):
        report.parse_card(
            overlapping_axes_card, round_id=ROUND, unknown_reasons=real_mirror_unknown_reasons()
        )


def test_each_hard_failure_kind_must_match_its_axis(overlapping_axes_card):
    overlapping_axes_card["hard_failures"] = 3
    overlapping_axes_card["hard_failures_by_kind"]["cross_user"] = 0
    overlapping_axes_card["hard_failures_by_kind"]["cross_entity"] = 1

    with pytest.raises(report.CandidateReportError, match=r"hard_failures_by_kind\.cross_user"):
        report.parse_card(
            overlapping_axes_card, round_id=ROUND, unknown_reasons=real_mirror_unknown_reasons()
        )


def test_nonoverlapping_historical_shape_is_still_accepted():
    quality, evidence = report.parse_card(
        real_mirror_card(), round_id=ROUND, unknown_reasons=real_mirror_unknown_reasons()
    )

    assert quality.passed == 19
    assert quality.safety_violations == evidence.violation_total == 2
    assert not evidence.verified


def test_nested_hard_failure_counts_must_match_axis_counts(overlapping_axes_card):
    overlapping_axes_card["hard_failures"] = 3
    overlapping_axes_card["hard_evidence"]["hard_failures_by_kind"] = {
        **overlapping_axes_card["hard_failures_by_kind"], "cross_user": 0
    }

    with pytest.raises(report.CandidateReportError, match=r"hard_evidence\.hard_failures_by_kind"):
        report.parse_card(
            overlapping_axes_card, round_id=ROUND, unknown_reasons=real_mirror_unknown_reasons()
        )


@pytest.fixture
def report_inputs():
    binding = "a" * 64
    public = public_card(run_id="public-1", config_hash=binding)
    manifest = {"run_id": "public-1", "config_hash": binding, "execution": "dry_run"}
    u_run = {"run_id": "public-u", "config_hash": "b" * 64, "execution_mode": "live", "real_calls": 1}
    u_matrix = {
        "u_table": [
            {"case_id": "U01", "basis": "R", "status": "pass", "run_id": "public-u", "source": "smoke"},
            {"case_id": "U02", "basis": "L", "status": "fail", "run_id": None, "source": "local-controls"},
        ],
        "runs": [u_run],
        "cases": [{**u_run, "case_id": "U01", "status": "pass"}],
    }
    return {
        "public": public,
        "public_manifest": manifest,
        "u_matrix": u_matrix,
        "holdout": real_mirror_report(),
        "ragas": {
            "run_id": "judge-1", "plan_sha256": "c" * 64, "status": "scored",
            "counts": {"scored": 4, "unknown": 1, "expected_refusal": 1},
            "metrics": {"faithfulness": 0.75, "factual_correctness": 0.75},
        },
        "measurements": [
            {
                "run_id": "public-1", "config_hash": binding, "scope": "answer_turns",
                "sample": 32, "eligible": 40, "p95_latency_ms": 12.5,
                "prompt_tokens": 360, "completion_tokens": 79,
                "conservative_held_cny": 0.5, "provider_usage_estimate_cny": None,
            }
        ],
    }


def test_engineering_report_keeps_each_source_and_denominator_separate(report_inputs):
    observations = build_engineering_report(**report_inputs)

    assert observations["publishable"] is False
    assert observations["public"]["run_id"] == "public-1"
    assert observations["public"]["b0"]["passed"] == 40
    assert observations["public"]["exact"] == {"planned": 24, "passed": 24}
    assert observations["public"]["ocr"] == {"planned": 8, "executed": 8, "passed": 8}
    assert observations["public"]["negative"]["passed"] == 8
    assert observations["public"]["boundary"]["passed"] == 6
    assert observations["u"]["R"]["passed"] == 1
    assert observations["u"]["R"]["source"]["run_id"] == "public-u"
    assert observations["u"]["L"]["failed"] == 1
    assert observations["u"]["L"]["missing"] == 8
    assert observations["holdout"]["round_id"] == ROUND
    assert observations["holdout"]["unknown_total"] == 38
    assert observations["ragas"]["run_id"] == "judge-1"
    assert observations["ragas"]["metrics"]["faithfulness"] == 0.75
    assert observations["runtime"]["answer_turns"]["coverage"] == "partial"
    assert observations["runtime"]["answer_turns"]["provider_usage_estimate_cny"] is None
    assert observations["runtime"]["all_attempts"]["coverage"] == "unknown"


@pytest.mark.parametrize(
    ("bad_input", "message"),
    [
        ("scorecard", "public scorecard"),
        ("scorecard_mock_as_live", "public scorecard"),
        ("u_mock", "U01"),
        ("u_zero_calls", "U01"),
        ("u_duplicate", "U 证据"),
        ("u_malformed", "U 证据"),
        ("runtime_other_run", "runtime"),
        ("runtime_sample", "sample"),
        ("runtime_zero_with_p95", "sample"),
        ("runtime_cost", "conservative"),
        ("ragas_nan", "faithfulness"),
        ("ragas_private_field", "ragas"),
    ],
)
def test_engineering_report_rejects_incompatible_or_invalid_inputs(report_inputs, bad_input, message):
    if bad_input == "scorecard":
        report_inputs["public_manifest"]["config_hash"] = "d" * 64
    elif bad_input == "scorecard_mock_as_live":
        report_inputs["public_manifest"]["execution"] = "live"
    elif bad_input == "u_mock":
        report_inputs["u_matrix"]["runs"][0]["execution_mode"] = "local_mock"
    elif bad_input == "u_zero_calls":
        report_inputs["u_matrix"]["runs"][0]["real_calls"] = 0
    elif bad_input == "u_duplicate":
        report_inputs["u_matrix"]["cases"][0]["duplicated_in"] = ["public-u-2"]
    elif bad_input == "u_malformed":
        report_inputs["u_matrix"]["u_table"] = "not a list"
    elif bad_input == "runtime_other_run":
        report_inputs["measurements"][0]["run_id"] = "public-2"
    elif bad_input == "runtime_sample":
        report_inputs["measurements"][0]["sample"] = 41
    elif bad_input == "runtime_zero_with_p95":
        report_inputs["measurements"][0]["sample"] = 0
    elif bad_input == "runtime_cost":
        report_inputs["measurements"][0]["provider_usage_estimate_cny"] = 1
    elif bad_input == "ragas_nan":
        report_inputs["ragas"]["metrics"]["faithfulness"] = float("nan")
    elif bad_input == "ragas_private_field":
        report_inputs["ragas"]["question"] = "private sentinel"

    with pytest.raises(report.CandidateReportError, match=message):
        build_engineering_report(**report_inputs)


def test_restored_e2_candidate_can_supply_holdout_without_changing_archive(tmp_path, report_inputs):
    archive_dir = tmp_path / "candidate"
    archive_candidate(make_candidate_baseline(tmp_path), clean_report(), archive_dir)
    manifest = archive_dir / report.CANDIDATE_FILENAME
    before = manifest.read_bytes()
    verified = report.verify_candidate_archive(archive_dir)
    restored = report.restore_candidate(archive_dir, tmp_path / "restored")
    assert manifest.read_bytes() == before
    assert verified.report == restored.report
    observations = build_engineering_report(
        public=report_inputs["public"], public_manifest=report_inputs["public_manifest"],
        holdout=restored.report,
    )

    assert not restored.publishable and observations["publishable"] is False
    assert observations["holdout"]["passed"] == 30
    assert observations["ragas"]["status"] == "unknown"
    assert observations["runtime"]["answer_turns"]["sample"] is None


@pytest.mark.parametrize("changes", [
    {"exact_passed": 0},
    {"ocr_passed": 0},
    {"executed": 38, "passed": 32, "failed": 6, "not_executed": 2, "ocr_executed": 5, "ocr_passed": 0},
    {"executed": 34, "passed": 32, "failed": 2, "not_executed": 6, "ocr_executed": 5, "ocr_passed": 2},
    {"passed": 24, "failed": 16},
    {"passed": 35, "failed": 5, "exact_passed": 20, "ocr_passed": 6},
    {"exact_passed": True},
    {"ocr_executed": True},
    {"ocr_passed": True},
])
def test_b0_subsets_must_fit_parent_counts(report_inputs, changes):
    public = report_inputs["public"]
    report_inputs["public"] = replace(public, suites={**public.suites, "b0": replace(public.suites["b0"], **changes)})

    with pytest.raises(report.CandidateReportError, match=r"(子分母|public\.(exact|ocr))"):
        build_engineering_report(**report_inputs)


@pytest.mark.parametrize("changes", [
    {"passed": 38, "failed": 2, "ocr_passed": 7},
    {"executed": 37, "passed": 34, "failed": 3, "not_executed": 3, "ocr_executed": 5, "ocr_passed": 2},
])
def test_historical_and_partial_b0_subsets_are_reported(report_inputs, changes):
    public = report_inputs["public"]
    report_inputs["public"] = replace(public, suites={**public.suites, "b0": replace(public.suites["b0"], **changes)})

    observations = build_engineering_report(**report_inputs)

    assert observations["public"]["b0"]["passed"] == changes["passed"]
    assert observations["public"]["ocr"]["passed"] == changes["ocr_passed"]


@pytest.mark.parametrize("real_calls", [0, 12])
def test_public_report_discloses_scorecard_real_calls_without_claiming_release(report_inputs, real_calls):
    report_inputs["public"] = replace(report_inputs["public"], execution_mode="live", real_calls=real_calls)
    report_inputs["public_manifest"]["execution"] = "live"

    observations = build_engineering_report(**report_inputs)

    assert observations["public"]["scorecard_real_calls"] == real_calls
    assert observations["publishable"] is False


@pytest.mark.parametrize("real_calls", [1.25, -0.5])
def test_public_report_rejects_invalid_accumulated_case_calls(report_inputs, real_calls):
    manifest = report_inputs["public_manifest"]
    manifest["execution"] = "live"
    score = P2CaseScore(P2_B0_IDS[0], "b0", "exact", "pass", False, 1, 1,
                        execution_mode="live", real_calls=real_calls)
    report_inputs["public"] = score_public_suites(
        [score], run_id=manifest["run_id"], config_hash=manifest["config_hash"],
    )

    with pytest.raises(report.CandidateReportError, match=r"public\.scorecard_real_calls"):
        build_engineering_report(**report_inputs)


@pytest.mark.parametrize("real_calls", [True, "7"])
def test_public_report_rejects_noninteger_scorecard_calls(report_inputs, real_calls):
    report_inputs["public"] = replace(report_inputs["public"], execution_mode="live", real_calls=real_calls)
    report_inputs["public_manifest"]["execution"] = "live"

    with pytest.raises(report.CandidateReportError, match=r"public\.scorecard_real_calls"):
        build_engineering_report(**report_inputs)


def test_public_report_keeps_scorecard_calls_distinct_from_run_outbound_attempts(tmp_path, report_inputs):
    manifest = {**report_inputs["public_manifest"], "execution": "live", "case_count": 1}
    (tmp_path / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "cases.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "summary.json").write_text(
        '{"network":{"available":true,"outbound_attempts":13},"attempts":{"reserved":17}}',
        encoding="utf-8",
    )

    run = score_run(tmp_path, cases=(make_case(P2_B0_IDS[0]),), document_codes={})
    observations = build_engineering_report(public=run.scorecard, public_manifest=manifest)

    assert run.real_calls == 13
    assert observations["public"]["scorecard_real_calls"] == 0
