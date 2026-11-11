"""独立验收用复现/取证脚本（T207-FIX-CONFLICT）：三例前后对照 + 候选窗口证据 + 零写入计数。

用法：
  .venv/Scripts/python.exe docs/reports/OBS-EVAL/P2/T207-FIX-CONFLICT/evidence/verify/verify3.py \
      --src=<产品源码根> --out=<json>

- 全部走产品 HTTP 入口（TestClient）+ 受控模型替身，零真实出站；
- C05/C06 用"rag 候选只剩表格行"的形状（等价 live 每轮 1 次 query embedding 的后果），
  直接锁定"候选窗口 = 证据上界"这一根因，不依赖 embedding 门控的实现细节；
- N08 用最小装配（仅 D01 已发布）；
- 同时记录：模型调用次数、ask 前后所有表行数差分（证明零索引写入）、
  trace spans（证明 retrieve 真实执行而 answer 未调用）。
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

from sqlalchemy import text, select  # noqa: E402

from support import b0  # noqa: E402
from mktkb.documents.models import SourceUnit  # noqa: E402

FIX = ROOT / "fixtures" / "acceptance"
V03 = FIX / "variants" / "V03_物品位置表_历史V1.xlsx"
D01 = FIX / "normal" / "D01_物品位置表.xlsx"
V01 = FIX / "variants" / "V01_临时物料位置通知.pdf"
D02 = FIX / "normal" / "D02_合作店家信息.xlsx"
V02 = FIX / "variants" / "V02_店家联系方式变更通知.pdf"


def table_counts(harness) -> dict:
    db = harness.session()
    try:
        from sqlalchemy import inspect

        names = inspect(db.get_bind()).get_table_names()
        return {name: int(db.execute(text(f'select count(*) from "{name}"')).scalar() or 0) for name in names}
    finally:
        db.close()


def diff_counts(before: dict, after: dict) -> dict:
    out = {}
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            out[key] = [before.get(key), after.get(key)]
    return out


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


def unit_facts(harness, ids) -> list[dict]:
    keys = []
    for value in ids:
        try:
            keys.append(uuid.UUID(str(value)))
        except (TypeError, ValueError):
            continue
    if not keys:
        return []
    db = harness.session()
    try:
        rows = db.scalars(select(SourceUnit).where(SourceUnit.id.in_(keys))).all()
        return [
            {
                "unit_id": str(unit.id),
                "kind": str(unit.kind),
                "document_id": str(unit.document_id),
                "ordinal": int(unit.ordinal),
            }
            for unit in rows
        ]
    finally:
        db.close()


def table_row_ids(harness) -> set:
    db = harness.session()
    try:
        return {str(value) for value in db.scalars(select(SourceUnit.id).where(SourceUnit.kind == "table_row")).all()}
    finally:
        db.close()


def ask(harness, question: str, *, narrow: bool) -> dict:
    admin = harness.admin()
    employee = harness.employee()
    log: list[dict] = []
    qa = harness.app.state.qa
    original = qa.candidate_unit_ids_for_intent
    rows = table_row_ids(harness)
    if narrow:
        def wrapped(*, mode, terms=(), entity_filters=None):
            ids = original(mode=mode, terms=terms, entity_filters=entity_filters)
            kept = {str(item) for item in ids if str(item) in rows}
            log.append({"mode": mode, "terms": list(terms), "candidates": len(ids), "kept_table_rows": len(kept)})
            return kept

        qa.candidate_unit_ids_for_intent = wrapped
    try:
        before_counts = table_counts(harness)
        before_calls = len(harness.model.calls)
        conversation = b0.new_conversation(employee, "T207-VERIFY")
        response = b0.ask(employee, conversation, question)
        payload = response.json()
        trace_id = response.headers.get("X-Trace-ID")
        spans: list[str] = []
        trace_kind = None
        if trace_id:
            try:
                trace, span_rows = harness.app.state.trace_repo.get(trace_id)
                spans = [str(getattr(span, "name", "")) for span in span_rows]
                trace_kind = getattr(trace, "outcome_kind", None)
            except Exception as exc:  # noqa: BLE001
                spans = [f"trace_unavailable:{exc!r}"]
        after_counts = table_counts(harness)
        calls = harness.model.calls[before_calls:]
        return {
            "question": question,
            "narrow_candidates": narrow,
            "kind": payload.get("kind"),
            "text": payload.get("text"),
            "sources": [
                {"document_name": item.get("document_name"), "version_number": item.get("version_number")}
                for item in payload.get("sources") or []
            ],
            "source_ids": [str(item.get("source_id")) for item in payload.get("sources") or []],
            "conflicts": payload.get("conflicts") or [],
            "candidates": [item.get("label") for item in payload.get("candidates") or []],
            "model_calls": len(calls),
            "model_call_purposes": [call.get("purpose") for call in calls],
            "model_evidence_counts": [len(call.get("evidence") or []) for call in calls],
            "candidate_calls": log,
            "write_diff": diff_counts(before_counts, after_counts),
            "trace_id": trace_id,
            "trace_outcome_kind": trace_kind,
            "trace_spans": spans,
            "source_units": unit_facts(harness, [item.get("source_id") for item in payload.get("sources") or []]),
        }
    finally:
        qa.candidate_unit_ids_for_intent = original


def conflict_case(work: Path, *, variant: Path, base_doc: Path | None, question: str, narrow: bool, stacked: bool):
    harness = b0.new_harness(work)
    try:
        admin = harness.admin()
        if stacked:
            first = publish(harness, admin, path=V03)
            publish(harness, admin, path=base_doc, document_id=first["document"]["id"], expected_active=first["version"]["id"])
        elif base_doc is not None:
            publish(harness, admin, path=base_doc)
        publish(harness, admin, path=variant)
        return ask(harness, question, narrow=narrow)
    finally:
        harness.close()


def simple_case(work: Path, *, docs: list[Path], question: str):
    harness = b0.new_harness(work)
    try:
        admin = harness.admin()
        for doc in docs:
            publish(harness, admin, path=doc)
        return ask(harness, question, narrow=False)
    finally:
        harness.close()


def image_pattern_battery() -> dict:
    from mktkb.conversations import intent as intent_module

    probe = getattr(intent_module, "image_source_question", None)
    if probe is None:
        return {"available": False}
    corpus = {}
    for item in b0.QUESTIONS:
        corpus[item["id"]] = {"question": item["question"], "hit": bool(probe(item["question"]))}
    adversarial = [
        "根据物料领用通知图片要求先填写什么？",
        "根据物料领用通知图片，需要谁确认？",
        "根据活动申请扫描件里的图片内容，申请部门是什么？",
        "从物料位置表截图里能看出城东店海报的位置吗？",
        "组织架构图中市场部向谁汇报？",
        "流程图里第三步是谁审批？",
        "参照仓库安全须知图片，物料通道要求是什么？",
        "看图说城东店的海报在哪",
        "物料领用通知图片要求先填写什么？",
        "巡检照片重复使用或者跨店套用，会被认定成什么？",
        "照片里没有标记的物品放在哪",
        "依据图片资料，物料领用需要哪些步骤？",
        "根据资料里的示意图，活动申请要提前多久？",
        "海报的照片有没有？",
        "城东店海报的图片能发我吗？",
    ]
    return {
        "available": True,
        "corpus_hits": [key for key, value in corpus.items() if value["hit"]],
        "corpus": corpus,
        "adversarial": [{"question": text, "hit": bool(probe(text))} for text in adversarial],
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="t207v-"))
    result = {
        "src": SRC or str(ROOT / "backend" / "src"),
        "cases": {
            "C05_narrow": conflict_case(
                tmp / "c05n", variant=V01, base_doc=D01, question="城东店的宣传海报现在放在哪里？", narrow=True, stacked=True
            ),
            "C05_ungated": conflict_case(
                tmp / "c05u", variant=V01, base_doc=D01, question="城东店的宣传海报现在放在哪里？", narrow=False, stacked=True
            ),
            "C06_narrow": conflict_case(
                tmp / "c06n", variant=V02, base_doc=D02, question="城东店的联系电话是什么？", narrow=True, stacked=False
            ),
            "C06_ungated": conflict_case(
                tmp / "c06u", variant=V02, base_doc=D02, question="城东店的联系电话是什么？", narrow=False, stacked=False
            ),
            "N08": simple_case(tmp / "n08", docs=[D01], question="根据货架照片告诉我没有标记物品的位置"),
        },
        "image_pattern": image_pattern_battery(),
    }
    Path(OUT).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("ok ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
