"""v3-fix-2/A：信息足够的记录题不再被“资料缺失/资料歧义”抢占而判澄清。

复现面（合成、离线）：本轮已点名 **2 个门店 + 1 个物品 + 记录字段角色**，题面里带
“按店家资料/按通知”这类顺带提及，或带一个非量化的回指词（“那个位置”）。
改前：``_missing_document`` 命中“资料”字样 → 规划层给出 ``DOCUMENT_NOT_FOUND``
（``mode=document``、``filters={}``、``enumerate=False``、``clarification`` 非空）
→ 产品层 ``_rag_owns_turn`` 为假 → 交回 legacy → legacy 判“多个实体”→ 澄清。
这与 v3 首轮封存证据里 C20/C22/C30 的 ``plan_observed`` 签名逐字段相同
（``mode=document`` / ``filters={}`` / ``enumerate=false`` / ``clarification=true``
/ ``path=legacy``）。

改后：本轮按 ``MULTI_TARGET_ENUMERATE`` 由内核逐条作答；带个人联系字段的合并请求仍在
检索前按 ``SECURITY_RESTRICTED_CONTACT`` 拒答。

反例（真歧义必须仍澄清）：两店 × 两物品交叉 ``ITEM_AMBIGUOUS``；纯指代（这两个/这几个）
``MULTIPLE_ENTITIES``；词表外门店 + 纯指代仍澄清；点名未收录资料的题仍 ``DOCUMENT_NOT_FOUND``。

全部离线：临时 SQLite + 确定性 offline provider；不建产品库、不调模型/embedding/rerank、
不开端口、不发请求。
"""

from __future__ import annotations

import pytest

from mktkb.conversations.service import _rag_owns_turn
from mktkb.rag.query import DocumentRef, Lexicon, parse_query
from mktkb.rag.types import QueryState

#: ``doc_id`` 按产品运行期形态（``str(Document.id)`` = UUID 字符串）构造；
#: 标题按 v3 ingest 的实际命名形态（带 ``Dxx_``/``Vxx_`` 代号前缀）。
LEXICON = Lexicon(
    stores=("城东店", "城西店"),
    items=("宣传海报", "展架", "价签卡纸"),
    field_labels=("位置", "联系人", "电话", "地址"),
    documents=(
        DocumentRef(doc_id="3f1f9a6e-2f4d-4c7a-9b3d-0a1b2c3d4e01", title="D01_物品位置表.xlsx"),
        DocumentRef(doc_id="7c2e8b1a-9d3f-4a5b-8c6d-1e2f3a4b5c02", title="D02_合作店家信息.xlsx"),
        DocumentRef(doc_id="b5a4c3d2-1e0f-4a9b-8c7d-6e5f4a3b2c03", title="V07_物料位置独立通知.pdf"),
    ),
)

RECORDS = [
    {"标识": "P01", "门店": "城东店", "物品": "宣传海报", "位置": "A区1号货架"},
    {"标识": "P02", "门店": "城西店", "物品": "宣传海报", "位置": "B区2号货架"},
    {"标识": "P03", "门店": "城东店", "物品": "展架", "位置": "C区门口"},
    {"标识": "P04", "门店": "城西店", "物品": "展架", "位置": "D区立柱"},
    {"标识": "P05", "门店": "城东店", "物品": "价签卡纸", "位置": "E区3号端架"},
    {"标识": "P06", "门店": "城西店", "物品": "价签卡纸", "位置": "F区4号端架"},
]


def _plan(question: str, previous: QueryState | None = None):
    return parse_query(question, previous=previous, lexicon=LEXICON, business_date="2026-10-15")


def _seed(add_records, make_doc) -> None:
    add_records(RECORDS, doc=make_doc(title="D01_物品位置表.xlsx"))


# --------------------------------------------------------------- A 正例（规划层）


@pytest.mark.parametrize(
    "question",
    [
        # 题面顺带提到“店家资料”：改前命中 _missing_document → DOCUMENT_NOT_FOUND → 澄清
        "城东店和城西店的价签卡纸那个位置，按店家资料确认一下",
        # 题面点名两份资料：改前走 DOCUMENT_AMBIGUOUS → 澄清
        "城东店和城西店的价签卡纸那个位置在D01和D02里分别是多少",
    ],
)
def test_record_scope_with_document_words_is_answered_not_clarified(question: str):
    plan = _plan(question)
    assert plan.reason == "MULTI_TARGET_ENUMERATE", (plan.reason, plan.clarification)
    assert plan.clarification is None
    assert plan.enumerate is True
    assert plan.mode == "record"
    # 产品层必须把该轮交给内核（改前为 False → legacy 多实体澄清）。
    assert _rag_owns_turn(QueryState(), plan) is True


def test_missing_document_still_fires_without_record_scope():
    """反例：点名未收录资料、没有记录实体/记录字段 → 仍按“资料未收录”判缺失。"""
    plan = _plan("促销活动台账在哪里")
    assert plan.reason == "DOCUMENT_NOT_FOUND"
    assert plan.clarification is not None
    assert plan.mode == "document"
    assert _rag_owns_turn(QueryState(), plan) is False


# --------------------------------------------------------------- A 正例（内核 e2e）


def test_multi_store_single_item_answers_instead_of_clarifying(rag_index, add_records, make_doc):
    _seed(add_records, make_doc)
    answer = rag_index.ask(
        "城东店和城西店的价签卡纸那个位置，按店家资料确认一下",
        user_id="u",
        conversation_id="c-fix2-a1",
    )
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert answer.diagnostics["returned"] == 2
    assert "E区3号端架" in answer.text and "F区4号端架" in answer.text
    assert len(answer.citations) == 2


def test_item_scope_with_contact_request_still_refused_before_retrieval(
    rag_index, add_records, make_doc
):
    """安全面不回退：物品记录 + 店家联系人的合并请求仍在检索前拒答。"""
    _seed(add_records, make_doc)
    answer = rag_index.ask(
        "城东店和城西店的价签卡纸那个位置和门店联系电话是多少，按店家资料一起给我",
        user_id="u",
        conversation_id="c-fix2-a2",
    )
    assert answer.kind == "no_answer"
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT"
    assert answer.citations == []
    for value in ("E区3号端架", "F区4号端架"):
        assert value not in answer.text


# --------------------------------------------------------------- A 反例（真歧义仍澄清）


@pytest.mark.parametrize(
    "question",
    [
        # 1) 两店 × 两物品：交叉配对不明
        "城东店和城西店的价签卡纸和宣传海报分别放在哪里",
        # 2) 纯指代：本轮没点名目标
        "城东店和城西店的这两个分别放在哪里",
        # 3) 词表外门店 + 纯指代
        "城东店和城南店的这两个分别放在哪里",
    ],
)
def test_genuine_ambiguity_still_clarifies(question: str):
    plan = _plan(question)
    assert plan.clarification is not None, plan.reason
    assert plan.reason in ("ITEM_AMBIGUOUS", "MULTIPLE_ENTITIES")
    assert _rag_owns_turn(QueryState(), plan) is False


@pytest.mark.parametrize(
    "question",
    [
        "城东店和城西店的价签卡纸和宣传海报分别放在哪里",
        "城东店和城西店的这两个分别放在哪里",
        "城东店和城南店的这两个分别放在哪里",
    ],
)
def test_genuine_ambiguity_still_clarifies_in_kernel(
    rag_index, add_records, make_doc, question: str
):
    _seed(add_records, make_doc)
    answer = rag_index.ask(question, user_id="u", conversation_id="c-fix2-neg-" + str(abs(hash(question)) % 10_000))
    assert answer.kind == "clarification", (answer.kind, answer.reason, answer.text)
    # 不得以“两店全部记录”作答。
    for value in ("E区3号端架", "F区4号端架", "A区1号货架", "B区2号货架"):
        assert value not in answer.text
