"""探针 15 运行器：正向控制必须 exit 0，负向控制必须 exit 1 且命中 teardown 断言。

输出：15-netguard-controls.out.json（含两次 pytest 的退出码与关键行）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
BASETEMP = ROOT / "backend" / ".pytest-tmp" / "q1a1b-independent-netguard"


def run(path: Path, basetemp: Path) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "MKTKB_NO_DOTENV": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": os.pathsep.join(
                [str(ROOT / "backend" / "src"), str(ROOT / "backend" / "tests"), str(HERE)]
            ),
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(path),
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(basetemp),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "file": path.name,
        "exit_code": completed.returncode,
        "stdout_tail": completed.stdout.strip().splitlines()[-12:],
        "stderr_tail": completed.stderr.strip().splitlines()[-12:],
        "teardown_assert_hit": "检测到真实外部出站尝试" in (completed.stdout + completed.stderr),
    }


def main() -> int:
    positive = run(HERE / "test_15_netguard_controls.py", BASETEMP / "positive")
    negative = run(HERE / "_test_netguard_negative.py", BASETEMP / "negative")
    checks = [
        {
            "label": "positive control: guard tests pass (exit 0)",
            "ok": positive["exit_code"] == 0,
            "detail": positive,
        },
        {
            "label": "negative control: uncleared external attempt fails teardown (exit 1 + assertion)",
            "ok": negative["exit_code"] == 1 and negative["teardown_assert_hit"],
            "detail": negative,
        },
    ]
    failures = [item for item in checks if not item["ok"]]
    payload = {
        "probe": "15-netguard-controls",
        "assertions_total": len(checks),
        "assertions_failed": len(failures),
        "checks": checks,
        "verdict": "PASS" if not failures else "FAIL",
    }
    (HERE / "15-netguard-controls.out.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verdict": payload["verdict"], "positive_exit": positive["exit_code"], "negative_exit": negative["exit_code"], "negative_assert_hit": negative["teardown_assert_hit"]}, ensure_ascii=False))
    if failures:
        print(json.dumps(failures, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
