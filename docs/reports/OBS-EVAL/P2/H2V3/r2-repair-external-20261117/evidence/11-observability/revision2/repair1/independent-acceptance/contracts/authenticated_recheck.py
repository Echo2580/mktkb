"""Independent repair1 synthetic authentication and context-gate checks."""
from __future__ import annotations
import copy
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import threading
from types import SimpleNamespace as NS
from unittest.mock import patch

platform._syscmd_ver = lambda *a, **k: ('Windows', '10', '10.0.0')
sys.dont_write_bytecode = True
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'backend/src/mktkb').is_dir())
TMP = ROOT/'.tmp-r2-obs-acceptance-contracts-repair1'
IO = Path(sys.argv[1]).resolve()
assert IO.is_dir() and not list(IO.iterdir())
os.chdir(TMP)
sys.path.insert(0,str(ROOT/'backend/src'))
timer=threading.Timer(55,lambda:os._exit(124)); timer.daemon=True; timer.start()
attempts={'network':0,'subprocess':0,'private_file':0}
def guard(event,args):
    if event in ('socket.connect','socket.getaddrinfo'):
        attempts['network']+=1; raise RuntimeError('NETWORK_BLOCKED')
    if event=='subprocess.Popen':
        attempts['subprocess']+=1; raise RuntimeError('SUBPROCESS_BLOCKED')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        p=Path(os.fsdecode(args[0]))
        if p.name=='.env' or p.name.startswith('.env.') or (p.suffix=='.fernet' and IO not in p.resolve().parents):
            attempts['private_file']+=1; raise RuntimeError('PRIVATE_FILE_BLOCKED')
sys.addaudithook(guard)
from mktkb.config import Settings
Settings.model_config={**Settings.model_config,'env_file':None}
from cryptography.fernet import Fernet
from mktkb.observability import evaluation_capture as cap
from mktkb.evaluation.p2_evidence_io import EvidenceWriter,canonical_json_bytes,read_encrypted_evidence
from mktkb.rag import answer
from mktkb.rag.types import QueryPlan,QueryState

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
safe=load('independent_repair1_safe',Path(__file__).resolve().parents[2]/'work/safe_plan_projection.py')
support=load('independent_synthetic_fixture',ROOT/'backend/tests/evaluation/test_p2_evidence_io.py')
writer=EvidenceWriter(root_dir=IO/'writer-root',key=Fernet.generate_key(),bindings=support._bindings(),run_name='independent-synthetic')
records=[]; outputs=[]; serial=0
def check(code,fn):
    try: records.append({'code':code,'pass':bool(fn())})
    except Exception as exc: records.append({'code':code,'pass':False,'exception':type(exc).__name__})
def payload(n=0,**kw):
    return dict(request_id=None,scope='direct_rag_retrieval',unit_ids=['SYNTHETIC_ID_%03d'%i for i in range(min(n,512))],
                candidate=True,truncated=n>512,empty=n==0,candidate_count=n,candidate_scope_limit='unknown',
                roles_state='available',effective_roles=['location','status'],role_unknown_count=0,
                effective_mode='record',effective_enumerate=True,stores_state='available',stores_count=0,
                store_join_status='unknown',page_has_more=True,**kw)
def env(events=None):
    v=support._envelope(); v['completeness']['status']='complete'
    if events is not None:
        v['capture']['events']=[{'seq':i+1,'kind':kind,'payload':copy.deepcopy(p)} for i,(kind,p) in enumerate(events)]
        v['capture']['event_count']=v['capture']['seq']=len(events)
    return v
def call(v,*,raw=False,bindings=None,key=None):
    global serial
    serial+=1; v=copy.deepcopy(v); v['turn']['turn_index']=serial
    if raw:
        path=IO/('invalid-%03d.fernet'%serial)
        assert not path.exists(); path.write_bytes(Fernet(writer.key).encrypt(canonical_json_bytes(v)))
    else: path=Path(writer.write_turn(v)['path'])
    out=safe.project_authenticated_turn(path,key or writer.key,expected_bindings=writer.bindings if bindings is None else bindings)
    outputs.append(out); return out,path,v
def status(v,expected,**kw): return call(v,**kw)[0]['status']==expected

for n in (0,1,512,513):
    def boundary(n=n):
        p=payload(n); out,path,v=call(env([('retrieval_observed',p)]))
        back=read_encrypted_evidence(path,key=writer.key,expected_bindings=writer.bindings)
        return back==v and out['status']=='observed' and out['events'][0]['candidate_count']==n and out['events'][0]['truncated']==(n>512) and out['events'][0]['page_has_more'] is True
    check('AUTH_BOUNDARY_%03d'%n,boundary)
old={k:payload()[k] for k in ('request_id','scope','unit_ids','candidate','truncated','empty')}
def old_compat():
    out,path,v=call(env([('retrieval_observed',old)]))
    back=read_encrypted_evidence(path,key=writer.key,expected_bindings=writer.bindings)
    return back==v and back['capture']['events'][0]['payload']==old and out['events']==[{'status':'field_missing'}]
check('AUTH_OLD_NO_SYNTHESIS',old_compat)
prepared=dict(request_id='SYNTHETIC_REQUEST',path='SYNTHETIC_PATH',mode='record',filters={'store':'SYNTHETIC_ENTITY'},terms=[],
              as_of=None,include_future=False,enumerate=True,clarification=False,state_keys=[],state_as_of=None,state_pending_slot=None,state_last_kind=None,
              field_role='location',field_roles=['status'],safe_roles=['quantity'],roles_state='available',role_unknown_count=0)
check('AUTH_PREPARED_MERGE',lambda:call(env([('plan_observed',prepared),('retrieval_observed',payload())]))[0]['prepared_plans'][0]['field_roles']==['location','quantity','status'])
check('AUTH_MISSING_RETRIEVAL',lambda:call(env([]))[0]=={'status':'not_captured','execution':'unknown'})
check('AUTH_OLD_CONTEXT_ONLY',lambda:call(env())[0]=={'status':'not_captured','execution':'unknown'})

sink=cap.CaptureSink()
with cap.capture_scope(sink):
    cap.emit_capture_event('retrieval_observed',**payload())
    cap.emit_capture_event('unknown_synthetic_kind')
failed=env(); failed['capture']=sink.snapshot()
check('AUTH_REAL_FAILED_SINK',lambda:status(failed,'sink_failed'))
for name,mutate,expected in [
 ('UNSEALED',lambda v:v['capture'].update(status='active'),'sink_unsealed'),
 ('CAPTURE_ERRORS',lambda v:v['capture'].update(errors=[dict(code='synthetic',stage='emit',request_id=None,detail='SYNTHETIC_PRIVATE')]),'sink_failed'),
 ('INCOMPLETE',lambda v:v['completeness'].update(status='incomplete'),'incomplete'),
 ('REPLAY',lambda v:v['completeness'].update(replay=True),'incomplete'),
 ('REPLAYED_STATUS',lambda v:v['completeness'].update(status='replayed'),'incomplete'),
 ('COMPLETE_ERRORS',lambda v:v['completeness'].update(errors=['synthetic']),'incomplete'),
 ('MISSING_KINDS',lambda v:v['completeness'].update(missing_event_kinds=['retrieval_observed']),'incomplete'),
 ('TIMEOUT',lambda v:v['turn'].update(timed_out=True),'incomplete')]:
    v=env([('retrieval_observed',payload())]); mutate(v)
    check('AUTH_'+name,lambda v=v,e=expected:status(v,e))
for name,mutate in [
 ('EVENT_COUNT',lambda v:v['capture'].update(event_count=99)),
 ('NEG_COUNT',lambda v:v['capture']['events'][0]['payload'].update(candidate_count=-1)),
 ('BOOL_COUNT',lambda v:v['capture']['events'][0]['payload'].update(candidate_count=True)),
 ('CONFLICT_COUNT',lambda v:v['capture']['events'][0]['payload'].update(candidate_count=1)),
 ('DUPLICATE_IDS',lambda v:v['capture']['events'][0]['payload'].update(candidate_count=2,unit_ids=['SYNTHETIC_ID','SYNTHETIC_ID'],empty=False)),
 ('CANDIDATE_FALSE',lambda v:v['capture']['events'][0]['payload'].update(candidate=False)),
 ('BAD_ROLE',lambda v:v['capture']['events'][0]['payload'].update(effective_roles=['SYNTHETIC_PRIVATE'])),
 ('BAD_SCOPE_CODE',lambda v:v['capture']['events'][0]['payload'].update(candidate_scope_limit='SYNTHETIC_PRIVATE'))]:
    v=env([('retrieval_observed',payload())]); mutate(v)
    check('AUTH_REJECT_'+name,lambda v=v:status(v,'authentication_or_read_failed',raw=True))
valid=env([('retrieval_observed',payload())])
check('AUTH_WRONG_KEY',lambda:status(valid,'authentication_or_read_failed',key=Fernet.generate_key()))
wrong=dict(writer.bindings); wrong['run_id']='SYNTHETIC_WRONG_BINDING'
check('AUTH_WRONG_BINDING',lambda:status(valid,'authentication_or_read_failed',bindings=wrong))
check('AUTH_MISSING_BINDING',lambda:status(valid,'binding_unavailable',bindings={}))
def corrupt_ciphertext():
    out,path,v=call(valid)
    broken=IO/'corrupt.fernet'; assert not broken.exists()
    token=bytearray(path.read_bytes()); token[len(token)//2]^=1; broken.write_bytes(token)
    result=safe.project_authenticated_turn(broken,writer.key,expected_bindings=writer.bindings); outputs.append(result)
    return result=={'status':'authentication_or_read_failed'}
check('AUTH_TAMPERED_CIPHERTEXT',corrupt_ciphertext)

def direct(reason):
    return dict(request_id=None,kind='no_answer',text='SYNTHETIC_TEXT',reason=reason,answer_source='refusal',cited_unit_ids=[],fact_count=0,facts=[],state_keys=[])
for reason in ('DOCUMENT_NOT_FOUND','UNKNOWN_STORE','RECORD_ONLY'):
    check('AUTH_PRE_'+reason,lambda r=reason:call(env([('direct_rag_answer',direct(r))]))[0]=={'status':'not_captured','execution':'not_executed'})
for reason in ('SECURITY_RESTRICTED_CONTACT','SYNTHETIC_PRIVATE',None):
    check('AUTH_UNKNOWN_REASON_%02d'%len(records),lambda r=reason:call(env([('direct_rag_answer',direct(r))]))[0]=={'status':'not_captured','execution':'unknown'})
check('AUTH_DUPLICATE_DIRECT_UNKNOWN',lambda:call(env([('direct_rag_answer',direct('DOCUMENT_NOT_FOUND')),('direct_rag_answer',direct('DOCUMENT_NOT_FOUND'))]))[0]['execution']=='unknown')

base=QueryPlan(question='synthetic',mode='record',query_text='synthetic',field_role=None,field_label=None,filters={},terms=(),state=QueryState(),enumerate=True)
def prove_pre_search(reason):
    p=replace(base,reason='DOCUMENT_NOT_FOUND') if reason=='DOCUMENT_NOT_FOUND' else replace(base,unknown_store='SYNTHETIC_STORE') if reason=='UNKNOWN_STORE' else replace(base,mode='document')
    calls=[]
    class Index:
        config=NS(provider_mode='offline',page_size=10,record_only=reason=='RECORD_ONLY',business_date=None)
        def load_state(self,*a):return QueryState()
        def lexicon_data(self):return {}
        def save_state(self,*a):calls.append('save')
        def search(self,*a,**k):calls.append('search');raise AssertionError('SEARCH_EXECUTED')
    with patch.object(answer,'build_lexicon',return_value=None),patch.object(answer,'parse_query',return_value=p):
        result=answer.answer_question(Index(),'synthetic',user_id='synthetic',conversation_id='synthetic')
    return result.reason==reason and calls==['save']
for reason in ('DOCUMENT_NOT_FOUND','UNKNOWN_STORE','RECORD_ONLY'):
    check('ACTUAL_PRE_SEARCH_'+reason,lambda r=reason:prove_pre_search(r))
check('SAFE_SENTINEL_CLOSURE',lambda:not any(s in json.dumps(outputs) for s in ('SYNTHETIC_ID','SYNTHETIC_ENTITY','SYNTHETIC_PATH','SYNTHETIC_PRIVATE','SYNTHETIC_TEXT','SYNTHETIC_REQUEST','SYNTHETIC_WRONG_BINDING')))
before=dict(attempts)
for code,fn in [('NETWORK_GUARD',lambda:socket.create_connection(('203.0.113.1',9))),('SUBPROCESS_GUARD',lambda:subprocess.Popen(['synthetic']))]:
    try:fn(); records.append({'code':code,'pass':False})
    except RuntimeError:records.append({'code':code,'pass':True})
report={'checks':records,'passed':sum(r['pass'] for r in records),'failed':sum(not r['pass'] for r in records),
        'encrypted_cases':serial,'pre_positive_guard_attempts':before,'post_positive_guard_attempts':attempts}
(TMP/'authenticated-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2));timer.cancel();sys.exit(1 if report['failed'] else 0)
