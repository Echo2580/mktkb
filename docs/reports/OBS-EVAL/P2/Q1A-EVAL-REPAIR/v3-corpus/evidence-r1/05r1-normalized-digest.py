"""v3 语料返工 R1：规范化摘要（双人重算判据 + 「原列投影 v3 == v2」证明）。

规范化方案**逐字沿用上一轮**（``../evidence/05-normalized-digest.py`` 的 scheme，不换算法，
否则跨轮不可比）：

1. 逐文件按相对路径升序；
2. xlsx：读全部工作表，按「表名顺序」输出
   ``{name, state, max_row, max_col, cells:[[row, col, data_type, text]], merged, col_widths, row_heights}``，
   ``cells`` 覆盖 A1..(max_col,max_row) 整个矩形（空格也输出），``text`` 为 ``str(value)``；
3. docx/pdf：输出 ``{bytes, sha256}``；
4. 整体 ``json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))`` → SHA-256。

两个摘要：
- ``v3_normalized``：v3 全部 12 个文件的规范化摘要 —— **R1 必然变**（11 格由空变哨兵）；
- ``original_column_projection``：把 v3 的 6 个 xlsx 裁回 v2 的列数/行数后重算，
  必须与 v2 的对应摘要**逐字相等** —— 这就是「除新增两列外业务内容没变」的单一字符串证明。
  哨兵只落在第 2 新列，故裁掉新列后它根本不参与比较；R1 这一项**必须仍为 equal true**。

跨轮对照写在 ``cross_round``：读上一轮的 ``05-normalized-digest.json``，比
``v2_digest``（必须相等，v2 语料只读）与两个 ``v3 digest``（必须不等，因为哨兵是新增内容）。

零真实调用。
用法：``.venv\\Scripts\\python.exe 05r1-normalized-digest.py``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[7]
OUT = HERE / "05r1-normalized-digest.json"
R0_DIGEST = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-corpus/evidence/05-normalized-digest.json"

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
    args = parser.parse_args(argv)
    v3_root, v2_root = Path(args.v3), Path(args.v2)
    manifest = json.loads((v3_root / "manifest.json").read_text(encoding="utf-8"))
    files = [item["path"] for item in manifest["normal_files"] + manifest["variants"]]

    v3_full = bundle(v3_root, files)
    v3_projection = bundle(v3_root, files, v2_root=v2_root)
    v2_projection = bundle(v2_root, files, v2_root=v2_root)
    projection_equal = v3_projection["digest"] == v2_projection["digest"]
    per_file_equal = all(v3_projection["per_file"][rel] == v2_projection["per_file"][rel] for rel in files)

    r0 = json.loads(R0_DIGEST.read_text(encoding="utf-8"))
    cross_round = {
        "r0_evidence": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-corpus/evidence/05-normalized-digest.json",
        "r0_v3_normalized_digest": r0["v3_normalized"]["digest"],
        "r1_v3_normalized_digest": v3_full["digest"],
        "v3_digest_changed_as_expected": r0["v3_normalized"]["digest"] != v3_full["digest"],
        "r0_v2_projection_digest": r0["original_column_projection"]["v2_digest"],
        "r1_v2_projection_digest": v2_projection["digest"],
        "v2_projection_digest_stable": r0["original_column_projection"]["v2_digest"] == v2_projection["digest"],
        "why_v3_digest_must_change": "规范化摘要把 全部单元格（含新列、含空格）纳入；11 个 失效日期 格由空变为哨兵 未声明，故整份摘要必变",
        "why_projection_must_not_change": "原列投影把 v3 裁回 v2 的 max_col/max_row；哨兵只落在第 2 新列，被裁掉后不参与比较 ⇒ 投影摘要必须仍与 v2 逐字相等",
    }

    payload = {
        "schema_version": "p2h2v3-normalized-digest/v0.1",
        "phase": "normalized-digest-r1",
        "scheme": {
            "canonical_json": "json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(',', ':'))",
            "hash": "sha256(utf-8 bytes of canonical json)",
            "xlsx": "全部工作表按表名顺序；cells 覆盖 A1..(max_col,max_row) 矩形，空格输出 [row,col,data_type,'']；含 merged/col_widths/row_heights",
            "binary": "docx/pdf 输出 {bytes, sha256}（这些文件要求逐字节复制）",
            "unchanged_from_r0": True,
            "why": "跨轮必须可比，故算法逐字沿用上一轮，不换实现",
        },
        "inputs": {"v3_root": str(v3_root), "v2_root": str(v2_root), "files": files, "file_count": len(files)},
        "sentinel": {"literal": "未声明", "data_cells": 11, "spec_ref": "docs/superpowers/plans/2026-11-15-h2-v3-corpus-modification-spec.md §1.5"},
        "v3_normalized": {"digest": v3_full["digest"], "per_file": v3_full["per_file"]},
        "original_column_projection": {
            "v3_digest": v3_projection["digest"],
            "v2_digest": v2_projection["digest"],
            "equal": projection_equal and per_file_equal,
            "per_file_equal": {rel: v3_projection["per_file"][rel] == v2_projection["per_file"][rel] for rel in files},
        },
        "cross_round": cross_round,
        "third_party_recompute": [
            "在同一分支上运行：.venv\\Scripts\\python.exe 05r1-normalized-digest.py",
            "把输出 v3_normalized.digest 与 05r1-normalized-digest.json 里的值逐字比较",
            "把 original_column_projection.equal 必须为 true（否则说明原有单元格被改）",
            "只比规范化摘要，不要比 zip 字节；zip 字节只作观测记录（03r1-determinism.json）",
        ],
        "result": "PROJECTION_IDENTICAL" if projection_equal and per_file_equal else "PROJECTION_DIFFERS",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=True, indent=1) + "\n", encoding="ascii", newline="\n")
    print(
        json.dumps(
            {
                "v3_normalized_digest": v3_full["digest"],
                "original_column_projection_equal": payload["original_column_projection"]["equal"],
                "v2_projection_digest": v2_projection["digest"],
                "cross_round": {k: cross_round[k] for k in ("v3_digest_changed_as_expected", "v2_projection_digest_stable")},
                "result": payload["result"],
            },
            ensure_ascii=True,
            indent=1,
        )
    )
    return 0 if payload["result"] == "PROJECTION_IDENTICAL" and cross_round["v3_digest_changed_as_expected"] else 1


if __name__ == "__main__":
    sys.exit(main())
