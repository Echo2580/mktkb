"""Hash public protected artifacts and compare only the approved R1 edits."""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path.cwd()
EVIDENCE = Path(__file__).resolve().parent
protected = json.loads((EVIDENCE / 'protection-before.json').read_text(encoding='utf-8'))
current = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in protected}
assert current == protected
review = json.loads((ROOT / 'docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/review-aggregate.json').read_text(encoding='utf-8'))
sources = json.loads((ROOT / 'docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json').read_text(encoding='utf-8'))['sources']
corpus = {row['path']: hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() for row in sources}
assert len(corpus) == 12
assert all(review['input_hashes_before']['corpus:' + name] == digest for name, digest in corpus.items())
files = [
    ('backend/src/mktkb/evaluation/p2_holdout_scenarios.py', 'p2_holdout_scenarios.before.py'),
    ('backend/tests/evaluation/test_p2_holdout_scenarios.py', 'test_p2_holdout_scenarios.before.py'),
    ('docs/evaluation/p2-h2-scenario-execution-v0_1.md', 'execution-contract.before.md'),
]
diffs = []
for name, snapshot in files:
    before = (EVIDENCE / snapshot).read_bytes()
    after = (ROOT / name).read_bytes()
    if name.endswith('/p2_holdout_scenarios.py'):
        old = b"        _require(all(isinstance(target[k], str) and 0 < len(target[k]) <= 256 for k in ('entity_type', 'entity_key')),"
        newline = b'\r\n' if b'\r\n' in before else b'\n'
        new = (b"        _require(isinstance(target['entity_type'], str) and 0 < len(target['entity_type']) <= 256 and" + newline +
               b"                 isinstance(target['entity_key'], str) and len(target['entity_key']) <= 256,")
        assert before.count(old) == 1 and before.replace(old, new) == after
    elif name.endswith('/test_p2_holdout_scenarios.py'):
        assert after.startswith(before)
    else:
        changes = [line for line in difflib.ndiff(before.decode('utf-8').splitlines(), after.decode('utf-8').splitlines())
                   if line.startswith(('- ', '+ '))]
        assert len(changes) == 2 and all(line.startswith('+ ') for line in changes)
    diffs.extend(difflib.unified_diff(before.decode('utf-8').splitlines(keepends=True),
        after.decode('utf-8').splitlines(keepends=True), fromfile=snapshot, tofile=name))
(EVIDENCE / 'r1-exact.diff').write_text(''.join(diffs), encoding='utf-8')
guard = json.loads((EVIDENCE / 'network-guard.json').read_text(encoding='utf-8'))
assert guard['guarded_tests'] == 76 and guard['external_attempts'] == guard['pytest_exit_status'] == 0
payload = dict(protected_unchanged=True, protected_count=len(protected), protected_sha256=current,
    public_corpus_unchanged=True, public_corpus_count=len(corpus), public_corpus_sha256=corpus,
    only_axis_condition_changed=True, original_tests_bytes_retained_as_prefix=True,
    execution_contract_only_one_sentence_added=True, final_network_guard=guard)
(EVIDENCE / 'protection-after.json').write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
print('PASS: 21 protected files and 12 public sources unchanged; exact source/test/doc scope verified; 76 guarded tests, 0 external attempts')
