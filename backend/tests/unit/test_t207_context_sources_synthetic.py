from types import SimpleNamespace
from unittest.mock import MagicMock

from mktkb.conversations import service


def _context(rows, monkeypatch):
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = []
    refs = [SimpleNamespace(source_id=f"source-{n}") for n in range(len(rows))]
    db.scalars.return_value.all.return_value = refs
    db.scalar.side_effect = [SimpleNamespace(id="assistant")] + [SimpleNamespace(entity_filters=row) for row in rows]
    events = []
    monkeypatch.setattr(service, "capture_enabled", lambda: True)
    monkeypatch.setattr(service, "emit_capture_event", lambda kind, **kw: events.append((kind, kw)))
    _, entities = service._load_context(db, SimpleNamespace(id="conversation"), 5, capture_request_id="r")
    inherited = [event for event in events if event[0] == "entity_inheritance"]
    return entities, inherited


def test_conflicting_sources_do_not_choose_an_arbitrary_store(monkeypatch):
    entities, events = _context([
        {"store": "北园店", "item": "展板"},
        {"store": "南园店", "item": "展板"},
    ], monkeypatch)
    assert entities == {"item": "展板"}
    assert {event[1]["entity_type"] for event in events} == {"item"}


def test_unambiguous_sources_keep_both_dimensions(monkeypatch):
    entities, _ = _context([
        {"store": "北园店", "item": "展板"},
        {"store": "北园店", "item": "展板"},
    ], monkeypatch)
    assert entities == {"store": "北园店", "item": "展板"}


def test_unrelated_partial_sources_cannot_create_a_pair(monkeypatch):
    entities, _ = _context([{"store": "北园店"}, {"item": "展板"}], monkeypatch)
    assert not ({"store", "item"} <= entities.keys())


def test_inherited_pair_cites_the_source_supporting_both(monkeypatch):
    entities, events = _context([{"store": "北园店"}, {"store": "北园店", "item": "展板"}], monkeypatch)
    assert entities == {"store": "北园店", "item": "展板"}
    assert {event[1]["source_unit_id"] for event in events} == {"source-1"}
