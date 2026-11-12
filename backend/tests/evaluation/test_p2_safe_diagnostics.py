"""SAFE-DIAG: independently constructed synthetic inputs; never sealed H2."""
import copy
import json
import sys
import dataclasses
import asyncio
from pathlib import Path

import pytest

from mktkb.evaluation import p2_runner as runner
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation.test_p2_holdout_scorecard import (
    _card_for_rows, _value_case, _scoring_row, _product_turn, VALUE_TOKEN, _synthetic_dataset,
    _synthetic_cases, _ledger, _codes_plan, _run_answering_holdout, _write_sealed,
    _make_plan, _dry_run_authorization, _ingest_plan, D01, D04, NOW,
    _answering_products, t09_network_guard,
)


def test_safe_diagnostics_is_present_and_unverified():
    case = _value_case()
    card = _card_for_rows(case, _scoring_row(case, _product_turn(case.question, text=VALUE_TOKEN).as_dict(include_text=True)))
    assert card['diagnostics']['counts']['observed'] == 1
    assert card['diagnostics']['classification_status'] == 'unverified'


@pytest.mark.parametrize('payload', [
    {'ASCII_QUESTION_FRAGMENT': 1}, {'document': 'PUBLIC_DOCUMENT_CONTENT'},
    {'reference_answer': {'value': 'synthetic'}}, {'unknown\n': 0},
    {'unknown': 'x' * 4096}, {'unknown': [0]},
])
def test_writer_rejects_unregistered_diagnostics(payload):
    case = _value_case()
    dataset = _synthetic_dataset((case,))
    with pytest.raises(runner.P2RunError):
        runner._assert_holdout_scorecard_payload({'diagnostics': payload}, dataset)


def good_card():
    case = _value_case()
    row = _scoring_row(case, _product_turn(case.question, text=VALUE_TOKEN).as_dict(include_text=True))
    return case, row, _card_for_rows(case, row)


def test_every_nested_layer_rejects_unknown_fields_and_bad_leaves():
    from mktkb.evaluation.p2_diagnostics import validate_diagnostics
    case, _, card = good_card()
    original = card['diagnostics']
    paths = []
    def collect(obj, path=()):
        if isinstance(obj, dict):
            paths.append(path)
            for key, value in obj.items():
                collect(value, path + (key,))
    collect(original)
    for path in paths:
        for key, value in [('ASCII_QUESTION_FRAGMENT', 0), ('reference_answer', 'DOCUMENT_CONTENT'),
                           ('unknown\n', 0), ('x' * 4096, 0), ('unregistered', [1])]:
            payload = copy.deepcopy(original)
            target = payload
            for part in path:
                target = target[part]
            target[key] = value
            with pytest.raises(ValueError):
                validate_diagnostics(payload)
            from mktkb.evaluation.p2_diagnostics import HoldoutDiagnostics
            builder = HoldoutDiagnostics()
            builder.payload = payload
            with pytest.raises(ValueError):
                builder.to_dict()
            bad_card = copy.deepcopy(card)
            bad_card['diagnostics'] = payload
            with pytest.raises(runner.P2RunError):
                runner._assert_holdout_scorecard_payload(bad_card, _synthetic_dataset((case,)), run_id=card['run_id'])
    for value in (True, -1, 1.0, 361, 'ASCII_DOCUMENT_CONTENT', 'unverified\n', [0], {'reference_answer': 0}):
        payload = copy.deepcopy(original)
        payload['counts']['observed'] = value
        with pytest.raises(ValueError):
            validate_diagnostics(payload)
    for path in [('schema_version',), ('classification_status',), ('classification_owner',)]:
        payload = copy.deepcopy(original)
        payload[path[0]] += '\n'
        with pytest.raises(ValueError):
            validate_diagnostics(payload)


def test_poisoned_payload_fails_closed_without_sanitizing(monkeypatch):
    case, _, card = good_card()
    for poison in ({'reference_answer': 'ASCII_SECRET'}, ['DOCUMENT_CONTENT'], 'ASCII_QUESTION_FRAGMENT\n'):
        bad = copy.deepcopy(card)
        bad['diagnostics']['kind_matrix']['kind_answer'] = poison
        monkeypatch.setattr(runner, '_holdout_scorecard', lambda *args, **kwargs: bad)
        output = runner._holdout_scorecard_artifact(_ledger(), _synthetic_dataset((case,)),
            ingest_plan=_codes_plan(), execution='dry_run', real_calls=0, binding={}, gate_config=None)
        assert output['errors'] == 1 and output['passed'] == 0
        assert output['blocks'][0]['code'] == 'holdout_scorecard_leak'
        assert 'ASCII_SECRET' not in json.dumps(output) and 'DOCUMENT_CONTENT' not in json.dumps(output)


def test_unmapped_ascii_source_code_is_counted_without_exporting_text():
    case = dataclasses.replace(_value_case(), expected_sources=({'doc_code': 'ASCII_DOCUMENT_FRAGMENT'},))
    output = _card_for_rows(case, _scoring_row(case, _product_turn(case.question).as_dict(include_text=True)))
    assert 'ASCII_DOCUMENT_FRAGMENT' not in json.dumps(output)
    block = next(x for x in output['blocks'] if x['code'] == 'holdout_document_code_unmapped')
    assert block['evidence']['missing_count'] == 1


def test_full_card_rejects_unknown_top_block_evidence_and_unbound_metadata(monkeypatch):
    case, _, original = good_card()
    bad_cards = []
    for target in ('top', 'block', 'evidence', 'stratum', 'hard_by_kind'):
        for key, value in [('ASCII_FRAGMENT', 1), ('reference_answer', 'DOCUMENT_TEXT'), ('unknown\n', [0])]:
            bad = copy.deepcopy(original)
            obj = {'top': bad, 'block': bad['blocks'][0], 'evidence': bad['blocks'][0]['evidence'],
                   'stratum': bad['by_stratum']['paraphrase'], 'hard_by_kind': bad['hard_failures_by_kind']}[target]
            obj[key] = value
            bad_cards.append(bad)
    for key in ('code', 'detail'):
        bad = copy.deepcopy(original)
        bad['blocks'][0][key] = 'ASCII_DOCUMENT_FRAGMENT\n'
        bad_cards.append(bad)
    for key in ('run_id', 'config_hash'):
        bad = copy.deepcopy(original)
        bad[key] = 'UNBOUND_ASCII_DOCUMENT_FRAGMENT'
        bad_cards.append(bad)
    bad = copy.deepcopy(original)
    bad['blocks'][0]['evidence']['total'] = True
    bad_cards.append(bad)
    for bad in bad_cards:
        monkeypatch.setattr(runner, '_holdout_scorecard', lambda *args, **kwargs: bad)
        out = runner._holdout_scorecard_artifact(_ledger(), _synthetic_dataset((case,)),
            ingest_plan=_codes_plan(), execution='dry_run', real_calls=0, binding={}, gate_config=None)
        assert out['passed'] == 0 and out['errors'] == 1
        assert out['blocks'][0]['code'] == 'holdout_scorecard_leak'
        assert 'ASCII_DOCUMENT_FRAGMENT' not in json.dumps(out)


def test_unknown_codes_and_kinds_never_become_dynamic_keys(monkeypatch):
    from mktkb.evaluation import p2_score_run
    case, row, _ = good_card()
    row['turns'][0]['product']['kind'] = 'ASCII_QUESTION_FRAGMENT'
    output = _card_for_rows(case, row)['diagnostics']
    assert output['counts']['observed'] == 0 and output['counts']['unknown_kind'] == 1
    assert output['kind_matrix']['kind_answer']['kind_unknown'] == 1
    def boom(*args, **kwargs):
        raise runner.P2RunError('ASCII_DOCUMENT_CONTENT\n')
    monkeypatch.setattr(p2_score_run, 'holdout_case_scores_from_rows', boom)
    output = _card_for_rows(case, row)
    assert output['diagnostics']['errors']['unknown'] == 1
    assert 'ASCII_DOCUMENT_CONTENT' not in json.dumps(output)
    monkeypatch.setattr(runner, '_holdout_scorecard', boom)
    output = runner._holdout_scorecard_artifact(_ledger(), _synthetic_dataset((case,)),
        ingest_plan=_codes_plan(), execution='dry_run', real_calls=0, binding={}, gate_config=None)
    assert output['errors'] == 1 and output['passed'] == 0
    assert output['blocks'][0]['code'] == 'holdout_case_unscorable'
    assert 'ASCII_DOCUMENT_CONTENT' not in json.dumps(output)


def test_unknown_checks_are_fixed_counts_and_do_not_copy_evidence():
    from mktkb.evaluation.p2_diagnostics import HoldoutDiagnostics
    from mktkb.evaluation.p2_scoring import score_public_case
    case, row, _ = good_card()
    item = score_public_case(case, row, document_codes={'D01_物品位置表.xlsx': 'D01'})
    item = dataclasses.replace(item, score=dataclasses.replace(item.score, checks=(
        {'check_id': 'ASCII_QUESTION_FRAGMENT', 'status': 'fail', 'evidence': {'reference_answer': 'DOCUMENT_TEXT'}},
        {'check_id': 'unknown\n', 'status': 'fail'},)))
    builder = HoldoutDiagnostics()
    builder.record(case, row, item)
    out = builder.to_dict()
    assert out['failed_checks']['unknown'] == 1
    assert 'ASCII_QUESTION_FRAGMENT' not in json.dumps(out) and 'DOCUMENT_TEXT' not in json.dumps(out)


def test_refusal_uses_should_refuse_and_excludes_structural_errors():
    from mktkb.evaluation.p2_diagnostics import HoldoutDiagnostics
    from mktkb.evaluation.p2_scoring import score_public_case
    builder = HoldoutDiagnostics()
    for should_refuse, kind in ((True, 'not_found'), (False, 'no_answer'),
                                (True, 'answer'), (False, 'answer')):
        case = dataclasses.replace(_value_case(), expected_kind='conflict', should_refuse=should_refuse)
        row = _scoring_row(case, _product_turn(case.question, kind=kind, text=VALUE_TOKEN).as_dict(include_text=True))
        scored = score_public_case(case, row, document_codes={'D01_物品位置表.xlsx': 'D01'})
        builder.record(case, row, scored)
    case, row, _ = good_card()
    scored = score_public_case(case, row, document_codes={'D01_物品位置表.xlsx': 'D01'})
    builder.record(case, row, scored, status='error')
    builder.record(case, None)
    unknown = dataclasses.replace(scored, outcome=dataclasses.replace(scored.outcome, kind='ASCII_FRAGMENT'))
    builder.record(case, row, unknown)
    out = builder.to_dict()
    assert out['refusal_confusion'] == dict(tp=1, fp=1, tn=1, fn=1, errors=1, not_executed=1, unknown=1)
    assert out['counts']['observed'] == 4 and out['counts']['unknown_kind'] == 1


def test_partial_30_and_middle_turn_error_have_exact_denominators():
    cases = tuple(dataclasses.replace(_value_case(), case_id=f'SAFE-SYNTH-{i}', stratum=s)
                  for i, s in enumerate(['paraphrase']*10 + ['multi_turn']*5 + ['negative']*5
                                      + ['stale_conflict']*5 + ['cross_doc_security']*5))
    rows = [_scoring_row(c, _product_turn(c.question, text=VALUE_TOKEN).as_dict(include_text=True))
            for c in cases[:22]]
    rows[-1]['status'] = 'error'
    rows[-1]['error_code'] = 'MODEL_OUTPUT_INVALID'
    rows[-1]['turns'][0]['product']['model_failure_reason'] = 'record_facts'
    ledger = _ledger()
    ledger.scoring_cases = rows
    card = runner._holdout_scorecard(ledger, _synthetic_dataset(cases), ingest_plan=_codes_plan(),
        execution='dry_run', real_calls=0, binding={}, gate_config=None)
    d = card['diagnostics']
    assert d['counts'] == dict(planned=30, scored=21, errors=1, not_executed=8, observed=21, unknown_kind=0)
    assert d['kind_matrix']['kind_answer']['kind_answer'] == 21
    assert d['errors']['MODEL_OUTPUT_INVALID'] == 1 and d['errors']['not_executed'] == 8
    assert d['model_failure_reasons']['record_facts'] == 1
    assert d['by_stratum']['stale_conflict']['not_executed'] == 3
    assert d['by_stratum']['cross_doc_security']['not_executed'] == 5
    case = dataclasses.replace(cases[0], turns=({'question': 'synthetic A'}, {'question': 'synthetic B'}, {'question': 'synthetic C'}))
    row = copy.deepcopy(rows[0])
    row['planned_turns'] = 3
    row['turns'] *= 3
    row['turns'][1] = dict(row['turns'][1], status='error', error_code='MODEL_TIMEOUT')
    d = _card_for_rows(case, row)['diagnostics']
    assert d['counts']['observed'] == 0 and d['counts']['errors'] == 1
    assert d['errors']['MODEL_TIMEOUT'] == 1


@pytest.mark.parametrize('message,reason', [
    ('content 不是 JSON 对象', 'json_parse'), ('answer 不合法', 'response_schema'),
    ('记录型回答不是可验证的字段事实陈述', 'record_facts'),
    ('回答字段原值未由被引用来源背书', 'record_source'),
    ('回答字段原值属于其它对象', 'record_entity'),
    ('ASCII_SECRET_DOCUMENT_CONTENT', 'unknown'), ('content 不是 JSON 对象\n', 'unknown'),
])
def test_model_reason_trace_and_existing_error_behavior(message, reason):
    from mktkb.providers.types import ModelOutputInvalid
    from mktkb.conversations.service import _model_failure_result
    from mktkb.observability.tracer import start_trace
    class Repo:
        def write_best_effort(self, trace, spans):
            self.trace, self.spans = trace, spans
    repo = Repo()
    exc = ModelOutputInvalid(message)
    with start_trace(http_request_id='synthetic', mode='local', scope='synthetic', repo=repo):
        result = _model_failure_result(exc, 7)
    assert result.kind == 'service_error' and result.error_code == 'MODEL_OUTPUT_INVALID'
    assert result.retryable is True and result.revision == 7
    span = next(s for s in repo.spans if s.name == 'model_failure')
    assert json.loads(span.attributes_json) == {'model_failure_reason': reason}
    assert message not in span.attributes_json


@pytest.mark.usefixtures('t09_network_guard')
def test_true_runner_normal_30_matrix(tmp_path, monkeypatch):
    card, _, _ = asyncio.run(_run_answering_holdout(tmp_path, monkeypatch))
    d = card['diagnostics']
    assert d['counts'] == dict(planned=30, scored=30, errors=0, not_executed=0, observed=30, unknown_kind=0)
    assert d['kind_matrix']['kind_answer']['kind_answer'] == 25
    assert d['kind_matrix']['kind_refusal']['kind_answer'] == 5
    assert d['failed_checks']['value_hit'] == 0
    assert d['failed_checks']['source_hit'] == 2
    assert d['source'] == dict(matched=23, unmatched=2, mapping_blocked=0)
    assert all(v == {'checked': 0, 'unknown': 30, 'violations': 0}
               for v in d['hard_failure_evidence'].values())
    assert 'holdout_hard_failure_unverified' in {x['code'] for x in card['blocks']}


@pytest.mark.usefixtures('t09_network_guard')
def test_true_runner_stops_after_21_scored_one_error_eight_unstarted(tmp_path, monkeypatch):
    from mktkb.evaluation.p2_dataset import HOLDOUT_ROOT_ENV, HOLDOUT_KEY_FILE_ENV, load_p2_dataset
    from mktkb.evaluation.product_adapter import P2RunDataset, ProductEvalAdapter, MockChatBackend
    async def run():
        sealed = _write_sealed(tmp_path)
        monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(sealed.root))
        monkeypatch.setenv(HOLDOUT_KEY_FILE_ENV, str(sealed.key_file))
        dataset = P2RunDataset.from_p2_dataset(load_p2_dataset(sealed.manifest_path, visibility='holdout'))
        plan = _make_plan(dataset.cases)
        adapter = ProductEvalAdapter(tmp_path / 'partial', chat=MockChatBackend(), dataset=dataset,
            ingest_plan=_ingest_plan(D01, D04), purge_traces_on_close=True)
        products = _answering_products(dataset)
        target = dataset.cases[21].question
        async def ask(question, **kwargs):
            if question == target:
                return dataclasses.replace(_product_turn(question), kind='service_error',
                    error_code='MODEL_OUTPUT_INVALID', model_failure_reason='record_facts')
            return products[question]
        adapter.ask_turn = ask
        try:
            result = await runner.run_p2(plan, adapter=adapter, authorization=_dry_run_authorization(plan), now=NOW)
        finally:
            await adapter.close()
        assert result.stop_code == 'product_service_error'
        card = json.loads((adapter.paths.run_dir / 'holdout_scorecard.json').read_text(encoding='utf-8'))
        d = card['diagnostics']
        assert d['counts'] == dict(planned=30, scored=21, errors=1, not_executed=8, observed=21, unknown_kind=0)
        assert d['errors']['MODEL_OUTPUT_INVALID'] == 1 and d['errors']['not_executed'] == 8
        assert d['model_failure_reasons']['record_facts'] == 1
        assert not (adapter.paths.run_dir / 'cases.jsonl').exists()
        assert not adapter.paths.trace_db.exists()
    asyncio.run(run())


@pytest.mark.usefixtures('t09_network_guard')
def test_real_adapter_json_failure_reason_reaches_runner_diagnostics(tmp_path):
    from mktkb.evaluation.product_adapter import ProductEvalAdapter, MockChatBackend, ChatBehavior
    case = dataclasses.replace(_value_case(), question='活动策划需要哪些步骤？')
    dataset = _synthetic_dataset((case,))
    plan = _make_plan(dataset.cases)
    async def run():
        adapter = ProductEvalAdapter(tmp_path / 'json-reason',
            chat=MockChatBackend(behaviors=(ChatBehavior(kind='invalid_json'),)),
            dataset=dataset, ingest_plan=_ingest_plan(D01, D04), purge_traces_on_close=True)
        try:
            result = await runner.run_p2(plan, adapter=adapter,
                authorization=_dry_run_authorization(plan), now=NOW)
        finally:
            await adapter.close()
        assert result.stop_code == 'product_service_error'
        card = json.loads((adapter.paths.run_dir / 'holdout_scorecard.json').read_text(encoding='utf-8'))
        assert card['diagnostics']['errors']['MODEL_OUTPUT_INVALID'] == 1
        assert card['diagnostics']['model_failure_reasons']['json_parse'] == 1
        assert card['diagnostics']['counts']['observed'] == 0
        assert adapter.provider_calls()['chat']['calls'] == 1
        assert not adapter.paths.trace_db.exists()
    asyncio.run(run())


def test_r1_scored_requires_complete_observation_at_both_boundaries(monkeypatch):
    from mktkb.evaluation.p2_diagnostics import HoldoutDiagnostics, validate_diagnostics
    case, _, bad = good_card()
    d = bad['diagnostics']
    d['counts']['observed'] = d['by_stratum']['paraphrase']['observed'] = 0
    d['kind_matrix']['kind_answer']['kind_answer'] = 0
    d['refusal_confusion']['tn'] = 0
    d['refusal_confusion']['unknown'] = 1
    with pytest.raises(ValueError):
        validate_diagnostics(d)
    builder = HoldoutDiagnostics()
    builder.payload = d
    with pytest.raises(ValueError):
        builder.to_dict()
    monkeypatch.setattr(runner, '_holdout_scorecard', lambda *a, **kw: bad)
    out = runner._holdout_scorecard_artifact(_ledger(), _synthetic_dataset((case,)),
        ingest_plan=_codes_plan(), execution='dry_run', real_calls=0, binding={}, gate_config=None)
    assert (out['passed'], out['executed'], out['errors']) == (0, 0, 1)
    assert out['blocks'][0]['code'] == 'holdout_scorecard_leak'


@pytest.mark.parametrize('broken', ['missing_outcome', 'invalid_should_refuse'])
def test_r1_generation_rejects_missing_refusal_or_outcome_evidence(broken):
    from mktkb.evaluation.p2_diagnostics import HoldoutDiagnostics
    from mktkb.evaluation.p2_scoring import score_public_case
    case, row, _ = good_card()
    scored = score_public_case(case, row, document_codes={'D01_物品位置表.xlsx': 'D01'})
    if broken == 'missing_outcome':
        scored = dataclasses.replace(scored, outcome=None)
    else:
        case = dataclasses.replace(case, should_refuse='unknown')
    with pytest.raises(ValueError):
        builder = HoldoutDiagnostics()
        builder.record(case, row, scored)
        builder.to_dict()


@pytest.mark.parametrize('missing', ['holdout_sample_missing', 'holdout_case_error',
    'holdout_below_threshold', 'holdout_threshold_unapproved', 'holdout_hard_failure_unverified'])
def test_r1_normal_card_cannot_delete_required_blocks(missing, monkeypatch):
    case, row, _ = good_card()
    if missing == 'holdout_case_error':
        row['status'] = 'error'
        row['error_code'] = 'MODEL_TIMEOUT'
    bad = _card_for_rows(case, row)
    assert missing in {block['code'] for block in bad['blocks']}
    bad['blocks'] = [block for block in bad['blocks'] if block['code'] != missing]
    monkeypatch.setattr(runner, '_holdout_scorecard', lambda *a, **kw: bad)
    out = runner._holdout_scorecard_artifact(_ledger(), _synthetic_dataset((case,)),
        ingest_plan=_codes_plan(), execution='dry_run', real_calls=0, binding={}, gate_config=None)
    assert (out['passed'], out['executed'], out['errors']) == (0, 0, 1)
    assert out['blocks'][0]['code'] == 'holdout_scorecard_leak'
    assert 'holdout_hard_failure_unverified' in {block['code'] for block in out['blocks']}


def test_r1_cannot_move_pass_to_unknown_stratum(monkeypatch):
    cases = (dataclasses.replace(_value_case(), case_id='R1-NORMAL'),
             dataclasses.replace(_value_case(), case_id='R1-UNKNOWN', stratum='negative'))
    ledger = _ledger()
    ledger.scoring_cases = [_scoring_row(case, _product_turn(case.question, text=VALUE_TOKEN,
        kind=kind).as_dict(include_text=True)) for case, kind in zip(cases, ('answer', 'UNREGISTERED'))]
    dataset = _synthetic_dataset(cases)
    bad = runner._holdout_scorecard(ledger, dataset, ingest_plan=_codes_plan(),
        execution='dry_run', real_calls=0, binding={}, gate_config=None)
    assert (bad['passed'], bad['failed'], bad['diagnostics']['counts']['observed']) == (1, 1, 1)
    bad['by_stratum']['paraphrase'].update(passed=0, failed=1)
    bad['by_stratum']['negative'].update(passed=1, failed=0)
    monkeypatch.setattr(runner, '_holdout_scorecard', lambda *a, **kw: bad)
    out = runner._holdout_scorecard_artifact(ledger, dataset, ingest_plan=_codes_plan(),
        execution='dry_run', real_calls=0, binding={}, gate_config=None)
    assert (out['passed'], out['executed'], out['errors']) == (0, 0, 2)
    assert out['blocks'][0]['code'] == 'holdout_scorecard_leak'


def test_r1_diagnostic_strata_cannot_disagree_with_scorecard(monkeypatch):
    case, _, bad = good_card()
    d = bad['diagnostics']
    d['by_stratum']['negative'], d['by_stratum']['paraphrase'] = (
        d['by_stratum']['paraphrase'], d['by_stratum']['negative'])
    monkeypatch.setattr(runner, '_holdout_scorecard', lambda *a, **kw: bad)
    out = runner._holdout_scorecard_artifact(_ledger(), _synthetic_dataset((case,)),
        ingest_plan=_codes_plan(), execution='dry_run', real_calls=0, binding={}, gate_config=None)
    assert out['blocks'][0]['code'] == 'holdout_scorecard_leak'
    assert (out['passed'], out['errors']) == (0, 1)


def test_r1_fallback_also_keeps_unverified_block():
    case, _, _ = good_card()
    out = runner._blocked_holdout_scorecard(_ledger(), _synthetic_dataset((case,)),
        code='holdout_case_unscorable', execution='dry_run', real_calls=0, binding={}, gate_config=None)
    assert (out['passed'], out['executed'], out['errors']) == (0, 0, 1)
    assert out['diagnostics']['classification_status'] == 'unverified'
    assert all(e == dict(checked=0, unknown=1, violations=0)
               for e in out['diagnostics']['hard_failure_evidence'].values())
    assert 'holdout_hard_failure_unverified' in {block['code'] for block in out['blocks']}
