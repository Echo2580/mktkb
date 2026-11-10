"""P1-F：live 请求计数口径与「超限前拒绝」的离线回归。

本文件锁定三件事（完整口径见 ``docs/evaluation/live-request-accounting-2026-11-10.md``）：

1. ``GO scope.max_requests`` 是 **运行上限**（累计口径，跨 kind/stage/run），由共享账本在
   预留前拒绝；拒绝发生在任何供应商 HTTP 之前，账本不新增行。
2. ``GO scope.bindings.rag.embedding_requests / rerank_requests`` 是 **J2 受控计划值**
   （``s2j2-controlled-plan-v1`` + ``request_plan_sha256`` 绑定、plan stage=S2-DEV），
   不被 P1 live retrieval 路线消费，也不参与运行上限；P1 只核对 provider/model/region
   与 settlement_version 绑定。
3. 预检 ``request_limit_insufficient`` 在构造 index/provider 之前拒绝（零真实调用）。

零真实网络/零 .env：账本/预算/GO 全是 tmp_path 隔离副本，provider 只用
``httpx.MockTransport``；仓库共享账本只读一次（GO 计划值一致性断言），不写任何证据文件。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from mktkb import live_authorization
from mktkb.evaluation import live as live_module
from mktkb.evaluation.dataset import load_cases, write_cases
from mktkb.evaluation.live import (
    LiveBudgetRefused,
    LiveConfigError,
    LiveRuntime,
    load_live_runtime,
    plan_live_cost,
)
from mktkb.evaluation.runner import run_suite
from mktkb.rag.budget import BudgetLedger, RequestLimitExceeded
from mktkb.rag.config import RagConfig
from mktkb.rag.providers import BailianEmbeddingProvider
from mktkb.rag.types import EmbeddingResponse, RerankResponse, RerankResult

STAGE = "P1-RETRIEVAL"
STAGE_LIMIT_CNY = 3.0
MAX_REQUEST_CNY = 0.05
MAX_REQUESTS = 1000
TOTAL_LIMIT_CNY = 20.0
HISTORY_CNY = 0.03

#: P1 live 路线在 GO 上实际核对的 provider 绑定键（``evaluation/live.py:_assert_live_bindings``）。
EXPECTED_LIVE_BINDING_KEYS = frozenset(
    {
        "base_url_host",
        "embedding_provider",
        "embedding_model",
        "embedding_dimensions",
        "embedding_host",
        "embedding_region",
        "rerank_provider",
        "rerank_model",
        "rerank_host",
        "rerank_region",
        "region",
        "settlement_version",
    }
)
#: J2 受控计划值：只有 ``controlled_execution.py`` 的受控执行路线消费，不是 P1 运行上限。
PLAN_ONLY_BINDING_KEYS = frozenset(
    {
        "plan_version",
        "request_plan_sha256",
        "serial",
        "embedding_requests",
        "rerank_requests",
        "ocr_text_requests",
        "ocr_table_requests",
        "ocr_max_calls",
        "ocr_max_tiles_per_page",
        "ocr_max_attempts",
        "embedding_total_tokens_cap",
        "rerank_total_tokens_cap",
        "ocr_text_price_cny",
        "ocr_table_price_cny",
        "ocr_provider",
        "ocr_host",
        "ocr_region",
        "ocr_text_model",
        "ocr_table_model",
        "ocr_pricing_source",
    }
)


# --------------------------------------------------------------------------- #
# 隔离账本 / 预算 / GO（一律 tmp_path 副本，不碰仓库共享文件）
# --------------------------------------------------------------------------- #


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_ledger(path: Path, *, historical: float = HISTORY_CNY) -> None:
    path.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": historical}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_budget(path: Path, *, stage_limit: float = STAGE_LIMIT_CNY) -> None:
    path.write_text(
        json.dumps(
            {
                "limit_cny": TOTAL_LIMIT_CNY,
                "historical_conservative_accounted_cny": HISTORY_CNY,
                "stages": {STAGE: stage_limit},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _provider_bindings() -> dict:
    return {
        "base_url_host": "dashscope.aliyuncs.com",
        "embedding_provider": "bailian",
        "embedding_model": "text-embedding-v4",
        "embedding_dimensions": 1024,
        "embedding_host": "dashscope.aliyuncs.com",
        "embedding_region": "cn-beijing",
        "rerank_provider": "bailian",
        "rerank_model": "gte-rerank-v2",
        "rerank_host": "dashscope.aliyuncs.com",
        "rerank_region": "cn-beijing",
        "region": "beijing",
        "settlement_version": "usage-conservative-v1",
    }


def _write_go(
    path: Path,
    *,
    ledger_sha: str,
    plan_embedding_requests: int = 1,
    plan_rerank_requests: int = 1,
) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "document": "S2-LIVE-GO",
        "stage": STAGE,
        "authorization": "UNIT-TEST-MOCK-GO（零真实调用）",
        "issued_by": "pytest",
        "nonce": "unit-test-nonce-0123456789",
        "issued_utc": (now - timedelta(minutes=5)).isoformat(),
        "expires_utc": (now + timedelta(hours=1)).isoformat(),
        "budget_ledger_sha256": ledger_sha,
        "scope": {
            "services": ["rag"],
            "stage_limits_cny": {STAGE: STAGE_LIMIT_CNY},
            "max_requests": MAX_REQUESTS,
            "max_request_cny": MAX_REQUEST_CNY,
            "bindings": {
                "rag": {
                    **_provider_bindings(),
                    # 计划值：故意写得极小，用于证明它们不会变成运行上限。
                    "plan_version": "s2j2-controlled-plan-v1",
                    "request_plan_sha256": "f" * 64,
                    "serial": True,
                    "embedding_requests": plan_embedding_requests,
                    "rerank_requests": plan_rerank_requests,
                    "ocr_text_requests": 1,
                    "ocr_table_requests": 1,
                    "ocr_max_calls": 2,
                    "ocr_max_tiles_per_page": 1,
                    "ocr_max_attempts": 1,
                    "embedding_total_tokens_cap": 4096,
                    "rerank_total_tokens_cap": 6000,
                }
            },
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _isolated_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan_embedding_requests: int = 1,
    plan_rerank_requests: int = 1,
) -> dict[str, str]:
    ledger = tmp_path / "live-ledger.jsonl"
    budget = tmp_path / "budget.json"
    go = tmp_path / "S2-LIVE-GO.json"
    _write_ledger(ledger)
    _write_budget(budget)
    _write_go(
        go,
        ledger_sha=_sha(ledger),
        plan_embedding_requests=plan_embedding_requests,
        plan_rerank_requests=plan_rerank_requests,
    )
    monkeypatch.setattr(live_authorization, "SHARED_LEDGER_PATH", ledger)
    monkeypatch.setattr(live_authorization, "SHARED_BUDGET_PATH", budget)
    monkeypatch.setattr(live_authorization, "PRODUCT_GO_PATH", go)
    # project_total_limit_cny() 读 os.environ；给 run/lock 内的同一只账本一个自洽总上限。
    monkeypatch.setenv("MKTKB_PROJECT_TOTAL_LIMIT_CNY", str(TOTAL_LIMIT_CNY))
    for name in ("MKTKB_RAG_STAGE_LIMIT_CNY", "MKTKB_RAG_MAX_REQUESTS"):
        monkeypatch.delenv(name, raising=False)
    return {
        "MKTKB_PROJECT_TOTAL_LIMIT_CNY": str(TOTAL_LIMIT_CNY),
        "DASHSCOPE_API_KEY": "unit-test-key",
    }


def _authorization(rag_bindings: dict) -> live_authorization.LiveAuthorization:
    now = datetime.now(timezone.utc)
    return live_authorization.LiveAuthorization(
        stage=STAGE,
        service="rag",
        issued_by="pytest",
        nonce="unit-test-nonce-0123456789",
        issued_utc=now - timedelta(minutes=5),
        expires_utc=now + timedelta(hours=1),
        stage_limit_cny=STAGE_LIMIT_CNY,
        max_requests=MAX_REQUESTS,
        max_request_cny=MAX_REQUEST_CNY,
        ledger_sha256="0" * 64,
        source_path="unit-test-go",
        bindings={"rag": dict(rag_bindings)},
    )


# --------------------------------------------------------------------------- #
# 1. GO 计划值 = J2 计划的计划值，不是 P1 运行上限
# --------------------------------------------------------------------------- #


def test_go_plan_counts_bind_the_s2_j2_plan_not_p1_request_caps() -> None:
    """``request_plan_sha256`` 反推出计划：7/4/1/1 是 S2-DEV 的 J2 计划，不是本 GO 的请求上限。"""
    from mktkb.controlled_execution import ControlledRequestPlan

    go = json.loads(live_authorization.PRODUCT_GO_PATH.read_text(encoding="utf-8"))
    rag = go["scope"]["bindings"]["rag"]
    # 由 GO 里 request_plan_sha256 反解出的唯一计划（chat 2 次 + embedding 7 + rerank 4 + OCR 1+1）。
    plan = ControlledRequestPlan(
        stage="S2-DEV",
        chat_requests=2,
        embedding_requests=7,
        rerank_requests=4,
        ocr_text_requests=1,
        ocr_table_requests=1,
    )
    assert rag["plan_version"] == plan.plan_version == "s2j2-controlled-plan-v1"
    assert rag["request_plan_sha256"] == plan.request_plan_sha256
    assert (rag["embedding_requests"], rag["rerank_requests"]) == (7, 4)
    assert (plan.embedding_requests, plan.rerank_requests) == (7, 4)
    assert rag["ocr_max_calls"] == plan.ocr_total_requests == 2
    assert (rag["embedding_total_tokens_cap"], rag["rerank_total_tokens_cap"]) == (4096, 6000)
    assert (plan.embedding_total_tokens_cap, plan.rerank_total_tokens_cap) == (4096, 6000)
    assert plan.total_calls == 15

    # 计划绑定的是另一个阶段（S2-DEV）的 J2 计划；本 GO 是 P1-RETRIEVAL，
    # 因此这些计划值不是本路线的运行上限，本路线上限只有 scope.max_requests。
    assert plan.stage == "S2-DEV"
    assert go["stage"] == STAGE
    assert go["scope"]["max_requests"] == MAX_REQUESTS > plan.total_calls
    assert go["scope"]["max_request_cny"] == MAX_REQUEST_CNY
    assert go["scope"]["stage_limits_cny"] == {STAGE: STAGE_LIMIT_CNY}


def test_plan_counts_do_not_become_runtime_caps_for_p1_live_route(
    tmp_path, b0_cases, monkeypatch
) -> None:
    """GO 绑定里的 1/1 计划值不会收窄运行上限；预检按 scope.max_requests 放行 27 个真实请求。"""
    env = _isolated_gate(tmp_path, monkeypatch, plan_embedding_requests=1, plan_rerank_requests=1)
    runtime = load_live_runtime(
        data_dir=tmp_path / "index",
        business_date="2026-10-28",
        environ=env,
        env_file=None,
    )
    # 运行上限只来自 scope.max_requests=1000（GO 累计口径），不是 bindings 的 1/1 计划值。
    assert runtime.max_requests == MAX_REQUESTS
    assert runtime.stage_limit_cny == pytest.approx(STAGE_LIMIT_CNY)
    assert runtime.max_request_cny == pytest.approx(MAX_REQUEST_CNY)
    assert runtime.budget.max_requests == MAX_REQUESTS
    assert runtime.authorization is not None
    # 计划值仍被解析并保存在 bindings（可审计），但运行器不把它当限制使用。
    assert runtime.authorization.bindings["rag"]["embedding_requests"] == 1
    assert runtime.authorization.bindings["rag"]["rerank_requests"] == 1

    dataset = tmp_path / "b0-pilot10.jsonl"
    write_cases(dataset, b0_cases[:10])
    cases = load_cases(dataset)
    corpus = live_module.load_suite_corpus(
        "b0", live_module.default_corpus_dir("b0"), business_date="2026-10-28"
    )
    estimate = plan_live_cost(
        corpus,
        cases,
        runtime.config,
        stage_remaining_cny=runtime.stage_limit_cny,
        request_remaining=runtime.max_requests,
        max_request_cny=runtime.max_request_cny,
    )
    assert estimate.total_requests == 27  # 7 索引批 + 10 查询 embedding + 10 rerank
    assert estimate.total_requests > 1 + 1  # 若计划值当上限，27 请求必须被拒
    assert estimate.accepted is True


# --------------------------------------------------------------------------- #
# 2. P1 live 绑定的期望键集合：只核对 provider/model/region/settlement_version
# --------------------------------------------------------------------------- #


def test_assert_live_bindings_checks_provider_keys_but_not_plan_counts(monkeypatch) -> None:
    captured: dict = {}
    original = live_module.assert_provider_binding

    def fake_assert(authorization, service, **expected):
        captured.update(expected)
        return dict(authorization.bindings[service])

    monkeypatch.setattr(live_module, "assert_provider_binding", fake_assert)
    config = RagConfig()
    live_module._assert_live_bindings(_authorization(_provider_bindings()), config)

    assert set(captured) == EXPECTED_LIVE_BINDING_KEYS
    assert not set(captured) & PLAN_ONLY_BINDING_KEYS
    assert captured["embedding_model"] == config.embedding_model
    assert captured["settlement_version"] == "usage-conservative-v1"

    # 正向对照：绑定核对不是空转——缺少 provider 字段时仍在首个预留前拒绝。
    monkeypatch.setattr(live_module, "assert_provider_binding", original)
    missing = _provider_bindings()
    missing.pop("embedding_host")
    with pytest.raises(LiveConfigError, match="GO 供应商绑定不匹配"):
        live_module._assert_live_bindings(_authorization(missing), config)


# --------------------------------------------------------------------------- #
# 3. 累计请求上限：跨 kind 计数、预留前拒绝、零 HTTP、零账本写入
# --------------------------------------------------------------------------- #


def test_cumulative_request_cap_refuses_before_provider_http(tmp_path) -> None:
    ledger_path = tmp_path / "live-ledger.jsonl"
    budget_path = tmp_path / "budget.json"
    _write_ledger(ledger_path)
    _write_budget(budget_path)
    ledger = BudgetLedger(
        ledger_path,
        budget_path,
        stage=STAGE,
        stage_limit_cny=STAGE_LIMIT_CNY,
        max_requests=1,
    )
    # 「已用 = 上限」：先记一笔 rerank 预留；累计口径会占用后续 embedding 的额度。
    ledger.reserve(
        kind="rerank",
        provider="bailian",
        model="gte-rerank-v2",
        max_cny=0.024,
        request_sha256="a" * 64,
    )
    posts = {"attempts": 0}

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - 不应被调用
        posts["attempts"] += 1
        return httpx.Response(200, json={})

    config = RagConfig(
        provider_mode="offline",
        embedding_api_key="unit-test-key",
        embedding_base_url="https://dashscope.aliyuncs.com",
        embedding_batch_size=5,
        max_request_cny=MAX_REQUEST_CNY,
    )
    provider = BailianEmbeddingProvider(
        config, budget=ledger, transport=httpx.MockTransport(handler)
    )
    digest_before = _sha(ledger_path)
    summary_before = ledger.summary().as_dict()
    with pytest.raises(RequestLimitExceeded, match="未发请求"):
        provider.embed(["湖滨店 展架位置"], purpose="query")

    assert posts["attempts"] == 0, "累计请求上限拒绝不得发出任何 HTTP"
    assert _sha(ledger_path) == digest_before, "拒绝不得写入账本行"
    assert ledger.summary().as_dict() == summary_before
    assert ledger.summary().reservation_count == 1  # rerank + embedding 共用同一累计计数


# --------------------------------------------------------------------------- #
# 4. 预检 request_limit_insufficient：构造 index/provider 之前拒绝
# --------------------------------------------------------------------------- #


class _FakeBudget:
    def __init__(self, *, stage_remaining: float = STAGE_LIMIT_CNY, reservation_count: int) -> None:
        self._summary = SimpleNamespace(
            stage=STAGE,
            stage_limit_cny=STAGE_LIMIT_CNY,
            stage_accounted_cny=STAGE_LIMIT_CNY - stage_remaining,
            stage_remaining_cny=stage_remaining,
            total_limit_cny=TOTAL_LIMIT_CNY,
            historical_conservative_cny=HISTORY_CNY,
            accounted_cny=HISTORY_CNY,
            remaining_cny=TOTAL_LIMIT_CNY - HISTORY_CNY,
            success_estimated_list_price_cny=0.0,
            provider_billed_cny=None,
            reservation_count=reservation_count,
            result_count=reservation_count,
        )

    def summary(self) -> SimpleNamespace:
        return self._summary


class _FakeEmbedder:
    provider = "bailian"
    model = "text-embedding-v4"
    dimensions = 1024

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts, *, purpose: str = "document") -> EmbeddingResponse:
        self.calls += 1
        vectors = tuple((1.0,) + (0.0,) * 1023 for _ in texts)
        return EmbeddingResponse(
            vectors=vectors,
            model=self.model,
            dimensions=self.dimensions,
            provider=self.provider,
            usage={"total_tokens": max(1, len(texts) * 10)},
        )

    def close(self) -> None:
        return None


class _FakeReranker:
    provider = "bailian"
    model = "gte-rerank-v2"

    def __init__(self) -> None:
        self.calls = 0

    def rerank(self, query, documents, *, top_n=None) -> RerankResponse:
        self.calls += 1
        return RerankResponse(
            results=tuple(
                RerankResult(index=index, score=1.0 / (index + 1))
                for index in range(len(documents))
            ),
            model=self.model,
            provider=self.provider,
            usage={"total_tokens": max(1, len(documents) * 10)},
        )

    def close(self) -> None:
        return None


def _runtime(tmp_path: Path, *, reservation_count: int, embedder, reranker) -> LiveRuntime:
    config = RagConfig(
        provider_mode="live",
        data_dir=tmp_path / "index",
        business_date="2026-10-28",
        embedding_api_key="unit-test-key",
        rerank_api_key="unit-test-key",
        embedding_batch_size=5,
        chunk_max_chars=420,
        chunk_max_units=3,
        chunk_overlap_units=1,
        top_k=8,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=10,
        max_request_cny=MAX_REQUEST_CNY,
        max_retries=0,
        require_zero_retries=True,
        stage=STAGE,
        stage_limit_cny=STAGE_LIMIT_CNY,
    )
    return LiveRuntime(
        config=config,
        budget=_FakeBudget(reservation_count=reservation_count),
        stage=STAGE,
        service="rag",
        stage_limit_cny=STAGE_LIMIT_CNY,
        max_requests=MAX_REQUESTS,
        max_request_cny=MAX_REQUEST_CNY,
        authorization=None,
        ledger_path=None,
        budget_path=None,
        go_path=None,
        credentials_source="unit-test",
        embedder=embedder,
        reranker=reranker,
    )


def test_precheck_request_limit_insufficient_refuses_before_index_build(
    tmp_path, b0_cases
) -> None:
    dataset = tmp_path / "b0-pilot10.jsonl"
    write_cases(dataset, b0_cases[:10])
    cases = load_cases(dataset)
    corpus = live_module.load_suite_corpus(
        "b0", live_module.default_corpus_dir("b0"), business_date="2026-10-28"
    )
    embedder = _FakeEmbedder()
    reranker = _FakeReranker()
    # 累计已用 = 上限：request_remaining = max(0, 1000 - 1000) = 0。
    runtime = _runtime(
        tmp_path, reservation_count=MAX_REQUESTS, embedder=embedder, reranker=reranker
    )

    estimate = plan_live_cost(
        corpus,
        cases,
        runtime.config,
        stage_remaining_cny=STAGE_LIMIT_CNY,
        request_remaining=0,
        max_request_cny=MAX_REQUEST_CNY,
    )
    assert estimate.total_requests == 27
    assert estimate.reasons == ("request_limit_insufficient",)
    with pytest.raises(LiveBudgetRefused, match="request_limit_insufficient"):
        estimate.assert_accepted()

    with pytest.raises(LiveBudgetRefused, match="request_limit_insufficient"):
        run_suite(
            "b0",
            "live",
            scope="retrieval_only",
            dataset_path=dataset,
            pilot_cases=10,
            out_dir=tmp_path / "run",
            live_runtime=runtime,
            live_env_file=None,
        )

    # 预检拒绝必须早于 out 目录/index/真实 provider 构造。
    assert not (tmp_path / "run").exists()
    assert not (tmp_path / "run" / "index").exists()
    assert embedder.calls == 0
    assert reranker.calls == 0
