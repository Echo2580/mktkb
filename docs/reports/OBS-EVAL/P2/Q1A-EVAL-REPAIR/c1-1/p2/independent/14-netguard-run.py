"""C1-P2 独立验收：零真实调用（进程级出站守卫 + 正向控制 + 隔离 import）。

三个子进程，各自带 sitecustomize 守卫：
  1) control：只跑正向控制测试 —— 必须拦截并记账；
  2) suite：跑全部 88 项 —— 退出时 external/socket/DNS/httpx 必须全 0；
  3) isolated：stub mktkb 只 import 新模块 —— 不得加载 provider/冻结模块。
守卫计数在退出时写 JSON；本脚本汇总为 14-zero-call.json。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
BACKEND = REPO / "backend"
IND = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/independent"
NETGUARD = IND / "netguard"
PY = REPO / ".venv/Scripts/python.exe"
OUT = IND / "14-zero-call.json"


def run(name: str, args: list[str], guard_out: Path, log_name: str) -> dict:
    env = dict(os.environ)
    env["MKTKB_NO_DOTENV"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(NETGUARD) + os.pathsep + str(BACKEND / "src")
    env["C1P2_GUARD_OUT"] = str(guard_out)
    completed = subprocess.run(
        [str(PY), "-B", *args],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    (IND / log_name).write_text(
        f"$ {' '.join(args)}\nexit={completed.returncode}\n--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}\n",
        encoding="utf-8",
    )
    guard = json.loads(guard_out.read_text(encoding="utf-8")) if guard_out.is_file() else None
    return {
        "name": name,
        "exit": completed.returncode,
        "stdout_tail": completed.stdout.strip().splitlines()[-3:],
        "stderr_tail": completed.stderr.strip().splitlines()[-5:],
        "guard": guard,
        "log": str(IND / log_name),
        "guard_json": str(guard_out),
    }


def main() -> int:
    control = run(
        "control",
        ["-m", "pytest", str(IND / "test_00_netguard_positive_control.py"), "-q", "-p", "no:cacheprovider"],
        IND / "14a-control-guard.json",
        "14a-control.txt",
    )
    suite = run(
        "suite",
        [
            "-m",
            "pytest",
            "tests/evaluation/test_p2_empty_scope_proof.py",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            ".pytest-tmp/c1p2-netguard",
        ],
        IND / "14b-suite-guard.json",
        "14b-suite.txt",
    )
    isolated = run(
        "isolated",
        [str(IND / "14c-isolated-import.py")],
        IND / "14c-isolated-guard.json",
        "14c-isolated.txt",
    )

    def zero(g: dict | None) -> bool:
        if not g:
            return False
        return all(
            g.get(key, 0) == 0
            for key in (
                "socket_connect_attempts",
                "socket_connect_ex_attempts",
                "create_connection_attempts",
                "dns_getaddrinfo_attempts",
                "http_client_connect_attempts",
                "httpx_transport_attempts",
            )
        )

    positive = (control["guard"] or {}).get("positive_control") or {}
    control_ok = bool(
        control["guard"]
        and positive.get("blocked") is True
        and positive.get("attempted") is True
        and positive.get("socket_blocked") is True
        and positive.get("dns_blocked") is True
        and positive.get("httpx_blocked") is True
        and int(positive.get("blocked_total_after_attempt") or 0) >= 3
        and any(
            "203.0.113.1" in str(detail.get("detail", ""))
            for detail in (positive.get("details") or [])
        )
        and any(
            "example.invalid" in str(detail.get("detail", ""))
            for detail in (positive.get("details") or [])
        )
    )
    payload = {
        "schema_version": "c1p2-independent-zero-call/v0.1",
        "control": control,
        "suite": suite,
        "isolated": isolated,
        "verdicts": {
            "positive_control_blocked_and_recorded": control_ok,
            "suite_zero_external": zero(suite["guard"]),
            "control_exit_zero": control["exit"] == 0,
            "suite_exit_zero": suite["exit"] == 0,
            "isolated_exit_zero": isolated["exit"] == 0,
            "suite_guard_present": suite["guard"] is not None,
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(payload["verdicts"], ensure_ascii=False, indent=1))
    print("control guard:", json.dumps(control["guard"], ensure_ascii=False)[:1200])
    print("suite guard:", json.dumps(suite["guard"], ensure_ascii=False)[:1200])
    print("isolated guard:", json.dumps(isolated["guard"], ensure_ascii=False)[:800])
    print("suite tail:", suite["stdout_tail"])
    return 0 if all(payload["verdicts"].values()) else 4


if __name__ == "__main__":
    raise SystemExit(main())
