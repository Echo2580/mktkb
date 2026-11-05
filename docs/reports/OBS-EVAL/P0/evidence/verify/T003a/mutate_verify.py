"""T003a 变异探针（仓库外）：证明“独立验收探针”与“开发者测试”对关键缺陷都不是空转。

做法：把 HEAD 的 mktkb 包复制到临时目录，逐条注入应被抓到的缺陷，分别运行：
  1) probe_tracer.py（验收者独立探针）——预期 control 通过、每个变异体失败；
  2) 开发者 test_tracer.py（仓库内测试，用 PYTHONPATH 指向变异副本 + -o pythonpath= 禁
     掉 pyproject 的 pythonpath，保证 import 的是变异副本）——预期 control 全过、每个变异体
     至少 1 条失败。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(os.environ.get("VERIFY_BASE", Path(__file__).resolve().parent))
PROBE = BASE / "probe_tracer.py"
REPO = Path(r"D:\GPT项目\市场部AI知识库")
REPO_SRC = REPO / "backend" / "src"
DEV_TEST = REPO / "backend" / "tests" / "observability" / "test_tracer.py"
WORK = BASE / "mutants"
PYTHON = sys.executable

MUTATIONS = [
    ("parent_span_id_always_none", "mktkb/observability/tracer.py",
     "            parent_span_id=_current_span_id(),", "            parent_span_id=None,"),
    ("finish_never_writes", "mktkb/observability/tracer.py",
     "            self._repo.write_best_effort(record, spans)", "            pass  # mutation: skip write"),
    ("validate_always_empty", "mktkb/observability/contracts.py",
     "    return sorted(required - set(span_names))", "    return []  # mutation"),
    ("missing_fields_status_ok", "mktkb/observability/tracer.py",
     "            return TRACE_STATUS_INCOMPLETE", "            return TRACE_STATUS_OK  # mutation"),
    ("contextvar_not_reset", "mktkb/observability/tracer.py",
     "        _CURRENT_TRACE.reset(current_token)", "        pass  # mutation: no reset"),
    ("content_mode_off_hashes", "mktkb/observability/tracer.py",
     "    if content_mode == CONTENT_MODE_OFF:", "    if False:  # mutation"),
    ("span_exception_status_ok", "mktkb/observability/tracer.py",
     "        self._status = SPAN_STATUS_ERROR", "        pass  # mutation"),
    ("trace_id_constant", "mktkb/observability/tracer.py",
     "        trace_id=uuid.uuid4().hex,", '        trace_id="0" * 32,'),
    ("attributes_ascii_escaped", "mktkb/observability/tracer.py",
     "        ensure_ascii=False,", "        ensure_ascii=True,"),
    ("conditional_spans_ignored", "mktkb/observability/contracts.py",
     "    required |= set(conditional_required_spans(attrs))", "    required |= set()  # mutation"),
    ("inner_trace_inherits_span_stack", "mktkb/observability/tracer.py",
     "    span_token = _SPAN_STACK.set(())", "    span_token = _SPAN_STACK.set(_SPAN_STACK.get())  # mutation"),
    ("auto_finish_missing", "mktkb/observability/tracer.py",
     "        trace.finish()", "        pass  # mutation: no auto finish"),
]


def copy_package(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    shutil.copytree(REPO_SRC / "mktkb", dest / "mktkb")


def env_for(package_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root)
    env["EXPECT_MKTKB_ROOT"] = str(package_root)
    env["PYTHONIOENCODING"] = "utf-8"
    env["MKTKB_PROJECT_TOTAL_LIMIT_CNY"] = "20.0"
    return env


def run_probe(package_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-B", str(PROBE)], cwd=str(BASE), env=env_for(package_root),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )


def run_dev_tests(package_root: Path) -> subprocess.CompletedProcess[str]:
    base_temp = tempfile.mkdtemp(prefix="t003a-devmut-", dir=str(BASE / "pytest-tmp"))
    return subprocess.run(
        [
            PYTHON, "-B", "-m", "pytest", str(DEV_TEST), "-q", "-p", "no:cacheprovider",
            "-o", "pythonpath=", "--basetemp", base_temp,
        ],
        cwd=str(REPO), env=env_for(package_root),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )


def marker(proc: subprocess.CompletedProcess[str]) -> str:
    for stream in (proc.stderr, proc.stdout):
        for line in (stream or "").splitlines():
            if "PROBE-FAIL::" in line:
                return line.strip()
            if "PROBE-ERROR" in line:
                return "PROBE-ERROR(意外异常)"
    for line in (proc.stdout or "").splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            return line.strip()[:120]
    return "(no marker)"


def main() -> int:
    (BASE / "pytest-tmp").mkdir(exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, str, str]] = []
    control = WORK / "control"
    copy_package(control)
    probe_proc = run_probe(control)
    dev_proc = run_dev_tests(control)
    control_ok = probe_proc.returncode == 0 and "PROBE-PASS" in probe_proc.stdout and dev_proc.returncode == 0
    rows.append((
        "control（未变异副本）",
        "PASS(exit 0)" if control_ok else "FAIL",
        f"probe exit={probe_proc.returncode}",
        f"dev pytest exit={dev_proc.returncode}",
    ))
    print(f"control: probe exit={probe_proc.returncode}, dev pytest exit={dev_proc.returncode}", flush=True)

    all_ok = control_ok
    for index, (name, rel, old, new) in enumerate(MUTATIONS, start=1):
        root = WORK / f"mut{index:02d}"
        copy_package(root)
        target = root / rel
        text = target.read_text(encoding="utf-8")
        count = text.count(old)
        if count != 1:
            rows.append((name, f"BAD-PATTERN({count})", "", ""))
            all_ok = False
            continue
        target.write_text(text.replace(old, new), encoding="utf-8")
        probe_proc = run_probe(root)
        dev_proc = run_dev_tests(root)
        probe_hit = probe_proc.returncode != 0
        dev_hit = dev_proc.returncode != 0
        rows.append((
            name,
            "BOTH-DETECTED" if (probe_hit and dev_hit) else ("PROBE-ONLY" if probe_hit else ("DEV-ONLY" if dev_hit else "MISSED")),
            marker(probe_proc),
            marker(dev_proc),
        ))
        print(
            f"[{index:02d}] {name}: probe={probe_proc.returncode} dev={dev_proc.returncode}",
            flush=True,
        )
        if not (probe_hit and dev_hit):
            all_ok = False

    print("\n| 变异体 | 结果 | 独立探针失败点 | 开发者测试失败点 |")
    print("| --- | --- | --- | --- |")
    for name, result, probe_mark, dev_mark in rows:
        print(f"| {name} | {result} | {probe_mark.replace('|', '/')} | {dev_mark.replace('|', '/')} |")
    detected = sum(1 for _, r, _, _ in rows[1:] if r != "MISSED" and not r.startswith("BAD"))
    print(
        f"\nMUTATION-SUMMARY::control={'PASS' if control_ok else 'FAIL'} mutants={len(MUTATIONS)} "
        f"detected_by_both={sum(1 for _, r, _, _ in rows[1:] if r == 'BOTH-DETECTED')} "
        f"missed={sum(1 for _, r, _, _ in rows[1:] if r == 'MISSED')} all_ok={all_ok}"
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
