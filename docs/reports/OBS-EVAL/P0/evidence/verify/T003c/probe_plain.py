"""T003c 独立验收：无 trace 行为对照探针（同一脚本分别用旧/新代码解释器运行）。

用法：
    python probe_plain.py <out.json> <work_root>

只使用公开的 RagIndex / RagConfig / DocumentSpec / AtomicUnit；不 import
observability.trace_attrs（旧提交 d41d19f 没有该模块）。输出仅业务字段。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

QUESTION = "滨江店的宣传海报放在哪里？"
ROW = {
    "标识": "QF01",
    "门店": "滨江店",
    "物品": "宣传海报",
    "别名": "海报",
    "位置": "店内外侧",
    "数量": 40,
}
TIMING_KEYS = {"elapsed_ms", "ms", "vector_query_ms", "latency_ms"}


def strip_timings(payload):
    if isinstance(payload, dict):
        return {
            key: strip_timings(value)
            for key, value in payload.items()
            if key not in TIMING_KEYS
        }
    if isinstance(payload, list):
        return [strip_timings(item) for item in payload]
    return payload


def main() -> int:
    out_path = Path(sys.argv[1])
    root = Path(sys.argv[2])
    root.mkdir(parents=True, exist_ok=True)

    import mktkb
    from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex

    info = {"mktkb_file": str(Path(mktkb.__file__).resolve())}
    index = RagIndex(
        root / "rag.sqlite3",
        config=RagConfig(
            provider_mode="offline",
            data_dir=root,
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
    try:
        doc = DocumentSpec(
            doc_id="D01",
            logical_id="D01",
            source_path="D01.xlsx",
            title="测试资料",
            file_kind="xlsx",
            version_id="D01-v1",
            version_label="当前",
            sha256="d" * 64,
        )
        unit = AtomicUnit(
            unit_id="D01-fixed-0",
            doc_id="D01",
            version_id="D01-v1",
            kind="table_row",
            ordinal=0,
            unit_key="sheet:物品位置:row:7",
            text="；".join(f"{name}: {value}" for name, value in ROW.items()),
            fields=dict(ROW),
            sheet="物品位置",
            locator={"sheet": "物品位置", "row": 7, "header_row": 6},
            header_row=6,
            row_number=7,
            title="测试资料",
        )
        index.add_document(doc, [unit], embed=True)
        first = index.ask(QUESTION, user_id="u", conversation_id="c-fixed")
        second = index.ask(QUESTION, user_id="u", conversation_id="c-fixed")
        scenarios = {}
        for label, question in (
            ("clarification", "？"),
            ("document_no_answer", "公司的年度愿景是什么？"),
            ("document_not_found", "促销活动台账在哪里？"),
        ):
            answer = index.ask(question, user_id="u", conversation_id=f"c-{label}")
            scenarios[label] = strip_timings(answer.to_dict())
        payload = {
            "info": info,
            "work_root": str(root),
            "first": strip_timings(first.to_dict()),
            "second": strip_timings(second.to_dict()),
            "scenarios": scenarios,
        }
    finally:
        index.close()

    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print("WROTE", out_path)
    print("MKTKB_FILE", info["mktkb_file"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
