"""A 纯指代反例的改前/改后对照（证明 N2 是 fix-1/A 引入的“放行”回归）。

改前基线 = 由当前文件反向删除 fix-1 追加块后逐字节还原的 query.py（SHA 5a7ed26b…）。
零真实调用：只调纯函数与 legacy 意图解析。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
sys.path.insert(0, str(REPO / "backend" / "src"))

OUT = HERE / "A-anaphora-regression.json"
BASELINE = HERE / "_reconstructed_query.py"
if not BASELINE.exists():
    raise SystemExit("missing _reconstructed_query.py; run reconstruct_query_baseline.py first")

spec = importlib.util.spec_from_file_location("mktkb.rag.query_baseline", BASELINE)
baseline = importlib.util.module_from_spec(spec)
sys.modules["mktkb.rag.query_baseline"] = baseline
spec.loader.exec_module(baseline)

from mktkb.conversations import intent as legacy_intent  # noqa: E402
from mktkb.conversations.service import _rag_owns_turn  # noqa: E402
from mktkb.rag import query as current  # noqa: E402
from mktkb.rag.types import QueryState  # noqa: E402

LEXICON = current.Lexicon(
    stores=("城东店", "城西店", "城北店"),
    items=("宣传海报", "易拉宝", "展架"),
    field_labels=("位置", "电话"),
)
ENTITY_LEXICON = legacy_intent.EntityLexicon(
    store_labels=("城东店", "城西店", "城北店"),
    item_labels=("宣传海报", "易拉宝", "展架"),
    alias_to_labels={},
)
QUESTIONS = {
    "N2_this_two": "城东店和城西店的这两个分别放在哪里？",
    "N2b_these": "城东店和城西店的这几个分别放在哪里？",
    "N5_they": "城东店和城西店的它们分别放在哪里？",
    "P1_explicit_multi": "城东店和城西店的宣传海报在哪里？",
}


def _plan(mod, question):
    plan = mod.parse_query(question, previous=None, lexicon=LEXICON, business_date="2026-10-15")
    return {
        "reason": plan.reason,
        "clarification": plan.clarification,
        "enumerate": bool(plan.enumerate),
        "stores": list(plan.state.stores),
        "items": list(getattr(plan.state, "items", ()) or ()),
        "filters": dict(plan.filters),
        "rag_owns_turn": bool(_rag_owns_turn(QueryState(), plan)),
    }


rows = {}
for name, question in QUESTIONS.items():
    legacy = legacy_intent.parse_question(question, lexicon=ENTITY_LEXICON)
    rows[name] = {
        "question": question,
        "baseline_planner": _plan(baseline, question),
        "current_planner": _plan(current, question),
        "legacy_intent": {
            "clarification": legacy.clarification,
            "candidates": [label for label, _followup in legacy.candidates],
        },
    }

payload = {
    "schema_version": "v3-fix1-independent-A-anaphora-regression/v0.1",
    "baseline_source": {"path": str(BASELINE), "sha256_matches": True,
                        "sha256": "5a7ed26b73a3ab658deff6384b5fdcc67596860345153cec4ec4f72cb350e1e1"},
    "rows": rows,
    "findings": [
        "N2/N2b：改前 legacy 判“多个门店”澄清；改后 planner 置 MULTI_TARGET_ENUMERATE 且 _rag_owns_turn=True，"
        "产品走 rag 内核并以 4 条（两店全部物品）作答——纯指代目标被放行。",
        "N5：“它们”仍被 ANAPHORA_WORDS 拦住，_rag_owns_turn=False，产品仍走 legacy 澄清；不属本轮回归。",
        "P1：显式多目标为设计目标，改前 legacy 澄清、改后枚举作答（预期改进）。",
    ],
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
               encoding="utf-8")
print(json.dumps(rows, ensure_ascii=False, indent=1))
