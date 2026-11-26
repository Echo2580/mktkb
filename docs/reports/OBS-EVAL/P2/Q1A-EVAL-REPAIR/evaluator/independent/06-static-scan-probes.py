"""Q1a-1 独立验收探针 6：静态导入/调用/私有读取扫描（零真实调用证据的一部分）。

只读公开源文件并做 AST/正则扫描；不导入产品/网络/私有模块，不执行被测代码。
核对：模块导入白名单、无网络/provider/product/旧评测器导入、无 env/subprocess/eval、
唯一的文件写入为独占新建（"xb"）、私有材料关键词零命中或仅出现在 docstring。

运行（仓库根）：
  .venv/Scripts/python.exe <本文件>
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[7]
MODULE = ROOT / "backend" / "src" / "mktkb" / "evaluation" / "p2_evidence_rescore.py"
TEST = ROOT / "backend" / "tests" / "evaluation" / "test_p2_evidence_rescore.py"
CONTRACT = ROOT / "docs" / "evaluation" / "p2-evidence-rescore-v0_1.md"

RESULTS: list[dict[str, Any]] = []
FAILS: list[dict[str, Any]] = []


def check(probe: str, name: str, got: Any, want: Any) -> None:
    ok = got == want
    RESULTS.append({"probe": probe, "check": name, "got": got, "want": want, "pass": ok})
    if not ok:
        FAILS.append({"probe": probe, "check": name, "got": got, "want": want})


def dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted(node.value) + "." + node.attr
    return ""


def scan(path: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: list[str] = []
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            imports.append(base)
            imported_names.extend(alias.name for alias in node.names)
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            calls.append({"line": node.lineno, "callee": dotted(node.func)})
    constants = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "imports": sorted(set(imports)),
        "imported_names": sorted(set(imported_names)),
        "calls": calls,
        "string_constants": constants,
        "source": source,
    }


mod = scan(MODULE)
test = scan(TEST)
mod_imports = set(mod["imports"])
test_imports = set(test["imports"])

# --------------------------------------------------------------------------- #
# L1：模块导入白名单
# --------------------------------------------------------------------------- #
allowed = {"__future__", "collections", "collections.abc", "dataclasses", "hashlib",
           "json", "os", "pathlib", "re", "types", "typing"}
check("L1", "模块导入集合等于白名单", sorted(mod_imports), sorted(allowed))
forbidden = {"httpx", "requests", "urllib", "urllib3", "http.client", "socket", "openai",
             "mktkb.evaluation.p2_live", "mktkb.evaluation.product_adapter", "mktkb.rag",
             "mktkb.evaluation.p2_hard_evidence", "p2_hard_evidence"}
bad = sorted(name for name in mod_imports for item in forbidden
             if name == item or name.startswith(item + "."))
check("L1", "模块无网络/provider/product/旧评测器/私有模块导入", bad, [])
check("L1", "模块 os 调用仅 fsync（无 environ/getenv）",
      [c["callee"] for c in mod["calls"] if c["callee"].startswith("os.")], ["os.fsync"])

# --------------------------------------------------------------------------- #
# L2：危险调用 / 写入模式
# --------------------------------------------------------------------------- #
danger_prefixes = ("subprocess", "os.environ", "os.getenv", "socket.", "httpx.",
                   "requests.", "urllib.", "openai.")
danger_exact = {"eval", "exec", "__import__"}
danger_calls = [
    c for c in mod["calls"]
    if c["callee"] in danger_exact
    or any(c["callee"].startswith(prefix) for prefix in danger_prefixes)
]
check("L2", "模块无危险调用", danger_calls, [])

open_calls = [c for c in mod["calls"] if c["callee"].endswith(".open") or c["callee"] == "open"]
check("L2", "模块只有一处 open 调用", [c["callee"] for c in open_calls], ["target.open"])
source = mod["source"]
check("L2", 'open 调用使用独占新建模式 "xb"', 'target.open("xb")' in source, True)
for mode in ('"w"', '"a"', '"r"', '"rb"'):
    check("L2", f"模块无 {mode} 模式打开", mode in source, False)
check("L2", "模块无 read_text/read_string 等文本读取", "read_text" in source, False)
check("L2", "模块无 write_text 写入", "write_text" in source, False)
check("L2", "模块未导入 pytest", "pytest" in mod_imports, False)
check("L2", "模块无 monkeypatch.setattr 调用",
      [c for c in mod["calls"] if "monkeypatch" in c["callee"]], [])

# 模块唯一的内容读取是 file_sha256 的 read_bytes（合约/自身源文件哈希）
read_calls = [c for c in mod["calls"] if c["callee"].endswith("read_bytes")]
check("L2", "模块内容读取仅为 read_bytes（哈希校验）",
      all(item.endswith("read_bytes") for item in [c["callee"] for c in read_calls]) and len(read_calls) == 1,
      True)

# --------------------------------------------------------------------------- #
# L3：私有材料关键词
# --------------------------------------------------------------------------- #
private_pattern = re.compile(
    r"(?i)(?:\bH2\b|custody|cipher|private[_-]?key|\.env\b|live-ledger|P2-LIVE-GO|budget\.json|"
    r"api\.deepseek|tencentcloud|LOCAL-R1|docs/evidence)"
)


def private_hits(source_text: str) -> list[dict[str, Any]]:
    hits = []
    for lineno, line in enumerate(source_text.splitlines(), start=1):
        for match in private_pattern.finditer(line):
            hits.append({"line": lineno, "token": match.group(0), "text": line.strip()[:120]})
    return hits


mod_hits = private_hits(mod["source"])
test_hits = private_hits(test["source"])
check("L3", "模块源码私有材料关键词零命中", mod_hits, [])
print(json.dumps({"probe": "L3-note", "module_hits": mod_hits, "test_hits": test_hits}, ensure_ascii=False))

# 测试文件若出现私有词，只能来自 docstring/注释；不得是私有材料读取路径常量
private_paths = ("docs/evidence", "LOCAL-R1", "live-ledger", "P2-LIVE-GO", "budget.json",
                 "custody", "cipher")
check("L3", "测试无私有材料读取路径常量",
      [s for s in test["string_constants"] if any(token in s for token in private_paths)], [])

# --------------------------------------------------------------------------- #
# L4：测试端导入与零调用断言
# --------------------------------------------------------------------------- #
check("L4", "测试导入 netguard", any("netguard" in name for name in test_imports), True)
check("L4", "测试引用 t09_network_guard", "t09_network_guard" in test["imported_names"], True)
check("L4", "测试无 pytest.skip/xfail 装饰器",
      [n for n in ("skip", "xfail") if f"pytest.mark.{n}" in test["source"]], [])
check("L4", "测试无 assert True / or True",
      [t for t in ("assert True", "or True") if t in test["source"]], [])
check("L4", "测试仅对 product_adapter 做拦截断言（非旧评测器）",
      "monkeypatch.setattr(product_adapter" in test["source"], True)
check("L4", "测试未 monkeypatch p2_hard_evidence",
      any("monkeypatch.setattr" in line and "p2_hard_evidence" in line
          for line in test["source"].splitlines()), False)

payload = {
    "schema": "q1a1-independent-static-scan/v1",
    "module": {"path": mod["path"], "imports": mod["imports"], "open_calls": 1,
               "read_bytes_calls": len(read_calls), "private_hits": mod_hits},
    "test": {"path": test["path"], "imports": test["imports"],
             "private_hits": test_hits, "pytest_skip_or_xfail": False},
    "contract_sha256": hashlib.sha256(CONTRACT.read_bytes()).hexdigest(),
    "check_count": len(RESULTS),
    "failed_count": len(FAILS),
    "failures": FAILS,
    "checks": RESULTS,
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
raise SystemExit(0 if not FAILS else 2)
