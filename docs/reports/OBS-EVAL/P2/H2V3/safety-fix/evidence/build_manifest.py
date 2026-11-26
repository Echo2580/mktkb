"""生成 v3-safety-fix 证据清单（逐件 SHA-256/字节；不含本文件自身的自引用哈希）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

EXCLUDE_NAMES = {"MANIFEST.json"}
EXCLUDE_DIRS = {"__pycache__"}


def sha(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main() -> int:
    files = []
    for path in sorted(HERE.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(HERE)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if rel.name in EXCLUDE_NAMES:
            continue
        entry = {"path": rel.as_posix(), **sha(path)}
        files.append(entry)
    payload = {
        "schema_version": "v3-safety-fix-evidence-manifest/v0.1",
        "root": "docs/reports/OBS-EVAL/P2/H2V3/safety-fix/evidence",
        "file_count": len(files),
        "files": files,
    }
    (HERE / "MANIFEST.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(files)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
