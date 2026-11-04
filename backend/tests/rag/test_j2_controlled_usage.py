"""S2-J2 定向测试：受控字段白名单 + 版本化 chat/E/R 预留-发送-结算（Mock-only）。

只使用隔离账本（``tmp_path``）与 ``httpx.MockTransport``；不发真实网络、不读 `.env`、
不写真实 budget/ledger/GO；每用例独立 ledger（历史 0.03 元）。
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from mktkb.rag.budget import BudgetLedger, SettlementNotReleasable
from mktkb.rag.config import RagConfig
from mktkb.rag.controlled_usage import (
    ControlledFieldError,
    build_chat_evidence,
    build_total_evidence,
    safe_dimensions,
    safe_error_code,
    safe_http_status,
    safe_request_id,
    safe_usage,
    usage_for_evidence,
)
from mktkb.rag.providers import (
    BailianEmbeddingProvider,
    BailianRerankProvider,
    DeepSeekChatProvider,
)
from mktkb.rag.settlement_policy import CHAT_PROMPT_TOKENS_CAP, SETTLEMENT_VERSION, build_policy

STAGE = "S2-J2-TEST"
DIM = 8
SECRET = "sk-S2J2-SYNTH-SECRET-DO-NOT-LEAK-0123456789"
LONG_SECRET_ID = "Authorization: Bearer " + SECRET


# ---------------------------------------------------------------- 隔离账本/配置


def make_ledger(tmp_path: Path, *, stage_limit: float = 9.66, max_requests: int = 400) -> BudgetLedger:
    ledger_path = tmp_path / "live-ledger.jsonl"
    budget_path = tmp_path / "budget.json"
    ledger_path.write_text(
        json.dumps(
            {
                "event": "historical_import",
                "accounted_cny": 0.03,
                "estimated_success_list_price_cny": 0.0000352,
                "provider_billed_cny": None,
                "note": "S2-J2 isolated test ledger",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    budget_path.write_text(
        json.dumps(
            {
                "limit_cny": 10.0,
                "historical_conservative_accounted_cny": 0.03,
                "stages": {STAGE: stage_limit},
                "ledger": ledger_path.as_posix(),
                "provider_billed_cny": None,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return BudgetLedger(
        ledger_path,
        budget_path,
        stage=STAGE,
        stage_limit_cny=stage_limit,
        max_requests=max_requests,
    )


def live_config(tmp_path: Path) -> RagConfig:
    return RagConfig(
        provider_mode="live",
        data_dir=tmp_path,
        embedding_model="text-embedding-v4",
        embedding_dimensions=DIM,
        embedding_base_url="https://dashscope.aliyuncs.com",
        embedding_api_key="sk-test-j2-fake-embedding",
        rerank_model="gte-rerank-v2",
        rerank_base_url="https://dashscope.aliyuncs.com",
        rerank_api_key="sk-test-j2-fake-rerank",
        rerank_max_request_tokens=30000,
        chat_model="deepseek-flash",
        chat_base_url="https://api.deepseek.com/v1",
        chat_api_key="sk-test-j2-fake-chat",
        chat_input_price_per_million_cny=2.0,
        chat_output_price_per_million_cny=8.0,
        chat_max_input_tokens=6144,
        chat_max_output_tokens=800,
        chat_reserve_profile="model_context_ceiling",
        chat_context_ceiling_tokens=1_048_576,
        max_output_tokens=800,
        max_request_cny=2.11,
        max_retries=0,
        require_zero_retries=False,
    )


def ledger_events(ledger: BudgetLedger) -> list[dict]:
    return [
        json.loads(line)
        for line in ledger.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def ledger_bytes(ledger: BudgetLedger) -> bytes:
    return ledger.ledger_path.read_bytes()


def embedding_handler(*, usage=None, status=200, request_id="req-emb-1", rows=None):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append({"path": request.url.path, "body": body})
        texts = body.get("input") or []
        data = [
            {"object": "embedding", "index": index, "embedding": [0.01 + index * 0.001] * DIM}
            for index in range(len(texts) if rows is None else rows)
        ]
        payload = {"object": "list", "data": data, "model": body.get("model", "text-embedding-v4")}
        if usage is not None:
            payload["usage"] = usage
        if request_id is not None:
            payload["id"] = request_id
        return httpx.Response(status, json=payload)

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


def rerank_handler(*, usage=None, status=200, request_id="req-rerank-1"):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append({"path": request.url.path, "body": body})
        documents = (body.get("input") or {}).get("documents") or []
        payload = {
            "output": {
                "results": [
                    {"index": index, "relevance_score": round(1 / (index + 1), 6)}
                    for index in range(len(documents))
                ]
            },
            "request_id": request_id,
        }
        if usage is not None:
            payload["usage"] = usage
        return httpx.Response(status, json=payload)

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


def chat_handler(*, content=None, usage=None, finish_reason="stop", status=200, request_id="req-chat-1"):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append({"path": request.url.path, "body": body})
        text = content if content is not None else json.dumps({"answer": "答案", "source_ids": ["s1"]}, ensure_ascii=False)
        payload = {
            "id": request_id,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": text},
                }
            ],
        }
        if usage is not None:
            payload["usage"] = usage
        return httpx.Response(status, json=payload)

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


CHAT_USAGE_OK = {
    "prompt_tokens": 1000,
    "completion_tokens": 200,
    "total_tokens": 1200,
    "prompt_cache_hit_tokens": 300,
    "prompt_cache_miss_tokens": 700,
}


def embedding(ledger, handler, tmp_path, *, policy=True):
    provider = BailianEmbeddingProvider(
        live_config(tmp_path),
        budget=ledger,
        transport=httpx.MockTransport(handler),
        settlement_policy=build_policy("embedding", model="text-embedding-v4") if policy else None,
    )
    try:
        return provider.embed(["测试文本一", "测试文本二"])
    finally:
        provider.close()


def rerank(ledger, handler, tmp_path, *, policy=True):
    provider = BailianRerankProvider(
        live_config(tmp_path),
        budget=ledger,
        transport=httpx.MockTransport(handler),
        settlement_policy=build_policy("rerank", model="gte-rerank-v2") if policy else None,
    )
    try:
        return provider.rerank("测试查询", ["文档一", "文档二"])
    finally:
        provider.close()


def chat(ledger, handler, tmp_path, *, policy=True):
    provider = DeepSeekChatProvider(
        live_config(tmp_path),
        budget=ledger,
        transport=httpx.MockTransport(handler),
        settlement_policy=build_policy("chat", model="deepseek-flash") if policy else None,
    )
    try:
        return provider.complete(system="系统", user="用户")
    finally:
        provider.close()


# ---------------------------------------------------------------- 白名单


def test_safe_request_id_hashes_all_external_ids_and_keeps_internal_refs_idempotent():
    """S2-J2-R1：任何外部供应商 request_id 都不原文返回，统一不可逆哈希引用。

    - 安全字符集内的短凭据形态串（如合成 ``sk-...``）、合法常规 id、外部伪造的
      ``sha256:<32hex>`` 前缀都必须被哈希（不允许前缀冒充内部引用）；
    - 本模块返回的内部引用再次收敛时幂等（多层调用不出现 hash-of-hash）；
    - 空/非字符串 → None；超长不截断原文、直接哈希。
    """

    def ref(raw: str) -> str:
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    raw_ids = (
        "req-123_abc:def",  # 合法常规 id（外部仍不得原文持久化）
        "sk-S2J2-R1-SYNTH-SECRET-A1B2C3D4E5F6",  # 安全字符集内短凭据形态串
        "AKID.S2J2R1.SYNTH.SECRET.F6E5D4C3B2A1",  # 另一安全字符集凭据形态
        "sha256:" + "0123456789abcdef0123456789abcdef",  # 外部伪造内部前缀
        "x" * 65,  # 超长
        LONG_SECRET_ID,  # 非安全字符集，既有路径回归
    )
    for raw in raw_ids:
        value = safe_request_id(raw)
        assert value is not None and value.startswith("sha256:")
        assert value == ref(raw)
        assert value != raw
        assert SECRET not in value and "Authorization" not in value
        assert len(value) <= 71
        # 内部引用多层重复收敛必须幂等（不 hash-of-hash）。
        assert safe_request_id(value) == value
        assert safe_request_id(safe_request_id(value)) == value

    assert safe_request_id(None) is None
    assert safe_request_id("") is None
    assert safe_request_id("   ") is None
    assert safe_request_id(1234) is None
    overlong = safe_request_id("y" * 4096)
    assert overlong == ref("y" * 4096)
    assert len(overlong) <= 71


def test_safe_dimensions_accepts_int_range_and_rejects_secret_or_bad_types():
    assert safe_dimensions([1024]) == (1024,)
    assert safe_dimensions((1024,), expected=(1024,)) == (1024,)
    with pytest.raises(ControlledFieldError):
        safe_dimensions(1024)  # 非序列
    with pytest.raises(ControlledFieldError):
        safe_dimensions([True])
    with pytest.raises(ControlledFieldError):
        safe_dimensions([1.5])
    with pytest.raises(ControlledFieldError):
        safe_dimensions([4097])
    with pytest.raises(ControlledFieldError):
        safe_dimensions([1024], expected=(768,))
    with pytest.raises(ControlledFieldError) as caught:
        safe_dimensions([LONG_SECRET_ID])
    assert SECRET not in str(caught.value)


def test_safe_http_status_and_error_code_are_controlled():
    assert safe_http_status(200) == 200
    assert safe_http_status(429) == 429
    for bad in (True, "200", 99, 600, None, 200.0):
        assert safe_http_status(bad) is None
    for code in ("CHAT_TIMEOUT", "EMBEDDING_HTTP", "OCR_INVALID_OUTPUT", "RERANK_RATE_LIMITED"):
        assert safe_error_code(code) == code
    for bad in (None, 200, "", "api_key=" + SECRET, "CHAT_TIMEOUT " + SECRET, "x" * 100):
        assert safe_error_code(bad) == "PROVIDER_ERROR"
        assert SECRET not in safe_error_code(bad)


def test_usage_whitelist_vs_evidence_mapping():
    raw = {
        "total_tokens": 12,
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "prompt_cache_hit_tokens": 4,
        "prompt_cache_miss_tokens": 6,
        "unknown_key": "sk-" + SECRET,
        "bool_key": True,
        "negative": -1,
    }
    clean = safe_usage("embedding", raw)
    assert clean == {"total_tokens": 12, "prompt_tokens": 10, "completion_tokens": 2,
                     "prompt_cache_hit_tokens": 4, "prompt_cache_miss_tokens": 6}
    # 证据映射保留未知键，让 J1 以 unknown_usage_field fail closed（不静默吞掉）
    evidence_map = usage_for_evidence("embedding", raw)
    assert "unknown_key" in evidence_map
    chat_raw = {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
        "prompt_cache_hit_tokens": 4,
        "prompt_cache_miss_tokens": 6,
        "completion_tokens_details": {"reasoning_tokens": 1},
    }
    normalized = usage_for_evidence("chat", chat_raw)
    assert "completion_tokens_details" not in normalized
    assert normalized["reasoning_tokens"] == 1
    assert safe_usage("ocr", {"total_tokens": 1}) == {}


def test_build_evidence_rejects_kind_mismatch_and_bad_request_sha():
    policy = build_policy("embedding", model="text-embedding-v4")
    with pytest.raises(ControlledFieldError):
        build_total_evidence(build_policy("chat", model="deepseek-flash"), request_sha256="0" * 64, usage={"total_tokens": 1})
    with pytest.raises(ControlledFieldError):
        build_total_evidence(policy, request_sha256="not-hex", usage={"total_tokens": 1})
    with pytest.raises(ControlledFieldError):
        build_chat_evidence(build_policy("embedding", model="text-embedding-v4"), request_sha256="0" * 64, usage=CHAT_USAGE_OK)
    evidence = build_total_evidence(policy, request_sha256="a" * 64, usage={"total_tokens": 1, "secret": SECRET})
    assert evidence.kind == "embedding"
    assert "secret" in dict(evidence.usage)  # 交给 J1 判 unknown_usage_field


# ---------------------------------------------------------------- 版本化 embedding / rerank


def test_versioned_embedding_success_releases_unused_reserve(tmp_path):
    ledger = make_ledger(tmp_path)
    handler = embedding_handler(usage={"total_tokens": 1000})
    response = embedding(ledger, handler, tmp_path)
    assert response.estimated_list_price_cny == pytest.approx(0.0005)
    assert len(handler.calls) == 1
    events = ledger_events(ledger)
    reserved = [item for item in events if item.get("event") == "reserved"]
    results = [item for item in events if item.get("event") == "result"]
    assert len(reserved) == 1 and len(results) == 1
    assert reserved[0]["settlement_policy"]["version"] == SETTLEMENT_VERSION
    assert reserved[0]["reserve_cny"] == 0.04096
    assert results[0]["status"] == "succeeded"
    assert results[0]["provider_billed_cny"] is None
    assert results[0]["conservative_charge_cny"] == pytest.approx(0.0005)
    assert results[0]["settlement"]["usage"] == {"total_tokens": 1000}
    assert results[0]["dimensions"] == [DIM]
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.0305)
    assert summary.historical_conservative_cny == pytest.approx(0.03)


def test_versioned_embedding_over_cap_keeps_full_and_raises(tmp_path):
    ledger = make_ledger(tmp_path)
    handler = embedding_handler(usage={"total_tokens": 4097})
    with pytest.raises(SettlementNotReleasable) as caught:
        embedding(ledger, handler, tmp_path)
    assert caught.value.reason == "over_cap_total"
    events = ledger_events(ledger)
    results = [item for item in events if item.get("event") == "result"]
    assert results[0]["status"] == "unknown"
    assert results[0]["error_code"] == "SETTLEMENT_NOT_RELEASABLE:over_cap_total"
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.04096)


def test_versioned_embedding_missing_total_keeps_full(tmp_path):
    ledger = make_ledger(tmp_path)
    handler = embedding_handler(usage={"prompt_tokens": 10})
    with pytest.raises(SettlementNotReleasable) as caught:
        embedding(ledger, handler, tmp_path)
    assert caught.value.reason == "usage_missing:total_tokens"
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.04096)


def test_versioned_embedding_unknown_usage_field_fails_closed_without_secret_leak(tmp_path):
    ledger = make_ledger(tmp_path)
    handler = embedding_handler(
        usage={"total_tokens": 1000, "api_key": SECRET, "nested": {"authorization": SECRET}}
    )
    with pytest.raises(SettlementNotReleasable) as caught:
        embedding(ledger, handler, tmp_path)
    assert caught.value.reason == "unknown_usage_field"
    raw = ledger_bytes(ledger)
    assert SECRET.encode("utf-8") not in raw
    assert b"api_key" not in raw
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.04096)


def test_versioned_embedding_http_failure_keeps_full_and_no_settlement_block(tmp_path):
    ledger = make_ledger(tmp_path)
    handler = embedding_handler(status=500)
    with pytest.raises(Exception):
        embedding(ledger, handler, tmp_path)
    events = ledger_events(ledger)
    results = [item for item in events if item.get("event") == "result"]
    assert results[0]["status"] == "failed"
    assert "settlement" not in results[0]
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.04096)


def test_legacy_embedding_path_still_uses_old_settle(tmp_path):
    ledger = make_ledger(tmp_path)
    handler = embedding_handler(usage={"total_tokens": 1000})
    embedding(ledger, handler, tmp_path, policy=False)
    events = ledger_events(ledger)
    reserved = [item for item in events if item.get("event") == "reserved"]
    results = [item for item in events if item.get("event") == "result"]
    assert "settlement_policy" not in reserved[0]
    assert "settlement" not in results[0]
    assert results[0]["conservative_charge_cny"] == pytest.approx(0.04096)
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.04096)


def test_legacy_path_sanitizes_unsafe_request_id_and_usage(tmp_path):
    ledger = make_ledger(tmp_path)
    handler = embedding_handler(usage={"total_tokens": 1000, "unknown": SECRET}, request_id=LONG_SECRET_ID)
    embedding(ledger, handler, tmp_path, policy=False)
    events = ledger_events(ledger)
    results = [item for item in events if item.get("event") == "result"]
    assert results[0]["request_id"].startswith("sha256:")
    assert set(results[0]["usage"]) == {"total_tokens"}
    assert SECRET.encode("utf-8") not in ledger_bytes(ledger)


def test_versioned_rerank_success_and_over_cap(tmp_path):
    ledger = make_ledger(tmp_path)
    rerank(ledger, rerank_handler(usage={"total_tokens": 1000}), tmp_path)
    results = [item for item in ledger_events(ledger) if item.get("event") == "result"]
    assert results[0]["status"] == "succeeded"
    assert results[0]["conservative_charge_cny"] == pytest.approx(0.0008)
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.0008)

    over_dir = tmp_path / "over"
    over_dir.mkdir()
    ledger2 = make_ledger(over_dir)
    with pytest.raises(SettlementNotReleasable) as caught:
        rerank(ledger2, rerank_handler(usage={"total_tokens": 6001}), tmp_path)
    assert caught.value.reason == "over_cap_total"
    assert ledger2.summary().accounted_cny == pytest.approx(0.03 + 0.024)


# ---------------------------------------------------------------- 版本化 chat


def test_versioned_chat_success_releases_huge_reserve(tmp_path):
    ledger = make_ledger(tmp_path)
    handler = chat_handler(usage=CHAT_USAGE_OK)
    response = chat(ledger, handler, tmp_path)
    assert response.usage["prompt_cache_hit_tokens"] == 300
    reserved = [item for item in ledger_events(ledger) if item.get("event") == "reserved"]
    results = [item for item in ledger_events(ledger) if item.get("event") == "result"]
    assert reserved[0]["reserve_cny"] == pytest.approx(2.103552)
    assert results[0]["settlement"]["usage"]["prompt_cache_hit_tokens"] == 300
    assert results[0]["conservative_charge_cny"] == pytest.approx(0.0036)
    assert ledger.summary().accounted_cny == pytest.approx(0.0336)


def test_versioned_chat_missing_cache_split_keeps_full(tmp_path):
    ledger = make_ledger(tmp_path)
    usage = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
    with pytest.raises(SettlementNotReleasable) as caught:
        chat(ledger, chat_handler(usage=usage), tmp_path)
    assert caught.value.reason == "usage_missing:prompt_cache_hit_tokens"
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 2.103552)


def test_versioned_chat_over_cap_keeps_full(tmp_path):
    ledger = make_ledger(tmp_path)
    # 超 cap 必须越过当前准入 cap（settlement_policy.CHAT_PROMPT_TOKENS_CAP），
    # 不能写死历史值 1536：cap 已对齐到请求自身上界 6144。
    over_cap = CHAT_PROMPT_TOKENS_CAP + 1
    usage = {
        "prompt_tokens": over_cap,
        "completion_tokens": 10,
        "total_tokens": over_cap + 10,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": over_cap,
    }
    with pytest.raises(SettlementNotReleasable) as caught:
        chat(ledger, chat_handler(usage=usage), tmp_path)
    assert caught.value.reason == "over_cap_prompt"
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 2.103552)


def test_versioned_chat_finish_not_stop_keeps_full_without_settlement(tmp_path):
    ledger = make_ledger(tmp_path)
    with pytest.raises(Exception):
        chat(ledger, chat_handler(usage=CHAT_USAGE_OK, finish_reason="length"), tmp_path)
    results = [item for item in ledger_events(ledger) if item.get("event") == "result"]
    assert results[0]["status"] == "failed"
    assert "settlement" not in results[0]
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 2.103552)


def test_versioned_replay_is_idempotent_and_keeps_history(tmp_path):
    ledger = make_ledger(tmp_path)
    chat(ledger, chat_handler(usage=CHAT_USAGE_OK), tmp_path)
    first = ledger.summary().as_dict()
    second = ledger.summary().as_dict()
    assert first == second
    reopened = BudgetLedger(
        ledger.ledger_path,
        ledger.budget_json_path,
        stage=STAGE,
        stage_limit_cny=9.66,
        max_requests=400,
    )
    assert reopened.summary().as_dict() == first
    assert reopened.summary().historical_conservative_cny == pytest.approx(0.03)
