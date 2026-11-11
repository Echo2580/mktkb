"""P2-T207-FIX-A：live 执行包装器 —— 显式 --env-file，由包装器自己读取并注入子进程环境。

为什么需要它（任务书 §3.1）：真实 provider 的凭据只允许经"显式给定的文件"进入**本次执行**，
不能被任何库偷偷从 .env 读出来。因此：

- 只接受显式 --env-file；**默认不读 .env**，并且显式指向名为 .env 的文件也会被拒绝；
- 只在文件里认白名单变量名（p2_live / 门控 / H2 的少数几个），其余名字一律 fail closed；
- 缺必需变量时只报**变量名**并以稳定码拒绝，绝不回显值；
- 注入只发生在子进程环境里（父进程不变），输出里只有变量名与子进程退出码；
- 不打印、不记录、不写盘任何凭据值（连 repr 都不打）。

用法（仓库根）：

    .venv/Scripts/python.exe -B -X utf8 tools/p2_live_execute.py ^
        --env-file '<工作区外>/p2-live.env' -- p2-run --plan ... --out ... --mode live ...

    # 只做读取/校验（不发请求、不构造适配器）
    .venv/Scripts/python.exe -B -X utf8 tools/p2_live_execute.py --env-file '...' --check-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = PROJECT_ROOT / "backend" / "src"
DEFAULT_CHILD_MODULE = "mktkb.evaluation.cli"

#: 只注入这些名字：p2_live 的必需变量 + 门控总上限 + H2 封存根/键。
P2_LIVE_ENV_NAMES: tuple[str, ...] = (
    "MKTKB_MODEL_API_KEY",
    "MKTKB_MODEL_BASE_URL",
    "MKTKB_MODEL_NAME",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
    "MKTKB_OCR_SECRET_ID",
    "MKTKB_OCR_SECRET_KEY",
    "MKTKB_OCR_REGION",
    "MKTKB_OCR_DISABLED",
)
GATE_ENV_NAMES: tuple[str, ...] = ("MKTKB_PROJECT_TOTAL_LIMIT_CNY",)
HOLDOUT_ENV_NAMES: tuple[str, ...] = ("MKTKB_P2_HOLDOUT_ROOT", "MKTKB_P2_HOLDOUT_KEY_FILE")
ALLOWED_ENV_NAMES: tuple[str, ...] = P2_LIVE_ENV_NAMES + GATE_ENV_NAMES + HOLDOUT_ENV_NAMES

#: 与 mktkb.evaluation.p2_live / 门控一致的最小必需集（缺任一即 fail closed）。
REQUIRED_ENV_NAMES: tuple[str, ...] = (
    "MKTKB_MODEL_API_KEY",
    "MKTKB_MODEL_BASE_URL",
    "MKTKB_MODEL_NAME",
    "DASHSCOPE_API_KEY",
    "MKTKB_OCR_SECRET_ID",
    "MKTKB_OCR_SECRET_KEY",
)

_LINE_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)$")


class EnvFileError(ValueError):
    """环境文件不可用：code + **只含变量名**的 detail（绝不带值）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = str(code)
        self.detail = str(detail)


@dataclass(frozen=True)
class EnvLoading:
    """一次读取的结果：只有变量名清单与来源文件名（值留在内存里，不进 repr）。"""

    path: Path
    names: tuple[str, ...]
    values: Mapping[str, str]

    def __repr__(self) -> str:  # pragma: no cover - 防御性：不打印值
        return f"EnvLoading(path={self.path.name!r}, names={list(self.names)!r}, values=<redacted>)"


def parse_env_text(raw: str, *, source: str) -> dict[str, str]:
    """解析 KEY=VALUE（支持 # 注释与空行）；未知/重复/空值一律拒绝。"""
    values: dict[str, str] = {}
    for number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _LINE_RE.match(line)
        if match is None:
            raise EnvFileError("env_line_invalid", f"{source}:{number}")
        key = match.group("key")
        value = match.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key not in ALLOWED_ENV_NAMES:
            raise EnvFileError("env_name_not_allowed", f"{source}:{number}:{key}")
        if not value:
            raise EnvFileError("env_value_empty", f"{key}")
        if key in values:
            raise EnvFileError("env_name_duplicated", f"{key}")
        values[key] = value
    return values


def load_env_file(path: Path | str) -> EnvLoading:
    """读显式给定的环境文件；名为 .env 的文件一律拒绝（默认不许从 .env 取凭据）。"""
    target = Path(path)
    if target.name == ".env" or target.name.startswith(".env."):
        raise EnvFileError("env_file_forbidden", target.name)
    if not target.is_file():
        raise EnvFileError("env_file_missing", target.name)
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise EnvFileError("env_file_unreadable", target.name) from None
    values = parse_env_text(raw, source=target.name)
    missing = [name for name in REQUIRED_ENV_NAMES if name not in values]
    if missing:
        raise EnvFileError("env_required_missing", ",".join(missing))
    return EnvLoading(path=target, names=tuple(sorted(values)), values=values)


def build_child_env(
    path: Path | str, *, base_env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """父环境去掉白名单同名项后只加上本次文件里的值（不让旧值混进来）。"""
    loaded = load_env_file(path)
    base = dict(os.environ if base_env is None else base_env)
    for name in ALLOWED_ENV_NAMES:
        base.pop(name, None)
    base.update(loaded.values)
    backend_src = str(BACKEND_SRC)
    path_parts = [part for part in str(base.get("PYTHONPATH") or "").split(os.pathsep) if part]
    if backend_src not in path_parts:
        path_parts.insert(0, backend_src)
    base["PYTHONPATH"] = os.pathsep.join(path_parts)
    # 子进程不读 .env（阻断"顺手从工作区 .env 取凭据"的路径）。
    base["MKTKB_NO_DOTENV"] = "1"
    return base


def run_command(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path | str | None = None,
) -> subprocess.CompletedProcess:
    """跑子进程并**捕获**输出（调用方决定怎么显示；本模块从不打印 env 值）。"""
    return subprocess.run(
        list(command),
        cwd=str(cwd or PROJECT_ROOT),
        env=dict(env),
        capture_output=True,
        text=True,
    )


def run_cli(
    env_file: Path | str,
    argv: Sequence[str],
    *,
    python: str | None = None,
    module: str = DEFAULT_CHILD_MODULE,
    base_env: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    """注入环境后运行 p2 CLI；返回 (exit_code, stdout, stderr)。"""
    env = build_child_env(env_file, base_env=base_env)
    command = [python or sys.executable, "-B", "-X", "utf8", "-m", module, *argv]
    completed = run_command(command, env=env)
    return int(completed.returncode), completed.stdout, completed.stderr


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="p2_live_execute",
        description="显式 --env-file -> 注入子进程环境 -> 运行 p2 CLI（零隐式读取、零值回显）",
    )
    parser.add_argument("--env-file", required=True, help="显式环境文件（不得是 .env）")
    parser.add_argument("--python", default=None, help="子进程解释器（默认当前解释器）")
    parser.add_argument("--module", default=DEFAULT_CHILD_MODULE, help="子进程模块（默认 p2 CLI）")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只读取/校验环境文件（不发请求、不构造适配器、不运行子进程）",
    )
    parser.add_argument(
        "child_args",
        nargs=argparse.REMAINDER,
        help="传给 p2 CLI 的参数（用 -- 分隔）",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    rest = [item for item in (args.child_args or []) if item != "--"]
    try:
        loaded = load_env_file(args.env_file)
    except EnvFileError as exc:
        print(
            json.dumps(
                {"ok": False, "error_code": exc.code, "detail": exc.detail, "values_printed": False},
                ensure_ascii=False,
            )
        )
        return 3
    summary = {
        "ok": True,
        "env_file": loaded.path.name,
        "injected": list(loaded.names),
        "values_printed": False,
    }
    if args.check_only:
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    if not rest:
        print(
            json.dumps(
                {"ok": False, "error_code": "child_args_missing", "detail": "需要用 -- 给出 p2 CLI 参数"},
                ensure_ascii=False,
            )
        )
        return 3
    try:
        code, stdout, stderr = run_cli(
            args.env_file, rest, python=args.python, module=args.module
        )
    except EnvFileError as exc:
        print(json.dumps({"ok": False, "error_code": exc.code, "detail": exc.detail}, ensure_ascii=False))
        return 3
    summary["child_exit_code"] = code
    print(json.dumps(summary, ensure_ascii=False))
    if stdout:
        sys.stdout.write(stdout if stdout.endswith("\n") else stdout + "\n")
    if stderr:
        sys.stderr.write(stderr if stderr.endswith("\n") else stderr + "\n")
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
