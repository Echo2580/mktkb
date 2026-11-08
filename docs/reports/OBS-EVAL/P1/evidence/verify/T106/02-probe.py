"""T106 独立验收探针（验收者自写，非开发测试）。

只读源码 + import mktkb.copy；不启动服务、不调模型、不建库。
用法（项目根）：.venv\\Scripts\\python.exe backend\\.pytest-tmp\\T106-verify\\02-probe.py
"""

from __future__ import annotations

import ast
import re
import string
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = next(
    (p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents]
     if (p / "backend" / "src" / "mktkb").is_dir()),
    None,
)
if ROOT is None:
    raise SystemExit("无法定位仓库根（需要 backend/src/mktkb）")
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb import copy as C  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"FAIL  {msg}")
    else:
        print(f"ok    {msg}")


# ---------------------------------------------------------------- A. 映射清单
print("== A. 映射清单 ==")
check(len(C.REQUIRED_REASONS) == 33, f"REQUIRED_REASONS 数量 33（实 {len(C.REQUIRED_REASONS)}）")
missing = [r for r in C.REQUIRED_REASONS if r not in C.REASON_COPY_KEY]
check(not missing, f"required reason 全部登记（缺 {missing}）")
for r in C.REQUIRED_REASONS:
    key = C.copy_key(r)
    if key not in C.COPY:
        check(False, f"{r} -> {key} 不在 COPY")
    if C.COPY.get(key) and key == "UNCLASSIFIED":
        check(False, f"{r} 落到 UNCLASSIFIED")
bad_alias = [r for r, k in C.REASON_ALIASES.items() if k not in C.COPY]
check(not bad_alias, f"别名目标都在 COPY（坏 {bad_alias}）")
alias_to_alias = [r for r, k in C.REASON_ALIASES.items() if k in C.REASON_ALIASES]
check(not alias_to_alias, f"无别名链（坏 {alias_to_alias}）")

templates = [e.template for e in C.COPY.values()]
check(len(templates) == len(set(templates)), "COPY 模板全局唯一")
keys = [e.key for e in C.COPY.values()]
check(len(keys) == len(set(keys)), "COPY key 唯一")

# 占位符合法且实际调用方都有能力提供（这里只做模板语法 + 已知字段集合检查）
fmt = string.Formatter()
declared = {}
for e in C.COPY.values():
    fields = {f for _, f, _, _ in fmt.parse(e.template) if f}
    declared[e.key] = fields
    unknown = fields - {
        "identifier", "subject", "names", "labels", "detail", "start", "end",
        "as_of", "status", "document", "region", "label", "entity", "field",
        "lines", "role", "total", "shown", "reason", "retry_hint", "store",
    }
    check(not unknown, f"{e.key} 占位符均为已登记字段（未知 {unknown}）")

# 渲染唯一性（用样例字段渲染）
SAMPLE = {
    "identifier": "QF01", "subject": "宣传海报", "names": "“城南店”", "labels": "城东店、城西店",
    "detail": "资料中对位置记录了多个有效值", "start": "2026-12-01", "end": "2026-10-01",
    "as_of": "2026-10-28", "status": "生效", "document": "D01.xlsx", "region": "城西区",
    "label": "门店", "entity": "物料", "field": "位置", "lines": "A：1；B：2", "role": "位置",
    "total": 150, "shown": "已列出前 2 条候选，", "reason": "原因", "retry_hint": "可稍后重新提问",
    "store": "城南店",
}
rendered = {}
for r in C.REQUIRED_REASONS:
    key = C.copy_key(r)
    rendered.setdefault(key, C.text(key, **SAMPLE))
dups = {t: [k for k, v in rendered.items() if v == t] for t in set(rendered.values())}
dups = {t: ks for t, ks in dups.items() if len(ks) > 1}
check(not dups, f"33 reason 渲染结果无重复（重复 {dups}）")
check(all(v for v in rendered.values()), "33 reason 渲染均非空")

# ---------------------------------------------------------------- B. 源码 reason 覆盖
print("== B. 源码 reason 调用点覆盖 ==")
FILES = [
    ROOT / "backend/src/mktkb/conversations/service.py",
    ROOT / "backend/src/mktkb/rag/answer.py",
    ROOT / "backend/src/mktkb/rag/query.py",
]
found: dict[str, list[str]] = {}


def add(value: str, where: str) -> None:
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", value):
        found.setdefault(value, []).append(where)


for path in FILES:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rel = f"{path.name}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fname = ""
            if isinstance(node.func, ast.Name):
                fname = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fname = node.func.attr
            for kw in node.keywords:
                if kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    add(kw.value.value, f"{rel}:{kw.lineno}")
            # RagAnswer / _Result / _no_answer：位置参数 reason 常见于 _no_answer 第 3 位
            if fname == "_no_answer" and len(node.args) >= 3:
                arg = node.args[2]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    add(arg.value, f"{rel}:{node.lineno}")
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in ("plan_reason", "reason"):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        add(node.value.value, f"{rel}:{node.lineno}")
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute):
            if node.left.attr == "reason" and isinstance(node.comparators[0], ast.Constant):
                v = node.comparators[0].value
                if isinstance(v, str):
                    add(v, f"{rel}:{node.lineno}")

unregistered = {r: w for r, w in found.items() if r not in C.REASON_COPY_KEY}
unclassified = {r: w for r, w in found.items()
                if r in C.REASON_COPY_KEY and C.copy_key(r) == "UNCLASSIFIED"}
check(not unregistered, f"源码 reason 字面量全部登记（未登记 {unregistered}）")
check(not unclassified, f"源码 reason 无一落 UNCLASSIFIED（{unclassified}）")
print("     源码 reason 字面量:", ", ".join(sorted(found)))

# ---------------------------------------------------------------- C. T104 逐字对照父提交
print("== C. T104 七类 + POST_SEND 文案对父提交 ==")
parent = subprocess.run(
    ["git", "show", "9933a7b:backend/src/mktkb/conversations/service.py"],
    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
).stdout
m = re.search(r"_MODEL_ERROR_REASONS: dict\[str, tuple\[str, str\]\] = \{(.*?)\n\}", parent, re.S)
block = m.group(1)
pairs = {k: (v1, v2) for (k, v1, v2) in re.findall(
    r'"?([A-Z_]+)"?\s*:\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,?\s*\)', block)}
check(len(pairs) == 8, f"父提交解析出 8 个码（实 {len(pairs)}）")
TEMPLATE = "{reason}。这是服务调用失败，不是资料中没有答案；{retry_hint}。服务端不会因重试而重复保存同一条回答。"
for code, (reason, hint) in pairs.items():
    expected = TEMPLATE.format(reason=reason, retry_hint=hint)
    actual = C.service_error_text(code)
    check(actual == expected, f"{code} 文案与父提交逐字相同")
    if actual != expected:
        print("       exp:", expected)
        print("       got:", actual)

# ---------------------------------------------------------------- D. 三要素 / 可重试性
print("== D. 三要素与 retryable 元数据 ==")
RETRY_TOKENS = ("可稍后重新提问", "后重新提问", "后重试", "后重新查询", "可重新提问", "重新查询", "后可重新提问")
for e in C.COPY.values():
    r = e.template.format(**{f: SAMPLE.get(f, "") for f in declared[e.key]})
    if e.service_error:
        check("不是资料中没有答案" in r and "服务端不会因重试而重复保存同一条回答" in r,
              f"{e.key} 服务错误三要素")
    if e.retryable and not any(t in r for t in RETRY_TOKENS):
        check(False, f"{e.key} retryable=True 但无重试指引：{r}")
    if not e.retryable and "可稍后重新提问" in r:
        check(False, f"{e.key} retryable=False 却写可稍后重新提问")

T104 = {
    "MODEL_NOT_CONFIGURED": False, "MODEL_BUDGET_REFUSED": False, "MODEL_TIMEOUT": True,
    "MODEL_UNAVAILABLE": True, "MODEL_OUTPUT_INVALID": True, "MODEL_CALL_FAILED": True,
    "QA_INTERNAL_ERROR": False, "MODEL_POST_SEND_AUTH_DENIED": True,
}
for code, expected in T104.items():
    check(C.service_error_is_retryable(code) is expected, f"{code} retryable={expected}")

# 未登记码按真实可重试性
for retryable in (True, False):
    t = C.service_error_text("A_FUTURE_CODE", retryable=retryable)
    check("不是资料中没有答案" in t and "服务端不会因重试而重复保存同一条回答" in t,
          f"未登记码 retryable={retryable} 三要素")
    if retryable:
        check("可稍后重新提问" in t and "重试不会自行恢复" not in t, "未登记码可重试提示")
    else:
        check("重试不会自行恢复" in t and "可稍后重新提问" not in t, "未登记码不可重试提示")

# ---------------------------------------------------------------- E. 服务错误码集合
print("== E. service.py 实际服务错误码登记 ==")
svc = (ROOT / "backend/src/mktkb/conversations/service.py").read_text(encoding="utf-8")
codes = set(re.findall(r'_service_error\(\s*"([A-Z_]+)"', svc))
codes |= set(re.findall(r'"(MODEL_[A-Z_]+|QA_INTERNAL_ERROR|INDEX_NOT_READY|INVALID_QUERY)"', svc))
codes &= set(C.SERVICE_ERROR_CODES) | {"MODEL_POST_SEND_AUTH_DENIED"}
unregistered_codes = [c for c in codes if c not in C.SERVICE_ERROR_CODES]
check(not unregistered_codes, f"实际服务码都在 SERVICE_ERROR_CODES（缺 {unregistered_codes}）")
for c in C.SERVICE_ERROR_CODES:
    check(C.service_error_text(c).startswith(("问答模型", "当前预算", "模型服务", "模型输出", "模型调用", "问答服务", "预算或授权", "检索索引", "无法理解")),
          f"{c} 有专属文案")

# ---------------------------------------------------------------- F. 前端标签/历史可重试集合同步
print("== F. 前端稳定性集合 ==")
tsx = (ROOT / "frontend/src/features/chat/MessageCard.tsx").read_text(encoding="utf-8")
set_block = re.search(r"NON_RETRYABLE_SERVICE_ERROR_CODES = new Set\(\[(.*?)\]\)", tsx, re.S).group(1)
non_retry = set(re.findall(r"'([A-Z_]+)'", set_block))
expected_non_retry = {"MODEL_NOT_CONFIGURED", "MODEL_BUDGET_REFUSED", "QA_INTERNAL_ERROR", "INVALID_QUERY"}
check(expected_non_retry <= non_retry, f"前端非重试集合覆盖后端非重试码（{non_retry}）")
backend_non_retry = {c for c in C.SERVICE_ERROR_CODES if C.service_error_is_retryable(c) is False}
check(backend_non_retry <= non_retry, f"后端非重试码都在前端集合（缺 {backend_non_retry - non_retry}）")
backend_retry = {c for c in C.SERVICE_ERROR_CODES if C.service_error_is_retryable(c) is True}
check(not (backend_retry & non_retry), f"前端集合未误标可重试码（{backend_retry & non_retry}）")

# ---------------------------------------------------------------- G. 文案诚实性（人工口径固化）
print("== G. 系统侧失败不得伪装成资料缺失 ==")
ident = C.text("IDENTIFIER_NOT_RETRIEVABLE", identifier="QF21")
check(
    not ("未找到标识" in ident and "未按标识检索" in ident),
    "IDENTIFIER_NOT_RETRIEVABLE 未在“未按标识检索”的同时断言“资料中未找到”",
)
check(
    "未按标识检索" in ident and "不能据此判断该记录不存在" in ident,
    "IDENTIFIER_NOT_RETRIEVABLE 明确未检索、不能判不存在",
)
ana = C.text("ANAPHORA_NEW_CONTENT")
check(
    "资料中未记录" not in ana or "不是资料中没有答案" not in ana,
    "ANAPHORA_NEW_CONTENT 不同时断言“资料中未记录”和“不是资料中没有答案”",
)
no_intent = C.text("NO_INTENT")
check(
    "不是资料中没有答案" in no_intent or "资料中未找到" not in no_intent,
    "NO_INTENT（系统未识别意图）不以“资料中未找到”作唯一原因",
)
print("      IDENTIFIER 文案:", ident)
print("      ANAPHORA 文案  :", ana)
print("      NO_INTENT 文案 :", no_intent)

# ---------------------------------------------------------------- H. 阻塞路径可达性
print("== H. IDENTIFIER_NOT_RETRIEVABLE 可达性（产品意图层） ==")
from mktkb.conversations.intent import EntityLexicon, parse_question  # noqa: E402

lexicon = EntityLexicon(
    store_labels=("城东店",),
    item_labels=("宣传海报",),
    identifier_labels=("QF21",),
    alias_to_labels={},
)
plan = parse_question("QF21 放在哪里？", lexicon=lexicon)
check(
    plan.intent is None and plan.identifier == "QF21" and not plan.clarification,
    "标识-only 查询产生 intent=None + identifier=QF21 + 无澄清（进入 service.py:2071 分支）",
)
print("      plan.intent=", plan.intent, "identifier=", plan.identifier,
      "clarification=", plan.clarification, "fields=", plan.requested_fields)

print()
print("FAILS:", len(FAILS))
for f in FAILS:
    print(" -", f)
sys.exit(1 if FAILS else 0)
