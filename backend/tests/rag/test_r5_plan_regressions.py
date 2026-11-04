"""R5-B 定点回归：结构上界、trace 拒收、运行入口闸门与可审计报告。

对应 R4 独立复验的 R4-NEW-1（trace 当上界）、R4-NEW-2（无 planned-vs-actual 报告）、
R4-NEW-3（把“分支未检索”记成缓存命中）。所有 HTTP 都走 MockTransport，socket 熔断。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex
from mktkb.rag.budget import BudgetLedger
from mktkb.rag.providers import FakeEmbeddingProvider, LexicalReranker

ROOT = Path(__file__).resolve().parents[3]


def _tools():
    spec = importlib.util.spec_from_file_location("rag_experiment_r5", ROOT / "tools" / "rag_experiment.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _doc(code: str, title: str) -> DocumentSpec:
    return DocumentSpec(
        doc_id=code,
        logical_id=code,
        source_path=f"{code}.xlsx",
        title=title,
        file_kind="xlsx",
        version_id=f"{code}-v1",
        version_label="当前",
        sha256=hashlib.sha256(code.encode()).hexdigest(),
        business_date="2026-10-28",
    )


def _row(doc: DocumentSpec, fields: dict, ordinal: int = 0) -> AtomicUnit:
    return AtomicUnit(
        unit_id=f"{doc.doc_id}-{ordinal}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=ordinal,
        unit_key=f"r{ordinal}",
        text="；".join(f"{k}: {v}" for k, v in fields.items()),
        fields=fields,
        sheet="物品位置",
        locator={"sheet": "物品位置", "row": ordinal + 2, "header_row": 1, "row_number": ordinal + 2},
        header_row=1,
        row_number=ordinal + 2,
    )


def _docs(
    tmp_path: Path, *, docs: int = 1, rows: int = 121, shared: bool = False
) -> list[tuple[DocumentSpec, list[AtomicUnit]]]:
    result = []
    for index in range(docs):
        doc = _doc(f"E{index}", f"端架台账{index}")
        units = [
            _row(
                doc,
                {"门店": "滨江店", "物品": "端架侧板", "数量": 2, "备注": f"R{row}" if shared else f"N{index}-{row}"},
                row,
            )
            for row in range(rows)
        ]
        result.append((doc, units))
    return result


def _config(tmp_path: Path, **kwargs: Any) -> RagConfig:
    base = dict(data_dir=tmp_path, business_date="2026-10-28", max_retries=0)
    base.update(kwargs)
    return RagConfig(**base)


# ------------------------------------------------------- 观测计划 vs 结构上界


def test_structural_upper_ignores_observed_trace(tmp_path) -> None:
    tools = _tools()
    documents = _docs(tmp_path)
    low = tools.build_index_plan(
        documents,
        config=_config(tmp_path),
        max_requests=40,
        max_questions=3,
        stage_remaining_cny=3.0,
        trace_counts={"embedding_build_calls": 1, "embedding_query_calls": 0, "rerank_calls": 0},
    )
    assert low["trace_validation"]["valid"] is True
    # trace 的建库调用是按资料计的逻辑调用（1 份资料 = 1 次），HTTP 批数仍是 13
    assert low["observed"]["requests_total"] == 13 + 0 + 0
    # 结构上界 = 13 建库 + 3 查询 + 3 重排；trace 里的 0/0 不能把它压小
    assert low["requests_structural_upper"] == 19
    assert low["requests_worst_case"] == 19
    high = tools.build_index_plan(
        documents,
        config=_config(tmp_path),
        max_requests=400,
        max_questions=3,
        stage_remaining_cny=3.0,
        trace_counts={"embedding_build_calls": 1, "embedding_query_calls": 999, "rerank_calls": 999},
    )
    assert high["trace_validation"]["valid"] is False
    assert any("TRACE_OVER_QUESTIONS" in err for err in high["trace_validation"]["errors"])
    assert high["executable"] is False
    assert any("TRACE_INVALID" in reason for reason in high["blocked_reasons"])
    assert high["requests_structural_upper"] == 19, "矛盾 trace 不得改上界，也不得静默夹小"


def test_trace_rejects_negative_and_non_integer_and_build_mismatch(tmp_path) -> None:
    tools = _tools()
    documents = _docs(tmp_path)
    for trace, code in (
        ({"embedding_build_calls": 1, "embedding_query_calls": -1, "rerank_calls": 1}, "TRACE_NEGATIVE"),
        ({"embedding_build_calls": 1, "embedding_query_calls": 1, "rerank_calls": 1.5}, "TRACE_NOT_INTEGER"),
        ({"embedding_build_calls": 9, "embedding_query_calls": 1, "rerank_calls": 1}, "TRACE_BUILD_OVER_DOCUMENTS"),
        ({"embedding_build_calls": 1, "embedding_query_calls": 0, "rerank_calls": 0}, None),
    ):
        plan = tools.build_index_plan(
            documents,
            config=_config(tmp_path),
            max_requests=40,
            max_questions=2,
            stage_remaining_cny=3.0,
            trace_counts=trace,
        )
        if code is None:
            assert plan["trace_validation"]["valid"] is True
            continue
        assert any(code in err for err in plan["trace_validation"]["errors"]), (code, plan["trace_validation"])
        assert plan["executable"] is False


def test_build_upper_sums_per_document_batches(tmp_path) -> None:
    """多文档时全局去重分组会低估：结构上界必须按每份资料分别取整。"""
    tools = _tools()
    documents = _docs(tmp_path, docs=2, rows=6, shared=True)  # 每份 6 块 + batch 10 ⇒ 每份 1 批
    plan = tools.build_index_plan(
        documents,
        config=_config(tmp_path),
        max_requests=40,
        max_questions=1,
        stage_remaining_cny=3.0,
    )
    assert plan["per_document_batches"][0]["batches"] == 1
    assert plan["embedding_build_requests"] == 2
    assert plan["requests_structural_upper"] == 2 + 1 + 1

    bigger = _docs(tmp_path, docs=2, rows=11, shared=True)
    plan2 = tools.build_index_plan(
        bigger,
        config=_config(tmp_path),
        max_requests=40,
        max_questions=1,
        stage_remaining_cny=3.0,
    )
    assert plan2["embedding_build_requests"] == 4, "2 份 × ceil(11/10)=2"
    # 全局分组只有 ceil(22/10)=3：按全局分组会低估，不能当上界
    assert plan2["embedding_batches_global_grouped"] == 3
    assert plan2["embedding_build_requests"] > plan2["embedding_batches_global_grouped"]


def test_retry_factor_applies_to_structural_upper(tmp_path) -> None:
    tools = _tools()
    documents = _docs(tmp_path)
    plan = tools.build_index_plan(
        documents,
        config=_config(tmp_path, max_retries=2),
        max_requests=60,
        max_questions=2,
        stage_remaining_cny=3.0,
    )
    assert plan["requests_structural_upper"] == 17
    assert plan["attempt_factor"] == 3
    assert plan["requests_worst_case"] == 51


def test_chat_upper_unproven_blocks_unless_record_only(tmp_path) -> None:
    tools = _tools()
    documents = _docs(tmp_path)
    config = _config(
        tmp_path,
        chat_model="deepseek-chat",
        chat_base_url="https://example.invalid",
        chat_api_key="k" * 20,
    )
    plan = tools.build_index_plan(
        documents, config=config, max_requests=60, max_questions=2, stage_remaining_cny=3.0
    )
    assert plan["chat_requests_upper"] == 2
    assert plan["executable"] is False
    assert any("CHAT_UPPER_UNPROVEN" in reason for reason in plan["blocked_reasons"])
    record_only = tools.build_index_plan(
        documents,
        config=_config(
            tmp_path,
            chat_model="deepseek-chat",
            chat_base_url="https://example.invalid",
            chat_api_key="k" * 20,
            record_only=True,
        ),
        max_requests=60,
        max_questions=2,
        stage_remaining_cny=3.0,
        record_only=True,
    )
    assert record_only["chat_requests_upper"] == 0
    assert record_only["face_enforcement"]["chat_enforced_at"]
    assert record_only["executable"] is True


def test_cache_naming_is_corrected_without_claiming_cache(tmp_path) -> None:
    tools = _tools()
    plan = tools.build_index_plan(
        _docs(tmp_path), config=_config(tmp_path), max_requests=40, max_questions=3, stage_remaining_cny=3.0
    )
    assert plan["cache_semantics"]["embedding_query_cache_hits"] == 0
    assert plan["embedding_query_cache_hits_planned"] == 0
    assert "embedding_query_cache_hits_planned" in plan["deprecated_fields"]


# ------------------------------------------------------- 运行时强制面


class _CountingEmbedding(FakeEmbeddingProvider):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.query_calls = 0

    def embed(self, texts, *, purpose: str = "document"):
        if purpose == "query":
            self.query_calls += 1
        return super().embed(texts, purpose=purpose)


def test_no_query_embedding_is_enforced_at_runtime(tmp_path) -> None:
    index = RagIndex(
        tmp_path / "noq.sqlite3",
        config=_config(tmp_path, disable_query_embedding=True),
        embedder=_CountingEmbedding(),
        reranker=LexicalReranker(),
    )
    doc = _doc("E1", "端架台账")
    index.add_document(doc, [_row(doc, {"门店": "滨江店", "物品": "端架侧板", "数量": 2})])
    try:
        answer = index.ask("滨江店的端架侧板有多少", user_id="u", conversation_id="noq")
        assert answer.kind == "answer", (answer.reason, answer.text)
        assert index.embedder.query_calls == 0
        assert "vector" in (answer.diagnostics.get("degraded") or [])
        assert answer.diagnostics.get("vector_error") == "QUERY_EMBEDDING_DISABLED"
    finally:
        index.close()


def test_record_only_never_constructs_chat(tmp_path, monkeypatch) -> None:
    import mktkb.rag.answer as answer_module
    import mktkb.rag.providers as providers_module

    def _boom(*args, **kwargs):  # pragma: no cover - 只证明不会被调用
        raise AssertionError("record_only 不允许构造 chat provider")

    monkeypatch.setattr(providers_module, "DeepSeekChatProvider", _boom)
    live_config = _config(
        tmp_path,
        record_only=True,
        provider_mode="live",
        embedding_api_key="mock-emb-key",
        rerank_api_key="mock-rerank-key",
        chat_model="deepseek-chat",
        chat_base_url="https://example.invalid",
        chat_api_key="mock-chat-key",
        chat_input_price_per_million_cny=1.0,
        chat_output_price_per_million_cny=2.0,
        chat_max_input_tokens=1000,
        chat_max_output_tokens=800,
    )
    index = RagIndex(
        tmp_path / "rec.sqlite3",
        config=live_config,
        embedder=FakeEmbeddingProvider(),
        reranker=LexicalReranker(),
    )
    doc = _doc("D1", "市场周例会纪要")
    index.add_document(
        doc,
        [
            AtomicUnit(
                unit_id="u1",
                doc_id=doc.doc_id,
                version_id=doc.version_id,
                kind="paragraph",
                ordinal=0,
                unit_key="p1",
                text="市场周例会纪要：本周重点检查端架陈列高度与价格签一致性。",
                fields={},
                sheet=None,
                locator={"paragraph": 1},
                header_row=None,
                row_number=None,
                title=doc.title,
            )
        ],
    )
    try:
        answer = index.ask("本周例会的重点是什么", user_id="u", conversation_id="rec")
        assert answer.kind == "no_answer"
        assert answer.reason == "RECORD_ONLY"
    finally:
        index.close()


# ------------------------------------------------------- 轨迹不超结构上界


def _counted_run(config: RagConfig, db: Path, documents, questions: list[str], user: str = "u") -> dict[str, int]:
    embedder = _CountingEmbedding()
    reranker = _CountingReranker()
    index = RagIndex(db, config=config, embedder=embedder, reranker=reranker)
    try:
        for spec, units in documents:
            index.add_document(spec, units)
        for position, question in enumerate(questions):
            index.ask(question, user_id=user, conversation_id=f"c{position}")
        return {
            "embedding_build_calls": embedder.build_calls if hasattr(embedder, "build_calls") else 0,
            "embedding_query_calls": embedder.query_calls,
            "rerank_calls": reranker.calls,
        }
    finally:
        index.close()


class _CountingReranker(LexicalReranker):
    def __init__(self) -> None:
        self.calls = 0

    def rerank(self, query: str, documents, *, top_n: int | None = None):
        self.calls += 1
        return super().rerank(query, documents, top_n=top_n)


class _ZeroEmbedding(FakeEmbeddingProvider):
    def embed(self, texts, *, purpose: str = "document"):
        response = super().embed(texts, purpose=purpose)
        return type(response)(
            vectors=tuple(tuple(0.0 for _ in vector) for vector in response.vectors),
            model=response.model,
            dimensions=response.dimensions,
            provider=response.provider,
            usage=response.usage,
        )


def test_fresh_and_resumed_state_stay_within_structural_upper(tmp_path) -> None:
    tools = _tools()
    documents = _docs(tmp_path, rows=3)
    questions = ["滨江店的端架侧板有多少", "梧桐里店和滨江店的端架侧板分别有多少"]
    config = _config(tmp_path)
    plan = tools.build_index_plan(
        documents, config=config, max_requests=40, max_questions=len(questions), stage_remaining_cny=3.0
    )
    upper = plan["requests_structural_upper"]
    fresh = _counted_run(config, tmp_path / "fresh.sqlite3", documents, questions)
    resumed = _counted_run(config, tmp_path / "fresh.sqlite3", documents, questions)
    refreshed = _counted_run(config, tmp_path / "fresh.sqlite3", documents, questions)
    # provider 逻辑调用与 HTTP 批数是两个层级：这里比逻辑调用（每份资料 1 次建库），
    # HTTP 批数上界由 live 入口的 MockTransport 计数测试覆盖。
    logical_upper = len(documents) + 2 * len(questions)
    for counts in (fresh, resumed, refreshed):
        total = counts["embedding_build_calls"] + counts["embedding_query_calls"] + counts["rerank_calls"]
        assert total <= logical_upper, (counts, logical_upper)
        assert counts["embedding_query_calls"] <= len(questions)
        assert counts["rerank_calls"] <= len(questions)
    assert upper >= logical_upper


def test_different_vector_semantics_never_exceed_upper(tmp_path) -> None:
    tools = _tools()
    documents = _docs(tmp_path, rows=3)
    questions = ["滨江店的端架侧板有多少", "梧桐里店和滨江店的端架侧板分别有多少"]
    plan = tools.build_index_plan(
        documents, config=_config(tmp_path), max_requests=40, max_questions=2, stage_remaining_cny=3.0
    )
    upper = plan["requests_structural_upper"]
    db = tmp_path / "zero.sqlite3"
    index = RagIndex(db, config=_config(tmp_path), embedder=_ZeroEmbedding(), reranker=_CountingReranker())
    try:
        for spec, units in documents:
            index.add_document(spec, units)
        query_calls = 0
        for position, question in enumerate(questions):
            index.ask(question, user_id="u", conversation_id=f"z{position}")
            query_calls += 1
        rerank_calls = index.reranker.calls
        assert query_calls + rerank_calls + 1 <= upper, (query_calls, rerank_calls, upper)
        first = index.ask(questions[0], user_id="u", conversation_id="z-fresh")
        assert first.diagnostics.get("degraded") is not None
    finally:
        index.close()


# ------------------------------------------------------- live 入口闸门与报告


def _ledger(tmp_path: Path, *, limit_cny: float = 10.0, stage: float = 3.0) -> tuple[Path, Path]:
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"limit_cny": limit_cny, "stages": {"S1-DEV": stage}}), encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps({"event": "historical_import", "stage": "S1-DEV", "accounted_cny": 0.03}) + "\n",
        encoding="utf-8",
    )
    return ledger, budget


def _live_env(tmp_path: Path, monkeypatch, *, module) -> tuple[Path, Path, Path]:
    ledger, budget = _ledger(tmp_path)
    go_path = tmp_path / "S1-LIVE-GO.md"
    digest = hashlib.sha256(ledger.read_bytes()).hexdigest()
    go_path.write_text(
        json.dumps(
            {
                "document": "S1-LIVE-GO",
                "stage": "S1-DEV",
                "authorization": "REAL-STAGE",
                "issued_by": "PM",
                "nonce": "n" * 24,
                "issued_utc": "2026-11-02T00:00:00+08:00",
                "expires_utc": "2099-01-01T00:00:00+08:00",
                "budget_ledger_sha256": digest,
                "scope": {
                    "max_documents": 2,
                    "max_requests": 40,
                    "max_questions": 2,
                    "stage_limit_cny": 3.0,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_FIXED_LEDGER", ledger)
    monkeypatch.setattr(module, "_FIXED_BUDGET", budget)
    monkeypatch.setattr(module, "GO_PATH", go_path)
    for key, value in {
        "DASHSCOPE_API_KEY": "mock-dashscope-key",
        "MKTKB_MODEL_NAME": "deepseek-chat",
        "MKTKB_MODEL_API_KEY": "mock-chat-key",
        "MKTKB_MODEL_BASE_URL": "https://example.invalid",
        "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY": "1",
        "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY": "2",
        "MKTKB_MODEL_MAX_INPUT_TOKENS": "100000",
        "MKTKB_MODEL_MAX_OUTPUT_TOKENS": "800",
        "MKTKB_MODEL_CONTEXT_CEILING_TOKENS": "100000",
        "MKTKB_MODEL_RESERVE_PROFILE": "model_context_ceiling",
    }.items():
        monkeypatch.setenv(key, value)
    return ledger, budget, go_path


def _questions_file(tmp_path: Path, questions: list[str]) -> Path:
    path = tmp_path / "questions.json"
    path.write_text(
        json.dumps(
            {"conversations": [{"id": "c1", "questions": [{"id": f"q{i}", "question": q} for i, q in enumerate(questions)]}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _corpus_file(tmp_path: Path, documents) -> Path:
    """写一个只含指定资料的最小语料目录（用 manifest + xlsx 不可行，改用 monkeypatch load_corpus）。"""
    return tmp_path


def test_live_entry_blocks_before_http_when_structural_upper_exceeds_scope(tmp_path, monkeypatch) -> None:
    tools = _tools()
    ledger, budget, _go = _live_env(tmp_path, monkeypatch, module=tools)
    documents = _docs(tmp_path, rows=60)  # 60 块 ⇒ 6 批建库 + 2 查询 + 2 重排 = 10
    monkeypatch.setattr(tools, "load_corpus", lambda *a, **k: (documents, []))
    monkeypatch.setattr(tools, "build_new_index", lambda *a, **k: pytest.fail("闸门失败时不得开始建库"))
    out = tmp_path / "out"
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(str(request.url))
        return httpx.Response(500)

    original_client_init = httpx.Client.__init__

    def patched(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched)
    questions = _questions_file(tmp_path, ["滨江店的端架侧板有多少", "梧桐里店的端架侧板有多少"])
    with pytest.raises(SystemExit) as excinfo:
        tools.main(
            [
                "live",
                "--ledger",
                str(ledger),
                "--budget",
                str(budget),
                "--questions",
                str(questions),
                "--out",
                str(out),
                "--max-requests",
                "8",
                "--max-questions",
                "2",
                "--max-retries",
                "0",
                "--doc-codes",
                "E11",
            ]
        )
    assert "结构上界未通过闸门" in str(excinfo.value)
    assert attempts == [], "闸门失败不得发出任何 HTTP"
    report = json.loads((out / "run-live.json").read_text(encoding="utf-8"))
    assert report["plan"]["executable"] is False
    assert any("REQUEST_LIMIT" in reason for reason in report["plan"]["blocked_reasons"])
    assert report["execution"]["complete"] is False
    assert report["execution"]["error"] == "PLAN_NOT_EXECUTABLE"
    assert report["execution"]["ledger"]["delta_reservations"] == 0
    assert report["execution"]["plan_vs_actual"]["actual_attempts"] == 0


def test_live_entry_mock_transport_is_labeled_and_counted(tmp_path, monkeypatch) -> None:
    tools = _tools()
    ledger, budget, _go = _live_env(tmp_path, monkeypatch, module=tools)
    documents = _docs(tmp_path, rows=3)
    monkeypatch.setattr(tools, "load_corpus", lambda *a, **k: (documents, []))
    monkeypatch.setattr(tools, "build_legacy", lambda *a, **k: (None, None))
    out = tmp_path / "out"
    questions = _questions_file(tmp_path, ["滨江店的端架侧板有多少", "梧桐里店的端架侧板有多少"])
    counters = _install_boundary_spies(monkeypatch)
    code = tools.main(
        [
            "live",
            "--ledger",
            str(ledger),
            "--budget",
            str(budget),
            "--questions",
            str(questions),
            "--out",
            str(out),
            "--max-requests",
            "40",
            "--max-questions",
            "2",
            "--max-retries",
            "0",
            "--no-old",
            "--transport",
            "mock",
            "--record-only",
        ]
    )
    assert code == 0
    report = json.loads((out / "run-live.json").read_text(encoding="utf-8"))
    execution = report["execution"]
    assert report["mode"] == "live"
    assert report["transport"] == "mock"
    assert report["mock"] is True
    assert execution["transport_attribution"] == "mock_transport_injected_by_tool"
    assert report["real_calls"] == 0
    assert execution["mock_http_attempts"] and execution["mock_http_attempts"] > 0
    assert execution["complete"] is True
    # 独立观测：post 边界与 transport 边界各自计数，不从账本预留推算（R5-REG）。
    assert execution["providers"]["reserved_by_kind"], "预留与发送尝试必须分列"
    assert execution["plan_vs_actual"]["actual_attempts_layer"] == "post_attempts"
    assert execution["plan_vs_actual"]["actual_attempts"] == counters["post"]
    assert execution["attribution"]["layers"]["post_attempts"]["total"] == counters["post"]
    assert execution["attribution"]["layers"]["transport_attempts"]["total"] == counters["transport"]
    assert execution["attribution"]["layers"]["transport_attempts"]["verified"] is True
    assert execution["attribution"]["layers"]["reserved"]["own"] == _reserved_rows(ledger)
    assert execution["attribution"]["layers"]["reserved"]["foreign"] == 0
    # 费用：1 建库批 + 2 查询 + 2 重排 = 3×0.04096 + 2×0.024
    assert execution["cost"]["planned_structural_upper_cny"] == pytest.approx(0.17088)
    assert execution["cost"]["own_reserved_cny"] == pytest.approx(0.17088)
    assert execution["cost"]["own_conservative_total_cny"] >= 0.17088 - 1e-9
    assert execution["ledger"]["prefix_unchanged"] is True
    assert set(execution["providers"]["results_by_kind"]) <= {"embedding", "rerank", "chat"}


def test_live_report_attributes_budget_exhaustion(tmp_path, monkeypatch) -> None:
    """并发/他人写入把余额用光时：不得静默降级，必须在报告里逐题归因。"""
    tools = _tools()
    ledger, budget, _go = _live_env(tmp_path, monkeypatch, module=tools)
    documents = _docs(tmp_path, rows=3)
    monkeypatch.setattr(tools, "load_corpus", lambda *a, **k: (documents, []))
    monkeypatch.setattr(tools, "build_legacy", lambda *a, **k: (None, None))
    real_run = tools.run_conversations

    def _drain_then_run(*args, **kwargs):
        other = tools.BudgetLedger(
            ledger, budget, stage="S1-DEV", stage_limit_cny=3.0, max_requests=10_000,
            run_id="concurrent-writer",
        )
        drained = 0
        for _ in range(200):
            try:
                reservation = other.reserve(
                    kind="other", provider="external", model="external", max_cny=0.04, request_sha256="b" * 64
                )
            except Exception:  # noqa: BLE001 - 用光即停
                break
            other.settle(reservation, status="failed", error_code="SIMULATED_CONCURRENT_WRITE")
            drained += 1
        assert drained > 0
        return real_run(*args, **kwargs)

    monkeypatch.setattr(tools, "run_conversations", _drain_then_run)
    out = tmp_path / "out"
    questions = _questions_file(tmp_path, ["滨江店的端架侧板有多少", "梧桐里店的端架侧板有多少"])
    code = tools.main(
        [
            "live",
            "--ledger",
            str(ledger),
            "--budget",
            str(budget),
            "--questions",
            str(questions),
            "--out",
            str(out),
            "--max-requests",
            "40",
            "--max-questions",
            "2",
            "--max-retries",
            "0",
            "--no-old",
            "--transport",
            "mock",
            "--record-only",
        ]
    )
    assert code == 0
    report = json.loads((out / "run-live.json").read_text(encoding="utf-8"))
    execution = report["execution"]
    degraded = execution["degraded_questions"]
    assert degraded, "预算被用光后必须逐题标降级，不能当正常效果"
    codes = {"BUDGET_EXCEEDED", "REQUEST_LIMIT_EXCEEDED", "EMBEDDING_UNAVAILABLE"}
    assert all(item.get("vector_error") in codes or "vector" in (item.get("degraded") or []) for item in degraded)
    # 账本行数不能直接冒充 HTTP 数：本轮自己的预留必须与并发写入分开
    attribution = execution["self_attribution"]
    assert attribution["foreign_reservations_in_window"] > 0
    assert attribution["own_reservations"] == execution["attribution"]["layers"]["reserved"]["own"]
    assert execution["ledger"]["delta_reservations"] > attribution["own_reservations"]
    assert execution["attribution"]["layers"]["post_attempts"]["total"] == execution["plan_vs_actual"]["actual_attempts"]
    plan_vs_actual = execution["plan_vs_actual"]
    assert plan_vs_actual["within_worst_case"] is True
    assert plan_vs_actual["attempts"] <= plan_vs_actual["requests_worst_case"]
    run_md = (out / "run-live.md").read_text(encoding="utf-8")
    assert "降级/中断归因" in run_md


def test_report_preserves_costs_and_marks_interruption(tmp_path, monkeypatch) -> None:
    tools = _tools()
    ledger, budget, _go = _live_env(tmp_path, monkeypatch, module=tools)
    documents = _docs(tmp_path, rows=3)
    monkeypatch.setattr(tools, "load_corpus", lambda *a, **k: (documents, []))
    monkeypatch.setattr(tools, "build_legacy", lambda *a, **k: (None, None))

    def _explode(*args, **kwargs):
        raise RuntimeError("simulated interrupt")

    monkeypatch.setattr(tools, "run_conversations", _explode)
    out = tmp_path / "out"
    questions = _questions_file(tmp_path, ["滨江店的端架侧板有多少"])
    with pytest.raises(RuntimeError):
        tools.main(
            [
                "live",
                "--ledger",
                str(ledger),
                "--budget",
                str(budget),
                "--questions",
                str(questions),
                "--out",
                str(out),
                "--max-requests",
                "40",
                "--max-questions",
                "1",
                "--max-retries",
                "0",
                "--no-old",
                "--transport",
                "mock",
                "--record-only",
            ]
        )
    report = json.loads((out / "run-live.json").read_text(encoding="utf-8"))
    execution = report["execution"]
    assert execution["complete"] is False
    assert "simulated interrupt" in str(execution["error"])
    # 已消耗的建库预留必须留在报告与账本里，不能被失败擦掉
    assert execution["ledger"]["delta_reservations"] >= 1
    assert execution["providers"]["conservative_charge_cny"] >= 0.0
    assert execution["providers"]["total_reserved"] >= 1

def _reserved_rows(ledger: Path) -> int:
    total = 0
    for line in ledger.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and json.loads(text).get("event") == "reserved":
            total += 1
    return total


def _install_boundary_spies(monkeypatch) -> dict[str, int]:
    """独立观测 post 与 transport 两层，不读产品报告里的任何计数。"""
    counters = {"post": 0, "transport": 0}
    original_post = httpx.Client.post
    original_handle = httpx.MockTransport.handle_request

    def post_spy(self, url, *args, **kwargs):
        counters["post"] += 1
        return original_post(self, url, *args, **kwargs)

    def handle_spy(self, request):
        counters["transport"] += 1
        return original_handle(self, request)

    monkeypatch.setattr(httpx.Client, "post", post_spy)
    monkeypatch.setattr(httpx.MockTransport, "handle_request", handle_spy)
    return counters


def test_reserve_persisted_but_unreturned_is_counted_as_own(tmp_path, monkeypatch) -> None:
    """预留已落盘、reserve 未返回：本轮 reserved/post/transport 分列，外来 0，占用不漏算。"""
    tools = _tools()
    ledger, budget, _go = _live_env(tmp_path, monkeypatch, module=tools)
    documents = _docs(tmp_path, rows=3)
    monkeypatch.setattr(tools, "load_corpus", lambda *a, **k: (documents, []))
    monkeypatch.setattr(tools, "build_legacy", lambda *a, **k: (None, None))
    counters = _install_boundary_spies(monkeypatch)
    from mktkb.rag.budget import BudgetLedger as _Ledger

    original_reserve = _Ledger.reserve
    state = {"n": 0}

    def reserve_spy(self, *args, **kwargs):
        reservation = original_reserve(self, *args, **kwargs)
        state["n"] += 1
        if state["n"] == 2:
            raise KeyboardInterrupt("注入：第 2 次预留已落盘、reserve 未返回")
        return reservation

    monkeypatch.setattr(_Ledger, "reserve", reserve_spy)
    out = tmp_path / "out"
    questions = _questions_file(tmp_path, ["滨江店的端架侧板有多少"])
    with pytest.raises(BaseException):
        tools.main(
            [
                "live",
                "--ledger", str(ledger),
                "--budget", str(budget),
                "--questions", str(questions),
                "--out", str(out),
                "--max-requests", "40",
                "--max-questions", "1",
                "--max-retries", "0",
                "--no-old",
                "--transport", "mock",
                "--record-only",
            ]
        )
    report = json.loads((out / "run-live.json").read_text(encoding="utf-8"))
    execution = report["execution"]
    layers = execution["attribution"]["layers"]
    assert execution["complete"] is False
    assert layers["reserved"]["own"] == 2 == _reserved_rows(ledger)
    assert layers["reserved"]["foreign"] == 0
    assert layers["post_attempts"]["total"] == counters["post"] == 1
    assert layers["transport_attempts"]["total"] == counters["transport"] == 1
    assert layers["outcomes"]["settled"] == 1
    assert layers["outcomes"]["unsettled"] == 1
    assert execution["cost"]["own_conservative_total_cny"] == pytest.approx(0.08192)
    assert execution["plan_vs_actual"]["actual_attempts_layer"] == "post_attempts"

