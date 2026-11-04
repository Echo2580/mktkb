"""S2-D 定向回归：预留成功后、真实 POST 前的第二次授权/预算复核。

只覆盖本轮缺口窗口：reserve 已成功、post 尚未发出时 GO 过期/服务撤回/单请求上界收窄/
阶段预算收窄/累计请求上限收窄，必须零 POST、零 transport、错误可归因、已有预留不清账。
全部使用 tmp_path 副本账本/预算/GO、假凭据、假价格与 MockTransport；不发真实请求。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from mktkb import live_authorization as gate_module
from mktkb.live_authorization import resolve_live_gate
from mktkb.rag.budget import BudgetLedger
from mktkb.rag.config import RagConfig

STAGE = "S2-D-UNIT"
HISTORY_CNY = 0.03
# 隔离预算的总上限：测试内用同值环境变量，自洽即可，不再跟随仓库真实预算（20 元）。
PROJECT_TOTAL_LIMIT_CNY = 10.0
PRICING_ENV = {
    "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com/v1",
    "MKTKB_MODEL_NAME": "deepseek-flash",
    "MKTKB_MODEL_API_KEY": "s2d-unit-mock-key",
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
        "authorization": "S2-D-UNIT-MOCK-GO",
        "issued_by": "pytest",
        "nonce": "s2d-unit-nonce-0123456789",
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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_ledger(path: Path, *, historical: float = HISTORY_CNY) -> None:
    """自建隔离账本：只含一行 historical_import，不复制仓库共享账本。

    共享账本会随真实阶段增长（当前 83 笔预留），复制它会让“预留/结果计数”
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
def guard_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    ledger = tmp_path / "live-ledger.jsonl"
    _write_ledger(ledger)
    budget = tmp_path / "budget.json"
    _write_budget(budget, ledger)
    go = tmp_path / "S2-LIVE-GO.json"
    _write_go(go, ledger)
    monkeypatch.setattr(gate_module, "SHARED_LEDGER_PATH", ledger)
    monkeypatch.setattr(gate_module, "SHARED_BUDGET_PATH", budget)
    monkeypatch.setattr(gate_module, "PRODUCT_GO_PATH", go)
    # 三件套一致：budget.limit_cny == MKTKB_PROJECT_TOTAL_LIMIT_CNY == 10.0。
    monkeypatch.setenv("MKTKB_PROJECT_TOTAL_LIMIT_CNY", str(PROJECT_TOTAL_LIMIT_CNY))
    monkeypatch.setenv("MKTKB_LIVE_STAGE", STAGE)
    monkeypatch.setenv("MKTKB_RAG_STAGE_LIMIT_CNY", "5.0")
    monkeypatch.setenv("MKTKB_RAG_MAX_REQUESTS", "5")
    for key, value in PRICING_ENV.items():
        monkeypatch.setenv(key, value)
    for key in ("MKTKB_RAG_BUDGET_LEDGER", "MKTKB_RAG_BUDGET_JSON", "MKTKB_RAG_STAGE"):
        monkeypatch.delenv(key, raising=False)
    return {"ledger": ledger, "budget": budget, "go": go, "root": tmp_path}


def _resolve(**overrides):
    params = {
        "stage": STAGE,
        "service": "chat",
        "requested_stage_limit_cny": 5.0,
        "requested_max_requests": 3,
        "request_bound_cny": 2.103552,
    }
    params.update(overrides)
    return resolve_live_gate(**params)


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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
                fields={"门店": "北辰店", "联系电话": "0571-8800-0011"},
            ),
        ),
    )


def _mock_transport(posts: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        posts["count"] += 1
        posts.setdefault("bodies", []).append(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": f"mock-s2d-{posts['count']}",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": "北辰店的电话：0571-8800-0011",
                                    "source_ids": ["11111111-1111-1111-1111-111111111111"],
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60},
            },
        )

    return httpx.MockTransport(handler)


def _gateway(gate, transport, root: Path):
    from mktkb.config import Settings
    from mktkb.providers import build_gateway

    settings = Settings(
        _env_file=None,
        data_dir=root / "app",
        database_url=f"sqlite:///{(root / 'app' / 'c.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="s2d-unit-csrf-secret-0123456789",
        admin_password="UnitPass-1",
        employee_password="UnitPass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        model_base_url=PRICING_ENV["MKTKB_MODEL_BASE_URL"],
        model_name=PRICING_ENV["MKTKB_MODEL_NAME"],
        model_api_key=PRICING_ENV["MKTKB_MODEL_API_KEY"],
        rag_qa_enabled=False,
    )
    return build_gateway(settings, gate=gate, transport=transport)


def _flip_after_client_created(monkeypatch: pytest.MonkeyPatch, flip) -> None:
    """把变化注入到“client 已创建/锁等待 await 完成之后、真实 POST 之前”。"""
    from mktkb.providers.deepseek import DeepSeekClient

    original = DeepSeekClient._client_or_create

    async def wrapper(self):  # noqa: ANN001
        client = await original(self)
        flip()
        return client

    monkeypatch.setattr(DeepSeekClient, "_client_or_create", wrapper)


def _assert_refused_reservation(ledger_path: Path, gateway) -> dict:
    """预留仍保留原 id、结果与其关联、错误码可归因、累计占用保存到下个实例。"""
    events = _events(ledger_path)
    reserved = [event for event in events if event["event"] == "reserved"][-1]
    linked = [
        event
        for event in events
        if event["event"] == "result"
        and event["reservation_id"] == reserved["reservation_id"]
    ]
    assert len(linked) == 1
    assert linked[0]["error_code"] == "MODEL_POST_SEND_AUTH_DENIED"
    assert linked[0]["conservative_charge_cny"] >= reserved["reserve_cny"] - 1e-12
    return reserved


def test_chat_post_boundary_refuses_when_go_expires_after_reserve(guard_env, monkeypatch):
    from mktkb.providers.budgeted import ModelPostSendDenied

    gate = _resolve(requested_max_requests=5)
    posts = {"count": 0}
    gateway = _gateway(gate, _mock_transport(posts), guard_env["root"])
    _flip_after_client_created(
        monkeypatch,
        lambda: _write_go(
            guard_env["go"],
            guard_env["ledger"],
            expires_utc=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        ),
    )
    ledger = gate.ledger()
    before = ledger.summary().as_dict()
    with pytest.raises(ModelPostSendDenied):
        asyncio.run(gateway.complete(_chat_request(), timeout_seconds=5.0))
    after = ledger.summary().as_dict()
    counters = gateway.stats()["counters"]
    bound = gateway.stats()["request_bound_cny"]

    assert posts["count"] == 0  # 零 transport
    assert counters["reserved"] == 1 and counters["send_attempts"] == 0
    assert counters["pre_send_refused"] == 1
    assert after["reservation_count"] == before["reservation_count"] + 1
    assert after["result_count"] == before["result_count"] + 1
    assert after["accounted_cny"] - before["accounted_cny"] == pytest.approx(bound)
    _assert_refused_reservation(guard_env["ledger"], gateway)
    # 重启（新账本实例/新网关）后累计占用不丢，也不会重记一次。
    restarted = gate.ledger().summary().as_dict()
    assert restarted["accounted_cny"] == after["accounted_cny"]


def test_chat_post_boundary_refuses_when_budget_narrows_after_reserve(guard_env, monkeypatch):
    from mktkb.providers.budgeted import ModelPostSendDenied

    gate = _resolve(requested_max_requests=5)
    posts = {"count": 0}
    gateway = _gateway(gate, _mock_transport(posts), guard_env["root"])
    _flip_after_client_created(
        monkeypatch,
        lambda: _write_budget(guard_env["budget"], guard_env["ledger"], stage_limit=0.00001),
    )
    with pytest.raises(ModelPostSendDenied):
        asyncio.run(gateway.complete(_chat_request(), timeout_seconds=5.0))
    assert posts["count"] == 0
    assert gateway.stats()["counters"]["pre_send_refused"] == 1
    _assert_refused_reservation(guard_env["ledger"], gateway)


def test_chat_single_request_limit_one_is_not_double_counted(guard_env):
    gate = _resolve(requested_max_requests=1)
    posts = {"count": 0}
    gateway = _gateway(gate, _mock_transport(posts), guard_env["root"])
    output = asyncio.run(gateway.complete(_chat_request(), timeout_seconds=5.0))
    counters = gateway.stats()["counters"]

    assert output.text.startswith("北辰店的电话")
    assert posts["count"] == 1
    assert counters["reserved"] == 1 and counters["send_attempts"] == 1
    assert counters["pre_send_refused"] == 0
    summary = gate.ledger().summary().as_dict()
    assert summary["reservation_count"] == 1 and summary["result_count"] == 1

    # 上限 1 已用完：第 2 次在预留前就拒绝，仍零发送。
    # 预算/授权拒绝与“供应商不可用”分码：这里是 MODEL_BUDGET_REFUSED（不是 MODEL_UNAVAILABLE）。
    from mktkb.providers.types import ModelBudgetRefused

    with pytest.raises(ModelBudgetRefused):
        asyncio.run(gateway.complete(_chat_request(), timeout_seconds=5.0))
    assert posts["count"] == 1
    assert gateway.stats()["counters"]["refused"] == 1


def test_chat_post_boundary_refuses_when_go_request_limit_narrows_after_reserve(guard_env, monkeypatch):
    from mktkb.providers.budgeted import ModelPostSendDenied

    gate = _resolve(requested_max_requests=3)
    posts = {"count": 0}
    gateway = _gateway(gate, _mock_transport(posts), guard_env["root"])
    asyncio.run(gateway.complete(_chat_request(), timeout_seconds=5.0))
    assert posts["count"] == 1

    # 预留时 GO 仍允许 3 次；预留成功后收窄到 1 次 → 已计入的 2 次 > 1，拒绝发送。
    _flip_after_client_created(
        monkeypatch,
        lambda: _write_go(guard_env["go"], guard_env["ledger"], scope={"max_requests": 1}),
    )
    with pytest.raises(ModelPostSendDenied):
        asyncio.run(gateway.complete(_chat_request(), timeout_seconds=5.0))
    assert posts["count"] == 1
    counters = gateway.stats()["counters"]
    assert counters["reserved"] == 2 and counters["send_attempts"] == 1
    assert counters["pre_send_refused"] == 1
    _assert_refused_reservation(guard_env["ledger"], gateway)


def _rag_config(**overrides) -> RagConfig:
    values = dict(
        provider_mode="offline",
        embedding_api_key="sk-s2d-mock-never-real",
        embedding_base_url="https://example.invalid",
        embedding_timeout_seconds=1.0,
        rerank_api_key="sk-s2d-mock-never-real",
        rerank_base_url="https://example.invalid",
        rerank_timeout_seconds=1.0,
        max_retries=0,
        retry_base_seconds=0.001,
    )
    values.update(overrides)
    return RagConfig(**values)


def _flip_after_reserve(ledger: BudgetLedger, flip) -> None:
    original = ledger.reserve

    def reserve(**kwargs):  # noqa: ANN003
        reservation = original(**kwargs)
        flip()
        return reservation

    ledger.reserve = reserve  # type: ignore[method-assign]


def test_rag_embedding_refuses_after_reserve_when_go_expires(guard_env):
    from mktkb.rag.errors import EmbeddingUnavailable
    from mktkb.rag.providers import BailianEmbeddingProvider, post_counters, reset_post_counters

    gate = _resolve(service="rag", requested_max_requests=5, requested_stage_limit_cny=0.4)
    ledger = gate.ledger()
    posts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        posts["count"] += 1
        raise AssertionError("refused request must not reach transport")

    reset_post_counters()
    _flip_after_reserve(
        ledger,
        lambda: _write_go(
            guard_env["go"],
            guard_env["ledger"],
            expires_utc=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        ),
    )
    provider = BailianEmbeddingProvider(
        _rag_config(), budget=ledger, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(EmbeddingUnavailable) as excinfo:
            provider.embed(["北辰店的电话是多少？"])
    finally:
        provider.close()

    assert "发送前授权/预算复核拒绝" in str(excinfo.value)
    assert posts["count"] == 0
    assert post_counters()["attempts"].get("embedding", 0) == 0
    summary = ledger.summary().as_dict()
    assert summary["reservation_count"] == 1 and summary["result_count"] == 1
    events = _events(guard_env["ledger"])
    reserved = [event for event in events if event["event"] == "reserved"][-1]
    result = [event for event in events if event["event"] == "result"][-1]
    assert result["reservation_id"] == reserved["reservation_id"]
    assert result["error_code"] == "EMBEDDING_POST_AUTH_DENIED"
    assert summary["accounted_cny"] >= reserved["reserve_cny"] - 1e-12


def test_rag_rerank_refuses_after_reserve_when_go_service_withdrawn(guard_env):
    from mktkb.rag.errors import RerankUnavailable
    from mktkb.rag.providers import BailianRerankProvider, post_counters, reset_post_counters

    gate = _resolve(service="rag", requested_max_requests=5, requested_stage_limit_cny=0.4)
    ledger = gate.ledger()
    posts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        posts["count"] += 1
        raise AssertionError("refused request must not reach transport")

    reset_post_counters()
    _flip_after_reserve(
        ledger,
        lambda: _write_go(guard_env["go"], guard_env["ledger"], scope={"services": ["chat"]}),
    )
    provider = BailianRerankProvider(
        _rag_config(), budget=ledger, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(RerankUnavailable) as excinfo:
            provider.rerank("北辰店", ["北辰店 骆青 0571-8800-0011"])
    finally:
        provider.close()

    assert "发送前授权/预算复核拒绝" in str(excinfo.value)
    assert posts["count"] == 0
    assert post_counters()["attempts"].get("rerank", 0) == 0
    summary = ledger.summary().as_dict()
    assert summary["reservation_count"] == 1 and summary["result_count"] == 1
    result = [event for event in _events(guard_env["ledger"]) if event["event"] == "result"][-1]
    assert result["error_code"] == "RERANK_POST_AUTH_DENIED"


def test_legacy_ledger_without_post_guard_keeps_previous_behavior(guard_env):
    """未注入 post_reserve_guard 的旧调用者（S1/直连）不新增复核，也不报错。"""
    ledger = BudgetLedger(
        guard_env["ledger"],
        guard_env["budget"],
        stage=STAGE,
        stage_limit_cny=0.3,
        max_requests=3,
    )
    reservation = ledger.reserve(
        kind="chat", provider="mock", model="m", max_cny=0.001, request_sha256="a" * 64
    )
    _write_go(
        guard_env["go"],
        guard_env["ledger"],
        expires_utc=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    )
    ledger.recheck_reservation(reservation)  # 没有 guard：空操作，不抛
    assert ledger.summary().as_dict()["reservation_count"] == 1
