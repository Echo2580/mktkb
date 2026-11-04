"""T07 图片解析与共享的图像边界/切块/版面规则。

- 先读文件头与像素尺寸，再决定是否解码；超过 20,000,000 像素不进入整图解码。
- 图片只通过注入的 OCRGateway 识别；本模块不读取密钥、不访问网络、不拼接目标 URL。
- 规则表格判定只使用明确的长横/竖线结构，不宣称识别准确率；无法可靠恢复行列时
  不生成确定记录。
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from ...providers.types import (
    OCRInput,
    OCRMode,
    OCRPageResult,
    OCRQuotaUnavailable,
    OCRError,
)
from .types import (
    ParseError,
    ParseLimitError,
    ParseQuotaExceeded,
    ParsedUnit,
    ParseServices,
    ensure_live,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
EXPECTED_FORMAT = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG"}
MIN_PROVIDER_SIDE = 50
MAX_PROVIDER_SIDE = 10000
MAX_TABLE_ASPECT = 3.0
# 规则表格竖线判定：连续暗像素段至少达到缩放后图高的 20%，且不少于 24px
MIN_VERTICAL_RUN_RATIO = 0.2
MIN_VERTICAL_RUN_PX = 24


# ---------------------------------------------------------------- 共享图像规则


def image_is_near_blank(image: Image.Image) -> bool:
    """近空白判定：缩略图灰度动态范围极小且整体接近白色；只用于“无文字”稳定原因。"""
    thumbnail = image.convert("L")
    thumbnail.thumbnail((64, 64))
    low, high = thumbnail.getextrema()
    return (high - low) <= 6 and high >= 245


def looks_like_rule_table(image: Image.Image) -> bool:
    """只按长横线/长竖线结构判定“可能是规则表格”，不输出识别置信度。

    T09-D2：竖线判定从"覆盖整图高度的一半"改为"存在足够长的连续竖线像素段"。
    原口径要求竖线贯穿半张图，对"页面上只看表格区域"的截图（表格只占图高约 1/3）会漏判，
    这类图片被当成普通文字图整段识别，单元格事实进不了结构化索引。
    新口径仍要求至少 2 条长横线（覆盖半幅宽）+ 至少 2 条足够长的连续竖线；纯文字图
    不满足（字符笔画会被行距打断，无法形成长连续段）。
    """
    gray = image.convert("L")
    width, height = gray.size
    if width < 100 or height < 100:
        return False
    scale = min(1.0, 400.0 / max(width, height))
    if scale < 1.0:
        gray = gray.resize((max(1, int(width * scale)), max(1, int(height * scale))))
    width, height = gray.size
    pixels = gray.tobytes()
    dark_threshold = 160
    row_dark = [0] * height
    for y in range(height):
        offset = y * width
        count = 0
        for x in range(width):
            if pixels[offset + x] < dark_threshold:
                count += 1
        row_dark[y] = count
    horizontal = sum(1 for count in row_dark if count >= width * 0.5)
    column_runs = _longest_dark_runs(pixels, width, height, dark_threshold)
    min_vertical_run = max(MIN_VERTICAL_RUN_PX, int(height * MIN_VERTICAL_RUN_RATIO))
    vertical = sum(1 for run in column_runs if run >= min_vertical_run)
    return horizontal >= 2 and vertical >= 2


def _longest_dark_runs(pixels: bytes, width: int, height: int, threshold: int) -> list[int]:
    """逐列计算最长连续暗像素段长度（用于识别表格竖线，不受表格只占图高一部分的影响）。"""
    longest = [0] * width
    current = [0] * width
    for y in range(height):
        offset = y * width
        for x in range(width):
            if pixels[offset + x] < threshold:
                value = current[x] + 1
                current[x] = value
                if value > longest[x]:
                    longest[x] = value
            else:
                current[x] = 0
    return longest


def prepare_ocr_tiles(
    image: Image.Image,
    *,
    limits,
    mode: OCRMode,
    source_width: float | None = None,
    source_height: float | None = None,
) -> list[dict[str, Any]]:
    """把图片编码为符合供应商体积/尺寸/长宽比的有界块，并保留到源页面的 bbox 映射。

    返回项：content（PNG 字节）、bbox（源坐标；整页为 None）、box（像素裁剪框）。
    """
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 1 or height < 1:
        raise ParseError("图片尺寸不合法", code="FILE_CORRUPT")
    source_width = float(source_width or width)
    source_height = float(source_height or height)
    max_tiles = max(1, int(limits.ocr_max_tiles))
    max_bytes = max(1, int(limits.ocr_max_image_bytes))

    for rows, columns in _candidate_grids(max_tiles):
        if rows > height or columns > width:
            continue
        boxes: list[tuple[int, int, int, int]] = []
        for row in range(rows):
            for column in range(columns):
                box = (
                    int(column * width / columns),
                    int(row * height / rows),
                    int((column + 1) * width / columns),
                    int((row + 1) * height / rows),
                )
                tile_width = box[2] - box[0]
                tile_height = box[3] - box[1]
                if tile_width < MIN_PROVIDER_SIDE or tile_height < MIN_PROVIDER_SIDE:
                    boxes = []
                    break
                if tile_width > MAX_PROVIDER_SIDE or tile_height > MAX_PROVIDER_SIDE:
                    boxes = []
                    break
                if mode == "table" and max(tile_width, tile_height) / min(tile_width, tile_height) >= MAX_TABLE_ASPECT:
                    boxes = []
                    break
                boxes.append(box)
            if not boxes:
                break
        if not boxes:
            continue
        tiles: list[dict[str, Any]] = []
        for box in boxes:
            tile = rgb.crop(box)
            buffer = io.BytesIO()
            tile.save(buffer, format="PNG", optimize=False)
            content = buffer.getvalue()
            if len(content) > max_bytes:
                tiles = []
                break
            x_scale = source_width / width
            y_scale = source_height / height
            bbox = (
                box[0] * x_scale,
                box[1] * y_scale,
                box[2] * x_scale,
                box[3] * y_scale,
            )
            tiles.append(
                {
                    "content": content,
                    "bbox": None if len(boxes) == 1 else bbox,
                    "box": box,
                }
            )
        if tiles:
            return tiles
    raise ParseLimitError(
        "图片无法在供应商体积/尺寸限制内形成可识别块",
        code="OCR_IMAGE_TOO_LARGE",
    )


def _candidate_grids(max_tiles: int):
    total = 1
    while total <= max_tiles:
        for rows in range(1, total + 1):
            if total % rows == 0:
                yield rows, total // rows
        total *= 2


def validate_ocr_table(rows: tuple[tuple[str | None, ...], ...]) -> tuple[bool, str, list[str], list[tuple[str | None, ...]]]:
    """校验供应商表格结构；不猜测缺失表头或补齐行列。"""
    if len(rows) < 2:
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
    data_rows = []
    for row in rows[1:]:
        normalized = tuple(None if cell is None or not str(cell).strip() else str(cell).strip() for cell in row)
        if any(value is not None for value in normalized):
            data_rows.append(normalized)
    if not data_rows:
        return False, "表格没有有效数据行", [], []
    return True, "", header, data_rows


# ---------------------------------------------------------------- 图片解析


def parse_image(path: Path, kind: str, services: ParseServices) -> Iterator[ParsedUnit]:
    """解析单张图片；识别失败/无文字/表格结构不可靠都抛出稳定 ParseError。"""
    kind = kind.lower()
    services.page_total = 1
    _begin_report(services, kind)

    try:
        image = _load_image(Path(path), kind, services.limits)
    except ParseError as exc:
        _page_failed(services, exc.code, exc.message)
        raise
    if image_is_near_blank(image):
        reason = "图片几乎为空白，未识别到可用文字"
        _page_failed(services, "OCR_NO_TEXT", reason, source="image_blank")
        raise ParseError(reason, code="OCR_NO_TEXT", retryable=False)

    if services.ocr is None:
        reason = "OCR 未配置，无法识别图片文字"
        _page_failed(services, "OCR_NOT_CONFIGURED", reason)
        raise ParseError(reason, code="OCR_NOT_CONFIGURED", retryable=False)

    mode: OCRMode = "table" if looks_like_rule_table(image) else "text"
    try:
        tiles = prepare_ocr_tiles(image, limits=services.limits, mode=mode)
    except ParseLimitError as exc:
        _page_failed(services, exc.code, exc.message, ocr_mode=mode)
        raise

    results: list[tuple[dict[str, Any], OCRPageResult]] = []
    try:
        for tile in tiles:
            ensure_live(services)
            result = services.ocr.recognize(
                OCRInput(
                    content=tile["content"],
                    mime_type="image/png",
                    page=1,
                    bbox=tile["bbox"],
                ),
                mode=mode,
            )
            ensure_live(services)
            results.append((tile, result))
    except ParseQuotaExceeded:
        raise
    except OCRQuotaUnavailable as exc:
        _page_failed(services, exc.code, "OCR 额度不足，图片识别已暂停", ocr_mode=mode)
        raise ParseQuotaExceeded() from exc
    except OCRError as exc:
        _page_failed(services, exc.code, "图片识别失败", ocr_mode=mode)
        raise ParseError("图片识别失败，未产生确定记录", code=exc.code, retryable=exc.retryable) from exc

    text = "\n".join(item.text for _tile, item in results if item.text.strip())
    request_ids = [item.provider_request_id for _tile, item in results if item.provider_request_id]
    confidence = _combined_confidence([item.confidence for _tile, item in results])
    units: list[ParsedUnit] = []

    if mode == "table":
        rows: list[tuple[str | None, ...]] = []
        for _tile, result in results:
            rows.extend(result.table_rows)
        ok, reason, header, data_rows = validate_ocr_table(tuple(rows))
        if not ok:
            _page_failed(
                services,
                "OCR_TABLE_UNRELIABLE",
                reason,
                ocr_mode=mode,
                request_ids=request_ids,
                confidence=confidence,
            )
            raise ParseError(reason, code="OCR_TABLE_UNRELIABLE", retryable=False)
        for index, row in enumerate(data_rows, start=1):
            fields = {header[column]: row[column] for column in range(len(header))}
            text_value = "；".join(
                f"{header[column]}: {row[column]}" for column in range(len(header)) if row[column] is not None
            )
            units.append(
                ParsedUnit(
                    kind="table_row",
                    locator={"page": 1, "table": 1, "row": index},
                    text=text_value,
                    fields=fields,
                    warnings=[],
                    unit_key=f"table:p1:r{index}",
                )
            )
    else:
        if not text.strip():
            _page_failed(
                services,
                "OCR_NO_TEXT",
                "图片中未识别到可用文字",
                ocr_mode=mode,
                request_ids=request_ids,
                confidence=confidence,
            )
            raise ParseError("图片中未识别到可用文字", code="OCR_NO_TEXT", retryable=False)
        for index, (tile, result) in enumerate(results, start=1):
            if not result.text.strip():
                continue
            locator: dict[str, Any] = {"page": 1}
            if tile["bbox"] is not None:
                locator["bbox"] = list(tile["bbox"])
            units.append(
                ParsedUnit(
                    kind="image_text",
                    locator=locator,
                    text=result.text,
                    fields={},
                    warnings=[],
                    unit_key=f"image_text:p1:t{index}",
                )
            )

    _page_success(
        services,
        mode=mode,
        request_ids=request_ids,
        confidence=confidence,
        units=len(units),
        text=text,
        table_rows=sum(1 for unit in units if unit.kind == "table_row"),
    )
    for unit in units:
        yield unit


def _load_image(path: Path, kind: str, limits) -> Image.Image:
    suffix = kind.lower()
    expected = EXPECTED_FORMAT.get(suffix)
    if expected is None:
        raise ParseError("不支持的图片格式", code="UNSUPPORTED_FILE_TYPE")
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError:
        raise ParseError("图片无法读取", code="FILE_CORRUPT") from None
    if suffix == "png" and not head.startswith(PNG_MAGIC):
        raise ParseError("文件内容不是 PNG", code="INVALID_FILE_TYPE")
    if suffix in {"jpg", "jpeg"} and not head.startswith(JPEG_MAGIC):
        raise ParseError("文件内容不是 JPEG", code="INVALID_FILE_TYPE")
    try:
        with Image.open(path) as image:
            if image.format != expected:
                raise ParseError("图片内容与扩展名不一致", code="INVALID_FILE_TYPE")
            width, height = image.size
            if width <= 0 or height <= 0:
                raise ParseError("图片尺寸不合法", code="FILE_CORRUPT")
            if width * height > limits.image_max_pixels:
                raise ParseLimitError(
                    f"图片像素超过 {limits.image_max_pixels} 上限",
                    code="IMAGE_PIXEL_LIMIT",
                )
            image.verify()
    except ParseError:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        raise ParseError("图片已损坏或无法解码", code="FILE_CORRUPT") from None
    try:
        with Image.open(path) as image:
            return ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        raise ParseError("图片已损坏或无法解码", code="FILE_CORRUPT") from None


# ---------------------------------------------------------------- 报告辅助（图片）


def _begin_report(services: ParseServices, kind: str) -> None:
    services.report.clear()
    services.report.update(
        {
            "kind": kind,
            "total_pages": 1,
            "pages": [],
            "failed_pages": [],
            "blank_pages": [],
            "units": 0,
            "quality": {"complete": False, "issues": []},
        }
    )


def _page_success(
    services: ParseServices,
    *,
    mode: OCRMode,
    request_ids: list[str],
    confidence: float | None,
    units: int,
    text: str,
    table_rows: int,
) -> None:
    services.report["pages"].append(
        {
            "page": 1,
            "source": "ocr",
            "status": "success",
            "ocr_mode": mode,
            "request_ids": request_ids,
            "confidence": confidence,
            "units": units,
            "text_chars": len(text),
            "table_rows": table_rows,
        }
    )
    services.report["units"] = units
    services.report["quality"] = {"complete": True, "issues": []}
    services.pages_done = 1


def _page_failed(
    services: ParseServices,
    code: str,
    reason: str,
    *,
    source: str = "ocr",
    ocr_mode: OCRMode | None = None,
    request_ids: list[str] | None = None,
    confidence: float | None = None,
) -> None:
    services.report["pages"] = [
        {
            "page": 1,
            "source": source,
            "status": "failed",
            "reason": code,
            "message": reason,
            "ocr_mode": ocr_mode,
            "request_ids": list(request_ids or []),
            "confidence": confidence,
        }
    ]
    services.report["failed_pages"] = [1]
    services.report["quality"] = {
        "complete": False,
        "issues": [{"issue": code, "page": 1, "source": source, "message": reason}],
    }
    services.report["units"] = 0
    services.pages_done = 1


def _combined_confidence(values: list[float | None]) -> float | None:
    if not values or any(value is None for value in values):
        return None
    return min(value for value in values if value is not None)
