"""C1-P5 aggregate builder: whitelist-only public aggregate (counts/distributions).

Reads the in-package forecast output and the netguard/preservation receipts. Emits
`forecast-aggregate.json` next to the report. No question text, answers, target values,
dates, ids, record keys or doc codes.
"""
from __future__ import annotations

import json
from pathlib import Path

P5 = Path(r"D:\GPT项目\市场部AI知识库\docs\reports\OBS-EVAL\P2\Q1A-EVAL-REPAIR\c1-1\p5")
EVID = P5 / "evidence"


def load(name: str) -> dict:
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def main() -> int:
    forecast = load("01-forecast.out.json")
    independent = load("02-independent-keycheck.out.json")
    guard = load("04-forecast-zero-call.json")
    positive = load("03-netguard-positive-control.json")
    preserved = load("06-preservation-check.out.json")
    privacy = load("05-privacy-scan.out.json")

    axes = [
        {
            "label": row["label"],
            "criterion": row["criterion"],
            "matchable_targets": row["matchable_targets"],
            "target_granularities": row["target_granularities"],
            "target_entity_types": row["target_entity_types"],
            "target_key_spaces": row["target_key_spaces"],
            "turns": row["turns"],
            "records_used": row["records_used"],
            "verdict": row["verdict"],
            "record_classes": row["record_classes"],
            "match_codes": row["match_codes"],
            "cross_entity": row["cross_state"],
            "cross_reason": row["cross_reason"],
            "stale_source": row["stale_state"],
            "stale_reason": row["stale_reason"],
            "unobserved_use_layer_count": len(row["unobserved_use_layers"]),
        }
        for row in forecast["key_space"]["axes"]
    ]

    aggregate = {
        "schema_version": "c1p5-forecast-aggregate/v0.1",
        "package": "C1-P5",
        "role": "custody-execution",
        "status": "COMPLETE",
        "scope": "zero-call forecast of C1-2 yield using old v0.2 H2 evidence + contract v2 + adapter v2",
        "inputs": {
            "contract_ciphertext_sha256": forecast["inputs"]["contract_ciphertext_sha256"],
            "contract_ciphertext_bytes": forecast["inputs"]["contract_ciphertext_bytes"],
            "contract_schema_sha256": forecast["inputs"]["contract_schema_sha256"],
            "old_run_binding_payload_sha256": forecast["inputs"]["old_run_binding_payload_sha256"],
            "old_evidence_runs": forecast["inputs"]["old_evidence_runs"],
            "public_structure_hashes": forecast["inputs"]["public_structure_hashes"],
        },
        "universe": {
            "cases": forecast["universe"]["cases"],
            "cases_with_executed_evidence": forecast["universe"]["cases_with_executed_evidence"],
            "turns": forecast["universe"]["turns"],
            "used_unit_refs_unique_per_case": forecast["universe"]["used_unit_refs_unique_per_case"],
            "matchable_cross_entity_axes": forecast["universe"]["matchable_cross_entity_axes"],
            "cross_applicability": forecast["universe"]["cross_applicability"],
            "stale_applicability": forecast["universe"]["stale_applicability"],
            "target_entity_types": forecast["universe"]["target_entity_types"],
            "target_key_spaces": forecast["universe"]["target_key_spaces"],
            "cross_entity_states_v03": forecast["universe"]["cross_entity_states_v03"],
            "stale_source_states_v03": forecast["universe"]["stale_source_states_v03"],
            "match_codes": forecast["universe"]["match_codes"],
        },
        "key_space": {
            "counts": forecast["key_space"]["counts"],
            "aligned": forecast["key_space"]["aligned"],
            "entity_key_space_incompatible": forecast["key_space"]["entity_key_space_incompatible"],
            "missing_v03_field": forecast["key_space"]["missing_v03_field"],
            "other_fixed_code": forecast["key_space"]["other_fixed_code"],
            "independent_recheck": {
                "counts": independent["counts"],
                "matchable_axes": independent["matchable_axes"],
                "used_rows_total": independent["used_rows_total"],
                "agrees_with_adapter": independent["counts"] == {
                    key: forecast["key_space"]["counts"].get(key, 0)
                    for key in independent["counts"]
                },
            },
            "axes": axes,
        },
        "v03_dependency": forecast["v03_dependency"],
        "forecast": {
            "realistic": forecast["forecast"]["realistic"],
            "optimistic": forecast["forecast"]["optimistic"],
            "empty_use_axes": forecast["forecast"]["empty_use_axes"],
            "baseline_q1a3_r2": {
                "cross_entity": {"passed": 1, "unknown": 29, "violations": 0},
                "stale_source": {"passed": 13, "unknown": 17, "violations": 0},
                "case_level_pass": 1,
                "case_level_unknown": 29,
                "source": "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r2.json",
            },
            "threshold_reference": {
                "min_pass": 24,
                "total_cases": 30,
                "meets_24_of_30_realistic": False,
                "meets_24_of_30_optimistic": False,
            },
        },
        "conclusion": {
            "line": "C1-2 不值得签 GO（应转 C2）",
            "basis": [
                "realistic case-level pass = 0; optimistic upper bound = 3/30; 24/30 unreachable",
                "stale_source has no pass route under adapter v2 without per-source lifecycle evidence",
                "cross_entity gain 1 -> 13 is reproducible zero-call; a rerun does not increase judgeability",
            ],
        },
        "zero_real_calls": {
            "netguard_blocked": guard["blocked"],
            "external_connect_attempts": sum(
                guard[name] for name in (
                    "socket_connect_external",
                    "socket_connect_ex",
                    "create_connection_external",
                    "dns_getaddrinfo_external",
                    "http_client_external",
                    "httpx_transport_external",
                )
            ),
            "loopback_connects": guard["loopback_connects"],
            "guard_installed": guard["installed"],
            "positive_control_all_blocked": positive["positive_control"]["all_blocked"],
            "positive_control_attempts": len(positive["positive_control"]["attempts"]),
        },
        "preservation": {
            "head_ok": preserved["head_ok"],
            "branch_ok": preserved["branch_ok"],
            "staged_empty": preserved["staged_empty"],
            "c_freeze_12_all_match": preserved["c_freeze_12_all_match"],
            "tracked_modified_all_match": preserved["tracked_modified_all_match"],
            "old_run_intact": all(
                item["card_matches_r2"] and item["seal_tree_matches_r2"] and item["evidence_files_match_seal"]
                for item in preserved["old_run_checks"].values()
            ),
            "readonly_all_untouched": preserved["readonly_all_untouched"],
            "p5_new_file_count_at_check": preserved["p5_new_file_count"],
            "preserved": preserved["preserved"],
        },
        "privacy": {
            "files_scanned": privacy["files_scanned"],
            "clean": privacy["clean"],
            "hits": privacy["hits"],
            "embedded_fernet_key_pattern_files": privacy["embedded_fernet_key_pattern_files"],
        },
        "not_claimed": [
            "T207 pass", "quality pass", "release", "threshold met", "GO / C1-2 authorization",
            "real H2 score", "product correctness", "v0.3 capture availability on a rerun",
        ],
        "residual_marks": [
            "multi-turn composition is undefined by the adapter (one snapshot per case); forecast unions used units across turns",
            "1 stale axis is forbidden-source-only: adapter counts its target_ref as positive (15 resolved) while public coverage reports 14 positive-ref-resolved + 6 no-positive-refs",
            "adapter empty-use proof is stricter than the frozen C primitive (frozen: 2 turns proven; adapter: 0); 1 proven turn belongs to a matchable cross_entity axis",
            "old v0.2 envelopes carry no runtime_snapshot.retrieval_use; the v0.3 model assumes availability=complete, which cannot create the missing model/direct-RAG layers",
            "doc_code_index/record_index are rebuilt from public corpus rules (accepted R2 mapping); no real v0.3 capture exists to cross-check",
        ],
    }
    (P5 / "forecast-aggregate.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(
        {
            "status": aggregate["status"],
            "key_space": aggregate["key_space"]["counts"],
            "realistic": aggregate["forecast"]["realistic"],
            "optimistic": aggregate["forecast"]["optimistic"],
            "conclusion": aggregate["conclusion"]["line"],
            "privacy_clean": aggregate["privacy"]["clean"],
            "preserved": aggregate["preservation"]["preserved"],
        },
        ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
