"""v3 fix-1/A：planner 单轮多目标行为探针（纯函数，零真实调用）。

只调用产品 `mktkb.rag.query.parse_query`（rag 规划器）与
`mktkb.conversations.intent.parse_question`（legacy 意图层），
不建库、不检索、不调模型、不开端口、不发请求。
"""

from __future__ import annotations

import json
import socket
import sys
from typing import Any

from mktkb.conversations import intent as legacy_intent
from mktkb.conversations.service import _rag_owns_turn
from mktkb.rag.query import Lexicon, parse_query
from mktkb.rag.types import QueryState

OUTBOUND: list[str] = []


def _install_guard() -> None:
    def deny(*args: Any, **kwargs: Any) -> Any:
        OUTBOUND.append(f"connect:{args!r}")
        raise OSError("netguard: outbound blocked")

    socket.socket.connect = deny  # type: ignore[assignment]
    socket.socket.connect_ex = deny  # type: ignore[assignment]
    socket.create_connection = deny  # type: ignore[assignment]
    socket.getaddrinfo = deny  # type: ignore[assignment]


LEXICON = Lexicon(
    stores=("城东店", "城西店"),
    items=("宣传海报", "易拉宝"),
    field_labels=("位置",),
)
ENTITY_LEXICON = legacy_intent.EntityLexicon(
    store_labels=("城东店", "城西店"),
    item_labels=("宣传海报", "易拉宝"),
    alias_to_labels={},
)

QUESTIONS = {
    "Q1_single_target": "城东店的宣传海报在哪里？",
    "Q2_two_stores_one_item": "城东店和城西店的宣传海报在哪里？",
    "Q3_one_store_two_items": "城东店的宣传海报和易拉宝在哪里？",
    "Q4_two_stores_two_items": "城东店和城西店的宣传海报和易拉宝在哪里？",
    "Q5_two_stores_with_enumerate_word": "城东店和城西店的宣传海报分别在哪里？",
    "Q6_multi_target_no_field": "城东店和城西店的海报和易拉宝",
}


def _rag_row(question: str) -> dict[str, Any]:
    plan = parse_query(question, previous=None, lexicon=LEXICON, business_date="2026-10-15")
    return {
        "mode": plan.mode,
        "clarification": plan.clarification,
        "reason": plan.reason,
        "filters": dict(plan.filters),
        "field_role": plan.field_role,
        "enumerate": bool(plan.enumerate),
        "candidates": list(plan.candidates),
        "state_stores": list(plan.state.stores),
        "rag_owns_turn": bool(_rag_owns_turn(QueryState(), plan)),
    }


def _legacy_row(question: str) -> dict[str, Any]:
    plan = legacy_intent.parse_question(question, lexicon=ENTITY_LEXICON)
    return {
        "mode": plan.mode,
        "clarification": plan.clarification,
        "entities": dict(plan.entities),
        "requested_fields": list(plan.requested_fields),
        "filters": dict(plan.intent.entity_filters) if plan.intent is not None else None,
        "candidates": [label for label, _followup in plan.candidates],
    }


def main() -> int:
    _install_guard()
    rows = {}
    for name, question in QUESTIONS.items():
        rows[name] = {
            "question": question,
            "rag_planner": _rag_row(question),
            "legacy_intent": _legacy_row(question),
        }
    print(json.dumps({"rows": rows, "outbound_attempts": OUTBOUND}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
