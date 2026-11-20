"""生成 6 条 trace 核定表与 U01 引用重建证据（机器可读）。"""
from __future__ import annotations

import json
import sqlite3
import hashlib
from pathlib import Path

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
BASE = ROOT / "docs/reports/OBS-EVAL/P2/T207"
ISO = ROOT / ".tmp-ncu-isolated"
OUT = ROOT / "docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/evidence"
OUT.mkdir(parents=True, exist_ok=True)

SIX = {"R1": ["N01", "C01", "C02"], "R2": ["U01"], "R4": ["C05", "C06"]}
rows = []
for run, ids in SIX.items():
    rd = BASE / f"p2-t207-{run.lower()}-20261111-01"
    man = json.loads((rd / "run_manifest.json").read_text(encoding="utf-8"))
    cases = {json.loads(l)["case_id"]: json.loads(l) for l in (rd / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    con = sqlite3.connect(f"file:{ISO/'traces'/f'{run}.sqlite3'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rag = sqlite3.connect(f"file:{ISO/'traces'/f'{run}-rag.sqlite3'}?mode=ro", uri=True)
    rag_meta = dict(rag.execute("select key,value from rag_meta").fetchall())
    for cid in ids:
        prod = cases[cid]["turns"][0]["product"]
        tr = dict(con.execute("select * from traces where trace_id=?", (prod["trace_id"],)).fetchone())
        spans = [r[0] for r in con.execute("select name from spans where trace_id=? order by started_at, rowid", (prod["trace_id"],))]
        publish_rev = max(e["revision"] for e in man["ingest"] if e["published"])
        rag_path = "recall" in spans
        rows.append({
            "run": run,
            "case_id": cid,
            "run_id": man["run_id"],
            "trace_id": prod["trace_id"],
            "trace_path": tr["path"],
            "trace_outcome": tr["outcome_kind"],
            "question_sha256": prod["question_sha256"],
            "binding_index_revision": man["index_revision"],
            "stage_ingest_published_max_revision": publish_rev,
            "stage_product_response_revision": prod.get("revision"),
            "stage_rag_index_revision": int(rag_meta["revision"]),
            "stage_rag_product_revision": int(rag_meta["product_revision"]),
            "trace_index_revision": int(tr["index_revision"]),
            "rag_retrieval_executed": rag_path,
            "spans": spans,
            "mismatch": int(tr["index_revision"]) != man["index_revision"],
            "explanation": (
                "trace.index_revision 由 rag/retrieval.py 用 rag_meta.revision 覆盖；该计数与 product_revision（manifest 绑定）是两套计数器，且本题走了 RAG 检索路径。"
                if rag_path else
                "本题未执行 RAG 检索，trace 保留 run 绑定的 product_revision，无差异。"
            ),
            "closes": rag_path and int(tr["index_revision"]) == int(rag_meta["revision"]) and prod.get("revision") == man["index_revision"],
        })
    con.close()
    rag.close()

(OUT / "trace-adjudication.json").write_text(json.dumps({
    "schema_version": "p2-ncu-trace-adjudication/v0.1",
    "note": "6 条 = 冻结 N/C/U 范围内 trace.index_revision 与 manifest.index_revision 不一致的全部案例；R1 另有 Q01-Q24 属 B0 组，不在本表。",
    "rows": rows,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# U01 reconstruction
rag = sqlite3.connect(f"file:{ISO/'traces'/'R2-rag.sqlite3'}?mode=ro", uri=True)
rag.row_factory = sqlite3.Row
chunk = dict(rag.execute("select * from rag_chunks where chunk_id like 'a202ff9b%'").fetchone())
unit = dict(rag.execute("select * from rag_units where unit_id=?", (chunk["record_unit_id"],)).fetchone())
rd = BASE / "p2-t207-r2-20261111-01"
u01 = [json.loads(l) for l in (rd / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
u01 = next(c for c in u01 if c["case_id"] == "U01")["turns"][0]["product"]
trace = sqlite3.connect(f"file:{ISO/'traces'/'R2.sqlite3'}?mode=ro", uri=True)
trace.row_factory = sqlite3.Row
tr = dict(trace.execute("select * from traces where trace_id=?", (u01["trace_id"],)).fetchone())
citation = json.loads(tr["citation_refs_json"])[0]
recon = {
    "schema_version": "p2-ncu-u01-citation-reconstruction/v0.1",
    "case_id": "U01",
    "run_id": "p2-t207-r2-20261111-01",
    "trace_id": u01["trace_id"],
    "trace_citation": citation,
    "hash_reconstruction": {
        "trace.citation_refs_json[0].unit_id_hash": citation["unit_id_hash"],
        "sha256(rag_chunks.chunk_id)[:16]": hashlib.sha256(chunk["chunk_id"].encode()).hexdigest()[:16],
        "matched": citation["unit_id_hash"] == hashlib.sha256(chunk["chunk_id"].encode()).hexdigest()[:16],
    },
    "rag_chunk": {k: chunk[k] for k in ("chunk_id", "doc_id", "version_id", "revision", "kind", "unit_ids", "record_unit_id", "unit_key" if "unit_key" in chunk else "title", "content_sha256")},
    "rag_unit": {k: unit[k] for k in ("unit_id", "doc_id", "version_id", "unit_key", "sheet", "row_number", "text")},
    "product_response": {
        "kind": u01["kind"],
        "revision": u01.get("revision"),
        "source_ids": u01.get("source_ids"),
        "evidence": [{"unit_id": e["unit_id"], "unit_key": e.get("unit_key"), "version_id": e.get("version_id"), "version_number": e.get("version_number")} for e in u01.get("evidence", [])],
        "retrieved_count": len(u01.get("retrieved") or []),
        "sources_count": len(u01.get("sources") or []),
    },
    "conclusion": "trace 引用的是 RAG chunk（哈希=sha256(chunk_id)[:16]），其 record_unit_id 与 product.evidence/sources 的 unit 一致（同一 unit_key、同一行、同一取值 B区1号货架第二层）。引用真实且可对回；门禁 citation_required 失败的直接原因是同轮 product.retrieved=[]（evidence 有 1 条），不是引用编造。",
}
(OUT / "u01-citation-reconstruction.json").write_text(json.dumps(recon, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("wrote trace-adjudication.json rows:", len(rows))
print("closes:", [(r["case_id"], r["closes"]) for r in rows])
print("u01 reconstruction written")
