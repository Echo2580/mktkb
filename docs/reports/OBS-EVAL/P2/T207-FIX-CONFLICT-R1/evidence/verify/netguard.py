"""验收脚本共用的零出站闸门。

只放行 AF_UNIX 与 loopback（Windows asyncio 自管道会走 127.0.0.1 的 TCP socketpair），
其余 AF_INET/AF_INET6 连接一律失败并记账。装配侧另有 b0.assert_fake_configuration 守住假凭据。
"""

from __future__ import annotations

import socket

BLOCKED: list[str] = []
LOOPBACK: list[str] = []
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_orig_create_connection = socket.create_connection


def _is_loopback(address) -> bool:
    if not isinstance(address, tuple) or not address:
        return False
    host = str(address[0])
    return host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127.")


def _check(family, address) -> None:
    if family in (socket.AF_INET, socket.AF_INET6):
        if not _is_loopback(address):
            BLOCKED.append(repr(address))
            raise AssertionError(f"BLOCKED-OUTBOUND {address!r}")
        LOOPBACK.append(repr(address))


def _guard(self, address):
    _check(self.family, address)
    return _real_connect(self, address)


def _guard_ex(self, address):
    _check(self.family, address)
    return _real_connect_ex(self, address)


def _create_connection(address, *args, **kwargs):
    _check(socket.AF_INET, address)
    return _orig_create_connection(address, *args, **kwargs)


def install() -> None:
    socket.socket.connect = _guard
    socket.socket.connect_ex = _guard_ex
    socket.create_connection = _create_connection


def summary() -> dict:
    return {
        "outbound_guard": "non-loopback AF_INET/AF_INET6 connect blocked",
        "blocked_attempts": BLOCKED,
        "loopback_connects": len(LOOPBACK),
    }
