"""T209-PREP 证据：用公开安全聚合的合成镜像渲染分列报告（零真实调用）。

只使用任务书/real-h2.md 已公开的计数（30/19/11/2/27 等），不读取真实逐题材料。
输出 Markdown 供 dev-report 引用；同时打印关键断言，便于机器核对。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_candidate_report as pr  # noqa: E402

ROUND = "P2-T207-H2-20261114-r1"


def card() -> dict:
    return {
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
        "hard_evidence": {
            "axes": {
                "safety": {
                    "planned": 30,
                    "passed": 1,
                    "not_applicable": 24,
                    "unknown": 3,
                    "violations": 2,
                },
                "cross_user": {
                    "planned": 30,
                    "passed": 27,
                    "not_applicable": 0,
                    "unknown": 3,
                    "violations": 0,
                },
                "cross_entity": {
                    "planned": 30,
                    "passed": 3,
                    "not_applicable": 0,
                    "unknown": 27,
                    "violations": 0,
                },
                "stale_source": {
                    "planned": 30,
                    "passed": 25,
                    "not_applicable": 0,
                    "unknown": 5,
                    "violations": 0,
                },
            },
            "missing_evidence_cases": 27,
            "verified": False,
        },
    }


def build_report() -> pr.SplitReport:
    quality, evidence = pr.parse_card(
        card(),
        round_id=ROUND,
        scenario_verifications=(
            ("r0", False),
            ("r1", False),
            ("r2", False),
            ("r3", True),
        ),
        thresholds_approved=False,
        unknown_reasons={
            "safety": "undetermined",
            "cross_user": "undetermined",
            "cross_entity": "real_scope_targets_contract_not_generated",
            "stale_source": "undetermined",
        },
    )
    return pr.build_split_report(
        reference=pr.ReferenceSource.create(
            source_kind="real-h2-aggregate",
            document="docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/real-h2.md",
            plan_id=ROUND,
            code_version="f6c118432a73aa2541c78b9b33c08314bee462b1e1aa70c4391933625b2892ea",
            config_sha256="9cb322863939522d5defb948b8739dd9385a3bf219c7291c5d1e916de3efbd65",
            binding_sha256="291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4",
        ),
        execution=pr.build_execution(
            round_id=ROUND,
            runs=(
                pr.RunOutcome("r0", "base_b0", "succeeded", 26, 32),
                pr.RunOutcome("r1", "base_b0_plus_v01", "succeeded", 1, 1),
                pr.RunOutcome("r2", "pre_v05_without_v07", "succeeded", 2, 2),
                pr.RunOutcome("r3", "post_v05_without_v01", "succeeded", 1, 1),
            ),
        ),
        quality=quality,
        evidence=evidence,
        soft=(
            pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="真实 judge 未授权"),
            pr.SoftStatus.unknown(
                "auxiliary", recorded_status="unavailable", detail="辅助评分未执行"
            ),
        ),
        funding=pr.FundingStatus.create(
            ledger_current_sha256="ca9dceb9019790eb6ba4e25cfaf88232915b607d756d0eae21ad7cdf10c6fec9",
            ledger_previous_sha256="4d80d776bcf25079817f5f7dd8863037c27bc01971b6fa0fe239b432ee55fcc6",
            ledger_change_cause="legitimate_spend",
            go_current_sha256="c72dc7abf6ba135fb6c53f77c35b40dda34e97cf535d3be212467c6734b27324",
            go_archived_sha256="f688ec7efb7e8ddc145ae9fd593a482a85a6e4a764a9d49a09eab4f3fc26ea98",
            archived_line_moment="2026-11-14 真实 H2 执行前归档（f688…）",
        ),
    )


def main() -> int:
    report = build_report()
    text = pr.render_split_markdown(report)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out is not None:
        out.write_text(text, encoding="utf-8")
    print(f"execution_status={report.execution.status}")
    print(f"quality_status={report.quality.status} passed={report.quality.passed}/{report.quality.total}")
    print(f"safety_violations={report.quality.safety_violations}")
    print(f"threshold_met={report.quality.threshold_met} verified={report.quality.verified} "
          f"release_ready={report.quality.release_ready}")
    print(f"missing_evidence_cases={report.evidence.missing_evidence_cases}")
    print(f"cross_entity_unknown={report.evidence.axes[2].unknown}")
    print(f"soft={[item.status for item in report.soft]}")
    print(f"publication_publishable={report.publication['publishable']}")
    assert report.execution.status == "succeeded"
    assert report.quality.status == "fail"
    assert report.quality.threshold_met is False and report.quality.verified is False
    assert report.quality.release_ready is False
    assert report.evidence.missing_evidence_cases == 27
    assert "27 是缺失证据题数，不是 27 题答错" in text
    assert "不外推整体" in text
    assert "release_ready: false" in text
    assert "overall_success" not in text and "总体通过" not in text
    print("report_example=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
