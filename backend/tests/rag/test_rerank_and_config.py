"""真实适配器的重排/配置边界：MockTransport 解析、429 有界、上下限校验。"""

from __future__ import annotations

import json

import httpx
import pytest

from mktkb.rag.config import RagConfig
from mktkb.rag.errors import RagConfigError, RerankUnavailable
from mktkb.rag.providers import (
    BailianEmbeddingProvider,
    BailianRerankProvider,
    DeepSeekChatProvider,
)


def _config(**overrides) -> RagConfig:
    values = dict(
        provider_mode="offline",
        embedding_api_key="sk-test",
        rerank_api_key="sk-test",
        embedding_base_url="https://example.invalid",
        rerank_base_url="https://example.invalid",
        max_retries=0,
        retry_base_seconds=0.001,
    )
    values.update(overrides)
    return RagConfig(**values)


def test_rerank_parses_scores_and_top_n() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "gte-rerank-v2"
        assert len(payload["input"]["documents"]) == 3
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": 2, "relevance_score": 0.91},
                        {"index": 0, "relevance_score": 0.42},
                        {"index": 1, "relevance_score": 0.1},
                    ]
                },
                "usage": {"total_tokens": 12},
                "request_id": "r1",
            },
        )

    provider = BailianRerankProvider(_config(), transport=httpx.MockTransport(handler), require_budget=False)
    try:
        response = provider.rerank("问题", ["文档一", "文档二", "文档三"], top_n=2)
    finally:
        provider.close()
    assert [item.index for item in response.results] == [2, 0]
    assert response.results[0].score == pytest.approx(0.91)
    assert response.usage["total_tokens"] == 12


def test_rerank_429_is_bounded() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(429, json={"code": "Throttling"})

    provider = BailianRerankProvider(
        _config(max_retries=1), transport=httpx.MockTransport(handler), require_budget=False
    )
    try:
        with pytest.raises(RerankUnavailable):
            provider.rerank("问题", ["文档一"])
    finally:
        provider.close()
    assert calls["count"] == 2


def test_config_rejects_invalid_limits_and_live_without_key() -> None:
    with pytest.raises(RagConfigError):
        RagConfig(max_output_tokens=0)
    with pytest.raises(RagConfigError):
        RagConfig(embedding_batch_size=11)
    with pytest.raises(RagConfigError):
        RagConfig(provider_mode="live", embedding_api_key="").require_live_credentials()


def test_missing_budget_is_rejected_before_http() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"data": [], "usage": {}})

    provider = BailianEmbeddingProvider(
        _config(), transport=httpx.MockTransport(handler), require_budget=True
    )
    try:
        with pytest.raises(RagConfigError):
            provider.embed(["文本"])
    finally:
        provider.close()
    assert calls["count"] == 0


def test_chat_prices_can_be_read_from_environment_without_leaking(monkeypatch) -> None:
    monkeypatch.setenv("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY", "1.5")
    monkeypatch.setenv("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY", "2.5")
    config = RagConfig.from_env(provider_mode="offline")
    assert config.chat_input_price_per_million_cny == pytest.approx(1.5)
    assert config.chat_output_price_per_million_cny == pytest.approx(2.5)
    assert "sk-" not in repr(config)


def test_chat_max_output_tokens_is_enforced_before_http() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    config = _config(
        chat_base_url="https://api.deepseek.com",
        chat_model="deepseek-flash",
        chat_api_key="sk-test",
        chat_input_price_per_million_cny=2.0,
        chat_output_price_per_million_cny=8.0,
        chat_max_input_tokens=6144,
        chat_max_output_tokens=800,
        chat_reserve_profile="model_context_ceiling",
        chat_context_ceiling_tokens=1_048_576,
        max_output_tokens=800,
    )
    provider = DeepSeekChatProvider(config, transport=httpx.MockTransport(handler), require_budget=False)
    try:
        with pytest.raises(RagConfigError):
            provider.complete(system="s", user="u", max_output_tokens=801)
    finally:
        provider.close()
    assert calls["count"] == 0
