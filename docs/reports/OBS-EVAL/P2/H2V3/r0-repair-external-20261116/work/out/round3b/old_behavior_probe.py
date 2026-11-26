"""在**旧口径**下重跑最终合成断言，确认第三轮的 5 条形状断言是红的。

做法：把本轮新加的两个“被请求字段集合”常量在内存里还原成修复前的取值
（``_FIELD_LIST_JOINERS`` 只认 和/及/以及/、/与；``_EXTRA_FIELD_ROLE_WORDS`` 为空），
不改工作树，再跑与 test_r0_6_synthetic_repairs.py 相同的问法。
"""

from __future__ import annotations

import hashlib
import pathlib
import tempfile

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex
from mktkb.rag import query as query_module


def _add(index, fields, *, doc_id, title="合成台账"):
    doc = DocumentSpec(
        doc_id=doc_id, logical_id=doc_id, source_path=f"corpus/{doc_id}.xlsx", title=title,
        file_kind="xlsx", version_id=f"V-{doc_id}", version_label="当前",
        sha256=hashlib.sha256(doc_id.encode()).hexdigest(), is_current=True, state="active",
        business_date="2026-10-28",
    )
    unit = AtomicUnit(
        unit_id=f"{doc_id}-row7", doc_id=doc_id, version_id=doc.version_id, kind="table_row",
        ordinal=0, unit_key="sheet:合成表:row:7",
        text="；".join(f"{n}: {v}" for n, v in fields.items()), fields=dict(fields),
        sheet="合成表",
        locator={"sheet": "合成表", "row": 7, "header_row": 0,
                 "cells": [{"header": n, "display": str(v)} for n, v in fields.items()]},
        header_row=0, row_number=7, title=title,
    )
    index.add_document(doc, [unit], embed=False)


WINDOW = {"标识": "L01", "门店": "甲店", "物品": "立牌",
          "生效日期": "2026-01-05", "失效日期": "2026-09-30"}
CONTACT = {"门店": "甲店", "门店地址": "合成区长街 1 号", "联系电话": "010-1000-1001"}

SHAPES = (
    ("c21_both_and", WINDOW, "列出甲店立牌的生效日期和失效日期"),
    ("c21_stem_and", WINDOW, "列出甲店立牌什么时候生效和什么时候失效"),
    ("c21_comma", WINDOW, "列出甲店立牌什么时候生效，什么时候失效"),
    ("c27_both_and", CONTACT, "列出甲店的地址和电话"),
    ("c27_comma", CONTACT, "列出甲店的地址，电话"),
)


def main() -> int:
    saved = (query_module._FIELD_LIST_JOINERS, dict(query_module._EXTRA_FIELD_ROLE_WORDS))
    query_module._FIELD_LIST_JOINERS = ("和", "及", "以及", "、", "与")
    query_module._EXTRA_FIELD_ROLE_WORDS.clear()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            index = RagIndex(tmp / "old.sqlite3",
                             config=RagConfig(provider_mode="offline", data_dir=tmp,
                                              business_date="2026-10-28"))
            try:
                for tag, fields, question in SHAPES:
                    _add(index, dict(fields), doc_id=f"OLD-{tag}")
                    answer = index.ask(question, user_id="u", conversation_id=f"old-{tag}")
                    pairs = [(f.field_role, f.value) for f in answer.facts]
                    print("[%-13s] kind=%-9s facts=%d %s" % (tag, answer.kind, len(answer.facts), pairs))
            finally:
                index.close()
    finally:
        query_module._FIELD_LIST_JOINERS, extra = saved
        query_module._EXTRA_FIELD_ROLE_WORDS.update(extra)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
