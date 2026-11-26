"""C1-P3 独立验收补充探针：用**公开语料** D01/D04 复核运行期 entity_key 形态。

只读公共 fixture（fixtures/acceptance），不读任何私有 H2 题面/标签/答案/密文。
目的：确认「有 id 表头的表格 → 运行期 item|id:* 键」不是我合成语料特有的形态。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = next(
    parent
    for parent in HERE.parents
    if (parent / "backend" / "src" / "mktkb").is_dir() and (parent / "docs").is_dir()
)
sys.path.insert(0, str(HERE))

import netguard_independent as guard  # noqa: E402

guard.install()

from cryptography.fernet import Fernet  # noqa: E402

from mktkb.evaluation.p2_evidence_capture import BINDING_KEYS, EvidenceCaptureConfig  # noqa: E402
from mktkb.evaluation.p2_evidence_io import EvidenceWriter, read_encrypted_evidence  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)

FIXTURES = REPO / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"
QUESTION = "把城东店和城西店的宣传海报记录都列出来"


def bindings() -> dict[str, str]:
    values = {key: "independent-public-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = "independent-public-fixtures"
    values["dataset_version"] = "independent-public-v1"
    return values


async def drive(adapter: ProductEvalAdapter) -> None:
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation(user_id="employee")
        await adapter.ask_turn(
            QUESTION,
            user_id="employee",
            conversation_id=conversation,
            client_request_id=str(uuid.uuid4()),
        )
    finally:
        await adapter.close()


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="c1p3-independent-public-"))
    binding_values = bindings()
    writer = EvidenceWriter(
        root_dir=temp / "evidence",
        key=Fernet.generate_key(),
        bindings=binding_values,
        run_name="independent-public",
    )
    adapter = ProductEvalAdapter(
        temp / "run",
        chat=MockChatBackend(),
        dataset=P2RunDataset(
            visibility="public",
            cases=(),
            identity={
                "dataset_version": "independent-public-v1",
                "label_version": "independent-v1",
                "suite": "p2-holdout",
                "manifest_sha256": "d" * 64,
                "case_count": 0,
            },
        ),
        ingest_plan=P2IngestPlan(sources=(IngestSource(D01), IngestSource(D04)), label="independent-public"),
        evidence_capture=EvidenceCaptureConfig(
            root_dir=temp / "evidence",
            bindings=binding_values,
            writer=writer,
            capture_schema_version="p2-hard-evidence-capture/v0.3",
        ),
        turn_timeout_seconds=120.0,
        purge_traces_on_close=True,
        rag_business_date="2026-09-02",
        manifest_business_date="2026-09-02",
    )
    asyncio.run(drive(adapter))
    records = [item for item in writer.written if item["kind"] == "turn"]
    evidence = [
        read_encrypted_evidence(Path(item["path"]), key=writer.key, expected_bindings=writer.bindings)
        for item in records
    ]
    units = [
        {
            "kind": unit.get("kind"),
            "document_name": unit.get("document_name"),
            "entity_type": unit.get("entity_type"),
            "entity_key": unit.get("entity_key"),
            "entity_filters": unit.get("entity_filters"),
        }
        for item in evidence
        for unit in item["db_projection"]["units"]
    ]
    result = {
        "probe": "public-fixture-entity-shape",
        "outbound_attempts": adapter.network_stats()["outbound_attempts"],
        "turns": len(evidence),
        "units": units,
        "id_style_runtime_keys": sorted({u["entity_key"] for u in units if isinstance(u.get("entity_key"), str) and "|id:" in u["entity_key"]}),
        "verdict": "OK" if units else "FAIL",
    }
    guard.assert_clean()
    result["netguard"] = guard.snapshot()["counts"]
    (HERE / "out" / "08b-public-fixture-entity-shape.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=1)[:2500])
    return 0 if units else 1


if __name__ == "__main__":
    raise SystemExit(main())
