"""v3-fix-1 §2a 顺带核：run2 ``MODEL_OUTPUT_INVALID(record_facts)`` 最小复现。

离线、纯函数：用产品自己的 ``service._facts`` + ``service._record_facts`` 重放
dryrun 的 ``echo-all`` 替身输出（``tools/p2_v3_mock_dryrun.py::build_chat``：
把证据行的**全部字段**用“；”拼成答案并引用全部来源 id），不建库、不调模型、不发请求。

两种形态：
- A 同一问字段同值出现在两条证据行（表格行 + 独立通知）：替身会把“位置：同值”回显两次；
- B 两条证据行同字段不同值（正常冲突前置会拦下，这里只看准入形态）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from mktkb.conversations import service
from mktkb.retrieval.index import resolve_requested_role

ROWS_SAME_VALUE = [
    SimpleNamespace(id="u-row-1", fields={"门店": "城东店", "物品": "宣传海报", "位置": "D区暂存柜"}),
    SimpleNamespace(id="u-row-2", fields={"门店": "城东店", "物品": "宣传海报", "位置": "D区暂存柜"}),
]
ROWS_DIFFERENT_VALUE = [
    SimpleNamespace(id="u-row-1", fields={"门店": "城东店", "物品": "宣传海报", "位置": "A区1号货架"}),
    SimpleNamespace(id="u-row-2", fields={"门店": "城西店", "物品": "易拉宝", "位置": "B区2号货架"}),
]


def echo_all(rows) -> str:
    """与 dryrun 替身同口径：全部行的全部字段，字段名：原值，用“；”连接。"""
    return "；".join(f"{key}：{value}" for row in rows for key, value in row.fields.items())


def _asked(facts) -> dict[str, str]:
    asked: dict[str, str] = {}
    for label, value in facts:
        role = resolve_requested_role(label)
        if role:
            asked.setdefault(role, value)
    return asked


def replay(rows) -> dict:
    facts, missing = service._facts(rows, ("位置",))
    text = echo_all(rows)
    validated = service._record_facts(text, rows, facts, object_label="", missing=missing)
    clauses = [part.strip() for part in service._RECORD_CLAUSE_SPLIT.split(text) if part.strip()]
    asked = _asked(facts)
    trail = []
    seen: list[str] = []
    for clause in clauses:
        found = service._match_record_clause(clause, rows, "", asked)
        action = "other"
        if found is not None:
            role = found[0]
            action = "duplicate_role" if role in seen else "matched"
            seen.append(role)
        elif service._is_echoed_other_field(clause, rows):
            action = "echoed_other_field"
        else:
            action = "unverifiable"
        trail.append({"clause": clause, "action": action})
    return {
        "echo_all_text": text,
        "facts": facts,
        "record_facts_result": validated,
        "product_outcome": "answer" if validated else "MODEL_OUTPUT_INVALID(record_facts)",
        "clause_trail": trail,
    }


def main() -> int:
    print(
        json.dumps(
            {
                "shape_A_same_value_twice": replay(ROWS_SAME_VALUE),
                "shape_B_different_values": replay(ROWS_DIFFERENT_VALUE),
                "cause": (
                    "echo-all 替身把**每条证据行的全部字段**回显；同字段同值在两行里各出现一次时，"
                    "第二条同角色分句命中 _record_facts 的 `if role in seen: return None`，"
                    "整段被判不可验证 → 产品抛 ModelOutputInvalid → MODEL_OUTPUT_INVALID(record_facts)。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
