"""应用工厂：组装配置、数据库、错误处理与路由。"""

from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request

from .auth.routes import router as auth_router
from .auth.service import bootstrap_accounts
from .config import Settings
from .conversations.routes import router as conversations_router
from .db import Database, run_migrations
from .documents.routes import router as documents_router
from .documents.service import Store, UploadLimits
from .errors import register_error_handlers
from .ingestion.routes import router as ingestion_router
from .observability import TraceMode, start_trace
from .observability.store import TraceRepository
from .providers import build_gateway, build_ocr_gateway
from .qa import QaEngine, QaNotReady, resolve_rag_config
from .sources.routes import router as sources_router

logger = logging.getLogger("mktkb")

APP_VERSION = "0.1.0"

#: 设计 §9：P0 只允许 replay / local，**禁止 live**。这里写死 LOCAL（不按 provider 模式分支），
#: 保证中间件永远不会把 live 传给 tracer 内核（内核接受该枚举，不会替调用方拦截）。
TRACE_MODE = TraceMode.LOCAL
#: 产品问答的执行尝试是端到端范围（设计 §6.3 scope）。
TRACE_SCOPE = "end_to_end"
#: 只对 QA 问答 POST 开启 Trace：conversations 路由的 ``POST /{conversation_id}/messages``。
#: 中间件运行在路由匹配之前，因此按 URL 路径精确匹配（不含查询串），其它端点一律不观测。
_QA_POST_PATH = re.compile(r"^/api/v1/conversations/[^/]+/messages$")


def _is_qa_post(request: Request) -> bool:
    """是否 QA 问答 POST（设计 §5 的 request_context 观测入口）。"""
    return request.method == "POST" and _QA_POST_PATH.fullmatch(request.url.path) is not None


def create_app(
    settings: Settings | None = None,
    *,
    initialize: bool = True,
    model_gateway=None,
    ocr_gateway=None,
    qa_engine=None,
) -> FastAPI:
    """按配置创建应用。initialize=True 时执行迁移与预置账号初始化（均幂等）。

    ``model_gateway``/``ocr_gateway`` 只供测试/受控环境注入可控适配器；生产由服务端配置构建。
    网关未配置时应用照常启动，仅问答返回 MODEL_NOT_CONFIGURED、扫描页返回 OCR_NOT_CONFIGURED。
    """
    settings = settings or Settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    database = Database(
        settings.resolved_database_url(),
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        enable_wal=settings.enable_wal,
    )
    gateway = model_gateway if model_gateway is not None else build_gateway(settings)
    # 只给**本函数自己构建的**生产网关挂版本化结算策略：注入的替身（测试/受控环境）
    # 没有该方法也不该被改造；否则 create_app 会在替身上 AttributeError。
    attach = getattr(gateway, "attach_settlement_policy", None) if model_gateway is None else None
    if gateway is not None and callable(attach) and getattr(gateway, "settlement_policy", None) is None:
        # 真实应用路径也必须按实际 usage 结算：否则旧结算语义下的
        # max(reserve, estimate) 永远是全额预留（真实 UI 实测每问留账 2.103552 元）。
        # 策略与受控执行同源（build_policy("chat")），cap/费率/来源仍由 J1 精确固化。
        try:
            from .rag.settlement_policy import build_policy

            attach(build_policy("chat", model=str(getattr(settings, "model_name", "") or "")))
        except ValueError as exc:
            raise ValueError(f"chat live 版本化结算装配拒绝：{exc}") from None
    ocr_gateway = ocr_gateway if ocr_gateway is not None else build_ocr_gateway(settings)
    # S2：rag 问答内核。构造本身不打开索引库；live 供应商必须显式给出预算入口（默认拒绝）。
    if qa_engine is None and settings.rag_qa_enabled:
        rag_config, rag_budget = resolve_rag_config(
            data_dir=settings.data_dir,
            provider_mode=settings.rag_provider_mode,
            page_size=settings.rag_page_size,
            top_k=settings.rag_top_k,
            business_date=settings.rag_business_date,
        )
        qa_engine = QaEngine(
            database,
            settings.resolved_rag_index_path,
            config=rag_config,
            budget=rag_budget,
            embedding_retry_seconds=settings.rag_embedding_retry_seconds,
        )

    # 设计 §6.2：Trace 使用独立 SQLite。默认关闭时**完全不构造**仓储（不建目录、不建库文件、
    # 不产生任何副作用）；开启时才创建，写入失败由仓储/内核 best-effort 兜底（设计 §6.6）。
    trace_repo = TraceRepository(settings.resolved_trace_db_path) if settings.trace_enabled else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        closer = getattr(gateway, "aclose", None)
        if closer is not None:
            await closer()
        ocr_closer = getattr(ocr_gateway, "close", None)
        if ocr_closer is not None:
            ocr_closer()
        qa_closer = getattr(qa_engine, "close", None)
        if qa_closer is not None:
            qa_closer()
        if trace_repo is not None:
            trace_repo.close()
        database.dispose()

    app = FastAPI(title=settings.app_name, version=APP_VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = database
    app.state.model_gateway = gateway
    app.state.ocr_gateway = ocr_gateway
    app.state.qa = qa_engine
    app.state.trace_repo = trace_repo
    # 存储目录在首次使用时创建（initialize=False 的 OpenAPI 检查不写运行目录）
    app.state.store = Store(settings.resolved_storage_dir, UploadLimits.from_settings(settings))

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        request.state.trace_id = None
        # 只对 QA 问答 POST 开启 Trace（设计 §5/§6.1）：用 contextvars 覆盖下游整个调用链，
        # T003c/d 可在业务路径里通过 current_trace() 继续埋 Span（本包不埋业务 Span）。
        if trace_repo is not None and _is_qa_post(request):
            with start_trace(
                http_request_id=request.state.request_id,
                mode=TRACE_MODE,
                scope=TRACE_SCOPE,
                repo=trace_repo,
                content_mode=settings.trace_content_mode,
                hmac_key=settings.trace_hmac_key_bytes,
            ) as trace:
                request.state.trace_id = trace.trace_id
                response = await call_next(request)
                # 设计 §10：唯一允许新增的响应头；body 与请求参数结构完全不变。
                response.headers["X-Trace-ID"] = trace.trace_id
                response.headers["X-Request-ID"] = request.state.request_id
                return response
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    register_error_handlers(app)

    if initialize:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        run_migrations(settings.resolved_database_url())
        with database.session_scope() as session:
            created = bootstrap_accounts(
                session,
                admin_username=settings.admin_username,
                admin_password=settings.admin_password,
                admin_display_name=settings.admin_display_name,
                employee_username=settings.employee_username,
                employee_password=settings.employee_password,
                employee_display_name=settings.employee_display_name,
                rounds=settings.bcrypt_rounds,
            )
        if created:
            logger.info("accounts_initialized count=%s", len(created))
        if qa_engine is not None and settings.rag_sync_on_startup:
            # 启动配置：在业务库迁移完成后同步一次索引；失败只记录状态，查询入口会明确返回
            # INDEX_NOT_READY，不静默使用过期索引。
            try:
                qa_engine.ensure_ready()
                logger.info("rag_index_ready revision=%s", qa_engine.status().get("product_revision"))
            except QaNotReady as exc:
                logger.warning("rag_index_not_ready code=%s", exc.error_code)

    api = APIRouter(prefix="/api/v1")
    api.include_router(auth_router)
    api.include_router(documents_router)
    api.include_router(ingestion_router)
    api.include_router(conversations_router)
    api.include_router(sources_router)

    @api.get("/healthz", tags=["health"], summary="最小健康检查")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api)
    return app


app = None  # 由部署入口（如 `uvicorn mktkb.main:create_app --factory`）创建
