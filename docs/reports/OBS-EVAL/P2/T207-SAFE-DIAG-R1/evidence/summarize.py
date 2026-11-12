"""Summarize only newly replayed synthetic cards and the bounded R1 source diff."""
import difflib
import hashlib
import json
from pathlib import Path

from mktkb.evaluation.p2_diagnostics import validate_diagnostics

root = Path.cwd()
here = Path(__file__).resolve().parent
replayed = here / 'replayed-review'
summary = {'evidence_tier': 'developer_replay_not_independent_acceptance',
           'real_calls': 0, 'synthetic_runs': {}, 'repaired_counterexamples': {}}
for mode in ('normal', 'partial'):
    card = json.loads((replayed / ('runner-' + mode + '.json')).read_text(encoding='utf-8'))
    validate_diagnostics(card['diagnostics'], total=30)
    summary['synthetic_runs'][mode] = {
        'scorecard': {key: card[key] for key in ('total', 'passed', 'failed', 'executed', 'errors')},
        'diagnostics': card['diagnostics'],
        'blocks': [block['code'] for block in card['blocks']],
        'release_ready': card['release_ready'],
    }
for path in sorted(replayed.glob('counterexample-*.json')):
    card = json.loads(path.read_text(encoding='utf-8'))['writer_output']
    assert (card['passed'], card['executed'], card['errors']) == (0, 0, 1)
    assert card['blocks'][0]['code'] == 'holdout_scorecard_leak'
    assert 'holdout_hard_failure_unverified' in {block['code'] for block in card['blocks']}
    summary['repaired_counterexamples'][path.stem] = {
        key: card[key] for key in ('passed', 'executed', 'errors', 'blocks')}
(here / 'synthetic-summary.json').write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

diff = []
for before, current in (
    ('p2_diagnostics.before.py', 'backend/src/mktkb/evaluation/p2_diagnostics.py'),
    ('p2_runner.before.py', 'backend/src/mktkb/evaluation/p2_runner.py'),
    ('test_p2_holdout_scorecard.before.py', 'backend/tests/evaluation/test_p2_holdout_scorecard.py'),
):
    old = (here / before).read_text(encoding='utf-8')
    new = (root / current).read_text(encoding='utf-8')
    diff.extend(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=before, tofile=current))
(here / 'r1-source.diff').write_text(''.join(diff), encoding='utf-8')

original = root / 'docs/reports/OBS-EVAL/P2/T207-SAFE-DIAG/evidence/independent'
copies = {}
for name in ('test_independent_safe_diag.py', 'independent_guard.py', 'check_hashes.py', 'default_diff.py'):
    original_hash = hashlib.sha256((original / name).read_bytes()).hexdigest()
    replay_hash = hashlib.sha256((replayed / name).read_bytes()).hexdigest()
    assert original_hash == replay_hash
    copies[name] = original_hash
(here / 'replay-tool-hashes.json').write_text(json.dumps(copies, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'synthetic_runs': 2, 'repaired_saved_counterexamples': len(summary['repaired_counterexamples']),
                  'original_review_tools_identical': True}))
