"""S2-H-R2 定向：model_context_ceiling 保守 profile、强制 bindings、预留不随小额 meter 缩小。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from mktkb import live_authorization as gate_module
from mktkb.live_authorization import LiveGateError, _parse_scope_bindings, resolve_live_gate
from mktkb.providers import build_gateway
from mktkb.providers.budgeted import BudgetedModelGateway, ChatPricing
from mktkb.providers.deepseek import DeepSeekClient
from mktkb.providers.types import CompletionInput, DialogueContext, ModelEvidence
from mktkb.rag.budget import BudgetLedger
from mktkb.rag.config import (
    CONSERVATIVE_CONTEXT_CEILING_TOKENS,
    CONTEXT_CEILING_OUTPUT_TOKENS,
    RESERVE_PROFILE_CONTEXT_CEILING,
    RagConfig,
)
from mktkb.rag.errors import RagConfigError
from mktkb.rag.providers import DeepSeekChatProvider

STAGE = "S2-H-R2-TEST"
HISTORY_CNY = 0.03
# 隔离预算的总上限：测试内用同值环境变量，自洽即可，不再跟随仓库真实预算（20 元）。
PROJECT_TOTAL_LIMIT_CNY = 10.0
CEILING = 1_048_576
INPUT_PRICE = 2.0
OUTPUT_PRICE = 8.0
MAX_INPUT = 6144
BOUND = CEILING * INPUT_PRICE / 1_000_000.0 + CONTEXT_CEILING_OUTPUT_TOKENS * OUTPUT_PRICE / 1_000_000.0

PRICING_ENV = {
    "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com/v1",
    "MKTKB_MODEL_NAME": "deepseek-flash",
    "MKTKB_MODEL_API_KEY": "s2h-r2-mock-key",
    "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY": str(INPUT_PRICE),
    "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY": str(OUTPUT_PRICE),
    "MKTKB_MODEL_MAX_INPUT_TOKENS": str(MAX_INPUT),
    "MKTKB_MODEL_MAX_OUTPUT_TOKENS": "800",
    "MKTKB_MODEL_CONTEXT_CEILING_TOKENS": str(CEILING),
    "MKTKB_MODEL_RESERVE_PROFILE": RESERVE_PROFILE_CONTEXT_CEILING,
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _go_payload(ledger: Path, *, bindings: dict | None) -> dict:
    now = datetime.now(timezone.utc)
    scope = {
        "services": ["rag", "chat"],
        "stage_limits_cny": {STAGE: 5.0},
        "max_requests": 5,
        "max_request_cny": 2.11,
    }
    if bindings is not None:
        scope["bindings"] = bindings
    return {
        "document": "S2-LIVE-GO",
        "stage": STAGE,
        "authorization": "S2-H-R2-UNIT-MOCK-GO",
        "issued_by": "pytest",
        "nonce": "s2h-r2-nonce-0123456789",
        "issued_utc": (now - timedelta(minutes=5)).isoformat(),
        "expires_utc": (now + timedelta(hours=1)).isoformat(),
        "budget_ledger_sha256": _sha(ledger),
        "scope": scope,
    }


def _chat_bindings(**overrides) -> dict:
    chat = {
        "base_url_host": "api.deepseek.com",
        "model": "deepseek-flash",
        "thinking": "disabled",
        "max_input_tokens": MAX_INPUT,
        "max_output_tokens": 800,
        "reserve_profile": RESERVE_PROFILE_CONTEXT_CEILING,
        "context_ceiling_tokens": CEILING,
        "input_price_per_million_cny": INPUT_PRICE,
        "output_price_per_million_cny": OUTPUT_PRICE,
    }
    chat.update(overrides)
    return {"chat": chat}


def _write_ledger(path: Path, *, historical: float = HISTORY_CNY) -> None:
    """自建隔离账本：只含一行 historical_import，不复制仓库共享账本。

    共享账本会随真实阶段增长（当前 83 笔预留），复制它会让“chat 预留条数/累计请求上限”
    类断言随真实用量漂移。
    """
    path.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": historical}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_budget(path: Path, ledger: Path, *, stage_limit: float = 5.0) -> None:
    """自建隔离预算：limit_cny 与测试环境变量同值，stages 只声明本用例阶段。"""
    budget = {
        "limit_cny": PROJECT_TOTAL_LIMIT_CNY,
        "historical_conservative_accounted_cny": HISTORY_CNY,
        "stages": {STAGE: stage_limit},
        "ledger": str(ledger),
    }
    path.write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def gate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    ledger = tmp_path / "live-ledger.jsonl"
    _write_ledger(ledger)
    budget_path = tmp_path / "budget.json"
    _write_budget(budget_path, ledger)
    go = tmp_path / "S2-LIVE-GO.json"
    go.write_text(json.dumps(_go_payload(ledger, bindings=_chat_bindings()), indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(gate_module, "SHARED_LEDGER_PATH", ledger)
    monkeypatch.setattr(gate_module, "SHARED_BUDGET_PATH", budget_path)
    monkeypatch.setattr(gate_module, "PRODUCT_GO_PATH", go)
    # 三件套一致：budget.limit_cny == MKTKB_PROJECT_TOTAL_LIMIT_CNY == 10.0。
    monkeypatch.setenv("MKTKB_PROJECT_TOTAL_LIMIT_CNY", str(PROJECT_TOTAL_LIMIT_CNY))
    monkeypatch.setenv("MKTKB_LIVE_STAGE", STAGE)
    monkeypatch.setenv("MKTKB_RAG_STAGE_LIMIT_CNY", "0.3")
    monkeypatch.setenv("MKTKB_RAG_MAX_REQUESTS", "5")
    for key, value in PRICING_ENV.items():
        monkeypatch.setenv(key, value)
    for key in ("MKTKB_RAG_BUDGET_LEDGER", "MKTKB_RAG_BUDGET_JSON", "MKTKB_RAG_STAGE", "MKTKB_REQUIRE_TOKEN_METER"):
        monkeypatch.delenv(key, raising=False)
    return {"ledger": ledger, "budget": budget_path, "go": go, "root": tmp_path}


def _gate(**overrides):
    params = {
        "stage": STAGE,
        "service": "chat",
        "requested_stage_limit_cny": 5.0,
        "requested_max_requests": 3,
        "request_bound_cny": BOUND,
    }
    params.update(overrides)
    return resolve_live_gate(**params)


def _request() -> CompletionInput:
    return CompletionInput(
        purpose="answer",
        question="湖滨店的展架在哪里？",
        context=DialogueContext(questions=(), entities={}),
        evidence=(ModelEvidence(source_id="s1", text="湖滨店 展架 A 区", fields={"位置": "A 区"}),),
    )


class _SmallMeter:
    """模拟“旧 artifact 小额计量”：若被用于预留会把金额压得很小。"""

    tokenizer_sha256 = "0" * 64
    template_sha256 = "1" * 64

    def prompt_token_upper_bound(self, system: str, user: str) -> int:
        return 10

    def as_dict(self) -> dict:
        return {"tokenizer_sha256": self.tokenizer_sha256, "note": "small fake meter"}


def test_chat_pricing_official_ceiling_worst_case_is_2103552(monkeypatch) -> None:
    monkeypatch.setenv("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY", "2")
    monkeypatch.setenv("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY", "8")
    monkeypatch.setenv("MKTKB_MODEL_MAX_INPUT_TOKENS", "6144")
    monkeypatch.setenv("MKTKB_MODEL_MAX_OUTPUT_TOKENS", "800")
    monkeypatch.setenv("MKTKB_MODEL_CONTEXT_CEILING_TOKENS", str(CONSERVATIVE_CONTEXT_CEILING_TOKENS))
    monkeypatch.setenv("MKTKB_MODEL_RESERVE_PROFILE", RESERVE_PROFILE_CONTEXT_CEILING)
    pricing = ChatPricing.from_env()
    assert pricing is not None
    assert pricing.worst_case_cny() == pytest.approx(2.103552)
    assert pricing.as_dict()["reserve_input_tokens"] == 1_048_576
    assert pricing.as_dict()["reserve_output_tokens"] == 800


def test_chat_pricing_refuses_missing_or_non_conservative_profile(monkeypatch) -> None:
    for key in ("MKTKB_MODEL_CONTEXT_CEILING_TOKENS", "MKTKB_MODEL_RESERVE_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY", "2")
    monkeypatch.setenv("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY", "8")
    monkeypatch.setenv("MKTKB_MODEL_MAX_INPUT_TOKENS", "6144")
    monkeypatch.setenv("MKTKB_MODEL_MAX_OUTPUT_TOKENS", "800")
    assert ChatPricing.from_env() is None
    with pytest.raises(LiveGateError):
        ChatPricing(2.0, 8.0, 6144, 800, "small_meter_profile", 6144)
    with pytest.raises(LiveGateError):
        ChatPricing(2.0, 8.0, 6144, 800, RESERVE_PROFILE_CONTEXT_CEILING, 1000)  # ceiling < payload 闸门


def test_gateway_reserves_full_ceiling_even_with_small_meter(gate_env) -> None:
    gate = _gate()
    pricing = ChatPricing(INPUT_PRICE, OUTPUT_PRICE, MAX_INPUT, 800, RESERVE_PROFILE_CONTEXT_CEILING, CEILING)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "mock-r2",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"answer": "A 区", "source_ids": ["s1"]})},
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 5, "total_tokens": 35},
            },
        )

    inner = DeepSeekClient(
        base_url=PRICING_ENV["MKTKB_MODEL_BASE_URL"],
        model=PRICING_ENV["MKTKB_MODEL_NAME"],
        api_key=PRICING_ENV["MKTKB_MODEL_API_KEY"],
        max_output_tokens=800,
        transport=httpx.MockTransport(handler),
    )
    gateway = BudgetedModelGateway(inner, gate=gate, pricing=pricing, meter=_SmallMeter(), require_meter=False)
    asyncio.run(gateway.complete(_request(), timeout_seconds=5.0))
    events = [json.loads(line) for line in gate_env["ledger"].read_text(encoding="utf-8").splitlines() if line.strip()]
    chat = [event for event in events if event.get("event") == "reserved" and event.get("kind") == "chat"]
    assert len(chat) == 1
    assert chat[0]["reserve_cny"] == pytest.approx(BOUND)
    assert gateway.stats()["pricing"]["reserve_input_tokens"] == CEILING


def test_build_gateway_requires_bindings_and_ceiling_fields(gate_env, monkeypatch) -> None:
    from mktkb.config import Settings

    settings = Settings(
        _env_file=None,
        data_dir=gate_env["root"] / "app",
        database_url=f"sqlite:///{(gate_env['root'] / 'app' / 'a.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="s2h-r2-csrf-secret-0123456789",
        admin_password="UnitPass-1",
        employee_password="UnitPass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        model_base_url=PRICING_ENV["MKTKB_MODEL_BASE_URL"],
        model_name=PRICING_ENV["MKTKB_MODEL_NAME"],
        model_api_key=PRICING_ENV["MKTKB_MODEL_API_KEY"],
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))

    def rewrite(**overrides) -> None:
        gate_env["go"].write_text(
            json.dumps(_go_payload(gate_env["ledger"], bindings=_chat_bindings(**overrides)), indent=2) + "\n",
            encoding="utf-8",
        )

    gateway = build_gateway(settings, transport=transport)
    assert gateway is not None  # 完整绑定通过

    gate_env["go"].write_text(json.dumps(_go_payload(gate_env["ledger"], bindings=None), indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bindings"):
        build_gateway(settings, transport=transport)

    for field, value in (
        ("context_ceiling_tokens", None),
        ("reserve_profile", None),
        ("output_price_per_million_cny", None),
        ("base_url_host", "evil.example"),
        ("max_output_tokens", 500),
    ):
        overrides = {field: value}
        rewrite(**overrides)
        with pytest.raises(ValueError, match="chat live"):
            build_gateway(settings, transport=transport)


def test_rag_config_live_requires_profile_and_derives_request_cap(monkeypatch) -> None:
    with pytest.raises(RagConfigError, match="model_context_ceiling"):
        RagConfig(
            provider_mode="live",
            embedding_api_key="k" * 10,
            rerank_api_key="k" * 10,
            chat_model="deepseek-flash",
            chat_base_url="https://api.deepseek.com",
            chat_api_key="k" * 10,
            chat_input_price_per_million_cny=2.0,
            chat_output_price_per_million_cny=8.0,
            chat_max_input_tokens=6144,
            chat_max_output_tokens=800,
        ).require_live_credentials()

    for key, value in PRICING_ENV.items():
        monkeypatch.setenv(key, value)
    config = RagConfig.from_env(provider_mode="live")
    assert config.chat_reserve_profile == RESERVE_PROFILE_CONTEXT_CEILING
    assert config.chat_context_ceiling_tokens == CEILING
    assert config.max_request_cny >= BOUND


def test_rag_chat_provider_reserves_ceiling(gate_env) -> None:
    ledger = BudgetLedger(
        gate_env["ledger"],
        gate_env["budget"],
        stage=STAGE,
        stage_limit_cny=5.0,
        max_requests=5,
    )
    config = RagConfig(
        provider_mode="live",
        embedding_api_key="k" * 10,
        rerank_api_key="k" * 10,
        chat_model="deepseek-flash",
        chat_base_url="https://api.deepseek.com/v1",
        chat_api_key="k" * 10,
        chat_input_price_per_million_cny=INPUT_PRICE,
        chat_output_price_per_million_cny=OUTPUT_PRICE,
        chat_max_input_tokens=MAX_INPUT,
        chat_max_output_tokens=800,
        chat_reserve_profile=RESERVE_PROFILE_CONTEXT_CEILING,
        chat_context_ceiling_tokens=CEILING,
        max_output_tokens=800,
        max_request_cny=BOUND,
        max_retries=0,
        require_zero_retries=True,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"finish_reason": "stop", "message": {"content": "答案"}}], "usage": {"prompt_tokens": 20, "completion_tokens": 2}},
        )

    provider = DeepSeekChatProvider(config, budget=ledger, transport=httpx.MockTransport(handler))
    try:
        provider.complete(system="s", user="u")
    finally:
        provider.close()
    events = [json.loads(line) for line in gate_env["ledger"].read_text(encoding="utf-8").splitlines() if line.strip()]
    chat = [event for event in events if event.get("event") == "reserved" and event.get("kind") == "chat"]
    assert chat[-1]["reserve_cny"] == pytest.approx(BOUND)


def test_chat_provider_accepts_higher_ceiling_with_not_lower_reserve(gate_env) -> None:
    """更高保守 ceiling 可接受，但预留必须按实际值计算，不得低于官方下界。"""
    higher = CONSERVATIVE_CONTEXT_CEILING_TOKENS + 1
    expected = higher * INPUT_PRICE / 1_000_000.0 + 800 * OUTPUT_PRICE / 1_000_000.0
    ledger = BudgetLedger(
        gate_env["ledger"],
        gate_env["budget"],
        stage=STAGE,
        stage_limit_cny=5.0,
        max_requests=5,
    )
    config = RagConfig(
        provider_mode="live",
        chat_model="deepseek-flash",
        chat_base_url="https://api.deepseek.com",
        chat_api_key="k" * 10,
        chat_input_price_per_million_cny=INPUT_PRICE,
        chat_output_price_per_million_cny=OUTPUT_PRICE,
        chat_max_input_tokens=MAX_INPUT,
        chat_max_output_tokens=800,
        chat_reserve_profile=RESERVE_PROFILE_CONTEXT_CEILING,
        chat_context_ceiling_tokens=higher,
        max_output_tokens=800,
        max_request_cny=expected,
        max_retries=0,
        require_zero_retries=True,
    )
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "答案"}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 2},
            },
        )

    provider = DeepSeekChatProvider(config, budget=ledger, transport=httpx.MockTransport(handler))
    try:
        provider.complete(system="s", user="u")
    finally:
        provider.close()
    assert calls["n"] == 1
    events = [json.loads(line) for line in gate_env["ledger"].read_text(encoding="utf-8").splitlines() if line.strip()]
    chat = [event for event in events if event.get("event") == "reserved" and event.get("kind") == "chat"]
    assert chat[-1]["reserve_cny"] == pytest.approx(expected)
    assert chat[-1]["reserve_cny"] > BOUND


def test_bindings_accept_finite_float_prices_and_reject_nan() -> None:
    parsed = _parse_scope_bindings({"chat": {"input_price_per_million_cny": 2.0, "output_price_per_million_cny": 8.0}})
    assert parsed["chat"]["input_price_per_million_cny"] == 2.0
    with pytest.raises(LiveGateError):
        _parse_scope_bindings({"chat": {"input_price_per_million_cny": float("nan")}})
