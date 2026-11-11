r"""P2-T207：正式矩阵计划 + 候选 GO 的**确定性构造**（零真实调用、零网络、零写入账本）。

用法（仓库根）：
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207/evidence/build-plan.py

产物（只写本包目录）：
  PM/T207-plan-v0_1.json                公开矩阵计划（P2RunPlan，当前代码可表达）
  PM/T207-plan-h2-v0_1.template.json    H2 受限计划模板（**不是** P2RunPlan；case_id/turn 由封存进程生成）
  PM/T207-GO.CANDIDATE-DRAFT.json       公开矩阵候选 GO（DRAFT，不可用）
  PM/T207-GO-h2.CANDIDATE-DRAFT.json    H2 候选 GO（DRAFT；plan_sha256 待封存计划生成后填入）

所有价格画像来自 p2_contracts 的冻结常量；本脚本不读 .env、不读 H2、不 import 需要网络的东西。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[6]                       # docs/reports/OBS-EVAL/P2/T207/evidence -> repo root
PM = HERE.parents[1] / "PM"
sys.path.insert(0, str(REPO / "backend" / "src"))

from mktkb.evaluation.p2_contracts import (  # noqa: E402
    CHAT_COMPLETION_TOKENS_CAP,
    CHAT_HOST,
    CHAT_INPUT_PRICE_FLOOR,
    CHAT_MODEL,
    CHAT_OUTPUT_PRICE_FLOOR,
    CHAT_PRICING_SOURCE,
    CHAT_PROVIDER,
    CHAT_PROMPT_TOKENS_CAP,
    CHAT_REGION,
    EMBEDDING_MODEL,
    EMBEDDING_PRICING_SOURCE,
    EMBEDDING_PROVIDER,
    EMBEDDING_TOTAL_TOKENS_CAP,
    EMBEDDING_UNIT_PRICE_FLOOR,
    OCR_HOST,
    OCR_PAGES_PER_REQUEST,
    OCR_PRICING_SOURCE,
    OCR_PROVIDER,
    OCR_REGION,
    OCR_TABLE_MODEL,
    OCR_TABLE_PRICE_CNY,
    OCR_TEXT_MODEL,
    OCR_TEXT_PRICE_CNY,
    RERANK_MODEL,
    RERANK_PRICING_SOURCE,
    RERANK_PROVIDER,
    RERANK_TOTAL_TOKENS_CAP,
    RERANK_UNIT_PRICE_FLOOR,
    P2RunPlan,
)

# ---------------------------------------------------------------- 冻结的现场常量
PLAN_ID = "P2-T207-MATRIX-20261111"
PLAN_VERSION = "v0.1"
CREATED_UTC = "2026-11-11T08:30:00+08:00"
PROJECT_TOTAL_LIMIT_CNY = 40.0
STAGE_LIMIT_CNY = 20.0
#: 阶段内四中心重排（OCR 6.15 > 原 6.0 的证明见 PM/T207-cost-and-quota.md §3）。
COST_CENTERS_CNY = {"answer_retrieval": 8.5, "ocr": 6.5, "judge": 3.0, "independent": 2.0}
MAX_REQUESTS = 1000           # 当前 HARD_MAX_REQUESTS 下的最大值（547 已用 + 本计划 254 = 801 ≤ 1000）
#: 提硬顶后（见 PM/T207-cost-and-quota.md §6）改这一处即可重发计划：MAX_REQUESTS = 1200。
MAX_REQUESTS_AFTER_CAP_RAISE = 1200
INGEST_BATCHES = 22           # fixtures 侧（11 批非 OCR + 11 批 OCR 文本上限），见 evidence/estimate-out.json
LEDGER_PREFIX_SHA = "f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014"
BUDGET_LEDGER_PATH = "docs\\evidence\\LOCAL-R1-20261101\\budget\\live-ledger.jsonl"

B0 = [f"Q{i:02d}" for i in range(1, 41)]
NEG = [f"N{i:02d}" for i in range(1, 9)]
BOUND = [f"C{i:02d}" for i in range(1, 7)]
UPDATE_SMOKE = ["U01"]        # 计划绑定的有限真实更新 smoke（未生效版不改答案）
MATRIX_CASES = B0 + NEG + BOUND + UPDATE_SMOKE

#: 每页 OCR 项（D07 8 页 / D08 2 页 / D09 1 图 / D10 1 图 = 12 页）。
OCR_PAGES = (
    [("D07", p, OCR_TEXT_MODEL, OCR_TEXT_PRICE_CNY) for p in range(1, 9)]
    + [("D08", p, OCR_TEXT_MODEL, OCR_TEXT_PRICE_CNY) for p in range(1, 3)]
    + [("D09", 1, OCR_TEXT_MODEL, OCR_TEXT_PRICE_CNY)]
    + [("D10", 1, OCR_TABLE_MODEL, OCR_TABLE_PRICE_CNY)]   # T204 实测判 table → 0.15
)


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


def ocr_profile(model: str, price: float) -> dict:
    return {
        "kind": "ocr", "model": model, "provider": OCR_PROVIDER, "host": OCR_HOST,
        "region": OCR_REGION, "pricing_source": OCR_PRICING_SOURCE,
        "price_cny_per_page": float(price), "pages_per_request": int(OCR_PAGES_PER_REQUEST),
    }


def item(item_id: str, operation: str, center: str, case_id: str, turn: int, page: int,
         requests: int, profile: dict, expected: float) -> dict:
    return {
        "item_id": item_id, "operation": operation, "cost_center": center,
        "case_id": case_id, "turn": turn, "page": page, "requests": requests,
        "price_profile": profile, "expected_success_cny": expected,
    }


def build_public_plan() -> dict:
    items = [item("ingest-index-embedding", "index_embedding", "answer_retrieval", "INGEST", 1, 0,
                  INGEST_BATCHES, embedding_profile(), 0.0003)]
    for case_id in MATRIX_CASES:
        items.append(item(f"embed-{case_id}-t1", "query_embedding", "answer_retrieval", case_id, 1, 0,
                          1, embedding_profile(), 0.0003))
        items.append(item(f"rerank-{case_id}-t1", "rerank", "answer_retrieval", case_id, 1, 0,
                          1, rerank_profile(), 0.001))
        items.append(item(f"expand-{case_id}-t1", "query_expansion", "answer_retrieval", case_id, 1, 0,
                          1, chat_profile(), 0.004))
        items.append(item(f"answer-{case_id}-t1", "answer", "answer_retrieval", case_id, 1, 0,
                          1, chat_profile(), 0.004))
    for doc, page, model, price in OCR_PAGES:
        items.append(item(f"ocr-{doc}-p{page}", "ocr", "ocr", doc, 1, page, 1,
                          ocr_profile(model, price), float(price)))
    return {
        "schema_version": "p2-run-plan/v0.1",
        "plan_id": PLAN_ID,
        "plan_version": PLAN_VERSION,
        "mode": "end_to_end",
        "stage": "P2-LIVE",
        "created_utc": CREATED_UTC,
        "project_total_limit_cny": PROJECT_TOTAL_LIMIT_CNY,
        "stage_limit_cny": STAGE_LIMIT_CNY,
        "max_requests": MAX_REQUESTS,
        "cost_centers_cny": dict(COST_CENTERS_CNY),
        "items": items,
    }


def build_go(plan: P2RunPlan, *, document_plan_sha: str, authorization_note: str,
             nonce: str, max_requests: int) -> dict:
    return {
        "document": "P2-LIVE-GO",
        "schema_version": "p2-live-go/v0.1",
        "stage": "P2-LIVE",
        "authorization": authorization_note,
        "issued_by": "PM-candidate",
        "nonce": nonce,
        "issued_utc": "2026-11-11T08:30:00+08:00",
        "expires_utc": "2026-11-24T08:30:00+08:00",
        "budget_ledger_path": BUDGET_LEDGER_PATH,
        "budget_ledger_sha256": LEDGER_PREFIX_SHA,
        "budget_total_limit_cny": PROJECT_TOTAL_LIMIT_CNY,
        "scope": {
            "plan_id": plan.plan_id,
            "plan_sha256": document_plan_sha,
            "operations": sorted(plan.operations),
            "cost_centers_cny": dict(COST_CENTERS_CNY),
            "stage_limits_cny": {"P2-LIVE": STAGE_LIMIT_CNY},
            "max_requests": int(max_requests),
            "max_request_cny": 0.5,
        },
    }


def h2_plan_template() -> dict:
    return {
        "document": "p2-h2-plan-template/v0.1",
        "NOT_A_P2RunPlan": True,
        "why": (
            "H2 逐题 case_id 只存在于封存密文里；计划项按 (operation, case_id, turn) 解析，"
            "因此 H2 计划必须在封存进程内由 load_p2_dataset(visibility=holdout) 的 36 个真实回合生成，"
            "再对生成物取 plan_sha256 交给 GO 绑定。本模板只冻结口径与规模，不含任何 case_id/题干。"
        ),
        "generator_contract": {
            "input": "P2Dataset(visibility='holdout')（30 题 / 36 回合；不落盘题干）",
            "output": "P2RunPlan（schema_version=p2-run-plan/v0.1，stage=P2-LIVE，mode=end_to_end）",
            "case_id_rule": "原始 case_id 只写进计划文件（封存目录内），仓库内任何文件都不得出现",
            "item_rule": "每个 (case_id, turn) 生成 4 项：query_embedding/rerank/query_expansion/answer，各 requests=1",
            "index_embedding_rule": "1 项，requests = 声明的 H2 语料包批数 B（上限见 cost-and-quota §5）",
            "ocr_rule": "语料包含 OCR 页时按页生成 ocr 项；不含则 GO 不授权 ocr 操作",
        },
        "scale": {
            "cases": 30,
            "total_turns": 36,
            "turn_derived_items": 36 * 4,
            "request_count_without_ingest": 36 * 4,
        },
        "cost_centers_cny": dict(COST_CENTERS_CNY),
        "stage_limit_cny": STAGE_LIMIT_CNY,
        "project_total_limit_cny": PROJECT_TOTAL_LIMIT_CNY,
        "max_requests": 1100,
        "forbidden": [
            "把本模板当成计划直接授权（没有 case_id/turn 项，runner 会在第一个 case 处 plan_item_missing 停）",
            "把封存 case_id、题干或标签写进仓库内任何文件/日志/报告",
        ],
    }


def main() -> None:
    plan_doc = build_public_plan()
    plan = P2RunPlan.from_dict(plan_doc)                     # 严格校验（当前代码可表达）
    PM.mkdir(parents=True, exist_ok=True)
    (PM / "T207-plan-v0_1.json").write_text(
        json.dumps(plan.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    go = build_go(
        plan,
        document_plan_sha=plan.plan_sha256,
        authorization_note=(
            "DRAFT CANDIDATE (PM-candidate) - NOT ISSUED / NOT USABLE / production_ready=false; "
            "the only usable GO is written by the manager to the fixed P2_GO_PATH"
        ),
        nonce="DRAFT-T207-public-candidate-nonce-NOT-A-REAL-NONCE",
        max_requests=MAX_REQUESTS,
    )
    (PM / "T207-GO.CANDIDATE-DRAFT.json").write_text(
        json.dumps(go, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    template = h2_plan_template()
    (PM / "T207-plan-h2-v0_1.template.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    go_h2 = build_go(
        plan,
        document_plan_sha="0" * 64,
        authorization_note=(
            "DRAFT CANDIDATE (PM-candidate) - NOT ISSUED / NOT USABLE / plan_sha256 待封存进程生成 "
            "H2 计划后再填（本文件绑定的是全零占位，授权链必然失败）；只作形状与上限的预审件"
        ),
        nonce="DRAFT-T207-h2-candidate-nonce-NOT-A-REAL-NONCE",
        max_requests=1100,
    )
    go_h2["scope"]["plan_id"] = "P2-T207-H2-20261111"
    go_h2["scope"]["operations"] = ["answer", "index_embedding", "query_embedding", "query_expansion", "rerank"]
    (PM / "T207-GO-h2.CANDIDATE-DRAFT.json").write_text(
        json.dumps(go_h2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "items": len(plan.items),
        "case_count": plan.case_count,
        "turn_count": plan.turn_count,
        "page_count": plan.page_count,
        "total_requests": plan.total_requests,
        "max_requests": plan.max_requests,
        "worst_case_cny": plan.worst_case_cny,
        "reserve_peak_cny": plan.reserve_peak_cny,
        "estimated_success_cny": plan.estimated_success_cny,
        "requests_by_operation": plan.requests_by_operation(),
        "center_needs_cny": dict(plan.center_needs_cny()),
        "center_limits_cny": dict(plan.cost_centers_cny),
        "go_plan_sha_bound": go["scope"]["plan_sha256"] == plan.plan_sha256,
        "go_max_requests": go["scope"]["max_requests"],
        "plan_sha_file_sha256": hashlib.sha256(
            (PM / "T207-plan-v0_1.json").read_bytes()).hexdigest(),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
