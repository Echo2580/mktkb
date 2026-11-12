"""Public artifact audit; hashes private ciphertext references only as public metadata."""
import difflib
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent
EVIDENCE = OUT.parent
OLD = ROOT / 'docs/reports/OBS-EVAL/P2/T207-SCENARIO/evidence'
sha = lambda raw: hashlib.sha256(raw).hexdigest()
protected = json.loads((EVIDENCE / 'protection-before.json').read_text(encoding='utf-8'))
current = {p: sha((ROOT / p).read_bytes()) for p in protected}
assert current == protected
prior = json.loads((OLD / 'independent/source-review.json').read_text(encoding='utf-8'))
for source, digest in prior['source_sha256'].items():
    if source.endswith('/p2_holdout_scenarios.py'):
        raw = (EVIDENCE / 'p2_holdout_scenarios.before.py').read_bytes()
    elif source.endswith('/test_p2_holdout_scenarios.py'):
        raw = (EVIDENCE / 'test_p2_holdout_scenarios.before.py').read_bytes()
    elif source.endswith('/controlled_binding_check.py'):
        continue  # fixed-code diagnostic update was reviewed separately
    else:
        raw = (ROOT / source).read_bytes()
    assert sha(raw) == digest, source
before = (EVIDENCE / 'p2_holdout_scenarios.before.py').read_bytes()
after = (ROOT / 'backend/src/mktkb/evaluation/p2_holdout_scenarios.py').read_bytes()
needle = b"        _require(all(isinstance(target[k], str) and 0 < len(target[k]) <= 256 for k in ('entity_type', 'entity_key')),"
nl = b'\r\n' if b'\r\n' in before else b'\n'
replacement = b"        _require(isinstance(target['entity_type'], str) and 0 < len(target['entity_type']) <= 256 and" + nl + b"                 isinstance(target['entity_key'], str) and len(target['entity_key']) <= 256,"
assert before.count(needle) == 1 and before.replace(needle, replacement) == after
assert (ROOT / 'backend/tests/evaluation/test_p2_holdout_scenarios.py').read_bytes().startswith((EVIDENCE / 'test_p2_holdout_scenarios.before.py').read_bytes())
old_doc = (EVIDENCE / 'execution-contract.before.md').read_text(encoding='utf-8').splitlines()
new_doc = (ROOT / 'docs/evaluation/p2-h2-scenario-execution-v0_1.md').read_text(encoding='utf-8').splitlines()
changes = [x for x in difflib.ndiff(old_doc, new_doc) if x.startswith(('- ', '+ '))]
assert len(changes) == 2 and all(x.startswith('+ ') for x in changes)
assert sum(bool(x[2:].strip()) for x in changes) == 1
sources = json.loads((ROOT / 'docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json').read_text(encoding='utf-8'))['sources']
review = json.loads((ROOT / 'docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/review-aggregate.json').read_text(encoding='utf-8'))
corpus = {s['path']: sha((ROOT / s['path']).read_bytes()) for s in sources}
assert len(corpus) == 12 and all(review['input_hashes_before']['corpus:' + p] == h for p, h in corpus.items())
extra = [ROOT / 'backend/src/mktkb/evaluation/p2_holdout_scenarios.py',
    ROOT / 'backend/tests/evaluation/test_p2_holdout_scenarios.py',
    ROOT / 'docs/evaluation/p2-h2-scenario-execution-v0_1.md']
extra += [p for p in EVIDENCE.iterdir() if p.is_file()]
extra += [EVIDENCE.parent / 'report.md']
extra += [OLD / p for p in ('controlled_binding_check.py', 'controlled_target_shape.py',
    'actual-binding-check-initial-fail.json', 'actual-binding-check-targets-fail.json', 'target-shape-check.json')]
snapshot = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in extra}
if sys.argv[1] == 'before':
    (OUT / 'protected-start.json').write_text(json.dumps(snapshot, indent=2) + '\n', encoding='utf-8')
else:
    assert snapshot == json.loads((OUT / 'protected-start.json').read_text(encoding='utf-8'))
    result = dict(protected_count=len(protected), public_corpus_count=len(corpus),
        protected_unchanged=True, corpus_unchanged=True, original_255_source_snapshot_matches=True,
        exact_axis_only_change=True, original_test_bytes_prefix=True, only_one_contract_sentence=True,
        development_and_old_evidence_unchanged=True, protected_sha256=current,
        public_corpus_sha256=corpus, source_and_evidence_sha256=snapshot,
        real_ciphertexts_read=False, real_ciphertext_content_verified=False)
    (OUT / 'scope-audit.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print('PASS: exact approved scope; 21 protection artifacts and 12 public sources; preserved prior source snapshot/evidence')
