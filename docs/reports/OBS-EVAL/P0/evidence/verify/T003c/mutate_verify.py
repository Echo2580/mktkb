"""T003c 独立验收：仓库外副本变异探针。

把 commit 776497f 的 ``backend/src``（已用 git archive 解出）+ 工作树测试复制到
临时目录，对副本施加变异，再运行开发测试 ``test_rag_spans.py``，确认测试会失败
（非空转）。仓库内文件不修改。

用法：python mutate_verify.py <report.txt> <base_backend_dir> <work_dir>
  base_backend_dir: 含 src/ 的临时 backend 目录（例如 %TEMP%/t003c-verify/new/backend）
  work_dir: 变异副本根目录
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]  # repo root
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
TEST_FILE = "tests/observability/test_rag_spans.py"


def prepare_base(base: Path, work: Path) -> Path:
    """复制 src（已解出）+ 工作树 tests/pyproject 到 work/base/backend。"""
    target = work / "base" / "backend"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copytree(base / "src", target / "src")
    if (base / "migrations").exists():
        shutil.copytree(base / "migrations", target / "migrations")
    shutil.copytree(ROOT / "backend" / "tests", target / "tests")
    shutil.copy2(ROOT / "backend" / "pyproject.toml", target / "pyproject.toml")
    return target


def apply_replace(base: Path, mutation: dict) -> None:
    path = base / mutation["file"]
    text = path.read_text(encoding="utf-8")
    count = text.count(mutation["old"])
    if count != 1:
        raise AssertionError(
            f"{mutation['id']}: 期望原文出现 1 次，实际 {count} 次（{mutation['file']}）"
        )
    path.write_text(text.replace(mutation["old"], mutation["new"]), encoding="utf-8")


def apply_span_error_mutation(base: Path) -> None:
    """把 trace_attrs.span 改成“异常时正常退出上下文、不标 error”。"""
    path = base / "src" / "mktkb" / "observability" / "trace_attrs.py"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"@contextmanager\r?\ndef span\(name: str, \*\*attrs: Any\) -> Iterator\[SpanHandle \| NullSpan\]:.*?"
        r"(?=\r?\ndef annotate_trace)",
        re.S,
    )
    replacement = '''@contextmanager
def span(name: str, **attrs: Any) -> Iterator[SpanHandle | NullSpan]:
    trace = current_trace()
    if trace is None:
        yield _NULL_SPAN
        return
    manager = trace.span(name, **attrs)
    handle = manager.__enter__()
    try:
        yield handle
    except BaseException:
        manager.__exit__(None, None, None)
        raise
    else:
        manager.__exit__(None, None, None)


'''
    new_text, count = pattern.subn(replacement, text)
    if count != 1:
        raise AssertionError(f"span 函数替换失败，匹配 {count} 次")
    path.write_text(new_text, encoding="utf-8")


MUTATIONS = [
    {
        "id": "M1-missing-fuse-span",
        "file": "src/mktkb/rag/retrieval.py",
        "old": 'with trace_attrs.span("fuse") as fuse_span:',
        "new": 'with trace_attrs.span("fuse_mutated") as fuse_span:',
        "expect_fail": [
            "test_answer_path_span_set_and_hierarchy",
            "test_conditional_spans_agree_with_filter_decisions_json",
            "test_rerank_span_only_when_rerank_actually_executes",
            "test_retrieval_no_answer_passes_integrity",
            "test_conflict_path_includes_answer_and_fact_validate",
        ],
    },
    {
        "id": "M2-vector-span-always",
        "file": "src/mktkb/rag/retrieval.py",
        "old": '            if vector_enabled:\n                with trace_attrs.span("vector_recall")',
        "new": '            if True:\n                with trace_attrs.span("vector_recall")',
        "expect_fail": ["test_vector_span_absent_when_query_embedding_disabled"],
    },
    {
        "id": "M3-raw-question-in-attributes",
        "file": "src/mktkb/rag/answer.py",
        "old": (
            "            unknown_store=bool(plan.unknown_store),\n"
            "            reason=plan.reason,\n"
            "        )"
        ),
        "new": (
            "            unknown_store=bool(plan.unknown_store),\n"
            "            reason=plan.reason,\n"
            "            question_text=plan.question,\n"
            "        )"
        ),
        "expect_fail": ["test_trace_and_span_attributes_are_canonical_and_content_free"],
    },
    {
        "id": "M4-exception-not-marked-error",
        "file": None,
        "expect_fail": [
            "test_internal_exception_marks_span_error_and_still_propagates",
            "test_embedding_failure_marks_embedding_span_error_without_new_exception",
            "test_fact_rejection_marks_fact_span_error_and_returns_refusal",
        ],
    },
]


def run_case(mut_dir: Path, backend: Path) -> dict:
    result = subprocess.run(
        [
            str(PYTHON),
            "-B",
            "-m",
            "pytest",
            TEST_FILE,
            "-q",
            "-rf",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(mut_dir / "pytest-tmp"),
        ],
        cwd=str(backend),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    output = result.stdout + "\n" + result.stderr
    failed = sorted(set(re.findall(r"FAILED [^\s:]*::(\w+)", output)))
    summary = [line for line in output.splitlines() if re.search(r"\d+ (passed|failed)", line)]
    return {
        "returncode": result.returncode,
        "failed_tests": failed,
        "summary": summary[-1] if summary else "",
        "output": output,
    }


def main() -> int:
    report_path = Path(sys.argv[1])
    base_source = Path(sys.argv[2])
    work = Path(sys.argv[3])
    work.mkdir(parents=True, exist_ok=True)
    base = prepare_base(base_source, work)

    lines: list[str] = []
    results: list[dict] = []

    # 控制组
    control_dir = work / "control"
    if control_dir.exists():
        shutil.rmtree(control_dir)
    shutil.copytree(base, control_dir / "backend")
    control = run_case(control_dir, control_dir / "backend")
    control_ok = control["returncode"] == 0 and "20 passed" in control["summary"]
    lines.append(f"CONTROL: {control['summary']} rc={control['returncode']} OK={control_ok}")
    results.append({"id": "control", "expected": "20 passed", "ok": control_ok,
                    "failed": control["failed_tests"], "summary": control["summary"]})

    for mutation in MUTATIONS:
        mut_dir = work / mutation["id"]
        if mut_dir.exists():
            shutil.rmtree(mut_dir)
        backend = mut_dir / "backend"
        shutil.copytree(base, backend)
        if mutation["file"] is None:
            apply_span_error_mutation(backend)
        else:
            apply_replace(backend, mutation)
        outcome = run_case(mut_dir, backend)
        detected = all(
            any(expected in failed for failed in outcome["failed_tests"])
            for expected in mutation["expect_fail"]
        )
        lines.append(
            f"{mutation['id']}: rc={outcome['returncode']} summary={outcome['summary']!r} "
            f"detected={detected} failed={outcome['failed_tests']}"
        )
        results.append(
            {
                "id": mutation["id"],
                "expected_failures": mutation["expect_fail"],
                "ok": detected,
                "failed": outcome["failed_tests"],
                "summary": outcome["summary"],
                "returncode": outcome["returncode"],
            }
        )
        # 保留输出便于审计
        (work / f"{mutation['id']}.log").write_text(outcome["output"], encoding="utf-8")

    overall = control_ok and all(item["ok"] for item in results[1:])
    lines.append("RESULT " + ("PASS" if overall else "FAIL"))
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    (work / "mutation-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
