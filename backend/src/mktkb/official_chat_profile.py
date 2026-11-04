"""官方 DeepSeek chat profile 的唯一、不可弱化下界。

产品入口（``providers.build_gateway``、``qa.resolve_rag_config``、实际 rag-chat
构造）都必须经过这里；GO/env 相互一致只证明“配置自洽”，不能证明“官方 profile”。
当前实际支持的官方版本：DeepSeek ``deepseek-flash`` / ``DeepSeek-V4.1-Flash-1017``。

下界（低于任一值即拒绝）：
- reserve_profile = model_context_ceiling；
- context ceiling >= 1,048,576；
- cache-miss 输入价 >= 2 元/百万 token；
- 输出价 >= 8 元/百万 token；
- 非思考（thinking=disabled）；
- 输出 cap = 800（官方上界与实际 max_tokens 都是）。

高于下界的保守配置允许，但预留金额必须按实际值计算，不能低于官方下界。
未知 model/host/profile 一律拒绝，不因为 env 与 GO 相等而视为已支持。
"""

from __future__ import annotations

import math
from typing import Any

RESERVE_PROFILE = "model_context_ceiling"
OFFICIAL_CONTEXT_CEILING_TOKENS = 1_048_576
OFFICIAL_INPUT_PRICE_PER_MILLION_CNY = 2.0
OFFICIAL_OUTPUT_PRICE_PER_MILLION_CNY = 8.0
OFFICIAL_MAX_OUTPUT_TOKENS = 800
OFFICIAL_CHAT_MODEL_NAMES = frozenset({"deepseek-flash", "deepseek-v4.1-flash-1017"})
OFFICIAL_CHAT_HOSTS = frozenset({"api.deepseek.com"})


class OfficialChatProfileError(ValueError):
    """当前配置不满足官方 chat profile 的不可弱化下界。"""


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OfficialChatProfileError(f"{label} 必须是正整数")
    return value


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise OfficialChatProfileError(f"{label} 必须是有限数字")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise OfficialChatProfileError(f"{label} 必须是有限数字") from None
    if not math.isfinite(number):
        raise OfficialChatProfileError(f"{label} 必须是有限数字")
    return number


def assert_official_chat_pricing_floor(
    *,
    reserve_profile: Any,
    context_ceiling_tokens: Any,
    input_price_per_million_cny: Any,
    output_price_per_million_cny: Any,
    max_output_tokens: Any,
) -> None:
    """只校验不依赖 model/host 的官方数值下界。"""
    if str(reserve_profile or "").strip() != RESERVE_PROFILE:
        raise OfficialChatProfileError(f"chat 只允许 {RESERVE_PROFILE} 官方保守 profile")
    ceiling = _positive_int(context_ceiling_tokens, "context_ceiling_tokens")
    if ceiling < OFFICIAL_CONTEXT_CEILING_TOKENS:
        raise OfficialChatProfileError(
            f"context ceiling {ceiling} 低于官方下界 {OFFICIAL_CONTEXT_CEILING_TOKENS}"
        )
    input_price = _finite_number(input_price_per_million_cny, "input_price_per_million_cny")
    if input_price + 1e-12 < OFFICIAL_INPUT_PRICE_PER_MILLION_CNY:
        raise OfficialChatProfileError(
            f"cache-miss 输入价 {input_price:g} 低于官方下界 {OFFICIAL_INPUT_PRICE_PER_MILLION_CNY:g} 元/百万"
        )
    output_price = _finite_number(output_price_per_million_cny, "output_price_per_million_cny")
    if output_price + 1e-12 < OFFICIAL_OUTPUT_PRICE_PER_MILLION_CNY:
        raise OfficialChatProfileError(
            f"输出价 {output_price:g} 低于官方下界 {OFFICIAL_OUTPUT_PRICE_PER_MILLION_CNY:g} 元/百万"
        )
    if _positive_int(max_output_tokens, "max_output_tokens") != OFFICIAL_MAX_OUTPUT_TOKENS:
        raise OfficialChatProfileError(
            f"model_context_ceiling 要求输出上界固定为 {OFFICIAL_MAX_OUTPUT_TOKENS}"
        )


def assert_official_chat_profile(
    *,
    model: Any,
    base_url_host: Any,
    thinking: Any,
    reserve_profile: Any,
    context_ceiling_tokens: Any,
    input_price_per_million_cny: Any,
    output_price_per_million_cny: Any,
    max_output_tokens: Any,
    chat_max_output_tokens: Any | None = None,
) -> None:
    """产品入口的完整官方 profile 校验（model/host/thinking + 数值下界）。"""
    model_name = str(model or "").strip().lower()
    if model_name not in OFFICIAL_CHAT_MODEL_NAMES:
        raise OfficialChatProfileError(
            f"未知 chat model {model!r}，当前只支持官方 deepseek-flash/V4.1-Flash-1017"
        )
    host = str(base_url_host or "").strip().lower()
    if host not in OFFICIAL_CHAT_HOSTS:
        raise OfficialChatProfileError(f"未知 chat host {base_url_host!r}，当前只支持官方 api.deepseek.com")
    if str(thinking or "").strip().lower() != "disabled":
        raise OfficialChatProfileError("官方 profile 只允许非思考模式（thinking=disabled）")
    assert_official_chat_pricing_floor(
        reserve_profile=reserve_profile,
        context_ceiling_tokens=context_ceiling_tokens,
        input_price_per_million_cny=input_price_per_million_cny,
        output_price_per_million_cny=output_price_per_million_cny,
        max_output_tokens=max_output_tokens,
    )
    if chat_max_output_tokens is not None:
        if _positive_int(chat_max_output_tokens, "chat_max_output_tokens") != OFFICIAL_MAX_OUTPUT_TOKENS:
            raise OfficialChatProfileError(
                f"官方 profile 要求 chat_max_output_tokens 固定为 {OFFICIAL_MAX_OUTPUT_TOKENS}"
            )


__all__ = [
    "OFFICIAL_CHAT_HOSTS",
    "OFFICIAL_CHAT_MODEL_NAMES",
    "OFFICIAL_CONTEXT_CEILING_TOKENS",
    "OFFICIAL_INPUT_PRICE_PER_MILLION_CNY",
    "OFFICIAL_MAX_OUTPUT_TOKENS",
    "OFFICIAL_OUTPUT_PRICE_PER_MILLION_CNY",
    "OfficialChatProfileError",
    "RESERVE_PROFILE",
    "assert_official_chat_pricing_floor",
    "assert_official_chat_profile",
]
