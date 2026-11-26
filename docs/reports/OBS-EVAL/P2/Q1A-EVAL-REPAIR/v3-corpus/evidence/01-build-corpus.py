"""v3 语料生成器（P2-HOLDOUT-v3 corpus，零真实调用）。

做什么（只做规格允许的两件事）：
1. 把 v2 的 12 个被 ingest 源复制到新根 ``fixtures/acceptance-h2v3/``；
2. 其中 6 个 xlsx 的目标表各追加 2 列 ``生效日期`` / ``失效日期``，值逐个抄 L1
   （``docs/evaluation/p2-source-lifecycle-v1.json``：``sources[]`` 版本窗口，
   ``records[]`` 记录级覆盖），其余单元格一格不动；6 个 docx/pdf 逐字节复制。

不做：不读题面/答案/密文/密钥/.env；不联网；不改 fixtures/acceptance/**；
不 stage/commit。

确定性契约（规格 §3.2，双人重算用）：
- 保存后统一重打包：entry 顺序 = v2 原始 zip 顺序；entry 时间戳固定 1980-01-01T00:00:00；
  压缩方式固定 ``ZIP_STORED``（不依赖 zlib 版本）；``create_system=0``、``external_attr=0``；
- ``docProps/core.xml`` 与 ``docProps/app.xml`` 原样取回 v2 字节（openpyxl 会把
  ``dcterms:modified`` 改成当前时间，取回即消除时间戳漂移）；
- 日期一律写文本单元格 ``YYYY-MM-DD``（不写 Excel 序列号）；``effective_to = null``
  时留空单元格（不写 "null"/"9999-12-31"/"长期有效"）。

用法：
    .venv\\Scripts\\python.exe 01-build-corpus.py --output fixtures/acceptance-h2v3
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[7]
V2_ROOT = ROOT / "fixtures/acceptance"
V2_MANIFEST = V2_ROOT / "manifest.json"
L1_PATH = ROOT / "docs/evaluation/p2-source-lifecycle-v1.json"
DEFAULT_OUTPUT = ROOT / "fixtures/acceptance-h2v3"

DATASET_VERSION = "P2-HOLDOUT-v3"
LABEL_VERSION = "p2-holdout-v3-2026-11-15"
LIFECYCLE_SCHEMA = "p2-source-lifecycle/v1"
CORPUS_MANIFEST_SCHEMA = "p2-acceptance-corpus-manifest/v0.2"

#: 与 ``backend/src/mktkb/retrieval/index.py:39`` 同值；目标表必须是带该表头的表格。
ID_HEADERS = ("标识", "编号", "id", "ID")

#: 目标表定义：只用「表名 + 表头行 + 原表头逐字」来定位，不用行号猜业务事实。
SHEETS = {
    "D01": {
        "sheet": "物品位置",
        "header_row": 7,
        "orig_headers": ("标识", "门店", "物品", "别名", "位置"),
        "new_headers": ("生效日期", "失效日期"),
    },
    "D02": {
        "sheet": "店家信息",
        "header_row": 4,
        "orig_headers": ("标识", "店家", "联系人", "电话", "地址", "合作状态"),
        "new_headers": ("生效日期", "失效日期"),
    },
}

#: 12 个被 ingest 源（顺序 = T207 ingest plan 下标 0..11）。
SOURCES = (
    {"index": 0, "source_id": "V03", "doc_code": "D01", "version_number": 1, "path": "variants/V03_物品位置表_历史V1.xlsx", "kind": "xlsx"},
    {"index": 1, "source_id": "D01", "doc_code": "D01", "version_number": 2, "path": "normal/D01_物品位置表.xlsx", "kind": "xlsx"},
    {"index": 2, "source_id": "V04", "doc_code": "D01", "version_number": 3, "path": "variants/V04_物品位置表_新版V3.xlsx", "kind": "xlsx"},
    {"index": 3, "source_id": "V05", "doc_code": "D01", "version_number": 4, "path": "variants/V05_物品位置表_新版V3_移除P01.xlsx", "kind": "xlsx"},
    {"index": 4, "source_id": "D02", "doc_code": "D02", "version_number": 1, "path": "normal/D02_合作店家信息.xlsx", "kind": "xlsx"},
    {"index": 5, "source_id": "V06", "doc_code": "D02", "version_number": 2, "path": "variants/V06_合作店家信息_新电话.xlsx", "kind": "xlsx"},
    {"index": 6, "source_id": "D03", "doc_code": "D03", "version_number": 1, "path": "normal/D03_市场部工作指南.docx", "kind": "docx"},
    {"index": 7, "source_id": "D04", "doc_code": "D04", "version_number": 1, "path": "normal/D04_活动策划流程.docx", "kind": "docx"},
    {"index": 8, "source_id": "D05", "doc_code": "D05", "version_number": 1, "path": "normal/D05_物料领用规范.pdf", "kind": "pdf-text"},
    {"index": 9, "source_id": "D06", "doc_code": "D06", "version_number": 1, "path": "normal/D06_店家资料维护说明.pdf", "kind": "pdf-text"},
    {"index": 10, "source_id": "V01", "doc_code": "V01", "version_number": 1, "path": "variants/V01_临时物料位置通知.pdf", "kind": "pdf-text"},
    {"index": 11, "source_id": "V07", "doc_code": "V07", "version_number": 1, "path": "variants/V07_物料位置独立通知.pdf", "kind": "pdf-text"},
)

PRESERVE_FROM_SOURCE = ("docProps/core.xml", "docProps/app.xml")
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_l1() -> dict:
    payload = json.loads(L1_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == LIFECYCLE_SCHEMA, payload["schema_version"]
    assert payload["interval"] == "closed", payload["interval"]
    assert payload["declaration"]["kind"] == "design_fixture", payload["declaration"]["kind"]
    return payload


def windows_from_l1(l1: dict) -> tuple[dict, dict]:
    versions = {
        (row["doc_code"], int(row["version_number"])): {
            "source_id": row["source_id"],
            "effective_from": row["effective_from"],
            "effective_to": row["effective_to"],
        }
        for row in l1["sources"]
    }
    records = {
        (row["doc_code"], int(row["version_number"]), row["record_code"]): {
            "effective_from": row["effective_from"],
            "effective_to": row["effective_to"],
        }
        for row in l1["records"]
    }
    return versions, records


def locate_table(workbook, spec: dict) -> tuple[object, int]:
    """按「表名 + 表头逐字相等」定位目标表，不做行号猜测。"""
    sheet = workbook[spec["sheet"]]
    header_row = spec["header_row"]
    got = tuple(sheet.cell(row=header_row, column=col).value for col in range(1, len(spec["orig_headers"]) + 1))
    if got != spec["orig_headers"]:
        raise SystemExit(f"目标表 {spec['sheet']}!{header_row} 原表头不符: {got!r}")
    if got[0] not in ID_HEADERS:
        raise SystemExit(f"目标表 {spec['sheet']} 首列不是 ID_HEADERS: {got[0]!r}")
    return sheet, header_row


def preserve_empty_typed_cells(workbook) -> int:
    """保住 v2 里「存在但为空」的单元格。

    openpyxl 保存时会丢弃 value is None 的单元格（哪怕原 XML 里它是
    ``<c r="D12" t="inlineStr"/>``），读回后该位置就会从 ``inlineStr`` 退化成
    ``n``。规格 §3.1 要求原列投影矩阵「逐格 (值, 值类型) 全等」，因此把这些位置
    重新物化为空串：写盘后读回仍是「值 None、类型 inlineStr」，与原文件一致。
    """
    restored = 0
    for sheet in workbook.worksheets:
        for row in range(1, sheet.max_row + 1):
            for col in range(1, sheet.max_column + 1):
                cell = sheet.cell(row=row, column=col)
                if cell.value is None and cell.data_type != "n":
                    cell.value = ""
                    restored += 1
    return restored


def rewrite_workbook(src: Path, dst: Path, doc_code: str, version: int, versions: dict, records: dict) -> dict:
    """加两列并确定性重打包；返回本文件的加列统计。"""
    spec = SHEETS[doc_code]
    version_window = versions[(doc_code, version)]
    workbook = openpyxl.load_workbook(src)
    empty_cells_restored = preserve_empty_typed_cells(workbook)
    sheet, header_row = locate_table(workbook, spec)
    first_new_col = len(spec["orig_headers"]) + 1
    for offset, header in enumerate(spec["new_headers"]):
        sheet.cell(row=header_row, column=first_new_col + offset, value=header)

    data_rows = 0
    cells_written = 0
    cells_blank = 0
    overridden = []
    written_rows = []
    for row in range(header_row + 1, sheet.max_row + 1):
        record_code = sheet.cell(row=row, column=1).value
        if record_code in (None, ""):
            continue
        record_code = str(record_code).strip()
        window = records.get((doc_code, version, record_code), version_window)
        if (doc_code, version, record_code) in records:
            overridden.append(record_code)
        effective_from = window["effective_from"]
        effective_to = window["effective_to"]
        if not isinstance(effective_from, str) or len(effective_from) != 10:
            raise SystemExit(f"{doc_code} v{version} {record_code} effective_from 非 YYYY-MM-DD: {effective_from!r}")
        if effective_to is not None and (not isinstance(effective_to, str) or len(effective_to) != 10):
            raise SystemExit(f"{doc_code} v{version} {record_code} effective_to 非 YYYY-MM-DD: {effective_to!r}")
        sheet.cell(row=row, column=first_new_col, value=effective_from)
        cells_written += 1
        if effective_to is None:
            cells_blank += 1
        else:
            sheet.cell(row=row, column=first_new_col + 1, value=effective_to)
            cells_written += 1
        data_rows += 1
        written_rows.append({"row": row, "record_code": record_code, "effective_from": effective_from, "effective_to": effective_to})

    buffer = io.BytesIO()
    workbook.save(buffer)
    payload = buffer.getvalue()
    written = repack_deterministic(payload, src, dst)
    unchanged_sheets = [name for name in workbook.sheetnames if name != spec["sheet"]]
    return {
        "sheet": spec["sheet"],
        "header_row": header_row,
        "new_columns": list(spec["new_headers"]),
        "new_column_letters": [openpyxl.utils.get_column_letter(first_new_col), openpyxl.utils.get_column_letter(first_new_col + 1)],
        "version_window": {"effective_from": version_window["effective_from"], "effective_to": version_window["effective_to"]},
        "data_rows": data_rows,
        "cells_written": cells_written,
        "cells_blank_not_asserted": cells_blank,
        "record_overrides": sorted(overridden),
        "rows": written_rows,
        "unchanged_sheets": unchanged_sheets,
        "empty_typed_cells_restored": empty_cells_restored,
        "repacked_bytes": written,
    }


def repack_deterministic(payload: bytes, original: Path, dst: Path) -> int:
    """固定 entry 顺序/时间戳/压缩方式重打包；docProps 取回原字节。"""
    with zipfile.ZipFile(io.BytesIO(payload)) as fresh, zipfile.ZipFile(original) as source:
        order = source.namelist()
        if sorted(order) != sorted(fresh.namelist()):
            raise SystemExit(
                f"{original.name}: openpyxl 产物 entry 集合与原始不同 "
                f"(仅原始 {sorted(set(order) - set(fresh.namelist()))}, 仅产物 {sorted(set(fresh.namelist()) - set(order))})"
            )
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:
            for name in order:
                data = source.read(name) if name in PRESERVE_FROM_SOURCE else fresh.read(name)
                info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 0
                info.external_attr = 0
                archive.writestr(info, data)
    data = out.getvalue()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    return len(data)


def build_manifest(output: Path, per_file: list, l1: dict, l1_sha: str, stats: dict) -> dict:
    v2 = json.loads(V2_MANIFEST.read_text(encoding="utf-8"))
    v2_by_id = {item["id"]: item for item in v2["normal_files"] + v2["variants"]}
    normal = []
    variants = []
    for item in per_file:
        record = {
            "id": item["source_id"],
            "path": item["path"],
            "kind": item["kind"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
            "bytes_unchanged": item["bytes_unchanged"],
            "ingest_index": item["index"],
            "base_doc_code": item["doc_code"],
            "version_number": item["version_number"],
            "effective_from": item["effective_from"],
            "effective_to": item["effective_to"],
            "v2_source_sha256": v2_by_id[item["source_id"]]["sha256"],
        }
        if item["source_id"] in ("V01", "V02", "V03", "V04", "V05", "V06", "V07"):
            record["business_version"] = v2_by_id[item["source_id"]].get("business_version")
            variants.append(record)
        else:
            record["business_version"] = v2_by_id[item["source_id"]].get("business_version")
            normal.append(record)

    lifecycle = {
        "source_of_truth": {
            "path": "docs/evaluation/p2-source-lifecycle-v1.json",
            "sha256": l1_sha,
            "schema_version": LIFECYCLE_SCHEMA,
            "interval": l1["interval"],
            "declaration_kind": l1["declaration"]["kind"],
            "business_date_anchor": l1["business_date_anchor"],
        },
        "columns": {
            "effective_from": {"header": "生效日期", "position": "first_new_column"},
            "effective_to": {"header": "失效日期", "position": "second_new_column"},
        },
        "value_format": "YYYY-MM-DD 文本单元格（不写 Excel 日期序列号）",
        "interval_semantics": "closed：[effective_from, effective_to]，两端点均有效",
        "null_semantics": "not_asserted：effective_to 为 null 时该单元格留空，不写 null/9999-12-31/长期有效",
        "applied_sheets": stats["applied_sheets"],
        "unchanged_sheets": stats["unchanged_sheets"],
        "records_overrides": stats["record_overrides"],
        "totals": stats["totals"],
    }

    manifest = {
        "schema_version": CORPUS_MANIFEST_SCHEMA,
        "root": ".",
        "dataset_version": DATASET_VERSION,
        "label_version": LABEL_VERSION,
        "built_at": v2["built_at"],
        "lifecycle_ref": {
            "path": "docs/evaluation/p2-source-lifecycle-v1.json",
            "sha256": l1_sha,
            "schema_version": LIFECYCLE_SCHEMA,
        },
        "lifecycle": lifecycle,
        "font": v2["font"],
        "normal_files": normal,
        "variants": variants,
        "records": v2["records"],
        "sources": v2["sources"],
        "questions_file": None,
        "corpus_notes": [
            "本根只含 12 个被 ingest 的源 + 本 manifest；D07-D10、V02、A01-A08、B01-B08、font-license/ 按规格 §1.1 不复制。",
            "font 块逐值沿用 v2（源字体身份与许可为构建事实）；font-license/OFL.txt 不随语料复制，许可副本仍在 fixtures/acceptance/font-license/OFL.txt。",
            "questions_file 为 null：H2 题面/答案属私有件，不落在语料根；v2 questions.json 是另一套 64 题公共集，未复制。",
            "records / sources 逐值等于 v2 manifest（记录身份与表/行定位不变）；built_at 仍 2026-10-27，作为『端点撞页眉常量即拒收』的可检测锚点。",
            "b0_initialization 与 boundary 两块按规格 §4.4 未收入：前者引用未复制的 D07-D10，后者是单文件边界样本集，均非 ingest 源。",
        ],
    }
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"输出目录非空，拒绝覆盖: {output}")

    l1 = load_l1()
    l1_sha = sha256_file(L1_PATH)
    versions, records = windows_from_l1(l1)
    v2_manifest = json.loads(V2_MANIFEST.read_text(encoding="utf-8"))
    v2_sha = {item["id"]: item["sha256"] for item in v2_manifest["normal_files"] + v2_manifest["variants"]}

    per_file = []
    applied_sheets = []
    unchanged_sheets = []
    record_overrides = set()
    for source in SOURCES:
        src = V2_ROOT / source["path"]
        if sha256_file(src) != v2_sha[source["source_id"]]:
            raise SystemExit(f"v2 源已被改动，拒绝据此生成: {source['path']}")
        dst = output / source["path"]
        window = versions[(source["doc_code"], source["version_number"])]
        entry = {
            "index": source["index"],
            "source_id": source["source_id"],
            "doc_code": source["doc_code"],
            "version_number": source["version_number"],
            "path": source["path"],
            "kind": source["kind"],
            "effective_from": window["effective_from"],
            "effective_to": window["effective_to"],
            "bytes_unchanged": source["kind"] in ("docx", "pdf-text"),
        }
        if source["kind"] == "xlsx":
            stat = rewrite_workbook(src, dst, source["doc_code"], source["version_number"], versions, records)
            entry["bytes"] = stat["repacked_bytes"]
            entry["sha256"] = sha256_file(dst)
            applied_sheets.append({"source_id": source["source_id"], "path": source["path"], **{k: stat[k] for k in ("sheet", "header_row", "new_columns", "new_column_letters", "data_rows", "cells_written", "cells_blank_not_asserted", "record_overrides", "empty_typed_cells_restored")}})
            unchanged_sheets.extend(
                {"source_id": source["source_id"], "path": source["path"], "sheet": name} for name in stat["unchanged_sheets"]
            )
            record_overrides.update(stat["record_overrides"])
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            if sha256_file(dst) != v2_sha[source["source_id"]]:
                raise SystemExit(f"字节复制后 SHA 不等: {source['path']}")
            entry["bytes"] = dst.stat().st_size
            entry["sha256"] = sha256_file(dst)
        per_file.append(entry)

    totals = {
        "corpus_files": len(per_file),
        "xlsx_modified": sum(1 for entry in per_file if entry["kind"] == "xlsx"),
        "bytes_unchanged": sum(1 for entry in per_file if entry["bytes_unchanged"]),
        "applied_sheets": len(applied_sheets),
        "unchanged_sheets": len(unchanged_sheets),
        "header_cells_added": 2 * len(applied_sheets),
        "data_rows_touched": sum(stat["data_rows"] for stat in applied_sheets),
        "data_cells_written": sum(stat["cells_written"] for stat in applied_sheets),
        "data_cells_left_blank": sum(stat["cells_blank_not_asserted"] for stat in applied_sheets),
        "record_override_rows": len(record_overrides),
        "empty_typed_cells_restored": sum(stat["empty_typed_cells_restored"] for stat in applied_sheets),
        "existing_cells_modified": 0,
    }
    stats = {"applied_sheets": applied_sheets, "unchanged_sheets": unchanged_sheets, "record_overrides": sorted(record_overrides), "totals": totals}
    manifest = build_manifest(output, per_file, l1, l1_sha, stats)
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {
        "output": str(output),
        "files": len(per_file),
        "manifest": {"path": str(manifest_path), "bytes": manifest_path.stat().st_size, "sha256": sha256_file(manifest_path)},
        "totals": totals,
        "per_file": per_file,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
