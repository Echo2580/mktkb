"""C1-P2 独立验收：72 例差分复算 + 12 分歧结构归因 + 敏感性探针。

不读真实 H2 数据；只使用测试模块自建合成 envelope。
冻结原语以只读 import 作对照（前后 SHA 必须为 fba6e606...）。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

REPO = Path(r"D:\GPT项目\市场部AI知识库")
BACKEND = REPO / "backend"
TEST_FILE = BACKEND / "tests/evaluation/test_p2_empty_scope_proof.py"
FROZEN = BACKEND / "src/mktkb/evaluation/p2_hard_evidence.py"
FROZEN_SHA = "fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b"
OUT = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/independent/11-divergences.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_test_module():
    sys.path.insert(0, str(BACKEND / "src"))
    sys.path.insert(0, str(BACKEND / "tests"))
    spec = importlib.util.spec_from_file_location("c1p2_test_mod", TEST_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def payloads(evidence: Mapping[str, Any], kind: str) -> list[Mapping[str, Any]]:
    capture = evidence.get("capture")
    rows = capture.get("events") if isinstance(capture, Mapping) else None
    out = []
    for row in rows or ():
        if isinstance(row, Mapping) and str(row.get("kind")) == kind:
            payload = row.get("payload")
            if isinstance(payload, Mapping):
                out.append(payload)
    return out


def structural_facts(evidence: Mapping[str, Any]) -> dict[str, Any]:
    projection = evidence.get("db_projection")
    projection = projection if isinstance(projection, Mapping) else {}
    plan_rows = payloads(evidence, "plan_observed")
    plan_path = str(plan_rows[0].get("path")) if len(plan_rows) == 1 else "?"
    retrieval = payloads(evidence, "retrieval_observed")
    retrieval_ids = [uid for p in retrieval for uid in (p.get("unit_ids") or [])]
    qs_events = []
    for kind in ("query_state_observed", "query_state_saved", "query_state_cleared"):
        for p in payloads(evidence, kind):
            state = p.get("state_json") if isinstance(p.get("state_json"), Mapping) else {}
            qs_events.extend(state.get("candidates") or [])
    qs_projection = []
    for row in projection.get("query_states") or ():
        if isinstance(row, Mapping) and isinstance(row.get("state_json"), Mapping):
            qs_projection.extend(row["state_json"].get("candidates") or [])
    model_inputs = payloads(evidence, "model_input")
    model_outputs = payloads(evidence, "model_output")
    model_evidence = [
        item.get("source_id")
        for p in model_inputs
        for item in (p.get("evidence") or ())
        if isinstance(item, Mapping)
    ]
    model_out_ids = [v for p in model_outputs for v in (p.get("source_ids") or [])]
    answer_ids = [v for p in payloads(evidence, "answer_result") for v in (p.get("source_ids") or [])]
    commit_ids = [v for p in payloads(evidence, "commit_observed") for v in (p.get("source_ids") or [])]
    facts = [f for p in payloads(evidence, "direct_rag_answer") for f in (p.get("facts") or [])]
    direct_rag_source_ids = [f.get("source_unit_id") for f in facts if isinstance(f, Mapping)]
    direct_rag_citations = [
        v for p in payloads(evidence, "direct_rag_answer") for v in (p.get("cited_unit_ids") or [])
    ]
    inheritance_ids = [p.get("source_unit_id") for p in payloads(evidence, "entity_inheritance")]
    message_sources = [row.get("source_id") for row in (projection.get("message_sources") or ())]
    snapshot = evidence.get("runtime_snapshot")
    marker = None
    if isinstance(snapshot, Mapping):
        usage = snapshot.get("retrieval_use")
        if isinstance(usage, Mapping):
            marker = {
                "schema_version": snapshot.get("schema_version"),
                "availability": usage.get("availability"),
                "reason": usage.get("reason"),
                "candidate_observation": usage.get("candidate_observation"),
                "candidates": usage.get("candidates"),
            }
    usage_nonempty = {
        "model_evidence": [v for v in model_evidence if v],
        "model_output_sources": [v for v in model_out_ids if v],
        "direct_rag_facts": [v for v in direct_rag_source_ids if v],
        "direct_rag_citations": [v for v in direct_rag_citations if v],
        "answer_sources": [v for v in answer_ids if v],
        "commit_sources": [v for v in commit_ids if v],
        "entity_inheritance": [v for v in inheritance_ids if v],
        "message_sources": [v for v in message_sources if v],
    }
    usage_nonempty = {k: v for k, v in usage_nonempty.items() if v}
    # 适用且必须显式为空的使用容器（按分支矩阵）
    applicable_empty: dict[str, Any] = {
        "answer_result.source_ids": answer_ids,
        "commit_observed.source_ids": commit_ids,
        "projection.message_sources": message_sources,
    }
    if plan_path == "rag":
        applicable_empty["direct_rag_answer.facts"] = direct_rag_source_ids
        applicable_empty["direct_rag_answer.cited_unit_ids"] = direct_rag_citations
    if model_inputs or model_outputs:
        applicable_empty["model_input.evidence"] = model_evidence
        applicable_empty["model_output.source_ids"] = model_out_ids
    explicit_empty = {k: (v == [] or v == ()) for k, v in applicable_empty.items()}
    return {
        "plan_path": plan_path,
        "retrieval_event_count": len(retrieval),
        "retrieval_unit_ids": retrieval_ids,
        "query_state_event_candidates": qs_events,
        "query_state_projection_candidates": qs_projection,
        "usage_nonempty": usage_nonempty,
        "applicable_usage_containers": {k: list(v) for k, v in applicable_empty.items()},
        "applicable_usage_explicit_empty": explicit_empty,
        "all_applicable_usage_explicit_empty": all(explicit_empty.values()) and not usage_nonempty,
        "positive_no_retrieval_marker": marker,
        "projection_units": [row.get("unit_id") for row in (projection.get("units") or ()) if isinstance(row, Mapping)],
        "projection_unresolved": [
            row.get("unit_id") for row in (projection.get("unresolved_unit_ids") or ()) if isinstance(row, Mapping)
        ],
    }


def expected_class(facts: Mapping[str, Any]) -> str:
    if facts["usage_nonempty"]:
        return "stricter_entity_inheritance"
    if facts["retrieval_unit_ids"]:
        return "retrieval_candidates_are_usage_only_in_frozen"
    if facts["query_state_event_candidates"] or facts["query_state_projection_candidates"]:
        return "query_state_candidates_are_usage_only_in_frozen"
    if facts["retrieval_event_count"] == 0 and facts["positive_no_retrieval_marker"]:
        return "no_retrieval_marker_only_in_new"
    return "no_divergence"


def main() -> int:
    before = sha256_file(FROZEN)
    assert before == FROZEN_SHA, before
    mod = load_test_module()
    corpus = mod._corpus()
    rows = []
    summary = {
        "total": len(corpus),
        "ours_proven": 0,
        "frozen_proven": 0,
        "equal_proven": 0,
        "equal_not_proven": 0,
        "extension_proven": 0,
        "stricter_not_proven": 0,
        "uncoded": [],
    }
    by_class: dict[str, int] = {}
    for case in corpus:
        ours = mod.prove_empty_use_scope(case.evidence)
        frozen_proven, frozen_reason = mod._empty_use_scope_proof(case.evidence)
        facts = structural_facts(case.evidence)
        if ours.proven != case.expect_proven:
            summary["uncoded"].append({"case": case.name, "why": "ours_vs_declared_expectation"})
        if ours.proven:
            summary["ours_proven"] += 1
        if frozen_proven:
            summary["frozen_proven"] += 1
        if ours.proven == frozen_proven:
            verdict = "equal_proven" if ours.proven else "equal_not_proven"
        elif ours.proven:
            verdict = "extension_proven"
        else:
            verdict = "stricter_not_proven"
        summary[verdict] += 1
        cls = expected_class(facts)
        if verdict == "extension_proven":
            by_class[cls] = by_class.get(cls, 0) + 1
        if verdict == "stricter_not_proven":
            by_class[cls] = by_class.get(cls, 0) + 1
        rows.append(
            {
                "case": case.name,
                "declared_divergence": case.divergence,
                "declared_stricter": case.stricter,
                "ours": ours.as_dict(),
                "frozen": {"proven": frozen_proven, "reason": frozen_reason},
                "verdict": verdict,
                "structural_class": cls,
                "facts": facts,
                "consistency": {
                    "declared_matches_structural": (
                        (verdict == "extension_proven" and case.divergence is not None)
                        or (verdict == "stricter_not_proven" and case.stricter is True)
                        or (verdict == "equal_proven" and case.divergence is None)
                        or (verdict == "equal_not_proven" and case.divergence is None)
                    ),
                    "extension_has_explicit_empty_usage": (
                        facts["all_applicable_usage_explicit_empty"] if verdict == "extension_proven" else None
                    ),
                    "extension_has_candidate_layer": (
                        bool(facts["retrieval_unit_ids"] or facts["query_state_event_candidates"] or facts["query_state_projection_candidates"])
                        if verdict == "extension_proven"
                        else None
                    ),
                },
            }
        )
    after = sha256_file(FROZEN)
    payload = {
        "schema_version": "c1p2-independent-divergences/v0.1",
        "frozen_sha_before": before,
        "frozen_sha_after": after,
        "frozen_unchanged": before == after == FROZEN_SHA,
        "summary": summary,
        "divergence_classes": by_class,
        "rows": rows,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "rows"}, ensure_ascii=False, indent=1))
    print("divergence rows:")
    for row in rows:
        if row["verdict"] in {"extension_proven", "stricter_not_proven"}:
            print(
                row["verdict"],
                row["case"],
                "declared=", row["declared_divergence"],
                "structural=", row["structural_class"],
                "ours=", row["ours"]["proven"], row["ours"]["shape"], row["ours"]["detail"],
                "frozen=", row["frozen"],
                "explicit_empty=", row["consistency"]["extension_has_explicit_empty_usage"],
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
