"""隔离 RAG 配置。

- 离线模式完全不读取或调用供应商；`provider_mode="offline"` 使用确定性替身。
- 真实模式必须显式提供 Key、GO 文件与共享账本；配置对象不打印 Key。
- 价格只用于 usage 标价估算，不等于供应商账单；保守占用由预算账本另行记录。
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..numeric import NumericInvalid, finite_non_negative, finite_positive
from ..official_chat_profile import (
    OFFICIAL_CONTEXT_CEILING_TOKENS as CONSERVATIVE_CONTEXT_CEILING_TOKENS,
    OFFICIAL_MAX_OUTPUT_TOKENS as CONTEXT_CEILING_OUTPUT_TOKENS,
    RESERVE_PROFILE as RESERVE_PROFILE_CONTEXT_CEILING,
)
from .errors import RagConfigError

DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"
DEFAULT_EMBEDDING_DIMENSIONS = 1024
DEFAULT_EMBEDDING_BASE_URL = "https://dashscope.aliyuncs.com"
DEFAULT_RERANK_MODEL = "gte-rerank-v2"
DEFAULT_RERANK_PATH = "/api/v1/services/rerank/text-rerank/text-rerank"
DEFAULT_EMBEDDING_PATH = "/compatible-mode/v1/embeddings"
DEFAULT_CHAT_PATH = "/chat/completions"

# S2-H-R2：保守 token 预算 profile。按官方当前模型公开的最大 context/输入额度
# **全额**预留输入，输出固定 800；不依赖本地 tokenizer artifact 的逐版本匹配证明。
# S2-H-R3：数值下界单一来源在 mktkb.official_chat_profile，产品入口必须经过该 policy。

# 官方标价（2026-11-01 只读核对）：北京 text-embedding-v4 0.5 元/百万输入 token；
# gte-rerank-v2 0.8 元/百万输入 token。仅用于估算，不是账单。
EMBEDDING_PRICE_PER_MILLION_CNY = 0.5
RERANK_PRICE_PER_MILLION_CNY = 0.8


@dataclass(frozen=True)
class RagConfig:
    provider_mode: str = "offline"  # offline / live
    data_dir: Path = Path("docs/evidence/LOCAL-R1-20261101/S1-DEV/data")
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    embedding_base_url: str = DEFAULT_EMBEDDING_BASE_URL
    embedding_path: str = DEFAULT_EMBEDDING_PATH
    embedding_api_key: str = ""
    embedding_batch_size: int = 10
    embedding_timeout_seconds: float = 20.0
    embedding_price_per_million_cny: float = EMBEDDING_PRICE_PER_MILLION_CNY

    rerank_model: str = DEFAULT_RERANK_MODEL
    rerank_base_url: str = DEFAULT_EMBEDDING_BASE_URL
    rerank_path: str = DEFAULT_RERANK_PATH
    rerank_api_key: str = ""
    rerank_timeout_seconds: float = 20.0
    rerank_price_per_million_cny: float = RERANK_PRICE_PER_MILLION_CNY
    rerank_top_n: int = 30
    rerank_max_documents: int = 50
    rerank_max_single_tokens: int = 4000
    rerank_max_request_tokens: int = 30000

    chat_model: str = ""
    chat_base_url: str = ""
    chat_path: str = DEFAULT_CHAT_PATH
    chat_api_key: str = ""
    chat_timeout_seconds: float = 30.0
    chat_input_price_per_million_cny: float | None = None
    chat_output_price_per_million_cny: float | None = None
    chat_max_input_tokens: int | None = None
    chat_max_output_tokens: int | None = None
    # S2-H-R2：live chat 必须声明保守 profile；ceiling 是官方允许的最大输入/context 额度，
    # 预留按 ceiling（不是按本地 meter 的小额上界）。
    chat_reserve_profile: str | None = None
    chat_context_ceiling_tokens: int | None = None
    max_output_tokens: int = 800

    chunk_max_chars: int = 900
    chunk_max_units: int = 6
    chunk_overlap_units: int = 1
    top_k: int = 8
    candidate_limit: int = 5000
    vector_candidate_limit: int = 50
    page_size: int = 10
    max_page_size: int = 50
    business_date: str | None = None
    max_request_cny: float = 0.10
    stage: str = "S1-DEV"
    stage_limit_cny: float = 3.0
    budget_ledger_path: Path | None = None
    budget_json_path: Path | None = None
    max_retries: int = 2
    retry_base_seconds: float = 0.2
    # S2-H：真实 smoke 要求显式零重试；由 from_env(live)/运行器置 True 后，
    # 任何非 0 max_retries 都在配置阶段拒绝，而不是只在测试里临时改值。
    require_zero_retries: bool = False
    # S2-H：真实 chat 的 token/费用上界必须来自官方 tokenizer artifact；
    # 路径/哈希缺失时 require_token_meter=True 的 live 路径在构造阶段拒绝。
    chat_tokenizer_path: Path | None = None
    chat_tokenizer_sha256: str | None = None
    require_token_meter: bool = False
    # 调用面强制约束：只有能被运行时拦死的开关才允许在计划里把对应上界降为 0。
    disable_query_embedding: bool = False
    record_only: bool = False
    hard_filters: tuple[str, ...] = field(
        default_factory=lambda: (
            "store",
            "item",
            "product",
            "channel",
            "price_type",
            "identifier",
        )
    )

    def __post_init__(self) -> None:
        if self.provider_mode not in ("offline", "live"):
            raise RagConfigError("provider_mode 只允许 offline/live")
        if self.embedding_dimensions <= 0:
            raise RagConfigError("embedding_dimensions 必须为正整数")
        if self.embedding_batch_size <= 0 or self.embedding_batch_size > 10:
            raise RagConfigError("embedding_batch_size 必须在 1～10（text-embedding-v4 单次上限）")
        _positive_config(self.max_request_cny, "max_request_cny")
        _positive_config(self.stage_limit_cny, "stage_limit_cny")
        _non_negative_config(self.embedding_price_per_million_cny, "embedding_price_per_million_cny")
        _non_negative_config(self.rerank_price_per_million_cny, "rerank_price_per_million_cny")
        if self.chat_input_price_per_million_cny is not None:
            _non_negative_config(self.chat_input_price_per_million_cny, "chat_input_price_per_million_cny")
        if self.chat_output_price_per_million_cny is not None:
            _non_negative_config(self.chat_output_price_per_million_cny, "chat_output_price_per_million_cny")
        if not 1 <= self.top_k <= 50:
            raise RagConfigError("top_k 必须在 1～50")
        if self.vector_candidate_limit <= 0:
            raise RagConfigError("vector_candidate_limit 必须为正数")
        if not 1 <= self.page_size <= self.max_page_size <= 50:
            raise RagConfigError("page_size 必须在 1～max_page_size（<=50）")
        if self.max_output_tokens <= 0:
            raise RagConfigError("max_output_tokens 必须为正数")
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int):
            raise RagConfigError("max_retries 必须是整数")
        if not 0 <= self.max_retries <= 5:
            raise RagConfigError("max_retries 必须在 0～5")
        if self.require_zero_retries and self.max_retries != 0:
            raise RagConfigError("真实 smoke 要求 max_retries=0，拒绝任何非零自动重试")
        if (self.chat_tokenizer_path is None) != (self.chat_tokenizer_sha256 is None):
            raise RagConfigError("chat_tokenizer_path 与 chat_tokenizer_sha256 必须同时提供")
        if self.chat_tokenizer_sha256 is not None:
            digest = str(self.chat_tokenizer_sha256).strip().lower()
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise RagConfigError("chat_tokenizer_sha256 必须是 64 位十六进制")
        if self.require_token_meter and (
            self.chat_tokenizer_path is None or self.chat_tokenizer_sha256 is None
        ):
            raise RagConfigError(
                "require_token_meter=True 时必须提供官方 tokenizer 路径与 sha256，禁止回退字节启发式"
            )
        if self.chat_max_input_tokens is not None and self.chat_max_input_tokens <= 0:
            raise RagConfigError("chat_max_input_tokens 必须为正数")
        if self.chat_max_output_tokens is not None:
            if self.chat_max_output_tokens <= 0:
                raise RagConfigError("chat_max_output_tokens 必须为正数")
            if self.max_output_tokens > self.chat_max_output_tokens:
                raise RagConfigError("max_output_tokens 超过官方 max_output_tokens")
        if (self.chat_reserve_profile is None) != (self.chat_context_ceiling_tokens is None):
            raise RagConfigError(
                "chat_reserve_profile 与 chat_context_ceiling_tokens 必须同时提供"
            )
        if self.chat_reserve_profile is not None:
            if self.chat_reserve_profile != RESERVE_PROFILE_CONTEXT_CEILING:
                raise RagConfigError(
                    f"chat_reserve_profile 只允许 {RESERVE_PROFILE_CONTEXT_CEILING}"
                )
            if self.chat_context_ceiling_tokens is None or self.chat_context_ceiling_tokens <= 0:
                raise RagConfigError("chat_context_ceiling_tokens 必须为正整数")
            if self.chat_max_input_tokens is None:
                raise RagConfigError("model_context_ceiling 需要 payload 输入闸门 chat_max_input_tokens")
            if self.chat_context_ceiling_tokens < self.chat_max_input_tokens:
                raise RagConfigError("chat_context_ceiling_tokens 不能小于 payload 输入闸门")
            if self.chat_max_output_tokens != CONTEXT_CEILING_OUTPUT_TOKENS:
                raise RagConfigError(
                    f"model_context_ceiling 要求官方输出上界固定为 {CONTEXT_CEILING_OUTPUT_TOKENS}"
                )
            if self.max_output_tokens != CONTEXT_CEILING_OUTPUT_TOKENS:
                raise RagConfigError(
                    f"model_context_ceiling 要求实际 max_tokens 固定为 {CONTEXT_CEILING_OUTPUT_TOKENS}"
                )
        if not 1 <= self.embedding_batch_size <= 10:
            raise RagConfigError("embedding_batch_size 必须在 1～10")
        if self.rerank_max_single_tokens <= 0 or self.rerank_max_request_tokens <= 0:
            raise RagConfigError("rerank token 上限必须为正数")
        if self.rerank_max_single_tokens > self.rerank_max_request_tokens:
            raise RagConfigError("rerank 单条 token 上限不能大于请求上限")

    @property
    def live(self) -> bool:
        return self.provider_mode == "live"

    def require_live_credentials(self) -> None:
        if not self.live:
            raise RagConfigError("当前为离线模式，不能调用真实供应商")
        if not self.embedding_api_key.strip():
            raise RagConfigError("缺少 DASHSCOPE_API_KEY，真实 embedding 不可用")
        if not self.embedding_base_url.strip():
            raise RagConfigError("缺少 embedding base URL")
        if not self.rerank_api_key.strip():
            raise RagConfigError("缺少百炼 rerank Key")
        if self.chat_model and (not self.chat_base_url or not self.chat_api_key):
            raise RagConfigError("chat 配置不完整")
        if self.chat_model and (
            self.chat_input_price_per_million_cny is None
            or self.chat_output_price_per_million_cny is None
            or self.chat_max_input_tokens is None
            or self.chat_max_output_tokens is None
        ):
            raise RagConfigError("chat 价格或官方输入/输出上界未知，不能预留真实调用预算")
        if self.chat_model and self.chat_reserve_profile != RESERVE_PROFILE_CONTEXT_CEILING:
            raise RagConfigError(
                "chat live 必须使用 model_context_ceiling 保守 profile（禁止依赖未证明的 tokenizer 小额计量）"
            )
        if self.chat_model and not self.chat_context_ceiling_tokens:
            raise RagConfigError("chat live 缺少官方 context 上限，不能全额预留")
        if self.chat_model and self.require_token_meter and self.chat_tokenizer_path is None:
            raise RagConfigError("chat 要求官方 tokenizer 计量，但未配置路径/哈希，禁发")

    @classmethod
    def from_env(
        cls,
        *,
        provider_mode: str = "offline",
        data_dir: Path | None = None,
        business_date: str | None = None,
        budget_ledger_path: Path | None = None,
        budget_json_path: Path | None = None,
        stage_limit_cny: float = 3.0,
    ) -> "RagConfig":
        """从环境读取配置；只读取值，不输出、不写日志。"""
        dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "")
        dashscope_base = os.environ.get("DASHSCOPE_BASE_URL", DEFAULT_EMBEDDING_BASE_URL).rstrip("/")
        chat_base = os.environ.get("MKTKB_MODEL_BASE_URL", "").rstrip("/")
        live = provider_mode == "live"
        max_retries = _strict_retry_env()
        if live and max_retries != 0:
            raise RagConfigError(
                "MKTKB_RAG_MAX_RETRIES 在 live/smoke 下必须显式为 0；禁止任何非零自动重试"
            )
        require_token_meter = _bool_env("MKTKB_REQUIRE_TOKEN_METER", default=False)
        tokenizer_path_raw = os.environ.get("MKTKB_TOKENIZER_PATH", "").strip()
        tokenizer_sha = os.environ.get("MKTKB_TOKENIZER_SHA256", "").strip() or None
        tokenizer_path = Path(tokenizer_path_raw) if tokenizer_path_raw else None
        reserve_profile = os.environ.get("MKTKB_MODEL_RESERVE_PROFILE", "").strip() or None
        context_ceiling = _int_env("MKTKB_MODEL_CONTEXT_CEILING_TOKENS")
        input_price = _float_env("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY")
        output_price = _float_env("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY")
        chat_ceiling_bound = None
        if (
            reserve_profile == RESERVE_PROFILE_CONTEXT_CEILING
            and context_ceiling is not None
            and input_price is not None
            and output_price is not None
        ):
            chat_ceiling_bound = (
                context_ceiling * input_price / 1_000_000.0
                + CONTEXT_CEILING_OUTPUT_TOKENS * output_price / 1_000_000.0
            )
        request_cap = positive_float_env("MKTKB_RAG_MAX_REQUEST_CNY") or max(
            0.10, chat_ceiling_bound or 0.10
        )
        return cls(
            provider_mode=provider_mode,
            data_dir=data_dir or Path("docs/evidence/LOCAL-R1-20261101/S1-DEV/data"),
            embedding_base_url=dashscope_base,
            rerank_base_url=dashscope_base,
            embedding_api_key=dashscope_key,
            rerank_api_key=dashscope_key,
            chat_base_url=chat_base,
            chat_model=os.environ.get("MKTKB_MODEL_NAME", ""),
            chat_api_key=os.environ.get("MKTKB_MODEL_API_KEY", ""),
            chat_input_price_per_million_cny=_float_env("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY"),
            chat_output_price_per_million_cny=_float_env("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY"),
            chat_max_input_tokens=_int_env("MKTKB_MODEL_MAX_INPUT_TOKENS"),
            chat_max_output_tokens=_int_env("MKTKB_MODEL_MAX_OUTPUT_TOKENS"),
            chat_reserve_profile=reserve_profile,
            chat_context_ceiling_tokens=context_ceiling,
            max_output_tokens=min(
                800,
                _int_env("MKTKB_MODEL_MAX_OUTPUT_TOKENS") or 800,
            ),
            max_request_cny=request_cap,
            max_retries=max_retries,
            require_zero_retries=live,
            chat_tokenizer_path=tokenizer_path,
            chat_tokenizer_sha256=tokenizer_sha,
            require_token_meter=require_token_meter,
            business_date=business_date,
            budget_ledger_path=budget_ledger_path,
            budget_json_path=budget_json_path,
            stage_limit_cny=stage_limit_cny,
        )


def positive_float_env(name: str) -> float | None:
    """环境里的正数（省略/非法/<=0 一律返回 None，由调用方默认拒绝）。"""
    value = _float_env(name)
    return value if value is not None and value > 0 else None


def positive_int_env(name: str) -> int | None:
    """环境里的正整数（省略/非法/<=0 一律返回 None，由调用方默认拒绝）。"""
    value = _int_env(name)
    return value if value is not None and value > 0 else None


def _int_env(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _strict_retry_env() -> int:
    """MKTKB_RAG_MAX_RETRIES：省略=0（安全默认）；非法/负数/超范围一律拒绝。"""
    raw = os.environ.get("MKTKB_RAG_MAX_RETRIES")
    if raw is None or not str(raw).strip():
        return 0
    text = str(raw).strip()
    if not text.isdigit():
        raise RagConfigError("MKTKB_RAG_MAX_RETRIES 必须是非负整数（拒绝小数/符号/空值混写）")
    value = int(text)
    if value > 5:
        raise RagConfigError("MKTKB_RAG_MAX_RETRIES 超过上限 5")
    return value


def _bool_env(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise RagConfigError(f"{name} 只接受 0/1/true/false")


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value):
        # NaN/±Infinity 不是可参与闸门的数值：按“未配置”处理，由调用方默认拒绝。
        return None
    return value if value >= 0 else None


def _positive_config(value: object, label: str) -> float:
    try:
        return finite_positive(value, label)
    except NumericInvalid as exc:
        raise RagConfigError(str(exc)) from None


def _non_negative_config(value: object, label: str) -> float:
    try:
        return finite_non_negative(value, label)
    except NumericInvalid as exc:
        raise RagConfigError(str(exc)) from None


def safe_config_summary(config: RagConfig) -> dict[str, object]:
    """可写入证据的配置摘要：不含 Key、认证头或完整环境。"""
    return {
        "provider_mode": config.provider_mode,
        "embedding_model": config.embedding_model,
        "embedding_dimensions": config.embedding_dimensions,
        "embedding_base_url": _safe_url(config.embedding_base_url),
        "rerank_model": config.rerank_model,
        "rerank_base_url": _safe_url(config.rerank_base_url),
        "chat_model": config.chat_model or None,
        "chunk_max_chars": config.chunk_max_chars,
        "chunk_max_units": config.chunk_max_units,
        "top_k": config.top_k,
        "candidate_limit": config.candidate_limit,
        "stage": config.stage,
        "stage_limit_cny": config.stage_limit_cny,
        "max_request_cny": config.max_request_cny,
        "max_output_tokens": config.max_output_tokens,
        "chat_reserve_profile": config.chat_reserve_profile,
        "chat_context_ceiling_tokens": config.chat_context_ceiling_tokens,
        "max_retries": config.max_retries,
        "require_zero_retries": config.require_zero_retries,
        "require_token_meter": config.require_token_meter,
        "tokenizer_configured": config.chat_tokenizer_path is not None,
        "tokenizer_sha256": config.chat_tokenizer_sha256,
        "disable_query_embedding": config.disable_query_embedding,
        "record_only": config.record_only,
        "credentials_present": bool(config.embedding_api_key),
    }


def _safe_url(url: str) -> str | None:
    if not url:
        return None
    # 只保留 scheme/host/path；去除 userinfo/query/fragment。
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if not parts.scheme or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.hostname}{parts.path}"
