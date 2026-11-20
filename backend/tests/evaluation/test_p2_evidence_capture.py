"""A2 定向测试：同实例 DB 投影、原始证据构造、篡改可见性与完整性闸门。

全部合成数据；不读真实 H2/私有密文/凭据，不发真实模型/网络请求（外层网络闸门）。
本文件只验证采集与完整性，不声称任何"四轴已通过"。
"""

from __future__ import annotations

import copy
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from cryptography.fernet import Fernet  # noqa: E402

from mktkb.evaluation.p2_evidence_capture import (  # noqa: E402
    BINDING_KEYS,
    EvidenceCaptureBlocked,
    EvidenceCaptureConfig,
    EvidenceCaptureConfigError,
    EvidenceCaptureIncomplete,
    EvidenceCaptureSession,
    build_turn_evidence,
    evaluate_completeness,
    public_capture_summary,
    read_turn_projection,
)
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    EvidenceWriter,
    read_encrypted_evidence,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

QUESTION_SENTINEL = "P2CAPTURE_SENTINEL_DO_NOT_EXPORT_9f3a"


def _bindings(**overrides: str) -> dict[str, str]:
    values = {key: "local_mock-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values.update(overrides)
    return values


class _FakeQa:
    def __init__(self, index) -> None:
        self._index = index
        self.config = type("Config", (), {"business_date": None})()

    def index(self):
        return self._index


def _rag_index(tmp_path: Path):
    from mktkb.rag import RagConfig, RagIndex

    config = RagConfig(provider_mode="offline", data_dir=tmp_path)
    index = RagIndex(tmp_path / "rag.sqlite3", config=config)
    index.initialize()
    return index


def _seed(
    tmp_path: Path,
    *,
    tampered: bool = False,
    long_unit_text: bool = False,
    extra_messages: int = 0,
) -> dict:
    """建一个完全合成的隔离业务库 + 隔离 rag 状态库。

    - entity 索引行（RetrievalUnitIndex.entity_filters）用于独立核对实体继承；
    - long_unit_text/extra_messages 用于验证投影截断必须显式记录而不是静默裁剪。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    tmp_path.mkdir(parents=True, exist_ok=True)
    from mktkb.conversations.models import (
        Base,
        Conversation,
        ConversationMessage,
        ConversationRequest,
        MessageSource,
    )
    from mktkb.documents import models as _document_models  # noqa: F401 - 注册表
    from mktkb.documents.models import Document, DocumentVersion, SourceUnit
    from mktkb.retrieval import models as _retrieval_models  # noqa: F401 - 注册 entity 索引表
    from mktkb.retrieval.models import RetrievalUnitIndex

    engine = create_engine("sqlite:///" + str(tmp_path / "business.sqlite3"))
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    ids: dict[str, Any] = {}
    db = session_factory()
    try:
        owner = uuid.uuid4()
        other = uuid.uuid4()
        conversation = Conversation(id=uuid.uuid4(), user_id=owner, title="capture")
        db.add(conversation)
        db.flush()
        ids["conversation_id"] = str(conversation.id)
        ids["owner_user_id"] = str(owner)

        question_text = "城东店的宣传海报在哪里？"
        user_message = ConversationMessage(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=owner,
            seq=1,
            role="user",
            text=question_text,
        )
        assistant = ConversationMessage(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=owner,
            seq=2,
            role="assistant",
            text="位置：A区1号货架",
            kind="answer",
            revision=1,
        )
        db.add_all([user_message, assistant])
        if tampered:
            db.add(
                ConversationMessage(
                    id=uuid.uuid4(),
                    conversation_id=conversation.id,
                    user_id=other,
                    seq=3,
                    role="user",
                    text="other-owner-context-message",
                )
            )
        for offset in range(extra_messages):
            db.add(
                ConversationMessage(
                    id=uuid.uuid4(),
                    conversation_id=conversation.id,
                    user_id=owner,
                    seq=3 + offset,
                    role="assistant",
                    text="filler-" + str(offset),
                )
            )
        db.flush()
        ids["user_message_id"] = str(user_message.id)
        ids["assistant_message_id"] = str(assistant.id)

        client_request_id = uuid.uuid4()
        ids["client_request_id"] = str(client_request_id)
        request = ConversationRequest(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=owner,
            client_request_id=client_request_id,
            payload_sha256="0" * 64,
            question=question_text,
            status="succeeded",
            attempt=1,
            user_message_id=user_message.id,
            result_message_id=assistant.id,
            error_retryable=False,
            created_at=assistant.created_at,
            started_at=assistant.created_at,
            deadline_at=assistant.created_at,
            finished_at=assistant.created_at,
        )
        db.add(request)
        db.flush()
        ids["request_id"] = str(request.id)

        document = Document(
            id=uuid.uuid4(),
            name="D01_合成物品位置表",
            name_key="d01",
            file_type="xlsx",
            latest_version_number=2,
            deleted=bool(tampered),
        )
        version1 = DocumentVersion(
            id=uuid.uuid4(),
            document_id=document.id,
            number=1,
            state="published",
            sha256="a" * 64,
            size_bytes=10,
            stored_path="synthetic/d01.xlsx",
        )
        version2 = DocumentVersion(
            id=uuid.uuid4(),
            document_id=document.id,
            number=2,
            state="superseded",
            sha256="b" * 64,
            size_bytes=10,
            stored_path="synthetic/d01-v2.xlsx",
        )
        document.active_version_id = version2.id if tampered else version1.id
        db.add_all([document, version1, version2])
        db.flush()

        def add_unit(
            unit_key: str,
            fields: dict,
            *,
            version=version1,
            ordinal: int = 0,
            text_suffix: str = "",
        ) -> SourceUnit:
            unit = SourceUnit(
                id=uuid.uuid4(),
                document_id=document.id,
                version_id=version.id,
                kind="table_row",
                ordinal=ordinal,
                unit_key=unit_key,
                locator={"sheet": "物品位置", "row": ordinal + 2},
                text="；".join(str(f"{key}：{value}") for key, value in fields.items()) + text_suffix,
                fields=fields,
            )
            db.add(unit)
            db.flush()
            return unit

        long_suffix = ("长" * 16400) if long_unit_text else ""
        unit = add_unit(
            "row:2",
            {
                "标识": "QF01",
                "门店": "城东店",
                "物品": "宣传海报",
                "位置": "A区1号货架",
                "生效日期": None if tampered else "2026-01-01",
                "失效日期": "not-a-date" if tampered else "2026-12-31",
            },
            text_suffix=long_suffix,
        )
        unit2 = add_unit(
            "row:3",
            {"标识": "QF02", "门店": "城西店", "物品": "宣传海报", "位置": "A区1号货架"},
            ordinal=1,
        )
        db.add_all(
            [
                RetrievalUnitIndex(
                    unit_id=unit.id,
                    version_id=version1.id,
                    document_id=document.id,
                    entity_type="record",
                    entity_key="城东店",
                    label="QF01",
                    entity_filters={"store": "城东店", "item": "宣传海报"},
                    token_count=1,
                ),
                RetrievalUnitIndex(
                    unit_id=unit2.id,
                    version_id=version1.id,
                    document_id=document.id,
                    entity_type="record",
                    entity_key="城西店",
                    label="QF02",
                    entity_filters={"store": "城西店", "item": "宣传海报"},
                    token_count=1,
                ),
            ]
        )
        db.add(
            MessageSource(
                id=uuid.uuid4(),
                message_id=assistant.id,
                source_id=unit.id,
                document_id=document.id,
                version_id=version1.id,
            )
        )
        db.commit()
        ids["unit_id"] = str(unit.id)
        ids["unit2_id"] = str(unit2.id)
        ids["document_id"] = str(document.id)
        ids["version_id"] = str(version1.id)
    finally:
        db.close()

    index = _rag_index(tmp_path)
    from mktkb.rag import QueryState

    index.save_state(
        QueryState(
            user_id=ids["owner_user_id"],
            conversation_id=ids["conversation_id"],
            store="城东店",
            last_kind="answer",
        )
    )
    if tampered:
        index.save_state(
            QueryState(
                user_id="other-user",
                conversation_id=ids["conversation_id"],
                store="城西店",
            )
        )
    return {
        "engine": engine,
        "session_factory": session_factory,
        "qa": _FakeQa(index),
        "index": index,
        "ids": ids,
    }


def _emit_complete_turn(sink, ids: dict, *, path: str = "legacy", include_bad_ids: bool = False) -> None:
    """合成一个完整回合事件流；全部身份/原值都取合成 DB 的真实行，便于独立核对。"""
    request_id = ids["request_id"]
    unit_ids = [ids["unit_id"], ids["unit2_id"]]
    if include_bad_ids:
        unit_ids.extend(["not-a-uuid", str(uuid.uuid4())])
    sink.emit(
        "claim_observed",
        {
            "request_id": request_id,
            "conversation_id": ids["conversation_id"],
            "attempt": 1,
            "authenticated_user_id": ids["owner_user_id"],
            "owner_user_id": ids["owner_user_id"],
            "user_message_id": ids["user_message_id"],
            "user_message_seq": 1,
            "initial_revision": 0,
            "replay": False,
        },
    )
    sink.emit("context_observed", {"request_id": request_id, "count": 0, "empty": True})
    sink.emit(
        "query_state_observed",
        {
            "request_id": None,
            "user_id": ids["owner_user_id"],
            "conversation_id": ids["conversation_id"],
            "stored_user_id": ids["owner_user_id"],
            "stored_conversation_id": ids["conversation_id"],
            "row_present": True,
            "state_keys": ["last_kind", "store"],
            "state_json": {"store": "城东店", "last_kind": "answer"},
            "pending_slot": None,
            "last_kind": "answer",
            "turn": None,
        },
    )
    sink.emit(
        "plan_observed",
        {
            "request_id": request_id,
            "path": path,
            "mode": "record",
            "filters": {"store": "城东店"},
            "terms": ["宣传海报"],
            "as_of": None,
            "include_future": False,
            "enumerate": False,
            "clarification": False,
            "state_keys": ["last_kind", "store"],
            "state_as_of": None,
            "state_pending_slot": None,
            "state_last_kind": "answer",
        },
    )
    sink.emit(
        "retrieval_observed",
        {
            "request_id": request_id,
            "scope": "legacy_retrieve_initial",
            "unit_ids": unit_ids,
            "candidate": False,
            "truncated": False,
            "empty": False,
        },
    )
    if path == "rag":
        sink.emit(
            "direct_rag_answer",
            {
                "request_id": None,
                "kind": "answer",
                "text": "位置：A区1号货架",
                "reason": None,
                "answer_source": "structured",
                "cited_unit_ids": [ids["unit_id"]],
                "fact_count": 1,
                "facts": [
                    {
                        "entity_key": "城东店",
                        "entity_label": "城东店",
                        "field_role": "位置",
                        "field_label": "位置",
                        "value": "A区1号货架",
                        "source_chunk_id": "chunk-1",
                        "source_unit_id": ids["unit_id"],
                        "doc_id": ids["document_id"],
                        "version_id": ids["version_id"],
                        "revision": 1,
                    }
                ],
                "state_keys": ["last_kind", "store"],
            },
        )
    else:
        sink.emit(
            "model_input",
            {
                "request_id": request_id,
                "purpose": "answer",
                "question": "question",
                "context_questions": [],
                "context_entities": {"store": "城东店"},
                "evidence": [
                    {
                        "source_id": unit_id,
                        "text": "门店：城东店",
                        "fields": {"门店": "城东店", "位置": "A区1号货架"},
                    }
                    for unit_id in unit_ids
                ],
            },
        )
        sink.emit(
            "model_output",
            {
                "request_id": request_id,
                "purpose": "answer",
                "status": "ok",
                "text": "位置：A区1号货架",
                "source_ids": [ids["unit_id"]],
                "query_terms": [],
                "provider_request_id": "mock-provider-request",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "error_code": None,
                "retryable": False,
            },
        )
    sink.emit(
        "answer_result",
        {
            "request_id": request_id,
            "kind": "answer",
            "text": QUESTION_SENTINEL + " 位置：A区1号货架",
            "source_ids": [ids["unit_id"]],
            "candidates": 0,
            "conflicts": 0,
            "missing_fields": [],
            "error_code": None,
            "reason": None,
        },
    )
    sink.emit(
        "commit_observed",
        {
            "request_id": request_id,
            "message_id": ids["assistant_message_id"],
            "assistant_seq": 2,
            "kind": "answer",
            "requested_kind": "answer",
            "text": "位置：A区1号货架",
            "source_ids": [ids["unit_id"]],
            "revision_before": 0,
            "revision_after": 0,
            "knowledge_changed": False,
            "error_code": None,
        },
    )



def _finish(
    seed: dict,
    *,
    root_dir: Path,
    path: str = "legacy",
    emit=...,
    strict: bool = True,
    timed_out: bool = False,
    include_bad_ids: bool = False,
    pre_revision: int | None = 0,
    post_revision: int | None = 0,
):
    session = EvidenceCaptureSession(
        EvidenceCaptureConfig(root_dir=root_dir, bindings=_bindings(), strict=strict)
    )
    session.bind()
    turn = session.begin_turn(
        turn_index=0,
        client_request_id=seed["ids"]["client_request_id"],
        conversation_id=seed["ids"]["conversation_id"],
        authenticated_user_id=seed["ids"]["owner_user_id"],
        question_sha256="a" * 64,
        pre_revision=pre_revision,
    )
    if emit is ...:
        _emit_complete_turn(turn.sink, seed["ids"], path=path, include_bad_ids=include_bad_ids)
    else:
        emit(turn.sink, seed["ids"])
    evidence = session.finish_turn(
        turn,
        http_status=200,
        timed_out=timed_out,
        db_factory=seed["session_factory"],
        qa=seed["qa"],
        post_revision=post_revision,
    )
    return session, turn, evidence


def _recompute(evidence: dict, **overrides: Any) -> dict:
    """对已构造证据重跑完整性（可篡改事件/投影），用于精确反例。"""
    kwargs: dict[str, Any] = {
        "events": evidence["capture"]["events"],
        "projection": evidence["db_projection"],
        "timed_out": False,
        "capture_status": evidence["capture"]["status"],
        "capture_errors": evidence["capture"]["errors"],
        "post_revision": evidence["turn"]["post_revision"],
        "authenticated_user_id": evidence["turn"]["authenticated_user_id"],
    }
    kwargs.update(overrides)
    return evaluate_completeness(**kwargs)



def test_turn_evidence_projects_db_facts_and_raw_unit_fields(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    session, turn, evidence = _finish(seed, root_dir=tmp_path / "evidence")
    assert evidence["completeness"]["status"] == "complete"
    projection = evidence["db_projection"]
    assert projection["request"]["id"] == seed["ids"]["request_id"]
    assert projection["conversation"]["owner_user_id"] == seed["ids"]["owner_user_id"]
    assert projection["request"]["result_message_id"] == seed["ids"]["assistant_message_id"]
    assert len(projection["messages"]) == 2
    units = {item["unit_id"]: item for item in projection["units"]}
    first = units[seed["ids"]["unit_id"]]
    assert first["raw_fields"]["门店"] == "城东店"
    assert first["date_fields"] == {"生效日期": "2026-01-01", "失效日期": "2026-12-31"}
    assert first["version_state"] == "published"
    assert first["active"] is True and first["document_deleted"] is False
    assert projection["query_states"][0]["stored_user_id"] == seed["ids"]["owner_user_id"]
    assert projection["unresolved_unit_ids"] == []
    summary = public_capture_summary(evidence)
    assert summary["completeness_status"] == "complete"
    assert QUESTION_SENTINEL not in json.dumps(summary, ensure_ascii=False)
    assert "question" not in json.dumps(summary)
    turn.sink.seal()


def test_tampered_projection_is_visible_not_silently_corrected(tmp_path: Path) -> None:
    seed = _seed(tmp_path, tampered=True)
    _, _, evidence = _finish(seed, root_dir=tmp_path / "evidence", include_bad_ids=True)
    projection = evidence["db_projection"]
    units = {item["unit_id"]: item for item in projection["units"]}
    unit = units[seed["ids"]["unit_id"]]
    assert unit["document_deleted"] is True
    assert unit["version_state"] == "published"
    assert unit["active"] is False, "active_version_id 与 unit.version 不一致必须如实保留"
    assert unit["date_fields"] == {"生效日期": None, "失效日期": "not-a-date"}
    owners = {item["owner_user_id"] for item in projection["messages"]}
    assert str(seed["ids"]["owner_user_id"]) in owners
    assert len(owners) == 2, "其它 owner 的上下文消息不能被静默丢弃"
    reasons = {item["reason"] for item in projection["unresolved_unit_ids"]}
    assert {"unit_id_invalid", "unit_not_found"} <= reasons
    state_users = {item["stored_user_id"] for item in projection["query_states"]}
    assert state_users == {seed["ids"]["owner_user_id"], "other-user"}
    assert evidence["completeness"]["status"] == "complete", "投影差异本身不自动判违规"


def test_incomplete_events_and_timeout_are_recorded(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    def emit_partial(sink, ids):
        sink.emit("claim_observed", {
            "request_id": "req-1",
            "conversation_id": ids["conversation_id"],
            "attempt": 1,
            "authenticated_user_id": ids["owner_user_id"],
            "owner_user_id": ids["owner_user_id"],
            "user_message_id": "m-user",
            "user_message_seq": 1,
            "initial_revision": 0,
            "replay": False,
        })
    _, _, evidence = _finish(
        seed,
        root_dir=tmp_path / "evidence",
        emit=emit_partial,
        timed_out=True,
        strict=False,
    )
    completeness = evidence["completeness"]
    assert completeness["status"] == "incomplete"
    assert "answer_result" in completeness["missing_event_kinds"]
    assert "commit_observed" in completeness["missing_event_kinds"]
    assert "turn_timed_out" in completeness["errors"]


def test_strict_session_blocks_after_incomplete_and_replay_is_distinct(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    session = EvidenceCaptureSession(
        EvidenceCaptureConfig(root_dir=tmp_path / "evidence", bindings=_bindings(), strict=True)
    )
    session.bind()
    turn = session.begin_turn(
        turn_index=0,
        client_request_id="not-in-db",
        conversation_id=seed["ids"]["conversation_id"],
        authenticated_user_id=seed["ids"]["owner_user_id"],
        question_sha256="a" * 64,
        pre_revision=0,
    )
    with pytest.raises(EvidenceCaptureIncomplete):
        session.finish_turn(
            turn,
            http_status=200,
            timed_out=False,
            db_factory=seed["session_factory"],
            qa=seed["qa"],
            post_revision=0,
        )
    assert session.blocked is True
    with pytest.raises(EvidenceCaptureBlocked):
        session.begin_turn(
            turn_index=1,
            client_request_id="x",
            conversation_id=seed["ids"]["conversation_id"],
            authenticated_user_id=seed["ids"]["owner_user_id"],
            question_sha256="a" * 64,
            pre_revision=0,
        )


def test_config_requires_bindings_and_outside_repo_root(tmp_path: Path) -> None:
    missing = _bindings()
    missing.pop("run_id")
    with pytest.raises(EvidenceCaptureConfigError):
        EvidenceCaptureSession(EvidenceCaptureConfig(root_dir=tmp_path / "ev", bindings=missing))
    with pytest.raises(EvidenceCaptureConfigError):
        EvidenceCaptureSession(
            EvidenceCaptureConfig(root_dir=Path(__file__).resolve().parents[3] / "inline-evidence", bindings=_bindings())
        )
    with pytest.raises(EvidenceCaptureConfigError):
        EvidenceCaptureSession(
            EvidenceCaptureConfig(
                root_dir=tmp_path / "ev",
                bindings=_bindings(),
                fixture_kind="real_go",
            )
        )


def test_adapter_bindings_override_placeholder_dataset_identity(tmp_path: Path) -> None:
    session = EvidenceCaptureSession(EvidenceCaptureConfig(root_dir=tmp_path / "evidence", bindings=_bindings()))
    session.bind(
        {
            "dataset_version": "adapter-dataset",
            "manifest_sha256": "b" * 64,
            "label_version": "adapter-label",
            "suite": "p2-holdout",
            "pipeline_version": "adapter-pipeline",
            "index_revision": 7,
            "provider": {"chat": {"provider": "mock"}},
        }
    )
    assert session.bindings["dataset_version"] == "adapter-dataset"
    assert session.bindings["index_revision"] == "7"
    assert session.bindings["run_id"].startswith("local_mock-")
    summary = session.summary()
    assert summary["blocked"] is False
    assert "adapter_components" not in summary


# --------------------------------------------------------------------------- #
# R1 反例：上下文声明/sink 失败/截断/同时点/身份/事实/实体继承/repr
# --------------------------------------------------------------------------- #


def _codes(result: dict) -> set[str]:
    return set(result["errors"])


def test_completeness_catches_context_declaration_and_identity_mismatch(tmp_path: Path) -> None:
    """声明 count/empty 与实际消息数量/身份/顺序/原值不符不得仍 complete。"""
    seed = _seed(tmp_path)
    _, _, evidence = _finish(seed, root_dir=tmp_path / "evidence")
    assert _recompute(evidence)["status"] == "complete"

    # a) 声明 2 条但只实际发出 1 条。
    tampered = copy.deepcopy(evidence)
    tampered["capture"]["events"][1]["payload"]["count"] = 2
    tampered["capture"]["events"][1]["payload"]["empty"] = False
    result = _recompute(tampered)
    assert result["status"] == "incomplete"
    assert "context_count_mismatch" in _codes(result), result

    # b) 声明 empty=true 但 count=1。
    tampered = copy.deepcopy(evidence)
    tampered["capture"]["events"][1]["payload"]["count"] = 1
    tampered["capture"]["events"][1]["payload"]["empty"] = True
    assert "context_empty_mismatch" in _codes(_recompute(tampered))

    # c) 声称 1 条历史消息，但 DB 中该消息原值/身份与事件不一致。
    events = copy.deepcopy(evidence["capture"]["events"])
    claim = events[0]["payload"]
    claim["user_message_seq"] = 3
    events[1]["payload"] = {"request_id": claim["request_id"], "count": 1, "empty": False}
    events.append(
        {
            "seq": len(events) + 1,
            "kind": "context_message",
            "payload": {
                "request_id": claim["request_id"],
                "message_id": seed["ids"]["user_message_id"],
                "owner_user_id": seed["ids"]["owner_user_id"],
                "role": "user",
                "seq": 1,
                "text": "被篡改的上下文原文",
                "origin": "history_user_question",
            },
        }
    )
    result = _recompute(evidence, events=events)
    assert result["status"] == "incomplete"
    assert "context_message_mismatch" in _codes(result), result

    # d) 消息顺序错误：事件 seq 倒序。
    events = copy.deepcopy(evidence["capture"]["events"])
    claim = events[0]["payload"]
    events[1]["payload"] = {"request_id": claim["request_id"], "count": 2, "empty": False}
    base_seq = len(events)
    for index, seq in enumerate((2, 1), start=1):
        events.append(
            {
                "seq": base_seq + index,
                "kind": "context_message",
                "payload": {
                    "request_id": claim["request_id"],
                    "message_id": seed["ids"]["user_message_id"],
                    "owner_user_id": seed["ids"]["owner_user_id"],
                    "role": "user",
                    "seq": seq,
                    "text": "q",
                    "origin": "history_user_question",
                },
            }
        )
    result = _recompute(evidence, events=events)
    assert "context_message_order_invalid" in _codes(result), result


def test_completeness_treats_sink_failure_and_projection_truncation_as_incomplete(
    tmp_path: Path,
) -> None:
    """sink 失败/溢出、投影截断都必须令回合 incomplete（不得静默裁剪）。"""
    seed = _seed(tmp_path)
    _, _, evidence = _finish(seed, root_dir=tmp_path / "evidence")
    assert _recompute(evidence)["status"] == "complete"

    failed = _recompute(evidence, capture_status="failed", capture_errors=[{"code": "capture_event_invalid"}])
    assert failed["status"] == "incomplete"
    assert "capture_sink_failed" in _codes(failed)
    assert "capture_error:capture_event_invalid" in _codes(failed)

    long_seed = _seed(tmp_path / "long", long_unit_text=True)
    _, _, long_evidence = _finish(long_seed, root_dir=tmp_path / "evidence-long", strict=False)
    assert "unit_text" in long_evidence["db_projection"]["truncations"]
    long_result = _recompute(long_evidence)
    assert long_result["status"] == "incomplete"
    assert "projection_unit_text_truncated" in _codes(long_result)

    many_seed = _seed(tmp_path / "many", extra_messages=60)
    _, _, many_evidence = _finish(many_seed, root_dir=tmp_path / "evidence-many", strict=False)
    assert "messages_limit" in many_evidence["db_projection"]["truncations"]


def test_completeness_requires_same_point_revision_evidence(tmp_path: Path) -> None:
    """revision 不能只查不倒退：claim/commit/快照必须证明同一时点。"""
    seed = _seed(tmp_path)
    _, _, evidence = _finish(seed, root_dir=tmp_path / "evidence")
    assert _recompute(evidence)["status"] == "complete"

    # a) 领取时的 revision 与发送前快照不一致。
    events = copy.deepcopy(evidence["capture"]["events"])
    events[0]["payload"]["initial_revision"] = 3
    result = _recompute(evidence, events=events)
    assert "revision_claim_mismatch" in _codes(result), result

    # b) 投影快照 revision 与回合结束后即时读取的 post revision 不一致（并发变更/事后反填）。
    result = _recompute(evidence, post_revision=9)
    assert "revision_snapshot_mismatch" in _codes(result), result

    # c) 无法读取 revision：必须 unknown/incomplete，不得仍 complete。
    _, _, no_pre = _finish(seed, root_dir=tmp_path / "evidence2", pre_revision=None, strict=False)
    result = _recompute(no_pre)
    assert result["status"] == "incomplete"
    assert "revision_unavailable" in _codes(result), result

    # d) 提交回执 revision_after 与 post revision 不一致。
    events = copy.deepcopy(evidence["capture"]["events"])
    events[-1]["payload"]["revision_after"] = 5
    result = _recompute(evidence, events=events)
    assert "revision_commit_after_mismatch" in _codes(result), result


def test_completeness_requires_claim_commit_and_db_identity(tmp_path: Path) -> None:
    """领取/提交身份必须与独立 DB 投影逐项一致。"""
    seed = _seed(tmp_path)
    _, _, evidence = _finish(seed, root_dir=tmp_path / "evidence")
    assert _recompute(evidence)["status"] == "complete"

    mutations = [
        ((0, "request_id"), "another-request", "claim_request_mismatch"),
        ((0, "owner_user_id"), "another-owner", "claim_owner_mismatch"),
        ((0, "user_message_id"), "another-message", "claim_user_message_unresolved"),
        ((-1, "message_id"), "another-message", "commit_message_unresolved"),
        ((-1, "text"), "tampered-committed-text", "commit_message_mismatch"),
        ((-1, "request_id"), "another-request", "commit_request_mismatch"),
    ]
    for (index, key), value, expected in mutations:
        events = copy.deepcopy(evidence["capture"]["events"])
        events[index]["payload"][key] = value
        result = _recompute(evidence, events=events)
        assert expected in _codes(result), (key, result)


def test_completeness_requires_full_rag_facts_and_entity_inheritance(tmp_path: Path) -> None:
    """直接 RAG facts/实体继承不得用计数代替，且来源必须独立可解析。"""
    seed = _seed(tmp_path)
    _, _, evidence = _finish(seed, root_dir=tmp_path / "evidence", path="rag")
    assert _recompute(evidence)["status"] == "complete"

    # a) fact_count 与完整 facts 条数不一致。
    events = copy.deepcopy(evidence["capture"]["events"])
    rag_event = next(event for event in events if event["kind"] == "direct_rag_answer")
    rag_event["payload"]["fact_count"] = 0
    assert "direct_rag_fact_count_mismatch" in _codes(_recompute(evidence, events=events))

    # b) facts 的来源 unit 未解析：不得静默丢失。
    events = copy.deepcopy(evidence["capture"]["events"])
    rag_event = next(event for event in events if event["kind"] == "direct_rag_answer")
    rag_event["payload"]["facts"][0]["source_unit_id"] = str(uuid.uuid4())
    assert "direct_rag_fact_source_unresolved" in _codes(_recompute(evidence, events=events))

    # c) 实体继承声明与 DB entity_filters 不一致。
    events = copy.deepcopy(evidence["capture"]["events"])
    events.append(
        {
            "seq": len(events) + 1,
            "kind": "entity_inheritance",
            "payload": {
                "request_id": seed["ids"]["request_id"],
                "entity_type": "store",
                "entity_key": "城西店",
                "source_message_id": seed["ids"]["assistant_message_id"],
                "source_unit_id": seed["ids"]["unit_id"],
                "source": "latest_assistant_message_source",
            },
        }
    )
    assert "entity_inheritance_mismatch" in _codes(_recompute(evidence, events=events))


def test_capture_reprs_never_echo_payload_text(tmp_path: Path) -> None:
    """严格白名单：repr 不得回显题面/回答哨兵或事件正文。"""
    seed = _seed(tmp_path)
    session, turn, evidence = _finish(seed, root_dir=tmp_path / "evidence")
    assert QUESTION_SENTINEL in json.dumps(evidence, ensure_ascii=False)
    for value in (repr(session), repr(turn), repr(session.config)):
        assert QUESTION_SENTINEL not in value
        assert "位置：A区1号货架" not in value

# --------------------------------------------------------------------------- #
# R1-1：实体继承前序 assistant / replay 语义 / writer 绑定一致性
# --------------------------------------------------------------------------- #

_PRIOR_UNIT_ID = "11111111-1111-4111-8111-111111111111"


def _r11_ev(_kind: str, **payload: Any) -> dict:
    return {"seq": 0, "kind": _kind, "payload": payload}


def _inheritance_fixture(*, source_message_id: str | None = "m-prior-assistant") -> tuple[list[dict], dict]:
    """合成一个满足全部完整性检查的多轮回合：前序 assistant 消息 seq2 < 本轮用户 seq3。"""
    events = [
        _r11_ev("claim_observed", request_id="req-1", conversation_id="c1", attempt=1,
                authenticated_user_id="u1", owner_user_id="u1", user_message_id="m-current-user",
                user_message_seq=3, initial_revision=0, replay=False),
        _r11_ev("context_observed", request_id="req-1", count=1, empty=False),
        _r11_ev("context_message", request_id="req-1", message_id="m-prior-user",
                owner_user_id="u1", role="user", seq=1, text="q1", origin="history_user_question"),
        _r11_ev("plan_observed", request_id="req-1", path="legacy", mode="record", filters={},
                terms=[], as_of=None, include_future=False, enumerate=False, clarification=False,
                state_keys=[], state_as_of=None, state_pending_slot=None, state_last_kind=None),
        _r11_ev("model_input", request_id="req-1", purpose="answer", question="q2",
                context_questions=["q1"], context_entities={"store": "城东店"},
                evidence=[{"source_id": _PRIOR_UNIT_ID, "text": "门店：城东店",
                           "fields": {"门店": "城东店"}}]),
        _r11_ev("model_output", request_id="req-1", purpose="answer", status="ok", text="a2",
                source_ids=[], query_terms=[], provider_request_id=None, usage=None,
                error_code=None, retryable=False),
        _r11_ev("answer_result", request_id="req-1", kind="answer", text="a2", source_ids=[],
                candidates=0, conflicts=0, missing_fields=[], error_code=None, reason=None),
        _r11_ev("commit_observed", request_id="req-1", message_id="m-current-assistant",
                assistant_seq=4, kind="answer", requested_kind="answer", text="a2", source_ids=[],
                revision_before=0, revision_after=0, knowledge_changed=False, error_code=None),
        _r11_ev("entity_inheritance", request_id="req-1", entity_type="store",
                entity_key="城东店", source_message_id=source_message_id,
                source_unit_id=_PRIOR_UNIT_ID, source="latest_assistant_message_source"),
    ]
    for index, item in enumerate(events, start=1):
        item["seq"] = index
    projection = {
        "conversation": {"id": "c1", "owner_user_id": "u1"},
        "request": {"id": "req-1", "conversation_id": "c1", "user_id": "u1",
                    "user_message_id": "m-current-user", "result_message_id": "m-current-assistant",
                    "status": "succeeded"},
        "query_states_available": True,
        "errors": [],
        "capture_revision": 0,
        "pre_revision": 0,
        "truncations": [],
        "messages": [
            {"id": "m-prior-user", "conversation_id": "c1", "owner_user_id": "u1",
             "role": "user", "seq": 1, "text": "q1"},
            {"id": "m-prior-assistant", "conversation_id": "c1", "owner_user_id": "u1",
             "role": "assistant", "seq": 2, "kind": "answer", "text": "a1"},
            {"id": "m-current-user", "conversation_id": "c1", "owner_user_id": "u1",
             "role": "user", "seq": 3, "text": "q2"},
            {"id": "m-current-assistant", "conversation_id": "c1", "owner_user_id": "u1",
             "role": "assistant", "seq": 4, "kind": "answer", "text": "a2"},
        ],
        "units": [{"unit_id": _PRIOR_UNIT_ID, "entity_filters": {"store": "城东店"}}],
        "unresolved_unit_ids": [],
    }
    return events, projection


def _r11_evaluate(events, projection) -> dict:
    return evaluate_completeness(
        events=events,
        projection=projection,
        timed_out=False,
        capture_status="active",
        capture_errors=[],
        post_revision=0,
        authenticated_user_id="u1",
    )


def test_entity_inheritance_source_must_be_prior_assistant() -> None:
    """契约 §2：实体继承来源必须是同会话、同 owner 的前序 assistant；否则 incomplete。"""
    events, projection = _inheritance_fixture()
    assert _r11_evaluate(events, projection)["status"] == "complete"

    def mutate(events_mut, projection_mut):
        return _r11_evaluate(events_mut, projection_mut)["errors"]

    # a) 指向本轮当前 assistant（seq4 >= 本轮用户 seq3）。
    events_a, projection_a = _inheritance_fixture(source_message_id="m-current-assistant")
    assert "entity_inheritance_message_not_prior" in mutate(events_a, projection_a)

    # b) 指向未来 assistant。
    events_b, projection_b = _inheritance_fixture(source_message_id="m-future-assistant")
    projection_b["messages"].append(
        {"id": "m-future-assistant", "conversation_id": "c1", "owner_user_id": "u1",
         "role": "assistant", "seq": 5, "kind": "answer", "text": "a3"}
    )
    assert "entity_inheritance_message_not_prior" in mutate(events_b, projection_b)

    # c) 跨会话/不存在的消息。
    events_c, projection_c = _inheritance_fixture(source_message_id="m-other-conversation")
    assert "entity_inheritance_message_unresolved" in mutate(events_c, projection_c)

    # d) 缺少来源消息（不能证明前序）。
    events_d, projection_d = _inheritance_fixture(source_message_id=None)
    assert "entity_inheritance_message_unresolved" in mutate(events_d, projection_d)

    # e) owner 不一致。
    events_e, projection_e = _inheritance_fixture()
    projection_e["messages"][1]["owner_user_id"] = "u2"
    assert "entity_inheritance_message_owner_mismatch" in mutate(events_e, projection_e)

    # f) 来源不是 assistant。
    events_f, projection_f = _inheritance_fixture()
    projection_f["messages"][1]["role"] = "user"
    assert "entity_inheritance_message_not_assistant" in mutate(events_f, projection_f)

    # g) 消息属别的 conversation。
    events_g, projection_g = _inheritance_fixture()
    projection_g["messages"][1]["conversation_id"] = "c-other"
    assert "entity_inheritance_message_conversation_mismatch" in mutate(events_g, projection_g)


def test_replay_only_turn_is_replayed_and_strict_session_does_not_block(tmp_path: Path) -> None:
    """契约 §2：replay 只要求 claim_observed(replay=true)；strict 不阻断合法 replay。"""
    seed = _seed(tmp_path)
    replay_event = {
        "seq": 1,
        "kind": "claim_observed",
        "payload": {
            "request_id": seed["ids"]["request_id"],
            "conversation_id": seed["ids"]["conversation_id"],
            "attempt": 1,
            "authenticated_user_id": seed["ids"]["owner_user_id"],
            "owner_user_id": seed["ids"]["owner_user_id"],
            "user_message_id": None,
            "user_message_seq": None,
            "initial_revision": 0,
            "replay": True,
        },
    }
    session, turn, evidence = _finish(
        seed,
        root_dir=tmp_path / "evidence",
        emit=lambda sink, ids: sink.events.append(replay_event),
        strict=True,
    )
    assert evidence["completeness"]["status"] == "replayed"
    assert session.blocked is False
    session.begin_turn(
        turn_index=1,
        client_request_id="next-request",
        conversation_id=seed["ids"]["conversation_id"],
        authenticated_user_id=seed["ids"]["owner_user_id"],
        question_sha256="a" * 64,
        pre_revision=0,
    )

    # 缺 claim 的 replay 回合不得被放过。
    missing_claim = _recompute(evidence, events=[])
    assert missing_claim["status"] == "incomplete"

    # 伪造 replay 标记：附带其它事件（含必需事件）一律 incomplete。
    forged_events = copy.deepcopy(evidence["capture"]["events"]) + [
        {
            "seq": 2,
            "kind": "plan_observed",
            "payload": {
                "request_id": seed["ids"]["request_id"], "path": "legacy", "mode": "record",
                "filters": {}, "terms": [], "as_of": None, "include_future": False,
                "enumerate": False, "clarification": False, "state_keys": [],
                "state_as_of": None, "state_pending_slot": None, "state_last_kind": None,
            },
        }
    ]
    forged = _recompute(evidence, events=forged_events)
    assert forged["status"] == "incomplete"
    assert "replay_with_unexpected_events" in forged["errors"]

    # 被 replay 的请求在 DB 中必须是 succeeded。
    wrong_projection = copy.deepcopy(evidence["db_projection"])
    wrong_projection["request"] = dict(wrong_projection["request"], status="running")
    running = _recompute(evidence, projection=wrong_projection)
    assert "replay_request_not_succeeded" in running["errors"]


def test_writer_binding_mismatch_fails_closed_instead_of_overwrite(tmp_path: Path) -> None:
    """首回合前已知绑定不一致必须固定失败，不得静默覆盖 writer.bindings。"""
    seed = _seed(tmp_path)
    writer = EvidenceWriter(
        root_dir=tmp_path / "evidence",
        key=Fernet.generate_key(),
        bindings=_bindings(run_id="run-B"),
        run_name="binding-probe",
    )
    session = EvidenceCaptureSession(
        EvidenceCaptureConfig(
            root_dir=tmp_path / "evidence",
            bindings=_bindings(run_id="run-A"),
            writer=writer,
        )
    )
    session.bind()
    turn = session.begin_turn(
        turn_index=0,
        client_request_id=seed["ids"]["client_request_id"],
        conversation_id=seed["ids"]["conversation_id"],
        authenticated_user_id=seed["ids"]["owner_user_id"],
        question_sha256="a" * 64,
        pre_revision=0,
    )
    _emit_complete_turn(turn.sink, seed["ids"])
    with pytest.raises(EvidenceCaptureIncomplete, match="evidence_writer_binding_mismatch"):
        session.finish_turn(
            turn,
            http_status=200,
            timed_out=False,
            db_factory=seed["session_factory"],
            qa=seed["qa"],
            post_revision=0,
        )
    assert session.blocked is True
    assert writer.bindings["run_id"] == "run-B", "不得被静默覆盖"
    assert writer.written == []

    # 一致时正常写入，adapter 合并键仍可同步。
    good_writer = EvidenceWriter(
        root_dir=tmp_path / "evidence-good",
        key=Fernet.generate_key(),
        bindings=_bindings(run_id="run-A"),
        run_name="binding-ok",
    )
    good_session = EvidenceCaptureSession(
        EvidenceCaptureConfig(
            root_dir=tmp_path / "evidence-good",
            bindings=_bindings(run_id="run-A"),
            writer=good_writer,
        )
    )
    good_session.bind({"dataset_version": "adapter-dataset", "index_revision": 7})
    good_turn = good_session.begin_turn(
        turn_index=0,
        client_request_id=seed["ids"]["client_request_id"],
        conversation_id=seed["ids"]["conversation_id"],
        authenticated_user_id=seed["ids"]["owner_user_id"],
        question_sha256="a" * 64,
        pre_revision=0,
    )
    _emit_complete_turn(good_turn.sink, seed["ids"])
    good_evidence = good_session.finish_turn(
        good_turn,
        http_status=200,
        timed_out=False,
        db_factory=seed["session_factory"],
        qa=seed["qa"],
        post_revision=0,
    )
    assert good_evidence["completeness"]["status"] == "complete"
    assert good_writer.bindings["dataset_version"] == "adapter-dataset"
    assert good_writer.bindings["run_id"] == "run-A"
    manifest = good_session.finalize()
    assert manifest["sealed"]["kind"] == "manifest"
    assert read_encrypted_evidence(
        Path(manifest["sealed"]["path"]), key=good_writer.key, expected_bindings=good_writer.bindings
    )["summary"]["turn_count"] == 1


