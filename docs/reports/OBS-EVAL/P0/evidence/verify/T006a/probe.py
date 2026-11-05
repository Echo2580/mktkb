#!/usr/bin/env python
"""Independent T006a verification probe.

Read-only against the repository; every run directory is created under the
system temp directory. No model / OCR / embedding / rerank provider is used.
The probe constructs its own CaseSpec/RunManifest/RunResult/trace records and
does not import the package's test helpers.

Exit status is 1 when any expected property fails.
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import gate as gate_module
from mktkb.evaluation.dataset import CaseSpec, write_cases
from mktkb.evaluation.gate import (
    EXIT_HARD_FAILURE,
    EXIT_LIVE_UNAUTHORIZED,
    EXIT_PASS,
    EXIT_QUALITY_REGRESSION,
    EXIT_UNKNOWN,
    HARD_GATE_IDS,
    evaluate_gate,
    load_gate_config,
)
from mktkb.evaluation.runner import RunManifest, RunResult, run_suite
from mktkb.observability.contracts import (
    GATE_SCHEMA_VERSION,
    SpanRecord,
    TraceRecord,
)
from mktkb.observability.store import TraceRepository

DEFAULT_CONFIG = ROOT / "docs" / "evaluation" / "gate_v0_1.json"
CASES: list[dict[str, Any]] = []


def check(label: str, condition: bool, detail: Any = "") -> None:
    status = "PASS" if condition else "FAIL"
    text = "" if detail == "" else f" :: {detail}"
    print(f"{status} {label}{text}")
    CASES.append({"label": label, "ok": bool(condition), "detail": str(detail)})


def brief(result: Any) -> str:
    """Compact result projection for evidence output."""
    if not hasattr(result, "exit_code"):
        return str(result)
    unknowns = [(item.gate_id, item.check_id) for item in result.unknowns]
    failing = [
        (item.gate_id, item.case_id, item.check_id) for item in result.failures
    ]
    return (
        f"exit={result.exit_code} hard={list(result.hard_failures)} "
        f"unknown={unknowns} failing={failing} status={dict(result.gate_status)}"
    )


def case(case_id: str = "Q01", **overrides: Any) -> CaseSpec:
    payload = {
        "case_id": case_id,
        "suite": "b0",
        "split": "dev",
        "stratum": "exact",
        "business_date": "2026-10-28",
        "question": "P01 在哪里？",
        "expected_kind": "answer",
        "expected_values": ("P01",),
        "expected_sources": ({"doc_code": "D01", "unit_key": "K1"},),
        "labeler": "lead",
        "label_version": "v1",
    }
    payload.update(overrides)
    return CaseSpec(**payload)


def manifest(**overrides: Any) -> RunManifest:
    payload = {
        "run_id": "run-x",
        "mode": "local",
        "scope": "end_to_end",
        "suite": "b0",
        "dataset_version": "b0:v1:deadbeef",
        "dataset_sha256": "a" * 64,
        "corpus_manifest_sha256": "b" * 64,
        "business_date": "2026-10-28",
        "index_revision": 1,
        "pipeline_version": "pipeline",
        "gate_version": GATE_SCHEMA_VERSION,
        "label_version": "v1",
        "created_at": "2026-11-05T00:00:00Z",
        "case_count": 1,
        "config_hash": "c" * 12,
        "dataset_path": "",
    }
    payload.update(overrides)
    return RunManifest(**payload)


def citation(**overrides: Any) -> dict[str, Any]:
    payload = {"doc_code": "D01", "unit_key": "K1", "unit_ids": ["U1"], "locator": {}}
    payload.update(overrides)
    return payload


def retrieved(**overrides: Any) -> dict[str, Any]:
    payload = {"doc_code": "D01", "unit_key": "K1", "unit_ids": ["U1"], "locator": {}}
    payload.update(overrides)
    return payload


def row(
    c: CaseSpec,
    *,
    kind: str | None = "answer",
    text: str = "P01 位于 A 区",
    citations: list[dict[str, Any]] | None = None,
    retrieved_items: list[dict[str, Any]] | None = None,
    pagination: Any = None,
    status: str = "pass",
    checks: list[dict[str, Any]] | None = None,
    error: Any = None,
    outcome_missing: bool = False,
    gold_relevant: tuple[str, ...] = ("U1",),
    gold_sources: tuple[dict[str, Any], ...] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    if citations is None:
        citations = [citation()]
    if retrieved_items is None:
        retrieved_items = [retrieved()]
    if pagination is None:
        pagination = {}
    if gold_sources is None:
        gold_sources = (
            ({"doc_code": "D01", "unit_ids": ["U1"], "unit_keys": ["K1"]},)
            if gold_relevant
            else ()
        )
    resolved_trace_id = trace_id or f"t-{c.case_id}"
    outcome = {
        "kind": kind,
        "text": text,
        "path": "rag",
        "trace_id": resolved_trace_id,
        "pagination": pagination,
        "citations": citations,
        "retrieved": retrieved_items,
    }
    return {
        "case_id": c.case_id,
        "status": status,
        "trace_id": resolved_trace_id,
        "replayed": False,
        "checks": checks or [],
        "outcome": None if outcome_missing else outcome,
        "gold": {
            "case_id": c.case_id,
            "requires_ocr": False,
            "skipped": status == "skipped_requires_ocr",
            "sources": list(gold_sources),
            "unit_ids": list(gold_relevant),
            "relevant_unit_ids": list(gold_relevant),
        },
        "error": error,
    }


def write_trace(
    repo: TraceRepository,
    man: RunManifest,
    case_id: str,
    *,
    spans: tuple[str, ...] = ("parse", "recall", "fuse", "answer", "commit"),
    path: str | None = "rag",
    outcome: str | None = "answer",
    reason: str | None = None,
    replayed: bool = False,
    status: str | None = None,
    **overrides: Any,
) -> str:
    trace_id = str(overrides.pop("trace_id", f"t-{case_id}"))
    fields = {
        "trace_id": trace_id,
        "mode": man.mode,
        "scope": man.scope,
        "path": path,
        "case_id": case_id,
        "replayed": replayed,
        "dataset_version": man.dataset_version,
        "run_id": man.run_id,
        "index_revision": str(man.index_revision),
        "manifest_sha256": man.corpus_manifest_sha256,
        "pipeline_version": man.pipeline_version,
        "config_hash": man.config_hash,
        "outcome_kind": outcome,
        "reason": reason,
        "status": status or ("replayed" if replayed else "ok"),
    }
    fields.update(overrides)
    trace = TraceRecord(**fields)
    span_records = [
        SpanRecord(span_id=f"{trace_id}-{name}", trace_id=trace_id, name=name, status="ok")
        for name in dict.fromkeys(spans)
    ]
    repo.write(trace, span_records)
    return trace_id


def build_run(
    root: Path,
    cases: list[CaseSpec],
    rows: list[dict[str, Any]],
    *,
    trace_specs: dict[str, dict[str, Any] | None] | None = None,
    **manifest_overrides: Any,
) -> RunResult:
    root.mkdir(parents=True, exist_ok=True)
    dataset = root / "dataset.jsonl"
    write_cases(dataset, cases)
    suite = manifest_overrides.pop("suite", cases[0].suite if cases else "b0")
    man = manifest(suite=suite, dataset_path=str(dataset), case_count=len(cases), **manifest_overrides)
    run_dir = root / "run"
    run_dir.mkdir()
    repo = TraceRepository(run_dir / "traces.sqlite3")
    try:
        if trace_specs is not None:
            for case_id, spec in trace_specs.items():
                if spec is not None:
                    write_trace(repo, man, case_id, **spec)
    finally:
        repo.close()
    (run_dir / "run_manifest.json").write_text(
        json.dumps(man.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "cases.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps({"scored_count": sum(1 for item in rows if item["status"] in {"pass", "fail"})}),
        encoding="utf-8",
    )
    return RunResult(man, run_dir, tuple(rows), {})


def cfg(min_sample: dict[str, int] | None = None):
    loaded = load_gate_config(DEFAULT_CONFIG)
    if min_sample is not None:
        loaded = dataclasses.replace(loaded, min_sample=min_sample)
    return loaded


def failures(result: Any, gate_id: str) -> list[Any]:
    return [item for item in result.failures if item.gate_id == gate_id]


def failure_shape(result: Any, gate_id: str) -> bool:
    items = failures(result, gate_id)
    return bool(items) and all(
        item.case_id and item.check_id and isinstance(item.evidence, dict) and item.evidence
        for item in items
    )


def trigger(kind: str, c: CaseSpec, r: dict[str, Any], spec: dict[str, Any] | None) -> Any:
    with tempfile.TemporaryDirectory(prefix=f"t006a-{kind}-") as td:
        run = build_run(Path(td), [c], [r], trace_specs={c.case_id: spec})
        return evaluate_gate(run, config=cfg({"b0": 1, "badcase": 1}))


def real_runs() -> int:
    """Exercise T005's real local/replay products through the gate (offline)."""
    config = load_gate_config(DEFAULT_CONFIG)
    with tempfile.TemporaryDirectory(prefix="t006a-real-") as td:
        root = Path(td)
        for suite in ("b0", "badcase"):
            local = run_suite(suite, "local", out_dir=root / f"{suite}-local")
            replay = run_suite(suite, "replay", out_dir=root / f"{suite}-replay", replay_from=local.out_dir)
            for label, run in (("local", local), ("replay", replay)):
                res = evaluate_gate(run, config=config)
                check(
                    f"real.{suite}.{label}.exit0",
                    res.exit_code == EXIT_PASS and not res.hard_failures and not res.unknowns,
                    f"rows={len(run.cases)} scored={res.scored_count} min={res.min_sample} "
                    f"exit={res.exit_code} hard={list(res.hard_failures)} "
                    f"unknown={[(u.gate_id, u.check_id) for u in res.unknowns]} "
                    f"na={[n.gate_id for n in res.not_applicable]}",
                )
                check(
                    f"real.{suite}.{label}.denominator",
                    res.scored_count == (32 if suite == "b0" else 13),
                    f"scored={res.scored_count} (T005 b0=32, badcase rows pass/fail=13; "
                    "T005 metric denominator badcase=10 excluding empty gold)",
                )
    print(f"SUMMARY checks={len(CASES)} failed={sum(1 for item in CASES if not item['ok'])}")
    return 0 if all(item["ok"] for item in CASES) else 1


def main() -> int:
    # Default config skeleton.
    config = load_gate_config(DEFAULT_CONFIG)
    raw = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    check("config.hard_gates", tuple(config.hard_gates) == HARD_GATE_IDS, config.hard_gates)
    check("config.status", config.status == "unapproved", config.status)
    check("config.min_sample", dict(config.min_sample) == {"b0": 32, "badcase": 10}, dict(config.min_sample))
    thresholds = [(m.name, m.absolute_min, m.absolute_max, m.max_regression_pp) for m in config.metrics]
    check("config.thresholds_empty", all(a is None and b is None and c is None for _, a, b, c in thresholds), thresholds)
    check("config.metrics_count", len(config.metrics) == 15, len(config.metrics))
    check("config.no_waiver_api", not any(hasattr(gate_module, n) for n in ("waive", "waive_hard_gate", "calibrate_gate", "GateProposal")), "")
    import inspect

    check("config.no_waiver_arg", "waiver" not in inspect.signature(evaluate_gate).parameters and "waivers" not in inspect.signature(evaluate_gate).parameters, "")
    check("config.exit2_constant", EXIT_QUALITY_REGRESSION == 2, EXIT_QUALITY_REGRESSION)
    check("config.raw_thresholds_null", all(item.get("absolute_min") is None and item.get("absolute_max") is None and item.get("max_regression_pp") is None for item in raw["metrics"]), "")
    check("config.raw_status", raw.get("status") == "unapproved", raw.get("status"))

    # 8 gates: each has an independent sample.
    c = case("S01", stratum="text", expected_values=(), expected_sources=(), forbidden_values=("SECRET",))
    r = row(c, kind="answer", text="SECRET")
    res = trigger("security_leak", c, r, {})
    check("gate.security_leak", res.exit_code == EXIT_HARD_FAILURE and "security_leak" in res.hard_failures and failure_shape(res, "security_leak"), brief(res))
    check("gate.security_leak.only", set(res.hard_failures) == {"security_leak"}, res.hard_failures)

    c = case("X01")
    r = row(c, retrieved_items=[retrieved(hard_filter_violation="cross_entity")])
    res = trigger("cross_entity", c, r, {})
    check("gate.cross_entity", res.exit_code == EXIT_HARD_FAILURE and set(res.hard_failures) == {"cross_entity"} and failure_shape(res, "cross_entity"), brief(res))

    c = case("T01")
    r = row(c, retrieved_items=[retrieved(hard_filter_violation="stale")])
    res = trigger("stale_bypass", c, r, {})
    check("gate.stale_bypass", res.exit_code == EXIT_HARD_FAILURE and set(res.hard_failures) == {"stale_bypass"} and failure_shape(res, "stale_bypass"), brief(res))

    c = case("F01", expected_kind="conflict", stratum="text", expected_values=(), expected_sources=())
    r = row(c, kind="answer", text="safe")
    res = trigger("conflict_not_rejected", c, r, {"path": "rag", "outcome": "answer"})
    check("gate.conflict_not_rejected", res.exit_code == EXIT_HARD_FAILURE and set(res.hard_failures) == {"conflict_not_rejected"} and failure_shape(res, "conflict_not_rejected"), brief(res))

    c = case("E01")
    r = row(c, text="other")
    res = trigger("exact_value_contract", c, r, {})
    check("gate.exact_value_contract", res.exit_code == EXIT_HARD_FAILURE and set(res.hard_failures) == {"exact_value_contract"} and failure_shape(res, "exact_value_contract"), brief(res))

    c = case("G01", stratum="text", expected_values=(), expected_sources=(), expected_pagination={"total": 2})
    r = row(c, pagination={"total": 1, "returned": 1, "has_more": False, "next_page": None})
    res = trigger("pagination_contract", c, r, {})
    check("gate.pagination_contract", res.exit_code == EXIT_HARD_FAILURE and set(res.hard_failures) == {"pagination_contract"} and failure_shape(res, "pagination_contract"), brief(res))

    c = case("C01")
    r = row(c, citations=[])
    res = trigger("citation_required", c, r, {})
    check("gate.citation_required", res.exit_code == EXIT_HARD_FAILURE and set(res.hard_failures) == {"citation_required"} and failure_shape(res, "citation_required"), brief(res))

    c = case("Q01")
    r = row(c)
    res = trigger("trace_integrity", c, r, None)
    check("gate.trace_integrity", res.exit_code == EXIT_HARD_FAILURE and set(res.hard_failures) == {"trace_integrity"} and failure_shape(res, "trace_integrity"), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-exit0-") as td:
        c = case("Q01")
        run = build_run(Path(td), [c], [row(c)], trace_specs={"Q01": {}})
        res = evaluate_gate(run, config=cfg({"b0": 1, "badcase": 1}))
        check("exit.0_clean", res.exit_code == EXIT_PASS and not res.hard_failures and not res.unknowns, brief(res))
        check("exit.0_not_applicable", {"security_leak", "cross_entity", "stale_bypass", "conflict_not_rejected", "pagination_contract"} <= set(res.gate_status) and all(res.gate_status[g] == "not_applicable" for g in ("security_leak", "cross_entity", "stale_bypass", "conflict_not_rejected")), res.gate_status)

    with tempfile.TemporaryDirectory(prefix="t006a-exit3-") as td:
        c = case("Q01")
        run = build_run(Path(td), [c], [row(c)], trace_specs={"Q01": {}})
        res = evaluate_gate(run, config=cfg({"b0": 2, "badcase": 2}))
        check("exit.3_min_sample", res.exit_code == EXIT_UNKNOWN and any(u.gate_id == "min_sample" for u in res.unknowns), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-gold-") as td:
        c = case("Q01", expected_sources=({"doc_code": "D01", "record_code": "P01"},))
        run = build_run(Path(td), [c], [row(c)], trace_specs={"Q01": {}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("exit.3_record_code_only", res.exit_code == EXIT_UNKNOWN and any(u.gate_id == "gold" and u.check_id == "record_code_only_gold" for u in res.unknowns), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-gold2-") as td:
        c = case("Q01", expected_sources=({"doc_code": "D01", "record_code": "P01", "locator": {}},))
        run = build_run(Path(td), [c], [row(c)], trace_specs={"Q01": {}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("exit.3_record_code_empty_locator", res.exit_code == EXIT_UNKNOWN and any(u.gate_id == "gold" for u in res.unknowns), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-dataset-") as td:
        c = case("Q01")
        run = build_run(Path(td), [c], [row(c)], trace_specs={"Q01": {}})
        broken = Path(td) / "broken.jsonl"
        broken.write_text("{not-json\n", encoding="utf-8")
        res = evaluate_gate(run, config=cfg({"b0": 1}), dataset_path=broken)
        check("exit.3_corrupt_dataset", res.exit_code == EXIT_UNKNOWN and any(u.gate_id == "dataset" for u in res.unknowns), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-error-") as td:
        c = case("Q01")
        r = row(c, status="error", error={"code": "gold_unresolved", "message": "x"}, outcome_missing=True)
        run = build_run(Path(td), [c], [r], trace_specs={})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("exit.3_error_row", res.exit_code == EXIT_UNKNOWN and any(u.gate_id == "run" and u.check_id == "case_error" for u in res.unknowns), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-live-") as td:
        c = case("Q01")
        run = build_run(Path(td), [c], [row(c)], trace_specs={}, mode="live")
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("exit.4_live_direct", res.exit_code == EXIT_LIVE_UNAUTHORIZED and not res.hard_failures and not res.unknowns, brief(res))
        run2 = build_run(Path(td) / "upper", [c], [row(c)], trace_specs={}, mode="LIVE")
        check("exit.4_live_case_insensitive", evaluate_gate(run2, config=cfg({"b0": 1})).exit_code == EXIT_LIVE_UNAUTHORIZED, "")

    # PM rulings: fields and unit-level citation.
    with tempfile.TemporaryDirectory(prefix="t006a-citation-") as td:
        c = case("Q01")
        r = row(c, citations=[], checks=[{"check_id": "source_hit", "status": "pass", "evidence": {}}])
        run = build_run(Path(td), [c], [r], trace_specs={"Q01": {}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("pm.citation_not_source_hit", res.exit_code == EXIT_HARD_FAILURE and "citation_required" in res.hard_failures, brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-vnf-") as td:
        c = case("Q01")
        r = row(c, checks=[{"check_id": "value_no_fabricated", "status": "fail", "evidence": {}}])
        run = build_run(Path(td), [c], [r], trace_specs={"Q01": {}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("pm.value_no_fabricated_not_hard", res.exit_code == EXIT_PASS and not res.hard_failures, brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-unit-") as td:
        c = case("Q01", stratum="text", expected_values=(), expected_sources=(), forbidden_sources=({"doc_code": "D01", "unit_key": "K1"},))
        r = row(
            c,
            text="safe",
            citations=[citation(unit_key=None, unit_ids=["U1"])],
            retrieved_items=[retrieved(unit_key="K1", unit_ids=["U1"])],
        )
        run = build_run(Path(td), [c], [r], trace_specs={"Q01": {}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("pm.security_unit_ids_only", res.exit_code == EXIT_HARD_FAILURE and "security_leak" in res.hard_failures and any(x.check_id == "forbidden_source_citation" for x in failures(res, "security_leak")), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-unit2-") as td:
        c = case("Q01", stratum="text", expected_values=(), expected_sources=(), forbidden_sources=({"doc_code": "D01", "unit_key": "K1"},))
        r = row(
            c,
            text="safe",
            citations=[citation(unit_key=None, unit_ids=["U1"])],
            retrieved_items=[retrieved(unit_key=None, unit_ids=["U1"])],
            gold_sources=(),
        )
        run = build_run(Path(td), [c], [r], trace_specs={"Q01": {}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("pm.security_unresolved_is_unknown", res.exit_code == EXIT_UNKNOWN and any(u.gate_id == "security_leak" and u.check_id == "forbidden_ref_unresolved" for u in res.unknowns), brief(res))

    # Trace contract.
    no_answer = case("N01", stratum="text", expected_kind="no_answer", expected_values=(), expected_sources=(), should_refuse=True, refusal_reason="x")
    no_answer_row = row(no_answer, kind="no_answer", text="", citations=[], retrieved_items=[])
    with tempfile.TemporaryDirectory(prefix="t006a-reason1-") as td:
        run = build_run(Path(td), [no_answer], [no_answer_row], trace_specs={"N01": {"path": "rag", "outcome": "no_answer", "reason": "DOCUMENT_NOT_FOUND", "spans": ("parse", "commit")}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("trace.reason_document_not_found", res.exit_code == EXIT_PASS and res.gate_status["trace_integrity"] == "pass", brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-reason2-") as td:
        run = build_run(Path(td), [no_answer], [no_answer_row], trace_specs={"N01": {"path": "rag", "outcome": "no_answer", "reason": "UNKNOWN_REASON", "spans": ("parse", "commit")}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("trace.unknown_reason_still_requires_recall_fuse", res.exit_code == EXIT_HARD_FAILURE and set(failures(res, "trace_integrity")[0].evidence["missing"]) == {"recall", "fuse"}, brief(res))

    kc = case("K01", stratum="text", expected_kind="knowledge_changed", expected_values=(), expected_sources=(), should_refuse=True, refusal_reason="x")
    kc_row = row(kc, kind="knowledge_changed", text="", citations=[], retrieved_items=[])
    with tempfile.TemporaryDirectory(prefix="t006a-reason3-") as td:
        run = build_run(Path(td), [kc], [kc_row], trace_specs={"K01": {"path": "legacy", "outcome": "knowledge_changed", "reason": "KNOWLEDGE_CHANGED_AT_COMMIT", "spans": ("intent_parse", "commit")}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("trace.reason_knowledge_changed_at_commit", res.exit_code == EXIT_PASS and res.gate_status["trace_integrity"] == "pass", brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-replayed-") as td:
        c = case("R01")
        r = row(c, trace_id="t-R01")
        r["replayed"] = True
        run = build_run(Path(td), [c], [r], trace_specs={"R01": {"replayed": True, "path": None, "outcome": None, "spans": ()}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("trace.replayed_skip_path_outcome_spans", res.exit_code == EXIT_PASS and res.gate_status["trace_integrity"] == "pass", brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-replayed-json-") as td:
        c = case("R02")
        r = row(c, trace_id="t-R02")
        r["replayed"] = True
        run = build_run(Path(td), [c], [r], trace_specs={"R02": {"replayed": True, "path": None, "outcome": None, "spans": (), "pagination_json": "{bad"}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("trace.replayed_json_fail_closed", res.exit_code == EXIT_HARD_FAILURE and any(x.check_id == "json_invalid" for x in failures(res, "trace_integrity")), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-replayed-ver-") as td:
        c = case("R03")
        r = row(c, trace_id="t-R03")
        r["replayed"] = True
        run = build_run(Path(td), [c], [r], trace_specs={"R03": {"replayed": True, "path": None, "outcome": None, "spans": (), "dataset_version": "tampered"}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("trace.replayed_version_binding", res.exit_code == EXIT_HARD_FAILURE and any(x.check_id == "version_binding" for x in failures(res, "trace_integrity")), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-schema-record-") as td:
        c = case("V01")
        run = build_run(Path(td), [c], [row(c)], trace_specs={"V01": {}})
        con = sqlite3.connect(run.out_dir / "traces.sqlite3")
        con.execute("UPDATE traces SET trace_schema_version='mktkb.trace.v9.9'")
        con.commit(); con.close()
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("trace.record_schema_mismatch", res.exit_code == EXIT_HARD_FAILURE and any(x.check_id == "schema_version_mismatch" for x in failures(res, "trace_integrity")), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-trace-store-") as td:
        c = case("U01")
        run = build_run(Path(td), [c], [row(c)], trace_specs={"U01": {}})
        (run.out_dir / "traces.sqlite3").unlink()
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("trace.store_missing_unknown", res.exit_code == EXIT_UNKNOWN and any(u.gate_id == "trace_integrity" and u.check_id == "trace_store_unreadable" for u in res.unknowns), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-schema-meta-") as td:
        c = case("V02")
        run = build_run(Path(td), [c], [row(c)], trace_specs={"V02": {}})
        con = sqlite3.connect(run.out_dir / "traces.sqlite3")
        con.execute("UPDATE schema_meta SET value='mktkb.trace.v9.9' WHERE key='trace_schema_version'")
        con.commit(); con.close()
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("trace.store_schema_meta_mismatch", res.exit_code == EXIT_HARD_FAILURE and "trace_integrity" in res.hard_failures, brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-citation-kind-") as td:
        c = case("K02")
        r = row(c, kind=None, text="P01", citations=[])
        run = build_run(Path(td), [c], [r], trace_specs={"K02": {}})
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("pm.missing_kind_citation_unknown_or_fail", res.exit_code in {EXIT_HARD_FAILURE, EXIT_UNKNOWN} and res.gate_status["citation_required"] != "not_applicable", brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-security-missing-") as td:
        c = case("S02", stratum="text", expected_kind="no_answer", expected_values=(), expected_sources=(), should_refuse=True, refusal_reason="x", forbidden_values=("SECRET",))
        r = row(c, outcome_missing=True)
        run = build_run(Path(td), [c], [r], trace_specs={"S02": {"path": "rag", "outcome": "no_answer", "reason": "DOCUMENT_NOT_FOUND", "spans": ("parse", "commit")}})
        res = evaluate_gate(run, config=cfg({"badcase": 1, "b0": 1}))
        check("pm.security_missing_outcome_unknown", res.exit_code == EXIT_UNKNOWN and any(u.gate_id == "security_leak" for u in res.unknowns), brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-pagination-bad-") as td:
        c = case("P02", stratum="text", expected_values=(), expected_sources=(), expected_pagination={"total": 2})
        r = row(c, pagination="not-a-mapping")
        run = build_run(Path(td), [c], [r], trace_specs={"P02": {}})
        try:
            res = evaluate_gate(run, config=cfg({"b0": 1}))
            check("pm.pagination_malformed_fail_closed", res.exit_code == EXIT_UNKNOWN, brief(res))
        except Exception as exc:  # noqa: BLE001 - probe must report crash as failure
            check("pm.pagination_malformed_fail_closed", False, f"raised {type(exc).__name__}: {exc}")

    # T005's badcase denominator is 10: 3 empty-gold rows must not make 8
    # scorable cases look like 11.
    with tempfile.TemporaryDirectory(prefix="t006a-badcase-den-") as td:
        cs: list[CaseSpec] = []
        rs: list[dict[str, Any]] = []
        specs: dict[str, dict[str, Any]] = {}
        for index in range(11):
            cid = f"B{index:02d}"
            if index < 8:
                c = case(cid, suite="badcase", stratum="price")
                r = row(c)
            else:
                c = case(cid, suite="badcase", stratum="price", expected_values=(), expected_sources=())
                r = row(c, gold_relevant=(), gold_sources=())
            cs.append(c)
            rs.append(r)
            specs[cid] = {}
        run = build_run(Path(td), cs, rs, trace_specs=specs, suite="badcase")
        res = evaluate_gate(run, config=cfg({"badcase": 10, "b0": 1}))
        check("pm.badcase_denominator_10_not_13", res.exit_code == EXIT_UNKNOWN, brief(res))

    # Exit 2 is never returned by any hard-failure matrix sample.
    seen = set()
    for kind, c, r, spec in (
        ("security", case("A01", stratum="text", expected_values=(), expected_sources=(), forbidden_values=("S",)), None, {}),
        ("trace", case("A02"), row(case("A02")), None),
    ):
        if r is None:
            r = row(c)
        res = trigger(kind, c, r, spec)
        seen.add(res.exit_code)
    check("exit.2_never_hard", 2 not in seen, sorted(seen))

    # Baseline is explicitly ignored, trace can be opted out.
    with tempfile.TemporaryDirectory(prefix="t006a-baseline-") as td:
        c = case("Q01")
        run = build_run(Path(td), [c], [row(c)], trace_specs={"Q01": {}})
        res = evaluate_gate(run, object(), cfg({"b0": 1}))
        check("baseline.ignored_with_warning", res.exit_code == EXIT_PASS and any("baseline" in w for w in res.warnings), brief(res))
    with tempfile.TemporaryDirectory(prefix="t006a-require-trace-") as td:
        c = case("Q01")
        run = build_run(Path(td), [c], [row(c)], trace_specs={})
        res = evaluate_gate(run, config=cfg({"b0": 1}), require_trace=False)
        check("trace.require_trace_false", res.exit_code == EXIT_PASS and res.gate_status["trace_integrity"] == "not_applicable", brief(res))

    with tempfile.TemporaryDirectory(prefix="t006a-normal-json-") as td:
        c = case("J01")
        run = build_run(Path(td), [c], [row(c)], trace_specs={"J01": {}})
        con = sqlite3.connect(run.out_dir / "traces.sqlite3")
        con.execute("UPDATE traces SET citation_refs_json='{bad'")
        con.commit(); con.close()
        res = evaluate_gate(run, config=cfg({"b0": 1}))
        check("trace.normal_json_fail_closed", res.exit_code == EXIT_HARD_FAILURE and any(x.check_id == "json_invalid" for x in failures(res, "trace_integrity")), brief(res))

    # Real T005 artifacts are exercised separately by 03-real-runs.txt.
    print(f"SUMMARY checks={len(CASES)} failed={sum(1 for item in CASES if not item['ok'])}")
    return 0 if all(item["ok"] for item in CASES) else 1


if __name__ == "__main__":
    if "--real" in sys.argv:
        raise SystemExit(real_runs())
    raise SystemExit(main())
