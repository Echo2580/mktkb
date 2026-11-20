"""R0/C12 候选丢弃原因：``rag.retrieval.search`` 的 ``diag`` 早退点（诊断码固定值）。

- ``diag`` 是**只写诊断码**的可选关键字：``None``（默认）时不建键、不改控制流、不新增查询，
  结果集与加参数前逐值相同；
- 固定码与产品面枚举一致：``kind_miss`` / ``term_miss`` / ``vector_unavailable`` /
  ``filter_miss`` / ``dedup_dropped`` / ``limit_dropped``；
- 合成索引与合成题面，0 次真实请求（网络闸门逐次断言外部出站为 0）。

先红后绿：实现前 ``search(..., diag=...)`` 会因未知关键字直接 TypeError。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.rag import RagConfig, RagIndex  # noqa: E402
from mktkb.rag.types import QueryPlan, QueryState  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROWS = [
    {"标识": "B01", "门店": "滨江店", "物品": "宣传海报", "位置": "店内外侧"},
    {"标识": "B02", "门店": "滨江店", "物品": "价签纸", "位置": "收银台旁"},
    {"标识": "B03", "门店": "滨江店", "物品": "立牌", "位置": "入口堆头旁"},
]


def _plan(**overrides):
    values = dict(
        question="滨江店的宣传海报位置",
        mode="record",
        query_text="滨江店的宣传海报位置",
        field_role=None,
        field_label=None,
        filters={"store": "滨江店"},
        terms=("滨江店",),
        state=QueryState(user_id="u", conversation_id="c"),
        page=1,
        page_size=10,
    )
    values.update(overrides)
    return QueryPlan(**values)


def _stable(result) -> dict:
    """与耗时无关的结果投影：用于逐值比较 diag/无 diag 两次调用。"""

    return {
        "exact": [chunk.chunk_id for chunk in result.exact],
        "lexical": [chunk.chunk_id for chunk in result.lexical],
        "vector": [chunk.chunk_id for chunk in result.vector],
        "fused": [(chunk.chunk_id, round(score, 9)) for chunk, score in result.fused],
        "evidence": [(item.chunk_id, dict(item.scores)) for item in result.evidence],
        "recall_counts": dict(result.recall_counts),
        "total": result.total,
        "returned": result.returned,
        "has_more": result.has_more,
        "next_page": result.next_page,
        "degraded": list(result.degraded),
    }


@pytest.fixture
def no_vector_index(tmp_path, make_doc, make_unit):
    """运行时关闭查询向量面：向量通道固定不可用。"""

    config = RagConfig(
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
        disable_query_embedding=True,
    )
    index = RagIndex(tmp_path / "novec.sqlite3", config=config)
    doc = make_doc()
    units = [
        make_unit(
            doc,
            fields={"标识": "B01", "门店": "滨江店", "物品": "宣传海报", "位置": "店内外侧"},
            ordinal=0,
            row=7,
        )
    ]
    index.add_document(doc, units, embed=False)
    try:
        yield index
    finally:
        index.close()


# --------------------------------------------------------------------------- #
# 1) 默认 None：结果集与加参数前逐值相同（红→绿的主不变量）
# --------------------------------------------------------------------------- #


def test_search_without_diag_is_result_identical(rag_index, add_records):
    add_records(ROWS)
    plan = _plan()

    before = rag_index.search(plan)
    after = rag_index.search(plan, diag={})

    assert _stable(before) == _stable(after)
    assert set(before.diagnostics) == set(after.diagnostics)
    assert len(before.fused) == len(ROWS)
    assert before.recall_counts["exact"] == len(ROWS)


def test_search_with_diag_does_not_write_retrieval_state(rag_index, add_records):
    """diag 只写调用方给的字典：不落到 ``RetrievalResult``/diagnostics。"""

    add_records(ROWS)
    diag: dict[str, str] = {}
    result = rag_index.search(_plan(), diag=diag)

    assert isinstance(diag, dict) and all(type(value) is str for value in diag.values())
    assert "candidate_dropped_reason" not in result.diagnostics
    assert "diag" not in result.diagnostics
    assert not hasattr(result, "diag")


# --------------------------------------------------------------------------- #
# 2) 各早退/丢弃点写出的固定码
# --------------------------------------------------------------------------- #


def test_kind_miss_when_plan_is_not_record(rag_index, add_records):
    add_records([], text_units=[{"text": "宣传海报应放在入口堆头旁，并由门店负责人确认。"}])
    plan = _plan(mode="document", filters={}, terms=("海报",))
    diag: dict[str, str] = {}

    result = rag_index.search(plan, diag=diag)

    assert result.lexical, "正文面必须真的召回，否则 kind_miss 只是空集"
    assert diag == {"exact": "kind_miss"}


def test_term_miss_when_record_terms_are_empty(rag_index, add_records):
    add_records(ROWS)
    diag: dict[str, str] = {}

    rag_index.search(_plan(terms=()), diag=diag)

    # 记录面精确通道仍命中（与 terms 无关），只有词面早退。
    assert diag == {"lexical": "term_miss"}


def test_vector_unavailable_when_query_embedding_is_disabled(no_vector_index):
    diag: dict[str, str] = {}

    result = no_vector_index.search(_plan(), diag=diag)

    assert result.degraded == ("vector",)
    assert diag.get("vector") == "vector_unavailable"
    assert result.exact and result.lexical


def test_limit_dropped_when_top_k_truncates_fused(rag_index, add_records):
    rows = [
        {"标识": f"I{index:02d}", "门店": "滨江店", "物品": "宣传海报", "位置": f"位置{index}"}
        for index in range(8)
    ]
    add_records(rows)
    diag: dict[str, str] = {}

    result = rag_index.search(_plan(), diag=diag)

    assert len(result.fused) == 8 and len(result.evidence) == 5
    assert diag == {"limit": "limit_dropped"}


def test_dedup_dropped_when_enumerate_collapses_split_unit_chunks(rag_index, add_records):
    fields = {"标识": "L01", "门店": "滨江店", "物品": "长物料", "位置": "A区1号货架"}
    fields.update({f"说明{i:02d}": "这是一段用于触发记录块拆分的较长说明文本" * 3 for i in range(20)})
    add_records([fields])
    diag: dict[str, str] = {}

    result = rag_index.search(_plan(terms=(), enumerate=True), diag=diag)

    assert len(result.exact) >= 2, "长记录必须被拆成多个 chunk 才有去重可测"
    assert diag.get("dedup") == "dedup_dropped", diag
    assert "limit" not in diag, "单页装得下时不得记 limit_dropped"


def test_filter_miss_when_hard_filter_drops_candidates(rag_index, add_records, monkeypatch):
    add_records(ROWS)
    from mktkb.rag import retrieval as retrieval_module

    monkeypatch.setattr(retrieval_module, "_passes_filters", lambda chunk, plan: False)
    diag: dict[str, str] = {}

    result = rag_index.search(_plan(), diag=diag)

    assert diag == {"filter": "filter_miss"}
    assert result.fused == [] and result.evidence == []
