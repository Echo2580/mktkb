"""v3 语料生成会话的进程级出站守卫（sitecustomize 注入）。

只证明一件事：**本轮零真实调用进程没有发生任何外部连接/DNS**。
- 非回环 socket connect / connect_ex / create_connection / getaddrinfo → 计数并抛 OSError；
- 回环/本机地址放行（只计入 loopback_connects，不记为出站）；
- http.client.HTTPConnection.connect 与 httpx 传输层同样拦截（若已导入）；
- 计数与明细只在内存，退出时由 sitecustomize 落盘到 ``V3CORPUS_GUARD_OUT``。

守卫自身不做任何网络访问；不安装依赖、不读密钥。
"""

from __future__ import annotations

import atexit
import json
import os
import socket
import sys
from typing import Any

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}

_STATE: dict[str, Any] = {
    "socket_connect_external": 0,
    "socket_connect_ex_external": 0,
    "create_connection_external": 0,
    "dns_getaddrinfo_external": 0,
    "http_client_external": 0,
    "httpx_transport_external": 0,
    "loopback_connects": 0,
    "blocked": 0,
    "details": [],
    "positive_control": None,
    "installed": False,
    "httpx_patched": False,
    "guard_version": "v3corpus-netguard/v0.1",
}

_ORIGINAL_HTTPX_HANDLE = None
_ORIGINAL_HTTPX_ASYNC = None


def _is_loopback(address: Any) -> bool:
    if isinstance(address, str):
        return address in _LOOPBACK or address.startswith("127.")
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("utf-8", "replace")
        return isinstance(host, str) and (host in _LOOPBACK or host.startswith("127."))
    return False


def _note(kind: str, detail: str) -> None:
    _STATE[kind] = int(_STATE.get(kind, 0)) + 1
    _STATE["blocked"] = int(_STATE["blocked"]) + 1
    if len(_STATE["details"]) < 50:
        _STATE["details"].append({"kind": kind, "detail": detail})
    print(f"[v3corpus-netguard] BLOCKED {kind}: {detail}", file=sys.stderr)


def install() -> None:
    if _STATE["installed"]:
        return
    _STATE["installed"] = True
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address):  # noqa: ANN001
        if _is_loopback(address):
            _STATE["loopback_connects"] = int(_STATE["loopback_connects"]) + 1
            return original_connect(self, address)
        _note("socket_connect_external", repr(address))
        raise OSError("v3corpus-netguard blocked socket.connect")

    def guarded_connect_ex(self, address):  # noqa: ANN001
        if _is_loopback(address):
            _STATE["loopback_connects"] = int(_STATE["loopback_connects"]) + 1
            return original_connect_ex(self, address)
        _note("socket_connect_ex_external", repr(address))
        raise OSError("v3corpus-netguard blocked socket.connect_ex")

    def guarded_create_connection(address, *args, **kwargs):  # noqa: ANN001
        if _is_loopback(address):
            _STATE["loopback_connects"] = int(_STATE["loopback_connects"]) + 1
            return original_create_connection(address, *args, **kwargs)
        _note("create_connection_external", repr(address))
        raise OSError("v3corpus-netguard blocked create_connection")

    def guarded_getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
        if _is_loopback(host):
            return original_getaddrinfo(host, *args, **kwargs)
        _note("dns_getaddrinfo_external", str(host))
        raise OSError("v3corpus-netguard blocked getaddrinfo")

    socket.socket.connect = guarded_connect  # type: ignore[assignment]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[assignment]
    socket.create_connection = guarded_create_connection  # type: ignore[assignment]
    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]

    try:
        import http.client as http_client

        original_http_connect = http_client.HTTPConnection.connect

        def guarded_http_connect(self):  # noqa: ANN001
            if _is_loopback(self.host):
                return original_http_connect(self)
            _note("http_client_external", f"{self.host}:{self.port}")
            raise OSError("v3corpus-netguard blocked http.client connect")

        http_client.HTTPConnection.connect = guarded_http_connect  # type: ignore[assignment]
    except Exception:  # noqa: BLE001 - 守卫不因可选模块缺失而失败
        pass

    def patch_httpx() -> None:
        global _ORIGINAL_HTTPX_HANDLE, _ORIGINAL_HTTPX_ASYNC
        module = sys.modules.get("httpx")
        if module is None or _STATE["httpx_patched"]:
            return
        try:
            transport = module.HTTPTransport
            async_transport = module.AsyncHTTPTransport
            _ORIGINAL_HTTPX_HANDLE = transport.handle_request
            _ORIGINAL_HTTPX_ASYNC = async_transport.handle_async_request

            def guarded_handle(self, request):  # noqa: ANN001
                host = getattr(getattr(request, "url", None), "host", "")
                if _is_loopback(host):
                    return _ORIGINAL_HTTPX_HANDLE(self, request)
                _note("httpx_transport_external", str(getattr(request, "url", request)))
                raise OSError("v3corpus-netguard blocked httpx transport")

            transport.handle_request = guarded_handle  # type: ignore[assignment]

            async def guarded_async(self, request):  # noqa: ANN001
                host = getattr(getattr(request, "url", None), "host", "")
                if _is_loopback(host):
                    return await _ORIGINAL_HTTPX_ASYNC(self, request)
                _note("httpx_transport_external", str(getattr(request, "url", request)))
                raise OSError("v3corpus-netguard blocked httpx async transport")

            async_transport.handle_async_request = guarded_async  # type: ignore[assignment]
            _STATE["httpx_patched"] = True
        except Exception:  # noqa: BLE001
            pass

    patch_httpx()
    import builtins

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):  # noqa: ANN001
        module = original_import(name, *args, **kwargs)
        if name == "httpx" or name.startswith("httpx."):
            patch_httpx()
        return module

    builtins.__import__ = guarded_import  # type: ignore[assignment]


def snapshot() -> dict:
    return json.loads(json.dumps(_STATE))


def record_positive_control(observed: dict) -> None:
    _STATE["positive_control"] = observed


def dump() -> None:
    out = os.environ.get("V3CORPUS_GUARD_OUT")
    if not out:
        return
    payload = snapshot()
    payload["modules_at_exit"] = sorted(
        name
        for name in sys.modules
        if name in {"httpx", "http.client", "socket", "openpyxl", "sqlalchemy", "mktkb.retrieval.index", "mktkb.retrieval.tokenize"}
        or name.startswith("mktkb.providers")
    )
    payload["argv"] = sys.argv
    try:
        with open(out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
    except Exception:  # noqa: BLE001 - 守卫落盘失败不改变本轮结论，但会被 07 脚本检出缺失
        pass
