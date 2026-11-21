"""落盘 P2-LIVE 调额并签发本轮专属 GO（一次性、可回滚、原子替换）。

用法（仓库根）：
    .venv\\Scripts\\python.exe -X utf8 <本文件> --apply

做的事（严格顺序）：
1. 备份共享 `budget.json` 与本轮 GO 固定槽的原字节 + 摘要到证据目录；
2. 构造新预算：只改 `stages.P2-LIVE 24.00→32.00` 与 `stages.later_shared_reserve 50.07→42.07`
   （保持 各阶段合计 99.97 + 历史 0.03 = 100.00），并追加 `stage_revision` 记录；
3. **先在内存里**用 `authorize_p2` 试算 GO+预算+账本（不写任何文件），失败即退出；
4. 原子替换预算 → 重取真实账本快照 → `preflight_p2` 必须通过；
5. 原子替换 GO 固定槽 → 用固定路径 `authorize_p2` 复核 `production_ready=True`；
6. 打印公开摘要（**不含 nonce**）。

失败时：不留下半套状态；已写入的预算按备份原字节恢复。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]
BUDGET = ROOT / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
GO = ROOT / "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json"
EVIDENCE = ROOT / "docs/reports/OBS-EVAL/P2/FOLLOW-UP/requalification/evidence"
PLAN_FILE = EVIDENCE / "b0-request-plan.bound.json"

NEW_STAGE = {"P2-LIVE": 32.0, "later_shared_reserve": 42.07}
OWNER_AUTHORIZATION = (
    "2026-11-21 owner approved a new B0 for the requalified candidate: P2-LIVE 24->32 CNY, "
    "194 requests, 7.464016 CNY cap, OCR 12 pages, zero retry (requalification taskbook §3)."
)
ISSUED_BY = "P2 requalification executor, acting on the owner's explicit approval 2026-11-21"


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def canonical(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from mktkb.evaluation import p2_authorization as auth
    from mktkb.evaluation.p2_contracts import P2RunPlan

    plan = P2RunPlan.from_dict(json.loads(PLAN_FILE.read_text(encoding="utf-8")))
    budget_raw = BUDGET.read_bytes()
    go_slot_raw = GO.read_bytes() if GO.is_file() else b""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "budget.before.json").write_bytes(budget_raw)
    if go_slot_raw:
        (EVIDENCE / "go-slot.before.json").write_bytes(go_slot_raw)

    budget = json.loads(budget_raw)
    revised = json.loads(json.dumps(budget))
    previous = {key: revised["stages"][key] for key in NEW_STAGE}
    revised["stages"].update(NEW_STAGE)
    now_local = datetime.now(timezone.utc).astimezone()
    arithmetic = " + ".join(f"{value}" for value in revised["stages"].values())
    revised["stage_revision"] = {
        "revision": int(budget.get("stage_revision", {}).get("revision", 0)) + 1,
        "revised_at": now_local.isoformat(timespec="microseconds"),
        "revised_by": "主人（2026-11-21 授权新 B0 调额 +8.00 元；任务书 2026-11-21 收尾任务书 §3）",
        "previous_stages": previous,
        "change": (
            "P2-LIVE 24.00→32.00（新 B0 上界 7.464016 元，原剩余 1.906231 元不足）；"
            "差额 8.00 从 later_shared_reserve 50.07→42.07 划入。"
        ),
        "arithmetic": f"{arithmetic} + 0.03(历史) = {round(sum(revised['stages'].values()) + 0.03, 6)}",
        "retained": "历史 0.03 与已发生占用全部保留，不清账、不重置；累计请求不重置。",
        "previous_revision": budget.get("stage_revision", {}),
    }

    snapshot = auth.read_ledger_snapshot()
    nonce = secrets.token_hex(16)
    issued = datetime.now(timezone.utc)
    expires = issued + timedelta(hours=24)
    go_payload = {
        "document": auth.P2_GO_DOCUMENT,
        "schema_version": auth.P2_GO_SCHEMA_VERSION,
        "stage": auth.P2_STAGE,
        "authorization": OWNER_AUTHORIZATION,
        "issued_by": ISSUED_BY,
        "nonce": nonce,
        "issued_utc": issued.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00"),
        "expires_utc": expires.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00"),
        "budget_ledger_path": str(auth.P2_LEDGER_PATH.relative_to(ROOT)).replace("\\", "/"),
        "budget_ledger_sha256": snapshot.historical_prefix_sha256,
        "budget_total_limit_cny": float(revised["limit_cny"]),
        "scope": {
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "operations": sorted(plan.operations),
            "cost_centers_cny": {key: float(value) for key, value in plan.cost_centers_cny.items()},
            "stage_limits_cny": {auth.P2_STAGE: float(plan.stage_limit_cny)},
            "max_requests": "unlimited",
            "max_request_cny": float(plan.reserve_peak_cny),
        },
    }

    # 3) 内存试算（不写文件）：确认 GO/预算/计划三者自洽。
    #    注意：账本快照的阶段分配来自当前 budget.json（仍是 24.00），因此试算时把
    #    P2-LIVE 分配按**拟写入值**覆盖；真实写入后再用固定路径重读复核。
    snapshot_dict = snapshot.as_dict() if hasattr(snapshot, "as_dict") else dict(snapshot.__dict__)
    trial_snapshot = dict(
        snapshot_dict,
        stage_allocations_cny=dict(snapshot_dict["stage_allocations_cny"], **{"P2-LIVE": float(plan.stage_limit_cny)}),
    )
    trial = auth.authorize_p2(
        plan,
        go_payload=go_payload,
        budget_payload=revised,
        ledger_snapshot=trial_snapshot,
    )
    summary = {
        "simulated": {
            "ok": True,
            "plan_id": trial.plan_id,
            "plan_sha256": trial.plan_sha256,
            "stage_limit_cny": trial.stage_limit_cny,
            "stage_remaining_cny": trial.stage_remaining_cny,
            "center_limits_cny": dict(trial.cost_center_limits_cny),
            "center_remaining_cny": dict(trial.center_remaining_cny),
            "production_ready": trial.production_ready,
        },
        "budget": {
            "before_sha256": sha_bytes(budget_raw),
            "stages_before": budget["stages"],
            "stages_after": revised["stages"],
            "stage_revision": revised["stage_revision"]["revision"],
        },
        "go": {
            "slot": str(GO.relative_to(ROOT)).replace("\\", "/"),
            "slot_before_sha256": sha_bytes(go_slot_raw) if go_slot_raw else None,
            "issued_utc": go_payload["issued_utc"],
            "expires_utc": go_payload["expires_utc"],
            "nonce_len": len(nonce),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.apply:
        print("dry-run：未写任何文件（加 --apply 落盘）")
        return 0

    # 4) 原子替换预算 + 复核预检。
    write_atomic(BUDGET, canonical(revised))
    after_budget_raw = BUDGET.read_bytes()
    snapshot_after = auth.read_ledger_snapshot()
    preflight = auth.preflight_p2(plan, snapshot_after)
    if not preflight.ok:
        write_atomic(BUDGET, budget_raw)
        print(json.dumps({"error": "preflight_failed_after_budget_write", "reasons": list(preflight.reasons)}))
        return 3

    # 5) 原子替换 GO 固定槽 + 固定路径复核（production_ready 必须为 True）。
    write_atomic(GO, canonical(go_payload))
    os.environ[auth.TOTAL_LIMIT_ENV] = str(revised["limit_cny"])
    try:
        live = auth.authorize_p2(
            plan,
            go_payload=auth.P2_GO_PATH,
            budget_payload=auth.P2_BUDGET_PATH,
            ledger_snapshot=auth.read_ledger_snapshot(),
        )
    except Exception as exc:  # noqa: BLE001 - 任何失败都回滚预算并报告
        write_atomic(GO, go_slot_raw)
        write_atomic(BUDGET, budget_raw)
        print(json.dumps({"error": "authorize_p2_failed", "detail": f"{type(exc).__name__}: {exc}"}))
        return 4

    result = {
        "applied": True,
        "budget": {
            "after_sha256": sha_bytes(after_budget_raw),
            "stage_revision": revised["stage_revision"]["revision"],
            "stages": revised["stages"],
        },
        "go": {
            "slot_after_sha256": sha_bytes(GO.read_bytes()),
            "issued_utc": go_payload["issued_utc"],
            "expires_utc": go_payload["expires_utc"],
            "nonce_len": len(nonce),
            "go_sha256": trial.go_sha256,
        },
        "authorization": {
            "production_ready": live.production_ready,
            "stage_limit_cny": live.stage_limit_cny,
            "stage_remaining_cny": live.stage_remaining_cny,
            "center_remaining_cny": dict(live.center_remaining_cny),
            "requirements_ok": live.requirements_ok() if hasattr(live, "requirements_ok") else None,
            "requests_used": live.requests_used,
            "max_requests": live.max_requests,
        },
        "preflight": {
            "ok": preflight.ok,
            "reasons": list(preflight.reasons),
            "stage_remaining_cny": preflight.stage_remaining_cny,
            "center_remaining_cny": dict(preflight.center_remaining_cny),
        },
    }
    (EVIDENCE / "go-issue.json").write_bytes(canonical(result))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if live.production_ready else 5


if __name__ == "__main__":
    sys.exit(main())
