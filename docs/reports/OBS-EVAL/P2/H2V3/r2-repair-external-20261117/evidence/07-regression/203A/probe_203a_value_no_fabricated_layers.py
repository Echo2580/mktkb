"""T-R2-203A 探针：``total`` 1→2 后新出现的数字在**评分两层**各自是否有出处。

两层口径（代码事实）：

- **P2 层**（``p2_scoring.score_public_case``，p2_scoring.py:1003-1013）：结构 token =
  ``citation_structural_number_keys(outcome.citations)``
  ∪ ``_pagination_number_keys(outcome.pagination)``（p2_scoring.py:837-853，只认
  ``total/page/page_size/returned/next_page`` 且必须 ``int``），并入
  ``value_no_fabricated`` 的允许集合（scorers.py:714-735）。
- **P1 层**（``runner.score_case``，runner.py:1578/1622/1802/2112/2119）：**不传**
  ``allowed_number_keys``、也不传 ``structural_number_keys`` ⇒ 允许集合只有
  ``_gold_number_keys(case)``（scorers.py:422-429：题面/金标/参考答案/业务日期）。

要回答的问题：本批把 ``total`` 由 1 变 2 后，页头新出现的 ``2`` 在两层是否各有出处？
若无出处，会不会**新增** ``value_no_fabricated`` fail？

全部合成数据；零出站（``t09_network_guard`` teardown 断言 ``external == []``，本文件
每个用例再显式断言一次），子进程封死。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("t09_network_guard", "no_subprocess")

from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_scoring import (  # noqa: E402
    P2_PAGINATION_NUMBER_KEYS,
    _pagination_number_keys,
    _resolved_without_index,
    score_public_case,
)
from mktkb.evaluation.scorers import EvalOutcome, score_case  # noqa: E402

DOC_NAME = "合成物品资料"
DOC_CODE = "D-203A"
STORE_DOC_NAME = "合成合作店家信息"
STORE_DOC_CODE = "D-203A-S"
QUESTION = "样品桌的位置在哪里，合作状态分别是什么？"
#: 金标只有业务值，**不含任何计数**（这是"页头数字必须靠结构 token 才有出处"的前提）
GOLD_VALUES = ("子区3号架",)
REFERENCE = "样品桌的位置是子区3号架，合作状态是合作中"

LOCATOR = {
    "sheet": "台账",
    "row": 4,
    "header_row": 3,
    "cells": [
        {"column": "A", "display": "澄江店", "header": "门店"},
        {"column": "B", "display": "样品桌", "header": "物品"},
    ],
}
STORE_LOCATOR = {
    "sheet": "台账",
    "row": 4,
    "header_row": 3,
    "cells": [
        {"column": "B", "display": "澄江店", "header": "店家"},
        {"column": "D", "display": "合作中", "header": "合作状态"},
    ],
}

#: 改前（202C 之前）C29 形态：只有物品行 → 页头 1/1。
TEXT_BEFORE = (
    "共 1 条，当前第 1 页显示 1 条。\n"
    "- 澄江店的样品桌：位置 子区3号架（来源：合成物品资料）\n"
    "已显示全部。"
)
#: 改后：物品行 + 联结店家行 → 页头 2/2（本批实测形态）。
TEXT_AFTER = (
    "共 2 条，当前第 1 页显示 2 条。\n"
    "- 澄江店的样品桌：位置 子区3号架（来源：合成物品资料）\n"
    "- 澄江店：合作状态 合作中（来源：合成合作店家信息）\n"
    "已显示全部。"
)

PAGINATION_BEFORE = {"page": 1, "page_size": 10, "total": 1, "returned": 1, "has_more": False, "next_page": None}
PAGINATION_AFTER = {"page": 1, "page_size": 10, "total": 2, "returned": 2, "has_more": False, "next_page": None}


def _case(*, expected_values: tuple[str, ...] = GOLD_VALUES) -> CaseSpec:
    return CaseSpec(
        case_id="R203A-LAYERS",
        suite="synthetic",
        split="train",
        stratum="exact",
        business_date="2026-09-30",
        question=QUESTION,
        expected_kind="answer",
        expected_values=expected_values,
        reference_answer=REFERENCE,
    )


def _sources() -> list[dict]:
    return [
        {
            "source_id": "U-203a-item",
            "document_name": DOC_NAME,
            "locator": LOCATOR,
            "status": "active",
        },
        {
            "source_id": "U-203a-store",
            "document_name": STORE_DOC_NAME,
            "locator": STORE_LOCATOR,
            "status": "active",
        },
    ]


def _p2(text: str, pagination: dict | None) -> dict:
    product: dict = {"kind": "answer", "text": text, "sources": _sources()}
    if pagination is not None:
        product["pagination"] = pagination
    case = _case()
    case_row = {
        "case_id": case.case_id,
        "status": "ok",
        "planned_turns": 1,
        "turns": ({"turn": 1, "status": "ok", "product": product},),
    }
    scored = score_public_case(
        case,
        case_row,
        document_codes={DOC_NAME: DOC_CODE, STORE_DOC_NAME: STORE_DOC_CODE},
    )
    return _check(scored, "value_no_fabricated")


def _as_dict(item) -> dict:
    """``CaseCheck`` 是 dataclass，P2ScoredCase 的 checks 是 dict —— 统一成 dict 便于断言。"""
    if isinstance(item, dict):
        return item
    return {
        "check_id": str(item.check_id),
        "status": str(item.status),
        "evidence": dict(item.evidence or {}),
    }


def _check(scored, check_id: str) -> dict:
    # ``score_public_case`` 返回 P2ScoredCase(.score.checks)；``score_case`` 返回 CaseResult(.checks)
    inner = getattr(scored, "score", scored)
    checks = [_as_dict(item) for item in inner.checks]
    found = [item for item in checks if item["check_id"] == check_id]
    assert len(found) == 1, (check_id, checks)
    return found[0]


# --------------------------------------------------------------------------- #
# 1. P2 层：新出现的 2 有出处（pagination 随答案下发时）
# --------------------------------------------------------------------------- #
def test_p2_after_text_is_grounded_by_product_pagination(t09_network_guard):
    check = _p2(TEXT_AFTER, PAGINATION_AFTER)
    assert check["status"] == "pass", check
    assert check["evidence"].get("extra") is None, check
    # 结构 token 至少含页头的 2 / 1（total, returned, page）
    assert check["evidence"].get("structural_numbers", 0) >= 2, check
    assert t09_network_guard.snapshot()["external"] == []


def test_p2_before_text_is_grounded_too(t09_network_guard):
    """改前基线同样 pass（1/1 也有出处）——说明这不是"改后才被放行"。"""

    check = _p2(TEXT_BEFORE, PAGINATION_BEFORE)
    assert check["status"] == "pass", check
    assert check["evidence"].get("extra") is None, check
    assert t09_network_guard.snapshot()["external"] == []


def test_p2_after_text_without_pagination_is_fabricated(t09_network_guard):
    """分页不下发时：页头 1/2 都没有出处 ⇒ 新增 fail（这是唯一的新风险面）。"""

    check = _p2(TEXT_AFTER, None)
    assert check["status"] == "fail", check
    assert set(check["evidence"]["extra"]) == {"1", "2"}, check
    assert t09_network_guard.snapshot()["external"] == []


# --------------------------------------------------------------------------- #
# 2. 白名单本身：只认五个 int 键（负例，证明没被放宽）
# --------------------------------------------------------------------------- #
def test_pagination_key_whitelist_is_exactly_five_int_keys(t09_network_guard):
    assert P2_PAGINATION_NUMBER_KEYS == ("total", "page", "page_size", "returned", "next_page")
    assert _pagination_number_keys({"total": 2, "returned": "2", "revision": 42, "has_more": 1}) == {
        "2"
    }
    assert _pagination_number_keys({"total": True, "page": 1}) == {"1"}
    assert _pagination_number_keys(None) == frozenset()
    assert t09_network_guard.snapshot()["external"] == []


# --------------------------------------------------------------------------- #
# 3. P1 层（runner.score_case 口径）：没有任何结构 token
# --------------------------------------------------------------------------- #
def _p1(text: str, *, expected_values: tuple[str, ...] = GOLD_VALUES) -> dict:
    case = _case(expected_values=expected_values)
    outcome = EvalOutcome(
        kind="answer",
        text=text,
        citations=(),
        pagination=PAGINATION_AFTER,
        path="rag",
    )
    # 与 runner.py:1578/1622/1802/2112/2119 同一调用口径：不传任何 opt-in 集合。
    scored = score_case(case, _resolved_without_index(case), outcome)
    return _check(scored, "value_no_fabricated")


def test_p1_layer_ignores_pagination_entirely(t09_network_guard):
    """P1 口径：即使 outcome 带 pagination，页头数字仍全部算"无出处"。"""

    before = _p1(TEXT_BEFORE)
    after = _p1(TEXT_AFTER)
    assert before["status"] == "fail", before
    assert set(before["evidence"]["extra"]) == {"1"}, before
    assert after["status"] == "fail", after
    assert set(after["evidence"]["extra"]) == {"1", "2"}, after
    # 结构 token 从未参与 P1（evidence 里不出现 structural_numbers）
    assert "structural_numbers" not in before["evidence"], before
    assert t09_network_guard.snapshot()["external"] == []


def test_p1_layer_flips_pass_to_fail_only_if_gold_contains_the_old_count(t09_network_guard):
    """条件性新失败：金标/题面恰好含 ``1`` 时，P1 口径由 pass（改前）变 fail（改后）。"""

    gold_with_one = ("子区3号架", "1")
    before = _p1(TEXT_BEFORE, expected_values=gold_with_one)
    after = _p1(TEXT_AFTER, expected_values=gold_with_one)
    assert before["status"] == "pass", before
    assert after["status"] == "fail", after
    assert after["evidence"]["extra"] == ["2"], after
    assert t09_network_guard.snapshot()["external"] == []
