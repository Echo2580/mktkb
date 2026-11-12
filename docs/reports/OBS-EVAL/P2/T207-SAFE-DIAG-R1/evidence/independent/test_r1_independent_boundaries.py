"""Fresh R1 mixed-state probes; synthetic/public fixtures only."""
import copy
import dataclasses
import json
from pathlib import Path

import pytest

from test_independent_safe_diag import (
    _value_case, _product_turn, _scoring_row, _synthetic_dataset, _ledger,
    _codes_plan, VALUE_TOKEN, runner, t09_network_guard,
)
from mktkb.evaluation.p2_diagnostics import HoldoutDiagnostics, validate_scorecard
from mktkb.evaluation.p2_scoring import score_public_case

pytestmark = pytest.mark.usefixtures('t09_network_guard')


def mixed():
    strata = ('paraphrase', 'negative', 'multi_turn', 'stale_conflict', 'cross_doc_security')
    cases = tuple(dataclasses.replace(_value_case(), case_id='R1-INDEPENDENT-' + str(i),
        question='INDEPENDENT_SYNTHETIC_QUESTION_' + str(i), stratum=name)
        for i, name in enumerate(strata))
    ledger = _ledger()
    ledger.scoring_cases = []
    for i, case in enumerate(cases[:3]):
        product = _product_turn(case.question, kind='INDEPENDENT_UNKNOWN_KIND' if i == 1 else 'answer', text=VALUE_TOKEN)
        row = _scoring_row(case, product.as_dict(include_text=True))
        if i == 2:
            row.update(status='error', error_code='MODEL_TIMEOUT')
        ledger.scoring_cases.append(row)
    case = cases[4]
    ledger.scoring_cases.append(_scoring_row(case,
        _product_turn(case.question, text='INDEPENDENT_WRONG_VALUE').as_dict(include_text=True)))
    dataset = _synthetic_dataset(cases)
    card = runner._holdout_scorecard(ledger, dataset, ingest_plan=_codes_plan(),
        execution='dry_run', real_calls=0, binding={}, gate_config=None)
    return ledger, dataset, card


def write(ledger, dataset, payload, monkeypatch):
    monkeypatch.setattr(runner, '_holdout_scorecard', lambda *a, **kw: copy.deepcopy(payload))
    return runner._holdout_scorecard_artifact(ledger, dataset, ingest_plan=_codes_plan(),
        execution='dry_run', real_calls=0, binding={}, gate_config=None)


def closed(out):
    assert (out['executed'], out['passed'], out['errors']) == (0, 0, 5)
    assert out['blocks'][0]['code'] == 'holdout_scorecard_leak'
    assert 'holdout_hard_failure_unverified' in {b['code'] for b in out['blocks']}
    assert out['diagnostics']['classification_status'] == 'unverified'
    assert all(e == dict(checked=0, unknown=5, violations=0)
        for e in out['diagnostics']['hard_failure_evidence'].values())
    assert 'INDEPENDENT_' not in json.dumps(out)


def test_mixed_valid_card_preserves_all_denominators(monkeypatch):
    ledger, dataset, original = mixed()
    out = write(ledger, dataset, original, monkeypatch)
    assert out == original
    d = out['diagnostics']
    assert d['counts'] == dict(planned=5, scored=3, errors=1, not_executed=1, observed=2, unknown_kind=1)
    assert d['refusal_confusion'] == dict(tp=0, fp=0, tn=2, fn=0, errors=1, not_executed=1, unknown=1)
    assert (out['passed'], out['failed'], out['errors']) == (1, 2, 2)
    Path(__file__).with_name('mixed-valid.json').write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')


@pytest.mark.parametrize('mutation', ['unknown_tn', 'unknown_matrix', 'missing_scored_observation',
    'shift_diagnostic_stratum', 'move_pass_to_unknown_stratum', 'fake_fallback'])
def test_mixed_conserved_mutations_failclosed(mutation, monkeypatch):
    ledger, dataset, bad = mixed()
    d = bad['diagnostics']
    if mutation == 'unknown_tn':
        d['refusal_confusion'].update(tn=3, unknown=0)
    elif mutation == 'unknown_matrix':
        d['kind_matrix']['kind_answer']['kind_unknown'] = 0
        d['kind_matrix']['kind_answer']['kind_answer'] += 1
    elif mutation == 'missing_scored_observation':
        # Preserve planned/scored and refusal total, remove only the scored evidence.
        d['counts']['observed'] -= 1
        d['by_stratum']['paraphrase']['observed'] -= 1
        d['kind_matrix']['kind_answer']['kind_answer'] -= 1
        d['refusal_confusion']['tn'] -= 1
        d['refusal_confusion']['unknown'] += 1
    elif mutation == 'shift_diagnostic_stratum':
        d['by_stratum']['paraphrase'], d['by_stratum']['negative'] = (
            d['by_stratum']['negative'], d['by_stratum']['paraphrase'])
    elif mutation == 'move_pass_to_unknown_stratum':
        bad['by_stratum']['paraphrase'].update(passed=0, failed=1)
        bad['by_stratum']['negative'].update(passed=1, failed=0)
    else:
        fallback = runner._blocked_holdout_scorecard(ledger, dataset,
            code='holdout_case_unscorable', execution='dry_run', real_calls=0, binding={}, gate_config=None)
        bad['blocks'] = fallback['blocks']
    closed(write(ledger, dataset, bad, monkeypatch))


@pytest.mark.parametrize('missing', ['holdout_sample_missing', 'holdout_case_error',
    'holdout_below_threshold', 'holdout_threshold_unapproved', 'holdout_hard_failure_unverified'])
def test_mixed_required_block_removal_failsclosed(missing, monkeypatch):
    ledger, dataset, bad = mixed()
    assert missing in {b['code'] for b in bad['blocks']}
    bad['blocks'] = [b for b in bad['blocks'] if b['code'] != missing]
    closed(write(ledger, dataset, bad, monkeypatch))


def test_fallback_itself_cannot_drop_unverified(monkeypatch):
    ledger, dataset, _ = mixed()
    fallback = runner._blocked_holdout_scorecard(ledger, dataset,
        code='holdout_case_unscorable', execution='dry_run', real_calls=0, binding={}, gate_config=None)
    validate_scorecard(fallback, total=5, run_id=ledger.run_id)
    fallback['blocks'] = [b for b in fallback['blocks'] if b['code'] != 'holdout_hard_failure_unverified']
    with pytest.raises(ValueError):
        validate_scorecard(fallback, total=5, run_id=ledger.run_id)
    closed(write(ledger, dataset, fallback, monkeypatch))


@pytest.mark.parametrize('invalid', [None, 0, 1, 'false', []])
def test_nonboolean_should_refuse_cannot_generate_normal_evidence(invalid):
    case = dataclasses.replace(_value_case(), should_refuse=invalid)
    row = _scoring_row(case, _product_turn(case.question, text=VALUE_TOKEN).as_dict(include_text=True))
    scored = score_public_case(case, row, document_codes={'D01_物品位置表.xlsx': 'D01'})
    d = HoldoutDiagnostics()
    with pytest.raises(ValueError):
        d.record(case, row, scored)
    assert d.payload['counts']['planned'] == 0
