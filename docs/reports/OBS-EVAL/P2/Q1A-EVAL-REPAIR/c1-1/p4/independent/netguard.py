"""C1-P4 独立验收：自建零出站守卫（不复制开发/前轮守卫）。

拦截点：``socket.socket.connect`` / ``connect_ex``、``socket.create_connection``、
``socket.getaddrinfo`` / ``gethostbyname``、``http.client.HTTPConnection.connect``、
以及可选的 ``httpx`` 传输层。任何尝试先记账再抛错；``assert_clean()`` 在账未清时必报错。
"""

from __future__ import annotations

import http.client
import socket
from typing import Any


class NetworkBlocked(RuntimeError):
    pass


class NetGuard:
    def __init__(self) -> None:
        self.attempts: list[dict[str, Any]] = []
        self._originals: list[tuple[Any, str, Any]] = []

    # -- 记账 --------------------------------------------------------------- #
    def _deny(self, kind: str, target: Any) -> None:
        self.attempts.append({"kind": kind, "target": str(target)})
        raise NetworkBlocked(f"blocked network attempt: {kind} {target}")

    def _patch(self, obj: Any, name: str, replacement: Any) -> None:
        self._originals.append((obj, name, getattr(obj, name)))
        setattr(obj, name, replacement)

    # -- 安装/卸载 ----------------------------------------------------------- #
    def install(self) -> "NetGuard":
        guard = self

        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex

        def connect(sock: socket.socket, address: Any) -> Any:  # noqa: ANN401
            guard._deny("socket.connect", address)

        def connect_ex(sock: socket.socket, address: Any) -> Any:  # noqa: ANN401
            guard._deny("socket.connect_ex", address)

        self._patch(socket.socket, "connect", connect)
        self._patch(socket.socket, "connect_ex", connect_ex)

        def create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            guard._deny("socket.create_connection", address)

        self._patch(socket, "create_connection", create_connection)

        def getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            guard._deny("socket.getaddrinfo", (host, port))

        self._patch(socket, "getaddrinfo", getaddrinfo)

        def gethostbyname(host: Any) -> Any:  # noqa: ANN401
            guard._deny("socket.gethostbyname", host)

        self._patch(socket, "gethostbyname", gethostbyname)

        def http_connect(connection: http.client.HTTPConnection) -> None:
            guard._deny("http.client.connect", (connection.host, connection.port))

        self._patch(http.client.HTTPConnection, "connect", http_connect)

        try:
            import httpx  # noqa: PLC0415

            original_handle = httpx.HTTPTransport.handle_request

            def handle_request(transport: Any, request: Any) -> Any:  # noqa: ANN401
                guard._deny("httpx.HTTPTransport.handle_request", str(getattr(request, "url", request)))

            self._patch(httpx.HTTPTransport, "handle_request", handle_request)
        except Exception:  # noqa: BLE001 - httpx 未安装则不拦
            pass

        return self

    def uninstall(self) -> None:
        for obj, name, original in reversed(self._originals):
            setattr(obj, name, original)
        self._originals.clear()

    # -- 断言/清账 ----------------------------------------------------------- #
    def external(self) -> int:
        return len(self.attempts)

    def assert_clean(self) -> None:
        if self.attempts:
            raise AssertionError(f"network attempts recorded: {self.attempts}")

    def clear(self) -> None:
        self.attempts.clear()

    def kinds(self) -> list[str]:
        return sorted({row["kind"] for row in self.attempts})
