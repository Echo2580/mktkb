"""New optional capture fields survive the existing encrypted IO contract."""
from pathlib import Path

from .test_p2_evidence_io import _envelope, _writer
from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence


def test_retrieval_event_encrypted_roundtrip(tmp_path):
    envelope = _envelope()
    payload = {'request_id': None, 'scope': 'direct_rag_retrieval', 'unit_ids': [],
        'candidate': True, 'truncated': False, 'empty': True, 'effective_roles': [],
        'role_unknown_count': 0, 'roles_state': 'available', 'stores_state': 'available',
        'stores_count': 0, 'store_join_status': 'item_filter_missing', 'candidate_count': 0,
        'page_has_more': False}
    envelope['capture']['events'] = [{'seq': 1, 'kind': 'retrieval_observed', 'payload': payload}]
    writer = _writer(tmp_path)
    receipt = writer.write_turn(envelope)
    result = read_encrypted_evidence(Path(receipt['path']), key=writer.key, expected_bindings=writer.bindings)
    assert result == envelope
