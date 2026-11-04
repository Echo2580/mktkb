"""真实企业语料的离线端到端：海报位置、黄金高度、乌龙茶NKA组合价、全部枚举、追问与通知时效。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mktkb.ingestion.parsers import ParseServices, parse_document
from mktkb.rag import DocumentSpec, RagConfig, RagIndex, adapt_parsed_unit

CORPUS = Path(__file__).resolve().parents[3] / "corpus" / "enterprise-20261101"


def _add(index: RagIndex, code: str, rel: str, kind: str, title: str, *, effective_from: str | None = None):
    path = CORPUS / rel
    assert path.exists(), path
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    doc = DocumentSpec(
        doc_id=code,
        logical_id=code,
        source_path=rel,
        title=title,
        file_kind=kind,
        version_id=f"{code}-v1",
        version_label="当前",
        sha256=sha,
        business_date="2026-10-28",
        effective_from=effective_from,
    )
    units = [
        adapt_parsed_unit(unit, doc=doc, unit_id=f"{code}-{ordinal}", ordinal=ordinal)
        for ordinal, unit in enumerate(parse_document(path, kind, ParseServices()))
    ]
    result = index.add_document(doc, units)
    assert result["embedding_error"] is None, result
    return result


@pytest.fixture
def enterprise_index(tmp_path: Path):
    index = RagIndex(
        tmp_path / "enterprise.sqlite3",
        config=RagConfig(data_dir=tmp_path, business_date="2026-10-28", page_size=10, top_k=5),
    )
    try:
        _add(index, "E11", "excel/E11_终端物料位置表_当前V2.xlsx", "xlsx", "终端物料位置表")
        _add(index, "E03", "excel/E03_2026年Q4渠道价目表.xlsx", "xlsx", "2026年Q4渠道价目表")
        _add(index, "W01", "word/W01_终端陈列与生动化管理制度_V2.1.docx", "docx", "终端陈列与生动化管理制度")
        _add(
            index,
            "P03",
            "pdf/P03_关于部分门店物料临时调整存放位置的通知.pdf",
            "pdf",
            "关于部分门店物料临时调整存放位置的通知",
            effective_from="2026-11-20",
        )
        yield index
    finally:
        index.close()


def test_poster_position_and_golden_display_height(enterprise_index):
    poster = enterprise_index.ask(
        "滨江店的宣传海报（标识：QF01）放在哪里？", user_id="u", conversation_id="c1"
    )
    assert poster.kind == "answer"
    assert "店内外侧" in poster.text
    assert poster.citations and poster.citations[0].doc_id == "E11"
    assert poster.citations[0].locator["row"] == 7

    height = enterprise_index.ask("黄金陈列位的高度区间是多少？", user_id="u", conversation_id="c2")
    assert height.kind == "answer"
    assert "1.2" in height.text and "1.5" in height.text
    assert height.citations and "W01" in height.citations[0].doc_id
    assert "第七条" in height.text


def test_oolong_nka_combo_price_and_follow_up(enterprise_index):
    answer = enterprise_index.ask(
        "启沣乌龙茶（900ml PET）在NKA卖场的组合价是多少？", user_id="u", conversation_id="c3"
    )
    assert answer.kind == "answer"
    assert "5" in answer.text and "2瓶" in answer.text
    assert "4.5" not in answer.text
    assert answer.citations and answer.citations[0].doc_id == "E03"
    assert answer.citations[0].locator["sheet"] == "NKA卖场"
    assert answer.citations[0].locator["row"] == 10

    follow_up = enterprise_index.ask("那这个组合价什么时候失效？", user_id="u", conversation_id="c3")
    assert follow_up.kind == "answer"
    assert "2026-11-15" in follow_up.text
    assert follow_up.state["product"] == "启沣乌龙茶（900ml PET） 900ml×12瓶/箱"


def test_enumeration_all_reports_total_and_no_fake_top_k(enterprise_index):
    answer = enterprise_index.ask("把NKA卖场乌龙茶的组合价全部列出来", user_id="u", conversation_id="c4")
    assert answer.kind == "answer"
    assert answer.diagnostics["total"] >= 1
    assert answer.diagnostics["returned"] == answer.diagnostics["total"]
    assert answer.diagnostics["has_more"] is False
    assert "共 " in answer.text and "已显示全部" in answer.text
    assert "5" in answer.text and "2瓶" in answer.text


def test_ambiguous_then_clarification_answer(enterprise_index):
    first = enterprise_index.ask("宣传海报在哪里？", user_id="u", conversation_id="c5")
    assert first.kind == "ambiguous"
    assert "滨江店" in first.text and "鹿鸣路店" in first.text
    second = enterprise_index.ask("滨江店", user_id="u", conversation_id="c5")
    assert second.kind == "answer"
    assert "店内外侧" in second.text


def test_current_vs_notice_future(enterprise_index):
    current = enterprise_index.ask(
        "滨江店的宣传海报（标识：QF01）现在放在哪里？", user_id="u", conversation_id="c6"
    )
    assert current.kind == "answer"
    assert "店内外侧" in current.text

    notice = enterprise_index.ask(
        "按《关于部分门店物料临时调整存放位置的通知》，滨江店的宣传海报（标识：QF01）（本次调整）调整后位于哪里？",
        user_id="u",
        conversation_id="c6",
    )
    assert notice.kind == "answer"
    assert notice.reason is None
    assert "E区5号货架第二层" in notice.text
    assert notice.citations and notice.citations[0].doc_id == "P03"


def test_unknown_store_is_refused(enterprise_index):
    answer = enterprise_index.ask("城南店的联系人是谁？", user_id="u", conversation_id="c7")
    assert answer.kind == "no_answer"
    assert answer.reason == "UNKNOWN_STORE"
    assert "城南店" in answer.text
