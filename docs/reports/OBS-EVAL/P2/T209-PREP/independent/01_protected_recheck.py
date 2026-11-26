"""T209-PREP 独立验收：保护件重算（只读，不复用开发快照脚本）。

独立实现：显式对象逐字节 SHA256；大目录只用「相对路径+字节数+mtime_ns」元数据指纹。
与开发提供的 00-protected-pre.txt / 09-protected-post.txt 逐行比较，并单独核对
资金 4/4、生产锁 2/2、C 冻结 12/12、E0 6/6、E1 5/5、正式 baseline 2/2、real-h2 1/1。

不读取目录内容，不写受保护对象。
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
REPORT = ROOT / "docs/reports/OBS-EVAL/P2/T209-PREP"
PRE = REPORT / "evidence/00-protected-pre.txt"
POST = REPORT / "evidence/09-protected-post.txt"
C_FREEZE = ROOT / "docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/evidence/c-freeze.txt"

FUNDING = (
    "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl",
    "docs/evidence/LOCAL-R1-20261101/budget/budget.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.t207-h2-run-20261114.pre.archived.json",
)
E0 = tuple(
    f"docs/reports/OBS-EVAL/P2/T207-SAFETY-TRIAGE-20261114/{name}"
    for name in (
        "custodian-a-aggregate.json",
        "custodian-a-report.md",
        "custodian-b-review.json",
        "custodian-b-review.md",
        "manager-receipt.json",
        "manager-receipt.md",
    )
)
E1 = (
    "backend/src/mktkb/evaluation/ragas_adapter.py",
    "backend/tests/evaluation/test_p2_ragas_adapter.py",
    "backend/tests/evaluation/test_p2_judge_budget.py",
    "docs/evaluation/p2-ragas-contract.md",
    "backend/requirements-ragas-eval.lock",
)
LOCKS = ("backend/requirements.lock", "backend/requirements-dev.lock")
REUSED = (
    "backend/src/mktkb/evaluation/report.py",
    "backend/src/mktkb/evaluation/baseline.py",
    "backend/src/mktkb/evaluation/gate.py",
    "backend/tests/evaluation/test_report.py",
    "backend/tests/evaluation/test_baseline_portability.py",
    "backend/tests/evaluation/test_diff_release_gate.py",
    "backend/tests/evaluation/test_p2_gate.py",
)
FORMAL = (
    "var/eval/baselines/bc6f6f906db1/baseline.json",
    "var/eval/baselines/bc6f6f906db1/approval.json",
)
REAL_PUBLIC = ("docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/real-h2.md",)
METADATA_DIRS = (
    "docs/evidence/LOCAL-R1-20261101",
    "docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS",
    "docs/reports/OBS-EVAL/P2/T208-OFFLINE",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def c_freeze_paths() -> list[str]:
    paths: list[str] = []
    section = ""
    for line in C_FREEZE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
            continue
        if section in {"[final-object-bytes]", "[C-new]"}:
            match = re.match(r"^[0-9a-f]{64} \*(.+)$", stripped)
            if match:
                paths.append(match.group(1))
    return paths


def tree_fingerprint(directory: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    for path in sorted(directory.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(ROOT).as_posix()
        stat = path.lstat()
        total += stat.st_size
        count += 1
        digest.update(f"{rel}\t{stat.st_size}\t{stat.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest(), count, total


def render() -> str:
    lines: list[str] = [
        "T209-PREP independent protected recheck (READ-ONLY)",
        f"repo_root: {ROOT}",
        "",
    ]
    groups = (
        ("funding", FUNDING),
        ("e0-safety", E0),
        ("e1-t208-frozen", E1),
        ("production-locks", LOCKS),
        ("reused-existing-modules", REUSED),
        ("formal-baseline", FORMAL),
        ("real-h2-public", REAL_PUBLIC),
        ("c-freeze-12", tuple(c_freeze_paths())),
    )
    counts: dict[str, tuple[int, int]] = {}
    actual_by_path: dict[str, str] = {}
    for label, paths in groups:
        ok = 0
        lines.append(f"[{label}]")
        for rel in paths:
            path = ROOT / rel
            if not path.is_file():
                lines.append(f"MISSING *{rel}")
                continue
            actual = sha256_file(path)
            actual_by_path[rel] = actual
            lines.append(f"{actual} *{rel}")
            ok += 1
        counts[label] = (ok, len(paths))
        lines.append("")
    lines.append("[metadata-fingerprints]")
    for rel in METADATA_DIRS:
        directory = ROOT / rel
        fingerprint, count, total = tree_fingerprint(directory)
        actual_by_path[rel] = fingerprint
        lines.append(f"{fingerprint} *{rel} (files={count}, bytes={total})")
    lines += ["", "[counts]"]
    for label, (ok, total) in counts.items():
        lines.append(f"{label}={ok}/{total}")
    lines.append("")

    for label, snapshot in (("pre", PRE), ("post", POST)):
        text = snapshot.read_text(encoding="utf-8")
        expected: dict[str, str] = {}
        for line in text.splitlines():
            match = re.match(r"^([0-9a-f]{64}) \*(.+?)(?: \(files=\d+, bytes=\d+\))?$", line)
            if match:
                expected[match.group(2)] = match.group(1)
        missing = sorted(set(expected) - set(actual_by_path))
        changed = sorted(
            path for path in set(expected) & set(actual_by_path) if expected[path] != actual_by_path[path]
        )
        extra = sorted(set(actual_by_path) - set(expected))
        lines.append(
            f"[compare-{label}] expected={len(expected)} actual={len(actual_by_path)} "
            f"missing={len(missing)} changed={len(changed)} extra={len(extra)} "
            f"RESULT={'IDENTICAL' if not (missing or changed or extra) else 'DIFF'}"
        )
        for path in changed:
            lines.append(f"  CHANGED {path}: pre={expected[path]} now={actual_by_path[path]}")
        for path in missing:
            lines.append(f"  MISSING {path}")
        for path in extra:
            lines.append(f"  EXTRA {path}")
    return "\n".join(lines) + "\n"


def main() -> int:
    print(render(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
