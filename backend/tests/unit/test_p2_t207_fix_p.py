"""P2-T207-FIX-P：回答事实准入接受"问题前提值"（用户输入）的最小口径。

复现的公开反例（T205 冻结，T207-FIX-P 复跑）：价目/指标/审批题把待查值写进问题本身
（"2026年Q4 的档期特价""单场预算 8000 元""咸味饼干 120g"），而资料只给结论、正文里
本来就不会出现用户的前提值；旧口径要求回答里的每个数据型 token 都出现在**引用来源**里，
于是"照实回答"被判成"引用来源中不存在的数据值"（MODEL_OUTPUT_INVALID），正确回答整轮作废。

本文件只固定三条，防止这次口径改动被放宽：
1) 问题里逐字出现的前提值可以复述（放行）；
2) 既不在问题、也不在引用来源里的值仍然拒绝；
3) 用未被引用的另一行取值仍然拒绝（"引用子集 + 别处取值"照旧拦截）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mktkb.conversations.service import _validate_answer
from mktkb.providers.types import CompletionOutput, ModelOutputInvalid

#: 引用行：只有被引用的这一行能为取值背书。
ROW = SimpleNamespace(
    id="u-row",
    text="价格单号：PX-0001 / 价格类型：档期特价 / 价格(元)：2.99",
    fields={"价格单号": "PX-0001", "价格类型": "档期特价", "价格(元)": "2.99"},
)
#: 未引用行：同 SKU 的旧价，任何情况下都不得为回答背书。
OTHER = SimpleNamespace(
    id="u-other",
    text="价格单号：PX-0020 / 价格类型：档期特价 / 价格(元)：2.5",
    fields={"价格单号": "PX-0020", "价格类型": "档期特价", "价格(元)": "2.5"},
)

QUESTION = "2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价是多少？"


def _output(text: str, *ids: str) -> CompletionOutput:
    return CompletionOutput(text=text, source_ids=tuple(ids))


def test_question_premise_value_is_attested() -> None:
    """问题里写明的年月/季度可被回答复述；取值仍来自被引用行。"""
    text = "2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价为 2.99 元/瓶。"
    validated, ids = _validate_answer(
        _output(text, "u-row"),
        {"u-row"},
        [],
        evidence=(ROW,),
        question=QUESTION,
    )
    assert validated == text
    assert ids == ["u-row"]


def test_unknown_value_from_neither_question_nor_citation_is_rejected() -> None:
    """既不在问题、也不在引用来源里的数字仍然拒绝（不放宽）。"""
    text = "2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价为 1.88 元/瓶。"
    with pytest.raises(ModelOutputInvalid) as excinfo:
        _validate_answer(
            _output(text, "u-row"),
            {"u-row"},
            [],
            evidence=(ROW,),
            question=QUESTION,
        )
    assert "引用来源中不存在的数据值" in str(excinfo.value)


def test_value_from_uncited_row_is_still_rejected() -> None:
    """"引用 A 行、用未引用 B 行的值"照旧拒绝（问题前提值不改变这条口径）。"""
    text = "2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价为 2.5 元/瓶。"
    with pytest.raises(ModelOutputInvalid) as excinfo:
        _validate_answer(
            _output(text, "u-row"),
            {"u-row", "u-other"},
            [],
            evidence=(ROW, OTHER),
            question=QUESTION,
        )
    assert "引用来源中不存在的数据值" in str(excinfo.value)


def test_attestation_without_question_keeps_old_behaviour() -> None:
    """不传问题（记录型既有调用）时逐字沿用旧口径：来源外的值仍拒绝。"""
    text = "2026年Q4 的档期特价为 2.99 元/瓶。"
    with pytest.raises(ModelOutputInvalid):
        _validate_answer(_output(text, "u-row"), {"u-row"}, [], evidence=(ROW,))
