"""正文型来源的记录事实抽取：把"门店 + 字段 + 值"的通知句子变成可检索的结构化字段。

背景（T09-D1 定位的 P0 缺陷）：正文 PDF/Word 段落原先一律 ``fields={}``，索引层因此拿不到
门店/物品/字段角色，record 检索与冲突检测都够不到正文通知（C05/C06/U06）。

本模块只做**句式层面的通用抽取**，不读取任何题集、文件名、题号或期望值：
- 句子必须同时出现「具体门店名」（``text_zh.iter_store_names`` 的同一口径）与「字段触发词」；
- 值取触发词之后的原文片段，遇到标点即止，去掉括号注释；
- 位置类额外要求能取出「门店与触发词之间的物品名」，否则不抽取（避免把"城东店在示例市"当位置）。

抽出的字段名直接用 ``retrieval.index.HEADER_ROLES`` 里的规范中文名（门店/物品/位置/电话/…），
因此索引、检索、冲突比较与来源详情都能沿用既有实现，无需改变任何数据契约。
"""

from __future__ import annotations

import re
from typing import Iterator

from ...text_zh import iter_store_names

# 句子边界：中文句号/分号/问号/感叹号/换行
SENTENCE_SPLIT = re.compile(r"[。；;！!？?\n]")
# 触发词 -> (HEADER_ROLES 规范名, 全角/半角连接词序列)
FIELD_TRIGGERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("位置", ("存放位置", "存放于", "存放至", "存放在", "存放", "临时调整至", "调整至", "调整为", "调整到", "调至", "移至", "搬到", "放在", "位于", "改至", "改为", "暂存于", "暂存")),
    ("电话", ("联系电话", "联系方式", "电话号码", "电话", "号码")),
    ("联系人", ("联系人",)),
    ("地址", ("地址",)),
    ("合作状态", ("合作状态", "合作关系")),
)
# 值前面可能出现的连接词（按长度降序剥离）
VALUE_CONNECTORS = ("调整为", "变更为", "更改为", "改为", "为", "是", "：", ":", "在", "于", "到", "至")
# 物品名两侧可能出现的修饰词
ITEM_PREFIX_NOISE = ("因", "其中", "本次", "该", "本")
ITEM_SUFFIX_NOISE = ("临时", "暂时", "已", "将", "需", "须", "要", "被", "进行", "统一")
# 括号注释（模拟数据用的"（模拟）"之类）不进入字段值
BRACKET_NOTE = re.compile(r"[（(][^（）()]{0,20}[）)]")
PHONE_VALUE = re.compile(r"^[0-9+\-() ]{5,}$")
MAX_VALUE_CHARS = 40
MIN_ITEM_CHARS = 2
MAX_ITEM_CHARS = 12


def _clean_value(raw: str) -> str:
    text = BRACKET_NOTE.sub("", raw).strip()
    text = text.strip("　 　，,。；;：:、")
    for connector in VALUE_CONNECTORS:
        if text.startswith(connector) and len(text) > len(connector):
            text = text[len(connector) :].strip()
            break
    return text[:MAX_VALUE_CHARS].strip()


def _clean_item(raw: str) -> str:
    text = raw.strip().strip("　 ，,。；;：:、的")
    for prefix in ITEM_PREFIX_NOISE:
        if text.startswith(prefix) and len(text) > len(prefix):
            text = text[len(prefix) :]
    for _ in range(3):
        for suffix in ITEM_SUFFIX_NOISE:
            if text.endswith(suffix) and len(text) > len(suffix) + MIN_ITEM_CHARS:
                text = text[: -len(suffix)]
    return text.strip("的 ").strip()


def _match_trigger(sentence: str, start: int) -> tuple[str, str, int] | None:
    """在 ``start`` 之后找最早出现的字段触发词，返回 (规范字段名, 触发词, 位置)。"""
    best: tuple[int, str, str] | None = None
    for field_name, triggers in FIELD_TRIGGERS:
        for trigger in triggers:
            index = sentence.find(trigger, start)
            if index == -1:
                continue
            if best is None or index < best[0] or (index == best[0] and len(trigger) > len(best[2])):
                best = (index, field_name, trigger)
    if best is None:
        return None
    return best[1], best[2], best[0]


def extract_record_facts(text: str) -> dict[str, str]:
    """从一段正文里抽「门店 + 字段 + 值」；抽不到或不满足形态时返回空字典。"""
    facts: dict[str, str] = {}
    if not text:
        return facts
    for sentence in SENTENCE_SPLIT.split(text):
        if not sentence.strip():
            continue
        stores = iter_store_names(sentence)
        if not stores:
            continue
        store_offset, store_name = stores[0]
        store_end = store_offset + len(store_name)
        matched = _match_trigger(sentence, store_end)
        if matched is None:
            continue
        field_name, trigger, trigger_offset = matched
        value = _clean_value(sentence[trigger_offset + len(trigger) :])
        if not value:
            continue
        if field_name == "电话" and not PHONE_VALUE.match(value.replace(" ", "")):
            continue
        if field_name == "位置":
            item = _clean_item(sentence[store_end:trigger_offset])
            if not (MIN_ITEM_CHARS <= len(item) <= MAX_ITEM_CHARS):
                continue
            if any(character in item for character in "，,。；;：:"):
                continue
            facts.setdefault("物品", item)
        facts.setdefault("门店", store_name)
        facts.setdefault(field_name, value)
        if len(facts) >= 4:
            break
    return facts


def iter_units_with_facts(units: Iterator) -> Iterator:
    """解析器辅助：对 ``paragraph`` 单元就地补 fields（其余单元原样返回）。"""
    for unit in units:
        if unit.kind == "paragraph" and not unit.fields:
            facts = extract_record_facts(unit.text)
            if facts:
                from dataclasses import replace

                unit = replace(unit, fields=facts)
        yield unit
