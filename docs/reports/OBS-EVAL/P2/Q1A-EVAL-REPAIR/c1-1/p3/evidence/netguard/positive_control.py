"""C1-P3 证据：出站守卫正对照（证明守卫真的会拦截，而不是“没调用所以为 0”）。

在守卫已注入的进程里尝试一次外部连接与一次外部 DNS；两者都必须被拦截。
结果写入守卫状态（`C1P3_GUARD_OUT`），本脚本正常退出（exit 0）。
"""

from __future__ import annotations

import json
import socket
import sys

OUTCOME = {"connect_blocked": False, "dns_blocked": False, "errors": []}


def main() -> int:
    try:
        socket.create_connection(("203.0.113.1", 9), timeout=0.5)
    except OSError as exc:
        OUTCOME["connect_blocked"] = "c1p3-netguard" in str(exc)
        OUTCOME["errors"].append(type(exc).__name__)
    try:
        socket.getaddrinfo("example.invalid", 443)
    except OSError as exc:
        OUTCOME["dns_blocked"] = "c1p3-netguard" in str(exc)
        OUTCOME["errors"].append(type(exc).__name__)
    try:
        from c1p3_netguard import record_positive_control

        record_positive_control(dict(OUTCOME))
    except Exception:  # noqa: BLE001
        pass
    print(json.dumps(OUTCOME, ensure_ascii=False))
    return 0 if OUTCOME["connect_blocked"] and OUTCOME["dns_blocked"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
