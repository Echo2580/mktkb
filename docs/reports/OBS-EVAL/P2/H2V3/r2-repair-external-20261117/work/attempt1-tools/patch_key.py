"""一次性小工具：把 r2_recompute_axes.py 的 KEY_PATH 指向 attempt1 的 ev.key，产出本地变体。

只改一行常量；判定逻辑零改动。产物仅供 attempt1 证据重算使用，不替换原工具。
"""
from __future__ import annotations

import pathlib

WORK = pathlib.Path(__file__).resolve().parent.parent
SRC = WORK / "r2_recompute_axes.py"
OUT_DIR = WORK / "attempt1-tools"
OUT = OUT_DIR / "r2_recompute_axes_attempt1.py"
KEY = pathlib.Path("D:/mktkb-p2-h2v3-r2-20261117/attempt1/ev.key")


def main() -> int:
    lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
    newline = 'KEY_PATH = pathlib.Path(r"' + str(KEY).replace("/", "\\") + '")\n'
    hits = 0
    for index, line in enumerate(lines):
        if line.startswith("KEY_PATH = pathlib.Path("):
            lines[index] = newline
            hits += 1
    if hits != 1:
        raise SystemExit("anchor_count_invalid: " + str(hits))
    OUT_DIR.mkdir(exist_ok=True)
    OUT.write_text("".join(lines), encoding="utf-8")
    print("written", OUT, OUT.stat().st_size)
    print("line", newline.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
