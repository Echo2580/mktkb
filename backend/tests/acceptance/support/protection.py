"""既有文件起止保护扫描与比较（真实字节 SHA-256，按名排除联接/依赖/缓存/证据目录）。

用法：
    python -B backend/tests/acceptance/support/protection.py baseline --label protect-start-01
    python -B backend/tests/acceptance/support/protection.py baseline --label protect-end-01
    python -B backend/tests/acceptance/support/protection.py compare --start <start.json> --end <end.json> --label protect-compare-01

排除口径（按名，不读内容）：`.venv`、`node_modules`、`__pycache__`、`.pytest_cache`、`.mypy_cache`、
`.ruff_cache`、`.git`、`.pytest-tmp`、`test-results`、`dist`、`tmp`、`docs/evidence`（本轮唯一新增证据
目录，含本轮全部日志/截图）、`.env`/`.env.*`（不读取内容）。目录联接/重解析点记录后跳过，绝不跟随。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUT = ROOT / "docs" / "evidence" / "T09" / "D1" / "protection"
OUT = DEFAULT_OUT

EXCLUDED_DIR_NAMES = {
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    ".pytest-tmp",
    "test-results",
    "dist",
    "tmp",
    "playwright-report",
}
EXCLUDED_RELATIVE = {Path("docs/evidence")}
EXCLUDED_FILE_NAMES = {".env"}
EXCLUDED_FILE_PREFIXES = (".env.",)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _is_reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(info, "st_file_attributes", 0) & 0x400) or stat.S_ISLNK(info.st_mode)


def _excluded_file(name: str) -> bool:
    return name in EXCLUDED_FILE_NAMES or name.startswith(EXCLUDED_FILE_PREFIXES)


def scan(label: str) -> dict:
    entries: dict[str, dict] = {}
    skipped: list[dict] = []
    unreadable: list[dict] = []
    total_bytes = 0

    for dirpath, dirnames, filenames in os.walk(ROOT, followlinks=False):
        current = Path(dirpath)
        kept_dirs = []
        for name in dirnames:
            child = current / name
            relative = child.relative_to(ROOT)
            if name in EXCLUDED_DIR_NAMES or relative in EXCLUDED_RELATIVE:
                continue
            if relative == Path("docs") or Path("docs/evidence").is_relative_to(relative):
                pass
            if _is_reparse(child):
                skipped.append({"path": relative.as_posix(), "reason": "directory-junction-or-link"})
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in filenames:
            if _excluded_file(name):
                skipped.append({"path": (current / name).relative_to(ROOT).as_posix(), "reason": "env-file-by-name"})
                continue
            path = current / name
            relative = path.relative_to(ROOT).as_posix()
            if _is_reparse(path):
                skipped.append({"path": relative, "reason": "file-link-or-reparse"})
                continue
            try:
                info = os.stat(path)
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except PermissionError:
                unreadable.append({"path": relative, "reason": "permission-denied"})
                continue
            except OSError as exc:
                unreadable.append({"path": relative, "reason": f"os-error:{type(exc).__name__}"})
                continue
            entries[relative] = {
                "sha256": digest.hexdigest(),
                "size": info.st_size,
                "mtime": datetime.fromtimestamp(info.st_mtime).astimezone().isoformat(timespec="seconds"),
            }
            total_bytes += info.st_size

    payload = {
        "label": label,
        "scan_kind": "baseline",
        "captured_at": _now(),
        "root": str(ROOT),
        "excluded_dir_names": sorted(EXCLUDED_DIR_NAMES),
        "excluded_relative": sorted(path.as_posix() for path in EXCLUDED_RELATIVE),
        "excluded_file_names": sorted(EXCLUDED_FILE_NAMES),
        "excluded_file_prefixes": list(EXCLUDED_FILE_PREFIXES),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "skipped": skipped,
        "unreadable": unreadable,
        "entries": entries,
    }
    return payload


def compare(
    start_path: Path,
    end_path: Path,
    label: str,
    allowed_added_prefixes: list[str],
    allowed_changed_prefixes: list[str] | None = None,
) -> dict:
    start = json.loads(Path(start_path).read_text(encoding="utf-8"))
    end = json.loads(Path(end_path).read_text(encoding="utf-8"))
    start_entries = start["entries"]
    end_entries = end["entries"]
    added = sorted(set(end_entries) - set(start_entries))
    removed = sorted(set(start_entries) - set(end_entries))
    changed = sorted(
        key for key in set(start_entries) & set(end_entries) if start_entries[key]["sha256"] != end_entries[key]["sha256"]
    )

    def allowed(relative: str) -> bool:
        return any(relative.startswith(prefix) for prefix in allowed_added_prefixes)

    def allowed_change(relative: str) -> bool:
        return any(relative.startswith(prefix) for prefix in (allowed_changed_prefixes or []))

    unexpected_added = [item for item in added if not allowed(item)]
    unexpected_removed = list(removed)
    unexpected_changed = [item for item in changed if not allowed_change(item)]
    payload = {
        "label": label,
        "scan_kind": "compare",
        "compared_at": _now(),
        "start": {"label": start["label"], "captured_at": start["captured_at"], "file_count": start["file_count"], "total_bytes": start["total_bytes"]},
        "end": {"label": end["label"], "captured_at": end["captured_at"], "file_count": end["file_count"], "total_bytes": end["total_bytes"]},
        "allowed_added_prefixes": allowed_added_prefixes,
        "allowed_changed_prefixes": allowed_changed_prefixes or [],
        "added": added,
        "removed": removed,
        "changed": [
            {
                "path": key,
                "start_sha256": start_entries[key]["sha256"],
                "end_sha256": end_entries[key]["sha256"],
                "start_size": start_entries[key]["size"],
                "end_size": end_entries[key]["size"],
            }
            for key in changed
        ],
        "unexpected_added": unexpected_added,
        "unexpected_removed": unexpected_removed,
        "unexpected_changed": unexpected_changed,
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "unexpected": len(unexpected_added) + len(unexpected_removed) + len(unexpected_changed),
        },
        "pass": not (unexpected_added or unexpected_removed or unexpected_changed),
    }
    return payload


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="T09 起止保护扫描（--out 指定证据目录，默认 T09/D1/protection）")
    parser.add_argument("--out", default=None, help="证据输出目录（本轮 T09-D2 用 docs/evidence/T09/D2/protection）")
    sub = parser.add_subparsers(dest="mode", required=True)

    base = sub.add_parser("baseline")
    base.add_argument("--label", required=True)

    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--start", required=True)
    cmp_.add_argument("--end", required=True)
    cmp_.add_argument("--label", required=True)
    cmp_.add_argument("--allow-added-prefix", action="append", default=[])
    cmp_.add_argument("--allow-changed-prefix", action="append", default=[])

    args = parser.parse_args(argv)
    global OUT
    if args.out:
        OUT = Path(args.out)
    OUT.mkdir(parents=True, exist_ok=True)

    if args.mode == "baseline":
        target = OUT / f"{args.label}.json"
        if target.exists():
            print(f"已存在，拒绝覆盖：{target}", file=sys.stderr)
            return 2
        payload = scan(args.label)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            f"[protection] {args.label}: files={payload['file_count']} bytes={payload['total_bytes']} "
            f"skipped={len(payload['skipped'])} unreadable={len(payload['unreadable'])} -> {target}"
        )
        return 0

    target = OUT / f"{args.label}.json"
    if target.exists():
        print(f"已存在，拒绝覆盖：{target}", file=sys.stderr)
        return 2
    payload = compare(
        Path(args.start),
        Path(args.end),
        args.label,
        list(args.allow_added_prefix),
        list(args.allow_changed_prefix),
    )
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"[protection] {args.label}: added={payload['counts']['added']} removed={payload['counts']['removed']} "
        f"changed={payload['counts']['changed']} unexpected={payload['counts']['unexpected']} pass={payload['pass']}"
    )
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
