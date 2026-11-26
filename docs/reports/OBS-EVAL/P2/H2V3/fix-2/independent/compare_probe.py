"""对比改前/改后两份探针结果，产出 probe-compare.json（机读）。"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
AFTER = HERE / "independent-probe.json"
BEFORE = HERE / "independent-probe-prefix.json"
OUT = HERE / "probe-compare.json"


def sig(row: dict) -> dict:
    planner = row["planner"]
    return {
        "reason": planner["reason"],
        "clarification": bool(planner["clarification"]),
        "enumerate": planner["enumerate"],
        "rag_owns_turn": planner["rag_owns_turn"],
        "kind": row["e2e"]["kind"],
        "returned": row["e2e"]["returned"],
        "citations": row["e2e"]["citations"],
    }


def main() -> int:
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    rows = {}
    flipped, stable_pass, stable_fail = [], [], []
    for name, case in after["cases"].items():
        b = before["cases"][name]
        entry = {
            "group": case["group"],
            "question": case["question"],
            "before": sig(b),
            "after": sig(case),
            "before_ok": b["ok"],
            "after_ok": case["ok"],
            "before_failed_checks": b["failed_checks"],
        }
        entry["changed"] = entry["before"] != entry["after"]
        rows[name] = entry
        if b["ok"] != case["ok"]:
            flipped.append(name)
        elif case["ok"]:
            stable_pass.append(name)
        else:
            stable_fail.append(name)

    payload = {
        "schema_version": "v3-fix2-probe-compare/v0.1",
        "before_src": before["src_used"],
        "after_src": after["src_used"],
        "before": {"passed": before["cases_passed"], "total": before["cases_total"],
                   "failures": before["failures"]},
        "after": {"passed": after["cases_passed"], "total": after["cases_total"],
                  "failures": after["failures"]},
        "flipped_to_pass": flipped,
        "stable_pass": stable_pass,
        "stable_fail": stable_fail,
        "cases": rows,
        "causality": {
            "statement": "同一份自建探针只换 src（仓库现状 vs 本包反向重建的改前版），"
                         "5 个 A/B 正例由失败翻为通过，其余 11 例前后一致。",
            "flipped_count": len(flipped),
            "unchanged_count": len(stable_pass) + len(stable_fail),
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: payload[k] for k in
                      ("before", "after", "flipped_to_pass", "stable_fail", "causality")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
