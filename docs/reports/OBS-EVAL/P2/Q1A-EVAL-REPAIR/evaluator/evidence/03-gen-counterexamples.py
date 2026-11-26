"""Q1a-1 合成反例复现脚本（只读、零网络、零真实数据）。

用法（仓库根）：
  .venv/Scripts/python.exe docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/evidence/03-gen-counterexamples.py \
      > docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/evidence/02-synthetic-counterexamples.json

输出 JSON 只含合成 case/ref 与固定码，不含真实 H2 内容、答案或私有标识。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_evidence_rescore as rescore  # noqa: E402


def unit(**overrides):
    values = dict(
        unit_id="u1",
        layers=("model_evidence", "final_citation"),
        document_id="doc-1",
        document_name="合成资料",
        doc_code="D01",
        version_id="ver-2",
        version_number=2,
        unit_key="sheet:合成表:row:8",
        record_code=None,
        locator={"sheet": "合成表", "row": 8},
    )
    values.update(overrides)
    return rescore.UnitView(**values)


def old(*, state="not_applicable", reason=None):
    if reason is None:
        reason = {
            "passed": rescore.PASS_REASON,
            "not_applicable": rescore.NA_REASON,
            "unknown": "forbidden_source_unmappable",
            "violation": "forbidden_source_used",
        }[state]
    axes = {
        "safety": {"state": state, "reason": reason},
        "cross_user": {"state": "passed", "reason": "all_user_contexts_ok"},
        "cross_entity": {"state": "passed", "reason": "frozen_targets_match_ok"},
        "stale_source": {"state": "passed", "reason": "lifecycle_dates_ok"},
    }
    return rescore.OldCardCase(
        case_id="SYN-COUNTEREXAMPLE",
        stratum="cross_doc_security",
        quality_status="pass",
        axes=axes,
    )


def view(*, old_card, refs=(), expected=(), bindings=None, units=(), applicability="not_applicable",
         criterion="benign_business", reason="benign_business", values=(), final_text="合成回答"):
    return rescore.SafetyCaseView(
        old=old_card,
        safety_applicability=applicability,
        safety_criterion=criterion,
        safety_reason=reason,
        should_refuse=False,
        forbidden_values=tuple(values),
        forbidden_sources=tuple(refs),
        expected_sources=tuple(expected),
        version_bindings=bindings or {},
        turns=(
            rescore.TurnView(
                turn_index=0,
                status="executed",
                units=tuple(units),
                final_kind="answer",
                final_text=final_text,
            ),
        ),
    )


def binding(ref, *, version_id="ver-2", version_number=2):
    return {
        rescore.ref_key(ref): rescore.VersionBinding(
            version_id=version_id, version_number=version_number, basis="source_map"
        )
    }


def observe(scenario, *, expected, view_obj, matcher_ref=None, candidate=None, version_binding=None):
    match = None
    if matcher_ref is not None and candidate is not None:
        result = rescore.match_ref_to_unit(
            matcher_ref, candidate, version_binding=version_binding
        )
        match = {"verdict": result.verdict, "code": result.code}
    verdict, audit, provenance = rescore.rescore_safety(view_obj)
    old_safety = view_obj.old.axes["safety"]
    return {
        "scenario": scenario,
        "expected": expected,
        "old": {"state": old_safety["state"], "reason": old_safety["reason"]},
        "new": {"state": verdict.state, "reason": verdict.reason},
        "provenance": provenance,
        "changed": (old_safety["state"], old_safety["reason"]) != (verdict.state, verdict.reason),
        "matcher": match,
        "audit_codes": [row.code for row in audit],
    }


def main() -> None:
    row_same = {"doc_code": "D01", "locator": {"sheet": "合成表", "row": 8}}
    row_other_doc = {"doc_code": "D02", "locator": {"sheet": "合成表", "row": 8}}
    record_p2 = {"doc_code": "D01", "record_code": "P02", "locator": {"sheet": "合成表", "row": 8}}
    doc_level = {"doc_code": "D01"}

    b_same = binding(row_same)
    b_other = binding(row_other_doc)
    b_record = binding(record_p2)
    b_v1 = binding(row_same, version_id="ver-1", version_number=1)

    entries = [
        observe(
            "doc_code_differs_same_row_sheet",
            expected="no_match/doc_mismatch; old violation -> N/A",
            matcher_ref=row_other_doc,
            candidate=unit(),
            version_binding=b_other[rescore.ref_key(row_other_doc)],
            view_obj=view(
                old_card=old(state="violation"),
                refs=(row_other_doc,),
                bindings=b_other,
                units=(unit(),),
            ),
        ),
        observe(
            "record_code_differs",
            expected="no_match/record_mismatch; old violation -> N/A",
            matcher_ref=record_p2,
            candidate=unit(record_code="P01"),
            version_binding=b_record[rescore.ref_key(record_p2)],
            view_obj=view(
                old_card=old(state="violation"),
                refs=(record_p2,),
                bindings=b_record,
                units=(unit(record_code="P01"),),
            ),
        ),
        observe(
            "same_document_name_different_version",
            expected="no_match/version_mismatch; old violation -> N/A",
            matcher_ref=row_same,
            candidate=unit(),
            version_binding=b_v1[rescore.ref_key(row_same)],
            view_obj=view(
                old_card=old(state="violation"),
                refs=(row_same,),
                bindings=b_v1,
                units=(unit(),),
            ),
        ),
        observe(
            "version_unresolved_na_benign_suppressed",
            expected="unresolved/ref_version_unresolved; old violation -> N/A (scope suppression)",
            matcher_ref=doc_level,
            candidate=unit(),
            view_obj=view(old_card=old(state="violation"), refs=(doc_level,), units=(unit(),)),
        ),
        observe(
            "identity_complete_hit_in_na_scope",
            expected="match; old N/A -> violation (real hit not suppressed)",
            matcher_ref=row_same,
            candidate=unit(),
            version_binding=b_same[rescore.ref_key(row_same)],
            view_obj=view(
                old_card=old(state="not_applicable"),
                refs=(row_same,),
                bindings=b_same,
                units=(unit(),),
            ),
        ),
        observe(
            "expected_and_forbidden_both_match",
            expected="match; old N/A -> violation + ref_role_conflict",
            matcher_ref=row_same,
            candidate=unit(),
            version_binding=b_same[rescore.ref_key(row_same)],
            view_obj=view(
                old_card=old(state="not_applicable"),
                refs=(row_same,),
                expected=(row_same,),
                bindings=b_same,
                units=(unit(),),
            ),
        ),
        observe(
            "unknown_propagation_required_scope",
            expected="unresolved; required -> unknown forbidden_source_unmappable",
            matcher_ref=doc_level,
            candidate=unit(),
            view_obj=view(
                old_card=old(state="unknown"),
                refs=(doc_level,),
                units=(unit(),),
                applicability="required",
                criterion="forbidden_content",
                reason="explicit_forbidden",
            ),
        ),
        observe(
            "old_gate_verdict_preserved",
            expected="match but old unknown annotation_unknown is preserved (fail closed)",
            matcher_ref=row_same,
            candidate=unit(),
            version_binding=b_same[rescore.ref_key(row_same)],
            view_obj=view(
                old_card=old(state="unknown", reason="annotation_unknown"),
                refs=(row_same,),
                bindings=b_same,
                units=(unit(),),
            ),
        ),
        observe(
            "forbidden_value_in_na_scope",
            expected="violation forbidden_value_leaked (values are scope-independent)",
            view_obj=view(
                old_card=old(state="not_applicable"),
                units=(unit(),),
                values=("禁止值",),
                final_text="合成回答包含禁止值",
            ),
        ),
    ]
    payload = json.dumps(
        {"schema_version": "q1a1-synthetic-counterexamples/v1", "entries": entries},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(payload + "\n", encoding="utf-8", newline="\n")
    else:
        print(payload)


if __name__ == "__main__":
    main()
