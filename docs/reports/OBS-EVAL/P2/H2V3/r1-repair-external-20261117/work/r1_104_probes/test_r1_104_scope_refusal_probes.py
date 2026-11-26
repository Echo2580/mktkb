"""T-R1-104 独立验收探针（RAG 内核侧）：102b 收窄 / 102c 拒答**不得误伤反例**。

合成语料：甲店/乙店、物品 立牌、位置 甲区/乙区、联系人 甲某/乙某（行号 4/5）。
所有断言都读 ``plan.filters`` 与答案正文/事实，不看 101/102 的报告结论。

探针：
1. 显式“乙店”问法（在甲店作用域 + 换话题轮之后）必须答乙店，不得被 102b 收窄成甲店；
   三种换话题措辞都试（机制不得只对一个措辞生效）。
2. 多店枚举（甲店和乙店）仍多店：filters 不带 store、正文同时含甲区与乙区。
3. 只问联系人的合法面不得被 102c 误拒（不含合同/账号等凭据词）。
4. 显式乙店的联系人问题不得泄漏甲店联系人。
5. 含“合同/账号”但属政策/流程提问的句子不得被误判为安全拒答（词面宽度反例）。
6. 暂存门店作用域不得把政策题变成记录题（102b 不越界）。

运行：``.venv\\Scripts\\python.exe -B -m pytest <本文件> -q -p no:cacheprovider``
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

for _root in Path(__file__).resolve().parents:
    if (_root / "backend" / "src").is_dir():
        sys.path.insert(0, str(_root / "backend" / "src"))
        break

import pytest  # noqa: E402

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402

STORES = (("D-r1104-a", "甲店", "甲区", "甲某", 4), ("D-r1104-b", "乙店", "乙区", "乙某", 5))
SCOPE_TURN = "甲店的立牌位置在哪？"
TOPICS = ("陈列要求有哪些？", "调拨需要谁同意？", "补货要怎么申请？")


def _add(index: RagIndex, doc_id: str, store: str, location: str, contact: str, row: int) -> None:
    fields = {"门店": store, "物品": "立牌", "位置": location, "联系人": contact}
    doc = DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"corpus/synthetic-{doc_id}.xlsx",
        title="合成物品资料",
        file_kind="xlsx",
        version_id=f"V-{doc_id}",
        version_label="当前",
        sha256=hashlib.sha256(doc_id.encode()).hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    unit = AtomicUnit(
        unit_id=f"U-{doc_id}-row{row}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key=f"sheet:合成表:row:{row}",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=fields,
        sheet="合成表",
        locator={
            "sheet": "合成表",
            "row": row,
            "header_row": 3,
            "cells": [
                {"column": chr(65 + offset), "display": str(value), "header": str(name)}
                for offset, (name, value) in enumerate(fields.items())
            ],
        },
        header_row=3,
        row_number=row,
        title=doc.title,
    )
    index.add_document(doc, [unit], embed=False)


def _index(tmp_path: Path, name: str) -> RagIndex:
    index = RagIndex(
        tmp_path / f"{name}.sqlite3",
        config=RagConfig(
            provider_mode="offline",
            data_dir=tmp_path,
            business_date="2026-10-28",
            chunk_max_chars=420,
            chunk_max_units=3,
            chunk_overlap_units=1,
            top_k=5,
            page_size=10,
            vector_candidate_limit=50,
            rerank_top_n=20,
        ),
    )
    for doc_id, store, location, contact, row in STORES:
        _add(index, doc_id, store, location, contact, row)
    return index


def _ask(index: RagIndex, question: str, conversation_id: str):
    return index.ask(question, user_id="u", conversation_id=conversation_id)


def _slug(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


def _filters(answer) -> dict:
    return dict(answer.diagnostics["plan"]["filters"])


# --------------------------------------------------------------------------- #
# 1. 显式换店不得被收窄
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("topic", TOPICS)
def test_probe_explicit_other_store_is_not_narrowed_by_retained_scope(
    tmp_path: Path, topic: str
) -> None:
    index = _index(tmp_path, f"probe-other-{_slug(topic)}")
    try:
        _ask(index, SCOPE_TURN, "c-other")
        _ask(index, topic, "c-other")
        answer = _ask(index, "乙店的立牌放在哪？", "c-other")
    finally:
        index.close()
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert _filters(answer).get("store") == "乙店", (topic, _filters(answer), answer.text)
    assert "乙区" in answer.text and "甲区" not in answer.text, (topic, answer.text)
    assert "甲某" not in answer.text, (topic, answer.text)
    assert {fact.value for fact in answer.facts} <= {"乙区", "乙店", "乙某", "立牌"}, [
        (fact.field_role, fact.value) for fact in answer.facts
    ]


# --------------------------------------------------------------------------- #
# 2. 多店枚举仍是多店
# --------------------------------------------------------------------------- #


def test_probe_multi_store_enumeration_stays_multi_store(tmp_path: Path) -> None:
    index = _index(tmp_path, "probe-multi")
    try:
        _ask(index, SCOPE_TURN, "c-multi")
        _ask(index, TOPICS[0], "c-multi")
        answer = _ask(index, "甲店和乙店的立牌放在哪？", "c-multi")
    finally:
        index.close()
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert "store" not in _filters(answer), _filters(answer)
    assert "甲区" in answer.text and "乙区" in answer.text, answer.text


# --------------------------------------------------------------------------- #
# 3. 只问联系人的合法面
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("question", ("甲店立牌由谁对接？", "甲店立牌的对接人是谁？"))
def test_probe_contact_only_question_is_not_refused(tmp_path: Path, question: str) -> None:
    index = _index(tmp_path, f"probe-contact-{_slug(question)}")
    try:
        answer = _ask(index, question, f"c-contact-{_slug(question)}")
    finally:
        index.close()
    assert answer.kind == "answer", (question, answer.kind, answer.reason, answer.text)
    assert not str(answer.reason or "").startswith("SECURITY_"), (question, answer.reason)
    assert "甲某" in answer.text, (question, answer.text)


# --------------------------------------------------------------------------- #
# 4. 乙店联系人不得被甲店作用域污染
# --------------------------------------------------------------------------- #


def test_probe_other_store_contact_question_does_not_leak_first_store(tmp_path: Path) -> None:
    index = _index(tmp_path, "probe-other-contact")
    try:
        _ask(index, SCOPE_TURN, "c-other-contact")
        _ask(index, TOPICS[1], "c-other-contact")
        answer = _ask(index, "乙店的立牌由谁对接？", "c-other-contact")
    finally:
        index.close()
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert "乙某" in answer.text and "甲某" not in answer.text, answer.text


# --------------------------------------------------------------------------- #
# 5. 含凭据词的政策/流程题不得被误拒（词面宽度反例）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("question", ("合同申请流程是什么？", "账号申请要走什么流程？"))
def test_probe_policy_question_with_credential_word_is_not_security_refused(
    tmp_path: Path, question: str
) -> None:
    index = _index(tmp_path, f"probe-policy-{_slug(question)}")
    try:
        answer = _ask(index, question, f"c-policy-{_slug(question)}")
    finally:
        index.close()
    assert not str(answer.reason or "").startswith(
        "SECURITY_"
    ), (question, answer.kind, answer.reason, answer.text)


# --------------------------------------------------------------------------- #
# 6. 暂存作用域不得把政策题变成记录题
# --------------------------------------------------------------------------- #


def test_probe_retained_scope_does_not_capture_policy_question(tmp_path: Path) -> None:
    index = _index(tmp_path, "probe-policy-scope")
    try:
        _ask(index, SCOPE_TURN, "c-policy-scope")
        _ask(index, TOPICS[0], "c-policy-scope")
        answer = _ask(index, TOPICS[0], "c-policy-scope")
    finally:
        index.close()
    assert answer.kind != "answer", (answer.kind, answer.reason, answer.text)
    assert _filters(answer).get("store") != "甲店", _filters(answer)
    assert "甲区" not in answer.text, answer.text
