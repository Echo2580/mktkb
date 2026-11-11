"""T207-FIX-CONFLICT 泛化探针：用**合成的新资料**（不在 fixtures、不在冻结题集里）验证冲突复核是通用规则。

两个用例（都在临时目录生成、不进 fixtures）：
- GS_new_value：docx 通知"城东店宣传海报临时调整至 C区9号架。"+ D01，候选裁成"只有表格行"
  （live 门控后的形状）→ 修复后应 conflict（表值 + 合成值，双来源），修复前 answer。
- GS_same_value：docx 通知写**与表格相同**的位置值 → 两臂都应 answer（不得把同值资料伪造成冲突）。
零真实出站（模型替身）。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
SRC = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--src=")), None)
OUT = next(arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--out="))
sys.path.insert(0, str(ROOT / "backend" / "tests" / "acceptance"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
sys.path.insert(0, str(Path(SRC)) if SRC else str(ROOT / "backend" / "src"))

from docx import Document  # noqa: E402
from sqlalchemy import select  # noqa: E402

from support import b0  # noqa: E402
from mktkb.documents.models import SourceUnit  # noqa: E402

D01 = ROOT / "fixtures" / "acceptance" / "normal" / "D01_物品位置表.xlsx"
QUESTION = "城东店的宣传海报现在放在哪里？"


def write_docx(path: Path, sentence: str) -> Path:
    document = Document()
    document.add_paragraph("物料位置调整通知")
    document.add_paragraph(sentence)
    document.save(path)
    return path


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


def run_case(work: Path, synthetic: Path) -> dict:
    harness = b0.new_harness(work)
    try:
        admin = harness.admin()
        publish(harness, admin, path=D01)
        publish(harness, admin, path=synthetic)
        employee = harness.employee()
        qa = harness.app.state.qa
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
            log.append({"mode": mode, "candidates": len(ids), "kept_table_rows": len(kept)})
            return kept

        qa.candidate_unit_ids_for_intent = wrapped
        try:
            calls_before = len(harness.model.calls)
            conversation = b0.new_conversation(employee, "T207-SYNTH")
            payload = b0.ask(employee, conversation, QUESTION).json()
        finally:
            qa.candidate_unit_ids_for_intent = original
        return {
            "question": QUESTION,
            "synthetic_document": synthetic.name,
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
            "candidate_calls": log,
            "model_calls": len(harness.model.calls) - calls_before,
        }
    finally:
        harness.close()


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="t207v-synth-"))
    synthetic = write_docx(work / "合成物料位置通知.docx", "城东店宣传海报临时调整至 C区9号架。")
    same_value = write_docx(work / "合成同值位置通知.docx", "城东店宣传海报临时调整至 B区1号货架第二层。")
    result = {
        "src": SRC or str(ROOT / "backend" / "src"),
        "GS_new_value": run_case(work / "new", synthetic),
        "GS_same_value": run_case(work / "same", same_value),
    }
    Path(OUT).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: {inner: result[key][inner] for inner in ("kind", "conflict_values", "sources", "model_calls")} for key in ("GS_new_value", "GS_same_value")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
