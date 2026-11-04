"""旧/新同资料同题对照：旧精确+FTS 无业务有效期/向量，新结构化+有效期+混合召回。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from mktkb.ingestion.parsers import ParseServices, parse_document
from mktkb.rag import DocumentSpec, RagConfig, RagIndex, adapt_parsed_unit
from mktkb.rag.legacy import LegacyIndex

CORPUS = Path(__file__).resolve().parents[3] / "corpus" / "enterprise-20261101"


def _doc_units(code: str, rel: str, kind: str, title: str):
    path = CORPUS / rel
    doc = DocumentSpec(
        doc_id=code,
        logical_id=code,
        source_path=rel,
        title=title,
        file_kind=kind,
        version_id=f"{code}-v1",
        version_label="当前",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        business_date="2026-10-28",
    )
    units = [
        adapt_parsed_unit(unit, doc=doc, unit_id=f"{code}-{ordinal}", ordinal=ordinal)
        for ordinal, unit in enumerate(parse_document(path, kind, ParseServices()))
    ]
    return doc, units


def test_old_and_new_same_material_price_contrast(tmp_path: Path):
    docs = [
        _doc_units("E11", "excel/E11_终端物料位置表_当前V2.xlsx", "xlsx", "终端物料位置表"),
        _doc_units("E03", "excel/E03_2026年Q4渠道价目表.xlsx", "xlsx", "2026年Q4渠道价目表"),
        _doc_units("W01", "word/W01_终端陈列与生动化管理制度_V2.1.docx", "docx", "终端陈列与生动化管理制度"),
    ]
    legacy = LegacyIndex(tmp_path / "legacy.sqlite3")
    try:
        assert legacy.build(docs)["documents"] == 3
        old_poster = legacy.ask("滨江店的宣传海报放在哪里？")
        assert old_poster.kind == "answer"
        assert "店内外侧" in old_poster.text

        old_price = legacy.ask("启沣乌龙茶（900ml PET）在NKA卖场的组合价是多少？")
        assert old_price.diagnostics["mode"] == "document"
        old_text = old_price.text + "\n" + "\n".join(item["text"] for item in old_price.evidence)
        assert "4.5" in old_text
        assert "2025" in old_text
    finally:
        legacy.close()

    index = RagIndex(tmp_path / "new.sqlite3", config=RagConfig(data_dir=tmp_path, business_date="2026-10-28"))
    try:
        for doc, units in docs:
            result = index.add_document(doc, units)
            assert result["embedding_error"] is None
        new_price = index.ask(
            "启沣乌龙茶（900ml PET）在NKA卖场的组合价是多少？", user_id="u", conversation_id="c"
        )
        assert new_price.kind == "answer"
        assert "5" in new_price.text and "2瓶" in new_price.text
        assert new_price.citations and new_price.citations[0].locator["row"] == 10
        assert "4.5" not in new_price.text
    finally:
        index.close()
