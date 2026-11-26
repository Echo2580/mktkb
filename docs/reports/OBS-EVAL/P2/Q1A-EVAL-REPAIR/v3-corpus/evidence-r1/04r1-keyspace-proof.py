"""v3 语料返工 R1：keyspace proof（36 条 target 逐条判定，含哨兵投影）。

与上一轮 ``../evidence/04-keyspace-proof.py`` 的**唯一判定差异**：``失效日期`` 现在可能装哨兵
``未声明``。原来那条「raw_fields 日期与 L1 逐字相等」的检查因此必须显式写出**两分支投影**：

    raw == 哨兵        ⇒ 投影成 None（= L1 effective_to = null，not_asserted）
    raw == YYYY-MM-DD  ⇒ 投影成自身（必须逐字等于 L1；不接受任何近似）

任何第三形态（空、其他文本、非文本）都直接判 fail —— 这不是放宽，是把「哨兵 ⟺ null」这条
唯一映射写进判据，并额外统计哨兵出现次数（必须是 11，且只在 V05/V06）。

其余 9 项检查与上一轮逐条相同（来源存在 / 该版本含该记录行且唯一 / 键含 ``|id:`` 且 id 段 =
``normalize_value(标识)`` / 实体类型与记录前缀一致 / 非 ``document|``+uuid / filters 键 ⊆ 运行期
角色键且含 id 键 / filters 值与运行期逐键逐值全等 / 该版本在本 run scenario 已上传 / 版本窗口
按闭区间覆盖 run 日）。

全部用**真实运行期函数**（``parse_document`` / ``analyze_fields`` / ``normalize_value``），不重写规则。
零真实调用；L1 读取在本脚本内重新实现。

用法：``.venv\\Scripts\\python.exe 04r1-keyspace-proof.py``
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[7]
V3_ROOT = ROOT / "fixtures/acceptance-h2v3"
L1_PATH = ROOT / "docs/evaluation/p2-source-lifecycle-v1.json"
OUT = HERE / "04r1-keyspace-proof.json"

sys.path.insert(0, str(ROOT / "backend/src"))

from mktkb.ingestion.parsers import ParseServices, parse_document  # noqa: E402
from mktkb.retrieval.index import ID_HEADERS, analyze_fields  # noqa: E402
from mktkb.retrieval.tokenize import normalize_value  # noqa: E402

#: R1 哨兵：L1 effective_to = null 在语料里的唯一字面值（规格 §1.5）。
SENTINEL = "未声明"
SENTINEL_EXPECTED_TOTAL = 11

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

#: 运行期会产出的角色键（``retrieval/index.py:128-136``）
RUNTIME_ROLE_KEYS = {"store", "item", "item_id", "store_id"}
ID_ROLE_BY_TYPE = {"item": "item_id", "store": "store_id"}
EXPECTED_TYPE_BY_PREFIX = {"P": "item", "S": "store"}

DECLARED_HEADER_ROWS = {"V03": 7, "D01": 7, "V04": 7, "V05": 7, "D02": 4, "V06": 4}
TARGET_SHEET_NAME = {"V03": "物品位置", "D01": "物品位置", "V04": "物品位置", "V05": "物品位置", "D02": "店家信息", "V06": "店家信息"}


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def project_effective_to(raw, *, present: bool) -> tuple[str | None, str, bool]:
    """哨兵 → None 的唯一投影。返回 (投影值, 分支名, 投影是否合法)。

    合法分支只有三个：列不存在（非目标表）/ 哨兵 / 日期；第四个形态一律不合法（不猜、不放宽）。
    """
    if not present:
        return None, "column_absent", True
    if raw == SENTINEL:
        return None, "sentinel_not_asserted", True
    if isinstance(raw, str) and len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        return raw, "date", True
    return None, f"illegal({raw!r})", False


def _filters_exact(entity_filters: dict, entity_type: str, id_value: str, role_values: dict) -> bool:
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
        sentinel_units = [
            unit for unit in parsed if dict(unit.fields).get("失效日期") == SENTINEL
        ]
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
            "units_with_sentinel": len(sentinel_units),
        }
        for unit in parsed:
            fields = dict(unit.fields)
            id_name = next((name for name in fields if name in ID_HEADERS), None)
            id_value = "" if id_name is None else str(fields.get(id_name) or "").strip()
            role_by_name, role_values, entity_type, entity_key, _label, entity_filters = analyze_fields(fields)
            raw_to = fields.get("失效日期")
            projected_to, branch, legal = project_effective_to(raw_to, present="失效日期" in fields)
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
                    "effective_from": fields.get("生效日期"),
                    "effective_to_raw": raw_to,
                    "effective_to_projected": projected_to,
                    "effective_to_branch": branch,
                    "effective_to_projection_legal": legal,
                }
            )

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
                for name, ok in checks.items():
                    if not ok and name not in reasons:
                        reasons.append(name)
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
            # R1：哨兵 → None 的唯一投影；两分支都必须与 L1 逐字对上。
            checks["effective_to_projection_legal"] = unit["effective_to_projection_legal"]
            if window[1] is None:
                checks["raw_effective_to_is_sentinel_for_null"] = unit["effective_to_raw"] == SENTINEL
                checks["raw_fields_dates_match_l1"] = unit["effective_from"] == window[0] and unit["effective_to_projected"] is None
            else:
                checks["raw_effective_to_is_sentinel_for_null"] = True  # 该分支不适用（L1 有日期）
                checks["raw_fields_dates_match_l1"] = (
                    unit["effective_from"] == window[0] and unit["effective_to_projected"] == window[1]
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
                    "effective_from_raw": unit["effective_from"],
                    "effective_to_raw": unit["effective_to_raw"],
                    "effective_to_branch": unit["effective_to_branch"],
                    "alignable": all(checks.values()),
                    "checks": checks,
                    "reasons": reasons,
                }
            )

    # ---- 3) 反向探针 ----
    spare_units = [u for u in units if u["sheet"] == "备用物料表"]
    negative = {
        "spare_sheet_units": len(spare_units),
        "spare_sheet_units_non_id_typed": sum(1 for u in spare_units if not (u["entity_key"] and "|id:" in u["entity_key"])),
        "spare_sheet_units_id_typed": sum(1 for u in spare_units if u["entity_key"] and "|id:" in u["entity_key"]),
        "hidden_draft_sheet_ingested": sum(1 for source in per_source.values() if "旧草稿" in source["ingested_sheets"]),
        "hidden_draft_sheet_present_in_files": sum(
            1 for source in per_source.values() if any(name.startswith("旧草稿") for name in source["sheets"])
        ),
        "non_id_units_total": sum(1 for u in units if not (u["entity_key"] and "|id:" in u["entity_key"])),
        "p05_p06_in_declared_targets": sum(
            1 for _run, _case, targets in DECLARED_TARGETS for record_code, _doc, _ver in targets if record_code in ("P05", "P06")
        ),
        "document_or_uuid_keys": sum(1 for u in units if u["entity_key"] and (u["entity_key"].startswith("document|") or "uuid" in u["entity_key"])),
        "record_key_stability_violations": sum(1 for keys in key_by_record.values() if len(keys) > 1),
        "records_with_stable_key": sum(1 for keys in key_by_record.values() if len(keys) == 1),
    }
    negative_ok = (
        negative["spare_sheet_units_non_id_typed"] == negative["spare_sheet_units"]
        and negative["hidden_draft_sheet_ingested"] == 0
        and negative["p05_p06_in_declared_targets"] == 0
        and negative["record_key_stability_violations"] == 0
    )

    # ---- 4) 哨兵审计（全局）----
    sentinel_audit = {
        "sentinel_literal": SENTINEL,
        "units_with_sentinel": sum(1 for u in units if u["effective_to_raw"] == SENTINEL),
        "expected_units_with_sentinel": SENTINEL_EXPECTED_TOTAL,
        "by_source": {source_id: per_source[source_id]["units_with_sentinel"] for source_id in sorted(per_source)},
        "illegal_effective_to_units": [
            {"source_id": u["source_id"], "unit_key": u["unit_key"], "raw": u["effective_to_raw"]}
            for u in units
            if not u["effective_to_projection_legal"]
        ],
    }
    sentinel_audit["ok"] = (
        sentinel_audit["units_with_sentinel"] == SENTINEL_EXPECTED_TOTAL
        and not sentinel_audit["illegal_effective_to_units"]
        and sentinel_audit["by_source"].get("V05") == 7
        and sentinel_audit["by_source"].get("V06") == 4
        and all(sentinel_audit["by_source"].get(code) == 0 for code in ("V03", "D01", "V04", "D02"))
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
        "sentinel_audit_ok": sentinel_audit["ok"],
    }
    result = "aligned" if summary["not_alignable"] == 0 and negative_ok and sentinel_audit["ok"] else "misaligned"
    payload = {
        "schema_version": "p2-holdout-v3-keyspace-proof/v0.2-r1",
        "phase": "keyspace-proof-r1",
        "method": "真实解析器 parse_document + 真实 analyze_fields/normalize_value；target 声明取自出题计划 §5；窗口与上传集取自 L1；失效日期 的哨兵 → None 唯一投影显式写进判据",
        "sentinel": {
            "literal": SENTINEL,
            "mapping": "raw == 未声明 ⇔ L1 effective_to = null (not_asserted)；raw == YYYY-MM-DD ⇔ 逐字等于 L1；第三形态判 fail",
            "spec_ref": "docs/superpowers/plans/2026-11-15-h2-v3-corpus-modification-spec.md §1.5",
        },
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
        "sentinel_audit": sentinel_audit,
        "summary": summary,
        "negative_probes": negative,
        "result": result,
        "targets": target_rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"summary": summary, "negative_probes": negative, "sentinel_audit": sentinel_audit, "result": result}, ensure_ascii=False, indent=1))
    if summary["not_alignable"]:
        for row in target_rows:
            if not row["alignable"]:
                print("NOT ALIGNABLE:", row["target"], row["reasons"], file=sys.stderr)
    return 0 if result == "aligned" else 1


if __name__ == "__main__":
    sys.exit(main())
