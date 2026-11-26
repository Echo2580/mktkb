"""汇总第一部分（预算/计划回退）与测试计数，写 rollback-summary.json。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
OUT = HERE / "rollback-summary.json"

sys.path.insert(0, str(REPO / "backend" / "src"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tracked() -> list[str]:
    raw = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "-uall"], cwd=REPO, capture_output=True
    ).stdout
    out = []
    for rec in raw.split(b"\0"):
        if not rec or rec.startswith(b"??"):
            continue
        out.append(rec.decode("utf-8", "surrogateescape")[3:])
    return sorted(out)


BASELINE_15 = [
    ".claude/handoffs/_index.md",
    "backend/src/mktkb/conversations/service.py",
    "backend/src/mktkb/evaluation/cli.py",
    "backend/src/mktkb/evaluation/p2_diagnostics.py",
    "backend/src/mktkb/evaluation/p2_holdout_scenarios.py",
    "backend/src/mktkb/evaluation/p2_live.py",
    "backend/src/mktkb/evaluation/p2_runner.py",
    "backend/src/mktkb/evaluation/p2_scoring.py",
    "backend/src/mktkb/evaluation/product_adapter.py",
    "backend/src/mktkb/qa/service.py",
    "backend/src/mktkb/rag/index.py",
    "backend/src/mktkb/rag/query.py",
    "backend/tests/rag/test_query_state.py",
    "backend/tests/unit/test_conversations.py",
    "docs/reports/OBS-EVAL/P2/T207-QUALITY-REPAIR/manager.md",
]
FIX1_7 = [
    "backend/src/mktkb/rag/types.py",
    "backend/src/mktkb/rag/retrieval.py",
    "backend/src/mktkb/retrieval/service.py",
    "backend/tests/observability/test_paths_e2e.py",
    "backend/tests/integration/test_p1_t103_record_fallback_http.py",
    "backend/tests/integration/test_t207_fix_conflict_r1.py",
    "backend/tests/unit/test_p1_t103_record_fallback.py",
]

budget = json.loads((HERE / "budget-rollback.json").read_text(encoding="utf-8"))
go = json.loads((HERE / "rollback-40" / "go-regeneration.json").read_text(encoding="utf-8"))
install = json.loads((HERE / "rollback-40" / "go-install.json").read_text(encoding="utf-8"))
pres = json.loads((HERE / "preservation-compare.json").read_text(encoding="utf-8"))

plan_path = REPO / "backend/src/mktkb/evaluation/p2_holdout_plan.py"
plan_diff_empty = (
    subprocess.run(
        ["git", "diff", "--quiet", "--", "backend/src/mktkb/evaluation/p2_holdout_plan.py"],
        cwd=REPO,
    ).returncode
    == 0
)
plan_head_bytes = subprocess.run(
    ["git", "show", "HEAD:backend/src/mktkb/evaluation/p2_holdout_plan.py"],
    cwd=REPO,
    capture_output=True,
).stdout

tool = REPO / "tools/p2_h2_v3_controlled_execute.py"
tool_before = "aa8e8cb44c16adc57dc00d6db8a9769662bee88700280b270d021e85cd7e97cb"
tool_after = sha(tool)

current = set(tracked())
payload = {
    "schema_version": "v3-fix1-independent-rollback-summary/v0.1",
    "budget": {
        "before": budget["before"],
        "after": budget["after"],
        "byte_offset": budget["first_diff_offset"],
        "byte_before_after": budget["byte_at_first_diff"],
        "only_changed_leaf": budget["deep_changed_leaves"],
        "sha_matches_original": budget["sha_matches_original_40"],
        "stages_unchanged": budget["stages_unchanged"],
        "ledger_field_unchanged": budget["ledger_field_unchanged"],
    },
    "p2_holdout_plan": {
        "current_sha256": sha(plan_path),
        "current_bytes": plan_path.stat().st_size,
        "expected_baseline_sha256": "d0cb23de2cff80a743c086a8723edd80654d64b22f4e18f97973dd83b153cd25",
        "matches": sha(plan_path)
        == "d0cb23de2cff80a743c086a8723edd80654d64b22f4e18f97973dd83b153cd25",
        "head_content_sha256": hashlib.sha256(plan_head_bytes).hexdigest(),
        "head_content_matches": hashlib.sha256(plan_head_bytes).hexdigest()
        == sha(plan_path),
        "git_diff_empty": plan_diff_empty,
    },
    "tracked_modified": {
        "count": len(current),
        "expected_baseline_15_present": all(p in current for p in BASELINE_15),
        "baseline_15_missing": [p for p in BASELINE_15 if p not in current],
        "fix1_7_present": all(p in current for p in FIX1_7),
        "fix1_7_missing": [p for p in FIX1_7 if p not in current],
        "extra": sorted(current - set(BASELINE_15) - set(FIX1_7)),
        "decomposition": "15 pre-existing baseline + 7 fix-1 files = 22; p2_holdout_plan no longer modified",
    },
    "plans_and_go": {
        "plans_dir": r"D:\mktkb-p2-h2v3-20261115\rollback-40\plans",
        "go_dir": r"D:\mktkb-p2-h2v3-20261115\rollback-40\go",
        "dial": go["dial"],
        "runs": [
            {
                "run_index": r["run_index"],
                "scenario_id": r["scenario_id"],
                "plan_sha256": r["plan_sha256"],
                "plan_file_sha256": r["plan_file_sha256"],
                "go_sha256": r["go_sha256"],
                "before_go_sha256": install["runs"][r["run_index"]]["before"]["sha256"],
                "archive_sha256": install["runs"][r["run_index"]]["archive"]["sha256"],
                "max_requests": r["max_requests"],
                "budget_total_limit_cny": r["budget_total_limit_cny"],
                "preflight_ok": r["preflight_ok"],
                "requests_remaining": r["authorization_requests_remaining"],
            }
            for r in go["runs"]
        ],
        "contract_validate_run_all_ok": True,
        "check_only": [
            {
                "run_index": i,
                "ok": json.loads(
                    (HERE / "rollback-40" / "check" / f"run{i}.json").read_text(encoding="utf-8")
                )["ok"],
                "zero_send": json.loads(
                    (HERE / "rollback-40" / "check" / f"run{i}.json").read_text(encoding="utf-8")
                )["zero_send"],
                "zero_write": json.loads(
                    (HERE / "rollback-40" / "check" / f"run{i}.json").read_text(encoding="utf-8")
                )["zero_write"],
            }
            for i in range(4)
        ],
        "ledger_unchanged": pres["ledger_unchanged"],
        "ledger_sha256": go["ledger"]["sha256"],
        "reservation_count": go["ledger"]["reservation_count"],
    },
    "companion_tool_change": {
        "path": "tools/p2_h2_v3_controlled_execute.py",
        "tracked": False,
        "before_sha256": tool_before,
        "after_sha256": tool_after,
        "change": "V3_PROJECT_TOTAL_LIMIT_CNY 50.0 -> 40.0（另改同行注释）",
        "reason": "唯一受控 v3 入口在导入期把该值写入 MKTKB_PROJECT_TOTAL_LIMIT_CNY；"
                  "不改则 check-only 会以 env_total_limit_mismatch 拒绝 40 预算。",
    },
    "tests": {
        "unit_rag": {"collected": 740, "passed": 738, "failed": 2, "exit": 1,
                     "log": "pytest-unit-rag-after-rollback.log"},
        "new_22": {"collected": 22, "passed": 22, "failed": 0, "exit": 0,
                   "log": "pytest-new-22-after-rollback.log"},
        "drift_two_no_env": {"collected": 22, "passed": 20, "failed": 2, "exit": 1,
                             "log": "pytest-drift-2-after-rollback.log"},
        "drift_two_env40": {"collected": 22, "passed": 21, "failed": 1, "exit": 1,
                            "log": "pytest-drift2-with-env40.log"},
        "fix_touched_3_files": {"collected": 23, "passed": 23, "failed": 0, "exit": 0,
                                "log": "pytest-fix-touched-tests.log"},
        "unit_rag_netguard": {"collected": 740, "passed": 738, "failed": 2, "exit": 1,
                              "external_attempts": 0, "loopback_calls": 55,
                              "log": "pytest-unit-rag-netguard.log"},
        "drift_failures": [
            "tests/unit/test_s2h_r3_official_profile.py::test_official_profile_accepted_by_both_entries_and_worst_case_is_2103552"
            " — 未设 MKTKB_PROJECT_TOTAL_LIMIT_CNY 时 live_authorization 默认 10.0 vs budget 40；env=40 时通过（14/14）。",
            "tests/rag/test_s4_stage_limit.py::test_current_go_and_budget_are_consistent_and_above_three_yuan"
            " — 第 208 行硬编码 budget['limit_cny']==20.0；40/50 都不通过；sum(stages)+historical=40 的断言现已通过。",
        ],
    },
    "preservation": {
        "head_same": pres["git"]["head_same"],
        "branch_same": pres["git"]["branch_same"],
        "commits": pres["git"]["commits"],
        "staged_after": pres["git"]["staged_after"],
        "c_freeze_12_all_equal": pres["c_freeze_12_all_equal"],
        "freeze32": pres["v3_freeze_32"],
        "external_ciphertext_corpus_changed": pres["external_ciphertext_corpus_changed"],
        "fixtures_changed": pres["fixtures_acceptance_h2v3_changed"],
        "ledger_unchanged": pres["ledger_unchanged"],
        "scenarios_py_unchanged": pres["scenarios_py_unchanged"],
        "scenarios_v3_py_unchanged": pres["scenarios_v3_py_unchanged"],
        "protected_changes_expected": pres["protected_changes_expected"],
    },
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
               encoding="utf-8")
print(json.dumps({k: payload[k] for k in ("budget", "p2_holdout_plan", "tracked_modified",
                                          "companion_tool_change")}, ensure_ascii=False, indent=1))
