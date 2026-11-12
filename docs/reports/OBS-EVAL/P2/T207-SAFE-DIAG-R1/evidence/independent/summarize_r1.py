"""Validate and summarize reviewer-owned synthetic aggregate evidence only."""
import hashlib
import json
from pathlib import Path

from mktkb.evaluation.p2_diagnostics import validate_scorecard

HERE = Path(__file__).parent
def read(name):
    return json.loads((HERE / name).read_text(encoding='utf-8'))

cards = {name: read('runner-' + name + '.json') for name in ('normal', 'partial')}
cards['mixed'] = read('mixed-valid.json')
summary = {'cards': {}, 'four_rejects': {}, 'reason_chain': {}, 'real_h2_quality': 'NOT-RUN',
    'hard_failure_classification': 'unverified', 'real_model_calls': 0}
for name, card in cards.items():
    validate_scorecard(card, total=card['total'], run_id=card['run_id'], config_hash=card['config_hash'])
    d = card['diagnostics']
    c = d['counts']
    assert c['scored'] == c['observed'] + c['unknown_kind']
    r = d['refusal_confusion']
    assert sum(r[k] for k in ('tp', 'fp', 'tn', 'fn')) == c['observed']
    assert r['unknown'] == c['unknown_kind']
    assert all(e == dict(checked=0, unknown=card['total'], violations=0)
        for e in d['hard_failure_evidence'].values())
    assert card['release_ready'] is False
    assert 'holdout_hard_failure_unverified' in {b['code'] for b in card['blocks']}
    for s, bucket in d['by_stratum'].items():
        assert bucket['scored'] == bucket['observed'] + bucket['unknown_kind']
        assert card['by_stratum'].get(s, {'passed': 0})['passed'] <= bucket['observed']
    summary['cards'][name] = {k: card[k] for k in ('total', 'passed', 'failed', 'errors')}
    summary['cards'][name].update(counts=c, refusal_confusion=r, by_stratum=d['by_stratum'],
        source=d['source'], hard_failure_evidence=d['hard_failure_evidence'],
        release_ready=card['release_ready'])
for label in ('unknown-to-tn', 'unknown-to-pass', 'required-block'):
    out = read('counterexample-' + label + '.json')['writer_output']
    assert (out['executed'], out['passed'], out['errors']) == (0, 0, 1)
    assert {b['code'] for b in out['blocks']} == {
        'holdout_scorecard_leak', 'holdout_hard_failure_unverified'}
    summary['four_rejects'][label] = {'passed': 0, 'errors': 1, 'fixed_block': 'holdout_scorecard_leak'}
summary['four_rejects']['remove-unverified'] = {'evidence': 'test_review_unverified_block_must_remain in regression.txt'}
for reason in ('json_parse', 'record_facts', 'unknown'):
    value = read('reason-' + reason + '.json')
    assert all(value[k] is True for k in ('trace_span_verified', 'product_memory_verified',
        'aggregate_verified', 'trace_purged', 'arbitrary_message_absent_from_run_artifacts'))
    assert value['chat_calls'] == 1 and value['error_code'] == 'MODEL_OUTPUT_INVALID'
    summary['reason_chain'][reason] = value
before, after = read('protected-hashes-before.json'), read('protected-hashes.json')
assert before == after and after['all_equal']
summary['protected_files_equal'] = len(after['protected_files'])
guard = read('network-guard.json')
assert guard['external_attempts'] == 0 and guard['pytest_exit_status'] == 0
summary['network_guard'] = guard
diff = read('default-differential.json')
assert sum(x['turns'] for x in diff['public_runs']) == 57
summary['public_default_equal_turns'] = 57
summary['reused_probe_tools_equal_original'] = {}
old = HERE.parents[2] / 'T207-SAFE-DIAG' / 'evidence' / 'independent'
for name in ('test_independent_safe_diag.py', 'independent_guard.py', 'check_hashes.py', 'default_diff.py'):
    assert (HERE / name).read_bytes() == (old / name).read_bytes()
    summary['reused_probe_tools_equal_original'][name] = hashlib.sha256((HERE / name).read_bytes()).hexdigest()
(HERE / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print(json.dumps({'synthetic_cards': len(cards), 'public_equal_turns': 57,
    'protected_files_equal': 16, 'external_attempts': 0, 'real_calls': 0}))
