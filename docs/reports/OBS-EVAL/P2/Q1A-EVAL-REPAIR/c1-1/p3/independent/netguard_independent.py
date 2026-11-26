"""C1-P3 独立验收：自建进程级零出站守卫（不复用开发 netguard）。

用法：
    from netguard_independent import install, counters, assert_clean, snapshot
    install()
    ... 运行被验收代码 ...
    assert_clean()          # external 计数非 0 则抛错退出（负向控制的核心）

设计：
- 只拦“外部”目标；loopback（127.0.0.0/8、::1、localhost）放行并单独计数，
  因为产品装配/插件管道会用本地环回。
- 拦截点覆盖 socket.connect / connect_ex / create_connection / getaddrinfo、
  http.client.HTTPConnection.connect、httpx.HTTPTransport.handle_request。
- 所有被拦尝试都记入 ledger（kind + 目标）；`assert_clean(clear_first=False)`
  在 ledger 非空时抛错 —— 这就是“不清账应报错”。
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import threading
from typing import Any

_LOCK = threading.Lock()
_LEDGER: list[dict[str, str]] = []
_COUNTS: dict[str, int] = {}
_INSTALLED = False
_ALLOWED_HOSTS = {"localhost", "localhost.localdomain", "127.0.0.1", "::1", ""}


def _is_loopback_host(host: Any) -> bool:
    text = str(host or "").strip().lower()
    if text in _ALLOWED_HOSTS:
        return True
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    try:
        return ipaddress.ip_address(text.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _record(kind: str, detail: str, *, external: bool) -> None:
    with _LOCK:
        _COUNTS[kind] = _COUNTS.get(kind, 0) + 1
        if external:
            _LEDGER.append({"kind": kind, "detail": detail[:200]})


def counters() -> dict[str, int]:
    with _LOCK:
        return dict(sorted(_COUNTS.items()))


def ledger() -> list[dict[str, str]]:
    with _LOCK:
        return list(_LEDGER)


def snapshot() -> dict[str, Any]:
    counts = counters()
    external = sum(
        value for key, value in counts.items() if not key.startswith("loopback")
    )
    return {
        "counts": counts,
        "ledger": ledger(),
        "external_attempts": external,
        "installed": _INSTALLED,
    }


def reset() -> None:
    with _LOCK:
        _LEDGER.clear()
        _COUNTS.clear()


def assert_clean(*, allow_loopback: bool = True) -> None:
    """负向控制：只要 ledger 未被清空（曾发生外部尝试），就必须报错。"""
    data = snapshot()
    external = data["external_attempts"]
    if external:
        raise RuntimeError(
            f"external_attempts_nonzero:{external}:{data['ledger'][:3]}"
        )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    original_http_connect = http.client.HTTPConnection.connect

    def connect(self: socket.socket, address: Any) -> None:  # type: ignore[override]
        host = address[0] if isinstance(address, tuple) else address
        if _is_loopback_host(host):
            _record("loopback_connect", str(host), external=False)
            return original_connect(self, address)
        _record("socket_connect_external", str(address), external=True)
        raise OSError("blocked_by_independent_netguard:connect")

    def connect_ex(self: socket.socket, address: Any) -> int:  # type: ignore[override]
        host = address[0] if isinstance(address, tuple) else address
        if _is_loopback_host(host):
            _record("loopback_connect_ex", str(host), external=False)
            return original_connect_ex(self, address)
        _record("socket_connect_ex_external", str(address), external=True)
        return 111

    def create_connection(address: Any, *args: Any, **kwargs: Any):  # type: ignore[override]
        host = address[0] if isinstance(address, tuple) else address
        if _is_loopback_host(host):
            _record("loopback_create_connection", str(host), external=False)
            return original_create_connection(address, *args, **kwargs)
        _record("create_connection_external", str(address), external=True)
        raise OSError("blocked_by_independent_netguard:create_connection")

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any):  # type: ignore[override]
        if _is_loopback_host(host):
            _record("loopback_getaddrinfo", str(host), external=False)
            return original_getaddrinfo(host, *args, **kwargs)
        _record("dns_getaddrinfo_external", str(host), external=True)
        raise socket.gaierror(-2, "blocked_by_independent_netguard:dns")

    def http_connect(self: http.client.HTTPConnection) -> None:  # type: ignore[override]
        if _is_loopback_host(self.host):
            _record("loopback_http_connect", str(self.host), external=False)
            return original_http_connect(self)
        _record("http_client_external", f"{self.host}:{self.port}", external=True)
        raise OSError("blocked_by_independent_netguard:http")

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.create_connection = create_connection  # type: ignore[assignment]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    http.client.HTTPConnection.connect = http_connect  # type: ignore[method-assign]

    try:  # httpx 可选：只在已安装时加一层传输计数
        import httpx

        original_handle_sync = httpx.HTTPTransport.handle_request
        original_handle_async = httpx.AsyncHTTPTransport.handle_request

        def handle_sync(self, request):  # type: ignore[no-untyped-def]
            url = str(getattr(request, "url", ""))
            host = getattr(getattr(request, "url", None), "host", "")
            if not _is_loopback_host(host):
                _record("httpx_transport_external", url, external=True)
                raise OSError("blocked_by_independent_netguard:httpx")
            return original_handle_sync(self, request)

        async def handle_async(self, request):  # type: ignore[no-untyped-def]
            url = str(getattr(request, "url", ""))
            host = getattr(getattr(request, "url", None), "host", "")
            if not _is_loopback_host(host):
                _record("httpx_async_transport_external", url, external=True)
                raise OSError("blocked_by_independent_netguard:httpx")
            return await original_handle_async(self, request)

        httpx.HTTPTransport.handle_request = handle_sync  # type: ignore[method-assign]
        httpx.AsyncHTTPTransport.handle_request = handle_async  # type: ignore[method-assign]
    except Exception:  # noqa: BLE001 - httpx 不可用不影响 socket 层守卫
        pass
