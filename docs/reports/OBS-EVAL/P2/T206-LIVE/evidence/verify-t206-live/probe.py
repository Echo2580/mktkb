
"""P2-T206-LIVE 独立验收探针（证伪优先；零真实调用）。

只读产品/评测代码，自建 tmp GO/预算/账本副本（monkeypatch 固定路径常量），
用 httpx.MockTransport 接住全部 provider 出站，并在进程内加一层 socket 闸门计数。
产出：02-cli-refusals.txt / 03-live-probes.txt 的原文。
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
FIX = ROOT / "fixtures"
EV = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T206-LIVE" / "evidence" / "verify-t206-live"
PILOT_PLAN = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T206" / "PM" / "p2-pilot-plan-v0_1.json"

# ---------------------------------------------------------------- socket 闸门
EXTERNAL: list[str] = []
LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def _is_local(host) -> bool:
    text = str(host)
    return text in LOOPBACK or text.startswith("127.") or text.startswith("\\\\.") or text.startswith("/")


_real_connect = socket.socket.connect


def _connect(self, address, *a, **k):
    if not _is_local(address[0] if isinstance(address, tuple) else address):
        EXTERNAL.append(f"socket.connect {address!r}")
        raise RuntimeError("external outbound blocked by verifier")
    return _real_connect(self, address, *a, **k)


socket.socket.connect = _connect
_real_gai = socket.getaddrinfo


def _gai(host, *a, **k):
    if not _is_local(host):
        EXTERNAL.append(f"socket.getaddrinfo {host!r}")
        raise RuntimeError("external dns blocked by verifier")
    return _real_gai(host, *a, **k)


socket.getaddrinfo = _gai

import httpx  # noqa: E402


def _sync_blocked(self, request):
    EXTERNAL.append(f"httpx.HTTPTransport {request.url}")
    raise RuntimeError("external httpx blocked by verifier")


async def _async_blocked(self, request):
    EXTERNAL.append(f"httpx.AsyncHTTPTransport {request.url}")
    raise RuntimeError("external httpx blocked by verifier")


httpx.HTTPTransport.handle_request = _sync_blocked
httpx.AsyncHTTPTransport.handle_async_request = _async_blocked

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
    ProductEvalAdapter,
)

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
TOTAL = 40.0
STAGE = 20.0
CENTERS = {"answer_retrieval": 9.0, "ocr": 6.0, "judge": 3.0, "independent": 2.0}
D01 = FIX / "acceptance" / "normal" / "D01_物品位置表.xlsx"
D09 = FIX / "acceptance" / "normal" / "D09_物料领用通知.png"
B0 = FIX / "evaluation" / "b0.jsonl"
OVERRIDES = {
    "chat_api_key": "verify-fake-key",
    "chat_base_url": "https://api.deepseek.com",
    "chat_model": "deepseek-flash",
    "dashscope_api_key": "verify-fake-key",
    "dashscope_base_url": "https://dashscope.aliyuncs.com",
    "ocr_secret_id": "verify-fake-id",
    "ocr_secret_key": "verify-fake-key",
    "ocr_region": "ap-guangzhou",
}


def out(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


# ---------------------------------------------------------------- 计划/GO 副本
PILOT = json.loads(PILOT_PLAN.read_text(encoding="utf-8"))
PROFILES = {item["item_id"]: item for item in PILOT["items"]}


def plan_dict(*, include_expansion: bool = True, ingest_requests: int = 8, case_id: str = "Q01") -> dict:
    header = {k: v for k, v in PILOT.items() if k != "items"}
    items = []
    for item_id in ("ingest-index-embedding", "embed-Q01-t1", "rerank-Q01-t1", "answer-Q01-t1", "ocr-Q37-p1"):
        item = copy.deepcopy(PROFILES[item_id])
        if item_id == "ingest-index-embedding":
            item["requests"] = ingest_requests
        if case_id != "Q01":
            item["case_id"] = case_id
            item["item_id"] = item["item_id"].replace("Q01", case_id)
        items.append(item)
    if include_expansion:
        expansion = copy.deepcopy(PROFILES["expand-Q01-t1"])
        if case_id != "Q01":
            expansion["case_id"] = case_id
            expansion["item_id"] = expansion["item_id"].replace("Q01", case_id)
        items.append(expansion)
    header["items"] = items
    return header


def build_plan(**kwargs) -> P2RunPlan:
    return P2RunPlan.from_dict(plan_dict(**kwargs))


def write_fixtures(root: Path, plan: P2RunPlan) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    ledger = root / "live-ledger.jsonl"
    budget = root / "budget.json"
    go = root / "P2-LIVE-GO.json"
    ledger.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": 2.0, "source": "verify"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    budget.write_text(
        json.dumps(
            {
                "limit_cny": TOTAL,
                "historical_conservative_accounted_cny": 2.0,
                "stages": {"S2-DEV": 18.0, "P2-LIVE": STAGE},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    go.write_text(
        json.dumps(
            {
                "document": "P2-LIVE-GO",
                "schema_version": "p2-live-go/v0.1",
                "stage": "P2-LIVE",
                "authorization": "VERIFY-T206-LIVE（零真实调用）",
                "issued_by": "verify-assistant",
                "nonce": "verify-t206-live-nonce-0123456789",
                "issued_utc": "2026-11-19T00:00:00+00:00",
                "expires_utc": "2026-11-20T00:00:00+00:00",
                "budget_ledger_path": str(ledger),
                "budget_ledger_sha256": live_authorization.historical_prefix_sha256(ledger),
                "budget_total_limit_cny": TOTAL,
                "scope": {
                    "plan_id": plan.plan_id,
                    "plan_sha256": plan.plan_sha256,
                    "operations": list(plan.operations),
                    "cost_centers_cny": dict(CENTERS),
                    "stage_limits_cny": {"P2-LIVE": STAGE},
                    "max_requests": int(plan.max_requests),
                    "max_request_cny": 0.5,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    p2a.P2_LEDGER_PATH = ledger
    p2a.P2_BUDGET_PATH = budget
    p2a.P2_GO_PATH = go
    os.environ[live_authorization.TOTAL_LIMIT_ENV] = str(TOTAL)
    return {"ledger": ledger, "budget": budget, "go": go}


# ---------------------------------------------------------------- fake transports
class UsageChat(MockChatBackend):
    def _completion(self, request, content, *, call):
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


class NoUsageChat(MockChatBackend):
    def _completion(self, request, content, *, call):
        response = super()._completion(request, content, call=call)
        payload = json.loads(response.content.decode("utf-8"))
        payload.pop("usage", None)
        return httpx.Response(200, json=payload, request=request)


def embedding_transport(log):
    def handler(request):
        body = json.loads(request.content.decode("utf-8"))
        texts = list(body.get("input") or ())
        dims = int(body.get("dimensions") or 1024)
        log.append({"texts": len(texts)})
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": i, "embedding": [0.01] * dims}
                    for i in range(len(texts))
                ],
                "usage": {"total_tokens": 40},
                "id": f"emb-{len(log)}",
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def rerank_transport(log):
    def handler(request):
        body = json.loads(request.content.decode("utf-8"))
        docs = list((body.get("input") or {}).get("documents") or ())
        log.append({"documents": len(docs)})
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": i, "relevance_score": 0.9 - i * 0.01} for i in range(len(docs))
                    ]
                },
                "usage": {"total_tokens": 80},
                "request_id": f"rerank-{len(log)}",
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def ocr_transport(log):
    def handler(request):
        log.append({"action": request.headers.get("X-TC-Action")})
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
                    "RequestId": "ocr-verify-1",
                }
            },
            request=request,
        )

    return httpx.MockTransport(handler)


def dataset(case: CaseSpec | None = None) -> P2RunDataset:
    if case is None:
        rows = [json.loads(line) for line in B0.read_text(encoding="utf-8").splitlines() if line.strip()]
        case = CaseSpec.from_dict(next(row for row in rows if row["case_id"] == "Q01"))
    validate_case(case)
    return P2RunDataset(
        visibility="public",
        cases=(case,),
        identity={
            "dataset_version": "verify-t206-live-v1",
            "label_version": "b0-2026-11-04",
            "suite": "b0",
            "manifest_sha256": "a" * 64,
            "case_count": 1,
        },
    )


def run_live(root: Path, *, chat, ingest=D01, include_expansion=True, ingest_requests=8, run_id="verify-live", case=None):
    case_id = case.case_id if case is not None else "Q01"
    plan = build_plan(include_expansion=include_expansion, ingest_requests=ingest_requests, case_id=case_id)
    paths = write_fixtures(root, plan)
    gate = p2_live.open_live_gate(plan, run_id=run_id, now=NOW)
    logs = {"embedding": [], "rerank": [], "ocr": []}
    transports = {
        "chat": chat.transport,
        "embedding": embedding_transport(logs["embedding"]),
        "rerank": rerank_transport(logs["rerank"]),
        "ocr": ocr_transport(logs["ocr"]),
    }
    ingest_plan = P2IngestPlan(sources=(IngestSource(path=ingest),), label="verify") if ingest else None

    async def go():
        return await p2_live.run_live_p2(
            plan,
            run_id=run_id,
            out_dir=root / "run",
            dataset=dataset(case),
            ingest_plan=ingest_plan,
            gate=gate,
            env={"MKTKB_OCR_DISABLED": "0"},
            env_overrides=OVERRIDES,
            transports=transports,
            now=NOW,
        )

    result, build = asyncio.run(go())
    return result, build, gate, plan, paths, logs


def events(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------- A. 默认 mock
def probe_default_mock(tmp: Path) -> None:
    out("A 默认 mock 安全（构造函数层）")
    adapter = ProductEvalAdapter(tmp / "mock-run")
    print("mode =", adapter.mode, "| is_mock =", adapter.is_mock,
          "| turn_usage =", adapter.turn_usage(), "| receipts =", adapter.attempt_receipts())
    for kwargs, label in (
        ({"mode": "live"}, "mode=live 无 wiring"),
        ({"mode": "mock", "live_wiring": object()}, "mode=mock 带 wiring"),
        ({"mode": "dry-run"}, "mode=dry-run"),
    ):
        try:
            ProductEvalAdapter(tmp / "bad", **kwargs)
            print(label, "-> 未拒绝 <<< 异常")
        except ValueError as exc:
            print(label, "-> ValueError:", exc)
    from mktkb.evaluation import cli
    args = cli.build_parser().parse_args(
        ["p2-run", "--plan", "x.json", "--out", "y", "--ingest", "z"]
    )
    print("CLI 默认 --mode =", args.mode, "| --run-id =", args.run_id)
    print("EXTERNAL =", EXTERNAL)


# ---------------------------------------------------------------- B. live 端到端
def probe_live_e2e(tmp: Path) -> None:
    out("B live 端到端（fake transport + 真实 P2Gate/真实 provider 编解码）")
    chat = UsageChat(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
    result, build, gate, plan, paths, logs = run_live(tmp / "e2e", chat=chat)
    receipts = build.wiring.receipt_payload()
    settled = [r for r in receipts if r["phase"] == "settle"]
    reservations = [e for e in events(paths["ledger"]) if e.get("event") == "reserved"]
    results = [e for e in events(paths["ledger"]) if e.get("event") == "result"]
    print("status/stop/production_ready:", result.status, result.stop_code, result.production_ready)
    print("requests planned/reserved/sent:", result.requests_planned, result.requests_reserved, result.requests_sent)
    print("chat purposes:", chat.counts_by_purpose(), "| chat calls:", chat.call_count)
    print("receipts:", len(receipts), "| settled:", len(settled), "| operations:", sorted({r['operation'] for r in settled}))
    print("reservations/results in ledger:", len(reservations), len(results),
          "| unique:", len({r['reservation_id'] for r in reservations}))
    print("all reservations have center:", all(r.get("cost_center") for r in reservations))
    print("by_center_cny:", json.dumps(result.by_center_cny, ensure_ascii=False, sort_keys=True))
    providers = build.adapter.provider_calls()
    print("outbound_network:", providers["outbound_network"],
          "| transport_outbound:", providers["network"]["transport_outbound"],
          "| mock_intercepted:", providers["network"]["mock_intercepted"])
    summary = json.loads((build.adapter.paths.run_dir / "summary.json").read_text(encoding="utf-8"))
    print("summary.execution:", summary["execution"],
          "| gate_reserved:", summary["attempts"]["gate_reserved"],
          "| expected:", summary["attempts"]["expected_reservations"])
    print("summary.requests:", json.dumps(summary["requests"], ensure_ascii=False, sort_keys=True))
    case_row = json.loads((build.adapter.paths.run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()[0])
    turn_row = case_row["turns"][0]
    print("product kind:", turn_row["product"]["kind"],
          "| retrieved:", len(turn_row["product"].get("retrieved") or ()),
          "| sources:", len(turn_row["product"].get("sources") or ()),
          "| evidence:", len(turn_row["product"].get("evidence") or ()))
    print("reservations(item_id/op/center):",
          [((r.get("metadata") or {}).get("item_id"), (r.get("metadata") or {}).get("operation"), r.get("cost_center"))
           for r in reservations])
    print("EXTERNAL =", EXTERNAL)


def probe_usage_missing(tmp: Path) -> None:
    out("C 缺 chat usage：usage_evidence_missing（不伪造金额）")
    chat = NoUsageChat(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
    result, build, gate, plan, paths, logs = run_live(tmp / "nousage", chat=chat)
    rows = [e for e in events(paths["ledger"]) if e.get("event") == "result" and e.get("kind") == "chat"]
    print("status/stop:", result.status, result.stop_code)
    for row in rows:
        print("answer result:", row.get("status"), row.get("error_code"),
              "conservative_charge_cny=", row.get("conservative_charge_cny"),
              "settled_cny=", row.get("settled_cny"))
    summary = json.loads((build.adapter.paths.run_dir / "summary.json").read_text(encoding="utf-8"))
    print("summary.requests:", json.dumps(summary["requests"], ensure_ascii=False, sort_keys=True))
    print("summary.failure:", json.dumps(summary.get("failure"), ensure_ascii=False))
    print("EXTERNAL =", EXTERNAL)


def probe_quota(tmp: Path) -> None:
    out("D 计划项配额不足 -> 发送前 attempt_quota_exhausted")
    chat = UsageChat(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
    result, build, gate, plan, paths, logs = run_live(tmp / "quota", chat=chat, ingest_requests=1)
    print("status/stop:", result.status, result.stop_code)
    summary = json.loads((build.adapter.paths.run_dir / "summary.json").read_text(encoding="utf-8"))
    print("summary.failure:", json.dumps(summary.get("failure"), ensure_ascii=False))
    print("embedding transport calls:", len(logs["embedding"]), "| reservations:",
          [((e.get("metadata") or {}).get("item_id")) for e in events(paths["ledger"]) if e.get("event") == "reserved"])
    print("EXTERNAL =", EXTERNAL)


def probe_expansion(tmp: Path) -> None:
    out("E1 已知限制核对：Q01（无灌库）是否触发 query_expansion")
    chat = UsageChat(behaviors=(ChatBehavior(answer="资料中未记录相关信息。"),))
    result, build, gate, plan, paths, logs = run_live(tmp / "expand-q01", chat=chat, ingest=None)
    print("status/stop:", result.status, result.stop_code)
    print("chat purposes:", chat.counts_by_purpose(), "| calls:", chat.call_count)
    cases = json.loads((build.adapter.paths.run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()[0])
    turn = cases["turns"][0]
    print("product kind/text:", turn["product"]["kind"], "|", str(turn["product"]["text"])[:40])
    rows = [e for e in events(paths["ledger"]) if e.get("event") == "result"]
    print("ledger results:", [(r.get("kind"), r.get("status"), r.get("error_code"), r.get("conservative_charge_cny")) for r in rows])
    print("EXTERNAL =", EXTERNAL)

    out("E2 正文型问题（非 record）空库：产品是否真的发 query_expansion")
    case = CaseSpec(
        case_id="V01",
        suite="b0",
        split="test",
        stratum="document",
        business_date="2026-11-01",
        question="公司的年假政策是怎么规定的？",
        expected_kind="answer",
        label_version="b0-2026-11-04",
    )
    chat2 = UsageChat(behaviors=(ChatBehavior(answer="资料中未记录相关信息。"),))
    result2, build2, gate2, plan2, paths2, logs2 = run_live(tmp / "expand-v01", chat=chat2, ingest=None, case=case)
    print("status/stop:", result2.status, result2.stop_code)
    print("chat purposes:", chat2.counts_by_purpose(), "| calls:", chat2.call_count)
    cases2 = json.loads((build2.adapter.paths.run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()[0])
    turn2 = cases2["turns"][0]
    print("product kind/text:", turn2["product"]["kind"], "|", str(turn2["product"]["text"])[:60])
    receipts = build2.wiring.receipt_payload()
    print("receipts settle:", [(r["operation"], r["item_id"], r["status"]) for r in receipts if r["phase"] == "settle"])
    print("reservations:",
          [(((e.get("metadata") or {}).get("item_id")) , ((e.get("metadata") or {}).get("operation")), e.get("cost_center"))
           for e in events(paths2["ledger"]) if e.get("event") == "reserved"])
    rows2 = [e for e in events(paths2["ledger"]) if e.get("event") == "result"]
    print("ledger results:", [(r.get("kind"), r.get("status"), r.get("error_code"), r.get("conservative_charge_cny")) for r in rows2])
    print("by_center_cny:", json.dumps(result2.by_center_cny, ensure_ascii=False, sort_keys=True))
    print("plan has expand item:", "expand-V01-t1" in [i.item_id for i in plan2.items])
    print("EXTERNAL =", EXTERNAL)



# ---------------------------------------------------------------- G. CLI 发送前拒绝
FULL_ENV = {
    "MKTKB_MODEL_API_KEY": "verify-fake",
    "MKTKB_MODEL_BASE_URL": "https://api.deepseek.com",
    "MKTKB_MODEL_NAME": "deepseek-flash",
    "DASHSCOPE_API_KEY": "verify-fake",
    "MKTKB_OCR_SECRET_ID": "verify-fake",
    "MKTKB_OCR_SECRET_KEY": "verify-fake",
    "MKTKB_OCR_DISABLED": "0",
}


def _base_env() -> dict:
    import subprocess  # noqa: F401
    env = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT") or r"C:\Windows",
        "PATH": os.environ.get("PATH") or r"C:\Windows\System32",
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return env


def probe_cli(tmp: Path) -> None:
    import subprocess

    out("G CLI 在**发送前**拒绝（真实固定路径；GO 不存在、预算未修订）")
    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    cases = [
        ("A 无 live 环境变量", {}, ["--run-id", "verify-cli-a"]),
        ("B 环境齐备但固定路径无 GO", dict(FULL_ENV), ["--run-id", "verify-cli-b"]),
        ("C 缺 --run-id", dict(FULL_ENV), []),
        ("D OCR_DISABLED=1", {**FULL_ENV, "MKTKB_OCR_DISABLED": "1"}, ["--run-id", "verify-cli-d"]),
        ("E 缺 DASHSCOPE_API_KEY", {k: v for k, v in FULL_ENV.items() if k != "DASHSCOPE_API_KEY"}, ["--run-id", "verify-cli-e"]),
        ("F 非白名单 chat 模型", {**FULL_ENV, "MKTKB_MODEL_NAME": "gpt-4o"}, ["--run-id", "verify-cli-f"]),
    ]
    for index, (label, extra, tail) in enumerate(cases):
        out_dir = EV / "_cli_out" / f"case-{index}"
        shutil.rmtree(out_dir, ignore_errors=True)
        argv = [
            py, "-B", "-X", "utf8", "-m", "mktkb.evaluation.cli", "p2-run",
            "--plan", str(PILOT_PLAN), "--out", str(out_dir), "--mode", "live",
            "--ingest", str(D01), *tail,
        ]
        proc = subprocess.run(argv, cwd=str(ROOT), env={**_base_env(), **extra},
                              capture_output=True, text=True, encoding="utf-8")
        print(f"## {label}")
        print("   exit =", proc.returncode)
        print("   stdout =", (proc.stdout or "").strip())
        print("   stderr =", (proc.stderr or "").strip().splitlines()[-1] if proc.stderr.strip() else "(empty)")
        print("   out_dir 创建? ", out_dir.exists(), "(data:", (out_dir / "data").exists(), ")")
        print()



# ---------------------------------------------------------------- H. 测试用例有效性
def probe_vacuous_test(tmp: Path) -> None:
    import contextlib
    import io

    out("H 回归用例 test_cli_live_refuses_without_go_before_building_adapter 是否真的测到拒绝原因")
    from mktkb.evaluation import cli

    print("用例源码里的 --plan 路径（tmp_path/plan.json）从未被写入 ->")
    print("  backend/tests/evaluation/test_p2_live_wiring.py: test_cli_live_refuses_without_go_before_building_adapter")
    missing_plan = tmp / "h" / "plan.json"
    missing_out = tmp / "h" / "out"
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = cli.main([
            "p2-run", "--plan", str(missing_plan), "--out", str(missing_out),
            "--mode", "live", "--run-id", "verify-h", "--ingest", str(D01),
        ])
    print("  缺失 plan 文件：exit =", code, "| stderr =", err.getvalue().strip())
    print("  断言 exit==EXIT_DATA(3) 与 out 目录不存在都会通过，但根本没有走到 live/GO 分支")

    valid_plan = tmp / "h" / "plan.json"
    valid_plan.parent.mkdir(parents=True, exist_ok=True)
    valid_plan.write_text(PILOT_PLAN.read_text(encoding="utf-8"), encoding="utf-8")
    valid_out = tmp / "h" / "out2"
    err2 = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()) as buf, contextlib.redirect_stderr(err2):
        code2 = cli.main([
            "p2-run", "--plan", str(valid_plan), "--out", str(valid_out),
            "--mode", "live", "--run-id", "verify-h2", "--ingest", str(D01),
        ])
    print("  换成真实 plan 文件：exit =", code2, "| stdout =", buf.getvalue().strip())
    print("  （这才是用例声称覆盖的 path_missing；缺这一步用例等于没测）")
    print()



# ---------------------------------------------------------------- I. OCR 真实客户端
def probe_ocr(tmp: Path) -> None:
    from mktkb.providers.tencent_ocr import TencentOCRClient
    from mktkb.providers.types import OCRInput

    out("I OCR 走真实 TencentOCRClient（真实签名/端点）+ 每页预留固定价")
    root = tmp / "ocr"
    plan = build_plan()
    paths = write_fixtures(root, plan)
    gate = p2_live.open_live_gate(plan, run_id="verify-ocr", now=NOW)
    env = p2_live.load_live_env({}, overrides=OVERRIDES)
    receipts: list = []
    ledger = p2_live.GateAttemptLedger(gate, plan, on_receipt=receipts.append)
    wiring = p2_live.LiveWiring(
        env=env,
        plan=plan,
        run_id="verify-ocr",
        gate=gate,
        ledger=ledger,
        attempt_budget=p2_live.AttemptBudget(plan),
        plan_index=p2_live.PlanIndex(plan),
        receipts=receipts,
    )
    calls: list = []

    def handler(request):
        calls.append(
            {
                "action": request.headers.get("X-TC-Action"),
                "auth_scheme": request.headers.get("Authorization", "").split(" ")[0],
                "host": request.headers.get("Host"),
                "body": json.loads(request.content.decode("utf-8")),
            }
        )
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
                    "RequestId": "ocr-verify-1",
                }
            },
            request=request,
        )

    client = TencentOCRClient(
        secret_id="verify-fake-id",
        secret_key="verify-fake-key",
        region="ap-guangzhou",
        transport=httpx.MockTransport(handler),
    )
    gateway = p2_live.GatedOcrGateway(client, wiring=wiring)
    page = OCRInput(content=D09.read_bytes(), mime_type="image/png", page=1)
    first = gateway.recognize(page, mode="text")
    print("text:", first.text)
    print("provider_request_id:", first.provider_request_id[:24], "...")
    print("request:", calls[0]["action"], "| auth:", calls[0]["auth_scheme"], "| host:", calls[0]["host"])
    print("body keys:", sorted(calls[0]["body"].keys()))
    try:
        gateway.recognize(page, mode="text")
        print("第二页未被拒绝 <<< 异常")
    except p2_live.P2LiveRefused as exc:
        print("第二页:", exc.code, "| 出站次数:", len(calls))
    reserved = [e for e in events(paths["ledger"]) if e.get("event") == "reserved" and e.get("kind") == "ocr"]
    results = [e for e in events(paths["ledger"]) if e.get("event") == "result" and e.get("kind") == "ocr"]
    print("ocr reservations:", [(e.get("cost_center"), e.get("reserve_cny")) for e in reserved])
    print("ocr result:", [(e.get("status"), e.get("conservative_charge_cny")) for e in results])
    print("receipt phases:", [(r.as_dict()["phase"], r.as_dict()["operation"], r.as_dict()["cost_center"]) for r in receipts])
    print("EXTERNAL =", EXTERNAL)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="verify-t206-live-"))
    print("tmp:", tmp)
    probe_default_mock(tmp)
    probe_live_e2e(tmp)
    probe_usage_missing(tmp)
    probe_quota(tmp)
    probe_expansion(tmp)
    probe_ocr(tmp)
    probe_cli(tmp)
    probe_vacuous_test(tmp)
    out("F 汇总")
    print("EXTERNAL total =", EXTERNAL)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
