"""v3 语料生成器 · 返工 R1（P2-HOLDOUT-v3 corpus，零真实调用）。

R1 相对上一轮的**唯一数据改动**：``失效日期`` 整列为空的 6 个工作簿，改为写**显式哨兵**
``未声明``（11 格 = V05 7 格 + V06 4 格），其余一格不动。

为什么必须有哨兵（经理 2026-11-15 裁定）：
上一轮判 PARTIAL — ``ingestion/parsers/excel.py:112-130 _find_header_index`` 用「下一行
占用列数 >= 本行非空数」加分；``失效日期`` 全列为空时真表头行非空数(7/8) 大于数据行占用数
(6/7)，于是**数据行反超表头**，产品解析出「无 标识 / 无日期」的 unit，7 条 target 不可对齐。
裁定：**暂缓修产品解析器**（冻结 v3 量具，产品修复单独开包），改数据侧用显式哨兵值。

为什么哨兵取 ``未声明`` 而不是 ``长期有效``：
L1 ``null_rule`` 写死「effective_to 为 null 表示**未声明失效日**，语义是 not_asserted，
**绝不等价于『无限有效』**」。写 ``长期有效`` 会让语料**断言一个 L1 明确否认的业务事实**
（人读会以为永不过期），把「未声明」偷换成「无限有效」。``未声明`` 与 L1 的 not_asserted
一一对应，且上一轮已在临时副本上模拟验证过（``../evidence/08-header-detection-finding.json``
的 ``alternative_shape_simulation``，当时用的正是 ``未声明``）。

哨兵语义（写死在规格 §1.4，判据侧不得再解释成别的意思）：
    单元格字面值 ``未声明``  ⇔  L1 ``effective_to = null``（not_asserted）  ⇔  ``_effective_range`` 该侧跳过
``_effective_range`` 语义不变的机制：``_parse_date_text("未声明")`` 无 ``20\\d{2}[-年/]…`` 匹配
⇒ ``_collect_dates(to)`` 为空 ⇒ 返回 ``("range", from, None)``，与留空**逐值相同**
（``p2_hard_evidence.py:1452-1474, 1481-1501``；另见本轮 ``07r1-effective-range-proof.json``）。
产品侧同理：``rag/chunking.py:154-165 effective_dates`` 里 ``parse_date("未声明") → None``。

确定性契约（规格 §3.2，双人重算用；与上一轮逐条相同）：
- 保存后统一重打包：entry 顺序 = v2 原始 zip 顺序；entry 时间戳固定 1980-01-01T00:00:00；
  压缩方式固定 ``ZIP_STORED``（不依赖 zlib 版本）；``create_system=0``、``external_attr=0``；
- ``docProps/core.xml`` 与 ``docProps/app.xml`` 原样取回 v2 字节；
- 日期一律写文本单元格 ``YYYY-MM-DD``（不写 Excel 序列号）。

用法：
    .venv\\Scripts\\python.exe 01r1-build-corpus.py --output fixtures/acceptance-h2v3 --replace-existing
    .venv\\Scripts\\python.exe 01r1-build-corpus.py --output <空临时目录>
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

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[7]
V2_ROOT = ROOT / "fixtures/acceptance"
V2_MANIFEST = V2_ROOT / "manifest.json"
L1_PATH = ROOT / "docs/evaluation/p2-source-lifecycle-v1.json"
DEFAULT_OUTPUT = ROOT / "fixtures/acceptance-h2v3"

DATASET_VERSION = "P2-HOLDOUT-v3"
LABEL_VERSION = "p2-holdout-v3-2026-11-15"
LIFECYCLE_SCHEMA = "p2-source-lifecycle/v1"
CORPUS_MANIFEST_SCHEMA = "p2-acceptance-corpus-manifest/v0.2"

#: R1 哨兵：L1 effective_to = null（not_asserted）在语料里的**唯一**字面值。
EFFECTIVE_TO_SENTINEL = "未声明"

#: 与 ``backend/src/mktkb/retrieval/index.py:39`` 同值；目标表必须是带该表头的表格。
ID_HEADERS = ("标识", "编号", "id", "ID")

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

EXPECTED_OUTPUT_PATHS = frozenset(item["path"] for item in SOURCES) | {"manifest.json"}

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


def locate_table(workbook, spec: dict):
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
    """保住 v2 里「存在但为空」的单元格（openpyxl 保存会丢弃它们，读回类型会退化）。"""
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
    cells_sentinel = 0
    cells_blank = 0
    overridden = []
    written_rows = []
    sentinel_rows = []
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
            # R1：null（not_asserted）→ 显式哨兵，不留空（留空会让表头识别失效）
            sheet.cell(row=row, column=first_new_col + 1, value=EFFECTIVE_TO_SENTINEL)
            cells_sentinel += 1
            sentinel_rows.append({"row": row, "record_code": record_code})
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
        "cells_sentinel_not_asserted": cells_sentinel,
        "cells_blank_not_asserted": cells_blank,
        "sentinel_rows": sentinel_rows,
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
        record["business_version"] = v2_by_id[item["source_id"]].get("business_version")
        if item["source_id"] in ("V01", "V02", "V03", "V04", "V05", "V06", "V07"):
            variants.append(record)
        else:
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
        "value_format": "YYYY-MM-DD 文本单元格（不写 Excel 日期序列号）；effective_to 为 null 时写哨兵 未声明",
        "effective_to_sentinel": {
            "literal": EFFECTIVE_TO_SENTINEL,
            "cell_data_type": "s",
            "maps_to": "L1 effective_to = null（null_semantics = not_asserted）",
            "one_to_one": "哨兵只出现在 L1 effective_to 为 null 的行；L1 为日期时该格必然写日期，二者互斥且穷尽",
            "not_a_date": "不含日期数字，_parse_date_text / chunking.parse_date 均返回 None",
            "why_not_blank": "整列为空会让 ingestion/parsers/excel.py:_find_header_index 选数据行当表头（v3 R0 的 PARTIAL 根因）",
            "why_not_changqi_youxiao": "L1 null_rule 明确 null 不等价于『无限有效』；写『长期有效』等于断言 L1 否认的业务事实",
            "spec_ref": "docs/superpowers/plans/2026-11-15-h2-v3-corpus-modification-spec.md §1.4（R1 修订）",
        },
        "interval_semantics": "closed：[effective_from, effective_to]，两端点均有效",
        "null_semantics": "not_asserted：effective_to 为 null 时写哨兵 未声明（不留空），_effective_range 该侧跳过，语义与留空逐值相同",
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
            "R1：失效日期 为 null（not_asserted）的行改写成哨兵 未声明（11 格），用于恢复产品 _find_header_index 的表头识别；哨兵一律不得被解析成日期。",
        ],
    }
    return manifest


def prepare_output(output: Path, replace_existing: bool) -> None:
    """输出目录守卫：空目录 → 直接用；非空 → 仅当 --replace-existing 且内容恰为 13 个预期路径时覆盖。"""
    if not output.exists() or not any(output.iterdir()):
        return
    if not replace_existing:
        raise SystemExit(f"输出目录非空，拒绝覆盖: {output}（如确为交付件原地重建，加 --replace-existing）")
    present = {str(path.relative_to(output)).replace("\\", "/") for path in sorted(output.rglob("*")) if path.is_file()}
    extra = sorted(present - EXPECTED_OUTPUT_PATHS)
    missing = sorted(EXPECTED_OUTPUT_PATHS - present)
    if extra or missing:
        raise SystemExit(f"交付目录内容与本轮预期不符，拒绝原地覆盖（多 {extra} / 少 {missing}）")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args(argv)
    output = Path(args.output)
    prepare_output(output, args.replace_existing)

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
            applied_sheets.append(
                {
                    "source_id": source["source_id"],
                    "path": source["path"],
                    **{
                        key: stat[key]
                        for key in (
                            "sheet",
                            "header_row",
                            "new_columns",
                            "new_column_letters",
                            "data_rows",
                            "cells_written",
                            "cells_sentinel_not_asserted",
                            "cells_blank_not_asserted",
                            "sentinel_rows",
                            "record_overrides",
                            "empty_typed_cells_restored",
                        )
                    },
                }
            )
            unchanged_sheets.extend({"source_id": source["source_id"], "path": source["path"], "sheet": name} for name in stat["unchanged_sheets"])
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
        "data_cells_sentinel_not_asserted": sum(stat["cells_sentinel_not_asserted"] for stat in applied_sheets),
        "data_cells_left_blank": sum(stat["cells_blank_not_asserted"] for stat in applied_sheets),
        "record_override_rows": len(record_overrides),
        "empty_typed_cells_restored": sum(stat["empty_typed_cells_restored"] for stat in applied_sheets),
        "existing_cells_modified": 0,
    }
    if totals["data_cells_sentinel_not_asserted"] != 11:
        raise SystemExit(f"哨兵格数不是 11: {totals['data_cells_sentinel_not_asserted']}")
    if totals["data_cells_left_blank"] != 0:
        raise SystemExit(f"仍有留空的 失效日期 单元格: {totals['data_cells_left_blank']}")
    stats = {"applied_sheets": applied_sheets, "unchanged_sheets": unchanged_sheets, "record_overrides": sorted(record_overrides), "totals": totals}
    manifest = build_manifest(output, per_file, l1, l1_sha, stats)
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {
        "output": str(output),
        "sentinel": EFFECTIVE_TO_SENTINEL,
        "files": len(per_file),
        "manifest": {"path": str(manifest_path), "bytes": manifest_path.stat().st_size, "sha256": sha256_file(manifest_path)},
        "l1": {"path": "docs/evaluation/p2-source-lifecycle-v1.json", "sha256": l1_sha},
        "totals": totals,
        "per_file": per_file,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
