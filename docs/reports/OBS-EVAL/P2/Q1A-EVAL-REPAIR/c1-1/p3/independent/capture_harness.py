"""C1-P3 独立验收：合成租户 + 合成文档的冻结 v0.3 回合证据采集驱动。

与开发测试相互独立：
- 语料是本目录 ``synth_corpus.py`` 现造的 xlsx/docx；
- 账号/租户由 adapter 在临时目录新建；
- 只通过 adapter 的公开入口（start/ingest/open_conversation/ask_turn/close）驱动，
  不导入开发测试模块、不复用其 fixture。
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from mktkb.evaluation.p2_evidence_capture import BINDING_KEYS, EvidenceCaptureConfig
from mktkb.evaluation.p2_evidence_io import (
    EvidenceWriter,
    read_encrypted_evidence,
)
from mktkb.evaluation.product_adapter import (
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)

V03 = "p2-hard-evidence-capture/v0.3"
#: 合成业务日期（不是任何冻结用例基线）。
BUSINESS_DATE = "2026-09-01"
QUESTION_FLOW = "独立验收入库流程一共分哪几步？"
QUESTION_STOCK = "独立验收仓储里折叠桌的数量是多少？"
QUESTION_LOOSE = "无编号台账里折叠凳在哪个门店？"
QUESTIONS = (QUESTION_FLOW, QUESTION_STOCK, QUESTION_LOOSE)
#: 合成租户（不含任何真实账号）；adapter 的 ingest 入口固定使用 admin 账号。
USER = "employee"


def bindings_for(run_id: str) -> dict[str, str]:
    values = {key: "independent-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = run_id
    values["dataset_version"] = "independent-synthetic-v1"
    return values


def dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "independent-synthetic-v1",
            "label_version": "independent-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "c" * 64,
            "case_count": 0,
        },
    )


async def _drive(adapter: ProductEvalAdapter, questions: list[str], user: str) -> None:
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation(user_id=user)
        for question in questions:
            await adapter.ask_turn(
                question,
                user_id=user,
                conversation_id=conversation,
                client_request_id=str(uuid.uuid4()),
            )
    finally:
        await adapter.close()


def capture(temp_root: Path, corpus: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    temp_root.mkdir(parents=True, exist_ok=True)
    bindings = bindings_for(run_id)
    writer = EvidenceWriter(
        root_dir=temp_root / "evidence",
        key=Fernet.generate_key(),
        bindings=bindings,
        run_name="independent-v03",
    )
    adapter = ProductEvalAdapter(
        temp_root / "run",
        chat=MockChatBackend(),
        dataset=dataset(),
        ingest_plan=P2IngestPlan(
            sources=(
                IngestSource(corpus["stock"]),
                IngestSource(corpus["loose"]),
                IngestSource(corpus["flow"]),
            ),
            label="independent-synthetic",
        ),
        evidence_capture=EvidenceCaptureConfig(
            root_dir=temp_root / "evidence",
            bindings=bindings,
            writer=writer,
            capture_schema_version=V03,
        ),
        turn_timeout_seconds=120.0,
        purge_traces_on_close=True,
        rag_business_date=BUSINESS_DATE,
        manifest_business_date=BUSINESS_DATE,
    )
    asyncio.run(_drive(adapter, list(QUESTIONS), USER))
    outbound = adapter.network_stats()["outbound_attempts"]
    records = [item for item in writer.written if item["kind"] == "turn"]
    evidence = [
        read_encrypted_evidence(
            Path(item["path"]), key=writer.key, expected_bindings=writer.bindings
        )
        for item in records
    ]
    run_bindings = dict(evidence[0]["bindings"]) if evidence else {}
    return {
        "temp_root": temp_root,
        "evidence": evidence,
        "writer_key": writer.key,
        "bindings": run_bindings,
        "writer": writer,
        "outbound_attempts": outbound,
        "provider_calls": adapter.provider_calls(),
        "questions": [QUESTION_FLOW, QUESTION_STOCK],
        "corpus": corpus,
    }


def summary_of(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for index, item in enumerate(evidence):
        projection = item.get("db_projection") or {}
        units = projection.get("units") or []
        rows.append(
            {
                "turn_index": int((item.get("turn") or {}).get("turn_index", -1)),
                "schema_version": item.get("schema_version"),
                "unit_kinds": sorted({str(unit.get("kind")) for unit in units}),
                "unit_count": len(units),
                "documents": sorted(
                    {str(unit.get("document_name")) for unit in units if unit.get("document_name")}
                ),
                "entity_types": sorted(
                    {str(unit.get("entity_type")) for unit in units if unit.get("entity_type")}
                ),
                "locator_samples": [
                    {"kind": unit.get("kind"), "locator": unit.get("locator")}
                    for unit in units[:4]
                ],
                "event_kinds": sorted(
                    {str(event.get("kind")) for event in (item.get("capture") or {}).get("events") or ()}
                ),
                "plan_events": [
                    dict(event.get("payload") or {})
                    for event in (item.get("capture") or {}).get("events") or ()
                    if str(event.get("kind")) == "plan_observed"
                ],
                "rag_business_date": projection.get("rag_business_date"),
                "retrieval_availability": (item.get("runtime_snapshot") or {}).get(
                    "retrieval_use", {}
                ).get("availability"),
                "question": rows_question(item),
                "index": index,
            }
        )
    return rows


def rows_question(item: dict[str, Any]) -> str:
    return str((item.get("turn") or {}).get("question_sha256") or "")[:8]
