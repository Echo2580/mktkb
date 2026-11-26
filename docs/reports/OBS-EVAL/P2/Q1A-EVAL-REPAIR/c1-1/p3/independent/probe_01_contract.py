"""C1-P3 独立验收探针 1/6：契约完整性（字段表 / 码表 / 文档一致性）。

不依赖开发测试或开发证据：直接 import 被验收模块，重新生成字段表与码表，
再与契约文档里的表格逐行比对。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = next(
    parent
    for parent in HERE.parents
    if (parent / "backend" / "src" / "mktkb").is_dir() and (parent / "docs").is_dir()
)
DOC = REPO / "docs" / "evaluation" / "p2-hard-evidence-capture-v0_3.md"

sys.path.insert(0, str(HERE))

from mktkb.evaluation import p2_evidence_snapshot_v03 as mod  # noqa: E402


def parse_doc_tables() -> tuple[list[dict[str, str]], list[str], list[str]]:
    text = DOC.read_text(encoding="utf-8")
    field_rows: list[dict[str, str]] = []
    code_rows: list[str] = []
    in_field = False
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("### 4."):
            in_field = True
            in_code = False
            continue
        if stripped.startswith("## 5."):
            in_field = False
            in_code = True
            continue
        if stripped.startswith("## ") and in_code:
            in_code = False
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or set("".join(cells)) <= set("-: "):
            continue
        if cells[0] in {"字段路径", "码族"}:
            continue
        if in_field and len(cells) >= 5:
            # 类型列可能自带 "|"（如 enum(local_mock|live_h2)），按后三列对齐后回并。
            field_rows.append(
                {
                    "path": cells[0].strip("`"),
                    "type": "|".join(cells[1:-3]).strip("`"),
                    "required": cells[-3],
                    "nullable": cells[-2],
                    "missing_code": cells[-1].strip("`"),
                }
            )
        elif in_code and len(cells) == 2:
            code_rows.append(cells[0].strip("`"))
    return field_rows, code_rows, []


def main() -> int:
    rows = mod.identity_field_table()
    doc_fields, doc_codes, _ = parse_doc_tables()
    codes = dict(mod.FAIL_CLOSED_CODES)

    generated = {
        row["path"]: {
            "path": row["path"],
            "type": row["type"],
            "required": "是" if row["required"] else "否",
            "nullable": "是" if row["nullable"] else "否",
            "missing_code": row["missing_code"],
        }
        for row in rows
    }
    doc_map = {row["path"]: row for row in doc_fields}

    missing_in_doc = sorted(set(generated) - set(doc_map))
    extra_in_doc = sorted(set(doc_map) - set(generated))
    mismatched = []
    for path in sorted(set(generated) & set(doc_map)):
        if generated[path] != doc_map[path]:
            mismatched.append({"generated": generated[path], "doc": doc_map[path]})

    code_set = set(codes)
    doc_code_set = set(doc_codes)
    result = {
        "probe": "contract-completeness",
        "field_rows_generated": len(rows),
        "field_rows_doc": len(doc_fields),
        "required_generated": sum(1 for row in rows if row["required"]),
        "nullable_generated": sum(1 for row in rows if row["nullable"]),
        "duplicate_paths": sorted(
            {row["path"] for row in rows if [r["path"] for r in rows].count(row["path"]) > 1}
        ),
        "all_have_missing_code": all(
            row["missing_code"] == f"snapshot_missing_field:{row['path']}" for row in rows
        ),
        "all_have_type": all(bool(row["type"]) for row in rows),
        "field_missing_in_doc": missing_in_doc,
        "field_extra_in_doc": extra_in_doc,
        "field_row_mismatch": mismatched,
        "codes_module": len(code_set),
        "codes_doc": len(doc_codes),
        "doc_code_duplicates": sorted(
            {code for code in doc_codes if doc_codes.count(code) > 1}
        ),
        "codes_missing_in_doc": sorted(code_set - doc_code_set),
        "codes_extra_in_doc": sorted(doc_code_set - code_set),
        "public_summary_keys": len(mod.PUBLIC_SUMMARY_KEYS),
        "use_layers": len(mod.USE_LAYER_NAMES),
        "candidate_layers": len(mod.CANDIDATE_LAYER_NAMES),
        "contract_version": mod.CONTRACT_VERSION,
        "snapshot_schema": mod.SNAPSHOT_SCHEMA_VERSION,
        "manifest_schema": mod.SNAPSHOT_MANIFEST_SCHEMA_VERSION,
        "verdict": None,
    }
    result["verdict"] = "PASS" if (
        len(rows) == 167
        and len(doc_fields) == 167
        and not missing_in_doc
        and not extra_in_doc
        and not mismatched
        and not result["duplicate_paths"]
        and result["all_have_missing_code"]
        and result["all_have_type"]
        and len(code_set) == 49
        and len(doc_codes) == 49
        and not result["codes_missing_in_doc"]
        and not result["codes_extra_in_doc"]
        and not result["doc_code_duplicates"]
        and len(mod.PUBLIC_SUMMARY_KEYS) == 25
    ) else "FAIL"

    out = HERE / "out" / "01-contract.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in result if k not in {"field_row_mismatch"}}, ensure_ascii=False, indent=1))
    if mismatched:
        print("MISMATCH_SAMPLE", json.dumps(mismatched[:3], ensure_ascii=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
