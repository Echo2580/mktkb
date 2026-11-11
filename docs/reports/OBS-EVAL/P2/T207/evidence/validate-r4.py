"""P2-T207-R4PREP：R4 计划/候选 GO 的**纯契约离线校验**（零真实调用、零写入）。

- 计划与候选 GO 只被 json 读一次；真实账本/预算快照经 p2_authorization.read_ledger_snapshot()
  只读读取（前后 SHA 必须一致）；
- 不写账本、不写预算、不创建/修改固定路径 GO、不发 HTTP、不读 .env/H1/H2。

用法（仓库根）：
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207/evidence/validate-r4.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[6]
PM = HERE.parents[1] / "PM"
sys.path.insert(0, str(REPO / "backend" / "src"))

from mktkb.evaluation import p2_authorization as pa  # noqa: E402
from mktkb.evaluation.p2_contracts import (  # noqa: E402
    HARD_MAX_REQUESTS,
    P2LedgerSnapshot,
    P2RunPlan,
)
from mktkb.evaluation.p2_live import required_live_operations  # noqa: E402

LEDGER = REPO / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
BUDGET = REPO / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "budget.json"
GO_PATH = REPO / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM" / "P2-LIVE-GO.json"
PLAN_NAME = "T207-plan-R4-v0_1.json"
GO_NAME = "T207-GO-R4.CANDIDATE-DRAFT.json"
#: 现在有效的公开矩阵计划（T207-FIX-A 重发）：用作"旧 plan sha"负例。
PUBLIC_PLAN_SHA = "0b4e55a4cd3a46f968e89fe495ffca3c6931c8f49f1f258a3dd753f83e24a194"
NOW = datetime(2026, 11, 11, 13, 0, tzinfo=timezone(timedelta(hours=8)))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict:
    return json.loads((PM / name).read_text(encoding="utf-8"))


def memory_snapshot(real: P2LedgerSnapshot) -> P2LedgerSnapshot:
    """把**真实**读到的资金事实包成内存快照（只用于授权链的形状检查，不是准入证据）。"""
    return P2LedgerSnapshot(
        schema_version=real.schema_version,
        ledger_path=real.ledger_path,
        ledger_sha256=real.ledger_sha256,
        historical_prefix_sha256=real.historical_prefix_sha256,
        budget_sha256=real.budget_sha256,
        total_limit_cny=real.total_limit_cny,
        historical_accounted_cny=real.historical_accounted_cny,
        accounted_cny=real.accounted_cny,
        reservation_count=real.reservation_count,
        result_count=real.result_count,
        stage_allocations_cny=dict(real.stage_allocations_cny),
        p2_stage_accounted_cny=real.p2_stage_accounted_cny,
        p2_center_accounted_cny=dict(real.p2_center_accounted_cny),
        source="in-memory",
    )


def mutated(plan_doc: dict, *, ingest: int | None = None, max_requests: int | None = None,
            center: dict | None = None, plan_id: str | None = None) -> dict:
    doc = json.loads(json.dumps(plan_doc))
    if plan_id is not None:
        doc["plan_id"] = plan_id
    if ingest is not None:
        for item in doc["items"]:
            if item["item_id"] == "ingest-index-embedding":
                item["requests"] = ingest
    if max_requests is not None:
        doc["max_requests"] = max_requests
    if center is not None:
        doc["cost_centers_cny"] = center
    return doc


def main() -> None:
    before = {"ledger_sha": sha(LEDGER), "budget_sha": sha(BUDGET),
              "ledger_bytes": LEDGER.stat().st_size,
              "ledger_lines": len(LEDGER.read_text(encoding="utf-8").splitlines())}
    real = pa.read_ledger_snapshot()
    plan_doc = load(PLAN_NAME)
    plan = P2RunPlan.from_dict(plan_doc)
    go = load(GO_NAME)
    budget_payload = pa.load_budget_payload()

    print(json.dumps({
        "step": "plan",
        "path": str((PM / PLAN_NAME).relative_to(REPO)),
        "file_sha256": sha(PM / PLAN_NAME),
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "items": len(plan.items),
        "cases": plan.case_count,
        "turns": plan.turn_count,
        "ocr_pages": plan.page_count,
        "operations": list(plan.operations),
        "total_requests": plan.total_requests,
        "max_requests": plan.max_requests,
        "worst_case_cny": plan.worst_case_cny,
        "reserve_peak_cny": plan.reserve_peak_cny,
        "estimated_success_cny": plan.estimated_success_cny,
        "by_operation": plan.requests_by_operation(),
        "center_needs_cny": dict(plan.center_needs_cny()),
        "center_limits_cny": dict(plan.cost_centers_cny),
        "hard_max_requests": HARD_MAX_REQUESTS,
        "no_ocr_item": plan.page_count == 0 and "ocr" not in plan.operations,
        "required_live_operations": list(required_live_operations(plan)),
        "max_item_bound_cny": max(item.bound_cny for item in plan.items),
        "every_item_within_max_request_cny": all(
            item.bound_cny <= float(go["scope"]["max_request_cny"]) for item in plan.items
        ),
        "max_requests_within_hard_cap": plan.max_requests <= HARD_MAX_REQUESTS,
        "requests_headroom": {
            "used": int(real.reservation_count),
            "plan_cap": plan.max_requests,
            "plan_total": plan.total_requests,
            "remaining_at_plan_cap": plan.max_requests - int(real.reservation_count),
            "remaining_at_hard_cap": HARD_MAX_REQUESTS - int(real.reservation_count),
        },
    }, ensure_ascii=False, indent=1))

    issued = datetime.fromisoformat(go["issued_utc"])
    expires = datetime.fromisoformat(go["expires_utc"])
    print(json.dumps({
        "step": "go_candidate",
        "path": str((PM / GO_NAME).relative_to(REPO)),
        "file_sha256": sha(PM / GO_NAME),
        "document": go["document"],
        "authorization": go["authorization"],
        "draft_marked_not_usable": "DRAFT" in go["authorization"] and "NOT USABLE" in go["authorization"],
        "plan_id_bound": go["scope"]["plan_id"] == plan.plan_id,
        "plan_sha_bound": go["scope"]["plan_sha256"] == plan.plan_sha256,
        "max_requests": go["scope"]["max_requests"],
        "max_request_cny": go["scope"]["max_request_cny"],
        "validity_days": (expires - issued).days,
        "ledger_sha_is_history_prefix": go["budget_ledger_sha256"] == real.historical_prefix_sha256,
        "operations": go["scope"]["operations"],
        "operations_have_no_ocr": "ocr" not in go["scope"]["operations"],
        "operations_cover_plan": sorted(set(plan.operations)) == sorted(set(go["scope"]["operations"])),
        "centers": go["scope"]["cost_centers_cny"],
        "stage_limits": go["scope"]["stage_limits_cny"],
        "go_path_untouched": GO_PATH.exists(),
    }, ensure_ascii=False, indent=1))

    pre_real = pa.preflight_p2(plan, real)
    print(json.dumps({
        "step": "preflight_real_snapshot",
        "ok": pre_real.ok,
        "reasons": list(pre_real.reasons),
        "stage_remaining": pre_real.stage_remaining_cny,
        "total_remaining": pre_real.total_remaining_cny,
        "requests_used": pre_real.requests_used,
        "requests_remaining": pre_real.requests_remaining,
        "requests_planned": pre_real.requests_planned,
        "worst_case": pre_real.worst_case_cny,
        "reserve_peak": pre_real.reserve_peak_cny,
        "center_remaining": dict(pre_real.center_remaining_cny),
        "production_ready": pre_real.production_ready,
    }, ensure_ascii=False, indent=1))

    snapshot_in_mem = memory_snapshot(real)
    auth = pa.authorize_p2(plan, go_payload=go, budget_payload=budget_payload,
                           ledger_snapshot=snapshot_in_mem, now=NOW)
    print(json.dumps({
        "step": "authorize_candidate",
        "production_ready": auth.production_ready,
        "go_sha256": auth.go_sha256,
        "plan_sha256": auth.plan_sha256,
        "stage_remaining_cny": auth.stage_remaining_cny,
        "requests_used": auth.requests_used,
        "requests_remaining": auth.requests_remaining,
        "max_requests": auth.max_requests,
        "max_request_cny": auth.max_request_cny,
        "operations": list(auth.operations),
        "note": "production_ready=False ⇒ 候选 GO 不能发送；只有经理落盘的固定路径 GO 才可能为 True",
    }, ensure_ascii=False, indent=1))

    negatives: list[dict] = []

    def expect(label: str, fn) -> None:
        try:
            outcome = fn()
            ok = getattr(outcome, "ok", None)
            if ok is False:
                negatives.append({"case": label, "kind": "preflight", "reasons": list(outcome.reasons)})
            else:
                negatives.append({"case": label, "result": "UNEXPECTED-PASS"})
        except Exception as exc:  # noqa: BLE001
            negatives.append({"case": label, "kind": "authorize",
                              "reason": getattr(exc, "reason", None) or getattr(exc, "code", None)
                              or type(exc).__name__})

    def gen(go_doc: dict) -> None:
        return pa.authorize_p2(plan, go_payload=go_doc, budget_payload=budget_payload,
                               ledger_snapshot=snapshot_in_mem, now=NOW)

    # 1) GO 少一个计划里的操作（去掉 rerank）
    fewer = json.loads(json.dumps(go))
    fewer["scope"]["operations"] = [op for op in fewer["scope"]["operations"] if op != "rerank"]
    expect("go_missing_rerank_operation", lambda: gen(fewer))

    # 2) GO 的 max_requests 低于计划自身的 max_requests（760）
    tight = json.loads(json.dumps(go))
    tight["scope"]["max_requests"] = 600
    expect("go_max_requests_below_plan", lambda: gen(tight))

    # 3) GO 的 max_requests 低于计划请求总数
    tiny = json.loads(json.dumps(go))
    tiny["scope"]["max_requests"] = 10
    expect("go_max_requests_below_total", lambda: gen(tiny))

    # 4) GO 绑旧（公开矩阵）plan sha
    stale = json.loads(json.dumps(go))
    stale["scope"]["plan_sha256"] = PUBLIC_PLAN_SHA
    expect("go_bound_to_stale_plan_sha", lambda: gen(stale))

    # 5) GO 绑别的 plan_id（拿公开矩阵计划来撞）
    other = P2RunPlan.from_dict(mutated(plan_doc, plan_id="P2-T207-MATRIX-20261111"))
    expect("go_plan_id_mismatch", lambda: pa.authorize_p2(
        other, go_payload=go, budget_payload=budget_payload,
        ledger_snapshot=snapshot_in_mem, now=NOW))

    # 6) GO 的中心额度低于计划分配
    cheap = json.loads(json.dumps(go))
    cheap["scope"]["cost_centers_cny"] = {**cheap["scope"]["cost_centers_cny"],
                                          "answer_retrieval": 0.05}
    expect("go_cost_center_below_plan", lambda: gen(cheap))

    # 7) GO 的单请求上界低于计划单次峰值预留
    low_peak = json.loads(json.dumps(go))
    low_peak["scope"]["max_request_cny"] = 0.001
    expect("go_max_request_cny_below_peak", lambda: gen(low_peak))

    # 8) GO 过期
    expired = json.loads(json.dumps(go))
    expired["expires_utc"] = (issued + timedelta(minutes=30)).isoformat()
    expect("go_expired", lambda: gen(expired))

    # 9) 计划把灌库批数写成 600（总请求 612 > 760-691=69）→ 请求窗口不足
    expect("requests_over_remaining", lambda: pa.preflight_p2(
        P2RunPlan.from_dict(mutated(plan_doc, ingest=600)), real))

    # 10) 计划把 answer_retrieval 中心压到 0.10（低于本次上界 0.14496）
    low_center = dict(plan_doc["cost_centers_cny"])
    low_center["answer_retrieval"] = 0.1
    low_center["ocr"] = 6.5 + (8.5 - 0.1)
    expect("center_below_plan_need", lambda: pa.preflight_p2(
        P2RunPlan.from_dict(mutated(plan_doc, center=low_center)), real))

    # 11) 计划超过硬顶（1601）在构造期即拒
    expect("hard_cap_over_1600", lambda: P2RunPlan.from_dict(mutated(plan_doc, max_requests=1601)))

    # 12) 计划自身 max_requests 小于请求总数（10 < 18）
    expect("plan_requests_over_cap", lambda: P2RunPlan.from_dict(mutated(plan_doc, max_requests=10)))

    print(json.dumps({"step": "negatives", "rows": negatives}, ensure_ascii=False, indent=1))

    after = {"ledger_sha": sha(LEDGER), "budget_sha": sha(BUDGET),
             "ledger_bytes": LEDGER.stat().st_size,
             "ledger_lines": len(LEDGER.read_text(encoding="utf-8").splitlines())}
    print(json.dumps({"step": "read_only_proof", "before": before, "after": after,
                      "unchanged": before == after,
                      "go_path_exists_after": GO_PATH.exists()}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
