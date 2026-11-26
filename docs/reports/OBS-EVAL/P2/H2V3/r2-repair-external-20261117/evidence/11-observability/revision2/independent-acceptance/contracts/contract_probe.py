"""Independent synthetic acceptance; emits fixed codes and counts only."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import platform
from pathlib import Path
import socket
import subprocess
import sys
import threading
from types import SimpleNamespace as NS
from dataclasses import replace
from unittest.mock import patch

# Prevent dependency-import platform discovery from launching cmd.exe.
# This scaffolding value is never used by retrieval or capture semantics.
platform._syscmd_ver = lambda *args, **kwargs: ('Windows', '10', '10.0.0')

ROOT = Path(__file__).resolve().parents[11]
assert (ROOT / 'backend/src/mktkb').is_dir()
TMP = ROOT / '.tmp-r2-obs-acceptance-contracts'
os.chdir(TMP)
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'backend/src'))
WATCHDOG = threading.Timer(55, lambda: os._exit(124))
WATCHDOG.daemon = True
WATCHDOG.start()
ATTEMPTS = {'network': 0, 'subprocess': 0, 'private_file': 0}

def audit(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        ATTEMPTS['network'] += 1
        raise RuntimeError('NETWORK_BLOCKED')
    if event == 'subprocess.Popen':
        ATTEMPTS['subprocess'] += 1
        raise RuntimeError('SUBPROCESS_BLOCKED')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        p = Path(os.fsdecode(args[0]))
        if p.name == '.env' or p.name.startswith('.env.'):
            ATTEMPTS['private_file'] += 1
            raise RuntimeError('PRIVATE_FILE_BLOCKED')
        if p.suffix == '.fernet' and TMP not in p.resolve().parents and 'contracts-synthetic-io' not in p.parts:
            ATTEMPTS['private_file'] += 1
            raise RuntimeError('PRIVATE_FILE_BLOCKED')

sys.addaudithook(audit)
from mktkb.observability import evaluation_capture as cap
from mktkb.rag import answer as answer
from mktkb.rag.errors import RagError
from mktkb.rag.types import QueryPlan, QueryState, RagAnswer, RetrievalResult
from mktkb.config import Settings
Settings.model_config = {**Settings.model_config, 'env_file': None}

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

projection = load('contract_safe_projection', Path(__file__).resolve().parents[2] / 'work/safe_plan_projection.py')
RESULTS = []
DETAILS = {}

def check(code, fn):
    try:
        success = bool(fn())
        RESULTS.append({'code': code, 'pass': success})
    except Exception as exc:
        RESULTS.append({'code': code, 'pass': False, 'exception': type(exc).__name__})

def rejected(kind, payload):
    try:
        cap.clean_event_payload(kind, payload)
    except cap.CaptureEventError:
        return True
    return False

def retrieval(**updates):
    value = dict(request_id=None, scope='direct_rag_retrieval', unit_ids=[], candidate=True,
                 truncated=False, empty=True, effective_roles=[], roles_state='available',
                 role_unknown_count=0, effective_mode='record', effective_enumerate=True,
                 stores_state='available', stores_count=0, store_join_status='unknown',
                 candidate_count=0, candidate_scope_limit='unknown', page_has_more=False)
    return {**value, **updates}

def prepared(**updates):
    value = dict(request_id='synthetic', path='rag', mode='record', filters={}, terms=[],
                 as_of=None, include_future=False, enumerate=True, clarification=False,
                 state_keys=[], state_as_of=None, state_pending_slot=None, state_last_kind=None)
    return {**value, **updates}

def plan(**updates):
    return replace(QueryPlan(question='synthetic', mode='record', query_text='synthetic',
                field_role='location', field_label=None, filters={}, terms=(),
                state=QueryState(), enumerate=True, field_roles=('status',)), **updates)

for values, expected in [(None, ([], 1)), ([], ([], 0)), (['location'], (['location'], 0)),
                         (['location', 'SYNTHETIC_PRIVATE'], (['location'], 1)),
                         ([True, 1, {}], ([], 3)), ('location', ([], 1))]:
    check('ROLE_%02d' % len(RESULTS), lambda v=values, e=expected: cap.safe_roles(v) == e)
for state, expected in [(NS(), ('unknown', None)), (NS(stores=None), ('unknown', None)),
                         (NS(stores=[]), ('available', 0)), (NS(stores=['private']), ('available', 1)),
                         (NS(stores=-1), ('unknown', None)), (NS(stores=True), ('unknown', None)),
                         (NS(stores={}), ('unknown', None))]:
    check('STORES_%02d' % len(RESULTS), lambda s=state, e=expected: cap.safe_stores(s) == e)
check('SCHEMA_LEGACY_PLAN', lambda: cap.clean_event_payload('plan_observed', prepared()) == prepared())
old = {k: retrieval()[k] for k in ('request_id', 'scope', 'unit_ids', 'candidate', 'truncated', 'empty')}
check('SCHEMA_LEGACY_RETRIEVAL', lambda: cap.clean_event_payload('retrieval_observed', old) == old)
for key, value in [('candidate_count', -1), ('candidate_count', True), ('stores_count', -1),
                   ('stores_count', False), ('role_unknown_count', -1), ('role_unknown_count', True),
                   ('effective_roles', ['SYNTHETIC_PRIVATE']), ('store_join_status', 'SYNTHETIC_PRIVATE'),
                   ('candidate_scope_limit', 'all_corpus'), ('roles_state', 'invalid'),
                   ('stores_state', 'invalid'), ('unit_ids', ['x'] * 513)]:
    check('SCHEMA_REJECT_%02d' % len(RESULTS), lambda k=key, v=value: rejected('retrieval_observed', retrieval(**{k:v})))
check('SCHEMA_BOUND_512', lambda: not rejected('retrieval_observed', retrieval(unit_ids=['x%03d'%i for i in range(512)], candidate_count=512, empty=False)))
check('SCHEMA_UNKNOWN_STORES', lambda: not rejected('retrieval_observed', retrieval(stores_state='unknown', stores_count=None)))
check('SCHEMA_UNKNOWN_STORES_MISMATCH', lambda: rejected('retrieval_observed', retrieval(stores_state='unknown', stores_count=0)))
check('SCHEMA_AVAILABLE_STORES_MISMATCH', lambda: rejected('retrieval_observed', retrieval(stores_count=None)))
for code, value in [('COUNT_ID_MISMATCH', retrieval(unit_ids=['synthetic'], candidate_count=0, empty=False)),
                    ('COUNT_EMPTY_MISMATCH', retrieval(candidate_count=1)),
                    ('TRUNCATION_MISMATCH', retrieval(unit_ids=['synthetic'], candidate_count=513, empty=False, truncated=False))]:
    check('SCHEMA_' + code, lambda v=value: rejected('retrieval_observed', v))

check('PROJECTION_MISSING', lambda: projection.project_plan({}) == {'status':'field_missing'})
check('PROJECTION_EMPTY', lambda: projection.project_plan({'field_roles':[]})['status'] == 'observed_empty')
check('PROJECTION_INVALID', lambda: projection.project_plan({'field_roles':None})['status'] == 'invalid_type')
check('PROJECTION_NOT_PROCESSED', lambda: projection.project_plan({}, processed=False)['status'] == 'projection_not_processed')
check('PROJECTION_FAILED', lambda: projection.project_plan(None)['status'] == 'projection_failed')
check('PROJECTION_UNKNOWN', lambda: projection.project_plan({'roles_state':'unknown', 'field_roles':[]})['status'] == 'unknown')
check('PROJECTION_PRIMARY_MERGE', lambda: projection.project_plan({'field_role':'location','field_roles':['status']})['field_roles'] == ['location','status'])
check('PROJECTION_PRIMARY_EMPTY_LIST', lambda: projection.project_plan({'field_role':'location','field_roles':[]})['field_roles'] == ['location'])
for invalid in (-1, True, 'SYNTHETIC_PRIVATE', None):
    check('PROJECTION_BAD_UNKNOWN_COUNT_%02d'%len(RESULTS), lambda v=invalid: projection.project_plan({'field_roles':[], 'role_unknown_count':v})['status'] not in ('observed','observed_empty'))
check('PROJECTION_UNKNOWN_COUNT', lambda: projection.project_plan({'field_roles':[], 'role_unknown_count':2}) == {'status':'invalid_role','field_roles':[],'invalid_count':2})
check('PROJECTION_RETRIEVAL_MISSING', lambda: projection.project_retrieval({})['status'] == 'field_missing')
check('PROJECTION_RETRIEVAL_NOT_PROCESSED', lambda: projection.project_retrieval({},processed=False)['status'] == 'projection_not_processed')
check('PROJECTION_RETRIEVAL_FAILED', lambda: projection.project_retrieval(None)['status'] == 'projection_failed')
check('PROJECTION_RETRIEVAL_BAD_JOIN', lambda: projection.project_retrieval({'store_join_status':'SYNTHETIC_PRIVATE'})['status'] == 'invalid_join_status')
for key, value in [('candidate_count', -1), ('candidate_count', True), ('stores_count', -1), ('truncated','SYNTHETIC_PRIVATE')]:
    check('PROJECTION_MALFORMED_%02d'%len(RESULTS), lambda k=key,v=value: projection.project_retrieval(retrieval(**{k:v}))['status'] != 'observed')
privacy_payload = retrieval(effective_roles=['location','SYNTHETIC_PRIVATE'], unit_ids=['SYNTHETIC_CANDIDATE'],
                            candidate_count=1, empty=False)
privacy_payload.update({'entity':'SYNTHETIC_ENTITY','path':'SYNTHETIC_PATH'})
check('PROJECTION_PRIVACY', lambda: not any(s in json.dumps(projection.project_retrieval(privacy_payload)) for s in ['SYNTHETIC_PRIVATE','SYNTHETIC_CANDIDATE','SYNTHETIC_ENTITY','SYNTHETIC_PATH']))

class Index:
    config = NS(provider_mode='offline', page_size=10, record_only=False, business_date=None)
    def __init__(self, p, mode='normal', size=0): self.p=p; self.mode=mode; self.calls=[]; self.size=size
    def load_state(self, *args): return QueryState()
    def lexicon_data(self): return {}
    def search(self,*args,**kwargs):
        self.calls.append('search')
        if self.mode=='error': raise RagError('SYNTHETIC_ERROR')
        chunks=[NS(chunk_id='c%03d'%i,kind='record',record_unit_id='u%03d'%i,unit_ids=()) for i in range(self.size)]
        return RetrievalResult(plan=self.p,revision=1,exact=chunks,total=self.size,has_more=True,diagnostics={})
    def save_state(self, state): self.calls.append('save')

def run_answer(p, sink=None, *, mode='normal',size=0, extra=None):
    index=Index(p,mode,size)
    with patch.object(answer,'build_lexicon',return_value=None), patch.object(answer,'parse_query',return_value=p), \
         patch.object(answer,'financial_metric_question',return_value=None), patch.object(answer,'FactValidator',return_value=None), \
         patch.object(answer,'_answer_record',side_effect=lambda i,p,r,v,d,t: RagAnswer(kind='answer',question='synthetic',text='synthetic',state=p.state.to_dict(),diagnostics=d)), \
         patch.object(answer,'_answer_document',side_effect=lambda i,p,r,v,d,t: RagAnswer(kind='answer',question='synthetic',text='synthetic',state=p.state.to_dict(),diagnostics=d)):
        if sink is None: result=answer.answer_question(index,'synthetic',user_id='synthetic',conversation_id='synthetic')
        else:
            with cap.capture_scope(sink): result=answer.answer_question(index,'synthetic',user_id='synthetic',conversation_id='synthetic')
    return result,index.calls

def observed(p, size=0, mode='normal'):
    sink=cap.CaptureSink(); result,calls=run_answer(p,sink,mode=mode,size=size)
    return result,calls,sink,[e['payload'] for e in sink.events if e['kind']=='retrieval_observed']

check('ANSWER_PRE_REFUSAL', lambda: (lambda o:o[0].kind=='no_answer' and o[1]==['save'] and o[3]==[])(observed(plan(reason='DOCUMENT_NOT_FOUND'))))
check('ANSWER_SEARCH_ERROR', lambda: (lambda o:o[0].kind=='error' and o[1]==['search','save'] and o[3]==[])(observed(plan(),mode='error')))
check('ANSWER_ROLE_MERGE', lambda: observed(plan())[3][0]['effective_roles']==['status','location'])
check('ANSWER_UNKNOWN_NOT_SUCCESS_EMPTY', lambda: observed(plan())[3][0]['store_join_status']=='unknown')
check('ANSWER_SCOPE_BOUND_513', lambda: (lambda p: p['candidate_count']==513 and len(p['unit_ids'])==512 and p['truncated'] and p['page_has_more'] and p['candidate_scope_limit']=='unknown')(observed(plan(),size=513)[3][0]))

def safe_helper_fault():
    off,_=run_answer(plan())
    with patch.object(answer,'safe_roles',side_effect=RuntimeError('SYNTHETIC_PRIVATE')):
        on,_,sink,events=observed(plan())
    return (off.kind,off.text)==(on.kind,on.text) and sink.failed and not events and 'SYNTHETIC_PRIVATE' not in str(sink.errors)
check('ANSWER_HELPER_FAULT', safe_helper_fault)

class EmitFailSink(cap.CaptureSink):
    def emit(self,*args,**kwargs): raise RuntimeError('SYNTHETIC_PRIVATE')
check('ANSWER_SINK_EMIT_FAULT',lambda: (lambda s: (run_answer(plan(),s)[0].kind=='answer' and s.failed))(EmitFailSink()))

class FailFailSink(EmitFailSink):
    def fail(self,*args,**kwargs): raise RuntimeError('SYNTHETIC_SINK_FAIL')
check('ANSWER_SINK_FAIL_FAULT_HARDENING',lambda: run_answer(plan(),FailFailSink())[0].kind=='answer')

def service_probe(helper_fault=False):
    from mktkb.conversations import service
    p=plan(field_role='location',field_roles=())
    qa=NS(prepare=lambda *a:(None,p), answer=lambda *a:RagAnswer(kind='answer',question='synthetic',text='synthetic',state={}))
    claim=NS(initial_revision=1,request_id='synthetic',conversation_id='synthetic')
    sink=cap.CaptureSink()
    def execute():
        c=service._answer(None,NS(id='synthetic'),claim,'synthetic',None,1.0,qa=qa)
        try: c.send(None)
        except StopIteration as stop: return stop.value
        finally: c.close()
    with patch.object(service,'_rag_owns_turn',return_value=True):
        off=execute()
        with cap.capture_scope(sink):
            if helper_fault:
                with patch.object(service,'safe_roles',side_effect=RuntimeError('SYNTHETIC_HELPER')): on=execute()
            else: on=execute()
    if helper_fault: return off.kind==on.kind
    payload=[e['payload'] for e in sink.events if e['kind']=='plan_observed'][0]
    DETAILS['prepared_primary_preserved']=payload['field_role']=='location'
    return projection.project_plan(payload).get('field_roles')==['location']
check('PREPARED_CAPTURE_PRIMARY_SAFE_MERGE',service_probe)
check('PREPARED_HELPER_FAULT_HARDENING',lambda:service_probe(True))

def failed_sink_context():
    sink=cap.CaptureSink()
    with cap.capture_scope(sink):
        cap.emit_capture_event('retrieval_observed',**retrieval())
        cap.emit_capture_event('unknown_synthetic_kind')
    output=projection.project_retrieval(sink.events[0]['payload'])
    DETAILS['failed_sink_payload_projection']={'sink_failed':sink.failed,'status':output['status'],'count':output['candidate_count']}
    # A payload-only helper cannot establish the provenance gate. Retain as a
    # required integration gate, separate from malformed-field findings.
    return sink.failed and output['status']!='observed'
check('SAFE_FAILED_SINK_CONTEXT_GATE',failed_sink_context)

DETAILS['minimal_safe_outputs']={
    'primary_with_empty_multi':projection.project_plan({'field_role':'location','field_roles':[]}),
    'negative_unknown_count':projection.project_plan({'field_roles':[],'role_unknown_count':-1}),
    'negative_candidate_count':projection.project_retrieval(retrieval(candidate_count=-1)),
    'negative_stores_count':projection.project_retrieval(retrieval(stores_count=-1)),
}

def synthetic_io():
    support=load('contract_io_fixture',ROOT/'backend/tests/evaluation/test_p2_evidence_io.py')
    from mktkb.evaluation.p2_evidence_io import EvidenceWriter, read_encrypted_evidence, validate_turn_evidence
    from cryptography.fernet import Fernet
    io_root=Path(sys.argv[1]) if len(sys.argv)>1 else TMP/'io-root'
    writer=EvidenceWriter(root_dir=io_root,key=Fernet.generate_key(),bindings=support._bindings(),run_name='synthetic-contracts')
    for name,payload,kind in [('old',old,'retrieval_observed'),('new',retrieval(),'retrieval_observed'),('plan',prepared(field_role='location',field_roles=[]),'plan_observed')]:
        env=support._envelope(); env['turn']['turn_index']={'old':0,'new':1,'plan':2}[name]
        env['capture']['events']=[dict(seq=1,kind=kind,payload=copy.deepcopy(payload))]
        assert validate_turn_evidence(env)==env
        receipt=writer.write_turn(env)
        read=read_encrypted_evidence(Path(receipt['path']),key=writer.key,expected_bindings=writer.bindings)
        assert read==env
        assert 'SYNTHETIC_PRIVATE'.encode() not in Path(receipt['path']).read_bytes()
        if name=='old': assert set(read['capture']['events'][0]['payload'])==set(old)
        if name=='new': assert projection.project_retrieval(read['capture']['events'][0]['payload'])['candidate_count']==0
    bad=support._envelope(); bad['capture']['event_count']=2
    try: validate_turn_evidence(bad)
    except Exception as exc:
        assert type(exc).__name__=='EvidenceIntegrityError'
        DETAILS['malformed_envelope_rejected']=True
    else: return False
    return True
check('SYNTHETIC_ENCRYPTED_IO',synthetic_io)

DETAILS['pre_positive_guard_attempts']=dict(ATTEMPTS)
for code,fn in [('NETWORK_GUARD',lambda: socket.create_connection(('203.0.113.1',9))),('SUBPROCESS_GUARD',lambda:subprocess.Popen(['synthetic']))]:
    try: fn(); RESULTS.append({'code':code,'pass':False})
    except RuntimeError: RESULTS.append({'code':code,'pass':True})
DETAILS['post_positive_guard_attempts']=dict(ATTEMPTS)
report={'checks':RESULTS,'passed':sum(r['pass'] for r in RESULTS),'failed':sum(not r['pass'] for r in RESULTS),'details':DETAILS}
(TMP/'probe-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
WATCHDOG.cancel()
sys.exit(1 if report['failed'] else 0)
