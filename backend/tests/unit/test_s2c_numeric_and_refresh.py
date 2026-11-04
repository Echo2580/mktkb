"""S2-C 定向回归：有限数值闸门、请求期授权/预算刷新、chat 输出上限。

只覆盖本轮实际发现的边界；账本/预算/GO 全部是 tmp_path 副本，chat 走 MockTransport。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from mktkb import live_authorization as gate_module
from mktkb.live_authorization import (
    LiveAuthorization,
    LiveGateError,
    resolve_live_gate,
)
from mktkb.providers.budgeted import ChatPricing
from mktkb.rag.budget import BudgetExceeded, BudgetLedger, BudgetLedgerInvalid, RequestLimitExceeded

STAGE = "S2-C-UNIT"
HISTORY_CNY = 0.03
# 隔离预算的总上限：测试内用同值环境变量，自洽即可，不再跟随仓库真实预算（20 元）。
PROJECT_TOTAL_LIMIT_CNY = 10.0
PRICING_ENV = {
    "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com/v1",
    "MKTKB_MODEL_NAME": "deepseek-flash",
    "MKTKB_MODEL_API_KEY": "s2c-unit-mock-key",
    "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY": "2",
    "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY": "8",
    "MKTKB_MODEL_MAX_INPUT_TOKENS": "6144",
    "MKTKB_MODEL_MAX_OUTPUT_TOKENS": "800",
    "MKTKB_MODEL_CONTEXT_CEILING_TOKENS": "1048576",
    "MKTKB_MODEL_RESERVE_PROFILE": "model_context_ceiling",
}


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_go(path: Path, ledger: Path, **overrides) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "document": "S2-LIVE-GO",
        "stage": STAGE,
        "authorization": "S2-C-UNIT-MOCK-GO",
        "issued_by": "pytest",
        "nonce": "s2c-unit-nonce-0123456789",
        "issued_utc": (now - timedelta(minutes=5)).isoformat(),
        "expires_utc": (now + timedelta(hours=1)).isoformat(),
        "budget_ledger_sha256": _sha(ledger),
        "scope": {
            "services": ["rag", "chat"],
            "stage_limits_cny": {STAGE: 5.0},
            "max_requests": 5,
            "max_request_cny": 2.11,
            "bindings": {
                "rag": {
                    "base_url_host": "mock.dashscope.invalid",
                    "embedding_model": "text-embedding-v4",
                    "embedding_dimensions": 1024,
                    "rerank_model": "gte-rerank-v2",
                    "region": "unknown",
                },
                "chat": {
                    "base_url_host": "api.deepseek.com",
                    "model": "deepseek-flash",
                    "thinking": "disabled",
                    "max_input_tokens": 6144,
                    "max_output_tokens": 800,
                    "reserve_profile": "model_context_ceiling",
                    "context_ceiling_tokens": 1048576,
                    "input_price_per_million_cny": 2.0,
                    "output_price_per_million_cny": 8.0,
                },
            },
        },
    }
    for key, value in overrides.items():
        if key == "scope":
            payload["scope"] = {**payload["scope"], **value}
        else:
            payload[key] = value
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=True) + "\n", encoding="utf-8")


def _write_ledger(path: Path, *, historical: float = HISTORY_CNY) -> None:
    """自建隔离账本：只含一行 historical_import，不复制仓库共享账本。

    共享账本会随真实阶段增长（当前 83 笔预留），复制它会让“累计请求上限/历史占用”
    类断言随真实用量漂移。
    """
    path.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": historical}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_budget(path: Path, ledger: Path, *, stage: str, stage_limit: float) -> None:
    """自建隔离预算：limit_cny 与测试环境变量同值，stages 只声明本用例阶段。"""
    budget = {
        "limit_cny": PROJECT_TOTAL_LIMIT_CNY,
        "historical_conservative_accounted_cny": HISTORY_CNY,
        "stages": {stage: stage_limit},
        "ledger": str(ledger),
    }
    path.write_text(json.dumps(budget, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def gate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    ledger = tmp_path / "live-ledger.jsonl"
    _write_ledger(ledger)
    budget_path = tmp_path / "budget.json"
    _write_budget(budget_path, ledger, stage=STAGE, stage_limit=5.0)
    go = tmp_path / "S2-LIVE-GO.json"
    _write_go(go, ledger)
    monkeypatch.setattr(gate_module, "SHARED_LEDGER_PATH", ledger)
    monkeypatch.setattr(gate_module, "SHARED_BUDGET_PATH", budget_path)
    monkeypatch.setattr(gate_module, "PRODUCT_GO_PATH", go)
    # 三件套一致：budget.limit_cny == MKTKB_PROJECT_TOTAL_LIMIT_CNY == 10.0。
    monkeypatch.setenv("MKTKB_PROJECT_TOTAL_LIMIT_CNY", str(PROJECT_TOTAL_LIMIT_CNY))
    for key in (
        "MKTKB_RAG_BUDGET_LEDGER",
        "MKTKB_RAG_BUDGET_JSON",
        "MKTKB_RAG_STAGE",
        "MKTKB_LIVE_STAGE",
        "MKTKB_RAG_STAGE_LIMIT_CNY",
        "MKTKB_RAG_MAX_REQUESTS",
    ):
        monkeypatch.delenv(key, raising=False)
    return {"ledger": ledger, "budget": budget_path, "go": go, "root": tmp_path}


def _resolve(**overrides):
    params = {
        "stage": STAGE,
        "service": "chat",
        "requested_stage_limit_cny": 0.3,
        "requested_max_requests": 3,
        "request_bound_cny": 0.01,
    }
    params.update(overrides)
    return resolve_live_gate(**params)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_go_stage_and_request_limits_reject_non_finite(gate_env, bad):
    _write_go(gate_env["go"], gate_env["ledger"], scope={
        "stage_limits_cny": {STAGE: bad},
        "max_requests": 3,
        "max_request_cny": 0.2,
    })
    with pytest.raises(LiveGateError):
        _resolve()
    _write_go(gate_env["go"], gate_env["ledger"], scope={
        "stage_limits_cny": {STAGE: 0.5},
        "max_requests": 3,
        "max_request_cny": bad,
    })
    with pytest.raises(LiveGateError):
        _resolve()
    _write_go(gate_env["go"], gate_env["ledger"])


def test_go_infinity_cannot_allow_9999_request_bound(gate_env):
    _write_go(gate_env["go"], gate_env["ledger"], scope={"max_request_cny": float("inf")})
    with pytest.raises(LiveGateError):
        _resolve(request_bound_cny=9999)
    _write_go(gate_env["go"], gate_env["ledger"])


def test_budget_non_finite_and_direct_ledger_values_are_rejected(gate_env, tmp_path: Path):
    for text in (
        '{"limit_cny": NaN, "stages": {"%s": 0.5}}' % STAGE,
        '{"limit_cny": Infinity, "stages": {"%s": 0.5}}' % STAGE,
        '{"limit_cny": 10.0, "stages": {"%s": NaN}}' % STAGE,
        '{"limit_cny": 10.0, "stages": {"%s": "NaN"}}' % STAGE,
    ):
        gate_env["budget"].write_text(text + "\n", encoding="utf-8")
        with pytest.raises(LiveGateError):
            _resolve()
    gate_env["budget"].write_text(
        json.dumps(
            {"limit_cny": 10.0, "historical_conservative_accounted_cny": 0.03, "stages": {STAGE: 0.5}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(BudgetLedgerInvalid):
        BudgetLedger(gate_env["ledger"], gate_env["budget"], stage=STAGE, stage_limit_cny=float("nan"), max_requests=3)
    ledger = BudgetLedger(gate_env["ledger"], gate_env["budget"], stage=STAGE, stage_limit_cny=0.3, max_requests=3)
    with pytest.raises(BudgetLedgerInvalid):
        ledger.reserve(kind="chat", provider="mock", model="m", max_cny=float("inf"), request_sha256="a" * 64)

    bad_ledger = tmp_path / "bad-ledger.jsonl"
    bad_ledger.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": 0.03}) + "\n"
        + json.dumps({"event": "reserved", "reservation_id": "r", "stage": STAGE, "reserve_cny": float("nan")}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(BudgetLedgerInvalid):
        BudgetLedger(bad_ledger, gate_env["budget"], stage=STAGE, stage_limit_cny=0.3, max_requests=3).summary()


def test_direct_authorization_and_pricing_reject_non_finite():
    now = datetime.now(timezone.utc)
    with pytest.raises(LiveGateError):
        LiveAuthorization(
            stage=STAGE,
            service="chat",
            issued_by="pytest",
            nonce="n" * 16,
            issued_utc=now,
            expires_utc=now + timedelta(hours=1),
            stage_limit_cny=float("nan"),
            max_requests=1,
            max_request_cny=0.1,
            ledger_sha256="0" * 64,
            source_path="mock",
        )
    with pytest.raises(LiveGateError):
        ChatPricing(
            input_price_per_million_cny=float("inf"),
            output_price_per_million_cny=1.0,
            max_input_tokens=10,
            max_output_tokens=800,
            reserve_profile="model_context_ceiling",
            context_ceiling_tokens=2000,
        )


def test_long_lived_gate_refreshes_go_and_budget_before_each_reserve(gate_env):
    gate = _resolve(requested_max_requests=100, requested_stage_limit_cny=0.4)
    ledger = gate.ledger()
    first = ledger.reserve(kind="chat", provider="mock", model="m", max_cny=0.01, request_sha256="a" * 64)
    ledger.settle(first, status="succeeded")

    _write_go(gate_env["go"], gate_env["ledger"], expires_utc=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    before = len(gate_env["ledger"].read_text(encoding="utf-8").splitlines())
    with pytest.raises(BudgetLedgerInvalid):
        ledger.reserve(kind="chat", provider="mock", model="m", max_cny=0.01, request_sha256="b" * 64)
    assert len(gate_env["ledger"].read_text(encoding="utf-8").splitlines()) == before

    _write_go(gate_env["go"], gate_env["ledger"], scope={"services": ["rag"]})
    with pytest.raises(BudgetLedgerInvalid):
        ledger.reserve(kind="chat", provider="mock", model="m", max_cny=0.01, request_sha256="c" * 64)
    _write_go(gate_env["go"], gate_env["ledger"])

    budget = json.loads(gate_env["budget"].read_text(encoding="utf-8"))
    budget["stages"] = {STAGE: 0.001}
    gate_env["budget"].write_text(json.dumps(budget, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(BudgetExceeded):
        ledger.reserve(kind="chat", provider="mock", model="m", max_cny=0.01, request_sha256="d" * 64)

    budget["stages"] = {STAGE: 0.5}
    gate_env["budget"].write_text(json.dumps(budget, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_go(gate_env["go"], gate_env["ledger"], scope={"max_requests": 1})
    with pytest.raises(RequestLimitExceeded):
        ledger.reserve(kind="chat", provider="mock", model="m", max_cny=0.001, request_sha256="e" * 64)


def _chat_request():
    from mktkb.providers.types import CompletionInput, DialogueContext, ModelEvidence

    return CompletionInput(
        purpose="answer",
        question="北辰店的电话是多少？",
        context=DialogueContext(questions=(), entities={"store": "北辰店"}),
        evidence=(
            ModelEvidence(
                source_id="11111111-1111-1111-1111-111111111111",
                text="北辰店 骆青 0571-8800-0011",
                fields={"门店": "北辰店", "联系人": "骆青", "联系电话": "0571-8800-0011", "地址": "北辰路11号", "合作状态": "合作中"},
            ),
        ),
    )


def test_chat_payload_carries_max_tokens_and_overage_is_conservatively_accounted(gate_env, monkeypatch):
    from mktkb.config import Settings
    from mktkb.providers import build_gateway

    for key, value in PRICING_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MKTKB_RAG_STAGE_LIMIT_CNY", "0.3")
    monkeypatch.setenv("MKTKB_RAG_MAX_REQUESTS", "5")
    settings = Settings(
        _env_file=None,
        data_dir=gate_env["root"] / "app",
        database_url=f"sqlite:///{(gate_env['root'] / 'app' / 'c.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="s2c-unit-csrf-secret-0123456789",
        admin_password="UnitPass-1",
        employee_password="UnitPass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        model_base_url=PRICING_ENV["MKTKB_MODEL_BASE_URL"],
        model_name=PRICING_ENV["MKTKB_MODEL_NAME"],
        model_api_key=PRICING_ENV["MKTKB_MODEL_API_KEY"],
        rag_qa_enabled=False,
    )
    gate = _resolve(requested_max_requests=5, requested_stage_limit_cny=5.0)
    posts = {"count": 0, "body": None}

    def handler(request: httpx.Request) -> httpx.Response:
        posts["count"] += 1
        body = json.loads(request.content.decode("utf-8"))
        posts["body"] = body
        user = json.loads(body["messages"][1]["content"])
        if "evidence" not in user:
            content = json.dumps({"terms": ["北辰店"]}, ensure_ascii=False)
        else:
            content = json.dumps(
                {"answer": "北辰店的电话：0571-8800-0011", "source_ids": ["11111111-1111-1111-1111-111111111111"]},
                ensure_ascii=False,
            )
        return httpx.Response(
            200,
            json={
                "id": "mock-c1",
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 300000, "total_tokens": 300040},
            },
        )

    gateway = build_gateway(settings, gate=gate, transport=httpx.MockTransport(handler))
    before = gate.ledger().summary().as_dict()
    asyncio.run(gateway.complete(_chat_request(), timeout_seconds=5.0))
    after = gate.ledger().summary().as_dict()
    assert posts["count"] == 1
    assert posts["body"]["max_tokens"] == 800
    assert posts["body"]["max_tokens"] <= gateway.stats()["pricing"]["max_output_tokens"]
    assert after["accounted_cny"] - before["accounted_cny"] > gateway.stats()["request_bound_cny"]
    assert gateway.stats()["counters"]["send_attempts"] == 1
