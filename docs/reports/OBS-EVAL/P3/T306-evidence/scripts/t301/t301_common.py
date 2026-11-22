"""T301 隔离环境公共装配：路径、Settings、可控模型替身、会话与上传辅助。

边界：
- 所有文件只落到 ``T301-isolated/evidence/data`` 内；绝不读写仓库 ``var/`` 业务库。
- 模型/OCR/Ragas 一律替身，不发起真实付费调用；``_env_file=None`` 避免读取仓库 ``.env``。
- 本模块不引用 ``backend/tests`` 下的 fixture（隔离目录独立 sys.path），替身在此自包含。
"""

from __future__ import annotations

import asyncio
import io
import sys
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

#: T301-isolated 目录（本文件位于 scripts/ 下）
#: T306 复算副本：只读取 T301 冻结目录，输出改到 T306-evidence/recompute-t301。
T301_ROOT = Path(r"D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P3\T301-isolated")
T306_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = T301_ROOT / "evidence"
DATA_DIR = EVIDENCE_DIR / "data"
MATRIX_DIR = EVIDENCE_DIR / "matrix"
RECOMPUTE_DIR = T306_ROOT / "recompute-t301"
TRACE_DIR = EVIDENCE_DIR / "trace"
PYTEST_DIR = EVIDENCE_DIR / "pytest"

#: 仓库根（T301-isolated → P3 → OBS-EVAL → docs → 仓库根）
REPO_ROOT = T301_ROOT.parents[4]
BACKEND_ROOT = REPO_ROOT / "backend"
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "acceptance"

#: 隔离库固定路径（与业务 var/ 完全分离）
BUSINESS_DB = DATA_DIR / "mktkb.sqlite3"
RAG_INDEX_DB = DATA_DIR / "rag-index.sqlite3"
TRACE_DB = DATA_DIR / "qa-traces.sqlite3"
STORAGE_DIR = DATA_DIR / "storage"

ORIGIN = "http://testserver"


def ensure_sys_path() -> None:
    """把 backend/src 加入导入路径（pytest 从 backend/ 运行时也兜底）。"""
    src = BACKEND_ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


ensure_sys_path()

#: 在导入 mktkb 前关闭 .env 读取（与既有测试隔离约定一致）。
from mktkb.config import Settings  # noqa: E402

Settings.model_config = {**Settings.model_config, "env_file": None}

from mktkb.db import run_migrations  # noqa: E402
from mktkb.main import create_app  # noqa: E402
from mktkb.providers.types import CompletionOutput, ModelUnavailable  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402


def build_settings(*, trace_enabled: bool) -> Settings:
    """构造指向隔离目录的 Settings；秘密值均为测试固定值，不来自 .env。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return Settings(
        _env_file=None,
        data_dir=DATA_DIR,
        database_url=f"sqlite:///{BUSINESS_DB.as_posix()}",
        rag_index_path=RAG_INDEX_DB,
        trace_db_path=TRACE_DB,
        storage_dir=STORAGE_DIR,
        cookie_secure=False,
        csrf_secret="t301-isolated-csrf-secret-0123456789",
        admin_password="AdminPass-1",
        employee_password="EmployeePass-1",
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="WARNING",
        trace_enabled=trace_enabled,
        rag_provider_mode="offline",
        ocr_disabled=True,
    )


class MockGateway:
    """可控模型替身：回显证据；可注入错误 / 固定文本 / 固定来源。零真实调用。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None
        self.answer_text: str | None = None
        self.source_ids: tuple[str, ...] | None = None
        self.expansion_terms: tuple[str, ...] = ()

    async def complete(self, request, *, timeout_seconds: float) -> CompletionOutput:
        self.calls.append(
            {
                "purpose": request.purpose,
                "question": request.question,
                "evidence": [
                    {"source_id": item.source_id, "fields": dict(item.fields)}
                    for item in request.evidence
                ],
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        if request.purpose == "query_expansion":
            return CompletionOutput(text="expansion", query_terms=tuple(self.expansion_terms))
        text = self.answer_text if self.answer_text is not None else _compose_answer(request)
        source_ids = self.source_ids if self.source_ids is not None else tuple(
            item.source_id for item in request.evidence
        )
        return CompletionOutput(text=text, source_ids=tuple(source_ids))


def _compose_answer(request) -> str:
    parts: list[str] = []
    for item in request.evidence[:8]:
        if item.fields:
            pairs = "；".join(f"{key}：{value}" for key, value in list(item.fields.items())[:12])
            parts.append(pairs)
        elif item.text:
            parts.append(item.text)
    return "根据资料：" + "；".join(parts)


class Session:
    """登录会话 + CSRF + 上传/问答便捷方法（TestClient 正常接口链路）。"""

    def __init__(self, app: Any, username: str, password: str) -> None:
        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)
        response = self.client.post(
            "/api/v1/auth/login", json={"username": username, "password": password},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 200, response.text
        me = self.client.get("/api/v1/auth/me")
        assert me.status_code == 200, me.text
        self.csrf = me.json()["csrf_token"]
        self.headers = {"Origin": ORIGIN, "X-CSRF-Token": self.csrf}

    def upload(
        self,
        *,
        path: Path | None = None,
        content: bytes | None = None,
        name: str | None = None,
        document_id: str | None = None,
        expected_active_version_id: str | None = None,
    ) -> Any:
        if content is None:
            assert path is not None
            content = Path(path).read_bytes()
        filename = name or (Path(path).name if path is not None else "upload.bin")
        data: dict[str, str] = {}
        if document_id is not None:
            data["document_id"] = document_id
        if expected_active_version_id is not None:
            data["expected_active_version_id"] = str(expected_active_version_id)
        url = "/api/v1/documents" if document_id is None else f"/api/v1/documents/{document_id}/versions"
        return self.client.post(
            url,
            files={"file": (filename, content, "application/octet-stream")},
            data=data,
            headers=self.headers,
        )

    def create_conversation(self) -> str:
        response = self.client.post("/api/v1/conversations", json={}, headers=self.headers)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def ask(self, conversation_id: str, question: str, client_request_id: uuid.UUID | None = None):
        payload = {
            "client_request_id": str(client_request_id or uuid.uuid4()),
            "question": question,
        }
        return self.client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json=payload,
            headers=self.headers,
        )

    def delete_conversation(self, conversation_id: str):
        return self.client.delete(
            f"/api/v1/conversations/{conversation_id}", headers=self.headers
        )

    def messages(self, conversation_id: str):
        response = self.client.get(f"/api/v1/conversations/{conversation_id}/messages")
        assert response.status_code == 200, response.text
        return response.json()


def run_worker(app: Any):
    db = app.state.db.session()
    try:
        return run_one_job(db, app.state.store)
    finally:
        db.close()


def current_revision(app: Any) -> int:
    from mktkb.documents.lifecycle import get_revision

    db = app.state.db.session()
    try:
        return get_revision(db)
    finally:
        db.close()


def publish(app: Any, admin: Session, document_id: str, version_id: str,
            expected_active_version_id: str | None = None) -> dict[str, Any]:
    response = admin.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        headers=admin.headers,
        json={
            "expected_active_version_id": expected_active_version_id,
            "expected_revision": current_revision(app),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def upload_published(app: Any, admin: Session, *, path: Path | None = None,
                     content: bytes | None = None, name: str | None = None,
                     document_id: str | None = None,
                     expected_active_version_id: str | None = None) -> dict[str, Any]:
    receipt = admin.upload(
        path=path, content=content, name=name, document_id=document_id,
        expected_active_version_id=expected_active_version_id,
    )
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    job = run_worker(app)
    assert job.state == "succeeded", f"基线资料导入失败：{job.state} {job.error_code}"
    publish(
        app, admin, record["document"]["id"], record["version"]["id"],
        expected_active_version_id=expected_active_version_id,
    )
    return {"record": record, "job_state": job.state, "job_error_code": job.error_code}


# ---- 受控构造的离线 xlsx ----


def _xlsx_bytes(rows_by_sheet: list[tuple[str, list[list[object]]]],
                hidden: set[str] | None = None) -> bytes:
    import openpyxl

    workbook = openpyxl.Workbook()
    first = True
    hidden = hidden or set()
    for title, rows in rows_by_sheet:
        worksheet = workbook.active if first else workbook.create_sheet()
        first = False
        worksheet.title = title
        if title in hidden:
            worksheet.sheet_state = "hidden"
        for row in rows:
            worksheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def conflict_xlsx_bytes(rows: list[list[object]]) -> bytes:
    """冲突资料：与 D01 同表头（标识/门店/物品/别名/位置）。"""
    return _xlsx_bytes([
        ("物品位置", [["标识", "门店", "物品", "别名", "位置"], *rows])
    ])


def uncached_formula_xlsx_bytes() -> bytes:
    """无缓存公式表 → 整单失败（PARSE_INCOMPLETE）。"""
    return _xlsx_bytes([
        ("正常表", [["编号", "位置"], ["P900", "A区"]]),
        ("无缓存公式", [["=1+1", "=2+2"]]),
    ])


def cached_formula_xlsx_bytes() -> bytes:
    """带已保存缓存的公式行 → 任务成功，版本落 review_required。"""
    source = _xlsx_bytes([("缓存公式", [["标识", "结果"], ["R1", "=1+2"]])])
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as src, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                text = data.decode("utf-8")
                assert "<f>1+2</f>" in text
                data = text.replace("<f>1+2</f>", "<f>1+2</f><v>150</v>").encode("utf-8")
            dst.writestr(item, data)
    return buffer.getvalue()


def reset_isolated_data_dir() -> None:
    """清空隔离库与存储（仅本目录内），保证每次样本生成幂等可复算。"""
    for candidate in (BUSINESS_DB, RAG_INDEX_DB, TRACE_DB):
        for suffix in ("", "-wal", "-shm"):
            target = Path(str(candidate) + suffix)
            if target.exists():
                target.unlink()
    if STORAGE_DIR.exists():
        for child in sorted(STORAGE_DIR.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
