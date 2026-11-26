"""Minimal outbound-call guard for the p1-impl zero-call probe.

Patches socket / http.client / httpx entry points, records every attempt, and
raises a private exception. `assert_clean()` fails if any attempt was recorded.
"""

from __future__ import annotations

import http.client
import socket
from typing import Any


class NetworkBlocked(RuntimeError):
    pass


class NetGuard:
    def __init__(self) -> None:
        self.events: list[str] = []
        self._saved: list[tuple[Any, str, Any]] = []

    def _patch(self, obj: Any, name: str, label: str) -> None:
        original = getattr(obj, name)
        self._saved.append((obj, name, original))

        def blocked(*args: Any, **kwargs: Any) -> Any:
            self.events.append(label)
            raise NetworkBlocked(label)

        setattr(obj, name, blocked)

    def __enter__(self) -> "NetGuard":
        self._patch(socket.socket, "connect", "socket.connect")
        self._patch(socket.socket, "connect_ex", "socket.connect_ex")
        self._patch(socket, "create_connection", "socket.create_connection")
        self._patch(socket, "getaddrinfo", "socket.getaddrinfo")
        self._patch(socket, "gethostbyname", "socket.gethostbyname")
        self._patch(http.client.HTTPConnection, "connect", "http.client.connect")
        try:
            import httpx

            self._patch(httpx.HTTPTransport, "handle_request", "httpx.handle_request")
        except Exception:  # noqa: BLE001 - optional dependency
            pass
        return self

    def __exit__(self, *args: Any) -> None:
        for obj, name, original in reversed(self._saved):
            setattr(obj, name, original)
        self._saved.clear()

    def clear(self) -> None:
        self.events.clear()

    def assert_clean(self) -> None:
        if self.events:
            raise AssertionError(f"outbound attempts: {self.events}")
