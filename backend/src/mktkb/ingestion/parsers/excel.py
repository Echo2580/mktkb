"""Excel（.xlsx）解析：逐可见工作表识别真实表头、保留原行号/原值与逐单元格元数据。

规则（T03-R1 修正）：
- 不固定首行；前 50 行内按“多列、字符串、下一行仍有同列数据”的规则识别表头，
  允许标题/说明前缀行（如第 13 行才出现表头）。
- 任何可见、非空但无法识别表头结构的工作表都视为“内容不完整”，不再当作说明表跳过；
  仍先扫描全部工作表，处理报告保留每一张表的状态，最后以失败结束，不整体成功。
- 逐数据行保存单元格元数据（列/列号/表头/原类型/number_format/显示值；公式区分表达式、
  缓存值缺失），`fields` 仍保留原有业务值语义（日期单元格转为 ISO 字符串，电话/编号保留字符串）。
- 隐藏表不入库但报告；空表/仅有表头无数据的表如实登记，不算不完整。
- 公式不执行、不重算：仅用已保存缓存值；无缓存时该值视为未知并使任务不能完整成功。
  该检查按可见工作表整表执行（表头前、表头行、数据行一视同仁），不由是否识别出表头决定；
  表头单元格本身是无缓存公式时字段名不可确认，不得用“列N”自动命名后按完整成功保存。
- 跨可见工作表有效数据行合计上限由 ParseLimits 决定，超限直接失败，不截断成部分成功。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.worksheet import Worksheet

from .types import ParseError, ParseLimitError, ParsedUnit, ParseServices

# 允许标题/说明前缀行；仍找不到可靠表头时保守失败，而不是猜成说明文字
MAX_HEADER_SCAN_ROWS = 50


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _nonempty_count(values: list) -> int:
    return sum(1 for value in values if not _blank(value))


def _display(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (datetime, date)):
        return raw.isoformat()
    if isinstance(raw, bytes):
        return f"<binary:{len(raw)}>"
    return str(raw)


def _cell_value(cell, cached_ws) -> tuple[object, list[str], dict]:
    """返回 (业务值, 行内告警, 单元格元数据)。元数据保留原类型/格式/显示与公式缓存状态。"""
    raw = cell.value
    meta: dict = {
        "column": get_column_letter(cell.column),
        "column_index": cell.column,
        "raw_type": cell.data_type,
        "number_format": cell.number_format,
        "display": _display(raw),
    }
    value = raw
    warnings: list[str] = []
    if cell.data_type == "f":
        cached = None
        if cached_ws is not None:
            try:
                cached = cached_ws.cell(row=cell.row, column=cell.column).value
            except (ValueError, KeyError):
                cached = None
        meta["formula"] = raw if isinstance(raw, str) else str(raw)
        if cached is None:
            warnings.append("formula_cache_missing")
            value = None
            meta["cache_status"] = "missing"
            meta["display"] = None
        else:
            warnings.append("formula_cached_value_used")
            value = cached
            meta["cache_status"] = "cached"
            meta["display"] = _display(cached)
    elif isinstance(raw, (datetime, date)):
        value = raw.isoformat()
        meta["display"] = raw.isoformat()
    elif isinstance(raw, bytes):
        value = f"<binary:{len(raw)}>"
    return value, warnings, meta


def _read_rows(worksheet: Worksheet, cached_ws) -> list[tuple[int, list, list[str], int, list[dict]]]:
    """返回 (行号, 业务值, 行内告警, 占用列数, 单元格元数据)。公式单元格即使无缓存也计入占用列。"""
    rows: list[tuple[int, list, list[str], int, list[dict]]] = []
    max_row = worksheet.max_row or 0
    max_col = worksheet.max_column or 0
    for row_number in range(1, max_row + 1):
        values: list = []
        warnings: list[str] = []
        metas: list[dict] = []
        occupied = 0
        for column in range(1, max_col + 1):
            cell = worksheet.cell(row=row_number, column=column)
            value, cell_warnings, meta = _cell_value(cell, cached_ws)
            values.append(value)
            warnings.extend(cell_warnings)
            metas.append(meta)
            if not _blank(value) or cell.data_type == "f":
                occupied += 1
        rows.append((row_number, values, warnings, occupied, metas))
    return rows


def _find_header_index(rows: list[tuple[int, list, list[str], int, list[dict]]]) -> int | None:
    """在前若干行中选最像表头的一行；不满足最低分数时返回 None（交给调用方判定不完整）。"""
    best: tuple[int, int] | None = None
    for index, (_row_number, values, _warnings, _occupied, _metas) in enumerate(rows[:MAX_HEADER_SCAN_ROWS]):
        nonempty = [value for value in values if not _blank(value)]
        if len(nonempty) < 2:
            continue
        all_strings = all(isinstance(value, str) for value in nonempty)
        next_has_same_width = False
        for _n, _next_values, _nw, next_occupied, _nm in rows[index + 1 : index + 3]:
            if next_occupied >= len(nonempty):
                next_has_same_width = True
                break
        score = (3 if all_strings else 0) + (2 if next_has_same_width else 0) + (1 if len(nonempty) >= 3 else 0)
        if best is None or score > best[0]:
            best = (score, index)
    if best is None or best[0] < 4:
        return None
    return best[1]


def _incomplete_note(reason: str, missing_formulas: bool) -> str:
    """缺缓存公式时把“公式结果未知”与结构原因同时说明，不因表头分支覆盖而丢失公式原因。"""
    if not missing_formulas:
        return reason
    return f"可见表含无缓存公式，公式结果未知，无法确认内容完整；{reason}"


def _missing_formula_cells(rows: list[tuple[int, list, list[str], int, list[dict]]]) -> list[dict]:
    """收集整张工作表中无已保存缓存的公式单元格位置（sheet 内 row/column 定位）。"""
    cells: list[dict] = []
    for row_number, _values, _warnings, _occupied, metas in rows:
        for meta in metas:
            if meta.get("cache_status") == "missing":
                cells.append(
                    {
                        "row": row_number,
                        "column": meta.get("column"),
                        "column_index": meta.get("column_index"),
                        "formula": meta.get("formula"),
                    }
                )
    return cells


def parse_xlsx(path: Path, kind: str, services: ParseServices) -> Iterator[ParsedUnit]:
    report = services.report
    report.clear()
    report.update(
        {
            "kind": "xlsx",
            "sheets": [],
            "warnings": [],
            "hidden_sheet_count": 0,
            "formula_cells": 0,
            "total_data_rows": 0,
            "units": 0,
            "quality": {"complete": True, "issues": []},
        }
    )
    issues: list[dict] = report["quality"]["issues"]

    try:
        workbook = openpyxl.load_workbook(filename=path, data_only=False, read_only=False)
    except (InvalidFileException, OSError, KeyError, ValueError, TypeError, EOFError):
        raise ParseError("Excel 文件无法读取，可能已损坏", code="FILE_CORRUPT") from None
    except Exception:  # openpyxl/zip 层的其他解析异常统一转为稳定错误
        raise ParseError("Excel 文件无法读取，可能已损坏", code="FILE_CORRUPT") from None

    try:
        try:
            cached_book = openpyxl.load_workbook(filename=path, data_only=True, read_only=False)
        except Exception:
            cached_book = None

        # ---- 第一遍：扫描全部工作表，登记状态并识别表头；不因单表异常提前丢失其他表状态 ----
        plans: list[dict] = []
        total_rows = 0
        for worksheet in workbook.worksheets:
            hidden = worksheet.sheet_state != "visible"
            entry: dict = {
                "name": worksheet.title,
                "hidden": hidden,
                "ingested": False,
                "header_row": None,
                "data_rows": 0,
                "note": "",
            }
            report["sheets"].append(entry)
            if hidden:
                report["hidden_sheet_count"] += 1
                entry["note"] = "隐藏工作表未入库"
                continue

            cached_ws = None
            if cached_book is not None and worksheet.title in cached_book.sheetnames:
                cached_ws = cached_book[worksheet.title]
            rows = _read_rows(worksheet, cached_ws)
            for _n, _values, warnings, _occupied, _metas in rows:
                report["formula_cells"] += sum(1 for warning in warnings if warning.startswith("formula_"))
            # 空表判定必须依据原始单元格占用（含无缓存公式单元格），不能用转换后的缓存业务值：
            # 无缓存公式的 value 为 None，但原始公式内容仍存在且结果未知，不能因此当作空表丢弃。
            if not any(occupied > 0 for _n, _values, _warnings, occupied, _metas in rows):
                entry["empty"] = True
                entry["note"] = "空工作表"
                continue

            merged = [
                rng for rng in worksheet.merged_cells.ranges if rng.max_col > rng.min_col or rng.max_row > rng.min_row
            ]
            # 缺缓存公式按可见工作表整表统一登记（表头前、表头行、数据行一视同仁），
            # 是否识别出表头不得改变该安全条件；定位保留在表摘要与 quality.issues 两处。
            missing_formulas = _missing_formula_cells(rows)
            if missing_formulas:
                entry["missing_formula_cells"] = missing_formulas
                report["quality"]["complete"] = False
                report["warnings"].append(f"sheet_formula_cache_missing:{worksheet.title}")
                issues.append(
                    {"sheet": worksheet.title, "issue": "formula_cache_missing", "cells": missing_formulas}
                )
            header_index = _find_header_index(rows)
            plan = {"entry": entry, "rows": rows, "header_index": header_index, "merged": merged}
            if header_index is None:
                if missing_formulas:
                    # 可见公式内容不因缓存未知而消失：保留 sheet/row/column 定位并登记不完整
                    entry["note"] = "可见表含无缓存公式，公式结果未知，无法确认内容完整（未入库，整体标记不完整）"
                    plans.append(plan)
                    continue
                # 非空未知结构不能当说明表静默跳过，登记为内容不完整
                entry["note"] = "非空但未识别到可靠表头结构（未入库，整体标记不完整）"
                issues.append({"sheet": worksheet.title, "issue": "unrecognized_sheet_structure"})
                report["quality"]["complete"] = False
                report["warnings"].append(f"sheet_unrecognized_structure:{worksheet.title}")
                plans.append(plan)
                continue

            header_row_number, header_values, _header_warnings, _header_occupied, header_metas = rows[header_index]
            header_names: list[str | None] = [
                None if _blank(value) else str(value).strip() for value in header_values
            ]
            if any(meta.get("cache_status") == "missing" for meta in header_metas):
                # 表头单元格本身是无缓存公式：字段名不可确认，不得生成“列N”后按完整成功保存
                entry["note"] = "表头含无缓存公式，字段名无法确认（未入库，整体标记不完整）"
                plans.append(plan)
                continue
            if any(rng.min_row <= header_row_number <= rng.max_row for rng in merged) or any(
                rng.min_row > header_row_number for rng in merged
            ):
                entry["note"] = _incomplete_note(
                    "表头或数据区包含合并单元格，字段关系不明确（未入库，整体标记不完整）", bool(missing_formulas)
                )
                issues.append({"sheet": worksheet.title, "issue": "merged_header_rows"})
                report["quality"]["complete"] = False
                plans.append(plan)
                continue
            named = [name for name in header_names if name]
            if len(set(named)) != len(named):
                entry["note"] = _incomplete_note(
                    "表头存在重复字段，字段关系不明确（未入库，整体标记不完整）", bool(missing_formulas)
                )
                issues.append({"sheet": worksheet.title, "issue": "duplicate_header_names"})
                report["quality"]["complete"] = False
                plans.append(plan)
                continue

            plan["header_row"] = header_row_number
            plan["header_names"] = [
                name if name is not None else f"列{index + 1}" for index, name in enumerate(header_names)
            ]
            sheet_rows = sum(
                1
                for _n, values, warnings, _occ, _m in rows[header_index + 1 :]
                if _nonempty_count(values) > 0 or "formula_cache_missing" in warnings
            )
            plan["data_rows"] = sheet_rows
            entry["header_row"] = header_row_number
            entry["data_rows"] = sheet_rows
            entry["ingested"] = sheet_rows > 0
            entry["note"] = _incomplete_note(
                "已识别为记录表" if sheet_rows else "表头明确但无有效数据行（未入库）", bool(missing_formulas)
            )
            total_rows += sheet_rows
            plans.append(plan)

        report["total_data_rows"] = total_rows
        if total_rows > services.limits.excel_max_data_rows:
            report["quality"]["complete"] = False
            issues.append({"issue": "excel_row_limit"})
            raise ParseLimitError(
                f"Excel 跨可见工作表有效数据行超过 {services.limits.excel_max_data_rows} 条上限"
            )

        # ---- 第二遍：为已识别的表构造来源单元（含逐单元格元数据） ----
        units: list[ParsedUnit] = []
        for plan in plans:
            if plan.get("header_row") is None or plan.get("data_rows", 0) <= 0:
                continue
            entry = plan["entry"]
            header_names = plan["header_names"]
            header_row_number = plan["header_row"]
            for row_number, values, row_warnings, _occupied, metas in plan["rows"][plan["header_index"] + 1 :]:
                if _nonempty_count(values) == 0 and "formula_cache_missing" not in row_warnings:
                    continue
                fields: dict = {}
                parts: list[str] = []
                cells_meta: list[dict] = []
                cell_types: dict = {}
                for index, name in enumerate(header_names):
                    value = values[index] if index < len(values) else None
                    meta = dict(metas[index]) if index < len(metas) else {}
                    meta["header"] = name
                    cells_meta.append(meta)
                    cell_types[name] = meta.get("raw_type")
                    fields[name] = value
                    if value is not None:
                        parts.append(f"{name}: {value}")
                # 缺缓存公式的定位与整体不完整已在第一遍按整表统一登记（含数据行），此处不再重复登记；
                # 单元的 warnings 仍保留 formula_cache_missing，供预览如实显示该值为未知。
                units.append(
                    ParsedUnit(
                        kind="table_row",
                        locator={
                            "sheet": entry["name"],
                            "row": row_number,
                            "header_row": header_row_number,
                            "cells": cells_meta,
                            "cell_types": cell_types,
                        },
                        text=" | ".join(parts),
                        fields=fields,
                        warnings=row_warnings,
                        unit_key=f"sheet:{entry['name']}:row:{row_number}",
                        sheet=entry["name"],
                    )
                )

        services.planned_units = len(units)
        report["units"] = len(units)
        if not units:
            report["quality"]["complete"] = False
            if any(issue.get("issue") == "formula_cache_missing" for issue in issues):
                raise ParseError(
                    "可见工作表仅含无缓存公式或其他无法确认的内容，公式结果未知，不能作为完整资料",
                    code="PARSE_INCOMPLETE",
                )
            if issues:
                raise ParseError(
                    "存在非空但无法识别表头结构的工作表，无法确认内容完整",
                    code="PARSE_UNRECOGNIZED_TABLE",
                )
            issues.append({"issue": "empty_content"})
            raise ParseError("Excel 未包含可识别的记录表数据", code="EMPTY_CONTENT")

        for unit in units:
            yield unit

        if issues:
            # 先产出可预览的已识别单元，再以失败结束：不得整体成功或标 quality.complete
            if any(issue.get("issue") == "formula_cache_missing" for issue in issues):
                raise ParseError(
                    "存在无缓存公式单元格，公式结果未知，无法确认记录完整性；请提供含已保存值的版本",
                    code="PARSE_INCOMPLETE",
                )
            if any(issue.get("issue") == "unrecognized_sheet_structure" for issue in issues):
                raise ParseError(
                    "存在非空但无法识别表头结构的工作表，不能确认内容完整；请提供规范表格或拆分后重传",
                    code="PARSE_UNRECOGNIZED_TABLE",
                )
            raise ParseError(
                "表格存在无法确认的完整性问题，请检查后重新上传",
                code="PARSE_INCOMPLETE",
            )
    finally:
        workbook.close()
        if cached_book is not None:
            cached_book.close()
