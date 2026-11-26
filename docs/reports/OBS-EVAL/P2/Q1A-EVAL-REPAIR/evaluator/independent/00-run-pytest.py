"""Q1a-1 独立验收：复跑开发测试并保存 UTF-8 证据（只跑新增测试）。

运行（仓库根）：
  .venv/Scripts/python.exe docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/independent/00-run-pytest.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
OUT = Path(__file__).resolve().with_name("00-pytest-independent.txt")
BASETEMP = Path(tempfile.mkdtemp(prefix="q1a1-indep-pytest-"))
command = [
    sys.executable, "-m", "pytest",
    "backend/tests/evaluation/test_p2_evidence_rescore.py",
    "-q", "-p", "no:cacheprovider", "--basetemp", str(BASETEMP), "--color=no",
]
env = os.environ.copy()
env.update({"MKTKB_NO_DOTENV": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
collect = subprocess.run(command + ["--collect-only"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=env)
result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", env=env)
header = (
    "# Q1a-1 独立验收：复跑开发测试（只跑新增测试；零真实出站）\n"
    "# 环境：MKTKB_NO_DOTENV=1；PYTHONDONTWRITEBYTECODE=1；-p no:cacheprovider\n"
    f"# 命令：{' '.join(command)}\n\n"
    "## collect-only\n"
)
body = (
    header + collect.stdout + collect.stderr + f"\ncollect_exit_code={collect.returncode}\n\n"
    "## run\n" + result.stdout + result.stderr + f"\nrun_exit_code={result.returncode}\n"
)
OUT.write_text(body, encoding="utf-8")
print(f"collect_exit_code={collect.returncode}")
print(f"run_exit_code={result.returncode}")
print(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(no stdout)")
raise SystemExit(0 if result.returncode == 0 and collect.returncode == 0 else 1)
