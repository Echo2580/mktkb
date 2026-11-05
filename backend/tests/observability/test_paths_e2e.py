"""T003d：QA 产品路径 / legacy 路径的 Trace 绑定（request_id / path / outcome / Span）E2E。

覆盖 handoff §5.1–§5.7：

- RAG 产品路径：固定枚举问答（RagIndex 内核作答）→ path=rag、outcome 来自 ``RagAnswer.kind``；
- legacy 路径：``_rag_owns_turn`` 为假 → path=legacy 或 legacy_with_rag_candidates，
  按设计 §6.4 表补齐 intent_parse / retrieve / query_expansion（仅触发）/ model_answer /
  answer_validate / commit；
- 多 outcome：answer / conflict / no_answer（检索后）/ clarification / service_error；
- index_sync 只在真正执行同步时出现；重放写 status=replayed 且不覆盖历史；
- HMAC key 配置下 hash_algo=hmac-sha256、记录里无密钥。

零真实模型/OCR/embedding/rerank 调用：模型用 ``conftest.EvidenceEchoGateway``，RAG 用
offline 确定性替身；只写 pytest ``tmp_path``，不读 ``.env``、不访问外网、不打印凭据。
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
from pydantic import SecretStr

from mktkb.documents import lifecycle
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app
from mktkb.observability import (
    OutcomeKind,
    TraceMode,
    TracePath,
    required_spans,
    start_trace,
    validate_required_spans,
)
from mktkb.providers.types import ModelUnavailable
from observability.conftest import T003D_HEADERS, T003D_ROWS, open_session

#: 纯 RAG 作答（记录型枚举 + 物品过滤 → ``_rag_owns_turn`` 为真）。
RAG_ENUMERATE_QUESTION = "把城东店和滨江店的宣传海报记录都列出来"
#: legacy 记录型问题：模型措辞 + 事实准入，且会先取 rag 候选（legacy_with_rag_candidates）。
LEGACY_RECORD_QUESTION = "滨江店的宣传海报在哪里？"
#: legacy 正文型问题：不取 rag 候选（path=legacy），由既有 FTS 证据 + 模型作答。
LEGACY_DOCUMENT_QUESTION = "公司的愿景是什么？"
#: legacy 服务错误：证据存在但模型不可用。
LEGACY_ERROR_QUESTION = "公司的愿景是什么？"
#: 触发 query_expansion 的问题：无实体命中、有正文词项、证据为空。
EXPANSION_QUESTION = "打印机怎么用？"
#: 两个已知门店 → 产品意图层直接澄清（不检索）。
CLARIFICATION_QUESTION = "滨江店和城东店的展架在哪里？"
#: 检索前拒答：RAG 内核对未收录资料名直接 no_answer（DOCUMENT_NOT_FOUND）。
MISSING_DOCUMENT_QUESTION = "促销活动台账在哪里？"
#: 检索后拒答：标识存在但无价格字段。
NO_ANSWER_QUESTION = "QF001的价格是多少？"
#: 同一标识在两条资料里位置冲突。
CONFLICT_QUESTION = "QF001在哪里？"
#: 空库固定问答：产品 legacy 路径稳定 not_found（与 test_middleware 同口径）。
EMPTY_QUESTION = "城东店的宣传海报在哪里？"
#: §5.11 复现问题：解析级早退 not_found（只问了资料未记录的字段，未执行 retrieve）。
EARLY_NOT_FOUND_QUESTIONS = ("滨江店的负责人是谁？", "滨江店宣传海报的负责人是谁？")


# ---- 装配辅助（只写 tmp_path） ----


def _xlsx(path: Path, rows: list[list[object]], *, headers: list[str] | None = None) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "台账"
    worksheet.cell(row=1, column=1, value="物品位置台账")
    for column, header in enumerate(headers or T003D_HEADERS, start=1):
        worksheet.cell(row=6, column=column, value=header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=7 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _admin(app) -> SimpleNamespace:
    return open_session(app, "admin", "AdminPass-1")


def _employee(app) -> SimpleNamespace:
    return open_session(app, "employee", "EmployeePass-1")


def _revision(app) -> int:
    from mktkb.documents.lifecycle import get_revision

    db = app.state.db.session()
    try:
        return get_revision(db)
    finally:
        db.close()


def _upload_and_worker(app, session: SimpleNamespace, path: Path) -> dict:
    receipt = session.upload(path=path)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
    finally:
        db.close()
    return record


def _publish(app, admin: SimpleNamespace, record: dict) -> dict:
    response = admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=admin.headers,
        json={"expected_active_version_id": None, "expected_revision": _revision(app)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _publish_bypassing_hook(app, record: dict) -> None:
    """绕过产品发布钩子的索引同步：只改生命周期 revision，不通知 qa。"""
    db = app.state.db.session()
    try:
        lifecycle.publish_version(
            db,
            uuid.UUID(record["document"]["id"]),
            uuid.UUID(record["version"]["id"]),
            expected_active_version_id=None,
            expected_revision=0,
        )
    finally:
        db.close()


def _dataset(app, session: SimpleNamespace, rows: list[list[object]] | None = None) -> dict:
    # 固定文件名：文档标题会进入 RAG 证据文本，随机 UUID 文件名可能恰好包含业务数值
    # 片段（如 "40"），会让事实校验把标题误判为“未请求字段值”，造成随机 flake。
    path = _xlsx(Path(app.state.settings.data_dir) / "t003d-dataset.xlsx", rows or T003D_ROWS)
    record = _upload_and_worker(app, session, path)
    _publish(app, session, record)
    return record


def _conversation(session: SimpleNamespace) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(
    session: SimpleNamespace,
    conversation_id: str,
    question: str,
    *,
    client_request_id: uuid.UUID | None = None,
):
    return session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(client_request_id or uuid.uuid4()), "question": question},
        headers=session.headers,
    )


def _trace_of(app, response) -> tuple[object, list[object]]:
    trace_id = response.headers.get("X-Trace-ID")
    assert trace_id, "开启 Trace 时 QA POST 必须返回 X-Trace-ID"
    trace, spans = app.state.trace_repo.get(trace_id)
    return trace, spans


def _names(spans: list[object]) -> set[str]:
    return {span.name for span in spans}


def _one(spans: list[object], name: str):
    matches = [span for span in spans if span.name == name]
    assert len(matches) == 1, f"Span {name!r} 应恰有一个，实际 {[span.name for span in spans]}"
    return matches[0]


def _flags(trace) -> dict:
    return json.loads(trace.filter_decisions_json or "{}")


def _assert_no_content_leak(trace, spans: list[object], *needles: str) -> None:
    blobs = [str(getattr(trace, field.name)) for field in dataclasses.fields(trace)]
    for span in spans:
        blobs.extend([str(span.name), str(span.attributes_json), str(span.error_code)])
    joined = "\n".join(blobs)
    for needle in needles:
        assert needle not in joined, f"Trace 泄漏了内容原文：{needle!r}"


class _CapturingRepo:
    """内存仓储替身（不建库），用于直接驱动 ``QaEngine.answer`` 的 outcome 绑定。"""

    def __init__(self) -> None:
        self.writes: list[tuple[object, list[object]]] = []

    def write_best_effort(self, record, spans) -> None:
        self.writes.append((record, list(spans)))

    @property
    def last(self):
        assert self.writes, "Trace 未写入"
        return self.writes[-1]


# ---- §5.1 RAG 产品路径 E2E ----


def test_rag_answer_path_binds_request_path_outcome_and_spans(trace_chat_app):
    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin)
    conversation_id = _conversation(employee)

    response = _ask(employee, conversation_id, RAG_ENUMERATE_QUESTION)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "answer"
    trace, spans = _trace_of(trace_chat_app, response)

    # request_id = 本次产品请求（ConversationRequest.id，响应体同名字段）；http_request_id 对齐中间件。
    assert trace.request_id == body["request_id"]
    assert trace.http_request_id == response.headers["X-Request-ID"]
    assert trace.path == TracePath.RAG.value
    assert trace.outcome_kind == OutcomeKind.ANSWER.value
    assert trace.status == "ok"
    names = _names(spans)
    assert required_spans(TracePath.RAG, OutcomeKind.ANSWER) <= names
    assert validate_required_spans(trace, names) == []
    assert {"parse", "recall", "fuse", "answer", "commit"} <= names
    # RAG 路径不应出现 legacy 专属 Span（未执行不伪造）。
    assert not {"intent_parse", "retrieve", "model_answer", "answer_validate"} & names
    # 问题只以哈希 + 长度出现（无 key → sha256；HMAC 场景见下一条用例）。
    assert trace.question_hash is not None and len(trace.question_hash) == 64
    assert trace.question_chars == len(RAG_ENUMERATE_QUESTION)
    assert trace.hash_algo == "sha256"
    assert trace.hmac_key_id is None
    # 问题原文不得进入 trace（答案/引用由 RAG 内核的 locator 承载，属 T003c 既有边界）。
    _assert_no_content_leak(trace, spans, RAG_ENUMERATE_QUESTION)


# ---- §5.2 legacy 路径 ----


def test_legacy_with_rag_candidates_answer_binds_path_and_legacy_spans(trace_chat_app):
    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin)
    conversation_id = _conversation(employee)

    response = _ask(employee, conversation_id, LEGACY_RECORD_QUESTION)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "answer", body
    trace, spans = _trace_of(trace_chat_app, response)

    assert trace.request_id == body["request_id"]
    assert trace.path == TracePath.LEGACY_WITH_RAG_CANDIDATES.value
    assert trace.outcome_kind == OutcomeKind.ANSWER.value
    assert trace.status == "ok"
    names = _names(spans)
    assert required_spans(TracePath.LEGACY_WITH_RAG_CANDIDATES, OutcomeKind.ANSWER) <= names
    assert {"intent_parse", "retrieve", "model_answer", "answer_validate", "commit"} <= names
    assert validate_required_spans(trace, names) == []
    # 证据命中时没有触发查询扩展：不得出现 query_expansion，也不得写条件属性。
    assert "query_expansion" not in names
    assert "expansion_triggered" not in _flags(trace)
    _assert_no_content_leak(trace, spans, LEGACY_RECORD_QUESTION, "B区1号货架第二层")


def test_plain_legacy_document_answer_binds_path_and_legacy_spans(trace_chat_app):
    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin)
    conversation_id = _conversation(employee)

    response = _ask(employee, conversation_id, LEGACY_DOCUMENT_QUESTION)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "answer", body
    trace, spans = _trace_of(trace_chat_app, response)

    assert trace.path == TracePath.LEGACY.value
    assert trace.outcome_kind == OutcomeKind.ANSWER.value
    names = _names(spans)
    assert {"intent_parse", "retrieve", "model_answer", "answer_validate", "commit"} <= names
    assert validate_required_spans(trace, names) == []
    # 正文型问题不取 rag 候选，因此没有 RAG recall/fuse Span。
    assert not {"recall", "fuse"} & names


# ---- §5.3 多 outcome 覆盖 ----


def test_rag_conflict_path_binds_outcome_and_required_spans(trace_chat_app):
    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin)
    # 第二条资料：同一标识 QF001 的不同位置 → 结构化冲突。
    second = _xlsx(
        Path(trace_chat_app.state.settings.data_dir) / "t003d-conflict.xlsx",
        [["滨江店", "宣传海报", 40, "QF001", "D区暂存柜"]],
    )
    record = _upload_and_worker(trace_chat_app, admin, second)
    _publish(trace_chat_app, admin, record)
    conversation_id = _conversation(employee)

    response = _ask(employee, conversation_id, CONFLICT_QUESTION)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "conflict", body
    trace, spans = _trace_of(trace_chat_app, response)

    assert trace.path == TracePath.RAG.value
    assert trace.outcome_kind == OutcomeKind.CONFLICT.value
    assert trace.reason == "CONFLICTING_VALUES"
    names = _names(spans)
    assert required_spans(TracePath.RAG, OutcomeKind.CONFLICT) <= names
    assert {"answer", "fact_validate"} <= names
    assert validate_required_spans(trace, names) == []


def test_rag_retrieval_no_answer_still_requires_recall_and_fuse(trace_chat_app):
    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin, [T003D_ROWS[0]])
    conversation_id = _conversation(employee)

    response = _ask(employee, conversation_id, NO_ANSWER_QUESTION)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "not_found", body
    trace, spans = _trace_of(trace_chat_app, response)

    assert trace.path == TracePath.RAG.value
    assert trace.outcome_kind == OutcomeKind.NO_ANSWER.value
    # 检索后拒答的 reason 不在例外集合：仍要求 recall/fuse（§5.9 另一侧）。
    assert trace.reason not in {"DOCUMENT_NOT_FOUND", "UNKNOWN_STORE", "RECORD_ONLY"}
    names = _names(spans)
    assert required_spans(TracePath.RAG, OutcomeKind.NO_ANSWER, reason=trace.reason) <= names
    assert {"recall", "fuse"} <= names
    assert validate_required_spans(trace, names) == []


def test_legacy_clarification_binds_outcome_without_fabricated_retrieval(trace_chat_app):
    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin)
    conversation_id = _conversation(employee)

    response = _ask(employee, conversation_id, CLARIFICATION_QUESTION)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "clarification", body
    trace, spans = _trace_of(trace_chat_app, response)

    assert trace.path == TracePath.LEGACY.value
    assert trace.outcome_kind == OutcomeKind.CLARIFICATION.value
    assert _names(spans) == {"intent_parse", "commit"}
    assert required_spans(TracePath.LEGACY, OutcomeKind.CLARIFICATION) <= _names(spans)
    assert validate_required_spans(trace, _names(spans)) == []


def test_legacy_service_error_sets_outcome_error_code_and_spans(trace_chat_app, chat_model):
    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin)
    conversation_id = _conversation(employee)
    chat_model.error = ModelUnavailable("T003D 注入：模型暂不可用")

    response = _ask(employee, conversation_id, LEGACY_ERROR_QUESTION)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "service_error", body
    assert body["error_code"] == "MODEL_UNAVAILABLE"
    trace, spans = _trace_of(trace_chat_app, response)

    assert trace.path == TracePath.LEGACY.value
    assert trace.outcome_kind == OutcomeKind.SERVICE_ERROR.value
    assert trace.reason == "MODEL_UNAVAILABLE"
    assert trace.error_code == "MODEL_UNAVAILABLE"
    assert trace.status == "error"
    names = _names(spans)
    assert required_spans(TracePath.LEGACY, OutcomeKind.SERVICE_ERROR) <= names
    assert {"intent_parse", "commit"} <= names
    assert _one(spans, "model_answer").status == "error"
    assert validate_required_spans(trace, names) == []


def test_query_expansion_span_appears_only_when_triggered(trace_chat_app):
    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin)
    conversation_id = _conversation(employee)

    response = _ask(employee, conversation_id, EXPANSION_QUESTION)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "not_found", body
    trace, spans = _trace_of(trace_chat_app, response)

    assert trace.outcome_kind == OutcomeKind.NOT_FOUND.value
    names = _names(spans)
    assert "query_expansion" in names
    assert _one(spans, "query_expansion").status == "ok"
    assert _flags(trace)["expansion_triggered"] is True
    # 条件必需 Span 已真实执行，validate 通过（未触发的阶段没有被伪造）。
    assert required_spans(TracePath.LEGACY, OutcomeKind.NOT_FOUND) <= names
    assert validate_required_spans(trace, names) == []


# ---- §5.9 检索前拒答（reason-aware 契约）在真实 QaEngine 上的绑定 ----


def test_rag_pre_retrieval_no_answer_reason_aware_outcome(trace_chat_app):
    """空索引 + 点名未收录资料：RagAnswer.kind=no_answer/reason=DOCUMENT_NOT_FOUND。

    产品 ``_rag_owns_turn`` 在该问句上为假（走 legacy），因此直接驱动
    ``QaEngine.answer`` 验证「outcome 映射 + reason-aware 必需集」这条 T004/T006 会依赖的链路。
    """
    repo = _CapturingRepo()
    with start_trace(
        http_request_id="t003d-" + uuid.uuid4().hex,
        mode=TraceMode.LOCAL,
        scope="end_to_end",
        path=TracePath.RAG,
        question=MISSING_DOCUMENT_QUESTION,
        repo=repo,
    ) as trace:
        answer = trace_chat_app.state.qa.answer(
            MISSING_DOCUMENT_QUESTION, "u-t003d", "c-" + uuid.uuid4().hex
        )

    assert answer.kind == "no_answer"
    assert answer.reason == "DOCUMENT_NOT_FOUND"
    record, spans = repo.last
    assert record.outcome_kind == OutcomeKind.NO_ANSWER.value
    assert record.reason == "DOCUMENT_NOT_FOUND"
    assert _names(spans) == {"parse", "commit"}
    assert validate_required_spans(record, _names(spans)) == []


# ---- §5.11 legacy 解析级早退 reason-aware + 补充 outcome 行 ----

LEGACY_SUPPLEMENT = frozenset({"intent_parse", "retrieve", "commit"})


@pytest.mark.parametrize("question", EARLY_NOT_FOUND_QUESTIONS)
def test_legacy_parse_early_not_found_is_reason_aware(trace_chat_app, question):
    """复现问题：只问了资料未记录的“负责人”，解析后直接 not_found，未执行 retrieve。

    §5.11 的 reason-aware 契约让必需集退化为 ``intent_parse`` + ``commit``；产品响应不变。
    """
    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin)
    conversation_id = _conversation(employee)

    response = _ask(employee, conversation_id, question)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "not_found", body
    trace, spans = _trace_of(trace_chat_app, response)

    assert trace.path == TracePath.LEGACY.value
    assert trace.outcome_kind == OutcomeKind.NOT_FOUND.value
    assert trace.reason == "UNRECORDED_FIELD"
    names = _names(spans)
    # 真实执行集合：解析 + 提交，没有为凑必需集伪造 retrieve。
    assert names == {"intent_parse", "commit"}
    assert "retrieve" not in names
    assert required_spans(TracePath.LEGACY, OutcomeKind.NOT_FOUND, reason=trace.reason) <= names
    assert validate_required_spans(trace, names) == []


def test_legacy_conflict_matches_supplement_row_without_value_error(trace_chat_app):
    """legacy 冲突：T001 表外组合，§5.11 按实测执行补行，validate 不再抛 ValueError。"""
    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin)
    second = _xlsx(
        Path(trace_chat_app.state.settings.data_dir) / "t003d-legacy-conflict.xlsx",
        [["滨江店", "宣传海报", 40, "QF001", "D区暂存柜"]],
    )
    record = _upload_and_worker(trace_chat_app, admin, second)
    _publish(trace_chat_app, admin, record)
    conversation_id = _conversation(employee)

    response = _ask(employee, conversation_id, LEGACY_RECORD_QUESTION)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "conflict", body
    trace, spans = _trace_of(trace_chat_app, response)

    assert trace.path == TracePath.LEGACY_WITH_RAG_CANDIDATES.value
    assert trace.outcome_kind == OutcomeKind.CONFLICT.value
    assert trace.reason == "CONFLICTING_VALUES"
    names = _names(spans)
    assert LEGACY_SUPPLEMENT <= names
    assert required_spans(TracePath.LEGACY_WITH_RAG_CANDIDATES, OutcomeKind.CONFLICT) <= names
    # 之前会抛 “未定义 path+outcome 的必需 Span 契约”，现按补充行通过。
    assert validate_required_spans(trace, names) == []


def test_legacy_knowledge_changed_matches_supplement_row(trace_chat_app, monkeypatch):
    """legacy knowledge_changed（检索阶段 revision 变化）也按补充行校验。"""
    from mktkb.conversations import service as conversations_service
    from mktkb.retrieval.types import KnowledgeRevisionChanged

    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin)
    conversation_id = _conversation(employee)

    def _boom(*args, **kwargs):
        raise KnowledgeRevisionChanged("T003D 注入：检索阶段 revision 变化")

    monkeypatch.setattr(conversations_service, "_retrieve", _boom)
    response = _ask(employee, conversation_id, LEGACY_RECORD_QUESTION)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "knowledge_changed", body
    trace, spans = _trace_of(trace_chat_app, response)

    assert trace.outcome_kind == OutcomeKind.KNOWLEDGE_CHANGED.value
    assert trace.reason == "KNOWLEDGE_CHANGED"
    names = _names(spans)
    # 检索真实执行过（异常也留下 retrieve Span），因此不会被判缺失。
    assert "retrieve" in names
    assert LEGACY_SUPPLEMENT <= names
    assert validate_required_spans(trace, names) == []


def test_legacy_commit_time_knowledge_changed_after_early_exit(trace_chat_app, monkeypatch):
    """R1：解析级早退（未执行 retrieve）后在 commit 阶段 revision 复核时升级。

    以并发发布落在 ``claim → commit`` 窗口模拟（与 ``_commit_result_impl`` 的升级条件等价）：
    ``滨江店的负责人是谁？`` 在解析级早退为 not_found，提交事务发现 revision 变化后升级为
    ``knowledge_changed``。真实 Span 严格 ``{intent_parse, commit}``，reason 用独立稳定码
    ``KNOWLEDGE_CHANGED_AT_COMMIT``，validate 不再要求 retrieve；产品响应不受影响。
    """
    from mktkb.conversations import service as conversations_service
    from mktkb.documents.models import KnowledgeState

    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    _dataset(trace_chat_app, admin)
    conversation_id = _conversation(employee)
    real_commit = conversations_service._commit_result

    def _bump_revision_then_commit(*args, **kwargs):
        # 模拟并发发布发生在 claim 之后、commit 事务之前（只动 revision，不改业务分支）。
        db = trace_chat_app.state.db.session()
        try:
            state = db.get(KnowledgeState, 1)
            state.revision = int(state.revision) + 1
            db.commit()
        finally:
            db.close()
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(conversations_service, "_commit_result", _bump_revision_then_commit)

    response = _ask(employee, conversation_id, EARLY_NOT_FOUND_QUESTIONS[0])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "knowledge_changed", body
    assert "reason" not in body

    trace, spans = _trace_of(trace_chat_app, response)
    assert trace.path == TracePath.LEGACY.value
    assert trace.outcome_kind == OutcomeKind.KNOWLEDGE_CHANGED.value
    assert trace.reason == "KNOWLEDGE_CHANGED_AT_COMMIT"
    names = _names(spans)
    # 真实执行集合：解析 + 提交。早退没有 retrieve，不得为凑必需集伪造。
    assert names == {"intent_parse", "commit"}
    # 默认补充行（检索形态）不降强度；只有 commit 升级 reason 才退化。
    assert required_spans(TracePath.LEGACY, OutcomeKind.KNOWLEDGE_CHANGED) == (
        frozenset({"intent_parse", "retrieve", "commit"})
    )
    assert validate_required_spans(trace, names) == []


# ---- §5.6 index_sync：只有真同步才出现 ----


def test_index_sync_span_only_when_sync_actually_executes(trace_chat_app):
    admin, employee = _admin(trace_chat_app), _employee(trace_chat_app)
    path = _xlsx(Path(trace_chat_app.state.settings.data_dir) / "t003d-sync.xlsx", T003D_ROWS)
    record = _upload_and_worker(trace_chat_app, admin, path)
    _publish_bypassing_hook(trace_chat_app, record)
    # 发布钩子被绕过：索引仍是旧 revision，首次问答必须真实同步。
    assert trace_chat_app.state.qa.status()["product_revision"] == 0

    conversation_id = _conversation(employee)
    first = _ask(employee, conversation_id, LEGACY_RECORD_QUESTION)
    assert first.status_code == 200, first.text
    trace, spans = _trace_of(trace_chat_app, first)
    assert "index_sync" in _names(spans)
    assert _flags(trace)["index_sync_performed"] is True
    assert validate_required_spans(trace, _names(spans)) == []

    # 第二次：索引已就绪，ensure_ready 不再同步 → 不出现 index_sync、不写条件属性。
    second = _ask(employee, conversation_id, LEGACY_RECORD_QUESTION)
    assert second.status_code == 200, second.text
    trace2, spans2 = _trace_of(trace_chat_app, second)
    assert "index_sync" not in _names(spans2)
    assert "index_sync_performed" not in _flags(trace2)
    assert validate_required_spans(trace2, _names(spans2)) == []


# ---- §5.7 重放 / §5.5 HMAC ----


def test_replay_trace_is_replayed_without_overwriting_history(trace_app):
    employee = open_session(trace_app, "employee", "EmployeePass-1")
    conversation_id = _conversation(employee)
    client_request_id = uuid.uuid4()

    first = _ask(employee, conversation_id, EMPTY_QUESTION, client_request_id=client_request_id)
    assert first.status_code == 200, first.text
    first_trace, first_spans = _trace_of(trace_app, first)
    assert first_trace.status == "ok"
    assert first_spans

    second = _ask(employee, conversation_id, EMPTY_QUESTION, client_request_id=client_request_id)
    assert second.status_code == 200, second.text
    assert second.json()["kind"] == first.json()["kind"]
    replay_trace, replay_spans = _trace_of(trace_app, second)

    # 重放：没有真实执行 → status=replayed、Span 为空；同一 request_id 的多条尝试都可见。
    assert replay_trace.status == "replayed"
    assert replay_spans == []
    assert replay_trace.request_id == first_trace.request_id
    assert replay_trace.trace_id != first_trace.trace_id
    # 历史尝试不被覆盖。
    reread, reread_spans = trace_app.state.trace_repo.get(first_trace.trace_id)
    assert reread.status == "ok"
    assert [span.name for span in reread_spans] == [span.name for span in first_spans]


def test_trace_hmac_key_hashes_question_and_never_persists_key(trace_settings):
    key = "t003d-test-hmac-key-0123456789abcdef"
    settings = trace_settings.model_copy(update={"trace_hmac_key": SecretStr(key)})
    app = create_app(settings)
    try:
        employee = open_session(app, "employee", "EmployeePass-1")
        conversation_id = _conversation(employee)
        response = _ask(employee, conversation_id, EMPTY_QUESTION)
        assert response.status_code == 200, response.text
        trace, spans = _trace_of(app, response)

        assert trace.content_mode == "hash"
        assert trace.hash_algo == "hmac-sha256"
        assert trace.hmac_key_id
        assert trace.question_hash is not None and len(trace.question_hash) == 64
        rendered = json.dumps(dataclasses.asdict(trace), ensure_ascii=False) + "\n" + "\n".join(
            str(span.attributes_json) for span in spans
        )
        assert key not in rendered
        assert trace.question_hash != key
    finally:
        app.state.trace_repo.close()
        app.state.qa.close()
        app.state.db.dispose()
