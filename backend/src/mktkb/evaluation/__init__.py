"""评测数据层（P0 第 7 包）：Case 契约、稳定引用解析与数据集版本。

只做数据契约与 gold 解析；runner / scorer / gate 在后续包实现。
"""

from .dataset import (
    CASE_SCHEMA_VERSION,
    CaseSpec,
    cases_to_jsonl,
    dataset_version,
    load_cases,
    validate_case,
    write_cases,
)
from .gold import GoldUnresolved, ResolvedGold, ResolvedSource, resolve_case, resolve_gold

__all__ = [
    "CASE_SCHEMA_VERSION",
    "CaseSpec",
    "GoldUnresolved",
    "ResolvedGold",
    "ResolvedSource",
    "cases_to_jsonl",
    "dataset_version",
    "load_cases",
    "resolve_case",
    "resolve_gold",
    "validate_case",
    "write_cases",
]
