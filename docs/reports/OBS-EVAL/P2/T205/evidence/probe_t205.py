"""P2-T205 证据生成器：公开财务反例的复现 + 评测器判定（全 Mock，零真实调用）。

复跑方式（仓库根目录）：

    .venv/Scripts/python.exe -B docs/reports/OBS-EVAL/P2/T205/evidence/probe_t205.py

输出（stdout，可直接重定向为 02-reproduction.txt）：

- 每条公开财务问题的产品回答（kind/text/来源 locator）；
- p2_scoring 对同一条回答的判定（status + 失败 check）；
- 末尾的计数：出站 0、RAG 供应商 POST 0、真实请求 0。

只用公开语料 docs（E10 市场部KPI月报 / W03 审批办法 / E03 2026 Q4 价目表），
不读 .env、不读 H1/H2、不联网（MockTransport + 本机 ASGI）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_scoring import score_public_case  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)
from mktkb.rag.providers import post_counters, reset_post_counters  # noqa: E402

FIX = ROOT / "corpus" / "enterprise-20261101"
FILES = (
    FIX / "excel" / "E10_市场部KPI月报.xlsx",
    FIX / "word" / "W03_促销活动申请审批与结案流程管理办法.docx",
    FIX / "excel" / "E03_2026年Q4渠道价目表.xlsx",
)
DOCUMENTS = {
    "E10_市场部KPI月报.xlsx": "E10",
    "W03_促销活动申请审批与结案流程管理办法.docx": "W03",
    "E03_2026年Q4渠道价目表.xlsx": "E03",
}

CASES = (
    CaseSpec(
        case_id="F01",
        suite="b0",
        split="dev",
        stratum="exact",
        business_date="2026-10-28",
        question="陈列达标率的计算口径和年度目标是什么？",
        expected_kind="answer",
        expected_values=("90%",),
        expected_sources=({"doc_code": "E10", "locator": {"sheet": "KPI月报", "row": 103}},),
        # C2：与 test_p2_public_controls.KPI_TARGET_CASE 同一口径（含 90% 与 ×100%）。
        reference_answer=(
            "月份：2026-09；指标：陈列达标率；计算口径：检核合格门店数 ÷ 抽检门店数 ×100%；年度目标：90%"
        ),
        labeler="lead",
        label_version="public-financial-2026-11-10",
    ),
    CaseSpec(
        case_id="F02",
        suite="b0",
        split="dev",
        stratum="exact",
        business_date="2026-10-28",
        question="单场预算 8000 元的活动由谁审批？",
        expected_kind="answer",
        expected_values=("市场部经理",),
        expected_sources=({"doc_code": "W03", "locator": {"heading": "第三章 审批权限"}},),
        forbidden_values=("事业部总经理", "通路行销主管"),
        labeler="lead",
        label_version="public-financial-2026-11-10",
    ),
    CaseSpec(
        case_id="F03",
        suite="b0",
        split="dev",
        stratum="exact",
        business_date="2026-10-28",
        question="2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价是多少？",
        expected_kind="answer",
        expected_values=("2.99",),
        expected_sources=({"doc_code": "E03", "locator": {"sheet": "NKA卖场", "row": 7}},),
        forbidden_values=("2.5",),
        labeler="lead",
        label_version="public-financial-2026-11-10",
    ),
    CaseSpec(
        case_id="F04",
        suite="badcase",
        split="dev",
        stratum="negative",
        business_date="2026-10-28",
        question="2026年Q4渠道价目表中 咸味饼干 120g 的批发价是多少？",
        expected_kind="not_found",
        expected_values=(),
        expected_sources=(),
        labeler="lead",
        label_version="public-financial-2026-11-10",
    ),
    CaseSpec(
        case_id="F05",
        suite="b0",
        split="dev",
        stratum="text",
        business_date="2026-10-28",
        question="活动结束后几日内上交结案报告？",
        expected_kind="answer",
        expected_values=("6 个自然日",),
        expected_sources=({"doc_code": "W03", "locator": {"heading": "第五章 结案与稽核"}},),
        labeler="lead",
        label_version="public-financial-2026-11-10",
    ),
)

QUESTIONS = tuple(case.question for case in CASES)


def empty_dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "t205-probe-v1",
            "label_version": "public-financial-2026-11-10",
            "suite": "p2-holdout",
            "manifest_sha256": "e" * 64,
            "case_count": 0,
        },
    )


async def run() -> dict:
    reset_post_counters()
    chat = MockChatBackend()
    work = Path(tempfile.mkdtemp(prefix="t205-probe-"))
    adapter = ProductEvalAdapter(
        work / "app",
        chat=chat,
        dataset=empty_dataset(),
        ingest_plan=P2IngestPlan(
            sources=tuple(IngestSource(path=path) for path in FILES), label="t205-probe"
        ),
    )
    rows = []
    try:
        await adapter.start()
        receipts = await adapter.ingest()
        conversation_id = await adapter.open_conversation()
        for index, (case, question) in enumerate(zip(CASES, QUESTIONS), start=1):
            turn = await adapter.ask_turn(
                question,
                user_id="employee",
                conversation_id=conversation_id,
                client_request_id=f"00000000-0000-4000-8000-{300 + index:012d}",
            )
            scored = score_public_case(
                case,
                {
                    "case_id": case.case_id,
                    "suite": case.suite,
                    "stratum": case.stratum,
                    "conversation_id": conversation_id,
                    "status": "ok",
                    "error_code": None,
                    "planned_turns": 1,
                    "turns_executed": 1,
                    "turns": [
                        {"turn": 1, "status": "ok", "error_code": None,
                         "product": turn.as_dict(include_text=True)}
                    ],
                },
                document_codes=DOCUMENTS,
                allowed_doc_codes=set(DOCUMENTS.values()),
            )
            rows.append(
                {
                    "case_id": case.case_id,
                    "question": question,
                    "kind": turn.kind,
                    "text": turn.text,
                    "sources": [
                        {
                            "document_name": source.get("document_name"),
                            "status": source.get("status"),
                            "locator": {
                                key: value
                                for key, value in (source.get("locator") or {}).items()
                                if key in {"heading", "sheet", "row", "page"}
                            },
                        }
                        for source in turn.sources
                    ],
                    "verdict": scored.score.status,
                    "failed_checks": [
                        check["check_id"]
                        for check in scored.score.checks
                        if check["status"] == "fail"
                    ],
                }
            )
        counters = adapter.provider_calls()
    finally:
        await adapter.close()
    return {
        "ingest": [
            {
                "document": Path(receipt.name).name if getattr(receipt, "name", None) else receipt.document_id,
                "job_state": receipt.job_state,
                "publish_status": receipt.publish_status,
            }
            for receipt in receipts
        ],
        "rows": rows,
        "provider_calls": {
            "outbound_network": counters["outbound_network"],
            "chat_calls": counters["chat"]["calls"],
        },
        "rag_provider_attempts": int(
            sum(int(value) for value in (post_counters().get("attempts") or {}).values())
        ),
    }


def main() -> None:
    payload = asyncio.run(run())
    print(json.dumps(payload, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
