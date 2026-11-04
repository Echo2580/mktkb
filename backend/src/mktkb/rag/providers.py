"""供应商适配：百炼 embedding/rerank、DeepSeek chat，以及明确标记的离线替身。

真实适配器只使用项目已安装的 httpx 0.28.1；地址来自配置，不允许调用方传 URL。
所有真实调用必须先通过 `BudgetLedger.reserve`。错误不打印响应正文、认证头或 Key。
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from typing import Any, Protocol, Sequence

import httpx
import numpy as np

from ..official_chat_profile import OfficialChatProfileError, assert_official_chat_profile
from ..retrieval.tokenize import bigrams, cut, normalize
from .budget import BudgetLedger, BudgetLedgerInvalid, Reservation
from .config import RagConfig
from .controlled_usage import (
    ControlledFieldError,
    build_chat_evidence,
    build_total_evidence,
    safe_dimensions,
    safe_error_code,
    safe_http_status,
    safe_request_id,
    safe_usage,
)
from .errors import (
    BudgetPricingUnknown,
    ChatUnavailable,
    EmbeddingDimensionError,
    EmbeddingRateLimited,
    EmbeddingResponseError,
    EmbeddingTimeout,
    EmbeddingUnavailable,
    RagConfigError,
    RerankError,
    RerankUnavailable,
)
from .settlement_policy import KIND_CHAT, KIND_EMBEDDING, KIND_RERANK, SettlementPolicy
from .types import ChatResponse, EmbeddingResponse, RerankResponse, RerankResult

MAX_EMBEDDING_INPUT_TOKENS = 8192
MAX_EMBEDDING_REQUEST_TOKENS = 10 * MAX_EMBEDDING_INPUT_TOKENS  # 官方单请求 81,920

# 客户端 post 边界观测（只用于审计，不参与业务逻辑）：
# 在调用 `self._client.post(...)` 之前计数，因此“进入 post 但未到 transport”也能被看见。
_POST_STATS_LOCK = threading.Lock()
_POST_STATS: dict[str, dict[str, int]] = {"attempts": {}, "outcomes": {}}


def reset_post_counters() -> None:
    with _POST_STATS_LOCK:
        _POST_STATS["attempts"] = {}
        _POST_STATS["outcomes"] = {}


def post_counters() -> dict[str, dict[str, int]]:
    with _POST_STATS_LOCK:
        return {
            "attempts": dict(_POST_STATS["attempts"]),
            "outcomes": {key: dict(value) for key, value in _POST_STATS["outcomes"].items()},
        }


def _record_post_attempt(kind: str) -> None:
    with _POST_STATS_LOCK:
        attempts = _POST_STATS["attempts"]
        attempts[kind] = attempts.get(kind, 0) + 1


def _record_post_outcome(kind: str, status: str) -> None:
    with _POST_STATS_LOCK:
        bucket = _POST_STATS["outcomes"].setdefault(kind, {})
        bucket[status] = bucket.get(status, 0) + 1


def _post_send_recheck(budget: BudgetLedger | None, reservation: Reservation) -> None:
    """预留成功后、真实 POST 前的第二次授权/预算复核。

    账本由产品 LiveGate 构造时带 ``post_reserve_guard``；未注入的旧账本为空操作。
    只读不写：不新增预留、不清账、不退款；拒绝时调用方必须在 POST 之前停住。
    """
    if budget is None:
        return
    budget.recheck_reservation(reservation)


def _validate_settlement_policy(policy: object, *, kind: str, provider: str, model: str) -> SettlementPolicy | None:
    """J2：版本化结算 policy 必须与 provider/kind/model 严格一致，否则构造期拒绝。"""
    if policy is None:
        return None
    if not isinstance(policy, SettlementPolicy):
        raise RagConfigError("settlement_policy 必须是 SettlementPolicy")
    if policy.kind != kind or policy.provider != provider or policy.model != model:
        raise RagConfigError("settlement_policy 与 provider/kind/model 不一致，拒绝构造")
    return policy


def _controlled_request_id(value: object):
    return safe_request_id(value)


def _controlled_dimensions(value: object) -> tuple[int, ...] | None:
    try:
        return safe_dimensions(value)
    except ControlledFieldError:
        return None


def _enforce_zero_retry(config: RagConfig) -> None:
    """S2-H：live/smoke 配置要求零重试时，provider 构造阶段再次硬拒非零值。"""
    if config.live and config.require_zero_retries and config.max_retries != 0:
        raise RagConfigError("live/smoke 禁止非零自动重试（max_retries 必须为 0）")


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int
    provider: str

    def embed(self, texts: Sequence[str], *, purpose: str = "document") -> EmbeddingResponse: ...


class RerankProvider(Protocol):
    model: str
    provider: str

    def rerank(self, query: str, documents: Sequence[str], *, top_n: int | None = None) -> RerankResponse: ...


def _upper_tokens(text: str) -> int:
    """正则/兼容口径的字符数；用于既有 embedding/chat 预算和测试。"""
    return max(1, len(str(text)))


def _byte_upper_tokens(text: str) -> int:
    """UTF-8 字节数上界：任一 token 至少消耗一个字节，另有固定特殊 token 余量。"""
    return max(1, len(str(text).encode("utf-8"))) + 8


def _estimated_cny(tokens: int, price_per_million: float) -> float:
    return max(0.0, float(tokens)) * float(price_per_million) / 1_000_000.0


def _validate_vector(vector: Any, dimensions: int) -> tuple[float, ...]:
    if not isinstance(vector, (list, tuple)):
        raise EmbeddingDimensionError("embedding 不是数组")
    if len(vector) != dimensions:
        raise EmbeddingDimensionError(f"embedding 维度不是 {dimensions}")
    values: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EmbeddingDimensionError("embedding 含非数值")
        number = float(value)
        if not math.isfinite(number):
            raise EmbeddingDimensionError("embedding 含 NaN/Inf")
        values.append(number)
    return tuple(values)


class FakeEmbeddingProvider:
    """离线确定性替身：哈希词袋向量，明确 provider=mock，不标真实通过。"""

    provider = "mock"

    _SYNONYMS = {
        "在哪": "位置",
        "哪里": "位置",
        "哪儿": "位置",
        "存放": "位置",
        "位于": "位置",
        "放到": "位置",
        "放在": "位置",
        "搁哪": "位置",
        "搁哪儿": "位置",
        "多少钱": "价格",
        "售价": "价格",
        "单价": "价格",
        "套餐价": "组合价",
        "全部": "全部",
        "所有": "全部",
    }

    def __init__(self, *, model: str = "text-embedding-v4", dimensions: int = 1024) -> None:
        if dimensions <= 0:
            raise RagConfigError("dimensions 必须为正整数")
        self.model = model
        self.dimensions = dimensions

    def _features(self, text: str) -> list[str]:
        normalized = normalize(text)
        tokens: list[str] = []
        for token in cut(text):
            tokens.append(self._SYNONYMS.get(token, token))
        tokens.extend(bigrams(text))
        # 全角/半角与大小写归一后的连续片段也作为特征，避免只靠分词。
        for piece in normalized.replace("\n", " ").split(" "):
            if len(piece) >= 2:
                tokens.append(piece)
        return [token for token in tokens if token]

    def _vector(self, text: str) -> tuple[float, ...]:
        vector = np.zeros(self.dimensions, dtype=np.float64)
        for token in self._features(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self.dimensions
            vector[index] += 1.0
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector = vector / norm
        return tuple(float(x) for x in vector)

    def embed(self, texts: Sequence[str], *, purpose: str = "document") -> EmbeddingResponse:
        vectors = tuple(self._vector(str(text)) for text in texts)
        tokens = sum(_byte_upper_tokens(text) for text in texts)
        return EmbeddingResponse(
            vectors=vectors,
            model=self.model,
            dimensions=self.dimensions,
            provider=self.provider,
            usage={"total_tokens": tokens},
            request_id=None,
            estimated_list_price_cny=0.0,
        )


class BailianEmbeddingProvider:
    """百炼 OpenAI 兼容 embeddings；1024 维强制校验。"""

    provider = "bailian"

    def __init__(
        self,
        config: RagConfig,
        *,
        budget: BudgetLedger | None = None,
        transport: httpx.BaseTransport | None = None,
        require_budget: bool = True,
        settlement_policy: SettlementPolicy | None = None,
    ) -> None:
        if not config.embedding_api_key.strip():
            raise RagConfigError("缺少 DASHSCOPE_API_KEY")
        if not config.embedding_base_url.strip():
            raise RagConfigError("缺少 embedding base URL")
        _enforce_zero_retry(config)
        self.config = config
        self.model = config.embedding_model
        self.dimensions = config.embedding_dimensions
        self.budget = budget
        self.require_budget = require_budget
        self.settlement_policy = _validate_settlement_policy(
            settlement_policy,
            kind=KIND_EMBEDDING,
            provider=self.provider,
            model=self.model,
        )
        if self.settlement_policy is not None and budget is None:
            raise RagConfigError("受控版本化结算需要共享账本，禁止无账本运行")
        if self.settlement_policy is not None and config.max_retries != 0:
            raise RagConfigError("受控版本化结算要求零自动重试（max_retries 必须为 0）")
        self._transport = transport
        self._client = httpx.Client(
            timeout=config.embedding_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def __repr__(self) -> str:  # 不包含 Key
        return f"BailianEmbeddingProvider(model={self.model!r}, dimensions={self.dimensions})"

    def close(self) -> None:
        self._client.close()

    def embed(self, texts: Sequence[str], *, purpose: str = "document") -> EmbeddingResponse:
        cleaned = [str(text) for text in texts]
        if not cleaned:
            raise EmbeddingResponseError("embedding 输入为空")
        for text in cleaned:
            # 只做保守的输入尺寸门禁，不把它当计费 token 上界；计费固定按官方
            # 单请求 10×8192 token 最大值预留。
            if len(str(text).encode("utf-8")) > MAX_EMBEDDING_INPUT_TOKENS:
                raise EmbeddingResponseError("单条 embedding 输入超过保守 8192 字节门禁")
        vectors: list[tuple[float, ...]] = []
        total_tokens = 0
        request_ids: list[str] = []
        estimated_total = 0.0
        batch_size = self.config.embedding_batch_size
        for offset in range(0, len(cleaned), batch_size):
            batch = cleaned[offset : offset + batch_size]
            response = self._embed_batch(batch, purpose=purpose)
            if len(response.vectors) != len(batch):
                raise EmbeddingResponseError("embedding 返回条数与输入不一致")
            vectors.extend(response.vectors)
            total_tokens += int(response.usage.get("total_tokens") or 0)
            estimated_total += response.estimated_list_price_cny
            if response.request_id:
                request_ids.append(response.request_id)
        return EmbeddingResponse(
            vectors=tuple(vectors),
            model=self.model,
            dimensions=self.dimensions,
            provider=self.provider,
            usage={"total_tokens": total_tokens},
            request_id=",".join(request_ids) or None,
            estimated_list_price_cny=estimated_total,
        )

    def _embed_batch(self, batch: list[str], *, purpose: str) -> EmbeddingResponse:
        # 官方单请求最多 10 条、每条最多 8,192 token；供应商未公布 tokenizer，
        # 不能用 UTF-8 字节证明实际 token，因此每次请求按官方最大值预留。
        reserve_cny = _estimated_cny(
            MAX_EMBEDDING_REQUEST_TOKENS,
            self.config.embedding_price_per_million_cny,
        )
        if reserve_cny > self.config.max_request_cny:
            raise EmbeddingUnavailable("单次 embedding 预留超过单请求上限")
        payload = {
            "model": self.model,
            "input": batch,
            "dimensions": self.dimensions,
            "encoding_format": "float",
        }
        url = f"{self.config.embedding_base_url.rstrip('/')}{self.config.embedding_path}"
        request_sha = _sha256_json(payload)
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            reservation = self._reserve(
                kind="embedding",
                max_cny=reserve_cny,
                request_sha256=request_sha,
            )
            started = time.monotonic()
            try:
                _post_send_recheck(self.budget, reservation)
            except BudgetLedgerInvalid as exc:
                self._settle(
                    reservation,
                    status="failed",
                    error_code="EMBEDDING_POST_AUTH_DENIED",
                    started=started,
                )
                raise EmbeddingUnavailable(f"发送前授权/预算复核拒绝，未发送：{exc}") from None
            _record_post_attempt("embedding")
            try:
                response = self._client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.config.embedding_api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
            except httpx.TimeoutException:
                _record_post_outcome("embedding", "timeout")
                self._settle(reservation, status="timeout", error_code="EMBEDDING_TIMEOUT", started=started)
                last_error = EmbeddingTimeout("embedding 请求超时")
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_base_seconds * (2**attempt))
                    continue
                raise last_error from None
            except httpx.HTTPError as exc:
                _record_post_outcome("embedding", "transport_error")
                self._settle(
                    reservation,
                    status="failed",
                    error_code="EMBEDDING_NETWORK",
                    started=started,
                )
                last_error = EmbeddingUnavailable(f"embedding 网络错误：{type(exc).__name__}")
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_base_seconds * (2**attempt))
                    continue
                raise last_error from None
            else:
                _record_post_outcome("embedding", "response")

            if response.status_code == 429:
                self._settle(
                    reservation,
                    status="failed",
                    http_status=429,
                    error_code="EMBEDDING_RATE_LIMITED",
                    started=started,
                )
                last_error = EmbeddingRateLimited("embedding 被限流")
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_base_seconds * (2**attempt))
                    continue
                raise last_error

            if response.status_code >= 500:
                self._settle(
                    reservation,
                    status="failed",
                    http_status=response.status_code,
                    error_code="EMBEDDING_UNAVAILABLE",
                    started=started,
                )
                last_error = EmbeddingUnavailable(f"embedding 供应商状态 {response.status_code}")
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_base_seconds * (2**attempt))
                    continue
                raise last_error

            if response.status_code != 200:
                self._settle(
                    reservation,
                    status="failed",
                    http_status=response.status_code,
                    error_code="EMBEDDING_HTTP",
                    started=started,
                )
                raise EmbeddingUnavailable(f"embedding 请求失败状态 {response.status_code}")

            try:
                data = response.json()
                parsed = self._parse(data, expected=len(batch))
            except Exception as exc:
                self._settle(
                    reservation,
                    status="failed",
                    http_status=200,
                    error_code=getattr(exc, "code", "EMBEDDING_RESPONSE_INVALID"),
                    started=started,
                )
                if isinstance(exc, EmbeddingResponseError):
                    raise
                if isinstance(exc, EmbeddingDimensionError):
                    raise
                raise EmbeddingResponseError("embedding 响应结构不合法") from None

            usage = parsed["usage"]
            received_tokens = int(usage.get("total_tokens") or 0)
            if received_tokens > MAX_EMBEDDING_REQUEST_TOKENS:
                self._settle(
                    reservation,
                    status="unknown",
                    http_status=200,
                    usage=usage,
                    error_code="EMBEDDING_USAGE_OVER_OFFICIAL_MAX",
                    started=started,
                )
                raise EmbeddingResponseError("embedding usage 超过官方单请求最大值，停止且标未证明")
            estimated = _estimated_cny(
                received_tokens or MAX_EMBEDDING_REQUEST_TOKENS,
                self.config.embedding_price_per_million_cny,
            )
            request_id = _controlled_request_id(parsed.get("request_id"))
            dimensions = _controlled_dimensions((self.dimensions,))
            if self.settlement_policy is not None:
                # J2 受控版本化结算：只由实际响应（HTTP 200 + 合法输出 + 官方 usage）
                # 构造 evidence，经 J1 严格重算；不合格时 settle_usage 抛停止信号且全额保留。
                evidence = build_total_evidence(
                    self.settlement_policy,
                    request_sha256=request_sha,
                    usage=parsed.get("raw_usage") if isinstance(parsed.get("raw_usage"), dict) else usage,
                    http_status=response.status_code,
                    output_valid=True,
                )
                decision = self.budget.settle_usage(  # type: ignore[union-attr]
                    reservation,
                    evidence=evidence,
                    request_id=request_id,
                    elapsed_seconds=time.monotonic() - started,
                    dimensions=dimensions,
                )
                estimated = float(decision.charge_cny)
            else:
                self._settle(
                    reservation,
                    status="succeeded",
                    http_status=response.status_code,
                    usage=usage,
                    estimated=estimated,
                    request_id=request_id,
                    started=started,
                    dimensions=dimensions,
                )
            return EmbeddingResponse(
                vectors=tuple(parsed["vectors"]),
                model=self.model,
                dimensions=self.dimensions,
                provider=self.provider,
                usage=usage,
                request_id=request_id,
                estimated_list_price_cny=estimated,
            )
        raise last_error or EmbeddingUnavailable("embedding 不可用")

    def _parse(self, data: Any, *, expected: int) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise EmbeddingResponseError("响应不是 JSON 对象")
        rows = data.get("data")
        if not isinstance(rows, list) or len(rows) != expected:
            raise EmbeddingResponseError("embedding 返回条数不合法")
        ordered: list[tuple[int, tuple[float, ...]]] = []
        for fallback_index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise EmbeddingResponseError("embedding 行不是对象")
            index = row.get("index", fallback_index)
            if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= expected:
                raise EmbeddingResponseError("embedding index 非法")
            vector = _validate_vector(row.get("embedding"), self.dimensions)
            ordered.append((index, vector))
        if sorted(index for index, _ in ordered) != list(range(expected)):
            raise EmbeddingResponseError("embedding index 不完整或重复")
        usage_raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        usage: dict[str, int] = {}
        for key in ("prompt_tokens", "total_tokens"):
            value = usage_raw.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                usage[key] = value
        request_id = _controlled_request_id(data.get("id"))
        vectors = [vector for _, vector in sorted(ordered, key=lambda item: item[0])]
        return {
            "vectors": vectors,
            "usage": usage,
            "raw_usage": dict(usage_raw),
            "request_id": request_id,
        }

    def _reserve(self, *, kind: str, max_cny: float, request_sha256: str) -> Reservation:
        if self.budget is None:
            if self.require_budget:
                raise RagConfigError("真实 embedding 调用必须提供共享预算账本")
            # 仅用于受控 HTTP 解析测试；不进入真实路径。
            return Reservation("test-" + request_sha256[:12], "TEST", kind, self.provider, self.model, max_cny, request_sha256, "")
        return self.budget.reserve(
            kind=kind,
            provider=self.provider,
            model=self.model,
            max_cny=max_cny,
            request_sha256=request_sha256,
            settlement_policy=self.settlement_policy,
        )

    def _settle(
        self,
        reservation: Reservation,
        *,
        status: str,
        http_status: int | None = None,
        usage: dict[str, int] | None = None,
        estimated: float = 0.0,
        request_id: str | None = None,
        error_code: str | None = None,
        started: float,
        dimensions: tuple[int, ...] | None = None,
    ) -> None:
        if self.budget is None:
            return
        self.budget.settle(
            reservation,
            status=status,
            usage=usage,
            estimated_list_price_cny=estimated,
            http_status=safe_http_status(http_status),
            request_id=_controlled_request_id(request_id),
            error_code=None if error_code is None else safe_error_code(error_code),
            elapsed_seconds=time.monotonic() - started,
            dimensions=_controlled_dimensions(dimensions),
        )


class BailianRerankProvider:
    """百炼 gte-rerank-v2；返回本次请求内的相对分数，不跨请求比较。"""

    provider = "bailian"

    def __init__(
        self,
        config: RagConfig,
        *,
        budget: BudgetLedger | None = None,
        transport: httpx.BaseTransport | None = None,
        require_budget: bool = True,
        settlement_policy: SettlementPolicy | None = None,
    ) -> None:
        if not config.rerank_api_key.strip():
            raise RagConfigError("缺少百炼 rerank Key")
        _enforce_zero_retry(config)
        self.config = config
        self.model = config.rerank_model
        self.budget = budget
        self.require_budget = require_budget
        self.settlement_policy = _validate_settlement_policy(
            settlement_policy,
            kind=KIND_RERANK,
            provider=self.provider,
            model=self.model,
        )
        if self.settlement_policy is not None and budget is None:
            raise RagConfigError("受控版本化结算需要共享账本，禁止无账本运行")
        if self.settlement_policy is not None and config.max_retries != 0:
            raise RagConfigError("受控版本化结算要求零自动重试（max_retries 必须为 0）")
        self._client = httpx.Client(
            timeout=config.rerank_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def __repr__(self) -> str:
        return f"BailianRerankProvider(model={self.model!r})"

    def close(self) -> None:
        self._client.close()

    def rerank(self, query: str, documents: Sequence[str], *, top_n: int | None = None) -> RerankResponse:
        docs = [str(item) for item in documents]
        if not docs:
            return RerankResponse((), self.model, self.provider)
        if len(docs) > self.config.rerank_max_documents:
            raise RerankError(f"rerank 文档数超过上限 {self.config.rerank_max_documents}")
        limit = len(docs) if top_n is None else max(1, min(int(top_n), len(docs)))
        query_tokens = _byte_upper_tokens(query)
        doc_tokens = [_byte_upper_tokens(item) for item in docs]
        for size in doc_tokens:
            if size > self.config.rerank_max_single_tokens:
                raise RerankError(
                    f"rerank 单条输入超过上限 {self.config.rerank_max_single_tokens} token"
                )
        # 官方计费口径：查询 token 按候选数计；请求总 token 同时受请求上限约束。
        tokens_upper = query_tokens * len(docs) + sum(doc_tokens)
        if tokens_upper > self.config.rerank_max_request_tokens:
            raise RerankError(
                f"rerank 请求 token 上界 {tokens_upper} 超过上限 "
                f"{self.config.rerank_max_request_tokens}"
            )
        # 预留按官方请求上限而不是按估算用量打折，保证任何通过校验的请求都被覆盖。
        reserve_cny = max(
            0.001,
            _estimated_cny(
                self.config.rerank_max_request_tokens,
                self.config.rerank_price_per_million_cny,
            ),
        )
        if reserve_cny > self.config.max_request_cny:
            raise RerankError("单次 rerank 预留超过单请求上限")
        payload = {
            "model": self.model,
            "input": {"query": str(query), "documents": docs},
            "parameters": {"return_documents": False, "top_n": limit},
        }
        url = f"{self.config.rerank_base_url.rstrip('/')}{self.config.rerank_path}"
        request_sha = _sha256_json(payload)
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            reservation = self._reserve(max_cny=reserve_cny, request_sha256=request_sha)
            started = time.monotonic()
            try:
                _post_send_recheck(self.budget, reservation)
            except BudgetLedgerInvalid as exc:
                self._settle(
                    reservation,
                    status="failed",
                    error_code="RERANK_POST_AUTH_DENIED",
                    started=started,
                )
                raise RerankUnavailable(f"发送前授权/预算复核拒绝，未发送：{exc}") from None
            _record_post_attempt("rerank")
            try:
                response = self._client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.config.rerank_api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
            except httpx.TimeoutException:
                _record_post_outcome("rerank", "timeout")
                self._settle(reservation, status="timeout", error_code="RERANK_TIMEOUT", started=started)
                last_error = RerankUnavailable("rerank 请求超时")
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_base_seconds * (2**attempt))
                    continue
                raise last_error from None
            except httpx.HTTPError as exc:
                _record_post_outcome("rerank", "transport_error")
                self._settle(reservation, status="failed", error_code="RERANK_NETWORK", started=started)
                last_error = RerankUnavailable(f"rerank 网络错误：{type(exc).__name__}")
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_base_seconds * (2**attempt))
                    continue
                raise last_error from None
            else:
                _record_post_outcome("rerank", "response")
            if response.status_code == 429:
                self._settle(reservation, status="failed", http_status=429, error_code="RERANK_RATE_LIMITED", started=started)
                last_error = RerankUnavailable("rerank 被限流")
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_base_seconds * (2**attempt))
                    continue
                raise last_error
            if response.status_code >= 500:
                self._settle(reservation, status="failed", http_status=response.status_code, error_code="RERANK_UNAVAILABLE", started=started)
                last_error = RerankUnavailable(f"rerank 供应商状态 {response.status_code}")
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_base_seconds * (2**attempt))
                    continue
                raise last_error
            if response.status_code != 200:
                self._settle(reservation, status="failed", http_status=response.status_code, error_code="RERANK_HTTP", started=started)
                raise RerankUnavailable(f"rerank 请求失败状态 {response.status_code}")
            try:
                data = response.json()
                raw_usage = data.get("usage") if isinstance(data, dict) and isinstance(data.get("usage"), dict) else {}
                results, usage = self._parse(data, limit=len(docs), top_n=limit)
            except Exception as exc:
                self._settle(reservation, status="failed", http_status=200, error_code="RERANK_RESPONSE_INVALID", started=started)
                if isinstance(exc, RerankError):
                    raise
                raise RerankError("rerank 响应结构不合法") from None
            estimated = _estimated_cny(
                int(usage.get("total_tokens") or tokens_upper),
                self.config.rerank_price_per_million_cny,
            )
            request_id = _controlled_request_id(data.get("request_id") if isinstance(data, dict) else None)
            if self.settlement_policy is not None:
                evidence = build_total_evidence(
                    self.settlement_policy,
                    request_sha256=request_sha,
                    usage=raw_usage,
                    http_status=response.status_code,
                    output_valid=True,
                )
                decision = self.budget.settle_usage(  # type: ignore[union-attr]
                    reservation,
                    evidence=evidence,
                    request_id=request_id,
                    elapsed_seconds=time.monotonic() - started,
                )
                estimated = float(decision.charge_cny)
            else:
                self._settle(
                    reservation,
                    status="succeeded",
                    http_status=response.status_code,
                    usage=usage,
                    estimated=estimated,
                    request_id=request_id,
                    started=started,
                )
            return RerankResponse(
                results=tuple(results),
                model=self.model,
                provider=self.provider,
                usage=usage,
                request_id=request_id,
                estimated_list_price_cny=estimated,
            )
        raise last_error or RerankUnavailable("rerank 不可用")

    def _parse(self, data: Any, *, limit: int, top_n: int) -> tuple[list[RerankResult], dict[str, int]]:
        if not isinstance(data, dict):
            raise RerankError("rerank 响应不是对象")
        output = data.get("output")
        rows = output.get("results") if isinstance(output, dict) else None
        if not isinstance(rows, list):
            raise RerankError("rerank 响应缺少 output.results")
        results: list[RerankResult] = []
        seen: set[int] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise RerankError("rerank 行不是对象")
            index = row.get("index")
            score = row.get("relevance_score")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < limit:
                raise RerankError("rerank index 非法")
            if index in seen:
                raise RerankError("rerank index 重复")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise RerankError("rerank score 非法")
            number = float(score)
            if not math.isfinite(number):
                raise RerankError("rerank score 非有限数")
            seen.add(index)
            results.append(RerankResult(index=index, score=max(0.0, min(1.0, number))))
        usage_raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        usage: dict[str, int] = {}
        for key in ("total_tokens", "prompt_tokens"):
            value = usage_raw.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                usage[key] = value
        results.sort(key=lambda item: (-item.score, item.index))
        return results[:top_n], usage

    def _reserve(self, *, max_cny: float, request_sha256: str) -> Reservation:
        if self.budget is None:
            if self.require_budget:
                raise RagConfigError("真实 rerank 调用必须提供共享预算账本")
            return Reservation("test-" + request_sha256[:12], "TEST", "rerank", self.provider, self.model, max_cny, request_sha256, "")
        return self.budget.reserve(
            kind="rerank",
            provider=self.provider,
            model=self.model,
            max_cny=max_cny,
            request_sha256=request_sha256,
            settlement_policy=self.settlement_policy,
        )

    def _settle(
        self,
        reservation: Reservation,
        *,
        status: str,
        http_status: int | None = None,
        usage: dict[str, int] | None = None,
        estimated: float = 0.0,
        request_id: str | None = None,
        error_code: str | None = None,
        started: float,
    ) -> None:
        if self.budget is None:
            return
        self.budget.settle(
            reservation,
            status=status,
            usage=usage,
            estimated_list_price_cny=estimated,
            http_status=safe_http_status(http_status),
            request_id=_controlled_request_id(request_id),
            error_code=None if error_code is None else safe_error_code(error_code),
            elapsed_seconds=time.monotonic() - started,
        )


class LexicalReranker:
    """离线替代排序：问题词/二元组在文档中的覆盖度；明确 provider=offline-lexical。"""

    provider = "offline-lexical"
    model = "lexical-overlap-v1"

    def rerank(self, query: str, documents: Sequence[str], *, top_n: int | None = None) -> RerankResponse:
        query_tokens = set(cut(query)) | set(bigrams(query))
        query_tokens = {token for token in query_tokens if len(token) >= 2}
        scored: list[RerankResult] = []
        for index, document in enumerate(documents):
            doc_tokens = set(cut(document)) | set(bigrams(document))
            score = sum(len(token) for token in query_tokens if token in doc_tokens)
            scored.append(RerankResult(index=index, score=float(score)))
        maximum = max((item.score for item in scored), default=0.0)
        if maximum > 0:
            scored = [RerankResult(item.index, item.score / maximum) for item in scored]
        scored.sort(key=lambda item: (-item.score, item.index))
        limit = len(scored) if top_n is None else max(1, min(int(top_n), len(scored)))
        return RerankResponse(
            results=tuple(scored[:limit]),
            model=self.model,
            provider=self.provider,
            usage={},
            request_id=None,
            estimated_list_price_cny=0.0,
        )


class DeepSeekChatProvider:
    """DeepSeek 文本回答；真实调用要求已知单价并预留预算。"""

    provider = "deepseek"

    @staticmethod
    def _assert_official_profile(config: RagConfig) -> None:
        """S2-H-R3：实际 rag-chat 构造/发送前也必须过官方不可弱化下界。"""
        from urllib.parse import urlsplit

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
            raise BudgetPricingUnknown(str(exc)) from None

    def __init__(
        self,
        config: RagConfig,
        *,
        budget: BudgetLedger | None = None,
        transport: httpx.BaseTransport | None = None,
        require_budget: bool = True,
        prompt_meter: Any | None = None,
        settlement_policy: SettlementPolicy | None = None,
    ) -> None:
        if not config.chat_base_url or not config.chat_model or not config.chat_api_key:
            raise RagConfigError("chat 配置不完整")
        if config.chat_input_price_per_million_cny is None or config.chat_output_price_per_million_cny is None:
            raise BudgetPricingUnknown("DeepSeek 单价未配置，不能预留真实调用预算")
        if config.chat_max_input_tokens is None or config.chat_max_output_tokens is None:
            raise BudgetPricingUnknown("chat 官方最大输入/输出上界未证明，禁发")
        _enforce_zero_retry(config)
        self._assert_official_profile(config)
        self.config = config
        self.model = config.chat_model
        self.budget = budget
        self.require_budget = require_budget
        self.settlement_policy = _validate_settlement_policy(
            settlement_policy,
            kind=KIND_CHAT,
            provider=self.provider,
            model=self.model,
        )
        if self.settlement_policy is not None and budget is None:
            raise RagConfigError("受控版本化结算需要共享账本，禁止无账本运行")
        if self.settlement_policy is not None and config.max_retries != 0:
            raise RagConfigError("受控版本化结算要求零自动重试（max_retries 必须为 0）")
        if prompt_meter is None and config.require_token_meter:
            from ..providers.token_metering import DeepSeekPromptMeter

            if config.chat_tokenizer_path is None or config.chat_tokenizer_sha256 is None:
                raise BudgetPricingUnknown("chat token 计量要求官方 tokenizer 路径/哈希，禁发")
            prompt_meter = DeepSeekPromptMeter.from_files(
                config.chat_tokenizer_path, expected_sha256=config.chat_tokenizer_sha256
            )
        self.prompt_meter = prompt_meter
        self._client = httpx.Client(
            timeout=config.chat_timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def __repr__(self) -> str:
        return f"DeepSeekChatProvider(model={self.model!r})"

    def close(self) -> None:
        self._client.close()

    def complete(self, *, system: str, user: str, max_output_tokens: int | None = None) -> ChatResponse:
        max_tokens = int(max_output_tokens or self.config.max_output_tokens)
        if max_tokens <= 0 or max_tokens > self.config.max_output_tokens:
            raise RagConfigError("max_output_tokens 超出配置上限")
        if (
            self.config.chat_input_price_per_million_cny is None
            or self.config.chat_output_price_per_million_cny is None
            or self.config.chat_max_input_tokens is None
            or self.config.chat_max_output_tokens is None
        ):
            raise BudgetPricingUnknown("chat 官方单价/最大输入/最大输出上界未证明，禁发")
        self._assert_official_profile(self.config)
        context_ceiling = getattr(self.config, "chat_context_ceiling_tokens", None)
        if int(context_ceiling) < int(self.config.chat_max_input_tokens):
            raise BudgetPricingUnknown("context 上限小于 payload 输入闸门，配置矛盾")
        input_bytes = len(str(system).encode("utf-8")) + len(str(user).encode("utf-8"))
        if input_bytes > int(self.config.chat_max_input_tokens):
            raise ChatUnavailable("chat 输入超过保守官方最大输入上界，禁发")
        if max_tokens > self.config.chat_max_output_tokens:
            raise RagConfigError("max_output_tokens 超过官方输出上界")
        # S2-H-R2：预留按官方 context 上限全额输入 + 固定 800 输出，
        # 不再把本地 tokenizer artifact 的小额上界当作可发送证明（artifact 只作离线诊断）。
        reserve_input_tokens = int(context_ceiling)
        reserve_output_tokens = 800
        reserve_cny = _estimated_cny(
            reserve_input_tokens,
            float(self.config.chat_input_price_per_million_cny),
        ) + _estimated_cny(
            reserve_output_tokens,
            float(self.config.chat_output_price_per_million_cny),
        )
        reserve_cny = max(0.001, reserve_cny)
        if reserve_cny > self.config.max_request_cny:
            raise BudgetPricingUnknown("单次 chat 按官方 context 上限全额预留超过单请求上限")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "temperature": 0,
            "max_tokens": max_tokens,
            # S2-H：产品生成请求明确关闭思考模式（官方 Flash 默认开启思考）。
            "thinking": {"type": "disabled"},
        }
        url = f"{self.config.chat_base_url.rstrip('/')}{self.config.chat_path}"
        request_sha = _sha256_json(payload)
        reservation = self._reserve(reserve_cny, request_sha)
        started = time.monotonic()
        try:
            _post_send_recheck(self.budget, reservation)
        except BudgetLedgerInvalid as exc:
            self._settle(
                reservation,
                status="failed",
                error_code="CHAT_POST_AUTH_DENIED",
                started=started,
            )
            raise ChatUnavailable(f"发送前授权/预算复核拒绝，未发送：{exc}") from None
        _record_post_attempt("chat")
        try:
            response = self._client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.config.chat_api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        except httpx.TimeoutException:
            _record_post_outcome("chat", "timeout")
            self._settle(reservation, status="timeout", error_code="CHAT_TIMEOUT", started=started)
            raise
        except httpx.HTTPError:
            _record_post_outcome("chat", "transport_error")
            self._settle(reservation, status="failed", error_code="CHAT_NETWORK", started=started)
            raise
        except BaseException as exc:  # noqa: BLE001 - portal 改写前留最小归因；不结算、不释放预留
            from ..providers.interrupt_trace import record_base_exception

            _record_post_outcome("chat", "base_exception")
            record_base_exception(
                exc,
                component="rag.providers.DeepSeekChatProvider",
                stage=self.config.stage,
                reservation_id=reservation.reservation_id,
            )
            raise
        else:
            _record_post_outcome("chat", "response")
        if response.status_code != 200:
            self._settle(reservation, status="failed", http_status=response.status_code, error_code="CHAT_HTTP", started=started)
            raise RagConfigError(f"chat 请求失败状态 {response.status_code}")
        try:
            data = response.json()
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("finish_reason")
            text = choice["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("content")
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            merged_usage: dict[str, Any] = dict(usage)
            details = usage.get("completion_tokens_details")
            if isinstance(details, dict):
                merged_usage["reasoning_tokens"] = details.get("reasoning_tokens")
            clean_usage = safe_usage(KIND_CHAT, merged_usage)
        except Exception as exc:
            self._settle(reservation, status="failed", http_status=200,
                         error_code="CHAT_RESPONSE_INVALID", started=started)
            raise ChatUnavailable("chat 响应结构不合法") from exc
        request_id = _controlled_request_id(data.get("id"))
        if self.settlement_policy is not None:
            # J2 受控版本化结算：由实际响应构造证据；缺 cache 拆分/矛盾/超 cap 由 J1 拒绝并全额保留。
            evidence = build_chat_evidence(
                self.settlement_policy,
                request_sha256=request_sha,
                usage=usage,
                http_status=response.status_code,
                streamed=False,
                finish_reason=choice.get("finish_reason"),
                content_complete=True,
                content_parse_ok=True,
            )
            decision = self.budget.settle_usage(  # type: ignore[union-attr]
                reservation,
                evidence=evidence,
                request_id=request_id,
                elapsed_seconds=time.monotonic() - started,
            )
            estimated = float(decision.charge_cny)
            return ChatResponse(
                text=text.strip(),
                model=self.model,
                provider=self.provider,
                usage=clean_usage,
                request_id=request_id,
                estimated_list_price_cny=estimated,
            )
        if int(clean_usage.get("prompt_tokens") or 0) > reserve_input_tokens:
            self._settle(reservation, status="unknown", http_status=200,
                         usage=clean_usage, error_code="CHAT_USAGE_OVER_INPUT_MAX", started=started)
            raise ChatUnavailable("chat usage 超过本次预留采用的输入上界，停止且标未证明")
        if int(clean_usage.get("completion_tokens") or 0) > int(self.config.chat_max_output_tokens):
            self._settle(reservation, status="unknown", http_status=200,
                         usage=clean_usage, error_code="CHAT_USAGE_OVER_OUTPUT_MAX", started=started)
            raise ChatUnavailable("chat usage 超过官方输出上界，停止且标未证明")
        estimated = _estimated_cny(
            int(clean_usage.get("prompt_tokens") or reserve_input_tokens),
            float(self.config.chat_input_price_per_million_cny),
        ) + _estimated_cny(
            int(clean_usage.get("completion_tokens") or max_tokens),
            float(self.config.chat_output_price_per_million_cny),
        )
        self._settle(
            reservation,
            status="succeeded",
            http_status=200,
            usage=clean_usage,
            estimated=estimated,
            request_id=request_id,
            started=started,
        )
        return ChatResponse(
            text=text.strip(),
            model=self.model,
            provider=self.provider,
            usage=clean_usage,
            request_id=request_id,
            estimated_list_price_cny=estimated,
        )

    def _reserve(self, max_cny: float, request_sha256: str) -> Reservation:
        if self.budget is None:
            if self.require_budget:
                raise RagConfigError("真实 chat 调用必须提供共享预算账本")
            return Reservation("test-" + request_sha256[:12], "TEST", "chat", self.provider, self.model, max_cny, request_sha256, "")
        return self.budget.reserve(
            kind="chat",
            provider=self.provider,
            model=self.model,
            max_cny=max_cny,
            request_sha256=request_sha256,
            settlement_policy=self.settlement_policy,
        )

    def _settle(
        self,
        reservation: Reservation,
        *,
        status: str,
        http_status: int | None = None,
        usage: dict[str, int] | None = None,
        estimated: float = 0.0,
        request_id: str | None = None,
        error_code: str | None = None,
        started: float,
    ) -> None:
        if self.budget is None:
            return
        self.budget.settle(
            reservation,
            status=status,
            usage=usage,
            estimated_list_price_cny=estimated,
            http_status=safe_http_status(http_status),
            request_id=_controlled_request_id(request_id),
            error_code=None if error_code is None else safe_error_code(error_code),
            elapsed_seconds=time.monotonic() - started,
        )


def _sha256_json(payload: Any) -> str:
    import json

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
