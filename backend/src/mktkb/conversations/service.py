"""T06 问答编排：持久请求幂等/恢复、受约束意图、模型网关、六类结果与最终提交事务。

关键顺序（任务单 5.3/5.4）：
1. 短事务领取请求（``BEGIN IMMEDIATE``）：会话/所有者校验、同 ID 幂等、每会话单一 running；
2. 关闭读事务后再读 revision、上下文与检索（``retrieve`` 自带一致读快照）；
3. 外部模型调用全部在事务外，受同一个 60 秒单调预算约束，最多一次扩展 + 一次答案；
4. 最终以一个短 ``BEGIN IMMEDIATE`` 事务重检 revision、请求 attempt/会话所有者/未删除、
   所有引用仍有效，再原子保存结果/消息/引用并完成请求；提交成功后才返回事实。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Iterator

from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .. import copy as copy_module
from ..auth.service import UserContext
from ..conversations import intent as intent_module
from ..conversations.models import (
    Conversation,
    ConversationMessage,
    ConversationRequest,
    MessageSource,
    as_utc,
    utcnow,
)
from ..conversations.schemas import (
    AskResult,
    CandidateView,
    ConflictEntry,
    ConflictView,
    ConversationList,
    ConversationSummary,
    MessageList,
    MessageView,
    PaginationView,
    SourceSummary,
)
from ..documents.lifecycle import get_revision, visible_source_units_stmt
from ..documents.models import Document, DocumentVersion, SourceUnit
from ..errors import (
    AccessDenied,
    ConversationNotFound,
    QuestionInProgress,
    RequestCancelled,
    RequestPayloadMismatch,
    ServiceOverloaded,
    SourceNotFound,
)
from ..observability import trace_attrs
from ..observability.contracts import OutcomeKind, TracePath
from ..observability.tracer import current_trace
from ..qa import QaNotReady
from ..rag.chunking import role_label as rag_role_label
from ..rag.errors import KnowledgeChanged as RagKnowledgeChanged
from ..rag.types import QueryPlan, QueryState, RagAnswer
from ..providers.types import (
    MAX_MODEL_TERM_CHARS,
    MAX_MODEL_TERMS,
    CompletionInput,
    CompletionOutput,
    DialogueContext,
    ModelError,
    ModelEvidence,
    ModelGateway,
    ModelNotConfigured,
    ModelOutputInvalid,
    ModelTimeout,
)
from ..retrieval.index import HEADER_ROLES, resolve_requested_role
from ..retrieval.service import retrieve
from ..retrieval.tokenize import cut, normalize
from ..retrieval.types import EvidenceSet, IndexNotReady, KnowledgeRevisionChanged, QueryIntent, QueryRejected
from ..sources.service import message_sources, status_of, summary_for

BUDGET_SECONDS = 60.0
PER_CALL_TIMEOUT_SECONDS = 30.0
MAX_CONTEXT_QUESTIONS = 3
MAX_ANSWER_CHARS = 8000
WRITE_RETRIES = 6
WRITE_RETRY_SLEEP = 0.05
DIGEST_PREFIX = "t06:v1:"
DEFAULT_TITLE = "新会话"

# 测试可替换的单调时钟；生产用真实单调时钟
monotonic = time.monotonic


def wall_clock() -> datetime:
    return datetime.now(timezone.utc)


def payload_digest(question: str) -> str:
    return hashlib.sha256((DIGEST_PREFIX + question).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 会话 CRUD


def create_conversation(db: Session, user: UserContext, title: str | None = None) -> ConversationSummary:
    now = utcnow()
    conversation = Conversation(
        id=uuid.uuid4(),
        user_id=user.id,
        title=(title or DEFAULT_TITLE)[:200],
        created_at=now,
        updated_at=now,
    )
    db.add(conversation)
    db.commit()
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def list_conversations(db: Session, user: UserContext, *, offset: int = 0, limit: int = 20) -> ConversationList:
    base = select(Conversation).where(
        Conversation.user_id == user.id, Conversation.deleted_at.is_(None)
    )
    total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = db.scalars(
        base.order_by(Conversation.updated_at.desc(), Conversation.id).offset(offset).limit(limit)
    ).all()
    return ConversationList(
        items=[
            ConversationSummary(
                id=row.id, title=row.title, created_at=row.created_at, updated_at=row.updated_at
            )
            for row in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


def _load_conversation(db: Session, user: UserContext, conversation_id: uuid.UUID) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFound()
    if conversation.user_id != user.id:
        raise AccessDenied()
    if conversation.deleted_at is not None:
        raise ConversationNotFound()
    return conversation


def _stored_results(db: Session, message_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """按结果消息批量读取持久 result_json；历史消息的候选/冲突明细以它为准。"""
    ids = [item for item in message_ids if item is not None]
    if not ids:
        return {}
    rows = db.scalars(
        select(ConversationRequest).where(ConversationRequest.result_message_id.in_(ids))
    ).all()
    return {row.result_message_id: dict(row.result_json or {}) for row in rows if row.result_message_id is not None}


def _candidates_from(payload: dict | None) -> list[CandidateView]:
    if not payload:
        return []
    try:
        return [CandidateView.model_validate(item) for item in payload.get("candidates") or []]
    except ValueError:
        return []


def _pagination_from(payload: dict | None) -> PaginationView | None:
    if not payload:
        return None
    value = payload.get("pagination")
    if not value:
        return None
    try:
        return PaginationView.model_validate(value)
    except ValueError:
        return None


def _conflicts_from(payload: dict | None) -> list[ConflictView]:
    if not payload:
        return []
    try:
        return [ConflictView.model_validate(item) for item in payload.get("conflicts") or []]
    except ValueError:
        return []


def _conflict_source_summaries(db: Session, payload: dict | None) -> list[SourceSummary]:
    """旧冲突消息未保存 MessageSource 行时，按 result_json 中记录的 source_id 解析真实单元。"""
    if not payload or payload.get("kind") != "conflict":
        return []
    summaries: list[SourceSummary] = []
    seen: set[uuid.UUID] = set()
    for conflict in payload.get("conflicts") or []:
        for entry in conflict.get("entries") or []:
            try:
                source_id = uuid.UUID(str(entry.get("source_id")))
            except (TypeError, ValueError):
                continue
            if source_id in seen:
                continue
            seen.add(source_id)
            summary = summary_for(db, source_id)
            if summary is not None:
                summaries.append(summary)
    return summaries


def _message_sources_for(db: Session, message: ConversationMessage, payload: dict | None) -> list[SourceSummary]:
    summaries = message_sources(db, message)
    known = {item.source_id for item in summaries}
    for summary in _conflict_source_summaries(db, payload):
        if summary.source_id not in known:
            summaries.append(summary)
            known.add(summary.source_id)
    return summaries


def list_messages(
    db: Session, user: UserContext, conversation_id: uuid.UUID, *, offset: int = 0, limit: int = 20
) -> MessageList:
    conversation = _load_conversation(db, user, conversation_id)
    base = select(ConversationMessage).where(ConversationMessage.conversation_id == conversation.id)
    total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = db.scalars(base.order_by(ConversationMessage.seq).offset(offset).limit(limit)).all()
    stored = _stored_results(
        db, [row.id for row in rows if row.role == "assistant"]
    )
    items = []
    for row in rows:
        payload = stored.get(row.id)
        items.append(
            MessageView(
                id=row.id,
                role=row.role,
                text=row.text,
                kind=row.kind,
                revision=row.revision,
                error_code=row.error_code,
                missing_fields=[str(item) for item in (row.missing_fields or [])],
                created_at=row.created_at,
                sources=_message_sources_for(db, row, payload),
                candidates=_candidates_from(payload),
                conflicts=_conflicts_from(payload),
                pagination=_pagination_from(payload),
            )
        )
    return MessageList(items=items, total=total, offset=offset, limit=limit)


def delete_conversation(db: Session, user: UserContext, conversation_id: uuid.UUID, *, qa=None) -> None:
    """删除本人会话：逻辑删除 + 使未完成请求失效；重复删除保持 204。"""
    try:
        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            raise ConversationNotFound()
        if conversation.user_id != user.id:
            raise AccessDenied()
        now = utcnow()
        if conversation.deleted_at is None:
            conversation.deleted_at = now
            conversation.updated_at = now
            running = db.scalars(
                select(ConversationRequest).where(
                    ConversationRequest.conversation_id == conversation.id,
                    ConversationRequest.status == "running",
                )
            ).all()
            for request_row in running:
                request_row.status = "cancelled"
                request_row.finished_at = now
                request_row.error_code = "REQUEST_CANCELLED"
        db.commit()
    except BaseException:
        db.rollback()
        raise
    if qa is not None:
        try:
            # 本人会话删除后清理 rag 查询状态；失败不影响删除结果（状态按用户+会话隔离）。
            qa.clear_state(str(user.id), str(conversation_id))
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- 请求领取与恢复


@dataclass
class _Claim:
    conversation_id: uuid.UUID | None
    request_id: uuid.UUID
    attempt: int
    user_message_id: uuid.UUID
    initial_revision: int
    context_questions: tuple[str, ...] = ()
    context_entities: dict[str, str] = field(default_factory=dict)
    replay: AskResult | None = None


def _session_factory(db_factory):
    """接受 Database 或 Database.session 两种工厂形态（契约要求后者）。"""
    if callable(db_factory):
        return db_factory
    session_method = getattr(db_factory, "session", None)
    if session_method is None:
        raise TypeError("db_factory must be callable or Database")
    return session_method


@contextmanager
def _write_transaction(db_factory) -> Iterator[Session]:
    db = _session_factory(db_factory)()
    try:
        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def _commit_transaction(db_factory, deadline: float) -> Iterator[Session]:
    """最终提交专用短事务：把 SQLite 等锁时间限制在本请求剩余总预算内。

    ``busy_timeout`` 是连接级参数（默认 5 秒），会叠加到每次重试上；提交前按剩余预算重设，
    使"模型预算 + 锁竞争 + 提交重试"落在同一绝对截止时间内。预算已用尽时设为 0，
    库空闲则立即落库安全失败结果，库被占用则立即失败而不空等。
    """
    db = _session_factory(db_factory)()
    previous_ms: int | None = None
    try:
        previous_ms = int(db.execute(text("PRAGMA busy_timeout")).scalar() or 0)
        remaining_ms = max(0, int((deadline - monotonic()) * 1000))
        db.execute(text(f"PRAGMA busy_timeout={remaining_ms}"))
        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        if previous_ms is not None:
            # 连接会回到连接池；恢复连接默认等待，避免影响后续非提交事务。
            try:
                db.execute(text(f"PRAGMA busy_timeout={previous_ms}"))
            except Exception:  # noqa: BLE001 - 连接已失效时无需恢复
                pass
        db.close()


@contextmanager
def _read_session(db_factory) -> Iterator[Session]:
    db = _session_factory(db_factory)()
    try:
        yield db
    finally:
        db.close()


def _add_user_message(db: Session, conversation: Conversation, user: UserContext, question: str, now: datetime) -> ConversationMessage:
    seq = int(
        db.scalar(
            select(func.max(ConversationMessage.seq)).where(
                ConversationMessage.conversation_id == conversation.id
            )
        )
        or 0
    ) + 1
    message = ConversationMessage(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        user_id=user.id,
        seq=seq,
        role="user",
        text=question,
        created_at=now,
    )
    db.add(message)
    db.flush()
    return message


def _load_context(db: Session, conversation: Conversation, before_seq: int) -> tuple[tuple[str, ...], dict[str, str]]:
    rows = db.execute(
        select(ConversationMessage.text)
        .where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.role == "user",
            ConversationMessage.seq < before_seq,
        )
        .order_by(ConversationMessage.seq.desc())
        .limit(MAX_CONTEXT_QUESTIONS)
    ).all()
    questions = tuple(reversed([row[0] for row in rows]))

    latest_assistant = db.scalar(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.role == "assistant",
            ConversationMessage.seq < before_seq,
        )
        .order_by(ConversationMessage.seq.desc())
        .limit(1)
    )
    entities: dict[str, str] = {}
    if latest_assistant is not None:
        references = db.scalars(
            select(MessageSource).where(MessageSource.message_id == latest_assistant.id)
        ).all()
        for reference in references:
            from ..retrieval.models import RetrievalUnitIndex

            index_row = db.scalar(
                select(RetrievalUnitIndex).where(RetrievalUnitIndex.unit_id == reference.source_id)
            )
            filters = dict((index_row.entity_filters or {})) if index_row is not None else {}
            for key in ("store", "item"):
                if filters.get(key):
                    entities.setdefault(key, str(filters[key]))
    return questions, entities


def _claim(
    db_factory,
    user: UserContext,
    conversation_id: uuid.UUID,
    client_request_id: uuid.UUID,
    question: str,
    digest: str,
    deadline_at: datetime,
) -> _Claim:
    with _write_transaction(db_factory) as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            raise ConversationNotFound()
        if conversation.user_id != user.id:
            raise AccessDenied()
        if conversation.deleted_at is not None:
            raise ConversationNotFound()
        now = utcnow()

        existing = db.scalar(
            select(ConversationRequest).where(
                ConversationRequest.conversation_id == conversation.id,
                ConversationRequest.client_request_id == client_request_id,
            )
        )
        if existing is not None:
            if existing.payload_sha256 != digest:
                raise RequestPayloadMismatch()
            if existing.status == "succeeded":
                return _ReplayClaim(_replay(db, existing))
            if existing.status == "running":
                if not _deadline_passed(existing.deadline_at, now):
                    raise QuestionInProgress()
                existing.status = "expired"
                existing.finished_at = now
            attempt = int(existing.attempt) + 1
            existing.attempt = attempt
            existing.status = "running"
            existing.started_at = now
            existing.deadline_at = deadline_at
            existing.finished_at = None
            existing.error_code = None
            existing.error_retryable = False
            request_row = existing
            user_message = db.get(ConversationMessage, existing.user_message_id) if existing.user_message_id else None
            if user_message is None:
                user_message = _add_user_message(db, conversation, user, question, now)
                existing.user_message_id = user_message.id
        else:
            running = db.scalar(
                select(ConversationRequest.id).where(
                    ConversationRequest.conversation_id == conversation.id,
                    ConversationRequest.status == "running",
                )
            )
            if running is not None:
                raise QuestionInProgress()
            user_message = _add_user_message(db, conversation, user, question, now)
            request_row = ConversationRequest(
                id=uuid.uuid4(),
                conversation_id=conversation.id,
                user_id=user.id,
                client_request_id=client_request_id,
                payload_sha256=digest,
                question=question,
                status="running",
                attempt=1,
                user_message_id=user_message.id,
                created_at=now,
                started_at=now,
                deadline_at=deadline_at,
            )
            db.add(request_row)
            db.flush()

        conversation.updated_at = now
        revision = get_revision(db)
        questions, entities = _load_context(db, conversation, user_message.seq)
        return _Claim(
            conversation_id=conversation.id,
            request_id=request_row.id,
            attempt=int(request_row.attempt),
            user_message_id=user_message.id,
            initial_revision=revision,
            context_questions=questions,
            context_entities=entities,
        )


class _ReplayClaim(_Claim):
    """同 ID 已完成请求的重放；不新增消息、不调用模型。"""

    def __init__(self, result: AskResult) -> None:
        self.conversation_id = None
        self.request_id = result.request_id
        self.attempt = 0
        self.user_message_id = result.message_id
        self.initial_revision = result.revision
        self.context_questions = ()
        self.context_entities = {}
        self.replay = result


def _deadline_passed(deadline_at: datetime, now: datetime) -> bool:
    value = as_utc(deadline_at)
    return value is not None and value <= now


def _replay(db: Session, request_row: ConversationRequest) -> AskResult:
    stored = request_row.result_json or {}
    message = db.get(ConversationMessage, request_row.result_message_id) if request_row.result_message_id else None
    if message is None:
        raise RequestCancelled("请求结果缺少消息记录，请重新提问")
    payload = dict(stored)
    payload["sources"] = [
        source.model_dump(mode="json") for source in _message_sources_for(db, message, stored)
    ]
    payload.setdefault("request_id", str(request_row.id))
    payload.setdefault("message_id", str(message.id))
    return AskResult.model_validate(payload)


def expire_stale_requests(db_factory, *, now: datetime | None = None) -> int:
    """把已超过持久截止时间的 running 请求标为 expired；不重发模型请求。"""
    moment = now or wall_clock()
    with _write_transaction(db_factory) as db:
        rows = db.scalars(
            select(ConversationRequest).where(
                ConversationRequest.status == "running",
                ConversationRequest.deadline_at <= moment,
            )
        ).all()
        for row in rows:
            row.status = "expired"
            row.finished_at = moment
            row.error_code = "MODEL_TIMEOUT"
            row.error_retryable = True
        return len(rows)


# ---------------------------------------------------------------- 检索与证据


def _retrieve(
    db_factory,
    intent: QueryIntent,
    revision: int,
    limit: int = 20,
    *,
    candidate_ids: set[str] | None = None,
) -> EvidenceSet:
    """产品证据入口。``candidate_ids`` 是 rag 内核本轮召回的产品来源单元集合（记录型问题）。

    rag 索引与本轮 revision 对齐后才给出候选；这里只把候选作为记录型检索的上界，
    分组/歧义/冲突/可见性仍由既有检索与提交事务复核。正文型问题不做该限制。
    """
    db = _session_factory(db_factory)()
    try:
        return retrieve(db, intent, revision=revision, limit=limit, candidate_ids=candidate_ids)
    finally:
        db.close()


def _role_value(fields: dict, role: str) -> str | None:
    synonyms = HEADER_ROLES.get(role, ())
    for name, value in (fields or {}).items():
        if str(name).strip() in synonyms and value not in (None, ""):
            return str(value).strip()
    return None


def _entity_labels(units: Iterable[SourceUnit]) -> tuple[str | None, str | None]:
    store = item = None
    for unit in units:
        store = store or _role_value(unit.fields, "store")
        item = item or _role_value(unit.fields, "item")
    return store, item


def _facts(units: list[SourceUnit], requested_fields: tuple[str, ...]) -> tuple[list[tuple[str, str]], list[str]]:
    facts: list[tuple[str, str]] = []
    missing: list[str] = []
    seen: set[tuple[str, str]] = set()
    for label in requested_fields:
        role = resolve_requested_role(label)
        value = None
        if role:
            for unit in units:
                candidate = _role_value(unit.fields, role)
                if candidate:
                    value = candidate
                    break
        if value is None:
            missing.append(label)
            continue
        pair = (label, value)
        if pair not in seen:
            seen.add(pair)
            facts.append(pair)
    return facts, missing


def _rank_document_units(
    question: str, units: list[SourceUnit], *, keep: int = 8, extra_terms: Iterable[str] = ()
) -> list[SourceUnit]:
    """按问题词（含本次模型扩展词）在正文中的命中长度排序，保留若干高分正文作为证据。

    保留多条而不是只取最高分：正文流程题往往由相邻段落共同回答，只交一条会漏掉步骤；
    提示词仍要求模型只依据证据作答，来源 ID 也只允许本次证据集合。
    若所有单元都与问题词零重合（例如只有扩展词命中），按检索顺序保留前几条，
    不把已由检索确认的候选误判为 not_found。
    """
    tokens = [token for token in cut(question) if len(token) >= 2 and token not in intent_module.STOPWORDS]
    for term in extra_terms:
        for token in cut(str(term)):
            if len(token) >= 2 and token not in intent_module.STOPWORDS and token not in tokens:
                tokens.append(token)
    scored: list[tuple[int, int, int, SourceUnit]] = []
    for unit in units:
        text = unit.text or ""
        score = sum(len(token) for token in tokens if token in text)
        if score <= 0:
            continue
        scored.append((score, len(text), -int(unit.ordinal), unit))
    if not scored:
        return list(units)[: min(keep, 3)]
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [unit for _score, _length, _ordinal, unit in scored][:keep]


def _candidate_view(plan: intent_module.IntentPlan, evidence: EvidenceSet) -> list[CandidateView]:
    views: list[CandidateView] = []
    seen: set[tuple[str, str]] = set()
    for candidate in evidence.candidates[:8]:
        filters = dict(candidate.entity_filters or {})
        store = filters.get("store")
        item = filters.get("item")
        # D-IA-1：同门店同物品多行时，只有标识能区分候选行；候选追问必须带上它才能收敛。
        identifier = filters.get("item_id") or filters.get("store_id")
        label = store or item or candidate.label
        fields_text = "、".join(plan.requested_fields) if plan.requested_fields else "信息"
        subject = f"{store}的{item}" if store and item else (store or item or label)
        if identifier and identifier not in subject:
            subject = f"{subject} {identifier}"
        if store and item:
            followup = f"{subject}在哪里？" if "位置" in plan.requested_fields else f"{subject}的{fields_text}是什么？"
        elif store:
            followup = f"{store}的{fields_text}是什么？"
        elif item:
            followup = f"{subject}在哪里？" if "位置" in plan.requested_fields else f"{subject}的{fields_text}是什么？"
        else:
            followup = f"{label}的{fields_text}是什么？"
        key = (label, followup)
        if key in seen:
            continue
        seen.add(key)
        views.append(CandidateView(label=label, followup_question=followup))
    return views


def _conflict_views(units: list[SourceUnit], requested_fields: tuple[str, ...]) -> list[ConflictView]:
    views: list[ConflictView] = []
    for label in requested_fields:
        role = resolve_requested_role(label)
        if not role:
            continue
        values: dict[str, tuple[str, uuid.UUID]] = {}
        for unit in units:
            value = _role_value(unit.fields, role)
            if value:
                values.setdefault(normalize(value), (value, unit.id))
        if len(values) > 1:
            entries = [ConflictEntry(value=value, source_id=unit_id) for _key, (value, unit_id) in sorted(values.items())]
            views.append(ConflictView(field=label, entries=entries))
    return views


# ---------------------------------------------------------------- 模型调用与输出校验


def _validate_terms(output: CompletionOutput) -> tuple[str, ...]:
    terms: list[str] = []
    for raw in output.query_terms or ():
        if not isinstance(raw, str):
            raise ModelOutputInvalid("query_terms 必须是字符串")
        cleaned = raw.strip()
        if not cleaned:
            continue
        if len(cleaned) > MAX_MODEL_TERM_CHARS:
            raise ModelOutputInvalid("检索词过长")
        if any(marker in cleaned.lower() for marker in ("://", "/", "\\", ";", "--", "select ", "insert ", "update ", "delete ", " drop ", "{")):
            raise ModelOutputInvalid("检索词包含不允许的结构")
        if cleaned not in terms:
            terms.append(cleaned)
        if len(terms) > MAX_MODEL_TERMS:
            raise ModelOutputInvalid("检索词数量超出上限")
    return tuple(terms)


# 数据型 token（电话、编号、门牌、数量等 ASCII 值）：只用于通用（非记录型）回答的
# "取值必须能在实际引用来源中找到"校验。R3 恢复被 R2 连同调用点一起删掉的这两个辅助函数，
# 使 ``_validate_answer(evidence=...)`` 的既有校验路径不再因 NameError 失效。
_VALUE_TOKEN = re.compile(r"[0-9A-Za-z]+(?:[-_./:][0-9A-Za-z]+)*")


def _value_tokens(text: str) -> set[str]:
    """抽取数据型 token；中文叙述不做分词比对（本关口只约束数据值的可追溯性）。"""
    return {token.casefold() for token in _VALUE_TOKEN.findall(text or "")}


def _cited_corpus(evidence: Iterable[object], cited: set[str]) -> str:
    """只拼装回答实际引用的来源正文与原值字段；未引用来源不能为任何值背书。"""
    parts: list[str] = []
    for unit in evidence:
        if str(getattr(unit, "id", "")) not in cited:
            continue
        parts.append(str(getattr(unit, "text", "") or ""))
        for name, value in dict(getattr(unit, "fields", None) or {}).items():
            parts.append(f"{name} {value}")
    return "\n".join(parts)


def _other_store_labels(
    plan, lexicon, units: Iterable[object], cited: Iterable[str] | None = None
) -> tuple[str, ...]:
    """非记录型回答的门店混合范围：仅在问题把检索锁定到单一门店时，给出其它已知门店名。

    作用域取本次检索的显式门店过滤（``plan.intent.entity_filters["store"]``）：
    - 没有该过滤的“全部列出/跨店”问题不设禁止项，合法枚举不被误拒，也不把整本词典
      下发给每个回答；
    - 豁免集只取模型**本次实际引用**的来源（``cited``）：未引用候选里出现的门店名不能
      为回答放行；只有逐字引用含该门店名的来源行时，该门店才不列入禁止项；
    - 门店名来源只复用索引词表 ``EntityLexicon.store_labels``，不另建业务词典。
    """
    filters = dict(getattr(getattr(plan, "intent", None), "entity_filters", None) or {})
    scoped = normalize(str(filters.get("store") or ""))
    if not scoped:
        return ()
    cited_ids = {str(item) for item in cited or ()}
    corpus = normalize(_cited_corpus(units, cited_ids) if cited is not None else "")
    labels: list[str] = []
    for label in getattr(lexicon, "store_labels", ()):
        key = normalize(str(label))
        if not key or key == scoped or key in corpus:
            continue
        labels.append(str(label))
    return tuple(labels)


def _validate_answer(
    output: CompletionOutput,
    allowed: set[str],
    facts: list[tuple[str, str]],
    *,
    evidence: Iterable[object] | None = None,
    other_store_labels: Iterable[str] = (),
    store_scope: tuple[object, object] | None = None,
) -> tuple[str, list[str]]:
    text_value = (output.text or "").strip()
    if not text_value or len(text_value) > MAX_ANSWER_CHARS:
        raise ModelOutputInvalid("回答文本为空或过长")
    ids: list[str] = []
    for raw in output.source_ids or ():
        if not isinstance(raw, str):
            raise ModelOutputInvalid("source_ids 必须是字符串")
        cleaned = raw.strip()
        if cleaned and cleaned not in ids:
            ids.append(cleaned)
    if not ids:
        raise ModelOutputInvalid("回答未给出任何来源")
    if any(item not in allowed for item in ids):
        raise ModelOutputInvalid("回答引用了本次候选之外的来源")
    normalized = normalize(text_value)
    for _label, value in facts:
        if normalize(value) not in normalized:
            raise ModelOutputInvalid("回答未保留精确字段原值")
    # 事实准入（PM06-01）：只要求"正确值出现"不足以防夹带。回答里每个数据型 token
    # （电话/编号/门牌/数量等）都必须出现在本次回答实际引用的来源正文或原值字段中；
    # 未引用来源不能为任何值背书，因此"引用子集 + 别处取值"同样被拒绝。
    if evidence is not None:
        evidence_units = tuple(evidence)
        cited_corpus = _cited_corpus(evidence_units, set(ids))
        attested = _value_tokens(cited_corpus)
        unattested = sorted(token for token in _value_tokens(text_value) if token not in attested)
        if unattested:
            raise ModelOutputInvalid("回答包含引用来源中不存在的数据值")
    else:
        evidence_units = None
    if store_scope is not None:
        # CD-F1-R1：门店名豁免也只取本次实际引用的来源；未引用候选里的店名不能放行。
        other_store_labels = _other_store_labels(
            *store_scope, evidence_units or (), cited=ids
        )
    # 记录型回答只应描述本次问题指定的门店；出现其它已知门店名即视为混合事实。
    for label in other_store_labels:
        key = normalize(label)
        if key and key in normalized:
            raise ModelOutputInvalid("回答混入了其它门店的事实")
    return text_value, ids


# ---------------------------------------------------------------- 记录型事实准入（PM06-01）

# 记录型答案不再把模型自由文本当作事实保存。只接受一种可逐句验证的"事实陈述"结构：
#   <问题中的对象><字段名><正关系词><本次所选行的原值>[，/；<字段名><正关系词><原值>]…[。]
# 否定（不是/不在/并非…）、替代（而在/改为…）、多值连接、未列出的值、字段关系错配
# 都无法满足该结构，因此不会因"正确值子串存在"就被当作正向事实；不满足即 MODEL_OUTPUT_INVALID，
# 既不静默纠正，也不用构造文本冒充通过。缺字段说明句"资料中未记录…"仅作解释允许出现。
_RECORD_CONNECTORS = ("：", ":", "是", "为", "位于", "在")
# 分句量取只在"字段标签之后"的范围内进行（见 _consume_record_statement），这样对象名里含"在"
# 等字也不会被提前截断；"的"作为字段前修饰（"城东店的电话…"）时由对象短语一并消费。
# 允许作为句法证据的字段名：本次问题的字段标签本身，加上问句里常见的取值标签。
_REQUESTED_EVIDENCE_NAMES = frozenset({"联系电话", "电话号码", "联系号码", "联系方式"})
# R5：取值标签也必须归属到唯一字段角色。这两个标签在索引层表头映射里没有登记，
# 但语义上只属于电话角色；它们在这里登记为"别名 -> 角色"，不是拦截词黑名单。
_RECORD_EVIDENCE_ALIAS_ROLES = {"电话号码": "phone", "联系号码": "phone"}
# 位置类字段的常规句法就是"在<原值>"，允许省略字段名；其余字段只认显式字段名 + 正关系词。
_RECORD_VALUE_ONLY_ROLES = frozenset({"location"})
_RECORD_CLAUSE_SPLIT = re.compile(r"[，,；;。]")
_RECORD_IDENTIFIER_ROLE = "identifier"
_RECORD_MISSING_MARKER = "资料中未记录"
# T09-D6（R1）：真实模型会在对象名后插入"（标识：P01）"这类说明括注，再陈述字段。
# 只允许"标识/编号 + 冒号 + 取值"且取值逐字等于当前记录行同角色原值的括注；括注只是
# 对象说明，不携带新事实，也不放宽对象/字段/原值判定（伪造值、别的行、别的字段都不剥离）。
_RECORD_ANNOTATION = re.compile(r"^\(([^()]{1,64})\)")
_RECORD_ANNOTATION_SEPARATOR = ":"
_RECORD_ANNOTATION_ROLE = _RECORD_IDENTIFIER_ROLE
# 唯一允许的展示前缀（排版引导）：必须逐字是"根据资料"加一个冒号，之后的内容全部参与校验。
_RECORD_PREAMBLE = "根据资料"
MAX_RECORD_CLAUSES = 8
# 对象绑定（R3）：每条记录型分句的对象描述必须正是本问对象（门店或"门店的物品"），
# 否则该分句不属于本问事实——包括另一个门店名、未知门店前缀、更换物品或附加关系。
# 只认"与所选记录行字段原值逐字一致"的对象名，其它写法一律不接受（不做模糊/子串放宽）。
_RECORD_POSSESSIVE = ("的",)
_RECORD_OWNERSHIP_MARKERS = ("属于", "所在", "属于门店", "归属")


def _role_by_name(fields: dict) -> dict[str, str]:
    """字段名 -> 字段角色；复用索引层同一表头映射，不另写业务词典。"""
    mapping: dict[str, str] = {}
    for name in fields or {}:
        role = resolve_requested_role(str(name))
        if role:
            mapping[str(name)] = role
    return mapping


def _role_values(fields: dict) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, value in (fields or {}).items():
        if value in (None, ""):
            continue
        role = resolve_requested_role(str(name))
        if role and role not in values:
            values[role] = str(value).strip()
    return values


def _is_store_level_request(plan) -> bool:
    """只按门店问店家级字段（电话/联系人/地址/合作状态）：门店级行才是本次记录。"""
    entities = dict(getattr(plan, "entities", None) or {})
    location_only = all(resolve_requested_role(label) == "location" for label in (plan.requested_fields or ()))
    return bool(entities.get("store")) and (not entities.get("item") or location_only)


def _record_units(
    units: Iterable[object],
    plan,
    answer_facts: Iterable[tuple[str, str]] = (),
    *,
    cited: Iterable[str] | None = None,
) -> list[object]:
    """本次问题涉及的记录行：模型给出的每个字段原值都必须由这些行的原值逐字背书。

    R3 收紧：字段原值由检索层按"本次问题行"从 ``evidence.units`` 取出，所以只有行原值
    与本次问题原值逐字相等的行才有资格为回答背书；未引用行（例如同门店别的物品行、
    别的门店行）不能被拿来给回答背书。门店/物品条件命中与否只作为附加过滤，不再用
    "过滤为空就退回全部行"的兜底放宽范围。

    T09-D4（F01）：同一字段同值可能来自多条已发布来源（表格记录行 + 正文通知单元）。
    为原值背书的行必须同时是模型实际引用的来源，因此这里按 ``cited`` 收口：没被引用的行
    不进入候选，也就不能为字段原值或回显字段背书。``cited=None`` 保持"不按引用收口"的原
    行为，仅供不涉及模型引用的内部调用使用。
    """
    cited_ids = None if cited is None else {str(item) for item in cited}
    filters = dict(getattr(plan, "entities", None) or {})
    asked: set[tuple[str, str]] = set()
    for label, value in answer_facts or ():
        role = resolve_requested_role(label)
        if role:
            asked.add((role, normalize(str(value))))
    selected: list[object] = []
    for unit in units:
        if cited_ids is not None and str(getattr(unit, "id", "")) not in cited_ids:
            continue
        fields = dict(getattr(unit, "fields", None) or {})
        values = _role_values(fields)
        if filters.get("store") and values.get("store") != filters["store"]:
            continue
        if filters.get("item") and values.get("item") != filters["item"]:
            continue
        if asked:
            attested = set()
            for name, raw in fields.items():
                role = resolve_requested_role(str(name))
                if role and raw not in (None, ""):
                    attested.add((role, normalize(str(raw).strip())))
            if not asked.issubset(attested):
                continue
        selected.append(unit)
    return selected


def _row_objects(unit: object) -> tuple[set[str], set[str]]:
    """记录行自身的门店名与物品名（取自字段原值），用于分句对象绑定。"""
    values = _role_values(dict(getattr(unit, "fields", None) or {}))
    stores = {normalize(values["store"])} if values.get("store") else set()
    items = {normalize(values["item"])} if values.get("item") else set()
    return stores, items


def _object_label(plan) -> str:
    """本次问题明确的门店/物品名；仅用于识别首句描述的对象，不参与事实判定。"""
    filters = dict(getattr(plan, "entities", None) or {})
    store = filters.get("store")
    item = filters.get("item")
    if store and item:
        return f"{store}的{item}"
    return store or item or ""


def _strip_record_preamble(norm_text: str) -> str:
    """去掉精确的"根据资料："展示前缀；它只是排版引导，不改变字段事实判定。

    R4：只接受"根据资料"后紧跟一个冒号这一种前缀写法。旧实现会在前缀之后找任意冒号，
    等于把"根据资料（错误）："这类夹带内容的引导句整段丢弃——属于不校验内容即跳过，
    因此改为逐字前缀匹配。
    """
    for separator in ("：", ":"):
        token = f"{_RECORD_PREAMBLE}{separator}"
        if norm_text.startswith(token):
            return norm_text[len(token) :]
    return norm_text


def _record_label_role(label: str) -> str | None:
    """字段标签所属的字段角色。

    R5：先按索引层现有角色解析（HEADER_ROLES / resolve_requested_role），解析不到的取值
    标签只在显式别名表里归属唯一角色。标签 -> 角色没有第二种来源。
    """
    return resolve_requested_role(label) or _RECORD_EVIDENCE_ALIAS_ROLES.get(str(label).strip())


def _record_evidence_names(asked_roles: Iterable[str]) -> tuple[str, ...]:
    """允许作为句法证据的字段名：每个本次问题角色自己的表头/别名与该角色名。

    R5：字段标签必须属于所求字段角色。旧实现把所有通用取值标签（联系电话/电话号码/
    联系号码/联系方式）无条件加入每个角色，于是位置题、联系人题也能用电话标签陈述，
    再由 ``_record_answer_text`` 静默改写成正确字段。现在按角色派生：允许的标签是本角色
    的表头同义词（HEADER_ROLES）+ 角色名 + 解析到本角色的通用取值标签，因此不存在
    "任何角色都能用"的标签，正确角色的别名（如"电话号码"）仍照常可用。
    """
    roles = {role for role in (asked_roles or ()) if role}
    names: set[str] = set(roles)
    for role in roles:
        names.update(HEADER_ROLES.get(role, ()))
    for label in _REQUESTED_EVIDENCE_NAMES:
        if _record_label_role(label) in roles:
            names.add(label)
    return tuple(sorted((normalize(name) for name in names if name), key=len, reverse=True))


def _record_object_heads(units: Iterable[object], object_label: str) -> set[str]:
    """本问对象允许出现在分句开头的写法（规范化后逐字；不含空串）。

    只包含"本问门店/本问物品/本问门店的本问物品"及其"的"形式，因此另一个门店名、
    同门店其它物品、未知门店前缀都无法作为分句开头的对象描述。
    """
    stores: set[str] = set()
    items: set[str] = set()
    for unit in units:
        unit_stores, unit_items = _row_objects(unit)
        stores |= unit_stores
        items |= unit_items
    filters: dict[str, str] = {}
    if object_label:
        filters["store"], _, filters["item"] = object_label.partition("的")
    explicit_store = normalize(filters["store"]) if filters.get("store") else ""
    explicit_item = normalize(filters["item"]) if filters.get("item") else ""
    if explicit_store:
        stores.add(explicit_store)
    if explicit_item:
        items.add(explicit_item)
    heads: set[str] = set()
    for store in stores:
        heads.add(store)
        heads.add(f"{store}{_RECORD_POSSESSIVE[0]}")
        for item in items:
            heads.add(f"{store}{_RECORD_POSSESSIVE[0]}{item}")
            heads.add(f"{store}{_RECORD_POSSESSIVE[0]}{item}{_RECORD_POSSESSIVE[0]}")
    for item in items:
        heads.add(item)
        heads.add(f"{item}{_RECORD_POSSESSIVE[0]}")
    return {head for head in heads if head}


def _record_statement_bodies(norm_text: str, heads: set[str]) -> set[str]:
    """剥掉开头至多两个"本问对象"短语后剩下的候选主体（含不剥对象的原文）。

    对象短语必须是 ``heads`` 里的写法（本问门店/物品及其"的"形式），因此"城东店的错误联系电话"
    只能剩下"错误联系电话…"这一主体，不会被后续匹配跳过。对象后紧跟的"的"一并吃掉。
    """
    bodies: set[str] = {norm_text}
    for head in heads:
        if not norm_text.startswith(head):
            continue
        rest = norm_text[len(head) :]
        bodies.add(rest.lstrip())
        if rest.startswith(_RECORD_POSSESSIVE[0]):
            bodies.add(rest[1:].lstrip())
        for second in heads:
            if not rest.startswith(second):
                continue
            tail = rest[len(second) :]
            bodies.add(tail.lstrip())
            if tail.startswith(_RECORD_POSSESSIVE[0]):
                bodies.add(tail[1:].lstrip())
    return {body for body in bodies if body}


def _strip_record_annotations(body: str, unit: object) -> str | None:
    """剥离已验证的标识括注（如"（标识：P01）"），返回余下主体；无括注时原样返回。

    T09-D6（R1）：只接受 role=identifier 的字段名 + 一个冒号 + 原值，且原值必须逐字等于
    该记录行同角色的原值。伪造值、别的字段、别的行、多个取值都不剥离；残句继续参与整句
    消费，因此仍判不可验证。括注不产生任何事实，只允许出现在对象名之后、字段陈述之前。
    """
    fields = dict(getattr(unit, "fields", None) or {})
    trusted = {
        normalize(str(raw).strip())
        for name, raw in fields.items()
        if resolve_requested_role(str(name)) == _RECORD_ANNOTATION_ROLE and raw not in (None, "")
    }
    while True:
        match = _RECORD_ANNOTATION.match(body)
        if match is None:
            return body
        name, separator, raw = match.group(1).partition(_RECORD_ANNOTATION_SEPARATOR)
        value = raw.strip()
        if (
            not separator
            or resolve_requested_role(name.strip()) != _RECORD_ANNOTATION_ROLE
            or not value
            or normalize(value) not in trusted
        ):
            return body
        body = body[match.end() :].lstrip()
        if not body:
            return None


def _consume_record_statement(body: str, role: str, norm_value: str, *, unit: object) -> bool:
    """``body`` 必须被"字段标签[的]连接词 原值[允许收尾]"整体消费；返回是否消费完。

    只用前缀匹配，不做任何 find 子串查找：字段标签必须出现在主体开头，标签与值之间只能有
    一个连接词（必要时加一个"的"），值之后只能是允许的收尾。位置类字段额外允许省略标签、
    直接以"在<原值>"陈述。T09-D6（R1）：对象名之后或字段标签之后允许一个已验证的标识括注
    （"（标识：P01）"），括注由 ``_strip_record_annotations`` 按当前记录行校验后才剥离。
    """
    labels = _record_evidence_names((role,))
    if role in _RECORD_VALUE_ONLY_ROLES:
        labels = ("", *labels)
    for label in labels:
        if label and not body.startswith(label):
            continue
        rest = body[len(label) :]
        if rest.startswith(_RECORD_POSSESSIVE[0]):
            rest = rest[1:]
        rest = _strip_record_annotations(rest, unit) or ""
        for connector in _RECORD_CONNECTORS:
            if not rest.startswith(connector):
                continue
            tail = rest[len(connector) :]
            if tail.startswith(norm_value) and _only_value_tail(tail, norm_value):
                return True
    return False


def _match_record_clause(
    clause: str, units: list[object], object_label: str, asked: dict[str, str]
) -> tuple[str, str, object] | None:
    """匹配"对象 + 字段名 + 正关系词 + 原值"；只在本问记录行的原值里找，返回 (角色, 原值, 行)。

    对象绑定（R3）+ 分句完整消费（R4）：去掉精确的"根据资料："前缀后，分句开头的对象描述必须
    正是本问对象（与本次记录行字段原值逐字一致的门店名，或"门店的物品"全称、问题已明确时的
    裸物品名）；对象之后必须立刻是本次字段的标签与连接词，分句其余部分必须正好是原值。
    因此对象与字段标签之间的任何残余文字（"错误""虚假""所属的""门店"…）、字段标签的部分匹配
    或分句尾部残余都不会被跳过，而是使整句不可验证。

    T09-D6（R1）：对象名之后允许一个"（标识：X）"括注，但只在该取值逐字等于当前记录行标识
    原值时剥离（见 ``_strip_record_annotations``）；括注之外仍按上面的完整消费判定。
    """
    norm_remainder = _strip_record_preamble(normalize(clause))
    bodies = _record_statement_bodies(norm_remainder, _record_object_heads(units, object_label))
    matches: list[tuple[str, str, object]] = []
    for role, expected in asked.items():
        norm_expected = normalize(expected)
        for unit in units:
            fields = dict(getattr(unit, "fields", None) or {})
            for name, raw in fields.items():
                if resolve_requested_role(str(name)) != role:
                    continue
                value = "" if raw in (None, "") else str(raw).strip()
                if not value:
                    continue
                norm_value = normalize(value)
                if norm_value != norm_expected:
                    continue
                if not any(
                    _consume_record_statement(stripped, role, norm_value, unit=unit)
                    for body in bodies
                    for stripped in (_strip_record_annotations(body, unit),)
                    if stripped
                ):
                    continue
                matches.append((role, value, unit))
    if not matches:
        return None
    # T09-D4（F01）：同一字段的同一原值由多条已发布来源记录时（表格行 + 正文通知单元），
    # 值的含义没有歧义，歧义只在"记到哪一行"。候选行已按模型实际引用收口（见 _record_units），
    # 因此同角色同值命中多行不再整体拒绝；不同原值（含同值不同写法）仍按不可验证处理。
    if len({(role, value) for role, value, _unit in matches}) > 1:
        return None
    role, value, unit = matches[0]
    # 同一原值在该行还属于其它角色时，字段关系不可区分，拒绝而不是猜。
    fields = dict(getattr(unit, "fields", None) or {})
    for other, raw in fields.items():
        other_role = resolve_requested_role(str(other))
        if str(raw).strip() == value and other_role not in (role, None):
            return None
    return role, value, unit


def _only_value_tail(tail: str, norm_value: str) -> bool:
    """连接词之后只能是"本原值 + 允许的收尾"；出现第二个值或其它内容即拒绝。"""
    rest = tail[len(norm_value) :]
    if not rest:
        return True
    allowed_end = (".", "，", ",", "；", ";", "。", "）", ")", "。")
    if rest in allowed_end:
        return True
    # "在B区1号货架第二层里"这类地点后缀允许，但 "和…"/"以及…"/"、…" 等连接多值必须拒绝。
    if rest[0] in ("和", "及", "、", "与", "或", "，", ",", "；", ";"):
        return False
    return rest in ("里", "中", "内", "处", "上", "下") or rest.startswith("。")


def _is_explicit_missing_notice(clause: str, missing_roles: set[str]) -> bool:
    """分句是否是"资料中未记录：<本次真实缺失字段>[、…]"这一种明确结构。

    R4：旧实现只按 startswith("资料中未记录") 就跳过整句，等于任意正文都能借这个标记
    绕过校验。这里要求标记之后必须是冒号 + 若干个能解析成字段角色、且确实属于本次缺失
    字段的标签；其它任何写法都不算说明句，按不可验证处理。
    """
    body = clause[len(_RECORD_MISSING_MARKER) :].strip()
    for separator in ("：", ":"):
        if body.startswith(separator):
            body = body[len(separator) :].strip()
            break
    else:
        return False
    labels = [part.strip() for part in body.split("、") if part.strip()]
    if not labels:
        return False
    for label in labels:
        role = resolve_requested_role(label)
        if role is None or role not in missing_roles:
            return False
    return True


def _record_facts(
    text: str,
    units: Iterable[object],
    facts: list[tuple[str, str]],
    *,
    object_label: str = "",
    missing: Iterable[str] = (),
) -> list[tuple[str, str, str]] | None:
    """把记录型模型文本解析成 (字段, 原值, 行标识)；不满足结构时返回 None。"""
    rows = list(units)
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if cleaned.endswith("。"):
        cleaned = cleaned[:-1]
    clauses = [part.strip() for part in _RECORD_CLAUSE_SPLIT.split(cleaned) if part.strip()]
    if not clauses or len(clauses) > MAX_RECORD_CLAUSES:
        return None
    label_by_role: dict[str, str] = {}
    asked: dict[str, str] = {}
    for label, value in facts:
        role = resolve_requested_role(label)
        if role:
            label_by_role.setdefault(role, label)
            asked.setdefault(role, value)
    if not label_by_role:
        return None
    missing_roles = {
        role
        for role in (resolve_requested_role(str(label)) for label in (missing or ()))
        if role is not None
    }
    parsed: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for index, clause in enumerate(clauses):
        if index == 0:
            stripped = _strip_record_preamble(clause)
            if stripped != clause:
                if not stripped.strip():
                    return None  # 只有引导前缀、没有事实：不能当通过
                clause = stripped
        found = _match_record_clause(clause, rows, object_label if index == 0 else "", asked)
        if found is None:
            if _is_explicit_missing_notice(clause, missing_roles):
                continue
            # 未匹配的分句：若是"字段名：取值"且该字段不属于本次问题，则只是回显的其它字段，
            # 不据此放行任何事实；否则整段文本不可验证，直接拒绝。
            if _is_echoed_other_field(clause, rows):
                continue
            return None
        role, value, unit = found
        if role in seen:
            return None
        seen.add(role)
        parsed.append((label_by_role[role], value, str(getattr(unit, "id", ""))))
    core_roles = {role for role in label_by_role if role != _RECORD_IDENTIFIER_ROLE}
    if not core_roles or not core_roles.issubset(seen):
        return None
    return parsed


def _is_echoed_other_field(clause: str, rows: list[object]) -> bool:
    """分句是否为其它字段的回显（不属于本次问题字段），且取值与该行原值完全一致。

    - "标识：S01" 这类标识回显本身不含业务事实，允许；
    - "店家：城东店" 这类普通字段回显，取值必须逐字等于所选行的原值。
      取值不符（改写/替换/否定）的回显一律不放行。
    - 表头映射未登记角色、但确是该记录行真实字段名（如“数量”）的回显同样只按
      “字段名逐字 + 原值逐字”放行：裸门店追问题面没有显式字段词，模型常会带出同行的
      数量列；它不构成本问事实，也不进入最终展示文本（最终文本只由已校验字段重建）。
    """
    for separator in ("：", ":"):
        if separator not in clause:
            continue
        name, _sep, raw = clause.partition(separator)
        role = resolve_requested_role(name.strip())
        value = raw.strip()
        for unit in rows:
            fields = dict(getattr(unit, "fields", None) or {})
            for field_name, field_raw in fields.items():
                if role is not None:
                    if resolve_requested_role(str(field_name)) != role:
                        continue
                elif str(field_name).strip() != name.strip():
                    # 未登记角色时只认“同名字段”，不能用别的字段的原值冒充该标签。
                    continue
                if normalize(str(field_raw)) == normalize(value):
                    return True
        return False
    return False


def _validated_subject(validated: list[tuple[str, str, str]], rows: Iterable[object]) -> str:
    """被校验字段所在记录行的对象原值（不得用于给别的对象背书）。"""
    row_by_id = {str(getattr(unit, "id", "")): unit for unit in rows}
    subjects: list[str] = []
    for _label, _value, row_id in validated:
        unit = row_by_id.get(row_id)
        if unit is None:
            continue
        values = _role_values(dict(getattr(unit, "fields", None) or {}))
        store = values.get("store") or ""
        item = values.get("item") or ""
        subject = f"{store}的{item}" if store and item else (store or item)
        if subject and subject not in subjects:
            subjects.append(subject)
    return subjects[0] if len(subjects) == 1 else ""


def _subject_matches_plan(plan, subject: str) -> bool:
    """记录行对象必须与本问对象一致：门店相同；问物品时物品也必须相同。

    问的是门店级字段（电话/联系人/地址/合作状态）时物品维度不参与判定；
    问的是物品字段（位置）时，行里的物品必须是本问物品。
    """
    filters = dict(getattr(plan, "entities", None) or {})
    expected = _object_label(plan)
    if expected and normalize(expected) == normalize(subject):
        return True
    normalized = normalize(subject)
    store = normalize(filters.get("store") or "")
    if not store or not normalized.startswith(store):
        return False
    store_level = _is_store_level_request(plan)
    item = normalize(filters.get("item") or "")
    # 问的是物品字段（位置）：行的物品必须是本问物品——"门店的物品"全称或裸物品名都算，
    # 同门店其它物品（"城东店的展架"）不算。
    if item and not _is_store_level_parts(plan):
        return normalized == f"{store}{_RECORD_POSSESSIVE[0]}{item}" or normalized == item
    return True


def _is_store_level_parts(plan) -> bool:
    """按"问题字段是不是门店级字段"判定（不看物品维度，避免把位置题误判成门店题）。"""
    labels = tuple(getattr(plan, "requested_fields", None) or ())
    if not labels:
        return False
    store_level_roles = {"contact", "phone", "address", "status"}
    return all(resolve_requested_role(str(label)) in store_level_roles for label in labels)


def _record_answer_text(
    validated: list[tuple[str, str, str]],
    missing: list[str],
    rows: Iterable[object] = (),
    subject_label: str = "",
) -> str:
    """用已验证字段构造记录型展示文本：对象 + 字段 + 原值（原样取值，不改写）。

    回答以本次问题字段为主；同一记录行的其它字段以"原值回显"随行展示（如联系人），
    这些值同样直接取自该行原值而不是模型文字，便于核对同一条资料。
    缺字段时追加"资料中未记录：…"说明；模型自由文本不进入回答与历史。

    ``subject_label`` 是"被校验字段所在记录行"的门店/物品原值；它与本问对象不一致时
    （R3：例如模型把已取证值挂到另一个门店名下）调用方必须按 MODEL_OUTPUT_INVALID 处理，
    这里只负责把行对象原值交给调用方核对，绝不用本问对象去"改写"别的行的值。
    """
    prefix = subject_label
    if prefix and not prefix.endswith("的"):
        prefix = f"{prefix}的"
    asked_roles = {resolve_requested_role(label) for label, _value, _row_id in validated}
    row_by_id = {str(getattr(unit, "id", "")): unit for unit in rows}
    echo_fields: list[tuple[str, str]] = []
    seen_rows: set[str] = set()
    for _label, _value, row_id in validated:
        if row_id in seen_rows:
            continue
        seen_rows.add(row_id)
        unit = row_by_id.get(row_id)
        fields = dict(getattr(unit, "fields", None) or {}) if unit is not None else {}
        for name, raw in fields.items():
            role = resolve_requested_role(str(name))
            value = "" if raw in (None, "") else str(raw).strip()
            if role in asked_roles or role in (_RECORD_IDENTIFIER_ROLE, None) or not value:
                continue
            pair = (str(name), value)
            if pair not in echo_fields:
                echo_fields.append(pair)
    parts = [f"{label}：{value}" for label, value, _row_id in validated]
    parts.extend(f"{label}：{value}" for label, value in echo_fields)
    text = prefix + "；".join(parts)
    if missing:
        text = f"{text}；资料中未记录：" + "、".join(missing) + "。"
    else:
        text = f"{text}。"
    return text


# ---------------------------------------------------------------- T104 异常原因分类


class ModelCallFailed(ModelError):
    """T104：模型调用抛出无法归类的异常（既不是网关稳定错误，也不是超时）。

    与 ``ModelUnavailable`` 分开：真实原因无法归因（本地网关、依赖或上游都可能），
    不能冒充“供应商不可用”；按“未知”透传并允许用户稍后重试。
    """

    code = "MODEL_CALL_FAILED"
    retryable = True


#: T104：已知稳定错误码 → 产品口径的可重试性。输出校验在此按“可重试”覆盖网关里的
#: 默认 False；未登记的码值（含供应商自定义码，如 ``MODEL_POST_SEND_AUTH_DENIED``）
#: 保留网关自带的 code / retryable，不改变既有契约。
_MODEL_RETRYABLE_BY_CODE: dict[str, bool] = {
    "MODEL_NOT_CONFIGURED": False,
    "MODEL_BUDGET_REFUSED": False,
    "MODEL_TIMEOUT": True,
    "MODEL_OUTPUT_INVALID": True,
    "MODEL_UNAVAILABLE": True,
    "MODEL_CALL_FAILED": True,
}

#: T104：产品自身（非模型层）非预期异常的稳定码。与 HTTP 500 信封的 ``INTERNAL_ERROR``
#: 分名，避免把“问答编排内部错误”与“未处理路由异常”混成同一遥测口径。
QA_INTERNAL_ERROR = "QA_INTERNAL_ERROR"


def _classify_model_error(exc: ModelError) -> tuple[str, bool]:
    """按真实原因归类模型异常；未登记的码值保留网关自带码值（网关联约）。"""
    code = str(getattr(exc, "code", "") or "")
    retryable = _MODEL_RETRYABLE_BY_CODE.get(code)
    if retryable is not None:
        return code, retryable
    return code, bool(getattr(exc, "retryable", False))


async def _call_model(
    model: ModelGateway | None,
    payload: CompletionInput,
    deadline: float,
) -> CompletionOutput:
    if model is None:
        raise ModelNotConfigured()
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ModelTimeout("总预算已用尽")
    timeout = min(remaining, PER_CALL_TIMEOUT_SECONDS)
    try:
        # 同一个单调绝对 deadline 既作为单次调用预算传给网关，也作为在途等待的硬截止：
        # 网关挂起/慢响应时由这里取消并映射 MODEL_TIMEOUT，不依赖调用方的外层保护超时。
        output = await asyncio.wait_for(
            model.complete(payload, timeout_seconds=timeout), timeout=timeout
        )
    except ModelError:
        raise
    except asyncio.TimeoutError as exc:  # pragma: no cover - 由可控网关触发
        raise ModelTimeout() from exc
    except Exception as exc:  # noqa: BLE001 - 外部调用统一映射，不透传原始异常
        # T104：无法归类的调用期异常按“未知”透传；不再一律冒充 provider 不可用。
        raise ModelCallFailed(f"{type(exc).__name__}") from exc
    if monotonic() > deadline:
        raise ModelTimeout("总预算已用尽")
    return output


# ---------------------------------------------------------------- 最终提交事务


@dataclass
class _Result:
    kind: str
    text: str
    revision: int
    source_ids: tuple[str, ...] = ()
    candidates: list[CandidateView] = field(default_factory=list)
    conflicts: list[ConflictView] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    pagination: PaginationView | None = None
    error_code: str | None = None
    retryable: bool = False
    #: T003d：只在内部传递的稳定 reason（写入 Trace 供 required_spans 判定）；
    #: 不进响应体、不参与业务分支。解析级早退的取值见 contracts 的
    #: ``_LEGACY_PRE_RETRIEVAL_NOT_FOUND_REASONS``。
    reason: str | None = None


def _annotate_overshoot_fallback(*, total: int, strategy: str, term_queries: int = 0) -> None:
    """T103：把 overshoot 回落的降级事实写入既有 trace 数据字段。

    只写 ``filter_decisions_json`` 的顶层数据键（tracer 在 finish 时会保留既有键并并入
    条件 Span 属性），不新增 TraceRecord 字段、不改必需 Span 表或 outcome 枚举。
    """
    trace_attrs.annotate_trace(
        filter_decisions_json={
            "record_overshoot_fallback": True,
            "record_overshoot_total": int(total),
            "record_overshoot_strategy": strategy,
            "record_overshoot_term_queries": int(term_queries),
        }
    )


def _record_overshoot_result(
    evidence: EvidenceSet, revision: int, plan: intent_module.IntentPlan
) -> _Result:
    """记录型 overshoot：给出真实命中量 + 可点击候选/缩小方式，不再返回零候选死路。"""
    total = int(evidence.total_candidates)
    candidates = _candidate_view(plan, evidence)
    return _Result(
        kind="clarification",
        text=copy_module.record_overshoot_text(total, len(candidates)),
        revision=revision,
        candidates=candidates,
    )


def _document_overshoot_evidence(
    db_factory,
    evidence: EvidenceSet,
    intent: QueryIntent,
    revision: int,
) -> EvidenceSet:
    """正文型 overshoot：按单检索词复用 ``_retrieve`` 扩大证据面，再交既有排序取正文。

    正文检索结果按文档/序号截断；宽泛词面命中超过 100 条时，前 100 条可能压掉真正
    命中的小文档。逐词再取一次（仍走同一检索入口与同一 limit 上限）只扩大候选集合，
    不改变检索/排序语义。返回值仍标记 ``truncated``，由后续既有正文排序选取证据。
    """
    terms = tuple(intent.terms)
    _annotate_overshoot_fallback(
        total=evidence.total_candidates,
        strategy="document_term_union",
        term_queries=len(terms),
    )
    units = list(evidence.units)
    seen = {unit.id for unit in units}
    for term in terms:
        narrowed = QueryIntent(mode="document", terms=(term,), entity_filters=intent.entity_filters)
        extra = _retrieve(db_factory, narrowed, revision, limit=100)
        for unit in extra.units:
            if unit.id not in seen:
                seen.add(unit.id)
                units.append(unit)
    return EvidenceSet(
        units=units,
        kind=evidence.kind,
        total_candidates=evidence.total_candidates,
        revision=evidence.revision,
        candidates=list(evidence.candidates),
        truncated=True,
    )


def _reference_ids(result: _Result) -> list[str]:
    """本次结果需要持久化/校验的来源：普通答案的引用 + 冲突条目的各自来源。"""
    ids = list(result.source_ids)
    if result.kind == "conflict":
        for conflict in result.conflicts:
            for entry in conflict.entries:
                value = str(entry.source_id)
                if value not in ids:
                    ids.append(value)
    return ids


def _commit_result(
    db_factory,
    user: UserContext,
    claim: _Claim,
    result: _Result,
    *,
    deadline: float,
) -> AskResult:
    """短写事务提交；锁竞争只重检和重试短事务，不重发模型调用。"""
    for attempt in range(WRITE_RETRIES):
        try:
            with _commit_transaction(db_factory, deadline) as db:
                return _commit_result_impl(db, user, claim, result)
        except OperationalError as exc:
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            if attempt == WRITE_RETRIES - 1 or monotonic() > deadline:
                raise ServiceOverloaded() from None
            time.sleep(WRITE_RETRY_SLEEP * (attempt + 1))
    raise ServiceOverloaded()


def _commit_result_impl(db: Session, user: UserContext, claim: _Claim, result: _Result) -> AskResult:
    conversation = db.get(Conversation, claim.conversation_id) if claim.conversation_id else None
    if conversation is None or conversation.deleted_at is not None:
        raise RequestCancelled("会话已删除，本次回答未保存")
    if conversation.user_id != user.id:
        raise AccessDenied()
    request_row = db.get(ConversationRequest, claim.request_id, populate_existing=True)
    if request_row is None or request_row.status != "running" or int(request_row.attempt) != claim.attempt:
        raise RequestCancelled()

    current_revision = get_revision(db)
    reference_ids = _reference_ids(result)
    units: list[SourceUnit] = []
    if reference_ids:
        units = list(
            db.scalars(
                visible_source_units_stmt()
                .where(SourceUnit.id.in_([uuid.UUID(item) for item in reference_ids]))
            ).unique().all()
        )
    valid = {str(unit.id) for unit in units}
    if current_revision != claim.initial_revision or any(item not in valid for item in reference_ids):
        result = _Result(
            kind="knowledge_changed",
            text=KNOWLEDGE_CHANGED_TEXT,
            revision=current_revision,
            error_code=None,
            retryable=False,
        )
        units = []
        reference_ids = []
    elif result.kind in {"service_error", "not_found", "clarification"}:
        units = []
        reference_ids = []

    now = utcnow()
    seq = int(
        db.scalar(
            select(func.max(ConversationMessage.seq)).where(
                ConversationMessage.conversation_id == conversation.id
            )
        )
        or 0
    ) + 1
    message = ConversationMessage(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        user_id=user.id,
        seq=seq,
        role="assistant",
        text=result.text,
        kind=result.kind,
        revision=result.revision,
        error_code=result.error_code,
        missing_fields=list(result.missing_fields) or None,
        created_at=now,
    )
    db.add(message)
    db.flush()

    summaries: list[SourceSummary] = []
    allowed_ids = {str(unit.id) for unit in units}
    for source_id in reference_ids:
        if source_id not in allowed_ids:
            continue
        unit = next(item for item in units if str(item.id) == source_id)
        version = db.get(DocumentVersion, unit.version_id)
        document = db.get(Document, unit.document_id)
        if version is None or document is None:
            continue
        if status_of(document, version) != "active":
            continue
        db.add(
            MessageSource(
                id=uuid.uuid4(),
                message_id=message.id,
                source_id=unit.id,
                document_id=unit.document_id,
                version_id=unit.version_id,
                created_at=now,
            )
        )
        summaries.append(
            SourceSummary(
                source_id=unit.id,
                document_name=document.name,
                version_number=version.number,
                status="active",
                locator=unit.locator or {},
                published_at=version.published_at,
            )
        )

    ask_result = AskResult(
        request_id=claim.request_id,
        message_id=message.id,
        kind=result.kind,
        text=result.text,
        revision=result.revision,
        sources=summaries,
        candidates=result.candidates,
        conflicts=result.conflicts,
        missing_fields=result.missing_fields,
        pagination=result.pagination,
        error_code=result.error_code,
        retryable=result.retryable,
    )
    request_row.result_message_id = message.id
    request_row.result_json = ask_result.model_dump(mode="json")
    request_row.status = "succeeded"
    request_row.error_code = result.error_code
    request_row.error_retryable = result.retryable
    request_row.finished_at = now
    conversation.updated_at = now
    db.flush()
    return ask_result


def _conversation_of(db: Session, request_id: uuid.UUID) -> uuid.UUID:
    value = db.scalar(select(ConversationRequest.conversation_id).where(ConversationRequest.id == request_id))
    if value is None:
        raise RequestCancelled()
    return value


# ---------------------------------------------------------------- 问答编排


KNOWLEDGE_CHANGED_TEXT = copy_module.text("KNOWLEDGE_CHANGED")


def _current_revision(db_factory) -> int:
    db = _session_factory(db_factory)()
    try:
        return get_revision(db)
    finally:
        db.close()


def _service_error(code: str, text: str, retryable: bool, revision: int) -> _Result:
    return _Result(kind="service_error", text=text, revision=revision, error_code=code, retryable=retryable)


def _model_failure_result(exc: ModelError, revision: int) -> _Result:
    """T104：按异常真实原因返回稳定码 / 可重试性 / ERR-07 模板文案。"""
    code, retryable = _classify_model_error(exc)
    return _service_error(code, _model_error_text(code, retryable=retryable), retryable, revision)


def _internal_failure_result(revision: int) -> _Result:
    """T104：本地校验/编排抛出的非预期异常；不冒充 provider，也不回显异常文本。"""
    return _service_error(QA_INTERNAL_ERROR, _model_error_text(QA_INTERNAL_ERROR), False, revision)


#: T106：服务错误文案统一由 ``mktkb.copy`` 提供；本函数保留既有私有名，
#: 供 T104 测试与 ``model is None`` 分支继续调用。未登记码按真实 retryable
#: 选提示（T104 复核残余 5），不再固定“可稍后重新提问”。
def _model_error_text(code: str, retryable: bool | None = None) -> str:
    return copy_module.service_error_text(code, retryable=retryable)


_INDEX_NOT_READY_TEXT = copy_module.service_error_text("INDEX_NOT_READY")
_INVALID_QUERY_TEXT = copy_module.service_error_text("INVALID_QUERY")


def _merge_missing(primary: Iterable[str], secondary: Iterable[str]) -> list[str]:
    merged: list[str] = []
    for item in list(primary) + list(secondary):
        if item not in merged:
            merged.append(item)
    return merged


def _model_input(
    purpose: str,
    question: str,
    claim: _Claim,
    plan: intent_module.IntentPlan,
    units: Iterable[SourceUnit] = (),
) -> CompletionInput:
    return CompletionInput(
        purpose=purpose,  # type: ignore[arg-type]
        question=question,
        context=DialogueContext(
            questions=tuple(claim.context_questions),
            entities=dict(plan.entities or {}),
        ),
        evidence=tuple(
            ModelEvidence(source_id=str(unit.id), text=unit.text or "", fields=dict(unit.fields or {}))
            for unit in units
        ),
    )


_RAG_ENTITY_FILTERS = ("store", "item", "product", "channel", "price_type", "identifier")


def _rag_owns_turn(previous: QueryState, plan: QueryPlan) -> bool:
    """rag 内核直接作答的轮次：记录型完整枚举/分页、标识定位与澄清槽补齐（追问）。

    普通单字段/正文问题仍走既有模型措辞与事实准入，保证既有安全回归继续被真实执行；
    但检索候选与查询状态由 rag 内核提供（见 ``_answer``）。

    D-IA-1：问题显式给出标识（编号）时，rag 已有 ``identifier`` 过滤与来源机制；
    这里只负责“可达到”——不再另造编号解析器，也不用枚举/澄清轮才交给内核。
    """
    if plan.mode != "record":
        return False
    if "identifier" in plan.filters:
        return True
    if plan.clarification:
        return False
    if plan.enumerate and any(key in plan.filters for key in _RAG_ENTITY_FILTERS):
        return True
    if previous.pending_slot and not plan.state.pending_slot:
        return True
    if previous.last_kind == "ambiguous" and plan.filters:
        # 多义澄清后的选择（例如同号候选按“门店的物品”追问）继续由内核按结构化
        # 过滤收敛，避免选择后仍落在自由措辞面而无法收敛（D-IA-1）。
        return True
    return False


_RAG_KIND_MAP = {
    "answer": "answer",
    "no_answer": "not_found",
    "ambiguous": "clarification",
    "clarification": "clarification",
    "conflict": "conflict",
    "error": "service_error",
}

#: T003d：legacy 路径的产品结果 → Trace outcome（rag 路径由 ``QaEngine.answer``
#: 从 ``RagAnswer.kind`` 设置；这里只处理产品自己判定的最终结局）。
_LEGACY_OUTCOME_BY_KIND = {
    "answer": OutcomeKind.ANSWER,
    "not_found": OutcomeKind.NOT_FOUND,
    "clarification": OutcomeKind.CLARIFICATION,
    "conflict": OutcomeKind.CONFLICT,
    "service_error": OutcomeKind.SERVICE_ERROR,
    "knowledge_changed": OutcomeKind.KNOWLEDGE_CHANGED,
}


def _trace_is_legacy(trace) -> bool:
    """当前 Trace 是否为 legacy 路径（commit Span 只在 legacy 路径补，RAG 由内核产生）。"""
    path = getattr(trace, "_path", None)
    return getattr(path, "value", path) in {
        TracePath.LEGACY.value,
        TracePath.LEGACY_WITH_RAG_CANDIDATES.value,
    }


def _executed_span_names(trace) -> set[str]:
    """当前 Trace 已创建的 Span 名称（判定某阶段是否**实际执行**，不猜业务分支）。

    与 ``_trace_is_legacy`` 同口径读取 ``TraceContext`` 的只读内部状态：``tracer.py``
    属本包禁止修改文件，不新增公开 getter；结果只用于 reason-aware 判定。
    """
    names: set[str] = set()
    for handle in getattr(trace, "_spans", ()):
        name = getattr(handle, "name", None)
        if isinstance(name, str):
            names.add(name)
    return names


def _record_legacy_outcome(trace, result: _Result, ask_result: AskResult) -> None:
    """把 legacy 路径的最终产品结果写成 Trace outcome / reason / error_code。

    只写稳定代码，不写问题/答案原文；``reason`` 供 ``required_spans`` 的
    reason-aware 判定使用（§5.9 的 RAG 检索前拒答、§5.11 的 legacy 解析级早退、
    T003d R1 的 commit 阶段升级）。提交事务内可能把任意结果升级为
    ``knowledge_changed``，此时以最终结局为准。
    """
    outcome = _LEGACY_OUTCOME_BY_KIND.get(ask_result.kind)
    if outcome is None:
        return
    if ask_result.kind == "knowledge_changed":
        # T003d R1：``knowledge_changed`` 两种真实执行形态，按实际 Span 区分（不改业务分支）：
        # - 已执行 retrieve（检索阶段异常 / 检索后提交升级）→ ``KNOWLEDGE_CHANGED``，
        #   契约补充行仍要求 retrieve；
        # - 解析级早退（未执行 retrieve）在 commit 事务复核时才升级 →
        #   ``KNOWLEDGE_CHANGED_AT_COMMIT``，契约只需 intent_parse + commit。
        reason = (
            "KNOWLEDGE_CHANGED"
            if "retrieve" in _executed_span_names(trace)
            else "KNOWLEDGE_CHANGED_AT_COMMIT"
        )
    elif ask_result.kind == result.kind:
        # 未升级：解析级早退等结果自带稳定 reason；service_error 回落 error_code。
        reason = result.reason or ask_result.error_code
    else:
        reason = ask_result.error_code
    trace.set_outcome(outcome, reason)
    if ask_result.error_code:
        trace.annotate(error_code=ask_result.error_code)


def _clarification_followup(label: str, field_role: str) -> str:
    """澄清候选的追问：候选标签本身已含能收敛的门店/物品约束，再带上所问字段。

    D-IA-1：多义标识候选必须能“选择后实际收敛”，不能只回一句与约束无关的问句。
    T106：文案模板统一由 ``mktkb.copy`` 提供。
    """
    return copy_module.clarification_followup(
        label, field_role, rag_role_label(field_role) if field_role else None
    )


def _rag_turn_result(answer: RagAnswer, revision: int) -> _Result:
    """把 rag 结构化答案映射为产品六类结果；引用只用产品来源单元 ID，交给提交事务复核。"""
    kind = _RAG_KIND_MAP.get(answer.kind, "service_error")
    diagnostics = dict(answer.diagnostics or {})
    source_ids: list[str] = []
    conflicts: list[ConflictView] = []
    if kind in {"answer", "conflict"}:
        for fact in answer.facts:
            unit_id = str(fact.source_unit_id or "")
            if unit_id and unit_id not in source_ids:
                source_ids.append(unit_id)
    if kind == "conflict" and answer.facts:
        entries: list[ConflictEntry] = []
        seen: set[tuple[str, str]] = set()
        for fact in answer.facts:
            key = (str(fact.value), str(fact.source_unit_id))
            if key in seen:
                continue
            seen.add(key)
            try:
                source_uuid = uuid.UUID(str(fact.source_unit_id))
            except (TypeError, ValueError):
                continue
            entries.append(ConflictEntry(value=str(fact.value), source_id=source_uuid))
        if entries:
            conflicts = [
                ConflictView(field=str(answer.facts[0].field_label or "值"), entries=entries)
            ]
    candidates: list[CandidateView] = []
    if kind == "clarification":
        state = dict(answer.state or {})
        field_role = str(state.get("field_role") or "")
        for label in state.get("candidates") or ():
            candidates.append(
                CandidateView(
                    label=str(label),
                    followup_question=_clarification_followup(str(label), field_role),
                )
            )
    pagination: PaginationView | None = None
    if kind == "answer" and (
        answer.answer_source == "structured_enumeration" or diagnostics.get("enumeration")
    ):
        pagination = PaginationView(
            page=max(1, int(diagnostics.get("page") or 1)),
            page_size=max(1, int(diagnostics.get("page_size") or 1)),
            total=max(0, int(diagnostics.get("total") or 0)),
            returned=max(0, int(diagnostics.get("returned") or 0)),
            has_more=bool(diagnostics.get("has_more")),
            next_page=diagnostics.get("next_page"),
        )
    error_code = None
    retryable = False
    if kind == "service_error":
        reason = str(answer.reason or "")
        error_code = "INDEX_NOT_READY" if "NOT_READY" in reason else "RETRIEVAL_ERROR"
        retryable = True
    return _Result(
        kind=kind,
        text=answer.text,
        revision=revision,
        source_ids=tuple(source_ids),
        candidates=candidates,
        conflicts=conflicts,
        pagination=pagination,
        error_code=error_code,
        retryable=retryable,
    )


async def _answer(
    db_factory,
    user: UserContext,
    claim: _Claim,
    question: str,
    model: ModelGateway | None,
    deadline: float,
    *,
    qa=None,
) -> _Result:
    revision = claim.initial_revision
    # T003d：埋点全部以 current_trace() 为 None 时 no-op；不新建 Trace、不改控制流。
    trace = current_trace()
    rag_candidates: set[str] | None = None
    rag_plan: QueryPlan | None = None
    if qa is not None:
        try:
            rag_previous, rag_plan = qa.prepare(question, str(user.id), str(claim.conversation_id))
        except QaNotReady as exc:
            return _service_error(
                "INDEX_NOT_READY",
                _INDEX_NOT_READY_TEXT,
                True,
                revision,
            )
        except Exception:  # noqa: BLE001 - 索引层稳定错误不把内部细节暴露给用户
            return _service_error(
                "INDEX_NOT_READY",
                _INDEX_NOT_READY_TEXT,
                True,
                revision,
            )
        if _rag_owns_turn(rag_previous, rag_plan):
            if trace is not None:
                trace.set_path(TracePath.RAG)
            try:
                rag_answer = qa.answer(question, str(user.id), str(claim.conversation_id))
            except RagKnowledgeChanged:
                if trace is not None:
                    trace.set_outcome(OutcomeKind.KNOWLEDGE_CHANGED, "KNOWLEDGE_CHANGED")
                return _Result(
                    kind="knowledge_changed",
                    text=KNOWLEDGE_CHANGED_TEXT,
                    revision=_current_revision(db_factory),
                )
            except QaNotReady:
                return _service_error(
                    "INDEX_NOT_READY", _INDEX_NOT_READY_TEXT, True, revision
                )
            # outcome 由 QaEngine.answer 按 RagAnswer.kind 设置（reason 一并写入）。
            return _rag_turn_result(rag_answer, revision)
        # 非 rag 直接作答的轮次也推进查询状态：澄清槽/话题切换/实体继承由 rag 状态机维护。
        try:
            qa.save_state(rag_plan.state)
        except Exception:  # noqa: BLE001 - 状态写失败不应改变既有问答结果
            pass

    if trace is not None:
        trace.set_path(TracePath.LEGACY)

    with trace_attrs.span("intent_parse") as intent_span:
        with _read_session(db_factory) as db:
            lexicon = intent_module.load_lexicon(db)
            plan = intent_module.parse_question(
                question,
                lexicon=lexicon,
                context_entities=claim.context_entities,
                context_questions=claim.context_questions,
            )
        intent_span.annotate(
            mode=plan.mode,
            has_intent=plan.intent is not None,
            clarification=bool(plan.clarification),
            requested_fields=len(plan.requested_fields),
        )
    if plan.unknown_identifier:
        return _Result(
            kind="not_found",
            text=copy_module.text(
                "UNKNOWN_IDENTIFIER", identifier=plan.unknown_identifier
            ),
            revision=revision,
            reason="UNKNOWN_IDENTIFIER",
        )
    if plan.identifier:
        # D-IA-1：标识只能由 rag 内核的 identifier 过滤定位（产品检索层没有标识筛选键，
        # 强行下发会被拒绝或退化成未受限检索）。内核没有接手时一律失败关闭，
        # 不允许拿同门店/同物品的其它行当答案。
        return _Result(
            kind="not_found",
            text=copy_module.text(
                "IDENTIFIER_NOT_RETRIEVABLE", identifier=plan.identifier
            ),
            revision=revision,
            reason="IDENTIFIER_NOT_RETRIEVABLE",
        )
    if plan.clarification:
        return _Result(
            kind="clarification",
            text=plan.clarification,
            revision=revision,
            candidates=[CandidateView(label=label, followup_question=followup) for label, followup in plan.candidates],
            missing_fields=list(plan.missing_fields),
        )
    if plan.intent is None:
        return _Result(
            kind="not_found",
            text=copy_module.text("NO_INTENT"),
            revision=revision,
            reason="NO_INTENT",
        )
    if not plan.requested_fields and plan.missing_fields:
        return _Result(
            kind="not_found",
            text=copy_module.text(
                "UNRECORDED_FIELD", subject="：" + "、".join(plan.missing_fields)
            ),
            revision=revision,
            missing_fields=list(plan.missing_fields),
            reason="UNRECORDED_FIELD",
        )

    # 记录型问题的证据候选由 rag 索引提供（与 product revision 对齐后才给候选）；
    # 正文型问题保持既有 FTS 证据面，避免离线向量召回把“无依据”问题变成可答。
    if qa is not None and rag_plan is not None and plan.intent.mode == "record":
        try:
            rag_candidates = qa.candidate_unit_ids_for_intent(
                mode="record",
                terms=plan.intent.terms,
                entity_filters=plan.intent.entity_filters,
            )
            if trace is not None and rag_candidates:
                # 实际拿到 rag 候选后才记 legacy_with_rag_candidates；空候选仍是纯 legacy。
                trace.set_path(TracePath.LEGACY_WITH_RAG_CANDIDATES)
        except QaNotReady:
            return _service_error("INDEX_NOT_READY", _INDEX_NOT_READY_TEXT, True, revision)
        except Exception:  # noqa: BLE001 - 稳定错误，不暴露内部细节
            return _service_error("INDEX_NOT_READY", _INDEX_NOT_READY_TEXT, True, revision)

    def _evidence(intent: QueryIntent, limit: int = 20) -> EvidenceSet:
        with trace_attrs.span("retrieve", limit=limit):
            return _retrieve(db_factory, intent, revision, limit=limit, candidate_ids=rag_candidates)

    evidence: EvidenceSet | None = None
    extra_terms: tuple[str, ...] = ()
    try:
        evidence = _evidence(plan.intent, 20)
        if evidence.truncated:
            evidence = _evidence(plan.intent, 100)
            if evidence.truncated:
                if plan.intent.mode == "record":
                    _annotate_overshoot_fallback(
                        total=evidence.total_candidates, strategy="record_candidates"
                    )
                    return _record_overshoot_result(evidence, revision, plan)
                evidence = _document_overshoot_evidence(db_factory, evidence, plan.intent, revision)
    except KnowledgeRevisionChanged:
        return _Result(kind="knowledge_changed", text=KNOWLEDGE_CHANGED_TEXT, revision=_current_revision(db_factory))
    except IndexNotReady:
        return _service_error("INDEX_NOT_READY", _INDEX_NOT_READY_TEXT, True, revision)
    except QueryRejected:
        return _service_error("INVALID_QUERY", _INVALID_QUERY_TEXT, False, revision)

    if evidence.kind == "none" and plan.intent.terms and model is not None:
        # 只有真正触发扩展调用时才置条件属性并创建 query_expansion Span（不伪造）。
        trace_attrs.annotate_trace(expansion_triggered=True)
        try:
            with trace_attrs.span("query_expansion") as expansion_span:
                output = await _call_model(
                    model, _model_input("query_expansion", question, claim, plan), deadline
                )
                terms = _validate_terms(output)
                expansion_span.annotate(terms=len(terms))
        except ModelError as exc:
            return _model_failure_result(exc, revision)
        except Exception:  # noqa: BLE001 - T104：本地校验/编排异常按“内部”透传
            return _internal_failure_result(revision)
        if terms:
            extra_terms = terms
            expanded = QueryIntent(
                mode=plan.intent.mode,
                terms=plan.intent.terms + terms,
                entity_filters=plan.entities,
            )
            try:
                evidence = _evidence(expanded, 20)
                if evidence.truncated:
                    evidence = _evidence(expanded, 100)
                    if evidence.truncated:
                        if expanded.mode == "record":
                            _annotate_overshoot_fallback(
                                total=evidence.total_candidates, strategy="record_candidates"
                            )
                            return _record_overshoot_result(evidence, revision, plan)
                        evidence = _document_overshoot_evidence(
                            db_factory, evidence, expanded, revision
                        )
            except KnowledgeRevisionChanged:
                return _Result(
                    kind="knowledge_changed", text=KNOWLEDGE_CHANGED_TEXT, revision=_current_revision(db_factory)
                )
            except IndexNotReady:
                return _service_error("INDEX_NOT_READY", _INDEX_NOT_READY_TEXT, True, revision)
            except QueryRejected:
                return _service_error("INVALID_QUERY", _INVALID_QUERY_TEXT, False, revision)

    if evidence.kind == "none":
        if plan.unknown_store:
            text = copy_module.text("LEGACY_UNKNOWN_STORE", store=plan.unknown_store)
        elif plan.missing_fields:
            text = copy_module.text(
                "UNRECORDED_FIELD", subject="：" + "、".join(plan.missing_fields)
            )
        else:
            text = copy_module.text("LEGACY_NO_EVIDENCE")
        return _Result(
            kind="not_found", text=text, revision=revision, missing_fields=list(plan.missing_fields)
        )

    if evidence.kind == "ambiguous":
        candidates = _candidate_view(plan, evidence)
        return _Result(
            kind="clarification",
            text=copy_module.text("LEGACY_MULTIPLE_ENTITIES"),
            revision=revision,
            candidates=candidates,
        )

    if evidence.kind == "conflict":
        conflicts = _conflict_views(evidence.units, plan.requested_fields)
        if not conflicts:
            return _Result(
                kind="clarification",
                text=copy_module.text("CLARIFICATION_REQUIRED"),
                revision=revision,
                candidates=_candidate_view(plan, evidence),
            )
        fields_text = "、".join(conflict.field for conflict in conflicts)
        return _Result(
            kind="conflict",
            text=copy_module.legacy_conflict_text(fields_text),
            revision=revision,
            conflicts=conflicts,
            reason="CONFLICTING_VALUES",
        )

    if plan.mode == "record":
        facts, field_missing = _facts(evidence.units, plan.requested_fields)
        missing = _merge_missing(plan.missing_fields, field_missing)
        units = list(evidence.units)
        if not facts:
            if missing:
                text = copy_module.field_not_recorded_text(
                    "：" + "、".join(missing)
                )
            else:
                text = copy_module.text("LEGACY_NO_EVIDENCE")
            return _Result(kind="not_found", text=text, revision=revision, missing_fields=missing)
    else:
        units = _rank_document_units(question, list(evidence.units), extra_terms=extra_terms)
        facts = []
        missing = list(plan.missing_fields)
        if not units:
            return _Result(
                kind="not_found",
                text=copy_module.text("LEGACY_NO_EVIDENCE"),
                revision=revision,
            )

    if model is None:
        return _service_error(
            "MODEL_NOT_CONFIGURED", _model_error_text("MODEL_NOT_CONFIGURED"), False, revision
        )

    allowed = {str(unit.id) for unit in units}
    try:
        with trace_attrs.span("model_answer"):
            output = await _call_model(
                model, _model_input("answer", question, claim, plan, units), deadline
            )
        with trace_attrs.span("answer_validate") as validate_span:
            if plan.mode == "record":
                text, source_ids = _validate_answer(output, allowed, facts)
            else:
                # CD-F1：非记录型（正文/清单）回答同样要求数据型 token 由本次实际引用的来源背书，
                # 并且明确单门店问题不得混入其它已知门店的事实（门店作用域只在锁定单店时生效）。
                # 记录型仍走下面更严的 _record_facts 路径，既不共用本分支也不放宽。
                text, source_ids = _validate_answer(
                    output,
                    allowed,
                    facts,
                    evidence=units,
                    # CD-F1-R1：门店豁免集延后到 ids 校验后按实际引用计算，不再按全部候选。
                    store_scope=(plan, lexicon),
                )
            missing_rows: list[str] = []
            if plan.mode == "record":
                # 记录型事实准入：模型文本必须是可逐句验证的"对象=本问对象、字段=原值"陈述，
                # 否则按 MODEL_OUTPUT_INVALID 处理；通过后再用代码按这些已验证字段构造展示文本，
                # 使保存的回答不再含未经校验的自由文本。
                record_rows = _record_units(units, plan, facts, cited=source_ids)
                validated = _record_facts(
                    text, record_rows, facts, object_label=_object_label(plan), missing=missing
                )
                if not validated:
                    # 不给原始模型文本加调试输出；仅在进程内提示可定位的拒绝原因。
                    raise ModelOutputInvalid("记录型回答不是可验证的字段事实陈述")
                cited = {row_id for _label, _value, row_id in validated}
                # 引用收口：为字段原值背书的行必须都在模型实际引用的来源里；否则等于"引用一行、
                # 用未引用行的值"作答，按不可验证处理。
                if not cited.issubset(set(source_ids)):
                    raise ModelOutputInvalid("回答字段原值未由被引用来源背书")
                # 对象绑定：被校验字段所在行的门店/物品原值必须就是本问对象（不做静默改写）。
                subject = _validated_subject(validated, record_rows)
                if subject and not _subject_matches_plan(plan, subject):
                    raise ModelOutputInvalid("回答字段原值属于其它对象")
                missing_rows = [label for label in missing if label not in {item[0] for item in validated}]
                text = _record_answer_text(validated, missing_rows, record_rows, subject_label=subject)
                source_ids = [item for item in source_ids if item in cited]
            validate_span.annotate(mode=plan.mode, cited=len(source_ids), missing=len(missing_rows))
    except ModelError as exc:
        return _model_failure_result(exc, revision)
    except Exception:  # noqa: BLE001 - T104：本地校验/编排异常按“内部”透传
        return _internal_failure_result(revision)

    return _Result(
        kind="answer",
        text=text,
        revision=revision,
        source_ids=tuple(source_ids),
        missing_fields=missing,
    )


async def ask(
    db_factory,
    user: UserContext,
    conversation_id: uuid.UUID,
    request,
    *,
    model: ModelGateway | None,
    qa=None,
) -> AskResult:
    """HTTP 问答入口：领取 -> 取证/模型 -> 同一短事务提交。"""
    deadline = monotonic() + BUDGET_SECONDS
    deadline_at = wall_clock() + timedelta(seconds=BUDGET_SECONDS)
    claim = _claim(
        db_factory,
        user,
        conversation_id,
        request.client_request_id,
        request.question,
        payload_digest(request.question),
        deadline_at,
    )
    # T003d：request_id 是产品请求 ID（ConversationRequest.id）；question 只进内存，
    # finish 时按 content_mode 转摘要/长度。当前无 Trace 时全部 no-op。
    trace = current_trace()
    if trace is not None:
        trace.set_request_id(str(claim.request_id))
        trace.set_question(request.question)
    if claim.replay is not None:
        if trace is not None:
            # 幂等重放没有真实执行：status=replayed、Span 为空，不覆盖历史（设计 §6.1）。
            trace.annotate(replayed=True)
        return claim.replay
    result = await _answer(db_factory, user, claim, request.question, model, deadline, qa=qa)
    if trace is not None and _trace_is_legacy(trace):
        # legacy 路径的产品提交阶段（RAG 路径的 commit 由 rag 内核产生）。
        with trace.span("commit"):
            ask_result = _commit_result(db_factory, user, claim, result, deadline=deadline)
        _record_legacy_outcome(trace, result, ask_result)
        return ask_result
    ask_result = _commit_result(db_factory, user, claim, result, deadline=deadline)
    if trace is not None and ask_result.kind == "knowledge_changed":
        # 提交事务内的 revision 复核可能把任意结果升级为 knowledge_changed；以最终结局为准。
        trace.set_outcome(OutcomeKind.KNOWLEDGE_CHANGED, "KNOWLEDGE_CHANGED")
    return ask_result

