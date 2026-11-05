"""运行命令并把 stdout+stderr 以 UTF-8 写入指定证据文件（仓库外工具）。"""

import os
import subprocess
import sys

out_path, *cmd = sys.argv[1:]
env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"
proc = subprocess.run(
    cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env
)
with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write("# CMD: " + " ".join(cmd) + "\n")
    handle.write(proc.stdout)
    if proc.stderr:
        handle.write("\n[stderr]\n" + proc.stderr)
    handle.write(f"\nEXIT_CODE={proc.returncode}\n")
print(f"captured exit={proc.returncode} -> {out_path}")
