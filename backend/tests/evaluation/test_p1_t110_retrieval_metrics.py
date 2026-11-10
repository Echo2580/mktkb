"""T110：检索金标（``relevant_units``）与同 chunk 同排名检索指标。

口径（PM 追认，见 `.claude/handoffs/T110-retrieval-gold-metrics/handoff.md` §0）：

- 排名单位是 retrieved **chunk**（``EvalRetrieved`` 条目；同一 ``chunk_id`` 的多条
  条目是同一个 chunk），同一 chunk 内多个 unit **共享同一排名**；
- ``Recall@10`` = top-10 chunk 内命中的相关 unit 去重数 / 相关 unit 总数；
- ``MRR@10`` = 1 / 首个包含相关 unit 的 chunk 排名（>10 或未命中 → 0）；
- ``nDCG@10``：DCG 按 chunk 排名计，**一个 chunk 位置只计一次 gain**（同 chunk 的
  相关 unit 共享该位置；重复出现的 unit 不重复计 gain）；ideal 用
  ``min(|relevant|, 10)`` 个相关 unit 位置；
- ``hard_filter_violation_rate`` = 违规检索 unit 数 / 全部检索 unit 数；
- ``empty_recall_rate`` = 没有任何 retrieved unit 的 case 比例；
- 无 gold / OCR 跳过的 case 不进入任何检索指标分母。

手工对照表见 ``docs/reports/OBS-EVAL/P1/evidence/T110/02-hand-calc.md``。
本文件全部是合成输入，零真实调用。
"""

from __future__ import annotations

import math

import pytest

from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.gold import GoldUnresolved, ResolvedGold, resolve_case
from mktkb.evaluation.scorers import (
    EvalOutcome,
    EvalRetrieved,
    aggregate_metrics,
    retrieval_metrics,
    score_case,
)

RETRIEVAL_KEYS = frozenset(
    {
        "Recall@10",
        "MRR@10",
        "nDCG@10",
        "hard_filter_violation_rate",
        "empty_recall_rate",
    }
)


def _case(
    case_id: str,
    *,
    relevant: tuple[str, ...] = (),
    expected_sources: tuple[dict, ...] = (),
    forbidden_sources: tuple[dict, ...] = (),
) -> CaseSpec:
    """合成 CaseSpec；``relevant`` 写进 ``relevant_units`` 让指标走检索金标路径。"""
    return CaseSpec(
        case_id=case_id,
        suite="t110",
        split="dev",
        stratum="exact",
        business_date="2026-11-09",
        question="T110 合成问题",
        expected_kind="answer",
        expected_sources=expected_sources,
        relevant_units=tuple({"doc_code": "D01", "unit_key": f"k:{unit}"} for unit in relevant),
        forbidden_sources=forbidden_sources,
        label_version="t110-1",
    )


def _gold(case_id: str, relevant: tuple[str, ...]) -> ResolvedGold:
    return ResolvedGold(
        case_id=case_id,
        requires_ocr=False,
        skipped=False,
        sources=(),
        unit_ids=(),
        relevant_unit_ids=relevant,
    )


def _chunk(
    chunk_id: str | None,
    *unit_ids: str,
    doc_code: str = "D01",
    violation: str | None = None,
) -> tuple[EvalRetrieved, ...]:
    """一个 chunk 按 runner 口径展开成多条 ``EvalRetrieved``（每条 1 个 unit）。"""
    return tuple(
        EvalRetrieved(
            doc_code=doc_code,
            unit_ids=(unit_id,),
            chunk_id=chunk_id,
            hard_filter_violation=violation,
        )
        for unit_id in unit_ids
    )


def _outcome(retrieved: tuple[EvalRetrieved, ...]) -> EvalOutcome:
    return EvalOutcome(kind="answer", retrieved=retrieved)


def _idcg(units: int) -> float:
    """ideal DCG：``min(units, 10)`` 个相关 unit 各占一个 chunk 位置。"""
    return sum(1.0 / math.log2(rank + 1) for rank in range(1, min(units, 10) + 1))


# --------------------------------------------------------------------------- #
# 1. 同 chunk 同排名（验收场景：1 chunk 含 3 unit 其中 2 相关）
# --------------------------------------------------------------------------- #


def test_same_chunk_units_share_rank_and_one_ndcg_gain() -> None:
    # chunk c1 = [u1(相关), u2(相关), u9]；chunk c2 = [u3]。
    retrieved = _chunk("c1", "u1", "u2", "u9") + _chunk("c2", "u3")
    result = score_case(
        _case("C01", relevant=("u1", "u2")),
        _gold("C01", ("u1", "u2")),
        _outcome(retrieved),
    )

    # 手算：Recall=2/2，MRR=1/1；DCG=1/log2(2)（c1 只计一次 gain），IDCG=1+1/log2(3)。
    assert result.metrics["gold_units"] == 2
    assert result.metrics["retrieved_units"] == 4
    assert result.metrics["Recall@10"] == pytest.approx(1.0)
    assert result.metrics["MRR@10"] == pytest.approx(1.0)
    assert result.metrics["nDCG@10"] == pytest.approx(1.0 / _idcg(2))
    assert result.metrics["nDCG@10"] <= 1.0


def test_relevant_unit_not_first_in_chunk_uses_chunk_rank_not_unit_order() -> None:
    # chunk c1 = [u1, u2, u3(相关)]；若按 unit 出现顺序编造排名，MRR 会变成 1/3。
    retrieved = _chunk("c1", "u1", "u2", "u3") + _chunk("c2", "u9")
    result = score_case(
        _case("C02", relevant=("u3",)),
        _gold("C02", ("u3",)),
        _outcome(retrieved),
    )

    assert result.metrics["Recall@10"] == pytest.approx(1.0)
    assert result.metrics["MRR@10"] == pytest.approx(1.0)
    assert result.metrics["nDCG@10"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# 2. unit 去重（重复 unit 只计一次）
# --------------------------------------------------------------------------- #


def test_repeated_unit_over_chunks_counts_once_for_recall_mrr_ndcg() -> None:
    # c1=[u1]；c2=[u1]（重复，不贡献）；c3=[u2]。
    retrieved = _chunk("c1", "u1") + _chunk("c2", "u1") + _chunk("c3", "u2")
    result = score_case(
        _case("C03", relevant=("u1", "u2")),
        _gold("C03", ("u1", "u2")),
        _outcome(retrieved),
    )

    # 手算：Recall=2/2；MRR=1；DCG=1+1/log2(4)=1.5，IDCG=1+1/log2(3)。
    assert result.metrics["retrieved_units"] == 2  # u1、u2 去重
    assert result.metrics["Recall@10"] == pytest.approx(1.0)
    assert result.metrics["MRR@10"] == pytest.approx(1.0)
    assert result.metrics["nDCG@10"] == pytest.approx(1.5 / _idcg(2))


# --------------------------------------------------------------------------- #
# 3. 部分命中 / 空召回 / top-10 按 chunk 计
# --------------------------------------------------------------------------- #


def test_partial_hit_uses_chunk_ranks() -> None:
    # c1=[u9]；c2=[u1]；c3=[u2,u3]；u4 未检索到。
    retrieved = _chunk("c1", "u9") + _chunk("c2", "u1") + _chunk("c3", "u2", "u3")
    result = score_case(
        _case("C04", relevant=("u1", "u2", "u3", "u4")),
        _gold("C04", ("u1", "u2", "u3", "u4")),
        _outcome(retrieved),
    )

    # 手算：Recall=3/4；MRR=1/2；DCG=1/log2(3)+1/log2(4)。
    assert result.metrics["Recall@10"] == pytest.approx(0.75)
    assert result.metrics["MRR@10"] == pytest.approx(0.5)
    assert result.metrics["nDCG@10"] == pytest.approx(
        (1 / math.log2(3) + 1 / math.log2(4)) / _idcg(4)
    )


def test_empty_recall_is_quantified_and_ndcg_is_zero() -> None:
    result = score_case(
        _case("C05", relevant=("u1",)),
        _gold("C05", ("u1",)),
        _outcome(()),
    )

    assert result.metrics["gold_units"] == 1
    assert result.metrics["retrieved_units"] == 0
    assert result.metrics["empty_recall"] == 1.0
    assert result.metrics["Recall@10"] == 0.0
    assert result.metrics["MRR@10"] == 0.0
    assert result.metrics["nDCG@10"] == 0.0
    assert retrieval_metrics([result])["empty_recall_rate"] == pytest.approx(1.0)


def test_top_10_limits_chunks_not_units() -> None:
    # 10 个 chunk（每个 2 个 unit）之后才是相关 unit：按 unit 数会误算进 top-10。
    noise = tuple(
        entry
        for index in range(10)
        for entry in _chunk(f"n{index}", f"x{index}a", f"x{index}b", doc_code="D02")
    )
    retrieved = noise + _chunk("hit", "u1")
    result = score_case(
        _case("C06", relevant=("u1",)),
        _gold("C06", ("u1",)),
        _outcome(retrieved),
    )

    assert result.metrics["retrieved_units"] == 21
    assert result.metrics["Recall@10"] == 0.0
    assert result.metrics["MRR@10"] == 0.0
    assert result.metrics["nDCG@10"] == 0.0
    assert result.metrics["empty_recall"] == 0.0


# --------------------------------------------------------------------------- #
# 4. 硬过滤违规率（unit 级分母）+ 无 gold 不进分母
# --------------------------------------------------------------------------- #


def test_hard_filter_violation_rate_is_violating_units_over_all_retrieved_units() -> None:
    retrieved = (
        _chunk("c1", "u1")
        + _chunk("c2", "u9", violation="stale")
        + _chunk("c3", "u8", doc_code="D08")
    )
    result = score_case(
        _case("C07", relevant=("u1",), forbidden_sources=({"doc_code": "D08"},)),
        _gold("C07", ("u1",)),
        _outcome(retrieved),
    )

    assert result.metrics["retrieved_units"] == 3
    assert result.metrics["hard_filter_violations"] == 2  # stale + forbidden_source
    assert retrieval_metrics([result])["hard_filter_violation_rate"] == pytest.approx(2 / 3)


def test_case_without_gold_is_excluded_from_every_retrieval_denominator() -> None:
    gold = score_case(
        _case("C08", relevant=("u1",)),
        _gold("C08", ("u1",)),
        _outcome(_chunk("c1", "u1")),
    )
    no_gold = score_case(
        _case("C09"),
        _gold("C09", ()),
        _outcome(_chunk("c1", "x1", violation="stale") + _chunk("c2", "x2")),
    )

    assert no_gold.metrics["Recall@10"] is None
    assert no_gold.metrics["empty_recall"] is None
    metrics = retrieval_metrics([gold, no_gold])
    assert metrics["Recall@10"] == pytest.approx(1.0)
    assert metrics["empty_recall_rate"] == pytest.approx(0.0)
    assert metrics["hard_filter_violation_rate"] == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# 5. 手工对照表整表聚合（≥4 case；与 summary 字段名兼容）
# --------------------------------------------------------------------------- #


def _hand_table() -> list[tuple[CaseSpec, ResolvedGold, EvalOutcome]]:
    return [
        (
            _case("A", relevant=("u3",)),
            _gold("A", ("u3",)),
            _outcome(_chunk("a1", "u1", "u2", "u3") + _chunk("a2", "u9")),
        ),
        (
            _case("B", relevant=("u1", "u2")),
            _gold("B", ("u1", "u2")),
            _outcome(_chunk("b1", "u1", "u2", "u9") + _chunk("b2", "u3")),
        ),
        (
            _case("C", relevant=("u1", "u2")),
            _gold("C", ("u1", "u2")),
            _outcome(_chunk("c1", "u1") + _chunk("c2", "u1") + _chunk("c3", "u2")),
        ),
        (
            _case("D", relevant=("u1", "u2", "u3", "u4")),
            _gold("D", ("u1", "u2", "u3", "u4")),
            _outcome(_chunk("d1", "u9") + _chunk("d2", "u1") + _chunk("d3", "u2", "u3")),
        ),
        (
            _case("E", relevant=("u1",)),
            _gold("E", ("u1",)),
            _outcome(()),
        ),
        (
            _case("F", relevant=("u1",)),
            _gold("F", ("u1",)),
            _outcome(
                tuple(
                    entry
                    for index in range(10)
                    for entry in _chunk(f"f{index}", f"y{index}a", f"y{index}b", doc_code="D02")
                )
                + _chunk("f-hit", "u1")
            ),
        ),
        (
            _case("G", relevant=("u1",), forbidden_sources=({"doc_code": "D08"},)),
            _gold("G", ("u1",)),
            _outcome(
                _chunk("g1", "u1")
                + _chunk("g2", "u9", violation="stale")
                + _chunk("g3", "u8", doc_code="D08")
            ),
        ),
    ]


def test_hand_calculated_table_matches_code_values() -> None:
    rows = _hand_table()
    results = [score_case(case, gold, outcome) for case, gold, outcome in rows]
    cases = [case for case, _, _ in rows]

    # 逐 case 手算值（同 chunk 多 unit/重复 unit/空召回/部分命中/top-10/硬过滤）。
    expected = {
        "A": (1.0, 1.0, 1.0, 0.0),  # Recall, MRR, nDCG, empty
        "B": (1.0, 1.0, 1.0 / _idcg(2), 0.0),
        "C": (1.0, 1.0, 1.5 / _idcg(2), 0.0),
        "D": (
            0.75,
            0.5,
            (1 / math.log2(3) + 1 / math.log2(4)) / _idcg(4),
            0.0,
        ),
        "E": (0.0, 0.0, 0.0, 1.0),
        "F": (0.0, 0.0, 0.0, 0.0),
        "G": (1.0, 1.0, 1.0, 0.0),
    }
    for result in results:
        recall, mrr, ndcg, empty = expected[result.case_id]
        assert result.metrics["Recall@10"] == pytest.approx(recall), result.case_id
        assert result.metrics["MRR@10"] == pytest.approx(mrr), result.case_id
        assert result.metrics["nDCG@10"] == pytest.approx(ndcg), result.case_id
        assert result.metrics["empty_recall"] == pytest.approx(empty), result.case_id

    metrics = aggregate_metrics(cases, results)
    # 7 个 case 的 macro 平均；retrieved_units = 4+4+2+4+0+21+3；
    # 违规 unit = G 的 2 个（stale + forbidden_source）。
    assert set(metrics) & RETRIEVAL_KEYS == RETRIEVAL_KEYS
    assert metrics["Recall@10"] == pytest.approx((1 + 1 + 1 + 0.75 + 0 + 0 + 1) / 7)
    assert metrics["MRR@10"] == pytest.approx((1 + 1 + 1 + 0.5 + 0 + 0 + 1) / 7)
    assert metrics["nDCG@10"] == pytest.approx(
        (1 + 1 / _idcg(2) + 1.5 / _idcg(2) + (1 / math.log2(3) + 1 / math.log2(4)) / _idcg(4) + 0 + 0 + 1)
        / 7
    )
    assert metrics["hard_filter_violation_rate"] == pytest.approx(2 / 38)
    assert metrics["empty_recall_rate"] == pytest.approx(1 / 7)


# --------------------------------------------------------------------------- #
# 6. relevant_units 金标：选择 / 派生 / 两者皆空 / fail closed
# --------------------------------------------------------------------------- #


def _gold_case(case_id: str, *, expected=(), relevant=()) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        suite="t110",
        split="dev",
        stratum="exact",
        business_date="2026-10-28",
        question="T110 gold 解析",
        expected_kind="answer",
        expected_sources=tuple(expected),
        relevant_units=tuple(relevant),
        label_version="t110-1",
    )


def test_relevant_units_override_expected_sources_as_retrieval_gold(b0_index) -> None:
    source = {"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}
    other = {"doc_code": "D01", "unit_key": "sheet:物品位置:row:9"}
    resolved = resolve_case(_gold_case("G1", expected=(source,), relevant=(other,)), b0_index)

    assert resolved.unit_ids  # 答案出处来自 expected_sources
    assert resolved.relevant_unit_ids == resolve_case(
        _gold_case("G2", expected=(other,)), b0_index
    ).unit_ids
    assert resolved.relevant_unit_ids != resolved.unit_ids


def test_empty_relevant_units_falls_back_to_expected_sources(b0_index) -> None:
    source = {"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}
    resolved = resolve_case(_gold_case("G3", expected=(source,)), b0_index)

    assert resolved.relevant_unit_ids == resolved.unit_ids
    assert resolved.relevant_unit_ids


def test_both_gold_fields_empty_means_no_retrieval_gold(b0_index) -> None:
    resolved = resolve_case(_gold_case("G4"), b0_index)

    assert resolved.skipped is False
    assert resolved.sources == ()
    assert resolved.unit_ids == ()
    assert resolved.relevant_unit_ids == ()


def test_relevant_units_unknown_unit_key_fails_closed(b0_index) -> None:
    with pytest.raises(GoldUnresolved) as excinfo:
        resolve_case(
            _gold_case(
                "G5",
                relevant=({"doc_code": "D01", "unit_key": "sheet:物品位置:row:999"},),
            ),
            b0_index,
        )
    assert excinfo.value.reason == "unit_key_not_found"


def test_relevant_units_duplicate_unit_key_fails_closed(duplicate_key_index) -> None:
    with pytest.raises(GoldUnresolved) as excinfo:
        resolve_case(
            _gold_case(
                "G6",
                relevant=({"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"},),
            ),
            duplicate_key_index,
        )
    assert excinfo.value.reason == "duplicate_unit_key"


def test_relevant_units_locator_identity_conflict_fails_closed(duplicate_key_index) -> None:
    with pytest.raises(GoldUnresolved) as excinfo:
        resolve_case(
            _gold_case(
                "G7",
                relevant=({"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 8}},),
            ),
            duplicate_key_index,
        )
    assert excinfo.value.reason == "ambiguous_units"


def test_record_code_only_reference_fails_closed(b0_index) -> None:
    bad = {"doc_code": "D01", "record_code": "P01"}
    with pytest.raises(GoldUnresolved) as excinfo:
        resolve_case(_gold_case("G8", relevant=(bad,)), b0_index)
    assert excinfo.value.reason == "record_code_not_a_lookup_key"

    with pytest.raises(GoldUnresolved) as excinfo:
        resolve_case(_gold_case("G9", expected=(bad,)), b0_index)
    assert excinfo.value.reason == "record_code_not_a_lookup_key"


def test_locator_range_reference_returns_unit_set(badcase_index) -> None:
    # 整张表是范围型 gold：E03「NKA卖场」命中多个 unit（P0 N05 口径）。
    resolved = resolve_case(
        _gold_case("G10", relevant=({"doc_code": "E03", "locator": {"sheet": "NKA卖场"}},)),
        badcase_index,
    )

    assert len(resolved.relevant_unit_ids) > 1
    assert len(set(resolved.relevant_unit_ids)) == len(resolved.relevant_unit_ids)
