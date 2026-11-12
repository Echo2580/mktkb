"""Summarize reviewer-created aggregate-only evidence, never sealed input."""
import json
from pathlib import Path

here = Path(__file__).parent
summary = {'verdict': 'FAIL', 'real_calls': 0, 'source': 'independent synthetic runs', 'runs': {}}
for mode in ('normal', 'partial'):
    card = json.loads((here / ('runner-' + mode + '.json')).read_text(encoding='utf-8'))
    d = card['diagnostics']; r = d['refusal_confusion']
    def ratio(a, b):
        return None if b == 0 else a / b
    summary['runs'][mode] = {
        'passed': card['passed'], 'failed': card['failed'], 'errors': card['errors'],
        'counts': d['counts'], 'refusal_confusion': r,
        'precision': ratio(r['tp'], r['tp'] + r['fp']),
        'recall': ratio(r['tp'], r['tp'] + r['fn']),
        'false_refusal': ratio(r['fp'], r['fp'] + r['tn']),
        'source': d['source'], 'by_stratum': d['by_stratum'],
        'classification_status': d['classification_status'],
        'hard_failure_evidence': d['hard_failure_evidence'],
        'hard_failure_unverified_block_present': any(b['code'] == 'holdout_hard_failure_unverified' for b in card['blocks']),
        'release_ready': card['release_ready'],
    }
summary['reason_chains'] = [json.loads((here / ('reason-' + reason + '.json')).read_text(encoding='utf-8'))
    for reason in ('json_parse', 'record_facts', 'unknown')]
summary['network'] = json.loads((here / 'network-guard.json').read_text(encoding='utf-8'))
summary['protected_files'] = json.loads((here / 'protected-hashes.json').read_text(encoding='utf-8'))['all_equal']
summary['public_cases'] = sum(r['cases'] for r in json.loads((here / 'default-differential.json').read_text(encoding='utf-8'))['public_runs'])
summary['independent_probes'] = {'passed': 21, 'failed': 4, 'skip': 0, 'xfail': 0}
(here / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'verdict': summary['verdict'], 'normal': summary['runs']['normal']['counts'],
    'partial': summary['runs']['partial']['counts'], 'external_attempts': summary['network']['external_attempts']}, ensure_ascii=False))
