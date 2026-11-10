"""精确/FTS/向量混合召回、硬过滤、融合与重排。

- 明确实体/商品/渠道/价格类型/业务日期在打分前执行硬过滤；
- 向量候选先全部打分再截断，不会因宽 OR 超过 100 候选直接拒答；
- 融合使用 RRF，重排只调整顺序，不改变硬过滤结果；
- “全部”按完整条件集合分页，不用 Top-K 冒充总数。
"""

from __future__ import annotations

import math
import time
from typing import Any, Iterable, Mapping

import numpy as np
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from ..observability import trace_attrs
from ..retrieval.tokenize import match_expression, normalize
from .errors import KnowledgeChanged
from .models import RagChunk, RagChunkEmbedding, RagDocument, RagEmbeddingCache
from .types import Citation, EvidenceItem, IndexedChunk, QueryPlan, RetrievalResult

RRF_K = 60
EXACT_WEIGHT = 2.2
LEXICAL_WEIGHT = 1.0
VECTOR_WEIGHT = 1.0


def search(index: Any, plan: QueryPlan, *, limit: int | None = None) -> RetrievalResult:
    started = time.monotonic()
    start_revision = index.revision()
    top_k = int(limit or index.config.top_k)
    diagnostics: dict[str, Any] = {
        "provider_mode": index.config.provider_mode,
        "embedding_provider": getattr(index.embedder, "provider", None),
        "rerank_provider": getattr(index.reranker, "provider", None),
        "top_k": top_k,
        "candidate_limit": index.config.candidate_limit,
    }
    degraded: list[str] = []
    # 查询向量面被运行时关闭时该通道不执行：不创建 Span、不置条件属性（设计 §6.4）。
    vector_enabled = not getattr(index.config, "disable_query_embedding", False)
    with index.session() as session:
        with trace_attrs.span("recall") as recall_span:
            if plan.mode == "record":
                with trace_attrs.span("exact_recall") as exact_span:
                    exact_chunks = _exact_recall(session, index, plan, diagnostics)
                    exact_span.annotate(candidates=len(exact_chunks))
            else:
                exact_chunks = _exact_recall(session, index, plan, diagnostics)
            hints = _effective_hints(session, index, plan, diagnostics)
            with trace_attrs.span("lexical_recall") as lexical_span:
                lexical_chunks = _lexical_recall(session, index, plan, diagnostics)
                lexical_span.annotate(
                    candidates=len(lexical_chunks),
                    expression_present=diagnostics.get("lexical_expression") is not None,
                )
            if vector_enabled:
                with trace_attrs.span("vector_recall") as vector_span:
                    vector_chunks, vector_error = _vector_recall(session, index, plan, diagnostics)
                    vector_span.annotate(
                        candidates=len(vector_chunks),
                        degraded=bool(vector_error),
                        degraded_reason=vector_error,
                    )
            else:
                vector_chunks, vector_error = _vector_recall(session, index, plan, diagnostics)
            if vector_error:
                degraded.append("vector")
                diagnostics["vector_error"] = vector_error
            recall_span.annotate(
                exact=len(exact_chunks),
                lexical=len(lexical_chunks),
                vector=len(vector_chunks),
                hints=len(hints),
                vector_enabled=vector_enabled,
            )
        with trace_attrs.span("fuse") as fuse_span:
            fused = _fuse(index, plan, exact_chunks, lexical_chunks, vector_chunks, diagnostics)
            # 重排只在融合结果非空时真实执行（_fuse 内创建 rerank Span 并写 diagnostics["rerank"]）。
            rerank_enabled = "rerank" in diagnostics
            fuse_span.annotate(candidates=len(fused), rerank_enabled=rerank_enabled)
        if plan.enumerate:
            base = _enumerate_base(exact_chunks, fused)
            total = len(base)
            page = max(1, int(plan.page))
            page_size = max(1, min(plan.page_size, index.config.max_page_size))
            start = (page - 1) * page_size
            page_items = base[start : start + page_size]
            has_more = start + len(page_items) < total
            next_page = page + 1 if has_more else None
            evidence = _to_evidence(session, index, plan, page_items, fused_scores={c.chunk_id: s for c, s in fused})
            diagnostics["enumeration"] = True
            diagnostics["total"] = total
            diagnostics["page"] = page
            diagnostics["page_size"] = page_size
        else:
            selected = fused[:top_k]
            evidence = _to_evidence(
                session,
                index,
                plan,
                [chunk for chunk, _ in selected],
                fused_scores={chunk.chunk_id: score for chunk, score in selected},
            )
            total = len(exact_chunks) if exact_chunks else len(fused)
            has_more = len(fused) > len(evidence)
            next_page = None
            diagnostics["enumeration"] = False
        recall_counts = {
            "exact": len(exact_chunks),
            "lexical": len(lexical_chunks),
            "vector": len(vector_chunks),
            "fused": len(fused),
            "returned": len(evidence),
        }
        diagnostics["recall"] = recall_counts
        diagnostics["timings_ms"] = {"search": round((time.monotonic() - started) * 1000, 2)}
        diagnostics["degraded"] = degraded
        result = RetrievalResult(
            plan=plan,
            revision=start_revision,
            exact=exact_chunks,
            lexical=lexical_chunks,
            vector=vector_chunks,
            fused=fused,
            evidence=evidence,
            total=total,
            returned=len(evidence),
            has_more=has_more,
            next_page=next_page,
            recall_counts=recall_counts,
            diagnostics=diagnostics,
            degraded=tuple(degraded),
            effective_hints=hints,
        )
    # Trace 级字段只写计数/布尔/稳定引用（设计 §6.3/§6.5）；条件属性经 annotate 并入
    # filter_decisions_json（T003a 约定），与 Span 的实际执行保持一致。
    trace_attrs.annotate_trace(
        index_revision=str(start_revision),
        retrieval_counts_json=recall_counts,
        filter_decisions_json={
            "mode": plan.mode,
            "enumerate": bool(plan.enumerate),
            "applied_filters": sorted(plan.filters),
            "vector_enabled": vector_enabled,
            "rerank_enabled": rerank_enabled,
        },
        degraded_json=list(degraded),
        vector_enabled=vector_enabled,
        rerank_enabled=rerank_enabled,
    )
    if index.revision() != start_revision:
        raise KnowledgeChanged("检索期间知识库版本发生变化")
    return result


def _base_stmt(
    session: Session,
    plan: QueryPlan,
    *,
    require_record: bool = False,
    ignore_effective: bool = False,
):
    stmt = (
        select(RagChunk)
        .join(RagDocument, RagDocument.doc_id == RagChunk.doc_id)
        .where(RagDocument.state == "active", RagDocument.is_current.is_(True))
    )
    if require_record:
        stmt = stmt.where(RagChunk.kind == "record")
    if plan.mode == "record" or plan.filters.get("doc_id"):
        _multi_store = tuple(getattr(plan.state, "stores", ()) or ())
        if len(_multi_store) > 1:
            stmt = stmt.where(
                or_(*(func.json_extract(RagChunk.filters_norm, "$.store") == normalize(item)
                      for item in _multi_store))
            )
        for key, value in plan.filters.items():
            if key == "doc_id":
                stmt = stmt.where(RagChunk.doc_id == value)
                continue
            if plan.mode != "record":
                continue
            if key not in ("store", "item", "product", "channel", "price_type", "identifier"):
                continue
            normalized = normalize(value)
            stores = tuple(getattr(plan.state, "stores", ()) or ())
            if key == "store" and len(stores) > 1:
                stmt = stmt.where(
                    or_(*(func.json_extract(RagChunk.filters_norm, "$.store") == normalize(item) for item in stores))
                )
                continue
            if key == "channel":
                stmt = stmt.where(
                    or_(
                        func.json_extract(RagChunk.filters_norm, "$.channel") == normalized,
                        func.json_extract(RagChunk.filters_norm, "$.channels").like(f'%"{normalized}"%'),
                    )
                )
            else:
                stmt = stmt.where(func.json_extract(RagChunk.filters_norm, f"$.{key}") == normalized)
    if plan.as_of and not plan.include_future and not ignore_effective:
        stmt = stmt.where(
            or_(RagChunk.effective_from.is_(None), RagChunk.effective_from == "", RagChunk.effective_from <= plan.as_of),
            or_(RagChunk.effective_to.is_(None), RagChunk.effective_to == "", RagChunk.effective_to >= plan.as_of),
            or_(RagDocument.effective_from.is_(None), RagDocument.effective_from == "", RagDocument.effective_from <= plan.as_of),
            or_(RagDocument.effective_to.is_(None), RagDocument.effective_to == "", RagDocument.effective_to >= plan.as_of),
        )
    return stmt.order_by(RagChunk.doc_id, RagChunk.ordinal)


def _load(session: Session, stmt) -> list[IndexedChunk]:
    from .index import _row_to_chunk

    return [_row_to_chunk(row) for row in session.execute(stmt).scalars().all()]


def _has_role(chunk: IndexedChunk, role: str | None) -> bool:
    if not role:
        return True
    return bool(chunk.role_values.get(role))


def _exact_recall(session: Session, index: Any, plan: QueryPlan, diagnostics: dict[str, Any]) -> list[IndexedChunk]:
    if plan.mode != "record":
        return []
    chunks = _load(session, _base_stmt(session, plan, require_record=True))
    chunks = [chunk for chunk in chunks if _has_role(chunk, plan.field_role)]
    # 多字段/多实体时保留全部精确命中；不在召回阶段截断。
    diagnostics["exact_candidates"] = len(chunks)
    return chunks


def _effective_hints(
    session: Session, index: Any, plan: QueryPlan, diagnostics: dict[str, Any]
) -> list[tuple[IndexedChunk, str]]:
    """日期过滤未命中时，保留未来生效/已过期记录用于解释，不把旧值当现价。"""
    if plan.mode != "record" or not plan.as_of or plan.include_future:
        return []
    chunks = _load(
        session,
        _base_stmt(session, plan, require_record=True, ignore_effective=True),
    )
    hints: list[tuple[IndexedChunk, str]] = []
    for chunk in chunks:
        if not _has_role(chunk, plan.field_role):
            continue
        status = "current"
        if chunk.effective_from and chunk.effective_from > plan.as_of:
            status = "future"
        elif chunk.effective_to and chunk.effective_to < plan.as_of:
            status = "expired"
        if status != "current":
            hints.append((chunk, status))
    diagnostics["effective_hints"] = len(hints)
    return hints[:20]


def _lexical_recall(session: Session, index: Any, plan: QueryPlan, diagnostics: dict[str, Any]) -> list[IndexedChunk]:
    expression = match_expression(plan.terms)
    if not expression:
        diagnostics["lexical_expression"] = None
        return []
    diagnostics["lexical_expression"] = expression
    try:
        rows = session.execute(
            text(
                "SELECT chunk_id FROM rag_chunk_fts WHERE rag_chunk_fts MATCH :expr "
                "ORDER BY bm25(rag_chunk_fts) LIMIT :limit"
            ),
            {"expr": expression, "limit": index.config.candidate_limit},
        ).scalars().all()
    except Exception as exc:
        diagnostics["lexical_error"] = type(exc).__name__
        return []
    if not rows:
        return []
    stmt = _base_stmt(session, plan).where(RagChunk.chunk_id.in_(list(rows)))
    chunks = _load(session, stmt)
    order = {chunk_id: position for position, chunk_id in enumerate(rows)}
    chunks.sort(key=lambda chunk: order.get(chunk.chunk_id, 10**9))
    diagnostics["lexical_candidates"] = len(chunks)
    return chunks


def _vector_recall(
    session: Session, index: Any, plan: QueryPlan, diagnostics: dict[str, Any]
) -> tuple[list[IndexedChunk], str | None]:
    started = time.monotonic()
    if getattr(index.config, "disable_query_embedding", False):
        # 运行时强制关闭查询向量面：计划里把该面上界降为 0 必须由这里兜底。
        diagnostics["query_embedding_error"] = "QUERY_EMBEDDING_DISABLED"
        return [], "QUERY_EMBEDDING_DISABLED"
    try:
        with trace_attrs.span("embedding_query") as embed_span:
            response = index.embedder.embed([plan.query_text], purpose="query")
            embed_span.annotate(
                provider=getattr(response, "provider", None),
                model=getattr(response, "model", None),
                dimensions=int(getattr(response, "dimensions", 0) or 0),
                vectors=len(getattr(response, "vectors", ()) or ()),
            )
        query_vector = np.asarray(response.vectors[0], dtype=np.float32)
    except Exception as exc:
        diagnostics["query_embedding_error"] = getattr(exc, "code", type(exc).__name__)
        return [], getattr(exc, "code", type(exc).__name__)
    norm = float(np.linalg.norm(query_vector))
    if norm == 0:
        return [], "QUERY_VECTOR_ZERO"
    query_vector = query_vector / norm
    model = getattr(index.embedder, "model", index.config.embedding_model)
    dimensions = int(getattr(index.embedder, "dimensions", index.config.embedding_dimensions))
    provider = getattr(index.embedder, "provider", "unknown")

    stmt = (
        select(RagChunk, RagEmbeddingCache.vector)
        .join(RagChunkEmbedding, RagChunkEmbedding.chunk_id == RagChunk.chunk_id)
        .join(RagEmbeddingCache, RagEmbeddingCache.cache_key == RagChunkEmbedding.cache_key)
        .join(RagDocument, RagDocument.doc_id == RagChunk.doc_id)
        .where(
            RagDocument.state == "active",
            RagDocument.is_current.is_(True),
            RagChunkEmbedding.model == model,
            RagChunkEmbedding.dimensions == dimensions,
            RagChunkEmbedding.provider == provider,
        )
    )
    if plan.mode == "record" or plan.filters.get("doc_id"):
        if plan.mode == "record":
            stmt = stmt.where(RagChunk.kind == "record")
        _multi_store = tuple(getattr(plan.state, "stores", ()) or ())
        if len(_multi_store) > 1:
            stmt = stmt.where(
                or_(*(func.json_extract(RagChunk.filters_norm, "$.store") == normalize(item)
                      for item in _multi_store))
            )
        for key, value in plan.filters.items():
            if key == "doc_id":
                stmt = stmt.where(RagChunk.doc_id == value)
                continue
            if plan.mode != "record":
                continue
            if key not in ("store", "item", "product", "channel", "price_type", "identifier"):
                continue
            normalized = normalize(value)
            stores = tuple(getattr(plan.state, "stores", ()) or ())
            if key == "store" and len(stores) > 1:
                stmt = stmt.where(
                    or_(*(func.json_extract(RagChunk.filters_norm, "$.store") == normalize(item) for item in stores))
                )
                continue
            if key == "channel":
                stmt = stmt.where(
                    or_(
                        func.json_extract(RagChunk.filters_norm, "$.channel") == normalized,
                        func.json_extract(RagChunk.filters_norm, "$.channels").like(f'%"{normalized}"%'),
                    )
                )
            else:
                stmt = stmt.where(func.json_extract(RagChunk.filters_norm, f"$.{key}") == normalized)
    if plan.as_of and not plan.include_future:
        stmt = stmt.where(
            or_(RagChunk.effective_from.is_(None), RagChunk.effective_from == "", RagChunk.effective_from <= plan.as_of),
            or_(RagChunk.effective_to.is_(None), RagChunk.effective_to == "", RagChunk.effective_to >= plan.as_of),
            or_(RagDocument.effective_from.is_(None), RagDocument.effective_from == "", RagDocument.effective_from <= plan.as_of),
            or_(RagDocument.effective_to.is_(None), RagDocument.effective_to == "", RagDocument.effective_to >= plan.as_of),
        )
    rows = session.execute(stmt).all()
    if not rows:
        return [], None
    vectors: list[np.ndarray] = []
    chunks: list[IndexedChunk] = []
    from .index import _row_to_chunk

    expected_bytes = dimensions * 4
    for chunk_row, blob in rows:
        if blob is None or len(blob) != expected_bytes:
            continue
        vector = np.frombuffer(blob, dtype=np.float32)
        if vector.shape[0] != dimensions:
            continue
        vectors.append(vector)
        chunks.append(_row_to_chunk(chunk_row))
    if not vectors:
        return [], "VECTOR_CACHE_EMPTY"
    matrix = np.vstack(vectors).astype(np.float32, copy=False)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    matrix = matrix / norms
    # 先对全部候选打分，再排序；不在打分前截断。
    scores = matrix @ query_vector
    order = np.argsort(-scores, kind="stable")
    limit = min(len(chunks), max(index.config.vector_candidate_limit, 1))
    selected: list[IndexedChunk] = []
    for position in order[:limit]:
        chunk = chunks[int(position)]
        selected.append(chunk)
    diagnostics["vector_candidates"] = len(chunks)
    diagnostics["vector_scored"] = len(chunks)
    diagnostics["vector_query_ms"] = round((time.monotonic() - started) * 1000, 2)
    return selected, None


def _passes_filters(chunk: IndexedChunk, plan: QueryPlan) -> bool:
    if plan.mode != "record":
        if plan.filters.get("doc_id") and chunk.doc_id != plan.filters["doc_id"]:
            return False
        if plan.as_of and not plan.include_future:
            if chunk.effective_from and chunk.effective_from > plan.as_of:
                return False
            if chunk.effective_to and chunk.effective_to < plan.as_of:
                return False
        return True
    if plan.filters.get("doc_id") and chunk.doc_id != plan.filters["doc_id"]:
        return False
    for key, value in plan.filters.items():
        if key in ("store", "item", "product", "price_type", "identifier"):
            stores = tuple(getattr(plan.state, "stores", ()) or ())
            if key == "store" and len(stores) > 1:
                if chunk.filters_norm.get("store") not in {normalize(item) for item in stores}:
                    return False
            elif chunk.filters_norm.get(key) != normalize(value):
                return False
        elif key == "channel":
            normalized = normalize(value)
            primary = chunk.filters_norm.get("channel")
            channels = chunk.filters_norm.get("channels") or ()
            if primary != normalized and normalized not in channels:
                return False
    if plan.as_of and not plan.include_future:
        if chunk.effective_from and chunk.effective_from > plan.as_of:
            return False
        if chunk.effective_to and chunk.effective_to < plan.as_of:
            return False
    return True


def _fuse(
    index: Any,
    plan: QueryPlan,
    exact: list[IndexedChunk],
    lexical: list[IndexedChunk],
    vector: list[IndexedChunk],
    diagnostics: dict[str, Any],
) -> list[tuple[IndexedChunk, float]]:
    rrf: dict[str, float] = {}
    by_id: dict[str, IndexedChunk] = {}
    channels: dict[str, set[str]] = {}
    filter_stats = {"candidates": 0, "passed": 0}

    def add(items: Iterable[IndexedChunk], weight: float, name: str) -> None:
        for rank, chunk in enumerate(items):
            filter_stats["candidates"] += 1
            if not _passes_filters(chunk, plan):
                continue
            filter_stats["passed"] += 1
            by_id.setdefault(chunk.chunk_id, chunk)
            channels.setdefault(chunk.chunk_id, set()).add(name)
            rrf[chunk.chunk_id] = rrf.get(chunk.chunk_id, 0.0) + weight / (RRF_K + rank + 1)

    with trace_attrs.span("hard_filter") as filter_span:
        add(exact, EXACT_WEIGHT, "exact")
        add(lexical, LEXICAL_WEIGHT, "lexical")
        add(vector, VECTOR_WEIGHT, "vector")
        filter_span.annotate(
            candidates=filter_stats["candidates"],
            passed=filter_stats["passed"],
            dropped=filter_stats["candidates"] - filter_stats["passed"],
        )
    for chunk in exact:
        if chunk.chunk_id in rrf:
            rrf[chunk.chunk_id] += 0.004
    ranked = sorted(
        ((by_id[chunk_id], score) for chunk_id, score in rrf.items()),
        key=lambda item: (-item[1], item[0].chunk_id),
    )
    diagnostics["fused_candidates"] = len(ranked)
    diagnostics["channels"] = {key: sorted(value) for key, value in channels.items()}
    if not ranked:
        return []
    rerank_candidates = ranked[: max(1, index.config.rerank_top_n)]
    rerank_started = time.monotonic()
    with trace_attrs.span("rerank") as rerank_span:
        try:
            response = index.reranker.rerank(
                plan.question,
                [chunk.text for chunk, _ in rerank_candidates],
                top_n=len(rerank_candidates),
            )
            scores = {result.index: result.score for result in response.results}
            maximum = max(scores.values(), default=0.0) or 1.0
            reranked: list[tuple[IndexedChunk, float]] = []
            for position, (chunk, rrf_score) in enumerate(rerank_candidates):
                rerank_score = scores.get(position, 0.0) / maximum
                combined = 0.5 * _normalize_score(rrf_score, ranked) + 0.5 * rerank_score
                reranked.append((chunk, combined))
            reranked.sort(key=lambda item: (-item[1], item[0].chunk_id))
            # 未进入重排的候选保留较低 RRF 分数，排在重排候选之后。
            head_ids = {chunk.chunk_id for chunk, _ in reranked}
            tail = [(chunk, score * 0.5) for chunk, score in ranked if chunk.chunk_id not in head_ids]
            diagnostics["rerank"] = {
                "provider": getattr(response, "provider", None),
                "model": getattr(response, "model", None),
                "candidates": len(rerank_candidates),
                "usage": dict(getattr(response, "usage", {}) or {}),
                "estimated_list_price_cny": getattr(response, "estimated_list_price_cny", 0.0),
                "ms": round((time.monotonic() - rerank_started) * 1000, 2),
            }
            rerank_span.annotate(
                candidates=len(rerank_candidates),
                provider=getattr(response, "provider", None),
                model=getattr(response, "model", None),
                scored=len(scores),
            )
            return reranked + tail
        except Exception as exc:
            diagnostics["rerank_error"] = getattr(exc, "code", type(exc).__name__)
            diagnostics["rerank"] = {"error": diagnostics["rerank_error"]}
            # 既有语义是“重排失败回退 RRF、异常不外抛”；Span 记录错误状态，不改变控制流。
            rerank_span.annotate(status="error", error_code=diagnostics["rerank_error"])
            return ranked


def _normalize_score(score: float, ranked: list[tuple[IndexedChunk, float]]) -> float:
    maximum = max((item[1] for item in ranked), default=0.0) or 1.0
    return max(0.0, min(1.0, score / maximum))


def _enumerate_base(exact: list[IndexedChunk], fused: list[tuple[IndexedChunk, float]]) -> list[IndexedChunk]:
    chunks = exact or [chunk for chunk, _ in fused]
    seen: set[str] = set()
    result: list[IndexedChunk] = []
    for chunk in chunks:
        key = chunk.record_unit_id or chunk.chunk_id
        if key in seen:
            continue
        seen.add(key)
        result.append(chunk)
    result.sort(key=lambda chunk: (chunk.label or "", chunk.entity_key or "", chunk.chunk_id))
    return result


def _to_evidence(
    session: Session,
    index: Any,
    plan: QueryPlan,
    chunks: list[IndexedChunk],
    *,
    fused_scores: Mapping[str, float],
) -> list[EvidenceItem]:
    if not chunks:
        return []
    doc_ids = sorted({chunk.doc_id for chunk in chunks})
    docs = {
        row.doc_id: row
        for row in session.execute(select(RagDocument).where(RagDocument.doc_id.in_(doc_ids))).scalars().all()
    }
    current_revision = index.revision()
    evidence: list[EvidenceItem] = []
    for chunk in chunks:
        doc = docs.get(chunk.doc_id)
        if doc is None:
            continue
        locator = dict(chunk.locator or {})
        citation = Citation(
            source_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            source_path=doc.source_path,
            title=doc.title,
            version_id=doc.version_id,
            version_label=doc.version_label,
            revision=current_revision,
            locator=locator,
            text=chunk.text,
            kind=chunk.kind,
            unit_ids=tuple(str(unit_id) for unit_id in (chunk.unit_ids or ())),
        )
        evidence.append(
            EvidenceItem(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                source_path=doc.source_path,
                title=doc.title,
                version_id=doc.version_id,
                version_label=doc.version_label,
                revision=current_revision,
                kind=chunk.kind,
                text=chunk.text,
                sheet=chunk.sheet,
                locator=locator,
                fields=dict(chunk.fields),
                citation=citation,
                scores={"fused": round(float(fused_scores.get(chunk.chunk_id, 0.0)), 6)},
                effective_status=_effective_status(chunk, plan),
            )
        )
    return evidence


def _effective_status(chunk: IndexedChunk, plan: QueryPlan) -> str:
    if plan.as_of:
        if chunk.effective_from and chunk.effective_from > plan.as_of:
            return "future"
        if chunk.effective_to and chunk.effective_to < plan.as_of:
            return "expired"
    return "current"
