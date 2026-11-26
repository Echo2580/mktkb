"""Q1a-1 独立验收探针 5：netguard 正向控制（证明闸门不是空壳）。

`t09_network_guard` 是开发测试使用的真实拦截器。本文件故意触发外部 socket /
getaddrinfo / httpx 尝试，证明：
  - 调用被 `NetworkBlocked` 拦截；
  - 闸门把目标记入 `external` 列表（随后清空，避免 teardown 把“故意触发”重复计数）。

运行（仓库根）：
  $env:PYTHONPATH="backend/src;backend/tests"
  .venv/Scripts/python.exe -m pytest <本文件> -q -p no:cacheprovider
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[7]
_TESTS_DIR = _REPO_ROOT / "backend" / "tests"
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401


def _clear(attempts) -> None:  # noqa: ANN001
    attempts.external.clear()
    attempts.local.clear()


def test_netguard_blocks_socket_create_connection_and_getaddrinfo(t09_network_guard) -> None:  # noqa: ANN001
    with pytest.raises(Exception) as first:
        socket.create_connection(("api.deepseek.com", 443), timeout=0.01)
    assert "网络闸门" in str(first.value), str(first.value)
    snapshot = t09_network_guard.snapshot()
    assert snapshot["external"], snapshot
    assert any("api.deepseek.com" in item for item in snapshot["external"]), snapshot

    with pytest.raises(Exception) as second:
        socket.getaddrinfo("ocr.tencentcloudapi.com", 443)
    assert "网络闸门" in str(second.value), str(second.value)
    assert any("ocr.tencentcloudapi.com" in item for item in t09_network_guard.snapshot()["external"])
    _clear(t09_network_guard)


def test_netguard_blocks_httpx_transport(t09_network_guard) -> None:  # noqa: ANN001
    # trust_env=False：绕过宿主代理环境变量，确保走到被拦截的 HTTPTransport。
    with httpx.Client(trust_env=False) as client:
        with pytest.raises(Exception) as caught:
            client.get("https://api.deepseek.com/v1/chat/completions", timeout=0.01)
    assert "网络闸门" in repr(caught.value) or "网络闸门" in str(caught.value), repr(caught.value)
    snapshot = t09_network_guard.snapshot()
    assert snapshot["external"], snapshot
    _clear(t09_network_guard)
