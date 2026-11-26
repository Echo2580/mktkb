"""T209-PREP 独立验收：报告分列 / 口径反例（合成镜像 A + 对照 B）。

完全独立构造：只用公开计数与模块公开 API，不调用开发测试的任何断言或夹具。
检查项：
A. 合成镜像（四 run succeeded、30/36、19/30、11 fail、2 safety、27 missing、
   cross_entity 27 unknown）：执行/质量/证据/软评分/资金分列，无 overall/ready。
B. 对照（24/30、0 hard failure、缺 scope、软评分 NOT-RUN）：执行成功不掩盖质量
   not_ready；not_ready 不等于 fail 也不等于 ready。
C. 口径反例：单 scenario verified 不外推；缺 scope 不写成 27 题答错；
   recorded_status 不冒充 rescored；跨轮/跨 pipeline/跨 scope 不合并；
   release_ready=true / detail_export=true 拒绝；题干/标签/逐题字段拒绝；
   额外 overall_success/ready 字段拒绝。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend/src"))

from mktkb.evaluation import p2_candidate_report as pr  # noqa: E402

ROUND = "P2-T209P-INDEP-ROUND-A"
ROUND_B = "P2-T209P-INDEP-ROUND-B"
OTHER = "P2-T209P-INDEP-ROUND-OTHER"
RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def expect_error(fn, *, needle: str, name: str) -> None:
    try:
        fn()
    except pr.CandidateReportError as exc:
        ok = needle in str(exc)
        check(ok, name, f"rejected={exc}" if ok else f"wrong reason: {exc}")
    except Exception as exc:  # noqa: BLE001
        check(False, name, f"unexpected {type(exc).__name__}: {exc}")
    else:
        check(False, name, "not rejected")


def card_a() -> dict:
    """公开安全聚合计数（real-h2.md 已公开值）的合成镜像卡。"""
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
                "safety": {"planned": 30, "checked": 27, "passed": 1, "not_applicable": 24, "unknown": 3, "violations": 2},
                "cross_user": {"planned": 30, "checked": 27, "passed": 27, "not_applicable": 0, "unknown": 3, "violations": 0},
                "cross_entity": {"planned": 30, "checked": 3, "passed": 3, "not_applicable": 0, "unknown": 27, "violations": 0},
                "stale_source": {"planned": 30, "checked": 25, "passed": 25, "not_applicable": 0, "unknown": 5, "violations": 0},
            },
            "missing_evidence_cases": 27,
            "verified": False,
        },
    }


def funding() -> pr.FundingStatus:
    return pr.FundingStatus.create(
        ledger_current_sha256="ca9dceb9019790eb6ba4e25cfaf88232915b607d756d0eae21ad7cdf10c6fec9",
        ledger_previous_sha256="4d80d776bcf25079817f5f7dd8863037c27bc01971b6fa0fe239b432ee55fcc6",
        ledger_change_cause="legitimate_spend",
        go_current_sha256="c72dc7abf6ba135fb6c53f77c35b40dda34e97cf535d3be212467c6734b27324",
        go_archived_sha256="f688ec7efb7e8ddc145ae9fd593a482a85a6e4a764a9d49a09eab4f3fc26ea98",
        archived_line_moment="2026-11-14 real H2 pre-run archive",
    )


def reference(round_id: str = ROUND, *, doc: str = "", code: str = "synthetic") -> pr.ReferenceSource:
    return pr.ReferenceSource.create(
        source_kind="synthetic-mirror",
        document=doc or "docs/reports/OBS-EVAL/P2/T209-PREP/independent/mirror.json",
        plan_id=round_id,
        code_version=code,
    )


def report_a() -> pr.SplitReport:
    quality, evidence = pr.parse_card(
        card_a(),
        round_id=ROUND,
        scenario_verifications=(("r0", False), ("r1", False), ("r2", False), ("r3", True)),
        thresholds_approved=False,
        unknown_reasons={
            "safety": "undetermined",
            "cross_user": "undetermined",
            "cross_entity": "real_scope_targets_contract_not_generated",
            "stale_source": "undetermined",
        },
    )
    return pr.build_split_report(
        reference=reference(ROUND),
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
            pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="no real judge authorized"),
            pr.SoftStatus.unknown("auxiliary", recorded_status="unavailable", detail="aux not run"),
        ),
        funding=funding(),
    )


def report_b() -> pr.SplitReport:
    """24/30、0 hard failure、24 阈值达标但未审批 + 6 缺 scope + 软评分 NOT-RUN。"""
    quality = pr.build_quality(
        round_id=ROUND_B,
        total=30,
        passed=24,
        failed=6,
        errors=0,
        safety_violations=0,
        min_pass=24,
        thresholds_approved=False,
        verified=False,
        scenario_verifications=(("s0", False), ("s1", False)),
    )
    axes = (
        pr.AxisEvidence.create(axis="safety", planned=30, passed=24, not_applicable=6, unknown=0, violations=0),
        pr.AxisEvidence.create(axis="cross_user", planned=30, passed=24, not_applicable=6, unknown=0, violations=0),
        pr.AxisEvidence.create(
            axis="cross_entity",
            planned=30,
            passed=24,
            not_applicable=0,
            unknown=6,
            violations=0,
            unknown_reason="real_scope_targets_contract_not_generated",
        ),
        pr.AxisEvidence.create(axis="stale_source", planned=30, passed=24, not_applicable=6, unknown=0, violations=0),
    )
    evidence = pr.build_evidence(
        round_id=ROUND_B, total=30, missing_evidence_cases=6, axes=axes, verified=False
    )
    return pr.build_split_report(
        reference=reference(ROUND_B),
        execution=pr.build_execution(
            round_id=ROUND_B,
            runs=(pr.RunOutcome("s0", "synthetic", "succeeded", 30, 30),),
        ),
        quality=quality,
        evidence=evidence,
        soft=(pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="soft not run"),),
        funding=funding(),
    )


def walk_keys(value, prefix="") -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            keys.append(f"{prefix}.{key}" if prefix else str(key))
            keys.extend(walk_keys(item, f"{prefix}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            keys.extend(walk_keys(item, f"{prefix}[{index}]"))
    return keys


def main() -> int:
    a = report_a()
    b = report_b()

    # ---------- A. 分列与无 overall ----------
    data = a.to_dict()
    check(data["report_kind"] == "split_axes", "A1 report_kind=split_axes")
    check(
        [item["axis"] for item in data["axes"]] == ["execution", "quality", "evidence", "soft", "funding"],
        "A2 五轴固定顺序且分列",
        str([item["status"] for item in data["axes"]]),
    )
    top = set(data)
    forbidden_top = {"overall", "overall_success", "overall_status", "ready", "success", "production_ready"}
    check(not (top & forbidden_top), "A3 顶层无 overall/ready/success 字段", str(sorted(top)))
    all_keys = walk_keys(data)
    bad_keys = [
        key
        for key in all_keys
        if key.split(".")[-1].split("[")[0] in {"overall", "overall_success", "overall_ready", "ready", "production_ready"}
    ]
    check(not bad_keys, "A4 递归无 overall/ready 字段", str(bad_keys[:5]))
    check(a.execution.status == "succeeded" and a.execution.succeeded_runs == 4, "A5 四 run 执行 succeeded")
    check(
        a.execution.total_questions == 30 and a.execution.total_turns == 36,
        "A6 30 题 / 36 回合",
        f"{a.execution.total_questions}/{a.execution.total_turns}",
    )
    check(
        a.quality.status == "fail" and a.quality.passed == 19 and a.quality.failed == 11,
        "A7 质量 FAIL 19/30、11 fail",
        a.quality.status,
    )
    check(a.quality.safety_violations == 2 and a.quality.threshold_met is False, "A8 2 safety / threshold_met=false")
    check(a.quality.verified is False and a.quality.release_ready is False, "A9 verified=false / release_ready=false")
    check(a.evidence.missing_evidence_cases == 27, "A10 missing_evidence_cases=27")
    cross = {item.axis: item for item in a.evidence.axes}["cross_entity"]
    check(cross.unknown == 27 and cross.unknown_reason == "real_scope_targets_contract_not_generated", "A11 cross_entity 27 unknown 且原因=scope 合同未生成")
    check(a.evidence.unknown_total == 38 and a.evidence.violation_total == 2, "A12 四轴 unknown 合计 38 / 违例 2", f"{a.evidence.unknown_total}/{a.evidence.violation_total}")
    check(a.axes[0]["status"] == "succeeded" and a.axes[1]["status"] == "fail" and a.axes[2]["status"] == "incomplete", "A13 轴状态分列（succeeded/fail/incomplete）")
    check(a.axes[3]["status"] == "unknown", "A14 软评分轴 unknown（NOT-RUN + UNKNOWN）")
    check(a.publication["publishable"] is False and a.publication["release_baseline"] is False and a.publication["gate_approved"] is False, "A15 publication 三项 false")

    text = pr.render_split_markdown(a)
    for needle in ("执行状态", "质量状态", "证据状态", "软评分状态", "资金与版本", "19/30", "threshold_met: false", "release_ready: false"):
        check(needle in text, f"A16 渲染含 {needle}")
    check("不合成" in text and "不代表质量" in text, "A17 渲染声明分列/执行不代表质量")
    for banned in ("总体通过", "全部通过", "overall_success", "release_ready: true", "production_ready", "REAL_READY"):
        check(banned not in text, f"A18 渲染不含 {banned}")

    # ---------- B. 对照：24/30 + 0 hard failure + 缺 scope + 软评分 NOT-RUN ----------
    check(b.execution.status == "succeeded", "B1 对照执行 succeeded")
    check(b.quality.threshold_met is True and b.quality.passed == 24, "B2 对照 24/30 阈值数值达标")
    check(b.quality.status == "not_ready", "B3 对照质量=not_ready（未审批，不是 pass）", b.quality.status)
    check(b.quality.release_ready is False and b.quality.verified is False, "B4 对照 verified=false / release_ready=false")
    check(b.evidence.missing_evidence_cases == 6 and b.axes[2]["status"] == "incomplete", "B5 对照证据 incomplete（缺 scope 6）")
    check(b.soft[0].status == "not_run", "B6 对照软评分 NOT-RUN")
    check(b.quality.status != "pass" and b.quality.status != "fail", "B7 not_ready 既不冒充 pass 也不混为 fail")
    text_b = pr.render_split_markdown(b)
    check("NOT_READY" in text_b and "24/30" in text_b, "B8 对照渲染 NOT_READY + 24/30")
    check("threshold_met: true" in text_b and "thresholds_approved: false" in text_b, "B9 对照区分 threshold_met 与 thresholds_approved")

    # ---------- C. 口径反例 ----------
    try:
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
    except pr.CandidateReportError as exc:
        check("外推" in str(exc), "C1 单 scenario verified=true 不得外推整体", str(exc))
    else:
        check(False, "C1 单 scenario verified=true 不得外推整体", "not rejected")

    check(a.quality.failed == 11 and a.evidence.missing_evidence_cases == 27, "C2 11 fail 与 27 缺证据是两个数")
    check("27 是缺失证据题数，不是 27 题答错" in text, "C3 渲染明确缺 scope 不等于答错")
    check("unknown（不可判）不是答错" in text, "C4 渲染明确 unknown 不是答错")
    check("四轴 unknown 合计是「轴×题」计数" in text, "C5 渲染明确 38 是轴×题计数")

    try:
        pr.SoftStatus.create(
            name="ragas", status="unknown", recorded_status="ok", detail="x",
            rescored=True, rescored_scores={}, rescored_reason="",
        )
    except pr.CandidateReportError as exc:
        check("rescored" in str(exc), "C6 recorded_status 不得冒充 rescored（无分数被拒）", str(exc))
    else:
        check(False, "C6 recorded_status 不得冒充 rescored", "not rejected")
    scored = pr.SoftStatus.create(
        name="ragas", status="scored", recorded_status="ok", detail="x",
        rescored=True, rescored_scores={"faithfulness": 0.9}, rescored_reason="independent rescore",
    )
    check(scored.rescored is True and scored.rescored_scores["faithfulness"] == 0.9, "C7 合法 rescored 需分数+原因")
    check("rescored=true（原因: independent rescore）" in pr.render_split_markdown(
        pr.build_split_report(
            reference=reference(ROUND), execution=a.execution, quality=a.quality,
            evidence=a.evidence, soft=(scored,), funding=funding(),
        )
    ), "C8 rescored 报告显式打印原因")

    expect_error(
        lambda: pr.build_split_report(
            reference=reference(OTHER),
            execution=a.execution,
            quality=pr.build_quality(
                round_id=OTHER, total=30, passed=19, failed=11, errors=0, safety_violations=2,
                min_pass=24, thresholds_approved=False, verified=False,
                scenario_verifications=(("r0", False),),
            ),
            evidence=pr.build_evidence(
                round_id=OTHER, total=30, missing_evidence_cases=27,
                axes=tuple(
                    pr.AxisEvidence.create(
                        axis=name, planned=30, **{
                            "safety": {"passed": 1, "not_applicable": 24, "unknown": 3, "violations": 2, "unknown_reason": "undetermined"},
                            "cross_user": {"passed": 27, "not_applicable": 0, "unknown": 3, "violations": 0, "unknown_reason": "undetermined"},
                            "cross_entity": {"passed": 3, "not_applicable": 0, "unknown": 27, "violations": 0, "unknown_reason": "real_scope_targets_contract_not_generated"},
                            "stale_source": {"passed": 25, "not_applicable": 0, "unknown": 5, "violations": 0, "unknown_reason": "undetermined"},
                        }[name],
                    )
                    for name in pr.AXES
                ),
                verified=False,
            ),
            soft=a.soft, funding=funding(),
        ),
        needle="跨轮", name="C9 跨轮分数不得合并",
    )

    card = card_a()
    card["release_ready"] = True
    expect_error(lambda: pr.parse_card(card, round_id=ROUND), needle="release_ready", name="C10 release_ready=true 拒绝")
    card = card_a()
    card["detail_export"] = True
    expect_error(lambda: pr.parse_card(card, round_id=ROUND), needle="detail_export", name="C11 detail_export=true 拒绝")
    card = card_a()
    card["threshold_met"] = True
    expect_error(lambda: pr.parse_card(card, round_id=ROUND), needle="threshold_met", name="C12 threshold_met 与计数不一致拒绝")
    card = card_a()
    card["hard_evidence"]["axes"]["cross_entity"]["unknown"] = 0
    expect_error(
        lambda: pr.parse_card(
            card,
            round_id=ROUND,
            unknown_reasons={
                "safety": "undetermined",
                "cross_user": "undetermined",
                "stale_source": "undetermined",
            },
        ),
        needle="自相矛盾", name="C13 缺 scope unknown 被抹成 0 拒绝（计数不自洽）",
    )

    for private_key in ("question", "questions", "answer", "labels", "per_case", "case_rows", "case_ids", "plaintext", "ciphertext"):
        payload = a.to_dict()
        payload[private_key] = ["RAW-PRIVATE"]
        expect_error(
            lambda payload=payload: pr.SplitReport.from_dict(payload),
            needle="题干", name=f"C14 报告拒绝私字段 {private_key}",
        )
    payload = a.to_dict()
    payload["quality"]["per_case"] = [{"question": "Q", "answer": "A"}]
    expect_error(lambda: pr.SplitReport.from_dict(payload), needle="题干", name="C15 嵌套逐题字段拒绝")

    for extra in ("overall_success", "overall", "ready", "overall_ready"):
        payload = a.to_dict()
        payload[extra] = True
        expect_error(
            lambda payload=payload: pr.SplitReport.from_dict(payload),
            needle="规范形式", name=f"C16 报告拒绝额外总体字段 {extra}",
        )
    payload = a.to_dict()
    payload["axes"][1]["status"] = "pass"
    expect_error(lambda: pr.SplitReport.from_dict(payload), needle="规范形式", name="C17 派生轴状态被改拒绝")

    payload = a.to_dict()
    check(pr.SplitReport.from_dict(payload).to_dict() == payload, "C18 合法报告 from_dict 规范往返")

    expect_error(
        lambda: pr.ReferenceSource.create(
            source_kind="real-h2-aggregate", document="D:/secret/real-h2.md",
            plan_id=ROUND, code_version="synthetic",
        ),
        needle="相对 POSIX", name="C19 报告参考路径逃逸拒绝",
    )
    expect_error(
        lambda: pr.ReferenceSource.create(
            source_kind="real-h2-aggregate", document="docs/reports/OBS-EVAL/P2/x.md",
            plan_id="../escape", code_version="synthetic",
        ),
        needle="路径", name="C20 plan_id 路径拒绝",
    )
    expect_error(
        lambda: pr.FundingStatus.create(
            ledger_current_sha256="1" * 64, ledger_previous_sha256="2" * 64,
            ledger_change_cause="legitimate_spend", go_current_sha256="3" * 64,
            go_archived_sha256="4" * 64, archived_line_moment="m",
            provider_balance_queried=True,
        ),
        needle="余额", name="C21 provider_balance_queried=true 拒绝",
    )
    expect_error(
        lambda: pr.FundingStatus.create(
            ledger_current_sha256="1" * 64, ledger_previous_sha256="2" * 64,
            ledger_change_cause="source_tampering", go_current_sha256="3" * 64,
            go_archived_sha256="4" * 64, archived_line_moment="m",
        ),
        needle="legitimate_spend", name="C22 账本变化不得写成源码篡改",
    )

    # 跨 pipeline/scope：diff 语义在 03 探针；此处核对 report 只允许单 plan/round。
    check(len({a.execution.round_id, a.quality.round_id, a.evidence.round_id, a.reference.plan_id}) == 1, "C23 报告单轮/单 plan")

    # 质量 FAIL 不被软评分 scored 抵消
    soft_scored = pr.SoftStatus.create(
        name="ragas", status="scored", recorded_status="ok", detail="x",
        rescored=True, rescored_scores={"faithfulness": 1.0}, rescored_reason="synthetic",
    )
    mixed = pr.build_split_report(
        reference=reference(ROUND), execution=a.execution, quality=a.quality,
        evidence=a.evidence, soft=(soft_scored,), funding=funding(),
    )
    check(mixed.quality.status == "fail" and mixed.quality.release_ready is False, "C24 软评分 scored 不能抵消质量 FAIL")

    failed = [name for ok, name, _ in RESULTS if not ok]
    print(f"\nchecks={len(RESULTS)} failed={len(failed)}")
    print("RESULT=" + ("PASS" if not failed else "FAIL"))
    for name in failed:
        print("FAILED_CHECK=" + name)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
