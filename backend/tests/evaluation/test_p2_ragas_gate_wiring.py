"""E3: real Ragas + real P2Gate, temporary synthetic funding, no network."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import sys
import typing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance.support.netguard import t09_network_guard
import test_p2_authorization as fixtures
from mktkb.evaluation import p2_authorization as p2a, ragas_adapter as ra
from mktkb.evaluation.p2_contracts import P2RunPlan

pytestmark = pytest.mark.usefixtures('t09_network_guard')
NOW = fixtures.NOW
SEQUENCE = ('StatementGeneratorOutput', 'NLIStatementOutput', 'ClaimDecompositionOutput',
            'NLIStatementOutput', 'ClaimDecompositionOutput', 'NLIStatementOutput')
SENTINEL = 'E3_PRIVATE_SYNTHETIC_SENTINEL_82ca'


def test_wiring_module_exists():
    assert importlib.util.find_spec('mktkb.evaluation.ragas_p2_gate') is not None, 'P2Gate wiring is missing'


@pytest.fixture
def env(tmp_path, monkeypatch):
    wiring = importlib.import_module('mktkb.evaluation.ragas_p2_gate')
    ledger, budget, go = (tmp_path / name for name in ('ledger.jsonl', 'budget.json', 'go.json'))
    fixtures._write_ledger(ledger)
    fixtures._write_budget(budget)
    plan = fixtures._plan(items=[fixtures._item(f'judge-S01-{i}', 'judge', 'S01') for i in range(6)])
    fixtures._write_go(go, ledger_prefix=fixtures._prefix_sha(ledger), plan=plan, ledger_path=ledger)
    for name, path in (('P2_LEDGER_PATH', ledger), ('P2_BUDGET_PATH', budget), ('P2_GO_PATH', go)):
        monkeypatch.setattr(p2a, name, path)
    monkeypatch.setenv(fixtures.live_authorization.TOTAL_LIMIT_ENV, str(fixtures.TOTAL_LIMIT_CNY))
    gate = fixtures._open_gate(SimpleNamespace(plan=plan, ledger=ledger, budget=budget, go=go))
    run = ra.RagasRun(run_id=gate.run_id, plan_id=plan.plan_id, plan_sha256=plan.plan_sha256,
                      source='synthetic', cases=(ra.RagasCase('S01', SENTINEL, SENTINEL, (SENTINEL,), SENTINEL),))
    auth = ra.RagasAuthorization(authorization_id='e3-synthetic', run_id=run.run_id,
        plan_id=run.plan_id, plan_sha256=run.plan_sha256, judge_id='fixture-judge', judge_version='fixture-v1',
        issued_utc=NOW, expires_utc=gate.authorization.expires_utc, max_calls_per_case=6,
        max_calls_total=6, max_cny_per_call=0.01, max_cny_total=1)
    return SimpleNamespace(w=wiring, ledger=ledger, budget=budget, go=go, gate=gate,
                           plan=plan, run=run, auth=auth,
                           bindings={'S01': tuple(i.item_id for i in plan.items)})


class Judge:
    execution_mode = 'synthetic'
    judge_id = 'fixture-judge'
    judge_version = 'fixture-v1'
    model = 'deepseek-flash'

    def __init__(self, *, fail_at=None, evidence_mode='valid'):
        self.calls = []
        self.fail_at = fail_at
        self.evidence_mode = evidence_mode

    async def complete(self, prompt, response_model, *, ticket):
        self.calls.append(ticket)
        if self.fail_at == len(self.calls):
            raise RuntimeError(SENTINEL)
        name = response_model.__name__
        if name == 'StatementGeneratorOutput':
            content = response_model(statements=['synthetic claim'])
        elif name == 'ClaimDecompositionOutput':
            content = response_model(claims=['synthetic claim'])
        elif name == 'NLIStatementOutput':
            cls = typing.get_args(response_model.model_fields['statements'].annotation)[0]
            content = response_model(statements=[cls(statement='synthetic claim', reason='fixture', verdict=1)])
        else:
            raise AssertionError('unexpected schema')
        evidence = fixtures._chat_evidence(ticket)
        if self.evidence_mode == 'missing':
            evidence = None
        elif self.evidence_mode == 'invalid':
            evidence = replace(evidence, usage={})
        elif self.evidence_mode == 'cross_request':
            evidence = replace(evidence, request_sha256='e' * 64)
        return SimpleNamespace(content=content, evidence=evidence)


def score(env, judge=None, **overrides):
    values = dict(plan=env.plan, gate=env.gate, judge=judge or Judge(), authorization=env.auth,
                  item_ids_by_case=env.bindings, enabled=True, clock=lambda: NOW)
    values.update(overrides)
    return asyncio.run(env.w.score_ragas_with_p2_gate(env.run, **values))


def real_ragas():
    pytest.importorskip('ragas')


def events(env, kind):
    return [e for e in fixtures._events(env.ledger) if e.get('event') == kind]


def test_real_six_nested_calls_each_reserve_confirm_send_settle(env, monkeypatch, t09_network_guard):
    real_ragas()
    order = []
    for name in ('begin', 'confirm_before_send', 'settle_success'):
        original = getattr(env.gate, name)
        def spy(*args, _name=name, _original=original, **kwargs):
            result = _original(*args, **kwargs)
            ticket = result if _name == 'begin' else args[0]
            order.append((_name, ticket.item_id))
            return result
        monkeypatch.setattr(env.gate, name, spy)
    judge = Judge()
    original = judge.complete
    async def send(*args, ticket, **kwargs):
        order.append(('send', ticket.item_id))
        return await original(*args, ticket=ticket, **kwargs)
    judge.complete = send
    result = score(env, judge)
    assert result['status'] == 'scored', result
    assert result['score']['ragas_version'] == '0.4.4'
    assert result['score']['cases'][0]['metric_call_sequence'] == list(SEQUENCE)
    assert len(judge.calls) == len(events(env, 'reserved')) == len(events(env, 'result')) == 6
    assert len({t.request_id for t in judge.calls}) == 6
    assert [name for name, _ in order] == ['begin', 'confirm_before_send', 'send', 'settle_success'] * 6
    assert all(e['metadata']['cost_center'] == 'judge' for e in events(env, 'reserved'))
    assert all(e.get('settlement', {}).get('version') == 'usage-conservative-v1' for e in events(env, 'result'))
    assert result['p2_cost']['charged_cny'] == pytest.approx(6 * 0.004)
    assert result['quality_decision'] is None and result['auxiliary_only'] is True
    assert result['production_ready'] is False
    assert t09_network_guard.snapshot()['external'] == []
    assert SENTINEL not in json.dumps(result)
    print(json.dumps({'real_framework': 'ragas-0.4.4', 'order': order, 'call_records': result['calls'],
                      'p2_cost': result['p2_cost'], 'external_attempts': 0,
                      'versioned_settlements': events(env, 'result')}, sort_keys=True))


@pytest.mark.parametrize('change,reason', [
    ({'enabled': False}, 'wiring_disabled'), ({'gate': None}, 'p2_gate_missing'),
    ({'authorization': None}, 'authorization_missing'),
])
def test_default_and_missing_authority_send_nothing(env, change, reason):
    judge = Judge()
    result = score(env, judge, **change)
    assert result['status'] == 'blocked' and result['reason_code'] == reason
    assert judge.calls == [] and events(env, 'reserved') == []


def test_enabled_defaults_false(env):
    result = asyncio.run(env.w.score_ragas_with_p2_gate(env.run, plan=env.plan, gate=env.gate,
        judge=Judge(), authorization=env.auth, item_ids_by_case=env.bindings))
    assert result['reason_code'] == 'wiring_disabled'


@pytest.mark.parametrize('kind', ['run', 'plan', 'model', 'version', 'source', 'item_count', 'duplicate_item', 'item_case', 'nonjudge', 'wrong_center'])
def test_binding_refusal_before_reserve(env, kind):
    judge = Judge()
    if kind == 'run':
        env.run = replace(env.run, run_id='other-run')
    elif kind == 'plan':
        env.run = replace(env.run, plan_sha256='f' * 64)
    elif kind == 'model':
        judge.model = 'other-model'
    elif kind == 'version':
        judge.judge_version = 'other-version'
    elif kind == 'source':
        object.__setattr__(env.run, 'source', 'holdout')
    elif kind == 'item_count':
        env.bindings['S01'] = env.bindings['S01'][:5]
    elif kind == 'duplicate_item':
        env.bindings['S01'] = (env.bindings['S01'][0],) * 6
    elif kind in ('item_case', 'nonjudge', 'wrong_center'):
        field, value = {'item_case': ('case_id', 'other-case'), 'nonjudge': ('operation', 'answer'), 'wrong_center': ('cost_center', 'answer_retrieval')}[kind]
        object.__setattr__(env.plan.items[0], field, value)
    result = score(env, judge)
    assert result['status'] == 'blocked'
    assert judge.calls == [] and events(env, 'reserved') == []


@pytest.mark.parametrize('when', ['before', 'after_reserve'])
def test_expired_go_never_sends(env, monkeypatch, when):
    real_ragas()
    def expire():
        go = json.loads(env.go.read_text(encoding='utf-8'))
        go['expires_utc'] = NOW.isoformat()
        env.go.write_text(json.dumps(go), encoding='utf-8')
    if when == 'before':
        expire()
    else:
        begin = env.gate.begin
        def reserve(*args, **kwargs):
            ticket = begin(*args, **kwargs)
            expire()
            return ticket
        monkeypatch.setattr(env.gate, 'begin', reserve)
    judge = Judge()
    result = score(env, judge)
    assert result['status'] == 'unknown' and result['reason_code'] == 'p2_gate_refused'
    assert judge.calls == []
    assert len(events(env, 'reserved')) == (when == 'after_reserve')
    assert len(events(env, 'result')) == (when == 'after_reserve')


@pytest.mark.parametrize('mode', ['exception', 'missing', 'invalid', 'cross_request'])
def test_failure_stops_without_retry_and_keeps_conservative_funding(env, mode):
    real_ragas()
    judge = Judge(fail_at=2 if mode == 'exception' else None, evidence_mode=mode)
    result = score(env, judge)
    expected = 2 if mode == 'exception' else 1
    assert result['status'] == 'unknown'
    assert len(judge.calls) == len(events(env, 'reserved')) == expected
    assert result['retry_count'] == 0
    assert env.gate.stopped_reason is not None
    assert SENTINEL not in json.dumps(result)
    assert events(env, 'result')[-1]['status'] in ('failed', 'unknown')
    assert result['p2_cost']['reserved_cny'] >= result['p2_cost']['charged_cny']


def test_repeated_settlement_is_refused_without_duplicate_event(env):
    real_ragas()
    judge = Judge()
    assert score(env, judge)['status'] == 'scored'
    with pytest.raises(p2a.P2GateError):
        env.gate.settle_success(judge.calls[0], evidence=fixtures._chat_evidence(judge.calls[0]))
    assert len(events(env, 'result')) == 6


@pytest.mark.parametrize('limit', ['requests', 'center', 'single_request'])
def test_actual_gate_budget_limits_block_before_send(env, limit):
    real_ragas()
    if limit == 'requests':
        object.__setattr__(env.gate.authorization, 'max_requests', 1)
    elif limit == 'center':
        env.gate.authorization.cost_center_limits_cny['judge'] = 0.001
    else:
        object.__setattr__(env.gate.authorization, 'max_request_cny', 0.001)
    judge = Judge()
    result = score(env, judge)
    assert result['status'] == 'unknown' and result['reason_code'] == 'p2_gate_refused'
    assert len(judge.calls) == (1 if limit == 'requests' else 0)


def test_missing_ragas_stable_blocked_no_p2_reservation(env, monkeypatch):
    def missing():
        raise ImportError('synthetic missing dependency')
    monkeypatch.setattr(ra, '_load_ragas', missing)
    result = score(env)
    assert result['status'] == 'blocked' and result['reason_code'] == 'ragas_not_installed'
    assert events(env, 'reserved') == []


def test_nested_seventh_call_is_refused_before_reserve(env, monkeypatch):
    real_ragas()
    captured = []
    original = env.w.P2RagasJudgeBridge
    def capture(**kwargs):
        bridge = original(**kwargs)
        captured.append(bridge)
        return bridge
    monkeypatch.setattr(env.w, 'P2RagasJudgeBridge', capture)
    assert score(env)['status'] == 'scored'
    bridge = captured[0]
    with pytest.raises(ra.RagasJudgeError):
        asyncio.run(bridge.complete('synthetic', object))
    assert len(events(env, 'reserved')) == 6
    assert bridge.stopped_reason == 'nested_call_ceiling_exceeded'


def test_hard_failure_kept_even_with_high_soft_scores(env):
    real_ragas()
    env.run = replace(env.run, cases=(replace(env.run.cases[0], hard_failure='safety_violation'),))
    result = score(env)
    assert result['score']['cases'][0]['faithfulness'] == 1.0
    assert result['score']['complete'] is False
    assert result['quality_decision'] is None


@pytest.mark.parametrize('target', ['plan', 'ledger', 'run'])
def test_actual_gate_internal_binding_must_match_authorized_objects(env, target):
    if target == 'plan':
        env.gate._plan = replace(env.plan, plan_id='different')
    elif target == 'ledger':
        env.gate._ledger.ledger_path = env.ledger.with_name('different-ledger.jsonl')
    else:
        env.gate._ledger.run_id = 'different-run'
    judge = Judge()
    result = score(env, judge)
    assert result['status'] == 'blocked'
    assert result['reason_code'] == 'p2_gate_binding_mismatch'
    assert judge.calls == [] and events(env, 'reserved') == []


def test_serialization_failure_preserves_calls_and_funding_after_send(env, monkeypatch):
    real_ragas()
    def broken(_):
        raise ValueError(SENTINEL)
    monkeypatch.setattr(ra.RagasScoreResult, 'to_dict', broken)
    judge = Judge()
    result = score(env, judge)
    assert result['status'] == 'unknown' and result['reason_code'] == 'wiring_internal_error'
    assert len(result['calls']) == len(judge.calls) == 6
    assert result['p2_cost']['charged_cny'] == pytest.approx(0.024)
    assert SENTINEL not in json.dumps(result)


def test_multiple_cases_explicitly_blocked_without_reservation(env):
    env.run = replace(env.run, cases=env.run.cases + (replace(env.run.cases[0], case_id='S02'),))
    judge = Judge()
    result = score(env, judge)
    assert result['reason_code'] == 'p2_single_case_required'
    assert judge.calls == [] and events(env, 'reserved') == []


def test_actual_missing_dependency_is_stable_blocked(env):
    if importlib.util.find_spec('ragas') is not None:
        pytest.skip('this check requires the existing production venv without ragas')
    result = score(env)
    assert result['status'] == 'blocked' and result['reason_code'] == 'ragas_not_installed'
    assert events(env, 'reserved') == []


def test_outer_ragas_cap_stops_existing_p2_gate(env):
    real_ragas()
    judge = Judge()
    result = score(env, judge, authorization=replace(env.auth, max_calls_total=2))
    assert result['status'] == 'unknown'
    assert len(judge.calls) == 2 and len(events(env, 'reserved')) == 2
    assert env.gate.stopped_reason is not None
