r"""T001 independent acceptance probe (verifier-owned, NOT written by dev).

Re-derives expectations from the design spec
(docs/superpowers/specs/2026-11-04-mktkb-observability-evaluation-design.md
section 6.3 / 6.4) and from handoff section 5, independently of the package's
own test fixtures/constants. ASCII-only output.

Run from repo root:
  $env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
  .\.venv\Scripts\python.exe -B -X utf8 <this file>
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]  # docs/reports/OBS-EVAL/P0/evidence/verify/T001 -> repo root
SRC = ROOT / "backend" / "src"
sys.path.insert(0, str(SRC))

from mktkb.observability import contracts as C  # noqa: E402
from mktkb.observability import versioning as V  # noqa: E402

FAILS: list[str] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
        print(f"PASS {name}" + (f" :: {detail}" if detail else ""))
    except Exception as exc:  # noqa: BLE001 - probe must record any mismatch
        FAILS.append(name)
        print(f"FAIL {name} :: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- section 5.1
def s51():
    assert C.TRACE_SCHEMA_VERSION == "mktkb.trace.v0.1", C.TRACE_SCHEMA_VERSION
    assert C.CASE_SCHEMA_VERSION == "mktkb.eval.case.v0.1", C.CASE_SCHEMA_VERSION
    assert C.GATE_SCHEMA_VERSION == "mktkb.gate.v0.1", C.GATE_SCHEMA_VERSION
    return "3 constants exact"


# ------------------------------------------- section 5.2: design 6.4, 8 rows
# Transcribed row by row from the design doc (not from the package tests).
DESIGN_ROWS = [
    # row 1
    (("rag", "answer"), {"parse", "recall", "fuse", "answer", "commit"}),
    (("rag", "conflict"), {"parse", "recall", "fuse", "answer", "commit"}),
    # row 2
    (("rag", "clarification"), {"parse", "commit"}),
    # row 3
    (("rag", "no_answer"), {"parse", "recall", "fuse", "commit"}),
    (("rag", "ambiguous"), {"parse", "recall", "fuse", "commit"}),
    # row 4
    (("rag", "error"), {"parse", "commit"}),
    (("rag", "knowledge_changed"), {"parse", "commit"}),
    # row 5
    (("legacy", "answer"), {"intent_parse", "retrieve", "model_answer", "answer_validate", "commit"}),
    (("legacy_with_rag_candidates", "answer"), {"intent_parse", "retrieve", "model_answer", "answer_validate", "commit"}),
    # row 6
    (("legacy", "not_found"), {"intent_parse", "retrieve", "commit"}),
    # row 7
    (("legacy", "clarification"), {"intent_parse", "commit"}),
    # row 8
    (("legacy", "service_error"), {"intent_parse", "commit"}),
]


def s52():
    for (path, outcome), expected in DESIGN_ROWS:
        got = C.required_spans(path, outcome)
        assert isinstance(got, frozenset), (path, outcome, type(got))
        assert got == frozenset(expected), f"{path}+{outcome}: got={sorted(got)} expected={sorted(expected)}"
    # explicit easy-to-miss points required by handoff 5.2
    clar = C.required_spans("rag", "clarification")
    assert "answer" not in clar, clar
    assert "recall" not in clar, clar
    nf = C.required_spans("legacy", "not_found")
    assert "query_expansion" not in nf, nf
    assert "answer" not in nf, nf
    assert "model_answer" not in nf, nf
    return f"{len(DESIGN_ROWS)} path+outcome combos from 8 design rows match; pitfalls ok"


# ------------------------------------------------------------ section 5.3
def s53():
    cases = {
        "vector_enabled": "vector_recall",
        "rerank_enabled": "rerank",
        "expansion_triggered": "query_expansion",
        "index_sync_performed": "index_sync",
    }
    for flag, span in cases.items():
        got = C.conditional_required_spans({flag: True})
        assert got == frozenset({span}), (flag, got)
        assert C.conditional_required_spans({flag: False}) == frozenset()
    assert C.conditional_required_spans({}) == frozenset()
    assert C.conditional_required_spans(None) == frozenset()
    # only the four known keys; unknown truthy keys must not require anything
    assert C.conditional_required_spans(
        {"vector": True, "rerank": True, "index_sync": True, "foo": True}
    ) == frozenset()
    union = C.conditional_required_spans(
        {"vector_enabled": True, "rerank_enabled": True, "expansion_triggered": True, "index_sync_performed": True}
    )
    assert union == frozenset({"vector_recall", "rerank", "query_expansion", "index_sync"}), union
    return "four keys only; {} / None / unknown ignored; union ok"


# ------------------------------------------------------------ section 5.4
HEX12 = re.compile(r"[0-9a-f]{12}")


def s54_deterministic():
    base = {"prompt": "A", "top_k": 8, "embedding_model": "m", "embedding_dimensions": 1024}
    assert V.pipeline_version(base) == V.pipeline_version(dict(base))
    assert HEX12.fullmatch(V.pipeline_version(base))
    assert V.pipeline_version(base) != V.pipeline_version({**base, "prompt": "B"})
    assert V.pipeline_version(base) != V.pipeline_version({**base, "top_k": 12})
    # key order must not matter, nested objects must be canonicalised too
    left = {"b": 2, "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "b": 2}
    assert V.pipeline_version(left) == V.pipeline_version(right)
    return "deterministic; prompt/top_k change digest; key order ignored"


def s54_lazy_imports():
    """Monkeypatch the business constants AFTER import; digest must change only if
    the default components are resolved at call time (lazy import)."""
    probes = [
        ("mktkb.qa.service", "QA_ENGINE_VERSION"),
        ("mktkb.rag.index", "SCHEMA_VERSION"),
        ("mktkb.rag.index", "INDEX_CACHE_VERSION"),
        ("mktkb.retrieval.tokenize", "TOKENIZER_VERSION"),
    ]
    changed = 0
    for mod_name, attr in probes:
        mod = importlib.import_module(mod_name)
        original = getattr(mod, attr)
        baseline = V.pipeline_version()
        setattr(mod, attr, "probe-lazy-value")
        try:
            assert V.pipeline_version() != baseline, f"{mod_name}.{attr} is bound at import time"
        finally:
            setattr(mod, attr, original)
        changed += 1
    assert V.pipeline_version() == V.pipeline_version()
    return f"{changed}/4 default components resolved at call time"


def s54_module_level_imports():
    """Top-level imports of both modules must be stdlib only."""
    for filename in ("contracts.py", "versioning.py"):
        tree = __import__("ast").parse((SRC / "mktkb" / "observability" / filename).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, __import__("ast").Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in sys.stdlib_module_names, f"{filename}: {alias.name}"
            elif isinstance(node, __import__("ast").ImportFrom):
                assert node.level == 0, f"{filename}: relative top-level import"
                assert node.module.split(".")[0] in sys.stdlib_module_names, f"{filename}: {node.module}"
    return "AST: both modules' top-level imports are stdlib only"


def s54_fresh_process():
    code = (
        "import sys\n"
        "from mktkb.observability import TRACE_SCHEMA_VERSION, pipeline_version\n"
        "print(TRACE_SCHEMA_VERSION)\n"
        "print(pipeline_version())\n"
        "print('mktkb.main_loaded=' + str('mktkb.main' in sys.modules))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(ROOT),
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    lines = [ln.strip() for ln in completed.stdout.strip().splitlines() if ln.strip()]
    assert lines[-3] == "mktkb.trace.v0.1", lines
    assert HEX12.fullmatch(lines[-2]), lines
    # Documented caveat: parent package mktkb/__init__.py pre-imports main.
    assert lines[-1] == "mktkb.main_loaded=True", lines
    return "fresh process imports cleanly (no circular import); parent mktkb/__init__ still loads main (pre-existing, disclosed)"


# ------------------------------------------------------------ section 5.5
def s55():
    try:
        V.hash_question("q", key=b"", algo="hmac-sha256")
    except ValueError:
        pass
    else:
        raise AssertionError("hmac-sha256 with empty key did NOT raise ValueError")
    digest = V.hash_question("城东店问题", key=b"k" * 32, algo="hmac-sha256")
    assert re.fullmatch(r"[0-9a-f]{64}", digest), digest
    assert "城东店问题" not in digest
    sha = V.hash_question("合成问题", key=b"", algo="sha256")
    assert re.fullmatch(r"[0-9a-f]{64}", sha)
    assert "合成问题" not in sha
    try:
        V.hash_question("q", key=b"k", algo="md5")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown algo did NOT raise ValueError")
    return "ValueError raised for empty key + unknown algo; 64-hex; no plaintext; sha256 empty key ok"


# ------------------------------------------------------------ section 5.6
DOC_WHITELIST = """provider_mode embedding_model embedding_dimensions rerank_model rerank_top_n
rerank_max_documents chat_model chunk_max_chars chunk_max_units chunk_overlap_units
top_k candidate_limit vector_candidate_limit page_size max_page_size hard_filters""".split()


def s56():
    assert list(V.CONFIG_HASH_FIELDS) == list(DOC_WHITELIST), (
        f"whitelist mismatch: impl={list(V.CONFIG_HASH_FIELDS)} doc={DOC_WHITELIST}"
    )
    for name in ("api_key", "API_KEY", "client_secret", "access_token", "db_password", "Password"):
        try:
            V.config_hash({"top_k": 8, name: "v"})
        except ValueError:
            pass
        else:
            raise AssertionError(f"secret-like key {name!r} did NOT raise ValueError")
    base = {"top_k": 8, "embedding_model": "text-embedding-v4"}
    for name in V.CONFIG_HASH_FIELDS:
        assert V.config_hash({name: "value-a"}) != V.config_hash({name: "value-b"}), name
    assert V.config_hash({**base, "unrelated": "x"}) == V.config_hash(base)
    assert HEX12.fullmatch(V.config_hash(base))
    return "16-field whitelist == doc; secret-like names raise ValueError; whitelist changes digest"


# ------------------------------------------------------------ section 5.7
# Transcribed field lists from design 6.3 (not from package tests).
DESIGN_TRACE_FIELDS = """
trace_id request_id http_request_id attempt replayed previous_trace_id
trace_schema_version mode scope path case_id dataset_version run_id
index_revision manifest_sha256 pipeline_version config_hash
query_kind outcome_kind reason answer_source
content_mode question_hash question_chars hash_algo hmac_key_id
user_id_hash conversation_id_hash
retrieval_counts_json filter_decisions_json fact_gate_json citation_refs_json pagination_json
token_usage_json cost_json go_decision degraded_json latency_ms status error_code created_at
""".split()
DESIGN_SPAN_FIELDS = """
span_id trace_id parent_span_id name started_at duration_ms status attributes_json error_code
""".split()


def s57():
    assert len(DESIGN_TRACE_FIELDS) == 41, len(DESIGN_TRACE_FIELDS)
    assert len(DESIGN_SPAN_FIELDS) == 9, len(DESIGN_SPAN_FIELDS)
    trace_fields = [f.name for f in dataclasses.fields(C.TraceRecord)]
    span_fields = [f.name for f in dataclasses.fields(C.SpanRecord)]
    assert len(trace_fields) == 41, len(trace_fields)
    assert len(span_fields) == 9, len(span_fields)
    assert set(trace_fields) == set(DESIGN_TRACE_FIELDS), (
        f"missing={set(DESIGN_TRACE_FIELDS) - set(trace_fields)} extra={set(trace_fields) - set(DESIGN_TRACE_FIELDS)}"
    )
    assert set(span_fields) == set(DESIGN_SPAN_FIELDS), (
        f"missing={set(DESIGN_SPAN_FIELDS) - set(span_fields)} extra={set(span_fields) - set(DESIGN_SPAN_FIELDS)}"
    )
    assert C.TraceRecord.__dataclass_params__.frozen is True
    assert C.SpanRecord.__dataclass_params__.frozen is True
    rec = C.TraceRecord(trace_id="t1", request_id="r1", mode="local", path="rag")
    payload = dataclasses.asdict(rec)
    json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert payload["trace_schema_version"] == C.TRACE_SCHEMA_VERSION
    assert payload["content_mode"] == "hash"
    assert payload["attempt"] == 1
    span = C.SpanRecord(span_id="s1", trace_id="t1", name="parse")
    json.dumps(dataclasses.asdict(span), ensure_ascii=False, sort_keys=True)
    try:
        rec.status = "x"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("TraceRecord is not frozen")
    return "traces=41 / spans=9 exact; frozen; instantiate+asdict+json.dumps ok"


# ---------------------------------------------------------------- enums
def enums():
    assert {x.value for x in C.TraceMode} == {"replay", "local", "live"}
    assert {x.value for x in C.TracePath} == {"rag", "legacy", "legacy_with_rag_candidates"}
    assert {x.value for x in C.OutcomeKind} == {
        "answer",
        "clarification",
        "no_answer",
        "ambiguous",
        "conflict",
        "error",
        "not_found",
        "service_error",
        "knowledge_changed",
    }
    return "TraceMode/TracePath/OutcomeKind values match design 6.3"


def main() -> int:
    print(f"python={sys.version.split()[0]} root={ROOT}")
    check("5.1 schema version constants", s51)
    check("5.2 required_spans: all 8 design rows (12 combos)", s52)
    check("5.3 conditional_required_spans", s53)
    check("5.4a pipeline_version determinism/sensitivity", s54_deterministic)
    check("5.4b default components lazy (call-time)", s54_lazy_imports)
    check("5.4c top-level imports stdlib-only", s54_module_level_imports)
    check("5.4d fresh-process import / no circular import", s54_fresh_process)
    check("5.5 hash_question", s55)
    check("5.6 config_hash", s56)
    check("5.7 TraceRecord/SpanRecord", s57)
    check("5.x enums", enums)
    print("")
    if FAILS:
        print(f"RESULT: {len(FAILS)} FAIL -> {FAILS}")
        return 1
    print("RESULT: ALL INDEPENDENT PROBES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
