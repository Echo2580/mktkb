#!/usr/bin/env python
r"""企业模拟资料库生成器（测试用，不属于产品代码）。

产出 `corpus/enterprise-20261101/`：60+ 份贴合快消市场部真实场景的资料
（Word 制度、Excel 台账、文字 PDF、扫描件与图片、版本变体、安全样本、
官方法规原文、边界样本），外加 manifest.json、答案键 questions.json、
导入顺序 README.md。

约束：只读复用 tools/build_demo_corpus.py 的字体与边界样本工具；
不访问网络、不调用 OCR 或模型、不修改 fixtures/acceptance 冻结语料；
固定随机源，两次生成内容一致。

用法：
    .\.venv\Scripts\python.exe -B tools\build_enterprise_corpus.py --output corpus\enterprise-20261101
    可选：--with-size-boundary 追加 20MB/20MB+1 两份大样本；--font-dir DIR 指定静态字体目录。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib.util

_spec = importlib.util.spec_from_file_location("build_demo_corpus", ROOT / "tools" / "build_demo_corpus.py")
_demo = importlib.util.module_from_spec(_spec)
sys.modules["build_demo_corpus"] = _demo
_spec.loader.exec_module(_demo)

from enterprise_corpus_data import (  # noqa: E402
    COMPANY,
    DATES,
    MATERIALS,
    POSITIONS,
    SKUS,
    STORES,
    fmt_day,
)
from enterprise_corpus_docs import (  # noqa: E402
    IMAGE_DOCS,
    SCAN_PDFS,
    SAFETY_PDFS,
    TEXT_PDFS,
    VARIANT_TEXT_PDFS,
    WORD_DOCS,
    doc_no,
)
from enterprise_corpus_questions import build_questions  # noqa: E402
from enterprise_corpus_tables import (  # noqa: E402
    campaign_sheet,
    contact_history_sheet,
    dealer_sheet,
    display_sheet,
    kpi_sheet,
    ledger_sheets,
    materials_sheet,
    price_sheets,
    positions_sheet,
    stores_sheet,
)

MARK = "模拟语料"
BIZ_DATE = fmt_day(DATES["biz_base"])
CREATOR = "tools/build_enterprise_corpus.py"
FIXED_DOC_TIME = datetime(2026, 11, 1, 9, 0, 0)
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
LEGAL_SRC = Path(__file__).resolve().parent / "enterprise_corpus_src" / "legal"
LIMITS = {
    "max_upload_bytes": 20 * 1024 * 1024,
    "pdf_max_pages": 50,
    "excel_max_data_rows": 5000,
    "image_max_pixels": 20_000_000,
    "supported_suffixes": ["xlsx", "docx", "pdf", "png", "jpg", "jpeg"],
}


# --------------------------------------------------------------------- 容器与文档构造


def _normalize_zip(path: Path) -> None:
    _demo.normalize_zip(path)


def make_docx(path: Path, title: str, sections: list[tuple[str, list[str]]], meta: list[str]) -> None:
    from docx import Document
    from docx.shared import Pt

    document = Document()
    props = document.core_properties
    props.author = CREATOR
    props.created = FIXED_DOC_TIME
    props.modified = FIXED_DOC_TIME
    props.title = f"{MARK} · {title}"
    props.comments = f"{MARK}｜业务更新 {BIZ_DATE}"
    props.revision = 1

    document.add_heading(title, level=0).runs[0].font.size = Pt(18)
    for line in meta:
        paragraph = document.add_paragraph(line)
        paragraph.runs[0].font.size = Pt(9)
    for section_title, paragraphs in sections:
        document.add_heading(section_title, level=1)
        for text in paragraphs:
            document.add_paragraph(text)
    document.save(path)
    _normalize_zip(path)


def make_xlsx(path: Path, sheets: list[dict]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for spec in sheets:
        sheet = workbook.create_sheet(spec["name"][:31])
        for row_index, row in enumerate(spec["rows"], start=1):
            for col_index, value in enumerate(row, start=1):
                if value is None or value == "":
                    continue
                cell = sheet.cell(row=row_index, column=col_index)
                cell.value = value
                if isinstance(value, str) and len(value) > 3 and value[:1].isdigit() and "-" in value:
                    cell.number_format = "@"
        if spec.get("hidden"):
            sheet.sheet_state = "hidden"
    workbook.properties.creator = CREATOR
    workbook.properties.created = FIXED_DOC_TIME
    workbook.properties.modified = FIXED_DOC_TIME
    workbook.properties.title = f"{MARK} 台账"
    workbook.save(path)
    _normalize_zip(path)


def make_text_pdf(path: Path, title: str, blocks: list[list[str]], meta: list[str], font_names: dict[int, str]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(f"{MARK} · {title}")
    pdf.setAuthor(CREATOR)
    pdf.setSubject(f"{MARK}｜业务更新 {BIZ_DATE}")
    pdf.setCreator(CREATOR)
    width, height = A4
    y = height - 64
    pdf.setFont(font_names[500], 15)
    pdf.drawString(48, y, title[:38])
    if len(title) > 38:
        y -= 16
        pdf.setFont(font_names[400], 11)
        pdf.drawString(48, y, title[38:])
    y -= 18
    pdf.setFont(font_names[400], 9)
    for line in meta:
        pdf.drawString(48, y, line)
        y -= 13
    y -= 12
    for block in blocks:
        for line in block:
            if y < 60:
                pdf.showPage()
                y = height - 60
            heading = line.startswith("# ")
            pdf.setFont(font_names[500] if heading else font_names[400], 12 if heading else 10)
            pdf.drawString(48, y, line[2:] if heading else line[:70])
            if not heading and len(line) > 70:
                y -= 14
                pdf.drawString(48, y, line[70:])
            y -= 17 if heading else 14
        y -= 10
    pdf.showPage()
    pdf.save()


def make_scan_pdf(path: Path, pages: list[list[str]], font_dir: Path) -> None:
    """纯图像扫描 PDF（无文字层），用于真实 OCR 链路测试。"""
    from PIL import Image, ImageDraw

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    title_font = _demo.pillow_font(font_dir, 500, 40)
    body_font = _demo.pillow_font(font_dir, 400, 30)
    note_font = _demo.pillow_font(font_dir, 400, 22)
    width_px, height_px = 1240, 1754
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(f"{MARK} · 扫描件")
    pdf.setAuthor(CREATOR)
    pdf.setCreator(CREATOR)
    for index, lines in enumerate(pages, start=1):
        image = Image.new("RGB", (width_px, height_px), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle([26, 26, width_px - 26, height_px - 26], outline=(150, 150, 150), width=3)
        draw.text((90, 120), lines[0], font=title_font, fill=(0, 0, 0))
        y = 220
        for line in lines[1:]:
            draw.text((90, y), line, font=body_font, fill=(0, 0, 0))
            y += 52
        draw.text((90, height_px - 110), f"{MARK}／第 {index} 页／扫描件样本", font=note_font, fill=(90, 90, 90))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        pdf.drawImage(ImageReader(buffer), 0, 0, width=A4[0], height=A4[1])
        pdf.showPage()
    pdf.save()


def make_text_image(path: Path, lines: list[str], font_dir: Path) -> None:
    from PIL import Image, ImageDraw

    width, height = 1000, 760
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _demo.pillow_font(font_dir, 500, 42)
    body_font = _demo.pillow_font(font_dir, 400, 32)
    draw.rectangle([18, 18, width - 18, height - 18], outline=(120, 120, 120), width=3)
    draw.text((56, 60), lines[0], font=title_font, fill=(0, 0, 0))
    y = 160
    for line in lines[1:]:
        draw.text((56, y), line, font=body_font, fill=(0, 0, 0))
        y += 62
    draw.text((56, height - 70), f"{MARK}／图片样张", font=_demo.pillow_font(font_dir, 400, 22), fill=(90, 90, 90))
    _save_image(image, path)


def make_table_image(path: Path, title: str, header: list[str], rows: list[list[str]], font_dir: Path) -> None:
    from PIL import Image, ImageDraw

    col_count = len(header)
    width = 1240
    row_height = 86
    height = 300 + row_height * (len(rows) + 1)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    head_font = _demo.pillow_font(font_dir, 500, 28)
    cell_font = _demo.pillow_font(font_dir, 400, 26)
    note_font = _demo.pillow_font(font_dir, 400, 22)
    draw.text((50, 44), title, font=head_font, fill=(0, 0, 0))
    draw.text((50, 92), f"{MARK}｜业务更新 {BIZ_DATE}", font=note_font, fill=(90, 90, 90))
    usable = width - 100
    col_width = usable // col_count
    left, top = 50, 150
    x = left
    for value in header:
        draw.rectangle([x, top, x + col_width, top + row_height], outline=(0, 0, 0), width=3)
        draw.text((x + 18, top + 26), value, font=head_font, fill=(0, 0, 0))
        x += col_width
    for row_index, row in enumerate(rows):
        y = top + row_height * (row_index + 1)
        x = left
        for col_index, value in enumerate(row):
            draw.rectangle([x, y, x + col_width, y + row_height], outline=(0, 0, 0), width=3)
            draw.text((x + 18, y + 26), str(value), font=cell_font, fill=(0, 0, 0))
            x += col_width
    draw.text((50, top + row_height * (len(rows) + 1) + 26), f"{MARK}／表格图片样本", font=note_font, fill=(90, 90, 90))
    _save_image(image, path)


def _save_image(image, path: Path) -> None:
    if path.suffix.lower() == ".png":
        image.save(path, format="PNG")
    else:
        image.save(path, format="JPEG", quality=92, subsampling=0, progressive=False)


def make_corrupt(path: Path, flavour: str) -> None:
    """按字节构造异常样本：截断的 Office 容器、随机噪声图片头。"""
    import random

    rng = random.Random(7)
    if flavour == "docx":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, payload in (("word/document.xml", "<w:document " + "x" * 200), ("[Content_Types].xml", "<Types/>")):
                info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, payload)
        path.write_bytes(buffer.getvalue()[: len(buffer.getvalue()) // 2])
    elif flavour == "xlsx":
        path.write_bytes(bytes(rng.randrange(256) for _ in range(4096)))
    elif flavour == "pdf":
        path.write_bytes(b"%PDF-1.7\n" + bytes(rng.randrange(256) for _ in range(4096)))
    elif flavour == "blank_image":
        from PIL import Image

        _save_image(Image.new("RGB", (1200, 700), (244, 240, 232)), path)


# --------------------------------------------------------------------- 法规原文


def legal_documents() -> list[dict]:
    mapping = {
        "规范促销行为暂行规定.txt": ("L01", "规范促销行为暂行规定（国家市场监督管理总局令第32号）.docx",
                                 "https://www.gov.cn/gongbao/content/2020/content_5567756.htm"),
        "明码标价和禁止价格欺诈规定.txt": ("L02", "明码标价和禁止价格欺诈规定（国家市场监督管理总局令第56号）.docx",
                                     "http://zjamr.zj.gov.cn/art/2024/8/6/art_1229810468_2526420.html"),
        "中华人民共和国反不正当竞争法.txt": ("L03", "中华人民共和国反不正当竞争法（2025年修订）.docx",
                                        "https://www.hebswjrb.gov.cn/content/3900/116.html"),
    }
    out = []
    for fname, (code, target, url) in mapping.items():
        src = LEGAL_SRC / fname
        if not src.is_file():
            continue
        lines = [l.strip() for l in src.read_text(encoding="utf-8").split("\n") if l.strip()]
        out.append({"code": code, "file": target, "title": target.rsplit(".", 1)[0], "lines": lines, "source_url": url})
    return out


# --------------------------------------------------------------------- 生成


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def measure(path: Path, kind: str) -> dict:
    info: dict = {"bytes": path.stat().st_size}
    name = path.name.lower()
    try:
        if name.endswith(".pdf"):
            import pdfplumber

            with pdfplumber.open(path) as pdf:
                info["pages"] = len(pdf.pages)
                info["has_text_layer"] = bool((pdf.pages[0].extract_text() or "").strip()) if pdf.pages else False
        elif name.endswith(".xlsx"):
            from openpyxl import load_workbook

            workbook = load_workbook(path, read_only=True)
            info["sheets"] = [sheet.title for sheet in workbook.worksheets]
            info["total_rows"] = int(sum(sheet.max_row or 0 for sheet in workbook.worksheets))
            workbook.close()
        elif name.endswith((".png", ".jpg", ".jpeg")):
            from PIL import Image

            with Image.open(path) as image:
                info["pixels"] = image.width * image.height
                info["size"] = [image.width, image.height]
        elif name.endswith(".docx"):
            from docx import Document

            document = Document(path)
            info["paragraphs"] = len(document.paragraphs)
    except Exception as exc:  # 边界样本允许不可解析
        info["measure_error"] = f"{type(exc).__name__}: {exc}"
    return info


class Builder:
    def __init__(self, output: Path, font_dir: Path, font_names: dict[int, str]) -> None:
        self.output = output
        self.font_dir = font_dir
        self.fonts = font_names
        self.entries: list[dict] = []

    def emit(self, code: str, group: str, subdir: str, filename: str, kind: str, writer, purpose: str,
             extra: dict | None = None) -> None:
        directory = self.output / subdir
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        if kind in {"pdf", "docx", "xlsx"} and path.exists():
            raise SystemExit(f"输出路径冲突，已有文件会被覆盖：{path}")
        writer(path)
        entry = {
            "code": code,
            "group": group,
            "path": f"{subdir}/{filename}",
            "kind": kind,
            "purpose": purpose,
            "sha256": sha256_file(path),
            **measure(path, kind),
        }
        if kind == "scan_pdf":
            entry["ocr_expected"] = True
        if extra:
            entry.update(extra)
        self.entries.append(entry)


def excel_files(b: Builder) -> None:
    ledgers = ledger_sheets()
    specs = [
        ("E01", "excel", "E01_物料主数据表.xlsx", materials_sheet(), "物料与成品单价、规格、条码、渠道；精确题与冲突题基础"),
        ("E02", "excel", "E02_覆盖门店台账.xlsx", stores_sheet(), "门店渠道、等级、店长、电话、面积与客流；门店事实题"),
        ("E03", "excel", "E03_2026年Q4渠道价目表.xlsx", None, "分渠道价格（多 sheet），含生效/失效与审批编号；价格题主来源"),
        ("E04", "excel", "E04_陈列位配置与考核标准表.xlsx", display_sheet(), "位置类型、排面数、考核分值与扣分规则"),
        ("E05", "excel", "E05_领用核销台账_1200行.xlsx", ledgers[0], "1200 行流水台账，检索与容量观察"),
        ("E06", "excel", "E06_促销活动排期与结案台账.xlsx", campaign_sheet(), "80 场活动机制、预算、费用率与结案状态"),
        ("E07", "excel", "E07_巡检评分明细_2000行.xlsx", ledgers[1], "2000 行巡检明细，含检查项编号与扣分原因"),
        ("E08", "excel", "E08_赠品核销明细_800行.xlsx", ledgers[2], "赠品发放与稽核结论，配合安全题"),
        ("E09", "excel", "E09_经销商与通路覆盖名录.xlsx", dealer_sheet(), "账期、返利与评级；仅经理及以上可查阅的敏感样本"),
        ("E10", "excel", "E10_市场部KPI月报.xlsx", kpi_sheet(), "指标口径与目标/实际；KPI 题主来源"),
        ("E11", "excel", "E11_终端物料位置表_当前V2.xlsx", positions_sheet(), "★当前有效的门店-物品-位置台账（精确题主来源）"),
        ("E12", "excel", "E12_门店信息变更历史表.xlsx", contact_history_sheet(), "旧值/新值/生效日期；陈旧事实题"),
    ]
    for code, subdir, filename, sheet, purpose in specs:
        if code == "E03":
            sheets = price_sheets()
            b.emit(code, "excel", subdir, filename, "xlsx", lambda p: make_xlsx(p, sheets), purpose,
                   extra={"sheet_count": len(sheets)})
        else:
            b.emit(code, "excel", subdir, filename, "xlsx", lambda p, s=sheet: make_xlsx(p, [s]), purpose)


def word_files(b: Builder) -> None:
    for spec in WORD_DOCS:
        meta = [
            f"{COMPANY}　市场部　文件编号：{doc_no(spec['no'])}",
            f"发布：市场部｜生效：{fmt_day(DATES['publish_effect'])}｜业务更新：{BIZ_DATE}",
            f"{MARK}｜本文件为知识库测试用模拟资料，不代表任何真实企业制度",
        ]
        b.emit(spec["code"], "word", "word", spec["file"], "docx",
               lambda p, s=spec, m=meta: make_docx(p, s["title"], s["sections"], m), spec["purpose"])


def pdf_files(b: Builder) -> None:
    for spec in TEXT_PDFS:
        meta = [
            f"{COMPANY}　市场部｜{doc_no(spec['no'])}",
            f"生效：{fmt_day(DATES['publish_effect'])}｜业务更新：{BIZ_DATE}",
            f"{MARK}｜模拟资料，不构成真实经营或报价依据",
        ]
        b.emit(spec["code"], "pdf", "pdf", spec["file"], "pdf",
               lambda p, s=spec, m=meta: make_text_pdf(p, s["title"], s["blocks"], m, b.fonts), spec["purpose"])


def scan_files(b: Builder) -> None:
    for spec in SCAN_PDFS:
        b.emit(spec["code"], "scan", "scan", spec["file"], "scan_pdf",
               lambda p, s=spec: make_scan_pdf(p, s["pages"], b.font_dir), spec["purpose"],
               extra={"planned_ocr_pages": len(spec["pages"])})
    for spec in IMAGE_DOCS:
        if spec["mode"] == "table":
            writer = lambda p, s=spec: make_table_image(p, s["title"], s["header"], s["rows"], b.font_dir)
        else:
            writer = lambda p, s=spec: make_text_image(p, s["lines"], b.font_dir)
        b.emit(spec["code"], "scan", "scan", spec["file"], "image", writer, spec["purpose"],
               extra={"planned_ocr_pages": 1})


def variant_files(b: Builder) -> None:
    from enterprise_corpus_data import POSITIONS_V1, POSITIONS_V3
    from enterprise_corpus_tables import _sheet

    def positions_sheet_for(records: list[tuple], title_lines: list[str], header_line: list[str]) -> dict:
        rows = [[r[0], r[1], r[2], "", r[3], r[4], r[5], r[6]] for r in records]
        return _sheet("物品位置", title_lines, header_line, rows)

    header = ["标识", "门店", "物品", "别名", "位置", "数量", "单位", "更新日期"]
    v1 = positions_sheet_for(
        [(pid, store, item, loc, qty, unit, day) for pid, store, item, loc, qty, unit, day in POSITIONS_V1],
        ["启沣饮品（苏城）市场部 终端物料位置表（历史 V1）", "文件编号：QF-SCB-2026-018 V1",
         "业务更新日期：2026-08-05", "说明：本表已被当前 V2 替代，仅用于对账追溯。"], header)
    v3 = positions_sheet_for(
        [(pid, store, item, loc, qty, unit, day) for pid, store, item, loc, qty, unit, day in POSITIONS_V3],
        ["启沣饮品（苏城）市场部 终端物料位置表（新版 V3，2026-11-20 生效）", "文件编号：QF-SCB-2026-018 V3",
         "编制：通路行销组　批准：沈亮", "业务更新日期：2026-11-20", "说明：城北片区仓库搬迁后的新库位。"], header)
    removed_rows = [[p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]] for p in POSITIONS if p[0] != "QF21"]
    v7 = _sheet("物品位置",
                ["启沣饮品（苏城）市场部 终端物料位置表（卓刀河店赠品已回收）", "文件编号：QF-SCB-2026-018 V2b",
                 f"业务更新日期：{BIZ_DATE}", "说明：本版删除了 QF21 马克杯记录。"],
                header, removed_rows)

    for code, purpose, sheet in [
        ("V01", "历史版本 V1：位置与当前不同，测试陈旧事实", v1),
        ("V02", "后续版本 V3：2026-11-20 才生效的新库位", v3),
        ("V07", "删除类：不含 QF21，测试删除后不可答", v7),
    ]:
        spec = next(s for s in VARIANT_TEXT_PDFS if s["code"] == code)
        target = spec["file"]
        b.emit(code, "variant", "variants", target, "xlsx", lambda p, s=sheet: make_xlsx(p, [s]), purpose)

    for spec in VARIANT_TEXT_PDFS:
        code = spec["code"]
        if code in ("V01", "V02", "V07"):
            continue
        if spec["kind"] == "pdf":
            meta = [f"{COMPANY}　市场部｜变体样本", f"业务更新：{BIZ_DATE}", f"{MARK}｜用于版本、冲突与重复导入测试"]
            subdir, filename = ("variants", spec["file"]) if "/" not in spec["file"] else ("variants/" + spec["file"].split("/")[0], spec["file"].split("/")[1])
            b.emit(code, "variant", subdir, filename, "pdf",
                   lambda p, s=spec, m=meta: make_text_pdf(p, s["title"], s["blocks"], m, b.fonts), spec["purpose"],
                   extra={"duplicate_of": spec.get("duplicate_of")} if spec.get("duplicate_of") else None)


def safety_files(b: Builder) -> None:
    for spec in SAFETY_PDFS:
        if spec["file"].endswith(".docx"):
            meta = [f"{COMPANY}　市场部｜{doc_no(spec['no'])}", f"{MARK}｜敏感资料模拟样本，姓名与手机号均为虚构"]
            b.emit(spec["code"], "safety", "safety", spec["file"], "docx",
                   lambda p, s=spec, m=meta: make_docx(p, s["title"], s["sections"], m), spec["purpose"])
        else:
            meta = [f"{COMPANY}　市场部｜{doc_no(spec['no'])}", f"业务更新：{BIZ_DATE}",
                    f"{MARK}｜安全测试样本，文本中的指令不应被执行"]
            b.emit(spec["code"], "safety", "safety", spec["file"], "pdf",
                   lambda p, s=spec, m=meta: make_text_pdf(p, s["title"], s["blocks"], m, b.fonts), spec["purpose"])


def legal_files(b: Builder) -> None:
    for spec in legal_documents():
        lines = spec["lines"]
        sections = [("正文（原文）", lines[1:])]
        meta = [
            f"来源：{spec['source_url']}（公开发布的国家机关公文文本，不适用著作权保护）",
            f"抓取日期：2026-11-01｜收录方式：全文原样，未作改写",
            "本文件为公开法规原文，非模拟内容；用于合规类问答测试。",
        ]
        b.emit(spec["code"], "legal", "legal", spec["file"], "docx",
               lambda p, s=spec, m=meta: make_docx(p, s["title"], sections, m), "官方法规原文（公开文本）",
               extra={"source_url": spec["source_url"], "article_lines": len(lines)})


def boundary_files(b: Builder, with_size: bool) -> None:
    """越界与异常样本。expected_rejection 标明应由哪一层拦下：parse / upload / none / ocr。"""
    def page_pdf(pages: int):
        return lambda p: _demo.make_page_count_pdf(p, b.fonts, pages)

    def rows_xlsx(rows: int):
        return lambda p: _demo.make_rows_xlsx(p, rows)

    plan = [
        ("B01", "B01_恰好50页.pdf", "pdf", page_pdf(50), "页数上限内应处理成功", "none"),
        ("B02", "B02_超过50页.pdf", "pdf", page_pdf(51), "页数超限应在解析层失败", "parse"),
        ("B03", "B03_恰好5000行.xlsx", "xlsx", rows_xlsx(5000), "行数上限内应成功", "none"),
        ("B04", "B04_超过5001行.xlsx", "xlsx", rows_xlsx(5001), "行数超限应在解析层失败", "parse"),
        ("B05", "B05_损坏的文档.docx", "docx_corrupt", lambda p: make_corrupt(p, "docx"), "容器损坏应解析失败，不发布", "parse"),
        ("B06", "B06_损坏的表格.xlsx", "xlsx_corrupt", lambda p: make_corrupt(p, "xlsx"), "非 zip 容器应拒绝", "parse"),
        ("B07", "B07_加密的规范.pdf", "pdf", lambda p: _demo.make_encrypted_pdf(p, b.fonts), "带口令 PDF 应提示需口令", "parse"),
        ("B08", "B08_无文字的照片.png", "image_no_text", lambda p: make_corrupt(p, "blank_image"), "无文字图片：OCR 应返回空，不得编造", "ocr"),
        ("B09", "B09_模糊的照片.png", "image", lambda p: _demo.make_blurred_image(p, b.font_dir), "模糊样张，识别质量取决于真实 OCR", "ocr"),
    ]
    for code, filename, kind, writer, purpose, rejection in plan:
        b.emit(code, "boundary", "boundary", filename, kind, writer, purpose, extra={"expected_rejection": rejection})

    if with_size:
        directory = b.output / "boundary" / "size"
        entries = _demo.build_boundary_files(directory, font_dir=b.font_dir)
        renames = {"B01_恰好20MB.pdf": ("B10", "none"), "B02_超过20MB一字节.pdf": ("B11", "upload")}
        for item in entries:
            code, rejection = renames[item["path"]]
            new_name = f"{code}_{item['path'].split('_', 1)[1]}"
            source = directory / item["path"]
            target = directory / new_name
            source.rename(target)
            b.entries.append({
                "code": code, "group": "boundary", "path": f"boundary/size/{new_name}", "kind": "pdf",
                "purpose": "体积边界样本（恰好 20MB 应放行；多 1 字节应在上传层拦下）",
                "expected_rejection": rejection, "sha256": sha256_file(target), "bytes": target.stat().st_size,
            })


# --------------------------------------------------------------------- 交付物


IMPORT_RECIPE = {
    "id": "enterprise_corpus_import",
    "description": "建议导入顺序。阶段 1–4 不触发 OCR；阶段 5 扫描件与图片会发起真实腾讯 OCR；"
                   "阶段 7 的版本与变体须严格按序，用于陈旧事实、同名替换与重复内容测试。",
    "phases": [
        {"phase": 1, "note": "基础台账（先建可答事实）", "files": ["E01", "E02", "E11", "E03", "E04", "E06", "E09", "E10", "E12"]},
        {"phase": 2, "note": "制度与流程（语义题来源）", "files": ["W01", "W02", "W03", "W04", "W05", "W06", "W07", "W08", "W09", "W10", "W11", "W12"]},
        {"phase": 3, "note": "通知、纪要与复盘", "files": ["P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10"]},
        {"phase": 4, "note": "大表流水（观察检索与容量）", "files": ["E05", "E07", "E08"]},
        {"phase": 5, "note": "★触发真实 OCR，导入前须确认额度", "files": ["C01", "C02", "C07", "C03", "C04", "C05", "C06", "C08"]},
        {"phase": 6, "note": "官方法规原文", "files": ["L01", "L02", "L03"]},
        {"phase": 7, "note": "变体（严格顺序：先历史、再当前、后新版）",
         "files": ["V01", "E11", "V02", "V03", "V04", "V05", "V06", "V07", "V08"],
         "assertions": [
             "V01 发布后 QF01 位置为 店内外侧（历史值），E11 发布后为当前有效值",
             "V04 与 V05 文件名相同、字节不同，用于同名不同字节的 409 与替换流程",
             "V06 与 V05 字节相同，用于重复内容 409 DUPLICATE_CONTENT",
             "V02 记录的库位 2026-11-20 才生效，导入后当前答案仍应为 E11 的值",
         ]},
        {"phase": 8, "note": "安全样本（注入、隐私、伪造依据）", "files": ["X01", "X02", "X03", "X04", "X05"]},
        {"phase": 9, "note": "边界样本（预期失败）", "files": ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B09"]},
    ],
}


def ocr_budget(entries: list[dict]) -> dict:
    pages = sum(e.get("planned_ocr_pages", 0) for e in entries)
    return {
        "files_requiring_real_ocr": sum(1 for e in entries if e.get("ocr_expected") or e.get("planned_ocr_pages")),
        "planned_images_or_pages": pages,
        "note": "扫描件按页、图片按张各至少 1 次 OCR 请求；表格页与大图可能按分片多次调用，"
                "上限以产品 ocr_max_tiles=64 为界。问答阶段每问约 1 次模型调用。",
        "model_calls_for_answer_key": len(build_questions()),
    }


def readme_text(entries: list[dict], questions: list[dict]) -> str:
    groups: dict[str, list[str]] = {}
    for e in entries:
        groups.setdefault(e["group"], []).append(e["code"])
    counts = {}
    for q in questions:
        counts[q["group"]] = counts.get(q["group"], 0) + 1
    lines = [
        "# 企业模拟资料库（corpus/enterprise-20261101）",
        "",
        f"- 业务基准日：{BIZ_DATE}　生成入口见下（重新生成内容字节一致）",
        f"- 文件总数：{len(entries)}　答案键题数：{len(questions)}（分组：{counts}）",
        "- 生成入口：`.\\.venv\\Scripts\\python.exe -B tools\\build_enterprise_corpus.py --output corpus\\enterprise-20261101`",
        "",
        "## 1. 这是什么",
        "",
        f"为「市场部 AI 知识库」准备的**测试资料库**。除 `legal/` 三份为公开发布的国家机关法规原文外，"
        f"其余全部为原创虚构内容：公司「{COMPANY}」、门店、经销商、条码、电话、价格、人名均不存在真实指向。"
        "业务设定为中国快消饮品企业市场部的终端行销场景（陈列生动化、物料领用核销、渠道价格、促销活动、"
        "门店巡检、经销商账期返利、导购管理），类目与术语取自公开行业资料的通用做法。",
        "",
        "## 2. 与冻结验收语料的关系",
        "",
        "- `fixtures/acceptance/`（D01–D10、V01–V07、B01–B08 与 64 题题集）是验收用冻结基线，**本资料库不覆盖、不修改、不参与判分**。",
        "- 本资料库使用独立编码体系（E/W/P/C/V/X/L/B），门店名与标识（QF01…）与冻结语料（P01…）刻意不同，避免事实串台。",
        "",
        "## 3. 目录与分组",
        "",
    ]
    for group in ["excel", "word", "pdf", "scan", "variants", "safety", "legal", "boundary"]:
        if groups.get(group):
            lines.append(f"- `{group}/`（{len(groups[group])} 份）：{'、'.join(sorted(groups[group]))}")
    lines += [
        "",
        "## 4. 系统硬上限（生成时已核对）",
        "",
        f"- 支持后缀：{', '.join(LIMITS['supported_suffixes'])}｜单文件 ≤ {LIMITS['max_upload_bytes'] // (1024 * 1024)}MB"
        f"｜PDF ≤ {LIMITS['pdf_max_pages']} 页｜Excel 数据行 ≤ {LIMITS['excel_max_data_rows']}"
        f"｜图片 ≤ {LIMITS['image_max_pixels']:,} 像素｜单次 OCR 图 ≤ 4MB、分片 ≤ 64。",
        "- `boundary/` 刻意放了越界样本（51 页、5001 行、损坏容器、加密 PDF、无文字图片），用于观察失败形态。",
        "",
        "## 5. 建议导入顺序",
        "",
        "见 `manifest.json` 的 `import_recipe`。要点：",
        "",
        "1. 先 `E11/E01/E02/E03` 建事实，再进制度与通知，问答才有针对性。",
        "2. **阶段 5（C01–C08）会发起真实腾讯 OCR**，阶段 8/9 的模型问答会发起真实模型调用。"
        "是否导入由主人决定，本工具本身不产生任何真实调用。",
        "3. 阶段 7 严格按序（V01 历史 → E11 当前 → V02 未生效新版），否则版本类题目会失真。",
        "",
        "## 6. 答案键与覆盖",
        "",
        f"`questions.json` 共 {len(questions)} 题，按 exact / semantic / stale / conflict / no_answer / safety / legal / ocr / rrem / boundary 分组，"
        "每题给出期望值、期望来源文件与期望 kind，可直接用于人工检查。",
        "",
        "其中 `rrem` 组专门复刻 **R-REM-01** 的四类被拒句式（双括号插入、值后置括号、尾注「（模拟）」、多字段并列），"
        "用于验证 `conversations/service.py` 记录型准入的返工效果；返工前这些题在真实服务下可能返回 `MODEL_OUTPUT_INVALID`。",
        "",
        "## 7. 已验证与未验证",
        "",
        "- 已离线验证：产品自身解析器可解析全部 docx/xlsx/文字 PDF；上限核对；两次生成字节一致。",
        "- **未验证：`scan/` 的识别质量**（需真实 OCR 才能确认，本工具未调用）；检索与问答效果需导入后由主人实测。",
        "- 法规原文来自公开政务网站，已在 `manifest.json` 记录来源 URL 与抓取日期；正文未作改写。",
        "",
        "## 8. 真实调用预算（导入前先看这条）",
        "",
        f"- 需要 OCR 的文件：{ocr_budget(entries)['files_requiring_real_ocr']} 份（按页/张估计 {ocr_budget(entries)['planned_images_or_pages']} 次起，表格分片会更多）。",
        f"- 跑完整答案键：约 {len(questions)} 次模型调用。",
        "- 按项目纪律，新真实调用需主人授权并记账（累计已 154 次）。",
        "",
    ]
    return "\n".join(lines)


def build_corpus(output: Path, font_dir: Path, with_size_boundary: bool) -> dict:
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"输出目录非空，拒绝覆盖：{output}")
    output.mkdir(parents=True, exist_ok=True)
    font_names = _demo.register_fonts(font_dir)
    b = Builder(output, font_dir, font_names)

    excel_files(b)
    word_files(b)
    pdf_files(b)
    scan_files(b)
    variant_files(b)
    safety_files(b)
    legal_files(b)
    boundary_files(b, with_size_boundary)

    questions = build_questions()
    manifest = {
        "root": ".",
        "generator": CREATOR,
        "company": f"{COMPANY}（虚构）",
        "business_base_date": BIZ_DATE,
        "limits": LIMITS,
        "font": {"family": "Noto Sans SC Static（只读复用冻结语料派生字体）", "regular": "OFL-1.1"},
        "declaration": "除 legal/ 为公开发布的国家机关法规原文外，全部内容均为虚构模拟语料，不含真实企业信息或个人信息。",
        "ocr_budget": ocr_budget(b.entries),
        "files": sorted(b.entries, key=lambda e: e["code"]),
        "import_recipe": IMPORT_RECIPE,
        "question_count": len(questions),
        "fact_index": {
            "positions": {p[0]: {"store": p[1], "item": p[2], "location": p[4], "qty": p[5], "unit": p[6]} for p in POSITIONS[:24]},
            "stores": {s[1]: {"code": s[0], "channel": s[4], "level": s[5], "principal": s[9], "phone": s[10]} for s in STORES},
            "materials": {m["code"]: {"name": m["name"], "unit_price": m["unit_price"], "spec": m["spec"]} for m in MATERIALS},
            "skus": {s["code"]: {"name": s["name"], "barcode": s["barcode"], "msrp": s["msrp"]} for s in SKUS},
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "questions.json").write_text(
        json.dumps({"version": "enterprise-20261101", "business_base_date": BIZ_DATE, "questions": questions},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "README.md").write_text(readme_text(b.entries, questions), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成企业模拟资料库（不调用 OCR/模型）")
    parser.add_argument("--output", required=True, help="全新空目录")
    parser.add_argument("--font-dir", default=str(_demo.DEFAULT_FONT_DIR), help="静态 Noto Sans SC 字体目录")
    parser.add_argument("--with-size-boundary", action="store_true", help="追加 20MB 与 20MB+1 两份大样本")
    args = parser.parse_args(argv)

    manifest = build_corpus(Path(args.output), Path(args.font_dir), args.with_size_boundary)
    files = manifest["files"]
    total_bytes = sum(f["bytes"] for f in files)
    print(json.dumps({
        "files": len(files),
        "total_bytes": total_bytes,
        "questions": manifest["question_count"],
        "ocr_files": manifest["ocr_budget"]["files_requiring_real_ocr"],
        "groups": sorted({f["group"] for f in files}),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
