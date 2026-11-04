"""分块与来源保真：表头/工作表/原始行号、长行可追溯、正文相邻语境与页段定位。"""

from __future__ import annotations

import re

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, build_chunks


def _doc() -> DocumentSpec:
    return DocumentSpec(
        doc_id="E11",
        source_path="excel/E11.xlsx",
        title="终端物料位置表",
        file_kind="xlsx",
        version_id="E11-v2",
        version_label="当前V2",
        sha256="a" * 64,
        business_date="2026-10-28",
    )


def _unit(**overrides) -> AtomicUnit:
    values = {
        "unit_id": "u1",
        "doc_id": "E11",
        "version_id": "E11-v2",
        "kind": "table_row",
        "ordinal": 0,
        "unit_key": "sheet:物品位置:row:7",
        "text": "",
        "fields": {},
        "sheet": "物品位置",
        "locator": {"sheet": "物品位置", "row": 7, "header_row": 6},
        "header_row": 6,
        "row_number": 7,
        "title": "终端物料位置表",
    }
    values.update(overrides)
    return AtomicUnit(**values)


def test_table_row_keeps_title_header_sheet_and_row() -> None:
    fields = {
        "标识": "QF01",
        "门店": "滨江店",
        "物品": "宣传海报",
        "别名": "海报",
        "位置": "店内外侧",
        "数量": 40,
        "单位": "张",
        "更新日期": "2026-10-28",
    }
    config = RagConfig()
    chunks = build_chunks(_doc(), [_unit(fields=fields)], config)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.kind == "record"
    assert chunk.record_unit_id == "u1"
    assert chunk.fields == fields
    assert chunk.locator["sheet"] == "物品位置"
    assert chunk.locator["row"] == 7
    assert chunk.locator["header_row"] == 6
    assert "第 7 行" in chunk.text
    assert "表头: 标识 | 门店 | 物品 | 别名 | 位置 | 数量 | 单位 | 更新日期" in chunk.text
    assert "QF01" in chunk.text and "店内外侧" in chunk.text
    assert chunk.entity_key == "item|滨江店|宣传海报"
    assert chunk.filters_norm["store"] == "滨江店"
    assert chunk.filters_norm["item"] == "宣传海报"


def test_long_table_row_chunks_preserve_key_conditions_and_all_fields() -> None:
    fields = {"标识": "QF99", "门店": "滨江店", "物品": "超长物料", "位置": "E区5号货架第二层"}
    for index in range(30):
        fields[f"扩展字段{index:02d}"] = f"值{index:02d}" + ("很长的说明" * 8)
    config = RagConfig(chunk_max_chars=260)
    chunks = build_chunks(_doc(), [_unit(fields=fields, unit_key="sheet:物品位置:row:99", row_number=99)], config)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.record_unit_id == "u1"
        assert chunk.fields == fields
        assert "QF99" in chunk.text
        assert "第 99 行" in chunk.text
        assert len(chunk.text) <= config.chunk_max_chars + 120
    combined = "\n".join(chunk.text for chunk in chunks)
    for name in fields:
        assert f"{name}:" in combined


def test_text_chunks_overlap_and_keep_page_paragraph_context() -> None:
    units = [
        _unit(
            unit_id=f"p{i}",
            kind="paragraph",
            ordinal=i,
            unit_key=f"paragraph:{i + 1}",
            text=f"第{i + 1}段：这是用于测试相邻语境的正文内容，包含流程说明。",
            sheet=None,
            locator={"paragraph": i + 1, "page": 1, "heading": "第二章 流程"},
            header_row=None,
            row_number=None,
        )
        for i in range(10)
    ]
    config = RagConfig(chunk_max_chars=130, chunk_max_units=2, chunk_overlap_units=1)
    chunks = build_chunks(_doc(), units, config)
    assert len(chunks) >= 4
    assert all(chunk.kind == "text" for chunk in chunks)
    assert all("第二章 流程" in chunk.text for chunk in chunks)
    assert chunks[0].locator["paragraph_start"] == 1
    assert chunks[0].locator["paragraph_end"] == 2
    assert "第2段" in chunks[0].text
    assert "第2段" in chunks[1].text
    assert chunks[1].locator["paragraph_start"] == 2
    for chunk in chunks:
        assert chunk.locator["page_start"] == 1
        assert chunk.locator["page_end"] == 1
        assert len(chunk.text) <= config.chunk_max_chars + 20


def test_long_paragraph_is_split_but_traceable_to_same_unit() -> None:
    long_text = "超长段落内容。" * 80
    unit = _unit(
        unit_id="long-paragraph",
        kind="paragraph",
        ordinal=0,
        unit_key="paragraph:1",
        text=long_text,
        sheet=None,
        locator={"paragraph": 1, "page": 2},
        header_row=None,
        row_number=None,
    )
    config = RagConfig(chunk_max_chars=180)
    chunks = build_chunks(_doc(), [unit], config)
    assert len(chunks) > 1
    assert all(chunk.unit_ids == ("long-paragraph",) for chunk in chunks)
    assert all(chunk.locator["page_start"] == 2 for chunk in chunks)
    assert all(len(chunk.text) <= config.chunk_max_chars for chunk in chunks)
    # 不能丢内容：所有片段拼起来应覆盖原文的字符集合。
    combined = "".join(chunk.text for chunk in chunks)
    assert "超长段落内容" in combined
    assert len(combined) >= len(long_text)
