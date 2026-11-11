"""Read sealed expectations only inside this process; export fixed aggregate counts.

No questions, answers, case IDs, source locators or arbitrary label strings leave
the process. No product execution or network access. Does not mutate the fixture.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / 'backend/src'))
os.environ['MKTKB_NO_DOTENV'] = '1'
os.environ['MKTKB_P2_HOLDOUT_ROOT'] = 'D:/mktkb-p2-holdout/v2'
os.environ['MKTKB_P2_HOLDOUT_KEY_FILE'] = 'D:/mktkb-p2-holdout/keys/v2.key'

def no_network(*args, **kwargs):
    raise RuntimeError('network_forbidden')

socket.socket.connect = no_network
socket.socket.connect_ex = no_network
socket.create_connection = no_network

def main():
    from mktkb.evaluation.p2_dataset import load_p2_dataset
    sealed_root = Path(os.environ['MKTKB_P2_HOLDOUT_ROOT'])
    ds = load_p2_dataset(sealed_root / 'manifest.json', visibility='holdout')
    state_path = ROOT / 'docs/reports/OBS-EVAL/P2/T207-FIX-A-R1/evidence/h2-state-out.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    # The version identity is determined from the PUBLIC import order, never
    # guessed from a hidden question, answer or expected value.
    versions = {'V03': ('D01', 1), 'V04': ('D01', 3), 'V05': ('D01', 4), 'V06': ('D02', 2)}
    active = {}
    for doc in state['documents']:
        code = doc['name'].split('_', 1)[0]
        if code in ('D01', 'D02'):
            active[code] = doc['active_version_number']
    counts = dict(cases=len(ds.cases), positive_cases=0, positive_cases_requiring_inactive_version=0,
                  expected_refs_to_inactive_versions=0, relevant_refs_to_inactive_versions=0,
                  source_expectations_without_version_key=0)
    for case in ds.cases:
        positive = case.expected_kind in ('answer', 'conflict')
        counts['positive_cases'] += int(positive)
        bad = False
        for field in ('expected_sources', 'relevant_units'):
            for ref in getattr(case, field):
                if 'version_number' not in ref.get('locator', {}):
                    counts['source_expectations_without_version_key'] += 1
                target = versions.get(ref.get('doc_code'))
                if target and active.get(target[0]) != target[1]:
                    counts['expected_refs_to_inactive_versions' if field == 'expected_sources' else 'relevant_refs_to_inactive_versions'] += 1
                    if positive and field == 'expected_sources':
                        bad = True
        counts['positive_cases_requiring_inactive_version'] += int(bad)
    payload = {
        'schema_version': 'p2-h2-contract-audit/v0.1',
        'counts': counts,
        'public_final_active_versions': active,
        'sealed_manifest_sha256': hashlib.sha256((sealed_root / 'manifest.json').read_bytes()).hexdigest(),
        'public_state_sha256': hashlib.sha256(state_path.read_bytes()).hexdigest(),
        'expected_source_active_conflict': counts['positive_cases_requiring_inactive_version'] > 0,
        'new_real_calls': 0,
        'detail_export': False,
    }
    target = Path(__file__).with_name('contract-audit.json')
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(json.dumps({'ok': False, 'code': 'contract_audit_failed', 'detail_export': False}))
        raise SystemExit(1)
