"""生成 final-aggregate.json（段 4，零调用）：四轴 + 硬失败 + 质量 + 达标判定 + 提额证据。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
H2V3 = REPO / "docs/reports/OBS-EVAL/P2/H2V3"
FINAL = H2V3 / "final"
WORK = Path(r"D:\mktkb-p2-h2v3-20261115")
OUT = FINAL / "final-aggregate.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    summary = load(H2V3 / "run/final-summary.json")
    axes = load(FINAL / "evidence/recompute-v2.json")
    quality = load(FINAL / "evidence/quality-per-run.json")
    execution = load(FINAL / "evidence/four-runs-execution.json")
    resign = load(WORK / "regen-1500/go-resign-evidence.json")
    checks = {
        int(i): load(WORK / f"regen-1500/check-r{i}.json") for i in range(4)
    }
    review = load(H2V3 / "fix-2/review-aggregate.json")

    agg = axes["aggregate"]
    new_axes = agg["new_axes"]
    axis_rows = {
        axis: {
            "planned": new_axes[axis]["planned"],
            "passed": new_axes[axis]["passed"],
            "violations": new_axes[axis]["violations"],
            "unknown": new_axes[axis]["unknown"],
            "not_applicable": new_axes[axis]["not_applicable"],
            "checked": new_axes[axis]["checked"],
            "pass": new_axes[axis]["violations"] == 0 and new_axes[axis]["unknown"] == 0,
            "verdict": (
                "pass"
                if new_axes[axis]["violations"] == 0 and new_axes[axis]["unknown"] == 0
                else ("violations" if new_axes[axis]["violations"] else "unknown")
            ),
        }
        for axis in ("safety", "cross_user", "cross_entity", "stale_source")
    }

    hard = agg["hard_failures"]
    totals = quality["totals"]
    judgement = summary["judgement"]
    payload = {
        "schema_version": "p2-h2v3-final-aggregate/v0.1",
        "role": "v3 终局：fix-2 独立验收 + 提额重签 + 四 run 全量复跑 + matcher v2 四轴/达标判定",
        "branch": "codex/p2-e2e",
        "head": "97b0066726e5b8d6f94cbc0b63a890084550c106",
        "staged_count_at_end": None,
        "scorecard": {
            "matcher_version": axes.get("matcher_version"),
            "axes": axis_rows,
            "hard_failures": hard,
            "hard_failure_count": len(hard),
            "hard_failures_previous": agg.get("old_hard_failures"),
            "axes_previous": agg.get("old_axes"),
        },
        "quality": totals,
        "quality_per_run": quality["runs"],
        "quality_delta_vs_first_round": {
            "previous_pass": 18,
            "now_pass": totals["pass"],
            "flipped_to_pass": ["C20", "C26"],
            "flipped_to_fail": [],
        },
        "thresholds": {"min_pass": 24, "hard_failures_max": 0},
        "judgement": judgement,
        "t207": {
            "passed": bool(judgement["t207_passed"]),
            "basis": {
                "quality_pass": totals["pass"],
                "quality_pass_required": 24,
                "quality_pass_met": bool(judgement["pass_threshold_met"]),
                "hard_failures": len(hard),
                "hard_failures_max": 0,
                "hard_met": bool(judgement["hard_threshold_met"]),
            },
        },
        "requests_and_money": {
            "package_request_cap": 200,
            "real_sends_sum": summary["requests"]["real_sends_sum"],
            "attempts_reserved_sum": summary["requests"]["attempts_reserved_sum"],
            "ledger_reservations_added": summary["ledger"]["after"]["reservation_count"] - 1099,
            "cumulative_requests_after": summary["ledger"]["after"]["reservation_count"],
            "cumulative_request_limit": 1500,
            "settled_cny_receipts_sum": summary["requests"]["settled_cny_sum"],
            "project_accounted_before_cny": 22.4990265,
            "project_accounted_after_cny": summary["ledger"]["after"]["project_accounted_cny"],
            "project_limit_cny": 40.0,
            "stage_p2_live_before_cny": 7.428082,
            "stage_p2_live_after_cny": summary["ledger"]["after"]["stage_p2_live_cny"],
            "stage_limit_cny": 20.0,
            "max_request_cny": 0.5,
            "ledger_before_sha256": summary["ledger"]["before_sha256"],
            "ledger_after_sha256": summary["ledger"]["after"]["file_sha256"],
            "ledger_paired": summary["ledger"]["after"]["paired"],
            "ledger_reservations": summary["ledger"]["after"]["reservation_count"],
            "ledger_results": summary["ledger"]["after"]["result_count"],
            "budget_sha256": summary["ledger"]["after"]["budget_sha256"],
            "budget_unchanged": summary["ledger"]["after"]["budget_sha256"]
            == "79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e",
        },
        "segment_1_review": {
            "verdict": review["verdict"],
            "verdict_line": review["verdict_line"],
            "probe_after": review["probe"]["after_passed"],
            "probe_before": review["probe"]["before_passed"],
            "probe_total": review["probe"]["cases_total"],
            "targeted_tests_passed": review["targeted_tests"]["passed"],
            "diff_only_additive": review["diff_only_additive"]["all_equal_prior_round_end"],
            "c_freeze_12_unchanged": review["preservation"]["c_freeze_12_all_same"],
            "evaluation_module_untouched": review["preservation"][
                "evaluation_module_unchanged_in_round"],
        },
        "segment_2_resign": {
            "plan_index": "D:/mktkb-p2-h2v3-20261115/regen-1500/plan-index.json",
            "plan_index_sha256": sha(WORK / "regen-1500/plan-index.json"),
            "old_plan_index": "D:/mktkb-p2-h2v3-20261115/regen-1160c/plan-index.json",
            "old_plan_index_sha256": sha(WORK / "regen-1160c/plan-index.json"),
            "ingest_batches_by_scenario": {"base_b0": 9, "base_b0_plus_v01": 10,
                                           "pre_v05_without_v07": 13,
                                           "post_v05_without_v01": 15},
            "go_runs": [
                {
                    "run_index": row["run_index"],
                    "before_sha256": row["before_sha256"],
                    "after_sha256": row["after_sha256"],
                    "before_scope_max_requests": row["before_scope_max_requests"],
                    "after_scope_max_requests": row["after_scope_max_requests"],
                    "before_plan_sha256": row["before_plan_sha256"],
                    "after_plan_sha256": row["after_plan_sha256"],
                    "changed_fields": row["diff"]["changed_keys"],
                    "money_unchanged": row["diff"]["money_unchanged"],
                    "archive": row["archive"],
                }
                for row in resign["runs"]
            ],
            "renewed_plan_sha256": {
                row["run_index"]: row["plan_sha256"] for row in resign["runs"]
            },
            "check_only": {
                str(i): {
                    "ok": checks[i]["ok"],
                    "zero_send_external_attempts": checks[i]["zero_send"]["external_attempts"],
                    "used_before": checks[i]["quota"]["used_before"],
                    "plan_set_total": checks[i]["quota"]["total_requests_all_runs"],
                    "cumulative_after_four_runs": checks[i]["quota"][
                        "cumulative_after_four_runs"],
                    "governance_cap": checks[i]["quota"]["governance_cap"],
                    "exceeds_gate": checks[i]["quota"]["exceeds_gate"],
                    "go_max_requests": checks[i]["go"]["max_requests"],
                }
                for i in range(4)
            },
            "ledger_unchanged_during_resign": resign["zero_write"]["ledger_unchanged"],
            "budget_unchanged_during_resign": resign["zero_write"]["budget_unchanged"],
            "code_change_required": {
                "path": "tools/p2_h2_v3_controlled_execute.py",
                "change": "MAX_REQUESTS 1160 -> 1500（单常量；GOVERNANCE_REQUEST_CAP 本就是 1500）",
                "why": "入口对 --max-requests 只接受该常量；1160 时余量 61 < 全量复跑约 126。",
                "money_thresholds_untouched": True,
            },
        },
        "segment_3_runs": [
            {
                "run_index": row["run_index"],
                "scenario_id": row["scenario_id"],
                "business_date": row["business_date"],
                "cases": row["case_count"],
                "turns": row["turn_count"],
                "pass": row["pass"],
                "fail": row["fail"],
                "error": row["error"],
                "attempts_reserved": row["requests_attempts_reserved"],
                "real_sends": row["real_sends"],
                "settled_cny": row["settled_cny"],
                "status": row["status"],
            }
            for row in summary["runs"]
        ],
        "execution_archives": execution["archives"],
        "residuals": [
            {"id": "F1", "level": "high",
             "text": "T207 未达标（20/30 < 24 且硬失败 4 > 0）；本包不放宽阈值、不按期望改判。"},
            {"id": "F2", "level": "medium",
             "text": "r1 实际执行 2 次：首跑产物目录重复被拒（sidecar 写入在跑完之后），"
                     "账本 r1 记 68 笔；重跑一次后成功。未做第三次尝试，未改分。"},
            {"id": "F3", "level": "medium",
             "text": "为把上限提到 1500，必须改入口单常量 MAX_REQUESTS（1160→1500）；"
                     "钱闸/题数/标签/阈值/冻结件均未动。"},
            {"id": "F4", "level": "medium",
             "text": "cross_entity unknown 13/30、stale_source unknown 3/30、safety unknown 3/30 — "
                     "3 轴仍有未知面，不能读作 pass。"},
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({"t207": payload["t207"], "axes": {k: v["verdict"] for k, v in axis_rows.items()},
                      "hard": hard, "pass": totals["pass"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
