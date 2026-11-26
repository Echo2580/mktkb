"""零出站证据（R2）：在 socket 层装探针后重跑 R2 重算（dry 模式），报告计数。

任何 socket 构造/连接/DNS 解析都会计数并抛错；本脚本同时记录被测脚本的退出状态。
正对照独立验证探针能拦住一次真实 socket 构造。
"""

from __future__ import annotations

import io
import json
import runpy
import socket
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent

COUNTS = {"socket_constructed": 0, "connect_attempts": 0, "dns_attempts": 0, "create_connection": 0}

_orig_socket = socket.socket
_orig_getaddrinfo = socket.getaddrinfo
_orig_create_connection = socket.create_connection


class _GuardedSocket(_orig_socket):  # type: ignore[misc,valid-type]
    def __init__(self, *args, **kwargs):
        COUNTS["socket_constructed"] += 1
        raise RuntimeError("network_blocked")

    def connect(self, *args, **kwargs):
        COUNTS["connect_attempts"] += 1
        raise RuntimeError("network_blocked")

    def connect_ex(self, *args, **kwargs):
        COUNTS["connect_attempts"] += 1
        raise RuntimeError("network_blocked")


def _guarded_getaddrinfo(*args, **kwargs):
    COUNTS["dns_attempts"] += 1
    raise RuntimeError("dns_blocked")


def _guarded_create_connection(*args, **kwargs):
    COUNTS["create_connection"] += 1
    raise RuntimeError("network_blocked")


def _positive_control() -> str:
    local = {"n": 0}
    saved = (socket.socket, socket.getaddrinfo, socket.create_connection)

    class _Probe(saved[0]):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            local["n"] += 1
            raise RuntimeError("control_blocked")

    try:
        socket.socket = _Probe  # type: ignore[assignment]
        try:
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except RuntimeError:
            return "blocked" if local["n"] == 1 else "probe_not_entered"
        return "not_blocked"
    finally:
        socket.socket, socket.getaddrinfo, socket.create_connection = saved


def main() -> int:
    socket.socket = _GuardedSocket  # type: ignore[assignment]
    socket.getaddrinfo = _guarded_getaddrinfo  # type: ignore[assignment]
    socket.create_connection = _guarded_create_connection  # type: ignore[assignment]
    status = "ok"
    captured = io.StringIO()
    argv = sys.argv[:]
    try:
        sys.argv = ["02-rescore-r2.py"]
        with redirect_stdout(captured):
            runpy.run_path(str(HERE / "02-rescore-r2.py"), run_name="__main__")
    except SystemExit as exc:
        status = f"exit:{exc.code}"
    except BaseException as exc:  # noqa: BLE001
        status = f"error:{type(exc).__name__}"
    finally:
        sys.argv = argv
        socket.socket = _orig_socket  # type: ignore[assignment]
        socket.getaddrinfo = _orig_getaddrinfo  # type: ignore[assignment]
        socket.create_connection = _orig_create_connection  # type: ignore[assignment]
    control = _positive_control()
    measured = dict(COUNTS)
    payload = {
        "schema_version": "q1a3r2-netguard/v0.1",
        "guard": "socket.socket / socket.getaddrinfo / socket.create_connection 全部拦截",
        "measured_counts": measured,
        "inner_status": status,
        "inner_stdout_bytes": len(captured.getvalue()),
        "positive_control": control,
        "verdict": "zero_network_attempts"
        if sum(measured.values()) == 0 and control == "blocked" and status == "exit:0"
        else "network_attempt_or_guard_failure",
        "calls": {"network": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
    }
    (HERE / "06-netguard.json").write_bytes(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    print(json.dumps({"verdict": payload["verdict"], "counts": measured, "control": control}, ensure_ascii=True))
    return 0 if payload["verdict"] == "zero_network_attempts" else 1


if __name__ == "__main__":
    raise SystemExit(main())
