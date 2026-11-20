"""T-R1-102a：评分侧结构数字增量（M1 行号 / M2 枚举页头计数）。

主人 2026-11-17 批准的口径：只把产品自述的**结构 token** —— 引用 locator 的整数
（``第 {row} 行`` 的行号/表头行）与 ``outcome.pagination`` 的页头计数
（``total``/``page``/``page_size``/``returned``/``next_page``，仅 int）—— 并入
``value_no_fabricated`` 的允许数字。结构 token ≠ 业务值：金标/期望值/禁用值口径一律
不动，既不在金标/问题/参考答、也不在 locator/pagination 的数字仍判"编造"。

全部用合成实体（甲店 / 立牌 / 甲区），不建索引、不调 provider、不读私有证据。
运行：``.venv\\Scripts\\python.exe -B -m pytest <本文件> -q -p no:cacheprovider``
"""

from __future__ import annotations

from typing import Any

from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.gold import ResolvedGold
from mktkb.evaluation.p2_scoring import (
    CASE_STATUS_FAIL,
    CASE_STATUS_PASS,
    P2_PAGINATION_NUMBER_KEYS,
    P2ScoredCase,
    score_public_case,
)
from mktkb.evaluation.scorers import (
    EvalCitation,
    EvalOutcome,
    citation_structural_number_keys,
    score_case,
)

DOC_NAME = "D11_合成物品资料.xlsx"
DOC_CODE = "D11"
QUESTION = "列出甲店立牌的全部信息"
BUSINESS_DATE = "2026-10-28"
#: 两行合成记录：row 7（甲区）/ row 8（乙区），各自一个 unit 身份。
ROW_UNITS = {
    7: "22222222-2222-4222-8222-222222222221",
    8: "22222222-2222-4222-8222-222222222222",
}
DOCUMENT_CODES = {DOC_NAME: DOC_CODE}
SOURCE_INDEX = {
    unit_id: {"doc_code": DOC_CODE, "unit_key": f"sheet:合成表:row:{row}", "locator": {}}
    for row, unit_id in ROW_UNITS.items()
}

#: M1 形态：整行渲染 + ``第 7 行`` 行号 + 纯 a–f 记录指纹（指纹不产十进制数字）。
M1_TEXT = (
    "- 甲店：门店 甲店、物品 立牌、数量 两件、位置 甲区"
    "（第 7 行）（记录 abcdefab）（来源：合成物品资料）"
)
#: M2 形态：枚举页头 ``共 2 条，当前第 1 页显示 2 条`` + 两条记录行。
M2_TEXT = (
    "共 2 条，当前第 1 页显示 2 条。\n"
    "- 甲店：门店 甲店、物品 立牌、位置 甲区（第 7 行）\n"
    "- 甲店：门店 甲店、物品 立牌、位置 乙区（第 8 行）"
)
M2_PAGINATION = {
    "total": 2,
    "page": 1,
    "page_size": 10,
    "returned": 2,
    "has_more": False,
    "next_page": None,
}


def locator(row: int) -> dict[str, Any]:
    return {
        "sheet": "合成表",
        "row": row,
        "header_row": 6,
        "cells": [
            {"column": "A", "display": "甲店", "header": "门店"},
            {"column": "B", "display": "立牌", "header": "物品"},
            {"column": "D", "display": "甲区" if row == 7 else "乙区", "header": "位置"},
        ],
    }


def make_case() -> CaseSpec:
    return CaseSpec(
        case_id="SYN-102A",
        suite="synthetic",
        split="train",
        stratum="exact",
        business_date=BUSINESS_DATE,
        question=QUESTION,
        expected_kind="answer",
        expected_values=("甲区",),
        reference_answer="甲店立牌的位置是甲区",
    )


def source(row: int) -> dict[str, Any]:
    return {
        "source_id": ROW_UNITS[row],
        "document_name": DOC_NAME,
        "version_number": 1,
        "status": "active",
        "locator": locator(row),
    }


def product(
    text: str,
    sources: list[dict[str, Any]],
    *,
    pagination: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "answer",
        "text": text,
        "trace_id": "trace-102a",
        "trace_path": "rag",
        "sources": sources,
        "http_status": 200,
    }
    if pagination is not None:
        payload["pagination"] = dict(pagination)
    return payload


def score_product(
    text: str,
    sources: list[dict[str, Any]],
    *,
    pagination: dict[str, Any] | None = None,
) -> P2ScoredCase:
    case = make_case()
    row = {
        "case_id": case.case_id,
        "suite": case.suite,
        "stratum": case.stratum,
        "conversation_id": "conv-102a",
        "status": "ok",
        "error_code": None,
        "planned_turns": 1,
        "turns_executed": 1,
        "turns": [
            {
                "turn": 1,
                "status": "ok",
                "error_code": None,
                "product": product(text, sources, pagination=pagination),
            }
        ],
    }
    return score_public_case(
        case,
        row,
        document_codes=DOCUMENT_CODES,
        source_index=SOURCE_INDEX,
    )


def check_map(scored: P2ScoredCase) -> dict[str, dict[str, Any]]:
    return {check["check_id"]: check for check in scored.score.checks}


def m1_outcome() -> EvalOutcome:
    """P2 口径的归一化输出：引用只带 locator（含 int 行号），不带答案正文。"""
    citation = EvalCitation(
        doc_code=DOC_CODE,
        unit_key="sheet:合成表:row:7",
        unit_ids=(ROW_UNITS[7],),
        locator=locator(7),
        text="",
        kind="active",
    )
    return EvalOutcome(kind="answer", text=M1_TEXT, citations=(citation,))


def gold(case: CaseSpec) -> ResolvedGold:
    return ResolvedGold(
        case_id=case.case_id,
        requires_ocr=False,
        skipped=False,
        sources=(),
        unit_ids=(),
        relevant_unit_ids=(),
    )


# --------------------------------------------------------------------------- #
# 1. 验收 §4.1：M1 形状（第 7 行 + 全字段行）不再被判"编造"
# --------------------------------------------------------------------------- #


def test_m1_row_marker_is_grounded_by_locator_integer() -> None:
    scored = score_product(M1_TEXT, [source(7)])
    checks = check_map(scored)
    assert checks["value_hit"]["status"] == "pass", checks
    fabricated = checks["value_no_fabricated"]
    assert fabricated["status"] == "pass", fabricated
    # 结构 token 两个整数：row=7 与 header_row=6（GOLD 里没有 7）。
    assert fabricated["evidence"]["structural_numbers"] == 2, fabricated
    assert scored.score.status == CASE_STATUS_PASS, checks


# --------------------------------------------------------------------------- #
# 2. 验收 §4.2：M2 形状（枚举页头 共 2 条…）不再被判"编造"
# --------------------------------------------------------------------------- #


def test_m2_enumeration_header_counts_are_grounded_by_pagination() -> None:
    scored = score_product(M2_TEXT, [source(7), source(8)], pagination=M2_PAGINATION)
    checks = check_map(scored)
    assert checks["value_hit"]["status"] == "pass", checks
    fabricated = checks["value_no_fabricated"]
    assert fabricated["status"] == "pass", fabricated
    # locator 整数 {6,7,8} + 分页整数 {1,2,10} 共 6 个 key。
    assert fabricated["evidence"]["structural_numbers"] == 6, fabricated
    assert scored.score.status == CASE_STATUS_PASS, checks


# --------------------------------------------------------------------------- #
# 3. 验收 §4.3 反例：真编造数字仍然 fail（结构 token 不是"有引用就放行"）
# --------------------------------------------------------------------------- #


def test_number_outside_gold_question_and_structure_still_fails() -> None:
    scored = score_product(M1_TEXT + "另有 9 家分店正在装修。", [source(7)])
    checks = check_map(scored)
    fabricated = checks["value_no_fabricated"]
    assert fabricated["status"] == "fail", fabricated
    assert fabricated["evidence"]["extra"] == ["9"], fabricated
    assert scored.score.status == CASE_STATUS_FAIL, checks


def test_m2_header_claiming_more_than_pagination_still_fails() -> None:
    """页头写 3 条、产品分页计数是 2：3 没有出处 → 仍判编造。"""
    scored = score_product(
        M2_TEXT.replace("共 2 条", "共 3 条"), [source(7), source(8)], pagination=M2_PAGINATION
    )
    fabricated = check_map(scored)["value_no_fabricated"]
    assert fabricated["status"] == "fail", fabricated
    assert fabricated["evidence"]["extra"] == ["3"], fabricated


def test_m2_header_without_pagination_still_fails() -> None:
    """同一段页头答案、但产品没给 pagination → 2/1 没有出处，仍判编造。"""
    scored = score_product(M2_TEXT, [source(7), source(8)])
    fabricated = check_map(scored)["value_no_fabricated"]
    assert fabricated["status"] == "fail", fabricated
    assert fabricated["evidence"]["extra"] == ["1", "2"], fabricated


def test_pagination_structural_tokens_are_limited_to_five_int_keys() -> None:
    """只认五个计数键、只认 int：``revision``（非计数键）与字符串 ``page_size`` 不放行。"""
    pagination = dict(M2_PAGINATION, revision=42, page_size="15")
    text = M2_TEXT + "（版本 42，每页 15 条）"
    scored = score_product(text, [source(7), source(8)], pagination=pagination)
    fabricated = check_map(scored)["value_no_fabricated"]
    assert fabricated["status"] == "fail", fabricated
    assert fabricated["evidence"]["extra"] == ["15", "42"], fabricated


def test_pagination_number_keys_are_the_five_frozen_header_counts() -> None:
    assert P2_PAGINATION_NUMBER_KEYS == ("total", "page", "page_size", "returned", "next_page")


# --------------------------------------------------------------------------- #
# 4. 验收 §4.4 默认口径：不传结构集合时行为逐字不变（P1）
# --------------------------------------------------------------------------- #


def test_default_score_case_still_counts_row_marker_as_extra() -> None:
    case = make_case()
    outcome = m1_outcome()
    strict = score_case(case, gold(case), outcome)
    strict_check = strict.check("value_no_fabricated")
    assert strict_check is not None
    assert strict_check.status == "fail"
    assert strict_check.evidence["extra"] == ["7"], strict_check.evidence
    assert "structural_numbers" not in strict_check.evidence
    assert strict.status == CASE_STATUS_FAIL

    loose = score_case(
        case,
        gold(case),
        outcome,
        structural_number_keys=citation_structural_number_keys(outcome.citations),
    )
    loose_check = loose.check("value_no_fabricated")
    assert loose_check is not None
    assert loose_check.status == "pass", loose_check.evidence
    assert loose_check.evidence["structural_numbers"] == 2


def test_structural_keys_exclude_container_names_strings_and_bools() -> None:
    """容器身份键（文档名/路径）、字符串内容与 bool 都不是结构 token。"""
    citation = EvalCitation(
        doc_code=DOC_CODE,
        locator={
            "document_name": "D07_2026年价目表.xlsx",
            "path": "corpus/row-9.xlsx",
            "row": 7,
            "header_row": 6,
            "printed": True,
            "cells": [{"display": "010-00000001"}],
        },
        text="分机 8021",
    )
    assert citation_structural_number_keys([citation]) == frozenset({"7", "6"})
    assert citation_structural_number_keys([]) == frozenset()
