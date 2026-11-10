
"""T206-LIVE-R1 独立复验探针（复验助手自写；证伪优先，零真实调用）。

不导入开发助手的测试断言；只用产品公开入口 + 自建 fake transport。
输出到 stdout（纯文本），账本/预算/GO 全部 tmp 副本；socket 闸门在进程内先装。
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import socket
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

REPO = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(REPO / "backend" / "src"))

# ---------------------------------------------------------------- socket 闸门
# 与仓库既有 t09_network_guard 同口径：放行回环（Windows asyncio self-pipe 需要），
# 拦一切**外部**目标并记账；外部尝试非 0 即视为真实出站。
_EXT: list[tuple[str, object]] = []
_LOCAL: list[tuple[str, object]] = []
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def _is_loopback(address) -> bool:
    if isinstance(address, str):
        return (address.startswith("\\\\.\\pipe\\") or address.startswith("/")
                or "localhost" in address)
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("utf-8", "replace")
        if not isinstance(host, str):
            return False
        return host in _LOOPBACK or host.startswith("127.")
    return False


def _record(label, address) -> None:
    (_LOCAL if address is not None and _is_loopback(address) else _EXT).append((label, address))


_orig_socket = socket.socket
_real_connect = _orig_socket.connect
_real_connect_ex = _orig_socket.connect_ex
_real_create_connection = socket.create_connection
_real_getaddrinfo = socket.getaddrinfo


def _guarded_connect(self, address, *args, **kwargs):
    _record("connect", address)
    if _is_loopback(address):
        return _real_connect(self, address, *args, **kwargs)
    raise OSError("blocked by verify-r1 probe: " + repr(address))


def _guarded_connect_ex(self, address, *args, **kwargs):
    _record("connect_ex", address)
    if _is_loopback(address):
        return _real_connect_ex(self, address, *args, **kwargs)
    return 111


def _guarded_create_connection(address, *args, **kwargs):
    _record("create_connection", address)
    if _is_loopback(address):
        return _real_create_connection(address, *args, **kwargs)
    raise OSError("blocked by verify-r1 probe: " + repr(address))


def _guarded_getaddrinfo(host, *args, **kwargs):
    if _is_loopback(host if isinstance(host, str) else ""):
        _LOCAL.append(("getaddrinfo", host))
        return _real_getaddrinfo(host, *args, **kwargs)
    _EXT.append(("getaddrinfo", host))
    raise OSError("blocked by verify-r1 probe: " + repr(host))


_orig_socket.connect = _guarded_connect
_orig_socket.connect_ex = _guarded_connect_ex
socket.create_connection = _guarded_create_connection
socket.getaddrinfo = _guarded_getaddrinfo

import httpx  # noqa: E402


def _blocked_sync_transport(self, request):
    _EXT.append(("HTTPTransport", str(request.url)))
    raise OSError("blocked by verify-r1 probe: " + str(request.url))


async def _blocked_async_transport(self, request):
    _EXT.append(("AsyncHTTPTransport", str(request.url)))
    raise OSError("blocked by verify-r1 probe: " + str(request.url))


httpx.HTTPTransport.handle_request = _blocked_sync_transport
httpx.AsyncHTTPTransport.handle_async_request = _blocked_async_transport

from mktkb import live_authorization  # noqa: E402
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation import p2_contracts as c  # noqa: E402
from mktkb.evaluation import p2_live  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, validate_case  # noqa: E402
from mktkb.evaluation.p2_contracts import P2RunPlan  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
)
from mktkb.providers.types import CompletionInput, CompletionOutput, ModelEvidence  # noqa: E402

ROOT = REPO
FIX = ROOT / "fixtures" / "acceptance"
D01 = FIX / "normal" / "D01_物品位置表.xlsx"
B0 = ROOT / "fixtures" / "evaluation" / "b0.jsonl"
NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
LIMIT = 40.0
STAGE = 20.0
CENTERS = {"answer_retrieval": 9.0, "ocr": 6.0, "judge": 3.0, "independent": 2.0}
OVERRIDES = {
    "chat_api_key": "verify-r1-not-a-secret",
    "chat_base_url": "https://api.deepseek.com",
    "chat_model": "deepseek-flash",
    "dashscope_api_key": "verify-r1-not-a-secret",
    "dashscope_base_url": "https://dashscope.aliyuncs.com",
    "ocr_secret_id": "verify-r1-not-a-secret",
    "ocr_secret_key": "verify-r1-not-a-secret",
    "ocr_region": "ap-guangzhou",
}


def out(tag: str, *values: object) -> None:
    print("[" + tag + "]", *values, flush=True)


def profiles() -> dict[str, dict]:
    return {
        "embedding": {"kind": "embedding", "model": "text-embedding-v4", "provider": "bailian",
                      "host": "dashscope.aliyuncs.com", "region": "cn-beijing",
                      "pricing_source": "official-list-price/bailian-text-embedding-v4-v1",
                      "unit_price_per_million_cny": 0.5, "total_tokens_cap": 4096},
        "rerank": {"kind": "rerank", "model": "gte-rerank-v2", "provider": "bailian",
                   "host": "dashscope.aliyuncs.com", "region": "cn-beijing",
                   "pricing_source": "official-list-price/bailian-gte-rerank-v2-v1",
                   "unit_price_per_million_cny": 0.8, "total_tokens_cap": 6000},
        "chat": {"kind": "chat", "model": "deepseek-flash", "provider": "deepseek",
                 "host": "api.deepseek.com", "region": "global",
                 "pricing_source": "official-list-price/deepseek-chat-cache-miss-v1",
                 "input_price_per_million_cny": 2.0, "output_price_per_million_cny": 8.0,
                 "prompt_tokens_cap": 6144, "completion_tokens_cap": 800},
        "ocr": {"kind": "ocr", "model": "GeneralAccurateOCR", "provider": "tencent",
                "host": "ocr.tencentcloudapi.com", "region": "ap-guangzhou",
                "pricing_source": "official-list-price/tencent-ocr-postpaid-highest-v1",
                "price_cny_per_page": 0.5, "pages_per_request": 1},
    }


def item(item_id: str, operation: str, case_id: str, *, requests: int = 1, page: int = 0) -> dict:
    prof = profiles()[c.OPERATION_KIND[operation]]
    expected = {"chat": 0.004, "embedding": 0.0003, "rerank": 0.001, "ocr": 0.5}[prof["kind"]]
    return {"item_id": item_id, "operation": operation,
            "cost_center": c.OPERATION_COST_CENTER[operation], "case_id": case_id,
            "turn": 1, "page": page, "requests": requests,
            "price_profile": copy.deepcopy(prof), "expected_success_cny": expected}


def plan_dict(*, with_expansion: bool = True, ingest_requests: int = 8) -> dict:
    items = [
        item("ingest-index", "index_embedding", "INGEST", requests=ingest_requests),
        item("embed-Q01-t1", "query_embedding", "Q01"),
        item("rerank-Q01-t1", "rerank", "Q01"),
        item("answer-Q01-t1", "answer", "Q01"),
        item("embed-Q25-t1", "query_embedding", "Q25"),
        item("rerank-Q25-t1", "rerank", "Q25"),
        item("answer-Q25-t1", "answer", "Q25"),
    ]
    if with_expansion:
        items.insert(3, item("expand-Q01-t1", "query_expansion", "Q01"))
        items.insert(-1, item("expand-Q25-t1", "query_expansion", "Q25"))
    items.append(item("ocr-Q01-p1", "ocr", "Q01", page=1))
    return {
        "schema_version": c.P2_RUN_PLAN_SCHEMA_VERSION,
        "plan_id": "P2-LIVE-VERIFY-R1", "plan_version": "v0.1", "mode": "end_to_end",
        "stage": "P2-LIVE", "created_utc": "2026-11-11T00:00:00+08:00",
        "project_total_limit_cny": LIMIT, "stage_limit_cny": STAGE, "max_requests": 1000,
        "cost_centers_cny": dict(CENTERS), "items": items,
    }


def write_ledger(path: Path) -> None:
    path.write_text(json.dumps({"event": "historical_import", "accounted_cny": 2.0,
                                "source": "verify-r1"}) + "\n", encoding="utf-8")


def write_budget(path: Path) -> None:
    path.write_text(json.dumps({"limit_cny": LIMIT, "historical_conservative_accounted_cny": 2.0,
                                "stages": {"S2-DEV": 18.0, "P2-LIVE": STAGE}}, indent=2) + "\n",
                    encoding="utf-8")


def write_go(path: Path, *, ledger: Path, plan: P2RunPlan) -> None:
    path.write_text(json.dumps({
        "document": "P2-LIVE-GO", "schema_version": "p2-live-go/v0.1", "stage": "P2-LIVE",
        "authorization": "VERIFY-R1-MOCK-GO（零真实调用）", "issued_by": "verify-r1-probe",
        "nonce": "verify-r1-nonce-0123456789", "issued_utc": "2026-11-19T00:00:00+00:00",
        "expires_utc": "2026-11-20T00:00:00+00:00", "budget_ledger_path": str(ledger),
        "budget_ledger_sha256": live_authorization.historical_prefix_sha256(ledger),
        "budget_total_limit_cny": LIMIT,
        "scope": {"plan_id": plan.plan_id, "plan_sha256": plan.plan_sha256,
                  "operations": list(plan.operations), "cost_centers_cny": dict(CENTERS),
                  "stage_limits_cny": {"P2-LIVE": STAGE}, "max_requests": 1000,
                  "max_request_cny": 0.5}}, indent=2) + "\n", encoding="utf-8")


def events(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def reservations(path: Path) -> list[dict]:
    return [r for r in events(path) if r.get("event") == "reserved"]


def results(path: Path) -> list[dict]:
    return [r for r in events(path) if r.get("event") == "result"]


class UsageBackend(MockChatBackend):
    """MockChatBackend + DeepSeek 官方 usage（含 cache 拆分）。"""

    def _completion(self, request, content, *, call):
        resp = super()._completion(request, content, call=call)
        payload = json.loads(resp.content.decode("utf-8"))
        payload["usage"] = {"prompt_tokens": 64, "completion_tokens": 32, "total_tokens": 96,
                            "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 64}
        return httpx.Response(200, json=payload, request=request)


def embedding_transport(calls: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        texts = list(body.get("input") or ())
        dims = int(body.get("dimensions") or 1024)
        calls.append(len(texts))
        return httpx.Response(200, json={
            "object": "list",
            "data": [{"object": "embedding", "index": i, "embedding": [0.01] * dims}
                     for i in range(len(texts))],
            "usage": {"total_tokens": 40}, "id": "emb-" + str(len(calls))}, request=request)
    return httpx.MockTransport(handler)


def rerank_transport(calls: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        docs = list((body.get("input") or {}).get("documents") or ())
        calls.append(len(docs))
        return httpx.Response(200, json={
            "output": {"results": [{"index": i, "relevance_score": 0.9 - i * 0.01}
                                   for i in range(len(docs))]},
            "usage": {"total_tokens": 80}, "request_id": "rr-" + str(len(calls))},
            request=request)
    return httpx.MockTransport(handler)


def ocr_transport(calls: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers.get("X-TC-Action"))
        return httpx.Response(200, json={"Response": {"TextDetections": [{
            "DetectedText": "领取活动物料需先填写物料领用单", "Confidence": 99,
            "Polygon": [{"X": 10, "Y": 10}, {"X": 200, "Y": 10},
                        {"X": 200, "Y": 40}, {"X": 10, "Y": 40}]}],
            "RequestId": "ocr-v1"}}, request=request)
    return httpx.MockTransport(handler)


def dataset(case_id: str = "Q01") -> P2RunDataset:
    rows = [json.loads(x) for x in B0.read_text(encoding="utf-8").splitlines() if x.strip()]
    case = CaseSpec.from_dict(next(r for r in rows if r["case_id"] == case_id))
    validate_case(case)
    return P2RunDataset(visibility="public", cases=(case,), identity={
        "dataset_version": "verify-r1-ds", "label_version": "b0-2026-11-04", "suite": "b0",
        "manifest_sha256": "a" * 64, "case_count": 1})


class Env:
    def __init__(self, root: Path, plan: P2RunPlan) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.plan = plan
        self.ledger = root / "ledger.jsonl"
        self.budget = root / "budget.json"
        self.go = root / "P2-LIVE-GO.json"
        write_ledger(self.ledger)
        write_budget(self.budget)
        write_go(self.go, ledger=self.ledger, plan=plan)


def pin(env: Env, monkeypatch) -> None:
    monkeypatch.setattr(p2a, "P2_LEDGER_PATH", env.ledger)
    monkeypatch.setattr(p2a, "P2_BUDGET_PATH", env.budget)
    monkeypatch.setattr(p2a, "P2_GO_PATH", env.go)


def run_e2e(env: Env, root: Path, *, case_id: str, ingest, chat: MockChatBackend, gate_config=None):
    plan = env.plan
    gate = p2_live.open_live_gate(plan, run_id="verify-r1", now=NOW)
    ingest_plan = None if ingest is None else P2IngestPlan(
        sources=(IngestSource(path=ingest),), label="verify-r1")
    transports = {"chat": chat.transport, "embedding": embedding_transport([]),
                  "rerank": rerank_transport([]), "ocr": ocr_transport([])}

    async def go():
        return await p2_live.run_live_p2(
            plan, run_id="verify-r1", out_dir=root / "run", dataset=dataset(case_id),
            ingest_plan=ingest_plan, gate=gate, env={"MKTKB_OCR_DISABLED": "0"},
            env_overrides=OVERRIDES, transports=transports, now=NOW, gate_config=gate_config)

    return asyncio.run(go())


class FakeGateway:
    provider = "deepseek"
    model = "deepseek-flash"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, request, *, timeout_seconds, **kwargs):
        self.calls.append(str(getattr(request, "purpose", "")))
        return CompletionOutput(text="ok", source_ids=(), query_terms=(),
                                provider_request_id="fake-1",
                                usage={"prompt_tokens": 64, "completion_tokens": 32,
                                       "total_tokens": 96, "prompt_cache_hit_tokens": 0,
                                       "prompt_cache_miss_tokens": 64},
                                raw_usage={"prompt_tokens": 64, "completion_tokens": 32,
                                           "total_tokens": 96, "prompt_cache_hit_tokens": 0,
                                           "prompt_cache_miss_tokens": 64})

    async def aclose(self):
        return None


def text_of(call):
    return str(call)


print("=" * 70)
print("T206-LIVE-R1 独立复验探针（verify-r1）")
tmp = Path(tempfile.mkdtemp(prefix="t206-r1-verify-"))
print("tmp=", tmp)
print("=" * 70)

from _pytest.monkeypatch import MonkeyPatch  # noqa: E402

mp = MonkeyPatch()
mp.setenv(live_authorization.TOTAL_LIMIT_ENV, str(LIMIT))

# ============================================================ F1
print("\n--- F1: query_expansion 真实归属 / answer-* 不被顶账 / 同轮第二次 answer 拒绝 ---")
try:
    plan = P2RunPlan.from_dict(plan_dict())
    env = Env(tmp / "f1", plan)
    pin(env, mp)
    gate = p2_live.open_live_gate(plan, run_id="verify-r1-f1", now=NOW)
    f1_budget = p2_live.AttemptBudget(plan)
    wiring = p2_live.LiveWiring(
        env=p2_live.load_live_env({}, overrides=OVERRIDES), plan=plan, run_id="verify-r1-f1",
        gate=gate, ledger=p2_live.GateAttemptLedger(gate, plan, attempt_budget=f1_budget),
        attempt_budget=f1_budget, plan_index=p2_live.PlanIndex(plan))
    wiring.ledger._on_receipt = wiring.receipts.append
    from mktkb.evaluation.p2_runner import _request_uuid
    wiring.enter_turn(_request_uuid("verify-r1-f1", "Q01", 1))
    inner = FakeGateway()
    gateway = p2_live.GatedChatGateway(inner, wiring=wiring)
    ticket = gate.begin("answer-Q01-t1")
    gate.confirm_before_send(ticket)
    evidence = (ModelEvidence(source_id="11111111-1111-1111-1111-111111111111", text="t", fields={}),)

    async def f1_flow():
        answer_req = CompletionInput(purpose="answer", question="q", evidence=evidence)
        await gateway.complete(answer_req, timeout_seconds=5)
        captured = wiring.retrieved_ids()
        first_calls = len(inner.calls)
        try:
            await gateway.complete(answer_req, timeout_seconds=5)
            second = None
        except p2_live.P2LiveRefused as exc:
            second = exc.code
        after_second = len(inner.calls)
        expansion_req = CompletionInput(purpose="query_expansion", question="q")
        await gateway.complete(expansion_req, timeout_seconds=5)
        return captured, first_calls, second, after_second, len(inner.calls)

    captured, first_calls, second_code, after_second, after_exp = asyncio.run(f1_flow())
    out("F1", "retrieved_captured=", captured)
    out("F1", "answer_posts_after_first=", first_calls, "second_answer_code=", second_code,
        "posts_after_second=", after_second, "posts_after_expansion=", after_exp)
    out("F1", "budget_used=", wiring.attempt_budget.as_dict(),
        "answer_item_used=", wiring.attempt_budget.used("answer-Q01-t1"),
        "chat_calls=", wiring.as_dict()["calls"])
    receipts = wiring.receipt_payload()
    out("F1", "expansion_receipts=", [(r["phase"], r["item_id"], r["operation"], r["status"],
                                      r["charged_cny"]) for r in receipts])
    led = events(env.ledger)
    chat_res = [r for r in reservations(env.ledger) if r.get("kind") == "chat"]
    out("F1", "ledger_chat_reservations=", len(chat_res),
        "centers=", [r.get("cost_center") for r in chat_res],
        "results=", [(r.get("status"), r.get("error_code")) for r in results(env.ledger)])
    # 缺 expand 计划项：必须在发送前失败（不借 answer 的钱）
    plan2 = P2RunPlan.from_dict(plan_dict(with_expansion=False))
    env2 = Env(tmp / "f1b", plan2)
    pin(env2, mp)
    gate2 = p2_live.open_live_gate(plan2, run_id="verify-r1-f1b", now=NOW)
    f1b_budget = p2_live.AttemptBudget(plan2)
    wiring2 = p2_live.LiveWiring(
        env=p2_live.load_live_env({}, overrides=OVERRIDES), plan=plan2, run_id="verify-r1-f1b",
        gate=gate2, ledger=p2_live.GateAttemptLedger(gate2, plan2, attempt_budget=f1b_budget),
        attempt_budget=f1b_budget, plan_index=p2_live.PlanIndex(plan2))
    wiring2.enter_turn(_request_uuid("verify-r1-f1b", "Q01", 1))
    inner2 = FakeGateway()
    gateway2 = p2_live.GatedChatGateway(inner2, wiring=wiring2)

    async def f1b():
        try:
            await gateway2.complete(CompletionInput(purpose="query_expansion", question="q"),
                                    timeout_seconds=5)
            return None
        except p2_live.P2LiveRefused as exc:
            return exc.code

    code = asyncio.run(f1b())
    out("F1", "no_expand_item_code=", code, "posts=", len(inner2.calls),
        "reservations=", len(reservations(env2.ledger)))
    # 产品真实路径（空库 + 正文型 Q25）：expand 项被真实消耗，answer-* 不被顶账。
    env3 = Env(tmp / "f1c", plan)
    pin(env3, mp)
    chat3 = UsageBackend()
    res3, build3 = run_e2e(env3, tmp / "f1c", case_id="Q25", ingest=None, chat=chat3)
    out("F1", "product_status=", res3.status, "stop=", res3.stop_code,
        "purposes=", chat3.counts_by_purpose(),
        "quota=", build3.wiring.attempt_budget.as_dict(),
        "calls=", build3.wiring.as_dict()["calls"])
    out("F1", "product_receipts=", [(r["phase"], r["item_id"], r["status"], r["charged_cny"])
                                    for r in build3.wiring.receipt_payload()])
    out("F1", "product_results=", [(r.get("kind"), r.get("status"), r.get("error_code"),
                                   r.get("conservative_charge_cny"))
                                  for r in results(env3.ledger)])
except Exception as exc:  # noqa: BLE001
    import traceback
    out("F1", "PROBE_ERROR", repr(exc))
    traceback.print_exc()

# ============================================================ F2
print("\n--- F2: 计划项配额按真实 POST/批 ---")
try:
    from mktkb.rag import RagConfig
    from mktkb.rag.providers import BailianEmbeddingProvider
    from mktkb.rag.settlement_policy import build_policy

    def embed_gated(env: Env, root: Path, plan: P2RunPlan, run_id: str):
        cfg = RagConfig(
            provider_mode="live", data_dir=root / "data", business_date=None, top_k=8,
            page_size=10, vector_candidate_limit=50, rerank_top_n=20,
            embedding_base_url="https://dashscope.aliyuncs.com",
            embedding_api_key="verify-r1-not-a-secret", embedding_batch_size=5,
            embedding_timeout_seconds=30.0, max_request_cny=0.5, max_retries=0,
            require_zero_retries=True)
        gate = p2_live.open_live_gate(plan, run_id=run_id, now=NOW)
        budget = p2_live.AttemptBudget(plan)
        recs: list = []
        ledger = p2_live.GateAttemptLedger(gate, plan, on_receipt=recs.append, attempt_budget=budget)
        wiring = p2_live.LiveWiring(env=p2_live.load_live_env({}, overrides=OVERRIDES),
                                    plan=plan, run_id=run_id, gate=gate, ledger=ledger,
                                    attempt_budget=budget, plan_index=p2_live.PlanIndex(plan),
                                    receipts=recs)
        posts: list = []
        inner = BailianEmbeddingProvider(
            cfg, budget=ledger, require_budget=True,
            settlement_policy=build_policy("embedding", model=cfg.embedding_model),
            transport=embedding_transport(posts))
        return p2_live.GatedEmbeddingProvider(inner, wiring=wiring), wiring, posts

    texts = ["第%d条待索引文本" % i for i in range(12)]
    env = Env(tmp / "f2", P2RunPlan.from_dict(plan_dict()))
    pin(env, mp)
    gated, wiring, posts = embed_gated(env, tmp / "f2", env.plan, "verify-r1-f2")
    resp = gated.embed(texts)
    out("F2", "vectors=", len(resp.vectors), "posts=", len(posts), "batch_sizes=", posts)
    out("F2", "quota_used=", wiring.attempt_budget.used("ingest-index"),
        "ledger_attempts=", wiring.ledger.attempts("index_embedding"),
        "reservations=", len([r for r in reservations(env.ledger) if r.get("kind") == "embedding"]),
        "results=", len([r for r in results(env.ledger) if r.get("kind") == "embedding"]),
        "as_dict=", gated.as_dict())
    # 计划只给 2 批
    tight_plan = P2RunPlan.from_dict(plan_dict(ingest_requests=2))
    env_t = Env(tmp / "f2t", tight_plan)
    pin(env_t, mp)
    gated_t, wiring_t, posts_t = embed_gated(env_t, tmp / "f2t", tight_plan, "verify-r1-f2t")
    from mktkb.rag.errors import BudgetLedgerInvalid
    try:
        gated_t.embed(texts)
        tight = None
    except BudgetLedgerInvalid as exc:
        tight = str(exc)
    out("F2", "tight_posts=", len(posts_t), "tight_quota=", wiring_t.attempt_budget.used("ingest-index"),
        "tight_reservations=", len([r for r in reservations(env_t.ledger) if r.get("kind") == "embedding"]),
        "tight_error=", tight)
except Exception as exc:  # noqa: BLE001
    import traceback
    out("F2", "PROBE_ERROR", repr(exc))
    traceback.print_exc()

# ============================================================ F6 + E2E
print("\n--- F6: live retrieved 从 CompletionInput.evidence 捕获（零额外付费） ---")
try:
    from mktkb.evaluation.p2_scoring import (
        EXECUTION_MODE_LIVE, build_gate_rows, build_gate_run, evaluate_p2_hard_gates,
        load_p2_gate_config, score_public_case)

    cfg = load_p2_gate_config()
    plan = P2RunPlan.from_dict(plan_dict())
    env = Env(tmp / "f6", plan)
    pin(env, mp)
    chat = UsageBackend(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
    result, build = run_e2e(env, tmp / "f6", case_id="Q01", ingest=D01, chat=chat, gate_config=cfg)
    out("F6", "status=", result.status, "stop=", result.stop_code, "requests_sent=", result.requests_sent,
        "chat_calls=", chat.call_count, "by_purpose=", chat.counts_by_purpose())
    run_dir = build.adapter.paths.run_dir
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    case_rows = [json.loads(x) for x in (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    product = case_rows[0]["turns"][0]["product"]
    cited = {str(s["source_id"]) for s in product["sources"]}
    retrieved = {u for r in product["retrieved"] for u in r["unit_ids"]}
    answer_calls = [x for x in chat.calls if x["purpose"] == "answer"]
    ev_ids = {str(v) for v in answer_calls[0]["evidence_ids"]}
    out("F6", "kind=", product["kind"], "cited=", len(cited), "retrieved=", len(retrieved),
        "cited_subset=", cited <= retrieved, "retrieved_eq_evidence_ids=", retrieved == ev_ids,
        "retrieved_eq_cited=", retrieved == cited)
    out("F6", "outbound=", build.adapter.provider_calls()["outbound_network"],
        "embedding_calls=", build.adapter.provider_calls()["embedding"],
        "rerank_calls=", build.adapter.provider_calls()["rerank"])
    cases = dataset().cases
    scored = [score_public_case(ca, row, document_codes={"D01_物品位置表.xlsx": "D01"},
                                allowed_doc_codes={"D01"}, execution_mode=EXECUTION_MODE_LIVE)
              for ca, row in zip(cases, case_rows)]
    rows = build_gate_rows(cases, scored)
    hard = evaluate_p2_hard_gates(build_gate_run(run_dir=run_dir, manifest=manifest, cases=cases,
                                                rows=rows, summary=summary),
                                  config=cfg, require_trace=False)
    out("F6", "citation_required(with retrieved)=", hard.gate_status["citation_required"])
    tampered = []
    for row in rows:
        copied = dict(row)
        outcome = dict(row.get("outcome") or {})
        if outcome.get("kind") == "answer":
            outcome["retrieved"] = []
        copied["outcome"] = outcome
        tampered.append(copied)
    hard2 = evaluate_p2_hard_gates(build_gate_run(run_dir=run_dir, manifest=manifest, cases=cases,
                                                 rows=tampered, summary=summary),
                                   config=cfg, require_trace=False)
    out("F6", "citation_required(without retrieved)=", hard2.gate_status["citation_required"],
        "hard_failures=", list(hard2.hard_failures))
    # 结构性闸门：live 不得走付费重放
    try:
        build.adapter.retrieval_candidates("q", conversation_id="c", client_request_id="r",
                                            trace_path=None, revision=None, state=None)
        replay = "NO_REFUSAL"
    except RuntimeError as exc:
        replay = "RuntimeError:" + str(exc)[:48]
    out("F6", "live_replay_guard=", replay)
    out("F6", "attempts=", {k: summary["attempts"].get(k) for k in
                           ("available", "receipt_count", "reservations", "gate_reserved",
                            "expected_reservations", "by_operation")})
    out("F6", "network=", summary["network"].get("outbound_attempts"),
        "unused=", summary["requests"].get("unused_no_paid_attempt"))
except Exception as exc:  # noqa: BLE001
    import traceback
    out("F6", "PROBE_ERROR", repr(exc))
    traceback.print_exc()

# ============================================================ F3 CLI
print("\n--- F3: CLI live 真测试（先写计划 + 置齐 env）---")
try:
    from mktkb.evaluation import cli

    env = Env(tmp / "f3", P2RunPlan.from_dict(plan_dict()))
    pin(env, mp)
    for key, value in {
        "MKTKB_MODEL_API_KEY": "verify-r1-not-a-secret",
        "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com",
        "MKTKB_MODEL_NAME": "deepseek-flash",
        "DASHSCOPE_API_KEY": "verify-r1-not-a-secret",
        "MKTKB_OCR_SECRET_ID": "verify-r1-not-a-secret",
        "MKTKB_OCR_SECRET_KEY": "verify-r1-not-a-secret",
        "MKTKB_OCR_DISABLED": "0"}.items():
        mp.setenv(key, value)
    plan_file = tmp / "f3" / "plan.json"
    plan_file.write_text(json.dumps(plan_dict()), encoding="utf-8")
    absent = tmp / "f3" / "absent-go.json"
    mp.setattr(p2a, "P2_GO_PATH", absent)
    outdir = tmp / "f3" / "cli-out"
    import io, contextlib
    buf_o, buf_e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_o), contextlib.redirect_stderr(buf_e):
        code = cli.main(["p2-run", "--plan", str(plan_file), "--out", str(outdir),
                         "--mode", "live", "--run-id", "verify-r1-cli", "--ingest", str(D01)])
    stdout = buf_o.getvalue().strip().splitlines()
    out("F3", "exit=", code, "stdout_last=", stdout[-1] if stdout else None,
        "stderr=", buf_e.getvalue().strip()[:160],
        "out_dir_created=", (outdir / "data").exists() or (outdir / "p2-run").exists())
    # 计划缺失 → plan_unreadable（而不是异常类名 / path_missing）
    buf_o, buf_e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_o), contextlib.redirect_stderr(buf_e):
        code2 = cli.main(["p2-run", "--plan", str(tmp / "f3" / "absent-plan.json"),
                          "--out", str(outdir), "--mode", "live", "--run-id", "verify-r1-cli",
                          "--ingest", str(D01)])
    out("F3", "absent_plan_exit=", code2, "stderr=", buf_e.getvalue().strip()[:120])
    # 非空但无效 JSON → plan_json_invalid；合法计划但 GO 存在（draft）→ 不同于 path_missing
    bad = tmp / "f3" / "bad.json"; bad.write_text("{not json", encoding="utf-8")
    buf_o, buf_e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_o), contextlib.redirect_stderr(buf_e):
        code3 = cli.main(["p2-run", "--plan", str(bad), "--out", str(outdir), "--mode", "live",
                          "--run-id", "verify-r1-cli", "--ingest", str(D01)])
    out("F3", "bad_json_exit=", code3, "stderr=", buf_e.getvalue().strip()[:80])
    mp.setattr(p2a, "P2_GO_PATH", REPO / "docs/reports/OBS-EVAL/P2/T206/PM/P2-LIVE-GO.CANDIDATE-DRAFT.json")
    buf_o, buf_e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_o), contextlib.redirect_stderr(buf_e):
        code4 = cli.main(["p2-run", "--plan", str(plan_file), "--out", str(outdir), "--mode", "live",
                          "--run-id", "verify-r1-cli", "--ingest", str(D01)])
    payload = stdout[-1] if stdout else ""
    out("F3", "draft_go_exit=", code4, "stdout=", (buf_o.getvalue().strip() or buf_e.getvalue().strip())[:200])
except Exception as exc:  # noqa: BLE001
    import traceback
    out("F3", "PROBE_ERROR", repr(exc))
    traceback.print_exc()

# ============================================================ F4/F5
print("\n--- F4/F5: runbook 码名 / OCR 模式门 ---")
try:
    import subprocess
    rb = (REPO / "docs/reports/OBS-EVAL/P2/T206/PM/runbook.md").read_text(encoding="utf-8")
    codes = ["path_missing", "go_expired", "go_budget_total_mismatch", "budget_stage_missing",
             "env_total_limit_missing", "attempt_quota_exhausted", "ocr_mode_plan_mismatch",
             "usage_evidence_missing", "attempt_accounting_mismatch"]
    src = "\n".join((REPO / p).read_text(encoding="utf-8")
                    for p in ("backend/src/mktkb/evaluation/p2_authorization.py",
                              "backend/src/mktkb/evaluation/p2_live.py",
                              "backend/src/mktkb/evaluation/p2_runner.py",
                              "backend/src/mktkb/live_authorization.py"))
    gomiss = [line.strip()[:90] for line in rb.splitlines() if "go_missing" in line]
    out("F4", "codes_in_runbook_missing_in_code=", [x for x in codes if x in rb and x not in src],
        "go_missing_lines=", gomiss)
    # OCR 模式门：计划项是 text 模型，但运行时 mode=table → 必须在发送前拒绝
    plan = P2RunPlan.from_dict(plan_dict())
    env = Env(tmp / "f5", plan)
    pin(env, mp)
    gate = p2_live.open_live_gate(plan, run_id="verify-r1-f5", now=NOW)
    wiring = p2_live.LiveWiring(env=p2_live.load_live_env({}, overrides=OVERRIDES), plan=plan,
                                run_id="verify-r1-f5", gate=gate,
                                ledger=p2_live.GateAttemptLedger(gate, plan),
                                attempt_budget=p2_live.AttemptBudget(plan),
                                plan_index=p2_live.PlanIndex(plan))
    wiring.ledger._on_receipt = wiring.receipts.append
    from mktkb.providers.tencent_ocr import TencentOCRClient
    from mktkb.providers.types import OCRInput
    ocr_calls: list = []
    client = TencentOCRClient(secret_id="verify-r1", secret_key="verify-r1",
                              region="ap-guangzhou", transport=ocr_transport(ocr_calls))
    gw = p2_live.GatedOcrGateway(client, wiring=wiring)
    page = OCRInput(content=(FIX / "normal" / "D09_物料领用通知.png").read_bytes(),
                    mime_type="image/png", page=1)
    ok = gw.recognize(page, mode="text")
    gw2 = p2_live.GatedOcrGateway(client, wiring=wiring)
    try:
        gw2.recognize(page, mode="table")
        mismatch = None
    except p2_live.P2LiveRefused as exc:
        mismatch = exc.code
    out("F5", "first_page_text=", ok.text[:12], "ocr_posts=", len(ocr_calls),
        "table_on_text_item=", mismatch,
        "ocr_reservations=", len([r for r in reservations(env.ledger) if r.get("kind") == "ocr"]),
        "receipts=", [(r["phase"], r["item_id"], r["charged_cny"]) for r in wiring.receipt_payload()])
except Exception as exc:  # noqa: BLE001
    import traceback
    out("F5", "PROBE_ERROR", repr(exc))
    traceback.print_exc()

# ============================================================ 安全面
print("\n--- 安全面：出站 / 共享文件 ---")
mp.undo()
files = {
    "ledger": REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl",
    "budget": REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json",
    "go": REPO / "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json",
}
for name, path in files.items():
    if path.exists():
        raw = path.read_bytes()
        out("SAFE", name, "size=", len(raw), "sha256=", hashlib.sha256(raw).hexdigest())
    else:
        out("SAFE", name, "absent=", True)
out("SAFE", "external_outbound_attempts=", len(_EXT), "detail=", _EXT[:5],
    "loopback_attempts=", len(_LOCAL))
print("\nDONE")
