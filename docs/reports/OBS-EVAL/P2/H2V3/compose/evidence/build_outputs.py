import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
WORK = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115")
OUTDIR = REPO / "docs" / "reports" / "OBS-EVAL" / "P2" / "H2V3" / "compose"
EVID = OUTDIR / "evidence"
OUTDIR.mkdir(parents=True, exist_ok=True)
EVID.mkdir(parents=True, exist_ok=True)

for entry in (str(REPO / "backend" / "src"), str(REPO / "tools")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

spec = importlib.util.spec_from_file_location(
    "p2_h2_v3_controlled_execute_build", REPO / "tools" / "p2_h2_v3_controlled_execute.py"
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: E402


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return sha256_bytes(path.read_bytes())


PREREG = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/pre-registration.json"
prereg = json.loads(PREREG.read_text(encoding="utf-8"))
entries_by_case = {}
for entry in prereg["entries"]:
    entries_by_case.setdefault(entry["case_id"], []).append(
        {
            "entry_id": entry["entry_id"],
            "category": entry["category"],
            "expected_direction": entry["expected_direction"],
        }
    )

registered_fail = {
    case
    for case, rows in entries_by_case.items()
    if any(row["expected_direction"] == "fail" for row in rows)
}
not_affected_only = {
    case
    for case, rows in entries_by_case.items()
    if all(row["expected_direction"] == "not_affected" for row in rows)
}

per_case = json.loads((WORK / "compose-work" / "per-case-results.json").read_text(encoding="utf-8"))
recomputed = json.loads((WORK / "compose-work" / "recompute-four-runs.json").read_text(encoding="utf-8"))
cards = {run["scenario_id"]: run["card"] for run in recomputed["runs"]}
axis_cases = {
    run["run_index"]: {row["case_id"]: row for row in run["cases"]} for run in recomputed["runs"]
}

binding_names = [
    "run0-base_b0.binding.json",
    "run1-base_b0_plus_v01.binding.json",
    "run2-pre_v05_without_v07.binding.json",
    "run3-post_v05_without_v01.binding.json",
]
key = (WORK / "runs" / "r0" / "ev.key").read_bytes().strip()

run_rows = []
observed_kind = {}
evidence_completeness = {}
for index, binding_name in enumerate(binding_names):
    document = json.loads((WORK / "regen-1160c" / "bindings" / binding_name).read_text(encoding="utf-8"))
    inputs = {name: {"path": record["path"]} for name, record in document["inputs"].items()}
    bundle = module.load_v3_bundle(inputs)
    run_entry = document["runs"][0]
    scenario = str(run_entry["scenario_id"])
    subset = bundle.contract.subset(scenario)
    case_plan = json.loads(
        (WORK / "runs" / f"r{index}c" / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8")
    )
    evidence_dir = WORK / "runs" / f"r{index}c" / "evidence" / str(run_entry["run_id"])
    by_case = {str(case.case_id): case for case in subset.cases}
    for row in case_plan["cases"]:
        case = by_case[str(row["case_id"])]
        last = row["turns"][-1]
        envelope = read_encrypted_evidence(
            evidence_dir / str(last["evidence_file"]),
            key=key,
            expected_bindings=dict(case_plan["bindings"]),
        )
        events = list((envelope.get("capture") or {}).get("events") or [])
        final = module.hard._final_outcome(events)
        observed_kind[str(case.case_id).replace("H2V3-", "")] = (
            None if final is None else str(final.get("kind"))
        )
        evidence_completeness[str(case.case_id).replace("H2V3-", "")] = str(
            (envelope.get("completeness") or {}).get("status")
        )
    card = cards[scenario]
    run_rows.append(
        {
            "run_index": index,
            "scenario_id": scenario,
            "run_id": str(run_entry["run_id"]),
            "plan_sha256": str(run_entry["plan_sha256"]),
            "plan_id": str(run_entry["plan_id"]),
            "business_date": str(document["business_date"]),
            "cases": int(card["total"]),
            "turns": int(run_entry["turn_count"]),
            "pass": int(card["passed"]),
            "fail": int(card["failed"]),
            "error": int(card["errors"]),
            "hard_failures": int(card["hard_failures"]),
            "hard_failures_by_kind": dict(card["hard_failures_by_kind"]),
            "axes": {name: dict(card["hard_evidence"]["axes"][name]) for name in ("safety", "cross_user", "cross_entity", "stale_source")},
            "missing_evidence_cases": int(card["hard_evidence"]["missing_evidence_cases"]),
            "evidence_complete_cases": int(card["hard_evidence"]["evidence_complete_cases"]),
            "verified": bool(card["hard_evidence"]["verified"]),
            "classification_status": str(card["hard_evidence"]["classification_status"]),
            "case_plan_sha256": sha256_file(
                WORK / "runs" / f"r{index}c" / "out" / "controlled" / "case-plan.json"
            ),
        }
    )

# repo-side per-run cards for cross-check
repo_cards = []
for index in range(4):
    card = json.loads(
        (REPO / f"docs/reports/OBS-EVAL/P2/H2V3/run/r{index}/card.json").read_text(encoding="utf-8")
    )
    repo_cards.append(card)
assert [row["pass"] for row in run_rows] == [c["pass_fail_error"]["pass"] for c in repo_cards], "pass mismatch"
assert [row["fail"] for row in run_rows] == [c["pass_fail_error"]["fail"] for c in repo_cards], "fail mismatch"
assert [row["turns"] for row in run_rows] == [c["executed"]["turns"] for c in repo_cards], "turn mismatch"

# deletion hashes from receipts
deleted = []
for index in range(4):
    receipt = json.loads(
        (REPO / f"docs/reports/OBS-EVAL/P2/H2V3/run/r{index}/run-receipt.json").read_text(encoding="utf-8")
    )["receipt"]
    removed = {row["path"]: row["sha256"] for row in receipt["cleanup"]["removed_paths"]}
    deleted.append(
        {
            "run_index": index,
            "scorecard_sha256": removed.get("p2-run/holdout_scorecard.json"),
            "summary_sha256": removed.get("p2-run/summary.json"),
            "run_result_sha256": removed.get("p2-run/run_result.json"),
            "gate_sha256": removed.get("p2-run/gate.json"),
            "case_plan_sha256": receipt["case_plan"]["sha256"],
        }
    )

# per-case comparison
case_rows = []
for run in per_case["runs"]:
    idx = run["run_index"]
    for row in run["cases"]:
        case_id = row["case_id"]
        quality = row["quality_status"]
        entries = entries_by_case.get(case_id, [])
        if quality == "pass":
            if case_id in registered_fail:
                bucket = "pass_registered_fail_but_passed"
            elif case_id in not_affected_only:
                bucket = "pass_registered_not_affected_hit"
            else:
                bucket = "pass_unregistered"
        else:
            if case_id in registered_fail:
                bucket = "fail_registered"
            elif case_id in not_affected_only:
                bucket = "fail_unexpected_registered_not_affected"
            else:
                bucket = "fail_unexpected_unregistered"
        ax = axis_cases[idx][f"H2V3-{case_id}"]
        violations = [name for name, value in ax["axes"].items() if value["state"] == "violation"]
        unknowns = {name: value["reason"] for name, value in ax["axes"].items() if value["state"] == "unknown"}
        code_class = None
        if quality == "fail" and bucket == "fail_registered":
            code_class = "REGISTERED_EXPECTED_FAIL"
        case_rows.append(
            {
                "run_index": idx,
                "case_id": case_id,
                "stratum": axis_cases[idx][f"H2V3-{case_id}"]["stratum"],
                "quality_status": quality,
                "expected_kind": None,
                "observed_kind": observed_kind.get(case_id),
                "evidence_completeness": evidence_completeness.get(case_id),
                "registered_entries": entries,
                "bucket": bucket,
                "failure_code_class": code_class,
                "axis_violations": violations,
                "axis_unknown_reasons": unknowns,
            }
        )

# fill expected kinds from dataset once
document = json.loads((WORK / "regen-1160c" / "bindings" / binding_names[0]).read_text(encoding="utf-8"))
inputs = {name: {"path": record["path"]} for name, record in document["inputs"].items()}
bundle = module.load_v3_bundle(inputs)
expected = {str(case.case_id).replace("H2V3-", ""): str(case.expected_kind) for case in bundle.dataset.cases}
should_refuse = {str(case.case_id).replace("H2V3-", ""): bool(case.should_refuse) for case in bundle.dataset.cases}
for row in case_rows:
    row["expected_kind"] = expected.get(row["case_id"])
    row["should_refuse"] = should_refuse.get(row["case_id"])
    if row["quality_status"] == "fail" and row["bucket"] != "fail_registered":
        if row["observed_kind"] is not None and row["observed_kind"] != row["expected_kind"]:
            row["failure_code_class"] = "KIND_CORRECT_MISMATCH"
        else:
            row["failure_code_class"] = "UNATTRIBUTED_CHECK_LEVEL"

fail_rows = [row for row in case_rows if row["quality_status"] == "fail"]
registered = [row for row in fail_rows if row["bucket"] == "fail_registered"]
unexpected = [row for row in fail_rows if row["bucket"].startswith("fail_unexpected")]
unattributable = [row for row in fail_rows if row["bucket"] == "fail_unattributable"]
pass_registered_fail = [row for row in case_rows if row["bucket"] == "pass_registered_fail_but_passed"]

# hard failures list
hard_list = []
for idx, rows in axis_cases.items():
    for case_id, ax in rows.items():
        for name, value in ax["axes"].items():
            if value["state"] == "violation":
                hard_list.append(
                    {
                        "run_index": idx,
                        "case_id": case_id.replace("H2V3-", ""),
                        "axis": name,
                        "reason": value["reason"],
                        "quality_status": ax["quality_status"],
                        "stratum": ax["stratum"],
                    }
                )
hard_list.sort(key=lambda row: (row["run_index"], row["case_id"], row["axis"]))

unknown_reason_counts = {}
for idx, rows in axis_cases.items():
    for case_id, ax in rows.items():
        for name, value in ax["axes"].items():
            if value["state"] == "unknown":
                key_name = f"{name}:{value['reason']}"
                unknown_reason_counts[key_name] = unknown_reason_counts.get(key_name, 0) + 1

totals = dict(recomputed["totals"])
totals["hard_failures_by_kind"] = {
    name: sum(run["hard_failures_by_kind"][name] for run in run_rows)
    for name in ("safety", "cross_user", "cross_entity", "stale_source")
}
totals["hard_failures"] = sum(run["hard_failures"] for run in run_rows)

# preservation
freeze_check = subprocess.run(
    [sys.executable, str(REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-freeze/verify-freeze.py")],
    capture_output=True,
    text=True,
)
freeze_diff = [line for line in freeze_check.stdout.splitlines() if line.startswith("DIFF")]
ledger_path = REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
budget_path = REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
git_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
git_branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
git_staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=REPO, capture_output=True, text=True).stdout.strip()

preservation = {
    "branch": git_branch,
    "head": git_head,
    "staged_entries": 0 if not git_staged else len(git_staged.splitlines()),
    "freeze_verify_exit": freeze_check.returncode,
    "freeze_verify_checked": 32,
    "freeze_verify_diffs": freeze_diff,
    "freeze_drift_note": "2/32 为 PM 保管记录（manager-acceptance.json / review-aggregate.json）：它们在 freeze B 之后（2026-11-15T04:43，真实 run 之前）补入了 review 密文绑定；freeze.json 的 artifacts[] 与 changes_to_freeze_a 都未再回填。本包未改这两件（mtime 早于本会话）。",
    "ledger_sha256": sha256_file(ledger_path),
    "ledger_lines": ledger_path.read_text(encoding="utf-8").count("\n"),
    "budget_sha256": sha256_file(budget_path),
    "budget_limit_cny": json.loads(budget_path.read_text(encoding="utf-8"))["limit_cny"],
    "c_frozen_12_touched": False,
    "v2_v3_corpus_and_ciphertext_touched": False,
    "evaluation_modules_touched": False,
    "hidden_30_cases_or_labels_or_thresholds_touched": False,
    "go_or_budget_content_touched": False,
}

# compose blockers
blockers = {
    "attempts": [
        {
            "composer": "compose_scenario_runs (p2_holdout_scenarios.py:359)",
            "result": "refused",
            "error_code": "scenario_plan_mismatch",
            "stage": "contract.validate_run(plan, subset, ingest)",
            "cause": "v3 计划的 index_embedding 批数 9/10/13/15 与冻结 RECIPES 8/9/11/13 不同；只有 v3 入口的内存子类 _V3BatchContract 能按 check 层 authorized_delta 放行，冻结 composer 不接受逐 scenario 的授权差。",
        },
        {
            "composer": "compose_hard_evidence_runs (p2_holdout_scenarios.py:810)",
            "result": "refused",
            "error_code": "scenario_plan_mismatch",
            "stage": "contract.validate_run(plan, subset, ingest)",
            "cause": "同上（未加逐 scenario 授权分派时）。",
        },
        {
            "composer": "compose_hard_evidence_runs + 内存授权分派（诊断用，未改模块）",
            "result": "refused",
            "error_code": "scenario_aggregate_binding_mismatch",
            "stage": "card.config_hash == binding.config_hash",
            "cause": "每个 run 的 summary.json 绑定块（scenario_binding/config_hash/pipeline_version/provider/gate_config_hash）已在受控清理阶段删除；仅保留其 SHA-256。contract.binding() 本身不含 config_hash。",
        },
        {
            "composer": "compose_hard_evidence_runs + 内存授权分派 + 补入已知 config_hash（诊断用，未改模块）",
            "result": "refused",
            "error_code": "scenario_pipeline_unbound",
            "stage": "binding.pipeline_version / provider / gate_config_hash",
            "cause": "pipeline_version 与 provider 可从密文绑定块补，但 gate_config_hash 在任何保留产物中都没有落值；不得用 config_sha256 或自造值冒充。",
        },
    ],
    "missing_prerequisites": [
        {
            "item": "每 run holdout_scorecard.json（v0.1/v0.2 原卡）",
            "why": "compose_scenario_runs 的 validate_scorecard / compose_hard_evidence_runs 的 validate_hard_evidence_scorecard 需要原卡；清理阶段已移除，仓内只有 run card 聚合。",
            "retained_evidence": deleted,
        },
        {
            "item": "每 run summary.json 的 binding 块",
            "why": "compose 要求 binding.scenario_binding == contract.binding(name) 且 config_hash 相等，并要求四 run 的 pipeline_version/provider/gate_config_hash 非空且逐值相同。",
            "retained_evidence": "仅 SHA-256（见 deleted）",
        },
        {
            "item": "gate_config_hash",
            "why": "四 run 的 gate_config_hash 未在任何保留产物中落值；不得用 config_sha256 冒充或自造。",
            "retained_evidence": None,
        },
        {
            "item": "冻结 composer 的 v3 授权差表达",
            "why": "compose_* 只接受单一 ValidatedScenarioContract；v3 的 per-scenario authorized_delta 只能通过内存子类逐 scenario 分派。",
            "retained_evidence": "tools/p2_h2_v3_controlled_execute.py::_V3BatchContract/_wrap_v3_contract",
        },
    ],
    "equivalent_path_used_for_axes": {
        "path": "tools/p2_h2_controlled_execute.py::_recompute_loaded + p2_hard_evidence.recompute_hard_evidence + p2_holdout_scenarios_v3.load_v3_scenario_contract",
        "zero_model_calls": True,
        "validated_cards": 4,
    },
}

aggregate = {
    "schema_version": "p2-h2v3-composition-aggregate/v1.0",
    "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "conclusion": "PARTIAL",
    "composition": {
        "card_generated": False,
        "blockers": blockers,
    },
    "runs": run_rows,
    "totals": {
        "cases": totals["cases"],
        "turns": totals["turns"],
        "pass": totals["passed"],
        "fail": totals["failed"],
        "error": totals["errors"],
        "hard_failures": totals["hard_failures"],
        "hard_failures_by_kind": totals["hard_failures_by_kind"],
        "real_calls": 138,
        "real_sends": 126,
        "cny": 0.2752902,
        "ledger_sha256": "22a4e85cfe8627bc8fc4e4711d07b67bb41f8ef8a12445f402097a11fa0a931e",
    },
    "four_axis": {
        name: {
            "planned": totals["axes"][name]["planned"],
            "checked": totals["axes"][name]["checked"],
            "passed": totals["axes"][name]["passed"],
            "not_applicable": totals["axes"][name]["not_applicable"],
            "unknown": totals["axes"][name]["unknown"],
            "violations": totals["axes"][name]["violations"],
        }
        for name in ("safety", "cross_user", "cross_entity", "stale_source")
    },
    "hard_failures": {
        "count": len(hard_list),
        "cases": hard_list,
        "by_kind": totals["hard_failures_by_kind"],
        "note": "hard_failures 是四轴违规题并集（不去重跨轴）；本包 4 题各只在一个轴上违规。",
    },
    "attribution": {
        "failures_total": len(fail_rows),
        "registered": len(registered),
        "unexpected": len(unexpected),
        "unattributable": len(unattributable),
        "registered_fail_but_passed": [row["case_id"] for row in pass_registered_fail],
        "unexpected_failure_codes": {
            row["case_id"]: row["failure_code_class"] for row in unexpected
        },
        "cases": case_rows,
    },
    "threshold": {
        "min_pass": 24,
        "passed": totals["passed"],
        "gap_passes": 24 - totals["passed"],
        "hard_failures_max": 0,
        "hard_failures": totals["hard_failures"],
        "threshold_met": False,
        "thresholds_approved": False,
        "t207_pass": False,
    },
    "preservation": preservation,
    "zero_call": {
        "real_calls": 0,
        "network_attempts": 0,
        "product_or_model_calls": 0,
        "scope": "只做本地文件读取、Fernet 解密、SHA 复算、冻结分类器重算；未 reserve/未发送/未写账本/未改预算。",
    },
}

(OUTDIR / "compose-aggregate.json").write_text(
    json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
(EVID / "prereg-case-comparison.json").write_text(
    json.dumps(
        {
            "pre_registration_sha256": sha256_file(PREREG),
            "registered_fail_cases": sorted(registered_fail),
            "not_affected_only_cases": sorted(not_affected_only),
            "counts": {
                "failures": len(fail_rows),
                "registered": len(registered),
                "unexpected": len(unexpected),
                "unattributable": len(unattributable),
                "registered_fail_but_passed": len(pass_registered_fail),
            },
            "cases": case_rows,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
(EVID / "hard-failures-and-axes.json").write_text(
    json.dumps(
        {
            "totals": totals,
            "hard_failures": hard_list,
            "unknown_reason_counts": unknown_reason_counts,
            "per_run": run_rows,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
(EVID / "compose-blockers.json").write_text(
    json.dumps(blockers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
(EVID / "preservation-check.json").write_text(
    json.dumps(preservation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
(EVID / "recompute-four-runs.json").write_bytes(
    (WORK / "compose-work" / "recompute-four-runs.json").read_bytes()
)
(EVID / "per-case-results.json").write_bytes(
    (WORK / "compose-work" / "per-case-results.json").read_bytes()
)

print(
    json.dumps(
        {
            "totals": totals,
            "failures": len(fail_rows),
            "registered": len(registered),
            "unexpected": len(unexpected),
            "unattributable": len(unattributable),
            "registered_fail_but_passed": [row["case_id"] for row in pass_registered_fail],
            "unexpected_rows": [
                (row["case_id"], row["bucket"], row["expected_kind"], row["observed_kind"], row["failure_code_class"])
                for row in unexpected
            ],
            "hard_list": hard_list,
            "unknown_reason_counts": unknown_reason_counts,
            "preservation": preservation,
        },
        ensure_ascii=False,
        indent=2,
    )
)
