"""T03 本地解析器检查：真实冻结 D01～D04、边界样本与临时构造的异常/边界样本。

只使用本地 openpyxl/python-docx 与冻结语料，不调用模型/OCR/外部服务。
构造样本全部写入 pytest 临时目录，不修改 fixtures/acceptance。
"""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

import docx
import openpyxl
import pytest

from mktkb.ingestion.parsers import (
    ParseError,
    ParseLimitError,
    ParseLimits,
    ParseServices,
    parse_document,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"


def _services(**limit_overrides) -> ParseServices:
    return ParseServices(limits=ParseLimits(**limit_overrides))


def _parse(path: Path, kind: str | None = None, services: ParseServices | None = None):
    services = services or _services()
    kind = kind or path.suffix.lstrip(".").lower()
    return list(parse_document(path, kind, services)), services


def _build_xlsx(path: Path, rows: list[list], *, title: str = "数据") -> Path:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = title
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def _rewrite_member(source: Path, target: Path, member: str, transform) -> Path:
    """复制 OOXML 并改写指定成员，用于构造含缓存公式/危险部件的样本。"""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == member:
                data = transform(data)
            dst.writestr(item, data)
    return target


# ---------------------------------------------------------------- 真实冻结语料


def test_parse_d01_real_sheets_rows_and_hidden_sheet():
    units, services = _parse(FIXTURES / "normal" / "D01_物品位置表.xlsx")
    report = services.report

    sheet_names = [sheet["name"] for sheet in report["sheets"]]
    assert sheet_names == ["物品位置", "备用物料表", "旧草稿"]
    hidden = next(sheet for sheet in report["sheets"] if sheet["name"] == "旧草稿")
    assert hidden["hidden"] is True and hidden["ingested"] is False
    assert "隐藏" in hidden["note"]

    assert len(units) == 9, "主表 8 行 + 备用表 1 行，隐藏旧草稿不入库"
    first = units[0]
    assert first.kind == "table_row"
    assert first.locator["sheet"] == "物品位置"
    assert first.locator["row"] == 8, "第 7 行是表头，第 8 行才是 P01"
    assert first.locator["header_row"] == 7
    assert first.fields["标识"] == "P01"
    assert first.fields["门店"] == "城东店"
    assert first.fields["物品"] == "宣传海报"
    assert first.fields["位置"] == "B区1号货架第二层"
    assert "标识: P01" in first.text and "B区1号货架第二层" in first.text

    p05 = next(unit for unit in units if unit.fields.get("标识") == "P05")
    assert p05.fields["别名"] is None, "空白单元格表示未知，不能编造别名"
    assert p05.locator["row"] == 12

    spare = units[-1]
    assert spare.locator["sheet"] == "备用物料表"
    assert spare.locator["header_row"] == 3
    assert spare.locator["row"] == 4
    assert spare.fields["物品"] == "宣传单" and spare.fields["位置"] == "A区5号柜"

    assert report["kind"] == "xlsx"
    assert report["hidden_sheet_count"] == 1


def test_parse_d02_real_header_phone_and_rows():
    units, services = _parse(FIXTURES / "normal" / "D02_合作店家信息.xlsx")
    assert len(units) == 4
    s01 = units[0]
    assert {key: s01.locator[key] for key in ("sheet", "row", "header_row")} == {
        "sheet": "店家信息",
        "row": 5,
        "header_row": 4,
    }
    assert s01.fields["电话"] == "010-00000001", "电话必须保留前导 0 的字符串形式"
    assert s01.fields["电话"] != "1000000001"
    assert s01.fields["联系人"] == "模拟联系人·陈宁"
    assert s01.fields["合作状态"] == "合作中"
    assert s01.locator["cell_types"]["电话"] == "s"
    assert services.report["sheets"][0]["data_rows"] == 4


def test_parse_d03_real_word_order_and_text():
    units, services = _parse(FIXTURES / "normal" / "D03_市场部工作指南.docx")
    assert [unit.kind for unit in units] == ["paragraph"] * 8
    texts = [unit.text for unit in units]
    assert texts[0] == "市场部工作指南"
    heading_unit = units[2]
    assert heading_unit.text == "2.3 物料领用与登记"
    assert heading_unit.locator["paragraph"] == 3
    follow = units[3]
    assert follow.locator["heading"] == "2.3 物料领用与登记", "契约 Locator 使用单数 heading"
    assert "headings" not in follow.locator, "不得继续使用复数 headings 键"
    assert "物料领用需填写登记表并经门店负责人确认，领取时登记实际领取数量。" in texts
    assert "归还时须核对数量与状态，并在登记表中登记归还日期。" in texts
    assert services.report["embedded_images"] == 0
    assert services.report["table_count"] == 0


def test_parse_d04_real_three_workdays_text():
    units, _ = _parse(FIXTURES / "normal" / "D04_活动策划流程.docx")
    joined = "\n".join(unit.text for unit in units)
    assert "活动申请至少提前 3 个工作日提交，不得以 3 个自然日替代。" in joined
    assert "活动方案需包含目标、时间地点、预算与物料清单四部分。" in joined
    assert "3个工作日" not in joined, "不得改写原文用词或去掉原文空格"


# ---------------------------------------------------------------- 临时构造样本


def _build_interleaved_docx(path: Path) -> Path:
    document = docx.Document()
    document.add_heading("3.1 活动申请", level=1)
    document.add_paragraph("活动申请至少提前 3 个工作日提交。")
    table = document.add_table(rows=3, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "名称", "数量"
    table.cell(1, 0).text, table.cell(1, 1).text = "展架", "2"
    table.cell(2, 0).text, table.cell(2, 1).text = "海报", "5"
    document.add_paragraph("表格之后的一段说明。")
    document.save(path)
    return path


def test_word_keeps_interleaved_body_order(tmp_path: Path):
    path = _build_interleaved_docx(tmp_path / "interleaved.docx")
    units, services = _parse(path)
    assert [unit.kind for unit in units] == ["paragraph", "paragraph", "table_row", "table_row", "paragraph"]
    assert units[0].text == "3.1 活动申请"
    assert units[0].locator["heading"] == "3.1 活动申请"
    assert units[2].fields == {"名称": "展架", "数量": "2"}
    assert units[2].locator["table"] == 1 and units[2].locator["row"] == 2
    assert units[2].locator["heading"] == "3.1 活动申请", "表格行定位同样使用契约 heading 键"
    assert "headings" not in units[2].locator
    assert units[4].text == "表格之后的一段说明。"
    assert units[4].locator["paragraph"] == 3, "段落序号按段落计数，不因表格插入而变化"
    assert units[4].locator["heading"] == "3.1 活动申请"
    assert services.report["table_count"] == 1
    assert services.report["embedded_images"] == 0


def test_excel_keeps_leading_zero_types_and_date(tmp_path: Path):
    path = _build_xlsx(
        tmp_path / "types.xlsx",
        [
            ["标识", "编号", "数量", "日期"],
            ["R1", "00123", 5, datetime(2026, 10, 30, 16, 0)],
        ],
    )
    units, _ = _parse(path)
    assert len(units) == 1
    fields = units[0].fields
    assert fields["编号"] == "00123", "文本编号前导 0 不能丢失"
    assert fields["数量"] == 5
    assert fields["日期"] == "2026-10-30T16:00:00", "日期按原值序列化，不擅自改业务语义"
    assert "编号: 00123" in units[0].text


def test_excel_uses_saved_formula_cache_and_never_recomputes(tmp_path: Path):
    source = _build_xlsx(
        tmp_path / "formula-src.xlsx",
        [["标识", "结果"], ["R1", "=1+2"]],
    )
    target = tmp_path / "formula-cached.xlsx"

    def add_cache(data: bytes) -> bytes:
        text = data.decode("utf-8")
        assert "<f>1+2</f>" in text
        return text.replace("<f>1+2</f>", "<f>1+2</f><v>150</v>").encode("utf-8")

    _rewrite_member(source, target, "xl/worksheets/sheet1.xml", add_cache)
    units, services = _parse(target)
    assert units[0].fields["结果"] in {150, 150.0}, "只能使用已保存缓存值 150，不能执行/重算公式"
    assert "formula_cached_value_used" in units[0].warnings
    assert services.report["formula_cells"] >= 1


def test_excel_formula_without_cache_blocks_complete_success(tmp_path: Path):
    path = _build_xlsx(
        tmp_path / "formula-missing.xlsx",
        [["标识", "结果"], ["R1", "=A2+1"]],
    )
    services = _services()
    collected = []
    with pytest.raises(ParseError) as excinfo:
        for unit in parse_document(path, "xlsx", services):
            collected.append(unit)
    assert excinfo.value.code == "PARSE_INCOMPLETE"
    assert collected, "异常前仍应产出可预览单元"
    assert "formula_cache_missing" in collected[0].warnings
    assert collected[0].fields["结果"] is None, "无缓存值时不能把公式表达式当确定事实"


def test_excel_merged_ambiguous_header_is_not_guessed(tmp_path: Path):
    path = tmp_path / "merged.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "数据"
    sheet["A1"] = "合并表头"
    sheet.merge_cells("A1:B1")
    sheet["A2"] = "城东店"
    sheet["B2"] = "A区1号柜"
    workbook.save(path)
    with pytest.raises(ParseError) as excinfo:
        _parse(path)
    assert excinfo.value.code == "PARSE_UNRECOGNIZED_TABLE"


def test_excel_duplicate_header_names_are_not_guessed(tmp_path: Path):
    path = _build_xlsx(
        tmp_path / "dup-header.xlsx",
        [["名称", "名称"], ["甲", "乙"]],
    )
    with pytest.raises(ParseError) as excinfo:
        _parse(path)
    assert excinfo.value.code == "PARSE_UNRECOGNIZED_TABLE"


def test_excel_reports_hidden_and_empty_sheets(tmp_path: Path):
    path = tmp_path / "sheets.xlsx"
    workbook = openpyxl.Workbook()
    visible = workbook.active
    visible.title = "记录"
    visible.append(["标识", "位置"])
    visible.append(["R1", "A区1号柜"])
    empty = workbook.create_sheet("空白表")
    assert empty.max_row == 1
    hidden = workbook.create_sheet("隐藏表")
    hidden.sheet_state = "hidden"
    hidden.append(["标识", "位置"])
    hidden.append(["R2", "B区2号柜"])
    workbook.save(path)

    units, services = _parse(path)
    assert len(units) == 1 and units[0].fields["标识"] == "R1"
    sheets = {sheet["name"]: sheet for sheet in services.report["sheets"]}
    assert sheets["空白表"]["ingested"] is False
    assert sheets["隐藏表"]["hidden"] is True and sheets["隐藏表"]["ingested"] is False


def test_excel_row_limit_boundary_and_over_limit():
    units, services = _parse(FIXTURES / "boundary" / "B05_恰好5000行.xlsx")
    assert len(units) == 5000
    assert services.report["total_data_rows"] == 5000

    services = _services()
    with pytest.raises(ParseLimitError) as excinfo:
        for _unit in parse_document(FIXTURES / "boundary" / "B06_超过5000行.xlsx", "xlsx", services):
            pass
    assert excinfo.value.code == "EXCEL_ROW_LIMIT"


def test_word_empty_document_is_not_success(tmp_path: Path):
    path = tmp_path / "empty.docx"
    docx.Document().save(path)
    with pytest.raises(ParseError) as excinfo:
        _parse(path)
    assert excinfo.value.code == "EMPTY_CONTENT"


def test_corrupt_frozen_files_raise_parse_error():
    with pytest.raises(ParseError) as docx_error:
        _parse(FIXTURES / "variants" / "A01_损坏的文档.docx")
    assert docx_error.value.code in {"FILE_CORRUPT", "EMPTY_CONTENT"}
    with pytest.raises(ParseError) as xlsx_error:
        _parse(FIXTURES / "variants" / "A02_损坏的表格.xlsx")
    assert xlsx_error.value.code == "FILE_CORRUPT"


def test_unknown_kind_is_rejected():
    with pytest.raises(ParseError) as excinfo:
        _parse(FIXTURES / "normal" / "D05_物料领用规范.pdf", "txt")
    assert excinfo.value.code == "UNSUPPORTED_FILE_TYPE"


# ---------------------------------------------------------------- T03-R1：边界与契约回归


def _build_mixed_unknown_sheet(path: Path) -> Path:
    workbook = openpyxl.Workbook()
    normal = workbook.active
    normal.title = "正常表"
    normal.append(["编号", "位置"])
    normal.append(["P900", "A区"])
    unknown = workbook.create_sheet("未识别记录")
    unknown.append(["唯一字段"])
    unknown.append(["不能静默丢弃的内容"])
    workbook.save(path)
    return path


def test_excel_unknown_nonempty_sheet_marks_incomplete(tmp_path: Path):
    """PM03-01：非空未知结构不得被当说明表跳过并整体成功；报告须保留全部工作表状态。"""
    path = _build_mixed_unknown_sheet(tmp_path / "mixed.xlsx")
    services = _services()
    collected = []
    with pytest.raises(ParseError) as excinfo:
        for unit in parse_document(path, "xlsx", services):
            collected.append(unit)
    assert excinfo.value.code == "PARSE_UNRECOGNIZED_TABLE"
    assert len(collected) == 1, "已识别表的单元仍可预览，但整体不得完整成功"
    report = services.report
    assert report["quality"]["complete"] is False
    assert [sheet["name"] for sheet in report["sheets"]] == ["正常表", "未识别记录"]
    unknown = report["sheets"][1]
    assert unknown["ingested"] is False and "不完整" in unknown["note"]
    assert any(issue.get("issue") == "unrecognized_sheet_structure" for issue in report["quality"]["issues"])


def test_excel_header_after_twelve_preamble_rows_is_recognized(tmp_path: Path):
    """PM03-01：第 13 行才出现表头时允许识别（不强制失败，但不能丢失或假成功）。"""
    workbook = openpyxl.Workbook()
    normal = workbook.active
    normal.title = "正常表"
    normal.append(["编号", "位置"])
    normal.append(["P900", "A区"])
    late = workbook.create_sheet("第13行表头")
    for index in range(12):
        late.append([f"说明{index + 1}"])
    late.append(["编号", "位置"])
    late.append(["P901", "B区"])
    path = tmp_path / "late-header.xlsx"
    workbook.save(path)

    units, services = _parse(path)
    assert len(units) == 2
    late_entry = next(sheet for sheet in services.report["sheets"] if sheet["name"] == "第13行表头")
    assert late_entry["ingested"] is True and late_entry["header_row"] == 13
    assert services.report["quality"]["complete"] is True


def test_excel_cell_metadata_keeps_date_text_vs_date_cell(tmp_path: Path):
    """PM03-04：保留逐单元格原类型/格式/显示，fields 业务值保持兼容。"""
    path = _build_xlsx(
        tmp_path / "cell-types.xlsx",
        [
            ["日期文本", "日期单元格"],
            ["2026-10-28T00:00:00", datetime(2026, 10, 28)],
        ],
    )
    units, services = _parse(path)
    locator = units[0].locator
    cells = {cell["header"]: cell for cell in locator["cells"]}
    assert cells["日期文本"]["raw_type"] == "s"
    assert cells["日期单元格"]["raw_type"] in {"d", "n"}
    assert cells["日期文本"]["raw_type"] != cells["日期单元格"]["raw_type"]
    assert cells["日期单元格"]["number_format"], "应保留必要格式信息"
    assert cells["日期文本"]["column"] == "A" and cells["日期单元格"]["column_index"] == 2
    assert locator["cell_types"] == {"日期文本": "s", "日期单元格": cells["日期单元格"]["raw_type"]}
    # fields 现有业务值语义不变：两者都是原样 ISO 字符串，可被下游直接比较/检索
    assert units[0].fields["日期文本"] == units[0].fields["日期单元格"] == "2026-10-28T00:00:00"
    assert services.report["quality"]["complete"] is True


# ---------------------------------------------------------------- T03-R2：可见无缓存公式表完整性


def _build_formula_sheet_xlsx(path: Path, *, with_normal_sheet: bool) -> Path:
    workbook = openpyxl.Workbook()
    if with_normal_sheet:
        normal = workbook.active
        normal.title = "正常表"
        normal.append(["编号", "位置"])
        normal.append(["P900", "A区"])
        formula = workbook.create_sheet("无缓存公式")
    else:
        formula = workbook.active
        formula.title = "仅公式"
    formula.append(["=1+1", "=2+2"])
    workbook.save(path)
    return path


def _formula_missing_cells(report: dict, sheet_name: str) -> list[dict]:
    entry = next(sheet for sheet in report["sheets"] if sheet["name"] == sheet_name)
    cells = list(entry.get("missing_formula_cells") or [])
    if not cells:
        for issue in report["quality"]["issues"]:
            if issue.get("sheet") == sheet_name and issue.get("issue") == "formula_cache_missing":
                cells.extend(issue.get("cells") or [])
    return cells


def test_excel_visible_uncached_formula_sheet_is_not_empty_and_blocks_success(tmp_path: Path):
    """PM03-R2-01：正常表 + 仅无缓存公式的可见表不得把公式表判空后整体成功。"""
    path = _build_formula_sheet_xlsx(tmp_path / "uncached-sheet.xlsx", with_normal_sheet=True)
    services = _services()
    collected = []
    with pytest.raises(ParseError) as excinfo:
        for unit in parse_document(path, "xlsx", services):
            collected.append(unit)
    assert excinfo.value.code == "PARSE_INCOMPLETE"
    assert len(collected) == 1, "正常表单元仍可预览，但整体不得完整成功"

    report = services.report
    assert report["formula_cells"] == 2
    assert [sheet["name"] for sheet in report["sheets"]] == ["正常表", "无缓存公式"]
    formula_entry = next(sheet for sheet in report["sheets"] if sheet["name"] == "无缓存公式")
    assert formula_entry.get("empty") is not True, "原始公式占用存在，不能伪报空表"
    assert formula_entry["ingested"] is False
    assert "公式" in formula_entry["note"]
    cells = _formula_missing_cells(report, "无缓存公式")
    assert {(cell["row"], cell["column"]) for cell in cells} == {(1, "A"), (1, "B")}
    assert {(cell["row"], cell["column"], cell["formula"]) for cell in cells} == {
        (1, "A", "=1+1"),
        (1, "B", "=2+2"),
    }
    assert report["quality"]["complete"] is False
    assert any(issue.get("issue") == "formula_cache_missing" for issue in report["quality"]["issues"])


def test_excel_only_uncached_formula_file_fails_without_claiming_empty(tmp_path: Path):
    """PM03-R2-01：仅公式文件必须失败，且不得伪报为真正空文件。"""
    path = _build_formula_sheet_xlsx(tmp_path / "only-formula.xlsx", with_normal_sheet=False)
    services = _services()
    with pytest.raises(ParseError) as excinfo:
        _parse(path, services=services)
    assert excinfo.value.code == "PARSE_INCOMPLETE"
    report = services.report
    entry = report["sheets"][0]
    assert entry.get("empty") is not True and "公式" in entry["note"]
    assert report["units"] == 0
    assert report["formula_cells"] == 2
    assert report["quality"]["complete"] is False
    assert len(_formula_missing_cells(report, "仅公式")) == 2


# ---------------------------------------------------------------- T03-R3：整表（表头前/表头内）公式完整性


def test_excel_uncached_formula_before_header_blocks_success(tmp_path: Path):
    """PM03-R3-01：表头前的无缓存公式不得因识别出表头而漏登记；已识别行仍可预览但不完整。"""
    path = _build_xlsx(
        tmp_path / "formula-before-header.xlsx",
        [["=1+1", "=2+2"], ["编号", "位置"], ["P900", "A区"]],
    )
    services = _services()
    collected = []
    with pytest.raises(ParseError) as excinfo:
        for unit in parse_document(path, "xlsx", services):
            collected.append(unit)
    assert excinfo.value.code == "PARSE_INCOMPLETE"
    report = services.report
    assert report["quality"]["complete"] is False
    assert report["formula_cells"] == 2
    entry = report["sheets"][0]
    assert entry["header_row"] == 2 and entry["data_rows"] == 1 and entry["ingested"] is True
    assert "公式" in entry["note"], "表头识别成功也要说明公式内容未知"
    assert {(cell["row"], cell["column"], cell["formula"]) for cell in _formula_missing_cells(report, "数据")} == {
        (1, "A", "=1+1"),
        (1, "B", "=2+2"),
    }
    assert len(collected) == 1 and collected[0].fields == {"编号": "P900", "位置": "A区"}


def test_excel_uncached_formula_in_header_blocks_and_does_not_invent_column(tmp_path: Path):
    """PM03-R3-01：表头单元格是无缓存公式时字段名不可确认，不得生成“列N”并按完整成功入库。"""
    path = _build_xlsx(
        tmp_path / "formula-in-header.xlsx",
        [["编号", "位置", "=1+1"], ["P900", "A区", "不能推断字段意义"]],
    )
    services = _services()
    collected = []
    with pytest.raises(ParseError) as excinfo:
        for unit in parse_document(path, "xlsx", services):
            collected.append(unit)
    assert excinfo.value.code == "PARSE_INCOMPLETE"
    report = services.report
    assert collected == [] and report["units"] == 0
    assert report["quality"]["complete"] is False
    entry = report["sheets"][0]
    assert entry["ingested"] is False and "公式" in entry["note"]
    assert {(cell["row"], cell["column"], cell["formula"]) for cell in _formula_missing_cells(report, "数据")} == {
        (1, "C", "=1+1")
    }
    assert "列3" not in json.dumps(report, ensure_ascii=False), "不得用自动列名掩盖未知表头"


def test_excel_uncached_formula_in_data_row_is_located_in_sheet_issue(tmp_path: Path):
    """PM03-R3-01：数据行缺缓存公式的定位同样保留在整表 issue（sheet/row/column/表达式）。"""
    path = _build_xlsx(tmp_path / "data-row-formula.xlsx", [["标识", "结果"], ["R1", "=A2+1"]])
    services = _services()
    collected = []
    with pytest.raises(ParseError) as excinfo:
        for unit in parse_document(path, "xlsx", services):
            collected.append(unit)
    assert excinfo.value.code == "PARSE_INCOMPLETE"
    report = services.report
    assert report["quality"]["complete"] is False
    issue = next(item for item in report["quality"]["issues"] if item.get("issue") == "formula_cache_missing")
    assert issue["sheet"] == "数据" and len(issue["cells"]) == 1
    assert (issue["cells"][0]["row"], issue["cells"][0]["column"], issue["cells"][0]["formula"]) == (2, "B", "=A2+1")
    assert "formula_cache_missing" in collected[0].warnings
    assert collected[0].fields["结果"] is None, "无缓存值不得把公式表达式当确定事实"
