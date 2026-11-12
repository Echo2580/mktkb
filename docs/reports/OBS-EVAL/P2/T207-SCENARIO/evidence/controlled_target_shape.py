"""Fixed Boolean syntax diagnostics only; no target values or per-case data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket

PRIVATE = Path('C:/Users/dell1712/.codex/visualizations/2026/11/12/01a1cd24-bccf-7e00-80df-0b75f57f7d1c/t207-custody')
KEY = Path('D:/mktkb-p2-holdout/keys/v2.key')
EXPECTED = '3d60c27364244a6ff8df76f66994ee50e5037649ea346c4b538f1fb9175ce4d0'


def deny(*args, **kwargs):
    raise RuntimeError('network_forbidden')


def shape_flags(payload):
    flags = dict(entity_key_null_present=False, entity_key_other_type_present=False,
                 empty_entity_key_string_present=False, entity_type_invalid_present=False,
                 filter_non_scalar_value_present=False, filter_non_mapping_present=False,
                 target_fields_mismatch_present=False)
    if type(payload) is not dict or type(payload.get('cases')) is not list or len(payload['cases']) != 30:
        raise ValueError('invalid_shape')
    for case in payload['cases']:
        for axis in ('safety', 'cross_user', 'cross_entity', 'stale_source'):
            for target in case['axes'][axis]['targets']:
                if type(target) is not dict or set(target) != {'entity_type', 'entity_key', 'filters'}:
                    flags['target_fields_mismatch_present'] = True
                    continue
                value = target['entity_key']
                flags['entity_key_null_present'] |= value is None
                flags['entity_key_other_type_present'] |= value is not None and type(value) is not str
                flags['empty_entity_key_string_present'] |= type(value) is str and not value
                flags['entity_type_invalid_present'] |= type(target['entity_type']) is not str or not target['entity_type']
                filters = target['filters']
                flags['filter_non_mapping_present'] |= type(filters) is not dict
                if type(filters) is dict:
                    flags['filter_non_scalar_value_present'] |= any(
                        item is not None and type(item) not in (str, int, float, bool) for item in filters.values())
    if not all(type(value) is bool for value in flags.values()):
        raise ValueError('invalid_shape')
    return flags


def main():
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.create_connection = deny
    from cryptography.fernet import Fernet
    cipher = (PRIVATE / 'annotations-v0_2.fernet').read_bytes()
    if not 0 < len(cipher) <= 8 * 1024 * 1024 or hashlib.sha256(cipher).hexdigest() != EXPECTED:
        raise ValueError('invalid_shape')
    raw = KEY.read_bytes()
    if not 0 < len(raw) <= 4096:
        raise ValueError('invalid_shape')
    payload = json.loads(Fernet(raw.strip()).decrypt(cipher).decode('utf-8'))
    return dict(schema_version='p2-h2-target-shape-check/v0.1', status='PASS',
                syntax_flags=shape_flags(payload), private_detail_export=False,
                product_test_count=0, real_model_calls=0, quality_released=False)


if __name__ == '__main__':
    try:
        result = main()
    except Exception:
        result = dict(schema_version='p2-h2-target-shape-check/v0.1', status='FAIL',
                      code='target_shape_check_failed', private_detail_export=False,
                      real_model_calls=0, quality_released=False)
    Path(__file__).with_name('target-shape-check.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['status'] == 'PASS' else 1)
