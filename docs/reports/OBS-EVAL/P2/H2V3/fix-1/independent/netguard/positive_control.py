"""零调用正对照：4 条出站路径必须全部被独立守卫拦截（不经本机代理）。"""
from __future__ import annotations

import json
import os
import socket
import urllib.request
from pathlib import Path

import netguard_independent as guard

OUT = Path(__file__).resolve().parent / "netguard-positive-control.json"
results: dict[str, str] = {}


def _attempt(name: str, fn) -> None:
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001 - 记录任何拦截/异常
        results[name] = f"{type(exc).__name__}: {exc}"
    else:
        results[name] = "NOT_BLOCKED"


_attempt("dns_getaddrinfo", lambda: socket.getaddrinfo("example.com", 80))
_attempt("direct_tcp", lambda: socket.create_connection(("1.1.1.1", 80), timeout=1))
_attempt(
    "urllib_proxyhandler_empty",
    lambda: urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        "http://example.com", timeout=1
    ),
)
try:
    import httpx

    _attempt(
        "httpx_trust_env_false",
        lambda: httpx.get("http://example.com", trust_env=False, timeout=1.0),
    )
except ImportError:  # pragma: no cover
    results["httpx_trust_env_false"] = "SKIPPED_NO_HTTPX"

proxy_left = [name for name in guard.PROXY_NAMES if name in os.environ]
payload = {
    "schema_version": "v3-fix1-independent-netguard-positive-control/v0.1",
    "proxy_env_removed_at_import": guard.REMOVED,
    "proxy_env_left": proxy_left,
    "urllib_getproxies": urllib.request.getproxies(),
    "results": results,
    "all_blocked": all(value.startswith(("OSError", "URLError", "ConnectError", "HTTPError"))
                       for value in results.values()),
    "external_count": len(guard.EXTERNAL),
    "loopback_calls": guard.LOOPBACK,
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
               encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=1))
