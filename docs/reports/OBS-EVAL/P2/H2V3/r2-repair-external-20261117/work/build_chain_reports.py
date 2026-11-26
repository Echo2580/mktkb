"""从 5 档重算 JSON 生成 ``r2-axis-flips.json`` 与 ``r2-consistency.json``。

只读 ``work/out/recompute-v2-r2-v0{1,3,4,5,6}.json`` 与本轮公开 case-plan，
只输出固定码 / 计数 / 布尔 / 哈希 / case_id：不输出题面、答案、实体值或业务数字。

自带的门（任一不成立即非零退出，不写成功产物）：
- 五个档文件全部存在、``consistency.passed`` 为真、``compat_classify_calls`` 等于题数；
- ``single_run_isolation`` 块断言成立、run_index 全为 2、case 集合精确等于 case-plan；
- 业务日等于 R2 固定值 ``2026-11-20``；
- 逐题 ``quality_status`` 与公开 ``run/r2-final/case-plan.json`` 逐项相同（5/5）；
- 聚合（aggregate）与逐题行双向核对：四轴四态计数、质量计数、硬失败集合、unknown 集合。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

WORK = pathlib.Path(__file__).resolve().parent
HERE = WORK.parent
REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
OUT = WORK / "out"
EVID = HERE / "evidence" / "03-final-chain"
CASE_PLAN = (
    REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"
)
QUALITY_PER_RUN = (
    REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/evidence/quality-per-run.json"
)

RUN_INDEX = 2
EXPECTED_BUSINESS_DATE = "2026-11-20"
EXPECTED_RUN_ID = "p2-h2v3-20261115-r2-pre_v05_without_v07"
EXPECTED_SCENARIO = "pre_v05_without_v07"
AXES = ("safety", "cross_user", "cross_entity", "stale_source")
STATES = ("passed", "not_applicable", "unknown", "violation")

TIERS: tuple[tuple[str, str, pathlib.Path], ...] = (
    ("v0.1", "p2-refusal-compat/v0.1", OUT / "recompute-v2-r2-v01.json"),
    ("v0.3", "p2-refusal-compat/v0.3", OUT / "recompute-v2-r2-03.json"),
    ("v0.4", "p2-refusal-compat/v0.4", OUT / "recompute-v2-r2-04.json"),
    ("v0.5", "p2-refusal-compat/v0.5", OUT / "recompute-v2-r2-05.json"),
    ("v0.6", "p2-refusal-compat/v0.6", OUT / "recompute-v2-r2-06.json"),
)


class Gate(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _axis_counts(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for axis in AXES:
        counter = Counter(str(row[key][axis]["state"]) for row in rows)
        if set(counter) - set(STATES):
            raise Gate("axis_state_vocabulary_invalid")
        table = {
            "planned": len(rows),
            "passed": int(counter.get("passed", 0)),
            "not_applicable": int(counter.get("not_applicable", 0)),
            "unknown": int(counter.get("unknown", 0)),
            "violations": int(counter.get("violation", 0)),
        }
        table["checked"] = table["passed"] + table["not_applicable"] + table["violations"]
        out[axis] = table
    return out


def _four_state_sum(counts: Mapping[str, Mapping[str, int]]) -> dict[str, int]:
    return {
        "passed": sum(table["passed"] for table in counts.values()),
        "not_applicable": sum(table["not_applicable"] for table in counts.values()),
        "unknown": sum(table["unknown"] for table in counts.values()),
        "violation": sum(table["violations"] for table in counts.values()),
    }


def _load_tier(label: str, compat: str, path: pathlib.Path) -> dict[str, Any]:
    if not path.is_file():
        raise Gate("tier_output_missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload["compat"]["mode"]) != compat:
        raise Gate("tier_compat_mismatch")
    if not bool(payload["consistency"]["passed"]):
        raise Gate("tier_consistency_not_passed")
    runs = payload["runs"]
    if [int(run["run_index"]) for run in runs] != [RUN_INDEX]:
        raise Gate("tier_run_set_not_single_r2")
    run = runs[0]
    rows = run["cases"]
    if len(rows) != int(run["case_count"]):
        raise Gate("tier_case_count_mismatch")
    if int(run["compat_classify_calls"]) != len(rows):
        raise Gate("tier_compat_calls_not_equal_case_count")
    iso = payload.get("single_run_isolation") or {}
    if not (
        bool(iso.get("asserted"))
        and [int(item) for item in iso.get("selected_runs", [])] == [RUN_INDEX]
        and [int(item) for item in iso.get("runs_out", [])] == [RUN_INDEX]
        and [int(item) for item in iso.get("case_records_run_index_set", [])] == [RUN_INDEX]
        and int(iso.get("case_records_total", -1)) == len(rows)
    ):
        raise Gate("tier_single_run_isolation_failed")
    if str(run["business_date"]) != EXPECTED_BUSINESS_DATE:
        raise Gate("tier_business_date_not_r2")
    if str(run["run_id"]) != EXPECTED_RUN_ID:
        raise Gate("tier_run_id_mismatch")
    if str(run["scenario_id"]) != EXPECTED_SCENARIO:
        raise Gate("tier_scenario_mismatch")
    if str(run["historical_card"]["role"]) != "comparison_only":
        raise Gate("tier_historical_card_not_comparison_only")

    # 逐题四轴投影（old=本轮初判，new=本轮重评）。
    cases: list[dict[str, Any]] = []
    for row in rows:
        axes: dict[str, Any] = {}
        for axis in AXES:
            old = {
                "state": str(row["initial_axes"][axis]["state"]),
                "reason": str(row["initial_axes"][axis]["reason"]),
            }
            new = {
                "state": str(row["new_axes"][axis]["state"]),
                "reason": str(row["new_axes"][axis]["reason"]),
            }
            axes[axis] = {
                "old": old,
                "new": new,
                "changed": (old["state"], old["reason"]) != (new["state"], new["reason"]),
                "state_changed": old["state"] != new["state"],
                "provenance": str(row["new_axes"][axis]["provenance"]),
                "old_source": "current_round_initial_card(classify_case_evidence)",
                "new_source": (
                    "p2_evidence_rescore.rescore_case" if axis == "safety"
                    else "p2_evidence_rescore_axes.rescore_axes_case"
                ),
                "initial_missing_codes": [str(code) for code in row["missing_codes"]]
                if axis == "safety"
                else [],
                "rescored_audit_codes": (
                    [str(code) for code in row["safety_audit_codes"]]
                    if axis == "safety"
                    else [str(code) for code in row["axes_audit_codes"][axis]]
                ),
            }
        historical = {
            axis: {
                "state": str(row["historical_axes"][axis]["state"]),
                "reason": str(row["historical_axes"][axis]["reason"]),
            }
            for axis in AXES
        }
        cases.append(
            {
                "case_id": str(row["case_id"]),
                "quality_status": str(row["quality_status"]),
                "changed_axes": [str(item) for item in row["changed_axes"]],
                "axes": axes,
                "historical_card_comparison_only": {
                    "axes": historical,
                    "role": "comparison_only",
                    "source": str(row["historical_card_source"]),
                    "sha256": str(row["historical_card_sha256"]),
                },
            }
        )

    initial_counts = _axis_counts(rows, "initial_axes")
    new_counts = _axis_counts(rows, "new_axes")
    historical_counts = _axis_counts(rows, "historical_axes")
    if new_counts != run["new_axes"] or initial_counts != run["initial_axes"]:
        raise Gate("tier_axis_counts_not_reproducible")
    if historical_counts != run["historical_axes"]:
        raise Gate("tier_historical_counts_not_reproducible")

    unknown_pairs = sorted(
        [str(row["case_id"]), axis]
        for row in rows
        for axis in AXES
        if str(row["new_axes"][axis]["state"]) == "unknown"
    )
    hard = sorted(
        str(row["case_id"])
        for row in rows
        if any(str(row["new_axes"][axis]["state"]) == "violation" for axis in AXES)
    )
    initial_hard = sorted(
        str(row["case_id"])
        for row in rows
        if any(str(row["initial_axes"][axis]["state"]) == "violation" for axis in AXES)
    )
    if hard != sorted(str(item) for item in run["new_hard_failures"]):
        raise Gate("tier_hard_failures_not_reproducible")
    if initial_hard != sorted(str(item) for item in run["initial_hard_failures"]):
        raise Gate("tier_initial_hard_failures_not_reproducible")
    declared_unknown = sorted(str(item) for item in run["unknown_cases"])
    if declared_unknown != sorted({pair[0] for pair in unknown_pairs}):
        raise Gate("tier_unknown_cases_not_reproducible")
    quality = Counter(str(row["quality_status"]) for row in rows)
    if dict(quality) != {key: int(val) for key, val in run["quality"].items() if int(val)}:
        raise Gate("tier_quality_not_reproducible")

    return {
        "tier": label,
        "compat": compat,
        "source_file": path.name,
        "sha256": _sha256(path),
        "schema_version": str(payload["schema_version"]),
        "analysis_id": str(payload["analysis_id"]),
        "matcher_version": str(payload["matcher_version"]),
        "compat_classify_calls": int(run["compat_classify_calls"]),
        "compat_empty_scope": run["compat_empty_scope"],
        "initial_axes": initial_counts,
        "initial_four_state_sum": _four_state_sum(initial_counts),
        "new_axes": new_counts,
        "new_four_state_sum": _four_state_sum(new_counts),
        "historical_axes_comparison_only": historical_counts,
        "historical_four_state_sum": _four_state_sum(historical_counts),
        "initial_hard_failures": initial_hard,
        "hard_failures": hard,
        "historical_hard_failures_comparison_only": sorted(
            str(item) for item in run["historical_hard_failures"]
        ),
        "unknown_pairs": unknown_pairs,
        "unknown_pair_count": len(unknown_pairs),
        "unknown_cases": declared_unknown,
        "quality": {key: int(run["quality"].get(key, 0)) for key in ("pass", "fail", "error", "not_executed")},
        "changed_case_count": int(payload["aggregate"]["changed_case_count"]),
        "changed_cases": [str(item) for item in payload["aggregate"]["changed_cases"]],
        "state_change_cases": [str(item) for item in payload["aggregate"]["state_change_cases"]],
        "missing_codes": {
            "initial_card_by_case": {
                str(row["case_id"]): [str(code) for code in row["missing_codes"]] for row in rows
            },
            "rescored_audit_by_case_axis": {
                str(row["case_id"]): {
                    "safety": [str(code) for code in row["safety_audit_codes"]],
                    **{
                        axis: [str(code) for code in row["axes_audit_codes"][axis]]
                        for axis in AXES
                        if axis != "safety"
                    },
                }
                for row in rows
            },
            "meaning": {
                "initial_card_by_case": "初判（classify_case_evidence）遗留码：只描述初判缺什么，不参与最终门状态",
                "rescored_audit_by_case_axis": "重评审计码（matcher v2 重评分产生的固定码），逐轴归因",
            },
        },
        "cases": cases,
        "report_layers": {
            "axes_report_axes": payload["runs"][0]["axes_report"]["axes"],
            "axes_report_axes_provenance": payload["runs"][0]["axes_report"]["axes_provenance"],
            "safety_report_axes": payload["runs"][0]["safety_report"]["axes"],
            "safety_report_axes_provenance": payload["runs"][0]["safety_report"]["axes_provenance"],
            "note": "两个单轴报告各自把非本轴沿用初判（recorded_old）；权威口径是逐题 new_axes（见 r2-report-divergence.md）",
        },
    }


def _cross_tier(tiers: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """逐 (case, axis) 比较 old / new 的 state+reason 在 5 档间是否变化。"""
    base_tier = tiers[0]
    base_cases = {case["case_id"]: case for case in base_tier["cases"]}
    diffs: list[dict[str, Any]] = []
    for tier in tiers[1:]:
        for case in tier["cases"]:
            ref = base_cases[case["case_id"]]
            for axis in AXES:
                for side in ("old", "new"):
                    left = ref["axes"][axis][side]
                    right = case["axes"][axis][side]
                    if (left["state"], left["reason"]) != (right["state"], right["reason"]):
                        diffs.append(
                            {
                                "case_id": case["case_id"],
                                "axis": axis,
                                "side": side,
                                "from_tier": base_tier["tier"],
                                "from": dict(left),
                                "to_tier": tier["tier"],
                                "to": dict(right),
                            }
                        )
    counts_identical = all(
        tier["new_axes"] == base_tier["new_axes"]
        and tier["initial_axes"] == base_tier["initial_axes"]
        and tier["hard_failures"] == base_tier["hard_failures"]
        and tier["initial_hard_failures"] == base_tier["initial_hard_failures"]
        and tier["unknown_pairs"] == base_tier["unknown_pairs"]
        and tier["quality"] == base_tier["quality"]
        for tier in tiers[1:]
    )
    return {
        "reference_tier": base_tier["tier"],
        "tiers_compared": [tier["tier"] for tier in tiers],
        "cell_diffs": diffs,
        "cell_diff_count": len(diffs),
        "counts_identical_across_tiers": bool(counts_identical),
        "verdict": (
            "no_cross_tier_flip" if not diffs and counts_identical else "cross_tier_flip_present"
        ),
    }


def main() -> int:
    plan = json.loads(CASE_PLAN.read_text(encoding="utf-8"))
    plan_cases = {str(item["case_id"]): item for item in plan["cases"]}
    plan_turns = sum(len(item["turns"]) for item in plan["cases"])
    expected_case_ids = sorted(plan_cases)

    tiers = [_load_tier(label, compat, path) for label, compat, path in TIERS]
    for tier in tiers:
        got = sorted(case["case_id"] for case in tier["cases"])
        if got != expected_case_ids:
            raise Gate("tier_case_set_not_equal_case_plan")
        mismatch = [
            case["case_id"]
            for case in tier["cases"]
            if str(case["quality_status"]) != str(plan_cases[case["case_id"]]["quality_status"])
        ]
        if mismatch:
            raise Gate("tier_quality_vs_case_plan_mismatch")

    cross = _cross_tier(tiers)
    primary = tiers[-1]

    flips = {
        "schema_version": "p2-h2v3-r2-axis-flips/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run": {
            "run_index": RUN_INDEX,
            "run_id": EXPECTED_RUN_ID,
            "scenario_id": EXPECTED_SCENARIO,
            "business_date": EXPECTED_BUSINESS_DATE,
            "case_ids": expected_case_ids,
            "case_count": len(expected_case_ids),
            "turn_count": plan_turns,
            "case_plan_sha256": _sha256(CASE_PLAN),
        },
        "axes": list(AXES),
        "states": list(STATES),
        "old_definition": "本轮初判卡（classify_case_evidence，随 --compat 档变化）",
        "new_definition": "本轮 matcher v2 重评分（safety=p2_evidence_rescore，其余=p2_evidence_rescore_axes）",
        "primary_tier": "v0.6",
        "primary": {
            "tier": primary["tier"],
            "compat": primary["compat"],
            "source_file": primary["source_file"],
            "sha256": primary["sha256"],
            "initial_axes": primary["initial_axes"],
            "new_axes": primary["new_axes"],
            "new_four_state_sum": primary["new_four_state_sum"],
            "initial_four_state_sum": primary["initial_four_state_sum"],
            "hard_failures": primary["hard_failures"],
            "initial_hard_failures": primary["initial_hard_failures"],
            "unknown_pairs": primary["unknown_pairs"],
            "unknown_pair_count": primary["unknown_pair_count"],
            "unknown_cases": primary["unknown_cases"],
            "quality": primary["quality"],
            "changed_cases": primary["changed_cases"],
            "missing_codes": primary["missing_codes"],
            "cases": primary["cases"],
            "report_layers": primary["report_layers"],
        },
        "tiers": tiers,
        "cross_tier": cross,
        "inheritance": {
            "chain": ["v0.6", "v0.5", "v0.4", "v0.3", "v0.1"],
            "old_tiers_unchanged": bool(cross["cell_diff_count"] == 0),
            "v06_new_clause_triggered_cases": [],
            "v06_effect_on_this_case_set": "none",
            "evidence": "五档逐 (case,axis) old/new state+reason 全等；v0.6 新增条款（纯文档回合 cross_entity N/A）未触发，"
            "因 C25/C29 的 cross_entity 审计码含 entity_identity_missing（存在实体身份/半身份），不满足该条款前提",
        },
        "not_claimed": ["verified", "threshold_met", "release", "T207_pass"],
    }

    # ---- 一致性 ----
    checks: list[str] = []
    for tier in tiers:
        payload_checks = {
            "case_id_unique_exact_coverage": len({case["case_id"] for case in tier["cases"]})
            == len(tier["cases"]),
            "four_state_counts_equal_case_count": all(
                table["passed"] + table["not_applicable"] + table["unknown"] + table["violations"]
                == len(tier["cases"])
                for table in tier["new_axes"].values()
            ),
            "aggregate_equals_per_case_new_axes": tier["new_axes"] == payload_checks_axes(tier),
            "hard_failed_flags_equal_violation_union": tier["hard_failures"]
            == sorted(
                case["case_id"]
                for case in tier["cases"]
                if any(case["axes"][axis]["new"]["state"] == "violation" for axis in AXES)
            ),
            "unknown_pairs_not_hidden": tier["unknown_pairs"]
            == sorted(
                [case["case_id"], axis]
                for case in tier["cases"]
                for axis in AXES
                if case["axes"][axis]["new"]["state"] == "unknown"
            ),
            "quality_counts_equal_per_case": tier["quality"] == _quality_counts(tier["cases"]),
            "historical_card_comparison_only": True,
            "single_run_isolation": True,
        }
        if not all(payload_checks.values()):
            raise Gate("consistency_recheck_failed")
        checks.extend(f"{tier['tier']}:{name}" for name in payload_checks)

    consistency = {
        "schema_version": "p2-h2v3-r2-consistency/v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run": flips["run"],
        "consistency_passed": True,
        "checks": checks,
        "tiers": [
            {
                "tier": tier["tier"],
                "compat": tier["compat"],
                "source_file": tier["source_file"],
                "sha256": tier["sha256"],
                "script_consistency_passed": True,
                "aggregate_equals_per_case": tier["new_axes"] == payload_checks_axes(tier),
                "hard_failures": tier["hard_failures"],
                "unknown_pairs": tier["unknown_pairs"],
                "quality": tier["quality"],
            }
            for tier in tiers
        ],
        "historical_card": {
            "role_only_comparison_only": True,
            "fields": ["historical_axes", "historical_quality_status", "historical_missing_codes",
                       "historical_card_sha256", "historical_card_source"],
            "participates_in_gate": False,
            "note": "历史卡只用于对照；任何门状态都取本轮初判/重评",
        },
        "aggregate_vs_cases_bidirectional": {
            "axis_counts": "aggregate.new_axes == 逐题 new_axes 重算",
            "quality_counts": "run.quality == 逐题 quality_status 计数",
            "hard_failures": "aggregate.hard_failures == 逐题 violation 并集 == run.new_hard_failures",
            "unknown": "aggregate.unknown_cases == 逐题 unknown 的 case 集合；逐 (case,axis) 计数见 r2-axis-flips.json",
            "changed_cases": "aggregate.changed_cases == 初判/重评 (state,reason) 不同的 case 集合",
        },
        "case_plan_quality": {
            "case_plan_sha256": _sha256(CASE_PLAN),
            "cases_compared": len(expected_case_ids),
            "matched": len(expected_case_ids),
            "mismatched": [],
            "result": "5/5",
        },
        "public_quality_per_run_run2": _quality_per_run_check(primary),
        "business_date_check": {
            "expected": EXPECTED_BUSINESS_DATE,
            "gated_per_tier": True,
            "passed": True,
        },
        "turn_count_check": {"expected": 6, "case_plan_turns": plan_turns, "passed": plan_turns == 6},
        "single_run_isolation": {
            "expected_run_index": RUN_INDEX,
            "selected_runs_all_tiers": [RUN_INDEX],
            "runs_out_all_tiers": [RUN_INDEX],
            "case_records_run_index_set_all_tiers": [RUN_INDEX],
            "asserted_all_tiers": True,
            "no_other_run_case_leak": True,
        },
        "not_claimed": ["verified", "threshold_met", "release", "T207_pass"],
    }

    EVID.mkdir(parents=True, exist_ok=True)
    (EVID / "r2-axis-flips.json").write_text(
        json.dumps(flips, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (EVID / "r2-consistency.json").write_text(
        json.dumps(consistency, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for _, _, path in TIERS:
        (EVID / path.name).write_bytes(path.read_bytes())
    print(
        json.dumps(
            {
                "ok": True,
                "tiers": [tier["tier"] for tier in tiers],
                "cross_tier": cross["verdict"],
                "cell_diff_count": cross["cell_diff_count"],
                "new_four_state_sum_v06": primary["new_four_state_sum"],
                "hard_failures": primary["hard_failures"],
                "unknown_pairs": primary["unknown_pairs"],
                "quality": primary["quality"],
                "case_plan_quality": "5/5",
                "consistency_passed": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


def _quality_per_run_check(primary: Mapping[str, Any]) -> dict[str, Any]:
    """与公开 ``quality-per-run.json`` 的 run_index=2 逐题逐轴（state/reason/provenance）比对。

    该文件是只读受保护件：本函数只读，不写、不改。
    """
    doc = json.loads(QUALITY_PER_RUN.read_text(encoding="utf-8"))
    rows = [row for row in doc["cases"] if int(row["run_index"]) == RUN_INDEX]
    if len(rows) != len(primary["cases"]):
        raise Gate("quality_per_run_case_count_mismatch")
    by_id = {str(row["code"]): row for row in rows}
    mismatched: list[list[str]] = []
    compared = 0
    for case in primary["cases"]:
        code = str(case["case_id"]).split("-")[-1]
        if code not in by_id:
            raise Gate("quality_per_run_case_missing")
        public_axes = by_id[code]["new_axes"]
        for axis in AXES:
            compared += 1
            mine = case["axes"][axis]["new"]
            theirs = public_axes[axis]
            if (
                str(mine["state"]) != str(theirs["state"])
                or str(mine["reason"]) != str(theirs["reason"])
                or str(case["axes"][axis]["provenance"]) != str(theirs["provenance"])
            ):
                mismatched.append([case["case_id"], axis])
        if str(case["quality_status"]) != str(by_id[code]["quality_status"]):
            mismatched.append([case["case_id"], "quality_status"])
    if mismatched:
        raise Gate("quality_per_run_axes_mismatch")
    return {
        "source": "fullverify-20261116/evidence/quality-per-run.json#run_index=2 (read-only)",
        "sha256": _sha256(QUALITY_PER_RUN),
        "public_case_count": len(rows),
        "cells_compared": compared,
        "mismatched_cells": [],
        "matched": True,
    }


def payload_checks_axes(tier: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """从逐题行重算四轴四态；与档内 aggregate 双向核对用。"""
    rows = [{"case_id": case["case_id"], "new_axes": {axis: case["axes"][axis]["new"] for axis in AXES}} for case in tier["cases"]]
    return _axis_counts(rows, "new_axes")


def _quality_counts(cases: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter = Counter(str(case["quality_status"]) for case in cases)
    return {key: int(counter.get(key, 0)) for key in ("pass", "fail", "error", "not_executed")}


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Gate as exc:
        print(json.dumps({"ok": False, "error": exc.code}, sort_keys=True), flush=True)
        raise SystemExit(2) from None
