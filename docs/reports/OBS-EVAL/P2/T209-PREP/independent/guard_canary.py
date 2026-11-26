"""负向 canary（预期 pytest 失败，用于证明 netguard 真的拦截外部连接）。

本文件不在 backend/tests 下，不参与开发测试收集。单独运行：

    .venv\\Scripts\\python.exe -m pytest independent/guard_canary.py -q -p no:cacheprovider

预期 exit=1，teardown 报「检测到真实外部出站尝试」。这说明
``t09_network_guard`` 不是空 fixture：若某测试真的外连，它会让该测试失败。
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[6]
_TESTS = _ROOT / "backend" / "tests"
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401


def test_guard_blocks_external_and_fails_teardown(t09_network_guard) -> None:
    try:
        socket.create_connection(("example.com", 80))
    except RuntimeError:
        pass
