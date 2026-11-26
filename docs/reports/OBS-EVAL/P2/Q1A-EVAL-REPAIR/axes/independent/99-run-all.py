#!/usr/bin/env python
"""探针汇总运行器：按顺序跑独立验收探针，记录退出码（最后跑 17 以复核字节稳定）。

输出：99-run-all.out.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
ORDER = [
    "10-static-reuse.py",
    "11-axis-semantics.py",
    "12-counts-provenance.py",
    "13-oldcard-write.py",
    "14-q1a2-adapter.py",
    "15-run-netguard-controls.py",
    "16-contract-consistency.py",
    "18-dev-evidence-audit.py",
    "19-residual-probes.py",
    "17-final-freeze.py",
]


def main() -> int:
    env = dict(os.environ)
    env.update({"MKTKB_NO_DOTENV": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    runs = []
    for name in ORDER:
        completed = subprocess.run(
            [sys.executable, str(HERE / name)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        runs.append(
            {
                "probe": name,
                "exit_code": completed.returncode,
                "stdout_tail": completed.stdout.strip().splitlines()[-4:],
                "stderr_tail": completed.stderr.strip().splitlines()[-4:],
            }
        )
    failures = [item for item in runs if item["exit_code"] != 0]
    payload = {
        "probe": "99-run-all",
        "runs": runs,
        "failed": failures,
        "verdict": "PASS" if not failures else "FAIL",
    }
    (HERE / "99-run-all.out.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": payload["verdict"], "failed": [item["probe"] for item in failures]}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
