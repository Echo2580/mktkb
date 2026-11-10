"""T106 R2 独立复验探针（验收者自写，非开发测试）。

只读源码 / git 对象 + import mktkb.copy / mktkb.conversations.intent；
不启动服务、不建库、不调真实模型。

用法（仓库根）：
  .venv\\Scripts\\python.exe backend\\.pytest-tmp\\T106-R2\\02-probe.py
"""

from __future__ import annotations

import ast
import re
import string
import subprocess
import sys
import types
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
from mktkb.conversations import intent as I  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"FAIL  {msg}")
    else:
        print(f"ok    {msg}")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout


SAMPLE = {
    "identifier": "QF21", "subject": "宣传海报", "names": "“城南店”",
    "labels": "城东店、城西店", "detail": "资料中对位置记录了多个有效值。",
    "start": "2026-12-01", "end": "2026-10-01", "as_of": "2026-10-28",
    "status": "生效", "document": "D01.xlsx", "region": "城西区",
    "label": "门店", "entity": "物料", "field": "位置", "lines": "A：1；B：2",
    "role": "位置", "total": 150, "shown": "已列出前 2 条候选，",
    "reason": "原因", "retry_hint": "可稍后重新提问", "store": "城南店",
}


def render(key: str) -> str:
    entry = C.COPY[key]
    names = {n for _, n, _, _ in string.Formatter().parse(entry.template) if n}
    return entry.template.format(**{n: SAMPLE.get(n, "X") for n in names})


MATERIAL_CLAIMS = ("资料中未找到", "资料中未记录", "资料中没有", "未收录该资料", "资料中未收录")
NEGATED = ("不是资料中没有答案", "不能据此判断资料中没有答案")
SERVICE_CLAIMS = ("服务调用失败", "服务不可用", "系统故障")


def strip_negations(text: str) -> str:
    for phrase in NEGATED:
        text = text.replace(phrase, "［否定］")
    return text


# ---------------------------------------------------------------- A. B1 文案
print("== A. B1 IDENTIFIER_NOT_RETRIEVABLE 文案 ==")
ident = C.text("IDENTIFIER_NOT_RETRIEVABLE", identifier="QF21")
check(C.COPY["IDENTIFIER_NOT_RETRIEVABLE"].material_related is False,
      "B1 material_related=False")
check("未按标识检索" in ident, "B1 明确写出“未按标识检索”")
check("不能据此判断该记录不存在" in ident, "B1 明确“不能据此判断该记录不存在”")
check("不是资料中没有答案" in ident, "B1 含“不是资料中没有答案”")
check("资料中未找到" not in ident, "B1 不含“资料中未找到”")
check("资料中未记录" not in ident, "B1 不含“资料中未记录”")
check("资料中没有" not in strip_negations(ident), "B1 剥离否定句后不含“资料中没有”")
check("未找到标识" not in ident, "B1 不再出现“未找到标识”式无据结论")
check("门店" in ident and "物品" in ident, "B1 自救指引含门店/物品")
check(("重新查询" in ident) or ("联系管理员" in ident), "B1 自救指引含重试/管理员")
check("未执行标识查询" in ident, "B1 明说系统未执行标识查询")
print("      B1:", ident)

# ---------------------------------------------------------------- B. B1 可达性
print("== B. B1 可达性（parse_question + service 分支） ==")
lexicon = I.EntityLexicon(
    store_labels=("城东店",), item_labels=("宣传海报",),
    identifier_labels=("QF21",), alias_to_labels={},
)
plan = I.parse_question("QF21 放在哪里？", lexicon=lexicon)
check(plan.intent is None, "标识-only 查询 intent=None")
check(plan.identifier == "QF21", "标识-only 查询 identifier=QF21")
check(not plan.unknown_identifier, "标识-only 查询无 unknown_identifier")
check(not plan.clarification, "标识-only 查询无澄清")
print("      plan:", f"intent={plan.intent} identifier={plan.identifier!r}",
      f"unknown={plan.unknown_identifier!r} clarification={plan.clarification!r}",
      f"fields={plan.requested_fields}")

svc = (ROOT / "backend/src/mktkb/conversations/service.py").read_text(encoding="utf-8")
svc_lines = svc.splitlines()
id_line = next(i for i, s in enumerate(svc_lines, 1) if '"IDENTIFIER_NOT_RETRIEVABLE"' in s)
no_intent_line = next(i for i, s in enumerate(svc_lines, 1) if '"NO_INTENT"' in s)
parse_line = next(i for i, s in enumerate(svc_lines, 1)
                  if "plan = intent_module.parse_question(" in s)
check(id_line < no_intent_line,
      f"service 分支顺序：IDENTIFIER({id_line}) 先于 NO_INTENT({no_intent_line})")
check(parse_line < id_line, f"parse_question({parse_line}) 先于 IDENTIFIER 分支({id_line})")
check("产品检索层没有标识筛选键" in svc,
      "service 注释确认产品检索层没有标识筛选键（未检索依据）")

# parse 与 IDENTIFIER 分支之间不应出现检索调用。
id_branch_line = next(i for i, s in enumerate(svc_lines, 1)
                      if s.strip() == "if plan.identifier:")
svc_tree = ast.parse(svc)
calls = []
for node in ast.walk(svc_tree):
    if isinstance(node, ast.Call) and parse_line <= node.lineno < id_branch_line:
        f = node.func
        name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
        calls.append(name)
retrieval_like = [n for n in calls if re.search(r"retriev|search|lookup|fetch|answer|qa", n, re.I)]
check(not retrieval_like,
      f"parse→IDENTIFIER 分支之间无检索调用（calls={sorted(set(calls))}）")

# ---------------------------------------------------------------- C. B2 文案/可达性
print("== C. B2 NO_INTENT 文案与可达性 ==")
no_intent = C.text("NO_INTENT")
check(C.COPY["NO_INTENT"].material_related is False, "B2 material_related=False")
check("没有识别出" in no_intent and "查询意图" in no_intent, "B2 说明未识别查询意图")
check("资料中未找到" not in no_intent, "B2 不含“资料中未找到”")
check("资料中没有" not in strip_negations(no_intent), "B2 剥离否定句后不含“资料中没有”")
check("不是资料中没有答案" in no_intent, "B2 含“不是资料中没有答案”")
check("请补充" in no_intent and ("门店" in no_intent or "物品" in no_intent),
      "B2 自救指引含补充门店/物品")
print("      B2:", no_intent)

intent_src = Path(I.__file__).read_text(encoding="utf-8")
tree = ast.parse(intent_src)
guarded: list[tuple[int, set[str]]] = []
for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    f = node.func
    name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
    if name != "IntentPlan":
        continue
    kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
    intent_kw = kwargs.get("intent")
    if isinstance(intent_kw, ast.Constant) and intent_kw.value is None:
        blockers = {
            k for k in ("unknown_identifier", "identifier", "clarification")
            if k in kwargs and not (isinstance(kwargs[k], ast.Constant) and not kwargs[k].value)
        }
        guarded.append((node.lineno, blockers))
check(bool(guarded), f"intent.py 存在 intent=None 的 IntentPlan（{len(guarded)} 处）")
check(all(b for _, b in guarded),
      f"所有 intent=None 计划均带非空阻断字段（{guarded}）")
print("      intent=None 计划:", guarded)

# 动态抽样：无阻断字段的 intent=None 不应出现。
samples = ["今天天气怎么样？", "你好", "", "随便问问", "城东店的宣传海报在哪里？",
           "QF21 放在哪里？", "宣传海报", "数量"]
unsafe = []
for q in samples:
    try:
        p = I.parse_question(q, lexicon=lexicon)
    except Exception as exc:  # noqa: BLE001
        print(f"      parse_question({q!r}) raised {exc!r}")
        continue
    if p.intent is None and not (p.unknown_identifier or p.identifier or p.clarification):
        unsafe.append((q, p))
check(not unsafe, f"动态抽样未见无阻断的 intent=None（{unsafe}）")

# ---------------------------------------------------------------- D. B3 文案/调用点
print("== D. B3 ANAPHORA_NEW_CONTENT 文案与调用点 ==")
ana = C.text("ANAPHORA_NEW_CONTENT")
check(C.COPY["ANAPHORA_NEW_CONTENT"].material_related is False, "B3 material_related=False")
check("资料中未记录" not in ana, "B3 不含“资料中未记录”")
check(("资料中未记录" not in ana) or ("不是资料中没有答案" not in ana),
      "B3 不再同时断言“资料中未记录”与“不是资料中没有答案”")
check("不属于台账字段" in ana, "B3 说明新内容不属于台账字段")
check("不是资料中没有答案" in ana, "B3 含“不是资料中没有答案”")
check("请指定" in ana and "重新提问" in ana, "B3 自救指引含指定字段后重试")
print("      B3:", ana)

answer_src = (ROOT / "backend/src/mktkb/rag/answer.py").read_text(encoding="utf-8")
check('plan.reason == "ANAPHORA_NEW_CONTENT"' in answer_src
      and 'copy_module.text("ANAPHORA_NEW_CONTENT")' in answer_src,
      "B3 调用点 rag/answer.py 直接渲染 copy 文本（可达）")

# ---------------------------------------------------------------- E. 机械诚实性
print("== E. 机械诚实性规则（全部 COPY） ==")
bad_false: list[tuple[str, str]] = []
bad_true: list[tuple[str, str]] = []
for entry in C.COPY.values():
    txt = render(entry.key)
    if not entry.material_related:
        stripped = strip_negations(txt)
        for claim in MATERIAL_CLAIMS:
            if claim in stripped:
                bad_false.append((entry.key, claim))
    else:
        for claim in SERVICE_CLAIMS:
            if claim in txt:
                bad_true.append((entry.key, claim))
check(not bad_false, f"material_related=False 均无资料侧结论（坏 {bad_false}）")
check(not bad_true, f"material_related=True 均不称服务失败（坏 {bad_true}）")
for key in ("IDENTIFIER_NOT_RETRIEVABLE", "NO_INTENT", "ANAPHORA_NEW_CONTENT"):
    txt = render(key)
    check("不是资料中没有答案" in txt, f"{key} 明说不是资料中没有答案")
    check(any(t in txt for t in ("请", "重新", "联系管理员")), f"{key} 有自救/重试指引")

# 机械测试是否真的覆盖规则（源码 AST 断言，不依赖测试名口头声明）。
test_src = (ROOT / "backend/tests/unit/test_p1_t106_copy.py").read_text(encoding="utf-8")
test_tree = ast.parse(test_src)
test_names = {n.name for n in ast.walk(test_tree) if isinstance(n, ast.FunctionDef)}
required = {
    "test_material_related_false_copy_never_asserts_material_absence",
    "test_material_related_true_copy_never_claims_service_failure",
    "test_identifier_not_retrievable_copy_is_honest",
    "test_identifier_not_retrievable_path_is_reachable_and_renders_honest_text",
    "test_no_intent_copy_is_honest",
    "test_anaphora_new_content_copy_is_honest",
    "test_no_intent_branch_is_guarded_by_current_intent_plans",
}
check(required <= test_names, f"R1 诚实性测试齐全（缺 {required - test_names}）")
check("for entry in copy_module.COPY.values()" in test_src,
      "机械规则测试遍历全部 COPY 条目")
check("MATERIAL_SIDE_CLAIMS" in test_src and "SERVICE_FAILURE_CLAIMS" in test_src,
      "机械规则测试使用显式资料侧/服务侧断言清单")
check("_without_negated_claims" in test_src, "机械规则测试先剥离允许的否定句")

# ---------------------------------------------------------------- F. T104 逐字不变
print("== F. T104 七类 + POST_SEND 对 9933a7b 逐字 ==")
parent_svc = git("show", "9933a7b:backend/src/mktkb/conversations/service.py")
m = re.search(r"_MODEL_ERROR_REASONS: dict\[str, tuple\[str, str\]\] = \{(.*?)\n\}", parent_svc, re.S)
check(bool(m), "父提交存在 _MODEL_ERROR_REASONS")
pairs = {k: (v1, v2) for (k, v1, v2) in re.findall(
    r'"?([A-Z_]+)"?\s*:\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,?\s*\)', m.group(1))}
check(len(pairs) == 8, f"父提交解析出 8 个码（实 {len(pairs)}）")
TEMPLATE = ("{reason}。这是服务调用失败，不是资料中没有答案；{retry_hint}。"
            "服务端不会因重试而重复保存同一条回答。")
for code, (reason, hint) in pairs.items():
    expected = TEMPLATE.format(reason=reason, retry_hint=hint)
    actual = C.service_error_text(code)
    check(actual == expected, f"{code} 文案与 T104 定稿逐字相同")
    if actual != expected:
        print("       exp:", expected)
        print("       got:", actual)

# 本 R1 只应改三条目：直接加载 a42ee48 的 copy.py 比较 COPY 映射。
old_src = git("show", "a42ee48:backend/src/mktkb/copy.py")
old_mod = types.ModuleType("old_copy_t106")
old_mod.__dict__["__name__"] = "old_copy_t106"
sys.modules["old_copy_t106"] = old_mod
exec(compile(old_src, "a42ee48:copy.py", "exec"), old_mod.__dict__)
old_keys = set(old_mod.COPY)
cur_keys = set(C.COPY)
changed = {
    k for k in old_keys | cur_keys
    if k not in old_keys or k not in cur_keys
    or old_mod.COPY[k].template != C.COPY[k].template
}
check(changed == {"IDENTIFIER_NOT_RETRIEVABLE", "NO_INTENT", "ANAPHORA_NEW_CONTENT"},
      f"R1 copy.py 仅三条目文案变化（实 {sorted(changed)}）")
meta_changed = {
    k for k in old_keys & cur_keys
    if (old_mod.COPY[k].material_related, old_mod.COPY[k].retryable,
        old_mod.COPY[k].requires_user_input)
    != (C.COPY[k].material_related, C.COPY[k].retryable, C.COPY[k].requires_user_input)
}
check(meta_changed <= {"NO_INTENT", "ANAPHORA_NEW_CONTENT"},
      f"元数据仅 B2/B3 的 material_related 变化（实 {sorted(meta_changed)}）")
for key in changed:
    print(f"      diff-key {key}: old material_related={old_mod.COPY[key].material_related}"
          f" -> new {C.COPY[key].material_related}")

# ---------------------------------------------------------------- G. 不变项（schema/kind）
print("== G. 结构不变项 ==")
check(git("diff", "a42ee48..972f508", "--", "backend/src/mktkb/conversations/schemas.py") == "",
      "schemas.py 在 R1 无 diff")
check(git("diff", "cb602b2..972f508", "--", "backend/src/mktkb/conversations/schemas.py") == "",
      "schemas.py 在 R1 父提交后无 diff")
from mktkb.conversations import schemas as S  # noqa: E402
ask_names = list(S.AskResult.model_fields)
msg_names = list(S.MessageView.model_fields)
check(len(ask_names) == 12, f"AskResult 12 字段（实 {len(ask_names)}：{ask_names}）")
check(set(S.ResultKind.__args__) == {"answer", "clarification", "not_found", "conflict",
                                     "service_error", "knowledge_changed"},
      f"ResultKind 集合不变（{list(S.ResultKind.__args__)}）")
print("      AskResult:", ask_names)
print("      MessageView:", msg_names)

# ---------------------------------------------------------------- H. 前端 P2 + 既有修正
print("== H. 前端文案与徽标 ==")
fmt = (ROOT / "frontend/src/utils/format.ts").read_text(encoding="utf-8")
card = (ROOT / "frontend/src/features/chat/MessageCard.tsx").read_text(encoding="utf-8")
check("INVALID_QUERY: '查询条件问题'" in fmt, "P2 徽标 INVALID_QUERY=查询条件问题")
check("resultBadgeLabel(kind, candidates.length, errorCode)" in card,
      "P2 徽标调用传入 errorCode")
check("errorCode === 'INVALID_QUERY'" in card and "这是查询条件问题" in card,
      "P2 历史提示 INVALID_QUERY 与正文一致")
check("该历史消息未保存候选明细" not in card, "既有修正：不再出现“历史消息未保存候选明细”")
check("需补充条件" in fmt and "需要确认" in fmt, "既有修正：无候选/有候选标签仍在")

print()
print("FAILS:", len(FAILS))
for f in FAILS:
    print(" -", f)
sys.exit(1 if FAILS else 0)
