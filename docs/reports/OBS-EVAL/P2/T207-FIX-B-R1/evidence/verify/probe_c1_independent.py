"""P2-T207-FIX-B-R1 独立验收探针：C1（J1 拒绝轮的保守占用）修复前后对照。

只读：复用 test_p2_live_wiring.py 的离线脚手架（tmp 账本/预算/GO、MockTransport），
不碰仓库共享账本/预算/GO；零真实出站。用法：

    python probe_c1_independent.py            # 当前工作区（修复后）
    PYTHONPATH=<head-injection-dir> python probe_c1_independent.py   # HEAD 的 p2_runner（修复前）

输出单个 JSON（ASCII 转义），包含账本 result 保守合计、summary、run_result 与逐请求行。
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = next(
    p
    for p in Path(__file__).resolve().parents
    if (p / "backend" / "src" / "mktkb" / "evaluation" / "p2_runner.py").exists()
)
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND / "tests"))
sys.path.insert(0, str(BACKEND / "src"))

_SPEC = importlib.util.spec_from_file_location(
    "probe_live_wiring_helpers", BACKEND / "tests" / "evaluation" / "test_p2_live_wiring.py"
)
w = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = w
assert _SPEC.loader is not None
_SPEC.loader.exec_module(w)

MP = pytest.MonkeyPatch()
BASE = Path(tempfile.mkdtemp(prefix="p2-fixbr1-probe-"))
RUN_NO = 0


def make_env(name: str) -> SimpleNamespace:
    root = BASE / name
    root.mkdir(parents=True, exist_ok=True)
    ledger = root / "live-ledger.jsonl"
    budget = root / "budget.json"
    go = root / "P2-LIVE-GO.json"
    plan = w._plan()
    w._write_ledger(ledger)
    w._write_budget(budget)
    w._write_go(go, ledger=ledger, plan=plan)
    MP.setattr(w.p2a, "P2_LEDGER_PATH", ledger)
    MP.setattr(w.p2a, "P2_BUDGET_PATH", budget)
    MP.setattr(w.p2a, "P2_GO_PATH", go)
    MP.setenv(w.live_authorization.TOTAL_LIMIT_ENV, str(w.TOTAL_LIMIT_CNY))
    return SimpleNamespace(ledger=ledger, budget=budget, go=go, plan=plan, root=root)


def run_once(env: SimpleNamespace, out_dir: Path, chat):
    global RUN_NO
    RUN_NO += 1
    run_id = f"p2-probe-c1-{RUN_NO}"
    gate = w.p2_live.open_live_gate(env.plan, run_id=run_id, now=w.NOW)
    ingest_plan = w.P2IngestPlan(
        sources=(w.IngestSource(path=w.D01),), label="probe-c1"
    )

    async def go():
        return await w.p2_live.run_live_p2(
            env.plan,
            run_id=run_id,
            out_dir=out_dir,
            dataset=w._dataset("Q01"),
            ingest_plan=ingest_plan,
            gate=gate,
            env={"MKTKB_OCR_DISABLED": "0"},
            env_overrides=w.LIVE_ENV_OVERRIDES,
            transports=w._transports(chat),
            now=w.NOW,
        )

    return asyncio.run(go())


class RejectTotalMismatch(w._UsageChatBackend):
    """官方 usage 自相矛盾：total_tokens=999 != 64+32，J1 必须拒绝。"""

    def _completion(self, request, content, *, call):
        response = super()._completion(request, content, call=call)
        payload = json.loads(response.content.decode("utf-8"))
        payload["usage"]["total_tokens"] = 999
        return w.httpx.Response(200, json=payload, request=request)


def collect(label: str, result, build, env: SimpleNamespace) -> dict:
    run_dir = build.adapter.paths.run_dir
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    results = w._results(env.ledger)
    held_total = round(
        sum(float(row.get("conservative_charge_cny") or 0.0) for row in results), 8
    )
    answer_rows = [row for row in results if row.get("kind") == "chat"]
    request_rows = [
        json.loads(line)
        for line in (run_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    requests = summary["requests"]
    state = requests.get("rejected_rounds")
    return {
        "label": label,
        "status": result.status,
        "stop_code": result.stop_code,
        "requests_sent": result.requests_sent,
        "run_result_settled_cny": result.settled_cny,
        "run_result_by_center_cny": dict(result.by_center_cny),
        "summary_requests": requests,
        "ledger_result_rows": results,
        "ledger_answer_result_rows": answer_rows,
        "ledger_held_total_cny": held_total,
        "requests_jsonl": request_rows,
        "outbound_attempts": summary["network"]["outbound_attempts"],
        "invariants": {
            "rejected_rounds_key_present": "rejected_rounds" in requests,
            "rejected_rounds": state,
            "mutually_exclusive_count_sum": int(requests["settled_success"])
            + int(requests["settled_failure"])
            + int(requests["unpaid_rounds"])
            + int(state or 0),
            "rounds_reaching_settlement": len(request_rows),
            "summary_held_equals_ledger_total": requests["conservative_held_cny"]
            == held_total,
            "summary_minus_ledger_gap_cny": round(
                float(requests["conservative_held_cny"]) - held_total, 8
            ),
            "run_result_settled_equals_sum_by_center": round(
                float(run_result["settled_cny"]), 8
            )
            == round(sum(float(v) for v in run_result["by_center_cny"].values()), 8),
        },
    }


def main() -> int:
    import importlib

    runner = importlib.import_module("mktkb.evaluation.p2_runner")
    report = {"runner_file": runner.__file__}

    env_reject = make_env("reject")
    result, build = run_once(
        env_reject,
        env_reject.root / "run",
        RejectTotalMismatch(behaviors=(w.ChatBehavior(answer="位置：B区1号货架第二层"),)),
    )
    report["j1_rejected"] = collect("j1_rejected", result, build, env_reject)

    env_normal = make_env("normal")
    result, build = run_once(
        env_normal,
        env_normal.root / "run",
        w._UsageChatBackend(behaviors=(w.ChatBehavior(answer="位置：B区1号货架第二层"),)),
    )
    report["normal_success"] = collect("normal_success", result, build, env_normal)

    MP.undo()
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
