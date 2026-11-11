"""Independent review: synthetic inputs and existing public artifacts only."""
import asyncio
import copy
import dataclasses
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path
import pytest

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT/'backend/tests'))
sys.path.insert(0, str(ROOT/'backend/tests/evaluation'))
from acceptance.support.netguard import t09_network_guard
from mktkb.config import Settings
from mktkb.evaluation import p2_score_run as drive, p2_scoring as scoring, p2_runner as runner
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.product_adapter import ProductEvalAdapter, MockChatBackend, IngestSource, P2IngestPlan
from mktkb.evaluation.scorers import CaseResult, CaseCheck
import test_p2_holdout_scorecard as existing

pytestmark = pytest.mark.usefixtures('t09_network_guard')
@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setattr(Settings, 'model_config', {**Settings.model_config, 'env_file':None})

def specimen(version=3, row=7):
    case = CaseSpec(case_id='SYNTH-INDEPENDENT', suite='holdout', split='holdout',
        stratum='paraphrase', business_date='2026-11-11', question='合成测试问题',
        expected_values=('合成答案',), expected_sources=({'doc_code':'V04',
        'unit_key':'key', 'locator':{'sheet':'synthetic','row':7}},))
    source = {'source_id':'id','document_name':'D01_synthetic.xlsx','version_number':version,
        'status':'active','locator':{'sheet':'synthetic','row':row}}
    observation = {'case_id':case.case_id,'status':'ok','turns':[{'status':'ok','product':{
        'kind':'answer','text':'合成答案','sources':[source]}}]}
    return case, observation

CODES = {'D01_synthetic.xlsx':'D01'}
def scored(case, row, **kw):
    mapped = drive.remap_holdout_case(case, drive.load_holdout_source_map())
    return scoring.score_public_case(mapped,row,document_codes=CODES,include_source_version=True,**kw)

@pytest.mark.parametrize('version,want', [(3,'pass'),(2,'fail'),(4,'fail'),(None,'fail'),
    (True,'fail'),(False,'fail'),('3','fail'),(3.0,'fail'),(-3,'fail'),(0,'fail')])
def test_product_version_strict(version,want):
    case,row=specimen(version)
    assert scored(case,row).score.status == want

def test_real_unit_key_cannot_bypass_original_locator():
    case,row=specimen(row=8)
    index={'id':{'unit_key':'key','locator':{'sheet':'synthetic','row':8}}}
    assert scored(case,row,source_index=index).score.status == 'fail'

@pytest.mark.parametrize('index_version',[None,3])
def test_explicit_product_locator_version_conflict_blocks(index_version):
    case,row=specimen()
    row['turns'][0]['product']['sources'][0]['locator']['version_number']=4
    locator={'sheet':'synthetic','row':7}
    if index_version is not None:
        locator['version_number']=index_version
    row['turns'][0]['product']['evidence']=[{'unit_id':'id','unit_key':'key','locator':locator}]
    index=drive.source_index_from_rows({case.case_id:row})
    with pytest.raises(scoring.P2ScoringError,match='conflict'):
        scored(case,row,source_index=index)

@pytest.mark.parametrize('status',['error','skipped','skipped_requires_ocr','unknown'])
def test_nonquality_status_identity_preserved(status):
    case,row=specimen()
    mapped=drive.remap_holdout_case(case,drive.load_holdout_source_map())
    outcome=scoring.normalize_product_outcome(row['turns'][0],document_codes=CODES,include_source_version=True)
    original=CaseResult(case.case_id,status,(CaseCheck('source_hit','pass'),))
    assert scoring._version_source_checks(mapped,outcome,original) is original

def test_quality_checks_and_refusal_preserved():
    case,row=specimen()
    mapped=drive.remap_holdout_case(case,drive.load_holdout_source_map())
    old=scoring.score_public_case(mapped,row,document_codes=CODES)
    new=scoring.score_public_case(mapped,row,document_codes=CODES,include_source_version=True)
    assert [c for c in old.result.checks if c.check_id not in ('source_hit','source_forbidden')] == [
        c for c in new.result.checks if c.check_id not in ('source_hit','source_forbidden')]
    refused=dataclasses.replace(case,should_refuse=True,expected_kind='refusal',expected_values=())
    result=scored(refused,row)
    assert result.result.check('source_hit').status == 'skipped'
    assert result.score.status == 'fail'
    row['turns'][0]['product']['text']='错误值'
    assert scored(case,row).score.status == 'fail'

@pytest.mark.parametrize('version,want',[(2,'pass'),(3,'fail'),(4,'pass'),(None,'pass')])
def test_forbidden_wrong_version_not_hit(version,want):
    case,row=specimen(version)
    case=dataclasses.replace(case,expected_sources=(),forbidden_sources=case.expected_sources)
    assert scored(case,row).score.status == want

def test_independent_public_baseline_and_fixed_hashes(t09_network_guard):
    base='d7728db35655ae67569aec84cc4ededeaf7f7c13'
    module=types.ModuleType('mktkb.evaluation._independent_baseline')
    sys.modules[module.__name__]=module
    source=subprocess.check_output(['git','show',base+':backend/src/mktkb/evaluation/p2_scoring.py'])
    module.__file__=str(ROOT/'backend/src/mktkb/evaluation/p2_scoring.py')
    exec(compile(source,module.__file__,'exec'),module.__dict__)
    root=ROOT/'docs/reports/OBS-EVAL/P2/T207'
    codes=drive.load_document_codes(root/'cases/document-codes.json')
    report={'runs':[], 'network':None,'fixed_hashes':{}}
    for label,archive in [('R1','R1-fixed'),('R2','R2-fixed'),('R4','R4')]:
        folder=root/('p2-t207-'+label.lower()+'-20261111-01')
        cases=drive.load_cases_file(root/('cases/'+label+'.jsonl'))
        rows=drive.read_cases_jsonl(folder/'cases.jsonl')
        index=drive.source_index_from_rows(rows) or None
        current=drive.score_run(folder,cases=cases,document_codes=codes)
        prior=[module.score_public_case(c,rows.get(c.case_id),document_codes=codes,
            source_index=index,execution_mode=current.execution_mode).score for c in cases]
        assert [s.to_dict() for s in prior]==[s.to_dict() for s in current.scores]
        assert module.score_public_suites(prior,run_id=current.run_id,config_hash=current.config_hash).to_dict()==current.scorecard.to_dict()
        stored=json.loads((root/'scoring'/archive/'case_scores.json').read_text(encoding='utf-8'))
        assert stored['case_scores']==[s.to_dict() for s in current.scores]
        turns=0
        for row in rows.values():
            for turn in row.get('turns',[]):
                assert module.outcome_to_dict(module.normalize_product_outcome(turn,document_codes=codes,source_index=index)) == scoring.outcome_to_dict(scoring.normalize_product_outcome(turn,document_codes=codes,source_index=index))
                turns+=1
        report['runs'].append({'label':label,'cases':len(cases),'turns':turns,'all_values_equal':True})
    for path in ['backend/src/mktkb/evaluation/scorers.py','backend/src/mktkb/evaluation/runner.py']:
        assert subprocess.check_output(['git','show',base+':'+path]).replace(b'\r\n',b'\n')==(ROOT/path).read_bytes().replace(b'\r\n',b'\n')
    for path,want in {
        'docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl':'1648405845fd5e19b593e610b92f8505fdfd78a9e57079648dc14673576785d7',
        'docs/evidence/LOCAL-R1-20261101/budget/budget.json':'79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e',
        'docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json':'3ed427f42ac2eeedff489505b94f730eadba1dc38f1b9adecf94d25750b02a7c',
    }.items():
        actual=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
        assert actual==want
        report['fixed_hashes'][path]=actual
    report['network']=t09_network_guard.snapshot()
    Path(__file__).with_name('public-diff.json').write_text(json.dumps(report,indent=2),encoding='utf-8')

def test_real_runner_with_mapped_v04_and_real_mock_transport(tmp_path,t09_network_guard):
    async def execute():
        cases=existing._synthetic_cases(gold_doc_code='V04')
        dataset=existing.P2RunDataset('holdout',cases,{'dataset_version':'synthetic',
            'label_version':'synthetic','suite':'p2-holdout','manifest_sha256':'a'*64,
            'case_count':len(cases),'strata':dict(existing.STRATA_PLAN)})
        fixture=ROOT/'fixtures/acceptance'
        name='D01_物品位置表.xlsx'
        ingest=P2IngestPlan(sources=(
            IngestSource(path=fixture/'variants/V03_物品位置表_历史V1.xlsx',name=name),
            IngestSource(path=fixture/'normal'/name,document_ref=name),
            IngestSource(path=fixture/'variants/V04_物品位置表_新版V3.xlsx',document_ref=name)),label='independent')
        adapter=ProductEvalAdapter(tmp_path/'runner',chat=MockChatBackend(),dataset=dataset,
            ingest_plan=ingest,purge_traces_on_close=True)
        plan=existing._make_plan(cases)
        try:
            result=await runner.run_p2(plan,adapter=adapter,
                authorization=existing._dry_run_authorization(plan),now=existing.NOW)
        finally:
            await adapter.close()
        assert result.status=='succeeded', result.as_dict()
        card=json.loads((adapter.paths.run_dir/'holdout_scorecard.json').read_text(encoding='utf-8'))
        assert card['total']==30 and card['executed']==30 and card['errors']==0
        assert 'holdout_document_code_unmapped' not in {b['code'] for b in card['blocks']}
        assert card['real_calls']==0 and card['execution_mode']=='local_mock'
        assert not (adapter.paths.run_dir/'cases.jsonl').exists()
        assert not adapter.paths.trace_db.exists()
        Path(__file__).with_name('runner-e2e.json').write_text(json.dumps({
            'status':result.status,'total':card['total'],'executed':card['executed'],
            'passed':card['passed'],'failed':card['failed'],'errors':card['errors'],
            'network':t09_network_guard.snapshot(),'real_calls':0},indent=2),encoding='utf-8')
    asyncio.run(execute())

# R1 fresh review additions; old independent suite above is retained verbatim.
@pytest.mark.parametrize('raw,index_locator,code', [
    ({'row':8}, {'sheet':'synthetic','row':7}, 'source_locator_conflict'),
    ({'sheet':'different'}, {'sheet':'synthetic','row':7}, 'source_locator_conflict'),
    ({'row':7,'heading':'alpha'}, {'row':7,'heading':'beta'}, 'source_locator_conflict'),
    ({'row':7,'page':1}, {'row':7,'page':2}, 'source_locator_conflict'),
    ({'row':7,'version_number':0}, {'row':7}, 'source_version_conflict'),
    ({'row':7,'version_number':3.0}, {'row':7}, 'source_version_conflict'),
    ({'row':7}, {'row':7,'version_number':False}, 'source_version_conflict'),
    ({'row':7,'version_number':3}, {'row':7,'version_number':4}, 'source_version_conflict'),
])
def test_r1_independent_all_explicit_conflicts(raw,index_locator,code):
    case,row=specimen()
    row['turns'][0]['product']['sources'][0]['locator']=raw
    row['turns'][0]['product']['evidence']=[{'unit_id':'id','unit_key':'key','locator':index_locator}]
    index=drive.source_index_from_rows({case.case_id:row})
    with pytest.raises(scoring.P2ScoringError) as caught:
        scored(case,row,source_index=index)
    assert caught.value.code==code

@pytest.mark.parametrize('bad_version',[None,True,'3',3.0,0,-1])
def test_r1_independent_locator_cannot_repair_product_version(bad_version):
    case,row=specimen(bad_version)
    product=row['turns'][0]['product']
    if bad_version is None:
        del product['sources'][0]['version_number']
    product['sources'][0]['locator']['version_number']=3
    product['evidence']=[{'unit_id':'id','unit_key':'key','locator':{
        'row':7,'sheet':'synthetic','version_number':3}}]
    index=drive.source_index_from_rows({case.case_id:row})
    assert scored(case,row,source_index=index).score.status=='fail'
    assert 'version_number' not in scoring.normalize_product_outcome(row['turns'][0],
        document_codes=CODES,source_index=index,include_source_version=True).citations[0].locator

@pytest.mark.parametrize('raw,index_locator,want',[
    ({'row':7}, {'row':7,'sheet':'synthetic'}, 'pass'),
    ({'row':7,'sheet':'synthetic'}, {'row':7}, 'fail'),
    ({'row':7,'sheet':'synthetic','version_number':3},
     {'row':7,'sheet':'synthetic','version_number':3}, 'pass'),
])
def test_r1_independent_one_sided_fields_not_merged(raw,index_locator,want):
    case,row=specimen()
    row['turns'][0]['product']['sources'][0]['locator']=raw
    index={'id':{'unit_key':'key','locator':index_locator}}
    value=scored(case,row,source_index=index)
    assert value.score.status==want
    assert dict(value.outcome.citations[0].locator)=={**index_locator,'version_number':3}

@pytest.mark.parametrize('index_version',[None,3])
def test_r1_runner_b1_is_error_not_pass(index_version):
    import test_p2_holdout_source_map as helpers
    loc={'sheet':'synthetic','row':7}
    if index_version is not None:
        loc['version_number']=index_version
    product_row,_=helpers.r1_indexed_row({'sheet':'synthetic','row':7,'version_number':4},loc)
    marks,blocks=helpers.marks(product_row=product_row)
    assert marks[0].status=='error'
    block=next(b for b in blocks if b.code=='holdout_case_unscorable')
    assert 'source_version_conflict' in block.evidence['codes']
