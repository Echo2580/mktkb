"""回归：规则表格图片的识别模式（T09-D2 P1 根因）。

既有 ``looks_like_rule_table`` 要求竖线贯穿整图高度的一半，表格只占页面一部分时会漏判，
导致单元格事实被当成普通文字整段识别。这里用真实 fixture 与合成图固定住新口径：
- 表格只占图高约 1/3 的截图仍判为规则表格（D10 盘点通知）；
- 纯文字图/扫描页文字图判为非表格（D09 物料领用通知、扫描页渲染图）；
- 原本就判为表格的合成表格仍判为表格（不回归）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from mktkb.ingestion.parsers.image import looks_like_rule_table

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"


def _table_screenshot(path: Path, *, top_ratio: float = 0.23, bottom_ratio: float = 0.56) -> Path:
    """表格只占页面中部一段（模拟"截图里只有表格区域"），上下留白。"""
    width, height = 1240, 620
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    top, bottom = int(height * top_ratio), int(height * bottom_ratio)
    rows = [top, int(top + (bottom - top) / 3), int(top + 2 * (bottom - top) / 3), bottom]
    for y in rows:
        draw.line((50, y, 1190, y), fill="black", width=2)
    for x in (50, 280, 530, 860, 1190):
        draw.line((x, top, x, bottom), fill="black", width=2)
    image.save(path)
    return path


def test_rule_table_spanning_part_of_page_is_detected():
    assert looks_like_rule_table(Image.open(FIXTURES / "normal" / "D10_盘点通知.jpg").convert("RGB")) is True


def test_partial_page_table_screenshot_is_detected(tmp_path):
    path = _table_screenshot(tmp_path / "partial-table.png")
    assert looks_like_rule_table(Image.open(path).convert("RGB")) is True


@pytest.mark.parametrize("name", ["D09_物料领用通知.png", "D07_活动申请扫描件.pdf", "D08_仓库安全须知扫描件.pdf"])
def test_text_only_images_are_not_rule_tables(name):
    path = FIXTURES / "normal" / name
    if path.suffix == ".pdf":
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(str(path))
        page = document[0]
        image = page.render(scale=2.0).to_pil().convert("RGB")
    else:
        image = Image.open(path).convert("RGB")
    assert looks_like_rule_table(image) is False


def test_full_page_table_still_detected(tmp_path):
    """既有口径下的整页表格（竖线贯穿大半个图高）不得回归。"""
    image = Image.new("RGB", (640, 420), "white")
    draw = ImageDraw.Draw(image)
    for y in (40, 140, 240, 340, 400):
        draw.line((30, y, 610, y), fill="black", width=3)
    for x in (30, 210, 410, 610):
        draw.line((x, 40, x, 400), fill="black", width=3)
    path = tmp_path / "table.png"
    image.save(path)
    assert looks_like_rule_table(Image.open(path).convert("RGB")) is True
