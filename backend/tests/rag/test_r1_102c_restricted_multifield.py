"""R1/T-R1-102c：多字段 + 联系人 / 合同·结算账号的拒答边界（M5）。

机制出处：``work/r1_mechanism_repro`` 的 M5 红例——问句
“甲店立牌放在哪，由谁对接，完整合同和结算账号是多少？” 当前 ``kind=answer``，
只渲染“位置 + 联系人”，把凭据族的索取当成了普通多字段题（应拒未拒）。

判据位置与取舍：
- ``field_roles`` 不足以判：M5 红例与 R0/C12 放行的合法面（“位置 + 对接人”）
  的 ``field_roles`` 完全同形（``("location", "contact")``）。按“多字段 + contact”
  或字段数拒答，会把冻结安全契约 C12 t7（位置 + 对接人 + 合作状态 → should_refuse=False）
  和 ``tests/rag/test_r0_11_contact_family.py`` 的“对接 + 电话 + 地址（门店资料）”一起拒掉。
- 因此新判据只认**凭据词面**（合同/账号/账户/银行卡/凭证/开户行/税号/密码），在
  ``rag/query.py`` 的同一安全早退点（检索/模型之前）整体拒答；法规/制度正文题
  （“合同条款第几条”）由 ``is_policy_question`` 先行排除。

全部离线合成数据：甲店 / 立牌 / 甲区 / 甲某 / 010-55550000 / 示例路18号 / SEQ-0001。
"""

from __future__ import annotations

from mktkb.rag import query as q
from mktkb.rag.query import Lexicon, parse_query

#: 一行同时带位置、联系人、电话、地址与凭据列：红例与合法面都从这一行取。
ROW = {
    "标识": "P01",
    "门店": "甲店",
    "物品": "立牌",
    "位置": "甲区",
    "联系人": "甲某",
    "电话": "010-55550000",
    "地址": "示例路18号",
    "合作状态": "合作中",
    "结算账号": "SEQ-0001",
}
#: M5 红例问句（与机制复现同形）：位置 + 由谁对接 + 完整合同/结算账号。
PAYMENT_QUESTION = "甲店立牌放在哪，由谁对接，完整合同和结算账号是多少？"
#: 合法面：只问位置 + 对接人（R0/C12 明确放行的组合）。
LOCATION_CONTACT_QUESTION = "甲店立牌放在哪，由谁对接？"
#: 合法面：只问对接人，不夹带位置/电话/地址/凭据。
CONTACT_ONLY_QUESTION = "甲店立牌的对接人是谁？"
#: 拒答面不得出现在正文里的值（联系人/电话/地址/凭据 + 位置，固定骨架一个都不含）。
LEAK_VALUES = ("甲某", "010-55550000", "示例路18号", "SEQ-0001", "甲区")

LEXICON = Lexicon(
    stores=("甲店",),
    items=("立牌",),
    field_labels=("位置", "联系人", "电话", "地址", "合作状态"),
)


def _seed(rag_index, add_records, make_doc) -> None:
    add_records([ROW], doc=make_doc(doc_id="D-r1102c", title="合成物品台账"))


def _facts(answer) -> set[tuple[str, str]]:
    return {(fact.field_role, fact.value) for fact in answer.facts}


# --------------------------------------------------------------------------- #
# 正例：M5 同形问句必须整体拒答，且不含任何联系人/电话/地址/凭据值
# --------------------------------------------------------------------------- #


def test_m5_multifield_with_contract_and_account_is_refused(rag_index, add_records, make_doc):
    _seed(rag_index, add_records, make_doc)

    answer = rag_index.ask(PAYMENT_QUESTION, user_id="u", conversation_id="c-102c-m5")

    assert answer.kind == "no_answer", (answer.kind, answer.reason, answer.text)
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT", answer.reason
    assert answer.citations == [], answer.text
    for value in LEAK_VALUES:
        assert value not in answer.text, (value, answer.text)


def test_credential_request_without_contact_is_refused(rag_index, add_records, make_doc):
    """凭据族的索取本身即受限，不依赖是否同时点名联系人。"""
    _seed(rag_index, add_records, make_doc)

    answer = rag_index.ask("甲店的结算账号是多少？", user_id="u", conversation_id="c-102c-account")

    assert answer.kind == "no_answer", (answer.kind, answer.reason, answer.text)
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT", answer.reason
    assert "SEQ-0001" not in answer.text, answer.text


def test_planner_refuses_m5_shape_before_retrieval():
    """规划层收口：同一早退点给出 SECURITY_RESTRICTED_CONTACT，且字段角色仍按题面识别。"""
    plan = parse_query(PAYMENT_QUESTION, previous=None, lexicon=LEXICON, business_date="2026-10-28")

    assert plan.reason == "SECURITY_RESTRICTED_CONTACT", plan.reason
    # 红例与合法面同形：字段角色都是 (location, contact)——这正是不能按字段数拒答的理由。
    # （拒答计划沿用既有早退形态：``field_roles`` 随计划清空，识别结果留在 state 上。）
    assert plan.state.field_roles == ("location", "contact"), plan.state.field_roles


# --------------------------------------------------------------------------- #
# 反例：相邻合法面必须继续作答，且不渲染未问字段
# --------------------------------------------------------------------------- #


def test_location_plus_contact_only_still_answers(rag_index, add_records, make_doc):
    _seed(rag_index, add_records, make_doc)

    answer = rag_index.ask(LOCATION_CONTACT_QUESTION, user_id="u", conversation_id="c-102c-loc-contact")

    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert "甲区" in answer.text and "甲某" in answer.text, answer.text
    assert {role for role, _value in _facts(answer)} == {"location", "contact"}, _facts(answer)
    for value in ("010-55550000", "示例路18号", "SEQ-0001"):
        assert value not in answer.text, (value, answer.text)


def test_contact_only_still_answers_without_unrequested_fields(rag_index, add_records, make_doc):
    _seed(rag_index, add_records, make_doc)

    answer = rag_index.ask(CONTACT_ONLY_QUESTION, user_id="u", conversation_id="c-102c-contact")

    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert _facts(answer) == {("contact", "甲某")}, _facts(answer)
    for value in ("甲区", "010-55550000", "示例路18号", "SEQ-0001"):
        assert value not in answer.text, (value, answer.text)


# --------------------------------------------------------------------------- #
# 不扩大拒答面：既有安全面保持，法规/制度正文题不被凭据词吞掉
# --------------------------------------------------------------------------- #


def test_phone_request_is_still_security_refused(rag_index, add_records, make_doc):
    _seed(rag_index, add_records, make_doc)

    answer = rag_index.ask("甲店立牌的电话是多少？", user_id="u", conversation_id="c-102c-phone")

    assert answer.kind == "no_answer", (answer.kind, answer.reason, answer.text)
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT", answer.reason
    assert "010-55550000" not in answer.text, answer.text


def test_regulation_clause_question_is_not_swallowed_by_credential_words():
    """“合同条款”问的是制度正文（``is_policy_question`` 口径），不按凭据拒答收口。"""
    plan = parse_query(
        "合同条款里第几条要求登记联系人？", previous=None, lexicon=LEXICON, business_date="2026-10-28"
    )

    assert plan.reason != "SECURITY_RESTRICTED_CONTACT", plan.reason
    assert q.is_contract_credential_question("甲店的结算账号是多少？") is True
    assert q.is_contract_credential_question("甲店立牌放在哪，由谁对接？") is False
