"""C1-P5 netguard positive control: prove the process-level guard actually blocks egress.

Every attempt targets a public host and must raise before any packet leaves the host.
Counts are written by the guard to C1P5_GUARD_OUT on exit.
"""
from __future__ import annotations

import http.client
import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "netguard"))

from c1p5_netguard import dump, install, record_positive_control, snapshot  # noqa: E402

OUT = Path(__file__).resolve().parent
HOST = "example.com"


def attempt(name: str, fn) -> dict:
    try:
        fn()
    except OSError as exc:
        return {"attempt": name, "blocked": True, "error": type(exc).__name__}
    except Exception as exc:  # noqa: BLE001
        return {"attempt": name, "blocked": False, "error": type(exc).__name__}
    return {"attempt": name, "blocked": False, "error": None}


def main() -> int:
    install()
    attempts = [
        attempt("dns_getaddrinfo", lambda: socket.getaddrinfo(HOST, 80)),
        attempt("create_connection", lambda: socket.create_connection((HOST, 80), timeout=2)),
        attempt("socket_connect", lambda: socket.socket().connect((HOST, 80))),
        attempt("http_client_connect", lambda: http.client.HTTPConnection(HOST, 80, timeout=2).connect()),
    ]
    result = {
        "probe": "03-netguard-positive-control",
        "attempts": attempts,
        "all_blocked": all(item["blocked"] for item in attempts),
    }
    record_positive_control(result)
    payload = snapshot()
    payload["positive_control"] = result
    (OUT / "03-netguard-positive-control.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["all_blocked"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
