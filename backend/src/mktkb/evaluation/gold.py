"""稳定引用解析（P0 设计 §7.2）：``doc_code`` + ``unit_key`` / ``locator`` -> 当前索引 unit。

fail closed 口径：

- ``unit_key`` 是**身份型**引用：必须恰好命中 1 个 unit。0 个 -> ``unit_key_not_found``；
  同一 ``doc_code`` 下出现两个同名 ``unit_key`` -> ``duplicate_unit_key``（不挑一个）；
- ``locator`` 是**范围型**引用：一页 / 一张表 / 整篇可以包含多个 unit（例如“把 NKA 卖场
  组合价全部列出来”的 gold 是整张表）。命中 0 个 -> ``locator_not_found``；命中多个但
  ``unit_key`` 有重复 -> ``ambiguous_units``（同一身份无法区分）；
- ``doc_code`` 只解析到**当前可见**（``state=active`` 且 ``is_current``）的文档；
- 多个 chunk 命中同一 unit 时按 unit 去重（这里解析的是 unit，chunk 去重由 scorer 复用 unit 口径）；
- ``requires_ocr=true`` 的 case 在 P0 显式 ``skipped``：不解析、不触发 OCR、不算通过。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .dataset import LOCATOR_KEYS, CaseSpec

__all__ = ["GoldUnresolved", "ResolvedGold", "ResolvedSource", "resolve_case", "resolve_gold"]


class GoldUnresolved(Exception):
    """0 / 多匹配或文档不可见：case gold 无法定位到唯一（或明确范围）unit。"""

    def __init__(self, case_id: str, reason: str, *, doc_code: str | None = None, detail: str = "") -> None:
        self.case_id = str(case_id)
        self.reason = str(reason)
        self.doc_code = doc_code
        self.detail = str(detail)
        message = f"{self.case_id}: gold 无法解析（{self.reason}）"
        if doc_code:
            message += f" doc_code={doc_code}"
        if detail:
            message += f": {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class ResolvedSource:
    """一条稳定引用解析出的当前 unit 集合。"""

    doc_code: str
    doc_id: str
    unit_ids: tuple[str, ...]
    unit_keys: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedGold:
    """一条 case 的 gold 解析结果；``relevant_unit_ids`` 才是检索指标口径。"""

    case_id: str
    requires_ocr: bool
    skipped: bool
    sources: tuple[ResolvedSource, ...]
    unit_ids: tuple[str, ...]
    relevant_unit_ids: tuple[str, ...]


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if actual is None or expected is None:
        return actual is expected
    return actual == expected or str(actual) == str(expected)


def _visible_documents(index: Any) -> list[dict[str, Any]]:
    documents = index.list_documents()
    return [
        dict(document)
        for document in documents
        if str(document.get("state")) == "active" and bool(document.get("is_current"))
    ]


def _locate_document(case_id: str, doc_code: str, index: Any) -> dict[str, Any]:
    matches = [
        document
        for document in _visible_documents(index)
        if str(document.get("doc_id")) == doc_code or str(document.get("logical_id")) == doc_code
    ]
    if not matches:
        raise GoldUnresolved(case_id, "document_not_found", doc_code=doc_code)
    if len(matches) > 1:
        raise GoldUnresolved(
            case_id,
            "document_ambiguous",
            doc_code=doc_code,
            detail=f"{len(matches)} 个可见文档匹配",
        )
    return matches[0]


def _document_units(index: Any, doc_id: str) -> list[Any]:
    from sqlalchemy import select

    from ..rag.models import RagUnit

    with index.session() as session:
        rows = session.execute(select(RagUnit).where(RagUnit.doc_id == doc_id)).scalars().all()
    # 稳定顺序：按解析序号，其次 unit_id；不依赖数据库返回顺序。
    return sorted(rows, key=lambda row: (int(row.ordinal), str(row.unit_id)))


def _unit_value(unit: Any, key: str) -> Any:
    locator = dict(unit.locator or {})
    if key == "kind":
        return unit.kind
    if key == "sheet":
        return unit.sheet if unit.sheet is not None else locator.get("sheet")
    if key == "row":
        return locator.get("row", unit.row_number)
    return locator.get(key)


def _match_locator(case_id: str, doc_code: str, locator: Mapping[str, Any], unit: Any) -> bool:
    for key, expected in locator.items():
        if key not in LOCATOR_KEYS:
            raise GoldUnresolved(
                case_id,
                "unsupported_locator_key",
                doc_code=doc_code,
                detail=f"locator 只允许 {sorted(LOCATOR_KEYS)}，收到 {key!r}",
            )
        if not _same(_unit_value(unit, str(key)), expected):
            return False
    return True


def _resolve_source(case_id: str, ref: Mapping[str, Any], index: Any) -> ResolvedSource:
    from .dataset import _validate_source_ref  # 复用同一套字段规则（未知字段直接失败）

    locator = ref.get("locator") if isinstance(ref, Mapping) else None
    if isinstance(locator, Mapping):
        unknown = set(locator) - LOCATOR_KEYS
        if unknown:
            raise GoldUnresolved(
                case_id,
                "unsupported_locator_key",
                detail=f"locator 只允许 {sorted(LOCATOR_KEYS)}，收到 {sorted(str(key) for key in unknown)}",
            )
    try:
        source = _validate_source_ref(ref, f"{case_id}.expected_sources")
    except ValueError as exc:
        raise GoldUnresolved(case_id, "invalid_source_reference", detail=str(exc)) from exc
    doc_code = str(source["doc_code"])
    document = _locate_document(case_id, doc_code, index)
    doc_id = str(document["doc_id"])
    units = _document_units(index, doc_id)

    if "unit_key" in source:
        unit_key = str(source["unit_key"])
        matches = [unit for unit in units if str(unit.unit_key) == unit_key]
        if not matches:
            raise GoldUnresolved(
                case_id,
                "unit_key_not_found",
                doc_code=doc_code,
                detail=f"unit_key={unit_key!r}，文档 unit 数 {len(units)}",
            )
        if len(matches) > 1:
            raise GoldUnresolved(
                case_id,
                "duplicate_unit_key",
                doc_code=doc_code,
                detail=f"unit_key={unit_key!r} 命中 {len(matches)} 个 unit",
            )
    elif "locator" in source:
        locator = dict(source["locator"])
        matches = [unit for unit in units if _match_locator(case_id, doc_code, locator, unit)]
        if not matches:
            raise GoldUnresolved(
                case_id,
                "locator_not_found",
                doc_code=doc_code,
                detail=f"locator={locator!r}，文档 unit 数 {len(units)}",
            )
        keys = [str(unit.unit_key) for unit in matches]
        if len(keys) != len(set(keys)):
            raise GoldUnresolved(
                case_id,
                "ambiguous_units",
                doc_code=doc_code,
                detail=f"locator 命中 {len(matches)} 个 unit，其中 unit_key 重复",
            )
    else:
        matches = units
        if not matches:
            raise GoldUnresolved(
                case_id,
                "document_has_no_units",
                doc_code=doc_code,
                detail="整篇级 gold 没有可解析 unit",
            )

    ordered = sorted(matches, key=lambda unit: (int(unit.ordinal), str(unit.unit_id)))
    return ResolvedSource(
        doc_code=doc_code,
        doc_id=doc_id,
        unit_ids=_dedupe([str(unit.unit_id) for unit in ordered]),
        unit_keys=_dedupe([str(unit.unit_key) for unit in ordered]),
    )


def resolve_case(case: CaseSpec, index: Any) -> ResolvedGold:
    """解析单条 case；任何 unresolved 都抛 ``GoldUnresolved``。"""
    if case.requires_ocr:
        return ResolvedGold(
            case_id=case.case_id,
            requires_ocr=True,
            skipped=True,
            sources=(),
            unit_ids=(),
            relevant_unit_ids=(),
        )
    sources = tuple(_resolve_source(case.case_id, ref, index) for ref in case.expected_sources)
    if case.relevant_units:
        relevant_sources = tuple(_resolve_source(case.case_id, ref, index) for ref in case.relevant_units)
    else:
        relevant_sources = sources
    return ResolvedGold(
        case_id=case.case_id,
        requires_ocr=False,
        skipped=False,
        sources=sources,
        unit_ids=_dedupe([unit_id for source in sources for unit_id in source.unit_ids]),
        relevant_unit_ids=_dedupe([unit_id for source in relevant_sources for unit_id in source.unit_ids]),
    )


def resolve_gold(cases: Sequence[CaseSpec], index: Any) -> list[ResolvedGold]:
    """按输入顺序解析整个数据集；任一 case 失败立即抛 ``GoldUnresolved``（不跳过）。"""
    return [resolve_case(case, index) for case in cases]
