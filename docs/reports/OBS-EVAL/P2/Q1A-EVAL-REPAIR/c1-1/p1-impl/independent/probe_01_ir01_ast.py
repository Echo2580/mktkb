"""IR-01 static audit: membership tests that could receive a non-hashable value.

Reconstructs the *old* failure mode (``value in frozenset``) from the AST and
classifies each site by whether the module guards the value before membership.
This is a static candidate list, not a verdict; probe_02 is the runtime oracle.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]
OUT = Path(__file__).resolve().parent / "out"

MODULES = {
    "adapter": "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py",
    "stale": "backend/src/mktkb/evaluation/p2_stale_version_state.py",
}

SAFE_CALLS = {"_enum_member", "_is_str", "_str_field", "isinstance", "str", "type"}


def _enclosing_function(tree: ast.AST) -> dict[int, str]:
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if hasattr(child, "lineno"):
                    owner.setdefault(child.lineno, node.name)
    return owner


def _source_has_guard(fn: ast.AST, expr: str, before_line: int) -> bool:
    """True when the same expression is guarded by _enum_member/_is_str/isinstance."""
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not hasattr(node, "lineno"):
            continue
        if node.lineno > before_line:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else ""
        )
        if name not in SAFE_CALLS:
            continue
        args = node.args
        if not args:
            continue
        first = args[0]
        # isinstance(value, str) / _is_str(value) / _enum_member(value, ...)
        if isinstance(first, ast.Name) and first.id == expr:
            if name in {"isinstance", "type"}:
                if len(args) >= 2 and isinstance(args[1], ast.Name) and args[1].id == "str":
                    return True
            return True
        if isinstance(first, ast.Call):
            inner = ast.unparse(first)
            if inner == expr:
                return True
    return False


def _last_assignment(fn: ast.AST, name: str, before_line: int) -> str | None:
    """Source of the last assignment to ``name`` before ``before_line``."""
    found: tuple[int, str] | None = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and hasattr(node, "lineno") and node.lineno < before_line:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    if found is None or node.lineno > found[0]:
                        found = (node.lineno, ast.unparse(node.value))
    return None if found is None else found[1]


def _input_derived(fn: ast.AST, expr: str, before_line: int) -> bool:
    """Heuristic: a bare name assigned from an input dict subscript / .get() call."""
    if not expr.isidentifier():
        return False
    origin = _last_assignment(fn, expr, before_line)
    if origin is None:
        return False
    return "[" in origin or origin.endswith(".get(") or ".get(" in origin


def main() -> int:
    report: dict = {"schema_version": "c1p1impl-ir01-ast/v0.1", "modules": {}}
    for label, rel in MODULES.items():
        path = ROOT / rel
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        owner = _enclosing_function(tree)
        sites: list[dict] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for op, comparator in zip(node.ops, node.comparators):
                if not isinstance(op, (ast.In, ast.NotIn)):
                    continue
                expr = ast.unparse(node.left)
                comp = ast.unparse(comparator)
                func_name = owner.get(node.lineno, "<module>")
                # Inside _enum_member the isinstance guard is explicit.
                if func_name == "_enum_member":
                    guarded = True
                    why = "inside _enum_member (isinstance(value, str))"
                elif _source_has_guard(
                    next(
                        (
                            fn
                            for fn in ast.walk(tree)
                            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and fn.name == func_name
                        ),
                        tree,
                    ),
                    expr,
                    node.lineno,
                ):
                    guarded = True
                    why = "same expression guarded by _enum_member/_is_str/isinstance earlier"
                elif _input_derived(
                    next(
                        (
                            fn
                            for fn in ast.walk(tree)
                            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and fn.name == func_name
                        ),
                        tree,
                    ),
                    expr,
                    node.lineno,
                ):
                    guarded = False
                    why = "name assigned from input subscript/.get(), no guard found"
                elif expr.startswith(("'", '"')) or expr[0].isdigit():
                    guarded = True
                    why = "literal"
                elif "[" in expr or "(" in expr or expr in {
                    "value",
                    "available",
                }:
                    guarded = False
                    why = "unguarded field/member expression"
                elif expr.startswith(("_", "self.")) or expr in {
                    "key",
                    "name",
                    "item",
                    "code",
                    "base",
                    "token",
                    "axis",
                    "determination.axis",
                    "determination.reason",
                    "self.axis",
                    "self.state",
                    "self.reason",
                    "self.evidence_grade",
                    "self.granularity",
                    "self.scenario_id",
                    "target.entity_key",
                    "record.entity_type",
                    "record.record_code",
                    "record.layers",
                    "row[",
                    "rest",
                }:
                    guarded = True
                    why = "internal/derived value (types validated upstream)"
                else:
                    guarded = False
                    why = "unclassified expression"
                sites.append(
                    {
                        "line": node.lineno,
                        "function": func_name,
                        "expression": expr,
                        "container": comp,
                        "guarded": guarded,
                        "why": why,
                        "source": src.splitlines()[node.lineno - 1].strip(),
                    }
                )
        report["modules"][label] = {
            "path": rel,
            "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
            "membership_sites": sites,
            "candidate_count": sum(1 for s in sites if not s["guarded"]),
            "candidates": [s for s in sites if not s["guarded"]],
        }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "01-ir01-ast.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    for label, row in report["modules"].items():
        print(f"== {label}: {row['candidate_count']} candidates of {len(row['membership_sites'])} sites")
        for site in row["candidates"]:
            print(f"  {site['line']:4d} {site['function']}: {site['expression']} in {site['container']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
