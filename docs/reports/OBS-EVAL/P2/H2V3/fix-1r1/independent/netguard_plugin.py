"""独立验收 zero-call 守卫（自建，不复用开发/上一轮插件代码）。

口径：
- 导入即删除全部代理环境变量（大小写不敏感），正对照运行时不经本机代理；
- 接管 socket.connect / connect_ex / create_connection / getaddrinfo：
  回环（127.0.0.1/::1/localhost）放行并计数，非回环一律拦截并计数；
- `pytest_configure` 先跑 4 个正对照：DNS、直连、urllib（ProxyHandler({})）、
  httpx（trust_env=False），必须全部被拦；
- `pytest_sessionfinish` 写 JSON：正对照、会话内外站尝试、回环计数、pytest 计数。

只证明本进程没有外部出站；不声称覆盖外部进程或其他会话。
"""
from __future__ import annotations

import json
import os
import socket
import urllib.request

EXTERNAL: list[dict[str, str]] = []
PROXY: list[dict[str, str]] = []
LOOPBACK: list[dict[str, str]] = []
CONTROLS: list[dict[str, object]] = []
COUNTS = {"collected": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 0}

_ORIG_CONNECT = socket.socket.connect
_ORIG_CONNECT_EX = socket.socket.connect_ex
_ORIG_CREATE_CONNECTION = socket.create_connection
_ORIG_GETADDRINFO = socket.getaddrinfo

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}
_LOCAL_PROXY_PORT = 7897  # 本机注册表代理；单独拦截，证明没有任何流量经过它


def _strip_proxy_env() -> list[str]:
    removed: list[str] = []
    for key in list(os.environ):
        lowered = key.lower()
        if lowered.endswith("_proxy") or lowered in {
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
        }:
            os.environ.pop(key, None)
            removed.append(key)
    return removed


REMOVED_ENV = _strip_proxy_env()


def _is_loopback(address: object) -> bool:
    if isinstance(address, (str, bytes)):
        return True
    if isinstance(address, tuple) and address:
        host = str(address[0]).strip().lower()
        return host in _LOOPBACK_HOSTS or host.startswith("127.")
    return False


def _is_local_proxy(address: object) -> bool:
    if isinstance(address, tuple) and len(address) >= 2:
        host = str(address[0]).strip().lower()
        try:
            port = int(address[1])
        except (TypeError, ValueError):
            return False
        return (host in _LOOPBACK_HOSTS or host.startswith("127.")) and port == _LOCAL_PROXY_PORT
    return False


def _deny_proxy(kind: str, detail: object) -> None:
    PROXY.append({"kind": kind, "detail": str(detail)[:200]})
    raise OSError(f"independent netguard: local proxy {kind} blocked")


def _deny(kind: str, detail: object) -> None:
    EXTERNAL.append({"kind": kind, "detail": str(detail)[:200]})
    raise OSError(f"independent netguard: {kind} blocked")


def _install() -> None:
    def connect(self, address):  # noqa: ANN001
        if _is_local_proxy(address):
            _deny_proxy("socket.connect", address)
        if _is_loopback(address):
            LOOPBACK.append({"kind": "socket.connect", "detail": str(address)[:120]})
            return _ORIG_CONNECT(self, address)
        _deny("socket.connect", address)

    def connect_ex(self, address):  # noqa: ANN001
        if _is_local_proxy(address):
            _deny_proxy("socket.connect_ex", address)
        if _is_loopback(address):
            LOOPBACK.append({"kind": "socket.connect_ex", "detail": str(address)[:120]})
            return _ORIG_CONNECT_EX(self, address)
        _deny("socket.connect_ex", address)

    def create_connection(address, *args, **kwargs):  # noqa: ANN002, ANN003
        if _is_local_proxy(address):
            _deny_proxy("socket.create_connection", address)
        if _is_loopback(address):
            LOOPBACK.append({"kind": "socket.create_connection", "detail": str(address)[:120]})
            return _ORIG_CREATE_CONNECTION(address, *args, **kwargs)
        _deny("socket.create_connection", address)

    def getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if _is_local_proxy((host, port)):
            _deny_proxy("socket.getaddrinfo", (host, port))
        if _is_loopback((host, port)):
            LOOPBACK.append({"kind": "socket.getaddrinfo", "detail": f"{host}:{port}"})
            return _ORIG_GETADDRINFO(host, port, *args, **kwargs)
        _deny("socket.getaddrinfo", (host, port))

    socket.socket.connect = connect  # type: ignore[assignment]
    socket.socket.connect_ex = connect_ex  # type: ignore[assignment]
    socket.create_connection = create_connection  # type: ignore[assignment]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]


_install()


def _control(name: str, fn) -> dict[str, object]:  # noqa: ANN001
    before = len(EXTERNAL)
    before_proxy = len(PROXY)
    blocked = False
    error = ""
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001 - 正对照只要“出不去”
        blocked = True
        error = f"{type(exc).__name__}: {exc}"
    return {
        "probe": name,
        "blocked": blocked,
        "attempts": len(EXTERNAL) - before,
        "proxy_attempts": len(PROXY) - before_proxy,
        "error": error[:160],
    }


def pytest_configure(config) -> None:  # noqa: ANN001
    import httpx

    CONTROLS.extend(
        [
            _control("dns_getaddrinfo", lambda: socket.getaddrinfo("example.invalid", 80)),
            _control(
                "direct_tcp_192_0_2_1",
                lambda: socket.create_connection(("192.0.2.1", 80), timeout=0.2),
            ),
            _control(
                "urllib_proxyhandler_empty",
                lambda: urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                    "http://example.invalid/", timeout=0.2
                ),
            ),
            _control(
                "httpx_trust_env_false",
                lambda: httpx.Client(trust_env=False, timeout=0.2).get(
                    "http://example.invalid/"
                ),
            ),
            _control(
                "local_proxy_127_0_0_1_7897",
                lambda: socket.create_connection(("127.0.0.1", 7897), timeout=0.2),
            ),
        ]
    )


def pytest_collection_finish(session) -> None:  # noqa: ANN001
    COUNTS["collected"] = len(session.items)


def pytest_runtest_logreport(report) -> None:  # noqa: ANN001
    if report.when != "call":
        if report.failed and report.when in {"setup", "teardown"}:
            COUNTS["error"] += 1
        return
    if report.passed:
        COUNTS["passed"] += 1
    elif report.failed:
        COUNTS["failed"] += 1
    elif report.skipped:
        COUNTS["skipped"] += 1


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001
    path = os.environ.get("INDEPENDENT_NETGUARD_OUT")
    if not path:
        return
    controls_attempts = sum(int(item["attempts"]) for item in CONTROLS)
    try:
        proxies_after = urllib.request.getproxies()
    except BaseException:  # noqa: BLE001
        proxies_after = {}
    payload = {
        "proxy_env_removed": sorted(REMOVED_ENV),
        "proxy_registry_after_env_removal": proxies_after,
        "guard": [
            "socket.connect",
            "socket.connect_ex",
            "socket.create_connection",
            "socket.getaddrinfo",
        ],
        "loopback_policy": "allowed_and_counted_except_local_proxy_port_7897",
        "proxy_attempts_total": len(PROXY),
        "proxy_attempts": PROXY,
        "positive_controls": CONTROLS,
        "all_controls_blocked": all(bool(item["blocked"]) for item in CONTROLS),
        "external_attempts_total": len(EXTERNAL),
        "external_attempts_during_session": len(EXTERNAL) - controls_attempts,
        "external_attempts": EXTERNAL,
        "loopback_attempts_total": len(LOOPBACK),
        "loopback_targets_unique": sorted({item["detail"] for item in LOOPBACK}),
        "loopback_attempts_sample": LOOPBACK[:40],
        "counts": COUNTS,
        "exitstatus": int(exitstatus),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
