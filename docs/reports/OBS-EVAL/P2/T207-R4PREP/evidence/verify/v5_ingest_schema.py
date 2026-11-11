"""P2-T207-R4PREP 独立验收 v5：灌库计划 schema/顺序 + 未知字段拒绝（只读、零网络）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = next(p for p in HERE.parents if (p / "backend" / "src").is_dir())
T207 = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207"
INGEST = T207 / "PM" / "T207-ingest-plan-R4.json"
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation.product_adapter import ingest_plan_from_document  # noqa: E402


def try_parse(doc: dict) -> dict:
    try:
        plan = ingest_plan_from_document(doc)
    except Exception as exc:  # noqa: BLE001 - 被测行为
        return {"ok": False, "type": type(exc).__name__, "code": getattr(exc, "code", None),
                "message": str(exc)[:160]}
    return {
        "ok": True,
        "sources": [
            {"path": str(source.path), "name": source.name, "document_ref": source.document_ref,
             "expected_active_version_id": source.expected_active_version_id,
             "publish": bool(source.publish)}
            for source in plan.sources
        ],
    }


def main() -> None:
    doc = json.loads(INGEST.read_text(encoding="utf-8"))
    baseline = try_parse(doc)
    order = [
        (Path(item["path"]).name, item.get("name"), item.get("document_ref"), item.get("publish", True))
        for item in doc["sources"]
    ]
    expected_order = [
        ("V03_物品位置表_历史V1.xlsx", "D01_物品位置表.xlsx", None, True),
        ("D01_物品位置表.xlsx", None, "D01_物品位置表.xlsx", True),
        ("V04_物品位置表_新版V3.xlsx", None, "D01_物品位置表.xlsx", False),
        ("V01_临时物料位置通知.pdf", None, None, True),
        ("D02_合作店家信息.xlsx", None, None, True),
        ("V02_店家联系方式变更通知.pdf", None, None, True),
    ]
    unknown_field = json.loads(json.dumps(doc))
    unknown_field["sources"][0]["assert_active_version"] = "v1"
    nested_assert = json.loads(json.dumps(doc))
    nested_assert["sources"][0]["expected"] = {"state": "published"}
    reordered = json.loads(json.dumps(doc))
    reordered["sources"] = [reordered["sources"][3], reordered["sources"][0]] + reordered["sources"][1:3] + reordered["sources"][4:]

    report = {
        "ingest_plan_path": str(INGEST.relative_to(ROOT)),
        "schema_version": doc.get("schema_version"),
        "label": doc.get("label"),
        "source_count": len(doc["sources"]),
        "order_observed": order,
        "order_matches_spec": [list(item) for item in order]
        == [list(item) for item in expected_order],
        "parse_ok": baseline.get("ok"),
        "parsed_sources": baseline.get("sources"),
        "unknown_field_rejected": try_parse(unknown_field),
        "nested_assert_rejected": try_parse(nested_assert),
        "reorder_accepted_by_schema": try_parse(reordered).get("ok"),
        "note": "schema 只校验形状/白名单，不校验顺序；顺序是语义（见 report §9.2 的表）。",
    }
    checks = {
        "schema_version_ok": doc.get("schema_version") == "p2-ingest-plan/v0.1",
        "six_sources": len(doc["sources"]) == 6,
        "order_matches_spec": report["order_matches_spec"],
        "parses": bool(report["parse_ok"]),
        "unknown_field_rejected": report["unknown_field_rejected"].get("ok") is False,
        "nested_assert_rejected": report["nested_assert_rejected"].get("ok") is False,
        "reorder_silently_accepted_by_schema": report["reorder_accepted_by_schema"] is True,
    }
    report["checks"] = checks
    report["all_hold"] = all(v for k, v in checks.items() if k != "reorder_silently_accepted_by_schema")
    print(json.dumps(report, ensure_ascii=False, indent=1))


def _run(main_fn) -> None:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        main_fn()
    text = buffer.getvalue()
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    if out:
        Path(out).write_text(text, encoding="utf-8")
    sys.stdout.write(text)


if __name__ == "__main__":
    _run(main)
