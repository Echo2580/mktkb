"""R2 返工回归：字节 token 上界、请求硬上限、计划、E01 多字段、缺资料/敏感资料、单位派生。"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from mktkb.ingestion.parsers import ParseServices, parse_document
from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex, adapt_parsed_unit
from mktkb.rag.budget import BudgetLedger
from mktkb.rag.errors import EmbeddingResponseError, RequestLimitExceeded
from mktkb.rag.providers import BailianEmbeddingProvider


ROOT = Path(__file__).resolve().parents[3]


def _tools():
    import importlib.util

    spec = importlib.util.spec_from_file_location("rag_experiment_r2", ROOT / "tools" / "rag_experiment.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _budget(tmp_path: Path, *, max_requests: int | None = None) -> BudgetLedger:
    (tmp_path / "budget.json").write_text(json.dumps({"limit_cny": 10.0, "stages": {"S1-DEV": 3.0}}), encoding="utf-8")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    return BudgetLedger(ledger, tmp_path / "budget.json", stage="S1-DEV", stage_limit_cny=3.0, max_requests=(1000 if max_requests is None else max_requests))


def _doc(code: str, title: str, *, path: str | None = None) -> DocumentSpec:
    return DocumentSpec(
        doc_id=code,
        logical_id=code,
        source_path=path or f"{code}.xlsx",
        title=title,
        file_kind="xlsx",
        version_id=f"{code}-v1",
        version_label="当前",
        sha256=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        business_date="2026-10-28",
    )


def _unit(doc: DocumentSpec, fields: dict, *, ordinal: int = 0) -> AtomicUnit:
    return AtomicUnit(
        unit_id=f"{doc.doc_id}-{ordinal}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=ordinal,
        unit_key=f"r{ordinal}",
        text="；".join(f"{key}: {value}" for key, value in fields.items()),
        fields=fields,
        sheet="表",
        locator={"sheet": "表", "row": ordinal + 2, "header_row": 1, "row_number": ordinal + 2},
        header_row=1,
        row_number=ordinal + 2,
    )


def test_embedding_rejects_byte_upper_over_official_single_limit(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"data": [{"embedding": [0.0] * 1024, "index": 0}], "usage": {"total_tokens": 1}})

    provider = BailianEmbeddingProvider(
        RagConfig(provider_mode="live", embedding_api_key="k" * 20),
        transport=httpx.MockTransport(handler),
        require_budget=False,
    )
    try:
        with pytest.raises(EmbeddingResponseError):
            provider.embed(["中" * 3000])
    finally:
        provider.close()
    assert calls["n"] == 0


def test_request_hard_cap_default_deny(tmp_path) -> None:
    ledger = _budget(tmp_path, max_requests=1)
    ledger.reserve(kind="test", provider="mock", model="m", max_cny=0.01, request_sha256="a" * 64)
    with pytest.raises(RequestLimitExceeded):
        ledger.reserve(kind="test", provider="mock", model="m", max_cny=0.01, request_sha256="b" * 64)


def test_index_plan_audits_batches_cost_and_request_count(tmp_path) -> None:
    tools = _tools()
    doc = _doc("P", "道具单价表")
    units = [_unit(doc, {"标识": "P-1", "门店": "滨江店", "物品": "帐篷", "单价": 480, "计价单位": "顶"})]
    plan = tools.build_index_plan(
        [(doc, units)],
        config=RagConfig(data_dir=tmp_path, business_date="2026-10-28"),
        max_requests=1,
        max_questions=1,
        stage_remaining_cny=3.0,
    )
    assert plan["documents"] == 1
    assert plan["chunks"] >= 1
    assert plan["embedding_batches"] >= 1
    assert plan["rerank_requests_planned"] == 1
    assert plan["total_upper_cny"] > 0
    assert "within_stage_balance" in plan


def test_e01_multi_field_identifier_suffix_and_unit(tmp_path) -> None:
    index = RagIndex(tmp_path / "e01.sqlite3", config=RagConfig(data_dir=tmp_path, business_date="2026-10-28", top_k=5))
    path = ROOT / "corpus" / "enterprise-20261101" / "excel" / "E01_物料主数据表.xlsx"
    doc = _doc("E01", "物料主数据表", path=str(path))
    doc = dataclasses.replace(doc, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    units = [adapt_parsed_unit(unit, doc=doc, unit_id=f"E01-{i}", ordinal=i)
             for i, unit in enumerate(parse_document(path, "xlsx", ParseServices()))]
    index.add_document(doc, units)
    try:
        answer = index.ask("宣传海报（WL-2026-0001）的单价和规格是什么？", user_id="u", conversation_id="e01")
        assert answer.kind == "answer"
        assert "2.6" in answer.text and "A2 铜版纸" in answer.text
        assert "每张" in answer.text
        assert {fact.field_role for fact in answer.facts} == {"price", "spec"}
    finally:
        index.close()


def test_missing_document_and_docx_enumeration_fail_explicitly(tmp_path) -> None:
    index = RagIndex(tmp_path / "docs.sqlite3", config=RagConfig(data_dir=tmp_path, business_date="2026-10-28", top_k=5))
    source = _doc("SRC", "道具单价表")
    index.add_document(source, [_unit(source, {"标识": "S-1", "门店": "滨江店", "物品": "帐篷", "单价": 480})])
    sensitive = _doc("X", "导购薪酬与手机号清单")
    index.add_document(sensitive, [AtomicUnit(
        unit_id="X-1", doc_id="X", version_id="X-v1", kind="paragraph", ordinal=0, unit_key="p1",
        text="工资 99999 元，手机号 13800000000", fields={}, sheet=None,
        locator={"paragraph": 1}, header_row=None, row_number=None,
    )])
    try:
        missing = index.ask("把不存在的仓库台账里滨江店的全部流水列出来", user_id="u", conversation_id="m1")
        assert missing.kind == "no_answer" and missing.reason == "DOCUMENT_NOT_FOUND"
        sensitive_answer = index.ask(
            "把导购薪酬与手机号清单里滨江店的全部内容列出来", user_id="u", conversation_id="m2"
        )
        # R6-3-4：请求里点名门店且总数为 0 时改为点名无记录（敏感样本仍不得泄露内容）。
        assert sensitive_answer.reason in ("NO_ENUMERABLE_RECORD", "NO_RECORD_FOR_ENTITY")
        assert "13800000000" not in sensitive_answer.text
    finally:
        index.close()


def test_units_are_derived_from_fields_not_fixed_whitelist(tmp_path) -> None:
    index = RagIndex(tmp_path / "units.sqlite3", config=RagConfig(data_dir=tmp_path, business_date="2026-10-28", top_k=5))
    doc = _doc("UN", "道具单价表")
    rows = [
        {"标识": "U-1", "门店": "滨江店", "物品": "户外帐篷", "单价": 480, "计价单位": "顶"},
        {"标识": "U-2", "门店": "滨江店", "物品": "团扇", "单价": 3.5, "计价单位": "把"},
        {"标识": "U-3", "门店": "滨江店", "物品": "导购补贴", "单价": 120, "计价单位": "每人"},
    ]
    index.add_document(doc, [_unit(doc, row, ordinal=i) for i, row in enumerate(rows)])
    try:
        for item, value, unit in (("户外帐篷", "480", "每顶"), ("团扇", "3.5", "每把"), ("导购补贴", "120", "每人")):
            answer = index.ask(f"滨江店{item}的单价是多少", user_id="u", conversation_id="u-" + item)
            assert answer.kind == "answer", (item, answer.reason, answer.text)
            assert value in answer.text and unit in answer.text
    finally:
        index.close()

