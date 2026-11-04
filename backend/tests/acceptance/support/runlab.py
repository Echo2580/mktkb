"""命令执行与原始日志记录：argv / cwd / 起止 / 退出码 / stdout / stderr。

用法（只用 .venv\\Scripts\\python.exe -B 调用）：

    python -B backend/tests/acceptance/support/runlab.py --label t09-b0-01 -- <命令 ...>

产物（全部在 docs/evidence/T09/D1/logs/ 下，按 label 唯一，不覆盖既有文件）：
    <label>.command.json / <label>.stdout.log / <label>.stderr.log / <label>.exitcode

子进程输出同时回显到父进程，便于直接观察；日志不写入任何密钥（子进程只收到本机参数与环境）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LOGS = ROOT / "docs" / "evidence" / "T09" / "D1" / "logs"
LOGS = DEFAULT_LOGS


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main(argv: list[str]) -> int:
    if "--label" not in argv:
        print("缺少 --label", file=sys.stderr)
        return 2
    split = argv.index("--label")
    label = argv[split + 1]
    if "--out" in argv:
        out_index = argv.index("--out")
        global LOGS
        LOGS = Path(argv[out_index + 1])
        if not LOGS.is_absolute():
            LOGS = ROOT / LOGS
        del argv[out_index : out_index + 2]
    if "--" not in argv:
        print("缺少 -- <命令>", file=sys.stderr)
        return 2
    command = argv[argv.index("--") + 1 :]
    if not command:
        print("命令为空", file=sys.stderr)
        return 2

    LOGS.mkdir(parents=True, exist_ok=True)
    targets = {
        "command": LOGS / f"{label}.command.json",
        "stdout": LOGS / f"{label}.stdout.log",
        "stderr": LOGS / f"{label}.stderr.log",
        "exitcode": LOGS / f"{label}.exitcode",
    }
    for key, path in targets.items():
        if path.exists():
            print(f"日志已存在，拒绝覆盖：{path}（请使用新的 label）", file=sys.stderr)
            return 2

    started = _now()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    working_directory = ROOT
    if "--cwd" in argv:
        cwd_index = argv.index("--cwd")
        working_directory = Path(argv[cwd_index + 1])
        if not working_directory.is_absolute():
            working_directory = ROOT / working_directory
        del argv[cwd_index : cwd_index + 2]
    process = subprocess.run(
        command,
        cwd=working_directory,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    ended = _now()

    targets["stdout"].write_text(process.stdout or "", encoding="utf-8")
    targets["stderr"].write_text(process.stderr or "", encoding="utf-8")
    targets["exitcode"].write_text(f"{process.returncode}\n", encoding="utf-8")
    record = {
        "label": label,
        "argv": command,
        "cwd": str(working_directory),
        "started_at": started,
        "ended_at": ended,
        "exitcode": process.returncode,
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "os": os.name,
        "stdout_path": str(targets["stdout"].relative_to(ROOT)),
        "stderr_path": str(targets["stderr"].relative_to(ROOT)),
        "stdout_bytes": len((process.stdout or "").encode("utf-8")),
        "stderr_bytes": len((process.stderr or "").encode("utf-8")),
        "stdout_tail": (process.stdout or "").strip().splitlines()[-15:],
        "stderr_tail": (process.stderr or "").strip().splitlines()[-15:],
    }
    targets["command"].write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    sys.stdout.write(process.stdout or "")
    sys.stderr.write(process.stderr or "")
    print(f"\n[runlab] label={label} exitcode={process.returncode} log={targets['command']}")
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
