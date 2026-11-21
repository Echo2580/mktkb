"""新 B0 只读预检（零出站、零预留、不改预算/账本/GO）。

用法（仓库根）：
    .venv\\Scripts\\python.exe -X utf8 docs\\reports\\OBS-EVAL\\P2\\FOLLOW-UP\\requalification\\evidence\\scripts\\b0_preflight.py \
        --out-json <evidence.json> --out-plan <plan.json>

做的事：
1. 用**当前候选**的 ``pipeline_source_sha256`` 重建 B0 计划绑定（40 题、194 次、OCR 12 页，
   沿用 T209-PREP 已核算的逐项配额，不新增也不放宽）；
2. 只读读账本快照（``read_ledger_snapshot``，固定路径），分别跑两次 ``preflight_p2``：
   A. 沿用上次批准的额度口径（stage 20.0 / 中心 6.5-12.0-0.5-1.0）→ 应拒绝，并给出固定原因码；
   B. 拟议调额后（stage 32.0 / 中心 7.0-23.5-0.5-1.0）→ 应通过；
3. 输出两份预检结果与计划摘要。B 的 stage 分配是**拟议值**，未写入 budget.json。

不写盘除 --out-json/--out-plan 之外的任何文件；不调 authorize_p2，不预留，不发送。
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]
DRAFT = ROOT / "docs/reports/OBS-EVAL/P2/T209-PREP/b0-request-plan.bound-draft.json"

RUN_ID = "p2-t209-b0-20261121-01"
#: 拟议调额：P2-LIVE 阶段 24.0 -> 32.0；中心 7.0 / 23.5 / 0.5 / 1.0（合计 32.00）。
PROPOSED_STAGE_LIMIT_CNY = 32.0
PROPOSED_CENTERS = {
    "answer_retrieval": 7.00,
    "ocr": 23.50,
    "judge": 0.50,
    "independent": 1.00,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-plan", required=True)
    args = parser.parse_args()

    from mktkb.evaluation import p2_b0
    from mktkb.evaluation.p2_authorization import preflight_p2, read_ledger_snapshot
    from mktkb.evaluation.p2_contracts import P2RunPlan, payload_sha256

    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    binding = p2_b0.build_b0_plan_binding(RUN_ID)
    snapshot = read_ledger_snapshot()
    snapshot_dict = snapshot.as_dict() if hasattr(snapshot, "as_dict") else dict(snapshot.__dict__)

    total_requests = sum(int(item["requests"]) for item in draft["items"])
    by_operation: dict[str, int] = {}
    for item in draft["items"]:
        by_operation[item["operation"]] = by_operation.get(item["operation"], 0) + int(item["requests"])

    def build_plan(*, stage_limit: float, centers: dict[str, float], created: str) -> P2RunPlan:
        payload = copy.deepcopy(draft)
        payload["plan_id"] = "P2-T209-B0-20261121-01"
        payload["plan_version"] = "v0.1"
        payload["created_utc"] = created
        payload["project_total_limit_cny"] = float(snapshot_dict["total_limit_cny"])
        payload["stage_limit_cny"] = float(stage_limit)
        payload["cost_centers_cny"] = dict(centers)
        payload["b0_binding"] = dict(binding)
        payload.pop("plan_sha256", None)
        return P2RunPlan.from_dict(payload)

    # A) 沿用上次批准的额度口径（stage 20.0；中心 6.5/12.0/0.5/1.0，合计 20.0）。
    plan_a = build_plan(
        stage_limit=20.0,
        centers={"answer_retrieval": 6.5, "ocr": 12.0, "judge": 0.5, "independent": 1.0},
        created="2026-11-21T14:00:00+08:00",
    )
    preflight_a = preflight_p2(plan_a, snapshot)

    # B) 拟议调额后（stage 32.0；中心 7.0/23.5/0.5/1.0）。stage 分配用拟议快照副本，不动真实文件。
    plan_b = build_plan(
        stage_limit=PROPOSED_STAGE_LIMIT_CNY,
        centers=PROPOSED_CENTERS,
        created="2026-11-21T14:05:00+08:00",
    )
    proposed_snapshot = copy.deepcopy(snapshot_dict)
    proposed_snapshot["stage_allocations_cny"] = dict(
        proposed_snapshot["stage_allocations_cny"], **{"P2-LIVE": PROPOSED_STAGE_LIMIT_CNY}
    )
    preflight_b = preflight_p2(plan_b, proposed_snapshot)

    result = {
        "schema": "p2-b0-preflight-request/v0.1",
        "kind": "offline-read-only",
        "candidate": {
            "pipeline_source_sha256": p2_b0.pipeline_source_sha256(),
            "b0_binding": binding,
            "binding_payload_sha256": payload_sha256(binding),
        },
        "plan_scale": {
            "cases": len(p2_b0.frozen_b0_cases()),
            "requests_total": total_requests,
            "requests_by_operation": dict(sorted(by_operation.items())),
            "ocr_pages": by_operation.get("ocr", 0),
            "ocr_documents": len(
                {item["case_id"] for item in draft["items"] if item["operation"] == "ocr"}
            ),
            "ocr_questions_standard": json.loads(
                (ROOT / "docs/evaluation/gate_v0_3_approved.json").read_text(encoding="utf-8")
            )["p2_standards"]["b0"]["ocr_total"],
        },
        "ledger_snapshot": {
            "ledger_sha256": snapshot_dict["ledger_sha256"],
            "budget_sha256": snapshot_dict["budget_sha256"],
            "total_limit_cny": snapshot_dict["total_limit_cny"],
            "accounted_cny": snapshot_dict["accounted_cny"],
            "stage_allocations_cny": snapshot_dict["stage_allocations_cny"],
            "p2_stage_accounted_cny": snapshot_dict["p2_stage_accounted_cny"],
            "p2_center_accounted_cny": snapshot_dict["p2_center_accounted_cny"],
            "reservation_count": snapshot_dict["reservation_count"],
        },
        "preflight_as_last_approved": {
            "inputs": {"stage_limit_cny": 20.0, "cost_centers_cny": plan_a.cost_centers_cny},
            "plan_sha256": payload_sha256(plan_a.as_dict()),
            "ok": preflight_a.ok,
            "reasons": list(preflight_a.reasons),
            "stage_remaining_cny": preflight_a.stage_remaining_cny,
            "total_remaining_cny": preflight_a.total_remaining_cny,
            "worst_case_cny": preflight_a.worst_case_cny,
            "center_limits_cny": dict(preflight_a.center_limits_cny),
            "center_needs_cny": dict(preflight_a.center_needs_cny),
            "center_remaining_cny": dict(preflight_a.center_remaining_cny),
        },
        "preflight_proposed_adjustment": {
            "inputs": {
                "stage_limit_cny": PROPOSED_STAGE_LIMIT_CNY,
                "cost_centers_cny": PROPOSED_CENTERS,
                "note": "stage 分配为拟议值，尚未写入 budget.json；执行前须先按主人授权落盘。",
            },
            "plan_sha256": payload_sha256(plan_b.as_dict()),
            "ok": preflight_b.ok,
            "reasons": list(preflight_b.reasons),
            "stage_remaining_cny": preflight_b.stage_remaining_cny,
            "total_remaining_cny": preflight_b.total_remaining_cny,
            "worst_case_cny": preflight_b.worst_case_cny,
            "center_limits_cny": dict(preflight_b.center_limits_cny),
            "center_needs_cny": dict(preflight_b.center_needs_cny),
            "center_remaining_cny": dict(preflight_b.center_remaining_cny),
            "max_requests": preflight_b.max_requests,
            "requests_used": preflight_b.requests_used,
            "requests_planned": preflight_b.requests_planned,
        },
        "quota_change_request": {
            "stage": "P2-LIVE",
            "from_cny": snapshot_dict["stage_allocations_cny"]["P2-LIVE"],
            "to_cny": PROPOSED_STAGE_LIMIT_CNY,
            "delta_cny": round(PROPOSED_STAGE_LIMIT_CNY - snapshot_dict["stage_allocations_cny"]["P2-LIVE"], 6),
            "project_total_unchanged_cny": snapshot_dict["total_limit_cny"],
            "cost_centers_before": {
                "answer_retrieval": 6.5,
                "ocr": 12.0,
                "judge": 0.5,
                "independent": 1.0,
            },
            "cost_centers_proposed": PROPOSED_CENTERS,
        },
        "post_run_residual_ceiling": {
            "note": "按计划逐项上限（worst case）执行后的余量；实际以账本结算为准。",
            "stage_remaining_cny": round(
                PROPOSED_STAGE_LIMIT_CNY - snapshot_dict["p2_stage_accounted_cny"] - preflight_b.worst_case_cny, 6
            ),
            "center_remaining_cny": {
                center: round(
                    float(preflight_b.center_remaining_cny[center]) - float(preflight_b.center_needs_cny[center]), 6
                )
                for center in PROPOSED_CENTERS
            },
            "project_remaining_cny": round(
                snapshot_dict["total_limit_cny"] - snapshot_dict["accounted_cny"] - preflight_b.worst_case_cny, 6
            ),
        },
    }

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_bytes((json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    out_plan = Path(args.out_plan)
    out_plan.parent.mkdir(parents=True, exist_ok=True)
    out_plan.write_bytes(
        (json.dumps(plan_b.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )

    print(json.dumps({
        "scale": result["plan_scale"],
        "as_last_approved": {
            "ok": result["preflight_as_last_approved"]["ok"],
            "reasons": result["preflight_as_last_approved"]["reasons"],
        },
        "proposed": {
            "ok": result["preflight_proposed_adjustment"]["ok"],
            "reasons": result["preflight_proposed_adjustment"]["reasons"],
            "stage_remaining_cny": result["preflight_proposed_adjustment"]["stage_remaining_cny"],
            "center_remaining_cny": result["preflight_proposed_adjustment"]["center_remaining_cny"],
        },
        "quota_change": result["quota_change_request"],
    }, ensure_ascii=False, indent=2))
    return 0 if (not preflight_a.ok and preflight_b.ok) else 1


if __name__ == "__main__":
    sys.exit(main())
