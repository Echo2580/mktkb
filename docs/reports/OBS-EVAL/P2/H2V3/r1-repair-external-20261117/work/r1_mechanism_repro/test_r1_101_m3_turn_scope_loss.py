"""R1-101 / M3：多回合里门店范围丢失 → 后一回合跨门店列出记录（cross_entity 的入口）。

机制出处：``R1-BASELINE.md`` §5 C13 → ``mktkb/rag/query.py`` 的 ``parse_query``/``_new_state``
（回合重置把 ``state.store``/``state.stores`` 清空；``filters`` 由 ``state`` 派生）。

合成序列（假数据，门店 甲店/乙店，物品 立牌，位置 甲区/乙区）：
1. 回合 1「甲店的立牌位置在哪？」→ ``filters={store:甲店, item:立牌}``（对照，绿）；
2. 回合 2「陈列要求有哪些？」→ 无实体、无字段的换话题轮次，当前实现把 filters 清空；
3. 回合 3「立牌放在哪？」→ 当前 ``filters={item:立牌}``（store 丢失），门店范围无从继承。

运行：``.venv\\Scripts\\python.exe -B -m pytest <本文件> -q -p no:cacheprovider``
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

for _root in Path(__file__).resolve().parents:
    if (_root / "backend" / "src").is_dir():
        sys.path.insert(0, str(_root / "backend" / "src"))
        break

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402

STORES = (("D-syn-m3-a", "甲店", "甲区", 7), ("D-syn-m3-b", "乙店", "乙区", 7))
TURN_SCOPE = "甲店的立牌位置在哪？"
TURN_TOPIC = "陈列要求有哪些？"


def _add(index: RagIndex, doc_id: str, store: str, location: str, row: int) -> None:
    fields = {"门店": store, "物品": "立牌", "位置": location}
    doc = DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"corpus/synthetic-{doc_id}.xlsx",
        title="合成物品资料",
        file_kind="xlsx",
        version_id=f"V-{doc_id}",
        version_label="当前",
        sha256=hashlib.sha256(doc_id.encode()).hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    unit = AtomicUnit(
        unit_id=f"U-{doc_id}-row{row}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key=f"sheet:合成表:row:{row}",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=fields,
        sheet="合成表",
        locator={
            "sheet": "合成表",
            "row": row,
            "header_row": 6,
            "cells": [
                {"column": "A", "display": store, "header": "门店"},
                {"column": "B", "display": "立牌", "header": "物品"},
                {"column": "C", "display": location, "header": "位置"},
            ],
        },
        header_row=6,
        row_number=row,
        title=doc.title,
    )
    index.add_document(doc, [unit], embed=False)


def _index(tmp_path: Path, name: str = "m3") -> RagIndex:
    index = RagIndex(
        tmp_path / f"{name}.sqlite3",
        config=RagConfig(
            provider_mode="offline",
            data_dir=tmp_path,
            business_date="2026-10-28",
            chunk_max_chars=420,
            chunk_max_units=3,
            chunk_overlap_units=1,
            top_k=5,
            page_size=10,
            vector_candidate_limit=50,
            rerank_top_n=20,
        ),
    )
    for doc_id, store, location, row in STORES:
        _add(index, doc_id, store, location, row)
    return index


def _three_turns(tmp_path: Path, third: str, *, conversation_id: str):
    index = _index(tmp_path)
    try:
        first = index.ask(TURN_SCOPE, user_id="u", conversation_id=conversation_id)
        index.ask(TURN_TOPIC, user_id="u", conversation_id=conversation_id)
        last = index.ask(third, user_id="u", conversation_id=conversation_id)
    finally:
        index.close()
    return first, last


def test_m3_first_turn_is_scoped_to_one_store(tmp_path: Path) -> None:
    """绿（对照）：单回合点名门店时 filters 带 store，只答本店记录。"""

    index = _index(tmp_path, name="m3-control")
    try:
        answer = index.ask(TURN_SCOPE, user_id="u", conversation_id="c-m3-control")
    finally:
        index.close()
    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    assert answer.diagnostics["plan"]["filters"] == {"store": "甲店", "item": "立牌"}
    assert "甲区" in answer.text and "乙区" not in answer.text


def test_m3_store_scope_is_still_known_on_later_turn(tmp_path: Path) -> None:
    """红：第三回合的 filters 只剩 item，上一轮已确定的门店条件被丢掉。"""

    _first, last = _three_turns(tmp_path, "立牌放在哪？", conversation_id="c-m3-plan")
    filters = dict(last.diagnostics["plan"]["filters"])
    assert filters.get("store") == "甲店", (filters, last.kind, last.reason, last.text)


def test_m3_later_turn_does_not_answer_with_another_store(tmp_path: Path) -> None:
    """红：枚举式追问直接跨门店作答（甲区 + 乙区），即 cross_entity 的可见表现。"""

    _first, last = _three_turns(tmp_path, "列一下立牌放在哪？", conversation_id="c-m3-answer")
    assert "乙区" not in last.text, (last.kind, last.reason, last.text)
    assert {fact.value for fact in last.facts} <= {"甲区"}, [
        (fact.field_role, fact.value) for fact in last.facts
    ]
