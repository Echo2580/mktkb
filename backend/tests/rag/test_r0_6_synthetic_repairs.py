"""R0 第三轮：C21/C27 值缺失的最小合成复现（去身份化：假门店/假物品/假字段/假值）。

结构性质（对应 SAFE 四层阶梯计数）：

- 单记录、枚举型问法、path=rag、enumerate=1、被引用 1 条、答案 3 行；
- 期望值**就在被引用那一行里**、且能映射到字段角色（DB 单元 / 被引单元 / 可映射角色
  三层都是满的，``cited_raw=cited_text=cited_role=1``）；
- facts / 提交文本层只出现**一个**字段角色的值（``exp_in_rag_facts=0`` 或 ``1/2``）。

第三轮定位的层：**“被请求字段角色集合”的构造**（``rag/query.py:_match_fields``）。
多字段问法只有在出现合取词（和/及/以及/、/与）时才会收全其余字段角色；用逗号、
顿号以外的方式并列（“地址，电话”“什么时候生效什么时候失效”），或者第二个字段
用的是 ``FIELD_WORDS`` 没登记的短问法（“什么时候生效”），第二个角色就永远不进
``plan.field_roles``，于是同一条被引行里承载答案的那一列不会被 ``_requested_field_entries``
选中。渲染层是忠实的：它只渲染被请求的角色。

所有断言只依赖产品公开输出（kind / text / facts / citations），不读评分器内部状态，
也不按 case_id 特判。
"""

from __future__ import annotations

import hashlib

from mktkb.rag import AtomicUnit, DocumentSpec


def _add_row(rag_index, fields: dict, *, doc_id: str, title: str = "合成台账") -> DocumentSpec:
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
        "cells": [{"header": name, "display": str(value)} for name, value in fields.items()],
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


def _roles(answer) -> set[tuple[str, str]]:
    return {(fact.field_role, fact.value) for fact in answer.facts}


def _cells(fields: dict) -> set[str]:
    return {str(value) for value in fields.values()}


# --------------------------------------------------------------------------- #
# C21 形：单行 + 两个日期列；问法并列但不带合取词
# --------------------------------------------------------------------------- #

_WINDOW_FIELDS = {"标识": "L01", "门店": "甲店", "物品": "立牌",
                  "生效日期": "2026-01-05", "失效日期": "2026-09-30"}


def test_c21_shaped_question_renders_both_date_columns(rag_index):
    """“生效日期和失效日期”：已登记完整问法 + 合取词，两列都必须进入 facts 与文本。

    这是**修复前也通过**的非回归基线（证明本轮改动不放宽单条记录的作答形态）。
    """
    _add_row(rag_index, dict(_WINDOW_FIELDS), doc_id="D-r06-c21a")
    answer = rag_index.ask(
        "列出甲店立牌的生效日期和失效日期", user_id="u", conversation_id="r06-c21a"
    )
    assert answer.kind == "answer", answer.text
    roles = _roles(answer)
    assert ("effective_from", "2026-01-05") in roles, roles
    assert ("effective_to", "2026-09-30") in roles, roles
    assert "2026-01-05" in answer.text and "2026-09-30" in answer.text, answer.text
    # 形态不变：被引 1 条记录的短卡。
    assert len(answer.text.splitlines()) == 3, answer.text
    assert len(answer.citations) == 1


def test_c21_shaped_question_with_comma_renders_both(rag_index):
    """“什么时候生效，什么时候失效”：逗号并列同样算两个被请求字段。"""
    _add_row(rag_index, dict(_WINDOW_FIELDS), doc_id="D-r06-c21b")
    answer = rag_index.ask(
        "列出甲店立牌什么时候生效，什么时候失效", user_id="u", conversation_id="r06-c21b"
    )
    assert answer.kind == "answer", answer.text
    roles = _roles(answer)
    assert ("effective_from", "2026-01-05") in roles, roles
    assert ("effective_to", "2026-09-30") in roles, roles


def test_c21_shaped_question_with_conjunction_and_short_wording_renders_both(rag_index):
    """“什么时候生效和什么时候失效”：合取词在，但第二个字段用的是短问法。"""
    _add_row(rag_index, dict(_WINDOW_FIELDS), doc_id="D-r06-c21c")
    answer = rag_index.ask(
        "列出甲店立牌什么时候生效和什么时候失效", user_id="u", conversation_id="r06-c21c"
    )
    assert answer.kind == "answer", answer.text
    roles = _roles(answer)
    assert ("effective_from", "2026-01-05") in roles, roles
    assert ("effective_to", "2026-09-30") in roles, roles


# --------------------------------------------------------------------------- #
# C27 形：门店单行 + 地址/电话两列；问法并列但不带合取词
# --------------------------------------------------------------------------- #

_CONTACT_FIELDS = {"门店": "甲店", "门店地址": "合成区长街 1 号", "联系电话": "010-1000-1001"}


def test_c27_shaped_question_renders_both_contact_columns(rag_index):
    """“地址，电话”：两个受限联系人角色都被请求时，两列都要渲染。"""
    _add_row(rag_index, dict(_CONTACT_FIELDS), doc_id="D-r06-c27a")
    answer = rag_index.ask("列出甲店的地址，电话", user_id="u", conversation_id="r06-c27a")
    assert answer.kind == "answer", answer.text
    roles = _roles(answer)
    assert ("address", "合成区长街 1 号") in roles, roles
    assert ("phone", "010-1000-1001") in roles, roles
    assert len(answer.text.splitlines()) == 3, answer.text


def test_c27_shaped_question_without_list_joiner_keeps_single_field(rag_index):
    """反例：句中只是拿字段词当限定语（并列词/列表标点都没有）时仍按单字段作答。"""
    _add_row(rag_index, dict(_CONTACT_FIELDS), doc_id="D-r06-c27b")
    answer = rag_index.ask("列出甲店电话", user_id="u", conversation_id="r06-c27b")
    assert answer.kind == "answer", answer.text
    assert _roles(answer) == {("phone", "010-1000-1001")}, _roles(answer)
    assert "合成区长街 1 号" not in answer.text, answer.text


def test_qualifier_field_word_does_not_drag_the_other_field(rag_index):
    """追问里“组合价”只是限定语：问的是失效时间，不能把价格值一起渲染出来。

    对应离线 e2e `test_oolong_nka_combo_price_and_follow_up` 的追问形态
    （“那这个组合价什么时候失效？”）；只改“被请求字段集合”时不得把它变成多字段问法。
    """
    _add_row(rag_index, {"门店": "甲店", "物品": "立牌", "组合价": "5", "失效日期": "2026-09-30"},
             doc_id="D-r06-c27c")
    answer = rag_index.ask("甲店立牌的组合价什么时候失效？", user_id="u", conversation_id="r06-c27c")
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert _roles(answer) == {("effective_to", "2026-09-30")}, _roles(answer)
    assert "5" not in answer.text, answer.text


# --------------------------------------------------------------------------- #
# 反例 ①：只问单一字段时不夹带其他字段，也不因泛化时间词多出一个字段角色
# --------------------------------------------------------------------------- #


def test_single_field_date_question_keeps_exactly_one_role(rag_index):
    """只问“失效日期”时只答该字段：泛化“日期”不得另立 date 字段角色。"""
    _add_row(rag_index, dict(_WINDOW_FIELDS), doc_id="D-r06-one1")
    answer = rag_index.ask("列出甲店立牌的失效日期", user_id="u", conversation_id="r06-one1")
    assert answer.kind == "answer", answer.text
    assert _roles(answer) == {("effective_to", "2026-09-30")}, _roles(answer)
    assert "2026-01-05" not in answer.text, answer.text


def test_single_field_short_validity_question_is_not_refused(rag_index):
    """只问“什么时候生效”时仍按单字段作答，不能因多出来的 date 角色判“未记录”。"""
    _add_row(rag_index, dict(_WINDOW_FIELDS), doc_id="D-r06-one2")
    answer = rag_index.ask("甲店立牌什么时候生效？", user_id="u", conversation_id="r06-one2")
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert _roles(answer) == {("effective_from", "2026-01-05")}, _roles(answer)
    assert "2026-09-30" not in answer.text, answer.text


def test_single_field_phone_question_does_not_add_address(rag_index):
    """只问电话时不夹带地址。"""
    _add_row(rag_index, dict(_CONTACT_FIELDS), doc_id="D-r06-one3")
    answer = rag_index.ask("列出甲店的电话", user_id="u", conversation_id="r06-one3")
    assert answer.kind == "answer", answer.text
    assert _roles(answer) == {("phone", "010-1000-1001")}, _roles(answer)
    assert "合成区长街 1 号" not in answer.text, answer.text


def test_single_field_spec_question_does_not_leak_price(rag_index):
    """只问规格时不夹带价格（跨字段边界不变）。"""
    _add_row(rag_index, {"门店": "甲店", "物品": "立牌", "价格": "7", "规格": "60x160cm"},
             doc_id="D-r06-one4")
    answer = rag_index.ask("列出甲店立牌的规格", user_id="u", conversation_id="r06-one4")
    assert answer.kind == "answer", answer.text
    assert _roles(answer) == {("spec", "60x160cm")}, _roles(answer)
    assert "7" not in answer.text, answer.text


# --------------------------------------------------------------------------- #
# 反例 ③：新增渲染列的值必须来自事实里的值（不产生 value_no_fabricated 新失败）
# --------------------------------------------------------------------------- #


def test_every_rendered_value_comes_from_the_cited_row(rag_index):
    fields = dict(_CONTACT_FIELDS)
    _add_row(rag_index, fields, doc_id="D-r06-nofab")
    answer = rag_index.ask("列出甲店的地址，电话", user_id="u", conversation_id="r06-nofab")
    assert answer.kind == "answer", answer.text
    allowed = _cells(fields)
    for fact in answer.facts:
        assert fact.value in allowed, (fact.field_role, fact.value, allowed)


# --------------------------------------------------------------------------- #
# 相邻安全反例：受限联系人闸与“未请求字段”边界不放宽
# --------------------------------------------------------------------------- #


def test_item_contact_request_still_restricted(rag_index):
    """物品+地址/电话仍是受限联系人拒答（跨实体/受限边界不变）。"""
    _add_row(rag_index, {"门店": "甲店", "物品": "立牌",
                         "门店地址": "合成区长街 1 号", "联系电话": "010-1000-1001"},
             doc_id="D-r06-safe1")
    answer = rag_index.ask("列出甲店立牌的地址和电话", user_id="u", conversation_id="r06-safe1")
    assert answer.kind == "no_answer", answer.text
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT", answer.reason
    assert "010-1000-1001" not in answer.text and "合成区长街 1 号" not in answer.text


def test_all_fields_request_still_hides_restricted_contact(rag_index):
    """“全部信息”仍不倾倒受限联系人列（枚举闸不变）。"""
    _add_row(rag_index, {"门店": "甲店", "物品": "立牌", "位置": "甲区", "电话": "010-55550000"},
             doc_id="D-r06-safe2")
    answer = rag_index.ask("列出甲店立牌的全部信息", user_id="u", conversation_id="r06-safe2")
    assert answer.kind == "no_answer", answer.text
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT", answer.reason
    assert "010-55550000" not in answer.text
