"""按新的 4 份计划签发 4 份 v3 GO（max_requests=1160），旧 GO 先归档、不覆盖。

边界
----
- 只写 4 份 GO（r0 固定槽 + r1..r3 `.pending.json`）与归档件；账本/预算/计划一字未改。
- GO 的字段集与 `p2_authorization._GO_KEYS/_GO_SCOPE_KEYS` 逐键相同；金额口径不变
  （项目 40、阶段 20、单请求 0.5）；只改 `scope.max_requests`（1137→1160）与
  `scope.plan_sha256`（新计划）、`nonce`、`issued_utc`、`authorization` 散文字样。
- 账本绑定沿用不可变历史前缀 SHA（`historical_prefix_sha256`），跑完新事件后仍有效。
- 每份新 GO 在写盘前用 `p2_authorization._check_go_payload` 逐份复核（只读、零发送）。

用法（cwd=仓库根）：.venv\\Scripts\\python.exe <本文件> --index <plan-index.json> --out <evidence.json>
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
MAX_REQUESTS = 1160
ISSUED_UTC = "2026-11-15T08:00:00+08:00"
EXPIRES_UTC = "2026-11-29T05:00:00+08:00"
LEDGER_REL = "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
OPERATIONS = ["answer", "index_embedding", "query_embedding", "query_expansion", "rerank"]
COST_CENTERS = {"answer_retrieval": 8.5, "ocr": 6.5, "judge": 3.0, "independent": 2.0}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target(run_index: int) -> Path:
    if run_index == 0:
        return FIXED
    return PM / f"P2-LIVE-GO.v3-r{run_index}.pending.json"


def _archive(run_index: int) -> Path:
    return PM / f"P2-LIVE-GO.v3-max1160-r{run_index}.previous.archived.json"


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
        target = _target(run_index)
        archive = _archive(run_index)
        if archive.exists():
            raise SystemExit(f"archive already exists: {archive.name}")
        before = target.read_bytes()
        archive.write_bytes(before)  # 归档改前字节，不覆盖任何既有归档
        payload = _go_payload(
            plan, ledger_sha, run_index=run_index, scenario=str(run["scenario_id"])
        )
        # 写盘前逐份复核：字段集/GO 语义/上限/成本中心/阶段额度（零发送）。
        p2a._check_go_payload(payload, plan, p2a._utcnow())
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        target.write_bytes(text.encode("utf-8"))
        rows.append(
            {
                "run_index": run_index,
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
                "target": str(target.relative_to(REPO)).replace("\\", "/"),
                "archive": str(archive.relative_to(REPO)).replace("\\", "/"),
                "archive_sha256": hashlib.sha256(before).hexdigest(),
                "archive_bytes": len(before),
                "after_file_sha256": _sha(target),
                "after_bytes": target.stat().st_size,
                "after_payload_sha256": payload_sha256(payload),
                "scope_max_requests": payload["scope"]["max_requests"],
                "nonce_len": len(payload["nonce"]),
                "fixed_slot": run_index == 0,
            }
        )
    evidence = {
        "schema_version": "p2-h2v3-go-regen/v0.1",
        "reason": "计划重签发（index_embedding 上界按 v3 实测 9/10/13/15；max_requests=1160）⇒ GO 必须重绑新 plan_sha256",
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
    evidence["zero_write"]["ledger_unchanged"] = (
        evidence["zero_write"]["ledger_sha_before"] == evidence["zero_write"]["ledger_sha_after"]
    )
    evidence["zero_write"]["budget_unchanged"] = (
        evidence["zero_write"]["budget_sha_before"] == evidence["zero_write"]["budget_sha_after"]
    )
    Path(args.out).write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
