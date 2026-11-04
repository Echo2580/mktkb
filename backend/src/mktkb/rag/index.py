"""隔离 RAG 索引：SQLite 持久化、来源保真块、内容哈希向量缓存与 NumPy 检索入口。"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import numpy as np
from sqlalchemy import bindparam, create_engine, delete, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..retrieval.tokenize import TOKENIZER_VERSION, index_body
from .chunking import build_chunks, role_values
from .config import RagConfig
from .errors import KnowledgeChanged, RagConfigError, RagNotReady
from .models import (
    RagBase,
    RagChunk,
    RagChunkEmbedding,
    RagDocument,
    RagEmbeddingCache,
    RagMeta,
    RagQueryStateRow,
    RagUnit,
)
from .providers import (
    BailianEmbeddingProvider,
    BailianRerankProvider,
    EmbeddingProvider,
    FakeEmbeddingProvider,
    LexicalReranker,
    RerankProvider,
)
from .types import AtomicUnit, DocumentSpec, IndexedChunk, QueryPlan, QueryState, RagAnswer

SCHEMA_VERSION = "local-r1-s1-1"
# 向量缓存寻址版本：内容/模型/维度/供应商之外再带索引口径版本；口径变化时旧缓存不再命中。
INDEX_CACHE_VERSION = "s2-a-1"


class RagIndex:
    """一个隔离 SQLite 索引；不打开 var 正式库。"""

    def __init__(
        self,
        db_path: Path | str,
        *,
        config: RagConfig | None = None,
        embedder: EmbeddingProvider | None = None,
        reranker: RerankProvider | None = None,
        budget: Any | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = config or RagConfig()
        self.budget = budget
        self.engine: Engine = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            future=True,
            connect_args={"check_same_thread": False, "timeout": 10.0},
        )
        event.listen(self.engine, "connect", self._on_connect)
        self._factory = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        self._lexicon_cache: dict[str, Any] | None = None
        self._lexicon_revision: int | None = None
        self.embedding_stats: dict[str, int] = {
            "cache_hits": 0,
            "cache_misses": 0,
            "provider_calls": 0,
        }
        if embedder is None:
            if self.config.live:
                self.config.require_live_credentials()
                # 真实应用路径同样按实际 usage 结算：旧结算语义下成功也按全额预留
                # （embedding 0.04096 / rerank 0.024）留账，真实 UI 实测每问约 0.13 元。
                from .settlement_policy import build_policy

                self.embedder: EmbeddingProvider = BailianEmbeddingProvider(
                    self.config, budget=budget, require_budget=True,
                    settlement_policy=build_policy(
                        "embedding", model=self.config.embedding_model
                    ),
                )
            else:
                self.embedder = FakeEmbeddingProvider(
                    model=self.config.embedding_model,
                    dimensions=self.config.embedding_dimensions,
                )
        else:
            self.embedder = embedder
        if reranker is None:
            if self.config.live:
                self.config.require_live_credentials()
                from .settlement_policy import build_policy

                self.reranker: RerankProvider = BailianRerankProvider(
                    self.config, budget=budget, require_budget=True,
                    settlement_policy=build_policy("rerank", model=self.config.rerank_model),
                )
            else:
                self.reranker = LexicalReranker()
        else:
            self.reranker = reranker
        self.initialize()

    def __repr__(self) -> str:
        return f"RagIndex(path={self.db_path.name!r}, mode={self.config.provider_mode!r})"

    def _on_connect(self, dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._factory()
        try:
            yield session
        finally:
            session.close()

    def initialize(self) -> None:
        RagBase.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS rag_chunk_fts USING fts5("
                "body, chunk_id UNINDEXED, tokenize='unicode61 remove_diacritics 2')"
            )
            row = connection.execute(text("SELECT value FROM rag_meta WHERE key='revision'")).scalar()
            if row is None:
                connection.execute(
                    text("INSERT INTO rag_meta(key, value) VALUES ('revision', '0')")
                )
            connection.execute(
                text(
                    "INSERT INTO rag_meta(key, value) VALUES ('schema_version', :v) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
                ),
                {"v": SCHEMA_VERSION},
            )
            connection.execute(
                text("INSERT OR REPLACE INTO rag_meta(key, value) VALUES ('tokenizer_version', :v)"),
                {"v": TOKENIZER_VERSION},
            )

    # ---------------------------------------------------------------- 基本状态

    def _meta(self, session: Session, key: str) -> str | None:
        return session.execute(select(RagMeta.value).where(RagMeta.key == key)).scalar()

    def revision(self) -> int:
        with self.session() as session:
            value = self._meta(session, "revision")
            return int(value or 0)

    def _bump_revision(self, session: Session) -> int:
        current = int(self._meta(session, "revision") or 0)
        next_value = current + 1
        session.execute(
            text("INSERT OR REPLACE INTO rag_meta(key, value) VALUES ('revision', :v)"),
            {"v": str(next_value)},
        )
        self._lexicon_cache = None
        self._lexicon_revision = None
        return next_value

    def stats(self) -> dict[str, Any]:
        with self.session() as session:
            documents = session.execute(select(RagDocument)).scalars().all()
            return {
                "db_path": str(self.db_path),
                "revision": self.revision(),
                "documents": {
                    "total": len(documents),
                    "active_current": sum(
                        1 for doc in documents if doc.state == "active" and bool(doc.is_current)
                    ),
                    "deleted": sum(1 for doc in documents if doc.state == "deleted"),
                    "superseded": sum(1 for doc in documents if doc.state == "superseded"),
                },
                "units": int(session.execute(select(RagUnit)).all().__len__()),
                "chunks": int(session.execute(select(RagChunk)).all().__len__()),
                "embedding_cache": int(session.execute(select(RagEmbeddingCache)).all().__len__()),
                "chunk_embeddings": int(session.execute(select(RagChunkEmbedding)).all().__len__()),
                "embedding_stats": dict(self.embedding_stats),
                "provider": {
                    "mode": self.config.provider_mode,
                    "embedding_provider": getattr(self.embedder, "provider", None),
                    "embedding_model": getattr(self.embedder, "model", None),
                    "rerank_provider": getattr(self.reranker, "provider", None),
                    "rerank_model": getattr(self.reranker, "model", None),
                },
            }

    def get_meta(self, key: str) -> str | None:
        """读取索引元数据（schema/产品 revision/同步状态等），供产品侧生命周期判断。"""
        with self.session() as session:
            return self._meta(session, key)

    def set_meta(self, values: Mapping[str, str | None]) -> None:
        """单事务写入索引元数据；None 表示删除该键。"""
        with self.session() as session:
            for key, value in values.items():
                if value is None:
                    session.execute(text("DELETE FROM rag_meta WHERE key=:k"), {"k": key})
                else:
                    session.execute(
                        text("INSERT OR REPLACE INTO rag_meta(key, value) VALUES (:k, :v)"),
                        {"k": key, "v": str(value)},
                    )
            session.commit()

    def list_documents(self) -> list[dict[str, Any]]:
        """列出索引内文档/版本与状态（只读），用于增量同步比对。"""
        with self.session() as session:
            rows = session.execute(select(RagDocument)).scalars().all()
            return [
                {
                    "doc_id": row.doc_id,
                    "logical_id": row.logical_id,
                    "version_id": row.version_id,
                    "title": row.title,
                    "state": row.state,
                    "is_current": bool(row.is_current),
                }
                for row in rows
            ]

    # ---------------------------------------------------------------- 建索引

    def rebuild(
        self,
        documents: Iterable[tuple[DocumentSpec, Sequence[AtomicUnit]]],
        *,
        embed: bool = True,
        clear_cache: bool = False,
    ) -> dict[str, Any]:
        started = time.monotonic()
        items = list(documents)
        with self.session() as session:
            session.execute(text("DELETE FROM rag_chunk_fts"))
            session.execute(delete(RagChunkEmbedding))
            session.execute(delete(RagChunk))
            session.execute(delete(RagUnit))
            session.execute(delete(RagDocument))
            if clear_cache:
                session.execute(delete(RagEmbeddingCache))
            session.execute(text("INSERT OR REPLACE INTO rag_meta(key, value) VALUES ('revision', '0')"))
            session.commit()
        total_chunks = 0
        total_units = 0
        for doc, units in items:
            result = self.add_document(doc, units, embed=embed)
            total_chunks += result["chunks"]
            total_units += result["units"]
        return {
            "documents": len(items),
            "units": total_units,
            "chunks": total_chunks,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "revision": self.revision(),
            "embedding_stats": dict(self.embedding_stats),
        }

    def add_document(
        self,
        doc: DocumentSpec,
        units: Sequence[AtomicUnit],
        *,
        embed: bool = True,
        activate: bool | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        if not doc.doc_id or not doc.version_id:
            raise RagConfigError("文档必须提供 doc_id 与 version_id")
        with self.session() as session:
            revision = self._bump_revision(session)
            self._delete_document_rows(session, doc.doc_id)
            should_activate = doc.is_current if activate is None else bool(activate)
            if should_activate:
                for other in session.execute(
                    select(RagDocument).where(RagDocument.logical_id == doc.logical_id)
                ).scalars():
                    other.is_current = False
                    if other.state == "active":
                        other.state = "superseded"
            state = doc.state if should_activate else ("superseded" if doc.state == "active" else doc.state)
            row = RagDocument(
                doc_id=doc.doc_id,
                logical_id=doc.logical_id,
                version_id=doc.version_id,
                version_label=doc.version_label,
                source_path=doc.source_path,
                title=doc.title,
                file_kind=doc.file_kind,
                sha256=doc.sha256,
                state=state,
                is_current=should_activate,
                effective_from=doc.effective_from,
                effective_to=doc.effective_to,
                business_date=doc.business_date,
                metadata_json=dict(doc.metadata or {}),
            )
            session.add(row)
            for unit in units:
                session.add(
                    RagUnit(
                        unit_id=unit.unit_id,
                        doc_id=doc.doc_id,
                        version_id=doc.version_id,
                        kind=unit.kind,
                        ordinal=unit.ordinal,
                        unit_key=unit.unit_key,
                        text=unit.text,
                        fields=dict(unit.fields or {}),
                        sheet=unit.sheet,
                        locator=dict(unit.locator or {}),
                        header_row=unit.header_row,
                        row_number=unit.row_number,
                        title=unit.title,
                        effective_from=unit.effective_from,
                        effective_to=unit.effective_to,
                    )
                )
            session.flush()
            chunks = [replace(chunk, revision=revision) for chunk in build_chunks(doc, units, self.config)]
            for chunk in chunks:
                session.add(self._chunk_row(chunk))
                session.execute(
                    text("INSERT INTO rag_chunk_fts(body, chunk_id) VALUES (:body, :chunk_id)"),
                    {"body": index_body(chunk.text), "chunk_id": chunk.chunk_id},
                )
            session.commit()
        embedded = 0
        embedding_error: str | None = None
        if embed and chunks:
            try:
                embedded = self._embed_chunks(chunks)
            except Exception as exc:  # 保留可检索的精确/FTS 层；错误显式返回，不伪装成功
                embedding_error = getattr(exc, "code", type(exc).__name__)
        return {
            "doc_id": doc.doc_id,
            "revision": revision,
            "units": len(units),
            "chunks": len(chunks),
            "embedded": embedded,
            "embedding_error": embedding_error,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }

    def _delete_document_rows(self, session: Session, doc_id: str) -> None:
        chunk_ids = session.execute(
            select(RagChunk.chunk_id).where(RagChunk.doc_id == doc_id)
        ).scalars().all()
        if chunk_ids:
            statement = text("DELETE FROM rag_chunk_fts WHERE chunk_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            )
            session.execute(statement, {"ids": chunk_ids})
            session.execute(delete(RagChunkEmbedding).where(RagChunkEmbedding.chunk_id.in_(chunk_ids)))
        session.execute(delete(RagChunk).where(RagChunk.doc_id == doc_id))
        session.execute(delete(RagUnit).where(RagUnit.doc_id == doc_id))
        existing = session.get(RagDocument, doc_id)
        if existing is not None:
            session.delete(existing)

    def remove_document(self, doc_id: str) -> dict[str, Any]:
        with self.session() as session:
            revision = self._bump_revision(session)
            self._delete_document_rows(session, doc_id)
            session.commit()
        return {"doc_id": doc_id, "revision": revision, "removed": True}

    def remove_version(self, version_id: str) -> dict[str, Any]:
        with self.session() as session:
            doc_ids = session.execute(
                select(RagDocument.doc_id).where(RagDocument.version_id == version_id)
            ).scalars().all()
            if not doc_ids:
                return {"version_id": version_id, "removed": False, "revision": self.revision()}
            revision = self._bump_revision(session)
            for doc_id in doc_ids:
                self._delete_document_rows(session, doc_id)
            session.commit()
        return {"version_id": version_id, "removed": True, "revision": revision, "documents": len(doc_ids)}

    def set_active_version(self, logical_id: str, version_id: str) -> dict[str, Any]:
        with self.session() as session:
            rows = session.execute(
                select(RagDocument).where(RagDocument.logical_id == logical_id)
            ).scalars().all()
            if not rows:
                return {"logical_id": logical_id, "changed": False}
            revision = self._bump_revision(session)
            target = next((row for row in rows if row.version_id == version_id), None)
            if target is None:
                return {"logical_id": logical_id, "changed": False, "revision": revision}
            for row in rows:
                row.is_current = row.doc_id == target.doc_id
                row.state = "active" if row.is_current else "superseded"
            session.commit()
        return {"logical_id": logical_id, "version_id": version_id, "changed": True, "revision": revision}

    def _chunk_row(self, chunk: IndexedChunk) -> RagChunk:
        return RagChunk(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            version_id=chunk.version_id,
            revision=chunk.revision,
            kind=chunk.kind,
            ordinal=chunk.ordinal,
            text=chunk.text,
            title=chunk.title,
            sheet=chunk.sheet,
            locator=dict(chunk.locator),
            fields=dict(chunk.fields),
            role_values={key: list(value) for key, value in chunk.role_values.items()},
            filters=dict(chunk.filters),
            filters_norm=dict(chunk.filters_norm),
            entity_type=chunk.entity_type,
            entity_key=chunk.entity_key,
            label=chunk.label,
            record_unit_id=chunk.record_unit_id,
            unit_ids=list(chunk.unit_ids),
            content_sha256=chunk.content_sha256,
            token_count=chunk.token_count,
            effective_from=chunk.effective_from,
            effective_to=chunk.effective_to,
        )

    # ---------------------------------------------------------------- 向量缓存

    def _embed_chunks(self, chunks: Sequence[IndexedChunk]) -> int:
        if not chunks:
            return 0
        model = getattr(self.embedder, "model", self.config.embedding_model)
        dimensions = int(getattr(self.embedder, "dimensions", self.config.embedding_dimensions))
        provider = getattr(self.embedder, "provider", "unknown")
        with self.session() as session:
            existing_mappings = {
                row.chunk_id: row
                for row in session.execute(
                    select(RagChunkEmbedding).where(
                        RagChunkEmbedding.chunk_id.in_([chunk.chunk_id for chunk in chunks])
                    )
                ).scalars()
            }
            cache = {
                (row.content_sha256, row.model, row.dimensions, row.provider): row
                for row in session.execute(
                    select(RagEmbeddingCache).where(
                        RagEmbeddingCache.model == model,
                        RagEmbeddingCache.dimensions == dimensions,
                        RagEmbeddingCache.provider == provider,
                    )
                ).scalars()
            }
            pending: list[IndexedChunk] = []
            for chunk in chunks:
                key = (chunk.content_sha256, model, dimensions, provider)
                if chunk.chunk_id in existing_mappings and key in cache:
                    self.embedding_stats["cache_hits"] += 1
                    continue
                if key in cache:
                    self._map_chunk(session, chunk.chunk_id, cache[key])
                    self.embedding_stats["cache_hits"] += 1
                    continue
                pending.append(chunk)
            if not pending:
                session.commit()
                return 0

            unique: dict[tuple[str, str, int, str], str] = {}
            for chunk in pending:
                key = (chunk.content_sha256, model, dimensions, provider)
                unique.setdefault(key, chunk.text)
            texts = list(unique.values())
            self.embedding_stats["provider_calls"] += 1
            response = self.embedder.embed(texts, purpose="document")
            if len(response.vectors) != len(texts):
                raise RagConfigError("embedding 返回条数与待嵌入块数不一致")
            if int(response.dimensions) != dimensions:
                raise RagConfigError("embedding 维度与索引配置不一致")
            by_key: dict[tuple[str, str, int, str], np.ndarray] = {}
            for key, vector in zip(unique.keys(), response.vectors):
                array = np.asarray(vector, dtype=np.float32)
                norm = float(np.linalg.norm(array))
                if norm > 0:
                    array = array / norm
                by_key[key] = array
            now_cache: dict[tuple[str, str, int, str], RagEmbeddingCache] = {}
            for key, array in by_key.items():
                content_sha, model_name, dims, provider_name = key
                cache_key = _cache_key(content_sha, model_name, dims, provider_name)
                row = cache.get(key) or RagEmbeddingCache(
                    cache_key=cache_key,
                    content_sha256=content_sha,
                    model=model_name,
                    dimensions=dims,
                    provider=provider_name,
                    vector=array.tobytes(order="C"),
                    token_count=0,
                )
                if row.cache_key not in {item.cache_key for item in now_cache.values()}:
                    session.add(row)
                now_cache[key] = row
            session.flush()
            for chunk in pending:
                key = (chunk.content_sha256, model, dimensions, provider)
                row = now_cache.get(key) or cache.get(key)
                if row is None:
                    raise RagConfigError("向量缓存写入失败")
                self._map_chunk(session, chunk.chunk_id, row)
                self.embedding_stats["cache_misses"] += 1
            session.commit()
        return len(pending)

    def ensure_embeddings(self, doc_id: str) -> dict[str, Any]:
        """补齐某文档缺失的向量映射（内容哈希缓存命中则不调用供应商）。

        生命周期重试用：同步失败后再次同步时，已写入的精确/FTS 层不会重复建，
        但缺失的向量仍会尝试补齐；错误向上抛，调用方标记 degraded 状态。
        """
        with self.session() as session:
            chunks = [
                _row_to_chunk(row)
                for row in session.execute(select(RagChunk).where(RagChunk.doc_id == doc_id)).scalars()
            ]
        if not chunks:
            return {"doc_id": doc_id, "chunks": 0, "missing": 0, "embedded": 0}
        model = getattr(self.embedder, "model", self.config.embedding_model)
        dimensions = int(getattr(self.embedder, "dimensions", self.config.embedding_dimensions))
        provider = getattr(self.embedder, "provider", "unknown")
        with self.session() as session:
            mapped = set(
                session.execute(
                    select(RagChunkEmbedding.chunk_id).where(
                        RagChunkEmbedding.chunk_id.in_([chunk.chunk_id for chunk in chunks]),
                        RagChunkEmbedding.model == model,
                        RagChunkEmbedding.dimensions == dimensions,
                        RagChunkEmbedding.provider == provider,
                    )
                ).scalars()
            )
        missing = [chunk for chunk in chunks if chunk.chunk_id not in mapped]
        embedded = self._embed_chunks(missing) if missing else 0
        return {"doc_id": doc_id, "chunks": len(chunks), "missing": len(missing), "embedded": embedded}

    def _map_chunk(self, session: Session, chunk_id: str, cache_row: RagEmbeddingCache) -> None:
        existing = session.get(RagChunkEmbedding, chunk_id)
        if existing is None:
            session.add(
                RagChunkEmbedding(
                    chunk_id=chunk_id,
                    cache_key=cache_row.cache_key,
                    model=cache_row.model,
                    dimensions=cache_row.dimensions,
                    provider=cache_row.provider,
                )
            )
        else:
            existing.cache_key = cache_row.cache_key
            existing.model = cache_row.model
            existing.dimensions = cache_row.dimensions
            existing.provider = cache_row.provider

    # ---------------------------------------------------------------- 查询状态

    def load_state(self, user_id: str, conversation_id: str) -> QueryState:
        with self.session() as session:
            row = session.get(RagQueryStateRow, (str(user_id), str(conversation_id)))
            if row is None:
                return QueryState(user_id=str(user_id), conversation_id=str(conversation_id))
            state = QueryState.from_dict(row.state_json)
            state.user_id = str(user_id)
            state.conversation_id = str(conversation_id)
            return state

    def save_state(self, state: QueryState) -> None:
        if not state.user_id or not state.conversation_id:
            raise RagConfigError("查询状态必须绑定 user_id 与 conversation_id")
        with self.session() as session:
            row = session.get(RagQueryStateRow, (state.user_id, state.conversation_id))
            payload = state.to_dict()
            if row is None:
                session.add(
                    RagQueryStateRow(
                        user_id=state.user_id,
                        conversation_id=state.conversation_id,
                        state_json=payload,
                    )
                )
            else:
                row.state_json = payload
            session.commit()

    def clear_state(self, user_id: str, conversation_id: str) -> None:
        with self.session() as session:
            row = session.get(RagQueryStateRow, (str(user_id), str(conversation_id)))
            if row is not None:
                session.delete(row)
                session.commit()

    # ---------------------------------------------------------------- 词表

    def lexicon_data(self) -> dict[str, Any]:
        revision = self.revision()
        if self._lexicon_cache is not None and self._lexicon_revision == revision:
            return self._lexicon_cache
        with self.session() as session:
            rows = session.execute(
                select(RagChunk)
                .join(RagDocument, RagDocument.doc_id == RagChunk.doc_id)
                .where(
                    RagDocument.state == "active",
                    RagDocument.is_current.is_(True),
                    RagChunk.kind == "record",
                )
            ).scalars().all()
            document_rows = session.execute(
                select(RagDocument).where(
                    RagDocument.state == "active", RagDocument.is_current.is_(True)
                )
            ).scalars().all()
            documents = tuple(
                {
                    "doc_id": row.doc_id,
                    "title": row.title,
                    "source_path": row.source_path,
                    "version_label": row.version_label,
                }
                for row in document_rows
            )
        data: dict[str, set[str]] = {
            "stores": set(),
            "items": set(),
            "products": set(),
            "channels": set(),
            "price_types": set(),
            "identifiers": set(),
            "field_labels": set(),
        }
        alias_map: dict[str, set[str]] = {}
        for row in rows:
            values = _role_values_from_json(row.role_values)
            for role, key in (
                ("store", "stores"),
                ("item", "items"),
                ("product", "products"),
                ("price_type", "price_types"),
                ("identifier", "identifiers"),
            ):
                for value in values.get(role, ()):
                    if value and value not in ("—", "-"):
                        data[key].add(value)
            for value in values.get("channel", ()):
                for part in value.replace("｜", "|").replace("/", "|").replace("、", "|").split("|"):
                    part = part.strip()
                    if part and part not in ("—", "-"):
                        data["channels"].add(part)
            targets = [
                values.get("item", (None,))[0],
                values.get("product", (None,))[0],
            ]
            for alias in values.get("alias", ()):
                for target in targets:
                    if target and target not in ("—", "-"):
                        alias_map.setdefault(alias, set()).add(target)
            for name in dict(row.fields or {}):
                data["field_labels"].add(str(name))
        result = {key: tuple(sorted(values)) for key, values in data.items()}
        result["alias_map"] = {key: tuple(sorted(values)) for key, values in alias_map.items()}
        result["documents"] = documents
        self._lexicon_cache = result
        self._lexicon_revision = revision
        return result

    # ---------------------------------------------------------------- 读取与检索

    def get_chunk(self, chunk_id: str, *, require_visible: bool = True) -> IndexedChunk | None:
        with self.session() as session:
            row = session.get(RagChunk, chunk_id)
            if row is None:
                return None
            if require_visible:
                doc = session.get(RagDocument, row.doc_id)
                if doc is None or doc.state != "active" or not doc.is_current:
                    return None
            return _row_to_chunk(row)

    def get_unit(self, unit_id: str) -> RagUnit | None:
        with self.session() as session:
            return session.get(RagUnit, unit_id)

    def document_info(self, doc_id: str) -> RagDocument | None:
        with self.session() as session:
            return session.get(RagDocument, doc_id)

    def chunks_by_ids(self, chunk_ids: Sequence[str], *, visible_only: bool = True) -> list[IndexedChunk]:
        if not chunk_ids:
            return []
        with self.session() as session:
            rows = session.execute(
                select(RagChunk)
                .join(RagDocument, RagDocument.doc_id == RagChunk.doc_id)
                .where(RagChunk.chunk_id.in_(list(chunk_ids)))
            ).scalars().all()
            if visible_only:
                rows = [
                    row
                    for row in rows
                    if (doc := session.get(RagDocument, row.doc_id)) is not None
                    and doc.state == "active"
                    and doc.is_current
                ]
            by_id = {row.chunk_id: _row_to_chunk(row) for row in rows}
            return [by_id[item] for item in chunk_ids if item in by_id]

    def search(self, plan: QueryPlan, *, limit: int | None = None) -> Any:
        from .retrieval import search as _search

        return _search(self, plan, limit=limit)

    def ask(
        self,
        question: str,
        *,
        user_id: str,
        conversation_id: str,
        limit: int | None = None,
    ) -> RagAnswer:
        from .answer import answer_question

        return answer_question(
            self,
            question,
            user_id=user_id,
            conversation_id=conversation_id,
            limit=limit,
        )

    def close(self) -> None:
        for provider in (self.embedder, self.reranker):
            close = getattr(provider, "close", None)
            if callable(close):
                close()
        self.engine.dispose()


def _cache_key(content_sha: str, model: str, dimensions: int, provider: str) -> str:
    import hashlib

    payload = f"{INDEX_CACHE_VERSION}|{provider}|{model}|{dimensions}|{content_sha}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _role_values_from_json(data: Mapping[str, Any] | None) -> dict[str, tuple[str, ...]]:
    return {
        str(key): tuple(str(item) for item in (values or ()))
        for key, values in dict(data or {}).items()
    }


def _row_to_chunk(row: RagChunk) -> IndexedChunk:
    return IndexedChunk(
        chunk_id=row.chunk_id,
        doc_id=row.doc_id,
        version_id=row.version_id,
        revision=int(row.revision),
        kind=row.kind,
        ordinal=int(row.ordinal),
        text=row.text,
        title=row.title,
        content_sha256=row.content_sha256,
        token_count=int(row.token_count),
        sheet=row.sheet,
        locator=dict(row.locator or {}),
        fields=dict(row.fields or {}),
        role_values=_role_values_from_json(row.role_values),
        filters=dict(row.filters or {}),
        filters_norm=dict(row.filters_norm or {}),
        entity_type=row.entity_type,
        entity_key=row.entity_key,
        label=row.label,
        record_unit_id=row.record_unit_id,
        unit_ids=tuple(str(item) for item in (row.unit_ids or ())),
        effective_from=row.effective_from,
        effective_to=row.effective_to,
    )


def false():
    """SQLAlchemy false() 的轻量包装，避免在条件表达式中引入额外导入。"""
    from sqlalchemy import false as _false

    return _false()
