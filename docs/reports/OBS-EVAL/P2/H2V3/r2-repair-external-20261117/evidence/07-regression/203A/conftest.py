"""T-R2-203A 探针的夹具引导：复用仓库既有 ``backend/tests/conftest.py``，不改它。

为什么需要本文件：本探针必须落在 ``evidence/07-regression/203A/``（本执行者唯一可写目录），
而 pytest 的 conftest 只沿**测试文件祖先目录**发现；因此这里按文件路径显式加载仓库
``backend/tests/conftest.py``，把它导出的 fixture 绑定到本模块命名空间 —— 等于本目录
自带一份 conftest，但**零复制、零改动**仓库夹具。

注意：本文件不属于产品代码，只在 203A 探针目录生效。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = next(
    parent for parent in _HERE.parents if (parent / "backend" / "src").is_dir()
)
_TESTS = _REPO / "backend" / "tests"
_SRC = _REPO / "backend" / "src"

for _p in (str(_TESTS), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_SPEC = importlib.util.spec_from_file_location(
    "_repo_tests_conftest_203a", _TESTS / "conftest.py"
)
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

# 只搬运 fixture/辅助符号；下划线开头的私有符号同样可用（显式取用，避免 import *）。
for _name, _value in vars(_MOD).items():
    if _name in {"__name__", "__file__", "__loader__", "__spec__", "__package__"}:
        continue
    globals().setdefault(_name, _value)

# ``t09_network_guard`` 不在 conftest 里，来自 ``acceptance/support/netguard.py``；
# 同样原样绑定到本模块（零复制），使本目录探针可用同一份出站闸门。
from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

import subprocess  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def no_subprocess(monkeypatch):
    """合成链路不得启动子进程（子进程会绕过进程内 socket 闸门）。"""

    calls: list[tuple] = []

    def _blocked(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append((args, tuple(sorted(kwargs))))
        raise AssertionError("203A 探针不得启动子进程")

    monkeypatch.setattr(subprocess, "Popen", _blocked)
    monkeypatch.setattr(subprocess, "run", _blocked)
    yield calls
    assert calls == [], calls


del _name, _value
