"""v3-fix-1 零调用证据：进程级网络守卫 + 四正对照（pytest 插件）。

用法：
    $env:NETGUARD_OUT = "<json 输出路径>"
    $env:PYTHONPATH = "<本目录>"
    python -m pytest -q -p netguard_plugin <测试文件...>

口径：
- 导入即删除全部代理环境变量（含大小写变体），正对照运行时**不经本机代理**；
- ``socket.connect / connect_ex / create_connection / getaddrinfo`` 全部接管：**回环放行并计数**
  （Windows 上 anyio 的阻塞 portal 用 socketpair 模拟，会走 127.0.0.1；这不是外部请求），
  非回环一律拦截并计数；
- 会话开始跑 DNS / 直连 / urllib（ProxyHandler({})）/ httpx 四个正对照，记录是否被拦；
- 会话内**外部**出站尝试计数应为 0；退出时写 JSON。
  守卫只证明本进程没有外部出站，不声称覆盖外部进程或其他会话。
"""

from __future__ import annotations

import json
import os
import socket
import urllib.request

EXTERNAL: list[dict[str, str]] = []
LOOPBACK: list[dict[str, str]] = []
CONTROLS: list[dict[str, object]] = []
COUNTS: dict[str, int] = {"collected": 0, "passed": 0, "failed": 0, "skipped": 0, "error": 0}

_ORIG_CONNECT = socket.socket.connect
_ORIG_CONNECT_EX = socket.socket.connect_ex
_ORIG_CREATE_CONNECTION = socket.create_connection
_ORIG_GETADDRINFO = socket.getaddrinfo

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


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
    if isinstance(address, (str, bytes)):  # AF_UNIX 路径
        return True
    if isinstance(address, tuple) and address:
        host = str(address[0]).strip().lower()
        return host in _LOOPBACK_HOSTS or host.startswith("127.")
    return False


def _deny(kind: str, detail: object) -> None:
    EXTERNAL.append({"kind": kind, "detail": str(detail)[:200]})
    raise OSError(f"netguard: {kind} blocked")


def _install() -> None:
    def connect(self, address):  # noqa: ANN001
        if _is_loopback(address):
            LOOPBACK.append({"kind": "socket.connect", "detail": str(address)[:120]})
            return _ORIG_CONNECT(self, address)
        _deny("socket.connect", address)

    def connect_ex(self, address):  # noqa: ANN001
        if _is_loopback(address):
            LOOPBACK.append({"kind": "socket.connect_ex", "detail": str(address)[:120]})
            return _ORIG_CONNECT_EX(self, address)
        _deny("socket.connect_ex", address)

    def create_connection(address, *args, **kwargs):  # noqa: ANN002, ANN003
        if _is_loopback(address):
            LOOPBACK.append({"kind": "socket.create_connection", "detail": str(address)[:120]})
            return _ORIG_CREATE_CONNECTION(address, *args, **kwargs)
        _deny("socket.create_connection", address)

    def getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
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
        "error": error[:160],
    }


def pytest_configure(config) -> None:  # noqa: ANN001
    import httpx

    CONTROLS.extend(
        [
            _control("dns", lambda: socket.getaddrinfo("example.invalid", 80)),
            _control("direct", lambda: socket.create_connection(("192.0.2.1", 80), timeout=0.2)),
            _control(
                "urllib",
                lambda: urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                    "http://example.invalid/", timeout=0.2
                ),
            ),
            _control(
                "httpx",
                lambda: httpx.Client(trust_env=False, timeout=0.2).get("http://example.invalid/"),
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
    path = os.environ.get("NETGUARD_OUT")
    if not path:
        return
    controls_attempts = sum(int(item["attempts"]) for item in CONTROLS)
    payload = {
        "proxy_env_removed": sorted(REMOVED_ENV),
        "guard": [
            "socket.connect",
            "socket.connect_ex",
            "socket.create_connection",
            "socket.getaddrinfo",
        ],
        "loopback_policy": "allowed_and_counted",
        "positive_controls": CONTROLS,
        "all_controls_blocked": all(bool(item["blocked"]) for item in CONTROLS),
        "external_attempts_total": len(EXTERNAL),
        "external_attempts_during_session": len(EXTERNAL) - controls_attempts,
        "external_attempts": EXTERNAL,
        "loopback_attempts": LOOPBACK,
        "loopback_attempts_total": len(LOOPBACK),
        "counts": COUNTS,
        "exitstatus": int(exitstatus),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
