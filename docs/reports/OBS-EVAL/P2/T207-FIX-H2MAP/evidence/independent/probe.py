"""Independent H2MAP synthetic probes; no sealed materials or network."""
import copy
import json
import socket
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / 'backend/src'))
attempts = []
def deny(*args, **kwargs):
    attempts.append('external')
    raise AssertionError('offline only')
socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
from mktkb.evaluation import p2_score_run as drive
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.p2_scoring import P2ScoringError

case = CaseSpec(case_id='SYNTH-INDEPENDENT', suite='holdout', split='holdout',
    stratum='paraphrase', business_date='2026-11-11', question='合成核查问题',
    expected_values=('合成答案',), expected_sources=({'doc_code':'V04',
        'unit_key':'unit-key', 'locator':{'sheet':'synthetic','row':7}},))
def run(raw_version=None, index_version=None, raw_row=7):
    locator = {'sheet':'synthetic', 'row':raw_row}
    if raw_version is not None:
        locator['version_number'] = raw_version
    source = {'source_id':'unit-id', 'document_name':'D01_synthetic.xlsx',
        'version_number':3, 'status':'active', 'locator':locator}
    evidence_locator = {'sheet':'synthetic','row':7}
    if index_version is not None:
        evidence_locator['version_number'] = index_version
    row = {'case_id':case.case_id, 'status':'ok','turns':[{'status':'ok', 'product':{
        'kind':'answer', 'text':'合成答案', 'sources':[source], 'evidence':[
            {'unit_id':'unit-id','unit_key':'unit-key','locator':evidence_locator}]}}]}
    index = drive.source_index_from_rows({case.case_id:row})
    try:
        marks, issues = drive.holdout_case_scores_from_rows((case,), {case.case_id:row},
            document_codes={'D01_synthetic.xlsx':'D01'}, source_index=index)
        return {'status':marks[0].status, 'issues':issues, 'input':row, 'index':index}
    except P2ScoringError as exc:
        return {'error_code':exc.code, 'input':row, 'index':index}

report = {'raw_only_version_conflict_index_version_absent':run(4),
          'raw_version_conflict_index_version_matches':run(4,3),
          'index_version_conflict':run(3,4),
          'consistent':run(3,3),
          'network_attempts':attempts}
Path(__file__).with_name('counterexamples.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({key:{k:v for k,v in value.items() if k not in ('input','index')}
    if isinstance(value,dict) else value for key,value in report.items()},ensure_ascii=False))
