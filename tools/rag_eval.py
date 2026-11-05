"""P0 评测 CLI 薄包装（设计 §8.5；计划 Task 7）。

用法（仓库根目录，零真实调用）：

    .\\.venv\\Scripts\\python.exe -B tools\\rag_eval.py --help
    .\\.venv\\Scripts\\python.exe -B tools\\rag_eval.py run --suite b0 --mode local --out var\\eval\\runs\\p0-b0

所有实现都在 ``mktkb.evaluation.cli``；本文件只补 ``backend/src`` 到 ``sys.path`` 后转调。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mktkb.evaluation.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
