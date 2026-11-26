"""T207 独立验收探针（2026-11-16，独立验收角色编写，非开发自测）。

目的：不复用开发断言，自行构建合成索引与纯解析输入，独立核对本轮宣称的行为边界：

1. 安全策略优先：跨店×跨物品 + 受限联系字段必须拒答，而不是退化澄清。
2. 同一请求去掉联系字段仍按普通多目标走（不允许用安全拒答吞掉正常问题）。
3. 物品“全字段”枚举遇受限联系字段拒答；门店级电话、无联系字段的物品枚举仍可答。
4. 多店/多物品候选范围：目标内必须保留，目标外必须排除。
5. 跨轮：旧单目标不得收窄新多目标；明确换题后的裸物品追问要补门店；无换题的普通追问仍继承。
6. 标题编号前缀（D/V + 数字 + 下划线）精确解前缀，非前缀标题不被污染。

仅使用合成数据与离线 provider，不读取任何真实题面/答案/合同/密钥。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

import pytest

from mktkb.conversations.intent import EntityLexicon, parse_question
from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex
from mktkb.rag.query import Lexicon, _document_core, _match_document, parse_query


def _config(tmp_path: Path) -> RagConfig:
    return RagConfig(
        provider_mode="offline",
        data_dir=tmp_path,
        business_date="2026-10-28",
        chunk_max_chars=420,
        chunk_max_units=3,
        chunk_overlap_units=1,
        top_k=5,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
    )


def _doc(title: str = "合成资料") -> DocumentSpec:
    identifier = "D" + uuid.uuid4().hex[:8]
    return DocumentSpec(
        doc_id=identifier,
        logical_id=identifier,
        source_path="corpus/acceptance.xlsx",
        title=title,
        file_kind="xlsx",
        version_id="V-" + uuid.uuid4().hex,
        version_label="当前",
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )


def _unit(document: DocumentSpec, fields: Mapping[str, Any], ordinal: int) -> AtomicUnit:
    from mktkb.rag.chunking import effective_dates

    values = dict(fields)
    effective_from, effective_to = effective_dates(values)
    body = "；".join(f"{name}: {value}" for name, value in values.items())
    return AtomicUnit(
        unit_id=f"{document.doc_id}-{ordinal}-{uuid.uuid4().hex[:6]}",
        doc_id=document.doc_id,
        version_id=document.version_id,
        kind="table_row",
        ordinal=ordinal,
        unit_key=f"sheet:物品位置:row:{7 + ordinal}",
        text=body,
        fields=values,
        sheet="物品位置",
        locator={"sheet": "物品位置", "row": 7 + ordinal, "header_row": 6},
        header_row=6,
        row_number=7 + ordinal,
        title=document.title,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _index(tmp_path: Path, rows: Iterable[Mapping[str, Any]], *, title: str = "合成资料"):
    index = RagIndex(tmp_path / "rag.sqlite3", config=_config(tmp_path))
    document = _doc(title)
    index.add_document(document, [_unit(document, row, n) for n, row in enumerate(rows)], embed=True)
    return index


# ---------------------------------------------------------------- 安全策略优先


def test_security_refusal_precedes_cross_product_clarification(tmp_path: Path) -> None:
    index = _index(tmp_path, [
        {"门店": "北园店", "物品": "展板", "位置": "甲柜", "电话": "010-55550001"},
        {"门店": "南园店", "物品": "横幅", "位置": "乙柜", "电话": "010-55550002"},
    ])
    try:
        answer = index.ask("北园店和南园店的展板和横幅的位置及联系电话是多少？",
                           user_id="acc", conversation_id="acc-1")
        assert answer.kind == "no_answer", answer.kind
        assert answer.reason == "SECURITY_RESTRICTED_CONTACT", answer.reason
        assert not answer.citations
        for leaked in ("甲柜", "乙柜", "010-55550001", "010-55550002"):
            assert leaked not in answer.text
    finally:
        index.close()


def test_same_request_without_contact_is_not_turned_into_security_refusal(tmp_path: Path) -> None:
    index = _index(tmp_path, [
        {"门店": "北园店", "物品": "展板", "位置": "甲柜"},
        {"门店": "南园店", "物品": "横幅", "位置": "乙柜"},
    ])
    try:
        answer = index.ask("北园店和南园店的展板和横幅的位置分别在哪里？",
                           user_id="acc", conversation_id="acc-2")
        assert answer.reason != "SECURITY_RESTRICTED_CONTACT"
        # 交叉配对不明仍是普通澄清面（不是安全拒答，也不是错误作答）
        assert answer.kind in {"clarification", "no_answer"}, answer.kind
    finally:
        index.close()


def test_legacy_financial_and_unknown_store_branches_do_not_swallow_contact_policy(tmp_path: Path) -> None:
    lexicon = EntityLexicon(
        store_labels=("北园店",), item_labels=("展板",), identifier_labels=()
    )
    financial = parse_question("北园店展板的位置和联系电话，以及公司的营业收入是多少？", lexicon=lexicon)
    assert financial.security_refusal == "SECURITY_RESTRICTED_CONTACT"
    unknown_store = parse_question("南园店展板的位置和联系电话是多少？", lexicon=lexicon)
    assert unknown_store.security_refusal == "SECURITY_RESTRICTED_CONTACT"
    # 反例：不受限的未知门店仍走原有未知门店分支
    plain = parse_question("南园店展板在哪里？", lexicon=lexicon)
    assert plain.security_refusal is None
    assert plain.unknown_store


# ---------------------------------------------------------------- 全字段枚举边界


def test_item_all_fields_with_restricted_contact_refuses(tmp_path: Path) -> None:
    index = _index(tmp_path, [
        {"门店": "北园店", "物品": "展板", "位置": "甲柜", "电话": "010-55551234"},
    ])
    try:
        answer = index.ask("列出北园店展板的全部信息", user_id="acc", conversation_id="acc-3")
        assert answer.kind == "no_answer"
        assert answer.reason == "SECURITY_RESTRICTED_CONTACT"
        assert not answer.citations
        assert "010-55551234" not in answer.text
    finally:
        index.close()


def test_store_level_phone_without_item_still_answers(tmp_path: Path) -> None:
    index = _index(tmp_path, [{"门店": "北园店", "电话": "010-55551234"}])
    try:
        answer = index.ask("北园店的电话是多少？", user_id="acc", conversation_id="acc-4")
        assert answer.kind == "answer", (answer.kind, answer.reason)
        assert "010-55551234" in answer.text
    finally:
        index.close()


def test_item_enumeration_without_contact_still_answers(tmp_path: Path) -> None:
    index = _index(tmp_path, [{"门店": "北园店", "物品": "展板", "位置": "甲柜"}])
    try:
        answer = index.ask("列出北园店展板的全部信息", user_id="acc", conversation_id="acc-5")
        assert answer.kind == "answer", (answer.kind, answer.reason)
        assert "甲柜" in answer.text
    finally:
        index.close()


# ---------------------------------------------------------------- 目标范围


def test_multi_store_targets_kept_and_non_targets_dropped(tmp_path: Path) -> None:
    index = _index(tmp_path, [
        {"门店": "北园店", "物品": "展板", "位置": "甲柜"},
        {"门店": "南园店", "物品": "展板", "位置": "乙柜"},
        {"门店": "西园店", "物品": "展板", "位置": "丙柜"},
    ])
    try:
        answer = index.ask("北园店和南园店的展板分别在哪里？", user_id="acc", conversation_id="acc-6")
        assert "甲柜" in answer.text and "乙柜" in answer.text
        assert "丙柜" not in answer.text
    finally:
        index.close()


def test_multi_item_targets_kept_and_non_targets_dropped(tmp_path: Path) -> None:
    index = _index(tmp_path, [
        {"门店": "北园店", "物品": "展板", "位置": "甲柜"},
        {"门店": "北园店", "物品": "横幅", "位置": "乙柜"},
        {"门店": "北园店", "物品": "灯箱", "位置": "丙柜"},
    ])
    try:
        answer = index.ask("北园店的展板和横幅分别在哪里？", user_id="acc", conversation_id="acc-7")
        assert "甲柜" in answer.text and "乙柜" in answer.text
        assert "丙柜" not in answer.text
    finally:
        index.close()


def test_multi_store_candidate_filter_keeps_only_requested_stores() -> None:
    from types import SimpleNamespace

    from mktkb.rag.retrieval import _passes_filters

    lexicon = Lexicon(stores=("北园店", "南园店", "西园店"), items=("展板",), field_labels=("位置",))
    plan = parse_query("北园店和南园店的展板在哪里？", previous=None, lexicon=lexicon)
    inside = SimpleNamespace(doc_id="d", filters_norm={"store": "北园店", "item": "展板"},
                             effective_from=None, effective_to=None)
    outside = SimpleNamespace(doc_id="d", filters_norm={"store": "西园店", "item": "展板"},
                              effective_from=None, effective_to=None)
    assert _passes_filters(inside, plan)
    assert not _passes_filters(outside, plan)


# ---------------------------------------------------------------- 跨轮继承


def test_previous_single_item_does_not_narrow_new_multi_item() -> None:
    from mktkb.rag.types import QueryState

    lexicon = Lexicon(stores=("北园店",), items=("展板", "横幅"), field_labels=("位置",))
    previous = QueryState(store="北园店", stores=("北园店",), item="展板", items=("展板",),
                          identifier="P77", turn=1)
    plan = parse_query("北园店的展板和横幅在哪里？", previous=previous, lexicon=lexicon)
    assert set(plan.state.items) == {"展板", "横幅"}
    assert "item" not in plan.filters


def test_explicit_topic_switch_then_bare_item_asks_for_store(tmp_path: Path) -> None:
    lexicon = EntityLexicon(store_labels=("北园店", "南园店"), item_labels=("展板", "横幅"),
                            identifier_labels=())
    plan = parse_question(
        "横幅呢？",
        lexicon=lexicon,
        context_questions=("换个话题，采购流程有哪些步骤？",),
        context_entities={"store": "南园店"},
    )
    assert plan.clarification
    assert plan.intent is None


def test_ordinary_bare_followup_still_inherits_store() -> None:
    """反例：上一轮不是换题时，裸物品追问必须继续继承门店并作答，不能被新守卫打成澄清。"""
    lexicon = EntityLexicon(store_labels=("北园店", "南园店"), item_labels=("展板", "横幅"),
                            identifier_labels=())
    plan = parse_question(
        "横幅呢？",
        lexicon=lexicon,
        context_questions=("北园店展板放在哪里？",),
        context_entities={"store": "北园店"},
    )
    assert not plan.clarification, "普通追问被错误地要求补门店"
    assert plan.intent is not None
    assert plan.intent.entity_filters.get("store") == "北园店"


# ---------------------------------------------------------------- 标题前缀


def test_numbered_title_prefix_is_stripped_with_exact_scope() -> None:
    assert _document_core("D99_设备巡检表.xlsx") == "设备巡检表"
    assert _document_core("V01_设备巡检表.xlsx") == "设备巡检表"
    assert _document_core("设备巡检表") == "设备巡检表"
    # 非前缀位置或形态不同不得被改动
    assert _document_core("设备D01_巡检表") == "设备D01"
    assert _document_core("D1_设备巡检表") == "D1"
    assert _document_core("DX01_设备巡检表") == "DX01"


def test_numbered_title_still_matches_human_question() -> None:
    document = DocumentSpec(
        doc_id="synthetic-acc",
        logical_id="synthetic-acc",
        source_path="corpus/acceptance.xlsx",
        title="V07_设备巡检表.xlsx",
        file_kind="xlsx",
        version_id="V-acc",
        version_label="当前",
        sha256="0" * 64,
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    lexicon = Lexicon(documents=(document,))
    assert _match_document("设备巡检表在哪里", lexicon) == (document, ())
