from pathlib import Path
import copy
import importlib.util
import socket
import subprocess
import sys
import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'backend/src/mktkb').is_dir())
sys.path.insert(0, str(ROOT / 'backend/tests'))
from evaluation.test_p2_evidence_io import _envelope, _writer
from mktkb.observability import evaluation_capture as cap
from cryptography.fernet import Fernet

spec = importlib.util.spec_from_file_location('r2_safe_repair1', Path(__file__).with_name('safe_plan_projection.py'))
safe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safe)


def payload(**updates):
    v = {'request_id':None, 'scope':'direct_rag_retrieval', 'unit_ids':[], 'candidate':True,
         'truncated':False, 'empty':True, 'effective_roles':[], 'roles_state':'available',
         'role_unknown_count':0, 'stores_state':'available', 'stores_count':0,
         'store_join_status':'unknown', 'candidate_count':0, 'page_has_more':False}
    v.update(updates)
    return v


def envelope(event=None):
    e = _envelope()
    e['completeness']['status'] = 'complete'
    if event is not None:
        e['capture']['events'] = [{'seq':1, 'kind':'retrieval_observed', 'payload':event}]
    return e


def test_roles_and_malformed_sentinels():
    assert safe.project_plan({'field_role':'location','field_roles':['status'], 'safe_roles':['status']})['field_roles'] == ['location','status']
    assert safe.project_plan({'field_role':'location','field_roles':[]})['status'] == 'observed'
    for v in (-1, True, 'PRIVATE_SENTINEL', None):
        assert safe.project_plan({'field_roles':[], 'role_unknown_count':v})['status'] == 'malformed'
    for key in ('candidate_count','stores_count','role_unknown_count','truncated','page_has_more'):
        for value in (-1, True, 'PRIVATE_SENTINEL', None):
            if key in ('truncated','page_has_more') and value is True:
                continue
            assert safe.project_retrieval(payload(**{key:value}))['status'] == 'malformed'
    assert safe.project_plan({})['status'] == 'field_missing'
    assert safe.project_plan({'field_roles':[]})['status'] == 'observed_empty'
    assert safe.project_plan({'field_roles':[], 'roles_state':'unknown'})['status'] == 'unknown'
    partial = safe.project_plan({'field_role':'location','field_roles':[], 'roles_state':'unknown', 'role_unknown_count':1})
    assert partial['status'] == 'unknown' and partial['field_roles'] == ['location']
    assert 'PRIVATE_SENTINEL' not in str(safe.project_plan({'field_roles':['PRIVATE_SENTINEL']}))


def test_combination_legacy_and_boundaries():
    legacy = {k:payload()[k] for k in ('request_id','scope','unit_ids','candidate','truncated','empty')}
    assert cap.clean_event_payload('retrieval_observed',legacy) == legacy
    for p in (payload(candidate_count=1), payload(unit_ids=['x'],empty=False), payload(candidate_count=513,unit_ids=['x'],empty=False), payload(unit_ids=['x','x'],candidate_count=2,empty=False)):
        with pytest.raises(cap.CaptureEventError): cap.clean_event_payload('retrieval_observed',p)
    for n in (0,1,512,513):
        p=payload(candidate_count=n,unit_ids=[str(x) for x in range(min(n,512))],empty=n==0,truncated=n>512,page_has_more=True)
        assert cap.clean_event_payload('retrieval_observed',p)==p


def test_context_gate_and_encrypted_roundtrip(tmp_path, monkeypatch):
    attempts = []
    def blocked(*args, **kwargs):
        attempts.append('blocked'); raise RuntimeError('blocked')
    import httpx
    monkeypatch.setattr(socket.socket,'connect',blocked)
    monkeypatch.setattr(socket.socket,'connect_ex',blocked)
    monkeypatch.setattr(socket,'getaddrinfo',blocked)
    monkeypatch.setattr(socket,'create_connection',blocked)
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',blocked)
    monkeypatch.setattr(subprocess,'Popen',blocked)
    writer = _writer(tmp_path)
    data = envelope(payload())
    receipt = writer.write_turn(data)
    outcome = safe.project_authenticated_turn(Path(receipt['path']),writer.key,expected_bindings=writer.bindings)
    assert outcome['status']=='observed' and outcome['events'][0]['candidate_count']==0
    assert safe.project_authenticated_turn(Path(receipt['path']),Fernet.generate_key(),expected_bindings=writer.bindings)['status']=='authentication_or_read_failed'
    bad = copy.deepcopy(data); bad['capture']['event_count'] = 2
    assert safe.project_validated_turn(bad,expected_bindings=writer.bindings)['status']=='invalid_envelope'
    bad = copy.deepcopy(data); bad['capture']['events'][0]['payload']['candidate_count'] = 1
    assert safe.project_validated_turn(bad,expected_bindings=writer.bindings)['status']=='invalid_envelope'
    failed = copy.deepcopy(data); failed['capture']['status']='failed'; failed['capture']['errors']=[{'code':'fail','stage':'emit','request_id':None,'detail':''}]
    assert safe.project_validated_turn(failed,expected_bindings=writer.bindings)['status']=='sink_failed'
    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event('retrieval_observed', **payload())
        cap.emit_capture_event('unknown_synthetic_kind')
    failed_actual = copy.deepcopy(data); failed_actual['capture'] = sink.snapshot()
    assert safe.project_validated_turn(failed_actual, expected_bindings=writer.bindings)['status'] == 'sink_failed'
    unsealed = copy.deepcopy(data); unsealed['capture']['status']='active'
    assert safe.project_validated_turn(unsealed,expected_bindings=writer.bindings)['status']=='sink_unsealed'
    incomplete = copy.deepcopy(data); incomplete['completeness']['status']='incomplete'
    assert safe.project_validated_turn(incomplete,expected_bindings=writer.bindings)['status']=='incomplete'
    absent = envelope(); assert safe.project_validated_turn(absent,expected_bindings=writer.bindings) == {'status':'not_captured','execution':'unknown'}
    pre = envelope()
    pre['capture']['events'] = [{'seq':1, 'kind':'direct_rag_answer', 'payload':{
        'request_id':None,'kind':'no_answer','text':'synthetic','reason':'DOCUMENT_NOT_FOUND',
        'answer_source':'refusal','cited_unit_ids':[],'fact_count':0,'facts':[],'state_keys':[]}}]
    assert safe.project_validated_turn(pre,expected_bindings=writer.bindings)['execution'] == 'not_executed'
    pre['capture']['events'][0]['payload']['reason'] = 'SECURITY_RESTRICTED_CONTACT'
    assert safe.project_validated_turn(pre,expected_bindings=writer.bindings)['execution'] == 'unknown'
    old = payload(); old.pop('candidate_count'); old.pop('store_join_status')
    old_out = safe.project_validated_turn(envelope(old),expected_bindings=writer.bindings)
    assert old_out['events'][0]['status']=='field_missing'
    assert safe.project_validated_turn(data,expected_bindings={})['status']=='binding_unavailable'
    assert attempts == []
    with pytest.raises(RuntimeError): socket.create_connection(('203.0.113.1',9))
    with pytest.raises(RuntimeError): subprocess.Popen(['synthetic'])
    assert attempts == ['blocked','blocked']
