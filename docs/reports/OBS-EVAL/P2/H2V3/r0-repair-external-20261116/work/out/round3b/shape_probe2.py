"""R0 round3 去身份化形态探针 v2：定位“被请求字段角色集合”漏项的具体形态。

A 形（C21 形）：单行、生效日期+失效日期两列。
B 形（C27 形）：门店单行、门店地址+联系电话两列（无物品/标识，避免命中受限联系人闸）。
输出：kind / reason / facts(role,value) / 行数 / 文本。
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[5] / "backend" / "src"))

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402


def _add_row(index: RagIndex, fields: dict, *, doc_id: str, title: str = "合成台账") -> None:
    doc = DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"corpus/{doc_id}.xlsx",
        title=title,
        file_kind="xlsx",
        version_id=f"V-{doc_id}",
        version_label="当前",
        sha256=hashlib.sha256(doc_id.encode()).hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    unit = AtomicUnit(
        unit_id=f"{doc_id}-row7",
        doc_id=doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key="sheet:合成表:row:7",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=dict(fields),
        sheet="合成表",
        locator={
            "sheet": "合成表",
            "row": 7,
            "header_row": 0,
            "cells": [{"header": n, "display": str(v)} for n, v in fields.items()],
        },
        header_row=0,
        row_number=7,
        title=title,
    )
    index.add_document(doc, [unit], embed=False)


def _report(tag: str, answer) -> None:
    pairs = [(fact.field_role, fact.value) for fact in answer.facts]
    print(
        "[%-22s] kind=%-10s reason=%-24s facts=%d lines=%d %s"
        % (tag, answer.kind, answer.reason, len(answer.facts), len(answer.text.splitlines()), pairs)
    )


def _case_a(root: pathlib.Path) -> None:
    config = RagConfig(provider_mode="offline", data_dir=root / "a", business_date="2026-10-28")
    index = RagIndex(root / "a.sqlite3", config=config)
    try:
        _add_row(index, {"标识": "L01", "门店": "甲店", "物品": "立牌",
                         "生效日期": "2026-01-05", "失效日期": "2026-09-30"}, doc_id="D-a")
        questions = {
            "a1_single_to": "列出甲店立牌的失效日期",
            "a2_both_and": "列出甲店立牌的生效日期和失效日期",
            "a4_both_comma": "列出甲店立牌什么时候生效，什么时候失效",
            "a5_both_bare": "甲店立牌什么时候生效什么时候失效",
            "a7_phantom_date": "列出甲店立牌的位置和失效日期",
            "a8_stem_and": "列出甲店立牌什么时候生效和什么时候失效",
            "a9_single_from": "列出甲店立牌的生效日期",
        }
        for tag, question in questions.items():
            _report(tag, index.ask(question, user_id="u", conversation_id="a"))
    finally:
        index.close()


def _case_b(root: pathlib.Path) -> None:
    config = RagConfig(provider_mode="offline", data_dir=root / "b", business_date="2026-10-28")
    index = RagIndex(root / "b.sqlite3", config=config)
    try:
        _add_row(index, {"门店": "甲店", "门店地址": "合成区长街 1 号",
                         "联系电话": "010-1000-1001"}, doc_id="D-b")
        questions = {
            "b1_addr": "列出甲店的门店地址",
            "b2_both_and": "列出甲店的地址和电话",
            "b3_both_comma": "列出甲店的地址，电话",
            "b4_both_bare": "列出甲店的地址电话",
            "b5_phone": "列出甲店的电话",
        }
        for tag, question in questions.items():
            _report(tag, index.ask(question, user_id="u", conversation_id="b"))
    finally:
        index.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        _case_a(root)
        _case_b(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
