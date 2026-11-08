"""T111 验收探针（只读；不发真实网络、不写账本）。

用法（cwd=仓库根）：
    .venv\\Scripts\\python.exe -B docs\\reports\\OBS-EVAL\\P1\\evidence\\verify\\T111\\02-probe.py

覆盖：
1. pilot manifest/summary/cases 的十题、版本字段与指标；
2. 共享账本按 run_id 的 27 笔预留/结果、零 chat、前缀哈希；
3. GO 未授权 stage/service、provider binding 不符、错误账本哈希；
4. 成本预检的接受值与三种拒绝理由（不预留、不发请求）；
5. 验收方 live 复跑（10 题）产物的聚合核对。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend" / "src"))
os.environ["MKTKB_PROJECT_TOTAL_LIMIT_CNY"] = "20.0"

from mktkb.evaluation import live as live_module  # noqa: E402
from mktkb.evaluation.dataset import load_cases  # noqa: E402
from mktkb.live_authorization import (  # noqa: E402
    LiveGateError,
    assert_provider_binding,
    ledger_binding_ok,
    load_live_authorization,
)

PILOT = ROOT / "var" / "eval" / "runs" / "b0-live-20261108T194053896474Z-b224f9fb"
RERUN = ROOT / "backend" / ".pytest-tmp" / "T111-verify" / "live-rerun"
LEDGER = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget" / "live-ledger.jsonl"
GO_SHA = "f4710b1869fe43b9a609b58f772549f76370fbadd54f93685b76211d4b47a014"
VERSION_FIELDS = {
    "dataset_version",
    "dataset_sha256",
    "corpus_manifest_sha256",
    "index_revision",
    "pipeline_version",
    "gate_version",
    "label_version",
    "business_date",
    "config_hash",
    "mode",
    "scope",
}


def _load(run: Path) -> tuple[dict, dict, list[dict]]:
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (run / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return manifest, summary, rows


def check_pilot() -> None:
    manifest, summary, rows = _load(PILOT)
    print("== pilot ==")
    print(
        "manifest",
        manifest["mode"],
        manifest["scope"],
        manifest["case_count"],
        manifest["dataset_version"],
        manifest["corpus_manifest_sha256"][:12],
        manifest["index_revision"],
        manifest["pipeline_version"],
        manifest["gate_version"],
    )
    print("statuses", Counter(row["status"] for row in rows), "rows", len(rows))
    print(
        "metrics",
        {k: summary["metrics"].get(k) for k in ("Recall@10", "MRR@10", "nDCG@10",
                                                "hard_filter_violation_rate", "empty_recall_rate")},
    )
    print(
        "versions_complete",
        all(VERSION_FIELDS <= set(row.get("versions") or {}) for row in rows),
        "identical",
        len({json.dumps(row["versions"], sort_keys=True) for row in rows}) == 1,
    )
    print("aborted", summary.get("aborted"), "error_count", summary.get("error_count"))
    print("pilot", summary["live"].get("pilot"), summary["live"].get("pilot_cases"))


def check_ledger(run_id: str, expected_charge: float, expected_reservations: int) -> None:
    events = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    run = [event for event in events if event.get("run_id") == run_id]
    charge = sum(float(event.get("conservative_charge_cny") or 0) for event in run if event.get("event") == "result")
    kinds = Counter((event.get("event"), event.get("kind")) for event in run)
    print("== ledger", run_id, "==")
    print("events", len(run), "kinds", dict(sorted(kinds.items())))
    print("charge", round(charge, 10), "expected", expected_charge)
    print("all_succeeded", all(event.get("status") == "succeeded" for event in run if event.get("event") == "result"))
    print("chat_events", sum(1 for event in run if event.get("kind") == "chat"))
    total_reservations = sum(1 for event in events if event.get("event") == "reserved")
    print("total_reservations", total_reservations, "expected_at_least", expected_reservations)
    prefix = bytearray()
    for line in LEDGER.read_bytes().splitlines(keepends=True):
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") != "historical_import":
            break
        prefix.extend(line)
    prefix_sha = hashlib.sha256(bytes(prefix)).hexdigest()
    print("prefix_sha", prefix_sha, "go_bound", GO_SHA, "match", prefix_sha == GO_SHA)
    print("binding_ok", ledger_binding_ok(GO_SHA, LEDGER), "wrong_sha_ok", ledger_binding_ok("0" * 64, LEDGER))


def check_go_and_precheck() -> None:
    print("== GO / precheck ==")
    auth = load_live_authorization(stage="P1-RETRIEVAL", service="rag")
    print("authorized", auth.stage, auth.service, auth.stage_limit_cny, auth.max_requests, auth.max_request_cny, auth.expires_utc.isoformat())
    for label, kwargs in (
        ("service=chat", {"stage": "P1-RETRIEVAL", "service": "chat"}),
        ("stage=S2-DEV", {"stage": "S2-DEV", "service": "rag"}),
    ):
        try:
            load_live_authorization(**kwargs)
            print("NEGATIVE-FAIL", label)
        except LiveGateError as exc:
            print("refused", label, str(exc)[:60])
    try:
        assert_provider_binding(auth, "rag", embedding_model="text-embedding-v3")
        print("NEGATIVE-FAIL binding")
    except LiveGateError as exc:
        print("refused binding", str(exc)[:60])

    runtime = live_module.load_live_runtime(
        data_dir=ROOT / "backend" / ".pytest-tmp" / "T111-verify" / "probe-index",
        business_date="2026-10-28",
        environ={"MKTKB_PROJECT_TOTAL_LIMIT_CNY": "20.0", "DASHSCOPE_API_KEY": "probe"},
        env_file=None,
    )
    print("chat_fields", repr(runtime.config.chat_model), repr(runtime.config.chat_base_url), repr(runtime.config.chat_api_key))
    print("retries", runtime.config.max_retries, runtime.config.require_zero_retries)
    cases = load_cases(ROOT / "var" / "eval" / "pilot" / "b0-pilot10.jsonl")
    corpus = live_module.load_suite_corpus(
        "b0", live_module.default_corpus_dir("b0"), business_date="2026-10-28",
        required_codes=live_module._required_doc_codes(cases),
    )
    before = live_module.budget_snapshot(runtime.budget.summary())
    estimate = live_module.plan_live_cost(
        corpus, cases, runtime.config,
        stage_remaining_cny=float(before["stage_remaining_cny"]),
        request_remaining=runtime.max_requests - int(before["reservation_count"]),
        max_request_cny=runtime.max_request_cny,
    )
    print(
        "estimate", estimate.estimated_cny, estimate.total_requests,
        estimate.embedding_requests, estimate.query_embedding_requests,
        estimate.rerank_requests, estimate.max_single_reserve_cny,
        estimate.accepted, estimate.reasons, "request_remaining", estimate.request_remaining,
    )
    for label, kwargs in (
        ("stage_tiny", {"stage_remaining_cny": 0.001, "request_remaining": 1000, "max_request_cny": 0.05}),
        ("cap_tiny", {"stage_remaining_cny": 3.0, "request_remaining": 1000, "max_request_cny": 0.01}),
        ("req_tiny", {"stage_remaining_cny": 3.0, "request_remaining": 5, "max_request_cny": 0.05}),
    ):
        refused = live_module.plan_live_cost(corpus, cases, runtime.config, **kwargs)
        print("refused", label, refused.accepted, refused.reasons)


def check_rerun() -> None:
    print("== reviewer live rerun ==")
    if not (RERUN / "run_manifest.json").is_file():
        print("rerun absent")
        return
    manifest, summary, rows = _load(RERUN)
    print("run_id", manifest["run_id"], "cases", manifest["case_count"], "mode", manifest["mode"], "scope", manifest["scope"])
    print("statuses", Counter(row["status"] for row in rows), "rows", len(rows))
    print(
        "metrics",
        {k: summary["metrics"].get(k) for k in ("Recall@10", "MRR@10", "nDCG@10",
                                                "hard_filter_violation_rate", "empty_recall_rate")},
    )
    print("chat_calls", summary["live"].get("chat_calls"), "provider", summary["live"].get("provider_requests"))
    delta = summary["live"]["budget_delta"]
    print("delta", delta["stage_accounted_cny"], delta["reservation_count"])
    print("aborted", summary.get("aborted"))


if __name__ == "__main__":
    check_pilot()
    check_ledger("b0-live-20261108T194053896474Z-b224f9fb", 0.0026345, 408)
    check_go_and_precheck()
    check_rerun()
    if (RERUN / "run_manifest.json").is_file():
        rerun_manifest = json.loads((RERUN / "run_manifest.json").read_text(encoding="utf-8"))
        check_ledger(rerun_manifest["run_id"], 0.0026345, 435)
