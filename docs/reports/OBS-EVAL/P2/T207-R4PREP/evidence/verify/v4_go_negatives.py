"""P2-T207-R4PREP 独立验收 v4：候选 GO 授权链 + 12 条负例 + 固定路径 GO 未被动（只读）。

逻辑独立于开发方的 validate-r4.py：本脚本自己造负例、自己断言稳定码，并额外补两条
开发方负例里没有覆盖的谓词（preflight 的中心窗口、GO 的账本绑定）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = next(p for p in HERE.parents if (p / "backend" / "src").is_dir())
T207 = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207"
PM = T207 / "PM"
PLAN = PM / "T207-plan-R4-v0_1.json"
GO = PM / "T207-GO-R4.CANDIDATE-DRAFT.json"
CASES = T207 / "cases" / "R4.jsonl"
INGEST = PM / "T207-ingest-plan-R4.json"
FIXED_GO = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM" / "P2-LIVE-GO.json"
BUDGET = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "budget.json"
LEDGER = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
NOW = datetime(2026, 11, 11, 13, 0, tzinfo=timezone(timedelta(hours=8)))

sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_authorization as pa  # noqa: E402
from mktkb.evaluation.p2_contracts import P2LedgerSnapshot, P2RunPlan  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def memory_snapshot(real: P2LedgerSnapshot) -> P2LedgerSnapshot:
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


def code_of(fn) -> dict:
    try:
        outcome = fn()
        if hasattr(outcome, "ok"):
            return {"kind": "preflight", "ok": bool(outcome.ok), "reasons": list(outcome.reasons)}
        return {"kind": "pass", "outcome": type(outcome).__name__}
    except Exception as exc:  # noqa: BLE001 - 被测行为
        reason = getattr(exc, "reason", None) or getattr(exc, "code", None)
        return {"kind": type(exc).__name__, "code": reason, "message": str(exc)[:160]}


def main() -> None:
    before = {
        "ledger": sha(LEDGER), "budget": sha(BUDGET), "fixed_go": sha(FIXED_GO),
        "plan": sha(PLAN), "go": sha(GO), "cases": sha(CASES), "ingest": sha(INGEST),
    }
    real = pa.read_ledger_snapshot()
    plan_doc = json.loads(PLAN.read_text(encoding="utf-8"))
    plan = P2RunPlan.from_dict(plan_doc)
    go = json.loads(GO.read_text(encoding="utf-8"))
    budget_payload = pa.load_budget_payload()
    snapshot = memory_snapshot(real)

    def authorize(go_doc: dict, the_plan: P2RunPlan = plan):
        return pa.authorize_p2(the_plan, go_payload=go_doc, budget_payload=budget_payload,
                               ledger_snapshot=snapshot, now=NOW)

    # ---------------------------------------------------------------- 1) 候选 GO 的 payload 自查
    payload_checks = {
        "document": go.get("document") == "P2-LIVE-GO",
        "draft_marked_not_usable": ("DRAFT" in str(go.get("authorization")))
        and ("NOT USABLE" in str(go.get("authorization"))),
        "plan_sha_bound": go["scope"]["plan_sha256"] == plan.plan_sha256,
        "plan_id_bound": go["scope"]["plan_id"] == plan.plan_id,
        "ledger_sha_is_history_prefix": go.get("budget_ledger_sha256") == real.historical_prefix_sha256,
        "ledger_path_is_fixed": str(go.get("budget_ledger_path")) == str(
            (ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl")
        ).replace("/", "\\") or go.get("budget_ledger_path", "").endswith("budget\\live-ledger.jsonl"),
        "five_operations_no_ocr": sorted(go["scope"]["operations"]) == [
            "answer", "index_embedding", "query_embedding", "query_expansion", "rerank"],
        "max_requests_760": go["scope"]["max_requests"] == 760,
        "max_request_cny_0_5": go["scope"]["max_request_cny"] == 0.5,
        "centers_8_5_6_5_3_2": go["scope"]["cost_centers_cny"] == {
            "answer_retrieval": 8.5, "ocr": 6.5, "judge": 3.0, "independent": 2.0},
        "budget_total_limit_40": go["budget_total_limit_cny"] == 40.0,
        "validity_days_13": (datetime.fromisoformat(go["expires_utc"])
                             - datetime.fromisoformat(go["issued_utc"])).days == 13,
        "stage_limit_20": go["scope"]["stage_limits_cny"] == {"P2-LIVE": 20.0},
    }

    # ---------------------------------------------------------------- 2) 授权链：候选 GO 通过但不可生产
    auth = authorize(go)
    auth_view = {
        "production_ready": auth.production_ready,
        "go_sha256_matches_candidate": auth.go_sha256 == pa.payload_sha256(go),
        "plan_sha256": auth.plan_sha256,
        "max_requests": auth.max_requests,
        "max_request_cny": auth.max_request_cny,
        "stage_remaining_cny": auth.stage_remaining_cny,
        "requests_remaining": auth.requests_remaining,
        "center_remaining_cny": dict(auth.center_remaining_cny),
        "operations": list(auth.operations),
    }

    # ---------------------------------------------------------------- 3) 固定路径 GO 不能授权 R4
    fixed_go_doc = json.loads(FIXED_GO.read_text(encoding="utf-8"))
    fixed_go_attempt = code_of(lambda: authorize(fixed_go_doc))
    fixed_go_attempt_from_path = code_of(lambda: pa.authorize_p2(
        plan, go_payload=str(FIXED_GO), budget_payload=str(BUDGET),
        ledger_snapshot=real, now=NOW))

    # ---------------------------------------------------------------- 4) 12 条负例（我自己的造法）
    negatives: list[dict] = []

    def neg(label: str, fn, expected: str) -> None:
        result = code_of(fn)
        got = result.get("code") or (result.get("reasons") or [None])[0]
        negatives.append({"case": label, "expected": expected, "observed": got,
                          "pass": got == expected, "kind": result.get("kind"),
                          "message": result.get("message")})

    def mutate_plan(**kwargs) -> dict:
        doc = json.loads(json.dumps(plan_doc))
        for item in doc["items"]:
            if item["item_id"] == "ingest-index-embedding" and "ingest" in kwargs:
                item["requests"] = kwargs["ingest"]
        if "max_requests" in kwargs:
            doc["max_requests"] = kwargs["max_requests"]
        if "centers" in kwargs:
            doc["cost_centers_cny"] = kwargs["centers"]
        if "plan_id" in kwargs:
            doc["plan_id"] = kwargs["plan_id"]
        return doc

    def mutate_go(**scope_changes) -> dict:
        doc = json.loads(json.dumps(go))
        for key, value in scope_changes.items():
            if key == "expires_utc":
                doc["expires_utc"] = value
            else:
                doc["scope"][key] = value
        return doc

    # 1 GO 少一个计划操作
    no_rerank = mutate_go(operations=["answer", "index_embedding", "query_embedding", "query_expansion"])
    neg("go_missing_rerank_operation", lambda: authorize(no_rerank), "go_operation_unauthorized")
    # 2 GO max_requests 低于计划自身 max_requests(760)
    neg("go_max_requests_below_plan_cap", lambda: authorize(mutate_go(max_requests=600)),
        "go_max_requests_below_plan")
    # 3 GO max_requests 低于计划请求总数(18)
    neg("go_max_requests_below_plan_total", lambda: authorize(mutate_go(max_requests=10)),
        "go_max_requests_below_plan")
    # 4 GO 绑旧计划 sha
    neg("go_bound_to_stale_plan_sha",
        lambda: authorize(mutate_go(plan_sha256="0b4e55a4cd3a46f968e89fe495ffca3c6931c8f49f1f258a3dd753f83e24a194")),
        "go_plan_sha256_mismatch")
    # 5 GO 绑别的 plan_id
    other_plan = P2RunPlan.from_dict(mutate_plan(plan_id="P2-T207-MATRIX-20261111"))
    neg("go_plan_id_mismatch", lambda: authorize(go, other_plan), "go_plan_id_mismatch")
    # 6 GO 的中心额度低于计划分配
    neg("go_cost_center_below_plan",
        lambda: authorize(mutate_go(cost_centers_cny={
            "answer_retrieval": 0.05, "ocr": 6.5, "judge": 3.0, "independent": 2.0})),
        "go_cost_center_below_plan")
    # 7 GO 的单请求上界低于计划峰值预留
    neg("go_max_request_cny_below_peak", lambda: authorize(mutate_go(max_request_cny=0.001)),
        "go_max_request_cny_below_plan")
    # 8 GO 过期
    neg("go_expired", lambda: authorize(mutate_go(
        expires_utc=(datetime.fromisoformat(go["issued_utc"]) + timedelta(minutes=30)).isoformat())),
        "go_expired")
    # 9 计划把灌库批数写成 600 -> 请求窗口不足（preflight）
    neg("requests_over_remaining", lambda: pa.preflight_p2(
        P2RunPlan.from_dict(mutate_plan(ingest=600)), real), "request_budget_insufficient")
    # 10 计划把硬顶写成 1601 -> 构造期拒
    neg("plan_max_requests_over_hard_cap", lambda: P2RunPlan.from_dict(
        mutate_plan(max_requests=1601)), "request_cap_over_hard_limit")
    # 11 计划自身 max_requests 小于请求总数
    neg("plan_requests_over_cap", lambda: P2RunPlan.from_dict(
        mutate_plan(max_requests=10)), "plan_requests_over_cap")
    # 12 计划中心额度低于计划自身需要（构造期拒）
    neg("plan_center_below_need", lambda: P2RunPlan.from_dict(mutate_plan(centers={
        "answer_retrieval": 0.1, "ocr": 14.9, "judge": 3.0, "independent": 2.0})),
        "center_budget_exceeded")

    # ---------------------------------------------------------------- 5) 我补的两条（开发方负例未覆盖）
    extra: list[dict] = []

    def extra_neg(label: str, fn, expected: str) -> None:
        result = code_of(fn)
        got = result.get("code") or (result.get("reasons") or [None])[0]
        extra.append({"case": label, "expected": expected, "observed": got,
                      "pass": got == expected, "kind": result.get("kind")})

    # A) preflight 的"中心剩余窗口"（构造合法：0.15 >= 需要 0.14496，四中心合计仍 20）
    extra_neg("preflight_center_window_insufficient", lambda: pa.preflight_p2(
        P2RunPlan.from_dict(mutate_plan(centers={
            "answer_retrieval": 0.15, "ocr": 14.85, "judge": 3.0, "independent": 2.0})), real),
        "center_budget_insufficient:answer_retrieval")
    # B) GO 的账本绑定不是当前历史前缀
    extra_neg("go_ledger_binding_mismatch", lambda: authorize(
        {**go, "budget_ledger_sha256": "0" * 64}), "go_ledger_binding_mismatch")

    after = {
        "ledger": sha(LEDGER), "budget": sha(BUDGET), "fixed_go": sha(FIXED_GO),
        "plan": sha(PLAN), "go": sha(GO), "cases": sha(CASES), "ingest": sha(INGEST),
    }
    checks = {
        "go_payload_all_ok": all(payload_checks.values()),
        "authorize_passes_but_not_production_ready": auth_view["production_ready"] is False
        and auth_view["go_sha256_matches_candidate"],
        "fixed_path_go_rejected_for_r4": (fixed_go_attempt_from_path.get("code") in {
            "go_plan_id_mismatch", "go_plan_sha256_mismatch"}), 
        "twelve_negatives_all_rejected_with_expected_code": all(item["pass"] for item in negatives)
        and len(negatives) == 12,
        "extra_negatives_pass": all(item["pass"] for item in extra),
        "files_unchanged": before == after,
    }
    report = {
        "go_payload_checks": payload_checks,
        "authorization": auth_view,
        "fixed_go": {
            "sha256_before": before["fixed_go"],
            "sha256_after": after["fixed_go"],
            "document": fixed_go_doc.get("document"),
            "authorization_text": str(fixed_go_doc.get("authorization"))[:120],
            "attempt_with_payload_dict": fixed_go_attempt,
            "attempt_from_fixed_path": fixed_go_attempt_from_path,
        },
        "negatives": negatives,
        "extra_negatives": extra,
        "before": before,
        "after": after,
        "checks": checks,
        "all_hold": all(checks.values()),
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))


def _run(main_fn) -> None:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        main_fn()
    text = buffer.getvalue()
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    if out:
        Path(out).write_text(text, encoding="utf-8")
    sys.stdout.write(text)


if __name__ == "__main__":
    _run(main)
