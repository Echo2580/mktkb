"""C1-P2 独立验收：覆盖率 / 形状遗漏 / 测试质量静态检查。"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
BACKEND = REPO / "backend"
TEST_FILE = BACKEND / "tests/evaluation/test_p2_empty_scope_proof.py"
OUT = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/independent/13-coverage.json"


def load():
    sys.path.insert(0, str(BACKEND / "src"))
    sys.path.insert(0, str(BACKEND / "tests"))
    spec = importlib.util.spec_from_file_location("c1p2_cov", TEST_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def events_of(case) -> list[dict]:
    capture = case.evidence.get("capture")
    rows = (capture.get("events") if isinstance(capture, dict) else None) or []
    return [row for row in rows if isinstance(row, dict) and "kind" in row]


def main() -> int:
    m = load()
    corpus = m._corpus()
    results = [m.prove_empty_use_scope(c.evidence) for c in corpus]
    shapes = Counter(r.shape for r in results)
    branches = Counter(r.branch for r in results)
    retrievals = Counter(r.retrieval for r in results)
    outcomes = Counter(r.outcome_class for r in results)

    event_kinds = Counter()
    retrieval_event_counts = Counter()
    context_message_counts = Counter()
    entity_inheritance_counts = Counter()
    query_state_event_counts = Counter()
    for case in corpus:
        events = events_of(case)
        event_kinds.update(str(e["kind"]) for e in events)
        retrieval_event_counts[sum(1 for e in events if e["kind"] == "retrieval_observed")] += 1
        context_message_counts[sum(1 for e in events if e["kind"] == "context_message")] += 1
        entity_inheritance_counts[sum(1 for e in events if e["kind"] == "entity_inheritance")] += 1
        query_state_event_counts[
            sum(
                1
                for e in events
                if e["kind"] in {"query_state_observed", "query_state_saved", "query_state_cleared"}
            )
        ] += 1

    required_shapes = {
        "无检索": [
            "legacy_model_answer_no_retrieval",
            "rag_direct_empty",
            "no_retrieval_positive_snapshot_legacy_no_model",
        ],
        "检索为空": ["legacy_no_model_retrieval_empty", "legacy_model_answer_retrieval_empty"],
        "检索有结果但未被使用": [
            "retrieval_candidates_unused_legacy_no_model",
            "retrieval_candidates_unused_legacy_model",
            "retrieval_candidates_unused_rag",
            "retrieval_candidates_unused_with_unresolved",
        ],
        "多轮中部分轮空": ["multi_turn_partial_empty", "context_history_no_usage", "query_state_candidates_unused"],
        "拒答/无事实分支（含仍有检索）": [
            "retrieval_candidates_unused_no_answer",
            "retrieval_candidates_unused_legacy_no_model",
            "factual_answer_kind",
        ],
        "带 clarification": [
            "clarification_template_base",
            "clarification_template_suffix",
            "retrieval_candidates_unused_clarification",
        ],
        "model_events 缺失": [
            "legacy_no_model_no_retrieval_no_marker",
            "model_input_without_output",
            "model_output_without_input",
        ],
    }
    required_rows = {
        label: {
            "cases": names,
            "present": all(any(c.name == n for c in corpus) for n in names),
            "all_cases": sorted(c.name for c in corpus if c.name in names),
        }
        for label, names in required_shapes.items()
    }

    usage_nonempty_cases = [c for c, r in zip(corpus, results) if r.usage_layers]
    context_cases = [c for c in corpus if any(e["kind"] == "context_message" for e in events_of(c))]
    missing_shapes = {
        "query_state_event_path": query_state_event_counts.get(0, 0) == len(corpus),
        "multiple_retrieval_events": max(retrieval_event_counts) <= 1,
        "multi_turn_with_current_usage": not any(
            c in context_cases and c in usage_nonempty_cases for c in corpus
        ),
        "rag_query_expansion_with_evidence": not any(
            e["kind"] == "model_input"
            and str(e["payload"].get("purpose")) == "query_expansion"
            and e["payload"].get("evidence")
            for c in corpus
            for e in events_of(c)
        ),
        "clarification_with_usage": not any(
            c in usage_nonempty_cases
            and any(
                e["kind"] == "commit_observed" and e["payload"].get("kind") == "clarification"
                for e in events_of(c)
            )
            for c in corpus
        ),
    }

    source = TEST_FILE.read_text(encoding="utf-8")
    static = {
        "skip_markers": sorted(
            set(re.findall(r"pytest\.mark\.skip|pytest\.skip|pytest\.mark\.xfail|pytest\.xfail", source))
        ),
        "assert_true_literals": source.count("assert True"),
        "parametrize_blocks": source.count("@pytest.mark.parametrize"),
        "differential_uses_frozen": "from mktkb.evaluation.p2_hard_evidence import _empty_use_scope_proof" in source,
        "frozen_sha_asserted": "assert _sha256_file(FROZEN_MODULE) == FROZEN_SHA" in source,
        "exact_extension_count_asserted": 'summary["extension_proven"] == 11' in source,
        "loose_extension_count_assertion": 'summary["extension_proven"] > 0' in source,
        "uncoded_asserted_empty": "assert uncoded == []" in source,
    }

    gap_labels = sorted(
        s
        for s in shapes
        if s
        in {
            "branch_evidence_missing",
            "branch_evidence_inconsistent",
            "evidence_incomplete",
            "unknown_usage_field",
            "template_identity_unverified",
            "model_events_missing",
            "internal_error",
        }
    )
    combos = sorted(s for s in shapes if s not in gap_labels)

    payload = {
        "schema_version": "c1p2-independent-coverage/v0.1",
        "corpus_size": len(corpus),
        "proven": sum(r.proven for r in results),
        "not_proven": sum(not r.proven for r in results),
        "distinct_shapes": len(shapes),
        "shape_counts": dict(shapes),
        "combo_shape_count": len(combos),
        "gap_shape_count": len(gap_labels),
        "gap_labels": gap_labels,
        "branches": dict(branches),
        "retrievals": dict(retrievals),
        "outcome_classes": dict(outcomes),
        "event_kinds": dict(event_kinds),
        "retrieval_event_counts": {str(k): v for k, v in sorted(retrieval_event_counts.items())},
        "context_message_counts": {str(k): v for k, v in sorted(context_message_counts.items())},
        "entity_inheritance_counts": {str(k): v for k, v in sorted(entity_inheritance_counts.items())},
        "query_state_event_counts": {str(k): v for k, v in sorted(query_state_event_counts.items())},
        "required_shapes": required_rows,
        "missing_or_weak_shapes": missing_shapes,
        "test_static": static,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
