"""T207-FIX-CONFLICT 复现：C05/C06 用 R2/R3 同一灌库计划走产品路径（mock provider，零真实出站）。

两种模式：
- `live_like`：仿真 live 的**每轮只有 1 个 query_embedding 计划项**（T207 plan 的
  query_embedding=55 / answer=55）。第 2 次 query embedding 直接失败，等价于 live 门控
  拒绝；这是 C05/C06 真实失败时的运行条件。
- `ungated`：不限制 embedding（离线既有口径），用于证明冲突逻辑本身没问题。

用法：.venv/Scripts/python.exe docs/reports/OBS-EVAL/P2/T207-FIX-CONFLICT/evidence/repro_r2_r3.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
# --src 用于"修复前"对照：把同一脚本跑在 git HEAD 的产品源码上（不改工作区文件）。
_SRC = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--src=")), None)
sys.path.insert(0, str(Path(_SRC)) if _SRC else str(ROOT / "backend" / "src"))

from mktkb.evaluation.product_adapter import (  # noqa: E402
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    ProductEvalAdapter,
)
from mktkb.rag.providers import post_counters, reset_post_counters  # noqa: E402

FIX = ROOT / "fixtures" / "acceptance"
V03 = FIX / "variants" / "V03_物品位置表_历史V1.xlsx"
D01 = FIX / "normal" / "D01_物品位置表.xlsx"
V04 = FIX / "variants" / "V04_物品位置表_新版V3.xlsx"
V01 = FIX / "variants" / "V01_临时物料位置通知.pdf"
D02 = FIX / "normal" / "D02_合作店家信息.xlsx"
V02 = FIX / "variants" / "V02_店家联系方式变更通知.pdf"

R2_PLAN = P2IngestPlan(
    sources=(
        IngestSource(path=V03, name="D01_物品位置表.xlsx"),
        IngestSource(path=D01, document_ref="D01_物品位置表.xlsx"),
        IngestSource(path=V04, document_ref="D01_物品位置表.xlsx", publish=False),
        IngestSource(path=V01),
    ),
    label="T207-R2",
)
R3_PLAN = P2IngestPlan(
    sources=(IngestSource(path=D02), IngestSource(path=V02)),
    label="T207-R3",
)


class PerTurnQueryEmbeddingGate:
    """仿真 live 门控：每轮只允许一次 query embedding（计划项 query_embedding=1/turn）。"""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.budget = 1

    def begin_turn(self) -> None:
        self.budget = 1

    def embed(self, texts, *, purpose: str = "document"):
        if purpose == "query":
            if self.budget <= 0:
                raise RuntimeError("p2-live gate: 本轮 query_embedding 计划项已用尽")
            self.budget -= 1
        return self._inner.embed(texts, purpose=purpose)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# live 实跑里模型给出的记录型回答（T207 R2/R3 产物，answer-C05/C06-t1 原文）；
# 离线 mock 用它复现 live 的 answer 形态，避免把 mock 的默认措辞当成产品行为。
LIVE_ANSWERS = {
    "C05": "城东店的宣传海报的位置：B区1号货架第二层；门店：城东店；物品：宣传海报；别名：海报。",
    "C06": "城东店的电话：010-00000001；店家：城东店；联系人：模拟联系人·陈宁；"
    "地址：示例市示例路18号（模拟）；合作状态：合作中。",
}


async def run_case(case_id: str, plan: P2IngestPlan, question: str, mode: str, out_dir: Path) -> dict:
    reset_post_counters()
    chat = MockChatBackend(behaviors=(ChatBehavior(answer=LIVE_ANSWERS[case_id]),))
    adapter = ProductEvalAdapter(out_dir, chat=chat, dataset=None, ingest_plan=plan)
    try:
        receipts = await adapter.ingest()
        if mode == "live_like":
            adapter._qa.index().embedder = PerTurnQueryEmbeddingGate(adapter._qa.index().embedder)
        conversation = await adapter.open_conversation()
        gate = adapter._qa.index().embedder
        if mode == "live_like":
            gate.begin_turn()
        turn = await adapter.ask_turn(
            question,
            user_id="employee",
            conversation_id=conversation,
            client_request_id="c0ffee00-0000-4000-8000-000000000001",
        )
        return {
            "case": case_id,
            "mode": mode,
            "revision": adapter.product_revision(),
            "ingest_documents": len(receipts),
            "kind": turn.kind,
            "text": turn.text,
            "sources": [
                {
                    "document_name": item.get("document_name"),
                    "version_number": item.get("version_number"),
                }
                for item in turn.sources
            ],
            "trace_path": turn.trace_path,
            "model_calls": chat.call_count,
            "provider_posts": {kind: dict(values) for kind, values in post_counters().items()},
        }
    finally:
        await adapter.close()


async def main() -> int:
    cases = (
        ("C05", R2_PLAN, "城东店的宣传海报现在放在哪里？"),
        ("C06", R3_PLAN, "城东店的联系电话是什么？"),
    )
    results = []
    tmp = Path(tempfile.mkdtemp(prefix="t207-fix-conflict-"))
    for mode in ("live_like", "ungated"):
        for index, (case_id, plan, question) in enumerate(cases):
            out_dir = tmp / f"{mode}-{index}"
            results.append(await run_case(case_id, plan, question, mode, out_dir))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
