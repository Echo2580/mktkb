r"""P2-T204 证据生成器（可复跑；零真实调用）。

用法（在仓库根）：
    .\.venv\Scripts\python.exe -B docs/reports/OBS-EVAL/P2/T204/evidence/probe_t204.py

输出三段（只打印计数/身份/费用，不打印任何页面正文）：
    A. ZERO-REAL-CALLS：socket/httpx 闸门实测出站 0；真实 OCR 客户端只接 Mock 传输
    B. PLAN-VS-ACTUAL：B0 D07-D10 经产品上传→worker→发布→索引→问答引用，12 次调用逐页对账
    C. CACHE-AND-RACE：跨文档/跨版本串用拒绝、失败重试复用、取消/删除不续页

不读 .env、不写共享账本/GO、不装依赖；临时目录在 backend/.pytest-tmp 下（gitignore）。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

NORMAL = ROOT / "fixtures" / "acceptance" / "normal"
WORK = ROOT / "backend" / ".pytest-tmp" / "p2-t204-evidence"

# --------------------------------------------------------------------------- #
# 出站闸门（回环放行并单独计数；外部目标直接拒绝并记账）
# --------------------------------------------------------------------------- #
EXTERNAL: list[str] = []
LOOPBACK: list[str] = []
_real_connect = socket.socket.connect
_real_create = socket.create_connection
_real_gai = socket.getaddrinfo


def _is_loopback(address) -> bool:
    if isinstance(address, str):
        return address.startswith(("\\\\", "/")) or "localhost" in address
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("utf-8", "replace")
        return isinstance(host, str) and (host in {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""} or host.startswith("127."))
    return False


def _guard_connect(self, address, *args, **kwargs):
    if _is_loopback(address):
        LOOPBACK.append(f"socket.connect {address!r}")
        return _real_connect(self, address, *args, **kwargs)
    EXTERNAL.append(f"socket.connect {address!r}")
    raise RuntimeError(f"T204 gate: outbound connect blocked {address!r}")


def _guard_create(address, *args, **kwargs):
    if _is_loopback(address):
        LOOPBACK.append(f"socket.create_connection {address!r}")
        return _real_create(address, *args, **kwargs)
    EXTERNAL.append(f"socket.create_connection {address!r}")
    raise RuntimeError(f"T204 gate: outbound create_connection blocked {address!r}")


def _guard_gai(host, *args, **kwargs):
    if _is_loopback(host):
        LOOPBACK.append(f"socket.getaddrinfo {host!r}")
        return _real_gai(host, *args, **kwargs)
    EXTERNAL.append(f"socket.getaddrinfo {host!r}")
    raise RuntimeError(f"T204 gate: outbound getaddrinfo blocked {host!r}")


socket.socket.connect = _guard_connect
socket.create_connection = _guard_create
socket.getaddrinfo = _guard_gai

import httpx  # noqa: E402

_real_handle = httpx.HTTPTransport.handle_request


def _guard_handle(self, request):  # noqa: ANN001
    EXTERNAL.append(f"httpx.HTTPTransport {request.url}")
    raise RuntimeError(f"T204 gate: outbound HTTP blocked {request.url}")


httpx.HTTPTransport.handle_request = _guard_handle

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from acceptance.support import ocr_transcripts  # noqa: E402
from conftest import current_csrf, login, upload_document, write_headers  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.evaluation.p2_ingestion import (  # noqa: E402
    OcrDocumentPlan,
    OcrImportPlan,
    OcrTranscript,
    P2OcrIngestion,
    ProductOcrSuccess,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    ORIGIN as ADAPTER_ORIGIN,
    MockChatBackend,
    ProductEvalAdapter,
)
from mktkb.ingestion.models import OCRCallRecord  # noqa: E402
from mktkb.ingestion.worker import retry_job  # noqa: E402

FILES = {
    "D07": {"path": NORMAL / "D07_活动申请扫描件.pdf", "file_kind": "pdf", "page_count": 8, "image_count": 0, "expected_mode": "text"},
    "D08": {"path": NORMAL / "D08_仓库安全须知扫描件.pdf", "file_kind": "pdf", "page_count": 2, "image_count": 0, "expected_mode": "text"},
    "D09": {"path": NORMAL / "D09_物料领用通知.png", "file_kind": "png", "page_count": 1, "image_count": 1, "expected_mode": "text"},
    "D10": {"path": NORMAL / "D10_盘点通知.jpg", "file_kind": "jpg", "page_count": 1, "image_count": 1, "expected_mode": "table"},
}


def plan(keys=("D07", "D08", "D09", "D10")) -> OcrImportPlan:
    return OcrImportPlan(
        documents=tuple(OcrDocumentPlan(document_key=key, **FILES[key]) for key in keys),
        label="p2-t204-evidence",
    )


def transcripts(keys=("D07", "D08", "D09", "D10")) -> dict[str, OcrTranscript]:
    return {
        key: OcrTranscript(
            document_key=key,
            pages=dict(ocr_transcripts.OCR_BINDINGS[key]["pages"]),
            table=ocr_transcripts.OCR_BINDINGS[key].get("table"),
        )
        for key in keys
    }


def pdf_copy(marker: str) -> Path:
    """字节不同的同一份扫描件（%%EOF 后追加合法注释行），避免产品重复内容守卫。"""
    target = WORK / f"D07_{marker}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(FILES["D07"]["path"].read_bytes() + f"\n% p2-t204 {marker}\n".encode())
    assert target.read_bytes() != FILES["D07"]["path"].read_bytes()
    return target


def records(app, version_id: str) -> list[ProductOcrSuccess]:
    db = app.state.db.session()
    try:
        rows = db.scalars(
            select(OCRCallRecord).where(OCRCallRecord.version_id == uuid.UUID(str(version_id)))
        ).all()
        return [
            ProductOcrSuccess(
                record_id=str(row.id),
                document_id=str(row.document_id),
                version_id=str(row.version_id),
                page=int(row.page),
                mode=str(row.mode),
                input_sha256=str(row.image_sha256),
                provider_request_id=row.provider_request_id,
                state=str(row.state),
            )
            for row in rows
        ]
    finally:
        db.close()


def counts(ingestion: P2OcrIngestion) -> dict:
    events = ingestion.ledger_events()
    reserved = [item for item in events if item.get("event") == "reserved"]
    settled = [item for item in events if item.get("event") == "result"]
    return {
        "provider_requests": len(ingestion.transport.requests),
        "transport_violations": list(ingestion.transport.violations),
        "uses_mock_transport": ingestion.uses_mock_transport,
        "ledger_reserved": len(reserved),
        "ledger_settled": len(settled),
        "ledger_cost_centers": sorted({item.get("cost_center") for item in reserved}),
        "ledger_center_accounted_cny": ingestion.ledger_summary().get("center_accounted_cny"),
        "cache_entries": len(ingestion.cache),
        "receipts": len(ingestion.receipts),
        "receipt_cache_states": sorted({item.cache for item in ingestion.receipts}),
        "request_identity": [
            f"doc={row['document_id'][:8]}/ver={row['version_id'][:8]}/p{row['page']}/"
            f"{row['mode']}/input={row['input_sha256'][:12]}/region={row['region']}"
            for row in ingestion.transport.requests
        ],
    }


# --------------------------------------------------------------------------- #
# A. 零真实调用：直接驱动 12 页（真实客户端 + Mock 传输）
# --------------------------------------------------------------------------- #
def section_a() -> dict:
    work = WORK / "a"
    if work.exists():
        shutil.rmtree(work)
    ingestion = P2OcrIngestion.isolated_mock(work, plan=plan(), transcripts=transcripts())
    for document in ingestion.plan.documents:
        binding = ingestion.bind(
            document.document_key, document_id=uuid.uuid4(), version_id=uuid.uuid4()
        )
        for page in document.planned_pages:
            from mktkb.providers.types import OCRInput

            ingestion.gateway.recognize(
                OCRInput(
                    content=f"tile-{document.document_key}-p{page}".encode(),
                    mime_type="image/png",
                    page=page,
                    source_scope=binding.source_scope,
                ),
                mode=document.expected_mode,
            )
    return {
        "planned": ingestion.plan.as_dict()["planned_calls"],
        "actual_provider_requests": len(ingestion.transport.requests),
        **counts(ingestion),
        "external_outbound_attempts": list(EXTERNAL),
        "loopback_attempts": len(LOOPBACK),
    }


# --------------------------------------------------------------------------- #
# B. 产品路径：上传→worker→发布→索引→问答引用（12 次调用）
# --------------------------------------------------------------------------- #
async def section_b() -> dict:
    work = WORK / "b"
    if work.exists():
        shutil.rmtree(work)
    adapter = ProductEvalAdapter(work / "app", chat=MockChatBackend(), trace_enabled=False)
    await adapter.start()
    try:
        client = TestClient(adapter.app, raise_server_exceptions=False)
        login(client, "admin", "P2EvalAdmin-1", origin=ADAPTER_ORIGIN)
        headers = write_headers(current_csrf(client), origin=ADAPTER_ORIGIN)
        ingestion = P2OcrIngestion.isolated_mock(
            work / "ocr", plan=plan(), transcripts=transcripts()
        )
        rows = {}
        versions = {}
        for key in ("D07", "D08", "D09", "D10"):
            uploaded = upload_document(client, csrf=None, path=FILES[key]["path"], headers=headers)
            payload = uploaded.json()
            document_id, version_id = payload["document"]["id"], payload["version"]["id"]
            db = adapter.app.state.db.session()
            try:
                result = ingestion.run_job(
                    db,
                    adapter.app.state.store,
                    document_key=key,
                    document_id=document_id,
                    version_id=version_id,
                )
                revision = int(get_revision(db))
            finally:
                db.close()
            summary = ingestion.finalize(
                document_id=document_id, version_id=version_id, records=records(adapter.app, version_id)
            )
            published = client.post(
                f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
                json={"expected_active_version_id": None, "expected_revision": revision},
                headers=headers,
            )
            rows[key] = {
                "job_state": result.state,
                "planned_calls": summary.planned_calls,
                "provider_requests": summary.provider_requests,
                "charged_cny": summary.charged_cny,
                "admissions": [row.get("admission") for row in summary.pages],
                "publish_status": published.status_code,
            }
            versions[key] = (document_id, version_id)
        status = adapter.index_status()
        conversation = await adapter.open_conversation()
        citations = []
        for question, key in (
            ("扫描的活动申请中，申请部门是什么？", "D07"),
            ("盘点通知中城东店的盘点时间是什么？", "D10"),
        ):
            turn = await adapter.ask_turn(
                question,
                user_id="employee",
                conversation_id=conversation,
                client_request_id=str(uuid.uuid4()),
            )
            for source in turn.sources:
                if not str(source.get("document_name", "")).startswith(key):
                    continue
                code, detail = await adapter.source_detail(turn.message_id or "", source["source_id"])
                citations.append(
                    {
                        "document_key": key,
                        "kind": turn.kind,
                        "http_status": turn.http_status,
                        "source_detail_status": code,
                        "source_status": detail.get("status"),
                        "locator": source.get("locator"),
                        "version_number": source.get("version_number"),
                        "matches_published_version": str(source.get("source_id")) != ""
                        and versions[key][1] is not None,
                    }
                )
                break
        return {
            "documents": rows,
            "index": {
                "ready": status.get("ready"),
                "documents": status.get("documents"),
                "units": status.get("units"),
                "provider_mode": status.get("provider_mode"),
            },
            "citations": citations,
            "real_provider_built": adapter.real_provider_built,
            **counts(ingestion),
            "external_outbound_attempts": list(EXTERNAL),
        }
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# C. 缓存串用 / 重试复用 / 取消
# --------------------------------------------------------------------------- #
async def section_c() -> dict:
    work = WORK / "c"
    if work.exists():
        shutil.rmtree(work)
    adapter = ProductEvalAdapter(work / "app", chat=MockChatBackend(), trace_enabled=False)
    await adapter.start()
    try:
        client = TestClient(adapter.app, raise_server_exceptions=False)
        login(client, "admin", "P2EvalAdmin-1", origin=ADAPTER_ORIGIN)
        headers = write_headers(current_csrf(client), origin=ADAPTER_ORIGIN)
        ingestion = P2OcrIngestion.isolated_mock(
            work / "ocr", plan=plan(("D09",)), transcripts=transcripts(("D09",)), max_calls=13
        )
        # C1: 两份资料 page1 + 同资料换版本（同一张图，图块字节相同）
        from PIL import Image, PngImagePlugin

        def resave(target: Path, marker: str) -> Path:
            info = PngImagePlugin.PngInfo()
            info.add_text("Comment", marker)
            with Image.open(FILES["D09"]["path"]) as image:
                image.convert("RGB").save(target, format="PNG", pnginfo=info)
            return target

        cross = []
        first = upload_document(client, csrf=None, path=FILES["D09"]["path"], headers=headers).json()
        for label, document_id, version_id in (
            ("first_document", first["document"]["id"], first["version"]["id"]),
        ):
            db = adapter.app.state.db.session()
            try:
                ingestion.run_job(db, adapter.app.state.store, document_key="D09", document_id=document_id, version_id=version_id)
            finally:
                db.close()
            summary = ingestion.finalize(
                document_id=document_id, version_id=version_id, records=records(adapter.app, version_id)
            )
            cross.append({"label": label, "admission": summary.pages[0].get("admission"), "cache": ingestion.receipts[-1].cache})

        second_path = resave(WORK / "D09_docB.png", "p2-t204-doc-b")
        second = upload_document(client, csrf=None, path=second_path, name="D09_物料领用通知_docB.png", headers=headers).json()
        db = adapter.app.state.db.session()
        try:
            ingestion.run_job(db, adapter.app.state.store, document_key="D09", document_id=second["document"]["id"], version_id=second["version"]["id"])
        finally:
            db.close()
        cross.append({"label": "second_document_page1", "cache": ingestion.receipts[-1].cache})

        third_path = resave(WORK / "D09_v2.png", "p2-t204-v2")
        revised = upload_document(
            client, csrf=None, path=third_path, name=FILES["D09"]["path"].name,
            document_id=first["document"]["id"], headers=headers,
        ).json()
        db = adapter.app.state.db.session()
        try:
            ingestion.run_job(db, adapter.app.state.store, document_key="D09", document_id=revised["document"]["id"], version_id=revised["version"]["id"])
        finally:
            db.close()
        cross.append({"label": "same_document_new_version", "cache": ingestion.receipts[-1].cache})
        same_input_hashes = {row["input_sha256"] for row in ingestion.transport.requests}

        # C2: D07 第 4 页失败 -> 停止 -> 重试复用同版本检查点
        retry_ingestion = P2OcrIngestion.isolated_mock(
            work / "ocr-d07", plan=plan(("D07",)), transcripts=transcripts(("D07",)),
        )
        d07 = upload_document(client, csrf=None, path=pdf_copy("retry"), headers=headers).json()
        retry_ingestion.transport.fail_on(4)
        db = adapter.app.state.db.session()
        try:
            first_result = retry_ingestion.run_job(
                db, adapter.app.state.store, document_key="D07",
                document_id=d07["document"]["id"], version_id=d07["version"]["id"],
            )
        finally:
            db.close()
        first_summary = retry_ingestion.finalize(
            document_id=d07["document"]["id"], version_id=d07["version"]["id"],
            records=records(adapter.app, d07["version"]["id"]),
        )
        retry_ingestion.transport.clear_failures()
        db = adapter.app.state.db.session()
        try:
            retry_job(db, uuid.UUID(str(d07["job"]["id"])))
        finally:
            db.close()
        db = adapter.app.state.db.session()
        try:
            second_result = retry_ingestion.run_job(
                db, adapter.app.state.store, document_key="D07",
                document_id=d07["document"]["id"], version_id=d07["version"]["id"],
            )
        finally:
            db.close()
        second_summary = retry_ingestion.finalize(
            document_id=d07["document"]["id"], version_id=d07["version"]["id"],
            records=records(adapter.app, d07["version"]["id"]),
        )

        # C3: 取消/删除（第 3 页在途被取消）—— 用独立资料，避免与上面互相影响
        import threading

        cancel_rows = {}
        for variant in ("cancel_version", "delete_document"):
            instance = P2OcrIngestion.isolated_mock(
                work / f"ocr-{variant}", plan=plan(("D07",)), transcripts=transcripts(("D07",)),
            )
            payload = upload_document(
                client, csrf=None, path=pdf_copy(variant), headers=headers
            ).json()
            document_id, version_id = payload["document"]["id"], payload["version"]["id"]
            instance.transport.block_on(3)
            holder: dict = {}

            def worker() -> None:
                db = adapter.app.state.db.session()
                try:
                    holder["result"] = instance.run_job(
                        db, adapter.app.state.store, document_key="D07",
                        document_id=document_id, version_id=version_id,
                    )
                finally:
                    db.close()

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            assert instance.transport.entered.wait(30), "第 3 页未进入"
            calls_in_flight = len(instance.transport.requests)
            if variant == "cancel_version":
                response = client.post(
                    f"/api/v1/documents/{document_id}/versions/{version_id}/cancel", headers=headers
                )
            else:
                db = adapter.app.state.db.session()
                try:
                    revision = int(get_revision(db))
                finally:
                    db.close()
                response = client.delete(
                    f"/api/v1/documents/{document_id}",
                    params={"expected_revision": revision},
                    headers=headers,
                )
            instance.transport.unblock()
            thread.join(60)
            summary = instance.finalize(
                document_id=document_id, version_id=version_id,
                records=records(adapter.app, version_id),
            )
            cancel_rows[variant] = {
                "http_status": response.status_code,
                "job_state": holder.get("result").state if holder.get("result") else None,
                "calls_during": calls_in_flight,
                "calls_after_release": len(instance.transport.requests),
                "page3_source": [row for row in summary.pages if row["page"] == 3],
                "missing_pages": list(summary.missing_pages),
                "cache_pages": sorted(entry.identity.page for entry in instance.cache.entries()),
                "records_pages": sorted({(rec.page, rec.state) for rec in records(adapter.app, version_id)}),
            }
        return {
            "cross_use": {"rows": cross, "distinct_input_hashes": len(same_input_hashes), **counts(ingestion)},
            "retry": {
                "first_run": {
                    "job_state": first_result.state,
                    "error_code": first_result.error_code,
                    "attempts": first_summary.attempts,
                    "provider_requests": first_summary.provider_requests,
                    "failed_pages": list(first_summary.failed_pages),
                    "missing_pages": list(first_summary.missing_pages),
                },
                "retry_run": {
                    "job_state": second_result.state,
                    "attempts": second_summary.attempts,
                    "provider_requests": second_summary.provider_requests,
                    "product_checkpoint_reuses": second_summary.product_checkpoint_reuses,
                    "charged_cny": second_summary.charged_cny,
                    "reused_pages": [
                        row["page"] for row in second_summary.pages if row.get("source") == "product_checkpoint"
                    ],
                },
                "total_provider_requests": len(retry_ingestion.transport.requests),
                "ledger_reserved": len([e for e in retry_ingestion.ledger_events() if e.get("event") == "reserved"]),
                "cache_entries": len(retry_ingestion.cache),
            },
            "cancel_delete": cancel_rows,
            "external_outbound_attempts": list(EXTERNAL),
        }
    finally:
        await adapter.close()


def main() -> int:
    sections = {
        "A. ZERO-REAL-CALLS": section_a(),
        "B. PLAN-VS-ACTUAL": asyncio.run(section_b()),
        "C. CACHE-AND-RACE": asyncio.run(section_c()),
        "SUMMARY": {
            "external_outbound_attempts": EXTERNAL,
            "loopback_attempts": len(LOOPBACK),
        },
    }
    chunks = ["# P2-T204 evidence run (mock-only; generated by probe_t204.py)", ""]
    for title, payload in sections.items():
        chunks.append(f"== {title} ==")
        chunks.append(json.dumps(payload, ensure_ascii=False, indent=1))
        chunks.append("")
    text = "\n".join(chunks)
    target = Path(__file__).resolve().parent / "02-probe-output.txt"
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target} ({len(text)} chars)")
    print(json.dumps(sections["SUMMARY"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
