"""T207-FIX-CONFLICT 非硬编码/泛化探针：换用未在冻结题集里配对的资料组合。

- G1：D01（表格）+ V07（另一份独立位置通知 PDF，U06 用）→ 窄候选下问位置，应仍报 conflict
      且两值两来源（不依赖 V01/C05 的具体取值）。
- G2：D02（店家表）+ V02（只改电话的通知）→ 窄候选下问"地址"，通知没有地址值 →
      不得误报 conflict（应是 answer，地址仍唯一）。
- G3：同 G1 形状但问"宣传海报的负责人"（该字段任何资料都没记录）→ 不得因复核变成 conflict。

用法：.venv/Scripts/python.exe .../generality.py --src=<产品源码根> --out=<json>
"""

from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
SRC = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--src=")), None)
OUT = next(arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--out="))
sys.path.insert(0, str(ROOT / "backend" / "tests" / "acceptance"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
sys.path.insert(0, str(Path(SRC)) if SRC else str(ROOT / "backend" / "src"))

from sqlalchemy import select  # noqa: E402

from support import b0  # noqa: E402
from mktkb.documents.models import SourceUnit  # noqa: E402

FIX = ROOT / "fixtures" / "acceptance"
D01 = FIX / "normal" / "D01_物品位置表.xlsx"
D02 = FIX / "normal" / "D02_合作店家信息.xlsx"
V02 = FIX / "variants" / "V02_店家联系方式变更通知.pdf"
V07 = FIX / "variants" / "V07_物料位置独立通知.pdf"


def publish(harness, admin, *, path, document_id=None, expected_active=None) -> dict:
    receipt = admin.upload(path=path, document_id=document_id, expected_active_version_id=expected_active)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    harness.ocr.unbind()
    result = harness.run_job()
    assert result.state == "succeeded", result
    detail = harness.detail(record["document"]["id"])
    active = detail["document"]["active_version"]
    published = admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        json={
            "expected_active_version_id": active["id"] if active else None,
            "expected_revision": detail["revision"],
        },
        headers=admin.headers,
    )
    assert published.status_code == 200, published.text
    return record


def narrow(qa, harness):
    rows = None
    db = harness.session()
    try:
        rows = {str(value) for value in db.scalars(select(SourceUnit.id).where(SourceUnit.kind == "table_row")).all()}
    finally:
        db.close()
    original = qa.candidate_unit_ids_for_intent
    log = []

    def wrapped(*, mode, terms=(), entity_filters=None):
        ids = original(mode=mode, terms=terms, entity_filters=entity_filters)
        kept = {str(item) for item in ids if str(item) in rows}
        log.append({"candidates": len(ids), "kept_table_rows": len(kept)})
        return kept

    qa.candidate_unit_ids_for_intent = wrapped
    return original, log


def run(docs, question):
    harness = b0.new_harness(Path(tempfile.mkdtemp(prefix="t207v-gen-")))
    try:
        admin = harness.admin()
        for doc in docs:
            publish(harness, admin, path=doc)
        employee = harness.employee()
        qa = harness.app.state.qa
        original, log = narrow(qa, harness)
        try:
            calls_before = len(harness.model.calls)
            conversation = b0.new_conversation(employee, "T207-GEN")
            payload = b0.ask(employee, conversation, question).json()
        finally:
            qa.candidate_unit_ids_for_intent = original
        return {
            "question": question,
            "docs": [Path(doc).name for doc in docs],
            "kind": payload.get("kind"),
            "text": payload.get("text"),
            "sources": [
                {"document_name": item.get("document_name"), "version_number": item.get("version_number")}
                for item in payload.get("sources") or []
            ],
            "conflict_values": [
                entry.get("value")
                for conflict in payload.get("conflicts") or []
                for entry in conflict.get("entries") or []
            ],
            "conflict_fields": [conflict.get("field") for conflict in payload.get("conflicts") or []],
            "candidates": [item.get("label") for item in payload.get("candidates") or []],
            "candidate_calls": log,
            "model_calls": len(harness.model.calls) - calls_before,
        }
    finally:
        harness.close()


def main() -> int:
    result = {
        "src": SRC or str(ROOT / "backend" / "src"),
        "G1_position_v07": run([D01, V07], "城东店的宣传海报现在放在哪里？"),
        "G2_phone_doc_address": run([D02, V02], "城东店的地址是什么？"),
        "G3_unrecorded_field": run([D01, V07], "城东店宣传海报的负责人是谁？"),
    }
    Path(OUT).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: {"kind": value["kind"], "values": value["conflict_values"], "sources": [item["document_name"] for item in value["sources"]]} for key, value in result.items() if key != "src"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
