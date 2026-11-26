"""v3 语料返工 R1：表头恢复 + ``_effective_range`` 语义不变的**函数级**证明。

三件事，全部跑冻结分类器的**真实函数**，不重写规则：

**一、表头恢复**
用真实 ``parse_document`` 解析 6 个 xlsx，取 ``report.sheets[].header_row``，与规格 §1.2 声明的
表头行逐项相等。并读上一轮 ``../evidence/08-header-detection-finding.json`` 里 R0 的实测值，
证明 V05 8→7、V06 5→4。

**二、`_effective_range` 逐 unit 不变（本轮最关键的语义判据）**
对每个 unit 造两份 ``raw_fields``：
  (a) 现状（``失效日期`` = 哨兵 ``未声明``）；
  (b) 掩回 R0 形态（``失效日期`` = ``None``）—— 解析器对每个表头都写 ``fields[name] = value``
      （``excel.py:319-325``），所以 R0 的留空格在 fields 里就是 ``None``，这是**真实**的 R0 形态，
      不是猜的。
然后调 ``mktkb.evaluation.p2_hard_evidence._effective_range`` 对两份各求一次三元组，要求
**逐 unit 逐值相等**。另外再测 ``""`` 与「键缺失」两种退形态，要求同样相等（稳健性）。

**三、哨兵不会被解析成日期**
``_parse_date_text("未声明") is None``；``rag.chunking.parse_date("未声明") is None``；
``rag.chunking.effective_dates`` 对 (a)(b) 两份返回同值；``_collect_dates(fields, EFFECTIVE_TO_KEYS)``
对哨兵 unit 为空列表（即 ``to`` 侧被跳过，而不是被解析成一个具体日期）。

零真实调用；只读本地文件 + 纯函数。
用法：``.venv\\Scripts\\python.exe 07r1-effective-range-proof.py``
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[7]
V3_ROOT = ROOT / "fixtures/acceptance-h2v3"
R0_FINDING = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-corpus/evidence/08-header-detection-finding.json"
OUT = HERE / "07r1-effective-range-proof.json"

sys.path.insert(0, str(ROOT / "backend/src"))

from mktkb.evaluation import p2_hard_evidence as he  # noqa: E402
from mktkb.ingestion.parsers import ParseServices, parse_document  # noqa: E402
from mktkb.rag import chunking  # noqa: E402

SENTINEL = "未声明"

TARGET_SHEET_NAME = {"V03": "物品位置", "D01": "物品位置", "V04": "物品位置", "V05": "物品位置", "D02": "店家信息", "V06": "店家信息"}
DECLARED_HEADER_ROWS = {"V03": 7, "D01": 7, "V04": 7, "V05": 7, "D02": 4, "V06": 4}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def variants(fields: dict) -> dict[str, dict]:
    """同一 unit 的四种 ``失效日期`` 形态：现状 / R0 的 None / 空串 / 键缺失。"""
    as_is = dict(fields)
    as_none = dict(fields)
    as_none["失效日期"] = None
    as_empty = dict(fields)
    as_empty["失效日期"] = ""
    as_absent = {key: value for key, value in fields.items() if key != "失效日期"}
    return {"sentinel": as_is, "r0_none": as_none, "empty": as_empty, "absent": as_absent}


def main() -> int:
    manifest = json.loads((V3_ROOT / "manifest.json").read_text(encoding="utf-8"))
    path_by_source = {item["id"]: item["path"] for item in manifest["normal_files"] + manifest["variants"]}
    r0 = json.loads(R0_FINDING.read_text(encoding="utf-8"))

    # ---- 一、表头恢复 ----
    header_check = {}
    per_unit = []
    for source_id, rel in sorted(path_by_source.items()):
        if not rel.lower().endswith(".xlsx"):
            continue
        services = ParseServices()
        parsed = list(parse_document(V3_ROOT / rel, "xlsx", services))
        target_sheet = TARGET_SHEET_NAME[source_id]
        header_row = next((sheet.get("header_row") for sheet in services.report.get("sheets", []) if sheet.get("name") == target_sheet), None)
        r0_header = ((r0.get("findings") or {}).get(source_id) or {}).get("parser_header_row")
        header_check[source_id] = {
            "path": rel,
            "target_sheet": target_sheet,
            "declared_header_row": DECLARED_HEADER_ROWS[source_id],
            "parser_header_row_r1": header_row,
            "parser_header_row_r0": r0_header,
            "header_restored": header_row == DECLARED_HEADER_ROWS[source_id],
            "changed_vs_r0": header_row != r0_header,
            "units_r1": len(parsed),
            "units_r0": ((r0.get("findings") or {}).get(source_id) or {}).get("units"),
        }
        for unit in parsed:
            fields = dict(unit.fields)
            shapes = variants(fields)
            triples = {name: list(he._effective_range({"raw_fields": shape})) for name, shape in shapes.items()}
            base = triples["sentinel"]
            # 只有原本「留空」的 unit（R1 里就是哨兵格）才谈得上「哨兵 vs 留空」的等价性；
            # 其余 unit 的 失效日期 是真实日期，掩成 None 当然会变（那是另一件事，且 02r1 已证其逐字节未动）。
            applicable = fields.get("失效日期") == SENTINEL
            to_dates = he._collect_dates(shapes["sentinel"], he.EFFECTIVE_TO_KEYS)
            per_unit.append(
                {
                    "source_id": source_id,
                    "sheet": unit.sheet,
                    "unit_key": unit.unit_key,
                    "effective_to_raw": fields.get("失效日期"),
                    "applicable_sentinel_unit": applicable,
                    "triple_sentinel": base,
                    "triple_r0_none": triples["r0_none"],
                    "triple_empty": triples["empty"],
                    "triple_absent": triples["absent"],
                    "triple_equal_all_shapes": (all(value == base for value in triples.values()) if applicable else None),
                    "to_dates_collected": to_dates,
                    "chunking_effective_dates_equal": (
                        list(chunking.effective_dates(shapes["sentinel"])) == list(chunking.effective_dates(shapes["r0_none"]))
                        if applicable
                        else None
                    ),
                }
            )

    # ---- 二、逐 unit 语义不变 ----
    sentinel_units = [row for row in per_unit if row["effective_to_raw"] == SENTINEL]
    semantic = {
        "units_compared_total": len(per_unit),
        "units_applicable_sentinel": len(sentinel_units),
        "note": "只有原本留空的 unit（R1 里装哨兵）参与「哨兵 vs 留空」等价判定；其余 unit 的 失效日期 是真实日期，两轮逐字节相同（见 02r1）",
        "triple_mismatch_units": [row["unit_key"] for row in sentinel_units if not row["triple_equal_all_shapes"]],
        "chunking_mismatch_units": [row["unit_key"] for row in sentinel_units if not row["chunking_effective_dates_equal"]],
        "sentinel_triples": [
            {"unit_key": row["unit_key"], "triple": row["triple_sentinel"], "to_dates_collected": row["to_dates_collected"]}
            for row in sentinel_units
        ],
        "sentinel_triples_all_right_side_skipped": all(
            row["triple_sentinel"][0] == "range" and row["triple_sentinel"][2] is None and row["to_dates_collected"] == []
            for row in sentinel_units
        ),
        "sentinel_triples_distinct": sorted({tuple(row["triple_sentinel"]) for row in sentinel_units}),
    }

    # ---- 三、哨兵不被解析成日期 ----
    not_a_date = {
        "sentinel": SENTINEL,
        "hard_evidence_parse_date_text": he._parse_date_text(SENTINEL),
        "chunking_parse_date": chunking.parse_date(SENTINEL),
        "chunking_effective_dates_on_sentinel_only": list(chunking.effective_dates({"失效日期": SENTINEL})),
        "hard_evidence_collect_dates_on_sentinel_only": he._collect_dates({"失效日期": SENTINEL}, he.EFFECTIVE_TO_KEYS),
        "ok": he._parse_date_text(SENTINEL) is None
        and chunking.parse_date(SENTINEL) is None
        and list(chunking.effective_dates({"失效日期": SENTINEL})) == [None, None]
        and he._collect_dates({"失效日期": SENTINEL}, he.EFFECTIVE_TO_KEYS) == [],
    }

    checks = {
        "all_six_headers_restored": all(item["header_restored"] for item in header_check.values()),
        "v05_header_back_to_7": header_check["V05"]["parser_header_row_r1"] == 7 and header_check["V05"]["parser_header_row_r0"] == 8,
        "v06_header_back_to_4": header_check["V06"]["parser_header_row_r1"] == 4 and header_check["V06"]["parser_header_row_r0"] == 5,
        "other_four_unchanged_vs_r0": all(
            header_check[code]["parser_header_row_r1"] == header_check[code]["parser_header_row_r0"] for code in ("V03", "D01", "V04", "D02")
        ),
        "effective_range_identical_all_units": not semantic["triple_mismatch_units"],
        "chunking_effective_dates_identical_all_units": not semantic["chunking_mismatch_units"],
        "sentinel_side_is_skipped_not_dated": semantic["sentinel_triples_all_right_side_skipped"],
        "sentinel_units_exactly_11": semantic["units_applicable_sentinel"] == 11,
        "sentinel_never_parsed_as_date": not_a_date["ok"],
    }
    payload = {
        "schema_version": "p2h2v3-effective-range-proof/v0.1",
        "phase": "effective-range-proof-r1",
        "question": "把 失效日期 的留空改成哨兵 未声明 之后，_effective_range 的返回值是否逐 unit 不变？表头是否恢复？",
        "method": "真实 parse_document 解析 6 个 xlsx；对每个 unit 造 (哨兵 / R0 的 None / 空串 / 键缺失) 四种 raw_fields，分别调冻结分类器 p2_hard_evidence._effective_range 与 rag.chunking.effective_dates，要求逐值相等",
        "frozen_classifier": {
            "path": "backend/src/mktkb/evaluation/p2_hard_evidence.py",
            "sha256": sha256_file(ROOT / "backend/src/mktkb/evaluation/p2_hard_evidence.py"),
            "functions": ["_parse_date_text:1452", "_collect_dates:1464", "_effective_range:1481"],
        },
        "chunking": {
            "path": "backend/src/mktkb/rag/chunking.py",
            "sha256": sha256_file(ROOT / "backend/src/mktkb/rag/chunking.py"),
            "functions": ["parse_date:142", "effective_dates:154"],
        },
        "r0_reference": {
            "path": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-corpus/evidence/08-header-detection-finding.json",
            "sha256": sha256_file(R0_FINDING),
        },
        "header_check": header_check,
        "semantic_invariance": semantic,
        "not_a_date": not_a_date,
        "checks": checks,
        "result": "HEADER_RESTORED_AND_RANGE_SEMANTICS_UNCHANGED" if all(checks.values()) else "SEMANTICS_CHANGED",
        "units": per_unit,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "header_check": {code: {k: item[k] for k in ("parser_header_row_r0", "parser_header_row_r1", "declared_header_row", "units_r0", "units_r1")} for code, item in header_check.items()},
                "semantic_invariance": {k: v for k, v in semantic.items() if k != "sentinel_triples"},
                "not_a_date": not_a_date,
                "checks": checks,
                "result": payload["result"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
