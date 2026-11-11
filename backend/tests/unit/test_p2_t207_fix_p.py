"""P2-T207-FIX-P：回答事实准入接受"问题前提值"（用户输入）的最小口径。

复现的公开反例（T205 冻结，T207-FIX-P 复跑）：价目/指标/审批题把待查值写进问题本身
（"2026年Q4 的档期特价""单场预算 8000 元""咸味饼干 120g"），而资料只给结论、正文里
本来就不会出现用户的前提值；旧口径要求回答里的每个数据型 token 都出现在**引用来源**里，
于是"照实回答"被判成"引用来源中不存在的数据值"（MODEL_OUTPUT_INVALID），正确回答整轮作废。

本文件固定以下口径，防止这次改动被放宽（前三条为 T207-FIX-P，第 4 条为 P-R1 补钉）：
1) 问题里逐字出现的前提值可以复述（放行）；
2) 既不在问题、也不在引用来源里的值仍然拒绝；
3) 用未被引用的另一行取值仍然拒绝（"引用子集 + 别处取值"照旧拦截）；
4) P-R1（经理决定 2026-11-11 T207-FIX-P 裁量 2）：前提值被搬到答案的"值位置"同样接受
   ——这是**有意放宽**（旧口径拒、新口径收），且对抗性错误前提也按当前口径接受；
   记录型路径（不带 question 形参）对既有样本输出逐字不变。
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


# ---------------------------------------------------------------- P-R1：裁量 2 的边界钉死
# 经理决定 2026-11-11（T207-FIX-P 裁量 2）：问题前提值可出现在答案"值位置"，判定为合理且
# 必要，但须钉边界并转 T209 知悉。以下 4 条只固定**当前行为**，不改产品语义。

#: 只给结论、正文不含「8000」的审批条款行：引用它时，8000 只能来自问题原文。
POLICY = SimpleNamespace(
    id="u-policy",
    text="第六条 审批权限：单场预算按分档审批，由市场部经理审批。",
    fields={},
)

#: 问题前提值 8000（F02 原句）。
PREMISE_QUESTION = "单场预算 8000 元的活动由谁审批？"


def test_question_premise_value_moved_into_value_position_is_accepted() -> None:
    """P-R1(a)：问题里的 8000 被搬到答案的"值位置"（审批门槛）也接受——有意的放宽。

    对照同一条文本不传 question：旧口径仍拒绝。两条断言一起才能说明放行只来自问题原文。
    """
    text = "审批门槛为 8000 元，由市场部经理审批。"
    validated, ids = _validate_answer(
        _output(text, "u-policy"),
        {"u-policy"},
        [],
        evidence=(POLICY,),
        question=PREMISE_QUESTION,
    )
    assert validated == text
    assert ids == ["u-policy"]
    with pytest.raises(ModelOutputInvalid) as excinfo:
        _validate_answer(_output(text, "u-policy"), {"u-policy"}, [], evidence=(POLICY,))
    assert str(excinfo.value) == "回答包含引用来源中不存在的数据值"


def test_fabricated_value_in_same_value_position_is_rejected() -> None:
    """P-R1(b)：同一句式只把 8000 换成 1.88（问题与引用来源都没有）→ 仍然拒绝。

    与 (a) 成对：放宽只认"问题原文逐字出现"，不是对值位置放宽。
    """
    text = "审批门槛为 1.88 元，由市场部经理审批。"
    with pytest.raises(ModelOutputInvalid) as excinfo:
        _validate_answer(
            _output(text, "u-policy"),
            {"u-policy"},
            [],
            evidence=(POLICY,),
            question=PREMISE_QUESTION,
        )
    assert str(excinfo.value) == "回答包含引用来源中不存在的数据值"


def test_record_path_without_question_keeps_three_samples_verbatim() -> None:
    """P-R1(c)：记录型路径（不带 question 形参）对 3 个既有样本输出逐字不变。

    样本取自既有记录型用例（test_conversations.py:127-143 / :248-257 / :272-279），
    覆盖三种形态：只给 facts 的记录型调用、带 evidence 的正确回答、夹带未取证值。
    """
    # 1) 记录型调用形态：三位置 + facts，与 service.py:2310 的调用一致（不带 question）。
    record_text = "位置是B区1号货架第二层。"
    record_facts = [("位置", "B区1号货架第二层")]
    assert _validate_answer(_output(record_text, "u-row"), {"u-row"}, record_facts) == (
        record_text,
        ["u-row"],
    )
    # 2) 带 evidence 的正确回答：返回文本与来源逐字不变（不归一化、不加字）。
    ok_text = "价格单号：PX-0001；价格(元)：2.99"
    assert _validate_answer(_output(ok_text, "u-row"), {"u-row"}, [], evidence=(ROW,)) == (
        ok_text,
        ["u-row"],
    )
    # 3) 夹带来源外电话：拒绝文案与旧口径逐字一致。
    with pytest.raises(ModelOutputInvalid) as excinfo:
        _validate_answer(
            _output("价格单号：PX-0001；价格(元)：2.99，联系 010-99999999。", "u-row"),
            {"u-row"},
            [],
            evidence=(ROW,),
        )
    assert str(excinfo.value) == "回答包含引用来源中不存在的数据值"


def test_adversarial_wrong_premise_is_accepted_as_known_widening() -> None:
    """P-R1(d)：对抗性前提（问题给错值 3000、答案照抄）→ 当前口径接受。

    ⚠️ 这是**已知放宽**，不是"正确性通过"：口径只按"问题原文逐字出现"背书，不判前提真伪，
    因此错误前提会被复述并同时通过产品闸与 value_no_fabricated（评测器把问题数字计入白名单）。
    经理决定 2026-11-11（T207-FIX-P 裁量 2）已知悉并转 T209 阈值决策；本用例只钉住行为，
    后人不得据此宣称该事实正确或评测已能拦住错误前提。
    """
    question = "单场预算 3000 元的活动由谁审批？"
    text = "单场预算 3000 元的活动由市场部经理审批。"
    validated, ids = _validate_answer(
        _output(text, "u-policy"),
        {"u-policy"},
        [],
        evidence=(POLICY,),
        question=question,
    )
    assert validated == text
    assert ids == ["u-policy"]
