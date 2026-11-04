"""百炼 embedding 适配：1024 维、条数/NaN 校验、批次、429/超时有界处理与 Key 不回显。"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from mktkb.rag.config import RagConfig
from mktkb.rag.errors import EmbeddingDimensionError, EmbeddingRateLimited, EmbeddingResponseError, EmbeddingTimeout
from mktkb.rag.providers import BailianEmbeddingProvider

KEY = "sk-test-secret-never-log"


def _vector(value: float = 0.01) -> list[float]:
    return [value] * 1024


def _payload(count: int, *, dims: int = 1024, nan: bool = False):
    rows = []
    for index in range(count):
        vector = [float("nan")] * dims if nan else [0.01 + index * 0.001] * dims
        rows.append({"embedding": vector, "index": index, "object": "embedding"})
    return {
        "data": rows,
        "model": "text-embedding-v4",
        "object": "list",
        "usage": {"prompt_tokens": 17, "total_tokens": 17},
        "id": "req-test",
    }


def _config(**overrides) -> RagConfig:
    values = dict(
        provider_mode="offline",
        embedding_api_key=KEY,
        embedding_base_url="https://example.invalid",
        embedding_timeout_seconds=1.0,
        max_retries=0,
        retry_base_seconds=0.001,
    )
    values.update(overrides)
    return RagConfig(**values)


def test_embedding_accepts_1024_and_batches_at_ten() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(200, json=_payload(len(payload["input"])))

    provider = BailianEmbeddingProvider(
        _config(), transport=httpx.MockTransport(handler), require_budget=False
    )
    try:
        response = provider.embed([f"文本{i}" for i in range(11)])
    finally:
        provider.close()
    assert len(response.vectors) == 11
    assert response.dimensions == 1024
    assert len(response.vectors[0]) == 1024
    assert len(calls) == 2
    assert len(calls[0]["input"]) == 10
    assert len(calls[1]["input"]) == 1
    assert calls[0]["dimensions"] == 1024
    assert response.usage["total_tokens"] == 34
    # S2-J2-R1：每批供应商 id 都收敛为不可逆哈希引用后再拼接（不落原文）。
    batch_ref = "sha256:" + hashlib.sha256(b"req-test").hexdigest()[:32]
    assert response.request_id == f"{batch_ref},{batch_ref}"


def test_embedding_rejects_wrong_dimensions_and_nan() -> None:
    def wrong_dims(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload(1, dims=1023))

    provider = BailianEmbeddingProvider(
        _config(), transport=httpx.MockTransport(wrong_dims), require_budget=False
    )
    try:
        with pytest.raises(EmbeddingDimensionError):
            provider.embed(["文本"])
    finally:
        provider.close()

    def nan_handler(request: httpx.Request) -> httpx.Response:
        vector = ",".join(["NaN"] * 1024)
        body = (
            '{"data":[{"embedding":[' + vector + '],"index":0,"object":"embedding"}],'
            '"model":"text-embedding-v4","usage":{"total_tokens":1},"id":"nan"}'
        )
        return httpx.Response(200, content=body.encode("utf-8"), headers={"content-type": "application/json"})

    provider = BailianEmbeddingProvider(
        _config(), transport=httpx.MockTransport(nan_handler), require_budget=False
    )
    try:
        with pytest.raises(EmbeddingDimensionError):
            provider.embed(["文本"])
    finally:
        provider.close()


def test_embedding_rejects_wrong_count_and_retries_429_once() -> None:
    def wrong_count(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload(1))

    provider = BailianEmbeddingProvider(
        _config(), transport=httpx.MockTransport(wrong_count), require_budget=False
    )
    try:
        with pytest.raises(EmbeddingResponseError):
            provider.embed(["a", "b"])
    finally:
        provider.close()

    calls = {"count": 0}

    def rate_limited(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"code": "Throttling"})
        return httpx.Response(200, json=_payload(1))

    provider = BailianEmbeddingProvider(
        _config(max_retries=1), transport=httpx.MockTransport(rate_limited), require_budget=False
    )
    try:
        response = provider.embed(["文本"])
    finally:
        provider.close()
    assert calls["count"] == 2
    assert len(response.vectors) == 1


def test_embedding_timeout_is_bounded_and_key_is_not_in_repr() -> None:
    calls = {"count": 0}

    def timeout(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ReadTimeout("simulated timeout")

    provider = BailianEmbeddingProvider(
        _config(max_retries=0), transport=httpx.MockTransport(timeout), require_budget=False
    )
    try:
        assert KEY not in repr(provider)
        with pytest.raises(EmbeddingTimeout):
            provider.embed(["文本"])
    finally:
        provider.close()
    assert calls["count"] == 1


def test_embedding_429_exhausted_is_rate_limited() -> None:
    def always_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"code": "Throttling"})

    provider = BailianEmbeddingProvider(
        _config(max_retries=1), transport=httpx.MockTransport(always_429), require_budget=False
    )
    try:
        with pytest.raises(EmbeddingRateLimited):
            provider.embed(["文本"])
    finally:
        provider.close()
