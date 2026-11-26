"""诊断壳：只回显异常类型名与「固定码形状」的 message，绝不回显其它正文。"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
import traceback

CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE.parent / "recompute_axes_fullverify_v2.py"


def main() -> int:
    spec = importlib.util.spec_from_file_location("_dbg_recompute", TARGET)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_dbg_recompute"] = module
    spec.loader.exec_module(module)
    argv = sys.argv[1:]
    try:
        return module.run(argv)
    except BaseException as exc:  # noqa: BLE001 - 诊断用
        first = exc.args[0] if exc.args else ""
        code = first if isinstance(first, str) and CODE.fullmatch(first) else "<noncode>"
        print("TYPE=", type(exc).__name__, "CODE=", code)
        # 只打印栈帧的「文件名:行号:函数名」，不打印源码行内容。
        for frame in traceback.extract_tb(exc.__traceback__):
            print("TB=", pathlib.Path(frame.filename).name, frame.lineno, frame.name)
        return 9


if __name__ == "__main__":
    raise SystemExit(main())
