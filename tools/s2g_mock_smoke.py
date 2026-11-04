"""S2-G Mock smoke：生产 HTTP 问答 + 生产预算/授权闸门 + 隔离 Mock GO/账本 + MockTransport。

边界：
- 只跑 D01 单资料两道记录题（Q01/Q03）；不跑 B0 全矩阵、不跑 OCR、不跑真实供应商；
- create_app / resolve_rag_config / build_gateway / BudgetedModelGateway / QaEngine 均为生产代码；
- 只在传输层注入明确假响应（httpx.MockTransport），观察真实请求路径、预算预留/结算与发送关口；
- Mock GO/预算/账本全部位于本轮 `S2-DEV/G/data/mock-*`，真实共享账本/预算只读 hash，不写入；
- 零自动重试：Mock 内把 `RagConfig.max_retries` 固定为 0（仅本进程测试注入，不是产品改动）；
  产品 live 目前默认 2 次重试，见交付报告的阻断说明。

用法（cwd 仓库根）：
    T09_EVIDENCE_ROOT=docs/evidence/LOCAL-R1-20261101/S2-DEV/G/data/t09-output \
    PYTHONPATH=backend/tests .venv/Scripts/python.exe -B tools/s2g_mock_smoke.py --all
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
G_DIR = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "S2-DEV" / "G"
DATA = G_DIR / "data"
LOGS = G_DIR / "logs"

TARGET = os.environ.get("T09_EVIDENCE_ROOT")
if not TARGET:
    raise SystemExit("T09_EVIDENCE_ROOT 未设置：拒绝启动 Mock 进程")
target_path = Path(TARGET)
if not target_path.is_absolute():
    target_path = ROOT / target_path
expected_root = (DATA / "t09-output").resolve()
if expected_root not in target_path.resolve().parents and target_path.resolve() != expected_root:
    raise SystemExit(f"T09_EVIDENCE_ROOT 必须位于 {expected_root} 之下，实际 {target_path.resolve()}")

if str(ROOT / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "src"))
if str(ROOT / "backend" / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "tests"))

from acceptance.support import b0  # noqa: E402
from acceptance.support.evidence import EVIDENCE_ROOT  # noqa: E402
from conftest import current_csrf, login, upload_document, write_headers  # noqa: E402

if EVIDENCE_ROOT.resolve() != target_path.resolve():
    raise SystemExit(f"证据根解析异常：{EVIDENCE_ROOT.resolve()} != {target_path.resolve()}")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import mktkb.live_authorization as gate_module  # noqa: E402
import mktkb.main as main_module  # noqa: E402
import mktkb.rag.providers as providers_module  # noqa: E402
from mktkb.config import Settings  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.providers import build_gateway as real_build_gateway  # noqa: E402
from mktkb.providers.deepseek import DeepSeekClient  # noqa: E402
from mktkb.rag import budget as budget_module  # noqa: E402
from mktkb.rag.config import RagConfig, safe_config_summary  # noqa: E402
from mktkb.rag.providers import FakeEmbeddingProvider  # noqa: E402

ORIGIN = "http://testserver"
ADMIN_PASSWORD = "S2GAdminPass-1"
EMPLOYEE_PASSWORD = "S2GEmployeePass-1"
STAGE = "S2-G-MOCK"
REAL_LEDGER = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
REAL_BUDGET = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "budget.json"
REAL_GO = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM" / "S2-LIVE-GO.json"

PRODUCT_CHAT_BOUND_CNY = 6144 * 2.0 / 1_000_000.0 + 800 * 8.0 / 1_000_000.0
EMBEDDING_BOUND_CNY = 10 * 8192 * 0.5 / 1_000_000.0
RERANK_BOUND_CNY = 30000 * 0.8 / 1_000_000.0


# ---------------------------------------------------------------- 基础


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return Path(path).resolve().relative_to(ROOT).as_posix()


def dump_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


class SocketGuard:
    """只放行回环/testserver；外部 socket/真实 HTTPTransport 一律记录并拒绝。"""

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
                raise RuntimeError(f"s2g-guard blocked external socket: {host}")
            return guard._real_connect(sock, address, *args, **kwargs)

        def connect_ex(sock, address, *args, **kwargs):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else address
            guard._record(f"socket.connect_ex {host!r}", host)
            raise RuntimeError(f"s2g-guard blocked connect_ex: {host}")

        def create_connection(address, *args, **kwargs):  # noqa: ANN001
            host = address[0] if isinstance(address, tuple) else address
            guard._record(f"socket.create_connection {host!r}", host)
            if not guard._allowed(host):
                raise RuntimeError(f"s2g-guard blocked external socket: {host}")
            return guard._real_create(address, *args, **kwargs)

        def getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
            guard._record(f"socket.getaddrinfo {host!r}", host)
            if not guard._allowed(host):
                raise RuntimeError(f"s2g-guard blocked getaddrinfo: {host}")
            return guard._real_resolve(host, *args, **kwargs)

        def handle_request(transport, request):  # noqa: ANN001
            guard._record(f"httpx.HTTPTransport {request.url}", str(request.url.host))
            raise RuntimeError(f"s2g-guard blocked real HTTPTransport: {request.url}")

        async def handle_async_request(transport, request):  # noqa: ANN001
            guard._record(f"httpx.AsyncHTTPTransport {request.url}", str(request.url.host))
            raise RuntimeError(f"s2g-guard blocked real AsyncHTTPTransport: {request.url}")

        socket.socket.connect = connect
        socket.socket.connect_ex = connect_ex
        socket.create_connection = create_connection
        socket.getaddrinfo = getaddrinfo
        httpx.HTTPTransport.handle_request = handle_request
        httpx.AsyncHTTPTransport.handle_async_request = handle_async_request
        return self

    def summary(self) -> dict:
        return {
            "attempts": len(self.attempts),
            "external_attempts": len(self.external),
            "external": list(self.external),
            "hosts": sorted(set(self.hosts)),
        }


# ---------------------------------------------------------------- 隔离 Mock 授权/预算


def _historical_ledger(path: Path) -> None:
    event = {
        "event": "historical_import",
        "accounted_cny": 0.03,
        "estimated_success_list_price_cny": 0.0000352,
        "provider_billed_cny": None,
        "note": "S2-G isolated mock ledger (not the shared ledger); 0.03 historical baseline only",
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
        "note": "S2-G isolated mock budget; never modifies the shared budget",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_go(
    path: Path,
    ledger: Path,
    *,
    stage_limit_cny: float,
    max_requests: int,
    max_request_cny: float,
    services: tuple[str, ...] = ("rag", "chat"),
    ledger_sha256: str | None = None,
    stage: str = STAGE,
    expires_minutes: int = 120,
) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "document": "S2-LIVE-GO",
        "stage": stage,
        "authorization": "S2-G-MOCK-GO (isolated; not a manager GO)",
        "issued_by": "s2g-mock-smoke",
        "nonce": f"s2g-mock-{uuid.uuid4().hex}",
        "issued_utc": (now - timedelta(minutes=1)).isoformat(),
        "expires_utc": (now + timedelta(minutes=expires_minutes)).isoformat(),
        "budget_ledger_sha256": ledger_sha256 or sha256_path(ledger),
        "scope": {
            "services": list(services),
            "stage_limits_cny": {stage: stage_limit_cny},
            "max_requests": max_requests,
            "max_request_cny": max_request_cny,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def setup_isolated(
    label: str,
    *,
    stage_limit_cny: float = 0.5,
    max_requests: int = 9,
    max_request_cny: float = 0.10,
    write_go: bool = True,
    services: tuple[str, ...] = ("rag", "chat"),
    ledger_sha256: str | None = None,
) -> dict:
    root = DATA / f"mock-{label}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    ledger = root / "live-ledger.jsonl"
    budget = root / "budget.json"
    go = root / "S2-G-MOCK-GO.json"
    _historical_ledger(ledger)
    _write_budget(budget, ledger, stage_limit_cny=stage_limit_cny)
    if write_go:
        _write_go(
            go,
            ledger,
            stage_limit_cny=stage_limit_cny,
            max_requests=max_requests,
            max_request_cny=max_request_cny,
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


def apply_env(*, max_requests: int | str, stage_limit: str, pricing: bool = True) -> None:
    env = {
        "MKTKB_LIVE_STAGE": STAGE,
        "MKTKB_RAG_STAGE_LIMIT_CNY": str(stage_limit),
        "MKTKB_RAG_MAX_REQUESTS": str(max_requests),
        "MKTKB_MODEL_BASE_URL": "https://mock.deepseek.invalid/v1",
        "MKTKB_MODEL_NAME": "deepseek-flash",
        "MKTKB_MODEL_API_KEY": "s2g-mock-model-key-not-real",
        "MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY": "2",
        "MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY": "8",
        "MKTKB_MODEL_MAX_INPUT_TOKENS": "6144",
        "MKTKB_MODEL_MAX_OUTPUT_TOKENS": "800",
        "DASHSCOPE_API_KEY": "s2g-mock-dashscope-key-not-real",
        "DASHSCOPE_BASE_URL": "https://mock.dashscope.invalid",
    }
    if not pricing:
        env.pop("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY")
        env.pop("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY")
        os.environ.pop("MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY", None)
        os.environ.pop("MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY", None)
    for key in ("MKTKB_RAG_BUDGET_LEDGER", "MKTKB_RAG_BUDGET_JSON", "MKTKB_RAG_STAGE"):
        os.environ.pop(key, None)
    os.environ.update(env)


# ---------------------------------------------------------------- MockTransport


class MockProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fake = FakeEmbeddingProvider(model="text-embedding-v4", dimensions=1024)

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
        self.calls.append(
            {
                "seq": len(self.calls) + 1,
                "kind": kind,
                "host": request.url.host,
                "path": path,
                "body_bytes": len(request.content or b""),
                "ts": now_iso(),
            }
        )
        if kind == "embedding":
            texts = [str(item) for item in body.get("input") or []]
            rows = [
                {"object": "embedding", "index": index, "embedding": list(self.fake._vector(text))}
                for index, text in enumerate(texts)
            ]  # noqa: SLF001 - 复用离线确定性向量，仅 Mock
            tokens = min(81920, sum(len(text.encode("utf-8")) + 8 for text in texts) or 1)
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
            rows = [
                {"index": index, "relevance_score": round(1.0 / (index + 1), 6)}
                for index in range(len(docs))
            ]
            tokens = min(30000, (len(query.encode("utf-8")) + 8) * max(1, len(docs)) + sum(len(d.encode("utf-8")) + 8 for d in docs))
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
                    str(item.get("source_id") or item.get("chunk_id"))
                    for item in evidence
                    if item.get("source_id") or item.get("chunk_id")
                ]
                content = json.dumps({"answer": answer, "source_ids": source_ids}, ensure_ascii=False)
            prompt = min(8192, len((messages[0].get("content") if messages else "").encode("utf-8")) + len(messages[1]["content"].encode("utf-8")))
            completion = min(800, len(content.encode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "id": f"mock-chat-{len(self.calls)}",
                    "choices": [
                        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
                    ],
                    "usage": {
                        "prompt_tokens": max(1, prompt),
                        "completion_tokens": max(1, completion),
                        "total_tokens": max(1, prompt) + max(1, completion),
                    },
                },
            )
        return httpx.Response(404, json={"error": "unknown mock path"})

    def summary(self) -> dict:
        buckets: dict[str, int] = {}
        for call in self.calls:
            buckets[call["kind"]] = buckets.get(call["kind"], 0) + 1
        return {
            "total": len(self.calls),
            "by_kind": buckets,
            "calls": list(self.calls),
        }


_ACTIVE = {"transport": None}
_PATCHED = {"providers": [], "rag_from_env": None, "build_gateway": None}


def install_transport_patches(transport: httpx.BaseTransport) -> None:
    _ACTIVE["transport"] = transport
    classes = [
        providers_module.BailianEmbeddingProvider,
        providers_module.BailianRerankProvider,
        providers_module.DeepSeekChatProvider,
    ]
    for cls in classes:
        original = cls.__init__
        if getattr(original, "_s2g_patched", False):
            continue

        def make(orig):
            def init(self, config, *, budget=None, transport=None, require_budget=True):
                return orig(
                    self,
                    config,
                    budget=budget,
                    transport=transport or _ACTIVE["transport"],
                    require_budget=require_budget,
                )

            init._s2g_patched = True
            return init

        cls.__init__ = make(original)
        _PATCHED["providers"].append((cls, original))

    if _PATCHED["rag_from_env"] is None:
        original_from_env = RagConfig.from_env.__func__

        def from_env(cls, **kwargs):
            cfg = original_from_env(cls, **kwargs)
            return dataclasses.replace(cfg, max_retries=0, retry_base_seconds=0.0)

        RagConfig.from_env = classmethod(from_env)
        _PATCHED["rag_from_env"] = original_from_env

    if _PATCHED["build_gateway"] is None:
        original_build = main_module.build_gateway

        def build_gateway(settings):
            return real_build_gateway(settings, transport=_ACTIVE["transport"])

        main_module.build_gateway = build_gateway
        _PATCHED["build_gateway"] = original_build


def uninstall_transport_patches() -> None:
    for cls, original in _PATCHED["providers"]:
        cls.__init__ = original
    _PATCHED["providers"].clear()
    if _PATCHED["rag_from_env"] is not None:
        RagConfig.from_env = classmethod(_PATCHED["rag_from_env"])
        _PATCHED["rag_from_env"] = None
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
        csrf_secret="s2g-mock-csrf-secret-0123456789",
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
        model_base_url=os.environ["MKTKB_MODEL_BASE_URL"],
        model_name=os.environ["MKTKB_MODEL_NAME"],
        model_api_key=os.environ["MKTKB_MODEL_API_KEY"],
        model_request_timeout_seconds=5.0,
    )


def read_ledger(paths: dict, *, max_requests: int = 9, stage_limit: float = 0.5) -> dict:
    ledger = budget_module.BudgetLedger(
        paths["ledger"],
        paths["budget"],
        stage=STAGE,
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
        "conservative_this_round_cny": round(summary.accounted_cny - summary.historical_conservative_cny, 10),
        "estimated_list_price_this_round_cny": round(summary.success_estimated_list_price_cny, 10),
    }


def upload_and_publish(client: TestClient, *, csrf: str, file_id: str) -> dict:
    receipt = upload_document(client, csrf=csrf, path=b0.fixture_path(file_id), allow_same_name=False)
    assert receipt.status_code == 202, receipt.text[:500]
    record = receipt.json()
    document_id = record["document"]["id"]
    version_id = record["version"]["id"]
    db = client.app.state.db.session()
    try:
        result = run_one_job(db, client.app.state.store)
        assert result.state == "succeeded", (result.state, result)
        revision = int(get_revision(db))
    finally:
        db.close()
    published = client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/publish",
        json={"expected_active_version_id": None, "expected_revision": revision},
        headers=write_headers(csrf),
    )
    assert published.status_code == 200, published.text[:500]
    return {
        "file_id": file_id,
        "document_id": document_id,
        "version_id": version_id,
        "revision": revision,
        "publish": published.json(),
    }


def ask(client: TestClient, *, csrf: str, question: str) -> dict:
    created = client.post("/api/v1/conversations", json={}, headers=write_headers(csrf))
    assert created.status_code == 201, created.text[:500]
    conversation = created.json()["id"]
    response = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=write_headers(csrf),
    )
    payload = response.json() if response.status_code == 200 else {}
    return {
        "http_status": response.status_code,
        "kind": payload.get("kind"),
        "error_code": payload.get("error_code"),
        "source_count": len(payload.get("sources") or []),
        "missing_fields": payload.get("missing_fields") or [],
        "text_chars": len(payload.get("text") or ""),
    }


def real_path_hashes() -> dict:
    return {
        "ledger_sha256": sha256_path(REAL_LEDGER),
        "budget_sha256": sha256_path(REAL_BUDGET),
        "go_exists": REAL_GO.exists(),
    }


# ---------------------------------------------------------------- 场景


def scenario_smoke(guard: SocketGuard, plan_trace: dict) -> dict:
    paths = setup_isolated("smoke", stage_limit_cny=0.5, max_requests=13, max_request_cny=0.10)
    apply_env(max_requests=13, stage_limit="0.5")
    patch_gate(paths)
    provider = MockProvider()
    transport = httpx.MockTransport(provider.handler)
    install_transport_patches(transport)
    providers_module.reset_post_counters()
    app = None
    try:
        settings = make_settings(paths)
        app = main_module.create_app(settings)
        client = TestClient(app, raise_server_exceptions=False)
        login(client, "admin", ADMIN_PASSWORD)
        csrf = current_csrf(client)

        build = upload_and_publish(client, csrf=csrf, file_id="D01")
        questions = [item for item in b0.QUESTIONS if item["id"] in {"Q01", "Q03"}]
        answers = [ask(client, csrf=csrf, question=item["question"]) for item in questions]

        # 只读诊断：不触发新请求。
        qa_status = app.state.qa.status() if app.state.qa is not None else None
        gateway_stats = app.state.model_gateway.stats() if hasattr(app.state.model_gateway, "stats") else None
        post_counters = providers_module.post_counters()
        transport_summary = provider.summary()
        ledger = read_ledger(paths, max_requests=13)
        real_hashes = real_path_hashes()

        # 记录型问题在 candidate_unit_ids_for_intent 中做 record + document 两次 search；
        # 每次 search ≤1 query embedding + 1 rerank；产品回答 chat ≤1（扩展时 +1）。
        expected_transport = 1 + len(questions) * 5  # 发布重索引 1 + 每问 2 embedding + 2 rerank + 1 chat
        checks = {
            "http_all_200": all(item["http_status"] == 200 for item in answers),
            "all_answer": all(item["kind"] == "answer" for item in answers),
            "all_have_sources": all(item["source_count"] > 0 for item in answers),
            "transport_expected": transport_summary["total"] == expected_transport,
            "reserved_equals_transport": ledger["reserved"] == transport_summary["total"],
            "settled_equals_reserved": ledger["results"] == ledger["reserved"],
            "unsettled_zero": ledger["unsettled"] == [],
            "external_zero": guard.summary()["external_attempts"] == 0,
            "chat_send_attempts": (gateway_stats or {}).get("counters", {}).get("send_attempts") == len(questions),
            "post_attempts_match": (
                post_counters["attempts"].get("embedding", 0)
                + post_counters["attempts"].get("rerank", 0)
                + post_counters["attempts"].get("chat", 0)
                + (gateway_stats or {}).get("counters", {}).get("send_attempts", 0)
                == transport_summary["total"]
            ),
            "conservative_positive": ledger["conservative_this_round_cny"] > 0,
            "real_paths_unchanged": real_hashes == plan_trace.get("_real_hashes_at_start", real_hashes),
        }
        return {
            "scenario": "smoke",
            "mode": "mock",
            "isolated": {key: rel(value) for key, value in paths.items()},
            "go_sha256": sha256_path(paths["go"]),
            "ledger_sha256": sha256_path(paths["ledger"]),
            "budget_sha256": sha256_path(paths["budget"]),
            "settings": {
                "provider_mode": getattr(getattr(app.state.qa, "config", None), "provider_mode", None),
                "max_retries": getattr(getattr(app.state.qa, "config", None), "max_retries", None),
                "max_input_tokens": 6144,
                "max_output_tokens": 800,
                "pricing": {"chat_input": 2.0, "chat_output": 8.0, "embedding": 0.5, "rerank": 0.8},
                "config_summary": safe_config_summary(app.state.qa.config) if app.state.qa is not None else None,
            },
            "build": build,
            "questions": [item["id"] for item in questions],
            "answers": answers,
            "expected_transport": expected_transport,
            "transport": transport_summary,
            "post_counters": post_counters,
            "gateway_stats": gateway_stats,
            "ledger": ledger,
            "qa_status": qa_status,
            "socket_guard": guard.summary(),
            "real_paths": real_hashes,
            "checks": checks,
            "pass": all(checks.values()),
            "captured_at": now_iso(),
        }
    finally:
        restore_gate_paths()
        uninstall_transport_patches()
        if app is not None:
            try:
                app.state.db.dispose()  # type: ignore[name-defined]
            except Exception:
                pass


def scenario_refusals(guard: SocketGuard) -> dict:
    """每一例都用独立隔离目录；断言拒绝发生在任何 transport/预留之前。"""
    cases: list[dict] = []

    def run_case(label: str, *, write_go: bool = True, max_requests: int | str = 9,
                 stage_limit: str = "0.5", pricing: bool = True,
                 services: tuple[str, ...] = ("rag", "chat"),
                 ledger_sha256: str | None = None,
                 max_request_cny: float = 0.10) -> None:
        paths = setup_isolated(
            f"refuse-{label}",
            stage_limit_cny=0.5,
            max_requests=9,
            max_request_cny=max_request_cny,
            write_go=write_go,
            services=services,
            ledger_sha256=ledger_sha256,
        )
        if not write_go:
            paths["go"].unlink(missing_ok=True)
        apply_env(max_requests=max_requests, stage_limit=stage_limit, pricing=pricing)
        patch_gate(paths)
        provider = MockProvider()
        before_transport = len(provider.calls)
        settings = SimpleNamespace(
            model_base_url=os.environ["MKTKB_MODEL_BASE_URL"],
            model_name=os.environ["MKTKB_MODEL_NAME"],
            model_api_key=os.environ["MKTKB_MODEL_API_KEY"],
            model_request_timeout_seconds=5.0,
        )
        error = None
        try:
            real_build_gateway(settings, transport=httpx.MockTransport(provider.handler))
        except Exception as exc:  # noqa: BLE001 - 拒绝类型/文本就是证据
            error = {"type": type(exc).__name__, "text": str(exc)[:400]}
        ledger = read_ledger(paths)
        cases.append(
            {
                "case": label,
                "refused": error is not None,
                "error": error,
                "transport_calls": len(provider.calls) - before_transport,
                "ledger_events": len(ledger["events"]),
                "reservations": ledger["reserved"],
                "isolated": {key: rel(value) for key, value in paths.items()},
            }
        )
        restore_gate_paths()

    run_case("no-go", write_go=False)
    run_case("zero-max-requests", max_requests=0)
    run_case("omitted-max-requests", max_requests="")
    run_case("zero-stage-limit", stage_limit="0")
    run_case("missing-pricing", pricing=False)
    run_case("service-not-allowed", services=("rag",))
    run_case("ledger-hash-mismatch", ledger_sha256="0" * 64)
    run_case("request-bound-over-go", max_request_cny=0.01)

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


def scenario_timeout(guard: SocketGuard) -> dict:
    paths = setup_isolated("timeout", stage_limit_cny=0.5, max_requests=9, max_request_cny=0.10)
    apply_env(max_requests=9, stage_limit="0.5")
    patch_gate(paths)
    provider = MockProvider()
    base_handler = provider.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            provider.calls.append(
                {
                    "seq": len(provider.calls) + 1,
                    "kind": "chat",
                    "host": request.url.host,
                    "path": request.url.path,
                    "body_bytes": len(request.content or b""),
                    "ts": now_iso(),
                    "injected": "timeout",
                }
            )
            raise httpx.ReadTimeout("s2g mock timeout", request=request)
        return base_handler(request)

    transport = httpx.MockTransport(handler)
    install_transport_patches(transport)
    providers_module.reset_post_counters()
    app = None
    try:
        settings = make_settings(paths)
        app = main_module.create_app(settings)
        client = TestClient(app, raise_server_exceptions=False)
        login(client, "admin", ADMIN_PASSWORD)
        csrf = current_csrf(client)
        build = upload_and_publish(client, csrf=csrf, file_id="D01")
        question = next(item for item in b0.QUESTIONS if item["id"] == "Q01")
        answer = ask(client, csrf=csrf, question=question["question"])
        ledger = read_ledger(paths)
        gateway_stats = app.state.model_gateway.stats() if hasattr(app.state.model_gateway, "stats") else None
        checks = {
            "http_200": answer["http_status"] == 200,
            "service_error_timeout": answer["kind"] == "service_error" and answer["error_code"] == "MODEL_TIMEOUT",
            "chat_result_timeout": "timeout" in ledger["result_statuses"],
            "no_unsettled": ledger["unsettled"] == [],
            "chat_conservative_retained": ledger["conservative_this_round_cny"] >= PRODUCT_CHAT_BOUND_CNY,
            "external_zero": guard.summary()["external_attempts"] == 0,
        }
        return {
            "scenario": "timeout",
            "mode": "mock",
            "isolated": {key: rel(value) for key, value in paths.items()},
            "build": build,
            "answer": answer,
            "transport": provider.summary(),
            "post_counters": providers_module.post_counters(),
            "gateway_stats": gateway_stats,
            "ledger": ledger,
            "socket_guard": guard.summary(),
            "checks": checks,
            "pass": all(checks.values()),
            "captured_at": now_iso(),
        }
    finally:
        restore_gate_paths()
        uninstall_transport_patches()
        if app is not None:
            try:
                app.state.db.dispose()
            except Exception:
                pass


def scenario_crash_unsettled(guard: SocketGuard) -> dict:
    """子进程预留后立即退出（不 settle），证明退出摘要仍把未结算预留计入占用。"""
    paths = setup_isolated("crash", stage_limit_cny=0.5, max_requests=9, max_request_cny=0.10, write_go=False)
    child = G_DIR / "probes" / "mock_crash_child.py"
    child.write_text(
        '''"""S2-G Mock：预留后立即退出，不结算（仅隔离 Mock 账本）。"""
from __future__ import annotations
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend" / "src"))
from mktkb.rag.budget import BudgetLedger
ledger = BudgetLedger(sys.argv[1], sys.argv[2], stage=sys.argv[3], stage_limit_cny=0.5, max_requests=9)
reservation = ledger.reserve(
    kind="chat", provider="deepseek", model="deepseek-flash",
    max_cny=0.022784, request_sha256="s2g-crash-unsettled-demo",
)
print(reservation.reservation_id)
os._exit(0)
''',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "-B", str(child), str(paths["ledger"]), str(paths["budget"]), STAGE],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "T09_EVIDENCE_ROOT": str(target_path), "PYTHONPATH": str(ROOT / "backend" / "src")},
        timeout=60,
    )
    ledger = read_ledger(paths)
    checks = {
        "child_exit_zero": completed.returncode == 0,
        "one_reservation": ledger["reserved"] == 1,
        "zero_results": ledger["results"] == 0,
        "one_unsettled": len(ledger["unsettled"]) == 1,
        "accounted_includes_reserve": ledger["summary"]["accounted_cny"] >= 0.03 + 0.022784 - 1e-9,
        "external_zero": guard.summary()["external_attempts"] == 0,
    }
    return {
        "scenario": "crash-unsettled",
        "mode": "mock",
        "isolated": {key: rel(value) for key, value in paths.items()},
        "child_exit_code": completed.returncode,
        "child_stdout": completed.stdout.strip(),
        "child_stderr": completed.stderr.strip()[:500],
        "ledger": ledger,
        "socket_guard": guard.summary(),
        "checks": checks,
        "pass": all(checks.values()),
        "captured_at": now_iso(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="跑 smoke + refusals + timeout + crash")
    parser.add_argument("--only", choices=["smoke", "refusals", "timeout", "crash"], default=None)
    args = parser.parse_args()
    if not args.all and not args.only:
        args.all = True

    DATA.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    plan_trace = read_json(DATA / "plan-trace.json") if (DATA / "plan-trace.json").exists() else {}
    real_start = real_path_hashes()
    plan_trace["_real_hashes_at_start"] = real_start
    guard = SocketGuard().install()
    results: dict[str, dict] = {}
    started = now_iso()
    try:
        if args.all or args.only == "smoke":
            print("[scenario] smoke ...", flush=True)
            results["smoke"] = scenario_smoke(guard, plan_trace)
            dump_json(DATA / "mock-smoke.json", results["smoke"])
            print(f"  pass={results['smoke']['pass']} transport={results['smoke']['transport']['total']} ledger={results['smoke']['ledger']['summary']}", flush=True)
        if args.all or args.only == "refusals":
            print("[scenario] refusals ...", flush=True)
            results["refusals"] = scenario_refusals(guard)
            dump_json(DATA / "mock-refusals.json", results["refusals"])
            print(f"  pass={results['refusals']['pass']} cases={len(results['refusals']['cases'])}", flush=True)
        if args.all or args.only == "timeout":
            print("[scenario] timeout ...", flush=True)
            results["timeout"] = scenario_timeout(guard)
            dump_json(DATA / "mock-timeout.json", results["timeout"])
            print(f"  pass={results['timeout']['pass']} answer={results['timeout']['answer']}", flush=True)
        if args.all or args.only == "crash":
            print("[scenario] crash-unsettled ...", flush=True)
            results["crash"] = scenario_crash_unsettled(guard)
            dump_json(DATA / "mock-crash-unsettled.json", results["crash"])
            print(f"  pass={results['crash']['pass']} ledger={results['crash']['ledger']['summary']}", flush=True)
    finally:
        restore_gate_paths()
        uninstall_transport_patches()

    real_end = real_path_hashes()
    summary = {
        "started_at": started,
        "finished_at": now_iso(),
        "mode": "mock-only; no real provider/network; isolated mock GO/ledger/budget",
        "evidence_root": str(EVIDENCE_ROOT),
        "real_paths_start": real_start,
        "real_paths_end": real_end,
        "real_paths_unchanged": real_start == real_end,
        "socket_guard": guard.summary(),
        "scenarios": {name: {"pass": payload.get("pass"), "checks": payload.get("checks")} for name, payload in results.items()},
        "pass": all(payload.get("pass") for payload in results.values()) and real_start == real_end,
    }
    dump_json(DATA / "mock-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
