"""T003b 独立验收：仓库外变异探针。

在 %TEMP% 复制一份 backend/（不触碰仓库文件），对 T003b 交付物做定向变异，
运行开发测试 test_middleware.py 的对应用例，验证断言不是空转：
- M1 默认开启（config.trace_enabled 默认 True）
- M2 错误路径也带头（_QA_POST_PATH 放宽为全部 /api/v1 路径）
- M3 传 live（TRACE_MODE = TraceMode.LIVE）
- M4 开启后不生效（中间件条件恒 False，不启动 trace）
- M5 写入失败抛给响应（tracer.finish 不再兜底 write_best_effort 异常）
- M6 非 QA 响应也带 X-Trace-ID

每个变异只运行能检出的最少用例；期望 rc != 0 且目标用例出现在失败集合。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
PY = str(REPO / ".venv" / "Scripts" / "python.exe")
TEST_REL = "tests/observability/test_middleware.py"
BASE_ENV = {
    **os.environ,
    "MKTKB_PROJECT_TOTAL_LIMIT_CNY": "20.0",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def copy_backend(dst: Path) -> None:
    shutil.copytree(
        REPO / "backend",
        dst,
        ignore=shutil.ignore_patterns(
            ".pytest-tmp", "__pycache__", "*.pyc", ".pytest_cache", "*.egg-info"
        ),
    )


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def mutate(path: Path, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise AssertionError(f"变异锚点未找到于 {path}：{old[:80]!r}")
    write(path, text.replace(old, new, 1))


def run_pytest(backend_copy: Path, selectors: list[str], tag: str) -> dict:
    basetemp = backend_copy / ".pytest-tmp" / f"mut-{tag}"
    basetemp.parent.mkdir(parents=True, exist_ok=True)
    env = {**BASE_ENV, "PYTHONPATH": str(backend_copy / "src")}
    command = [
        PY,
        "-B",
        "-m",
        "pytest",
        *selectors,
        "-q",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(basetemp),
    ]
    completed = subprocess.run(
        command,
        cwd=str(backend_copy),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return {"tag": tag, "returncode": completed.returncode, "output": output}


def import_check(backend_copy: Path) -> str:
    env = {**BASE_ENV, "PYTHONPATH": str(backend_copy / "src")}
    completed = subprocess.run(
        [PY, "-B", "-c", "import mktkb, sys; print(mktkb.__file__)"],
        cwd=str(backend_copy),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    return (completed.stdout or "").strip(), (completed.stderr or "").strip()


def summarize(result: dict) -> dict:
    lines = [line for line in result["output"].splitlines() if line.strip()]
    failed_lines = [line for line in lines if line.startswith("FAILED ")]
    errors_lines = [line for line in lines if line.startswith("ERROR ")]
    tail = lines[-3:]
    return {
        "tag": result["tag"],
        "returncode": result["returncode"],
        "failed": failed_lines,
        "errors": errors_lines,
        "tail": tail,
    }


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="t003b-mutation-"))
    print(f"mutation_root={root}")
    backend_copy = root / "backend"
    copy_backend(backend_copy)
    module_path, module_err = import_check(backend_copy)
    print(f"copy import mktkb -> {module_path} {module_err}".rstrip())
    if str(backend_copy / "src").lower() not in module_path.lower():
        print("FATAL: 复制副本没有优先导入自己的源码")
        return 2

    # 先跑未变异副本，证明复制环境本身可运行（20 passed）
    baseline = run_pytest(backend_copy, [TEST_REL], "baseline")
    baseline_summary = summarize(baseline)
    print("M0 unmutated copy:", baseline_summary["returncode"], baseline_summary["tail"])
    if baseline_summary["returncode"] != 0:
        print("---- M0 FULL OUTPUT ----")
        print(baseline["output"])
        return 2

    results = [{"mutation": "M0-unmutated-copy", **baseline_summary}]

    def fresh_copy(tag: str) -> Path:
        target = root / f"backend-{tag}"
        copy_backend(target)
        return target

    # M1 默认开启
    m1 = fresh_copy("M1")
    mutate(m1 / "src" / "mktkb" / "config.py", "trace_enabled: bool = False", "trace_enabled: bool = True")
    r = run_pytest(
        m1,
        [
            f"{TEST_REL}::test_settings_trace_defaults_are_disabled_and_safe",
            f"{TEST_REL}::test_disabled_app_has_no_trace_repo_or_db_file_and_keeps_request_id",
        ],
        "M1",
    )
    results.append({"mutation": "M1-default-enabled", **summarize(r)})

    # M2 错误路径也带头：路径正则放宽为所有 /api/v1 路径
    m2 = fresh_copy("M2")
    mutate(
        m2 / "src" / "mktkb" / "main.py",
        '_QA_POST_PATH = re.compile(r"^/api/v1/conversations/[^/]+/messages$")',
        '_QA_POST_PATH = re.compile(r"^/api/v1/.*$")',
    )
    r = run_pytest(
        m2,
        [f"{TEST_REL}::test_only_qa_post_gets_trace_header_and_writes_trace"],
        "M2",
    )
    results.append({"mutation": "M2-broad-qapath", **summarize(r)})

    # M3 传 live
    m3 = fresh_copy("M3")
    mutate(m3 / "src" / "mktkb" / "main.py", "TRACE_MODE = TraceMode.LOCAL", "TRACE_MODE = TraceMode.LIVE")
    r = run_pytest(
        m3,
        [
            f"{TEST_REL}::test_middleware_passes_local_mode_and_settings_content_mode",
            f"{TEST_REL}::test_middleware_source_hardcodes_local_mode_never_live",
        ],
        "M3",
    )
    results.append({"mutation": "M3-live-mode", **summarize(r)})

    # M4 开启后不生效（中间件永不启动 trace）
    m4 = fresh_copy("M4")
    mutate(
        m4 / "src" / "mktkb" / "main.py",
        "if trace_repo is not None and _is_qa_post(request):",
        "if False:  # MUTATION: enabled trace never starts",
    )
    r = run_pytest(
        m4,
        [f"{TEST_REL}::test_enabled_qa_post_returns_uuid_trace_header_and_persists_trace"],
        "M4",
    )
    results.append({"mutation": "M4-enabled-noop", **summarize(r)})

    # M5 写入失败抛给响应（内核 finish 不再兜底）
    m5 = fresh_copy("M5")
    mutate(
        m5 / "src" / "mktkb" / "observability" / "tracer.py",
        """        try:
            self._repo.write_best_effort(record, spans)
        except Exception:  # noqa: BLE001 - 写入失败不抛、不中断调用方（设计 §6.6）
            LOGGER.warning(
                "trace_finish_error: trace_id=%r", self.trace_id, exc_info=True
            )""",
        "        self._repo.write_best_effort(record, spans)  # MUTATION: propagate",
    )
    r = run_pytest(
        m5,
        [f"{TEST_REL}::test_monkeypatched_write_failure_keeps_qa_response"],
        "M5",
    )
    results.append({"mutation": "M5-write-failure-propagates", **summarize(r)})

    # M6 非 QA 响应也带 X-Trace-ID
    m6 = fresh_copy("M6")
    mutate(
        m6 / "src" / "mktkb" / "main.py",
        """        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    register_error_handlers(app)""",
        """        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Trace-ID"] = "MUTATED-HEADER"
        return response

    register_error_handlers(app)""",
    )
    r = run_pytest(
        m6,
        [
            f"{TEST_REL}::test_disabled_app_has_no_trace_repo_or_db_file_and_keeps_request_id",
            f"{TEST_REL}::test_only_qa_post_gets_trace_header_and_writes_trace",
        ],
        "M6",
    )
    results.append({"mutation": "M6-header-all-paths", **summarize(r)})

    print("\n===== MUTATION SUMMARY =====")
    expected = {
        "M0-unmutated-copy": True,   # 未变异应全过（rc == 0）
        "M1-default-enabled": False,
        "M2-broad-qapath": False,
        "M3-live-mode": False,
        "M4-enabled-noop": False,
        "M5-write-failure-propagates": False,
        "M6-header-all-paths": False,
    }
    all_ok = True
    for item in results:
        want_pass = expected[item["mutation"]]
        got_pass = item["returncode"] == 0
        detected = (got_pass == want_pass) if want_pass else (not got_pass)
        all_ok = all_ok and detected
        print(
            f"{'DETECTED' if detected else 'MISSED  '} {item['mutation']}: "
            f"rc={item['returncode']} failed={item['failed']} tail={item['tail']}"
        )
    print(json.dumps(results, ensure_ascii=False, indent=1))
    print(f"mutation_probe_result={'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
