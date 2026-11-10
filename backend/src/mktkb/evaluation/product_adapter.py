"""P2-T203 产品端到端适配器：在隔离目录里跑**用户同一产品入口**。

为什么单独一个模块（任务书 §5 / §6.2 / §8 T203）：
- P2 评测必须证明「产品真的这么答」，而不是「评测器自己调 RagIndex.ask 拼一个答案」。
  所以本适配器只在 ``out_dir`` 下建一套隔离的业务库 / 索引库 / 存储 / trace 库 / 账号，
  然后**全部经由 HTTP（ASGI）**走现有路由：
  上传 -> worker 解析 -> 发布 -> 提问 -> 来源详情；不复制产品逻辑，也不改产品 schema。
- 零真实调用是硬约束：chat 用**真实** ``DeepSeekClient`` + ``httpx.MockTransport``（走真实
  provider 编解码，但不出网），embedding/rerank 用可计数的离线替身（``FakeEmbeddingProvider``
  / ``LexicalReranker`` 的计数包装）。适配器自己记账每次 provider 调用，供 runner 与测试断言
  「RAG / legacy 两条分支都经过了产品入口」且「真实出站 = 0」。
- 不构造真实 provider：默认不注入 chat 网关，``create_app`` 在没有模型配置时返回 ``None``，
  问答以 ``MODEL_NOT_CONFIGURED`` 明确失败（而不是偷偷造一个能发送的客户端）。

冻结接口（§6.2，本包不改签名）：``async ingest(plan)``、``async ask_turn(question, *, user_id,
conversation_id, client_request_id)``、``async close()``；其他方法都是适配器自用的观测面。

边界：不读 ``.env``（``Settings(_env_file=None)``）、不碰原 ``var/`` 业务库、不发真实 HTTP、
不写共享账本/GO；真实发送与真实结算属 T206/T207。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

import httpx

from ..config import Settings
from ..conversations.service import BUDGET_SECONDS as _CONVERSATION_BUDGET_SECONDS
from ..documents.lifecycle import get_revision
from ..ingestion.worker import run_one_job
from ..main import create_app
from ..providers.deepseek import DeepSeekClient
from ..providers.types import OCRNotConfigured
from ..qa import QaEngine
from ..rag import RagConfig
from ..rag.providers import FakeEmbeddingProvider, LexicalReranker
from ..rag.types import EmbeddingResponse, RerankResponse
from .dataset import CaseSpec

__all__ = [
    "ChatBehavior",
    "IngestReceipt",
    "IngestSource",
    "MockChatBackend",
    "MockEmbeddingProvider",
    "MockReranker",
    "P2IngestPlan",
    "P2RunDataset",
    "PRODUCT_TURN_TIMEOUT_SECONDS",
    "ProductEvalAdapter",
    "ProductPaths",
    "ProductTurn",
    "case_questions",
    "utc_iso",
]

PRODUCT_TURN_TIMEOUT_SECONDS = float(_CONVERSATION_BUDGET_SECONDS)
"""T203 反例「超时」用的产品口径：单轮 60 秒总时限。适配器在**客户端侧**再套一层同样的
硬截止（``asyncio.wait_for``），迟到响应不会把 run 拖成挂起；这不是新增产品限额。"""

P2_ADAPTER_SCHEMA_VERSION = "p2-product-adapter/v0.1"
P2_INGEST_PLAN_SCHEMA_VERSION = "p2-ingest-plan/v0.1"

ORIGIN = "http://p2-eval.testserver"
"""隔离应用自己的受信任 Origin（只用于 CSRF/Origin 校验，不出网）。"""

MOCK_PROVIDER = "p2-mock"
MOCK_CHAT_MODEL = "mock-chat"
MOCK_CHAT_BASE_URL = "http://mock.invalid"
MOCK_CHAT_API_KEY = "p2-mock-not-a-secret"
MOCK_EMBEDDING_MODEL = "text-embedding-v4"
MOCK_RERANK_MODEL = "gte-rerank-v2"

_IDENTITY_KEYS = (
    "dataset_version",
    "label_version",
    "suite",
    "manifest_sha256",
    "case_count",
)
_VISIBILITIES = ("public", "holdout")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(moment: datetime | None = None) -> str:
    return (moment or _utc_now()).astimezone(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# 网络边界实测（F1：产物里的"零出站"必须是测量结果，不是常量）
# --------------------------------------------------------------------------- #


@dataclass
class NetworkMeter:
    """一次 run 的网络边界实测：区分「真实出站尝试」与「本地 Mock 拦截」。

    真实出站由注入给 ``DeepSeekClient`` 的**传输层**计数（MockTransport 一律记拦截，不出网）；
    RAG 供应商 POST 用既有机器计数 ``rag.providers.post_counters()`` 的进程内增量。
    本地替身（embedding/rerank）没有传输层，其出站恒为 0 由实现保证，而不是声明。
    """

    outbound_attempts: int = 0
    mock_intercepted: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "outbound_attempts": int(self.outbound_attempts),
            "mock_intercepted": int(self.mock_intercepted),
        }


class _MeteredTransport(httpx.AsyncBaseTransport):
    """包住注入的传输：``MockTransport`` 记「拦截」，其余一律记「真实出站尝试」。"""

    def __init__(self, inner: httpx.AsyncBaseTransport, meter: NetworkMeter) -> None:
        self._inner = inner
        self._meter = meter

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if isinstance(self._inner, httpx.MockTransport):
            self._meter.mock_intercepted += 1
        else:
            self._meter.outbound_attempts += 1
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        closer = getattr(self._inner, "aclose", None)
        if closer is not None:
            await closer()


def _rag_provider_posts() -> int:
    """RAG 供应商真实 POST 次数（既有机器计数的进程内累计，只数 attempts）。"""
    from ..rag.providers import post_counters

    return sum(int(value) for value in (post_counters().get("attempts") or {}).values())


# --------------------------------------------------------------------------- #
# 数据集（跑什么）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class P2RunDataset:
    """一次 P2 run 的题目与身份绑定（不含答案；答案属 T205）。

    ``visibility="holdout"`` 时 runner 只写聚合、不出逐题行；题目文本一律不进产物。
    ``identity`` 是 run_manifest 里绑定 dataset/manifest 的那一段，键固定，避免各包自造。
    """

    visibility: str
    cases: tuple[CaseSpec, ...]
    identity: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.visibility not in _VISIBILITIES:
            raise ValueError("dataset.visibility 必须是 public/holdout")
        if not isinstance(self.cases, tuple):
            raise ValueError("dataset.cases 必须是 tuple")
        for case in self.cases:
            if not isinstance(case, CaseSpec):
                raise ValueError("dataset.cases 只接受 CaseSpec")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("dataset.cases 存在重复 case_id")
        if not isinstance(self.identity, Mapping):
            raise ValueError("dataset.identity 必须是映射")
        missing = sorted(set(_IDENTITY_KEYS) - set(self.identity))
        if missing:
            raise ValueError(f"dataset.identity 缺少字段 {missing}")
        sha = str(self.identity["manifest_sha256"]).strip().lower()
        if len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
            raise ValueError("dataset.identity.manifest_sha256 必须是 64 位十六进制")
        count = self.identity["case_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("dataset.identity.case_count 必须是非负整数")
        if count != len(self.cases):
            raise ValueError("dataset.identity.case_count 与 cases 数量不一致")

    @property
    def public_details(self) -> bool:
        return self.visibility == "public"

    def as_dict(self) -> dict[str, Any]:
        payload = {name: self.identity[name] for name in _IDENTITY_KEYS}
        payload.update(
            {
                "visibility": self.visibility,
                "case_count_loaded": len(self.cases),
                "strata": dict(self.identity.get("strata") or {}),
                "declared_case_count": int(self.identity.get("declared_case_count") or self.identity["case_count"]),
            }
        )
        return payload

    @classmethod
    def from_p2_dataset(
        cls, dataset: Any, *, cases: Sequence[CaseSpec] | None = None
    ) -> "P2RunDataset":
        """从 T202 的 ``P2Dataset`` 取身份（public 视图没有题目，必须显式给 cases）。"""
        manifest = dataset.manifest
        chosen = tuple(cases if cases is not None else getattr(dataset, "cases", ()))
        declared = int(manifest.case_count)
        identity: dict[str, Any] = {
            "dataset_version": manifest.dataset_version,
            "label_version": manifest.label_version,
            "suite": manifest.suite,
            "manifest_sha256": manifest.manifest_sha256,
            "case_count": len(chosen),
            "declared_case_count": declared,
            "strata": dict(manifest.strata),
            "turn_stats": {
                "total_turns": int(manifest.turn_stats["total_turns"]),
                "max_turns_per_case": int(manifest.turn_stats["max_turns_per_case"]),
            },
        }
        return cls(visibility=dataset.visibility, cases=chosen, identity=identity)


def case_questions(case: CaseSpec) -> tuple[str, ...]:
    """一条 case 的逐轮问题：``turns`` >=2 走多轮（同会话顺序执行），否则单轮。

    兼容 ``text``（P0/P1 fixture）与 ``question``（holdout 导出）两种轮次形态；非 ``user``
    轮或空文本 fail closed——不把别人写的话当用户提问（与 P1 runner 同口径）。
    """
    if len(case.turns) < 2:
        return (case.question,)
    questions: list[str] = []
    for index, turn in enumerate(case.turns, start=1):
        if not isinstance(turn, Mapping):
            raise ValueError(f"{case.case_id}: turns[{index}] 必须是对象")
        role = turn.get("role")
        if role not in (None, "", "user"):
            raise ValueError(f"{case.case_id}: turns[{index}].role 只允许 user")
        text = turn.get("question") or turn.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{case.case_id}: turns[{index}] 缺少可执行的 question/text")
        questions.append(text.strip())
    return tuple(questions)


# --------------------------------------------------------------------------- #
# 灌库计划（怎么把语料变成产品可见资料）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class IngestSource:
    """一份要经产品上传/解析/发布路径进入隔离知识库的本地文件。"""

    path: Path
    name: str | None = None
    document_id: str | None = None
    expected_active_version_id: str | None = None
    allow_same_name: bool = False
    publish: bool = True

    def __post_init__(self) -> None:
        path = Path(self.path)
        if not path.is_file():
            raise ValueError(f"ingest source 不存在: {path}")
        object.__setattr__(self, "path", path)
        name = (self.name or path.name).strip()
        if not name:
            raise ValueError("ingest source 的 name 不得为空")
        object.__setattr__(self, "name", name)
        if self.document_id is None and self.expected_active_version_id is not None:
            raise ValueError("expected_active_version_id 只用于给既有资料上传新版本")
        if self.document_id is not None:
            uuid.UUID(str(self.document_id))
        if self.expected_active_version_id is not None:
            uuid.UUID(str(self.expected_active_version_id))

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "bytes": self.path.stat().st_size,
            "document_id": self.document_id,
            "publish": bool(self.publish),
        }


@dataclass(frozen=True)
class P2IngestPlan:
    """``ProductEvalAdapter.ingest(plan)`` 的入参（顺序即上传/发布顺序）。"""

    sources: tuple[IngestSource, ...]
    label: str = ""
    schema_version: str = P2_INGEST_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.sources, tuple) or not self.sources:
            raise ValueError("ingest plan.sources 必须是非空元组")
        for source in self.sources:
            if not isinstance(source, IngestSource):
                raise ValueError("ingest plan.sources 只接受 IngestSource")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "label": self.label,
            "sources": [source.as_dict() for source in self.sources],
        }


@dataclass(frozen=True)
class IngestReceipt:
    """一份资料的灌库回执：只含身份/状态/计数，不含正文。"""

    name: str
    sha256: str
    document_id: str
    version_id: str
    job_state: str
    published: bool
    revision: int | None
    upload_status: int
    publish_status: int | None
    units: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sha256": self.sha256,
            "document_id": self.document_id,
            "version_id": self.version_id,
            "job_state": self.job_state,
            "published": bool(self.published),
            "revision": self.revision,
            "upload_status": int(self.upload_status),
            "publish_status": None if self.publish_status is None else int(self.publish_status),
            "units": self.units,
        }


# --------------------------------------------------------------------------- #
# Mock provider（可计数、可编排失败）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ChatBehavior:
    """一次 chat 调用的 Mock 行为（默认正常作答）。"""

    kind: str = "answer"  # answer | http_error | connect_error | delay | invalid_json
    delay_seconds: float = 0.0
    status_code: int = 503
    answer: str | None = None

    def __post_init__(self) -> None:
        allowed = {"answer", "http_error", "connect_error", "delay", "invalid_json"}
        if self.kind not in allowed:
            raise ValueError(f"chat behavior.kind 只允许 {sorted(allowed)}")
        if self.delay_seconds < 0:
            raise ValueError("chat behavior.delay_seconds 不得为负")


class MockChatBackend:
    """真实 ``DeepSeekClient`` 的 ``httpx.MockTransport`` 后端：走 provider 编解码，不出网。

    - 默认按请求里的 evidence 生成**可被产品事实准入接受**的回答（正文型回显被引用来源
      原文；记录型按「字段名：原值」拼句），因此不是「评测器自己造答案」；
    - ``behaviors`` 按**调用序号**（从 0 开始）覆盖单次行为，用于还原 429/5xx/断网/迟到；
    - ``before_call`` 在生成响应前被 await，供反例注入「知识库在轮中变化」。
    """

    def __init__(
        self,
        *,
        behaviors: Sequence[ChatBehavior] = (),
        before_call: Callable[[int, Mapping[str, Any]], Awaitable[None] | None] | None = None,
        provider: str = MOCK_PROVIDER,
    ) -> None:
        self.behaviors = tuple(behaviors)
        self.before_call = before_call
        self.provider = provider
        self.calls: list[dict[str, Any]] = []
        self.transport = httpx.MockTransport(self._handle)
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- 观测面
    @property
    def call_count(self) -> int:
        return len(self.calls)

    def counts_by_purpose(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for call in self.calls:
            purpose = str(call["purpose"])
            counts[purpose] = counts.get(purpose, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": MOCK_CHAT_MODEL,
            "transport": "httpx.MockTransport",
            "calls": len(self.calls),
            "by_purpose": self.counts_by_purpose(),
            # 本类只统计被 MockTransport 接住的调用；真实出站由适配器的计量传输实测。
        }

    # ---------------------------------------------------------------- 行为
    async def _handle(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        body = self._body_of(payload)
        async with self._lock:
            index = len(self.calls)
            self.calls.append(
                {
                    "index": index,
                    "purpose": self._purpose_of(payload),
                    "url": f"{request.url.scheme}://{request.url.host}{request.url.path}",
                    "question_sha256": _sha256_text(str(body.get("question", ""))),
                    "evidence": len(body.get("evidence") or ()),
                }
            )
        behavior = self.behaviors[index] if index < len(self.behaviors) else ChatBehavior()
        if self.before_call is not None:
            hook = self.before_call(index, body)
            if hook is not None:
                await hook
        if behavior.kind == "connect_error":
            raise httpx.ConnectError("p2-mock: 禁止真实连接", request=request)
        if behavior.kind == "http_error":
            return httpx.Response(
                behavior.status_code,
                json={"error": {"message": "p2-mock 模拟供应商错误"}},
                request=request,
            )
        if behavior.delay_seconds > 0:
            await asyncio.sleep(behavior.delay_seconds)
        if behavior.kind == "invalid_json":
            return self._completion(request, "不是 JSON", call=index)
        if self.calls[index]["purpose"] == "query_expansion":
            return self._completion(request, json.dumps({"terms": []}), call=index)
        return self._completion(request, self._answer_json(body, behavior), call=index)

    @staticmethod
    def _body_of(payload: Mapping[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages") or []
        if len(messages) < 2:
            return {}
        content = messages[1].get("content")
        if not isinstance(content, str):
            return {}
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _purpose_of(payload: Mapping[str, Any]) -> str:
        messages = payload.get("messages") or []
        system = str(messages[0].get("content", "")) if messages else ""
        return "query_expansion" if "检索词" in system else "answer"

    def _answer_json(self, body: Mapping[str, Any], behavior: ChatBehavior) -> str:
        if behavior.answer is not None:
            return json.dumps(
                {"answer": behavior.answer, "source_ids": self._source_ids(body)},
                ensure_ascii=False,
            )
        evidence = [item for item in body.get("evidence") or () if isinstance(item, Mapping)]
        if not evidence:
            return json.dumps(
                {"answer": "资料中未记录相关信息。", "source_ids": []}, ensure_ascii=False
            )
        first = evidence[0]
        fields = first.get("fields") or {}
        if isinstance(fields, Mapping) and fields:
            clauses = [f"{key}：{value}" for key, value in list(fields.items())[:3]]
            text = "；".join(clauses)
        else:
            text = str(first.get("text") or "").strip()
        return json.dumps(
            {"answer": text or "资料中未记录相关信息。", "source_ids": self._source_ids(body)},
            ensure_ascii=False,
        )

    @staticmethod
    def _source_ids(body: Mapping[str, Any]) -> list[str]:
        ids: list[str] = []
        for item in body.get("evidence") or ():
            if not isinstance(item, Mapping):
                continue
            value = str(item.get("source_id") or "").strip()
            if value and value not in ids:
                ids.append(value)
        return ids[:2]

    def _completion(self, request: httpx.Request, content: str, *, call: int) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": f"p2-mock-chat-{call}",
                "object": "chat.completion",
                "model": MOCK_CHAT_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 64, "completion_tokens": 32, "total_tokens": 96},
            },
            request=request,
        )


class MockEmbeddingProvider:
    """可计数的离线 embedding（包装 ``FakeEmbeddingProvider``，不联网、不读凭据）。"""

    provider = MOCK_PROVIDER

    def __init__(self, *, model: str = MOCK_EMBEDDING_MODEL, dimensions: int = 1024) -> None:
        self.inner = FakeEmbeddingProvider(model=model, dimensions=dimensions)
        self.calls = 0
        self.texts = 0

    def __repr__(self) -> str:  # 与真实 provider 一致：不含任何凭据
        return f"MockEmbeddingProvider(model={MOCK_EMBEDDING_MODEL!r})"

    def embed(self, texts: Sequence[str], *, purpose: str = "document") -> EmbeddingResponse:
        self.calls += 1
        self.texts += len(texts)
        return self.inner.embed(texts, purpose=purpose)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": MOCK_PROVIDER,
            "model": MOCK_EMBEDDING_MODEL,
            "calls": int(self.calls),
            "texts": int(self.texts),
            "transport": "offline-fake（无传输层，不能出网）",
        }


class MockReranker:
    """可计数的离线 rerank（包装 ``LexicalReranker``，不联网、不读凭据）。"""

    provider = MOCK_PROVIDER

    def __init__(self, *, model: str = MOCK_RERANK_MODEL) -> None:
        self.inner = LexicalReranker()
        self.model = model
        self.calls = 0
        self.documents = 0

    def __repr__(self) -> str:
        return f"MockReranker(model={MOCK_RERANK_MODEL!r})"

    def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int | None = None
    ) -> RerankResponse:
        self.calls += 1
        self.documents += len(documents)
        return self.inner.rerank(query, documents, top_n=top_n)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": MOCK_PROVIDER,
            "model": MOCK_RERANK_MODEL,
            "calls": int(self.calls),
            "documents": int(self.documents),
            "transport": "offline-fake（无传输层，不能出网）",
        }


class _NoOcrGateway:
    """T203 不处理 OCR（属 T204）：任何页都 fail closed，绝不构造腾讯云客户端。"""

    code = "OCR_NOT_CONFIGURED"

    def recognize(self, page: Any, *, mode: str) -> Any:  # noqa: ANN401 - 协议实现
        raise OCRNotConfigured("P2-T203 适配器不提供 OCR（T204 负责）")


# --------------------------------------------------------------------------- #
# 隔离路径与产品回合观测
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProductPaths:
    root: Path
    data_dir: Path
    business_db: Path
    index_db: Path
    storage: Path
    trace_db: Path
    run_dir: Path

    @classmethod
    def of(cls, out_dir: Path | str) -> "ProductPaths":
        root = Path(out_dir)
        data_dir = root / "data"
        return cls(
            root=root,
            data_dir=data_dir,
            business_db=data_dir / "mktkb.sqlite3",
            index_db=data_dir / "rag-index.sqlite3",
            storage=data_dir / "storage",
            trace_db=data_dir / "observability" / "qa-traces.sqlite3",
            run_dir=root / "p2-run",
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "data_dir": str(self.data_dir),
            "business_db": str(self.business_db),
            "index_db": str(self.index_db),
            "storage": str(self.storage),
            "trace_db": str(self.trace_db),
            "run_dir": str(self.run_dir),
        }


@dataclass(frozen=True)
class ProductTurn:
    """一次产品问答的观测结果（产品响应 + trace 归属，不含任何评测评分）。"""

    question_sha256: str
    question_chars: int
    client_request_id: str
    http_status: int
    kind: str
    text: str
    message_id: str | None
    request_id: str | None
    revision: int | None
    error_code: str | None
    retryable: bool
    source_ids: tuple[str, ...]
    sources: tuple[Mapping[str, Any], ...]
    missing_fields: tuple[str, ...]
    candidates: int
    trace_id: str | None
    trace_path: str | None
    trace_outcome: str | None
    trace_status: str | None
    trace_spans: tuple[str, ...]
    replayed: bool
    elapsed_ms: int

    def as_dict(self, *, include_text: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "question_sha256": self.question_sha256,
            "question_chars": int(self.question_chars),
            "client_request_id": self.client_request_id,
            "http_status": int(self.http_status),
            "kind": self.kind,
            "message_id": self.message_id,
            "request_id": self.request_id,
            "revision": self.revision,
            "error_code": self.error_code,
            "retryable": bool(self.retryable),
            "source_ids": list(self.source_ids),
            "sources": [dict(source) for source in self.sources],
            "missing_fields": list(self.missing_fields),
            "candidates": int(self.candidates),
            "trace_id": self.trace_id,
            "trace_path": self.trace_path,
            "trace_outcome": self.trace_outcome,
            "trace_status": self.trace_status,
            "trace_spans": list(self.trace_spans),
            "replayed": bool(self.replayed),
            "elapsed_ms": int(self.elapsed_ms),
        }
        if include_text:
            payload["text"] = self.text
        return payload


class _UserSession:
    """一个隔离产品账号：自己的 cookie jar / CSRF / Origin 头。"""

    def __init__(self, username: str, password: str, client: httpx.AsyncClient) -> None:
        self.username = username
        self._password = password
        self.client = client
        self.csrf_token: str | None = None

    async def login(self) -> None:
        response = await self.client.post(
            "/api/v1/auth/login",
            json={"username": self.username, "password": self._password},
            headers={"Origin": ORIGIN},
        )
        if response.status_code != 200:
            raise RuntimeError(f"隔离账号登录失败: {response.status_code}")
        self.csrf_token = str(response.json()["csrf_token"])

    @property
    def write_headers(self) -> dict[str, str]:
        return {"Origin": ORIGIN, "X-CSRF-Token": str(self.csrf_token or "")}


# --------------------------------------------------------------------------- #
# 适配器
# --------------------------------------------------------------------------- #


class ProductEvalAdapter:
    """在 ``out_dir`` 内建立隔离产品应用，并把评测动作全部走产品 HTTP 入口。"""

    def __init__(
        self,
        out_dir: Path | str,
        *,
        ingest_plan: P2IngestPlan | None = None,
        dataset: P2RunDataset | None = None,
        chat: MockChatBackend | None = None,
        users: Sequence[tuple[str, str]] = (
            ("admin", "P2EvalAdmin-1"),
            ("employee", "P2EvalEmployee-1"),
        ),
        turn_timeout_seconds: float = PRODUCT_TURN_TIMEOUT_SECONDS,
        trace_enabled: bool = True,
        trace_content_mode: str = "hash",
        purge_traces_on_close: bool = False,
        label: str = "",
    ) -> None:
        self.paths = ProductPaths.of(out_dir)
        self.ingest_plan = ingest_plan
        self.dataset = dataset
        self.chat = chat
        self.turn_timeout_seconds = float(turn_timeout_seconds)
        if self.turn_timeout_seconds <= 0:
            raise ValueError("turn_timeout_seconds 必须为正数")
        self.trace_enabled = bool(trace_enabled)
        self.trace_content_mode = str(trace_content_mode)
        self.purge_traces_on_close = bool(purge_traces_on_close)
        self.label = str(label)
        self._users_spec = tuple(users)
        if not self._users_spec:
            raise ValueError("adapter 至少需要一个隔离账号")
        self._sessions: dict[str, _UserSession] = {}
        self._embedder = MockEmbeddingProvider()
        self._reranker = MockReranker()
        self._app: Any = None
        self._settings: Settings | None = None
        self._qa: QaEngine | None = None
        self._started = False
        self._closed = False
        self.ingest_receipts: list[IngestReceipt] = []
        self.real_provider_built = False
        # F1：网络边界必须实测；F6：holdout run 的题干明文在 close 时封存删除。
        self._meter = NetworkMeter()
        # 构造时先取一次基线：即使 run 在发送前被拒（adapter 从未 start），
        # provider_calls() 也不会把进程里别的 run 的 RAG 供应商 POST 算进来。
        self._rag_posts_baseline = _rag_provider_posts()
        self._seal_questions = bool(dataset is not None and dataset.visibility == "holdout")
        self.seal_receipt: dict[str, Any] | None = None

    # ---------------------------------------------------------------- 生命周期
    @property
    def app(self) -> Any:
        if self._app is None:
            raise RuntimeError("adapter 尚未 start()：请先 await adapter.start() 或调用 ingest()")
        return self._app

    @property
    def is_mock(self) -> bool:
        """本适配器只提供 Mock（接入真实 provider 属 T206）。"""
        return True

    async def start(self) -> "ProductEvalAdapter":
        if self._started:
            return self
        if self._closed:
            raise RuntimeError("adapter 已关闭，不能再次启动")
        # 出站基线：RAG 供应商 POST 计数是进程级机器计数，取增量才是本 run 的事实。
        self._rag_posts_baseline = _rag_provider_posts()
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{self.paths.business_db.as_posix()}"
        self._settings = Settings(
            _env_file=None,
            data_dir=self.paths.data_dir,
            database_url=database_url,
            cookie_secure=False,
            csrf_secret="p2-eval-csrf-secret-0123456789",
            bcrypt_rounds=4,
            session_ttl_seconds=3600,
            trusted_origins=[ORIGIN],
            log_level="WARNING",
            storage_dir=self.paths.storage,
            rag_index_path=self.paths.index_db,
            rag_provider_mode="offline",
            rag_sync_on_startup=False,
            ocr_disabled=True,
            trace_enabled=self.trace_enabled,
            trace_db_path=self.paths.trace_db,
            trace_content_mode=self.trace_content_mode,
            admin_password=self._users_spec[0][1],
            employee_password=self._users_spec[-1][1],
        )
        # embedding / rerank 一律注入离线计数替身；chat 只在显式给出 MockTransport 后端时构造
        # 真实 DeepSeekClient（走 provider 编解码但不出网）。默认不构造任何真实 provider。
        gateway = None
        if self.chat is not None:
            # 计量传输包住注入的 MockTransport：被拦截的调用与真实出站尝试分开计数。
            gateway = DeepSeekClient(
                base_url=MOCK_CHAT_BASE_URL,
                model=MOCK_CHAT_MODEL,
                api_key=MOCK_CHAT_API_KEY,
                transport=_MeteredTransport(self.chat.transport, self._meter),
            )
            self.real_provider_built = False
        rag_config = RagConfig(
            provider_mode="offline",
            data_dir=self.paths.data_dir,
            business_date=None,
            top_k=8,
            page_size=10,
            vector_candidate_limit=50,
            rerank_top_n=20,
        )
        self._qa = QaEngine(
            None,  # 真实 Database 在 create_app 之后绑定（见下）
            self.paths.index_db,
            config=rag_config,
            embedder=self._embedder,
            reranker=self._reranker,
        )
        self._app = create_app(
            self._settings,
            model_gateway=gateway,
            ocr_gateway=_NoOcrGateway(),
            qa_engine=self._qa,
        )
        self._qa.db_factory = self._app.state.db
        self._qa.ensure_ready()
        transport = httpx.ASGITransport(app=self._app, raise_app_exceptions=False)
        for username, password in self._users_spec:
            client = httpx.AsyncClient(transport=transport, base_url=ORIGIN, timeout=120.0)
            session = _UserSession(username, password, client)
            try:
                await session.login()
            except RuntimeError:
                # 第二个及以后的账号需要先由管理员创建（隔离库只预置 admin/employee）。
                self._create_account(username, password)
                await session.login()
            self._sessions[username] = session
        self._started = True
        return self

    def _create_account(self, username: str, password: str) -> None:
        from ..auth.service import create_account

        db = self._app.state.db.session()
        try:
            create_account(
                db,
                username=username,
                password=password,
                display_name=username,
                role="employee",
                rounds=4,
            )
        finally:
            db.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for session in self._sessions.values():
            await session.client.aclose()
        self._sessions.clear()
        gateway = getattr(self._app.state, "model_gateway", None) if self._app is not None else None
        closer = getattr(gateway, "aclose", None)
        if closer is not None:
            await closer()
        if self._qa is not None:
            self._qa.close()
        repo = getattr(self._app.state, "trace_repo", None) if self._app is not None else None
        if repo is not None:
            repo.close()
        if self._app is not None:
            self._app.state.db.dispose()
        if self.purge_traces_on_close:
            self.purge_traces()
        if self._seal_questions:
            # F6/H2：通知关闭后再封存，避免"trace 删了、业务库还留着题干明文"。
            self.seal_receipt = self.seal_question_store()

    def require_holdout_sealing(self) -> None:
        """runner 对 holdout run 的显式标记：close() 时必须删掉含题干明文的隔离业务库。"""
        self._seal_questions = True

    @staticmethod
    def _sqlite_family(path: Path) -> list[Path]:
        """SQLite 主文件 + 同目录的同名 -wal/-shm/-journal 副本。"""
        return [path] + [
            path.with_name(path.name + suffix) for suffix in ("-wal", "-shm", "-journal")
        ]

    def seal_question_store(self) -> dict[str, Any]:
        """H2 收尾：删除隔离业务库（会话/消息/请求表里存着题干明文）。

        只在 holdout run 的 close() 里调用（此时连接已关闭、引擎已 dispose）；公开/dry-run
        路径不触发封存，聚合产物与索引/存储副本保持原样。删不干净就报错，不允许"以为删了"。
        """
        removed: list[str] = []
        for path in self._sqlite_family(self.paths.business_db):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            removed.append(str(path))
        remaining = [
            str(path) for path in self._sqlite_family(self.paths.business_db) if path.exists()
        ]
        if remaining:
            raise RuntimeError(f"holdout 封存失败：题干明文仍留在 {remaining}")
        return {"question_store": "deleted", "removed": removed}

    def purge_traces(self) -> list[str]:
        """删除本轮的临时 trace 库（H2 只留聚合，不把逐题 trace 留在磁盘上）。"""
        removed: list[str] = []
        for path in (
            self.paths.trace_db,
            self.paths.trace_db.with_name(self.paths.trace_db.name + "-wal"),
            self.paths.trace_db.with_name(self.paths.trace_db.name + "-shm"),
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                continue
            removed.append(str(path))
        return removed

    # ---------------------------------------------------------------- 观测面
    def network_stats(self) -> dict[str, Any]:
        """本轮**实测**网络边界：出站尝试 = 注入传输的真实出站 + RAG 供应商 POST 增量。

        ``outbound_network`` 不再是常量：Mock 链上由传输层计到 0（调用被 MockTransport 接住，
        计入 ``mock_intercepted``）；换成真实传输时同一个计数器就会>0，产物如实反映。
        """
        rag_posts = max(0, _rag_provider_posts() - int(self._rag_posts_baseline))
        return {
            "outbound_attempts": int(self._meter.outbound_attempts + rag_posts),
            "chat_outbound_attempts": int(self._meter.outbound_attempts),
            "rag_provider_posts": int(rag_posts),
            "mock_intercepted": int(self._meter.mock_intercepted),
            "embedding_provider": "offline-fake（无传输层，不能出网）",
            "rerank_provider": "offline-fake（无传输层，不能出网）",
            "ocr_provider": "disabled（T204 前不构造）",
        }

    def provider_calls(self) -> dict[str, Any]:
        """本轮所有 provider 的调用计数与**实测**网络边界（供产物与测试断言）。

        ``outbound_network`` 有两个层次，语义不同、不可互相替代：

        - **顶层** ``outbound_network``：本轮实测总出站（chat 传输出站 + RAG 供应商 POST），
          是唯一真值；
        - **``network``**：该真值的**分解**（``chat_outbound_attempts`` +
          ``rag_provider_posts``），runner 会核对二者之和是否等于顶层，不一致即报错；
        - 每个 provider 字典里的 ``outbound_network`` 是该 provider 各自的实测出站
          （A3：恢复此字段以便 T203 旧 probe 复跑）：chat 取计量传输的真实出站，
          embedding/rerank 是离线替身、没有传输层，故结构性为 0，而不是"运行时测出来的 0"。
        """
        network = self.network_stats()
        chat = (
            self.chat.as_dict()
            if self.chat is not None
            else {"calls": 0, "provider": None, "transport": None}
        )
        return {
            "chat": {**chat, "outbound_network": int(network["chat_outbound_attempts"])},
            "embedding": {**self._embedder.as_dict(), "outbound_network": 0},
            "rerank": {**self._reranker.as_dict(), "outbound_network": 0},
            "ocr": {
                "calls": 0,
                "state": "T203 不执行 OCR（T204）",
                "outbound_network": 0,
            },
            "outbound_network": int(network["outbound_attempts"]),
            "network": network,
        }

    def trace_of(self, trace_id: str | None) -> tuple[Any, list[Any]] | None:
        repo = getattr(self._app.state, "trace_repo", None) if self._app is not None else None
        if repo is None or not trace_id:
            return None
        try:
            return repo.get(trace_id)
        except Exception:  # noqa: BLE001 - trace 是观测面，读失败不改业务结论
            return None

    def product_revision(self) -> int:
        db = self._app.state.db.session()
        try:
            return int(get_revision(db))
        finally:
            db.close()

    def index_status(self) -> dict[str, Any]:
        if self._qa is None:
            return {}
        return self._qa.status()

    def _session(self, user_id: str) -> _UserSession:
        session = self._sessions.get(str(user_id))
        if session is None:
            raise KeyError(f"未知隔离账号 {user_id!r}（可用：{sorted(self._sessions)}）")
        return session

    # ---------------------------------------------------------------- 灌库（产品路径）
    async def ingest(
        self, plan: P2IngestPlan | Mapping[str, Any] | None = None
    ) -> list[IngestReceipt]:
        """走产品上传 -> worker 解析 -> 发布路径把语料放进隔离库（不复制解析/发布逻辑）。"""
        await self.start()
        chosen: P2IngestPlan | None
        if plan is None:
            chosen = self.ingest_plan
        elif isinstance(plan, P2IngestPlan):
            chosen = plan
        else:
            chosen = P2IngestPlan(
                sources=tuple(
                    IngestSource(
                        path=Path(item["path"]),
                        name=item.get("name"),
                        document_id=item.get("document_id"),
                        expected_active_version_id=item.get("expected_active_version_id"),
                        allow_same_name=bool(item.get("allow_same_name", False)),
                        publish=bool(item.get("publish", True)),
                    )
                    for item in plan.get("sources") or ()
                ),
                label=str(plan.get("label") or ""),
            )
        if chosen is None:
            raise RuntimeError("adapter 没有 ingest plan：请显式传入")
        receipts: list[IngestReceipt] = []
        admin = self._session(self._users_spec[0][0])
        for source in chosen.sources:
            receipts.append(await self._ingest_one(admin, source))
        self.ingest_receipts.extend(receipts)
        return receipts

    async def _ingest_one(self, admin: _UserSession, source: IngestSource) -> IngestReceipt:
        content = source.path.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        url = "/api/v1/documents"
        data: dict[str, str] = {}
        if source.document_id is not None:
            url = f"/api/v1/documents/{source.document_id}/versions"
            if source.expected_active_version_id is not None:
                data["expected_active_version_id"] = str(source.expected_active_version_id)
        elif source.allow_same_name:
            data["allow_same_name"] = "true"
        response = await admin.client.post(
            url,
            files={"file": (str(source.name), content, "application/octet-stream")},
            data=data,
            headers=admin.write_headers,
        )
        if response.status_code != 202:
            raise RuntimeError(f"上传未获受理: {response.status_code} {response.text[:200]}")
        record = response.json()
        document_id = str(record["document"]["id"])
        version_id = str(record["version"]["id"])
        db = self._app.state.db.session()
        try:
            job = run_one_job(db, self._app.state.store)
            revision = int(get_revision(db))
        finally:
            db.close()
        if job.state != "succeeded":
            raise RuntimeError(f"worker 未成功处理 {source.name}: {job.state}")
        publish_status: int | None = None
        published = False
        if source.publish:
            published_response = await admin.client.post(
                f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
                json={
                    "expected_active_version_id": source.expected_active_version_id,
                    "expected_revision": revision,
                },
                headers=admin.write_headers,
            )
            publish_status = published_response.status_code
            if publish_status != 200:
                raise RuntimeError(
                    f"发布未获受理: {publish_status} {published_response.text[:200]}"
                )
            published = True
            revision = int(published_response.json()["revision"])
        units = self._unit_count(version_id)
        return IngestReceipt(
            name=str(source.name),
            sha256=sha256,
            document_id=document_id,
            version_id=version_id,
            job_state=str(job.state),
            published=published,
            revision=revision,
            upload_status=int(response.status_code),
            publish_status=publish_status,
            units=units,
        )

    def _unit_count(self, version_id: str) -> int | None:
        """该版本的产品来源单元数（只读计数，失败不影响灌库回执本身）。"""
        from sqlalchemy import func, select

        from ..documents.models import SourceUnit

        db = self._app.state.db.session()
        try:
            return int(
                db.scalar(
                    select(func.count())
                    .select_from(SourceUnit)
                    .where(SourceUnit.version_id == uuid.UUID(str(version_id)))
                )
                or 0
            )
        except Exception:  # noqa: BLE001 - 计数失败不影响灌库回执本身
            return None
        finally:
            db.close()

    # ---------------------------------------------------------------- 问答（产品路径）
    async def open_conversation(self, *, user_id: str = "employee", title: str | None = None) -> str:
        await self.start()
        session = self._session(user_id)
        payload: dict[str, Any] = {} if title is None else {"title": title}
        response = await session.client.post(
            "/api/v1/conversations", json=payload, headers=session.write_headers
        )
        if response.status_code != 201:
            raise RuntimeError(f"建会话失败: {response.status_code} {response.text[:200]}")
        return str(response.json()["id"])

    async def ask_turn(
        self,
        question: str,
        *,
        user_id: str,
        conversation_id: str,
        client_request_id: str,
    ) -> ProductTurn:
        """走用户同一产品入口提问一次；超时/异常都转成可记录的产品回合结果。"""
        await self.start()
        session = self._session(user_id)
        started = time.perf_counter()
        timed_out = False
        response: httpx.Response | None = None
        try:
            response = await asyncio.wait_for(
                session.client.post(
                    f"/api/v1/conversations/{conversation_id}/messages",
                    json={
                        "client_request_id": str(client_request_id),
                        "question": str(question),
                    },
                    headers=session.write_headers,
                ),
                timeout=self.turn_timeout_seconds,
            )
        except asyncio.TimeoutError:
            timed_out = True
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if timed_out or response is None:
            record: tuple[Any, list[Any]] | None = None
            return ProductTurn(
                question_sha256=_sha256_text(question),
                question_chars=len(question),
                client_request_id=str(client_request_id),
                http_status=504,
                kind="timeout",
                text="",
                message_id=None,
                request_id=None,
                revision=None,
                error_code="TURN_TIMEOUT",
                retryable=False,
                source_ids=(),
                sources=(),
                missing_fields=(),
                candidates=0,
                trace_id=None,
                trace_path=None if record is None else getattr(record[0], "path", None),
                trace_outcome=None,
                trace_status=None,
                trace_spans=(),
                replayed=False,
                elapsed_ms=elapsed_ms,
            )
        trace_id = response.headers.get("X-Trace-ID")
        trace_path = trace_outcome = trace_status = None
        trace_spans: tuple[str, ...] = ()
        record = self.trace_of(trace_id)
        if record is not None:
            trace, spans = record
            trace_path = getattr(trace, "path", None)
            trace_outcome = getattr(trace, "outcome_kind", None)
            trace_status = getattr(trace, "status", None)
            trace_spans = tuple(str(span.name) for span in spans)
        payload = self._json_body(response)
        kind = str(payload.get("kind") or ("service_error" if response.status_code != 200 else ""))
        sources = tuple(
            dict(item) for item in (payload.get("sources") or ()) if isinstance(item, Mapping)
        )
        source_ids: list[str] = []
        for item in sources:
            value = str(item.get("source_id") or "").strip()
            if value and value not in source_ids:
                source_ids.append(value)
        return ProductTurn(
            question_sha256=_sha256_text(question),
            question_chars=len(question),
            client_request_id=str(client_request_id),
            http_status=int(response.status_code),
            kind=kind or "unknown",
            text=str(payload.get("text") or ""),
            message_id=_opt_str(payload.get("message_id")),
            request_id=_opt_str(payload.get("request_id")),
            revision=_opt_int(payload.get("revision")),
            error_code=_opt_str(payload.get("error_code")),
            retryable=bool(payload.get("retryable", False)),
            source_ids=tuple(source_ids),
            sources=sources,
            missing_fields=tuple(str(item) for item in (payload.get("missing_fields") or ())),
            candidates=len(payload.get("candidates") or ()),
            trace_id=trace_id,
            trace_path=trace_path,
            trace_outcome=trace_outcome,
            trace_status=trace_status,
            trace_spans=trace_spans,
            replayed=bool(payload.get("replayed", False)),
            elapsed_ms=elapsed_ms,
        )

    @staticmethod
    def _json_body(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    # ---------------------------------------------------------------- 来源/会话观测
    async def source_detail(
        self, message_id: str, source_id: str, *, user_id: str = "employee"
    ) -> tuple[int, dict[str, Any]]:
        """走产品 ``GET /messages/{id}/sources/{sid}``（含归属鉴权与有效版本复核）。"""
        await self.start()
        session = self._session(user_id)
        response = await session.client.get(f"/api/v1/messages/{message_id}/sources/{source_id}")
        return int(response.status_code), self._json_body(response)

    async def list_messages(
        self, conversation_id: str, *, user_id: str = "employee"
    ) -> tuple[int, dict[str, Any]]:
        await self.start()
        session = self._session(user_id)
        response = await session.client.get(f"/api/v1/conversations/{conversation_id}/messages")
        return int(response.status_code), self._json_body(response)

    def messages_in_db(self, conversation_id: str) -> int:
        """直接数隔离业务库里该会话的消息行（幂等断言：重复提交不能多出消息）。"""
        from ..conversations.models import ConversationMessage

        db = self._app.state.db.session()
        try:
            return int(
                db.query(ConversationMessage)
                .filter(ConversationMessage.conversation_id == uuid.UUID(str(conversation_id)))
                .count()
            )
        finally:
            db.close()


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
