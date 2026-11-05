#!/usr/bin/env python
"""T005 independent verification probe.

Read-only with respect to the repository: every run artifact is written to a
fresh temporary directory. The probe drives the public ``run_suite`` API,
arms provider/socket/Settings guards, and cross-checks the persisted artifacts
against the frozen datasets and a separately built index.
"""

from __future__ import annotations

import builtins
import dataclasses
import hashlib
import json
import socket
import sys
import tempfile
from collections import Counter
from pathlib import Path


def _find_root(start: Path) -> Path:
    for parent in (start, *start.parents):
        if (parent / "backend" / "src" / "mktkb").is_dir() and (
            parent / "fixtures" / "evaluation"
        ).is_dir():
            return parent
    raise SystemExit("repo root not found")


ROOT = _find_root(Path(__file__).resolve())
sys.path.insert(0, str(ROOT / "backend" / "src"))

B0_DATASET = ROOT / "fixtures" / "evaluation" / "b0.jsonl"
BADCASE_DATASET = ROOT / "fixtures" / "evaluation" / "badcase.jsonl"
ACCEPTANCE = ROOT / "fixtures" / "acceptance"
BAD_CORPUS = ROOT / "corpus" / "enterprise-20261101"
TMP = Path(tempfile.mkdtemp(prefix="t005-verify-"))

FAILURES: list[str] = []
COUNTS = {key: 0 for key in ("provider", "socket", "settings", "env_open", "build_index")}


def safe(value: object) -> str:
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def check(name: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} :: {safe(detail)}")
        FAILURES.append(name)


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def guard(kind: str):
    def _guard(*args, **kwargs):
        COUNTS[kind] += 1
        raise AssertionError(f"forbidden {kind} call")

    return _guard


# ---------------------------------------------------------------------------
# Guards must be armed before the runner is exercised.
# ---------------------------------------------------------------------------
import mktkb.config as app_config  # noqa: E402
import mktkb.rag.providers as providers  # noqa: E402

providers.BailianEmbeddingProvider.embed = guard("provider")
providers.BailianRerankProvider.rerank = guard("provider")
providers.DeepSeekChatProvider.complete = guard("provider")
app_config.Settings.__init__ = guard("settings")
socket.socket.connect = guard("socket")
socket.create_connection = guard("socket")

_REAL_OPEN = builtins.open


def _guarded_open(file, *args, **kwargs):
    try:
        if Path(file).name == ".env":
            COUNTS["env_open"] += 1
    except (TypeError, ValueError):
        pass
    return _REAL_OPEN(file, *args, **kwargs)


builtins.open = _guarded_open

from sqlalchemy import select  # noqa: E402

from mktkb.evaluation import corpus as corpus_mod  # noqa: E402
from mktkb.evaluation import runner as runner_mod  # noqa: E402
from mktkb.evaluation.dataset import load_cases, write_cases  # noqa: E402
from mktkb.evaluation.gold import resolve_case  # noqa: E402
from mktkb.evaluation.scorers import (  # noqa: E402
    EvalCitation,
    EvalOutcome,
    EvalRetrieved,
    check_value,
    score_case,
)
from mktkb.observability.contracts import validate_required_spans  # noqa: E402
from mktkb.observability.store import TraceRepository  # noqa: E402
from mktkb.rag.models import RagUnit  # noqa: E402

print("probe_root", safe(ROOT))
print("temp_root", safe(TMP))

# ---------------------------------------------------------------------------
# Real runs: both suites, local; replay only after the build guard is armed.
# ---------------------------------------------------------------------------
b0_local = runner_mod.run_suite(
    "b0", "local", corpus_dir=ACCEPTANCE, out_dir=TMP / "b0-local-1", scope="end_to_end"
)
b0_local2 = runner_mod.run_suite(
    "b0", "local", corpus_dir=ACCEPTANCE, out_dir=TMP / "b0-local-2", scope="end_to_end"
)
badcase_local = runner_mod.run_suite(
    "badcase", "local", corpus_dir=BAD_CORPUS, out_dir=TMP / "badcase-local", scope="end_to_end"
)

# record_code-only gold: local first (needs index), replay after the guard.
b0_cases = load_cases(B0_DATASET)
record_case = dataclasses.replace(
    b0_cases[0],
    expected_sources=({"doc_code": "D01", "record_code": "P01"},),
    relevant_units=(),
)
record_dataset = TMP / "b0-record-code-only.jsonl"
write_cases(record_dataset, [record_case, *b0_cases[1:]])
record_local = runner_mod.run_suite(
    "b0",
    "local",
    corpus_dir=ACCEPTANCE,
    out_dir=TMP / "record-local",
    dataset_path=record_dataset,
)

# Extra edge probe (not used by fixtures): record_code + an empty locator is
# not rejected; resolve_case treats the empty locator as a whole-document range.
empty_locator_case = dataclasses.replace(
    b0_cases[0],
    expected_sources=({"doc_code": "D01", "record_code": "P01", "locator": {}},),
    relevant_units=(),
)
empty_locator_dataset = TMP / "b0-empty-locator.jsonl"
write_cases(empty_locator_dataset, [empty_locator_case, *b0_cases[1:]])
empty_locator_local = runner_mod.run_suite(
    "b0",
    "local",
    corpus_dir=ACCEPTANCE,
    out_dir=TMP / "empty-locator-local",
    dataset_path=empty_locator_dataset,
)
empty_row = load_rows(empty_locator_local.out_dir / "cases.jsonl")[0]
print(
    "NOTE record_code_empty_locator"
    f" status={safe(empty_row.get('status'))}"
    f" gold_units={len(((empty_row.get('gold') or {}).get('unit_ids') or ()))}"
    " (defense is key-presence based)"
)


def _no_build(*args, **kwargs):
    COUNTS["build_index"] += 1
    raise AssertionError("replay attempted to build an index")


runner_mod.build_suite_index = _no_build

b0_replay = runner_mod.run_suite(
    "b0",
    "replay",
    corpus_dir=ACCEPTANCE,
    out_dir=TMP / "b0-replay",
    scope="end_to_end",
    replay_from=b0_local.out_dir,
)
badcase_replay = runner_mod.run_suite(
    "badcase",
    "replay",
    corpus_dir=BAD_CORPUS,
    out_dir=TMP / "badcase-replay",
    scope="end_to_end",
    replay_from=badcase_local.out_dir,
)
record_replay = runner_mod.run_suite(
    "b0",
    "replay",
    corpus_dir=ACCEPTANCE,
    out_dir=TMP / "record-replay",
    dataset_path=record_dataset,
    replay_from=record_local.out_dir,
)

try:
    runner_mod.run_suite(
        "b0", "replay", corpus_dir=ACCEPTANCE, out_dir=TMP / "replay-missing-root"
    )
except ValueError as exc:
    check("replay_requires_replay_from", "replay_from" in str(exc), exc)
else:
    check("replay_requires_replay_from", False, "no ValueError")

# ---------------------------------------------------------------------------
# b0 local artifacts
# ---------------------------------------------------------------------------
b0_rows = load_rows(b0_local.out_dir / "cases.jsonl")
b0_manifest = load_json(b0_local.out_dir / "run_manifest.json")
b0_summary = load_json(b0_local.out_dir / "summary.json")
b0_metrics = b0_summary["metrics"]

check("b0_files", {p.name for p in b0_local.out_dir.iterdir()} == {
    "run_manifest.json",
    "cases.jsonl",
    "summary.json",
    "traces.sqlite3",
})
check("b0_rows_40", len(b0_rows) == 40, len(b0_rows))
status_counts = Counter(str(row.get("status")) for row in b0_rows)
check(
    "b0_status_counts",
    dict(status_counts) == {"pass": 29, "fail": 3, "skipped_requires_ocr": 8},
    dict(status_counts),
)
fail_ids = sorted(row["case_id"] for row in b0_rows if row["status"] == "fail")
check("b0_fail_ids_are_q25_q26_q31", fail_ids == ["Q25", "Q26", "Q31"], fail_ids)
row_shape_bad = [
    row.get("case_id")
    for row in b0_rows
    if not {"case_id", "status", "trace_id", "checks"} <= set(row)
    or not row.get("trace_id")
    or not isinstance(row.get("checks"), list)
    or row.get("turns_executed") != 1
    or row.get("multi_turn_claimed") is not False
    or row.get("error") is not None
]
check("b0_row_shape", not row_shape_bad, row_shape_bad[:5])
ocr_rows = [row for row in b0_rows if row["status"] == "skipped_requires_ocr"]
check(
    "b0_ocr_rows",
    len(ocr_rows) == 8
    and all(row.get("outcome") is None and row.get("metrics") == {} for row in ocr_rows),
    len(ocr_rows),
)

required_manifest = (
    "run_id",
    "mode",
    "scope",
    "dataset_version",
    "dataset_sha256",
    "corpus_manifest_sha256",
    "business_date",
    "index_revision",
    "pipeline_version",
    "gate_version",
)
check("b0_manifest_fields", all(name in b0_manifest for name in required_manifest))
check("b0_manifest_mode", b0_manifest.get("mode") == "local")
check("b0_manifest_suite", b0_manifest.get("suite") == "b0")
check("b0_manifest_scope", b0_manifest.get("scope") == "end_to_end")
check("b0_manifest_case_count", b0_manifest.get("case_count") == 40)
check("b0_dataset_sha", b0_manifest.get("dataset_sha256") == sha256(B0_DATASET))
check(
    "b0_corpus_sha",
    b0_manifest.get("corpus_manifest_sha256") == sha256(ACCEPTANCE / "manifest.json"),
)
check("b0_business_date", b0_manifest.get("business_date") == "2026-10-28")
check("b0_index_revision", b0_manifest.get("index_revision") == 6, b0_manifest.get("index_revision"))
check("b0_gate_version", b0_manifest.get("gate_version") == "mktkb.gate.v0.1")
check("b0_pipeline_version_len", len(str(b0_manifest.get("pipeline_version"))) == 12)
check("b0_trace_store", b0_manifest.get("trace_store") == "traces.sqlite3")

b0_manifest2 = load_json(b0_local2.out_dir / "run_manifest.json")
identity_bad = [
    name
    for name in runner_mod.IDENTITY_FIELDS
    if b0_manifest.get(name) != b0_manifest2.get(name)
]
check("b0_two_local_identity_stable", not identity_bad, identity_bad)
check(
    "b0_two_local_run_id_diff",
    b0_manifest.get("run_id") != b0_manifest2.get("run_id"),
)
check(
    "b0_two_local_created_at",
    isinstance(b0_manifest.get("created_at"), str)
    and isinstance(b0_manifest2.get("created_at"), str),
)

check("b0_summary_case_count", b0_metrics.get("case_count") == 40)
check("b0_summary_scored_count", b0_metrics.get("scored_count") == 32)
check("b0_summary_skipped_count", b0_metrics.get("skipped_count") == 8)
check("b0_summary_error_count", b0_summary.get("error_count") == 0)
print(
    "NOTE b0_denominators"
    f" case_count={b0_manifest.get('case_count')}"
    f" scored_count={b0_metrics.get('scored_count')}"
    f" skipped_ocr={b0_metrics.get('skipped_count')}"
    f" metrics_scope_cases_in_denominator={(b0_summary.get('metrics_scope') or {}).get('cases_in_denominator')}"
)

for metric_name in ("Recall@10", "MRR@10", "nDCG@10"):
    values = [
        float(row["metrics"][metric_name])
        for row in b0_rows
        if row["status"] != "skipped_requires_ocr"
        and int(row["metrics"].get("gold_units") or 0) > 0
    ]
    expected = sum(values) / len(values)
    print(f"METRIC b0 {metric_name} = {b0_metrics.get(metric_name)!r}")
    check(
        f"b0_summary_{metric_name}_mean",
        abs(float(b0_metrics.get(metric_name)) - expected) < 1e-12,
        (b0_metrics.get(metric_name), expected),
    )
check("b0_report_recall", abs(float(b0_metrics.get("Recall@10")) - 0.96875) < 1e-12)
check(
    "b0_report_mrr",
    abs(float(b0_metrics.get("MRR@10")) - 0.8697916666666666) < 1e-9,
    b0_metrics.get("MRR@10"),
)
check(
    "b0_report_ndcg",
    abs(float(b0_metrics.get("nDCG@10")) - 0.8954577739955403) < 1e-9,
    b0_metrics.get("nDCG@10"),
)


def check_local_traces(label, run, rows):
    repo = TraceRepository(run.out_dir / "traces.sqlite3")
    problems = []
    try:
        for row in rows:
            try:
                record, spans = repo.get(row["trace_id"])
            except Exception as exc:
                problems.append((row["case_id"], f"get:{type(exc).__name__}"))
                continue
            if record.case_id != row["case_id"]:
                problems.append((row["case_id"], "case_id"))
            if row["status"] == "skipped_requires_ocr":
                if record.status != "incomplete" or spans:
                    problems.append((row["case_id"], "ocr-trace"))
                continue
            if record.run_id != run.manifest.run_id:
                problems.append((row["case_id"], "run_id"))
            if record.dataset_version != run.manifest.dataset_version:
                problems.append((row["case_id"], "dataset_version"))
            if record.index_revision != str(run.manifest.index_revision):
                problems.append((row["case_id"], "index_revision"))
            if record.manifest_sha256 != run.manifest.corpus_manifest_sha256:
                problems.append((row["case_id"], "manifest_sha256"))
            if record.pipeline_version != run.manifest.pipeline_version:
                problems.append((row["case_id"], "pipeline_version"))
            try:
                missing = validate_required_spans(record, [span.name for span in spans])
            except Exception as exc:
                problems.append((row["case_id"], f"spans-exc:{type(exc).__name__}:{exc}"))
                continue
            if missing:
                problems.append((row["case_id"], f"missing:{sorted(missing)}"))
    finally:
        repo.close()
    check(f"{label}_local_traces", not problems, problems[:5])


check_local_traces("b0", b0_local, b0_rows)

# ---------------------------------------------------------------------------
# Real unit attribution: separately rebuild the b0 index.
# ---------------------------------------------------------------------------
(TMP / "verify-b0").mkdir(parents=True, exist_ok=True)
b0_corpus = corpus_mod.load_suite_corpus("b0", ACCEPTANCE)
b0_cfg = corpus_mod.offline_eval_config(TMP / "verify-b0", b0_corpus.business_date or "2026-10-28")
b0_index, b0_stats = corpus_mod.build_suite_index(
    b0_corpus, TMP / "verify-b0" / "rag.sqlite3", config=b0_cfg
)
try:
    with b0_index.session() as session:
        b0_units = {
            str(unit.unit_id): unit
            for unit in session.execute(select(RagUnit)).scalars().all()
        }
    unit_problems = []
    for row in b0_rows:
        gold = row.get("gold")
        if gold:
            for source in gold.get("sources") or ():
                for unit_id in source.get("unit_ids") or ():
                    if unit_id not in b0_units:
                        unit_problems.append((row["case_id"], "gold", unit_id))
            for unit_id in gold.get("unit_ids") or ():
                if unit_id not in b0_units:
                    unit_problems.append((row["case_id"], "gold.unit_ids", unit_id))
            for unit_id in gold.get("relevant_unit_ids") or ():
                if unit_id not in b0_units:
                    unit_problems.append((row["case_id"], "gold.relevant", unit_id))
        outcome = row.get("outcome")
        if outcome:
            for citation in outcome.get("citations") or ():
                ids = citation.get("unit_ids") or []
                if len(ids) != 1 or ids[0] not in b0_units:
                    unit_problems.append((row["case_id"], "citation.unit_ids", ids))
                    continue
                unit = b0_units[ids[0]]
                if citation.get("unit_key") != unit.unit_key:
                    unit_problems.append((row["case_id"], "citation.unit_key", citation))
                if citation.get("doc_code") != unit.doc_id:
                    unit_problems.append((row["case_id"], "citation.doc_code", citation))
                if not isinstance(citation.get("locator"), dict):
                    unit_problems.append((row["case_id"], "citation.locator", citation))
            for item in outcome.get("retrieved") or ():
                ids = item.get("unit_ids") or []
                if len(ids) != 1 or ids[0] not in b0_units:
                    unit_problems.append((row["case_id"], "retrieved.unit_ids", ids))
                    continue
                unit = b0_units[ids[0]]
                if item.get("unit_key") != unit.unit_key:
                    unit_problems.append((row["case_id"], "retrieved.unit_key", item))
                if item.get("doc_code") != unit.doc_id:
                    unit_problems.append((row["case_id"], "retrieved.doc_code", item))
    check("b0_real_unit_attribution", not unit_problems, unit_problems[:5])

    # Direct RagIndex.ask for the three reported b0 failures.
    def minimal_outcome(answer):
        citations = []
        for item in answer.citations:
            chunk = b0_index.chunks_by_ids([str(item.source_id)])[0]
            for unit_id in chunk.unit_ids:
                unit = b0_units[str(unit_id)]
                citations.append(
                    EvalCitation(
                        doc_code=str(item.doc_id),
                        unit_key=unit.unit_key,
                        unit_ids=(str(unit_id),),
                        locator=dict(item.locator or {}),
                        text=str(item.text),
                        kind=str(item.kind),
                    )
                )
        retrieved = []
        for chunk_id in answer.diagnostics.get("evidence_ids") or ():
            chunk = b0_index.chunks_by_ids([str(chunk_id)])[0]
            for unit_id in chunk.unit_ids:
                unit = b0_units[str(unit_id)]
                retrieved.append(
                    EvalRetrieved(
                        doc_code=str(chunk.doc_id),
                        unit_ids=(str(unit_id),),
                        unit_key=unit.unit_key,
                        locator=dict(chunk.locator or {}),
                        chunk_id=str(chunk_id),
                    )
                )
        return EvalOutcome(
            kind=str(answer.kind),
            text=str(answer.text),
            citations=tuple(citations),
            retrieved=tuple(retrieved),
            path="rag",
            pagination={},
        )

    for case_id in ("Q25", "Q26", "Q31"):
        case = next(item for item in b0_cases if item.case_id == case_id)
        answer = b0_index.ask(
            case.question, user_id="verify", conversation_id=f"verify:{case_id}"
        )
        direct = score_case(case, resolve_case(case, b0_index), minimal_outcome(answer), None)
        run_row = next(row for row in b0_rows if row["case_id"] == case_id)
        direct_fails = [
            f"{item.check_id}:{item.status}"
            for item in direct.checks
            if item.status == "fail"
        ]
        run_fails = [
            f"{item['check_id']}:{item['status']}"
            for item in run_row["checks"]
            if item["status"] == "fail"
        ]
        missing = [value for value in case.expected_values if not check_value(answer.text, value)]
        print(f"DIRECT {case_id} status={direct.status} answer_kind={safe(answer.kind)}")
        print(f"DIRECT {case_id} fails={safe(direct_fails)}")
        print(f"DIRECT {case_id} expected_values_missing={safe(missing)}")
        check(f"direct_status_{case_id}", direct.status == run_row["status"], (direct.status, run_row["status"]))
        check(f"direct_fail_checks_{case_id}", direct_fails == run_fails, (direct_fails, run_fails))
finally:
    b0_index.close()

# ---------------------------------------------------------------------------
# badcase local artifacts
# ---------------------------------------------------------------------------
bad_rows = load_rows(badcase_local.out_dir / "cases.jsonl")
bad_manifest = load_json(badcase_local.out_dir / "run_manifest.json")
bad_summary = load_json(badcase_local.out_dir / "summary.json")
bad_metrics = bad_summary["metrics"]
check("badcase_files", {p.name for p in badcase_local.out_dir.iterdir()} == {
    "run_manifest.json",
    "cases.jsonl",
    "summary.json",
    "traces.sqlite3",
})
check("badcase_rows_13", len(bad_rows) == 13, len(bad_rows))
bad_status = Counter(str(row.get("status")) for row in bad_rows)
check(
    "badcase_status_counts",
    dict(bad_status) == {"pass": 9, "fail": 4},
    dict(bad_status),
)
check("badcase_no_error", all(row.get("error") is None for row in bad_rows))
empty_gold_bad = []
for case_id in ("N10", "N12", "N13"):
    row = next((item for item in bad_rows if item["case_id"] == case_id), None)
    if row is None:
        empty_gold_bad.append((case_id, "missing"))
        continue
    if row.get("status") == "error":
        empty_gold_bad.append((case_id, "error"))
    if int(row.get("metrics", {}).get("gold_units") or 0) != 0:
        empty_gold_bad.append((case_id, row.get("metrics")))
    if (row.get("gold") or {}).get("relevant_unit_ids") != []:
        empty_gold_bad.append((case_id, "relevant_unit_ids"))
check("badcase_empty_gold_rows", not empty_gold_bad, empty_gold_bad)
n05 = next(row for row in bad_rows if row["case_id"] == "N05")
n09 = next(row for row in bad_rows if row["case_id"] == "N09")
check("badcase_n05_range_11", len(n05["gold"]["relevant_unit_ids"]) == 11, len(n05["gold"]["relevant_unit_ids"]))
check("badcase_n09_range_17", len(n09["gold"]["relevant_unit_ids"]) == 17, len(n09["gold"]["relevant_unit_ids"]))
check("badcase_manifest_mode", bad_manifest.get("mode") == "local")
check("badcase_manifest_suite", bad_manifest.get("suite") == "badcase")
check("badcase_dataset_sha", bad_manifest.get("dataset_sha256") == sha256(BADCASE_DATASET))
check(
    "badcase_corpus_sha",
    bad_manifest.get("corpus_manifest_sha256") == sha256(BAD_CORPUS / "manifest.json"),
)
check("badcase_index_revision", bad_manifest.get("index_revision") == 4, bad_manifest.get("index_revision"))
check("badcase_case_count", bad_manifest.get("case_count") == 13)
for metric_name in ("Recall@10", "MRR@10", "nDCG@10"):
    print(f"METRIC badcase {metric_name} = {bad_metrics.get(metric_name)!r}")
check("badcase_report_recall", abs(float(bad_metrics.get("Recall@10")) - 0.7679144385026737) < 1e-9)
check("badcase_report_mrr", abs(float(bad_metrics.get("MRR@10")) - 0.7166666666666667) < 1e-9)
check("badcase_report_ndcg", abs(float(bad_metrics.get("nDCG@10")) - 0.6851021519869538) < 1e-9)

declarations = bad_summary.get("declarations") or {}
check(
    "badcase_declarations_single_turn",
    (declarations.get("execution") or {}).get("turns_executed") == 1
    and (declarations.get("execution") or {}).get("multi_turn_verified") is False
    and (declarations.get("execution") or {}).get("single_turn_case_ids") == ["N06", "N11"],
    declarations.get("execution"),
)
check(
    "badcase_declarations_pagination",
    (declarations.get("pagination") or {}).get("claimed") is False,
    declarations.get("pagination"),
)
check(
    "badcase_declarations_range_gold",
    (declarations.get("gold") or {}).get("range_gold_case_ids") == ["N05", "N09"],
    declarations.get("gold"),
)
check(
    "badcase_rows_single_turn_flags",
    all(
        row.get("turns_executed") == 1 and row.get("multi_turn_claimed") is False
        for row in bad_rows
    ),
)

check_local_traces("badcase", badcase_local, bad_rows)

# ---------------------------------------------------------------------------
# badcase real unit attribution
# ---------------------------------------------------------------------------
(TMP / "verify-badcase").mkdir(parents=True, exist_ok=True)
bad_corpus = corpus_mod.load_suite_corpus("badcase", BAD_CORPUS)
bad_cfg = corpus_mod.offline_eval_config(
    TMP / "verify-badcase", bad_corpus.business_date or "2026-10-28"
)
bad_index, bad_stats = corpus_mod.build_suite_index(
    bad_corpus, TMP / "verify-badcase" / "rag.sqlite3", config=bad_cfg
)
try:
    with bad_index.session() as session:
        bad_units = {
            str(unit.unit_id): unit
            for unit in session.execute(select(RagUnit)).scalars().all()
        }
    bad_unit_problems = []
    for row in bad_rows:
        gold = row.get("gold")
        if gold:
            for unit_id in list(gold.get("unit_ids") or ()) + list(
                gold.get("relevant_unit_ids") or ()
            ):
                if unit_id not in bad_units:
                    bad_unit_problems.append((row["case_id"], "gold", unit_id))
        outcome = row.get("outcome")
        if outcome:
            for citation in outcome.get("citations") or ():
                ids = citation.get("unit_ids") or []
                if len(ids) != 1 or ids[0] not in bad_units:
                    bad_unit_problems.append((row["case_id"], "citation.unit_ids", ids))
                    continue
                unit = bad_units[ids[0]]
                if citation.get("unit_key") != unit.unit_key:
                    bad_unit_problems.append((row["case_id"], "citation.unit_key", citation))
            for item in outcome.get("retrieved") or ():
                ids = item.get("unit_ids") or []
                if len(ids) != 1 or ids[0] not in bad_units:
                    bad_unit_problems.append((row["case_id"], "retrieved.unit_ids", ids))
                    continue
                unit = bad_units[ids[0]]
                if item.get("unit_key") != unit.unit_key:
                    bad_unit_problems.append((row["case_id"], "retrieved.unit_key", item))
    check("badcase_real_unit_attribution", not bad_unit_problems, bad_unit_problems[:5])
finally:
    bad_index.close()

# ---------------------------------------------------------------------------
# replay determinism
# ---------------------------------------------------------------------------
REPLAY_METRIC_KEYS = (
    "case_count",
    "scored_count",
    "skipped_count",
    "Recall@10",
    "MRR@10",
    "nDCG@10",
    "value_hit",
    "source_hit",
    "kind_correct",
    "citation_precision",
    "citation_recall",
    "refusal_recall",
    "false_refusal_rate",
    "refusal_precision",
    "hard_filter_violation_rate",
    "empty_recall_rate",
)


def check_replay(label, local_run, replay_run):
    local_rows = load_rows(local_run.out_dir / "cases.jsonl")
    replay_rows = load_rows(replay_run.out_dir / "cases.jsonl")
    check(f"{label}_replay_rows", len(replay_rows) == len(local_rows), (len(replay_rows), len(local_rows)))
    row_problems = []
    for local_row, replay_row in zip(local_rows, replay_rows):
        if replay_row.get("case_id") != local_row.get("case_id"):
            row_problems.append((local_row.get("case_id"), "case_id"))
        if replay_row.get("status") != local_row.get("status"):
            row_problems.append((local_row.get("case_id"), "status"))
        if replay_row.get("checks") != local_row.get("checks"):
            row_problems.append((local_row.get("case_id"), "checks"))
        if replay_row.get("metrics") != local_row.get("metrics"):
            row_problems.append((local_row.get("case_id"), "metrics"))
        if replay_row.get("replayed") is not True:
            row_problems.append((local_row.get("case_id"), "replayed"))
        if replay_row.get("previous_trace_id") != local_row.get("trace_id"):
            row_problems.append((local_row.get("case_id"), "previous_trace_id"))
    check(f"{label}_replay_rows_equal", not row_problems, row_problems[:5])
    local_metrics = load_json(local_run.out_dir / "summary.json")["metrics"]
    replay_metrics = load_json(replay_run.out_dir / "summary.json")["metrics"]
    metric_diff = [
        key
        for key in REPLAY_METRIC_KEYS
        if local_metrics.get(key) != replay_metrics.get(key)
    ]
    check(f"{label}_replay_summary_metrics", not metric_diff, metric_diff)
    check(
        f"{label}_replay_files",
        {p.name for p in replay_run.out_dir.iterdir()}
        == {"run_manifest.json", "cases.jsonl", "summary.json", "traces.sqlite3"},
    )
    replay_manifest = load_json(replay_run.out_dir / "run_manifest.json")
    check(f"{label}_replay_manifest_mode", replay_manifest.get("mode") == "replay")
    check(
        f"{label}_replay_source_run",
        replay_manifest.get("source_run_id") == local_run.manifest.run_id
        and replay_manifest.get("replay_from") == str(local_run.out_dir.resolve()),
    )
    identity_diff = [
        name
        for name in runner_mod.IDENTITY_FIELDS
        if name != "mode"
        and replay_manifest.get(name) != local_run.manifest.to_dict().get(name)
    ]
    check(f"{label}_replay_identity", not identity_diff, identity_diff)
    repo = TraceRepository(replay_run.out_dir / "traces.sqlite3")
    trace_problems = []
    try:
        for local_row, replay_row in zip(local_rows, replay_rows):
            record, spans = repo.get(replay_row["trace_id"])
            if record.replayed is not True:
                trace_problems.append((replay_row["case_id"], "replayed"))
            if record.mode != "replay":
                trace_problems.append((replay_row["case_id"], "mode"))
            if record.status != "replayed":
                trace_problems.append((replay_row["case_id"], "status"))
            if record.previous_trace_id != local_row["trace_id"]:
                trace_problems.append((replay_row["case_id"], "previous"))
            if spans:
                trace_problems.append((replay_row["case_id"], "spans"))
    finally:
        repo.close()
    check(f"{label}_replay_traces", not trace_problems, trace_problems[:5])


check_replay("b0", b0_local, b0_replay)
check_replay("badcase", badcase_local, badcase_replay)
b0_replay_rows = load_rows(b0_replay.out_dir / "cases.jsonl")
print(
    "NOTE replay_outcome_trace_id_equals_source_local"
    f" {all(row['outcome']['trace_id'] == local['trace_id'] for local, row in zip(b0_rows, b0_replay_rows) if row.get('outcome'))}"
    " (row.trace_id is the replay provenance trace)"
)

# ---------------------------------------------------------------------------
# record_code-only gold fail closed
# ---------------------------------------------------------------------------
record_rows = load_rows(record_local.out_dir / "cases.jsonl")
record_summary = load_json(record_local.out_dir / "summary.json")
check("record_code_rows_40", len(record_rows) == 40, len(record_rows))
first = record_rows[0]
check("record_code_status_error", first.get("status") == "error", first.get("status"))
check(
    "record_code_error_code",
    (first.get("error") or {}).get("code") == "record_code_only_gold",
    first.get("error"),
)
check(
    "record_code_no_gold_outcome",
    first.get("gold") is None and first.get("outcome") is None and first.get("checks") == [],
)
check("record_code_summary_error_count", record_summary.get("error_count") == 1)

record_replay_rows = load_rows(record_replay.out_dir / "cases.jsonl")
record_replay_first = record_replay_rows[0]
check(
    "record_code_replay_error",
    record_replay_first.get("status") == "error"
    and (record_replay_first.get("error") or {}).get("code") == "record_code_only_gold"
    and record_replay_first.get("previous_trace_id") == first.get("trace_id"),
    record_replay_first.get("error"),
)

# ---------------------------------------------------------------------------
# Zero-call guards
# ---------------------------------------------------------------------------
check("zero_provider_calls", COUNTS["provider"] == 0, COUNTS)
check("zero_socket_calls", COUNTS["socket"] == 0, COUNTS)
check("zero_settings_init", COUNTS["settings"] == 0, COUNTS)
check("zero_env_open", COUNTS["env_open"] == 0, COUNTS)
check("zero_replay_index_build", COUNTS["build_index"] == 0, COUNTS)

print(f"GUARDS provider={COUNTS['provider']} socket={COUNTS['socket']} "
      f"settings={COUNTS['settings']} env_open={COUNTS['env_open']} "
      f"build_index={COUNTS['build_index']}")
print(f"SUMMARY failures={len(FAILURES)}")
if FAILURES:
    print("FAILED " + ",".join(FAILURES))
sys.exit(1 if FAILURES else 0)
