"""Independent offline audit: public artifacts + safe H2 aggregates only."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[7]
BASE = ROOT / "docs/reports/OBS-EVAL/P2/T207"
OUT = BASE / "evidence/closeout-verify"
os.environ["MKTKB_NO_DOTENV"] = "1"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "backend/src"))
network_attempts = []


def deny_network(*args, **kwargs):
    network_attempts.append("denied")
    raise AssertionError("independent_closeout_network_forbidden")


socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network
from mktkb.evaluation.p2_score_run import load_cases_file, load_document_codes, score_run
from mktkb.evaluation.p2_authorization import read_ledger_snapshot


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


checks = []


def check(name, predicate):
    assert predicate, name
    checks.append(name)


expected_head = "93a89ec92682260c186256a98521becb49f413c8"
head_before = git("rev-parse", "HEAD").decode().strip()
check("review_base_HEAD", head_before == expected_head)
check("review_branch", git("branch", "--show-current").decode().strip() == "codex/p2-e2e")
verification = read(BASE / "scoring/closeout/verification.json")
matrix = read(BASE / "scoring/closeout/matrix_observation.json")
fixed = verification["fixed_files_before"]
before = {p: sha(ROOT / p) for p in fixed}
check("fixed_hashes_match_prior_frozen_snapshot", before == fixed == verification["fixed_files_after"])
input_hashes = []
for item in verification["inputs"]:
    actual = sha(ROOT / item["path"])
    check("input_hash:" + item["path"], actual == item["sha256"])
    input_hashes.append({"path": item["path"], "sha256": actual})

selection = {
    "R1-fixed": ("R1", {f"Q{i:02}" for i in range(1, 41)} | {f"N{i:02}" for i in range(1, 8)} | {f"C{i:02}" for i in range(1, 5)}),
    "R4": ("R4", {"N08", "C05", "C06"}),
    "R2-fixed": ("R2", {"U01"}),
}
codes = load_document_codes(BASE / "cases/document-codes.json")
selected, provenance = {}, []
for label, (tag, ids) in selection.items():
    run_dir = BASE / f"p2-t207-{tag.lower()}-20261111-01"
    case_path = BASE / f"cases/{tag}.jsonl"
    manifest, summary = read(run_dir / "run_manifest.json"), read(run_dir / "summary.json")
    saved = read(BASE / f"scoring/{label}/case_scores.json")
    bundle = score_run(run_dir, cases=load_cases_file(case_path), document_codes=codes)
    rescored = json.loads(json.dumps([dataclasses.asdict(s) for s in bundle.scores]))
    check(label + ":full_public_scores_equal", rescored == saved["case_scores"])
    check(label + ":live_identity", manifest["execution"] == bundle.execution_mode == saved["execution_mode"] == "live")
    check(label + ":run_id", manifest["run_id"] == summary["run_id"] == bundle.run_id == saved["run_id"])
    check(label + ":binding_complete", manifest["binding"]["complete"] and manifest["binding"]["trace_identity_bound"])
    check(label + ":dataset_hash", sha(case_path) == manifest["dataset_sha256"] == manifest["binding"]["dataset_sha256"])
    check(label + ":measured_outbound", summary["network"]["available"] is True and bundle.real_calls == summary["network"]["outbound_attempts"] == saved["real_calls"])
    check(label + ":no_mock_intercept", summary["network"]["detail"]["mock_intercepted"] == 0)
    for key in ("config_hash", "index_revision"):
        check(label + ":" + key, getattr(bundle, key) == manifest[key] == manifest["binding"][key] == saved[key])
    scores = {s.case_id: s for s in bundle.scores}
    check(label + ":selection_available", ids <= scores.keys())
    check(label + ":selection_policy", sorted(ids) == matrix["selection_policy"]["scope"][label])
    for cid in ids:
        check("unique:" + cid, cid not in selected)
        selected[cid] = (scores[cid], bundle)
    summary_path = (run_dir / "summary.json").relative_to(ROOT).as_posix()
    input_hashes.append({"path": summary_path, "sha256": sha(run_dir / "summary.json")})
    provenance.append({"source": label, "run_id": bundle.run_id, "public_cases_rescored": len(bundle.scores), "selected_count": len(ids), "execution_mode": bundle.execution_mode, "real_calls_full_run": bundle.real_calls, "index_revision": bundle.index_revision, "config_hash": bundle.config_hash, "pipeline_version": manifest["pipeline_version"], "created_at": manifest["created_at"]})
check("55_selected_unique_public_cases", len(selected) == len(matrix["cases"]) == 55 and matrix["duplicated_cases"] == {})
for row in matrix["cases"]:
    s, b = selected[row["case_id"]]
    check("matrix_provenance:" + s.case_id, all(row[k] == v for k, v in {"status": s.status, "suite": s.suite, "stratum": s.stratum, "run_id": b.run_id, "config_hash": b.config_hash, "index_revision": b.index_revision, "execution_mode": "live", "basis": "R", "real_calls": 0, "duplicated_in": []}.items()))
groups = {"b0": {f"Q{i:02}" for i in range(1, 41)}, "negative": {f"N{i:02}" for i in range(1, 9)}, "boundary": {f"C{i:02}" for i in range(1, 7)}}
counts = {}
for group, ids in groups.items():
    tally = Counter(selected[cid][0].status for cid in ids)
    counts[group] = {"total": len(ids), "pass": tally["pass"], "fail": tally["fail"]}
    check("manual_tally:" + group, len(ids) == matrix["tallies"][group]["planned"] and tally["pass"] == matrix["tallies"][group]["passed"] and tally["fail"] == matrix["tallies"][group]["failed"])
exact = [s for s, _ in selected.values() if s.stratum == "exact"]
ocr = [s for s, _ in selected.values() if s.requires_ocr]
check("exact24_of24", len(exact) == sum(s.status == "pass" for s in exact) == 24)
check("OCR7_of8", len(ocr) == 8 and sum(s.status == "pass" for s in ocr) == 7)
failures = [{"case_id": cid, "failed_checks": [c["check_id"] for c in s.checks if c["status"] == "fail"]} for cid, (s, _) in sorted(selected.items()) if s.status != "pass"]
check("failures_preserved", failures == [{"case_id": "Q25", "failed_checks": ["value_hit"]}, {"case_id": "Q33", "failed_checks": ["source_hit"]}])
controls = read(BASE / "scoring/u-controls.json")
check("prior_U_time_and_exit", controls["generated_utc"] == "2026-11-11T07:17:40+00:00" and controls["exit_code"] == 0)
check("prior_U_10of10", set(controls["cases"]) == {f"U{i:02}" for i in range(1, 11)} and all(c["status"] == "pass" for c in controls["cases"].values()))
check("U_test_source_exists", (ROOT / controls["source"]).is_file())
test_text = (ROOT / controls["source"]).read_text(encoding="utf-8")
check("U_names_match_existing_test_functions", all("def " + t["name"].split("[")[0] + "(" in test_text for c in controls["cases"].values() for t in c["tests"]))
check("U_evidence_R1_L9", [r["basis"] for r in matrix["u_table"]] == ["R"] + ["L"] * 9 and all(r["status"] == "pass" for r in matrix["u_table"]))
check("U_real_coverage1of10", matrix["tallies"]["update_delete"]["passed"] == 1 and matrix["tallies"]["update_delete"]["missing"] == 9)
check("no_release_claim_in_matrix", matrix["release_decision"] is False and matrix["not_a_release_decision"] is True and matrix["gate"]["decision"] == "unknown")

h2_dir = BASE / "p2-t207-h2-20261111-01-aborted"
check("H2_repository_only_3_aggregates", {p.name for p in h2_dir.iterdir()} == {"holdout_scorecard.json", "holdout_aggregate.json", "run_result.json"})
card, agg, h2_result = (read(h2_dir / n) for n in ("holdout_scorecard.json", "holdout_aggregate.json", "run_result.json"))
check("H2_original_counts", [card[k] for k in ("total", "executed", "passed", "failed", "errors")] == [30, 21, 11, 10, 9])
check("H2_started_scored_error_unstarted", agg["cases"] == {"executed": 22, "planned": 30, "with_error": 1} and 30 - agg["cases"]["executed"] == 8)
check("H2_by_stratum_sums", all(sum(v[k] for v in card["by_stratum"].values()) == card[k] for k in ("total", "passed", "failed", "errors")))
check("H2_security_unfinished", card["by_stratum"]["cross_doc_security"] == {"errors": 5, "failed": 0, "passed": 0, "total": 5})
check("H2_aborted_unapproved_unreleased", h2_result["status"] == "aborted" and card["thresholds_approved"] is False and card["threshold_met"] is False and card["release_ready"] is False)
check("H2_stop_reason", agg["failure"]["error_code"] == "MODEL_OUTPUT_INVALID" and agg["stop_code"] == h2_result["stop_code"] == "product_service_error")
missing = next(b["evidence"] for b in card["blocks"] if b["code"] == "holdout_document_code_unmapped")
check("H2_mapping_gap", missing == {"mapped": 8, "missing": ["V04", "V06"]})
check("H2_zero_hard_failure_is_only_raw_field", card["hard_failures"] == 0)
check("H2_no_added_diagnostics", "diagnostics" not in card)
restricted = {"case_id", "question", "reference_answer", "expected_values", "product_text", "answer_text", "turns_detail"}


def restricted_count(obj):
    if isinstance(obj, dict):
        return sum(k in restricted for k in obj) + sum(restricted_count(v) for v in obj.values())
    return sum(restricted_count(v) for v in obj) if isinstance(obj, list) else 0


check("H2_aggregates_restricted_keys_absent", sum(restricted_count(x) for x in (card, agg, h2_result)) == 0)
audit = read(BASE / "scoring/closeout/h2-artifact-audit.json")
backup_hashes = []
for item in audit["files"]:
    p = Path(item["preserved_path"]) if "preserved_path" in item else h2_dir / item["name"]
    check("H2_artifact_hash:" + item["name"], sha(p) == item["sha256"] and p.stat().st_size == item["bytes"])
    backup_hashes.append({"name": item["name"], "bytes": p.stat().st_size, "sha256": sha(p), "content_parsed": "preserved_path" not in item})

snapshot = dataclasses.asdict(read_ledger_snapshot())
check("fresh_ledger_snapshot_matches", snapshot == verification["ledger_snapshot"])
check("774_reserved_and_results", snapshot["reservation_count"] == snapshot["result_count"] == 774)
check("P2_and_project_accounting", abs(snapshot["p2_stage_accounted_cny"] - 6.784628) < 1e-9 and abs(snapshot["accounted_cny"] - 21.8555725) < 1e-9)
accounting = []
for tag in ("r1", "r2", "r3", "r4", "h2"):
    suffix = "-aborted" if tag == "h2" else ""
    r = read(BASE / f"p2-t207-{tag}-20261111-01{suffix}/run_result.json")
    check(tag + ":attempts_all_operations", r["attempts_scope"] == "all_attempts" and sum(r["attempts_by_operation"].values()) == r["attempts_reserved"])
    check(tag + ":answer_side_settlement", set(r["by_operation"]) == {"answer"} and abs(sum(r["by_center_cny"].values()) - r["settled_cny"]) < 1e-9)
    accounting.append({"run": tag.upper(), "reservations": r["attempts_reserved"], "chat_sends": r["requests_sent"], "all_operation_conservative_cny": str(sum((Decimal(str(v)) for v in r["attempts_by_center_cny"].values()), Decimal(0))), "answer_side_settled_cny": r["settled_cny"]})
check("T207227reservations63chat", sum(r["reservations"] for r in accounting) == 227 and sum(r["chat_sends"] for r in accounting) == 63)
check("T207_cost6_2132697", sum(Decimal(r["all_operation_conservative_cny"]) for r in accounting) == Decimal("6.2132697"))

rollback = read(ROOT / "docs/reports/OBS-EVAL/P2/T207-FIX-H2DIAG/evidence/verify-current/rollback-proof.json")
rollback_results = []
for item in rollback["restored_files"]:
    head_bytes = git("show", expected_head + ":" + item["path"])
    current = sha(ROOT / item["path"])
    check("rollback:" + item["path"], current == item["sha256"] == hashlib.sha256(head_bytes).hexdigest())
    rollback_results.append({"path": item["path"], "sha256": current, "equal_to_HEAD": True})
check("all_source_and_tests_no_diff", git("diff", "--", "backend/src", "backend/tests", "frontend/src", "frontend/tests") == b"")
check("runbook_withdrawn_diagnostics_promise", "诊断" not in (BASE / "PM/T207-runbook.md").read_text(encoding="utf-8"))
after = {p: sha(ROOT / p) for p in fixed}
check("fixed_files_unchanged_during_audit", after == before)
check("HEAD_unchanged", git("rev-parse", "HEAD").decode().strip() == head_before)
check("no_network_attempts", network_attempts == [])
result = {"schema_version": "independent-t207-closeout-audit/v1", "generated_utc": datetime.now(timezone.utc).isoformat(), "verdict": "limited_acceptance_truthful_closeout_only", "quality_pass": False, "p2_complete": False, "assertions_passed": len(checks), "checks": checks, "head": head_before, "public_counts": counts, "exact": {"pass": 24, "total": 24}, "ocr": {"pass": 7, "total": 8}, "remaining_public_failures": failures, "public_provenance": provenance, "u_controls": {"generated_utc": controls["generated_utc"], "fresh_rerun_claimed": False, "basis": "R1+L9"}, "h2": {"total": 30, "scored": 21, "passed": 11, "failed": 10, "errors_or_unfinished": 9, "started": 22, "one_started_error": 1, "unstarted": 8, "release_ready": False, "metadata_backup_read_as_content": False}, "h2_artifact_hashes": backup_hashes, "fixed_files_before": before, "fixed_files_after": after, "ledger_counts": {"reservations": 774, "results": 774, "p2_conservative_cny": 6.784628, "project_conservative_cny": 21.8555725}, "run_accounting": accounting, "rollback": rollback_results, "input_hashes": input_hashes, "new_network_attempts": len(network_attempts), "new_real_calls": 0, "no_product_execution": True}
(OUT / "audit-results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"verdict": result["verdict"], "assertions_passed": len(checks), "public_counts": counts, "h2_counts": result["h2"], "fixed_files_unchanged": after == before, "network_attempts": len(network_attempts)}, ensure_ascii=False))
