"""段 3/4 落盘器：把四 run 的真实结果落成仓内安全聚合 + 四轴/硬失败/达标判定。

只写：
  docs/reports/OBS-EVAL/P2/H2V3/run/r{0..3}-final/{card,case-plan,run-receipt,status}.json
  docs/reports/OBS-EVAL/P2/H2V3/run/final-summary.json
  docs/reports/OBS-EVAL/P2/H2V3/final/evidence/quality-per-run.json
不含题面/答案/query 文本。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
H2V3 = REPO / "docs/reports/OBS-EVAL/P2/H2V3"
WORK = Path(r"D:\mktkb-p2-h2v3-20261115")
RUNS = WORK / "runs"
LEDGER = REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
BUDGET = REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
AXES = H2V3 / "final/evidence/recompute-v2.json"
OUT_DIRS = {0: "final-r0", 1: "finalc-r1", 2: "finalc-r2", 3: "finalc-r3"}
NAMES = {
    0: "run0-base_b0",
    1: "run1-base_b0_plus_v01",
    2: "run2-pre_v05_without_v07",
    3: "run3-post_v05_without_v01",
}
MIN_PASS = 24
HARD_MAX = 0


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ledger_state() -> dict:
    raw = LEDGER.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    reserved = [r for r in rows if r.get("event") == "reserved"]
    results = [r for r in rows if r.get("event") == "result"]
    historical = sum(float(r.get("accounted_cny") or 0) for r in rows
                     if r.get("event") == "historical_import")
    project = historical + sum(float(r.get("conservative_charge_cny") or 0) for r in results)
    stage = sum(float(r.get("conservative_charge_cny") or 0) for r in results
                if r.get("stage") == "P2-LIVE")
    return {
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "lines": raw.count(b"\n"),
        "reservation_count": len(reserved),
        "result_count": len(results),
        "paired": len(reserved) == len(results),
        "project_accounted_cny": round(project, 10),
        "stage_p2_live_cny": round(stage, 10),
        "budget_sha256": sha(BUDGET),
    }


def main() -> int:
    axes = json.loads(AXES.read_text(encoding="utf-8"))
    axes_cases = {
        int(run["run_index"]): {c["case_id"]: c for c in run["cases"]} for run in axes["runs"]
    }
    ledger_after = ledger_state()

    run_rows = []
    quality_total = Counter()
    all_cases = []
    for run_index, dirname in OUT_DIRS.items():
        run_root = RUNS / dirname
        receipt_path = next((run_root / "seal").rglob("run-receipt.json"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        sidecar_path = next(run_root.glob("v3-entry-*.json"))
        case_plan_src = run_root / "out" / "controlled" / "case-plan.json"
        case_plan = json.loads(case_plan_src.read_text(encoding="utf-8"))

        cases = case_plan["cases"]
        quality = Counter(c.get("quality_status") for c in cases)
        turns_total = sum(len(c["turns"]) for c in cases)
        turn_status = Counter(t.get("status") for c in cases for t in c["turns"])
        turn_errors = Counter(
            (t.get("error") or "none") for c in cases for t in c["turns"]
        )
        quality_total.update(quality)
        for case in cases:
            ax = axes_cases.get(run_index, {}).get(case["case_id"], {})
            all_cases.append(
                {
                    "code": case["case_id"].split("-")[-1],
                    "run_index": run_index,
                    "quality_status": case.get("quality_status"),
                    "new_axes": ax.get("new_axes"),
                    "hard_failed": case["case_id"].split("-")[-1]
                    in [h.split("-")[-1] for h in axes.get("new_hard_failures", [])],
                }
            )

        dst = H2V3 / "run" / f"r{run_index}-final"
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "case-plan.json").write_bytes(case_plan_src.read_bytes())
        (dst / "run-receipt.json").write_bytes(receipt_path.read_bytes())
        (dst / "v3-entry-sidecar.json").write_bytes(sidecar_path.read_bytes())

        card = {
            "schema_version": "p2-h2v3-run-card/v0.1",
            "role": "v3 四 run 全量复跑（fix-2 后）单 run 安全聚合；无题面/答案/query 文本",
            "run_index": receipt["run_index"],
            "run_id": receipt["run_id"],
            "scenario_id": receipt["scenario_id"],
            "business_date": receipt["business_date"],
            "plan_id": receipt["plan_id"],
            "plan_sha256": receipt["plan_sha256"],
            "status": receipt["status"],
            "ok": receipt["ok"],
            "stop_code": receipt["stop_code"],
            "error_code": receipt["error_code"],
            "started_utc": receipt["started_utc"],
            "finished_utc": receipt["finished_utc"],
            "duration_ms": receipt["duration_ms"],
            "case_plan": {"cases": len(cases), "turns": turns_total,
                          "sha256": sha(case_plan_src)},
            "quality": dict(quality),
            "turn_status": dict(turn_status),
            "turn_errors": {k: v for k, v in turn_errors.items() if k != "none"} or {},
            "requests": {
                "planned": receipt["requests"]["planned"],
                "reserved": receipt["requests"]["reserved"],
                "sent": receipt["requests"]["sent"],
                "attempts_reserved": receipt["requests"]["attempts_reserved"],
                "attempts_by_operation": receipt["requests"]["attempts_by_operation"],
                "reserved_cny": receipt["requests"]["reserved_cny"],
                "settled_cny": receipt["requests"]["settled_cny"],
            },
            "real_sends": receipt["real_sends"],
            "evidence": receipt["evidence"],
            "seal": {k: (receipt.get("seal") or {}).get(k) for k in
                     ("sealed", "tree_sha256", "seal_manifest_sha256", "file_count", "bytes")},
            "cleanup": {
                "plaintext_clean": receipt["cleanup"]["plaintext_clean"],
                "business_db_removed": receipt["cleanup"]["business_db_removed"],
                "final_scan_clean": receipt["cleanup"]["final_plaintext_scan"]["clean"],
            },
        }
        (dst / "card.json").write_text(
            json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        status_payload = {
            "schema_version": "p2-h2v3-run-status/v0.1",
            "run_index": run_index,
            "scenario_id": receipt["scenario_id"],
            "business_date": receipt["business_date"],
            "status": receipt["status"],
            "ok": receipt["ok"],
            "error_code": receipt["error_code"],
            "stop_code": receipt["stop_code"],
            "case_count": len(cases),
            "turn_count": turns_total,
            "quality": dict(quality),
            "pass": int(quality.get("pass", 0)),
            "fail": int(quality.get("fail", 0)),
            "error": int(quality.get("error", 0)),
            "turn_executed": int(turn_status.get("executed", 0)),
            "turn_error_codes": {k: v for k, v in turn_errors.items() if k != "none"} or {},
            "requests_attempts_reserved": receipt["requests"]["attempts_reserved"],
            "real_sends": receipt["real_sends"],
            "settled_cny": receipt["requests"]["settled_cny"],
        }
        (dst / "status.json").write_text(
            json.dumps(status_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        run_rows.append(status_payload)

    quality_payload = {
        "schema_version": "p2-h2v3-final-quality/v0.1",
        "runs": [
            {k: row[k] for k in ("run_index", "scenario_id", "business_date", "case_count",
                                 "turn_count", "pass", "fail", "error")}
            for row in run_rows
        ],
        "totals": {
            "cases": sum(r["case_count"] for r in run_rows),
            "turns": sum(r["turn_count"] for r in run_rows),
            "pass": sum(r["pass"] for r in run_rows),
            "fail": sum(r["fail"] for r in run_rows),
            "error": sum(r["error"] for r in run_rows),
        },
        "cases": sorted(
            [
                {k: c[k] for k in ("code", "run_index", "quality_status", "hard_failed")}
                | {"new_axes": c["new_axes"]}
                for c in all_cases
            ],
            key=lambda c: c["code"],
        ),
    }
    (H2V3 / "final/evidence/quality-per-run.json").write_text(
        json.dumps(quality_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    totals = quality_payload["totals"]
    agg = axes["aggregate"]
    hard = agg.get("hard_failures") or []
    summary = {
        "schema_version": "p2-h2v3-final-summary/v0.1",
        "role": "四 run 全量复跑（fix-2 之后）汇总",
        "runs": run_rows,
        "totals": totals,
        "requests": {
            "attempts_reserved_sum": sum(r["requests_attempts_reserved"] for r in run_rows),
            "real_sends_sum": sum(int(r["real_sends"] or 0) for r in run_rows),
            "settled_cny_sum": round(sum(float(r["settled_cny"] or 0) for r in run_rows), 10),
        },
        "axes_matcher_v2": agg["new_axes"],
        "axes_matcher_v2_previous": agg["old_axes"],
        "axes_matcher_v2_version": axes.get("matcher_version"),
        "hard_failures": hard,
        "hard_failures_previous": agg.get("old_hard_failures"),
        "hard_failure_count": len(hard),
        "thresholds": {"min_pass": MIN_PASS, "hard_failures_max": HARD_MAX},
        "judgement": {
            "pass": int(totals["pass"]),
            "min_pass": MIN_PASS,
            "pass_threshold_met": int(totals["pass"]) >= MIN_PASS,
            "hard_failures": len(hard),
            "hard_threshold_met": len(hard) <= HARD_MAX,
            "t207_passed": int(totals["pass"]) >= MIN_PASS and len(hard) <= HARD_MAX,
        },
        "ledger": {"before_sha256": "22a4e85cfe8627bc8fc4e4711d07b67bb41f8ef8a12445f402097a11fa0a931e",
                   "after": ledger_after},
    }
    (H2V3 / "run/final-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"totals": totals, "hard_failures": hard,
                      "t207": summary["judgement"], "ledger_after": ledger_after["file_sha256"]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
