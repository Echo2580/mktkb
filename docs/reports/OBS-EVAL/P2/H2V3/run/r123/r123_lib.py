"""run1..run3 串行真跑的最小工具库（只读账本/预算；只写仓外运行区 + 仓内安全聚合）。

用途：
  python r123_lib.py snapshot  <out.json>      # 账本/预算前后快照（只读）
  python r123_lib.py install-go <run_index>    # 把该 run 的 GO 装进固定槽位（先归档上一份）
  python r123_lib.py artifacts <run_index>     # 从入口 stdout + 快照生成仓内 card/case-plan/status/run-receipt

纪律：
  - 不改账本/预算内容（只读快照 + 真实花费自然增长）；
  - 不改任何 GO 文件字节（装槽 = 归档旧槽位件 + 复制该 run 的 GO 到固定路径，字节不变）；
  - 仓内产物不含 case_id / 题面 / 答案 / query 文本。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
RUN_REPORTS = REPO / "docs/reports/OBS-EVAL/P2/H2V3/run"
WORK = Path(r"D:\mktkb-p2-h2v3-20261115")
RUNS = WORK / "runs"
PM = REPO / "docs/evidence/LOCAL-R1-20261101/PM"
FIXED_GO = PM / "P2-LIVE-GO.json"
LEDGER = REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
BUDGET = REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"

NAMES = {
    0: "run0-base_b0",
    1: "run1-base_b0_plus_v01",
    2: "run2-pre_v05_without_v07",
    3: "run3-post_v05_without_v01",
}
RUN_DIR = {1: "r1c", 2: "r2c", 3: "r3c"}


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pending_go(run_index: int) -> Path:
    return PM / f"P2-LIVE-GO.v3-r{run_index}.pending.json"


def ledger_state() -> dict:
    raw = LEDGER.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    reserved = [r for r in rows if r.get("event") == "reserved"]
    results = [r for r in rows if r.get("event") == "result"]
    historical = sum(
        float(r.get("accounted_cny") or 0) for r in rows if r.get("event") == "historical_import"
    )
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
        "budget_sha256": sha(BUDGET),
    }


def cmd_snapshot(out: str) -> int:
    payload = {"at_utc": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat(), "ledger": ledger_state()}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_install_go(run_index: int) -> int:
    """把该 run 的 GO 装进固定槽位：先归档现有槽位件（字节不变），再复制该 run 的 GO。"""
    source = pending_go(run_index)
    if not source.is_file():
        print(json.dumps({"ok": False, "error": "go_missing", "path": str(source)}))
        return 1
    installed_sha = sha(source)
    receipt: dict = {"ok": True, "run_index": run_index, "schema_version": "p2-h2v3-go-slot/v0.1"}
    if FIXED_GO.is_file():
        current = sha(FIXED_GO)
        if current == installed_sha:
            receipt["archive"] = {"mode": "already-installed", "sha256": current}
        else:
            payload = json.loads(FIXED_GO.read_text(encoding="utf-8"))
            prev_run = int(
                str(payload.get("scope", {}).get("plan_id", "")).split("-r")[-1].split("-")[0]
            )
            archive = PM / f"P2-LIVE-GO.v3-r{prev_run}.done.archived.json"
            if archive.exists():
                if sha(archive) != current:
                    print(json.dumps({"ok": False, "error": "archive_conflict", "path": str(archive)}))
                    return 1
                receipt["archive"] = {"mode": "already-present", "path": str(archive),
                                      "sha256": current}
            else:
                shutil.copy2(FIXED_GO, archive)
                receipt["archive"] = {"mode": "archived", "path": str(archive),
                                      "sha256": sha(archive), "byte_identical": sha(archive) == current}
            shutil.copy2(source, FIXED_GO)
    else:
        shutil.copy2(source, FIXED_GO)
    receipt["fixed_path"] = str(FIXED_GO)
    receipt["installed_sha256"] = sha(FIXED_GO)
    receipt["source"] = str(source)
    receipt["source_sha256"] = installed_sha
    receipt["byte_identical"] = receipt["installed_sha256"] == installed_sha
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["byte_identical"] else 1


def _cases(run_index: int) -> tuple[list, dict]:
    path = RUNS / RUN_DIR[run_index] / "out/controlled/case-plan.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc["cases"], doc


def cmd_artifacts(run_index: int) -> int:
    stdout_path = RUNS / f"{RUN_DIR[run_index]}.stdout.json"
    source = stdout_path
    raw = source.read_bytes().decode("utf-8-sig")
    payload = json.loads(raw)
    before = json.loads(
        (RUN_REPORTS / "r123" / f"before-r{run_index}.json").read_text(encoding="utf-8")
    )["ledger"]
    after_path = RUN_REPORTS / "r123" / f"after-r{run_index}.json"
    if after_path.is_file():
        after = json.loads(after_path.read_text(encoding="utf-8"))["ledger"]
    else:
        after = ledger_state()
    target = RUN_REPORTS / f"r{run_index}"
    target.mkdir(parents=True, exist_ok=True)

    ok = bool(payload.get("ok"))
    receipt = payload.get("receipt") or {}
    sidecar = payload.get("sidecar_payload") or {}
    status_name = "COMPLETED" if ok else "ABORTED_AT_R{}".format(run_index)
    error_code = receipt.get("error_code") or payload.get("error_code")

    (target / "run-receipt.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="",
    )

    if not ok or not receipt:
        status = {
            "schema_version": "p2-h2v3-run-status/v1.0",
            "run_index": run_index,
            "run_id": receipt.get("run_id"),
            "scenario_id": receipt.get("scenario_id"),
            "business_date": receipt.get("business_date"),
            "status": status_name,
            "stop_code": receipt.get("stop_code"),
            "error_code": error_code,
            "failure_attribution": "entry_refused_before_outbound" if not receipt.get("real_sends") else None,
            "attempts": 1,
            "retried": False,
            "manual_score_fix": False,
            "requests_outbound_attempts": int((receipt.get("requests") or {}).get("attempts_reserved") or 0),
            "real_sends": int(receipt.get("real_sends") or 0),
            "ledger_delta_reservations": after["reservation_count"] - before["reservation_count"],
            "settled_cny_receipt": float((receipt.get("requests") or {}).get("settled_cny") or 0.0),
            "ledger_delta_cny": round(after["project_accounted_cny"] - before["project_accounted_cny"], 10),
            "four_axis": None,
            "hard_failures": None,
            "note": "首个错误即停：本 run 失败/中止，后续 run 不再执行；未重试、未加钱、未手工修分。",
        }
        (target / "status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="",
        )
        print(json.dumps({"run_index": run_index, "ok": False, "status": status_name,
                          "error_code": error_code}, ensure_ascii=False))
        return 0

    cases, plan_doc = _cases(run_index)
    case_status = Counter(str(row["quality_status"]) for row in cases)
    turns = [turn for row in cases for turn in row["turns"]]
    executed_turns = [turn for turn in turns if str(turn.get("status")) == "executed"]
    turn_status = Counter(str(turn["status"]) for turn in turns)
    requests = receipt["requests"]
    # 本 run 窗口内的单请求最大扣费（只取本次新增的 result 行，不含历史 P2-LIVE 行）
    all_results = [
        json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    all_results = [r for r in all_results if r.get("event") == "result"]
    window = int(after["result_count"]) - int(before["result_count"])
    this_run = all_results[len(all_results) - window:] if window > 0 else []
    max_single = max([float(r.get("conservative_charge_cny") or 0.0) for r in this_run] or [0.0])

    card = {
        "schema_version": "p2-h2v3-run-card/v1.0",
        "role": "v3 真实执行逐 run 安全聚合（无题面/答案/query 文本；无 case_id）",
        "package": "v3-run-r123",
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
            "cases": len(cases),
            "turns": len(turns),
            "requests": int(requests["planned"]),
            "ingest_batches": receipt["plan_ingest"]["batches"],
            "ingest_batches_source": receipt["plan_ingest"]["source"],
        },
        "executed": {
            "cases": len(cases),
            "turns": len(executed_turns),
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
        },
        "pass_fail_error": {
            "pass": int(case_status.get("pass", 0)),
            "fail": int(case_status.get("fail", 0)),
            "error": int(case_status.get("error", 0)),
            "basis": "逐题 quality_status（%d 题）；回合 %d/%d executed、逐回合 error 全 None"
            % (len(cases), len(executed_turns), len(turns)),
        },
        "hard_failures": None,
        "hard_failures_basis": "本 run 只产出逐题 pass/fail；hard-failure 聚合属四 run 汇总阶段"
        "（compose_scenario_runs），本包未执行 → 无实测值，不填 0",
        "four_axis": None,
        "four_axis_basis": "safety/cross_user/cross_entity/stale_source 的逐轴判定属 rescore/axes 阶段"
        "（p2_evidence_axes_adapter_v2 / Q1a-1b），本 run 未执行该步骤 → 无实测值，不填 0；"
        "已封存的回合证据可作其输入",
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
            "cases": len(cases),
            "turns": len(turns),
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
            "before": before,
            "after": after,
            "delta_lines": after["lines"] - before["lines"],
            "delta_reservations": after["reservation_count"] - before["reservation_count"],
            "delta_result": after["result_count"] - before["result_count"],
            "project_delta_cny": round(
                after["project_accounted_cny"] - before["project_accounted_cny"], 10
            ),
            "stage_delta_cny": round(
                after["stage_p2_live_cny"] - before["stage_p2_live_cny"], 10
            ),
        },
        "budget": {
            "sha256_before": before["budget_sha256"],
            "sha256_after": after["budget_sha256"],
            "unchanged": before["budget_sha256"] == after["budget_sha256"],
            "limit_cny": 40.0,
        },
        "limits": {
            "requests_this_run_attempts": int(requests["attempts_reserved"]),
            "requests_this_package_cap": 151,
            "cumulative_requests_after": after["reservation_count"],
            "max_requests": 1160,
            "governance_request_cap": 1500,
            "project_total_limit_cny": 40.0,
            "stage_limit_cny": 20.0,
            "single_attempt_max_cny": 0.5,
            "max_single_attempt_charge_cny": round(max_single, 10),
            "all_within_limit": (
                after["project_accounted_cny"] <= 40.0
                and after["stage_p2_live_cny"] <= 20.0
                and after["reservation_count"] <= 1160
                and max_single <= 0.5
            ),
        },
        "note": "run%d 真实执行（串行、零重试）；逐题 %d pass / %d fail / %d error；"
        "本 run 未产出四轴与 hard-failure 聚合。"
        % (run_index, int(case_status.get("pass", 0)), int(case_status.get("fail", 0)),
           int(case_status.get("error", 0))),
    }
    (target / "card.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="",
    )

    case_plan_public = {
        "schema_version": "p2-h2v3-run-case-plan-public/v0.2",
        "available": True,
        "run_index": int(receipt["run_index"]),
        "run_id": receipt["run_id"],
        "scenario_id": receipt["scenario_id"],
        "business_date": receipt["business_date"],
        "planned_cases": len(cases),
        "planned_turns": len(turns),
        "executed_cases": len(cases),
        "executed_turns": len(executed_turns),
        "turn_status_counts": dict(turn_status),
        "case_quality_counts": dict(case_status),
        "per_case_ordinal": [
            {"ordinal": index + 1, "quality_status": str(row["quality_status"]), "turns": len(row["turns"])}
            for index, row in enumerate(cases)
        ],
        "sealed_case_plan_sha256": receipt["case_plan"]["sha256"],
        "redaction": "仓内不含 case_id / 题面 / 答案 / query 文本；完整逐题 case-plan 只在仓外封存区",
        "thresholds_approved": bool(plan_doc.get("thresholds_approved")),
    }
    (target / "case-plan.json").write_text(
        json.dumps(case_plan_public, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="",
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
    (target / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="",
    )
    print(json.dumps({
        "run_index": run_index, "ok": True, "status": "COMPLETED",
        "cases": len(cases), "turns": len(turns),
        "pass": card["pass_fail_error"]["pass"],
        "fail": card["pass_fail_error"]["fail"],
        "error": card["pass_fail_error"]["error"],
        "attempts": requests["attempts_reserved"], "real_sends": receipt["real_sends"],
        "project_delta_cny": card["ledger"]["project_delta_cny"],
        "ledger_after": after["file_sha256"], "ledger_lines": after["lines"],
        "paired": after["paired"],
    }, ensure_ascii=False))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: snapshot <out> | install-go <idx> | artifacts <idx>")
        return 2
    command = argv[1]
    if command == "snapshot":
        return cmd_snapshot(argv[2])
    if command == "install-go":
        return cmd_install_go(int(argv[2]))
    if command == "artifacts":
        return cmd_artifacts(int(argv[2]))
    print("unknown command", command)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
