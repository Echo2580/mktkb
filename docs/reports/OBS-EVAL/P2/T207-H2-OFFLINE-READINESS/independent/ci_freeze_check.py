"""C1 独立冻结复核：只输出 hash/路径/时间等安全聚合，不含题面/答案/key/私有内容。

产物写入同目录 ``freeze-recheck.txt``（脚本自身写文件，不经 shell 重定向）。
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[6]
FREEZE = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207-H2-OFFLINE-READINESS" / "evidence" / "c-freeze.txt"
A_FREEZE = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207-CAPTURE-CONTRACT-R2" / "evidence" / "a-freeze.txt"
B_FREEZE = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207-CROSS-ENTITY-SCOPE-R1" / "evidence" / "b-freeze.txt"
A_SITE = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207-CAPTURE-CONTRACT-R2" / "evidence" / "site-baseline.txt"
R11 = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207-PRODUCT-BEHAVIOR-REPAIR-R1" / "rework-r5-evidence" / "r11-freeze-hashes.txt"
FUNDING = (
    "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl",
    "docs/evidence/LOCAL-R1-20261101/budget/budget.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json",
)
DEPS = (
    "backend/src/mktkb/observability/evaluation_capture.py",
    "backend/src/mktkb/conversations/service.py",
    "backend/src/mktkb/qa/service.py",
    "backend/src/mktkb/rag/index.py",
    "tools/p2_h2_controlled_execute.py",
)

import hashlib  # noqa: E402


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_lines(path: Path, *, stop_at: tuple[str, ...] = ("[funding]",)) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if any(line.startswith(marker) for marker in stop_at):
            break
        if len(line) > 66 and line[64:66] == " *":
            rows[line[66:].strip()] = line[:64]
    return rows


def main() -> int:
    lines: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines.append("T207-H2-OFFLINE-READINESS independent freeze recheck (ai-ci)")
    lines.append(f"checked_utc: {now}")
    lines.append(f"cwd: {ROOT}")
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    lines.append(f"branch: {branch}")
    lines.append(f"head: {head}")
    lines.append(f"staged_changes: {len(staged)}")
    lines.append("")

    frozen = parse_lines(FREEZE, stop_at=("[funding]",))
    frozen_text = FREEZE.read_text(encoding="utf-8")
    frozen_utc = next(
        line.split(":", 1)[1].strip() for line in frozen_text.splitlines() if line.startswith("frozen_utc:")
    )
    frozen_dt = datetime.strptime(frozen_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    lines.append(f"frozen_utc: {frozen_utc}")
    lines.append("")
    lines.append("[final-object-bytes]")
    ok = 0
    for rel, expected in frozen.items():
        path = ROOT / rel
        actual = sha(path) if path.is_file() else "<MISSING>"
        state = "OK" if actual == expected else "MISMATCH"
        ok += 1 if state == "OK" else 0
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        late = "<=frozen" if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) <= frozen_dt else "AFTER-FROZEN"
        lines.append(f"{state} {actual} {rel} mtime={mtime} {late}")
    lines.append(f"objects_total={len(frozen)} objects_ok={ok}")
    lines.append("")

    lines.append("[A-unchanged-vs-a-freeze / B-final-vs-b-freeze]")
    a_rows = parse_lines(A_FREEZE)
    b_rows = parse_lines(B_FREEZE)
    mismatch = 0
    for rel, expected in {**a_rows, **b_rows}.items():
        actual = sha(ROOT / rel) if (ROOT / rel).is_file() else "<MISSING>"
        if actual != expected:
            mismatch += 1
            lines.append(f"MISMATCH {rel} expected={expected} actual={actual}")
    lines.append(f"a_items={len(a_rows)} b_items={len(b_rows)} cross_mismatch={mismatch}")
    lines.append("")

    lines.append("[unchanged-dependencies-vs-A-site-baseline]")
    deps = {rel: expected for rel, expected in parse_lines(A_SITE).items() if rel in DEPS}
    for rel in DEPS:
        actual = sha(ROOT / rel) if (ROOT / rel).is_file() else "<MISSING>"
        expected = deps.get(rel)
        state = "OK" if expected == actual else "MISMATCH"
        lines.append(f"{state} {actual} {rel}")
    lines.append("")

    lines.append("[funding]")
    for rel in FUNDING:
        lines.append(f"{sha(ROOT / rel)} {rel}")
    lines.append("")

    lines.append("[r11]")
    r11_rows = parse_lines(R11)
    r11_mismatch = 0
    r11_missing = 0
    for rel, expected in r11_rows.items():
        path = ROOT / rel
        if not path.is_file():
            r11_missing += 1
            lines.append(f"MISSING {rel}")
            continue
        if sha(path) != expected:
            r11_mismatch += 1
            lines.append(f"MISMATCH {rel}")
    lines.append(f"r11_items={len(r11_rows)} mismatches={r11_mismatch} missing={r11_missing}")
    lines.append("")
    lines.append(
        "RESULT: "
        + (
            "ALL_FROZEN_BYTES_OK"
            if ok == len(frozen) and mismatch == 0 and not staged and r11_mismatch == 0 and r11_missing == 0
            else "CHECK_FAILED"
        )
    )
    output = "\n".join(lines) + "\n"
    (HERE.parent / "freeze-recheck.txt").write_text(output, encoding="utf-8")
    print(output)
    return 0 if ok == len(frozen) and mismatch == 0 and not staged else 1


if __name__ == "__main__":
    raise SystemExit(main())
