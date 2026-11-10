"""P2-T206-PLAN-R1 离线清点：5 份资料的 chunk/批估算（零真实调用、零网络、零 OCR）。

依据（全部本地只读）：
- 解析：产品解析器 mktkb.ingestion.parsers.parse_document（D09 是 png，必须先有 OCR 网关；
  本脚本不解析 D09，改用产品图片解析器的**确定性结构**推上界）；
- 分块：mktkb.rag.chunking.build_chunks，配置取产品 live 装配的 RagConfig
  （product_adapter.py:_start_live 只覆盖检索参数，分块用默认值
  chunk_max_chars=900 / chunk_max_units=6 / chunk_overlap_units=1）；
- 批：product_adapter.py:1016 的 embedding_batch_size=5，
  rag/index.py:_embed_chunks 每个文档一次 embed()，rag/providers.py:293 按 batch 拆真实 POST。

复跑：.venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T206/PLAN-R1/estimate.py
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]  # docs/reports/OBS-EVAL/P2/T206/PLAN-R1 -> repo root
sys.path.insert(0, str(ROOT / "backend" / "src"))

from PIL import Image  # noqa: E402
from mktkb.ingestion.parsers import ParseServices, parse_document  # noqa: E402
from mktkb.ingestion.parsers.image import (  # noqa: E402
    image_is_near_blank,
    looks_like_rule_table,
    prepare_ocr_tiles,
)
from mktkb.ingestion.parsers.types import ParseLimits  # noqa: E402
from mktkb.rag.chunking import adapt_parsed_unit, build_chunks  # noqa: E402
from mktkb.rag.config import RagConfig  # noqa: E402
from mktkb.rag.types import DocumentSpec  # noqa: E402

BATCH = 5  # product_adapter._start_live: embedding_batch_size=5
CONFIG = RagConfig(provider_mode="offline")  # 分块参数即产品默认值

FILES = (
    ("D01", "fixtures/acceptance/normal/D01_物品位置表.xlsx"),
    ("V03", "fixtures/acceptance/variants/V03_物品位置表_历史V1.xlsx"),
    ("D03", "fixtures/acceptance/normal/D03_市场部工作指南.docx"),
    ("E11", "corpus/enterprise-20261101/excel/E11_终端物料位置表_当前V2.xlsx"),
)


def spec_for(code: str, rel: str, path: Path) -> DocumentSpec:
    return DocumentSpec(
        doc_id=code,
        logical_id=code,
        source_path=rel,
        title=path.stem.split("_", 1)[1] if "_" in path.stem else path.stem,
        file_kind=path.suffix.lower().lstrip("."),
        version_id=f"{code}-v1",
        version_label="当前",
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def count_document(code: str, rel: str) -> dict:
    path = ROOT / rel
    parsed = list(parse_document(path, path.suffix.lower().lstrip("."), ParseServices()))
    spec = spec_for(code, rel, path)
    units = [
        adapt_parsed_unit(unit, doc=spec, unit_id=f"{code}-{ordinal}", ordinal=ordinal)
        for ordinal, unit in enumerate(parsed)
    ]
    chunks = build_chunks(spec, units, CONFIG)
    unique = {chunk.content_sha256 for chunk in chunks}
    return {
        "code": code,
        "file": rel,
        "bytes": path.stat().st_size,
        "units": len(units),
        "unit_kinds": {kind: sum(1 for u in units if u.kind == kind) for kind in sorted({u.kind for u in units})},
        "chunks": len(chunks),
        "unique_chunk_texts": len(unique),
        "max_chunk_chars": max((len(c.text) for c in chunks), default=0),
        "batches": math.ceil(len(unique) / BATCH),
    }


def d09_probe() -> dict:
    """D09 只做结构与几何探测（不解析：解析必然触发 OCR）。"""
    path = ROOT / "fixtures/acceptance/normal/D09_物料领用通知.png"
    with Image.open(path) as image:
        size = image.size
        near_blank = image_is_near_blank(image)
        rule_table = looks_like_rule_table(image)
        rgb = image.convert("RGB")
    tiles_text = prepare_ocr_tiles(rgb, limits=ParseLimits(), mode="text")
    return {
        "file": "fixtures/acceptance/normal/D09_物料领用通知.png",
        "bytes": path.stat().st_size,
        "pixels": {"width": size[0], "height": size[1]},
        "near_blank": near_blank,
        "looks_like_rule_table": rule_table,
        # text 模式 1 tile -> 1 个 image_text unit（image.py 的 parse_image 分支）
        "tiles_text_mode": len(tiles_text),
        "ocr_mode_expected": "table" if rule_table else "text",
    }


def d09_length_sensitivity() -> list[dict]:
    """D09：1 个 image_text unit，块数只由 OCR 文本长度决定（_split_text，900 字/块）。"""
    spec = DocumentSpec(
        doc_id="D09", logical_id="D09",
        source_path="fixtures/acceptance/normal/D09_物料领用通知.png",
        title="物料领用通知", file_kind="png", version_id="D09-v1",
        version_label="当前", sha256="0" * 64,
    )
    rows = []
    for chars in (600, 900, 1500, 2700, 4500, 9000, 13200, 23200):
        unit = adapt_parsed_unit(
            type("U", (), {
                "kind": "image_text", "locator": {"page": 1}, "text": "通" * chars,
                "fields": {}, "warnings": [], "unit_key": "image_text:p1:t1",
            })(),
            doc=spec, unit_id="D09-0", ordinal=0,
        )
        chunks = len(build_chunks(spec, [unit], CONFIG))
        rows.append({"ocr_chars": chars, "chunks": chunks, "batches": math.ceil(chunks / BATCH)})
    return rows


def main() -> None:
    docs = [count_document(code, rel) for code, rel in FILES]
    probe = d09_probe()
    sensitivity = d09_length_sensitivity()
    wk, ht = probe["pixels"]["width"], probe["pixels"]["height"]
    # 几何上界：6x6 px 字形、零行距（实际不可达）-> OCR 文本字数上界
    geo_chars = (wk // 6) * (ht // 6)
    geo_chunks = math.ceil(geo_chars / CONFIG.chunk_max_chars)
    out = {
        "batch_size": BATCH,
        "chunk_config": {
            "chunk_max_chars": CONFIG.chunk_max_chars,
            "chunk_max_units": CONFIG.chunk_max_units,
            "chunk_overlap_units": CONFIG.chunk_overlap_units,
        },
        "documents": docs,
        "measured_totals_4_docs": {
            "units": sum(d["units"] for d in docs),
            "chunks": sum(d["chunks"] for d in docs),
            "unique_chunk_texts": sum(d["unique_chunk_texts"] for d in docs),
            "batches": sum(d["batches"] for d in docs),
        },
        "d09_ocr_probe": probe,
        "d09_length_sensitivity": sensitivity,
        "d09_assumption": {
            "ocr_text_geometric_ceiling_chars": geo_chars,
            "formula": f"floor({wk}/6) * floor({ht}/6)  # 6x6px 字形、零行距",
            "chunks_at_ceiling": geo_chunks,
            "batches_at_ceiling": math.ceil(geo_chunks / BATCH),
            "batches_realistic_1_batch": "OCR 文本 <= 4,500 字（<=5 块）",
        },
        "plan_v0_2_ingest_batches": sum(d["batches"] for d in docs) + math.ceil(geo_chunks / BATCH),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
