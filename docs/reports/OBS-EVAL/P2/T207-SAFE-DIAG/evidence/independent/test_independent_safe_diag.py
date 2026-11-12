"""Reviewer-owned synthetic probes. No real sealed dataset is opened."""
import asyncio
import copy
import dataclasses
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / 'backend/tests'))
from evaluation.test_p2_holdout_scorecard import (
    _value_case, _product_turn, _scoring_row, _card_for_rows, _synthetic_dataset,
    _ledger, _codes_plan, _make_plan, _dry_run_authorization, _ingest_plan,
    D01, D04, NOW, VALUE_TOKEN, _write_sealed,
)
from acceptance.support.netguard import t09_network_guard
from mktkb.evaluation import p2_runner as runner
from mktkb.evaluation.p2_diagnostics import HoldoutDiagnostics
from mktkb.evaluation.p2_scoring import score_public_case

pytestmark = pytest.mark.usefixtures('t09_network_guard')


def sample(kind='answer'):
    case = dataclasses.replace(_value_case(), case_id='REVIEW-SYNTH-01',
        question='REVIEW_ASCII_QUESTION_FRAGMENT', reference_answer='REVIEW_ONLY_REFERENCE')
    row = _scoring_row(case, _product_turn(case.question, kind=kind,
        text=VALUE_TOKEN).as_dict(include_text=True))
    return case, row, _card_for_rows(case, row)


def artifact(case, payload, monkeypatch):
    monkeypatch.setattr(runner, '_holdout_scorecard', lambda *a, **kw: copy.deepcopy(payload))
    return runner._holdout_scorecard_artifact(_ledger(), _synthetic_dataset((case,)),
        ingest_plan=_codes_plan(), execution='dry_run', real_calls=0, binding={}, gate_config=None)


def paths(value, trail=()):
    if type(value) is dict:
        yield trail
        for key, child in value.items():
            yield from paths(child, trail + (key,))
    elif type(value) is list:
        for index, child in enumerate(value):
            yield from paths(child, trail + (index,))


def at(value, path):
    for key in path:
        value = value[key]
    return value


def test_review_every_dictionary_poison_fails_closed(monkeypatch):
    case, _, original = sample()
    poisons = [('REVIEW_ASCII_QUESTION_FRAGMENT', 1), ('reference_answer', {'secret': 'REVIEW_DOCUMENT_CONTENT'}),
        ('review_unknown\n', [0]), ('R' * 4096, 0)]
    for path in paths(original):
        for key, value in poisons:
            bad = copy.deepcopy(original)
            at(bad, path)[key] = value
            out = artifact(case, bad, monkeypatch)
            assert (out['passed'], out['errors']) == (0, 1), path
            assert out['blocks'][0]['code'] == 'holdout_scorecard_leak'
            raw = json.dumps(out)
            assert 'REVIEW_ASCII' not in raw and 'REVIEW_DOCUMENT' not in raw


@pytest.mark.parametrize('value', [True, 0, -1, 1.5, 999999999, 'REVIEW_DOCUMENT_CONTENT', [1],
    {'reference_answer': 'REVIEW_DOCUMENT_CONTENT'}, 'unverified\n'])
def test_review_bad_counts_fail_closed(value, monkeypatch):
    case, _, bad = sample()
    bad['diagnostics']['counts']['observed'] = value
    out = artifact(case, bad, monkeypatch)
    assert out['errors'] == 1 and out['passed'] == 0
    assert 'REVIEW_DOCUMENT_CONTENT' not in json.dumps(out)


def test_review_unregistered_generation_uses_unknown(monkeypatch):
    case, row, card = sample('REVIEW_ASCII_UNKNOWN_KIND\n')
    assert card['diagnostics']['counts']['observed'] == 0
    assert card['diagnostics']['refusal_confusion']['unknown'] == 1
    scored = score_public_case(case, row, document_codes={'D01_物品位置表.xlsx': 'D01'})
    scored = dataclasses.replace(scored, score=dataclasses.replace(scored.score, checks=(
        {'check_id': 'REVIEW_DOCUMENT_CONTENT', 'status': 'fail', 'evidence': {'reference_answer': 'REVIEW_LEAK'}},)))
    d = HoldoutDiagnostics(); d.record(case, row, scored)
    assert d.to_dict()['failed_checks']['unknown'] == 1
    d = HoldoutDiagnostics(); d.record(case, row, error='REVIEW_DOCUMENT_CONTENT\n')
    assert d.to_dict()['errors']['unknown'] == 1
    assert 'REVIEW_' not in json.dumps(d.to_dict())
    bad_case = dataclasses.replace(case, expected_sources=({'doc_code': 'REVIEW_DOCUMENT_CONTENT'},))
    output = _card_for_rows(bad_case, row)
    assert 'REVIEW_DOCUMENT_CONTENT' not in json.dumps(output)
    assert any(b['evidence'].get('missing_count') == 1 for b in output['blocks'])


@pytest.mark.parametrize('field', ['code', 'detail', 'evidence'])
def test_review_block_values_and_unbound_id_rejected(field, monkeypatch):
    case, _, original = sample()
    for poison in ('REVIEW_DOCUMENT_CONTENT', 'holdout_case_error\n', ['REVIEW_LEAK'], {'reference_answer': 'REVIEW_LEAK'}):
        bad = copy.deepcopy(original); bad['blocks'][0][field] = poison
        out = artifact(case, bad, monkeypatch)
        assert out['errors'] == 1 and 'REVIEW_' not in json.dumps(out)
    for key in ('run_id', 'config_hash'):
        bad = copy.deepcopy(original); bad[key] = 'REVIEW_UNBOUND_METADATA'
        out = artifact(case, bad, monkeypatch)
        assert out['errors'] == 1 and 'REVIEW_UNBOUND' not in json.dumps(out)


def test_review_unknown_cannot_be_reclassified_as_tn_at_writer(monkeypatch):
    case, _, bad = sample('REVIEW_UNREGISTERED_KIND')
    assert bad['diagnostics']['counts']['unknown_kind'] == 1
    assert bad['diagnostics']['counts']['observed'] == 0
    bad['diagnostics']['refusal_confusion']['unknown'] = 0
    bad['diagnostics']['refusal_confusion']['tn'] = 1
    out = artifact(case, bad, monkeypatch)
    Path(__file__).with_name('counterexample-unknown-to-tn.json').write_text(
        json.dumps({'input': bad, 'writer_output': out}, indent=2, ensure_ascii=False), encoding='utf-8')
    assert out['executed'] == 0 and out['errors'] == 1, 'writer accepted unknown actual kind as TN'


def test_review_unknown_cannot_be_pass_at_writer(monkeypatch):
    case, _, bad = sample('REVIEW_UNREGISTERED_KIND')
    assert bad['failed'] == 1 and bad['diagnostics']['counts']['observed'] == 0
    bad['passed'], bad['failed'] = 1, 0
    bad['by_stratum']['paraphrase']['passed'], bad['by_stratum']['paraphrase']['failed'] = 1, 0
    for block in bad['blocks']:
        if block['code'] == 'holdout_below_threshold':
            block['detail'] = 'H2 通过 1 < 门槛 24/30'; block['evidence']['passed'] = 1
    out = artifact(case, bad, monkeypatch)
    Path(__file__).with_name('counterexample-unknown-to-pass.json').write_text(
        json.dumps({'input': bad, 'writer_output': out}, indent=2, ensure_ascii=False), encoding='utf-8')
    assert out['passed'] == 0 and out['errors'] == 1, 'writer accepted unknown actual kind as pass'


def test_review_unverified_block_must_remain(monkeypatch):
    case, _, bad = sample()
    bad['blocks'] = [b for b in bad['blocks'] if b['code'] != 'holdout_hard_failure_unverified']
    out = artifact(case, bad, monkeypatch)
    assert out['errors'] == 1, 'writer accepted removal of mandatory unverified block'


def test_review_scalar_required_block_cannot_be_removed(monkeypatch):
    case, _, bad = sample()
    assert bad['thresholds_approved'] is False
    bad['blocks'] = [b for b in bad['blocks'] if b['code'] != 'holdout_threshold_unapproved']
    out = artifact(case, bad, monkeypatch)
    Path(__file__).with_name('counterexample-required-block.json').write_text(
        json.dumps({'input': bad, 'writer_output': out}, indent=2, ensure_ascii=False), encoding='utf-8')
    assert out['errors'] == 1, 'writer accepted removal of scalar-required unknown block'


def test_review_refusal_should_refuse_and_error_denominators():
    d = HoldoutDiagnostics()
    for refusal, kind in [(True, 'refusal'), (False, 'refusal'), (True, 'answer'), (False, 'answer')]:
        case, row, _ = sample(kind)
        case = dataclasses.replace(case, expected_kind='clarification', should_refuse=refusal)
        d.record(case, row, score_public_case(case, row, document_codes={'D01_物品位置表.xlsx': 'D01'}))
    case, row, _ = sample()
    scored = score_public_case(case, row, document_codes={'D01_物品位置表.xlsx': 'D01'})
    d.record(case, row, scored, status='error'); d.record(case, None)
    d.record(case, row, dataclasses.replace(scored, outcome=dataclasses.replace(scored.outcome, kind='REVIEW_UNKNOWN')))
    out = d.to_dict()
    assert out['counts'] == dict(planned=7, scored=5, errors=1, not_executed=1, observed=4, unknown_kind=1)
    assert out['refusal_confusion'] == dict(tp=1, fp=1, tn=1, fn=1, errors=1, not_executed=1, unknown=1)


def test_review_middle_turn_error_and_mapping_block():
    case, row, _ = sample()
    case = dataclasses.replace(case, turns=({'question': 'REVIEW_MIDDLE_FIRST'},
        {'question': 'REVIEW_MIDDLE_SECOND'}, {'question': 'REVIEW_MIDDLE_THIRD'}))
    row['planned_turns'] = 3
    row['turns'] = [copy.deepcopy(row['turns'][0]) for _ in range(3)]
    row['turns'][1]['status'] = 'error'; row['turns'][1]['error_code'] = 'MODEL_TIMEOUT'
    out = _card_for_rows(case, row)
    assert out['diagnostics']['counts']['observed'] == 0
    assert out['diagnostics']['refusal_confusion']['errors'] == 1
    assert out['diagnostics']['errors']['MODEL_TIMEOUT'] == 1
    case = dataclasses.replace(case, expected_sources=({'doc_code': 'REVIEW_UNMAPPED_DOCUMENT'},))
    out = _card_for_rows(case, row)
    assert out['diagnostics']['source']['mapping_blocked'] == 1
    assert out['diagnostics']['counts']['observed'] == 0


@pytest.mark.parametrize('reason', ['json_parse', 'record_facts', 'unknown'])
def test_review_real_trace_adapter_reason_chain(reason, tmp_path):
    from mktkb.evaluation.product_adapter import ProductEvalAdapter, MockChatBackend, ChatBehavior
    from mktkb.providers.types import ModelOutputInvalid
    message = 'REVIEW_ASCII_FREE_EXCEPTION_MESSAGE\n'
    case = dataclasses.replace(_value_case(), case_id='REVIEW-REASON-CASE',
        question='城东店的宣传海报在哪里？', reference_answer='REVIEW_SYNTHETIC_REFERENCE')
    dataset = _synthetic_dataset((case,)); plan = _make_plan(dataset.cases)
    async def run():
        async def raise_unknown(index, body):
            raise ModelOutputInvalid(message)
        chat = (MockChatBackend(before_call=raise_unknown) if reason == 'unknown' else
            MockChatBackend(behaviors=(ChatBehavior(kind='invalid_json'),)) if reason == 'json_parse' else
            MockChatBackend(behaviors=(ChatBehavior(answer='B区1号货架第二层'),)))
        adapter = ProductEvalAdapter(tmp_path / reason, chat=chat, dataset=dataset,
            ingest_plan=_ingest_plan(D01), purge_traces_on_close=True)
        ask = adapter.ask_turn; observations = []
        async def observe(question, **kw):
            product = await ask(question, **kw)
            observations.append(product)
            record = adapter.trace_of(product.trace_id)
            assert record is not None
            spans = record[1]
            attrs = [json.loads(s.attributes_json) for s in spans if s.name == 'model_failure']
            assert attrs == [{'model_failure_reason': reason}]
            assert 'model_failure_reason' not in product.as_dict(include_text=True)
            return product
        adapter.ask_turn = observe
        try:
            result = await runner.run_p2(plan, adapter=adapter,
                authorization=_dry_run_authorization(plan), now=NOW)
        finally:
            await adapter.close()
        assert result.stop_code == 'product_service_error'
        assert len(observations) == 1 and observations[0].model_failure_reason == reason
        assert observations[0].error_code == 'MODEL_OUTPUT_INVALID' and observations[0].retryable is True
        card = json.loads((adapter.paths.run_dir / 'holdout_scorecard.json').read_text(encoding='utf-8'))
        assert card['diagnostics']['model_failure_reasons'][reason] == 1
        assert card['diagnostics']['counts']['observed'] == 0
        assert chat.call_count == 1 and not adapter.paths.trace_db.exists()
        for file in adapter.paths.run_dir.iterdir():
            if file.is_file():
                assert 'REVIEW_ASCII_FREE_EXCEPTION_MESSAGE' not in file.read_text(encoding='utf-8')
        Path(__file__).with_name('reason-' + reason + '.json').write_text(json.dumps({
            'reason': reason, 'trace_span_verified': True, 'product_memory_verified': True,
            'aggregate_verified': True, 'chat_calls': chat.call_count, 'error_code': observations[0].error_code,
            'stop_code': result.stop_code, 'trace_purged': not adapter.paths.trace_db.exists(),
            'arbitrary_message_absent_from_run_artifacts': True}, indent=2), encoding='utf-8')
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['normal', 'partial'])
def test_review_true_runner_30(mode, tmp_path, monkeypatch):
    from mktkb.evaluation.p2_dataset import HOLDOUT_ROOT_ENV, HOLDOUT_KEY_FILE_ENV, load_p2_dataset
    from mktkb.evaluation.product_adapter import P2RunDataset, ProductEvalAdapter, MockChatBackend
    async def run():
        sealed = _write_sealed(tmp_path)
        monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(sealed.root)); monkeypatch.setenv(HOLDOUT_KEY_FILE_ENV, str(sealed.key_file))
        dataset = P2RunDataset.from_p2_dataset(load_p2_dataset(sealed.manifest_path, visibility='holdout'))
        plan = _make_plan(dataset.cases, plan_id='review-offline-30')
        adapter = ProductEvalAdapter(tmp_path / 'runner', chat=MockChatBackend(), dataset=dataset,
            ingest_plan=_ingest_plan(D01, D04), purge_traces_on_close=True)
        by_question = {q: (i, c) for i, c in enumerate(dataset.cases) for q in
            ((c.question,) if not c.turns else tuple(t.get('question', t.get('text')) for t in c.turns))}
        async def ask(question, **kw):
            index, case = by_question[question]
            if mode == 'partial' and index == 21:
                return dataclasses.replace(_product_turn(question), kind='service_error',
                    error_code='MODEL_OUTPUT_INVALID', model_failure_reason='record_facts')
            return _product_turn(question, kind='not_found' if case.should_refuse and mode == 'normal' else 'answer',
                text=VALUE_TOKEN if index < 10 or index == 20 or mode == 'normal' else '合成故意错误',
                source_id=None if case.should_refuse and mode == 'normal' else 'a'*8+'-'+'b'*4+'-'+'c'*4+'-'+'d'*4+'-'+'e'*12)
        adapter.ask_turn = ask
        try:
            result = await runner.run_p2(plan, adapter=adapter, authorization=_dry_run_authorization(plan), now=NOW)
        finally:
            await adapter.close()
        card = json.loads((adapter.paths.run_dir / 'holdout_scorecard.json').read_text(encoding='utf-8'))
        if mode == 'normal':
            assert (card['passed'], card['failed'], card['errors']) == (30, 0, 0)
            assert card['diagnostics']['counts']['observed'] == 30
            assert card['diagnostics']['refusal_confusion']['tp'] == 5
        else:
            assert result.stop_code == 'product_service_error'
            assert (card['passed'], card['failed'], card['errors']) == (11, 10, 9)
            assert card['diagnostics']['counts'] == dict(planned=30, scored=21, errors=1, not_executed=8, observed=21, unknown_kind=0)
        assert not (adapter.paths.run_dir / 'cases.jsonl').exists() and not adapter.paths.trace_db.exists()
        Path(__file__).with_name('runner-' + mode + '.json').write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding='utf-8')
    asyncio.run(run())
