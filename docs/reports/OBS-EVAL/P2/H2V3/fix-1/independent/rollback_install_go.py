"""独立验收：把回退后的 4 份 GO 安装到固定槽位（先归档 50 版），原子写。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[7]
PM = REPO / "docs" / "evidence" / "LOCAL-R1-20261101" / "PM"
SRC = Path(r"D:\mktkb-p2-h2v3-20261115\rollback-40\go")
OUT = Path(r"D:\mktkb-p2-h2v3-20261115\rollback-40\go-install.json")

TARGETS = {
    0: PM / "P2-LIVE-GO.json",
    1: PM / "P2-LIVE-GO.v3-r1.pending.json",
    2: PM / "P2-LIVE-GO.v3-r2.pending.json",
    3: PM / "P2-LIVE-GO.v3-r3.pending.json",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path: Path, raw: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".go.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


rows = []
for index in range(4):
    source = SRC / f"P2-LIVE-GO.v3-r{index}.json"
    new_raw = source.read_bytes()
    target = TARGETS[index]
    old_raw = target.read_bytes()
    archive = PM / f"P2-LIVE-GO.v3-limit50-r{index}.archived.json"
    assert not archive.exists(), archive
    shutil.copyfile(target, archive)
    assert archive.read_bytes() == old_raw
    atomic_write(target, new_raw)
    now_raw = target.read_bytes()
    rows.append(
        {
            "run_index": index,
            "target": str(target),
            "before": {"sha256": sha(old_raw), "bytes": len(old_raw),
                       "budget_total_limit_cny": json.loads(old_raw)["budget_total_limit_cny"]},
            "after": {"sha256": sha(now_raw), "bytes": len(now_raw),
                      "budget_total_limit_cny": json.loads(now_raw)["budget_total_limit_cny"]},
            "archive": {"path": str(archive), "sha256": sha(archive.read_bytes()),
                        "bytes": archive.stat().st_size},
            "in_place": now_raw == new_raw,
        }
    )

evidence = {"schema_version": "v3-fix1-independent-go-install/v0.1", "runs": rows,
            "wrote_ledger": False, "sent_http": False}
OUT.write_text(json.dumps(evidence, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
               encoding="utf-8")
print(json.dumps([{"run": r["run_index"], "before": r["before"]["sha256"][:12],
                   "after": r["after"]["sha256"][:12], "limit": r["after"]["budget_total_limit_cny"],
                   "archive": r["archive"]["sha256"][:12]} for r in rows], indent=1))
