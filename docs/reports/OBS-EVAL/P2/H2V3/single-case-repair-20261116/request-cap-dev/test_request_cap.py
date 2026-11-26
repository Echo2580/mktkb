from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend/tests/evaluation"))
from test_p2_authorization import (  # noqa: E402
    _plan, _write_ledger, _write_go, _prefix_sha, _snapshot, _open_gate,
    _events, _chat_evidence, _append_reserved, FakeTransport, p2_env,
)
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation.p2_contracts import P2RunPlan, P2ContractError  # noqa: E402


def test_explicit_unlimited_passes_history_and_serialization(p2_env):
    _write_ledger(p2_env.ledger, seeded=1601)
    p2_env.plan = _plan(max_requests="unlimited")
    _write_go(p2_env.go, ledger_prefix=_prefix_sha(p2_env.ledger), plan=p2_env.plan,
              ledger_path=p2_env.ledger, scope={"max_requests": "unlimited"})
    assert P2RunPlan.from_dict(json.loads(json.dumps(p2_env.plan.as_dict()))).max_requests == "unlimited"
    preflight = p2a.preflight_p2(p2_env.plan, _snapshot())
    assert preflight.ok and preflight.requests_used == 1601
    assert preflight.as_dict()["requests_remaining"] == "unlimited"
    gate = _open_gate(p2_env)
    ticket = gate.begin("answer-B0-Q01-t1")
    gate.confirm_before_send(ticket)
    transport = FakeTransport()
    transport.send(ticket)
    gate.settle_success(ticket, evidence=_chat_evidence(ticket))
    assert len(transport) == 1
    assert sum(e["event"] == "reserved" for e in _events(p2_env.ledger)) == 1602


@pytest.mark.parametrize("value", [True, False, -1, 0, None, "", "infinite", "UNLIMITED", "1500", float("nan")])
def test_invalid_plan_cap_fails_closed(value):
    with pytest.raises(P2ContractError):
        _plan(max_requests=value)


def test_old_finite_go_does_not_authorize_unlimited_plan(p2_env):
    p2_env.plan = _plan(max_requests="unlimited")
    _write_go(p2_env.go, ledger_prefix=_prefix_sha(p2_env.ledger), plan=p2_env.plan,
              ledger_path=p2_env.ledger, scope={"max_requests": 1000})
    with pytest.raises(p2a.P2AuthorizationError) as error:
        _open_gate(p2_env)
    assert error.value.reason == "go_max_requests_below_plan"


def test_unlimited_go_keeps_finite_plan_cap(p2_env):
    _write_go(p2_env.go, ledger_prefix=_prefix_sha(p2_env.ledger), plan=p2_env.plan,
              ledger_path=p2_env.ledger, scope={"max_requests": "unlimited"})
    gate = _open_gate(p2_env)
    assert gate._authorization.max_requests == 1000


def test_finite_plan_still_rejects_exhausted_history(p2_env):
    _write_ledger(p2_env.ledger, seeded=1000)
    result = p2a.preflight_p2(p2_env.plan, _snapshot())
    assert not result.ok and "request_budget_insufficient" in result.reasons


@pytest.mark.parametrize("cap", [True, -1, None, "", "unlimited ", float("nan")])
def test_invalid_go_cap_refused(p2_env, cap):
    p2_env.plan = _plan(max_requests="unlimited")
    _write_go(p2_env.go, ledger_prefix=_prefix_sha(p2_env.ledger), plan=p2_env.plan,
              ledger_path=p2_env.ledger, scope={"max_requests": cap})
    with pytest.raises(p2a.P2AuthorizationError):
        _open_gate(p2_env)


def unlimited_gate(env):
    env.plan = _plan(max_requests="unlimited")
    _write_go(env.go, ledger_prefix=_prefix_sha(env.ledger), plan=env.plan,
              ledger_path=env.ledger, scope={"max_requests": "unlimited"})
    return _open_gate(env)


def test_unlimited_gate_never_exceeds_item_attempts_even_after_reopen(p2_env):
    gate = unlimited_gate(p2_env)
    ticket = gate.begin("answer-B0-Q01-t1")
    gate.confirm_before_send(ticket)
    gate.settle_success(ticket, evidence=_chat_evidence(ticket))
    reopened = _open_gate(p2_env)
    before = len(_events(p2_env.ledger))
    with pytest.raises(p2a.P2GateError):
        reopened.begin("answer-B0-Q01-t1")
    assert len(_events(p2_env.ledger)) == before


def test_same_run_id_with_new_plan_hash_has_its_own_item_quota(p2_env):
    gate = unlimited_gate(p2_env)
    ticket = gate.begin("answer-B0-Q01-t1")
    gate.confirm_before_send(ticket)
    gate.settle_success(ticket, evidence=_chat_evidence(ticket))
    p2_env.plan = _plan(max_requests="unlimited", plan_version="v0.2")
    _write_go(p2_env.go, ledger_prefix=_prefix_sha(p2_env.ledger), plan=p2_env.plan,
              ledger_path=p2_env.ledger, scope={"max_requests": "unlimited"})
    next_gate = _open_gate(p2_env)
    ticket = next_gate.begin("answer-B0-Q01-t1")
    assert ticket.plan_sha256 == p2_env.plan.plan_sha256


@pytest.mark.parametrize("case", ["project", "stage", "center"])
def test_unlimited_keeps_money_limits_before_reservation(p2_env, case):
    gate = unlimited_gate(p2_env)
    if case == "project":
        _append_reserved(p2_env.ledger, rid="external", stage="S2-DEV", reserve=39.96)
    elif case == "stage":
        for center, amount in (("answer_retrieval", 12), ("ocr", 3), ("judge", 3), ("independent", 1.99)):
            _append_reserved(p2_env.ledger, rid="external-" + center, stage="P2-LIVE", reserve=amount, cost_center=center)
    else:
        _append_reserved(p2_env.ledger, rid="external", stage="P2-LIVE", reserve=2.6, cost_center="ocr")
    before = len(_events(p2_env.ledger))
    with pytest.raises(p2a.P2GateError):
        gate.begin("ocr-D07-p1" if case == "center" else "answer-B0-Q01-t1")
    assert len(_events(p2_env.ledger)) == before


def test_unlimited_go_single_request_cap_still_checked(p2_env):
    p2_env.plan = _plan(max_requests="unlimited")
    _write_go(p2_env.go, ledger_prefix=_prefix_sha(p2_env.ledger), plan=p2_env.plan,
              ledger_path=p2_env.ledger, scope={"max_requests": "unlimited", "max_request_cny": 0.49})
    with pytest.raises(p2a.P2AuthorizationError) as error:
        _open_gate(p2_env)
    assert error.value.reason == "go_max_request_cny_below_plan"


def test_unlimited_with_actual_center_allocations_still_refuses_overspend(p2_env):
    centers = {"answer_retrieval": 8.5, "ocr": 6.5, "judge": 3.0, "independent": 2.0}
    p2_env.plan = _plan(max_requests="unlimited", cost_centers_cny=centers)
    _write_go(p2_env.go, ledger_prefix=_prefix_sha(p2_env.ledger), plan=p2_env.plan,
              ledger_path=p2_env.ledger,
              scope={"max_requests": "unlimited", "cost_centers_cny": centers})
    gate = _open_gate(p2_env)
    _append_reserved(p2_env.ledger, rid="external-center", stage="P2-LIVE", reserve=8.49,
                     cost_center="answer_retrieval")
    before = len(_events(p2_env.ledger))
    with pytest.raises(p2a.P2GateError) as error:
        gate.begin("answer-B0-Q01-t1")
    assert error.value.reason == "center_budget_exceeded"
    assert len(_events(p2_env.ledger)) == before


def test_v3_cli_plan_and_config_share_explicit_cap():
    sys.path.insert(0, str(ROOT / "tools"))
    import p2_h2_v3_controlled_execute as entry
    from mktkb.evaluation.p2_holdout_plan import build_holdout_plan

    args = entry._build_parser().parse_args([
        "plan-private", "--root", "synthetic", "--key-file", "synthetic",
        "--out-dir", "synthetic", "--max-requests", "unlimited",
    ])
    config = entry._v3_config(business_date="2026-11-16", anchor_business_date="2026-11-15",
                              inputs={}, code_version="a" * 64, thresholds_approved=False)
    plan = build_holdout_plan(cases=[("SYN01", 1)], ingest_batches=1, plan_id="SYNTHETIC",
                              plan_version="v0.1", created_utc="2026-11-16T00:00:00+00:00",
                              max_requests=args.max_requests)
    assert args.max_requests == config["max_requests"] == plan.as_dict()["max_requests"] == "unlimited"
    assert P2RunPlan.from_dict(json.loads(json.dumps(plan.as_dict()))).plan_sha256 == plan.plan_sha256
    with pytest.raises(SystemExit):
        entry._build_parser().parse_args([
            "plan-private", "--root", "synthetic", "--key-file", "synthetic",
            "--out-dir", "synthetic", "--max-requests", "1500",
        ])
