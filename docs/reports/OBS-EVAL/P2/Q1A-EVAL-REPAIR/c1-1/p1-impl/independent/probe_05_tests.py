"""Test-quality probe: 98 collected items, markers, assertion strength, code pinning."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
OUT = Path(__file__).resolve().parent / "out"
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_evidence_axes_adapter_v2 as adapter  # noqa: E402
from mktkb.evaluation import p2_stale_version_state as stale  # noqa: E402

FILES = {
    "stale_tests": "backend/tests/evaluation/test_p2_stale_version_state.py",
    "adapter_tests": "backend/tests/evaluation/test_p2_evidence_axes_adapter_v2.py",
}
CODES = {
    "stale_tests": set(stale.DETERMINATION_CODES),
    "adapter_tests": set(adapter.FIXED_CODES),
}
RETIRED = set(stale.RETIRED_CODES)


def _compare_context(tree: ast.AST, line: int, literal: str) -> str:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or node.lineno != line:
            continue
        operands = [node.left, *node.comparators]
        if not any(isinstance(item, ast.Constant) and item.value == literal for item in operands):
            continue
        ops = [type(op).__name__ for op in node.ops]
        return "compare:" + ",".join(ops)
    return "other"


def _is_truthy_assert(node: ast.Assert) -> bool:
    test = node.test
    if isinstance(test, ast.Compare):
        return False
    if isinstance(test, ast.Call):
        # pytest.raises / isinstance / any / all are meaningful calls.
        return False
    return True


def main() -> int:
    report: dict[str, Any] = {"schema_version": "c1p1impl-test-quality/v0.1", "files": {}}
    for label, rel in FILES.items():
        src = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
        test_functions = [
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        asserts = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
        # All fixed-code string literals in the test file and their assertion context.
        code_literals: dict[str, dict[str, int]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in CODES[label]:
                key = node.value
                code_literals.setdefault(key, {"occurrences": 0, "assert_contexts": {}})
                code_literals[key]["occurrences"] += 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(child.value, str) and child.value in CODES[label]:
                    key = child.value
                    context = _compare_context(tree, node.lineno, key)
                    code_literals.setdefault(key, {"occurrences": 0, "assert_contexts": {}})
                    code_literals[key]["assert_contexts"][context] = code_literals[key]["assert_contexts"].get(context, 0) + 1
        equality_pinned = set()
        membership_pinned = set()
        for code, row in code_literals.items():
            for context in row["assert_contexts"]:
                if context.startswith("compare:Eq") or context.startswith("compare:NotEq"):
                    equality_pinned.add(code)
                elif context.startswith("compare:In") or context.startswith("compare:NotIn"):
                    membership_pinned.add(code)
        weak_code_set_assertions = [
            line for line, text in enumerate(src.splitlines(), start=1)
            if re.search(r"in\s+(stale|adapter)\.(FIXED_CODES|DETERMINATION_CODES|PASS_CODES|VIOLATION_CODES)", text)
        ]
        monkeypatch_targets = [
            line for line, text in enumerate(src.splitlines(), start=1)
            if re.search(r"monkeypatch\.setattr\(\s*(stale|adapter)\b", text)
            or re.search(r"mock\.patch\([^)]*(stale|adapter)", text)
        ]
        skip_markers = [
            line for line, text in enumerate(src.splitlines(), start=1)
            if re.search(r"pytest\.mark\.(skip|xfail)|pytest\.(skip|xfail)\(", text)
        ]
        truthy_asserts = [node.lineno for node in asserts if _is_truthy_assert(node)]
        parametrize = len(re.findall(r"@pytest\.mark\.parametrize", src))
        raises = len(re.findall(r"pytest\.raises", src))
        # §12.2 forbidden real-dataset literals.
        forbidden_real = []
        for pattern in (r"\bD0[1-6]\b", r"\bV0[1-7]\b", r"2026-10-27", r"2026-10-28",
                        r"base_b0", r"pre_v05", r"post_v05"):
            if re.search(pattern, src):
                forbidden_real.append(pattern)
        report["files"][label] = {
            "path": rel,
            "test_functions": len(test_functions),
            "asserts": len(asserts),
            "compare_asserts": sum(1 for node in asserts if isinstance(node.test, ast.Compare)),
            "truthy_asserts": truthy_asserts,
            "skip_xfail_markers": skip_markers,
            "parametrize_decorators": parametrize,
            "pytest_raises": raises,
            "monkeypatch_target_module": monkeypatch_targets,
            "weak_fixed_code_membership": weak_code_set_assertions,
            "fixed_code_literals": len(code_literals),
            "fixed_codes_equality_pinned": len(equality_pinned),
            "fixed_codes_membership_only": sorted(membership_pinned - equality_pinned),
            "fixed_codes_not_asserted": sorted(CODES[label] - (equality_pinned | membership_pinned)),
            "retired_codes_named": sorted(RETIRED & set(code_literals)),
            "retired_codes_not_named": sorted(RETIRED - set(code_literals)),
            "forbidden_real_dataset_literals": forbidden_real,
        }
    # Content checks on the specific §7 table test.
    stale_src = (ROOT / FILES["stale_tests"]).read_text(encoding="utf-8")
    stale_tree = ast.parse(stale_src)
    expected_rows = None
    for node in ast.walk(stale_tree):
        if isinstance(node, ast.FunctionDef) and node.name == "test_section7_fourteen_row_table_matches_criterion":
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name) and target.id == "expected" and isinstance(child.value, ast.List):
                            expected_rows = len(child.value.elts)
    report["section7_expected_rows"] = expected_rows
    report["section7_row14_separate"] = "multi_turn" in stale_src and 'folded = _determine(_s7_grounding(), multi_turn)' in stale_src
    report["hostile_test_pins_exact_codes"] = "assert determination.reason ==" in stale_src.split("def test_hostile_non_scalar_inputs_never_raise", 1)[-1].split("def ", 1)[0]
    report["pytest_summary"] = "98 passed, 1 warning in 0.47s (out/05-pytest.txt)"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "05-test-quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
