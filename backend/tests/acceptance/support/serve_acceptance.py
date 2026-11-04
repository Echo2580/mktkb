"""T09-D3 B 层浏览器验收后端服务（真实 uvicorn + B0 + 受控 worker + 验收控制路由）。

职责（对应 ``docs/evidence/T09/D3/tmp/d3-acceptance-contract.md`` §1）：

1. 显式 ``Settings(_env_file=None + 假密钥)``，并让 ``trusted_origins`` 同时包含
   ``http://testserver``（TestClient 内部会话）与浏览器来源
   ``http://127.0.0.1:5199`` / ``http://localhost:5199``；
2. 复用 ``support.b0`` 建立严格 33 步 B0，然后把**同一个 app 实例**交给 uvicorn 真实监听；
3. 后台 worker 线程用 ``app.state.db`` 的独立 Session 轮询 ``claim_job``/``run_one_job``，
   处理前按文档名前缀（D01…/V01…/M01…）自动 bind ``ocr_transcripts.OCR_BINDINGS`` 中的受控转录；
4. 在 ``EvidenceEchoGateway`` 外包一层可控包装，实现 fail-next / block-next / release 故障注入
   （不修改产品源码、不修改 b0.py）；同时把 ``purpose=="answer"`` 的替身文本按
   ``request.evidence`` 原值字段做**确定性去重重组**（``根据资料：字段：原值；…``，按
   (字段名, 原值) 唯一、保持证据顺序，不新增内容、不内置答案）——原因见
   ``ControlledModelGateway`` docstring：B 层跨 spec 累积状态会让同一实体同时命中表格行与
   正文通知两个证据单元，替身的简单多段回显会被产品的记录型准入误判为重复字段；
5. 进程级外部网络闸门（参考 ``support/netguard.py``，但为进程级安装而非 pytest fixture）：
   非回环 socket/httpx 出站全部拦截并记账，服务期内外部尝试必须为 0；
6. JSONL 逐行事件日志（start/b0_built/worker_started/claim/job_done/scenario/gateway/outbound/shutdown）；
7. ``/__acceptance/*`` 控制路由：只准备状态 / 注入故障 / 登记材料；上传、发布、删除等业务动作
   都经产品 HTTP 接口（服务内管理员会话 + CSRF/Origin）完成，不直接写业务表。
   其中 ``POST /__acceptance/scenario/prepare-u02`` 是 B 层串行状态卫生入口：用产品 delete 接口
   逻辑删除 C05 发布的 V01 资料，把累积状态恢复到验收矩阵 U02 的冻结前提「从 B0 恢复后执行」
   （详见 ``scenario_prepare_u02`` docstring）；它不修改产品代码，只清理本轮临时数据，
   并把动作写进 JSONL 的 ``scenario`` 事件；
8. SIGINT/SIGTERM 由 uvicorn 负责优雅退出，退出后写 ``shutdown`` 事件与最终 ``outbound`` 快照；
   ``POST /__acceptance/shutdown`` 提供等价的控制面优雅停服入口。

启动示例（由 ``run_browser_acceptance.py`` 调用）::

    .venv\\Scripts\\python.exe -B backend\\tests\\acceptance\\support\\serve_acceptance.py ^
        --host 127.0.0.1 --port 8188 ^
        --data-dir docs\\evidence\\T09\\D3\\tmp\\acceptance-<label>\\data ^
        --log-file docs\\evidence\\T09\\D3\\logs\\acceptance-server-<label>.jsonl --label <label>

已知限制（如实记录）：本进程内的出站闸门无法约束本进程之外启动的子进程；本轮服务不启动
任何会出站的子进程，runner 另行检查浏览器侧网络。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import platform
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# ---- import 路径：backend/src、backend/tests、backend/tests/acceptance（契约 §1） ----
HERE = Path(__file__).resolve()
ROOT = HERE.parents[4]
BACKEND = ROOT / "backend"
for _path in (BACKEND / "src", BACKEND / "tests", BACKEND / "tests" / "acceptance"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import APIRouter, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from conftest import ORIGIN, current_csrf, login, upload_document, write_headers  # noqa: E402
from mktkb.documents.models import Document, DocumentVersion  # noqa: E402
from mktkb.ingestion.models import ImportJob  # noqa: E402
from mktkb.ingestion.worker import claim_job, run_one_job  # noqa: E402
from mktkb.providers.types import CompletionOutput, ModelTimeout, ModelUnavailable  # noqa: E402

from support import b0, evidence as evidence_support, ocr_transcripts  # noqa: E402
from support.netguard import is_loopback  # noqa: E402

# ---------------------------------------------------------------- 常量

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8188
# 浏览器（Vite 127.0.0.1:5199）来源；http://testserver 由 b0.make_settings 提供，一并保留。
BROWSER_ORIGINS = ("http://127.0.0.1:5199", "http://localhost:5199")
READY_TIMEOUT_SECONDS = 120.0
HEALTHZ_TIMEOUT_SECONDS = 60.0
SCENARIO_TIMEOUT_SECONDS = 300.0
BLOCK_WAIT_SECONDS = 30.0
WORKER_IDLE_SECONDS = 0.1
WORKER_JOIN_SECONDS = 30.0
SHUTDOWN_JOIN_SECONDS = 30.0

MODEL_FAILURE_CODES = {"MODEL_UNAVAILABLE": ModelUnavailable, "MODEL_TIMEOUT": ModelTimeout}
REQUIRED_EVENTS_HINT = ("start", "b0_built", "worker_started", "claim", "job_done", "scenario", "gateway", "outbound", "shutdown")

FONT_DIR = evidence_support.ROOT / "docs" / "evidence" / "T01" / "C1-R1" / "derived-fonts"
FONT_REGULAR = FONT_DIR / "NotoSansSCStatic-Regular.ttf"
FONT_MEDIUM = FONT_DIR / "NotoSansSCStatic-Medium.ttf"

SCRIPT_DIR = HERE.parent
DEFAULT_EVIDENCE_ROOT = evidence_support.ROOT / "docs" / "evidence" / "T09" / "D3"

# 日志里绝不落盘的按键（假密钥也不落盘）
SECRET_KEY_MARKERS = ("password", "secret", "csrf", "api_key", "apikey", "token")


# ---------------------------------------------------------------- 小工具


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (set, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class JsonlLogger:
    """逐行 JSONL 事件日志；线程安全、逐条 flush、过滤疑似密钥字段。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._stream = self.path.open("a", encoding="utf-8")

    def event(self, event: str, **fields) -> None:
        record: dict = {"ts": now_iso(), "event": event}
        for key, value in fields.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in SECRET_KEY_MARKERS):
                continue
            record[key] = _jsonable(value)
        line = json.dumps(record, ensure_ascii=False, default=str, sort_keys=False) + "\n"
        with self._lock:
            if self._stream.closed:
                return
            self._stream.write(line)
            self._stream.flush()

    def close(self) -> None:
        with self._lock:
            if not self._stream.closed:
                self._stream.flush()
                self._stream.close()


# ---------------------------------------------------------------- 外部网络闸门（进程级）


class OutboundBlocked(RuntimeError):
    """外部出站被验收闸门拦截。"""


BLOCKED_MESSAGE = "T09-D3 验收闸门：服务期内禁止真实外部调用（0 次），已拦截出站连接"


class OutboundGuard:
    """进程级出站闸门：非回环 socket/httpx 全部拦截并记账，回环放行（asyncio self-pipe 需要）。

    与 ``support/netguard.py`` 同口径，但为进程级安装：不依赖 pytest fixture，
    服务期任意线程的尝试都会被记录到 ``snapshot()``，供 ``/__acceptance/state`` 与 JSONL 断言。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.external: list[str] = []
        self.local: list[str] = []
        self.installed = False

    def install(self) -> None:
        if self.installed:  # pragma: no cover - 单进程只安装一次
            return
        real_connect = socket.socket.connect
        real_connect_ex = socket.socket.connect_ex
        real_create_connection = socket.create_connection
        real_getaddrinfo = socket.getaddrinfo
        guard = self

        def guarded_connect(sock, address, *args, **kwargs):  # noqa: ANN001
            if not is_loopback(address):
                guard._add(f"socket.connect {address!r}", address)
                raise OutboundBlocked(f"{BLOCKED_MESSAGE}: connect {address!r}")
            guard._add(f"socket.connect {address!r}", address)
            return real_connect(sock, address, *args, **kwargs)

        def guarded_connect_ex(sock, address, *args, **kwargs):  # noqa: ANN001
            guard._add(f"socket.connect_ex {address!r}", address)
            if not is_loopback(address):
                raise OutboundBlocked(f"{BLOCKED_MESSAGE}: connect_ex {address!r}")
            return real_connect_ex(sock, address, *args, **kwargs)

        def guarded_create_connection(address, *args, **kwargs):  # noqa: ANN001
            if not is_loopback(address):
                guard._add(f"socket.create_connection {address!r}", address)
                raise OutboundBlocked(f"{BLOCKED_MESSAGE}: create_connection {address!r}")
            guard._add(f"socket.create_connection {address!r}", address)
            return real_create_connection(address, *args, **kwargs)

        def guarded_getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
            address = host if isinstance(host, str) else ""
            loopback = is_loopback(host) or is_loopback((address,))
            if not loopback:
                guard._add(f"socket.getaddrinfo {host!r}", (address,))
                raise OutboundBlocked(f"{BLOCKED_MESSAGE}: getaddrinfo {host!r}")
            guard._add(f"socket.getaddrinfo {host!r}", (address,))
            return real_getaddrinfo(host, *args, **kwargs)

        def guarded_handle_request(transport, request):  # noqa: ANN001
            guard._add(f"httpx.HTTPTransport {request.url}", (str(request.url.host),))
            raise OutboundBlocked(f"{BLOCKED_MESSAGE}: HTTP {request.url}")

        async def guarded_handle_async_request(transport, request):  # noqa: ANN001
            guard._add(f"httpx.AsyncHTTPTransport {request.url}", (str(request.url.host),))
            raise OutboundBlocked(f"{BLOCKED_MESSAGE}: HTTP {request.url}")

        socket.socket.connect = guarded_connect  # type: ignore[assignment]
        socket.socket.connect_ex = guarded_connect_ex  # type: ignore[assignment]
        socket.create_connection = guarded_create_connection  # type: ignore[assignment]
        socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]
        httpx.HTTPTransport.handle_request = guarded_handle_request  # type: ignore[assignment]
        httpx.AsyncHTTPTransport.handle_async_request = guarded_handle_async_request  # type: ignore[assignment]
        self.installed = True

    def _add(self, label: str, address=None) -> None:  # noqa: ANN001
        with self._lock:
            if is_loopback(address):
                self.local.append(label)
            else:
                self.external.append(label)

    def snapshot(self) -> dict:
        with self._lock:
            return {"external": list(self.external), "local_count": len(self.local)}


# ---------------------------------------------------------------- Settings 来源补丁


def patch_b0_settings() -> None:
    """包装 ``b0.make_settings``：在 B0 构建**之前**把浏览器来源加入 trusted_origins。

    产品路由在请求期通过 ``request.app.state.settings`` 读取该配置
    （``mktkb/auth/routes.py::get_settings`` → ``require_trusted_origin``），因此构建后
    每次请求都会看到新来源列表。不修改 ``b0.py``，只在本进程内替换模块全局函数。
    """
    original = b0.make_settings

    def make_settings_with_browser_origins(data_dir, **kwargs):  # noqa: ANN001
        settings = original(data_dir, **kwargs)
        merged = list(dict.fromkeys([*settings.trusted_origins, ORIGIN, *BROWSER_ORIGINS]))
        settings.trusted_origins = merged
        return settings

    b0.make_settings = make_settings_with_browser_origins


# ---------------------------------------------------------------- 模型替身故障注入


class ControlledModelGateway:
    """在 ``EvidenceEchoGateway`` 外包一层：fail-next / block-next / release。

    - fail-next N [code]：接下来 N 次 ``complete`` 立刻抛对应 ``ModelError`` 子类；
    - block-next N：接下来 N 次 ``complete`` 在入口阻塞（threading.Event），
      ``entered`` 置位供控制路由轮询；``release`` 置位或 30 秒超时后继续；
    - 只包装不修改替身本身；模型调用次数仍读内部替身的 ``calls``。

    另外对 ``purpose == "answer"`` 的替身返回文本做**确定性去重重组**（只重排/去重
    ``request.evidence`` 里的原值字段与正文，不新增任何内容、不内置答案）：

    B 层是单服务跨 spec 累积状态：``acceptance-06`` 发布 V01 正文通知后，同一实体
    会同时命中「表格记录行」与「正文通知单元」两个带 ``fields`` 的证据单元。
    ``EvidenceEchoGateway`` 会把每个单元的 fields 各拼一段，产生两条完全相同的
    “位置：D区暂存柜”，而产品的记录型准入 ``_record_facts`` 要求同一 role 只出现一次，
    于是回答被误判为 MODEL_OUTPUT_INVALID。这里按证据顺序重建：带 fields 的单元按
    (字段名, 原值) 唯一输出，没有 fields 的正文单元保留原文（完全相同正文只留一次），
    即 ``根据资料：字段：原值；…；正文…``，使替身输出与真实模型“每字段/每段证据陈述一次”
    的形态一致，同时不丢失文档型问答的正文证据。
    """

    def __init__(self, inner, logger: JsonlLogger) -> None:
        self.inner = inner
        self._log = logger
        self._lock = threading.Lock()
        self.fail_remaining = 0
        self.fail_code = "MODEL_UNAVAILABLE"
        self.block_remaining = 0
        self.entered = threading.Event()
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.block_entered_count = 0
        self.block_released_count = 0
        self.block_timeout_count = 0
        self.answer_rebuild_count = 0
        self.answer_rebuild_last: dict | None = None

    def arm_fail(self, count: int, code: str) -> dict:
        with self._lock:
            self.fail_remaining = max(0, int(count))
            self.fail_code = code
            remaining = self.fail_remaining
        self._log.event("gateway", action="fail_next", armed=int(count), code=code, remaining=remaining)
        return {"armed": int(count), "remaining": remaining, "code": code}

    def arm_block(self, count: int) -> dict:
        with self._lock:
            self.block_remaining = max(0, int(count))
            self.entered.clear()
            self.blocked.clear()
            self.release.clear()
            remaining = self.block_remaining
        self._log.event("gateway", action="block_next", armed=int(count), remaining=remaining)
        return {"armed": int(count), "remaining": remaining}

    def release_block(self) -> dict:
        was_blocked = self.blocked.is_set()
        self.release.set()
        self._log.event("gateway", action="release", was_blocked=was_blocked)
        return {"released": True, "was_blocked": was_blocked}

    def status(self) -> dict:
        with self._lock:
            return {
                "fail_remaining": self.fail_remaining,
                "block_remaining": self.block_remaining,
                "entered": self.entered.is_set(),
                "blocked": self.blocked.is_set(),
                "fail_code": self.fail_code,
                "block_entered_total": self.block_entered_count,
                "block_released_total": self.block_released_count,
                "block_timeout_total": self.block_timeout_count,
                "answer_rebuild_total": self.answer_rebuild_count,
                "answer_rebuild_last": self.answer_rebuild_last,
            }

    def _wait_release(self) -> bool:
        return self.release.wait(BLOCK_WAIT_SECONDS)

    def _rebuild_answer_from_evidence(self, request, output: CompletionOutput) -> CompletionOutput:
        """按证据原值重建 answer 文本：证据顺序、按 (字段名, 原值) 唯一；不新增内容。

        逐个证据单元处理：带 fields 的单元只取其 (字段名, 原值) 对（同值只保留一次）；
        没有 fields 的正文单元保留其原文（完全相同的正文只保留一次）。这样：
        - 记录型问答（表格行 + 正文通知同实体）不会重复陈述同一字段而触发产品记录型准入；
        - 文档型问答（docx/pdf/图片/扫描件正文单元）仍逐条回显证据原文，不丢正文；
        - 混合证据也保持两部分的原始顺序与内容。
        """
        evidence = tuple(getattr(request, "evidence", ()) or ())
        parts: list[str] = []
        seen_pairs: set[tuple[str, str]] = set()
        seen_texts: set[str] = set()
        for item in evidence:
            fields = dict(getattr(item, "fields", None) or {})
            if fields:
                for name, value in fields.items():
                    if value is None or str(value).strip() == "":
                        continue
                    pair = (str(name), str(value))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    parts.append(f"{pair[0]}：{pair[1]}")
                continue
            text = str(getattr(item, "text", "") or "").strip()
            if text and text not in seen_texts:
                seen_texts.add(text)
                parts.append(text)
        if not parts:
            # 证据里既无字段也无正文：沿用内部替身的回显文本，不做改写。
            return output
        text = "根据资料：" + "；".join(parts)
        detail = {
            "evidence_units": len(evidence),
            "field_pairs": len(seen_pairs),
            "text_units": len(seen_texts),
            "inner_text_chars": len(output.text or ""),
            "deduplicated": len(output.text or "") != len(text),
        }
        with self._lock:
            self.answer_rebuild_count += 1
            self.answer_rebuild_last = detail
        self._log.event(
            "gateway",
            action="answer_rebuild",
            note="仅按 request.evidence 原值字段/正文重排与去重，不新增内容、不内置答案",
            **detail,
        )
        return CompletionOutput(
            text=text,
            source_ids=output.source_ids,
            query_terms=output.query_terms,
            provider_request_id=output.provider_request_id,
            usage=output.usage,
        )

    async def complete(self, request, *, timeout_seconds: float):  # noqa: ANN001, ANN201
        action = None
        code = self.fail_code
        with self._lock:
            if self.fail_remaining > 0:
                self.fail_remaining -= 1
                action = "fail"
                code = self.fail_code
                remaining = self.fail_remaining
            elif self.block_remaining > 0:
                self.block_remaining -= 1
                action = "block"
                remaining = self.block_remaining
        if action == "fail":
            self._log.event(
                "gateway",
                action="fail_fired",
                purpose=getattr(request, "purpose", None),
                code=code,
                remaining=remaining,
            )
            raise MODEL_FAILURE_CODES[code](f"T09-D3 accepted fail-next {code}")
        if action == "block":
            self.entered.set()
            self.blocked.set()
            self.block_entered_count += 1
            self._log.event(
                "gateway",
                action="block_enter",
                purpose=getattr(request, "purpose", None),
                remaining=remaining,
            )
            released = await asyncio.to_thread(self._wait_release)
            self.entered.clear()
            self.blocked.clear()
            if released:
                self.block_released_count += 1
                self.release.clear()
            else:
                self.block_timeout_count += 1
            self._log.event("gateway", action="block_exit", released=bool(released), remaining=remaining)
        output = await self.inner.complete(request, timeout_seconds=timeout_seconds)
        if getattr(request, "purpose", None) == "answer":
            output = self._rebuild_answer_from_evidence(request, output)
        return output


# ---------------------------------------------------------------- 受控 OCR 绑定


def document_file_id(name: str) -> str:
    """按文件名去掉扩展名后的前缀（``D01_物品位置表.xlsx`` → ``D01``）。"""
    return Path(str(name or "")).stem.split("_")[0].strip()


# ---------------------------------------------------------------- 后台 worker


class AcceptanceWorker(threading.Thread):
    """单并发后台 worker：独立 Session 轮询 claim_job/run_one_job，处理前自动 bind OCR 替身。"""

    def __init__(self, runtime: "AcceptanceRuntime") -> None:
        super().__init__(name="acceptance-worker", daemon=True)
        self.runtime = runtime

    def run(self) -> None:  # noqa: D401 - 线程入口
        runtime = self.runtime
        runtime.log("worker_started", owner="acceptance-worker", pid=os.getpid())
        while not runtime.stop_event.is_set():
            db = None
            bound = None
            try:
                db = runtime.harness.app.state.db.session()
                lease = claim_job(db, owner="acceptance-worker")
                if lease is None:
                    db.close()
                    db = None
                    runtime.stop_event.wait(WORKER_IDLE_SECONDS)
                    continue
                job = db.get(ImportJob, lease.job_id)
                document = version = None
                if job is not None:
                    version = db.get(DocumentVersion, job.version_id)
                    if version is not None:
                        document = db.get(Document, version.document_id)
                file_id = document_file_id(document.name) if document is not None else None
                if file_id and file_id in ocr_transcripts.OCR_BINDINGS:
                    runtime.ocr.bind(file_id)
                    bound = file_id
                else:
                    runtime.ocr.unbind()
                runtime.log(
                    "claim",
                    job_id=lease.job_id,
                    version_id=lease.version_id,
                    document_id=getattr(version, "document_id", None),
                    document_name=getattr(document, "name", None),
                    file_id=file_id,
                    ocr_bound=bound,
                )
                result = run_one_job(
                    db,
                    runtime.harness.app.state.store,
                    ocr=runtime.ocr,
                    lease=lease,
                    owner="acceptance-worker",
                )
                runtime.log(
                    "job_done",
                    job_id=result.job_id,
                    state=result.state,
                    document_name=getattr(document, "name", None),
                    file_id=file_id,
                    units_written=result.units_written,
                    units_reused=result.units_reused,
                    error_code=result.error_code,
                )
            except Exception as exc:  # noqa: BLE001 - worker 不得因单次异常退出
                runtime.log("worker_error", type=type(exc).__name__, message=str(exc)[:300])
                runtime.stop_event.wait(0.2)
            finally:
                try:
                    runtime.ocr.unbind()
                except Exception:  # noqa: BLE001
                    pass
                if db is not None:
                    try:
                        db.close()
                    except Exception:  # noqa: BLE001
                        pass
        runtime.log("worker_stopped", owner="acceptance-worker")


# ---------------------------------------------------------------- 材料生成（A-03）

MATERIAL_SPECS: list[dict] = [
    {
        "key": "word",
        "filename": "M01_新员工入职指引.docx",
        "kind": "docx",
        "title": "新员工入职指引",
        "lines": [
            "入职第一天请在前台领取工牌，并完成账号开通。",
            "新员工入职第一周需完成安全培训与系统操作培训。",
        ],
        "question": "新员工入职第一天需要做什么？",
        "expected_value": "领取工牌",
        "expected_text": "入职第一天请在前台领取工牌，并完成账号开通。",
        "ocr": False,
    },
    {
        "key": "excel",
        "filename": "M02_差旅报销标准.xlsx",
        "kind": "xlsx",
        "header": ["费用项目", "标准", "说明"],
        "rows": [
            ["差旅报销-城市间交通费", "800 元", "凭票报销"],
            ["差旅报销-住宿费", "500 元", "每晚上限"],
            ["差旅报销-餐费补贴", "100 元", "每日上限"],
        ],
        "question": "差旅报销的住宿费标准是多少？",
        "expected_value": "500",
        "expected_text": "费用项目：差旅报销-住宿费；标准：500 元；说明：每晚上限",
        "ocr": False,
    },
    {
        "key": "pdf_text",
        "filename": "M03_会议室预约办法.pdf",
        "kind": "pdf-text",
        "title": "会议室预约办法",
        "lines": [
            "预约会议室需提前一天在办公系统中提交申请。",
            "单次预约时长不超过两小时。",
        ],
        "question": "会议室预约需要提前多久？",
        "expected_value": "提前一天",
        "expected_text": "预约会议室需提前一天在办公系统中提交申请。",
        "ocr": False,
    },
    {
        "key": "pdf_scan",
        "filename": "M04_员工培训报名通知.pdf",
        "kind": "pdf-scan",
        "lines": [
            "员工培训报名通知",
            "本期培训主题为消防安全。",
            "报名截止时间为本周五。",
            "请各部门统一提交报名名单。",
        ],
        "question": "员工培训报名截止到什么时候？",
        "expected_value": "本周五",
        "expected_text": "报名截止时间为本周五。",
        "ocr": True,
        "ocr_page_lines": [
            "员工培训报名通知",
            "本期培训主题为消防安全。",
            "报名截止时间为本周五。",
            "请各部门统一提交报名名单。",
        ],
    },
    {
        "key": "image",
        "filename": "M05_办公设备报修流程.png",
        "kind": "png",
        "lines": [
            "办公设备报修流程",
            "发现设备故障后，请在报修系统中提交工单。",
            "维修人员将在两个工作日内联系。",
        ],
        "question": "办公设备报修后多久会有人联系？",
        "expected_value": "两个工作日",
        "expected_text": "维修人员将在两个工作日内联系。",
        "ocr": True,
        "ocr_page_lines": [
            "办公设备报修流程",
            "发现设备故障后，请在报修系统中提交工单。",
            "维修人员将在两个工作日内联系。",
        ],
    },
]

MATERIALS_BY_KEY: dict[str, dict] = {spec["key"]: spec for spec in MATERIAL_SPECS}
MATERIAL_OCR_MAP = {"M04": "pdf_scan", "M05": "image"}


def _ensure_material_fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    registered = set(pdfmetrics.getRegisteredFontNames())
    regular_name = "D3Acceptance-Regular"
    medium_name = "D3Acceptance-Medium"
    if regular_name not in registered:
        if not FONT_REGULAR.is_file() or not FONT_MEDIUM.is_file():
            raise RuntimeError(f"材料生成缺少派生字体：{FONT_DIR}")
        pdfmetrics.registerFont(TTFont(regular_name, str(FONT_REGULAR)))
        pdfmetrics.registerFont(TTFont(medium_name, str(FONT_MEDIUM)))
    return regular_name, medium_name


def _write_docx(path: Path, title: str, lines: list[str]) -> None:
    from docx import Document as DocxDocument

    document = DocxDocument()
    document.add_heading(title, level=1)
    for line in lines:
        document.add_paragraph(line)
    document.save(str(path))


def _write_xlsx(path: Path, header: list[str], rows: list[list[str]]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "差旅标准"
    worksheet.append(header)
    for row in rows:
        worksheet.append(row)
    workbook.save(str(path))


def _write_text_pdf(path: Path, title: str, lines: list[str]) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    regular_name, medium_name = _ensure_material_fonts()
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(title)
    pdf.setAuthor("T09-D3 acceptance")
    pdf.setCreator("backend/tests/acceptance/support/serve_acceptance.py")
    width, height = A4
    y = height - 80
    pdf.setFont(medium_name, 16)
    pdf.drawString(56, y, title)
    y -= 36
    pdf.setFont(regular_name, 11)
    for line in lines:
        pdf.drawString(56, y, line)
        y -= 20
    pdf.showPage()
    pdf.save()


def _pillow_font(weight: int, size: int):
    from PIL import ImageFont

    filename = FONT_MEDIUM if weight == 500 else FONT_REGULAR
    if not filename.is_file():
        raise RuntimeError(f"材料生成缺少派生字体：{filename}")
    return ImageFont.truetype(str(filename), size)


def _render_material_image(lines: list[str], size: tuple[int, int] = (1240, 720)):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    title_font = _pillow_font(500, 40)
    body_font = _pillow_font(400, 28)
    draw.text((60, 60), lines[0], font=title_font, fill=(0, 0, 0))
    y = 150
    for line in lines[1:]:
        draw.text((60, y), line, font=body_font, fill=(0, 0, 0))
        y += 52
    return image


def _write_scan_pdf(path: Path, lines: list[str]) -> None:
    """纯图像扫描 PDF：整页位图、无文字层；OCR 转录由本模块登记。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    _ensure_material_fonts()
    image = _render_material_image(lines)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle("扫描件")
    pdf.setAuthor("T09-D3 acceptance")
    pdf.setCreator("serve_acceptance.py")
    pdf.drawImage(ImageReader(buffer), 0, 0, width=A4[0], height=A4[1])
    pdf.showPage()
    pdf.save()


def _write_image(path: Path, lines: list[str]) -> None:
    image = _render_material_image(lines)
    image.save(str(path), format="PNG")


def generate_materials(materials_dir: Path) -> dict:
    """生成 5 份新有效文件（Word/Excel/文字 PDF/扫描 PDF/图片）并登记 OCR 受控转录。

    内容只涉及 HR 文档型问答（入职指引/差旅报销/会议室预约/培训报名/设备报修），
    不含“门店 + 位置/电话/物品”等记录字段，避免污染冻结题集。
    """
    materials_dir = Path(materials_dir)
    materials_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {}
    for spec in MATERIAL_SPECS:
        path = materials_dir / spec["filename"]
        kind = spec["kind"]
        if kind == "docx":
            _write_docx(path, spec["title"], spec["lines"])
        elif kind == "xlsx":
            _write_xlsx(path, spec["header"], spec["rows"])
        elif kind == "pdf-text":
            _write_text_pdf(path, spec["title"], spec["lines"])
        elif kind == "pdf-scan":
            _write_scan_pdf(path, spec["lines"])
        elif kind == "png":
            _write_image(path, spec["lines"])
        else:  # pragma: no cover - 配方固定
            raise RuntimeError(f"未知材料类型：{kind}")
        payload[spec["key"]] = {
            "path": str(path.resolve()),
            "filename": path.name,
            "kind": kind,
            "expected_text": spec["expected_text"],
            "question": spec["question"],
            "expected_value": spec["expected_value"],
            "ocr": bool(spec["ocr"]),
            "bytes": path.stat().st_size,
            "sha256": sha256_path(path),
        }
    # 扫描 PDF / 图片的受控 OCR 转录登记（运行时登记，不改动 support/ocr_transcripts.py 源文件）
    for file_id, key in MATERIAL_OCR_MAP.items():
        spec = MATERIALS_BY_KEY[key]
        ocr_transcripts.OCR_BINDINGS[file_id] = {
            "kind": "pdf-scan" if spec["kind"] == "pdf-scan" else "image-text",
            "pages": {1: list(spec["ocr_page_lines"])},
        }
    return payload


# ---------------------------------------------------------------- 验收运行时


class AcceptanceRuntime:
    """服务期共享状态：B0 实例、控制路由所需会话、worker、故障注入与出站快照。"""

    def __init__(
        self,
        *,
        b0_case,
        data_dir: Path,
        label: str,
        host: str,
        port: int,
        materials_dir: Path,
        logger: JsonlLogger,
        guard: OutboundGuard,
    ) -> None:
        self.b0 = b0_case
        self.harness = b0_case.harness
        self.app = self.harness.app
        self.store = self.app.state.store
        self.data_dir = Path(data_dir)
        self.materials_dir = Path(materials_dir)
        self.label = label
        self.host = host
        self.port = port
        self.logger = logger
        self.guard = guard
        self.ocr = self.harness.ocr
        self.model = ControlledModelGateway(self.harness.model, logger)
        # 产品路由在请求期读取 app.state.model_gateway（conversations/routes.py::_model）
        self.app.state.model_gateway = self.model
        self.started_at = time.time()
        self.status = "starting"
        self.startup_error: str | None = None
        self.server = None
        self.worker: AcceptanceWorker | None = None
        self.stop_event = threading.Event()
        self.shutdown_reason: str | None = None
        self._scenario_lock = threading.RLock()
        self.admin: SimpleNamespace | None = None
        self.materials: dict | None = None
        self.scenarios: dict = {
            "conflict_C05": None,
            "conflict_C06": None,
            "prepare_u02": None,
            "update_position": None,
            "update_phone": None,
            "delete_doc_guide": None,
        }

    # ---- 日志 ----

    def log(self, event: str, **fields) -> None:
        self.logger.event(event, **fields)

    # ---- 会话与 HTTP 辅助（控制路由内部使用；真实产品接口） ----

    def create_admin_session(self) -> SimpleNamespace:
        client = TestClient(self.app, raise_server_exceptions=False)
        login(client, "admin", b0.ADMIN_PASSWORD, origin=ORIGIN)
        csrf = current_csrf(client)
        return SimpleNamespace(
            client=client,
            csrf=csrf,
            headers=write_headers(csrf, ORIGIN),
            upload=lambda **kwargs: upload_document(client, csrf=csrf, **kwargs),
        )

    def ensure_admin(self) -> SimpleNamespace:
        if self.admin is None:
            self.admin = self.create_admin_session()
        return self.admin

    def get_json(self, url: str) -> dict:
        response = self.ensure_admin().client.get(url)
        if response.status_code != 200:
            raise RuntimeError(f"GET {url} 失败：HTTP {response.status_code} {response.text[:300]}")
        return response.json()

    def detail(self, document_id) -> dict:
        return self.get_json(f"/api/v1/documents/{document_id}")

    def revision(self) -> int:
        return int(self.harness.revision())

    def upload_fixture(
        self,
        file_id: str,
        *,
        document_id=None,
        expected_active=None,
        allow_same_name: bool | None = None,
    ) -> dict:
        admin = self.ensure_admin()
        kwargs: dict = {"path": b0.fixture_path(file_id)}
        if document_id is not None:
            kwargs["document_id"] = document_id
            kwargs["expected_active_version_id"] = expected_active
        if allow_same_name is not None:
            kwargs["allow_same_name"] = allow_same_name
        response = admin.upload(**kwargs)
        if response.status_code != 202:
            raise RuntimeError(f"上传 {file_id} 失败：HTTP {response.status_code} {response.text[:400]}")
        return response.json()

    def wait_version_state(
        self,
        document_id,
        version_id,
        wanted: str,
        *,
        timeout: float = SCENARIO_TIMEOUT_SECONDS,
    ) -> dict:
        deadline = time.monotonic() + timeout
        last_state = None
        while time.monotonic() < deadline:
            detail = self.detail(document_id)
            version = next((item for item in detail.get("versions") or [] if item["id"] == str(version_id)), None)
            if version is None:
                raise RuntimeError(f"资料 {document_id} 中找不到版本 {version_id}")
            last_state = version["state"]
            if last_state == wanted:
                return detail
            if last_state in {"failed", "cancelled", "deleted"}:
                raise RuntimeError(f"版本 {version_id} 进入不可用状态 {last_state}（期望 {wanted}）")
            time.sleep(0.15)
        raise TimeoutError(f"等待版本 {version_id} 到 {wanted} 超时（最后状态 {last_state}）")

    def publish(self, document_id, version_id, *, expected_active, expected_revision) -> dict:
        admin = self.ensure_admin()
        response = admin.client.post(
            f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
            json={"expected_active_version_id": expected_active, "expected_revision": expected_revision},
            headers=admin.headers,
        )
        if response.status_code != 200:
            raise RuntimeError(f"发布 {version_id} 失败：HTTP {response.status_code} {response.text[:400]}")
        return response.json()

    # ---- 场景：C05 / C06 冲突 ----

    def scenario_conflict(self, case: str) -> dict:
        name = f"conflict_{case}"
        with self._scenario_lock:
            existing = self.scenarios.get(name)
            if existing is not None:
                self.log("scenario", name=name, params={"case": case}, result=_scenario_summary(existing), idempotent=True)
                return existing
            file_id = {"C05": "V01", "C06": "V02"}[case]
            question = next(item for item in b0.QUESTIONS if item["id"] == case)
            receipt = self.upload_fixture(file_id, allow_same_name=False)
            document_id = receipt["document"]["id"]
            version_id = receipt["version"]["id"]
            self.wait_version_state(document_id, version_id, "review_required")
            detail = self.detail(document_id)
            publication = self.publish(
                document_id,
                version_id,
                expected_active=None,
                expected_revision=detail["revision"],
            )
            result = {
                "applied": True,
                "case": case,
                "file": file_id,
                "document_id": document_id,
                "version_id": version_id,
                "revision": publication["revision"],
                "question": question["question"],
                "expected_values": question.get("expected_values", []),
                "expected_sources": question.get("expected_sources", []),
                "scenario": question.get("scenario", {}),
            }
            self.scenarios[name] = result
            self.log("scenario", name=name, params={"case": case, "file": file_id}, result=_scenario_summary(result))
            return result

    # ---- 场景：B 层状态卫生（恢复 U02 冻结前提） ----

    def scenario_prepare_u02(self) -> dict:
        """逻辑删除 C05 发布的 V01 资料，恢复验收矩阵 U02 的冻结前提。

        背景：B 层是单服务按 spec 串行累积状态。``acceptance-06`` 允许（并要求）先发布 V01
        正文通知来制造 C05 冲突；但 U02 冻结场景的 ``initial_state`` 是 "B0"，从 B0 恢复后
        D01 槽只有表格记录、没有同值正文通知。本控制路由仅用产品 delete 接口清理 C05 上传的
        临时资料 V01，把累积状态恢复到 U02 的冻结前提。

        T09-D4（F01）已修复"同角色同值多行 → 判不可验"的记录型准入缺口（修复后同值双来源
        可正常 answer；历史定位见
        ``docs/evidence/T09/D3/actual/finding-same-value-duplicate-sources.json``）。
        保留本路由是为了严格还原冻结场景的初始状态与串行状态卫生，不是规避现存产品缺陷。

        幂等：V01 不存在/已删除时仍返回 applied=True 并在 note 说明。
        """
        name = "prepare_u02"
        with self._scenario_lock:
            existing = self.scenarios.get(name)
            if existing is not None:
                self.log("scenario", name=name, params={}, result=_scenario_summary(existing), idempotent=True)
                return existing
            conflict = self.scenarios.get("conflict_C05") or {}
            document_id = conflict.get("document_id")
            note = ""
            if document_id is None:
                # 未记录场景时按 file_id=V01 的名称前缀在产品资料列表里定位（不直接查库）
                listing = self.get_json("/api/v1/documents?limit=100")
                candidates = [
                    item
                    for item in listing.get("items") or []
                    if str(item.get("name") or "").startswith("V01_")
                ]
                if candidates:
                    document_id = candidates[0]["id"]
                    note = "按名称前缀 V01_ 定位 C05 遗留资料"
            if document_id is None:
                result = {
                    "applied": True,
                    "revision": self.revision(),
                    "deleted_document_id": None,
                    "file": "V01",
                    "note": "V01 未发布或不存在，无需清理（幂等）",
                }
            else:
                detail = self.detail(document_id)
                if detail["document"].get("deleted"):
                    result = {
                        "applied": True,
                        "revision": detail["revision"],
                        "deleted_document_id": document_id,
                        "file": "V01",
                        "note": "V01 已删除（幂等重放）",
                    }
                else:
                    admin = self.ensure_admin()
                    response = admin.client.delete(
                        f"/api/v1/documents/{document_id}",
                        params={"expected_revision": detail["revision"]},
                        headers=admin.headers,
                    )
                    if response.status_code != 200:
                        raise RuntimeError(
                            f"清理 V01 资料 {document_id} 失败：HTTP {response.status_code} {response.text[:400]}"
                        )
                    body = response.json()
                    result = {
                        "applied": True,
                        "revision": body.get("revision"),
                        "deleted_document_id": document_id,
                        "file": "V01",
                        "note": note or "逻辑删除 C05 发布的 V01，恢复 U02 冻结前提（B0 恢复后状态）",
                    }
            self.scenarios[name] = result
            self.log("scenario", name=name, params={"file": "V01"}, result=_scenario_summary(result))
            return result

    # ---- 场景：U02 / U03 新版本发布 ----

    def _update_slot_with_new_version(self, *, name: str, slot: str, file_id: str, new_value: str) -> dict:
        existing = self.scenarios.get(name)
        if existing is not None:
            self.log("scenario", name=name, params={"slot": slot, "file": file_id}, result=_scenario_summary(existing), idempotent=True)
            return existing
        document_id = self.b0.slots[slot]
        detail = self.detail(document_id)
        active = detail["document"]["active_version"]
        receipt = self.upload_fixture(
            file_id,
            document_id=document_id,
            expected_active=active["id"] if active else None,
        )
        version_id = receipt["version"]["id"]
        self.wait_version_state(document_id, version_id, "review_required")
        publication = self.publish(
            document_id,
            version_id,
            expected_active=active["id"] if active else None,
            expected_revision=detail["revision"],
        )
        result = {
            "applied": True,
            "slot": slot,
            "file": file_id,
            "document_id": document_id,
            "version_id": version_id,
            "version_number": receipt["version"]["number"],
            "new_value": new_value,
            "revision": publication["revision"],
            "previous_active_version_id": active["id"] if active else None,
        }
        self.scenarios[name] = result
        self.log("scenario", name=name, params={"slot": slot, "file": file_id}, result=_scenario_summary(result))
        return result

    def scenario_update_position(self) -> dict:
        with self._scenario_lock:
            return self._update_slot_with_new_version(
                name="update_position",
                slot="doc-positions",
                file_id="V04",
                new_value="D区暂存柜",
            )

    def scenario_update_phone(self) -> dict:
        with self._scenario_lock:
            return self._update_slot_with_new_version(
                name="update_phone",
                slot="doc-stores",
                file_id="V06",
                new_value="010-00000088",
            )

    # ---- 场景：删除 ----

    def scenario_delete(self, slot: str) -> dict:
        if slot not in ("doc-guide", "doc-positions", "doc-stores"):
            raise HTTPException(status_code=422, detail={"code": "INVALID_SLOT", "slot": slot})
        name = f"delete_{slot.replace('-', '_')}"
        with self._scenario_lock:
            existing = self.scenarios.get(name)
            if existing is not None:
                self.log("scenario", name=name, params={"slot": slot}, result=_scenario_summary(existing), idempotent=True)
                return existing
            document_id = self.b0.slots[slot]
            detail = self.detail(document_id)
            if detail["document"].get("deleted"):
                result = {
                    "applied": True,
                    "slot": slot,
                    "document_id": document_id,
                    "deleted": True,
                    "revision": detail["revision"],
                    "already_deleted": True,
                }
            else:
                admin = self.ensure_admin()
                response = admin.client.delete(
                    f"/api/v1/documents/{document_id}",
                    params={"expected_revision": detail["revision"]},
                    headers=admin.headers,
                )
                if response.status_code != 200:
                    raise RuntimeError(f"删除资料 {document_id} 失败：HTTP {response.status_code} {response.text[:400]}")
                body = response.json()
                result = {
                    "applied": True,
                    "slot": slot,
                    "document_id": document_id,
                    "deleted": bool(body.get("deleted")),
                    "revision": body.get("revision"),
                }
            self.scenarios[name] = result
            self.log("scenario", name=name, params={"slot": slot}, result=_scenario_summary(result))
            return result

    # ---- 场景：材料生成 ----

    def materials_generate(self) -> dict:
        with self._scenario_lock:
            if self.materials is not None:
                self.log("scenario", name="materials_generate", params={}, result={"materials": list(self.materials)}, idempotent=True)
                return {"materials": self.materials}
            payload = generate_materials(self.materials_dir)
            self.materials = payload
            self.log(
                "scenario",
                name="materials_generate",
                params={"materials_dir": str(self.materials_dir)},
                result={
                    "keys": sorted(payload),
                    "ocr_registered": sorted(MATERIAL_OCR_MAP),
                    "files": {key: payload[key]["filename"] for key in payload},
                },
            )
            return {"materials": payload}

    # ---- 状态与 fixtures ----

    def fixtures_snapshot(self) -> dict:
        result: dict = {}

        def add(entry: dict, category: str) -> None:
            path = evidence_support.FIXTURES / entry["path"]
            result[entry["id"]] = {
                "path": str(path.resolve()),
                "filename": Path(entry["path"]).name,
                "kind": entry.get("kind"),
                "category": category,
                "exists": path.is_file(),
                "sha256": entry.get("sha256"),
                "bytes": entry.get("bytes"),
            }

        for entry in b0.MANIFEST.get("normal_files") or []:
            add(entry, "normal")
        for entry in b0.MANIFEST.get("variants") or []:
            add(entry, "variant")
        for entry in b0.MANIFEST.get("boundary") or []:
            add(entry, "boundary")
        return result

    def fixtures_summary(self) -> dict:
        return {
            key: {
                "filename": value["filename"],
                "kind": value["kind"],
                "category": value["category"],
                "exists": value["exists"],
            }
            for key, value in self.fixtures_snapshot().items()
        }

    def state_snapshot(self) -> dict:
        return {
            "status": self.status,
            "label": self.label,
            "data_dir": str(self.data_dir.resolve()),
            "materials_dir": str(self.materials_dir.resolve()),
            "host": self.host,
            "port": self.port,
            "url": f"http://{self.host}:{self.port}",
            "pid": os.getpid(),
            "started_at": datetime.fromtimestamp(self.started_at).astimezone().isoformat(timespec="seconds"),
            "uptime_seconds": round(time.time() - self.started_at, 3),
            "startup_error": self.startup_error,
            "revision": self.revision(),
            "slots": dict(self.b0.slots),
            "documents": _jsonable(self.b0.documents),
            "model_calls": len(self.b0.harness.model.calls),
            "ocr_calls": len(self.ocr.summary()),
            "outbound": self.guard.snapshot(),
            "scenarios": {key: self.scenarios.get(key) for key in self.scenarios},
            "fixtures": self.fixtures_summary(),
            "materials": self.materials or {},
            "worker_running": bool(self.worker is not None and self.worker.is_alive()),
            "worker_stop_requested": self.stop_event.is_set(),
            "gateway": self.model.status(),
        }

    # ---- 启动 / 停服 ----

    def start_worker(self) -> None:
        self.worker = AcceptanceWorker(self)
        self.worker.start()

    def wait_until_serving(self, server) -> None:  # noqa: ANN001
        try:
            deadline = time.monotonic() + READY_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if getattr(server, "started", False):
                    break
                if getattr(server, "should_exit", False):
                    self.startup_error = "uvicorn 在开始监听前退出"
                    return
                time.sleep(0.05)
            else:
                self.startup_error = f"uvicorn 在 {READY_TIMEOUT_SECONDS:.0f}s 内未开始监听"
                server.should_exit = True
                return
            health_started = time.monotonic()
            try:
                healthz_ms = _wait_healthz(f"http://{self.host}:{self.port}/api/v1/healthz", HEALTHZ_TIMEOUT_SECONDS)
            except Exception as exc:  # noqa: BLE001
                self.startup_error = f"healthz 未返回 200：{type(exc).__name__}: {exc}"
                server.should_exit = True
                return
            self.status = "ready"
            self.log(
                "ready",
                url=f"http://{self.host}:{self.port}",
                healthz_ms=healthz_ms,
                healthz_wait_seconds=round(time.monotonic() - health_started, 3),
            )
            # 契约要求启动器先打印一行 READY <url>（ASCII），供运行器/人工确认
            print(f"READY http://{self.host}:{self.port}", flush=True)
            self.start_worker()
        except Exception as exc:  # noqa: BLE001 - 启动期异常必须落到 startup_error
            self.startup_error = f"{type(exc).__name__}: {exc}"
            server.should_exit = True

    def request_shutdown(self, reason: str = "control") -> None:
        self.shutdown_reason = reason
        self.status = "stopping"
        self.log("shutdown_requested", reason=reason)
        if self.server is None:  # pragma: no cover - 控制路由可达时 server 必然存在
            return

        def _trigger() -> None:
            try:
                self.server.should_exit = True
            except Exception:  # noqa: BLE001
                pass

        threading.Timer(0.25, _trigger).start()

    def finalize(self) -> int:
        self.status = "stopping"
        self.stop_event.set()
        if self.worker is not None:
            self.worker.join(WORKER_JOIN_SECONDS)
            if self.worker.is_alive():
                self.log("worker_stop_timeout", seconds=WORKER_JOIN_SECONDS)
        outbound = self.guard.snapshot()
        if self.startup_error is None and self.shutdown_reason is None:
            self.shutdown_reason = "server-run-returned"
        self.log(
            "shutdown",
            reason=self.shutdown_reason,
            startup_error=self.startup_error,
            uptime_seconds=round(time.time() - self.started_at, 3),
            revision=_safe_revision(self),
            model_calls=len(self.b0.harness.model.calls),
            ocr_calls=len(self.ocr.summary()),
            outbound_external_count=len(outbound["external"]),
        )
        # 契约：shutdown 事件之后写最终 outbound 快照
        self.log("outbound", phase="final", **outbound)
        self.logger.close()
        print(f"STOPPED status={self.status} startup_error={bool(self.startup_error)}", flush=True)
        if self.startup_error is not None:
            return 1
        if outbound["external"]:
            return 3
        return 0


def _safe_revision(runtime: AcceptanceRuntime) -> int | None:
    try:
        return runtime.revision()
    except Exception:  # noqa: BLE001
        return None


def _scenario_summary(result: dict) -> dict:
    keys = (
        "applied",
        "case",
        "slot",
        "file",
        "document_id",
        "deleted_document_id",
        "version_id",
        "version_number",
        "revision",
        "new_value",
        "deleted",
        "question",
        "note",
    )
    summary = {key: result[key] for key in keys if key in result}
    return summary


# ---------------------------------------------------------------- 健康检查


# 本机环境可能设置 HTTP(S)_PROXY（另有 NO_PROXY 回环例外）；就绪自检强制直连，避免把代理
# 当作健康检查目标（也避免被出站闸门记录成“外部尝试”）。
_HEALTH_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _wait_healthz(url: str, timeout: float) -> int:
    """轮询真实 HTTP healthz（显式绕过环境代理直连回环），返回耗时毫秒；失败抛最后一次异常。"""
    started = time.monotonic()
    deadline = started + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with _HEALTH_OPENER.open(url, timeout=2.0) as response:
                if response.status == 200:
                    return int((time.monotonic() - started) * 1000)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = exc
        time.sleep(0.1)
    raise TimeoutError(f"等待 {url} 200 超时（最后错误 {type(last_error).__name__ if last_error else 'none'}）")


# ---------------------------------------------------------------- 控制路由


class ConflictRequest(BaseModel):
    case: str = "C05"


class DeleteRequest(BaseModel):
    slot: str = "doc-guide"


class FailNextRequest(BaseModel):
    count: int = 1
    code: str = "MODEL_UNAVAILABLE"


class BlockNextRequest(BaseModel):
    count: int = 1


def _run_control(runtime: AcceptanceRuntime, name: str, params: dict, operation):
    """控制动作统一异常包装：记录失败事件并返回稳定 500 结构（不吞掉真实原因文本）。"""
    try:
        return operation()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        runtime.log("scenario_error", name=name, params=params, type=type(exc).__name__, message=str(exc)[:500])
        raise HTTPException(
            status_code=500,
            detail={"code": "ACCEPTANCE_SCENARIO_FAILED", "scenario": name, "message": str(exc)[:500]},
        ) from exc


def build_control_router(runtime: AcceptanceRuntime) -> APIRouter:
    """契约 §1.2 控制路由：只准备状态/注入故障/登记材料，业务写操作全部走产品 HTTP 接口。"""
    router = APIRouter(prefix="/__acceptance", tags=["acceptance-control"])

    @router.get("/state")
    def acceptance_state() -> dict:
        return runtime.state_snapshot()

    @router.get("/fixtures")
    def acceptance_fixtures() -> dict:
        return runtime.fixtures_snapshot()

    @router.post("/scenario/conflict")
    def acceptance_conflict(payload: ConflictRequest) -> dict:
        case = str(payload.case).upper()
        if case not in ("C05", "C06"):
            raise HTTPException(status_code=422, detail={"code": "INVALID_CASE", "case": payload.case})
        return _run_control(runtime, f"conflict_{case}", {"case": case}, lambda: runtime.scenario_conflict(case))

    @router.post("/scenario/prepare-u02")
    def acceptance_prepare_u02() -> dict:
        return _run_control(runtime, "prepare_u02", {}, runtime.scenario_prepare_u02)

    @router.post("/scenario/update-position")
    def acceptance_update_position() -> dict:
        return _run_control(runtime, "update_position", {}, runtime.scenario_update_position)

    @router.post("/scenario/update-phone")
    def acceptance_update_phone() -> dict:
        return _run_control(runtime, "update_phone", {}, runtime.scenario_update_phone)

    @router.post("/scenario/delete")
    def acceptance_delete(payload: DeleteRequest) -> dict:
        return _run_control(runtime, f"delete_{payload.slot}", {"slot": payload.slot}, lambda: runtime.scenario_delete(payload.slot))

    @router.post("/materials/generate")
    def acceptance_materials_generate() -> dict:
        return _run_control(runtime, "materials_generate", {}, runtime.materials_generate)

    @router.post("/gateway/fail-next")
    def acceptance_gateway_fail_next(payload: FailNextRequest) -> dict:
        code = str(payload.code or "MODEL_UNAVAILABLE").upper()
        if code not in MODEL_FAILURE_CODES:
            raise HTTPException(status_code=422, detail={"code": "INVALID_MODEL_CODE", "allowed": sorted(MODEL_FAILURE_CODES)})
        count = int(payload.count) if payload.count else 0
        if count < 0 or count > 100:
            raise HTTPException(status_code=422, detail={"code": "INVALID_COUNT", "count": payload.count})
        return runtime.model.arm_fail(count, code)

    @router.post("/gateway/block-next")
    def acceptance_gateway_block_next(payload: BlockNextRequest) -> dict:
        count = int(payload.count) if payload.count else 0
        if count < 0 or count > 100:
            raise HTTPException(status_code=422, detail={"code": "INVALID_COUNT", "count": payload.count})
        return runtime.model.arm_block(count)

    @router.get("/gateway/status")
    def acceptance_gateway_status() -> dict:
        return runtime.model.status()

    @router.post("/gateway/release")
    def acceptance_gateway_release() -> dict:
        return runtime.model.release_block()

    @router.post("/shutdown")
    def acceptance_shutdown() -> dict:
        runtime.request_shutdown("control")
        return {"stopping": True, "status": runtime.status}

    @router.get("/healthz")
    def acceptance_healthz() -> dict:
        return {"status": "ok", "label": runtime.label}

    return router


# ---------------------------------------------------------------- 主入口


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="T09-D3 B 层浏览器验收后端服务（真实 uvicorn + B0 + 受控替身 + 控制路由）"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口，默认 8188")
    parser.add_argument("--label", required=True, help="本轮唯一 label（用于日志与材料目录）")
    parser.add_argument("--data-dir", required=True, help="数据目录；必须不存在，服务会全新构建 B0")
    parser.add_argument("--log-file", required=True, help="JSONL 事件日志路径")
    parser.add_argument(
        "--materials-dir",
        default=None,
        help="材料生成目录；默认 <data-dir 同级>/materials",
    )
    parser.add_argument("--ready-timeout", type=float, default=READY_TIMEOUT_SECONDS, help="启动就绪超时秒数")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    global READY_TIMEOUT_SECONDS
    READY_TIMEOUT_SECONDS = float(args.ready_timeout)

    data_dir = Path(args.data_dir).resolve()
    log_file = Path(args.log_file).resolve()
    materials_dir = Path(args.materials_dir).resolve() if args.materials_dir else data_dir.parent / "materials"

    # 契约：数据目录必须不存在，拒绝覆盖
    if data_dir.exists():
        print(f"ERROR data dir already exists: {data_dir}", file=sys.stderr, flush=True)
        return 2
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=False, exist_ok=False)

    logger = JsonlLogger(log_file)
    guard = OutboundGuard()
    guard.install()
    logger.event(
        "start",
        argv=list(sys.argv),
        cwd=str(Path.cwd()),
        python=sys.executable,
        python_version=platform.python_version(),
        platform=platform.platform(),
        pid=os.getpid(),
        label=args.label,
        data_dir=str(data_dir),
        materials_dir=str(materials_dir),
        log_file=str(log_file),
        host=args.host,
        port=int(args.port),
    )
    logger.event("outbound", phase="start", **guard.snapshot())

    patch_b0_settings()
    logger.event("b0_build_start", data_dir=str(data_dir))
    print(f"BUILDING B0 data_dir={data_dir}", flush=True)
    build_started = time.monotonic()
    try:
        b0_case = b0.build_b0(data_dir)
        invariants = b0.assert_b0_invariants(b0_case)
    except BaseException as exc:  # noqa: BLE001 - 构建失败必须留证据并快速退出
        logger.event("b0_build_failed", type=type(exc).__name__, message=str(exc)[:800])
        logger.event("outbound", phase="after_build_failure", **guard.snapshot())
        logger.close()
        print(f"ERROR B0 build failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    build_seconds = round(time.monotonic() - build_started, 3)
    app = b0_case.harness.app
    logger.event(
        "b0_built",
        revision=b0_case.revision,
        slots=dict(b0_case.slots),
        documents=_jsonable(b0_case.documents),
        ocr_calls=len(b0_case.ocr_calls),
        model_calls=len(b0_case.harness.model.calls),
        build_seconds=build_seconds,
        invariants=invariants,
        trusted_origins=list(app.state.settings.trusted_origins),
    )
    logger.event("outbound", phase="after_build", **guard.snapshot())
    print(f"B0 BUILT revision={b0_case.revision} build_seconds={build_seconds}", flush=True)

    runtime = AcceptanceRuntime(
        b0_case=b0_case,
        data_dir=data_dir,
        label=args.label,
        host=args.host,
        port=int(args.port),
        materials_dir=materials_dir,
        logger=logger,
        guard=guard,
    )
    try:
        runtime.ensure_admin()
        logger.event("admin_session_ready", note="控制路由使用独立的 TestClient 管理员会话（CSRF/Origin 齐备）")
    except BaseException as exc:  # noqa: BLE001
        runtime.startup_error = f"管理员会话创建失败：{type(exc).__name__}: {exc}"
        logger.event("admin_session_failed", type=type(exc).__name__, message=str(exc)[:500])
        runtime.finalize()
        return 1

    app.include_router(build_control_router(runtime))
    logger.event(
        "control_router_mounted",
        prefix="/__acceptance",
        routes=[
            "GET /state",
            "GET /fixtures",
            "POST /scenario/conflict",
            "POST /scenario/prepare-u02",
            "POST /scenario/update-position",
            "POST /scenario/update-phone",
            "POST /scenario/delete",
            "POST /materials/generate",
            "POST /gateway/fail-next",
            "POST /gateway/block-next",
            "GET /gateway/status",
            "POST /gateway/release",
            "POST /shutdown",
        ],
    )

    config = uvicorn.Config(
        app,
        host=args.host,
        port=int(args.port),
        log_level="info",
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    runtime.server = server
    helper = threading.Thread(target=runtime.wait_until_serving, args=(server,), name="acceptance-ready", daemon=True)
    helper.start()
    print(f"LISTENING http://{args.host}:{int(args.port)}", flush=True)
    try:
        server.run()
    except BaseException as exc:  # noqa: BLE001 - 启动/运行期异常都要落到 finalize 证据
        runtime.startup_error = f"uvicorn run 异常：{type(exc).__name__}: {exc}"
        logger.event("server_error", type=type(exc).__name__, message=str(exc)[:500])
    finally:
        exit_code = runtime.finalize()
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
