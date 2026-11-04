"""S2-J2 定向测试：受控 OCR 预算包装（同一账本、固定最高价、1 attempt、13 次、每页 tile=1）。

只使用隔离账本（``tmp_path``）与本地替身 OCRGateway；不发真实网络、不读 `.env`、
不写真实 budget/ledger/GO；验证失败/超时/中断全额保留与发送前拒绝。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mktkb.providers.ocr_budgeted import (
    OCR_TABLE_PRICE_CNY,
    OCR_TEXT_PRICE_CNY,
    BudgetedOCRGateway,
    OCRBudgetRefused,
)
from mktkb.providers.types import (
    OCRInput,
    OCRPageResult,
    OCRRateLimited,
    OCRTimeout,
    OCRUnavailable,
)
from mktkb.rag.budget import BudgetLedger, BudgetLedgerInvalid

STAGE = "S2-J2-OCR-TEST"
SECRET = "sk-S2J2-OCR-SYNTH-SECRET-DO-NOT-LEAK-0123456789"


def make_ledger(tmp_path: Path, *, stage_limit: float = 9.66, post_guard=None) -> BudgetLedger:
    ledger_path = tmp_path / "live-ledger.jsonl"
    budget_path = tmp_path / "budget.json"
    ledger_path.write_text(
        json.dumps(
            {
                "event": "historical_import",
                "accounted_cny": 0.03,
                "provider_billed_cny": None,
                "note": "S2-J2 isolated OCR test ledger",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    budget_path.write_text(
        json.dumps(
            {
                "limit_cny": 10.0,
                "historical_conservative_accounted_cny": 0.03,
                "stages": {STAGE: stage_limit},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return BudgetLedger(
        ledger_path,
        budget_path,
        stage=STAGE,
        stage_limit_cny=stage_limit,
        max_requests=400,
        post_reserve_guard=post_guard,
    )


class FakeOCRGateway:
    def __init__(self, outcome=None) -> None:
        self.outcome = outcome if outcome is not None else OCRPageResult(text="识别文本", provider_request_id="req-ocr-1")
        self.calls: list[tuple[int, str]] = []

    def recognize(self, page: OCRInput, *, mode: str) -> OCRPageResult:
        self.calls.append((int(page.page), str(mode)))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def page(number: int = 1) -> OCRInput:
    return OCRInput(content=b"fake-png-bytes-" + bytes([number % 250]), mime_type="image/png", page=number)


def events(ledger: BudgetLedger) -> list[dict]:
    return [
        json.loads(line)
        for line in ledger.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def wrapper(ledger: BudgetLedger, inner: FakeOCRGateway, **overrides) -> BudgetedOCRGateway:
    return BudgetedOCRGateway(
        inner,
        ledger=ledger,
        **overrides,
    )


def test_text_call_reserves_highest_price_and_settles_without_release(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    result = wrapper(ledger, inner).recognize(page(1), mode="text")
    assert result.text == "识别文本"
    assert inner.calls == [(1, "text")]
    rows = events(ledger)
    reserved = [row for row in rows if row.get("event") == "reserved"]
    results = [row for row in rows if row.get("event") == "result"]
    assert len(reserved) == 1 and len(results) == 1
    assert reserved[0]["kind"] == "ocr"
    assert reserved[0]["reserve_cny"] == float(OCR_TEXT_PRICE_CNY)
    assert results[0]["status"] == "succeeded"
    assert results[0]["provider_billed_cny"] is None
    assert results[0]["conservative_charge_cny"] == float(OCR_TEXT_PRICE_CNY)
    # S2-J2-R1：外部供应商 request_id 不原文落账，统一不可逆哈希引用。
    assert results[0]["request_id"] == (
        "sha256:" + hashlib.sha256(b"req-ocr-1").hexdigest()[:32]
    )
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.5)


def test_table_call_uses_fixed_table_price(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway(OCRPageResult(text="表格", provider_request_id="req-table-1"))
    wrapper(ledger, inner).recognize(page(2), mode="table")
    reserved = [row for row in events(ledger) if row.get("event") == "reserved"]
    results = [row for row in events(ledger) if row.get("event") == "result"]
    assert reserved[0]["reserve_cny"] == float(OCR_TABLE_PRICE_CNY)
    assert results[0]["conservative_charge_cny"] == float(OCR_TABLE_PRICE_CNY)
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.15)


def test_rate_limited_is_not_retried_and_stops_route(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway(OCRRateLimited("限流", provider_request_id="req-429"))
    gateway = wrapper(ledger, inner)
    with pytest.raises(OCRRateLimited):
        gateway.recognize(page(1), mode="text")
    assert inner.calls == [(1, "text")]  # 只一次 attempt
    results = [row for row in events(ledger) if row.get("event") == "result"]
    assert results[0]["status"] == "failed"
    assert results[0]["error_code"] == "OCR_RATE_LIMITED"
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.5)
    reserved_before = len([row for row in events(ledger) if row.get("event") == "reserved"])
    with pytest.raises(OCRBudgetRefused):
        gateway.recognize(page(2), mode="text")
    assert len([row for row in events(ledger) if row.get("event") == "reserved"]) == reserved_before
    assert inner.calls == [(1, "text")]


def test_second_tile_for_same_page_refused_before_reserve(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner)
    gateway.recognize(page(7), mode="text")
    reserved_before = len([row for row in events(ledger) if row.get("event") == "reserved"])
    with pytest.raises(OCRBudgetRefused):
        gateway.recognize(page(7), mode="table")
    assert len([row for row in events(ledger) if row.get("event") == "reserved"]) == reserved_before
    assert inner.calls == [(7, "text")]


def test_fourteenth_call_refused_before_reserve(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner)
    for index in range(1, 14):
        gateway.recognize(page(index), mode="text")
    assert len(inner.calls) == 13
    assert len([row for row in events(ledger) if row.get("event") == "reserved"]) == 13
    with pytest.raises(OCRBudgetRefused):
        gateway.recognize(page(14), mode="text")
    assert len(inner.calls) == 13  # 第 14 次未发送
    assert len([row for row in events(ledger) if row.get("event") == "reserved"]) == 13


def test_timeout_keeps_full_and_hashes_unsafe_request_id(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway(OCRTimeout("超时", provider_request_id="Authorization: Bearer " + SECRET))
    with pytest.raises(OCRTimeout):
        wrapper(ledger, inner).recognize(page(3), mode="text")
    results = [row for row in events(ledger) if row.get("event") == "result"]
    assert results[0]["status"] == "timeout"
    assert results[0]["error_code"] == "OCR_TIMEOUT"
    assert results[0]["request_id"].startswith("sha256:")
    assert SECRET.encode("utf-8") not in ledger.ledger_path.read_bytes()
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.5)


def test_ledger_denial_before_send_has_no_http(tmp_path):
    ledger = make_ledger(tmp_path, stage_limit=0.4)  # 阶段额度 < 0.5，首笔预留即拒绝
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner)
    with pytest.raises(OCRBudgetRefused):
        gateway.recognize(page(1), mode="text")
    assert inner.calls == []
    assert not [row for row in events(ledger) if row.get("event") == "reserved"]
    with pytest.raises(OCRBudgetRefused):  # 已停机，后续直接拒绝
        gateway.recognize(page(2), mode="text")


def test_pre_send_recheck_refusal_keeps_reserve_and_has_no_http(tmp_path):
    def guard(_amount, _facts):
        raise BudgetLedgerInvalid("stale authorization")

    ledger = make_ledger(tmp_path, post_guard=guard)
    inner = FakeOCRGateway()
    with pytest.raises(OCRBudgetRefused):
        wrapper(ledger, inner).recognize(page(1), mode="text")
    assert inner.calls == []
    results = [row for row in events(ledger) if row.get("event") == "result"]
    assert results[0]["error_code"] == "OCR_BUDGET_SEND_REFUSED"
    assert ledger.summary().accounted_cny == pytest.approx(0.03 + 0.5)


def test_keyboard_interrupt_keeps_unsettled_full_reserve(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway(KeyboardInterrupt())
    gateway = wrapper(ledger, inner)
    with pytest.raises(KeyboardInterrupt):
        gateway.recognize(page(4), mode="text")
    assert inner.calls == [(4, "text")]
    assert not [row for row in events(ledger) if row.get("event") == "result"]
    reopened = BudgetLedger(ledger.ledger_path, ledger.budget_json_path, stage=STAGE, stage_limit_cny=9.66, max_requests=400)
    assert reopened.summary().accounted_cny == pytest.approx(0.03 + 0.5)


def test_invalid_input_refused_before_reserve(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner)
    with pytest.raises(OCRBudgetRefused):
        gateway.recognize({"content": b"x"}, mode="text")  # type: ignore[arg-type]
    with pytest.raises(OCRBudgetRefused):
        gateway.recognize(page(1), mode="audio")  # type: ignore[arg-type]
    assert inner.calls == []
    assert not [row for row in events(ledger) if row.get("event") == "reserved"]


def test_constructor_refuses_weaker_limits(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    with pytest.raises(ValueError):
        wrapper(ledger, inner, max_calls=14)
    with pytest.raises(ValueError):
        wrapper(ledger, inner, attempts=2)
    with pytest.raises(ValueError):
        wrapper(ledger, inner, text_price_cny="0.49")
    with pytest.raises(ValueError):
        wrapper(ledger, inner, table_price_cny="0.14")
