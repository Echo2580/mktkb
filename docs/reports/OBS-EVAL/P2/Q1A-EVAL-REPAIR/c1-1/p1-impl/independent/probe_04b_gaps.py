"""Criterion edge/disagreement probe: reason ordering, partial turns, bindings.

Separates three classes:
  * conformance checks that pass;
  * `findings` where the implementation diverges from a strict reading of the
    frozen criterion (state remains fail-closed unless stated otherwise);
  * `limitations` that are declarative-binding gaps (fixture/source-map hash is
    a caller declaration, not a content digest).
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[8]
OUT = Path(__file__).resolve().parent / "out"
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_stale_version_state as stale  # noqa: E402

import synth_stale as S  # noqa: E402

RULES: list[dict[str, Any]] = []


def rule(name: str, ok: bool, actual: Any, expected: Any = None) -> None:
    RULES.append({"name": name, "pass": bool(ok), "actual": actual, "expected": expected})


def d(g, e):
    return stale.determine_stale_case(S.CRITERION, g, e)


def p(case) -> tuple[str, str]:
    return case.state, case.reason


def main() -> int:
    findings: list[dict[str, Any]] = []
    limitations: list[dict[str, Any]] = []

    # --- unknown reason ordering (R-J-10: P-1..P-5, R-J-6, R-J-7 in rule order).
    mixed_a = d(S.grounding(), S.evidence(units=[S.unit("NOPE"), S.unit("K30")]))
    mixed_b = d(S.grounding(), S.evidence(units=[S.unit("K30"), S.unit("NOPE")]))
    rule(
        "reason_order.mixed_unknown_units_stable",
        p(mixed_a) == p(mixed_b),
        [p(mixed_a), p(mixed_b)],
        "same fixed reason regardless of unit order",
    )
    if p(mixed_a) != p(mixed_b):
        findings.append(
            {
                "id": "P1-IMPL-F1",
                "severity": "low",
                "claim": "R-J-10 reason ordering",
                "detail": {
                    "unit_order_1": p(mixed_a),
                    "unit_order_2": p(mixed_b),
                    "expected": "R-J-6 stale_active_version_ambiguous before R-J-7 version_unresolved",
                    "impact": "state stays unknown; only reason changes with unit order",
                },
            }
        )
    source_a = d(S.grounding(), S.evidence(units=[{"unit_id": "u", "code": "K21"}, S.unit("NOPE")]))
    source_b = d(S.grounding(), S.evidence(units=[S.unit("NOPE"), {"unit_id": "u", "code": "K21"}]))
    rule(
        "reason_order.source_vs_version_stable",
        p(source_a) == p(source_b),
        [p(source_a), p(source_b)],
        "P-5 source_unresolved before R-J-7 version_unresolved",
    )
    if p(source_a) != p(source_b):
        findings.append(
            {
                "id": "P1-IMPL-F2",
                "severity": "low",
                "claim": "R-J-10 reason ordering across identity failures",
                "detail": {
                    "unit_order_1": p(source_a),
                    "unit_order_2": p(source_b),
                    "expected": "P-5 source_unresolved always first",
                    "impact": "state stays unknown; reason is unit-order dependent",
                },
            }
        )

    # --- partial turn with a non-empty use set.
    partial_with_units = d(
        S.grounding(),
        S.evidence(
            units=[S.unit("K21")],
            usage={"observed": True, "units": [S.unit("K21")], "turn_status": "partial"},
        ),
    )
    rule(
        "usage.partial_turn_with_units_not_pass",
        partial_with_units.state != "passed",
        p(partial_with_units),
        "unknown per R-J-3 ('回合 partial')",
    )
    if partial_with_units.state == "passed":
        findings.append(
            {
                "id": "P1-IMPL-F3",
                "severity": "medium",
                "claim": "R-J-3 partial turn",
                "detail": {
                    "input": "usage.observed=true, units=[K21], turn_status=partial",
                    "actual": p(partial_with_units),
                    "expected": "unknown stale_usage_set_missing (or evidence_incomplete) per R-J-3",
                    "impact": "false pass on a partially executed turn",
                },
            }
        )

    # --- declarative fixture / source-map binding.
    tampered_fixture = d(
        S.dated_grounding(fixture_sha256="f" * 64),
        S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
    )
    rule(
        "binding.fixture_sha_content_checked",
        tampered_fixture.state == "unknown",
        p(tampered_fixture),
        "unknown if fixture_sha256 is not a content digest of the payload",
    )
    if tampered_fixture.state == "passed":
        limitations.append(
            {
                "id": "P1-IMPL-L1",
                "severity": "medium",
                "claim": "§3.2 rule 3 fixture SHA binding",
                "detail": {
                    "input": "fixture_sha256='f'*64 with the default payload",
                    "actual": p(tampered_fixture),
                    "gap": "the module only checks the 64-hex shape; it does not hash the windows payload",
                    "mitigation": "caller must verify the frozen fixture bytes before passing the payload",
                },
            }
        )
    tampered_map = copy.deepcopy(S.SOURCE_MAP)
    # Semantically different source map, same declared hash. Version labels do not
    # change the verdict (K10 is UNDECLARED so R-AV-5 is skipped), which isolates
    # the binding gap from the verdict: a content check would reject, this module
    # accepts and passes.
    tampered_map["sources"]["K20"]["version_number"] = 99
    same_declared = S.windows()["bindings"]["source_map_sha256"]
    map_case = d(
        S.dated_grounding(
            source_map=tampered_map,
            source_map_sha256=same_declared,
            windows=S.windows(),
        ),
        S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
    )
    rule(
        "binding.source_map_content_checked",
        map_case.state == "unknown",
        p(map_case),
        "unknown if the source-map payload changed under a stale declared hash",
    )
    if map_case.state != "unknown":
        limitations.append(
            {
                "id": "P1-IMPL-L2",
                "severity": "medium",
                "claim": "§3.2 fixture bindings",
                "detail": {
                    "input": "source_map mutated (K20 version_number 1->99) while declared source_map_sha256 is unchanged",
                    "actual": p(map_case),
                    "gap": "declared source_map_sha256/ingest_plan_sha256 are compared to the fixture header, not recomputed from the payload",
                },
            }
        )

    # --- binding declarations that ARE checked.
    rule(
        "binding.source_map_declared_mismatch",
        p(
            d(
                S.dated_grounding(source_map_sha256="d" * 64),
                S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
            )
        )
        == ("unknown", "stale_window_unresolved"),
        p(d(S.dated_grounding(source_map_sha256="d" * 64), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF))),
    )
    rule(
        "binding.version_state_rejects_silently",
        p(
            d(
                S.grounding(
                    fixture_sha256=S.FIXTURE_SHA,
                    windows=S.windows(),
                    source_map_sha256="d" * 64,
                ),
                S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
            )
        )
        == ("passed", "stale_active_version_used"),
        "broken optional fixture is dropped in version_state",
    )

    # --- F-10 remaining variants.
    rule(
        "F-10.corpus_header_dates",
        p(
            d(
                S.grounding(
                    fixture_sha256=S.FIXTURE_SHA,
                    windows=S.windows(),
                    corpus_header_dates=["2031-01-01"],
                ),
                S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
            )
        )
        == ("passed", "stale_active_version_used"),
        "version_state drops constant-valued fixture",
    )
    rule(
        "F-10.evidence_ref_missing",
        p(d(S.dated_grounding(windows=S.windows(evidence_ref="")), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF)))
        == ("unknown", "stale_window_unresolved"),
        "empty evidence_ref rejects the fixture in date_window",
    )
    rule(
        "F-10.open_ended_conflict",
        p(
            d(
                S.dated_grounding(windows=S.windows(open_ended=["K20", "K11"])),
                S.evidence(units=[S.unit("K21")], as_of=S.AS_OF),
            )
        )
        == ("unknown", "stale_window_unresolved"),
        "code both open_ended and closed is rejected",
    )

    # --- slot / ingest plan / source map shape boundaries.
    slot_sources = copy.deepcopy(S.SOURCES)
    slot_sources[0]["name"] = "K99_a.xlsx"
    slot_case = d(
        S.grounding(ingest_plan={"sources": slot_sources}),
        S.evidence(units=[S.unit("K21")]),
    )
    rule("boundary.slot_base_conflict", p(slot_case) == ("unknown", "stale_active_version_ambiguous"), p(slot_case))
    rule(
        "boundary.slot_base_conflict_audit",
        "stale_slot_base_conflict" in slot_case.provenance["audit"],
        slot_case.provenance["audit"],
    )
    path_sources = copy.deepcopy(S.SOURCES)
    del path_sources[0]["path"]
    rule(
        "boundary.ingest_path_missing",
        p(d(S.grounding(ingest_plan={"sources": path_sources}), S.evidence(units=[S.unit("K21")])))
        == ("unknown", "stale_scenario_undeclared"),
        "missing path",
    )
    bad_map = copy.deepcopy(S.SOURCE_MAP)
    del bad_map["sources"]["K20"]["base_doc_code"]
    rule(
        "boundary.source_map_row_invalid",
        p(d(S.grounding(source_map=bad_map), S.evidence(units=[S.unit("K21")])))
        == ("unknown", "stale_active_version_ambiguous"),
        "base_doc_code missing",
    )

    # --- malformed nested values.
    rule(
        "boundary.invalid_as_of_date_window",
        p(d(S.dated_grounding(), S.evidence(units=[S.unit("K21")], as_of="not-a-date")))
        == ("unknown", "as_of_missing"),
        "invalid as_of",
    )
    rule(
        "boundary.invalid_annotation_as_of",
        p(d(S.grounding(), S.evidence(units=[S.unit("K21")], annotation=S.annotation(as_of="not-a-date"))))
        == ("unknown", "annotation_unknown"),
        "invalid annotation as_of",
    )
    rule(
        "boundary.citation_row_malformed",
        p(
            d(
                S.grounding(),
                S.evidence(
                    units=[S.unit("K21", document_id="d", version_id="v")],
                    citations=[["x"]],
                ),
            )
        )
        == ("unknown", "source_unresolved"),
        "citation row not a mapping",
    )
    empty_turns = S.evidence(with_usage=False)
    empty_turns["turns"] = []
    rule("boundary.empty_turns", p(d(S.grounding(), empty_turns)) == ("unknown", "turn_not_executed"), p(d(S.grounding(), empty_turns)))
    bad_turns = S.evidence(with_usage=False)
    bad_turns["turns"] = {"x": 1}
    rule("boundary.turns_not_list", p(d(S.grounding(), bad_turns)) == ("unknown", "evidence_incomplete"), p(d(S.grounding(), bad_turns)))

    # --- date_window group member window missing.
    missing_rows = {key: value for key, value in S.WINDOW_ROWS.items() if key != "K20"}
    rule(
        "window.member_missing",
        p(d(S.dated_grounding(windows=S.windows(missing_rows)), S.evidence(units=[S.unit("K21")], as_of=S.AS_OF)))
        == ("unknown", "stale_window_unresolved"),
        "K20 window missing while used group K10 has K20",
    )
    open_rows = copy.deepcopy(S.WINDOW_ROWS)
    open_rows["K11"] = {"effective_from": "2031-01-01"}
    rule(
        "window.open_ended_accepts",
        p(d(S.dated_grounding(windows=S.windows(open_rows)), S.evidence(units=[S.unit("K11")], as_of=S.AS_OF)))
        == ("passed", "stale_source_dates_ok"),
        "open ended source covers as_of",
    )

    # --- static: no code path writes state="not_applicable".
    source = Path(stale.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    na_assignments = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "state":
            value = node.value
            if isinstance(value, ast.Constant) and value.value == "not_applicable":
                na_assignments.append(node.lineno)
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "state"
                    and isinstance(value, ast.Constant)
                    and value.value == "not_applicable"
                ):
                    na_assignments.append(node.lineno)
    rule("na.no_assignment", na_assignments == [], na_assignments, "no state='not_applicable' assignment")
    lines = [
        (index, line.strip())
        for index, line in enumerate(source.splitlines(), start=1)
        if "not_applicable" in line
    ]
    rule("na.guard_present", any("criterion_not_applicable_unreachable" in line for _, line in lines), lines)

    # --- output-token guard on echoed input text.
    token_escapes = []
    for cid in ("release-1", "verified-x", "threshold-y"):
        evidence = S.evidence(units=[S.unit("K21")])
        evidence["case_id"] = cid
        try:
            d(S.grounding(), evidence)
        except BaseException as exc:  # noqa: BLE001
            token_escapes.append({"case_id": cid, "exception": type(exc).__name__, "message": str(exc)})
    rule(
        "output.forbidden_token_input_returns_fixed_code",
        token_escapes == [],
        token_escapes,
        "string case_id containing a conclusion token should not crash",
    )
    if token_escapes:
        findings.append(
            {
                "id": "P1-IMPL-F4",
                "severity": "low",
                "claim": "I-5 output guard on echoed input",
                "detail": {
                    "cases": token_escapes,
                    "expected": "fixed code + unknown, or sanitized echo",
                    "impact": "a case_id/scenario_id containing verified/threshold/release raises CriterionError out of determine_stale_case",
                },
            }
        )

    # --- old-evidence shape is not the §8.1 input.
    p4_path = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/independent/synth.py"
    spec = importlib.util.spec_from_file_location("p4synth_shape", p4_path)
    p4 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(p4)
    old_as_evidence = d(p4.contract(), p4.snapshot([p4.record()]))
    old_as_grounding = d(p4.contract(), S.evidence(units=[S.unit("K21")]))
    rule(
        "old_shape.snapshot_as_evidence",
        p(old_as_evidence) == ("unknown", "evidence_incomplete"),
        p(old_as_evidence),
        "P4 snapshot v0.3 is not a §8.1 evidence object",
    )
    rule(
        "old_shape.contract_as_grounding",
        p(old_as_grounding) == ("unknown", "stale_grounding_mode_invalid"),
        p(old_as_grounding),
        "contract v2 is not a §8.1 grounding object",
    )

    # --- documented criterion tensions (not failures; recorded for the manager).
    tensions = [
        {
            "id": "P1-IMPL-T1",
            "topic": "duplicate source_indices",
            "R-AV-1": "stale_scenario_undeclared",
            "F-2": "stale_active_version_ambiguous",
            "implemented": "stale_active_version_ambiguous (explicitly documented in module docstring §1)",
            "state": "unknown either way",
        },
        {
            "id": "P1-IMPL-T2",
            "topic": "empty units + turn partial",
            "R-J-3": "stale_usage_set_missing",
            "F-8": "empty_set_not_proven",
            "implemented": "empty_set_not_proven (explicitly documented in module docstring §2)",
            "state": "unknown either way",
        },
        {
            "id": "P1-IMPL-T3",
            "topic": "scenario_id not in dataset contract",
            "input_shape": "§8.1 carries the scenario object inline; no dataset-level scenario registry is an input",
            "implemented": "missing/invalid inline scenario -> stale_scenario_undeclared; membership in a registry cannot be checked",
        },
    ]

    report = {
        "schema_version": "c1p1impl-gaps/v0.1",
        "rules": RULES,
        "failures": [row for row in RULES if not row["pass"]],
        "findings": findings,
        "limitations": limitations,
        "tensions": tensions,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "04b-gaps.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "rules": len(RULES),
                "failed": len(report["failures"]),
                "failures": report["failures"],
                "findings": findings,
                "limitations": limitations,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
