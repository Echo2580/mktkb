"""Word（.docx）解析：按原文顺序交错保存标题、段落与普通表格。

- 正文顺序取 body 子元素顺序，不先输出全部段落再输出全部表格。
- 标题用样式名 Heading N 识别，段落定位用稳定序号与当前标题路径。
- 表格行作为独立来源单元，表头明确时映射字段，否则只保留列序号并告警，不猜业务字段。
- 内嵌图片不做 OCR，只在报告计数说明；空/坏文件不得成为成功资料。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from .notice_facts import extract_record_facts
from .types import ParseError, ParsedUnit, ParseServices


def _iter_blocks(document):
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style
    name = (style.name if style is not None else "") or ""
    if name.startswith("Heading"):
        try:
            return int(name.split()[-1])
        except ValueError:
            return 1
    return None


def _has_merged_cells(row) -> bool:
    try:
        return len({id(cell._tc) for cell in row.cells}) != len(row.cells)
    except Exception:  # 极少数坏结构不阻断，按普通行处理
        return False


def parse_docx(path: Path, kind: str, services: ParseServices) -> Iterator[ParsedUnit]:
    report = services.report
    report.clear()
    report.update(
        {
            "kind": "docx",
            "paragraph_count": 0,
            "table_count": 0,
            "units": 0,
            "embedded_images": 0,
            "warnings": [],
            "quality": {"complete": True, "issues": []},
        }
    )
    try:
        document = docx.Document(str(path))
    except Exception:
        raise ParseError("Word 文件无法读取，可能已损坏或不是有效 .docx", code="FILE_CORRUPT") from None

    report["embedded_images"] = len(document.element.body.findall(".//" + qn("w:drawing"))) + len(
        document.element.body.findall(".//" + qn("w:pict"))
    )
    if report["embedded_images"]:
        # 首版 Word 内嵌图片不做 OCR；只记录数量，供管理员在预览中知悉
        report["warnings"].append("embedded_images_not_ocr")
    units: list[ParsedUnit] = []
    headings: list[tuple[int, str]] = []
    paragraph_index = 0
    table_index = 0

    for block in _iter_blocks(document):
        if isinstance(block, Paragraph):
            paragraph_index += 1
            text = block.text.strip()
            level = _heading_level(block)
            style_name = block.style.name if block.style is not None else ""
            if level is not None:
                while headings and headings[-1][0] >= level:
                    headings.pop()
                heading = text
                headings.append((level, text))
            else:
                heading = headings[-1][1] if headings else None
            if not text:
                continue
            locator: dict = {"paragraph": paragraph_index, "style": style_name}
            if heading:
                # 契约 Locator 使用单数 heading 键；值为最近的标题文本（无标题时省略）
                locator["heading"] = heading
            units.append(
                ParsedUnit(
                    kind="paragraph",
                    locator=locator,
                    text=text,
                    # T09-D2：正文里明确出现「门店 + 字段 + 值」的通知句补充结构化字段，
                    # 使正文来源能参与 record 检索与冲突比较（locator 仍是段落号/标题）。
                    fields=extract_record_facts(text),
                    warnings=[],
                    unit_key=f"paragraph:{paragraph_index}",
                )
            )
            report["paragraph_count"] += 1
            continue

        table_index += 1
        report["table_count"] += 1
        table_entry = {"index": table_index, "rows": len(block.rows), "data_rows": 0, "warnings": []}
        report.setdefault("tables", []).append(table_entry)
        heading = headings[-1][1] if headings else None
        rows = [[cell.text.strip() for cell in row.cells] for row in block.rows]
        merged_rows = [_has_merged_cells(row) for row in block.rows]
        if any(merged_rows):
            table_entry["warnings"].append("merged_cells")
            report["warnings"].append(f"table_merged_cells:{table_index}")
        header_used = False
        if rows:
            first = rows[0]
            unique = len(set(first)) == len(first)
            if all(cell for cell in first) and unique and not merged_rows[0]:
                header_names = first
                header_used = True
            else:
                header_names = [f"列{index + 1}" for index in range(len(first))]
                table_entry["warnings"].append("generic_column_names")
        else:
            header_names = []
        start = 1 if header_used else 0
        for row_number in range(start, len(rows)):
            cells = rows[row_number]
            if not any(cells):
                continue
            fields = {
                header_names[index]: (cells[index] if index < len(cells) else None)
                for index in range(len(header_names))
            }
            parts = [f"{name}: {value}" for name, value in fields.items() if value not in (None, "")]
            row_warnings: list[str] = []
            if merged_rows[row_number]:
                row_warnings.append("merged_cells")
            units.append(
                ParsedUnit(
                    kind="table_row",
                    locator={**({"heading": heading} if heading else {}), "table": table_index, "row": row_number + 1},
                    text=" | ".join(parts),
                    fields=fields,
                    warnings=row_warnings,
                    unit_key=f"table:{table_index}:row:{row_number + 1}",
                )
            )
            table_entry["data_rows"] += 1

    services.planned_units = len(units)
    report["units"] = len(units)
    if not units:
        report["quality"]["complete"] = False
        report["quality"]["issues"].append({"issue": "empty_content"})
        raise ParseError("Word 文档没有可入库的正文内容", code="EMPTY_CONTENT")

    for unit in units:
        yield unit
