"""Hash-only checks of protected files; no sealed question/answer decoding."""
import hashlib
import json
from pathlib import Path
import subprocess

BASE = '09ddc87520576958ff4c19be16f245f8197fdfe5'
fixed = {
    'docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl': '1648405845fd5e19b593e610b92f8505fdfd78a9e57079648dc14673576785d7',
    'docs/evidence/LOCAL-R1-20261101/budget/budget.json': '79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e',
    'docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json': '3ed427f42ac2eeedff489505b94f730eadba1dc38f1b9adecf94d25750b02a7c',
}
paths = tuple(fixed) + (
    'backend/src/mktkb/evaluation/p2_scoring.py',
    'backend/src/mktkb/evaluation/scorers.py',
    'backend/src/mktkb/evaluation/runner.py',
    'backend/src/mktkb/evaluation/p2_live.py',
    'backend/src/mktkb/evaluation/p2_dataset.py',
    'backend/src/mktkb/evaluation/p2_contracts.py',
    'tools/p2_live_execute.py',
    'docs/evaluation/p2-holdout-v2.manifest.json',
    'docs/evaluation/p2-holdout-v2.source-map.json',
    'docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json',
    'docs/reports/OBS-EVAL/P2/T207/cases/R1.jsonl',
    'docs/reports/OBS-EVAL/P2/T207/cases/R2.jsonl',
    'docs/reports/OBS-EVAL/P2/T207/cases/R4.jsonl',
)
records = []
for path in paths:
    after = Path(path).read_bytes()
    old = fixed.get(path)
    if old is None:
        before = subprocess.check_output(['git', 'show', BASE + ':' + path])
        old = hashlib.sha256(before).hexdigest()
    new = hashlib.sha256(after).hexdigest()
    assert old == new, path
    assert path not in fixed or new == fixed[path], path
    records.append({'path': path, 'baseline_sha256': old, 'current_sha256': new, 'equal': True,
                    'baseline_origin': 'handoff_fixed_hash' if path in fixed else 'git_commit'})
payload = {'baseline_commit': BASE, 'protected_files': records, 'all_equal': True,
           'real_calls': 0, 'sealed_content_parsed': False}
Path(__file__).with_name('protected-hashes.json').write_text(
    json.dumps(payload, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'protected_files': len(records), 'all_equal': True}))
