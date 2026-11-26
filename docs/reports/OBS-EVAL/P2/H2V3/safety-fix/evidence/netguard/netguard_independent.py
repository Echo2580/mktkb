"""独立零调用守卫：进程内拦截一切非回环出站（不依赖本机代理）。

- 导入即删除代理环境变量（ALL_PROXY/HTTP_PROXY/HTTPS_PROXY/NO_PROXY/NODE_USE_ENV_PROXY）；
- 拦截 socket.connect / connect_ex / create_connection / getaddrinfo；
- 回环地址放行并计数（pytest/anyio 在 Windows 上可能需要 loopback socketpair）；
- 退出时把计数写到 NETGUARD_OUT。
"""
from __future__ import annotations

import atexit
import json
import os
import socket
from typing import Any

PROXY_NAMES = ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "NODE_USE_ENV_PROXY")
REMOVED = [name for name in PROXY_NAMES if name in os.environ]
for _name in REMOVED:
    os.environ.pop(_name, None)

OUT = os.environ.get("NETGUARD_OUT")
EXTERNAL: list[str] = []
LOOPBACK = 0
_CALLS = 0
_ORIG = {
    "connect": socket.socket.connect,
    "connect_ex": socket.socket.connect_ex,
    "create_connection": socket.create_connection,
    "getaddrinfo": socket.getaddrinfo,
}


def _is_loopback(host: Any) -> bool:
    if isinstance(host, bytes):
        host = host.decode("latin-1", "replace")
    return str(host) in {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def _host_of(address: Any) -> Any:
    if isinstance(address, tuple) and address:
        return address[0]
    return address


def _connect(self, address):  # type: ignore[no-untyped-def]
    global LOOPBACK
    if _is_loopback(_host_of(address)):
        LOOPBACK += 1
        return _ORIG["connect"](self, address)
    EXTERNAL.append(f"connect:{address!r}")
    raise OSError("netguard-independent: outbound blocked")


def _connect_ex(self, address):  # type: ignore[no-untyped-def]
    global LOOPBACK
    if _is_loopback(_host_of(address)):
        LOOPBACK += 1
        return _ORIG["connect_ex"](self, address)
    EXTERNAL.append(f"connect_ex:{address!r}")
    raise OSError("netguard-independent: outbound blocked")


def _create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
    global LOOPBACK
    if _is_loopback(_host_of(address)):
        LOOPBACK += 1
        return _ORIG["create_connection"](address, *args, **kwargs)
    EXTERNAL.append(f"create_connection:{address!r}")
    raise OSError("netguard-independent: outbound blocked")


def _getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
    global LOOPBACK
    if _is_loopback(host):
        LOOPBACK += 1
        return _ORIG["getaddrinfo"](host, port, *args, **kwargs)
    EXTERNAL.append(f"getaddrinfo:{host!r}:{port!r}")
    raise OSError("netguard-independent: outbound blocked")


socket.socket.connect = _connect  # type: ignore[assignment]
socket.socket.connect_ex = _connect_ex  # type: ignore[assignment]
socket.create_connection = _create_connection  # type: ignore[assignment]
socket.getaddrinfo = _getaddrinfo  # type: ignore[assignment]


def _flush() -> None:
    if not OUT:
        return
    try:
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "schema_version": "v3-fix1-independent-netguard/v0.1",
                    "proxy_env_removed": REMOVED,
                    "external_attempts": EXTERNAL,
                    "external_count": len(EXTERNAL),
                    "loopback_calls": LOOPBACK,
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
            fh.write("\n")
    except OSError:
        pass


atexit.register(_flush)
