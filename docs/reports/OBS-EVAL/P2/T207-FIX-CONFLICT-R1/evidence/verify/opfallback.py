"""独立验收脚本（T207-FIX-CONFLICT-R1）：冲突复核的异常兜底（OperationalError / 安全异常）。

用法：
  .venv/Scripts/python.exe <本文件> --src=<产品源码根> --out=<json>

形状：B0 装配 + 发布 V01，且把 rag 候选裁成只剩表格行（等价 live 每轮 1 次 query embedding 的后果），
使"同实体复核"成为 C05 是否 conflict 的唯一开关。三个臂：
  A 不注入            → 复核生效：conflict（证明探针形状有效）
  B 复核抛 OperationalError → 200 + answer + conflicts=[]（复核放弃，不披露冲突、不冒泡 500）
  C 复核抛 AccessDenied     → 安全异常不被吞：按其稳定错误映射返回（403 FORBIDDEN）
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import netguard  # noqa: E402

netguard.install()

parser = argparse.ArgumentParser()
parser.add_argument("--src", default=str(ROOT / "backend" / "src"))
parser.add_argument("--out", required=True)
args = parser.parse_args()
sys.path.insert(0, str(ROOT / "backend" / "tests" / "acceptance"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))
sys.path.insert(0, str(Path(args.src)))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from support import b0  # noqa: E402
import mktkb  # noqa: E402
from mktkb.conversations import service as service_module  # noqa: E402
from mktkb.documents.models import SourceUnit  # noqa: E402
from mktkb.errors import AccessDenied  # noqa: E402

assert Path(mktkb.__file__).resolve().is_relative_to(Path(args.src).resolve()), (
    mktkb.__file__,
    args.src,
)

V03 = ROOT / "fixtures" / "acceptance" / "variants" / "V03_物品位置表_历史V1.xlsx"
D01 = ROOT / "fixtures" / "acceptance" / "normal" / "D01_物品位置表.xlsx"
V01 = ROOT / "fixtures" / "acceptance" / "variants" / "V01_临时物料位置通知.pdf"
QUESTION = "城东店的宣传海报现在放在哪里？"


def publish(harness, admin, *, path: Path, document_id=None, expected_active=None) -> dict:
    """C05 的 B0 形状：V03 历史 V1 → D01 业务 V2 同槽 → 独立 V01 通知。"""
    receipt = admin.upload(
        path=path, document_id=document_id, expected_active_version_id=expected_active
    )
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


def ask(employee, question: str) -> dict:
    conversation = b0.new_conversation(employee, "T207-R1-FALLBACK")
    try:
        response = b0.ask(employee, conversation, question)
    except Exception as exc:  # noqa: BLE001 - 记录"未被吞掉"的异常类型
        return {"raised": type(exc).__name__, "message": str(exc)[:200]}
    payload = response.json()
    return {
        "status_code": response.status_code,
        "kind": payload.get("kind"),
        "text": payload.get("text"),
        "conflicts": payload.get("conflicts") or [],
        "sources": [item.get("document_name") for item in payload.get("sources") or []],
        "error": payload.get("error"),
    }


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="t207r1-fallback-"))
    harness = b0.new_harness(work)
    original = service_module._retrieve
    original_candidates = harness.app.state.qa.candidate_unit_ids_for_intent
    state = {"probes": 0, "candidate_calls": []}
    try:
        admin = harness.admin()
        first = publish(harness, admin, path=V03)
        publish(
            harness,
            admin,
            path=D01,
            document_id=first["document"]["id"],
            expected_active=first["version"]["id"],
        )
        publish(harness, admin, path=V01)

        db = harness.session()
        try:
            rows = {str(value) for value in db.scalars(select(SourceUnit.id).where(SourceUnit.kind == "table_row")).all()}
        finally:
            db.close()

        def narrowed(*, mode, terms=(), entity_filters=None):
            ids = original_candidates(mode=mode, terms=terms, entity_filters=entity_filters)
            kept = {str(item) for item in ids if str(item) in rows}
            state["candidate_calls"].append({"mode": mode, "candidates": len(ids), "kept_table_rows": len(kept)})
            return kept

        harness.app.state.qa.candidate_unit_ids_for_intent = narrowed

        def with_probe(exc):
            def wrapper(db_factory, intent, revision, limit=20, *, candidate_ids=None):
                if candidate_ids is None and getattr(intent, "mode", None) == "record":
                    state["probes"] += 1
                    if exc is not None:
                        raise exc
                return original(db_factory, intent, revision, limit=limit, candidate_ids=candidate_ids)

            return wrapper

        employee = harness.employee()
        arms = {}
        state["probes"] = 0
        service_module._retrieve = with_probe(None)
        try:
            arms["A_no_injection"] = ask(employee, QUESTION)
        finally:
            service_module._retrieve = original
        arms["A_no_injection"]["probe_calls"] = state["probes"]

        state["probes"] = 0
        service_module._retrieve = with_probe(
            OperationalError("SELECT 1", {}, Exception("database is locked"))
        )
        try:
            arms["B_operational_error"] = ask(employee, QUESTION)
        finally:
            service_module._retrieve = original
        arms["B_operational_error"]["probe_calls"] = state["probes"]

        state["probes"] = 0
        service_module._retrieve = with_probe(AccessDenied())
        try:
            arms["C_access_denied"] = ask(employee, QUESTION)
        finally:
            service_module._retrieve = original
        arms["C_access_denied"]["probe_calls"] = state["probes"]

        models_before = len(harness.model.calls)
        result = {
            "src": str(Path(args.src).resolve()),
            "mktkb_file": str(Path(mktkb.__file__).resolve()),
            "question": QUESTION,
            "narrow_candidate_calls": state["candidate_calls"],
            "arms": arms,
            "model_calls_total": models_before,
            "ocr_calls_total": len(harness.ocr.calls),
            **netguard.summary(),
        }
    finally:
        service_module._retrieve = original
        harness.app.state.qa.candidate_unit_ids_for_intent = original_candidates
        harness.close()
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"arms": {k: {kk: vv for kk, vv in v.items() if kk in ("status_code", "kind", "raised", "probe_calls")} for k, v in result["arms"].items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
