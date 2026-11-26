"""Q1a-1 独立验收探针 5b：netguard 负向控制（预期失败，证明 teardown 断言非空壳）。

本文件故意触发一次外部 socket 尝试且**不清空**记录。若 netguard 的 teardown 断言
真实生效，pytest 必须以非零退出并报告“检测到真实外部出站尝试”。
这不是开发测试失败，而是闸门有效性证据；运行结果见 05b-*.out.expected-fail.txt。

运行（仓库根，预期 exit 1）：
  $env:PYTHONPATH="backend/src;backend/tests"
  .venv/Scripts/python.exe -m pytest <本文件> -q -p no:cacheprovider
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[7]
_TESTS_DIR = _REPO_ROOT / "backend" / "tests"
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401


def test_deliberate_external_attempt_must_fail_teardown(t09_network_guard) -> None:  # noqa: ANN001
    with pytest.raises(Exception):
        socket.create_connection(("api.deepseek.com", 443), timeout=0.01)
    # 故意不清空 external：teardown 必须失败。
