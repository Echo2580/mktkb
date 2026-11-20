"""T207 A-R2 采集契约 v0.3：当次运行快照（产品响应切片 / trace / 检索使用）红绿测试。

本文件先红后绿：``test_runtime_snapshot_preserves_returned_versions_and_pagination``
在实现前必须失败（旧 envelope 没有 runtime_snapshot，产品返回版本/分页/轨迹未保全）。
全部数据为公共 fixtures 与合成 provider，零真实外连。
"""

from __future__ import annotations

import asyncio
import copy
import functools
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
    EvidenceCaptureIncomplete,
    evaluate_completeness,
)
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    EvidenceIntegrityError,
    EvidenceWriter,
    read_encrypted_evidence,
    validate_turn_evidence,
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
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
ENUMERATION_QUESTION = "把城东店和城西店的宣传海报记录都列出来"


def asyncio_test(func):
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def _bindings(run_id: str) -> dict[str, str]:
    values = {key: "local_mock-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = run_id
    values["dataset_version"] = "contract-dataset-v1"
    return values


def _dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "contract-dataset-v1",
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
        run_name="contract-run",
    )


def _adapter(
    root: Path, *, writer: EvidenceWriter, bindings: dict[str, str]
) -> ProductEvalAdapter:
    return ProductEvalAdapter(
        root,
        chat=MockChatBackend(),
        dataset=_dataset(),
        ingest_plan=P2IngestPlan(sources=(IngestSource(D01),), label="contract"),
        evidence_capture=EvidenceCaptureConfig(
            root_dir=root / "evidence",
            bindings=bindings,
            writer=writer,
            capture_schema_version="p2-hard-evidence-capture/v0.3",
        ),
        turn_timeout_seconds=120.0,
        purge_traces_on_close=True,
    )


@asyncio_test
async def test_runtime_snapshot_preserves_returned_versions_and_pagination(
    tmp_path: Path,
) -> None:
    """RED：产品响应已有 sources[].version_number 与 pagination，旧 envelope 全程丢弃。"""
    bindings = _bindings("contract-run-1")
    writer = _writer(tmp_path, bindings)
    adapter = _adapter(tmp_path / "run", writer=writer, bindings=bindings)
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
        status, messages = await adapter.list_messages(conversation)
        assistant = [
            item for item in messages.get("items", []) if item.get("role") == "assistant"
        ][-1]
        product_pagination = assistant.get("pagination")
        assert turn.kind == "answer", turn.kind
        assert status == 200
        assert product_pagination is not None, "本合成样例必须真实产生分页"
        assert product_pagination["total"] == 2
        product_versions = {
            str(item["source_id"]): int(item["version_number"]) for item in turn.sources
        }
        assert product_versions, "本合成样例必须返回结构化来源版本"
        session = adapter._evidence_session
        assert session is not None and session.blocked is False
    finally:
        await adapter.close()

    turn_records = [item for item in writer.written if item["kind"] == "turn"]
    assert len(turn_records) == 1
    envelope = read_encrypted_evidence(
        Path(turn_records[0]["path"]), key=writer.key, expected_bindings=writer.bindings
    )
    assert "runtime_snapshot" in envelope
    snapshot = envelope["runtime_snapshot"]
    assert snapshot["schema_version"] == "p2-runtime-snapshot/v0.1"
    response = snapshot["product_response"]
    assert response["availability"] == "available"
    assert response["pagination"] == product_pagination
    captured_versions = {
        str(item["source_id"]): int(item["version_number"]) for item in response["sources"]
    }
    assert captured_versions == product_versions
    assert snapshot["trace"]["availability"] in {"available", "absent"}
    assert snapshot["retrieval_use"]["availability"] == "complete"
    assert envelope["completeness"]["status"] == "complete"
    assert envelope["completeness"]["scoring_readiness"]["four_axis"] is True


# --------------------------------------------------------------------------- #
# A8：严格读写、旧版本兼容、坏字段/乱序/坏类型/null 与 [] 区分
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def captured(tmp_path_factory) -> dict[str, Any]:
    base = tmp_path_factory.mktemp("contract-module")
    bindings = _bindings("contract-module-run")
    writer = _writer(base, bindings)
    adapter = _adapter(base / "run", writer=writer, bindings=bindings)

    async def _run() -> dict[str, Any]:
        try:
            await adapter.start()
            await adapter.ingest()
            conversation = await adapter.open_conversation()
            await adapter.ask_turn(
                ENUMERATION_QUESTION,
                user_id="employee",
                conversation_id=conversation,
                client_request_id=str(uuid.uuid4()),
            )
            session = adapter._evidence_session
            assert session is not None and session.blocked is False
            return copy.deepcopy(session.turns[0])
        finally:
            await adapter.close()

    return {"evidence": asyncio.run(_run()), "bindings": bindings, "key": writer.key}


def test_strict_reader_rejects_missing_and_tampered_snapshot(captured: dict[str, Any]) -> None:
    base = captured["evidence"]
    assert base["schema_version"] == "p2-hard-evidence-capture/v0.3"
    assert validate_turn_evidence(copy.deepcopy(base))["runtime_snapshot"]["schema_version"] == (
        "p2-runtime-snapshot/v0.1"
    )

    missing = copy.deepcopy(base)
    missing.pop("runtime_snapshot")
    with pytest.raises(EvidenceIntegrityError, match="runtime_snapshot"):
        validate_turn_evidence(missing)

    extra = copy.deepcopy(base)
    extra["runtime_snapshot"]["unexpected"] = "x"
    with pytest.raises(EvidenceIntegrityError, match="unknown_keys"):
        validate_turn_evidence(extra)

    bad_reason = copy.deepcopy(base)
    bad_reason["runtime_snapshot"]["product_response"]["reason"] = "why"
    with pytest.raises(EvidenceIntegrityError, match="reason"):
        validate_turn_evidence(bad_reason)

    null_sources = copy.deepcopy(base)
    null_sources["runtime_snapshot"]["product_response"]["sources"] = None
    with pytest.raises(EvidenceIntegrityError):
        validate_turn_evidence(null_sources)

    bool_count = copy.deepcopy(base)
    bool_count["runtime_snapshot"]["product_response"]["sources"][0]["version_number"] = True
    with pytest.raises(EvidenceIntegrityError, match="must_be_int"):
        validate_turn_evidence(bool_count)

    bad_pagination = copy.deepcopy(base)
    bad_pagination["runtime_snapshot"]["product_response"]["pagination"]["has_more"] = True
    bad_pagination["runtime_snapshot"]["product_response"]["pagination"]["next_page"] = None
    with pytest.raises(EvidenceIntegrityError, match="pagination"):
        validate_turn_evidence(bad_pagination)

    bad_capture_seq = copy.deepcopy(base)
    bad_capture_seq["capture"]["events"][1]["seq"] = 99
    with pytest.raises(EvidenceIntegrityError, match="seq"):
        validate_turn_evidence(bad_capture_seq)

    cross_run = copy.deepcopy(base)
    cross_run["bindings"]["run_id"] = "other-run"
    with pytest.raises(EvidenceIntegrityError, match="cross_binding_mismatch"):
        validate_turn_evidence(cross_run, expected_bindings=captured["bindings"])

    # 旧版本不能被“放宽”接收新键：把 v0.3 直接改标 v0.1 必须拒绝。
    relabel = copy.deepcopy(base)
    relabel["schema_version"] = "p2-hard-evidence-capture/v0.1"
    with pytest.raises(EvidenceIntegrityError):
        validate_turn_evidence(relabel)


def test_legacy_v01_envelope_still_reads(captured: dict[str, Any]) -> None:
    legacy = copy.deepcopy(captured["evidence"])
    legacy["schema_version"] = "p2-hard-evidence-capture/v0.1"
    legacy.pop("runtime_snapshot")
    legacy["completeness"].pop("scoring_readiness")
    validated = validate_turn_evidence(legacy)
    assert validated["schema_version"] == "p2-hard-evidence-capture/v0.1"
    assert "runtime_snapshot" not in validated


def _completeness(evidence: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    turn = evidence["turn"]
    capture = evidence["capture"]
    return evaluate_completeness(
        events=capture["events"],
        projection=evidence["db_projection"],
        timed_out=bool(turn["timed_out"]),
        capture_status=str(capture["status"]),
        capture_errors=list(capture["errors"]),
        post_revision=turn["post_revision"],
        authenticated_user_id=turn["authenticated_user_id"],
        http_status=turn["http_status"],
        runtime_snapshot=snapshot,
        turn_identity={
            "client_request_id": turn["client_request_id"],
            "conversation_id": turn["conversation_id"],
            "pre_revision": turn["pre_revision"],
        },
    )


def test_gap_rework_identity_unparsable_pagination_and_candidate_marker(
    captured: dict[str, Any], tmp_path: Path
) -> None:
    """A-I G1/G2/G4/R4 回归：缺失身份、不可解析响应、分页矛盾、候选观察标记。"""
    from mktkb.evaluation.p2_evidence_capture import _product_response_block

    evidence = captured["evidence"]
    base = copy.deepcopy(evidence["runtime_snapshot"])
    assert base["retrieval_use"]["candidate_observation"]["availability"] == "not_observed"
    assert base["retrieval_use"]["candidate_observation"]["reason"] == (
        "candidate_layer_not_observed"
    )

    for field in ("request_id", "message_id", "kind", "revision"):
        tampered = copy.deepcopy(base)
        tampered["product_response"][field] = None
        result = _completeness(evidence, tampered)
        assert result["status"] == "incomplete", field
        assert "runtime_product_response_incomplete" in result["errors"], field
        assert result["scoring_readiness"]["four_axis"] is False
        assert result["scoring_readiness"]["quality_rescore"] is False

    pagination_drift = copy.deepcopy(base)
    pagination_drift["product_response"]["pagination"]["returned"] = (
        pagination_drift["product_response"]["pagination"]["total"] + 1
    )
    result = _completeness(evidence, pagination_drift)
    assert result["status"] == "incomplete"
    assert "runtime_pagination_invalid" in result["errors"]

    marker_drift = copy.deepcopy(base)
    marker_drift["retrieval_use"]["candidate_observation"] = {
        "availability": "observed",
        "reason": None,
    }
    result = _completeness(evidence, marker_drift)
    assert result["status"] == "incomplete"
    assert "runtime_candidate_observation_inconsistent" in result["errors"]

    unparsable = _product_response_block(None, http_status=200, timed_out=False)
    assert unparsable["availability"] == "unavailable"
    assert unparsable["reason"] == "product_response_unparsable"
    snapshot = copy.deepcopy(base)
    snapshot["product_response"] = unparsable
    result = _completeness(evidence, snapshot)
    assert result["status"] == "incomplete"
    assert "runtime_product_response_missing" in result["errors"]
    assert result["scoring_readiness"]["quality_rescore"] is False
    assert "product_response_unavailable" in result["scoring_readiness"]["reasons"]

    no_sources = dict(base["product_response"])
    no_sources.pop("sources")
    invalid = _product_response_block(no_sources, http_status=200, timed_out=False)
    assert invalid["availability"] == "unavailable"
    assert invalid["reason"] == "product_sources_invalid"
    null_sources = dict(base["product_response"])
    null_sources["sources"] = None
    invalid = _product_response_block(null_sources, http_status=200, timed_out=False)
    assert invalid["availability"] == "unavailable"
    assert invalid["reason"] == "product_sources_invalid"

    # R6：语义非法分页必须可在严格 writer 下落盘（记 unavailable 而不是被 schema 整条拒绝）。
    bad_page = dict(base["product_response"])
    bad_page["pagination"] = {
        "page": 0,
        "page_size": 10,
        "total": 2,
        "returned": 2,
        "has_more": False,
        "next_page": None,
    }
    invalid = _product_response_block(bad_page, http_status=200, timed_out=False)
    assert invalid["availability"] == "unavailable"
    assert invalid["reason"] == "runtime_pagination_invalid"
    snapshot = copy.deepcopy(base)
    snapshot["product_response"] = invalid
    result = _completeness(evidence, snapshot)
    assert result["status"] == "incomplete"
    assert "runtime_pagination_invalid" in result["errors"]
    assert result["scoring_readiness"]["quality_rescore"] is False

    writable = copy.deepcopy(evidence)
    writable["runtime_snapshot"] = snapshot
    writable["completeness"] = result
    writable.pop("sealed", None)
    writer = EvidenceWriter(
        root_dir=tmp_path / "rework-evidence",
        key=Fernet.generate_key(),
        bindings=dict(evidence["bindings"]),
        run_name="rework",
    )
    receipt = writer.write_turn(writable)
    readback = read_encrypted_evidence(
        Path(receipt["path"]), key=writer.key, expected_bindings=writer.bindings
    )
    assert readback["runtime_snapshot"]["product_response"]["reason"] == (
        "runtime_pagination_invalid"
    )
    assert readback["completeness"]["status"] == "incomplete"

    # 产品返回来源必须覆盖已提交引用；两份来源不能矛盾都算真。
    citation_mismatch = copy.deepcopy(base)
    citation_mismatch["product_response"]["sources"] = []
    result = _completeness(evidence, citation_mismatch)
    assert result["status"] == "incomplete"
    assert "runtime_product_response_inconsistent" in result["errors"]


def test_runtime_snapshot_semantics_catch_drift(captured: dict[str, Any]) -> None:
    evidence = captured["evidence"]
    base = copy.deepcopy(evidence["runtime_snapshot"])
    assert _completeness(evidence, copy.deepcopy(base))["status"] == "complete"

    version_drift = copy.deepcopy(base)
    version_drift["product_response"]["sources"][0]["version_number"] += 1
    result = _completeness(evidence, version_drift)
    assert result["status"] == "incomplete"
    assert "runtime_projection_version_mismatch" in result["errors"]

    # 反填反例：DB 已推进到“当前版本 2”，产品当次返回 1；快照保持 1 且被固定拒绝，
    # 绝不把 1 悄悄改写成 2（也不把 2 当成当次事实）。
    projection_drift = copy.deepcopy(evidence["db_projection"])
    projection_drift["units"][0]["version_number"] = 2
    projection_drift["units"][0]["active_version_id"] = str(uuid.uuid4())
    projection_drift["units"][0]["active"] = False
    projection_drift["units"][0]["version_state"] = "superseded"
    result = evaluate_completeness(
        events=evidence["capture"]["events"],
        projection=projection_drift,
        timed_out=False,
        capture_status=str(evidence["capture"]["status"]),
        capture_errors=list(evidence["capture"]["errors"]),
        post_revision=evidence["turn"]["post_revision"],
        authenticated_user_id=evidence["turn"]["authenticated_user_id"],
        http_status=evidence["turn"]["http_status"],
        runtime_snapshot=copy.deepcopy(base),
        turn_identity={
            "client_request_id": evidence["turn"]["client_request_id"],
            "conversation_id": evidence["turn"]["conversation_id"],
            "pre_revision": evidence["turn"]["pre_revision"],
        },
    )
    assert result["status"] == "incomplete"
    assert "runtime_projection_version_mismatch" in result["errors"]

    usage_drift = copy.deepcopy(base)
    usage_drift["retrieval_use"]["candidates"].append(
        {
            "scope": "injected",
            "candidate": True,
            "unit_ids": [],
            "truncated": False,
            "empty": True,
            "seq": 999,
        }
    )
    result = _completeness(evidence, usage_drift)
    assert result["status"] == "incomplete"
    assert "runtime_usage_inconsistent" in result["errors"]

    trace_lost = copy.deepcopy(base)
    trace_lost["trace"] = {
        "availability": "unavailable",
        "reason": "trace_record_missing",
        "trace_id": "synthetic-trace",
        "path": None,
        "outcome": None,
        "status": None,
        "spans": [],
        "model_failure_reason": None,
    }
    result = _completeness(evidence, trace_lost)
    assert result["status"] == "incomplete"
    assert "runtime_trace_unresolved" in result["errors"]
    assert result["scoring_readiness"]["four_axis"] is False
    assert result["scoring_readiness"]["quality_rescore"] is False
    assert "trace_unavailable" in result["scoring_readiness"]["reasons"]

    binding_drift = copy.deepcopy(base)
    binding_drift["binding"]["conversation_id"] = str(uuid.uuid4())
    result = _completeness(evidence, binding_drift)
    assert result["status"] == "incomplete"
    assert "runtime_snapshot_binding_mismatch" in result["errors"]


@asyncio_test
async def test_replay_turn_marks_snapshot_explicitly_unavailable(tmp_path: Path) -> None:
    bindings = _bindings("contract-replay")
    writer = _writer(tmp_path, bindings)
    adapter = _adapter(tmp_path / "run", writer=writer, bindings=bindings)
    replay_request_id = str(uuid.uuid4())
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        await adapter.ask_turn(
            ENUMERATION_QUESTION,
            user_id="employee",
            conversation_id=conversation,
            client_request_id=replay_request_id,
        )
        await adapter.ask_turn(
            ENUMERATION_QUESTION,
            user_id="employee",
            conversation_id=conversation,
            client_request_id=replay_request_id,
        )
        session = adapter._evidence_session
        assert session is not None and session.blocked is False
        statuses = [row["completeness"]["status"] for row in session.turns]
        assert statuses == ["complete", "replayed"]
        replay = session.turns[1]
        snapshot = replay["runtime_snapshot"]
        assert snapshot["product_response"]["availability"] == "absent"
        assert snapshot["product_response"]["reason"] == "replay_no_new_product_response"
        assert snapshot["trace"]["reason"] == "replay_no_trace"
        assert snapshot["retrieval_use"]["availability"] == "unavailable"
        assert snapshot["retrieval_use"]["reason"] == "replay"
        assert replay["completeness"]["scoring_readiness"]["four_axis"] is False
        assert "replay" in replay["completeness"]["scoring_readiness"]["reasons"]
    finally:
        await adapter.close()
    manifest = adapter.evidence_capture_manifest()
    assert manifest is not None
    replay_rows = [
        row for row in manifest["turns"] if row["completeness_status"] == "replayed"
    ]
    assert len(replay_rows) == 1
    assert replay_rows[0]["runtime_trace_status"] == "absent"
    assert replay_rows[0]["scoring_quality_rescore"] is False


@asyncio_test
async def test_timeout_turn_preserves_partial_usage_and_marks_not_ready(
    tmp_path: Path,
) -> None:
    bindings = _bindings("contract-timeout")
    writer = _writer(tmp_path, bindings)
    adapter = ProductEvalAdapter(
        tmp_path / "run",
        chat=MockChatBackend(),
        dataset=_dataset(),
        ingest_plan=P2IngestPlan(sources=(IngestSource(D01),), label="contract"),
        evidence_capture=EvidenceCaptureConfig(
            root_dir=tmp_path / "evidence",
            bindings=bindings,
            writer=writer,
            capture_schema_version="p2-hard-evidence-capture/v0.3",
        ),
        turn_timeout_seconds=0.0001,
        purge_traces_on_close=True,
    )
    try:
        await adapter.start()
        await adapter.ingest()
        conversation = await adapter.open_conversation()
        with pytest.raises(EvidenceCaptureIncomplete):
            await adapter.ask_turn(
                ENUMERATION_QUESTION,
                user_id="employee",
                conversation_id=conversation,
                client_request_id=str(uuid.uuid4()),
            )
        session = adapter._evidence_session
        assert session is not None and session.blocked is True
        record = session.turns[0]
        assert record["completeness"]["status"] == "incomplete"
        snapshot = record["runtime_snapshot"]
        assert snapshot["product_response"]["availability"] == "absent"
        assert snapshot["product_response"]["reason"] == "turn_timed_out"
        assert snapshot["retrieval_use"]["availability"] in {"partial", "unavailable"}
        assert record["completeness"]["scoring_readiness"]["four_axis"] is False
        turn_files = [item for item in writer.written if item["kind"] == "turn"]
        assert len(turn_files) == 1
        envelope = read_encrypted_evidence(
            Path(turn_files[0]["path"]), key=writer.key, expected_bindings=writer.bindings
        )
        assert envelope["completeness"]["status"] == "incomplete"
    finally:
        await adapter.close()


def test_legacy_historical_audit_fixed_rejects_v03() -> None:
    """A-I G3：旧历史审计对 v0.3* 固定拒绝，旧版本行为不变。"""
    import importlib.util

    tool_path = ROOT / "tools" / "p2_h2_historical_audit.py"
    spec = importlib.util.spec_from_file_location("t207_historical_audit_probe", tool_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    module._require_supported_evidence_schema(
        {"schema_version": "p2-hard-evidence-capture/v0.1"}
    )
    module._require_supported_evidence_schema(
        {"schema_version": "p2-hard-evidence-capture/v0.2-live"}
    )
    for version in (
        "p2-hard-evidence-capture/v0.3",
        "p2-hard-evidence-capture/v0.3-live",
        "p2-hard-evidence-capture/v0.9",
        "",
    ):
        with pytest.raises(module.EntryError) as excinfo:
            module._require_supported_evidence_schema({"schema_version": version})
        assert excinfo.value.code == "unsupported_evidence_schema"
        assert excinfo.value.exit_code == module.EXIT_REFUSED
