import hashlib

from mktkb.rag import AtomicUnit, DocumentSpec
from mktkb.rag.legacy import LegacyIndex
from mktkb.retrieval.service import retrieve
from mktkb.retrieval.types import QueryIntent


def test_overlapping_distinct_values_remain_conflict(tmp_path):
    docs = []
    for name, value in (("syn-a", "甲柜"), ("syn-b", "乙柜")):
        doc = DocumentSpec(doc_id=name, logical_id=name, source_path=f"synthetic/{name}.xlsx",
                           title="设备表", file_kind="xlsx", version_id=name + "-v1",
                           version_label="1", sha256=hashlib.sha256(name.encode()).hexdigest(), business_date=None)
        fields = {"标识": "P77", "门店": "北园店", "物品": "展板", "位置": value,
                  "生效日期": "2026-01-01", "失效日期": "2026-12-31"}
        unit = AtomicUnit(unit_id=name + "-row", doc_id=name, version_id=doc.version_id,
                          kind="table_row", ordinal=0, unit_key="sheet:设备:row:2",
                          text="；".join(f"{k}: {v}" for k, v in fields.items()), fields=fields,
                          sheet="设备", locator={"sheet": "设备", "row": 2, "header_row": 1},
                          row_number=2, title=doc.title)
        docs.append((doc, [unit]))
    index = LegacyIndex(tmp_path / "synthetic.sqlite3")
    try:
        index.build(docs)
        intent = QueryIntent(mode="record", entity_filters={"store": "北园店", "item": "展板"},
                             requested_fields=("位置",))
        with index.database.session() as session:
            result = retrieve(session, intent, revision=index.revision, limit=20, as_of="2026-06-01")
        assert result.kind == "conflict"
        assert {unit.fields["位置"] for unit in result.units} == {"甲柜", "乙柜"}
    finally:
        index.close()
