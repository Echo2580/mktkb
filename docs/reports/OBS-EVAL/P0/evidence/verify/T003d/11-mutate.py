"""Apply one intentional mutation to the isolated copy (reviewer probe only).

Usage: python mutate.py <copy_root> <mutation-id>
Each mutation must match exactly once; a no-op means the probe is invalid.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
MUTATION = sys.argv[2]

CONTRACTS = ROOT / "backend/src/mktkb/observability/contracts.py"
CONVERSATIONS = ROOT / "backend/src/mktkb/conversations/service.py"
QA = ROOT / "backend/src/mktkb/qa/service.py"

MUTATIONS = {
    # 1) validate_required_spans forgets record.reason (T003d reason-aware contract).
    "m1_validate_ignores_reason": (
        CONTRACTS,
        "required = set(required_spans(path, outcome, reason=record.reason))",
        "required = set(required_spans(path, outcome))",
    ),
    # 2) early not_found no longer writes the stable reason into Trace.
    "m2_drop_early_reason": (
        CONVERSATIONS,
        '            reason="UNRECORDED_FIELD",\n',
        "",
    ),
    # 3) legacy conflict / knowledge_changed supplement rows removed.
    "m3_drop_supplement_rows": (
        CONTRACTS,
        '    OutcomeKind.CONFLICT: frozenset({"intent_parse", "retrieve", "commit"}),\n'
        '    OutcomeKind.KNOWLEDGE_CHANGED: frozenset({"intent_parse", "retrieve", "commit"}),\n',
        "",
    ),
    # 4) QaEngine.sync never creates index_sync Span / flag.
    "m4_no_index_sync": (
        QA,
        '        trace_attrs.annotate_trace(index_sync_performed=True)\n'
        '        with trace_attrs.span("index_sync"):\n',
        "        if True:\n",
    ),
    # 5) legacy outcome writer drops reason for every result.
    "m5_outcome_writer_drops_reason": (
        CONVERSATIONS,
        "    trace.set_outcome(outcome, reason)",
        "    trace.set_outcome(outcome)",
    ),
}


def main() -> int:
    path, old, new = MUTATIONS[MUTATION]
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        print(f"INVALID mutation {MUTATION}: expected 1 match, found {count} in {path}")
        return 2
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"APPLIED {MUTATION} to {path.name}")
    return 0


raise SystemExit(main())
