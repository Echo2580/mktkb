"""S2-B：产品真实调用闸门（GAP-1/1b/2/3）单元回归，全程隔离副本 + MockTransport。

不读 `.env`、不打开正式业务库、不发真实网络：账本/预算/GO 都是 tmp_path 副本，
``mktkb.live_authorization`` 的固定路径常量在本测试内被 monkeypatch 到副本。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from mktkb import live_authorization as gate_module
from mktkb.live_authorization import LiveGateError, resolve_live_gate
from mktkb.rag.budget import RequestLimitExceeded
from mktkb.rag.config import RagConfig
from mktkb.rag.providers import BailianEmbeddingProvider

HISTORY_CNY = 0.03
# 隔离预算的总上限：测试内用同值环境变量，自洽即可，不再跟随仓库真实预算（20 元）。
PROJECT_TOTAL_LIMIT_CNY = 10.0

CHAT_PRICING_ENV = {
    "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com/v1",
    "MKTKB_MODEL_NAME": "deepseek-flash",
    "MKTKB_MODEL_API_KEY": "s2b-mock-model-key",
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


def _write_go(path: Path, *, ledger_hash: str, **overrides) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "document": "S2-LIVE-GO",
        "stage": "S2-DEV",
        "authorization": "UNIT-TEST-MOCK-GO",
        "issued_by": "pytest",
        "nonce": "unit-test-nonce-0123456789",
        "issued_utc": (now - timedelta(minutes=5)).isoformat(),
        "expires_utc": (now + timedelta(hours=1)).isoformat(),
        "budget_ledger_sha256": ledger_hash,
        "scope": {
            "services": ["rag", "chat"],
            "stage_limits_cny": {"S2-DEV": 5.0},
            "max_requests": 5,
            "max_request_cny": 2.11,
            "bindings": {
                "rag": {
                    "base_url_host": "dashscope.aliyuncs.com",
                    "embedding_model": "text-embedding-v4",
                    "embedding_dimensions": 1024,
                    "rerank_model": "gte-rerank-v2",
                    "region": "beijing",
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
            # 合并而不是整段替换：调用方只改一个字段时，其余 scope（services/bindings）保持不变。
            payload["scope"] = {**payload["scope"], **value}
        else:
            payload[key] = value
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_ledger(path: Path, *, historical: float = HISTORY_CNY) -> None:
    """自建隔离账本：只含一行 historical_import，不复制仓库共享账本。

    仓库共享账本会随真实阶段增长（当前 83 笔预留 / 14.32 元），复制它会让
    “历史占用 / 余额 / 累计请求上限”类断言随真实用量漂移。
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
    _write_budget(budget_path, ledger, stage="S2-DEV", stage_limit=5.0)
    go = tmp_path / "S2-LIVE-GO.json"
    _write_go(go, ledger_hash=_sha(ledger))
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


def _resolve(**kwargs):
    params = {
        "stage": "S2-DEV",
        "service": "rag",
        "requested_stage_limit_cny": 0.3,
        "requested_max_requests": 3,
        "request_bound_cny": 0.1,
    }
    params.update(kwargs)
    return resolve_live_gate(**params)


def test_gate_uses_shared_ledger_history_and_narrows_to_go(gate_env):
    gate = _resolve()
    summary = gate.ledger().summary().as_dict()
    assert summary["total_limit_cny"] == 10.0
    assert summary["historical_conservative_cny"] == 0.03
    assert summary["remaining_cny"] == pytest.approx(9.97)
    # 环境请求 0.3/3 只能收窄 GO 的 5.0/5
    assert gate.stage_limit_cny == pytest.approx(0.3)
    assert gate.max_requests == 3
    assert gate.max_request_cny == pytest.approx(2.11)


def test_env_path_cannot_redirect_the_gate(gate_env, monkeypatch):
    """闸门本身从固定常量取路径：环境变量指到别的账本也不会被采纳。"""
    empty = gate_env["root"] / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    outside = Path(tempfile.mkdtemp(prefix="s2b-outside-")) / "ledger.jsonl"
    shutil.copyfile(gate_env["ledger"], outside)
    monkeypatch.setenv("MKTKB_RAG_BUDGET_LEDGER", str(empty))
    monkeypatch.setenv("MKTKB_RAG_BUDGET_JSON", str(outside))
    gate = _resolve()
    assert gate.ledger_path == gate_env["ledger"]
    assert gate.budget_path == gate_env["budget"]


def _live_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    env = {
        "DASHSCOPE_API_KEY": "unit-mock-dashscope",
        **CHAT_PRICING_ENV,
        "MKTKB_RAG_STAGE": "S2-DEV",
        "MKTKB_RAG_STAGE_LIMIT_CNY": "0.3",
        "MKTKB_RAG_MAX_REQUESTS": "3",
    }
    env.update(overrides)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_product_live_entry_rejects_replaced_ledger_and_budget(gate_env, monkeypatch):
    from mktkb.qa.service import resolve_rag_config

    def _resolve_product():
        return resolve_rag_config(
            data_dir=gate_env["root"] / "data",
            provider_mode="live",
            page_size=10,
            top_k=8,
            business_date=None,
        )

    _live_env(monkeypatch)
    config, budget = _resolve_product()
    assert budget is not None
    assert budget.ledger_path == gate_env["ledger"]
    assert budget.summary().historical_conservative_cny == pytest.approx(0.03)

    empty = gate_env["root"] / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("MKTKB_RAG_BUDGET_LEDGER", str(empty))
    with pytest.raises(ValueError, match="rag live"):
        _resolve_product()

    outside = Path(tempfile.mkdtemp(prefix="s2b-outside-")) / "ledger.jsonl"
    shutil.copyfile(gate_env["ledger"], outside)
    monkeypatch.setenv("MKTKB_RAG_BUDGET_LEDGER", str(outside))
    with pytest.raises(ValueError, match="rag live"):
        _resolve_product()

    monkeypatch.delenv("MKTKB_RAG_BUDGET_LEDGER")
    other_budget = gate_env["root"] / "other-budget.json"
    other_budget.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("MKTKB_RAG_BUDGET_JSON", str(other_budget))
    with pytest.raises(ValueError, match="rag live"):
        _resolve_product()


def test_budget_total_limit_stage_allocation_and_history_are_anchored(gate_env, monkeypatch):
    huge = gate_env["root"] / "huge.json"
    huge.write_text(json.dumps({"limit_cny": 99999, "stages": {"S2-DEV": 99999}}), encoding="utf-8")
    monkeypatch.setattr(gate_module, "SHARED_BUDGET_PATH", huge)
    with pytest.raises(LiveGateError):
        _resolve()
    no_stage = gate_env["root"] / "no-stage.json"
    no_stage.write_text(
        json.dumps({"limit_cny": 10.0, "stages": {"S1-DEV": 3.0}, "ledger": str(gate_env["ledger"])}),
        encoding="utf-8",
    )
    monkeypatch.setattr(gate_module, "SHARED_BUDGET_PATH", no_stage)
    with pytest.raises(LiveGateError):
        _resolve()
    empty = gate_env["root"] / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(gate_module, "SHARED_LEDGER_PATH", empty)
    with pytest.raises(LiveGateError):
        _resolve()


@pytest.mark.parametrize(
    "override",
    [
        {"stage": "S1-DEV"},
        {"scope": {"services": ["chat"]}},
        {"scope": {"stage_limits_cny": {"S2-DEV": 0}}},
        {"scope": {"max_requests": 0}},
        {"scope": {"max_request_cny": 0}},
        {"budget_ledger_sha256": "0" * 64},
        {"nonce": "short"},
        {"authorization": ""},
        {"issued_by": ""},
    ],
)
def test_go_schema_rejections(gate_env, override):
    _write_go(gate_env["go"], ledger_hash=_sha(gate_env["ledger"]), **override)
    with pytest.raises(LiveGateError):
        _resolve()


def test_go_expired_and_missing(gate_env):
    _write_go(
        gate_env["go"],
        ledger_hash=_sha(gate_env["ledger"]),
        issued_utc=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        expires_utc=(datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
    )
    with pytest.raises(LiveGateError):
        _resolve()
    gate_env["go"].unlink()
    with pytest.raises(LiveGateError):
        _resolve()


def test_go_does_not_self_invalidate_after_settlement_and_caps_requests(gate_env):
    gate = _resolve(requested_max_requests=2)
    ledger = gate.ledger()
    first = ledger.reserve(kind="embedding", provider="bailian", model="m", max_cny=0.04096,
                           request_sha256="a" * 64)
    ledger.settle(first, status="succeeded", usage={"total_tokens": 10}, estimated_list_price_cny=0.0001)
    # 账本增长后同一 GO 仍然可用（绑定的是不可变历史前缀）
    again = _resolve(requested_max_requests=2)
    assert again.ledger().summary().reservation_count == 1
    second = again.ledger().reserve(kind="chat", provider="deepseek", model="deepseek-chat",
                                    max_cny=0.005, request_sha256="b" * 64)
    again.ledger().settle(second, status="failed", error_code="MOCK")
    with pytest.raises(RequestLimitExceeded):
        again.ledger().reserve(kind="chat", provider="deepseek", model="deepseek-chat",
                               max_cny=0.005, request_sha256="c" * 64)


def test_request_bound_above_go_is_refused(gate_env):
    with pytest.raises(LiveGateError):
        _resolve(request_bound_cny=2.2)


def test_zero_or_missing_request_caps_are_refused(gate_env):
    with pytest.raises(LiveGateError):
        _resolve(requested_max_requests=0)
    with pytest.raises(LiveGateError):
        _resolve(requested_max_requests=-1)
    with pytest.raises(LiveGateError):
        _resolve(requested_stage_limit_cny=0)


def test_chat_pricing_missing_refuses_build(gate_env, monkeypatch):
    from mktkb.config import Settings
    from mktkb.providers import build_gateway

    settings = Settings(
        _env_file=None,
        data_dir=gate_env["root"] / "app",
        database_url=f"sqlite:///{(gate_env['root'] / 'app' / 'a.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="UnitPass-1",
        employee_password="UnitPass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        model_base_url=CHAT_PRICING_ENV["MKTKB_MODEL_BASE_URL"],
        model_name=CHAT_PRICING_ENV["MKTKB_MODEL_NAME"],
        model_api_key=CHAT_PRICING_ENV["MKTKB_MODEL_API_KEY"],
    )
    monkeypatch.setenv("MKTKB_RAG_STAGE_LIMIT_CNY", "0.3")
    monkeypatch.setenv("MKTKB_RAG_MAX_REQUESTS", "3")
    for key, value in CHAT_PRICING_ENV.items():
        if key.startswith("MKTKB_MODEL_"):
            monkeypatch.setenv(key, value)
    # 未签 GO：构造期拒绝，且不会产生任何 transport 调用
    gate_env["go"].unlink()
    posts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        posts["count"] += 1
        return httpx.Response(200, json={})

    with pytest.raises(ValueError):
        build_gateway(settings, transport=httpx.MockTransport(handler))
    assert posts["count"] == 0
    # 缺价格上界也拒绝
    _write_go(gate_env["go"], ledger_hash=_sha(gate_env["ledger"]))
    monkeypatch.delenv("MKTKB_MODEL_MAX_OUTPUT_TOKENS")
    with pytest.raises(ValueError):
        build_gateway(settings, transport=httpx.MockTransport(handler))
    assert posts["count"] == 0


def test_chat_gateway_reserves_settles_and_keeps_failed_charge(gate_env, monkeypatch):
    from mktkb.config import Settings
    from mktkb.providers import build_gateway
    from mktkb.providers.types import CompletionInput, DialogueContext, ModelUnavailable

    settings = Settings(
        _env_file=None,
        data_dir=gate_env["root"] / "app",
        database_url=f"sqlite:///{(gate_env['root'] / 'app' / 'b.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="UnitPass-1",
        employee_password="UnitPass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        model_base_url=CHAT_PRICING_ENV["MKTKB_MODEL_BASE_URL"],
        model_name=CHAT_PRICING_ENV["MKTKB_MODEL_NAME"],
        model_api_key=CHAT_PRICING_ENV["MKTKB_MODEL_API_KEY"],
        rag_qa_enabled=False,
    )
    for key, value in CHAT_PRICING_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MKTKB_RAG_STAGE_LIMIT_CNY", "0.3")
    monkeypatch.setenv("MKTKB_RAG_MAX_REQUESTS", "2")
    gate = resolve_live_gate(
        stage="S2-DEV", service="chat", requested_stage_limit_cny=5.0,
        requested_max_requests=2, request_bound_cny=2.103552,
    )
    request = CompletionInput(
        purpose="answer", question="湖滨店的展架在哪里？",
        context=DialogueContext(questions=(), entities={}), evidence=(),
    )
    posts = {"count": 0}

    def ok_handler(_request: httpx.Request) -> httpx.Response:
        posts["count"] += 1
        return httpx.Response(
            200,
            json={
                "id": "mock-1",
                "choices": [{"finish_reason": "stop",
                             "message": {"content": json.dumps({"answer": "ok", "source_ids": []})}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    gateway = build_gateway(settings, gate=gate, transport=httpx.MockTransport(ok_handler))
    before = gate.ledger().summary().as_dict()
    output = asyncio.run(gateway.complete(request, timeout_seconds=5.0))
    after = gate.ledger().summary().as_dict()
    assert output.text == "ok"
    assert posts["count"] == 1
    assert after["reservation_count"] == before["reservation_count"] + 1
    assert after["accounted_cny"] - before["accounted_cny"] == pytest.approx(2.103552)
    assert gateway.stats()["counters"]["reserved"] == 1
    assert gateway.stats()["counters"]["send_attempts"] == 1

    def fail_handler(_request: httpx.Request) -> httpx.Response:
        posts["count"] += 1
        return httpx.Response(500, json={"error": "mock"})

    failing = build_gateway(settings, gate=gate, transport=httpx.MockTransport(fail_handler))
    before_fail = gate.ledger().summary().as_dict()
    with pytest.raises(ModelUnavailable):
        asyncio.run(failing.complete(request, timeout_seconds=5.0))
    after_fail = gate.ledger().summary().as_dict()
    assert after_fail["accounted_cny"] - before_fail["accounted_cny"] == pytest.approx(2.103552)


def test_chat_gateway_refuses_before_post_when_request_cap_is_used(gate_env, monkeypatch):
    from mktkb.config import Settings
    from mktkb.providers import build_gateway
    from mktkb.providers.types import CompletionInput, DialogueContext, ModelBudgetRefused

    settings = Settings(
        _env_file=None,
        data_dir=gate_env["root"] / "app",
        database_url=f"sqlite:///{(gate_env['root'] / 'app' / 'c.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="UnitPass-1",
        employee_password="UnitPass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        model_base_url=CHAT_PRICING_ENV["MKTKB_MODEL_BASE_URL"],
        model_name=CHAT_PRICING_ENV["MKTKB_MODEL_NAME"],
        model_api_key=CHAT_PRICING_ENV["MKTKB_MODEL_API_KEY"],
        rag_qa_enabled=False,
    )
    for key, value in CHAT_PRICING_ENV.items():
        monkeypatch.setenv(key, value)
    gate = resolve_live_gate(
        stage="S2-DEV", service="chat", requested_stage_limit_cny=5.0,
        requested_max_requests=1, request_bound_cny=2.103552,
    )
    pre = gate.ledger().reserve(kind="rerank", provider="bailian", model="m",
                                max_cny=0.00001, request_sha256="e" * 64)
    gate.ledger().settle(pre, status="succeeded")
    posts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        posts["count"] += 1
        return httpx.Response(200, json={})

    gateway = build_gateway(settings, gate=gate, transport=httpx.MockTransport(handler))
    before = gate.ledger().summary().as_dict()
    before_reserved = len([row for row in _events(gate_env["ledger"]) if row.get("event") == "reserved"])
    with pytest.raises(ModelBudgetRefused) as excinfo:
        asyncio.run(gateway.complete(
            CompletionInput(purpose="answer", question="q",
                            context=DialogueContext(questions=(), entities={}), evidence=()),
            timeout_seconds=5.0,
        ))
    assert excinfo.value.code == "MODEL_BUDGET_REFUSED"
    assert posts["count"] == 0
    assert gateway.stats()["counters"]["refused"] == 1
    # 预算/授权拒绝：账本必须没有新增预留（拒绝发生在任何预留与 HTTP 之前）。
    after_reserved = len([row for row in _events(gate_env["ledger"]) if row.get("event") == "reserved"])
    assert after_reserved == before_reserved
    assert gate.ledger().summary().as_dict() == before


def _isolated_budget_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """隔离账本/预算/GO：只含一行历史 0.03，阶段分配 5.0。

    不使用 ``shutil.copyfile`` 复制仓库共享账本：它会随真实阶段继续增长（当前 83 笔预留 /
    14.3 元），抄本会让“请求数上限”类断言与账本内容耦合。这里的隔离不再依赖共享账本大小。
    """
    ledger = tmp_path / "isolated-ledger.jsonl"
    _write_ledger(ledger)
    budget_path = tmp_path / "budget.json"
    _write_budget(budget_path, ledger, stage="S2-DEV", stage_limit=5.0)
    go = tmp_path / "S2-LIVE-GO.json"
    _write_go(go, ledger_hash=_sha(ledger), scope={"stage_limits_cny": {"S2-DEV": 18.4}, "max_requests": 60})
    monkeypatch.setattr(gate_module, "SHARED_LEDGER_PATH", ledger)
    monkeypatch.setattr(gate_module, "SHARED_BUDGET_PATH", budget_path)
    monkeypatch.setattr(gate_module, "PRODUCT_GO_PATH", go)
    # budget.json 的 limit_cny 是 10.0：项目总上限必须与之逐值相等，否则闸门默认拒绝。
    monkeypatch.setenv("MKTKB_PROJECT_TOTAL_LIMIT_CNY", str(PROJECT_TOTAL_LIMIT_CNY))
    for key in ("MKTKB_RAG_BUDGET_LEDGER", "MKTKB_RAG_BUDGET_JSON", "MKTKB_RAG_STAGE"):
        monkeypatch.delenv(key, raising=False)
    return {"ledger": ledger, "budget": budget_path, "go": go, "root": tmp_path}


def test_chat_budget_refusal_is_stable_code_and_leaves_ledger_bytes_unchanged(tmp_path, monkeypatch):
    """阶段额度不足（真实 UI 已发生过的场景）：稳定码 + 零 HTTP + 账本逐字节不变。

    旧行为把它显示成 MODEL_UNAVAILABLE（"服务不可用"），掩盖了"预算/授权不足"这一真实原因。
    """
    from mktkb.config import Settings
    from mktkb.providers import build_gateway
    from mktkb.providers.types import CompletionInput, DialogueContext, ModelBudgetRefused

    env = _isolated_budget_env(tmp_path, monkeypatch)
    for key, value in CHAT_PRICING_ENV.items():
        monkeypatch.setenv(key, value)
    settings = Settings(
        _env_file=None,
        data_dir=env["root"] / "app",
        database_url=f"sqlite:///{(env['root'] / 'app' / 'b2.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="unit-test-csrf-secret-0123456789",
        admin_password="UnitPass-1",
        employee_password="UnitPass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        model_base_url=CHAT_PRICING_ENV["MKTKB_MODEL_BASE_URL"],
        model_name=CHAT_PRICING_ENV["MKTKB_MODEL_NAME"],
        model_api_key=CHAT_PRICING_ENV["MKTKB_MODEL_API_KEY"],
        rag_qa_enabled=False,
    )
    # 阶段额度 1.0 元 - 历史 0.03 < 单次 chat 保守上界 2.103552 元：任何一次预留都必须被拒。
    gate = resolve_live_gate(
        stage="S2-DEV", service="chat", requested_stage_limit_cny=1.0,
        requested_max_requests=5, request_bound_cny=2.103552,
    )
    assert gate.stage_limit_cny == pytest.approx(1.0)
    posts = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - 不应被调用
        posts["count"] += 1
        return httpx.Response(200, json={})

    gateway = build_gateway(settings, gate=gate, transport=httpx.MockTransport(handler))
    ledger_digest_before = _sha(env["ledger"])
    before = gate.ledger().summary().as_dict()
    with pytest.raises(ModelBudgetRefused) as excinfo:
        asyncio.run(gateway.complete(
            CompletionInput(purpose="answer", question="q",
                            context=DialogueContext(questions=(), entities={}), evidence=()),
            timeout_seconds=5.0,
        ))

    assert excinfo.value.code == "MODEL_BUDGET_REFUSED"
    assert excinfo.value.retryable is False
    assert "预算/授权闸门拒绝" in str(excinfo.value)
    assert posts["count"] == 0, "预算拒绝不得发出任何 HTTP"
    assert gateway.stats()["counters"]["refused"] == 1
    assert gateway.stats()["counters"]["reserved"] == 0
    assert _sha(env["ledger"]) == ledger_digest_before, "预算拒绝不得写入任何账本行"
    assert gate.ledger().summary().as_dict() == before


def test_chat_and_embedding_share_one_ledger(gate_env):
    gate = resolve_live_gate(
        stage="S2-DEV", service="chat", requested_stage_limit_cny=5.0,
        requested_max_requests=3, request_bound_cny=2.103552,
    )
    config = RagConfig(
        provider_mode="offline",
        embedding_api_key="unit-mock-key",
        embedding_base_url="https://mock.bailian.invalid",
    )

    def emb_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "e1", "data": [{"index": 0, "embedding": [0.0] * 1024}],
                  "usage": {"prompt_tokens": 5, "total_tokens": 5}},
        )

    embedder = BailianEmbeddingProvider(
        config, budget=gate.ledger(), transport=httpx.MockTransport(emb_handler)
    )
    response = embedder.embed(["湖滨店 展架"], purpose="query")
    kinds = [event.get("kind") for event in _events(gate_env["ledger"]) if event["event"] == "reserved"]
    assert kinds == ["embedding"]
    assert len(response.vectors) == 1
    summary = gate.ledger().summary().as_dict()
    assert summary["stage"] == "S2-DEV"
    assert summary["accounted_cny"] == pytest.approx(0.03 + 0.04096)


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
