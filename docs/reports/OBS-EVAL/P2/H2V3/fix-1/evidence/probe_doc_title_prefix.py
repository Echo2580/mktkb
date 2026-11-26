"""v3-fix-1 §2b 顺带核：文档标题 ``D01_`` 前缀导致自然提问解析不到（离线、纯函数）。

同一句自然提问（只写中文标题、不写 Dxx 代号），唯一变量是索引里的文档标题形态；
使用产品自己的 ``rag.query._document_core`` / ``parse_query``。不建库、不调模型、不发请求。
"""

from __future__ import annotations

import json

from mktkb.rag.query import DocumentRef, Lexicon, _document_core, parse_query

QUESTION = "物品位置表里城东店的宣传海报放在哪里？"


def probe(title: str) -> dict:
    lexicon = Lexicon(
        stores=("城东店", "城西店"),
        items=("宣传海报",),
        field_labels=("位置",),
        documents=(DocumentRef(doc_id="doc-d01", title=title, source_path="x.xlsx", version_label="当前"),),
    )
    plan = parse_query(QUESTION, previous=None, lexicon=lexicon, business_date="2026-10-15")
    return {
        "document_title": title,
        "document_core": _document_core(title),
        "mode": plan.mode,
        "reason": plan.reason,
        "clarification": plan.clarification,
        "filters": dict(plan.filters),
        "resolved": plan.reason != "DOCUMENT_NOT_FOUND",
    }


def main() -> int:
    with_code_prefix = probe("D01_物品位置表")
    clean = probe("物品位置表")
    print(
        json.dumps(
            {
                "question": QUESTION,
                "ingest_name_with_code_prefix": with_code_prefix,
                "clean_title": clean,
                "cache": {
                    "title_resolvable_with_prefix": with_code_prefix["resolved"],
                    "title_resolvable_without_prefix": clean["resolved"],
                },
                "cause": (
                    "文档标题来自 ingest 上传名（源文件名带 D01_ 代号前缀）；产品 "
                    "_document_core 以第一个 '_' 截断，只得到 'D01'，中文标题核心丢失，"
                    "自然提问（只写中文标题）匹配不到任何资料 → DOCUMENT_NOT_FOUND。"
                    "属 ingest 命名侧为主、解析侧对代号前缀不鲁棒为辅。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
