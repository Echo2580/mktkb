"""C1-P4 进程级出站守卫（sitecustomize 注入）。

只证明一件事：**本进程没有发生任何外部连接/DNS**。
- 非回环 socket connect/connect_ex/create_connection/getaddrinfo → 记录并抛 OSError；
- 回环/本机地址放行（asyncio self-pipe、TestClient 的工具需求，不记为出站）；
- http.client.HTTPConnection.connect 与 httpx 传输层同样拦截；
- 计数只在内存，退出时由 sitecustomize 落盘到 ``C1P5_GUARD_OUT``。

守卫自身不做任何网络访问；缺少 httpx 时不补丁（测试依赖存在时再补）。
"""

from __future__ import annotations

import json
import os
import socket
import sys
from typing import Any

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}

_STATE: dict[str, Any] = {
    "socket_connect_external": 0,
    "socket_connect_ex": 0,
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
}


def _is_loopback(address: Any) -> bool:
    if isinstance(address, str):
        text = address
        return text in _LOOPBACK or text.startswith("127.")
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
    print(f"[c1p5-netguard] BLOCKED {kind}: {detail}", file=sys.stderr)


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
        raise OSError("c1p5-netguard blocked socket.connect")

    def guarded_connect_ex(self, address):  # noqa: ANN001
        if _is_loopback(address):
            _STATE["loopback_connects"] = int(_STATE["loopback_connects"]) + 1
            return original_connect_ex(self, address)
        _note("socket_connect_ex", repr(address))
        raise OSError("c1p5-netguard blocked socket.connect_ex")

    def guarded_create_connection(address, *args, **kwargs):  # noqa: ANN001
        if _is_loopback(address):
            _STATE["loopback_connects"] = int(_STATE["loopback_connects"]) + 1
            return original_create_connection(address, *args, **kwargs)
        _note("create_connection_external", repr(address))
        raise OSError("c1p5-netguard blocked create_connection")

    def guarded_getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
        if _is_loopback(host):
            return original_getaddrinfo(host, *args, **kwargs)
        _note("dns_getaddrinfo_external", str(host))
        raise OSError("c1p5-netguard blocked getaddrinfo")

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
            raise OSError("c1p5-netguard blocked http.client connect")

        http_client.HTTPConnection.connect = guarded_http_connect  # type: ignore[assignment]
    except Exception:  # noqa: BLE001 - 守卫不因可选模块缺失而失败
        pass

    def patch_httpx() -> None:
        module = sys.modules.get("httpx")
        if module is None or _STATE["httpx_patched"]:
            return
        try:
            transport = module.HTTPTransport
            async_transport = module.AsyncHTTPTransport

            def guarded_handle(self, request):  # noqa: ANN001
                url = getattr(request, "url", request)
                host = getattr(getattr(request, "url", None), "host", "")
                if _is_loopback(host):
                    return _ORIGINAL_HTTPX_HANDLE(self, request)
                _note("httpx_transport_external", str(url))
                raise OSError("c1p5-netguard blocked httpx transport")

            _ORIGINAL_HTTPX_HANDLE = transport.handle_request
            transport.handle_request = guarded_handle  # type: ignore[assignment]

            async def guarded_async(self, request):  # noqa: ANN001
                url = getattr(request, "url", request)
                host = getattr(getattr(request, "url", None), "host", "")
                if _is_loopback(host):
                    return await _ORIGINAL_HTTPX_ASYNC(self, request)
                _note("httpx_transport_external", str(url))
                raise OSError("c1p5-netguard blocked httpx async transport")

            _ORIGINAL_HTTPX_ASYNC = async_transport.handle_async_request
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
    out = os.environ.get("C1P5_GUARD_OUT")
    if not out:
        return
    payload = snapshot()
    payload["modules_at_exit"] = sorted(
        name
        for name in sys.modules
        if name.startswith("mktkb.providers")
        or name
        in {
            "mktkb.evaluation.p2_evidence_capture",
            "mktkb.evaluation.p2_evidence_io",
            "mktkb.evaluation.p2_evidence_snapshot_v03",
            "mktkb.evaluation.p2_evidence_rescore",
            "mktkb.evaluation.p2_evidence_rescore_axes",
            "mktkb.evaluation.p2_evidence_axes_adapter_v2",
            "httpx",
            "http.client",
        }
    )
    try:
        with open(out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
    except Exception:  # noqa: BLE001 - 守卫落盘失败不改测试结论
        pass
