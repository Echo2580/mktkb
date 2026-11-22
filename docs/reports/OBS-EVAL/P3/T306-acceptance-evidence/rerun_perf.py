"""T306 独立验收性能复跑包装器：原样执行只读探针，输出改到验收目录；
比对查询计划/规模与开发结果，并校验中位数阈值。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

P3 = Path(__file__).resolve().parents[1]
DEV = P3 / "T306-evidence"
ACC = P3 / "T306-acceptance-evidence"

spec = importlib.util.spec_from_file_location("perf_probe", DEV / "scripts" / "perf_probe.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["perf_probe"] = mod
spec.loader.exec_module(mod)
mod.OUT_DIR = ACC / "perf"
code = mod.main()
print(f"PERF_EXIT={code}")

dev = json.loads((DEV / "perf" / "perf-results.json").read_text(encoding="utf-8"))
acc = json.loads((ACC / "perf" / "perf-results.json").read_text(encoding="utf-8"))
print("PLANS_IDENTICAL:", dev["plans"] == acc["plans"])
same_scale = all(
    dev["databases"][k]["windows"][w]["scale"] == acc["databases"][k]["windows"][w]["scale"]
    for k in dev["databases"] for w in dev["databases"][k]["windows"]
)
print("SCALE_IDENTICAL:", same_scale)
worst = max(
    t["median_ms"]
    for k in acc["databases"] for w in acc["databases"][k]["windows"]
    for t in acc["databases"][k]["windows"][w]["timings"].values()
)
worst_max = max(
    t["max_ms"]
    for k in acc["databases"] for w in acc["databases"][k]["windows"]
    for t in acc["databases"][k]["windows"][w]["timings"].values()
)
print(f"ACC_MEDIAN_MAX={worst} ACC_SINGLE_MAX={worst_max} THRESHOLD_OK={worst < 0.05}")
scan = [
    (k, n, s) for k, plans in acc["plans"].items() for n, steps in plans.items()
    for s in steps if s.startswith("SCAN")
]
print("FULL_SCANS:", scan if scan else "NONE")