"""T207 A-R2 采集契约 v0.3 端到端：ask -> 观察/投影 -> 认证密文 -> 严格读回 -> 重算输入。

覆盖（合成/公共 fixtures，零真实外连）：
- 真实产品装配 + 合成 provider 的多轮 legacy / 枚举分页 / 拒答；
- 产品响应版本与分页、trace 白名单、候选/发送/引用分层全部落盘且读回逐值一致；
- 采集开启时**不再事后重放检索**；关闭采集时旧行为与业务结果逐值不变；
- 服务错误（合成 invalid_json）保留真实产品响应与使用层，不冒充空集；
- 公开摘要不含题面/答案/哨兵。
"""

from __future__ import annotations

import asyncio
import functools
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation.p2_evidence_capture import (  # noqa: E402
    BINDING_KEYS,
    EvidenceCaptureConfig,
)
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    EvidenceWriter,
    read_encrypted_evidence,
    validate_turn_evidence,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"
SENTINEL = "T207_CAPTURE_V03_SENTINEL_DO_NOT_EXPORT_5ecret"
ENUMERATION_QUESTION = "把城东店和城西店的宣传海报记录都列出来"
V03 = "p2-hard-evidence-capture/v0.3"


def asyncio_test(func):
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def _bindings(run_id: str) -> dict[str, str]:
    values = {key: "local_mock-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = run_id
    values["dataset_version"] = "contract-e2e-v1"
    return values


def _dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "contract-e2e-v1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "b" * 64,
            "case_count": 0,
        },
    )


def _writer(tmp_path: Path, bindings: dict[str, str]) -> EvidenceWriter:
    return EvidenceWriter(
        root_dir=tmp_path / "evidence",
        key=Fernet.generate_key(),
        bindings=bindings,
        run_name="e2e-v03",
    )


def _adapter(
    root: Path,
    *,
    writer: EvidenceWriter | None,
    bindings: dict[str, str],
    capture: bool = True,
    chat: MockChatBackend | None = None,
) -> ProductEvalAdapter:
    return ProductEvalAdapter(
        root,
        chat=chat or MockChatBackend(),
        dataset=_dataset(),
        ingest_plan=P2IngestPlan(
            sources=(IngestSource(D01), IngestSource(D04)), label="contract-e2e"
        ),
        evidence_capture=(
            EvidenceCaptureConfig(
                root_dir=root / "evidence",
                bindings=bindings,
                writer=writer,
                capture_schema_version=V03,
            )
            if capture
            else None
        ),
        turn_timeout_seconds=120.0,
        purge_traces_on_close=True,
    )


def _snapshot_layers(evidence: dict[str, Any]) -> dict[str, set[str]]:
    usage = evidence["runtime_snapshot"]["retrieval_use"]
    return {
        "candidate": {
            str(value)
            for row in usage["candidates"]
            for value in row["unit_ids"]
        },
        "model_evidence": {
            str(value)
            for row in usage["model_evidence"]
            for value in row["unit_ids"]
        },
        "direct_rag_fact": {
            str(row["source_unit_id"]) for row in usage["direct_rag_facts"]
        },
        "final_citation": {str(value) for value in usage["final_citations"]},
    }


@asyncio_test
async def test_capture_chain_roundtrip_and_public_boundary(tmp_path: Path) -> None:
    bindings = _bindings("e2e-chain")
    writer = _writer(tmp_path, bindings)
    adapter = _adapter(tmp_path / "run", writer=writer, bindings=bindings)
    questions = [
        "活动策划需要哪些步骤？",
        ENUMERATION_QUESTION,
        "火星店的宣传海报在哪里？" + SENTINEL,
        "那城西店呢？",
    ]
    turns = []
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        for question in questions:
            turns.append(
                await adapter.ask_turn(
                    question,
                    user_id="employee",
                    conversation_id=conversation,
                    client_request_id=str(uuid.uuid4()),
                )
            )
        session = adapter._evidence_session
        assert session is not None and session.blocked is False
        assert adapter.network_stats()["outbound_attempts"] == 0
    finally:
        await adapter.close()

    kinds = [turn.kind for turn in turns]
    assert "answer" in kinds
    assert any(kind in {"not_found", "clarification", "no_answer"} for kind in kinds), kinds

    records = [item for item in writer.written if item["kind"] == "turn"]
    assert len(records) == len(questions)
    pagination_seen = False
    for index, record in enumerate(records):
        evidence = read_encrypted_evidence(
            Path(record["path"]), key=writer.key, expected_bindings=writer.bindings
        )
        assert evidence["schema_version"] == V03
        assert evidence["completeness"]["status"] == "complete", evidence["completeness"]
        assert evidence["completeness"]["scoring_readiness"]["four_axis"] is True
        snapshot = evidence["runtime_snapshot"]
        binding = snapshot["binding"]
        assert binding["client_request_id"] == evidence["turn"]["client_request_id"]
        assert binding["conversation_id"] == evidence["turn"]["conversation_id"]
        assert binding["post_revision"] == evidence["turn"]["post_revision"]
        response = snapshot["product_response"]
        assert response["availability"] == "available"
        assert response["reason"] is None
        assert response["http_status"] == 200
        assert str(response["kind"]) == str(turns[index].kind)
        assert response["request_id"] == turns[index].request_id
        assert snapshot["trace"]["availability"] in {"available", "absent"}
        assert snapshot["retrieval_use"]["availability"] == "complete"
        plans = [
            event["payload"]
            for event in evidence["capture"]["events"]
            if event["kind"] == "plan_observed"
        ]
        marker = snapshot["retrieval_use"]["candidate_observation"]
        if plans and plans[0]["path"] == "rag":
            assert marker == {
                "availability": "not_observed",
                "reason": "candidate_layer_not_observed",
            }
        else:
            assert marker == {"availability": "observed", "reason": None}

        units = {str(row["unit_id"]): row for row in evidence["db_projection"]["units"]}
        for source in response["sources"]:
            unit = units.get(str(source["source_id"]))
            assert unit is not None
            assert int(source["version_number"]) == int(unit["version_number"])
        citations = _snapshot_layers(evidence)["final_citation"]
        assert citations <= {str(row["source_id"]) for row in response["sources"]}
        if response["pagination"] is not None:
            pagination_seen = True
            pagination = response["pagination"]
            assert pagination["page"] >= 1 and pagination["page_size"] >= 1
            assert pagination["total"] >= pagination["returned"] >= 0
            assert pagination["has_more"] is False
            assert pagination["next_page"] is None
        validate_turn_evidence(evidence, phase="any")
    assert pagination_seen, "枚举轮必须实际产生并保全分页"

    manifest = adapter.evidence_capture_manifest()
    assert manifest is not None
    manifest_path = Path(manifest["sealed"]["path"])
    token = manifest_path.read_bytes()
    for needle in (SENTINEL.encode("utf-8"), "活动策划需要哪些步骤".encode("utf-8")):
        assert needle not in token
    manifest_data = read_encrypted_evidence(
        manifest_path, key=writer.key, expected_bindings=writer.bindings
    )
    assert manifest_data["schema_version"] == V03
    assert manifest_data["summary"]["turn_count"] == len(questions)
    public_text = json.dumps(manifest_data["turns"], ensure_ascii=False)
    assert SENTINEL not in public_text
    assert "活动策划需要哪些步骤" not in public_text
    for row in manifest_data["turns"]:
        assert row["scoring_quality_rescore"] is True
        assert row["runtime_product_response_present"] is True


@asyncio_test
async def test_capture_mode_never_replays_retrieval(tmp_path: Path, monkeypatch) -> None:
    from mktkb.evaluation.product_adapter import ProductEvalAdapter as Adapter

    calls = {"count": 0}
    original = Adapter.retrieval_candidates

    def counting(self, *args, **kwargs):
        calls["count"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Adapter, "retrieval_candidates", counting)

    async def run(enabled: bool, tag: str) -> dict[str, Any]:
        bindings = _bindings("e2e-diff-" + tag)
        writer = _writer(tmp_path / tag, bindings) if enabled else None
        adapter = _adapter(
            tmp_path / tag / "run", writer=writer, bindings=bindings, capture=enabled
        )
        try:
            await adapter.start()
            await adapter.ingest()
            conversation = await adapter.open_conversation()
            turn = await adapter.ask_turn(
                ENUMERATION_QUESTION,
                user_id="employee",
                conversation_id=conversation,
                client_request_id=str(uuid.uuid4()),
            )
            session = adapter._evidence_session
            evidence = None if session is None else dict(session.turns[0])
        finally:
            await adapter.close()
        return {
            "turn": turn,
            "evidence": evidence,
            "calls": dict(calls),
            "network": adapter.network_stats()["outbound_attempts"],
        }

    before = dict(calls)
    on = await run(True, "on")
    on_calls = on["calls"]["count"] - before["count"]
    assert on_calls == 0, "采集启用时不得调用 retrieval_candidates 事后重放"
    assert on["turn"].kind == "answer"
    assert on["turn"].retrieved, "采集模式必须用实际观察候选/发送证据填 retrieved"
    evidence = on["evidence"]
    assert evidence is not None
    layers = _snapshot_layers(evidence)
    captured_ids = set().union(*layers.values())
    used_ids = {
        str(value)
        for item in evidence["db_projection"]["units"]
        for value in (item["unit_id"],)
    }
    assert {str(value) for item in on["turn"].retrieved for value in item["unit_ids"]} <= used_ids
    assert captured_ids

    off = await run(False, "off")
    off_calls = off["calls"]["count"] - before["count"] - on_calls
    assert off_calls == 1, "关闭采集必须保持旧的重放路径（逐值不变）"
    assert off["evidence"] is None
    assert off["network"] == 0 and on["network"] == 0
    # 两次运行是不同隔离实例，答案里的记录短 ID/来源 UUID 天然不同；
    # 逐值不变的对象是业务结局与调用次数，而不是随机 ID。
    assert on["turn"].kind == off["turn"].kind
    assert on["turn"].http_status == off["turn"].http_status
    assert len(on["turn"].source_ids) == len(off["turn"].source_ids)
    assert on["turn"].candidates == off["turn"].candidates


@asyncio_test
async def test_unparsable_product_response_is_incomplete(
    tmp_path: Path, monkeypatch
) -> None:
    """A-I G4：200 但响应体不可解析 → unavailable + incomplete，不得声明评分就绪。"""
    from mktkb.evaluation.product_adapter import ProductEvalAdapter as Adapter

    monkeypatch.setattr(Adapter, "_json_body_or_none", staticmethod(lambda response: None))
    bindings = _bindings("e2e-unparsable")
    writer = _writer(tmp_path, bindings)
    adapter = _adapter(tmp_path / "run", writer=writer, bindings=bindings)
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        with pytest.raises(Exception) as excinfo:
            await adapter.ask_turn(
                "活动策划需要哪些步骤？",
                user_id="employee",
                conversation_id=conversation,
                client_request_id=str(uuid.uuid4()),
            )
        assert "evidence_capture_incomplete" in str(excinfo.value)
        session = adapter._evidence_session
        assert session is not None and session.blocked is True
        record = session.turns[0]
        assert record["completeness"]["status"] == "incomplete"
        snapshot = record["runtime_snapshot"]
        assert snapshot["product_response"]["availability"] == "unavailable"
        assert snapshot["product_response"]["reason"] == "product_response_unparsable"
        assert record["completeness"]["scoring_readiness"]["four_axis"] is False
        assert record["completeness"]["scoring_readiness"]["quality_rescore"] is False
    finally:
        await adapter.close()


@asyncio_test
async def test_error_turn_preserves_actual_response_and_usage(tmp_path: Path) -> None:
    bindings = _bindings("e2e-error")
    writer = _writer(tmp_path, bindings)
    chat = MockChatBackend(behaviors=(ChatBehavior(kind="invalid_json"),))
    adapter = _adapter(tmp_path / "run", writer=writer, bindings=bindings, chat=chat)
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        turn = await adapter.ask_turn(
            "活动策划需要哪些步骤？",
            user_id="employee",
            conversation_id=conversation,
            client_request_id=str(uuid.uuid4()),
        )
        assert turn.kind == "service_error", turn.kind
        session = adapter._evidence_session
        assert session is not None and session.blocked is False
        record = session.turns[0]
        assert record["completeness"]["status"] == "complete"
        snapshot = record["runtime_snapshot"]
        assert snapshot["product_response"]["availability"] == "available"
        assert snapshot["product_response"]["kind"] == "service_error"
        assert snapshot["retrieval_use"]["availability"] == "complete"
        kinds = [event["kind"] for event in record["capture"]["events"]]
        assert "answer_result" in kinds
    finally:
        await adapter.close()
