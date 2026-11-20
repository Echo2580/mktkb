import sqlite3, json, hashlib, pathlib
base = pathlib.Path(r"D:\GPT项目\市场部AI知识库\.tmp-ncu-isolated\traces")
TARGET = "504e0ea7f4b1c86f"
PROD_UNIT = "072d28f2-b403-4af3-9fe9-31b9e8714dbf"

def ref(v):
    return hashlib.sha256(str(v).encode()).hexdigest()[:16]

rag = sqlite3.connect(f"file:{base/'R2-rag.sqlite3'}?mode=ro", uri=True)
rag.row_factory = sqlite3.Row
prod = sqlite3.connect(f"file:{base/'R2-product.sqlite3'}?mode=ro", uri=True)
prod.row_factory = sqlite3.Row

print("--- rag_units ids & hashes")
for r in rag.execute("select * from rag_units"):
    d = dict(r)
    mark = " <== MATCH" if ref(d["unit_id"]) == TARGET else ""
    print(f"  unit_id={d['unit_id']} hash={ref(d['unit_id'])} v={d['version_id'][:8]} key={d['unit_key']}{mark}")
print("--- rag_chunks ids")
for r in rag.execute("select chunk_id, record_unit_id, unit_ids, doc_id, version_id, revision, kind, ordinal from rag_chunks"):
    d = dict(r)
    h1 = ref(d["chunk_id"]); h2 = ref(d["record_unit_id"]) if d["record_unit_id"] else ""
    mark = " <== MATCH(chunk)" if h1 == TARGET else (" <== MATCH(record_unit)" if h2 == TARGET else "")
    print(f"  chunk={d['chunk_id'][:12]} hash={h1} rec={str(d['record_unit_id'])[:12]} rechash={h2} rev={d['revision']} kind={d['kind']}{mark}")
print("--- product source_units for D01")
for r in prod.execute("select id, document_id, version_id, unit_key, sheet, locator, text from source_units where document_id in (select id from documents where name like 'D01%')"):
    d = dict(r)
    mark = " <== HASH MATCH" if ref(d["id"]) == TARGET else (" <== expected prod unit" if d["id"] == PROD_UNIT else "")
    print(f"  unit={d['id']} v={d['version_id'][:8]} key={d['unit_key']} hash={ref(d['id'])}{mark}")
print("--- knowledge_state / rag_meta")
print(dict(prod.execute("select * from knowledge_state").fetchone()))
for r in rag.execute("select key,value from rag_meta order by key"):
    print("  rag_meta", r[0], "=", r[1][:120])
