"""独立探针 1：硬顶 1600 治理（计划层 + GO 层 + 同值不变式 + P1 不构成追加授权）。

只读：不写账本/预算/GO；全部在内存中构造。运行：
  cd backend && ..\.venv\Scripts\python.exe ..\docs\reports\OBS-EVAL\P2\T207-FIX-B\evidence\verify\probe1_hardcap.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb import live_authorization as la  # noqa: E402
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation import p2_contracts as c  # noqa: E402
from mktkb.evaluation.p2_contracts import P2ContractError, P2RunPlan  # noqa: E402

PLAN_ART = ROOT / "docs/reports/OBS-EVAL/P2/T201/candidates/p2-run-plan-v0_1.CANDIDATE-DRAFT.json"
NOW = datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)
out: list[str] = []


def say(line: str) -> None:
    out.append(line)
    print(line)


def base_plan_dict() -> dict:
    return json.loads(PLAN_ART.read_text(encoding="utf-8"))


def plan(max_requests: int) -> P2RunPlan:
    data = base_plan_dict()
    data["max_requests"] = max_requests
    return P2RunPlan.from_dict(data)


def go_payload(p: P2RunPlan, *, max_requests: int) -> dict:
    return {
        "document": p2a.P2_GO_DOCUMENT,
        "schema_version": p2a.P2_GO_SCHEMA_VERSION,
        "stage": p.stage,
        "authorization": "PROBE-ONLY（零真实调用）",
        "issued_by": "independent-verifier",
        "nonce": "probe-nonce-0123456789abcdef",
        "issued_utc": "2026-11-11T00:00:00+00:00",
        "expires_utc": "2026-11-12T00:00:00+00:00",
        "budget_ledger_path": "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl",
        "budget_ledger_sha256": "0" * 64,
        "budget_total_limit_cny": p.project_total_limit_cny,
        "scope": {
            "plan_id": p.plan_id,
            "plan_sha256": p.plan_sha256,
            "operations": list(p.operations),
            "cost_centers_cny": dict(p.cost_centers_cny),
            "stage_limits_cny": {c.P2_STAGE: p.stage_limit_cny},
            "max_requests": max_requests,
            "max_request_cny": 0.5,
        },
    }


say("== 1. 两处常量 ==")
say(f"HARD_MAX_REQUESTS            = {c.HARD_MAX_REQUESTS}")
say(f"live_authorization.MAX_GO_REQUESTS = {la.MAX_GO_REQUESTS}")
say(f"equal(invariant)             = {c.HARD_MAX_REQUESTS == la.MAX_GO_REQUESTS}")

say("")
say("== 2. 计划层：1600 可用 / 1601 拒绝（base=T201 候选计划原件，只改 max_requests） ==")
ok = plan(1600)
say(f"plan(max_requests=1600).max_requests = {ok.max_requests}  total_requests={ok.total_requests}")
for value in (1601, 2000, 2001):
    try:
        plan(value)
        say(f"plan(max_requests={value}) -> ACCEPTED (BAD)")
    except P2ContractError as exc:
        say(f"plan(max_requests={value}) -> REFUSED reason={exc.reason}")

say("")
say("== 3. GO 层：_check_go_payload 直接调用（1600 通过 / 1601 因硬顶拒绝） ==")
for value in (1600, 1601):
    try:
        issued, expires = p2a._check_go_payload(go_payload(ok, max_requests=value), ok, NOW)
        say(f"GO scope.max_requests={value} -> ACCEPTED issued={issued.isoformat()}")
    except Exception as exc:  # noqa: BLE001
        reason = getattr(exc, "reason", type(exc).__name__)
        say(f"GO scope.max_requests={value} -> REFUSED reason={reason} msg={exc}")

say("")
say("== 4. P1 已签 GO 的自身额度不被追授权（读真实文件，只读） ==")
p1_go = ROOT / "docs/evidence/LOCAL-R1-20261101/PM/S2-LIVE-GO.json"
payload = json.loads(p1_go.read_text(encoding="utf-8"))
say(f"P1 GO scope.max_requests = {payload.get('scope', {}).get('max_requests')}")
say(f"P1 GO 文件 sha256 未变（见 review 的到达/离开哈希）")
say("MAX_GO_REQUESTS 只做 _gate_int(... maximum=) 的**合法性上限**，闸门实际额度取自 GO 自身 scope.max_requests；")
say("因此已签 GO 仍是它自己写的数（见源码 live_authorization.py:167/207/574/717）。")

say("")
say("== 5. 事实交代：P1 侧**新开** GO 的合法性上限也从 1000 抬到 1600（经理落盘的共同天花板） ==")
for value in (1000, 1001, 1600, 1601):
    try:
        la._gate_int(value, "GO 累计请求上限", maximum=la.MAX_GO_REQUESTS)
        say(f"_gate_int(max_requests={value}, maximum=MAX_GO_REQUESTS) -> ACCEPTED")
    except Exception as exc:  # noqa: BLE001
        say(f"_gate_int(max_requests={value}, maximum=MAX_GO_REQUESTS) -> REFUSED {type(exc).__name__}: {exc}")
say("（HEAD 的 maximum=1000：1001 会被拒；现在 1001..1600 可过格式校验，但仍受该 GO 自身额度与预算约束）")

(ROOT / "docs/reports/OBS-EVAL/P2/T207-FIX-B/evidence/verify/probe1_hardcap.out.txt").write_text(
    "\n".join(out) + "\n", encoding="utf-8"
)
