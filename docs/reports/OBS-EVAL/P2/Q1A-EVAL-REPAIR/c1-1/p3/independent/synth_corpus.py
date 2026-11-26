"""C1-P3 独立验收：合成语料生成（不读任何真实 H2 / 私有语料）。

三份**自造**文档，覆盖三种运行期形态：

- ``synth_stock.xlsx``：表头 ``编号 | 物品名称 | 门店 | 数量``（编号是产品识别的 id 表头），
  sheet=独立验收仓储，row=2/3/4，记录键 W01/W02/W03 → 期望 ``entity_key=item|id:W01``。
- ``synth_loose.xlsx``：表头 ``物品编号 | 物品名称 | 门店``（无产品识别的 id 表头），
  row=2 → 期望运行期 ``entity_key`` 回退成含 ``doc:<uuid>|unit:<uuid>`` 的复合键。
- ``synth_flow.docx``：三段流程文本（无表格）→ 段落级、无实体行。
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from openpyxl import Workbook

STOCK_SHEET = "独立验收仓储"
STOCK_ROWS = (
    (2, "W01", "折叠桌", "城北店", 12),
    (3, "W02", "折叠椅", "城南店", 7),
    (4, "W03", "遮阳棚", "城北店", 3),
)
LOOSE_SHEET = "无编号台账"
LOOSE_ROWS = ((2, "B-77", "折叠凳", "城北店"),)
DOCX_TITLE = "独立验收入库流程"
DOCX_PARAGRAPHS = (
    "第一步：收货登记，核对运单与实物数量。",
    "第二步：外观质检，记录破损情况。",
    "第三步：分区上架，更新库存记录。",
)


def build(root: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    stock = root / "synth_stock.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = STOCK_SHEET
    sheet.append(("编号", "物品名称", "门店", "数量"))
    for _row, key, name, store, count in STOCK_ROWS:
        sheet.append((key, name, store, count))
    workbook.save(stock)

    loose = root / "synth_loose.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = LOOSE_SHEET
    sheet.append(("物品编号", "物品名称", "门店"))
    for _row, key, name, store in LOOSE_ROWS:
        sheet.append((key, name, store))
    workbook.save(loose)

    flow = root / "synth_flow.docx"
    document = Document()
    document.add_heading(DOCX_TITLE, level=1)
    for text in DOCX_PARAGRAPHS:
        document.add_paragraph(text)
    document.save(flow)
    return {
        "stock": stock,
        "loose": loose,
        "flow": flow,
        "stock_sheet": STOCK_SHEET,
        "stock_rows": [{"row": row, "record_key": key} for row, key, *_ in STOCK_ROWS],
        "loose_sheet": LOOSE_SHEET,
        "loose_rows": [{"row": row, "record_key": key} for row, key, *_ in LOOSE_ROWS],
    }
