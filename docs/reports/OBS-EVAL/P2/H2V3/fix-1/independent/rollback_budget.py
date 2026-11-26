"""独立验收：把 budget.json 的 limit_cny 从 50 逐字节回退到 40。

只做一处字节替换（等长），原子写；输出逐字节证据 JSON。
不写账本、不碰 GO、不发任何请求。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
)
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
    "docs/reports/OBS-EVAL/P2/H2V3/fix-1/independent/budget-rollback.json"
)
EXPECTED_AFTER = "79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e"

before = TARGET.read_bytes()
needle = b'"limit_cny": 50'
repl = b'"limit_cny": 40'
assert before.count(needle) == 1, before.count(needle)
after = before.replace(needle, repl)
assert len(before) == len(after)

sha_before = hashlib.sha256(before).hexdigest()
sha_after = hashlib.sha256(after).hexdigest()

# 首个不同字节位置
first_diff = next(i for i, (a, b) in enumerate(zip(before, after)) if a != b)
diff_positions = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]

deep_before = json.loads(before.decode("utf-8"))
deep_after = json.loads(after.decode("utf-8"))


def leaves(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(leaves(v, f"{prefix}/{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(leaves(v, f"{prefix}/{i}"))
    else:
        out[prefix] = obj
    return out


lb, la = leaves(deep_before), leaves(deep_after)
changed = sorted(k for k in set(lb) | set(la) if lb.get(k) != la.get(k))

# 原子写：同目录临时文件 + os.replace
fd, tmp = tempfile.mkstemp(dir=str(TARGET.parent), prefix=".budget.", suffix=".tmp")
try:
    with os.fdopen(fd, "wb") as fh:
        fh.write(after)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, TARGET)
finally:
    if os.path.exists(tmp):
        os.unlink(tmp)

on_disk = TARGET.read_bytes()
sha_disk = hashlib.sha256(on_disk).hexdigest()

evidence = {
    "schema_version": "v3-fix1-independent-budget-rollback/v0.1",
    "target": str(TARGET).replace("\\", "/"),
    "before": {"sha256": sha_before, "bytes": len(before)},
    "after": {"sha256": sha_disk, "bytes": len(on_disk)},
    "expected_after_sha256": EXPECTED_AFTER,
    "sha_matches_original_40": sha_disk == EXPECTED_AFTER,
    "replacement": {"needle": needle.decode(), "replacement": repl.decode()},
    "diff_positions": diff_positions,
    "first_diff_offset": first_diff,
    "byte_at_first_diff": {"before": before[first_diff:first_diff + 1].decode(),
                           "after": after[first_diff:first_diff + 1].decode()},
    "prefix_equal": before[:first_diff] == after[:first_diff],
    "suffix_equal": before[first_diff + 1:] == after[first_diff + 1:],
    "bytes_equal_length": len(before) == len(after),
    "deep_changed_leaves": changed,
    "deep_values": {"before": {k: lb.get(k) for k in changed},
                    "after": {k: la.get(k) for k in changed}},
    "stages_unchanged": deep_before.get("stages") == deep_after.get("stages"),
    "ledger_field_unchanged": deep_before.get("ledger") == deep_after.get("ledger"),
    "key_order_unchanged": list(deep_before) == list(deep_after),
    "tmp_or_lock_left": sorted(p.name for p in TARGET.parent.iterdir()
                               if p.name.startswith(".")),
    "wrote_ledger": False,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
               encoding="utf-8")
print(json.dumps({"sha_before": sha_before, "sha_after": sha_disk,
                  "matches": sha_disk == EXPECTED_AFTER}, ensure_ascii=False))
