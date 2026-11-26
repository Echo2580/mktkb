from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys

ROOT = Path.cwd().resolve()
OUT = Path(__file__).resolve().parent
REPAIR = OUT.parents[1]
REV2 = REPAIR.parent
TMP = ROOT / '.tmp-r2-obs-acceptance-scope-repair1'
TOOL = REPAIR / 'work/native_patch.py'
PATCHES = REPAIR / 'patches'
SOURCE_PATHS = ['backend/src/mktkb/conversations/service.py', 'backend/src/mktkb/observability/evaluation_capture.py', 'backend/src/mktkb/rag/answer.py', 'backend/src/mktkb/rag/retrieval.py']
PROTECTED_PATHS = ['backend/src/mktkb/rag/query.py', 'backend/src/mktkb/rag/facts.py', 'backend/src/mktkb/qa/service.py']

def sha(data):
    return hashlib.sha256(data).hexdigest()

def filehash(path):
    return sha(path.read_bytes())

def snapshot(tree):
    return {str(p.relative_to(tree)): filehash(p) for p in tree.rglob('*') if p.is_file()}

def newtree(code, source):
    tree = TMP/code
    tree.mkdir(parents=True, exist_ok=False)
    for name, data in source.items():
        target = tree/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return tree

def run_tool(tree, patch, manifest, apply=False):
    args = [sys.executable, '-B', '-X', 'utf8', str(TOOL), '--root', str(tree), '--patch', str(patch), '--manifest', str(manifest)]
    if apply:
        args.append('--apply')
    result = subprocess.run(args, capture_output=True, timeout=12)
    output = result.stdout.decode('utf-8', 'replace').strip()
    # The CLI outputs only fixed codes/counts for all cases built by this probe.
    return {'exit': result.returncode, 'output': output, 'stderr_sha256': sha(result.stderr)}

def main():
    TMP.mkdir(parents=True, exist_ok=False)
    before_scope = {n:(ROOT/'.tmp-r2-obs-baseline'/n.replace('/','_')).read_bytes() for n in SOURCE_PATHS}
    current = {n:(ROOT/n).read_bytes() for n in SOURCE_PATHS+PROTECTED_PATHS}
    original_scope = REV2/'independent-acceptance/scope-http'
    prior_integrity = json.loads((original_scope/'final-integrity.json').read_text(encoding='utf-8'))
    old_capture = ROOT/'.tmp-r2-obs-acceptance-scope-http/native-eol-after/backend/src/mktkb/observability/evaluation_capture.py'
    rev2_capture = old_capture.read_bytes()
    repair_baseline = REPAIR/'baseline/evaluation_capture.py.before'
    assert rev2_capture == repair_baseline.read_bytes()
    assert sha(rev2_capture) == '7429be11226916419d8061241b6284b6b9b2a0e8467cb8aae37646d81a1967c1'
    initial = {n:sha(b) for n,b in current.items()}
    protection_text = (REPAIR/'PROTECTION.md').read_text(encoding='utf-8')
    protection = dict(re.findall(r'^- `([^`]+)`: `([0-9a-f]{64})`', protection_text, re.M))
    expected_current = {n:protection[n] for n in current}
    assert initial == expected_current
    manifests = {}
    bound = {}
    for prefix in ['increment-source','increment-rollback','cumulative-source','cumulative-rollback']:
        patch = PATCHES/(prefix+'.patch')
        manifest = PATCHES/(prefix+'.json')
        data = json.loads(manifest.read_text(encoding='utf-8'))
        bound[prefix] = {'patch_sha256':filehash(patch), 'manifest_sha256':filehash(manifest), 'patch_matches_manifest':filehash(patch)==data['patch_sha256'], 'patch_matches_protection':filehash(patch)==protection['patches/'+patch.name], 'manifest_matches_protection':filehash(manifest)==protection['patches/'+manifest.name]}
        assert all(bound[prefix][n] for n in ('patch_matches_manifest','patch_matches_protection','manifest_matches_protection'))
        manifests[prefix] = data
    assert filehash(TOOL) == protection['work/native_patch.py']

    retained_names = ['DEV-REPORT.md','VALIDATION.md','PROTECTION.md','SOURCE.patch','ROLLBACK.patch','CUSTODY-CONTRACT.md','work/safe_plan_projection.py']
    retained = {str(REV2/n):filehash(REV2/n) for n in retained_names}
    own_old = {
        original_scope/'SCOPE-HTTP-VERDICT.md':prior_integrity['report_sha256'],
        ROOT/'.tmp-r2-obs-acceptance-scope-http/scope_probe.py':prior_integrity['scope_probe_sha256'],
        ROOT/'.tmp-r2-obs-acceptance-scope-http/http_probe.py':prior_integrity['http_probe_sha256'],
    }
    historical_checks = {str(p.relative_to(ROOT)):filehash(p)==h for p,h in own_old.items()}
    prior_scope_evidence = json.loads((original_scope/'scope-evidence.json').read_text(encoding='utf-8'))
    for name in ['SOURCE.patch','ROLLBACK.patch']:
        historical_checks[str((REV2/name).relative_to(ROOT))] = filehash(REV2/name)==prior_scope_evidence['patches'][name]['sha256']
    assert all(historical_checks.values())
    retained.update({str(p):filehash(p) for p in own_old})
    retained.update({str(original_scope/n):filehash(original_scope/n) for n in ['scope-evidence.json','final-integrity.json']})
    contracts = REV2/'independent-acceptance/contracts'
    retained.update({str(contracts/n):filehash(contracts/n) for n in ['contract_probe.py','CONTRACT-VERDICT.md','PROBE-RESULTS.json','PROTECTION-AFTER.json']})

    # Reuse this review seat's prior independent strict hunk matcher, not developer tests.
    spec = importlib.util.spec_from_file_location('independent_original_scope', ROOT/'.tmp-r2-obs-acceptance-scope-http/scope_probe.py')
    independent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(independent)
    report = {'tool_sha256':filehash(TOOL), 'bindings':bound,'current_source_sha256':initial,'historical_hash_checks':historical_checks,'retained_current_sha256':{str(Path(n).relative_to(ROOT)):h for n,h in retained.items()},'roundtrips':{},'rejection_cases':[]}
    for which in ['increment','cumulative']:
        originals = dict(current)
        if which=='increment':
            originals['backend/src/mktkb/observability/evaluation_capture.py'] = rev2_capture
        else:
            originals.update(before_scope)
        data = manifests[which+'-source']
        expected_set = {'backend/src/mktkb/observability/evaluation_capture.py'} if which=='increment' else set(SOURCE_PATHS)
        assert set(data['files'])==expected_set
        tree = newtree('roundtrip-'+which, originals)
        patch, manifest = PATCHES/(which+'-source.patch'),PATCHES/(which+'-source.json')
        reconstructed, files, hunks = independent.replay_exact_context(originals,patch.read_bytes())
        assert set(files)==expected_set
        assert all(reconstructed[n]==current[n] for n in SOURCE_PATHS+PROTECTED_PATHS)
        before_snapshot = snapshot(tree)
        check = run_tool(tree,patch,manifest)
        assert check['exit']==0 and snapshot(tree)==before_snapshot
        apply = run_tool(tree,patch,manifest,True)
        assert apply['exit']==0 and all((tree/n).read_bytes()==current[n] for n in current)
        forward = {n:filehash(tree/n) for n in expected_set}
        backward_patch, backward_manifest = PATCHES/(which+'-rollback.patch'), PATCHES/(which+'-rollback.json')
        after_snapshot = snapshot(tree)
        rollback_check=run_tool(tree,backward_patch,backward_manifest)
        assert rollback_check['exit']==0 and snapshot(tree)==after_snapshot
        rollback_apply=run_tool(tree,backward_patch,backward_manifest,True)
        assert rollback_apply['exit']==0 and all((tree/n).read_bytes()==originals[n] for n in originals)
        report['roundtrips'][which]={'files':len(expected_set),'hunks':hunks,'default_check':check,'apply':apply,'rollback_default_check':rollback_check,'rollback_apply':rollback_apply,'forward_sha256':forward,'restored_sha256':{n:filehash(tree/n) for n in expected_set},'byte_equal_roundtrip':True,'check_only_no_writes':True,'independent_reconstruction_matches':True}

    def reject(code, original_bytes, patch_bytes, manifest_data, expected_error):
        case = TMP/code
        case.mkdir()
        tree = newtree(code+'/tree',original_bytes)
        p = case/'case.patch'; m=case/'case.json'
        p.write_bytes(patch_bytes)
        m.write_text(json.dumps(manifest_data),encoding='utf-8')
        initial_snapshot = snapshot(tree)
        run = run_tool(tree,p,m,True)
        unchanged = snapshot(tree)==initial_snapshot
        assert run['exit']==1 and unchanged and expected_error in run['output']
        report['rejection_cases'].append({'code':code,'result':run,'no_target_or_temp_write':unchanged})

    original_bytes = dict(current); original_bytes.update(before_scope)
    patch_bytes=(PATCHES/'cumulative-source.patch').read_bytes()
    data=manifests['cumulative-source']
    last=next(reversed(data['files']))
    bad=copy.deepcopy(data);bad['patch_sha256']='0'*64
    reject('MANIFEST_PATCH_HASH_BAD',original_bytes,patch_bytes,bad,'patch_hash')
    reject('PATCH_BYTES_TAMPERED',original_bytes,patch_bytes+b' ',data,'patch_hash')
    bad_input=dict(original_bytes);bad_input[last]+=b' '
    reject('LAST_TARGET_INPUT_BAD',bad_input,patch_bytes,data,'before_hash')
    bad=copy.deepcopy(data);bad['files'][last]['after']='0'*64
    reject('LAST_EXPECTED_OUTPUT_BAD',original_bytes,patch_bytes,bad,'after_hash')
    rows=patch_bytes.decode('utf-8').splitlines(keepends=True)
    last_section=max(i for i,s in enumerate(rows) if s.startswith('--- a/'))
    for i in range(last_section+2,len(rows)):
        if rows[i].startswith(' '):
            rows[i]=' '+rows[i][1:].rstrip('\n')+' \n';break
    changed=''.join(rows).encode('utf-8');bad=copy.deepcopy(data);bad['patch_sha256']=sha(changed)
    reject('LAST_HUNK_CONTEXT_BAD_REBOUND',original_bytes,changed,bad,'hunk_context')
    bad=copy.deepcopy(data);bad['files'].pop(last)
    reject('MANIFEST_PATH_SET_BAD',original_bytes,patch_bytes,bad,'path_set')
    rows=patch_bytes.decode('utf-8').splitlines(keepends=True)
    for i,line in enumerate(rows):
        if line.startswith('@@ '):
            rows[i]=re.sub(r'-(\d+),(\d+)',lambda m:'-'+m[1]+','+str(int(m[2])+1),line,count=1);break
    changed=''.join(rows).encode('utf-8');bad=copy.deepcopy(data);bad['patch_sha256']=sha(changed)
    reject('HUNK_COUNT_BAD_REBOUND',original_bytes,changed,bad,'bad_hunk_count')
    # Reverse-direction wrong last input also cannot write earlier valid files.
    bad_input=dict(current);bad_input[last]+=b' '
    reject('ROLLBACK_LAST_TARGET_INPUT_BAD',bad_input,(PATCHES/'cumulative-rollback.patch').read_bytes(),manifests['cumulative-rollback'],'before_hash')

    report['main_source_unchanged'] = all(filehash(ROOT/n)==h for n,h in initial.items())
    report['retained_files_unchanged_during_recheck'] = all(filehash(Path(n))==h for n,h in retained.items())
    assert report['main_source_unchanged'] and report['retained_files_unchanged_during_recheck']
    report['scope_verdict']='PASS'
    report['native_eol_packaging_verdict']='PASS'
    report['http_verdict']='INCOMPLETE_NOT_RERUN'
    (OUT/'SCOPE-RECHECK-EVIDENCE.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'roundtrips':len(report['roundtrips']),'rejections':len(report['rejection_cases']),'bindings':len(bound),'main_source_unchanged':report['main_source_unchanged'],'retained_files_unchanged_during_recheck':report['retained_files_unchanged_during_recheck'],'historical_hash_checks':len(historical_checks),'native_eol_packaging_verdict':report['native_eol_packaging_verdict']}))

if __name__=='__main__':
    main()
