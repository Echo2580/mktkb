"""生成 review-aggregate.json（机器可读汇总）。"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIX1 = HERE.parent
OUT = FIX1 / "review-aggregate.json"

A = json.loads((HERE / "A-planner-multi-target.json").read_text(encoding="utf-8"))
AR = json.loads((HERE / "A-anaphora-regression.json").read_text(encoding="utf-8"))
B = json.loads((HERE / "B-business-date-filter.json").read_text(encoding="utf-8"))
RB = json.loads((HERE / "rollback-summary.json").read_text(encoding="utf-8"))
PR = json.loads((HERE / "preservation-compare.json").read_text(encoding="utf-8"))
QR = json.loads((HERE / "A-query-baseline-reconstruct.json").read_text(encoding="utf-8"))
SR = json.loads((HERE / "A-service-baseline-reconstruct.json").read_text(encoding="utf-8"))
NG = json.loads((HERE / "netguard" / "netguard-positive-control.json").read_text(encoding="utf-8"))
NG22 = json.loads((HERE / "netguard" / "netguard-tests22-run.json").read_text(encoding="utf-8"))
NGUR = json.loads((HERE / "netguard" / "netguard-unitrag-run.json").read_text(encoding="utf-8"))

pos = {k: v for k, v in A["cases"].items() if k.startswith("P")}
neg = {k: v for k, v in A["cases"].items() if k.startswith("N")}

payload = {
    "schema_version": "v3-fix1-independent-review-aggregate/v0.1",
    "reviewer": "v3-fix-verify",
    "baseline": {
        "branch": "codex/p2-e2e",
        "head": "97b0066726e5b8d6f94cbc0b63a890084550c106",
        "staged_before": 0,
        "staged_after": 0,
        "commits": 172,
    },
    "verdict": "FAIL",
    "verdict_scope": "窄口径：A 的纯指代硬性反例失败（N2/N2b），其余项绿。",
    "real_run_decision": "不可进入真实 v3 跑：唯一阻塞为 A 的纯指代回归；预算/计划/GO 闸门本身已 4/4 对齐。",
    "rollback": {
        "status": "DONE_WITH_DISAGREEMENTS",
        "budget": RB["budget"],
        "p2_holdout_plan": RB["p2_holdout_plan"],
        "tracked_modified": RB["tracked_modified"],
        "plans_and_go": RB["plans_and_go"],
        "companion_tool_change": RB["companion_tool_change"],
        "drift_tests": RB["tests"]["drift_failures"],
        "drift_counts": {
            "no_env": RB["tests"]["drift_two_no_env"],
            "env40": RB["tests"]["drift_two_env40"],
        },
    },
    "acceptance": {
        "A_planner_multi_target": {
            "status": "FAIL",
            "positives": {k: {"ok": v["ok"], "reason": v["planner"]["reason"],
                              "kind": v["e2e"]["kind"], "returned": v["e2e"]["returned"]}
                          for k, v in pos.items()},
            "negatives": {k: {"ok": v["ok"], "reason": v["planner"]["reason"],
                              "kind": v["e2e"]["kind"], "returned": v["e2e"]["returned"]}
                          for k, v in neg.items()},
            "failures": A["failures"],
            "regression": AR["rows"]["N2_this_two"],
            "regression_note": AR["findings"][0],
            "evidence": ["independent/A-planner-multi-target.json",
                         "independent/A-anaphora-regression.json"],
        },
        "B_business_date_filter": {
            "status": "PASS",
            "failures": B["failures"],
            "before": {"kind": B["before"]["kind"], "units": B["before"]["units"],
                       "locations": B["before"]["locations"]},
            "after": {"kind": B["after"]["kind"], "units": B["after"]["units"],
                      "locations": B["after"]["locations"]},
            "endpoints": {k: {"kind": v["kind"], "locations": v["locations"]}
                          for k, v in B["endpoints"].items()},
            "single_current": B["single_dated"]["locations"],
            "undeclared_start": B["undeclared_start"]["locations"],
            "wire": B["wire"],
            "invalid_as_of": B["invalid_as_of"],
            "order_subsequence": B["checks"]["subsequence_order"],
            "visible_units_unchanged": B["checks"]["visible_units_unchanged"],
            "no_fts_or_sort_changes": B["checks"]["no_changes_to_fts_or_sort"],
            "service_forwarding": {"none": B["checks"]["service_forward_none"],
                                   "dated": B["checks"]["service_forward_dated"]},
            "evidence": ["independent/B-business-date-filter.json"],
        },
        "no_revert_of_existing_work": {
            "status": "PASS",
            "query_py": {
                "current_sha256": QR["current_sha256"],
                "baseline_sha256": QR["expected_baseline_sha256"],
                "reconstructed_sha256": QR["reconstructed_sha256"],
                "byte_exact": QR["matches_expected"],
                "bytes": QR["reconstructed_bytes"],
            },
            "service_py": {
                "current_sha256": SR["current_sha256"],
                "baseline_sha256": SR["expected_baseline_sha256"],
                "reconstructed_sha256": SR["reconstructed_sha256"],
                "byte_exact": SR["matches_expected"],
                "bytes": SR["reconstructed_bytes"],
            },
            "other_baseline_paths_unchanged": PR["git"]["tracked_common_sha_changed"] == [],
            "evidence": ["independent/A-query-baseline-reconstruct.json",
                         "independent/A-service-baseline-reconstruct.json",
                         "independent/preservation-compare.json"],
        },
        "tests": {
            "status": "FAIL",
            "unit_rag": RB["tests"]["unit_rag"],
            "new_22": RB["tests"]["new_22"],
            "fix_touched_3": RB["tests"]["fix_touched_3_files"],
            "drift_two_no_env": RB["tests"]["drift_two_no_env"],
            "drift_two_env40": RB["tests"]["drift_two_env40"],
            "drift_failures": RB["tests"]["drift_failures"],
        },
        "zero_call": {
            "status": "PASS",
            "positive_control": {"all_blocked": NG["all_blocked"],
                                 "results": NG["results"],
                                 "proxy_env_removed": NG["proxy_env_removed_at_import"],
                                 "urllib_getproxies": NG["urllib_getproxies"]},
            "negative": {
                "tests22_external_count": NG22["external_count"],
                "unit_rag_external_count": NGUR["external_count"],
                "unit_rag_loopback_calls": NGUR["loopback_calls"],
                "probes_outbound": {"A": A["outbound_attempts"], "B": B["outbound_attempts"]},
            },
            "note": "不依赖本机代理：所有出站在 socket 层被拦；Windows 注册表代理 127.0.0.1:7897 未被使用。",
        },
        "preservation": {
            "status": "PASS",
            "head_same": PR["git"]["head_same"],
            "branch_same": PR["git"]["branch_same"],
            "commits": PR["git"]["commits"],
            "staged_after": PR["git"]["staged_after"],
            "tracked_modified_before": PR["git"]["tracked_modified_before"],
            "tracked_modified_after": PR["git"]["tracked_modified_after"],
            "tracked_removed": PR["git"]["tracked_removed"],
            "tracked_added": PR["git"]["tracked_added"],
            "c_freeze_12_all_equal": PR["c_freeze_12_all_equal"],
            "v3_freeze_32": PR["v3_freeze_32"],
            "external_ciphertext_corpus_changed": PR["external_ciphertext_corpus_changed"],
            "fixtures_changed": PR["fixtures_acceptance_h2v3_changed"],
            "ledger_unchanged": PR["ledger_unchanged"],
            "scenarios_py_unchanged": PR["scenarios_py_unchanged"],
            "scenarios_v3_py_unchanged": PR["scenarios_v3_py_unchanged"],
            "protected_changes_expected": PR["protected_changes_expected"],
        },
    },
    "disagreements": [
        {"id": "D1", "what": "tracked modified 回退后为 22（15 既有 + 7 fix-1），不是 15；dev-report 的 16 条为笔误",
         "evidence": "independent/preservation-compare.json"},
        {"id": "D2", "what": "2 条漂移测试未恢复绿：1 条需 MKTKB_PROJECT_TOTAL_LIMIT_CNY=40，1 条硬编码 limit_cny==20.0",
         "evidence": "independent/pytest-drift-2-after-rollback.log; pytest-drift2-with-env40.log"},
        {"id": "D3", "what": "A 的纯指代守卫不完整：带已点名门店的“这两个/这几个”被放行，且是 fix-1 引入的澄清→作答回归",
         "evidence": "independent/A-anaphora-regression.json"},
        {"id": "D4", "what": "dev-report §0.1/§4.2 的 status 集合描述与 §4.1 的 7 条 tracked 文件自相矛盾",
         "evidence": "fix-1/dev-report.md"},
        {"id": "D5", "what": "v3-go 的 report/plan-index 仍是 50 时代历史件；真实跑须用 rollback-40 下的计划/绑定",
         "evidence": "docs/reports/OBS-EVAL/P2/H2V3/v3-go/report.md"},
    ],
    "blockers": [
        "A 纯指代反例 N2/N2b 必须修复（指代守卫 + 回归用例）后才能重跑独立验收。",
    ],
    "evidence_files": [
        "independent-review.md",
        "independent/00-snapshot-start.json",
        "independent/00-snapshot-end.json",
        "independent/preservation-compare.json",
        "independent/budget-rollback.json",
        "independent/rollback-summary.json",
        "independent/A-planner-multi-target.json",
        "independent/A-anaphora-regression.json",
        "independent/A-query-baseline-reconstruct.json",
        "independent/A-service-baseline-reconstruct.json",
        "independent/B-business-date-filter.json",
        "independent/rollback-40/plan-index.json",
        "independent/rollback-40/go-regeneration.json",
        "independent/rollback-40/go-install.json",
        "independent/rollback-40/check/run0.json",
        "independent/rollback-40/check/run1.json",
        "independent/rollback-40/check/run2.json",
        "independent/rollback-40/check/run3.json",
        "independent/netguard/netguard-positive-control.json",
        "independent/netguard/netguard-tests22-run.json",
        "independent/netguard/netguard-unitrag-run.json",
        "independent/pytest-unit-rag-after-rollback.log",
        "independent/pytest-new-22-after-rollback.log",
        "independent/pytest-drift-2-after-rollback.log",
        "independent/pytest-drift2-with-env40.log",
        "independent/pytest-fix-touched-tests.log",
        "independent/pytest-unit-rag-netguard.log",
    ],
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
               encoding="utf-8")
print(json.dumps({"verdict": payload["verdict"], "real_run": payload["real_run_decision"],
                  "A": payload["acceptance"]["A_planner_multi_target"]["status"],
                  "B": payload["acceptance"]["B_business_date_filter"]["status"],
                  "no_revert": payload["acceptance"]["no_revert_of_existing_work"]["status"],
                  "tests": payload["acceptance"]["tests"]["status"],
                  "zero_call": payload["acceptance"]["zero_call"]["status"],
                  "preservation": payload["acceptance"]["preservation"]["status"]},
                 ensure_ascii=False, indent=1))
