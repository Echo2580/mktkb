"""H2 holdout source-map 版本分发（新增文件；``p2_score_run.py`` 一字未改）。

背景
----
``p2_score_run.load_holdout_source_map`` 只接受 ``p2-holdout-source-map/v0.1``（该文件
:498-499 的 schema 等价），而 v3 的 source map 是 ``/v0.2``（多 8 个码 + ``lifecycle_ref``
+ ``corpus_ref``）。计分侧需要一个**按版本分发**的入口，但不许改驱动层的既有语义，因此：

- ``/v0.1``：逐值委托 ``p2_score_run.load_holdout_source_map``（一行语义都不复制，
  连"重复键即拒"和固定码都沿用那边的实现）；
- ``/v0.2``：本文件自己校验（字段集/12 码全声明/身份双射/引用块形状），失败仍抛
  **同一个固定码** ``holdout_document_code_unmapped``——不新增码，调用方的 fail-closed
  分支不变；
- 未知版本：固定码拒绝（不猜、不降级成 v0.1）。

返回值形状与驱动层一致：``{code: {"base_doc_code": str, "version_number": int}}``，
可直接喂给 ``p2_score_run.remap_holdout_case``（见 ``remap_cases``）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .p2_score_run import (
    DEFAULT_HOLDOUT_SOURCE_MAP,
    RunScoreError,
    load_holdout_source_map,
    remap_holdout_case,
)

SCHEMA_V01 = 'p2-holdout-source-map/v0.1'
SCHEMA_V02 = 'p2-holdout-source-map/v0.2'
SUPPORTED_SCHEMA_VERSIONS = (SCHEMA_V01, SCHEMA_V02)

V02_TOP_KEYS = frozenset({'schema_version', 'sources', 'basis', 'lifecycle_ref', 'corpus_ref'})
"""v0.2 的严格 5 键（v0.1 只有 3 键：schema_version/sources/basis）。"""

V02_DOC_CODES = ('D01', 'D02', 'D03', 'D04', 'D05', 'D06', 'V01', 'V03', 'V04', 'V05', 'V06', 'V07')
"""v0.2 必须声明的 12 个码（与 v3 语料的 12 个被 ingest 源逐条双射）。"""

_SOURCE_KEYS = frozenset({'base_doc_code', 'version_number'})
_LIFECYCLE_REF_KEYS = frozenset({'path', 'sha256', 'schema_version'})
_CORPUS_REF_KEYS = frozenset({'root', 'manifest_sha256'})
_CODE_RE = re.compile(r'[DV][0-9]{2}')
#: 槽位根码：v2 的 4 个码全部折回 D01/D02，但 v0.2 起独立文档（V01/V07）的根码就是它自己，
#: 因此这里必须接受 D/V 两种前缀（v3 manifest 的 ``base_doc_code`` 逐条也这么写）。
_BASE_RE = re.compile(r'[DV][0-9]{2}')
_SHA_RE = re.compile(r'[0-9a-f]{64}')

ERROR_CODE = 'holdout_document_code_unmapped'
"""沿用驱动层固定码：v3 侧**不新增**错误码，调用方既有 fail-closed 分支无需改。"""

__all__ = [
    'ERROR_CODE',
    'SCHEMA_V01',
    'SCHEMA_V02',
    'SUPPORTED_SCHEMA_VERSIONS',
    'V02_DOC_CODES',
    'load_source_map',
    'remap_cases',
    'source_map_schema_version',
]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """与驱动层同口径：重复键即拒（不静默后者覆盖前者）。"""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def source_map_schema_version(path: Path | str | None = None) -> str:
    """只读 ``schema_version``（分发用）；文件不可读/非对象/缺字段一律固定码。"""
    try:
        payload = json.loads(Path(path or DEFAULT_HOLDOUT_SOURCE_MAP).read_text(encoding='utf-8'),
                             object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError, TypeError):
        raise RunScoreError(ERROR_CODE, 'H2 source map missing or not valid JSON') from None
    if not isinstance(payload, dict) or not isinstance(payload.get('schema_version'), str):
        raise RunScoreError(ERROR_CODE, 'H2 source map schema_version missing')
    return payload['schema_version']


def _validate_v02(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """v0.2 校验：严格 5 键、12 码全声明、(base_doc_code, version_number) 身份双射。"""
    if set(payload) != V02_TOP_KEYS:
        raise ValueError('schema')
    basis = payload['basis']
    if (not isinstance(basis, list) or not basis
            or not all(isinstance(item, str) and item.strip() for item in basis)):
        raise ValueError('basis')
    sources = payload['sources']
    if not isinstance(sources, dict) or set(sources) != set(V02_DOC_CODES):
        raise ValueError('sources')
    identities: set[tuple[str, int]] = set()
    for code, item in sources.items():
        if (not isinstance(code, str) or _CODE_RE.fullmatch(code) is None
                or not isinstance(item, dict) or set(item) != _SOURCE_KEYS
                or not isinstance(item['base_doc_code'], str)
                or _BASE_RE.fullmatch(item['base_doc_code']) is None
                or type(item['version_number']) is not int or item['version_number'] < 1):
            raise ValueError('source schema')
        identity = (item['base_doc_code'], item['version_number'])
        if identity in identities:
            raise ValueError('conflicting identity')
        identities.add(identity)
    lifecycle_ref = payload['lifecycle_ref']
    if (not isinstance(lifecycle_ref, dict) or set(lifecycle_ref) != _LIFECYCLE_REF_KEYS
            or not isinstance(lifecycle_ref['path'], str) or not lifecycle_ref['path'].strip()
            or not isinstance(lifecycle_ref['sha256'], str) or _SHA_RE.fullmatch(lifecycle_ref['sha256']) is None
            or not isinstance(lifecycle_ref['schema_version'], str) or not lifecycle_ref['schema_version'].strip()):
        raise ValueError('lifecycle_ref')
    corpus_ref = payload['corpus_ref']
    if (not isinstance(corpus_ref, dict) or set(corpus_ref) != _CORPUS_REF_KEYS
            or not isinstance(corpus_ref['root'], str) or not corpus_ref['root'].strip()
            or not isinstance(corpus_ref['manifest_sha256'], str)
            or _SHA_RE.fullmatch(corpus_ref['manifest_sha256']) is None):
        raise ValueError('corpus_ref')
    return {code: {'base_doc_code': item['base_doc_code'], 'version_number': item['version_number']}
            for code, item in sources.items()}


def load_source_map(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """按 ``schema_version`` 分发；未知版本固定码拒绝（不猜、不降级）。"""
    target = Path(path) if path is not None else DEFAULT_HOLDOUT_SOURCE_MAP
    version = source_map_schema_version(target)
    if version == SCHEMA_V01:
        # 逐值委托：v0.1 的语义（含重复键、字段集、冲突身份、固定码）只在驱动层有一份。
        return load_holdout_source_map(target)
    if version == SCHEMA_V02:
        try:
            payload = json.loads(target.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
            if not isinstance(payload, dict):
                raise ValueError('schema')
            return _validate_v02(payload)
        except (OSError, UnicodeError, ValueError, TypeError):
            raise RunScoreError(ERROR_CODE, 'H2 source map invalid or conflicting') from None
    raise RunScoreError(ERROR_CODE, f'H2 source map schema_version unsupported: {version}')


def remap_cases(cases: Iterable[Any], *, source_map: Mapping[str, Mapping[str, Any]] | None = None,
                path: Path | str | None = None) -> tuple[Any, ...]:
    """把 cases 的来源引用按（分发后的）source map 折回基槽；默认整表由 ``load_source_map`` 给出。"""
    if source_map is None:
        source_map = load_source_map(path)
    return tuple(remap_holdout_case(case, source_map) for case in cases)
