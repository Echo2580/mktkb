"""P2-T207 纯契约离线校验：计划/候选 GO/预检/授权/负例（零真实调用）。

- 计划与候选 GO 只被 json 读一次；
- **真实**账本快照用 p2_authorization.read_ledger_snapshot()（只读，前后 SHA 必须一致）；
- 不写账本、不写预算、不创建 GO、不发 HTTP、不读 .env/H2。

用法（仓库根）：
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207/evidence/validate-plan.py
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

LEDGER = REPO / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
BUDGET = REPO / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "budget.json"
GO_PATH = REPO / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM" / "P2-LIVE-GO.json"


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
            center: dict | None = None, plan_id: str | None = None,
            plan_version: str | None = None) -> dict:
    doc = json.loads(json.dumps(plan_doc))
    if plan_id is not None:
        doc["plan_id"] = plan_id
    if plan_version is not None:
        doc["plan_version"] = plan_version
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
    plan_doc = load("T207-plan-v0_1.json")
    plan = P2RunPlan.from_dict(plan_doc)
    go = load("T207-GO.CANDIDATE-DRAFT.json")
    budget_payload = pa.load_budget_payload()

    print(json.dumps({
        "step": "plan",
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "items": len(plan.items),
        "cases": plan.case_count,
        "turns": plan.turn_count,
        "ocr_pages": plan.page_count,
        "total_requests": plan.total_requests,
        "max_requests": plan.max_requests,
        "worst_case_cny": plan.worst_case_cny,
        "reserve_peak_cny": plan.reserve_peak_cny,
        "estimated_success_cny": plan.estimated_success_cny,
        "by_operation": plan.requests_by_operation(),
        "center_needs_cny": dict(plan.center_needs_cny()),
        "center_limits_cny": dict(plan.cost_centers_cny),
        "hard_max_requests": HARD_MAX_REQUESTS,
    }, ensure_ascii=False, indent=1))

    issued = datetime.fromisoformat(go["issued_utc"])
    expires = datetime.fromisoformat(go["expires_utc"])
    print(json.dumps({
        "step": "go_candidate",
        "document": go["document"],
        "authorization": go["authorization"],
        "plan_id_bound": go["scope"]["plan_id"] == plan.plan_id,
        "plan_sha_bound": go["scope"]["plan_sha256"] == plan.plan_sha256,
        "max_requests": go["scope"]["max_requests"],
        "max_request_cny": go["scope"]["max_request_cny"],
        "validity_days": (expires - issued).days,
        "ledger_sha_is_history_prefix": go["budget_ledger_sha256"] == real.historical_prefix_sha256,
        "operations": go["scope"]["operations"],
        "centers": go["scope"]["cost_centers_cny"],
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
        "go_path_exists": GO_PATH.exists(),
    }, ensure_ascii=False, indent=1))

    now = datetime(2026, 11, 11, 9, 0, tzinfo=timezone(timedelta(hours=8)))
    auth = pa.authorize_p2(plan, go_payload=go, budget_payload=budget_payload,
                           ledger_snapshot=memory_snapshot(real), now=now)
    print(json.dumps({
        "step": "authorize_candidate",
        "production_ready": auth.production_ready,
        "go_sha256": auth.go_sha256,
        "plan_sha256": auth.plan_sha256,
        "stage_remaining_cny": auth.stage_remaining_cny,
        "requests_used": auth.requests_used,
        "requests_remaining": auth.requests_remaining,
        "max_requests": auth.max_requests,
        "operation_count": len(auth.operations),
        "note": "production_ready=False ⇒ 候选 GO 不可发送；只有经理落盘的固定路径 GO 才可能为 True",
    }, ensure_ascii=False, indent=1))

    negatives: list[dict] = []
    snapshot_in_mem = memory_snapshot(real)

    def expect(label: str, fn) -> None:
        """负例：授权类必须抛稳定 reason；预检类必须返回 ok=False + 稳定 reason 码。"""
        try:
            outcome = fn()
            ok = getattr(outcome, "ok", None)
            if ok is False:
                negatives.append({"case": label, "kind": "preflight",
                                  "reasons": list(outcome.reasons)})
            else:
                negatives.append({"case": label, "result": "UNEXPECTED-PASS"})
        except Exception as exc:  # noqa: BLE001
            negatives.append({"case": label, "kind": "authorize",
                              "reason": getattr(exc, "reason", None) or getattr(exc, "code", None)
                              or type(exc).__name__})

    legacy = json.loads(json.dumps(go))
    legacy["document"] = "S2-LIVE-GO"
    expect("legacy_p1_go", lambda: pa.authorize_p2(
        plan, go_payload=legacy, budget_payload=budget_payload,
        ledger_snapshot=snapshot_in_mem, now=now))

    other_plan = P2RunPlan.from_dict(mutated(plan_doc, plan_id="P2-T207-OTHER"))
    expect("plan_sha_mismatch", lambda: pa.authorize_p2(
        other_plan, go_payload=go, budget_payload=budget_payload,
        ledger_snapshot=snapshot_in_mem, now=now))

    # 只改版本号（plan_id 不变）→ 摘要变、ID 不变 → 必须是 go_plan_sha256_mismatch 而不是 id 不匹配
    sha_only = P2RunPlan.from_dict(mutated(plan_doc, plan_version="v0.1-mutated"))
    expect("plan_sha_mismatch_only", lambda: pa.authorize_p2(
        sha_only, go_payload=go, budget_payload=budget_payload,
        ledger_snapshot=snapshot_in_mem, now=now))

    ocr_center = dict(plan_doc["cost_centers_cny"])
    ocr_center["answer_retrieval"] = 9.0
    ocr_center["ocr"] = 6.0
    expect("ocr_center_6_0_below_usage", lambda: pa.preflight_p2(
        P2RunPlan.from_dict(mutated(plan_doc, center=ocr_center)), real))

    expect("requests_over_remaining", lambda: pa.preflight_p2(
        P2RunPlan.from_dict(mutated(plan_doc, ingest=500)), real))

    # T207-FIX-A §7：硬顶已落盘 1600；1600 可建、1601 拒。公开计划自身 1200 必须仍然可建。
    assert P2RunPlan.from_dict(mutated(plan_doc, max_requests=1200)).max_requests == 1200
    assert P2RunPlan.from_dict(mutated(plan_doc, max_requests=1600)).max_requests == 1600
    expect("hard_cap_over_1600", lambda: P2RunPlan.from_dict(mutated(plan_doc, max_requests=1601)))

    expired = json.loads(json.dumps(go))
    expired["expires_utc"] = (issued + timedelta(minutes=30)).isoformat()
    expect("go_expired", lambda: pa.authorize_p2(
        plan, go_payload=expired, budget_payload=budget_payload,
        ledger_snapshot=snapshot_in_mem, now=now))

    tight = json.loads(json.dumps(go))
    tight["scope"]["max_requests"] = 200
    expect("go_max_requests_below_plan", lambda: pa.authorize_p2(
        plan, go_payload=tight, budget_payload=budget_payload,
        ledger_snapshot=snapshot_in_mem, now=now))

    small_req = json.loads(json.dumps(go))
    small_req["scope"]["max_request_cny"] = 0.1
    expect("go_max_request_cny_below_peak", lambda: pa.authorize_p2(
        plan, go_payload=small_req, budget_payload=budget_payload,
        ledger_snapshot=snapshot_in_mem, now=now))

    no_ocr = json.loads(json.dumps(go))
    no_ocr["scope"]["operations"] = [op for op in no_ocr["scope"]["operations"] if op != "ocr"]
    expect("go_operation_unauthorized_ocr", lambda: pa.authorize_p2(
        plan, go_payload=no_ocr, budget_payload=budget_payload,
        ledger_snapshot=snapshot_in_mem, now=now))

    print(json.dumps({"step": "negatives", "rows": negatives}, ensure_ascii=False, indent=1))

    # ---------------------------------------------------------------- 三次 run 的授权窗口
    # 每次 run = 新开一扇门（独立进程）。累计口径：plan.total_requests <= max_requests - 已用；
    # 中心口径：已占 + 计划上界 <= 中心额度。R1 含 12 页 OCR（5.65），所以**只有**在 ocr 已占
    # 仍 <= 0.85 时才允许它被授权 —— 这决定了顺序必须是 R3 -> R2 -> R1（详见 cost §3/§8）。
    RUNS = (
        ("R3", 6, 0.04832, {"answer_retrieval": 0.044224 + 0.004096}),
        ("R2", 15, 0.102784, {"answer_retrieval": 0.088448 + 0.014336}),
        ("R1", 242, 7.994704, {"answer_retrieval": 2.344704, "ocr": 5.65}),
    )
    stage_used = float(real.p2_stage_accounted_cny)
    center_used = {name: float(value) for name, value in real.p2_center_accounted_cny.items()}
    requests_used = int(real.reservation_count)
    windows: list[dict] = []
    for name, requests, spend, by_center in RUNS:
        snapshot = P2LedgerSnapshot(
            schema_version=real.schema_version,
            ledger_path=real.ledger_path,
            ledger_sha256=real.ledger_sha256,
            historical_prefix_sha256=real.historical_prefix_sha256,
            budget_sha256=real.budget_sha256,
            total_limit_cny=real.total_limit_cny,
            historical_accounted_cny=real.historical_accounted_cny,
            accounted_cny=real.accounted_cny,
            reservation_count=requests_used,
            result_count=real.result_count,
            stage_allocations_cny=dict(real.stage_allocations_cny),
            p2_stage_accounted_cny=stage_used,
            p2_center_accounted_cny=dict(center_used),
            source="in-memory",
        )
        pre = pa.preflight_p2(plan, snapshot)
        windows.append({
            "run": name,
            "requests_used_before": requests_used,
            "requests_this_run": requests,
            "ceiling_used_plus_planned": requests_used + pre.requests_planned,
            "max_requests": plan.max_requests,
            "preflight_ok": pre.ok,
            "reasons": list(pre.reasons),
            "stage_remaining_before": pre.stage_remaining_cny,
            "worst_case_this_run": spend,
        })
        requests_used += requests
        stage_used = round(stage_used + spend, 10)
        for center, amount in by_center.items():
            center_used[center] = round(center_used.get(center, 0.0) + amount, 10)
    print(json.dumps({
        "step": "runs_authorization",
        "order": [row[0] for row in RUNS],
        "windows": windows,
        "cumulative": {
            "requests": 547 + sum(row[1] for row in RUNS),
            "worst_case_cny": round(sum(row[2] for row in RUNS), 6),
        },
        "why_this_order": (
            "OCR 中心窗口：计划含 12 页 OCR（上界 5.65），R1 跑完后 ocr 已占 6.15，"
            "余 0.35 < 5.65，再次授权必然 center_budget_insufficient:ocr；"
            "R3/R2 不消耗 OCR，故先跑它们、R1 最后跑（各 run 仍独立进程 + 新门）。"
        ),
    }, ensure_ascii=False, indent=1))

    # 反证：若先跑 R1，R2 的授权会被 OCR 中心窗口拒绝（不是请求数不够）。
    stage_after_r1 = float(real.p2_stage_accounted_cny) + 7.994704
    center_after_r1 = {
        name: float(value) for name, value in real.p2_center_accounted_cny.items()
    }
    center_after_r1["answer_retrieval"] = round(center_after_r1.get("answer_retrieval", 0.0) + 2.344704, 10)
    center_after_r1["ocr"] = round(center_after_r1.get("ocr", 0.0) + 5.65, 10)
    snapshot_after_r1 = P2LedgerSnapshot(
        schema_version=real.schema_version,
        ledger_path=real.ledger_path,
        ledger_sha256=real.ledger_sha256,
        historical_prefix_sha256=real.historical_prefix_sha256,
        budget_sha256=real.budget_sha256,
        total_limit_cny=real.total_limit_cny,
        historical_accounted_cny=real.historical_accounted_cny,
        accounted_cny=real.accounted_cny,
        reservation_count=int(real.reservation_count) + 242,
        result_count=real.result_count,
        stage_allocations_cny=dict(real.stage_allocations_cny),
        p2_stage_accounted_cny=stage_after_r1,
        p2_center_accounted_cny=center_after_r1,
        source="in-memory",
    )
    after_r1 = pa.preflight_p2(plan, snapshot_after_r1)
    print(json.dumps({
        "step": "reorder_control",
        "if_r1_first": {
            "ok": after_r1.ok,
            "reasons": list(after_r1.reasons),
            "requests_remaining": after_r1.requests_remaining,
            "requests_planned": after_r1.requests_planned,
            "center_remaining": dict(after_r1.center_remaining_cny),
            "note": "请求窗口够（653-242=411 >= 254），但 ocr 中心不够 → 必须先 R3/R2 再 R1",
        },
    }, ensure_ascii=False, indent=1))

    after = {"ledger_sha": sha(LEDGER), "budget_sha": sha(BUDGET),
             "ledger_bytes": LEDGER.stat().st_size,
             "ledger_lines": len(LEDGER.read_text(encoding="utf-8").splitlines())}
    print(json.dumps({"step": "read_only_proof", "before": before, "after": after,
                      "unchanged": before == after,
                      "go_path_exists_after": GO_PATH.exists()}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
