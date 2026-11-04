"""T09-D3 B 层浏览器验收运行器：一条命令 = 一次完整运行，exit code 即结论。

职责（对应 ``docs/evidence/T09/D3/tmp/d3-acceptance-contract.md`` §2）：

1. ``--label`` 必填；所有输出路径由 label 派生到 ``docs/evidence/T09/D3``：
   - 服务日志 ``logs/acceptance-server-<label>.jsonl``（后端服务自身 JSONL）
   - 后端 stdout/stderr ``logs/acceptance-server-<label>.stdout.log`` / ``.stderr.log``
   - Vite 日志 ``logs/acceptance-vite-<label>.log``
   - Playwright stdout/stderr ``logs/playwright-<label>.stdout.log`` / ``.stderr.log``
   - Playwright JSON ``actual/playwright-<label>.json``；状态快照 ``actual/acceptance-state-<label>.json``
   - Playwright outputDir ``tmp/pw-<label>/results``；HTML 报告 ``tmp/pw-<label>/report``
   - 截图根 ``screenshots/<label>/``
   - 命令记录 ``logs/browser-acceptance-<label>.command.json``
2. 先确认 8188/5199 空闲（netstat + 连接探测 + 绑定探测三重核对），不空闲立即失败并留证；
   同时拒绝复用已存在的数据目录（``tmp/acceptance-<label>/data``）。
3. 启动后端（独立进程）→ 等真实 ``/api/v1/healthz`` 200（≤180s）；
4. 启动 Vite ``npm.cmd run dev -- --port 5199 --strictPort``（cwd=frontend，
   ``T08_BACKEND_ORIGIN=http://127.0.0.1:8188``）→ 等 ``http://127.0.0.1:5199/`` 可访问；
5. 跑 ``npx.cmd playwright test --config frontend/playwright.acceptance.config.ts``（cwd=frontend，
   传入 D3 路径 env）；捕获 stdout/stderr 与退出码；
6. 无论成败：先取 ``/__acceptance/state`` 的 outbound 快照存 ``actual/``，再停 Vite/后端
   （后端走控制面 ``POST /__acceptance/shutdown`` 优雅退出；Windows 上无法可靠发 SIGTERM，
   因此优先控制面停服，超时才强杀进程树）；
7. exit code：Playwright 通过 且 outbound.external 为空 且 服务/前端正常启动 → 0；否则非 0。

调试参数：``--dry-run``（只起后端并取快照，不跑 Vite/Playwright）、``--skip-vite``、
``--skip-playwright``、``--playwright-args "<额外参数>"``（shlex 拆分）、``--timeout-seconds``。

用法（cwd=仓库根）::

    .venv\\Scripts\\python.exe -B backend\\tests\\acceptance\\support\\run_browser_acceptance.py --label d3-b-01
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[4]
DEFAULT_EVIDENCE_ROOT = ROOT / "docs" / "evidence" / "T09" / "D3"
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8188
VITE_HOST = "127.0.0.1"
VITE_PORT = 5199
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"
VITE_URL = f"http://{VITE_HOST}:{VITE_PORT}"
HEALTH_TIMEOUT_SECONDS = 180.0
VITE_TIMEOUT_SECONDS = 120.0
SHUTDOWN_WAIT_SECONDS = 30.0
DEFAULT_PLAYWRIGHT_TIMEOUT_SECONDS = 1800.0
T08_PORTS = (8077, 5173)  # T08 端口，仅记录占用情况；本运行器绝不使用
# 本机环境可能设置 HTTP(S)_PROXY（另有 NO_PROXY 回环例外）；运行器自检强制直连回环。
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ---------------------------------------------------------------- 基础工具


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    path.write_text(text, encoding="utf-8")


def read_tail(path: Path, limit: int = 40) -> list[str]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


def _netstat_listen_lines() -> list[str]:
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return completed.stdout.splitlines()
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - netstat 不可用时退化为连接/绑定探测
        return []


def check_port_free(port: int) -> dict:
    """三重核对：netstat LISTENING 行、主动连接、绑定尝试。返回证据字典与 in_use 结论。"""
    evidence: dict = {"port": port, "netstat_listen": [], "connect_ok": False, "bind_error": None, "in_use": False}
    for line in _netstat_listen_lines():
        if f":{port}" in line and "LISTEN" in line.upper():
            evidence["netstat_listen"].append(line.strip())
            evidence["in_use"] = True
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            evidence["connect_ok"] = True
            evidence["in_use"] = True
    except OSError:
        pass
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
    except OSError as exc:
        evidence["bind_error"] = f"{type(exc).__name__}: {exc}"
        evidence["in_use"] = True
    finally:
        probe.close()
    return evidence


def http_get_json(url: str, timeout: float = 5.0):
    with _DIRECT_OPENER.open(url, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body)


def http_post_json(url: str, payload: dict, timeout: float = 10.0):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with _DIRECT_OPENER.open(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return response.status, (json.loads(body) if body.strip() else {})


def wait_http(url: str, timeout: float, proc: subprocess.Popen | None = None, proc_log: Path | None = None) -> int:
    """轮询 URL 直到返回 2xx/3xx；返回耗时毫秒。进程提前退出时抛 RuntimeError（附带日志尾部）。"""
    started = time.monotonic()
    deadline = started + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            tail = "\n".join(read_tail(proc_log)) if proc_log else ""
            raise RuntimeError(f"子进程提前退出（exit={proc.returncode}）：{tail[-1200:]}")
        try:
            with _DIRECT_OPENER.open(url, timeout=2.0) as response:
                if 200 <= response.status < 400:
                    return int((time.monotonic() - started) * 1000)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise TimeoutError(f"等待 {url} 可用超时（最后错误 {type(last_error).__name__ if last_error else 'none'}）")


def terminate_tree(proc: subprocess.Popen | None) -> int | None:
    """终止进程及其子进程树（Windows 用 taskkill /T）；返回退出码（无法获取时 None）。"""
    if proc is None:
        return None
    if proc.poll() is not None:
        return proc.returncode
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        else:  # pragma: no cover - 本轮只在 Windows 运行
            proc.terminate()
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        try:
            proc.kill()
        except OSError:
            pass
    try:
        return proc.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover
        try:
            proc.kill()
            return proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return None


def log_stream(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8")


class RunnerAbort(RuntimeError):
    """预检/子步骤失败：携带建议的退出码，最终统一写命令记录后退出。"""

    def __init__(self, code: int, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


# ---------------------------------------------------------------- 主流程


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="T09-D3 B 层浏览器验收一条命令运行器")
    parser.add_argument("--label", required=True, help="本轮唯一 label（如 d3-b-01）")
    parser.add_argument("--evidence-root", default=None, help="证据根目录；默认 docs/evidence/T09/D3")
    parser.add_argument("--skip-vite", action="store_true", help="调试用：不启动 Vite（需自备 5199 前端）")
    parser.add_argument("--skip-playwright", action="store_true", help="调试用：不跑 Playwright（仍启停服务）")
    parser.add_argument(
        "--playwright-args",
        default="",
        help='调试用：传给 playwright 的额外参数，如 --grep acceptance-01 --headed',
    )
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_PLAYWRIGHT_TIMEOUT_SECONDS, help="Playwright 总超时秒数")
    parser.add_argument("--dry-run", action="store_true", help="等价于 --skip-vite --skip-playwright：只验证后端启动/停服/状态快照")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    label = args.label.strip()
    if not label:
        print("ERROR --label 不能为空", file=sys.stderr, flush=True)
        return 2
    dry_run = bool(args.dry_run)
    skip_vite = bool(args.skip_vite or dry_run)
    skip_playwright = bool(args.skip_playwright or dry_run)
    d3 = Path(args.evidence_root) if args.evidence_root else DEFAULT_EVIDENCE_ROOT
    d3 = d3.resolve()

    # ---- 由 label 派生的全部输出路径（契约 §2.1） ----
    data_dir = d3 / "tmp" / f"acceptance-{label}" / "data"
    server_jsonl = d3 / "logs" / f"acceptance-server-{label}.jsonl"
    backend_stdout = d3 / "logs" / f"acceptance-server-{label}.stdout.log"
    backend_stderr = d3 / "logs" / f"acceptance-server-{label}.stderr.log"
    vite_log = d3 / "logs" / f"acceptance-vite-{label}.log"
    pw_stdout = d3 / "logs" / f"playwright-{label}.stdout.log"
    pw_stderr = d3 / "logs" / f"playwright-{label}.stderr.log"
    pw_json = d3 / "actual" / f"playwright-{label}.json"
    state_json = d3 / "actual" / f"acceptance-state-{label}.json"
    command_json = d3 / "logs" / f"browser-acceptance-{label}.command.json"
    pw_output_dir = d3 / "tmp" / f"pw-{label}" / "results"
    pw_html = d3 / "tmp" / f"pw-{label}" / "report"
    screenshots_dir = d3 / "screenshots" / label
    pw_config = ROOT / "frontend" / "playwright.acceptance.config.ts"
    vite_cwd = ROOT / "frontend"
    server_script = ROOT / "backend" / "tests" / "acceptance" / "support" / "serve_acceptance.py"

    started_at = now_iso()
    started_monotonic = time.monotonic()
    mode = "dry-run" if dry_run else ("skip-playwright" if skip_playwright else ("skip-vite" if skip_vite else "full"))

    record: dict = {
        "label": label,
        "mode": mode,
        "argv": list(sys.argv),
        "cwd": str(Path.cwd()),
        "python": sys.executable,
        "python_version": platform.python_version(),
        "os": platform.platform(),
        "started_at": started_at,
        "ended_at": None,
        "duration_seconds": None,
        "exit_code": None,
        "failure_reason": None,
        "ports": {},
        "components": {
            "backend": {"pid": None, "ready_ms": None, "exit_code": None, "stopped_by": None},
            "vite": {"pid": None, "ready_ms": None, "exit_code": None, "stopped_by": None},
            "playwright": {"exit_code": None, "duration_seconds": None, "command": None},
        },
        "outbound": None,
        "artifacts": {
            "server_jsonl": str(server_jsonl),
            "backend_stdout": str(backend_stdout),
            "backend_stderr": str(backend_stderr),
            "vite_log": str(vite_log),
            "playwright_stdout": str(pw_stdout),
            "playwright_stderr": str(pw_stderr),
            "playwright_json": str(pw_json),
            "state_json": str(state_json),
            "playwright_output_dir": str(pw_output_dir),
            "playwright_html": str(pw_html),
            "screenshots": str(screenshots_dir),
            "data_dir": str(data_dir),
        },
    }

    backend_proc: subprocess.Popen | None = None
    vite_proc: subprocess.Popen | None = None
    backend_stdout_handle = backend_stderr_handle = vite_handle = None
    exit_code = 1
    failure_reason: str | None = None

    try:
        # ---- 0. 预检：数据目录不复用；端口空闲；Playwright 配置存在 ----
        if data_dir.exists():
            raise RunnerAbort(2, f"数据目录已存在，拒绝复用：{data_dir}")
        for port in T08_PORTS:
            record["ports"][f"t08_{port}"] = check_port_free(port)
        for name, port in (("backend", BACKEND_PORT), ("vite", VITE_PORT)):
            evidence = check_port_free(port)
            record["ports"][name] = evidence
            if evidence["in_use"]:
                if name == "vite" and skip_vite:
                    # 调试模式（--dry-run/--skip-vite）不启动 Vite：5199 被占用只记录、不阻断，
                    # 默认全流程仍按契约“端口不空闲立即失败”。
                    evidence["note"] = "skip-vite 模式：5199 被占用仅记录，不阻断"
                    continue
                raise RunnerAbort(2, f"端口 {port} 已被占用：{evidence}")
        if not skip_playwright and not pw_config.is_file():
            raise RunnerAbort(2, f"缺少 Playwright 验收配置：{pw_config}（由前端队员交付）")
        if not server_script.is_file():  # pragma: no cover - 本文件同目录
            raise RunnerAbort(2, f"缺少后端验收服务脚本：{server_script}")

        (d3 / "tmp").mkdir(parents=True, exist_ok=True)
        pw_output_dir.mkdir(parents=True, exist_ok=True)
        pw_html.parent.mkdir(parents=True, exist_ok=True)
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        # ---- 1. 启动后端（独立进程，等真实 healthz） ----
        backend_cmd = [
            sys.executable,
            "-B",
            str(server_script),
            "--host",
            BACKEND_HOST,
            "--port",
            str(BACKEND_PORT),
            "--data-dir",
            str(data_dir),
            "--log-file",
            str(server_jsonl),
            "--label",
            label,
        ]
        record["components"]["backend"]["command"] = backend_cmd
        record["components"]["backend"]["data_dir"] = str(data_dir)
        backend_stdout_handle = log_stream(backend_stdout)
        backend_stderr_handle = log_stream(backend_stderr)
        backend_proc = subprocess.Popen(
            backend_cmd,
            cwd=str(ROOT),
            stdout=backend_stdout_handle,
            stderr=backend_stderr_handle,
            env=os.environ.copy(),
        )
        record["components"]["backend"]["pid"] = backend_proc.pid
        try:
            ready_ms = wait_http(f"{BACKEND_URL}/api/v1/healthz", HEALTH_TIMEOUT_SECONDS, backend_proc, backend_stderr)
        except (RuntimeError, TimeoutError) as exc:
            raise RunnerAbort(3, f"后端未就绪：{exc}") from exc
        record["components"]["backend"]["ready_ms"] = ready_ms
        print(f"BACKEND READY {BACKEND_URL} ({ready_ms} ms)", flush=True)

        # ---- 2. 启动 Vite（可选） ----
        if not skip_vite:
            npm = shutil.which("npm.cmd") or shutil.which("npm")
            if not npm:
                raise RunnerAbort(3, "找不到 npm/npm.cmd，无法启动 Vite")
            vite_env = os.environ.copy()
            vite_env["T08_BACKEND_ORIGIN"] = BACKEND_URL
            vite_cmd = [npm, "run", "dev", "--", "--port", str(VITE_PORT), "--strictPort"]
            record["components"]["vite"]["command"] = vite_cmd
            vite_handle = log_stream(vite_log)
            vite_proc = subprocess.Popen(
                vite_cmd,
                cwd=str(vite_cwd),
                stdout=vite_handle,
                stderr=subprocess.STDOUT,
                env=vite_env,
            )
            record["components"]["vite"]["pid"] = vite_proc.pid
            try:
                vite_ready_ms = wait_http(f"{VITE_URL}/", VITE_TIMEOUT_SECONDS, vite_proc, vite_log)
            except (RuntimeError, TimeoutError) as exc:
                raise RunnerAbort(3, f"Vite 未就绪：{exc}") from exc
            record["components"]["vite"]["ready_ms"] = vite_ready_ms
            print(f"VITE READY {VITE_URL} ({vite_ready_ms} ms)", flush=True)

        # ---- 3. 跑 Playwright（可选） ----
        if not skip_playwright:
            npx = shutil.which("npx.cmd") or shutil.which("npx")
            if not npx:
                raise RunnerAbort(3, "找不到 npx/npx.cmd，无法运行 Playwright")
            pw_env = os.environ.copy()
            pw_env.update(
                {
                    "D3_EVIDENCE_ROOT": str(d3),
                    "D3_LABEL": label,
                    "D3_BACKEND_URL": BACKEND_URL,
                    "D3_BASE_URL": VITE_URL,
                    "D3_PW_OUTPUT": str(pw_output_dir),
                    "D3_PW_JSON": str(pw_json),
                    "D3_PW_HTML": str(pw_html),
                    "D3_SCREENSHOTS": str(screenshots_dir),
                }
            )
            pw_cmd = [npx, "playwright", "test", "--config", str(pw_config)]
            pw_cmd.extend(shlex.split(args.playwright_args or ""))
            record["components"]["playwright"]["command"] = pw_cmd
            pw_started = time.monotonic()
            with log_stream(pw_stdout) as out_handle, log_stream(pw_stderr) as err_handle:
                pw_proc = subprocess.Popen(
                    pw_cmd,
                    cwd=str(vite_cwd),
                    stdout=out_handle,
                    stderr=err_handle,
                    env=pw_env,
                )
                try:
                    pw_exit = pw_proc.wait(timeout=float(args.timeout_seconds))
                except subprocess.TimeoutExpired:
                    terminate_tree(pw_proc)
                    pw_exit = -1
                    record["components"]["playwright"]["timed_out"] = True
            record["components"]["playwright"]["exit_code"] = pw_exit
            record["components"]["playwright"]["duration_seconds"] = round(time.monotonic() - pw_started, 3)
            print(f"PLAYWRIGHT EXIT {pw_exit}", flush=True)

        # ---- 4. 取 outbound 状态快照（无论成败，先取再停服） ----
        try:
            _status_code, state = http_get_json(f"{BACKEND_URL}/__acceptance/state")
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            raise RunnerAbort(3, f"取 /__acceptance/state 失败：{type(exc).__name__}: {exc}") from exc
        write_json(state_json, state)
        outbound = state.get("outbound") or {}
        record["outbound"] = {
            "external": list(outbound.get("external") or []),
            "local_count": outbound.get("local_count"),
            "external_count": len(outbound.get("external") or []),
            "state_status": state.get("status"),
            "revision": state.get("revision"),
            "scenarios": {key: bool(value) for key, value in (state.get("scenarios") or {}).items()},
        }
        print(json.dumps({"outbound": record["outbound"]}, ensure_ascii=False), flush=True)

        # ---- 5. 结论 ----
        problems: list[str] = []
        if record["components"]["playwright"]["exit_code"] not in (None, 0):
            problems.append(f"playwright={record['components']['playwright']['exit_code']}")
        if record["components"]["backend"].get("ready_ms") is None:
            problems.append("backend_not_ready")
        if not skip_vite and record["components"]["vite"].get("ready_ms") is None:
            problems.append("vite_not_ready")
        if record["outbound"]["external_count"]:
            problems.append(f"outbound_external={record['outbound']['external']}")
        if problems:
            failure_reason = "; ".join(problems)
            exit_code = 4 if record["outbound"]["external_count"] else 1
        else:
            exit_code = 0
    except RunnerAbort as exc:
        exit_code = exc.code
        failure_reason = exc.reason
    except Exception as exc:  # noqa: BLE001 - 任何未预期异常都要落命令记录并保留日志
        exit_code = 3
        failure_reason = f"{type(exc).__name__}: {exc}"
    finally:
        # ---- 6. 停服：后端优先控制面优雅停服，Vite/后端超时才强杀进程树 ----
        if backend_proc is not None:
            if backend_proc.poll() is None:
                try:
                    http_post_json(f"{BACKEND_URL}/__acceptance/shutdown", {"reason": "runner"}, timeout=5.0)
                    record["components"]["backend"]["stopped_by"] = "control"
                except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
                    record["components"]["backend"]["shutdown_request_error"] = f"{type(exc).__name__}: {exc}"
                try:
                    record["components"]["backend"]["exit_code"] = backend_proc.wait(timeout=SHUTDOWN_WAIT_SECONDS)
                except subprocess.TimeoutExpired:
                    record["components"]["backend"]["stopped_by"] = "terminate-tree"
                    record["components"]["backend"]["exit_code"] = terminate_tree(backend_proc)
            else:
                record["components"]["backend"]["exit_code"] = backend_proc.returncode
        if vite_proc is not None:
            if vite_proc.poll() is None:
                record["components"]["vite"]["stopped_by"] = "terminate-tree"
                record["components"]["vite"]["exit_code"] = terminate_tree(vite_proc)
            else:
                record["components"]["vite"]["exit_code"] = vite_proc.returncode
        for handle in (backend_stdout_handle, backend_stderr_handle, vite_handle):
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
        record["ended_at"] = now_iso()
        record["duration_seconds"] = round(time.monotonic() - started_monotonic, 3)
        record["exit_code"] = exit_code
        record["failure_reason"] = failure_reason
        write_json(command_json, record)
        print(json.dumps({"label": label, "exit_code": exit_code, "failure_reason": failure_reason}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
