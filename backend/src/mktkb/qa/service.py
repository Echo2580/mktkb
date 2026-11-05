"""S2 产品问答内核：把隔离 RAG 索引接入产品 HTTP 问答与持久查询状态。

边界（与任务的 S2 要求一一对应）：
- 索引来源只用产品自己的发布可见面：``visible_source_units_stmt()``（未删除资料 + 当前有效版本 +
  ``published``）。资料发布/替换/删除后，索引同步由产品生命周期与启动配置驱动；
- 索引元数据记录产品 ``KnowledgeState.revision`` 与清单摘要。revision 不一致时先同步；同步失败
  会写明确的 error 状态并抛 :class:`QaNotReady`，查询入口返回可重试的 ``INDEX_NOT_READY``，
  不允许静默继续使用旧索引；
- 查询状态按 ``(user_id, conversation_id)`` 持久在索引库，用户隔离与产品会话隔离一致；
- 供应商只允许 offline 确定性替身或显式 live 预算账本入口。离线模式不产生任何真实调用；
  live 模式必须显式给出账本/预算/阶段额度/请求上限，缺一不可，默认拒绝。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import select

from ..documents.lifecycle import get_revision, visible_source_units_stmt
from ..documents.models import Document, DocumentVersion, SourceUnit
from ..observability import trace_attrs
from ..observability.tracer import current_trace
from ..rag import DocumentSpec, RagConfig, RagIndex, safe_config_summary
from ..rag.chunking import adapt_parsed_unit
from ..rag.errors import KnowledgeChanged, RagError
from ..rag.query import QueryPlan, build_lexicon, parse_query
from ..rag.types import AtomicUnit, QueryState, RagAnswer, RetrievalResult

QA_ENGINE_VERSION = "s2-a-1"
_META_REVISION = "product_revision"
_META_DIGEST = "product_manifest_sha256"
_META_STATUS = "product_sync_status"
_META_ERROR_CODE = "product_sync_error_code"
_META_ERROR = "product_sync_error"
_META_SYNCED_AT = "product_synced_at"
_META_ENGINE = "qa_engine_version"
_META_PROVIDER = "provider_mode"
_META_DOCUMENTS = "product_documents"
_META_UNITS = "product_units"


class QaNotReady(Exception):
    """索引不可用/未同步；调用方必须向用户返回明确的可重试错误，不得用旧索引作答。"""

    code = "INDEX_NOT_READY"

    def __init__(self, message: str = "检索索引暂不可用", *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code or self.code


@dataclass(frozen=True)
class QaIndexStatus:
    ready: bool
    product_revision: int | None
    index_revision: int
    documents: int
    units: int
    chunks: int
    provider_mode: str
    degraded: tuple[str, ...] = ()
    error_code: str | None = None
    error: str | None = None
    synced_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "product_revision": self.product_revision,
            "index_revision": self.index_revision,
            "documents": self.documents,
            "units": self.units,
            "chunks": self.chunks,
            "provider_mode": self.provider_mode,
            "degraded": list(self.degraded),
            "error_code": self.error_code,
            "error": self.error,
            "synced_at": self.synced_at,
        }


@dataclass
class _Manifest:
    revision: int
    documents: dict[str, tuple[DocumentSpec, list[AtomicUnit]]]
    digest: str
    unit_count: int


class _IndexLock:
    """跨进程文件锁：O_EXCL + 有界等待 + 陈旧锁按 mtime 回收；不依赖额外依赖。"""

    def __init__(self, path: Path, *, timeout_seconds: float = 30.0, stale_seconds: float = 120.0) -> None:
        self.path = path
        self.timeout_seconds = float(timeout_seconds)
        self.stale_seconds = float(stale_seconds)
        self._fd: int | None = None

    def __enter__(self) -> "_IndexLock":
        deadline = time.monotonic() + self.timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, f"{os.getpid()}:{time.time():.6f}".encode("ascii"))
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > self.stale_seconds:
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() > deadline:
                    raise QaNotReady("索引同步等待超时", error_code="INDEX_SYNC_LOCK_TIMEOUT") from None
                time.sleep(0.05)

    def __exit__(self, *_exc: object) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class QaEngine:
    """产品侧 rag 索引入口。构造不打开数据库；首次使用才建索引文件（initialize=False 不写目录）。"""

    def __init__(
        self,
        db_factory: Any,
        index_path: Path | str,
        *,
        config: RagConfig | None = None,
        embedder: Any | None = None,
        reranker: Any | None = None,
        budget: Any | None = None,
        embedding_retry_seconds: float = 30.0,
    ) -> None:
        self.db_factory = db_factory
        self.index_path = Path(index_path)
        self.config = config or RagConfig(provider_mode="offline", data_dir=self.index_path.parent)
        self._embedder = embedder
        self._reranker = reranker
        self._budget = budget
        self._index: RagIndex | None = None
        self._index_lock = threading.Lock()
        self._sync_lock = _IndexLock(
            self.index_path.with_name(self.index_path.name + ".sync.lock")
        )
        self.embedding_retry_seconds = max(0.0, float(embedding_retry_seconds))
        self._last_attempt: float = 0.0

    # ---------------------------------------------------------------- 生命周期

    def _session_factory(self):
        session_method = getattr(self.db_factory, "session", None)
        if session_method is None:
            raise TypeError("QaEngine 需要产品 Database（含 session()）")
        return session_method

    def index(self) -> RagIndex:
        if self._index is None:
            with self._index_lock:
                if self._index is None:
                    self.index_path.parent.mkdir(parents=True, exist_ok=True)
                    self._index = RagIndex(
                        self.index_path,
                        config=self.config,
                        embedder=self._embedder,
                        reranker=self._reranker,
                        budget=self._budget,
                    )
        return self._index

    def close(self) -> None:
        with self._index_lock:
            if self._index is not None:
                self._index.close()
                self._index = None

    def product_revision(self) -> int:
        db = self._session_factory()()
        try:
            return int(get_revision(db))
        finally:
            db.close()

    def _read_manifest(self) -> _Manifest:
        """只读产品可见面，返回 DocumentSpec/AtomicUnit 清单与摘要。"""
        db = self._session_factory()()
        try:
            revision = int(get_revision(db))
            pairs = db.execute(
                select(Document, DocumentVersion)
                .join(DocumentVersion, DocumentVersion.id == Document.active_version_id)
                .where(Document.deleted.is_(False), DocumentVersion.state == "published")
                .order_by(Document.id)
            ).all()
            documents: dict[str, tuple[DocumentSpec, list[AtomicUnit]]] = {}
            digest = hashlib.sha256()
            unit_count = 0
            for document, version in pairs:
                doc_id = str(document.id)
                spec = DocumentSpec(
                    doc_id=doc_id,
                    logical_id=doc_id,
                    source_path=version.stored_path,
                    title=document.name,
                    file_kind=document.file_type,
                    version_id=str(version.id),
                    version_label=f"v{version.number}",
                    sha256=version.sha256,
                    state="active",
                    is_current=True,
                    business_date=None,
                    metadata={"product_document_id": doc_id, "product_version_id": str(version.id)},
                )
                units = [
                    adapt_parsed_unit(unit, doc=spec)
                    for unit in db.scalars(
                        visible_source_units_stmt()
                        .where(SourceUnit.version_id == version.id)
                        .order_by(SourceUnit.ordinal)
                    ).unique()
                ]
                documents[doc_id] = (spec, units)
                digest.update(f"{doc_id}|{version.id}|{len(units)}".encode("utf-8"))
                for unit in units:
                    digest.update(f"|{unit.unit_id}|{unit.ordinal}".encode("utf-8"))
                unit_count += len(units)
            return _Manifest(revision=revision, documents=documents, digest=digest.hexdigest(), unit_count=unit_count)
        finally:
            db.close()

    def _status_from_meta(self, *, ready: bool | None = None) -> QaIndexStatus:
        index = self.index()
        current = self.product_revision()
        stored = index.get_meta(_META_REVISION)
        status = index.get_meta(_META_STATUS) or "missing"
        documents = int(index.get_meta(_META_DOCUMENTS) or 0)
        units = int(index.get_meta(_META_UNITS) or 0)
        stats = index.stats()
        error_code = index.get_meta(_META_ERROR_CODE)
        error = index.get_meta(_META_ERROR)
        synced_at = index.get_meta(_META_SYNCED_AT)
        is_ready = ready if ready is not None else (
            stored == str(current) and status in {"ready", "degraded"}
        )
        return QaIndexStatus(
            ready=bool(is_ready),
            product_revision=int(stored) if stored and stored.isdigit() else None,
            index_revision=int(stats["revision"]),
            documents=documents,
            units=units,
            chunks=int(stats["chunks"]),
            provider_mode=self.config.provider_mode,
            degraded=("embedding_error",) if status == "degraded" else (),
            error_code=error_code,
            error=error,
            synced_at=synced_at,
        )

    def ensure_ready(self, *, force: bool = False) -> QaIndexStatus:
        """保证索引对应当前产品 revision；不一致先同步，失败显式抛错。"""
        index = self.index()
        current = self.product_revision()
        stored = index.get_meta(_META_REVISION)
        status = index.get_meta(_META_STATUS)
        if not force and stored == str(current) and status in {"ready", "degraded"}:
            if status == "degraded":
                # 降级状态显式暴露；只有超过重试间隔才重新同步补齐向量，避免每次提问都重试。
                # S2-H：要求零自动重试的真实 smoke 下，降级后再同步本身就是重发失败请求，
                # 必须在任何供应商请求之前终止本轮，而不是等间隔到期后自行重试。
                if getattr(self.config, "require_zero_retries", False):
                    raise QaNotReady(
                        "索引向量层已降级且要求零自动重试，本轮不再向供应商重发",
                        error_code="EMBEDDING_DEGRADED_NO_RETRY",
                    )
                last = self._last_attempt
                if self.embedding_retry_seconds > 0 and time.monotonic() - last < self.embedding_retry_seconds:
                    return self._status_from_meta(ready=True)
            else:
                return self._status_from_meta(ready=True)
        return self.sync(force=force)

    def sync(self, *, force: bool = False) -> QaIndexStatus:
        """按产品可见面增量同步索引；失败写 error 元数据并抛 QaNotReady。

        T003d：只有真正执行同步（``ensure_ready`` 未命中已就绪缓存 / 启动同步 /
        发布钩子）时才创建 ``index_sync`` Span 并置 ``index_sync_performed=true``；
        命中缓存直接返回时不会进入本方法，因此不会伪造该条件 Span。
        """
        trace_attrs.annotate_trace(index_sync_performed=True)
        with trace_attrs.span("index_sync"):
            return self._sync(force=force)

    def _sync(self, *, force: bool = False) -> QaIndexStatus:
        index = self.index()
        with self._sync_lock:
            self._last_attempt = time.monotonic()
            try:
                manifest = self._read_manifest()
                existing = {item["doc_id"]: item for item in index.list_documents()}
                # 1) 删除不再可见/版本已变化的文档
                for doc_id, item in existing.items():
                    target = manifest.documents.get(doc_id)
                    if target is None or target[0].version_id != item["version_id"]:
                        index.remove_document(doc_id)
                # 2) 写入缺失/变更的当前版本（同 doc_id 内部按版本替换）
                degraded: list[str] = []
                error_code: str | None = None
                for doc_id, (spec, units) in manifest.documents.items():
                    previous = existing.get(doc_id)
                    if previous is not None and previous["version_id"] == spec.version_id:
                        # 已同步过的文档：补缺失的向量映射（上次 provider 失败后的重试路径）。
                        try:
                            index.ensure_embeddings(doc_id)
                        except Exception as exc:  # noqa: BLE001 - 供应商错误只降级记录层
                            degraded.append("embedding_error")
                            error_code = getattr(exc, "code", type(exc).__name__)
                        continue
                    result = index.add_document(spec, units, embed=True)
                    if result.get("embedding_error"):
                        degraded.append("embedding_error")
                        error_code = str(result["embedding_error"])
                # 3) 同步期间产品 revision 又变化：不标记 ready，交由下一次查询重试
                current = self.product_revision()
                if current != manifest.revision:
                    index.set_meta(
                        {
                            _META_STATUS: "stale",
                            _META_ERROR_CODE: "KNOWLEDGE_CHANGED_DURING_SYNC",
                            _META_ERROR: "同步期间知识库 revision 发生变化，未标记就绪",
                        }
                    )
                    raise QaNotReady("同步期间知识库发生变化，请重试", error_code="KNOWLEDGE_CHANGED_DURING_SYNC")
                status = "degraded" if degraded else "ready"
                index.set_meta(
                    {
                        _META_REVISION: str(manifest.revision),
                        _META_DIGEST: manifest.digest,
                        _META_STATUS: status,
                        _META_ERROR_CODE: error_code,
                        _META_ERROR: None if error_code is None else "向量层暂不可用，记录型/精确层仍可用",
                        _META_SYNCED_AT: datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        _META_ENGINE: QA_ENGINE_VERSION,
                        _META_PROVIDER: self.config.provider_mode,
                        _META_DOCUMENTS: str(len(manifest.documents)),
                        _META_UNITS: str(manifest.unit_count),
                    }
                )
                return self._status_from_meta(ready=True)
            except QaNotReady:
                raise
            except RagError as exc:
                self._record_error(getattr(exc, "code", type(exc).__name__), exc)
                raise QaNotReady(getattr(exc, "message", str(exc)), error_code=getattr(exc, "code", None)) from exc
            except Exception as exc:  # noqa: BLE001 - 稳定错误，不泄露路径/堆栈
                self._record_error(type(exc).__name__, exc)
                raise QaNotReady("索引同步失败", error_code=type(exc).__name__) from None

    def _record_error(self, code: str, exc: Exception) -> None:
        try:
            self.index().set_meta(
                {
                    _META_STATUS: "error",
                    _META_ERROR_CODE: code,
                    _META_ERROR: f"{code}: {type(exc).__name__}",
                    _META_SYNCED_AT: datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            )
        except Exception:  # noqa: BLE001 - 记录状态失败不覆盖原始错误
            pass

    def notify_knowledge_changed(self) -> QaIndexStatus | None:
        """发布/删除/替换后的生命周期钩子：同步失败只记录状态，由后续查询返回明确错误。"""
        try:
            return self.sync()
        except QaNotReady:
            return None

    # ---------------------------------------------------------------- 查询状态

    def load_state(self, user_id: str, conversation_id: str) -> QueryState:
        return self.index().load_state(str(user_id), str(conversation_id))

    def save_state(self, state: QueryState) -> None:
        self.index().save_state(state)

    def clear_state(self, user_id: str, conversation_id: str) -> None:
        self.index().clear_state(str(user_id), str(conversation_id))

    def prepare(self, question: str, user_id: str, conversation_id: str) -> tuple[QueryState, QueryPlan]:
        """解析问题（带持久状态）并返回 (上一轮状态, 本轮计划)；不写状态。"""
        self.ensure_ready()
        previous = self.load_state(user_id, conversation_id)
        plan = parse_query(
            question,
            previous=previous,
            lexicon=build_lexicon(self.index().lexicon_data()),
            business_date=self.config.business_date,
            page_size=self.config.page_size,
        )
        plan.state.user_id = str(user_id)
        plan.state.conversation_id = str(conversation_id)
        return previous, plan

    def answer(self, question: str, user_id: str, conversation_id: str, *, limit: int | None = None) -> RagAnswer:
        """执行一次 RAG 直答；不新建 Trace，只在已有 Trace 上写 outcome/reason。

        T003d：``path`` 由调用方（``conversations._answer``）按 ``_rag_owns_turn`` 设置；
        这里把 ``RagAnswer.kind``（与 ``OutcomeKind`` 同值）映射为 outcome，``reason``
        交给 ``required_spans`` 识别“检索前拒答”的 reason-aware 例外（§5.9）。
        ``current_trace()`` 为 None 时全部 no-op。
        """
        self.ensure_ready()
        result = self.index().ask(
            question, user_id=str(user_id), conversation_id=str(conversation_id), limit=limit
        )
        trace = current_trace()
        if trace is not None:
            trace.set_outcome(result.kind, result.reason)
        return result

    def search(self, plan: QueryPlan, *, limit: int | None = None) -> RetrievalResult:
        self.ensure_ready()
        return self.index().search(plan, limit=limit)

    def candidate_unit_ids_for_intent(
        self, *, mode: str, terms: Iterable[str] = (), entity_filters: Mapping[str, str] | None = None
    ) -> set[str]:
        """按产品既有意图（实体条件/检索词）取 rag 召回候选，不继承 rag 状态。

        产品对话上下文由产品自己的 ``context_entities`` 决定；rag 持久状态只负责枚举/分页/
        澄清槽。两者刻意分开，避免把上一轮失败请求的实体继承进本轮候选。
        """
        filters = {
            key: str(value)
            for key, value in dict(entity_filters or {}).items()
            if key in ("store", "item", "product", "channel", "price_type", "identifier")
        }
        term_tuple = tuple(str(term) for term in terms)
        query_text = " ".join([*term_tuple, *filters.values()]).strip() or "查询"
        plan = QueryPlan(
            question=query_text,
            mode=mode,
            query_text=query_text,
            field_role=None,
            field_label=None,
            filters=filters,
            terms=term_tuple,
            state=QueryState(),
            include_future=True,
        )
        ids = self._candidate_ids(self.search(plan))
        if mode == "record":
            # 记录型产品检索还会合并“正文通知里的表格式事实”（T09-D2）；这些单元在 rag 里
            # 是 text chunk，记录面召回不会返回。用同一过滤条件的正文面补齐候选，避免把
            # 冲突通知误判成不可见。旧检索的分组/冲突判定仍在后面复核。
            document_plan = QueryPlan(
                question=query_text,
                mode="document",
                query_text=query_text,
                field_role=None,
                field_label=None,
                filters=filters,
                terms=term_tuple,
                state=QueryState(),
                include_future=True,
            )
            ids |= self._candidate_ids(self.search(document_plan))
        return ids

    def candidate_unit_ids(self, plan: QueryPlan, *, limit: int | None = None) -> set[str]:
        """返回本轮 rag 召回覆盖的产品来源单元 ID（记录行或正文单元）。"""
        return self._candidate_ids(self.search(plan, limit=limit))

    @staticmethod
    def _candidate_ids(result: RetrievalResult) -> set[str]:
        chunks: dict[str, Any] = {}
        for chunk in result.exact:
            chunks.setdefault(chunk.chunk_id, chunk)
        for collection in (result.lexical, result.vector):
            for chunk in collection:
                chunks.setdefault(chunk.chunk_id, chunk)
        for chunk, _score in result.fused:
            chunks.setdefault(chunk.chunk_id, chunk)
        ids: set[str] = set()
        for chunk in chunks.values():
            if chunk.kind == "record" and chunk.record_unit_id:
                ids.add(str(chunk.record_unit_id))
            for unit_id in chunk.unit_ids or ():
                ids.add(str(unit_id))
            if chunk.kind == "record" and chunk.record_unit_id is None:
                ids.add(str(chunk.chunk_id))
        return ids

    # ---------------------------------------------------------------- 诊断

    def status(self) -> dict[str, Any]:
        try:
            payload = self._status_from_meta().to_dict()
        except Exception as exc:  # noqa: BLE001 - 状态查询不能影响问答
            return {"ready": False, "error_code": type(exc).__name__}
        payload["db_path"] = str(self.index_path)
        payload["engine_version"] = QA_ENGINE_VERSION
        payload["config"] = safe_config_summary(self.config)
        return payload

    def describe_answer(self, answer: RagAnswer) -> dict[str, Any]:
        """可写入诊断的摘要：只含计划/计数/拒绝原因，不含密钥或正文全文。"""
        diagnostics = dict(answer.diagnostics or {})
        plan = dict(diagnostics.get("plan") or {})
        recall = dict(diagnostics.get("recall") or {})
        return {
            "engine_version": QA_ENGINE_VERSION,
            "kind": answer.kind,
            "reason": answer.reason,
            "answer_source": answer.answer_source,
            "mode": plan.get("mode"),
            "enumerate": plan.get("enumerate"),
            "page": plan.get("page"),
            "recall": recall,
            "degraded": diagnostics.get("degraded"),
        }


def _go_binds_tokenizer(bindings: object) -> bool:
    """GO 是否把 tokenizer artifact 写进了 chat 绑定（写进去就必须真的用它计量）。"""
    chat = bindings.get("chat") if isinstance(bindings, dict) else None
    return isinstance(chat, dict) and bool(chat.get("tokenizer_sha256"))


def resolve_rag_config(
    *,
    data_dir: Path,
    provider_mode: str,
    page_size: int,
    top_k: int,
    business_date: str | None,
) -> tuple[RagConfig, Any | None]:
    """构造产品侧 rag 配置；live 必须显式预算入口，默认拒绝真实请求。"""
    if provider_mode == "offline":
        return (
            RagConfig(
                provider_mode="offline",
                data_dir=data_dir,
                page_size=page_size,
                top_k=top_k,
                business_date=business_date,
            ),
            None,
        )
    if provider_mode != "live":
        raise ValueError("rag_provider_mode 只允许 offline/live")
    # live：阶段额度/请求上限显式，账本/预算/GO 固定锚定；缺一不启动，避免不受控付费路径。
    from ..live_authorization import (
        LiveGateError,
        assert_fixed_env_paths,
        product_stage,
        resolve_live_gate,
    )
    from ..rag.config import positive_float_env, positive_int_env

    stage = product_stage()
    stage_limit = positive_float_env("MKTKB_RAG_STAGE_LIMIT_CNY")
    max_requests = positive_int_env("MKTKB_RAG_MAX_REQUESTS")
    if stage_limit is None or max_requests is None:
        raise ValueError(
            "rag live 必须显式提供 MKTKB_RAG_STAGE_LIMIT_CNY>0 与 MKTKB_RAG_MAX_REQUESTS>0，"
            "并通过固定共享账本/预算与产品 GO 授权；默认拒绝真实请求"
        )
    # GAP-1/1b：环境变量只能“指名”固定共享账本/预算，不能换成新账本或仓库外/软链路径。
    try:
        assert_fixed_env_paths(
            os.environ.get("MKTKB_RAG_BUDGET_LEDGER"),
            os.environ.get("MKTKB_RAG_BUDGET_JSON"),
        )
    except LiveGateError as exc:
        raise ValueError(f"rag live 授权闸门拒绝：{exc}") from exc
    default_request_bound = RagConfig(provider_mode="offline", data_dir=data_dir).max_request_cny
    try:
        gate = resolve_live_gate(
            stage=stage,
            service="rag",
            requested_stage_limit_cny=stage_limit,
            requested_max_requests=max_requests,
            request_bound_cny=default_request_bound,
        )
    except LiveGateError as exc:
        raise ValueError(f"rag live 授权闸门拒绝：{exc}") from exc
    budget = gate.ledger()
    config = RagConfig.from_env(
        provider_mode="live",
        data_dir=data_dir,
        business_date=business_date,
        budget_ledger_path=gate.ledger_path,
        budget_json_path=gate.budget_path,
        stage_limit_cny=gate.stage_limit_cny,
    )
    config = RagConfig(
        **{
            **config.__dict__,
            "page_size": page_size,
            "top_k": top_k,
            "stage": gate.stage,
            "max_request_cny": min(config.max_request_cny, gate.max_request_cny),
        }
    )
    # live 的 Key/价格/官方上界必须在入口就核对，不在首次查询时才失败（GAP-2）。
    config.require_live_credentials()
    from urllib.parse import urlsplit

    if config.chat_model:
        from ..official_chat_profile import (
            OfficialChatProfileError,
            assert_official_chat_profile,
        )

        try:
            assert_official_chat_profile(
                model=config.chat_model,
                base_url_host=urlsplit(config.chat_base_url).hostname,
                thinking="disabled",
                reserve_profile=config.chat_reserve_profile,
                context_ceiling_tokens=config.chat_context_ceiling_tokens,
                input_price_per_million_cny=config.chat_input_price_per_million_cny,
                output_price_per_million_cny=config.chat_output_price_per_million_cny,
                max_output_tokens=config.max_output_tokens,
                chat_max_output_tokens=config.chat_max_output_tokens,
            )
        except OfficialChatProfileError as exc:
            raise ValueError(f"rag live 官方 profile 校验拒绝：{exc}") from None
    bindings = getattr(gate.authorization, "bindings", None)
    go_binds_tokenizer = _go_binds_tokenizer(bindings)
    # S2-H：GO 一旦绑定了 tokenizer artifact，运行期必须真的用同一个 artifact 计量；
    # 开不了计量就不允许发真实 chat 请求（不得退回“字节数 + 常数”启发式）。
    if go_binds_tokenizer and not config.require_token_meter:
        raise ValueError(
            "rag live GO 已绑定 tokenizer artifact，但运行期未开启 MKTKB_REQUIRE_TOKEN_METER，"
            "禁止真实调用"
        )
    meter = None
    if config.chat_model and config.require_token_meter:
        from ..providers.token_metering import DeepSeekPromptMeter, TokenMeterError

        if config.chat_tokenizer_path is None or config.chat_tokenizer_sha256 is None:
            raise ValueError("rag live 要求官方 tokenizer artifact，缺少路径/哈希，禁发")
        try:
            meter = DeepSeekPromptMeter.from_files(
                config.chat_tokenizer_path, expected_sha256=config.chat_tokenizer_sha256
            )
        except TokenMeterError as exc:
            raise ValueError(f"rag live token 计量拒绝：{exc}") from None
    if bindings is None:
        raise ValueError(
            "rag live GO 必须声明 scope.bindings（rag 的 host/型号/region 与 chat 的型号/host/"
            "thinking/输出/token 预算 profile/价格）；缺失即拒绝真实调用"
        )
    from ..live_authorization import assert_provider_binding

    host = urlsplit(config.embedding_base_url).hostname or ""
    region = {
        "dashscope.aliyuncs.com": "beijing",
        "dashscope-intl.aliyuncs.com": "intl",
    }.get(host, "unknown")
    try:
        assert_provider_binding(
            gate.authorization,
            "rag",
            base_url_host=host,
            embedding_model=config.embedding_model,
            embedding_dimensions=config.embedding_dimensions,
            rerank_model=config.rerank_model,
            region=region,
        )
    except LiveGateError as exc:
        raise ValueError(f"rag live GO 绑定不匹配：{exc}") from None
    if config.chat_model:
        # 产品问答模型仍是官方 DeepSeek；编码助手用 wb 不影响这里。
        chat_host = urlsplit(config.chat_base_url).hostname or ""
        chat_expected: dict[str, object] = {
            "base_url_host": chat_host,
            "model": config.chat_model,
            "thinking": "disabled",
            "max_input_tokens": config.chat_max_input_tokens,
            "max_output_tokens": config.chat_max_output_tokens,
            "reserve_profile": config.chat_reserve_profile,
            "context_ceiling_tokens": config.chat_context_ceiling_tokens,
            "input_price_per_million_cny": config.chat_input_price_per_million_cny,
            "output_price_per_million_cny": config.chat_output_price_per_million_cny,
        }
        if meter is not None:
            chat_expected["tokenizer_sha256"] = meter.tokenizer_sha256
            chat_expected["chat_template_sha256"] = meter.template_sha256
        try:
            assert_provider_binding(gate.authorization, "chat", **chat_expected)
        except LiveGateError as exc:
            raise ValueError(f"rag live GO 绑定不匹配：{exc}") from None
    return config, budget


def manifest_summary(manifest: _Manifest) -> dict[str, Any]:
    """诊断用：只给数量与摘要，不暴露原文。"""
    return {
        "revision": manifest.revision,
        "documents": len(manifest.documents),
        "units": manifest.unit_count,
        "digest": manifest.digest,
    }


def _digest_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


__all__ = [
    "QA_ENGINE_VERSION",
    "QaEngine",
    "QaIndexStatus",
    "QaNotReady",
    "manifest_summary",
    "resolve_rag_config",
]
