"""R1-101 / M4：问句同时含“位置/哪”与“生效”时，字段角色是否只取 ``effective_from``。

机制出处：``R1-BASELINE.md`` §5 C22 → ``mktkb/rag/query.py:_match_fields``（:1169 起）。
判定结论：当前工作树**不复现**——``_match_fields`` 在“无并列词 + 首角色是有效期”时会补回
句子里登记过的其它字段角色（:1189-1203，R0/C21 的修复），因此 ``field_roles`` 同时含
``effective_from`` 与 ``location``，位置值仍被渲染。本文件把这条现状钉住：
既锁“位置没被吞”（绿），也锁“只问生效时不夹带位置”（不因修复而收宽）。

合成数据：甲店 / 立牌 / 甲区 / 生效日期 2026-01-05。
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

FIELDS = {
    "门店": "甲店",
    "物品": "立牌",
    "位置": "甲区",
    "生效日期": "2026-01-05",
}
MIXED_QUESTIONS = (
    "甲店立牌放在哪，什么时候生效？",
    "甲店立牌放在哪尚未生效吗？",
    "甲店立牌的位置以及生效日期是什么？",
    "甲店立牌放在哪？生效日期呢？",
)


def _index(tmp_path: Path) -> RagIndex:
    from mktkb.rag.chunking import effective_dates

    index = RagIndex(
        tmp_path / "m4.sqlite3",
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
    doc = DocumentSpec(
        doc_id="D-syn-m4",
        logical_id="L-syn-m4",
        source_path="corpus/synthetic-m4.xlsx",
        title="合成物品资料",
        file_kind="xlsx",
        version_id="V-syn-m4-v1",
        version_label="当前",
        sha256=hashlib.sha256(b"synthetic-m4").hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    effective_from, effective_to = effective_dates(FIELDS)
    unit = AtomicUnit(
        unit_id="U-syn-m4-row7",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key="sheet:合成表:row:7",
        text="；".join(f"{name}: {value}" for name, value in FIELDS.items()),
        fields=dict(FIELDS),
        sheet="合成表",
        locator={
            "sheet": "合成表",
            "row": 7,
            "header_row": 6,
            "cells": [
                {"column": chr(65 + i), "display": str(value), "header": str(name)}
                for i, (name, value) in enumerate(FIELDS.items())
            ],
        },
        header_row=6,
        row_number=7,
        title=doc.title,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    index.add_document(doc, [unit], embed=False)
    return index


@pytest.mark.parametrize("question", MIXED_QUESTIONS)
def test_m4_location_role_survives_effective_question(tmp_path: Path, question: str) -> None:
    """绿：位置与生效并列问时 ``field_roles`` 两个都在，位置值不丢。"""

    index = _index(tmp_path)
    try:
        answer = index.ask(question, user_id="u", conversation_id="c-m4")
    finally:
        index.close()
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    roles = tuple(answer.state["field_roles"])
    assert "location" in roles, (question, roles, answer.text)
    assert "effective_from" in roles, (question, roles, answer.text)
    assert "甲区" in answer.text, answer.text
    assert "2026-01-05" in answer.text, answer.text
    assert answer.diagnostics["plan"]["filters"] == {"store": "甲店", "item": "立牌"}


def test_m4_effective_only_question_does_not_drag_location_in(tmp_path: Path) -> None:
    """绿（反例面）：只问生效时不夹带位置，避免“补角色”变成收宽。"""

    index = _index(tmp_path)
    try:
        answer = index.ask("甲店立牌的生效日期是什么？", user_id="u", conversation_id="c-m4-only")
    finally:
        index.close()
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert tuple(answer.state["field_roles"]) == ("effective_from",)
    assert "甲区" not in answer.text, answer.text
