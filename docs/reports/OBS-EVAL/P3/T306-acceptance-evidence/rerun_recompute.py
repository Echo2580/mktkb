"""T306 独立验收复算包装器：原样执行开发交付的两个只读复算脚本，
仅把输出路径改到验收目录，避免覆盖开发证据；随后与开发结果逐字节比对。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

P3 = Path(__file__).resolve().parents[1]
DEV = P3 / "T306-evidence"
ACC = P3 / "T306-acceptance-evidence"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# T301 复算（副本脚本，强制只读 URI）
common = load("t301_common", DEV / "scripts" / "t301" / "t301_common.py")
rc = load("t301_recompute", DEV / "scripts" / "t301" / "t301_recompute.py")
rc.RECOMPUTE_DIR = ACC / "recompute-t301"
out = rc.compute()
bad = [c for c in out["expected_vs_actual"]["checks"] if not c["consistent"]]
print(f"T301 completed={out['answer_volume']['completed_requests']} "
      f"coverage={out['trace_coverage']['coverage_ratio']} inconsistent={len(bad)}")
for item in bad:
    print("MISMATCH", item)

# 集成复算
ri = load("t306_recompute_integration", DEV / "scripts" / "t306_recompute_integration.py")
ri.OUT = ACC / "recompute-integration" / "recompute-results.json"
code = ri.main()
print(f"INTEGRATION_EXIT={code}")

# 与开发交付结果比对
for rel in ("recompute-t301/recompute-results.json", "recompute-integration/recompute-results.json"):
    a = json.loads((DEV / rel).read_text(encoding="utf-8"))
    b = json.loads((ACC / rel).read_text(encoding="utf-8"))
    print(f"COMPARE {rel}: {'IDENTICAL' if a == b else 'DIFFERENT'}")