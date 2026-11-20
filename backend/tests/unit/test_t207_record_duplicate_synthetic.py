from types import SimpleNamespace

from mktkb.conversations.service import _record_facts


def test_identical_attested_clause_repeated_is_deduplicated():
    rows = [SimpleNamespace(id="a", fields={"门店": "北园店", "位置": "甲柜"}),
            SimpleNamespace(id="b", fields={"门店": "北园店", "位置": "甲柜"})]
    result = _record_facts("位置：甲柜；位置：甲柜", rows, [("位置", "甲柜")])
    assert result == [("位置", "甲柜", "a")]


def test_conflicting_repetition_is_rejected():
    rows = [SimpleNamespace(id="a", fields={"门店": "北园店", "位置": "甲柜"})]
    assert _record_facts("位置：甲柜；位置：乙柜", rows, [("位置", "甲柜")]) is None
