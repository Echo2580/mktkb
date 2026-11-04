"""S2-H-R3 真实 smoke 入口（默认 plan；开发期只 Mock；不签 GO、不调真实供应商）。

三种模式：
- 默认 / ``--plan``：只出计划与可执行命令，不构造 app、不发任何请求、不写真实账本。
- ``--mock``：生产 HTTP 问答 + 生产预算/授权 + 隔离 Mock GO/账本 + 仅替换传输层。
  覆盖：两问正常（真实请求体 token 上界）、429/超时零重发、超 cap 不 POST、
  各拒绝路径、OCR 明确排除。
- ``--live``：显式准备付费路径；本轮**只做准备与拒绝**（无正式 GO），
  所有前提在首个预留/POST 之前核对，且任何情况下都不发送。

硬边界：
- 产品问答模型仍是官方 DeepSeek ``deepseek-flash``（api.deepseek.com）；编码助手用 wb 与此无关。
- 只在传输层注入 ``httpx.MockTransport``；不改预算/GO 校验代码，不 monkeypatch ``RagConfig.from_env``，
  零自动重试是产品配置（``require_zero_retries``）的实际效果，不是测试猴补。
- 隔离 Mock GO/预算/账本全部写在本轮 ``S2-DEV/H-R3/data/mock-*``；真实共享账本/预算只读 hash。
- 官方 tokenizer artifact 只读复用 ``S2-DEV/H/vendor``（不重下载、不写入、不开 pycache）。
- ``MKTKB_OCR_DISABLED=1`` + 清空/覆盖 OCR 凭据：不构造 OCR 客户端，需 OCR 的输入在发送前失败。

用法（cwd 仓库根，.venv）：
    # 计划（默认）
    .venv/Scripts/python.exe -B tools/s2h_mock_smoke.py
    # Mock 全套
    T09_EVIDENCE_ROOT=docs/evidence/LOCAL-R1-20261101/S2-DEV/H-R3/data/t09-output \
    .venv/Scripts/python.exe -B tools/s2h_mock_smoke.py --mock --all
    # 未来 live（本轮无 GO，会拒绝）
    .venv/Scripts/python.exe -B tools/s2h_mock_smoke.py --live
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101"
HR1 = EV / "S2-DEV" / "H-R1"  # 只读：旧诊断/artifact/plan 参考
HR3 = EV / "S2-DEV" / "H-R3"
OLD_H = EV / "S2-DEV" / "H"
DATA = HR3 / "data"
LOGS = HR3 / "logs"
T09_ROOT = (DATA / "t09-output").resolve()
VENDOR_PY = OLD_H / "vendor" / "py"
ARTIFACT = OLD_H / "vendor" / "tokenizer_deepseek_v4" / "deepseek_v4_tokenizer" / "tokenizer.json"
TOKENIZER_SHA = "89085f12ef79460ac5f66d1119325ddfc694b4ab209d80bbd81d35f081dc9614"

REAL_LEDGER = EV / "budget" / "live-ledger.jsonl"
REAL_BUDGET = EV / "budget" / "budget.json"
REAL_GO = EV / "PM" / "S2-LIVE-GO.json"

ORIGIN = "http://testserver"
ADMIN_PASSWORD = "S2HAdminPass-1"
EMPLOYEE_PASSWORD = "S2HEmployeePass-1"
STAGE = "S2-H-R3-MOCK"
PRODUCT_HOST = "api.deepseek.com"
DASHSCOPE_HOST = "dashscope.aliyuncs.com"
PRODUCT_MODEL = "deepseek-flash"
CHAT_MAX_OUTPUT_TOKENS = 800
CHAT_MAX_INPUT_TOKENS = 6144  # payload 闸门值（refuse-above），不是"每次请求的上界已证明"
CONTEXT_CEILING_TOKENS = 1_048_576  # 官方 1M 的十进制/二进制歧义取较大者，保守
RESERVE_PROFILE = "model_context_ceiling"
EMBEDDING_BOUND_CNY = 10 * 8192 * 0.5 / 1_000_000.0
RERANK_BOUND_CNY = 30000 * 0.8 / 1_000_000.0
CHAT_INPUT_PRICE = 2.0
CHAT_OUTPUT_PRICE = 8.0
CHAT_RESERVE_PER_REQUEST_CNY = (
    CONTEXT_CEILING_TOKENS * CHAT_INPUT_PRICE / 1_000_000.0
    + CHAT_MAX_OUTPUT_TOKENS * CHAT_OUTPUT_PRICE / 1_000_000.0
)  # 2.103552
WORST_13_REQUESTS_CNY = (
    5 * EMBEDDING_BOUND_CNY + 4 * RERANK_BOUND_CNY + 4 * CHAT_RESERVE_PER_REQUEST_CNY
)  # 8.715008
TWO_QUESTION_CNY = 5 * EMBEDDING_BOUND_CNY + 4 * RERANK_BOUND_CNY + 2 * CHAT_RESERVE_PER_REQUEST_CNY


def _fail(message: str) -> "SystemExit":
    return SystemExit(f"[s2h] {message}")


# ---------------------------------------------------------------- 证据根（导入 support 前）


def _verify_t09(reason: str) -> Path:
    raw = os.environ.get("T09_EVIDENCE_ROOT")
    if not raw:
        raise _fail(f"T09_EVIDENCE_ROOT 未设置，拒绝启动（{reason}）")
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    resolved = path.resolve()
    if resolved != T09_ROOT and T09_ROOT not in resolved.parents:
        raise _fail(f"T09_EVIDENCE_ROOT={resolved} 不在 {T09_ROOT} 之下（{reason}）")
    if not resolved.exists():
        raise _fail(f"T09_EVIDENCE_ROOT={resolved} 不存在（{reason}）")
    return resolved


T09_RESOLVED = _verify_t09("before importing support")

if str(ROOT / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "src"))
if str(ROOT / "backend" / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "tests"))

from acceptance.support import b0  # noqa: E402
from acceptance.support.evidence import EVIDENCE_ROOT  # noqa: E402
from conftest import current_csrf, login, upload_document, write_headers  # noqa: E402

if EVIDENCE_ROOT.resolve() != T09_RESOLVED:
    raise _fail(f"evidence 解析不一致：{EVIDENCE_ROOT.resolve()} != {T09_RESOLVED}")


# ---------------------------------------------------------------- 基础


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return Path(path).resolve().relative_to(ROOT).as_posix()


def dump_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def tokenizer_available() -> tuple[bool, str]:
    if not ARTIFACT.is_file():
        return False, "tokenizer.json 不存在"
    actual = sha256_path(ARTIFACT)
    if actual != TOKENIZER_SHA:
        return False, f"tokenizer.json sha256={actual} 与记录不一致"
    if not VENDOR_PY.is_dir():
        return False, "隔离 tokenizers 目录不存在"
    return True, "ok"


def install_vendor_path() -> None:
    if str(VENDOR_PY) not in sys.path:
        sys.path.insert(0, str(VENDOR_PY))


class SocketGuard:
    """只放行回环/testserver；外部 socket 与真实 HTTPTransport 一律记录并拒绝。"""

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self.external: list[str] = []
        self.hosts: list[str] = []
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
        self.hosts.append(str(host))
        if not self._allowed(host):
            self.external.append(label)

    def install(self) -> "SocketGuard":
        guard = self

        def connect(sock, address, *args, **kwargs):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else address
            guard._record(f"socket.connect {host!r}", host)
            if not guard._allowed(host):
                raise RuntimeError(f"s2h-guard blocked external socket: {host}")
            return guard._real_connect(sock, address, *args, **kwargs)

        def connect_ex(sock, address, *args, **kwargs):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else address
            guard._record(f"socket.connect_ex {host!r}", host)
            raise RuntimeError(f"s2h-guard blocked connect_ex: {host}")

        def create_connection(address, *args, **kwargs):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else address
            guard._record(f"socket.create_connection {host!r}", host)
            if not guard._allowed(host):
                raise RuntimeError(f"s2h-guard blocked external socket: {host}")
            return guard._real_create(address, *args, **kwargs)

        def getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
            guard._record(f"socket.getaddrinfo {host!r}", host)
            if not guard._allowed(host):
                raise RuntimeError(f"s2h-guard blocked getaddrinfo: {host}")
            return guard._real_resolve(host, *args, **kwargs)

        def handle_request(transport, request):  # noqa: ANN001
            guard._record(f"httpx.HTTPTransport {request.url}", str(request.url.host))
            raise RuntimeError(f"s2h-guard blocked real HTTPTransport: {request.url}")

        async def handle_async_request(transport, request):  # noqa: ANN001
            guard._record(f"httpx.AsyncHTTPTransport {request.url}", str(request.url.host))
            raise RuntimeError(f"s2h-guard blocked real AsyncHTTPTransport: {request.url}")

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.create_connection = create_connection
        socket.getaddrinfo = getaddrinfo
        httpx.HTTPTransport.handle_request = handle_request
        httpx.AsyncHTTPTransport.handle_async_request = handle_async_request
        return self

    def uninstall(self) -> "SocketGuard":
        """真实发送阶段必须恢复原始 socket/httpx；只在 preflight 全部通过后调用。"""
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
            "hosts": sorted(set(self.hosts)),
        }


import httpx  # noqa: E402  (guard 需要 httpx 符号已存在)
from fastapi.testclient import TestClient  # noqa: E402

import mktkb.live_authorization as gate_module  # noqa: E402
import mktkb.main as main_module  # noqa: E402
import mktkb.rag.providers as providers_module  # noqa: E402
from mktkb.config import Settings  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import _ocr_from_env, run_one_job  # noqa: E402
from mktkb.providers import build_gateway as real_build_gateway  # noqa: E402
from mktkb.providers import interrupt_trace as interrupt_trace_module  # noqa: E402
from mktkb.providers import build_ocr_gateway  # noqa: E402
from mktkb.providers.budgeted import BudgetedModelGateway, ChatPricing  # noqa: E402
from mktkb.providers.deepseek import DeepSeekClient  # noqa: E402
from mktkb.providers.token_metering import (  # noqa: E402
    DeepSeekPromptMeter,
    TokenMeterError,
    load_meter_from_env,
)
from mktkb.providers.types import CompletionInput, DialogueContext  # noqa: E402
from mktkb.rag import budget as budget_module  # noqa: E402
from mktkb.rag.config import RagConfig, safe_config_summary  # noqa: E402
from mktkb.rag.providers import FakeEmbeddingProvider  # noqa: E402


# ---------------------------------------------------------------- 隔离 Mock 授权/预算


def _historical_ledger(path: Path) -> None:
    event = {
        "event": "historical_import",
        "accounted_cny": 0.03,
        "estimated_success_list_price_cny": 0.0000352,
        "provider_billed_cny": None,
        "note": "S2-H-R3 isolated mock ledger (not the shared ledger)",
    }
    path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_budget(path: Path, ledger: Path, *, stage_limit_cny: float) -> None:
    payload = {
        "limit_cny": 10.0,
        "historical_conservative_accounted_cny": 0.03,
        "historical_success_estimated_list_price_cny": 0.0000352,
        "provider_billed_cny": None,
        "stages": {STAGE: stage_limit_cny},
        "ledger": rel(ledger),
        "note": "S2-H-R3 isolated mock budget; never modifies the shared budget",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_go(
    path: Path,
    ledger: Path,
    *,
    stage_limit_cny: float,
    max_requests: int,
    max_request_cny: float,
    bindings: dict | None,
    services: tuple[str, ...] = ("rag", "chat"),
    ledger_sha256: str | None = None,
    stage: str = STAGE,
    expires_minutes: int = 120,
) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "document": "S2-LIVE-GO",
        "stage": stage,
        "authorization": "S2-H-R3-MOCK-GO (isolated; not a manager GO)",
        "issued_by": "s2h-mock-smoke",
        "nonce": f"s2h-mock-{uuid.uuid4().hex}",
        "issued_utc": (now - timedelta(minutes=1)).isoformat(),
        "expires_utc": (now + timedelta(minutes=expires_minutes)).isoformat(),
        "budget_ledger_sha256": ledger_sha256 or sha256_path(ledger),
        "scope": {
            "services": list(services),
            "stage_limits_cny": {stage: stage_limit_cny},
            "max_requests": max_requests,
            "max_request_cny": max_request_cny,
            "bindings": bindings,
        },
    }
    if bindings is None:
        payload["scope"].pop("bindings")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mock_bindings(*, model: str = "deepseek-flash") -> dict:
    """合法绑定：字段与运行期值一致；Mock 与 live 用同一组校验，只是文件路径不同。"""
    return {
        "rag": {
            "base_url_host": "dashscope.aliyuncs.com",
            "embedding_model": "text-embedding-v4",
            "embedding_dimensions": 1024,
            "rerank_model": "gte-rerank-v2",
            "region": "beijing",
        },
        "chat": {
            "base_url_host": "api.deepseek.com",
            "model": model,
            "thinking": "disabled",
            "max_output_tokens": CHAT_MAX_OUTPUT_TOKENS,
            "max_input_tokens": CHAT_MAX_INPUT_TOKENS,
            "reserve_profile": RESERVE_PROFILE,
            "context_ceiling_tokens": CONTEXT_CEILING_TOKENS,
            "input_price_per_million_cny": CHAT_INPUT_PRICE,
            "output_price_per_million_cny": CHAT_OUTPUT_PRICE,
        },
    }


def setup_isolated(
    label: str,
    *,
    stage_limit_cny: float = 8.72,
    max_requests: int = 13,
    max_request_cny: float = 2.11,
    write_go: bool = True,
    services: tuple[str, ...] = ("rag", "chat"),
    ledger_sha256: str | None = None,
    bindings: dict | None = "__default__",
) -> dict:
    root = (DATA / f"mock-{label}").resolve()
    if DATA.resolve() not in root.parents:
        raise SystemExit(f"REFUSE: 隔离目录 {root} 不在 {DATA} 之下")
    if root.exists():
        # 只清本轮自己的 Mock 跑批目录；不触碰任何旧轮证据。每次都记入 data/mock-runs.jsonl。
        shutil.rmtree(root)
    root.mkdir(parents=True)
    with (DATA / "mock-runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": now_iso(), "reset_dir": rel(root)}, ensure_ascii=False) + "\n")
    ledger = root / "live-ledger.jsonl"
    budget = root / "budget.json"
    go = root / "S2-H-R3-MOCK-GO.json"
    _historical_ledger(ledger)
    _write_budget(budget, ledger, stage_limit_cny=stage_limit_cny)
    if write_go:
        if bindings == "__default__":
            bindings = mock_bindings()
        _write_go(
            go,
            ledger,
            stage_limit_cny=stage_limit_cny,
            max_requests=max_requests,
            max_request_cny=max_request_cny,
            bindings=bindings,
            services=services,
            ledger_sha256=ledger_sha256,
        )
    return {"root": root, "ledger": ledger, "budget": budget, "go": go}


def patch_gate(paths: dict) -> None:
    gate_module.SHARED_LEDGER_PATH = Path(paths["ledger"])
    gate_module.SHARED_BUDGET_PATH = Path(paths["budget"])
    gate_module.PRODUCT_GO_PATH = Path(paths["go"])


def restore_gate_paths() -> None:
    gate_module.SHARED_LEDGER_PATH = REAL_LEDGER
    gate_module.SHARED_BUDGET_PATH = REAL_BUDGET
    gate_module.PRODUCT_GO_PATH = REAL_GO


_BASE_ENV = {
    "MKTKB_LIVE_STAGE": STAGE,
    # Mock 也使用官方 host/型号/价格/上限：只有传输层与文件路径不同，校验不豁免。
    "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com/v1",
    "MKTKB_MODEL_NAME": "deepseek-flash",
    "MKTKB_MODEL_API_KEY": "s2h-mock-model-key-not-real",
    "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY": str(CHAT_INPUT_PRICE),
    "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY": str(CHAT_OUTPUT_PRICE),
    "MKTKB_MODEL_MAX_INPUT_TOKENS": str(CHAT_MAX_INPUT_TOKENS),
    "MKTKB_MODEL_MAX_OUTPUT_TOKENS": str(CHAT_MAX_OUTPUT_TOKENS),
    "MKTKB_MODEL_CONTEXT_CEILING_TOKENS": str(CONTEXT_CEILING_TOKENS),
    "MKTKB_MODEL_RESERVE_PROFILE": RESERVE_PROFILE,
    "DASHSCOPE_API_KEY": "s2h-mock-dashscope-key-not-real",
    "DASHSCOPE_BASE_URL": "https://dashscope.aliyuncs.com",
    "MKTKB_OCR_DISABLED": "1",
    # 故意保留假 OCR 凭据：证明 MKTKB_OCR_DISABLED 优先，不构造客户端。
    "MKTKB_OCR_SECRET_ID": "s2h-fake-ocr-id-never-real",
    "MKTKB_OCR_SECRET_KEY": "s2h-fake-ocr-key-never-real",
}
_CLEAR_ENV = (
    "MKTKB_RAG_MAX_RETRIES",
    "MKTKB_RAG_BUDGET_LEDGER",
    "MKTKB_RAG_BUDGET_JSON",
    "MKTKB_RAG_STAGE",
    "MKTKB_RAG_MAX_REQUEST_CNY",
    "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY",
    "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY",
    "MKTKB_MODEL_MAX_INPUT_TOKENS",
    "MKTKB_MODEL_MAX_OUTPUT_TOKENS",
    "MKTKB_MODEL_CONTEXT_CEILING_TOKENS",
    "MKTKB_MODEL_RESERVE_PROFILE",
    "MKTKB_REQUIRE_TOKEN_METER",
    "MKTKB_TOKENIZER_PATH",
    "MKTKB_TOKENIZER_SHA256",
    "MKTKB_OCR_DISABLED",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
    "MKTKB_MODEL_BASE_URL",
    "MKTKB_MODEL_NAME",
    "MKTKB_MODEL_API_KEY",
)


def apply_env(
    *,
    max_requests: int | str = 13,
    stage_limit: str = "8.72",
    overrides: dict[str, str | None] | None = None,
) -> dict:
    """设置 Mock 进程环境；overrides 里值为 None 表示删除该变量。"""
    for key in _CLEAR_ENV:
        os.environ.pop(key, None)
    env = {
        **_BASE_ENV,
        "MKTKB_RAG_STAGE_LIMIT_CNY": str(stage_limit),
        "MKTKB_RAG_MAX_REQUESTS": str(max_requests),
    }
    for key, value in (overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    os.environ.update(env)
    return {key: ("<unset>" if key not in env else env[key]) for key in sorted(set(_BASE_ENV) | set(overrides or {}))}


# ---------------------------------------------------------------- MockTransport


class MockProvider:
    """只在传输层伪造供应商响应；请求体大小/计数/token 上界都按真实 payload 记录。"""

    def __init__(self, *, meter: DeepSeekPromptMeter | None = None, mode: str = "ok") -> None:
        self.calls: list[dict] = []
        self.fake = FakeEmbeddingProvider(model="text-embedding-v4", dimensions=1024)
        self.meter = meter
        self.mode = mode
        self.fail_kind: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        path = request.url.path
        if path.endswith("/embeddings"):
            kind = "embedding"
        elif "rerank" in path:
            kind = "rerank"
        elif path.endswith("/chat/completions"):
            kind = "chat"
        else:
            kind = "unknown"
        record = {
            "seq": len(self.calls) + 1,
            "kind": kind,
            "host": request.url.host,
            "path": path,
            "body_bytes": len(request.content or b""),
            "ts": now_iso(),
        }
        if kind == "chat":
            messages = body.get("messages") or []
            record["payload"] = {
                "model": body.get("model"),
                "stream": body.get("stream"),
                "temperature": body.get("temperature"),
                "max_tokens": body.get("max_tokens"),
                "thinking": body.get("thinking"),
                "message_roles": [item.get("role") for item in messages],
                "system_bytes": len(str(messages[0].get("content", "")).encode("utf-8")) if messages else 0,
                "user_bytes": len(str(messages[1].get("content", "")).encode("utf-8")) if len(messages) > 1 else 0,
            }
            if self.meter is not None and len(messages) >= 2:
                bound = self.meter.measure(messages[0]["content"], messages[1]["content"])
                record["payload"]["metered"] = bound.as_dict()
            # 真实请求体（仅 chat；用于核对 payload 结构与 thinking/max_tokens）
            record["payload"]["body"] = body
        self.calls.append(record)

        if self.mode != "ok" and kind == self.fail_kind:
            if self.mode == "timeout":
                raise httpx.ReadTimeout("s2h mock timeout", request=request)
            if self.mode == "429":
                return httpx.Response(429, json={"error": {"message": "s2h mock rate limited"}})
            if self.mode == "interrupt":
                raise KeyboardInterrupt("s2h mock keyboard interrupt")
            raise AssertionError(f"unknown mock mode {self.mode}")

        if kind == "embedding":
            texts = [str(item) for item in body.get("input") or []]
            rows = [
                {"object": "embedding", "index": index, "embedding": list(self.fake._vector(text))}  # noqa: SLF001
                for index, text in enumerate(texts)
            ]
            tokens = min(81920, sum(len(text.encode("utf-8")) for text in texts) or 1)
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": rows,
                    "model": body.get("model") or "text-embedding-v4",
                    "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
                    "id": f"mock-embed-{len(self.calls)}",
                },
            )
        if kind == "rerank":
            docs = [str(item) for item in (body.get("input") or {}).get("documents") or []]
            query = str((body.get("input") or {}).get("query") or "")
            rows = [{"index": index, "relevance_score": round(1.0 / (index + 1), 6)} for index in range(len(docs))]
            tokens = min(
                30000,
                (len(query.encode("utf-8"))) * max(1, len(docs)) + sum(len(d.encode("utf-8")) for d in docs),
            )
            return httpx.Response(
                200,
                json={
                    "output": {"results": rows},
                    "usage": {"total_tokens": max(1, tokens)},
                    "request_id": f"mock-rerank-{len(self.calls)}",
                },
            )
        if kind == "chat":
            messages = body.get("messages") or []
            user = json.loads(messages[1]["content"]) if len(messages) > 1 else {}
            if "evidence" not in user:
                content = json.dumps({"terms": []}, ensure_ascii=False)
            else:
                evidence = user.get("evidence") or []
                fields = (evidence[0].get("fields") or {}) if evidence else {}
                parts = [
                    f"{key}：{value}"
                    for key, value in fields.items()
                    if key in ("门店", "物品", "位置", "联系人", "联系电话", "地址", "合作状态")
                ]
                answer = "根据资料：" + "；".join(parts) if parts else "根据资料：未找到可引用字段。"
                source_ids = [
                    str(item.get("chunk_id") or item.get("source_id"))
                    for item in evidence
                    if item.get("chunk_id") or item.get("source_id")
                ]
                content = json.dumps({"answer": answer, "source_ids": source_ids}, ensure_ascii=False)
            prompt = len((messages[0].get("content") if messages else "").encode("utf-8")) + len(
                messages[1]["content"].encode("utf-8")
            ) if len(messages) > 1 else 1
            completion = min(CHAT_MAX_OUTPUT_TOKENS, max(1, len(content.encode("utf-8"))))
            return httpx.Response(
                200,
                json={
                    "id": f"mock-chat-{len(self.calls)}",
                    "choices": [
                        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
                    ],
                    "usage": {
                        "prompt_tokens": max(1, prompt),
                        "completion_tokens": completion,
                        "total_tokens": max(1, prompt) + completion,
                    },
                },
            )
        return httpx.Response(404, json={"error": "unknown mock path"})

    def summary(self) -> dict:
        buckets: dict[str, int] = {}
        for call in self.calls:
            buckets[call["kind"]] = buckets.get(call["kind"], 0) + 1
        return {"total": len(self.calls), "by_kind": buckets, "calls": list(self.calls)}

    def chat_metered(self) -> list[dict]:
        return [call["payload"]["metered"] for call in self.calls if call["kind"] == "chat" and "metered" in call.get("payload", {})]


_ACTIVE = {"transport": None}
_PATCHED = {"providers": [], "build_gateway": None}


def install_transport(transport: httpx.BaseTransport) -> None:
    """只替换传输层：三个 rag provider 的 httpx.Client transport + 网关 build 调用点。

    不修改预算/GO 校验，也不改 ``RagConfig.from_env``（零重试是产品配置的真实效果）。
    """
    _ACTIVE["transport"] = transport
    for cls in (
        providers_module.BailianEmbeddingProvider,
        providers_module.BailianRerankProvider,
        providers_module.DeepSeekChatProvider,
    ):
        original = cls.__init__
        if getattr(original, "_s2h_patched", False):
            continue

        def make(orig):
            def init(self, config, *, budget=None, transport=None, require_budget=True, **extra):
                # 只替换 transport；其余关键字按原 provider 签名透传。
                return orig(
                    self,
                    config,
                    budget=budget,
                    transport=transport or _ACTIVE["transport"],
                    require_budget=require_budget,
                    **extra,
                )

            init._s2h_patched = True
            return init

        cls.__init__ = make(original)
        _PATCHED["providers"].append((cls, original))

    if _PATCHED["build_gateway"] is None:
        original_build = main_module.build_gateway

        def build_gateway(settings):
            return real_build_gateway(settings, transport=_ACTIVE["transport"])

        main_module.build_gateway = build_gateway
        _PATCHED["build_gateway"] = original_build


def uninstall_transport() -> None:
    for cls, original in _PATCHED["providers"]:
        cls.__init__ = original
    _PATCHED["providers"].clear()
    if _PATCHED["build_gateway"] is not None:
        main_module.build_gateway = _PATCHED["build_gateway"]
        _PATCHED["build_gateway"] = None
    _ACTIVE["transport"] = None


# ---------------------------------------------------------------- 应用与证据


def make_settings(paths: dict) -> Settings:
    data_dir = paths["root"] / "app"
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        _env_file=None,
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'mktkb.sqlite3').as_posix()}",
        storage_dir=data_dir / "storage",
        cookie_secure=False,
        csrf_secret="s2h-mock-csrf-secret-0123456789",
        admin_password=ADMIN_PASSWORD,
        employee_password=EMPLOYEE_PASSWORD,
        trusted_origins=[ORIGIN],
        bcrypt_rounds=4,
        session_ttl_seconds=3600,
        log_level="WARNING",
        rag_qa_enabled=True,
        rag_provider_mode="live",
        rag_sync_on_startup=True,
        rag_page_size=10,
        rag_top_k=8,
        rag_embedding_retry_seconds=30.0,
        model_base_url=os.environ.get("MKTKB_MODEL_BASE_URL"),
        model_name=os.environ.get("MKTKB_MODEL_NAME"),
        model_api_key=os.environ.get("MKTKB_MODEL_API_KEY"),
        model_request_timeout_seconds=5.0,
        # OCR 明确排除：即使环境里有假凭据也不构造客户端。
        ocr_disabled=True,
        ocr_secret_id=os.environ.get("MKTKB_OCR_SECRET_ID"),
        ocr_secret_key=os.environ.get("MKTKB_OCR_SECRET_KEY"),
    )


def read_ledger(paths: dict, *, max_requests: int = 13, stage_limit: float = 8.72, stage: str = STAGE) -> dict:
    ledger = budget_module.BudgetLedger(
        paths["ledger"],
        paths["budget"],
        stage=stage,
        stage_limit_cny=stage_limit,
        max_requests=max_requests,
    )
    summary = ledger.summary()
    events = [json.loads(line) for line in Path(paths["ledger"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    reserved = [event for event in events if event.get("event") == "reserved"]
    results = [event for event in events if event.get("event") == "result"]
    reserved_ids = {event["reservation_id"] for event in reserved}
    result_ids = {event["reservation_id"] for event in results}
    return {
        "summary": summary.as_dict(),
        "events": events,
        "reserved": len(reserved),
        "results": len(results),
        "unsettled": sorted(reserved_ids - result_ids),
        "result_statuses": sorted({str(event.get("status")) for event in results}),
        "kinds": sorted({str(event.get("kind")) for event in reserved}),
        "reserve_cny_by_kind": _sum_by_kind(reserved),
        "conservative_this_round_cny": round(summary.accounted_cny - summary.historical_conservative_cny, 10),
        "estimated_list_price_this_round_cny": round(summary.success_estimated_list_price_cny, 10),
    }


def _sum_by_kind(events: list[dict]) -> dict:
    totals: dict[str, float] = {}
    for event in events:
        kind = str(event.get("kind"))
        totals[kind] = round(totals.get(kind, 0.0) + float(event.get("reserve_cny") or 0.0), 10)
    return totals


def upload_and_publish(client: TestClient, *, csrf: str, file_id: str) -> dict:
    receipt = upload_document(client, csrf=csrf, path=b0.fixture_path(file_id), allow_same_name=False)
    if receipt.status_code != 202:
        raise AssertionError(f"upload {file_id} -> {receipt.status_code} {receipt.text[:400]}")
    record = receipt.json()
    document_id = record["document"]["id"]
    version_id = record["version"]["id"]
    db = client.app.state.db.session()
    try:
        # 生产 worker 单次入口；显式不注入 OCR 网关（等同 _ocr_from_env() 返回 None）。
        result = run_one_job(db, client.app.state.store)
        revision = int(get_revision(db))
    finally:
        db.close()
    published = client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={"expected_active_version_id": None, "expected_revision": revision},
        headers=write_headers(csrf),
    )
    return {
        "file_id": file_id,
        "upload_sha256": sha256_path(b0.fixture_path(file_id)),
        "document_id": document_id,
        "version_id": version_id,
        "worker_state": result.state,
        "worker_error_code": result.error_code,
        "worker_units": result.units_written,
        "publish_status": published.status_code,
        "publish_body": published.json() if published.status_code == 200 else published.text[:300],
    }


def ask(client: TestClient, *, csrf: str, question_id: str, on_before_post=None) -> dict:
    item = next(entry for entry in b0.QUESTIONS if entry["id"] == question_id)
    created = client.post("/api/v1/conversations", json={}, headers=write_headers(csrf))
    conversation = created.json()["id"]
    if on_before_post is not None:
        on_before_post()
    response = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": item["question"]},
        headers=write_headers(csrf),
    )
    payload = response.json() if response.status_code == 200 else {}
    sources = payload.get("sources") or []
    source_ids = [
        str(source.get("source_id"))
        for source in sources
        if isinstance(source, dict) and source.get("source_id")
    ]
    return {
        "question_id": question_id,
        "http_status": response.status_code,
        "kind": payload.get("kind"),
        "error_code": payload.get("error_code"),
        "text": payload.get("text"),
        "source_ids": source_ids,
        "source_count": len(sources),
        "text_chars": len(payload.get("text") or ""),
        "expected_values_present": _expected_values_present(payload, item),
    }


def _expected_values_present(payload: dict, item: dict) -> list[str]:
    """只用于自测对照，不把 expected_values 送进模型或产品。"""
    text = str(payload.get("text") or "")
    return [value for value in item.get("expected_values", []) if value and value in text]


def real_path_hashes() -> dict:
    return {
        "ledger_sha256": sha256_path(REAL_LEDGER) if REAL_LEDGER.is_file() else None,
        "budget_sha256": sha256_path(REAL_BUDGET) if REAL_BUDGET.is_file() else None,
        "go_exists": REAL_GO.exists(),
    }


install_vendor_path()


def _new_meter() -> DeepSeekPromptMeter:
    install_vendor_path()
    return DeepSeekPromptMeter.from_files(ARTIFACT, expected_sha256=TOKENIZER_SHA)


# ---------------------------------------------------------------- 场景：正常两问


class TransportHub(httpx.BaseTransport, httpx.AsyncBaseTransport):
    """单一传输层枢纽：按场景切换 MockProvider，并给出进程级传输计数。

    同时实现同步/异步接口：rag provider 用同步 httpx.Client，产品 chat 网关用异步 AsyncClient。
    """

    def __init__(self) -> None:
        self.provider: MockProvider | None = None
        self.calls: list[dict] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append({"url": str(request.url), "host": request.url.host, "path": request.url.path})
        if self.provider is None:
            raise AssertionError(f"s2h: 未绑定 MockProvider，拒绝真实传输 {request.url}")
        return self.provider.handler(request)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self.handle_request(request)

    def reset(self, provider: MockProvider) -> None:
        self.calls = []
        self.provider = provider

    def count(self, kind: str | None = None) -> int:
        if kind is None:
            return len(self.calls)
        return sum(1 for call in self.calls if _kind_of(call["path"]) == kind)


def _kind_of(path: str) -> str:
    if path.endswith("/embeddings"):
        return "embedding"
    if "rerank" in path:
        return "rerank"
    if path.endswith("/chat/completions"):
        return "chat"
    return "unknown"


HUB = TransportHub()


def scenario_smoke(guard: SocketGuard, meter: DeepSeekPromptMeter) -> dict:
    paths = setup_isolated("smoke", stage_limit_cny=8.72, max_requests=13, max_request_cny=2.11)
    apply_env(max_requests=13, stage_limit="8.72")
    patch_gate(paths)
    provider = MockProvider(meter=meter, mode="ok")
    HUB.reset(provider)
    providers_module.reset_post_counters()
    app = None
    try:
        app = main_module.create_app(make_settings(paths))
        client = TestClient(app, raise_server_exceptions=False)
        login(client, "admin", ADMIN_PASSWORD)
        csrf = current_csrf(client)
        build = upload_and_publish(client, csrf=csrf, file_id="D01")
        answers = [ask(client, csrf=csrf, question_id=qid) for qid in ("Q01", "Q03")]
        qa_config = app.state.qa.config
        gateway_stats = app.state.model_gateway.stats() if hasattr(app.state.model_gateway, "stats") else None
        post_counters = providers_module.post_counters()
        transport = provider.summary()
        metered = provider.chat_metered()
        ledger = read_ledger(paths, max_requests=13)
        real_hashes = real_path_hashes()

        expected_transport = 1 + len(answers) * 5
        chat_expected_total = len(answers) * CHAT_RESERVE_PER_REQUEST_CNY
        chat_expected_each = CHAT_RESERVE_PER_REQUEST_CNY
        chat_calls = [call for call in transport["calls"] if call["kind"] == "chat"]
        checks = {
            "http_all_200": all(item["http_status"] == 200 for item in answers),
            "all_answer": all(item["kind"] == "answer" for item in answers),
            "all_have_sources": all(item["source_count"] > 0 for item in answers),
            "expected_value_hit": all(item["expected_values_present"] for item in answers),
            "worker_succeeded": build["worker_state"] == "succeeded" and build["publish_status"] == 200,
            "transport_expected": transport["total"] == expected_transport,
            "reserved_equals_transport": ledger["reserved"] == transport["total"],
            "settled_equals_reserved": ledger["results"] == ledger["reserved"],
            "unsettled_zero": ledger["unsettled"] == [],
            "only_succeeded": ledger["result_statuses"] == ["succeeded"],
            "product_max_retries_zero": qa_config.max_retries == 0,
            "product_require_zero_retries": qa_config.require_zero_retries is True,
            "product_reserve_profile": qa_config.chat_reserve_profile == RESERVE_PROFILE,
            "product_context_ceiling": qa_config.chat_context_ceiling_tokens == CONTEXT_CEILING_TOKENS,
            "chat_send_attempts": (gateway_stats or {}).get("counters", {}).get("send_attempts") == len(answers),
            "reserve_profile_ceiling": (gateway_stats or {}).get("pricing", {}).get("reserve_profile") == RESERVE_PROFILE,
            "meter_artifact_diagnostic_only": bool(metered)
            and all(
                item["byte_upper_tokens"] == item["rendered_bytes"] and item["exact_tokens"] <= item["rendered_bytes"]
                for item in metered
            ),
            "chat_payload_thinking_disabled": bool(chat_calls)
            and all(call["payload"]["thinking"] == {"type": "disabled"} for call in chat_calls),
            "chat_payload_max_tokens": bool(chat_calls)
            and all(call["payload"]["max_tokens"] == CHAT_MAX_OUTPUT_TOKENS for call in chat_calls),
            "chat_reserve_is_full_ceiling": abs(ledger["reserve_cny_by_kind"].get("chat", 0.0) - chat_expected_total) < 1e-9,
            "chat_bound_is_2103552": abs(
                float((gateway_stats or {}).get("request_bound_cny") or 0.0) - CHAT_RESERVE_PER_REQUEST_CNY
            ) < 1e-12,
            "ocr_gateway_none": app.state.ocr_gateway is None,
            "external_zero": guard.summary()["external_attempts"] == 0,
            "real_go_absent": real_hashes["go_exists"] is False,
        }
        return {
            "scenario": "smoke",
            "mode": "mock",
            "isolated": {key: rel(value) for key, value in paths.items()},
            "build": build,
            "questions": ["Q01", "Q03"],
            "answers": answers,
            "expected_transport": expected_transport,
            "transport": transport,
            "chat_expected_reserve_cny_each_max": round(chat_expected_each, 12),
            "chat_expected_reserve_cny_total": round(chat_expected_total, 12),
            "chat_metered_bounds": metered,
            "post_counters": post_counters,
            "gateway_stats": gateway_stats,
            "qa_config": {
                "provider_mode": qa_config.provider_mode,
                "max_retries": qa_config.max_retries,
                "require_zero_retries": qa_config.require_zero_retries,
                "require_token_meter": qa_config.require_token_meter,
                "chat_reserve_profile": qa_config.chat_reserve_profile,
                "chat_context_ceiling_tokens": qa_config.chat_context_ceiling_tokens,
                "max_output_tokens": qa_config.max_output_tokens,
                "chat_max_input_tokens": qa_config.chat_max_input_tokens,
                "chat_max_output_tokens": qa_config.chat_max_output_tokens,
                "tokenizer_sha256": qa_config.chat_tokenizer_sha256,
                "embedding_retry_seconds": app.state.qa.embedding_retry_seconds,
                "summary": safe_config_summary(qa_config),
            },
            "qa_status": app.state.qa.status(),
            "ledger": ledger,
            "socket_guard": guard.summary(),
            "real_paths": real_hashes,
            "checks": checks,
            "pass": all(checks.values()),
            "captured_at": now_iso(),
        }
    finally:
        restore_gate_paths()
        if app is not None:
            try:
                app.state.db.dispose()
            except Exception:  # noqa: BLE001 - 清理失败不影响证据
                pass


def scenario_zero_retry_429(guard: SocketGuard, meter: DeepSeekPromptMeter) -> dict:
    """Mock 429：同一 chat 请求只发 1 次；首发失败即终止，不继续第二题。"""
    paths = setup_isolated("zero-retry-429", stage_limit_cny=8.72, max_requests=13, max_request_cny=2.11)
    apply_env(max_requests=13, stage_limit="8.72")
    patch_gate(paths)
    provider = MockProvider(meter=meter, mode="429")
    provider.fail_kind = "chat"
    HUB.reset(provider)
    providers_module.reset_post_counters()
    app = None
    try:
        app = main_module.create_app(make_settings(paths))
        client = TestClient(app, raise_server_exceptions=False)
        login(client, "admin", ADMIN_PASSWORD)
        csrf = current_csrf(client)
        build = upload_and_publish(client, csrf=csrf, file_id="D01")
        first = ask(client, csrf=csrf, question_id="Q01")
        # 首发失败即终止本轮：不调用 ask(Q03)。
        transport = provider.summary()
        ledger = read_ledger(paths, max_requests=13)
        post_counters = providers_module.post_counters()
        gateway_stats = app.state.model_gateway.stats() if hasattr(app.state.model_gateway, "stats") else None
        checks = {
            "publish_ok": build["publish_status"] == 200,
            "chat_sent_once": transport["by_kind"].get("chat") == 1,
            "gateway_send_attempt_once": (gateway_stats or {}).get("counters", {}).get("send_attempts") == 1,
            "gateway_failed_once": (gateway_stats or {}).get("counters", {}).get("results", {}).get("failed") == 1,
            "no_second_question": HUB.count("chat") == 1,
            "answer_not_success": first["kind"] != "answer",
            "ledger_chat_failed": "failed" in ledger["result_statuses"],
            "ledger_settled": ledger["unsettled"] == [],
            "external_zero": guard.summary()["external_attempts"] == 0,
        }
        return {
            "scenario": "zero-retry-429",
            "mode": "mock",
            "isolated": {key: rel(value) for key, value in paths.items()},
            "build": build,
            "answer": first,
            "transport": transport,
            "post_counters": post_counters,
            "gateway_stats": gateway_stats,
            "ledger": ledger,
            "socket_guard": guard.summary(),
            "checks": checks,
            "pass": all(checks.values()),
            "captured_at": now_iso(),
        }
    finally:
        restore_gate_paths()
        if app is not None:
            try:
                app.state.db.dispose()
            except Exception:  # noqa: BLE001
                pass


def scenario_zero_retry_timeout(guard: SocketGuard, meter: DeepSeekPromptMeter) -> dict:
    """Mock 超时：发布重索引 embedding 只尝试 1 次；降级后提问不再自动重发。"""
    from mktkb.qa import QaNotReady

    paths = setup_isolated("zero-retry-timeout", stage_limit_cny=8.72, max_requests=13, max_request_cny=2.11)
    apply_env(max_requests=13, stage_limit="8.72")
    patch_gate(paths)
    provider = MockProvider(meter=meter, mode="timeout")
    provider.fail_kind = "embedding"
    HUB.reset(provider)
    providers_module.reset_post_counters()
    app = None
    try:
        app = main_module.create_app(make_settings(paths))
        client = TestClient(app, raise_server_exceptions=False)
        login(client, "admin", ADMIN_PASSWORD)
        csrf = current_csrf(client)
        build = upload_and_publish(client, csrf=csrf, file_id="D01")
        embedding_calls_after_publish = HUB.count("embedding")
        degraded_error = None
        try:
            app.state.qa.ensure_ready()
        except QaNotReady as exc:
            degraded_error = {
                "type": type(exc).__name__,
                "code": getattr(exc, "error_code", None),
                "message": str(exc)[:200],
            }
        first = ask(client, csrf=csrf, question_id="Q01")
        transport = provider.summary()
        ledger = read_ledger(paths, max_requests=13)
        post_counters = providers_module.post_counters()
        status = app.state.qa.status()
        checks = {
            "publish_ok": build["publish_status"] == 200,
            "degraded_marked": "embedding_error" in (status.get("degraded") or ()),
            "embedding_attempted_once": embedding_calls_after_publish == 1,
            "no_resend_after_degraded": HUB.count("embedding") == 1,
            "degraded_error_code": bool(degraded_error)
            and degraded_error.get("code") == "EMBEDDING_DEGRADED_NO_RETRY",
            "answer_index_not_ready": first["error_code"] == "INDEX_NOT_READY",
            "no_chat_sent": HUB.count("chat") == 0,
            "ledger_timeout_recorded": "timeout" in ledger["result_statuses"],
            "ledger_settled": ledger["unsettled"] == [],
            "external_zero": guard.summary()["external_attempts"] == 0,
        }
        return {
            "scenario": "zero-retry-timeout",
            "mode": "mock",
            "isolated": {key: rel(value) for key, value in paths.items()},
            "build": build,
            "degraded_error": degraded_error,
            "qa_status": app.state.qa.status(),
            "answer": first,
            "transport": transport,
            "post_counters": post_counters,
            "ledger": ledger,
            "socket_guard": guard.summary(),
            "checks": checks,
            "pass": all(checks.values()),
            "captured_at": now_iso(),
        }
    finally:
        restore_gate_paths()
        if app is not None:
            try:
                app.state.db.dispose()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------- 场景：拒绝路径


def scenario_refusals(guard: SocketGuard) -> dict:
    """每个案例独立隔离目录；断言拒绝发生在任何 transport/预留之前。"""
    cases: list[dict] = []

    def run_case(
        label: str,
        *,
        write_go: bool = True,
        max_requests: int | str = 13,
        stage_limit: str = "8.72",
        overrides: dict | None = None,
        services: tuple[str, ...] = ("rag", "chat"),
        ledger_sha256: str | None = None,
        max_request_cny: float = 2.11,
        bindings="__default__",
    ) -> None:
        paths = setup_isolated(
            f"refuse-{label}",
            stage_limit_cny=8.72,
            max_requests=13,
            max_request_cny=max_request_cny,
            write_go=write_go,
            services=services,
            ledger_sha256=ledger_sha256,
            bindings=bindings,
        )
        if not write_go:
            paths["go"].unlink(missing_ok=True)
        apply_env(max_requests=max_requests, stage_limit=stage_limit, overrides=overrides)
        patch_gate(paths)
        provider = MockProvider(mode="ok")
        HUB.reset(provider)
        error = None
        try:
            app = main_module.create_app(make_settings(paths))
            try:
                app.state.db.dispose()
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001 - 拒绝类型/文本就是证据
            error = {"type": type(exc).__name__, "text": str(exc)[:300]}
        finally:
            restore_gate_paths()
        ledger = read_ledger(paths)
        cases.append(
            {
                "case": label,
                "refused": error is not None,
                "error": error,
                "transport_calls": HUB.count(),
                "ledger_events": len(ledger["events"]),
                "reservations": ledger["reserved"],
                "isolated": {key: rel(value) for key, value in paths.items()},
            }
        )

    run_case("no-go", write_go=False)
    run_case("omit-max-requests", max_requests="")
    run_case("max-requests-junk", max_requests="1.5")
    run_case("max-requests-negative", max_requests="-3")
    run_case("zero-stage-limit", stage_limit="0")
    run_case("negative-stage-limit", stage_limit="-0.5")
    run_case("missing-price", overrides={"MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY": None})
    run_case("zero-price", overrides={"MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY": "0"})
    run_case("service-not-allowed", services=("rag",))
    run_case("ledger-hash-mismatch", ledger_sha256="0" * 64)
    run_case("request-bound-over-go", max_request_cny=0.01)
    run_case("retry-env-nonzero", overrides={"MKTKB_RAG_MAX_RETRIES": "2"})
    run_case("retry-env-junk", overrides={"MKTKB_RAG_MAX_RETRIES": "2.5"})
    run_case("retry-env-negative", overrides={"MKTKB_RAG_MAX_RETRIES": "-1"})
    run_case("reserve-profile-missing", overrides={"MKTKB_MODEL_RESERVE_PROFILE": None})
    run_case("context-ceiling-missing", overrides={"MKTKB_MODEL_CONTEXT_CEILING_TOKENS": None})
    run_case("context-ceiling-below-gate", overrides={"MKTKB_MODEL_CONTEXT_CEILING_TOKENS": "1000"})
    run_case("output-cap-not-800", overrides={"MKTKB_MODEL_MAX_OUTPUT_TOKENS": "900"})
    no_ceiling = mock_bindings()
    no_ceiling["chat"].pop("context_ceiling_tokens")
    run_case("go-chat-binding-missing-ceiling", bindings=no_ceiling)
    no_profile = mock_bindings()
    no_profile["chat"].pop("reserve_profile")
    run_case("go-chat-binding-missing-profile", bindings=no_profile)
    wrong_model = mock_bindings()
    wrong_model["chat"]["model"] = "deepseek-chat"
    run_case("go-chat-model-mismatch", bindings=wrong_model)

    checks = {
        "all_refused": all(case["refused"] for case in cases),
        "no_transport": all(case["transport_calls"] == 0 for case in cases),
        "no_reservation": all(case["reservations"] == 0 for case in cases),
        "ledger_only_history": all(case["ledger_events"] <= 1 for case in cases),
        "external_zero": guard.summary()["external_attempts"] == 0,
    }
    return {
        "scenario": "refusals",
        "mode": "mock",
        "cases": cases,
        "socket_guard": guard.summary(),
        "checks": checks,
        "pass": all(checks.values()),
        "captured_at": now_iso(),
    }


def scenario_over_cap(guard: SocketGuard) -> dict:
    """Payload 超过已声明输入上界：在首个预留/POST 之前拒绝，且账本无新增。"""
    import asyncio

    from mktkb.providers.types import ModelEvidence

    paths = setup_isolated("over-cap", stage_limit_cny=8.72, max_requests=13, max_request_cny=2.11)
    apply_env(max_requests=13, stage_limit="8.72")
    patch_gate(paths)
    provider = MockProvider(mode="ok")
    HUB.reset(provider)
    settings = make_settings(paths)
    gateway = None
    result: dict = {}
    try:
        gateway = real_build_gateway(settings, transport=HUB)
        request = CompletionInput(
            purpose="answer",
            question="D01 的位置在哪里",
            context=DialogueContext(),
            evidence=(ModelEvidence(source_id="chunk-over-cap", text="A" * 9000, fields={}),),
        )
        try:
            asyncio.run(gateway.complete(request, timeout_seconds=5.0))
            result["error"] = None
        except Exception as exc:  # noqa: BLE001 - 拒绝就是证据
            result["error"] = {"type": type(exc).__name__, "text": str(exc)[:300]}
        result["gateway_stats"] = gateway.stats()
    except Exception as exc:  # noqa: BLE001
        result["error"] = {"type": type(exc).__name__, "text": str(exc)[:300]}
    finally:
        if gateway is not None:
            try:
                asyncio.run(gateway.aclose())
            except Exception:  # noqa: BLE001
                pass
        restore_gate_paths()
    ledger = read_ledger(paths)
    stats = result.get("gateway_stats") or {}
    checks = {
        "refused": result.get("error") is not None,
        "no_transport": HUB.count() == 0,
        "no_reservation": ledger["reserved"] == 0,
        "ledger_untouched": len(ledger["events"]) == 1,
        "refused_counter": stats.get("counters", {}).get("refused") == 1,
        "send_attempts_zero": stats.get("counters", {}).get("send_attempts") == 0,
        "external_zero": guard.summary()["external_attempts"] == 0,
    }
    return {
        "scenario": "over-cap",
        "mode": "mock",
        "isolated": {key: rel(value) for key, value in paths.items()},
        "result": result,
        "ledger": ledger,
        "socket_guard": guard.summary(),
        "checks": checks,
        "pass": all(checks.values()),
        "captured_at": now_iso(),
    }


def scenario_ocr_excluded(guard: SocketGuard) -> dict:
    """OCR 排除：凭据仍在也不构造客户端；需 OCR 的输入在发送前失败为 OCR_NOT_CONFIGURED。"""
    paths = setup_isolated("ocr-excluded", stage_limit_cny=8.72, max_requests=13, max_request_cny=2.11)
    apply_env(max_requests=13, stage_limit="8.72")
    patch_gate(paths)
    provider = MockProvider(mode="ok")
    HUB.reset(provider)
    app = None
    without_flag = None
    try:
        settings = make_settings(paths)
        app = main_module.create_app(settings)
        client = TestClient(app, raise_server_exceptions=False)
        login(client, "admin", ADMIN_PASSWORD)
        csrf = current_csrf(client)
        ocr_from_env_disabled = _ocr_from_env()
        ocr_gateway = build_ocr_gateway(settings)
        # 反证：去掉开关后 worker 会构造客户端（只构造，不调用）。
        os.environ.pop("MKTKB_OCR_DISABLED", None)
        try:
            built = _ocr_from_env()
            without_flag = type(built).__name__ if built is not None else None
        finally:
            os.environ["MKTKB_OCR_DISABLED"] = "1"

        receipt = upload_document(client, csrf=csrf, path=b0.fixture_path("D09"), allow_same_name=False)
        record = receipt.json() if receipt.status_code == 202 else {}
        job = None
        if record:
            db = app.state.db.session()
            try:
                job = run_one_job(db, app.state.store)
            finally:
                db.close()
        checks = {
            "upload_accepted": receipt.status_code == 202,
            "ocr_flag_hides_env_gateway": ocr_from_env_disabled is None,
            "settings_gateway_none": ocr_gateway is None,
            "app_has_no_ocr": app.state.ocr_gateway is None,
            "flag_is_what_blocks": without_flag == "TencentOCRClient",
            "job_failed_on_ocr": job is not None and job.state == "failed",
            "job_error_ocr_not_configured": job is not None and job.error_code == "OCR_NOT_CONFIGURED",
            "no_provider_transport": HUB.count() == 0,
            "external_zero": guard.summary()["external_attempts"] == 0,
        }
        return {
            "scenario": "ocr-excluded",
            "mode": "mock",
            "isolated": {key: rel(value) for key, value in paths.items()},
            "worker": None
            if job is None
            else {
                "state": job.state,
                "error_code": job.error_code,
                "units_written": job.units_written,
            },
            "without_flag_would_build": without_flag,
            "transport": provider.summary(),
            "socket_guard": guard.summary(),
            "checks": checks,
            "pass": all(checks.values()),
            "captured_at": now_iso(),
        }
    finally:
        restore_gate_paths()
        if app is not None:
            try:
                app.state.db.dispose()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------- GO 绑定要求（运行器层）


def smoke_go_requirements(go_path: Path, *, require_formal: bool = False) -> list[dict]:
    """运行器对 GO 的额外要求（Mock 与 live 同一套校验）。

    S2-H-R3：不再要求 tokenizer/template 绑定（旧 artifact 与当前模型匹配未证）；
    改为必须绑定官方型号/host/thinking/输出/context 上限/token 预算 profile/价格。
    """
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: object) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail[:300] if isinstance(detail, str) else detail})

    exists = go_path.is_file()
    check("go_exists", exists, rel(go_path) if exists else "missing")
    if not exists:
        return checks
    try:
        go = read_json(go_path)
    except Exception as exc:  # noqa: BLE001
        check("go_parsable", False, type(exc).__name__)
        return checks
    check("go_parsable", True, "ok")
    scope = go.get("scope") if isinstance(go.get("scope"), dict) else {}
    bindings = scope.get("bindings")
    check(
        "scope_bindings_present",
        isinstance(bindings, dict) and bool(bindings),
        sorted(bindings) if isinstance(bindings, dict) else None,
    )
    bindings = bindings if isinstance(bindings, dict) else {}
    rag = bindings.get("rag") if isinstance(bindings.get("rag"), dict) else {}
    chat = bindings.get("chat") if isinstance(bindings.get("chat"), dict) else {}
    check(
        "rag_binding",
        rag.get("base_url_host") == DASHSCOPE_HOST
        and rag.get("embedding_model") == "text-embedding-v4"
        and int(rag.get("embedding_dimensions") or 0) == 1024
        and rag.get("rerank_model") == "gte-rerank-v2"
        and rag.get("region") == "beijing",
        rag or None,
    )
    check("chat_binding_host", chat.get("base_url_host") == PRODUCT_HOST, chat.get("base_url_host"))
    check("chat_binding_model", chat.get("model") == PRODUCT_MODEL, chat.get("model"))
    check("chat_binding_thinking", chat.get("thinking") == "disabled", chat.get("thinking"))
    check(
        "chat_binding_max_output",
        chat.get("max_output_tokens") == CHAT_MAX_OUTPUT_TOKENS,
        chat.get("max_output_tokens"),
    )
    check(
        "chat_binding_max_input_gate",
        chat.get("max_input_tokens") == CHAT_MAX_INPUT_TOKENS,
        chat.get("max_input_tokens"),
    )
    check(
        "chat_binding_reserve_profile",
        chat.get("reserve_profile") == RESERVE_PROFILE,
        chat.get("reserve_profile"),
    )
    check(
        "chat_binding_context_ceiling",
        chat.get("context_ceiling_tokens") == CONTEXT_CEILING_TOKENS,
        chat.get("context_ceiling_tokens"),
    )
    check(
        "chat_binding_input_price",
        chat.get("input_price_per_million_cny") == CHAT_INPUT_PRICE,
        chat.get("input_price_per_million_cny"),
    )
    check(
        "chat_binding_output_price",
        chat.get("output_price_per_million_cny") == CHAT_OUTPUT_PRICE,
        chat.get("output_price_per_million_cny"),
    )
    if chat.get("tokenizer_sha256"):
        # 可选、仅防替换；不是可发送证明，也不参与预留。
        check(
            "chat_binding_tokenizer_sha_if_present",
            str(chat.get("tokenizer_sha256")).lower() == TOKENIZER_SHA,
            chat.get("tokenizer_sha256"),
        )
    if require_formal:
        check("go_stage_is_product_stage", go.get("stage") == "S2-DEV", go.get("stage"))
        marker = f"{go.get('authorization') or ''} {go.get('issued_by') or ''}".lower()
        check("go_not_mock_marker", "mock" not in marker, marker[:120])
        check(
            "go_services_include_rag_chat",
            set(scope.get("services") or ()) >= {"rag", "chat"},
            scope.get("services"),
        )
    return checks


def scenario_go_requirements(guard: SocketGuard) -> dict:
    """运行器层 GO 要求：缺绑定/缺 profile/型号不符必须被拒；完整绑定才通过。"""
    cases: list[dict] = []
    HUB.reset(MockProvider(mode="ok"))

    def run_case(label: str, bindings) -> None:
        paths = setup_isolated(f"go-req-{label}", bindings=bindings)
        checks = smoke_go_requirements(paths["go"])
        cases.append(
            {
                "case": label,
                "all_ok": all(item["ok"] for item in checks),
                "failed_checks": [item["check"] for item in checks if not item["ok"]],
                "go": rel(paths["go"]),
                "transport_calls": HUB.count(),
            }
        )

    run_case("complete", mock_bindings())
    run_case("missing-bindings", None)
    partial = mock_bindings()
    partial["chat"].pop("context_ceiling_tokens")
    run_case("missing-ceiling", partial)
    no_profile = mock_bindings()
    no_profile["chat"].pop("reserve_profile")
    run_case("missing-reserve-profile", no_profile)
    no_price = mock_bindings()
    no_price["chat"].pop("output_price_per_million_cny")
    run_case("missing-price", no_price)
    wrong_model = mock_bindings()
    wrong_model["chat"]["model"] = "deepseek-chat"
    run_case("wrong-model", wrong_model)

    by_case = {case["case"]: case for case in cases}
    checks = {
        "complete_passes": by_case["complete"]["all_ok"] is True,
        "missing_bindings_rejected": by_case["missing-bindings"]["all_ok"] is False,
        "missing_ceiling_rejected": by_case["missing-ceiling"]["all_ok"] is False,
        "missing_profile_rejected": by_case["missing-reserve-profile"]["all_ok"] is False,
        "missing_price_rejected": by_case["missing-price"]["all_ok"] is False,
        "wrong_model_rejected": by_case["wrong-model"]["all_ok"] is False,
        "no_transport": all(case["transport_calls"] == 0 for case in cases),
        "external_zero": guard.summary()["external_attempts"] == 0,
    }
    return {
        "scenario": "go-requirements",
        "mode": "mock",
        "cases": cases,
        "socket_guard": guard.summary(),
        "checks": checks,
        "pass": all(checks.values()),
        "captured_at": now_iso(),
        "missing_bindings_go": rel(setup_isolated("go-req-missing")["go"]),
    }


# ---------------------------------------------------------------- live：同一执行函数 + 同一校验


def _env_text(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def live_preflight(
    *,
    go_path: Path,
    out_dir: Path | None,
    require_formal: bool,
    data_dir: Path | None = None,
) -> dict:
    """Mock 与 live 共用的 run-live 校验；任一不满足都在首个预留/POST 之前拒绝。"""
    from urllib.parse import urlsplit

    checks: list[dict] = []

    def check(name: str, ok: bool, detail: object) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail[:300] if isinstance(detail, str) else detail})

    stage_limit = _env_text("MKTKB_RAG_STAGE_LIMIT_CNY")
    max_requests = _env_text("MKTKB_RAG_MAX_REQUESTS")
    try:
        stage_limit_value = float(stage_limit)
    except ValueError:
        stage_limit_value = None
    check(
        "stage_limit_covers_worst_13_requests",
        stage_limit_value is not None and stage_limit_value >= WORST_13_REQUESTS_CNY,
        {"value": stage_limit, "required": round(WORST_13_REQUESTS_CNY, 6)},
    )
    check(
        "max_requests_at_least_13",
        max_requests.isdigit() and int(max_requests) >= 13,
        max_requests or "<unset>",
    )
    check(
        "input_price_official",
        _env_text("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY") == str(CHAT_INPUT_PRICE),
        _env_text("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY") or "<unset>",
    )
    check(
        "output_price_official",
        _env_text("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY") == str(CHAT_OUTPUT_PRICE),
        _env_text("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY") or "<unset>",
    )
    check(
        "context_ceiling_1048576",
        _env_text("MKTKB_MODEL_CONTEXT_CEILING_TOKENS") == str(CONTEXT_CEILING_TOKENS),
        _env_text("MKTKB_MODEL_CONTEXT_CEILING_TOKENS") or "<unset>",
    )
    check(
        "reserve_profile_model_context_ceiling",
        _env_text("MKTKB_MODEL_RESERVE_PROFILE") == RESERVE_PROFILE,
        _env_text("MKTKB_MODEL_RESERVE_PROFILE") or "<unset>",
    )
    check(
        "max_output_tokens_800",
        _env_text("MKTKB_MODEL_MAX_OUTPUT_TOKENS") == str(CHAT_MAX_OUTPUT_TOKENS),
        _env_text("MKTKB_MODEL_MAX_OUTPUT_TOKENS") or "<unset>",
    )
    check(
        "max_input_gate_6144",
        _env_text("MKTKB_MODEL_MAX_INPUT_TOKENS") == str(CHAT_MAX_INPUT_TOKENS),
        _env_text("MKTKB_MODEL_MAX_INPUT_TOKENS") or "<unset>",
    )
    chat_host = (urlsplit(_env_text("MKTKB_MODEL_BASE_URL")).hostname or "") if _env_text("MKTKB_MODEL_BASE_URL") else ""
    embed_host = (urlsplit(_env_text("DASHSCOPE_BASE_URL")).hostname or "") if _env_text("DASHSCOPE_BASE_URL") else ""
    check("chat_host_is_official_deepseek", chat_host == PRODUCT_HOST, chat_host or "<unset>")
    check("chat_model_is_deepseek_flash", _env_text("MKTKB_MODEL_NAME") == PRODUCT_MODEL, _env_text("MKTKB_MODEL_NAME") or "<unset>")
    check("embedding_host_is_beijing_dashscope", embed_host == DASHSCOPE_HOST, embed_host or "<unset>")
    check("chat_thinking_disabled_declared", _env_text("MKTKB_MODEL_THINKING") in ("", "disabled"), _env_text("MKTKB_MODEL_THINKING") or "disabled(default)")
    check(
        "zero_retry_env",
        _env_text("MKTKB_RAG_MAX_RETRIES") in ("", "0"),
        _env_text("MKTKB_RAG_MAX_RETRIES") or "0(default)",
    )
    ocr_disabled = _env_text("MKTKB_OCR_DISABLED").lower() in ("1", "true", "yes", "on")
    ocr_creds = bool(_env_text("MKTKB_OCR_SECRET_ID") or _env_text("MKTKB_OCR_SECRET_KEY"))
    check("ocr_excluded", ocr_disabled, {"MKTKB_OCR_DISABLED": _env_text("MKTKB_OCR_DISABLED"), "ocr_creds_present": ocr_creds})
    check("output_dir_explicit_and_new", out_dir is not None and not out_dir.exists(), None if out_dir is None else rel(out_dir))

    for item in smoke_go_requirements(go_path, require_formal=require_formal):
        check(f"go:{item['check']}", item["ok"], item["detail"])

    product_refusal = None
    if out_dir is not None and data_dir is not None:
        try:
            from mktkb.qa import resolve_rag_config

            resolve_rag_config(
                data_dir=data_dir,
                provider_mode="live",
                page_size=10,
                top_k=8,
                business_date=None,
            )
            product_refusal = {"refused": False, "text": "product accepted live config"}
        except Exception as exc:  # noqa: BLE001 - 拒绝类型/文本就是证据
            product_refusal = {"refused": True, "type": type(exc).__name__, "text": str(exc)[:300]}

    preconditions_ok = all(item["ok"] for item in checks)
    return {
        "mode": "run-live-preflight",
        "formal": require_formal,
        "preconditions": checks,
        "preconditions_all_ok": preconditions_ok,
        "failed": [item["check"] for item in checks if not item["ok"]],
        "go_path": rel(go_path),
        "out_dir": None if out_dir is None else rel(out_dir),
        "product_refusal": product_refusal,
        "product_accepted": bool(product_refusal and not product_refusal.get("refused")),
        "real_paths": real_path_hashes(),
        "captured_at": now_iso(),
    }


def execute_two_questions(
    *,
    paths: dict,
    out_dir: Path,
    receipt_path: Path,
    mode: str,
    guard: SocketGuard | None,
) -> dict:
    """真实执行路径：create_app → D01 导入发布 → Q01/Q03 HTTP 问答 → 生产网关。

    Mock 只把它 ``paths`` 指向隔离 GO/账本、``out_dir`` 指向本轮隔离目录，并预装
    ``MockTransport``；函数本身不再分支，也不额外豁免任何校验。

    S2-H-R3：每题 POST 前记录 current_question_id/阶段；中断时 finally receipt 保留
    未完成题号、原始异常事件（portal 改写前）与传播后异常，二者不混称。
    """
    receipt: dict = {
        "mode": mode,
        "questions": ["Q01", "Q03"],
        "started_at": now_iso(),
        "action": "create_app -> upload D01 -> worker publish -> HTTP Q01/Q03 -> production gateway",
        "outcome": "running",
        "current_question_id": None,
        "current_phase": "init",
        "inflight": None,
        "stopped_after": None,
        "interruption": None,
        "answers": [],
        "question_states": [
            {"question_id": "Q01", "state": "not_started"},
            {"question_id": "Q03", "state": "not_started"},
        ],
        "post_attempts": None,
        "mock_transport_received": None,
        "real_service_received": "unobservable-from-local",
        "build": None,
        "error": None,
        "ledger": None,
        "socket_guard": None,
    }
    app = None
    providers_module.reset_post_counters()
    try:
        app = main_module.create_app(make_settings({**paths, "root": out_dir}))
        client = TestClient(app, raise_server_exceptions=False)
        login(client, "admin", ADMIN_PASSWORD)
        csrf = current_csrf(client)
        receipt["build"] = upload_and_publish(client, csrf=csrf, file_id="D01")
        for question_id in ("Q01", "Q03"):
            state = next(item for item in receipt["question_states"] if item["question_id"] == question_id)
            state["state"] = "in_flight"
            receipt["current_question_id"] = question_id
            receipt["current_phase"] = "before_question_post"
            receipt["inflight"] = {
                "question_id": question_id,
                "phase": "before_question_post",
                "started_at": now_iso(),
            }
            interrupt_trace_module.reset()
            question_tokens = interrupt_trace_module.set_question_context(
                question_id=question_id, phase="before_question_post"
            )

            def mark_question_post(question_id: str = question_id) -> None:
                receipt["current_phase"] = "question_post"
                if receipt.get("inflight"):
                    receipt["inflight"]["phase"] = "question_post"
                interrupt_trace_module.set_phase("question_post")

            answer = ask(
                client,
                csrf=csrf,
                question_id=question_id,
                on_before_post=mark_question_post,
            )
            receipt["answers"].append(answer)
            state["state"] = "answered"
            receipt["last_completed_question_id"] = question_id
            interrupt_trace_module.clear_question_context(question_tokens)
            receipt["current_question_id"] = None
            receipt["current_phase"] = "idle"
            receipt["inflight"] = None
            if answer["kind"] != "answer":
                state["state"] = "stopped"
                receipt["outcome"] = "stopped"
                receipt["stopped_after"] = question_id
                receipt["stop_reason"] = {"http_status": answer["http_status"], "error_code": answer["error_code"]}
                break
        else:
            receipt["outcome"] = "completed"
        gateway = getattr(app.state, "model_gateway", None)
        receipt["gateway_stats"] = gateway.stats() if hasattr(gateway, "stats") else None
        receipt["qa_config"] = {
            "max_retries": app.state.qa.config.max_retries,
            "require_zero_retries": app.state.qa.config.require_zero_retries,
            "reserve_profile": app.state.qa.config.chat_reserve_profile,
            "context_ceiling_tokens": app.state.qa.config.chat_context_ceiling_tokens,
            "max_output_tokens": app.state.qa.config.max_output_tokens,
        }
    except BaseException as exc:  # noqa: BLE001 - 中断/失败也必须留下已发生占用
        trace = interrupt_trace_module.last_event()
        current_question = receipt.get("current_question_id")
        for state in receipt.get("question_states") or []:
            if state.get("question_id") == current_question and state.get("state") == "in_flight":
                state["state"] = "interrupted"
        receipt["outcome"] = "interrupted_or_failed"
        receipt["current_phase"] = "exception"
        receipt["stopped_after"] = receipt.get("stopped_after") or current_question
        receipt["interruption"] = {
            "question_id": current_question,
            "phase": (receipt.get("inflight") or {}).get("phase"),
            "original_exception": trace,
            "original_exception_type": trace["type"] if trace else "unknown",
            "propagated_exception_type": type(exc).__name__,
            "propagated_exception_text": str(exc)[:300],
            "original_recovered": trace is not None,
            "portal_rewritten": bool(trace) and trace.get("type") != type(exc).__name__,
            "reservation_id": trace.get("reservation_id") if trace else None,
            "request_id": trace.get("request_id") if trace else None,
        }
        receipt["error"] = {"type": type(exc).__name__, "text": str(exc)[:300]}
        raise
    finally:
        receipt["finished_at"] = now_iso()
        try:
            receipt["post_attempts"] = providers_module.post_counters()
        except Exception:  # noqa: BLE001
            receipt["post_attempts"] = None
        receipt["mock_transport_received"] = HUB.count() if mode == "mock" else 0
        receipt["socket_guard"] = guard.summary() if guard is not None else {"installed": False, "note": "真实发送阶段不装 socket guard"}
        try:
            receipt["ledger"] = read_ledger(
                paths,
                max_requests=int(_env_text("MKTKB_RAG_MAX_REQUESTS") or 13),
                stage_limit=float(_env_text("MKTKB_RAG_STAGE_LIMIT_CNY") or "8.72"),
                stage=_env_text("MKTKB_LIVE_STAGE") or STAGE,
            )
        except Exception as exc:  # noqa: BLE001 - 账本读失败也要落盘
            receipt["ledger_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        if app is not None:
            try:
                app.state.db.dispose()
            except Exception:  # noqa: BLE001
                pass
        dump_json(receipt_path, receipt)
        HUB.provider = None
    return receipt


def run_live_like(
    *,
    paths: dict,
    out_dir: Path,
    mode: str,
    require_formal: bool,
    guard: SocketGuard | None,
    receipt_path: Path,
    before_execute=None,
) -> dict:
    preflight = live_preflight(
        go_path=Path(paths["go"]),
        out_dir=out_dir,
        require_formal=require_formal,
        data_dir=out_dir / "app",
    )
    if not preflight["preconditions_all_ok"]:
        return {
            "mode": mode,
            "decision": "refused-before-first-reservation",
            "sent_any_request": False,
            "preflight": preflight,
            "transport_receipt_observable": False,
            "captured_at": now_iso(),
        }
    if before_execute is not None:
        before_execute()
    out_dir.mkdir(parents=True, exist_ok=False)  # 已存在则拒绝；不清旧目录
    (out_dir / "app").mkdir()
    (out_dir / "logs").mkdir()
    receipt = execute_two_questions(
        paths=paths,
        out_dir=out_dir,
        receipt_path=receipt_path,
        mode=mode,
        guard=guard,
    )
    receipt["preflight"] = preflight
    return receipt


# ---------------------------------------------------------------- live 分支（Mock 传输，同一校验）


def scenario_live_branch(guard: SocketGuard) -> dict:
    """同一 run_live_like/preflight/执行函数：Mock 传输必须真正收到两题请求。

    同时逐项验证 live 前提拒绝路径（缺 profile/错型号/额度不足/缺 bindings/
    输出目录已存在/正式 GO 检查）都在首个预留/POST 前拒绝。
    """
    paths = setup_isolated("live-branch", stage_limit_cny=8.72, max_requests=13, max_request_cny=2.11)
    apply_env(max_requests=13, stage_limit="8.72")
    patch_gate(paths)
    provider = MockProvider(meter=_new_meter(), mode="ok")
    HUB.reset(provider)
    out_dir = paths["root"] / "exec-out"
    receipt_path = DATA / "mock-live-branch-receipt.json"
    result = run_live_like(
        paths=paths,
        out_dir=out_dir,
        mode="mock",
        require_formal=False,
        guard=guard,
        receipt_path=receipt_path,
    )
    receipt = read_json(receipt_path) if receipt_path.is_file() else {}
    ledger = receipt.get("ledger") or {}
    transport = provider.summary()
    positives = {
        "preflight_all_ok": (result.get("preflight") or {}).get("preconditions_all_ok") is True,
        "product_accepted": (result.get("preflight") or {}).get("product_accepted") is True,
        "not_early_return": result.get("decision") != "refused-before-first-reservation",
        "two_questions_answered": len(receipt.get("answers") or []) == 2
        and all(item.get("kind") == "answer" for item in receipt.get("answers") or []),
        "mock_transport_received_11": receipt.get("mock_transport_received") == 11,
        "chat_transport_received_2": transport["by_kind"].get("chat") == 2,
        "product_gateway_chat_2": ((receipt.get("gateway_stats") or {}).get("counters") or {}).get("send_attempts") == 2,
        "rag_post_attempts_9": sum(((receipt.get("post_attempts") or {}).get("attempts") or {}).values()) == 9,
        "ledger_reserved_11_settled": ledger.get("reserved") == 11 and ledger.get("results") == 11,
        "ledger_unsettled_zero": ledger.get("unsettled") == [],
        "chat_reserve_is_ceiling": abs(
            float(ledger.get("reserve_cny_by_kind", {}).get("chat", 0.0)) - 2 * CHAT_RESERVE_PER_REQUEST_CNY
        ) < 1e-9,
        "real_service_unobservable_marked": receipt.get("real_service_received") == "unobservable-from-local",
        "exec_output_new": out_dir.is_dir(),
        "external_zero": guard.summary()["external_attempts"] == 0,
    }

    negatives: list[dict] = []

    def try_refusal(
        label: str,
        *,
        overrides: dict | None = None,
        bindings="__default__",
        stage: str = "8.72",
        out_exists: bool = False,
        formal: bool = False,
    ) -> None:
        case_paths = setup_isolated(
            f"live-branch-{label}",
            stage_limit_cny=8.72,
            max_requests=13,
            max_request_cny=2.11,
            bindings=bindings,
        )
        apply_env(max_requests=13, stage_limit=stage, overrides=overrides or {})
        patch_gate(case_paths)
        case_out = case_paths["root"] / "exec-out"
        if out_exists:
            case_out.mkdir()
        before = HUB.count()
        pre = live_preflight(
            go_path=case_paths["go"],
            out_dir=case_out,
            require_formal=formal,
            data_dir=case_out / "app",
        )
        negatives.append(
            {
                "case": label,
                "refused_before_run": not pre["preconditions_all_ok"],
                "failed": pre["failed"],
                "transport_delta": HUB.count() - before,
                "out_created_by_failed_preflight": case_out.exists() and not out_exists,
                "product_refused": bool((pre.get("product_refusal") or {}).get("refused")),
                "isolated": {key: rel(value) for key, value in case_paths.items()},
            }
        )

    try:
        try_refusal("missing-reserve-profile", overrides={"MKTKB_MODEL_RESERVE_PROFILE": None})
        try_refusal("wrong-model", overrides={"MKTKB_MODEL_NAME": "deepseek-chat"})
        try_refusal("stage-too-small", stage="5")
        try_refusal("go-missing-bindings", bindings=None)
        try_refusal("output-dir-exists", out_exists=True)
        try_refusal("formal-requires-real-go", formal=True)
    finally:
        apply_env(max_requests=13, stage_limit="8.72")
        patch_gate(paths)
        restore_gate_paths()

    checks = {
        **positives,
        "all_negatives_refused": all(case["refused_before_run"] for case in negatives),
        "negatives_no_transport": all(case["transport_delta"] == 0 for case in negatives),
        "negatives_no_out_dir": all(not case["out_created_by_failed_preflight"] for case in negatives),
        "negatives_product_refused_when_config_invalid": all(
            case["product_refused"]
            for case in negatives
            if case["case"] in ("missing-reserve-profile", "wrong-model", "go-missing-bindings")
        ),
    }
    return {
        "scenario": "live-branch",
        "mode": "mock",
        "positive": {"result": result, "receipt": receipt, "transport_by_kind": transport["by_kind"]},
        "negatives": negatives,
        "socket_guard": guard.summary(),
        "checks": checks,
        "pass": all(checks.values()),
        "captured_at": now_iso(),
    }


# ---------------------------------------------------------------- 中断：预留保留、摘要落盘


def scenario_interrupt(guard: SocketGuard) -> dict:
    """KeyboardInterrupt 中断必须留下已发生的预留与 unsettled，摘要仍落盘。"""
    import asyncio

    from mktkb.providers.types import ModelEvidence

    paths = setup_isolated("interrupt", stage_limit_cny=8.72, max_requests=13, max_request_cny=2.11)
    apply_env(max_requests=13, stage_limit="8.72")
    patch_gate(paths)
    provider = MockProvider(mode="interrupt")
    provider.fail_kind = "chat"
    HUB.reset(provider)
    gateway = None
    interrupted = False
    result: dict = {}
    try:
        gateway = real_build_gateway(make_settings(paths), transport=HUB)
        request = CompletionInput(
            purpose="answer",
            question="D01 的位置在哪里",
            context=DialogueContext(),
            evidence=(ModelEvidence(source_id="chunk-interrupt", text="位置：A 区", fields={"位置": "A 区"}),),
        )
        try:
            asyncio.run(gateway.complete(request, timeout_seconds=5.0))
        except KeyboardInterrupt:
            interrupted = True
        result["gateway_stats"] = gateway.stats()
    finally:
        ledger = read_ledger(paths)
        payload = {
            "scenario": "interrupt",
            "mode": "mock",
            "interrupted": interrupted,
            "result": result,
            "transport": provider.summary(),
            "ledger": ledger,
            "socket_guard": guard.summary(),
            "checks": {
                "interrupted": interrupted,
                "one_reservation_left": ledger["reserved"] == 1,
                "one_unsettled": len(ledger["unsettled"]) == 1,
                "send_attempt_recorded": (result.get("gateway_stats") or {}).get("counters", {}).get("send_attempts") == 1,
                "summary_has_reserved_cny": float(ledger["conservative_this_round_cny"]) >= CHAT_RESERVE_PER_REQUEST_CNY - 1e-9,
                "external_zero": guard.summary()["external_attempts"] == 0,
            },
            "captured_at": now_iso(),
        }
        payload["pass"] = all(payload["checks"].values())
        dump_json(DATA / "mock-interrupt.json", payload)
        restore_gate_paths()
        if gateway is not None:
            try:
                asyncio.run(gateway.aclose())
            except Exception:  # noqa: BLE001
                pass
    return payload


# ---------------------------------------------------------------- plan


def build_plan(meter: DeepSeekPromptMeter) -> dict:
    probe_path = HR1 / "data" / "token-meter-probe.json"  # 旧诊断，只读
    mock_path = DATA / "mock-smoke.json"
    probe = read_json(probe_path) if probe_path.is_file() else None
    mock = read_json(mock_path) if mock_path.is_file() else None

    transport_counts = None
    observed_chat_reserve = None
    if mock:
        transport_counts = mock.get("transport", {}).get("by_kind")
        observed_chat_reserve = (mock.get("ledger") or {}).get("reserve_cny_by_kind", {}).get("chat")

    chat_per_request_cny = CHAT_RESERVE_PER_REQUEST_CNY
    structural_requests = {"embedding": 5, "rerank": 4, "chat": 4, "total": 13}
    two_question_cny = (
        structural_requests["embedding"] * EMBEDDING_BOUND_CNY
        + structural_requests["rerank"] * RERANK_BOUND_CNY
        + 2 * chat_per_request_cny
    )
    worst_cny = (
        structural_requests["embedding"] * EMBEDDING_BOUND_CNY
        + structural_requests["rerank"] * RERANK_BOUND_CNY
        + 4 * chat_per_request_cny
    )

    plan = {
        "version": "S2-H-R3-1",
        "generated_at": now_iso(),
        "mode": "plan-only; no provider call; Mock evidence only; no formal GO",
        "task": "docs/evidence/LOCAL-R1-20261101/PM/S2-H-R3-targeted-task.md",
        "scope": {
            "documents": ["D01"],
            "questions": ["Q01", "Q03"],
            "ocr": "excluded (MKTKB_OCR_DISABLED=1; gateway not constructed; OCR input refused before send)",
            "s2_go_signed": False,
            "real_provider_calls": 0,
            "real_spend_cny": 0,
        },
        "product_chat": {
            "provider": "DeepSeek official api.deepseek.com",
            "model": PRODUCT_MODEL,
            "thinking": "disabled (explicit thinking.type=disabled)",
            "stream": False,
            "temperature": 0,
            "max_tokens": CHAT_MAX_OUTPUT_TOKENS,
            "input_price_per_million_cny": CHAT_INPUT_PRICE,
            "output_price_per_million_cny": CHAT_OUTPUT_PRICE,
            "price_source": "PM/S2-H-R3-targeted-task.md（沿用 R2 经理 2026-11-03 重读官方 pricing；保守人民币，无折扣）",
        },
        "token_bound": {
            "profile": RESERVE_PROFILE,
            "reserve_input_tokens": CONTEXT_CEILING_TOKENS,
            "reserve_output_tokens": CHAT_MAX_OUTPUT_TOKENS,
            "ceiling_note": "官方上下文 1M 对十进制/二进制有歧义；本方案取较大的 1,048,576 作为保守输入上限，独立于任何本地 tokenizer。",
            "payload_gate_input_tokens": CHAT_MAX_INPUT_TOKENS,
            "payload_gate_is": "refuse-above 闸门；D01 固定小 payload，实际请求远小于该值",
            "old_tokenizer_artifact": {
                "path": "S2-DEV/H/vendor/tokenizer_deepseek_v4/tokenizer.json",
                "sha256": meter.tokenizer_sha256,
                "template_sha256": meter.template_sha256,
                "model_version_match_proven": False,
                "role_now": "只作离线诊断/防替换绑定（可选）；不得用其小额计量放行真实请求，也不参与本轮预留",
            },
            "unproven": "旧 artifact（2026-08-28，model_max_length=16384）与 DeepSeek-V4.1-Flash-1017 逐版本一致仍未证明；本轮已不再把它当证明。",
        },
        "request_bounds": {
            "embedding": {
                "upper_tokens_per_request": 81920,
                "cny_per_request": round(EMBEDDING_BOUND_CNY, 10),
                "basis": "rag/providers.py：单请求最多 10 条 × 8192 token；北京 text-embedding-v4 0.5 元/百万",
            },
            "rerank": {
                "upper_tokens_per_request": 30000,
                "cny_per_request": round(RERANK_BOUND_CNY, 10),
                "basis": "rag/config.py rerank_max_request_tokens=30000；北京 gte-rerank-v2 0.8 元/百万",
            },
            "chat": {
                "reserve_input_tokens": CONTEXT_CEILING_TOKENS,
                "reserve_output_tokens": CHAT_MAX_OUTPUT_TOKENS,
                "cny_per_request": round(chat_per_request_cny, 10),
                "formula": "1,048,576 × 2/1e6 + 800 × 8/1e6",
                "basis": "官方 context 上限全额输入 + 固定 800 输出；不依赖本地 tokenizer",
            },
        },
        "request_counts": {
            "observed_mock": transport_counts,
            "structural_upper": structural_requests,
            "breakdown": "1 次发布重索引 embedding + 2 问 ×(2 次 query embedding + 2 次 rerank + 1 次 answer chat)（结构上界把 chat 计为 2/问）",
            "observed_mock_chat_reserve_cny": None if observed_chat_reserve is None else round(float(observed_chat_reserve), 10),
        },
        "cny": {
            "chat_two_questions_actual_shape": round(two_question_cny, 10),
            "chat_worst_4_requests": round(worst_cny, 10),
            "two_chat_vs_four_chat": {
                "2_chat": round(two_question_cny, 10),
                "4_chat": round(worst_cny, 10),
                "difference": round(worst_cny - two_question_cny, 10),
            },
            "remaining_project_conservative_cny_before": 9.97,
            "remaining_after_worst_case_cny": round(9.97 - worst_cny, 10),
            "ledger_reset": False,
            "historical_reserve_released": False,
            "not_a_spend_authorization": True,
            "note": "8.715008 元只是保守审查方案的上界，不是实际消费、不签 GO；不能在余 9.97 元内承诺 40 题全量矩阵。",
        },
        "impact_on_later_real_matrix": {
            "if_worst_case_adopted": "本阶段最坏占用 8.715008 元后，剩余保守余额约 1.254992 元；单次 chat 保守 2.103552 元，后续 40 题矩阵不可能在剩余额度内完成。",
            "if_two_question_real_shape": "两问约 4.507904 元，剩余约 5.462096 元；仍不足以覆盖 40 题（每题至少 1 次 chat × 2.103552 元）。",
            "decision_needed": "经理需决定采用该保守方案、限制问题数，或等待更精确的官方逐版本/上限依据；本窗不签 GO。",
        },
        "stage": {
            "stage_limit_cny": 8.72,
            "max_requests": 13,
            "max_request_cny": 2.11,
            "stop_condition": "首个供应商失败/超时/关口拒绝即终止；不重试；不继续下一题",
        },
        "commands": {
            "plan": ".venv/Scripts/python.exe -B tools/s2h_mock_smoke.py --plan",
            "mock": "T09_EVIDENCE_ROOT=docs/evidence/LOCAL-R1-20261101/S2-DEV/H-R3/data/t09-output .venv/Scripts/python.exe -B tools/s2h_mock_smoke.py --mock --all",
            "live_future": "MKTKB_LIVE_STAGE=S2-DEV MKTKB_RAG_STAGE_LIMIT_CNY=8.72 MKTKB_RAG_MAX_REQUESTS=13 MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY=2 MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY=8 MKTKB_MODEL_MAX_INPUT_TOKENS=6144 MKTKB_MODEL_MAX_OUTPUT_TOKENS=800 MKTKB_MODEL_CONTEXT_CEILING_TOKENS=1048576 MKTKB_MODEL_RESERVE_PROFILE=model_context_ceiling MKTKB_OCR_DISABLED=1 .venv/Scripts/python.exe -B tools/s2h_mock_smoke.py --live --out docs/evidence/LOCAL-R1-20261101/S2-DEV/H-R3/data/live-run-<new>（密钥/正式 GO 由经理注入；--out 必须全新）",
        },
        "evidence": {
            "protection_start": "data/protection-start.json",
            "mock_smoke": "data/mock-smoke.json",
            "mock_live_branch": "data/mock-live-branch.json",
            "mock_live_branch_receipt": "data/mock-live-branch-receipt.json",
            "mock_interrupt": "data/mock-interrupt.json",
            "mock_zero_retry_429": "data/mock-zero-retry-429.json",
            "mock_zero_retry_timeout": "data/mock-zero-retry-timeout.json",
            "mock_refusals": "data/mock-refusals.json",
            "mock_go_requirements": "data/mock-go-requirements.json",
            "mock_over_cap": "data/mock-over-cap.json",
            "mock_ocr_excluded": "data/mock-ocr-excluded.json",
        },
        "not_done": [
            "未签正式 GO；未写真实共享账本/预算；未调用真实模型/embedding/rerank/OCR；真实付费 0 元。",
            "旧 tokenizer/template 与 DeepSeek-V4.1-Flash-1017 逐版本一致仍未证明；已在预留中移除对其依赖。",
            "未做上下文容量压测；编码助手 1M 上下文与本产品请求无关。",
        ],
    }
    if probe is not None:
        plan["token_bound"]["old_tokenizer_artifact"]["probe_pass"] = probe.get("pass")
        plan["token_bound"]["old_tokenizer_artifact"]["probe_note"] = "仅证明该 artifact 内部字节上界性质，不证明模型适用性"
    return plan


# ---------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description="S2-H-R3 smoke 入口（默认 plan；Mock 优先；live 有真实执行分支）")
    parser.add_argument("--plan", action="store_true", help="只出计划（默认）")
    parser.add_argument("--mock", action="store_true", help="跑 Mock 全套")
    parser.add_argument("--live", action="store_true", help="校验前提；全部通过后真实执行并发送")
    parser.add_argument("--out", default=None, help="live 的真实输出目录（必须显式、全新、在 H-R3/data 下）")
    parser.add_argument("--all", action="store_true", help="Mock 全场景（隐含 --mock，且不限定 --only）")
    parser.add_argument(
        "--only",
        choices=["smoke", "429", "timeout", "go-requirements", "refusals", "over-cap", "ocr", "live-branch", "interrupt"],
        default=None,
    )
    args = parser.parse_args()
    if args.all:
        args.mock = True
    if not any((args.plan, args.mock, args.live)):
        args.plan = True
    DATA.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    real_start = real_path_hashes()
    results: dict[str, dict] = {}
    started = now_iso()
    guard = SocketGuard().install()
    code = 0

    def run_and_dump(name: str, filename: str, fn) -> None:
        print(f"[scenario] {name} ...", flush=True)
        try:
            payload = fn()
        except BaseException as exc:  # noqa: BLE001 - 失败也落盘，不抹掉已发生的占用
            payload = {
                "scenario": name,
                "mode": "mock",
                "pass": False,
                "error": {"type": type(exc).__name__, "text": str(exc)[:400]},
                "captured_at": now_iso(),
            }
            if isinstance(exc, KeyboardInterrupt):
                results[name] = payload
                dump_json(DATA / filename, payload)
                raise
        results[name] = payload
        dump_json(DATA / filename, payload)
        print(f"  pass={payload.get('pass')}", flush=True)

    try:
        meter_ok, meter_detail = tokenizer_available()
        if args.plan:
            if not meter_ok:
                raise _fail(f"plan 需要官方 tokenizer artifact：{meter_detail}")
            meter = _new_meter()
            plan = build_plan(meter)
            dump_json(DATA / "smoke-plan.json", plan)
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        if args.mock:
            if not meter_ok:
                raise _fail(f"Mock 无法离线计量：{meter_detail}")
            meter = _new_meter()
            install_transport(HUB)
            try:
                if args.only in (None, "smoke"):
                    run_and_dump("smoke", "mock-smoke.json", lambda: scenario_smoke(guard, meter))
                if args.only in (None, "429"):
                    run_and_dump("zero-retry-429", "mock-zero-retry-429.json", lambda: scenario_zero_retry_429(guard, meter))
                if args.only in (None, "timeout"):
                    run_and_dump(
                        "zero-retry-timeout",
                        "mock-zero-retry-timeout.json",
                        lambda: scenario_zero_retry_timeout(guard, meter),
                    )
                if args.only in (None, "go-requirements"):
                    run_and_dump(
                        "go-requirements", "mock-go-requirements.json", lambda: scenario_go_requirements(guard)
                    )
                if args.only in (None, "refusals"):
                    run_and_dump("refusals", "mock-refusals.json", lambda: scenario_refusals(guard))
                if args.only in (None, "over-cap"):
                    run_and_dump("over-cap", "mock-over-cap.json", lambda: scenario_over_cap(guard))
                if args.only in (None, "ocr"):
                    run_and_dump("ocr-excluded", "mock-ocr-excluded.json", lambda: scenario_ocr_excluded(guard))
                if args.only in (None, "live-branch"):
                    run_and_dump("live-branch", "mock-live-branch.json", lambda: scenario_live_branch(guard))
                if args.only in (None, "interrupt"):
                    run_and_dump("interrupt", "mock-interrupt.json", lambda: scenario_interrupt(guard))
            finally:
                uninstall_transport()
                restore_gate_paths()
        if args.live:
            out_raw = (args.out or "").strip()
            out_dir = None
            if out_raw:
                candidate = Path(out_raw)
                if not candidate.is_absolute():
                    candidate = ROOT / candidate
                out_dir = candidate.resolve()
                if DATA.resolve() not in out_dir.parents:
                    raise _fail(f"live --out={out_dir} 必须在 {rel(DATA)} 之下（保护旧证据）")
            live_paths = {"go": REAL_GO, "ledger": REAL_LEDGER, "budget": REAL_BUDGET, "root": out_dir}
            pre = live_preflight(go_path=REAL_GO, out_dir=out_dir, require_formal=True, data_dir=None)
            if out_raw and out_dir is not None and out_dir.exists():
                pre["preconditions_all_ok"] = False
                pre["failed"] = sorted(set(pre["failed"]) | {"output_dir_explicit_and_new"})
            if not pre["preconditions_all_ok"]:
                payload = {
                    "mode": "live",
                    "decision": "refused-before-first-reservation",
                    "sent_any_request": False,
                    "preflight": pre,
                    "real_paths": real_path_hashes(),
                    "transport_receipt_observable": False,
                    "checks": {
                        "no_request_sent": True,
                        "external_zero": guard.summary()["external_attempts"] == 0,
                        "no_formal_go": REAL_GO.is_file() is False,
                    },
                    "captured_at": now_iso(),
                }
                results["live"] = payload
                dump_json(DATA / "live-run.json", payload)
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                live_paths["root"] = out_dir
                results["live"] = run_live_like(
                    paths=live_paths,
                    out_dir=out_dir,
                    mode="live",
                    require_formal=True,
                    guard=None,
                    receipt_path=DATA / "live-run.json",
                    before_execute=guard.uninstall,
                )
                print(json.dumps(results["live"], ensure_ascii=False, indent=2))
    finally:
        real_end = real_path_hashes()
        summary = {
            "started_at": started,
            "finished_at": now_iso(),
            "evidence_root": str(T09_RESOLVED),
            "modes": {
                "plan": bool(args.plan),
                "mock": bool(args.mock),
                "live": bool(args.live),
            },
            "real_paths_start": real_start,
            "real_paths_end": real_end,
            "real_paths_unchanged": real_start == real_end,
            "socket_guard": guard.summary(),
            "scenarios": {
                name: {
                    "pass": payload.get("pass"),
                    "checks": payload.get("checks"),
                    "ledger_conservative_this_round_cny": (payload.get("ledger") or {}).get("conservative_this_round_cny"),
                    "ledger_unsettled": (payload.get("ledger") or {}).get("unsettled"),
                }
                for name, payload in results.items()
            },
            "ledger_conservative_this_round_cny_total": round(
                sum(
                    float((payload.get("ledger") or {}).get("conservative_this_round_cny") or 0.0)
                    for payload in results.values()
                ),
                10,
            ),
            "note": "isolated mock ledgers only; the shared ledger/budget is hash-verified and never written",
        }
        failed = [name for name, payload in results.items() if payload.get("pass") is False or (payload.get("checks") and not all(payload["checks"].values()))]
        live_executed = bool(results.get("live") and results["live"].get("answers"))
        summary["failed"] = failed
        summary["live_executed"] = live_executed
        summary["pass"] = not failed and (live_executed or real_start == real_end)
        dump_json(DATA / "mock-summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        code = 0 if summary["pass"] else 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
