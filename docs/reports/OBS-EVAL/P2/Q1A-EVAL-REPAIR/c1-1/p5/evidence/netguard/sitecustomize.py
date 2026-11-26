"""C1-P5 evidence: process-level outbound guard start/stop (injected by PYTHONPATH)."""

from __future__ import annotations

import atexit

from c1p5_netguard import dump, install

install()
atexit.register(dump)