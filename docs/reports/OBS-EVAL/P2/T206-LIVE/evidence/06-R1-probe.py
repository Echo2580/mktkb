"""T206-LIVE-R1 只读证明（零真实调用）：F1 expand 归属 / F2 批配额 / F6 retrieved。

不联网：所有 provider 都挂在 httpx.MockTransport 上（与测试同一套 fake transport），
账本/预算/GO 都是 tmp 副本（改写 p2_authorization 的三个固定路径常量）。
打印的是**事实**（回执/账本/产物），不是结论性断言。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend" / "tests" / "evaluation"))

import tempfile  # noqa: E402

import test_p2_live_wiring as T  # noqa: E402

from mktkb import live_authorization  # noqa: E402
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation import p2_live  # noqa: E402
from mktkb.evaluation.p2_contracts import P2RunPlan  # noqa: E402


def make_env(root: Path) -> SimpleNamespace:
    root.mkdir(parents=True, exist_ok=True)
    ledger = root / "live-ledger.jsonl"
    budget = root / "budget.json"
    go = root / "P2-LIVE-GO.json"
    plan = T._plan()
    T._write_ledger(ledger)
    T._write_budget(budget)
    T._write_go(go, ledger=ledger, plan=plan)
    p2a.P2_LEDGER_PATH = ledger
    p2a.P2_BUDGET_PATH = budget
    p2a.P2_GO_PATH = go
    os.environ[live_authorization.TOTAL_LIMIT_ENV] = str(T.TOTAL_LIMIT_CNY)
    return SimpleNamespace(ledger=ledger, budget=budget, go=go, plan=plan, root=root)


def f1(root: Path) -> None:
    env = make_env(root / "f1")
    chat = T._UsageChatBackend()
    result, build, _gate = T._run(env, root / "f1", chat=chat, case_id="Q25", ingest=None)
    receipts = build.wiring.receipt_payload()
    print("[F1] chat_by_purpose=", chat.counts_by_purpose())
    print("[F1] status=", result.status, "stop=", result.stop_code)
    for row in receipts:
        print(
            "[F1] receipt",
            {key: row[key] for key in ("operation", "item_id", "phase", "cost_center", "status", "charged_cny")},
        )
    print(
        "[F1] quota_used=",
        build.wiring.attempt_budget.as_dict(),
        "calls=",
        build.wiring.as_dict()["calls"],
    )
    rows = T._results(env.ledger)
    print(
        "[F1] ledger_results=",
        [{key: row.get(key) for key in ("kind", "status", "error_code", "conservative_charge_cny")} for row in rows],
    )


def f2(root: Path) -> None:
    env = make_env(root / "f2")
    live_env = p2_live.load_live_env({}, overrides=T.LIVE_ENV_OVERRIDES)
    texts = [f"第{index}条待索引文本" for index in range(12)]
    gated, wiring, calls = T._embedding_gated(
        live_env, root / "f2", env.plan, run_id="p2-live-probe-batch"
    )
    gated.embed(texts)
    print(
        "[F2] texts=12 batch=5 posts=", len(calls),
        "quota_used=", wiring.attempt_budget.used("ingest-index"),
        "ledger_attempts=", wiring.ledger.attempts("index_embedding"),
        "as_dict=", {"calls": gated.as_dict()["calls"], "embed_calls": gated.as_dict()["embed_calls"]},
    )
    tight = T._plan_with_ingest_requests(2)
    T._write_go(root / "f2" / "go-tight.json", ledger=env.ledger, plan=tight)
    p2a.P2_GO_PATH = root / "f2" / "go-tight.json"
    gated2, wiring2, calls2 = T._embedding_gated(
        live_env, root / "f2", tight, run_id="p2-live-probe-tight"
    )
    try:
        gated2.embed(texts)
    except Exception as exc:  # noqa: BLE001 - 只打印拒绝类型
        print("[F2] tight(requests=2) refused:", type(exc).__name__, str(exc)[:90])
    print(
        "[F2] tight posts=", len(calls2),
        "quota_used=", wiring2.attempt_budget.used("ingest-index"),
        "ledger_attempts=", wiring2.ledger.attempts("index_embedding"),
    )


def f6(root: Path) -> None:
    from mktkb.evaluation.p2_scoring import (
        EXECUTION_MODE_LIVE,
        build_gate_rows,
        build_gate_run,
        evaluate_p2_hard_gates,
        load_p2_gate_config,
        score_public_case,
    )

    env = make_env(root / "f6")
    config = load_p2_gate_config()
    chat = T._UsageChatBackend(behaviors=(T.ChatBehavior(answer="位置：B区1号货架第二层"),))
    result, build, _gate = T._run(env, root / "f6", chat=chat, gate_config=config)
    run_dir = build.adapter.paths.run_dir
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    case_rows = [
        json.loads(line)
        for line in (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    product = case_rows[0]["turns"][0]["product"]
    cited = {str(item["source_id"]) for item in product["sources"]}
    cands = {unit for item in product["retrieved"] for unit in item["unit_ids"]}
    print(
        "[F6] status=", result.status,
        "kind=", product["kind"],
        "evidence_in_request=", chat.calls[0]["evidence"],
        "evidence_ids=", len(chat.calls[0]["evidence_ids"]),
        "retrieved=", len(product["retrieved"]),
        "cited=", len(cited),
        "cited_subset=", cited <= cands,
        "outbound=", build.adapter.provider_calls()["outbound_network"],
    )
    cases = T._dataset().cases
    scored = [
        score_public_case(
            case,
            row,
            document_codes={"D01_物品位置表.xlsx": "D01"},
            allowed_doc_codes={"D01"},
            execution_mode=EXECUTION_MODE_LIVE,
        )
        for case, row in zip(cases, case_rows)
    ]
    rows = build_gate_rows(cases, scored)
    hard = evaluate_p2_hard_gates(
        build_gate_run(run_dir=run_dir, manifest=manifest, cases=cases, rows=rows, summary=summary),
        config=config,
        require_trace=False,
    )
    print("[F6] citation_required(with retrieved)=", hard.gate_status["citation_required"])
    tampered = []
    for row in rows:
        copied = dict(row)
        outcome = dict(row.get("outcome") or {})
        if outcome.get("kind") == "answer":
            outcome["retrieved"] = []
        copied["outcome"] = outcome
        tampered.append(copied)
    hard2 = evaluate_p2_hard_gates(
        build_gate_run(run_dir=run_dir, manifest=manifest, cases=cases, rows=tampered, summary=summary),
        config=config,
        require_trace=False,
    )
    print(
        "[F6] citation_required(without retrieved)=", hard2.gate_status["citation_required"],
        "hard_failures=", sorted(hard2.hard_failures),
    )


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="t206-r1-"))
    print("[env] tmp_root=", root)
    f1(root)
    f2(root)
    f6(root)
    print("[env] shared_paths_untouched: P2_GO_PATH/ledger/budget 全部是 tmp 副本")


if __name__ == "__main__":
    main()
