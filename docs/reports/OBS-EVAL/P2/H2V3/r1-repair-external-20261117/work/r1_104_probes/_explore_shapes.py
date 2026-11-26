"""临时探查（不属于交付物）：在合成索引上打印若干问法的 plan/答案形状。"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve()
for _p in _ROOT.parents:
    if (_p / "backend" / "src").is_dir():
        sys.path.insert(0, str(_p / "backend" / "src"))
        break

import tempfile

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex

ROWS = (
    ("D-syn-a", "甲店", "甲区", "甲某", 4),
    ("D-syn-b", "乙店", "乙区", "乙某", 5),
)


def _index(tmp: Path) -> RagIndex:
    index = RagIndex(
        tmp / "probe.sqlite3",
        config=RagConfig(
            provider_mode="offline",
            data_dir=tmp,
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
    for doc_id, store, location, contact, row in ROWS:
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
            text="；".join(f"{n}: {v}" for n, v in fields.items()),
            fields=fields,
            sheet="合成表",
            locator={
                "sheet": "合成表",
                "row": row,
                "header_row": 3,
                "cells": [
                    {"column": chr(65 + i), "display": str(v), "header": str(n)}
                    for i, (n, v) in enumerate(fields.items())
                ],
            },
            header_row=3,
            row_number=row,
            title=doc.title,
        )
        index.add_document(doc, [unit], embed=False)
    return index


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="r1104-probe-"))
    index = _index(tmp)
    try:
        for topic in ("陈列要求有哪些？", "调拨需要谁同意？", "补货要怎么申请？"):
            conv = f"c-{topic}"
            first = index.ask("甲店的立牌位置在哪？", user_id="u", conversation_id=conv)
            second = index.ask(topic, user_id="u", conversation_id=conv)
            third = index.ask("乙店的立牌放在哪？", user_id="u", conversation_id=conv)
            print(
                "TOPIC",
                topic,
                "| t1", first.kind, first.diagnostics["plan"]["filters"],
                "| t2", second.kind, second.diagnostics["plan"].get("filters"),
                "| t3", third.kind, third.diagnostics["plan"]["filters"],
                "| 乙区", "乙区" in third.text, "甲区", "甲区" in third.text,
            )
        conv = "c-multi"
        index.ask("甲店的立牌位置在哪？", user_id="u", conversation_id=conv)
        index.ask("陈列要求有哪些？", user_id="u", conversation_id=conv)
        multi = index.ask("甲店和乙店的立牌放在哪？", user_id="u", conversation_id=conv)
        print("MULTI", multi.kind, multi.diagnostics["plan"]["filters"],
              "甲区" in multi.text, "乙区" in multi.text)
        for q in ("甲店立牌由谁对接？", "甲店的立牌由谁对接？", "合同申请流程是什么？",
                  "账号申请要走什么流程？", "甲店立牌有合同吗？"):
            answer = index.ask(q, user_id="u", conversation_id=f"c-{q}")
            print("Q", q, "|", answer.kind, answer.reason,
                  "| fields", answer.diagnostics["plan"].get("field_roles"),
                  "| 甲某", "甲某" in answer.text)
        conv = "c-policy"
        index.ask("甲店的立牌位置在哪？", user_id="u", conversation_id=conv)
        index.ask("陈列要求有哪些？", user_id="u", conversation_id=conv)
        policy = index.ask("陈列要求有哪些？", user_id="u", conversation_id=conv)
        print("POLICY2", policy.kind, policy.reason,
              policy.diagnostics["plan"].get("filters"), "甲区", "甲区" in policy.text)
    finally:
        index.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
