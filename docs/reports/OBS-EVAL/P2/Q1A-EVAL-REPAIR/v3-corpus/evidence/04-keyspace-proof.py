"""v3 keyspace proof：30 题声明的 entity target 是否与运行期键空间同形可对齐。

证明方式（全部用**真实运行期函数**，不重写规则）：
1. 用真实解析器 ``mktkb.ingestion.parsers.parse_document`` 解析 v3 的 6 个 xlsx，拿到与入库
   一致的 ``ParsedUnit.fields``（表头→值；日期是文本，原样保留）；
2. 用真实 ``mktkb.retrieval.index.analyze_fields`` 为每个 unit 求
   ``(entity_type, entity_key, entity_filters)``；用真实 ``mktkb.retrieval.tokenize.normalize_value``
   复算键内 id 的小写形态；
3. 对出题计划 §5 逐题声明的 target（``记录@版本``，30 题 36 条）检查 9 项：
   来源在 v3 里存在 / 该版本含该记录行 / 键含 ``|id:`` 且 id 段非空 / 实体类型与记录前缀一致 /
   不是 ``document|<uuid>`` / filters 只含运行期角色键且含 id 键 / 该版本在本 run 的 scenario 内已上传 /
   该版本窗口按闭区间覆盖 run 的 business_date / 记录→unit 在该版本内唯一；
4. 反向探针（防止"硬凑"）：``备用物料表`` 行必须**不是** id 型键；隐藏表 ``旧草稿`` 必须不入库；
   ``P05``/``P06`` 必须不出现在任何 target；同一记录跨版本的 entity_key 必须相同。

零真实调用：只读本地文件 + 纯函数；L1 读取在本脚本内重新实现。
用法：``.venv\\Scripts\\python.exe 04-keyspace-proof.py``
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
HERE = Path(__file__).resolve().parent
V3_ROOT = ROOT / "fixtures/acceptance-h2v3"
L1_PATH = ROOT / "docs/evaluation/p2-source-lifecycle-v1.json"
OUT = HERE / "04-keyspace-proof.json"

sys.path.insert(0, str(ROOT / "backend/src"))

from mktkb.ingestion.parsers import ParseServices, parse_document  # noqa: E402
from mktkb.retrieval.index import ID_HEADERS, analyze_fields  # noqa: E402
from mktkb.retrieval.tokenize import normalize_value  # noqa: E402

#: 出题计划 §5 公开声明的 target（记录@版本）：run, case, [record_code, doc_code, version_number]
DECLARED_TARGETS = [
    (0, "C01", [("P01", "D01", 2)]),
    (0, "C02", [("P03", "D01", 2)]),
    (0, "C03", [("S01", "D02", 1)]),
    (0, "C04", [("P02", "D01", 2)]),
    (1, "C05", [("P07", "D01", 2)]),
    (1, "C06", [("S03", "D02", 1)]),
    (1, "C07", [("P04", "D01", 2), ("P08", "D01", 2)]),
    (2, "C08", [("P02", "D01", 3)]),
    (3, "C09", [("P08", "D01", 4)]),
    (3, "C10", [("S02", "D02", 2)]),
    (0, "C11", [("P01", "D01", 2)]),
    (0, "C12", [("P02", "D01", 2), ("S02", "D02", 1)]),
    (1, "C13", [("P03", "D01", 2)]),
    (2, "C14", [("P04", "D01", 3)]),
    (3, "C15", [("P07", "D01", 4)]),
    (0, "C16", [("S03", "D02", 1)]),
    (0, "C17", [("S04", "D02", 1)]),
    (1, "C18", [("P07", "D01", 2)]),
    (2, "C19", [("P02", "D01", 3)]),
    (3, "C20", [("P08", "D01", 4)]),
    (0, "C21", [("P01", "D01", 2)]),
    (1, "C22", [("P01", "D01", 2)]),
    (0, "C23", [("P08", "D01", 2)]),
    (1, "C24", [("P02", "D01", 2)]),
    (2, "C25", [("P01", "D01", 3)]),
    (0, "C26", [("P01", "D01", 2), ("S01", "D02", 1)]),
    (0, "C27", [("S01", "D02", 1)]),
    (1, "C28", [("P08", "D01", 2), ("S02", "D02", 1)]),
    (2, "C29", [("P03", "D01", 3), ("S03", "D02", 2)]),
    (3, "C30", [("P07", "D01", 4), ("S02", "D02", 2)]),
]

#: 运行期会产出的角色键（``retrieval/index.py:128-136``）；不得放 doc_code/record_code/version/sheet/row
RUNTIME_ROLE_KEYS = {"store", "item", "item_id", "store_id"}
ID_ROLE_BY_TYPE = {"item": "item_id", "store": "store_id"}
EXPECTED_TYPE_BY_PREFIX = {"P": "item", "S": "store"}

#: 目标表在 v2/v3 里的物理表头行（规格 §1.2 原表头行；整表加列不改变行号）。
DECLARED_HEADER_ROWS = {"V03": 7, "D01": 7, "V04": 7, "V05": 7, "D02": 4, "V06": 4}
TARGET_SHEET_NAME = {"V03": "物品位置", "D01": "物品位置", "V04": "物品位置", "V05": "物品位置", "D02": "店家信息", "V06": "店家信息"}


def l1_payload() -> dict:
    payload = json.loads(L1_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "p2-source-lifecycle/v1"
    assert payload["interval"] == "closed"
    return payload


def covers(window: tuple[str, str | None], day: str) -> bool:
    start, end = window
    if date.fromisoformat(day) < date.fromisoformat(start):
        return False
    return end is None or date.fromisoformat(day) <= date.fromisoformat(end)


def _filters_exact(entity_filters: dict, entity_type: str, id_value: str, role_values: dict) -> bool:
    """``entity_filters`` 必须与运行期逐键逐值全等（``retrieval/index.py:128-136``）。"""
    if not entity_filters:
        return False
    expected = {"store": role_values.get("store"), "item": role_values.get("item")}
    if entity_type == "item":
        expected["item_id"] = id_value
    elif entity_type == "store":
        expected["store_id"] = id_value
    expected = {key: value for key, value in expected.items() if value not in (None, "")}
    if set(expected) != set(entity_filters):
        return False
    return all(str(entity_filters[key]) == str(value) for key, value in expected.items())


def main() -> int:
    l1 = l1_payload()
    versions = {(row["doc_code"], int(row["version_number"])): row for row in l1["sources"]}
    records_l1 = {(row["doc_code"], int(row["version_number"]), row["record_code"]): row for row in l1["records"]}
    run_dates = {run["run_index"]: run["business_date"] for run in l1["coverage_selfcheck"]["per_run_dates"]["runs"]}
    run_scenarios = {run["run_index"]: run["scenario_id"] for run in l1["coverage_selfcheck"]["per_run_dates"]["runs"]}
    uploaded = {
        row["scenario_id"]: {doc: list(codes) for doc, codes in row["uploaded_slots"].items()}
        for row in l1["coverage_selfcheck"]["per_scenario"]
    }
    manifest = json.loads((V3_ROOT / "manifest.json").read_text(encoding="utf-8"))
    path_by_source = {item["id"]: item["path"] for item in manifest["normal_files"] + manifest["variants"]}
    source_by_version = {(row["doc_code"], int(row["version_number"])): row["source_id"] for row in l1["sources"]}

    # ---- 1) 真实解析：v3 语料 -> units ----
    per_source = {}
    units = []
    for source_id, rel in sorted(path_by_source.items()):
        path = V3_ROOT / rel
        if path.suffix.lower() != ".xlsx":
            continue
        services = ParseServices()
        parsed = list(parse_document(path, "xlsx", services))
        sheet_reports = services.report.get("sheets", [])
        target_sheet = TARGET_SHEET_NAME[source_id]
        parser_header = next(
            (sheet.get("header_row") for sheet in sheet_reports if sheet.get("name") == target_sheet), None
        )
        per_source[source_id] = {
            "path": rel,
            "units": len(parsed),
            "sheets": [sheet["name"] + ("|hidden" if sheet.get("hidden") else "") for sheet in sheet_reports],
            "hidden_sheet_count": services.report.get("hidden_sheet_count"),
            "ingested_sheets": [sheet["name"] for sheet in sheet_reports if sheet.get("ingested")],
            "target_sheet": target_sheet,
            "declared_header_row": DECLARED_HEADER_ROWS[source_id],
            "parser_header_row": parser_header,
            "header_detection_agrees": parser_header == DECLARED_HEADER_ROWS[source_id],
            "id_header_detected_units": sum(1 for unit in parsed if any(name in ID_HEADERS for name in unit.fields)),
        }
        for unit in parsed:
            fields = dict(unit.fields)
            id_name = next((name for name in fields if name in ID_HEADERS), None)
            id_value = "" if id_name is None else str(fields.get(id_name) or "").strip()
            role_by_name, role_values, entity_type, entity_key, _label, entity_filters = analyze_fields(fields)
            units.append(
                {
                    "source_id": source_id,
                    "sheet": unit.sheet,
                    "unit_key": unit.unit_key,
                    "locator": unit.locator,
                    "id_header": id_name,
                    "id_value": id_value,
                    "entity_type": entity_type,
                    "entity_key": entity_key,
                    "filters_keys": sorted(entity_filters or {}),
                    "filters_values_match": _filters_exact(entity_filters, entity_type, id_value, role_values),
                    "header_detected": services.report.get("sheets") is not None,
                    "effective_from": fields.get("生效日期"),
                    "effective_to": fields.get("失效日期"),
                }
            )

    # 同一记录跨版本的 entity_key 是否稳定（键空间与版本无关，才可能被 target 复用）
    key_by_record: dict[str, set] = {}
    for unit in units:
        if unit["entity_key"] and "|id:" in unit["entity_key"]:
            key_by_record.setdefault(unit["id_value"], set()).add(unit["entity_key"])

    # ---- 2) 逐题逐 target 检查 ----
    target_rows = []
    for run_index, case_id, targets in DECLARED_TARGETS:
        business_date = run_dates[run_index]
        scenario_id = run_scenarios[run_index]
        for record_code, doc_code, version_number in targets:
            source_id = source_by_version.get((doc_code, version_number))
            checks = {}
            reasons = []
            source_units = [u for u in units if u["source_id"] == source_id]
            matches = [u for u in source_units if u["id_value"] == record_code]
            unit = matches[0] if len(matches) == 1 else None
            checks["source_in_corpus"] = source_id is not None
            if not source_id:
                reasons.append("source_for_version_missing")
            checks["record_in_declared_version"] = len(matches) == 1
            if len(matches) != 1:
                reasons.append(f"record_rows_found={len(matches)}")
            checks["record_unit_unique_in_version"] = len(matches) == 1
            if unit is None:
                target_rows.append(
                    {
                        "case_id": case_id,
                        "run_index": run_index,
                        "business_date": business_date,
                        "scenario_id": scenario_id,
                        "target": f"{record_code}@{doc_code}v{version_number}",
                        "entity_key": None,
                        "alignable": False,
                        "checks": checks,
                        "reasons": reasons,
                    }
                )
                continue
            expected_type = EXPECTED_TYPE_BY_PREFIX[record_code[0]]
            key = unit["entity_key"] or ""
            id_segment = key.split("|id:", 1)[1] if "|id:" in key else ""
            checks["id_typed_key"] = bool(id_segment) and id_segment == normalize_value(unit["id_value"])
            checks["entity_type_matches_record_prefix"] = unit["entity_type"] == expected_type
            checks["not_document_or_uuid"] = "uuid" not in key and not key.startswith("document|")
            checks["filters_keys_runtime_only"] = set(unit["filters_keys"]) <= RUNTIME_ROLE_KEYS and ID_ROLE_BY_TYPE[expected_type] in unit["filters_keys"]
            checks["filters_values_match_runtime"] = unit["filters_values_match"]
            uploaded_versions = uploaded[scenario_id].get(doc_code, [])
            checks["version_uploaded_in_run_scenario"] = source_id in uploaded_versions
            window = (
                records_l1[(doc_code, version_number, record_code)]["effective_from"],
                records_l1[(doc_code, version_number, record_code)]["effective_to"],
            ) if (doc_code, version_number, record_code) in records_l1 else (
                versions[(doc_code, version_number)]["effective_from"],
                versions[(doc_code, version_number)]["effective_to"],
            )
            checks["active_at_run_date_closed_interval"] = covers(window, business_date)
            checks["raw_fields_dates_match_l1"] = (unit["effective_from"], unit["effective_to"]) == (window[0], window[1] or None) or (
                unit["effective_from"] == window[0] and (unit["effective_to"] in (None, "")) == (window[1] is None)
            )
            for name, ok in checks.items():
                if not ok:
                    reasons.append(name)
            target_rows.append(
                {
                    "case_id": case_id,
                    "run_index": run_index,
                    "business_date": business_date,
                    "scenario_id": scenario_id,
                    "target": f"{record_code}@{doc_code}v{version_number}",
                    "source_id": source_id,
                    "entity_type": unit["entity_type"],
                    "entity_key": key,
                    "filters_keys": unit["filters_keys"],
                    "window": list(window),
                    "unit_key": unit["unit_key"],
                    "alignable": all(checks.values()),
                    "checks": checks,
                    "reasons": reasons,
                }
            )

    # ---- 3) 反向探针 ----
    non_id_units = [u for u in units if not (u["entity_key"] and "|id:" in u["entity_key"])]
    spare_units = [u for u in units if u["sheet"] == "备用物料表"]
    negative = {
        "spare_sheet_units": len(spare_units),
        "spare_sheet_units_non_id_typed": sum(1 for u in spare_units if not (u["entity_key"] and "|id:" in u["entity_key"])),
        "spare_sheet_units_id_typed": sum(1 for u in spare_units if u["entity_key"] and "|id:" in u["entity_key"]),
        "hidden_draft_sheet_ingested": sum(1 for source in per_source.values() if "旧草稿" in source["ingested_sheets"]),
        "hidden_draft_sheet_present_in_files": sum(
            1 for source in per_source.values() if any(name.startswith("旧草稿") for name in source["sheets"])
        ),
        "non_id_units_total": len(non_id_units),
        "p05_p06_in_declared_targets": sum(
            1 for _run, _case, targets in DECLARED_TARGETS for record_code, _doc, _ver in targets if record_code in ("P05", "P06")
        ),
        "document_or_uuid_keys": sum(1 for u in units if u["entity_key"] and (u["entity_key"].startswith("document|") or "uuid" in u["entity_key"])),
        "record_key_stability_violations": sum(1 for record, keys in key_by_record.items() if len(keys) > 1),
        "records_with_stable_key": sum(1 for keys in key_by_record.values() if len(keys) == 1),
    }
    negative_ok = (
        negative["spare_sheet_units_non_id_typed"] == negative["spare_sheet_units"]
        and negative["hidden_draft_sheet_ingested"] == 0
        and negative["p05_p06_in_declared_targets"] == 0
        and negative["record_key_stability_violations"] == 0
    )

    alignable = [row for row in target_rows if row["alignable"]]
    summary = {
        "declared_cases": len(DECLARED_TARGETS),
        "declared_targets": len(target_rows),
        "alignable": len(alignable),
        "not_alignable": len(target_rows) - len(alignable),
        "multi_target_cases": sum(1 for _run, _case, targets in DECLARED_TARGETS if len(targets) > 1),
        "distinct_records_used": len({row["target"].split("@")[0] for row in target_rows}),
        "units_total": len(units),
        "units_id_typed": sum(1 for u in units if u["entity_key"] and "|id:" in u["entity_key"]),
        "runs": sorted({row["run_index"] for row in target_rows}),
        "cases_with_any_unalignable_target": len({row["case_id"] for row in target_rows if not row["alignable"]}),
        "header_detection_mismatch_sources": sorted(
            source_id for source_id, source in per_source.items() if not source["header_detection_agrees"]
        ),
        "negative_probes_ok": negative_ok,
    }
    result = "aligned" if summary["not_alignable"] == 0 and negative_ok else "misaligned"
    payload = {
        "schema_version": "p2-holdout-v3-keyspace-proof/v0.1",
        "phase": "keyspace-proof",
        "method": "真实解析器 parse_document + 真实 analyze_fields/normalize_value；target 声明取自出题计划 §5；窗口与上传集取自 L1",
        "code_facts": {
            "id_headers": list(ID_HEADERS),
            "entity_key_form": 'f"{entity_type}|id:{normalize_value(标识)}"（retrieval/index.py:121-126）',
            "entity_types_allowed": ["item", "store"],
            "runtime_role_keys": sorted(RUNTIME_ROLE_KEYS),
            "expected_type_by_prefix": EXPECTED_TYPE_BY_PREFIX,
        },
        "l1": {"path": "docs/evaluation/p2-source-lifecycle-v1.json", "sha256": hash_file(L1_PATH)},
        "corpus_manifest": {"path": "fixtures/acceptance-h2v3/manifest.json", "sha256": hash_file(V3_ROOT / "manifest.json")},
        "parsed_sources": per_source,
        "summary": summary,
        "negative_probes": negative,
        "result": result,
        "targets": target_rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"summary": summary, "negative_probes": negative, "result": result}, ensure_ascii=False, indent=1))
    if summary["not_alignable"]:
        for row in target_rows:
            if not row["alignable"]:
                print("NOT ALIGNABLE:", row["target"], row["reasons"], file=sys.stderr)
    return 0 if result == "aligned" else 1


def hash_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
