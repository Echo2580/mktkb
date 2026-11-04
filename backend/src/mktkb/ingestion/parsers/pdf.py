"""T07 PDF 逐页解析：文字页提取正文/普通表格，无可用文字的页才渲染并走 OCR。

规则（对应任务单 3.1/3.2）：
- 页码从 1 开始；页面正文/表格行 locator 保留 page 与 bbox，可回映原页；
- 只有 pdfplumber 明确识别出、且行列完整一致的表才生成 table_row；表头空/重复、
  行长度不一致或提取异常时只提示、不生成确定记录，并阻止整份完整成功；
- 只有无文字且无图像/矢量/线条等绘制对象的页才可核实为真空白；
  有绘制对象但无可用文字走有界渲染与 OCR，未识别则明确失败，不当空白跳过；
- 任一必需页失败/表格不可靠时整份不标记完整成功，但已成功页仍可预览；
- OCR 调用前后都复核任务/资料/版本/租约；取消/删除/租约失效时不写迟到结果。
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium

from ...providers.types import (
    OCRInput,
    OCRMode,
    OCRPageResult,
    OCRQuotaUnavailable,
    OCRError,
)
from .image import (
    _combined_confidence,
    looks_like_rule_table,
    prepare_ocr_tiles,
    validate_ocr_table,
)
from .notice_facts import extract_record_facts
from .types import (
    ParseError,
    ParseLimitError,
    ParseQuotaExceeded,
    ParsedUnit,
    ParseServices,
    ensure_live,
)

USABLE_TEXT_MIN_CHARS = 1


def parse_pdf(path: Path, kind: str, services: ParseServices) -> Iterator[ParsedUnit]:
    path = Path(path)
    # 先用 pypdfium2 区分口令加密与损坏；pdfminer 对加密文件的异常文本随版本变化。
    try:
        probe = pdfium.PdfDocument(str(path))
    except Exception as exc:
        message = str(exc).lower()
        if "password" in message or "encrypted" in message:
            raise ParseError("PDF 已加密，无法读取", code="FILE_ENCRYPTED") from None
        raise ParseError("PDF 已损坏或无法读取", code="FILE_CORRUPT") from None
    else:
        probe.close()
    try:
        pdf = pdfplumber.open(path)
    except Exception as exc:  # pdfminer 的异常类型随版本变化；按稳定原因归类
        message = str(exc).lower()
        if "password" in message or "encrypted" in message:
            raise ParseError("PDF 已加密，无法读取", code="FILE_ENCRYPTED") from None
        raise ParseError("PDF 已损坏或无法读取", code="FILE_CORRUPT") from None

    try:
        pages = list(pdf.pages)
        total = len(pages)
        _begin_report(services, total)
        if total <= 0:
            raise ParseError("PDF 没有可处理页面", code="EMPTY_CONTENT")
        if total > services.limits.pdf_max_pages:
            services.report["failed_pages"] = list(range(1, total + 1))
            services.report["quality"] = {
                "complete": False,
                "issues": [{"issue": "PDF_PAGE_LIMIT", "limit": services.limits.pdf_max_pages, "pages": total}],
            }
            raise ParseLimitError(
                f"PDF 页数超过 {services.limits.pdf_max_pages} 上限",
                code="PDF_PAGE_LIMIT",
            )

        units_total = 0
        issues: list[dict] = []
        failed_pages: list[int] = []
        blank_pages: list[int] = []
        fatal_reason: str | None = None

        for index, page in enumerate(pages, start=1):
            if fatal_reason is not None:
                _record_not_attempted(services, index, total, fatal_reason)
                failed_pages.append(index)
                continue
            ensure_live(services)
            try:
                lines = page.extract_text_lines() or []
                tables = page.find_tables() or []
            except Exception:
                _record_page_failure(
                    services, index, "PAGE_EXTRACT_FAILED", "页面内容无法可靠提取", source="text"
                )
                failed_pages.append(index)
                units_total = sum(entry.get("units", 0) for entry in services.report["pages"])
                continue

            usable = _usable_text(lines)
            detected_tables: list[Any] = []
            page_units: list[ParsedUnit] = []

            if usable:
                table_boxes: list[tuple[float, float, float, float]] = []
                unreliable_boxes: list[tuple[float, float, float, float]] = []
                for table_index, table in enumerate(tables, start=1):
                    ok, reason, header, data_rows = _table_rows(table)
                    if not ok:
                        issues.append(
                            {
                                "issue": "OCR_TABLE_UNRELIABLE" if "表格" in reason else "TABLE_UNRELIABLE",
                                "page": index,
                                "table": table_index,
                                "message": reason,
                            }
                        )
                        try:
                            unreliable_boxes.append(tuple(float(value) for value in table.bbox))
                        except Exception:
                            pass
                        continue
                    detected_tables.append(table)
                    bbox = tuple(float(value) for value in table.bbox)
                    table_boxes.append(bbox)
                    for row_number, row in enumerate(data_rows, start=2):
                        fields = {header[column]: row[column] for column in range(len(header))}
                        text_value = "；".join(
                            f"{header[column]}: {row[column]}"
                            for column in range(len(header))
                            if row[column] is not None
                        )
                        page_units.append(
                            ParsedUnit(
                                kind="table_row",
                                locator={
                                    "page": index,
                                    "table": table_index,
                                    "row": row_number,
                                    "bbox": [round(value, 3) for value in bbox],
                                },
                                text=text_value,
                                fields=fields,
                                warnings=[],
                                unit_key=f"table:p{index}:t{table_index}:r{row_number}",
                            )
                        )

                seen_texts: set[str] = set()
                for line_number, line in enumerate(lines, start=1):
                    text = str(line.get("text") or "")
                    if not text.strip():
                        continue
                    bbox = _line_bbox(line)
                    if _inside_any(bbox, table_boxes + unreliable_boxes):
                        continue
                    if text in seen_texts:
                        continue
                    seen_texts.add(text)
                    page_units.append(
                        ParsedUnit(
                            kind="paragraph",
                            locator={"page": index, "bbox": [round(value, 3) for value in bbox]},
                            text=text,
                            # T09-D2：正文里明确出现「门店 + 字段 + 值」的通知句补充结构化字段，
                            # 使正文来源能参与 record 检索与冲突比较（locator 仍是页/坐标）。
                            fields=extract_record_facts(text),
                            warnings=[],
                            unit_key=f"paragraph:p{index}:l{line_number}",
                        )
                    )

                _record_page_success(
                    services,
                    index,
                    source="text",
                    units=len(page_units),
                    tables=len(detected_tables),
                    text_lines=len(lines),
                    table_rows=sum(1 for unit in page_units if unit.kind == "table_row"),
                )
                for unit in page_units:
                    yield unit
                units_total += len(page_units)
                continue

            if not _has_nontext_objects(page):
                blank_pages.append(index)
                services.report["pages"].append(
                    {"page": index, "source": "blank", "status": "blank", "units": 0}
                )
                services.pages_done = index
                continue

            if services.ocr is None:
                _record_page_failure(
                    services,
                    index,
                    "OCR_NOT_CONFIGURED",
                    "OCR 未配置，扫描页无法识别",
                    source="ocr",
                )
                failed_pages.append(index)
                fatal_reason = "OCR_NOT_CONFIGURED"
                continue

            try:
                image, scale = _render_page(path, index, page.width, page.height, services.limits)
            except ParseLimitError as exc:
                _record_page_failure(services, index, exc.code, exc.message, source="ocr")
                failed_pages.append(index)
                continue
            except Exception:
                _record_page_failure(services, index, "PAGE_RENDER_FAILED", "页面渲染失败", source="ocr")
                failed_pages.append(index)
                continue

            mode: OCRMode = "table" if looks_like_rule_table(image) else "text"
            try:
                tiles = prepare_ocr_tiles(
                    image,
                    limits=services.limits,
                    mode=mode,
                    source_width=page.width,
                    source_height=page.height,
                )
            except ParseLimitError as exc:
                _record_page_failure(services, index, exc.code, exc.message, source="ocr", ocr_mode=mode)
                failed_pages.append(index)
                continue

            results: list[tuple[dict[str, Any], OCRPageResult]] = []
            try:
                for tile in tiles:
                    ensure_live(services)
                    result = services.ocr.recognize(
                        OCRInput(
                            content=tile["content"],
                            mime_type="image/png",
                            page=index,
                            bbox=tile["bbox"],
                        ),
                        mode=mode,
                    )
                    ensure_live(services)
                    results.append((tile, result))
            except OCRQuotaUnavailable as exc:
                _record_page_failure(
                    services,
                    index,
                    "OCR_QUOTA_UNAVAILABLE",
                    "OCR 额度不足，后续页面不再自动请求",
                    source="ocr",
                    ocr_mode=mode,
                )
                failed_pages.append(index)
                for remaining in range(index + 1, total + 1):
                    _record_not_attempted(services, remaining, total, "OCR_QUOTA_UNAVAILABLE")
                    failed_pages.append(remaining)
                raise ParseQuotaExceeded() from exc
            except OCRError as exc:
                _record_page_failure(
                    services,
                    index,
                    exc.code,
                    "页面 OCR 失败",
                    source="ocr",
                    ocr_mode=mode,
                )
                failed_pages.append(index)
                if exc.code == "OCR_RATE_LIMITED":
                    fatal_reason = "OCR_RATE_LIMITED"
                continue

            text = "\n".join(item.text for _tile, item in results if item.text.strip())
            request_ids = [item.provider_request_id for _tile, item in results if item.provider_request_id]
            confidence = _combined_confidence([item.confidence for _tile, item in results])
            page_units = []

            if mode == "table":
                rows: list[tuple[str | None, ...]] = []
                for _tile, result in results:
                    rows.extend(result.table_rows)
                ok, reason, header, data_rows = validate_ocr_table(tuple(rows))
                if not ok:
                    _record_page_failure(
                        services,
                        index,
                        "OCR_TABLE_UNRELIABLE",
                        reason,
                        source="ocr",
                        ocr_mode=mode,
                        request_ids=request_ids,
                        confidence=confidence,
                    )
                    failed_pages.append(index)
                    continue
                for row_number, row in enumerate(data_rows, start=2):
                    fields = {header[column]: row[column] for column in range(len(header))}
                    text_value = "；".join(
                        f"{header[column]}: {row[column]}"
                        for column in range(len(header))
                        if row[column] is not None
                    )
                    page_units.append(
                        ParsedUnit(
                            kind="table_row",
                            locator={"page": index, "table": 1, "row": row_number},
                            text=text_value,
                            fields=fields,
                            warnings=[],
                            unit_key=f"table:p{index}:r{row_number}",
                        )
                    )
            else:
                if not text.strip():
                    _record_page_failure(
                        services,
                        index,
                        "OCR_NO_TEXT",
                        "页面图像未识别到可用文字",
                        source="ocr",
                        ocr_mode=mode,
                        request_ids=request_ids,
                        confidence=confidence,
                    )
                    failed_pages.append(index)
                    continue
                for tile_index, (tile, result) in enumerate(results, start=1):
                    if not result.text.strip():
                        continue
                    locator: dict[str, Any] = {"page": index}
                    if tile["bbox"] is not None:
                        locator["bbox"] = [round(float(value), 3) for value in tile["bbox"]]
                    page_units.append(
                        ParsedUnit(
                            kind="image_text",
                            locator=locator,
                            text=result.text,
                            fields={},
                            warnings=[],
                            unit_key=f"image_text:p{index}:t{tile_index}",
                        )
                    )

            _record_page_success(
                services,
                index,
                source="ocr",
                units=len(page_units),
                ocr_mode=mode,
                request_ids=request_ids,
                confidence=confidence,
                tiles=len(tiles),
                text_chars=len(text),
                table_rows=sum(1 for unit in page_units if unit.kind == "table_row"),
            )
            for unit in page_units:
                yield unit
            units_total += len(page_units)
            services.report["units"] = units_total

        services.report["units"] = units_total
        services.report["failed_pages"] = sorted(set(failed_pages))
        services.report["blank_pages"] = sorted(set(blank_pages))
        failure_issues = [
            {
                "issue": entry.get("reason"),
                "page": entry.get("page"),
                "source": entry.get("source"),
                "message": entry.get("message"),
            }
            for entry in services.report["pages"]
            if entry.get("status") == "failed"
        ]
        services.report["quality"] = {
            "complete": not failed_pages and not issues and units_total > 0,
            "issues": issues + failure_issues,
        }
        if units_total == 0 and not failed_pages and blank_pages:
            raise ParseError("PDF 没有可用的文字内容", code="EMPTY_CONTENT", retryable=False)
        if services.report["quality"]["complete"] is not True:
            retryable = any(
                entry.get("reason") in {"OCR_TIMEOUT", "OCR_UNAVAILABLE", "OCR_RATE_LIMITED", "PAGE_EXTRACT_FAILED"}
                for entry in services.report["pages"]
                if entry.get("status") == "failed"
            )
            reasons = {
                entry.get("reason")
                for entry in services.report["pages"]
                if entry.get("status") == "failed" and entry.get("reason")
            }
            code = next(iter(reasons)) if len(reasons) == 1 else "PARSE_INCOMPLETE"
            raise ParseError(
                "PDF 存在失败页或不可靠内容，未形成完整记录；已成功页仍可预览",
                code=code,
                retryable=retryable,
            )
    finally:
        pdf.close()


# ---------------------------------------------------------------- 页面内容规则


def _begin_report(services: ParseServices, total: int) -> None:
    services.report.clear()
    services.report.update(
        {
            "kind": "pdf",
            "total_pages": total,
            "pages": [],
            "failed_pages": [],
            "blank_pages": [],
            "units": 0,
            "quality": {"complete": False, "issues": []},
        }
    )
    services.page_total = total
    services.pages_done = 0


def _usable_text(lines: list[dict]) -> bool:
    """存在任意非空白可提取字符即视为文字页（1～3 个字符同样保留原值）。

    固定 4 字符阈值会把真实短文字误判为无文字，进而漏页；这里只排除纯空白页。
    """
    chars = 0
    for line in lines:
        text = str(line.get("text") or "")
        stripped = "".join(character for character in text if not character.isspace())
        chars += len(stripped)
    return chars >= USABLE_TEXT_MIN_CHARS


def _has_nontext_objects(page) -> bool:
    """页面是否存在图像/矩形/曲线/线条/注释等非文字绘制对象。

    “没有位图图片”不等于真空白：矢量矩形、线条等同样是页面内容。只有这些对象与
    可提取文字都不存在时，页才可核实为真空白；否则必须走有界渲染与 OCR，或明确失败。
    """
    return any(
        getattr(page, name, None)
        for name in ("images", "rects", "curves", "lines", "annots")
    )


def _line_bbox(line: dict) -> tuple[float, float, float, float]:
    return (
        float(line.get("x0") or 0.0),
        float(line.get("top") or 0.0),
        float(line.get("x1") or 0.0),
        float(line.get("bottom") or 0.0),
    )


def _inside_any(bbox: tuple[float, float, float, float], boxes: list[tuple[float, float, float, float]]) -> bool:
    x = (bbox[0] + bbox[2]) / 2
    y = (bbox[1] + bbox[3]) / 2
    return any(box[0] <= x <= box[2] and box[1] <= y <= box[3] for box in boxes)


def _table_rows(table) -> tuple[bool, str, list[str], list[tuple[str | None, ...]]]:
    try:
        rows = table.extract()
    except Exception:
        return False, "表格提取失败，无法确认行列关系", [], []
    if not rows or len(rows) < 2:
        return False, "表格少于两行，缺少可确认的表头与数据", [], []
    width = len(rows[0])
    if width < 2:
        return False, "表格少于两列，不能确认行列关系", [], []
    if any(len(row) != width for row in rows):
        return False, "表格各行长度不一致，无法可靠恢复行列", [], []
    header = ["" if cell is None else str(cell).strip() for cell in rows[0]]
    if any(not cell for cell in header):
        return False, "表头存在空列，不能确认字段意义", [], []
    if len(set(header)) != width:
        return False, "表头存在重复字段，不能确认字段意义", [], []
    data_rows: list[tuple[str | None, ...]] = []
    for row in rows[1:]:
        normalized = tuple(
            None if cell is None or not str(cell).strip() else str(cell).strip() for cell in row
        )
        if any(value is not None for value in normalized):
            data_rows.append(normalized)
    if not data_rows:
        return False, "表格没有有效数据行", [], []
    return True, "", header, data_rows


def _render_page(path: Path, page_number: int, width: float, height: float, limits):
    """有界渲染：先按像素/边长/页数预算缩放，再解码；不先无界渲染整页。"""
    if width <= 0 or height <= 0:
        raise ParseLimitError("页面尺寸不合法", code="PDF_PAGE_SIZE_INVALID")
    max_pixels = max(1, int(limits.pdf_max_page_pixels))
    scale = min(float(limits.pdf_render_scale), math.sqrt(max_pixels / (width * height)))
    scale = min(scale, 10000.0 / max(width, height))
    if scale <= 0 or max(width, height) * scale < 50:
        raise ParseLimitError("页面在供应商尺寸限制内无法形成可识别图像", code="OCR_IMAGE_TOO_LARGE")
    document = pdfium.PdfDocument(str(path))
    try:
        page = document[page_number - 1]
        try:
            bitmap = page.render(scale=scale)
            try:
                return bitmap.to_pil().convert("RGB"), scale
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


# ---------------------------------------------------------------- 报告辅助


def _record_page_success(
    services: ParseServices,
    page: int,
    *,
    source: str,
    units: int,
    ocr_mode: OCRMode | None = None,
    request_ids: list[str] | None = None,
    confidence: float | None = None,
    tiles: int | None = None,
    text_lines: int | None = None,
    text_chars: int | None = None,
    tables: int | None = None,
    table_rows: int = 0,
) -> None:
    entry: dict[str, Any] = {
        "page": page,
        "source": source,
        "status": "success",
        "ocr_mode": ocr_mode,
        "units": units,
        "table_rows": table_rows,
    }
    if request_ids:
        entry["request_ids"] = request_ids
    if confidence is not None:
        entry["confidence"] = confidence
    if tiles is not None:
        entry["tiles"] = tiles
    if text_lines is not None:
        entry["text_lines"] = text_lines
    if text_chars is not None:
        entry["text_chars"] = text_chars
    if tables is not None:
        entry["tables"] = tables
    services.report["pages"].append(entry)
    services.pages_done = page


def _record_page_failure(
    services: ParseServices,
    page: int,
    code: str,
    message: str,
    *,
    source: str,
    ocr_mode: OCRMode | None = None,
    request_ids: list[str] | None = None,
    confidence: float | None = None,
) -> None:
    services.report["pages"].append(
        {
            "page": page,
            "source": source,
            "status": "failed",
            "reason": code,
            "message": message,
            "ocr_mode": ocr_mode,
            "request_ids": list(request_ids or []),
            "confidence": confidence,
        }
    )
    services.report["failed_pages"] = sorted(set(services.report.get("failed_pages") or []) | {page})
    services.report["quality"] = {
        "complete": False,
        "issues": (services.report.get("quality", {}).get("issues") or [])
        + [{"issue": code, "page": page, "source": source, "message": message}],
    }
    services.pages_done = page


def _record_not_attempted(services: ParseServices, page: int, total: int, reason: str) -> None:
    services.report["pages"].append(
        {
            "page": page,
            "source": "ocr",
            "status": "failed",
            "reason": reason,
            "message": "前序页面失败后未再发起后续 OCR 请求",
            "ocr_mode": None,
            "request_ids": [],
            "confidence": None,
        }
    )
    services.report["failed_pages"] = sorted(set(services.report.get("failed_pages") or []) | {page})
    services.pages_done = page
