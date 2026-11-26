"""v3 残余缺陷定位：xlsx 表头启发式 vs 「失效日期留空」的冲突（V05 / V06）。

已观测事实（04-keyspace-proof.json）：
- V05（D01 v4）/ V06（D02 v2）的 ``失效日期`` 全列为空（L1 里 ``effective_to = null``），
  导致真实解析器 ``ingestion/parsers/excel.py:_find_header_index`` 把**数据行**当表头；
- 其余 4 个 xlsx（D01/V03/V04/D02）两列都有值，表头行与数据行占用数相同 ⇒ 表头正确。

本脚本做三件事（只读 + 纯本地；不改语料、不改产品代码）：
1. 复算启发式分数，逐行给出 V05/V06 为什么选中第 8/5 行（而不是第 7/4 行）；
2. 证明该错选使 unit 失去 ``标识`` 字段 ⇒ 没有 id 型 entity_key（无法被 target 对齐）；
3. **模拟**另一种写法（``失效日期`` 写非日期占位文本，让该列非空）并证明：
   表头恢复、id 键恢复，且冻结分类器 ``_effective_range`` 的返回值与留空**完全一样**
   （``("range", from, None)`` ⇒ 右侧 not_asserted 被跳过）。
   该写法**违反规格 §1.4 的「留空」字面要求**，故本脚本只作决策依据，不落盘。

用法：``.venv\\Scripts\\python.exe 08-header-detection-finding.py``
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
HERE = Path(__file__).resolve().parent
OUT = HERE / "08-header-detection-finding.json"
V3_ROOT = ROOT / "fixtures/acceptance-h2v3"
L1_PATH = ROOT / "docs/evaluation/p2-source-lifecycle-v1.json"

sys.path.insert(0, str(ROOT / "backend/src"))

import openpyxl  # noqa: E402

from mktkb.evaluation.p2_hard_evidence import _effective_range  # noqa: E402
from mktkb.ingestion.parsers import ParseServices, parse_document  # noqa: E402
from mktkb.retrieval.index import ID_HEADERS, analyze_fields  # noqa: E402

TARGETS = {
    "V03": ("variants/V03_物品位置表_历史V1.xlsx", "物品位置"),
    "D01": ("normal/D01_物品位置表.xlsx", "物品位置"),
    "V04": ("variants/V04_物品位置表_新版V3.xlsx", "物品位置"),
    "V05": ("variants/V05_物品位置表_新版V3_移除P01.xlsx", "物品位置"),
    "D02": ("normal/D02_合作店家信息.xlsx", "店家信息"),
    "V06": ("variants/V06_合作店家信息_新电话.xlsx", "店家信息"),
}
PLACEHOLDER = "未声明"  # 只用于模拟，不写入语料


def read_rows(path: Path, sheet_name: str) -> list[tuple[int, list]]:
    workbook = openpyxl.load_workbook(path)
    sheet = workbook[sheet_name]
    rows = []
    for row in range(1, sheet.max_row + 1):
        rows.append((row, [sheet.cell(row=row, column=col).value for col in range(1, sheet.max_column + 1)]))
    return rows


def blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def scores(rows: list[tuple[int, list]]) -> list[dict]:
    """复刻 ``excel.py:112-130`` 的评分公式，逐行给出证据。"""
    out = []
    for index, (row_number, values) in enumerate(rows):
        nonempty = [value for value in values if not blank(value)]
        if len(nonempty) < 2:
            out.append({"row": row_number, "nonempty": len(nonempty), "skipped": "len<2"})
            continue
        all_strings = all(isinstance(value, str) for value in nonempty)
        next_has_same_width = False
        for _n, next_values in rows[index + 1 : index + 3]:
            if sum(1 for value in next_values if not blank(value)) >= len(nonempty):
                next_has_same_width = True
                break
        score = (3 if all_strings else 0) + (2 if next_has_same_width else 0) + (1 if len(nonempty) >= 3 else 0)
        out.append({"row": row_number, "nonempty": len(nonempty), "all_strings": all_strings,
                    "next_has_same_width": next_has_same_width, "score": score})
    return out


def parse_sheet(path: Path, sheet_name: str) -> dict:
    services = ParseServices()
    units = list(parse_document(path, "xlsx", services))
    header = next((item.get("header_row") for item in services.report.get("sheets", []) if item.get("name") == sheet_name), None)
    ids = []
    ranges = []
    for unit in units:
        fields = dict(unit.fields)
        id_name = next((name for name in fields if name in ID_HEADERS), None)
        id_value = "" if id_name is None else str(fields.get(id_name) or "").strip()
        if id_value:
            ids.append(id_value)
        entity = analyze_fields(fields)
        if unit.sheet == sheet_name:
            ranges.append({"unit_key": unit.unit_key, "effective_range": list(_effective_range({"raw_fields": fields}))})
    return {"header_row": header, "id_values": sorted(set(ids)), "units": len(units), "effective_ranges": ranges}


def main() -> int:
    findings = {}
    for source_id, (rel, sheet_name) in TARGETS.items():
        path = V3_ROOT / rel
        row_scores = scores(read_rows(path, sheet_name))
        parsed = parse_sheet(path, sheet_name)
        best = max((item for item in row_scores if "score" in item), key=lambda item: item["score"])
        findings[source_id] = {
            "path": rel,
            "sheet": sheet_name,
            "parser_header_row": parsed["header_row"],
            "expected_header_row": 7 if sheet_name == "物品位置" else 4,
            "id_values_detected": parsed["id_values"],
            "units": parsed["units"],
            "top_scoring_row": {"row": best["row"], "score": best["score"], "nonempty": best["nonempty"],
                                "next_has_same_width": best["next_has_same_width"]},
            "row_scores": row_scores,
            "blank_effective_to_rows": sum(1 for value in read_rows(path, sheet_name)[1:] if False) or None,
            "effective_ranges_sample": parsed["effective_ranges"][:2],
        }

    # ---- 模拟：把空的 失效日期 填成非日期占位文本（仅临时副本，不落盘到语料） ----
    simulation = {}
    with tempfile.TemporaryDirectory() as tmp:
        for source_id in ("V05", "V06"):
            rel, sheet_name = TARGETS[source_id]
            tmp_path = Path(tmp) / Path(rel).name
            shutil.copyfile(V3_ROOT / rel, tmp_path)
            workbook = openpyxl.load_workbook(tmp_path)
            sheet = workbook[sheet_name]
            header_row = findings[source_id]["expected_header_row"]
            filled = 0
            for row in range(header_row + 1, sheet.max_row + 1):
                if sheet.cell(row=row, column=1).value in (None, ""):
                    continue
                target = sheet.cell(row=row, column=sheet.max_column)
                if target.value in (None, ""):
                    target.value = PLACEHOLDER
                    filled += 1
            workbook.save(tmp_path)
            parsed = parse_sheet(tmp_path, sheet_name)
            simulation[source_id] = {
                "cells_filled": filled,
                "parser_header_row": parsed["header_row"],
                "id_values_detected": parsed["id_values"],
                "effective_ranges_sample": parsed["effective_ranges"][:2],
            }

    payload = {
        "schema_version": "p2h2v3-header-detection-finding/v0.1",
        "phase": "residual-finding",
        "finding": "V05/V06 的 失效日期 全列为空 ⇒ 表头行占用数(7/8) > 数据行占用数(6/7) ⇒ _find_header_index 选中数据行",
        "root_cause_code": [
            "backend/src/mktkb/ingestion/parsers/excel.py:112-130 _find_header_index（next_has_same_width 用表头行非空数作阈值）",
            "backend/src/mktkb/ingestion/parsers/excel.py:248-283 表头行被选中后才产出 header_names/fields",
        ],
        "impact": {
            "sources_affected": ["V05", "V06"],
            "runs_affected": [2, 3],
            "declared_targets_unalignable": 7,
            "cases_affected": ["C09", "C10", "C15", "C20", "C29", "C30"],
        },
        "alternative_shape_simulation": {
            "description": "把空 失效日期 填成非日期文本（模拟值不写入语料），验证是否恢复表头识别且语义不变",
            "placeholder": PLACEHOLDER,
            "spec_conflict": "规格 §1.4 明确要求 null 时留空；占位文本属偏离，需主人/经理裁定",
            "results": simulation,
        },
        "classifier_semantics": {
            "blank_to_side": "from 可解析 + to 空 ⇒ _collect_dates(to)=[] ⇒ _effective_range 返回 ('range', from, None) ⇒ 右侧跳过（not_asserted）",
            "placeholder_to_side": "占位文本不可解析 ⇒ _collect_dates(to)=[] ⇒ 同上，返回值与留空完全一致（p2_hard_evidence.py:1452-1474, 1481-1501）",
        },
        "findings": findings,
        "recommended_fix_owner": "经理/主人裁定：产品侧改表头启发式（首选，需独立验收）或本规格改 §1.4（fixture 侧偏离，需书面裁定）",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "affected": {k: {"parser_header_row": v["parser_header_row"], "expected_header_row": v["expected_header_row"],
                         "id_values_detected": v["id_values_detected"]} for k, v in findings.items()},
        "simulation": simulation,
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
