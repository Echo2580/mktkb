"""T105/ERR-06：指代追问的字段继承与“无字段澄清”单元用例。

不建产品、不调模型：用隔离 rag 索引验证多轮状态——继承了实体就必须判断“问什么”：
- 上文问过某个记录字段 → 只答该字段，不倾倒整条记录；
- 没有可继承字段 → 澄清要哪项信息；
- 指代无源 → 澄清对象；
- 用户显式要求“列出来”仍按枚举渲染（不被指代分支吞掉）。
"""

from __future__ import annotations

import pytest

from mktkb.rag import DocumentSpec

ROWS = [
    {
        "标识": "QF02",
        "门店": "城西店",
        "物品": "宣传海报",
        "别名": "海报",
        "位置": "C区2号货架第一层",
        "数量": 20,
        "参考供价": 2.6,
        "规格型号": "A2 铜版纸 157g",
    },
    {
        "标识": "QF01",
        "门店": "滨江店",
        "物品": "宣传海报",
        "别名": "海报",
        "位置": "店内外侧",
        "数量": 40,
        "参考供价": 2.6,
        "规格型号": "A2 铜版纸 157g",
    },
]

UNASKED_VALUES = ("店内外侧", "C区2号货架第一层", "A2 铜版纸 157g", "2.6", "40")

MANY_ROWS = ROWS + [
    {
        "标识": f"QF{index:02d}",
        "门店": store,
        "物品": "宣传海报",
        "别名": "海报",
        "位置": f"{store}位置",
        "数量": index,
        "参考供价": 2.6,
        "规格型号": "A2 铜版纸 157g",
    }
    for index, store in enumerate(
        ("城东店", "城南店", "城北店", "湖滨店", "高新店", "经开店", "临港店", "中心店", "东湖店", "西湖店"),
        start=3,
    )
]


def _seed(rag_index, add_records) -> None:
    add_records(
        ROWS,
        doc=DocumentSpec(
            doc_id="E11",
            source_path="e11.xlsx",
            title="终端物料位置表",
            file_kind="xlsx",
            version_id="E11-v1",
            version_label="当前",
            sha256="e" * 64,
            business_date="2026-10-28",
        ),
    )


def _ask(rag_index, conversation: str, question: str):
    return rag_index.ask(question, user_id="u", conversation_id=conversation)


def test_location_followup_answers_location_only(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-loc", "城西店的宣传海报在哪里？")
    assert first.kind == "answer", first.text
    assert "C区2号货架第一层" in first.text

    followup = _ask(rag_index, "c-loc", "那个海报呢")
    assert followup.kind == "answer", followup.text
    assert "C区2号货架第一层" in followup.text
    assert "A2 铜版纸 157g" not in followup.text
    assert "2.6" not in followup.text
    assert "20" not in followup.text
    assert followup.state["field_role"] == "location"
    # “只答该字段”不是枚举页：状态里不得残留枚举标记。
    assert followup.state["enumerate"] is False


def test_quantity_followup_answers_quantity_only(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-qty", "城西店的宣传海报的数量是多少？")
    assert "20" in first.text

    followup = _ask(rag_index, "c-qty", "那个海报呢")
    assert followup.kind == "answer", followup.text
    assert "20" in followup.text
    assert "C区2号货架第一层" not in followup.text
    assert "A2 铜版纸 157g" not in followup.text
    assert "2.6" not in followup.text
    assert followup.state["field_role"] == "quantity"


def test_price_followup_answers_price_only(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-price", "城西店的宣传海报的参考供价是多少？")
    assert "2.6" in first.text

    followup = _ask(rag_index, "c-price", "那个海报呢")
    assert followup.kind == "answer", followup.text
    assert "2.6" in followup.text
    assert "C区2号货架第一层" not in followup.text
    assert "A2 铜版纸 157g" not in followup.text
    assert "20" not in followup.text
    assert followup.state["field_role"] == "price"


def test_spec_followup_answers_spec_only(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-spec", "城西店的宣传海报的规格型号是什么？")
    assert "A2 铜版纸 157g" in first.text

    followup = _ask(rag_index, "c-spec", "那个海报呢")
    assert followup.kind == "answer", followup.text
    assert "A2 铜版纸 157g" in followup.text
    assert "C区2号货架第一层" not in followup.text
    assert "2.6" not in followup.text
    assert "20" not in followup.text
    assert followup.state["field_role"] == "spec"


def test_anaphora_without_context_asks_which_field(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    answer = _ask(rag_index, "c-fresh", "那个海报呢")

    assert answer.kind == "clarification", answer.text
    assert answer.reason == "ANAPHORA_NO_FIELD"
    assert "哪项信息" in answer.text
    for value in UNASKED_VALUES:
        assert value not in answer.text, (value, answer.text)
    assert answer.state["item"] == "宣传海报"


def test_anaphora_without_entity_clarifies_referent(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    answer = _ask(rag_index, "c-bare", "那个呢")

    assert answer.kind == "clarification", answer.text
    assert answer.reason == "ANAPHORA_NO_ENTITY"
    assert "哪个物品" in answer.text


def test_anaphora_without_unique_entity_does_not_dump_fields(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-multi", "宣传海报在哪里？")
    assert first.kind == "ambiguous", first.text

    followup = _ask(rag_index, "c-multi", "那个海报呢")
    assert followup.kind == "ambiguous", followup.text
    assert "C区2号货架第一层" not in followup.text
    assert "A2 铜版纸 157g" not in followup.text


def test_anaphora_after_multi_field_question_asks_which_field(rag_index, add_records) -> None:
    """上文问了两个字段时没有唯一的“问什么”可继承：应澄清，不得整条渲染。"""
    _seed(rag_index, add_records)
    first = _ask(rag_index, "c-many", "城西店的宣传海报的位置和数量是什么？")
    assert first.kind == "answer", first.text
    assert "C区2号货架第一层" in first.text
    assert "20" in first.text

    followup = _ask(rag_index, "c-many", "那个海报呢")
    assert followup.kind == "clarification", followup.text
    assert followup.reason == "ANAPHORA_NO_FIELD"
    assert "哪项信息" in followup.text
    for value in UNASKED_VALUES:
        assert value not in followup.text, (value, followup.text)


def test_explicit_enumeration_is_not_treated_as_field_followup(rag_index, add_records) -> None:
    _seed(rag_index, add_records)
    _ask(rag_index, "c-list", "城西店的宣传海报在哪里？")

    listed = _ask(rag_index, "c-list", "把那个海报的位置列出来")
    assert listed.kind == "answer", listed.text
    assert "共 " in listed.text
    assert listed.state["enumerate"] is True


def _seed_many(rag_index, add_records) -> None:
    add_records(
        MANY_ROWS,
        doc=DocumentSpec(
            doc_id="E11",
            source_path="e11.xlsx",
            title="终端物料位置表",
            file_kind="xlsx",
            version_id="E11-v1",
            version_label="当前",
            sha256="e" * 64,
            business_date="2026-10-28",
        ),
    )


def test_anaphora_page_after_enumeration_keeps_pagination(rag_index, add_records) -> None:
    """T105 R1/B1：枚举后「那个海报的第2页」不得被指代澄清分支劫持。"""
    _seed_many(rag_index, add_records)
    first = _ask(rag_index, "c-page", "把宣传海报都列出来")
    assert first.kind == "answer", first.text
    assert first.diagnostics["page"] == 1
    assert first.diagnostics["total"] == 12

    second = _ask(rag_index, "c-page", "那个海报的第2页")
    assert second.kind == "answer", second.text
    assert second.state["page"] == 2
    assert second.state["enumerate"] is True
    assert second.diagnostics["page"] == 2
    assert second.diagnostics["total"] == 12
    assert second.diagnostics["returned"] == 2
    assert "第 2 页" in second.text


def test_bare_page_after_enumeration_keeps_pagination(rag_index, add_records) -> None:
    """单独「第2页」（无指代）行为不变。"""
    _seed_many(rag_index, add_records)
    _ask(rag_index, "c-bare-page", "把宣传海报都列出来")

    second = _ask(rag_index, "c-bare-page", "第2页")
    assert second.kind == "answer", second.text
    assert second.state["page"] == 2
    assert second.diagnostics["page"] == 2


def test_new_content_record_field_followup_answers_that_field_only(rag_index, add_records) -> None:
    """T105 R1/B2：带新内容的指代追问若问到记录字段，仍只答该字段。"""
    _seed(rag_index, add_records)
    _ask(rag_index, "c-new-spec", "城西店的宣传海报在哪里？")

    answer = _ask(rag_index, "c-new-spec", "那个海报的规格型号呢")
    assert answer.kind == "answer", answer.text
    assert "A2 铜版纸 157g" in answer.text
    for value in ("C区2号货架第一层", "2.6", "20", "QF02"):
        assert value not in answer.text, (value, answer.text)
    assert answer.state["field_role"] == "spec"


def test_new_content_non_field_followup_does_not_dump(rag_index, add_records) -> None:
    """T105 R1/B2：打印材质/陈列要求不是台账字段，不得整条倾倒，也不得列未问值。"""
    _seed(rag_index, add_records)
    for conversation, question in (
        ("c-new-material", "那个海报的打印材质呢"),
        ("c-new-display", "那个海报的陈列要求呢"),
    ):
        _ask(rag_index, conversation, "城西店的宣传海报在哪里？")
        answer = _ask(rag_index, conversation, question)

        assert answer.kind == "no_answer", answer.text
        assert answer.reason == "ANAPHORA_NEW_CONTENT", answer.text
        # T106 R1：不再断言“资料中未记录”（系统未检索，不得冒充资料缺失）；
        # 改为断言同义的“不属于台账字段的新内容”文案，断言语义不变。
        assert "不属于台账字段" in answer.text
        for value in UNASKED_VALUES:
            assert value not in answer.text, (value, answer.text)
        assert not answer.citations


POLICY_TEXT = (
    "第七条 常规物料需求每周五 17:00 前提交，市场部次周二集中下单；档期物料须提前 21 天提报。",
    "第四条 宣传海报的审批流程：市场部通路行销组发起，门店店长确认。",
)
REGULATION_TEXT = (
    "第二十七条 本规定自 2022年7月1日起施行。2000年10月31日原中华人民共和国国家发展计划委员会令第8号发布的《关于商品和服务实行明码标价的规定》、2001年11月7日原中华人民共和国国家发展计划委员会令第15号发布的《禁止价格欺诈行为的规定》同时废止。",
    "第二条 本规定所称价格欺诈，是指经营者利用虚假的或者使人误解的价格手段，诱骗消费者或者其他经营者与其进行交易的行为。",
)


def _seed_policy_docs(rag_index, add_records) -> None:
    add_records(
        [],
        doc=DocumentSpec(
            doc_id="W02",
            source_path="w02.docx",
            title="广宣物料与道具管理办法",
            file_kind="docx",
            version_id="W02-v1",
            version_label="当前",
            sha256="a" * 64,
            business_date="2026-10-28",
        ),
        text_units=[{"text": text, "kind": "paragraph"} for text in POLICY_TEXT],
    )
    add_records(
        [],
        doc=DocumentSpec(
            doc_id="L56",
            source_path="l56.docx",
            title="明码标价和禁止价格欺诈规定",
            file_kind="docx",
            version_id="L56-v1",
            version_label="当前",
            sha256="b" * 64,
            business_date="2026-10-28",
        ),
        text_units=[{"text": text, "kind": "paragraph"} for text in REGULATION_TEXT],
    )


def test_anaphora_policy_followup_answers_from_policy_text(rag_index, add_records) -> None:
    """T105 R2/C3：实体+指代+政策题不得被压成未记录，应从制度正文答 21 天。"""
    _seed(rag_index, add_records)
    _seed_policy_docs(rag_index, add_records)
    _ask(rag_index, "c-r2-policy", "城西店的宣传海报在哪里？")

    answer = _ask(rag_index, "c-r2-policy", "那个海报的档期物料要提前多少天提报需求？")
    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "21" in answer.text, answer.text
    assert "C区2号货架第一层" not in answer.text, answer.text
    assert "标识：" not in answer.text, answer.text


@pytest.mark.parametrize(
    "question",
    ("那个海报的价格欺诈规定是什么？", "那个海报的相关规定是什么？", "那个海报适用的价格欺诈规定是什么？"),
)
def test_anaphora_regulation_followup_answers_regulation_not_inherited_field(
    rag_index, add_records, question: str
) -> None:
    """T105 R2/C5 系列：法规追问不得返回继承的位置，应从法规正文作答。"""
    _seed(rag_index, add_records)
    _seed_policy_docs(rag_index, add_records)
    conversation = "c-r2-reg-" + str(abs(hash(question)))
    _ask(rag_index, conversation, "城西店的宣传海报在哪里？")

    answer = _ask(rag_index, conversation, question)
    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "规定" in answer.text, answer.text
    assert "C区2号货架第一层" not in answer.text, answer.text
    assert "标识：" not in answer.text, answer.text


def test_anaphora_regulation_followup_after_spec_does_not_inherit_spec(rag_index, add_records) -> None:
    """T105 R2/C5d：上文问规格后，法规追问也不得随上文返回规格字段。"""
    _seed(rag_index, add_records)
    _seed_policy_docs(rag_index, add_records)
    _ask(rag_index, "c-r2-reg-spec", "城西店的宣传海报的规格型号是什么？")

    answer = _ask(rag_index, "c-r2-reg-spec", "那个海报的价格欺诈规定是什么？")
    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "欺诈" in answer.text, answer.text
    assert "A2 铜版纸 157g" not in answer.text, answer.text


def test_anaphora_process_followup_answers_from_document(rag_index, add_records) -> None:
    """T105 R2/C6：实体+指代+流程题不得被压成未记录，应从正文作答。"""
    _seed(rag_index, add_records)
    _seed_policy_docs(rag_index, add_records)
    _ask(rag_index, "c-r2-flow", "城西店的宣传海报在哪里？")

    answer = _ask(rag_index, "c-r2-flow", "那个海报的审批流程是什么？")
    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "审批流程" in answer.text, answer.text
    assert "C区2号货架第一层" not in answer.text, answer.text


def test_anaphora_date_followup_without_field_does_not_claim_no_record(rag_index, add_records) -> None:
    """T105 R2/C7（P2）：记录存在、仅缺日期字段时，文案不得称“未找到记录”。"""
    _seed(rag_index, add_records)
    _ask(rag_index, "c-r2-date", "城西店的宣传海报在哪里？")

    answer = _ask(rag_index, "c-r2-date", "那个海报的盘点时间是什么？")
    assert answer.kind == "no_answer", (answer.reason, answer.text)
    assert "未记录" in answer.text, answer.text
    assert "未在资料中找到" not in answer.text, answer.text


def test_bare_policy_question_without_anaphora_still_answers_from_text(rag_index, add_records) -> None:
    """控制组：不带指代的政策题行为不变（T102 口径）。"""
    _seed(rag_index, add_records)
    _seed_policy_docs(rag_index, add_records)
    _ask(rag_index, "c-r2-bare-policy", "城西店的宣传海报在哪里？")

    answer = _ask(rag_index, "c-r2-bare-policy", "档期物料要提前多少天提报需求？")
    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "21" in answer.text, answer.text
    assert "城西店" not in answer.text, answer.text
