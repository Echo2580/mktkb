"""S2-K-R1A 定向测试：受控 OCR 预算网关按 (可信来源锚, 真实页号) 计 tile。

覆盖 F-K2 最小修复的网关边界：
- 两个不同来源的同一真实页号都能各有 1 个 tile；同来源同页第二个 tile 仍在预留/发送前拒绝；
- 无来源旧调用走固定 legacy 兼容锚（不是随机 scope），仍受同页与全局 13 次上限；
- 非法来源格式在预留/发送前拒绝且不回显原始值；
- 新 request_sha256 绑定来源/mode/真实页号/图块字节（64hex），旧公式只保留给无来源兼容调用；
- stats 保留 tiles_by_page 聚合，并新增可核“哪份来源哪一页”的来源页明细。

只使用隔离账本（``tmp_path``）与本地替身；不发真实网络、不读 ``.env``、不写真实共享文件。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mktkb.providers.ocr_budgeted import (
    LEGACY_SOURCE_SCOPE,
    OCR_TABLE_PRICE_CNY,
    OCR_TEXT_PRICE_CNY,
    BudgetedOCRGateway,
    OCRBudgetRefused,
)
from mktkb.providers.types import (
    OCRInput,
    OCRPageResult,
    is_valid_ocr_source_scope,
    make_ocr_source_scope,
)
from mktkb.rag.budget import BudgetLedger

STAGE = "S2-K-R1A-OCR-TEST"


def make_ledger(tmp_path: Path, *, stage_limit: float = 9.66) -> BudgetLedger:
    ledger_path = tmp_path / "live-ledger.jsonl"
    budget_path = tmp_path / "budget.json"
    ledger_path.write_text(
        json.dumps(
            {
                "event": "historical_import",
                "accounted_cny": 0.03,
                "provider_billed_cny": None,
                "note": "S2-K-R1A isolated OCR test ledger (not the shared ledger)",
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
                "note": "S2-K-R1A isolated budget (not the shared budget)",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return BudgetLedger(ledger_path, budget_path, stage=STAGE, stage_limit_cny=stage_limit, max_requests=400)


class FakeOCRGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def recognize(self, page: OCRInput, *, mode: str) -> OCRPageResult:
        self.calls.append((int(page.page), str(mode)))
        return OCRPageResult(text="识别文本", provider_request_id=f"req-{len(self.calls)}")


def source(document: str, version: str) -> str:
    return make_ocr_source_scope(document, version)


def page(number: int = 1, *, content: bytes | None = None, scope: str | None = None, bbox=None) -> OCRInput:
    return OCRInput(
        content=content if content is not None else b"fake-png-bytes-" + bytes([number % 250]),
        mime_type="image/png",
        page=number,
        bbox=bbox,
        source_scope=scope,
    )


def wrapper(ledger: BudgetLedger, inner: FakeOCRGateway, **overrides) -> BudgetedOCRGateway:
    return BudgetedOCRGateway(inner, ledger=ledger, **overrides)


def events(ledger: BudgetLedger) -> list[dict]:
    return [
        json.loads(line)
        for line in ledger.ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def reserved_events(ledger: BudgetLedger) -> list[dict]:
    return [row for row in events(ledger) if row.get("event") == "reserved"]


def test_make_and_validate_source_scope():
    first = source("doc-a", "ver-1")
    assert first == source("doc-a", "ver-1")
    assert first != source("doc-a", "ver-2")
    assert first != source("doc-b", "ver-1")
    assert len(first) == 64 and first == first.lower()
    assert is_valid_ocr_source_scope(first)
    assert not is_valid_ocr_source_scope(first.upper())
    assert not is_valid_ocr_source_scope("x" * 64)
    assert not is_valid_ocr_source_scope(None)
    with pytest.raises(ValueError):
        make_ocr_source_scope(None, "ver")
    with pytest.raises(ValueError):
        make_ocr_source_scope("doc", None)


def test_two_sources_same_real_page_both_allowed(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner)
    scope_a = source("doc-a", "ver-1")
    scope_b = source("doc-b", "ver-1")

    gateway.recognize(page(1, scope=scope_a), mode="text")
    gateway.recognize(page(1, scope=scope_b), mode="text")

    assert inner.calls == [(1, "text"), (1, "text")]
    stats = gateway.stats()
    assert stats["calls"] == 2
    assert stats["tiles_by_page"] == {1: 2}
    assert stats["tiles_by_source_page"] == {scope_a: {1: 1}, scope_b: {1: 1}}
    assert stats["calls_by_source"] == {scope_a: 1, scope_b: 1}
    assert sorted(stats["source_scopes"]) == sorted([scope_a, scope_b])
    assert stats["legacy_source_scope_used"] is False
    assert len(reserved_events(ledger)) == 2


def test_same_source_same_page_second_tile_refused_before_reserve(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner)
    scope = source("doc-a", "ver-1")
    gateway.recognize(page(1, scope=scope, content=b"tile-one"), mode="text")
    reserved_before = len(reserved_events(ledger))

    with pytest.raises(OCRBudgetRefused):
        gateway.recognize(page(1, scope=scope, content=b"tile-two"), mode="table")

    assert inner.calls == [(1, "text")]
    assert len(reserved_events(ledger)) == reserved_before == 1
    assert gateway.stats()["tiles_by_source_page"] == {scope: {1: 1}}
    assert gateway.stats()["calls"] == 1


def test_different_real_pages_of_one_source_are_distinct(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner)
    scope = source("doc-pdf", "ver-1")
    gateway.recognize(page(1, scope=scope), mode="text")
    gateway.recognize(page(3, scope=scope), mode="text")
    assert inner.calls == [(1, "text"), (3, "text")]
    assert gateway.stats()["tiles_by_source_page"] == {scope: {1: 1, 3: 1}}
    assert gateway.stats()["tiles_by_page"] == {1: 1, 3: 1}


def test_legacy_no_source_keeps_global_page_limit_without_random_scope(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner)
    gateway.recognize(page(1, content=b"legacy-tile-one"), mode="text")
    with pytest.raises(OCRBudgetRefused) as caught:
        gateway.recognize(page(1, content=b"legacy-tile-two"), mode="table")
    assert "页面 tile 数达到受控上限" in str(caught.value)
    assert inner.calls == [(1, "text")]
    assert len(reserved_events(ledger)) == 1
    stats = gateway.stats()
    assert stats["legacy_source_scope_used"] is True
    assert stats["tiles_by_source_page"] == {LEGACY_SOURCE_SCOPE: {1: 1}}
    assert stats["tiles_by_page"] == {1: 1}


def test_malformed_source_refused_before_reserve_without_echo(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner)
    raw = "Authorization: Bearer sk-KR1A-SYNTHETIC-MUST-NOT-ECHO-0123456789"
    with pytest.raises(OCRBudgetRefused) as caught:
        gateway.recognize(page(1, scope=raw), mode="text")
    assert raw not in str(caught.value)
    assert raw.split(" ")[-1] not in str(caught.value)
    assert inner.calls == []
    assert reserved_events(ledger) == []
    assert gateway.stats()["source_scopes"] == []


def test_request_sha_binds_source_mode_page_and_tile_bytes(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner)
    scope_a = source("doc-a", "ver-1")
    scope_b = source("doc-b", "ver-1")
    tile = b"kr1a-tile-bytes"
    gateway.recognize(page(1, content=tile, scope=scope_a), mode="table")

    expected = hashlib.sha256(f"ocr-v2|{scope_a}|table|1|".encode("utf-8") + tile).hexdigest()
    reserved = reserved_events(ledger)
    assert reserved[0]["request_sha256"] == expected
    assert len(expected) == 64
    other = hashlib.sha256(f"ocr-v2|{scope_b}|table|1|".encode("utf-8") + tile).hexdigest()
    assert other != expected
    assert other not in [row["request_sha256"] for row in reserved]

    # 无来源兼容调用沿用历史公式（旧事件/旧 request_sha 不改不减）
    gateway.recognize(page(2, content=b"legacy-bytes"), mode="text")
    legacy_expected = hashlib.sha256("ocr-v1|text|2|".encode("utf-8") + b"legacy-bytes").hexdigest()
    assert reserved_events(ledger)[-1]["request_sha256"] == legacy_expected


def test_thirteenth_allowed_fourteenth_refused_new_source_does_not_reset(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner, max_calls=13)
    for index in range(1, 14):
        gateway.recognize(page(1, content=f"tile-{index}".encode(), scope=source(f"doc-{index}", "ver-1")), mode="text")
    assert len(inner.calls) == 13
    assert len(reserved_events(ledger)) == 13
    with pytest.raises(OCRBudgetRefused) as caught:
        gateway.recognize(page(1, content=b"tile-14", scope=source("doc-new", "ver-1")), mode="text")
    assert "OCR 调用数达到受控上限" in str(caught.value)
    assert len(inner.calls) == 13
    assert len(reserved_events(ledger)) == 13
    assert gateway.stats()["calls"] == 13


def test_legacy_and_source_calls_share_one_global_cap(tmp_path):
    ledger = make_ledger(tmp_path)
    inner = FakeOCRGateway()
    gateway = wrapper(ledger, inner, max_calls=2)
    gateway.recognize(page(1, scope=source("doc-a", "ver-1")), mode="text")
    gateway.recognize(page(1, content=b"legacy-tile"), mode="text")
    with pytest.raises(OCRBudgetRefused):
        gateway.recognize(page(2, scope=source("doc-b", "ver-1")), mode="text")
    assert len(inner.calls) == 2
    assert gateway.stats()["legacy_source_scope_used"] is True
