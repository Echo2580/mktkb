"""按 1500 的新计划重签 4 份 v3 GO（本包自建）。

边界
----
- 只写 4 份 GO（r0 固定槽 + r1..r3 `.pending.json`）与归档件；账本/预算/计划/语料一字未改。
- 字段集与 `p2_authorization._GO_KEYS/_GO_SCOPE_KEYS` 逐键相同；钱口径不变
  （项目 40、阶段 20、单请求 0.5），只改 `scope.max_requests`（1160→1500）与
  `scope.plan_sha256`（新计划）；`nonce`/`issued_utc`/`authorization` 散文、`budget_ledger_sha256`
  （历史前缀）随之刷新。
- 旧 GO 先按字节归档为 `P2-LIVE-GO.v3-max1500-r{n}.previous.archived.json`（不覆盖任何既有归档）。
- 每份新 GO 写盘前用 `p2_authorization._check_go_payload` 逐份复核（只读、零发送）。

用法（cwd=仓库根）：
    .venv\\Scripts\\python.exe <本文件> --index <plan-index.json> --out <evidence.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(REPO / "backend" / "src"))

from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation.p2_contracts import P2RunPlan, payload_sha256  # noqa: E402
from mktkb.live_authorization import historical_prefix_sha256  # noqa: E402

PM = REPO / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM"
FIXED = PM / "P2-LIVE-GO.json"
MAX_REQUESTS = 1500
ISSUED_UTC = "2026-11-15T16:40:00+08:00"
EXPIRES_UTC = "2026-11-29T05:00:00+08:00"
LEDGER_REL = "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
OPERATIONS = ["answer", "index_embedding", "query_embedding", "query_expansion", "rerank"]
COST_CENTERS = {"answer_retrieval": 8.5, "ocr": 6.5, "judge": 3.0, "independent": 2.0}
MONEY_KEYS = ("budget_total_limit_cny", "scope.stage_limits_cny.P2-LIVE", "scope.max_request_cny")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target(run_index: int) -> Path:
    return FIXED if run_index == 0 else PM / f"P2-LIVE-GO.v3-r{run_index}.pending.json"


def _archive(run_index: int) -> Path:
    return PM / f"P2-LIVE-GO.v3-max1500-r{run_index}.previous.archived.json"


def _go_payload(plan: P2RunPlan, ledger_sha: str, *, run_index: int, scenario: str) -> dict:
    return {
        "authorization": (
            f"Owner 2026-11-15 pre-auth: H2 v3 run{run_index} ({scenario}); 40 CNY total; "
            f"{MAX_REQUESTS} cumulative requests; 0.5 CNY/request; P2-LIVE 20 CNY; zero retry"
        ),
        "budget_ledger_path": LEDGER_REL,
        "budget_ledger_sha256": ledger_sha,
        "budget_total_limit_cny": float(plan.project_total_limit_cny),
        "document": "P2-LIVE-GO",
        "expires_utc": EXPIRES_UTC,
        "issued_by": "PM (lead) — pre-authorized by owner 2026-11-15",
        "issued_utc": ISSUED_UTC,
        "nonce": secrets.token_hex(16),
        "schema_version": "p2-live-go/v0.1",
        "scope": {
            "cost_centers_cny": dict(COST_CENTERS),
            "max_request_cny": 0.5,
            "max_requests": MAX_REQUESTS,
            "operations": list(OPERATIONS),
            "plan_id": plan.plan_id,
            "plan_sha256": plan.plan_sha256,
            "stage_limits_cny": {"P2-LIVE": 20.0},
        },
        "stage": plan.stage,
    }


def _flatten(payload: dict) -> dict:
    out = {}
    for key, value in payload.items():
        if key == "scope":
            for sub, item in value.items():
                if sub == "stage_limits_cny":
                    for stage, amount in item.items():
                        out[f"scope.stage_limits_cny.{stage}"] = amount
                else:
                    out[f"scope.{sub}"] = item
        else:
            out[key] = value
    return out


def _diff(before: dict, after: dict) -> dict:
    flat_before, flat_after = _flatten(before), _flatten(after)
    changed = {
        key: {"before": flat_before.get(key), "after": flat_after.get(key)}
        for key in sorted(set(flat_before) | set(flat_after))
        if flat_before.get(key) != flat_after.get(key)
    }
    return {
        "changed_fields": changed,
        "changed_keys": sorted(changed),
        "money_fields_unchanged": {
            key: flat_after.get(key) for key in MONEY_KEYS
        },
        "money_unchanged": all(flat_before.get(k) == flat_after.get(k) for k in MONEY_KEYS),
        "only_expected_fields_changed": sorted(changed)
        == sorted(
            [
                "authorization",
                "budget_ledger_sha256",
                "issued_utc",
                "nonce",
                "scope.max_requests",
                "scope.plan_sha256",
            ]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    index = json.loads(Path(args.index).read_text(encoding="utf-8"))
    ledger_sha = historical_prefix_sha256(p2a.P2_LEDGER_PATH)
    budget_before = _sha(Path(p2a.P2_BUDGET_PATH))
    ledger_before = _sha(Path(p2a.P2_LEDGER_PATH))
    rows = []
    for run in index["runs"]:
        run_index = int(run["run_index"])
        plan = P2RunPlan.from_dict(
            json.loads(Path(run["plan_file"]).read_text(encoding="utf-8"))
        )
        if plan.plan_sha256 != run["plan_sha256"]:
            raise SystemExit(f"plan sha mismatch for run {run_index}")
        if int(plan.max_requests) != MAX_REQUESTS:
            raise SystemExit(f"plan max_requests mismatch for run {run_index}")
        target, archive = _target(run_index), _archive(run_index)
        if archive.exists():
            raise SystemExit(f"archive already exists: {archive.name}")
        before_bytes = target.read_bytes()
        before_payload = json.loads(before_bytes.decode("utf-8"))
        archive.write_bytes(before_bytes)  # 归档改前字节，不覆盖任何既有归档
        payload = _go_payload(
            plan, ledger_sha, run_index=run_index, scenario=str(run["scenario_id"])
        )
        p2a._check_go_payload(payload, plan, p2a._utcnow())  # 写盘前逐份复核（零发送）
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        target.write_bytes(text.encode("utf-8"))
        diff = _diff(before_payload, payload)
        rows.append(
            {
                "run_index": run_index,
                "scenario_id": run["scenario_id"],
                "business_date": run["business_date"],
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
                "plan_total_requests": int(plan.total_requests),
                "target": str(target.relative_to(REPO)).replace("\\", "/"),
                "archive": str(archive.relative_to(REPO)).replace("\\", "/"),
                "before_sha256": hashlib.sha256(before_bytes).hexdigest(),
                "before_bytes": len(before_bytes),
                "before_scope_max_requests": int(before_payload["scope"]["max_requests"]),
                "before_plan_sha256": before_payload["scope"]["plan_sha256"],
                "after_sha256": _sha(target),
                "after_bytes": target.stat().st_size,
                "after_payload_sha256": payload_sha256(payload),
                "after_scope_max_requests": int(payload["scope"]["max_requests"]),
                "after_plan_sha256": payload["scope"]["plan_sha256"],
                "nonce_len": len(payload["nonce"]),
                "diff": diff,
            }
        )
    evidence = {
        "schema_version": "p2-h2v3-final-go-resign/v0.1",
        "reason": "主人把授权总量提到 1500；1160 时已用 1099、余 61 < 全量复跑约 126，四 run 无法开跑。",
        "max_requests": MAX_REQUESTS,
        "issued_utc": ISSUED_UTC,
        "expires_utc": EXPIRES_UTC,
        "ledger_historical_prefix_sha256": ledger_sha,
        "zero_write": {
            "ledger_sha_before": ledger_before,
            "ledger_sha_after": _sha(Path(p2a.P2_LEDGER_PATH)),
            "budget_sha_before": budget_before,
            "budget_sha_after": _sha(Path(p2a.P2_BUDGET_PATH)),
        },
        "runs": rows,
    }
    zero = evidence["zero_write"]
    zero["ledger_unchanged"] = zero["ledger_sha_before"] == zero["ledger_sha_after"]
    zero["budget_unchanged"] = zero["budget_sha_before"] == zero["budget_sha_after"]
    Path(args.out).write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "zero_write": zero,
                "runs": [
                    {
                        "run": row["run_index"],
                        "before": row["before_sha256"][:12],
                        "after": row["after_sha256"][:12],
                        "max_requests": [row["before_scope_max_requests"],
                                         row["after_scope_max_requests"]],
                        "changed_keys": row["diff"]["changed_keys"],
                        "money_unchanged": row["diff"]["money_unchanged"],
                        "only_expected": row["diff"]["only_expected_fields_changed"],
                    }
                    for row in rows
                ],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
