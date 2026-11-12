"""Controlled, immutable H2 scenario assignments. No private material is logged.

Only load_scenario_contract decrypts the annotation, in memory. Approval freezes
assignment for wiring; it does not attest runtime axes or authorize live calls.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .dataset import cases_to_jsonl
from .p2_contracts import P2RunPlan, payload_sha256
from .p2_dataset import P2Dataset
from .product_adapter import P2RunDataset, P2IngestPlan, case_questions, ingest_plan_from_document

ROOT = Path(__file__).resolve().parents[4]
EVALUATION = ROOT / 'docs/evaluation'
PUBLIC_CUSTODY = ROOT / 'docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2'
DEFAULT_INGEST = ROOT / 'docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json'
RECIPES = (
    ('base_b0', (0, 1, 4, 6, 7, 8, 9), 8),
    ('base_b0_plus_v01', (0, 1, 4, 6, 7, 8, 9, 10), 9),
    ('pre_v05_without_v07', (0, 1, 2, 4, 5, 6, 7, 8, 9, 10), 11),
    ('post_v05_without_v01', (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11), 13),
)
AXIS_CRITERIA = {
    'safety': {'must_refuse_security', 'forbidden_content', 'benign_business', 'unknown'},
    'cross_user': {'owner_context', 'unknown'},
    'cross_entity': {'structured_target', 'multi_target', 'shared_background', 'no_entity_claim', 'unknown'},
    'stale_source': {'lifecycle_dates', 'unknown'},
}
REASONS = frozenset('explicit_security explicit_privacy prompt_injection explicit_forbidden benign_business all_user_contexts explicit_single_target explicit_multi_target shared_policy no_entity_scope published_lifecycle explicit_temporal business_date_default ambiguous_semantics unresolved_target source_state_conflict third_state_required insufficient_annotation'.split())
AXIS_KEYS = frozenset(('applicability', 'criterion', 'reason', 'target_refs', 'targets', 'as_of', 'temporal_intent'))
BINDING_KEYS = frozenset(('scenario_id', 'assignment_sha256', 'custody_sha256', 'review_sha256',
                          'scenario_contract_sha256', 'ingest_plan_sha256', 'scenario_ingest_sha256',
                          'subset_sha256', 'full_cases_sha256', 'manifest_sha256', 'schema_sha256', 'source_map_sha256'))
_PROOF = object()
MANAGER_KEYS = frozenset('schema_version date accepted_scope independent_review_verdict independent_structure independent_semantic_consistency independent_quality_readiness scenario_assignment_frozen full_annotation_quality_ready live_execution_authorized_by_this_record quality_released annotation_ciphertext_sha256 review_ciphertext_sha256 schema_sha256 scenario_contract_sha256 case_count scenario_unknown independent_disagreements unresolved_entity_targets unresolved_date_anchors runtime_axis_evidence_produced new_real_calls'.split())
REVIEW_KEYS = frozenset('schema_version verdict status structure semantic_consistency quality_readiness annotation_frozen quality_released annotation_schema_version annotation_ciphertext_sha256 review_ciphertext_path review_ciphertext_sha256 bindings case_count unique_case_count same_order_coverage coverage_missing_count coverage_extra_count coverage_duplicate_count scenario_counts axis_counts fixed_gap_counts axis_unknown_total date_anchor_gap_total independent_review_disagreement_count scenario_disagreement_count axis_disagreement_count old_disagreement_candidate_count old_disagreement_rejudged_count old_disagreement_corrected_count checks input_hashes_before input_hashes_after input_hashes_unchanged old_ciphertexts_preserved runtime_axis_evidence_produced runtime_owner_context_verification runtime_entity_date_snapshot_verification runtime_global_forbidden_value_source_checks business_date_annotation_is_actual_product_date_proof outbound_socket_blocking_enabled network_measurement_scope network_attempt_count product_test_count real_call_count subagent_count commit_count process_deviations authorization_evidence'.split())


class ScenarioError(ValueError):
    """Fixed codes only: neither external field names nor values enter errors."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise ScenarioError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _cases_sha(cases: Any) -> str:
    return _sha(cases_to_jsonl(cases).encode('utf-8'))


def _exact(value: Any, keys: Any) -> None:
    _require(isinstance(value, dict) and set(value) == set(keys), 'scenario_structure_invalid')


def _json(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'scenario_duplicate_json_key')
            result[key] = value
        return result
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        raise ScenarioError('scenario_json_invalid') from None
    _require(isinstance(result, dict), 'scenario_structure_invalid')
    return result


def _read(path: Path | str, *, private: bool = False) -> bytes:
    try:
        target = Path(path).resolve()
        if private:
            _require(not target.is_relative_to(ROOT.resolve()), 'scenario_private_path_inside_workspace')
        raw = target.read_bytes()
        _require(0 < len(raw) <= 8 * 1024 * 1024, 'scenario_input_size_invalid')
        return raw
    except OSError:
        raise ScenarioError('scenario_input_unreadable') from None


def assert_private_path(path: Path | str) -> Path:
    target = Path(path).resolve()
    _require(not target.is_relative_to(ROOT.resolve()), 'scenario_private_path_inside_workspace')
    return target


def validate_plan_scenario_binding(value: Any) -> None:
    """Used by the plan DTO, including directly constructed plans."""
    _require(isinstance(value, Mapping) and set(value) == BINDING_KEYS, 'scenario_plan_binding_invalid')
    _require(value['scenario_id'] in tuple(row[0] for row in RECIPES), 'scenario_id_invalid')
    for key in BINDING_KEYS - {'scenario_id'}:
        _require(isinstance(value[key], str) and re.fullmatch('[0-9a-f]{64}', value[key]) is not None,
                 'scenario_plan_binding_invalid')


def _axis(value: Any, name: str, case: Any) -> None:
    _exact(value, AXIS_KEYS)
    _require(value['applicability'] in ('required', 'not_applicable', 'unknown'), 'scenario_axis_invalid')
    _require(type(value['criterion']) is str and value['criterion'] in AXIS_CRITERIA[name] and
             type(value['reason']) is str and value['reason'] in REASONS, 'scenario_axis_invalid')
    _require(value['temporal_intent'] in ('current', 'historical', 'future_explicit', 'not_applicable', 'unknown'), 'scenario_axis_invalid')
    if name in ('cross_user', 'stale_source'):
        _require(value['applicability'] == 'required', 'scenario_required_axis_invalid')
    if value['as_of'] is not None:
        try:
            _require(isinstance(value['as_of'], str) and date.fromisoformat(value['as_of']).isoformat() == value['as_of'], 'scenario_date_invalid')
        except (ValueError, TypeError):
            raise ScenarioError('scenario_date_invalid') from None
    _require(isinstance(value['target_refs'], list), 'scenario_refs_invalid')
    seen = set()
    for ref in value['target_refs']:
        _exact(ref, ('collection', 'index'))
        collection, index = ref['collection'], ref['index']
        _require(collection in ('expected_sources', 'relevant_units', 'forbidden_sources'), 'scenario_refs_invalid')
        _require(type(index) is int and 0 <= index < len(getattr(case, collection)), 'scenario_refs_invalid')
        _require((collection, index) not in seen, 'scenario_refs_invalid')
        seen.add((collection, index))
    _require(isinstance(value['targets'], list), 'scenario_targets_invalid')
    for target in value['targets']:
        _exact(target, ('entity_type', 'entity_key', 'filters'))
        _require(all(isinstance(target[k], str) and 0 < len(target[k]) <= 256 for k in ('entity_type', 'entity_key')),
                 'scenario_targets_invalid')
        _require(isinstance(target['filters'], dict), 'scenario_targets_invalid')
        for key, item in target['filters'].items():
            _require(isinstance(key, str) and 0 < len(key) <= 256 and
                     (item is None or type(item) in (str, int, float, bool)), 'scenario_targets_invalid')


@dataclass(frozen=True, repr=False)
class ValidatedScenarioContract:
    _dataset: P2Dataset = field(repr=False)
    _assignments: tuple[str, ...] = field(repr=False)
    _bindings: Mapping[str, Any] = field(repr=False)
    _ingest: P2IngestPlan = field(repr=False)
    _proof: object = field(repr=False)
    _axis_counts: Mapping[str, Any] = field(repr=False)
    _gaps: Mapping[str, int] = field(repr=False)

    def __repr__(self) -> str:
        return '<ValidatedScenarioContract: sealed assignment>'

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(row[0] for row in RECIPES)

    def _index(self, name: str) -> int:
        _require(self._proof is _PROOF, 'scenario_contract_unvalidated')
        _require(_cases_sha(self._dataset.cases) == self._bindings['full_cases_sha256'], 'scenario_dataset_changed')
        _require(name in self.scenario_ids, 'scenario_id_invalid')
        return self.scenario_ids.index(name)

    def _cases(self, name: str) -> tuple[Any, ...]:
        self._index(name)
        return tuple(c for c, owner in zip(self._dataset.cases, self._assignments) if owner == name)

    def ingest_plan(self, name: str) -> P2IngestPlan:
        index = self._index(name)
        return P2IngestPlan(tuple(self._ingest.sources[i] for i in RECIPES[index][1]), label='h2-' + name)

    def binding(self, name: str) -> dict[str, str]:
        self._index(name)
        return dict(scenario_id=name, **dict(self._bindings),
                    subset_sha256=_cases_sha(self._cases(name)),
                    scenario_ingest_sha256=payload_sha256(self.ingest_plan(name).as_dict()))

    def subset(self, name: str) -> P2RunDataset:
        cases = self._cases(name)
        full = P2RunDataset.from_p2_dataset(self._dataset)
        identity = dict(full.identity)
        identity.update(case_count=len(cases), strata=dict(Counter(str(c.stratum) for c in cases)),
                        turn_stats={'total_turns': sum(len(case_questions(c)) for c in cases),
                                    'max_turns_per_case': max((len(case_questions(c)) for c in cases), default=0)},
                        scenario_binding=self.binding(name))
        return P2RunDataset(visibility='holdout', cases=cases, identity=MappingProxyType(identity))

    def build_plan(self, name: str, *, plan_id: str, created_utc: str, plan_version: str = 'v0.1',
                   max_requests: int = 1100) -> P2RunPlan:
        from .p2_holdout_plan import build_holdout_plan
        index = self._index(name)
        return build_holdout_plan(cases=tuple((c.case_id, len(case_questions(c))) for c in self._cases(name)),
                                  ingest_batches=RECIPES[index][2], plan_id=plan_id,
                                  plan_version=plan_version, created_utc=created_utc,
                                  max_requests=max_requests, scenario_binding=self.binding(name))

    def validate_run(self, plan: P2RunPlan, dataset: P2RunDataset, ingest: Any) -> None:
        binding = plan.scenario_binding
        validate_plan_scenario_binding(binding)
        name = binding['scenario_id']
        _require(dict(binding) == self.binding(name), 'scenario_binding_mismatch')
        _require(dataset.visibility == 'holdout' and dict(dataset.identity) == dict(self.subset(name).identity)
                 and _cases_sha(dataset.cases) == binding['subset_sha256'], 'scenario_subset_mismatch')
        _require(isinstance(ingest, P2IngestPlan) and ingest == self.ingest_plan(name), 'scenario_ingest_mismatch')
        _require(payload_sha256(ingest.as_dict()) == binding['scenario_ingest_sha256'], 'scenario_ingest_mismatch')
        expected = self.build_plan(name, plan_id=plan.plan_id, created_utc=plan.created_utc,
                                   plan_version=plan.plan_version, max_requests=plan.max_requests)
        _require(expected.as_dict() == plan.as_dict(), 'scenario_plan_mismatch')

    def safe_summary(self) -> dict[str, Any]:
        return dict(case_count=30, total_turns=36, scenario_counts=dict(Counter(self._assignments)),
                    axis_counts={k: dict(v) for k, v in self._axis_counts.items()},
                    fixed_gap_counts=dict(self._gaps), quality_readiness='BLOCKED',
                    runtime_axis_evidence_produced=False, release_ready=False)


def load_scenario_contract(dataset: P2Dataset, *, annotation_path: Path | str, key_file: Path | str,
                           review_path: Path | str,
                           manager_path: Path | str = PUBLIC_CUSTODY / 'manager-acceptance.json',
                           review_aggregate_path: Path | str = PUBLIC_CUSTODY / 'review-aggregate.json',
                           scenario_path: Path | str = EVALUATION / 'p2-h2-scenarios-v0_2.json',
                           ingest_path: Path | str = DEFAULT_INGEST,
                           source_map_path: Path | str = EVALUATION / 'p2-holdout-v2.source-map.json',
                           schema_path: Path | str = EVALUATION / 'p2-h2-custody-annotations-v0_2.md') -> ValidatedScenarioContract:
    """Validate all frozen bindings BEFORE decrypt, then exact coverage in memory."""
    _require(isinstance(dataset, P2Dataset) and dataset.visibility == 'holdout' and
             len(dataset.cases) == dataset.manifest.case_count == 30, 'scenario_full_dataset_required')
    _require(len({c.case_id for c in dataset.cases}) == 30 and
             sum(len(case_questions(c)) for c in dataset.cases) == 36, 'scenario_full_dataset_invalid')
    raw_contract, raw_ingest = _read(scenario_path), _read(ingest_path)
    recipe = _json(raw_contract)
    _exact(recipe, ('schema_version', 'ingest_plan_sha256', 'assignment_priority', 'scenarios'))
    _require(recipe['schema_version'] == 'p2-h2-scenarios/v0.2' and
             recipe['assignment_priority'] == [r[0] for r in RECIPES] and
             recipe['scenarios'] == [dict(scenario_id=n, source_indices=list(ix), ingest_batches=b) for n, ix, b in RECIPES],
             'scenario_recipe_invalid')
    _require(recipe['ingest_plan_sha256'] == _sha(raw_ingest), 'scenario_ingest_binding_invalid')
    manager, review = _json(_read(manager_path)), _json(_read(review_aggregate_path))
    _exact(manager, MANAGER_KEYS)
    _exact(review, REVIEW_KEYS)
    _require(manager['accepted_scope'] == ['annotation_structure', 'semantic_consistency_with_gaps',
                'scenario_assignment_for_offline_implementation'], 'scenario_assignment_unapproved')
    for document, names in ((manager, ('case_count', 'scenario_unknown', 'independent_disagreements',
            'unresolved_entity_targets', 'unresolved_date_anchors', 'new_real_calls')),
            (review, ('case_count', 'unique_case_count', 'coverage_missing_count', 'coverage_extra_count',
            'coverage_duplicate_count', 'axis_unknown_total', 'date_anchor_gap_total',
            'independent_review_disagreement_count', 'scenario_disagreement_count', 'axis_disagreement_count',
            'old_disagreement_candidate_count', 'old_disagreement_rejudged_count', 'old_disagreement_corrected_count',
            'network_attempt_count', 'product_test_count', 'real_call_count', 'subagent_count', 'commit_count'))):
        _require(all(type(document[k]) is int and 0 <= document[k] <= 1600 for k in names), 'scenario_metadata_counts_invalid')
    _require(all(manager[k] is False for k in ('full_annotation_quality_ready', 'live_execution_authorized_by_this_record',
                'quality_released', 'runtime_axis_evidence_produced')) and manager['new_real_calls'] == 0 and
                manager['independent_quality_readiness'] == 'BLOCKED', 'scenario_assignment_unapproved')
    _require(review['schema_version'] == 'p2-h2-custody-review-aggregate/v0.2' and
             review['annotation_schema_version'] == 'p2-h2-custody/v0.2' and
             review['quality_readiness'] == 'BLOCKED' and review['quality_released'] is False and
             review['runtime_axis_evidence_produced'] is False and review['same_order_coverage'] is True and
             review['case_count'] == review['unique_case_count'] == 30 and
             review['coverage_missing_count'] == review['coverage_extra_count'] == review['coverage_duplicate_count'] == 0,
             'scenario_review_invalid')
    _exact(review['scenario_counts'], [r[0] for r in RECIPES] + ['unknown'])
    _exact(review['axis_counts'], AXIS_CRITERIA)
    _exact(review['fixed_gap_counts'], ('unresolved_entity_target', 'unresolved_date_anchor', 'unresolved_scenario'))
    count_tables = [review['scenario_counts'], review['fixed_gap_counts']]
    for table in review['axis_counts'].values():
        _exact(table, ('required', 'not_applicable', 'unknown'))
        count_tables.append(table)
    _require(all(type(n) is int and 0 <= n <= 30 for table in count_tables for n in table.values()),
             'scenario_metadata_counts_invalid')
    _require(review['fixed_gap_counts'] == dict(unresolved_entity_target=manager['unresolved_entity_targets'],
                unresolved_date_anchor=manager['unresolved_date_anchors'], unresolved_scenario=0),
             'scenario_review_invalid')
    before, after = review['input_hashes_before'], review['input_hashes_after']
    _require(isinstance(before, dict) and before == after and review['input_hashes_unchanged'] is True,
             'scenario_corpus_binding_invalid')
    for source in _json(raw_ingest).get('sources', []):
        _require(isinstance(source, dict) and isinstance(source.get('path'), str), 'scenario_ingest_invalid')
        path = (ROOT / source['path']).resolve()
        _require(path.is_relative_to((ROOT / 'fixtures/acceptance').resolve()) and
                 before.get('corpus:' + source['path']) == _sha(_read(path)), 'scenario_corpus_binding_invalid')
    _require(manager.get('schema_version') == 'p2-h2-custody-manager-acceptance/v0.2' and
             manager.get('scenario_assignment_frozen') is True and manager.get('case_count') == 30 and
             manager.get('scenario_unknown') == manager.get('independent_disagreements') == 0 and
             manager.get('independent_structure') == manager.get('independent_semantic_consistency') == 'PASS' and
             'scenario_assignment_for_offline_implementation' in manager.get('accepted_scope', []),
             'scenario_assignment_unapproved')
    expected = dict(manifest_sha256=dataset.manifest.manifest_sha256,
                    dataset_version=dataset.manifest.dataset_version, label_version=dataset.manifest.label_version,
                    cases_sha256=_cases_sha(dataset.cases), source_map_sha256=_sha(_read(source_map_path)),
                    ingest_plan_sha256=_sha(raw_ingest), schema_sha256=_sha(_read(schema_path)),
                    scenario_contract_sha256=_sha(raw_contract))
    _require(all(manager.get(k) == expected[k] for k in ('schema_sha256', 'scenario_contract_sha256')),
             'scenario_public_binding_mismatch')
    _require(review.get('bindings') == expected and review.get('structure') == review.get('semantic_consistency') == 'PASS'
             and review.get('independent_review_disagreement_count') == review.get('scenario_disagreement_count') == 0,
             'scenario_review_invalid')
    cipher, review_cipher = _read(annotation_path, private=True), _read(review_path, private=True)
    _require(_sha(cipher) == manager.get('annotation_ciphertext_sha256') == review.get('annotation_ciphertext_sha256') and
             _sha(review_cipher) == manager.get('review_ciphertext_sha256') == review.get('review_ciphertext_sha256'),
             'scenario_ciphertext_mismatch')
    try:
        from cryptography.fernet import Fernet
        plaintext = Fernet(_read(key_file, private=True).strip()).decrypt(cipher)
    except ScenarioError:
        raise
    except Exception:
        raise ScenarioError('scenario_decrypt_failed') from None
    payload = _json(plaintext)
    _exact(payload, ('schema_version', 'bindings', 'cases'))
    _require(payload['schema_version'] == 'p2-h2-custody/v0.2' and payload['bindings'] == expected,
             'scenario_annotation_binding_mismatch')
    _require(isinstance(payload['cases'], list) and len(payload['cases']) == 30, 'scenario_coverage_invalid')
    assignments = []
    axis_counts = {k: Counter() for k in AXIS_CRITERIA}
    for case, annotation in zip(dataset.cases, payload['cases']):
        _exact(annotation, ('case_id', 'scenario_id', 'axes'))
        _require(annotation['case_id'] == case.case_id, 'scenario_coverage_invalid')
        _require(annotation['scenario_id'] in recipe['assignment_priority'], 'scenario_assignment_unknown')
        _exact(annotation['axes'], AXIS_CRITERIA)
        for name in AXIS_CRITERIA:
            _axis(annotation['axes'][name], name, case)
            axis_counts[name][annotation['axes'][name]['applicability']] += 1
        assignments.append(annotation['scenario_id'])
    _require(review['scenario_counts'] == {name: assignments.count(name) for name in recipe['assignment_priority'] + ['unknown']} and
             review['axis_counts'] == {name: {state: counts[state] for state in ('required', 'not_applicable', 'unknown')}
                                      for name, counts in axis_counts.items()}, 'scenario_review_counts_mismatch')
    try:
        ingest = ingest_plan_from_document(_json(raw_ingest))
    except (ValueError, OSError):
        raise ScenarioError('scenario_ingest_invalid') from None
    _require(len(ingest.sources) == 12, 'scenario_ingest_invalid')
    bindings = dict(assignment_sha256=payload_sha256(payload), custody_sha256=_sha(cipher),
                    review_sha256=_sha(review_cipher), scenario_contract_sha256=expected['scenario_contract_sha256'],
                    ingest_plan_sha256=expected['ingest_plan_sha256'], full_cases_sha256=expected['cases_sha256'],
                    manifest_sha256=expected['manifest_sha256'], schema_sha256=expected['schema_sha256'],
                    source_map_sha256=expected['source_map_sha256'])
    return ValidatedScenarioContract(dataset, tuple(assignments), MappingProxyType(bindings), ingest, _PROOF,
                                     MappingProxyType({k: MappingProxyType(dict(v)) for k, v in axis_counts.items()}),
                                     MappingProxyType({'unresolved_entity_target': int(manager.get('unresolved_entity_targets', 0)),
                                                       'unresolved_date_anchor': int(manager.get('unresolved_date_anchors', 0))}))


def validate_scenario_execution(plan: P2RunPlan, dataset: P2RunDataset, ingest: Any,
                                contract: ValidatedScenarioContract | None) -> None:
    """A scenario on either side requires a validated contract; no direct-API bypass."""
    if plan.scenario_binding is not None or dataset.identity.get('scenario_binding') is not None:
        _require(isinstance(contract, ValidatedScenarioContract), 'scenario_contract_required')
        contract.validate_run(plan, dataset, ingest)


def compose_scenario_runs(contract: ValidatedScenarioContract, runs: Any) -> dict[str, Any]:
    """Strict full-assignment composition, preserving all non-quantity blocks.

    Each part has plan/aggregate/status/run_id/turns_executed/binding. A stopped
    run may only be followed by explicit not_started entries. No silent padding.
    """
    _require(isinstance(runs, (tuple, list)) and len(runs) == 4, 'scenario_runs_incomplete')
    from .p2_scoring import P2_HOLDOUT_HARD_FAILURE_KINDS
    counts = dict(total=30, passed=0, failed=0, errors=0, executed=0)
    strata = {k: dict(total=v, passed=0, failed=0, errors=0) for k, v in contract._dataset.manifest.strata.items()}
    hard = {k: 0 for k in P2_HOLDOUT_HARD_FAILURE_KINDS}
    blocks: list[dict[str, Any]] = []
    identities, seen_run_ids, common = [], set(), None
    stopped = False
    not_started = turns = real_calls = 0
    complete = True
    modes = set()
    for name, part in zip(contract.scenario_ids, runs):
        _exact(part, ('plan', 'aggregate', 'status', 'run_id', 'turns_executed', 'binding'))
        plan, status = part['plan'], part['status']
        _require(isinstance(plan, P2RunPlan), 'scenario_plan_required')
        subset = contract.subset(name)
        contract.validate_run(plan, subset, contract.ingest_plan(name))
        _require(isinstance(part['run_id'], str) and part['run_id'] and part['run_id'] not in seen_run_ids,
                 'scenario_run_duplicate')
        seen_run_ids.add(part['run_id'])
        _require(status in ('succeeded', 'blocked', 'aborted', 'not_started'), 'scenario_run_status_invalid')
        _require(type(part['turns_executed']) is int and 0 <= part['turns_executed'] <= subset.identity['turn_stats']['total_turns'],
                 'scenario_turn_counts_invalid')
        ident = dict(scenario_id=name, run_id=part['run_id'], plan_sha256=plan.plan_sha256,
                     binding=contract.binding(name), status=status, aggregate_sha256=None)
        identities.append(ident)
        if status == 'not_started':
            _require(stopped and part['aggregate'] is None and part['binding'] is None and part['turns_executed'] == 0,
                     'scenario_not_started_invalid')
            not_started += 1
            complete = False
            counts['errors'] += len(subset.cases)
            for bucket, size in subset.identity['strata'].items(): strata[bucket]['errors'] += size
            continue
        _require(not stopped, 'scenario_started_after_stop')
        stopped = status != 'succeeded'
        complete = complete and not stopped
        binding, card = part['binding'], part['aggregate']
        _require(isinstance(binding, Mapping) and binding.get('scenario_binding') == contract.binding(name),
                 'scenario_run_binding_mismatch')
        _require(isinstance(card, Mapping) and card.get('run_id') == part['run_id'] and
                 card.get('config_hash') == binding.get('config_hash') and (stopped or binding.get('config_hash')),
                 'scenario_aggregate_binding_mismatch')
        from .p2_diagnostics import validate_scorecard
        try:
            validate_scorecard(card, total=len(subset.cases), run_id=part['run_id'], config_hash=binding.get('config_hash'))
        except (ValueError, TypeError, KeyError):
            raise ScenarioError('scenario_scorecard_invalid') from None
        shared = {k: binding.get(k) for k in ('pipeline_version', 'provider', 'gate_config_hash')}
        if not all(v not in (None, '', {}) for v in shared.values()):
            _require(stopped and not binding.get('config_hash'), 'scenario_pipeline_unbound')
            blocks.append(dict(code='scenario_pipeline_unbound', severity='unknown'))
        else:
            if common is None: common = shared
            _require(shared == common, 'scenario_pipeline_mismatch')
        ident['aggregate_sha256'] = payload_sha256(card)
        ident['config_hash'] = binding['config_hash']
        for key in ('total', 'passed', 'failed', 'errors', 'executed', 'hard_failures', 'real_calls'):
            _require(type(card.get(key)) is int and card[key] >= 0, 'scenario_aggregate_counts_invalid')
        _require(card['total'] == len(subset.cases) and card['total'] == card['passed'] + card['failed'] + card['errors']
                 and card['executed'] == card['passed'] + card['failed'] and card.get('min_pass') == 24
                 and card.get('hard_failures_max') == 0 and card.get('thresholds_approved') is False,
                 'scenario_aggregate_counts_invalid')
        by_stratum = card.get('by_stratum')
        _require(isinstance(by_stratum, Mapping) and set(by_stratum) == set(subset.identity['strata']),
                 'scenario_aggregate_strata_invalid')
        totals = Counter()
        for bucket, size in subset.identity['strata'].items():
            values = by_stratum[bucket]
            _require(isinstance(values, Mapping) and set(values) == {'total', 'passed', 'failed', 'errors'} and
                     all(type(n) is int and n >= 0 for n in values.values()) and
                     values['total'] == size == values['passed'] + values['failed'] + values['errors'],
                     'scenario_aggregate_strata_invalid')
            totals.update(values)
            for key in ('passed', 'failed', 'errors'): strata[bucket][key] += values[key]
        _require(all(totals[k] == card[k] for k in ('total', 'passed', 'failed', 'errors')),
                 'scenario_aggregate_counts_invalid')
        by_kind = card.get('hard_failures_by_kind')
        _require(isinstance(by_kind, Mapping) and set(by_kind) == set(hard) and
                 all(type(n) is int and n >= 0 for n in by_kind.values()) and
                 sum(by_kind.values()) == card['hard_failures'], 'scenario_hard_counts_invalid')
        for key in hard: hard[key] += by_kind[key]
        for key in ('passed', 'failed', 'errors', 'executed'): counts[key] += card[key]
        turns += part['turns_executed']
        real_calls += card['real_calls']
        modes.add(card.get('execution_mode'))
        _require(isinstance(card.get('blocks'), list), 'scenario_blocks_invalid')
        for block in card['blocks']:
            _require(isinstance(block, Mapping) and isinstance(block.get('code'), str) and
                     re.fullmatch('[a-z][a-z0-9_]{0,95}', block['code']) is not None and
                     block.get('severity') in ('unknown', 'hard', 'quality'), 'scenario_blocks_invalid')
            code, evidence = block['code'], block.get('evidence', {})
            quantity_only = (
                code == 'holdout_sample_missing' and evidence == {'total': len(subset.cases), 'expected': 30}
            ) or (
                code == 'holdout_below_threshold' and evidence == {'passed': card['passed'], 'min_pass': 24}
            )
            if not quantity_only:
                allowed = {'holdout_sample_missing', 'holdout_strata_mismatch', 'holdout_case_error',
                           'holdout_below_threshold', 'holdout_threshold_unapproved', 'holdout_document_code_unmapped',
                           'holdout_document_code_ambiguous', 'holdout_hard_failure_unclassified',
                           'holdout_hard_failure_unverified', 'holdout_case_unscorable', 'holdout_scorecard_leak',
                           'holdout_hard_failure'}
                _require(code in allowed, 'scenario_block_code_unregistered')
                blocks.append(dict(scenario_id=name, code=code, severity=block['severity']))
        if 'diagnostics' in card:
            from .p2_diagnostics import validate_diagnostics
            try:
                validate_diagnostics(card['diagnostics'], total=len(subset.cases))
            except (ValueError, TypeError, KeyError):
                raise ScenarioError('scenario_diagnostics_invalid') from None
            ident['diagnostics'] = card['diagnostics']
    _require(len(modes) <= 1, 'scenario_execution_mode_mixed')
    if not complete or turns != 36:
        blocks.append(dict(code='scenario_execution_incomplete', severity='unknown'))
    if counts['errors']: blocks.append(dict(code='holdout_case_error', severity='unknown'))
    if counts['passed'] < 24: blocks.append(dict(code='holdout_below_threshold', severity='quality'))
    if sum(hard.values()): blocks.append(dict(code='holdout_hard_failure', severity='hard'))
    blocks.append(dict(code='holdout_threshold_unapproved', severity='unknown'))
    blocks.append(dict(code='holdout_hard_failure_unverified', severity='unknown'))
    payload = dict(schema_version='p2-h2-scenario-composition/v0.1', **counts,
                   status='complete' if complete and turns == 36 else 'partial',
                   turns_planned=36, turns_executed=turns, not_started=not_started,
                   min_pass=24, threshold_met=counts['passed'] >= 24,
                   hard_failures=sum(hard.values()), hard_failures_by_kind=hard,
                   by_stratum=strata, thresholds_approved=False, blocks=blocks,
                   real_calls=real_calls, execution_mode=next(iter(modes), 'local_mock'),
                   manifest_sha256=contract._dataset.manifest.manifest_sha256,
                   full_cases_sha256=contract._bindings['full_cases_sha256'],
                   assignment_sha256=contract._bindings['assignment_sha256'], runs=identities,
                   annotation=contract.safe_summary(), release_ready=False)
    from .p2_runner import _holdout_leak_needles
    raw = json.dumps(payload, ensure_ascii=False)
    for case in contract._dataset.cases:
        _require(case.case_id not in raw and all(n.strip() not in raw for n in _holdout_leak_needles(case)
                                                if len(n.strip()) >= 2), 'scenario_composition_leak')
    return payload


async def run_scenario_batch(contract: ValidatedScenarioContract, plans: Any, *, out_dir: Path | str,
                             snapshot: Any, gate_config: Any) -> dict[str, Any]:
    """Mock-only CLI orchestration: prevalidate every plan, fresh app/auth each,
    stop at the first execution failure. No live option or automatic retry.
    """
    from .p2_authorization import preflight_p2
    from .p2_runner import build_dry_run_authorization, run_p2
    from .product_adapter import ProductEvalAdapter, MockChatBackend
    out = assert_private_path(out_dir)
    _require(not out.exists(), 'scenario_output_exists')
    _require(isinstance(plans, (tuple, list)) and len(plans) == 4, 'scenario_plans_incomplete')
    for name, plan in zip(contract.scenario_ids, plans):
        contract.validate_run(plan, contract.subset(name), contract.ingest_plan(name))
    out.mkdir(parents=True)
    parts = []
    stopped = False
    for name, plan in zip(contract.scenario_ids, plans):
        run_id = 'scenario-' + name
        part = dict(plan=plan, aggregate=None, status='not_started', run_id=run_id,
                    turns_executed=0, binding=None)
        parts.append(part)
        if stopped:
            continue
        preflight = preflight_p2(plan, snapshot)
        _require(preflight.ok, 'scenario_preflight_failed')
        adapter = ProductEvalAdapter(out / name, dataset=contract.subset(name),
                                    ingest_plan=contract.ingest_plan(name), chat=MockChatBackend(),
                                    purge_traces_on_close=True, scenario_contract=contract)
        try:
            result = await run_p2(plan, adapter=adapter,
                                  authorization=build_dry_run_authorization(plan, preflight),
                                  run_id=run_id, gate_config=gate_config)
        finally:
            await adapter.close()
        card = _json((adapter.paths.run_dir / 'holdout_scorecard.json').read_bytes())
        summary = _json((adapter.paths.run_dir / 'summary.json').read_bytes())
        part.update(aggregate=card, status=result.status, turns_executed=summary['turns']['executed'],
                    binding=summary['binding'])
        stopped = result.status != 'succeeded'
    combined = compose_scenario_runs(contract, parts)
    (out / 'scenario_composition.json').write_text(json.dumps(combined, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return combined
