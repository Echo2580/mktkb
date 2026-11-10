"""T101：ERR-03 缺失字段词表的语境约束与法规优先（离线单元用例）。

只调用意图层 ``parse_question``，不建索引、不调模型：
- 法规/制度题（《…规定》、第 X 条、规定/制度等）优先按正文检索，不判缺失字段；
- 「价格」「销售」只有在同时给出门店与物品（确有所指记录）且没有更明确的字段说法时才算缺字段；
- 明确字段名（采购价格/销售额/负责人/营业时间/库存）保持原有缺字段行为。
"""

from __future__ import annotations

from mktkb.conversations import intent as intent_module
from mktkb.rag.query import is_regulation_question

#: ERR-20261104-03 影响面（corpus/enterprise-20261101/questions.json）
REGULATION_QUESTIONS = (
    "《明码标价和禁止价格欺诈规定》自何时起施行？同时废止了哪两个规定？",
    "进行价格比较时，未标明被比较价格详细信息的，被比较价格有什么限制？",
    "抽奖式有奖销售的最高奖金额上限是多少？",
    "违反反不正当竞争法第十一条进行有奖销售的，罚款幅度是多少？",
)


def _lexicon() -> intent_module.EntityLexicon:
    return intent_module.EntityLexicon(
        store_labels=("城东店", "城西店", "滨江店"),
        item_labels=("宣传海报", "柠檬茶 500ml"),
        alias_to_labels={"海报": ("宣传海报",)},
    )


def test_regulation_questions_are_not_judged_as_missing_fields() -> None:
    for question in REGULATION_QUESTIONS:
        plan = intent_module.parse_question(question, lexicon=_lexicon())
        assert plan.missing_fields == (), (question, plan.missing_fields)
        assert plan.requested_fields == (), (question, plan.requested_fields)
        assert plan.mode == "document", (question, plan.mode)
        assert plan.intent is not None and plan.intent.terms, question


def test_explicit_missing_fields_still_reported() -> None:
    cases = {
        "宣传海报的采购价格是多少？": "采购价格",
        "城西店本月销售额是多少？": "销售额",
        "城东店宣传海报的负责人是谁？": "负责人",
        "城东店几点营业？": "营业时间",
        "城东店海报现在剩余多少张？": "库存",
        "城东店的执照号是多少？": "营业执照号",
    }
    for question, label in cases.items():
        plan = intent_module.parse_question(question, lexicon=_lexicon())
        assert plan.missing_fields == (label,), (question, plan.missing_fields)


def test_generic_price_word_needs_record_entity() -> None:
    # 门店+物品（确有所指记录）：泛化词「价格」仍按采购价格缺失处理（真实缺字段行为不变）。
    with_record = intent_module.parse_question("滨江店柠檬茶 500ml 的价格是多少？", lexicon=_lexicon())
    assert with_record.missing_fields == ("采购价格",)

    # 只提商品/渠道：属于价目表取值问题，不再判成采购价格缺失（ERR-03/E095）。
    item_only = intent_module.parse_question("柠檬茶 500ml 的价格是多少？", lexicon=_lexicon())
    assert item_only.missing_fields == ()
    assert item_only.mode == "document"

    # 没有物品实体：不再因题干出现「价格」就判成采购价格缺失（ERR-03/E087）。
    without_item = intent_module.parse_question(
        "2025 年 Q4 柠檬茶在 NKA卖场的特价还是现在的有效价格吗？", lexicon=_lexicon()
    )
    assert without_item.missing_fields == ()
    assert without_item.mode == "document"


def test_regulation_priority_also_covers_explicit_field_words() -> None:
    # 法规题优先于缺失字段判定：即使题干写了负责人/采购价格，也先走正文检索。
    for question in (
        "《明码标价和禁止价格欺诈规定》对负责人有什么要求？",
        "《明码标价和禁止价格欺诈规定》里采购价格的标注要求是什么？",
    ):
        plan = intent_module.parse_question(question, lexicon=_lexicon())
        assert plan.missing_fields == (), (question, plan.missing_fields)
        assert plan.mode == "document"


def test_regulation_question_detection() -> None:
    assert is_regulation_question("《明码标价和禁止价格欺诈规定》自何时起施行？")
    assert is_regulation_question("违反反不正当竞争法第十一条进行有奖销售的，罚款幅度是多少？")
    assert is_regulation_question("按管理制度，陈列高度不足怎么扣分？")
    # 《…通知》是记录题的资料来源，不是法规题。
    assert not is_regulation_question(
        "按《关于部分门店物料临时调整存放位置的通知》，滨江店的宣传海报（标识：QF01）调整后位于哪里？"
    )
    assert not is_regulation_question("滨江店的宣传海报在哪里？")
    assert not is_regulation_question("抽奖式有奖销售的最高奖金额上限是多少？")
