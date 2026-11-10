"""T06 自然语言问题 -> T05 QueryIntent（一般化字段/实体识别，不按题号或整句硬编码）。

规则来源：
- 业务字段/别名复用 ``retrieval.index.HEADER_ROLES`` 与已建成索引里的实体标签，不新写业务词典；
- 门店/物品名来自当前检索索引中真实存在的实体标签，别名来自索引的 alias 字段角色；
- 上下文只继承"已明确实体条件"和最近最多 3 条用户问题，不把历史助手答案当事实；
- 不认识的业务字段（营业时间/负责人/库存/销售额/采购价格/营业执照号）只用于说明缺失，
  不传给检索层当筛选键。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..retrieval.models import RetrievalFieldIndex, RetrievalUnitIndex
from ..retrieval.tokenize import cut, normalize
from ..retrieval.types import QueryIntent
from ..rag.query import (
    GENERIC_FIELD_WORDS,
    financial_metric_question,
    identifier_shape,
    is_regulation_question,
    match_identifier,
)
from ..text_zh import iter_store_names

# 受支持的记录字段（能由检索层按角色取原值）
FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "位置": ("位置", "在哪", "哪里", "放哪", "放到哪", "放在哪", "哪儿", "存放"),
    "联系人": ("联系人",),
    "电话": ("联系电话", "电话", "号码"),
    "地址": ("地址",),
    "合作状态": ("合作状态", "合作关系", "合作"),
}
# 业务上可能被问到、但当前资料/契约没有的字段：只用于 missing_fields 说明
MISSING_FIELD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "负责人": ("负责人",),
    "营业时间": ("营业时间", "几点营业", "几点开门", "营业"),
    "库存": ("库存", "剩余", "还剩", "多少张", "多少个"),
    "销售额": ("销售额", "营业额", "销售"),
    "采购价格": ("采购价格", "采购价", "价格", "多少钱"),
    "营业执照号": ("营业执照号", "营业执照", "执照号"),
}
#: T101/ERR-03：上表里同时会出现在法规/制度题干中的泛化词。词表与
#: ``rag.query.GENERIC_FIELD_WORDS`` 同源（同一批词不重复登记），只有问题里确有门店与物品
#: （确有所指记录）、且没有更明确的字段说法时，才判成“资料未记录该字段”；法规/制度题一律不判。
MISSING_FIELD_GENERIC_WORDS: dict[str, tuple[str, ...]] = {
    "销售额": GENERIC_FIELD_WORDS["sales"],
    "采购价格": GENERIC_FIELD_WORDS["price"],
}
STOPWORDS: frozenset[str] = frozenset(
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
        "哪些步骤",
    }
)
STORE_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,6}店")  # 兼容旧引用；实体识别统一走 text_zh.iter_store_names
MAX_DOC_TERMS = 8
MAX_CANDIDATES = 8
# 裸补槽追问（D-IA-2）：去掉实体片段后只允许剩下这些语气/指代碎片。
_FOLLOWUP_FILLERS: tuple[str, ...] = (
    "的话",
    "那个",
    "这个",
    "那家",
    "这家",
    "那边",
    "这边",
    "门店",
    "呢",
    "啊",
    "呀",
    "吧",
    "就",
    "是",
    "那",
    "这",
    "的",
)
_FOLLOWUP_PUNCTUATION = " \t，,。.？?！!、；;：:　\"'“”‘’（）()【】[]"
MAX_FOLLOWUP_CHARS = 16
IDENTIFIER_MARKERS: tuple[str, ...] = ("标识", "编号")


@dataclass(frozen=True)
class EntityLexicon:
    """当前索引中的实体标签与别名；每次询问现读，不写回词典。"""

    store_labels: tuple[str, ...] = ()
    item_labels: tuple[str, ...] = ()
    identifier_labels: tuple[str, ...] = ()
    alias_to_labels: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def known(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.store_labels) | set(self.item_labels)))


@dataclass(frozen=True)
class IntentPlan:
    """意图解析结果；clarification 非空时不检索、不调用模型。"""

    mode: str
    intent: QueryIntent | None
    requested_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    entities: dict[str, str] = field(default_factory=dict)
    clarification: str | None = None
    candidates: tuple[tuple[str, str], ...] = ()
    unknown_store: str | None = None
    identifier: str | None = None
    unknown_identifier: str | None = None
    #: P1-FIX/A：问题在问公司级经营/财务指标（营收/利润率等）。
    #: 这里只标记“问的是哪类指标”；是否拒答由 service 层在检索后做资料支持判定。
    out_of_scope: str | None = None


def load_lexicon(db: Session) -> EntityLexicon:
    """读取当前检索索引中的实体标签与别名；索引为空时返回空词典。"""
    stores: set[str] = set()
    items: set[str] = set()
    labels_by_unit: dict[str, str] = {}
    rows = db.execute(
        select(
            RetrievalUnitIndex.entity_type,
            RetrievalUnitIndex.label,
            RetrievalUnitIndex.entity_filters,
            RetrievalUnitIndex.unit_id,
        ).where(RetrievalUnitIndex.entity_type.in_(("store", "item")))
    ).all()
    for entity_type, label, filters, unit_id in rows:
        filters = dict(filters or {})
        store_name = str(filters.get("store") or "").strip()
        item_name = str(filters.get("item") or "").strip()
        # 门店名也存在于物品/位置记录里：只要有门店筛选值就纳入词表，
        # 这样仅发布物品位置表时也能按门店条件检索（店家记录不是唯一来源）。
        if store_name:
            stores.add(store_name)
        if item_name:
            items.add(item_name)
        if entity_type == "store":
            name = store_name or str(label or "").strip()
            if name:
                labels_by_unit[str(unit_id)] = name
        elif entity_type == "item":
            # 索引中的物品实体 label 是"门店的物品"；对外实体名取筛选条件里的物品原值
            name = item_name or str(label or "").strip()
            if name:
                labels_by_unit[str(unit_id)] = name

    alias_rows = db.execute(
        select(RetrievalFieldIndex.unit_id, RetrievalFieldIndex.value_text).where(
            RetrievalFieldIndex.field_role == "alias"
        )
    ).all()
    alias_map: dict[str, set[str]] = {}
    for unit_id, value in alias_rows:
        label = labels_by_unit.get(str(unit_id))
        if not label or not value:
            continue
        normalized = normalize(str(value))
        if normalized:
            alias_map.setdefault(normalized, set()).add(label)

    return EntityLexicon(
        store_labels=tuple(sorted(stores)),
        item_labels=tuple(sorted(items)),
        identifier_labels=_load_identifier_labels(db),
        alias_to_labels={key: tuple(sorted(values)) for key, values in alias_map.items()},
    )


def _load_identifier_labels(db: Session) -> tuple[str, ...]:
    """索引里已落库的标识值（D-IA-1）。

    检索索引把“标识/编号”列拆成实体标识角色（物品记录 -> item_id，店家记录 -> store_id）；
    两套角色名指向同一批标识原值，这里合并成一个词表，供意图层复用同一个标识匹配口径，
    不新写编号词典/解析器。
    """
    rows = db.execute(
        select(RetrievalFieldIndex.value_text).where(
            RetrievalFieldIndex.field_role.in_(("identifier", "item_id", "store_id"))
        )
    ).all()
    values = {str(row[0]).strip() for row in rows if str(row[0] or "").strip()}
    return tuple(sorted(values))


def _match_labels(text: str, labels: tuple[str, ...]) -> list[str]:
    """在问题中查找标签（规范化后子串）；长标签优先且不重复占用同一片段。"""
    normalized = normalize(text)
    consumed = [False] * len(normalized)
    found: list[str] = []
    for label in sorted(set(labels), key=lambda item: (-len(item), item)):
        key = normalize(label)
        if not key:
            continue
        start = normalized.find(key)
        while start != -1:
            end = start + len(key)
            if not any(consumed[start:end]):
                for index in range(start, end):
                    consumed[index] = True
                found.append(label)
                break
            start = normalized.find(key, start + 1)
    return found


def _alias_labels(question: str, lexicon: EntityLexicon) -> list[str]:
    normalized = normalize(question)
    found: list[str] = []
    for alias, labels in lexicon.alias_to_labels.items():
        if alias and alias in normalized:
            for label in labels:
                if label not in found:
                    found.append(label)
    return found


def _unknown_store(question: str, matched_stores: list[str], lexicon: EntityLexicon) -> str | None:
    known = {normalize(label) for label in lexicon.store_labels}
    # T09-D2：与解析层共用同一门店名口径，避免把"发现店家""门店领取"里的片段当成门店
    for _offset, token in iter_store_names(question):
        normalized = normalize(token)
        if normalized in known:
            continue
        if any(normalized in normalize(label) for label in matched_stores):
            continue
        return token
    return None


def _document_terms(question: str) -> tuple[str, ...]:
    terms: list[str] = []
    for token in cut(question):
        cleaned = token.strip()
        if len(cleaned) < 2 or cleaned in STOPWORDS:
            continue
        if cleaned.isdigit():
            continue
        if cleaned not in terms:
            terms.append(cleaned)
        if len(terms) >= MAX_DOC_TERMS:
            break
    return tuple(terms)


def _field_hits(question: str, synonyms: dict[str, tuple[str, ...]]) -> list[str]:
    normalized = normalize(question)
    hits: list[str] = []
    for label, words in synonyms.items():
        if any(normalize(word) in normalized for word in words):
            hits.append(label)
    return hits


def _missing_field_hits(question: str, *, has_record_entity: bool) -> list[str]:
    """缺失字段判定（T101/ERR-03）：法规/制度题优先，泛化词要有所指记录实体的语境。

    - 法规/制度题问的是条文本身（「价格欺诈」「有奖销售」是术语），不判缺失字段；
    - 「价格」「销售」这类泛化词只有在问题同时给出门店与物品（确有所指记录），且没有更明确
      的字段说法时，才判成“资料未记录采购价格/销售额”。只提商品/渠道的价格题属于价目表
      取值问题，不能被意图层提前截断。
    """
    if is_regulation_question(question):
        return []
    normalized = normalize(question)
    hits: list[str] = []
    for label, words in MISSING_FIELD_SYNONYMS.items():
        if not any(normalize(word) in normalized for word in words):
            continue
        generic = MISSING_FIELD_GENERIC_WORDS.get(label, ())
        if generic and not has_record_entity:
            specific = tuple(word for word in words if word not in generic)
            if not any(normalize(word) in normalized for word in specific):
                continue
        hits.append(label)
    return hits


def _previous_item(context_questions: tuple[str, ...], lexicon: EntityLexicon) -> str | None:
    """上一轮问题里唯一明确的物品名；没有/多个都不继承（避免猜对象）。

    裸补槽追问可能紧跟在“澄清”轮之后：此时上一轮没有可回显来源，产品上下文实体为空，
    物品/字段只能从上一轮问题文本恢复。只取唯一物品，不含检索词扩展。
    """
    if not context_questions:
        return None
    previous = context_questions[-1]
    items = _match_labels(previous, lexicon.item_labels)
    for alias_label in _alias_labels(previous, lexicon):
        if alias_label in lexicon.item_labels and alias_label not in items:
            items.append(alias_label)
    return items[0] if len(items) == 1 else None


def _bare_entity_followup(question: str, *, stores: list[str], lexicon: EntityLexicon) -> bool:
    """问题是否只是“补一个实体值”的短追问（D-IA-2）。

    只认“去掉本次命中的门店/别名后什么都不剩”的短句（如“湖滨店”“湖滨店呢”“江湾店的话”）。
    只要还有其它信息（物品、字段词、疑问词、资料名等）就当作新的完整问题，不强行继承旧槽。
    """
    text = normalize(question)
    if not text or len(text) > MAX_FOLLOWUP_CHARS:
        return False
    for label in sorted(set(stores), key=lambda item: (-len(item), item)):
        key = normalize(label)
        if key:
            text = text.replace(key, "")
    for alias, labels in lexicon.alias_to_labels.items():
        if alias and any(label in stores for label in labels):
            text = text.replace(alias, "")
    for filler in _FOLLOWUP_FILLERS:
        text = text.replace(normalize(filler), "")
    return text.strip(_FOLLOWUP_PUNCTUATION) == ""


def _unknown_identifier(question: str, identifier: str | None, lexicon: EntityLexicon) -> str | None:
    """问题显式写了“标识/编号”但值不在索引里：不得拿别的行当答案。"""
    if identifier:
        return None
    normalized = normalize(question)
    if not any(normalize(marker) in normalized for marker in IDENTIFIER_MARKERS):
        return None
    shape = identifier_shape(question)
    if not shape:
        return None
    known = {normalize(value) for value in lexicon.identifier_labels}
    return None if normalize(shape) in known else shape


def _candidate_questions(
    lexicon: EntityLexicon, *, stores: list[str], item: str | None, requested_fields: tuple[str, ...]
) -> tuple[tuple[str, str], ...]:
    """澄清候选：按门店给出可直接发送的完整追问；没有门店维度时按物品给出。"""
    field_text = "".join(requested_fields) if requested_fields else "信息"
    candidates: list[tuple[str, str]] = []
    for store in stores[:MAX_CANDIDATES]:
        if item:
            followup = f"{store}的{item}在哪里？" if "位置" in requested_fields else f"{store}的{item}的{field_text}是什么？"
        else:
            followup = f"{store}的{field_text}是什么？"
        candidates.append((store, followup))
    if not candidates and item:
        for label in lexicon.store_labels[:MAX_CANDIDATES]:
            candidates.append((label, f"{label}的{item}在哪里？" if "位置" in requested_fields else f"{label}的{item}的{field_text}是什么？"))
    return tuple(candidates)


def parse_question(
    question: str,
    *,
    lexicon: EntityLexicon,
    context_entities: dict[str, str] | None = None,
    context_questions: tuple[str, ...] = (),
) -> IntentPlan:
    """把自然语言问题解析为 QueryIntent 或澄清计划。

    不读取题号/预期答案；实体与别名都来自当前索引。上下文只补足问题中缺失的明确实体。
    ``context_questions`` 只用于“裸补槽短追问”时恢复上一轮所问字段（D-IA-2），
    不把历史助手答案当事实。
    """
    context_entities = dict(context_entities or {})
    # P1-FIX/A：公司级经营/财务指标（营收/利润率等）不在当前语料范围。先标记，
    # 仍走正文检索以做“资料支持判定”（证据里确有该指标数值时不拒答）；判定在
    # service 层检索后、任何模型调用前完成。
    out_of_scope = financial_metric_question(question)
    if out_of_scope:
        return IntentPlan(
            mode="document",
            intent=QueryIntent(mode="document", terms=_document_terms(question)),
            out_of_scope=out_of_scope,
        )
    stores = _match_labels(question, lexicon.store_labels)
    item_labels = _match_labels(question, lexicon.item_labels)
    for alias_label in _alias_labels(question, lexicon):
        if alias_label in lexicon.item_labels and alias_label not in item_labels:
            item_labels.append(alias_label)
        elif alias_label in lexicon.store_labels and alias_label not in stores:
            stores.append(alias_label)

    identifier = match_identifier(question, lexicon.identifier_labels) if lexicon.identifier_labels else None
    unknown_identifier = _unknown_identifier(question, identifier, lexicon)
    if unknown_identifier:
        return IntentPlan(
            mode="record",
            intent=None,
            unknown_identifier=unknown_identifier,
        )

    unknown_store = _unknown_store(question, stores, lexicon) if not stores else None
    if unknown_store:
        return IntentPlan(
            mode="record",
            intent=QueryIntent(mode="record", entity_filters={"store": unknown_store}),
            entities={"store": unknown_store},
            unknown_store=unknown_store,
        )

    if len(stores) > 1:
        return IntentPlan(
            mode="record",
            intent=None,
            entities={},
            clarification="问题中包含多个门店，请选择要查询的门店。",
            candidates=_candidate_questions(
                lexicon, stores=stores, item=item_labels[0] if item_labels else None, requested_fields=()
            ),
        )
    if len(item_labels) > 1:
        return IntentPlan(
            mode="record",
            intent=None,
            entities={},
            clarification="问题中包含多个物品，请明确要查询的物品。",
            candidates=tuple((label, f"{label}在哪里？") for label in item_labels[:MAX_CANDIDATES]),
        )

    store = stores[0] if stores else None
    item = item_labels[0] if item_labels else None
    explicit_store = store is not None
    explicit_item = item is not None
    previous_item = _previous_item(context_questions, lexicon)

    record_fields = _field_hits(question, FIELD_SYNONYMS)
    missing_fields = _missing_field_hits(
        question, has_record_entity=bool(stores) and bool(item_labels)
    )
    # "负责人"是资料未记录的字段，不能被当作联系人命中
    if "负责人" in missing_fields:
        record_fields = [name for name in record_fields if name != "联系人"]
        if any(normalize(word) in normalize(question) for word in ("负责人",)):
            record_fields = []

    # 明确实体可继承：新明确对象覆盖旧对象；问题没有新对象时补足上下文中的实体。
    # 门店级字段（联系人/电话/地址/合作状态）不继承物品，避免把店家记录误配到物品行。
    # D-IA-2：短追问（只补一个门店值）必须保留上一轮的物品与所问字段；新的完整问题
    # （含物品/字段/其它检索信息）仍按“新话题”处理，不强行继承旧物品。
    store_level = bool(set(record_fields) & {"联系人", "电话", "地址", "合作状态"})
    bare_followup = (
        not explicit_item
        and not record_fields
        and not missing_fields
        and not store_level
        and bool(stores)
        and (bool(context_entities) or previous_item is not None)
        and _bare_entity_followup(question, stores=stores, lexicon=lexicon)
    )
    if bare_followup and not record_fields and context_questions:
        # 上一轮问的是可复用字段（位置/联系人/电话/地址/合作状态）时，按原字段继续问，
        # 避免把“江湾店”这类补槽变成全表检索。
        previous_fields = _field_hits(context_questions[-1], FIELD_SYNONYMS)
        previous_missing = _missing_field_hits(
            context_questions[-1],
            has_record_entity=bool(_match_labels(context_questions[-1], lexicon.store_labels))
            and bool(_match_labels(context_questions[-1], lexicon.item_labels)),
        )
        if previous_fields and not previous_missing:
            record_fields = list(previous_fields)
            store_level = bool(set(record_fields) & {"联系人", "电话", "地址", "合作状态"})
            if store_level:
                bare_followup = False  # 已转为记录型字段问题，按字段分支处理
    if store is None and context_entities.get("store"):
        store = context_entities["store"]
    inherited_item = context_entities.get("item") or (previous_item if bare_followup else None)
    if item is None and inherited_item and not store_level and (bare_followup or not explicit_store):
        item = inherited_item

    entities: dict[str, str] = {}
    if store:
        entities["store"] = store
    if item:
        entities["item"] = item
    explicit_entities: dict[str, str] = {}
    if explicit_store:
        explicit_entities["store"] = stores[0]
    if explicit_item:
        explicit_entities["item"] = item_labels[0]

    if record_fields:
        if not store and not item:
            if identifier:
                # 只有标识、没有门店/物品：产品检索层没有标识筛选键，交给 rag 内核才安全；
                # 内核没接手时由上层失败关闭（不退回未受限检索）。
                return IntentPlan(
                    mode="record",
                    intent=None,
                    requested_fields=tuple(record_fields),
                    missing_fields=tuple(missing_fields),
                    identifier=identifier,
                )
            return IntentPlan(
                mode="record",
                intent=None,
                requested_fields=tuple(record_fields),
                missing_fields=tuple(missing_fields),
                clarification="请补充要查询的门店或物品。",
                candidates=_candidate_questions(
                    lexicon, stores=list(lexicon.store_labels), item=None, requested_fields=record_fields
                ),
            )
        filters: dict[str, str] = {}
        if store:
            filters["store"] = store
        if item:
            filters["item"] = item
        # 只有门店、查询店家字段时使用门店条件；门店+物品用于位置类记录。
        return IntentPlan(
            mode="record",
            intent=QueryIntent(mode="record", entity_filters=filters, requested_fields=tuple(record_fields)),
            requested_fields=tuple(record_fields),
            missing_fields=tuple(missing_fields),
            entities=entities,
            identifier=identifier,
        )

    terms = _document_terms(question)
    if not terms and not entities:
        return IntentPlan(
            mode="document",
            intent=None,
            missing_fields=tuple(missing_fields),
            clarification="请说明要查询的物品、门店或流程名称。",
            candidates=_candidate_questions(
                lexicon, stores=list(lexicon.store_labels), item=None, requested_fields=record_fields
            ),
        )
    document_filters = dict(explicit_entities)
    if bare_followup and item and "item" not in document_filters:
        # 裸补槽追问：把继承来的物品写进本次过滤，避免同门店其它物品行混进回答。
        document_filters["item"] = item
    return IntentPlan(
        mode="document",
        intent=QueryIntent(mode="document", terms=terms, entity_filters=document_filters),
        requested_fields=tuple(record_fields),
        missing_fields=tuple(missing_fields),
        entities=entities,
    )
