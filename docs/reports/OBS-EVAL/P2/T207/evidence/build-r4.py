r"""P2-T207-R4PREP：R4 定点重测的**确定性构造**（零真实调用、零网络、零账本写入）。

三段（顺序固定，逐段可复跑；证据见 evidence/r4-*-out.txt）：

  --step inputs   写 cases/R4.jsonl（既有只读转换器，N08→C05→C06）与 PM/T207-ingest-plan-R4.json
  --step plan     读 evidence/r4-ingest-state.json 的 B（实测批数）→ 写 PM/T207-plan-R4-v0_1.json
  --step go       读上面的计划 → 写 PM/T207-GO-R4.CANDIDATE-DRAFT.json（DRAFT，不可用）

输入只读：fixtures/acceptance/questions.json（题集）、p2_contracts 的冻结价格常量。
不读 .env / H1 / H2，不改账本/预算/GO 固定路径，不 import 任何需要网络的东西。

用法（仓库根）：
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207/evidence/build-r4.py --step inputs
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207/evidence/r4-ingest-probe.py --out docs/.../evidence/r4-ingest-state.json
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207/evidence/build-r4.py --step plan
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207/evidence/build-r4.py --step go
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[6]                       # docs/reports/OBS-EVAL/P2/T207/evidence -> repo root
T207 = HERE.parents[1]                       # docs/reports/OBS-EVAL/P2/T207
PM = T207 / "PM"
CASES = T207 / "cases"
EVIDENCE = T207 / "evidence"
sys.path.insert(0, str(REPO / "backend" / "src"))

from mktkb.evaluation.dataset import write_cases  # noqa: E402
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
    RERANK_MODEL,
    RERANK_PRICING_SOURCE,
    RERANK_PROVIDER,
    RERANK_TOTAL_TOKENS_CAP,
    RERANK_UNIT_PRICE_FLOOR,
    P2RunPlan,
)
from mktkb.evaluation.p2_public_cases import load_acceptance_cases  # noqa: E402

# ---------------------------------------------------------------- 冻结的 R4 现场常量
PLAN_ID = "P2-T207-R4-20261111"
PLAN_VERSION = "v0.1"
CREATED_UTC = "2026-11-11T12:00:00+08:00"
GO_ISSUED_UTC = "2026-11-11T12:30:00+08:00"
GO_EXPIRES_UTC = "2026-11-24T12:30:00+08:00"      # 13 天（与 T207 候选 GO 同口径）
PROJECT_TOTAL_LIMIT_CNY = 40.0
STAGE_LIMIT_CNY = 20.0
#: 与 T207 计划/候选 GO 逐值相同（阶段内四中心，合计 = 阶段额度 20）。
COST_CENTERS_CNY = {"answer_retrieval": 8.5, "ocr": 6.5, "judge": 3.0, "independent": 2.0}
#: used 691 + 余量；每个 run 新开一扇门，口径为 plan.total_requests <= max_requests - 已用。
MAX_REQUESTS = 760
LEDGER_PREFIX_SHA = "f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014"
BUDGET_LEDGER_PATH = "docs\\evidence\\LOCAL-R1-20261101\\budget\\live-ledger.jsonl"
#: R4 的题集顺序固定：先负例再冲突（与 cases/R4.jsonl 逐行一致）。
CASE_IDS = ("N08", "C05", "C06")
INGEST_PLAN_NAME = "T207-ingest-plan-R4.json"
STATE_PATH = EVIDENCE / "r4-ingest-state.json"

#: 同一 KB 状态：版本槽三步（V03 建槽 → D01 当前版 → V04 未发布）+ V01 发布 + D02 → V02 发布。
#: **顺序即语义**，不得重排（重排会改变 active 版本与冲突来源）。
INGEST_SOURCES = (
    {"path": "fixtures/acceptance/variants/V03_物品位置表_历史V1.xlsx", "name": "D01_物品位置表.xlsx"},
    {"path": "fixtures/acceptance/normal/D01_物品位置表.xlsx", "document_ref": "D01_物品位置表.xlsx"},
    {"path": "fixtures/acceptance/variants/V04_物品位置表_新版V3.xlsx",
     "document_ref": "D01_物品位置表.xlsx", "publish": False},
    {"path": "fixtures/acceptance/variants/V01_临时物料位置通知.pdf"},
    {"path": "fixtures/acceptance/normal/D02_合作店家信息.xlsx"},
    {"path": "fixtures/acceptance/variants/V02_店家联系方式变更通知.pdf"},
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


def item(item_id: str, operation: str, center: str, case_id: str, turn: int, page: int,
         requests: int, profile: dict, expected: float) -> dict:
    return {
        "item_id": item_id, "operation": operation, "cost_center": center,
        "case_id": case_id, "turn": turn, "page": page, "requests": requests,
        "price_profile": profile, "expected_success_cny": expected,
    }


def ingest_plan_document() -> dict:
    return {
        "schema_version": "p2-ingest-plan/v0.1",
        "label": "T207-R4",
        "sources": [dict(source) for source in INGEST_SOURCES],
    }


def batches_from_state() -> int:
    if not STATE_PATH.is_file():
        raise SystemExit(
            "r4-ingest-state.json 不存在：先跑 evidence/r4-ingest-probe.py（B 必须实测，不估）"
        )
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    batches = int(state.get("batches_B") or 0)
    if batches <= 0:
        raise SystemExit("r4-ingest-state.json 的 batches_B 非法（必须 >=1）")
    return batches


def build_plan(ingest_batches: int) -> dict:
    items = [item("ingest-index-embedding", "index_embedding", "answer_retrieval", "INGEST", 1, 0,
                  int(ingest_batches), embedding_profile(), 0.0003)]
    for case_id in CASE_IDS:
        items.append(item(f"embed-{case_id}-t1", "query_embedding", "answer_retrieval", case_id, 1, 0,
                          1, embedding_profile(), 0.0003))
        items.append(item(f"rerank-{case_id}-t1", "rerank", "answer_retrieval", case_id, 1, 0,
                          1, rerank_profile(), 0.001))
        items.append(item(f"expand-{case_id}-t1", "query_expansion", "answer_retrieval", case_id, 1, 0,
                          1, chat_profile(), 0.004))
        items.append(item(f"answer-{case_id}-t1", "answer", "answer_retrieval", case_id, 1, 0,
                          1, chat_profile(), 0.004))
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


def build_go(plan: P2RunPlan, *, document_plan_sha: str) -> dict:
    return {
        "document": "P2-LIVE-GO",
        "schema_version": "p2-live-go/v0.1",
        "stage": "P2-LIVE",
        "authorization": (
            "DRAFT CANDIDATE (PM-candidate) - NOT ISSUED / NOT USABLE; 仅覆盖 P2-T207 定点重测 R4"
            "（N08/C05/C06）；前置未闭环见 T207/report.md §9，签发前需经理决策"
        ),
        "issued_by": "PM-candidate",
        "nonce": "DRAFT-T207-r4-candidate-nonce-NOT-A-REAL-NONCE",
        "issued_utc": GO_ISSUED_UTC,
        "expires_utc": GO_EXPIRES_UTC,
        "budget_ledger_path": BUDGET_LEDGER_PATH,
        "budget_ledger_sha256": LEDGER_PREFIX_SHA,
        "budget_total_limit_cny": PROJECT_TOTAL_LIMIT_CNY,
        "scope": {
            "plan_id": plan.plan_id,
            "plan_sha256": document_plan_sha,
            "operations": sorted(plan.operations),
            "cost_centers_cny": dict(COST_CENTERS_CNY),
            "stage_limits_cny": {"P2-LIVE": STAGE_LIMIT_CNY},
            "max_requests": MAX_REQUESTS,
            "max_request_cny": 0.5,
        },
    }


def step_inputs() -> dict:
    cases = load_acceptance_cases(ids=CASE_IDS)          # 既有只读转换器，字段逐项可回溯
    CASES.mkdir(parents=True, exist_ok=True)
    cases_path = CASES / "R4.jsonl"
    cases_sha = write_cases(cases_path, cases)
    plan_doc = ingest_plan_document()
    PM.mkdir(parents=True, exist_ok=True)
    ingest_path = PM / INGEST_PLAN_NAME
    ingest_path.write_text(json.dumps(plan_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "step": "inputs",
        "cases": {
            "path": str(cases_path.relative_to(REPO)),
            "sha256": cases_sha,
            "case_ids": [case.case_id for case in cases],
            "suites": [case.suite for case in cases],
            "label_version": cases[0].label_version,
            "expected_kind": [case.expected_kind for case in cases],
        },
        "ingest_plan": {
            "path": str(ingest_path.relative_to(REPO)),
            "sha256": hashlib.sha256(ingest_path.read_bytes()).hexdigest(),
            "sources": len(plan_doc["sources"]),
            "order": [
                {"path": Path(source["path"]).name, "name": source.get("name"),
                 "document_ref": source.get("document_ref"),
                 "publish": bool(source.get("publish", True))}
                for source in plan_doc["sources"]
            ],
        },
    }


def step_plan() -> dict:
    batches = batches_from_state()
    document = build_plan(batches)
    plan = P2RunPlan.from_dict(document)
    PM.mkdir(parents=True, exist_ok=True)
    path = PM / "T207-plan-R4-v0_1.json"
    path.write_text(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "step": "plan",
        "path": str(path.relative_to(REPO)),
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
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
    }


def step_go() -> dict:
    path = PM / "T207-plan-R4-v0_1.json"
    plan = P2RunPlan.from_dict(json.loads(path.read_text(encoding="utf-8")))
    go = build_go(plan, document_plan_sha=plan.plan_sha256)
    target = PM / "T207-GO-R4.CANDIDATE-DRAFT.json"
    target.write_text(json.dumps(go, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    from datetime import datetime

    issued = datetime.fromisoformat(go["issued_utc"])
    expires = datetime.fromisoformat(go["expires_utc"])
    return {
        "step": "go",
        "path": str(target.relative_to(REPO)),
        "file_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "document": go["document"],
        "draft_marked": "DRAFT" in go["authorization"],
        "plan_sha_bound": go["scope"]["plan_sha256"] == plan.plan_sha256,
        "ledger_sha_is_history_prefix": go["budget_ledger_sha256"] == LEDGER_PREFIX_SHA,
        "operations": go["scope"]["operations"],
        "max_requests": go["scope"]["max_requests"],
        "max_request_cny": go["scope"]["max_request_cny"],
        "centers": go["scope"]["cost_centers_cny"],
        "validity_days": (expires - issued).days,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="P2-T207 R4 的确定性构造（零真实调用）")
    parser.add_argument("--step", required=True, choices=("inputs", "plan", "go"))
    args = parser.parse_args(list(argv) if argv is not None else None)
    payload = {"inputs": step_inputs, "plan": step_plan, "go": step_go}[args.step]()
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
