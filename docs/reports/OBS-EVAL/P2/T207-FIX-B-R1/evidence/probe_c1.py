"""T207-FIX-B-R1 / C1 复现探针：answer 轮 J1 结算被拒时的保守占用记账。

零真实调用：全部出站都被 httpx.MockTransport 接住；账本/预算/GO 全部是 tmp 副本
（只在本进程内把 p2a 的固定路径常量指向 tmp），不写仓库共享文件。

用法（任意 cwd；脚本自己 chdir 到 backend）：
    D:/GPT项目/市场部AI知识库/.venv/Scripts/python.exe \
        docs/reports/OBS-EVAL/P2/T207-FIX-B-R1/evidence/probe_c1.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[6]
BACKEND = ROOT / "backend"
os.chdir(BACKEND)
for entry in (str(BACKEND / "tests" / "evaluation"), str(BACKEND / "tests")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import httpx  # noqa: E402

import test_p2_live_wiring as live  # noqa: E402
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402

BOUND_CHAT_CNY = 0.018688


class _TotalMismatchChat(live._UsageChatBackend):
    """官方 usage 自相矛盾（total_tokens != prompt+completion）：J1 必须拒绝结算。"""

    def _completion(self, request, content, *, call):
        response = super()._completion(request, content, call=call)
        payload = json.loads(response.content.decode("utf-8"))
        payload["usage"]["total_tokens"] = 999
        return httpx.Response(200, json=payload, request=request)


def _run_scenario(label: str, chat_factory) -> dict:
    root = Path(tempfile.mkdtemp(prefix=f"p2-c1-{label}-"))
    ledger = root / "live-ledger.jsonl"
    budget = root / "budget.json"
    go = root / "P2-LIVE-GO.json"
    plan = live._plan()
    live._write_ledger(ledger)
    live._write_budget(budget)
    live._write_go(go, ledger=ledger, plan=plan)
    p2a.P2_LEDGER_PATH = ledger
    p2a.P2_BUDGET_PATH = budget
    p2a.P2_GO_PATH = go
    os.environ[live.live_authorization.TOTAL_LIMIT_ENV] = str(live.TOTAL_LIMIT_CNY)
    env = SimpleNamespace(ledger=ledger, budget=budget, go=go, plan=plan, root=root)
    result, build, _gate = live._run(env, root, chat=chat_factory())
    run_dir = build.adapter.paths.run_dir
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    run_result = json.loads((run_dir / "run_result.json").read_text(encoding="utf-8"))
    results = live._results(ledger)
    requests = summary["requests"]
    held_ledger = round(
        sum(float(row.get("conservative_charge_cny") or 0.0) for row in results), 8
    )
    answer_rows = [row for row in results if row.get("kind") == "chat"]
    answer_holds = [round(float(row.get("conservative_charge_cny") or 0.0), 8) for row in answer_rows]
    providers = build.adapter.provider_calls()
    record = {
        "label": label,
        "status": result.status,
        "stop_code": result.stop_code,
        "requests_sent": int(result.requests_sent),
        "run_result.settled_cny": round(float(result.settled_cny), 8),
        "summary.conservative_held_cny": round(float(requests["conservative_held_cny"]), 8),
        "summary.provider_billed_cny": round(float(requests["provider_billed_cny"]), 8),
        "summary.rejected_rounds": requests.get("rejected_rounds", "<key-absent>"),
        "summary.settled_success": requests["settled_success"],
        "summary.settled_failure": requests["settled_failure"],
        "summary.unpaid_rounds": requests["unpaid_rounds"],
        "summary.billed_cny": requests["billed_cny"],
        "ledger.result_conservative_sum": held_ledger,
        "ledger.answer_result_conservative": answer_holds,
        "ledger.answer_error_codes": [row.get("error_code") for row in answer_rows],
        "ledger.answer_status": [row.get("status") for row in answer_rows],
        "run_result.by_center_cny": run_result["by_center_cny"],
        "run_result.attempts_by_center_sum": round(
            sum(float(value) for value in (run_result.get("attempts_by_center_cny") or {}).values()), 8
        ),
        "outbound_network": providers["outbound_network"],
        "held == ledger_sum": round(float(requests["conservative_held_cny"]), 8) == held_ledger,
        "attempts_by_center_sum == held": round(
            sum(float(value) for value in (run_result.get("attempts_by_center_cny") or {}).values()), 8
        )
        == round(float(requests["conservative_held_cny"]), 8),
    }
    return record


def main() -> None:
    rejected = _run_scenario(
        "j1-rejected",
        lambda: _TotalMismatchChat(behaviors=(live.ChatBehavior(answer="位置：B区1号货架第二层"),)),
    )
    normal = _run_scenario("normal", lambda: live._UsageChatBackend(
        behaviors=(live.ChatBehavior(answer="位置：B区1号货架第二层"),)
    ))
    for record in (rejected, normal):
        print(f"=== {record['label']} ===")
        for key, value in record.items():
            if key != "label":
                print(f"{key} = {value}")
        print()
    checks = {
        "rejected.stop_code == gate_error": rejected["stop_code"] == "gate_error",
        "rejected.answer_conservative == bound": rejected["ledger.answer_result_conservative"]
        == [BOUND_CHAT_CNY],
        "rejected.held == ledger_sum": rejected["held == ledger_sum"],
        "rejected.rejected_rounds == 1": rejected["summary.rejected_rounds"] == 1,
        "rejected.settled_cny == bound": rejected["run_result.settled_cny"] == BOUND_CHAT_CNY,
        "normal.rejected_rounds == 0": normal["summary.rejected_rounds"] == 0,
        "normal.held == ledger_sum": normal["held == ledger_sum"],
        "rejected.attempts_by_center_sum == held": rejected["attempts_by_center_sum == held"],
        "normal.attempts_by_center_sum == held": normal["attempts_by_center_sum == held"],
    }
    print("bound_chat_cny =", BOUND_CHAT_CNY)
    print("C1 判定:")
    for name, ok in checks.items():
        print(f"  {name} -> {ok}")
    if not all(checks.values()):
        print("  -> C1 仍存在（J1 拒绝轮的保守占用未进 summary/run_result）")
        raise SystemExit(1)
    print("  -> C1 已修复")


if __name__ == "__main__":
    main()
