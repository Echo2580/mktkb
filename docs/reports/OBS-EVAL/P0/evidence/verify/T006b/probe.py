# T006b independent verification probe (2026-11-05).
# Requires read-only T005 artifacts at %TEMP%\t005-runs\{b0-local,badcase-local}.
# Run: $env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"; .\.venv\Scripts\python.exe -B probe.py
# The probe creates fixtures only under %TEMP%\t006b-verify\probe and mutates copies there.
# -*- coding: utf-8 -*-
"""T006b independent verification probe (outside repo). Zero real provider calls."""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
TMP = Path(os.environ["TEMP"]) / "t006b-verify" / "probe"
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True)

from mktkb.evaluation.gate import (
    HARD_GATE_IDS,
    QualityPolicy,
    QualityWaiver,
    calibrate_gate,
    evaluate_gate,
    load_gate_config,
    load_run_result,
    write_gate_proposal,
)

CONFIG_PATH = REPO / "docs" / "evaluation" / "gate_v0_1.json"
EVID = REPO / "docs" / "reports" / "OBS-EVAL" / "P0" / "evidence" / "T006b"
DEV_B0 = Path(os.environ["TEMP"]) / "t005-runs" / "b0-local"
DEV_BAD = Path(os.environ["TEMP"]) / "t005-runs" / "badcase-local"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: object, detail: str = "") -> None:
    ok = bool(cond)
    RESULTS.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + ((" | " + detail) if detail else ""))


def expect_raises(name: str, exc_type: type[BaseException], fn) -> None:
    try:
        fn()
    except exc_type:
        check(name, True, exc_type.__name__)
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"wrong exception {type(exc).__name__}: {exc}")
    else:
        check(name, False, "no exception")


# --------------------------------------------------------------------------- #
# fixture helpers
# --------------------------------------------------------------------------- #
def metric(name, group, direction, *, min_sample=None, absolute_min=None,
           absolute_max=None, max_regression_pp=None):
    return {
        "name": name, "group": group, "direction": direction,
        "min_sample": min_sample, "absolute_min": absolute_min,
        "absolute_max": absolute_max, "max_regression_pp": max_regression_pp,
    }


def write_config(name, metrics, *, status="approved", hard_min=None,
                 gate_version="mktkb.gate.v0.1"):
    payload = {
        "schema_version": "mktkb.gate.config.v0.1",
        "gate_version": gate_version,
        "status": status,
        "hard_gates": list(HARD_GATE_IDS),
        "hard_gate_min_sample": hard_min or {"b0": 1},
        "sensitive_patterns": [],
        "metrics": metrics,
    }
    path = TMP / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return load_gate_config(path)


def case(cid, stratum="price", *, expected_kind="answer", should_refuse=False,
         expected_sources=(), forbidden_values=(), requires_ocr=False):
    refs = [{"doc_code": d, "unit_key": u} for d, u in expected_sources]
    return {
        "case_id": cid, "suite": "badcase", "split": "dev", "stratum": stratum,
        "business_date": "2026-11-01", "question": f"question {cid}", "turns": [],
        "expected_kind": expected_kind, "expected_values": [],
        "expected_sources": refs, "relevant_units": [],
        "reference_answer": "", "should_refuse": should_refuse,
        "refusal_reason": "unsafe" if should_refuse else None,
        "forbidden_values": list(forbidden_values), "forbidden_sources": [],
        "expected_pagination": None, "requires_ocr": requires_ocr,
        "labeler": "lead", "label_version": "synth-v0", "notes": "",
    }


def answer_outcome(text="ok", units=("u1",), citations=True):
    return {
        "kind": "answer", "text": text,
        "citations": [{"unit_ids": list(units)}] if citations else [],
        "retrieved": [{"unit_ids": list(units)}],
    }


def row(cid, *, status="pass", outcome=None, metrics=None, refused=False,
        latency=10, cost=None, checks=None, error=None):
    payload = {
        "case_id": cid, "status": status,
        "outcome": answer_outcome() if outcome is None else outcome,
        "checks": checks or [], "metrics": metrics or {},
        "refused": refused, "latency_ms": latency, "cost_cny": cost,
    }
    if error:
        payload["error"] = error
    return payload


def write_run(name, cases, rows, summary_metrics, *, suite="badcase",
              pipeline_version="pv1", mode="local"):
    out = TMP / name
    out.mkdir(parents=True)
    dataset_text = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)
    dataset = out / "dataset.jsonl"
    dataset.write_text(dataset_text, encoding="utf-8")
    (out / "cases.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    manifest = {
        "run_id": name, "mode": mode, "scope": "end_to_end", "suite": suite,
        "dataset_version": "synth:v0", "dataset_sha256": hashlib.sha256(dataset_text.encode()).hexdigest(),
        "corpus_manifest_sha256": "0" * 64, "business_date": "2026-11-01",
        "index_revision": 0, "pipeline_version": pipeline_version,
        "gate_version": "mktkb.gate.v0.1", "label_version": "synth-v0",
        "created_at": "2026-11-05T00:00:00+00:00", "case_count": len(cases),
        "config_hash": "deadbeef", "trace_store": "traces.sqlite3",
        "dataset_path": str(dataset), "corpus_dir": None,
        "replay_from": None, "source_run_id": None,
    }
    (out / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    summary = {"metrics": summary_metrics, "case_count": len(cases),
               "scored_count": sum(1 for r in rows if r.get("status") in {"pass", "fail"})}
    (out / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return load_run_result(out)


# --------------------------------------------------------------------------- #
# A. config
# --------------------------------------------------------------------------- #
print("== A. config ==")
config = load_gate_config(CONFIG_PATH)
raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
check("A1 status unapproved", config.status == "unapproved", config.status)
check("A2 15 metrics / four groups", len(config.metrics) == 15 and
      {m.group for m in config.metrics} == {"retrieval", "answer", "refusal", "runtime"},
      f"{len(config.metrics)}")
check("A3 all thresholds null",
      all(m.absolute_min is None and m.absolute_max is None and
          m.max_regression_pp is None and m.min_sample is None for m in config.metrics))
check("A4 hard_gate_min_sample b0=32 badcase=13",
      dict(config.min_sample) == {"b0": 32, "badcase": 13}, str(dict(config.min_sample)))
check("A5 config hash", config.config_hash.startswith("eeb70a6c2d3b"), config.config_hash[:16])
file_sha = hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()
check("A6 file sha256", file_sha.startswith("8b3718247208"), file_sha[:16])
legacy = TMP / "legacy.json"
legacy_payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
legacy_payload["min_sample"] = legacy_payload.pop("hard_gate_min_sample")
legacy.write_text(json.dumps(legacy_payload), encoding="utf-8")
expect_raises("A7 legacy min_sample rejected", ValueError, lambda: load_gate_config(legacy))
check("A8 quality_layer metadata",
      raw.get("quality_layer", {}).get("status") == "unapproved" and
      raw.get("quality_layer", {}).get("denominators", {}).get("retrieval", "").startswith("gold_cases_non_ocr"))
check("A9 no composite metric", not any(
    str(m.name).lower() in {"score", "composite", "overall"} for m in config.metrics))


# --------------------------------------------------------------------------- #
# B. calibration reproducibility (T005 run artifacts, read-only)
# --------------------------------------------------------------------------- #
print("== B. calibration ==")
b0 = load_run_result(DEV_B0)
bad = load_run_result(DEV_BAD)
config_sha_before = hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()
prop_b0 = calibrate_gate(b0, config)
prop_bad = calibrate_gate(bad, config)
delivered_b0 = json.loads((EVID / "gate-proposal.json").read_text(encoding="utf-8"))
delivered_bad = json.loads((EVID / "badcase-proposal.json").read_text(encoding="utf-8"))
check("B1 b0 proposal object-identical", prop_b0.to_dict() == delivered_b0)
check("B2 badcase proposal object-identical", prop_bad.to_dict() == delivered_bad)
check("B3 config bytes unchanged", hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest() == config_sha_before)
check("B4 proposal status/run/hash", prop_b0.status == "unapproved" and
      prop_b0.run_id == b0.manifest.run_id and prop_b0.gate_config_hash == config.config_hash)
check("B5 proposal counts 45/105", len(prop_b0.metrics) == 45 and len(prop_bad.metrics) == 105)
p0 = {(m["metric"], m["stratum"]): m for m in prop_b0.metrics}
p2 = {(m["metric"], m["stratum"]): m for m in prop_bad.metrics}
check("B6 b0 denominators 32/32", p0[("Recall@10", "all")]["denominator"] == 32 and
      p0[("value_hit", "all")]["denominator"] == 32,
      f"{p0[('Recall@10','all')]['denominator']}/{p0[('value_hit','all')]['denominator']}")
check("B7 badcase denominators 10/13", p2[("Recall@10", "all")]["denominator"] == 10 and
      p2[("value_hit", "all")]["denominator"] == 13,
      f"{p2[('Recall@10','all')]['denominator']}/{p2[('value_hit','all')]['denominator']}")
check("B8 badcase refusal denominators 2/11/2",
      p2[("refusal_recall", "all")]["denominator"] == 2 and
      p2[("false_refusal_rate", "all")]["denominator"] == 11 and
      p2[("refusal_precision", "all")]["denominator"] == 2)
check("B9 badcase 7 strata, no ocr", set(prop_bad.strata) ==
      {"all", "clarify", "notice", "policy", "poster", "price", "safety"} and "ocr" not in prop_bad.strata)
check("B10 b0 only 3 strata", set(prop_b0.strata) == {"all", "exact", "text"})
check("B11 b0 Recall observation/suggestion",
      p0[("Recall@10", "all")]["observed"] == 0.96875 and
      p0[("Recall@10", "all")]["suggested"]["absolute_min"] == 0.9487 and
      p0[("Recall@10", "all")]["suggested"]["max_regression_pp"] == 2.0 and
      p0[("Recall@10", "all")]["suggested"]["min_sample"] == 32)
check("B12 badcase Recall observation/suggestion",
      abs(p2[("Recall@10", "all")]["observed"] - 0.7679144385026737) < 1e-12 and
      p2[("Recall@10", "all")]["suggested"]["absolute_min"] == 0.7479)
check("B13 runtime not auto-suggested",
      all(p0[(name, "all")]["suggested"]["absolute_min"] is None and
          p0[(name, "all")]["suggested"]["absolute_max"] is None and
          p0[(name, "all")]["suggested"]["max_regression_pp"] is None
          for name in ("p95_latency_ms", "cost_per_case_cny")))
check("B14 value_no_fabricated diagnostic-only",
      prop_b0.diagnostics["value_no_fabricated"]["participates_in_gate"] is False and
      not any(m["metric"] == "value_no_fabricated" for m in prop_b0.metrics))
expect_raises("B15 write proposal onto gate config rejected", ValueError,
              lambda: write_gate_proposal(prop_b0, CONFIG_PATH, overwrite=True))
approved_prop_cfg = write_config("cal-approved.json", [
    metric("Recall@10", "retrieval", "higher_is_better", min_sample=32, absolute_min=0.5)
], status="approved", hard_min={"b0": 32})
prop_approved_in = calibrate_gate(b0, approved_prop_cfg)
check("B17 calibration status stays unapproved even with approved config",
      prop_approved_in.status == "unapproved" and
      {m["status"] for m in prop_approved_in.metrics} == {"unapproved"})

out_path = TMP / "proposal-out.json"
write_gate_proposal(prop_b0, out_path)
check("B16 proposal write UTF-8 no BOM", out_path.read_bytes()[:3] != b"\xef\xbb\xbf" and
      json.loads(out_path.read_text(encoding="utf-8"))["run_id"] == b0.manifest.run_id)


# --------------------------------------------------------------------------- #
# C. real-run quality outcomes
# --------------------------------------------------------------------------- #
print("== C. quality outcomes ==")
unapproved = evaluate_gate(b0, config=config, quality=True)
q = unapproved.quality
check("C1 unapproved b0 exit 3 / quality unknown",
      unapproved.exit_code == 3 and q.status == "unknown" and not unapproved.hard_failures,
      f"exit={unapproved.exit_code} status={q.status}")
check("C2 b0 42 approval unknowns, all thresholds_unapproved",
      len(q.unknowns) == 42 and {u.check_id for u in q.unknowns} == {"thresholds_unapproved"},
      str(len(q.unknowns)))
check("C3 no quality failure in unapproved", not q.failures)
bad_unapproved = evaluate_gate(bad, config=config, quality=True)
check("C4 unapproved badcase exit 3 / 105 metrics",
      bad_unapproved.exit_code == 3 and len(bad_unapproved.quality.metrics) == 105)

recall_ok = write_config("recall-ok.json", [
    metric("Recall@10", "retrieval", "higher_is_better", min_sample=1, absolute_min=0.5)
], hard_min={"b0": 32})
r = evaluate_gate(b0, config=recall_ok, quality=True)
check("C5 approved pass exit 0", r.exit_code == 0 and r.quality.status == "pass" and
      not r.quality.unknowns and not r.quality.failures,
      f"exit={r.exit_code} status={r.quality.status}")
check("C6 per-stratum observed exact=1.0 text=0.875",
      {(m.metric, m.stratum): m.observed for m in r.quality.metrics}[("Recall@10", "exact")] == 1.0 and
      {(m.metric, m.stratum): m.observed for m in r.quality.metrics}[("Recall@10", "text")] == 0.875)
check("C7 no composite key", "score" not in r.quality.to_dict() and
      "composite" not in r.quality.to_dict())

strict = write_config("recall-strict.json", [
    metric("Recall@10", "retrieval", "higher_is_better", min_sample=1, absolute_min=0.999)
], hard_min={"b0": 32})
r = evaluate_gate(b0, config=strict, quality=True)
check("C8 absolute_min miss exit 2", r.exit_code == 2 and r.quality.status == "fail" and
      not r.hard_failures and all(f.check_id == "absolute_min" for f in r.quality.failures),
      f"exit={r.exit_code} failures={[(f.check_id, f.evidence.get('stratum')) for f in r.quality.failures]}")

missing_min = write_config("recall-nomin.json", [
    metric("Recall@10", "retrieval", "higher_is_better", absolute_min=0.5)
], hard_min={"b0": 32})
r = evaluate_gate(b0, config=missing_min, quality=True)
check("C9 missing metric min_sample -> unknown",
      r.exit_code == 3 and any(u.check_id == "min_sample_missing" for u in r.quality.unknowns))

all_level_min = write_config("recall-min32.json", [
    metric("Recall@10", "retrieval", "higher_is_better", min_sample=32, absolute_min=0.5)
], hard_min={"b0": 32})
r = evaluate_gate(b0, config=all_level_min, quality=True)
check("C10 all-level min_sample 32 makes exact/text unknown (T009 constraint)",
      r.exit_code == 3 and r.quality.status == "unknown", f"exit={r.exit_code}")

# proposal suggestions applied as-is -> runtime metrics keep quality unknown
suggested_metrics = []
for item in config.metrics:
    s = p0[(item.name, "all")]["suggested"]
    suggested_metrics.append(metric(item.name, item.group, item.direction,
                                    min_sample=s["min_sample"], absolute_min=s["absolute_min"],
                                    absolute_max=s["absolute_max"],
                                    max_regression_pp=s["max_regression_pp"]))
suggested_config = write_config("proposal-as-config.json", suggested_metrics, hard_min={"b0": 32})
r = evaluate_gate(b0, config=suggested_config, quality=True)
check("C11 proposal-as-approved never passes (runtime/cost + text stratum thresholds)",
      r.exit_code == 3 and r.quality.status in {"fail", "unknown"},
      "exit=%s quality=%s unknown check ids=%s" % (r.exit_code, r.quality.status, sorted({u.check_id for u in r.quality.unknowns})))


# --------------------------------------------------------------------------- #
# D. denominator separation on a synthetic badcase-shaped run
# --------------------------------------------------------------------------- #
print("== D. denominators ==")
cases, rows = [], []
for i in range(1, 14):
    cid = f"D{i:02d}"
    has_gold = i <= 10
    cases.append(case(cid, "price", expected_sources=(("d1", f"u{i}"),) if has_gold else ()))
    metrics = {"value_hit": 1.0}
    if has_gold:
        metrics["Recall@10"] = 1.0
    rows.append(row(cid, metrics=metrics))
# OCR cases carry a *scored* row to prove case-level OCR exclusion (not row-status only).
cases.append(case("O1", "ocr", expected_kind="no_answer", should_refuse=True,
                  expected_sources=(("d9", "u91"),), requires_ocr=True))
cases.append(case("O2", "ocr", expected_kind="no_answer", should_refuse=True,
                  expected_sources=(("d9", "u92"),), requires_ocr=True))
rows.append(row("O1", outcome={"kind": "refusal", "text": "", "citations": [], "retrieved": []},
                refused=True))
rows.append(row("O2", outcome={"kind": "refusal", "text": "", "citations": [], "retrieved": []},
                refused=True))
den_run = write_run("denominators", cases, rows, {"Recall@10": 1.0, "value_hit": 1.0},
                    suite="badcase")
den_config = write_config("den-retrieval.json", [
    metric("Recall@10", "retrieval", "higher_is_better", min_sample=10, absolute_min=0.5)
], hard_min={"badcase": 13})
r = evaluate_gate(den_run, config=den_config, quality=True, require_trace=False)
check("D1 retrieval denominator 10 (13 scored, 2 OCR passed rows excluded)",
      r.exit_code == 0 and {(m.metric, m.stratum): m.denominator for m in r.quality.metrics}[("Recall@10", "all")] == 10,
      f"exit={r.exit_code}")
den11 = write_config("den-retrieval-11.json", [
    metric("Recall@10", "retrieval", "higher_is_better", min_sample=11, absolute_min=0.5)
], hard_min={"badcase": 13})
r = evaluate_gate(den_run, config=den11, quality=True, require_trace=False)
check("D2 min_sample 11 on 10 gold -> unknown (no hard_gate 13 reuse)",
      r.exit_code == 3 and any(u.check_id == "min_sample_not_met" for u in r.quality.unknowns))
ans13 = write_config("den-answer.json", [
    metric("value_hit", "answer", "higher_is_better", min_sample=13, absolute_min=0.5)
], hard_min={"badcase": 13})
r = evaluate_gate(den_run, config=ans13, quality=True, require_trace=False)
check("D3 answer denominator 13 (OCR rows excluded)", r.exit_code == 0,
      f"exit={r.exit_code} denom=" + str({(m.metric, m.stratum): m.denominator for m in r.quality.metrics}))
ans14 = write_config("den-answer-14.json", [
    metric("value_hit", "answer", "higher_is_better", min_sample=14, absolute_min=0.5)
], hard_min={"badcase": 13})
r = evaluate_gate(den_run, config=ans14, quality=True, require_trace=False)
check("D4 min_sample 14 on 13 scored -> unknown (proves 13, not 15)",
      r.exit_code == 3 and any(u.check_id == "min_sample_not_met" for u in r.quality.unknowns))
check("D5 no ocr stratum in quality report", "ocr" not in r.quality.strata, str(r.quality.strata))

# summary has metrics but one metric missing -> unknown not 0
missing_run = write_run("missing-metric", cases, rows, {"value_hit": 1.0},
                        suite="badcase")
r = evaluate_gate(missing_run, config=den_config, quality=True, require_trace=False)
recall_all = {(m.metric, m.stratum): m for m in r.quality.metrics}[("Recall@10", "all")]
check("D6 summary missing metric -> unknown observed=None",
      r.exit_code == 3 and recall_all.status == "unknown" and recall_all.observed is None and
      any(c.kind == "metric_missing" for c in recall_all.checks))

# boundary: summary lacks the whole metrics mapping -> implementation recomputes from rows
no_summary_dir = TMP / "no-summary-metrics"
shutil.copytree(TMP / "denominators", no_summary_dir)
summary = json.loads((no_summary_dir / "summary.json").read_text(encoding="utf-8"))
summary.pop("metrics", None)
(no_summary_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
r = evaluate_gate(load_run_result(no_summary_dir), config=den_config, quality=True,
                  require_trace=False)
print(f"INFO summary metrics mapping entirely absent -> exit={r.exit_code} "
      f"quality={r.quality.status} (recomputed from cases.jsonl, warning only)")

# absolute_max direction (lower_is_better)
refuse_cases = [
    case("R1", "safety", expected_kind="no_answer", should_refuse=True,
         expected_sources=(("d9", "u1"),)),
    case("R2", "safety", expected_kind="no_answer", should_refuse=True,
         expected_sources=(("d9", "u2"),)),
    case("R3", "safety", expected_kind="no_answer", should_refuse=True,
         expected_sources=(("d9", "u3"),)),
    case("R4", "safety", expected_kind="no_answer", should_refuse=True,
         expected_sources=(("d9", "u4"),)),
    case("A1", "safety", expected_sources=(("d1", "u3"),)),
]
refuse_rows = [
    row("R1", outcome={"kind": "refusal", "text": "", "citations": [], "retrieved": []}, refused=True),
    row("R2", outcome={"kind": "knowledge_changed", "text": "", "citations": [], "retrieved": []},
        refused=False, metrics={"value_hit": 0.0}),
    row("R3", outcome={"kind": "service_error", "text": "", "citations": [], "retrieved": []},
        refused=False, metrics={"value_hit": 0.0}),
    row("R4", outcome={"kind": "error", "text": "", "citations": [], "retrieved": []},
        refused=False, metrics={"value_hit": 0.0}),
    row("A1", metrics={"value_hit": 1.0}, refused=True),
]
ref_run = write_run("refusal", refuse_cases, refuse_rows,
                    {"refusal_recall": 1.0, "false_refusal_rate": 0.0},
                    suite="badcase")
ref_cfg = write_config("refusal-recall.json", [
    metric("refusal_recall", "refusal", "higher_is_better", min_sample=1, absolute_min=0.9)
], hard_min={"badcase": 5})
r = evaluate_gate(ref_run, config=ref_cfg, quality=True, require_trace=False)
obs = {(m.metric, m.stratum): m for m in r.quality.metrics}[("refusal_recall", "all")]
check("D7 refusal excludes knowledge_changed/service_error/error (denominator 1, observed 1.0)",
      r.exit_code == 0 and obs.denominator == 1 and obs.observed == 1.0,
      f"exit={r.exit_code} denom={obs.denominator} obs={obs.observed}")
false_cfg = write_config("false-refusal.json", [
    metric("false_refusal_rate", "refusal", "lower_is_better", min_sample=1, absolute_max=0.0)
], hard_min={"badcase": 5})
r = evaluate_gate(ref_run, config=false_cfg, quality=True, require_trace=False)
check("D8 absolute_max on lower_is_better -> exit 2",
      r.exit_code == 2 and any(f.check_id == "absolute_max" for f in r.quality.failures),
      f"exit={r.exit_code}")

# error row excluded from answer denominator (hard evaluated_count 13 -> 12)
err_cases = [case(f"E{i:02d}", "price", expected_sources=(("d1", f"u{i}"),)) for i in range(1, 14)]
err_rows = [row(f"E{i:02d}", metrics={"value_hit": 1.0}) for i in range(1, 13)]
err_rows.append(row("E13", status="error", outcome=None, error="boom"))
err_run = write_run("error-row", err_cases, err_rows,
                    {"value_hit": 1.0}, suite="badcase")
err_cfg = write_config("error-answer.json", [
    metric("value_hit", "answer", "higher_is_better", min_sample=12, absolute_min=0.5)
], hard_min={"badcase": 12})
r = evaluate_gate(err_run, config=err_cfg, quality=True, require_trace=False)
vh = {(m.metric, m.stratum): m for m in r.quality.metrics}[("value_hit", "all")]
check("D9 error row excluded from answer denominator (12)",
      vh.denominator == 12 and r.exit_code == 3,
      f"exit={r.exit_code} denom={vh.denominator}")
# hard min 12 and quality 12 should pass; error row still makes exit 3 via hard run unknown
check("D10 hard error row still forces exit 3 (hard layer regression)",
      r.exit_code == 3 and any(u.gate_id == "run" and u.check_id == "case_error" for u in r.unknowns),
      f"exit={r.exit_code}")


# --------------------------------------------------------------------------- #
# E. baseline regression (same version / cross version / none)
# --------------------------------------------------------------------------- #
print("== E. baseline ==")
reg_cfg = write_config("regression.json", [
    metric("Recall@10", "retrieval", "higher_is_better", min_sample=1,
           absolute_min=0.5, max_regression_pp=1.0)
], hard_min={"b0": 32})
summary = dict(b0.summary)
summary["metrics"] = dict(summary["metrics"])
summary["metrics"]["Recall@10"] = 0.99
baseline_same = dataclasses.replace(b0, summary=summary)
r = evaluate_gate(b0, baseline=baseline_same, config=reg_cfg, quality=True)
reg = [f for f in r.quality.failures if f.check_id == "max_regression_pp"]
check("E1 same-version regression -> exit 2",
      r.exit_code == 2 and len(reg) == 1 and reg[0].evidence["stratum"] == "all" and
      abs(reg[0].evidence["delta_pp"] - 2.125) < 1e-9,
      f"exit={r.exit_code} delta={reg[0].evidence['delta_pp'] if reg else None}")
baseline_cross = dataclasses.replace(
    baseline_same, manifest=dataclasses.replace(b0.manifest, pipeline_version="pv-other")
)
r = evaluate_gate(b0, baseline=baseline_cross, config=reg_cfg, quality=True)
check("E2 cross-version regression rejected -> unknown exit 3",
      r.exit_code == 3 and not r.quality.failures and
      any(u.check_id == "cross_pipeline_version" for u in r.quality.unknowns),
      f"exit={r.exit_code}")
r = evaluate_gate(b0, config=reg_cfg, quality=True)
reg_checks = [c for m in r.quality.metrics for c in m.checks if c.kind == "max_regression_pp"]
check("E3 no baseline -> max_regression_pp skipped, exit 0",
      r.exit_code == 0 and all(c.status == "skipped" for c in reg_checks))


# --------------------------------------------------------------------------- #
# F. waiver
# --------------------------------------------------------------------------- #
print("== F. waiver ==")
expect_raises("F1 missing reason", ValueError, lambda: QualityWaiver(reason="", approver="master"))
expect_raises("F2 missing approver", ValueError, lambda: QualityWaiver(reason="r", approver=" "))
expect_raises("F3 hard gate id rejected", ValueError,
              lambda: QualityWaiver(reason="r", approver="master", metric="trace_integrity"))
ok_waiver = QualityWaiver(reason="fixture", approver="master", metric="Recall@10")
policy = QualityPolicy(waivers=(ok_waiver,))
r = evaluate_gate(b0, config=strict, quality=policy)
check("F4 global quality waiver -> exit 0 pass_with_waivers",
      r.exit_code == 0 and r.quality.status == "pass_with_waivers" and
      len(r.quality.waived) == 2 and not r.quality.failures,
      f"exit={r.exit_code} status={r.quality.status} waived={len(r.quality.waived)}")
check("F5 waiver reason/approver in warnings",
      any("reason=fixture" in w and "approver=master" in w for w in r.warnings))
only_all = QualityWaiver(reason="fixture", approver="master", metric="Recall@10", stratum="all")
r = evaluate_gate(b0, config=strict, quality=QualityPolicy(waivers=(only_all,)))
check("F6 stratum-scoped waiver leaves text failure -> exit 2",
      r.exit_code == 2 and len(r.quality.waived) == 1 and len(r.quality.failures) == 1)
unapproved_thresholds = write_config("unapproved-thresholds.json", [
    metric("Recall@10", "retrieval", "higher_is_better", min_sample=1, absolute_min=0.5)
], status="unapproved", hard_min={"b0": 32})
r = evaluate_gate(b0, config=unapproved_thresholds, quality=policy)
check("F7 waiver does not turn unapproved unknown into pass",
      r.exit_code == 3 and r.quality.status == "unknown", f"exit={r.exit_code}")

# hard failure + quality failure + waiver -> exit 1
sec_cases = [case("S1", "price", expected_sources=(("d1", "u1"),), forbidden_values=("SECRET",))]
sec_rows = [row("S1", outcome=answer_outcome(text="SECRET leaked"), metrics={"Recall@10": 1.0})]
sec_run = write_run("security", sec_cases, sec_rows, {"Recall@10": 1.0}, suite="b0")
sec_cfg = write_config("security-config.json", [
    metric("Recall@10", "retrieval", "higher_is_better", min_sample=1, absolute_min=1.01)
], hard_min={"b0": 1})
r = evaluate_gate(sec_run, config=sec_cfg, quality=policy, require_trace=False)
check("F8 hard security_leak + quality fail + waiver -> exit 1",
      r.exit_code == 1 and "security_leak" in r.hard_failures and
      r.quality.status == "pass_with_waivers",
      f"exit={r.exit_code} hard={r.hard_failures} quality={r.quality.status}")


# --------------------------------------------------------------------------- #
# G. hard-gate regression / trace / live
# --------------------------------------------------------------------------- #
print("== G. hard gates ==")
check("G1 8 hard gate ids unchanged", tuple(HARD_GATE_IDS) == (
    "security_leak", "cross_entity", "stale_bypass", "conflict_not_rejected",
    "exact_value_contract", "pagination_contract", "citation_required", "trace_integrity"))
r = evaluate_gate(b0, config=config, quality=True, require_trace=False)
check("G2 trace skip still exit 3 only for quality approval", r.exit_code == 3 and
      r.gate_status["trace_integrity"] == "not_applicable")
trace_dir = TMP / "trace-bad"
shutil.copytree(DEV_B0, trace_dir)
conn = sqlite3.connect(trace_dir / "traces.sqlite3")
conn.execute("UPDATE schema_meta SET value='mktkb.trace.v9.9' WHERE key='trace_schema_version'")
conn.commit()
conn.close()
trace_run = load_run_result(trace_dir)
r = evaluate_gate(trace_run, config=config, quality=True)
check("G3 trace schema mismatch -> hard exit 1",
      r.exit_code == 1 and r.hard_failures == ("trace_integrity",),
      f"exit={r.exit_code} hard={r.hard_failures}")
live_run = dataclasses.replace(b0, manifest=dataclasses.replace(b0.manifest, mode="live"))
r = evaluate_gate(live_run, config=config, quality=True)
check("G4 live -> exit 4, quality not evaluated",
      r.exit_code == 4 and r.quality is None and
      set(r.gate_status.values()) == {"not_evaluated"})
r = evaluate_gate(b0, config=config)
check("G5 quality=False keeps T006a exit 0 / quality None",
      r.exit_code == 0 and r.quality is None and not r.unknowns)


# --------------------------------------------------------------------------- #
# H. mutation probes (repo-external copies)
# --------------------------------------------------------------------------- #
print("== H. mutations ==")
SOURCE = (REPO / "backend" / "src" / "mktkb" / "evaluation" / "gate.py").read_text(encoding="utf-8")
MUT = TMP / "mutations"
MUT.mkdir()


def load_mutated(name: str, old: str, new: str):
    source = SOURCE
    assert source.count(old) == 1, f"mutation anchor count {source.count(old)}: {old}"
    source = source.replace(old, new)
    path = MUT / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("mktkb.evaluation.gate", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["mktkb.evaluation.gate"] = module
    spec.loader.exec_module(module)
    return module


# H1: unapproved treated as approved
mut = load_mutated("unapproved_as_approved",
                   "if str(config.status) != QUALITY_APPROVED_STATUS:",
                   "if False:  # mutation")
cfg = mut.load_gate_config(TMP / "unapproved-thresholds.json")
rr = mut.load_run_result(DEV_B0)
res = mut.evaluate_gate(rr, config=cfg, quality=True)
check("H1 mutation unapproved-as-approved turns green (exit 0, not 3)",
      res.exit_code == 0, f"mutant exit={res.exit_code}")

# H2: hard-gate waiver guard removed
mut = load_mutated("waiver_hard_gate",
                   "if self.metric is not None and self.metric in HARD_GATE_IDS:",
                   "if False:  # mutation")
try:
    mut.QualityWaiver(reason="r", approver="master", metric="trace_integrity")
    accepted = True
except ValueError:
    accepted = False
check("H2 mutation accepts hard-gate waiver (guard removal turns probe red)", accepted)

# H3: cross-version regression check disabled
mut = load_mutated("cross_version_enabled",
                   'if context.pipeline_version != str(identity.get("pipeline_version") or ""):',
                   "if False:  # mutation")
cfg = mut.load_gate_config(TMP / "regression.json")
rr = mut.load_run_result(DEV_B0)
base = dataclasses.replace(
    rr, summary={**rr.summary, "metrics": {**rr.summary["metrics"], "Recall@10": 0.99}},
    manifest=dataclasses.replace(rr.manifest, pipeline_version="pv-other"),
)
res = mut.evaluate_gate(rr, baseline=base, config=cfg, quality=True)
check("H3 mutation cross-version regression applies (exit 2, not unknown 3)",
      res.exit_code == 2, f"mutant exit={res.exit_code}")

# H4: quality min_sample replaced by hard-gate 13
mut = load_mutated("min_sample_hardcoded",
                   "elif observation.denominator < spec.min_sample:",
                   "elif observation.denominator < 13:  # mutation")
cfg = mut.load_gate_config(TMP / "den-retrieval.json")
rr = mut.load_run_result(TMP / "denominators")
res = mut.evaluate_gate(rr, config=cfg, quality=True)
check("H4 mutation hard-gate 13 used for retrieval (exit 3, not 0)",
      res.exit_code == 3, f"mutant exit={res.exit_code}")

failed = [name for name, ok, _ in RESULTS if not ok]
print(f"SUMMARY total={len(RESULTS)} passed={len(RESULTS) - len(failed)} failed={len(failed)}")
if failed:
    print("FAILED: " + "; ".join(failed))
    sys.exit(1)
