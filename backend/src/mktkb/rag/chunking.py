"""来源保真分块。

- 表格：一行一个记录块，保留标题、表头、工作表、原始行号、完整字段；超长行拆成多个
  嵌入块，但每个块都带关键条件，且完整字段仍保存在记录块中，检索精确值时不会丢条件。
- 正文：相邻段落有界分组并保留 1 段重叠；保留页/段/标题定位；超长段落按字符边界再切。
- 所有块都有稳定 chunk_id 与内容哈希，供向量缓存按内容/模型/维度复用。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from .config import RagConfig
from .types import AtomicUnit, DocumentSpec, IndexedChunk

# 角色 -> 表头同义词。只做字段角色识别，不存放任何业务答案。
ROLE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "identifier": (
        "标识",
        "编号",
        "标准编号",
        "价格单号",
        "sku编码",
        "审批编号",
        "单号",
        "编码",
    ),
    "product": ("品名规格", "商品名称", "产品名称", "品名", "商品", "产品"),
    "channel": ("适用渠道", "渠道"),
    "price_type": ("价格类型", "价格类别", "类型"),
    "effective_from": ("生效日期", "生效期间", "开始日期", "生效时间"),
    "effective_to": ("失效日期", "结束日期", "截止日期"),
    "store": ("门店名称", "店家名称", "店铺名称", "商户名称", "门店", "店家", "店铺", "商户"),
    "item": ("物品名称", "物料名称", "物品", "物料"),
    "alias": ("别名", "俗称", "别称", "别名/俗称"),
    "price": ("参考供价", "建议零售价", "会员价", "档期特价", "箱促价", "组合价", "零售价", "价格", "单价", "金额", "特价", "供价"),
    "unit": ("计价单位", "基本单位", "单位"),
    "issued_quantity": ("实发数量", "申请数量", "领用数量"),
    "quantity": ("标准排面数", "物料数量", "排面数", "数量", "库存"),
    "location": ("存放位置", "货架/位编号", "摆放位置", "所在位置", "存放区域", "位置", "层位"),
    "note": ("搭赠/限购规则", "扣分规则", "摆放要求", "备注", "说明", "规则"),
    "date": ("更新日期", "盘点时间", "活动日期", "日期", "时间"),
    "contact": ("联系人", "负责人"),
    "phone": ("联系电话", "手机号码", "手机号", "联系方式", "电话"),
    "address": ("门店地址", "详细地址", "地址"),
    "status": ("合作状态", "状态"),
    "clause": ("条款", "条"),
    "height": ("高度区间", "高度"),
    "spec": ("规格型号", "型号规格", "规格/型号", "规格"),
}
ROLE_LABELS: dict[str, str] = {
    "identifier": "标识",
    "product": "商品",
    "channel": "渠道",
    "price_type": "价格类型",
    "effective_from": "生效日期",
    "effective_to": "失效日期",
    "store": "门店",
    "item": "物品",
    "alias": "别名",
    "price": "价格",
    "unit": "计价单位",
    "quantity": "数量",
    "issued_quantity": "发放数量",
    "location": "位置",
    "note": "备注",
    "date": "日期",
    "contact": "联系人",
    "phone": "电话",
    "address": "地址",
    "status": "合作状态",
    "clause": "条款",
    "height": "高度",
    "spec": "规格",
}
# 在拆分超长行时每个块都必须携带的关键条件角色。
KEY_ROLES: tuple[str, ...] = (
    "identifier",
    "store",
    "item",
    "product",
    "channel",
    "price_type",
    "effective_from",
    "effective_to",
    "location",
    "price",
)
_FILTER_ROLES: tuple[str, ...] = ("store", "item", "product", "channel", "price_type", "identifier")
_DATE_RE = re.compile(r"(20\d{2})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})")
_SPLIT_RE = re.compile(r"(?<=[。！？；;!?])\s*")


def normalize_field(name: object) -> str:
    from ..retrieval.tokenize import normalize

    return normalize(str(name)).strip()


def field_role(name: object) -> str | None:
    """字段名 -> 角色；支持带单位/括号的表头（如“价格(元)”）。"""
    normalized = normalize_field(name)
    if not normalized:
        return None
    for role, synonyms in ROLE_SYNONYMS.items():
        for synonym in synonyms:
            key = normalize_field(synonym)
            if normalized == key or normalized.startswith(key + "(") or normalized.startswith(key + "（"):
                return role
    # 物料编码/门店编码/经销商编码等后缀是通用 identifier，不按具体资料名白名单。
    if normalized.endswith(("编码", "编号", "单号")) and not normalized.endswith("编码规则"):
        return "identifier"
    return None


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def role_values(fields: Mapping[str, Any] | None) -> dict[str, tuple[str, ...]]:
    values: dict[str, list[str]] = {}
    for name, value in (fields or {}).items():
        role = field_role(name)
        if not role or value is None:
            continue
        text = str(value).strip()
        if not text or text in ("—", "-", "无", "None", "null"):
            continue
        if text not in values.setdefault(role, []):
            values[role].append(text)
    return {role: tuple(items) for role, items in values.items()}


def first_value(values: Mapping[str, tuple[str, ...]], role: str) -> str | None:
    items = values.get(role) or ()
    return items[0] if items else None


def parse_date(value: object) -> str | None:
    if value is None:
        return None
    match = _DATE_RE.search(str(value))
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def effective_dates(fields: Mapping[str, Any] | None) -> tuple[str | None, str | None]:
    values = role_values(fields)
    start = parse_date(first_value(values, "effective_from"))
    end = parse_date(first_value(values, "effective_to"))
    if start is None and values.get("effective_from"):
        dates = [parse_date(item) for item in values["effective_from"]]
        dates = [item for item in dates if item]
        if dates:
            start = dates[0]
            if end is None and len(dates) > 1:
                end = dates[1]
    return start, end


def _combine_effective(
    doc: DocumentSpec, unit: Any
) -> tuple[str | None, str | None]:
    starts = [value for value in (doc.effective_from, getattr(unit, "effective_from", None)) if value]
    ends = [value for value in (doc.effective_to, getattr(unit, "effective_to", None)) if value]
    start = max(starts) if starts else None
    end = min(ends) if ends else None
    return start, end


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _content_sha(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def adapt_parsed_unit(
    unit: object,
    *,
    doc: DocumentSpec,
    unit_id: str | None = None,
    ordinal: int | None = None,
) -> AtomicUnit:
    """把现有 ParsedUnit / SourceUnit 适配为隔离单元；不修改产品对象。"""
    locator = dict(getattr(unit, "locator", None) or {})
    fields = dict(getattr(unit, "fields", None) or {})
    kind = str(getattr(unit, "kind", "paragraph") or "paragraph")
    unit_key = str(getattr(unit, "unit_key", "") or "")
    raw_id = unit_id or getattr(unit, "id", None)
    if raw_id is None:
        raw_id = _stable_id(doc.doc_id, doc.version_id, unit_key, ordinal or 0)
    row = locator.get("row")
    header_row = locator.get("header_row")
    return AtomicUnit(
        unit_id=str(raw_id),
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind=kind,
        ordinal=int(getattr(unit, "ordinal", ordinal or 0) or ordinal or 0),
        unit_key=unit_key,
        text=str(getattr(unit, "text", "") or ""),
        fields=fields,
        sheet=getattr(unit, "sheet", None),
        locator=locator,
        header_row=int(header_row) if isinstance(header_row, int) else None,
        row_number=int(row) if isinstance(row, int) else None,
        title=doc.title,
        effective_from=effective_dates(fields)[0],
        effective_to=effective_dates(fields)[1],
    )


def _entity(fields: Mapping[str, Any], *, doc: DocumentSpec) -> tuple[str, str, str, dict[str, str], dict[str, object]]:
    values = role_values(fields)
    store = first_value(values, "store")
    item = first_value(values, "item")
    product = first_value(values, "product")
    channel = first_value(values, "channel")
    price_type = first_value(values, "price_type")
    identifier = first_value(values, "identifier")

    if product:
        entity_type = "product"
        key = f"product|{normalize_field(product)}|{normalize_field(channel)}|{normalize_field(price_type)}"
        label = "｜".join(part for part in (product, channel, price_type) if part)
    elif store and item:
        entity_type = "item"
        key = f"item|{normalize_field(store)}|{normalize_field(item)}"
        label = f"{store}的{item}"
    elif store:
        entity_type = "store"
        key = f"store|{normalize_field(store)}"
        label = store
    elif identifier:
        entity_type = "record"
        key = f"record|{normalize_field(identifier)}"
        label = identifier
    else:
        entity_type = "document"
        key = f"document|{doc.doc_id}"
        label = doc.title

    filters: dict[str, str] = {}
    filters_norm: dict[str, object] = {}
    for role in _FILTER_ROLES:
        value = first_value(values, role)
        if value:
            filters[role] = value
            filters_norm[role] = normalize_field(value)
    # 渠道单元格可能是一条记录覆盖多个渠道（NKA|LKA|CVS...）；硬过滤必须能匹配任一渠道。
    channel_value = first_value(values, "channel")
    if channel_value:
        parts = [part.strip() for part in re.split(r"[|｜/、,，;；\n]+", channel_value) if part.strip()]
        if len(parts) > 1:
            filters_norm["channel"] = normalize_field(parts[0])
            filters_norm["channels"] = [normalize_field(part) for part in parts]
    return entity_type, key, label, filters, filters_norm


def _row_prefix(
    doc: DocumentSpec,
    unit: AtomicUnit,
    *,
    chunk_index: int,
    chunk_count: int,
) -> str:
    parts = [f"标题: {doc.title}", f"工作表: {unit.sheet or '—'}"]
    if unit.row_number is not None:
        parts.append(f"第 {unit.row_number} 行")
    if unit.header_row is not None:
        parts.append(f"表头行: {unit.header_row}")
    if chunk_count > 1:
        parts.append(f"片段 {chunk_index + 1}/{chunk_count}")
    headers = [str(name) for name in (unit.fields or {}).keys()]
    if headers:
        # 完整字段仍保存在记录块 fields 中；嵌入文本只带关键表头，避免前缀本身超长。
        shown = headers[:10]
        header_text = " | ".join(shown)
        if len(headers) > len(shown):
            header_text += f" | …共{len(headers)}列"
        parts.append("表头: " + header_text)
    return " / ".join(parts)


def _record_chunks(doc: DocumentSpec, unit: AtomicUnit, config: RagConfig) -> list[IndexedChunk]:
    values = role_values(unit.fields)
    entity_type, entity_key, label, filters, filters_norm = _entity(unit.fields, doc=doc)
    prefix = _row_prefix(doc, unit, chunk_index=0, chunk_count=1)
    field_items = [(str(name), str(value).strip()) for name, value in (unit.fields or {}).items() if value not in (None, "")]
    full_text = prefix + " / " + "；".join(f"{name}: {value}" for name, value in field_items)

    groups: list[list[tuple[str, str]]]
    if len(full_text) <= config.chunk_max_chars or not field_items:
        groups = [field_items]
    else:
        key_items = [
            (name, value)
            for name, value in field_items
            if field_role(name) in KEY_ROLES
        ]
        other_items = [item for item in field_items if item not in key_items]
        key_text_len = len("；".join(f"{name}: {value}" for name, value in key_items))
        prefix_len = len(_row_prefix(doc, unit, chunk_index=0, chunk_count=1))
        groups = []
        current: list[tuple[str, str]] = []
        current_len = 0
        budget = max(60, config.chunk_max_chars - key_text_len - prefix_len - 40)
        for item in other_items:
            item_len = len(item[0]) + len(item[1]) + 4
            if current and current_len + item_len > budget:
                groups.append(current)
                current = []
                current_len = 0
            current.append(item)
            current_len += item_len
        if current:
            groups.append(current)
        if key_items:
            groups = [key_items + group for group in groups] if groups else [key_items]
        if not groups:
            groups = [field_items]

    chunk_count = len(groups)
    effective_from, effective_to = _combine_effective(doc, unit)
    chunks: list[IndexedChunk] = []
    base_locator = dict(unit.locator or {})
    for index, group in enumerate(groups):
        body = "；".join(f"{name}: {value}" for name, value in group)
        if not body:
            body = full_text
        text = _row_prefix(doc, unit, chunk_index=index, chunk_count=chunk_count) + " / " + body
        locator = dict(base_locator)
        locator.update({"chunk_index": index, "chunk_count": chunk_count, "unit_key": unit.unit_key})
        chunks.append(
            IndexedChunk(
                chunk_id=_stable_id("record", doc.doc_id, doc.version_id, unit.unit_key, index),
                doc_id=doc.doc_id,
                version_id=doc.version_id,
                revision=0,
                kind="record",
                ordinal=unit.ordinal * 1000 + index,
                text=text,
                title=doc.title,
                content_sha256=_content_sha(text),
                token_count=max(1, len(text)),
                sheet=unit.sheet,
                locator=locator,
                fields=dict(unit.fields),
                role_values=values,
                filters=filters,
                filters_norm=filters_norm,
                entity_type=entity_type,
                entity_key=entity_key,
                label=label,
                record_unit_id=unit.unit_id,
                unit_ids=(unit.unit_id,),
                effective_from=effective_from,
                effective_to=effective_to,
            )
        )
    return chunks


def _split_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sentences = [part for part in _SPLIT_RE.split(text) if part]
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(sentence[index : index + max_chars] for index in range(0, len(sentence), max_chars))
            continue
        if current and len(current) + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        pieces.append(current)
    return pieces or [text[:max_chars]]


def _heading(unit: AtomicUnit) -> str:
    locator = unit.locator or {}
    heading = str(locator.get("heading") or "").strip()
    return heading


def _text_chunks(doc: DocumentSpec, units: Sequence[AtomicUnit], config: RagConfig) -> list[IndexedChunk]:
    chunks: list[IndexedChunk] = []
    ordinal = 0
    index = 0
    max_chars = max(160, config.chunk_max_chars)
    max_units = max(1, config.chunk_max_units)
    overlap = max(0, min(config.chunk_overlap_units, max_units - 1))
    while index < len(units):
        start = index
        group: list[AtomicUnit] = []
        chars = 0
        while index < len(units) and len(group) < max_units:
            unit = units[index]
            text = unit.text.strip()
            if not text:
                index += 1
                continue
            if group and chars + len(text) > max_chars:
                break
            group.append(unit)
            chars += len(text)
            index += 1
        if not group:
            index += 1
            continue
        heading = next((_heading(unit) for unit in group if _heading(unit)), "")
        body = "\n".join(unit.text.strip() for unit in group if unit.text.strip())
        text = (heading + "\n" + body).strip() if heading else body
        pieces = _split_text(text, max_chars)
        page_values = [int((unit.locator or {}).get("page")) for unit in group if isinstance((unit.locator or {}).get("page"), int)]
        paragraph_values = [
            int((unit.locator or {}).get("paragraph"))
            for unit in group
            if isinstance((unit.locator or {}).get("paragraph"), int)
        ]
        locator: dict[str, Any] = {
            "heading": heading or None,
            "unit_keys": [unit.unit_key for unit in group],
        }
        if page_values:
            locator["page_start"] = min(page_values)
            locator["page_end"] = max(page_values)
            locator["page"] = min(page_values)
        if paragraph_values:
            locator["paragraph_start"] = min(paragraph_values)
            locator["paragraph_end"] = max(paragraph_values)
            locator["paragraph"] = min(paragraph_values)
        for piece_index, piece in enumerate(pieces):
            chunk_locator = dict(locator)
            chunk_locator.update({"chunk_index": piece_index, "chunk_count": len(pieces)})
            chunks.append(
                IndexedChunk(
                    chunk_id=_stable_id("text", doc.doc_id, doc.version_id, start, ordinal, piece_index),
                    doc_id=doc.doc_id,
                    version_id=doc.version_id,
                    revision=0,
                    kind="text",
                    ordinal=ordinal,
                    text=piece,
                    title=doc.title,
                    content_sha256=_content_sha(piece),
                    token_count=max(1, len(piece)),
                    sheet=None,
                    locator=chunk_locator,
                    fields={},
                    role_values={},
                    filters={},
                    filters_norm={},
                    entity_type="document",
                    entity_key=f"document|{doc.doc_id}",
                    label=doc.title,
                    record_unit_id=None,
                    unit_ids=tuple(unit.unit_id for unit in group),
                    effective_from=doc.effective_from,
                    effective_to=doc.effective_to,
                )
            )
            ordinal += 1
        # 下一块从上一块尾部重叠 1 段开始；保证至少前进 1 段。
        next_index = max(start + 1, index - overlap)
        if next_index <= index and index >= len(units):
            break
        index = next_index
    return chunks


def build_chunks(doc: DocumentSpec, units: Iterable[AtomicUnit], config: RagConfig) -> list[IndexedChunk]:
    table_units: list[AtomicUnit] = []
    text_units: list[AtomicUnit] = []
    for unit in units:
        if unit.kind == "table_row":
            table_units.append(unit)
        else:
            text_units.append(unit)
    chunks: list[IndexedChunk] = []
    for unit in table_units:
        chunks.extend(_record_chunks(doc, unit, config))
    chunks.extend(_text_chunks(doc, text_units, config))
    return chunks


def chunk_debug_summary(chunks: Sequence[IndexedChunk]) -> dict[str, Any]:
    return {
        "count": len(chunks),
        "record_count": sum(1 for chunk in chunks if chunk.kind == "record"),
        "text_count": sum(1 for chunk in chunks if chunk.kind == "text"),
        "chars": sum(len(chunk.text) for chunk in chunks),
        "sha256": hashlib.sha256(
            json.dumps([chunk.chunk_id for chunk in chunks], ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }
