"""S2-H-R1 定向测试：零自动重试配置、OCR 排除、GO 绑定字段守卫。

只覆盖本轮改动面，不重跑 B0/64 题矩阵。
"""

from __future__ import annotations

import pytest

from mktkb.config import Settings
from mktkb.ingestion.worker import _ocr_from_env
from mktkb.live_authorization import LiveGateError, _parse_scope_bindings
from mktkb.providers import build_ocr_gateway
from mktkb.rag.config import RagConfig, _strict_retry_env
from mktkb.rag.errors import RagConfigError
from mktkb.rag.providers import (
    BailianEmbeddingProvider,
    BailianRerankProvider,
    DeepSeekChatProvider,
    _enforce_zero_retry,
)


# ---------------------------------------------------------------- 重试环境变量


def test_retry_env_omitted_is_zero(monkeypatch):
    monkeypatch.delenv("MKTKB_RAG_MAX_RETRIES", raising=False)
    assert _strict_retry_env() == 0
    # 空白值同样按省略处理（安全默认 0），不是 2。
    monkeypatch.setenv("MKTKB_RAG_MAX_RETRIES", "   ")
    assert _strict_retry_env() == 0


@pytest.mark.parametrize("raw", ["2", "0", "5"])
def test_retry_env_accepts_only_explicit_non_negative_int(monkeypatch, raw):
    monkeypatch.setenv("MKTKB_RAG_MAX_RETRIES", raw)
    assert _strict_retry_env() == int(raw)


@pytest.mark.parametrize("raw", ["-1", "2.5", "two", "+2", "0x2", "1e2"])
def test_retry_env_rejects_illegal_values(monkeypatch, raw):
    monkeypatch.setenv("MKTKB_RAG_MAX_RETRIES", raw)
    with pytest.raises(RagConfigError):
        _strict_retry_env()


def test_retry_env_rejects_over_limit(monkeypatch):
    monkeypatch.setenv("MKTKB_RAG_MAX_RETRIES", "6")
    with pytest.raises(RagConfigError):
        _strict_retry_env()


def test_config_rejects_bool_and_negative_retries():
    with pytest.raises(RagConfigError):
        RagConfig(max_retries=True)  # type: ignore[arg-type]
    with pytest.raises(RagConfigError):
        RagConfig(max_retries=-1)


def test_require_zero_retries_rejects_non_zero():
    with pytest.raises(RagConfigError):
        RagConfig(max_retries=2, require_zero_retries=True)
    RagConfig(max_retries=0, require_zero_retries=True)


# ---------------------------------------------------------------- live 计量强制


def _clear_model_env(monkeypatch):
    for key in (
        "MKTKB_RAG_MAX_RETRIES",
        "MKTKB_REQUIRE_TOKEN_METER",
        "MKTKB_TOKENIZER_PATH",
        "MKTKB_TOKENIZER_SHA256",
        "MKTKB_MODEL_MAX_INPUT_TOKENS",
        "MKTKB_MODEL_MAX_OUTPUT_TOKENS",
        "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY",
        "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_from_env_live_forces_zero_retries(monkeypatch):
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("MKTKB_RAG_MAX_RETRIES", "2")
    with pytest.raises(RagConfigError, match="MKTKB_RAG_MAX_RETRIES"):
        RagConfig.from_env(provider_mode="live")


def test_from_env_live_keeps_meter_opt_in_but_forces_zero_retries(monkeypatch):
    """live 只强制零重试；计量开关由部署/GO 打开（打开后缺失 artifact 即拒绝）。"""
    _clear_model_env(monkeypatch)
    config = RagConfig.from_env(provider_mode="live")
    assert config.max_retries == 0
    assert config.require_zero_retries is True
    assert config.require_token_meter is False

    monkeypatch.setenv("MKTKB_REQUIRE_TOKEN_METER", "1")
    with pytest.raises(RagConfigError, match="tokenizer"):
        RagConfig.from_env(provider_mode="live")


def test_go_binding_for_tokenizer_requires_runtime_meter():
    """GO 一旦绑定 tokenizer，运行期必须开启计量；否则产品拒绝真实调用。"""
    from mktkb.qa.service import _go_binds_tokenizer

    assert _go_binds_tokenizer({"chat": {"tokenizer_sha256": "a" * 64}}) is True
    assert _go_binds_tokenizer({"chat": {"model": "deepseek-flash"}}) is False
    assert _go_binds_tokenizer({"rag": {"embedding_model": "text-embedding-v4"}}) is False
    assert _go_binds_tokenizer(None) is False


def test_from_env_offline_keeps_working_without_meter(monkeypatch):
    _clear_model_env(monkeypatch)
    config = RagConfig.from_env(provider_mode="offline")
    assert config.max_retries == 0
    assert config.require_zero_retries is False
    assert config.require_token_meter is False


# ---------------------------------------------------------------- provider 构造期硬拒


class _LiveNonZero:
    """只提供重试闸门需要的三个属性，不构造真实客户端。"""

    provider_mode = "live"
    live = True
    require_zero_retries = True
    max_retries = 2


def test_provider_construction_enforces_zero_retry():
    with pytest.raises(RagConfigError, match="max_retries"):
        _enforce_zero_retry(_LiveNonZero())  # type: ignore[arg-type]


def test_all_three_providers_call_zero_retry_gate():
    """构造期拒绝必须覆盖 embedding/rerank/chat 三类客户端。"""
    for factory in (
        lambda cfg: BailianEmbeddingProvider(cfg, require_budget=False),
        lambda cfg: BailianRerankProvider(cfg, require_budget=False),
        lambda cfg: DeepSeekChatProvider(cfg, require_budget=False),
    ):
        config = RagConfig(
            provider_mode="live",
            embedding_api_key="mock-key",
            rerank_api_key="mock-key",
            chat_model="deepseek-flash",
            chat_base_url="https://api.deepseek.com",
            chat_api_key="mock-key",
            chat_input_price_per_million_cny=2.0,
            chat_output_price_per_million_cny=8.0,
            chat_max_input_tokens=6144,
            chat_max_output_tokens=800,
            max_retries=0,
            require_zero_retries=True,
        )
        # 模拟“绕过构造校验的配置”（手改/反序列化）：provider 构造期仍需硬拒。
        object.__setattr__(config, "max_retries", 2)
        with pytest.raises(RagConfigError, match="max_retries"):
            factory(config)


# ---------------------------------------------------------------- OCR 排除


def test_ocr_disabled_flag_beats_present_credentials(monkeypatch):
    monkeypatch.setenv("MKTKB_OCR_SECRET_ID", "fake-ocr-id")
    monkeypatch.setenv("MKTKB_OCR_SECRET_KEY", "fake-ocr-key")
    monkeypatch.setenv("MKTKB_OCR_DISABLED", "1")
    assert _ocr_from_env() is None
    settings = Settings(
        _env_file=None,
        csrf_secret="test-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=["http://testserver"],
        ocr_disabled=True,
        ocr_secret_id="fake-ocr-id",
        ocr_secret_key="fake-ocr-key",
    )
    assert build_ocr_gateway(settings) is None


def test_ocr_without_flag_still_builds_for_non_smoke_paths(monkeypatch):
    monkeypatch.setenv("MKTKB_OCR_SECRET_ID", "fake-ocr-id")
    monkeypatch.setenv("MKTKB_OCR_SECRET_KEY", "fake-ocr-key")
    monkeypatch.delenv("MKTKB_OCR_DISABLED", raising=False)
    built = _ocr_from_env()
    assert built is not None and type(built).__name__ == "TencentOCRClient"
    # 只构造客户端对象，不发出任何请求（未调用任何方法）。


# ---------------------------------------------------------------- GO 绑定字段守卫


def test_bindings_reject_credentials_but_allow_counts_and_hashes():
    parsed = _parse_scope_bindings(
        {
            "chat": {
                "model": "deepseek-flash",
                "thinking": "disabled",
                "max_output_tokens": 800,
                "max_input_tokens": 6144,
                "tokenizer_sha256": "a" * 64,
                "chat_template_sha256": "b" * 64,
            }
        }
    )
    assert parsed["chat"]["max_output_tokens"] == 800


@pytest.mark.parametrize(
    "name",
    ["api_key", "secret", "secret_key", "password", "authorization", "access_token", "session_cookie", "token"],
)
def test_bindings_reject_credential_names(name):
    with pytest.raises(LiveGateError):
        _parse_scope_bindings({"chat": {name: "x"}})


def test_bindings_reject_credential_values():
    with pytest.raises(LiveGateError):
        _parse_scope_bindings({"chat": {"model_note": "Bearer abcdef"}})
