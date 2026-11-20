"""S2-B 标识作用域：跨门店/物品复用同一标识时按命中记录自己的业务范围分组。

被验证的产品行为（只改 ``rag/answer.py::_answer_record`` 的非枚举记录消歧分组）：
- 同一标识被两家门店复用（canonical ``item|id:…`` 相同）时，首问落到既有
  ``MULTIPLE_ENTITIES`` 澄清，两个候选都能用产品同模板追问收敛到各自那条记录；
- 值偶然相同（两店同位置）也必须澄清，不能因值相同推成同一实体；
- 同店同号但物品不同（业务范围可区分）同样澄清，候选分别指向不同物品；
- 同店同物品同号、两个不同有效位置仍是 ``conflict``，canonical ``entity_key`` 不变。

先红后绿：改前 A1/A3 是 ``answer``、A4 是 ``conflict``、A1 的跨店对照会触发
``CROSS_ENTITY`` 拒答；A2 因首轮不是 ``ambiguous`` 直接失败。全部合成店名/物品/
标识/值/位置，不读 fixtures、题面或真实数据。
"""

from __future__ import annotations

from mktkb import copy as copy_module
from mktkb.retrieval.tokenize import normalize

STORE_A = "青禾店"
STORE_B = "南屿店"
ITEM_A = "折叠桌"
ITEM_B = "展架"
ID_SHARED = "IB-S2B-1"
ID_DUP_VALUES = "IB-S2B-2"
ID_DUP_ITEMS = "IB-S2B-3"
ID_CONFLICT = "IB-S2B-4"
LOC_A = "A区一层"
LOC_B = "B区二层"


def _row(store: str, item: str, identifier: str, location: str) -> dict[str, str]:
    return {"门店": store, "物品": item, "标识": identifier, "位置": location}


def _canonical(identifier: str) -> str:
    return f"item|id:{normalize(identifier)}"


def _rows(payload) -> list[int]:
    return sorted(
        {item.locator.get("row") for item in payload.citations if item.locator.get("row")}
    )


def _candidate_labels(payload) -> list[str]:
    return [str(label) for label in payload.state.get("candidates") or ()]


def _converge(rag_index, conversation: str, label: str):
    """用与产品层同模板的追问（``copy.clarification_followup``）选择候选。"""

    question = copy_module.clarification_followup(label, "location")
    return rag_index.ask(question, user_id="u", conversation_id=conversation)


# --------------------------------------------------------------------------- #
# A1/A2 跨门店同号同物品、位置不同：先澄清，再两个候选各自收敛
# --------------------------------------------------------------------------- #


def test_a1_cross_store_same_identifier_is_ambiguous(rag_index, add_records):
    add_records(
        [
            _row(STORE_A, ITEM_A, ID_SHARED, LOC_A),
            _row(STORE_B, ITEM_A, ID_SHARED, LOC_B),
        ]
    )
    answer = rag_index.ask(
        f"标识 {ID_SHARED} 的位置是什么？", user_id="u", conversation_id="a1"
    )
    assert answer.kind == "ambiguous", (answer.kind, answer.reason, answer.text)
    assert answer.reason == "MULTIPLE_ENTITIES", answer.reason
    labels = _candidate_labels(answer)
    assert len(labels) == 2, labels
    assert any(STORE_A in label for label in labels), labels
    assert any(STORE_B in label for label in labels), labels
    assert answer.facts == [], answer.facts
    assert answer.citations == [], answer.citations


def test_a2_both_candidate_followups_converge(rag_index, add_records):
    add_records(
        [
            _row(STORE_A, ITEM_A, ID_SHARED, LOC_A),
            _row(STORE_B, ITEM_A, ID_SHARED, LOC_B),
        ]
    )
    conversation = "a2"
    opening = rag_index.ask(
        f"标识 {ID_SHARED} 的位置是什么？", user_id="u", conversation_id=conversation
    )
    assert opening.kind == "ambiguous", (opening.kind, opening.reason, opening.text)
    labels = _candidate_labels(opening)
    assert len(labels) == 2, labels
    expected = {STORE_A: (LOC_A, 7), STORE_B: (LOC_B, 8)}
    other_of = {STORE_A: STORE_B, STORE_B: STORE_A}
    for label in labels:
        store = next(name for name in expected if name in label)
        answer = _converge(rag_index, conversation, label)
        value, row = expected[store]
        assert answer.kind == "answer", (store, answer.kind, answer.reason, answer.text)
        assert len(answer.facts) == 1, answer.facts
        assert len(answer.citations) == 1, answer.citations
        assert answer.facts[0].value == value, answer.facts[0].value
        assert answer.citations[0].locator.get("row") == row, answer.citations[0].locator
        assert value in answer.text, answer.text
        assert expected[other_of[store]][0] not in answer.text, answer.text
        assert answer.facts[0].entity_key == _canonical(ID_SHARED), answer.facts[0].entity_key


# --------------------------------------------------------------------------- #
# A3 值偶然相同：仍须澄清，不得因值相同推断成同一实体
# --------------------------------------------------------------------------- #


def test_a3_same_location_across_stores_still_ambiguous(rag_index, add_records):
    add_records(
        [
            _row(STORE_A, ITEM_A, ID_DUP_VALUES, LOC_A),
            _row(STORE_B, ITEM_A, ID_DUP_VALUES, LOC_A),
        ]
    )
    answer = rag_index.ask(
        f"标识 {ID_DUP_VALUES} 的位置是什么？", user_id="u", conversation_id="a3"
    )
    assert answer.kind == "ambiguous", (answer.kind, answer.reason, answer.text)
    assert answer.reason == "MULTIPLE_ENTITIES", answer.reason
    labels = _candidate_labels(answer)
    assert len(labels) == 2, labels
    assert any(STORE_A in label for label in labels), labels
    assert any(STORE_B in label for label in labels), labels
    assert answer.facts == [], answer.facts
    assert answer.citations == [], answer.citations


# --------------------------------------------------------------------------- #
# A4 同店同号、物品不同：范围可区分 → 澄清，候选分别收敛到对应物品行
# --------------------------------------------------------------------------- #


def test_a4_same_store_different_items_is_ambiguous_and_converges(rag_index, add_records):
    add_records(
        [
            _row(STORE_A, ITEM_A, ID_DUP_ITEMS, LOC_A),
            _row(STORE_A, ITEM_B, ID_DUP_ITEMS, "A区九层"),
        ]
    )
    conversation = "a4"
    opening = rag_index.ask(
        f"标识 {ID_DUP_ITEMS} 的位置是什么？", user_id="u", conversation_id=conversation
    )
    assert opening.kind == "ambiguous", (opening.kind, opening.reason, opening.text)
    assert opening.reason == "MULTIPLE_ENTITIES", opening.reason
    labels = _candidate_labels(opening)
    assert len(labels) == 2, labels
    assert any(ITEM_A in label for label in labels), labels
    assert any(ITEM_B in label for label in labels), labels
    assert opening.facts == [], opening.facts
    assert opening.citations == [], opening.citations
    expected = {ITEM_A: (LOC_A, 7), ITEM_B: ("A区九层", 8)}
    for label in labels:
        item = next(name for name in expected if name in label)
        answer = _converge(rag_index, conversation, label)
        value, row = expected[item]
        assert answer.kind == "answer", (item, answer.kind, answer.reason, answer.text)
        assert len(answer.facts) == 1, answer.facts
        assert len(answer.citations) == 1, answer.citations
        assert answer.facts[0].value == value, answer.facts[0].value
        assert answer.citations[0].locator.get("row") == row, answer.citations[0].locator
        assert answer.facts[0].entity_key == _canonical(ID_DUP_ITEMS), answer.facts[0].entity_key


# --------------------------------------------------------------------------- #
# A5 同店同物品同号、两个可见有效位置：仍是既有 conflict，身份键不变
# --------------------------------------------------------------------------- #


def test_a5_same_scope_conflicting_locations_stay_conflict(rag_index, add_records):
    add_records(
        [
            _row(STORE_A, ITEM_A, ID_CONFLICT, LOC_A),
            _row(STORE_A, ITEM_A, ID_CONFLICT, "A区二层"),
        ]
    )
    answer = rag_index.ask(
        f"标识 {ID_CONFLICT} 的位置是什么？", user_id="u", conversation_id="a5"
    )
    # ``conflict`` 分支在返回前用 ``_fact_gate`` + ``FactValidator`` 校验过，
    # 走到这里即证明准入通过（校验失败会变成 ``no_answer``/``rejected``）。
    assert answer.kind == "conflict", (answer.kind, answer.reason, answer.text)
    assert answer.reason == "CONFLICTING_VALUES", answer.reason
    assert {fact.value for fact in answer.facts} == {LOC_A, "A区二层"}, answer.facts
    assert _rows(answer) == [7, 8], [item.locator for item in answer.citations]
    assert all(fact.entity_key == _canonical(ID_CONFLICT) for fact in answer.facts)
    assert LOC_A in answer.text and "A区二层" in answer.text, answer.text


# --------------------------------------------------------------------------- #
# A6 既有边界：同名异号 / 已限定范围 / 未知标识 / 不匹配门店
# --------------------------------------------------------------------------- #


def test_a6_same_name_different_identifiers_keeps_item_semantics(rag_index, add_records):
    add_records(
        [
            _row(STORE_A, ITEM_A, "IB-S2B-5", LOC_A),
            _row(STORE_A, ITEM_A, "IB-S2B-6", "A区二层"),
            _row(STORE_B, ITEM_A, "IB-S2B-7", "B区三层"),
        ]
    )
    answer = rag_index.ask(
        f"{ITEM_A}的位置是什么？", user_id="u", conversation_id="a6-name"
    )
    assert answer.kind == "ambiguous", (answer.kind, answer.reason, answer.text)
    assert answer.reason == "MULTIPLE_ENTITIES", answer.reason
    labels = set(_candidate_labels(answer))
    assert any(STORE_A in label for label in labels), labels
    assert any(STORE_B in label for label in labels), labels
    assert answer.facts == [], answer.facts
    assert answer.citations == [], answer.citations


def test_a6_qualified_identifier_uses_only_its_own_row(rag_index, add_records):
    add_records(
        [
            _row(STORE_A, ITEM_A, "IB-S2B-5", LOC_A),
            _row(STORE_B, ITEM_A, "IB-S2B-5", LOC_B),
            _row(STORE_A, ITEM_B, "IB-S2B-8", "C区"),
        ]
    )
    answer = rag_index.ask(
        f"{STORE_A}{ITEM_A} IB-S2B-5 的位置是什么？", user_id="u", conversation_id="a6-qualified"
    )
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert len(answer.facts) == 1, answer.facts
    assert _rows(answer) == [7], [item.locator for item in answer.citations]
    assert answer.facts[0].value == LOC_A, answer.facts[0].value
    assert LOC_B not in answer.text, answer.text


def test_a6_unknown_identifier_returns_no_evidence(rag_index, add_records):
    add_records([_row(STORE_A, ITEM_A, ID_SHARED, LOC_A)])
    answer = rag_index.ask(
        "标识 IB-S2B-999 的位置是什么？", user_id="u", conversation_id="a6-unknown"
    )
    # 未知标识不得作答：rag 内核给安全澄清/拒答（产品层对未知标识映射 not_found，
    # 由既有 ``test_s2b_intent_semantics.py::test_unknown_identifier_and_conflicting_scope_are_refused`` 覆盖）。
    assert answer.kind in {"clarification", "no_answer"}, (answer.kind, answer.reason, answer.text)
    assert answer.facts == [], answer.facts
    assert answer.citations == [], answer.citations


def test_a6_identifier_with_mismatched_store_is_refused(rag_index, add_records):
    add_records(
        [
            _row(STORE_A, ITEM_A, "IB-S2B-5", LOC_A),
            _row(STORE_B, ITEM_B, "IB-S2B-8", LOC_B),
        ]
    )
    answer = rag_index.ask(
        f"{STORE_B}{ITEM_B} IB-S2B-5 的位置是什么？",
        user_id="u",
        conversation_id="a6-mismatch",
    )
    assert answer.kind == "no_answer", (answer.kind, answer.reason, answer.text)
    assert answer.facts == [], answer.facts
    assert answer.citations == [], answer.citations


# --------------------------------------------------------------------------- #
# A7 身份契约：fact 的 entity_key 与来源块 canonical 键逐字一致
# --------------------------------------------------------------------------- #


def test_a7_fact_entity_key_matches_source_chunk(rag_index, add_records):
    add_records(
        [
            _row(STORE_A, ITEM_A, ID_SHARED, LOC_A),
            _row(STORE_B, ITEM_A, ID_SHARED, LOC_B),
        ]
    )
    conversation = "a7"
    opening = rag_index.ask(
        f"标识 {ID_SHARED} 的位置是什么？", user_id="u", conversation_id=conversation
    )
    assert opening.kind == "ambiguous", (opening.kind, opening.reason, opening.text)
    answer = _converge(rag_index, conversation, _candidate_labels(opening)[0])
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert len(answer.facts) == 1, answer.facts
    fact = answer.facts[0]
    chunk = rag_index.get_chunk(fact.source_chunk_id)
    assert chunk is not None, fact.source_chunk_id
    assert chunk.entity_key == _canonical(ID_SHARED), chunk.entity_key
    assert fact.entity_key == chunk.entity_key, (fact.entity_key, chunk.entity_key)
