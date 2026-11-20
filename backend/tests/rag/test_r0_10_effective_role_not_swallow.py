"""R0/C21：无并列词时有效期角色不得吞掉句子里的登记字段词。

实测证据（第五轮 SAFE 投影）：C21 的问句同时命中 ``location`` 与“失效”，
但 ``plan.field_roles`` 只有 ``["effective_to"]``——``_match_fields`` 在没有并列词时
提前返回首个角色，答案层只渲染 ``field_roles`` 里的角色列，于是位置列整列丢失，
``value_hit`` 缺值。

规则（最小、全局）：
- 仅当首个角色是有效期角色（``effective_from`` / ``effective_to``）时才扩展；
- 扩展只认 ``FIELD_WORDS`` / ``_EXTRA_FIELD_ROLE_WORDS`` 里登记过的字段词；
- 价格类角色是“限定语”典型，一律不夹带（保留原反例）。
"""

from __future__ import annotations

import pytest

from mktkb.rag import query as q


def test_effective_role_does_not_swallow_field_word_without_joiner() -> None:
    # 位置 + 失效（无并列词）：两个角色都必须被请求到。
    roles = q._match_fields("甲店立牌放在什么位置什么时候失效")
    assert "effective_to" in roles, roles
    assert "location" in roles, roles


def test_effective_role_alone_stays_single() -> None:
    # 只问失效：不得凭空扩展。
    assert q._match_fields("甲店立牌的失效日期是哪天") == ("effective_to",)


def test_price_qualifier_is_never_carried() -> None:
    # 既有反例：价格只是限定语，问的是失效时间。
    roles = q._match_fields("那这个组合价什么时候失效")
    assert "effective_to" in roles, roles
    assert "price" not in roles, roles
    assert "price_type" not in roles, roles


def test_non_effective_first_role_keeps_old_behaviour() -> None:
    # 首角色不是有效期角色时，不做扩展（旧行为逐字保留）。
    assert q._match_fields("甲店立牌放在什么位置") == ("location",)


def test_joiner_path_unchanged() -> None:
    # 带并列词的既有路径不受影响。
    roles = q._match_fields("地址，电话")
    assert set(roles) >= {"address", "phone"}, roles
