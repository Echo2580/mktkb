"""v3 语料返工 R1：产品缺陷 ``EXCEL-HEADER-EMPTY-COLUMN`` 的**最小复现**（只读产品代码，不改）。

目的：给 ``product-defects-found.md`` 一条可执行、可复核、**不含任何题面/标签/答案值**的复现件。
做法：用 openpyxl 现场造两个 4 列 3 行的小 xlsx（合成数据 X01/X02），只差 ``失效日期`` 是否为哨兵：

    文件 A（缺陷形态）：``失效日期`` 整列为空
    文件 B（绕开形态）：``失效日期`` 写哨兵 ``未声明``

然后各跑一次**真实** ``mktkb.ingestion.parsers.parse_document``，比较
``report.sheets[0].header_row``、首个 unit 的 ``fields`` 键、以及冻结分类器的 ``_effective_range``。
并把 ``_find_header_index`` 的打分过程逐行重算出来（公式抄自 ``excel.py:112-130``），
让「为什么表头会输」看得见。

零真实调用；临时文件在系统 temp 下，跑完即删。
用法：``.venv\\Scripts\\python.exe 11r1-defect-repro.py``
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[7]
OUT = HERE / "11r1-defect-repro.json"

sys.path.insert(0, str(ROOT / "backend/src"))

from mktkb.evaluation import p2_hard_evidence as he  # noqa: E402
from mktkb.ingestion.parsers import ParseServices, parse_document  # noqa: E402

SENTINEL = "未声明"
SHEET = "示例表"
HEADERS = ("标识", "门店", "物品", "失效日期")
ROWS = (
    ("X01", "示例门店甲", "示例物品一", None),
    ("X02", "示例门店乙", "示例物品二", None),
)
FROM_VALUE = "2026-01-01"


def build(path: Path, *, sentinel: bool) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = SHEET
    for col, header in enumerate(HEADERS, start=1):
        sheet.cell(row=1, column=col, value=header)
    sheet.cell(row=1, column=1)  # 标识
    for index, row in enumerate(ROWS, start=2):
        sheet.cell(row=index, column=1, value=row[0])
        sheet.cell(row=index, column=2, value=row[1])
        sheet.cell(row=index, column=3, value=row[2])
        sheet.cell(row=index, column=4, value=SENTINEL if sentinel else None)
    # 另加一列"生效日期"，让 _effective_range 有 from；放在第 5 列不影响表头打分的最小性
    sheet.cell(row=1, column=5, value="生效日期")
    for index in range(2, 2 + len(ROWS)):
        sheet.cell(row=index, column=5, value=FROM_VALUE)
    workbook.save(path)


def score_table(path: Path) -> list[dict]:
    """逐行重算 ``_find_header_index`` 的打分（公式抄自 excel.py:112-130），只作解释用。"""
    workbook = openpyxl.load_workbook(path)
    sheet = workbook[SHEET]
    rows = []
    for row in range(1, sheet.max_row + 1):
        values = [sheet.cell(row=row, column=col).value for col in range(1, sheet.max_column + 1)]
        nonempty = [value for value in values if value not in (None, "")]
        occupied = len(nonempty)
        rows.append({"row": row, "nonempty": len(nonempty), "occupied": occupied, "all_strings": all(isinstance(v, str) for v in nonempty)})
    for index, item in enumerate(rows):
        if item["nonempty"] < 2:
            item["score"] = None
            item["skipped"] = "len(nonempty)<2"
            continue
        next_bonus = any(rows[j]["occupied"] >= item["nonempty"] for j in range(index + 1, min(index + 3, len(rows))))
        item["next_has_same_width"] = next_bonus
        item["score"] = (3 if item["all_strings"] else 0) + (2 if next_bonus else 0) + (1 if item["nonempty"] >= 3 else 0)
    return rows


def probe(path: Path) -> dict:
    services = ParseServices()
    units = list(parse_document(path, "xlsx", services))
    report = services.report
    sheet_report = (report.get("sheets") or [{}])[0]
    first = units[0] if units else None
    fields = dict(first.fields) if first is not None else {}
    return {
        "parser_header_row": sheet_report.get("header_row"),
        "ingested": sheet_report.get("ingested"),
        "units": len(units),
        "first_unit_fields_keys": sorted(fields),
        "first_unit_has_id_header": any(key in ("标识", "编号", "id", "ID") for key in fields),
        "first_unit_effective_to": fields.get("失效日期"),
        "first_unit_effective_range": list(he._effective_range({"raw_fields": fields})),
        "first_unit_text": first.text if first is not None else None,
        "score_table": score_table(path),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    with tempfile.TemporaryDirectory() as workdir:
        defective = Path(workdir) / "defect.xlsx"
        bypassed = Path(workdir) / "bypassed.xlsx"
        build(defective, sentinel=False)
        build(bypassed, sentinel=True)
        result = {
            "defective": {"file": "defect.xlsx", "sha256_of_generated": sha256(defective), **probe(defective)},
            "bypassed": {"file": "bypassed.xlsx", "sha256_of_generated": sha256(bypassed), **probe(bypassed)},
        }

    checks = {
        "defect_reproduced_header_lost": result["defective"]["parser_header_row"] == 2,
        "defect_reproduced_no_id_header": result["defective"]["first_unit_has_id_header"] is False,
        "defect_reproduced_no_effective_to": result["defective"]["first_unit_effective_to"] is None,
        "defect_reproduced_range_degraded": result["defective"]["first_unit_effective_range"] == ["none", None, None],
        "bypass_restores_header": result["bypassed"]["parser_header_row"] == 1,
        "bypass_restores_id_header": result["bypassed"]["first_unit_has_id_header"] is True,
        "bypass_keeps_sentinel": result["bypassed"]["first_unit_effective_to"] == SENTINEL,
        "bypass_keeps_range_semantics": result["bypassed"]["first_unit_effective_range"] == ["range", FROM_VALUE, None],
    }
    payload = {
        "schema_version": "p2h2v3-defect-repro/v0.1",
        "phase": "product-defect-repro",
        "defect_id": "EXCEL-HEADER-EMPTY-COLUMN",
        "product_file_read_only": {
            "path": "backend/src/mktkb/ingestion/parsers/excel.py",
            "sha256": sha256(ROOT / "backend/src/mktkb/ingestion/parsers/excel.py"),
            "region": "112-130 _find_header_index（next_has_same_width 用表头行非空数作阈值）",
        },
        "minimal_shape": {
            "sheet": SHEET,
            "columns": list(HEADERS) + ["生效日期"],
            "header_rows": 1,
            "data_rows": len(ROWS),
            "condition": "任一张表：某一列的**所有数据格**为空，且该列在表头行有值 ⇒ 表头行非空数 > 数据行占用数 ⇒ 数据行反超表头",
            "data_is_synthetic": True,
            "contains_question_or_answer_values": False,
        },
        "result": result,
        "checks": checks,
        "verdict": "REPRODUCED" if all(checks.values()) else "NOT_REPRODUCED",
        "note": "本脚本只读产品代码、只在临时目录造合成 xlsx；不改产品代码、不写任何题面/标签/答案值。",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"checks": checks, "verdict": payload["verdict"], "defective": {k: result["defective"][k] for k in ("parser_header_row", "units", "first_unit_fields_keys", "first_unit_effective_range")}, "bypassed": {k: result["bypassed"][k] for k in ("parser_header_row", "units", "first_unit_fields_keys", "first_unit_effective_range")}}, ensure_ascii=False, indent=1))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
