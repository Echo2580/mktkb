"""P2-T208-OFFLINE：judge 预算网关与授权反例（不发起任何真实调用）。

本文件只使用自建合成 run/judge/授权，覆盖：
- 授权缺失、类型错误、过期、未生效、跨 run、旧计划、非离线模式、production_ready；
- judge 身份/版本/执行模式不匹配；
- 单调用上界、合成账本隔离、重复结算、预留后失效、失败后隐式重试拒绝；
- 单 case 最坏调用数声明（Faithfulness 2 + FactualCorrectness(f1) 4 = 6）。

``test_p2_ragas_adapter.py`` 负责“真实安装的 Ragas 框架链路”；本文件不 mock
被验指标，只验证网关和失败边界。真正的裁判调用在本轮为 0 次。
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.evaluation import ragas_adapter as ra  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

NOW = datetime(2026, 11, 14, 0, 0, 0, tzinfo=timezone.utc)
PLAN_SHA = "a" * 64


# --------------------------------------------------------------------------- #
# 合成夹具（无题面、无真实答案、无 H2）
# --------------------------------------------------------------------------- #


def _case(
    case_id: str = "S01",
    *,
    answer: str = "A [[SUPPORTED]]",
    contexts: tuple[str, ...] = ("C [[SUPPORTED]]",),
    reference: str = "R [[SUPPORTED]]",
    refusal: bool = False,
    hard_failure: str | None = None,
) -> ra.RagasCase:
    return ra.RagasCase(
        case_id=case_id,
        question=f"Q {case_id}",
        answer=answer,
        contexts=tuple(contexts),
        reference=reference,
        refusal=refusal,
        hard_failure=hard_failure,
    )


def _run(
    *cases: ra.RagasCase,
    run_id: str = "run-synthetic-001",
    plan_id: str = "plan-synthetic-001",
    plan_sha256: str = PLAN_SHA,
    source: str = "synthetic",
) -> ra.RagasRun:
    return ra.RagasRun(
        run_id=run_id,
        plan_id=plan_id,
        plan_sha256=plan_sha256,
        source=source,
        cases=tuple(cases) or (_case(),),
    )


def _auth(run: ra.RagasRun, **overrides) -> ra.RagasAuthorization:
    values = {
        "authorization_id": "auth-synthetic-001",
        "run_id": run.run_id,
        "plan_id": run.plan_id,
        "plan_sha256": run.plan_sha256,
        "judge_id": "synthetic-rule-judge",
        "judge_version": "1.0",
        "issued_utc": NOW - timedelta(minutes=5),
        "expires_utc": NOW + timedelta(hours=1),
        "max_calls_per_case": ra.RAGAS_WORST_CASE_JUDGE_CALLS,
        "max_calls_total": 24,
        "max_cny_per_call": 0.01,
        "max_cny_total": 1.0,
    }
    values.update(overrides)
    return ra.RagasAuthorization(**values)


class _NeverCalledJudge:
    judge_id = "synthetic-rule-judge"
    judge_version = "1.0"
    execution_mode = "synthetic"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, prompt, response_model):  # noqa: ANN001
        self.calls += 1
        raise AssertionError("预算/授权反例不应到达 judge 传输")


class _Clock:
    def __init__(self, instants: list[datetime]) -> None:
        self._instants = list(instants)
        self._last = self._instants[-1]

    def __call__(self) -> datetime:
        if self._instants:
            self._last = self._instants.pop(0)
        return self._last


def _gateway(tmp_path: Path, *, run=None, auth=None, judge=None, clock=None):
    run = run or _run()
    auth = auth or _auth(run)
    judge = judge or _NeverCalledJudge()
    ledger = ra.open_synthetic_ledger(tmp_path / "ledger", run=run, authorization=auth)
    gateway = ra.JudgeBudgetGateway(
        run=run,
        authorization=auth,
        ledger=ledger,
        transport=judge,
        clock=clock or (lambda: NOW),
    )
    return gateway, ledger, judge


def _events(ledger_path: Path) -> list[dict]:
    return [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rewrite_events(ledger_path: Path, events: list[dict]) -> None:
    ledger_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def _append_raw(ledger_path: Path, event: dict) -> None:
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _score(run, judge, auth):
    return asyncio.run(
        ra.score_ragas(run, judge=judge, authorization=auth, clock=lambda: NOW)
    )


# --------------------------------------------------------------------------- #
# 授权/身份反例
# --------------------------------------------------------------------------- #


def test_missing_authorization_is_blocked_without_judge_call():
    judge = _NeverCalledJudge()
    result = _score(_run(), judge, None)
    assert result.status == "blocked"
    assert result.complete is False
    assert result.reason_code == "authorization_missing"
    assert judge.calls == 0
    assert result.counts["judge_calls"] == 0


def test_forged_authorization_dto_is_blocked_not_raised():
    forged = object.__new__(ra.RagasAuthorization)
    result = _score(_run(), _NeverCalledJudge(), forged)
    assert result.status == "blocked"
    assert result.reason_code in ra.RAGAS_REASON_CODES
    assert result.authorization["authorization_id"] is None
    assert result.judge["judge_id"] == "synthetic-rule-judge"


def test_forged_run_dto_is_blocked_not_raised():
    forged = object.__new__(ra.RagasRun)
    result = _score(forged, _NeverCalledJudge(), None)
    assert result.status == "blocked"
    assert result.reason_code in ra.RAGAS_REASON_CODES
    assert result.run_id is None
    assert result.run_digest is None
    assert result.counts["blocked"] == 0


def test_authorization_wrong_type_is_blocked():
    result = _score(
        _run(), _NeverCalledJudge(), {"run_id": "run-synthetic-001"}
    )
    assert result.status == "blocked"
    assert result.reason_code == "authorization_invalid_type"


def test_authorization_expired_is_blocked():
    run = _run()
    auth = _auth(run, issued_utc=NOW - timedelta(hours=2), expires_utc=NOW - timedelta(hours=1))
    result = _score(run, _NeverCalledJudge(), auth)
    assert result.status == "blocked"
    assert result.reason_code == "authorization_expired"
    assert result.counts["judge_calls"] == 0


def test_authorization_not_yet_valid_is_blocked():
    run = _run()
    auth = _auth(run, issued_utc=NOW + timedelta(minutes=5), expires_utc=NOW + timedelta(hours=1))
    result = _score(run, _NeverCalledJudge(), auth)
    assert result.status == "blocked"
    assert result.reason_code == "authorization_not_yet_valid"


def test_authorization_cross_run_is_blocked():
    run = _run()
    auth = _auth(run, run_id="run-other-999")
    result = _score(run, _NeverCalledJudge(), auth)
    assert result.status == "blocked"
    assert result.reason_code == "authorization_run_mismatch"


def test_authorization_old_plan_is_blocked():
    run = _run()
    auth = _auth(run, plan_sha256="b" * 64)
    result = _score(run, _NeverCalledJudge(), auth)
    assert result.status == "blocked"
    assert result.reason_code == "authorization_plan_mismatch"


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"mode": "live"}, "authorization_mode_forbidden"),
        ({"production_ready": True}, "authorization_production_ready_forbidden"),
    ],
)
def test_authorization_must_be_offline_and_not_production_ready(overrides, reason):
    run = _run()
    # 构造期严格拒绝非法授权；这里用 object.__new__ 绕过构造，验证 score_ragas 的二次检查。
    auth = object.__new__(ra.RagasAuthorization)
    for field, value in _auth(run).__dict__.items():
        object.__setattr__(auth, field, value)
    for field, value in overrides.items():
        object.__setattr__(auth, field, value)
    result = _score(run, _NeverCalledJudge(), auth)
    assert result.status == "blocked"
    assert result.reason_code == reason


def test_judge_must_be_synthetic():
    class _LiveJudge(_NeverCalledJudge):
        execution_mode = "live"

    result = _score(_run(), _LiveJudge(), _auth(_run()))
    assert result.status == "blocked"
    assert result.reason_code == "judge_not_synthetic"


def test_judge_identity_version_mismatch_is_blocked():
    class _OtherJudge(_NeverCalledJudge):
        judge_version = "2.0"

    run = _run()
    result = _score(run, _OtherJudge(), _auth(run))
    assert result.status == "blocked"
    assert result.reason_code == "judge_identity_mismatch"


def test_per_call_budget_over_authorization_is_blocked_before_call():
    run = _run()
    auth = _auth(run, max_cny_per_call=0.0001)
    judge = _NeverCalledJudge()
    result = _score(run, judge, auth)
    assert result.status == "blocked"
    assert result.reason_code == "per_call_budget_exceeded"
    assert judge.calls == 0


def test_authorization_rejects_non_finite_numbers():
    run = _run()
    for field, value in (
        ("max_cny_total", float("nan")),
        ("max_cny_total", float("inf")),
        ("max_cny_per_call", -0.1),
        ("max_calls_total", True),
        ("max_calls_per_case", 0),
    ):
        with pytest.raises(ra.RagasAdapterError) as caught:
            _auth(run, **{field: value})
        assert caught.value.code == "authorization_value_invalid"


def test_run_source_holdout_is_rejected():
    with pytest.raises(ra.RagasAdapterError) as caught:
        _run(source="holdout")
    assert caught.value.code == "run_source_not_allowed"


# --------------------------------------------------------------------------- #
# 合成账本 / 预算网关
# --------------------------------------------------------------------------- #


def test_synthetic_ledger_is_separate_and_bounded(tmp_path):
    run = _run()
    auth = _auth(run, max_cny_total=0.5, max_calls_total=12)
    ledger = ra.open_synthetic_ledger(tmp_path / "ledger", run=run, authorization=auth)
    assert ledger.ledger_path.parent == tmp_path / "ledger"
    assert "docs" not in str(ledger.ledger_path).replace("\\", "/").split("/")
    assert ledger.total_limit_cny == pytest.approx(0.5)
    assert ledger.stage == ra.RAGAS_LEDGER_STAGE
    budget = json.loads(ledger.budget_json_path.read_text(encoding="utf-8"))
    assert budget["limit_cny"] == pytest.approx(0.5)
    assert budget["stages"][ra.RAGAS_LEDGER_STAGE] == pytest.approx(0.5)


def test_synthetic_ledger_rejects_existing_or_real_shaped_paths(tmp_path):
    run = _run()
    auth = _auth(run)

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ra.RagasAdapterError) as caught:
        ra.open_synthetic_ledger(existing, run=run, authorization=auth)
    assert caught.value.code == "synthetic_ledger_invalid"

    simulated = tmp_path / "docs" / "evidence" / "LOCAL-R1-20261101" / "budget"
    with pytest.raises(ra.RagasAdapterError) as caught:
        ra.open_synthetic_ledger(simulated, run=run, authorization=auth)
    assert caught.value.code == "synthetic_ledger_invalid"
    assert not simulated.exists()

    outside = Path.cwd() / "var" / "t208-ledger-probe-not-created"
    with pytest.raises(ra.RagasAdapterError) as caught:
        ra.open_synthetic_ledger(outside, run=run, authorization=auth)
    assert caught.value.code == "synthetic_ledger_invalid"
    assert not outside.exists()


def test_confirm_uses_real_post_reserve_guard(tmp_path):
    gateway, ledger, _judge = _gateway(tmp_path)
    assert getattr(ledger, "_ragas_post_reserve_guard", None) is not None
    gateway.enter_case("S01")
    ticket = gateway.begin_call("a" * 64)
    gateway.confirm_call(ticket)
    gateway.settle_success(ticket)


def test_confirm_rejects_settled_reservation_after_reserve(tmp_path):
    gateway, ledger, judge = _gateway(tmp_path)
    gateway.enter_case("S01")
    ticket = gateway.begin_call("b" * 64)
    _append_raw(
        ledger.ledger_path,
        {
            "event": "result",
            "reservation_id": ticket.reservation_id,
            "stage": ra.RAGAS_LEDGER_STAGE,
            "kind": "chat",
            "provider": "synthetic",
            "model": gateway.authorization.judge_id,
            "status": "succeeded",
            "conservative_charge_cny": ticket.amount_cny,
            "estimated_list_price_cny": ticket.amount_cny,
        },
    )
    with pytest.raises(ra.RagasBudgetError) as caught:
        gateway.confirm_call(ticket)
    assert caught.value.code == "ledger_refused"
    assert judge.calls == 0
    assert gateway.stopped_reason == "ledger_refused"


def test_confirm_rejects_deleted_reservation_after_reserve(tmp_path):
    gateway, ledger, judge = _gateway(tmp_path)
    gateway.enter_case("S01")
    ticket = gateway.begin_call("c" * 64)
    events = [
        event
        for event in _events(ledger.ledger_path)
        if not (
            event.get("event") == "reserved"
            and event.get("reservation_id") == ticket.reservation_id
        )
    ]
    _rewrite_events(ledger.ledger_path, events)
    with pytest.raises(ra.RagasBudgetError) as caught:
        gateway.confirm_call(ticket)
    assert caught.value.code == "ledger_refused"
    assert judge.calls == 0


def test_confirm_rejects_tampered_reservation_amount_after_reserve(tmp_path):
    gateway, ledger, judge = _gateway(tmp_path)
    gateway.enter_case("S01")
    ticket = gateway.begin_call("d" * 64)
    events = _events(ledger.ledger_path)
    for event in events:
        if (
            event.get("event") == "reserved"
            and event.get("reservation_id") == ticket.reservation_id
        ):
            event["reserve_cny"] = float(ticket.amount_cny) + 0.001
    _rewrite_events(ledger.ledger_path, events)
    with pytest.raises(ra.RagasBudgetError) as caught:
        gateway.confirm_call(ticket)
    assert caught.value.code == "ledger_refused"
    assert judge.calls == 0


def test_declared_worst_case_call_count_is_six():
    assert ra.RAGAS_WORST_CASE_JUDGE_CALLS == 6
    assert ra.RAGAS_FAITHFULNESS_CALLS == 2
    assert ra.RAGAS_FACTUAL_CORRECTNESS_CALLS == 4


def test_duplicate_settlement_is_rejected(tmp_path):
    gateway, ledger, _judge = _gateway(tmp_path)
    gateway.enter_case("S01")
    ticket = gateway.begin_call("d" * 64)
    gateway.confirm_call(ticket)
    gateway.settle_success(ticket)
    with pytest.raises(ra.RagasBudgetError) as caught:
        gateway.settle_success(ticket)
    assert caught.value.code == "duplicate_settlement"
    results = [event for event in _events(ledger.ledger_path) if event["event"] == "result"]
    assert len(results) == 1
    assert gateway.charged_cny == pytest.approx(ra.RAGAS_DEFAULT_SYNTHETIC_CALL_COST_CNY)


def test_reservation_expiry_between_reserve_and_confirm_refuses_send(tmp_path):
    run = _run()
    auth = _auth(run, expires_utc=NOW + timedelta(minutes=1))
    clock = _Clock([NOW, NOW + timedelta(minutes=2)])
    gateway, ledger, judge = _gateway(tmp_path, run=run, auth=auth, clock=clock)
    gateway.enter_case("S01")
    ticket = gateway.begin_call("e" * 64)
    with pytest.raises(ra.RagasBudgetError) as caught:
        gateway.confirm_call(ticket)
    assert caught.value.code == "authorization_expired"
    assert judge.calls == 0
    results = [event for event in _events(ledger.ledger_path) if event["event"] == "result"]
    assert len(results) == 1
    assert results[0]["status"] == "failed"
    assert "P2_RAGAS_PRE_SEND_REFUSED" in results[0]["error_code"]
    assert gateway.stopped_reason == "authorization_expired"


def test_failure_stops_gateway_and_implicit_retry_is_refused(tmp_path):
    gateway, _ledger, _judge = _gateway(tmp_path)
    gateway.enter_case("S01")
    ticket = gateway.begin_call("f" * 64)
    gateway.confirm_call(ticket)
    gateway.settle_failure(ticket, "judge_service_error")
    assert gateway.stopped_reason == "judge_service_error"
    with pytest.raises(ra.RagasBudgetError) as caught:
        gateway.begin_call("0" * 64)
    assert caught.value.code == "gateway_stopped"


def test_case_call_ceiling_is_declared_and_enforced(tmp_path):
    run = _run()
    auth = _auth(run, max_calls_per_case=2, max_calls_total=12)
    gateway, _ledger, _judge = _gateway(tmp_path, run=run, auth=auth)
    gateway.enter_case("S01")
    gateway.begin_call("1" * 64)
    gateway.begin_call("2" * 64)
    with pytest.raises(ra.RagasBudgetError) as caught:
        gateway.begin_call("3" * 64)
    assert caught.value.code == "case_call_ceiling_exceeded"
    assert gateway.stopped_reason == "case_call_ceiling_exceeded"


def test_missing_ragas_dependency_is_blocked_not_faked(monkeypatch):
    run = _run()
    auth = _auth(run)
    judge = _NeverCalledJudge()

    def _missing():
        raise ImportError("synthetic missing ragas")

    monkeypatch.setattr(ra, "_load_ragas", _missing)
    result = _score(run, judge, auth)
    assert result.status == "blocked"
    assert result.reason_code == "ragas_not_installed"
    assert result.ragas_version is None
    assert judge.calls == 0
