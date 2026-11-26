"""零调用正对照：5 条出站路径必须全部被 axes-v2 独立守卫拦截（不经本机代理）。"""
from __future__ import annotations

import json
import os
import socket
import urllib.request
from pathlib import Path

import netguard_axesv2 as guard

HERE = Path(__file__).resolve().parent
OUT = HERE / "netguard-positive-control.json"
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

try:
    import requests

    _attempt(
        "requests_trust_env_false",
        lambda: requests.get("http://example.com", timeout=1, proxies={}),
    )
except ImportError:  # pragma: no cover
    results["requests_trust_env_false"] = "SKIPPED_NO_REQUESTS"

proxy_left = [name for name in guard.PROXY_NAMES if name in os.environ]
attempted = {k: v for k, v in results.items() if not v.startswith("SKIPPED_")}
skipped = sorted(k for k, v in results.items() if v.startswith("SKIPPED_"))
payload = {
    "schema_version": "p2-h2v3-axes-v2-netguard-positive-control/v0.1",
    "guard_schema_version": guard.SCHEMA_VERSION,
    "proxy_env_removed_at_import": guard.REMOVED,
    "proxy_env_left": proxy_left,
    "urllib_getproxies": urllib.request.getproxies(),
    "results": results,
    "skipped": skipped,
    "attempted_count": len(attempted),
    "all_blocked": all(
        value.startswith(("OSError", "URLError", "ConnectError", "HTTPError", "NewConnectionError"))
        for value in attempted.values()
    ),
    "external_count": len(guard.EXTERNAL),
    "loopback_calls": guard.LOOPBACK,
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=1))
