"""独立验收探针：_conflict_values_text 的通用渲染行为（不落产品代码，仅调用）。"""
import sys, uuid
sys.path.insert(0, "backend/src")
from mktkb.conversations.service import _conflict_values_text, MAX_DISCLOSED_CONFLICT_VALUES
from mktkb.conversations.schemas import ConflictEntry, ConflictView

def view(field, *values):
    return ConflictView(field=field, entries=[ConflictEntry(value=v, source_id=uuid.uuid4()) for v in values])

cases = [
    ("single-field/2", [view("位置", "B区1号货架第二层", "D区暂存柜")]),
    ("multi-field", [view("位置", "甲", "乙"), view("电话", "1", "2")]),
    ("whitespace-fold+dedupe", [view("位置", "A  区", "A 区", " A\t区 ")]),
    ("exactly-8", [view("字段F", *[f"值{i}" for i in range(8)])]),
    ("9-values", [view("字段F", *[f"值{i}" for i in range(9)])]),
    ("12-values", [view("字段F", *[f"值{i}" for i in range(12)])]),
    ("empty-entries", [view("位置")]),
    ("blank-values", [view("位置", "   ", "")]),
    ("newline-value", [view("位置", "第一行\n第二行", "单值")]),
]
print("MAX_DISCLOSED_CONFLICT_VALUES =", MAX_DISCLOSED_CONFLICT_VALUES)
for name, conflicts in cases:
    text = _conflict_values_text(conflicts)
    print(f"{name}: {text!r}")
# 顺序稳定性：同一输入重复 20 次结果必须一致
same = view("位置", "乙", "甲", "丙")
outs = {_conflict_values_text([same]) for _ in range(20)}
print("deterministic:", len(outs) == 1, outs)
# 不含任何题面/文档名/答案常量
src = open("backend/src/mktkb/conversations/service.py", encoding="utf-8").read()
for token in ("B区1号货架第二层", "D区暂存柜", "010-00000001", "010-00000099", "城东店", "C05", "C06", "V01", "D01"):
    print(f"service.py contains {token!r}:", token in src)
