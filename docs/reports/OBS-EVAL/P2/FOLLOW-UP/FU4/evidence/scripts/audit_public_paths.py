"""FU-4 公开层路径泄露审计（只读扫描；只输出类别/计数/文件相对路径，绝不回显命中内容）。

用法（仓库根运行）::

    .venv\\Scripts\\python.exe -B docs/reports/OBS-EVAL/P2/FOLLOW-UP/FU4/evidence/scripts/audit_public_paths.py \
        --mode historical --root docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS ... \
        --out docs/reports/OBS-EVAL/P2/FOLLOW-UP/FU4/evidence/historical-leaks.json

    ... --mode new --root docs/reports/OBS-EVAL/P2/FOLLOW-UP \
        --out .../FU4/evidence/new-artifact-scan.json

口径
----
* 二进制/密文后缀（``.fernet``）**不读**，只按文件名计入 ``skipped_files``；
* 每个文件的命中只记 ``category/count``，**不写命中字符串**（避免把泄露复制到新公开产物）；
* ``--mode new``：新公开产物里任一类别 > 0 即 ``clean=false``；
* ``--mode historical``：只登记（历史冻结件**不改**），供报告"历史泄露登记"节使用。

说明：检测用的字面量在这里用分段拼接，避免本脚本自己成为"含受限根字面量"的新公开产物。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

_HOLDOUT = "mktkb-p2-" + "holdout"
_H2V3 = "mktkb-p2-" + "h2v3"

TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".txt", ".log", ".py", ".yml", ".yaml", ".csv"}
SKIP_SUFFIXES = {
    ".fernet", ".db", ".sqlite", ".sqlite3", ".png", ".jpg", ".jpeg",
    ".zip", ".gz", ".xlsx", ".docx", ".pdf",
}

PATTERNS = {
    "restricted_root": re.compile(re.escape(_HOLDOUT).encode(), re.IGNORECASE),
    "h2v3_batch_root": re.compile(re.escape(_H2V3).encode(), re.IGNORECASE),
    "key_or_ciphertext_name": re.compile(rb"[A-Za-z0-9_.\-]*\.(?:fernet|key)\b", re.IGNORECASE),
    "env_file": re.compile(rb"(?<![\w.\-])\.env(?:\.[A-Za-z0-9_.\-]+)?\b", re.IGNORECASE),
    "absolute_path": re.compile(rb"[A-Za-z]:[\\/]{1,2}[^\s\"'<>|,;]+"),
    "unc": re.compile(rb"\\\\[A-Za-z0-9_.\-]+\\[^\s\"'<>|,;]+"),
}
HARD_FAIL = ("restricted_root", "h2v3_batch_root", "key_or_ciphertext_name", "env_file", "absolute_path", "unc")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "backend" / "src" / "mktkb").is_dir():
            return parent
    return Path.cwd()


def scan_bytes(raw: bytes) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, pattern in PATTERNS.items():
        hits = len(pattern.findall(raw))
        if hits:
            counts[name] = hits
    return counts


def scan_tree(root: Path, *, max_bytes: int, exclude: list[str] | None = None) -> dict[str, object]:
    files: list[dict[str, object]] = []
    skipped: list[str] = []
    totals: dict[str, int] = {name: 0 for name in PATTERNS}
    scanned = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        if exclude and any(Path(relative).match(pattern) for pattern in exclude):
            skipped.append(relative)
            continue
        suffix = path.suffix.lower()
        if suffix in SKIP_SUFFIXES or suffix not in TEXT_SUFFIXES:
            skipped.append(relative)
            continue
        if path.stat().st_size > max_bytes:
            skipped.append(relative)
            continue
        raw = path.read_bytes()
        scanned += 1
        counts = scan_bytes(raw)
        for name, value in counts.items():
            totals[name] += value
        if counts:
            files.append({"path": relative, "bytes": len(raw), "sha256": sha(raw), "counts": counts})
    return {
        "root": root.as_posix(),
        "files_scanned": scanned,
        "files_with_findings": len(files),
        "skipped_files": len(skipped),
        "skipped_sample": skipped[:40],
        "totals": totals,
        "findings": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FU-4 public path leak audit (read-only)")
    parser.add_argument("--root", required=True, nargs="+")
    parser.add_argument("--mode", choices=["historical", "new", "source"], required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--repo", default=None, help="仓库根（默认按脚本位置上溯）")
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        help="相对 glob（可重复）：跳过脚本/检测器本身（它们含检测字面量，不是泄露值）",
    )
    args = parser.parse_args(argv)

    base = Path(args.repo).resolve() if args.repo else repo_root()
    results = []
    for item in args.root:
        path = Path(item)
        if not path.is_absolute():
            path = base / path
        if not path.exists():
            results.append({"root": Path(item).as_posix(), "missing": True})
            continue
        scanned = scan_tree(path, max_bytes=args.max_bytes, exclude=list(args.exclude or []))
        scanned["root"] = Path(item).as_posix()
        results.append(scanned)

    totals: dict[str, int] = {}
    for item in results:
        for name, value in dict(item.get("totals") or {}).items():
            totals[name] = totals.get(name, 0) + int(value)
    hard = {name: int(totals.get(name, 0)) for name in HARD_FAIL}
    payload = {
        "schema_version": "p2-fu4-public-path-audit/v0.1",
        "mode": args.mode,
        "roots": results,
        "totals": totals,
        "hard_fail_totals": hard,
    }
    if args.mode == "new":
        payload["clean"] = all(value == 0 for value in hard.values())
    elif args.mode == "historical":
        payload["clean"] = None
        payload["note"] = "历史冻结件只登记、不改写；外发副本必须排除登记项"
    else:
        payload["clean"] = None
        payload["note"] = "源码回显点清单：file:line 级分类见 echo_sites 生成脚本"
    out = Path(args.out)
    if not out.is_absolute():
        out = base / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": out.as_posix(), "mode": args.mode, "totals": totals, "clean": payload.get("clean")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
