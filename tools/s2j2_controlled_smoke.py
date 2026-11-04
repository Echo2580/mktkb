"""S2-J2 受控 Mock 冒烟：经**实际生产适配器**证明 chat/E/R/OCR 预留→发送边界→结算。

硬边界（Mock-only）：
- 只在传输层注入 ``httpx.MockTransport``；宿主 socket 熔断（外部地址一律拒绝并记录）；
- 隔离 ledger/budget/GO 全部写本轮 ``S2-DEV/J2/data/mock-*/``；真实共享账本/预算/GO 只读 hash；
- 不读 `.env` 内容、不 hash；不开 `var` 数据库；不签 GO、不发真实请求、不部署、不装依赖、不派子代理。

覆盖（每个场景独立隔离账本 + 全新 GO）：
- S1 同一账本 chat/E/R/OCR-text/OCR-table：版本化结算释放差额、OCR 固定价不释放、重放一致；
- S2 chat 超 cap / S3 HTTP 5xx / S4 timeout / S5 中断：全额保留、停机、零重试；
- S6 usage 缺失拆分：J1 fail closed；S7 合成 secret 注入 request_id/usage/OCR 错误路径：账本零泄露；
- S8 每页 tile=1 发送前拒绝；S9 第 14 次 OCR 发送前拒绝；S10 OCR 429 只一次 attempt；
- S11 GO/plan 绑定缺失/篡改（含 secret 原文）：构造期拒绝、0 预留 0 POST；
- S12 授权漂移：预留期拒绝 + 发送前复核拒绝；S13 并发重复结算只一次；
- S14 崩溃未结算保持全额；S15 旧路径（无 policy）旧会计不变；S16 受控适配器可注入产品 app；
- S17 无 GO 拒绝；S18 串行计划并发调用拒绝（不承诺容量并发）。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import socket
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101"
J2 = EV / "S2-DEV" / "J2"
DATA = J2 / "data"
LOGS = J2 / "logs"
MOCK_ROOT = DATA / "s2j2-mock"
REAL_LEDGER = EV / "budget" / "live-ledger.jsonl"
REAL_BUDGET = EV / "budget" / "budget.json"
REAL_GO = EV / "PM" / "S2-LIVE-GO.json"
DOTENV = ROOT / ".env"

if str(ROOT / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "src"))

import mktkb.live_authorization as gate_module  # noqa: E402
from mktkb.config import Settings  # noqa: E402
from mktkb.db import Database, run_migrations  # noqa: E402
from mktkb.documents.models import Document, DocumentVersion  # noqa: E402
from mktkb.ingestion.models import OCRCallRecord  # noqa: E402
from mktkb.ingestion.worker import OcrExecutor, OcrRateLimiter  # noqa: E402
from mktkb.controlled_execution import (  # noqa: E402
    ControlledBindingError,
    ControlledExecution,
    ControlledRefused,
    ControlledRequestPlan,
    _plan_bindings,
)
from mktkb.live_authorization import load_live_authorization  # noqa: E402
from mktkb.providers import build_gateway  # noqa: E402
from mktkb.providers.deepseek import DeepSeekClient  # noqa: E402
from mktkb.providers.types import (  # noqa: E402
    CompletionInput,
    DialogueContext,
    OCRInput,
    OCRRateLimited,
    OCRUnavailable,
)
from mktkb.rag.budget import BudgetLedger, BudgetLedgerInvalid  # noqa: E402
from mktkb.rag.errors import BudgetError  # noqa: E402
from mktkb.rag.controlled_usage import (  # noqa: E402
    ControlledFieldError,
    build_chat_evidence,
    build_total_evidence,
    safe_dimensions,
    safe_error_code,
    safe_request_id,
)
from mktkb.rag.providers import BailianEmbeddingProvider  # noqa: E402
from mktkb.rag.settlement_policy import build_policy  # noqa: E402

STAGE = "S2-J2-MOCK"
STAGE_LIMIT = "9.66"
MAX_REQUESTS = 354
SECRET = "sk-S2J2-SMOKE-SYNTH-SECRET-DO-NOT-LEAK-0123456789"
LONG_SECRET_ID = "Authorization: Bearer " + SECRET
CHAT_USAGE_OK = {
    "prompt_tokens": 1000,
    "completion_tokens": 200,
    "total_tokens": 1200,
    "prompt_cache_hit_tokens": 300,
    "prompt_cache_miss_tokens": 700,
}
CHAT_USAGE_OVER_CAP = {
    "prompt_tokens": 1537,
    "completion_tokens": 10,
    "total_tokens": 1547,
    "prompt_cache_hit_tokens": 0,
    "prompt_cache_miss_tokens": 1537,
}
CHAT_USAGE_NO_SPLIT = {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200}
EMBED_USAGE_OK = {"total_tokens": 1000}
RERANK_USAGE_OK = {"total_tokens": 1000}

_BASE_ENV = {
    "MKTKB_LIVE_STAGE": STAGE,
    "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com/v1",
    "MKTKB_MODEL_NAME": "deepseek-flash",
    "MKTKB_MODEL_API_KEY": "s2j2-mock-model-key-not-real",
    "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY": "2.0",
    "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY": "8.0",
    "MKTKB_MODEL_MAX_INPUT_TOKENS": "6144",
    "MKTKB_MODEL_MAX_OUTPUT_TOKENS": "800",
    "MKTKB_MODEL_CONTEXT_CEILING_TOKENS": "1048576",
    "MKTKB_MODEL_RESERVE_PROFILE": "model_context_ceiling",
    "DASHSCOPE_API_KEY": "s2j2-mock-dashscope-key-not-real",
    "DASHSCOPE_BASE_URL": "https://dashscope.aliyuncs.com",
    "MKTKB_OCR_DISABLED": "0",
    "MKTKB_OCR_SECRET_ID": "s2j2-fake-ocr-id-not-real",
    "MKTKB_OCR_SECRET_KEY": "s2j2-fake-ocr-key-not-real",
    "MKTKB_OCR_REGION": "ap-guangzhou",
    "MKTKB_OCR_ENDPOINT": "https://ocr.tencentcloudapi.com",
    "MKTKB_RAG_STAGE_LIMIT_CNY": STAGE_LIMIT,
    "MKTKB_RAG_MAX_REQUESTS": str(MAX_REQUESTS),
}
_CLEAR_ENV = (
    "MKTKB_RAG_MAX_RETRIES",
    "MKTKB_RAG_BUDGET_LEDGER",
    "MKTKB_RAG_BUDGET_JSON",
    "MKTKB_RAG_STAGE",
    "MKTKB_RAG_MAX_REQUEST_CNY",
    "MKTKB_REQUIRE_TOKEN_METER",
    "MKTKB_TOKENIZER_PATH",
    "MKTKB_TOKENIZER_SHA256",
    "T09_EVIDENCE_ROOT",
)
_RESTORE_ENV: dict[str, str | None] = {}
_GATE_PATHS = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str | None:
    if not Path(path).is_file():
        return None
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- socket 熔断


class SocketGuard:
    """只放行回环/testserver；外部 socket 与真实 HTTPTransport 一律记录并拒绝。"""

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self.external: list[str] = []
        self._real_connect = socket.socket.connect
        self._real_connect_ex = socket.socket.connect_ex
        self._real_create = socket.create_connection
        self._real_resolve = socket.getaddrinfo
        self._real_http = httpx.HTTPTransport.handle_request
        self._real_async_http = httpx.AsyncHTTPTransport.handle_async_request

    @staticmethod
    def _allowed(host: object) -> bool:
        text = str(host)
        return text in {"127.0.0.1", "::1", "localhost", "testserver", "0.0.0.0", ""} or text.startswith("127.")

    def _record(self, label: str, host: object) -> None:
        self.attempts.append(label)
        if not self._allowed(host):
            self.external.append(label)

    def install(self) -> "SocketGuard":
        guard = self

        def connect(sock, address, *args, **kwargs):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else address
            guard._record(f"socket.connect {host!r}", host)
            if not guard._allowed(host):
                raise RuntimeError("s2j2-guard blocked external socket")
            return guard._real_connect(sock, address, *args, **kwargs)

        def connect_ex(sock, address, *args, **kwargs):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else address
            guard._record(f"socket.connect_ex {host!r}", host)
            raise RuntimeError("s2j2-guard blocked connect_ex")

        def create_connection(address, *args, **kwargs):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else address
            guard._record(f"socket.create_connection {host!r}", host)
            if not guard._allowed(host):
                raise RuntimeError("s2j2-guard blocked create_connection")
            return guard._real_create(address, *args, **kwargs)

        def getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
            guard._record(f"socket.getaddrinfo {host!r}", host)
            if not guard._allowed(host):
                raise RuntimeError("s2j2-guard blocked getaddrinfo")
            return guard._real_resolve(host, *args, **kwargs)

        def handle_request(transport, request):  # noqa: ANN001
            guard._record(f"httpx.HTTPTransport {request.url}", str(request.url.host))
            raise RuntimeError("s2j2-guard blocked real HTTPTransport")

        async def handle_async_request(transport, request):  # noqa: ANN001
            guard._record(f"httpx.AsyncHTTPTransport {request.url}", str(request.url.host))
            raise RuntimeError("s2j2-guard blocked real AsyncHTTPTransport")

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.create_connection = create_connection
        socket.getaddrinfo = getaddrinfo
        httpx.HTTPTransport.handle_request = handle_request
        httpx.AsyncHTTPTransport.handle_async_request = handle_async_request
        return self

    def uninstall(self) -> "SocketGuard":
        socket.socket.connect = self._real_connect
        socket.socket.connect_ex = self._real_connect_ex
        socket.create_connection = self._real_create
        socket.getaddrinfo = self._real_resolve
        httpx.HTTPTransport.handle_request = self._real_http
        httpx.AsyncHTTPTransport.handle_async_request = self._real_async_http
        return self

    def summary(self) -> dict:
        return {
            "attempts": len(self.attempts),
            "external_attempts": len(self.external),
            "external": list(self.external),
        }


# ---------------------------------------------------------------- Mock 供应商


class MockVendor(httpx.BaseTransport, httpx.AsyncBaseTransport):
    """按 kind 配置返回/异常；只记录调用轨迹，不记录请求头/正文内容。"""

    def __init__(self) -> None:
        self.behavior: dict[str, dict] = {}
        self.calls: list[dict] = []

    def configure(self, kind: str, **values) -> "MockVendor":
        if "raise_" in values:
            values["raise"] = values.pop("raise_")
        self.behavior.setdefault(kind, {}).update(values)
        return self

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        host = request.url.host
        if path.endswith("/embeddings"):
            kind = "embedding"
        elif "rerank" in path:
            kind = "rerank"
        elif path.endswith("/chat/completions"):
            kind = "chat"
        elif host == "ocr.tencentcloudapi.com":
            kind = "ocr"
        else:
            kind = "unknown"
        behavior = self.behavior.get(kind, {})
        self.calls.append(
            {
                "seq": len(self.calls) + 1,
                "kind": kind,
                "host": host,
                "path": path,
                "body_bytes": len(request.content or b""),
                "action": request.headers.get("x-tc-action"),
            }
        )
        delay = float(behavior.get("delay_seconds") or 0.0)
        if delay > 0:
            time.sleep(delay)
        if behavior.get("raise") == "timeout":
            raise httpx.ReadTimeout("s2j2 mock timeout", request=request)
        if behavior.get("raise") == "interrupt":
            raise KeyboardInterrupt("s2j2 mock interrupt")
        if behavior.get("raise") == "transport":
            raise httpx.ConnectError("s2j2 mock transport error", request=request)
        status = int(behavior.get("status", 200))
        request_id = behavior.get("request_id", f"mock-{kind}-{len(self.calls)}")
        if kind == "chat":
            content = behavior.get("content")
            if content is None:
                content = json.dumps({"answer": "根据资料：B区1号货架第二层。", "source_ids": ["s1"]}, ensure_ascii=False)
            payload = {
                "id": request_id,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": behavior.get("finish_reason", "stop"),
                        "message": {"role": "assistant", "content": content},
                    }
                ],
            }
            usage = behavior.get("usage", CHAT_USAGE_OK)
            if usage is not None:
                payload["usage"] = usage
            return httpx.Response(status, json=payload)
        if kind == "embedding":
            body = json.loads(request.content.decode("utf-8"))
            texts = body.get("input") or []
            dimension = int(behavior.get("dimensions", 1024))
            rows = [
                {"object": "embedding", "index": index, "embedding": [0.01] * dimension}
                for index in range(len(texts))
            ]
            payload = {"object": "list", "data": rows, "model": body.get("model")}
            if behavior.get("usage", EMBED_USAGE_OK) is not None:
                payload["usage"] = behavior.get("usage", EMBED_USAGE_OK)
            if request_id is not None:
                payload["id"] = request_id
            return httpx.Response(status, json=payload)
        if kind == "rerank":
            body = json.loads(request.content.decode("utf-8"))
            documents = (body.get("input") or {}).get("documents") or []
            payload = {
                "output": {
                    "results": [
                        {"index": index, "relevance_score": round(1 / (index + 1), 6)}
                        for index in range(len(documents))
                    ]
                },
                "request_id": request_id,
            }
            if behavior.get("usage", RERANK_USAGE_OK) is not None:
                payload["usage"] = behavior.get("usage", RERANK_USAGE_OK)
            return httpx.Response(status, json=payload)
        if kind == "ocr":
            action = str(request.headers.get("x-tc-action") or "").lower()
            if status == 429:
                return httpx.Response(
                    429,
                    json={"Response": {"RequestId": request_id, "Error": {"Code": "RequestLimitExceeded", "Message": "rate"}}},
                )
            if status >= 500:
                return httpx.Response(status, json={"Response": {"RequestId": request_id}})
            if behavior.get("ocr_error") == "auth_secret":
                return httpx.Response(
                    200,
                    json={
                        "Response": {
                            "RequestId": LONG_SECRET_ID,
                            "Error": {
                                "Code": "AuthFailure.SignatureFailure " + SECRET,
                                "Message": "Authorization: Bearer " + SECRET,
                            },
                        }
                    },
                )
            if "recognizetable" in action:
                return httpx.Response(
                    200,
                    json={
                        "Response": {
                            "TableDetections": [
                                {
                                    "Cells": [
                                        {"RowTl": 0, "ColTl": 0, "RowBr": 1, "ColBr": 1, "Text": "表头", "Confidence": 90.0},
                                        {"RowTl": 1, "ColTl": 0, "RowBr": 2, "ColBr": 1, "Text": "值", "Confidence": 90.0},
                                    ]
                                }
                            ],
                            "RequestId": request_id,
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "Response": {
                        "TextDetections": [
                            {
                                "DetectedText": "识别文本",
                                "Confidence": 95.0,
                                "Polygon": [
                                    {"X": 0, "Y": 0},
                                    {"X": 10, "Y": 0},
                                    {"X": 10, "Y": 10},
                                    {"X": 0, "Y": 10},
                                ],
                            }
                        ],
                        "RequestId": request_id,
                    }
                },
            )
        return httpx.Response(404, json={"error": "s2j2 unknown path"})

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self.handle_request(request)

    def count(self, kind: str | None = None) -> int:
        if kind is None:
            return len(self.calls)
        return sum(1 for call in self.calls if call["kind"] == kind)

    def summary(self) -> dict:
        buckets: dict[str, int] = {}
        for call in self.calls:
            buckets[call["kind"]] = buckets.get(call["kind"], 0) + 1
        return {"total": len(self.calls), "by_kind": buckets, "calls": list(self.calls), "external": False}


# ---------------------------------------------------------------- 隔离环境


def apply_env() -> None:
    for key in _CLEAR_ENV:
        _RESTORE_ENV.setdefault(key, os.environ.get(key))
        os.environ.pop(key, None)
    for key, value in _BASE_ENV.items():
        _RESTORE_ENV.setdefault(key, os.environ.get(key))
        os.environ[key] = value
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def restore_env() -> None:
    for key, value in _RESTORE_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def write_ledger(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "event": "historical_import",
                "accounted_cny": 0.03,
                "estimated_success_list_price_cny": 0.0000352,
                "provider_billed_cny": None,
                "note": "S2-J2 isolated mock ledger (not the shared ledger)",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def write_budget(path: Path, ledger: Path, *, limit_cny: float = 10.0, stage_limit: float = 9.66) -> None:
    path.write_text(
        json.dumps(
            {
                "limit_cny": limit_cny,
                "historical_conservative_accounted_cny": 0.03,
                "historical_success_estimated_list_price_cny": 0.0000352,
                "provider_billed_cny": None,
                "stages": {STAGE: stage_limit},
                "ledger": rel(ledger),
                "note": "S2-J2 isolated mock budget; never modifies the shared budget",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def plan_bindings(plan: ControlledRequestPlan) -> dict:
    return _plan_bindings(plan)


def write_go(
    path: Path,
    ledger: Path,
    plan: ControlledRequestPlan,
    *,
    stage_limit: float = 9.66,
    max_requests: int = MAX_REQUESTS,
    max_request_cny: float = 2.11,
    tamper=None,
) -> None:
    bindings = plan_bindings(plan)
    if callable(tamper):
        tamper(bindings)
    now = datetime.now(timezone.utc)
    payload = {
        "document": "S2-LIVE-GO",
        "stage": STAGE,
        "authorization": "S2-J2-MOCK-GO (isolated; not a manager GO)",
        "issued_by": "s2j2-controlled-smoke",
        "nonce": f"s2j2-mock-{uuid.uuid4().hex}",
        "issued_utc": (now - timedelta(minutes=1)).isoformat(),
        "expires_utc": (now + timedelta(minutes=180)).isoformat(),
        "budget_ledger_sha256": sha256_file(ledger),
        "scope": {
            "services": ["rag", "chat"],
            "stage_limits_cny": {STAGE: stage_limit},
            "max_requests": max_requests,
            "max_request_cny": max_request_cny,
            "bindings": bindings,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_gate(paths: dict) -> None:
    _GATE_PATHS.update(
        {
            "SHARED_LEDGER_PATH": gate_module.SHARED_LEDGER_PATH,
            "SHARED_BUDGET_PATH": gate_module.SHARED_BUDGET_PATH,
            "PRODUCT_GO_PATH": gate_module.PRODUCT_GO_PATH,
        }
    )
    gate_module.SHARED_LEDGER_PATH = Path(paths["ledger"])
    gate_module.SHARED_BUDGET_PATH = Path(paths["budget"])
    gate_module.PRODUCT_GO_PATH = Path(paths["go"])


def restore_gate() -> None:
    if not _GATE_PATHS:
        return
    gate_module.SHARED_LEDGER_PATH = _GATE_PATHS["SHARED_LEDGER_PATH"]
    gate_module.SHARED_BUDGET_PATH = _GATE_PATHS["SHARED_BUDGET_PATH"]
    gate_module.PRODUCT_GO_PATH = _GATE_PATHS["PRODUCT_GO_PATH"]


@contextmanager
def isolated(label: str, *, plan: ControlledRequestPlan | None = None, limit_cny=10.0,
             stage_limit=9.66, go_max_requests=MAX_REQUESTS, go_tamper=None, write_go_file=True):
    MOCK_ROOT.mkdir(parents=True, exist_ok=True)
    root = MOCK_ROOT / label
    if root.exists():
        shutil.rmtree(root)
    (root / "app").mkdir(parents=True)
    ledger = root / "live-ledger.jsonl"
    budget = root / "budget.json"
    go = root / "S2-J2-MOCK-GO.json"
    write_ledger(ledger)
    write_budget(budget, ledger, limit_cny=limit_cny, stage_limit=stage_limit)
    plan = plan or ControlledRequestPlan(stage=STAGE)
    if write_go_file:
        write_go(go, ledger, plan, stage_limit=stage_limit, max_requests=go_max_requests, tamper=go_tamper)
    paths = {"root": root, "ledger": ledger, "budget": budget, "go": go, "plan": plan}
    apply_env()
    patch_gate(paths)
    try:
        yield paths
    finally:
        restore_gate()
        restore_env()


def make_settings(paths: dict) -> Settings:
    app_dir = paths["root"] / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        _env_file=None,
        data_dir=app_dir,
        database_url=f"sqlite:///{(app_dir / 'mktkb.sqlite3').as_posix()}",
        storage_dir=app_dir / "storage",
        cookie_secure=False,
        csrf_secret="s2j2-mock-csrf-secret-0123456789",
        admin_password="S2J2AdminPass-1",
        employee_password="S2J2EmployeePass-1",
        trusted_origins=["http://testserver"],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="WARNING",
        rag_qa_enabled=True,
        rag_provider_mode="live",
        rag_sync_on_startup=False,
        rag_page_size=10,
        rag_top_k=8,
        rag_embedding_retry_seconds=30.0,
        model_base_url=os.environ.get("MKTKB_MODEL_BASE_URL"),
        model_name=os.environ.get("MKTKB_MODEL_NAME"),
        model_api_key=os.environ.get("MKTKB_MODEL_API_KEY"),
        model_request_timeout_seconds=5.0,
        ocr_disabled=False,
        ocr_secret_id=os.environ.get("MKTKB_OCR_SECRET_ID"),
        ocr_secret_key=os.environ.get("MKTKB_OCR_SECRET_KEY"),
        ocr_region=os.environ.get("MKTKB_OCR_REGION", "ap-guangzhou"),
        ocr_endpoint=os.environ.get("MKTKB_OCR_ENDPOINT", "https://ocr.tencentcloudapi.com"),
    )


def build_executor(paths: dict, vendor: MockVendor) -> ControlledExecution:
    settings = make_settings(paths)
    return ControlledExecution.build(
        settings=settings,
        plan=paths["plan"],
        data_dir=paths["root"] / "app",
        chat_transport=vendor,
        rag_transport=vendor,
        ocr_transport=vendor,
    )


def read_ledger(paths: dict) -> dict:
    ledger = BudgetLedger(
        paths["ledger"],
        paths["budget"],
        stage=STAGE,
        stage_limit_cny=9.66,
        max_requests=MAX_REQUESTS,
    )
    events = [
        json.loads(line)
        for line in Path(paths["ledger"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = ledger.summary()
    reserved = [event for event in events if event.get("event") == "reserved"]
    results = [event for event in events if event.get("event") == "result"]
    reserved_ids = {event["reservation_id"] for event in reserved}
    result_ids = {event["reservation_id"] for event in results}
    return {
        "summary": summary.as_dict(),
        "reserved": len(reserved),
        "results": len(results),
        "unsettled": sorted(reserved_ids - result_ids),
        "reserve_kinds": sorted(event.get("kind") for event in reserved),
        "result_statuses": sorted({str(event.get("status")) for event in results}),
        "events": events,
    }


def chat_input() -> CompletionInput:
    return CompletionInput(
        purpose="answer",
        question="城东店的联系电话是什么？",
        context=DialogueContext(),
        evidence=(),
    )


def ocr_page(number: int) -> OCRInput:
    return OCRInput(content=b"s2j2-fake-png-bytes-" + bytes([number % 250]), mime_type="image/png", page=number)


def no_secret(text: object) -> bool:
    return "S2J2-SMOKE-SYNTH-SECRET" not in str(text) and "Authorization: Bearer" not in str(text)


def result_payload(*, label: str, paths: dict, vendor: MockVendor, checks: dict, extra: dict | None = None) -> dict:
    ledger = read_ledger(paths)
    payload = {
        "scenario": label,
        "isolated": {key: rel(value) for key, value in paths.items() if isinstance(value, Path)},
        "checks": checks,
        "pass": all(checks.values()),
        "transport": vendor.summary(),
        "ledger": {
            "summary": ledger["summary"],
            "reserved": ledger["reserved"],
            "results": ledger["results"],
            "unsettled": ledger["unsettled"],
            "reserve_kinds": ledger["reserve_kinds"],
            "result_statuses": ledger["result_statuses"],
        },
        "events": ledger["events"],
        "captured_at": now_iso(),
    }
    if extra:
        payload.update(extra)
    return payload


# ---------------------------------------------------------------- 场景


def scenario_s1_mixed() -> dict:
    label = "s1-mixed"
    with isolated(label) as paths:
        vendor = MockVendor()
        executor = build_executor(paths, vendor)
        chat_out = executor.run_chat(chat_input())
        embed_out = executor.run_embedding(["文本一", "文本二"])
        rerank_out = executor.run_rerank("查询", ["文档一", "文档二"])
        ocr_text = executor.run_ocr(ocr_page(1), mode="text")
        ocr_table = executor.run_ocr(ocr_page(2), mode="table")
        ledger = read_ledger(paths)
        replay_a = ledger["summary"]
        replay_b = read_ledger(paths)["summary"]
        events = ledger["events"]
        versioned = [event for event in events if event.get("event") == "result" and "settlement" in event]
        ocr_results = [event for event in events if event.get("event") == "result" and event.get("kind") == "ocr"]
        checks = {
            "chat_answer": bool(chat_out.text),
            "embedding_rows": len(embed_out.vectors) == 2,
            "rerank_rows": len(rerank_out.results) == 2,
            "ocr_text": ocr_text.text == "识别文本",
            "ocr_table": "表头" in ocr_table.text,
            "transport_counts": vendor.count("chat") == 1 and vendor.count("embedding") == 1
            and vendor.count("rerank") == 1 and vendor.count("ocr") == 2,
            "ledger_reserved_5": ledger["reserved"] == 5,
            "ledger_results_5": ledger["results"] == 5,
            "no_unsettled": ledger["unsettled"] == [],
            "kinds": ledger["reserve_kinds"] == ["chat", "embedding", "ocr", "ocr", "rerank"],
            "all_succeeded": ledger["result_statuses"] == ["succeeded"],
            "versioned_chat_emb_rerank": len(versioned) == 3
            and {event["kind"] for event in versioned} == {"chat", "embedding", "rerank"},
            "ocr_fixed_full_price": all(
                event["conservative_charge_cny"] in (0.5, 0.15)
                and event["provider_billed_cny"] is None
                for event in ocr_results
            ),
            "accounted": abs(ledger["summary"]["accounted_cny"] - (0.03 + 0.0036 + 0.0005 + 0.0008 + 0.5 + 0.15)) < 1e-9,
            "history_kept": abs(ledger["summary"]["historical_conservative_cny"] - 0.03) < 1e-12,
            "replay_equal": replay_a == replay_b,
            "executor_stopped": executor.stopped is False,
            "no_secret": no_secret(json.dumps(events, ensure_ascii=False)),
            "external_zero": SocketGuard().summary()["external_attempts"] == 0,
        }
        return result_payload(label=label, paths=paths, vendor=vendor, checks=checks,
                              extra={"counts": executor.stats()["counts"]})


def _failure_scenario(label: str, *, configure, call=None, expect_exc=Exception) -> dict:
    with isolated(label) as paths:
        vendor = MockVendor()
        for kind, values in configure.items():
            vendor.configure(kind, **values)
        executor = build_executor(paths, vendor)
        caught = None
        try:
            if call is None:
                executor.run_chat(chat_input())
            else:
                call(executor)
        except BaseException as exc:  # noqa: BLE001 - 记录失败后仍要取证
            caught = exc
        ledger = read_ledger(paths)
        second_refused = False
        if executor.stopped:
            try:
                executor.run_embedding(["后续调用必须被拒"])
            except ControlledRefused:
                second_refused = True
        chat_results = [event for event in ledger["events"] if event.get("event") == "result"]
        checks = {
            "raised": isinstance(caught, expect_exc) if expect_exc is not Exception else caught is not None,
            "one_chat_post": vendor.count("chat") == 1,
            "ledger_reserved_1": ledger["reserved"] == 1,
            "full_reserve_kept": abs(ledger["summary"]["accounted_cny"] - (0.03 + 2.103552)) < 1e-9,
            "not_released": all(abs(event.get("conservative_charge_cny", 0) - 2.103552) < 1e-9 for event in chat_results),
            "executor_stopped": executor.stopped is True,
            "second_call_refused_no_post": second_refused and vendor.count("embedding") == 0
            and ledger["reserved"] == 1,
            "no_secret": no_secret(str(caught)) and no_secret(json.dumps(ledger["events"], ensure_ascii=False)),
            "external_zero": SocketGuard().summary()["external_attempts"] == 0,
        }
        return result_payload(
            label=label,
            paths=paths,
            vendor=vendor,
            checks=checks,
            extra={"exception": {"type": type(caught).__name__, "code": getattr(caught, "code", None),
                                 "reason": getattr(caught, "reason", None)}},
        )


def scenario_s2_chat_over_cap() -> dict:
    return _failure_scenario(
        "s2-chat-over-cap",
        configure={"chat": {"usage": CHAT_USAGE_OVER_CAP}},
        expect_exc=Exception,
    )


def scenario_s3_chat_http_500() -> dict:
    return _failure_scenario("s3-chat-http-500", configure={"chat": {"status": 500}})


def scenario_s4_chat_timeout() -> dict:
    return _failure_scenario("s4-chat-timeout", configure={"chat": {"raise": "timeout"}})


def scenario_s5_chat_interrupt() -> dict:
    with isolated("s5-chat-interrupt") as paths:
        vendor = MockVendor().configure("chat", raise_="interrupt")
        executor = build_executor(paths, vendor)
        caught = None
        try:
            executor.run_chat(chat_input())
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        ledger = read_ledger(paths)
        checks = {
            "raised_keyboard_interrupt": isinstance(caught, KeyboardInterrupt),
            "one_chat_post": vendor.count("chat") == 1,
            "reserved_1_unsettled": ledger["reserved"] == 1 and ledger["results"] == 0,
            "full_reserve_kept": abs(ledger["summary"]["accounted_cny"] - (0.03 + 2.103552)) < 1e-9,
            "executor_stopped": executor.stopped is True,
            "no_secret": no_secret(json.dumps(ledger["events"], ensure_ascii=False)),
        }
        return result_payload(label="s5-chat-interrupt", paths=paths, vendor=vendor, checks=checks)


def scenario_s6_usage_missing_split() -> dict:
    return _failure_scenario(
        "s6-usage-missing-split",
        configure={"chat": {"usage": CHAT_USAGE_NO_SPLIT}},
    )


def scenario_s7_secret_injection() -> dict:
    with isolated("s7-secret-injection") as paths:
        vendor = MockVendor().configure(
            "embedding",
            usage={"total_tokens": 1000, "api_key": SECRET, "nested": {"authorization": SECRET}},
            request_id=LONG_SECRET_ID,
        )
        executor = build_executor(paths, vendor)
        caught = None
        try:
            executor.run_embedding(["注入 usage 的调用"])
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        # 旧生产适配入口（不传 policy）的字段白名单：直接经 provider._settle 注入
        # request_id/dimensions/error_code 的 synthetic secret（无 HTTP）。
        legacy_provider = BailianEmbeddingProvider(
            executor.rag_config,
            budget=executor.rag_budget,
            transport=vendor,
            settlement_policy=None,
        )
        try:
            legacy_reservation = executor.rag_budget.reserve(
                kind="embedding",
                provider="bailian",
                model="text-embedding-v4",
                max_cny=0.04096,
                request_sha256="b" * 64,
            )
            legacy_provider._settle(  # noqa: SLF001 - 验证旧适配入口字段白名单
                legacy_reservation,
                status="failed",
                request_id=LONG_SECRET_ID,
                dimensions=(LONG_SECRET_ID,),  # type: ignore[arg-type]
                error_code="AuthFailure " + SECRET,
                started=time.monotonic(),
            )
        finally:
            legacy_provider.close()
        ledger = read_ledger(paths)
        ledger_bytes = Path(paths["ledger"]).read_bytes()
        dimension_error = None
        try:
            safe_dimensions([LONG_SECRET_ID])
        except ControlledFieldError as exc:  # noqa: BLE001
            dimension_error = exc
        error_ledger = read_ledger(paths)
        legacy_events = [
            event
            for event in error_ledger["events"]
            if event.get("event") == "result" and event.get("error_code") == "PROVIDER_ERROR"
        ]
        checks = {
            "embedding_rejected": caught is not None and "unknown_usage_field" in str(getattr(caught, "reason", "")),
            "ledger_no_secret": b"S2J2-SMOKE-SYNTH-SECRET" not in ledger_bytes,
            "ledger_no_secret_key_name": b"api_key" not in ledger_bytes and b"authorization" not in ledger_bytes,
            "request_id_not_raw": all(
                not str(event.get("request_id", "")).startswith("Authorization")
                for event in error_ledger["events"]
            ),
            "legacy_fields_sanitized": bool(legacy_events)
            and legacy_events[-1]["request_id"].startswith("sha256:")
            and legacy_events[-1]["dimensions"] is None,
            "dimensions_error_no_secret": no_secret(dimension_error),
            "safe_request_id_hashed": str(safe_request_id(LONG_SECRET_ID)).startswith("sha256:"),
            "safe_error_code_no_secret": no_secret(safe_error_code("AuthFailure " + SECRET)),
            "full_reserve_kept": abs(ledger["summary"]["accounted_cny"] - (0.03 + 2 * 0.04096)) < 1e-9,
            "executor_stopped": executor.stopped is True,
            "exception_message_no_secret": no_secret(str(caught)),
            "external_zero": SocketGuard().summary()["external_attempts"] == 0,
        }
        return result_payload(label="s7-secret-injection", paths=paths, vendor=vendor, checks=checks)


def scenario_s7b_ocr_secret_error() -> dict:
    with isolated("s7b-ocr-secret-error") as paths:
        vendor = MockVendor().configure("ocr", ocr_error="auth_secret")
        executor = build_executor(paths, vendor)
        caught = None
        try:
            executor.run_ocr(ocr_page(1), mode="text")
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        ledger = read_ledger(paths)
        ledger_bytes = Path(paths["ledger"]).read_bytes()
        checks = {
            "ocr_auth_failed": caught is not None and getattr(caught, "code", None) == "OCR_AUTH_FAILED",
            "one_ocr_post": vendor.count("ocr") == 1,
            "full_reserve_kept": abs(ledger["summary"]["accounted_cny"] - (0.03 + 0.5)) < 1e-9,
            "ledger_no_secret": b"S2J2-SMOKE-SYNTH-SECRET" not in ledger_bytes,
            "result_request_id_hashed": all(
                str(event.get("request_id", "")).startswith("sha256:")
                for event in ledger["events"]
                if event.get("event") == "result"
            ),
            "exception_no_secret": no_secret(str(caught)),
            "executor_stopped": executor.stopped is True,
        }
        return result_payload(label="s7b-ocr-secret-error", paths=paths, vendor=vendor, checks=checks)


def scenario_s8_ocr_tile_limit() -> dict:
    with isolated("s8-ocr-tile-limit") as paths:
        vendor = MockVendor()
        executor = build_executor(paths, vendor)
        first = executor.run_ocr(ocr_page(1), mode="text")
        caught = None
        try:
            executor.run_ocr(ocr_page(1), mode="table")
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        ledger = read_ledger(paths)
        checks = {
            "first_ok": first.text == "识别文本",
            "extra_tile_refused_before_send": isinstance(caught, Exception)
            and getattr(caught, "code", None) == "OCR_BUDGET_REFUSED",
            "only_one_ocr_post": vendor.count("ocr") == 1,
            "only_one_reserve": ledger["reserved"] == 1,
            "executor_stopped": executor.stopped is True,
            "accounted": abs(ledger["summary"]["accounted_cny"] - (0.03 + 0.5)) < 1e-9,
        }
        return result_payload(label="s8-ocr-tile-limit", paths=paths, vendor=vendor, checks=checks)


def scenario_s9_ocr_fourteenth() -> dict:
    with isolated("s9-ocr-fourteenth") as paths:
        vendor = MockVendor()
        executor = build_executor(paths, vendor)
        for number in range(1, 13):
            executor.run_ocr(ocr_page(number), mode="text")
        executor.run_ocr(ocr_page(13), mode="table")
        caught = None
        try:
            executor.run_ocr(ocr_page(14), mode="text")
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        ledger = read_ledger(paths)
        checks = {
            "thirteen_posts": vendor.count("ocr") == 13,
            "thirteen_reserves": ledger["reserved"] == 13,
            "fourteenth_refused_before_send": caught is not None,
            "no_fourteenth_post": vendor.count("ocr") == 13,
            "accounted": abs(ledger["summary"]["accounted_cny"] - (0.03 + 12 * 0.5 + 0.15)) < 1e-9,
            "all_succeeded": ledger["result_statuses"] == ["succeeded"],
            "external_zero": SocketGuard().summary()["external_attempts"] == 0,
        }
        return result_payload(
            label="s9-ocr-fourteenth",
            paths=paths,
            vendor=vendor,
            checks=checks,
            extra={"last_refusal": type(caught).__name__ if caught else None},
        )


def scenario_s10_ocr_rate_limited() -> dict:
    with isolated("s10-ocr-rate-limited") as paths:
        vendor = MockVendor().configure("ocr", status=429)
        executor = build_executor(paths, vendor)
        caught = None
        try:
            executor.run_ocr(ocr_page(1), mode="text")
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        ledger = read_ledger(paths)
        checks = {
            "rate_limited": isinstance(caught, OCRRateLimited),
            "one_attempt_only": vendor.count("ocr") == 1,
            "no_retry": vendor.count("ocr") == 1,
            "full_reserve_kept": abs(ledger["summary"]["accounted_cny"] - (0.03 + 0.5)) < 1e-9,
            "result_failed": ledger["result_statuses"] == ["failed"],
            "executor_stopped": executor.stopped is True,
            "second_call_refused": _refused(executor, ocr_page(2), "text"),
            "no_second_post": vendor.count("ocr") == 1,
        }
        return result_payload(label="s10-ocr-rate-limited", paths=paths, vendor=vendor, checks=checks)


def _refused(executor: ControlledExecution, page: OCRInput, mode: str) -> bool:
    try:
        executor.run_ocr(page, mode=mode)  # type: ignore[arg-type]
    except BaseException:  # noqa: BLE001
        return True
    return False


def _go_refusal_case(label: str, tamper=None, *, write_go_file=True, budget_limit=10.0,
                     stage_limit=9.66, go_max_requests=MAX_REQUESTS) -> dict:
    with isolated(
        label,
        write_go_file=write_go_file,
        go_tamper=tamper,
        limit_cny=budget_limit,
        stage_limit=stage_limit,
        go_max_requests=go_max_requests,
    ) as paths:
        vendor = MockVendor()
        caught = None
        try:
            build_executor(paths, vendor)
        except BaseException as exc:  # noqa: BLE001
            caught = exc
        ledger = read_ledger(paths)
        checks = {
            "binding_refused": isinstance(caught, ControlledBindingError),
            "zero_reserve": ledger["reserved"] == 0,
            "zero_posts": vendor.count() == 0,
            "message_no_secret": no_secret(str(caught)),
            "message_mentions_field": bool(str(caught)),
        }
        return result_payload(
            label=label,
            paths=paths,
            vendor=vendor,
            checks=checks,
            extra={"error": {"type": type(caught).__name__ if caught else None, "message": str(caught)[:300]}},
        )


def scenario_s11_go_binding_refusals() -> dict:
    def remove_plan_hash(bindings):
        bindings["rag"].pop("request_plan_sha256")

    def tamper_plan_hash_secret(bindings):
        bindings["chat"]["request_plan_sha256"] = "Authorization: Bearer " + SECRET

    def serial_int(bindings):
        bindings["rag"]["serial"] = 1

    def tiles_two(bindings):
        bindings["rag"]["ocr_max_tiles_per_page"] = 2

    def attempts_three(bindings):
        bindings["rag"]["ocr_max_attempts"] = 3

    def chat_count_short(bindings):
        bindings["chat"]["chat_requests"] = 135

    def cap_wrong(bindings):
        bindings["rag"]["embedding_total_tokens_cap"] = 8192

    def model_wrong(bindings):
        bindings["rag"]["embedding_model"] = "other-embedding-model"

    def ocr_price_wrong(bindings):
        bindings["rag"]["ocr_text_price_cny"] = 0.4

    cases = [
        ("s11a-missing-plan-hash", remove_plan_hash, {}),
        ("s11b-tampered-plan-hash-secret", tamper_plan_hash_secret, {}),
        ("s11c-serial-int", serial_int, {}),
        ("s11d-ocr-tiles-2", tiles_two, {}),
        ("s11e-ocr-attempts-3", attempts_three, {}),
        ("s11f-chat-count-short", chat_count_short, {}),
        ("s11g-cap-wrong", cap_wrong, {}),
        ("s11h-model-wrong", model_wrong, {}),
        ("s11i-ocr-price-wrong", ocr_price_wrong, {}),
        ("s11j-max-requests-too-small", None, {"go_max_requests": 100}),
        ("s11k-stage-limit-too-small", None, {"stage_limit": 9.0, "budget_limit": 10.0}),
        ("s11l-budget-limit-11", None, {"budget_limit": 11.0}),
        ("s11m-no-go", None, {"write_go_file": False}),
    ]
    results = []
    for label, tamper, overrides in cases:
        results.append(_go_refusal_case(label, tamper, **overrides))
    checks = {
        "all_binding_refused": all(item["checks"]["binding_refused"] for item in results),
        "all_zero_reserve": all(item["checks"]["zero_reserve"] for item in results),
        "all_zero_posts": all(item["checks"]["zero_posts"] for item in results),
        "no_secret_echo": all(item["checks"]["message_no_secret"] for item in results),
    }
    return {
        "scenario": "s11-go-binding-refusals",
        "pass": all(checks.values()),
        "checks": checks,
        "cases": [{k: v for k, v in item.items() if k in ("scenario", "pass", "checks", "error")} for item in results],
        "captured_at": now_iso(),
    }


def scenario_s12_auth_drift() -> dict:
    with isolated("s12-auth-drift") as paths:
        vendor = MockVendor()
        executor = build_executor(paths, vendor)
        # 1) 预留期授权漂移：改小 GO 阶段额度后，下一次预留期复核拒绝。
        policy = build_policy("embedding", model="text-embedding-v4")
        reservation = executor.rag_budget.reserve(
            kind="embedding",
            provider="bailian",
            model="text-embedding-v4",
            max_cny=0.04096,
            request_sha256="c" * 64,
            settlement_policy=policy,
        )
        go_payload = json.loads(Path(paths["go"]).read_text(encoding="utf-8"))
        go_payload["scope"]["stage_limits_cny"][STAGE] = 0.001
        Path(paths["go"]).write_text(json.dumps(go_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        reserve_denied = None
        try:
            executor.rag_budget.reserve(
                kind="embedding",
                provider="bailian",
                model="text-embedding-v4",
                max_cny=0.04096,
                request_sha256="d" * 64,
                settlement_policy=policy,
            )
        except BudgetError as exc:  # noqa: BLE001 - 预留期 GO/预算漂移拒绝
            reserve_denied = exc
        # 2) 发送前复核边界：把 GO 过期时间改到过去后 recheck_reservation 必须拒绝。
        go_payload["scope"]["stage_limits_cny"][STAGE] = 9.66
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        go_payload["expires_utc"] = past
        Path(paths["go"]).write_text(json.dumps(go_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        send_denied = None
        try:
            executor.rag_budget.recheck_reservation(reservation)
        except BudgetLedgerInvalid as exc:  # noqa: BLE001
            send_denied = exc
        ledger = read_ledger(paths)
        checks = {
            "reserve_time_drift_denied": reserve_denied is not None,
            "pre_send_drift_denied": send_denied is not None,
            "no_posts": vendor.count() == 0,
            "first_reserve_kept_full": abs(ledger["summary"]["accounted_cny"] - (0.03 + 0.04096)) < 1e-9,
            "no_secret": no_secret(str(reserve_denied)) and no_secret(str(send_denied)),
        }
        return result_payload(label="s12-auth-drift", paths=paths, vendor=vendor, checks=checks)


def scenario_s13_concurrent_duplicate_settle() -> dict:
    with isolated("s13-duplicate-settle") as paths:
        ledger = BudgetLedger(
            paths["ledger"],
            paths["budget"],
            stage=STAGE,
            stage_limit_cny=9.66,
            max_requests=MAX_REQUESTS,
        )
        policy = build_policy("chat", model="deepseek-flash")
        reservation = ledger.reserve(
            kind="chat",
            provider="deepseek",
            model="deepseek-flash",
            max_cny=2.103552,
            request_sha256="e" * 64,
            settlement_policy=policy,
        )
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            evidence = build_chat_evidence(
                policy,
                request_sha256="e" * 64,
                usage=CHAT_USAGE_OK,
                http_status=200,
            )
            try:
                ledger.settle_usage(reservation, evidence=evidence, request_id="mock-chat-1")
            except BudgetLedgerInvalid:
                with lock:
                    outcomes.append("duplicate_rejected")
            else:
                with lock:
                    outcomes.append("settled")

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        events = [json.loads(line) for line in Path(paths["ledger"]).read_text(encoding="utf-8").splitlines() if line.strip()]
        results = [event for event in events if event.get("event") == "result"]
        checks = {
            "one_settled": outcomes.count("settled") == 1,
            "one_rejected": outcomes.count("duplicate_rejected") == 1,
            "result_count_one": len(results) == 1,
            "accounted_once": abs(ledger.summary().accounted_cny - (0.03 + 0.0036)) < 1e-9,
        }
        return {
            "scenario": "s13-duplicate-settle",
            "isolated": {key: rel(value) for key, value in paths.items() if isinstance(value, Path)},
            "checks": checks,
            "pass": all(checks.values()),
            "outcomes": outcomes,
            "captured_at": now_iso(),
        }


def scenario_s14_crash_unsettled() -> dict:
    with isolated("s14-crash-unsettled") as paths:
        ledger = BudgetLedger(
            paths["ledger"],
            paths["budget"],
            stage=STAGE,
            stage_limit_cny=9.66,
            max_requests=MAX_REQUESTS,
        )
        policy = build_policy("chat", model="deepseek-flash")
        ledger.reserve(
            kind="chat",
            provider="deepseek",
            model="deepseek-flash",
            max_cny=2.103552,
            request_sha256="f" * 64,
            settlement_policy=policy,
        )
        reopened = BudgetLedger(
            paths["ledger"],
            paths["budget"],
            stage=STAGE,
            stage_limit_cny=9.66,
            max_requests=MAX_REQUESTS,
        )
        summary = reopened.summary()
        checks = {
            "unsettled_kept_full": abs(summary.accounted_cny - (0.03 + 2.103552)) < 1e-9,
            "history_kept": abs(summary.historical_conservative_cny - 0.03) < 1e-12,
        }
        return {
            "scenario": "s14-crash-unsettled",
            "isolated": {key: rel(value) for key, value in paths.items() if isinstance(value, Path)},
            "checks": checks,
            "pass": all(checks.values()),
            "summary": summary.as_dict(),
            "captured_at": now_iso(),
        }


def scenario_s15_legacy_path() -> dict:
    with isolated("s15-legacy-path") as paths:
        vendor = MockVendor()
        settings = make_settings(paths)
        plan = paths["plan"]
        executor = ControlledExecution.build(
            settings=settings,
            plan=plan,
            data_dir=paths["root"] / "app",
            chat_transport=vendor,
            rag_transport=vendor,
            ocr_transport=vendor,
        )
        old_gateway = build_gateway(settings, gate=executor.chat_gate, transport=vendor)
        old_embed = BailianEmbeddingProvider(
            executor.rag_config,
            budget=executor.rag_budget,
            transport=vendor,
            settlement_policy=None,
        )
        try:
            output = asyncio.run(old_gateway.complete(chat_input(), timeout_seconds=5.0))
            old_embed.embed(["旧路径 embedding"])
        finally:
            asyncio.run(old_gateway.aclose())
            old_embed.close()
        ledger = read_ledger(paths)
        events = ledger["events"]
        results = [event for event in events if event.get("event") == "result"]
        reserved = [event for event in events if event.get("event") == "reserved"]
        checks = {
            "chat_ok": bool(output.text),
            "no_settlement_policy_in_reserved": all("settlement_policy" not in event for event in reserved),
            "old_result_has_no_settlement_block": all("settlement" not in event for event in results),
            "old_chat_charge_equals_full_reserve": any(
                event.get("kind") == "chat" and abs(event.get("conservative_charge_cny", 0) - 2.103552) < 1e-9
                for event in results
            ),
            "old_embed_charge_equals_full_reserve": any(
                event.get("kind") == "embedding" and abs(event.get("conservative_charge_cny", 0) - 0.04096) < 1e-9
                for event in results
            ),
            "history_kept": abs(ledger["summary"]["historical_conservative_cny"] - 0.03) < 1e-12,
            "accounted": abs(ledger["summary"]["accounted_cny"] - (0.03 + 2.103552 + 0.04096)) < 1e-9,
        }
        return result_payload(label="s15-legacy-path", paths=paths, vendor=vendor, checks=checks)


def scenario_s16_app_injection() -> dict:
    with isolated("s16-app-injection") as paths:
        vendor = MockVendor()
        settings = make_settings(paths)
        executor = build_executor(paths, vendor)
        app = executor.create_app(settings, initialize=False)
        qa_engine = app.state.qa
        checks = {
            "model_gateway_injected": app.state.model_gateway is executor.chat_gateway,
            "ocr_gateway_injected": app.state.ocr_gateway is executor.ocr_gateway,
            "controlled_marker": getattr(app.state, "controlled_execution", None) is executor,
            "qa_embedder_versioned": getattr(qa_engine._embedder, "settlement_policy", None) is not None,
            "qa_reranker_versioned": getattr(qa_engine._reranker, "settlement_policy", None) is not None,
            "qa_budget_is_shared_ledger": qa_engine._budget is executor.rag_budget,
            "zero_posts": vendor.count() == 0,
        }
        try:
            app.state.db.dispose()
        except Exception:  # noqa: BLE001
            pass
        try:
            qa_engine.close()
        except Exception:  # noqa: BLE001
            pass
        return {
            "scenario": "s16-app-injection",
            "isolated": {key: rel(value) for key, value in paths.items() if isinstance(value, Path)},
            "checks": checks,
            "pass": all(checks.values()),
            "captured_at": now_iso(),
        }


def scenario_s17_worker_ocr() -> dict:
    """生产 OcrExecutor + 受控 OCR 包装 + 隔离迁移库：worker 每次实际调用前预留、attempt=1。"""
    with isolated("s17-worker-ocr") as paths:
        vendor = MockVendor()
        executor = build_executor(paths, vendor)
        app_dir = paths["root"] / "app"
        db_url = f"sqlite:///{(app_dir / 'worker.sqlite3').as_posix()}"
        run_migrations(db_url)
        database = Database(db_url)
        session = database.session()
        try:
            document = Document(name="S2-J2 worker 图片", file_type="png")
            version = DocumentVersion(
                document=document,
                number=1,
                state="published",
                sha256=hashlib.sha256(b"s2j2-worker-doc").hexdigest(),
                size_bytes=128,
                stored_path=str(app_dir / "stored.png"),
            )
            session.add(document)
            session.add(version)
            session.commit()
            ocr_executor = OcrExecutor(
                session,
                version_id=version.id,
                document_id=document.id,
                gateway=executor.ocr_gateway,
                ensure_live=lambda: None,
                limiter=OcrRateLimiter(max_per_second=1000.0),
                max_attempts=1,
            )
            result = ocr_executor.recognize(ocr_page(1), mode="text")
            refused = None
            try:
                ocr_executor.recognize(ocr_page(1), mode="table")
            except BaseException as exc:  # noqa: BLE001
                refused = exc
            ledger = read_ledger(paths)
            records = session.query(OCRCallRecord).all()
            checks = {
                "worker_ok": result.text == "识别文本",
                "worker_one_attempt": all(record.attempt == 1 for record in records),
                "worker_success_record": any(record.state == "succeeded" for record in records),
                "worker_tile_refused_before_send": refused is not None
                and getattr(refused, "code", None) == "OCR_BUDGET_REFUSED",
                "worker_posts_one": vendor.count("ocr") == 1,
                "worker_reserves_one": ledger["reserved"] == 1,
                "worker_accounted": abs(ledger["summary"]["accounted_cny"] - (0.03 + 0.5)) < 1e-9,
                "worker_request_id_safe": all(
                    record.provider_request_id is None
                    or len(record.provider_request_id) <= 71
                    for record in records
                ),
            }
        finally:
            session.close()
            database.dispose()
        return result_payload(label="s17-worker-ocr", paths=paths, vendor=vendor, checks=checks)


def scenario_s18_serial_concurrency() -> dict:
    with isolated("s18-serial-concurrency") as paths:
        vendor = MockVendor().configure("embedding", delay_seconds=0.3)
        executor = build_executor(paths, vendor)
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            try:
                executor.run_embedding(["并发调用必须被串行拒绝"])
            except ControlledRefused:
                with lock:
                    outcomes.append("refused")
            except Exception:  # noqa: BLE001
                with lock:
                    outcomes.append("error")
            else:
                with lock:
                    outcomes.append("accepted")

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        ledger = read_ledger(paths)
        checks = {
            "one_accepted_one_refused": sorted(outcomes) == ["accepted", "refused"],
            "one_reserve": ledger["reserved"] == 1,
            "one_embedding_post": vendor.count("embedding") == 1,
            "no_capacity_claim": True,
        }
        return {
            "scenario": "s18-serial-concurrency",
            "isolated": {key: rel(value) for key, value in paths.items() if isinstance(value, Path)},
            "checks": checks,
            "pass": all(checks.values()),
            "outcomes": outcomes,
            "captured_at": now_iso(),
        }


# ---------------------------------------------------------------- 主流程


def real_paths() -> dict:
    return {
        "ledger_sha256": sha256_file(REAL_LEDGER),
        "budget_sha256": sha256_file(REAL_BUDGET),
        "go_exists": REAL_GO.exists(),
        "dotenv": {
            "path": rel(DOTENV),
            "size": DOTENV.stat().st_size if DOTENV.is_file() else None,
            "mtime_ns": DOTENV.stat().st_mtime_ns if DOTENV.is_file() else None,
            "content_read": False,
            "content_hashed": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S2-J2 controlled Mock smoke")
    parser.add_argument("--only", default=None, help="只跑指定场景前缀（可选）")
    args = parser.parse_args(argv)
    MOCK_ROOT.mkdir(parents=True, exist_ok=True)
    guard = SocketGuard().install()
    started = now_iso()
    real_start = real_paths()
    scenarios: list[dict] = []
    try:
        for factory in (
            scenario_s1_mixed,
            scenario_s2_chat_over_cap,
            scenario_s3_chat_http_500,
            scenario_s4_chat_timeout,
            scenario_s5_chat_interrupt,
            scenario_s6_usage_missing_split,
            scenario_s7_secret_injection,
            scenario_s7b_ocr_secret_error,
            scenario_s8_ocr_tile_limit,
            scenario_s9_ocr_fourteenth,
            scenario_s10_ocr_rate_limited,
            scenario_s11_go_binding_refusals,
            scenario_s12_auth_drift,
            scenario_s13_concurrent_duplicate_settle,
            scenario_s14_crash_unsettled,
            scenario_s15_legacy_path,
            scenario_s16_app_injection,
            scenario_s17_worker_ocr,
            scenario_s18_serial_concurrency,
        ):
            label = factory.__name__.replace("scenario_", "")
            if args.only and not label.startswith(args.only):
                continue
            print(f"[s2j2-smoke] running {label} ...", flush=True)
            payload = factory()
            scenarios.append(payload)
            print(
                json.dumps(
                    {"scenario": payload.get("scenario", label), "pass": payload.get("pass"),
                     "failed_checks": [k for k, v in (payload.get("checks") or {}).items() if not v]},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    finally:
        guard.uninstall()
    all_pass = all(item.get("pass") for item in scenarios)
    real_end = real_paths()
    real_unchanged = real_start == real_end and real_end["go_exists"] is False
    result = {
        "document": "S2-J2-controlled-mock-smoke",
        "captured_at": now_iso(),
        "started_at": started,
        "stage": STAGE,
        "mode": "mock-only",
        "plan": ControlledRequestPlan(stage=STAGE).plan_dict(),
        "request_plan_sha256": ControlledRequestPlan(stage=STAGE).request_plan_sha256,
        "scenarios": scenarios,
        "all_pass": all_pass and real_unchanged,
        "scenario_count": len(scenarios),
        "real_paths_start": real_start,
        "real_paths_end": real_end,
        "real_paths_unchanged": real_unchanged,
        "socket_guard": guard.summary(),
        "external_attempts": guard.summary()["external_attempts"],
        "boundaries": {
            "real_go_signed": False,
            "real_api_calls": 0,
            "real_ledger_or_budget_written": False,
            "env_content_read": False,
            "var_database_opened": False,
            "subagents": 0,
            "dependencies_installed": False,
            "git_initialized": False,
            "deployed": False,
        },
    }
    out = DATA / "s2j2-smoke-results.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 全结果文件零 secret 扫描
    leak = "S2J2-SMOKE-SYNTH-SECRET" in out.read_text(encoding="utf-8")
    result["result_file_secret_leak"] = leak
    print(json.dumps({"all_pass": result["all_pass"], "scenarios": len(scenarios), "result": rel(out),
                      "external_attempts": result["external_attempts"], "real_unchanged": real_unchanged,
                      "secret_leak": leak}, ensure_ascii=False))
    return 0 if result["all_pass"] and not leak else 2


if __name__ == "__main__":
    raise SystemExit(main())
