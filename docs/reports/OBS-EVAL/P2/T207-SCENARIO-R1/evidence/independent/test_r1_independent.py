"""Independent synthetic probes. No real holdout, annotations or keys are read."""
import ast
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / 'backend/tests/evaluation'))
from test_p2_holdout_scenarios import package, _run_parts
from mktkb.evaluation import p2_holdout_scenarios as scenario


def empty_target():
    return dict(entity_type='INDEPENDENT-SYNTHETIC-TYPE', entity_key='', filters={})


def test_empty_keys_all_axes_preserve_labels_unknown_and_full_blocks(package):
    dataset, payload, paths, _, review, write = package
    for row in payload['cases']:
        for axis in row['axes'].values():
            axis['targets'] = [dict(empty_target(), entity_key='INDEPENDENT-PLACEHOLDER')]
    for row in payload['cases'][:2]:
        row['axes']['cross_entity'].update(applicability='unknown', criterion='unknown', reason='unresolved_target')
    review['axis_counts']['cross_entity'] = dict(required=28, not_applicable=0, unknown=2)
    review['axis_unknown_total'] = 2
    write()
    old_summary = scenario.load_scenario_contract(dataset, **paths).safe_summary()
    labels = scenario.cases_to_jsonl(dataset.cases)
    expected = copy.deepcopy(payload)
    for row in payload['cases']:
        for axis in row['axes'].values():
            axis['targets'][0]['entity_key'] = ''
    write()
    contract = scenario.load_scenario_contract(dataset, **paths)
    assert contract.safe_summary() == old_summary
    assert scenario.cases_to_jsonl(dataset.cases) == labels
    for row, prior in zip(payload['cases'], expected['cases']):
        for name, axis in row['axes'].items():
            assert {k: v for k, v in axis.items() if k != 'targets'} == {k: v for k, v in prior['axes'][name].items() if k != 'targets'}
            assert axis['targets'] == [empty_target()]
    summary = contract.safe_summary()
    assert summary['axis_counts']['cross_entity'] == dict(required=28, unknown=2)
    assert summary['fixed_gap_counts'] == dict(unresolved_entity_target=2, unresolved_date_anchor=2)
    assert summary['quality_readiness'] == 'BLOCKED'
    assert summary['runtime_axis_evidence_produced'] is summary['release_ready'] is False
    combined = scenario.compose_scenario_runs(contract, _run_parts(contract))
    assert combined['annotation'] == summary and combined['release_ready'] is False
    assert any(b['code'] == 'holdout_hard_failure_unverified' for b in combined['blocks'])
    assert 'INDEPENDENT' not in json.dumps(combined)


def test_old_condition_reproduces_fixed_failure_in_memory(package, monkeypatch):
    dataset, payload, paths, _, _, write = package
    payload['cases'][0]['axes']['cross_entity']['targets'] = [empty_target()]
    write()
    scenario.load_scenario_contract(dataset, **paths)
    before = Path(__file__).parents[1] / 'p2_holdout_scenarios.before.py'
    tree = ast.parse(before.read_text(encoding='utf-8'))
    old_axis = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_axis')
    namespace = dict(scenario.__dict__)
    exec(compile(ast.Module(body=[old_axis], type_ignores=[]), '<synthetic-old-axis>', 'exec'), namespace)
    monkeypatch.setattr(scenario, '_axis', namespace['_axis'])
    with pytest.raises(scenario.ScenarioError) as caught:
        scenario.load_scenario_contract(dataset, **paths)
    assert str(caught.value) == 'scenario_targets_invalid'


@pytest.mark.parametrize('field,value', [
    ('entity_key', None), ('entity_key', []), ('entity_key', {}),
    ('entity_key', True), ('entity_key', False), ('entity_key', 0),
    ('entity_key', 1.0), ('entity_key', '汉' * 257),
    ('entity_type', ''), ('entity_type', None), ('entity_type', []),
    ('entity_type', {}), ('entity_type', False), ('entity_type', 0),
    ('entity_type', 1.0), ('entity_type', '汉' * 257),
    ('filters', None), ('filters', []), ('filters', True),
    ('filters', {'nested': {'INDEPENDENT-SECRET': 1}}),
    ('filters', {'nested': ['INDEPENDENT-SECRET']}),
    ('filters', {'': 'INDEPENDENT-SECRET'}),
    ('filters', {'x' * 257: 'INDEPENDENT-SECRET'}),
])
def test_invalid_syntax_remains_fixed_error(package, field, value):
    dataset, payload, paths, _, _, write = package
    target = empty_target()
    target[field] = value
    payload['cases'][0]['axes']['cross_entity']['targets'] = [target]
    write()
    with pytest.raises(scenario.ScenarioError) as caught:
        scenario.load_scenario_contract(dataset, **paths)
    assert str(caught.value) == 'scenario_targets_invalid'


@pytest.mark.parametrize('mutation,code', [
    ('extra_target', 'scenario_structure_invalid'), ('missing_target', 'scenario_structure_invalid'),
    ('extra_axis', 'scenario_structure_invalid'), ('ref_bool', 'scenario_refs_invalid'),
    ('ref_negative', 'scenario_refs_invalid'), ('ref_duplicate', 'scenario_refs_invalid'),
    ('bad_date', 'scenario_date_invalid'),
])
def test_empty_key_never_bypasses_surrounding_checks(package, mutation, code):
    dataset, payload, paths, _, _, write = package
    axis = payload['cases'][0]['axes']['cross_entity']
    axis['targets'] = [empty_target()]
    if mutation == 'extra_target': axis['targets'][0]['INDEPENDENT-SECRET'] = 'SECRET'
    elif mutation == 'missing_target': del axis['targets'][0]['filters']
    elif mutation == 'extra_axis': axis['INDEPENDENT-SECRET'] = 'SECRET'
    elif mutation == 'ref_bool': axis['target_refs'] = [dict(collection='expected_sources', index=False)]
    elif mutation == 'ref_negative': axis['target_refs'] = [dict(collection='expected_sources', index=-1)]
    elif mutation == 'ref_duplicate': axis['target_refs'] = [dict(collection='expected_sources', index=0)] * 2
    else: axis['as_of'] = '2026-02-30'
    write()
    with pytest.raises(scenario.ScenarioError) as caught:
        scenario.load_scenario_contract(dataset, **paths)
    assert str(caught.value) == code


def test_unicode_256_and_scalar_filters_still_valid(package):
    dataset, payload, paths, _, _, write = package
    payload['cases'][0]['axes']['cross_entity']['targets'] = [dict(
        entity_type='类' * 256, entity_key='键' * 256,
        filters=dict(a=None, b=True, c=12, d=1.25, e='synthetic'))]
    write()
    assert scenario.load_scenario_contract(dataset, **paths).safe_summary()['release_ready'] is False


def test_changed_corpus_bytes_rejected_before_decrypt(package, monkeypatch):
    dataset, payload, paths, _, _, write = package
    payload['cases'][0]['axes']['cross_entity']['targets'] = [empty_target()]
    write()
    original = scenario._read
    def mutated(path, *, private=False):
        if Path(path).is_relative_to(scenario.ROOT / 'fixtures/acceptance'):
            return original(path, private=private) + b'INDEPENDENT-SYNTHETIC-CHANGE'
        assert not private, 'must reject changed public corpus before private inputs'
        return original(path, private=private)
    monkeypatch.setattr(scenario, '_read', mutated)
    with pytest.raises(scenario.ScenarioError) as caught:
        scenario.load_scenario_contract(dataset, **paths)
    assert str(caught.value) == 'scenario_corpus_binding_invalid'


def test_dataset_mutation_rejected_after_empty_key_load(package):
    dataset, payload, paths, _, _, write = package
    payload['cases'][0]['axes']['cross_entity']['targets'] = [empty_target()]
    write()
    contract = scenario.load_scenario_contract(dataset, **paths)
    dataset.cases[0].expected_sources[0]['doc_code'] = 'INDEPENDENT-SYNTHETIC-CHANGE'
    with pytest.raises(scenario.ScenarioError) as caught:
        contract.subset(contract.scenario_ids[0])
    assert str(caught.value) == 'scenario_dataset_changed'


@pytest.mark.parametrize('abort_first', [False, True])
def test_empty_key_cli_mock_executes_or_stops_with_unknown_preserved(package, tmp_path, capsys, monkeypatch, abort_first):
    import test_p2_holdout_scenarios as original
    _, payload, _, _, review, write = package
    for row in payload['cases'][:2]:
        row['axes']['cross_entity'].update(applicability='unknown', criterion='unknown', reason='unresolved_target', targets=[empty_target()])
    review['axis_counts']['cross_entity'] = dict(required=28, not_applicable=0, unknown=2)
    review['axis_unknown_total'] = 2
    write()
    original.test_cli_batch_real_product_states_and_stop(package, tmp_path, capsys, monkeypatch, abort_first)
    composition = json.loads((tmp_path / 'batch/scenario_composition.json').read_text(encoding='utf-8'))
    summary = composition['annotation']
    assert summary['axis_counts']['cross_entity'] == dict(required=28, unknown=2)
    assert summary['quality_readiness'] == 'BLOCKED'
    assert summary['runtime_axis_evidence_produced'] is False
