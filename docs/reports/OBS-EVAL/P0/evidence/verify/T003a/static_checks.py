"""T003a 静态/结构检查（仓库外，只读仓库）：补充验收证据。"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
TRACER = REPO / "backend/src/mktkb/observability/tracer.py"
CONTRACTS = REPO / "backend/src/mktkb/observability/contracts.py"
INIT = REPO / "backend/src/mktkb/observability/__init__.py"
TESTS = REPO / "backend/tests/observability/test_tracer.py"

failures: list[str] = []
passes = 0


def check(cond: object, label: str) -> None:
    global passes
    if cond:
        passes += 1
        print(f"[PASS] {label}")
    else:
        failures.append(label)
        print(f"[FAIL] {label}")


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    check(proc.returncode == 0, f"git {' '.join(args)} exit=0")
    return proc.stdout


# ---- 1. 测试文件导入 / 硬约束 ----
test_source = TESTS.read_text(encoding="utf-8")
test_tree = ast.parse(test_source)
absolute_imports: set[str] = set()
relative_imports: set[str] = set()
for node in ast.walk(test_tree):
    if isinstance(node, ast.Import):
        absolute_imports.update(a.name.split(".")[0] for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        if node.level == 0:
            absolute_imports.add(node.module.split(".")[0])
        else:
            relative_imports.add("." * node.level + node.module)
allowed_test_top = set(sys.stdlib_module_names) | {"pytest", "mktkb"}
check(absolute_imports <= allowed_test_top, f"测试只 import 标准库/pytest/mktkb：{sorted(absolute_imports)}")
check(relative_imports == set(), f"测试无相对导入：{relative_imports}")
check("pytest" in absolute_imports, "使用 pytest")

def uses_os_environ(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv", "putenv"}:
            return True
        if isinstance(node, ast.Name) and node.id == "load_dotenv":
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "dotenv":
            return True
    return False


check(not uses_os_environ(test_tree), "测试不读环境变量/dotenv（AST）")
skip_markers = {
    "skip", "skipif", "xfail", "usefixtures",
}
decorator_texts = [
    ast.unparse(dec) for node in ast.walk(test_tree) if hasattr(node, "decorator_list")
    for dec in node.decorator_list  # type: ignore[attr-defined]
]
check(
    all(not (text.startswith("pytest.mark.") and text.split(".")[2].split("(")[0] in skip_markers)
        for text in decorator_texts),
    "测试无 skip/xfail 标记（AST）",
)
check("monkeypatch" not in test_source, "测试不 monkeypatch 生产代码")
check("os" not in absolute_imports, "测试不 import os（无法读 .env/环境）")
# 不把仓库路径当写入位置（避免 docstring 误伤，检查代码里的字面量路径）
check(
    re.search(r"""Path\(\s*["'](?:var|fixtures|docs|backend)[\\/]""", test_source) is None,
    "测试代码无仓库路径字面量写入",
)

# DB 只写 tmp_path：TraceRepository(...) 调用参数必须含 tmp_path
repo_calls = re.findall(r"TraceRepository\(([^)]*)\)", test_source)
check(len(repo_calls) >= 1, f"TraceRepository 调用数={len(repo_calls)}")
check(all("tmp_path" in args for args in repo_calls), f"TraceRepository 路径均来自 tmp_path：{repo_calls}")

# 无真实模型/OCR/embedding/rerank/网络调用
for token in ("build_gateway", "build_ocr_gateway", "embedding_query(", "rerank_documents(", "requests.", "httpx.", "socket."):
    check(token not in test_source, f"测试无真实调用：{token}")

# ---- 2. 测试数量（58 函数 / 66 用例声明）----
test_funcs = [
    node for node in test_tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
]
case_counts: dict[str, int] = {}
for node in test_tree.body:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    if not node.name.startswith("test_"):
        continue
    multiplier = 1
    for decorator in node.decorator_list:
        text = ast.unparse(decorator)
        if text.startswith("pytest.mark.parametrize"):
            argvalues = decorator.args[1]
            if isinstance(argvalues, (ast.List, ast.Tuple, ast.Set)):
                multiplier *= len(argvalues.elts)
            else:
                try:
                    multiplier *= len(ast.literal_eval(ast.unparse(argvalues)))
                except Exception:  # noqa: BLE001
                    multiplier *= -1
    case_counts[node.name] = multiplier
check(len(test_funcs) == 58, f"测试函数数=58（实际 {len(test_funcs)}）")
total_cases = sum(case_counts.values())
check(total_cases == 66, f"参数化后用例数=66（实际 {total_cases}）")
asserts = sum(
    1 for node in ast.walk(test_tree) if isinstance(node, ast.Assert)
) + sum(
    1
    for node in ast.walk(test_tree)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    and node.func.attr == "raises"
)
check(asserts >= 100, f"断言密度：assert/raises 共 {asserts} 处")
# 关键行为断言存在（非空转的最低结构证据，行为层面由变异探针覆盖）
for token, label in [
    ('assert record.status == "incomplete"', "断言 incomplete 行为"),
    ('assert record.status == "error"', "断言异常 status=error"),
    ('assert by_name["exact_recall"].parent_span_id == recall.span_id', "断言 parent_span_id 行为"),
    ("validate_required_spans(record", "调用完整性校验"),
    ("write_best_effort", "断言 finish 走 write_best_effort"),
]:
    check(token in test_source, f"测试包含关键断言：{label}")

# ---- 3. tracer 导入边界 ----
tracer_source = TRACER.read_text(encoding="utf-8")
tracer_tree = ast.parse(tracer_source)
abs_t: set[str] = set()
rel_t: set[str] = set()
for node in ast.walk(tracer_tree):
    if isinstance(node, ast.Import):
        abs_t.update(a.name.split(".")[0] for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        if node.level == 0:
            abs_t.add(node.module.split(".")[0])
        else:
            rel_t.add("." * node.level + node.module)
check(abs_t <= set(sys.stdlib_module_names), f"tracer 仅标准库导入：{sorted(abs_t)}")
check(rel_t <= {".contracts", ".store", ".versioning"}, f"tracer 相对导入受限：{rel_t}")
for token in ("os.environ", "load_dotenv", ".env", "eval(", "exec("):
    check(token not in tracer_source, f"tracer 无危险/违规片段：{token}")

# ---- 4. contracts.py 只末尾追加 ----
check(INIT.exists() and CONTRACTS.exists(), "交付文件存在")
numstat = git("diff", "--numstat", "2ac976f..dea4d5d")
for line in numstat.splitlines():
    added, deleted, path = line.split("\t")
    if path in {"backend/src/mktkb/observability/contracts.py", "backend/src/mktkb/observability/__init__.py"}:
        check(deleted == "0", f"{path} 纯新增（deleted={deleted}）")
contracts_diff = git("diff", "-U0", "2ac976f..dea4d5d", "--", "backend/src/mktkb/observability/contracts.py")
minus_lines = [
    line for line in contracts_diff.splitlines()
    if line.startswith("-") and not line.startswith("---")
]
check(minus_lines == [], f"contracts.py 无删除/修改行：{minus_lines}")
# 追加位置：旧文件最后一行为 __all__ 的闭括号，新函数在其后
old_contracts = subprocess.run(
    ["git", "show", "2ac976f:backend/src/mktkb/observability/contracts.py"],
    cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
).stdout
new_tail = CONTRACTS.read_text(encoding="utf-8")
check(old_contracts.rstrip() and new_tail.startswith(old_contracts.rstrip("\n") + "\n"), "contracts.py 前缀与旧文件一致（仅末尾追加）")
# __all__ 未被改：旧 __all__ 内容逐行仍存在
old_all = re.search(r"__all__ = \[(.*?)\]", old_contracts, re.S)
new_all = re.search(r"__all__ = \[(.*?)\]", new_tail, re.S)
check(old_all is not None and new_all is not None and old_all.group(1) == new_all.group(1), "contracts.py __all__ 未被修改")

# ---- 5. 受保护路径零改动 ----
protected = [
    "backend/src/mktkb/main.py",
    "backend/src/mktkb/config.py",
    "backend/src/mktkb/qa",
    "backend/src/mktkb/rag",
    "backend/src/mktkb/conversations",
    "backend/src/mktkb/observability/store.py",
    "backend/src/mktkb/observability/versioning.py",
    "backend/pyproject.toml",
    "backend/requirements.lock",
    "backend/requirements-dev.lock",
    "docs/evidence",
    "var",
    "fixtures",
]
changed_protected = git("diff", "--name-only", "2ac976f..dea4d5d", "--", *protected).strip()
check(changed_protected == "", f"受保护路径零改动：{changed_protected}")

# ---- 6. 既有测试零改动 ----
tests_changed = git("diff", "--name-status", "2ac976f..dea4d5d", "--", "backend/tests").strip()
check(tests_changed == "A\tbackend/tests/observability/test_tracer.py", f"仅新增 test_tracer.py：{tests_changed}")

# ---- 7. 提交边界：只允许 handoff §2 路径 ----
allowed_prefix = (
    "backend/src/mktkb/observability/tracer.py",
    "backend/src/mktkb/observability/__init__.py",
    "backend/src/mktkb/observability/contracts.py",
    "backend/tests/observability/test_tracer.py",
    "docs/reports/OBS-EVAL/P0/evidence/T003a/",
    ".claude/handoffs/T003a-tracer/report.md",
)
changed = [line.split("\t")[-1] for line in git("diff", "--name-status", "2ac976f..dea4d5d").splitlines() if line.strip()]
check(len(changed) == 12, f"commit 文件数=12（实际 {len(changed)}）")
check(all(any(p == c or c.startswith(p) for p in allowed_prefix) for c in changed), f"commit 路径均在 §2 允许范围：{changed}")
check(git("diff", "--diff-filter=D", "--name-only", "2ac976f..dea4d5d").strip() == "", "commit 无删除文件")
parent = git("rev-parse", "dea4d5d^").strip()
check(parent.startswith("2ac976f"), f"提交父=2ac976f（实际 {parent[:7]}）")
head = git("rev-parse", "HEAD").strip()
check(head.startswith("dea4d5d"), f"HEAD=dea4d5d（实际 {head[:7]}）")
branch = git("branch", "--show-current").strip()
check(branch == "p0/obs-eval", f"分支 p0/obs-eval（实际 {branch}）")

# ---- 8. 无新增依赖 ----
deps_changed = git(
    "diff", "--name-only", "2ac976f..dea4d5d", "--",
    "backend/pyproject.toml", "backend/requirements.lock", "backend/requirements-dev.lock",
).strip()
check(deps_changed == "", f"依赖清单零改动：{deps_changed}")

print(f"\nSTATIC-SUMMARY::pass={passes} fail={len(failures)} failures={failures}")
raise SystemExit(0 if not failures else 1)
