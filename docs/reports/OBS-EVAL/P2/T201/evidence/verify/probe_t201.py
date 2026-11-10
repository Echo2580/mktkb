"""P2-T201 独立验收探针（不修改仓库共享账本/预算/GO；所有 P2 场景都在临时目录）。

用途：独立于开发自测，重新证明下列主张，任何一条不成立就以非零退出码失败：
  1. 真实共享账本/预算事实（hash、1011 行、505/505、15.0709445）可由本探针独立复算；
  2. 候选 DRAFT 的额度算术与 20→40 语义（P2 只有 20，旧剩余不变成 P2 资金）；
  3. 授权前/发送前拒绝链：旧 P1 GO、错 stage、未授权 operation/center、预算/请求不足、
     改计划同 nonce、账本前缀变化、过期、缺身份、路径替换 → 均在首个 HTTP 之前拒绝；
  4. 预留后发送前失效 → 保守留账（result 全额、保留 request/plan/center），不谎称 0；
  5. 运行时门控：串行、跨 kind 累计计数、中心/阶段上限、零自动重试、换模型/中心绕不过；
  6. 合法 Mock 路径仍能完整走通并正确结算；
  7. P1 retrieval-only / 旧 GO 不得获得 P2 权限；P2 模块不触网（socket 已被禁用）。
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import socket
import sys
import tempfile
import traceback
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve()
ROOT = _HERE
while ROOT.parent != ROOT and not (ROOT / "backend" / "src" / "mktkb").is_dir():
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))


class NetworkBlocked(RuntimeError):
    pass


def _blocked(*args, **kwargs):
    raise NetworkBlocked("probe: network access attempted")


socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked
socket.getaddrinfo = _blocked

from mktkb import live_authorization as la  # noqa: E402
from mktkb.evaluation import live as p1_live  # noqa: E402
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation import p2_contracts as pc  # noqa: E402
from mktkb.rag.budget import BudgetLedger  # noqa: E402
from mktkb.rag.settlement_policy import UsageEvidence  # noqa: E402

ORIGINAL_FIXED_PATHS = (p2a.P2_LEDGER_PATH, p2a.P2_BUDGET_PATH, p2a.P2_GO_PATH)

T201 = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T201"
CAND = T201 / "candidates"
REAL_LEDGER = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
REAL_BUDGET = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "budget.json"
REAL_P1_GO = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM" / "S2-LIVE-GO.json"

LEDGER_SHA_EXPECTED = "1f46d1b9e846528d5a1635db5175a997eab9da075d61a90a8cbf803f3fde7390"
BUDGET_SHA_EXPECTED = "084ba9acb4ee90379fd51fab8878f6dd4bab1bd481bff2a14c83057ffbc1cc58"
PREFIX_SHA_EXPECTED = "f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014"
ACCOUNTED_EXPECTED = 15.070944499999985

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
HISTORY = 0.03
TOTAL = 40.0
STAGE = 20.0
CENTERS = {"answer_retrieval": 12.0, "ocr": 3.0, "judge": 3.0, "independent": 2.0}
CHAT_BOUND = 0.018688
EMB_BOUND = 0.002048
RERANK_BOUND = 0.0048

RESULTS: list[tuple[str, str, str]] = []


def check(name):
    def wrap(fn):
        try:
            detail = fn()
            RESULTS.append((name, "PASS", str(detail)))
            print("PASS  %s :: %s" % (name, detail))
        except Exception as exc:  # noqa: BLE001
            RESULTS.append((name, "FAIL", "%s: %s" % (type(exc).__name__, exc)))
            print("FAIL  %s :: %s: %s" % (name, type(exc).__name__, exc))
            traceback.print_exc()
        return fn

    return wrap


def sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expect_raises(types, fn, reasons=None, label=""):
    try:
        fn()
    except types as exc:  # noqa: PERF203
        reason = getattr(exc, "reason", None)
        if reasons is not None and reason not in reasons:
            raise AssertionError("%s: unexpected reason %r (want %r)" % (label, reason, reasons))
        return reason
    raise AssertionError("%s: did not raise %s" % (label, types))


def events(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def reserved_count(path) -> int:
    return sum(1 for event in events(path) if event.get("event") == "reserved")


def result_events(path) -> list[dict]:
    return [event for event in events(path) if event.get("event") == "result"]


def append_event(path, payload) -> None:
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def append_reserved(path, *, rid, stage, kind="chat", reserve=CHAT_BOUND, center="answer_retrieval"):
    event = {
        "event": "reserved",
        "reservation_id": rid,
        "stage": stage,
        "kind": kind,
        "provider": "deepseek",
        "model": "deepseek-flash",
        "reserve_cny": reserve,
        "request_sha256": "a" * 64,
        "time_utc": "2026-11-19T00:00:00+00:00",
    }
    if center is not None:
        event["cost_center"] = center
    append_event(path, event)


# ---------------------------------------------------------------- 夹具


def profiles() -> dict[str, dict]:
    chat = {
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
    }
    embedding = {
        "kind": "embedding",
        "model": "text-embedding-v4",
        "provider": "bailian",
        "host": "dashscope.aliyuncs.com",
        "region": "cn-beijing",
        "pricing_source": "official-list-price/bailian-text-embedding-v4-v1",
        "unit_price_per_million_cny": 0.5,
        "total_tokens_cap": 4096,
    }
    rerank = {
        "kind": "rerank",
        "model": "gte-rerank-v2",
        "provider": "bailian",
        "host": "dashscope.aliyuncs.com",
        "region": "cn-beijing",
        "pricing_source": "official-list-price/bailian-gte-rerank-v2-v1",
        "unit_price_per_million_cny": 0.8,
        "total_tokens_cap": 6000,
    }
    ocr_text = {
        "kind": "ocr",
        "model": "GeneralAccurateOCR",
        "provider": "tencent",
        "host": "ocr.tencentcloudapi.com",
        "region": "ap-guangzhou",
        "pricing_source": "official-list-price/tencent-ocr-postpaid-highest-v1",
        "price_cny_per_page": 0.5,
        "pages_per_request": 1,
    }
    ocr_table = dict(ocr_text, model="RecognizeTableAccurateOCR", price_cny_per_page=0.15)
    return {"chat": chat, "embedding": embedding, "rerank": rerank, "ocr_text": ocr_text, "ocr_table": ocr_table}


def item(item_id, operation, case_id, *, requests=1, turn=1, page=0, expected=0.004, profile=None):
    prof = profiles()
    kind = pc.OPERATION_KIND[operation]
    if profile is None:
        if kind == "chat":
            profile = prof["chat"]
        elif kind == "embedding":
            profile = prof["embedding"]
            expected = min(expected, EMB_BOUND)
        elif kind == "rerank":
            profile = prof["rerank"]
            expected = min(expected, RERANK_BOUND)
    return {
        "item_id": item_id,
        "operation": operation,
        "cost_center": pc.OPERATION_COST_CENTER[operation],
        "case_id": case_id,
        "turn": turn,
        "page": page,
        "requests": requests,
        "price_profile": copy.deepcopy(profile),
        "expected_success_cny": expected,
    }


def plan_dict() -> dict:
    prof = profiles()
    items = [item("ingest-index", "index_embedding", "INGEST", requests=8, expected=0.0003)]
    for case, turn in (("B0-Q01", 1), ("B0-Q03", 1), ("N01", 1), ("U01", 2), ("D07", 1)):
        items.append(item("embed-%s-t%d" % (case, turn), "query_embedding", case, turn=turn, expected=0.0003))
        items.append(item("rerank-%s-t%d" % (case, turn), "rerank", case, turn=turn, expected=0.001))
        items.append(item("answer-%s-t%d" % (case, turn), "answer", case, turn=turn, expected=0.004))
    items.append(item("expand-U01-t2", "query_expansion", "U01", turn=2))
    items.append(item("expand-B0-Q03", "query_expansion", "B0-Q03"))
    items.append(item("ocr-D07-p1", "ocr", "D07", page=1, expected=0.5, profile=prof["ocr_text"]))
    items.append(item("ocr-D07-p2", "ocr", "D07", page=2, expected=0.15, profile=prof["ocr_table"]))
    items.append(item("judge-B0-Q01", "judge", "B0-Q01"))
    items.append(item("judge-N01", "judge", "N01"))
    items.append(item("independent-B0-Q01", "independent", "B0-Q01"))
    return {
        "schema_version": "p2-run-plan/v0.1",
        "plan_id": "P2-VERIFY-20261119",
        "plan_version": "v0.1",
        "mode": "end_to_end",
        "stage": "P2-LIVE",
        "created_utc": "2026-11-19T00:00:00+08:00",
        "project_total_limit_cny": TOTAL,
        "stage_limit_cny": STAGE,
        "max_requests": 1000,
        "cost_centers_cny": dict(CENTERS),
        "items": items,
    }


def make_plan(**overrides):
    payload = plan_dict()
    payload.update(overrides)
    return pc.P2RunPlan.from_dict(payload)


def write_ledger(path, *, history=HISTORY, seeded=0):
    lines = [
        json.dumps(
            {
                "event": "historical_import",
                "accounted_cny": history,
                "estimated_success_list_price_cny": 0.0000352,
                "source": "verify-probe",
            },
            ensure_ascii=False,
        )
    ]
    for index in range(seeded):
        lines.append(
            json.dumps(
                {
                    "event": "reserved",
                    "reservation_id": "seed%04d" % index,
                    "stage": "S2-DEV",
                    "kind": ("chat", "embedding", "ocr")[index % 3],
                    "provider": "deepseek",
                    "model": "deepseek-flash",
                    "reserve_cny": 1e-08,
                    "request_sha256": "e" * 64,
                    "time_utc": "2026-11-05T00:00:00+00:00",
                },
                ensure_ascii=False,
            )
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_budget(path, *, limit=TOTAL, stage=STAGE, history=HISTORY, include_stage=True):
    stages = {"S1-DEV": 0.0, "S1-IA": 0.0, "S2-DEV": 15.4, "P1-RETRIEVAL": 3.0, "later_shared_reserve": 1.57}
    if include_stage:
        stages["P2-LIVE"] = stage
    Path(path).write_text(
        json.dumps({"limit_cny": limit, "historical_conservative_accounted_cny": history, "stages": stages}, indent=2)
        + "\n",
        encoding="utf-8",
    )


def go_dict(plan, ledger, *, prefix=None, limit=TOTAL, stage=STAGE, centers=None, max_requests=1000,
            max_request_cny=0.5, operations=None, nonce="verify-probe-nonce-0123456789",
            issued="2026-11-19T00:00:00+00:00", expires="2026-11-20T00:00:00+00:00"):
    return {
        "document": "P2-LIVE-GO",
        "schema_version": "p2-live-go/v0.1",
        "stage": "P2-LIVE",
        "authorization": "VERIFY-PROBE-MOCK（零真实调用）",
        "issued_by": "p2-t201-verify-probe",
        "nonce": nonce,
        "issued_utc": issued,
        "expires_utc": expires,
        "budget_ledger_path": str(ledger),
        "budget_ledger_sha256": prefix if prefix is not None else la.historical_prefix_sha256(ledger),
        "budget_total_limit_cny": limit,
        "scope": {
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "operations": list(plan.operations) if operations is None else operations,
            "cost_centers_cny": dict(centers if centers is not None else CENTERS),
            "stage_limits_cny": {"P2-LIVE": stage},
            "max_requests": max_requests,
            "max_request_cny": max_request_cny,
        },
    }


class Env(SimpleNamespace):
    pass


def make_env(root, *, limit=TOTAL, stage=STAGE, seeded=0, include_stage=True, plan=None):
    directory = Path(tempfile.mkdtemp(dir=str(root), prefix="env-"))
    ledger = directory / "live-ledger.jsonl"
    budget = directory / "budget.json"
    go = directory / "P2-LIVE-GO.json"
    write_ledger(ledger, seeded=seeded)
    write_budget(budget, limit=limit, stage=stage, include_stage=include_stage)
    plan = plan if plan is not None else make_plan()
    Path(go).write_text(
        json.dumps(go_dict(plan, ledger, limit=limit, stage=stage if include_stage else STAGE), indent=2) + "\n",
        encoding="utf-8",
    )
    p2a.P2_LEDGER_PATH = ledger
    p2a.P2_BUDGET_PATH = budget
    p2a.P2_GO_PATH = go
    os.environ[la.TOTAL_LIMIT_ENV] = str(limit)
    snapshot = p2a.read_ledger_snapshot()
    return Env(directory=directory, ledger=ledger, budget=budget, go=go, plan=plan, snapshot=snapshot)


def open_gate(env, **kwargs):
    return p2a.P2Gate.open(
        env.plan,
        go_payload=kwargs.pop("go_payload", env.go),
        budget_payload=kwargs.pop("budget_payload", env.budget),
        ledger_snapshot=kwargs.pop("ledger_snapshot", None),
        now=kwargs.pop("now", NOW),
        run_id=kwargs.pop("run_id", "p2run-verify"),
        **kwargs,
    )


def authorize(env, **kwargs):
    return p2a.authorize_p2(
        kwargs.pop("plan", env.plan),
        go_payload=kwargs.pop("go_payload", env.go),
        budget_payload=kwargs.pop("budget_payload", env.budget),
        ledger_snapshot=kwargs.pop("ledger_snapshot", env.snapshot),
        now=kwargs.pop("now", NOW),
    )


def chat_evidence(ticket, *, prompt=1200, completion=200):
    return UsageEvidence(
        kind="chat",
        provider="deepseek",
        model="deepseek-flash",
        host="api.deepseek.com",
        region="global",
        pricing_source="official-list-price/deepseek-chat-cache-miss-v1",
        request_sha256=ticket.reservation.request_sha256,
        http_status=200,
        streamed=False,
        finish_reason="stop",
        content_complete=True,
        content_parse_ok=True,
        usage={
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": prompt,
        },
    )


class Transport:
    def __init__(self):
        self.sent = []

    def send(self, ticket):
        self.sent.append(ticket.as_dict())
        return {"http_status": 200}

    def __len__(self):
        return len(self.sent)


LEDGER_SHA_START = sha256(REAL_LEDGER)
BUDGET_SHA_START = sha256(REAL_BUDGET)
TMPROOT = Path(tempfile.mkdtemp(prefix="p2-t201-verify-"))

# ================================================================ 1. 真实账本事实
print("== section 1: real shared ledger facts ==")


@check("real_ledger_matches_recorded_facts")
def _():
    raw = REAL_LEDGER.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == LEDGER_SHA_EXPECTED, "ledger sha changed"
    lines = [line for line in raw.splitlines() if line.strip()]
    assert len(lines) == 1011, "expected 1011 non-empty lines, got %d" % len(lines)
    parsed = [json.loads(line) for line in lines]
    kinds = {}
    for event in parsed:
        kinds[event["event"]] = kinds.get(event["event"], 0) + 1
    assert kinds == {"historical_import": 1, "reserved": 505, "result": 505}, kinds
    history = sum(float(e.get("accounted_cny") or 0) for e in parsed if e["event"] == "historical_import")
    reserved = {e["reservation_id"]: e for e in parsed if e["event"] == "reserved"}
    results = {e["reservation_id"]: e for e in parsed if e["event"] == "result"}
    assert set(reserved) == set(results), "unpaired reservation/result"
    total = history + sum(float(results[rid]["conservative_charge_cny"]) for rid in reserved)
    assert abs(total - ACCOUNTED_EXPECTED) < 1e-9, "independent replay %.12f" % total
    assert round(total, 7) == 15.0709445
    assert sha256(REAL_BUDGET) == BUDGET_SHA_EXPECTED, "budget sha changed"
    prefix = la.historical_prefix_sha256(REAL_LEDGER)
    assert prefix == PREFIX_SHA_EXPECTED, "prefix sha changed: %s" % prefix
    return "lines=1011 reserved=505 result=505 accounted=%.10f prefix=%s" % (total, prefix[:12])


@check("real_budget_has_no_p2_stage")
def _():
    payload = json.loads(REAL_BUDGET.read_text(encoding="utf-8"))
    assert payload["limit_cny"] == 20.0, payload["limit_cny"]
    assert "P2-LIVE" not in payload["stages"], payload["stages"]
    assert abs(sum(payload["stages"].values()) + payload["historical_conservative_accounted_cny"] - 20.0) < 1e-9
    return "limit=20 stages=%s" % sorted(payload["stages"])


@check("no_fixed_p2_go_file")
def _():
    assert not p2a.P2_GO_PATH.exists(), "fixed P2 GO exists: %s" % p2a.P2_GO_PATH
    first = expect_raises((p2a.P2AuthorizationError,), lambda: p2a.load_go_payload(), reasons={"path_missing"}, label="load_go")
    return "P2_GO_PATH absent; loader reason=%s" % first


# ================================================================ 2. 候选 DRAFT
print("== section 2: candidate DRAFT arithmetic and status ==")
CAND_BUDGET = json.loads((CAND / "budget.CANDIDATE-DRAFT.json").read_text(encoding="utf-8"))
CAND_GO = json.loads((CAND / "p2-live-go.CANDIDATE-DRAFT.json").read_text(encoding="utf-8"))
CAND_PLAN = json.loads((CAND / "p2-run-plan-v0_1.CANDIDATE-DRAFT.json").read_text(encoding="utf-8"))
CAND_SNAP = json.loads((CAND / "p2-ledger-snapshot.CANDIDATE-DRAFT.json").read_text(encoding="utf-8"))


@check("candidate_budget_keeps_owner_arithmetic")
def _():
    real = json.loads(REAL_BUDGET.read_text(encoding="utf-8"))
    assert CAND_BUDGET["limit_cny"] == 40.0
    assert CAND_BUDGET["historical_conservative_accounted_cny"] == real["historical_conservative_accounted_cny"] == 0.03
    assert CAND_BUDGET["stages"]["P2-LIVE"] == 20.0
    for stage, amount in real["stages"].items():
        assert CAND_BUDGET["stages"][stage] == amount, "old stage %s changed" % stage
    total = sum(CAND_BUDGET["stages"].values()) + CAND_BUDGET["historical_conservative_accounted_cny"]
    assert abs(total - 40.0) < 1e-9, total
    assert abs(sum(CAND_BUDGET["stages"].values()) - 39.97) < 1e-9
    # 20 元新增 == 上限增量；旧剩余（4.9290555）已在旧上限内，不是 P2 的额外资金
    assert abs((40.0 - 20.0) - 20.0) < 1e-12
    old_remaining = 20.0 - ACCOUNTED_EXPECTED
    assert abs(old_remaining - 4.9290555) < 1e-6, old_remaining
    return "40 = 39.97(stages) + 0.03(history); P2-LIVE=20; old remaining %.7f stays outside P2" % old_remaining


@check("candidate_plan_centers_and_request_caps")
def _():
    plan = pc.P2RunPlan.from_dict(CAND_PLAN)
    assert plan.stage == "P2-LIVE" and plan.stage_limit_cny == 20.0 and plan.project_total_limit_cny == 40.0
    assert plan.cost_centers_cny == CENTERS, plan.cost_centers_cny
    assert abs(sum(plan.cost_centers_cny.values()) - plan.stage_limit_cny) < 1e-9
    assert all(amount < plan.stage_limit_cny for amount in plan.cost_centers_cny.values()), "a center got the full stage"
    assert plan.max_requests == 1000 and plan.total_requests == 30
    assert plan.case_count == 6 and plan.page_count == 2
    assert abs(plan.worst_case_cny - 0.887504) < 1e-9, plan.worst_case_cny
    assert abs(plan.reserve_peak_cny - 0.5) < 1e-9, plan.reserve_peak_cny
    assert abs(plan.estimated_success_cny - 0.6989) < 1e-9, plan.estimated_success_cny
    return "requests=30 cases=6 pages=2 worst=%.6f peak=%.6f est=%.6f" % (
        plan.worst_case_cny, plan.reserve_peak_cny, plan.estimated_success_cny)


@check("candidate_authorizes_only_as_non_production")
def _():
    plan = pc.P2RunPlan.from_dict(CAND_PLAN)
    snapshot = pc.P2LedgerSnapshot.from_dict(CAND_SNAP)
    assert snapshot.source == "in-memory" and snapshot.reservation_count == 505 and snapshot.result_count == 505
    assert abs(snapshot.accounted_cny - ACCOUNTED_EXPECTED) < 1e-9
    assert snapshot.ledger_sha256 == LEDGER_SHA_EXPECTED and snapshot.budget_sha256 == BUDGET_SHA_EXPECTED
    assert snapshot.historical_prefix_sha256 == PREFIX_SHA_EXPECTED
    pre = p2a.preflight_p2(plan, snapshot)
    assert pre.ok and not pre.reasons, pre.reasons
    assert pre.production_ready is False
    assert abs(pre.stage_remaining_cny - 20.0) < 1e-9 and abs(pre.total_remaining_cny - 24.9290555) < 1e-6
    assert pre.requests_used == 505 and pre.requests_remaining == 495
    auth = p2a.authorize_p2(plan, go_payload=CAND_GO, budget_payload=CAND_BUDGET, ledger_snapshot=snapshot, now=NOW)
    assert auth.production_ready is False, "candidate must not be a usable authorization"
    assert abs(auth.stage_remaining_cny - 20.0) < 1e-9
    assert auth.cost_center_limits_cny == CENTERS
    assert abs(sum(auth.cost_center_limits_cny.values()) - 20.0) < 1e-9
    return "preflight ok, stage_remaining=20 total_remaining=24.929 requests_remaining=495 production_ready=False"


@check("candidate_files_are_marked_draft")
def _():
    readme = (CAND / "README.md").read_text(encoding="utf-8")
    assert "DRAFT" in readme and "不是授权" in readme
    for name in ("budget.CANDIDATE-DRAFT.json", "p2-live-go.CANDIDATE-DRAFT.json",
                 "p2-run-plan-v0_1.CANDIDATE-DRAFT.json", "p2-ledger-snapshot.CANDIDATE-DRAFT.json"):
        assert (CAND / name).is_file(), name
        assert "CANDIDATE-DRAFT" in name
    assert "DRAFT" in CAND_GO["issued_by"].upper() and "DRAFT" in CAND_GO["authorization"].upper()
    assert CAND_GO["scope"]["plan_sha256"] == pc.P2RunPlan.from_dict(CAND_PLAN).plan_sha256
    assert la.ledger_binding_ok(CAND_GO["budget_ledger_sha256"], REAL_LEDGER), "candidate GO must bind the real ledger prefix"
    return "GO marks DRAFT; binds real prefix %s" % CAND_GO["budget_ledger_sha256"][:12]


@check("candidate_cannot_be_used_against_real_budget")
def _():
    # 真实预算 + 真实账本副本（只读复制），恒定路径指向副本，不写原文件。
    directory = Path(tempfile.mkdtemp(dir=str(TMPROOT), prefix="real-"))
    ledger = directory / "live-ledger.jsonl"
    budget = directory / "budget.json"
    ledger.write_bytes(REAL_LEDGER.read_bytes())
    budget.write_bytes(REAL_BUDGET.read_bytes())
    plan = pc.P2RunPlan.from_dict(CAND_PLAN)
    saved = (p2a.P2_LEDGER_PATH, p2a.P2_BUDGET_PATH)
    p2a.P2_LEDGER_PATH, p2a.P2_BUDGET_PATH = ledger, budget
    try:
        snapshot = p2a.read_ledger_snapshot()
        assert snapshot.source == "fixed-paths" and snapshot.reservation_count == 505
        assert abs(snapshot.p2_stage_accounted_cny) < 1e-12
        reasons = p2a.preflight_p2(plan, snapshot).reasons
        assert "budget_total_mismatch" in reasons and "stage_allocation_missing" in reasons, reasons
        reason = expect_raises(
            (p2a.P2AuthorizationError,),
            lambda: p2a.authorize_p2(plan, go_payload=CAND_GO, budget_payload=CAND_BUDGET,
                                     ledger_snapshot=snapshot, now=NOW),
            reasons={"budget_total_mismatch"}, label="candidate-vs-real-budget")
    finally:
        p2a.P2_LEDGER_PATH, p2a.P2_BUDGET_PATH = saved
    return "reasons=%s reason=%s" % (reasons, reason)


# ================================================================ 3. 预检拒绝
print("== section 3: preflight rejections ==")


@check("preflight_rejections")
def _():
    env = make_env(TMPROOT)
    base = env.snapshot
    cases = []

    def variant(**kwargs):
        return replace(base, **kwargs)

    cases.append(("stage_allocation_missing",
                  variant(stage_allocations_cny={k: v for k, v in base.stage_allocations_cny.items() if k != "P2-LIVE"}),
                  "stage_allocation_missing"))
    cases.append(("stage_allocation_below_plan",
                  variant(stage_allocations_cny=dict(base.stage_allocations_cny, **{"P2-LIVE": 10.0})),
                  "stage_allocation_below_plan"))
    cases.append(("budget_total_mismatch", variant(total_limit_cny=20.0), "budget_total_mismatch"))
    cases.append(("stage_budget_insufficient",
                  variant(p2_stage_accounted_cny=19.9, p2_center_accounted_cny={"answer_retrieval": 19.9}),
                  "stage_budget_insufficient"))
    cases.append(("center_budget_insufficient:ocr",
                  variant(p2_stage_accounted_cny=2.9, p2_center_accounted_cny={"ocr": 2.9}),
                  "center_budget_insufficient:ocr"))
    cases.append(("center_accounting_inconsistent",
                  variant(p2_stage_accounted_cny=0.1, p2_center_accounted_cny={}),
                  "center_accounting_inconsistent"))
    cases.append(("request_budget_insufficient", variant(reservation_count=975), "request_budget_insufficient"))
    cases.append(("total_budget_insufficient", variant(accounted_cny=39.9), "total_budget_insufficient"))
    seen = []
    for label, snapshot, expected in cases:
        pre = p2a.preflight_p2(env.plan, snapshot)
        assert pre.ok is False, label
        assert expected in pre.reasons, "%s -> %s" % (label, pre.reasons)
        reason = expect_raises((p2a.P2AuthorizationError,), lambda s=snapshot: authorize(env, ledger_snapshot=s),
                               reasons={expected}, label=label)
        seen.append("%s=%s" % (label, reason))
    before = reserved_count(env.ledger)
    assert before == 0, "preflight must not reserve"
    return "; ".join(seen)


@check("plan_schema_numeric_and_cap_matrix")
def _():
    """独立复现任务书 T201 第 1 条：非法/空 plan、bool 当 int、NaN/Inf/负数、缺单价或缺上界、
    写小上界、中心合计、累计请求硬顶、成功估价越界一律构造期拒绝。"""
    matrix = []

    def mutate(path, value):
        payload = plan_dict()
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return payload

    def drop(path):
        payload = plan_dict()
        target = payload
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
        return payload

    cases = [
        ("bool_requests", mutate(("items", 0, "requests"), True), "integer_invalid"),
        ("nan_token_cap", mutate(("items", 0, "price_profile", "total_tokens_cap"), float("nan")), "integer_invalid"),
        ("inf_unit_price", mutate(("items", 0, "price_profile", "unit_price_per_million_cny"), float("inf")), "number_invalid"),
        ("negative_price", mutate(("items", 0, "price_profile", "unit_price_per_million_cny"), -0.5), "number_invalid"),
        ("zero_price", mutate(("items", 0, "price_profile", "unit_price_per_million_cny"), 0.0), "number_invalid"),
        ("missing_token_cap", drop(("items", 0, "price_profile", "total_tokens_cap")), "field_missing"),
        ("missing_output_price", drop(("items", 3, "price_profile", "output_price_per_million_cny")), "field_missing"),
        ("lowered_cap", mutate(("items", 0, "price_profile", "total_tokens_cap"), 512), "cap_not_frozen"),
        ("legacy_stage", mutate(("stage",), "P1-RETRIEVAL"), "stage_invalid"),
        ("mode_retrieval_only", mutate(("mode",), "retrieval_only"), "mode_invalid"),
        ("empty_items", mutate(("items",), []), "items_required"),
        ("center_sum_mismatch",
         mutate(("cost_centers_cny",), {"answer_retrieval": 12.0, "ocr": 4.0, "judge": 3.0, "independent": 2.0}),
         "cost_center_total_mismatch"),
        ("every_center_gets_full_stage",
         mutate(("cost_centers_cny",), {name: 20.0 for name in CENTERS}), "cost_center_total_mismatch"),
        ("request_cap_1500", mutate(("max_requests",), 1500), "request_cap_over_hard_limit"),
        ("requests_over_plan_cap", mutate(("max_requests",), 10), "plan_requests_over_cap"),
        ("estimate_over_bound", mutate(("items", -1, "expected_success_cny"), 1.0), "success_estimate_over_bound"),
        ("ocr_page_zero", mutate(("items", 19, "page"), 0), "page_required"),
        ("page_on_answer", mutate(("items", 3, "page"), 1), "page_forbidden"),
    ]
    for label, payload, expected in cases:
        reason = expect_raises((pc.P2ContractError,), lambda x=payload: pc.P2RunPlan.from_dict(x),
                               reasons={expected}, label=label)
        matrix.append(label)
    return "%d plan rejections (all before any ledger/GO involvement)" % len(matrix)


# ================================================================ 4. 授权拒绝
print("== section 4: authorization rejections ==")


@check("authorize_rejects_legacy_p1_go")
def _():
    env = make_env(TMPROOT)
    real = json.loads(REAL_P1_GO.read_text(encoding="utf-8"))
    assert real["document"] == "S2-LIVE-GO", real.get("document")
    reason_a = expect_raises((p2a.P2AuthorizationError,), lambda: authorize(env, go_payload=real),
                             reasons={"legacy_go_document"}, label="real-p1-go")
    reason_b = expect_raises((p2a.P2AuthorizationError,),
                             lambda: authorize(env, go_payload={"document": "S2-LIVE-GO"}),
                             reasons={"legacy_go_document"}, label="minimal-p1-go")
    assert reserved_count(env.ledger) == 0
    return "real P1 GO -> %s; minimal -> %s" % (reason_a, reason_b)


@check("authorize_rejects_stage_operation_center_and_limits")
def _():
    env = make_env(TMPROOT)
    base_go = go_dict(env.plan, env.ledger)
    trials = [
        ("go_stage_mismatch", dict(base_go, stage="S2-DEV", schema_version="p2-live-go/v0.1")),
        ("go_schema_invalid", dict(base_go, schema_version="p2-live-go/v9")),
        ("go_document_invalid", dict(base_go, document="P2-LIVE-GO-X")),
        ("go_operation_unauthorized",
         dict(base_go, scope=dict(base_go["scope"], operations=[op for op in base_go["scope"]["operations"] if op != "judge"]))),
        ("go_operation_invalid",
         dict(base_go, scope=dict(base_go["scope"], operations=list(base_go["scope"]["operations"]) + ["tts"]))),
        ("go_cost_center_unauthorized",
         dict(base_go, scope=dict(base_go["scope"],
                                  cost_centers_cny={k: v for k, v in CENTERS.items() if k != "independent"}))),
        ("go_cost_center_below_plan",
         dict(base_go, scope=dict(base_go["scope"], cost_centers_cny=dict(CENTERS, ocr=2.0)))),
        ("go_stage_limit_missing", dict(base_go, scope=dict(base_go["scope"], stage_limits_cny={"S2-DEV": 20.0}))),
        ("go_stage_limit_below_plan", dict(base_go, scope=dict(base_go["scope"], stage_limits_cny={"P2-LIVE": 10.0}))),
        ("go_max_requests_over_hard_cap", dict(base_go, scope=dict(base_go["scope"], max_requests=2001))),
        ("go_max_requests_below_plan", dict(base_go, scope=dict(base_go["scope"], max_requests=10))),
        ("go_max_request_cny_below_plan", dict(base_go, scope=dict(base_go["scope"], max_request_cny=0.4))),
        ("go_nonce_invalid", dict(base_go, nonce="short")),
        ("text_invalid", dict(base_go, issued_by="  ")),
        ("number_invalid", dict(base_go, budget_total_limit_cny=True)),
        ("number_invalid", dict(base_go, budget_total_limit_cny=float("nan"))),
        ("go_budget_total_mismatch", dict(base_go, budget_total_limit_cny=39.0)),
        ("field_missing", {k: v for k, v in base_go.items() if k != "authorization"}),
        ("field_unknown", dict(base_go, extra_field=1)),
        ("go_expired", dict(base_go, issued_utc="2026-11-01T00:00:00+00:00", expires_utc="2026-11-02T00:00:00+00:00")),
        ("go_not_yet_valid", dict(base_go, issued_utc="2026-12-01T00:00:00+00:00", expires_utc="2026-12-02T00:00:00+00:00")),
    ]
    results = []
    for expected, payload in trials:
        reason = expect_raises((p2a.P2AuthorizationError,), lambda p=payload: authorize(env, go_payload=p),
                               reasons={expected}, label=expected)
        results.append(expected)
    assert reserved_count(env.ledger) == 0, "no reservation may happen on rejection"
    return "%d GO rejections, reserved=0" % len(results)


@check("authorize_rejects_plan_swap_with_same_nonce")
def _():
    env = make_env(TMPROOT)
    swapped = plan_dict()
    swapped["plan_id"] = env.plan.plan_id
    swapped["items"] = swapped["items"][:-1]
    plan_b = pc.P2RunPlan.from_dict(swapped)
    assert plan_b.plan_sha256 != env.plan.plan_sha256
    go = go_dict(env.plan, env.ledger)
    reason = expect_raises((p2a.P2AuthorizationError,), lambda: authorize(env, plan=plan_b, go_payload=go),
                           reasons={"go_plan_sha256_mismatch"}, label="plan-swap")
    assert reserved_count(env.ledger) == 0
    return "reason=%s" % reason


@check("authorize_rejects_ledger_prefix_change")
def _():
    env = make_env(TMPROOT)
    go = go_dict(env.plan, env.ledger)
    lines = env.ledger.read_text(encoding="utf-8").splitlines()
    history = json.loads(lines[0])
    history["accounted_cny"] = 0.0301
    env.ledger.write_text("\n".join([json.dumps(history)] + lines[1:]) + "\n", encoding="utf-8")
    snapshot = p2a.read_ledger_snapshot()
    reason = expect_raises((p2a.P2AuthorizationError,), lambda: authorize(env, go_payload=go, ledger_snapshot=snapshot),
                           reasons={"go_ledger_binding_mismatch"}, label="prefix-change")
    assert reserved_count(env.ledger) == 0
    return "reason=%s" % reason


@check("authorize_rejects_budget_and_env_mismatch")
def _():
    env = make_env(TMPROOT)
    budget = {
        "limit_cny": TOTAL,
        "historical_conservative_accounted_cny": HISTORY,
        "stages": {"P2-LIVE": STAGE},
    }
    trials = [
        ("budget_total_mismatch", dict(budget, limit_cny=39.0)),
        ("budget_stage_missing", dict(budget, stages={"S2-DEV": 15.4})),
        ("budget_stage_below_plan", dict(budget, stages={"P2-LIVE": 10.0})),
        ("budget_history_mismatch", dict(budget, historical_conservative_accounted_cny=0.031)),
        ("budget_ledger_path_not_fixed", dict(budget, ledger="docs/evidence/other/live-ledger.jsonl")),
    ]
    seen = []
    for expected, payload in trials:
        reason = expect_raises((p2a.P2AuthorizationError,), lambda p=payload: authorize(env, budget_payload=p),
                               reasons={expected}, label=expected)
        seen.append(reason)
    os.environ[la.TOTAL_LIMIT_ENV] = "39"
    try:
        reason_env = expect_raises((p2a.P2AuthorizationError,), lambda: authorize(env, budget_payload=budget),
                                   reasons={"env_total_limit_mismatch"}, label="env-mismatch")
    finally:
        os.environ[la.TOTAL_LIMIT_ENV] = str(TOTAL)
    os.environ.pop(la.TOTAL_LIMIT_ENV, None)
    try:
        reason_missing = expect_raises((p2a.P2AuthorizationError,), lambda: authorize(env),
                                       reasons={"env_total_limit_missing"}, label="env-missing")
    finally:
        os.environ[la.TOTAL_LIMIT_ENV] = str(TOTAL)
    assert reserved_count(env.ledger) == 0
    return "%s; %s; %s" % (",".join(seen), reason_env, reason_missing)


@check("authorize_rejects_path_substitution_and_other_snapshot")
def _():
    env = make_env(TMPROOT)
    other = env.directory / "other-go.json"
    other.write_text(json.dumps(go_dict(env.plan, env.ledger)), encoding="utf-8")
    reason_path = expect_raises((p2a.P2AuthorizationError,), lambda: authorize(env, go_payload=other),
                                reasons={"path_not_fixed"}, label="go-path")
    other_ledger = env.directory / "other-ledger.jsonl"
    other_ledger.write_text(env.ledger.read_text(encoding="utf-8"), encoding="utf-8")
    foreign = replace(env.snapshot, ledger_path=str(other_ledger))
    reason_snap = expect_raises((p2a.P2AuthorizationError,), lambda: authorize(env, ledger_snapshot=foreign),
                                reasons={"snapshot_ledger_path_not_fixed"}, label="snapshot-path")
    assert reserved_count(env.ledger) == 0
    return "%s; %s" % (reason_path, reason_snap)


# ================================================================ 5. 运行时门控
print("== section 5: runtime gate ==")


@check("gate_serial_and_zero_retry")
def _():
    env = make_env(TMPROOT)
    transport = Transport()
    gate = open_gate(env)
    ticket = gate.begin("answer-B0-Q01-t1")
    reason = expect_raises((p2a.P2GateError,), lambda: gate.begin("answer-B0-Q03-t1"),
                           reasons={"request_inflight"}, label="serial")
    assert len(transport) == 0 and reserved_count(env.ledger) == 1
    assert gate.confirm_before_send(ticket) is ticket
    transport.send(ticket)
    gate.settle_failure(ticket, error_code="CHAT_503", http_status=503)
    assert gate.stopped_reason == "CHAT_503"
    reason_stop = expect_raises((p2a.P2GateError,), lambda: gate.begin("answer-B0-Q03-t1"),
                                reasons={"gate_stopped"}, label="no-retry")
    assert len(transport) == 1 and reserved_count(env.ledger) == 1
    receipt = gate.result()
    assert receipt.status == "blocked" and receipt.requests_sent == 1 and receipt.stop_code == "CHAT_503"
    return "%s / %s; transport=%d reserved=%d" % (reason, reason_stop, len(transport), reserved_count(env.ledger))


@check("gate_cumulative_request_cap_across_kinds")
def _():
    env = make_env(TMPROOT)
    gate = open_gate(env)
    for index in range(999):
        append_reserved(env.ledger, rid="other%04d" % index, stage="P2-LIVE",
                        kind=("chat", "embedding", "ocr")[index % 3],
                        center=("answer_retrieval", "ocr", "judge")[index % 3], reserve=1e-08)
    transport = Transport()
    first = gate.begin("answer-B0-Q01-t1")
    gate.confirm_before_send(first)
    transport.send(first)
    gate.settle_success(first, evidence=chat_evidence(first))
    assert reserved_count(env.ledger) == 1000, reserved_count(env.ledger)
    reason = expect_raises((p2a.P2GateError,), lambda: gate.begin("answer-B0-Q03-t1"),
                           reasons={"request_limit"}, label="cap")
    assert reserved_count(env.ledger) == 1000 and len(transport) == 1
    return "cap at 1000 -> %s" % reason


@check("gate_center_and_stage_caps_are_runtime")
def _():
    env = make_env(TMPROOT)
    gate = open_gate(env)
    append_reserved(env.ledger, rid="other-ocr", stage="P2-LIVE", kind="ocr", reserve=2.6, center="ocr")
    reason_center = expect_raises((p2a.P2GateError,), lambda: gate.begin("ocr-D07-p1"),
                                  reasons={"center_budget_exceeded"}, label="center")
    assert reserved_count(env.ledger) == 1

    env2 = make_env(TMPROOT)
    gate2 = open_gate(env2)
    append_reserved(env2.ledger, rid="other-stage", stage="P2-LIVE", kind="ocr", reserve=20.01, center="ocr")
    reason_stage = expect_raises((p2a.P2GateError,), lambda: gate2.begin("answer-B0-Q01-t1"),
                                 reasons={"stage_budget_exceeded"}, label="stage")
    assert reserved_count(env2.ledger) == 1

    env3 = make_env(TMPROOT)
    gate3 = open_gate(env3)
    append_reserved(env3.ledger, rid="other-nocenter", stage="P2-LIVE", reserve=0.1, center=None)
    reason_unattributed = expect_raises((p2a.P2GateError,), lambda: gate3.begin("answer-B0-Q01-t1"),
                                        reasons={"center_accounting_inconsistent"}, label="unattributed")
    return "%s / %s / %s" % (reason_center, reason_stage, reason_unattributed)


@check("gate_reserve_then_invalidate_is_conservative")
def _():
    env = make_env(TMPROOT)
    transport = Transport()
    gate = open_gate(env)
    ticket = gate.begin("answer-B0-Q01-t1")
    refusal = None
    try:
        gate.confirm_before_send(ticket, now=NOW + timedelta(days=2))
    except p2a.P2SendRefused as exc:
        refusal = exc
    assert refusal is not None, "expected P2SendRefused"
    assert refusal.reason == "authorization_expired", refusal.reason
    assert refusal.reservation_id == ticket.reservation_id
    assert refusal.request_id == ticket.request_id
    assert refusal.cost_center == "answer_retrieval"
    assert len(transport) == 0, "must not send after refusal"
    assert reserved_count(env.ledger) == 1, "must not release or duplicate the reservation"
    results = result_events(env.ledger)
    assert len(results) == 1
    row = results[0]
    assert row["status"] == "failed" and row["error_code"] == "P2_PRE_SEND_REFUSED:authorization_expired"
    assert row["reservation_id"] == ticket.reservation_id and row["request_id"] == ticket.request_id
    assert abs(row["conservative_charge_cny"] - CHAT_BOUND) < 1e-12, row["conservative_charge_cny"]
    reserved_row = [e for e in events(env.ledger)
                    if e.get("event") == "reserved" and e.get("reservation_id") == ticket.reservation_id]
    assert len(reserved_row) == 1, "reservation row must be kept"
    assert reserved_row[0]["cost_center"] == "answer_retrieval"
    metadata = reserved_row[0].get("metadata") or {}
    assert metadata.get("plan_id") == env.plan.plan_id
    assert metadata.get("plan_sha256") == env.plan.plan_sha256
    assert metadata.get("operation") == "answer" and metadata.get("cost_center") == "answer_retrieval"
    summary = BudgetLedger(env.ledger, env.budget, stage="P2-LIVE", stage_limit_cny=STAGE,
                           max_requests=1000).summary()
    assert abs(summary.stage_accounted_cny - CHAT_BOUND) < 1e-9, summary.stage_accounted_cny
    assert abs(summary.center_accounted_cny.get("answer_retrieval", 0.0) - CHAT_BOUND) < 1e-9
    receipt = gate.result()
    assert receipt.status == "blocked" and receipt.requests_sent == 0
    assert abs(receipt.settled_cny - CHAT_BOUND) < 1e-12
    assert receipt.plan_id == env.plan.plan_id and receipt.plan_sha256 == env.plan.plan_sha256
    return "status=failed charge=%.8f request_id=%s center=%s (kept on reservation row + ticket)" % (
        row["conservative_charge_cny"], row["request_id"][:12], reserved_row[0]["cost_center"])


@check("gate_reserve_then_plan_or_prefix_change_is_conservative")
def _():
    env = make_env(TMPROOT)
    gate = open_gate(env)
    ticket = gate.begin("answer-B0-Q01-t1")
    payload = json.loads(env.go.read_text(encoding="utf-8"))
    payload["scope"]["plan_sha256"] = "0" * 64
    env.go.write_text(json.dumps(payload), encoding="utf-8")
    reason_plan = expect_raises((p2a.P2SendRefused,), lambda: gate.confirm_before_send(ticket),
                                reasons={"plan_sha256_changed"}, label="plan-edit")
    assert reserved_count(env.ledger) == 1 and len(result_events(env.ledger)) == 1

    env2 = make_env(TMPROOT)
    gate2 = open_gate(env2)
    ticket2 = gate2.begin("answer-B0-Q01-t1")
    lines = env2.ledger.read_text(encoding="utf-8").splitlines()
    history = json.loads(lines[0])
    history["accounted_cny"] = 0.0301
    env2.ledger.write_text("\n".join([json.dumps(history)] + lines[1:]) + "\n", encoding="utf-8")
    reason_prefix = expect_raises((p2a.P2SendRefused,), lambda: gate2.confirm_before_send(ticket2),
                                  reasons={"ledger_prefix_mismatch"}, label="prefix")
    assert reserved_count(env2.ledger) == 1

    env3 = make_env(TMPROOT)
    gate3 = open_gate(env3)
    ticket3 = gate3.begin("ocr-D07-p1")
    payload3 = json.loads(env3.go.read_text(encoding="utf-8"))
    payload3["scope"]["operations"] = [op for op in payload3["scope"]["operations"] if op != "ocr"]
    env3.go.write_text(json.dumps(payload3), encoding="utf-8")
    reason_op = expect_raises((p2a.P2SendRefused,), lambda: gate3.confirm_before_send(ticket3),
                              reasons={"operation_unauthorized"}, label="op-withdrawn")
    return "%s / %s / %s" % (reason_plan, reason_prefix, reason_op)


@check("gate_no_bypass_by_model_or_center")
def _():
    signature = inspect.signature(p2a.P2Gate.begin)
    assert list(signature.parameters) == ["self", "item_id", "now"], signature
    bad = plan_dict()
    bad["items"][0]["cost_center"] = "judge"
    reason_center = expect_raises((pc.P2ContractError,),
                                  lambda: pc.P2RunPlan.from_dict(bad),
                                  reasons={"cost_center_mismatch"}, label="center-bypass")
    bad2 = plan_dict()
    bad2["items"][0]["price_profile"] = dict(bad2["items"][0]["price_profile"], model="text-embedding-v3")
    reason_model = expect_raises((pc.P2ContractError,),
                                 lambda: pc.P2RunPlan.from_dict(bad2),
                                 reasons={"price_model_invalid"}, label="model-bypass")
    return "begin(item_id only); %s; %s" % (reason_center, reason_model)


@check("gate_missing_evidence_stays_inflight")
def _():
    env = make_env(TMPROOT)
    gate = open_gate(env)
    ticket = gate.begin("answer-B0-Q01-t1")
    gate.confirm_before_send(ticket)
    reason = expect_raises((p2a.P2GateError,), lambda: gate.settle_success(ticket),
                           reasons={"evidence_required"}, label="no-evidence")
    assert result_events(env.ledger) == [], "no result may be written without evidence"
    charge = gate.settle_success(ticket, evidence=chat_evidence(ticket))
    assert abs(charge - 0.004) < 1e-9
    return "%s then settled at %.6f" % (reason, charge)


# ================================================================ 6. 合法路径
print("== section 6: legal mock path settles ==")


@check("legal_mock_path_completes_and_settles")
def _():
    env = make_env(TMPROOT)
    assert env.snapshot.source == "fixed-paths"
    gate = open_gate(env)
    assert gate.authorization.production_ready is True, "production-shaped inputs must be flagged ready"
    transport = Transport()

    ticket = gate.begin("answer-B0-Q01-t1")
    assert ticket.cost_center == "answer_retrieval" and ticket.kind == "chat"
    assert abs(ticket.bound_cny - CHAT_BOUND) < 1e-12
    gate.confirm_before_send(ticket)
    transport.send(ticket)
    charge = gate.settle_success(ticket, evidence=chat_evidence(ticket))
    assert abs(charge - 0.004) < 1e-9, charge

    ocr_ticket = gate.begin("ocr-D07-p1")
    assert ocr_ticket.cost_center == "ocr" and abs(ocr_ticket.bound_cny - 0.5) < 1e-12
    gate.confirm_before_send(ocr_ticket)
    transport.send(ocr_ticket)
    ocr_charge = gate.settle_success(ocr_ticket)
    assert abs(ocr_charge - 0.5) < 1e-9, ocr_charge

    summary = BudgetLedger(env.ledger, env.budget, stage="P2-LIVE", stage_limit_cny=STAGE,
                           max_requests=1000).summary()
    assert abs(summary.accounted_cny - (HISTORY + 0.004 + 0.5)) < 1e-9, summary.accounted_cny
    assert abs(summary.center_accounted_cny["answer_retrieval"] - 0.004) < 1e-9
    assert abs(summary.center_accounted_cny["ocr"] - 0.5) < 1e-9
    assert summary.reservation_count == 2 and summary.result_count == 2
    receipt = gate.result()
    assert receipt.status == "succeeded" and receipt.requests_reserved == 2 and receipt.requests_sent == 2
    assert abs(receipt.settled_cny - 0.504) < 1e-9, receipt.settled_cny
    assert receipt.by_operation == {"answer": 1, "ocr": 1}
    assert len(transport) == 2
    return "chat 0.018688->0.004, ocr 0.5->0.5, receipt settled=0.504, production_ready=True"


@check("in_memory_go_can_still_reserve_on_fixed_ledger")
def _():
    """残余风险（供 T203 复核）：内存 GO 不是固定路径，production_ready=False，
    但 authorize/begin 仍会往固定共享账本写预留；能否真花钱取决于 runner 是否硬断言
    production_ready。本探针只确认这一事实，不把它当作可用授权。"""
    env = make_env(TMPROOT)
    mem_go = go_dict(env.plan, env.ledger)
    gate = open_gate(env, go_payload=mem_go, budget_payload=env.budget)
    assert gate.authorization.production_ready is False, "memory GO must not be production ready"
    ticket = gate.begin("answer-B0-Q01-t1")
    assert ticket.reservation_id
    assert reserved_count(env.ledger) == 1
    return "production_ready=False but reservation written to the fixed path ledger (runner must assert)"


@check("production_defaults_fail_closed_without_p2_go")
def _():
    plan = make_plan()
    saved = (p2a.P2_LEDGER_PATH, p2a.P2_BUDGET_PATH, p2a.P2_GO_PATH)
    p2a.P2_LEDGER_PATH, p2a.P2_BUDGET_PATH, p2a.P2_GO_PATH = ORIGINAL_FIXED_PATHS
    try:
        assert p2a.P2_GO_PATH == ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM" / "P2-LIVE-GO.json"
        assert not p2a.P2_GO_PATH.exists()
        reason = expect_raises((p2a.P2AuthorizationError,), lambda: p2a.P2Gate.open(plan, now=NOW),
                               reasons={"path_missing"}, label="default-open")
        reason_go = expect_raises((p2a.P2AuthorizationError,), lambda: p2a.load_go_payload(),
                                  reasons={"path_missing"}, label="default-load")
    finally:
        p2a.P2_LEDGER_PATH, p2a.P2_BUDGET_PATH, p2a.P2_GO_PATH = saved
    assert reserved_count(REAL_LEDGER) == 505
    assert sha256(REAL_LEDGER) == LEDGER_SHA_EXPECTED
    return "default open -> %s; loader -> %s; real ledger untouched (505)" % (reason, reason_go)


@check("no_retry_logic_in_gate")
def _():
    tokens = []
    for name in ("p2_contracts.py", "p2_authorization.py"):
        text = (ROOT / "backend" / "src" / "mktkb" / "evaluation" / name).read_text(encoding="utf-8").lower()
        tokens.extend([token for token in ("retry", "retries", "backoff", "sleep(") if token in text])
    assert not tokens, tokens
    assert not hasattr(p2a.P2Gate, "retry")
    return "no retry/backoff/sleep tokens in P2 modules; auto-retry=0 by construction"


# ================================================================ 7. 接口冻结 / P1 不回退 / 不触网
print("== section 7: interface freeze, P1 non-regression, no network ==")


@check("frozen_interface_matches_contract")
def _():
    for name in ("P2RunPlan", "P2PreflightResult", "P2Authorization", "P2RunResult",
                 "P2RequestItem", "P2PriceProfile", "P2LedgerSnapshot"):
        assert hasattr(pc, name), name
    for name in ("preflight_p2", "authorize_p2", "read_ledger_snapshot", "P2Gate", "P2RequestTicket",
                 "load_go_payload", "load_budget_payload"):
        assert hasattr(p2a, name), name
    assert list(inspect.signature(p2a.preflight_p2).parameters) == ["plan", "snapshot"]
    params = inspect.signature(p2a.authorize_p2).parameters
    assert list(params) == ["plan", "go_payload", "budget_payload", "ledger_snapshot", "now"], list(params)
    assert params["go_payload"].kind is inspect.Parameter.KEYWORD_ONLY
    schema = [pc.P2_RUN_PLAN_SCHEMA_VERSION, pc.P2_PREFLIGHT_SCHEMA_VERSION,
              pc.P2_AUTHORIZATION_SCHEMA_VERSION, pc.P2_RUN_RESULT_SCHEMA_VERSION,
              pc.P2_LEDGER_SNAPSHOT_SCHEMA_VERSION]
    assert schema == ["p2-run-plan/v0.1", "p2-preflight/v0.1", "p2-authorization/v0.1",
                      "p2-run-result/v0.1", "p2-ledger-snapshot/v0.1"], schema
    assert len(pc.OPERATIONS) == 8 and pc.COST_CENTERS == ("answer_retrieval", "ocr", "judge", "independent")
    assert pc.HARD_MAX_REQUESTS == 1000
    return "4 DTO + preflight_p2/authorize_p2/P2Gate frozen; schema versions stable; hard cap 1000"


@check("p2_modules_do_not_touch_network")
def _():
    banned = ("import httpx", "import requests", "import socket", "import http.client", "import urllib",
              "import openai", "import aiohttp", "from http", "from urllib")
    for name in ("p2_contracts.py", "p2_authorization.py"):
        text = (ROOT / "backend" / "src" / "mktkb" / "evaluation" / name).read_text(encoding="utf-8")
        hits = [token for token in banned if token in text]
        assert not hits, "%s imports %s" % (name, hits)
    return "no network imports in p2_contracts/p2_authorization (socket guarded during whole probe)"


@check("p1_entry_still_retrieval_only_and_rejects_p2_stage")
def _():
    assert la.ALLOWED_SERVICES == ("rag", "chat"), la.ALLOWED_SERVICES
    assert p1_live.LIVE_SCOPE == "retrieval_only", p1_live.LIVE_SCOPE
    reason = expect_raises((la.LiveGateError,),
                           lambda: la.load_live_authorization(stage="P2-LIVE", service="rag", now=NOW),
                           label="p1-stage")
    source = inspect.getsource(la.refresh_request_limits)
    assert "load_live_authorization(" in source, "request-time refresh must re-check the P1 GO"
    assert "P2" in "".join(la.P1_FORBIDDEN_STAGES)
    return "services=%s scope=%s; P2 stage rejected (%s); refresh re-checks GO" % (
        la.ALLOWED_SERVICES, p1_live.LIVE_SCOPE, type(reason).__name__)


@check("shared_files_untouched_by_probe")
def _():
    assert sha256(REAL_LEDGER) == LEDGER_SHA_START == LEDGER_SHA_EXPECTED, "real ledger changed"
    assert sha256(REAL_BUDGET) == BUDGET_SHA_START == BUDGET_SHA_EXPECTED, "real budget changed"
    assert reserved_count(REAL_LEDGER) == 505
    leftovers = sorted(p.name for p in REAL_LEDGER.parent.iterdir())
    assert leftovers == ["budget.json", "live-ledger.jsonl"], leftovers
    return "ledger/budget sha unchanged; 505 reservations; budget dir=%s" % leftovers


# ================================================================ 汇总
print()
failures = [row for row in RESULTS if row[1] != "PASS"]
print("SUMMARY: %d checks, %d passed, %d failed" % (len(RESULTS), len(RESULTS) - len(failures), len(failures)))
print("real ledger sha start=%s" % LEDGER_SHA_START)
print("real ledger sha end  =%s" % sha256(REAL_LEDGER))
print("real budget sha start=%s" % BUDGET_SHA_START)
print("real budget sha end  =%s" % sha256(REAL_BUDGET))
print("temp sandbox: %s (isolated; nothing written into docs/evidence)" % TMPROOT)
sys.exit(1 if failures else 0)
