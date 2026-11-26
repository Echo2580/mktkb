"""独立验收：预算回退后重新生成 4 份 GO（limit 40），并做只读预检/授权复核。

不读私有题面/答案；只读计划文档（case_id 不回显）、账本快照与预算。
输出：rollback-40/go/*.json + rollback-40/go-regeneration.json（无 case_id）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[7]
SRC = REPO / "backend" / "src"
sys.path.insert(0, str(SRC))

from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation.p2_contracts import COST_CENTERS, P2RunPlan  # noqa: E402

OUT_ROOT = Path(r"D:\mktkb-p2-h2v3-20261115\rollback-40")
PLANS = OUT_ROOT / "plans"
GO_DIR = OUT_ROOT / "go"
EVID = OUT_ROOT / "go-regeneration.json"

TAG = "P2-H2V3-20261115"
MAX_REQUESTS = 1137
PROJECT_TOTAL_LIMIT_CNY = 40.0
STAGE_LIMIT_CNY = 20.0
MAX_REQUEST_CNY = 0.5
ISSUED_UTC = "2026-11-15T05:00:00+08:00"
EXPIRES_UTC = "2026-11-29T05:00:00+08:00"
ISSUED_BY = "PM (lead) — pre-authorized by owner 2026-11-15"
SCENARIO_ORDER = (
    "base_b0",
    "base_b0_plus_v01",
    "pre_v05_without_v07",
    "post_v05_without_v01",
)

budget_raw = p2a.P2_BUDGET_PATH.read_bytes()
budget = json.loads(budget_raw.decode("utf-8"))
assert budget["limit_cny"] == PROJECT_TOTAL_LIMIT_CNY, budget["limit_cny"]
snapshot = p2a.read_ledger_snapshot()
now = datetime.now(timezone.utc)


def write_json(path: Path, payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    raw = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    assert not path.exists()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


rows = []
prefix = snapshot.reservation_count
for index, scenario in enumerate(SCENARIO_ORDER):
    plan_path = PLANS / f"run{index}-{scenario}.plan.json"
    plan = P2RunPlan.from_dict(json.loads(plan_path.read_text(encoding="utf-8")))
    assert plan.plan_id == f"{TAG}-r{index}-{scenario}"
    assert plan.max_requests == MAX_REQUESTS
    assert plan.project_total_limit_cny == PROJECT_TOTAL_LIMIT_CNY
    nonce = hashlib.sha256(f"{TAG}:go:r{index}:{plan.plan_sha256}".encode()).hexdigest()[:32]
    go = {
        "document": p2a.P2_GO_DOCUMENT,
        "schema_version": p2a.P2_GO_SCHEMA_VERSION,
        "stage": "P2-LIVE",
        "authorization": (
            f"Owner 2026-11-15 pre-auth: H2 v3 run{index} ({scenario}); 40 CNY total; "
            f"1137 cumulative requests; 0.5 CNY/request; P2-LIVE 20 CNY; zero retry"
        ),
        "issued_by": ISSUED_BY,
        "nonce": nonce,
        "issued_utc": ISSUED_UTC,
        "expires_utc": EXPIRES_UTC,
        "budget_ledger_path": "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl",
        "budget_ledger_sha256": snapshot.historical_prefix_sha256,
        "budget_total_limit_cny": PROJECT_TOTAL_LIMIT_CNY,
        "scope": {
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "operations": list(plan.operations),
            "cost_centers_cny": {c: float(plan.cost_centers_cny[c]) for c in COST_CENTERS},
            "stage_limits_cny": {"P2-LIVE": STAGE_LIMIT_CNY},
            "max_requests": MAX_REQUESTS,
            "max_request_cny": MAX_REQUEST_CNY,
        },
    }
    go_rec = write_json(GO_DIR / f"P2-LIVE-GO.v3-r{index}.json", go)

    snap_before = replace(snapshot, reservation_count=prefix)
    pre = p2a.preflight_p2(plan, snap_before)
    auth = p2a.authorize_p2(
        plan, go_payload=go, budget_payload=budget, ledger_snapshot=snap_before, now=now
    )
    assert pre.ok, (index, pre.reasons)
    assert auth.max_requests == MAX_REQUESTS
    assert auth.plan_sha256 == plan.plan_sha256
    rows.append(
        {
            "run_index": index,
            "scenario_id": scenario,
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "plan_file_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "go_path": go_rec["path"],
            "go_sha256": go_rec["sha256"],
            "go_bytes": go_rec["bytes"],
            "nonce": nonce,
            "budget_total_limit_cny": PROJECT_TOTAL_LIMIT_CNY,
            "max_requests": MAX_REQUESTS,
            "stage_limit_cny": STAGE_LIMIT_CNY,
            "total_requests": plan.total_requests,
            "preflight_ok": pre.ok,
            "preflight_reasons": list(pre.reasons),
            "preflight_total_limit_cny": pre.total_limit_cny,
            "authorization_requests_remaining": auth.requests_remaining,
            "authorization_production_ready": auth.production_ready,
        }
    )
    prefix += plan.total_requests

evidence = {
    "schema_version": "v3-fix1-independent-go-regeneration/v0.1",
    "generated_utc": now.isoformat(),
    "budget": {
        "path": str(p2a.P2_BUDGET_PATH),
        "sha256": hashlib.sha256(budget_raw).hexdigest(),
        "limit_cny": budget["limit_cny"],
    },
    "ledger": {
        "path": str(p2a.P2_LEDGER_PATH),
        "sha256": snapshot.ledger_sha256,
        "historical_prefix_sha256": snapshot.historical_prefix_sha256,
        "reservation_count": snapshot.reservation_count,
    },
    "dial": {
        "project_total_limit_cny": PROJECT_TOTAL_LIMIT_CNY,
        "max_requests": MAX_REQUESTS,
        "stage_limit_cny": STAGE_LIMIT_CNY,
        "max_request_cny": MAX_REQUEST_CNY,
    },
    "runs": rows,
    "wrote_ledger": False,
    "sent_http": False,
}
EVID.write_text(json.dumps(evidence, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                encoding="utf-8")
print(json.dumps({"budget": evidence["budget"], "ledger_sha": snapshot.ledger_sha256,
                  "runs": [{k: r[k] for k in ("run_index", "scenario_id", "plan_sha256",
                                              "go_sha256", "preflight_ok",
                                              "authorization_requests_remaining")} for r in rows]},
                 ensure_ascii=False, indent=1))
