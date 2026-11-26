"""T209-PREP 独立验收：冻结清单重算 + 开发证据可复现。

1. 重算 evidence/11-freeze.txt 中 18 个对象的 SHA256；
2. 重算 dev-report / 新模块 / 新测试的 hash，与冻结清单逐项比较；
3. 用**开发脚本的公开入口**独立重跑 render_example.py / chain_demo.py（输出写到本目录），
   与开发 evidence/04-report-example.md、05-chain-demo.txt 做字节比较（meta 行除外）；
4. 检查 04-report-example.md 与 11-freeze.txt 的冻结 hash 一致。
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
REPORT = ROOT / "docs/reports/OBS-EVAL/P2/T209-PREP"
INDEP = REPORT / "independent"
FREEZE = REPORT / "evidence/11-freeze.txt"
PY = str(ROOT / ".venv/Scripts/python.exe")

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    entries = []
    for line in FREEZE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([0-9a-f]{64}) \*(.+)$", line.strip())
        if match:
            entries.append((match.group(2), match.group(1)))
    declared = int(re.search(r"new_objects=(\d+)", FREEZE.read_text(encoding="utf-8")).group(1))
    check(len(entries) == declared, f"F1 冻结清单 {declared} 项", str(len(entries)))
    bad = []
    for rel, expected in entries:
        path = ROOT / rel
        if not path.is_file():
            bad.append(f"MISSING {rel}")
            continue
        actual = sha(path)
        if actual != expected:
            bad.append(f"CHANGED {rel}")
    check(not bad, f"F2 冻结清单 {declared}/{declared} 重算一致", str(bad))

    dev_report = REPORT / "dev-report.md"
    module = ROOT / "backend/src/mktkb/evaluation/p2_candidate_report.py"
    test = ROOT / "backend/tests/evaluation/test_p2_candidate_report.py"
    frozen = dict(entries)
    for rel, path in (
        ("backend/src/mktkb/evaluation/p2_candidate_report.py", module),
        ("backend/tests/evaluation/test_p2_candidate_report.py", test),
        ("docs/reports/OBS-EVAL/P2/T209-PREP/dev-report.md", dev_report),
    ):
        check(frozen.get(rel) == sha(path), f"F3 {Path(rel).name} hash 与冻结清单一致", sha(path)[:16])

    # 开发证据可复现：render_example 只读模块 + 公开计数
    render_out = INDEP / "repro-04-report-example.md"
    completed = subprocess.run(
        [PY, str(REPORT / "evidence/render_example.py"), str(render_out)],
        capture_output=True, text=True, check=False, cwd=str(ROOT),
        encoding="utf-8", errors="replace",
    )
    check(completed.returncode == 0, "F4 render_example.py 复跑退出码 0", completed.stderr.strip()[-200:])
    if render_out.exists():
        check(
            render_out.read_bytes() == (REPORT / "evidence/04-report-example.md").read_bytes(),
            "F5 04-report-example.md 可逐字节复现",
            f"len={render_out.stat().st_size}",
        )
    else:
        check(False, "F5 04-report-example.md 可逐字节复现", "output missing")

    chain_out = INDEP / "repro-05-chain-demo.txt"
    completed = subprocess.run(
        [PY, str(REPORT / "evidence/chain_demo.py"), str(chain_out)],
        capture_output=True, text=True, check=False, cwd=str(ROOT),
        encoding="utf-8", errors="replace",
    )
    check(completed.returncode == 0, "F6 chain_demo.py 复跑退出码 0", completed.stderr.strip()[-200:])
    if chain_out.exists():
        dev_lines = [
            line
            for line in (REPORT / "evidence/05-chain-demo.txt").read_text(encoding="utf-8").splitlines()
            if not line.startswith("[") and not line.startswith("cwd=") and not line.startswith("exit_code=")
            and not line.startswith("script=") and not line.startswith("env=") and not line.startswith("result=")
            and line.strip()
        ]
        my_lines = [line for line in chain_out.read_text(encoding="utf-8").splitlines() if line.strip()]
        check(dev_lines == my_lines, "F7 05-chain-demo.txt 复跑文本一致", f"dev={len(dev_lines)} mine={len(my_lines)}")
    else:
        check(False, "F7 05-chain-demo.txt 复跑文本一致", "output missing")

    failed = [name for ok, name, _ in RESULTS if not ok]
    print(f"\nchecks={len(RESULTS)} failed={len(failed)}")
    print("RESULT=" + ("PASS" if not failed else "FAIL"))
    for name in failed:
        print("FAILED_CHECK=" + name)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
