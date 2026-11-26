"""必测 9：测试质量 —— 独立执行 43 项，0 skip/xfail/恒真；固定码断言是否真钉到码。"""

from __future__ import annotations

import ast
import io
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from harness import Checks
from netguard import NetGuard, NetworkBlocked

from mktkb.evaluation.p2_evidence_axes_adapter_v2 import FIXED_CODES

REPO = Path(__file__).resolve().parents[8]
TESTS = REPO / "backend/tests/evaluation/test_p2_evidence_axes_adapter_v2.py"
OUT = Path(__file__).resolve().parent / "out"
CODE_SHAPE = re.compile(r"^[a-z][a-z0-9_]{5,}(:[a-zA-Z0-9_.\[\]]+)?$")


def run_pytest() -> dict[str, Any]:
    import pytest

    tempdir = Path(tempfile.mkdtemp(prefix="c1p4-pytest-"))
    junit = tempdir / "junit.xml"
    basetemp = tempdir / "basetemp"
    args = [
        str(TESTS),
        "-q",
        "-p",
        "no:cacheprovider",
        f"--basetemp={basetemp}",
        f"--junitxml={junit}",
        "--rootdir",
        str(REPO),
    ]
    buffer = io.StringIO()
    exit_code = 1
    with redirect_stdout(buffer):
        exit_code = pytest.main(args)
    text = buffer.getvalue()
    (OUT / "09-pytest.txt").write_text(text, encoding="utf-8")
    result: dict[str, Any] = {"exit_code": int(exit_code), "tempdir": str(tempdir), "stdout_tail": text[-4000:]}
    if junit.is_file():
        tree = ET.parse(junit)
        suites = tree.getroot()
        cases = suites.iter("testcase")
        rows = []
        for case in cases:
            skipped = case.find("skipped") is not None
            failure = case.find("failure") is not None or case.find("error") is not None
            rows.append({"name": case.get("name"), "classname": case.get("classname"),
                         "skipped": skipped, "failure": failure, "time": case.get("time")})
        result.update(
            {
                "test_count": len(rows),
                "failures": [row["name"] for row in rows if row["failure"]],
                "skipped": [row["name"] for row in rows if row["skipped"]],
                "cases": rows,
            }
        )
    return result


def ast_analysis() -> dict[str, Any]:
    source = TESTS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    test_functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")]
    markers: list[str] = []
    for node in test_functions:
        for decorator in node.decorator_list:
            markers.append(ast.get_source_segment(source, decorator) or "")
    module_markers = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
            module_markers.append(ast.get_source_segment(source, node) or "")

    asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
    constant_truthy = []
    fixed_literals: list[str] = []
    weak_membership: list[str] = []
    contexts = {"equality": 0, "membership": 0, "call_argument": 0, "other": 0}
    for node in asserts:
        segment = ast.get_source_segment(source, node) or ""
        if isinstance(node.test, ast.Constant) and bool(node.test.value):
            constant_truthy.append({"line": node.lineno, "text": segment})
        comparisons = [child for child in ast.walk(node) if isinstance(child, ast.Compare)]
        calls = [child for child in ast.walk(node) if isinstance(child, ast.Call)]
        for child in ast.walk(node):
            if not (isinstance(child, ast.Constant) and isinstance(child.value, str)):
                continue
            value = child.value
            if not (CODE_SHAPE.match(value) and (value in FIXED_CODES or value.split(":", 1)[0] in FIXED_CODES)):
                continue
            fixed_literals.append(value)
            in_equality = any(
                isinstance(op, (ast.Eq, ast.NotEq))
                and any(grand is child for grand in ast.walk(compare))
                for compare in comparisons
                for op in compare.ops
            )
            in_membership = any(
                isinstance(op, (ast.In, ast.NotIn))
                and any(grand is child for grand in ast.walk(compare))
                for compare in comparisons
                for op in compare.ops
            )
            in_call = any(any(grand is child for grand in ast.walk(call)) for call in calls)
            if in_equality:
                contexts["equality"] += 1
            elif in_membership:
                contexts["membership"] += 1
            elif in_call:
                contexts["call_argument"] += 1
            else:
                contexts["other"] += 1
        if "in FIXED_CODES" in segment:
            weak_membership.append({"line": node.lineno, "text": segment})

    known_literals = [value for value in fixed_literals if value.split(":", 1)[0] in FIXED_CODES]
    unknown_literals = sorted({value for value in fixed_literals if value.split(":", 1)[0] not in FIXED_CODES})

    raises = [ast.get_source_segment(source, node) or "" for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "raises"]
    monkeypatch = [ast.get_source_segment(source, node) or "" for node in ast.walk(tree)
                   if isinstance(node, ast.Name) and node.id == "monkeypatch"]

    return {
        "test_function_count": len(test_functions),
        "test_names": [node.name for node in test_functions],
        "markers": markers,
        "module_markers": module_markers,
        "assert_count": len(asserts),
        "constant_truthy_asserts": constant_truthy,
        "fixed_code_literal_count": len(fixed_literals),
        "fixed_code_literals_unique": sorted(set(known_literals)),
        "fixed_code_literal_unique_count": len(set(known_literals)),
        "non_fixed_code_literals": unknown_literals,
        "literal_contexts": contexts,
        "weak_membership_asserts": weak_membership,
        "pytest_raises_calls": raises,
        "monkeypatch_references": monkeypatch,
    }


def main() -> dict:
    checks = Checks("09-test-quality")
    guard = NetGuard().install()
    try:
        # 守卫活性正对照：先故意出站一次（被拦并记账），再清账跑套件
        blocked = False
        try:
            import socket as _socket

            _socket.getaddrinfo("example.invalid", 80)
        except NetworkBlocked:
            blocked = True
        checks.eq("guard_active_before_suite", blocked, True)
        guard.clear()
        result = run_pytest()
        external = guard.external()
        checks.eq("suite_external_attempts_zero", external, 0, guard.attempts)
    finally:
        guard.uninstall()

    analysis = ast_analysis()
    checks.eq("suite_test_count", result.get("test_count"), 43)
    checks.eq("suite_failures", result.get("failures"), [])
    checks.eq("suite_exit_code", result.get("exit_code"), 0)
    checks.eq("suite_skipped_count", len(result.get("skipped", [])), 0)
    checks.eq("declared_test_functions", analysis["test_function_count"], 43)
    checks.eq("no_skip_or_xfail_markers", [m for m in analysis["markers"] + analysis["module_markers"] if "skip" in m or "xfail" in m], [])
    checks.eq("no_constant_truthy_asserts", analysis["constant_truthy_asserts"], [])
    checks.eq("fixed_code_literals_all_known", analysis["non_fixed_code_literals"], [])
    checks.record(
        "fixed_code_assertion_count_at_least_dev_claim",
        analysis["fixed_code_literal_count"] >= 66,
        {"assert_literal_count": analysis["fixed_code_literal_count"], "unique": analysis["fixed_code_literal_unique_count"]},
    )
    checks.record(
        "asserts_are_not_only_membership",
        len(analysis["weak_membership_asserts"]) <= 3,
        {"weak": analysis["weak_membership_asserts"], "assert_total": analysis["assert_count"]},
    )
    checks.eq("no_monkeypatch_of_module_under_test", analysis["monkeypatch_references"], [])
    checks.record(
        "pytest_raises_used_with_codes",
        len(analysis["pytest_raises_calls"]) >= 1,
        {"count": len(analysis["pytest_raises_calls"])},
    )

    asserted_heads = {value.split(":", 1)[0] for value in analysis["fixed_code_literals_unique"]}
    return checks.write(
        {
            "pytest": {key: value for key, value in result.items() if key != "cases"},
            "ast": analysis,
            "external_attempts": external,
            "fixed_codes_total": len(FIXED_CODES),
            "fixed_codes_asserted_heads": sorted(asserted_heads),
            "fixed_codes_unasserted": sorted(FIXED_CODES - asserted_heads),
        }
    )


if __name__ == "__main__":
    main()
