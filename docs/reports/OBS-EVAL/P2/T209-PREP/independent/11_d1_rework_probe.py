"""T209-PREP D1 定向返工独立复验（round 2）。

只使用模块公开 API，独立构造执行状态：
1. 4 run 全 failed → failed（不再 not_run）；failed 枚举可达；
2. 2 succeeded + 2 failed → partial；全部 not_run → not_run；0 run → not_run；
3. 全部 succeeded → succeeded（原语义不变）；
4. to_dict / from_dict canonical 往返保留每个状态（含空 runs）；
5. 渲染：failed 显示“执行失败”，partial/not_run/succeeded 文案与枚举一致；
   failed 报告不得出现“状态: not_run”；仍无 overall/ready 字段。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend/src"))

from mktkb.evaluation import p2_candidate_report as pr  # noqa: E402

ROUND = "T209P-INDEP-D1-ROUND"
RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def outcomes(status: str, count: int) -> tuple[pr.RunOutcome, ...]:
    return tuple(
        pr.RunOutcome(
            f"{status}-{index}", "synthetic", status, 1, 1,
            errors=1 if status == "failed" else 0,
        )
        for index in range(1, count + 1)
    )


def build(runs) -> pr.ExecutionStatus:
    return pr.build_execution(round_id=ROUND, runs=runs)


def report_for(execution: pr.ExecutionStatus) -> pr.SplitReport:
    axes = tuple(
        pr.AxisEvidence.create(axis=axis, planned=30, passed=30, not_applicable=0, unknown=0, violations=0)
        for axis in pr.AXES
    )
    return pr.build_split_report(
        reference=pr.ReferenceSource.create(
            source_kind="synthetic-mirror",
            document="docs/reports/OBS-EVAL/P2/T209-PREP/independent/mirror.json",
            plan_id=ROUND, code_version="synthetic",
        ),
        execution=execution,
        quality=pr.build_quality(
            round_id=ROUND, total=30, passed=30, failed=0, errors=0, safety_violations=0,
            min_pass=24, thresholds_approved=False, verified=True,
            scenario_verifications=(("s0", True),),
        ),
        evidence=pr.build_evidence(
            round_id=ROUND, total=30, missing_evidence_cases=0, axes=axes, verified=True
        ),
        soft=(pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="synthetic"),),
        funding=pr.FundingStatus.create(
            ledger_current_sha256="1" * 64, ledger_previous_sha256="2" * 64,
            ledger_change_cause="legitimate_spend", go_current_sha256="3" * 64,
            go_archived_sha256="4" * 64, archived_line_moment="synthetic",
        ),
    )


def main() -> int:
    cases = (
        ("all-failed-4", outcomes("failed", 4), "failed"),
        ("mixed-2-2", (*outcomes("succeeded", 2), *outcomes("failed", 2)), "partial"),
        ("all-not_run", outcomes("not_run", 2), "not_run"),
        ("zero-run", (), "not_run"),
        ("all-succeeded", outcomes("succeeded", 4), "succeeded"),
        ("succeeded+not_run", (*outcomes("succeeded", 1), *outcomes("not_run", 1)), "partial"),
    )
    for name, runs, expected in cases:
        execution = build(runs)
        check(execution.status == expected, f"D1-{name} status={expected}", execution.status)
        payload = execution.to_dict()
        check(payload["status"] == expected, f"D1-{name} to_dict status 一致", str(payload["status"]))
        try:
            rebuilt = pr.build_execution(
                round_id=payload["round_id"],
                runs=[pr.RunOutcome.from_dict(item) for item in payload["runs"]],
            )
        except Exception as exc:  # noqa: BLE001
            check(False, f"D1-{name} from_dict 可重建", f"{type(exc).__name__}: {exc}")
        else:
            check(rebuilt.status == expected and rebuilt.to_dict() == payload, f"D1-{name} from_dict canonical 往返")

    failed = build(outcomes("failed", 4))
    check(failed.failed_runs == 4 and failed.succeeded_runs == 0, "D1 failed_runs=4 / succeeded_runs=0")
    check(failed.total_errors == 4, "D1 failed 报告保留 errors=4")
    empty = build(())
    check(empty.status == "not_run" and empty.failed_runs == 0 and empty.succeeded_runs == 0, "D1 0 run→not_run")
    check(empty.runs == () and empty.total_questions == 0, "D1 0 run 空数组保留")

    # 渲染与枚举一致
    labels = {
        "succeeded": "执行成功",
        "failed": "执行失败",
        "partial": "执行部分完成",
        "not_run": "未执行/未开始",
    }
    for name, runs, status in cases:
        text = pr.render_split_markdown(report_for(build(runs)))
        check(f"状态: {status}（{labels[status]}" in text, f"D1-render-{name} 文案与枚举一致")
        check("聚合映射" in text, f"D1-render-{name} 含聚合映射说明")
        report_payload = report_for(build(runs)).to_dict()
        check(report_payload["axes"][0]["status"] == status, f"D1-render-{name} axes[0].status 一致")
        check("overall" not in report_payload and "overall_success" not in report_payload, f"D1-render-{name} 无 overall 字段")
    failed_text = pr.render_split_markdown(report_for(failed))
    check("状态: not_run" not in failed_text, "D1 failed 报告不出现“状态: not_run”")
    check("状态: failed（执行失败" in failed_text, "D1 failed 报告显式“执行失败”")

    # 失败输入仍 fail-closed（未被放宽）
    try:
        pr.build_execution(round_id=ROUND, runs="not-a-list")
    except pr.CandidateReportError as exc:
        check("数组" in str(exc), "D1 非数组 runs 仍拒绝", str(exc))
    else:
        check(False, "D1 非数组 runs 仍拒绝", "not rejected")
    try:
        pr.build_execution(round_id=ROUND, runs=(pr.RunOutcome("r", "s", "bogus", 1, 1),))
    except pr.CandidateReportError as exc:
        check("status" in str(exc), "D1 非法 run status 仍拒绝", str(exc))
    else:
        check(False, "D1 非法 run status 仍拒绝", "not rejected")

    failed_checks = [name for ok, name, _ in RESULTS if not ok]
    print(f"\nchecks={len(RESULTS)} failed={len(failed_checks)}")
    print("RESULT=" + ("PASS" if not failed_checks else "FAIL"))
    for name in failed_checks:
        print("FAILED_CHECK=" + name)
    return 0 if not failed_checks else 1


if __name__ == "__main__":
    raise SystemExit(main())
