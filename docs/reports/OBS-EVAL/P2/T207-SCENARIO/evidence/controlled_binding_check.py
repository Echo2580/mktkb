"""Manager-only, metadata-only check after independent source approval.

Private data stays in the existing verified loaders' process memory. The only
export is the closed safe_summary and whole-file hashes; no product is run.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[6]
PRIVATE = Path('C:/Users/dell1712/.codex/visualizations/2026/11/12/01a1cd24-bccf-7e00-80df-0b75f57f7d1c/t207-custody')
SEALED = Path('D:/mktkb-p2-holdout/v2')
KEY = Path('D:/mktkb-p2-holdout/keys/v2.key')
PROTECTED = (
    ROOT / 'docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl',
    ROOT / 'docs/evidence/LOCAL-R1-20261101/budget/budget.json',
    ROOT / 'docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json',
    PRIVATE / 'annotations-v0_2.fernet',
    PRIVATE / 'review-v0_2.fernet',
)
attempts = []
SAFE_FAILURE_CODES = frozenset((
    'scenario_structure_invalid', 'scenario_axis_invalid', 'scenario_targets_invalid',
    'scenario_refs_invalid', 'scenario_date_invalid', 'scenario_required_axis_invalid',
    'scenario_review_invalid', 'scenario_public_binding_mismatch', 'scenario_ciphertext_mismatch',
    'scenario_annotation_binding_mismatch', 'scenario_corpus_binding_invalid', 'scenario_coverage_invalid',
    'scenario_full_dataset_required', 'scenario_full_dataset_invalid', 'scenario_assignment_unknown',
    'scenario_decrypt_failed', 'scenario_review_counts_mismatch', 'scenario_assignment_unapproved',
    'scenario_recipe_invalid', 'scenario_ingest_binding_invalid', 'scenario_metadata_counts_invalid',
    'scenario_ingest_invalid', 'scenario_input_unreadable', 'scenario_input_size_invalid',
    'scenario_private_path_inside_workspace', 'scenario_json_invalid', 'scenario_duplicate_json_key',
    'P2_DATASET_INVALID',
))


def deny(*args, **kwargs):
    attempts.append('blocked')
    raise RuntimeError('network_forbidden')


def hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED}


def main():
    os.environ['MKTKB_NO_DOTENV'] = '1'
    os.environ['MKTKB_P2_HOLDOUT_ROOT'] = str(SEALED)
    os.environ['MKTKB_P2_HOLDOUT_KEY_FILE'] = str(KEY)
    sys.path.insert(0, str(ROOT / 'backend/src'))
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.create_connection = deny
    before = hashes()
    from mktkb.evaluation.p2_dataset import load_p2_dataset
    from mktkb.evaluation.p2_holdout_scenarios import load_scenario_contract
    dataset = load_p2_dataset(SEALED / 'manifest.json', visibility='holdout')
    contract = load_scenario_contract(
        dataset, annotation_path=PRIVATE / 'annotations-v0_2.fernet',
        key_file=KEY, review_path=PRIVATE / 'review-v0_2.fernet')
    summary = contract.safe_summary()
    after = hashes()
    if before != after or attempts:
        raise ValueError('controlled_check_failed')
    return dict(schema_version='p2-h2-scenario-binding-check/v0.1', status='PASS',
                summary=summary, protected_hashes=after, inputs_unchanged=True,
                network_attempts=len(attempts), product_test_count=0,
                real_model_calls=0, reservations_added=0, private_detail_export=False,
                quality_released=False)


if __name__ == '__main__':
    try:
        result = main()
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if type(code) is not str or code not in SAFE_FAILURE_CODES:
            code = 'actual_binding_check_failed'
        result = dict(schema_version='p2-h2-scenario-binding-check/v0.1', status='FAIL',
                      code=code, private_detail_export=False,
                      real_model_calls=0, quality_released=False)
    Path(__file__).with_name('actual-binding-check.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
