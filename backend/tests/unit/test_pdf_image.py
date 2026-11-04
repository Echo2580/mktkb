"""T07 本地 PDF/图片解析检查：真实冻结样本 + 临时构造的有界样本。

OCR 只使用本文件的可控替身，不发网络请求、不读密钥。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

from mktkb.ingestion.parsers import (
    ParseError,
    ParseLimitError,
    ParseLimits,
    ParseQuotaExceeded,
    ParseServices,
    parse_document,
)
from mktkb.ingestion.parsers.image import prepare_ocr_tiles
from mktkb.providers.types import (
    OCRPageResult,
    OCRQuotaUnavailable,
    OCRTimeout,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"


class StubOCR:
    """可控 OCR：记录 page/mode/bbox/字节数，按页返回或抛出稳定错误。"""

    def __init__(self, handler=None) -> None:
        self.calls: list[dict] = []
        self.handler = handler

    def recognize(self, page, *, mode):
        self.calls.append(
            {
                "page": page.page,
                "mode": mode,
                "bbox": page.bbox,
                "bytes": len(page.content),
                "mime_type": page.mime_type,
            }
        )
        if self.handler is not None:
            return self.handler(page, mode)
        return OCRPageResult(
            text=f"识别文本第{page.page}页",
            regions=({"text": f"识别文本第{page.page}页", "bbox": [1, 2, 3, 4], "confidence": 98.0},),
            provider_request_id=f"req-{page.page}",
            confidence=98.0,
        )


def _services(ocr=None, **limit_overrides) -> ParseServices:
    return ParseServices(limits=ParseLimits(**limit_overrides), ocr=ocr)


def _parse(path: Path, kind: str, services: ParseServices):
    return list(parse_document(path, kind, services))


def _build_table_pdf(path: Path, rows: list[list[str]], *, span_header: bool = False) -> Path:
    document = SimpleDocTemplate(str(path), pagesize=A4)
    styles = getSampleStyleSheet()
    table = Table(rows, colWidths=[90, 100, 190])
    style = [("GRID", (0, 0), (-1, -1), 1, colors.black)]
    if span_header:
        style.append(("SPAN", (0, 0), (1, 0)))
    table.setStyle(TableStyle(style))
    document.build([Spacer(1, 12), table])
    return path


def _build_two_page_pdf(path: Path) -> Path:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.drawString(72, 720, "Page one has usable text")
    pdf.showPage()
    pdf.showPage()
    pdf.save()
    return path


def _build_rule_table_image(path: Path) -> Path:
    image = Image.new("RGB", (640, 420), "white")
    draw = ImageDraw.Draw(image)
    for y in (40, 140, 240, 340, 400):
        draw.line((30, y, 610, y), fill="black", width=3)
    for x in (30, 210, 410, 610):
        draw.line((x, 40, x, 400), fill="black", width=3)
    draw.text((50, 70), "Store", fill="black")
    draw.text((230, 70), "Item", fill="black")
    draw.text((50, 170), "East", fill="black")
    draw.text((230, 170), "Poster", fill="black")
    image.save(path)
    return path


# ---------------------------------------------------------------- 文字 PDF


def test_text_pdf_extracts_pages_without_ocr():
    stub = StubOCR()
    services = _services(stub)
    units = _parse(FIXTURES / "normal" / "D05_物料领用规范.pdf", "pdf", services)

    assert stub.calls == [], "文字型 PDF 不得调用 OCR"
    assert len(units) >= 5
    assert {unit.locator["page"] for unit in units} == {1}
    assert all(len(unit.locator["bbox"]) == 4 for unit in units)
    assert any("物料领用" in unit.text for unit in units)
    assert services.report["pages"][0]["source"] == "text"
    assert services.report["quality"]["complete"] is True


def test_text_pdf_regular_table_is_recovered_with_page_locator(tmp_path: Path):
    path = _build_table_pdf(
        tmp_path / "table.pdf",
        [
            ["Store", "Item", "Location"],
            ["East", "Poster", "B1 shelf 2"],
            ["West", "Stand", "C2 cabinet 1"],
        ],
    )
    stub = StubOCR()
    services = _services(stub)
    units = _parse(path, "pdf", services)

    assert stub.calls == []
    table_units = [unit for unit in units if unit.kind == "table_row"]
    assert len(table_units) == 2
    assert table_units[0].locator["page"] == 1
    assert table_units[0].locator["table"] == 1
    assert table_units[0].locator["row"] == 2
    assert table_units[0].fields == {"Store": "East", "Item": "Poster", "Location": "B1 shelf 2"}
    assert "Location: B1 shelf 2" in table_units[0].text
    assert services.report["quality"]["complete"] is True


def test_text_pdf_unreliable_table_does_not_invent_rows(tmp_path: Path):
    path = _build_table_pdf(
        tmp_path / "merged.pdf",
        [["Merged", "", "Location"], ["East", "Poster", "B1 shelf 2"]],
        span_header=True,
    )
    services = _services(StubOCR())
    collected: list = []
    with pytest.raises(ParseError) as excinfo:
        for unit in parse_document(path, "pdf", services):
            collected.append(unit)
    assert excinfo.value.code == "PARSE_INCOMPLETE"
    assert collected == [], "不可靠表不得生成确定记录，也不得把散落文字当段落"
    assert services.report["quality"]["complete"] is False
    issues = services.report["quality"]["issues"]
    assert any(issue.get("issue") == "TABLE_UNRELIABLE" for issue in issues)
    assert services.report["quality"]["complete"] is False


# ---------------------------------------------------------------- 混合/扫描 PDF


def test_scanned_eight_page_pdf_reports_every_page_and_skips_blank_logic():
    stub = StubOCR()
    services = _services(stub)
    units = _parse(FIXTURES / "normal" / "D07_活动申请扫描件.pdf", "pdf", services)

    assert [call["page"] for call in stub.calls] == list(range(1, 9))
    assert len(units) == 8
    assert [unit.locator["page"] for unit in units] == list(range(1, 9))
    pages = services.report["pages"]
    assert [entry["page"] for entry in pages] == list(range(1, 9))
    assert all(entry["status"] == "success" and entry["source"] == "ocr" for entry in pages)
    assert services.report["total_pages"] == 8
    assert services.report["quality"]["complete"] is True


def test_mixed_pdf_chooses_text_or_ocr_per_page():
    stub = StubOCR()
    services = _services(stub)
    _parse(FIXTURES / "variants" / "A07_混合页文档.pdf", "pdf", services)

    pages = services.report["pages"]
    assert [entry["source"] for entry in pages] == ["text", "ocr"]
    assert [call["page"] for call in stub.calls] == [2]
    assert services.report["quality"]["complete"] is True


def test_true_blank_page_is_reported_blank_and_not_ocr(tmp_path: Path):
    path = _build_two_page_pdf(tmp_path / "blank-page.pdf")
    stub = StubOCR()
    services = _services(stub)
    units = _parse(path, "pdf", services)

    assert stub.calls == [], "真空白页不得当作有图页调用 OCR"
    assert services.report["blank_pages"] == [2]
    second = services.report["pages"][1]
    assert second == {"page": 2, "source": "blank", "status": "blank", "units": 0}
    assert [unit.locator["page"] for unit in units] == [1]
    assert services.report["quality"]["complete"] is True


def test_failed_page_blocks_complete_success_but_keeps_other_pages():
    def handler(page, mode):
        if page.page == 3:
            raise OCRTimeout("simulated timeout")
        return OCRPageResult(text=f"第{page.page}页内容", provider_request_id=f"req-{page.page}")

    services = _services(StubOCR(handler))
    collected: list = []
    with pytest.raises(ParseError) as excinfo:
        for unit in parse_document(FIXTURES / "normal" / "D07_活动申请扫描件.pdf", "pdf", services):
            collected.append(unit)
    assert excinfo.value.code == "OCR_TIMEOUT"
    assert services.report["failed_pages"] == [3]
    assert [entry["page"] for entry in services.report["pages"]] == list(range(1, 9))
    assert len(collected) == 7
    assert services.report["quality"]["complete"] is False


def test_quota_marks_all_remaining_pages_and_stops_calls():
    def handler(page, mode):
        raise OCRQuotaUnavailable()

    stub = StubOCR(handler)
    services = _services(stub)
    with pytest.raises(ParseQuotaExceeded) as excinfo:
        _parse(FIXTURES / "normal" / "D07_活动申请扫描件.pdf", "pdf", services)
    assert excinfo.value.code == "OCR_QUOTA_UNAVAILABLE"
    assert len(stub.calls) == 1, "额度不足后不得继续请求下一页"
    assert services.report["failed_pages"] == list(range(1, 9))
    assert all(entry["status"] == "failed" for entry in services.report["pages"])


def test_encrypted_and_corrupt_pdf_have_stable_reasons(tmp_path: Path):
    with pytest.raises(ParseError) as encrypted:
        _parse(FIXTURES / "variants" / "A03_加密的规范.pdf", "pdf", _services())
    assert encrypted.value.code == "FILE_ENCRYPTED"

    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4\nthis is not a valid pdf body")
    with pytest.raises(ParseError) as broken:
        _parse(corrupt, "pdf", _services())
    assert broken.value.code == "FILE_CORRUPT"


def test_pdf_page_limit_boundary_and_over_limit():
    units = _parse(FIXTURES / "boundary" / "B03_恰好50页.pdf", "pdf", _services())
    assert len(units) == 50

    services = _services()
    with pytest.raises(ParseLimitError) as excinfo:
        _parse(FIXTURES / "boundary" / "B04_超过50页.pdf", "pdf", services)
    assert excinfo.value.code == "PDF_PAGE_LIMIT"
    assert services.report["failed_pages"] == list(range(1, 52))


# ---------------------------------------------------------------- 图片


def test_image_parser_uses_ocr_and_keeps_page_locator():
    stub = StubOCR()
    services = _services(stub)
    units = _parse(FIXTURES / "normal" / "D09_物料领用通知.png", "png", services)

    assert len(stub.calls) == 1
    assert stub.calls[0]["page"] == 1
    assert stub.calls[0]["mime_type"] == "image/png"
    assert len(units) == 1 and units[0].kind == "image_text"
    assert units[0].locator["page"] == 1
    assert services.report["quality"]["complete"] is True
    assert services.report["total_pages"] == 1


def test_blank_image_is_failure_not_success():
    stub = StubOCR()
    services = _services(stub)
    with pytest.raises(ParseError) as excinfo:
        _parse(FIXTURES / "variants" / "A05_无文字的照片.png", "png", services)
    assert excinfo.value.code == "OCR_NO_TEXT"
    assert stub.calls == []
    assert services.report["failed_pages"] == [1]
    assert services.report["quality"]["complete"] is False


def test_blurry_image_without_recognized_text_is_failure():
    def handler(page, mode):
        return OCRPageResult(text="", provider_request_id="blur-req")

    stub = StubOCR(handler)
    services = _services(stub)
    with pytest.raises(ParseError) as excinfo:
        _parse(FIXTURES / "variants" / "A04_模糊的照片.png", "png", services)
    assert excinfo.value.code == "OCR_NO_TEXT"
    assert len(stub.calls) == 1, "模糊图仍交给 OCR，以真实空结果作为稳定失败原因"
    assert services.report["quality"]["complete"] is False


def test_image_without_ocr_configuration_fails_stably():
    services = _services(None)
    with pytest.raises(ParseError) as excinfo:
        _parse(FIXTURES / "normal" / "D09_物料领用通知.png", "png", services)
    assert excinfo.value.code == "OCR_NOT_CONFIGURED"
    assert services.report["quality"]["complete"] is False


def test_image_pixel_limit_is_checked_before_decode_and_calls():
    stub = StubOCR()
    services = _services(stub)
    with pytest.raises(ParseLimitError) as excinfo:
        _parse(FIXTURES / "boundary" / "B08_超过2000万像素.png", "png", services)
    assert excinfo.value.code == "IMAGE_PIXEL_LIMIT"
    assert stub.calls == []

    exact = _services(StubOCR())
    with pytest.raises(ParseError) as boundary:
        _parse(FIXTURES / "boundary" / "B07_恰好2000万像素.png", "png", exact)
    assert boundary.value.code == "OCR_NO_TEXT", "恰好 2000 万像素允许进入解析，空白图按无文字失败"


def test_image_extension_mismatch_and_corrupt(tmp_path: Path):
    mislabeled = tmp_path / "photo.png"
    mislabeled.write_bytes((FIXTURES / "normal" / "D10_盘点通知.jpg").read_bytes())
    with pytest.raises(ParseError) as mismatch:
        _parse(mislabeled, "png", _services())
    assert mismatch.value.code == "INVALID_FILE_TYPE"

    corrupt = tmp_path / "broken.png"
    corrupt.write_bytes(b"\x89PNG\r\n\x1a\n" + b"broken")
    with pytest.raises(ParseError) as broken:
        _parse(corrupt, "png", _services())
    assert broken.value.code == "FILE_CORRUPT"


def test_rule_table_image_produces_table_rows(tmp_path: Path):
    path = _build_rule_table_image(tmp_path / "table.png")

    def handler(page, mode):
        assert mode == "table"
        return OCRPageResult(
            text="Store | Item\nEast | Poster",
            table_rows=(("Store", "Item"), ("East", "Poster")),
            provider_request_id="table-req",
            confidence=99.0,
        )

    stub = StubOCR(handler)
    services = _services(stub)
    units = _parse(path, "png", services)

    assert len(stub.calls) == 1 and stub.calls[0]["mode"] == "table"
    assert len(units) == 1 and units[0].kind == "table_row"
    assert units[0].fields == {"Store": "East", "Item": "Poster"}
    assert services.report["quality"]["complete"] is True


def test_unreliable_ocr_table_produces_no_records(tmp_path: Path):
    path = _build_rule_table_image(tmp_path / "table.png")

    def handler(page, mode):
        return OCRPageResult(text="broken", table_rows=(("Store", "Item"), ("East",)))

    services = _services(StubOCR(handler))
    with pytest.raises(ParseError) as excinfo:
        _parse(path, "png", services)
    assert excinfo.value.code == "OCR_TABLE_UNRELIABLE"
    assert services.report["quality"]["complete"] is False


def test_tiling_preserves_source_bbox_mapping(tmp_path: Path):
    path = tmp_path / "gradient.png"
    image = Image.new("RGB", (800, 600))
    pixels = image.load()
    for y in range(600):
        for x in range(800):
            value = (x * 7 + y * 13) % 256
            pixels[x, y] = (value, (value * 3) % 256, (value * 5) % 256)
    image.save(path)

    with Image.open(path) as opened:
        tiles = prepare_ocr_tiles(
            opened.convert("RGB"),
            limits=SimpleNamespace(ocr_max_tiles=16, ocr_max_image_bytes=2000),
            mode="text",
            source_width=400.0,
            source_height=300.0,
        )
    assert len(tiles) > 1
    for tile in tiles:
        assert tile["bbox"] is not None
        x0, y0, x1, y1 = tile["bbox"]
        assert 0 <= x0 < x1 <= 400.0 and 0 <= y0 < y1 <= 300.0
        assert tile["content"].startswith(b"\x89PNG")


# ---------------------------------------------------------------- T07-R1 追加回归


def _r1_two_page_pdf(path: Path, draw_second) -> Path:
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.drawString(72, 720, "Page one has usable text")
    pdf.showPage()
    draw_second(pdf)
    pdf.showPage()
    pdf.save()
    return path


@pytest.mark.parametrize("value", ["1", "12", "123", "1234"])
def test_r1_short_text_pages_keep_original_text_and_page_locator(tmp_path: Path, value: str):
    def draw_second(pdf):
        pdf.drawString(60, 700, value)

    path = _r1_two_page_pdf(tmp_path / f"short-{value}.pdf", draw_second)
    stub = StubOCR()
    services = _services(stub)
    units = _parse(path, "pdf", services)

    assert stub.calls == [], "可提取短文字页不得被当作扫描页调用 OCR"
    assert services.report["blank_pages"] == [], "1～3 个字符的可提取文字不是真空白"
    assert services.report["pages"][1]["status"] == "success"
    assert services.report["pages"][1]["source"] == "text"
    second_page = [unit for unit in units if unit.locator["page"] == 2]
    assert [unit.text for unit in second_page] == [value], "短文字必须保留原值"
    assert len(second_page[0].locator["bbox"]) == 4
    assert services.report["quality"]["complete"] is True


def test_r1_vector_only_page_is_not_blank_and_goes_to_bounded_ocr(tmp_path: Path):
    def draw_second(pdf):
        pdf.setFillColorRGB(0, 0, 0)
        pdf.rect(60, 500, 200, 150, fill=1)

    path = _r1_two_page_pdf(tmp_path / "vector-only.pdf", draw_second)
    stub = StubOCR()
    services = _services(stub)
    units = _parse(path, "pdf", services)

    assert services.report["blank_pages"] == [], "仅含矢量内容的非空页不得标空白"
    assert services.report["pages"][1]["status"] == "success"
    assert services.report["pages"][1]["source"] == "ocr"
    assert [call["page"] for call in stub.calls] == [2]
    assert [unit.locator["page"] for unit in units] == [1, 2]
    assert services.report["quality"]["complete"] is True


def test_r1_vector_only_page_without_ocr_fails_instead_of_blank(tmp_path: Path):
    def draw_second(pdf):
        pdf.setFillColorRGB(0, 0, 0)
        pdf.rect(60, 500, 200, 150, fill=1)

    path = _r1_two_page_pdf(tmp_path / "vector-no-ocr.pdf", draw_second)
    services = _services(None)
    with pytest.raises(ParseError) as excinfo:
        _parse(path, "pdf", services)

    assert excinfo.value.code == "OCR_NOT_CONFIGURED"
    assert services.report["blank_pages"] == [], "未识别不得静默转为真空白"
    assert services.report["failed_pages"] == [2]
    assert services.report["quality"]["complete"] is False
