"""T004a：稳定引用解析 resolve_gold（设计 §7.2）。

金标准口径：
- ``unit_key`` 是身份型引用：必须恰好命中 1 个 unit；0 个或同 key 多 unit → GoldUnresolved；
- ``locator`` 是范围型引用：页/表/整篇可包含多个 unit，0 命中才失败；
- ``relevant_units`` 缺省时由 ``expected_sources`` 派生；多个 chunk 命中同一 unit 按 unit 去重；
- ``requires_ocr=true`` 的 case 在 P0 显式 skipped，不解析、不触发 OCR。
"""

from __future__ import annotations

import dataclasses

import pytest

from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.gold import GoldUnresolved, resolve_gold


def _case(case_id: str, sources, *, relevant=(), requires_ocr=False) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        suite="b0",
        split="dev",
        stratum="exact",
        business_date="2026-10-28",
        question="测试问题",
        expected_kind="answer",
        expected_sources=tuple(sources),
        relevant_units=tuple(relevant),
        requires_ocr=requires_ocr,
        label_version="b0-2026-11-04",
    )


def test_b0_all_40_cases_resolve_without_ocr(b0_cases, b0_index) -> None:
    resolved = resolve_gold(b0_cases, b0_index)

    assert len(resolved) == 40
    assert [item.case_id for item in resolved] == [case.case_id for case in b0_cases]
    non_ocr = [item for item in resolved if not item.requires_ocr]
    assert len(non_ocr) == 32
    for item in non_ocr:
        assert item.skipped is False
        assert item.sources, f"{item.case_id} 没有解析出来源"
        assert item.unit_ids, f"{item.case_id} 没有 relevant unit"
        for source in item.sources:
            assert source.doc_id == source.doc_code
            assert len(source.unit_ids) == 1, f"{item.case_id} 身份型来源应命中 1 个 unit"
        assert item.relevant_unit_ids == item.unit_ids


def test_ocr_cases_are_skipped_and_index_never_parsed_them(b0_cases, b0_index) -> None:
    resolved = resolve_gold(b0_cases, b0_index)
    ocr = [item for item in resolved if item.requires_ocr]
    assert len(ocr) == 8
    for item in ocr:
        assert item.skipped is True
        assert item.sources == ()
        assert item.unit_ids == ()
        assert item.relevant_unit_ids == ()
    visible = {item["doc_id"] for item in b0_index.list_documents()}
    assert visible == {"D01", "D02", "D03", "D04", "D05", "D06"}
    assert visible.isdisjoint({"D07", "D08", "D09", "D10"})


def test_badcase_gold_resolves_and_negative_cases_have_no_gold(badcase_cases, badcase_index) -> None:
    resolved = {item.case_id: item for item in resolve_gold(badcase_cases, badcase_index)}
    assert set(resolved) == {f"N{index:02d}" for index in range(1, 14)}

    for case_id in ("N10", "N12", "N13"):
        assert resolved[case_id].sources == ()
        assert resolved[case_id].unit_ids == ()

    for case_id in ("N01", "N02", "N08", "N11"):
        source = resolved[case_id].sources[0]
        assert source.doc_code == "E11"
        assert source.unit_keys == ("sheet:物品位置:row:7",)
        assert len(source.unit_ids) == 1

    clause = resolved["N03"].sources[0]
    assert clause.doc_code == "W01"
    assert clause.unit_keys == ("paragraph:13",)

    price = resolved["N04"].sources[0]
    assert price.doc_code == "E03"
    assert price.unit_keys == ("sheet:NKA卖场:row:10",)

    # 整表 / 整篇是范围型 gold：允许多个 unit。
    assert len(resolved["N05"].sources[0].unit_ids) > 1
    assert len(resolved["N09"].sources[0].unit_ids) == 17
    assert resolved["N09"].unit_ids == resolved["N09"].sources[0].unit_ids


def test_unknown_document_fails_closed(b0_index) -> None:
    case = _case("X01", [{"doc_code": "D99", "unit_key": "sheet:物品位置:row:8"}])
    with pytest.raises(GoldUnresolved) as excinfo:
        resolve_gold([case], b0_index)
    assert excinfo.value.case_id == "X01"
    assert excinfo.value.reason == "document_not_found"
    assert "X01" in str(excinfo.value)


def test_unknown_unit_key_fails_closed(b0_index) -> None:
    case = _case("X02", [{"doc_code": "D01", "unit_key": "sheet:物品位置:row:999"}])
    with pytest.raises(GoldUnresolved) as excinfo:
        resolve_gold([case], b0_index)
    assert excinfo.value.reason == "unit_key_not_found"


def test_unknown_locator_fails_closed(b0_index) -> None:
    case = _case("X03", [{"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 999}}])
    with pytest.raises(GoldUnresolved) as excinfo:
        resolve_gold([case], b0_index)
    assert excinfo.value.reason == "locator_not_found"


def test_unsupported_locator_key_fails_closed(b0_index) -> None:
    case = _case("X04", [{"doc_code": "D01", "locator": {"image": True}}])
    with pytest.raises(GoldUnresolved) as excinfo:
        resolve_gold([case], b0_index)
    assert excinfo.value.reason == "unsupported_locator_key"


def test_duplicate_unit_key_fails_closed(duplicate_key_index) -> None:
    case = _case("X05", [{"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}])
    with pytest.raises(GoldUnresolved) as excinfo:
        resolve_gold([case], duplicate_key_index)
    assert excinfo.value.reason == "duplicate_unit_key"


def test_locator_with_duplicate_units_is_deduped_and_ambiguity_is_explicit(duplicate_key_index) -> None:
    case = _case("X06", [{"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 8}}])
    with pytest.raises(GoldUnresolved) as excinfo:
        resolve_gold([case], duplicate_key_index)
    assert excinfo.value.reason == "ambiguous_units"


def test_duplicate_source_references_are_deduped(b0_index) -> None:
    source = {"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}
    case = _case("X07", [source, dict(source)])
    resolved = resolve_gold([case], b0_index)[0]
    assert len(resolved.sources) == 2
    assert len(resolved.unit_ids) == 1


def test_multiple_chunks_of_one_unit_collapse_to_one_gold_unit(split_chunk_index) -> None:
    """同一 unit 被拆成多个 chunk 时，gold 口径按 unit 去重（不重复计数）。"""
    from sqlalchemy import select

    from mktkb.rag.models import RagChunk

    resolved = resolve_gold([_case("X11", [{"doc_code": "D90", "unit_key": "sheet:物品位置:row:8"}])], split_chunk_index)[0]
    assert resolved.unit_ids == ("D90-long",)
    assert resolved.sources[0].unit_keys == ("sheet:物品位置:row:8",)
    with split_chunk_index.session() as session:
        chunks = session.execute(select(RagChunk).where(RagChunk.doc_id == "D90")).scalars().all()
    assert len(chunks) > 1, "夹具应把一个 record unit 拆成多个 chunk"
    assert {chunk.record_unit_id for chunk in chunks} == {"D90-long"}
    assert all("D90-long" in tuple(chunk.unit_ids or ()) for chunk in chunks)


def test_relevant_units_override_and_derive(b0_index) -> None:
    derived = resolve_gold([_case("X08", [{"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}])], b0_index)[0]
    other = resolve_gold([_case("X09", [{"doc_code": "D01", "unit_key": "sheet:物品位置:row:9"}])], b0_index)[0]
    assert derived.relevant_unit_ids == derived.unit_ids
    assert derived.unit_ids != other.unit_ids

    overridden = resolve_gold(
        [
            _case(
                "X10",
                [{"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}],
                relevant=[{"doc_code": "D01", "unit_key": "sheet:物品位置:row:9"}],
            )
        ],
        b0_index,
    )[0]
    assert overridden.unit_ids == derived.unit_ids
    assert overridden.relevant_unit_ids == other.unit_ids


def test_resolved_gold_is_immutable_and_deterministic(b0_cases, b0_index) -> None:
    first = resolve_gold(b0_cases, b0_index)
    second = resolve_gold(b0_cases, b0_index)
    assert first == second
    with pytest.raises(dataclasses.FrozenInstanceError):
        first[0].case_id = "mutated"  # type: ignore[misc]
