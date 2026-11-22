"""T301 隔离测试 sys.path 引导（测试目录位于 backend/ 之外，避免依赖 rootdir 解析）。"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
T301_ROOT = HERE.parent
SCRIPTS = T301_ROOT / "scripts"
REPO_ROOT = T301_ROOT.parents[4]
BACKEND_SRC = REPO_ROOT / "backend" / "src"

for path in (str(SCRIPTS), str(BACKEND_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)
