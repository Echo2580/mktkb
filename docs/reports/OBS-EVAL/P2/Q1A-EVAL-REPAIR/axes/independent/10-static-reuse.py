#!/usr/bin/env python
"""探针 10：真复用 matcher v2 + 静态导入白名单 + 冻结 hash（独立验收自建）。

只读：评测器源码、契约文件、测试文件；不读 H2/私有密文/key/.env。
输出：10-static-reuse.out.json
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from _common import HERE, ROOT, expect, dump, rescore, axes, ref, unit, version_binding

SRC = ROOT / "backend" / "src" / "mktkb" / "evaluation" / "p2_evidence_rescore_axes.py"
BASE = ROOT / "backend" / "src" / "mktkb" / "evaluation" / "p2_evidence_rescore.py"
TEST = ROOT / "backend" / "tests" / "evaluation" / "test_p2_evidence_rescore_axes.py"
FROZEN = ROOT / "backend" / "src" / "mktkb" / "evaluation" / "p2_hard_evidence.py"

FORBIDDEN_IMPORTS = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "urllib.request",
    "requests",
    "httpx",
    "aiohttp",
    "openai",
    "anthropic",
    "subprocess",
    "multiprocessing",
    "ctypes",
    "cryptography",
    "base64",
    "pickle",
    "shutil",
    "tempfile",
    "mktkb.rag",
    "mktkb.providers",
    "p2_hard_evidence",
    "mktkb.evaluation.p2_hard_evidence",
    "product_adapter",
    "p2_live",
}


def imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                names.append("." * node.level + module)
            else:
                names.append(module)
    return names


def forbidden(names: list[str]) -> list[str]:
    hits: list[str] = []
    for name in names:
        stripped = name.lstrip(".")
        for bad in FORBIDDEN_IMPORTS:
            if stripped == bad or stripped.startswith(bad + "."):
                hits.append(name)
                break
    return hits


def matcher_matrix() -> list[dict]:
    """同一组 (ref, unit, binding) 在两个模块入口上必须给出逐值相同结论。"""
    combos = []
    refs = [
        ref(),
        ref(doc_code="D02"),
        ref(record_code="P02"),
        ref(record_code=None),
        ref(unit_key="sheet:物品位置:row:8"),
        ref(unit_key="sheet:其他:row:1"),
        ref(locator={"sheet": "物品位置", "row": 8}),
        ref(locator={"sheet": "物品位置", "row": 9}),
        {"doc_code": "D01", "record_code": "P01", "locator": {"row": 8}},
    ]
    units = [
        unit("u1"),
        unit("u2", record_code=None),
        unit("u3", unit_key="sheet:物品位置:row:8"),
        unit("u4", locator={"sheet": "物品位置", "row": 9}),
        unit("u5", doc_code=None),
        unit("u6", version_id=None, version_number=None),
    ]
    bindings = [
        version_binding("ver-2", 2),
        version_binding("ver-1", 1),
        rescore.VersionBinding(basis="unresolved"),
        None,
    ]
    for r in refs:
        for u in units:
            for b in bindings:
                left = axes.match_ref_to_unit(r, u, version_binding=b)
                right = rescore.match_ref_to_unit(r, u, version_binding=b)
                combos.append(
                    {
                        "ref": r,
                        "unit": u.unit_id,
                        "binding": None if b is None else {"version_id": b.version_id, "number": b.version_number, "basis": b.basis},
                        "axes": [left.verdict, left.code],
                        "rescore": [right.verdict, right.code],
                        "equal": (left.verdict, left.code) == (right.verdict, right.code),
                    }
                )
    return combos


def main() -> int:
    checks: list[dict] = []

    def check(label: str, ok: bool, detail: object = None) -> None:
        checks.append({"label": label, "ok": bool(ok), "detail": detail})
    src_tree = ast.parse(SRC.read_text(encoding="utf-8"))
    test_tree = ast.parse(TEST.read_text(encoding="utf-8"))

    src_names = imports_of(SRC)
    test_names = imports_of(TEST)
    checks.append(expect(forbidden(src_names) == [], f"module imports clean: {forbidden(src_names)}"))
    checks.append(expect(forbidden(test_names) == [], f"test imports clean: {forbidden(test_names)}"))
    checks.append(
        expect(
            all(
                (name.startswith(".") and name in {".p2_evidence_rescore"})
                or name.split(".")[0]
                in {
                    "hashlib",
                    "json",
                    "os",
                    "re",
                    "collections",
                    "dataclasses",
                    "datetime",
                    "pathlib",
                    "types",
                    "typing",
                    "__future__",
                }
                for name in src_names
            ),
            f"module import whitelist: {sorted(set(src_names))}",
        )
    )

    # 不得自带 matcher 副本 / 不得 import C 冻结评测器
    top_defs = {
        node.name
        for node in src_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    checks.append(expect("match_ref_to_unit" not in top_defs, "module defines no local match_ref_to_unit"))
    checks.append(
        expect(
            not any("p2_hard_evidence" in name for name in src_names + test_names),
            "no p2_hard_evidence import in module/test",
        )
    )

    # 测试内唯一被 import 的 product 模块必须只在“零调用负向控制”里，且不进入实现
    nested_product: list[str] = []
    for node in ast.walk(test_tree):
        if isinstance(node, ast.FunctionDef) and node.name == "test_rescore_axes_run_makes_zero_external_calls":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Import):
                    nested_product.extend(alias.name for alias in inner.names)
    checks.append(
        expect(
            nested_product == ["mktkb.evaluation.product_adapter"],
            f"product_adapter import confined to zero-call test: {nested_product}",
        )
    )
    checks.append(
        expect(
            "product_adapter" not in SRC.read_text(encoding="utf-8")
            and "ProductEvalAdapter" not in SRC.read_text(encoding="utf-8"),
            "module source never references product adapter",
        )
    )
    checks.append(expect("ref_key" not in top_defs and "ref_key" in axes.__all__, "ref_key re-exported not redefined"))

    # 函数对象同一性：axes 暴露的 matcher 必须就是 Q1a-1 的对象
    checks.append(expect(axes.match_ref_to_unit is rescore.match_ref_to_unit, "matcher function identity"))

    combos = matcher_matrix()
    checks.append(expect(all(item["equal"] for item in combos), f"matcher matrix equal ({len(combos)} combos)"))

    # 语义区分：若 matcher 退化为“忽略 doc_code/版本”，下列探针会从 unknown 变 passed
    from _common import (
        annotation,
        case,
        cross_entity_contract,
        cross_entity_view,
        scope_target,
        state,
    )

    target_refs = [{"collection": "expected_sources", "index": 0}]
    base_ann = dict(target_refs=target_refs, targets=[{"entity_type": "item", "entity_key": "K1", "filters": {}}])
    common_ev = dict(units=(unit("u1"),), bindings={"run_id": "SYN-RUN-Q1A1B", "plan_id": "SYN-PLAN-Q1A1B", "plan_sha256": "c" * 64})

    def entity_case(ref_payload: dict, binding) -> tuple[str, str]:
        view = case(
            anns={"cross_entity": annotation("cross_entity", **base_ann)},
            cross_entity=cross_entity_view(**common_ev),
            cross_entity_contract=cross_entity_contract(
                targets=(scope_target("item", "K1"),),
                refs={"expected_sources": (ref_payload,)},
                version_bindings={rescore.ref_key(ref_payload): binding},
            ),
        )
        return state(view, "cross_entity")

    checks.append(expect(entity_case(ref(), version_binding()) == ("passed", "frozen_targets_match_ok"), "identity match -> passed"))
    checks.append(
        expect(
            entity_case(ref(doc_code="D02"), version_binding())[0] == "unknown",
            "doc mismatch -> unknown (v2 doc_code-aware, would pass if matcher ignored doc)",
        )
    )
    checks.append(
        expect(
            entity_case(ref(record_code="P02"), version_binding())[0] == "unknown",
            "record mismatch -> unknown",
        )
    )
    checks.append(
        expect(
            entity_case(ref(), version_binding("ver-1", 1))[0] == "unknown",
            "version mismatch -> unknown",
        )
    )
    checks.append(
        expect(
            entity_case(ref(locator={"sheet": "物品位置", "row": 9}), version_binding())[0] == "unknown",
            "locator mismatch -> unknown",
        )
    )

    # 测试质量：无 skip/xfail、无恒真断言
    asserts = [node for node in ast.walk(test_tree) if isinstance(node, ast.Assert)]
    check("test has >= 200 assert statements", len(asserts) >= 200, len(asserts))

    def always_true(node: ast.AST) -> bool:
        if isinstance(node, ast.Constant) and node.value is True:
            return True
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            return any(always_true(value) for value in node.values)
        return False

    tautologies = [item for item in asserts if always_true(item.test)]
    check("no tautological assert (True / ... or True)", tautologies == [], len(tautologies))

    skips: list[str] = []
    for node in ast.walk(test_tree):
        if isinstance(node, ast.Attribute) and node.attr in {"skip", "skipif", "xfail"}:
            skips.append(node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"skip", "xfail"}:
            skips.append(f"call:{node.func.attr}")
    check("no pytest skip/xfail usage", skips == [], skips)
    test_functions = [node for node in test_tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
    check("test functions all have a body with assert", all(any(isinstance(stmt, ast.Assert) for stmt in ast.walk(node)) for node in test_functions), len(test_functions))

    # 冻结 hash
    frozen = {
        "p2_evidence_rescore.py": rescore.file_sha256(BASE),
        "p2_hard_evidence.py": rescore.file_sha256(FROZEN),
        "p2_evidence_rescore_axes.py": rescore.file_sha256(SRC),
        "test_p2_evidence_rescore_axes.py": rescore.file_sha256(TEST),
    }
    checks.append(
        expect(
            frozen["p2_hard_evidence.py"].startswith("fba6e606"),
            "p2_hard_evidence.py == fba6e606…",
        )
    )
    checks.append(
        expect(
            frozen["p2_evidence_rescore.py"].startswith("d8260256"),
            "p2_evidence_rescore.py == d8260256…",
        )
    )

    failures = [item for item in checks if not item["ok"]]
    payload = {
        "probe": "10-static-reuse",
        "checks_total": len(checks),
        "checks_failed": len(failures),
        "checks": checks,
        "matcher_matrix_size": len(combos),
        "matcher_matrix_mismatches": [item for item in combos if not item["equal"]],
        "frozen_sha256": frozen,
        "module_imports": sorted(set(src_names)),
        "test_imports": sorted(set(test_names)),
        "verdict": "PASS" if not failures else "FAIL",
    }
    dump(HERE / "10-static-reuse.out.json", payload)
    print(json.dumps({"verdict": payload["verdict"], "failed": failures}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
