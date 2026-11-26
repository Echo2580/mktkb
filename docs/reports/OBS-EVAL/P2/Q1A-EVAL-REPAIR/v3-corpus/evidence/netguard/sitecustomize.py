"""v3 语料会话：由 PYTHONPATH 注入的出站守卫启停（进程级）。"""

from __future__ import annotations

import atexit

from v3corpus_netguard import dump, install

install()
atexit.register(dump)
