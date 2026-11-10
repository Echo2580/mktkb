"""P2-T203-R1 加固证据探针（F1 实测计数 / F2 live 真门 / F3 holdout purge / F6 封存）。

可复跑：`.venv/Scripts/python.exe -B <本文件>`，stdout 打印 JSON，直接落到 `r1-digest.json`。
只跑隔离目录里的 Mock 链（零真实调用、不读 .env、不碰原 var/）；题目/夹具全部来自既有
`test_p2_runner.py` 的 helper，避免复制一套会漂移的构造逻辑。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(REPO / "backend" / "src"))
sys.path.insert(0, str(REPO / "backend" / "tests"))

from evaluation.test_p2_runner import (  # noqa: E402
    LEGACY_QUESTION,
    NOW,
    RAG_QUESTION,
    ChatBehavior,
    MeteredMockAdapter,
    MockChatBackend,
    ProductEvalAdapter,
    RealishAdapter,
    StubGate,
    dry_run_authorization,
    files_containing,
    make_case,
    make_dataset,
    make_ingest_plan,
    make_plan,
    read_json,
    read_jsonl,
    run_p2,
)

SENTINEL = "R1探针哨兵题干9F4A：火星店的宣传海报到底在哪里？"


def scratch(name: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"t203-r1-{name}-"))


def measured(summary: dict) -> dict:
    return {
        "requests": {
            "real_requests": summary["requests"]["real_requests"],
            "billed_cny": summary["requests"]["billed_cny"],
        },
        "network": {
            "outbound_attempts": summary["network"]["outbound_attempts"],
            "detail": summary["network"]["detail"],
        },
        "providers_outbound_network": summary["providers"]["outbound_network"],
    }


async def mock_dry_run_measured() -> dict:
    cs = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cs)
    adapter = ProductEvalAdapter(
        scratch("dry") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cs),
        ingest_plan=make_ingest_plan(),
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=dry_run_authorization(plan), now=NOW)
        summary = read_json(adapter.paths.run_dir / "summary.json")
        return {
            "status": result.status,
            "stop_code": result.stop_code,
            "measured": measured(summary),
            "request_rows": [
                row["provider_calls"] for row in read_jsonl(adapter.paths.run_dir / "requests.jsonl")
            ],
        }
    finally:
        await adapter.close()


async def injected_outbound() -> dict:
    cs = (make_case("P01", RAG_QUESTION), make_case("P03", LEGACY_QUESTION))
    plan = make_plan(cs)
    adapter = MeteredMockAdapter(
        scratch("metered") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cs),
        ingest_plan=make_ingest_plan(),
        outbound_per_turn=2,
    )
    gate = StubGate(is_mock_gate=True)
    try:
        result = await run_p2(
            plan, adapter=adapter, authorization=dry_run_authorization(plan), gate=gate, now=NOW
        )
        summary = read_json(adapter.paths.run_dir / "summary.json")
        return {
            "status": result.status,
            "stop_code": result.stop_code,
            "measured": measured(summary),
            "request_outbound_deltas": [
                row["provider_calls"]["outbound"]
                for row in read_jsonl(adapter.paths.run_dir / "requests.jsonl")
            ],
            "gate_facts": {
                "requests_reserved": result.requests_reserved,
                "requests_sent": result.requests_sent,
                "settled_cny": result.settled_cny,
            },
        }
    finally:
        await adapter.close()


async def live_with_stub_gate() -> dict:
    cs = (make_case("P01", LEGACY_QUESTION),)
    plan = make_plan(cs)
    authorization = replace(dry_run_authorization(plan), production_ready=True)
    adapter = RealishAdapter(scratch("live") / "run", make_dataset(cs))
    gate = StubGate(is_mock_gate=True)
    result = await run_p2(plan, adapter=adapter, authorization=authorization, gate=gate, now=NOW)
    gate_payload = read_json(adapter.paths.run_dir / "gate.json")
    summary = read_json(adapter.paths.run_dir / "summary.json")
    return {
        "status": result.status,
        "stop_code": result.stop_code,
        "execution": gate_payload["execution"],
        "real_sends_allowed": gate_payload["real_sends_allowed"],
        "failed_checks": [check["name"] for check in gate_payload["checks"] if not check["ok"]],
        "gate_calls": gate.calls,
        "adapter_asks": len(adapter.asks),
        "real_requests": summary["requests"]["real_requests"],
    }


async def holdout_without_purge() -> dict:
    cs = (make_case("H01", RAG_QUESTION),)
    plan = make_plan(cs)
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        scratch("holdout-nopurge") / "run",
        chat=chat,
        dataset=make_dataset(cs, visibility="holdout", manifest_sha256="e" * 64),
        ingest_plan=make_ingest_plan(),
    )
    try:
        result = await run_p2(plan, adapter=adapter, authorization=dry_run_authorization(plan), now=NOW)
        summary = read_json(adapter.paths.run_dir / "summary.json")
        calls = adapter.provider_calls()
        return {
            "status": result.status,
            "stop_code": result.stop_code,
            "failure_stage": summary["failure"]["stage"],
            "holdout": summary["holdout"],
            "ingest_receipts": len(adapter.ingest_receipts),
            "chat_calls": chat.call_count,
            "embedding_calls": calls["embedding"]["calls"],
            "trace_db_exists": adapter.paths.trace_db.exists(),
        }
    finally:
        await adapter.close()


async def holdout_sealed() -> dict:
    cs = (make_case("H91", SENTINEL),)
    plan = make_plan(cs)
    adapter = ProductEvalAdapter(
        scratch("holdout-sealed") / "run",
        chat=MockChatBackend(),
        dataset=make_dataset(cs, visibility="holdout", manifest_sha256="f" * 64),
        ingest_plan=make_ingest_plan(),
        purge_traces_on_close=True,
    )
    out_dir = adapter.paths.root
    before: list[str] = []
    try:
        result = await run_p2(plan, adapter=adapter, authorization=dry_run_authorization(plan), now=NOW)
        before = files_containing(out_dir, SENTINEL)
        summary = read_json(adapter.paths.run_dir / "summary.json")
        payload = {
            "status": result.status,
            "stop_code": result.stop_code,
            "plaintext_hits_before_close": before,
            "holdout": summary["holdout"],
        }
    finally:
        await adapter.close()
    payload.update(
        {
            "seal_receipt": adapter.seal_receipt,
            "plaintext_hits_after_close": files_containing(out_dir, SENTINEL),
            "business_db_exists": adapter.paths.business_db.exists(),
            "trace_db_exists": adapter.paths.trace_db.exists(),
            "aggregate_exists": (adapter.paths.run_dir / "holdout_aggregate.json").is_file(),
            "detail_files": sorted(
                path.name for path in adapter.paths.run_dir.iterdir() if path.is_file()
            ),
        }
    )
    return payload


async def main() -> dict:
    return {
        "schema": "p2-t203-r1-digest/v0.1",
        "scenarios": {
            "f1_mock_dry_run_measured": await mock_dry_run_measured(),
            "f1_injected_outbound": await injected_outbound(),
            "f2_live_with_stub_gate": await live_with_stub_gate(),
            "f3_holdout_without_purge": await holdout_without_purge(),
            "f6_holdout_sealed": await holdout_sealed(),
        },
    }


if __name__ == "__main__":
    digest = asyncio.run(main())
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(digest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    # 终端只打 ASCII 摘要（避免 Windows 控制台代码页把中文证据打坏）。
    scenarios = digest["scenarios"]
    print(
        json.dumps(
            {
                "written": sys.argv[1] if len(sys.argv) > 1 else None,
                "f1_mock": scenarios["f1_mock_dry_run_measured"]["measured"],
                "f1_injected": scenarios["f1_injected_outbound"]["measured"],
                "f2_stop": scenarios["f2_live_with_stub_gate"]["stop_code"],
                "f2_real_sends_allowed": scenarios["f2_live_with_stub_gate"]["real_sends_allowed"],
                "f3_stop": scenarios["f3_holdout_without_purge"]["stop_code"],
                "f6_before": len(scenarios["f6_holdout_sealed"]["plaintext_hits_before_close"]),
                "f6_after": len(scenarios["f6_holdout_sealed"]["plaintext_hits_after_close"]),
                "f6_seal": scenarios["f6_holdout_sealed"]["seal_receipt"]["question_store"],
            },
            ensure_ascii=True,
        )
    )
