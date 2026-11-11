
"""T207-FIX-LIVECAP 独立验收探针（只读复核；零真实调用）。

刻意不复用开发新增的测试模块：计划按真实计划文件的 item/price_profile 复刻，
GO/预算/账本全部在本文件内构造，出站全部由 httpx.MockTransport 接住。

运行（仓库根）：
  .venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207-FIX-LIVECAP\evidence\verify\probe-independent-livecap.py --out <json>
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
ROOT = _HERE
while ROOT.parent != ROOT and not (ROOT / "backend" / "src").is_dir():
    ROOT = ROOT.parent
for extra in (ROOT / "backend" / "src", ROOT / "backend" / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import httpx  # noqa: E402

from mktkb import live_authorization  # noqa: E402
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation import p2_contracts as c  # noqa: E402
from mktkb.evaluation import p2_live  # noqa: E402
from mktkb.evaluation import product_adapter as pa  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, validate_case  # noqa: E402
from mktkb.evaluation.p2_contracts import P2RunPlan  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
)
from mktkb.rag import RagConfig  # noqa: E402
from mktkb.rag.providers import (  # noqa: E402
    MAX_EMBEDDING_REQUEST_TOKENS,
    BailianEmbeddingProvider,
    BailianRerankProvider,
    post_counters,
    reset_post_counters,
)

NOW = datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc)
GO_ISSUED = "2026-11-19T00:00:00+00:00"
GO_EXPIRES = "2026-11-26T00:00:00+00:00"
TOTAL_LIMIT_CNY = 40.0
STAGE_LIMIT_CNY = 20.0
CENTERS = {"answer_retrieval": 8.5, "ocr": 6.5, "judge": 3.0, "independent": 2.0}
LIVE_ENV_OVERRIDES = {
    "chat_api_key": "verify-only-chat-key-not-a-secret",
    "chat_base_url": "https://api.deepseek.com",
    "chat_model": "deepseek-flash",
    "dashscope_api_key": "verify-only-dashscope-key-not-a-secret",
    "dashscope_base_url": "https://dashscope.aliyuncs.com",
    "ocr_secret_id": "verify-only-ocr-id-not-a-secret",
    "ocr_secret_key": "verify-only-ocr-key-not-a-secret",
    "ocr_region": "ap-guangzhou",
}

R4_PLAN = ROOT / "docs/reports/OBS-EVAL/P2/T207/PM/T207-plan-R4-v0_1.json"
PUB_PLAN = ROOT / "docs/reports/OBS-EVAL/P2/T207/PM/T207-plan-v0_1.json"
D01 = ROOT / "fixtures/acceptance/normal/D01_物品位置表.xlsx"
B0 = ROOT / "fixtures/evaluation/b0.jsonl"

#: 独立复算用的常量（只用于断言，不参与产品逻辑）
EMBED_RESERVE = MAX_EMBEDDING_REQUEST_TOKENS * 0.5 / 1_000_000  # 81920*0.5/1e6
RERANK_RESERVE = 30000 * 0.8 / 1_000_000  # RagConfig 默认 rerank_max_request_tokens
CHAT_RESERVE = (6144 * 2.0 + 800 * 8.0) / 1_000_000


# --------------------------------------------------------------------------- #
# 计划 / GO / 预算 / 账本（全部临时副本）
# --------------------------------------------------------------------------- #


def _plan_dict(*, with_ocr: bool) -> tuple[dict, dict]:
    r4_raw = json.loads(R4_PLAN.read_text(encoding="utf-8"))
    pub_raw = json.loads(PUB_PLAN.read_text(encoding="utf-8"))
    by_id = {item["item_id"]: item for item in pub_raw["items"]}
    items = [copy.deepcopy(r4_raw["items"][0])]  # ingest-index-embedding (requests=6)
    for item_id in ("embed-Q01-t1", "rerank-Q01-t1", "expand-Q01-t1", "answer-Q01-t1"):
        items.append(copy.deepcopy(by_id[item_id]))
    if with_ocr:
        ocr_item = next(
            item
            for item in pub_raw["items"]
            if item["operation"] == "ocr" and int(item.get("page") or 0) == 1
        )
        ocr_item = copy.deepcopy(ocr_item)
        ocr_item["case_id"] = "Q01"
        ocr_item["item_id"] = "ocr-Q01-p1"
        items.append(ocr_item)
    plan = {
        "schema_version": r4_raw["schema_version"],
        "plan_id": "P2-T207-FIXLIVECAP-VERIFY-20261120",
        "plan_version": "v0.1",
        "mode": r4_raw["mode"],
        "stage": r4_raw["stage"],
        "created_utc": "2026-11-20T00:00:00+08:00",
        "project_total_limit_cny": TOTAL_LIMIT_CNY,
        "stage_limit_cny": STAGE_LIMIT_CNY,
        "max_requests": 760,
        "cost_centers_cny": dict(CENTERS),
        "items": items,
    }
    return plan, {"r4_item_ids": [i["item_id"] for i in r4_raw["items"]][:2]}


def _live_cfg(*, max_request_cny: float) -> RagConfig:
    """与 product_adapter._start_live 同形的 live RagConfig（价格/批量用默认值即为产品值）。"""
    return RagConfig(
        provider_mode="live",
        data_dir=Path("."),
        business_date=None,
        top_k=8,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
        embedding_base_url="https://dashscope.aliyuncs.com",
        rerank_base_url="https://dashscope.aliyuncs.com",
        embedding_api_key="verify-only-embedding-key",
        rerank_api_key="verify-only-rerank-key",
        embedding_batch_size=5,
        embedding_timeout_seconds=30.0,
        rerank_timeout_seconds=30.0,
        max_request_cny=max_request_cny,
        max_retries=0,
        require_zero_retries=True,
        chat_model="",
        chat_base_url="",
        chat_api_key="",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_ledger(path: Path) -> None:
    path.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": 2.0, "source": "verify"},
                   ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _prepare(tmp: Path, *, with_ocr: bool, max_request_cny: float) -> dict[str, Any]:
    plan_dict, _ = _plan_dict(with_ocr=with_ocr)
    plan = P2RunPlan.from_dict(plan_dict)
    ledger = tmp / "live-ledger.jsonl"
    budget = tmp / "budget.json"
    go = tmp / "P2-LIVE-GO.json"
    _write_ledger(ledger)
    _write_json(
        budget,
        {
            "limit_cny": TOTAL_LIMIT_CNY,
            "historical_conservative_accounted_cny": 2.0,
            "stages": {"S2-DEV": 18.0, "P2-LIVE": STAGE_LIMIT_CNY},
        },
    )
    _write_json(
        go,
        {
            "document": "P2-LIVE-GO",
            "schema_version": "p2-live-go/v0.1",
            "stage": "P2-LIVE",
            "authorization": "INDEPENDENT-VERIFY-MOCK-GO（零真实调用）",
            "issued_by": "verify-probe",
            "nonce": "verify-livecap-nonce-0123456789abcdef",
            "issued_utc": GO_ISSUED,
            "expires_utc": GO_EXPIRES,
            "budget_ledger_path": str(ledger),
            "budget_ledger_sha256": live_authorization.historical_prefix_sha256(ledger),
            "budget_total_limit_cny": TOTAL_LIMIT_CNY,
            "scope": {
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
                "operations": list(plan.operations),
                "cost_centers_cny": dict(CENTERS),
                "stage_limits_cny": {"P2-LIVE": STAGE_LIMIT_CNY},
                "max_requests": int(plan.max_requests),
                "max_request_cny": float(max_request_cny),
            },
        },
    )
    return {"plan": plan, "ledger": ledger, "budget": budget, "go": go}


class _Patch:
    def __init__(self) -> None:
        self._saved: list[tuple[Any, str, Any]] = []
        self._env: list[tuple[str, str | None]] = []

    def attr(self, obj: Any, name: str, value: Any) -> None:
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def env(self, name: str, value: str) -> None:
        self._env.append((name, os.environ.get(name)))
        os.environ[name] = value

    def undo(self) -> None:
        for obj, name, value in reversed(self._saved):
            setattr(obj, name, value)
        for name, value in reversed(self._env):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _legacy_resolver(config: Any, *, plan_peak_cny: float, authorization_cny: float):
    """旧接线语义：effective 就是计划串行峰值，不看 provider 单次预留、也不 fail closed。"""
    return p2_live.RequestCeiling(
        plan_peak_cny=float(plan_peak_cny),
        provider_bounds_cny={},
        authorization_cny=float(authorization_cny),
        effective_cny=float(plan_peak_cny),
    )


# --------------------------------------------------------------------------- #
# fake transports
# --------------------------------------------------------------------------- #


class _UsageChatBackend(MockChatBackend):
    def _completion(self, request: httpx.Request, content: str, *, call: int) -> httpx.Response:
        response = super()._completion(request, content, call=call)
        payload = json.loads(response.content.decode("utf-8"))
        payload["usage"] = {
            "prompt_tokens": 64,
            "completion_tokens": 32,
            "total_tokens": 96,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 64,
        }
        return httpx.Response(200, json=payload, request=request)


def _embedding_transport(calls: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        texts = list(body.get("input") or ())
        dims = int(body.get("dimensions") or 1024)
        calls.append({"texts": len(texts)})
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": index, "embedding": [0.01] * dims}
                    for index in range(len(texts))
                ],
                "usage": {"total_tokens": 40},
                "id": "verify-emb-" + str(len(calls)),
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def _rerank_transport(calls: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        docs = list((body.get("input") or {}).get("documents") or ())
        calls.append({"documents": len(docs)})
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": index, "relevance_score": 0.9 - index * 0.01}
                        for index in range(len(docs))
                    ]
                },
                "usage": {"total_tokens": 80},
                "request_id": "verify-rerank-" + str(len(calls)),
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def _ocr_transport(calls: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"action": request.headers.get("X-TC-Action")})
        return httpx.Response(
            200,
            json={
                "Response": {
                    "TextDetections": [
                        {
                            "DetectedText": "领取活动物料需先填写物料领用单",
                            "Confidence": 99,
                            "Polygon": [
                                {"X": 10, "Y": 10},
                                {"X": 200, "Y": 10},
                                {"X": 200, "Y": 40},
                                {"X": 10, "Y": 40},
                            ],
                        }
                    ],
                    "RequestId": "verify-ocr-unit",
                }
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def _dataset() -> P2RunDataset:
    rows = [json.loads(line) for line in B0.read_text(encoding="utf-8").splitlines() if line.strip()]
    case = CaseSpec.from_dict(next(row for row in rows if row["case_id"] == "Q01"))
    validate_case(case)
    return P2RunDataset(
        visibility="public",
        cases=(case,),
        identity={
            "dataset_version": "p2-livecap-verify-v1",
            "label_version": "b0-2026-11-04",
            "suite": "b0",
            "manifest_sha256": "b" * 64,
            "case_count": 1,
        },
    )


def _run_case(*, label: str, with_ocr: bool, go_cap: float, legacy: bool) -> dict[str, Any]:
    tmp = Path(tempfile.mkdtemp(prefix="t207-livecap-verify-"))
    patch = _Patch()
    payload: dict[str, Any] = {
        "label": label,
        "plan": "with_ocr_page1" if with_ocr else "no_ocr",
        "go_max_request_cny": float(go_cap),
        "wiring": "legacy(emulated)" if legacy else "fixed(head)",
    }
    replace_calls: list = []
    real_replace = pa.replace

    def _counting_replace(obj, **kwargs):
        replace_calls.append(sorted(kwargs))
        return real_replace(obj, **kwargs)

    try:
        prepared = _prepare(tmp, with_ocr=with_ocr, max_request_cny=go_cap)
        patch.attr(p2a, "P2_LEDGER_PATH", prepared["ledger"])
        patch.attr(p2a, "P2_BUDGET_PATH", prepared["budget"])
        patch.attr(p2a, "P2_GO_PATH", prepared["go"])
        patch.env(live_authorization.TOTAL_LIMIT_ENV, str(TOTAL_LIMIT_CNY))
        patch.attr(pa, "replace", _counting_replace)
        if legacy:
            patch.attr(p2_live, "resolve_request_ceiling", _legacy_resolver)

        plan = prepared["plan"]
        payload["plan_peak_cny"] = float(plan.reserve_peak_cny)
        payload["plan_total_requests"] = int(plan.total_requests)
        payload["item_bound_cny"] = {item.item_id: float(item.bound_cny) for item in plan.items}

        gate = p2_live.open_live_gate(plan, run_id="p2-livecap-verify", now=NOW)
        payload["go_authorization_cny"] = float(gate.authorization.max_request_cny)

        embedding_calls: list = []
        rerank_calls: list = []
        ocr_calls: list = []
        chat = _UsageChatBackend(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
        reset_post_counters()

        async def go():
            return await p2_live.run_live_p2(
                plan,
                run_id="p2-livecap-verify",
                out_dir=tmp / "run",
                dataset=_dataset(),
                ingest_plan=P2IngestPlan(sources=(IngestSource(path=D01),), label="t207-livecap-verify"),
                gate=gate,
                env={"MKTKB_OCR_DISABLED": "0"},
                env_overrides=LIVE_ENV_OVERRIDES,
                transports={
                    "chat": chat.transport,
                    "embedding": _embedding_transport(embedding_calls),
                    "rerank": _rerank_transport(rerank_calls),
                    "ocr": _ocr_transport(ocr_calls),
                },
                now=NOW,
            )

        try:
            import asyncio

            result, build = asyncio.run(go())
        except p2_live.P2LiveConfigError as exc:
            payload.update(
                {
                    "refused": True,
                    "refused_code": str(exc.code),
                    "refused_detail": str(exc.detail),
                    "embedding_posts": len(embedding_calls),
                    "rerank_posts": len(rerank_calls),
                    "ocr_posts": len(ocr_calls),
                    "chat_posts": int(chat.call_count),
                    "product_post_counters": post_counters()["attempts"],
                    "ledger_reserved": 0,
                    "artifacts": [],
                    "replace_calls": list(replace_calls),
                }
            )
            payload["ledger_reserved"] = len(
                [
                    row
                    for row in _events(prepared["ledger"])
                    if row.get("event") == "reserved"
                ]
            )
            payload["ledger_event_counts"] = _event_counts(prepared["ledger"])
            payload["ledger_reserved_rows"] = _reserved_rows(prepared["ledger"])
            payload["ledger_result_rows"] = _result_rows(prepared["ledger"])
            payload["artifacts"] = (
                sorted(str(p.relative_to(tmp / "run")) for p in (tmp / "run").rglob("*") if p.is_file())
                if (tmp / "run").is_dir()
                else []
            )
            return payload

        status = build.adapter.index_status()
        manifest_candidates = sorted((tmp / "run").rglob("run_manifest.json"))
        manifest = (
            json.loads(manifest_candidates[0].read_text(encoding="utf-8"))
            if manifest_candidates
            else {}
        )
        summary_candidates = sorted((tmp / "run").rglob("summary.json"))
        summary_path = summary_candidates[0] if summary_candidates else None
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8")) if summary_path is not None else {}
        )
        live_block = (summary.get("providers") or {}).get("live") or {}
        payload.update(
            {
                "refused": False,
                "run_status": result.status,
                "stop_code": result.stop_code,
                "requests_sent": int(result.requests_sent),
                "embedding_posts": len(embedding_calls),
                "rerank_posts": len(rerank_calls),
                "ocr_posts": len(ocr_calls),
                "chat_posts": int(chat.call_count),
                "product_post_counters": post_counters()["attempts"],
                "ledger_reserved": len(
                    [row for row in _events(prepared["ledger"]) if row.get("event") == "reserved"]
                ),
                "index_status": {
                    "ready": status.get("ready"),
                    "degraded": list(status.get("degraded") or ()),
                    "error_code": status.get("error_code"),
                    "documents": status.get("documents"),
                    "chunks": status.get("chunks"),
                },
                "config_max_request_cny": float(build.adapter._qa.config.max_request_cny),
                "request_ceiling": build.wiring.request_ceiling,
                "summary_request_ceiling": live_block.get("request_ceiling"),
                "summary_calls": live_block.get("calls"),
                "manifest_request_ceiling": ((manifest.get("providers") or {}).get("live") or {}).get("request_ceiling"),
                "outbound_network": int(build.adapter.provider_calls()["outbound_network"]),
                "replace_calls": list(replace_calls),
                "summary_path": str(summary_path.relative_to(tmp)) if summary_path else None,
                "ledger_event_counts": _event_counts(prepared["ledger"]),
                "ledger_reserved_rows": _reserved_rows(prepared["ledger"]),
                "ledger_result_rows": _result_rows(prepared["ledger"]),
                "artifacts": sorted(
                    str(p.relative_to(tmp / "run")) for p in (tmp / "run").rglob("*") if p.is_file()
                )
                if (tmp / "run").is_dir()
                else [],
            }
        )
        return payload
    finally:
        patch.undo()
        shutil.rmtree(tmp, ignore_errors=True)


def _reserved_rows(path: Path) -> list:
    rows = []
    for row in _events(path):
        if row.get("event") != "reserved":
            continue
        rows.append(
            {
                key: row.get(key)
                for key in ("kind", "provider", "model", "max_cny", "status", "item_id")
                if key in row
            }
        )
    return rows


def _result_rows(path: Path) -> list:
    rows = []
    for row in _events(path):
        if row.get("event") != "result":
            continue
        rows.append(
            {
                key: row.get(key)
                for key in ("kind", "status", "error_code", "http_status")
                if key in row
            }
        )
    return rows


def _event_counts(path: Path) -> dict:
    counts: dict = {}
    for row in _events(path):
        key = str(row.get("event"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _events(path: Path) -> list:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# 1. 数值推导（真实计划文件 + 真实 provider 常量）
# --------------------------------------------------------------------------- #


def _derivation() -> dict[str, Any]:
    cfg = _live_cfg(max_request_cny=0.018688)
    bounds = p2_live.provider_single_request_bounds(cfg)
    r4 = P2RunPlan.from_dict(json.loads(R4_PLAN.read_text(encoding="utf-8")))
    pub = P2RunPlan.from_dict(json.loads(PUB_PLAN.read_text(encoding="utf-8")))
    out: dict[str, Any] = {
        "constants": {
            "MAX_EMBEDDING_REQUEST_TOKENS": MAX_EMBEDDING_REQUEST_TOKENS,
            "embedding_price_per_million_cny": cfg.embedding_price_per_million_cny,
            "rerank_max_request_tokens": cfg.rerank_max_request_tokens,
            "rerank_price_per_million_cny": cfg.rerank_price_per_million_cny,
            "chat_prompt_tokens_cap": 6144,
            "chat_completion_tokens_cap": 800,
        },
        "recomputed": {
            "embedding": EMBED_RESERVE,
            "rerank": RERANK_RESERVE,
            "chat": CHAT_RESERVE,
        },
        "provider_single_request_bounds": dict(bounds),
        "bounds_match_recomputed": {
            "embedding": abs(bounds["embedding"] - EMBED_RESERVE) < 1e-15,
            "rerank": abs(bounds["rerank"] - RERANK_RESERVE) < 1e-15,
            "chat": abs(bounds["chat"] - CHAT_RESERVE) < 1e-15,
        },
        "real_plans": {},
    }
    for name, plan in (("R4(no_ocr)", r4), ("public(12_ocr_pages)", pub)):
        try:
            ceiling = p2_live.resolve_request_ceiling(
                cfg, plan_peak_cny=float(plan.reserve_peak_cny), authorization_cny=0.5
            )
            entry = {
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
                "items": len(plan.items),
                "total_requests": int(plan.total_requests),
                "ocr_items": len([i for i in plan.items if i.operation == "ocr"]),
                "reserve_peak_cny": float(plan.reserve_peak_cny),
                "refused": False,
                "effective_max_request_cny": ceiling.effective_cny,
                "effective_equals_plan_peak": abs(ceiling.effective_cny - float(plan.reserve_peak_cny)) < 1e-15,
                "effective_le_authorization": ceiling.effective_cny <= ceiling.authorization_cny,
                "replace_would_happen": ceiling.effective_cny != float(plan.reserve_peak_cny),
            }
        except p2_live.P2LiveConfigError as exc:
            entry = {
                "plan_id": plan.plan_id,
                "reserve_peak_cny": float(plan.reserve_peak_cny),
                "refused": True,
                "refused_code": str(exc.code),
            }
        out["real_plans"][name] = entry

    # 边界：GO 上限恰好等于 embedding 单次预留 ⇒ 允许；低 1e-6 ⇒ 拒绝。
    edge = {}
    for label, cap in (("cap_eq_embedding", EMBED_RESERVE), ("cap_below_embedding", EMBED_RESERVE - 1e-6)):
        try:
            ceiling = p2_live.resolve_request_ceiling(
                cfg, plan_peak_cny=0.018688, authorization_cny=cap
            )
            edge[label] = {"refused": False, "effective": ceiling.effective_cny, "cap": cap}
        except p2_live.P2LiveConfigError as exc:
            edge[label] = {"refused": True, "code": str(exc.code), "cap": cap}
    out["go_cap_edges"] = edge
    return out


# --------------------------------------------------------------------------- #
# 2. provider 层：旧上限 vs 新上限（真实 provider 类 + MockTransport）
# --------------------------------------------------------------------------- #


def _provider_guard() -> dict[str, Any]:
    results: dict[str, Any] = {"embedding": {}, "rerank": {}}

    for label, cap in (
        ("plan_peak_0.018688", 0.018688),
        ("ceiling_0.04096", EMBED_RESERVE),
        ("ceiling_0.024", RERANK_RESERVE),
    ):
        posts: list = []
        transport = _embedding_transport(posts)
        provider = BailianEmbeddingProvider(
            _live_cfg(max_request_cny=cap),
            budget=None,
            require_budget=False,
            settlement_policy=None,
            transport=transport,
        )
        try:
            provider.embed(["物料领用单"], purpose="query")
            results["embedding"][label] = {"raised": None, "posts": len(posts)}
        except Exception as exc:  # noqa: BLE001 - 探针只记录类型与消息
            results["embedding"][label] = {
                "raised": type(exc).__name__,
                "message": str(exc),
                "posts": len(posts),
            }
        finally:
            provider.close()

    for label, cap in (
        ("plan_peak_0.018688", 0.018688),
        ("ceiling_0.024", RERANK_RESERVE),
    ):
        posts = []

        def handler(request: httpx.Request) -> httpx.Response:
            posts.append(1)
            docs = list((json.loads(request.content.decode("utf-8")).get("input") or {}).get("documents") or ())
            return httpx.Response(
                200,
                json={
                    "output": {
                        "results": [
                            {"index": index, "relevance_score": 0.5}
                            for index in range(len(docs))
                        ]
                    },
                    "usage": {"total_tokens": 10},
                    "request_id": "verify-rerank",
                },
                request=request,
            )

        provider = BailianRerankProvider(
            _live_cfg(max_request_cny=cap),
            budget=None,
            require_budget=False,
            settlement_policy=None,
            transport=httpx.MockTransport(handler),
        )
        try:
            provider.rerank("物料", ["甲", "乙"])
            results["rerank"][label] = {"raised": None, "posts": len(posts)}
        except Exception as exc:  # noqa: BLE001
            results["rerank"][label] = {
                "raised": type(exc).__name__,
                "message": str(exc),
                "posts": len(posts),
            }
        finally:
            provider.close()
    return results


def _ingest_swallow_control() -> dict:
    """对照：不经 run_live_p2 的显式 start，run_p2 会把同一拒绝吞成 ingest_failed。"""
    tmp = Path(tempfile.mkdtemp(prefix="t207-livecap-control-"))
    patch = _Patch()
    try:
        prepared = _prepare(tmp, with_ocr=False, max_request_cny=0.02)
        patch.attr(p2a, "P2_LEDGER_PATH", prepared["ledger"])
        patch.attr(p2a, "P2_BUDGET_PATH", prepared["budget"])
        patch.attr(p2a, "P2_GO_PATH", prepared["go"])
        patch.env(live_authorization.TOTAL_LIMIT_ENV, str(TOTAL_LIMIT_CNY))
        plan = prepared["plan"]
        gate = p2_live.open_live_gate(plan, run_id="p2-livecap-control", now=NOW)
        live_env = p2_live.load_live_env({"MKTKB_OCR_DISABLED": "0"}, overrides=LIVE_ENV_OVERRIDES)
        dataset = _dataset()
        ingest_plan = P2IngestPlan(
            sources=(IngestSource(path=D01),), label="t207-livecap-control"
        )
        build = p2_live.build_live_adapter(
            plan,
            gate=gate,
            env=live_env,
            run_id="p2-livecap-control",
            out_dir=tmp / "run",
            dataset=dataset,
            ingest_plan=ingest_plan,
            transports={
                "chat": _UsageChatBackend().transport,
                "embedding": _embedding_transport([]),
                "rerank": _rerank_transport([]),
                "ocr": _ocr_transport([]),
            },
        )
        from mktkb.evaluation import p2_runner

        async def go():
            try:
                return await p2_runner.run_p2(
                    plan,
                    adapter=build.adapter,
                    authorization=gate.authorization,
                    dataset=dataset,
                    gate=gate,
                    run_id="p2-livecap-control",
                    settle_evidence=p2_live.make_settle_evidence(build.adapter),
                    now=NOW,
                )
            finally:
                await build.adapter.close()

        try:
            result = asyncio.run(go())
        except p2_live.P2LiveConfigError as exc:
            return {"raised": str(exc.code), "stop_code": None, "status": None}
        return {
            "raised": None,
            "status": getattr(result, "status", None),
            "stop_code": getattr(result, "stop_code", None),
            "requests_sent": int(getattr(result, "requests_sent", 0)),
        }
    finally:
        patch.undo()
        shutil.rmtree(tmp, ignore_errors=True)


def _checks(report: dict) -> dict:
    runs = {run["label"]: run for run in report["runs"]}
    legacy = runs["no_ocr / legacy(plan_peak)"]
    fixed = runs["no_ocr / fixed(head)"]
    refused = runs["no_ocr / fixed(head) / GO cap 0.02"]
    ocr_legacy = runs["ocr_page1 / legacy(plan_peak)"]
    ocr_fixed = runs["ocr_page1 / fixed(head)"]
    deriv = report["derivation"]
    guard = report["provider_guard"]
    checks = {
        "derivation_bounds_follow_provider_formulas": all(deriv["bounds_match_recomputed"].values()),
        "derivation_r4_effective_is_embedding_reserve": (
            abs(deriv["real_plans"]["R4(no_ocr)"]["effective_max_request_cny"] - EMBED_RESERVE) < 1e-15
            and deriv["real_plans"]["R4(no_ocr)"]["effective_le_authorization"]
        ),
        "derivation_public_plan_unchanged": (
            deriv["real_plans"]["public(12_ocr_pages)"]["effective_equals_plan_peak"]
            and not deriv["real_plans"]["public(12_ocr_pages)"]["replace_would_happen"]
        ),
        "go_cap_edges": (
            not deriv["go_cap_edges"]["cap_eq_embedding"]["refused"]
            and deriv["go_cap_edges"]["cap_below_embedding"]["refused"]
        ),
        "provider_refuses_plan_peak_cap": (
            guard["embedding"]["plan_peak_0.018688"]["raised"] is not None
            and guard["embedding"]["plan_peak_0.018688"]["posts"] == 0
            and guard["rerank"]["plan_peak_0.018688"]["raised"] is not None
            and guard["rerank"]["plan_peak_0.018688"]["posts"] == 0
        ),
        "provider_accepts_effective_cap": (
            guard["embedding"]["ceiling_0.04096"]["raised"] is None
            and guard["embedding"]["ceiling_0.04096"]["posts"] == 1
            and guard["rerank"]["ceiling_0.024"]["raised"] is None
            and guard["rerank"]["ceiling_0.024"]["posts"] == 1
        ),
        "legacy_no_ocr_sends_nothing": (
            legacy["embedding_posts"] == 0
            and legacy["rerank_posts"] == 0
            and "embedding_error" in legacy["index_status"]["degraded"]
            and legacy["config_max_request_cny"] == 0.018688
        ),
        "fixed_no_ocr_sends_embeddings": (
            fixed["embedding_posts"] == 3
            and fixed["rerank_posts"] == 1
            and fixed["index_status"]["degraded"] == []
            and fixed["run_status"] == "succeeded"
            and abs(fixed["config_max_request_cny"] - EMBED_RESERVE) < 1e-15
            and abs(
                fixed["summary_request_ceiling"]["effective_max_request_cny"] - EMBED_RESERVE
            ) < 1e-15
            and fixed["manifest_request_ceiling"] is not None
            and fixed["outbound_network"] == 0
        ),
        "go_cap_insufficient_fails_closed": (
            refused["refused"]
            and refused["refused_code"] == "live_request_ceiling_insufficient"
            and refused["embedding_posts"] == 0
            and refused["rerank_posts"] == 0
            and refused["chat_posts"] == 0
            and refused["ledger_reserved"] == 0
            and refused["artifacts"] == []
        ),
        "without_explicit_start_error_is_swallowed": (
            report["ingest_swallow_control"]["raised"] is None
            and report["ingest_swallow_control"]["stop_code"] == "ingest_failed"
        ),
        "ocr_plan_counts_unchanged": (
            ocr_legacy["embedding_posts"] == ocr_fixed["embedding_posts"] == 3
            and ocr_legacy["rerank_posts"] == ocr_fixed["rerank_posts"] == 1
            and ocr_legacy["chat_posts"] == ocr_fixed["chat_posts"] == 1
            and ocr_legacy["ledger_reserved"] == ocr_fixed["ledger_reserved"] == 5
            and ocr_legacy["config_max_request_cny"] == ocr_fixed["config_max_request_cny"] == 0.5
            and ocr_fixed["replace_calls"] == []
            and ocr_legacy["replace_calls"] == []
        ),
    }
    return {
        "checks": checks,
        "failed": [name for name, ok in checks.items() if not ok],
        "all_pass": all(checks.values()),
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="T207-FIX-LIVECAP 独立验收探针")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    report: dict[str, Any] = {
        "schema": "t207-fix-livecap-independent-verify/v1",
        "real_calls": 0,
        "inputs": {
            "r4_plan": str(R4_PLAN.relative_to(ROOT)),
            "public_plan": str(PUB_PLAN.relative_to(ROOT)),
            "d01": str(D01.relative_to(ROOT)),
        },
        "derivation": _derivation(),
        "provider_guard": _provider_guard(),
        "runs": [
            _run_case(label="no_ocr / legacy(plan_peak)", with_ocr=False, go_cap=0.5, legacy=True),
            _run_case(label="no_ocr / fixed(head)", with_ocr=False, go_cap=0.5, legacy=False),
            _run_case(label="no_ocr / fixed(head) / GO cap 0.02", with_ocr=False, go_cap=0.02, legacy=False),
            _run_case(label="ocr_page1 / legacy(plan_peak)", with_ocr=True, go_cap=0.5, legacy=True),
            _run_case(label="ocr_page1 / fixed(head)", with_ocr=True, go_cap=0.5, legacy=False),
        ],
    }
    report["ingest_swallow_control"] = _ingest_swallow_control()
    report["checks"] = _checks(report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
