"""R3 transition probe: aggregate-only R2 -> R3 axis transitions.

Reads the two out-of-repo private details; prints only counts grouped by run and
reason. No case ids, question text, answers or target values.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from cryptography.fernet import Fernet

KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
R2 = Path(r"D:\mktkb-q1a3-rescore\rescore-detail-r2.fernet")
R3 = Path(r"D:\mktkb-q1a3-rescore\rescore-detail-r3.fernet")
OUT = Path(r"D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\rescore\evidence-r3\09-transition-probe.out.json")


def load(path: Path):
    return json.loads(Fernet(KEY.read_bytes()).decrypt(path.read_bytes()).decode("utf-8"))


def main() -> int:
    r2 = load(R2)
    r3 = load(R3)
    r2_cases = {row["case_id"]: row for row in r2["cases"]}
    r3_cases = {row["case_id"]: row for row in r3["cases"]}
    out = {
        "case_count_r2": len(r2_cases),
        "case_count_r3": len(r3_cases),
        "stale_transitions": Counter(),
        "stale_transitions_by_run": Counter(),
        "stale_regression_reasons": Counter(),
        "stale_improvement_reasons": Counter(),
        "case_level_transitions": Counter(),
        "case_level_transitions_by_quality": Counter(),
    }
    for case_id, row3 in r3_cases.items():
        row2 = r2_cases.get(case_id)
        if row2 is None:
            continue
        before = row2["axes"]["stale_source"]["state"]
        after = row3["axes"]["stale_source"]["state"]
        if before != after:
            out["stale_transitions"][f"{before}->{after}"] += 1
            out["stale_transitions_by_run"][f"r{row3['run_index']}:{before}->{after}"] += 1
            if after == "unknown":
                out["stale_regression_reasons"][f"r{row3['run_index']}:{row3['axes']['stale_source']['reason']}"] += 1
            if after == "passed":
                out["stale_improvement_reasons"][f"r{row3['run_index']}:{row3['axes']['stale_source']['reason']}"] += 1
        # case-level status using the same rule as the aggregate
        def status(row):
            states = {axis: row["axes"][axis]["state"] for axis in ("safety", "cross_user", "cross_entity", "stale_source")}
            if any(state == "violation" for state in states.values()):
                return "hard_failure"
            for axis, state in states.items():
                if row["axes"][axis]["applicability"] == "not_applicable":
                    continue
                if row["axes"][axis]["applicability"] == "unknown" or state == "unknown":
                    return "unknown"
            return "pass"

        b = status(row2)
        a = status(row3)
        if b != a:
            out["case_level_transitions"][f"{b}->{a}"] += 1
            out["case_level_transitions_by_quality"][f"q={row3['case_plan_quality']}:{b}->{a}"] += 1
    for key in ("stale_transitions", "stale_transitions_by_run", "stale_regression_reasons",
                "stale_improvement_reasons", "case_level_transitions", "case_level_transitions_by_quality"):
        out[key] = {k: v for k, v in sorted(out[key].items())}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
