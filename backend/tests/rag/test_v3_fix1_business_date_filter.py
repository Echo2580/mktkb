"""v3-fix-1/B 合成回归：legacy 证据面按业务日过滤过期版本（只做时间维度过滤）。

离线合成数据：``LegacyIndex`` 建临时 SQLite（真实 ``SourceUnit`` + 检索索引 +
``prepare_version_index``），直接调用产品检索入口 ``retrieve(..., as_of=...)``。
不建产品库、不调模型/embedding/rerank、不开端口、不发请求。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mktkb.rag import AtomicUnit, DocumentSpec
from mktkb.rag.legacy import LegacyIndex
from mktkb.retrieval.service import _as_of_bound, retrieve
from mktkb.retrieval.types import QueryIntent, QueryRejected

INTENT = QueryIntent(
    mode="record",
    entity_filters={"store": "城东店", "item": "宣传海报"},
    requested_fields=("位置",),
)

V03_LOCATION = "A区3号货架第二层"
D01_LOCATION = "D区暂存柜"
V05_LOCATION = "E区新柜"


def _doc(doc_id: str, label: str) -> DocumentSpec:
    return DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"fixtures/synthetic/{doc_id}.xlsx",
        title="物品位置表",
        file_kind="xlsx",
        version_id=f"{doc_id}-v1",
        version_label=label,
        sha256=hashlib.sha256(doc_id.encode("utf-8")).hexdigest(),
        business_date=None,
    )


def _row(
    doc: DocumentSpec,
    *,
    ordinal: int,
    location: str,
    effective_from: str,
    effective_to: str | None,
) -> AtomicUnit:
    fields = {
        "标识": "P01",
        "门店": "城东店",
        "物品": "宣传海报",
        "位置": location,
        "生效日期": effective_from,
    }
    # L1 null_semantics = not_asserted：失效日期为 null 时语料写哨兵“未声明”。
    fields["失效日期"] = effective_to if effective_to is not None else "未声明"
    return AtomicUnit(
        unit_id=f"{doc.doc_id}-row-{ordinal}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=ordinal,
        unit_key=f"sheet:物品位置:row:{8 + ordinal}",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=fields,
        sheet="物品位置",
        locator={"sheet": "物品位置", "row": 8 + ordinal, "header_row": 7},
        row_number=8 + ordinal,
        title=doc.title,
    )


@pytest.fixture
def versioned_legacy(tmp_path: Path):
    """同一标识（P01）三个版本，窗口互不重叠：V03 → D01 → V05（末端 not_asserted）。"""
    legacy = LegacyIndex(tmp_path / "legacy-b.sqlite3")
    v03, d01, v05 = _doc("V03", "历史V1"), _doc("D01", "当前V2"), _doc("V05", "新版V3")
    legacy.build(
        [
            (v03, [_row(v03, ordinal=0, location=V03_LOCATION, effective_from="2026-01-05", effective_to="2026-04-30")]),
            (d01, [_row(d01, ordinal=0, location=D01_LOCATION, effective_from="2026-05-01", effective_to="2026-10-31")]),
            (v05, [_row(v05, ordinal=0, location=V05_LOCATION, effective_from="2026-12-01", effective_to=None)]),
        ]
    )
    try:
        yield legacy
    finally:
        legacy.close()


def _retrieve(legacy: LegacyIndex, *, as_of: str | None):
    with legacy.database.session() as session:
        return retrieve(session, INTENT, revision=legacy.revision, limit=20, as_of=as_of)


# ------------------------------------------------------------------ 正例：过滤前后对比


def test_filter_drops_superseded_version_and_keeps_order(versioned_legacy):
    before = _retrieve(versioned_legacy, as_of=None)
    after = _retrieve(versioned_legacy, as_of="2026-10-15")

    # 过滤前：同一标识的三个版本同时“现行”，产品因此判冲突（= 登记的 P01 碰撞）。
    assert before.kind == "conflict"
    assert len(before.units) == 3

    # 过滤后：只有窗口覆盖业务日的那一版进入证据面，冲突消失、引用不再含过期行。
    assert after.kind == "matches"
    assert len(after.units) == 1
    assert after.units[0].fields["位置"] == D01_LOCATION
    assert after.units[0].fields["失效日期"] == "2026-10-31"

    # 只做时间过滤：存活单元的相对顺序与过滤前完全一致（召回/排序未被改动）。
    before_ids = [str(unit.id) for unit in before.units]
    after_ids = [str(unit.id) for unit in after.units]
    assert after_ids == [unit_id for unit_id in before_ids if unit_id in set(after_ids)]


def test_only_current_version_is_not_killed(versioned_legacy):
    """反例：只有一个现行版本时不得误杀（窗口内 → 正常作答证据）。"""
    single = _retrieve(versioned_legacy, as_of="2026-07-15")
    assert single.kind == "matches"
    assert [unit.fields["位置"] for unit in single.units] == [D01_LOCATION]


def test_closed_interval_boundaries_keep_the_row(versioned_legacy):
    """闭区间两端点都算有效：as_of == effective_from / effective_to 均不丢行。"""
    at_end = _retrieve(versioned_legacy, as_of="2026-04-30")
    assert [unit.fields["位置"] for unit in at_end.units] == [V03_LOCATION]

    at_start = _retrieve(versioned_legacy, as_of="2026-05-01")
    assert [unit.fields["位置"] for unit in at_start.units] == [D01_LOCATION]


def test_undeclared_end_keeps_the_row(versioned_legacy):
    """失效日期哨兵“未声明”= not_asserted：该侧不参与过滤，不得被当过期删掉。"""
    late = _retrieve(versioned_legacy, as_of="2026-12-15")
    assert [unit.fields["位置"] for unit in late.units] == [V05_LOCATION]


def test_explicit_future_phrasing_skips_the_filter(versioned_legacy):
    """反例：``as_of=None``（含“调整后/未来”问法）时行为与改前逐值相同。"""
    before = _retrieve(versioned_legacy, as_of=None)
    assert before.kind == "conflict"
    assert len(before.units) == 3


def test_as_of_must_be_iso_date():
    with pytest.raises(QueryRejected):
        _as_of_bound("2026/10/15")
    assert _as_of_bound(None) is None
    assert _as_of_bound(" 2026-10-15 ") == "2026-10-15"
