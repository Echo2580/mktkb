"""C1-P4 证据：由 PYTHONPATH 注入的出站守卫启停（进程级）。"""

from __future__ import annotations

import atexit

from c1p4_netguard import dump, install

install()
atexit.register(dump)
