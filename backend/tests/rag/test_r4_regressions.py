"""R4 定点回归：limit/实际 turn、plan 全调用面、配置可见性、多门店硬过滤与披露。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex

ROOT = Path(__file__).resolve().parents[3]


def _tools():
    import importlib.util

    spec = importlib.util.spec_from_file_location("rag_experiment_r4", ROOT / "tools" / "rag_experiment.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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


def test_limit_is_conversation_count_but_plan_counts_all_turns() -> None:
    tools = _tools()
    conversations = [
        {"id": "a", "questions": [{"id": "a1", "question": "q1"}, {"id": "a2", "question": "q2"}]},
        {"id": "b", "questions": [{"id": "b1", "question": "q3"}]},
        {"id": "c", "questions": [{"id": "c1", "question": "q4"}, {"id": "c2", "question": "q5"}]},
    ]
    selected, count = tools.select_conversations(conversations, limit_conversations=2)
    assert [item["id"] for item in selected] == ["a", "b"]
    assert count == 3
    selected2, count2 = tools.select_conversations(conversations, limit_conversations=2, max_questions=2)
    assert count2 == 2
    assert [q["id"] for item in selected2 for q in item["questions"]] == ["a1", "a2"]


def test_plan_retry_and_existing_cumulative_request_accounting(tmp_path) -> None:
    tools = _tools()
    doc = _doc("E11", "终端物料位置表")
    units = [_row(doc, {"门店": "滨江店", "物品": "端架侧板", "数量": 2}, i) for i in range(121)]
    plan = tools.build_index_plan(
        [(doc, units)],
        config=RagConfig(data_dir=tmp_path, business_date="2026-10-28", max_retries=2),
        max_requests=20,
        max_questions=1,
        stage_remaining_cny=3.0,
        query_embedding_requests=1,
        rerank_requests=1,
        question_texts=["q1"],
        existing_requests=3,
    )
    assert plan["requests_planned"] == 15
    assert plan["requests_worst_case"] == 45
    assert plan["remaining_requests"] == 17
    assert plan["within_request_limit"] is False
    assert plan["failure_retention_upper_cny"] == pytest.approx((14 * 0.04096 + 0.024) * 3)


def test_plan_can_use_chat_env_without_http(monkeypatch, tmp_path) -> None:
    for key, value in {
        "MKTKB_MODEL_NAME": "deepseek-chat",
        "MKTKB_MODEL_API_KEY": "sk-test",
        "MKTKB_MODEL_BASE_URL": "https://example.invalid",
        "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY": "1",
        "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY": "2",
        "MKTKB_MODEL_MAX_INPUT_TOKENS": "1000",
        "MKTKB_MODEL_MAX_OUTPUT_TOKENS": "100",
    }.items():
        monkeypatch.setenv(key, value)
    tools = _tools()
    config = tools.RagConfig.from_env(provider_mode="offline", data_dir=tmp_path,
                                      business_date="2026-10-28", stage_limit_cny=3.0)
    assert config.chat_max_input_tokens == 1000
    assert config.chat_max_output_tokens == 100
    doc = _doc("E11", "终端物料位置表")
    units = [_row(doc, {"门店": "滨江店", "物品": "端架侧板", "数量": 2}, i) for i in range(121)]
    plan = tools.build_index_plan(
        [(doc, units)], config=config, max_requests=30, max_questions=1,
        stage_remaining_cny=3.0, query_embedding_requests=1, rerank_requests=1,
        question_texts=["q1"], max_retries=0,
    )
    assert plan["chat_requests_planned"] == 1
    assert plan["chat_prices_and_limits_known"] is True
    assert plan["chat_upper_cny"] == pytest.approx((1000 * 1 + 100 * 2) / 1_000_000)


def test_plan_reports_chat_per_request_cap_without_relaxing_budget(tmp_path) -> None:
    tools = _tools()
    config = RagConfig(
        data_dir=tmp_path, business_date="2026-10-28", max_retries=0,
        chat_model="deepseek-chat", chat_input_price_per_million_cny=2.0,
        chat_output_price_per_million_cny=3.0, chat_max_input_tokens=128000,
        chat_max_output_tokens=8000, max_output_tokens=800,
    )
    doc = _doc("E11", "终端物料位置表")
    units = [_row(doc, {"门店": "滨江店", "物品": "端架侧板", "数量": 2}, i) for i in range(121)]
    plan = tools.build_index_plan(
        [(doc, units)], config=config, max_requests=30, max_questions=1,
        stage_remaining_cny=3.0, query_embedding_requests=0, rerank_requests=0,
        chat_requests=1, question_texts=["q1"],
    )
    assert plan["chat_request_upper_cny"] == pytest.approx((128000 * 2 + 8000 * 3) / 1_000_000)
    assert plan["executable"] is False
    assert any("CHAT_REQUEST_CAP" in reason for reason in plan["blocked_reasons"])


def test_multi_store_filters_exactly_and_discloses_missing(tmp_path) -> None:
    index = RagIndex(tmp_path / "multi.sqlite3", config=RagConfig(data_dir=tmp_path, business_date="2026-10-28", top_k=10))
    doc = _doc("M", "端架台账")
    rows = [
        {"门店": "滨江店", "物品": "端架侧板", "数量": 2},
        {"门店": "和悦广场店", "物品": "端架侧板", "数量": 3},
        {"门店": "梧桐里店", "物品": "端架侧板", "数量": 4},
    ]
    index.add_document(doc, [_row(doc, row, i) for i, row in enumerate(rows)])
    try:
        answer = index.ask(
            "把滨江店和和悦广场店的端架侧板数量都列出来", user_id="u", conversation_id="multi"
        )
        assert answer.kind == "answer", (answer.reason, answer.text)
        assert "滨江店" in answer.text and "和悦广场店" in answer.text
        assert "梧桐里店" not in answer.text
        assert "共 2 条" in answer.text
        assert "已显示全部" in answer.text
    finally:
        index.close()


def test_multi_store_unknown_is_disclosed_without_cross_entity(tmp_path) -> None:
    index = RagIndex(tmp_path / "unknown.sqlite3", config=RagConfig(data_dir=tmp_path, business_date="2026-10-28", top_k=10))
    doc = _doc("U", "端架台账")
    index.add_document(doc, [_row(doc, {"门店": "滨江店", "物品": "端架侧板", "数量": 2})])
    try:
        answer = index.ask(
            "把滨江店和和悦广场店的端架侧板数量都列出来", user_id="u", conversation_id="unknown"
        )
        assert answer.kind == "answer", (answer.reason, answer.text)
        assert "和悦广场店" in answer.text
        assert "未在资料中找到" in answer.text
        assert "已显示全部" not in answer.text
    finally:
        index.close()
