"""v3 语料返工 R1：单元格级一级校验（原列投影 + 哨兵落点 + R1≠R0 的逐格差）。

三块判定，缺一不可：

**A. R1 交付件 vs v2 源（唯一判定口径 = 规格 §3.1 原列投影矩阵）**
把 v3 产物裁回 v2 的列数/行数后逐格比较 `(value, data_type)` 与样式签名，必须**全等**；
`existing_cells_modified` 必须为 **0**。新列另按 L1 独立重算（不 import 生成器）。

**B. 哨兵审计（R1 新增）**
`失效日期` 的每格必须落在且只落在两个互斥分支：
`L1.effective_to is None` ⇒ 字面值恰为 `未声明`；否则 ⇒ 逐字等于 L1 日期。
哨兵总数必须 = 11（V05 7 + V06 4），且只出现在 V05/V06；`生效日期` 列全为日期。

**C. R1 vs R0（上一轮交付）逐格差（R1 新增）**
用**上一轮的生成器**（`../evidence/01-build-corpus.py`，只读）在临时目录重放 R0，
再用 `00r1-baseline.json` 里记录的 R0 交付件 SHA256 交叉校验这次重放确实等于 R0；
然后把 R1 与 R0 逐格 diff（含新列），差异**只允许**是那 11 格「空 → `未声明`」。
`生效日期` 列差异必须为 0 —— 这就是「`生效日期` 列不变」的逐格证明。

零真实调用：只读本地文件 + openpyxl + 本地子进程。
用法：``.venv\\Scripts\\python.exe 02r1-verify-cells.py``
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[7]
V2_ROOT = ROOT / "fixtures/acceptance"
V3_ROOT = ROOT / "fixtures/acceptance-h2v3"
L1_PATH = ROOT / "docs/evaluation/p2-source-lifecycle-v1.json"
R0_GENERATOR = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-corpus/evidence/01-build-corpus.py"
BASELINE = HERE / "00r1-baseline.json"
OUT = HERE / "02r1-cell-diff.json"

SENTINEL = "未声明"
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


def plain_matrix(sheet, max_row: int, max_col: int) -> list:
    """R1 vs R0 用：只要 (value, data_type)，不做样式（两轮样式契约相同，但样式噪声会淹没差异）。"""
    out = []
    for row in range(1, max_row + 1):
        for col in range(1, max_col + 1):
            cell = sheet.cell(row=row, column=col)
            out.append([row, col, cell.data_type, "" if cell.value is None else str(cell.value)])
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


def _header_row(sheet) -> int:
    for row in range(1, min(sheet.max_row, 12) + 1):
        if sheet.cell(row=row, column=1).value in ID_HEADERS:
            return row
    raise SystemExit(f"{sheet.title}: 找不到 ID_HEADERS 表头行")


def compare_pair(rel: str, doc_code: str, version: int, sheet_name: str, versions: dict, records: dict) -> dict:
    """A + B：R1 对 v2 的原列投影，以及新列的 L1 逐格重算与哨兵审计。"""
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
        "new_column_date_cells_written": 0,
        "new_column_sentinel_cells": 0,
        "new_column_blank_cells": 0,
        "new_column_dates_mismatched": 0,
        "date_mismatches": [],
        "sentinel_mismatches": [],
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
        rows, cols = s2.max_row, s2.max_column
        m2 = matrix(s2, rows, cols)
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
            header_row = _header_row(s2)
            data_rows = [r for r in range(header_row + 1, rows + 1) if s2.cell(row=r, column=1).value not in (None, "")]
            allowed_rows = {header_row, *data_rows}
            for row in range(1, max(rows, s3.max_row) + 1):
                for offset in (1, 2):
                    cell = s3.cell(row=row, column=cols + offset)
                    if cell.value is not None and row not in allowed_rows:
                        result["new_column_extra_cells"].append(f"{get_column_letter(cols + offset)}{row}={cell.value!r}")
            for row in data_rows:
                record_code = str(s2.cell(row=row, column=1).value).strip()
                expected_from, expected_to = records.get((doc_code, version, record_code), version_window)
                result["new_column_cells_expected"] += 2
                from_cell = s3.cell(row=row, column=cols + 1)
                to_cell = s3.cell(row=row, column=cols + 2)
                got_from, got_to = from_cell.value, to_cell.value
                if from_cell.data_type == "s" and got_from:
                    result["new_column_date_cells_written"] += 1
                # ---- B. 哨兵审计（两分支互斥且穷尽）----
                if expected_to is None:
                    if got_to == SENTINEL and to_cell.data_type == "s":
                        result["new_column_sentinel_cells"] += 1
                    else:
                        result["sentinel_mismatches"].append(
                            {"row": row, "record_code": record_code, "expected_sentinel": SENTINEL, "got": got_to, "data_type": to_cell.data_type}
                        )
                else:
                    if got_to == expected_to and to_cell.data_type == "s":
                        result["new_column_date_cells_written"] += 1
                    else:
                        result["new_column_dates_mismatched"] += 1
                        result["date_mismatches"].append({"row": row, "record_code": record_code, "expected": expected_to, "got": got_to})
                if got_to in (None, ""):
                    result["new_column_blank_cells"] += 1
                if got_from != expected_from:
                    result["new_column_dates_mismatched"] += 1
                    result["date_mismatches"].append(
                        {"row": row, "record_code": record_code, "column": "生效日期", "expected": expected_from, "got": got_from}
                    )
        result["sheets"].append(sheet_entry)
    return result


def r1_vs_r0(rel: str, sheet_name: str, r0_root: Path, baseline: dict) -> dict:
    """C：R1 与 R0 的逐格差（含新列），只允许 11 格「空 → 未声明」。"""
    r0_path = r0_root / rel
    if not r0_path.is_file():
        return {"path": rel, "r0_present": False}
    r0_sha_declared = baseline.get("r1_start_delivery", {}).get(rel, {}).get("sha256")
    wb0, wb1 = openpyxl.load_workbook(r0_path), openpyxl.load_workbook(V3_ROOT / rel)
    diffs: list[dict] = []
    sentinel_added = 0
    sentinel_removed = 0
    from_column_diffs = 0
    other_diffs = 0
    for name in wb0.sheetnames:
        s0, s1 = wb0[name], wb1[name]
        rows, cols = max(s0.max_row, s1.max_row), max(s0.max_column, s1.max_column)
        m0, m1 = plain_matrix(s0, rows, cols), plain_matrix(s1, rows, cols)
        header_row = _header_row(s0) if name == sheet_name else None
        from_col = (cols - 1) if name == sheet_name else None
        for cell0, cell1 in zip(m0, m1):
            if cell0 == cell1:
                continue
            record = {"sheet": name, "cell": f"{get_column_letter(cell0[1])}{cell0[0]}", "r0": cell0[2:], "r1": cell1[2:]}
            diffs.append(record)
            if header_row is not None and from_col is not None and cell0[1] == from_col and cell0[0] > header_row:
                from_column_diffs += 1
            elif cell0[2:] == ["n", ""] and cell1[2:] == ["s", SENTINEL]:
                sentinel_added += 1
            elif cell0[2:][1] == SENTINEL and cell1[2:][1] == "":
                sentinel_removed += 1
            else:
                other_diffs += 1
    return {
        "path": rel,
        "r0_present": True,
        "r0_sha256_reconstructed": sha256_file(r0_path),
        "r0_sha256_declared_in_baseline": r0_sha_declared,
        "r0_reconstruction_matches_baseline": r0_sha_declared == sha256_file(r0_path),
        "r0_sha256_delivered_now": sha256_file(V3_ROOT / rel),
        "diff_count": len(diffs),
        "sentinel_added": sentinel_added,
        "sentinel_removed": sentinel_removed,
        "from_column_diffs": from_column_diffs,
        "other_diffs": other_diffs,
        "diffs": diffs[:40],
    }


def unchanged_files_check(manifest_path: Path) -> dict:
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
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    versions, records = l1_windows()
    pairs = [compare_pair(rel, doc, ver, sheet, versions, records) for rel, (doc, ver, sheet) in TARGETS.items()]
    unchanged = unchanged_files_check(V3_ROOT / "manifest.json")

    with tempfile.TemporaryDirectory() as workdir:
        r0_root = Path(workdir) / "r0"
        completed = subprocess.run(
            [sys.executable, "-B", str(R0_GENERATOR), "--output", str(r0_root)], capture_output=True, cwd=str(ROOT)
        )
        if completed.returncode != 0:
            print(completed.stderr.decode("utf-8", "replace"), file=sys.stderr)
            return 1
        r0_block = [r1_vs_r0(rel, sheet, r0_root, baseline) for rel, (_doc, _ver, sheet) in TARGETS.items()]

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
        "new_column_date_cells_written": sum(pair["new_column_date_cells_written"] for pair in pairs),
        "new_column_sentinel_cells": sum(pair["new_column_sentinel_cells"] for pair in pairs),
        "new_column_blank_cells": sum(pair["new_column_blank_cells"] for pair in pairs),
        "new_column_dates_mismatched": sum(pair["new_column_dates_mismatched"] for pair in pairs),
        "sentinel_mismatches": sum(len(pair["sentinel_mismatches"]) for pair in pairs),
        "new_column_extra_cells": sum(len(pair["new_column_extra_cells"]) for pair in pairs),
        "merged_into_new_columns": sum(len(entry["merged_after_original_columns"]) for pair in pairs for entry in pair["sheets"]),
        "max_column_increase_all_two": all(
            entry["max_column_v3"] - entry["max_column_v2"] == (2 if entry["is_target"] else 0)
            for pair in pairs for entry in pair["sheets"]
        ),
        "r1_vs_r0_diff_cells_total": sum(item.get("diff_count", 0) for item in r0_block),
        "r1_vs_r0_sentinel_added": sum(item.get("sentinel_added", 0) for item in r0_block),
        "r1_vs_r0_sentinel_removed": sum(item.get("sentinel_removed", 0) for item in r0_block),
        "r1_vs_r0_from_column_diffs": sum(item.get("from_column_diffs", 0) for item in r0_block),
        "r1_vs_r0_other_diffs": sum(item.get("other_diffs", 0) for item in r0_block),
        "r0_reconstruction_matches_baseline_all": all(item.get("r0_reconstruction_matches_baseline") for item in r0_block),
    }
    checks = {
        "projection_identical": totals["projection_cells_differing"] == 0,
        "no_existing_cell_modified": totals["existing_cells_modified"] == 0,
        "headers_verbatim": totals["header_ok_all"],
        "sheet_names_and_order": totals["sheet_names_equal_all"],
        "sheet_visibility": totals["sheet_states_equal_all"],
        "dates_match_l1": totals["new_column_dates_mismatched"] == 0,
        "sentinel_cells_match_l1_null_exactly": totals["sentinel_mismatches"] == 0 and totals["new_column_sentinel_cells"] == 11,
        "no_blank_effective_to_left": totals["new_column_blank_cells"] == 0,
        "all_new_data_cells_are_text": totals["new_column_date_cells_written"] == 67
        and totals["new_column_sentinel_cells"] == 11
        and totals["new_column_date_cells_written"] + totals["new_column_sentinel_cells"] == totals["new_column_cells_expected"],
        "no_extra_cells_in_new_columns": totals["new_column_extra_cells"] == 0,
        "no_merged_cells_in_new_columns": totals["merged_into_new_columns"] == 0,
        "two_columns_added_per_target_sheet": totals["max_column_increase_all_two"],
        "new_cell_slots_expect_78_data": totals["new_column_cells_expected"] == 78,
        "total_new_cell_slots_expect_90": totals["new_column_cells_expected"] + 2 * totals["target_sheets"] == 90,
        "unchanged_files_byte_identical_6": unchanged["unchanged_byte_identical"] == 6 and unchanged["expected_unchanged"] == 6,
        "changed_files_all_sha_differ": unchanged["changed_files_sha_differs"] == 6,
        "r0_reconstruction_verified_against_baseline": totals["r0_reconstruction_matches_baseline_all"],
        "r1_vs_r0_only_sentinel_added": totals["r1_vs_r0_sentinel_added"] == 11
        and totals["r1_vs_r0_sentinel_removed"] == 0
        and totals["r1_vs_r0_other_diffs"] == 0
        and totals["r1_vs_r0_diff_cells_total"] == 11,
        "r1_vs_r0_from_column_unchanged": totals["r1_vs_r0_from_column_diffs"] == 0,
    }
    payload = {
        "schema_version": "p2h2v3-cell-diff-r1/v0.1",
        "phase": "verify-cells-r1",
        "method": "A 原列投影（v3 裁回 v2 列/行后逐格比 (value, data_type) + 样式签名）；B 哨兵两分支审计；C R1 vs R0 重放逐格差",
        "sentinel": {"literal": SENTINEL, "maps_to": "L1 effective_to = null (not_asserted)"},
        "v2_root": "fixtures/acceptance",
        "v3_root": "fixtures/acceptance-h2v3",
        "r0_replay": {
            "generator": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-corpus/evidence/01-build-corpus.py（只读重放）",
            "why": "R0 交付件已被本轮原地覆盖，故用上一轮生成器重放；重放结果用 00r1-baseline.json 记录的 R0 交付 SHA256 交叉校验",
        },
        "l1": {"path": "docs/evaluation/p2-source-lifecycle-v1.json", "sha256": sha256_file(L1_PATH)},
        "totals": totals,
        "checks": checks,
        "unchanged_files": unchanged,
        "result": "CELL_IDENTICAL_EXCEPT_TWO_NEW_COLUMNS_AND_SENTINEL" if all(checks.values()) else "CELL_DIFF_FOUND",
        "pairs": pairs,
        "r1_vs_r0": r0_block,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"totals": totals, "checks": checks, "result": payload["result"]}, ensure_ascii=False, indent=1))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
