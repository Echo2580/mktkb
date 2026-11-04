#!/usr/bin/env python
r"""T01-C2 模拟语料生成器（B0 冻结基线）。

生成：10 份正常模拟资料（D01～D10）、隔离变体（冲突/历史版本/新版本/移除记录/新电话/U06 剩余来源）、
异常样本（损坏、加密、模糊、无文字、不可恢复表格、混合 PDF、失败页）、单文件边界样本，
以及 manifest.json（文件哈希与 Locator）、questions.json（64 条题目/场景）、README.md、字体许可副本。

约束：
- 只读复用 docs/evidence/T01/C1-R1/derived-fonts 的静态 Regular/Medium 字体，不重新实例化；
- 不访问网络、不安装依赖、不调用 OCR/模型；
- 固定 Office ZIP 时间、PDF 时间/ID、随机源，保证两次生成字节一致；
- 不覆盖已存在的非空输出目录（除非 --force 明确用于刷新本工具自己的候选目录）。

用法：
    .\.venv\Scripts\python.exe -B tools\build_demo_corpus.py --output <DIR> [--font-dir DIR] [--boundary-dir DIR]
接口：
    build_corpus(output_dir: Path, ...) -> CorpusManifest
    load_manifest(path: Path) -> CorpusManifest
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FONT_DIR = ROOT / "docs" / "evidence" / "T01" / "C1-R1" / "derived-fonts"
OFL_SOURCE = ROOT / "docs" / "evidence" / "T01" / "C1-R1" / "OFL.txt"
FONT_FILES = {
    400: ("NotoSansSCStatic-Regular.ttf", "F2B1C83E95DA726AA0A10FD5B6A9252A15E75AF9FFB3B25A2930D09860E39669"),
    500: ("NotoSansSCStatic-Medium.ttf", "EFF5ACBE28D97768E393285F71A7B9672747ABAAA5E2A99330CDF57FE612555F"),
}
FIXED_DOC_TIME = datetime(2026, 10, 1, 9, 0, 0)
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
MARK = "模拟数据"
BUSINESS_DATE = "2026-10-27"


# --------------------------------------------------------------------- helpers


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_zip(path: Path) -> None:
    """重写 Office 容器：固定条目时间与属性，保证字节可复现。

    openpyxl/python-docx 在保存时会把 docProps/core.xml 的 modified 改成当前时间，
    因此这里统一把 created/modified 改回固定时间。
    """
    import re

    with zipfile.ZipFile(path) as source:
        entries = sorted((info.filename, source.read(info.filename)) for info in source.infolist())
    fixed = "2026-10-01T09:00:00Z"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in entries:
            if name == "docProps/core.xml":
                text = data.decode("utf-8")
                text = re.sub(
                    r"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)",
                    lambda match: match.group(1) + fixed + match.group(2),
                    text,
                )
                data = text.encode("utf-8")
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            target.writestr(info, data)
    path.write_bytes(buffer.getvalue())


def register_fonts(font_dir: Path) -> dict[int, str]:
    from reportlab import rl_config
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    rl_config.invariant = 1  # 固定 PDF 时间戳与文档 ID
    names = {}
    for weight, (filename, expected) in FONT_FILES.items():
        path = font_dir / filename
        if not path.is_file():
            raise SystemExit(f"static font missing: {path}")
        actual = sha256_file(path)
        if actual.lower() != expected.lower():
            raise SystemExit(f"static font hash mismatch: {path} {actual}")
        name = f"C2Static-{weight}"
        pdfmetrics.registerFont(TTFont(name, str(path)))
        names[weight] = name
    return names


def pillow_font(font_dir: Path, weight: int, size: int):
    from PIL import ImageFont

    filename, _ = FONT_FILES[weight]
    return ImageFont.truetype(str(font_dir / filename), size)


# --------------------------------------------------------------------- documents


def make_text_pdf(path: Path, title: str, blocks: list[list[str]], font_names: dict[int, str]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics  # noqa: F401  (注册已在 register_fonts 完成)
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(f"{MARK} · {title}")
    pdf.setAuthor("T01-C2")
    pdf.setSubject("模拟部门资料（非真实业务数据）")
    pdf.setCreator("tools/build_demo_corpus.py")
    width, height = A4
    y = height - 64
    pdf.setFont(font_names[500], 15)
    pdf.drawString(50, y, title)
    y -= 18
    pdf.setFont(font_names[400], 9)
    pdf.drawString(50, y, f"{MARK}｜业务更新 {BUSINESS_DATE}｜仅用于入职考核演示")
    y -= 26
    for block in blocks:
        for line in block:
            if y < 60:
                pdf.showPage()
                y = height - 60
            heading = line.startswith("# ")
            pdf.setFont(font_names[500] if heading else font_names[400], 12 if heading else 10)
            pdf.drawString(50, y, line[2:] if heading else line)
            y -= 18 if heading else 15
        y -= 10
    pdf.showPage()
    pdf.save()


def make_scan_pdf(path: Path, pages: list[list[str]], font_dir: Path) -> None:
    """纯图像扫描 PDF：每页整幅图像，无文字层。"""
    from PIL import Image, ImageDraw

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    title_font = pillow_font(font_dir, 500, 38)
    body_font = pillow_font(font_dir, 400, 28)
    width_px, height_px = 1240, 1754
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(f"{MARK} · 扫描件")
    pdf.setAuthor("T01-C2")
    pdf.setCreator("tools/build_demo_corpus.py")
    for index, lines in enumerate(pages, start=1):
        image = Image.new("RGB", (width_px, height_px), "white")
        draw = ImageDraw.Draw(image)
        draw.text((80, 110), lines[0], font=title_font, fill=(0, 0, 0))
        y = 190
        for line in lines[1:]:
            draw.text((80, y), line, font=body_font, fill=(0, 0, 0))
            y += 44
        draw.text((80, height_px - 90), f"{MARK}／第 {index} 页／仅用于解析验证", font=body_font, fill=(80, 80, 80))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        pdf.drawImage(ImageReader(buffer), 0, 0, width=A4[0], height=A4[1])
        pdf.showPage()
    pdf.save()


def make_text_image(path: Path, lines: list[str], font_dir: Path, size=(1200, 640), title_weight=500) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    title_font = pillow_font(font_dir, title_weight, 40)
    body_font = pillow_font(font_dir, 400, 30)
    draw.text((60, 50), lines[0], font=title_font, fill=(0, 0, 0))
    y = 130
    for line in lines[1:]:
        draw.text((60, y), line, font=body_font, fill=(0, 0, 0))
        y += 50
    draw.text((60, size[1] - 60), f"{MARK}／链路验证样张", font=body_font, fill=(90, 90, 90))
    suffix = path.suffix.lower()
    if suffix == ".png":
        image.save(path, format="PNG")
    else:
        image.save(path, format="JPEG", quality=92, subsampling=0, progressive=False)


def make_table_image(path: Path, header: list[str], rows: list[list[str]], font_dir: Path) -> None:
    from PIL import Image, ImageDraw

    width, height = 1240, 620
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    head_font = pillow_font(font_dir, 500, 26)
    cell_font = pillow_font(font_dir, 400, 24)
    note_font = pillow_font(font_dir, 400, 20)
    draw.text((50, 36), "盘点通知（规则表格）", font=head_font, fill=(0, 0, 0))
    draw.text((50, 80), f"{MARK}｜业务更新 {BUSINESS_DATE}", font=note_font, fill=(90, 90, 90))
    left, top = 50, 140
    widths = [230, 250, 330, 330]
    row_height = 70
    x = left
    for index, value in enumerate(header):
        draw.rectangle([x, top, x + widths[index], top + row_height], outline=(0, 0, 0), width=2)
        draw.text((x + 16, top + 20), value, font=head_font, fill=(0, 0, 0))
        x += widths[index]
    for row_index, row in enumerate(rows):
        y = top + row_height * (row_index + 1)
        x = left
        for col, value in enumerate(row):
            draw.rectangle([x, y, x + widths[col], y + row_height], outline=(0, 0, 0), width=2)
            draw.text((x + 16, y + 20), value, font=cell_font, fill=(0, 0, 0))
            x += widths[col]
    draw.text((50, top + row_height * (len(rows) + 1) + 24), "门店/物品/时间/地点逐行对应，供串行检查使用", font=note_font, fill=(90, 90, 90))
    image.save(path, format="JPEG", quality=92, subsampling=0, progressive=False)


def make_xlsx(path: Path, sheets: list[dict]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for index, spec in enumerate(sheets):
        sheet = workbook.create_sheet(spec["name"])
        for row_index, row in enumerate(spec["rows"], start=1):
            for col_index, value in enumerate(row, start=1):
                cell = sheet.cell(row=row_index, column=col_index)
                if isinstance(value, str) and value.startswith("="):
                    cell.value = value
                else:
                    cell.value = value
                if spec.get("text_columns") and col_index in spec["text_columns"]:
                    cell.number_format = "@"
        if spec.get("hidden"):
            sheet.sheet_state = "hidden"
    workbook.properties.creator = "T01-C2"
    workbook.properties.created = FIXED_DOC_TIME
    workbook.properties.modified = FIXED_DOC_TIME
    workbook.properties.title = f"{MARK} 工作簿"
    workbook.save(path)
    normalize_zip(path)


def make_docx(path: Path, title: str, sections: list[tuple[str, list[str]]]) -> None:
    from docx import Document
    from docx.shared import Pt

    document = Document()
    document.core_properties.author = "T01-C2"
    document.core_properties.created = FIXED_DOC_TIME
    document.core_properties.modified = FIXED_DOC_TIME
    document.core_properties.title = f"{MARK} · {title}"
    document.core_properties.revision = 1

    heading = document.add_heading(title, level=0)
    heading.runs[0].font.size = Pt(18)
    note = document.add_paragraph(f"{MARK}｜业务更新 {BUSINESS_DATE}｜仅用于入职考核演示")
    note.runs[0].font.size = Pt(9)
    for section_title, paragraphs in sections:
        document.add_heading(section_title, level=1)
        for text in paragraphs:
            document.add_paragraph(text)
    document.save(path)
    normalize_zip(path)


# --------------------------------------------------------------------- corpus data


POSITIONS = [
    ("P01", "城东店", "宣传海报", "海报", "B区1号货架第二层"),
    ("P02", "城西店", "宣传海报", "海报", "C区2号货架第一层"),
    ("P03", "城东店", "展架", "展示架", "A区2号货架底层"),
    ("P04", "城西店", "展架", "展示架", "B区3号货架中层"),
    ("P05", "城东店", "易拉宝", "", "D区1号柜第二层"),
    ("P06", "城西店", "易拉宝", "", "D区2号柜第二层"),
    ("P07", "城东店", "促销贴纸", "贴纸", "A区4号货架第一层"),
    ("P08", "城西店", "价签卡纸", "价签纸", "C区1号柜第一层"),
]
STORES = [
    ("S01", "城东店", "模拟联系人·陈宁", "010-00000001", "示例市示例路18号（模拟）", "合作中"),
    ("S02", "城西店", "模拟联系人·王平", "010-00000002", "示例市示例路26号（模拟）", "合作中"),
    ("S03", "城北店", "模拟联系人·李禾", "010-00000003", "示例市北街8号（模拟）", "暂停合作"),
    ("S04", "滨河店", "模拟联系人·周安", "010-00000004", "示例市滨河路6号（模拟）", "待签约"),
]
RESERVED_SHEET = "备用物料表"
HIDDEN_SHEET = "旧草稿"

# B0 初始化配方：在同一 D01 逻辑文件上先发布历史 V1（V03），再发布正常 D01 作为业务 V2。
# revision 与产品版本号由实际运行产生，配方只描述有序动作与可核对断言。
B0_INITIALIZATION = {
    "id": "b0_initialization",
    "description": "同一 D01 逻辑文件先导入并发布历史 V1（V03），再导入并发布正常 D01 作为业务 V2；其余正常文件首次导入后发布。",
    "logical_slots": {
        "doc-positions": {"files": ["V03", "D01"], "active_business_version": "V2"},
        "doc-stores": {"files": ["D02"], "active_business_version": "V1"},
    },
    "steps": [
        {"step": 1, "op": "import_document", "file": "V03", "document_slot": "doc-positions", "business_version": "V1"},
        {"step": 2, "op": "process", "file": "V03"},
        {"step": 3, "op": "publish", "file": "V03"},
        {"step": 4, "op": "import_version", "file": "D01", "document_slot": "doc-positions", "business_version": "V2"},
        {"step": 5, "op": "process", "file": "D01"},
        {"step": 6, "op": "publish", "file": "D01"},
        {"step": 7, "op": "import_document", "file": "D02", "document_slot": "doc-stores", "business_version": "V1"},
        {"step": 8, "op": "process", "file": "D02"},
        {"step": 9, "op": "publish", "file": "D02"},
        {"step": 10, "op": "import_document", "file": "D03", "document_slot": "doc-guide", "business_version": "V1"},
        {"step": 11, "op": "process", "file": "D03"},
        {"step": 12, "op": "publish", "file": "D03"},
        {"step": 13, "op": "import_document", "file": "D04", "document_slot": "doc-planning", "business_version": "V1"},
        {"step": 14, "op": "process", "file": "D04"},
        {"step": 15, "op": "publish", "file": "D04"},
        {"step": 16, "op": "import_document", "file": "D05", "document_slot": "doc-usage", "business_version": "V1"},
        {"step": 17, "op": "process", "file": "D05"},
        {"step": 18, "op": "publish", "file": "D05"},
        {"step": 19, "op": "import_document", "file": "D06", "document_slot": "doc-store-ops", "business_version": "V1"},
        {"step": 20, "op": "process", "file": "D06"},
        {"step": 21, "op": "publish", "file": "D06"},
        {"step": 22, "op": "import_document", "file": "D07", "document_slot": "doc-application-scan", "business_version": "V1"},
        {"step": 23, "op": "process", "file": "D07"},
        {"step": 24, "op": "publish", "file": "D07"},
        {"step": 25, "op": "import_document", "file": "D08", "document_slot": "doc-safety-scan", "business_version": "V1"},
        {"step": 26, "op": "process", "file": "D08"},
        {"step": 27, "op": "publish", "file": "D08"},
        {"step": 28, "op": "import_document", "file": "D09", "document_slot": "doc-notice-image", "business_version": "V1"},
        {"step": 29, "op": "process", "file": "D09"},
        {"step": 30, "op": "publish", "file": "D09"},
        {"step": 31, "op": "import_document", "file": "D10", "document_slot": "doc-stocktake-image", "business_version": "V1"},
        {"step": 32, "op": "process", "file": "D10"},
        {"step": 33, "op": "publish", "file": "D10"},
    ],
    "assertions": [
        "发布 V03 后，D01 逻辑槽的 P01 位置为 A区3号货架第二层（业务 V1）",
        "发布 D01 后，P01 为 B区1号货架第二层，且为当前有效业务 V2",
        "其余正常文件各自首次导入即业务 V1，无历史版本",
        "应用 revision 由实际运行读取，不在本配方中预设",
    ],
    "forbidden": [
        "不得用 V04 建立 B0（V04 是 D 区新位置，仅用于 U01/U02/U07/U08）",
        "不得把 D01 首次导入直接命名为业务 V2",
    ],
}


def positions_rows(records=POSITIONS, header_row: int = 7) -> list[list]:
    rows: list[list] = [["物品位置表（模拟数据）"], ["部门：市场部"], ["业务更新：2026-10-27"], [], ["说明：位置值以现场核对为准"], []]
    rows.append(["标识", "门店", "物品", "别名", "位置"])
    for code, store, item, alias, place in records:
        rows.append([code, store, item, alias, place])
    return rows


def make_d01(path: Path, records=POSITIONS) -> None:
    make_xlsx(
        path,
        [
            {
                "name": "物品位置",
                "rows": positions_rows(records),
            },
            {
                "name": RESERVED_SHEET,
                "rows": [["备用物料（模拟）"], [], ["门店", "物品", "位置"], ["城东店", "宣传单", "A区5号柜"]],
            },
            {
                "name": HIDDEN_SHEET,
                "rows": [["旧草稿（不得入库）"], ["门店", "物品", "位置"], ["城东店", "宣传海报", "A区3号货架第二层"]],
                "hidden": True,
            },
        ],
    )


def make_d02(path: Path, stores=STORES) -> None:
    rows = [["合作店家信息（模拟数据）"], ["业务更新：2026-10-27"], [], ["标识", "店家", "联系人", "电话", "地址", "合作状态"]]
    for row in stores:
        rows.append(list(row))
    make_xlsx(path, [{"name": "店家信息", "rows": rows, "text_columns": {1, 4}}])


def build_normal(corpus: Path, font_names: dict[int, str], font_dir: Path) -> list[dict]:
    normal = corpus / "normal"
    normal.mkdir(parents=True, exist_ok=True)
    created: list[dict] = []

    d01 = normal / "D01_物品位置表.xlsx"
    make_d01(d01)
    d02 = normal / "D02_合作店家信息.xlsx"
    make_d02(d02)

    d03 = normal / "D03_市场部工作指南.docx"
    make_docx(
        d03,
        "市场部工作指南",
        [
            (
                "2.3 物料领用与登记",
                [
                    "门店领取宣传物料前，须在《物料领用登记表》中填写活动名称、门店、用途与数量。",
                    "物料领用需填写登记表并经门店负责人确认，领取时登记实际领取数量。",
                    "归还时须核对数量与状态，并在登记表中登记归还日期。",
                ],
            ),
            (
                "2.4 物料归还",
                ["归还后由市场部行政复核并留存记录；数量与状态不符时须当日报备。"],
            ),
        ],
    )

    d04 = normal / "D04_活动策划流程.docx"
    make_docx(
        d04,
        "活动策划流程",
        [
            (
                "3.1 活动申请",
                [
                    "活动申请至少提前 3 个工作日提交，不得以 3 个自然日替代。",
                    "活动方案需包含目标、时间地点、预算与物料清单四部分。",
                ],
            ),
            ("3.2 方案复核", ["市场部负责人在收到方案后 2 个工作日内完成复核。"]),
        ],
    )

    d05 = normal / "D05_物料领用规范.pdf"
    make_text_pdf(
        d05,
        "物料领用规范",
        [
            ["# 一、领用范围", "本规范适用于市场部各门店的宣传活动物料。"],
            ["# 二、跨店调拨", "跨店调拨物料须经两店负责人确认后方可执行。"],
            ["# 三、归还核对", "物料归还时须核对数量与完好情况，异常当场记录。"],
        ],
        font_names,
    )

    d06 = normal / "D06_店家资料维护说明.pdf"
    make_text_pdf(
        d06,
        "店家资料维护说明",
        [
            ["# 一、变更报告", "发现店家信息变化后，应当日联系资料管理员核实。"],
            ["# 二、变更记录", "店家资料修改时须记录业务更新时间与修改原因。"],
        ],
        font_names,
    )

    d07 = normal / "D07_活动申请扫描件.pdf"
    d07_pages = []
    for page in range(1, 9):
        if page == 3:
            d07_pages.append(
                [
                    "活动申请表",
                    "申请部门：市场部",
                    "活动名称：秋季门店联合推广",
                    "活动日期：2026-11-05",
                    "预算：人民币 8,000 元（模拟）",
                    "物料清单：宣传海报、易拉宝、促销贴纸",
                ]
            )
        else:
            d07_pages.append(
                [
                    f"活动申请表（第 {page} 页）",
                    "申请部门：市场部",
                    f"附件说明：本页为扫描页示例 {page}，内容为模拟文字。",
                    "审批意见：按流程复核。",
                ]
            )
    make_scan_pdf(d07, d07_pages, font_dir)

    d08 = normal / "D08_仓库安全须知扫描件.pdf"
    make_scan_pdf(
        d08,
        [
            ["仓库安全须知（第 1 页）", "进入仓库须佩戴工牌，禁止吸烟。", "物料摆放不得超高、倾斜。"],
            ["仓库安全须知（第 2 页）", "物料通道保持畅通，不得堆放杂物。", "发现异常须向仓库负责人报告。"],
        ],
        font_dir,
    )

    d09 = normal / "D09_物料领用通知.png"
    make_text_image(
        d09,
        ["物料领用通知", "领取活动物料前，请填写领用登记表并由负责人确认。", "登记表由市场部行政留存。"],
        font_dir,
        size=(1200, 700),
    )

    d10 = normal / "D10_盘点通知.jpg"
    make_table_image(
        d10,
        ["门店", "物品", "盘点时间", "盘点地点"],
        [
            ["城东店", "宣传海报", "2026-10-30 16:00", "城东店物料区"],
            ["城西店", "宣传海报", "2026-10-31 15:30", "城西店二层仓库"],
        ],
        font_dir,
    )

    for entry in (
        (d01, "D01", "xlsx", "V2"),
        (d02, "D02", "xlsx", "V1"),
        (d03, "D03", "docx", "V1"),
        (d04, "D04", "docx", "V1"),
        (d05, "D05", "pdf-text", "V1"),
        (d06, "D06", "pdf-text", "V1"),
        (d07, "D07", "pdf-scan", "V1"),
        (d08, "D08", "pdf-scan", "V1"),
        (d09, "D09", "png", "V1"),
        (d10, "D10", "jpg", "V1"),
    ):
        path, file_id, kind, version = entry
        created.append(
            {
                "id": file_id,
                "path": f"normal/{path.name}",
                "kind": kind,
                "business_version": version,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return created


def build_variants(corpus: Path, font_names: dict[int, str], font_dir: Path) -> list[dict]:
    variants = corpus / "variants"
    variants.mkdir(parents=True, exist_ok=True)
    created: list[dict] = []

    def add(path: Path, file_id: str, kind: str, version: str, purpose: str, scenario: str | None) -> None:
        created.append(
            {
                "id": file_id,
                "path": f"variants/{path.name}",
                "kind": kind,
                "business_version": version,
                "purpose": purpose,
                "scenario": scenario,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    # C05：与 D01 冲突的有效通知（P01 位置 D区暂存柜）
    p = variants / "V01_临时物料位置通知.pdf"
    make_text_pdf(
        p,
        "临时物料位置通知",
        [["# 通知", "因 B 区货架盘点，城东店宣传海报临时调整至 D区暂存柜。", "暂存期间取用须联系门店负责人登记。"]],
        font_names,
    )
    add(p, "V01", "pdf-text", "V1", "C05 位置冲突的另一有效来源", "C05")

    # C06：与 D02 冲突的有效店家通知（S01 电话不同）
    p = variants / "V02_店家联系方式变更通知.pdf"
    make_text_pdf(
        p,
        "店家联系方式变更通知",
        [["# 变更通知", "城东店联系电话调整为 010-00000099（模拟）。", "本次变更自业务更新时间起生效。"]],
        font_names,
    )
    add(p, "V02", "pdf-text", "V1", "C06 电话冲突的另一有效来源", "C06")

    # 历史 V1（P01 在 A区3号货架第二层）
    p = variants / "V03_物品位置表_历史V1.xlsx"
    v1_records = [list(row) for row in POSITIONS]
    v1_records[0] = ["P01", "城东店", "宣传海报", "海报", "A区3号货架第二层"]
    make_d01(p, records=v1_records)
    add(p, "V03", "xlsx", "V1", "P01 历史位置（U01/U02 建立历史版本用）", "U01")

    # 新版本 V3（P01 改 D区暂存柜）
    p = variants / "V04_物品位置表_新版V3.xlsx"
    v3_records = [list(row) for row in POSITIONS]
    v3_records[0] = ["P01", "城东店", "宣传海报", "海报", "D区暂存柜"]
    make_d01(p, records=v3_records)
    add(p, "V04", "xlsx", "V3", "P01 新位置（U02 发布后用）", "U02")

    # 新版本 V3 移除 P01 整行
    p = variants / "V05_物品位置表_新版V3_移除P01.xlsx"
    make_d01(p, records=[row for row in POSITIONS if row[0] != "P01"])
    add(p, "V05", "xlsx", "V3", "新版删除 P01 整行（U04）", "U04")

    # S01 新电话
    p = variants / "V06_合作店家信息_新电话.xlsx"
    stores_new = [list(row) for row in STORES]
    stores_new[0][3] = "010-00000088"
    make_d02(p, stores=stores_new)
    add(p, "V06", "xlsx", "V2", "S01 电话变更（U03/U06 恢复基础）", "U03")

    # U06：删除 D01 后仍保留 P01 事实的独立有效来源
    p = variants / "V07_物料位置独立通知.pdf"
    make_text_pdf(
        p,
        "物料位置独立通知",
        [["# 位置通知", "城东店宣传海报存放于 B区1号货架第二层。", "本通知与物品位置表分别维护。"]],
        font_names,
    )
    add(p, "V07", "pdf-text", "V1", "U06 删除 D01 后的剩余有效来源", "U06")

    # 异常样本
    p = variants / "A01_损坏的文档.docx"
    good = corpus / "normal" / "D03_市场部工作指南.docx"
    p.write_bytes(good.read_bytes()[:400])
    add(p, "A01", "docx", "V1", "损坏 docx（截断字节，非合法 ZIP）", "anomaly")

    p = variants / "A02_损坏的表格.xlsx"
    p.write_bytes((corpus / "normal" / "D01_物品位置表.xlsx").read_bytes()[:300])
    add(p, "A02", "xlsx", "V1", "损坏 xlsx（截断字节）", "anomaly")

    p = variants / "A03_加密的规范.pdf"
    make_encrypted_pdf(p, font_names)
    add(p, "A03", "pdf-text", "V1", "真实口令加密 PDF（reportlab StandardEncryption）", "anomaly")

    p = variants / "A04_模糊的照片.png"
    make_blurred_image(p, font_dir)
    add(p, "A04", "png", "V1", "模糊图片（文字不可辨）", "anomaly")

    p = variants / "A05_无文字的照片.png"
    from PIL import Image

    Image.new("RGB", (1200, 800), "white").save(p, format="PNG")
    add(p, "A05", "png", "V1", "无文字图片（纯白）", "anomaly")

    p = variants / "A06_行列不可恢复的表格.jpg"
    make_broken_table(p, font_dir)
    add(p, "A06", "jpg", "V1", "表格行列无法可靠恢复（错位、缺线）", "anomaly")

    # 混合 PDF：文字页 + 扫描页（合法支持路径）
    p = variants / "A07_混合页文档.pdf"
    make_mixed_pdf(p, font_names, font_dir, failed_page=False)
    add(p, "A07", "pdf-mixed", "V1", "混合 PDF：文字页 + 扫描页（支持路径，不含失败页）", "anomaly")

    # 混合 PDF 含失败页（扫描页整页空白，后续以替身模拟识别失败）
    p = variants / "A08_混合页含失败页文档.pdf"
    make_mixed_pdf(p, font_names, font_dir, failed_page=True)
    add(p, "A08", "pdf-mixed", "V1", "混合 PDF 含不可识别失败页（不得整份发布）", "anomaly")

    return created


def make_encrypted_pdf(path: Path, font_names: dict[int, str]) -> None:
    from reportlab.lib import pdfencrypt
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    encrypt = pdfencrypt.StandardEncryption("user-pass", "owner-pass", canPrint=1)
    pdf = canvas.Canvas(str(path), pagesize=A4, encrypt=encrypt)
    pdf.setFont(font_names[400], 12)
    pdf.drawString(50, 780, "加密文档示例（口令 user-pass，仅用于拒绝路径验证）")
    pdf.save()


def make_blurred_image(path: Path, font_dir: Path) -> None:
    from PIL import Image, ImageFilter

    make_text_image(path, ["模糊照片示例", "领取活动物料前，请填写登记表。", "（本图故意模糊，文字不可辨）"], font_dir)
    with Image.open(path) as image:
        image.filter(ImageFilter.GaussianBlur(radius=6)).save(path, format="PNG")


def make_broken_table(path: Path, font_dir: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1240, 700), "white")
    draw = ImageDraw.Draw(image)
    font = pillow_font(font_dir, 400, 24)
    draw.text((50, 30), "表格照片示例（行列不可恢复）", font=font, fill=(0, 0, 0))
    # 错位、缺线、文字跨越边框
    draw.line([(60, 120), (1150, 128)], fill=(0, 0, 0), width=2)
    draw.line([(60, 260), (900, 250)], fill=(0, 0, 0), width=2)
    draw.line([(60, 120), (70, 500)], fill=(0, 0, 0), width=2)
    draw.text((80, 150), "城东店   宣传海报   B区1号货架第二层   2026-10-30", font=font, fill=(0, 0, 0))
    draw.text((300, 200), "城西店 宣传海报 C区2号货架第一层", font=font, fill=(0, 0, 0))
    draw.text((80, 330), "盘点时间与地点信息被裁切，无法确定列关系", font=font, fill=(0, 0, 0))
    image.save(path, format="JPEG", quality=88, subsampling=0, progressive=False)


def make_mixed_pdf(path: Path, font_names: dict[int, str], font_dir: Path, failed_page: bool) -> None:
    from PIL import Image, ImageDraw
    from reportlab.lib import pdfencrypt  # noqa: F401
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(f"{MARK} · 混合页文档")
    pdf.setAuthor("T01-C2")
    pdf.setCreator("tools/build_demo_corpus.py")
    # 第 1 页：文字层
    pdf.setFont(font_names[400], 12)
    pdf.drawString(50, 780, "混合文档第 1 页：文字型页面（可提取）")
    pdf.drawString(50, 756, "本页由文字对象组成，用于验证文字页提取。")
    pdf.showPage()
    # 第 2 页：扫描图像
    width_px, height_px = 1240, 1754
    image = Image.new("RGB", (width_px, height_px), "white")
    if failed_page:
        draw = ImageDraw.Draw(image)
        draw.rectangle([100, 200, 1140, 1500], fill=(238, 238, 238))
    else:
        draw = ImageDraw.Draw(image)
        font = pillow_font(font_dir, 400, 32)
        draw.text((90, 140), "混合文档第 2 页：扫描页", font=font, fill=(0, 0, 0))
        draw.text((90, 220), "活动日期 2026-11-05", font=font, fill=(0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    pdf.drawImage(ImageReader(buffer), 0, 0, width=A4[0], height=A4[1])
    pdf.showPage()
    pdf.save()


# --------------------------------------------------------------------- boundary samples


def make_boundary(boundary: Path, font_names: dict[int, str], font_dir: Path) -> list[dict]:
    """限内/恰好上限/超限样本。20MB 级样本写入临时目录后仅保留计量与哈希。"""
    boundary.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []

    def record(path: Path, file_id: str, kind: str, measure: dict, note: str, kept: bool = True) -> None:
        entries.append(
            {
                "id": file_id,
                "path": f"boundary/{path.name}",
                "kind": kind,
                "measure": measure,
                "note": note,
                "kept": kept,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    # 20MB：恰好上限与超限（1 字节）。体积大，计量与哈希记录后删除，可用同一命令复现
    exact = boundary / "B01_恰好20MB.pdf"
    over = boundary / "B02_超过20MB一字节.pdf"
    for target, path, file_id, note in (
        (20 * 1024 * 1024, exact, "B01", "恰好 20×1024×1024 字节（PDF 尾部合法注释填充，可正常打开与提取）"),
        (20 * 1024 * 1024 + 1, over, "B02", "超出 1 字节（同上填充方式）"),
    ):
        build_padded_pdf(path, font_names, target)
        record(
            path,
            file_id,
            "pdf-text",
            {"bytes": path.stat().st_size, "limit": 20 * 1024 * 1024},
            note + "；为控制仓库体积，计量与哈希记录后删除，复现命令见 C2 报告",
            kept=False,
        )
        path.unlink()

    # 50 页 / 51 页
    for pages, path, file_id in ((50, boundary / "B03_恰好50页.pdf", "B03"), (51, boundary / "B04_超过50页.pdf", "B04")):
        make_page_count_pdf(path, font_names, pages)
        record(path, file_id, "pdf-text", {"pages": pages, "limit": 50}, "PDF 页数边界")

    # 5000 / 5001 行
    for rows, path, file_id in ((5000, boundary / "B05_恰好5000行.xlsx", "B05"), (5001, boundary / "B06_超过5000行.xlsx", "B06")):
        make_rows_xlsx(path, rows)
        record(path, file_id, "xlsx", {"data_rows": rows, "limit": 5000}, "Excel 有效数据行边界（跨可见表合计）")

    # 20,000,000 像素 / 超出
    from PIL import Image

    for size, path, file_id in (((5000, 4000), boundary / "B07_恰好2000万像素.png", "B07"), ((5000, 4001), boundary / "B08_超过2000万像素.png", "B08")):
        Image.new("RGB", size, "white").save(path, format="PNG")
        record(path, file_id, "png", {"pixels": size[0] * size[1], "limit": 20_000_000}, "图片像素边界")

    return entries


def build_padded_pdf(path: Path, font_names: dict[int, str], target_bytes: int) -> None:
    """生成 1 页可读 PDF，再以合法 PDF 注释填充到精确字节数（保留 %%EOF 前）。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f"{MARK} · 大小边界样本")
    pdf.setAuthor("T01-C2")
    pdf.setFont(font_names[400], 12)
    pdf.drawString(50, 780, "大小边界样本：本页文字可正常提取，文件尾部为合法注释填充。")
    pdf.showPage()
    pdf.save()
    data = buffer.getvalue()
    marker = b"%%EOF"
    index = data.rfind(marker)
    head, tail = data[:index], data[index:]
    padding_len = target_bytes - len(data)
    if padding_len < 0:
        raise SystemExit("target size smaller than base PDF")
    padding = b"%" + b"0" * (padding_len - 2) + b"\n"
    path.write_bytes(head + padding + tail)
    assert len(path.read_bytes()) == target_bytes


def build_boundary_files(output_dir: Path, *, font_dir: Path | None = None) -> list[dict]:
    """生成并**保留** 20MB 大小边界样本（B01/B02），供后续上传测试直接取用。

    默认语料生成仍只记录 B01/B02 的计量与哈希后删除；本入口用于需要实际文件时。
    目标目录必须为空（不存在或为空），否则拒绝，避免覆盖其他产物。
    """
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"boundary output directory not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    font_dir = Path(font_dir) if font_dir else DEFAULT_FONT_DIR
    register_fonts(font_dir)
    names = {400: "C2Static-400", 500: "C2Static-500"}

    entries: list[dict] = []
    for target, name, file_id in (
        (20 * 1024 * 1024, "B01_恰好20MB.pdf", "B01"),
        (20 * 1024 * 1024 + 1, "B02_超过20MB一字节.pdf", "B02"),
    ):
        path = output_dir / name
        build_padded_pdf(path, names, target)
        entries.append(
            {
                "id": file_id,
                "path": name,
                "kept": True,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "note": "PDF 尾部合法注释填充；pdfplumber 可提取文字，PDFium 可打开",
            }
        )
    return entries


def make_page_count_pdf(path: Path, font_names: dict[int, str], pages: int) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(f"{MARK} · 页数边界样本")
    pdf.setAuthor("T01-C2")
    for index in range(1, pages + 1):
        pdf.setFont(font_names[400], 12)
        pdf.drawString(50, 780, f"页数边界样本 第 {index}/{pages} 页（模拟数据）")
        pdf.showPage()
    pdf.save()


def make_rows_xlsx(path: Path, rows: int) -> None:
    make_xlsx(
        path,
        [
            {
                "name": "记录",
                "rows": [["标识", "门店", "物品", "位置"]] + [[f"R{index:05d}", "城东店", f"物料{index}", f"A区{index}号柜"] for index in range(1, rows + 1)],
            }
        ],
    )


# --------------------------------------------------------------------- manifest / questions


def positions_manifest() -> tuple[dict, dict]:
    records = {}
    sources = {}
    for index, (code, store, item, alias, place) in enumerate(POSITIONS):
        row = 8 + index
        records[code] = {"门店": store, "物品": item, "别名": alias, "位置": place}
        sources[code] = {"file": "D01", "sheet": "物品位置", "row": row, "business_version": "V2"}
    stores = {}
    for index, (code, store, contact, phone, address, status) in enumerate(STORES):
        row = 5 + index
        stores[code] = {"店家": store, "联系人": contact, "电话": phone, "地址": address, "合作状态": status}
        sources[code] = {"file": "D02", "sheet": "店家信息", "row": row, "business_version": "V1"}
    records.update(stores)
    return records, sources


def normal_questions() -> list[dict]:
    exact = [
        ("Q01", "城东店的宣传海报在哪里？", ["B区1号货架第二层"], "D01", "P01"),
        ("Q02", "城西店的宣传海报在哪里？", ["C区2号货架第一层"], "D01", "P02"),
        ("Q03", "城东店的展架在哪里？", ["A区2号货架底层"], "D01", "P03"),
        ("Q04", "城西店的展架在哪里？", ["B区3号货架中层"], "D01", "P04"),
        ("Q05", "城东店的易拉宝在哪里？", ["D区1号柜第二层"], "D01", "P05"),
        ("Q06", "城西店的易拉宝在哪里？", ["D区2号柜第二层"], "D01", "P06"),
        ("Q07", "城东店的促销贴纸在哪里？", ["A区4号货架第一层"], "D01", "P07"),
        ("Q08", "城西店的价签卡纸在哪里？", ["C区1号柜第一层"], "D01", "P08"),
        ("Q09", "城东店的联系人是谁？", ["模拟联系人·陈宁"], "D02", "S01"),
        ("Q10", "城西店的联系人是谁？", ["模拟联系人·王平"], "D02", "S02"),
        ("Q11", "城北店的联系人是谁？", ["模拟联系人·李禾"], "D02", "S03"),
        ("Q12", "滨河店的联系人是谁？", ["模拟联系人·周安"], "D02", "S04"),
        ("Q13", "城东店的联系电话是什么？", ["010-00000001"], "D02", "S01"),
        ("Q14", "城西店的联系电话是什么？", ["010-00000002"], "D02", "S02"),
        ("Q15", "城北店的联系电话是什么？", ["010-00000003"], "D02", "S03"),
        ("Q16", "滨河店的联系电话是什么？", ["010-00000004"], "D02", "S04"),
        ("Q17", "城东店的地址是什么？", ["示例市示例路18号（模拟）"], "D02", "S01"),
        ("Q18", "城西店的地址是什么？", ["示例市示例路26号（模拟）"], "D02", "S02"),
        ("Q19", "城北店的地址是什么？", ["示例市北街8号（模拟）"], "D02", "S03"),
        ("Q20", "滨河店的地址是什么？", ["示例市滨河路6号（模拟）"], "D02", "S04"),
        ("Q21", "城东店现在是什么合作状态？", ["合作中"], "D02", "S01"),
        ("Q22", "城西店现在是什么合作状态？", ["合作中"], "D02", "S02"),
        ("Q23", "城北店现在是什么合作状态？", ["暂停合作"], "D02", "S03"),
        ("Q24", "滨河店现在是什么合作状态？", ["待签约"], "D02", "S04"),
    ]
    text = [
        ("Q25", "领取活动物料需要哪些步骤？", ["填写登记表", "负责人确认", "领取时登记数量"], "D03", {"heading": "2.3 物料领用与登记"}),
        ("Q26", "物料归还后还需要登记什么？", ["归还日期"], "D03", {"heading": "2.3 物料领用与登记"}),
        ("Q27", "活动申请至少提前多久？", ["3 个工作日"], "D04", {"heading": "3.1 活动申请"}),
        ("Q28", "活动方案需要包含哪些内容？", ["目标", "时间地点", "预算", "物料清单"], "D04", {"heading": "3.1 活动申请"}),
        ("Q29", "跨店调拨物料需要谁确认？", ["两店负责人"], "D05", {"page": 1, "heading": "二、跨店调拨"}),
        ("Q30", "物料归还时需要核对什么？", ["数量", "完好情况"], "D05", {"page": 1, "heading": "三、归还核对"}),
        ("Q31", "发现店家信息变化后，应何时联系谁？", ["当日", "资料管理员"], "D06", {"page": 1, "heading": "一、变更报告"}),
        ("Q32", "店家资料修改时需要记录什么？", ["业务更新时间", "修改原因"], "D06", {"page": 1, "heading": "二、变更记录"}),
    ]
    ocr = [
        ("Q33", "扫描的活动申请中，申请部门是什么？", ["市场部"], "D07", {"page": 3}),
        ("Q34", "扫描的活动申请中，活动日期是什么？", ["2026-11-05"], "D07", {"page": 3}),
        ("Q35", "仓库安全须知对物料通道有什么要求？", ["保持畅通"], "D08", {"page": 2}),
        ("Q36", "仓库安全须知要求向谁报告异常？", ["仓库负责人"], "D08", {"page": 2}),
        ("Q37", "物料领用通知图片要求先填写什么？", ["领用登记表"], "D09", {"image": True}),
        ("Q38", "物料领用通知图片要求谁确认？", ["负责人"], "D09", {"image": True}),
        ("Q39", "盘点通知中城东店海报的盘点时间是什么？", ["2026-10-30 16:00"], "D10", {"table_row": "城东店"}),
        ("Q40", "盘点通知中城东店海报的盘点地点是什么？", ["城东店物料区"], "D10", {"table_row": "城东店"}),
    ]
    questions = []
    for code, question, values, doc, record in exact:
        questions.append(
            {
                "id": code,
                "group": "normal",
                "category": "exact",
                "question": question,
                "expected_values": values,
                "expected_sources": [{"file": doc, "record": record}],
                "scenario": {"initial_state": "B0", "actions": [], "expected_kind": "answer"},
            }
        )
    for code, question, values, doc, locator in text:
        questions.append(
            {
                "id": code,
                "group": "normal",
                "category": "text",
                "question": question,
                "expected_values": values,
                "expected_sources": [{"file": doc, "locator": locator}],
                "scenario": {"initial_state": "B0", "actions": [], "expected_kind": "answer"},
            }
        )
    for code, question, values, doc, locator in ocr:
        questions.append(
            {
                "id": code,
                "group": "normal",
                "category": "ocr",
                "question": question,
                "expected_values": values,
                "expected_sources": [{"file": doc, "locator": locator}],
                "scenario": {"initial_state": "B0", "actions": [], "expected_kind": "answer"},
            }
        )
    return questions


def negative_questions() -> list[dict]:
    data = [
        ("N01", "城南店联系人是谁？", ["没有", "未找到"], "不存在该店资料"),
        ("N02", "城东店几点营业？", ["未记录"], "营业时间字段缺失"),
        ("N03", "城东店宣传海报的负责人是谁？", ["未记录"], "物品负责人未记录，不得用店家联系人代替"),
        ("N04", "城东店海报现在剩余多少张？", ["无", "未记录"], "无库存依据"),
        ("N05", "城西店本月销售额是多少？", ["无", "未记录"], "无销售资料"),
        ("N06", "宣传海报的采购价格是多少？", ["无", "未记录"], "无采购价格"),
        ("N07", "滨河店营业执照号是多少？", ["无", "未记录"], "无该字段"),
        ("N08", "根据货架照片告诉我没有标记物品的位置", ["范围外", "无法"], "图片不做实物识别"),
    ]
    out = []
    for code, question, values, reason in data:
        out.append(
            {
                "id": code,
                "group": "negative",
                "category": None,
                "question": question,
                "expected_values": values,
                "expected_sources": [],
                "scenario": {"initial_state": "B0", "actions": [], "expected_kind": "not_found", "reason": reason},
            }
        )
    return out


def ambiguity_questions() -> list[dict]:
    return [
        {
            "id": "C01",
            "group": "ambiguity_conflict",
            "category": None,
            "question": "宣传海报在哪里？",
            "expected_values": ["城东店", "城西店"],
            "expected_sources": [],
            "scenario": {
                "initial_state": "B0",
                "actions": [],
                "expected_kind": "clarification",
                "candidates": ["城东店", "城西店"],
            },
        },
        {
            "id": "C02",
            "group": "ambiguity_conflict",
            "category": None,
            "question": "展架在哪里？",
            "expected_values": ["城东店", "城西店"],
            "expected_sources": [],
            "scenario": {
                "initial_state": "B0",
                "actions": [],
                "expected_kind": "clarification",
                "candidates": ["城东店", "城西店"],
            },
        },
        {
            "id": "C03",
            "group": "ambiguity_conflict",
            "category": None,
            "question": "请给我联系人电话",
            "expected_values": ["门店", "店家"],
            "expected_sources": [],
            "scenario": {"initial_state": "B0", "actions": [], "expected_kind": "clarification", "candidates": ["城东店", "城西店", "城北店", "滨河店"]},
        },
        {
            "id": "C04",
            "group": "ambiguity_conflict",
            "category": None,
            "question": "它在哪？",
            "expected_values": ["物品", "门店"],
            "expected_sources": [],
            "scenario": {"initial_state": "B0", "actions": [], "expected_kind": "clarification", "reason": "新会话无上下文"},
        },
        {
            "id": "C05",
            "group": "ambiguity_conflict",
            "category": None,
            "question": "城东店的宣传海报现在放在哪里？",
            "expected_values": ["B区1号货架第二层", "D区暂存柜"],
            "expected_sources": [{"file": "D01", "record": "P01"}, {"file": "V01", "locator": {"page": 1, "heading": "通知"}}],
            "scenario": {
                "initial_state": "B0 + V01",
                "actions": [{"op": "publish", "file": "V01"}],
                "expected_kind": "conflict",
                "allowed_sources": ["D01", "V01"],
                "forbidden_sources": ["V03"],
            },
        },
        {
            "id": "C06",
            "group": "ambiguity_conflict",
            "category": None,
            "question": "城东店的联系电话是什么？",
            "expected_values": ["010-00000001", "010-00000099"],
            "expected_sources": [{"file": "D02", "record": "S01"}, {"file": "V02", "locator": {"page": 1, "heading": "变更通知"}}],
            "scenario": {
                "initial_state": "B0 + V02",
                "actions": [{"op": "publish", "file": "V02"}],
                "expected_kind": "conflict",
                "allowed_sources": ["D02", "V02"],
                "forbidden_sources": ["V06"],
            },
        },
    ]


def mutation_questions() -> list[dict]:
    base = {"initial_state": "B0", "expected_kind": "answer"}
    return [
        {
            "id": "U01",
            "group": "mutation",
            "category": None,
            "question": "P01 位置改版未发布时，城东店宣传海报在哪？",
            "expected_values": ["B区1号货架第二层"],
            "expected_sources": [{"file": "D01", "record": "P01"}],
            "scenario": {
                **base,
                "actions": [{"op": "upload_version", "document": "D01", "file": "V04"}, {"op": "process", "file": "V04"}],
                "assertions": ["发布前回答仍为旧值", "来源为当前有效版本 D01/V2"],
            },
        },
        {
            "id": "U02",
            "group": "mutation",
            "category": None,
            "question": "发布 P01 新位置后，新旧会话都问城东店宣传海报在哪？",
            "expected_values": ["D区暂存柜"],
            "expected_sources": [{"file": "V04", "record": "P01"}],
            "scenario": {
                **base,
                "actions": [
                    {"op": "upload_version", "document": "D01", "file": "V04"},
                    {"op": "publish", "file": "V04"},
                ],
                "assertions": ["新会话使用新值", "原会话追问同样使用新值", "来源指向新版本"],
            },
        },
        {
            "id": "U03",
            "group": "mutation",
            "category": None,
            "question": "改为新电话 010-00000088 并发布后，城东店联系电话是什么？",
            "expected_values": ["010-00000088"],
            "expected_sources": [{"file": "V06", "record": "S01"}],
            "scenario": {
                **base,
                "actions": [{"op": "upload_version", "document": "D02", "file": "V06"}, {"op": "publish", "file": "V06"}],
                "assertions": ["返回新电话", "不混入旧联系人字段"],
            },
        },
        {
            "id": "U04",
            "group": "mutation",
            "category": None,
            "question": "新版删除 P01 整行后，城东店宣传海报在哪？",
            "expected_values": ["未找到", "未记录"],
            "expected_sources": [],
            "scenario": {
                **base,
                "actions": [{"op": "upload_version", "document": "D01", "file": "V05"}, {"op": "publish", "file": "V05"}],
                "expected_kind": "not_found",
                "assertions": ["不得从旧索引或会话记忆返回 B区1号货架第二层"],
            },
        },
        {
            "id": "U05",
            "group": "mutation",
            "category": None,
            "question": "删除唯一含滨河店的资料后，滨河店联系人是谁？",
            "expected_values": ["失效", "未找到"],
            "expected_sources": [],
            "scenario": {
                **base,
                "actions": [{"op": "delete", "document": "D02"}],
                "expected_kind": "not_found",
                "assertions": ["新问题无该店依据", "历史答案保留且来源标记失效", "旧来源内容与原件不可访问"],
                "precondition": "D02 是 S04 的唯一来源",
            },
        },
        {
            "id": "U06",
            "group": "mutation",
            "category": None,
            "question": "删除 D01 后，城东店宣传海报在哪？",
            "expected_values": ["B区1号货架第二层"],
            "expected_sources": [{"file": "V07", "locator": {"page": 1, "heading": "位置通知"}}],
            "scenario": {
                **base,
                "actions": [{"op": "publish", "file": "V07"}, {"op": "delete", "document": "D01"}],
                "assertions": ["仍可由 V07 回答", "来源不得指向已删除的 D01"],
            },
        },
        {
            "id": "U07",
            "group": "mutation",
            "category": None,
            "question": "模型生成期间发布新版或删除来源，结果如何？",
            "expected_values": ["knowledge_changed"],
            "expected_sources": [],
            "scenario": {
                "initial_state": "B0",
                "sub_scenarios": [
                    {
                        "id": "U07a",
                        "variant": "publish",
                        "initial_state": "B0",
                        "preconditions": [
                            {"op": "upload_version", "document": "D01", "file": "V04"},
                            {"op": "process", "file": "V04"},
                            {"op": "review_required", "file": "V04"},
                        ],
                        "events": [
                            "ask_read_revision",
                            "pause_model_generation",
                            "publish_commit_V04",
                            "model_return",
                            "commit_revision_check",
                            "knowledge_changed",
                        ],
                        "expected": {"kind": "knowledge_changed", "sources": [], "saved_old_facts": False},
                    },
                    {
                        "id": "U07b",
                        "variant": "delete",
                        "initial_state": "B0",
                        "preconditions": [],
                        "events": [
                            "ask_read_revision",
                            "pause_model_generation",
                            "delete_commit_D01",
                            "model_return",
                            "commit_revision_check",
                            "knowledge_changed",
                        ],
                        "expected": {"kind": "knowledge_changed", "sources": [], "saved_old_facts": False},
                    },
                ],
                "assertions": [
                    "问答开始先读取 revision 并暂停模型生成",
                    "发布或删除提交后 revision 变化",
                    "提交前复核 revision 失败，返回 knowledge_changed",
                    "不保存待发旧事实，不返回任何旧来源",
                ],
            },
        },
        {
            "id": "U08",
            "group": "mutation",
            "category": None,
            "question": "两个不同候选基于同一旧版本并发发布，结果如何？",
            "expected_values": ["一个成功", "另一个 PUBLISH_CONFLICT"],
            "expected_sources": [],
            "scenario": {
                "initial_state": "B0",
                "preconditions": [
                    {"op": "upload_version", "document": "D01", "file": "V04"},
                    {"op": "process", "file": "V04"},
                    {"op": "review_required", "file": "V04"},
                    {"op": "upload_version", "document": "D01", "file": "V05"},
                    {"op": "process", "file": "V05"},
                    {"op": "review_required", "file": "V05"},
                ],
                "requests": [
                    {
                        "id": "U08a",
                        "file": "V04",
                        "captured_active_version_id": "current-active-version",
                        "captured_revision": "current-revision",
                        "expected": {"http_status": 200},
                    },
                    {
                        "id": "U08b",
                        "file": "V05",
                        "captured_active_version_id": "current-active-version",
                        "captured_revision": "current-revision",
                        "expected": {"http_status": 409, "error_code": "PUBLISH_CONFLICT"},
                    },
                ],
                "expected_revision_increment": 1,
                "assertions": [
                    "两次请求捕获同一旧 active_version_id 与 revision",
                    "仅一个返回 200，另一个返回 409 PUBLISH_CONFLICT",
                    "revision 只递增一次，有效版本不倒序切换",
                ],
                "idempotency": {
                    "file": "V04",
                    "expected_http_status": 200,
                    "note": "同一已生效版本重复发布且无竞争变更时返回原成功结果，不重复递增 revision；该子检查不得要求返回冲突",
                },
            },
        },
        {
            "id": "U09",
            "group": "mutation",
            "category": None,
            "question": "worker 处理扫描件时删除、取消或租约失效，迟到结果如何处理？",
            "expected_values": ["迟到结果丢弃"],
            "expected_sources": [],
            "scenario": {
                "initial_state": "B0",
                "sub_scenarios": [
                    {
                        "id": "U09a",
                        "variant": "delete",
                        "document": "D07",
                        "old_active_version": "D07/V1（已生效）",
                        "pending_version": "D07/V2（处理中，已被删除事务取消）",
                        "lease_id": "lease-u09a",
                        "ocr_sent_at": "2026-10-27T10:00:05+08:00",
                        "late_result_at": "2026-10-27T10:00:40+08:00",
                        "actions": [
                            {"op": "start_job", "document": "D07"},
                            {"op": "ocr_request_sent"},
                            {"op": "delete", "document": "D07"},
                            {"op": "late_result_arrives"},
                        ],
                        "expected": {
                            "active_access_revoked": True,
                            "document_restored": False,
                            "late_result_committed": False,
                            "no_next_page_or_retry": True,
                        },
                    },
                    {
                        "id": "U09b",
                        "variant": "cancel_pending_version",
                        "document": "D07",
                        "old_active_version": "D07/V1（已生效）",
                        "pending_version": "D07/V2（待处理新版，被取消）",
                        "lease_id": "lease-u09b",
                        "ocr_sent_at": "2026-10-27T10:01:05+08:00",
                        "late_result_at": "2026-10-27T10:01:35+08:00",
                        "actions": [
                            {"op": "start_job", "document": "D07"},
                            {"op": "ocr_request_sent"},
                            {"op": "cancel_version", "version": "D07/V2"},
                            {"op": "late_result_arrives"},
                        ],
                        "expected": {
                            "old_version_still_answerable": True,
                            "late_result_committed": False,
                            "no_next_page_or_retry": True,
                        },
                    },
                    {
                        "id": "U09c",
                        "variant": "lease_expired",
                        "document": "D07",
                        "old_active_version": "D07/V1（已生效）",
                        "pending_version": "D07/V2（处理中）",
                        "lease_id": "lease-u09c",
                        "ocr_sent_at": "2026-10-27T10:02:05+08:00",
                        "late_result_at": "2026-10-27T10:02:50+08:00",
                        "actions": [
                            {"op": "start_job", "document": "D07"},
                            {"op": "ocr_request_sent"},
                            {"op": "lease_expires"},
                            {"op": "late_result_arrives"},
                            {"op": "new_lease_acquired"},
                        ],
                        "expected": {
                            "stale_result_committed": False,
                            "new_holder_may_continue": True,
                        },
                    },
                ],
                "assertions": [
                    "删除：旧有效版访问立即撤销，迟到结果不得恢复资料",
                    "取消新版：旧有效版继续可查，不得一律期望 not_found",
                    "租约失效：旧租约结果不能提交，新持有者可继续处理",
                    "三种子场景均不开始下一页或重试",
                ],
            },
        },
        {
            "id": "U10",
            "group": "mutation",
            "category": None,
            "question": "同一 client_request_id 重复提交问答，结果如何？",
            "expected_values": ["不重复创建消息"],
            "expected_sources": [],
            "scenario": {
                "initial_state": "B0",
                "actions": [
                    {"op": "ask", "question": "城东店宣传海报在哪？", "client_request_id": "11111111-1111-4111-8111-111111111111"},
                    {"op": "ask", "question": "城东店宣传海报在哪？", "client_request_id": "11111111-1111-4111-8111-111111111111"},
                    {"op": "ask", "question": "城西店宣传海报在哪？", "client_request_id": "11111111-1111-4111-8111-111111111111"},
                ],
                "expected_kind": "answer",
                "events": ["request_1", "request_2_same_payload", "request_3_different_payload"],
                "assertions": ["同 ID 同载荷返回既有结果", "同 ID 不同载荷返回 REQUEST_PAYLOAD_MISMATCH"],
            },
        },
    ]


# --------------------------------------------------------------------- manifest


@dataclass
class CorpusManifest:
    root: str
    normal_files: list[dict] = field(default_factory=list)
    variants: list[dict] = field(default_factory=list)
    boundary: list[dict] = field(default_factory=list)
    records: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    questions: list[dict] = field(default_factory=list)
    font: dict = field(default_factory=dict)
    b0_initialization: dict = field(default_factory=dict)
    built_at: str = ""

    def record(self, code: str) -> dict:
        return self.records[code]

    def source(self, code: str):
        data = self.sources[code]
        return SimpleNamespace(**data)

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "built_at": self.built_at,
            "font": self.font,
            "b0_initialization": self.b0_initialization,
            "normal_files": self.normal_files,
            "variants": self.variants,
            "boundary": self.boundary,
            "records": self.records,
            "sources": self.sources,
            "questions_file": "questions.json",
        }


def load_manifest(path: Path) -> CorpusManifest:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    questions_path = Path(path).parent / data.get("questions_file", "questions.json")
    questions = json.loads(questions_path.read_text(encoding="utf-8"))["questions"] if questions_path.is_file() else []
    return CorpusManifest(
        root=data["root"],
        normal_files=data["normal_files"],
        variants=data["variants"],
        boundary=data.get("boundary", []),
        records=data["records"],
        sources=data["sources"],
        questions=questions,
        font=data.get("font", {}),
        b0_initialization=data.get("b0_initialization", {}),
        built_at=data.get("built_at", ""),
    )


def readme_text(font_hashes: dict) -> str:
    lines = [
        "# fixtures/acceptance 模拟语料（T01-C2）",
        "",
        f"本目录由 `tools/build_demo_corpus.py` 生成，全部内容为**{MARK}**，不代表任何真实企业流程或个人信息。",
        "",
        "## 结构",
        "",
        "- `normal/`：10 份正常资料（D01～D10），业务版本见 manifest。",
        "- `variants/`：冲突通知、历史/新版本、移除记录、新电话、U06 独立来源、异常样本与混合/失败页样本。",
        "- `boundary/`：单文件边界样本（50/51 页、5000/5001 行、2000 万/超出像素，共 6 个保留文件）。20MB 与 20MB+1 两份体积较大，默认只记录计量与哈希，需要实际文件时用下方“大小边界重建”命令生成。",
        "- `manifest.json`：文件身份、相对路径、SHA-256、业务版本、Locator、场景关联与 `b0_initialization` 初始化配方。",
        "- `questions.json`：64 条题目/场景（40 正常 + 8 无答案 + 6 歧义/冲突 + 10 更新回归），场景引用 B0 配方。",
        "- `font-license/OFL.txt`：静态字体派生所依据的 OFL 1.1 许可副本。",
        "",
        "## B0 初始化（业务 V2 的来源）",
        "",
        "B0 不是把 D01 直接当作业务 V2 导入，而是在**同一逻辑文件槽**上先建立历史版本：",
        "",
        "1. 导入 `variants/V03_物品位置表_历史V1.xlsx`（业务 V1，P01 在 A区3号货架第二层）→ 处理 → 发布。",
        "2. 以新版本方式导入 `normal/D01_物品位置表.xlsx`（业务 V2，P01 在 B区1号货架第二层）→ 处理 → 发布，成为当前有效版本。",
        "3. 其余 9 份正常文件各自首次导入即业务 V1，无历史版本。",
        "",
        "完整有序步骤与断言见 `manifest.json` 的 `b0_initialization`（含 `document_slot`、`business_version`、`forbidden`）。",
        "**不得用 V04 建立 B0**（V04 是 D 区新位置，仅用于 U01/U02/U07/U08）；业务版本与应用自动分配的版本号、`revision` 分开，`revision` 由实际运行读取，配方中不预设具体值。",
        "",
        "## 大小边界重建（保留实际文件）",
        "",
        "需要 20MB 上传边界文件时，用独立入口生成到**全新空目录**（非空目录会被拒绝）：",
        "",
        "```powershell",
        r".\.venv\Scripts\python.exe -B tools/build_demo_corpus.py --boundary-only <全新目录>",
        "```",
        "",
        "该命令生成并保留 `B01_恰好20MB.pdf`（20,971,520 字节）与 `B02_超过20MB一字节.pdf`（20,971,521 字节），字节数与 SHA-256 与 `manifest.json` 中记录一致；两份文件均为可打开的 PDF（尾部以合法注释填充），pdfplumber 可提取文字、PDFium 可打开。",
        "",
        "## 生成命令",
        "",
        "```powershell",
        r"Set-Location -LiteralPath 'D:\GPT项目\市场部AI知识库'",
        r".\.venv\Scripts\python.exe -B tools/build_demo_corpus.py --output <全新目录>",
        "```",
        "",
        "已有非空目录不会被静默覆盖；两次生成应在两个全新目录进行并比对哈希。",
        "",
        "## 字体",
        "",
        f"- 只读复用 `docs/evidence/T01/C1-R1/derived-fonts/` 的静态实例：Regular 400 `{font_hashes['regular']}`、Medium 500 `{font_hashes['medium']}`，均为 Noto Sans SC VF 固定 wght 派生，保留版权与 OFL。",
        "- 源 VF 为本地 Noto Sans SC 可变字体（版本串含 non-release），未与上游发布包逐字节比较。",
        "",
        "## 场景恢复",
        "",
        "- 正常 40 题始终在无冲突 B0 上执行。",
        "- C05/C06 需先发布 `variants/V01_临时物料位置通知.pdf` / `V02_店家联系方式变更通知.pdf`。",
        "- U01～U10 每个用例从 B0 独立恢复（独立数据库与文件目录），按 `questions.json` 中 `scenario.actions` 顺序执行。",
        "- `scenario.events`/`assertions` 给出事件先后与断言，供后续测试消费；本步不实现事务、worker 或模型适配器。",
        "",
        "## 限制",
        "",
        "- 未调用真实 OCR/模型；扫描件与图片的机器识别质量未验证。",
        "- 边界样本只证明计量口径，不构成业务拒绝规则或负载验收。",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- build


def build_corpus(
    output_dir: Path,
    *,
    font_dir: Path | None = None,
    boundary_dir: Path | None = None,
    force: bool = False,
) -> CorpusManifest:
    output_dir = Path(output_dir)
    font_dir = Path(font_dir) if font_dir else DEFAULT_FONT_DIR
    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        raise SystemExit(f"output directory not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    font_names = register_fonts(font_dir)
    normal = build_normal(output_dir, font_names, font_dir)
    variants = build_variants(output_dir, font_names, font_dir)
    boundary = make_boundary(Path(boundary_dir) if boundary_dir else output_dir / "boundary", font_names, font_dir)

    license_dir = output_dir / "font-license"
    license_dir.mkdir(exist_ok=True)
    shutil.copyfile(OFL_SOURCE, license_dir / "OFL.txt")

    records, sources = positions_manifest()
    questions = normal_questions() + negative_questions() + ambiguity_questions() + mutation_questions()
    # 依赖 B0 的场景统一引用同一初始化配方，避免 64 条重复整段步骤
    for question in questions:
        scenario = question["scenario"]
        if str(scenario.get("initial_state", "")).startswith("B0"):
            scenario.setdefault("initialization_ref", "b0_initialization")
        for sub in scenario.get("sub_scenarios", []):
            if str(sub.get("initial_state", "")).startswith("B0"):
                sub.setdefault("initialization_ref", "b0_initialization")

    manifest = CorpusManifest(
        root=".",
        normal_files=normal,
        variants=variants,
        boundary=boundary,
        records=records,
        sources=sources,
        questions=questions,
        font={
            "family": "Noto Sans SC Static",
            "regular_sha256": FONT_FILES[400][1],
            "medium_sha256": FONT_FILES[500][1],
            "license": "SIL OFL 1.1",
            "license_file": "font-license/OFL.txt",
        },
        b0_initialization=B0_INITIALIZATION,
        built_at="2026-10-27",
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    (output_dir / "questions.json").write_text(
        json.dumps(
            {
                "version": "B0",
                "built_at": "2026-10-27",
                "normal_categories": {"exact": 24, "text": 8, "ocr": 8},
                "questions": questions,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(
        readme_text({"regular": FONT_FILES[400][1], "medium": FONT_FILES[500][1]}), encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover
            pass
    parser = argparse.ArgumentParser(description="T01-C2 demo corpus builder (B0)")
    parser.add_argument("--output", required=False, type=Path, help="语料输出目录（全新或空目录）")
    parser.add_argument("--font-dir", type=Path, default=DEFAULT_FONT_DIR)
    parser.add_argument("--boundary-dir", type=Path, default=None)
    parser.add_argument("--force", action="store_true", help="允许写入已存在的非空输出目录")
    parser.add_argument(
        "--boundary-only",
        type=Path,
        default=None,
        metavar="DIR",
        help="仅生成并保留 20MB 大小边界样本 B01/B02 到全新目录（供上传测试取用）",
    )
    args = parser.parse_args(argv)

    if args.boundary_only is not None:
        entries = build_boundary_files(args.boundary_only, font_dir=args.font_dir)
        print(json.dumps({"boundary_only": str(args.boundary_only), "files": entries}, ensure_ascii=False, indent=2))
        return 0

    if args.output is None:
        parser.error("--output is required unless --boundary-only is used")

    manifest = build_corpus(
        args.output, font_dir=args.font_dir, boundary_dir=args.boundary_dir, force=args.force
    )
    summary = {
        "output": str(args.output),
        "normal": len(manifest.normal_files),
        "variants": len(manifest.variants),
        "boundary": len(manifest.boundary),
        "questions": len(manifest.questions),
        "groups": {
            key: sum(1 for q in manifest.questions if q["group"] == key)
            for key in ("normal", "negative", "ambiguity_conflict", "mutation")
        },
        "categories": {
            key: sum(1 for q in manifest.questions if q["category"] == key)
            for key in ("exact", "text", "ocr")
        },
        "total_bytes": sum(item["bytes"] for item in manifest.normal_files + manifest.variants),
        "boundary_kept_bytes": sum(item["bytes"] for item in manifest.boundary if item.get("kept")),
        "boundary_measured_only": [item["id"] for item in manifest.boundary if not item.get("kept")],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
