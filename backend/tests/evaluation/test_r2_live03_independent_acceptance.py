"""T-R2-LIVE-03 步骤1 独立验收席位：全新合成数据重跑「生产路径封存 -> SAFE 认证消费」。

与开发自测完全独立的合成资料（不同门店/物品/值/哨兵/run_id 前缀）。正例只走正式
产品问答入口：capture_scope -> finish_turn -> EvidenceWriter.write_turn ->
manifest/receipt -> 磁盘密文回读 -> repair1 SAFE 认证入口；不预设回合状态、不补写
磁盘字段、不喂低层 payload。负例覆盖坏密文/错 key/错 binding/缺失 binding/failed
sink/未封存/completeness 异常/回执错配。零真实模型与外部出站，仅临时合成 key。
"""

from __future__ import annotations

import asyncio
import copy
import functools
import hashlib
import importlib.util
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import openpyxl
import pytest
from cryptography.fernet import Fernet

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation.p2_evidence_capture import (  # noqa: E402
    BINDING_KEYS,
    EvidenceCaptureBlocked,
    EvidenceCaptureConfig,
    EvidenceCaptureIncomplete,
)
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    EvidenceWriter,
    read_encrypted_evidence,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
SAFE_TOOL = (
    ROOT
    / "docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117/evidence"
    / "11-observability/revision2/repair1/work/safe_plan_projection.py"
)
BUSINESS_DATE = "2026-11-20"
SENTINEL = "INDEP_R2LIVE03_CANARY_7e21d9"

ITEM_DOC = "独立验收物品台账.xlsx"
STORE_DOC = "独立验收店家名录.xlsx"
ITEM_HEADERS = ["门店", "物品", "标识", "位置", "数量"]
ITEM_ROWS = [
    ["虚构丙店", "虚构升降台", "IND-I01", "虚构丙区7号柜", "2"],
    ["虚构丙店", "虚构周转筐", "IND-I02", "虚构丙区8号柜", "5"],
    ["虚构丁店", "虚构平板车", "IND-I03", "虚构丁区5号柜", "7"],
]
STORE_HEADERS = ["标识", "店家", "联系人", "合作状态", "备注"]
STORE_ROWS = [
    ["IND-S02", "虚构丁店", "虚构联络人丁", "暂缓履约", SENTINEL],
    ["IND-S01", "虚构丙店", "虚构联络人丙", "正常履约", "虚构批注"],
]
QUESTION_ENUM = "虚构升降台的位置在哪里，合作状态分别是什么？"
QUESTION_NAMED = "虚构丙店的虚构升降台放在哪个位置，合作状态分别是什么？"
ITEM_LOCATION = "虚构丙区7号柜"
STORE_STATUS = "正常履约"


def _load_safe():
    spec = importlib.util.spec_from_file_location("r2live03_indep_safe_tool", SAFE_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def asyncio_test(func):
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def _bindings(run_id: str) -> dict[str, str]:
    values = {key: "local_mock-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = run_id
    values["dataset_version"] = "r2live03-indep-v1"
    return values


def _dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "r2live03-indep-v1",
            "label_version": "independent-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "d" * 64,
            "case_count": 0,
        },
    )


def _xlsx(path: Path, title: str, headers: list[str], rows: list[list[str]]) -> Path:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "台账"
    sheet.cell(row=1, column=1, value=title)
    for column, header in enumerate(headers, start=1):
        sheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            sheet.cell(row=4 + offset, column=column, value=value)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()
    return path


def _sources(tmp_path: Path) -> list[IngestSource]:
    return [
        IngestSource(_xlsx(tmp_path / ITEM_DOC, "独立验收物品台账", ITEM_HEADERS, ITEM_ROWS)),
        IngestSource(_xlsx(tmp_path / STORE_DOC, "独立验收店家名录", STORE_HEADERS, STORE_ROWS)),
    ]


def _writer(base: Path, bindings: dict[str, str]) -> EvidenceWriter:
    return EvidenceWriter(
        root_dir=base / "evidence",
        key=Fernet.generate_key(),
        bindings=bindings,
        run_name="r2live03-indep",
    )


def _adapter(
    base: Path,
    *,
    writer: EvidenceWriter | None,
    bindings: dict[str, str],
    chat: MockChatBackend | None = None,
    turn_timeout_seconds: float = 120.0,
) -> ProductEvalAdapter:
    config = (
        EvidenceCaptureConfig(root_dir=base / "evidence", bindings=bindings, writer=writer)
        if writer is not None
        else None
    )
    return ProductEvalAdapter(
        base / "run",
        chat=chat or MockChatBackend(),
        dataset=_dataset(),
        ingest_plan=P2IngestPlan(sources=tuple(_sources(base / "docs")), label="r2live03-indep"),
        evidence_capture=config,
        turn_timeout_seconds=turn_timeout_seconds,
        purge_traces_on_close=True,
        rag_business_date=BUSINESS_DATE,
        manifest_business_date=BUSINESS_DATE,
    )


def _turn_receipts(writer: EvidenceWriter) -> list[dict]:
    return [item for item in writer.written if item["kind"] == "turn"]


def _receipt_binding_errors(writer: EvidenceWriter, manifest: dict) -> list[str]:
    """独立实现的写后回执/manifest 与磁盘密文核对（缺失/错配必须可检出）。"""
    errors: list[str] = []
    receipts = {int(item["turn_index"]): item for item in _turn_receipts(writer)}
    summaries = {int(item["turn_index"]): item for item in manifest["turns"]}
    if set(receipts) != set(summaries):
        errors.append("receipt_turn_set_mismatch")
    for turn_index, receipt in receipts.items():
        path = Path(receipt["path"])
        if not path.exists():
            errors.append("receipt_file_missing")
            continue
        token = path.read_bytes()
        if hashlib.sha256(token).hexdigest() != receipt["sha256"]:
            errors.append("receipt_sha_mismatch")
        if len(token) != receipt["bytes"]:
            errors.append("receipt_bytes_mismatch")
        summary = summaries.get(turn_index)
        if summary is None or summary["capture_status"] != "sealed":
            errors.append("manifest_capture_status_not_sealed")
    sealed = manifest.get("sealed")
    if not isinstance(sealed, dict):
        errors.append("manifest_receipt_missing")
    else:
        sealed_path = Path(sealed["path"])
        if not sealed_path.exists():
            errors.append("manifest_receipt_file_missing")
        else:
            token = sealed_path.read_bytes()
            if hashlib.sha256(token).hexdigest() != sealed["sha256"]:
                errors.append("manifest_receipt_sha_mismatch")
            if "bytes" in sealed and len(token) != sealed["bytes"]:
                errors.append("manifest_receipt_bytes_mismatch")
    return errors


async def _run_turns(adapter: ProductEvalAdapter, questions: list[tuple[str, str | None]]) -> list:
    await adapter.start()
    await adapter.ingest()
    conversation = await adapter.open_conversation()
    turns = []
    for question, request_id in questions:
        turns.append(
            await adapter.ask_turn(
                question,
                user_id="employee",
                conversation_id=conversation,
                client_request_id=request_id or str(uuid.uuid4()),
            )
        )
    return turns


@asyncio_test
async def test_independent_production_seal_readback_and_safe(tmp_path: Path) -> None:
    safe = _load_safe()
    bindings = _bindings("r2live03-indep-production")
    writer = _writer(tmp_path, bindings)
    chat = MockChatBackend()
    adapter = _adapter(tmp_path, writer=writer, bindings=bindings, chat=chat)
    from mktkb.rag import retrieval as rag_retrieval

    original_join = rag_retrieval._store_join_chunks
    request_ids = [str(uuid.uuid4()) for _ in range(3)]
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        turn_enum = await adapter.ask_turn(
            QUESTION_ENUM, user_id="employee", conversation_id=conversation,
            client_request_id=request_ids[0],
        )
        turn_named = await adapter.ask_turn(
            QUESTION_NAMED, user_id="employee", conversation_id=conversation,
            client_request_id=request_ids[1],
        )
        # 同形变体：替换为裸二元组 -> 联结未发生（区别于联结后缺覆盖）。
        rag_retrieval._store_join_chunks = lambda session, plan: ("", [])
        try:
            turn_join_off = await adapter.ask_turn(
                QUESTION_ENUM, user_id="employee", conversation_id=conversation,
                client_request_id=request_ids[2],
            )
        finally:
            rag_retrieval._store_join_chunks = original_join
        turn_replay = await adapter.ask_turn(
            QUESTION_ENUM, user_id="employee", conversation_id=conversation,
            client_request_id=request_ids[0],
        )
        assert adapter.network_stats()["outbound_attempts"] == 0
        assert chat.call_count == 0
    finally:
        await adapter.close()

    assert turn_enum.kind == "answer" and ITEM_LOCATION in turn_enum.text and STORE_STATUS in turn_enum.text
    assert turn_named.kind == "answer" and STORE_STATUS in turn_named.text
    assert turn_join_off.kind == "answer" and ITEM_LOCATION in turn_join_off.text
    assert STORE_STATUS not in turn_join_off.text, "联结关闭变体必须缺店家级值"
    assert len(turn_join_off.source_ids) < len(turn_enum.source_ids)
    assert turn_replay.http_status == 200

    manifest = adapter.evidence_capture_manifest()
    assert manifest is not None and manifest["summary"]["turn_count"] == 4
    assert _receipt_binding_errors(writer, manifest) == []

    outputs = []
    statuses = []
    for receipt in _turn_receipts(writer):
        path = Path(receipt["path"])
        envelope = read_encrypted_evidence(path, key=writer.key, expected_bindings=writer.bindings)
        # 写前 envelope 契约：密文内不得有 sealed 回执键；sink 终态必须已封存。
        assert "sealed" not in envelope
        statuses.append(envelope["capture"]["status"])
        outputs.append(
            safe.project_authenticated_turn(path, writer.key, expected_bindings=writer.bindings)
        )
    assert statuses == ["sealed"] * 4, statuses

    enum_out, named_out, join_off_out, replay_out = outputs
    for out in (enum_out, named_out):
        assert out["status"] == "observed", out
        assert len(out["events"]) == 1, out
        event = out["events"][0]
        assert event["join"] == "joined", event
        assert event["roles"]["status"] == "observed", event
        assert set(event["roles"]["field_roles"]) == {"location", "status"}, event
        assert event["effective_mode"] == "record" and event["effective_enumerate"] is True
        assert event["candidate_count_status"] == "observed" and event["candidate_count"] > 0
        assert event["stores_status"] == "observed" and event["stores_count"] >= 0
        assert event["truncated_status"] == "observed" and event["page_has_more_status"] == "observed"
        assert len(out["prepared_plans"]) >= 1
        assert out["prepared_plans"][0]["status"] == "observed"
    assert join_off_out["status"] == "observed", join_off_out
    join_off_event = join_off_out["events"][0]
    assert join_off_event["join"] != "joined", join_off_event
    assert join_off_event["candidate_count_status"] == "observed" and join_off_event["candidate_count"] > 0
    assert replay_out["status"] == "incomplete", replay_out

    # 脱敏闭包：SAFE 输出与公开 manifest 摘要不含哨兵/题面/实体原文。
    serialized = json.dumps(outputs, ensure_ascii=False) + json.dumps(manifest["turns"], ensure_ascii=False)
    for needle in (
        SENTINEL, QUESTION_ENUM, QUESTION_NAMED, "虚构丙店", "虚构丁店", "虚构升降台",
        ITEM_LOCATION, STORE_STATUS, "IND-I01", "IND-S01", "虚构联络人丙",
    ):
        assert needle not in serialized, needle
    manifest_token = Path(manifest["sealed"]["path"]).read_bytes()
    assert SENTINEL.encode("utf-8") not in manifest_token

    # 诊断留痕（供验收回报记录 not_captured/unknown/实测值）。
    diag = {
        "turn_statuses": statuses,
        "enum": enum_out["events"][0],
        "join_off_join": join_off_event["join"],
        "join_off_candidate_count": join_off_event["candidate_count"],
        "replay_status": replay_out["status"],
        "outbound_attempts": adapter.network_stats()["outbound_attempts"],
        "mock_call_count": chat.call_count,
    }
    print("INDEP_ACCEPTANCE_DIAG " + json.dumps(diag, ensure_ascii=False, sort_keys=True))


@asyncio_test
async def test_independent_capture_toggle_does_not_change_business_output(tmp_path: Path) -> None:
    def normalize(turn) -> tuple:
        # 记录短码/来源 id 是逐库随机身份，不属于业务输出；其余逐字比较。
        text = re.sub(r"记录 [0-9a-f]{8}", "记录 <id>", turn.text)
        return (turn.kind, text, len(turn.source_ids), turn.http_status)

    results = {}
    for enabled in (False, True):
        tag = "on" if enabled else "off"
        bindings = _bindings("r2live03-indep-toggle-" + tag)
        base = tmp_path / tag
        writer = _writer(base, bindings) if enabled else None
        chat = MockChatBackend()
        adapter = _adapter(base, writer=writer, bindings=bindings, chat=chat)
        try:
            turns = await _run_turns(adapter, [(QUESTION_ENUM, None), (QUESTION_NAMED, None)])
            results[tag] = [normalize(turn) for turn in turns]
            assert chat.call_count == 0
            assert adapter.network_stats()["outbound_attempts"] == 0
        finally:
            await adapter.close()
    assert results["on"] == results["off"]


@asyncio_test
async def test_independent_failed_sink_is_written_and_rejected(tmp_path: Path, monkeypatch) -> None:
    safe = _load_safe()
    bindings = _bindings("r2live03-indep-failed-sink")
    writer = _writer(tmp_path, bindings)
    adapter = _adapter(tmp_path, writer=writer, bindings=bindings)
    from mktkb.rag import answer as rag_answer

    original_emit = rag_answer.emit_capture_event

    def emit_with_unknown_kind(kind, /, **payload):
        sink = original_emit(kind, **payload)
        if sink is not None and kind == "retrieval_observed":
            from mktkb.observability import evaluation_capture as cap

            cap.emit_capture_event("r2live03_indep_unknown_kind")
        return sink

    monkeypatch.setattr(rag_answer, "emit_capture_event", emit_with_unknown_kind)
    with pytest.raises(EvidenceCaptureIncomplete):
        await _run_turns(adapter, [(QUESTION_ENUM, None)])
    try:
        with pytest.raises(EvidenceCaptureBlocked):
            await adapter.ask_turn(
                QUESTION_NAMED, user_id="employee", conversation_id="synthetic",
                client_request_id=str(uuid.uuid4()),
            )
    finally:
        await adapter.close()
    receipts = _turn_receipts(writer)
    assert len(receipts) == 1
    out = safe.project_authenticated_turn(Path(receipts[0]["path"]), writer.key, expected_bindings=writer.bindings)
    assert out["status"] == "sink_failed", out


@asyncio_test
async def test_independent_timeout_turn_is_incomplete_and_rejected(tmp_path: Path) -> None:
    safe = _load_safe()
    bindings = _bindings("r2live03-indep-timeout")
    writer = _writer(tmp_path, bindings)
    adapter = _adapter(tmp_path, writer=writer, bindings=bindings, turn_timeout_seconds=0.0001)
    with pytest.raises(EvidenceCaptureIncomplete):
        await _run_turns(adapter, [(QUESTION_ENUM, None)])
    await adapter.close()
    receipts = _turn_receipts(writer)
    assert len(receipts) == 1
    out = safe.project_authenticated_turn(Path(receipts[0]["path"]), writer.key, expected_bindings=writer.bindings)
    assert out["status"] == "incomplete", out


@asyncio_test
async def test_independent_safe_negative_gates_on_production_envelope(tmp_path: Path) -> None:
    safe = _load_safe()
    bindings = _bindings("r2live03-indep-negatives")
    writer = _writer(tmp_path, bindings)
    adapter = _adapter(tmp_path, writer=writer, bindings=bindings)
    try:
        await _run_turns(adapter, [(QUESTION_ENUM, None)])
    finally:
        await adapter.close()
    receipt = _turn_receipts(writer)[0]
    path = Path(receipt["path"])
    envelope = read_encrypted_evidence(path, key=writer.key, expected_bindings=writer.bindings)
    assert envelope["capture"]["status"] == "sealed"

    def write_raw(name: str, value: dict) -> Path:
        target = tmp_path / (name + ".fernet")
        target.write_bytes(Fernet(writer.key).encrypt(json.dumps(value, ensure_ascii=False).encode("utf-8")))
        return target

    def project(target: Path, *, key: bytes | None = None, expected: dict | None = None) -> dict:
        return safe.project_authenticated_turn(
            target, key or writer.key,
            expected_bindings=writer.bindings if expected is None else expected,
        )

    assert project(path)["status"] == "observed"
    # 坏密文：翻转中段一个字节。
    broken = tmp_path / "indep-corrupt.fernet"
    token = bytearray(path.read_bytes())
    token[len(token) // 2] ^= 1
    broken.write_bytes(token)
    assert project(broken)["status"] == "authentication_or_read_failed"
    # 错 key。
    assert project(path, key=Fernet.generate_key())["status"] == "authentication_or_read_failed"
    # 错 binding。
    wrong = dict(writer.bindings)
    wrong["run_id"] = "r2live03-indep-wrong-binding"
    assert project(path, expected=wrong)["status"] == "authentication_or_read_failed"
    # 缺失 binding。
    assert project(path, expected={})["status"] == "binding_unavailable"

    mutations = [
        ("failed", lambda v: v["capture"].update(status="failed"), "sink_failed"),
        ("unsealed", lambda v: v["capture"].update(status="active"), "sink_unsealed"),
        ("errors", lambda v: v["capture"].update(errors=[dict(code="indep-synthetic", stage="emit", request_id=None, detail="")]), "sink_failed"),
        ("incomplete", lambda v: v["completeness"].update(status="incomplete"), "incomplete"),
        ("replay", lambda v: v["completeness"].update(replay=True), "incomplete"),
        ("timeout", lambda v: v["turn"].update(timed_out=True), "incomplete"),
        ("missing_kinds", lambda v: v["completeness"].update(missing_event_kinds=["retrieval_observed"]), "incomplete"),
    ]
    for name, mutate, expected in mutations:
        value = copy.deepcopy(envelope)
        mutate(value)
        assert project(write_raw("indep-neg-" + name, value))["status"] == expected, name

    # 回执缺失/sha 错配、manifest 状态异常必须可检出。
    manifest = adapter.evidence_capture_manifest()
    assert _receipt_binding_errors(writer, manifest) == []
    bad_receipt = copy.deepcopy(receipt)
    bad_receipt["sha256"] = "0" * 64
    bad_writer = copy.copy(writer)
    bad_writer.written = [bad_receipt]
    assert "receipt_sha_mismatch" in _receipt_binding_errors(bad_writer, manifest)
    missing_writer = copy.copy(writer)
    missing_writer.written = [item for item in writer.written if item["kind"] != "turn"]
    assert "receipt_turn_set_mismatch" in _receipt_binding_errors(missing_writer, manifest)
    bad_manifest = copy.deepcopy(manifest)
    bad_manifest["turns"][0]["capture_status"] = "active"
    assert "manifest_capture_status_not_sealed" in _receipt_binding_errors(writer, bad_manifest)
    no_receipt_manifest = copy.deepcopy(manifest)
    del no_receipt_manifest["sealed"]
    assert "manifest_receipt_missing" in _receipt_binding_errors(writer, no_receipt_manifest)