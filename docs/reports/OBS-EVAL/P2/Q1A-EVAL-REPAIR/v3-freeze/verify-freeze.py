#!/usr/bin/env python3
"""独立复算 p2-holdout-v3.freeze.json 中每一件的 SHA-256 与字节数。

用法（stdlib only，不依赖仓库包）：
    python docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-freeze/verify-freeze.py

行为：
- 读取同目录 `p2-holdout-v3.freeze.json`；
- 对 `artifacts[]` 每一条重算 SHA-256 与字节数，逐件打印 `OK <id>` 或差异；
- 任一件缺失/字节数不符/SHA 不符 → 退出码 1；全部一致 → 打印 `OK <n>/<n>` 并退出 0。

`root` 语义：
- `repo`：`path` 是相对仓库根的 POSIX 路径；仓库根由本文件位置反推
  （`<repo>/docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-freeze/verify-freeze.py`）。
- `external`：`path` 是绝对路径（v3 封存 root 在仓库外）。

本脚本只读；不写任何文件、不联网、不执行被校验文件。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

FREEZE_NAME = "p2-holdout-v3.freeze.json"
EXPECTED_SCHEMA = "p2-holdout-v3-freeze/v1"


def repo_root() -> Path:
    # .../v3-freeze/verify-freeze.py -> v3-freeze -> Q1A-EVAL-REPAIR -> P2 -> OBS-EVAL -> reports -> docs -> <repo>
    return Path(__file__).resolve().parents[6]


def digest(path: Path) -> tuple[int, str]:
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()


def main() -> int:
    freeze_path = Path(__file__).resolve().with_name(FREEZE_NAME)
    if not freeze_path.is_file():
        print(f"DIFF freeze.json missing: {freeze_path}")
        return 1
    try:
        document = json.loads(freeze_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"DIFF freeze.json unreadable: {type(error).__name__}")
        return 1

    if document.get("schema_version") != EXPECTED_SCHEMA:
        print(f"DIFF schema_version: {document.get('schema_version')!r} != {EXPECTED_SCHEMA!r}")
        return 1

    artifacts = document.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        print("DIFF artifacts[] missing or empty")
        return 1

    root = repo_root()
    failures = 0
    seen: set[tuple[str, str]] = set()
    for record in artifacts:
        if not isinstance(record, dict):
            print("DIFF malformed artifact record")
            failures += 1
            continue
        identifier = record.get("id")
        group = record.get("group")
        where = record.get("root")
        text = record.get("path")
        expected_sha = record.get("sha256")
        expected_bytes = record.get("bytes")
        if not isinstance(identifier, str) or not isinstance(text, str):
            print("DIFF artifact without id/path")
            failures += 1
            continue
        if where not in ("repo", "external"):
            print(f"DIFF {identifier}: root must be repo|external, got {where!r}")
            failures += 1
            continue
        if (where, text) in seen:
            print(f"DIFF {identifier}: duplicate path {text}")
            failures += 1
            continue
        seen.add((where, text))

        path = (root / text) if where == "repo" else Path(text)
        if not path.is_file():
            print(f"DIFF {identifier}: missing {path}")
            failures += 1
            continue
        try:
            actual_bytes, actual_sha = digest(path)
        except OSError as error:
            print(f"DIFF {identifier}: unreadable {path} ({type(error).__name__})")
            failures += 1
            continue
        if actual_bytes != expected_bytes:
            print(f"DIFF {identifier}: bytes expected={expected_bytes} actual={actual_bytes}")
            failures += 1
            continue
        if actual_sha != expected_sha:
            print(f"DIFF {identifier}: sha256 expected={expected_sha} actual={actual_sha}")
            failures += 1
            continue
        print(f"OK {identifier} [{group}] {actual_bytes}B {actual_sha}")

    total = len(artifacts)
    if failures:
        print(f"DIFF {failures}/{total} artifact(s) differ")
        return 1
    print(f"OK {total}/{total}")
    print(f"OK freeze.json sha256={hashlib.sha256(freeze_path.read_bytes()).hexdigest()} (self, not listed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
