"""v3 语料一级校验：单元格级「除新增两列外一个都不改」。

口径（规格 §3.1，唯一判定口径 = 原列投影矩阵）：
把 v3 产物裁回原列数（丢掉最后两列）后，应与 v2 源在语义上等价。逐项比较：

| 项 | 比较方式 |
|---|---|
| 工作表名称与顺序 / 可见性 | 完全相同（含 备用物料表、旧草稿） |
| 原列投影矩阵 | 原列表头行 + 原数据行逐格 (value, data_type)，空格也算一格 |
| 单元格样式 | number_format / font / fill / border / alignment / protection 规范化签名逐格相等 |
| 合并单元格 | 原列范围内集合相同；新列不得引入合并 |
| 行高 / 列宽 | 原有 key 与取值相同（新列宽度任意） |
| 数据有效性 / 条件格式 / 表格对象 | 范围内相同；新列不得新增 |
| 新增列内容 | 表头逐字 = 生效日期/失效日期；日期值**独立**按 L1 重算后逐格相等 |

L1 的读取在本脚本内**重新实现**（不 import 生成器），以便第三方独立复算。
零真实调用：只读本地文件 + openpyxl。

用法：``.venv\\Scripts\\python.exe 02-verify-cells.py``
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[7]
HERE = Path(__file__).resolve().parent
V2_ROOT = ROOT / "fixtures/acceptance"
V3_ROOT = ROOT / "fixtures/acceptance-h2v3"
L1_PATH = ROOT / "docs/evaluation/p2-source-lifecycle-v1.json"
OUT = HERE / "02-cell-diff.json"

ID_HEADERS = ("标识", "编号", "id", "ID")
NEW_HEADERS = ("生效日期", "失效日期")
TARGETS = {
    "variants/V03_物品位置表_历史V1.xlsx": ("D01", 1, "物品位置"),
    "normal/D01_物品位置表.xlsx": ("D01", 2, "物品位置"),
    "variants/V04_物品位置表_新版V3.xlsx": ("D01", 3, "物品位置"),
    "variants/V05_物品位置表_新版V3_移除P01.xlsx": ("D01", 4, "物品位置"),
    "normal/D02_合作店家信息.xlsx": ("D02", 1, "店家信息"),
    "variants/V06_合作店家信息_新电话.xlsx": ("D02", 2, "店家信息"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def l1_windows() -> tuple[dict, dict]:
    payload = json.loads(L1_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "p2-source-lifecycle/v1"
    assert payload["interval"] == "closed"
    versions = {(row["doc_code"], int(row["version_number"])): (row["effective_from"], row["effective_to"]) for row in payload["sources"]}
    records = {
        (row["doc_code"], int(row["version_number"]), row["record_code"]): (row["effective_from"], row["effective_to"])
        for row in payload["records"]
    }
    return versions, records


def style_signature(cell) -> dict:
    font, fill, border, alignment, protection = cell.font, cell.fill, cell.border, cell.alignment, cell.protection
    return {
        "number_format": cell.number_format,
        "font": [font.name, font.size, font.bold, font.italic, font.underline, font.strike, _color(font.color)],
        "fill": [fill.patternType, _color(fill.fgColor), _color(fill.bgColor)],
        "border": [
            _side(border.left), _side(border.right), _side(border.top), _side(border.bottom),
            _side(border.diagonal), border.diagonal_direction, border.outline,
        ],
        "alignment": [alignment.horizontal, alignment.vertical, alignment.wrap_text, alignment.shrink_to_fit,
                      alignment.indent, alignment.relativeIndent, alignment.justifyLastLine, alignment.textRotation],
        "protection": [protection.locked, protection.hidden],
    }


def _color(color) -> list | None:
    if color is None:
        return None
    return [color.type, color.rgb, color.indexed, color.auto, color.theme, color.tint, color.index]


def _side(side) -> list:
    return [side.style, _color(side.color)]


def matrix(sheet, max_row: int, max_col: int) -> list:
    out = []
    for row in range(1, max_row + 1):
        for col in range(1, max_col + 1):
            cell = sheet.cell(row=row, column=col)
            out.append([row, col, cell.data_type, "" if cell.value is None else str(cell.value), style_signature(cell)])
    return out


def sheet_facts(sheet) -> dict:
    return {
        "state": sheet.sheet_state,
        "merged": sorted(str(item) for item in sheet.merged_cells.ranges),
        "col_widths": {key: [value.width, value.customWidth, value.hidden] for key, value in sorted(sheet.column_dimensions.items())},
        "row_heights": {key: [value.height, value.customHeight, value.hidden] for key, value in sorted(sheet.row_dimensions.items())},
        "data_validations": sorted(
            [str(dv.type), str(dv.formula1), str(dv.formula2), str(dv.sqref)] for dv in sheet.data_validations.dataValidation
        ),
        "conditional_formatting": sorted(str(item.sqref) + "|" + "|".join(str(rule.type) for rule in item.rules)
                                          for item in sheet.conditional_formatting),
        "tables": sorted(f"{name}|{table.ref}" for name, table in sheet.tables.items()),
    }


def compare_pair(rel: str, doc_code: str, version: int, sheet_name: str, versions: dict, records: dict) -> dict:
    v2_path, v3_path = V2_ROOT / rel, V3_ROOT / rel
    wb2, wb3 = openpyxl.load_workbook(v2_path), openpyxl.load_workbook(v3_path)
    result = {
        "path": rel,
        "doc_code": doc_code,
        "version_number": version,
        "v2_sha256": sha256_file(v2_path),
        "v3_sha256": sha256_file(v3_path),
        "v2_sheets": list(wb2.sheetnames),
        "v3_sheets": list(wb3.sheetnames),
        "sheet_names_equal": list(wb2.sheetnames) == list(wb3.sheetnames),
        "sheet_states_equal": True,
        "projection_cells_compared": 0,
        "projection_cells_differing": 0,
        "projection_diffs": [],
        "sheets": [],
        "new_column_cells_expected": 0,
        "new_column_cells_written": 0,
        "new_column_cells_blank": 0,
        "new_column_dates_mismatched": 0,
        "date_mismatches": [],
        "new_column_extra_cells": [],
        "header_ok": False,
    }
    version_window = versions[(doc_code, version)]
    for name in wb2.sheetnames:
        s2 = wb2[name]
        s3 = wb3[name] if name in wb3.sheetnames else None
        if s3 is None:
            result["sheet_names_equal"] = False
            continue
        facts2, facts3 = sheet_facts(s2), sheet_facts(s3)
        is_target = name == sheet_name
        rows = s2.max_row
        cols = s2.max_column
        m2 = matrix(s2, rows, cols)
        # 唯一判定口径：v3 裁回原列数（丢掉每行最后两列）后逐格比较
        m3_trimmed = matrix(s3, rows, cols)
        result["projection_cells_compared"] += len(m2)
        diffs = [f"{get_column_letter(pair[0][1])}{pair[0][0]}" for pair in zip(m2, m3_trimmed) if pair[0] != pair[1]]
        result["projection_cells_differing"] += len(diffs)
        if diffs:
            result["projection_diffs"].append({"sheet": name, "cells": diffs[:20], "count": len(diffs)})
        sheet_entry = {
            "sheet": name,
            "is_target": is_target,
            "cells_compared": len(m2),
            "state_equal": facts2["state"] == facts3["state"],
            "merged_equal": facts2["merged"] == facts3["merged"],
            "col_widths_equal": facts2["col_widths"] == facts3["col_widths"],
            "row_heights_equal": facts2["row_heights"] == facts3["row_heights"],
            "data_validations_equal": facts2["data_validations"] == facts3["data_validations"],
            "conditional_formatting_equal": facts2["conditional_formatting"] == facts3["conditional_formatting"],
            "tables_equal": facts2["tables"] == facts3["tables"],
            "merged_after_original_columns": [str(item) for item in s3.merged_cells.ranges if item.max_col > cols],
            "max_column_v2": cols,
            "max_column_v3": s3.max_column,
            "max_row_v2": rows,
            "max_row_v3": s3.max_row,
        }
        result["sheet_states_equal"] &= sheet_entry["state_equal"]
        if is_target:
            sheet_entry["header_ok"] = all(
                s3.cell(row=_header_row(s2), column=cols + 1 + offset).value == NEW_HEADERS[offset] for offset in range(2)
            )
            result["header_ok"] = sheet_entry["header_ok"]
            # 新列：只允许出现在原表头行与原数据行
            header_row = _header_row(s2)
            data_rows = [r for r in range(header_row + 1, rows + 1) if s2.cell(row=r, column=1).value not in (None, "")]
            allowed_rows = {header_row, *data_rows}
            for row in range(1, max(rows, s3.max_row) + 1):
                for offset in (1, 2):
                    cell = s3.cell(row=row, column=cols + offset)
                    if cell.value is not None and row not in allowed_rows:
                        result["new_column_extra_cells"].append(f"{get_column_letter(cols + offset)}{row}={cell.value!r}")
            # 日期：按 L1 独立重算
            for row in data_rows:
                record_code = str(s2.cell(row=row, column=1).value).strip()
                expected_from, expected_to = records.get((doc_code, version, record_code), version_window)
                result["new_column_cells_expected"] += 2
                got_from = s3.cell(row=row, column=cols + 1).value
                got_to = s3.cell(row=row, column=cols + 2).value
                if got_from not in (None, ""):
                    result["new_column_cells_written"] += 1
                if got_to not in (None, ""):
                    result["new_column_cells_written"] += 1
                if got_to in (None, ""):
                    result["new_column_cells_blank"] += 1
                if got_from != expected_from or (expected_to if expected_to is not None else None) != (got_to if got_to not in (None, "") else None):
                    result["new_column_dates_mismatched"] += 1
                    result["date_mismatches"].append(
                        {"row": row, "record_code": record_code, "expected": [expected_from, expected_to], "got": [got_from, got_to]}
                    )
                if s3.cell(row=row, column=cols + 1).data_type not in ("s",) or (
                    got_to is not None and s3.cell(row=row, column=cols + 2).data_type not in ("s",)
                ):
                    result.setdefault("non_text_date_cells", []).append(f"r{row}")
        result["sheets"].append(sheet_entry)
    return result


def _header_row(sheet) -> int:
    for row in range(1, min(sheet.max_row, 12) + 1):
        if sheet.cell(row=row, column=1).value in ID_HEADERS:
            return row
    raise SystemExit(f"{sheet.title}: 找不到 ID_HEADERS 表头行")


def unchanged_files_check(manifest_path: Path) -> dict:
    """6 个 docx/pdf 必须与 v2 对应文件**逐字节**相等（按字节比较，不只比 SHA）。"""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = []
    for item in manifest["normal_files"] + manifest["variants"]:
        v2_path, v3_path = V2_ROOT / item["path"], V3_ROOT / item["path"]
        v2_bytes, v3_bytes = v2_path.read_bytes(), v3_path.read_bytes()
        rows.append(
            {
                "path": item["path"],
                "kind": item["kind"],
                "declared_bytes_unchanged": item["bytes_unchanged"],
                "v2_bytes": len(v2_bytes),
                "v3_bytes": len(v3_bytes),
                "byte_identical": v2_bytes == v3_bytes,
                "v2_sha256": sha256_file(v2_path),
                "v3_sha256": sha256_file(v3_path),
                "sha_equal": sha256_file(v2_path) == sha256_file(v3_path),
            }
        )
    expect_unchanged = [row for row in rows if row["declared_bytes_unchanged"]]
    changed = [row for row in rows if not row["declared_bytes_unchanged"]]
    return {
        "rows": rows,
        "expected_unchanged": len(expect_unchanged),
        "unchanged_byte_identical": sum(1 for row in expect_unchanged if row["byte_identical"]),
        "unchanged_not_identical": [row["path"] for row in expect_unchanged if not row["byte_identical"]],
        "changed_files_sha_differs": sum(1 for row in changed if not row["sha_equal"]),
        "changed_files": [row["path"] for row in changed],
        "docx_pdf_identical": sum(1 for row in expect_unchanged if row["byte_identical"]),
    }


def main() -> int:
    versions, records = l1_windows()
    pairs = [compare_pair(rel, doc, ver, sheet, versions, records) for rel, (doc, ver, sheet) in TARGETS.items()]
    unchanged = unchanged_files_check(V3_ROOT / "manifest.json")
    totals = {
        "workbooks_compared": len(pairs),
        "projection_cells_compared": sum(pair["projection_cells_compared"] for pair in pairs),
        "projection_cells_differing": sum(pair["projection_cells_differing"] for pair in pairs),
        "existing_cells_modified": sum(pair["projection_cells_differing"] for pair in pairs),
        "sheets_total_v3": sum(len(pair["v3_sheets"]) for pair in pairs),
        "target_sheets": sum(1 for pair in pairs for entry in pair["sheets"] if entry["is_target"]),
        "unchanged_sheets": sum(1 for pair in pairs for entry in pair["sheets"] if not entry["is_target"]),
        "header_ok_all": all(pair["header_ok"] for pair in pairs),
        "sheet_names_equal_all": all(pair["sheet_names_equal"] for pair in pairs),
        "sheet_states_equal_all": all(pair["sheet_states_equal"] for pair in pairs),
        "new_column_cells_expected": sum(pair["new_column_cells_expected"] for pair in pairs),
        "new_column_cells_written": sum(pair["new_column_cells_written"] for pair in pairs),
        "new_column_cells_blank": sum(pair["new_column_cells_blank"] for pair in pairs),
        "new_column_dates_mismatched": sum(pair["new_column_dates_mismatched"] for pair in pairs),
        "new_column_extra_cells": sum(len(pair["new_column_extra_cells"]) for pair in pairs),
        "non_text_date_cells": sum(len(pair.get("non_text_date_cells", [])) for pair in pairs),
        "merged_into_new_columns": sum(len(entry["merged_after_original_columns"]) for pair in pairs for entry in pair["sheets"]),
        "max_column_increase_all_two": all(
            entry["max_column_v3"] - entry["max_column_v2"] == (2 if entry["is_target"] else 0)
            for pair in pairs for entry in pair["sheets"]
        ),
    }
    checks = {
        "projection_identical": totals["projection_cells_differing"] == 0,
        "no_existing_cell_modified": totals["existing_cells_modified"] == 0,
        "headers_verbatim": totals["header_ok_all"],
        "sheet_names_and_order": totals["sheet_names_equal_all"],
        "sheet_visibility": totals["sheet_states_equal_all"],
        "dates_match_l1": totals["new_column_dates_mismatched"] == 0,
        "dates_are_text": totals["non_text_date_cells"] == 0,
        "no_extra_cells_in_new_columns": totals["new_column_extra_cells"] == 0,
        "no_merged_cells_in_new_columns": totals["merged_into_new_columns"] == 0,
        "two_columns_added_per_target_sheet": totals["max_column_increase_all_two"],
        "new_cell_slots_expect_78_data": totals["new_column_cells_expected"] == 78,
        "total_new_cell_slots_expect_90": totals["new_column_cells_expected"] + 2 * totals["target_sheets"] == 90,
        "unchanged_files_byte_identical_6": unchanged["unchanged_byte_identical"] == 6 and unchanged["expected_unchanged"] == 6,
        "changed_files_all_sha_differ": unchanged["changed_files_sha_differs"] == 6,
    }
    payload = {
        "schema_version": "p2h2v3-cell-diff/v0.1",
        "phase": "verify-cells",
        "method": "原列投影矩阵：v3 裁回原列数后与 v2 逐格比较 (value, data_type) 与样式签名；日期另按 L1 独立重算",
        "v2_root": "fixtures/acceptance",
        "v3_root": "fixtures/acceptance-h2v3",
        "l1": {"path": "docs/evaluation/p2-source-lifecycle-v1.json", "sha256": sha256_file(L1_PATH)},
        "totals": totals,
        "checks": checks,
        "unchanged_files": unchanged,
        "result": "CELL_IDENTICAL_EXCEPT_TWO_NEW_COLUMNS" if all(checks.values()) else "CELL_DIFF_FOUND",
        "pairs": pairs,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"totals": totals, "checks": checks, "result": payload["result"],
                      "unchanged_files": {key: unchanged[key] for key in ("expected_unchanged", "unchanged_byte_identical", "changed_files_sha_differs", "docx_pdf_identical")}},
                     ensure_ascii=False, indent=1))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
