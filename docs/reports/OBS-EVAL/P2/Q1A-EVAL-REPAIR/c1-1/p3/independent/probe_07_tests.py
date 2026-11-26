"""C1-P3 独立验收探针 7/7：测试质量（26 项是否有 skip/xfail/恒真，断言是否钉到字段级）。

- 实际执行：pytest 26 项，禁用 cache、basetemp 放仓外、禁写 pyc；
- 静态扫描：skip/xfail/恒真断言/monkeypatch 被测模块/断言粒度；
- 码覆盖：开发测试里实际出现的固定码 vs 49 码表。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = next(
    parent
    for parent in HERE.parents
    if (parent / "backend" / "src" / "mktkb").is_dir() and (parent / "docs").is_dir()
)
TEST = REPO / "backend/tests/evaluation/test_p2_evidence_snapshot_v03.py"

sys.path.insert(0, str(HERE))

from mktkb.evaluation.p2_evidence_snapshot_v03 import FAIL_CLOSED_CODES  # noqa: E402


def main() -> int:
    basetemp = Path(tempfile.mkdtemp(prefix="c1p3-pytest-"))
    env = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(REPO / "backend" / "tests") + ";" + str(REPO / "backend" / "src"),
    }
    import os

    run_env = {**os.environ, **env}
    completed = subprocess.run(
        [
            str(REPO / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "pytest",
            str(TEST),
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(basetemp),
            "-rsx",
        ],
        cwd=REPO / "backend",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=run_env,
    )
    collect = subprocess.run(
        [
            str(REPO / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "pytest",
            str(TEST),
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO / "backend",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=run_env,
    )
    text = TEST.read_text(encoding="utf-8")
    test_names = re.findall(r"^def (test_[a-zA-Z0-9_]+)\(", text, flags=re.MULTILINE)
    bodies = re.split(r"^def (test_[a-zA-Z0-9_]+)\(", text, flags=re.MULTILINE)
    per_test: list[dict] = []
    for index in range(1, len(bodies), 2):
        name, body = bodies[index], bodies[index + 1]
        asserts = re.findall(r"^\s*assert\s", body, flags=re.MULTILINE)
        exact_codes = re.findall(r"snapshot_[a-z0-9_]+:", body)
        per_test.append(
            {
                "name": name,
                "asserts": len(asserts),
                "fixed_code_with_path": len(exact_codes),
            }
        )
    always_true = re.findall(r"assert\s+(?:True|1|not False|bool\(True\))", text)
    skips = re.findall(r"(pytest\.(?:skip|xfail)|@pytest\.mark\.(?:skip|xfail))", text)
    monkeypatch = re.findall(r"monkeypatch|unittest\.mock|MagicMock|patch\(", text)
    codes_in_tests = sorted(set(re.findall(r"snapshot_[a-z0-9_]+", text)))
    code_families_in_tests = sorted(
        {code for code in codes_in_tests if code in FAIL_CLOSED_CODES}
    )
    test_codes_not_in_table = sorted(
        {code for code in codes_in_tests if code.startswith("snapshot_") and code not in FAIL_CLOSED_CODES}
    )
    result = {
        "probe": "test-quality",
        "pytest": {
            "exit_code": completed.returncode,
            "tail": (completed.stdout + completed.stderr).strip().splitlines()[-3:],
            "skipped_or_xfail_markers": skips,
            "collected": [
                line.strip()
                for line in collect.stdout.splitlines()
                if line.strip().startswith("test_") or "tests collected" in line
            ][:3],
        },
        "static": {
            "test_functions": len(test_names),
            "assert_statements": sum(item["asserts"] for item in per_test),
            "tests_without_assert": [item["name"] for item in per_test if item["asserts"] == 0],
            "tests_with_fixed_code_path_assertion": sum(
                1 for item in per_test if item["fixed_code_with_path"] > 0
            ),
            "per_test": per_test,
            "always_true_assertions": always_true,
            "mock_or_patch_usage": monkeypatch,
            "code_families_referenced": len(code_families_in_tests),
            "codes_referenced": code_families_in_tests,
            "codes_in_tests_not_in_table": test_codes_not_in_table,
            "has_coverage_assertion_for_49_codes": bool(
                re.search(r"assert\s+len\((?:code_families|FAIL_CLOSED_CODES|OBSERVED_CODES)\)", text)
                or "coverage" in text
            ),
        },
        "verdict": None,
    }
    result["verdict"] = "PASS" if (
        completed.returncode == 0
        and len(test_names) == 26
        and not skips
        and not always_true
        and not monkeypatch
        and not result["static"]["tests_without_assert"]
    ) else "FAIL"
    (HERE / "out" / "07-test-quality.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "pytest": {
                    "exit_code": completed.returncode,
                    "tail": result["pytest"]["tail"],
                    "collect": result["pytest"]["collected"],
                },
                "static": {
                    key: result["static"][key]
                    for key in (
                        "test_functions",
                        "assert_statements",
                        "tests_without_assert",
                        "tests_with_fixed_code_path_assertion",
                        "always_true_assertions",
                        "mock_or_patch_usage",
                        "code_families_referenced",
                        "codes_in_tests_not_in_table",
                        "has_coverage_assertion_for_49_codes",
                    )
                },
                "verdict": result["verdict"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
