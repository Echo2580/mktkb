"""v3 语料会话：出站守卫正对照。

在守卫已注入的进程里尝试一次外部连接与一次外部 DNS；两者都必须被拦截。这证明
"零调用"不是"没装守卫所以计数为 0"。结果写入守卫状态，本脚本自身 exit 0。
"""

from __future__ import annotations

import json
import socket

OUTCOME = {"connect_blocked": False, "dns_blocked": False, "errors": []}


def main() -> int:
    try:
        socket.create_connection(("203.0.113.1", 9), timeout=0.5)
    except OSError as exc:
        OUTCOME["connect_blocked"] = "v3corpus-netguard" in str(exc)
        OUTCOME["errors"].append(type(exc).__name__)
    try:
        socket.getaddrinfo("example.invalid", 443)
    except OSError as exc:
        OUTCOME["dns_blocked"] = "v3corpus-netguard" in str(exc)
        OUTCOME["errors"].append(type(exc).__name__)
    try:
        from v3corpus_netguard import record_positive_control

        record_positive_control(dict(OUTCOME))
    except Exception:  # noqa: BLE001
        pass
    print(json.dumps(OUTCOME, ensure_ascii=False))
    return 0 if OUTCOME["connect_blocked"] and OUTCOME["dns_blocked"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
