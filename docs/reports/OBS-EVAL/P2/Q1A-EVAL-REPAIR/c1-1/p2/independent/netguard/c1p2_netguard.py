"""C1-P2 独立验收：进程级出站守卫（sitecustomize 注入）。

目标不是“证明没有 import 网络库”，而是证明**没有发生任何外部连接/DNS**：
- AF_INET/AF_INET6 socket 的 connect/connect_ex → 记录并抛 OSError；
- socket.create_connection → 记录并抛 OSError；
- socket.getaddrinfo（非 localhost）→ 记录并抛 OSError；
- http.client.HTTPConnection.connect → 记录并抛 OSError；
- httpx HTTPTransport.handle_request / AsyncHTTPTransport.handle_async_request
  （若 httpx 被 import）→ 记录并抛 OSError。

guard 自身不做任何网络访问；计数只保存在内存，退出时由 sitecustomize 落盘。
"""

from __future__ import annotations

import atexit
import json
import os
import socket
import sys
import traceback
from typing import Any

_STATE: dict[str, Any] = {
    "socket_connect_attempts": 0,
    "socket_connect_ex_attempts": 0,
    "create_connection_attempts": 0,
    "dns_getaddrinfo_attempts": 0,
    "http_client_connect_attempts": 0,
    "httpx_transport_attempts": 0,
    "inet_socket_created": 0,
    "blocked": 0,
    "details": [],
    "positive_control": None,
    "installed": False,
    "httpx_patched": False,
    "modules_at_exit": [],
}
_ORIGINALS: dict[str, Any] = {}


def _note(kind: str, detail: str) -> None:
    _STATE[kind] = int(_STATE.get(kind, 0)) + 1
    _STATE["blocked"] = int(_STATE["blocked"]) + 1
    if len(_STATE["details"]) < 50:
        _STATE["details"].append({"kind": kind, "detail": detail})
    print(f"[c1p2-netguard] BLOCKED {kind}: {detail}", file=sys.stderr)


def _raise(kind: str) -> None:
    raise OSError(f"c1p2-netguard blocked {kind}")


def install() -> None:
    if _STATE["installed"]:
        return
    _STATE["installed"] = True

    original_socket = socket.socket
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    _ORIGINALS.update(
        {
            "connect": original_connect,
            "connect_ex": original_connect_ex,
            "create_connection": original_create_connection,
            "getaddrinfo": original_getaddrinfo,
        }
    )

    def guarded_connect(self, address):  # noqa: ANN001
        _note("socket_connect_attempts", repr(address))
        _raise("socket_connect")

    def guarded_connect_ex(self, address):  # noqa: ANN001
        _note("socket_connect_ex_attempts", repr(address))
        _raise("socket_connect_ex")

    def guarded_create_connection(address, *args, **kwargs):  # noqa: ANN001
        _note("create_connection_attempts", repr(address))
        _raise("create_connection")

    def guarded_getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
        text = str(host)
        if text in {"127.0.0.1", "::1", "localhost", ""}:
            return original_getaddrinfo(host, *args, **kwargs)
        _note("dns_getaddrinfo_attempts", text)
        _raise("dns_getaddrinfo")

    socket.socket.connect = guarded_connect  # type: ignore[assignment]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[assignment]
    socket.create_connection = guarded_create_connection  # type: ignore[assignment]
    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]

    try:
        import http.client as http_client

        original_http_connect = http_client.HTTPConnection.connect

        def guarded_http_connect(self):  # noqa: ANN001
            _note("http_client_connect_attempts", f"{self.host}:{self.port}")
            _raise("http_client_connect")

        http_client.HTTPConnection.connect = guarded_http_connect  # type: ignore[assignment]
        _ORIGINALS["http_connect"] = original_http_connect
    except Exception:  # noqa: BLE001
        pass

    # httpx 是测试依赖（fastapi.testclient 会 import）；在 import 后补丁 transport。
    def _patch_httpx() -> None:
        module = sys.modules.get("httpx")
        if module is None or _STATE["httpx_patched"]:
            return
        try:
            transport = module.HTTPTransport
            async_transport = module.AsyncHTTPTransport

            original_handle = transport.handle_request

            def guarded_handle(self, request):  # noqa: ANN001
                _note("httpx_transport_attempts", str(getattr(request, "url", request)))
                _raise("httpx_transport")

            transport.handle_request = guarded_handle  # type: ignore[assignment]
            _ORIGINALS["httpx_handle"] = original_handle

            original_async = async_transport.handle_async_request

            async def guarded_async(self, request):  # noqa: ANN001
                _note("httpx_transport_attempts", str(getattr(request, "url", request)))
                _raise("httpx_transport")

            async_transport.handle_async_request = guarded_async  # type: ignore[assignment]
            _ORIGINALS["httpx_async"] = original_async
            _STATE["httpx_patched"] = True
        except Exception:  # noqa: BLE001
            pass

    # 每次 import 后尝试补丁（低成本；只 patch 一次）。
    import builtins

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):  # noqa: ANN001
        module = original_import(name, *args, **kwargs)
        if name == "httpx" or name.startswith("httpx."):
            _patch_httpx()
        return module

    builtins.__import__ = guarded_import  # type: ignore[assignment]
    _ORIGINALS["import"] = original_import


def snapshot() -> dict[str, Any]:
    return json.loads(json.dumps(_STATE))


def reset() -> None:
    for key in (
        "socket_connect_attempts",
        "socket_connect_ex_attempts",
        "create_connection_attempts",
        "dns_getaddrinfo_attempts",
        "http_client_connect_attempts",
        "httpx_transport_attempts",
        "inet_socket_created",
        "blocked",
    ):
        _STATE[key] = 0
    _STATE["details"] = []


def record_positive_control(observed: dict[str, Any]) -> None:
    _STATE["positive_control"] = observed


def _at_exit() -> None:
    _STATE["modules_at_exit"] = sorted(
        name
        for name in sys.modules
        if name.startswith("mktkb.providers") or name in {
            "mktkb.evaluation.p2_hard_evidence",
            "mktkb.evaluation.p2_evidence_capture",
            "mktkb.evaluation.p2_evidence_io",
            "httpx",
            "http.client",
        }
    )
    out = os.environ.get("C1P2_GUARD_OUT")
    if not out:
        return
    try:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(_STATE, fh, ensure_ascii=False, indent=1)
    except Exception:  # noqa: BLE001
        traceback.print_exc()


install()
atexit.register(_at_exit)
