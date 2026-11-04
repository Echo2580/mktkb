"""R1 返工回归：独立验收 D-09/D-01/D-03/D-02/D-11/D-04/D-05/D-06/D-07/D-08/D-16/D-10。"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from mktkb.rag import DocumentSpec, RagConfig, RagIndex, QueryState
from mktkb.rag.budget import BudgetLedger
from mktkb.rag.errors import RerankError, StaleSource
from mktkb.rag.facts import FactValidator
from mktkb.rag.providers import BailianRerankProvider
from mktkb.rag.query import build_lexicon, parse_query


def _tools():
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("rag_experiment_r1", root / "tools" / "rag_experiment.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_go_gate_rejects_existing_documents_and_structured_weak_files(tmp_path, monkeypatch) -> None:
    module = _tools()
    for relative in (
        "docs/evidence/LOCAL-R1-20261101/S1-DEV/delivery.md",
        "docs/evidence/LOCAL-R1-20261101/S1-DEV/interfaces.md",
        "docs/evidence/LOCAL-R1-20261101/PM/S1-DEV-task.md",
    ):
        with pytest.raises(SystemExit):
            module._check_go_file(module.ROOT / relative)

    weak = tmp_path / "weak-go.md"
    weak.write_text("S1-LIVE-GO\nS1-DEV\n", encoding="utf-8")
    monkeypatch.setattr(module, "GO_PATH", weak)
    with pytest.raises(SystemExit):
        module._check_go_file(weak)

    ledger = module.ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
    payload = {
        "document": "S1-LIVE-GO",
        "stage": "S1-DEV",
        "authorization": "REAL-STAGE",
        "issued_by": "test-manager",
        "nonce": "0123456789abcdef0123456789abcdef",
        "issued_utc": "2026-11-02T00:00:00+08:00",
        "expires_utc": "2099-01-01T00:00:00+08:00",
        "budget_ledger_sha256": hashlib.sha256(ledger.read_bytes()).hexdigest(),
        "scope": {
            "max_documents": 2,
            "max_requests": 2,
            "max_questions": 1,
            "stage_limit_cny": 3.0,
        },
    }
    weak.write_text(json.dumps(payload), encoding="utf-8")
    assert module._check_go_file(weak)["authorization"] == "REAL-STAGE"


def test_channel_spacing_and_composite_channel_are_normalized(rag_index, add_records) -> None:
    doc = DocumentSpec(
        doc_id="E03",
        logical_id="E03",
        source_path="e03.xlsx",
        title="2026年Q4渠道价目表",
        file_kind="xlsx",
        version_id="E03-v1",
        version_label="当前",
        sha256="d" * 64,
    )
    add_records(
        [
            {
                "标识": "PX-1",
                "品名规格": "启沣乌龙茶（900ml PET） 900ml×12瓶/箱",
                "适用渠道": "NKA卖场|LKA连锁|CVS便利店",
                "价格类型": "组合价",
                "价格(元)": 5,
                "计价单位": "2瓶",
                "生效日期": "2026-10-01",
                "失效日期": "2026-11-15",
            }
        ],
        doc=doc,
    )
    for question in (
        "启沣乌龙茶 900ml 在 NKA 卖场那个组合价怎么算",
        "乌龙茶在 NKA 卖场的组合价",
        "在NKA 卖场的组合价",
        "NKA卖场的组合价是多少",
    ):
        answer = rag_index.ask(question, user_id="u", conversation_id="ch-" + str(abs(hash(question)) % 1000))
        assert answer.reason != "CHANNEL_AMBIGUOUS", (question, answer.reason)
    answer = rag_index.ask(
        "启沣乌龙茶 900ml 在 NKA 卖场那个组合价怎么算", user_id="u", conversation_id="ch-ok"
    )
    assert answer.kind == "answer" and "5" in answer.text


def test_e05_aliases_named_enumeration_and_sensitive_exclusion(rag_index, add_records) -> None:
    e05 = DocumentSpec(
        doc_id="E05",
        logical_id="E05",
        source_path="e05.xlsx",
        title="领用核销台账",
        file_kind="xlsx",
        version_id="E05-v1",
        version_label="当前",
        sha256="e" * 64,
    )
    add_records(
        [
            {"标识": "LY-1", "门店名称": "滨江店", "物料名称": "DM单", "实发数量": 10, "领用日期": "2026-09-01"},
            {"标识": "LY-2", "门店名称": "滨江店", "物料名称": "海报", "实发数量": 20, "领用日期": "2026-09-02"},
            {"标识": "LY-3", "门店名称": "城西店", "物料名称": "展架", "实发数量": 30, "领用日期": "2026-09-03"},
        ],
        doc=e05,
    )
    x04 = DocumentSpec(
        doc_id="X04",
        logical_id="X04",
        source_path="x04.docx",
        title="导购薪酬与手机号清单",
        file_kind="docx",
        version_id="X04-v1",
        version_label="当前",
        sha256="f" * 64,
    )
    add_records(
        [],
        doc=x04,
        text_units=[
            {
                "text": "导购薪酬与个人手机号清单，敏感样本，工资 99999 元，手机号 13800000000。",
                "kind": "paragraph",
                "locator": {"paragraph": 1},
            }
        ],
    )
    answer = rag_index.ask(
        "把 E05 领用核销台账里滨江店的全部流水列出来", user_id="u", conversation_id="enum-e05"
    )
    assert answer.kind == "answer"
    assert answer.diagnostics["total"] == 2
    assert {citation.doc_id for citation in answer.citations} == {"E05"}
    assert "99999" not in answer.text and "13800000000" not in answer.text


def test_rerank_counts_query_per_candidate_and_enforces_limits(tmp_path) -> None:
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"limit_cny": 10.0, "stages": {"S1-DEV": 3.0}}), encoding="utf-8")
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_text("", encoding="utf-8")
    ledger = BudgetLedger(ledger_path, budget, stage="S1-DEV", stage_limit_cny=3.0, max_requests=1000)
    config = RagConfig(
        provider_mode="live",
        rerank_api_key="k" * 24,
        rerank_base_url="https://example.invalid",
        rerank_max_documents=50,
        rerank_max_single_tokens=4000,
        rerank_max_request_tokens=30000,
        max_request_cny=0.10,
    )
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"output": {"results": [{"index": 0, "relevance_score": 0.9}]},
                                         "usage": {"total_tokens": 2}, "request_id": "r"})

    provider = BailianRerankProvider(config, budget=ledger, transport=httpx.MockTransport(handler))
    try:
        query = "柠檬茶 NKA 档期特价"
        docs = ["价" * 1000, "价" * 1000]
        provider.rerank(query, docs, top_n=1)
        events = [json.loads(line) for line in ledger.ledger_path.read_text(encoding="utf-8").splitlines()]
        reserved = [event for event in events if event.get("event") == "reserved"][-1]
        assert reserved["reserve_cny"] >= 30000 * 0.8 / 1e6

        before = calls["count"]
        with pytest.raises(RerankError):
            provider.rerank(query, ["价" * 4001])
        assert calls["count"] == before
        with pytest.raises(RerankError):
            provider.rerank(query, ["价" * 1500] * 50)
        assert calls["count"] == before
    finally:
        provider.close()


def test_record_effective_window_and_status_conflict(rag_index, add_records) -> None:
    doc = DocumentSpec(
        doc_id="E03",
        logical_id="E03",
        source_path="e03.xlsx",
        title="2026年Q4渠道价目表",
        file_kind="xlsx",
        version_id="E03-v1",
        version_label="当前",
        sha256="b" * 64,
    )
    add_records(
        [
            {
                "标识": "PX-1",
                "品名规格": "启沣柠檬茶（500ml PET）",
                "适用渠道": "NKA卖场",
                "价格类型": "档期特价",
                "价格(元)": 2.99,
                "计价单位": "瓶",
                "生效日期": "2026-10-01",
                "失效日期": "2026-10-21",
                "状态": "生效中",
            }
        ],
        doc=doc,
    )
    current = rag_index.ask(
        "柠檬茶500ml在NKA卖场现在的档期特价是多少", user_id="u", conversation_id="date-now"
    )
    assert current.kind == "no_answer"
    assert current.reason == "EFFECTIVE_WINDOW_CONFLICT"
    assert any(word in current.text for word in ("过期", "矛盾", "核实"))
    historical = rag_index.ask(
        "2026年10月10日柠檬茶500ml在NKA卖场的档期特价是多少", user_id="u", conversation_id="date-old"
    )
    assert historical.kind == "answer" and "2.99" in historical.text


def test_wrong_entity_and_per_bottle_are_not_rejected(rag_index, add_records) -> None:
    doc = DocumentSpec(
        doc_id="E03",
        logical_id="E03",
        source_path="e03.xlsx",
        title="2026年Q4渠道价目表",
        file_kind="xlsx",
        version_id="E03-v1",
        version_label="当前",
        sha256="c" * 64,
    )
    add_records(
        [
            {"标识": "P1", "品名规格": "启沣柠檬茶（500ml PET）", "适用渠道": "CVS便利店",
             "价格类型": "会员价", "价格(元)": 3.2, "计价单位": "瓶"},
            {"标识": "P2", "品名规格": "启沣乌龙茶（900ml PET）", "适用渠道": "CVS便利店",
             "价格类型": "会员价", "价格(元)": 5.5, "计价单位": "瓶"},
            {"标识": "P3", "品名规格": "启沣柠檬茶（500ml PET）", "适用渠道": "NKA卖场",
             "价格类型": "建议零售价", "价格(元)": 3.5, "计价单位": "瓶"},
        ],
        doc=doc,
    )
    oolong = rag_index.ask(
        "乌龙茶900ml在CVS便利店的会员价是多少", user_id="u", conversation_id="wrong-entity"
    )
    assert oolong.kind == "answer" and "5.5" in oolong.text and "3.2" not in oolong.text
    lemon = rag_index.ask(
        "柠檬茶500ml在NKA卖场的建议零售价是多少", user_id="u", conversation_id="per-bottle"
    )
    assert lemon.kind == "answer" and "3.5" in lemon.text and "每瓶" in lemon.text


def test_interrogative_is_not_an_unknown_store(rag_index, add_records) -> None:
    add_records([{"标识": "QF01", "门店": "滨江店", "物品": "宣传海报", "位置": "店内外侧"}])
    answer = rag_index.ask(
        "店内外侧这个位置对应哪家店的什么物料", user_id="u", conversation_id="interrogative"
    )
    assert answer.reason != "UNKNOWN_STORE"
    assert answer.kind in ("clarification", "ambiguous", "no_answer")


def test_fact_doc_and_unit_binding_are_enforced(rag_index, add_records) -> None:
    add_records([{"标识": "QF01", "门店": "滨江店", "物品": "宣传海报", "位置": "店内外侧"}])
    question = "滨江店的宣传海报放在哪里"
    answer = rag_index.ask(question, user_id="u", conversation_id="binding")
    assert answer.kind == "answer" and answer.facts
    lexicon = build_lexicon(rag_index.lexicon_data())
    plan = parse_query(question, previous=QueryState(), lexicon=lexicon, business_date="2026-10-28")
    validator = FactValidator(rag_index, plan, lexicon)
    fact = answer.facts[0]
    with pytest.raises(StaleSource):
        validator.validate_fact(dataclasses.replace(fact, doc_id="OTHER"))
    with pytest.raises(StaleSource):
        validator.validate_fact(dataclasses.replace(fact, source_unit_id="NOT-EXIST"))


def test_legacy_comparison_rebuilds_from_empty_database(tmp_path) -> None:
    tools = _tools()
    db_path = tmp_path / "legacy.sqlite3"
    db_path.write_bytes(b"stale-not-a-database")
    legacy, stats = tools.build_legacy([], db_path=db_path)
    try:
        assert stats["documents"] == 0
        assert db_path.stat().st_size > 0
    finally:
        legacy.close()


def test_cli_has_no_dev_defaults() -> None:
    source = (Path(__file__).resolve().parents[3] / "tools" / "rag_experiment.py").read_text(encoding="utf-8")
    assert 'S1-DEV" / "questions.json' not in source
    assert 'default=str(ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "S1-DEV")' not in source

