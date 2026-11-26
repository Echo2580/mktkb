"""C26-only frozen initial classifier; actual execution requires B review."""
import ast
import hashlib
import importlib.util
import json
import pathlib
import sys
sys.dont_write_bytecode = True

REPO = pathlib.Path(__file__).resolve().parents[7]
FULL = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/work/recompute_axes_fullverify.py"
SAFE = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/evidence/recompute-v2.json"
GUARD = REPO / "docs/reports/OBS-EVAL/P2/H2V3/t207-repair-20261115/custody-a/safe_case_v10.py"
LEDGER = REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
BUDGET = REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
OUTPUT = pathlib.Path(__file__).parent / "SAFE-C26-CURRENT.json"
FULL_SHA = "8952a5ce4fc2a804d6b91aa8199f5478fa3ca0223e8dc5c4c4206d15e5455d2e"
SAFE_SHA = "04e1f3df307f5c4036dcf77a992d1065d045177924827e1da206307f3c99c114"
LEDGER_SHA = "e564106329ece3cf0d3a0158cbfd321dbfc0a24f1b05b7829c01a7acced6b656"
BUDGET_SHA = "79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e"
RUN = "p2-h2v3-20261115-r0-base_b0"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def snapshot():
    files = list((REPO / "backend/src/mktkb").rglob("*.py"))
    files += [REPO / "tools/p2_h2_controlled_execute.py", REPO / "tools/p2_h2_v3_controlled_execute.py", FULL, GUARD]
    rows = [(p.relative_to(REPO).as_posix(), sha(p)) for p in sorted(set(files)) if "__pycache__" not in p.parts]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def original_private_path(source, assigned_name, line):
    """Extract the existing entry's literal from source; never emit the value."""
    tree = ast.parse(source)
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and n.lineno == line and any(isinstance(t, ast.Name) and t.id == assigned_name for t in n.targets)]
    if len(matches) != 1:
        raise ValueError("source_layout_mismatch")
    calls = [n for n in ast.walk(matches[0].value) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "pathlib" and n.func.attr == "Path" and len(n.args) == 1 and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)]
    if len(calls) != 1:
        raise ValueError("source_layout_mismatch")
    return pathlib.Path(calls[0].args[0].value)

def result_projection(result, criterion, hard):
    axis = result.axis("safety")
    allowed_states = {"passed", "violation", "unknown", "not_applicable"}
    reasons = set(hard.UNKNOWN_REASONS_BY_AXIS["safety"]) | set(hard.VIOLATION_REASONS_BY_AXIS["safety"]) | {hard.PASS_REASONS["safety"], hard.NA_REASONS["safety"]}
    if axis.state not in allowed_states or axis.reason not in reasons:
        raise ValueError("classifier_output_invalid")
    return {"state": axis.state, "reason": axis.reason, "criterion": criterion,
            "evidence_complete": bool(result.evidence_complete), "planned_turns": result.planned_turns,
            "executed_turns": result.executed_turns, "replayed_turns": result.replayed_turns}

def classify_current():
    before = snapshot()
    if before != snapshot() or sha(FULL) != FULL_SHA or sha(SAFE) != SAFE_SHA:
        raise ValueError("dependency_changed")
    if sha(LEDGER) != LEDGER_SHA or sha(BUDGET) != BUDGET_SHA or OUTPUT.exists():
        raise ValueError("protection_or_output_mismatch")
    source = FULL.read_text(encoding="utf-8")
    key_path = original_private_path(source, "key", 793)
    binding_dir = original_private_path(source, "binding", 802)
    full = load("c26_current_full", FULL)
    entry, hard = full.ENTRY, full.hard
    binding_name, run_index = full.SCENARIOS[0]
    if run_index != 0:
        raise ValueError("scenario_mismatch")
    binding = entry.v2._read_json_mapping(binding_dir / binding_name, "binding_invalid")
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    bundle = entry.load_v3_bundle(inputs)
    run = binding["runs"][0]
    if run["run_id"] != RUN or run["run_index"] != 0:
        raise ValueError("run_mismatch")
    cases = bundle.contract.subset(str(run["scenario_id"])).cases
    plan_raw = entry.v2._read_json_mapping(full.WORK / full.RUN_DIR_NAMES[0] / "out" / "controlled" / "case-plan.json", "case_plan_invalid")
    static = {name: value for name, value in dict(run["evidence_bindings"]).items() if name != "index_revision"}
    plan = entry.v2._validate_case_plan_document(plan_raw, cases=cases, static_bindings=static)
    if plan["run_id"] != RUN or plan["bindings"].get("run_id") != RUN:
        raise ValueError("plan_run_mismatch")
    receipt = entry.v2._read_json_mapping(full.WORK / full.RUN_DIR_NAMES[0] / "seal" / RUN / "run-receipt.json", "receipt_invalid")
    if str(receipt["business_date"]) != str(plan_raw.get("run_binding", {}).get("business_date")) or str(receipt["business_date"]) != "2026-10-15":
        raise ValueError("date_mismatch")
    public_receipt = entry.v2._read_json_mapping(REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r0-final/run-receipt.json", "public_receipt_invalid")
    tree_hash = entry.v2.tree_digest(full.WORK / full.RUN_DIR_NAMES[0] / "evidence")["tree_sha256"]
    if receipt.get("run_id") != RUN or public_receipt.get("run_id") != RUN or receipt.get("seal", {}).get("evidence_tree_sha256") != tree_hash or public_receipt.get("seal", {}).get("evidence_tree_sha256") != tree_hash:
        raise ValueError("evidence_tree_mismatch")
    matches = [(case, row) for case, row in zip(cases, plan["cases"]) if case.case_id == "H2V3-C26" and row["case_id"] == "H2V3-C26"]
    if len(matches) != 1:
        raise ValueError("case_mismatch")
    case, row = matches[0]
    key = key_path.read_bytes().strip()
    evidence_dir = full.WORK / full.RUN_DIR_NAMES[0] / "evidence" / RUN
    turns = []
    for turn in row["turns"]:
        envelope = None
        if turn["status"] == "executed":
            envelope = full.read_encrypted_evidence(evidence_dir / str(turn["evidence_file"]), key=key, expected_bindings=dict(plan["bindings"]))
            if envelope.get("turn", {}).get("turn_index") != turn["turn_index"]:
                raise ValueError("turn_mismatch")
        turns.append({"turn_index": turn["turn_index"], "status": turn["status"], "error": turn.get("error"), "evidence": envelope})
    audit = {"quality_status": row["quality_status"], "turns": turns}
    axes, _ = hard.annotation_for_case(bundle.annotation, case)
    criterion = axes["safety"]["criterion"]
    if criterion not in {"must_refuse_security", "forbidden_content", "benign_business", "unknown"}:
        raise ValueError("criterion_invalid")
    result = hard.classify_case_evidence(case, bundle.annotation, audit)
    projected = result_projection(result, criterion, hard)
    projected.update({"case_id": "H2V3-C26", "run_id": RUN, "run_index": 0,
                      "classifier": "frozen_initial", "source_matcher": "frozen_locator",
                      "current_source_sha256": SAFE_SHA, "evidence_tree_sha256": tree_hash, "dependency_snapshot_sha256": before,
                      "final_kind": "unknown", "security_copy_equal": "unknown", "forbidden_value_hit": "unknown",
                      "forbidden_source_hit": "unknown", "classifier_same_as_commit_event": "unknown"})
    if len(turns) == 1 and turns[0]["status"] == "executed":
        env = turns[0]["evidence"]
        events = hard._events(env)
        final = hard._final_outcome(events)
        commits = hard._payloads(events, "commit_observed")
        if isinstance(final, dict) or hasattr(final, "get"):
            kind = final.get("kind")
            if kind in {"answer", "not_found", "no_answer", "refusal", "clarification", "conflict", "ambiguous", "error", "knowledge_changed"}:
                projected["final_kind"] = kind
            if len(commits) == 1:
                projected["classifier_same_as_commit_event"] = final is commits[0]
            text = final.get("text")
            if isinstance(text, str):
                from mktkb import copy as copy_module
                projected["security_copy_equal"] = text == copy_module.text("SECURITY_RESTRICTED_CONTACT")
                if isinstance(case.forbidden_values, tuple) and all(isinstance(x, str) for x in case.forbidden_values):
                    projected["forbidden_value_hit"] = any(value and str(value) in text for value in case.forbidden_values)
        # A positive frozen violation is explicit; absence is not claimed when
        # the source set could be unmappable or completeness is uncertain.
        acc = hard._AxisAccumulator("safety", "turn")
        hard._check_safety(case, axes["safety"], env, acc)
        if any(reason == "forbidden_source_used" for reason, _ in acc.violations):
            projected["forbidden_source_hit"] = True
        projected["evidence_status"] = "complete" if env.get("completeness", {}).get("status") == "complete" else "unknown"
        for label, fn in (("structural_closure", hard._structural_closure_violation), ("integrity", hard._turn_integrity_violation)):
            code = fn(env)
            projected[label] = code if code in hard.UNKNOWN_REASONS_BY_AXIS["safety"] else ("none" if code is None else "unknown")
        branch = hard._turn_branch_matrix_violation(env)
        projected["branch_matrix"] = branch[0] if branch and branch[0] in hard.UNKNOWN_REASONS_BY_AXIS["safety"] else ("none" if branch is None else "unknown")
    if snapshot() != before or sha(LEDGER) != LEDGER_SHA or sha(BUDGET) != BUDGET_SHA or sha(SAFE) != SAFE_SHA:
        raise ValueError("dependency_or_protection_changed")
    with OUTPUT.open("x", encoding="utf-8") as stream:
        json.dump(projected, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

def main():
    guard = load("c26_guard", GUARD)
    if sys.argv[1:] != ["--execute-after-b-review"]:
        print('{"status":"blocked","code":"review_required"}')
        return 2
    try:
        with guard.suppress_output():
            guard.positive_controls()
            classify_current()
        print('{"status":"safe_projection_written"}')
        return 0
    except BaseException:
        print('{"status":"blocked","code":"controlled_diagnostic_failed"}')
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
