"""C21/C27 与 entity_key 形态关系的受控反事实（假实体/假字段）。

1. 同一合成语料、同一问法，分别在两种 entity_key 派生下建索引并作答：
   - 现状：rag/chunking._entity —— 名复合（item|store|item，无 id/doc/unit 后缀）
   - 对齐：retrieval/index.analyze_fields 形态 —— 名复合 + |id:<标识>
2. 比较答案文本 / 行数 / facts 数 / 被引 unit。
3. 另证：value_hit 只吃答案文本（scorers.check_value），不读 entity_key。
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend" / "src"))

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402
from mktkb.rag import chunking  # noqa: E402

QUESTION = "列出甲店立牌的售价"


def doc(doc_id: str, title: str) -> DocumentSpec:
    return DocumentSpec(
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


def build(tmp: Path, *, aligned: bool) -> RagIndex:
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
    index = RagIndex(tmp / f"{'aligned' if aligned else 'current'}.sqlite3", config=config)
    d = doc("D-ek", "合成价目")
    fields = {"标识": "P01", "门店": "甲店", "物品": "立牌", "价格": "7", "售价": "9"}
    locator = {"sheet": "合成表", "row": 7, "header_row": 0}
    unit = AtomicUnit(
        unit_id="D-ek-row7",
        doc_id=d.doc_id,
        version_id=d.version_id,
        kind="table_row",
        ordinal=0,
        unit_key="sheet:合成表:row:7",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=dict(fields),
        sheet="合成表",
        locator=locator,
        header_row=0,
        row_number=7,
        title=d.title,
    )
    if aligned:
        original = chunking._entity

        def _aligned_entity(fields_map, *, doc):  # noqa: ANN001
            entity_type, key, label, filters, filters_norm = original(fields_map, doc=doc)
            identifier = filters.get("identifier")
            if identifier:
                key = f"{entity_type}|id:{chunking.normalize_field(identifier)}"
            return entity_type, key, label, filters, filters_norm

        chunking._entity = _aligned_entity
    try:
        index.add_document(d, [unit], embed=False)
    finally:
        if aligned:
            chunking._entity = original
    return index


def main() -> None:
    out = {}
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        for aligned in (False, True):
            (root / ("aligned" if aligned else "current")).mkdir()
            index = build(root, aligned=aligned)
            try:
                answer = index.ask(QUESTION, user_id="u", conversation_id="ek")
                chunk = index.search.__self__  # noqa: F841 - 仅为可读性
                out["aligned" if aligned else "current"] = {
                    "kind": answer.kind,
                    "text": answer.text,
                    "lines": len(answer.text.splitlines()),
                    "chars": len(answer.text),
                    "facts": [[f.entity_key, f.field_role, f.value] for f in answer.facts],
                }
            finally:
                index.close()
    out["text_equal"] = out["current"]["text"] == out["aligned"]["text"]
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
