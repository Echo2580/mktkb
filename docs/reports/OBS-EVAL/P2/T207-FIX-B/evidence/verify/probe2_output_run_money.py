"""独立探针 2：output_valid（C）+ 三口径（B）+ run_result additive（A）一次跑完。

零真实调用：httpx.MockTransport 全接住；账本/预算/GO 全是 tmp 副本；内置 socket 外部连接闸门。
运行：cd backend && <repo>\.venv Scripts python.exe ..\docs\reports\OBS-EVAL\P2\T207-FIX-B\evidence\verify\probe2_output_run_money.py
"""
from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_live  # noqa: E402
from mktkb.evaluation.p2_contracts import P2RunPlan  # noqa: E402
from mktkb.rag.budget import BudgetLedger, SettlementNotReleasable  # noqa: E402
from mktkb.rag.controlled_usage import build_total_evidence  # noqa: E402
from mktkb.rag.settlement_policy import build_policy  # noqa: E402

PLAN_ART = ROOT / "docs/reports/OBS-EVAL/P2/T201/candidates/p2-run-plan-v0_1.CANDIDATE-DRAFT.json"
OUT: list[str] = []


def say(line: str = "") -> None:
    OUT.append(line)
    print(line, flush=True)


PLAN = P2RunPlan.from_dict(json.loads(PLAN_ART.read_text(encoding="utf-8")))
CHAT_ITEM = next(i for i in PLAN.items if i.operation == "answer")
EMB_ITEM = next(i for i in PLAN.items if i.operation == "query_embedding")
CHAT_MODEL = CHAT_ITEM.price_profile.model
BOUND = CHAT_ITEM.bound_cny

GOOD_USAGE = {
    "prompt_tokens": 64,
    "completion_tokens": 32,
    "total_tokens": 96,
    "prompt_cache_hit_tokens": 0,
    "prompt_cache_miss_tokens": 64,
}


def new_ledger(tmp: Path) -> BudgetLedger:
    budget = tmp / "budget.json"
    budget.write_text(json.dumps({"limit_cny": 40, "stages": {"P2-LIVE": 20}}), encoding="utf-8")
    ledger_path = tmp / "live-ledger.jsonl"
    ledger_path.write_text("", encoding="utf-8")
    return BudgetLedger(
        ledger_path,
        budget,
        stage="P2-LIVE",
        stage_limit_cny=20.0,
        max_requests=1600,
    )


def shadow_embedding_policy():
    """embedding policy 必须来自已核来源；直接借计划里的冻结画像。"""
    return EMB_ITEM.price_profile.settlement_policy()


def events(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def chat_case(name: str, *, criteria: dict | None, usage: dict | None = None, mutate=False):
    """一次真实 reserve -> settle_usage，返回 (evidence, decision/reason, ledger result 事件)。"""
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ledger = new_ledger(tmp)
        policy = CHAT_ITEM.price_profile.settlement_policy()
        reservation = ledger.reserve(
            kind="chat",
            provider=policy.provider,
            model=policy.model,
            max_cny=BOUND,
            request_sha256="a" * 64,
            settlement_policy=policy,
            metadata={"stage": "P2-LIVE", "operation": "answer"},
            cost_center="answer_retrieval",
        )
        if criteria is None:
            evidence = p2_live.chat_usage_evidence(
                request_sha256=reservation.request_sha256,
                usage=usage if usage is not None else dict(GOOD_USAGE),
                model=CHAT_MODEL,
            )
        else:
            evidence = p2_live.chat_usage_evidence(
                request_sha256=reservation.request_sha256,
                usage=usage if usage is not None else dict(GOOD_USAGE),
                model=CHAT_MODEL,
                **criteria,
            )
        if mutate and evidence is not None:
            evidence = dataclasses.replace(evidence, output_valid=False)
        reason = None
        charge = None
        accepted = None
        if evidence is None:
            reason = "evidence=None（调用方视为缺 usage：保守留账+停止）"
        else:
            try:
                decision = ledger.settle_usage(reservation, evidence=evidence)
                accepted = decision.accepted
                charge = float(decision.charge_cny)
            except SettlementNotReleasable as exc:
                accepted = False
                reason = exc.reason
                charge = exc.conservative_charge_cny
        rows = [r for r in events(tmp / "live-ledger.jsonl") if r.get("event") == "result"]
        row = rows[-1] if rows else None
        say(f"-- {name}")
        if evidence is not None:
            say(
                "   evidence: finish_reason=%r content_complete=%r content_parse_ok=%r output_valid=%r"
                % (
                    evidence.finish_reason,
                    evidence.content_complete,
                    evidence.content_parse_ok,
                    evidence.output_valid,
                )
            )
        else:
            say("   evidence: None")
        say(f"   J1 accepted={accepted} reason={reason} charge_cny={charge}")
        if row is not None:
            say(
                "   ledger result: status=%r error_code=%r conservative_charge_cny=%r"
                % (row.get("status"), row.get("error_code"), row.get("conservative_charge_cny"))
            )
            block = row.get("settlement") or {}
            say(
                "   ledger settlement block: output_valid=%r content_complete=%r content_parse_ok=%r"
                % (block.get("output_valid"), block.get("content_complete"), block.get("content_parse_ok"))
            )
        say("")
        return evidence, accepted, reason, charge, row


say("== A. chat 三判据 -> output_valid 与 J1 决定 ==")
say(f"chat 单次上界 bound_cny = {BOUND}（= 6144*2e-6 + 800*8e-6）")
say("")
chat_case("合法 usage + 三判据齐（stop/非空/已解析）", criteria={"finish_reason": "stop", "content_present": True, "content_parsed": True})
chat_case("空内容", criteria={"finish_reason": "stop", "content_present": False, "content_parsed": False})
chat_case("非 stop 完成态", criteria={"finish_reason": "length", "content_present": True, "content_parsed": True})
chat_case("未解析（无 answer/source_ids 结构）", criteria={"finish_reason": "stop", "content_present": True, "content_parsed": False})
chat_case("判据缺省（调用方不传）", criteria=None)
chat_case("usage 缺字段（判据齐）", criteria={"finish_reason": "stop", "content_present": True, "content_parsed": True}, usage={"total_tokens": 96})

say("== B. 更正核对：chat J1 不读 output_valid；只有 embedding/rerank 读 ==")
chat_case("chat：三判据齐但强行 output_valid=False", criteria={"finish_reason": "stop", "content_present": True, "content_parsed": True}, mutate=True)

with tempfile.TemporaryDirectory() as raw:
    tmp = Path(raw)
    ledger = new_ledger(tmp)
    policy = shadow_embedding_policy()
    for flag in (False, True):
        reservation = ledger.reserve(
            kind="embedding",
            provider=policy.provider,
            model=policy.model,
            max_cny=EMB_ITEM.bound_cny,
            request_sha256="b" * 64,
            settlement_policy=policy,
            metadata={"stage": "P2-LIVE", "operation": "query_embedding"},
            cost_center="answer_retrieval",
        )
        evidence = build_total_evidence(
            policy,
            request_sha256=reservation.request_sha256,
            usage={"total_tokens": 40},
            http_status=200,
            output_valid=flag,
        )
        try:
            decision = ledger.settle_usage(reservation, evidence=evidence)
            say(f"-- embedding output_valid={flag}: J1 accepted={decision.accepted} charge={float(decision.charge_cny)}")
        except SettlementNotReleasable as exc:
            say(f"-- embedding output_valid={flag}: J1 REFUSED reason={exc.reason} conservative={exc.conservative_charge_cny}")
say("")
say("== C. 代码位置（行号证据） ==")
sp = (ROOT / "backend/src/mktkb/rag/settlement_policy.py").read_text(encoding="utf-8").splitlines()
for idx, line in enumerate(sp, start=1):
    if "if evidence.finish_reason != \"stop\"" in line or "if evidence.output_valid is not True" in line:
        say(f"   settlement_policy.py:{idx}: {line.strip()}")
say("   -> chat 校验段（_validate_chat_evidence）只看 finish_reason/content_complete/content_parse_ok；")
say("      output_valid 只在 _validate_total_evidence（embedding/rerank）被读。")


# ---------------------------------------------------------------- 第 2 部分所需
import asyncio  # noqa: E402
import copy  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402

from mktkb import live_authorization  # noqa: E402
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation import p2_contracts as c  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, validate_case  # noqa: E402
from mktkb.evaluation.p2_contracts import P2RunResult  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
)

say("")
say("################ 第 2 部分：run_result additive（A）+ 三口径（B）+ 实跑观察 ################")
say("")
# 零真实出站：把 socket.connect 之外的全部外部目标拦下来（探针自证，不依赖 pytest fixture）
import socket  # noqa: E402

_EXTERNAL: list[str] = []
_real_connect = socket.socket.connect


def _guarded_connect(self, address, *args, **kwargs):  # noqa: ANN001
    host = address[0] if isinstance(address, (tuple, list)) and address else address
    if isinstance(host, str) and (host.startswith("127.") or host in {"::1", "localhost", "0.0.0.0", ""}):
        return _real_connect(self, address, *args, **kwargs)
    if isinstance(host, str) and (host.startswith("\\\\.\\pipe") or host.startswith("/")):
        return _real_connect(self, address, *args, **kwargs)
    _EXTERNAL.append(str(address))
    raise RuntimeError("probe guard: 外部连接被拦截 " + str(address))


socket.socket.connect = _guarded_connect


def say(line: str = "") -> None:
    OUT.append(line)
    print(line, flush=True)


NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
TOTAL = 40.0
STAGE = 20.0
CENTERS = {"answer_retrieval": 9.0, "ocr": 6.0, "judge": 3.0, "independent": 2.0}
D01 = ROOT / "fixtures/acceptance/normal/D01_物品位置表.xlsx"
B0 = ROOT / "fixtures/evaluation/b0.jsonl"
ENV_OVERRIDES = {
    "chat_api_key": "probe-placeholder",
    "chat_base_url": "https://api.deepseek.com",
    "chat_model": "deepseek-flash",
    "dashscope_api_key": "probe-placeholder",
    "dashscope_base_url": "https://dashscope.aliyuncs.com",
    "ocr_secret_id": "probe-placeholder",
    "ocr_secret_key": "probe-placeholder",
    "ocr_region": "ap-guangzhou",
}
PROFILES = {
    "embedding": {
        "kind": "embedding",
        "model": "text-embedding-v4",
        "provider": "bailian",
        "host": "dashscope.aliyuncs.com",
        "region": "cn-beijing",
        "pricing_source": "official-list-price/bailian-text-embedding-v4-v1",
        "unit_price_per_million_cny": 0.5,
        "total_tokens_cap": 4096,
    },
    "rerank": {
        "kind": "rerank",
        "model": "gte-rerank-v2",
        "provider": "bailian",
        "host": "dashscope.aliyuncs.com",
        "region": "cn-beijing",
        "pricing_source": "official-list-price/bailian-gte-rerank-v2-v1",
        "unit_price_per_million_cny": 0.8,
        "total_tokens_cap": 6000,
    },
    "chat": {
        "kind": "chat",
        "model": "deepseek-flash",
        "provider": "deepseek",
        "host": "api.deepseek.com",
        "region": "global",
        "pricing_source": "official-list-price/deepseek-chat-cache-miss-v1",
        "input_price_per_million_cny": 2.0,
        "output_price_per_million_cny": 8.0,
        "prompt_tokens_cap": 6144,
        "completion_tokens_cap": 800,
    },
    "ocr": {
        "kind": "ocr",
        "model": "GeneralAccurateOCR",
        "provider": "tencent",
        "host": "ocr.tencentcloudapi.com",
        "region": "ap-guangzhou",
        "pricing_source": "official-list-price/tencent-ocr-postpaid-highest-v1",
        "price_cny_per_page": 0.5,
        "pages_per_request": 1,
    },
}


def item(item_id: str, operation: str, case_id: str, *, requests: int = 1, page: int = 0) -> dict:
    kind = c.OPERATION_KIND[operation]
    expected = {"chat": 0.004, "embedding": 0.0003, "rerank": 0.001, "ocr": 0.5}[kind]
    return {
        "item_id": item_id,
        "operation": operation,
        "cost_center": c.OPERATION_COST_CENTER[operation],
        "case_id": case_id,
        "turn": 1,
        "page": page,
        "requests": requests,
        "price_profile": copy.deepcopy(PROFILES[kind]),
        "expected_success_cny": expected,
    }


def plan() -> P2RunPlan:
    return P2RunPlan.from_dict(
        {
            "schema_version": c.P2_RUN_PLAN_SCHEMA_VERSION,
            "plan_id": "P2-PROBE-20261111",
            "plan_version": "v0.1",
            "mode": "end_to_end",
            "stage": "P2-LIVE",
            "created_utc": "2026-11-11T00:00:00+08:00",
            "project_total_limit_cny": TOTAL,
            "stage_limit_cny": STAGE,
            "max_requests": 1600,
            "cost_centers_cny": dict(CENTERS),
            "items": [
                item("ingest-index", "index_embedding", "INGEST", requests=8),
                item("embed-Q01-t1", "query_embedding", "Q01"),
                item("rerank-Q01-t1", "rerank", "Q01"),
                item("expand-Q01-t1", "query_expansion", "Q01"),
                item("answer-Q01-t1", "answer", "Q01"),
                item("ocr-Q01-p1", "ocr", "Q01", page=1),
            ],
        }
    )


def write_env(tmp: Path, p: P2RunPlan) -> dict[str, Path]:
    ledger = tmp / "live-ledger.jsonl"
    budget = tmp / "budget.json"
    go = tmp / "P2-LIVE-GO.json"
    ledger.write_text(
        json.dumps({"event": "historical_import", "accounted_cny": 2.0, "source": "probe"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    budget.write_text(
        json.dumps({"limit_cny": TOTAL, "historical_conservative_accounted_cny": 2.0, "stages": {"S2-DEV": 18.0, "P2-LIVE": STAGE}}),
        encoding="utf-8",
    )
    go.write_text(
        json.dumps(
            {
                "document": "P2-LIVE-GO",
                "schema_version": "p2-live-go/v0.1",
                "stage": "P2-LIVE",
                "authorization": "PROBE-ONLY（零真实调用）",
                "issued_by": "independent-verifier",
                "nonce": "probe-live-nonce-0123456789",
                "issued_utc": "2026-11-19T00:00:00+00:00",
                "expires_utc": "2026-11-20T00:00:00+00:00",
                "budget_ledger_path": str(ledger),
                "budget_ledger_sha256": live_authorization.historical_prefix_sha256(ledger),
                "budget_total_limit_cny": TOTAL,
                "scope": {
                    "plan_id": p.plan_id,
                    "plan_sha256": p.plan_sha256,
                    "operations": list(p.operations),
                    "cost_centers_cny": dict(CENTERS),
                    "stage_limits_cny": {"P2-LIVE": STAGE},
                    "max_requests": 1600,
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


class UsageChat(MockChatBackend):
    """官方 usage（cache 拆分满足 J1）。bad_total=True 时故意让 total != prompt+completion。"""

    def __init__(self, *, bad_total: bool = False) -> None:
        super().__init__(behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),))
        self.bad_total = bad_total

    def _completion(self, request: httpx.Request, content: str, *, call: int) -> httpx.Response:
        response = super()._completion(request, content, call=call)
        payload = json.loads(response.content.decode("utf-8"))
        total = 999 if self.bad_total else 96
        payload["usage"] = {
            "prompt_tokens": 64,
            "completion_tokens": 32,
            "total_tokens": total,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 64,
        }
        return httpx.Response(200, json=payload, request=request)


def transports(chat: MockChatBackend) -> dict[str, Any]:
    def emb(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        dims = int(body.get("dimensions") or 1024)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": i, "embedding": [0.01] * dims} for i in range(len(body.get("input") or ()))],
                "usage": {"total_tokens": 40},
                "id": "emb-1",
            },
            request=request,
        )

    def rer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        docs = list((body.get("input") or {}).get("documents") or ())
        return httpx.Response(
            200,
            json={"output": {"results": [{"index": i, "relevance_score": 0.9 - i * 0.01} for i in range(len(docs))]}, "usage": {"total_tokens": 80}, "request_id": "rer-1"},
            request=request,
        )

    def ocr(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"Response": {"TextDetections": [{"DetectedText": "领取活动物料需先填写物料领用单", "Confidence": 99, "Polygon": [{"X": 10, "Y": 10}, {"X": 200, "Y": 10}, {"X": 200, "Y": 40}, {"X": 10, "Y": 40}]}], "RequestId": "ocr-1"}},
            request=request,
        )

    return {"chat": chat.transport, "embedding": httpx.MockTransport(emb), "rerank": httpx.MockTransport(rer), "ocr": httpx.MockTransport(ocr)}


def dataset() -> P2RunDataset:
    rows = [json.loads(l) for l in B0.read_text(encoding="utf-8").splitlines() if l.strip()]
    case = CaseSpec.from_dict(next(r for r in rows if r["case_id"] == "Q01"))
    validate_case(case)
    return P2RunDataset(
        visibility="public",
        cases=(case,),
        identity={"dataset_version": "probe-v1", "label_version": "b0", "suite": "b0", "manifest_sha256": "a" * 64, "case_count": 1},
    )


def run(tmp: Path, chat: MockChatBackend, gate_out: dict) -> dict:
    p = plan()
    env = write_env(tmp, p)
    gate = p2_live.open_live_gate(p, run_id="p2-probe", now=NOW)
    gate_out["gate"] = gate

    async def go():
        return await p2_live.run_live_p2(
            p,
            run_id="p2-probe",
            out_dir=tmp / "run",
            dataset=dataset(),
            ingest_plan=P2IngestPlan(sources=(IngestSource(path=D01),), label="probe"),
            gate=gate,
            env={"MKTKB_OCR_DISABLED": "0"},
            env_overrides=ENV_OVERRIDES,
            transports=transports(chat),
            now=NOW,
        )

    result, build = asyncio.run(go())
    run_dir = build.adapter.paths.run_dir
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in env["ledger"].read_text(encoding="utf-8").splitlines() if l.strip()]
    reservations = [r for r in rows if r.get("event") == "reserved"]
    results = [r for r in rows if r.get("event") == "result"]
    return {"result": result, "summary": summary, "run_result": run_result, "reservations": reservations, "results": results, "gate": gate}


say("== A. 一次真实 mock 全链（1 案 Q01 + INGEST；零出网） ==")
with tempfile.TemporaryDirectory() as raw:
    tmp = Path(raw)
    gate_box: dict = {}
    got = run(tmp, UsageChat(), gate_box)
    res, summary, run_result = got["result"], got["summary"], got["run_result"]
    say(f"run status={res.status} stop_code={res.stop_code} sent={res.requests_sent}")
    say(f"summary.requests = {json.dumps(summary['requests'], ensure_ascii=False)}")
    say(f"summary.attempts.scope = {summary['attempts'].get('scope')} gate_reserved={summary['attempts'].get('gate_reserved')}")
    say(f"run_result keys = {sorted(run_result)}")
    say(f"run_result.attempts_* = scope={run_result['attempts_scope']} reserved={run_result['attempts_reserved']} by_op={run_result['attempts_by_operation']}")
    say(f"  by_center={run_result['attempts_by_center_cny']}")
    say(f"len(ledger reservations) = {len(got['reservations'])}")
    say(f"attempts_reserved == 门登记 reservation 数 ? {run_result['attempts_reserved'] == len(got['reservations'])}")
    say(f"attempts_reserved == result.attempts_reserved ? {run_result['attempts_reserved'] == res.attempts_reserved}")
    say(f"sum(attempts_by_operation) == attempts_reserved ? {sum(run_result['attempts_by_operation'].values()) == run_result['attempts_reserved']}")
    say(f"attempts_by_operation['answer'] == requests_reserved({res.requests_reserved}) ? {run_result['attempts_by_operation'].get('answer') == res.requests_reserved}")
    ledger_held = round(sum(float(r.get('conservative_charge_cny') or 0.0) for r in got['results']), 8)
    say(f"summary.conservative_held_cny={summary['requests']['conservative_held_cny']} 账本 result 保守合计={ledger_held} 一致={abs(summary['requests']['conservative_held_cny']-ledger_held) < 1e-9}")
    say(f"provider_billed_cny={summary['requests']['provider_billed_cny']} unpaid_rounds={summary['requests']['unpaid_rounds']} failed_rounds={summary['requests']['failed_rounds']} settled_failure={summary['requests']['settled_failure']}")
    chat_rows = [r for r in got['results'] if r.get('kind') == 'chat']
    for r in chat_rows:
        say(f"chat result status={r.get('status')} charged={r.get('conservative_charge_cny')} settlement.output_valid={(r.get('settlement') or {}).get('output_valid')}")
    say(f"P2Gate.result(): attempts_scope={got['gate'].result().attempts_scope} attempts_reserved={got['gate'].result().attempts_reserved}（门只知道自己一侧）")
    say("")

say("== B. 旧产物可读：T206/PILOT/run_result.json（无 attempts_*） ==")
old = json.loads((ROOT / "docs/reports/OBS-EVAL/P2/T206/PILOT/run_result.json").read_text(encoding="utf-8"))
loaded = P2RunResult.from_dict(old)
say(f"from_dict 成功 scope={loaded.attempts_scope} reserved={loaded.attempts_reserved} settled_cny={loaded.settled_cny} requests_reserved={loaded.requests_reserved}")
say(f"as_dict 仍能写出 attempts_* 键: {sorted(loaded.as_dict())}")
say("")

say("== C. 三口径用真实 pilot 账本 + 产物独立重算（不经 runner 代码） ==")
pilot_rows = [json.loads(l) for l in (ROOT / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
pilot = [r for r in pilot_rows if str(r.get("run_id") or "") == "p2-t206-pilot-20261111-01" and r.get("event") == "result"]
paid = [r for r in pilot if r.get("status") == "succeeded"]
unpaid = [r for r in pilot if str(r.get("error_code") or "").startswith("P2_NO_PAID_ATTEMPT")]
held = sum(float(r.get("conservative_charge_cny") or 0.0) for r in pilot)
billed = sum(float(r.get("conservative_charge_cny") or 0.0) for r in paid)
say(f"保守占用（全部 result 的 conservative_charge 合计） = {round(held, 8)}")
say(f"带供应商证据的金额（status=succeeded 的合计数）     = {round(billed, 8)}")
say(f"零付费轮（P2_NO_PAID_ATTEMPT）                     = {len(unpaid)} 笔 × {unpaid[0].get('conservative_charge_cny')} = {round(sum(float(r.get('conservative_charge_cny') or 0) for r in unpaid), 8)}")
say(f"差额 = {round(held - billed, 8)}（= 零付费轮保守留账，不是供应商花费）")
say("")

say("== D. 实跑观察：usage 自身不一致（total != prompt+completion）时 J1 拒绝的整条链 ==")
with tempfile.TemporaryDirectory() as raw:
    tmp = Path(raw)
    got = run(tmp, UsageChat(bad_total=True), {})
    res, summary = got["result"], got["summary"]
    say(f"run status={res.status} stop_code={res.stop_code} sent={res.requests_sent} settled_cny={res.settled_cny}")
    say(f"summary.requests = {json.dumps(summary['requests'], ensure_ascii=False)}")
    held_ledger = round(sum(float(r.get('conservative_charge_cny') or 0.0) for r in got['results']), 8)
    say(f"账本 result 保守合计 = {held_ledger}")
    say(f"summary.conservative_held_cny = {summary['requests']['conservative_held_cny']}")
    say(f"两者一致 ? {abs(summary['requests']['conservative_held_cny'] - held_ledger) < 1e-9}")
    for r in got['results']:
        if r.get('kind') == 'chat':
            say(f"  chat result status={r.get('status')} error_code={r.get('error_code')} charged={r.get('conservative_charge_cny')}")

say("== E. 零真实出站自证 ==")
say(f"外部 socket.connect 尝试 = {len(_EXTERNAL)}（探针内置闸门）")
say("")


report = ROOT / "docs/reports/OBS-EVAL/P2/T207-FIX-B/evidence/verify/probe2_output_run_money.out.txt"
report.write_text("\n".join(OUT) + "\n", encoding="utf-8")
