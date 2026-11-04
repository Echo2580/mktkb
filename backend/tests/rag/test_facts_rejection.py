"""事实准入：伪造值、夹带无关值、跨实体、跨字段角色、失效来源与无依据拒绝。"""

from __future__ import annotations

from dataclasses import replace

import pytest

from mktkb.rag import Fact, QueryState
from mktkb.rag.errors import CrossEntity, CrossField, ForgedValue, StaleSource, UnsupportedClaim
from mktkb.rag.facts import FactValidator
from mktkb.rag.query import build_lexicon, parse_query


def _setup(rag_index, add_records):
    doc = add_records(
        [
            {"标识": "QF01", "门店": "滨江店", "物品": "宣传海报", "位置": "店内外侧", "数量": 40, "单位": "张"},
            {"标识": "QF02", "门店": "鹿鸣路店", "物品": "宣传海报", "位置": "入口堆头旁", "数量": 24, "单位": "张"},
        ]
    )
    lexicon = build_lexicon(rag_index.lexicon_data())
    plan = parse_query(
        "滨江店的宣传海报位置",
        previous=QueryState(user_id="u", conversation_id="c"),
        lexicon=lexicon,
        business_date="2026-10-28",
    )
    answer = rag_index.ask("滨江店的宣传海报位置", user_id="u", conversation_id="c")
    assert answer.kind == "answer"
    assert answer.facts
    return doc, plan, answer.facts[0], FactValidator(rag_index, plan, lexicon)


def test_correct_fact_passes_and_forged_value_rejected(rag_index, add_records):
    _doc, _plan, fact, validator = _setup(rag_index, add_records)
    validator.validate_fact(fact)
    with pytest.raises(ForgedValue):
        validator.validate_fact(replace(fact, value="D区暂存柜"))


def test_correct_value_with_unrelated_value_is_rejected(rag_index, add_records):
    _doc, _plan, fact, validator = _setup(rag_index, add_records)
    with pytest.raises(ForgedValue):
        validator.validate_record_text("根据资料，滨江店的宣传海报的位置是店内外侧，数量999张。", [fact])
    with pytest.raises((ForgedValue, UnsupportedClaim)):
        validator.validate_record_text("根据资料，滨江店的宣传海报的位置是店内外侧，另一位置是D区。", [fact])


def test_cross_entity_and_cross_field_are_rejected(rag_index, add_records):
    _doc, _plan, fact, validator = _setup(rag_index, add_records)
    with pytest.raises(CrossEntity):
        validator.validate_fact(replace(fact, entity_key="item|鹿鸣路店|宣传海报"))
    quantity_fact = Fact(
        entity_key=fact.entity_key,
        entity_label=fact.entity_label,
        field_role="quantity",
        field_label="数量",
        value="40",
        source_chunk_id=fact.source_chunk_id,
        source_unit_id=fact.source_unit_id,
        doc_id=fact.doc_id,
        version_id=fact.version_id,
        revision=fact.revision,
    )
    with pytest.raises(CrossField):
        validator.validate_fact(quantity_fact)


def test_deleted_source_is_rejected(rag_index, add_records):
    doc, _plan, fact, validator = _setup(rag_index, add_records)
    rag_index.remove_document(doc.doc_id)
    with pytest.raises(StaleSource):
        validator.validate_fact(fact)


def test_empty_facts_are_rejected(rag_index, add_records):
    _doc, _plan, _fact, validator = _setup(rag_index, add_records)
    with pytest.raises(UnsupportedClaim):
        validator.validate_record_text("根据资料，滨江店的宣传海报的位置是店内外侧。", [])
