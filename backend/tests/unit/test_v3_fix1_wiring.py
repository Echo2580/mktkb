"""v3-fix-1 产品层接线：legacy 业务日期取值 + 多目标轮次路由。

纯单元：不建库、不检索、不调模型、不开端口。
"""

from __future__ import annotations

from types import SimpleNamespace

from mktkb.conversations import service
from mktkb.rag.query import Lexicon, parse_query
from mktkb.rag.types import QueryState
from mktkb.retrieval.types import EvidenceSet, QueryIntent


class _Session:
    def close(self) -> None:
        return None


def test_legacy_as_of_comes_from_the_product_plan():
    plan = SimpleNamespace(as_of="2026-10-15", include_future=False)
    assert service._legacy_evidence_as_of(SimpleNamespace(), plan) == "2026-10-15"


def test_legacy_as_of_absent_without_rag_or_for_future_phrasing():
    assert service._legacy_evidence_as_of(None, None) is None
    assert service._legacy_evidence_as_of(SimpleNamespace(), None) is None
    plan = SimpleNamespace(as_of="2026-10-15", include_future=True)
    assert service._legacy_evidence_as_of(SimpleNamespace(), plan) is None
    assert service._legacy_evidence_as_of(
        SimpleNamespace(), SimpleNamespace(as_of=None, include_future=False)
    ) is None


def test_retrieve_entry_forwards_as_of(monkeypatch):
    seen: dict[str, object] = {}

    def fake_retrieve(db, intent, *, revision, limit=20, candidate_ids=None, as_of=None):
        seen.update({"revision": revision, "limit": limit, "as_of": as_of})
        return EvidenceSet([], "none", 0, revision, [])

    monkeypatch.setattr(service, "retrieve", fake_retrieve)
    result = service._retrieve(
        lambda: _Session(),
        QueryIntent(mode="document", terms=("物料",)),
        0,
        as_of="2026-10-15",
    )
    assert seen == {"revision": 0, "limit": 20, "as_of": "2026-10-15"}
    assert result.kind == "none"


def test_multi_target_turn_is_routed_to_kernel_even_without_entity_filter():
    lexicon = Lexicon(stores=("城东店", "城西店"), items=("宣传海报",), field_labels=("电话",))
    plan = parse_query(
        "城东店和城西店的电话是多少？",
        previous=QueryState(),
        lexicon=lexicon,
        business_date="2026-10-15",
    )
    assert plan.filters == {}
    assert plan.reason == "MULTI_TARGET_ENUMERATE"
    assert service._rag_owns_turn(QueryState(), plan) is True


def test_plain_multi_entity_ambiguity_still_clarifies():
    lexicon = Lexicon(stores=("城东店", "城西店"), items=("宣传海报", "易拉宝"), field_labels=("位置",))
    plan = parse_query(
        "城东店和城西店的宣传海报和易拉宝在哪里？",
        previous=QueryState(),
        lexicon=lexicon,
        business_date="2026-10-15",
    )
    assert plan.clarification
    assert service._rag_owns_turn(QueryState(), plan) is False
