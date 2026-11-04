"""S2-K-R1A 定向测试：生产 worker 的 OcrExecutor 用可信 document/version 来源锚。

真实产品 DB + 上传产生的 Document/Version 行（pytest 隔离目录），只使用本地 OCR 替身：
- OcrExecutor 无条件用 worker 实际持有的 document/version 覆盖 OCRInput 中伪造的 source_scope；
- 检查点仍按 version+page+mode+bbox+image_sha 复用，命中时 0 新增网关调用；
- 不同 document/version 不复用陈旧结果，且各自携带可信来源锚；
- 经真实 BudgetedOCRGateway 时，同一文档同页第二个 tile 仍在预留/发送前拒绝。

不发真实网络、不读 `.env`、不写真实共享账本/预算/GO。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from mktkb.ingestion.worker import OcrExecutor
from mktkb.providers.ocr_budgeted import BudgetedOCRGateway, OCRBudgetRefused
from mktkb.providers.types import OCRInput, OCRPageResult, make_ocr_source_scope
from mktkb.rag.budget import BudgetLedger

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D09 = FIXTURES / "normal" / "D09_物料领用通知.png"
D10 = FIXTURES / "normal" / "D10_盘点通知.jpg"
STAGE = "S2-K-R1A-WORKER-TEST"


class FakeOCRGateway:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def recognize(self, page: OCRInput, *, mode: str) -> OCRPageResult:
        self.calls.append({"page": int(page.page), "mode": str(mode), "source_scope": page.source_scope})
        return OCRPageResult(text=f"识别文本-{page.page}", provider_request_id=f"req-{len(self.calls)}")


class RecordingGateway:
    """Transparent proxy: records the page object the real OcrExecutor hands to a gateway."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls: list[dict] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def recognize(self, page, *, mode):
        self.calls.append({"page": getattr(page, "page", None), "mode": mode, "source_scope": getattr(page, "source_scope", None)})
        return self._inner.recognize(page, mode=mode)


def _uploaded(admin_write, path: Path) -> tuple[uuid.UUID, uuid.UUID]:
    receipt = admin_write.upload(path=path, name=path.name)
    assert receipt.status_code == 202, receipt.text
    payload = receipt.json()
    return uuid.UUID(payload["document"]["id"]), uuid.UUID(payload["version"]["id"])


def _executor(app, document_id, version_id, gateway, db) -> OcrExecutor:
    return OcrExecutor(
        db,
        version_id=version_id,
        document_id=document_id,
        gateway=gateway,
        ensure_live=lambda: None,
    )


def _ledger(tmp_path: Path, *, stage_limit: float = 9.66) -> BudgetLedger:
    ledger_path = tmp_path / "live-ledger.jsonl"
    budget_path = tmp_path / "budget.json"
    ledger_path.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": 0.03, "provider_billed_cny": None}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    budget_path.write_text(
        json.dumps(
            {
                "limit_cny": 10.0,
                "historical_conservative_accounted_cny": 0.03,
                "stages": {STAGE: stage_limit},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return BudgetLedger(ledger_path, budget_path, stage=STAGE, stage_limit_cny=stage_limit, max_requests=400)


def test_worker_executor_attaches_trusted_scope_and_overrides_forged(app, admin_write):
    document_id, version_id = _uploaded(admin_write, D10)
    fake = FakeOCRGateway()
    recording = RecordingGateway(fake)
    forged = make_ocr_source_scope("forged-document", "forged-version")
    trusted = make_ocr_source_scope(document_id, version_id)
    db = app.state.db.session()
    try:
        executor = _executor(app, document_id, version_id, recording, db)
        result = executor.recognize(
            OCRInput(content=b"kr1a-page-tile", mime_type="image/png", page=1, bbox=None, source_scope=forged),
            mode="table",
        )
    finally:
        db.close()
    assert result.text == "识别文本-1"
    assert len(recording.calls) == 1
    assert recording.calls[0]["source_scope"] == trusted != forged


def test_checkpoint_reuse_issue_no_new_gateway_call(app, admin_write):
    document_id, version_id = _uploaded(admin_write, D10)
    fake = FakeOCRGateway()
    recording = RecordingGateway(fake)
    db = app.state.db.session()
    try:
        executor = _executor(app, document_id, version_id, recording, db)
        source = OCRInput(content=b"same-tile-bytes", mime_type="image/png", page=1, bbox=None, source_scope="forged")
        first = executor.recognize(source, mode="text")
        second = executor.recognize(source, mode="text")
    finally:
        db.close()
    assert first.text == second.text == "识别文本-1"
    assert len(recording.calls) == 1, "同一 version 同页同图必须命中 DB checkpoints，0 新增网关调用"


def test_other_document_does_not_reuse_stale_checkpoint(app, admin_write):
    d10_doc, d10_ver = _uploaded(admin_write, D10)
    d09_doc, d09_ver = _uploaded(admin_write, D09)
    fake = FakeOCRGateway()
    recording = RecordingGateway(fake)
    db = app.state.db.session()
    try:
        source = OCRInput(content=b"shared-tile-bytes", mime_type="image/png", page=1, bbox=None)
        _executor(app, d10_doc, d10_ver, recording, db).recognize(source, mode="text")
        _executor(app, d09_doc, d09_ver, recording, db).recognize(source, mode="text")
    finally:
        db.close()
    assert len(recording.calls) == 2, "另一个 document 必须重新调用，不命中陈旧结果"
    assert recording.calls[0]["source_scope"] == make_ocr_source_scope(d10_doc, d10_ver)
    assert recording.calls[1]["source_scope"] == make_ocr_source_scope(d09_doc, d09_ver)


def test_same_document_second_tile_refused_through_real_executor(app, admin_write, tmp_path):
    document_id, version_id = _uploaded(admin_write, D10)
    ledger = _ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = BudgetedOCRGateway(inner, ledger=ledger, max_calls=13, max_tiles_per_page=1, attempts=1)
    db = app.state.db.session()
    try:
        executor = _executor(app, document_id, version_id, gateway, db)
        first = executor.recognize(
            OCRInput(content=b"first-tile", mime_type="image/png", page=1, bbox=None),
            mode="table",
        )
        with pytest.raises(OCRBudgetRefused):
            executor.recognize(
                OCRInput(content=b"first-tile", mime_type="image/png", page=1, bbox=(0.0, 0.0, 10.0, 10.0)),
                mode="table",
            )
    finally:
        db.close()
    assert first.text == "识别文本-1"
    assert inner.calls == [{"page": 1, "mode": "table", "source_scope": make_ocr_source_scope(document_id, version_id)}]
    stats = gateway.stats()
    assert stats["calls"] == 1
    assert stats["tiles_by_source_page"] == {make_ocr_source_scope(document_id, version_id): {1: 1}}
    reserved = [
        json.loads(line)
        for line in ledger.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("event") == "reserved"
    ]
    assert len(reserved) == 1
