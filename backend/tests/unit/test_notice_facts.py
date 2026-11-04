"""回归：正文来源的记录事实抽取（T09-D2 P0 根因）。

覆盖三件事，均只用语言层面句式与词表，不读取题集/期望值：
1. 通知句里的「门店 + 字段 + 值」能被抽成结构化字段（位置/电话）；
2. 流程叙述、泛指门店（门店/两店/店家）不被误抽；
3. 门店名识别与意图层共用同一口径："发现店家"不被当成门店"发现店"。
"""

from __future__ import annotations

import pytest

from mktkb.ingestion.parsers.notice_facts import extract_record_facts
from mktkb.text_zh import iter_store_names


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "因 B 区货架盘点，城东店宣传海报临时调整至 D区暂存柜。",
            {"门店": "城东店", "物品": "宣传海报", "位置": "D区暂存柜"},
        ),
        (
            "城东店宣传海报存放于 B区1号货架第二层。",
            {"门店": "城东店", "物品": "宣传海报", "位置": "B区1号货架第二层"},
        ),
        (
            "城东店联系电话调整为 010-00000099（模拟）。",
            {"门店": "城东店", "电话": "010-00000099"},
        ),
    ],
)
def test_notice_sentence_yields_structured_fields(text, expected):
    assert extract_record_facts(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "发现店家信息变化后，应当日联系资料管理员核实。",
        "跨店调拨物料须经两店负责人确认后方可执行。",
        "物料领用需填写登记表并经门店负责人确认，领取时登记实际领取数量。",
        "归还时须核对数量与状态，并在登记表中登记归还日期。",
        "活动申请至少提前 3 个工作日提交，不得以 3 个自然日替代。",
        "",
    ],
)
def test_non_record_sentences_are_not_extracted(text):
    assert extract_record_facts(text) == {}


def test_store_name_recognition_is_shared_and_conservative():
    # 具体门店名可识别（未登记门店仍要能被识别，才能给出"资料中没有该门店"）
    assert [name for _offset, name in iter_store_names("城南店联系人是谁？")] == ["城南店"]
    # "店家/门店/两店/各家店/经两店"等不是门店名
    for text in ("发现店家信息变化后", "门店领取宣传物料前", "须经两店负责人确认", "该门店需登记"):
        assert iter_store_names(text) == [], text
    # 同一句里既有误匹配片段又有真实门店名时，只返回真实门店名
    assert [name for _offset, name in iter_store_names("门店通知：城东店今日盘点")] == ["城东店"]


def test_extraction_does_not_depend_on_document_or_question_metadata():
    """抽取函数只接收文本：换一个说法（不同门店/物品/值）同样成立，证明未写死语料。"""
    facts = extract_record_facts("因盘点，西单店易拉宝临时调整至 A区1号柜。")
    assert facts == {"门店": "西单店", "物品": "易拉宝", "位置": "A区1号柜"}
