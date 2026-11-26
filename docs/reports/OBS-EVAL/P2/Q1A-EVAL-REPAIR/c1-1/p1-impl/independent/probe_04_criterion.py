"""Criterion conformance probe for `p2-stale-source-criterion/v1`.

Independent of the developer test suite: builds its own K*/S_syn fixture from
synth_stale.py, asserts exact fixed codes (equality, never membership-only),
walks §7's 14 rows, F-1..F-12, the four ambiguity routes, folding, N/A
unreachability, output prohibition, and count identities.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
OUT = Path(__file__).resolve().parent / "out"
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_stale_version_state as stale  # noqa: E402

import synth_stale as S  # noqa: E402

CHECKS: list[dict[str, Any]] = []


def check(name: str, condition: bool, detail: Any = None) -> None:
    CHECKS.append({"name": name, "pass": bool(condition), "detail": detail})


def eq(name: str, actual: Any, expected: Any) -> None:
    check(name, actual == expected, {"actual": actual, "expected": expected})


def determine(grounding: dict[str, Any], evidence: dict[str, Any]):
    return stale.determine_stale_case(S.CRITERION, grounding, evidence)


def pair(case) -> tuple[str, str]:
    return case.state, case.reason


def reason_of(case) -> str:
    return case.reason


def section_constants() -> None:
    new = {
        "stale_active_version_used",
        "stale_empty_use_scope_proven",
        "stale_superseded_version_used",
        "stale_out_of_window",
        "stale_active_version_ambiguous",
        "stale_scenario_undeclared",
        "stale_usage_set_missing",
        "stale_window_unresolved",
        "stale_grounding_mode_invalid",
    }
    inherited = {
        "stale_source_dates_ok",
        "annotation_unknown",
        "source_unresolved",
        "version_unresolved",
        "empty_set_not_proven",
        "as_of_missing",
        "citation_version_mismatch",
        "date_intent_conflict",
        "turn_not_executed",
        "turn_error",
        "replay_without_original",
        "evidence_incomplete",
    }
    retired = {
        "no_dated_sources_lifecycle_checked",
        "source_deleted",
        "source_not_published",
        "source_not_active",
        "source_expired",
        "future_source_as_current",
        "lifecycle_unavailable",
        "date_unresolved",
        "citation_source_unresolved",
        "stale_lifecycle_evidence_missing",
        "version_mismatch",
        "stale_source_unresolved",
        "stale_no_positive_refs",
        "stale_positive_ref_not_record_level",
    }
    eq("codes.new_set_9", set(stale.NEW_CODES), new)
    eq("codes.inherited_set_12", set(stale.INHERITED_CODES), inherited)
    eq("codes.total_21", len(stale.DETERMINATION_CODES), 21)
    eq("codes.retired_14", set(stale.RETIRED_CODES), retired)
    eq("codes.partition", set(stale.PASS_CODES) | set(stale.VIOLATION_CODES) | set(stale.UNKNOWN_CODES), set(stale.DETERMINATION_CODES))
    eq("codes.pass_3", set(stale.PASS_CODES), {"stale_active_version_used", "stale_empty_use_scope_proven", "stale_source_dates_ok"})
    eq("codes.violation_4", set(stale.VIOLATION_CODES), {"stale_superseded_version_used", "stale_out_of_window", "citation_version_mismatch", "date_intent_conflict"})
    eq("codes.no_overlap", set(stale.DETERMINATION_CODES) & set(stale.RETIRED_CODES), set())
    check("codes.state_by_code_total", set(stale.STATE_BY_CODE) == set(stale.DETERMINATION_CODES), len(stale.STATE_BY_CODE))
    eq("codes.states", {stale.STATE_BY_CODE[code] for code in stale.DETERMINATION_CODES}, {"passed", "unknown", "violation"})
    doc = (ROOT / "docs/evaluation/p2-stale-source-criterion-v1.md").read_text(encoding="utf-8")
    check("codes.each_appears_in_frozen_doc", all(code in doc for code in stale.DETERMINATION_CODES | stale.RETIRED_CODES))
    eq("constants.criterion_version", stale.CRITERION_VERSION, "p2-stale-source-criterion/v1")
    eq("constants.modes", tuple(stale.GROUNDING_MODES), ("version_state", "date_window"))
    eq("constants.grades", tuple(stale.EVIDENCE_GRADES), ("none", "version_only", "version_plus_date"))
    eq("constants.window_bases", tuple(stale.WINDOW_BASES), ("owner_ruling", "custodian_transcription"))


def section_two_modes() -> None:
    evidence = S.evidence(units=[S.unit("K21")], as_of=S.AS_OF)
    version = determine(S.grounding(), evidence)
    dated = determine(S.dated_grounding(), evidence)
    eq("modes.version_state", pair(version), ("passed", "stale_active_version_used"))
    eq("modes.version_grade", version.evidence_grade, "version_only")
    eq("modes.date_window", pair(dated), ("passed", "stale_source_dates_ok"))
    eq("modes.date_grade", dated.evidence_grade, "version_plus_date")
    eq("modes.mode_provenance", version.provenance["grounding_mode"], "version_state")
    eq("modes.mode_provenance_2", dated.provenance["grounding_mode"], "date_window")
    # Same function, same code path: both calls are determine_stale_case.
    check("modes.same_entry", stale.determine_stale_case is determine.__globals__["stale"].determine_stale_case)
    # Per-case mode switching is not possible: an extra mode key in evidence is rejected.
    extra = S.evidence(units=[S.unit("K21")])
    extra["mode"] = "date_window"
    eq("modes.no_per_case_switch", pair(determine(S.grounding(), extra)), ("unknown", "evidence_incomplete"))


def section_table_14() -> None:
    # §7 shape mapped to K*/S_syn_k; exact expected tuples from the frozen table.
    rows = [
        determine(S.grounding(), S.evidence(units=[S.unit("K21")])),
        determine(S.grounding(), S.evidence(units=[S.unit("K20")])),
        determine(S.grounding(), S.evidence(units=[S.unit("K10")])),
        determine(S.grounding(), S.evidence(units=[S.unit("K11")])),
        determine(S.grounding(), S.evidence(units=[S.unit("K30")])),
        determine(S.grounding(), S.evidence(with_usage=False, usage=S.proven_empty_usage())),
        determine(S.grounding(), S.evidence(with_usage=False, usage=S.usage([]))),
        determine(S.grounding(), S.evidence(with_usage=False, usage={"observed": False, "units": []})),
        determine(
            S.grounding(fixture_sha256=S.FIXTURE_SHA, windows=S.windows()),
            S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
        ),
        determine(
            S.grounding(
                fixture_sha256=S.FIXTURE_SHA,
                windows=S.windows({**copy.deepcopy(S.WINDOW_ROWS), "K21": {"effective_from": "2031-01-01", "effective_to": "2031-02-01"}}),
            ),
            S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
        ),
        determine(
            S.grounding(
                fixture_sha256=S.FIXTURE_SHA,
                windows=S.windows({**copy.deepcopy(S.WINDOW_ROWS), "K21": {"effective_from": "2031-01-01"}}, open_ended=["K11"]),
            ),
            S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
        ),
        determine(
            S.grounding(mode="date_window", fixture_sha256=S.FIXTURE_SHA, windows=None),
            S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
        ),
        determine(
            S.dated_grounding(
                windows=S.windows({**copy.deepcopy(S.WINDOW_ROWS), "K21": {"effective_from": "2031-01-01", "effective_to": "2031-02-01"}})
            ),
            S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
        ),
    ]
    expected = [
        ("passed", "stale_active_version_used", "version_only"),
        ("violation", "stale_superseded_version_used", "none"),
        ("violation", "stale_superseded_version_used", "none"),
        ("passed", "stale_active_version_used", "version_only"),
        ("unknown", "stale_active_version_ambiguous", "none"),
        ("passed", "stale_empty_use_scope_proven", "version_only"),
        ("unknown", "empty_set_not_proven", "none"),
        ("unknown", "stale_usage_set_missing", "none"),
        ("passed", "stale_active_version_used", "version_plus_date"),
        ("violation", "stale_out_of_window", "none"),
        ("passed", "stale_active_version_used", "version_only"),
        ("unknown", "stale_window_unresolved", "none"),
        ("violation", "stale_out_of_window", "none"),
    ]
    actual = [(case.state, case.reason, case.evidence_grade) for case in rows]
    eq("table14.rows_1_13", actual, expected)
    for index, (case, want) in enumerate(zip(rows, expected), start=1):
        eq(f"table14.row{index}", (case.state, case.reason, case.evidence_grade), want)
    multi = S.evidence(with_usage=False)
    multi["turns"] = [
        S.turn(0, {"usage": S.usage([S.unit("K21")])}),
        S.turn(1, {"usage": S.usage([S.unit("K20")])}),
    ]
    folded = determine(S.grounding(), multi)
    eq("table14.row14", pair(folded), ("violation", "stale_superseded_version_used"))
    eq(
        "table14.row14_per_turn",
        [(turn.state, turn.reason) for turn in folded.per_turn],
        [("passed", "stale_active_version_used"), ("violation", "stale_superseded_version_used")],
    )
    check("table14.row14_low_turn_kept", "turn[0]:passed:stale_active_version_used" in folded.provenance["audit"])


def section_f1_f12() -> None:
    # F-1: UNDECLARED member, position order decides; no version_unresolved.
    f1 = determine(S.grounding(), S.evidence(units=[S.unit("K10")]))
    eq("F-1.undeclared_nonactive", pair(f1), ("violation", "stale_superseded_version_used"))
    check("F-1.not_version_unresolved", f1.reason != "version_unresolved")
    f1b = determine(S.grounding(), S.evidence(units=[S.unit("K11")]))
    eq("F-1.undeclared_active", pair(f1b), ("passed", "stale_active_version_used"))
    eq("F-1.undeclared_is_null", f1b.provenance["active_versions"]["K11"]["version_number"], None)

    # F-2: multiple active via duplicate source_indices.
    f2 = determine(
        S.grounding(scenario={**S.SCENARIO, "source_indices": [0, 0, 1, 2, 5]}),
        S.evidence(units=[S.unit("K21")]),
    )
    eq("F-2.duplicate_indices", pair(f2), ("unknown", "stale_active_version_ambiguous"))
    check("F-2.not_violation", f2.state != "violation")

    # F-3: zero active.
    f3 = determine(S.grounding(), S.evidence(units=[S.unit("K30")]))
    eq("F-3.zero_active", pair(f3), ("unknown", "stale_active_version_ambiguous"))
    check("F-3.not_violation", f3.state != "violation")
    check("F-3.audit", any("stale_usage_source_not_in_scenario" in token for token in f3.provenance["audit"]))

    # F-4: date_window all windows exclude as_of -> violation, not N/A.
    f4 = determine(S.dated_grounding(), S.evidence(units=[S.unit("K21")], as_of="2035-01-01"))
    eq("F-4.all_expired", pair(f4), ("violation", "stale_out_of_window"))
    check("F-4.not_na", f4.state != "not_applicable")

    # F-5: mode declaration variants.
    for label, grounding in (
        ("missing", {k: v for k, v in S.grounding().items() if k != "mode"}),
        ("list", S.grounding(mode=["version_state", "date_window"])),
        ("unknown", S.grounding(mode="both")),
        ("dict", S.grounding(mode={"mode": "version_state"})),
        ("double", {**S.grounding(), "stale_grounding": {"mode": "version_state"}}),
    ):
        case = determine(grounding, S.evidence(units=[S.unit("K21")]))
        eq(f"F-5.{label}", pair(case), ("unknown", "stale_grounding_mode_invalid"))
    version_mismatch = stale.determine_stale_case(
        "p2-stale-source-criterion/v0", S.grounding(), S.evidence(units=[S.unit("K21")])
    )
    eq("F-5.criterion_version", pair(version_mismatch), ("unknown", "stale_grounding_mode_invalid"))

    # F-6: scenario contract variants.
    for label, scenario in (
        ("missing", None),
        ("no_indices", {"scenario_id": "S_syn_k"}),
        ("indices_string", {"scenario_id": "S_syn_k", "source_indices": "0,1"}),
        ("index_oob", {"scenario_id": "S_syn_k", "source_indices": [0, 9]}),
        ("index_negative", {"scenario_id": "S_syn_k", "source_indices": [-1]}),
        ("index_bool", {"scenario_id": "S_syn_k", "source_indices": [True]}),
        ("no_scenario_id", {"source_indices": [0]}),
    ):
        case = determine(S.grounding(scenario=scenario), S.evidence(units=[S.unit("K21")]))
        eq(f"F-6.{label}", pair(case), ("unknown", "stale_scenario_undeclared"))
    eq(
        "F-6.ingest_plan_missing",
        pair(determine(S.grounding(ingest_plan=None), S.evidence(units=[S.unit("K21")]))),
        ("unknown", "stale_scenario_undeclared"),
    )

    # F-7: zero usage observation.
    for label, usage in (
        ("observed_false", {"observed": False, "units": []}),
        ("units_missing", {"observed": True, "turn_status": "complete"}),
        ("units_string", {"observed": True, "units": "nope"}),
    ):
        case = determine(S.grounding(), S.evidence(with_usage=False, usage=usage))
        eq(f"F-7.{label}", pair(case), ("unknown", "stale_usage_set_missing"))
    eq(
        "F-7.usage_key_missing",
        pair(determine(S.grounding(), S.evidence(with_usage=False))),
        ("unknown", "stale_usage_set_missing"),
    )

    # F-8: empty set not proven.
    base_empty = S.proven_empty_usage()
    f8_variants = {}
    f8_variants["missing_layers"] = {"observed": True, "units": [], "turn_status": "complete"}
    layer_not_observed = copy.deepcopy(base_empty)
    layer_not_observed["use_layers"]["layer_a"]["observed"] = False
    f8_variants["layer_not_observed"] = layer_not_observed
    truncated = copy.deepcopy(base_empty)
    truncated["retrieval"]["truncated"] = True
    f8_variants["retrieval_truncated"] = truncated
    nonzero = copy.deepcopy(base_empty)
    nonzero["retrieval"]["count"] = 1
    nonzero["retrieval"]["refs"] = ["u1"]
    f8_variants["retrieval_nonzero"] = nonzero
    forged = {"observed": True, "units": [], "turn_status": "complete", "closure_proven": True, "empty_set_candidate": True}
    f8_variants["forged_booleans"] = forged
    for label, usage in f8_variants.items():
        case = determine(S.grounding(), S.evidence(with_usage=False, usage=usage))
        eq(f"F-8.{label}", pair(case), ("unknown", "empty_set_not_proven"))

    # F-9: declared version order conflicts with position order.
    source_map = copy.deepcopy(S.SOURCE_MAP)
    source_map["sources"]["K10"] = {"base_doc_code": "K10", "version_number": 5}
    f9 = determine(S.grounding(source_map=source_map), S.evidence(units=[S.unit("K21")]))
    eq("F-9.order_conflict", pair(f9), ("unknown", "stale_active_version_ambiguous"))
    check("F-9.not_violation", f9.state != "violation")

    # F-10: corpus-constant / all-identical / bad-basis windows.
    constant_rows = copy.deepcopy(S.WINDOW_ROWS)
    constant_rows["K21"] = {"effective_from": "2031-01-01", "effective_to": "2032-01-01"}
    constant = S.grounding(
        fixture_sha256=S.FIXTURE_SHA,
        windows=S.windows(constant_rows),
        built_at="2031-01-01",
    )
    eq("F-10.built_at_version_state", pair(determine(constant, S.evidence(units=[S.unit("K21")], as_of=S.AS_OF))), ("passed", "stale_active_version_used"))
    check("F-10.built_at_audit", "stale_date_fixture_rejected" in determine(constant, S.evidence(units=[S.unit("K21")], as_of=S.AS_OF)).provenance["audit"])
    eq("F-10.built_at_date_window", pair(determine({**constant, "mode": "date_window"}, S.evidence(units=[S.unit("K21")], as_of=S.AS_OF))), ("unknown", "stale_window_unresolved"))
    identical = S.windows({"K20": {"effective_from": "2030-01-01", "effective_to": "2031-01-01"}, "K10": {"effective_from": "2030-01-01", "effective_to": "2031-01-01"}}, open_ended=[])
    eq(
        "F-10.all_identical",
        pair(determine(S.grounding(fixture_sha256=S.FIXTURE_SHA, windows=identical), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF))),
        ("passed", "stale_active_version_used"),
    )
    eq(
        "F-10.bad_basis_date_window",
        pair(determine({**S.dated_grounding(windows=S.windows(basis="inferred_from_upload_order"))}, S.evidence(units=[S.unit("K21")], as_of=S.AS_OF))),
        ("unknown", "stale_window_unresolved"),
    )

    # F-11: annotation N/A or wrong criterion -> annotation_unknown, never N/A.
    for label, annotation in (
        ("not_applicable", S.annotation(applicability="not_applicable", reason="no_entity_scope")),
        ("wrong_criterion", S.annotation(criterion="no_entity_claim")),
    ):
        case = determine(S.grounding(), S.evidence(units=[S.unit("K21")], annotation=annotation))
        eq(f"F-11.{label}", pair(case), ("unknown", "annotation_unknown"))
        check(f"F-11.{label}.not_na", case.state != "not_applicable")
    check("F-11.scope_audit", "scope_mode_mismatch" in determine(S.grounding(), S.evidence(units=[S.unit("K21")], annotation=S.annotation(applicability="not_applicable"))).provenance["audit"])

    # F-12: violation wins, unknown turn preserved.
    evidence = S.evidence(with_usage=False)
    evidence["turns"] = [
        S.turn(0, {"usage": {"observed": False, "units": []}}),
        S.turn(1, {"usage": S.usage([S.unit("K20")])}),
    ]
    f12 = determine(S.grounding(), evidence)
    eq("F-12.fold", pair(f12), ("violation", "stale_superseded_version_used"))
    eq("F-12.per_turn", [turn.reason for turn in f12.per_turn], ["stale_usage_set_missing", "stale_superseded_version_used"])
    check("F-12.unknown_kept", "turn[0]:unknown:stale_usage_set_missing" in f12.provenance["audit"])


def section_ambiguity() -> None:
    # Four ambiguity routes must all be unknown, none violation.
    routes: dict[str, Any] = {}
    routes["multi_active_duplicate"] = determine(
        S.grounding(scenario={**S.SCENARIO, "source_indices": [0, 0, 1, 2, 5]}),
        S.evidence(units=[S.unit("K21")]),
    )
    routes["zero_active"] = determine(S.grounding(), S.evidence(units=[S.unit("K30")]))
    source_map = copy.deepcopy(S.SOURCE_MAP)
    source_map["sources"]["K10"] = {"base_doc_code": "K10", "version_number": 9}
    routes["version_order_conflict"] = determine(S.grounding(source_map=source_map), S.evidence(units=[S.unit("K21")]))
    cross_rows = copy.deepcopy(S.WINDOW_ROWS)
    cross_rows["K10"] = {"effective_from": "2030-01-01", "effective_to": "2031-06-01"}
    routes["window_position_crosscheck"] = determine(
        S.dated_grounding(windows=S.windows(cross_rows)),
        S.evidence(units=[S.unit("K10")], as_of="2030-06-01"),
    )
    for label, case in routes.items():
        eq(f"ambiguity.{label}", pair(case), ("unknown", "stale_active_version_ambiguous"))
        check(f"ambiguity.{label}.not_violation", case.state != "violation")
    check(
        "ambiguity.crosscheck_audit",
        any("stale_grounding_crosscheck_disagreement" in token for token in routes["window_position_crosscheck"].provenance["audit"]),
    )
    # date_window multiple covering members -> unknown, not pick-one.
    overlap = copy.deepcopy(S.WINDOW_ROWS)
    overlap["K20"] = {"effective_from": "2031-01-01", "effective_to": "2031-06-01"}
    overlap["K21"] = {"effective_from": "2031-01-01", "effective_to": "2031-06-01"}
    multi_cover = determine(
        S.dated_grounding(windows=S.windows(overlap)),
        S.evidence(units=[S.unit("K21")], as_of="2031-03-01"),
    )
    eq("ambiguity.window_multi_cover", pair(multi_cover), ("unknown", "stale_active_version_ambiguous"))


def section_folding() -> None:
    eq("fold.priority_exact", dict(stale.STATE_PRIORITY), {"violation": 3, "unknown": 2, "not_applicable": 1, "passed": 0})

    class Dummy:
        def __init__(self, state: str, turn_index: int) -> None:
            self.state = state
            self.turn_index = turn_index

    folded = stale._fold([Dummy("passed", 0), Dummy("not_applicable", 1), Dummy("unknown", 2), Dummy("violation", 3)])
    eq("fold.violation_wins", folded.state, "violation")
    eq("fold.na_between_unknown_and_passed", stale._fold([Dummy("not_applicable", 0), Dummy("passed", 1)]).state, "not_applicable")
    eq("fold.tie_smallest_index", stale._fold([Dummy("violation", 5), Dummy("violation", 2)]).turn_index, 2)
    # N/A is not constructible as a real TurnDetermination. Because no fixed code
    # maps to N/A, the state/reason consistency guard fires before the explicit
    # N/A guard; either fixed CriterionError is acceptable, a silent construction
    # is not.
    try:
        stale.TurnDetermination(turn_index=0, state="not_applicable", reason="annotation_unknown", evidence_grade="none")
        raised = False
    except stale.CriterionError as exc:
        raised = exc.code in {
            "criterion_not_applicable_unreachable",
            "criterion_state_reason_mismatch",
        }
    check("fold.na_turn_forbidden", raised)
    # aggregate hard invariant counts.not_applicable == 0.
    fake = SimpleNamespace(state="not_applicable", evidence_grade="none")
    try:
        stale.aggregate_cases([fake])
        raised = False
    except stale.CriterionError as exc:
        raised = exc.code == "not_applicable_unreachable"
    check("fold.aggregate_rejects_na", raised)
    # Unknown is never downgraded to N/A; every code's mapping is fixed.
    check("fold.no_code_maps_to_na", all(state != "not_applicable" for state in stale.STATE_BY_CODE.values()))


def section_basis_output() -> None:
    evidence = S.evidence(units=[S.unit("K21")], as_of=S.AS_OF)
    owner = determine(S.grounding(fixture_sha256=S.FIXTURE_SHA, windows=S.windows(basis="owner_ruling")), evidence)
    custodian = determine(S.grounding(fixture_sha256=S.FIXTURE_SHA, windows=S.windows(basis="custodian_transcription")), evidence)
    eq("basis.owner", (owner.state, owner.reason, owner.evidence_grade), ("passed", "stale_active_version_used", "version_plus_date"))
    eq("basis.custodian", (custodian.state, custodian.reason, custodian.evidence_grade), (owner.state, owner.reason, owner.evidence_grade))
    eq("basis.same_audit", owner.provenance["audit"], custodian.provenance["audit"])
    # Output shape and forbidden conclusion tokens.
    payload = determine(S.grounding(), S.evidence(units=[S.unit("K21")])).as_dict()
    eq("output.keys", set(payload), {"case_id", "scenario_id", "state", "reason", "evidence_grade", "per_turn", "provenance"})
    eq("output.per_turn_keys", set(payload["per_turn"][0]), {"turn_index", "state", "reason"})
    eq("output.provenance_keys", set(payload["provenance"]), {"grounding_mode", "active_versions", "audit"})
    flat = json.dumps(payload, ensure_ascii=False).lower()
    for token in ("verified", "threshold", "release", "score", "mean", "weight"):
        check(f"output.no_{token}", token not in flat)
    check("output.no_as_of_value", S.AS_OF not in flat)
    check("output.no_unit_id", "u-K21" not in flat)
    check("output.no_record_code", "rec-K21" not in flat)
    # Non-pass grades are always none.
    for case in (
        determine(S.grounding(), S.evidence(units=[S.unit("K20")])),
        determine(S.grounding(), S.evidence(with_usage=False)),
        determine(S.grounding(), S.evidence(units=[S.unit("K30")])),
    ):
        eq(f"grade.none.{case.state}.{case.reason}", case.evidence_grade, "none")
    # Grade is not a score: aggregate counts split and sum to passed.
    batch = [
        determine(S.grounding(), S.evidence(units=[S.unit("K21")])),
        determine(S.dated_grounding(), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF)),
        determine(S.grounding(), S.evidence(units=[S.unit("K20")])),
        determine(S.grounding(), S.evidence(with_usage=False)),
    ]
    counts = stale.aggregate_cases(batch)["counts"]
    eq("counts.split_sum", counts["passed"], counts["passed_version_only"] + counts["passed_version_plus_date"])
    eq("counts.expected", counts, {"planned": 4, "passed": 2, "not_applicable": 0, "unknown": 1, "violations": 1, "checked": 3, "passed_version_only": 1, "passed_version_plus_date": 1})


def section_counts() -> None:
    pass_v = determine(S.grounding(), S.evidence(units=[S.unit("K21")]))
    pass_d = determine(S.dated_grounding(), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF))
    violation = determine(S.grounding(), S.evidence(units=[S.unit("K20")]))
    unknown = determine(S.grounding(), S.evidence(with_usage=False))
    empty = stale.aggregate_cases([])["counts"]
    eq("counts.empty", empty, {"planned": 0, "passed": 0, "not_applicable": 0, "unknown": 0, "violations": 0, "checked": 0, "passed_version_only": 0, "passed_version_plus_date": 0})
    # Arbitrary synthetic batches: all three identities hold for every size.
    pool = [pass_v, pass_d, violation, unknown]
    failures = []
    for size in range(0, 41):
        batch = [pool[index % len(pool)] for index in range(size)]
        counts = stale.aggregate_cases(batch)["counts"]
        if counts["planned"] != counts["passed"] + counts["not_applicable"] + counts["unknown"] + counts["violations"]:
            failures.append((size, "planned"))
        if counts["checked"] != counts["passed"] + counts["not_applicable"] + counts["violations"]:
            failures.append((size, "checked"))
        if counts["planned"] != counts["checked"] + counts["unknown"]:
            failures.append((size, "planned_checked"))
        if counts["not_applicable"] != 0:
            failures.append((size, "na"))
        if counts["passed"] != counts["passed_version_only"] + counts["passed_version_plus_date"]:
            failures.append((size, "grade"))
    eq("counts.batches_0_40_failures", failures, [])
    agg = stale.aggregate_cases(pool)
    eq("counts.axes_provenance", agg["axes_provenance"], "rescored")
    eq("counts.criterion_version", agg["criterion_version"], S.CRITERION)


def section_codes_reachable() -> None:
    cases = [
        determine(S.grounding(), S.evidence(units=[S.unit("K21")])),                       # active
        determine(S.grounding(), S.evidence(units=[S.unit("K20")])),                       # superseded
        determine(S.dated_grounding(), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF)), # dates ok
        determine(S.grounding(), S.evidence(with_usage=False, usage=S.proven_empty_usage())),  # empty proven
        determine(S.grounding(), S.evidence(units=[S.unit("K30")])),                       # 0 active
        determine(S.grounding(scenario=None), S.evidence(units=[S.unit("K21")])),          # scenario
        determine(S.grounding(), S.evidence(with_usage=False)),                            # usage missing
        determine(S.grounding(mode="date_window", fixture_sha256=None), S.evidence(units=[S.unit("K21")])),  # window
        determine(S.grounding(mode="unknown"), S.evidence(units=[S.unit("K21")])),         # mode
        determine(S.grounding(), S.evidence(units=[S.unit("K21")], annotation=S.annotation(applicability="not_applicable"))),  # annotation
        determine(S.grounding(), S.evidence(units=[{"unit_id": "u", "code": "K21"}])),     # source unresolved
        determine(S.grounding(), S.evidence(units=[S.unit("NOPE")])),                      # version unresolved
        determine(S.grounding(), S.evidence(with_usage=False, usage=S.usage([]))),         # empty not proven
        determine(S.dated_grounding(), S.evidence(units=[S.unit("K21")], as_of=None)),     # as_of missing
        determine(
            S.grounding(),
            S.evidence(
                units=[S.unit("K21", document_id="d1", version_id="v1")],
                citations=[{"unit_id": "u-K21", "document_id": "d1", "version_id": "v2"}],
            ),
        ),                                                                                  # citation mismatch
        determine(S.grounding(), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF, annotation=S.annotation(as_of="2030-01-01"))),  # date conflict
        determine(S.grounding(), S.evidence(with_usage=False, usage={"observed": False, "reason": "turn_not_executed"})),
        determine(S.grounding(), S.evidence(with_usage=False, usage={"observed": False, "reason": "turn_error"})),
        determine(S.grounding(), S.evidence(with_usage=False, usage={"observed": False, "reason": "replay_without_original"})),
        determine(S.grounding(), S.evidence(with_usage=False, usage={"observed": False, "reason": "evidence_incomplete"})),
        determine(
            S.grounding(fixture_sha256=S.FIXTURE_SHA, windows=S.windows({**copy.deepcopy(S.WINDOW_ROWS), "K21": {"effective_from": "2031-01-01", "effective_to": "2031-02-01"}})),
            S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
        ),                                                                                  # out of window via overlay
    ]
    produced = {case.reason for case in cases}
    eq("codes.all_21_produced", produced, set(stale.DETERMINATION_CODES))
    check("codes.no_retired_produced", produced.isdisjoint(stale.RETIRED_CODES))
    check("codes.no_na_state", all(case.state != "not_applicable" for case in cases))
    for case in cases:
        eq(f"codes.mapping.{case.reason}", stale.STATE_BY_CODE[case.reason], case.state)


def section_identity_and_citation() -> None:
    # P-5 / R-J-7 / R-J-6 ordering: unresolved identity first, then unknown code,
    # then not-in-scenario. Documented order must not turn into "not superseded".
    for label, unit_row, expected in (
        ("unit_not_mapping", "nope", ("unknown", "source_unresolved")),
        ("record_code_missing", {"unit_id": "u", "code": "K21"}, ("unknown", "source_unresolved")),
        ("unknown_code", S.unit("NOPE"), ("unknown", "version_unresolved")),
        ("base_not_in_scenario", S.unit("K30"), ("unknown", "stale_active_version_ambiguous")),
    ):
        eq(f"identity.{label}", pair(determine(S.grounding(), S.evidence(units=[unit_row]))), expected)
    # Citation layer.
    unit = S.unit("K21", document_id="doc-1", version_id="ver-3")
    ok = determine(
        S.grounding(),
        S.evidence(units=[unit], citations=[{"unit_id": "u-K21", "document_id": "doc-1", "version_id": "ver-3"}]),
    )
    eq("citation.match", pair(ok), ("passed", "stale_active_version_used"))
    mismatch = determine(
        S.grounding(),
        S.evidence(units=[unit], citations=[{"unit_id": "u-K21", "document_id": "doc-1", "version_id": "ver-9"}]),
    )
    eq("citation.mismatch", pair(mismatch), ("violation", "citation_version_mismatch"))
    missing = determine(
        S.grounding(),
        S.evidence(units=[unit], citations=[{"unit_id": "u-other", "document_id": "d", "version_id": "v"}]),
    )
    eq("citation.missing_row", pair(missing), ("unknown", "source_unresolved"))
    eq(
        "citation.row_without_unit_identity",
        pair(determine(S.grounding(), S.evidence(units=[S.unit("K21")], citations=[{"unit_id": "u-K21", "document_id": "d", "version_id": "v"}]))),
        ("unknown", "source_unresolved"),
    )
    # R-J-13 product-side date conflict.
    eq(
        "date_intent.conflict",
        pair(determine(S.grounding(), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF, annotation=S.annotation(as_of="2030-01-01")))),
        ("violation", "date_intent_conflict"),
    )
    eq(
        "date_intent.equal",
        pair(determine(S.grounding(), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF, annotation=S.annotation(as_of=S.AS_OF)))),
        ("passed", "stale_active_version_used"),
    )


def section_fixture_binding() -> None:
    # date_window requires a fixture; null -> stale_window_unresolved, not mode invalid.
    eq(
        "fixture.date_window_null",
        pair(determine(S.grounding(mode="date_window", fixture_sha256=None), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF))),
        ("unknown", "stale_window_unresolved"),
    )
    eq(
        "fixture.date_window_missing_payload",
        pair(determine(S.grounding(mode="date_window", fixture_sha256=S.FIXTURE_SHA, windows=None), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF))),
        ("unknown", "stale_window_unresolved"),
    )
    bad_binding = S.windows()
    bad_binding["bindings"] = {"source_map_sha256": "b" * 64}
    eq(
        "fixture.bad_binding",
        pair(determine(S.grounding(mode="date_window", fixture_sha256=S.FIXTURE_SHA, windows=bad_binding), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF))),
        ("unknown", "stale_window_unresolved"),
    )
    # version_state: broken optional fixture is dropped, never unknown.
    broken = S.windows({**copy.deepcopy(S.WINDOW_ROWS), "K21": {"effective_from": "2031-01-01"}}, open_ended=["K11"])
    vs = determine(
        S.grounding(fixture_sha256=S.FIXTURE_SHA, windows=broken),
        S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
    )
    eq("fixture.vs_broken_verdict", pair(vs), ("passed", "stale_active_version_used"))
    eq("fixture.vs_broken_grade", vs.evidence_grade, "version_only")
    check("fixture.vs_broken_audit", "stale_date_fixture_rejected" in vs.provenance["audit"])
    # version_state without fixture -> version_only.
    eq(
        "fixture.vs_absent_grade",
        determine(S.grounding(), S.evidence(units=[S.unit("K21")])).evidence_grade,
        "version_only",
    )
    # date_window must not borrow stale_superseded_version_used.
    # as_of 2031-03: K21 covers, K10 does not; the used K10 is a group member but
    # not the window-active source -> violation stale_out_of_window (not superseded).
    dated_superseded = determine(
        S.dated_grounding(),
        S.evidence(units=[S.unit("K10")], as_of=S.AS_OF),
    )
    eq("fixture.date_window_no_superseded", pair(dated_superseded), ("violation", "stale_out_of_window"))
    check("fixture.date_window_not_superseded", dated_superseded.reason != "stale_superseded_version_used")


def section_precedence() -> None:
    # P-1 before P-3, P-3 before P-4.
    no_annotation = S.evidence(units=[S.unit("K21")], with_usage=False)
    no_annotation.pop("annotation")
    eq(
        "precedence.annotation_before_mode",
        pair(determine({k: v for k, v in S.grounding().items() if k != "mode"}, no_annotation)),
        ("unknown", "annotation_unknown"),
    )
    eq(
        "precedence.mode_before_scenario",
        pair(determine(S.grounding(scenario=None, mode="bad"), S.evidence(units=[S.unit("K21")]))),
        ("unknown", "stale_grounding_mode_invalid"),
    )
    eq(
        "precedence.scenario_before_source_map",
        pair(determine(S.grounding(scenario=None, source_map=None), S.evidence(units=[S.unit("K21")]))),
        ("unknown", "stale_scenario_undeclared"),
    )
    # Unknown top-level keys are rejected, not ignored.
    extra = S.evidence(units=[S.unit("K21")])
    extra["answer"] = "x"
    eq("precedence.unknown_evidence_key", pair(determine(S.grounding(), extra)), ("unknown", "evidence_incomplete"))
    extra_g = S.grounding()
    extra_g["scratch"] = 1
    eq("precedence.unknown_grounding_key", pair(determine(extra_g, S.evidence(units=[S.unit("K21")]))), ("unknown", "stale_grounding_mode_invalid"))


def main() -> int:
    for section in (
        section_constants,
        section_two_modes,
        section_table_14,
        section_f1_f12,
        section_ambiguity,
        section_folding,
        section_basis_output,
        section_counts,
        section_codes_reachable,
        section_identity_and_citation,
        section_fixture_binding,
        section_precedence,
    ):
        section()
    failures = [row for row in CHECKS if not row["pass"]]
    report = {
        "schema_version": "c1p1impl-criterion/v0.1",
        "checks": CHECKS,
        "total": len(CHECKS),
        "passed": len(CHECKS) - len(failures),
        "failed": len(failures),
        "failures": failures,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "04-criterion.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=lambda value: sorted(value) if isinstance(value, set) else repr(value)) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"total": report["total"], "failed": report["failed"], "failures": failures}, ensure_ascii=False, indent=1, default=lambda value: sorted(value) if isinstance(value, set) else repr(value)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
