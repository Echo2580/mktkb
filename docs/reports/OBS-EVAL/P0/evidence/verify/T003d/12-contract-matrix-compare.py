"""Reviewer probe: compare T003d contracts against the T003c baseline (776497f).

Checks:
1. default `required_spans(path, outcome)` (no reason) is byte-for-byte equivalent to
   the frozen T001 table for every path/outcome combination;
2. `validate_required_spans` (no reason field) is equivalent to the old implementation;
3. the T003d `reason` parameter is additive only (the documented exceptions).

Run from an arbitrary directory; both modules are loaded by file path.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path

TEMP = Path(__file__).resolve().parent
OLD_PATH = TEMP / "old_contracts.py"
NEW_PATH = Path(sys.argv[1])


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


old = load(OLD_PATH, "old_contracts_776497f")
new = load(NEW_PATH, "new_contracts_b811f9f")

failures = 0
rows = 0
print("== 1) default required_spans matrix (path x outcome) ==")
for path, outcome in itertools.product(old.TracePath, old.OutcomeKind):
    old_value = old_error = new_value = new_error = None
    try:
        old_value = sorted(old.required_spans(path, outcome))
    except Exception as exc:  # noqa: BLE001 - probe
        old_error = type(exc).__name__
    try:
        new_value = sorted(new.required_spans(path, outcome))
    except Exception as exc:  # noqa: BLE001 - probe
        new_error = type(exc).__name__
    rows += 1
    # T003d intentionally adds legacy conflict / knowledge_changed rows.
    intentional_new_row = (path is not old.TracePath.RAG) and outcome.value in {
        "conflict",
        "knowledge_changed",
    }
    same = old_value == new_value and old_error == new_error
    if not same and not intentional_new_row:
        failures += 1
        print("  MISMATCH", path.value, outcome.value, old_value, old_error, "->", new_value, new_error)
print(f"  rows={rows} unexpected_mismatches={failures}")
print("  intentional new legacy rows:", sorted(
    f"{p.value}+{o.value}"
    for p in (old.TracePath.LEGACY, old.TracePath.LEGACY_WITH_RAG_CANDIDATES)
    for o in (old.OutcomeKind.CONFLICT, old.OutcomeKind.KNOWLEDGE_CHANGED)
    if old.OutcomeKind(o.value) not in old._LEGACY_REQUIRED_SPANS
))

print("== 2) validate_required_spans without reason: old vs new ==")
validate_failures = 0
for path, outcome in itertools.product(old.TracePath, old.OutcomeKind):
    try:
        required = old.required_spans(path, outcome)
    except ValueError:
        continue
    names = sorted(required)
    old_record = old.TraceRecord(path=path.value, outcome_kind=outcome.value)
    new_record = new.TraceRecord(path=path.value, outcome_kind=outcome.value)
    old_result = old.validate_required_spans(old_record, names)
    new_result = new.validate_required_spans(new_record, names)
    if old_result != new_result:
        validate_failures += 1
        print("  MISMATCH", path.value, outcome.value, old_result, new_result)
print(f"  unexpected_mismatches={validate_failures}")

print("== 3) reason-aware exceptions (documented T003d deltas) ==")
for reason in ("DOCUMENT_NOT_FOUND", "UNKNOWN_STORE", "RECORD_ONLY"):
    got = sorted(new.required_spans("rag", "no_answer", reason=reason))
    print(f"  rag+no_answer reason={reason}: {got}")
for reason in ("UNKNOWN_IDENTIFIER", "IDENTIFIER_NOT_RETRIEVABLE", "NO_INTENT", "UNRECORDED_FIELD"):
    for path in ("legacy", "legacy_with_rag_candidates"):
        got = sorted(new.required_spans(path, "not_found", reason=reason))
        print(f"  {path}+not_found reason={reason}: {got}")
print("  rag+no_answer reason=NO_EVIDENCE:", sorted(new.required_spans("rag", "no_answer", reason="NO_EVIDENCE")))
print("  default rag+no_answer:", sorted(new.required_spans("rag", "no_answer")))
print("  default legacy+not_found:", sorted(new.required_spans("legacy", "not_found")))

total = failures + validate_failures
print("RESULT:", "PASS" if total == 0 else f"FAIL({total})")
raise SystemExit(0 if total == 0 else 1)
