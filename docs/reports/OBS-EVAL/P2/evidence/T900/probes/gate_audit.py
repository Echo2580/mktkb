"""T900 phase-2 gate/quality audit (read-only).

Audits the frozen formal gate result, the NCU manifest tallies, the H2
aggregate/source proof/cards index, and the eight hard-gate rows.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend/src"))

from mktkb.evaluation.p2_b0 import load_approved_b0_config  # noqa: E402
from mktkb.evaluation.p2_contracts import payload_sha256  # noqa: E402

P2 = ROOT / "docs/reports/OBS-EVAL/P2"
FREEZE = P2 / "candidate-freeze.json"
GATE = P2 / "CROSS-SCENARIO-GATE/gate-result.real-ncu.json"
NCU = P2 / "NCU-RELEASE-EVIDENCE"
H2 = P2 / "H2-REBUILT-CARDS"
APPROVED = ROOT / "docs/evaluation/gate_v0_3_approved.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    freeze = json.loads(FREEZE.read_text("utf-8"))
    gate = json.loads(GATE.read_text("utf-8"))
    ncu = json.loads((NCU / "manifest.json").read_text("utf-8"))
    agg = json.loads((H2 / "h2-composition-aggregate.json").read_text("utf-8"))
    proof = json.loads((H2 / "h2-source-proof.full.json").read_text("utf-8"))
    index = json.loads((H2 / "cards-index.json").read_text("utf-8"))
    report = (H2 / "report.md").read_text("utf-8")
    rows = {row["row_id"]: row for row in gate["rows"]}

    checks: list[dict] = []

    def check(name: str, ok: bool, detail) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    counts = Counter(row["decision"] for row in gate["rows"])
    check("row_count_47", len(gate["rows"]) == 47, len(gate["rows"]))
    check("counts_38_0_0_9", counts == {"pass": 38, "observed": 9},
          dict(counts))
    check("counts_field", gate["counts"] == {"pass": 38, "blocked": 0, "pending": 0, "observed": 9},
          gate["counts"])
    check("reason_codes_empty", gate["reason_codes"] == [], gate["reason_codes"])
    check("decision_pass", gate["decision"] == "pass", gate["decision"])
    check("technical_gate_pass", gate["technical_gate"] == "pass", gate["technical_gate"])
    check("release_not_allowed", gate["release_allowed"] is False, gate["release_allowed"])
    check("owner_not_decided", gate["owner_release_decision"] == "not_decided",
          gate["owner_release_decision"])
    check("release_authority_owner", gate["release_authority"] == "owner",
          gate["release_authority"])

    row_ids = [row["row_id"] for row in gate["rows"]]
    freeze_ids = freeze["formal_gate"]["row_ids"]
    sorted_ids = sorted(row_ids)
    ids_sha = hashlib.sha256(("\n".join(sorted_ids)).encode()).hexdigest()
    check("row_ids_set_matches_freeze", set(row_ids) == set(freeze_ids),
          {"gate": len(row_ids), "freeze": len(freeze_ids), "only_gate": sorted(set(row_ids) - set(freeze_ids)),
           "only_freeze": sorted(set(freeze_ids) - set(row_ids))})
    check("row_ids_sha256_matches_freeze", ids_sha == freeze["formal_gate"]["row_ids_sha256"],
          {"computed": ids_sha, "freeze": freeze["formal_gate"]["row_ids_sha256"]})
    check("disclosure_row_present", "hard_gate_min_sample.run_level_subset" in rows,
          rows.get("hard_gate_min_sample.run_level_subset", {}).get("decision"))
    disclosure = rows["hard_gate_min_sample.run_level_subset"]["detail"]
    check("disclosure_values", (
        disclosure["suite"] == "update_delete"
        and disclosure["suite_planned_cases"] == 10
        and disclosure["required_min_sample"] == 10
        and disclosure["run_level_evaluated"] == 1
        and disclosure["basis"] == "suite_planned_cases"
        and disclosure["covered"] is True
    ), disclosure)

    config = load_approved_b0_config(APPROVED)
    check("gate_config_file_sha", sha(APPROVED) == freeze["gate_config"]["sha256"],
          {"sha": sha(APPROVED), "freeze": freeze["gate_config"]["sha256"]})
    check("gate_config_canonical_hash", gate["gate_config_hash"] == config.config_hash ==
          "7fa6f47a445f9643eb7f2e5ae78a72411007da38a56fca1082657870b2eab094",
          gate["gate_config_hash"])

    b0 = rows["b0.execution"]["detail"]
    check("b0_execution", b0["planned"] == 40 and b0["executed"] == 40, b0)
    check("b0_quality", rows["b0.quality"]["detail"]["passed"] == 38
          and rows["b0.quality"]["detail"]["failed"] == 2
          and rows["b0.quality"]["detail"]["errors"] == 0, rows["b0.quality"]["detail"])
    check("b0_exact", rows["b0.exact"]["detail"]["exact_passed"] == 24
          and rows["b0.exact"]["detail"]["exact_planned"] == 24, rows["b0.exact"]["detail"])
    check("b0_ocr", rows["b0.ocr"]["detail"]["ocr_executed"] == 8
          and rows["b0.ocr"]["detail"]["ocr_passed"] == 7, rows["b0.ocr"]["detail"])
    b0g = rows["hard_gates.b0"]["detail"]
    check("b0_hard_gates", b0g["min_sample"] == 32 and b0g["scored_count"] == 40
          and set(b0g["gate_status"].values()) <= {"pass", "not_applicable"}
          and b0g["min_sample_coverage"]["run_level_evaluated"] == 40, b0g)

    cases = ncu["cases"]
    per_tier = Counter((case["group"], case["adopt"]) for case in cases)
    formal = {
        "N": per_tier[("N", "ADOPTED")] + per_tier[("N", "ADOPTED_WITH_BINDING_PROOF")],
        "C": per_tier[("C", "ADOPTED")] + per_tier[("C", "ADOPTED_WITH_BINDING_PROOF")],
        "U": per_tier[("U", "ADOPTED")] + per_tier[("U", "ADOPTED_WITH_BINDING_PROOF")],
    }
    unconditional = {k: per_tier[(k, "ADOPTED")] for k in "NCU"}
    proofed = {k: per_tier[(k, "ADOPTED_WITH_BINDING_PROOF")] for k in "NCU"}
    check("ncu_cases_24", len(cases) == 24, len(cases))
    check("ncu_unconditional_7_2_9", unconditional == {"N": 7, "C": 2, "U": 9}, unconditional)
    check("ncu_proofed_1_4_1", proofed == {"N": 1, "C": 4, "U": 1}, proofed)
    check("ncu_formal_8_6_10", formal == {"N": 8, "C": 6, "U": 10}, formal)
    check("ncu_tallies", ncu["tallies"]["judged_pass"] == {"N": "8/8", "C": "6/6", "U": "10/10", "not_executed": 0}
          and ncu["tallies"]["adopted_unconditional"]["N"] == 7
          and ncu["tallies"]["adopted_unconditional"]["C"] == 2
          and ncu["tallies"]["adopted_unconditional"]["U"] == 9
          and ncu["tallies"]["adopted_with_binding_proof"]["N"] == 1
          and ncu["tallies"]["adopted_with_binding_proof"]["C"] == 4
          and ncu["tallies"]["adopted_with_binding_proof"]["U"] == 1
          and ncu["tallies"]["adopted_formal_total"]["N"] == 8
          and ncu["tallies"]["adopted_formal_total"]["C"] == 6
          and ncu["tallies"]["adopted_formal_total"]["U"] == 10,
          ncu["tallies"])
    proofed_cases = [case for case in cases if case["adopt"] == "ADOPTED_WITH_BINDING_PROOF"]
    check("ncu_proofed_cases_retain_mechanical_fail", all(
        case.get("mechanical_gate_failures") and case.get("binding_proof") for case in proofed_cases),
        [(case["case_id"], len(case.get("mechanical_gate_failures") or [])) for case in proofed_cases])
    def case_pass(case: dict) -> bool:
        if "score_status" in case:
            return case["score_status"] == "pass"
        return (case.get("historical") or {}).get("status") == "pass" \
            and (case.get("rerun") or {}).get("failed") == 0

    check("ncu_judged_pass", all(case_pass(case) for case in cases)
          and len(proofed_cases) == 6, {"cases": len(cases), "proofed": len(proofed_cases),
                                        "non_pass": [case["case_id"] for case in cases if not case_pass(case)]})
    check("ncu_release_decision_false", ncu["release_decision"] is False, ncu["release_decision"])
    check("ncu_network_zero", all(ncu["network_evidence"][k] == 0 for k in (
        "new_real_requests", "new_model_or_api_calls", "production_data_or_real_provider_execution")),
        ncu["network_evidence"])
    check("ncu_min_sample_unmet_1_10", ncu["hard_gate_min_sample"]["unmet"] == {
        "suite": "update_delete", "evaluated": 1, "required": 10}, ncu["hard_gate_min_sample"]["unmet"])

    check("tally_row_unconditional", rows["tallies.unconditional"]["decision"] == "observed"
          and rows["tallies.unconditional"]["detail"]["counts"] == {"N": 7, "C": 2, "U": 9}
          and rows["tallies.unconditional"]["detail"]["planned"] == {"N": 8, "C": 6, "U": 10},
          rows["tallies.unconditional"]["detail"])
    check("tally_row_formal", rows["tallies.formal"]["decision"] == "pass"
          and rows["tallies.formal"]["detail"]["counts"] == {"N": 8, "C": 6, "U": 10}
          and rows["tallies.formal"]["detail"]["unconditional"] == {"N": 7, "C": 2, "U": 9}
          and rows["tallies.formal"]["detail"]["with_binding_proof"] == {"N": 1, "C": 4, "U": 1}
          and rows["tallies.formal"]["detail"]["recomputed_pass"] == {"N": 8, "C": 6, "U": 10},
          rows["tallies.formal"]["detail"])
    check("evidence_manifest_row_17", rows["evidence_manifest"]["decision"] == "pass"
          and rows["evidence_manifest"]["detail"]["sha256sums"]["verified"] == 17
          and rows["evidence_manifest"]["detail"]["sha256sums"]["mismatch"] == 0
          and rows["evidence_manifest"]["detail"]["sha256sums"]["missing"] == 0,
          rows["evidence_manifest"]["detail"]["sha256sums"])

    u = rows["u.hard_gates"]["detail"]
    check("u_hard_gate_min_sample", u["min_sample"] == 10 and u["scored_count"] == 1
          and u["min_sample_coverage"] == {
              "suite": "update_delete", "suite_planned_cases": 10,
              "required_min_sample": 10, "run_level_evaluated": 1,
              "basis": "suite_planned_cases", "covered": True}, u)
    check("u_only_disclosed_unknown", set(u["gate_status"].values()) <= {"pass", "not_applicable"}
          and all(item.get("check_id") == "min_sample_not_met" for item in (u.get("unknowns") or [])),
          u.get("unknowns"))
    check("u_local_counts", rows["u"]["detail"]["passed"] == 10
          and rows["u"]["detail"]["real"]["case_ids"] == ["U01"]
          and len(rows["u"]["detail"]["local"]["case_ids"]) == 10, rows["u"]["detail"])

    h2 = rows["h2.aggregate"]["detail"]
    check("h2_30_36_29_1", h2["total"] == 30 and h2["turns_planned"] == 36
          and h2["turns_executed"] == 36 and h2["passed"] == 29 and h2["failed"] == 1
          and h2["hard_failures"] == 0 and h2["required_unknowns"] == 0,
          h2)
    check("h2_strata", agg["strata"]["paraphrase"]["total"] == 10
          and agg["strata"]["multi_turn"]["total"] == 5
          and agg["strata"]["negative"]["total"] == 5
          and agg["strata"]["stale_conflict"]["total"] == 5
          and agg["strata"]["cross_doc_security"]["total"] == 5, agg["strata"])
    check("h2_axes", agg["axes"]["safety"] == {"planned": 30, "passed": 5, "not_applicable": 25, "unknown": 0, "violations": 0, "checked": 30}
          and all(agg["axes"][axis]["unknown"] == 0 and agg["axes"][axis]["violations"] == 0
                  for axis in ("cross_user", "cross_entity", "stale_source")),
          agg["axes"])
    check("h2_cards_4", len(index["cards"]) == 4 and len(agg["cards"]) == 4
          and [c["scenario_id"] for c in index["cards"]] == ["base_b0", "base_b0_plus_v01",
                                                             "pre_v05_without_v07", "post_v05_without_v01"],
          [c["scenario_id"] for c in index["cards"]])
    file_hashes = [c["card_sha256"] for c in index["cards"]]
    agg_hashes = [c["aggregate_sha256"] for c in agg["cards"]]
    check("h2_card_hash_sets_distinct", len(set(file_hashes)) == 4 and len(set(agg_hashes)) == 4
          and all(a != b for a, b in zip(file_hashes, agg_hashes)),
          {"files": file_hashes, "aggregates": agg_hashes})
    proof_by_id = {item["scenario_id"]: item for item in proof["scenarios"]}
    check("h2_proof_derived_matches_aggregate", all(
        proof_by_id[c["scenario_id"]]["derived_card_sha256"] == c["aggregate_sha256"]
        for c in agg["cards"]),
        [(c["scenario_id"], proof_by_id[c["scenario_id"]]["derived_card_sha256"] == c["aggregate_sha256"])
         for c in agg["cards"]])
    check("h2_zero_call", proof["zero_call"] == {"new_requests": 0, "new_outbound": 0, "replayed": False},
          proof["zero_call"])
    check("h2_c25_derived_zero", proof["c25_non_required_unknown"]["count"] == 0
          and rows["h2.non_required_axes"]["detail"]["c25"]["count"] == 0,
          proof["c25_non_required_unknown"])
    check("h2_c25_historical_one_documented",
          "| 历史 live（未传同场景 `source_identity`） | `unknown / forbidden_source_unmappable` | **1** |" in report
          and "| 本派生（v0.6 + 授权真实身份） | `not_applicable / benign_business_no_frozen_checks` | **0** |" in report,
          {"report_c25_block": "§5/§12.7"})

    hg = rows["hard_gates"]["detail"]
    check("eight_gates_no_fail", all(
        status in {"pass", "not_applicable"}
        for per_gate in hg["per_gate"].values() for status in per_gate.values()),
        hg["per_gate"])
    check("eight_gates_not_applicable_three", set(hg["not_applicable_gates"]) == {
        "cross_entity", "pagination_contract", "stale_bypass"}, hg["not_applicable_gates"])
    check("eight_gates_disclosed_unknown_only_min_sample",
          all(item["gate_id"] == "min_sample" for item in hg["disclosed_unknowns"]),
          hg["disclosed_unknowns"])
    check("eight_gates_min_sample_map", hg["min_sample"] == {
        "b0": 32, "badcase": 8, "boundary": 6, "update_delete": 10,
        "regression": 7, "p2-holdout": 30}, hg["min_sample"])

    em = gate["evidence_manifest"]
    check("evidence_manifest_hashes", em == {
        "manifest_sha256": sha(NCU / "manifest.json"),
        "report_sha256": sha(NCU / "report.md"),
        "sha256sums_sha256": sha(NCU / "SHA256SUMS")}, em)

    failed = [c for c in checks if not c["ok"]]
    result = {"checks_total": len(checks), "checks_failed": len(failed),
              "failed": failed, "checks": checks}
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if out is not None:
        out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({"checks_total": len(checks), "checks_failed": len(failed),
                      "failed": failed}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
