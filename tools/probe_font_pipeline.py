#!/usr/bin/env python
r"""T01-C1-R1 字体与最小生成链路探针（静态字重版）。

与 C1 的差别：先用 fontTools 从本地 Noto Sans SC 可变字体派生**静态** Regular(400)/Medium(500)，
再由 reportlab 分别嵌入两种静态字体，使 PDF 内嵌字重真实为 400/500；图像样张同样使用静态字体。

验证内容：
  1. 字体身份（name/fvar）、派生字体（无 fvar、usWeightClass、字形轮廓差异、名称）；
  2. 文字 PDF 的两个内嵌子集及其 OS/2.usWeightClass（不是只看 BaseFont 名称）；
  3. 中文可提取性；纯图像扫描 PDF 无文字层；
  4. 4 份样张（text.pdf、scan.pdf、sample.png、table.jpg）与派生字体、渲染图的确定性。

用法：
    .\.venv\Scripts\python.exe -B tools\probe_font_pipeline.py --output docs\evidence\T01\C1-R1\run-a

约束：不访问网络、不安装依赖、只读系统字体；所有时间戳固定，输出目录内自包含。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
import sys
import zlib
from pathlib import Path

DEFAULT_FONT = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")

STATIC_FAMILY = "Noto Sans SC Static"
STATIC_PS_PREFIX = "NotoSansSCStatic"
STATIC_WEIGHTS = {400: "Regular", 500: "Medium"}
FIXED_EPOCH = 3029529600  # 2000-01-01（head 时间基准为 1904-01-01），避免 0 触发 fontTools 时间戳警告

SAMPLE_LINES = [
    "市场部",
    "活动日期 2026-11-05",
    "联系电话 010-00000001",
]
POSITION_LINES = [
    "物品位置：城东店 宣传海报 B区1号货架第二层（模拟）",
    "物品位置：城西店 宣传海报 C区2号货架第一层（模拟）",
]
TABLE_HEADER = ["门店", "物品", "位置"]
TABLE_ROWS = [
    ["城东店", "宣传海报", "B区1号货架第二层"],
    ["城西店", "宣传海报", "C区2号货架第一层"],
]
MARK = "模拟数据／链路验证样张"


# ---------------------------------------------------------------- sfnt / name / fvar


def _read_u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _sfnt_tables(data: bytes) -> dict[str, tuple[int, int]]:
    if data[0:4] == b"ttcf":
        raise SystemExit("unsupported: TTC container, expected a single sfnt font")
    num_tables = _read_u16(data, 4)
    tables: dict[str, tuple[int, int]] = {}
    for index in range(num_tables):
        base = 12 + index * 16
        name = data[base : base + 4].decode("latin-1")
        tables[name] = (_read_u32(data, base + 8), _read_u32(data, base + 12))
    return tables


def _decode_name(platform_id: int, encoding_id: int, raw: bytes) -> str:
    if platform_id in (0, 3):
        return raw.decode("utf-16-be", errors="replace")
    if platform_id == 1 and encoding_id == 0:
        return raw.decode("mac-roman", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _name_records(data: bytes, tables: dict[str, tuple[int, int]]):
    offset, _length = tables["name"]
    count = _read_u16(data, offset + 2)
    string_offset = _read_u16(data, offset + 4)
    for index in range(count):
        rec = offset + 6 + index * 12
        yield {
            "platform": _read_u16(data, rec),
            "encoding": _read_u16(data, rec + 2),
            "language": _read_u16(data, rec + 4),
            "name_id": _read_u16(data, rec + 6),
            "raw": data[
                offset + string_offset + _read_u16(data, rec + 10) :
                offset + string_offset + _read_u16(data, rec + 10) + _read_u16(data, rec + 8)
            ],
        }


def parse_name_table(data: bytes, tables: dict[str, tuple[int, int]]) -> dict[str, str]:
    wanted = {
        0: "copyright",
        1: "family",
        2: "subfamily",
        3: "unique_id",
        4: "full_name",
        5: "version",
        6: "postscript_name",
        13: "license",
        14: "license_url",
        16: "typographic_family",
        17: "typographic_subfamily",
    }
    found: dict[str, tuple[int, str]] = {}
    for record in _name_records(data, tables):
        key = wanted.get(record["name_id"])
        if key is None:
            continue
        text = _decode_name(record["platform"], record["encoding"], record["raw"])
        priority = 2 if record["platform"] == 3 and record["language"] == 0x0409 else 1
        if key not in found or priority > found[key][0]:
            found[key] = (priority, text)
    return {key: value for key, (_priority, value) in found.items()}


def _name_id_text(data: bytes, tables: dict[str, tuple[int, int]], name_id: int) -> str | None:
    for record in _name_records(data, tables):
        if record["name_id"] == name_id:
            return _decode_name(record["platform"], record["encoding"], record["raw"])
    return None


def parse_fvar(data: bytes, tables: dict[str, tuple[int, int]]) -> dict:
    if "fvar" not in tables:
        return {"present": False, "axes": [], "instances": []}
    offset, _length = tables["fvar"]
    axes_offset = _read_u16(data, offset + 4)
    axis_count = _read_u16(data, offset + 8)
    axis_size = _read_u16(data, offset + 10)
    instance_count = _read_u16(data, offset + 12)
    instance_size = _read_u16(data, offset + 14)
    axes = []
    axis_base = offset + axes_offset
    for index in range(axis_count):
        base = axis_base + index * axis_size
        axes.append(
            {
                "tag": data[base : base + 4].decode("latin-1"),
                "min": struct.unpack_from(">i", data, base + 4)[0],
                "default": struct.unpack_from(">i", data, base + 8)[0],
                "max": struct.unpack_from(">i", data, base + 12)[0],
            }
        )
    instances = []
    inst_base = axis_base + axis_count * axis_size
    for index in range(instance_count):
        base = inst_base + index * instance_size
        instances.append(
            {
                "name_id": _read_u16(data, base),
                "name": _name_id_text(data, tables, _read_u16(data, base)),
                "coordinates": [
                    struct.unpack_from(">i", data, base + 4 + axis_index * 4)[0]
                    for axis_index in range(axis_count)
                ],
            }
        )
    return {"present": True, "axes": axes, "instances": instances}


def font_facts(path: Path) -> dict:
    data = path.read_bytes()
    tables = _sfnt_tables(data)
    fvar = parse_fvar(data, tables)
    return {
        "path": str(path),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "tables": sorted(tables),
        "has_fvar": "fvar" in tables,
        "has_gvar": "gvar" in tables,
        "names": parse_name_table(data, tables),
        "fvar": fvar,
    }


def os2_weight(path: Path) -> int | None:
    from fontTools.ttLib import TTFont

    with TTFont(str(path), lazy=False) as font:
        return font["OS/2"].usWeightClass


# ---------------------------------------------------------------- static instancing


def instantiate_static(vf_path: Path, weight: int, out_path: Path) -> dict:
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    style = STATIC_WEIGHTS[weight]
    postscript = f"{STATIC_PS_PREFIX}-{style}"

    source = TTFont(str(vf_path))
    static = instancer.instantiateVariableFont(
        source, {"wght": weight}, inplace=False, updateFontNames=True
    )

    # 显式命名：派生字体主名不使用保留名 Source，并与真实字重一致
    name = static["name"]
    for platform, encoding, language in ((3, 1, 0x409), (1, 0, 0)):
        try:
            name.setName(STATIC_FAMILY, 1, platform, encoding, language)
            name.setName(style, 2, platform, encoding, language)
            name.setName(f"{STATIC_FAMILY} {style}", 4, platform, encoding, language)
            name.setName(postscript, 6, platform, encoding, language)
            name.setName(STATIC_FAMILY, 16, platform, encoding, language)
            name.setName(style, 17, platform, encoding, language)
        except Exception:
            continue
    # 可变字体的 PS 名称前缀记录在静态实例中已无意义
    for name_id in (25,):
        name.removeNames(nameID=name_id)

    static["OS/2"].usWeightClass = weight
    for record in ("head",):
        static[record].created = FIXED_EPOCH
        static[record].modified = FIXED_EPOCH
    # recalcTimestamp=False：否则 save() 会把 head.modified 改回当前时间，破坏字节可复现
    static.recalcTimestamp = False
    static.save(str(out_path))

    facts = font_facts(out_path)
    # 输出目录名不进入结果，保证两个输出目录的 JSON 可比
    facts["path"] = out_path.name
    facts.update(
        {
            "requested_weight": weight,
            "style": style,
            "postscript_name": postscript,
            "os2_usWeightClass": os2_weight(out_path),
            "fvar_removed": not facts["has_fvar"],
        }
    )
    return facts


def glyph_signature(path: Path, char: str) -> dict:
    from fontTools.ttLib import TTFont

    with TTFont(str(path), lazy=False) as font:
        cmap = font.getBestCmap()
        glyph_name = cmap.get(ord(char))
        if glyph_name is None:
            return {"char": char, "found": False}
        glyph = font["glyf"][glyph_name]
        advance, _lsb = font["hmtx"][glyph_name]
        return {
            "char": char,
            "found": True,
            "glyph_name": glyph_name,
            "advance_width": advance,
            "number_of_contours": glyph.numberOfContours,
            "xMin": glyph.xMin,
            "xMax": glyph.xMax,
            "yMin": glyph.yMin,
            "yMax": glyph.yMax,
        }


# ---------------------------------------------------------------- samples


def _pillow_font(font_path: Path, size: int):
    from PIL import ImageFont

    return ImageFont.truetype(str(font_path), size)


def make_text_pdf(path: Path, static_fonts: dict[int, Path]) -> dict:
    from reportlab import rl_config

    rl_config.invariant = 1
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    for weight, font_path in static_fonts.items():
        pdfmetrics.registerFont(TTFont(f"NotoSCStatic-{STATIC_WEIGHTS[weight]}", str(font_path)))

    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(MARK)
    pdf.setAuthor("T01-C1-R1 probe")
    pdf.setSubject("文字PDF静态字重验证（非正式语料）")
    pdf.setCreator("tools/probe_font_pipeline.py")
    pdf.setKeywords("模拟数据,链路验证,T01-C1-R1")

    width, height = A4
    y = height - 70
    pdf.setFont("NotoSCStatic-Medium", 17)
    pdf.drawString(50, y, "市场部 AI 知识库 · 静态字重链路验证样张（模拟数据）")
    y -= 26
    pdf.setFont("NotoSCStatic-Regular", 9)
    pdf.drawString(50, y, MARK + "  |  仅用于解析与字体链路验证，不作为业务事实")

    blocks = (
        (400, "Regular 400", 12),
        (500, "Medium 500", 12),
    )
    for weight, label, size in blocks:
        y -= 36
        pdf.setFont(f"NotoSCStatic-{STATIC_WEIGHTS[weight]}", 11)
        pdf.drawString(50, y, f"【{label}】同一组文字，不同静态字重实例")
        y -= size + 10
        pdf.setFont(f"NotoSCStatic-{STATIC_WEIGHTS[weight]}", size)
        for line in SAMPLE_LINES + POSITION_LINES:
            pdf.drawString(50, y, line)
            y -= size + 10

    y -= 24
    pdf.setFont("NotoSCStatic-Regular", 9)
    pdf.drawString(50, y, "本页使用两个静态字体实例：NotoSansSCStatic-Regular(wght400) 与 NotoSansSCStatic-Medium(wght500)")
    pdf.showPage()
    pdf.save()
    return {"file": path.name, "page_size": "A4", "weights_used": [400, 500]}


def make_scan_pdf(path: Path, static_fonts: dict[int, Path]) -> dict:
    from PIL import Image, ImageDraw

    from reportlab import rl_config

    rl_config.invariant = 1
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    width_px, height_px = 1240, 1754  # A4 @150dpi
    image = Image.new("RGB", (width_px, height_px), "white")
    draw = ImageDraw.Draw(image)
    title_font = _pillow_font(static_fonts[500], 40)
    body_font = _pillow_font(static_fonts[400], 28)
    draw.text((90, 130), "市场部 链路验证扫描样张", font=title_font, fill=(0, 0, 0))
    draw.text((90, 210), "活动日期 2026-11-05", font=body_font, fill=(0, 0, 0))
    draw.text((90, 260), "联系电话 010-00000001", font=body_font, fill=(0, 0, 0))
    draw.text((90, 310), "物品位置：城东店 宣传海报 B区1号货架第二层", font=body_font, fill=(0, 0, 0))
    draw.text((90, 360), MARK, font=body_font, fill=(60, 60, 60))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(MARK)
    pdf.setAuthor("T01-C1-R1 probe")
    pdf.setCreator("tools/probe_font_pipeline.py")
    pdf.drawImage(ImageReader(buffer), 0, 0, width=A4[0], height=A4[1])
    pdf.showPage()
    pdf.save()
    return {"file": path.name, "image_px": [width_px, height_px], "dpi_equivalent": 150, "text_layer": "none (image only)"}


def make_sample_png(path: Path, static_fonts: dict[int, Path]) -> dict:
    from PIL import Image, ImageDraw

    width, height = 1200, 760
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title = _pillow_font(static_fonts[500], 40)
    label = _pillow_font(static_fonts[400], 22)

    draw.text((60, 50), "市场部 AI 知识库 · PNG 静态字重样张", font=title, fill=(0, 0, 0))
    draw.text((60, 110), MARK, font=label, fill=(80, 80, 80))

    for label_text, weight, x in (("Regular 400", 400, 60), ("Medium 500", 500, 620)):
        draw.text((x, 180), label_text, font=label, fill=(90, 90, 90))
        body = _pillow_font(static_fonts[weight], 34)
        y = 220
        for line in ("市场部", "2026-11-05", "010-00000001"):
            draw.text((x, y), line, font=body, fill=(0, 0, 0))
            y += 56
    draw.text((60, 640), "两个静态字体文件：NotoSansSCStatic-Regular / NotoSansSCStatic-Medium（由同一 VF 固定 wght 派生）", font=label, fill=(80, 80, 80))
    draw.text((60, 680), MARK, font=label, fill=(120, 120, 120))
    image.save(path, format="PNG")
    return {"file": path.name, "size_px": [width, height], "weights": ["Regular(400)", "Medium(500)"]}


def make_table_jpg(path: Path, static_fonts: dict[int, Path]) -> dict:
    from PIL import Image, ImageDraw

    width, height = 1200, 620
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    header_font = _pillow_font(static_fonts[500], 26)
    cell_font = _pillow_font(static_fonts[400], 24)
    note_font = _pillow_font(static_fonts[400], 20)

    draw.text((60, 40), "物品位置规则表格 · JPG 样张", font=header_font, fill=(0, 0, 0))
    draw.text((60, 84), MARK, font=note_font, fill=(90, 90, 90))

    left, top = 60, 140
    col_widths = [220, 260, 560]
    row_height = 70
    x = left
    for index, head in enumerate(TABLE_HEADER):
        draw.rectangle([x, top, x + col_widths[index], top + row_height], outline=(0, 0, 0), width=2)
        draw.text((x + 18, top + 20), head, font=header_font, fill=(0, 0, 0))
        x += col_widths[index]
    for row_index, row in enumerate(TABLE_ROWS):
        y = top + row_height * (row_index + 1)
        x = left
        for col_index, value in enumerate(row):
            draw.rectangle([x, y, x + col_widths[col_index], y + row_height], outline=(0, 0, 0), width=2)
            draw.text((x + 18, y + 20), value, font=cell_font, fill=(0, 0, 0))
            x += col_widths[col_index]
    draw.text((60, top + row_height * 3 + 30), "门店/物品/位置取自 B0 的 P01、P02；不含库存、负责人等未记录字段", font=note_font, fill=(90, 90, 90))
    image.save(path, format="JPEG", quality=92, subsampling=0, progressive=False)
    return {"file": path.name, "size_px": [width, height], "rows": len(TABLE_ROWS) + 1}


# ---------------------------------------------------------------- probes


def probe_pdf(path: Path) -> dict:
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""
        chars = page.chars
        font_counts: dict[str, int] = {}
        for char in chars:
            font_counts[char["fontname"]] = font_counts.get(char["fontname"], 0) + 1
        return {
            "pages": len(pdf.pages),
            "text": text,
            "char_count": len(chars),
            "font_counts": font_counts,
            "sizes": sorted({round(char["size"], 2) for char in chars}) if chars else [],
            "has_text_layer": len(chars) > 0,
        }


def embedded_font_facts(path: Path) -> list[dict]:
    """从 PDF 中解出所有 FlateDecode 的 TrueType 字体流，读取其 OS/2 字重与名称。"""
    from fontTools.ttLib import TTFont

    data = path.read_bytes()
    facts: list[dict] = []
    position = 0
    while True:
        marker = data.find(b"stream", position)
        if marker < 0:
            break
        start = marker + len(b"stream")
        if data[start : start + 2] == b"\r\n":
            start += 2
        elif data[start : start + 1] in (b"\n", b"\r"):
            start += 1
        end = data.find(b"endstream", start)
        if end < 0:
            break
        position = end + len(b"endstream")
        raw = data[start:end]
        try:
            decoded = zlib.decompress(raw)
        except Exception:
            continue
        if decoded[:4] not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
            continue
        try:
            with TTFont(io.BytesIO(decoded), lazy=False) as font:
                name = font["name"]
                facts.append(
                    {
                        "bytes": len(decoded),
                        "sha256": hashlib.sha256(decoded).hexdigest(),
                        "os2_usWeightClass": font["OS/2"].usWeightClass,
                        "name_id1": name.getDebugName(1),
                        "name_id2": name.getDebugName(2),
                        "name_id4": name.getDebugName(4),
                        "name_id6": name.getDebugName(6),
                        "has_fvar": "fvar" in font,
                        "has_gvar": "gvar" in font,
                    }
                )
        except Exception as error:  # 解析失败也保留事实
            facts.append({"bytes": len(decoded), "parse_error": f"{type(error).__name__}: {error}"})
    return facts


def render_pdf(path: Path, out_png: Path, scale: float = 2.0) -> dict:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    page = document[0]
    image = page.render(scale=scale).to_pil()
    image.save(out_png, format="PNG")
    return {"file": out_png.name, "size_px": list(image.size), "scale": scale}


def ink_pixels(path: Path, text: str, size: int = 48) -> int:
    from PIL import Image, ImageDraw

    font = _pillow_font(path, size)
    canvas_image = Image.new("L", (900, 120), 255)
    ImageDraw.Draw(canvas_image).text((10, 10), text, font=font, fill=0)
    return sum(1 for value in canvas_image.tobytes() if value < 200)


# ---------------------------------------------------------------- main


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(output: Path, vf_path: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    renders = output / "renders"
    renders.mkdir(exist_ok=True)
    fonts_dir = output / "fonts"
    fonts_dir.mkdir(exist_ok=True)

    static_fonts: dict[int, Path] = {}
    static_facts: dict[str, dict] = {}
    for weight, style in STATIC_WEIGHTS.items():
        target = fonts_dir / f"{STATIC_PS_PREFIX}-{style}.ttf"
        static_facts[str(weight)] = instantiate_static(vf_path, weight, target)
        static_fonts[weight] = target

    outline = {}
    for weight, target in static_fonts.items():
        outline[str(weight)] = {
            char: glyph_signature(target, char) for char in "宣海市"
        }

    text_pdf = output / "text.pdf"
    scan_pdf = output / "scan.pdf"
    sample_png = output / "sample.png"
    table_jpg = output / "table.jpg"

    text_meta = make_text_pdf(text_pdf, static_fonts)
    scan_meta = make_scan_pdf(scan_pdf, static_fonts)
    png_meta = make_sample_png(sample_png, static_fonts)
    jpg_meta = make_table_jpg(table_jpg, static_fonts)

    render_text = render_pdf(text_pdf, renders / "text.pdf.png")
    render_scan = render_pdf(scan_pdf, renders / "scan.pdf.png")

    from PIL import Image

    with Image.open(sample_png) as image:
        png_format, png_size = image.format, image.size
    with Image.open(table_jpg) as image:
        jpg_format, jpg_size = image.format, image.size

    text_probe = probe_pdf(text_pdf)
    return {
        "source_vf": font_facts(vf_path),
        "static_fonts": static_facts,
        "static_outline": outline,
        "static_ink": {
            str(weight): ink_pixels(target, "宣传海报 B区1号货架第二层") for weight, target in static_fonts.items()
        },
        "samples": {
            "text.pdf": text_meta,
            "scan.pdf": scan_meta,
            "sample.png": {**png_meta, "actual_format": png_format, "actual_size": list(png_size)},
            "table.jpg": {**jpg_meta, "actual_format": jpg_format, "actual_size": list(jpg_size)},
        },
        "pdf_text_layer": {"text.pdf": text_probe, "scan.pdf": probe_pdf(scan_pdf)},
        "pdf_embedded_fonts": embedded_font_facts(text_pdf),
        "renders": {"text.pdf.png": render_text, "scan.pdf.png": render_scan},
        "files": {
            name: {"bytes": (output / name).stat().st_size, "sha256": sha256_file(output / name)}
            for name in ("text.pdf", "scan.pdf", "sample.png", "table.jpg")
        },
        "font_files": {
            target.name: {"bytes": target.stat().st_size, "sha256": sha256_file(target)}
            for target in static_fonts.values()
        },
        "render_files": {
            name: {"bytes": (renders / name).stat().st_size, "sha256": sha256_file(renders / name)}
            for name in ("text.pdf.png", "scan.pdf.png")
        },
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover
            pass

    parser = argparse.ArgumentParser(description="T01-C1-R1 static-weight font pipeline probe")
    parser.add_argument("--output", required=True, type=Path, help="输出目录（新建或已存在）")
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT, help="源可变字体路径")
    parser.add_argument("--quiet", action="store_true", help="只输出最终 JSON 到文件")
    args = parser.parse_args(argv)

    if not args.font.is_file():
        print(f"font not found: {args.font}", file=sys.stderr)
        return 2

    facts = build(args.output, args.font)
    report_path = args.output / "probe-result.json"
    report_path.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.quiet:
        print(json.dumps(facts, ensure_ascii=False, indent=2))
    print(f"wrote {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
