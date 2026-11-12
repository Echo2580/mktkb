"""Independent negative probes, freshly synthetic; never load real custody."""
import copy
import json
import sys
from pathlib import Path
from dataclasses import replace

import pytest

sys.path.insert(0, str(Path.cwd() / 'backend/tests/evaluation'))
from test_p2_holdout_scenarios import package, _run_parts
from mktkb.evaluation import p2_holdout_scenarios as s
from mktkb.evaluation.p2_contracts import P2RunPlan


@pytest.mark.parametrize('field', sorted(s.BINDING_KEYS))
def test_each_binding_field_tamper_rejected_before_adapter(package, field):
    dataset, _, paths, _, _, _ = package
    contract = s.load_scenario_contract(dataset, **paths)
    name = contract.scenario_ids[0]
    plan = contract.build_plan(name, plan_id='independent-binding', created_utc='2026-11-12T00:00:00Z')
    raw = plan.as_dict()
    raw['scenario_binding'][field] = contract.scenario_ids[1] if field == 'scenario_id' else 'f' * 64
    changed = P2RunPlan.from_dict(raw)
    with pytest.raises(s.ScenarioError):
        s.validate_scenario_execution(changed, contract.subset(name), contract.ingest_plan(name), contract)


@pytest.mark.parametrize('mutation', ['bool_ref', 'negative_ref', 'duplicate_ref', 'nested_filter', 'duplicate_json'])
def test_independent_malformed_annotation_fixed_failure(package, mutation):
    dataset, payload, paths, manager, review, write = package
    value = copy.deepcopy(payload)
    axis = value['cases'][0]['axes']['cross_entity']
    if mutation == 'bool_ref': axis['target_refs'] = [dict(collection='expected_sources', index=True)]
    elif mutation == 'negative_ref': axis['target_refs'] = [dict(collection='expected_sources', index=-1)]
    elif mutation == 'duplicate_ref': axis['target_refs'] = [dict(collection='expected_sources', index=0)] * 2
    elif mutation == 'nested_filter': axis['targets'] = [dict(entity_type='synthetic', entity_key='synthetic', filters={'x': {'PRIVATE-ASCII-PROBE': 1}})]
    write(value)
    if mutation == 'duplicate_json':
        from cryptography.fernet import Fernet
        import hashlib
        raw = json.dumps(value).replace('"schema_version":', '"schema_version":"PRIVATE-ASCII-PROBE","schema_version":', 1).encode()
        token = Fernet(paths['key_file'].read_bytes().strip()).encrypt(raw)
        paths['annotation_path'].write_bytes(token)
        for doc in (manager, review): doc['annotation_ciphertext_sha256'] = hashlib.sha256(token).hexdigest()
        paths['manager_path'].write_text(json.dumps(manager), encoding='utf-8')
        paths['review_aggregate_path'].write_text(json.dumps(review), encoding='utf-8')
    with pytest.raises(s.ScenarioError) as caught: s.load_scenario_contract(dataset, **paths)
    assert 'PRIVATE-ASCII-PROBE' not in str(caught.value)
    assert dataset.cases[0].case_id not in str(caught.value)


@pytest.mark.parametrize('mutation', ['diagnostics_absent', 'nested_ascii', 'unknown_pass', 'unverified_absent', 'free_error'])
def test_full_card_boundary_cannot_be_bypassed(package, mutation):
    dataset, _, paths, _, _, _ = package
    contract = s.load_scenario_contract(dataset, **paths)
    parts = _run_parts(contract)
    card = parts[0]['aggregate']
    if mutation == 'diagnostics_absent': del card['diagnostics']
    elif mutation == 'nested_ascii': card['diagnostics']['source']['PRIVATE-ASCII-PROBE'] = 1
    elif mutation == 'free_error': card['blocks'][0]['evidence']['PRIVATE-ASCII-PROBE'] = 'PRIVATE-ASCII-PROBE'
    elif mutation == 'unverified_absent': card['blocks'] = [b for b in card['blocks'] if b['code'] != 'holdout_hard_failure_unverified']
    else:
        d = card['diagnostics']
        d['counts']['unknown_kind'], d['counts']['observed'] = d['counts']['observed'], 0
        for bucket in d['by_stratum'].values(): bucket['unknown_kind'], bucket['observed'] = bucket['observed'], 0
        for row in d['kind_matrix'].values(): row['kind_unknown'], row['kind_answer'] = row['kind_answer'], 0
        r = d['refusal_confusion']; r.update(unknown=r['tn'] + r['fn'], tn=0, fn=0)
    with pytest.raises(s.ScenarioError) as caught: s.compose_scenario_runs(contract, parts)
    assert str(caught.value) == 'scenario_scorecard_invalid'


@pytest.mark.parametrize('mutation', ['provider', 'gate', 'plan_swap', 'run_duplicate', 'subset_swap'])
def test_composition_cross_identity_rejected(package, mutation):
    dataset, _, paths, _, _, _ = package
    contract = s.load_scenario_contract(dataset, **paths)
    parts = _run_parts(contract)
    if mutation == 'provider': parts[3]['binding']['provider'] = {'chat': 'different'}
    elif mutation == 'gate': parts[3]['binding']['gate_config_hash'] = 'c' * 64
    elif mutation == 'plan_swap': parts[3]['plan'] = parts[2]['plan']
    elif mutation == 'run_duplicate': parts[3]['run_id'] = parts[2]['run_id']
    else: parts[3]['binding']['scenario_binding']['subset_sha256'] = parts[2]['binding']['scenario_binding']['subset_sha256']
    with pytest.raises(s.ScenarioError): s.compose_scenario_runs(contract, parts)


def test_cli_plan_and_score_binding_mismatch(package, tmp_path, capsys):
    from mktkb.evaluation import cli
    dataset, _, paths, _, _, _ = package
    contract = s.load_scenario_contract(dataset, **paths)
    name = contract.scenario_ids[0]
    private_args = ['--scenario-id', name, '--scenario-annotations', str(paths['annotation_path']),
        '--scenario-review', str(paths['review_path']), '--scenario-key-file', str(paths['key_file']),
        '--scenario-manager', str(paths['manager_path']), '--scenario-review-aggregate', str(paths['review_aggregate_path'])]
    manifest = Path(paths['annotation_path']).parent / 'sealed/manifest.json'
    plan_path = tmp_path / 'generated.json'
    assert cli.main(['p2-h2-plan', '--holdout-manifest', str(manifest), '--plan-out', str(plan_path), *private_args]) == 0
    plan = P2RunPlan.from_dict(json.loads(plan_path.read_text(encoding='utf-8')))
    contract.validate_run(plan, contract.subset(name), contract.ingest_plan(name))
    run = tmp_path / 'fake-run'; run.mkdir()
    (run / 'run_manifest.json').write_text(json.dumps({'binding': {'scenario_binding': contract.binding(name)}, 'plan': {'plan_sha256': '0' * 64}}), encoding='utf-8')
    verdicts = tmp_path / 'unused.jsonl'; verdicts.write_text('', encoding='utf-8')
    assert cli.main(['p2-score', '--run-dir', str(run), '--visibility', 'holdout', '--holdout-manifest', str(manifest), '--verdicts', str(verdicts), '--plan', str(plan_path), *private_args]) == 3
    captured = capsys.readouterr()
    assert 'scenario_run_binding_mismatch' in captured.err
    assert all(c.case_id not in captured.out + captured.err for c in dataset.cases)


def test_batch_first_service_error_stops_later_scenarios(package, tmp_path, monkeypatch):
    import asyncio
    from test_p2_holdout_scorecard import _snapshot, _product_turn
    from mktkb.evaluation.product_adapter import ProductEvalAdapter
    from mktkb.evaluation.p2_scoring import load_p2_gate_config
    dataset, _, paths, _, _, _ = package
    contract = s.load_scenario_contract(dataset, **paths)
    calls = []
    async def fail(self, question, **kwargs):
        calls.append(self.dataset.identity['scenario_binding']['scenario_id'])
        return replace(_product_turn(question), kind='service_error', error_code='MODEL_OUTPUT_INVALID', model_failure_reason='record_facts')
    monkeypatch.setattr(ProductEvalAdapter, 'ask_turn', fail)
    plans = [contract.build_plan(n, plan_id='independent-' + n, created_utc='2026-11-12T00:00:00Z') for n in contract.scenario_ids]
    out = tmp_path / 'service-stop'
    result = asyncio.run(s.run_scenario_batch(contract, plans, out_dir=out, snapshot=_snapshot(plans[0]), gate_config=load_p2_gate_config()))
    assert calls == [contract.scenario_ids[0]]
    assert result['status'] == 'partial' and result['not_started'] == 3
    assert result['errors'] == 30 and result['passed'] == 0 and result['release_ready'] is False
    assert len(list(out.rglob('run_manifest.json'))) == 1
    assert result['real_calls'] == 0
    raw = ''.join(p.read_text(encoding='utf-8') for p in out.rglob('*') if p.is_file() and p.suffix in ('.json', '.jsonl', '.md'))
    assert all(c.case_id not in raw for c in dataset.cases)
