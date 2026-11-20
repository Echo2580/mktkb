"""精确/FTS/向量混合召回、硬过滤、融合与重排。

- 明确实体/商品/渠道/价格类型/业务日期在打分前执行硬过滤；
- 向量候选先全部打分再截断，不会因宽 OR 超过 100 候选直接拒答；
- 融合使用 RRF，重排只调整顺序，不改变硬过滤结果；
- “全部”按完整条件集合分页，不用 Top-K 冒充总数。
"""

from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import Any, Iterable, Mapping

import numpy as np
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from ..observability import trace_attrs
from ..observability.evaluation_capture import capture_enabled
from ..retrieval.tokenize import match_expression, normalize
from .errors import KnowledgeChanged
from .models import RagChunk, RagChunkEmbedding, RagDocument, RagEmbeddingCache
from .types import Citation, EvidenceItem, IndexedChunk, QueryPlan, RetrievalResult

RRF_K = 60
EXACT_WEIGHT = 2.2
LEXICAL_WEIGHT = 1.0
VECTOR_WEIGHT = 1.0


def search(
    index: Any,
    plan: QueryPlan,
    *,
    limit: int | None = None,
    diag: dict[str, str] | None = None,
) -> RetrievalResult:
    """混合召回并返回证据。

    ``diag`` 只服务 R0/C12 诊断：各早退/丢弃点按固定码写入 ``{丢弃点: 枚举码}``
    （``exact`` -> ``kind_miss``、``lexical`` -> ``term_miss``、
    ``vector`` -> ``vector_unavailable``、``filter`` -> ``filter_miss``、
    ``dedup`` -> ``dedup_dropped``、``limit`` -> ``limit_dropped``）。
    默认 ``None`` 时不建键、不改控制流、不新增查询，结果与加参数前逐字相同。
    """
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
            if plan.mode != "record" and diag is not None:
                # 记录面精确通道只服务 record 计划：非 record 计划没有该通道。
                diag["exact"] = "kind_miss"
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
            if diag is not None and not diagnostics.get("lexical_expression"):
                # 检索词为空 → ``match_expression(())`` 返回 None（C12 根因之一）。
                diag["lexical"] = "term_miss"
            if vector_enabled:
                with trace_attrs.span("vector_recall") as vector_span:
                    vector_chunks, vector_error = _vector_recall(
                        session, index, plan, diagnostics, diag=diag
                    )
                    vector_span.annotate(
                        candidates=len(vector_chunks),
                        degraded=bool(vector_error),
                        degraded_reason=vector_error,
                    )
            else:
                vector_chunks, vector_error = _vector_recall(
                    session, index, plan, diagnostics, diag=diag
                )
            if vector_error:
                degraded.append("vector")
                diagnostics["vector_error"] = vector_error
                if diag is not None:
                    diag["vector"] = "vector_unavailable"
            recall_span.annotate(
                exact=len(exact_chunks),
                lexical=len(lexical_chunks),
                vector=len(vector_chunks),
                hints=len(hints),
                vector_enabled=vector_enabled,
            )
        with trace_attrs.span("fuse") as fuse_span:
            fused = _fuse(
                index, plan, exact_chunks, lexical_chunks, vector_chunks, diagnostics, diag=diag
            )
            # 重排只在融合结果非空时真实执行（_fuse 内创建 rerank Span 并写 diagnostics["rerank"]）。
            rerank_enabled = "rerank" in diagnostics
            fuse_span.annotate(candidates=len(fused), rerank_enabled=rerank_enabled)
        if plan.enumerate:
            base = _enumerate_base(exact_chunks, [] if plan.record_field_stores else fused, diag=diag)
            total = len(base)
            page = max(1, int(plan.page))
            page_size = max(1, min(plan.page_size, index.config.max_page_size))
            start = (page - 1) * page_size
            page_items = base[start : start + page_size]
            has_more = start + len(page_items) < total
            if diag is not None and has_more:
                diag["limit"] = "limit_dropped"
            next_page = page + 1 if has_more else None
            evidence = _to_evidence(session, index, plan, page_items, fused_scores={c.chunk_id: s for c, s in fused})
            diagnostics["enumeration"] = True
            diagnostics["total"] = total
            diagnostics["page"] = page
            diagnostics["page_size"] = page_size
        else:
            selected = fused[:top_k]
            if diag is not None and len(fused) > len(selected):
                diag["limit"] = "limit_dropped"
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
        # v3-fix-1/A：同一轮明确点名多个物品时，证据面只取这些物品（与多门店同口径），
        # 目标之外的行不参与作答，避免把“多目标”变成“整表枚举”。
        _multi_item = tuple(getattr(plan.state, "items", ()) or ())
        if len(_multi_item) > 1:
            stmt = stmt.where(
                or_(*(func.json_extract(RagChunk.filters_norm, "$.item") == normalize(item)
                      for item in _multi_item))
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


#: 只登记在店家信息行上的字段角色（与 ``retrieval.service._STORE_LEVEL_FIELD_ROLES`` 同口径）。
_STORE_LEVEL_ROLES = frozenset({"contact", "phone", "address", "status"})
#: 只登记在物品位置行上的字段角色（与 ``retrieval.service._ITEM_LEVEL_FIELD_ROLES`` 同口径）。
_ITEM_LEVEL_ROLES = frozenset({"location"})


def _requested_roles(plan: QueryPlan) -> set[str]:
    """本问请求的字段角色集合（多字段轮次取 ``field_roles``，单字段轮次取 ``field_role``）。"""
    requested = set(getattr(plan, "field_roles", ()) or ())
    if plan.field_role:
        requested.add(plan.field_role)
    return requested


#: ``diagnostics["store_join"]["status"]`` 的固定码（R2-202D）。只编码判定结果，不带门店名、
#: 行数等任何业务值；``joined`` 表示确实并入了店家行，另外两个码表示 fail-closed 未联结。
STORE_JOIN_JOINED = "joined"
STORE_JOIN_MISSING = "store_row_missing"
STORE_JOIN_AMBIGUOUS = "store_row_ambiguous"


class _StoreJoin(tuple):
    """``_store_join_chunks`` 的返回：``(store_value, store_rows)`` 二元组 + 判定码。

    R2-202D 的唯一性守卫要在诊断里区分「已联结 / 无店家行 / 店家行不唯一」。既有调用方
    （含 202A/202C/204 的敏感性开关）都按**二元组**解包或整体替换本函数，因此判定码作为
    ``status`` 属性随值返回，不改元数、不改解包写法；被替换成裸二元组时视为未知。
    """

    def __new__(cls, store: str, rows: list[IndexedChunk], status: str, observed: str = "unknown") -> "_StoreJoin":
        value = super().__new__(cls, (store, rows))
        value.status = status
        value.observed = observed
        return value


def _store_row_is_unique(store_rows: list[IndexedChunk]) -> bool:
    """按派生门店值命中的店家行是否**恰好 1 条**（按记录身份计；一行拆多 chunk 仍算 1 条）。"""
    return len({chunk.record_unit_id or chunk.chunk_id for chunk in store_rows}) == 1


def _store_join_chunks(session: Session, plan: QueryPlan) -> tuple[str, list[IndexedChunk]]:
    """「物品字段 + 店家级字段」同问时，按唯一物品行反推门店并取同门店店家行（R2-202C）。

    R0/C12 的同类取数只在 legacy 取证路径（``retrieval.service._retrieve_records``）生效；
    rag 直答的枚举轮次里，``$.item`` 等值过滤会把店家行整体排除，店家级字段（合作状态/
    联系人等）因此没有任何来源。这里只做**额外取数**，不改变既有过滤、排序与分页口径。

    fail-closed：以下任一条件不成立就返回空，行为与加本函数前逐字相同——
    - ``mode == "record"`` 且 ``enumerate``（rag 直答的枚举轮次）；
    - 请求角色**同时**含店家级角色与物品级角色（只问一侧时不跨表）；
    - 过滤条件含物品（``item``），且本轮物品/门店目标都不是多目标；
    - 物品行**唯一**（多行 = 多目标/歧义），且其门店值**唯一且非空**；
    - 同门店店家行落在**同一记录面上界**内（同一个 ``_base_stmt``：活动/当前资料 +
      记录有效期窗口），且确实存在；
    - R2-202D：同门店店家行**恰好 1 条**。0 条（门店值派生不出 / 店家表无该店 / 记录面
      过滤后无行）与 >1 条（同一 active 版本里的多行，可能是互斥状态值）一律**不联结**，
      并在 ``status`` 里留固定码 ``store_row_missing`` / ``store_row_ambiguous``。
      行基数不是版本语义：同版本两行都过记录面过滤，故只能按基数 fail-closed。
    """
    if plan.mode != "record" or not plan.enumerate:
        return _StoreJoin("", [], "", "not_record_or_enumerate")
    requested = _requested_roles(plan)
    if not requested & _STORE_LEVEL_ROLES or not requested & _ITEM_LEVEL_ROLES:
        return _StoreJoin("", [], "", "roles_not_cross_level")
    if not str(plan.filters.get("item") or "").strip():
        return _StoreJoin("", [], "", "item_filter_missing")
    if len(tuple(getattr(plan.state, "items", ()) or ())) > 1:
        return _StoreJoin("", [], "", "multiple_items")
    if len(tuple(getattr(plan.state, "stores", ()) or ())) > 1:
        return _StoreJoin("", [], "", "multiple_stores")
    item_rows = [
        chunk
        for chunk in _load(session, _base_stmt(session, plan, require_record=True))
        if chunk.entity_type == "item"
    ]
    if len({chunk.record_unit_id or chunk.chunk_id for chunk in item_rows}) != 1:
        return _StoreJoin("", [], "", "item_row_not_unique")
    stores = {normalize(str((chunk.filters_norm or {}).get("store") or "")) for chunk in item_rows}
    stores.discard("")
    if not stores:
        # 门店值派生不出：没有任何可按门店命中的店家行（= 命中 0 行）。
        return _StoreJoin("", [], STORE_JOIN_MISSING, "store_value_missing")
    if len(stores) > 1:
        # 同一物品行给出多个门店值：无法唯一确定要并哪一家的店家行。
        return _StoreJoin("", [], STORE_JOIN_AMBIGUOUS, "store_value_ambiguous")
    store_value = next(iter(stores))
    # 店家行同样经 ``_base_stmt``：活动/当前资料 + 记录与资料有效期窗口都按本问 as_of 过滤。
    store_rows = [
        chunk
        for chunk in _load(
            session,
            _base_stmt(session, replace(plan, filters={"store": store_value}), require_record=True),
        )
        if chunk.entity_type == "store"
    ]
    if not store_rows:
        return _StoreJoin("", [], STORE_JOIN_MISSING, "store_row_missing")
    if not _store_row_is_unique(store_rows):
        # 同门店多行（含互斥状态值）：并进去会让正文同时输出矛盾值，故 fail-closed 不联结。
        return _StoreJoin("", [], STORE_JOIN_AMBIGUOUS, "store_row_ambiguous")
    return _StoreJoin(store_value, store_rows, STORE_JOIN_JOINED, "rows_found")


def _exact_recall(session: Session, index: Any, plan: QueryPlan, diagnostics: dict[str, Any]) -> list[IndexedChunk]:
    if plan.mode != "record":
        return []
    if getattr(plan, "record_field_stores", None):
        chunks = _scoped_record_chunks(session, plan, diagnostics)
        diagnostics["exact_candidates"] = len(chunks)
        return chunks
    chunks = _load(session, _base_stmt(session, plan, require_record=True))
    chunks = [chunk for chunk in chunks if _has_role(chunk, plan.field_role)]
    # 多字段/多实体时保留全部精确命中；不在召回阶段截断。
    decision = _store_join_chunks(session, plan)
    store_value, store_rows = decision
    # R2-202D：判定码由 ``_store_join_chunks`` 随值返回。两个 fail-closed 码只登记「没联结」
    # 这一事实（固定码，不带门店名/行数）；被替换成裸二元组时视为未知，行为与加守卫前逐字相同。
    status = str(getattr(decision, "status", "") or "")
    observed = getattr(decision, "observed", "unknown")
    if status in (STORE_JOIN_MISSING, STORE_JOIN_AMBIGUOUS):
        diagnostics["store_join"] = {"status": status}
    elif store_rows:
        seen = {chunk.chunk_id for chunk in chunks}
        joined = [chunk for chunk in store_rows if chunk.chunk_id not in seen]
        if joined:
            # 只并入记录面候选，不参与 RRF/重排（店家行仍受原过滤口径约束）。
            chunks = chunks + joined
            payload: dict[str, Any] = {
                "store": store_value,
                "chunk_ids": [chunk.chunk_id for chunk in joined],
            }
            if status:
                payload["status"] = status
            diagnostics["store_join"] = payload
        if observed == "rows_found":
            observed = "joined" if joined else "already_present"
    if capture_enabled():
        diagnostics["store_join_observed"] = observed
    diagnostics["exact_candidates"] = len(chunks)
    return chunks


def _scoped_record_chunks(
    session: Session, plan: QueryPlan, diagnostics: dict[str, Any]
) -> list[IndexedChunk]:
    chunks: list[IndexedChunk] = []
    for role, store in plan.record_field_stores.items():
        filters = {**plan.filters, "store": store}
        if role == "status":
            filters.pop("item", None)
        scoped = replace(plan, filters=filters, state=replace(plan.state, store=store, stores=(store,)))
        rows = [
            row for row in _load(session, _base_stmt(session, scoped, require_record=True))
            if plan.scoped_record_role(row) == role
        ]
        if len({row.record_unit_id or row.chunk_id for row in rows}) > 1:
            diagnostics["scoped_record_ambiguity"] = store
            return []
        chunks.extend(row for row in rows if _has_role(row, role))
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
    session: Session,
    index: Any,
    plan: QueryPlan,
    diagnostics: dict[str, Any],
    *,
    diag: dict[str, str] | None = None,
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
        _multi_item = tuple(getattr(plan.state, "items", ()) or ())
        if plan.mode == "record" and len(_multi_item) > 1:
            stmt = stmt.where(
                or_(*(func.json_extract(RagChunk.filters_norm, "$.item") == normalize(item)
                      for item in _multi_item))
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
    if diag is not None and limit < len(chunks):
        # 向量窗口按配置截断：候选被 limit 丢掉。
        diag["limit"] = "limit_dropped"
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
    # The separately scoped store row is exact evidence only. Do not send its text to reranking.
    if plan.record_field_stores and plan.scoped_record_role(chunk) != "location":
        return False
    if plan.filters.get("doc_id") and chunk.doc_id != plan.filters["doc_id"]:
        return False
    for key, targets in (("store", plan.state.stores), ("item", plan.state.items)):
        if len(targets) > 1 and chunk.filters_norm.get(key) not in {normalize(target) for target in targets}:
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
    *,
    diag: dict[str, str] | None = None,
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
    if diag is not None and filter_stats["candidates"] > filter_stats["passed"]:
        # 硬过滤真实丢掉候选；同一 chunk 跨通道重复不是丢弃（归并在 _enumerate_base）。
        diag["filter"] = "filter_miss"
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


def _enumerate_base(
    exact: list[IndexedChunk],
    fused: list[tuple[IndexedChunk, float]],
    *,
    diag: dict[str, str] | None = None,
) -> list[IndexedChunk]:
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
    if diag is not None and len(result) < len(chunks):
        # 同一记录单元被拆成多个 chunk：按记录身份归并，真实减少候选行。
        diag["dedup"] = "dedup_dropped"
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
