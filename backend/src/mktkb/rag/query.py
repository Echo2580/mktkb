"""查询补全、条件继承、澄清与“全部”枚举计划。

规则只使用当前索引里的实体/渠道/价格类型词表与通用字段同义词，不按题号、答案或
资料文件名硬编码。助手答案不作为业务事实继承；状态只保存检索条件和分页。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from ..retrieval.tokenize import cut, normalize
from .types import QueryPlan, QueryState

RECORD_FIELD_ROLES: frozenset[str] = frozenset(
    {
        "location",
        "contact",
        "phone",
        "address",
        "status",
        "quantity",
        "price",
        "note",
        "date",
        "effective_from",
        "effective_to",
        "spec",
    }
)
DOCUMENT_FIELD_ROLES: frozenset[str] = frozenset({"height", "clause"})
FIELD_WORDS: dict[str, tuple[str, ...]] = {
    "location": ("位置", "在哪", "哪里", "哪儿", "搁哪", "搁哪儿", "放哪", "放到哪", "放在哪", "存放", "位于", "所在"),
    "price": ("参考供价", "建议零售价", "会员价", "档期特价", "箱促价", "组合价", "零售价", "价格", "单价", "多少钱", "售价", "特价", "供价"),
    "quantity": ("有多少", "数量", "多少张", "多少个", "多少面", "多少块", "几瓶", "几箱", "实发", "剩余", "库存"),
    "effective_from": ("生效日期", "生效时间", "什么时候开始生效", "开始生效"),
    "effective_to": ("失效日期", "截止日期", "什么时候失效", "结束日期"),
    "date": ("日期", "时间", "什么时候", "盘点时间", "活动日期", "更新日期"),
    "height": ("高度", "高度区间", "陈列高度"),
    "note": ("备注", "规则", "限购", "搭赠", "摆放要求", "扣分规则"),
    "contact": ("联系人", "负责人"),
    "phone": ("电话", "联系电话", "手机号", "手机号码", "联系方式"),
    "address": ("地址", "门店地址", "详细地址"),
    "status": ("合作状态", "合作关系", "状态"),
    "spec": ("规格型号", "型号规格", "规格/型号", "规格", "品名规格"),
    "clause": ("条款", "第几条", "第几条规定"),
    "price_type": ("价格类型", "价格类别"),
}
ENUMERATE_WORDS = (
    "全部",
    "所有",
    "列出",
    "列一下",
    "清单",
    "逐一",
    "分别",
    "各店",
    "每个",
    "每一条",
    "多少条",
    "几条",
    "多少笔",
    "总共有多少",
)
ANAPHORA_WORDS = ("它", "这个", "那个", "该", "上述", "刚才", "前面", "这家", "那家", "这种", "该项", "其")
SWITCH_WORDS = ("换成", "改为", "另外", "其他", "不说", "重新问", "换个", "再问一个", "换一个话题")
PAGE_WORDS = ("下一页", "继续看", "更多", "下一页呢")
FUTURE_WORDS = ("调整后", "通知", "生效后", "之后", "未来", "新版", "将调整", "拟")
STOPWORDS = frozenset(
    {
        "哪些",
        "什么",
        "怎么",
        "如何",
        "需要",
        "是否",
        "可以",
        "现在",
        "告诉",
        "请问",
        "一下",
        "多久",
        "多少",
        "是谁",
        "是",
        "的",
        "了",
        "吗",
        "呢",
        "和",
        "与",
        "或",
        "在",
        "有",
        "要",
        "请",
        "给",
        "我",
        "它",
        "他",
        "她",
        "这个",
        "那个",
        "该",
        "其",
        "以及",
        "还有",
        "一个",
        "全部",
        "所有",
        "列出",
        "列出来",
        "分别",
        "各",
        "资料",
    }
)
_DATE_FULL = re.compile(r"(20\d{2})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})")
_QUARTER = re.compile(r"(20\d{2})\s*年?\s*[Qq]\s*([1-4])")
_PAGE_NUMBER = re.compile(r"第\s*(\d+)\s*页")
_IDENTIFIER = re.compile(r"\b([A-Za-z]{1,8}[-_]?\d{3,})\b")
_STORE_SUFFIX = "店"
_STORE_NAME_LIMIT = 8
# 连接词只在“紧跟在已识别门店/分隔符之后”时才是分隔符；“和平里店”这类名字
# 自身以连接词开头时不能被剥首字（R4-NEW-5）。
_STORE_CONNECTORS = "和与及跟同"
_STORE_SEPARATORS = "、、，,；;：:。.·/|\\|\t\n\r（）()【】[]「」""'' \u3000"
_STORE_MASK = "\u0000"
_BAD_STORE_WORDS = (
    "门店",
    "店家",
    "店铺",
    "本店",
    "该店",
    "各店",
    "全部门店",
    "连锁店",
    "便利店",
    "专卖店",
    "这家店",
    "那家店",
    "哪家店",
    "哪家",
    "哪些店",
    "台账里",
    "表里",
    "资料里",
    "记录里",
    "这个位置",
    "那个位置",
    "对应的店",
    "门店里",
    "多少家店",
)


@dataclass(frozen=True)
class DocumentRef:
    doc_id: str
    title: str
    source_path: str = ""
    version_label: str = ""


@dataclass(frozen=True)
class Lexicon:
    stores: tuple[str, ...] = ()
    items: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    price_types: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    field_labels: tuple[str, ...] = ()
    alias_map: Mapping[str, tuple[str, ...]] | None = None
    documents: tuple[DocumentRef, ...] = ()

    def aliases_for(self, alias: str) -> tuple[str, ...]:
        return tuple((self.alias_map or {}).get(alias, ()))

    def all_entity_labels(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.stores) | set(self.items) | set(self.products)))


def build_lexicon(data: Mapping[str, Any]) -> Lexicon:
    return Lexicon(
        stores=tuple(str(x) for x in data.get("stores") or ()),
        items=tuple(str(x) for x in data.get("items") or ()),
        products=tuple(str(x) for x in data.get("products") or ()),
        channels=tuple(str(x) for x in data.get("channels") or ()),
        price_types=tuple(str(x) for x in data.get("price_types") or ()),
        identifiers=tuple(str(x) for x in data.get("identifiers") or ()),
        field_labels=tuple(str(x) for x in data.get("field_labels") or ()),
        alias_map={str(k): tuple(str(i) for i in v) for k, v in dict(data.get("alias_map") or {}).items()},
        documents=tuple(
            DocumentRef(
                doc_id=str(item.get("doc_id") or ""),
                title=str(item.get("title") or ""),
                source_path=str(item.get("source_path") or ""),
                version_label=str(item.get("version_label") or ""),
            )
            for item in (data.get("documents") or ())
            if isinstance(item, Mapping) and item.get("doc_id")
        ),
    )


def _norm(value: str) -> str:
    return normalize(value)


def _compact(value: str) -> str:
    """去空白/常见分隔符，用于“NKA 卖场”与“NKA卖场”等价匹配。"""
    return re.sub(r"[\s\-_/|｜、，,;；:：()（）\[\]【】]+", "", _norm(value))


def _match_labels(question: str, labels: tuple[str, ...]) -> list[str]:
    normalized = _norm(question)
    found: list[str] = []
    for label in sorted(set(labels), key=lambda item: (-len(item), item)):
        key = _norm(label)
        if key and key in normalized and label not in found:
            found.append(label)
    return found


def _match_aliases(question: str, labels: tuple[str, ...], lexicon: Lexicon) -> list[str]:
    normalized = _norm(question)
    compact_question = _compact(question)
    found: list[str] = []
    for label in sorted(set(labels), key=lambda item: (-len(item), item)):
        key = _norm(label)
        if (key and key in normalized) or (_compact(label) and _compact(label) in compact_question):
            if label not in found:
                found.append(label)
    for alias, targets in sorted((lexicon.alias_map or {}).items(), key=lambda item: (-len(item[0]), item[0])):
        if _norm(alias) in normalized or _compact(alias) in compact_question:
            for target in targets:
                if target in labels and target not in found:
                    found.append(target)
    return found


def _product_core(product: str) -> str:
    return re.split(r"[（(]", product, maxsplit=1)[0].strip()


def _product_volume(product: str) -> str | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|毫升|l|升|g|克)", _norm(product))
    if not match:
        return None
    number, unit = match.groups()
    return f"{number}{'ml' if unit in ('ml', '毫升') else ('l' if unit in ('l', '升') else 'g')}"


def _match_products(question: str, lexicon: Lexicon) -> tuple[str | None, tuple[str, ...]]:
    normalized = _norm(question)
    compact_question = _compact(question)
    exact = [product for product in lexicon.products if _compact(product) and _compact(product) in compact_question]
    if exact:
        return max(exact, key=len), ()
    tokens = [token for token in cut(question) if len(token) >= 2 and token not in STOPWORDS]
    matches: list[str] = []
    for product in lexicon.products:
        core = _norm(_product_core(product))
        if not core:
            continue
        if core in normalized or any(token in core for token in tokens):
            matches.append(product)
    matches = sorted(set(matches))
    if not matches:
        return None, ()
    if len(matches) == 1:
        return matches[0], ()
    volumes = {product: _product_volume(product) for product in matches}
    question_volumes = {
        f"{match.group(1)}{'ml' if match.group(2) in ('ml', '毫升') else ('l' if match.group(2) in ('l', '升') else 'g')}"
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(ml|毫升|l|升|g|克)", normalized)
    }
    if question_volumes:
        narrowed = [product for product in matches if volumes.get(product) in question_volumes]
        if len(narrowed) == 1:
            return narrowed[0], ()
        if narrowed:
            return None, tuple(narrowed)
    return None, tuple(matches)


def _match_channels(question: str, lexicon: Lexicon) -> list[str]:
    normalized = _norm(question)
    compact_question = _compact(question)
    found: list[str] = []
    for channel in sorted(set(lexicon.channels), key=lambda item: (-len(item), item)):
        key = _compact(channel)
        if key and key in compact_question:
            found.append(channel)
    if not found:
        for channel in sorted(set(lexicon.channels), key=lambda item: (-len(item), item)):
            short = re.split(r"(卖场|连锁|便利店|超市|渠道)", channel, maxsplit=1)[0].strip()
            if len(_compact(short)) >= 2 and _compact(short) in compact_question:
                found.append(channel)
    return found


def _match_price_types(question: str, lexicon: Lexicon) -> list[str]:
    compact_question = _compact(question)
    found = [
        price_type
        for price_type in sorted(set(lexicon.price_types), key=lambda item: (-len(item), item))
        if _compact(price_type) and _compact(price_type) in compact_question
    ]
    if found:
        return found
    tokens = [token for token in cut(question) if len(token) >= 2 and token not in STOPWORDS]
    for price_type in lexicon.price_types:
        if any(token in _norm(price_type) for token in tokens):
            found.append(price_type)
    return sorted(set(found))


def _match_identifier(question: str, lexicon: Lexicon) -> str | None:
    normalized = _norm(question)
    for identifier in sorted(set(lexicon.identifiers), key=lambda item: (-len(item), item)):
        if _norm(identifier) and _norm(identifier) in normalized:
            return identifier
    match = _IDENTIFIER.search(question)
    if match:
        candidate = match.group(1).strip()
        if candidate in lexicon.identifiers:
            return candidate
    return None


def match_identifier(question: str, identifiers: Iterable[str]) -> str | None:
    """公开的标识匹配入口：与查询内核同一正则/规范化口径。

    供产品意图层复用（D-IA-1），避免另造一套编号解析器；命中判定仍是“已知标识值”
    优先，未知形态只作为形态识别（是否像标识）返回 None。
    """
    return _match_identifier(question, Lexicon(identifiers=tuple(str(x) for x in identifiers)))


def identifier_shape(question: str) -> str | None:
    """问题里出现的“像标识”的片段（只做形态识别，不判断是否存在）。"""
    match = _IDENTIFIER.search(str(question or ""))
    return match.group(1).strip() if match else None


def _document_core(title: str) -> str:
    return re.split(r"[_（(]", str(title), maxsplit=1)[0].strip()


def _missing_document(question: str) -> str | None:
    pattern = re.compile(r"([\u4e00-\u9fffA-Za-z0-9]{2,}(?:台账|清单|通知|资料|表))")
    generic = {"资料", "文档", "表格", "台账", "清单", "通知", "这个表", "该表", "表里", "表内"}
    for match in pattern.finditer(question):
        name = match.group(1).strip()
        name = re.sub(r"^(?:把|将|查|看|找|从|在|对)", "", name)
        if name in generic or any(word in name for word in ("这个", "该", "上述", "表里", "表内")):
            continue
        return name
    return None


def _match_document(question: str, lexicon: Lexicon) -> tuple[DocumentRef | None, tuple[str, ...]]:
    compact_question = _compact(question)
    hits: list[DocumentRef] = []
    for document in lexicon.documents:
        code = _compact(document.doc_id)
        core = _compact(_document_core(document.title))
        if (code and code in compact_question) or (len(core) >= 3 and core in compact_question):
            hits.append(document)
    unique: dict[str, DocumentRef] = {}
    for document in hits:
        unique.setdefault(document.doc_id, document)
    if len(unique) == 1:
        return next(iter(unique.values())), ()
    if len(unique) > 1:
        return None, tuple(document.title for document in unique.values())
    # 未直接写出资料名时，只有问题明确指向“台账/表/通知/资料”或未来调整时才做资料推断，
    # 避免把普通字段问题误绑到标题相似的某份资料。
    document_cues = (
        "台账",
        "清单",
        "通知",
        "制度",
        "价目表",
        "明细",
        "记录",
        "表里",
        "表内",
        "表格",
        "工作表",
        "资料",
        "文档",
        "调整之后",
        "调整后",
        "按《",
    )
    if not any(cue in question for cue in document_cues):
        return None, ()
    # 未直接写出资料名时，用标题与问题的最长公共片段做唯一匹配。
    action_words = ("调整", "通知", "变更", "生效", "失效", "停用", "替换")
    scored: list[tuple[int, DocumentRef]] = []
    for document in lexicon.documents:
        core = _compact(_document_core(document.title))
        if not core:
            continue
        best = 0
        for size in range(min(len(core), len(compact_question)), 1, -1):
            if any(core[index : index + size] in compact_question for index in range(len(core) - size + 1)):
                best = size
                break
        if best <= 0:
            continue
        if any(word in compact_question and word in core for word in action_words):
            best += 2
        if any(word in compact_question for word in ("调整", "通知", "变更")) and any(
            word in core for word in ("通知", "公告")
        ):
            best += 3
        scored.append((best, document))
    if not scored:
        return None, ()
    top = max(score for score, _ in scored)
    winners = [document for score, document in scored if score == top]
    if len({document.doc_id for document in winners}) == 1:
        return winners[0], ()
    return None, ()


def _match_stores(question: str, lexicon: Lexicon) -> tuple[str, ...]:
    known = _match_labels(question, lexicon.stores)
    return tuple(sorted(known, key=lambda value: (-len(value), value)))


def _mask_known_stores(question: str, lexicon: Lexicon) -> str:
    """把词表内门店名遮掉，剩下的 `店` 才可能是未知门店。"""
    masked = list(question)
    for label in sorted(set(lexicon.stores), key=lambda item: (-len(item), item)):
        if not label:
            continue
        start = 0
        while True:
            index = question.find(label, start)
            if index < 0:
                break
            span = range(index, index + len(label))
            if any(masked[position] == _STORE_MASK for position in span):
                start = index + 1
                continue
            for position in span:
                masked[position] = _STORE_MASK
            start = index + len(label)
    return "".join(masked)


def _unknown_store_tokens(question: str, lexicon: Lexicon) -> tuple[str, ...]:
    """按分隔符与“真连接词”切段，提取词表外的 `*店` token。

    - 已知门店先遮掉，避免“和悦广场店”这类名字被切成“悦广场店”；
    - “和/与/及”只有紧跟已识别门店或分隔符时才算连接词，避免把“和平里店”
      的首字当连接词剥掉；
    - 每个分段只取 `店` 及其前最多 8 个汉字。
    """
    masked = _mask_known_stores(question, lexicon)
    separators = [False] * len(masked)
    for position, char in enumerate(masked):
        if char == _STORE_MASK or char in _STORE_SEPARATORS:
            separators[position] = True
            continue
        if char not in _STORE_CONNECTORS:
            continue
        previous = masked[position - 1] if position > 0 else ""
        original_previous = question[position - 1] if position > 0 else ""
        following = masked[position + 1] if position + 1 < len(masked) else ""
        previous_is_boundary = bool(previous) and (
            previous == _STORE_MASK
            or previous in _STORE_SEPARATORS
            or (previous not in _STORE_CONNECTORS and original_previous == _STORE_SUFFIX)
        )
        following_is_store = bool(following) and following == _STORE_MASK
        if previous_is_boundary or following_is_store:
            separators[position] = True
    tokens: list[str] = []
    run_start = 0
    runs: list[str] = []
    for position, char in enumerate(masked):
        if separators[position]:
            runs.append(masked[run_start:position])
            run_start = position + 1
    runs.append(masked[run_start:])
    for run in runs:
        index = run.find(_STORE_SUFFIX)
        if index < 0:
            continue
        head = index
        while head > 0 and index - head < _STORE_NAME_LIMIT - 1 and "\u4e00" <= run[head - 1] <= "\u9fff":
            head -= 1
        token = run[head : index + 1]
        if len(token) < len(_STORE_SUFFIX) + 2:
            continue
        if any(bad in token for bad in _BAD_STORE_WORDS):
            continue
        if "哪" in token or token.startswith(("把", "将", "查", "找")):
            continue
        if any(_norm(token) == _norm(item) or _norm(token) in _norm(item) for item in lexicon.stores):
            continue
        if token not in tokens:
            tokens.append(token)
    return tuple(tokens)


def _match_store(question: str, lexicon: Lexicon) -> tuple[str | None, str | None]:
    known = _match_stores(question, lexicon)
    store = known[0] if known else None
    unknown = _unknown_store_tokens(question, lexicon)
    return store, (unknown[0] if unknown else None)


def _match_field(question: str) -> str | None:
    normalized = _norm(question)
    # 明确的生效/失效词优先于“组合价/价格”等泛化词。
    if any(_norm(word) in normalized for word in ("失效", "截止", "结束日期")):
        return "effective_to"
    if any(_norm(word) in normalized for word in ("生效", "开始日期", "什么时候开始")):
        return "effective_from"
    # 先识别价格类型，避免“价格类型”被“价格”抢先。
    if any(_norm(word) in normalized for word in FIELD_WORDS["price_type"]):
        return "price_type"
    for role, words in FIELD_WORDS.items():
        if role == "price_type":
            continue
        if any(_norm(word) in normalized for word in words):
            return role
    return None


def _match_fields(question: str) -> tuple[str, ...]:
    """返回问题明确要求的多个字段；单价+规格这类并列问法不能只取第一个。"""
    normalized = _norm(question)
    found: list[str] = []
    first = _match_field(question)
    if first:
        found.append(first)
    if not any(word in question for word in ("和", "及", "以及", "、", "与")):
        return tuple(found)
    for role, words in FIELD_WORDS.items():
        if role in found:
            continue
        if any(_norm(word) in normalized for word in words):
            found.append(role)
    return tuple(found)


def _terms(question: str, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    seen: list[str] = []
    for token in cut(question):
        cleaned = token.strip()
        if len(cleaned) < 2 or cleaned in STOPWORDS or cleaned.isdigit():
            continue
        if cleaned not in seen:
            seen.append(cleaned)
        if len(seen) >= 12:
            break
    for token in extra:
        if token and token not in seen and len(token) >= 2:
            seen.append(token)
    return tuple(seen[:12])


def _as_of(question: str, previous: str | None, business_date: str | None) -> str | None:
    match = _DATE_FULL.search(question)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    quarter = _QUARTER.search(question)
    if quarter:
        year, q = int(quarter.group(1)), int(quarter.group(2))
        return {
            1: f"{year}-03-31",
            2: f"{year}-06-30",
            3: f"{year}-09-30",
            4: f"{year}-12-31",
        }[q]
    if any(word in question for word in ("现在", "当前", "目前", "今天")):
        return business_date or previous
    return previous or business_date


def _page_request(question: str, previous: QueryState) -> int | None:
    match = _PAGE_NUMBER.search(question)
    if match:
        return max(1, int(match.group(1)))
    if any(word in question for word in PAGE_WORDS):
        return max(1, previous.page + 1)
    return None


def _fill_pending(pending: str, question: str, lexicon: Lexicon) -> str | None:
    if pending == "store":
        store, _unknown = _match_store(question, lexicon)
        return store
    if pending == "item":
        found = _match_aliases(question, lexicon.items, lexicon)
        return found[0] if found else None
    if pending == "product":
        product, candidates = _match_products(question, lexicon)
        return product or (candidates[0] if len(candidates) == 1 else None)
    if pending == "channel":
        found = _match_channels(question, lexicon)
        return found[0] if found else None
    if pending == "price_type":
        found = _match_price_types(question, lexicon)
        return found[0] if found else None
    return None


def _new_state(
    previous: QueryState,
    *,
    question: str,
    slots: Mapping[str, str | None],
    stores: tuple[str, ...],
    field_role: str | None,
    field_roles: tuple[str, ...],
    enumerate: bool,
    page: int | None,
    page_size: int,
    as_of: str | None,
    reset: bool,
) -> QueryState:
    state = QueryState(
        user_id=previous.user_id,
        conversation_id=previous.conversation_id,
        page_size=page_size,
        turn=previous.turn + 1,
        last_question=question,
    )
    if not reset:
        state.store = previous.store
        state.stores = previous.stores
        state.item = previous.item
        state.product = previous.product
        state.channel = previous.channel
        state.price_type = previous.price_type
        state.identifier = previous.identifier
        state.doc_id = previous.doc_id
        state.doc_title = previous.doc_title
        state.field_role = previous.field_role
        state.field_roles = previous.field_roles
        state.as_of = previous.as_of
        state.pending_slot = previous.pending_slot
        state.candidates = previous.candidates
    if reset:
        state.doc_id = None
        state.doc_title = None
        state.store = None
        state.stores = ()
    elif slots.get("doc_id") and previous.doc_id and slots.get("doc_id") != previous.doc_id:
        # 明确切到另一份资料时，旧实体/字段条件不再适用于新资料。
        state.store = state.item = state.product = state.channel = state.price_type = state.identifier = None
        state.stores = ()
        state.field_role = None
        state.field_roles = ()
    elif previous.doc_id and not slots.get("doc_id"):
        state.doc_id = previous.doc_id
        state.doc_title = previous.doc_title
    # 明确切换实体时清掉旧实体的标识/渠道/价格类型，避免把 QF02 带到滨江店查询。
    if slots.get("store") and previous.store and slots.get("store") != previous.store and not slots.get("identifier"):
        state.identifier = None
    if slots.get("item") and previous.item and slots.get("item") != previous.item and not slots.get("identifier"):
        state.identifier = None
    if slots.get("product") and previous.product and slots.get("product") != previous.product:
        if not slots.get("identifier"):
            state.identifier = None
        if not slots.get("channel"):
            state.channel = None
        if not slots.get("price_type"):
            state.price_type = None
    for key in ("store", "item", "product", "channel", "price_type", "identifier", "doc_id", "doc_title"):
        value = slots.get(key)
        if value:
            setattr(state, key, value)
    if stores:
        state.stores = stores
        state.store = stores[0]
    elif slots.get("store"):
        state.stores = (slots["store"],)
    if field_role:
        state.field_role = field_role
    if field_roles:
        state.field_roles = field_roles
    if as_of:
        state.as_of = as_of
    state.enumerate = bool(enumerate)
    state.page = page if page is not None else 1
    return state


def _clarification_candidates(
    state: QueryState,
    *,
    missing: str,
    lexicon: Lexicon,
) -> tuple[str, ...]:
    if missing == "product":
        if state.product:
            family = _norm(_product_core(state.product))
            return tuple(product for product in lexicon.products if _norm(_product_core(product)) == family)
        return lexicon.products[:8]
    if missing == "store":
        return lexicon.stores[:8]
    if missing == "item":
        return lexicon.items[:8]
    if missing == "channel":
        return lexicon.channels[:8]
    if missing == "price_type":
        return lexicon.price_types[:8]
    return ()


def _required_missing(state: QueryState, mode: str) -> str | None:
    if mode != "record":
        return None
    if state.enumerate and state.doc_id:
        return None
    if state.enumerate and not state.field_role and (state.store or state.item or state.product):
        return None
    if state.field_role == "price":
        if not (state.product or state.item or state.identifier):
            return "product"
    if state.field_role in ("location", "quantity", "note"):
        if not (state.store or state.item or state.product or state.identifier):
            return "store"
    if state.field_role in ("contact", "phone", "address", "status"):
        if not state.store:
            return "store"
    if not any((state.store, state.item, state.product, state.identifier, state.doc_id)):
        return "store"
    return None


def parse_query(
    question: str,
    *,
    previous: QueryState | None,
    lexicon: Lexicon,
    business_date: str | None = None,
    page_size: int = 10,
) -> QueryPlan:
    question = str(question or "").strip()
    if not question:
        raise ValueError("问题不能为空")
    previous = previous or QueryState()
    normalized = _norm(question)
    stores = _match_stores(question, lexicon)
    unknown_stores = _unknown_store_tokens(question, lexicon)
    store = stores[0] if stores else None
    unknown_store = unknown_stores[0] if unknown_stores else None
    item_hits = _match_aliases(question, lexicon.items, lexicon)
    product, product_candidates = _match_products(question, lexicon)
    channel_hits = _match_channels(question, lexicon)
    price_type_hits = _match_price_types(question, lexicon)
    identifier = _match_identifier(question, lexicon)
    document, document_candidates = _match_document(question, lexicon)
    missing_document = _missing_document(question) if document is None else None
    missing_stores = unknown_stores if stores else ()
    slots: dict[str, str | None] = {
        "store": store if len(stores) <= 1 else None,
        "item": item_hits[0] if len(item_hits) == 1 and not product else None,
        "product": product,
        "channel": channel_hits[0] if len(channel_hits) == 1 else None,
        "price_type": price_type_hits[0] if len(price_type_hits) == 1 else None,
        "identifier": identifier,
        "doc_id": document.doc_id if document else None,
        "doc_title": document.title if document else None,
    }
    field_roles = _match_fields(question)
    field_role = field_roles[0] if field_roles else None
    page_request = _page_request(question, previous)
    enumerate_flag = any(word in question for word in ENUMERATE_WORDS)
    if page_request is not None and previous.enumerate:
        enumerate_flag = True
    page = page_request
    as_of = _as_of(question, previous.as_of, business_date)
    include_future = any(word in question for word in FUTURE_WORDS)

    # 短回答先补 pending slot，再判断是否话题切换。
    filled_pending = False
    if previous.pending_slot and not any(slots.values()) and not field_role and len(question) <= 24:
        value = _fill_pending(previous.pending_slot, question, lexicon)
        if value:
            slots[previous.pending_slot] = value
            filled_pending = True

    explicit_entity = any(slots.get(key) for key in ("store", "item", "product", "identifier", "doc_id"))
    previous_entity = any(
        getattr(previous, key) for key in ("store", "item", "product", "identifier", "doc_id")
    )
    overlap = any(
        slots.get(key) and slots.get(key) == getattr(previous, key)
        for key in ("store", "item", "product", "identifier", "doc_id")
    )
    anaphora = any(word in question for word in ANAPHORA_WORDS)
    reset = False
    if any(word in question for word in SWITCH_WORDS):
        reset = True
    elif explicit_entity and previous_entity and not overlap and field_role is not None:
        reset = True
    elif field_role in DOCUMENT_FIELD_ROLES and previous_entity and not explicit_entity:
        reset = True
    elif previous.pending_slot and not filled_pending and explicit_entity and not overlap:
        # 澄清后换了对象：保留其它有效条件，只替换该对象。
        reset = False

    state = _new_state(
        previous,
        question=question,
        slots=slots,
        stores=stores,
        field_role=field_role,
        field_roles=field_roles,
        enumerate=enumerate_flag,
        page=page,
        page_size=page_size,
        as_of=as_of,
        reset=reset,
    )
    if filled_pending:
        state.pending_slot = None
        state.candidates = ()
    elif previous.pending_slot and slots.get(previous.pending_slot):
        # 用户直接在问题里给出了澄清槽的值（例如“城东店”）：槽已满足，不能继续挂起。
        state.pending_slot = None
        state.candidates = ()
    if missing_document:
        return QueryPlan(
            question=question,
            mode="record" if state.enumerate else "document",
            query_text=question,
            field_role=state.field_role,
            field_label=state.field_role,
            filters={},
            terms=_terms(question),
            state=state,
            enumerate=state.enumerate,
            page=state.page,
            page_size=state.page_size,
            clarification=f"资料“{missing_document}”未收录，未使用其它资料替代。",
            include_future=include_future,
            reason="DOCUMENT_NOT_FOUND",
            missing_stores=missing_stores,
        )

    # 多个候选对象：先澄清，不检索。
    if document_candidates and not state.doc_id:
        return QueryPlan(
            question=question,
            mode="record" if (state.enumerate or field_role is None) else "document",
            query_text=question,
            field_role=state.field_role,
            field_label=state.field_role,
            filters={},
            terms=_terms(question),
            state=state,
            enumerate=state.enumerate,
            page=state.page,
            page_size=state.page_size,
            clarification="问题包含多份资料，请指定要查询的资料。",
            candidates=document_candidates[:8],
            include_future=include_future,
            reason="DOCUMENT_AMBIGUOUS",
        )
    if product_candidates and not state.product:
        return QueryPlan(
            question=question,
            mode="record" if field_role in RECORD_FIELD_ROLES or "price" in normalized else "document",
            query_text=question,
            field_role=state.field_role,
            field_label=state.field_role,
            filters={},
            terms=_terms(question),
            state=state,
            enumerate=state.enumerate,
            page=state.page,
            page_size=state.page_size,
            clarification="该商品有多个规格/版本，请选择要查询的商品。",
            candidates=product_candidates[:8],
            include_future=include_future,
            reason="PRODUCT_AMBIGUOUS",
        )
    if len(item_hits) > 1:
        return QueryPlan(
            question=question,
            mode="record",
            query_text=question,
            field_role=state.field_role,
            field_label=state.field_role,
            filters={},
            terms=_terms(question),
            state=state,
            enumerate=state.enumerate,
            page=state.page,
            page_size=state.page_size,
            clarification="问题包含多个物品，请选择要查询的物品。",
            candidates=tuple(item_hits[:8]),
            include_future=include_future,
            reason="ITEM_AMBIGUOUS",
        )
    if len(channel_hits) > 1:
        return QueryPlan(
            question=question,
            mode="record",
            query_text=question,
            field_role=state.field_role,
            field_label=state.field_role,
            filters={},
            terms=_terms(question),
            state=state,
            enumerate=state.enumerate,
            page=state.page,
            page_size=state.page_size,
            clarification="问题包含多个渠道，请选择要查询的渠道。",
            candidates=tuple(channel_hits[:8]),
            include_future=include_future,
            reason="CHANNEL_AMBIGUOUS",
        )
    if len(price_type_hits) > 1:
        return QueryPlan(
            question=question,
            mode="record",
            query_text=question,
            field_role=state.field_role,
            field_label=state.field_role,
            filters={},
            terms=_terms(question),
            state=state,
            enumerate=state.enumerate,
            page=state.page,
            page_size=state.page_size,
            clarification="问题包含多个价格类型，请选择要查询的价格类型。",
            candidates=tuple(price_type_hits[:8]),
            include_future=include_future,
            reason="PRICE_TYPE_AMBIGUOUS",
        )
    if unknown_store and not state.store:
        return QueryPlan(
            question=question,
            mode="record",
            query_text=question,
            field_role=state.field_role,
            field_label=state.field_role,
            filters={"store": unknown_store},
            terms=_terms(question),
            state=state,
            enumerate=state.enumerate,
            page=state.page,
            page_size=state.page_size,
            unknown_store=unknown_store,
            unknown_stores=unknown_stores,
            include_future=include_future,
            reason="UNKNOWN_STORE",
        )

    filters = {
        key: str(getattr(state, key))
        for key in ("store", "item", "product", "channel", "price_type", "identifier")
        if getattr(state, key) and not (key == "store" and len(state.stores) > 1)
    }
    if state.doc_id:
        filters["doc_id"] = state.doc_id
    if state.field_role in RECORD_FIELD_ROLES:
        mode = "record"
    elif state.enumerate and (filters or state.doc_id):
        mode = "record"
    else:
        mode = "document"
    if state.field_role == "price_type":
        mode = "record" if filters else "document"
    if state.field_role in DOCUMENT_FIELD_ROLES:
        mode = "document"
    # “按通知/调整后”问的是正文通知，不是当前台账行；不能让结构化精确行覆盖通知。
    if include_future and any(word in question for word in ("通知", "调整后", "调整之后", "按")):
        mode = "document"

    missing = _required_missing(state, mode)
    if missing:
        candidates = _clarification_candidates(state, missing=missing, lexicon=lexicon)
        state.pending_slot = missing
        state.candidates = candidates
        state.field_role = state.field_role
        return QueryPlan(
            question=question,
            mode=mode,
            query_text=question,
            field_role=state.field_role,
            field_label=state.field_role,
            filters=filters,
            terms=_terms(question),
            state=state,
            enumerate=state.enumerate,
            page=state.page,
            page_size=state.page_size,
            clarification=_clarification_text(missing),
            candidates=candidates,
            include_future=include_future,
            reason="MISSING_SLOT",
        )

    terms = _terms(question, tuple(filters.values()))
    if mode == "document" and not terms and not filters:
        return QueryPlan(
            question=question,
            mode="document",
            query_text=question,
            field_role=state.field_role,
            field_label=state.field_role,
            filters=filters,
            terms=(),
            state=state,
            enumerate=state.enumerate,
            page=state.page,
            page_size=state.page_size,
            clarification="请说明要查询的物品、门店或流程名称。",
            candidates=tuple(lexicon.stores[:8]),
            include_future=include_future,
            reason="EMPTY_QUERY",
        )
    return QueryPlan(
        question=question,
        mode=mode,
        query_text=(question + " " + " ".join(filters.values())).strip(),
        field_role=state.field_role,
        field_label=state.field_role,
        filters=filters,
        terms=terms,
        state=state,
        enumerate=state.enumerate,
        page=state.page,
        page_size=state.page_size,
        include_future=include_future,
        field_roles=state.field_roles,
        missing_stores=missing_stores,
    )


def _clarification_text(missing: str) -> str:
    return {
        "product": "请补充要查询的商品名称或规格。",
        "store": "请补充要查询的门店。",
        "item": "请补充要查询的物品。",
        "channel": "请补充要查询的渠道。",
        "price_type": "请补充要查询的价格类型。",
    }.get(missing, "请补充查询条件。")
