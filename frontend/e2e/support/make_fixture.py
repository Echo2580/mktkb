"""T08 浏览器测试专用：生成一个 30 行的分页检查用表格（虚构数据）。

只写入 frontend/.e2e-data/uploads 下的测试文件，不修改 fixtures 或项目语料。
"""

from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook


def main() -> int:
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "分页检查"
    sheet.append(["标识", "门店", "物品", "位置"])
    for index in range(1, 31):
        sheet.append([f"T{index:02d}", "城东店", f"测试物品{index:02d}", f"T区{index}号柜"])
    workbook.save(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
