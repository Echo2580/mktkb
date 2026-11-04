"""S3 文件夹上传真实后端浏览器测试运行器。

只启动本脚本创建的隔离 FastAPI/worker/Vite 进程：
- 后端使用 frontend/e2e/folder-upload-real-server.py（真实 create_app + 真实 worker）；
- 数据目录位于 docs/evidence/LOCAL-R1-20261101/S3-DEV/tmp/real-<label>/data；
- 不读取 .env，不调用模型/embedding/rerank/OCR；
- 测试结束通过 /__s3/shutdown 停后端，只结束本脚本创建的 Vite 进程树。

用法：
    .venv/Scripts/python.exe -B frontend/e2e/folder-upload-real-run.py --label s3-real-01
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
EVIDENCE_ROOT = (ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "S3-DEV").resolve()
SERVER_SCRIPT = FRONTEND / "e2e" / "folder-upload-real-server.py"
PW_CONFIG = FRONTEND / "playwright.folder-real.config.ts"
LABEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def free_port(port: int) -> bool:
    with socket.socket() as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wait_http(url: str, process: subprocess.Popen, timeout_seconds: float, expect_json: bool = False) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    with httpx.Client(timeout=1.0, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"服务提前退出（exit={process.returncode}）：{url}")
            try:
                response = client.get(url)
                if response.status_code == 200 and (not expect_json or response.json().get("status") == "ok"):
                    return
                last_error = f"HTTP {response.status_code}"
            except (httpx.HTTPError, ValueError) as exc:
                last_error = type(exc).__name__
            time.sleep(0.2)
    raise RuntimeError(f"等待服务超时：{url}（{last_error}）")


def sanitized_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith("MKTKB_")}


def stop_process(process: subprocess.Popen | None, *, tree: bool, name: str, record: dict) -> None:
    if process is None:
        return
    if process.poll() is not None:
        record[name] = {"already_exited": True, "exit_code": process.returncode}
        return
    stopped: dict[str, object] = {}
    if os.name == "nt" and tree:
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stopped["taskkill_exit"] = result.returncode
        stopped["taskkill_stdout"] = result.stdout.strip()
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
        stopped["exit_code"] = process.returncode
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            stopped["ungraceful"] = True
        stopped["exit_code"] = process.returncode
    record[name] = stopped


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台可能是 GBK；Playwright 的 “›” 等字符不应让运行器自身失败。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--backend-port", type=int, default=8181)
    parser.add_argument("--frontend-port", type=int, default=5874)
    parser.add_argument("--skip-playwright", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    if not LABEL_RE.fullmatch(args.label):
        raise SystemExit("label 只能包含字母、数字、点、下划线和横线")

    label = args.label
    backend_origin = f"http://127.0.0.1:{args.backend_port}"
    frontend_origin = f"http://127.0.0.1:{args.frontend_port}"
    run_root = EVIDENCE_ROOT / "tmp" / f"real-{label}"
    data_dir = run_root / "data"
    if run_root.exists():
        raise SystemExit(f"隔离运行目录已存在，请换 label：{run_root}")
    if not free_port(args.backend_port) or not free_port(args.frontend_port):
        raise SystemExit(f"端口已被占用：backend={args.backend_port} frontend={args.frontend_port}")
    if not SERVER_SCRIPT.is_file() or not PW_CONFIG.is_file():
        raise SystemExit("缺少 S3 真实后端服务或 Playwright 配置")

    logs = EVIDENCE_ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    actual = EVIDENCE_ROOT / "actual"
    actual.mkdir(parents=True, exist_ok=True)
    backend_jsonl = logs / f"real-server-{label}.jsonl"
    backend_stdout = logs / f"real-server-{label}.stdout.log"
    backend_stderr = logs / f"real-server-{label}.stderr.log"
    vite_log = logs / f"real-vite-{label}.log"
    pw_stdout = logs / f"real-playwright-{label}.stdout.log"
    pw_stderr = logs / f"real-playwright-{label}.stderr.log"
    command_json = logs / f"real-run-{label}.command.json"
    run_json = actual / f"real-run-{label}.json"

    admin_password = secrets.token_urlsafe(18)
    employee_password = secrets.token_urlsafe(18)
    csrf_secret = secrets.token_urlsafe(32)
    record: dict[str, object] = {
        "label": label,
        "started_at": utc_now(),
        "backend_origin": backend_origin,
        "frontend_origin": frontend_origin,
        "data_dir": str(data_dir),
        "logs": {
            "backend_jsonl": str(backend_jsonl),
            "backend_stdout": str(backend_stdout),
            "backend_stderr": str(backend_stderr),
            "vite": str(vite_log),
            "playwright_stdout": str(pw_stdout),
            "playwright_stderr": str(pw_stderr),
        },
        "secrets": "临时凭据由运行器生成，不写入证据",
    }
    command_json.write_text(
        json.dumps(
            {
                "label": label,
                "backend_port": args.backend_port,
                "frontend_port": args.frontend_port,
                "server_script": str(SERVER_SCRIPT),
                "playwright_config": str(PW_CONFIG),
                "data_dir": str(data_dir),
                "skip_playwright": args.skip_playwright,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        python = Path(sys.executable)
    node = shutil.which("node")
    vite = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
    if not node or not vite.is_file():
        raise SystemExit("未找到 Node 或 Vite")

    backend: subprocess.Popen | None = None
    frontend: subprocess.Popen | None = None
    backend_out = backend_err = frontend_out = None
    exit_code = 1
    try:
        env = sanitized_env()
        env.update(
            {
                "S3_REAL_ADMIN_PASSWORD": admin_password,
                "S3_REAL_EMPLOYEE_PASSWORD": employee_password,
                "S3_REAL_CSRF_SECRET": csrf_secret,
            }
        )
        backend_out = backend_stdout.open("w", encoding="utf-8")
        backend_err = backend_stderr.open("w", encoding="utf-8")
        backend = subprocess.Popen(
            [
                str(python),
                "-B",
                str(SERVER_SCRIPT),
                "--port",
                str(args.backend_port),
                "--backend-origin",
                backend_origin,
                "--frontend-origin",
                frontend_origin,
                "--data-dir",
                str(data_dir),
                "--log-file",
                str(backend_jsonl),
            ],
            cwd=ROOT,
            env=env,
            stdout=backend_out,
            stderr=backend_err,
            stdin=subprocess.DEVNULL,
        )
        record["backend_pid"] = backend.pid
        wait_http(f"{backend_origin}/api/v1/healthz", backend, 30.0, expect_json=True)
        record["backend_ready"] = True

        frontend_out = vite_log.open("w", encoding="utf-8")
        frontend_env = sanitized_env()
        frontend_env["T08_BACKEND_ORIGIN"] = backend_origin
        frontend = subprocess.Popen(
            [node, str(vite), "--host", "127.0.0.1", "--port", str(args.frontend_port), "--strictPort"],
            cwd=FRONTEND,
            env=frontend_env,
            stdout=frontend_out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        record["frontend_pid"] = frontend.pid
        wait_http(frontend_origin, frontend, 60.0)
        record["frontend_ready"] = True

        if args.skip_playwright:
            record["playwright"] = {"skipped": True}
            exit_code = 0
        else:
            pw_env = sanitized_env()
            pw_env.update(
                {
                    "S3_REAL_BASE_URL": frontend_origin,
                    "S3_REAL_BACKEND_URL": backend_origin,
                    "S3_REAL_ADMIN_PASSWORD": admin_password,
                    "S3_REAL_EVIDENCE_ROOT": str(EVIDENCE_ROOT),
                    "S3_REAL_RUN_LABEL": label,
                }
            )
            playwright_cli = FRONTEND / "node_modules" / "@playwright" / "test" / "cli.js"
            if not playwright_cli.is_file():
                raise RuntimeError(f"缺少 Playwright CLI：{playwright_cli}")
            command = [node, str(playwright_cli), "test", "--config", str(PW_CONFIG), "--reporter=list"]
            started = time.monotonic()
            completed = subprocess.run(
                command,
                cwd=FRONTEND,
                env=pw_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=args.timeout_seconds,
            )
            duration = round(time.monotonic() - started, 3)
            pw_stdout.write_text(completed.stdout, encoding="utf-8")
            pw_stderr.write_text(completed.stderr, encoding="utf-8")
            record["playwright"] = {
                "command": command,
                "exit_code": completed.returncode,
                "duration_seconds": duration,
            }
            print(completed.stdout, flush=True)
            if completed.stderr:
                print(completed.stderr, file=sys.stderr, flush=True)
            exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        record["error"] = f"Playwright 超时：{exc}"
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        print(record["error"], file=sys.stderr, flush=True)
    finally:
        if backend is not None:
            try:
                with httpx.Client(timeout=5.0, trust_env=False) as client:
                    client.post(f"{backend_origin}/__s3/shutdown")
                record["shutdown_request"] = "ok"
            except httpx.HTTPError as exc:
                record["shutdown_request"] = type(exc).__name__
            try:
                backend.wait(timeout=10)
                record["backend_graceful_exit"] = backend.returncode
            except subprocess.TimeoutExpired:
                record["backend_graceful_exit"] = "timeout"
        stop_record: dict[str, object] = {}
        stop_process(backend, tree=False, name="backend_stop", record=stop_record)
        stop_process(frontend, tree=True, name="frontend_stop", record=stop_record)
        record["stops"] = stop_record
        for handle in (backend_out, backend_err, frontend_out):
            if handle is not None:
                handle.close()
        record["finished_at"] = utc_now()
        record["exit_code"] = exit_code
        run_json.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"RUN_RESULT={run_json}", flush=True)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
