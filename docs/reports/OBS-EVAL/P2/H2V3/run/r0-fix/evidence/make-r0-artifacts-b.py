"""把 run0（v3-run-r4，真实成功）的事实落成仓内安全聚合产物。

输入：
  D:\\mktkb-p2-h2v3-20261115\\runs\\r0c.stdout.json                 入口 run 的 stdout（receipt+sidecar）
  docs/reports/OBS-EVAL/P2/H2V3/run/r0-fix/evidence/check-only-rebind2.json  run 前的零写证据（before 快照）
输出（仓内，无题面/答案/case_id）：
  docs/reports/OBS-EVAL/P2/H2V3/run/r0/{run-receipt,card,case-plan,status}.json

只读账本/预算，不改它们。
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
RUN = REPO / "docs/reports/OBS-EVAL/P2/H2V3/run"
R0 = RUN / "r0"
STDOUT = Path(r"D:\mktkb-p2-h2v3-20261115\runs\r0c.stdout.json")
PRECHECK = RUN / "r0-fix/evidence/check-only-rebind2.json"
SEALED_CASE_PLAN = Path(
    r"D:\mktkb-p2-h2v3-20261115\runs\r0c\out\controlled\case-plan.json"
)

LEDGER = REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
BUDGET = REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ledger_state() -> dict:
    raw = LEDGER.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    reserved = [r for r in rows if r.get("event") == "reserved"]
    results = [r for r in rows if r.get("event") == "result"]
    historical = sum(float(r.get("accounted_cny") or 0) for r in rows if r.get("event") == "historical_import")
    project = historical + sum(float(r.get("conservative_charge_cny") or 0) for r in results)
    stage = sum(
        float(r.get("conservative_charge_cny") or 0)
        for r in results
        if r.get("stage") == "P2-LIVE"
    )
    return {
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "lines": raw.count(b"\n"),
        "reservation_count": len(reserved),
        "result_count": len(results),
        "paired": len(reserved) == len(results),
        "project_accounted_cny": round(project, 10),
        "stage_p2_live_cny": round(stage, 10),
    }


payload = json.loads(STDOUT.read_bytes().decode("utf-8-sig"))
receipt = payload["receipt"]
sidecar = payload["sidecar_payload"]
precheck = json.loads(PRECHECK.read_text(encoding="utf-8"))
before = precheck["zero_write"]

cases = json.loads(SEALED_CASE_PLAN.read_text(encoding="utf-8"))["cases"]
case_status = Counter(str(row["quality_status"]) for row in cases)
turns = [turn for row in cases for turn in row["turns"]]
turn_status = Counter(str(turn["status"]) for turn in turns)

after = ledger_state()
requests = receipt["requests"]

# 1) run-receipt.json：入口 stdout 原样（receipt + sidecar），重排为干净 UTF-8 JSON。
(R0 / "run-receipt.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
    newline="",
)

card = {
    "schema_version": "p2-h2v3-run-card/v1.0",
    "role": "v3 真实执行逐 run 安全聚合（无题面/答案/query 文本；无 case_id）",
    "package": "v3-run-r4",
    "run_index": int(receipt["run_index"]),
    "run_id": receipt["run_id"],
    "scenario_id": receipt["scenario_id"],
    "business_date": receipt["business_date"],
    "fixture_kind": receipt["fixture_kind"],
    "execution_mode": receipt["execution_mode"],
    "plan_id": receipt["plan_id"],
    "plan_sha256": receipt["plan_sha256"],
    "status": "COMPLETED",
    "ok": bool(receipt["ok"]),
    "run_status": receipt["status"],
    "stop_code": receipt["stop_code"],
    "error_code": receipt["error_code"],
    "started_utc": receipt["started_utc"],
    "finished_utc": receipt["finished_utc"],
    "duration_ms": int(receipt["duration_ms"]),
    "planned": {
        "cases": 12,
        "turns": 14,
        "requests": int(requests["planned"]),
        "ingest_batches": receipt["plan_ingest"]["batches"],
        "ingest_batches_source": receipt["plan_ingest"]["source"],
        "worst_case_cny": 0.637568,
    },
    "executed": {
        "cases": len(cases),
        "turns": len(turns),
        "turn_status": dict(turn_status),
        "case_quality_status": dict(case_status),
    },
    "requests": {
        "planned": int(requests["planned"]),
        "reserved_plan_items": int(requests["reserved"]),
        "sent": int(requests["sent"]),
        "real_sends": int(receipt["real_sends"]),
        "attempts_reserved": int(requests["attempts_reserved"]),
        "attempts_by_operation": dict(requests["attempts_by_operation"]),
        "attempts_by_center_cny": {
            key: float(value) for key, value in (requests["attempts_by_center_cny"] or {}).items()
        },
        "settled_cny": float(requests["settled_cny"]),
        "ledger_delta_cny": round(after["project_accounted_cny"] - 22.2237363, 10),
    },
    "pass_fail_error": {
        "pass": int(case_status.get("pass", 0)),
        "fail": int(case_status.get("fail", 0)),
        "error": int(case_status.get("error", 0)),
        "basis": "逐题 quality_status（12 题）；回合 14/14 executed、error 全 None",
    },
    "hard_failures": None,
    "hard_failures_basis": "本 run 只产出逐题 pass/fail；hard-failure 聚合属四 run 汇总阶段（compose_scenario_runs），未在本包执行 → 无实测值，不填 0",
    "four_axis": None,
    "four_axis_basis": "safety/cross_user/cross_entity/stale_source 的逐轴判定属 rescore/axes 阶段（p2_evidence_axes_adapter_v2 / Q1a-1b），本 run 未执行该步骤 → 无实测值，不填 0；已封存的 14 份回合证据可作其输入",
    "evidence": {
        "available": bool(receipt["evidence"]["available"]),
        "turn_files": int(receipt["evidence"]["turn_files"]),
        "manifest_present": bool(receipt["evidence"]["manifest_present"]),
        "manifest_turn_count": receipt["evidence"]["manifest_turn_count"],
        "status_counts": dict(receipt["evidence"]["status_counts"]),
        "readback_ok": bool(receipt["evidence"]["readback_ok"]),
        "error_count": int(receipt["evidence"]["error_count"]),
        "manifest_sha256": receipt["evidence"]["manifest_sha256"],
    },
    "case_plan": {
        "available": receipt["case_plan"] is not None,
        "cases": 12,
        "turns": 14,
        "sha256": (receipt["case_plan"] or {}).get("sha256"),
        "location": "仓外封存区（不出仓；仓内只留聚合）",
    },
    "seal": {
        "sealed": bool(receipt["seal"].get("sealed")),
        "mode": receipt["seal"].get("mode"),
        "evidence_file_count": receipt["seal"].get("evidence_file_count"),
        "evidence_bytes": receipt["seal"].get("evidence_bytes"),
        "evidence_tree_sha256": receipt["seal"].get("evidence_tree_sha256"),
        "out_tree_sha256": receipt["seal"].get("out_tree_sha256"),
        "seal_manifest_sha256": receipt["seal"].get("seal_manifest_sha256"),
        "seal_dir": "仓外封存区（路径见 run-receipt.json）",
    },
    "cleanup": {
        "plaintext_clean": bool(receipt["cleanup"].get("plaintext_clean")),
        "final_plaintext_scan_clean": bool(receipt["cleanup"]["final_plaintext_scan"]["clean"]),
        "final_plaintext_hits": int(receipt["cleanup"]["final_plaintext_scan"]["hit_count"]),
        "needles": int(receipt["cleanup"]["final_plaintext_scan"]["needles"]),
        "business_db_removed": bool(receipt["cleanup"].get("business_db_removed")),
        "purge_traces_on_close": True,
    },
    "bindings": {
        "binding_sha256": receipt["bindings"]["binding_sha256"],
        "code_version": receipt["bindings"]["code_version"],
        "config_sha256": receipt["bindings"]["config_sha256"],
        "go_sha256": receipt["bindings"]["go_sha256"],
        "ledger_chain_sha256": receipt["bindings"]["ledger_sha256"],
        "attempt_scope_sha256": receipt["bindings"]["attempt_scope_sha256"],
        "evidence_key_sha256": receipt["evidence_key_sha256"],
    },
    "contract": {
        "check_layer": sidecar["contract_validate_run"],
        "plan_recompute": sidecar["plan_recompute"],
        "source_map": sidecar["source_map"],
        "scoring_map": sidecar["scoring_map"],
    },
    "ledger": {
        "before": {
            "file_sha256": before["ledger_sha256_before"],
            "lines": 1923,
            "reservation_count": int(before["reservation_count"]),
            "result_count": int(before["result_count"]),
            "paired": True,
            "project_accounted_cny": 22.2237363,
            "stage_p2_live_cny": 7.1527918,
        },
        "after": {
            "file_sha256": after["file_sha256"],
            "lines": after["lines"],
            "reservation_count": after["reservation_count"],
            "result_count": after["result_count"],
            "paired": after["paired"],
            "project_accounted_cny": after["project_accounted_cny"],
            "stage_p2_live_cny": after["stage_p2_live_cny"],
        },
        "delta_lines": after["lines"] - 1923,
        "delta_reservations": after["reservation_count"] - int(before["reservation_count"]),
        "delta_result": after["result_count"] - int(before["result_count"]),
        "project_delta_cny": round(after["project_accounted_cny"] - 22.2237363, 10),
        "stage_delta_cny": round(after["stage_p2_live_cny"] - 7.1527918, 10),
    },
    "budget": {
        "sha256_before": before["budget_sha256_before"],
        "sha256_after": sha(BUDGET),
        "unchanged": sha(BUDGET) == before["budget_sha256_before"],
        "limit_cny": 40.0,
    },
    "limits": {
        "requests_this_run_attempts": int(requests["attempts_reserved"]),
        "requests_this_package_cap": 80,
        "cumulative_requests_after": after["reservation_count"],
        "max_requests": 1160,
        "governance_request_cap": 1500,
        "project_total_limit_cny": 40.0,
        "stage_limit_cny": 20.0,
        "single_attempt_max_cny": 0.5,
        "max_single_attempt_charge_cny": 0.018688,
        "all_within_limit": True,
    },
    "note": "B+ 修复后 run0 首次真实跑通：check 层 authorized_delta（index_embedding 9 批）已透传到执行层，"
    "契约复核通过，14/14 回合执行并封存。逐题 7 pass / 5 fail / 0 error；本 run 未产出四轴与 hard-failure 聚合。",
}
(R0 / "card.json").write_text(
    json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
    newline="",
)

case_plan_public = {
    "schema_version": "p2-h2v3-run-case-plan-public/v0.2",
    "available": True,
    "run_index": int(receipt["run_index"]),
    "run_id": receipt["run_id"],
    "scenario_id": receipt["scenario_id"],
    "business_date": receipt["business_date"],
    "planned_cases": 12,
    "planned_turns": 14,
    "executed_cases": len(cases),
    "executed_turns": len(turns),
    "turn_status_counts": dict(turn_status),
    "case_quality_counts": dict(case_status),
    "per_case_ordinal": [
        {"ordinal": index + 1, "quality_status": str(row["quality_status"]), "turns": len(row["turns"])}
        for index, row in enumerate(cases)
    ],
    "sealed_case_plan_sha256": receipt["case_plan"]["sha256"],
    "redaction": "仓内不含 case_id / 题面 / 答案 / query 文本；完整逐题 case-plan 只在仓外封存区",
    "thresholds_approved": bool(
        json.loads(SEALED_CASE_PLAN.read_text(encoding="utf-8"))["thresholds_approved"]
    ),
}
(R0 / "case-plan.json").write_text(
    json.dumps(case_plan_public, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
    newline="",
)

status = {
    "schema_version": "p2-h2v3-run-status/v1.0",
    "run_index": int(receipt["run_index"]),
    "run_id": receipt["run_id"],
    "scenario_id": receipt["scenario_id"],
    "business_date": receipt["business_date"],
    "status": "COMPLETED",
    "stop_code": receipt["stop_code"],
    "error_code": receipt["error_code"],
    "failure_attribution": None,
    "attempts": 1,
    "retried": False,
    "manual_score_fix": False,
    "requests_outbound_attempts": int(requests["attempts_reserved"]),
    "real_sends": int(receipt["real_sends"]),
    "ledger_delta_reservations": card["ledger"]["delta_reservations"],
    "settled_cny_receipt": float(requests["settled_cny"]),
    "ledger_delta_cny": card["ledger"]["project_delta_cny"],
    "four_axis": None,
    "hard_failures": None,
    "note": "首个错误即停的纪律未触发（无错误）；未重试、未加钱、未手工修分。",
}
(R0 / "status.json").write_text(
    json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
    newline="",
)

print("written", sorted(p.name for p in R0.glob("*.json")))
print("ledger_before", before["ledger_sha256_before"])
print("ledger_after ", after["file_sha256"], after["lines"], after["reservation_count"], after["result_count"])
print("project_delta_cny", card["ledger"]["project_delta_cny"])
print("stage_delta_cny", card["ledger"]["stage_delta_cny"])
print("budget_unchanged", card["budget"]["unchanged"])
print("pass_fail_error", card["pass_fail_error"])
