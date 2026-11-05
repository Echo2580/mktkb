r"""T001 independent probe #2: digest math, documented defaults, doc/impl sync.

Verifier-owned. Recomputes every digest from first principles instead of trusting
the implementation, and cross-checks the two frozen docs against the design spec
and the code. ASCII-only output.

Run from repo root:
  $env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
  .\.venv\Scripts\python.exe -B -X utf8 <this file>
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
SRC = ROOT / "backend" / "src"
sys.path.insert(0, str(SRC))

from mktkb.observability import contracts as C  # noqa: E402
from mktkb.observability import versioning as V  # noqa: E402
import mktkb.observability as PKG  # noqa: E402

FAILS: list[str] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
        print(f"PASS {name}" + (f" :: {detail}" if detail else ""))
    except Exception as exc:  # noqa: BLE001
        FAILS.append(name)
        print(f"FAIL {name} :: {type(exc).__name__}: {exc}")


def canon(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha12(payload) -> str:
    return hashlib.sha256(canon(payload).encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------- digest math probes
def hash_math():
    q = "城东店海报在哪里"
    key = b"verifier-key-material"
    got = V.hash_question(q, key=key, algo="hmac-sha256")
    expected = hmac.new(key, q.encode("utf-8"), hashlib.sha256).hexdigest()
    assert got == expected, "hmac-sha256 digest is not plain HMAC-SHA256(key, utf8(question))"
    got2 = V.hash_question(q, key=b"", algo="sha256")
    expected2 = hashlib.sha256(q.encode("utf-8")).hexdigest()
    assert got2 == expected2, "sha256 digest is not plain SHA-256(utf8(question))"
    return "HMAC-SHA256 / SHA-256 recomputed independently, match"


def pipeline_math():
    comps = {"prompt": "P", "top_k": 8, "nested": {"b": 2, "a": 1}, "flag": True}
    assert V.pipeline_version(comps) == sha12(comps), "pipeline_version != sha256(canonical JSON)[:12]"
    return "explicit-components digest == manual sha256(canonical JSON)[:12]"


def pipeline_default_payload():
    """Rebuild the documented default component mapping from business constants."""
    from mktkb.qa.service import QA_ENGINE_VERSION
    from mktkb.rag.config import RagConfig
    from mktkb.rag.index import INDEX_CACHE_VERSION, SCHEMA_VERSION
    from mktkb.retrieval.tokenize import TOKENIZER_VERSION

    cfg = RagConfig()
    expected = {
        "qa_engine_version": QA_ENGINE_VERSION,
        "rag_schema_version": SCHEMA_VERSION,
        "index_cache_version": INDEX_CACHE_VERSION,
        "tokenizer_version": TOKENIZER_VERSION,
        "embedding_model": cfg.embedding_model,
        "embedding_dimensions": cfg.embedding_dimensions,
        "rerank_model": cfg.rerank_model,
        "chunk_max_chars": cfg.chunk_max_chars,
        "chunk_max_units": cfg.chunk_max_units,
        "chunk_overlap_units": cfg.chunk_overlap_units,
        "top_k": cfg.top_k,
        "page_size": cfg.page_size,
    }
    got = V.pipeline_version()
    assert got == sha12(expected), f"default pipeline_version={got} != sha256(documented payload)[:12]={sha12(expected)}"
    return f"default digest matches documented component mapping (12 keys), value={got}"


def config_math():
    cfg = {"top_k": 8, "embedding_model": "m", "unrelated_meta": "ignored"}
    filtered = {name: cfg[name] for name in V.CONFIG_HASH_FIELDS if name in cfg}
    assert V.config_hash(cfg) == sha12(filtered), "config_hash != sha256(whitelisted canonical JSON)[:12]"
    return "config_hash == sha256(canonical JSON of whitelisted subset)[:12]"


def keyfp_math():
    key = b"abc123"
    expected = hashlib.sha256(b"mktkb.trace.hmac_key_id.v0.1:" + key).hexdigest()[:12]
    assert V.key_fingerprint(key) == expected, "key_fingerprint domain prefix/scheme mismatch"
    return "key_fingerprint == sha256(domain || key)[:12]"


# ------------------------------------------------------- docs vs code sync
DOC = ROOT / "docs" / "evaluation" / "trace_schema_v0_1.md"
EVAL_DOC = ROOT / "docs" / "evaluation" / "eval_data_v0_1.md"
DESIGN = ROOT / "docs" / "superpowers" / "specs" / "2026-11-04-mktkb-observability-evaluation-design.md"


def _md_table_rows(text: str, after_heading: str) -> list[str]:
    """Return markdown data rows of the first table after a heading line."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith(after_heading))
    rows: list[str] = []
    seen_sep = False
    for ln in lines[start:]:
        s = ln.strip()
        if s.startswith("|") and s.endswith("|"):
            if set(s) <= set("|-: "):
                seen_sep = True
                continue
            if seen_sep:
                rows.append(s)
        elif rows and not s.startswith("|"):
            break
    return rows


def doc_fields():
    text = DOC.read_text(encoding="utf-8")
    rows = _md_table_rows(text, "| 字段 | 类型 | 必填 |")
    names = [re.findall(r"`([^`]+)`", r)[0] for r in rows]
    assert len(names) == 41, f"doc trace field table has {len(names)} rows, want 41"
    design_fields = """
    trace_id request_id http_request_id attempt replayed previous_trace_id
    trace_schema_version mode scope path case_id dataset_version run_id
    index_revision manifest_sha256 pipeline_version config_hash
    query_kind outcome_kind reason answer_source content_mode question_hash
    question_chars hash_algo hmac_key_id user_id_hash conversation_id_hash
    retrieval_counts_json filter_decisions_json fact_gate_json citation_refs_json
    pagination_json token_usage_json cost_json go_decision degraded_json latency_ms
    status error_code created_at
    """.split()
    assert names == design_fields, f"doc trace fields differ from design: {set(design_fields) ^ set(names)}"

    span_rows = _md_table_rows(text, "| 字段 | 类型 | 说明 |")
    span_names = [re.findall(r"`([^`]+)`", r)[0] for r in span_rows]
    assert span_names == """
    span_id trace_id parent_span_id name started_at duration_ms status attributes_json error_code
    """.split(), span_names
    return "trace_schema doc: 41 trace fields + 9 span fields listed in design order"


def doc_required_spans():
    text = DOC.read_text(encoding="utf-8")
    section = text.split("### 6.1")[1].split("### 6.2")[0]
    rows = [ln.strip() for ln in section.splitlines() if ln.strip().startswith("|") and "`" in ln]
    rows = [r for r in rows if not set(r) <= set("|-: ")]
    assert len(rows) == 8, f"doc 6.1 required-span table has {len(rows)} data rows, want 8"
    assert "rag` + `clarification`" in section
    assert "`parse`、`commit`" in section
    assert "legacy` + `not_found`" in section
    assert "`query_expansion`" in section and "不含" in section
    return "doc 6.1: 8-row design table present, incl. both pitfall notes"


def doc_whitelist():
    text = DOC.read_text(encoding="utf-8")
    block = text.split("`config_hash` 白名单")[1].split("```")[1]
    names = [x.strip() for x in re.split(r"[,\n]", block) if x.strip() and x.strip() != "text"]
    assert names == list(V.CONFIG_HASH_FIELDS), f"doc whitelist != CONFIG_HASH_FIELDS: {names}"
    assert "sha256(canonical_json).hexdigest()[:12]" in text, "digest format statement missing"
    for token in ('ensure_ascii=False', 'sort_keys=True', 'separators=(",", ":")'):
        assert token in text, f"canonical JSON token missing in doc: {token}"
    return "doc 7.2: whitelist (16) == CONFIG_HASH_FIELDS; 12-hex + canonical JSON defined"


def doc_eval():
    text = EVAL_DOC.read_text(encoding="utf-8")
    assert "dataset_version = suite:label_version:sha256(canonical JSONL)[:12]" in text
    assert C.CASE_SCHEMA_VERSION == "mktkb.eval.case.v0.1"
    assert "mktkb.eval.case.v0.1" in text
    return "eval_data doc: dataset_version formula + CASE_SCHEMA_VERSION bound"


def design_source_of_truth():
    """The 8 rows and the two pitfalls must exist in the design spec itself."""
    text = DESIGN.read_text(encoding="utf-8")
    for token in (
        "| `rag` + `answer` / `conflict` |",
        "| `rag` + `clarification` |",
        "| `rag` + `no_answer` / `ambiguous` |",
        "| `rag` + `error` / `knowledge_changed` |",
        "| `legacy` / `legacy_with_rag_candidates` + `answer` |",
        "| `legacy` + `not_found` |",
        "| `legacy` + `clarification` |",
        "| `legacy` + `service_error` |",
    ):
        assert token in text, f"design row missing: {token}"
    assert "`vector_enabled=true` → `vector_recall`" in text
    assert "`rerank_enabled=true` → `rerank`" in text
    assert "`expansion_triggered=true` → `query_expansion`" in text
    assert "`index_sync_performed=true` → `index_sync`" in text
    return "design spec confirms 8 rows + 4 conditional flags"


def package_reexports():
    exported = set(PKG.__all__)
    expected = {
        "CASE_SCHEMA_VERSION",
        "CONFIG_HASH_FIELDS",
        "GATE_SCHEMA_VERSION",
        "TRACE_SCHEMA_VERSION",
        "OutcomeKind",
        "SpanRecord",
        "TraceMode",
        "TracePath",
        "TraceRecord",
        "conditional_required_spans",
        "config_hash",
        "hash_question",
        "key_fingerprint",
        "pipeline_version",
        "required_spans",
    }
    assert exported == expected, f"__all__ mismatch: {exported ^ expected}"
    for name in expected:
        assert getattr(PKG, name) is not None
    return "package __init__ re-exports all 15 contract/versioning names"


def main() -> int:
    check("digest: hash_question math", hash_math)
    check("digest: pipeline_version explicit math", pipeline_math)
    check("digest: pipeline_version documented defaults", pipeline_default_payload)
    check("digest: config_hash math", config_math)
    check("digest: key_fingerprint math", keyfp_math)
    check("docs: trace/span field tables", doc_fields)
    check("docs: required-span table (8 rows)", doc_required_spans)
    check("docs: config_hash whitelist + format", doc_whitelist)
    check("docs: eval_data version protocol", doc_eval)
    check("design: source of truth", design_source_of_truth)
    check("package: re-exports", package_reexports)
    print("")
    if FAILS:
        print(f"RESULT: {len(FAILS)} FAIL -> {FAILS}")
        return 1
    print("RESULT: ALL INDEPENDENT PROBES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
