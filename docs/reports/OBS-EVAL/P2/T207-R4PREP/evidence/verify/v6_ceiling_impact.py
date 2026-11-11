"""P2-T207-R4PREP 独立验收 v6：F-1 的影响面（离线模拟"live 单请求上限拒绝 embedding"）。

做法：Mock 产品路径 + 把所有 embedding 调用（document/query）替换成抛
EmbeddingUnavailable("单次 embedding 预留超过单请求上限")（即 live 在
max_request_cny < 0.04096 时 provider 的真实行为），观察：
- 灌库是"失败"还是"降级"（qa/service.py:345-348 会捕获并标 degraded）；
- 三例还能不能产出 kind；索引/单元/chunk 是否缺失。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = next(p for p in HERE.parents if (p / "backend" / "src").is_dir())
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation.dataset import CaseSpec, validate_case  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    MockChatBackend,
    P2RunDataset,
    ProductEvalAdapter,
    ingest_plan_from_document,
)
from mktkb.rag.errors import EmbeddingUnavailable  # noqa: E402

T207 = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207"
INGEST = T207 / "PM" / "T207-ingest-plan-R4.json"
CASES = T207 / "cases" / "R4.jsonl"


class CeilingRefusingEmbedder:
    """如实模拟 live 的"单请求上限不够 ⇒ 不发 POST"分支。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.refused_document = 0
        self.refused_query = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def embed(self, texts, *, purpose="document"):
        if purpose == "document":
            self.refused_document += 1
        else:
            self.refused_query += 1
        raise EmbeddingUnavailable("单次 embedding 预留超过单请求上限")


async def main() -> dict:
    plan = ingest_plan_from_document(json.loads(INGEST.read_text(encoding="utf-8")))
    cases = [CaseSpec.from_dict(json.loads(line)) for line in
             CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    for case in cases:
        validate_case(case)
    tmp = Path(tempfile.mkdtemp(prefix="p2-r4prep-v6-"))
    dataset = P2RunDataset(
        visibility="public", cases=(),
        identity={"dataset_version": "p2-r4prep-v6", "label_version": "p2-r4prep-v6",
                  "suite": "p2-r4prep-v6", "manifest_sha256": "c" * 64, "case_count": 0},
    )
    adapter = ProductEvalAdapter(tmp / "run", chat=MockChatBackend(), dataset=dataset,
                                 ingest_plan=plan, trace_enabled=False)
    refusing = CeilingRefusingEmbedder(adapter._embedder)
    adapter._embedder = refusing
    try:
        await adapter.start()
        ingest_error = None
        receipts = []
        try:
            receipts = await adapter.ingest()
        except Exception as exc:  # noqa: BLE001 - 被测行为
            ingest_error = {"type": type(exc).__name__, "code": getattr(exc, "code", None),
                            "message": str(exc)[:160]}
        status = adapter.index_status()
        turns = []
        if ingest_error is None:
            for case in cases:
                conversation = await adapter.open_conversation()
                try:
                    turn = await adapter.ask_turn(
                        case.question, user_id="employee", conversation_id=conversation,
                        client_request_id=str(uuid.uuid4()))
                    turns.append({"case_id": case.case_id, "kind": turn.kind,
                                  "http_status": turn.http_status,
                                  "text": (turn.text or "")[:120],
                                  "sources": [s.get("document_name") for s in turn.sources]})
                except Exception as exc:  # noqa: BLE001
                    turns.append({"case_id": case.case_id, "error": type(exc).__name__,
                                  "code": getattr(exc, "code", None), "message": str(exc)[:160]})
        return {
            "scenario": "所有 embedding 调用都被单请求上限拒绝（模拟 live 的 max_request_cny=plan.reserve_peak=0.018688）",
            "ingest_raised": ingest_error,
            "ingest_receipts": [{"name": r.name, "published": bool(r.published),
                                 "publish_status": r.publish_status, "units": r.units} for r in receipts],
            "index_status": {k: v for k, v in status.items() if k not in ("db_path", "config")},
            "refused_embedding_calls": {"document": refusing.refused_document,
                                        "query": refusing.refused_query},
            "turns": turns,
            "conclusion": {
                "ingest_fails_hard": ingest_error is not None,
                "index_degraded": str(status.get("degraded")) != "[]" or bool(status.get("error_code")),
                "no_vectors_but_units": status.get("units") == 23 and status.get("chunks") == 15,
            },
        }
    finally:
        await adapter.close()


def _emit(payload) -> None:
    import sys as _sys
    from pathlib import Path as _Path

    text = json.dumps(payload, ensure_ascii=False, indent=1)
    out = _sys.argv[_sys.argv.index("--out") + 1] if "--out" in _sys.argv else None
    if out:
        _Path(out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    _emit(asyncio.run(main()))
