"""闸门数值的最小不变量校验。

只回答三个问题：是不是数字、是不是有限、是否满足正数/非负/整数/上限。
不引入数值框架，也不接受 float 比较来“碰巧”拒绝 NaN/Infinity。
"""

from __future__ import annotations

import math
from typing import Any


class NumericInvalid(ValueError):
    """数值不是约定的有限正数/非负数/整数。"""


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NumericInvalid(f"{label} 必须是数字（拒绝 bool/字符串/None）")
    number = float(value)
    if not math.isfinite(number):
        raise NumericInvalid(f"{label} 必须是有限数字（拒绝 NaN/±Infinity）")
    return number


def finite_positive(value: Any, label: str) -> float:
    """有限且 > 0；NaN/±Infinity/bool/非数字/<=0 一律拒绝。"""
    number = _finite(value, label)
    if number <= 0:
        raise NumericInvalid(f"{label} 必须为正数")
    return number


def finite_non_negative(value: Any, label: str) -> float:
    """有限且 >= 0；NaN/±Infinity/bool/非数字/<0 一律拒绝。"""
    number = _finite(value, label)
    if number < 0:
        raise NumericInvalid(f"{label} 不得为负数")
    return number


def positive_int(value: Any, label: str, *, maximum: int | None = None) -> int:
    """正整数；bool 不算整数；可给出闭区间上限。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise NumericInvalid(f"{label} 必须是整数")
    if value <= 0:
        raise NumericInvalid(f"{label} 必须为正整数")
    if maximum is not None and value > maximum:
        raise NumericInvalid(f"{label} 不得超过 {maximum}")
    return value


def non_negative_int(value: Any, label: str) -> int:
    """非负整数；bool 不算整数。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise NumericInvalid(f"{label} 必须是非负整数")
    if value < 0:
        raise NumericInvalid(f"{label} 不得为负数")
    return value


__all__ = [
    "NumericInvalid",
    "finite_non_negative",
    "finite_positive",
    "non_negative_int",
    "positive_int",
]
