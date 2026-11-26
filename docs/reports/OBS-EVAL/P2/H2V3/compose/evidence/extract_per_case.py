import json
import pathlib

ROOT = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs")
RUNS = [(0, "r0c"), (1, "r1c"), (2, "r2c"), (3, "r3c")]
PRE = json.loads(
    pathlib.Path(
        r"D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\v3-author\pre-registration.json"
    ).read_text(encoding="utf-8")
)
entries = PRE["entries"]
by_case = {}
for entry in entries:
    by_case.setdefault(entry["case_id"], []).append(entry)

out = {"runs": [], "counts": {}}
fail_total = 0
for run_index, dirname in RUNS:
    plan = json.loads((ROOT / dirname / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8"))
    rows = []
    for case in plan["cases"]:
        case_id = case["case_id"]
        short = case_id.split("-")[-1]
        rows.append(
            {
                "case_id": short,
                "full_case_id": case_id,
                "quality_status": case["quality_status"],
                "turns": len(case["turns"]),
                "registered": [
                    {
                        "entry_id": entry["entry_id"],
                        "category": entry["category"],
                        "expected_direction": entry["expected_direction"],
                    }
                    for entry in by_case.get(short, [])
                ],
            }
        )
    fails = [row["case_id"] for row in rows if row["quality_status"] == "fail"]
    fail_total += len(fails)
    out["runs"].append(
        {
            "run_index": run_index,
            "run_id": plan["run_id"],
            "case_count": len(rows),
            "pass": sum(1 for row in rows if row["quality_status"] == "pass"),
            "fail": len(fails),
            "fail_cases": fails,
            "cases": rows,
        }
    )
out["counts"]["fail_total"] = fail_total
out["counts"]["pass_total"] = sum(run["pass"] for run in out["runs"])

target = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\compose-work\per-case-results.json")
target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

for run in out["runs"]:
    print(run["run_index"], run["run_id"], "cases", run["case_count"], "pass", run["pass"], "fail", run["fail"])
    for row in run["cases"]:
        mark = row["quality_status"]
        reg = ",".join(e["entry_id"] + ":" + e["expected_direction"] for e in row["registered"]) or "-"
        print(f"  {row['case_id']}\t{mark}\t{reg}")
print("totals", out["counts"])
