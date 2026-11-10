"""P1-FIX/C 单元：内部引用（citations）→ 产品来源（source_ids/missing_fields）的转换。

不建产品、不调模型：直接验证 ``conversations.service._rag_turn_result`` 的映射语义。
"""

from __future__ import annotations

from mktkb.conversations import service
from mktkb.rag.types import Citation, Fact, RagAnswer


def _citation(chunk_id: str, *, title: str, version_label: str, unit_ids: tuple[str, ...]) -> Citation:
    return Citation(
        source_id=chunk_id,
        doc_id="doc-1",
        source_path="legal.docx",
        title=title,
        version_id="ver-1",
        version_label=version_label,
        revision=7,
        locator={"paragraph": 39},
        text="第二十七条 本规定自 2022年7月1日起施行。",
        kind="text",
        unit_ids=unit_ids,
    )


def _fact(source_unit_id: str) -> Fact:
    return Fact(
        entity_key="item|城西店|宣传海报",
        entity_label="城西店的宣传海报",
        field_role="location",
        field_label="位置",
        value="C区2号货架第一层",
        source_chunk_id="chunk-1",
        source_unit_id=source_unit_id,
        doc_id="doc-1",
        version_id="ver-1",
        revision=7,
    )


def test_document_answer_citations_become_product_source_ids() -> None:
    """文档/法规抽取答案没有 facts 时，也要把 citations 的来源单元映射成产品来源。"""
    answer = RagAnswer(
        kind="answer",
        question="那个海报的价格欺诈规定是什么？",
        text="根据资料，第二十七条 本规定自 2022年7月1日起施行。",
        state={},
        citations=(
            _citation("chunk-a", title="明码标价和禁止价格欺诈规定", version_label="v1", unit_ids=("u1", "u2")),
            _citation("chunk-b", title="明码标价和禁止价格欺诈规定", version_label="v1", unit_ids=("u2", "u3")),
        ),
        facts=(),
        answer_source="extractive_offline",
    )

    result = service._rag_turn_result(answer, revision=7)

    assert result.kind == "answer"
    assert result.source_ids == ("u1", "u2", "u3")
    assert result.missing_fields == []


def test_structured_answer_still_uses_fact_sources_only() -> None:
    """结构化记录答案保持既有口径：来源取 facts 的 source_unit_id，不被 citation 扩大。"""
    answer = RagAnswer(
        kind="answer",
        question="城西店的宣传海报在哪里？",
        text="根据资料，城西店的宣传海报的位置：C区2号货架第一层。",
        state={},
        citations=(
            _citation("chunk-a", title="终端物料位置表", version_label="当前", unit_ids=("rec-1", "rec-2")),
        ),
        facts=(_fact("rec-1"),),
        answer_source="structured",
    )

    result = service._rag_turn_result(answer, revision=7)

    assert result.kind == "answer"
    assert result.source_ids == ("rec-1",)


def test_field_not_recorded_carries_missing_field_label() -> None:
    """记录存在但缺字段：带出缺失字段名，前端徽标可显示“字段未记录”（不再一律“无匹配资料”）。"""
    answer = RagAnswer(
        kind="no_answer",
        question="那个海报的盘点时间是什么？",
        text="资料中未记录日期（记录存在，但缺少该字段）；记录缺失不等于服务异常。",
        state={},
        citations=(),
        facts=(),
        reason="FIELD_NOT_RECORDED",
        answer_source="refusal",
        diagnostics={"plan": {"field_role": "date", "mode": "record"}},
    )

    result = service._rag_turn_result(answer, revision=7)

    assert result.kind == "not_found"
    assert result.missing_fields == ["日期"]
    assert result.source_ids == ()


def test_refusal_with_citations_does_not_expose_sources() -> None:
    """拒答（no_answer）即便内部带有效期提示 citations，也不把来源当答案依据暴露。"""
    answer = RagAnswer(
        kind="no_answer",
        question="这个价格现在还有效吗？",
        text="该记录的有效期已过期，不能作为现价。",
        state={},
        citations=(_citation("chunk-a", title="价目表", version_label="v1", unit_ids=("u9",)),),
        facts=(),
        reason="EFFECTIVE_WINDOW_EXPIRED",
        answer_source="structured_refusal",
    )

    result = service._rag_turn_result(answer, revision=7)

    assert result.kind == "not_found"
    assert result.source_ids == ()
