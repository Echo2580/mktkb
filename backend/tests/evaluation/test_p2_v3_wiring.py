"""v3 三处接线的合成测试（A scenario loader / B source-map 分发 / C per-run business_date）。

口径
----
- **零真实调用**：业务用例全部挂 ``t09_network_guard``（外部出站尝试必须为空）。
- **代理必须不可达**：本机配着 ``http://127.0.0.1:7897``（env 里 3 个变量 + 注册表里 3 个
  scheme）。netguard 把回环放行，所以"借道本机代理"的探针会被当成回环而漏出——这正是历史
  上一次 example.com 探针漏出的路径。因此：autouse fixture 删掉全部代理环境变量（注册表代理
  删不掉，只能绕过），正对照里的 urllib 探针一律用 ``ProxyHandler({})`` 显式禁用代理，并断言
  记录到的 4 条外部尝试全部指向外部主机。
- **正对照**：``test_zz_outbound_positive_control`` 独立安装**同一组** primitives
  （``acceptance.support.netguard`` 的 ``NetworkAttempts``/``NetworkBlocked``/``is_loopback``），
  证明 DNS / 直连 / urllib / httpx 四类探针都被拦。它不挂共享 fixture：共享 fixture 的 teardown
  要求 external 为空，而正对照必须产生外部尝试。
- **只读公开件**：v2/v3 source map、v2 scenario contract、v2 ingest plan、v3 语料 manifest 与
  12 个语料文件、L1、v2 公开 custody 元数据。不读题面/答案/私有密文/key/``.env``。
- 合成封存数据复用 ``test_p2_holdout_scorecard._write_sealed``（现生成 Fernet key，落在 tmp_path）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet

_EVAL_TESTS = Path(__file__).resolve().parent
_TESTS = Path(__file__).resolve().parents[1]
for _path in (_TESTS, _EVAL_TESTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from acceptance.support.netguard import NetworkAttempts, NetworkBlocked, is_loopback  # noqa: E402
from test_p2_holdout_scorecard import _write_sealed, t09_network_guard  # noqa: E402,F401

from mktkb.evaluation import p2_holdout_run_date as run_date  # noqa: E402
from mktkb.evaluation import p2_holdout_scenarios as scenario  # noqa: E402
from mktkb.evaluation import p2_holdout_scenarios_v3 as scenario_v3  # noqa: E402
from mktkb.evaluation import p2_holdout_source_map as source_map  # noqa: E402
from mktkb.evaluation import p2_score_run as drive  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, cases_to_jsonl  # noqa: E402
from mktkb.evaluation.p2_dataset import HOLDOUT_KEY_FILE_ENV, HOLDOUT_ROOT_ENV, load_p2_dataset  # noqa: E402
from mktkb.evaluation.product_adapter import ProductAdapterError, ProductEvalAdapter  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
V2_INGEST = ROOT / 'docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json'
V2_CONTRACT = ROOT / 'docs/evaluation/p2-h2-scenarios-v0_2.json'
V2_MAP = ROOT / 'docs/evaluation/p2-holdout-v2.source-map.json'
V2_SCHEMA = ROOT / 'docs/evaluation/p2-h2-custody-annotations-v0_2.md'
V3_MAP = ROOT / 'docs/evaluation/p2-holdout-v3.source-map.json'
V3_MANIFEST = ROOT / 'fixtures/acceptance-h2v3/manifest.json'
PUBLIC_CUSTODY = ROOT / 'docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2'
CORPUS_PREFIX = {'v2': 'fixtures/acceptance/', 'v3': 'fixtures/acceptance-h2v3/'}

_PROXY_KEYS = ('HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy',
               'NODE_USE_ENV_PROXY', 'node_use_env_proxy', 'NO_PROXY', 'no_proxy')
_PROXY_SCHEMES = frozenset({'all', 'http', 'https', 'ftp'})
AMBIENT_REGISTRY_PROXY = urllib.request.getproxies()
"""本机代理的**记录**（删不掉的那部分：Windows 注册表 IE/WinHTTP 设置）。"""


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')


@pytest.fixture(autouse=True)
def no_ambient_env_proxy(monkeypatch):
    """删掉代理环境变量：让"借道 env 代理"在本次用例里不可达（注册表代理由正对照显式绕过）。"""
    for key in _PROXY_KEYS:
        monkeypatch.delenv(key, raising=False)
    env_proxies = urllib.request.getproxies_environment()
    assert not (_PROXY_SCHEMES & set(env_proxies)), f'env 代理仍在：{env_proxies}'


# --------------------------------------------------------------------------- #
# A. v3 语料根：合成 v3 包（12 源逐条同构 v2 plan，只换语料根）
# --------------------------------------------------------------------------- #


def v3_ingest_document() -> dict[str, Any]:
    """用 v3 语料 manifest 生成 12 源 ingest 文档（上传次序/槽位语义与 v2 plan 逐条同构）。

    槽位规则抄自 v2 plan 的既有事实：槽位首传若不是该槽位的 normal 文件，用 ``name`` 指定该槽位
    的资料名（D01 槽位由 V03 建文档）；同槽后续上传一律用 ``document_ref`` 指回同一资料。
    """
    manifest = json.loads(V3_MANIFEST.read_text(encoding='utf-8'))
    normal_names = {item['id']: Path(item['path']).name for item in manifest['normal_files']}
    rows = sorted([(item['ingest_index'], item) for item in manifest['normal_files'] + manifest['variants']],
                  key=lambda pair: pair[0])
    seen_slots: set[str] = set()
    sources: list[dict[str, str]] = []
    for _, item in rows:
        slot = item['base_doc_code']
        own = Path(item['path']).name
        doc_name = normal_names.get(slot, own)
        entry = {'path': CORPUS_PREFIX['v3'] + item['path']}
        if slot in seen_slots:
            entry['document_ref'] = doc_name
        elif own != doc_name:
            entry['name'] = doc_name
        seen_slots.add(slot)
        sources.append(entry)
    return {'schema_version': 'p2-ingest-plan/v0.1', 'label': 'H2-v3', 'sources': sources}


@dataclass(frozen=True)
class Package:
    dataset: Any
    paths: dict[str, Path]
    ingest_document: dict[str, Any]


def _annotation_payload(dataset: Any, priority: list[str], bindings: dict[str, str]) -> dict[str, Any]:
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
        rows.append(dict(case_id=case.case_id, scenario_id=priority[index % len(priority)], axes=axes))
    return dict(schema_version='p2-h2-custody/v0.2', bindings=bindings, cases=rows)


def _package(tmp_path: Path, monkeypatch, *, corpus: str) -> Package:
    """造一套（合成封存 dataset + 真语料 ingest + 合成 custody 元数据）的 scenario 包。

    ``corpus='v3'`` 用 v3 语料根 + v3 source map；``corpus='v2'`` 用 v2 原件（回归/等价性用）。
    """
    sealed = _write_sealed(tmp_path)
    key = sealed.key_file.read_bytes().strip()
    monkeypatch.setenv(HOLDOUT_ROOT_ENV, str(sealed.root))
    monkeypatch.setenv(HOLDOUT_KEY_FILE_ENV, str(sealed.key_file))
    dataset = load_p2_dataset(sealed.manifest_path, visibility='holdout')
    if corpus == 'v3':
        ingest_document = v3_ingest_document()
        source_map_path = V3_MAP
    else:
        ingest_document = json.loads(V2_INGEST.read_text(encoding='utf-8'))
        source_map_path = V2_MAP
    contract_document = json.loads(V2_CONTRACT.read_text(encoding='utf-8'))
    ingest_path, contract_path = tmp_path / f'ingest-{corpus}.json', tmp_path / f'contract-{corpus}.json'
    ingest_path.write_bytes(encoded(ingest_document))
    # 只改一处：scenario contract 绑定的 ingest plan SHA（换成这轮真正落盘的字节）。
    contract_document['ingest_plan_sha256'] = sha(ingest_path.read_bytes())
    contract_path.write_bytes(encoded(contract_document))
    bindings = dict(manifest_sha256=dataset.manifest.manifest_sha256,
                    dataset_version=dataset.manifest.dataset_version,
                    label_version=dataset.manifest.label_version,
                    cases_sha256=sha(cases_to_jsonl(dataset.cases).encode('utf-8')),
                    source_map_sha256=sha(source_map_path.read_bytes()),
                    ingest_plan_sha256=sha(ingest_path.read_bytes()),
                    schema_sha256=sha(V2_SCHEMA.read_bytes()),
                    scenario_contract_sha256=sha(contract_path.read_bytes()))
    priority = list(contract_document['assignment_priority'])
    payload = _annotation_payload(dataset, priority, bindings)
    manager = json.loads((PUBLIC_CUSTODY / 'manager-acceptance.json').read_text(encoding='utf-8'))
    manager.update(schema_sha256=bindings['schema_sha256'],
                   scenario_contract_sha256=bindings['scenario_contract_sha256'])
    review_path = tmp_path / f'review-{corpus}.fernet'
    review_path.write_bytes(Fernet(key).encrypt(b'synthetic review only'))
    manager['review_ciphertext_sha256'] = sha(review_path.read_bytes())
    review = json.loads((PUBLIC_CUSTODY / 'review-aggregate.json').read_text(encoding='utf-8'))
    review.update(bindings=bindings, structure='PASS', semantic_consistency='PASS',
                  independent_review_disagreement_count=0, scenario_disagreement_count=0,
                  review_ciphertext_sha256=sha(review_path.read_bytes()))
    review['scenario_counts'] = {name: sum(row['scenario_id'] == name for row in payload['cases'])
                                 for name in priority + ['unknown']}
    review['axis_counts'] = {name: {state: sum(row['axes'][name]['applicability'] == state
                                              for row in payload['cases'])
                                    for state in ('required', 'not_applicable', 'unknown')}
                             for name in payload['cases'][0]['axes']}
    corpus_hashes = {'corpus:' + item['path']: sha((ROOT / item['path']).read_bytes())
                     for item in ingest_document['sources']}
    review.update(input_hashes_before=corpus_hashes, input_hashes_after=corpus_hashes,
                  input_hashes_unchanged=True)
    annotation_path = tmp_path / f'annotations-{corpus}.fernet'
    token = Fernet(key).encrypt(encoded(payload))
    annotation_path.write_bytes(token)
    manager['annotation_ciphertext_sha256'] = sha(token)
    review['annotation_ciphertext_sha256'] = sha(token)
    manager_path = tmp_path / f'manager-{corpus}.json'
    review_aggregate_path = tmp_path / f'review-aggregate-{corpus}.json'
    manager_path.write_bytes(encoded(manager))
    review_aggregate_path.write_bytes(encoded(review))
    paths = dict(annotation_path=annotation_path, key_file=sealed.key_file, review_path=review_path,
                 manager_path=manager_path, review_aggregate_path=review_aggregate_path,
                 scenario_path=contract_path, ingest_path=ingest_path,
                 source_map_path=source_map_path, schema_path=V2_SCHEMA)
    return Package(dataset, paths, ingest_document)


@pytest.mark.usefixtures('t09_network_guard')
class TestV3ScenarioLoader:
    def test_v3_plan_paths_are_v2_plan_with_only_the_corpus_root_swapped(self):
        """v3 ingest 文档与 v2 plan 逐条同构：只有 path 根不同（name/document_ref 一字不差）。"""
        v2 = json.loads(V2_INGEST.read_text(encoding='utf-8'))['sources']
        v3 = v3_ingest_document()['sources']
        assert len(v2) == len(v3) == 12
        for left, right in zip(v2, v3):
            assert right['path'] == left['path'].replace(CORPUS_PREFIX['v2'], CORPUS_PREFIX['v3'])
            assert (left.get('name'), left.get('document_ref')) == (right.get('name'), right.get('document_ref'))
            assert (ROOT / right['path']).is_file()

    def test_v3_ingest_plan_is_accepted_and_v2_plan_stays_rejected(self, tmp_path, monkeypatch):
        package = _package(tmp_path, monkeypatch, corpus='v3')
        contract = scenario_v3.load_v3_scenario_contract(package.dataset, **package.paths)
        assert contract.scenario_ids == tuple(row[0] for row in scenario.RECIPES)
        assert sum(len(contract.subset(name).cases) for name in contract.scenario_ids) == 30
        plan = contract.ingest_plan('base_b0')
        assert len(plan.sources) == 7
        assert all(Path(source.path).parts[:2] == ('fixtures', 'acceptance-h2v3') for source in plan.sources)
        assert contract.binding('base_b0')['source_map_sha256'] == sha(V3_MAP.read_bytes())
        assert contract.binding('base_b0')['ingest_plan_sha256'] == sha(package.paths['ingest_path'].read_bytes())
        # 回归不变：同一个 v3 包喂给**冻结 loader**（未改）仍按原前缀拒收 v3。
        with pytest.raises(scenario.ScenarioError) as caught:
            scenario.load_scenario_contract(package.dataset, **package.paths)
        assert caught.value.code == 'scenario_corpus_binding_invalid'

    def test_v2_package_is_accepted_by_frozen_loader_and_rejected_by_v3_loader(self, tmp_path, monkeypatch):
        package = _package(tmp_path, monkeypatch, corpus='v2')
        frozen = scenario.load_scenario_contract(package.dataset, **package.paths)
        assert frozen.scenario_ids == tuple(row[0] for row in scenario.RECIPES)
        with pytest.raises(scenario.ScenarioError) as caught:
            scenario_v3.load_v3_scenario_contract(package.dataset, **package.paths)
        assert caught.value.code == 'scenario_corpus_binding_invalid'
        # v3 的允许前缀是闭集：随便一个目录也进不来（不是"放开校验"，是"换成 v3 根"）。
        with pytest.raises(scenario.ScenarioError) as caught:
            scenario_v3.validate_v3_corpus_root(tmp_path)
        assert caught.value.code == 'scenario_corpus_root_invalid'

    def test_v3_body_is_value_identical_to_frozen_loader_on_the_same_v2_package(self, tmp_path, monkeypatch):
        """等价性：同一份 v2 包，两条 loader 的 binding/subset/aggregate 身份逐值相同。"""
        package = _package(tmp_path, monkeypatch, corpus='v2')
        frozen = scenario.load_scenario_contract(package.dataset, **package.paths)
        mirror = scenario_v3._load_contract(package.dataset, corpus_root=scenario_v3.V2_CORPUS_ROOT,
                                            **package.paths)
        assert mirror.scenario_ids == frozen.scenario_ids
        for name in frozen.scenario_ids:
            assert mirror.binding(name) == frozen.binding(name)
            assert mirror.ingest_plan(name).as_dict() == frozen.ingest_plan(name).as_dict()
            left, right = frozen.subset(name), mirror.subset(name)
            assert [case.case_id for case in left.cases] == [case.case_id for case in right.cases]
            assert dict(left.identity) == dict(right.identity)
        assert mirror.safe_summary() == frozen.safe_summary()

    def test_missing_v3_custody_file_fails_closed_without_falling_back_to_v2(self, tmp_path, monkeypatch):
        package = _package(tmp_path, monkeypatch, corpus='v3')
        paths = dict(package.paths)
        paths['scenario_path'] = tmp_path / 'absent-contract.json'
        with pytest.raises(scenario.ScenarioError) as caught:
            scenario_v3.load_v3_scenario_contract(package.dataset, **paths)
        assert caught.value.code == 'scenario_input_unreadable'
        # 默认路径逐条是 v3 件（不是 v2）：缺件靠固定码拒，不靠回落。
        assert scenario_v3.V3_SOURCE_MAP == ROOT / 'docs/evaluation/p2-holdout-v3.source-map.json'
        assert 'H2V3' in str(scenario_v3.V3_INGEST)
        assert scenario_v3.V3_CORPUS_ROOT == (ROOT / 'fixtures/acceptance-h2v3').resolve()


# --------------------------------------------------------------------------- #
# B. source-map 版本分发（v0.1 / v0.2 / 未知）
# --------------------------------------------------------------------------- #


def _case(doc_code: str) -> CaseSpec:
    return CaseSpec(case_id='SYNTHETIC-V3', suite='holdout', split='holdout', stratum='paraphrase',
                    business_date='2026-11-20', question='合成问题', expected_values=('合成答案',),
                    expected_sources=({'doc_code': doc_code, 'locator': {'sheet': 'synthetic', 'row': 7}},))


@pytest.mark.usefixtures('t09_network_guard')
class TestSourceMapDispatch:
    def test_v01_is_delegated_value_for_value(self):
        assert source_map.source_map_schema_version(V2_MAP) == source_map.SCHEMA_V01
        assert source_map.load_source_map(V2_MAP) == drive.load_holdout_source_map(V2_MAP)
        assert set(source_map.load_source_map(V2_MAP)) == {'V03', 'V04', 'V05', 'V06'}
        # 默认路径仍是驱动层默认（v0.1）：分发器不改既有默认语义。
        assert source_map.load_source_map() == drive.load_holdout_source_map()

    def test_v02_declares_all_twelve_codes(self):
        assert source_map.source_map_schema_version(V3_MAP) == source_map.SCHEMA_V02
        mapping = source_map.load_source_map(V3_MAP)
        assert set(mapping) == set(source_map.V02_DOC_CODES) and len(mapping) == 12
        assert mapping['D01'] == {'base_doc_code': 'D01', 'version_number': 2}
        assert mapping['V03'] == {'base_doc_code': 'D01', 'version_number': 1}
        assert mapping['V04'] == {'base_doc_code': 'D01', 'version_number': 3}
        assert mapping['V05'] == {'base_doc_code': 'D01', 'version_number': 4}
        assert mapping['V06'] == {'base_doc_code': 'D02', 'version_number': 2}
        assert mapping['V07'] == {'base_doc_code': 'V07', 'version_number': 1}

    @pytest.mark.parametrize('version', ['p2-holdout-source-map/v9.9', 'p2-holdout-source-map/v0.0',
                                         'v0.2', ''])
    def test_unknown_or_empty_version_fails_closed(self, tmp_path, version):
        target = tmp_path / 'map.json'
        target.write_text(json.dumps({'schema_version': version, 'sources': {}, 'basis': ['synthetic']}),
                          encoding='utf-8')
        with pytest.raises(drive.RunScoreError) as caught:
            source_map.load_source_map(target)
        assert caught.value.code == source_map.ERROR_CODE

    def test_missing_map_fails_closed(self, tmp_path):
        with pytest.raises(drive.RunScoreError) as caught:
            source_map.load_source_map(tmp_path / 'absent.json')
        assert caught.value.code == source_map.ERROR_CODE

    @pytest.mark.parametrize('kind', ['missing_code', 'extra_top_key', 'bad_version_type', 'conflict',
                                      'bad_corpus_sha', 'empty_basis', 'duplicate_key'])
    def test_malformed_v02_fails_closed_with_the_driver_code(self, tmp_path, kind):
        payload = json.loads(V3_MAP.read_text(encoding='utf-8'))
        text = None
        if kind == 'missing_code':
            payload['sources'].pop('V07')
        elif kind == 'extra_top_key':
            payload['extra'] = 1
        elif kind == 'bad_version_type':
            payload['sources']['V05']['version_number'] = True
        elif kind == 'conflict':
            payload['sources']['V05']['version_number'] = 3
        elif kind == 'bad_corpus_sha':
            payload['corpus_ref']['manifest_sha256'] = 'Z' * 64
        elif kind == 'empty_basis':
            payload['basis'] = []
        else:
            text = V3_MAP.read_text(encoding='utf-8').replace(
                '"base_doc_code": "D01"', '"base_doc_code": "D01", "base_doc_code": "D02"', 1)
        target = tmp_path / 'map.json'
        target.write_text(text if text is not None else json.dumps(payload), encoding='utf-8')
        with pytest.raises(drive.RunScoreError) as caught:
            source_map.load_source_map(target)
        assert caught.value.code == source_map.ERROR_CODE

    def test_dispatched_map_is_consumer_compatible_with_the_driver_remap(self):
        v3 = source_map.remap_cases((_case('V05'),), path=V3_MAP)[0]
        assert v3.expected_sources[0]['doc_code'] == 'D01'
        assert v3.expected_sources[0]['locator']['version_number'] == 4
        v1 = source_map.remap_cases((_case('V03'),), source_map=source_map.load_source_map(V2_MAP))[0]
        assert v1.expected_sources[0]['doc_code'] == 'D01'
        assert v1.expected_sources[0]['locator']['version_number'] == 1
        # v0.2 独有码也能被驱动层 remap（V07 映射到自身 v1），形状与 v0.1 返回一致。
        stated = source_map.remap_cases((_case('V07'),), path=V3_MAP)[0]
        assert stated.expected_sources[0]['doc_code'] == 'V07'
        assert stated.expected_sources[0]['locator']['version_number'] == 1


# --------------------------------------------------------------------------- #
# C. per-run business_date 接线（run 绑定 → RagConfig.business_date）
# --------------------------------------------------------------------------- #


PLAN_DATES = {0: ('base_b0', '2026-10-15'), 1: ('base_b0_plus_v01', '2026-07-15'),
              2: ('pre_v05_without_v07', '2026-11-20'), 3: ('post_v05_without_v01', '2026-12-15')}


@pytest.mark.usefixtures('t09_network_guard')
class TestRunBusinessDate:
    def test_declared_dates_equal_the_lifecycle_single_source_of_truth(self):
        rows = run_date.verified_run_dates()
        assert {row.run_index: (row.scenario_id, row.business_date) for row in rows} == PLAN_DATES
        assert len({row.business_date for row in rows}) == 4

    def test_each_run_binds_its_own_date_and_reaches_rag_config(self, tmp_path):
        bindings = run_date.bind_all_runs(dataset_anchor='2026-10-28')
        assert [binding.run_index for binding in bindings] == [0, 1, 2, 3]
        for binding in bindings:
            scenario_id, expected = PLAN_DATES[binding.run_index]
            assert (binding.scenario_id, binding.business_date) == (scenario_id, expected)
            assert run_date.adapter_kwargs(binding) == {'rag_business_date': expected,
                                                        'manifest_business_date': expected}
            config = run_date.product_rag_config(binding, data_dir=tmp_path / f'run-{binding.run_index}')
            assert config.provider_mode == 'offline'
            assert config.business_date == expected

    @pytest.mark.parametrize('run_index', [0, 1, 2, 3])
    def test_started_adapter_reports_the_run_date_from_the_product_config(self, tmp_path, run_index):
        binding = run_date.bind_run(run_index, dataset_anchor='2026-10-28')
        expected = PLAN_DATES[run_index][1]
        adapter = ProductEvalAdapter(tmp_path / f'adapter-{run_index}', trace_enabled=False,
                                     **run_date.adapter_kwargs(binding))
        try:
            asyncio.run(adapter.start())
            assert adapter.rag_business_date == expected
            assert adapter._qa.config.business_date == expected
            assert adapter.manifest_business_date == expected
        finally:
            asyncio.run(adapter.close())

    @pytest.mark.parametrize('run_index,table,code', [
        (4, None, run_date.RUN_UNKNOWN),
        (None, None, run_date.RUN_UNKNOWN),
        (True, None, run_date.RUN_UNKNOWN),
        ('0', None, run_date.RUN_UNKNOWN),
        (0, (run_date.RunDate(0, 'base_b0', None),), run_date.RUN_MISSING),
        (0, (run_date.RunDate(0, 'base_b0', ''),), run_date.RUN_MISSING),
        (0, (run_date.RunDate(0, 'base_b0', '2026-13-01'),), run_date.RUN_INVALID),
        (0, (run_date.RunDate(0, 'base_b0', '2026/10/15'),), run_date.RUN_INVALID),
        (0, (run_date.RunDate(0, 'base_b0', '2026-10-15'), run_date.RunDate(0, 'base_b0', '2026-10-15')),
         run_date.RUN_DUPLICATE),
    ])
    def test_unsupported_bindings_fail_closed_with_fixed_codes(self, run_index, table, code):
        with pytest.raises(run_date.RunDateError) as caught:
            run_date.bind_run(run_index, table=table)
        assert caught.value.code == code

    def test_dataset_anchor_cannot_be_used_as_a_run_date(self, tmp_path):
        with pytest.raises(run_date.RunDateError) as caught:
            run_date.bind_run(0, dataset_anchor='2026-10-15')
        assert caught.value.code == run_date.RUN_ANCHOR_FORBIDDEN
        # adapter 侧同一条边界（它自己的固定码）：把锚点当 run manifest 日期当场拒。
        with pytest.raises(ProductAdapterError) as caught:
            ProductEvalAdapter(tmp_path / 'never-created', rag_business_date='2026-10-15',
                               manifest_business_date='2026-10-28')
        assert caught.value.code == 'adapter_business_date_manifest_mismatch'
        assert not (tmp_path / 'never-created').exists()

    def test_lifecycle_mismatch_and_unreadable_source_fail_closed(self, tmp_path):
        payload = json.loads(run_date.LIFECYCLE_PATH.read_text(encoding='utf-8'))
        drifted = json.loads(json.dumps(payload))
        drifted['coverage_selfcheck']['per_run_dates']['runs'][0]['business_date'] = '2026-10-16'
        drift_path = tmp_path / 'lifecycle-drift.json'
        drift_path.write_text(json.dumps(drifted), encoding='utf-8')
        with pytest.raises(run_date.RunDateError) as caught:
            run_date.verified_run_dates(drift_path)
        assert caught.value.code == run_date.RUN_LIFECYCLE_MISMATCH
        same_day = json.loads(json.dumps(payload))
        same_day['coverage_selfcheck']['per_run_dates']['runs'][1]['business_date'] = '2026-10-15'
        same_path = tmp_path / 'lifecycle-same-day.json'
        same_path.write_text(json.dumps(same_day), encoding='utf-8')
        with pytest.raises(run_date.RunDateError) as caught:
            run_date.verified_run_dates(same_path)
        assert caught.value.code == run_date.RUN_LIFECYCLE_MISMATCH
        with pytest.raises(run_date.RunDateError) as caught:
            run_date.verified_run_dates(tmp_path / 'absent-lifecycle.json')
        assert caught.value.code == run_date.RUN_LIFECYCLE_UNREADABLE

    def test_missing_date_never_defaults_to_today(self, monkeypatch):
        class _NoToday(date):
            calls = 0

            @classmethod
            def today(cls):
                cls.calls += 1
                raise AssertionError('per-run business_date 不得回落到今天')

        monkeypatch.setattr(run_date, 'date', _NoToday)
        bindings = run_date.bind_all_runs(dataset_anchor='2026-10-28')
        assert _NoToday.calls == 0
        assert [binding.business_date for binding in bindings] == [PLAN_DATES[index][1] for index in range(4)]
        with pytest.raises(run_date.RunDateError) as caught:
            run_date.bind_run(0, table=(run_date.RunDate(0, 'base_b0', None),))
        assert caught.value.code == run_date.RUN_MISSING


# --------------------------------------------------------------------------- #
# 正对照：外部探针必须真被拦，且不得借道本机代理
# --------------------------------------------------------------------------- #


def _install_guard(monkeypatch) -> NetworkAttempts:
    """装同一组 primitives（与 ``acceptance.support.netguard`` 同口径，供正对照使用）。"""
    attempts = NetworkAttempts()
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.connect {address!r}', address)
        if is_loopback(address):
            return real_connect(self, address, *args, **kwargs)
        raise NetworkBlocked(f'blocked connect {address!r}')

    def guarded_connect_ex(self, address, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.connect_ex {address!r}', address)
        raise NetworkBlocked(f'blocked connect_ex {address!r}')

    def guarded_create(address, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.create_connection {address!r}', address)
        if is_loopback(address):
            return real_create(address, *args, **kwargs)
        raise NetworkBlocked(f'blocked create_connection {address!r}')

    def guarded_getaddrinfo(host, *args, **kwargs):  # noqa: ANN001
        attempts.add(f'socket.getaddrinfo {host!r}', (host if isinstance(host, str) else '',))
        if is_loopback(host):
            return real_getaddrinfo(host, *args, **kwargs)
        raise NetworkBlocked(f'blocked getaddrinfo {host!r}')

    def guarded_handle_request(self, request):  # noqa: ANN001
        attempts.add(f'httpx {request.url}', (str(request.url.host),))
        raise NetworkBlocked(f'blocked http {request.url}')

    async def guarded_handle_async_request(self, request):  # noqa: ANN001
        attempts.add(f'httpx-async {request.url}', (str(request.url.host),))
        raise NetworkBlocked(f'blocked http {request.url}')

    monkeypatch.setattr(socket.socket, 'connect', guarded_connect, raising=True)
    monkeypatch.setattr(socket.socket, 'connect_ex', guarded_connect_ex, raising=True)
    monkeypatch.setattr(socket, 'create_connection', guarded_create, raising=True)
    monkeypatch.setattr(socket, 'getaddrinfo', guarded_getaddrinfo, raising=True)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', guarded_handle_request, raising=True)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request',
                        guarded_handle_async_request, raising=True)
    return attempts


def test_zz_outbound_positive_control():
    """DNS / 直连 / urllib / httpx 四类外部探针全被拦，且拦的是外部目标而不是本机代理。

    本机代理是回环（env + 注册表都指向 ``127.0.0.1:7897``），netguard 对回环放行；若探针沿用
    环境/注册表代理，它会先连 127.0.0.1:7897 再由代理真正出网——正是历史漏点。所以这里：
    先证明 env 代理已不可达（autouse fixture），urllib 探针再用 ``ProxyHandler({})`` 显式绕过
    注册表代理，最后断言记录到的 4 条尝试全部指向外部主机。
    """
    env_proxies = urllib.request.getproxies_environment()
    assert not (_PROXY_SCHEMES & set(env_proxies)), env_proxies
    assert is_loopback(('127.0.0.1', 7897)), '本机代理是回环，netguard 会放行——必须显式绕过'

    with pytest.MonkeyPatch.context() as patch:
        attempts = _install_guard(patch)
        with pytest.raises(NetworkBlocked):
            socket.create_connection(('example.com', 80), timeout=2)
        with pytest.raises(NetworkBlocked):
            sock = socket.socket()
            try:
                sock.connect(('192.0.2.1', 80))  # TEST-NET-1：不经 DNS 直连也要被拦
            finally:
                sock.close()
        with pytest.raises(NetworkBlocked):
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            opener.open('http://example.com/', timeout=2)
        with pytest.raises(NetworkBlocked):
            httpx.get('http://example.com/', timeout=2)
        snapshot = attempts.snapshot()

    assert len(snapshot['external']) == 4, snapshot
    assert snapshot['local'] == [], snapshot
    joined = ' '.join(snapshot['external'])
    assert 'example.com' in joined and '192.0.2.1' in joined
    assert '127.0.0.1' not in joined and 'localhost' not in joined and '7897' not in joined
    assert AMBIENT_REGISTRY_PROXY, '记录本机代理事实（不假装没有代理）'
