"""T-R1-102d：产品回合补分页（M2 端到端闭环）。

T-R1-102a 只把**评分侧**的结构数字打开；真实 run 的 ``outcome.pagination`` 仍为空，
因为 ``ProductTurn`` 不采集产品响应里的 ``pagination``。本文件守这条**链路**：

合成产品 HTTP 响应（``httpx.Response``）→ 回合构造点（``_ask_turn_inner``）→
``ProductTurn`` → ``as_dict()`` → 打分行 → ``normalize_product_outcome`` →
``value_no_fabricated``。

对照用例（同一条 M2 答案，唯一差别是产品有没有给分页）：
- 带分页 → ``pagination`` 非空且 ``value_no_fabricated=pass``；
- 抽掉分页 → ``pagination == {}`` 且回到 ``fail``（证明是链路生效，不是断言放宽）。

全部合成数据：不发真实/离线产品请求、不建库、不建索引、不读私有证据。
运行：``.venv\\Scripts\\python.exe -B -m pytest <本文件> -q -p no:cacheprovider``
"""

from __future__ import annotations

import asyncio
import functools
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_scoring import (  # noqa: E402
    CASE_STATUS_FAIL,
    CASE_STATUS_PASS,
    P2ScoredCase,
    normalize_product_outcome,
    score_public_case,
)
from mktkb.evaluation.product_adapter import (  # noqa: E402
    ProductEvalAdapter,
    ProductTurn,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ORIGIN = "http://p2-eval.testserver"
CONVERSATION_ID = "conv-102d"
CLIENT_REQUEST_ID = "p2req-102d"
CASE_ID = "SYN-102D"
DOC_NAME = "D11_合成物品资料.xlsx"
DOC_CODE = "D11"
BUSINESS_DATE = "2026-10-28"
QUESTION = "列出甲店立牌的全部信息"
#: 两行合成记录：row 7（甲区）/ row 8（乙区）。
ROW_UNITS = {
    7: "22222222-2222-4222-8222-222222222221",
    8: "22222222-2222-4222-8222-222222222222",
}
#: M2 形态：枚举页头 ``共 2 条，当前第 1 页显示 2 条`` + 两条记录行（数字无金标出处）。
M2_TEXT = (
    "共 2 条，当前第 1 页显示 2 条。\n"
    "- 甲店：门店 甲店、物品 立牌、位置 甲区（第 7 行）\n"
    "- 甲店：门店 甲店、物品 立牌、位置 乙区（第 8 行）"
)
#: 交接单 §3 给的分页形状（产品实际还会带 ``next_page``，见下一常量）。
M2_PAGINATION = {"total": 2, "page": 1, "page_size": 10, "returned": 2, "has_more": False}
#: ``conversations.schemas.PaginationView`` 的真实序列化形状（``next_page`` 显式为 null）。
M2_PAGINATION_FULL = dict(M2_PAGINATION, next_page=None)


def asyncio_test(func):
    """仓库没有 pytest-asyncio：同一事件循环跑一个 async 用例（保留 fixture 签名）。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


# --------------------------------------------------------------------------- #
# 合成产品响应 + 回合构造点（不启动隔离应用：本用例只验「响应 -> 回合 -> 评分」）
# --------------------------------------------------------------------------- #


class _StubClient:
    """替身产品 HTTP 客户端：返回给定响应，一次也不出网（闸门另行实测）。"""

    def __init__(self, response: httpx.Response, *, delay: float = 0.0) -> None:
        self._response = response
        self._delay = float(delay)
        self.calls = 0

    async def post(self, _url: str, **_kwargs: Any) -> httpx.Response:
        self.calls += 1
        if self._delay > 0:
            await asyncio.sleep(self._delay)
        return self._response

    async def aclose(self) -> None:
        return None


class _StubSession:
    """``_UserSession`` 的最小观测面：``client.post`` + 写请求头。"""

    write_headers = {"Origin": ORIGIN, "X-CSRF-Token": "p2-eval-csrf"}

    def __init__(self, response: httpx.Response, *, delay: float = 0.0) -> None:
        self.client = _StubClient(response, delay=delay)


def response_of(payload: dict[str, Any], *, status: int = 200) -> httpx.Response:
    request = httpx.Request(
        "POST", f"{ORIGIN}/api/v1/conversations/{CONVERSATION_ID}/messages"
    )
    return httpx.Response(
        status, json=payload, request=request, headers={"X-Trace-ID": "trace-102d"}
    )


def source(row: int) -> dict[str, Any]:
    return {
        "source_id": ROW_UNITS[row],
        "document_name": DOC_NAME,
        "version_number": 1,
        "status": "active",
        "locator": {
            "sheet": "合成表",
            "row": row,
            "header_row": 6,
            "cells": [
                {"column": "A", "display": "甲店", "header": "门店"},
                {"column": "B", "display": "立牌", "header": "物品"},
                {"column": "D", "display": "甲区" if row == 7 else "乙区", "header": "位置"},
            ],
        },
    }


def product_payload(
    text: str,
    *,
    pagination: dict[str, Any] | None = None,
    with_pagination_key: bool = True,
) -> dict[str, Any]:
    """合成产品响应：字段与 ``conversations.schemas.AskResult`` 同形。"""

    payload: dict[str, Any] = {
        "request_id": "p2res-102d",
        "message_id": "p2msg-102d",
        "kind": "answer",
        "text": text,
        "revision": 1,
        "sources": [source(7), source(8)],
        "candidates": [],
        "conflicts": [],
        "missing_fields": [],
        "error_code": None,
        "retryable": False,
    }
    if with_pagination_key:
        # 非枚举答复时产品回的是 ``pagination: null``，不是"没有这个键"。
        payload["pagination"] = None if pagination is None else dict(pagination)
    return payload


async def turn_from(
    out_dir: Path,
    payload: dict[str, Any],
    *,
    delay: float = 0.0,
    turn_timeout_seconds: float = 60.0,
) -> ProductTurn:
    """走**真实回合构造点**（``_ask_turn_inner``）拿到 ProductTurn。

    不 ``start()``：本用例不建隔离库、不发产品请求，只验「产品响应 → 回合」这段取值。
    ``_app``/``_qa`` 为 None 时既有观测面各自降级（revision/候选/trace 取不到→空），
    不影响本用例断言的字段；超时用例靠 ``delay`` 触发客户端硬截止。
    """
    adapter = ProductEvalAdapter(out_dir, turn_timeout_seconds=turn_timeout_seconds)
    adapter._sessions = {  # noqa: SLF001 - 只替换 HTTP 观测面，不动产品逻辑
        "employee": _StubSession(response_of(payload), delay=delay)
    }
    try:
        return await adapter._ask_turn_inner(  # noqa: SLF001 - 被测的正是这个构造点
            QUESTION,
            user_id="employee",
            conversation_id=CONVERSATION_ID,
            client_request_id=CLIENT_REQUEST_ID,
        )
    finally:
        await adapter.close()


def turn_row(turn: ProductTurn) -> dict[str, Any]:
    """打分行：与 ``p2_runner`` 落盘形状一致（``product`` 就是 ``as_dict``）。"""
    return {
        "case_id": CASE_ID,
        "suite": "synthetic",
        "stratum": "exact",
        "conversation_id": CONVERSATION_ID,
        "status": "ok",
        "error_code": None,
        "planned_turns": 1,
        "turns_executed": 1,
        "turns": [
            {
                "turn": 1,
                "status": "ok",
                "error_code": None,
                "product": turn.as_dict(include_text=True),
            }
        ],
    }


def make_case() -> CaseSpec:
    return CaseSpec(
        case_id=CASE_ID,
        suite="synthetic",
        split="train",
        stratum="exact",
        business_date=BUSINESS_DATE,
        question=QUESTION,
        expected_kind="answer",
        expected_values=("甲区",),
        reference_answer="甲店立牌的位置是甲区",
    )


def score(turn: ProductTurn) -> P2ScoredCase:
    return score_public_case(make_case(), turn_row(turn), document_codes={DOC_NAME: DOC_CODE})


def check_map(scored: P2ScoredCase) -> dict[str, dict[str, Any]]:
    return {check["check_id"]: check for check in scored.score.checks}


# --------------------------------------------------------------------------- #
# 1. 验收 §3.1/§3.2：回合携带响应里的分页；缺省就是 {}
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_turn_carries_pagination_from_product_response(tmp_path: Path) -> None:
    turn = await turn_from(
        tmp_path, product_payload(M2_TEXT, pagination=M2_PAGINATION_FULL)
    )
    assert dict(turn.pagination) == M2_PAGINATION_FULL
    payload = turn.as_dict(include_text=False)
    assert payload["pagination"] == M2_PAGINATION_FULL
    # 只允许 int/bool（``next_page`` 可为 None）：不夹带任何文本。
    assert all(
        type(value) in (int, bool) or (key == "next_page" and value is None)
        for key, value in payload["pagination"].items()
    ), payload["pagination"]


@asyncio_test
async def test_pagination_without_next_page_key_is_not_invented(tmp_path: Path) -> None:
    """交接单 §3 的形状（没有 ``next_page``）：按原样保留，不补 ``next_page``。"""
    turn = await turn_from(tmp_path, product_payload(M2_TEXT, pagination=M2_PAGINATION))
    assert dict(turn.pagination) == M2_PAGINATION
    assert "next_page" not in turn.as_dict(include_text=False)["pagination"]
    assert check_map(score(turn))["value_no_fabricated"]["status"] == "pass"


@asyncio_test
async def test_pagination_null_or_absent_is_empty_not_a_default_page(tmp_path: Path) -> None:
    """产品没给分页 → ``{}``：不补"第 1 页/共 0 条"。"""
    null_turn = await turn_from(tmp_path / "null", product_payload(M2_TEXT))
    absent_turn = await turn_from(
        tmp_path / "absent",
        product_payload(M2_TEXT, with_pagination_key=False),
    )
    for turn in (null_turn, absent_turn):
        assert dict(turn.pagination) == {}
        assert turn.as_dict(include_text=False)["pagination"] == {}


@asyncio_test
async def test_pagination_keeps_only_int_and_bool_whitelist(tmp_path: Path) -> None:
    """白名单 + 原类型：字符串计数、bool 冒充计数、未知文本键一律丢弃。"""
    raw = {
        "page": 1,
        "page_size": "10",  # 字符串：丢弃（不做隐式转换）
        "total": True,  # bool：丢弃（不算计数）
        "returned": 2,
        "has_more": 1,  # int 冒充 bool：丢弃
        "next_page": 2,
        "revision": 42,  # 非页头键：不进分页块
        "note": "共 2 条",
    }
    turn = await turn_from(tmp_path, product_payload(M2_TEXT, pagination=raw))
    assert dict(turn.pagination) == {"page": 1, "returned": 2, "next_page": 2}


@asyncio_test
async def test_timeout_turn_has_no_pagination(tmp_path: Path) -> None:
    """超时没有产品响应 → 不得凭空出现分页。"""
    turn = await turn_from(
        tmp_path,
        product_payload(M2_TEXT, pagination=M2_PAGINATION_FULL),
        delay=0.2,
        turn_timeout_seconds=0.02,
    )
    assert turn.kind == "timeout", turn.as_dict(include_text=False)
    assert dict(turn.pagination) == {}
    assert turn.as_dict(include_text=False)["pagination"] == {}


# --------------------------------------------------------------------------- #
# 2. 验收 §3.3：真链路对照 —— 有分页 → pass；抽掉分页 → fail
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_end_to_end_pagination_grounds_m2_header_counts(tmp_path: Path) -> None:
    turn = await turn_from(
        tmp_path, product_payload(M2_TEXT, pagination=M2_PAGINATION_FULL)
    )
    outcome = normalize_product_outcome(
        {"product": turn.as_dict(include_text=True)},
        document_codes={DOC_NAME: DOC_CODE},
    )
    assert dict(outcome.pagination) == dict(turn.pagination)
    assert dict(outcome.pagination)  # 非空：真实 run 的 outcome.pagination 有值了

    scored = score(turn)
    checks = check_map(scored)
    assert checks["value_hit"]["status"] == "pass", checks
    fabricated = checks["value_no_fabricated"]
    assert fabricated["status"] == "pass", fabricated
    # locator 整数 {6,7,8} + 分页整数 {1,2,10} 共 6 个 key。
    assert fabricated["evidence"]["structural_numbers"] == 6, fabricated
    assert scored.score.status == CASE_STATUS_PASS, checks


@asyncio_test
async def test_end_to_end_without_pagination_falls_back_to_fail(tmp_path: Path) -> None:
    """同一条 M2 答案，只把分页抽掉：链路上没有出处 → 回到 fail（不是断言被放宽）。"""
    turn = await turn_from(tmp_path, product_payload(M2_TEXT))
    outcome = normalize_product_outcome(
        {"product": turn.as_dict(include_text=True)},
        document_codes={DOC_NAME: DOC_CODE},
    )
    assert dict(outcome.pagination) == {}

    scored = score(turn)
    checks = check_map(scored)
    assert checks["value_hit"]["status"] == "pass", checks  # 只有编造判定该变
    fabricated = checks["value_no_fabricated"]
    assert fabricated["status"] == "fail", fabricated
    assert fabricated["evidence"]["extra"] == ["1", "2"], fabricated
    # 只剩引用 locator 的整数 {6,7,8}；分页那 3 个计数没有出处（有分页时是 6）。
    assert fabricated["evidence"]["structural_numbers"] == 3, fabricated
    assert scored.score.status == CASE_STATUS_FAIL, checks


@asyncio_test
async def test_pagination_only_grounds_the_counts_the_product_reported(tmp_path: Path) -> None:
    """页头写 3 条、产品分页是 2 条：3 仍没有出处 → 仍判编造。"""
    turn = await turn_from(
        tmp_path,
        product_payload(M2_TEXT.replace("共 2 条", "共 3 条"), pagination=M2_PAGINATION_FULL),
    )
    fabricated = check_map(score(turn))["value_no_fabricated"]
    assert fabricated["status"] == "fail", fabricated
    assert fabricated["evidence"]["extra"] == ["3"], fabricated
