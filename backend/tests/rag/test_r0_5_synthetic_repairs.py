"""R0 第二轮：C21/C27 值缺失的最小合成复现（去身份化：假门店/假物品/假字段/假值）。

结构性质（对应 SAFE 事实）：
- 单记录、枚举型问法、path=rag、enumerate=1、1 条事实、引用 1 条；
- 答案 3 行 / 数十字符，只渲染**一个**列，同一条被引记录里承载目标值的另一列被丢掉；
- source_hit / kind_correct 全 pass，只有 value_hit fail。

第一个偏离边界（第二轮定位）：``rag/answer.py:_requested_field_entries`` 只认
``chunking.field_role(表头) == plan.field_roles`` 的列；表头侧的角色表只登记了少量
同义词，真实的同义列名（如“售价/促销价/尺寸/上架日期/铺货数量”）被判定为“无角色”，
于是同一行里承载目标值的列被静默丢弃。第一轮修的是“已登记角色的多列”（参考供价/零售价），
本文件覆盖“未登记的同义列”。

所有断言只依赖产品公开输出（kind / text / facts），不读评分器内部状态。
"""

from __future__ import annotations

import hashlib

from mktkb.rag import AtomicUnit, DocumentSpec


def _add_row(rag_index, fields: dict, *, doc_id: str, title: str = "合成价目表") -> DocumentSpec:
    doc = DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"corpus/{doc_id}.xlsx",
        title=title,
        file_kind="xlsx",
        version_id=f"V-{doc_id}",
        version_label="当前",
        sha256=hashlib.sha256(doc_id.encode()).hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    locator = {
        "sheet": "合成表",
        "row": 7,
        "header_row": 0,
        "cells": [
            {"header": name, "display": str(value)} for name, value in fields.items()
        ],
    }
    unit = AtomicUnit(
        unit_id=f"{doc_id}-row7",
        doc_id=doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key="sheet:合成表:row:7",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=dict(fields),
        sheet="合成表",
        locator=locator,
        header_row=0,
        row_number=7,
        title=title,
    )
    rag_index.add_document(doc, [unit], embed=False)
    return doc


# --------------------------------------------------------------------------- #
# C21：单条记录、单字段问法；目标值在“同一角色、未登记表头”的另一列
# --------------------------------------------------------------------------- #


def test_c21_single_record_question_renders_unregistered_sibling_price_column(rag_index):
    _add_row(
        rag_index,
        {"标识": "P01", "门店": "甲店", "物品": "立牌", "价格": "7", "售价": "9"},
        doc_id="D-r05-c21",
    )
    answer = rag_index.ask("列出甲店立牌的售价", user_id="u", conversation_id="r05-c21")
    assert answer.kind == "answer"
    # 目标值（同一行、同一价格语义的第二列）必须出现在答案与事实里。
    assert "9" in answer.text, answer.text
    assert ("price", "9") in {(fact.field_role, fact.value) for fact in answer.facts}
    # 形态仍是被引 1 条记录的短卡：3 行、1 条引用。
    assert len(answer.text.splitlines()) == 3, answer.text
    assert len(answer.citations) == 1


def test_c21_adjacent_normal_single_price_column_is_unchanged(rag_index):
    """正常反例：只有一列价格时，答案仍只答该列，不夹带未问字段。"""
    _add_row(
        rag_index,
        {"门店": "甲店", "物品": "立牌", "价格": "7", "位置": "甲区"},
        doc_id="D-r05-c21-normal",
    )
    answer = rag_index.ask("列出甲店立牌的价格", user_id="u", conversation_id="r05-c21-normal")
    assert answer.kind == "answer"
    assert "7" in answer.text
    assert "甲区" not in answer.text
    assert {(fact.field_role, fact.value) for fact in answer.facts} == {("price", "7")}


# --------------------------------------------------------------------------- #
# C27：两字段问法、只缺一个；缺失值的表头是同义但未登记的列名
# --------------------------------------------------------------------------- #


def test_c27_two_field_question_renders_unregistered_sibling_spec_column(rag_index):
    _add_row(
        rag_index,
        {"门店": "甲店", "物品": "立牌", "价格": "7", "尺寸": "60x160cm"},
        doc_id="D-r05-c27",
    )
    answer = rag_index.ask("列出甲店立牌的价格和规格", user_id="u", conversation_id="r05-c27")
    assert answer.kind == "answer"
    assert "7" in answer.text
    assert "60x160cm" in answer.text, answer.text
    roles = {fact.field_role for fact in answer.facts}
    assert {"price", "spec"} <= roles, {(fact.field_role, fact.value) for fact in answer.facts}
    assert len(answer.text.splitlines()) == 3, answer.text


def test_c27_adjacent_normal_two_registered_fields_is_unchanged(rag_index):
    """正常反例：两列都已登记角色时，答案逐字保持“名称 值、名称 值”的既有形态。"""
    _add_row(
        rag_index,
        {"门店": "甲店", "物品": "立牌", "价格": "7", "规格": "60x160cm"},
        doc_id="D-r05-c27-normal",
    )
    answer = rag_index.ask("列出甲店立牌的价格和规格", user_id="u", conversation_id="r05-c27-normal")
    assert answer.kind == "answer"
    assert "价格 7 元" in answer.text and "规格 60x160cm" in answer.text, answer.text
    assert len(answer.text.splitlines()) == 3


def test_c21_date_question_renders_unregistered_sibling_date_column(rag_index):
    """C21 答案里带 1 个完整日期：日期题同样可能只渲染已登记的日期列。"""
    _add_row(
        rag_index,
        {"门店": "甲店", "物品": "立牌", "更新日期": "2026-03-04", "上架日期": "2026-02-01"},
        doc_id="D-r05-c21-date",
    )
    answer = rag_index.ask("列出甲店立牌的日期", user_id="u", conversation_id="r05-c21-date")
    assert answer.kind == "answer"
    assert "2026-03-04" in answer.text and "2026-02-01" in answer.text, answer.text
    assert len(answer.text.splitlines()) == 3, answer.text


def test_c27_quantity_question_renders_unregistered_sibling_quantity_column(rag_index):
    _add_row(
        rag_index,
        {"门店": "甲店", "物品": "立牌", "数量": "3", "铺货数量": "12"},
        doc_id="D-r05-c27-qty",
    )
    answer = rag_index.ask("列出甲店立牌的数量", user_id="u", conversation_id="r05-c27-qty")
    assert answer.kind == "answer"
    assert "3" in answer.text and "12" in answer.text, answer.text


# --------------------------------------------------------------------------- #
# 安全反例：字段角色扩展不得放宽跨字段/受限联系人边界
# --------------------------------------------------------------------------- #


def test_r05_spec_question_does_not_leak_price(rag_index):
    _add_row(
        rag_index,
        {"门店": "甲店", "物品": "立牌", "价格": "7", "尺寸": "60x160cm"},
        doc_id="D-r05-safe-spec",
    )
    answer = rag_index.ask("列出甲店立牌的规格", user_id="u", conversation_id="r05-safe-spec")
    assert answer.kind == "answer"
    assert "60x160cm" in answer.text
    assert "7 元" not in answer.text


def test_r05_position_question_still_hides_prices_and_phone(rag_index):
    _add_row(
        rag_index,
        {"门店": "甲店", "物品": "立牌", "价格": "7", "售价": "9", "位置": "甲区"},
        doc_id="D-r05-safe-location",
    )
    answer = rag_index.ask("列出甲店立牌的位置", user_id="u", conversation_id="r05-safe-location")
    assert answer.kind == "answer"
    assert "甲区" in answer.text
    assert "7" not in answer.text and "9" not in answer.text


def test_r05_restricted_contact_boundary_is_unchanged(rag_index):
    _add_row(
        rag_index,
        {"门店": "甲店", "物品": "立牌", "位置": "甲区", "电话": "010-55550000"},
        doc_id="D-r05-safe-contact",
    )
    answer = rag_index.ask("列出甲店立牌的全部信息", user_id="u", conversation_id="r05-safe-contact")
    assert answer.kind == "no_answer"
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT"
    assert "010-55550000" not in answer.text


# --------------------------------------------------------------------------- #
# 非枚举相邻问法：多价格列仍按冲突披露，不静默选一个
# --------------------------------------------------------------------------- #


def test_r05_non_enumerate_two_price_columns_still_conflict(rag_index):
    _add_row(
        rag_index,
        {"门店": "甲店", "物品": "立牌", "价格": "7", "售价": "9"},
        doc_id="D-r05-conflict",
    )
    answer = rag_index.ask("甲店立牌的售价是多少？", user_id="u", conversation_id="r05-conflict")
    assert answer.kind == "conflict"
    assert "7" in answer.text and "9" in answer.text


# --------------------------------------------------------------------------- #
# C12：legacy 记录检索的“请求字段角色裁剪”不得把只含未登记角色的行裁掉
# --------------------------------------------------------------------------- #


def _c12_index(tmp_path):
    """门店行（联系人）+ 盘点行（盘点时间/数量）+ 无关行（备注）。

    legacy ``HEADER_ROLES`` 只登记了 store/item/location/contact/phone/address/status；
    “盘点时间”“数量”都解析不到角色。裁剪若只按“已解析角色”判定，盘点行会被整行裁掉，
    它承载的期望值既不进证据面也不被引用（SAFE：expected 2 / retrieved 1 / neither 1）。
    """

    from mktkb.rag.legacy import LegacyIndex

    doc = DocumentSpec(
        doc_id="D-syn-c12b",
        logical_id="L-syn-c12b",
        source_path="synthetic/syn-c12b.xlsx",
        title="合成门店资料",
        file_kind="xlsx",
        version_id="V-syn-c12b-v1",
        version_label="1",
        sha256=hashlib.sha256(b"synthetic-c12b").hexdigest(),
        business_date=None,
    )

    def unit(ordinal, fields, kind="table_row"):
        return AtomicUnit(
            unit_id=f"U-syn-c12b-{ordinal}",
            doc_id=doc.doc_id,
            version_id=doc.version_id,
            kind=kind,
            ordinal=ordinal,
            unit_key=f"sheet:合成表:row:{ordinal + 2}",
            text="；".join(f"{name}: {value}" for name, value in fields.items()),
            fields=fields,
            sheet="合成表",
            locator={"sheet": "合成表", "row": ordinal + 2, "header_row": 1},
            row_number=ordinal + 2,
            title=doc.title,
        )

    rows = [
        unit(0, {"标识": "S01", "门店": "甲店", "联系人": "阿甲"}),
        unit(1, {"标识": "P01", "门店": "甲店", "物品": "立牌", "盘点时间": "2026-03-04", "数量": "12"}),
        unit(2, {"标识": "P02", "门店": "甲店", "物品": "立牌", "备注": "无关说明"}),
    ]
    index = LegacyIndex(tmp_path / "synthetic-c12b.sqlite3")
    index.build([(doc, rows)])
    return index


def _c12_retrieve(index, requested_fields):
    from mktkb.retrieval.service import retrieve
    from mktkb.retrieval.types import QueryIntent

    intent = QueryIntent(
        mode="record",
        entity_filters={"store": "甲店"},
        requested_fields=tuple(requested_fields),
    )
    with index.database.session() as session:
        return retrieve(session, intent, revision=index.revision, limit=20)


def test_c12_requested_field_without_registered_role_is_not_a_trim_reason(tmp_path):
    index = _c12_index(tmp_path)
    try:
        result = _c12_retrieve(index, ("联系人", "盘点时间", "数量"))
        assert result.kind == "matches"
        keys = {unit.unit_key for unit in result.units}
        assert "sheet:合成表:row:2" in keys
        # 盘点行只含“盘点时间/数量”这类未登记角色字段——它承载期望值，不能被裁掉。
        assert "sheet:合成表:row:3" in keys, keys
        assert any(unit.fields.get("盘点时间") == "2026-03-04" for unit in result.units)
        assert any(unit.fields.get("数量") == "12" for unit in result.units)
        # 无关行仍按 T09-D2 口径裁掉（只含未请求字段的备注/说明）。
        assert "sheet:合成表:row:4" not in keys
    finally:
        index.close()


def test_c12_all_role_resolvable_fields_still_trim_unrelated_rows(tmp_path):
    """正常反例：请求字段全部能解析成角色时，裁剪口径与修复前逐值相同。"""

    index = _c12_index(tmp_path)
    try:
        result = _c12_retrieve(index, ("联系人", "位置"))
        keys = {unit.unit_key for unit in result.units}
        assert keys == {"sheet:合成表:row:2"}, keys
    finally:
        index.close()

