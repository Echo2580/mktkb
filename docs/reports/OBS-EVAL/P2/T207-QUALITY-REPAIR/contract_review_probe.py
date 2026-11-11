"""Independent offline contract review. Only fixed aggregates may leave this process."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
os.environ['MKTKB_NO_DOTENV'] = '1'
os.environ['MKTKB_P2_HOLDOUT_ROOT'] = 'D:/mktkb-p2-holdout/v2'
os.environ['MKTKB_P2_HOLDOUT_KEY_FILE'] = 'D:/mktkb-p2-holdout/keys/v2.key'
sys.path.insert(0, str(ROOT / 'backend/src'))
os.chdir(ROOT)


def deny(*args, **kwargs):
    raise RuntimeError('network_forbidden')


socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.socket.sendto = deny
socket.create_connection = deny
socket.getaddrinfo = deny


def audit_hook(event, args):
    global DENIED_EVENT
    if event.startswith('socket.') and event not in ('socket.__new__', 'socket.gethostname'):
        DENIED_EVENT = event if event in ('socket.gethostname', 'socket.gethostbyname', 'socket.bind', 'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyaddr') else 'other_socket_event'
        raise RuntimeError('network_forbidden')
    if event in ('subprocess.Popen', 'os.system'):
        DENIED_EVENT = 'child_process_event'
        raise RuntimeError('child_process_forbidden')


sys.addaudithook(audit_hook)
STAGE = 'startup'
DENIED_EVENT = 'none'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    global STAGE
    # Credentials are accessed only by the established loader, never by this probe.
    # Import the unchanged data-layer modules without unrelated app package init
    # (mktkb.__init__ imports the full ASGI app and host platform discovery).
    for name, suffix in (('mktkb', 'mktkb'), ('mktkb.evaluation', 'mktkb/evaluation'),
                         ('mktkb.observability', 'mktkb/observability')):
        package = ModuleType(name)
        package.__path__ = [str(ROOT / 'backend/src' / suffix)]
        sys.modules[name] = package
    from mktkb.evaluation.p2_dataset import load_p2_dataset
    STAGE = 'public_inputs'

    plan_path = ROOT / 'docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json'
    state_path = ROOT / 'docs/reports/OBS-EVAL/P2/T207-FIX-A-R1/evidence/h2-state-out.json'
    manager_path = HERE / 'contract-audit.json'
    manifest_path = Path(os.environ['MKTKB_P2_HOLDOUT_ROOT']) / 'manifest.json'
    watched = (plan_path, state_path, manager_path, manifest_path)
    before = tuple(map(digest, watched))
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    state = json.loads(state_path.read_text(encoding='utf-8'))
    manager = json.loads(manager_path.read_text(encoding='utf-8'))
    allowed = frozenset(('D01','D02','D03','D04','D05','D06','V01','V03','V04','V05','V06','V07'))
    by_name = {doc['name']: doc for doc in state['documents']}
    upload_counts = Counter()
    mapping = {}
    sha_version_matches = 0
    order_matches = 0
    receipt_matches = 0
    final_published = {}
    for index, source in enumerate(plan['sources']):
        path = Path(source['path'])
        code = path.name.split('_', 1)[0]
        assert code in allowed
        name = source.get('name') or path.name
        slot = source.get('document_ref') or name
        upload_counts[slot] += 1
        number = upload_counts[slot]
        document = by_name[slot]
        doc_code = slot.split('_', 1)[0]
        assert doc_code in allowed
        matches = [v for v in document['versions'] if v['sha256'] == digest(path)]
        assert len(matches) == 1
        matched = matches[0]
        sha_version_matches += 1
        order_matches += int(matched['number'] == number)
        receipt = state['receipts'][index]
        # Historical probe encodes receipts by upload name, not file basename.
        receipt_matches += int(receipt['code'] == name.split('_', 1)[0] and receipt['name'] == name)
        mapping[code] = (doc_code, matched['number'])
        if source.get('publish', True):
            final_published[slot] = number
    STAGE = 'public_checks'
    active_matches = sum(by_name[name]['active_version_number'] == number
                         for name, number in final_published.items())
    active = {code: by_name[next(name for name in by_name if name.split('_', 1)[0] == code)]['active_version_number']
              for code in ('D01', 'D02')}
    v04_doc, v04_number = mapping['V04']
    v04 = next(v for name, doc in by_name.items() if name.split('_', 1)[0] == v04_doc
               for v in doc['versions'] if v['number'] == v04_number)
    public_checks = {
        'source_count': len(plan['sources']),
        'state_source_count_matches': state['sources'] == len(plan['sources']),
        'plan_label_matches': plan['label'] == state['plan_label'],
        'sha_version_matches': sha_version_matches,
        'ordered_version_matches': order_matches,
        'ordered_receipt_matches': receipt_matches,
        'document_count': len(final_published),
        'last_published_active_matches': active_matches,
        'fixed_variant_mapping_matches': all(mapping[k] == v for k,v in {
            'V03': ('D01', 1), 'V04': ('D01', 3), 'V05': ('D01', 4), 'V06': ('D02', 2)}.items()),
        'v04_is_version_3': v04_number == 3,
        'v04_is_superseded': v04['state'] == 'superseded',
        'v04_is_inactive': v04['is_active'] is False,
        'd01_active_is_4': active['D01'] == 4,
        'd02_active_is_2': active['D02'] == 2,
    }
    STAGE = 'controlled_loader'
    ds = load_p2_dataset(manifest_path, visibility='holdout')
    STAGE = 'controlled_aggregation'
    counts = dict(cases=len(ds.cases), positive_cases=0,
                  positive_cases_requiring_inactive_version=0,
                  expected_refs_to_inactive_versions=0,
                  relevant_refs_to_inactive_versions=0,
                  source_expectations_without_version_key=0)
    extra = dict(all_expected_refs=0, all_relevant_refs=0,
                 unmapped_source_references=0, positive_cases_with_no_active_expected_alternative=0)
    all_active = {name.split('_', 1)[0]: doc['active_version_number'] for name,doc in by_name.items()}
    for case in ds.cases:
        positive = case.expected_kind in ('answer', 'conflict')
        counts['positive_cases'] += int(positive)
        inactive_expected = 0
        active_expected = 0
        for field in ('expected_sources', 'relevant_units'):
            for ref in getattr(case, field):
                extra['all_expected_refs' if field == 'expected_sources' else 'all_relevant_refs'] += 1
                counts['source_expectations_without_version_key'] += int('version_number' not in ref.get('locator', {}))
                # A base document code without a version denotes its active slot;
                # a variant code names the unique public imported version.
                code = ref.get('doc_code')
                target = ((code, all_active[code]) if code in all_active else mapping.get(code))
                if target is None:
                    extra['unmapped_source_references'] += 1
                    continue
                inactive = all_active.get(target[0]) != target[1]
                if inactive:
                    counts['expected_refs_to_inactive_versions' if field == 'expected_sources' else 'relevant_refs_to_inactive_versions'] += 1
                if field == 'expected_sources':
                    inactive_expected += int(inactive)
                    active_expected += int(not inactive)
        counts['positive_cases_requiring_inactive_version'] += int(positive and inactive_expected > 0)
        extra['positive_cases_with_no_active_expected_alternative'] += int(positive and inactive_expected > 0 and active_expected == 0)
    output = {
        'schema_version': 'p2-h2-contract-independent-review/v0.1',
        'public_checks': public_checks,
        'counts': counts,
        'additional_counts': extra,
        'manager_counts_match': counts == manager['counts'],
        'manager_public_hashes_match': manager['public_state_sha256'] == before[1] and manager['sealed_manifest_sha256'] == before[3],
        'public_ingest_plan_sha256': before[0],
        'public_state_sha256': before[1],
        'public_manifest_sha256': before[3],
        'watched_inputs_unchanged': before == tuple(map(digest, watched)),
        'expected_source_active_conflict': counts['positive_cases_requiring_inactive_version'] > 0,
        'new_real_calls': 0,
        'network_forbidden': True,
        'child_processes_forbidden': True,
        'detail_export': False,
    }
    STAGE = 'aggregate_assertions'
    print(json.dumps(output, indent=2))
    assert all(public_checks[k] for k in public_checks if k not in ('source_count','sha_version_matches','ordered_version_matches','ordered_receipt_matches','document_count','last_published_active_matches'))
    assert sha_version_matches == order_matches == receipt_matches == len(plan['sources'])
    assert active_matches == len(final_published)
    assert output['manager_counts_match'] and output['manager_public_hashes_match'] and output['watched_inputs_unchanged']
    (HERE / 'contract-review-aggregate.json').write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        error_kind = next((name for name, typ in (('import_error', ImportError), ('permission_error', PermissionError), ('runtime_error', RuntimeError), ('assertion_error', AssertionError)) if isinstance(exc, typ)), 'other_error')
        print(json.dumps({'ok': False, 'code': 'independent_contract_review_failed', 'stage': STAGE, 'denied_event': DENIED_EVENT, 'error_kind': error_kind, 'detail_export': False}))
        raise SystemExit(1)
