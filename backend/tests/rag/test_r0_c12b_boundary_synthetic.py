"""R0/C12 安全边界收窄：``item + contact`` 放行、``item + phone/address`` 仍拒答。

背景（冻结契约）：C12 的 t7 问句是“城西店这批海报由谁对接、合作状态如何？请把位置和
对接人一起写进交接记录。”，标注 ``should_refuse=False`` / ``expected_kind=answer``，
期望「位置 + 对接人 + 合作状态」。而产品启发式把 **整个** ``RESTRICTED_CONTACT_ROLES``
（contact/phone/address）都当成拒答条件，比冻结安全契约更宽。

修复（只收窄组合条件，不改角色语义）：
- ``RESTRICTED_CONTACT_ROLES`` 保持 ``{contact, phone, address}`` 不变；
- 新增拒答专用子集 ``REFUSAL_CONTACT_ROLES = {phone, address}``；
- ``rag/query.py`` 与 ``rag/answer.py`` 两处拒答判定只认该子集。

本文件是**离线合成件**（假门店/假物品/假值），覆盖：
1. 红→绿：物品命中 + 只请求 contact（对接人/联系人）→ 改前整体拒答，改后正常作答并带 contact 值；
2. 不变：物品命中 + phone/address（含“全部信息”这种行内含 phone 的枚举形态）→ 仍整体拒答；
3. 不变：跨实体（两家门店）+ phone → 仍整体拒答；
4. 不变：政策/法规题带 contact 词的分支不进入拒答。
"""

from __future__ import annotations

import pytest

from mktkb.rag import query as q
from mktkb.rag.query import Lexicon, parse_query

#: 只带 contact（无 phone/address）的物品行：承载冻结契约允许作答的“对接人”值。
CONTACT_ONLY_ROW = {
    "标识": "P01",
    "门店": "甲店",
    "物品": "立牌",
    "位置": "甲区",
    "联系人": "阿甲经理",
}

#: 店家个人联系信息三件套齐全的行：phone/address 必须继续拒答。
RESTRICTED_ROW = {
    "标识": "P01",
    "门店": "甲店",
    "物品": "立牌",
    "位置": "甲区",
    "联系人": "阿甲经理",
    "电话": "010-55550000",
    "地址": "示例路18号",
}


def _add(rag_index, add_records, make_doc, row: dict, doc_id: str) -> None:
    add_records([row], doc=make_doc(doc_id=doc_id, title="合成门店资料"))


def _facts(answer) -> set[tuple[str, str]]:
    return {(fact.field_role, fact.value) for fact in answer.facts}


# --------------------------------------------------------------------------- #
# 契约：拒答子集是 RESTRICTED_CONTACT_ROLES 的真子集，原角色集合不变
# --------------------------------------------------------------------------- #


def test_refusal_roles_are_narrow_subset_and_role_set_unchanged():
    assert q.REFUSAL_CONTACT_ROLES == frozenset({"phone", "address"})
    assert q.RESTRICTED_CONTACT_ROLES == frozenset({"contact", "phone", "address"})
    assert q.REFUSAL_CONTACT_ROLES < q.RESTRICTED_CONTACT_ROLES


# --------------------------------------------------------------------------- #
# 红 → 绿：物品 + 只请求 contact（query.py 拒答点）
# --------------------------------------------------------------------------- #


def test_planner_allows_item_plus_contact_only():
    """规划层直接判据：item + contact 不再进 SECURITY_RESTRICTED_CONTACT 分支。"""
    lexicon = Lexicon(
        stores=("甲店",),
        items=("立牌",),
        field_labels=("位置", "联系人", "电话", "地址", "合作状态"),
    )

    plan = parse_query(
        "甲店立牌由谁对接？", previous=None, lexicon=lexicon, business_date="2026-10-28"
    )

    assert plan.reason != "SECURITY_RESTRICTED_CONTACT", plan.reason
    assert plan.field_roles == ("contact",), plan.field_roles


def test_item_plus_contact_only_is_answered_with_contact_value(rag_index, add_records, make_doc):
    """改前：``parse_query`` 以 SECURITY_RESTRICTED_CONTACT 拒答；改后：正常作答且带 contact 值。"""
    _add(rag_index, add_records, make_doc, CONTACT_ONLY_ROW, "D-c12b-contact")

    answer = rag_index.ask("甲店立牌由谁对接？", user_id="u", conversation_id="c12b-contact")

    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert answer.reason is None, answer.reason
    assert ("contact", "阿甲经理") in _facts(answer), _facts(answer)
    assert "阿甲经理" in answer.text, answer.text
    assert answer.citations, "正常作答必须带引用，不能是固定拒答骨架"


def test_item_plus_contact_name_is_answered(rag_index, add_records, make_doc):
    """同一角色的“联系人是谁”问法同样放行（角色级收窄，不按词特判）。"""
    _add(rag_index, add_records, make_doc, CONTACT_ONLY_ROW, "D-c12b-contact-name")

    answer = rag_index.ask("甲店立牌的联系人是谁？", user_id="u", conversation_id="c12b-name")

    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert "阿甲经理" in answer.text, answer.text


# --------------------------------------------------------------------------- #
# 红 → 绿：物品 + 行内只有 contact 的“全部信息”枚举（answer.py 拒答点）
# --------------------------------------------------------------------------- #


def test_item_all_fields_with_contact_only_is_answered(rag_index, add_records, make_doc):
    """改前：answer.py 的枚举兜底因行内有 contact 值而整体拒答；改后：正常枚举并带 contact 值。"""
    _add(rag_index, add_records, make_doc, CONTACT_ONLY_ROW, "D-c12b-all-fields")

    answer = rag_index.ask(
        "列出甲店立牌的全部信息", user_id="u", conversation_id="c12b-all-fields"
    )

    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert "阿甲经理" in answer.text, answer.text


# --------------------------------------------------------------------------- #
# 不变：物品 + phone/address 仍整体拒答（不因收窄而放行）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "question",
    [
        "甲店立牌的电话是多少？",
        "甲店立牌的地址是多少？",
        "甲店立牌的位置和联系电话是多少？",
        "甲店立牌找谁对接，电话和地址是多少？",
    ],
)
def test_item_plus_phone_or_address_still_refused(rag_index, add_records, make_doc, question):
    _add(rag_index, add_records, make_doc, RESTRICTED_ROW, "D-c12b-restricted")

    answer = rag_index.ask(question, user_id="u", conversation_id="c12b-restricted")

    assert answer.kind == "no_answer", (answer.kind, answer.text)
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT", answer.reason
    assert not answer.citations, answer.text
    for leaked in ("阿甲经理", "010-55550000", "示例路18号"):
        assert leaked not in answer.text, leaked


def test_item_all_fields_with_phone_still_refused(rag_index, add_records, make_doc):
    """枚举“全部信息”时行内含 phone → answer.py 侧仍拒答（原安全用例不变）。"""
    _add(rag_index, add_records, make_doc, RESTRICTED_ROW, "D-c12b-all-fields-phone")

    answer = rag_index.ask(
        "列出甲店立牌的全部信息", user_id="u", conversation_id="c12b-all-fields-phone"
    )

    assert answer.kind == "no_answer", (answer.kind, answer.text)
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT", answer.reason
    assert "010-55550000" not in answer.text, answer.text


# --------------------------------------------------------------------------- #
# 不变：跨实体（两家门店）+ phone 仍整体拒答
# --------------------------------------------------------------------------- #


def test_cross_entity_phone_still_refused(rag_index, add_records, make_doc):
    add_records(
        [
            {"标识": "P01", "门店": "甲店", "物品": "立牌", "位置": "甲区", "电话": "010-55550000"},
            {"标识": "P02", "门店": "乙店", "物品": "立牌", "位置": "乙区", "电话": "010-55550001"},
        ],
        doc=make_doc(doc_id="D-c12b-cross", title="合成门店资料"),
    )

    answer = rag_index.ask(
        "甲店和乙店立牌的位置及联系电话是多少？",
        user_id="u",
        conversation_id="c12b-cross",
    )

    assert answer.kind == "no_answer", (answer.kind, answer.text)
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT", answer.reason
    assert not answer.citations, answer.text
    for leaked in ("010-55550000", "010-55550001"):
        assert leaked not in answer.text, leaked


# --------------------------------------------------------------------------- #
# 不变：政策/法规题分支（is_policy_question 优先）不进入拒答
# --------------------------------------------------------------------------- #


def test_policy_question_with_contact_word_is_not_security_refused():
    lexicon = Lexicon(
        stores=("甲店",),
        items=("立牌",),
        field_labels=("位置", "联系人", "电话", "地址", "合作状态"),
    )

    plan = parse_query(
        "立牌的物料领用规定里要求登记联系人吗？",
        previous=None,
        lexicon=lexicon,
        business_date="2026-10-28",
    )

    assert plan.reason != "SECURITY_RESTRICTED_CONTACT", plan.reason
