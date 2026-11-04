"""S2-H-R3 定向：官方 chat profile 下界必须在两个产品入口 + 实际 rag-chat 构造生效。

覆盖经理要求：
- env 与 GO **同时错且相等**（不是只测不一致）时，build_gateway / resolve_rag_config 都拒绝；
- 6144 / 10000 / 20000 ceiling、输入 0.5、输出 < 8、输出 cap != 800；
- 未知 model/host、缺 bindings/profile、env↔GO 不一致；
- 关闭 token meter 不解除 policy；GO 省略 profile 不解除；
- 正向 1048576/2/8 仍为 2.103552 元，两个入口接受；更高 ceiling 不得降低预留。
全部 tmp_path 副本 + MockTransport；不是真实请求。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from mktkb import live_authorization as gate_module
from mktkb.config import Settings
from mktkb.live_authorization import LiveGateError
from mktkb.providers import build_gateway
from mktkb.providers.budgeted import ChatPricing
from mktkb.rag.config import RagConfig
from mktkb.rag.errors import BudgetPricingUnknown, RagConfigError
from mktkb.rag.providers import DeepSeekChatProvider
from mktkb.qa import resolve_rag_config

ROOT = Path(__file__).resolve().parents[3]
REAL_LEDGER = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
REAL_BUDGET = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "budget.json"
STAGE = "S2-H-R3-UNIT"
OFFICIAL_CEILING = 1_048_576
OFFICIAL_INPUT = 2.0
OFFICIAL_OUTPUT = 8.0
OFFICIAL_MAX_OUTPUT = 800
OFFICIAL_MAX_INPUT_GATE = 6144


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_go(path: Path, ledger: Path, *, bindings: dict | None) -> None:
    now = datetime.now(timezone.utc)
    scope = {
        "services": ["rag", "chat"],
        "stage_limits_cny": {STAGE: 5.0},
        "max_requests": 5,
        "max_request_cny": 2.11,
    }
    if bindings is not None:
        scope["bindings"] = bindings
    payload = {
        "document": "S2-LIVE-GO",
        "stage": STAGE,
        "authorization": "S2-H-R3-UNIT-MOCK-GO",
        "issued_by": "pytest",
        "nonce": "s2h-r3-unit-nonce-0123456789",
        "issued_utc": (now - timedelta(minutes=5)).isoformat(),
        "expires_utc": (now + timedelta(hours=1)).isoformat(),
        "budget_ledger_sha256": _sha(ledger),
        "scope": scope,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _bindings(
    *,
    ceiling: int = OFFICIAL_CEILING,
    input_price: float = OFFICIAL_INPUT,
    output_price: float = OFFICIAL_OUTPUT,
    max_output: int = OFFICIAL_MAX_OUTPUT,
    model: str = "deepseek-flash",
    host: str = "api.deepseek.com",
    thinking: str = "disabled",
    include_profile: bool = True,
) -> dict:
    chat = {
        "base_url_host": host,
        "model": model,
        "thinking": thinking,
        "max_input_tokens": OFFICIAL_MAX_INPUT_GATE,
        "max_output_tokens": max_output,
        "context_ceiling_tokens": ceiling,
        "input_price_per_million_cny": input_price,
        "output_price_per_million_cny": output_price,
    }
    if include_profile:
        chat["reserve_profile"] = "model_context_ceiling"
    return {
        "rag": {
            "base_url_host": "dashscope.aliyuncs.com",
            "embedding_model": "text-embedding-v4",
            "embedding_dimensions": 1024,
            "rerank_model": "gte-rerank-v2",
            "region": "beijing",
        },
        "chat": chat,
    }


def _fixture_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    bindings: dict | None,
    ceiling: int = OFFICIAL_CEILING,
    input_price: float = OFFICIAL_INPUT,
    output_price: float = OFFICIAL_OUTPUT,
    max_output: int = OFFICIAL_MAX_OUTPUT,
    model: str = "deepseek-flash",
    host: str = "api.deepseek.com",
    meter: str = "0",
) -> dict:
    ledger = tmp_path / "live-ledger.jsonl"
    shutil.copyfile(REAL_LEDGER, ledger)
    budget = json.loads(REAL_BUDGET.read_text(encoding="utf-8"))
    budget["stages"] = {**(budget.get("stages") or {}), STAGE: 5.0}
    budget["ledger"] = str(ledger)
    budget_path = tmp_path / "budget.json"
    budget_path.write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    go = tmp_path / "S2-LIVE-GO.json"
    _write_go(go, ledger, bindings=bindings)

    monkeypatch.setattr(gate_module, "SHARED_LEDGER_PATH", ledger)
    monkeypatch.setattr(gate_module, "SHARED_BUDGET_PATH", budget_path)
    monkeypatch.setattr(gate_module, "PRODUCT_GO_PATH", go)
    monkeypatch.setenv("MKTKB_LIVE_STAGE", STAGE)
    monkeypatch.setenv("MKTKB_RAG_STAGE_LIMIT_CNY", "5")
    monkeypatch.setenv("MKTKB_RAG_MAX_REQUESTS", "5")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "s2h-r3-mock-dashscope")
    monkeypatch.setenv("MKTKB_MODEL_BASE_URL", f"https://{host}/v1")
    monkeypatch.setenv("MKTKB_MODEL_NAME", model)
    monkeypatch.setenv("MKTKB_MODEL_API_KEY", "s2h-r3-mock-model")
    monkeypatch.setenv("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY", str(input_price))
    monkeypatch.setenv("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY", str(output_price))
    monkeypatch.setenv("MKTKB_MODEL_MAX_INPUT_TOKENS", str(OFFICIAL_MAX_INPUT_GATE))
    monkeypatch.setenv("MKTKB_MODEL_MAX_OUTPUT_TOKENS", str(max_output))
    monkeypatch.setenv("MKTKB_MODEL_CONTEXT_CEILING_TOKENS", str(ceiling))
    monkeypatch.setenv("MKTKB_MODEL_RESERVE_PROFILE", "model_context_ceiling")
    monkeypatch.setenv("MKTKB_REQUIRE_TOKEN_METER", meter)
    for key in ("MKTKB_RAG_BUDGET_LEDGER", "MKTKB_RAG_BUDGET_JSON", "MKTKB_RAG_STAGE", "MKTKB_TOKENIZER_PATH", "MKTKB_TOKENIZER_SHA256"):
        monkeypatch.delenv(key, raising=False)
    return {"ledger": ledger, "budget": budget_path, "go": go, "root": tmp_path}


def _settings(env: dict, *, model: str, host: str) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=env["root"] / "app",
        database_url=f"sqlite:///{(env['root'] / 'app' / 'a.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="s2h-r3-csrf-secret-0123456789",
        admin_password="UnitPass-1",
        employee_password="UnitPass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        model_base_url=f"https://{host}/v1",
        model_name=model,
        model_api_key="s2h-r3-mock-model",
        rag_qa_enabled=False,
    )


def _ledger_lines(path: Path) -> int:
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])


def _both_entries(env: dict, *, model: str, host: str):
    posts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        posts["count"] += 1
        return httpx.Response(200, json={})

    settings = _settings(env, model=model, host=host)
    transport = httpx.MockTransport(handler)
    with pytest.raises(ValueError):
        build_gateway(settings, transport=transport)
    with pytest.raises((ValueError, RagConfigError)):
        resolve_rag_config(
            data_dir=env["root"] / "app",
            provider_mode="live",
            page_size=10,
            top_k=8,
            business_date=None,
        )
    return posts["count"]


@pytest.mark.parametrize(
    ("ceiling", "input_price", "output_price", "max_output"),
    [
        (6144, OFFICIAL_INPUT, OFFICIAL_OUTPUT, OFFICIAL_MAX_OUTPUT),
        (10000, OFFICIAL_INPUT, OFFICIAL_OUTPUT, OFFICIAL_MAX_OUTPUT),
        (20000, OFFICIAL_INPUT, OFFICIAL_OUTPUT, OFFICIAL_MAX_OUTPUT),
        (OFFICIAL_CEILING, 0.5, OFFICIAL_OUTPUT, OFFICIAL_MAX_OUTPUT),
        (OFFICIAL_CEILING, OFFICIAL_INPUT, 7.5, OFFICIAL_MAX_OUTPUT),
        (OFFICIAL_CEILING, OFFICIAL_INPUT, OFFICIAL_OUTPUT, 900),
    ],
)
def test_env_and_go_both_small_and_equal_are_rejected_by_both_product_entries(
    tmp_path, monkeypatch, ceiling, input_price, output_price, max_output
) -> None:
    env = _fixture_env(
        tmp_path,
        monkeypatch,
        bindings=_bindings(
            ceiling=ceiling,
            input_price=input_price,
            output_price=output_price,
            max_output=max_output,
        ),
        ceiling=ceiling,
        input_price=input_price,
        output_price=output_price,
        max_output=max_output,
    )
    before = _ledger_lines(env["ledger"])
    assert _both_entries(env, model="deepseek-flash", host="api.deepseek.com") == 0
    assert _ledger_lines(env["ledger"]) == before


def test_chat_pricing_floor_rejects_lower_values() -> None:
    for kwargs in (
        {"context_ceiling_tokens": 6144},
        {"context_ceiling_tokens": 10000},
        {"context_ceiling_tokens": 20000},
        {"input_price_per_million_cny": 0.5},
        {"output_price_per_million_cny": 7.5},
        {"max_output_tokens": 900},
    ):
        values = {
            "input_price_per_million_cny": OFFICIAL_INPUT,
            "output_price_per_million_cny": OFFICIAL_OUTPUT,
            "max_input_tokens": OFFICIAL_MAX_INPUT_GATE,
            "max_output_tokens": OFFICIAL_MAX_OUTPUT,
            "reserve_profile": "model_context_ceiling",
            "context_ceiling_tokens": OFFICIAL_CEILING,
        }
        values.update(kwargs)
        with pytest.raises(LiveGateError):
            ChatPricing(**values)


@pytest.mark.parametrize(
    ("model", "host"),
    [
        ("deepseek-chat", "api.deepseek.com"),
        ("deepseek-flash", "mock.deepseek.invalid"),
    ],
)
def test_unknown_model_or_host_rejected_even_if_env_and_go_equal(tmp_path, monkeypatch, model, host) -> None:
    env = _fixture_env(
        tmp_path,
        monkeypatch,
        bindings=_bindings(model=model, host=host),
        model=model,
        host=host,
    )
    before = _ledger_lines(env["ledger"])
    assert _both_entries(env, model=model, host=host) == 0
    assert _ledger_lines(env["ledger"]) == before


def test_meter_off_and_go_profile_omitted_do_not_lift_policy(tmp_path, monkeypatch) -> None:
    env = _fixture_env(
        tmp_path,
        monkeypatch,
        bindings=_bindings(ceiling=6144, include_profile=False),
        ceiling=6144,
        meter="0",
    )
    before = _ledger_lines(env["ledger"])
    assert _both_entries(env, model="deepseek-flash", host="api.deepseek.com") == 0
    assert _ledger_lines(env["ledger"]) == before


def test_env_go_mismatch_still_rejected_by_both_entries(tmp_path, monkeypatch) -> None:
    env = _fixture_env(
        tmp_path,
        monkeypatch,
        bindings=_bindings(ceiling=10000),
        ceiling=OFFICIAL_CEILING,
    )
    before = _ledger_lines(env["ledger"])
    assert _both_entries(env, model="deepseek-flash", host="api.deepseek.com") == 0
    assert _ledger_lines(env["ledger"]) == before


def test_official_profile_accepted_by_both_entries_and_worst_case_is_2103552(tmp_path, monkeypatch) -> None:
    env = _fixture_env(
        tmp_path,
        monkeypatch,
        bindings=_bindings(),
    )
    config, _budget = resolve_rag_config(
        data_dir=env["root"] / "app",
        provider_mode="live",
        page_size=10,
        top_k=8,
        business_date=None,
    )
    assert config.chat_context_ceiling_tokens == OFFICIAL_CEILING
    assert config.chat_input_price_per_million_cny == OFFICIAL_INPUT
    assert config.chat_output_price_per_million_cny == OFFICIAL_OUTPUT
    posts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        posts["count"] += 1
        return httpx.Response(200, json={})

    gateway = build_gateway(_settings(env, model="deepseek-flash", host="api.deepseek.com"), transport=httpx.MockTransport(handler))
    assert gateway is not None
    assert gateway.stats()["request_bound_cny"] == pytest.approx(2.103552)
    assert ChatPricing.from_env().worst_case_cny() == pytest.approx(2.103552)
    assert posts["count"] == 0


def test_rag_chat_construction_rejects_small_profile_before_transport(tmp_path) -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        calls["n"] += 1
        return httpx.Response(200, json={})

    config = RagConfig(
        provider_mode="live",
        chat_model="deepseek-flash",
        chat_base_url="https://api.deepseek.com",
        chat_api_key="k" * 10,
        chat_input_price_per_million_cny=0.5,
        chat_output_price_per_million_cny=OFFICIAL_OUTPUT,
        chat_max_input_tokens=OFFICIAL_MAX_INPUT_GATE,
        chat_max_output_tokens=OFFICIAL_MAX_OUTPUT,
        chat_reserve_profile="model_context_ceiling",
        chat_context_ceiling_tokens=6144,
        max_output_tokens=OFFICIAL_MAX_OUTPUT,
        max_request_cny=2.11,
        max_retries=0,
        require_zero_retries=True,
    )
    with pytest.raises(BudgetPricingUnknown):
        DeepSeekChatProvider(config, transport=httpx.MockTransport(handler), require_budget=False)
    assert calls["n"] == 0


def test_rag_config_requires_profile_for_live_chat() -> None:
    with pytest.raises(RagConfigError, match="model_context_ceiling"):
        RagConfig(
            provider_mode="live",
            embedding_api_key="k" * 10,
            rerank_api_key="k" * 10,
            chat_model="deepseek-flash",
            chat_base_url="https://api.deepseek.com",
            chat_api_key="k" * 10,
            chat_input_price_per_million_cny=OFFICIAL_INPUT,
            chat_output_price_per_million_cny=OFFICIAL_OUTPUT,
            chat_max_input_tokens=OFFICIAL_MAX_INPUT_GATE,
            chat_max_output_tokens=OFFICIAL_MAX_OUTPUT,
        ).require_live_credentials()
