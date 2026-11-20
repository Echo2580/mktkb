"""R0/C27：问句用未登记的联系人问法（“找谁 / 对接”）时 contact 列整列被丢弃。

SAFE 投影事实（第六轮，证据只留布尔/下标，不含问句与值）：
- ``FIELD_WORDS["contact"]``（只有「联系人 / 负责人」）在问句里 **不命中**；
- 但问句命中「谁 / 找谁 / 对接」这类**通用联系人问法**，``_match_fields`` 给出
  ``("phone", "address")``——问的是“电话、地址，找谁对接”，contact 角色没被请求；
- 被引 1 行 / 8 列，``contact`` / ``phone`` / ``address`` 各 1 列，期望值 #0 落在 contact 列；
- 答案层只渲染 ``plan.field_roles`` 里的角色（``_multi_field_answer`` / ``_requested_field_entries``），
  于是 contact 列不进取值集 → 不进 facts / 不进正文 → ``value_hit`` 缺 1 值（``role_missing``）。

最小修复（全局词表，不加业务数据、不加题号特判）：
把「找谁」「对接」登记进 ``FIELD_WORDS["contact"]``。**不**登记单字「谁」（任何“谁……”的句子都会
被当成联系字段），也**不**做“同族自动扩展”（问 phone/address 就把同族的 contact 全带上）——
后者会让“只问电话”的答案多渲染联系人姓名，见本文件的安全/单字段反例。
"""

from __future__ import annotations

import hashlib
import re

from mktkb.rag import AtomicUnit, DocumentSpec
from mktkb.rag import query as q

#: 复刻 C27 被引行的角色形态：8 列，contact / phone / address 各 1 列（其余为实体/状态/有效期）。
CONTACT_ROW = {
    "标识": "S01",
    "门店": "甲店",
    "联系人": "阿甲经理",
    "电话": "010-55550000",
    "地址": "示例路18号",
    "合作状态": "合作中",
    "生效日期": "2026-01-01",
    "失效日期": "2026-12-31",
}
#: 只问电话的安全类形态：物品记录 + 店家联系信息（既有 v3-safety-fix 拒答面）。
ITEM_CONTACT_ROW = {
    "标识": "P01",
    "门店": "甲店",
    "物品": "立牌",
    "位置": "甲区",
    "联系人": "阿甲经理",
    "电话": "010-55550000",
}


def _add_row(rag_index, fields: dict, *, doc_id: str, title: str = "合成门店资料") -> None:
    from mktkb.rag.chunking import effective_dates

    doc = DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"corpus/{doc_id}.xlsx",
        title=title,
        file_kind="xlsx",
        version_id=f"V-{doc_id}",
        version_label="当前",
        sha256=hashlib.sha256(doc_id.encode("utf-8")).hexdigest(),
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
    effective_from, effective_to = effective_dates(fields)
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
        effective_from=effective_from,
        effective_to=effective_to,
    )
    rag_index.add_document(doc, [unit], embed=False)


def _facts(answer) -> set[tuple[str, str]]:
    return {(fact.field_role, fact.value) for fact in answer.facts}


# --------------------------------------------------------------------------- #
# 红 → 绿：问“电话、地址，找谁对接”时，contact 列必须进正文
# --------------------------------------------------------------------------- #


def test_c27_contact_column_is_rendered_when_question_asks_who_to_contact(rag_index):
    """修复前：``plan.field_roles == ("phone", "address")``，contact 列整列丢失（红）。"""
    _add_row(rag_index, CONTACT_ROW, doc_id="D-r011-c27")

    answer = rag_index.ask(
        "甲店找谁对接，电话和地址是多少？",
        user_id="u",
        conversation_id="r011-c27",
    )

    assert answer.kind == "answer", (answer.reason, answer.text)
    assert ("contact", "阿甲经理") in _facts(answer), _facts(answer)
    assert "阿甲经理" in answer.text, answer.text
    assert "010-55550000" in answer.text, answer.text
    assert "示例路18号" in answer.text, answer.text


def test_c27_contact_column_is_rendered_on_enumeration_path(rag_index):
    """C27 在真实运行里也可能走枚举渲染（3 行短卡）；两条渲染路径都必须带上 contact 列。

    枚举路径取值的入口是 ``answer._requested_field_entries``，与多字段路径
    （``_multi_field_answer``）共用 ``plan.field_roles``——词表不补，两条路径都丢列。
    """
    _add_row(rag_index, CONTACT_ROW, doc_id="D-r011-c27-enum")

    answer = rag_index.ask(
        "甲店找谁对接，把电话和地址分别说一下",
        user_id="u",
        conversation_id="r011-c27-enum",
    )

    assert answer.kind == "answer", (answer.reason, answer.text)
    assert ("contact", "阿甲经理") in _facts(answer), _facts(answer)
    assert "联系人 阿甲经理" in answer.text, answer.text
    assert len(answer.text.splitlines()) == 3, answer.text


def test_c27_contact_only_question_renders_contact(rag_index):
    """只问联系人的既有问法（词表已登记）继续单字段作答。"""
    _add_row(rag_index, CONTACT_ROW, doc_id="D-r011-contact-only")

    answer = rag_index.ask("甲店的联系人是谁？", user_id="u", conversation_id="r011-contact-only")

    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "阿甲经理" in answer.text, answer.text
    assert "010-55550000" not in answer.text, answer.text
    assert _facts(answer) == {("contact", "阿甲经理")}, _facts(answer)


# --------------------------------------------------------------------------- #
# 单字段反例：只问一个字段时不夹带同族其它字段（尤其不夹带联系人姓名）
# --------------------------------------------------------------------------- #


def test_c27_phone_only_question_does_not_render_contact(rag_index):
    _add_row(rag_index, CONTACT_ROW, doc_id="D-r011-phone-only")

    answer = rag_index.ask("甲店的电话是多少？", user_id="u", conversation_id="r011-phone-only")

    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "010-55550000" in answer.text, answer.text
    assert "阿甲经理" not in answer.text, answer.text
    assert "示例路18号" not in answer.text, answer.text
    assert _facts(answer) == {("phone", "010-55550000")}, _facts(answer)


def test_c27_address_only_question_does_not_carry_phone_or_contact(rag_index):
    _add_row(rag_index, CONTACT_ROW, doc_id="D-r011-address-only")

    answer = rag_index.ask("甲店的地址是什么？", user_id="u", conversation_id="r011-address-only")

    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "示例路18号" in answer.text, answer.text
    assert "010-55550000" not in answer.text, answer.text
    assert "阿甲经理" not in answer.text, answer.text
    assert _facts(answer) == {("address", "示例路18号")}, _facts(answer)


def test_c27_phone_address_question_is_not_family_expanded(rag_index):
    """反例锁定：问 phone+address（问句没有任何 contact 问法）时**不**自动带上同族 contact。

    这条就是“同族扩展”方案被否掉的原因：它会让只问电话/地址的答案多渲染联系人姓名。
    """
    _add_row(rag_index, CONTACT_ROW, doc_id="D-r011-no-expand")

    answer = rag_index.ask("甲店的电话和地址是多少？", user_id="u", conversation_id="r011-no-expand")

    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "阿甲经理" not in answer.text, answer.text
    assert {role for role, _value in _facts(answer)} == {"phone", "address"}, _facts(answer)


# --------------------------------------------------------------------------- #
# 安全反例：只问电话的安全类问法不得把联系人姓名渲染出来
# --------------------------------------------------------------------------- #


def test_c27_item_plus_phone_only_still_security_refused_without_contact_name(rag_index):
    _add_row(rag_index, ITEM_CONTACT_ROW, doc_id="D-r011-safe-phone")

    answer = rag_index.ask("甲店立牌的电话是多少？", user_id="u", conversation_id="r011-safe-phone")

    assert answer.kind == "no_answer", (answer.kind, answer.text)
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT", answer.reason
    assert "阿甲经理" not in answer.text, answer.text
    assert "010-55550000" not in answer.text, answer.text
    assert not answer.citations, answer.text


def test_c27_item_plus_contact_ask_still_security_refused(rag_index):
    """物品记录 + 联系信息（本轮新增的“对接”问法同样算联系信息）仍整体拒答。"""
    _add_row(rag_index, ITEM_CONTACT_ROW, doc_id="D-r011-safe-both")

    answer = rag_index.ask(
        "甲店立牌找谁对接，电话是多少？",
        user_id="u",
        conversation_id="r011-safe-both",
    )

    assert answer.kind == "no_answer", (answer.kind, answer.text)
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT", answer.reason
    assert "阿甲经理" not in answer.text, answer.text
    assert "010-55550000" not in answer.text, answer.text
    assert not answer.citations, answer.text


# --------------------------------------------------------------------------- #
# 不新增 value_no_fabricated：进正文的值必须是行内真实单元格
# --------------------------------------------------------------------------- #


def test_c27_rendered_values_are_real_cells(rag_index):
    _add_row(rag_index, CONTACT_ROW, doc_id="D-r011-real-cells")

    answer = rag_index.ask(
        "甲店找谁对接，电话和地址是多少？",
        user_id="u",
        conversation_id="r011-real-cells",
    )

    assert answer.kind == "answer", (answer.reason, answer.text)
    cells = {str(value) for value in CONTACT_ROW.values()}
    assert {value for _role, value in _facts(answer)} <= cells, _facts(answer)
    row_digits = "".join(str(value) for value in CONTACT_ROW.values())
    for token in re.findall(r"\d+", answer.text):
        assert token in row_digits, (token, answer.text)


# --------------------------------------------------------------------------- #
# 词表层：只补通用联系人问法，不登记单字「谁」，不改变单字段口径
# --------------------------------------------------------------------------- #


def test_contact_ask_synonyms_are_registered() -> None:
    assert "contact" in q._match_fields("甲店找谁对接，电话和地址是多少？")
    assert "contact" in q._match_fields("甲店的对接人是谁")
    assert q._match_fields("甲店的联系人是谁") == ("contact",)


def test_bare_who_is_not_a_contact_word() -> None:
    # 单字「谁」不登记：任何“谁……”的句子都不得被当成在问联系人。
    assert "contact" not in q._match_fields("甲店谁在负责补货")


def test_single_field_plans_stay_single() -> None:
    assert q._match_fields("甲店的电话是多少") == ("phone",)
    assert q._match_fields("甲店的地址是多少") == ("address",)


def test_contact_words_do_not_bypass_policy_short_circuit() -> None:
    # 政策/流程题（无记录实体）即使带“找谁”，也不得被判成记录字段题。
    assert q.field_roles_for_question("活动预算4000元找谁审批？", has_entity=False) == ()
