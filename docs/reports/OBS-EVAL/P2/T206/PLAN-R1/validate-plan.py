"""P2-T206-PLAN-R1 纯契约离线校验（零真实调用）：plan v0_2 / GO DRAFT v0_2 / 预检 / 授权 / 负例。

零写入保证：账本、预算、GO 都只出现在**内存对象**里（P2LedgerSnapshot 直接构造，不读固定路径、
不建 .lock、不追加事件）；两个候选文件只被 json 读一次。

复跑：.venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T206/PLAN-R1/validate-plan.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PM = Path(__file__).resolve().parents[1] / "PM"
REPO = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO / "backend" / "src"))

from mktkb.evaluation import p2_authorization as pa  # noqa: E402
from mktkb.evaluation.p2_contracts import P2LedgerSnapshot, P2RunPlan  # noqa: E402

LEDGER_SHA = "1f46d1b9e846528d5a1635db5175a997eab9da075d61a90a8cbf803f3fde7390"
PREFIX_SHA = "f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014"
BUDGET_SHA = "084ba9acb4ee90379fd51fab8878f6dd4bab1bd481bff2a14c83057ffbc1cc58"


def snapshot(total_limit: float, allocations: dict[str, float]) -> P2LedgerSnapshot:
    return P2LedgerSnapshot(
        schema_version="p2-ledger-snapshot/v0.1",
        ledger_path=str(REPO / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"),
        ledger_sha256=LEDGER_SHA,
        historical_prefix_sha256=PREFIX_SHA,
        budget_sha256=BUDGET_SHA,
        historical_accounted_cny=0.03,
        accounted_cny=15.070944499999985,
        reservation_count=505,
        result_count=505,
        p2_stage_accounted_cny=0.0,
        p2_center_accounted_cny={},
        total_limit_cny=total_limit,
        stage_allocations_cny=allocations,
        source="in-memory",
    )


CURRENT_BUDGET = snapshot(20.0, {"S1-DEV": 0.0, "S1-IA": 0.0, "S2-DEV": 15.4, "P1-RETRIEVAL": 3.0, "later_shared_reserve": 1.57})
PLANNED_BUDGET = snapshot(40.0, {"S1-DEV": 0.0, "S1-IA": 0.0, "S2-DEV": 15.4, "P1-RETRIEVAL": 3.0, "later_shared_reserve": 1.57, "P2-LIVE": 20.0})
BUDGET_PAYLOAD = {
    "limit_cny": 40.0,
    "historical_conservative_accounted_cny": 0.03,
    "remaining_conservative_cny_at_start": 24.9290555,
    "provider_billed_cny": None,
    "stages": {"S1-DEV": 0.0, "S1-IA": 0.0, "S2-DEV": 15.4, "P1-RETRIEVAL": 3.0, "later_shared_reserve": 1.57, "P2-LIVE": 20.0},
    "ledger": "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl",
    "note": "DRAFT CANDIDATE ONLY",
}


def load(name: str) -> dict:
    return json.loads((PM / name).read_text(encoding="utf-8"))


def probe(plan_doc: dict, label: str, ingest: int | None = None, max_requests: int | None = None) -> dict:
    doc = json.loads(json.dumps(plan_doc))
    if ingest is not None:
        for item in doc["items"]:
            if item["item_id"] == "ingest-index-embedding":
                item["requests"] = ingest
    if max_requests is not None:
        doc["max_requests"] = max_requests
    plan = P2RunPlan.from_dict(doc)
    pre = pa.preflight_p2(plan, PLANNED_BUDGET)
    return {
        "case": label,
        "ingest_batches": int(next(i["requests"] for i in doc["items"] if i["item_id"] == "ingest-index-embedding")),
        "total_requests": plan.total_requests,
        "max_requests": plan.max_requests,
        "worst_case_cny": plan.worst_case_cny,
        "preflight_ok": pre.ok,
        "preflight_reasons": list(pre.reasons),
        "requests_remaining": pre.requests_remaining,
        "within_560_envelope": plan.max_requests <= 560,
    }


def main() -> None:
    plan_doc = load("p2-pilot-plan-v0_2.json")
    plan = P2RunPlan.from_dict(plan_doc)
    go = load("P2-LIVE-GO.CANDIDATE-DRAFT-v0_2.json")
    print(json.dumps({
        "step": "plan_v0_2",
        "plan_id": plan.plan_id,
        "plan_version": plan.plan_version,
        "plan_sha256": plan.plan_sha256,
        "items": len(plan.items),
        "case_count": plan.case_count,
        "total_requests": plan.total_requests,
        "max_requests": plan.max_requests,
        "worst_case_cny": plan.worst_case_cny,
        "reserve_peak_cny": plan.reserve_peak_cny,
        "estimated_success_cny": plan.estimated_success_cny,
        "requests_by_operation": plan.requests_by_operation(),
        "center_needs_cny": dict(plan.center_needs_cny()),
    }, ensure_ascii=False, indent=1))

    issued = datetime.fromisoformat(go["issued_utc"])
    expires = datetime.fromisoformat(go["expires_utc"])
    print(json.dumps({
        "step": "go_draft_v0_2",
        "document": go["document"],
        "stage": go["stage"],
        "authorization": go["authorization"],
        "plan_id_bound": go["scope"]["plan_id"] == plan.plan_id,
        "plan_sha_bound": go["scope"]["plan_sha256"] == plan.plan_sha256,
        "max_requests": go["scope"]["max_requests"],
        "max_request_cny": go["scope"]["max_request_cny"],
        "validity_days": (expires - issued).days,
        "ledger_sha_is_history_prefix": go["budget_ledger_sha256"] == PREFIX_SHA,
    }, ensure_ascii=False, indent=1))

    pre_now = pa.preflight_p2(plan, CURRENT_BUDGET)
    pre_planned = pa.preflight_p2(plan, PLANNED_BUDGET)
    print(json.dumps({
        "step": "preflight",
        "against_current_budget": {"ok": pre_now.ok, "reasons": list(pre_now.reasons)},
        "against_planned_budget": {
            "ok": pre_planned.ok, "reasons": list(pre_planned.reasons),
            "stage_remaining": pre_planned.stage_remaining_cny,
            "total_remaining": pre_planned.total_remaining_cny,
            "requests_remaining": pre_planned.requests_remaining,
            "requests_planned": pre_planned.requests_planned,
            "worst_case": pre_planned.worst_case_cny,
            "reserve_peak": pre_planned.reserve_peak_cny,
            "production_ready": pre_planned.production_ready,
        },
    }, ensure_ascii=False, indent=1))

    now = datetime(2026, 11, 11, 0, 40, tzinfo=timezone(timedelta(hours=8)))
    auth = pa.authorize_p2(plan, go_payload=go, budget_payload=BUDGET_PAYLOAD, ledger_snapshot=PLANNED_BUDGET, now=now)
    print(json.dumps({
        "step": "authorize",
        "production_ready": auth.production_ready,
        "go_sha256": auth.go_sha256,
        "plan_sha256": auth.plan_sha256,
        "max_requests": auth.max_requests,
        "requests_used": auth.requests_used,
        "requests_remaining": auth.requests_remaining,
        "stage_remaining_cny": auth.stage_remaining_cny,
    }, ensure_ascii=False, indent=1))

    negatives = []
    try:
        pa.authorize_p2(P2RunPlan.from_dict(load("p2-pilot-plan-v0_1.json")),
                        go_payload=go, budget_payload=BUDGET_PAYLOAD, ledger_snapshot=PLANNED_BUDGET, now=now)
        negatives.append({"case": "v0_1_plan_vs_v0_2_go", "result": "UNEXPECTED-PASS"})
    except Exception as exc:  # noqa: BLE001
        negatives.append({"case": "v0_1_plan_vs_v0_2_go", "reason": getattr(exc, "reason", type(exc).__name__)})
    go_tight = json.loads(json.dumps(go)); go_tight["scope"]["max_requests"] = 560
    try:
        pa.authorize_p2(plan, go_payload=go_tight, budget_payload=BUDGET_PAYLOAD, ledger_snapshot=PLANNED_BUDGET, now=now)
        negatives.append({"case": "go_max_requests_560", "result": "UNEXPECTED-PASS"})
    except Exception as exc:  # noqa: BLE001
        negatives.append({"case": "go_max_requests_560", "reason": getattr(exc, "reason", type(exc).__name__)})
    go_expired = json.loads(json.dumps(go)); go_expired["expires_utc"] = (issued + timedelta(minutes=30)).isoformat()  # 00:30 < now(00:40) -> 过期
    try:
        pa.authorize_p2(plan, go_payload=go_expired, budget_payload=BUDGET_PAYLOAD, ledger_snapshot=PLANNED_BUDGET, now=now)
        negatives.append({"case": "go_expired", "result": "UNEXPECTED-PASS"})
    except Exception as exc:  # noqa: BLE001
        negatives.append({"case": "go_expired", "reason": getattr(exc, "reason", type(exc).__name__)})
    print(json.dumps({"step": "negatives", "rows": negatives}, ensure_ascii=False, indent=1))

    print(json.dumps({"step": "envelope_560", "rows": [
        probe(plan_doc, "v0_2（D09 保守 6 批）", 36, 566),
        probe(plan_doc, "同请求数但压回 560", 36, 560),
        probe(plan_doc, "删 V03（−2 批）但 D09 仍 6 批", 34, 564),
        probe(plan_doc, "删 V03 + D09 压到 2 批（<=9,000 字）", 30, 560),
    ]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
