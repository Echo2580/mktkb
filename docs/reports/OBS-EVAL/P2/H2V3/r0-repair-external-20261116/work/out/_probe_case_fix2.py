"""R0 第二轮定位探针：只跑现有产品路径（RagIndex.ask），全部假实体/假字段/假值。

不做断言，只打印 plan 形状 + 答案形态 + facts，用于找“值在记录里但没被渲染”的分支。
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend" / "src"))

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402
from mktkb.rag.query import build_lexicon, parse_query  # noqa: E402


def doc(doc_id: str, title: str, logical: str | None = None) -> DocumentSpec:
    return DocumentSpec(
        doc_id=doc_id,
        logical_id=logical or doc_id,
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


def unit(document: DocumentSpec, fields: dict, ordinal: int, sheet: str = "合成台账", row: int | None = None):
    row_number = row if row is not None else 7 + ordinal
    locator = {"sheet": sheet, "row": row_number, "header_row": 0}
    return AtomicUnit(
        unit_id=f"{document.doc_id}-row{row_number}",
        doc_id=document.doc_id,
        version_id=document.version_id,
        kind="table_row",
        ordinal=ordinal,
        unit_key=f"sheet:{sheet}:row:{row_number}",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=dict(fields),
        sheet=sheet,
        locator=locator,
        header_row=0,
        row_number=row_number,
        title=document.title,
    )


def make_index(tmp: Path) -> RagIndex:
    config = RagConfig(
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
    )
    index = RagIndex(tmp / "probe.sqlite3", config=config)
    d1 = doc("D-probe-a", "合成台账甲")
    rows1 = [
        {"门店": "甲店", "物品": "立牌", "数量": "3", "价格": "7", "位置": "甲区", "更新日期": "2026-03-04"},
        # 同门店同物品的第二行：只有“位置”，没有“价格”
        {"门店": "甲店", "物品": "立牌", "位置": "乙区", "盘点时间": "2026-03-05"},
    ]
    index.add_document(d1, [unit(d1, f, i) for i, f in enumerate(rows1)], embed=False)

    d2 = doc("D-probe-b", "合成价目乙")
    rows2 = [
        {"门店": "甲店", "物品": "立牌", "价格": "7", "售价": "9", "促销价": "11"},
    ]
    index.add_document(d2, [unit(d2, f, i) for i, f in enumerate(rows2)], embed=False)
    return index


QUESTIONS = [
    "列出甲店立牌的全部信息",
    "列出甲店立牌的价格",
    "甲店立牌的售价是多少",
    "列出甲店立牌的售价",
    "列出甲店立牌的价格和尺寸",
    "列出甲店立牌的价格和规格",
    "甲店立牌有多少条记录",
    "列出甲店立牌的记录",
    "甲店立牌的数量和位置",
    "甲店立牌什么时候盘点",
    "列出甲店立牌的盘点时间",
    "甲店立牌的价格和位置",
    "甲店立牌的售价和位置",
]


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        index = make_index(tmp)
        try:
            lexicon = build_lexicon(index.lexicon_data())
            for i, question in enumerate(QUESTIONS):
                plan = parse_query(
                    question,
                    previous=None,
                    lexicon=lexicon,
                    business_date="2026-10-28",
                    page_size=10,
                )
                answer = index.ask(question, user_id="u", conversation_id=f"probe-{i}")
                print("=" * 100)
                print(json.dumps({
                    "q": question,
                    "mode": plan.mode,
                    "enumerate": plan.enumerate,
                    "field_role": plan.field_role,
                    "field_roles": list(plan.field_roles),
                    "filters": dict(plan.filters),
                    "reason": plan.reason,
                    "kind": answer.kind,
                    "reason_answer": answer.reason,
                    "len": len(answer.text),
                    "lines": len(answer.text.splitlines()),
                    "text": answer.text,
                    "facts": [[f.field_role, f.value] for f in answer.facts],
                    "cited_units": [list(c.unit_ids) for c in answer.citations],
                }, ensure_ascii=False, indent=1))
        finally:
            index.close()


if __name__ == "__main__":
    main()
