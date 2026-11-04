"""真实外部连接闸门：把"本轮 0 次真实模型/OCR 调用"变成可失败的机器断言。

做法：
1. 拦截 ``socket.socket.connect/connect_ex``、``socket.create_connection``、``socket.getaddrinfo``
   与 ``httpx.HTTPTransport.handle_request`` / ``AsyncHTTPTransport``；
2. **回环地址除外**：Windows 上 asyncio 的 self-pipe 用 ``socket.socketpair()`` 模拟（内部真的
   连 127.0.0.1），拦掉它会直接破坏 TestClient 的事件循环，属工具限制而非真实调用；
   回环尝试单独记账，不计入外部调用；
3. 用例结束时若出现任何**外部**尝试即 fail——"没有调用"不是口头声明，而是每次运行都被验证。

ASGI 传输（``fastapi.testclient``）本身不经过网络，因此本地链路不受影响；
真实 DeepSeek/腾讯云 OCR 的目标都是外部域名（api.deepseek.com / ocr.tencentcloudapi.com）。
"""

from __future__ import annotations

import socket
import threading

import httpx
import pytest

BLOCKED_MESSAGE = "T09-D1 网络闸门：本轮禁止真实外部调用（0 次），已拦截出站连接"
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


class NetworkBlocked(RuntimeError):
    """出站连接被闸门拦截。"""


def is_loopback(address) -> bool:
    """判断地址是否为本地回环/本机（socketpair 模拟、AF_UNIX 路径都算本地）。"""
    if isinstance(address, str):
        return address.startswith("\\\\.\\pipe\\") or address.startswith("/") or "localhost" in address
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("utf-8", "replace")
        if not isinstance(host, str):
            return False
        return host in LOOPBACK_HOSTS or host.startswith("127.")
    return False


class NetworkAttempts:
    """线程安全的出站尝试记录：``external`` 为真实外部目标，``local`` 为回环。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.external: list[str] = []
        self.local: list[str] = []

    def add(self, label: str, address=None) -> None:
        with self._lock:
            if address is not None and is_loopback(address):
                self.local.append(label)
            else:
                self.external.append(label)

    def snapshot(self) -> dict:
        with self._lock:
            return {"external": list(self.external), "local": list(self.local)}


@pytest.fixture
def t09_network_guard(monkeypatch):
    """各 T09 测试模块通过 ``pytestmark = pytest.mark.usefixtures("t09_network_guard")`` 启用。"""
    attempts = NetworkAttempts()

    real_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):  # noqa: ANN001
        if is_loopback(address):
            attempts.add(f"socket.connect {address!r}", address)
            return real_connect(self, address, *args, **kwargs)
        attempts.add(f"socket.connect {address!r}", address)
        raise NetworkBlocked(f"{BLOCKED_MESSAGE}: connect {address!r}")

    def guarded_connect_ex(self, address, *args, **kwargs):  # noqa: ANN001
        if is_loopback(address):
            attempts.add(f"socket.connect_ex {address!r}", address)
            raise NetworkBlocked(f"{BLOCKED_MESSAGE}: connect_ex {address!r}")
        attempts.add(f"socket.connect_ex {address!r}", address)
        raise NetworkBlocked(f"{BLOCKED_MESSAGE}: connect_ex {address!r}")

    real_create_connection = socket.create_connection

    def guarded_create_connection(address, *args, **kwargs):  # noqa: ANN001
        if is_loopback(address):
            attempts.add(f"socket.create_connection {address!r}", address)
            return real_create_connection(address, *args, **kwargs)
        attempts.add(f"socket.create_connection {address!r}", address)
        raise NetworkBlocked(f"{BLOCKED_MESSAGE}: create_connection {address!r}")

    real_getaddrinfo = socket.getaddrinfo

    def guarded_handle_request(self, request):  # noqa: ANN001
        attempts.add(f"httpx.HTTPTransport {request.url}", (str(request.url.host),))
        raise NetworkBlocked(f"{BLOCKED_MESSAGE}: HTTP {request.url}")

    async def guarded_handle_async_request(self, request):  # noqa: ANN001
        attempts.add(f"httpx.AsyncHTTPTransport {request.url}", (str(request.url.host),))
        raise NetworkBlocked(f"{BLOCKED_MESSAGE}: HTTP {request.url}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect, raising=True)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex, raising=True)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection, raising=True)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded_handle_request, raising=True)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", guarded_handle_async_request, raising=True
    )
    if hasattr(socket, "getaddrinfo"):
        # 只拦外部主机解析；本地名放行，避免破坏事件循环初始化
        def guarded_getaddrinfo_local(host, *args, **kwargs):  # noqa: ANN001
            if is_loopback(host):
                attempts.add(f"socket.getaddrinfo {host!r}", (host if isinstance(host, str) else "",))
                return real_getaddrinfo(host, *args, **kwargs)
            attempts.add(f"socket.getaddrinfo {host!r}", (host if isinstance(host, str) else "",))
            raise NetworkBlocked(f"{BLOCKED_MESSAGE}: getaddrinfo {host!r}")

        monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo_local, raising=True)

    yield attempts

    snapshot = attempts.snapshot()
    assert snapshot["external"] == [], f"检测到真实外部出站尝试（本轮应为 0）：{snapshot['external']}"
