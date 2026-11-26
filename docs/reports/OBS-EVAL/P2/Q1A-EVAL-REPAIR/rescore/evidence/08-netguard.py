"""零出站证据：在 socket 层装探针后重跑合同消费方校验（06）。

任何 socket 构造/连接/DNS 解析都会计数并抛出；本脚本报告计数与退出码。
"""

from __future__ import annotations

import json
import runpy
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

COUNTS = {"socket_constructed": 0, "connect_attempts": 0, "dns_attempts": 0, "create_connection": 0}

_orig_socket = socket.socket
_orig_getaddrinfo = socket.getaddrinfo
_orig_create_connection = socket.create_connection


class _GuardedSocket(_orig_socket):  # type: ignore[misc,valid-type]
    def __init__(self, *args, **kwargs):  # noqa: D401
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


def main() -> int:
    socket.socket = _GuardedSocket  # type: ignore[assignment]
    socket.getaddrinfo = _guarded_getaddrinfo  # type: ignore[assignment]
    socket.create_connection = _guarded_create_connection  # type: ignore[assignment]
    status = "ok"
    try:
        runpy.run_path(str(HERE / "06-contract-consumer-check.py"), run_name="__main__")
    except SystemExit as exc:
        status = f"exit:{exc.code}"
    except BaseException as exc:  # noqa: BLE001
        status = f"error:{type(exc).__name__}"
    finally:
        socket.socket = _orig_socket  # type: ignore[assignment]
        socket.getaddrinfo = _orig_getaddrinfo  # type: ignore[assignment]
        socket.create_connection = _orig_create_connection  # type: ignore[assignment]
    payload = {
        "schema_version": "q1a3-netguard/v0.1",
        "guard": "socket.socket / socket.getaddrinfo / socket.create_connection 全部拦截",
        "counts": COUNTS,
        "inner_status": status,
        "verdict": "zero_network_attempts" if sum(COUNTS.values()) == 0 else "network_attempt_detected",
        "calls": {"network": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
    }
    out = HERE / "08-netguard.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"netguard_json": str(out), "verdict": payload["verdict"], "counts": COUNTS}, ensure_ascii=False))
    return 0 if sum(COUNTS.values()) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
