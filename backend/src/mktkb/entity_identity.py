"""实体身份：来源（检索索引）侧与产品事实（rag 分块）侧共用同一套 ``entity_key`` 派生。

同一条 ``SourceUnit`` 在两条链上各派生一次实体键：

- 检索索引写 ``retrieval_unit_index.entity_key``（评测 ``db_projection.units`` 读它）；
- rag 分块写 ``rag_chunks.entity_key``（``direct_rag_answer.facts[].entity_key`` 读它，
  ``rag.facts`` 也用它核对事实与来源块是否同一实体）。

两处曾各自硬编码键形态，同一记录得到 ``item|id:p01`` 与 ``item|城东店|宣传海报`` 两个不同键，
评测 ``cross_entity`` 轴因此判不出身份一致（``entity_identity_unresolved``）。键形态此后只在
本模块定义，两侧都调用它，避免再出现两套词法。

键形态只有两种，不按资料/题面/业务数据分支：

- 有「标识」列：``<entity_type>|id:<归一化标识值>``。权威形态：它是记录级唯一身份，
  也是冻结合同 target 使用的形态，检索侧 ``_has_identifier`` 按 ``|id:`` 决定能否跨资料合并。
- 无「标识」列：``<name_key>|doc:<document_id>|unit:<unit_id>``。名称本身不能区分同店同物的
  多行记录（检索侧既有语义：无标识不跨行/跨资料合并，只成为独立候选），所以必须带资料与
  单元身份。

归一化两侧共用 ``mktkb.retrieval.tokenize.normalize``（NFKC + 空白折叠 + casefold），
不做前缀/包含/模糊匹配。
"""

from __future__ import annotations

from typing import Any, Mapping

#: 标识列表头：检索索引与 rag 分块共用的唯一判据（与既有多资料表头一致）。
IDENTIFIER_HEADERS: tuple[str, ...] = ("标识", "编号", "id", "ID")


def _normalize(value: object) -> str:
    from .retrieval.tokenize import normalize

    return normalize(str(value))


def is_identifier_header(name: object) -> bool:
    """表头是否为标识列（两侧共用；不按资料名白名单扩表）。"""
    cleaned = str(name).strip()
    return cleaned in IDENTIFIER_HEADERS or cleaned.lower() in ("id", "编号")


def identifier_value(fields: Mapping[str, Any] | None) -> str | None:
    """首个带值的标识列原值（未归一化）；空白值按“无标识”处理。"""
    for name, value in (fields or {}).items():
        if is_identifier_header(name) and value not in (None, ""):
            return str(value).strip() or None
    return None


def build_entity_key(
    entity_type: str,
    *,
    name_key: str,
    identifier: str | None = None,
    document_id: object = None,
    unit_id: object = None,
) -> str:
    """派生实体键：有标识按标识，无标识退回“名称 + 资料 + 单元”。"""
    if identifier:
        return f"{entity_type}|id:{_normalize(identifier)}"
    return f"{name_key}|doc:{document_id}|unit:{unit_id}"
