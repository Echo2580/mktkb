"""零调用守卫：只拦**非回环**出站并计数，回环放行并单独计数；退出时写回执。

放在 PYTHONPATH 前面即可对整进程生效（pytest/子进程同样生效）。
之所以放行回环：进程内测试装配（TestClient/anyio/asyncio self-pipe）会用到回环，
拦掉它们会让被测代码根本没跑起来——那不是"零调用"，而是"没测"。
"""

from __future__ import annotations

import atexit
import json
import os
import socket

_EXTERNAL: list[str] = []
_LOOPBACK = 0
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver", "0.0.0.0", ""}


def _is_local(address) -> bool:
    host = None
    if isinstance(address, tuple) and address:
        host = address[0]
    elif isinstance(address, (str, bytes)):
        # AF_UNIX 或路径型地址
        return True
    if host is None:
        return False
    if isinstance(host, bytes):
        host = host.decode("utf-8", "ignore")
    return str(host) in _LOCAL_HOSTS


def _wrap(module, name: str) -> None:
    original = getattr(module, name)

    def wrapper(*args, **kwargs):
        global _LOOPBACK
        address = args[1] if name in ("connect", "connect_ex") and len(args) > 1 else (
            args[0] if args else None
        )
        if _is_local(address):
            _LOOPBACK += 1
            return original(*args, **kwargs)
        _EXTERNAL.append(f"{name}:{address!r}")
        raise OSError(f"netguard: non-loopback outbound blocked ({name} {address!r})")

    setattr(module, name, wrapper)


_wrap(socket.socket, "connect")
_wrap(socket.socket, "connect_ex")
_wrap(socket, "create_connection")


@atexit.register
def _flush() -> None:
    path = os.environ.get("NETGUARD_RECEIPT", "")
    if not path:
        return
    payload = {
        "schema_version": "v3-fix2-netguard/v0.2",
        "external_attempts": _EXTERNAL,
        "external_attempts_count": len(_EXTERNAL),
        "loopback_attempts": _LOOPBACK,
        "argv": os.sys.argv[:6],
        "patched": ["socket.socket.connect", "socket.socket.connect_ex", "socket.create_connection"],
        "loopback_hosts_allowed": sorted(_LOCAL_HOSTS),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
