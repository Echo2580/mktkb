"""P2-T207-R4PREP 独立验收 v3b：Mock 灌库终态 + B_r4 + R2/R3 方法学自证 + 三例 live 形状打分。

独立口径（不复用开发方 probe 的任何测量代码）：
- 每次 embed 的待嵌入文本数，取自**产品自己的**索引统计增量
  （RagIndex.embedding_stats: provider_calls / cache_misses / cache_hits），
  在 RagIndex._embed_chunks 这一层记录；批数 = sum(ceil(文本数 / embedding_batch_size))，
  embedding_batch_size 取产品 live 装配值 5（product_adapter.py:1088）。
- 终态直接用 SQLAlchemy 读隔离产品库（资料/版本/状态/激活/单元数），不读正文。
- 三例按 live 形状（每轮 1 次 query embedding）提问，用冻结评分器打分。
- 零真实调用：Mock 适配器（rag_provider_mode=offline、无传输层），前后核对 post_counters。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = next(p for p in HERE.parents if (p / "backend" / "src").is_dir())
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation.dataset import CaseSpec, validate_case  # noqa: E402
from mktkb.evaluation.p2_score_run import (  # noqa: E402
    load_document_codes,
    source_index_from_rows,
)
from mktkb.evaluation.p2_scoring import (  # noqa: E402
    EXECUTION_MODE_LOCAL_MOCK,
    score_public_case,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    MockChatBackend,
    P2RunDataset,
    ProductEvalAdapter,
    ingest_plan_from_document,
)
from mktkb.rag.index import RagIndex  # noqa: E402
from mktkb.rag.providers import post_counters  # noqa: E402

T207 = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207"
LEDGER = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
BATCH = 5
EMBED_LOG: list[dict] = []
_ORIG_EMBED_CHUNKS = RagIndex._embed_chunks


def _patched_embed_chunks(self, chunks):  # noqa: ANN001, ANN201
    before = dict(self.embedding_stats)
    result = _ORIG_EMBED_CHUNKS(self, chunks)
    after = dict(self.embedding_stats)
    EMBED_LOG.append({
        "candidate_chunks": len(chunks),
        "provider_calls": int(after.get("provider_calls", 0)) - int(before.get("provider_calls", 0)),
        "texts_embedded": int(after.get("cache_misses", 0)) - int(before.get("cache_misses", 0)),
        "cache_hits": int(after.get("cache_hits", 0)) - int(before.get("cache_hits", 0)),
    })
    return result


class PerTurnQueryGate:
    """live 形状：每轮只允许 1 次 query embedding（计划项 query_embedding=1/turn）。"""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.budget = 1
        self.refused = 0

    def begin_turn(self) -> None:
        self.budget = 1

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def embed(self, texts, *, purpose="document"):
        if purpose == "query":
            if self.budget <= 0:
                self.refused += 1
                raise RuntimeError("verifier gate: 本轮 query_embedding 已用尽")
            self.budget -= 1
        return self.inner.embed(texts, purpose=purpose)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def my_document_state(adapter: ProductEvalAdapter) -> list[dict]:
    from sqlalchemy import func, select

    from mktkb.documents.models import Document, DocumentVersion, SourceUnit

    db = adapter.app.state.db.session()
    try:
        rows = []
        for document in db.scalars(select(Document).order_by(Document.name)).all():
            versions = db.scalars(
                select(DocumentVersion)
                .where(DocumentVersion.document_id == document.id)
                .order_by(DocumentVersion.number)
            ).all()
            entries = []
            for version in versions:
                units = int(db.scalar(
                    select(func.count()).select_from(SourceUnit)
                    .where(SourceUnit.version_id == version.id)
                ) or 0)
                entries.append({
                    "number": int(version.number),
                    "state": str(version.state),
                    "sha256": str(version.sha256),
                    "active": version.id == document.active_version_id,
                    "published_at": None if getattr(version, "published_at", None) is None
                    else str(version.published_at),
                    "units": units,
                })
            rows.append({
                "name": str(document.name),
                "document_id": str(document.id),
                "latest": int(document.latest_version_number),
                "active_number": next((e["number"] for e in entries if e["active"]), None),
                "versions": entries,
            })
        return rows
    finally:
        db.close()


def build_adapter(tmp_root: Path, ingest_plan_path: Path) -> ProductEvalAdapter:
    payload = json.loads(ingest_plan_path.read_text(encoding="utf-8"))
    plan = ingest_plan_from_document(payload)
    dataset = P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "p2-r4prep-verify",
            "label_version": "p2-r4prep-verify",
            "suite": "p2-r4prep-verify",
            "manifest_sha256": "d" * 64,
            "case_count": 0,
        },
    )
    return ProductEvalAdapter(
        tmp_root,
        chat=MockChatBackend(),
        dataset=dataset,
        ingest_plan=plan,
        trace_enabled=False,
    )


async def measure_ingest(ingest_plan_path: Path) -> dict:
    """只量灌库：终态 + 每次 embed 的文本数 + 批数。"""
    EMBED_LOG.clear()
    tmp = Path(tempfile.mkdtemp(prefix="p2-r4prep-verify-b-"))
    adapter = build_adapter(tmp / "run", ingest_plan_path)
    try:
        await adapter.start()
        receipts = await adapter.ingest()
        adapter._qa.ensure_ready()
        calls = [entry for entry in EMBED_LOG if entry["provider_calls"]]
        texts = [entry["texts_embedded"] for entry in calls]
        return {
            "plan": str(ingest_plan_path.relative_to(ROOT)),
            "plan_sha256": sha256_of(ingest_plan_path),
            "sources": len(json.loads(ingest_plan_path.read_text(encoding="utf-8"))["sources"]),
            "receipts": [
                {"name": item.name, "published": bool(item.published), "units": item.units,
                 "publish_status": item.publish_status}
                for item in receipts
            ],
            "embedding_calls": calls,
            "texts_per_call": texts,
            "texts_total": sum(texts),
            "batches_B": sum(math.ceil(count / BATCH) for count in texts),
            "upper_bound_per_upload": sum(
                max(1, math.ceil((item.units or 0) / BATCH)) for item in receipts
            ),
            "documents": my_document_state(adapter),
            "product_revision": adapter.product_revision(),
            "index_status": {k: v for k, v in adapter.index_status().items()
                             if k not in ("db_path", "config")},
            "is_mock": adapter.is_mock,
        }
    finally:
        await adapter.close()


async def measure_cases(ingest_plan_path: Path) -> dict:
    """灌库 + 三例 live 形状提问 + 冻结评分器打分 + 原始 conflicts 负载。"""
    cases: list[CaseSpec] = []
    for line in (T207 / "cases" / "R4.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            case = CaseSpec.from_dict(json.loads(line))
            validate_case(case)
            cases.append(case)
    codes = load_document_codes(T207 / "cases" / "document-codes.json")
    EMBED_LOG.clear()
    tmp = Path(tempfile.mkdtemp(prefix="p2-r4prep-verify-c-"))
    adapter = build_adapter(tmp / "run", ingest_plan_path)
    try:
        await adapter.start()
        await adapter.ingest()
        adapter._qa.ensure_ready()
        gate = PerTurnQueryGate(adapter._qa.index().embedder)
        adapter._qa.index().embedder = gate
        turns, raw, rows = [], [], {}
        for case in cases:
            conversation = await adapter.open_conversation()
            gate.begin_turn()
            chat_before = len(adapter.chat.calls)
            turn = await adapter.ask_turn(
                case.question, user_id="employee", conversation_id=conversation,
                client_request_id=str(uuid.uuid4()),
            )
            product = turn.as_dict(include_text=True)
            rows[case.case_id] = {"case_id": case.case_id, "status": "ok",
                                  "planned_turns": 1,
                                  "turns": [{"turn": 1, "status": "ok", "product": product}]}
            turns.append({
                "case_id": case.case_id,
                "expected_kind": case.expected_kind,
                "kind": turn.kind,
                "text": turn.text,
                "http_status": turn.http_status,
                "candidates": turn.candidates,
                "sources": [{"document_name": item.get("document_name"),
                             "version_number": item.get("version_number"),
                             "document_code": codes.get(str(item.get("document_name") or ""))}
                            for item in turn.sources],
                "model_calls_this_turn": len(adapter.chat.calls) - chat_before,
                "query_embedding_refused": gate.refused,
                "expected_values_in_text": [
                    {"value": value, "present": value in (turn.text or "")}
                    for value in case.expected_values
                ],
            })
            session = adapter._session("employee")
            created = await session.client.post("/api/v1/conversations", json={},
                                                headers=session.write_headers)
            cid = created.json()["id"]
            response = await session.client.post(
                f"/api/v1/conversations/{cid}/messages",
                json={"client_request_id": str(uuid.uuid4()), "question": case.question},
                headers=session.write_headers,
            )
            payload = response.json()
            raw.append({
                "case_id": case.case_id,
                "http_status": int(response.status_code),
                "kind": payload.get("kind"),
                "text": payload.get("text"),
                "conflicts": payload.get("conflicts") or [],
                "source_documents": [item.get("document_name") for item in payload.get("sources") or ()],
            })
        source_index = source_index_from_rows(rows)
        scores = []
        for case in cases:
            scored = score_public_case(
                case, rows[case.case_id], document_codes=codes, source_index=source_index,
                execution_mode=EXECUTION_MODE_LOCAL_MOCK, real_calls=0,
            )
            scores.append({
                "case_id": case.case_id,
                "status": scored.score.status,
                "checks": {item["check_id"]: item["status"] for item in scored.score.checks},
            })
        return {
            "turns": turns,
            "raw_payloads": raw,
            "scoring": scores,
            "batches_B": sum(math.ceil(e["texts_embedded"] / BATCH)
                             for e in EMBED_LOG if e["provider_calls"]),
            "network": adapter.provider_calls().get("outbound_network"),
            "provider_calls": {k: v for k, v in adapter.provider_calls().items()
                               if k != "outbound_network"},
            "is_mock": adapter.is_mock,
        }
    finally:
        await adapter.close()


def ledger_ingest_reservations() -> dict:
    per_run: dict[str, int] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") != "reserved":
            continue
        if str((event.get("metadata") or {}).get("item_id") or "") != "ingest-index-embedding":
            continue
        run_id = str(event.get("run_id") or "(null)")
        per_run[run_id] = per_run.get(run_id, 0) + 1
    return per_run


async def main() -> dict:
    RagIndex._embed_chunks = _patched_embed_chunks
    before_posts = dict(post_counters()["attempts"])
    r4 = await measure_ingest(T207 / "PM" / "T207-ingest-plan-R4.json")
    r2 = await measure_ingest(T207 / "PM" / "T207-ingest-plan-R2.json")
    r3 = await measure_ingest(T207 / "PM" / "T207-ingest-plan-R3.json")
    cases = await measure_cases(T207 / "PM" / "T207-ingest-plan-R4.json")
    after_posts = dict(post_counters()["attempts"])
    ledger = ledger_ingest_reservations()

    checks = {
        "r4_batches_is_6": r4["batches_B"] == 6,
        "r4_texts_per_call_pattern": r4["texts_per_call"] == [9, 1, 1, 4, 1],
        "r4_upper_bound_is_9": r4["upper_bound_per_upload"] == 9,
        "r4_four_documents": len(r4["documents"]) == 4,
        "r4_revision_5": r4["product_revision"] == 5,
        "r4_index_four_docs_23_units_15_chunks": (
            r4["index_status"].get("documents") == 4
            and r4["index_status"].get("units") == 23
            and r4["index_status"].get("chunks") == 15
        ),
        "r2_batches_is_4": r2["batches_B"] == 4,
        "r3_batches_is_2": r3["batches_B"] == 2,
        "method_matches_live_ledger": all(
            ledger.get(f"p2-t207-{name}-20261111-01") == value
            for name, value in (("r2", r2["batches_B"]), ("r3", r3["batches_B"]))
        ),
        "cases_batches_same_as_ingest_run": cases["batches_B"] == r4["batches_B"],
        "zero_outbound_network": cases["network"] == 0,
        "zero_provider_posts_in_process": after_posts == before_posts,
        "mock_mode": r4["is_mock"] and cases["is_mock"],
    }
    return {
        "r4_ingest": r4,
        "r2_ingest": r2,
        "r3_ingest": r3,
        "r4_cases": cases,
        "ledger_ingest_reservations_by_run": ledger,
        "checks": checks,
        "all_hold": all(checks.values()),
    }


def _emit(payload) -> None:
    import sys
    from pathlib import Path

    text = json.dumps(payload, ensure_ascii=False, indent=1)
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    _emit(asyncio.run(main()))

