"""T05 本地分词与规范化：入库与查询使用同一 jieba 规则、同一词典版本与同一 NFKC 规范化。

设计要点：
- 私有 Tokenizer 实例，禁用 jieba 缓存文件（不写临时文件，也不把本轮动态词写入下一轮）；
- 只加入通用、无业务事实的领域词（别名/字段同义词），不加入门店名、编号或答案值；
- 中文正文同时索引 jieba 词与汉字二元组：短词（1～2 字）和别名词条即使被 jieba 合并，
  仍能通过二元组命中；编号/电话仍以字段精确匹配为主，不让分词改写原值；
- FTS 查询表达式只由安全引号包裹的 token 组成，用户输入不能注入 OR/NEAR/引号/星号等语法。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from functools import lru_cache

import jieba

# 通用领域词（无门店/物品业务事实）；用于稳定切分与别名查询。
DOMAIN_WORDS: tuple[str, ...] = (
    "门店",
    "店家",
    "店铺",
    "商户",
    "物品",
    "物料",
    "位置",
    "别名",
    "俗称",
    "别称",
    "联系人",
    "联系电话",
    "合作状态",
    "宣传海报",
    "海报",
    "展示架",
    "展架",
    "价签卡纸",
    "价签纸",
    "易拉宝",
    "促销贴纸",
    "贴纸",
    "货架",
    "柜位",
)

_WHITESPACE = re.compile(r"\s+")
_TOKEN_KEEP = re.compile(r"[\w\u4e00-\u9fff]", re.UNICODE)
_HAN_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
_HAN = "\u4e00-\u9fff"


def normalize(text: str) -> str:
    """查询/入库共用的规范化：NFKC、首尾空白、空白折叠、ASCII 大小写归一。"""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    normalized = unicodedata.normalize("NFKC", text)
    return _WHITESPACE.sub(" ", normalized).strip().casefold()


def normalize_value(value: object) -> str:
    """字段值规范化：仅用于建键与比较，返回给调用方的仍是原值。"""
    if value is None:
        return ""
    return normalize(str(value))


@lru_cache(maxsize=1)
def _tokenizer() -> jieba.Tokenizer:
    tokenizer = jieba.Tokenizer()
    # 直接构建前缀词典，绕过 jieba 的 cache 读写：
    # - 不写任何 jieba.cache/临时文件，词典版本每次都由已安装包决定；
    # - 不读取机器上可能被其他项目污染的缓存；
    # - 只在内存中 add 通用领域词，不把本轮数据写入下一轮。
    tokenizer.FREQ, tokenizer.total = tokenizer.gen_pfdict(tokenizer.get_dict_file())
    tokenizer.initialized = True
    for word in DOMAIN_WORDS:
        tokenizer.add_word(word)
    return tokenizer


def _version_tag() -> str:
    digest = hashlib.sha256("|".join(DOMAIN_WORDS).encode("utf-8")).hexdigest()[:12]
    return f"jieba-{getattr(jieba, '__version__', 'unknown')}|dict-default|domain-{digest}|bigram-v1|nfkc-v1"


TOKENIZER_VERSION = _version_tag()


def cut(text: str) -> tuple[str, ...]:
    """jieba 分词（规范化后），过滤纯标点/空白 token；保持原顺序与去重前的重复。"""
    normalized = normalize(text)
    if not normalized:
        return ()
    tokens = []
    for token in _tokenizer().lcut(normalized):
        token = token.strip()
        if token and _TOKEN_KEEP.search(token):
            tokens.append(token)
    return tuple(tokens)


def bigrams(text: str) -> tuple[str, ...]:
    """汉字二元组（只含 CJK 连续段），用于短词/别名召回。"""
    normalized = normalize(text)
    grams: list[str] = []
    for run in _HAN_RUN.findall(normalized):
        grams.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tuple(grams)


def index_body(text: str) -> str:
    """FTS 索引正文：jieba 词 + 汉字二元组，按出现顺序去重，空格分隔。"""
    seen: dict[str, None] = {}
    for token in cut(text):
        seen.setdefault(token, None)
    for gram in bigrams(text):
        seen.setdefault(gram, None)
    return " ".join(seen)


def _quote(token: str) -> str:
    """FTS5 字符串字面量：双引号包裹，内部双引号翻倍，任何运算符都失效。"""
    return '"' + token.replace('"', '""') + '"'


def term_expression(term: str) -> str | None:
    """单个检索词的 FTS 表达式：词面 AND，或汉字二元组 AND（两者取 OR）。"""
    parts: list[str] = []
    tokens = cut(term)
    if tokens:
        parts.append("(" + " ".join(_quote(token) for token in tokens) + ")")
    grams = bigrams(term)
    if len(grams) >= 1:
        parts.append("(" + " ".join(_quote(gram) for gram in grams) + ")")
    if not parts:
        return None
    return " OR ".join(parts)


def match_expression(terms: tuple[str, ...] | list[str]) -> str | None:
    """多检索词的 FTS 表达式：逐词 OR（召回优先），词内 AND。非法/空词被忽略。"""
    expressions = [expr for expr in (term_expression(term) for term in terms) if expr]
    if not expressions:
        return None
    return " OR ".join(f"({expr})" for expr in expressions)


def is_short_term(term: str) -> bool:
    """1～2 字短词：保留受限精确/子串渠道（字段值与原文），避免只靠词面。"""
    normalized = normalize(term)
    return 0 < len(normalized) <= 2


def contains_han(text: str) -> bool:
    return any(_HAN[0] <= char <= _HAN[-1] for char in normalize(text))
