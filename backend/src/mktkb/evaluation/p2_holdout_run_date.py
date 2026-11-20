"""per-run ``business_date`` 接线（新增文件；不动产品侧、不做请求级注入）。

产品事实（``docs/reports/OBS-EVAL/P2/T207-QUALITY-REPAIR/product-date-recon.md``）
--------------------------------------------------------------------------------
``business_date`` **只有进程级配置**（``Settings.rag_business_date`` →
``resolve_rag_config(business_date=...)`` → ``RagConfig.business_date`` →
``QaEngine``），API 的提问 schema 没有 as_of/business_date 入参。因此"每 run 一个日期"
只能在**运行绑定层**表达：一个 run 起一个进程、一个进程一个日期。本模块就是那个绑定层，
**不做**请求级注入、也**不**改产品 schema。

取值来源
--------
四个日期不是本文件自造的常量：唯一真相源是 ``docs/evaluation/p2-source-lifecycle-v1.json``
（L1）的 ``coverage_selfcheck.per_run_dates.runs[]``（``run_index`` / ``scenario_id`` /
``business_date``）。``RUN_DATES`` 只是**声明表**，``verified_run_dates()`` 会逐值对账；
不一致即固定码拒绝。数据集 manifest 的 ``business_date``（``2026-10-28``）只是**设计
自检锚点**，把它当 run 日属回填（计划 §13 #8 C4 禁止）⇒ ``run_business_date_anchor_forbidden``。

fail-closed 口径
----------------
缺值/未知 run/非法日期/重复 run/与 L1 不一致/用了锚点日 —— 全部抛 ``RunDateError``
（固定码，错误文本只含码，不回显日期值）。**任何分支都不默认取今天**：本模块不 import
``date.today``，``bind_run`` 的每个返回路径都以表里的显式值为准。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[4]
LIFECYCLE_PATH = ROOT / 'docs/evaluation/p2-source-lifecycle-v1.json'
"""per-run 日期的唯一真相源（L1）。"""

RUN_UNKNOWN = 'run_business_date_run_unknown'
RUN_MISSING = 'run_business_date_missing'
RUN_INVALID = 'run_business_date_invalid'
RUN_DUPLICATE = 'run_business_date_duplicate'
RUN_LIFECYCLE_MISMATCH = 'run_business_date_lifecycle_mismatch'
RUN_LIFECYCLE_UNREADABLE = 'run_business_date_lifecycle_unreadable'
RUN_ANCHOR_FORBIDDEN = 'run_business_date_anchor_forbidden'
RUN_CONFIG_DROPPED = 'run_business_date_config_dropped'

_ISO_RE = re.compile(r'\d{4}-\d{2}-\d{2}')

__all__ = [
    'LIFECYCLE_PATH',
    'RUN_ANCHOR_FORBIDDEN',
    'RUN_CONFIG_DROPPED',
    'RUN_DATES',
    'RUN_DUPLICATE',
    'RUN_INVALID',
    'RUN_LIFECYCLE_MISMATCH',
    'RUN_LIFECYCLE_UNREADABLE',
    'RUN_MISSING',
    'RUN_UNKNOWN',
    'RunBinding',
    'RunDate',
    'RunDateError',
    'adapter_kwargs',
    'bind_all_runs',
    'bind_run',
    'checked_business_date',
    'load_lifecycle_run_dates',
    'product_rag_config',
    'verified_run_dates',
]


class RunDateError(ValueError):
    """固定码拒绝：不把日期值或外部字段写进错误文本。"""

    def __init__(self, code: str) -> None:
        self.code = str(code)
        super().__init__(self.code)


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise RunDateError(code)


def checked_business_date(value: Any) -> str:
    """只接受真实日历日期的 ``YYYY-MM-DD``；``None``/空串 → missing，其余非法 → invalid。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise RunDateError(RUN_MISSING)
    if not isinstance(value, str):
        raise RunDateError(RUN_INVALID)
    text = value.strip()
    if _ISO_RE.fullmatch(text) is None:
        raise RunDateError(RUN_INVALID)
    try:
        date.fromisoformat(text)
    except ValueError:
        raise RunDateError(RUN_INVALID) from None
    return text


@dataclass(frozen=True)
class RunDate:
    """一个 run 的声明日期（``run_index`` 与 4 个 scenario 一一对应）。"""

    run_index: int
    scenario_id: str
    business_date: str


@dataclass(frozen=True)
class RunBinding:
    """一个 run 的运行绑定：产品实际日期 = 该 run 的 run-manifest 聚合日期。"""

    run_index: int
    scenario_id: str
    business_date: str

    @property
    def rag_business_date(self) -> str:
        return self.business_date

    @property
    def manifest_business_date(self) -> str:
        """run manifest 的 ``business_date``（``p2_runner.py:2376-2383`` 由 cases 聚合）。"""
        return self.business_date


RUN_DATES: tuple[RunDate, ...] = (
    RunDate(0, 'base_b0', '2026-10-15'),
    RunDate(1, 'base_b0_plus_v01', '2026-07-15'),
    RunDate(2, 'pre_v05_without_v07', '2026-11-20'),
    RunDate(3, 'post_v05_without_v01', '2026-12-15'),
)
"""声明表（计划 §7.2 的 4 个 run 日期）；必须与 L1 ``per_run_dates.runs[]`` 逐值相等。"""


def _table(table: Iterable[RunDate] | None) -> tuple[RunDate, ...]:
    """规范化声明表：逐条验日期、拒绝重复 run_index。"""
    rows = tuple(RUN_DATES if table is None else table)
    seen: set[int] = set()
    for row in rows:
        _require(isinstance(row, RunDate), RUN_INVALID)
        _require(type(row.run_index) is int, RUN_UNKNOWN)
        _require(row.run_index not in seen, RUN_DUPLICATE)
        seen.add(row.run_index)
        checked_business_date(row.business_date)
    return rows


def _row(run_index: Any, table: Iterable[RunDate] | None) -> RunDate:
    _require(type(run_index) is int, RUN_UNKNOWN)
    rows = _table(table)
    for row in rows:
        if row.run_index == run_index:
            return row
    raise RunDateError(RUN_UNKNOWN)


def load_lifecycle_run_dates(lifecycle_path: Path | str = LIFECYCLE_PATH) -> tuple[RunDate, ...]:
    """从 L1 逐值读取 4 个 run 的日期（唯一真相源）；读不到/形状不对即固定码。"""
    try:
        payload = json.loads(Path(lifecycle_path).read_text(encoding='utf-8'))
        runs = payload['coverage_selfcheck']['per_run_dates']['runs']
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise RunDateError(RUN_LIFECYCLE_UNREADABLE) from None
    if not isinstance(runs, list):
        raise RunDateError(RUN_LIFECYCLE_UNREADABLE)
    rows: list[RunDate] = []
    for item in runs:
        if not isinstance(item, Mapping) or type(item.get('run_index')) is not int:
            raise RunDateError(RUN_LIFECYCLE_UNREADABLE)
        rows.append(RunDate(item['run_index'], str(item.get('scenario_id') or ''),
                            checked_business_date(item.get('business_date'))))
    return tuple(rows)


def verified_run_dates(lifecycle_path: Path | str = LIFECYCLE_PATH,
                       *, table: Iterable[RunDate] | None = None) -> tuple[RunDate, ...]:
    """声明表 vs L1 逐值对账（run_index/scenario_id/business_date 三元组集合相等）。"""
    declared = _table(table)
    expected = load_lifecycle_run_dates(lifecycle_path)
    left = {(row.run_index, row.scenario_id, row.business_date) for row in declared}
    right = {(row.run_index, row.scenario_id, row.business_date) for row in expected}
    _require(left == right, RUN_LIFECYCLE_MISMATCH)
    # 只做了集合比较不够：四个 run 的日期必须两两不同（否则等同单一全局日期）。
    _require(len({row.business_date for row in declared}) == len(declared), RUN_LIFECYCLE_MISMATCH)
    return declared


def bind_run(run_index: Any, *, table: Iterable[RunDate] | None = None,
             dataset_anchor: str | None = None) -> RunBinding:
    """把一个 run 绑到它自己的 ``business_date``；缺值不回落、不取今天。"""
    row = _row(run_index, table)
    value = checked_business_date(row.business_date)
    if dataset_anchor is not None:
        # 数据集 manifest 的 business_date 只是设计自检锚点；当成 run 日 = 回填（C4 禁止）。
        _require(value != checked_business_date(dataset_anchor), RUN_ANCHOR_FORBIDDEN)
    return RunBinding(run_index=row.run_index, scenario_id=row.scenario_id, business_date=value)


def bind_all_runs(*, lifecycle_path: Path | str = LIFECYCLE_PATH,
                  dataset_anchor: str | None = None,
                  table: Iterable[RunDate] | None = None) -> tuple[RunBinding, ...]:
    """4 个 run 各一个绑定，且先与 L1 对账（默认对账，不能靠调用方记得）。"""
    rows = verified_run_dates(lifecycle_path, table=table)
    return tuple(bind_run(row.run_index, table=rows, dataset_anchor=dataset_anchor)
                 for row in sorted(rows, key=lambda item: item.run_index))


def adapter_kwargs(binding: RunBinding) -> dict[str, str]:
    """喂给 ``ProductEvalAdapter`` 的两个显式入参（产品实际日期 + run manifest 聚合日期）。

    两者相等是**设计意图**（R-LC-5：注解 ``as_of``、``CaseSpec.business_date``、产品实际
    ``rag_business_date`` 三者逐字相等）；adapter 侧还有自己的固定码
    （``adapter_business_date_*``）复核，本函数不替代那层。
    """
    _require(isinstance(binding, RunBinding), RUN_UNKNOWN)
    return {'rag_business_date': binding.rag_business_date,
            'manifest_business_date': binding.manifest_business_date}


def product_rag_config(binding: RunBinding, *, data_dir: Path | str,
                       page_size: int = 10, top_k: int = 8) -> Any:
    """走产品自己的配置装配（``main.py:85-91`` 同一个函数）并断言日期真的进了 RagConfig。

    参数默认值取自 ``Settings``（``config.py:106-109``：offline / page_size=10 / top_k=8）；
    ``provider_mode`` 固定 ``offline``：本函数只做配置装配，不构造任何真实 provider。
    """
    _require(isinstance(binding, RunBinding), RUN_UNKNOWN)
    from ..qa.service import resolve_rag_config

    config, _budget = resolve_rag_config(
        data_dir=Path(data_dir),
        provider_mode='offline',
        page_size=int(page_size),
        top_k=int(top_k),
        business_date=binding.rag_business_date,
    )
    _require(getattr(config, 'business_date', None) == binding.business_date, RUN_CONFIG_DROPPED)
    return config
