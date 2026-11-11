r"""P2-T207 离线清点（零真实调用、零网络、零 OCR）：chunk / embedding 批次。

口径（全部取产品代码，不另立一套）：
- 解析：mktkb.ingestion.parsers.parse_document（本地文件；扫描件/图片需要 OCR 网关，本脚本不解析它们）；
- 分块：mktkb.rag.chunking.build_chunks + RagConfig 默认值（chunk_max_chars=900 / max_units=6 / overlap=1）；
- 批：product_adapter._start_live 的 embedding_batch_size=5，rag/index.py:_embed_chunks 每份资料一次
  embed()，rag/providers.py 按批拆真实 POST ⇒ 批数 = ceil(唯一 chunk 文本数 / 5)。

用法（仓库根）：
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207/evidence/estimate.py            # 快速（fixtures + OCR 三档）
  .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207/evidence/estimate.py --corpus   # 附加 corpus 全量包络（约 3 分钟）
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[6]
sys.path.insert(0, str(REPO / "backend" / "src"))
sys.path.insert(0, str(REPO / "backend" / "tests"))

from mktkb.ingestion.parsers import ParseServices, parse_document  # noqa: E402
from mktkb.rag.chunking import adapt_parsed_unit, build_chunks  # noqa: E402
from mktkb.rag.config import RagConfig  # noqa: E402
from mktkb.rag.types import DocumentSpec  # noqa: E402

BATCH = 5
CONFIG = RagConfig(provider_mode="offline")
NORMAL = REPO / "fixtures" / "acceptance" / "normal"
VARIANTS = REPO / "fixtures" / "acceptance" / "variants"
CORPUS = REPO / "corpus" / "enterprise-20261101"

#: B0 运行真正需要灌进去的文件（C05/C06 的运行另行追加 V01/V02）。
B0_INGEST = [
    ("D01", NORMAL / "D01_物品位置表.xlsx"),
    ("D02", NORMAL / "D02_合作店家信息.xlsx"),
    ("D03", NORMAL / "D03_市场部工作指南.docx"),
    ("D04", NORMAL / "D04_活动策划流程.docx"),
    ("D05", NORMAL / "D05_物料领用规范.pdf"),
    ("D06", NORMAL / "D06_店家资料维护说明.pdf"),
    ("V03", VARIANTS / "V03_物品位置表_历史V1.xlsx"),
    ("V04", VARIANTS / "V04_物品位置表_新版V3.xlsx"),
]
EXTRA_VARIANTS = [
    ("V01", VARIANTS / "V01_临时物料位置通知.pdf"),
    ("V02", VARIANTS / "V02_店家联系方式变更通知.pdf"),
    ("V05", VARIANTS / "V05_物品位置表_新版V3_移除P01.xlsx"),
    ("V06", VARIANTS / "V06_合作店家信息_新电话.xlsx"),
    ("V07", VARIANTS / "V07_物料位置独立通知.pdf"),
]


def spec_for(code: str, rel: str, path: Path) -> DocumentSpec:
    return DocumentSpec(
        doc_id=code, logical_id=code, source_path=rel, title=path.stem,
        file_kind=path.suffix.lower().lstrip("."), version_id=f"{code}-v1",
        version_label="当前", sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def count_file(code: str, path: Path) -> dict:
    rel = str(path.relative_to(REPO)).replace("\\", "/")
    parsed = list(parse_document(path, path.suffix.lower().lstrip("."), ParseServices()))
    spec = spec_for(code, rel, path)
    units = [adapt_parsed_unit(u, doc=spec, unit_id=f"{code}-{i}", ordinal=i) for i, u in enumerate(parsed)]
    chunks = build_chunks(spec, units, CONFIG)
    unique = {c.content_sha256 for c in chunks}
    return {"code": code, "file": rel, "bytes": path.stat().st_size, "units": len(units),
            "chunks": len(chunks), "unique_chunk_texts": len(unique),
            "max_chunk_chars": max((len(c.text) for c in chunks), default=0),
            "batches": math.ceil(len(unique) / BATCH)}


def _fake_unit(kind: str, page: int, text: str):
    return type("U", (), {"kind": kind, "locator": {"page": page}, "text": text,
                          "fields": {}, "warnings": [], "unit_key": f"image_text:p{page}:t1"})()


def count_ocr_pages(code: str, file_kind: str, pages: dict[int, str]) -> dict:
    spec = DocumentSpec(doc_id=code, logical_id=code, source_path=code, title=code,
                        file_kind=file_kind, version_id=f"{code}-v1", version_label="当前",
                        sha256="0" * 64)
    units = [adapt_parsed_unit(_fake_unit("image_text", p, text), doc=spec,
                               unit_id=f"{code}-{i}", ordinal=i)
             for i, (p, text) in enumerate(sorted(pages.items()))]
    chunks = build_chunks(spec, units, CONFIG)
    unique = {c.content_sha256 for c in chunks}
    return {"code": code, "pages": len(pages), "chars": sum(len(t) for t in pages.values()),
            "units": len(units), "chunks": len(chunks), "unique_chunk_texts": len(unique),
            "batches": math.ceil(len(unique) / BATCH)}


def ocr_scenarios() -> dict:
    from acceptance.support import ocr_transcripts as T

    shapes = {"D07": (8, "pdf"), "D08": (2, "pdf"), "D09": (1, "png"), "D10": (1, "jpg")}
    real = [
        count_ocr_pages("D07", "pdf", {p: "\n".join(v) for p, v in T.D07_PAGES.items()}),
        count_ocr_pages("D08", "pdf", {p: "\n".join(v) for p, v in T.D08_PAGES.items()}),
        count_ocr_pages("D09", "png", {1: "\n".join(T.D09_TEXT)}),
        count_ocr_pages("D10", "jpg", {1: "\n".join(T.D10_TEXT)}),
    ]
    out = {"transcript_anchored": real,
           "transcript_total_chars": sum(item["chars"] for item in real),
           "transcript_total_batches": sum(item["batches"] for item in real)}
    for cap in (900, 1800, 2700):
        rows = []
        for code, (pages, kind) in shapes.items():
            texts = {p: " ".join(f"w{p:02d}-{i:04d}" for i in range(cap // 8 + 1))
                     for p in range(1, pages + 1)}
            rows.append(count_ocr_pages(code, kind, texts))
        out[f"cap_{cap}_chars_per_page"] = rows
        out[f"cap_{cap}_total_batches"] = sum(item["batches"] for item in rows)
    return out


def corpus_envelope() -> dict:
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    rows: list[dict] = []
    for entry in manifest["files"]:
        code, kind, rel = entry["code"], entry["kind"], entry["path"]
        if entry.get("group") == "boundary":
            rows.append({"code": code, "skipped": "boundary-sample"})
            continue
        if kind in ("docx_corrupt", "xlsx_corrupt"):
            rows.append({"code": code, "skipped": "corrupt-sample"})
            continue
        if entry.get("ocr_expected") or entry.get("planned_ocr_pages"):
            rows.append({"code": code, "skipped": "ocr-page-sample",
                         "pages": entry.get("pages") or 1})
            continue
        path = CORPUS / rel
        try:
            rows.append(count_file(code, path))
        except Exception as exc:  # noqa: BLE001 - 单份失败不改整体口径
            rows.append({"code": code, "error": type(exc).__name__})
    ok = [r for r in rows if "batches" in r]
    by_code = {r["code"]: r["batches"] for r in ok}
    groups = {"E": [], "W": [], "P": [], "L": [], "X": [], "V": []}
    for code in by_code:
        groups.setdefault(code[0], []).append(code)
    return {
        "files": rows,
        "parsed_documents": len(ok),
        "unique_chunk_texts": sum(r["unique_chunk_texts"] for r in ok),
        "batches": sum(r["batches"] for r in ok),
        "batches_by_code": by_code,
        "batches_by_group": {name: sum(by_code[c] for c in codes)
                             for name, codes in groups.items() if codes},
        "note": ("不含 11 份 boundary 预期失败样本；12 页 OCR（C01–C08）另计，"
                 "见 ocr_scenarios 的上限口径"),
    }


def main(argv: list[str]) -> None:
    b0 = [count_file(code, path) for code, path in B0_INGEST]
    extra = [count_file(code, path) for code, path in EXTRA_VARIANTS]
    payload = {
        "batch_size": BATCH,
        "chunk_config": {"chunk_max_chars": CONFIG.chunk_max_chars,
                         "chunk_max_units": CONFIG.chunk_max_units,
                         "chunk_overlap_units": CONFIG.chunk_overlap_units},
        "b0_ingest_documents": b0,
        "b0_ingest_batches_non_ocr": sum(item["batches"] for item in b0),
        "extra_variant_documents": extra,
        "ocr_scenarios": ocr_scenarios(),
        "plan_ingest_batches": {
            "non_ocr": sum(item["batches"] for item in b0),
            "ocr_at_cap_1800": ocr_scenarios()["cap_1800_total_batches"],
            "ocr_at_cap_2700": ocr_scenarios()["cap_2700_total_batches"],
            "declared_in_plan": 22,
            "formula": "11（fixtures 非 OCR） + 11（12 页 OCR，按 2,700 字/页上限 = 7+2+1+1）",
        },
    }
    if "--corpus" in argv:
        payload["corpus_envelope"] = corpus_envelope()
    print(json.dumps(payload, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
