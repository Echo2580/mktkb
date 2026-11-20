"""v3 source-map ``/v0.2`` 的**计分侧接线**（新增文件；``p2_score_run.py`` 一字未改）。

为什么需要这个文件
-----------------
``p2_score_run`` 的计分入口（``holdout_case_scores_from_rows``）与驱动层
（``p2_runner._holdout_score_marks``）都在函数体里取 map：

    from .p2_score_run import ... load_holdout_source_map ...
    source_map = load_holdout_source_map()

而 ``load_holdout_source_map`` 只接受 ``p2-holdout-source-map/v0.1``（v3 的 map 是 ``/v0.2``：
12 码全声明 + ``lifecycle_ref`` + ``corpus_ref``）。本包不许改那两个模块的语义，因此接线放在
**调用侧**：``dispatched_scoring_map`` 在受控作用域内把 ``p2_score_run.load_holdout_source_map``
换成 ``p2_holdout_source_map.load_source_map``（版本分发器），退出即还原。

这是**语义等价替换**，不是放宽：

- ``/v0.1``：分发器逐值委托 ``p2_score_run.load_holdout_source_map``（一行语义都不复制）；
  因此 v2 路径替换前后返回值逐值相同（``assert_v01_identity`` 可机检）。
- ``/v0.2``：分发器自己校验，失败仍抛**同一个固定码** ``holdout_document_code_unmapped``；
  调用方既有的 fail-closed 分支不用改。
- 未知版本：固定码拒绝（不猜、不降级成 v0.1）。

作用域是**显式**的：只有 ``with dispatched_scoring_map(...)`` 内才生效；作用域外
``p2_score_run`` 的行为逐字不变（含默认路径）。调用被记录在 ``ScoringMapDispatch.calls`` 里，
所以"驱动层这次真的走了分发器"是**可观测事实**，不是声明。

``assert_remap_closure`` 是配套的消费者兼容性证明：用分发后的 map 折过的 case，再被驱动层
**自身默认 map** 折一次必须逐值不变。不成立就固定码拒绝——这样"先接线、后又被驱动层默认
map 二次改写"这条静默破坏路径会被当场拦下。
"""
from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import p2_score_run as _driver
from .p2_holdout_source_map import (
    SCHEMA_V01,
    SCHEMA_V02,
    V02_DOC_CODES,
    load_source_map,
)

ERROR_CODE = 'holdout_source_map_dispatch_invalid'
"""接线自身的固定码（不新增评分侧码：评分失败仍由驱动层的既有序号表达）。"""

__all__ = [
    'ERROR_CODE',
    'Dispatched',
    'ScoringMapDispatch',
    'assert_remap_closure',
    'assert_v01_identity',
    'dispatch_summary',
    'dispatched_scoring_map',
    'driver_default_source_map',
    'source_map_for_scoring',
]


class ScoringMapError(ValueError):
    """接线失败：固定码 + 只含码/计数的 detail（不回显 case 内容）。"""

    def __init__(self, code: str, detail: str = '') -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(self.code if not detail else f'{self.code}: {detail}')


@dataclasses.dataclass(frozen=True)
class Dispatched:
    """一次分发的结果（只含身份与计数，不含任何 case/来源内容）。"""

    path: str | None
    schema_version: str
    code_count: int
    mapping: Mapping[str, Mapping[str, Any]] = dataclasses.field(repr=False)


def source_map_for_scoring(path: Path | str | None = None) -> Dispatched:
    """按版本分发取 map（``path=None`` = 驱动层默认路径，行为不变）。"""
    target = None if path is None else str(path)
    try:
        version = _driver_version(target)
        mapping = load_source_map(None if target is None else target)
    except Exception as exc:  # noqa: BLE001 - 统一折成接线固定码，保留原始原因类型名
        if getattr(exc, 'code', None) == 'holdout_document_code_unmapped':
            raise
        raise ScoringMapError(ERROR_CODE, type(exc).__name__) from None
    if not isinstance(mapping, dict) or not mapping:
        raise ScoringMapError(ERROR_CODE, 'empty_map')
    return Dispatched(path=target, schema_version=version, code_count=len(mapping), mapping=mapping)


def _driver_version(path: str | None) -> str:
    """只读版本号：v0.1 走驱动层自己的校验，v0.2 走分发器，其余不猜。"""
    from .p2_holdout_source_map import source_map_schema_version

    return source_map_schema_version(None if path is None else path)


def driver_default_source_map() -> dict[str, dict[str, Any]]:
    """驱动层默认 map（只读；用于 v0.1 等价性与二次折叠闭包证明）。"""
    return _driver.load_holdout_source_map()


def assert_v01_identity() -> str:
    """``/v0.1`` 上分发器与驱动层逐值相同（否则接线就不是"等价替换"）。"""
    left = load_source_map(None)
    right = driver_default_source_map()
    if left != right:
        raise ScoringMapError(ERROR_CODE, 'v01_not_identical')
    if _driver_version(None) != SCHEMA_V01:
        raise ScoringMapError(ERROR_CODE, 'driver_default_not_v01')
    return SCHEMA_V01


def assert_remap_closure(cases: Sequence[Any], mapping: Mapping[str, Mapping[str, Any]]) -> int:
    """用**驱动层自身默认 map** 再折一次必须逐值不变；返回核对题数。"""
    default = driver_default_source_map()
    for case in cases:
        once = _driver.remap_holdout_case(case, mapping)
        twice = _driver.remap_holdout_case(once, default)
        if twice != once:
            raise ScoringMapError(ERROR_CODE, 'double_remap_changed_case')
    return len(cases)


@dataclasses.dataclass
class ScoringMapDispatch:
    """受控替换的可观测记录：驱动层每次取 map 都记一条。"""

    path: str | None
    version: str
    code_count: int
    calls: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def served(self) -> int:
        return len(self.calls)

    def public(self) -> dict[str, Any]:
        return {
            'path': self.path,
            'schema_version': self.version,
            'code_count': self.code_count,
            'resolutions': self.served(),
            'served_by_dispatch': sum(1 for row in self.calls if row.get('dispatch')),
        }


@contextmanager
def dispatched_scoring_map(path: Path | str | None = None) -> Iterator[ScoringMapDispatch]:
    """在作用域内让驱动层的取 map 路径走版本分发器；退出即还原（异常也还原）。

    ``path=None`` 表示"驱动层原本会用的默认路径"，此时分发器对 v0.1 逐值委托、对 v0.2 自己校验。
    显式传 v3 map 时，驱动层即使传 ``None`` 也会被导向该文件（这正是 v3 计分接线所需）。
    """
    pinned = None if path is None else str(path)
    dispatched = source_map_for_scoring(pinned)
    record = ScoringMapDispatch(path=pinned, version=dispatched.schema_version,
                                code_count=dispatched.code_count)
    original = _driver.load_holdout_source_map
    if getattr(original, '_p2_v3_dispatch', False):
        raise ScoringMapError(ERROR_CODE, 'already_dispatched')

    def resolve(requested: Path | str | None = None) -> dict[str, dict[str, Any]]:
        # 驱动层传了显式路径就尊重它（当前调用点都不传），否则用本作用域钉住的 map。
        target = requested if requested is not None else pinned
        mapping = load_source_map(None if target is None else target)
        record.calls.append({
            'requested': None if requested is None else str(requested),
            'served': 'pinned' if requested is None else 'requested',
            'dispatch': True,
            'schema_version': _driver_version(None if target is None else str(target)),
            'code_count': len(mapping),
        })
        return mapping

    resolve._p2_v3_dispatch = True  # type: ignore[attr-defined]
    _driver.load_holdout_source_map = resolve  # type: ignore[assignment]
    try:
        yield record
    finally:
        _driver.load_holdout_source_map = original  # type: ignore[assignment]


def dispatch_summary(record: ScoringMapDispatch, *, overlap: Iterable[str] | None = None) -> dict[str, Any]:
    """给产物用的公开回执：v0.2 声明 12 码 vs 驱动层默认只声明 4 码（只报计数）。"""
    default_codes = set(driver_default_source_map())
    payload = record.public()
    payload['driver_default_code_count'] = len(default_codes)
    payload['v02_declared_code_count'] = len(V02_DOC_CODES)
    payload['v02_only_codes'] = len(set(V02_DOC_CODES) - default_codes)
    if overlap is not None:
        payload['disagreement_codes'] = len(set(overlap) - default_codes)
    payload['driver_default_schema_version'] = SCHEMA_V01
    payload['v02_schema_version'] = SCHEMA_V02
    return payload
