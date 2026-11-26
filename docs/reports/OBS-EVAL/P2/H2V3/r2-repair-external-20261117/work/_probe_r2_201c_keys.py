"""诊断：找出 ext 输出里第一个不在白名单的键（只打键名与路径，不打值）。"""
from __future__ import annotations

import pathlib
import sys

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r2_boundary_ext as ext  # noqa: E402
import r2_safe_project as base  # noqa: E402


def walk(node, path="$", depth=0):
    bad = []
    if depth > 8:
        return bad
    if isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                bad.append((path, "<non-str-key>"))
                continue
            if key not in base.ALLOWED_KEYS:
                bad.append((path, key))
            bad.extend(walk(value, f"{path}.{key}", depth + 1))
    elif isinstance(node, list):
        for index, item in enumerate(node[:64]):
            bad.extend(walk(item, f"{path}[{index}]", depth + 1))
    elif isinstance(node, str):
        if not base._safe_string(node):
            bad.append((path, f"<unsafe-string len={len(node)}>"))
    elif isinstance(node, int) and not isinstance(node, bool):
        if node < 0 or node > 10**9:
            bad.append((path, f"<int-out-of-range>"))
    return bad


def _dump(payload, path, *, echo):
    problems = walk(dict(payload))
    if problems:
        print("WHITELIST_PROBLEMS", len(problems))
        for where, key in problems[:40]:
            print("  ", where, "->", key)
        raise SystemExit(97)
    text = __import__("json").dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")


ext._dump = _dump
raise SystemExit(ext.main(sys.argv[1:]))
