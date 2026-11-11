
"""T207-FIX-SCORE 验收复跑：比较 probe_default_diff.py 的 old/new 转储（逐字节，含键序）。"""
from __future__ import annotations
import json
import sys
from pathlib import Path

old = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
new = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

def cmp(key: str) -> tuple[int, int, list[str]]:
    old_by_id = {item["id"]: item["result"] for item in old[key]}
    same = order_only = 0
    value_diff: list[str] = []
    for item in new[key]:
        a = json.dumps(old_by_id[item["id"]], ensure_ascii=False)
        b = json.dumps(item["result"], ensure_ascii=False)
        if a == b:
            same += 1
            continue
        # 键序差异检测：排序键后再比（本次应为 0）
        def deep(o):
            if isinstance(o, dict):
                return {k: deep(o[k]) for k in sorted(o)}
            if isinstance(o, list):
                return [deep(x) for x in o]
            return o
        if json.dumps(deep(old_by_id[item["id"]]), ensure_ascii=False) == json.dumps(deep(item["result"]), ensure_ascii=False):
            order_only += 1
        else:
            value_diff.append(item["id"])
    print(f"{key}: records={len(new[key])} byte_identical={same} order_only={order_only} value_diff={len(value_diff)}")
    if value_diff:
        print("  diff ids:", ", ".join(value_diff[:10]))
    return len(new[key]), same, value_diff

print("old module:", old["module"])
print("new module:", new["module"])
fixture_total, fixture_same, fixture_diff = cmp("fixture_records")
run_total, run_same, run_diff = cmp("run_records")

fails = []
for item in new["run_records"]:
    check = next(c for c in item["result"]["checks"] if c["check_id"] == "value_no_fabricated")
    if check["status"] == "fail":
        fails.append((item["id"], check["evidence"].get("extra")))
print(f"default value_no_fabricated fails on real rows: {len(fails)}")
for case_id, extra in fails:
    print(f"  {case_id} extra={extra}")

print("Q09-Q24 default vnf status:")
for case_id in [f"Q{i:02d}" for i in range(9, 25)]:
    item = next(i for i in new["run_records"] if i["id"].endswith(":" + case_id))
    check = next(c for c in item["result"]["checks"] if c["check_id"] == "value_no_fabricated")
    print(f"  {case_id} {check['status']} extra={check['evidence'].get('extra')} case={item['result']['status']}")

ok = (fixture_total == fixture_same and run_total == run_same and not fixture_diff and not run_diff)
print("VERDICT:", "IDENTICAL" if ok else "DIFF")
raise SystemExit(0 if ok else 1)
