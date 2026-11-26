"""C1-P2 冻结清单探针：逐字节核对 C 冻结 12 对象（只读）。

参考值来自 `axes/evidence/04-protected-hashes-before.json` 的 `c_freeze_12`；
本脚本不 import/不执行冻结实现，只读文件字节。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
REFERENCE = (
    ROOT
    / "docs"
    / "reports"
    / "OBS-EVAL"
    / "P2"
    / "Q1A-EVAL-REPAIR"
    / "axes"
    / "evidence"
    / "04-protected-hashes-before.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> dict[str, Any]:
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    expected: dict[str, str] = reference["c_freeze_12"]
    rows = {}
    mismatches = []
    for rel, expected_sha in sorted(expected.items()):
        path = ROOT / rel
        actual = _sha256(path) if path.is_file() else None
        match = actual == expected_sha
        rows[rel] = {
            "expected_sha256": expected_sha,
            "actual_sha256": actual,
            "bytes": path.stat().st_size if path.is_file() else None,
            "match": match,
        }
        if not match:
            mismatches.append(rel)
    hard = ROOT / "backend/src/mktkb/evaluation/p2_hard_evidence.py"
    return {
        "schema_version": "c1p2-frozen-sha/v0.1",
        "verified_at": datetime.now().astimezone().isoformat(),
        "reference": str(REFERENCE.relative_to(ROOT)).replace("\\", "/"),
        "item_count": len(expected),
        "mismatches": mismatches,
        "p2_hard_evidence_sha256": _sha256(hard),
        "p2_hard_evidence_expected": expected.get(
            "backend/src/mktkb/evaluation/p2_hard_evidence.py"
        ),
        "p2_evidence_capture_sha256": _sha256(
            ROOT / "backend/src/mktkb/evaluation/p2_evidence_capture.py"
        ),
        "p2_evidence_io_sha256": _sha256(
            ROOT / "backend/src/mktkb/evaluation/p2_evidence_io.py"
        ),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = run()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "item_count": payload["item_count"],
                "mismatch_count": len(payload["mismatches"]),
                "p2_hard_evidence_sha256": payload["p2_hard_evidence_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if not payload["mismatches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
