"""探针 15b：netguard 负向控制——故意不清空 external 记账，teardown 必须报错。

本文件刻意不以 `test_` 开头：正常运行 `pytest` 目录不会被收集；只由
`15-run-netguard-controls.py` 显式指定路径运行，期望 exit 1 + teardown 断言消息。
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

from acceptance.support.netguard import NetworkBlocked, t09_network_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("t09_network_guard")


def test_leaves_external_attempt_uncleared(t09_network_guard) -> None:  # noqa: ANN001
    try:
        socket.create_connection(("203.0.113.9", 80), timeout=1)
    except NetworkBlocked:
        pass
    assert t09_network_guard.snapshot()["external"] != []
    # 故意不清空：teardown 断言应失败
