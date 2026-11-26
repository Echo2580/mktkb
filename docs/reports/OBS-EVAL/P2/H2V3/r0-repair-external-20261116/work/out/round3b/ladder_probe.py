"""四层/五层值阶梯（去身份化合成件）：值在哪一层被丢，只出计数与固定枚举。

对每个“C21/C27 形”合成问法，按期望值逐值统计：
  L1 DB 单元 -> L2 被引用单元 -> L3 可映射字段角色 -> L4 facts -> L5 提交文本
并给出该形态的 requested_roles / row_roles / 交集（角色名是固定枚举）。

用法：
  python ladder_probe.py            # 修复后（当前工作树）
  python ladder_probe.py --old      # 修复前口径（内存里还原两个常量）
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex
from mktkb.rag import query as query_module
from mktkb.rag.chunking import field_role, role_values

#: 合成件：假门店/假物品/假字段/假值，只保留“单行记录 + 两个字段列”的结构。
SHAPES = (
    ("C21形", "列出甲店立牌什么时候生效，什么时候失效",
     {"标识": "L01", "门店": "甲店", "物品": "立牌",
      "生效日期": "2026-01-05", "失效日期": "2026-09-30"},
     ("2026-01-05", "生效日期")),
    ("C27形", "列出甲店的地址，电话",
     {"门店": "甲店", "门店地址": "合成区长街 1 号", "联系电话": "010-1000-1001"},
     ("合成区长街 1 号", "门店地址")),
)


def _add(index, fields, *, doc_id: str):
    doc = DocumentSpec(
        doc_id=doc_id, logical_id=doc_id, source_path=f"corpus/{doc_id}.xlsx", title="合成台账",
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
        header_row=0, row_number=7, title="合成台账",
    )
    index.add_document(doc, [unit], embed=False)


def _planned_roles(question: str, index) -> tuple[str, ...]:
    from mktkb.rag.query import build_lexicon, parse_query
    from mktkb.rag.types import QueryState

    plan = parse_query(question, previous=QueryState(), lexicon=build_lexicon(index.lexicon_data()),
                       business_date="2026-10-28", page_size=10)
    return tuple(plan.field_roles) or ((plan.field_role,) if plan.field_role else ())


def main(argv: list[str]) -> int:
    old = "--old" in argv
    if old:
        query_module._FIELD_LIST_JOINERS = ("和", "及", "以及", "、", "与")
        query_module._EXTRA_FIELD_ROLE_WORDS.clear()
    print("# value ladder (counts + fixed role enums only); mode=%s" % ("pre-fix" if old else "current"))
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        for label, question, fields, (expected, expected_header) in SHAPES:
            index = RagIndex(root / f"{label}.sqlite3",
                             config=RagConfig(provider_mode="offline", data_dir=root / label,
                                              business_date="2026-10-28"))
            try:
                _add(index, fields, doc_id=f"D-{label}")
                requested = _planned_roles(question, index)
                row_roles = sorted(role_values(fields))
                intersection = sorted(set(requested) & set(row_roles))
                answer = index.ask(question, user_id="u", conversation_id=label)
                cited = {citation.source_id for citation in answer.citations}
                facts = {(fact.field_role, fact.value) for fact in answer.facts}
                db_role = role_values(fields).get(field_role(expected_header) or "", ())
                l1 = int(any(str(v) == expected for v in fields.values()))
                l2 = int(l1 and bool(cited))
                l3 = int(any(str(v) == expected for v in db_role))
                l4 = int(any(value == expected for _role, value in facts))
                l5 = int(expected in answer.text)
                print(
                    "%s question_kind=fixed requested=%s row_roles=%s hit=%s "
                    "L1_db=%d L2_cited=%d L3_role_mappable=%d L4_facts=%d L5_commit=%d "
                    "kind=%s facts=%d"
                    % (label, list(requested), row_roles, intersection,
                       l1, l2, l3, l4, l5, answer.kind, len(answer.facts))
                )
            finally:
                index.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
