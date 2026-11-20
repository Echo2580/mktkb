"""重建 .tmp-ncu-isolated 里的只读副本（用于复核复算）；只从原始 run 目录复制，不改原件。"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
ISO = ROOT / ".tmp-ncu-isolated" / "traces"
ISO.mkdir(parents=True, exist_ok=True)
EXPECTED = json.loads((ROOT / "docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/evidence/artifact-hashes.json").read_text(encoding="utf-8"))
SRC = Path(r"D:\mktkb-p2-run\t207")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


mapping = {}
for run in ["R1", "R2", "R4"]:
    mapping[ISO / f"{run}.sqlite3"] = SRC / run / "data" / "observability" / "qa-traces.sqlite3"
    mapping[ISO / f"{run}-rag.sqlite3"] = SRC / run / "data" / "rag-index.sqlite3"
mapping[ISO / "R2-product.sqlite3"] = SRC / "R2" / "data" / "mktkb.sqlite3"

for dst, src in mapping.items():
    if not dst.exists():
        shutil.copy2(src, dst)
    key = f"{dst.stem}.trace_db" if dst.stem in {"R1", "R2", "R4"} else (
        f"{dst.stem.split('-')[0]}.rag_index" if dst.stem.endswith("-rag") else "R2.product_db")
    actual = sha(dst)
    expect = EXPECTED.get(key)
    print(f"{dst.name:22s} {actual} {'OK' if expect in (None, actual) else 'MISMATCH expected ' + str(expect)}")
print("done:", ISO)
