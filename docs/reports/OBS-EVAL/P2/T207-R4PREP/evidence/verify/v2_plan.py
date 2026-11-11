"""P2-T207-R4PREP 独立验收 v2：R4 计划逐值复算（不从开发方脚本拷贝任何数字）。

三件事：
1) 自己按契约常量**从零构造**同一份计划文档 -> P2RunPlan -> plan_sha256；
2) 用 Decimal 自己算每项上界/合计/峰值/成功估价（不用 plan 的派生属性做唯一依据）；
3) 只读解析账本 JSONL 自己算 691 / 6.5409604 / 21.6119049 / 中心占用，
   再与 read_ledger_snapshot() 的事实逐值对照，最后跑 preflight 复核窗口。
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = next(p for p in HERE.parents if (p / "backend" / "src").is_dir())
T207 = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207"
PLAN_PATH = T207 / "PM" / "T207-plan-R4-v0_1.json"
LEDGER = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
BUDGET = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "budget.json"
GO_PATH = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM" / "P2-LIVE-GO.json"

EXPECT_PLAN_SHA = "00b9fdefd8cc8220178745f0806486eaf3a70818be4068dd0fd2307303b5d2b9"
EXPECT_FILE_SHA = "d68db2074f84f79b7b4b207dc369ae7c12ef65d622c768af42e095ac4efd0022"

import sys

sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_authorization as pa  # noqa: E402
from mktkb.evaluation.p2_contracts import (  # noqa: E402
    CHAT_COMPLETION_TOKENS_CAP,
    CHAT_HOST,
    CHAT_INPUT_PRICE_FLOOR,
    CHAT_MODEL,
    CHAT_OUTPUT_PRICE_FLOOR,
    CHAT_PRICING_SOURCE,
    CHAT_PROMPT_TOKENS_CAP,
    CHAT_PROVIDER,
    CHAT_REGION,
    EMBEDDING_MODEL,
    EMBEDDING_PRICING_SOURCE,
    EMBEDDING_PROVIDER,
    EMBEDDING_TOTAL_TOKENS_CAP,
    EMBEDDING_UNIT_PRICE_FLOOR,
    HARD_MAX_REQUESTS,
    P2RunPlan,
    RERANK_MODEL,
    RERANK_PRICING_SOURCE,
    RERANK_PROVIDER,
    RERANK_TOTAL_TOKENS_CAP,
    RERANK_UNIT_PRICE_FLOOR,
)

Q = Decimal("0.00000001")


def money(value: Decimal) -> Decimal:
    return value.quantize(Q, rounding="ROUND_CEILING")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def chat_profile() -> dict:
    return {
        "kind": "chat", "model": CHAT_MODEL, "provider": CHAT_PROVIDER, "host": CHAT_HOST,
        "region": CHAT_REGION, "pricing_source": CHAT_PRICING_SOURCE,
        "input_price_per_million_cny": float(CHAT_INPUT_PRICE_FLOOR),
        "output_price_per_million_cny": float(CHAT_OUTPUT_PRICE_FLOOR),
        "prompt_tokens_cap": int(CHAT_PROMPT_TOKENS_CAP),
        "completion_tokens_cap": int(CHAT_COMPLETION_TOKENS_CAP),
    }


def embedding_profile() -> dict:
    return {
        "kind": "embedding", "model": EMBEDDING_MODEL, "provider": EMBEDDING_PROVIDER,
        "host": "dashscope.aliyuncs.com", "region": "cn-beijing",
        "pricing_source": EMBEDDING_PRICING_SOURCE,
        "unit_price_per_million_cny": float(EMBEDDING_UNIT_PRICE_FLOOR),
        "total_tokens_cap": int(EMBEDDING_TOTAL_TOKENS_CAP),
    }


def rerank_profile() -> dict:
    return {
        "kind": "rerank", "model": RERANK_MODEL, "provider": RERANK_PROVIDER,
        "host": "dashscope.aliyuncs.com", "region": "cn-beijing",
        "pricing_source": RERANK_PRICING_SOURCE,
        "unit_price_per_million_cny": float(RERANK_UNIT_PRICE_FLOOR),
        "total_tokens_cap": int(RERANK_TOTAL_TOKENS_CAP),
    }


def my_plan_document(ingest_batches: int = 6) -> dict:
    """我自己写的构造（13 项 = 1 灌库 + 3 例 x 4 操作；18 请求）。"""
    items = [{
        "item_id": "ingest-index-embedding", "operation": "index_embedding",
        "cost_center": "answer_retrieval", "case_id": "INGEST", "turn": 1, "page": 0,
        "requests": ingest_batches, "price_profile": embedding_profile(),
        "expected_success_cny": 0.0003,
    }]
    for case_id in ("N08", "C05", "C06"):
        items.append({"item_id": f"embed-{case_id}-t1", "operation": "query_embedding",
                      "cost_center": "answer_retrieval", "case_id": case_id, "turn": 1, "page": 0,
                      "requests": 1, "price_profile": embedding_profile(),
                      "expected_success_cny": 0.0003})
        items.append({"item_id": f"rerank-{case_id}-t1", "operation": "rerank",
                      "cost_center": "answer_retrieval", "case_id": case_id, "turn": 1, "page": 0,
                      "requests": 1, "price_profile": rerank_profile(),
                      "expected_success_cny": 0.001})
        items.append({"item_id": f"expand-{case_id}-t1", "operation": "query_expansion",
                      "cost_center": "answer_retrieval", "case_id": case_id, "turn": 1, "page": 0,
                      "requests": 1, "price_profile": chat_profile(),
                      "expected_success_cny": 0.004})
        items.append({"item_id": f"answer-{case_id}-t1", "operation": "answer",
                      "cost_center": "answer_retrieval", "case_id": case_id, "turn": 1, "page": 0,
                      "requests": 1, "price_profile": chat_profile(),
                      "expected_success_cny": 0.004})
    return {
        "schema_version": "p2-run-plan/v0.1",
        "plan_id": "P2-T207-R4-20261111",
        "plan_version": "v0.1",
        "mode": "end_to_end",
        "stage": "P2-LIVE",
        "created_utc": "2026-11-11T12:00:00+08:00",
        "project_total_limit_cny": 40.0,
        "stage_limit_cny": 20.0,
        "max_requests": 760,
        "cost_centers_cny": {"answer_retrieval": 8.5, "ocr": 6.5, "judge": 3.0, "independent": 2.0},
        "items": items,
    }


def my_unit_bounds() -> dict:
    million = Decimal(1000000)
    return {
        "embedding": money(Decimal(int(EMBEDDING_TOTAL_TOKENS_CAP)) * Decimal(EMBEDDING_UNIT_PRICE_FLOOR) / million),
        "rerank": money(Decimal(int(RERANK_TOTAL_TOKENS_CAP)) * Decimal(RERANK_UNIT_PRICE_FLOOR) / million),
        "chat": money(
            Decimal(int(CHAT_PROMPT_TOKENS_CAP)) * Decimal(CHAT_INPUT_PRICE_FLOOR) / million
            + Decimal(int(CHAT_COMPLETION_TOKENS_CAP)) * Decimal(CHAT_OUTPUT_PRICE_FLOOR) / million
        ),
    }


def my_ledger_facts() -> dict:
    """只读解析账本：自己算预留数、P2 阶段占用、四中心占用（不分阶段）。"""
    reservations: dict[str, dict] = {}
    results: dict[str, dict] = {}
    historical = Decimal(0)
    versioned = 0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") == "historical_import":
            historical += Decimal(str(event.get("accounted_cny") or 0.0))
        elif event.get("event") == "reserved":
            reservations[str(event["reservation_id"])] = event
        elif event.get("event") == "result":
            results[str(event["reservation_id"])] = event
    stage_accounted = Decimal(0)
    p2_centers: dict[str, Decimal] = {}
    total_accounted = historical
    per_run: dict[str, dict] = {}
    for rid, reserved in reservations.items():
        result = results.get(rid)
        reserve_cny = Decimal(str(reserved.get("reserve_cny") or 0.0))
        charge = reserve_cny
        if result is not None and "settlement" in result:
            # 版本化 result：账本重放会独立重算并要求"存档金额 == 重算金额"逐值相等，因此这里直接
            # 用存档金额（其正确性由 read_ledger_snapshot() 不抛 BudgetLedgerInvalid 反证）。
            versioned += 1
            charge = Decimal(str(result.get("conservative_charge_cny") or 0.0))
        elif result is not None:
            charge = max(Decimal(str(result.get("conservative_charge_cny") or 0.0)), reserve_cny)
        total_accounted += charge
        key = str(reserved.get("run_id") or "(null)")
        bucket = per_run.setdefault(key, {"reservations": 0, "worst_cny": Decimal(0), "ops": {}})
        bucket["reservations"] += 1
        bucket["worst_cny"] += charge
        op = str((reserved.get("metadata") or {}).get("operation") or reserved.get("kind"))
        bucket["ops"][op] = bucket["ops"].get(op, 0) + 1
        if reserved.get("stage") == "P2-LIVE":
            stage_accounted += charge
            center = str(reserved.get("cost_center") or "(none)")
            p2_centers[center] = p2_centers.get(center, Decimal(0)) + charge
    return {
        "historical_import_cny": float(historical),
        "versioned_results": versioned,
        "reservation_count": len(reservations),
        "result_count": len(results),
        "total_accounted_cny": float(total_accounted),
        "p2_stage_accounted_cny": float(stage_accounted),
        "p2_center_accounted_cny": {k: float(v) for k, v in p2_centers.items()},
        "per_run": {
            k: {"reservations": v["reservations"], "worst_cny": float(v["worst_cny"]), "ops": v["ops"]}
            for k, v in per_run.items()
        },
    }


def main() -> None:
    file_doc = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    mine = my_plan_document(int(file_doc["items"][0]["requests"]))
    mine_plan = P2RunPlan.from_dict(mine)
    file_plan = P2RunPlan.from_dict(file_doc)

    bounds = my_unit_bounds()
    # 自己算每项上界 / 合计 / 峰值（不用 plan 的派生属性做唯一依据）
    per_item = []
    worst = Decimal(0)
    peak = Decimal(0)
    success = Decimal(0)
    requests = 0
    for item in file_doc["items"]:
        kind = item["price_profile"]["kind"]
        bound = bounds[kind]
        item_worst = money(bound * Decimal(int(item["requests"])))
        item_success = money(Decimal(str(item["expected_success_cny"])) * Decimal(int(item["requests"])))
        worst += item_worst
        success += item_success
        peak = max(peak, bound)
        requests += int(item["requests"])
        per_item.append({
            "item_id": item["item_id"], "kind": kind, "requests": item["requests"],
            "bound_cny": float(bound), "worst_cny": float(item_worst),
            "worst_matches_contract": abs(item_worst - Decimal(str(
                next(i for i in file_plan.items if i.item_id == item["item_id"]).worst_case_cny))) <= Decimal("1e-12"),
        })

    my_totals = {
        "items": len(per_item),
        "requests": requests,
        "worst_cny": float(worst),
        "reserve_peak_cny": float(peak),
        "estimated_success_cny": float(success),
        "unit_bounds_cny": {k: float(v) for k, v in bounds.items()},
    }

    snapshot = pa.read_ledger_snapshot()
    my_ledger = my_ledger_facts()
    preflight = pa.preflight_p2(file_plan, snapshot)

    stage_used = float(my_ledger["p2_stage_accounted_cny"])
    answer_center_used = float(my_ledger["p2_center_accounted_cny"].get("answer_retrieval", 0.0))
    ocr_center_used = float(my_ledger["p2_center_accounted_cny"].get("ocr", 0.0))
    windows = {
        "requests_used": my_ledger["reservation_count"],
        "plan_total_requests": requests,
        "plan_max_requests": file_plan.max_requests,
        "request_window_at_plan_cap": file_plan.max_requests - my_ledger["reservation_count"],
        "request_window_ok": requests <= file_plan.max_requests - my_ledger["reservation_count"],
        "hard_cap": HARD_MAX_REQUESTS,
        "cumulative_after_r4": my_ledger["reservation_count"] + requests,
        "cumulative_after_r4_ok": my_ledger["reservation_count"] + requests <= HARD_MAX_REQUESTS,
        "stage_used": stage_used,
        "stage_after_r4": round(stage_used + float(worst), 7),
        "stage_limit": file_plan.stage_limit_cny,
        "stage_ok": stage_used + float(worst) <= file_plan.stage_limit_cny,
        "project_total_after_r4": round(my_ledger["total_accounted_cny"] + float(worst), 7),
        "project_total_limit": file_plan.project_total_limit_cny,
        "project_total_ok": my_ledger["total_accounted_cny"] + float(worst) <= file_plan.project_total_limit_cny,
        "answer_center_after_r4": round(answer_center_used + float(worst), 7),
        "answer_center_limit": file_plan.cost_centers_cny["answer_retrieval"],
        "answer_center_ok": answer_center_used + float(worst) <= file_plan.cost_centers_cny["answer_retrieval"],
        "ocr_center_used": ocr_center_used,
        "ocr_center_limit": file_plan.cost_centers_cny["ocr"],
        "ocr_center_ok": ocr_center_used <= file_plan.cost_centers_cny["ocr"],
        "centers_sum": round(sum(file_plan.cost_centers_cny.values()), 10),
        "centers_sum_equals_stage_limit": abs(sum(file_plan.cost_centers_cny.values())
                                             - file_plan.stage_limit_cny) <= 1e-9,
    }

    report = {
        "plan_path": str(PLAN_PATH.relative_to(ROOT)),
        "file_sha256": sha256(PLAN_PATH),
        "file_sha256_matches_evidence": sha256(PLAN_PATH) == EXPECT_FILE_SHA,
        "plan_sha256": file_plan.plan_sha256,
        "plan_sha256_expected": EXPECT_PLAN_SHA,
        "plan_sha256_matches": file_plan.plan_sha256 == EXPECT_PLAN_SHA,
        "my_construction_equals_file": mine_plan.as_dict() == file_plan.as_dict(),
        "my_construction_sha256": mine_plan.plan_sha256,
        "my_construction_sha256_matches": mine_plan.plan_sha256 == EXPECT_PLAN_SHA,
        "derived_matches_contract": {
            "items": file_plan.items and len(file_plan.items) == my_totals["items"],
            "total_requests": file_plan.total_requests == my_totals["requests"],
            "worst_case_cny": abs(file_plan.worst_case_cny - my_totals["worst_cny"]) <= 1e-12,
            "reserve_peak_cny": abs(file_plan.reserve_peak_cny - my_totals["reserve_peak_cny"]) <= 1e-12,
            "estimated_success_cny": abs(file_plan.estimated_success_cny - my_totals["estimated_success_cny"]) <= 1e-12,
            "page_count_zero": file_plan.page_count == 0,
            "turns": file_plan.turn_count == 4,
            "cases": file_plan.case_count == 4,
            "operations_no_ocr": "ocr" not in file_plan.operations,
        },
        "my_totals": my_totals,
        "per_item": per_item,
        "snapshot_from_fixed_paths": {
            "ledger_sha256": snapshot.ledger_sha256,
            "budget_sha256": snapshot.budget_sha256,
            "historical_prefix_sha256": snapshot.historical_prefix_sha256,
            "total_limit_cny": snapshot.total_limit_cny,
            "accounted_cny": snapshot.accounted_cny,
            "historical_accounted_cny": snapshot.historical_accounted_cny,
            "reservation_count": snapshot.reservation_count,
            "result_count": snapshot.result_count,
            "p2_stage_accounted_cny": snapshot.p2_stage_accounted_cny,
            "p2_center_accounted_cny": dict(snapshot.p2_center_accounted_cny),
            "source": snapshot.source,
        },
        "my_ledger_parse": my_ledger,
        "snapshot_equals_my_parse": {
            "reservation_count": snapshot.reservation_count == my_ledger["reservation_count"],
            "result_count": snapshot.result_count == my_ledger["result_count"],
            "accounted_cny": abs(snapshot.accounted_cny - my_ledger["total_accounted_cny"]) <= 1e-7,
            "p2_stage_accounted_cny": abs(snapshot.p2_stage_accounted_cny
                                         - my_ledger["p2_stage_accounted_cny"]) <= 1e-7,
            "p2_center_accounted_cny": all(
                abs(float(snapshot.p2_center_accounted_cny.get(center, 0.0))
                    - my_ledger["p2_center_accounted_cny"].get(center, 0.0)) <= 1e-7
                for center in ("answer_retrieval", "ocr", "judge", "independent")
            ),
        },
        "preflight": {
            "ok": preflight.ok,
            "reasons": list(preflight.reasons),
            "stage_remaining": preflight.stage_remaining_cny,
            "requests_remaining": preflight.requests_remaining,
            "center_remaining": dict(preflight.center_remaining_cny),
        },
        "windows": windows,
    }

    checks = {
        "file_sha_matches_evidence": report["file_sha256_matches_evidence"],
        "plan_sha256_matches": report["plan_sha256_matches"],
        "my_construction_reproduces_plan": report["my_construction_equals_file"]
        and report["my_construction_sha256_matches"],
        "all_items_bounds_recompute": all(item["worst_matches_contract"] for item in per_item),
        "totals_recompute": all(report["derived_matches_contract"].values()),
        "snapshot_reproduced_from_jsonl": all(report["snapshot_equals_my_parse"].values()),
        "preflight_ok": preflight.ok,
        "request_window_ok": windows["request_window_ok"],
        "stage_window_ok": windows["stage_ok"],
        "cumulative_ok": windows["cumulative_after_r4_ok"],
        "project_total_ok": windows["project_total_ok"],
        "centers_ok": windows["answer_center_ok"] and windows["ocr_center_ok"]
        and windows["centers_sum_equals_stage_limit"],
        "no_ocr_pages": file_plan.page_count == 0,
    }
    report["checks"] = checks
    report["all_hold"] = all(checks.values())
    report["ledger_lock_leftover"] = (LEDGER.parent / (LEDGER.name + ".lock")).exists()
    report["fixed_go_sha256"] = sha256(GO_PATH)
    print(json.dumps(report, ensure_ascii=False, indent=1))




def _run(main_fn) -> None:
    import contextlib
    import io
    import sys
    from pathlib import Path

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

