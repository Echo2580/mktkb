"""R5-A 定点回归：被请求但无记录的门店披露、未知门店切词、披露/归因攻击对照。

对应 R4 独立复验的 R4-NEW-4（缺记录门店披露整条被 CROSS_ENTITY 拒掉）与
R4-NEW-5（“和”连接的未知门店名被切走首字）。fixture 结构等价 E11：
滨江店在全库词表中存在，但没有“端架侧板”记录。
"""

from __future__ import annotations

import hashlib

import pytest

from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex
from mktkb.rag.errors import CrossEntity, FactRejected, UnsupportedClaim
from mktkb.rag.facts import FactValidator
from mktkb.rag.query import build_lexicon, parse_query


def _doc(code: str, title: str) -> DocumentSpec:
    return DocumentSpec(
        doc_id=code,
        logical_id=code,
        source_path=f"{code}.xlsx",
        title=title,
        file_kind="xlsx",
        version_id=f"{code}-v1",
        version_label="当前",
        sha256=hashlib.sha256(code.encode()).hexdigest(),
        business_date="2026-10-28",
    )


def _row(doc: DocumentSpec, fields: dict, ordinal: int = 0) -> AtomicUnit:
    return AtomicUnit(
        unit_id=f"{doc.doc_id}-{ordinal}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=ordinal,
        unit_key=f"r{ordinal}",
        text="；".join(f"{k}: {v}" for k, v in fields.items()),
        fields=fields,
        sheet="物品位置",
        locator={"sheet": "物品位置", "row": ordinal + 2, "header_row": 1, "row_number": ordinal + 2},
        header_row=1,
        row_number=ordinal + 2,
    )


ROWS = [
    {"门店": "和悦广场店", "物品": "端架侧板", "数量": 6, "单位": "块"},
    {"门店": "梧桐里店", "物品": "端架侧板", "数量": 220, "单位": "块"},
    {"门店": "湖畔店", "物品": "端架侧板", "数量": 42, "单位": "块"},
    {"门店": "卓刀河店", "物品": "端架侧板", "数量": 240, "单位": "块"},
    {"门店": "滨江店", "物品": "堆头围挡", "数量": 3, "单位": "块"},
]


@pytest.fixture
def store_index(tmp_path):
    config = RagConfig(
        provider_mode="offline",
        data_dir=tmp_path,
        business_date="2026-10-28",
        chunk_max_chars=420,
        chunk_max_units=3,
        top_k=10,
        page_size=10,
        rerank_top_n=20,
    )
    index = RagIndex(tmp_path / "stores.sqlite3", config=config)
    doc = _doc("E11X", "终端物料位置表")
    index.add_document(doc, [_row(doc, dict(row), position) for position, row in enumerate(ROWS)])
    try:
        yield index
    finally:
        index.close()


def _ask(index: RagIndex, question: str, conversation_id: str):
    return index.ask(question, user_id="r5", conversation_id=conversation_id)


def _disclosure(text: str) -> str | None:
    for line in text.splitlines():
        if "未在资料中找到" in line:
            return line
    return None


# --------------------------------------------------------------- R4-NEW-4


def test_requested_store_without_record_is_disclosed_not_rejected(store_index) -> None:
    answer = _ask(store_index, "和悦广场店和滨江店的端架侧板分别有多少", "ms-2b")
    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "和悦广场店" in answer.text and "6" in answer.text
    assert _disclosure(answer.text) == "未在资料中找到：滨江店（该实体没有匹配记录）。"
    assert "梧桐里店" not in answer.text
    assert answer.citations, "有记录实体必须保留来源引用"
    assert "来源：" in answer.text or "（来源" in answer.text


def test_three_stores_one_without_record_keeps_valid_values(store_index) -> None:
    answer = _ask(store_index, "把卓刀河店、湖畔店和滨江店的端架侧板数量都列出来", "ms-2d")
    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "240" in answer.text and "42" in answer.text
    assert "3" not in answer.text, "滨江店记录的是其它物品，不能混入本条答案"
    assert _disclosure(answer.text) == "未在资料中找到：滨江店（该实体没有匹配记录）。"
    assert "已显示全部" not in answer.text


def test_single_store_without_record_says_so_without_numbers(store_index) -> None:
    answer = _ask(store_index, "滨江店的端架侧板有多少", "ms-2e")
    assert answer.kind == "no_answer"
    assert answer.reason == "NO_RECORD_FOR_ENTITY"
    assert "滨江店" in answer.text and "端架侧板" in answer.text
    for value in ("6", "220", "42", "240", "3"):
        assert value not in answer.text


def test_recorded_store_is_not_disclosed_as_missing(store_index) -> None:
    answer = _ask(store_index, "和悦广场店和梧桐里店的端架侧板分别有多少", "ms-2a")
    assert answer.kind == "answer", (answer.reason, answer.text)
    assert "6" in answer.text and "220" in answer.text
    assert _disclosure(answer.text) is None
    assert "已显示全部" in answer.text


# --------------------------------------------------------------- R4-NEW-5


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("和悦广场店和星海店的端架侧板分别有多少", "星海店"),
        ("和悦广场店、星海店的端架侧板分别有多少", "星海店"),
        ("和悦广场店与星海店的端架侧板分别有多少", "星海店"),
        ("和悦广场店及星海店的端架侧板分别有多少", "星海店"),
        ("和悦广场店和和平里店的端架侧板分别有多少", "和平里店"),
        ("梧桐里店和XX不存在店的端架侧板分别有多少", "不存在店"),
    ],
)
def test_unknown_store_name_is_extracted_whole(store_index, question: str, expected: str) -> None:
    answer = _ask(store_index, question, "ms-unknown-" + expected)
    assert answer.kind == "answer", (answer.reason, answer.text)
    assert _disclosure(answer.text) == f"未在资料中找到：{expected}（该实体没有匹配记录）。"


def test_unknown_store_starting_with_connector_keeps_first_char(store_index) -> None:
    answer = _ask(store_index, "和平里店的端架侧板有多少", "ms-2i")
    assert answer.kind == "no_answer"
    assert answer.reason == "UNKNOWN_STORE"
    assert "和平里店" in answer.text
    assert "平里店" not in answer.text.replace("和平里店", "")


def test_all_unknown_stores_refuse_and_name_every_one(store_index) -> None:
    answer = _ask(store_index, "星海店和银河店的端架侧板分别有多少", "ms-2k")
    assert answer.kind == "no_answer"
    assert answer.reason == "UNKNOWN_STORE"
    assert "星海店" in answer.text and "银河店" in answer.text
    assert "不能据此编造" in answer.text


# --------------------------------------------------------------- 攻击对照


def _capture(store_index, question: str) -> tuple[dict, FactValidator]:
    """复现产品调用上下文：拿到真实 plan/facts/text 后用于篡改回放。"""
    import mktkb.rag.answer as answer_module

    captured: dict = {}
    original = answer_module.FactValidator.validate_record_text

    def spy(validator, text, facts_list, **kwargs):
        captured.update({"validator": validator, "text": text, "facts": list(facts_list), "kwargs": dict(kwargs)})
        return original(validator, text, facts_list, **kwargs)

    answer_module.FactValidator.validate_record_text = spy
    try:
        result = _ask(store_index, question, f"atk-{abs(hash(question)) % 10000}")
    finally:
        answer_module.FactValidator.validate_record_text = original
    assert captured, f"没有捕获到校验调用：{result.kind} {result.text}"
    return captured, captured["validator"]


def _replay(captured: dict, text: str) -> None:
    captured["validator"].validate_record_text(
        text, captured["facts"], **captured["kwargs"]
    )


def test_disclosure_line_with_unrequested_store_is_rejected(store_index) -> None:
    captured, _validator = _capture(store_index, "和悦广场店和滨江店的端架侧板分别有多少")
    line = _disclosure(captured["text"])
    assert line is not None
    tampered = captured["text"].replace(line, line.replace("滨江店", "滨江店、梧桐里店"))
    with pytest.raises(FactRejected) as excinfo:
        _replay(captured, tampered)
    assert excinfo.value.code == "CROSS_ENTITY"


def test_disclosure_cannot_carry_forged_quantity(store_index) -> None:
    captured, _validator = _capture(store_index, "和悦广场店和滨江店的端架侧板分别有多少")
    line = _disclosure(captured["text"])
    assert line is not None
    # 9 不在引用证据里；“6” 这类语料真值也不能挂到无记录门店名下。
    for forged in ("滨江店 9 块，", "滨江店 6 块，"):
        tampered = captured["text"].replace(line, line.replace("滨江店", forged))
        with pytest.raises(FactRejected) as excinfo:
            _replay(captured, tampered)
        assert excinfo.value.code in ("FORGED_VALUE", "CROSS_ENTITY")


def test_recorded_store_cannot_be_claimed_missing(store_index) -> None:
    captured, _validator = _capture(store_index, "和悦广场店和滨江店的端架侧板分别有多少")
    line = _disclosure(captured["text"])
    assert line is not None
    tampered = captured["text"].replace(line, line.replace("滨江店", "和悦广场店"))
    with pytest.raises(FactRejected) as excinfo:
        _replay(captured, tampered)
    assert excinfo.value.code == "CROSS_ENTITY"


def test_entity_cannot_take_another_entitys_true_value(store_index) -> None:
    captured, _validator = _capture(store_index, "和悦广场店和梧桐里店的端架侧板分别有多少")
    original = captured["text"]
    tampered = original.replace("和悦广场店的端架侧板：6", "和悦广场店的端架侧板：220")
    assert tampered != original
    with pytest.raises(FactRejected) as excinfo:
        _replay(captured, tampered)
    assert excinfo.value.code == "CROSS_ENTITY"


def test_appending_missing_line_when_nothing_is_missing_is_rejected(store_index) -> None:
    captured, _validator = _capture(store_index, "和悦广场店和梧桐里店的端架侧板分别有多少")
    tampered = captured["text"] + "\n未在资料中找到：梧桐里店（该实体没有匹配记录）。"
    with pytest.raises(FactRejected) as excinfo:
        _replay(captured, tampered)
    assert excinfo.value.code == "CROSS_ENTITY"


def test_validator_rejects_disclosure_disabled_by_incomplete_coverage(store_index) -> None:
    captured, validator = _capture(store_index, "和悦广场店和滨江店的端架侧板分别有多少")
    kwargs = dict(captured["kwargs"])
    kwargs["disclosure_complete"] = False
    with pytest.raises(UnsupportedClaim):
        validator.validate_record_text(captured["text"], captured["facts"], **kwargs)


def test_validator_rejects_disclosure_of_unrequested_entity(store_index) -> None:
    captured, validator = _capture(store_index, "和悦广场店和滨江店的端架侧板分别有多少")
    kwargs = dict(captured["kwargs"])
    kwargs["disclosure_entities"] = ("梧桐里店",)
    with pytest.raises(CrossEntity):
        validator.validate_record_text(captured["text"], captured["facts"], **kwargs)


def test_paged_result_does_not_claim_entity_is_missing(store_index) -> None:
    """分页未看完时不能下“无记录”结论。"""
    index = store_index
    config = index.config
    paged = RagIndex(index.db_path.parent / "paged.sqlite3", config=RagConfig(**{**config.__dict__, "page_size": 1}))
    doc = _doc("E11P", "终端物料位置表")
    rows = [
        {"门店": "和悦广场店", "物品": "端架侧板", "数量": 6, "单位": "块"},
        {"门店": "和悦广场店", "物品": "端架侧板", "数量": 6, "单位": "块", "位置": "A 区"},
        {"门店": "滨江店", "物品": "堆头围挡", "数量": 3, "单位": "块"},
    ]
    paged.add_document(doc, [_row(doc, dict(row), position) for position, row in enumerate(rows)])
    try:
        plan = parse_query(
            "和悦广场店和星海店的端架侧板都列出来",
            previous=None,
            lexicon=build_lexicon(paged.lexicon_data()),
            business_date="2026-10-28",
            page_size=1,
        )
        assert plan.enumerate is True
        answer = paged.ask("和悦广场店和星海店的端架侧板都列出来", user_id="r5", conversation_id="paged")
        if "还有更多" in answer.text:
            assert "未在资料中找到" not in answer.text
    finally:
        paged.close()
