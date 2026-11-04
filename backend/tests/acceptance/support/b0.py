"""T09-D1 B0 基线装配、受控网关、快照恢复与逐题执行/判分。

设计约束：
- 装配只用显式 ``Settings``（``_env_file=None`` + 假密钥 + 指向不可达本地端口的 base_url），
  任何路径都不会回落到项目 ``.env`` 的真实模型/OCR 配置；
- 模型与 OCR 都由注入的受控替身承担：模型只回显本次证据（``conftest.EvidenceEchoGateway``），
  OCR 只返回 ``ocr_transcripts`` 的受控转录；两者都不内置验收答案；
- 上传→worker→发布→检索→问答全部走真实本地实现（HTTP/ASGI、SQLite、解析器、worker、T05 检索）；
- B0 只按 ``manifest.b0_initialization`` 的 33 步执行（V03 历史 V1 → D01 业务 V2 同槽，其余 8 份首次导入）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from mktkb.config import Settings
from mktkb.documents.lifecycle import get_revision
from mktkb.ingestion.worker import run_one_job
from mktkb.main import create_app
from mktkb.providers.types import OCRPageResult

from conftest import ORIGIN, EvidenceEchoGateway, current_csrf, login, upload_document, write_headers

from . import evidence, ocr_transcripts

# ---- 显式假配置：即使被误用也连不到真实服务（端口 9 为 discard） ----
FAKE_MODEL_API_KEY = "sk-t09-fake-model-key-never-real-000000"
FAKE_MODEL_BASE_URL = "http://127.0.0.1:9/t09-fake-model-never-called"
FAKE_MODEL_NAME = "t09-fake-model-never-called"
FAKE_OCR_SECRET_ID = "T09FAKEOCRIDNEVERREAL0000"
FAKE_OCR_SECRET_KEY = "t09-fake-ocr-key-never-real-0000"
# 配置校验要求 ocr_endpoint 必须是腾讯云官方 HTTPS 域名，故保留官方主机名；
# 凭据为假值，且本轮由 netguard 保证 0 次出站（见 support/netguard.py）。
FAKE_OCR_ENDPOINT = "https://ocr.tencentcloudapi.com"
ADMIN_PASSWORD = "AdminPass-1"
EMPLOYEE_PASSWORD = "EmployeePass-1"

MANIFEST = evidence.load_manifest()
QUESTIONS = evidence.load_questions()
FILE_INDEX: dict[str, dict] = {entry["id"]: entry for entry in MANIFEST["normal_files"]}
FILE_INDEX.update({entry["id"]: entry for entry in MANIFEST["variants"]})
B0_STEPS: list[dict] = MANIFEST["b0_initialization"]["steps"]
B0_SLOTS: dict = MANIFEST["b0_initialization"]["logical_slots"]


def fixture_path(file_id: str) -> Path:
    entry = FILE_INDEX[file_id]
    return evidence.FIXTURES / entry["path"]


def make_settings(data_dir: Path, *, with_gateways: bool = True) -> Settings:
    """显式配置：不改环境、不读 .env。

    ``with_gateways=False`` 时把模型/OCR 三项配置全部置空，用于验证"未配置"的稳定错误映射
    （此时 create_app 不注入替身，``build_gateway``/``build_ocr_gateway`` 返回 None）。
    """
    data_dir = Path(data_dir)
    gateway_kwargs = (
        {
            "model_base_url": FAKE_MODEL_BASE_URL,
            "model_name": FAKE_MODEL_NAME,
            "model_api_key": FAKE_MODEL_API_KEY,
            "ocr_secret_id": FAKE_OCR_SECRET_ID,
            "ocr_secret_key": FAKE_OCR_SECRET_KEY,
            "ocr_endpoint": FAKE_OCR_ENDPOINT,
        }
        if with_gateways
        else {
            "model_base_url": None,
            "model_name": None,
            "model_api_key": None,
            "ocr_secret_id": None,
            "ocr_secret_key": None,
            "ocr_endpoint": FAKE_OCR_ENDPOINT,
        }
    )
    return Settings(
        _env_file=None,
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'mktkb.sqlite3').as_posix()}",
        cookie_secure=False,
        csrf_secret="t09-acceptance-csrf-secret-0123456789",
        admin_password=ADMIN_PASSWORD,
        employee_password=EMPLOYEE_PASSWORD,
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="INFO",
        **gateway_kwargs,
    )


def assert_fake_configuration(settings: Settings) -> None:
    """守住"没有真实配置泄漏进本轮"：所有服务端凭据都必须是本轮假值。"""
    assert settings.model_api_key is not None
    assert settings.model_api_key.get_secret_value() == FAKE_MODEL_API_KEY
    assert settings.model_base_url == FAKE_MODEL_BASE_URL
    assert settings.ocr_secret_id is not None
    assert settings.ocr_secret_id.get_secret_value() == FAKE_OCR_SECRET_ID
    assert settings.ocr_secret_key is not None
    assert settings.ocr_secret_key.get_secret_value() == FAKE_OCR_SECRET_KEY
    assert settings.ocr_endpoint == FAKE_OCR_ENDPOINT


# ---------------------------------------------------------------- 受控 OCR 替身


class OCRTranscriptStandIn:
    """只替代 OCR 识别结果：按绑定文件的受控转录返回文本/表格，逐次记录调用与页码。

    - 未绑定文件或未转录的页立即抛错，避免替身"自动补"任何内容；
    - ``block``/``entered``/``release`` 供 U09 的"识别在途被删除/取消/租约失效"时序用；
    - ``error`` 可注入稳定 OCR 错误（额度/限流/超时）用于安全与故障映射检查。
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._spec: dict | None = None
        self._label: str | None = None
        self.block = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.error: Exception | None = None
        self.return_empty = False
        self._lock = threading.Lock()

    def bind(self, file_id: str) -> None:
        spec = ocr_transcripts.OCR_BINDINGS.get(file_id)
        assert spec is not None, f"{file_id} 不在受控转录表中，不允许用替身代替"
        self._label = file_id
        self._spec = spec

    def unbind(self) -> None:
        self._label = None
        self._spec = None

    def label(self) -> str | None:
        return self._label

    def recognize(self, page, *, mode):
        if self._spec is None:
            raise RuntimeError(f"OCR 替身未绑定任何文件，拒绝识别第 {page.page} 页（不允许内置答案）")
        lines = self._spec["pages"].get(page.page)
        expected_mode = "table" if "table" in self._spec else "text"
        entry = {
            "ordinal": len(self.calls) + 1,
            "file": self._label,
            "page": page.page,
            "mode": mode,
            "mode_expected": expected_mode,
            "mode_match": mode == expected_mode,
            "mime_type": page.mime_type,
            "bbox": None if page.bbox is None else list(page.bbox),
            "content_bytes": len(page.content),
            "content_sha256": hashlib.sha256(page.content).hexdigest(),
            "transcript_found": lines is not None,
        }
        with self._lock:
            self.calls.append(entry)
        if self.block:
            self.entered.set()
            if not self.release.wait(20):
                raise RuntimeError("替身屏障超时")
        if self.error is not None:
            raise self.error
        if lines is None:
            raise RuntimeError(f"{self._label} 第 {page.page} 页没有受控转录，拒绝编造识别结果")
        request_id = f"t09stub-{self._label}-p{page.page}-{entry['ordinal']}"
        text = "" if self.return_empty else "\n".join(lines)
        entry["returned_empty_text"] = self.return_empty
        if mode == "table" and "table" in self._spec:
            header, rows = self._spec["table"]
            table_rows = (tuple(header), *tuple(tuple(row) for row in rows))
            return OCRPageResult(
                text=text, table_rows=table_rows, provider_request_id=request_id, confidence=90.0
            )
        return OCRPageResult(text=text, provider_request_id=request_id, confidence=90.0)

    def summary(self) -> list[dict]:
        with self._lock:
            return list(self.calls)


# ---------------------------------------------------------------- 装配


@dataclass
class Harness:
    """一个独立数据库 + 独立文件目录 + 注入式网关的应用实例。"""

    data_dir: Path
    settings: Settings
    app: object
    model: EvidenceEchoGateway
    ocr: OCRTranscriptStandIn
    _clients: list[TestClient] = field(default_factory=list)

    @property
    def store(self):
        return self.app.state.store

    def client(self) -> TestClient:
        client = TestClient(self.app, raise_server_exceptions=False)
        self._clients.append(client)
        return client

    def session(self):
        return self.app.state.db.session()

    def revision(self) -> int:
        db = self.session()
        try:
            return get_revision(db)
        finally:
            db.close()

    def admin(self) -> SimpleNamespace:
        return self._writer("admin", ADMIN_PASSWORD)

    def employee(self) -> SimpleNamespace:
        return self._writer("employee", EMPLOYEE_PASSWORD)

    def _writer(self, username: str, password: str) -> SimpleNamespace:
        client = self.client()
        login(client, username, password)
        csrf = current_csrf(client)
        return SimpleNamespace(
            client=client,
            csrf=csrf,
            headers=write_headers(csrf),
            upload=lambda **kwargs: upload_document(client, csrf=csrf, **kwargs),
        )

    def run_job(self, **kwargs):
        """跑一个任务；需要 OCR 的文件由调用方先 ``ocr.bind(file_id)``。"""
        db = self.session()
        try:
            return run_one_job(db, self.store, ocr=self.ocr, **kwargs)
        finally:
            db.close()

    def detail(self, document_id) -> dict:
        response = self.admin().client.get(f"/api/v1/documents/{document_id}")
        assert response.status_code == 200, response.text
        return response.json()

    def close(self) -> None:
        for client in self._clients:
            try:
                client.close()
            except Exception:  # pragma: no cover - 关闭失败不影响证据
                pass
        self._clients.clear()
        try:
            self.app.state.db.dispose()
        except Exception:  # pragma: no cover
            pass


def new_harness(data_dir: Path, *, initialize: bool = True, inject: bool = True) -> Harness:
    """装配一个独立应用实例。

    ``inject=True`` 注入受控替身（正常执行路径）；``inject=False`` 用于验证"未配置"稳定错误映射，
    此时模型/OCR 配置全部置空、不注入任何网关，并断言应用侧确实为 None（没有回落真实客户端）。
    """
    data_dir = Path(data_dir)
    settings = make_settings(data_dir, with_gateways=inject)
    if inject:
        assert_fake_configuration(settings)
        model = EvidenceEchoGateway()
        ocr = OCRTranscriptStandIn()
        app = create_app(settings, initialize=initialize, model_gateway=model, ocr_gateway=ocr)
        assert app.state.model_gateway is model, "模型网关必须是注入的替身，不得回落真实客户端"
        assert app.state.ocr_gateway is ocr, "OCR 网关必须是注入的替身，不得回落真实客户端"
    else:
        assert settings.model_api_key is None and settings.ocr_secret_id is None
        model = None
        ocr = None
        app = create_app(settings, initialize=initialize)
        assert app.state.model_gateway is None, "未配置时不得构建真实模型客户端"
        assert app.state.ocr_gateway is None, "未配置时不得构建真实 OCR 客户端"
    return Harness(data_dir=data_dir, settings=settings, app=app, model=model, ocr=ocr)


# ---------------------------------------------------------------- B0 装配


@dataclass
class B0:
    harness: Harness
    admin: SimpleNamespace
    documents: dict[str, dict]  # file_id -> {document, version, number}
    slots: dict[str, str]  # document_slot -> document_id
    steps: list[dict]
    revision: int

    @property
    def ocr_calls(self) -> list[dict]:
        return self.harness.ocr.summary()


def _publish(admin: SimpleNamespace, document_id, version_id, *, expected_active, expected_revision) -> dict:
    response = admin.client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={"expected_active_version_id": expected_active, "expected_revision": expected_revision},
        headers=admin.headers,
    )
    assert response.status_code == 200, f"publish 失败: {response.status_code} {response.text[:400]}"
    return response.json()


def build_b0(data_dir: Path) -> B0:
    """严格按 manifest.b0_initialization 的 33 步建立 B0（10 份正常资料）。"""
    harness = new_harness(data_dir)
    admin = harness.admin()
    documents: dict[str, dict] = {}
    slots: dict[str, str] = {}
    step_log: list[dict] = []

    for step in B0_STEPS:
        op = step["op"]
        file_id = step["file"]
        entry = {
            "step": step["step"],
            "op": op,
            "file": file_id,
            "document_slot": step.get("document_slot"),
            "business_version": step.get("business_version"),
        }
        if op == "import_document":
            receipt = admin.upload(path=fixture_path(file_id), allow_same_name=False)
            assert receipt.status_code == 202, f"{file_id} 上传失败: {receipt.text[:400]}"
            record = receipt.json()
            document_id = record["document"]["id"]
            documents[file_id] = {
                "document": document_id,
                "version": record["version"]["id"],
                "number": record["version"]["number"],
                "job": record["job"]["id"],
            }
            if step.get("document_slot"):
                slots[step["document_slot"]] = document_id
            entry.update(
                {"document": document_id, "version": record["version"]["id"], "state": record["version"]["state"]}
            )
        elif op == "import_version":
            document_id = slots[step["document_slot"]]
            active = harness.detail(document_id)["document"]["active_version"]
            receipt = admin.upload(
                path=fixture_path(file_id),
                document_id=document_id,
                expected_active_version_id=active["id"] if active else None,
            )
            assert receipt.status_code == 202, f"{file_id} 新版本上传失败: {receipt.text[:400]}"
            record = receipt.json()
            documents[file_id] = {
                "document": document_id,
                "version": record["version"]["id"],
                "number": record["version"]["number"],
                "job": record["job"]["id"],
            }
            entry.update(
                {"document": document_id, "version": record["version"]["id"], "state": record["version"]["state"]}
            )
        elif op == "process":
            harness.ocr.bind(file_id) if file_id in ocr_transcripts.OCR_BINDINGS else harness.ocr.unbind()
            result = harness.run_job()
            entry.update({"job_state": result.state, "job_id": str(result.job_id) if result.job_id else None})
            assert result.state == "succeeded", f"{file_id} 处理未成功: {result.state} {result}"
            version_detail = harness.detail(documents[file_id]["document"])
            version = next(
                item for item in version_detail["versions"] if item["id"] == documents[file_id]["version"]
            )
            entry["version_state"] = version["state"]
            entry["report_kind"] = (version.get("processing_report") or {}).get("kind")
            entry["ocr_calls_so_far"] = len(harness.ocr.summary())
            assert version["state"] == "review_required", f"{file_id} 处理后状态应为 review_required"
        elif op == "publish":
            document_id = documents[file_id]["document"]
            version_id = documents[file_id]["version"]
            detail = harness.detail(document_id)
            active = detail["document"]["active_version"]
            publication = _publish(
                admin,
                document_id,
                version_id,
                expected_active=active["id"] if active else None,
                expected_revision=detail["revision"],
            )
            entry.update(
                {
                    "active_version": publication["active_version_id"],
                    "revision": publication["revision"],
                    "document": document_id,
                }
            )
        else:  # pragma: no cover - 配方里没有其它 op
            raise AssertionError(f"未知的 B0 步骤操作: {op}")
        step_log.append(entry)

    harness.ocr.unbind()
    revision = harness.revision()
    b0 = B0(
        harness=harness,
        admin=admin,
        documents=documents,
        slots=slots,
        steps=step_log,
        revision=revision,
    )
    return b0


def b0_facts(b0: B0) -> dict:
    """B0 结构与不变量的事实记录（供报告与逐题记录引用）。"""
    positions = b0.slots.get("doc-positions")
    detail = b0.harness.detail(positions) if positions else {}
    versions = detail.get("versions", [])
    return {
        "layer": evidence.LAYER,
        "provider": evidence.PROVIDER_TAG,
        "revision": b0.revision,
        "steps": b0.steps,
        "documents": b0.documents,
        "slots": b0.slots,
        "ocr_calls": b0.ocr_calls,
        "ocr_call_count": len(b0.ocr_calls),
        "model_calls": len(b0.harness.model.calls),
        "positions_versions": [
            {
                "id": item["id"],
                "number": item["number"],
                "state": item["state"],
                "sha256": item["sha256"],
                "report_kind": (item.get("processing_report") or {}).get("kind"),
            }
            for item in versions
        ],
    }


def assert_b0_invariants(b0: B0) -> dict:
    """核对 manifest 的 B0 断言：V03 为历史 V1、D01 为当前业务 V2，其余首次导入即 V1。"""
    positions = b0.slots["doc-positions"]
    detail = b0.harness.detail(positions)
    versions = detail["versions"]
    assert len(versions) == 2, f"位置表槽应有 2 个版本，实际 {len(versions)}"
    assert versions[0]["number"] == 1 and versions[0]["state"] == "superseded", versions[0]
    assert versions[0]["sha256"] == FILE_INDEX["V03"]["sha256"], "历史 V1 必须是 V03 的字节"
    active = detail["document"]["active_version"]
    assert active is not None and active["number"] == 2, active
    assert active["sha256"] == FILE_INDEX["D01"]["sha256"], "当前有效版本必须是 D01 的字节"
    others = {}
    for slot, document_id in b0.slots.items():
        if slot == "doc-positions":
            continue
        other = b0.harness.detail(document_id)
        assert len(other["versions"]) == 1, f"{slot} 应只有 1 个版本"
        others[slot] = {
            "versions": len(other["versions"]),
            "active_number": other["document"]["active_version"]["number"],
        }
    assert all(item["active_number"] == 1 for item in others.values()), others
    # 其余正常文件：每个 id 只对应一个资料
    assert len(b0.slots) == 10, f"B0 应有 10 个资料槽，实际 {len(b0.slots)}"
    return {
        "positions_versions": len(versions),
        "positions_v1_state": versions[0]["state"],
        "positions_v1_sha256": versions[0]["sha256"],
        "positions_v2_number": active["number"],
        "positions_v2_sha256": active["sha256"],
        "other_slots": others,
    }


# ---------------------------------------------------------------- 快照与恢复


def checkpoint_and_dispose(harness: Harness) -> None:
    db_path = harness.data_dir / "mktkb.sqlite3"
    harness.app.state.db.dispose()
    if db_path.exists():
        connection = sqlite3.connect(db_path)
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.commit()
        finally:
            connection.close()


def snapshot_b0(build_dir: Path, snapshot_dir: Path) -> Path:
    """把已建立的 B0（数据库 + 文件目录）固化为快照，供 U01～U10 独立恢复。"""
    snapshot_dir = Path(snapshot_dir)
    if snapshot_dir.exists():
        raise AssertionError(f"快照目标已存在，拒绝覆盖：{snapshot_dir}")
    shutil.copytree(Path(build_dir), snapshot_dir)
    return snapshot_dir


def restore_b0(snapshot_dir: Path, dest: Path) -> Harness:
    """从快照恢复到全新独立目录（独立数据库 + 独立文件目录），不共享任何运行状态。"""
    snapshot_dir = Path(snapshot_dir)
    dest = Path(dest)
    assert snapshot_dir.exists(), f"B0 快照不存在：{snapshot_dir}"
    if dest.exists():
        raise AssertionError(f"恢复目标已存在，拒绝覆盖：{dest}")
    shutil.copytree(snapshot_dir, dest)
    return new_harness(dest)


# ---------------------------------------------------------------- 问答与判分


def new_conversation(ns: SimpleNamespace, title: str | None = None):
    payload = {} if title is None else {"title": title}
    response = ns.client.post("/api/v1/conversations", json=payload, headers=ns.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ask(ns: SimpleNamespace, conversation_id, question: str, request_id=None):
    return ns.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(request_id or uuid.uuid4()), "question": question},
        headers=ns.headers,
    )


def messages(ns: SimpleNamespace, conversation_id) -> dict:
    response = ns.client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert response.status_code == 200, response.text
    return response.json()


# 判分器第三档（T09-D6 T1）：显式"有序字符 + 插入词白名单"。
# 只在字面档与"实际"剔除档都失败时启用：期望值的字符必须按原顺序出现，相邻字符之间
# 多出的内容只能是 VALUE_FILLER_WORDS 中的完整词依次拼成（例如
# "领取时登记实际领取数量" 相对 "领取时登记数量" 的插入内容 = "实际" + "领取"）。
# 旧实现用任意字符子序列，长答案几乎必然命中；这里任一非白名单字符都会使该档失败。
VALUE_FILLER_WORDS = ("实际", "领取")


def _value_fillers_only(gap: str) -> bool:
    """插入内容必须由白名单词完整拼成；出现任何其它字符即不成立。"""
    while gap:
        for word in VALUE_FILLER_WORDS:
            if gap.startswith(word):
                gap = gap[len(word) :]
                break
        else:
            return False
    return True


def _value_matches_from(text: str, value: str, start: int) -> bool:
    end = start + 1
    search_from = end
    for character in value[1:]:
        index = text.find(character, search_from)
        while index >= 0 and not _value_fillers_only(text[end:index]):
            index = text.find(character, index + 1)
        if index < 0:
            return False
        end = index + 1
        search_from = end
    return True


def _value_in_order(text: str, value: str) -> bool:
    """value 的字符按序出现，且相邻字符之间的插入内容只由白名单词组成。"""
    if not value:
        return False
    start = text.find(value[0])
    while start >= 0:
        if _value_matches_from(text, value, start):
            return True
        start = text.find(value[0], start + 1)
    return False


def value_present(text: str, value: str) -> bool:
    """矩阵口径：比较业务值/步骤，不要求逐字；第三档只允许显式白名单插入词。"""
    if value in text:
        return True
    compact = text.replace("实际", "")
    if value in compact:
        return True
    return _value_in_order(text, value)


B0_D01_DOC_PREFIX = "V03"  # D01 槽由 V03 建立，业务 V2 的文档名沿用槽名
LOCATOR_STRICT_KEYS = ("page", "row", "sheet", "table", "column")
LOCATOR_SKIPPED_KEYS = ("heading",)


def expected_document_prefix(file_id: str) -> str:
    if file_id == "D01":
        return B0_D01_DOC_PREFIX
    return file_id


def source_hint(file_id: str, upload_record: dict) -> dict:
    """把"上传某文件的版本"落成来源身份提示：文档名沿用槽名，版本号按实际上传结果。

    用于"以新版本方式导入变体文件"（U02 的 V04、U03 的 V06）——此时来源的文档名不是变体文件名，
    而是原资料槽名；用实际返回的 document.name + version.number 判定，不做名称猜测。
    """
    return {
        "file_id": file_id,
        "document_name": upload_record["document"]["name"],
        "version_number": upload_record["version"]["number"],
    }


def source_matches(source: dict, expected: dict, hints: dict | None = None) -> tuple[bool, list[str]]:
    """来源匹配：文件身份 + 版本号（D01 取业务 V2）+ 可核对的定位键。

    ``hints`` 来自 :func:`source_hint`，仅覆盖"以新版本导入的变体文件"这类槽名不变的情况。
    """
    file_id = expected["file"]
    hint = (hints or {}).get(file_id)
    if hint:
        prefix = hint["document_name"]
        required_number = hint.get("version_number")
    else:
        prefix = expected_document_prefix(file_id)
        required_number = 2 if file_id == "D01" else None
    notes: list[str] = []
    name = source.get("document_name") or ""
    if not (name == prefix or name.startswith(prefix)):
        return False, [f"文档名 {name!r} 不是 {file_id} 的槽（期望 {prefix!r}）"]
    if required_number is not None and source.get("version_number") != required_number:
        return False, [f"{file_id} 期望 version_number={required_number}，实际 {source.get('version_number')}"]
    locator = expected.get("locator") or {}
    actual = source.get("locator") or {}
    for key, value in locator.items():
        if key in LOCATOR_SKIPPED_KEYS:
            notes.append(f"locator.{key} 属自由文本，本轮不做逐字比较（实际 {actual.get(key)!r}）")
            continue
        if key in LOCATOR_STRICT_KEYS and actual.get(key) != value:
            return False, [f"locator.{key} 期望 {value!r}，实际 {actual.get(key)!r}"]
    return True, notes


def _is_forbidden_source(source: dict, file_id: str) -> bool:
    """判断某条来源是否就是被禁止的那个来源。

    ``V03`` 在 B0 配方里有双重身份：既是 D01 资料槽的**文档名**（先导入 V03 建立槽），
    又是历史 V1 的**文件名**。冻结题集的 ``forbidden_sources`` 语义是"历史 V1 不参与冲突"，
    因此这里按版本身份判定（同槽的第 1 个版本），而不是按文档名前缀——否则会把
    D01 当前业务 V2（文档名沿用 V03、version_number=2）误判为被禁来源。
    """
    name = str(source.get("document_name") or "")
    if file_id == B0_D01_DOC_PREFIX:
        return name.startswith(B0_D01_DOC_PREFIX) and source.get("version_number") == 1
    return name.startswith(file_id)


def _candidate_labels(payload: dict) -> list[str]:
    return [item.get("label", "") for item in payload.get("candidates") or []]


def _conflict_values(payload: dict) -> list[str]:
    values: list[str] = []
    for entry in payload.get("conflicts") or []:
        for item in entry.get("entries") or []:
            text = str(item.get("value", ""))
            if text and text not in values:
                values.append(text)
    return values


ANY_OF_KINDS = {"not_found", "clarification"}

# 矩阵 §4 对 N08 的"必须行为"是"首版范围外，不能声称完成实物定位"，并未规定必须返回 not_found；
# 已接收的 T06 产品用例（backend/tests/integration/test_chat.py:780-788）同样接受 clarification。
# 因此仅在 N08 上按"行为口径"接受 clarification，并同时记录严格口径（expected_kind=not_found）结果。
KIND_EXCEPTIONS = {"N08": ("not_found", "clarification")}
VALUE_EXEMPT_IDS = {"N08"}


def _expected_kinds(item: dict) -> tuple[str, ...]:
    expected = (item.get("scenario") or {}).get("expected_kind")
    return KIND_EXCEPTIONS.get(item["id"], (expected,))


def evaluate(
    item: dict,
    response,
    *,
    environment: dict,
    forbidden_values: list[str] | None = None,
    forbid_phrases: tuple[str, ...] = (),
    source_hints: dict | None = None,
) -> dict:
    """按冻结题集判分：kind + 必含值/可接受措辞 + 允许来源（含 C05/C06 的 allowed/forbidden）。

    `expected_values` 的语义按题组区分（见上方 ANY_OF_KINDS 说明）：answer/conflict 为全含，
    not_found/clarification 为"任一可接受措辞"。
    ``forbidden_values``/``forbid_phrases`` 只用于把《验收矩阵》正文里已经写明的否定要求
    （如 Q39/Q40"不取城西店行"、N08"不能声称完成实物定位"）落成断言，不改变冻结题集中的期望值。
    """
    scenario = item.get("scenario") or {}
    expected_kind = scenario.get("expected_kind")
    record = {
        "id": item["id"],
        "group": item["group"],
        "category": item.get("category"),
        "question": item["question"],
        "expected": {
            "kind": expected_kind,
            "values": item.get("expected_values", []),
            "sources": item.get("expected_sources", []),
            "candidates": scenario.get("candidates", []),
            "initial_state": scenario.get("initial_state"),
            "initialization_ref": scenario.get("initialization_ref"),
        },
        "provider": evidence.PROVIDER_TAG,
        "environment": environment,
        "http_status": response.status_code,
    }
    problems: list[str] = []
    notes: list[str] = []
    if response.status_code != 200:
        record["error"] = response.text[:800]
        record["status"] = "fail"
        record["problems"] = [f"HTTP {response.status_code}"]
        return record

    payload = response.json()
    record["actual"] = {
        "kind": payload.get("kind"),
        "text": payload.get("text"),
        "revision": payload.get("revision"),
        "sources": payload.get("sources") or [],
        "candidates": _candidate_labels(payload),
        "conflicts": payload.get("conflicts") or [],
        "missing_fields": payload.get("missing_fields") or [],
        "error_code": payload.get("error_code"),
    }
    record["source"] = [
        {
            "document_name": source.get("document_name"),
            "version_number": source.get("version_number"),
            "status": source.get("status"),
            "locator": source.get("locator"),
        }
        for source in payload.get("sources") or []
    ]

    kinds_allowed = _expected_kinds(item)
    if payload.get("kind") not in kinds_allowed:
        problems.append(f"kind={payload.get('kind')!r} 期望 {expected_kind!r}")

    values = item.get("expected_values") or []
    text_value = payload.get("text") or ""
    any_of = expected_kind in ANY_OF_KINDS

    if expected_kind == "answer":
        for value in values:
            if not value_present(text_value, value):
                problems.append(f"缺少必含内容 {value!r}")
    elif expected_kind == "not_found":
        if payload.get("sources"):
            problems.append("无答案题不得返回来源")
        if item["id"] in VALUE_EXEMPT_IDS:
            notes.append("N08 按矩阵 §4 行为口径判定：不得声称完成实物定位（见 forbid_phrases）")
        elif not any(value_present(text_value, value) for value in values):
            problems.append(f"缺少可接受的缺失措辞（任一）：{values}")
    elif expected_kind == "clarification":
        labels = _candidate_labels(payload)
        candidates_required = scenario.get("candidates") or []
        for label in candidates_required:
            if label not in labels:
                problems.append(f"澄清候选缺少 {label!r}（实际 {labels}）")
        if values and not any(
            value_present(text_value, value) or any(value in label for label in labels) for value in values
        ):
            problems.append(f"缺少可接受的追问措辞（任一）：{values}（候选 {labels}）")
        if not (labels or payload.get("text")):
            problems.append("澄清结果既无候选也无文本")
        if payload.get("sources"):
            problems.append("澄清结果不应带来源")
    elif expected_kind == "conflict":
        conflict_values = _conflict_values(payload)
        for value in values:
            if not (value_present(text_value, value) or any(value in entry for entry in conflict_values)):
                problems.append(f"冲突结果缺少 {value!r}（实际冲突值 {conflict_values}）")
        if not payload.get("conflicts"):
            problems.append("冲突结果未给出 conflicts 结构")
        allowed = set(scenario.get("allowed_sources") or [])
        forbidden = set(scenario.get("forbidden_sources") or [])
        seen_prefixes = {str(source.get("document_name", "")).split("_")[0] for source in payload.get("sources") or []}
        for file_id in item.get("expected_sources") or []:
            prefix = expected_document_prefix(file_id["file"])
            if not any(str(source.get("document_name", "")).startswith(prefix) for source in payload.get("sources") or []):
                problems.append(f"冲突来源缺少 {file_id['file']}")
        for file_id in forbidden:
            if any(_is_forbidden_source(source, file_id) for source in payload.get("sources") or []):
                problems.append(f"冲突来源不应包含 {file_id}")
        if allowed and not seen_prefixes:
            notes.append(f"allowed_sources={sorted(allowed)} 但结果未带来源列表")
    elif expected_kind == "knowledge_changed":
        if payload.get("sources"):
            problems.append("knowledge_changed 不得返回来源")

    for expected_source in item.get("expected_sources") or []:
        if expected_kind == "conflict":
            continue  # 已在冲突分支按文件身份核对
        matched = False
        for source in payload.get("sources") or []:
            ok, source_notes = source_matches(source, expected_source, source_hints)
            notes.extend(source_notes)
            if ok:
                matched = True
                break
        if not matched:
            problems.append(f"缺少期望来源 {expected_source}")

    record["notes"] = notes
    for forbidden in forbidden_values or []:
        if value_present(text_value, forbidden):
            problems.append(f"回答包含矩阵明令不得出现的内容 {forbidden!r}")
    for phrase in forbid_phrases:
        if phrase in text_value:
            problems.append(f"回答出现不得声称的表述 {phrase!r}")
    record["forbidden_values"] = list(forbidden_values or [])
    record["forbid_phrases"] = list(forbid_phrases)
    record["problems"] = problems
    record["status"] = "fail" if problems else "pass"

    # 严格口径：kind 必须与 questions.json 的 expected_kind 逐字一致（不含 N08 行为例外），
    # 且 expected_values 全部出现。仅供报告并列展示，不作为矩阵判定。
    strict_problems: list[str] = []
    if payload.get("kind") != expected_kind:
        strict_problems.append(f"kind={payload.get('kind')!r} 期望 {expected_kind!r}")
    if not any_of:
        for value in values:
            if not value_present(text_value, value):
                strict_problems.append(f"缺少内容 {value!r}")
    else:
        if not any(value_present(text_value, value) for value in values):
            strict_problems.append(f"缺少可接受措辞（任一）：{values}")
    record["strict_status"] = "fail" if strict_problems else "pass"
    record["strict_problems"] = strict_problems
    return record


def evaluate_event(
    sub_scenario: dict,
    response,
    *,
    environment: dict,
    forbidden_values: list[str] | None = None,
) -> dict:
    """事件型子场景判分（U07）：按 ``sub_scenario.expected`` 核对 kind/来源，不复用问答 evaluate()。

    U07 的期望 kind 在 sub_scenario 里，冻结题集外层 ``scenario`` 没有 expected_kind；
    旧实现把整例交给 :func:`evaluate`，于是证据内层 ``graded.status`` 字面为 fail（字段伪报）。
    这里保持实质判据不变：kind 必须等于事件期望、事件结果不得带来源；"不保存待发旧事实"
    仍由用例直接核对 history。事件型子场景不再生成问答口径的 expected/values 字段。
    """
    expected = dict(sub_scenario.get("expected") or {})
    record = {
        "id": sub_scenario.get("id"),
        "variant": sub_scenario.get("variant"),
        "mode": "event",
        "expected": expected,
        "provider": evidence.PROVIDER_TAG,
        "environment": environment,
        "http_status": response.status_code,
    }
    problems: list[str] = []
    if response.status_code != 200:
        record["error"] = response.text[:800]
        record["actual"] = None
        record["problems"] = [f"HTTP {response.status_code}"]
        record["status"] = "fail"
        return record

    payload = response.json()
    record["actual"] = {
        "kind": payload.get("kind"),
        "text": payload.get("text"),
        "revision": payload.get("revision"),
        "sources": payload.get("sources") or [],
    }
    if payload.get("kind") != expected.get("kind"):
        problems.append(f"kind={payload.get('kind')!r} 期望 {expected.get('kind')!r}")
    if expected.get("sources") == [] and payload.get("sources"):
        problems.append("事件结果不得返回来源")
    for forbidden in forbidden_values or []:
        if value_present(payload.get("text") or "", forbidden):
            problems.append(f"回答包含矩阵明令不得出现的内容 {forbidden!r}")
    record["forbidden_values"] = list(forbidden_values or [])
    record["problems"] = problems
    record["status"] = "fail" if problems else "pass"
    return record


def summarize(records: list[dict]) -> dict:
    """按矩阵口径汇总：40 正常题（含 Q01～Q24 精确题全对）、8 无答案、6 歧义/冲突。"""
    by_id = {record["id"]: record for record in records}
    normal = [record for record in records if record["group"] == "normal"]
    exact_ids = [f"Q{index:02d}" for index in range(1, 25)]
    exact = [by_id[qid] for qid in exact_ids if qid in by_id]
    negative = [record for record in records if record["group"] == "negative"]
    ambiguity = [record for record in records if record["group"] == "ambiguity_conflict"]
    mutation = [record for record in records if record["group"] == "mutation"]

    def passed(items: list[dict]) -> int:
        return sum(1 for item in items if item["status"] == "pass")

    def passed_strict(items: list[dict]) -> int:
        return sum(1 for item in items if item.get("strict_status") == "pass")

    return {
        "total": len(records),
        "normal_total": len(normal),
        "normal_correct": passed(normal),
        "normal_threshold": 36,
        "normal_failures": [record["id"] for record in normal if record["status"] != "pass"],
        "exact_total": len(exact),
        "exact_correct": passed(exact),
        "exact_failures": [record["id"] for record in exact if record["status"] != "pass"],
        "negative_total": len(negative),
        "negative_passed": passed(negative),
        "negative_passed_strict": passed_strict(negative),
        "negative_failures": [record["id"] for record in negative if record["status"] != "pass"],
        "negative_failures_strict": [record["id"] for record in negative if record.get("strict_status") != "pass"],
        "ambiguity_total": len(ambiguity),
        "ambiguity_passed": passed(ambiguity),
        "ambiguity_passed_strict": passed_strict(ambiguity),
        "ambiguity_failures": [record["id"] for record in ambiguity if record["status"] != "pass"],
        "ambiguity_failures_strict": [record["id"] for record in ambiguity if record.get("strict_status") != "pass"],
        "mutation_total": len(mutation),
        "mutation_passed": passed(mutation),
        "mutation_failures": [record["id"] for record in mutation if record["status"] != "pass"],
    }
