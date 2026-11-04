"""R3 预算闸门回归：固定账本、官方最大值预留、chat 禁发、全调用计划、双实体完整性。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex
from mktkb.rag.budget import BudgetLedger
from mktkb.rag.errors import BudgetPricingUnknown, EmbeddingResponseError, RequestLimitExceeded
from mktkb.rag.providers import BailianEmbeddingProvider, DeepSeekChatProvider

ROOT = Path(__file__).resolve().parents[3]


def _tools():
    import importlib.util

    spec = importlib.util.spec_from_file_location("rag_experiment_r3", ROOT / "tools" / "rag_experiment.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _budget(tmp_path: Path, *, max_requests: int = 100) -> BudgetLedger:
    (tmp_path / "budget.json").write_text(json.dumps({"limit_cny": 10.0, "stages": {"S1-DEV": 3.0}}), encoding="utf-8")
    (tmp_path / "ledger.jsonl").write_text("", encoding="utf-8")
    return BudgetLedger(
        tmp_path / "ledger.jsonl",
        tmp_path / "budget.json",
        stage="S1-DEV",
        stage_limit_cny=3.0,
        max_requests=max_requests,
    )


def _doc(code: str, title: str) -> DocumentSpec:
    return DocumentSpec(
        doc_id=code, logical_id=code, source_path=f"{code}.xlsx", title=title,
        file_kind="xlsx", version_id=f"{code}-v1", version_label="当前",
        sha256=hashlib.sha256(code.encode()).hexdigest(), business_date="2026-10-28",
    )


def _row(doc: DocumentSpec, fields: dict, ordinal: int = 0) -> AtomicUnit:
    return AtomicUnit(
        unit_id=f"{doc.doc_id}-{ordinal}", doc_id=doc.doc_id, version_id=doc.version_id,
        kind="table_row", ordinal=ordinal, unit_key=f"r{ordinal}",
        text="；".join(f"{k}: {v}" for k, v in fields.items()), fields=fields, sheet="表",
        locator={"sheet": "表", "row": ordinal + 2, "header_row": 1, "row_number": ordinal + 2},
        header_row=1, row_number=ordinal + 2,
    )


def test_budget_ledger_defaults_to_zero_requests(tmp_path) -> None:
    (tmp_path / "budget.json").write_text(json.dumps({"limit_cny": 10.0, "stages": {"S1-DEV": 3.0}}), encoding="utf-8")
    (tmp_path / "ledger.jsonl").write_text("", encoding="utf-8")
    ledger = BudgetLedger(tmp_path / "ledger.jsonl", tmp_path / "budget.json", stage="S1-DEV")
    with pytest.raises(RequestLimitExceeded):
        ledger.reserve(kind="test", provider="mock", model="m", max_cny=0.01, request_sha256="a" * 64)


def test_go_rejects_any_ledger_path_other_than_fixed_shared(tmp_path, monkeypatch) -> None:
    tools = _tools()
    go = tmp_path / "S1-LIVE-GO.md"
    monkeypatch.setattr(tools, "GO_PATH", go)
    payload = {
        "document": "S1-LIVE-GO", "stage": "S1-DEV", "authorization": "REAL-STAGE",
        "issued_by": "PM", "nonce": "n" * 24,
        "issued_utc": "2026-11-02T00:00:00+08:00", "expires_utc": "2099-01-01T00:00:00+08:00",
        "budget_ledger_sha256": "0" * 64,
        "budget_ledger_path": str(tmp_path / "ledger.jsonl"),
        "scope": {"max_documents": 1, "max_requests": 2, "max_questions": 1, "stage_limit_cny": 3.0},
    }
    go.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit):
        tools._check_go_file()


def test_embedding_reserves_official_request_maximum(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"data": [{"embedding": [0.0] * 1024, "index": 0}], "usage": {"total_tokens": 10}})

    config = RagConfig(provider_mode="live", embedding_api_key="k" * 20)
    ledger = _budget(tmp_path)
    provider = BailianEmbeddingProvider(config, budget=ledger, transport=httpx.MockTransport(handler))
    try:
        provider.embed(["hello"])
    finally:
        provider.close()
    assert calls["n"] == 1
    events = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    reserved = [e for e in events if e.get("event") == "reserved"]
    assert reserved and reserved[0]["reserve_cny"] == pytest.approx(10 * 8192 * 0.5 / 1_000_000)


def test_chat_blocks_without_official_input_output_limits(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={})

    config = RagConfig(
        provider_mode="live",
        chat_model="deepseek-chat",
        chat_base_url="https://example.invalid",
        chat_api_key="sk-test",
        chat_input_price_per_million_cny=1.0,
        chat_output_price_per_million_cny=2.0,
        max_output_tokens=10,
    )
    with pytest.raises(BudgetPricingUnknown):
        DeepSeekChatProvider(config, transport=httpx.MockTransport(handler), require_budget=False)
    assert calls["n"] == 0


def test_embedding_usage_above_official_max_is_not_accepted(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"data": [{"embedding": [0.0] * 1024, "index": 0}],
                                         "usage": {"total_tokens": 90000}})

    config = RagConfig(provider_mode="live", embedding_api_key="k" * 20)
    provider = BailianEmbeddingProvider(config, budget=_budget(tmp_path), transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(EmbeddingResponseError):
            provider.embed(["hello"])
    finally:
        provider.close()
    assert calls["n"] == 1


def test_plan_contains_all_call_faces_and_stage_block(tmp_path) -> None:
    """R5 起 executable 只认结构上界；观测口径（requests_planned）不再当上界。"""
    tools = _tools()
    doc = _doc("E11", "终端物料位置表")
    units = [_row(doc, {"门店": "滨江店", "物品": "端架侧板", "数量": 2}, i) for i in range(121)]
    plan = tools.build_index_plan(
        [(doc, units)],
        config=RagConfig(data_dir=tmp_path, business_date="2026-10-28", max_retries=0),
        max_requests=16,
        max_questions=2,
        stage_remaining_cny=0.80,
        query_embedding_requests=0,
        rerank_requests=2,
    )
    assert plan["embedding_build_requests"] == 13
    assert plan["requests_planned"] == 15  # 观测口径：13 建库 + 0 查询 + 2 重排
    assert plan["total_upper_cny"] == pytest.approx(0.58048)
    # 结构上界仍包含每问 1 次查询 embedding（没有被运行时关闭）⇒ 17 > 16，不可执行
    assert plan["requests_structural_upper"] == 17
    assert plan["executable"] is False
    assert any("REQUEST_LIMIT:17>16" in x for x in plan["blocked_reasons"])
    disabled = tools.build_index_plan(
        [(doc, units)],
        config=RagConfig(
            data_dir=tmp_path, business_date="2026-10-28", max_retries=0,
            disable_query_embedding=True,
        ),
        max_requests=16,
        max_questions=2,
        stage_remaining_cny=0.80,
        rerank_requests=2,
    )
    assert disabled["requests_structural_upper"] == 15
    assert disabled["executable"] is True
    over = tools.build_index_plan(
        [(doc, units)],
        config=RagConfig(
            data_dir=tmp_path, business_date="2026-10-28", max_retries=0,
            disable_query_embedding=True,
        ),
        max_requests=16,
        max_questions=2,
        stage_remaining_cny=0.10,
        rerank_requests=2,
    )
    assert over["executable"] is False and any("STAGE_BALANCE" in x for x in over["blocked_reasons"])


def test_two_store_enumeration_reports_missing_entity(tmp_path) -> None:
    index = RagIndex(tmp_path / "two.sqlite3", config=RagConfig(data_dir=tmp_path, business_date="2026-10-28", top_k=5))
    doc = _doc("T", "端架台账")
    index.add_document(doc, [_row(doc, {"门店": "滨江店", "物品": "端架侧板", "数量": 2})])
    try:
        answer = index.ask("把滨江店和和悦广场店的端架侧板数量都列出来", user_id="u", conversation_id="two")
        assert answer.kind == "answer"
        assert "和悦广场店" in answer.text
        assert "未在资料中找到" in answer.text
        assert "已显示全部" not in answer.text
    finally:
        index.close()


