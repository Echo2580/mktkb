"""生成 fix-1r1 证据清单（不读内容以外的东西；只哈希本目录文件）。

用法：python build_manifest.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


files = []
for path in sorted(PACKAGE.rglob("*")):
    if not path.is_file():
        continue
    rel = path.relative_to(PACKAGE).as_posix()
    if rel == "evidence/MANIFEST.json":
        continue
    files.append({"path": f"docs/reports/OBS-EVAL/P2/H2V3/fix-1r1/{rel}",
                  "bytes": path.stat().st_size, "sha256": sha256(path)})

payload = {
    "package": "docs/reports/OBS-EVAL/P2/H2V3/fix-1r1",
    "file_count": len(files),
    "files": files,
    "note": "本清单不含自身（MANIFEST.json）。",
}
(HERE / "MANIFEST.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
)
print(json.dumps({"file_count": len(files), "out": str(HERE / "MANIFEST.json")},
                 ensure_ascii=False))
