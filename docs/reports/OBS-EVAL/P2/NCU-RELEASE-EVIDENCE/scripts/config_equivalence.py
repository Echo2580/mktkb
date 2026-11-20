"""证明冻结 v0.3 模板与批准配置的硬门禁语义等价；复算两个加载摘要。"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(ROOT / "backend/src"))
os.environ["MKTKB_NO_DOTENV"] = "1"
from mktkb.evaluation.p2_scoring import load_p2_gate_config  # noqa: E402

frozen_path = ROOT / "docs/evaluation/gate_v0_3.json"
approved_path = ROOT / "docs/evaluation/gate_v0_3_approved.json"
frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
approved = json.loads(approved_path.read_text(encoding="utf-8"))


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(obj):
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()


print("frozen file sha256:", hashlib.sha256(frozen_path.read_bytes()).hexdigest())
print("approved file sha256:", hashlib.sha256(approved_path.read_bytes()).hexdigest())
print("frozen canonical (loader) hash:", sha(frozen))
print("approved canonical (loader) hash:", sha(approved))
print("load frozen:", load_p2_gate_config(frozen_path).config_hash)
print("load approved:", load_p2_gate_config(approved_path).config_hash)

keys = ["schema_version", "gate_version", "hard_gates", "hard_gate_min_sample", "suites", "sensitive_patterns", "metrics"]
diff = {}
for k in keys:
    same = canon(frozen.get(k)) == canon(approved.get(k))
    diff[k] = same
    print(f"  {k}: identical={same}")
extra = sorted(set(approved) - set(frozen))
print("approved extra top-level keys:", extra)
print("frozen top-level keys:", sorted(frozen))
print("approved top-level keys:", sorted(approved))
print("p2_standards negative/boundary/update_delete:",
      {k: approved["p2_standards"][k] for k in ("negative", "boundary", "update_delete")})
