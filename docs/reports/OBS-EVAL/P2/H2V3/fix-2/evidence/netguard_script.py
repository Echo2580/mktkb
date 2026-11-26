"""零调用守卫（脚本版）：在**同一进程内**先装网络守卫与四正对照，再用 runpy 执行目标脚本。

用法：
    python netguard_script.py <receipt.json> <target.py> [target args...]

口径（与 fix-1r1/safety-fix 的 pytest 插件一致）：
- 导入即删除全部代理环境变量（含大小写变体）；正对照显式 ``ProxyHandler({})`` / ``trust_env=False``，
  **不经本机代理**；
- ``socket.connect / connect_ex / create_connection / getaddrinfo`` 全部接管：回环放行并计数，
  非回环一律拦截并计数；
- 回执记录：正对照 4/4 是否被拦、外部出站尝试总数与会话期（扣除正对照）计数、回环计数、退出码。
"""

from __future__ import annotations

import json
import os
import runpy
import socket
import sys
import urllib.request

EXTERNAL: list[dict[str, str]] = []
LOOPBACK: list[dict[str, object]] = []
CONTROLS: list[dict[str, object]] = []

_ORIG_CONNECT = socket.socket.connect
_ORIG_CONNECT_EX = socket.socket.connect_ex
_ORIG_CREATE_CONNECTION = socket.create_connection
_ORIG_GETADDRINFO = socket.getaddrinfo
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def _strip_proxy_env() -> list[str]:
    removed: list[str] = []
    for key in list(os.environ):
        if key.lower().endswith("_proxy") or key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}:
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


def _control(name: str, fn) -> dict[str, object]:  # noqa: ANN001
    before = len(EXTERNAL)
    blocked = False
    error = ""
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001
        blocked = True
        error = f"{type(exc).__name__}: {exc}"
    return {"probe": name, "blocked": blocked, "attempts": len(EXTERNAL) - before, "error": error[:160]}


def main(argv: list[str]) -> int:
    receipt_path, target = argv[0], argv[1]
    target_args = argv[2:]
    _install()
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
            _control("httpx", lambda: httpx.Client(trust_env=False, timeout=0.2).get("http://example.invalid/")),
        ]
    )
    control_attempts = sum(int(item["attempts"]) for item in CONTROLS)
    exit_code = 0
    sys.argv = [target, *target_args]
    try:
        runpy.run_path(target, run_name="__main__")
    except SystemExit as exc:  # noqa: PERF203
        exit_code = int(exc.code or 0)
    payload = {
        "target": target,
        "target_args": target_args,
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
        "external_attempts_during_session": len(EXTERNAL) - control_attempts,
        "external_attempts": EXTERNAL,
        "loopback_attempts_total": len(LOOPBACK),
        "exit_code": exit_code,
    }
    with open(receipt_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: payload[k] for k in ("all_controls_blocked", "external_attempts_during_session", "loopback_attempts_total", "exit_code")}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
