"""T209-PREP 保护件快照（只读）：显式文件用 SHA256，受保护目录用元数据指纹。

设计取舍（写进 dev-report）：

- 显式保护文件（资金/GO/生产锁/C 冻结对象/E0/E1/正式 baseline/既有复用模块）逐个算
  SHA256，能发现任意字节变化；
- 大目录（``docs/evidence/LOCAL-R1-20261101`` 约 4.7GB、真实 H2 报告树、T208 报告根）
  只用「相对路径 + 字节数 + mtime_ns」的 SHA256 指纹，不读取文件内容，避免触碰
  私有逐题/密文材料的边界；元数据变化（增删/改名/改大小/被写）都会改变指纹；
- 本脚本只读，不创建/修改任何受保护对象；输出 UTF-8 文本。
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
C_FREEZE = ROOT / "docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/evidence/c-freeze.txt"
FUNDING = (
    "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl",
    "docs/evidence/LOCAL-R1-20261101/budget/budget.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.t207-h2-run-20261114.pre.archived.json",
)
E0 = (
    "docs/reports/OBS-EVAL/P2/T207-SAFETY-TRIAGE-20261114/custodian-a-aggregate.json",
    "docs/reports/OBS-EVAL/P2/T207-SAFETY-TRIAGE-20261114/custodian-a-report.md",
    "docs/reports/OBS-EVAL/P2/T207-SAFETY-TRIAGE-20261114/custodian-b-review.json",
    "docs/reports/OBS-EVAL/P2/T207-SAFETY-TRIAGE-20261114/custodian-b-review.md",
    "docs/reports/OBS-EVAL/P2/T207-SAFETY-TRIAGE-20261114/manager-receipt.json",
    "docs/reports/OBS-EVAL/P2/T207-SAFETY-TRIAGE-20261114/manager-receipt.md",
)
E1 = (
    "backend/src/mktkb/evaluation/ragas_adapter.py",
    "backend/tests/evaluation/test_p2_ragas_adapter.py",
    "backend/tests/evaluation/test_p2_judge_budget.py",
    "docs/evaluation/p2-ragas-contract.md",
    "backend/requirements-ragas-eval.lock",
)
LOCKS = (
    "backend/requirements.lock",
    "backend/requirements-dev.lock",
)
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
    """解析 c-freeze.txt 的 [final-object-bytes] + [C-new]（12 项），保持登记顺序。"""
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
    """目录元数据指纹：相对路径 + 字节数 + mtime_ns（不读内容）。"""
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


def main() -> int:
    lines: list[str] = [
        "T209-PREP protected-object snapshot (READ-ONLY)",
        f"repo_root: {ROOT}",
        "note: explicit files = SHA256 of content; directories = metadata fingerprint",
        "",
        "[funding]",
    ]
    groups = (
        ("[funding]", FUNDING),
        ("[e0-safety]", E0),
        ("[e1-t208-frozen]", E1),
        ("[production-locks]", LOCKS),
        ("[reused-existing-modules]", REUSED),
        ("[formal-baseline]", FORMAL),
        ("[real-h2-public]", REAL_PUBLIC),
        ("[c-freeze-12]", tuple(c_freeze_paths())),
    )
    first = True
    for label, paths in groups:
        if label == "[funding]":
            lines.append("")
        else:
            lines += ["", label]
        for rel in paths:
            path = ROOT / rel
            if not path.is_file():
                lines.append(f"MISSING {rel}")
                continue
            lines.append(f"{sha256_file(path)} *{rel}")
        first = False
    lines += ["", "[metadata-fingerprints]"]
    for rel in METADATA_DIRS:
        directory = ROOT / rel
        if not directory.is_dir():
            lines.append(f"MISSING {rel}")
            continue
        fingerprint, count, total = tree_fingerprint(directory)
        lines.append(f"{fingerprint} *{rel} (files={count}, bytes={total})")
    lines += ["", "[c-freeze-count]", f"c_freeze_items={len(c_freeze_paths())}"]
    text = "\n".join(lines) + "\n"
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out is None:
        sys.stdout.write(text)
    else:
        out.write_text(text, encoding="utf-8")
        sys.stdout.write(f"written {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
