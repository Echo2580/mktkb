"""生成新冻结件（v0.3）：同一候选的指纹 + 新 B0 准入 + 正式门禁输出 + 证据索引 + 费用。

用法（仓库根）：
    .venv\\Scripts\\python.exe -X utf8 <本文件> --out <freeze.json>

只读既有证据 JSON 与文件哈希，不触碰产品代码、账本、GO、旧冻结件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]
REQ = ROOT / "docs/reports/OBS-EVAL/P2/FOLLOW-UP/requalification"
EVIDENCE = REQ / "evidence"


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(ROOT)).replace("\\", "/")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    from mktkb.evaluation.p2_contracts import payload_sha256

    inventory = json.loads((EVIDENCE / "candidate-inventory.json").read_text(encoding="utf-8"))
    preflight = json.loads((EVIDENCE / "b0-preflight.json").read_text(encoding="utf-8"))
    gate = json.loads((REQ / "gate/gate-result.json").read_text(encoding="utf-8"))
    isolate = json.loads((EVIDENCE / "version-gate-isolation.json").read_text(encoding="utf-8"))
    admission = json.loads((ROOT / "var/eval/baselines/2b40ee9b4740/b0-admission.json").read_text(encoding="utf-8"))
    run_dir = ROOT / "var/eval/runs/p2-t209-b0-20261121-01/p2-run"
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    ledger_lines = [
        json.loads(line)
        for line in (ROOT / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    run_events = [row for row in ledger_lines if row.get("run_id") == "p2-t209-b0-20261121-01"]
    reserved = [row for row in run_events if row.get("event") == "reserved"]
    settled = [row for row in run_events if row.get("event") == "result"]
    p2_live = [
        row for row in ledger_lines
        if row.get("stage") == "P2-LIVE" and row.get("event") == "result"
    ]

    candidate_files = []
    for entry in inventory["candidate_fingerprint_v2"]["files"]:
        path = ROOT / entry["path"]
        candidate_files.append({
            "path": entry["path"],
            "status": entry["status"],
            "category": "product" if entry["path"].startswith("backend/src") else "test",
            "sha256": sha(path),
            "bytes": path.stat().st_size,
            "delta_vs_v1": entry["delta_vs_fingerprint_v1"],
        })
    for entry in inventory["extra_tracked_drift"]:
        if entry["category"] == "bookkeeping":
            continue
        path = ROOT / entry["path"]
        candidate_files.append({
            "path": entry["path"],
            "status": "modified",
            "category": entry["category"],
            "sha256": sha(path),
            "bytes": path.stat().st_size,
            "delta_vs_v1": "not_in_v1_fingerprint",
            "note": entry["note"],
        })

    freeze = {
        "schema_version": "p2-candidate-freeze/v0.3",
        "frozen_at_local": datetime.now().astimezone().isoformat(timespec="seconds"),
        "branch": inventory["branch"],
        "head": inventory["head"],
        "supersedes": {
            "freeze": "docs/reports/OBS-EVAL/P2/candidate-freeze.json",
            "reason": (
                "原冻结候选（93486b6 工作树）在 FU-1..FU-4 修复与 live_authorization 改动后流水线摘要变化；"
                "本轮按同一流程重做真实 B0 并重新登记基线后重新冻结。旧冻结件与旧基线原件保留不动。"
            ),
        },
        "candidate": {
            "pipeline_source_sha256": inventory["candidate"]["pipeline_source_sha256"],
            "product_pipeline_version": inventory["candidate"]["product_pipeline_version"],
            "b0_pipeline_version": admission["pipeline_version"],
            "files": candidate_files,
            "extra_tracked_drift": inventory["extra_tracked_drift"],
            "fingerprint_evidence": "docs/reports/OBS-EVAL/P2/FOLLOW-UP/requalification/evidence/candidate-inventory.json",
        },
        "gate_config": {
            "path": "docs/evaluation/gate_v0_3_approved.json",
            "sha256": sha(ROOT / "docs/evaluation/gate_v0_3_approved.json"),
            "changed": False,
        },
        "b0": {
            "baseline_id": "2b40ee9b4740",
            "run_id": admission["run_id"],
            "admission_evidence_sha256": json.loads(
                (EVIDENCE / "b0-acceptance-receipt.json").read_text(encoding="utf-8")
            )["evidence_sha256"],
            "registry_files": {
                name: sha(ROOT / "var/eval/baselines/2b40ee9b4740" / name)
                for name in ("baseline.json", "b0-admission.json", "b0-approval-receipt.json")
            },
            "plan_sha256": admission["plan_sha256"],
            "go_sha256": admission["go_sha256"],
            "dataset_version": admission["dataset_version"],
            "corpus_sha256": admission["corpus_sha256"],
            "real_calls": admission["real_calls"],
            "b0_tally": admission["b0"],
            "hard_gate": admission["hard_gate"],
            "p2_release_status": admission["p2_release_status"],
            "run_artifacts": admission["artifact_sha256"],
            "request_plan": {
                "path": "docs/reports/OBS-EVAL/P2/FOLLOW-UP/requalification/evidence/b0-request-plan.bound.json",
                "requests_total": preflight["plan_scale"]["requests_total"],
                "requests_by_operation": preflight["plan_scale"]["requests_by_operation"],
                "worst_case_cny": preflight["preflight_proposed_adjustment"]["worst_case_cny"],
                "ocr_pages": preflight["plan_scale"]["ocr_pages"],
            },
        },
        "formal_gate": {
            "inputs": rel(REQ / "gate/inputs.json"),
            "inputs_sha256": sha(REQ / "gate/inputs.json"),
            "result": rel(REQ / "gate/gate-result.json"),
            "result_sha256": sha(REQ / "gate/gate-result.json"),
            "decision": gate["decision"],
            "technical_gate": gate["technical_gate"],
            "counts": gate["counts"],
            "pending": gate["pending"],
            "reason_codes": gate["reason_codes"],
            "row_count": len(gate["rows"]),
            "candidate_pipeline_row": next(row for row in gate["rows"] if row["row_id"] == "candidate.pipeline"),
            "b0_admission_row": next(row for row in gate["rows"] if row["row_id"] == "b0.admission"),
            "evidence_provenance_row": next(row for row in gate["rows"] if row["row_id"] == "evidence_provenance"),
            "release_allowed": gate["release_allowed"],
            "owner_release_decision": gate["owner_release_decision"],
        },
        "verification": {
            "thresholds": {
                "b0_executed": admission["b0"]["executed"],
                "b0_passed_min": 36,
                "b0_passed": admission["b0"]["passed"],
                "exact_passed": admission["b0"]["exact_passed"],
                "exact_total": admission["b0"]["exact_planned"],
                "ocr_executed": admission["b0"]["ocr_executed"],
                "ocr_planned": admission["b0"]["ocr_planned"],
                "hard_failures": admission["hard_gate"]["hard_failures"],
                "unknown_count": admission["hard_gate"]["unknown_count"],
            },
            "version_gate_isolation": {
                "negative_blocked_rows": isolate["runs"]["negative_current_candidate"]["blocked_rows"],
                "simulated_identity_decision": isolate["runs"]["positive_simulated_identity"]["decision"],
                "same_candidate_real_admission": "closed by the new B0 above",
            },
        },
        "cost": {
            "reservations": len(reserved),
            "settled": len(settled),
            "outstanding": len(reserved) - len(settled),
            "reserved_cny": round(sum(float(row.get("reserve_cny") or 0) for row in reserved), 6),
            "conservative_charged_cny": round(
                sum(float(row.get("conservative_charge_cny") or 0) for row in settled), 6
            ),
            "provider_billed_cny": summary["requests"].get("provider_billed_cny"),
            "by_kind": {
                kind: sum(1 for row in settled if row.get("kind") == kind)
                for kind in sorted({row.get("kind") for row in settled})
            },
            "p2_live_stage_accounted_cny_after": round(
                sum(float(row.get("conservative_charge_cny") or 0) for row in p2_live), 6
            ),
            "p2_live_stage_limit_cny": 32.0,
            "budget_stage_revision": json.loads(
                (ROOT / "docs/evidence/LOCAL-R1-20261101/budget/budget.json").read_text(encoding="utf-8")
            )["stage_revision"]["revision"],
        },
        "evidence_index": {
            "candidate_inventory": "evidence/candidate-inventory.json",
            "b0_preflight": "evidence/b0-preflight.json",
            "b0_preflight_request": "b0-preflight-request.md",
            "version_gate_isolation": "evidence/version-gate-isolation.json",
            "go_issue": "evidence/go-issue.json",
            "b0_acceptance_receipt": "evidence/b0-acceptance-receipt.json",
            "b0_run_logs": "var/eval/t209-prep/b0-live-20261121/logs/",
            "gate": "gate/gate-result.json",
            "fu2_e2e_derive": "evidence/fu2-e2e-derive.json",
            "fu2_e2e_cards": "evidence/fu2-e2e-cards/",
            "browser": "browser/actual/playwright-p2requal2-20261121.json",
            "legacy_freeze": "docs/reports/OBS-EVAL/P2/candidate-freeze.json",
            "legacy_gate_snapshot": "docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/gate-result.real-ncu.json",
        },
        "reservations": [
            "FU-2 端到端派生已跑通（4/4 卡 + 官方验卡 4/4 + 三目录确定性），但合成证据包为 incomplete → 四轴 unknown、卡的 verified=false；未伪造 pass。真实受限批次与四份真 binding 的 CLI 组合仍 NOT-RUN。",
            "浏览器复验为隔离实例 + 受控替身网关（Mock 标注），不是真实模型生成；真实问答/OCR 亲验需另授权。",
            "N/C/U 的 6 条原机械失败（N01/C01/C02/C05/C06/U01）与 D-011 披露行按原样保留。",
            "H2 30 题历史聚合沿用原受限证据，未重跑。",
            "供应商实账未出（OCR 后付费）；费用按应用保守记账披露。",
            "`.claude/handoffs/**`、`docs/reports/OBS-EVAL/P2/FOLLOW-UP/**` 之外的未跟踪历史证据目录未纳入候选。",
        ],
    }
    freeze["payload_sha256"] = payload_sha256(
        {key: value for key, value in freeze.items() if key != "payload_sha256"}
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(freeze, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps({
        "freeze": rel(out),
        "payload_sha256": freeze["payload_sha256"],
        "candidate_files": len(candidate_files),
        "pipeline": freeze["candidate"]["pipeline_source_sha256"],
        "b0": {"baseline_id": freeze["b0"]["baseline_id"], "tally": freeze["b0"]["b0_tally"]},
        "gate": {"decision": freeze["formal_gate"]["decision"], "counts": freeze["formal_gate"]["counts"]},
        "cost": freeze["cost"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
