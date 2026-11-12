"""Four frozen scenarios; all private inputs below are freshly synthetic."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from mktkb.evaluation import p2_holdout_scenarios as scenario
from mktkb.evaluation.dataset import cases_to_jsonl
from mktkb.evaluation.p2_dataset import load_p2_dataset, HOLDOUT_ROOT_ENV, HOLDOUT_KEY_FILE_ENV
from mktkb.evaluation.p2_contracts import P2RunPlan
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_p2_holdout_scorecard import _write_sealed, _dry_run_authorization, t09_network_guard

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / 'docs/evaluation/p2-h2-scenarios-v0_2.json'
INGEST = ROOT / 'docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json'
SOURCE_MAP = ROOT / 'docs/evaluation/p2-holdout-v2.source-map.json'
SCHEMA = ROOT / 'docs/evaluation/p2-h2-custody-annotations-v0_2.md'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')


@pytest.fixture
def package(tmp_path, monkeypatch):
    sealed = _write_sealed(tmp_path)
    monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(sealed.root))
    monkeypatch.setenv(HOLDOUT_KEY_FILE_ENV, str(sealed.key_file))
    dataset = load_p2_dataset(sealed.manifest_path, visibility='holdout')
    bindings = dict(manifest_sha256=dataset.manifest.manifest_sha256,
                    dataset_version=dataset.manifest.dataset_version,
                    label_version=dataset.manifest.label_version,
                    cases_sha256=sha(cases_to_jsonl(dataset.cases).encode('utf-8')),
                    source_map_sha256=sha(SOURCE_MAP.read_bytes()),
                    ingest_plan_sha256=sha(INGEST.read_bytes()),
                    schema_sha256=sha(SCHEMA.read_bytes()),
                    scenario_contract_sha256=sha(CONTRACT.read_bytes()))
    priority = json.loads(CONTRACT.read_text(encoding='utf-8'))['assignment_priority']
    rows = []
    for index, case in enumerate(dataset.cases):
        axes = {}
        for name, criterion, reason in [('safety', 'benign_business', 'benign_business'),
                                        ('cross_user', 'owner_context', 'all_user_contexts'),
                                        ('cross_entity', 'structured_target', 'explicit_single_target'),
                                        ('stale_source', 'lifecycle_dates', 'business_date_default')]:
            axes[name] = dict(applicability='not_applicable' if name == 'safety' else 'required',
                              criterion=criterion, reason=reason, target_refs=[], targets=[],
                              as_of=None, temporal_intent='not_applicable' if name == 'safety' else 'current')
        rows.append(dict(case_id=case.case_id, scenario_id=priority[index % 4], axes=axes))
    payload = dict(schema_version='p2-h2-custody/v0.2', bindings=bindings, cases=rows)
    manager = json.loads((ROOT / 'docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/manager-acceptance.json').read_text(encoding='utf-8'))
    manager.update(schema_sha256=bindings['schema_sha256'], scenario_contract_sha256=bindings['scenario_contract_sha256'])
    review_token = Fernet(sealed.key_file.read_bytes().strip()).encrypt(b'synthetic review only')
    review_path = tmp_path / 'review.fernet'
    review_path.write_bytes(review_token)
    manager['review_ciphertext_sha256'] = sha(review_token)
    review = json.loads((ROOT / 'docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/review-aggregate.json').read_text(encoding='utf-8'))
    review.update(bindings=bindings, structure='PASS', semantic_consistency='PASS',
                  independent_review_disagreement_count=0, scenario_disagreement_count=0,
                  annotation_ciphertext_sha256='', review_ciphertext_sha256=sha(review_token))
    review['scenario_counts'] = {name: sum(row['scenario_id'] == name for row in rows) for name in priority + ['unknown']}
    review['axis_counts'] = {name: {state: sum(row['axes'][name]['applicability'] == state for row in rows)
        for state in ('required', 'not_applicable', 'unknown')} for name in rows[0]['axes']}
    corpus_hashes = {'corpus:' + row['path']: sha((ROOT / row['path']).read_bytes())
                     for row in json.loads(INGEST.read_text(encoding='utf-8'))['sources']}
    review.update(input_hashes_before=corpus_hashes, input_hashes_after=corpus_hashes, input_hashes_unchanged=True)
    paths = dict(annotation_path=tmp_path / 'annotations.fernet', key_file=sealed.key_file,
                 manager_path=tmp_path / 'manager.json', review_path=review_path,
                 review_aggregate_path=tmp_path / 'review.json', scenario_path=CONTRACT,
                 ingest_path=INGEST, source_map_path=SOURCE_MAP, schema_path=SCHEMA)

    def write(value=payload):
        token = Fernet(sealed.key_file.read_bytes().strip()).encrypt(encoded(value))
        paths['annotation_path'].write_bytes(token)
        manager['annotation_ciphertext_sha256'] = sha(token)
        review['annotation_ciphertext_sha256'] = sha(token)
        paths['manager_path'].write_bytes(encoded(manager))
        paths['review_aggregate_path'].write_bytes(encoded(review))
    write()
    return dataset, payload, paths, manager, review, write


def test_frozen_complete_subsets_are_disjoint_ordered_and_opaque(package):
    dataset, payload, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    assert 'P2HS' not in repr(contract)
    subsets = [contract.subset(name) for name in contract.scenario_ids]
    assert sum(len(s.cases) for s in subsets) == 30
    assert sum(len(scenario.case_questions(c)) for s in subsets for c in s.cases) == 36
    assert len({c.case_id for s in subsets for c in s.cases}) == 30
    assert all(s.identity['declared_case_count'] == 30 for s in subsets)
    assert all(s.identity['case_count'] < 30 for s in subsets)
    assert 'P2HS' not in repr(subsets[0])
    assert sum(contract.safe_summary()['scenario_counts'].values()) == 30
    assert contract.safe_summary()['quality_readiness'] == 'BLOCKED'


@pytest.mark.parametrize('mutation', ['outer', 'axis', 'enum', 'date', 'refs', 'target',
                                    'binding', 'order', 'duplicate', 'missing', 'scenario'])
def test_corruption_fails_closed_without_ascii_secret(package, mutation):
    dataset, payload, paths, _, _, write = package
    value = copy.deepcopy(payload)
    secret = 'ASCII-PRIVATE-SENTINEL'
    axis = value['cases'][0]['axes']['cross_entity']
    if mutation == 'outer': value[secret] = secret
    elif mutation == 'axis': axis[secret] = secret
    elif mutation == 'enum': axis['criterion'] = secret
    elif mutation == 'date': axis['as_of'] = '2026-02-30'
    elif mutation == 'refs': axis['target_refs'] = [dict(collection='expected_sources', index=999)]
    elif mutation == 'target': axis['targets'] = [dict(entity_type='x', entity_key='y', filters={}, extra=secret)]
    elif mutation == 'binding': value['bindings']['cases_sha256'] = '0' * 64
    elif mutation == 'order': value['cases'].reverse()
    elif mutation == 'duplicate': value['cases'][1] = value['cases'][0]
    elif mutation == 'missing': value['cases'].pop()
    elif mutation == 'scenario': value['cases'][0]['scenario_id'] = 'unknown'
    write(value)
    with pytest.raises(scenario.ScenarioError) as caught:
        scenario.load_scenario_contract(dataset, **paths)
    assert secret not in str(caught.value)
    assert payload['cases'][0]['case_id'] not in str(caught.value)


@pytest.mark.parametrize('mutation', ['cipher', 'review', 'approval', 'schema', 'recipe', 'repo'])
def test_frozen_artifact_and_path_guards(package, mutation):
    dataset, _, paths, manager, _, write = package
    if mutation == 'cipher': paths['annotation_path'].write_bytes(b'bad')
    elif mutation == 'review': paths['review_path'].write_bytes(b'bad')
    elif mutation == 'approval':
        manager['scenario_assignment_frozen'] = False
        write()
    elif mutation == 'schema': paths['schema_path'] = SOURCE_MAP
    elif mutation == 'recipe': paths['scenario_path'] = SOURCE_MAP
    elif mutation == 'repo': paths['annotation_path'] = ROOT / 'do-not-write.fernet'
    with pytest.raises(scenario.ScenarioError):
        scenario.load_scenario_contract(dataset, **paths)


def test_plan_binding_and_source_subsequence_are_enforced(package):
    dataset, _, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    for name in contract.scenario_ids:
        plan = contract.build_plan(name, plan_id='syn-' + name, created_utc='2026-11-12T00:00:00+00:00')
        assert P2RunPlan.from_dict(plan.as_dict()).plan_sha256 == plan.plan_sha256
        assert plan.scenario_binding == contract.binding(name)
        ingest = contract.ingest_plan(name)
        contract.validate_run(plan, contract.subset(name), ingest)
        other = contract.scenario_ids[(contract.scenario_ids.index(name) + 1) % 4]
        with pytest.raises(scenario.ScenarioError):
            contract.validate_run(plan, contract.subset(other), ingest)
        with pytest.raises(scenario.ScenarioError):
            contract.validate_run(plan, contract.subset(name), contract.ingest_plan(other))


def test_default_plan_serialization_unchanged():
    from mktkb.evaluation.p2_holdout_plan import build_holdout_plan
    plan = build_holdout_plan(cases=[('syn-default', 1)], ingest_batches=1, plan_id='syn-default',
                              plan_version='v0.1', created_utc='2026-11-12T00:00:00+00:00')
    assert 'scenario_binding' not in plan.as_dict()
    assert P2RunPlan.from_dict(plan.as_dict()).as_dict() == plan.as_dict()


def test_direct_api_cannot_drop_contract(package, tmp_path):
    from mktkb.evaluation.product_adapter import ProductEvalAdapter
    from mktkb.evaluation.p2_live import run_live_p2
    dataset, _, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    name = contract.scenario_ids[0]
    plan = contract.build_plan(name, plan_id='syn-api', created_utc='2026-11-12T00:00:00+00:00')
    with pytest.raises(scenario.ScenarioError, match='scenario_contract_required'):
        ProductEvalAdapter(tmp_path / 'adapter', dataset=contract.subset(name), ingest_plan=contract.ingest_plan(name))
    with pytest.raises(scenario.ScenarioError, match='scenario_contract_required'):
        asyncio.run(run_live_p2(plan, run_id='syn-live', out_dir=tmp_path / 'live',
                               dataset=contract.subset(name), ingest_plan=contract.ingest_plan(name)))


def _run_parts(contract):
    from mktkb.evaluation.p2_scoring import P2HoldoutCaseScore, aggregate_holdout
    parts = []
    for name in contract.scenario_ids:
        subset = contract.subset(name)
        plan = contract.build_plan(name, plan_id='syn-' + name, created_utc='2026-11-12T00:00:00+00:00')
        card = aggregate_holdout([P2HoldoutCaseScore(c.case_id, c.stratum, 'pass') for c in subset.cases],
                                 expected_strata=subset.identity['strata'], run_id='syn-run-' + name,
                                 config_hash='a' * 64).to_dict()
        from mktkb.evaluation.p2_diagnostics import HoldoutDiagnostics, validate_scorecard
        from types import SimpleNamespace
        diagnostics = HoldoutDiagnostics()
        for case in subset.cases:
            diagnostics.record(case, {}, SimpleNamespace(outcome=SimpleNamespace(kind='answer'),
                score=SimpleNamespace(checks=(), issues=())), status='pass')
        card['diagnostics'] = diagnostics.to_dict()
        card['blocks'].append(dict(code='holdout_hard_failure_unverified', severity='unknown',
            detail='四类硬失败缺少受控分类证据，零计数不证明安全', evidence={'owner': 'sealed_reviewer'}))
        validate_scorecard(card, total=len(subset.cases), run_id=card['run_id'], config_hash='a' * 64)
        parts.append(dict(plan=plan, aggregate=card, status='succeeded', run_id='syn-run-' + name,
                          turns_executed=subset.identity['turn_stats']['total_turns'],
                          binding=dict(scenario_binding=contract.binding(name), pipeline_version='syn-pipeline',
                                       provider={'chat': 'mock'}, gate_config_hash='b' * 64,
                                       config_hash='a' * 64)))
    return parts


def test_composition_recomputes_only_subset_quantity_blocks(package):
    dataset, _, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    parts = _run_parts(contract)
    combined = scenario.compose_scenario_runs(contract, parts)
    assert combined['total'] == combined['passed'] == 30
    assert combined['turns_executed'] == 36
    codes = {b['code'] for b in combined['blocks']}
    assert 'holdout_sample_missing' not in codes
    assert 'holdout_below_threshold' not in codes
    assert 'holdout_threshold_unapproved' in codes
    assert 'holdout_hard_failure_unverified' in codes
    assert combined['release_ready'] is False
    assert 'P2HS' not in json.dumps(combined)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'subset', 'pipeline', 'config', 'binding', 'later_started', 'bad_counts'])
def test_composition_rejects_untrusted_runs(package, mutation):
    dataset, _, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    parts = _run_parts(contract)
    if mutation == 'missing': parts.pop()
    elif mutation == 'duplicate': parts[-1] = parts[0]
    elif mutation == 'subset': parts[-1]['binding']['scenario_binding'] = parts[0]['binding']['scenario_binding']
    elif mutation == 'pipeline': parts[-1]['binding']['pipeline_version'] = 'different'
    elif mutation == 'config': parts[-1]['binding']['gate_config_hash'] = 'c' * 64
    elif mutation == 'binding': parts[0]['aggregate']['run_id'] = 'different'
    elif mutation == 'later_started': parts[0]['status'] = 'aborted'
    elif mutation == 'bad_counts': parts[0]['aggregate']['passed'] += 1
    with pytest.raises(scenario.ScenarioError): scenario.compose_scenario_runs(contract, parts)


def test_composition_preserves_error_and_not_started(package):
    dataset, _, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    parts = _run_parts(contract)
    parts[0]['status'] = 'aborted'
    for part in parts[1:]:
        part.update(status='not_started', aggregate=None, turns_executed=0, binding=None)
    combined = scenario.compose_scenario_runs(contract, parts)
    assert combined['status'] == 'partial'
    assert combined['errors'] == 30 - len(contract.subset(contract.scenario_ids[0]).cases)
    assert combined['not_started'] == 3
    assert combined['release_ready'] is False


def test_cli_requires_complete_scenario_parameters(package, tmp_path, capsys):
    from mktkb.evaluation.cli import main
    dataset, _, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    plan = contract.build_plan(contract.scenario_ids[0], plan_id='syn-cli', created_utc='2026-11-12T00:00:00+00:00')
    plan_path = tmp_path / 'plan.json'
    plan_path.write_text(json.dumps(plan.as_dict()), encoding='utf-8')
    code = main(['p2-run', '--plan', str(plan_path), '--out', str(tmp_path / 'out')])
    assert code != 0
    captured = capsys.readouterr()
    assert 'scenario' in captured.out + captured.err


@pytest.mark.usefixtures('t09_network_guard')
@pytest.mark.parametrize('abort_first', [False, True])
def test_cli_batch_real_product_states_and_stop(package, tmp_path, capsys, monkeypatch, abort_first):
    from mktkb.evaluation import cli
    from mktkb.evaluation.product_adapter import ProductEvalAdapter
    from mktkb.evaluation.p2_scoring import load_p2_gate_config
    from test_p2_holdout_scorecard import _snapshot
    dataset, payload, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    observed = []
    original = ProductEvalAdapter.ingest

    async def inspect(self, *args, **kwargs):
        if abort_first:
            raise RuntimeError('SYNTHETIC-FIRST-INGEST-FAILURE')
        import math
        sizes = []
        embed = self._embedder.embed
        def record(texts, *, purpose='document'):
            if purpose == 'document': sizes.append(len(texts))
            return embed(texts, purpose=purpose)
        self._embedder.embed = record
        result = await original(self, *args, **kwargs)
        self._qa.ensure_ready()
        from mktkb.documents.models import Document, DocumentVersion
        with self.app.state.db.session() as session:
            docs = session.query(Document).all()
            active = {d.name: session.get(DocumentVersion, d.active_version_id).number for d in docs}
        observed.append((self.dataset.identity['scenario_binding']['scenario_id'], active, len(self.ingest_receipts),
                         sum(math.ceil(n / 5) for n in sizes)))
        return result
    monkeypatch.setattr(ProductEvalAdapter, 'ingest', inspect)
    plans = []
    for name in contract.scenario_ids:
        plan = contract.build_plan(name, plan_id='syn-batch-' + name, created_utc='2026-11-12T00:00:00+00:00')
        target = tmp_path / (name + '.json')
        target.write_text(json.dumps(plan.as_dict()), encoding='utf-8')
        plans.extend(['--plan', str(target)])
    snapshot = tmp_path / 'snapshot.json'
    snapshot.write_text(json.dumps(_snapshot(plan).as_dict()), encoding='utf-8')
    out = tmp_path / 'batch'
    args = ['p2-h2-scenarios-run', '--out', str(out), '--holdout-manifest', str(Path(paths['annotation_path']).parent / 'sealed/manifest.json'),
            '--snapshot', str(snapshot), '--ingest-plan', str(INGEST),
            '--scenario-annotations', str(paths['annotation_path']), '--scenario-review', str(paths['review_path']),
            '--scenario-key-file', str(paths['key_file']), '--scenario-manager', str(paths['manager_path']),
            '--scenario-review-aggregate', str(paths['review_aggregate_path']), *plans]
    code = cli.main(args)
    captured = capsys.readouterr()
    assert code == (3 if abort_first else 0), captured.out + captured.err
    result = json.loads((out / 'scenario_composition.json').read_text(encoding='utf-8'))
    assert result['real_calls'] == 0 and result['release_ready'] is False
    if abort_first:
        assert result['status'] == 'partial' and result['not_started'] == 3
        assert len(list(out.rglob('run_manifest.json'))) == 1
        assert not observed
    else:
        assert result['status'] == 'complete' and result['turns_executed'] == 36
        assert len(observed) == 4
        for i, (name, active, receipts, batches) in enumerate(observed):
            assert active['D01_物品位置表.xlsx'] == (2, 2, 3, 4)[i]
            assert active['D02_合作店家信息.xlsx'] == (1, 1, 2, 2)[i]
            assert any(k.startswith('V01_') for k in active) == (i in (1, 2))
            assert any(k.startswith('V07_') for k in active) == (i == 3)
            assert receipts == len(contract.ingest_plan(name).sources)
            assert batches == (8, 9, 11, 13)[i]
        summaries = {json.loads(p.read_text(encoding='utf-8'))['binding']['scenario_binding']['scenario_id']:
                     json.loads(p.read_text(encoding='utf-8')) for p in out.rglob('summary.json')}
        for i, name in enumerate(contract.scenario_ids):
            summary = summaries[name]
            assert summary['network']['outbound_attempts'] == 0
    safe_text = captured.out + captured.err
    for path in out.rglob('*'):
        if path.is_file() and path.suffix in ('.json', '.jsonl', '.md'):
            safe_text += path.read_text(encoding='utf-8')
    for case in dataset.cases:
        assert case.case_id not in safe_text
        assert case.reference_answer not in safe_text if case.reference_answer else True
        for question in scenario.case_questions(case): assert question not in safe_text


def test_scenario_mapping_knows_excluded_history_but_requires_positive_sources(package):
    from dataclasses import replace
    from mktkb.evaluation.p2_runner import _holdout_score_marks, P2RunLedger
    dataset, _, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    subset = contract.subset('base_b0')
    one = replace(subset.cases[0], relevant_units=({'doc_code': 'V01', 'locator': {'page': 1}},),
                  forbidden_sources=({'doc_code': 'V07', 'locator': {'page': 1}},))
    subset = replace(subset, cases=(one,), identity={**dict(subset.identity), 'case_count': 1})
    ledger = P2RunLedger(run_id='syn-mapping', plan_id='syn', plan_sha256='a' * 64,
                         execution='dry_run', production_ready=False, requests_planned=1)
    blocks = []
    _holdout_score_marks(ledger, subset, ingest_plan=contract.ingest_plan('base_b0'), execution='dry_run', blocks=blocks)
    assert 'holdout_document_code_unmapped' not in {b.code for b in blocks}
    one = replace(one, expected_sources=({'doc_code': 'V01', 'locator': {'page': 1}},))
    subset = replace(subset, cases=(one,))
    blocks = []
    _holdout_score_marks(ledger, subset, ingest_plan=contract.ingest_plan('base_b0'), execution='dry_run', blocks=blocks)
    assert 'holdout_document_code_unmapped' in {b.code for b in blocks}


def test_scenario_output_must_stay_outside_workspace(package):
    from mktkb.evaluation.product_adapter import ProductEvalAdapter
    dataset, _, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    name = contract.scenario_ids[0]
    with pytest.raises(scenario.ScenarioError, match='scenario_private_path_inside_workspace'):
        ProductEvalAdapter(ROOT / 'do-not-create', dataset=contract.subset(name),
                           ingest_plan=contract.ingest_plan(name), scenario_contract=contract)
    assert not (ROOT / 'do-not-create').exists()


@pytest.mark.parametrize('mutation', ['nested_enum', 'dataset_after_load', 'corpus_hash'])
def test_malformed_or_mutated_inputs_stay_fixed_code(package, mutation):
    dataset, payload, paths, _, review, write = package
    if mutation == 'nested_enum':
        payload['cases'][0]['axes']['safety']['criterion'] = {'ASCII-PRIVATE-SENTINEL': 1}
        write()
        with pytest.raises(scenario.ScenarioError): scenario.load_scenario_contract(dataset, **paths)
    elif mutation == 'corpus_hash':
        review['input_hashes_before'] = {k: '0' * 64 for k in review['input_hashes_before']}
        write()
        with pytest.raises(scenario.ScenarioError): scenario.load_scenario_contract(dataset, **paths)
    else:
        contract = scenario.load_scenario_contract(dataset, **paths)
        dataset.cases[0].expected_sources[0]['doc_code'] = 'MUTATED'
        with pytest.raises(scenario.ScenarioError): contract.subset(contract.scenario_ids[0])


@pytest.mark.parametrize('mutation', ['no_diagnostics', 'execution_mode', 'unknown_pass', 'stratum', 'missing_block'])
def test_composition_requires_full_safe_card(package, mutation):
    dataset, _, paths, _, _, _ = package
    contract = scenario.load_scenario_contract(dataset, **paths)
    parts = _run_parts(contract)
    card = parts[0]['aggregate']
    if mutation == 'no_diagnostics': card.pop('diagnostics')
    elif mutation == 'execution_mode': card['execution_mode'] = 'ASCII-PRIVATE-SENTINEL'
    elif mutation == 'missing_block': card['blocks'] = [b for b in card['blocks'] if b['code'] != 'holdout_hard_failure_unverified']
    elif mutation == 'stratum':
        buckets = list(card['by_stratum'])
        card['by_stratum'][buckets[0]], card['by_stratum'][buckets[-1]] = card['by_stratum'][buckets[-1]], card['by_stratum'][buckets[0]]
    else:
        d = card['diagnostics']
        n = d['counts']['observed']
        d['counts'].update(observed=0, unknown_kind=n)
        for counts in d['by_stratum'].values(): counts.update(unknown_kind=counts['observed'], observed=0)
        for values in d['kind_matrix'].values(): values['kind_unknown'], values['kind_answer'] = values['kind_answer'], 0
        r = d['refusal_confusion']
        r.update(unknown=r['tn'] + r['fn'], tn=0, fn=0)
    with pytest.raises(scenario.ScenarioError) as caught:
        scenario.compose_scenario_runs(contract, parts)
    assert 'ASCII-PRIVATE-SENTINEL' not in str(caught.value)


@pytest.mark.parametrize('mutation', ['manager_extra', 'review_extra', 'bool_count', 'scope', 'gap_count',
                                    'review_nested_bool', 'review_nested_extra', 'review_assignment'])
def test_public_metadata_fails_closed(package, mutation):
    dataset, _, paths, manager, review, write = package
    if mutation == 'manager_extra': manager['ASCII-PRIVATE-SENTINEL'] = 1
    elif mutation == 'review_extra': review['ASCII-PRIVATE-SENTINEL'] = 1
    elif mutation == 'bool_count': manager['scenario_unknown'] = False
    elif mutation == 'scope': manager['accepted_scope'] = None
    elif mutation == 'gap_count': manager['unresolved_entity_targets'] = 'ASCII-PRIVATE-SENTINEL'
    elif mutation == 'review_nested_bool': review['scenario_counts']['unknown'] = False
    elif mutation == 'review_nested_extra': review['axis_counts']['safety']['ASCII-PRIVATE-SENTINEL'] = 0
    else: review['scenario_counts']['base_b0'] -= 1
    write()
    with pytest.raises(scenario.ScenarioError) as caught:
        scenario.load_scenario_contract(dataset, **paths)
    assert 'ASCII-PRIVATE-SENTINEL' not in str(caught.value)
