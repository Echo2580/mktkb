"""R1-101 / M5：问句含“位置 + 由谁对接 + 完整合同/结算账号”时应拒答而未拒答。

机制出处：``R1-BASELINE.md`` §5 C28 → ``mktkb/rag/answer.py:658-665``（拒答分支要求
``not plan.field_role``）与 ``mktkb/rag/query.py:1647``（安全拒答条件只认 ``phone``/``address``）。
“合同/结算账号”这一族目前没有任何角色词或拒答判据，于是包含它的问句照常作答（kind=answer），
即 ``security_refusal_missing``。

合成数据：甲店 / 立牌 / 甲区 / 联系人 甲某 / 结算账号 SEQ-0001（全为假值）。
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

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402

FIELDS = {
    "门店": "甲店",
    "物品": "立牌",
    "位置": "甲区",
    "联系人": "甲某",
    "结算账号": "SEQ-0001",
}
PAYMENT_QUESTION = "甲店立牌放在哪，由谁对接，完整合同和结算账号是多少？"


def _index(tmp_path: Path) -> RagIndex:
    index = RagIndex(
        tmp_path / "m5.sqlite3",
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
        doc_id="D-syn-m5",
        logical_id="L-syn-m5",
        source_path="corpus/synthetic-m5.xlsx",
        title="合成物品资料",
        file_kind="xlsx",
        version_id="V-syn-m5-v1",
        version_label="当前",
        sha256=hashlib.sha256(b"synthetic-m5").hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    unit = AtomicUnit(
        unit_id="U-syn-m5-row7",
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
    )
    index.add_document(doc, [unit], embed=False)
    return index


def test_m5_contract_and_settlement_account_question_is_refused(tmp_path: Path) -> None:
    """红：应拒未拒——含“完整合同/结算账号”的问句返回 kind=answer。"""

    index = _index(tmp_path)
    try:
        answer = index.ask(PAYMENT_QUESTION, user_id="u", conversation_id="c-m5")
    finally:
        index.close()
    assert answer.kind == "no_answer", (answer.kind, answer.reason, answer.text)
    assert str(answer.reason or "").startswith("SECURITY_"), (answer.reason, answer.text)
    assert "SEQ-0001" not in answer.text, answer.text


def test_m5_position_plus_contact_only_still_answers(tmp_path: Path) -> None:
    """绿（反例面）：只问位置+对接人（R0/C12 已放行的组合）仍正常作答，不因新拒答收紧。"""

    index = _index(tmp_path)
    try:
        answer = index.ask(
            "甲店立牌放在哪，由谁对接？", user_id="u", conversation_id="c-m5-ok"
        )
    finally:
        index.close()
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert "甲区" in answer.text and "甲某" in answer.text
    assert "SEQ-0001" not in answer.text, answer.text
