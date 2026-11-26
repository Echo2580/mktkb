"""v3 语料规范化摘要（双人重算判据，规格 §3.2 降级方案条）。

为什么不能用 zip 字节当唯一判据：OOXML 重新序列化会改 entry 顺序/时间戳/共享字符串分块。
生成器虽然已经把这三项固定（见 03-determinism.json 的 zip_contract），但第三方只要换
openpyxl 小版本就仍可能变字节。因此**必须**另有内容规范化摘要。

规范化方案（写死；第三方照此独立复算即可）：
1. 逐文件按相对路径升序；
2. xlsx：读全部工作表，按「表名顺序」输出
   ``{name, state, max_row, max_col, cells:[[row, col, data_type, text]], merged, col_widths, row_heights}``，
   其中 ``cells`` 覆盖 A1..(max_col,max_row) 整个矩形，空格也输出（``data_type`` + ``""``），
   ``text`` 为 ``str(value)``（None → ""）；``col_widths`` / ``row_heights`` 取 openpyxl 读到的
   显式设置，键排序；
3. 其他类型（docx/pdf）：输出 ``{bytes, sha256}``（这些文件本来就要求逐字节复制）；
4. 整体序列化：``json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))``，
   UTF-8 编码后取 SHA-256 —— 这就是「规范化摘要」。

另给两个派生摘要（复核用，不替代上面那个）：
- ``v3_normalized``：v3 全部 12 个文件的规范化摘要；
- ``original_column_projection``：把 v3 的 6 个 xlsx 裁回 v2 的列数/行数后重算规范化摘要，
  必须与 v2 的对应摘要**逐字相等**（这就是「业务内容没变（除新增列）」的单一字符串证明）。

第三方复算：
    .venv\\Scripts\\python.exe 05-normalized-digest.py --v3 fixtures/acceptance-h2v3 \\
        --v2 fixtures/acceptance --json-only
把打印出的 v3_normalized 与 delivered 里的值逐字比对；相等即内容一致（与 zip 字节无关）。

用法：``.venv\\Scripts\\python.exe 05-normalized-digest.py``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[7]
HERE = Path(__file__).resolve().parent
OUT = HERE / "05-normalized-digest.json"

XLSX_SOURCES = {
    "variants/V03_物品位置表_历史V1.xlsx",
    "normal/D01_物品位置表.xlsx",
    "variants/V04_物品位置表_新版V3.xlsx",
    "variants/V05_物品位置表_新版V3_移除P01.xlsx",
    "normal/D02_合作店家信息.xlsx",
    "variants/V06_合作店家信息_新电话.xlsx",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def workbook_payload(path: Path, *, max_cols: dict | None = None, max_rows: dict | None = None) -> dict:
    workbook = openpyxl.load_workbook(path)
    sheets = []
    for sheet in workbook.worksheets:
        cols = sheet.max_column if not max_cols else min(sheet.max_column, max_cols.get(sheet.title, sheet.max_column))
        rows = sheet.max_row if not max_rows else min(sheet.max_row, max_rows.get(sheet.title, sheet.max_row))
        cells = []
        for row in range(1, rows + 1):
            for col in range(1, cols + 1):
                cell = sheet.cell(row=row, column=col)
                cells.append([row, col, cell.data_type, "" if cell.value is None else str(cell.value)])
        sheets.append(
            {
                "name": sheet.title,
                "state": sheet.sheet_state,
                "max_row": rows,
                "max_col": cols,
                "cells": cells,
                "merged": sorted(str(item) for item in sheet.merged_cells.ranges),
                "col_widths": {key: [value.width, value.customWidth, value.hidden] for key, value in sorted(sheet.column_dimensions.items())},
                "row_heights": {key: [value.height, value.customHeight, value.hidden] for key, value in sorted(sheet.row_dimensions.items())},
            }
        )
    return {"kind": "xlsx", "sheets": sheets}


def file_payload(root: Path, rel: str, *, projection_of: Path | None = None) -> dict:
    path = root / rel
    if rel not in XLSX_SOURCES:
        return {"kind": path.suffix.lower().lstrip("."), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
    if projection_of is None:
        body = workbook_payload(path)
    else:
        reference = openpyxl.load_workbook(projection_of)
        body = workbook_payload(
            path,
            max_cols={sheet.title: sheet.max_column for sheet in reference.worksheets},
            max_rows={sheet.title: sheet.max_row for sheet in reference.worksheets},
        )
    return {"kind": "xlsx", **body}


def digest(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def bundle(root: Path, files: list[str], *, v2_root: Path | None = None) -> dict:
    files_payload = {}
    per_file = {}
    for rel in sorted(files):
        reference = (v2_root / rel) if (v2_root is not None and rel in XLSX_SOURCES) else None
        body = file_payload(root, rel, projection_of=reference)
        files_payload[rel] = body
        per_file[rel] = digest(body)
    return {"digest": digest(files_payload), "per_file": per_file, "files": sorted(files)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v3", default=str(ROOT / "fixtures/acceptance-h2v3"))
    parser.add_argument("--v2", default=str(ROOT / "fixtures/acceptance"))
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args(argv)
    v3_root, v2_root = Path(args.v3), Path(args.v2)
    manifest = json.loads((v3_root / "manifest.json").read_text(encoding="utf-8"))
    files = [item["path"] for item in manifest["normal_files"] + manifest["variants"]]

    v3_full = bundle(v3_root, files)
    v3_projection = bundle(v3_root, files, v2_root=v2_root)
    v2_projection = bundle(v2_root, files, v2_root=v2_root)
    projection_equal = v3_projection["digest"] == v2_projection["digest"]
    per_file_equal = all(v3_projection["per_file"][rel] == v2_projection["per_file"][rel] for rel in files)

    payload = {
        "schema_version": "p2h2v3-normalized-digest/v0.1",
        "phase": "normalized-digest",
        "scheme": {
            "canonical_json": "json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(',', ':'))",
            "hash": "sha256(utf-8 bytes of canonical json)",
            "xlsx": "全部工作表按表名顺序；cells 覆盖 A1..(max_col,max_row) 矩形，空格输出 [row,col,data_type,'']；含 merged/col_widths/row_heights",
            "binary": "docx/pdf 输出 {bytes, sha256}（这些文件要求逐字节复制）",
            "why": "OOXML 重打包必然改 zip 字节；规范化摘要只依赖单元格值与表结构，故可跨实现比对",
        },
        "inputs": {
            "v3_root": str(v3_root),
            "v2_root": str(v2_root),
            "files": files,
            "file_count": len(files),
        },
        "v3_normalized": {
            "digest": v3_full["digest"],
            "per_file": v3_full["per_file"],
        },
        "original_column_projection": {
            "v3_digest": v3_projection["digest"],
            "v2_digest": v2_projection["digest"],
            "equal": projection_equal and per_file_equal,
            "per_file_equal": {rel: v3_projection["per_file"][rel] == v2_projection["per_file"][rel] for rel in files},
        },
        "third_party_recompute": [
            "在同一分支上运行：.venv\\Scripts\\python.exe 05-normalized-digest.py",
            "把输出 v3_normalized.digest 与 05-normalized-digest.json 里 delivered 的值逐字比较",
            "把 original_column_projection.equal 必须为 true（否则说明原有单元格被改）",
            "只比规范化摘要，不要比 zip 字节；zip 字节只作观测记录（03-determinism.json）",
        ],
        "result": "PROJECTION_IDENTICAL" if projection_equal and per_file_equal else "PROJECTION_DIFFERS",
    }
    text = json.dumps(payload, ensure_ascii=True, indent=1)
    OUT.write_text(text + "\n", encoding="ascii", newline="\n")
    print(json.dumps({"v3_normalized_digest": v3_full["digest"],
                      "original_column_projection": payload["original_column_projection"]["equal"],
                      "result": payload["result"]}, ensure_ascii=True, indent=1))
    return 0 if payload["result"] == "PROJECTION_IDENTICAL" else 1


if __name__ == "__main__":
    sys.exit(main())
