"""H2 v3 专用 scenario loader 实例（新增文件；``p2_holdout_scenarios.py`` 一字未改）。

为什么需要这个文件
------------------
冻结的 ``p2_holdout_scenarios.load_scenario_contract`` 在语料绑定处把允许前缀钉成
``fixtures/acceptance``（该文件 :286-288），而 v3 语料的根是
``fixtures/acceptance-h2v3``（见 v3 manifest），因此 v3 ingest plan 会被
``scenario_corpus_binding_invalid`` 拒收。D-G 明令不得改那个文件，所以这里提供
**同形态的第二个 loader 实例**，只放开两处：

1. **允许前缀**：只允许 ``fixtures/acceptance-h2v3``（v3 根），并且**仍然拒绝**
   ``fixtures/acceptance``（v2 根）——不是"取消前缀校验"，是"换成 v3 的根"。
2. **v3 ingest plan 绑定**：默认 ingest/scenario/source-map/custody 路径全部指向 v3 件，
   逐源 SHA 仍与 v3 review aggregate 的 ``input_hashes_before`` 逐值相等。

校验体本身逐字复用 ``p2_holdout_scenarios`` 里已有的实现：JSON/固定码/轴校验/密文/
计数/表结构全部调用那边的函数（``_read`` / ``_json`` / ``_exact`` / ``_require`` /
``_sha`` / ``_cases_sha`` / ``_axis`` / ``RECIPES`` / ``AXIS_CRITERIA`` / ``MANAGER_KEYS`` /
``REVIEW_KEYS`` / ``ValidatedScenarioContract``）。唯一**计算**差异就是那个前缀常量；
v3 与 v2 的校验体等价性由 ``test_p2_v3_wiring.py`` 用"同一份 v2 合成包，两条 loader 产出
逐值相同的 binding/subset"机检证明（不是靠声明）。

v3 的保管件（scenario contract / manager acceptance / review aggregate）目前**尚未产出**：
本模块的默认路径是它们的**声明位置**，缺件一律由 ``p2_holdout_scenarios._read`` 抛
``scenario_input_unreadable``（固定码），不会回落到 v2 件、也不会静默放行。
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .p2_contracts import payload_sha256
from .p2_dataset import P2Dataset
from .p2_holdout_scenarios import (
    AXIS_CRITERIA,
    EVALUATION,
    MANAGER_KEYS,
    RECIPES,
    REVIEW_KEYS,
    ROOT,
    ScenarioError,
    ValidatedScenarioContract,
    _PROOF,
    _axis,
    _cases_sha,
    _exact,
    _json,
    _read,
    _require,
    _sha,
)
from .product_adapter import case_questions, ingest_plan_from_document

V2_CORPUS_ROOT = (ROOT / 'fixtures/acceptance').resolve()
"""v2 语料根（原 loader 允许、v3 loader 拒绝）。"""

V3_CORPUS_ROOT = (ROOT / 'fixtures/acceptance-h2v3').resolve()
"""v3 语料根（v3 loader 允许、原 loader 拒绝）。"""

_ALLOWED_ROOTS = (V2_CORPUS_ROOT, V3_CORPUS_ROOT)

V3_INGEST = ROOT / 'docs/reports/OBS-EVAL/P2/H2V3/PM/p2-ingest-plan-H2-v3.json'
V3_SCENARIO_CONTRACT = EVALUATION / 'p2-h2-scenarios-H2v3.json'
V3_MANAGER = ROOT / 'docs/reports/OBS-EVAL/P2/H2V3/PM/manager-acceptance.json'
V3_REVIEW_AGGREGATE = ROOT / 'docs/reports/OBS-EVAL/P2/H2V3/PM/review-aggregate.json'
V3_SOURCE_MAP = EVALUATION / 'p2-holdout-v3.source-map.json'
V3_SCHEMA = EVALUATION / 'p2-h2-custody-annotations-v0_2.md'

__all__ = [
    'V2_CORPUS_ROOT',
    'V3_CORPUS_ROOT',
    'V3_INGEST',
    'V3_MANAGER',
    'V3_REVIEW_AGGREGATE',
    'V3_SCENARIO_CONTRACT',
    'V3_SCHEMA',
    'V3_SOURCE_MAP',
    'ScenarioError',
    'load_v3_scenario_contract',
    'validate_v3_corpus_root',
]


def validate_v3_corpus_root(value: Any) -> Path:
    """只接受两个已知语料根之一（resolve 后逐字相等）；其余固定码拒绝。

    这条约束的意义：允许前缀是**闭集**，不是"随便传一个目录"。公开入口
    ``load_v3_scenario_contract`` 始终传 v3 根；``_load_contract`` 的 ``corpus_root``
    参数只为等价性测试开放，且同样受这条闭集约束。
    """
    try:
        resolved = Path(value).resolve()
    except (OSError, TypeError, ValueError):
        raise ScenarioError('scenario_corpus_root_invalid') from None
    _require(resolved in _ALLOWED_ROOTS, 'scenario_corpus_root_invalid')
    return resolved


def _load_contract(
    dataset: P2Dataset,
    *,
    annotation_path: Path | str,
    key_file: Path | str,
    review_path: Path | str,
    manager_path: Path | str,
    review_aggregate_path: Path | str,
    scenario_path: Path | str,
    ingest_path: Path | str,
    source_map_path: Path | str,
    schema_path: Path | str,
    corpus_root: Path | str,
) -> ValidatedScenarioContract:
    """与 ``load_scenario_contract`` 等价的校验体；唯一计算差异是语料前缀。

    ``p2_holdout_scenarios.py`` 未改动，因此这里保留与它逐条相同的校验顺序与固定码：
    先全部绑定校验，再解密读注解（in memory），最后按覆盖计数逐条对账。
    """
    root = validate_v3_corpus_root(corpus_root)
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
        # 与冻结 loader :286-288 的唯一计算差异：允许前缀由 fixtures/acceptance 换成传入的语料根。
        _require(path.is_relative_to(root) and
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
    # _PROOF 是冻结模块的封印哨兵（ValidatedScenarioContract 没有公开构造器）：
    # 这里刻意复用同一个对象，而不是在 v3 侧另造一个"看起来像封印"的标记。
    return ValidatedScenarioContract(dataset, tuple(assignments), MappingProxyType(bindings), ingest, _PROOF,
                                     MappingProxyType({k: MappingProxyType(dict(v)) for k, v in axis_counts.items()}),
                                     MappingProxyType({'unresolved_entity_target': int(manager.get('unresolved_entity_targets', 0)),
                                                       'unresolved_date_anchor': int(manager.get('unresolved_date_anchors', 0))}))


def load_v3_scenario_contract(
    dataset: P2Dataset,
    *,
    annotation_path: Path | str,
    key_file: Path | str,
    review_path: Path | str,
    manager_path: Path | str = V3_MANAGER,
    review_aggregate_path: Path | str = V3_REVIEW_AGGREGATE,
    scenario_path: Path | str = V3_SCENARIO_CONTRACT,
    ingest_path: Path | str = V3_INGEST,
    source_map_path: Path | str = V3_SOURCE_MAP,
    schema_path: Path | str = V3_SCHEMA,
) -> ValidatedScenarioContract:
    """v3 loader 入口：语料前缀钉死 ``fixtures/acceptance-h2v3``，其余与冻结 loader 同义。

    与 ``load_scenario_contract`` 的差异仅两处（其余逐条相同）：
    - 允许前缀 = v3 语料根（v2 根被拒，固定码 ``scenario_corpus_binding_invalid``）；
    - 默认 ingest / scenario contract / source-map / custody 路径 = v3 件。
    """
    return _load_contract(
        dataset,
        annotation_path=annotation_path,
        key_file=key_file,
        review_path=review_path,
        manager_path=manager_path,
        review_aggregate_path=review_aggregate_path,
        scenario_path=scenario_path,
        ingest_path=ingest_path,
        source_map_path=source_map_path,
        schema_path=schema_path,
        corpus_root=V3_CORPUS_ROOT,
    )
