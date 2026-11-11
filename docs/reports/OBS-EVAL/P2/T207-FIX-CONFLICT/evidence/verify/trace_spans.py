"""T207-FIX-CONFLICT 取证：N08/冲突轮的 Trace Span 契约（required_spans 是否满足）。

用法：.venv/Scripts/python.exe .../trace_spans.py [--src=...]
零真实出站（MockChatBackend）；只读 trace 记录与 spans 名称。
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
_SRC = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--src=")), None)
sys.path.insert(0, str(Path(_SRC)) if _SRC else str(ROOT / "backend" / "src"))

from mktkb.evaluation.product_adapter import (  # noqa: E402
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    ProductEvalAdapter,
)
from mktkb.observability.contracts import required_spans  # noqa: E402

FIX = ROOT / "fixtures" / "acceptance"
D01 = FIX / "normal" / "D01_物品位置表.xlsx"
V01 = FIX / "variants" / "V01_临时物料位置通知.pdf"


async def ask(question: str, plan: P2IngestPlan, work: Path, *, narrow: bool = False) -> dict:
    chat = MockChatBackend(behaviors=(ChatBehavior(answer="x"),))
    adapter = ProductEvalAdapter(work, chat=chat, dataset=None, ingest_plan=plan)
    try:
        await adapter.ingest()
        if narrow:
            from sqlalchemy import select

            from mktkb.documents.models import SourceUnit

            qa = adapter._qa
            original = qa.candidate_unit_ids_for_intent
            db = adapter._app.state.db.session()
            try:
                rows = {str(value) for value in db.scalars(select(SourceUnit.id).where(SourceUnit.kind == "table_row")).all()}
            finally:
                db.close()

            def wrapped(*, mode, terms=(), entity_filters=None):
                ids = original(mode=mode, terms=terms, entity_filters=entity_filters)
                return {str(item) for item in ids if str(item) in rows}

            qa.candidate_unit_ids_for_intent = wrapped
        conversation = await adapter.open_conversation()
        turn = await adapter.ask_turn(
            question,
            user_id="employee",
            conversation_id=conversation,
            client_request_id="c0ffee00-0000-4000-8000-000000000002",
        )
        spans = list(turn.trace_spans or ())
        reason = None
        try:
            record = adapter.trace_of(turn.trace_id)
            if record is not None:
                reason = getattr(record[0], "reason", None)
        except Exception:  # noqa: BLE001
            reason = None
        required = None
        if turn.trace_path and turn.trace_outcome:
            try:
                required = sorted(required_spans(turn.trace_path, turn.trace_outcome, reason=reason))
            except Exception as exc:  # noqa: BLE001
                required = [f"value_error:{exc!r}"]
        return {
            "question": question,
            "kind": turn.kind,
            "trace_path": turn.trace_path,
            "trace_outcome_kind": turn.trace_outcome,
            "trace_reason": reason,
            "spans": spans,
            "required_spans": required,
            "missing_spans": [name for name in (required or ()) if name not in spans],
            "model_calls": chat.call_count,
        }
    finally:
        await adapter.close()


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="t207v-span-"))
    v03 = FIX / "variants" / "V03_物品位置表_历史V1.xlsx"
    out = {
        "src": _SRC or str(ROOT / "backend" / "src"),
        "n08": await ask(
            "根据货架照片告诉我没有标记物品的位置",
            P2IngestPlan(sources=(IngestSource(path=D01), IngestSource(path=V01)), label="T207-SPAN"),
            tmp / "n08",
        ),
        "c05_narrow": await ask(
            "城东店的宣传海报现在放在哪里？",
            P2IngestPlan(
                sources=(
                    IngestSource(path=v03, name="D01_物品位置表.xlsx"),
                    IngestSource(path=D01, document_ref="D01_物品位置表.xlsx"),
                    IngestSource(path=V01),
                ),
                label="T207-SPAN-C05",
            ),
            tmp / "c05",
            narrow=True,
        ),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
