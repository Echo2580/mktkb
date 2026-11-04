"""共享预算账本：历史占用、原子预留、失败保守计账、阶段上限、并发锁与脱敏。"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from mktkb.rag.budget import BudgetLedger, redact, redact_mapping
from mktkb.rag.errors import BudgetExceeded, BudgetLedgerInvalid


def _write_budget(tmp_path: Path) -> tuple[Path, Path]:
    budget = tmp_path / "budget.json"
    budget.write_text(
        json.dumps({"limit_cny": 10.0, "stages": {"S1-DEV": 3.0}}, ensure_ascii=False),
        encoding="utf-8",
    )
    ledger = tmp_path / "live-ledger.jsonl"
    ledger.write_text(
        json.dumps(
            {"event": "historical_import", "accounted_cny": 0.03, "note": "history once"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return ledger, budget


def test_summary_and_reserve_settle_separate_accounting(tmp_path: Path) -> None:
    ledger_path, budget_path = _write_budget(tmp_path)
    ledger = BudgetLedger(ledger_path, budget_path, stage="S1-DEV", stage_limit_cny=3.0, max_requests=1000)
    summary = ledger.summary()
    assert summary.historical_conservative_cny == pytest.approx(0.03)
    assert summary.accounted_cny == pytest.approx(0.03)
    assert summary.remaining_cny == pytest.approx(9.97)
    assert summary.stage_remaining_cny == pytest.approx(3.0)

    reservation = ledger.reserve(
        kind="embedding",
        provider="bailian",
        model="text-embedding-v4",
        max_cny=0.5,
        request_sha256="a" * 64,
    )
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.53)
    assert summary.stage_accounted_cny == pytest.approx(0.5)
    assert summary.remaining_cny == pytest.approx(9.47)

    ledger.settle(
        reservation,
        status="succeeded",
        usage={"total_tokens": 100},
        estimated_list_price_cny=0.00005,
        http_status=200,
        request_id="req-1",
        dimensions=(1024,),
    )
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.53)
    assert summary.success_estimated_list_price_cny == pytest.approx(0.00005)
    assert summary.provider_billed_cny is None
    assert summary.result_count == 1


def test_failed_request_keeps_conservative_charge_and_stage_cap(tmp_path: Path) -> None:
    ledger_path, budget_path = _write_budget(tmp_path)
    ledger = BudgetLedger(ledger_path, budget_path, stage="S1-DEV", stage_limit_cny=3.0, max_requests=1000)
    first = ledger.reserve(
        kind="rerank", provider="bailian", model="gte-rerank-v2", max_cny=0.5, request_sha256="b" * 64
    )
    ledger.settle(first, status="failed", error_code="RERANK_UNAVAILABLE")
    summary = ledger.summary()
    assert summary.accounted_cny == pytest.approx(0.53)
    assert summary.stage_accounted_cny == pytest.approx(0.5)

    with pytest.raises(BudgetExceeded):
        ledger.reserve(
            kind="rerank",
            provider="bailian",
            model="gte-rerank-v2",
            max_cny=2.51,
            request_sha256="c" * 64,
        )

    second = ledger.reserve(
        kind="embedding", provider="bailian", model="text-embedding-v4", max_cny=2.5, request_sha256="d" * 64
    )
    ledger.settle(second, status="succeeded", estimated_list_price_cny=0.001)
    with pytest.raises(BudgetExceeded):
        ledger.reserve(
            kind="embedding", provider="bailian", model="text-embedding-v4", max_cny=0.01, request_sha256="e" * 64
        )


def test_invalid_ledger_fails_closed(tmp_path: Path) -> None:
    ledger_path, budget_path = _write_budget(tmp_path)
    ledger_path.write_text("not-json\n", encoding="utf-8")
    ledger = BudgetLedger(ledger_path, budget_path, stage="S1-DEV", stage_limit_cny=3.0, max_requests=1000)
    with pytest.raises(BudgetLedgerInvalid):
        ledger.summary()


def test_secret_redaction() -> None:
    text = "Authorization: Bearer sk-abcdef1234567890 api_key=secret-value"
    cleaned = redact(text)
    assert "sk-abcdef" not in cleaned
    assert "secret-value" not in cleaned
    assert "***" in cleaned
    assert redact_mapping({"Authorization": "Bearer x", "api_key": "sk-1", "safe": "ok"}) == {
        "Authorization": "***",
        "api_key": "***",
        "safe": "ok",
    }


def _reserve_worker(ledger_path: str, budget_path: str, amount: float, results) -> None:
    try:
        ledger = BudgetLedger(ledger_path, budget_path, stage="S1-DEV", stage_limit_cny=3.0, max_requests=1000)
        reservation = ledger.reserve(
            kind="embedding",
            provider="bailian",
            model="text-embedding-v4",
            max_cny=amount,
            request_sha256="f" * 64,
        )
        results.put(("ok", reservation.reserve_cny))
    except BudgetExceeded:
        results.put(("exceeded", 0.0))
    except Exception as exc:  # 记录意外，避免静默
        results.put(("error", type(exc).__name__))


def test_cross_process_reservations_do_not_overspend(tmp_path: Path) -> None:
    ledger_path, budget_path = _write_budget(tmp_path)
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    processes = [
        context.Process(target=_reserve_worker, args=(str(ledger_path), str(budget_path), 0.9, results))
        for _ in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    outcomes = [results.get(timeout=5) for _ in processes]
    ok = sum(1 for status, _value in outcomes if status == "ok")
    exceeded = sum(1 for status, _value in outcomes if status == "exceeded")
    assert ok == 3
    assert exceeded == 1
    summary = BudgetLedger(ledger_path, budget_path, stage="S1-DEV", stage_limit_cny=3.0, max_requests=1000).summary()
    assert summary.stage_accounted_cny == pytest.approx(2.7)
    assert summary.accounted_cny == pytest.approx(2.73)

