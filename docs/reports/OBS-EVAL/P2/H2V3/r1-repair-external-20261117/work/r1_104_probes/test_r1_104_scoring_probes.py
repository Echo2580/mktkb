"""T-R1-104 独立验收探针（评分侧）：结构 token 是否被用来"放水"。

只调用产品打分入口 ``score_public_case``（P2 全路径：product 响应 → normalize →
``score_case``），不复制 scorer 内部逻辑。

四条：
1. 自造业务数字 ``87``（不在题面/金标/引用 locator/分页）→ ``value_no_fabricated=fail``；
2. 分页谎报：正文写 ``共 3 条``、产品 ``pagination.total=2`` → 仍 fail，``extra=["3"]``；
3. 行号不在 locator 里（正文 ``第 9 行``、locator ``row=7``）→ 仍 fail，``extra=["9"]``；
4. 对照（防空转）：同样的 ``第 7 行`` + locator ``row=7`` → pass 且 ``structural_numbers>=1``。

全部合成数据；不读 var/.env；不发网络请求。
运行：``.venv\\Scripts\\python.exe -B -m pytest <本文件> -q -p no:cacheprovider``
"""

from __future__ import annotations

import sys
from pathlib import Path

for _root in Path(__file__).resolve().parents:
    if (_root / "backend" / "src").is_dir():
        sys.path.insert(0, str(_root / "backend" / "src"))
        break

from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_scoring import score_public_case  # noqa: E402

DOC_NAME = "合成物品资料"
DOC_CODE = "D-R1104"
QUESTION = "列出甲店立牌的记录"
ROW = 7


def _locator(row: int = ROW) -> dict:
    return {
        "sheet": "合成表",
        "row": row,
        "header_row": 6,
        "cells": [
            {"column": "A", "display": "甲店", "header": "门店"},
            {"column": "B", "display": "甲区", "header": "位置"},
        ],
    }


def _product(text: str, *, pagination: dict | None = None, locator: dict | None = None) -> dict:
    product = {
        "kind": "answer",
        "text": text,
        "sources": [
            {
                "source_id": "U-r1104-row7",
                "document_name": DOC_NAME,
                "locator": _locator() if locator is None else locator,
                "status": "active",
            }
        ],
    }
    if pagination is not None:
        product["pagination"] = pagination
    return product


def _score(product: dict):
    case = CaseSpec(
        case_id="R1104-PROBE",
        suite="synthetic",
        split="train",
        stratum="exact",
        business_date="2026-10-28",
        question=QUESTION,
        expected_kind="answer",
        expected_values=("甲区",),
        reference_answer="甲店立牌的位置是甲区",
    )
    case_row = {
        "case_id": case.case_id,
        "status": "ok",
        "planned_turns": 1,
        "turns": ({"turn": 1, "status": "ok", "product": product},),
    }
    return score_public_case(case, case_row, document_codes={DOC_NAME: DOC_CODE})


def _check(scored, check_id: str) -> dict:
    found = [item for item in scored.score.checks if item.get("check_id") == check_id]
    assert len(found) == 1, (check_id, scored.score.checks)
    return found[0]


# --------------------------------------------------------------------------- #
# 1. 编造业务数字
# --------------------------------------------------------------------------- #


def test_probe_fabricated_business_number_still_fails() -> None:
    """``87`` 不在题面/金标/参考答/citation/locator/分页 → 结构 token 不得放行。"""

    product = _product(
        "共 2 条，当前第 1 页显示 2 条。甲店的立牌位置是甲区。另有 87 家分店正在装修。",
        pagination={"page": 1, "page_size": 10, "total": 2, "returned": 2},
    )
    check = _check(_score(product), "value_no_fabricated")
    assert check["status"] == "fail", check
    assert check["evidence"]["extra"] == ["87"], check
    assert _check(_score(product), "value_hit")["status"] == "pass"


# --------------------------------------------------------------------------- #
# 2. 分页谎报
# --------------------------------------------------------------------------- #


def test_probe_pagination_lie_still_fails() -> None:
    """正文 ``共 3 条``，产品分页 ``total=2``：谎报的数字没有出处。"""

    product = _product(
        "共 3 条，当前第 1 页显示 2 条。甲店的立牌位置是甲区。",
        pagination={"page": 1, "page_size": 10, "total": 2, "returned": 2},
    )
    check = _check(_score(product), "value_no_fabricated")
    assert check["status"] == "fail", check
    assert check["evidence"]["extra"] == ["3"], check


def test_probe_pagination_counts_are_grounded_only_when_reported() -> None:
    """对照：同一段页头在分页存在时 pass；只差 ``pagination`` 一个字段即 fail。"""

    text = "共 2 条，当前第 1 页显示 2 条。甲店的立牌位置是甲区。"
    pagination = {"page": 1, "page_size": 10, "total": 2, "returned": 2}
    good = _check(_score(_product(text, pagination=pagination)), "value_no_fabricated")
    assert good["status"] == "pass", good
    assert good["evidence"].get("structural_numbers", 0) >= 3, good

    without = _check(_score(_product(text)), "value_no_fabricated")
    assert without["status"] == "fail", without
    assert set(without["evidence"]["extra"]) == {"1", "2"}, without


# --------------------------------------------------------------------------- #
# 3. 不在 locator 里的行号
# --------------------------------------------------------------------------- #


def test_probe_row_number_not_backed_by_locator_still_fails() -> None:
    """locator 只有 ``row=7``：正文写 ``第 9 行`` 时 9 没有出处。"""

    product = _product("甲店的立牌位置是甲区，见合成表第 9 行。")
    check = _check(_score(product), "value_no_fabricated")
    assert check["status"] == "fail", check
    assert check["evidence"]["extra"] == ["9"], check


def test_probe_control_locator_row_number_passes() -> None:
    """对照：正文写 ``第 7 行`` 且 locator ``row=7`` → pass（探针非空转）。"""

    product = _product("甲店的立牌位置是甲区，见合成表第 7 行。")
    check = _check(_score(product), "value_no_fabricated")
    assert check["status"] == "pass", check
    assert check["evidence"].get("extra") is None, check
    assert check["evidence"].get("structural_numbers", 0) >= 1, check


# --------------------------------------------------------------------------- #
# 4. 分页白名单的类型/键面不得被放宽
# --------------------------------------------------------------------------- #


def test_probe_non_int_pagination_counts_do_not_ground_numbers() -> None:
    """``total="2"`` / ``returned="2"``（字符串）不做隐式转换：页头 2 仍判编造。"""

    product = _product(
        "共 2 条，当前第 1 页显示 2 条。甲店的立牌位置是甲区。",
        pagination={"page": 1, "total": "2", "returned": "2"},
    )
    check = _check(_score(product), "value_no_fabricated")
    assert check["status"] == "fail", check
    assert set(check["evidence"]["extra"]) == {"2"}, check


def test_probe_non_count_pagination_key_does_not_ground_numbers() -> None:
    """``revision=42`` 不是页头计数：正文里的 42 仍是编造。"""

    product = _product(
        "甲店的立牌位置是甲区。本轮修订号 42。",
        pagination={"page": 1, "total": 1, "returned": 1, "revision": 42},
    )
    check = _check(_score(product), "value_no_fabricated")
    assert check["status"] == "fail", check
    assert check["evidence"]["extra"] == ["42"], check


# --------------------------------------------------------------------------- #
# 5. 已知边界（102a §未覆盖 3 的既有口径，非本次放水）：locator 内任意 int 都算结构 token
# --------------------------------------------------------------------------- #


def test_probe_locator_int_business_value_is_grounded_by_structure() -> None:
    """观测记录：locator 里非排除键的整数（此处 ``quantity=5``）会进结构集合。

    102a 报告 §未覆盖 3 已声明该边界（"locator 内**任意**非排除键整数都会放行"）。
    本用例把现状固化为可执行证据：答案里的 5 不在金标/题面/引用文本里，却因 locator
    整数而 pass。它是**已批准口径的残余风险**，不是本批新增的隐性放宽。
    """

    product = _product(
        "甲店的立牌位置是甲区，共 5 件。",
        locator={**_locator(), "quantity": 5},
    )
    check = _check(_score(product), "value_no_fabricated")
    assert check["status"] == "pass", check
    assert check["evidence"].get("extra") is None, check
    assert "5" not in QUESTION  # 数字 5 也不在题面里，唯一出处是 locator 整数


# --------------------------------------------------------------------------- #
# 6. 采集侧（102d）：分页只按白名单/原类型保留，不补默认页
# --------------------------------------------------------------------------- #


def test_probe_adapter_pagination_whitelist_and_types() -> None:
    """``_pagination_of``：缺失/None → ``{}``；字符串/布尔计数丢弃；非白名单键丢弃。"""

    from mktkb.evaluation.product_adapter import _pagination_of

    assert _pagination_of(None) == {}
    assert _pagination_of({}) == {}
    assert _pagination_of({"pagination": None}) == {}
    assert _pagination_of({"pagination": {"total": "2", "page": 1, "returned": True,
                                          "revision": 42, "next_page": None}}) == {
        "page": 1,
        "next_page": None,
    }
    assert _pagination_of({"pagination": {"total": 2, "has_more": 1}}) == {"total": 2}
