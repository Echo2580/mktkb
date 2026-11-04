"""中文文本里的通用实体名识别辅助（解析层与意图层共用同一口径）。

只提供**语言层面**的判定，不包含任何业务词表、文件名或题目信息：
- ``iter_store_names``：从文本里取"地名+店"形态的门店名；
- 排除 ``店家/店铺/店面/店长/店员/店内/店外/店里/店的`` 这类"店"并非门店名后缀的用法，
  以及"门店/两店/该店/本店"这类泛指（两字形态不视为门店名）。

解析层用它决定"正文通知里是否真的出现了一家具体门店"；意图层用它识别"未登记门店"
（例如语料里不存在的门店），两者共享同一口径可避免"发现店家"被当成门店"发现店"。
"""

from __future__ import annotations

import re

# "地名/字号 + 店"：两到四个汉字加"店"；两字形态（门店/店家/该店/两店）在过滤阶段丢弃。
STORE_NAME_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,4}店")
# "店"后若是这些字，说明原文是"店家/店铺/店面/店长/店内…"等普通词，不是门店名。
# 注意："的"不在此列——"城东店的联系人"是正常表达。
STORE_SUFFIX_BLOCK = frozenset("家铺面长员内外里中子门址名号前旁边侧")
# "店"前紧邻若是这些字，说明是"两店/该店/经两店/到店"等数量词或动词介词短语，不是门店名。
STORE_PRECEDING_BLOCK = frozenset(
    "两三多全各每该本跨分总须经由把被将要需和与及或给让使对向从往按就也都更最再又只才已正刚常不没无有含属归是为在到同另其他门家"
)
# 泛指性两字/三字组合，不作为具体门店名。
GENERIC_STORE_NAMES = frozenset(
    {
        "门店",
        "店家",
        "店铺",
        "店面",
        "店长",
        "店员",
        "店内",
        "店外",
        "店里",
        "店的",
        "各店",
        "该店",
        "本店",
        "两店",
        "三店",
        "多店",
        "全店",
        "分店",
        "总店",
        "连锁店",
    }
)
MIN_STORE_NAME_LENGTH = 3


def is_store_name(candidate: str) -> bool:
    """判断一个"…店"候选串是否像具体门店名（纯语言规则，不含业务词表）。"""
    name = candidate.strip()
    if len(name) < MIN_STORE_NAME_LENGTH or not name.endswith("店"):
        return False
    if name in GENERIC_STORE_NAMES:
        return False
    # "两店/该店/经两店…"：紧邻"店"的字是数量词或动词/介词时不是门店名
    if name[-2] in STORE_PRECEDING_BLOCK:
        return False
    # "门店/店家"等两字形态已由长度过滤；这里再拦"X店"里 X 是泛称的情况
    return not any(name.startswith(prefix) for prefix in ("门店", "店家", "店铺", "店面", "该店", "本店"))


def iter_store_names(text: str) -> list[tuple[int, str]]:
    """按出现顺序返回 ``(起始下标, 门店名)``，并丢弃后接"家/铺/面/长/员…"的误匹配。"""
    if not text:
        return []
    found: list[tuple[int, str]] = []
    seen: set[str] = set()
    for match in STORE_NAME_PATTERN.finditer(text):
        name = match.group(0)
        if not is_store_name(name):
            continue
        tail = text[match.end() : match.end() + 1]
        if tail and tail in STORE_SUFFIX_BLOCK:
            continue
        if name in seen:
            continue
        seen.add(name)
        found.append((match.start(), name))
    return found


def first_store_name(text: str) -> str | None:
    names = iter_store_names(text)
    return names[0][1] if names else None
