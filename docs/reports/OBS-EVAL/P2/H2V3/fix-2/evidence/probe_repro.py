"""fix-2 复现探针（改前 / 改后同一脚本、同一输入）。

只调产品纯函数：``mktkb.rag.query.parse_query``、``mktkb.conversations.service._rag_owns_turn``。
不建库、不检索、不调模型 —— 零真实调用。

字典/资料标题按 v3 ingest 的实际命名形态构造（`D01_物品位置表.xlsx` 等），
`doc_id` 按产品运行期形态（`str(document.id)` = UUID 字符串）构造。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
#: 允许指向“改前重建”的临时源码树（``run_prestate_probe.py`` 用）；默认用工作区源码。
sys.path.insert(0, os.environ.get("P2_FIX2_SRC") or str(REPO / "backend" / "src"))

from mktkb.conversations.service import _rag_owns_turn  # noqa: E402
from mktkb.rag.query import DocumentRef, Lexicon, parse_query  # noqa: E402
from mktkb.rag.types import QueryState  # noqa: E402

LEXICON = Lexicon(
    stores=("城东店", "城西店"),
    items=("宣传海报", "展架", "价签卡纸"),
    products=(),
    field_labels=("位置", "联系人", "电话", "地址"),
    documents=(
        DocumentRef(doc_id="3f1f9a6e-2f4d-4c7a-9b3d-0a1b2c3d4e01", title="D01_物品位置表.xlsx"),
        DocumentRef(doc_id="7c2e8b1a-9d3f-4a5b-8c6d-1e2f3a4b5c02", title="D02_合作店家信息.xlsx"),
        DocumentRef(doc_id="b5a4c3d2-1e0f-4a9b-8c7d-6e5f4a3b2c03", title="V07_物料位置独立通知.pdf"),
    ),
)

# --- A 类：信息足够（2 店 × 1 物品 + 记录字段角色），却混入“资料/通知”字样或回指词
A_INSUFFICIENT = (
    "城东店和城西店的价签卡纸那个位置，按店家资料确认一下",
    "城东店和城西店的价签卡纸那个位置在D01和D02里分别是多少",
    "城东店和城西店的价签卡纸那个位置和门店联系电话是多少，按店家资料一起给我",
)
# --- A 类反例：真歧义（必须仍澄清）
A_AMBIGUOUS = (
    "城东店和城西店的价签卡纸和宣传海报分别放在哪里",
    "城东店和城西店的这两个分别放在哪里",
    "城东店和城南店的这两个分别放在哪里",
    "城东店和城南店的价签卡纸那个位置在哪里",
)

# --- B 类：语料有答案（首轮、显式门店+物品），却因“回指新内容”直接判未记录
B_ANSWERABLE = (
    "城东店的展架那个陈列规矩是怎么定的",
    "城东店的宣传海报那个上架节奏如何安排",
)
# --- B 类反例：语料确实无覆盖（首轮、显式门店+物品，但该店无该物品记录）
B_UNCOVERED = (
    "城北店的展架那个陈列规矩是怎么定的",
)


def _sig(question: str, previous: QueryState | None = None, business_date: str = "2026-10-15") -> dict:
    plan = parse_query(question, previous=previous, lexicon=LEXICON, business_date=business_date)
    return {
        "question": question,
        "mode": plan.mode,
        "reason": plan.reason,
        "clarification_present": plan.clarification is not None,
        "enumerate": bool(plan.enumerate),
        "filters": dict(plan.filters),
        "field_role": plan.field_role,
        "field_roles": list(plan.field_roles),
        "stores": list(plan.state.stores),
        "items": list(plan.state.items),
        "rag_owns_turn": _rag_owns_turn(QueryState(), plan),
    }


def main() -> int:
    groups = {
        "A_insufficient": A_INSUFFICIENT,
        "A_ambiguous": A_AMBIGUOUS,
        "B_answerable": B_ANSWERABLE,
        "B_uncovered": B_UNCOVERED,
    }
    out = {name: [_sig(q) for q in questions] for name, questions in groups.items()}
    # B 类第二轮回指（必须仍按“未记录”收口，不能被本轮修复放开）
    first = parse_query(B_ANSWERABLE[0], previous=None, lexicon=LEXICON, business_date="2026-10-15")
    out["B_followup_collapse"] = [
        _sig("城东店的展架那个打印材质呢", previous=first.state, business_date="2026-10-15")
    ]
    path = sys.argv[1] if len(sys.argv) > 1 else "repro-pre.json"
    target = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(target)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
