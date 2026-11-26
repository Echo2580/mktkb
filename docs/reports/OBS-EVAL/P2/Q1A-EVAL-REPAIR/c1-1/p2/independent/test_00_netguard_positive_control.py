"""C1-P2 独立验收：出站守卫正向控制。

必须先证明守卫会拦截并记账（socket 连接 / DNS / httpx transport 三条路径），
随后清零，再让被测套件在同一个进程里运行。
本测试由 14-netguard-run.py 与正式 88 项一起调用。
"""

from __future__ import annotations

import socket

import c1p2_netguard


def test_positive_control_outbound_is_blocked_and_recorded() -> None:
    before = c1p2_netguard.snapshot()

    # 1) TCP connect
    blocked_socket = False
    try:
        socket.create_connection(("203.0.113.1", 9), timeout=1)
    except OSError:
        blocked_socket = True
    assert blocked_socket, "outbound create_connection was not blocked by c1p2 netguard"

    # 2) DNS
    blocked_dns = False
    try:
        socket.getaddrinfo("example.invalid", 80)
    except OSError:
        blocked_dns = True
    assert blocked_dns, "DNS getaddrinfo was not blocked by c1p2 netguard"

    # 3) httpx transport（若 httpx 可用；测试依赖会 import 它）
    blocked_httpx = False
    try:
        import httpx

        request = httpx.Request("GET", "http://example.invalid/")
        try:
            httpx.HTTPTransport().handle_request(request)
        except OSError:
            blocked_httpx = True
    except ImportError:
        blocked_httpx = False
    assert blocked_httpx, "httpx transport was not blocked by c1p2 netguard"

    after = c1p2_netguard.snapshot()
    assert after["create_connection_attempts"] >= before["create_connection_attempts"] + 1
    assert after["dns_getaddrinfo_attempts"] >= before["dns_getaddrinfo_attempts"] + 1
    assert after["httpx_transport_attempts"] >= before["httpx_transport_attempts"] + 1
    assert after["blocked"] >= before["blocked"] + 3
    details = " ".join(str(item["detail"]) for item in after["details"])
    assert "203.0.113.1" in details
    assert "example.invalid" in details
    c1p2_netguard.record_positive_control(
        {
            "attempted": True,
            "blocked": True,
            "socket_blocked": blocked_socket,
            "dns_blocked": blocked_dns,
            "httpx_blocked": blocked_httpx,
            "blocked_total_after_attempt": after["blocked"],
            "details": after["details"][-5:],
        }
    )
    # 清零：正式套件运行期间如果再出现任何出站，就是独立证据。
    c1p2_netguard.reset()
