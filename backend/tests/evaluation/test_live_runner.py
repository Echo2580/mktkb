"""P1 T111：live 检索运行器（retrieval_only）的离线回归。

全部使用 fake embedder/reranker + 临时预算/GO 副本；不读仓库真实 ``.env``、不写共享
账本、不发真实网络。覆盖：成本预检/预算拒绝、GO 绑定不符、零 chat、fail closed、
零重试、pilot=10 停止、manifest/逐行版本字段、OCR 显式跳过。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from mktkb import live_authorization
from mktkb.evaluation import live as live_module
from mktkb.evaluation.dataset import load_cases, write_cases
from mktkb.evaluation.live import (
    LiveBudgetRefused,
    LiveConfigError,
    LiveRuntime,
    httpx_compatible_proxy_env,
    load_live_runtime,
    plan_live_cost,
)
from mktkb.evaluation.runner import run_suite
from mktkb.rag.config import RagConfig
from mktkb.rag.types import EmbeddingResponse, RerankResponse, RerankResult

ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #


class _FakeBudget:
    def __init__(
        self,
        *,
        stage_remaining: float = 3.0,
        reservation_count: int = 381,
        stage_accounted: float = 0.0,
    ) -> None:
        self._summary = SimpleNamespace(
            stage="P1-RETRIEVAL",
            stage_limit_cny=3.0,
            stage_accounted_cny=stage_accounted,
            stage_remaining_cny=stage_remaining,
            total_limit_cny=20.0,
            historical_conservative_cny=15.0566296,
            accounted_cny=15.0566296 + stage_accounted,
            remaining_cny=20.0 - 15.0566296 - stage_accounted,
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

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def rerank(self, query, documents, *, top_n=None) -> RerankResponse:
        self.calls += 1
        if self.fail:
            raise RuntimeError("fake rerank failure")
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


def _runtime(
    tmp_path: Path,
    *,
    stage_remaining: float = 3.0,
    max_request_cny: float = 0.05,
    max_requests: int = 1000,
    reservation_count: int = 381,
    embedder=None,
    reranker=None,
) -> LiveRuntime:
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
        max_request_cny=max_request_cny,
        max_retries=0,
        require_zero_retries=True,
        stage="P1-RETRIEVAL",
        stage_limit_cny=3.0,
    )
    return LiveRuntime(
        config=config,
        budget=_FakeBudget(
            stage_remaining=stage_remaining, reservation_count=reservation_count
        ),
        stage="P1-RETRIEVAL",
        service="rag",
        stage_limit_cny=3.0,
        max_requests=max_requests,
        max_request_cny=max_request_cny,
        authorization=None,
        ledger_path=None,
        budget_path=None,
        go_path=None,
        credentials_source="unit-test",
        embedder=embedder,
        reranker=reranker,
    )


@pytest.fixture()
def pilot_dataset(tmp_path: Path, b0_cases) -> Path:
    target = tmp_path / "b0-pilot10.jsonl"
    write_cases(target, b0_cases[:10])
    return target


def _run_pilot(tmp_path: Path, dataset: Path, runtime: LiveRuntime, **overrides):
    params = {
        "scope": live_module.LIVE_SCOPE,
        "dataset_path": dataset,
        "pilot_cases": 10,
        "out_dir": tmp_path / "run",
        "live_runtime": runtime,
        "live_env_file": None,
    }
    params.update(overrides)
    return run_suite("b0", "live", **params)


# --------------------------------------------------------------------------- #
# 成功路径 / manifest / 版本字段 / 隔离索引
# --------------------------------------------------------------------------- #


def test_live_pilot_writes_isolated_index_and_version_fields(tmp_path, pilot_dataset) -> None:
    embedder = _FakeEmbedder()
    reranker = _FakeReranker()
    result = _run_pilot(
        tmp_path,
        pilot_dataset,
        _runtime(tmp_path, embedder=embedder, reranker=reranker),
    )

    assert result.aborted is False
    assert len(result.cases) == 10
    assert (tmp_path / "run" / "index" / "rag.sqlite3").is_file()
    assert embedder.calls > 0
    assert reranker.calls == 10

    manifest = json.loads((tmp_path / "run" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "live"
    assert manifest["scope"] == "retrieval_only"
    assert manifest["suite"] == "b0"
    assert manifest["case_count"] == 10
    assert manifest["index_revision"] > 0
    for name in (
        "dataset_version",
        "dataset_sha256",
        "corpus_manifest_sha256",
        "index_revision",
        "pipeline_version",
        "gate_version",
        "label_version",
        "business_date",
        "config_hash",
    ):
        assert manifest[name] not in (None, ""), name
    assert manifest["pipeline_version"] != ""

    rows = [
        json.loads(line)
        for line in (tmp_path / "run" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["status"] for row in rows] == ["pass"] * 10
    for row in rows:
        versions = row["versions"]
        assert versions["dataset_version"] == manifest["dataset_version"]
        assert versions["corpus_manifest_sha256"] == manifest["corpus_manifest_sha256"]
        assert versions["index_revision"] == manifest["index_revision"]
        assert versions["pipeline_version"] == manifest["pipeline_version"]
        assert versions["gate_version"] == manifest["gate_version"]
        assert versions["mode"] == "live"
        assert versions["scope"] == "retrieval_only"
        assert row["retrieval_only"] is True

    summary = json.loads((tmp_path / "run" / "summary.json").read_text(encoding="utf-8"))
    assert summary["retrieval_only"] is True
    assert summary["live"]["chat_calls"] == 0
    assert summary["live"]["pilot"] is True
    assert summary["live"]["pilot_cases"] == 10
    assert summary["live"]["precheck"]["accepted"] is True
    assert summary["metrics"]["Recall@10"] is not None
    assert summary["metrics"]["empty_recall_rate"] is not None
    assert "value_hit" not in summary["metrics"]
    assert summary["declarations"]["retrieval_only"]["answers_generated"] is False


def test_live_zero_chat_spy_and_ocr_skipped(tmp_path, b0_cases, monkeypatch) -> None:
    import mktkb.rag.index as index_module
    import mktkb.rag.providers as providers

    counts = {"init": 0, "complete": 0, "ask": 0}

    def spy_init(self, *args, **kwargs):
        counts["init"] += 1
        raise AssertionError("live retrieval_only 不得构造 chat provider")

    def spy_complete(self, *args, **kwargs):
        counts["complete"] += 1
        raise AssertionError("live retrieval_only 不得调用 chat")

    def spy_ask(self, *args, **kwargs):
        counts["ask"] += 1
        raise AssertionError("live retrieval_only 不得调用 RagIndex.ask")

    monkeypatch.setattr(providers.DeepSeekChatProvider, "__init__", spy_init)
    monkeypatch.setattr(providers.DeepSeekChatProvider, "complete", spy_complete)
    monkeypatch.setattr(index_module.RagIndex, "ask", spy_ask)

    ocr_case = next(case for case in b0_cases if case.requires_ocr)
    normal = b0_cases[0]
    dataset = tmp_path / "pilot2.jsonl"
    write_cases(dataset, [normal, ocr_case])
    reranker = _FakeReranker()
    result = run_suite(
        "b0",
        "live",
        scope="retrieval_only",
        dataset_path=dataset,
        pilot_cases=2,
        out_dir=tmp_path / "run",
        live_runtime=_runtime(tmp_path, embedder=_FakeEmbedder(), reranker=reranker),
        live_env_file=None,
    )

    rows = result.cases
    assert [row["status"] for row in rows] == ["pass", "skipped_requires_ocr"]
    assert rows[1]["metrics"] == {}
    assert rows[1]["versions"]["mode"] == "live"
    assert reranker.calls == 1  # OCR case never reaches retrieval
    assert counts == {"init": 0, "complete": 0, "ask": 0}
    assert result.summary["live"]["chat_calls"] == 0


def test_live_multi_turn_retrieval_uses_sequential_state(tmp_path, b0_cases) -> None:
    base = b0_cases[0]
    case = replace(
        base,
        case_id="MT01",
        turns=(
            {"role": "user", "text": base.question},
            {"role": "user", "text": base.question},
        ),
    )
    dataset = tmp_path / "mt.jsonl"
    write_cases(dataset, [case])
    reranker = _FakeReranker()
    result = run_suite(
        "b0",
        "live",
        scope="retrieval_only",
        dataset_path=dataset,
        pilot_cases=1,
        out_dir=tmp_path / "run",
        live_runtime=_runtime(tmp_path, embedder=_FakeEmbedder(), reranker=reranker),
        live_env_file=None,
    )
    row = result.cases[0]
    assert row["status"] == "pass"
    assert row["turns_executed"] == 2
    assert [item["turn"] for item in row["turn_traces"]] == [1, 2]
    assert all(item["status"] == "ok" for item in row["turn_traces"])
    assert row["trace_id"] == row["turn_traces"][-1]["trace_id"]
    assert row["trace_id"] != row["turn_traces"][0]["trace_id"]
    assert reranker.calls == 2


# --------------------------------------------------------------------------- #
# pilot 停点
# --------------------------------------------------------------------------- #


def test_live_requires_explicit_pilot_and_exact_subset(tmp_path, b0_cases) -> None:
    full = tmp_path / "b0-full.jsonl"
    write_cases(full, b0_cases)
    runtime = _runtime(tmp_path, embedder=_FakeEmbedder(), reranker=_FakeReranker())
    with pytest.raises(LiveConfigError, match="主人放行"):
        run_suite(
            "b0",
            "live",
            scope="retrieval_only",
            dataset_path=full,
            out_dir=tmp_path / "r1",
            live_runtime=runtime,
            live_env_file=None,
        )
    with pytest.raises(LiveConfigError, match="1–10"):
        run_suite(
            "b0",
            "live",
            scope="retrieval_only",
            dataset_path=full,
            pilot_cases=11,
            out_dir=tmp_path / "r2",
            live_runtime=runtime,
            live_env_file=None,
        )
    with pytest.raises(LiveConfigError, match="恰好 10 题"):
        run_suite(
            "b0",
            "live",
            scope="retrieval_only",
            dataset_path=full,
            pilot_cases=10,
            out_dir=tmp_path / "r3",
            live_runtime=runtime,
            live_env_file=None,
        )
    with pytest.raises(ValueError, match="只用于 mode='live'"):
        run_suite(
            "b0",
            "local",
            dataset_path=full,
            pilot_cases=1,
            out_dir=tmp_path / "r4",
        )


# --------------------------------------------------------------------------- #
# 成本预检 / 预算拒绝
# --------------------------------------------------------------------------- #


def _estimate(tmp_path, runtime, pilot_dataset):
    cases = load_cases(pilot_dataset)
    corpus = live_module.load_suite_corpus(
        "b0", live_module.default_corpus_dir("b0"), business_date="2026-10-28"
    )
    return corpus, cases


def test_live_precheck_rejects_stage_and_single_request(tmp_path, pilot_dataset) -> None:
    runtime = _runtime(tmp_path)
    corpus, cases = _estimate(tmp_path, runtime, pilot_dataset)
    estimate = plan_live_cost(
        corpus,
        cases,
        runtime.config,
        stage_remaining_cny=3.0,
        request_remaining=1000,
        max_request_cny=0.05,
    )
    assert estimate.accepted is True
    assert estimate.total_requests == 27  # 7 index batches + 10 query + 10 rerank
    assert estimate.estimated_cny <= 3.0

    refused_stage = plan_live_cost(
        corpus,
        cases,
        runtime.config,
        stage_remaining_cny=0.001,
        request_remaining=1000,
        max_request_cny=0.05,
    )
    assert refused_stage.accepted is False
    assert "stage_remaining_insufficient" in refused_stage.reasons

    refused_cap = plan_live_cost(
        corpus,
        cases,
        runtime.config,
        stage_remaining_cny=3.0,
        request_remaining=1000,
        max_request_cny=0.01,
    )
    assert "single_request_cap_exceeded" in refused_cap.reasons

    refused_requests = plan_live_cost(
        corpus,
        cases,
        runtime.config,
        stage_remaining_cny=3.0,
        request_remaining=5,
        max_request_cny=0.05,
    )
    assert "request_limit_insufficient" in refused_requests.reasons


def test_live_runner_refuses_before_building_index(tmp_path, pilot_dataset) -> None:
    embedder = _FakeEmbedder()
    reranker = _FakeReranker()
    runtime = _runtime(
        tmp_path, stage_remaining=0.001, embedder=embedder, reranker=reranker
    )
    with pytest.raises(LiveBudgetRefused, match="stage_remaining_insufficient"):
        _run_pilot(tmp_path, pilot_dataset, runtime)
    assert not (tmp_path / "run" / "index").exists()
    assert embedder.calls == 0
    assert reranker.calls == 0


# --------------------------------------------------------------------------- #
# fail closed / 零重试
# --------------------------------------------------------------------------- #


def test_live_provider_error_fails_closed_without_retry(tmp_path, pilot_dataset) -> None:
    reranker = _FakeReranker(fail=True)
    result = _run_pilot(
        tmp_path,
        pilot_dataset,
        _runtime(tmp_path, embedder=_FakeEmbedder(), reranker=reranker),
    )

    assert result.aborted is True
    assert reranker.calls == 1  # 零重试：失败后不再调用
    assert len(result.cases) == 10
    first, *rest = result.cases
    assert first["status"] == "error"
    assert first["error"]["code"] == "rerank_error"
    assert all(row["status"] == "error" for row in rest)
    assert all(row["error"]["code"] == "run_aborted_after_failure" for row in rest)
    assert result.summary["aborted"] is True
    assert result.summary["error_count"] == 10
    assert result.summary["status_counts"] == {"error": 10}
    assert result.summary["metrics"]["scored_count"] == 0


# --------------------------------------------------------------------------- #
# GO 绑定 / 运行时构造
# --------------------------------------------------------------------------- #


def _write_ledger(path: Path) -> str:
    path.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": 0.03}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_budget(path: Path, *, total: float = 20.0, stage_limit: float = 3.0) -> None:
    path.write_text(
        json.dumps(
            {
                "limit_cny": total,
                "historical_conservative_accounted_cny": 0.03,
                "stages": {"P1-RETRIEVAL": stage_limit},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_go(path: Path, *, ledger_sha: str, embedding_model: str = "text-embedding-v4") -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "document": "S2-LIVE-GO",
        "stage": "P1-RETRIEVAL",
        "authorization": "UNIT-TEST-MOCK-GO",
        "issued_by": "pytest",
        "nonce": "unit-test-nonce-0123456789",
        "issued_utc": (now - timedelta(minutes=5)).isoformat(),
        "expires_utc": (now + timedelta(hours=1)).isoformat(),
        "budget_ledger_sha256": ledger_sha,
        "scope": {
            "services": ["rag"],
            "stage_limits_cny": {"P1-RETRIEVAL": 3.0},
            "max_requests": 1000,
            "max_request_cny": 0.05,
            "bindings": {
                "rag": {
                    "base_url_host": "dashscope.aliyuncs.com",
                    "embedding_provider": "bailian",
                    "embedding_model": embedding_model,
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
            },
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _isolated_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **go_overrides):
    ledger = tmp_path / "ledger.jsonl"
    budget = tmp_path / "budget.json"
    go = tmp_path / "go.json"
    sha = _write_ledger(ledger)
    _write_budget(budget)
    _write_go(go, ledger_sha=sha, **go_overrides)
    monkeypatch.setattr(live_authorization, "SHARED_LEDGER_PATH", ledger)
    monkeypatch.setattr(live_authorization, "SHARED_BUDGET_PATH", budget)
    monkeypatch.setattr(live_authorization, "PRODUCT_GO_PATH", go)
    monkeypatch.setenv("MKTKB_PROJECT_TOTAL_LIMIT_CNY", "20.0")
    return {"MKTKB_PROJECT_TOTAL_LIMIT_CNY": "20.0", "DASHSCOPE_API_KEY": "unit-test-key"}


def test_live_runtime_rejects_go_binding_mismatch(tmp_path, monkeypatch) -> None:
    env = _isolated_gate(tmp_path, monkeypatch, embedding_model="text-embedding-v3")
    with pytest.raises(LiveConfigError, match="GO 供应商绑定不匹配"):
        load_live_runtime(
            data_dir=tmp_path / "index",
            business_date="2026-10-28",
            environ=env,
            env_file=None,
        )


def test_live_runtime_builds_only_embedding_rerank_config(tmp_path, monkeypatch) -> None:
    env = _isolated_gate(tmp_path, monkeypatch)
    runtime = load_live_runtime(
        data_dir=tmp_path / "index",
        business_date="2026-10-28",
        run_id="unit-live-run",
        environ=env,
        env_file=None,
    )
    assert runtime.config.provider_mode == "live"
    assert runtime.config.chat_model == ""
    assert runtime.config.chat_api_key == ""
    assert runtime.config.chat_base_url == ""
    assert runtime.config.max_retries == 0
    assert runtime.config.require_zero_retries is True
    assert "unit-test-key" not in repr(runtime)
    assert runtime.authorization is not None
    assert runtime.authorization.ledger_sha256 == hashlib.sha256(
        (tmp_path / "ledger.jsonl").read_bytes()
    ).hexdigest()


def test_httpx_proxy_env_removes_bracketed_ipv6_and_restores(monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1,[::1]")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1,::1,[::1]")
    with httpx_compatible_proxy_env():
        assert "[" not in os.environ["NO_PROXY"]
        assert "::1" not in os.environ["NO_PROXY"].split(",")
    assert os.environ["NO_PROXY"] == "localhost,127.0.0.1,::1,[::1]"


def test_live_runtime_requires_project_total_limit_env(tmp_path, monkeypatch) -> None:
    env = _isolated_gate(tmp_path, monkeypatch)
    env = dict(env)
    env.pop("MKTKB_PROJECT_TOTAL_LIMIT_CNY", None)
    monkeypatch.delenv("MKTKB_PROJECT_TOTAL_LIMIT_CNY", raising=False)
    with pytest.raises(LiveConfigError, match="MKTKB_PROJECT_TOTAL_LIMIT_CNY"):
        load_live_runtime(
            data_dir=tmp_path / "index",
            business_date="2026-10-28",
            environ=env,
            env_file=None,
        )
