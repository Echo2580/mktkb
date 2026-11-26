"""C1-P2 独立验收：sitecustomize 入口（自动 import）。

只要本目录在 PYTHONPATH 上，解释器启动时即安装出站守卫；
进程退出时把计数写到 C1P2_GUARD_OUT 指向的 JSON。
"""

from __future__ import annotations

import c1p2_netguard

c1p2_netguard.install()
