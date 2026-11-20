"""R0-4：四案去身份化最小合成复现（只用假实体/假字段/假数值）。

C02：记录枚举答案里的机器指纹（8 位 hex）会被评测数字口径当成额外数值。
C21/C27：枚举单字段/多字段时只渲染 ``plan.field_role`` 的第一个值，丢掉同角色
          的第二个字段列与 ``plan.field_roles`` 里的其余字段。
C12：legacy 记录检索的“只有门店条件”捷径会把同门店的物品行（承载另一期望
      来源）整组丢掉；修复点在 ``mktkb/retrieval/service.py``，超出本任务单
      允许修改的 rag/conversations/qa 范围，故以 strict xfail 记录红例。
"""

from __future__ import annotations

import hashlib
import re

from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.gold import ResolvedGold
from mktkb.evaluation.scorers import (
    EvalCitation,
    EvalOutcome,
    citation_number_keys,
    score_case,
)
from mktkb.rag import AtomicUnit, DocumentSpec
from mktkb.rag.legacy import LegacyIndex
from mktkb.retrieval.service import retrieve
from mktkb.retrieval.types import QueryIntent


# --------------------------------------------------------------------------- #
# C02：枚举答案不得把机器指纹的十进制数字当作业务值
# --------------------------------------------------------------------------- #


def _c02_index(rag_index):
    """单条记录 + 固定身份：行号 1 与数量 1 互相支撑，唯一未落地的数字来自记录指纹。"""

    doc = DocumentSpec(
        doc_id="D-syn-c02",
        logical_id="L-syn-c02",
        source_path="corpus/synthetic-c02.xlsx",
        title="合成物品资料",
        file_kind="xlsx",
        version_id="V-syn-c02-v1",
        version_label="当前",
        sha256=hashlib.sha256(b"synthetic-c02").hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    fields = {"门店": "甲店", "物品": "立牌", "数量": "1", "标识": "QP001", "位置": "甲区"}
    locator = {
        "sheet": "合成表",
        "row": 1,
        "header_row": 0,
        "cells": [
            {"column": "A", "display": "甲店", "header": "门店"},
            {"column": "B", "display": "立牌", "header": "物品"},
            {"column": "C", "display": "1", "header": "数量"},
            {"column": "D", "display": "QP001", "header": "标识"},
            {"column": "E", "display": "甲区", "header": "位置"},
        ],
    }
    unit = AtomicUnit(
        unit_id="U-syn-c02-row1",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key="sheet:合成表:row:1",
        text=" | ".join(f"{name}: {value}" for name, value in fields.items()),
        fields=fields,
        sheet="合成表",
        locator=locator,
        header_row=0,
        row_number=1,
        title=doc.title,
    )
    rag_index.add_document(doc, [unit], embed=False)
    return locator


def _c02_case() -> CaseSpec:
    return CaseSpec(
        case_id="SYN-C02",
        suite="synthetic",
        split="train",
        stratum="exact",
        business_date="2026-10-28",
        question="列出甲店立牌的全部信息",
        expected_kind="answer",
        expected_values=("甲区",),
        reference_answer="甲店立牌的位置是甲区",
    )


def _score_c02(answer, locator) -> dict[str, str]:
    """按 P2 实际口径：引用只带 unit locator（cells），不带产品 answer 正文。"""

    citation = EvalCitation(
        doc_code="D01",
        unit_key="sheet:合成表:row:1",
        unit_ids=("U-syn-c02-row1",),
        locator=dict(locator),
        text="",
        kind="active",
    )
    outcome = EvalOutcome(kind=answer.kind, text=answer.text, citations=(citation,))
    gold = ResolvedGold(
        case_id="SYN-C02",
        requires_ocr=False,
        skipped=False,
        sources=(),
        unit_ids=("U-syn-c02-row1",),
        relevant_unit_ids=(),
    )
    scored = score_case(
        _c02_case(),
        gold,
        outcome,
        cross_explicit_space=True,
        allowed_number_keys=citation_number_keys(outcome.citations),
    )
    return {check.check_id: check.status for check in scored.checks}


def test_c02_enumeration_answer_does_not_leak_machine_fingerprint_digits(rag_index):
    locator = _c02_index(rag_index)
    answer = rag_index.ask("列出甲店立牌的全部信息", user_id="u", conversation_id="c02")
    assert answer.kind == "answer"
    marker = re.search(r"（记录 ([^）]+)）", answer.text)
    assert marker is not None
    # 机器指纹只做记录消歧，不是业务字段；不得以十进制数字进入答案。
    assert not re.search(r"\d", marker.group(1)), marker.group(1)
    assert _score_c02(answer, locator)["value_no_fabricated"] == "pass", answer.text


def test_c02_multi_record_answer_keeps_stable_marker_without_digits(rag_index):
    locator = _c02_index(rag_index)
    # 相邻正常反例：同一门店同一物品的两条记录仍能正常枚举，两条记录的标记互不相同且都不含数字。
    extra = dict(门店="甲店", 物品="立牌", 数量="2", 标识="QP002", 位置="乙区")
    doc = DocumentSpec(
        doc_id="D-syn-c02b",
        logical_id="L-syn-c02b",
        source_path="corpus/synthetic-c02b.xlsx",
        title="合成物品资料",
        file_kind="xlsx",
        version_id="V-syn-c02b-v1",
        version_label="当前",
        sha256=hashlib.sha256(b"synthetic-c02b").hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    unit = AtomicUnit(
        unit_id="U-syn-c02b-row2",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=1,
        unit_key="sheet:合成表:row:2",
        text=" | ".join(f"{name}: {value}" for name, value in extra.items()),
        fields=extra,
        sheet="合成表",
        locator={"sheet": "合成表", "row": 2, "header_row": 0},
        header_row=0,
        row_number=2,
        title=doc.title,
    )
    rag_index.add_document(doc, [unit], embed=False)
    answer = rag_index.ask("列出甲店立牌的全部信息", user_id="u", conversation_id="c02b")
    assert answer.kind == "answer"
    markers = re.findall(r"（记录 ([^）]+)）", answer.text)
    assert len(markers) == 2 and len(set(markers)) == 2
    assert all(re.fullmatch(r"[a-f]{8}", marker) for marker in markers), markers
    assert "甲区" in answer.text and "乙区" in answer.text
    # 安全反例：标记仍与各自记录行绑定，不能把一条记录的值挂到另一条记录的标记上。
    record_lines = [line for line in answer.text.splitlines() if "（记录 " in line]
    assert len(record_lines) == 2
    assert "甲区" in record_lines[0] and "（记录 " + markers[0] + "）" in record_lines[0]
    assert "乙区" in record_lines[1] and "（记录 " + markers[1] + "）" in record_lines[1]


# --------------------------------------------------------------------------- #
# C21/C27：枚举分支必须覆盖同一角色的全部字段列 + 全部请求角色
# --------------------------------------------------------------------------- #


def _two_price_row(add_records, make_doc):
    add_records(
        [
            {
                "门店": "甲店",
                "物品": "立牌",
                "参考供价": "7",
                "零售价": "9",
                "规格": "60x160cm",
                "位置": "甲区",
            }
        ],
        doc=make_doc(title="合成价格资料"),
    )


def test_c21_c27_single_role_enumerate_renders_every_column_of_that_role(rag_index, add_records, make_doc):
    _two_price_row(add_records, make_doc)
    answer = rag_index.ask("列出甲店立牌的价格", user_id="u", conversation_id="c21")
    assert answer.kind == "answer"
    facts = {(fact.field_role, fact.value) for fact in answer.facts}
    assert ("price", "7") in facts
    assert ("price", "9") in facts, answer.text
    assert "7" in answer.text and "9" in answer.text
    # 不得把未请求的规格/位置倾倒出来（安全边界不因多值渲染而放宽）。
    assert "60x160cm" not in answer.text and "甲区" not in answer.text


def test_c21_c27_multi_field_enumerate_renders_every_requested_role(rag_index, add_records, make_doc):
    _two_price_row(add_records, make_doc)
    answer = rag_index.ask("列出甲店立牌的价格和规格", user_id="u", conversation_id="c27")
    assert answer.kind == "answer"
    facts = {(fact.field_role, fact.value) for fact in answer.facts}
    assert ("price", "7") in facts and ("price", "9") in facts
    assert ("spec", "60x160cm") in facts, answer.text
    assert "60x160cm" in answer.text and "7" in answer.text and "9" in answer.text
    assert "甲区" not in answer.text


def test_adjacent_normal_single_value_enumerate_is_unchanged(rag_index, add_records, make_doc):
    _two_price_row(add_records, make_doc)
    answer = rag_index.ask("列出甲店立牌的位置", user_id="u", conversation_id="c-normal")
    assert answer.kind == "answer"
    assert "甲区" in answer.text
    assert "7" not in answer.text and "9" not in answer.text and "60x160cm" not in answer.text


def test_adjacent_normal_non_enumerate_conflict_still_reports_both_values(rag_index, add_records, make_doc):
    _two_price_row(add_records, make_doc)
    answer = rag_index.ask("甲店立牌的价格是多少？", user_id="u", conversation_id="c-conflict")
    assert answer.kind == "conflict"
    assert "7" in answer.text and "9" in answer.text


def test_adjacent_safety_item_contact_enumeration_still_refuses(rag_index, add_records, make_doc):
    add_records(
        [{"门店": "甲店", "物品": "立牌", "位置": "甲区", "电话": "010-55550000"}],
        doc=make_doc(title="合成设备资料"),
    )
    answer = rag_index.ask("列出甲店立牌的全部信息", user_id="u", conversation_id="c-safe")
    assert answer.kind == "no_answer"
    assert answer.reason == "SECURITY_RESTRICTED_CONTACT"
    assert "010-55550000" not in answer.text
    # 单字段电话同样受物品+联系人安全边界约束，不因渲染修复而放行。
    phone = rag_index.ask("列出甲店立牌的电话", user_id="u", conversation_id="c-safe2")
    assert phone.kind == "no_answer"
    assert phone.reason == "SECURITY_RESTRICTED_CONTACT"


# --------------------------------------------------------------------------- #
# C12：legacy 记录检索“只有门店条件”捷径丢弃同门店物品行（已修）
# --------------------------------------------------------------------------- #


def _c12_legacy_index(tmp_path):
    doc = DocumentSpec(
        doc_id="D-syn-c12",
        logical_id="L-syn-c12",
        source_path="synthetic/syn-c12.xlsx",
        title="合成门店资料",
        file_kind="xlsx",
        version_id="V-syn-c12-v1",
        version_label="1",
        sha256=hashlib.sha256(b"synthetic-c12").hexdigest(),
        business_date=None,
    )

    def unit(ordinal, fields):
        return AtomicUnit(
            unit_id=f"U-syn-c12-row{ordinal}",
            doc_id=doc.doc_id,
            version_id=doc.version_id,
            kind="table_row",
            ordinal=ordinal,
            unit_key=f"sheet:合成表:row:{ordinal + 2}",
            text="；".join(f"{name}: {value}" for name, value in fields.items()),
            fields=fields,
            sheet="合成表",
            locator={"sheet": "合成表", "row": ordinal + 2, "header_row": 1},
            row_number=ordinal + 2,
            title=doc.title,
        )

    store_row = unit(0, {"标识": "S01", "门店": "甲店", "联系人": "阿甲"})
    item_row = unit(
        1, {"标识": "P01", "门店": "甲店", "物品": "立牌", "位置": "C区", "盘点时间": "2026-03-04"}
    )
    index = LegacyIndex(tmp_path / "synthetic-c12.sqlite3")
    index.build([(doc, [store_row, item_row])])
    return index


def _c12_retrieve(index, requested_fields):
    intent = QueryIntent(
        mode="record",
        entity_filters={"store": "甲店"},
        requested_fields=tuple(requested_fields),
    )
    with index.database.session() as session:
        return retrieve(session, intent, revision=index.revision, limit=20)


def test_c12_legacy_store_only_retrieval_keeps_item_row_for_mixed_fields(tmp_path):
    index = _c12_legacy_index(tmp_path)
    try:
        # 红例：门店行承载“联系人”，物品行承载“位置/盘点时间”；store-only 条件
        # 不能把同门店的物品行整批丢弃，否则第二期望来源既不检索也不引用。
        result = _c12_retrieve(index, ("联系人", "位置", "盘点时间"))
        unit_keys = {unit.unit_key for unit in result.units}
        assert result.kind == "matches"
        assert result.total_candidates == 1  # 合并为“一个门店候选”，不新增歧义
        assert unit_keys == {"sheet:合成表:row:2", "sheet:合成表:row:3"}
        assert any(unit.fields.get("位置") == "C区" for unit in result.units)
        assert any(unit.fields.get("盘点时间") == "2026-03-04" for unit in result.units)
        # 既有候选口径保留：一个候选携带两个来源单元。
        assert len(result.candidates) == 1
        assert len(result.candidates[0].source_ids) == 2
    finally:
        index.close()


def test_c12_store_only_contact_question_stays_store_scoped(tmp_path):
    """正常 store-only 问法（只问门店级字段）行为不变：不把物品行带进来。"""

    index = _c12_legacy_index(tmp_path)
    try:
        result = _c12_retrieve(index, ("联系人",))
        assert result.kind == "matches"
        assert result.total_candidates == 1
        assert {unit.unit_key for unit in result.units} == {"sheet:合成表:row:2"}
    finally:
        index.close()


def test_c12_store_only_location_question_stays_item_scoped(tmp_path):
    """相邻正常反例：只问物品/位置字段时仍只返回物品行，不被店家行抢占。"""

    index = _c12_legacy_index(tmp_path)
    try:
        result = _c12_retrieve(index, ("位置",))
        assert result.kind == "matches"
        assert result.total_candidates == 1
        assert {unit.unit_key for unit in result.units} == {"sheet:合成表:row:3"}
    finally:
        index.close()
