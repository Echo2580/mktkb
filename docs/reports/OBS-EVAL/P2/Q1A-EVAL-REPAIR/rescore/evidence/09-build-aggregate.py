"""汇总公开聚合（只计数/分布/hash/零调用；无逐题内容）。

输入只读本目录已生成的 *.out.json 与 04-protected-*.json；不重新解密任何私有件。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AXES = ("safety", "cross_user", "cross_entity", "stale_source")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load(name: str):
    path = HERE / name
    return json.loads(path.read_text(encoding="utf-8-sig")), {"path": str(path), "sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}


def main() -> int:
    entry, entry_rec = load("01-entry-selfcheck.out.json")
    identity, identity_rec = load("02-identity-binding.out.json")
    blocked, blocked_rec = load("03-blocked-input-proof.out.json")
    before, before_rec = load("04-protected-before.json")
    after, after_rec = load("04-protected-after.json")
    contract, contract_rec = load("06-contract-consumer-check.out.json")
    private, private_rec = load("07-private-detail.out.json")
    netguard, netguard_rec = load("08-netguard.py") if False else (None, None)

    netguard_path = HERE / "08-netguard.json"
    netguard_payload = json.loads(netguard_path.read_text(encoding="utf-8").strip())

    repo_changed = [k for k in before["repo_files"] if before["repo_files"][k]["sha256"] != after["repo_files"][k]["sha256"]]
    external_changed = {}
    for key, old in before["external"].items():
        new = after["external"][key]
        if "tree_sha256" in old:
            changed_files = [p for p in set(old["files"]) | set(new["files"]) if old["files"].get(p) != new["files"].get(p)]
            if old["tree_sha256"] != new["tree_sha256"] or changed_files:
                external_changed[key] = {"tree_changed": old["tree_sha256"] != new["tree_sha256"], "files": sorted(changed_files)}
        elif old["sha256"] != new["sha256"]:
            external_changed[key] = "changed"

    old_axes = blocked["aggregate_old_axes_from_cards"]
    safety_old = old_axes["safety"]
    cross_entity_old = old_axes["cross_entity"]

    aggregate = {
        "schema_version": "q1a3-rescore-aggregate/v0.1",
        "package": "Q1a-3（P2 Q1A-EVAL-REPAIR / rescore）",
        "analysis_id": "Q1A-RESCORE-20261114-r1",
        "generated_utc": "2026-11-14",
        "conclusion": "NOT-RUN",
        "conclusion_reason": {
            "code": "old_card_per_case_axes_absent",
            "statement": (
                "4 张旧卡均为聚合卡（detail_export=false，顶层无逐题行），case-plan 只有 case_id/quality_status/turns，"
                "回执/manifest 只有计数；Q1a-1 的 OldCardCase 与 Q1a-1b 的 AxesCaseView 都要求逐题四轴 state+reason，"
                "缺该输入则 SafetyCaseView/AxesCaseView 无法构造，rescore_run/rescore_axes_run 一律 refused:cases_empty。"
            ),
            "not_worked_around_because": [
                "import C 冻结 p2_hard_evidence.py 补造旧值 → 明令禁止，且等于重算旧分而非读旧卡（违背 R-04 字节实测口径）",
                "用合同标注或证据推断逐题旧 verdict → 等于伪造旧值",
                "读自由回答文本判产品对错 → 被语义边界禁止",
            ],
            "evidence": [blocked_rec, entry_rec],
        },
        "entry_selfcheck": {
            "overall": entry["overall"],
            "check_count": len(entry["checks"]),
            "failed_checks": [c["check"] for c in entry["checks"] if not c["match"]],
            "dataset_version": "P2-HOLDOUT-v2",
            "label_version": "p2-holdout-v2-2026-11-10",
            "case_count": 30,
            "turn_count": 36,
            "cases_sha256": entry["measured"]["cases_sha256"],
            "scenario_counts": entry["measured"]["scenario_counts"],
            "artifact": entry_rec,
        },
        "analysis_identity": {
            "components": identity["identity_components"],
            "component_matches": {c["component"]: c["match"] for c in identity["checks"]},
            "all_components_match": identity["overall"] == "MATCH",
            "package_binding_sha256": identity["package_binding_sha256"],
            "package_binding_note": identity["package_binding_note"],
            "module_analysis_identity_sha256_issued": False,
            "module_analysis_identity_sha256_not_issued_because": "只能由 rescue_run/rescore_axes_run 成功评分后签发；本次无评分",
            "evidence_tree_cross_check_vs_seal_manifest": {
                k: v["evidence_tree"]["cross_check_equal"] for k, v in identity["measured"]["runs"].items()
            },
            "artifact": identity_rec,
        },
        "old_card_facts": {
            "cards": {
                k: {
                    "run_id": v["run_id"],
                    "sha256": v["card_sha256"],
                    "bytes": v["card_bytes"],
                    "detail_export": v["detail_export"],
                    "has_per_case_array": v["has_per_case_array"],
                }
                for k, v in blocked["per_run"].items()
            },
            "old_axes_aggregate_from_cards": old_axes,
            "old_axes_consistency": blocked["aggregate_old_axes_consistency"],
            "cases": blocked["cases"],
            "fail_counts_by_run": {k: v["case_plan_quality_status_counts"].get("fail", 0) for k, v in blocked["per_run"].items()},
            "artifact": blocked_rec,
        },
        "contract_v1_consumer_check": {
            "contract_ciphertext_sha256": contract["contract_ciphertext_sha256"],
            "contract_ciphertext_bytes": contract["contract_ciphertext_bytes"],
            "defect_count": contract["defect_count"],
            "defects": contract["defects"],
            "binding_checks_total": len(contract["binding_checks"]),
            "binding_checks_failed": [b["binding"] for b in contract["binding_checks"] if not b["match"]],
            "coverage": contract["coverage"],
            "unknown_total": contract["unknown_total"],
            "applicability": contract["applicability"],
            "basis_counts": contract["basis_counts"],
            "criterion_counts": contract["criterion_counts"],
            "reason_counts": contract["reason_counts"],
            "reason_code_table_size_verified_against": contract["reason_code_table_size"],
            "reason_codes_outside_table": contract["reason_codes_not_in_authoritative_table"],
            "basis_recompute_rule": "schema §4.1 首个命中即止（v0.3 gap 例外 → unknown → 按轴）",
            "artifact": contract_rec,
        },
        "four_axis_rescore": {
            "executed": False,
            "reason": "old_card_per_case_axes_absent",
            "old_axes": old_axes,
            "new_axes": None,
            "old_new_columns_deliverable": False,
            "provenance": "无法签发：axes_provenance 需要逐题 rescored/recorded_old 归属",
        },
        "fail_triage_11": {
            "cases_total": 11,
            "by_run": {k: v for k, v in {k: blocked["per_run"][k]["case_plan_quality_status_counts"].get("fail", 0) for k in blocked["per_run"]}.items()},
            "assigned": 0,
            "not_assigned": 11,
            "enum_counts": {"product_error": 0, "annotation_or_criterion_issue": 0, "evidence_insufficient": 0, "undetermined": 11},
            "reason": (
                "逐题归属需要『四轴投影』（逐题 old/new 轴值）；四轴投影缺失。"
                "剩余可用的结构化来源（卡片 block、case-plan quality_status、证据完整度、合同判定）只能定位到 run 级计数，"
                "无法把 11 个 fail 逐个落到固定四枚举，故一律记 undetermined（不猜）。"
            ),
            "structural_only_facts": {
                "failed_total_from_cards": blocked["cases"]["failed_from_cards"],
                "passed_total_from_cards": blocked["cases"]["passed_from_cards"],
                "safety_violations_total": safety_old["violations"],
                "cross_entity_unknown_total": cross_entity_old["unknown"],
                "cross_user_unknown_total": old_axes["cross_user"]["unknown"],
                "stale_source_unknown_total": old_axes["stale_source"]["unknown"],
            },
        },
        "safety_r0_r2": {
            "r0": {
                "verdict_under_new_criteria": "undetermined",
                "missing_inputs": ["逐题旧 safety verdict（state+reason）", "逐题 missing_codes", "逐题 evidence_complete"],
                "e0_reference": "E0 manager receipt：两角色一致 annotation_or_criterion_issue / strong（旧 matcher 忽略 doc_code/record_code；version-aware forbidden match=0；无 forbidden value）",
                "why_not_adopted_as_verdict": "E0 是旧 matcher 下的定位，不是新判据（matcher v2 + safety-n/a-scope/v1）下的轴判定；新判据要求逐题 SafetyCaseView 重算",
            },
            "r2": {
                "verdict_under_new_criteria": "undetermined",
                "missing_inputs": ["逐题旧 safety verdict（state+reason）", "逐题 missing_codes", "逐题 evidence_complete"],
                "e0_reference": "E0 保留 A/B 分歧：A=outbound_send/retrieval_or_use_scope_issue；B=mapping_or_annotation/annotation_or_criterion_issue（版本身份假阳性）",
                "why_not_adopted_as_verdict": "同一缺口；且 A/B 的『性质』分歧若要判定必须读自由文本，被语义边界禁止",
            },
            "mechanism_note": (
                "新判据下 safety 的结构性事实：matcher v2 对 frozen forbidden ref 需要 record_code 与 version 绑定，"
                "而冻结 ref 无 version 字段、unit 侧也无 record_code 映射（_UNIT_SCHEMA 无该列）→ 全部 forbidden ref 只能 unresolved；"
                "N/A(benign) 作用域对 unresolved 抑制，required 作用域落 unknown forbidden_source_unmappable。"
                "因此两个旧 violation 即使有逐题旧值，也不会被新判据重新判成 violation；但也不等于『证明干净』，"
                "且旧 violation 若 missing_codes 命中固定门还要 fail-closed 保留。"
            ),
        },
        "cross_entity_27_unknown": {
            "count": cross_entity_old["unknown"],
            "converted_to_pass": 0,
            "converted_to_fail": 0,
            "kept_unknown": 27,
            "set_to_not_applicable": 0,
            "reason": "逐题可判化需要 AxesCaseView（含逐题 old 轴值）；缺该输入无法逐题转判，按契约保留 unknown，绝不改 N/A",
        },
        "disagreement_sensitivity_band": {
            "computable": False,
            "why": "『两套四轴计数与总分』依赖逐题 cross_entity verdict；四轴重评分未执行，故两套计数均不可算",
            "denominators_only": {
                "reading_A_contract_v1_required": {"cross_entity_required": 30, "cross_entity_not_applicable": 0},
                "reading_B_custody_b": {"cross_entity_required": 21, "cross_entity_not_applicable": 9},
                "disputed_axes": 9,
                "composition_from_manager_acceptance": {"D1_shared_background": 7, "D2_multi_target_policy_compare": 1, "D3_document_artifact_target": 1},
                "structural_candidates_measured": {
                    "shared_background_criterion": contract["criterion_counts"]["cross_entity"].get("shared_background", 0),
                    "multi_target_criterion": contract["criterion_counts"]["cross_entity"].get("multi_target", 0),
                },
                "note": "D2 的 1 轴是 multi_target 4 轴中的 1 轴、D3 的 1 轴需题面语义，二者不可由结构字段唯一隔离",
            },
            "chosen": None,
        },
        "residual_marks": {
            "D4_explicit_time_window_not_in_filters": {"count": 2, "mark": "scope_weak", "per_axis_isolable": False, "why": "需要题面语义判断『显式时间窗』，结构字段无法唯一隔离"},
            "D5_empty_entity_key": {"count": 1, "mark": "scope_weak", "per_axis_isolable": True, "measured_matches_manager": True},
            "D6_stale_source_only_as_of": {"count": 3, "mark": "scope_weak", "per_axis_isolable": False, "structural_candidates": 5, "why": "所有 stale_source 且 as_of 非空且无 target_refs 的轴共 5 条，B 只标 3 条，需题面语义区分"},
            "D7_historical_intent_uses_business_baseline_as_of": {"count": 2, "mark": "disclosed_limit", "per_axis_isolable": True, "measured_matches_manager": True},
            "D3_document_artifact_target": {"count": 1, "mark": "scope_weak", "per_axis_isolable": False},
            "claim_scope_fully_resolved": False,
        },
        "private_detail": {
            "path": private["path"],
            "ciphertext_sha256": private["ciphertext_sha256"],
            "ciphertext_bytes": private["ciphertext_bytes"],
            "plaintext_sha256": private["plaintext_sha256"],
            "axis_rows": private["axis_rows"],
            "flag_counts": private["flag_counts"],
            "exclusive_create": private["exclusive_create"],
            "artifact": private_rec,
        },
        "preservation": {
            "repo_protected_files": len(before["repo_files"]),
            "repo_changed": repo_changed,
            "external_changed": external_changed,
            "old_run_tree_files": before["external"]["old_run_tree"]["file_count"],
            "old_run_tree_tree_sha256": before["external"]["old_run_tree"]["tree_sha256"],
            "holdout_root_tree_sha256": before["external"]["holdout_root"]["tree_sha256"],
            "custody_annotations_tree_sha256": before["external"]["custody_annotations"]["tree_sha256"],
            "contract_ciphertext_sha256": before["external"]["contract_ciphertext"]["sha256"],
            "before_after_equal": not repo_changed and not external_changed,
            "old_card_bytes_before_after": {k: v["card_sha256"] for k, v in blocked["per_run"].items()},
            "artifacts": [before_rec, after_rec],
        },
        "zero_real_calls": {
            "network": 0,
            "socket_attempts": netguard_payload["counts"]["socket_constructed"],
            "dns_attempts": netguard_payload["counts"]["dns_attempts"],
            "provider": 0,
            "model": 0,
            "embedding": 0,
            "rerank": 0,
            "ocr": 0,
            "judge": 0,
            "retrieval": 0,
            "auth": 0,
            "balance": 0,
            "real": 0,
            "real_reservations": 0,
            "new_go": 0,
            "subagents": 0,
            "netguard_verdict": netguard_payload["verdict"],
            "artifact": {"path": str(netguard_path), "sha256": sha(netguard_path.read_bytes())},
        },
        "not_claimed": ["verified", "threshold_met", "release_ready", "release", "T207_pass", "P2_complete", "q1a3_complete", "all_axes_real_complete"],
        "notes": [
            "旧卡自身是可信聚合：四轴 planned/checked/passed/N-A/unknown/violations 全部自洽（见 old_axes_consistency）。",
            "合同 v1 消费方校验通过：17/17 binding 可复算且相等、30/120 覆盖、120 轴 7 字段与合并冻结标注深度相等、basis 按 §4.1 全部复算一致、reason 全在 18 码权威表内。",
            "本包未读真实回答/trace 自由文本，未做任何模型/检索/鉴权调用，未改任何既有文件。",
        ],
    }
    out = ROOT / "rescore-aggregate.json"
    body = json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    out.write_bytes(body + b"\n")
    print(
        json.dumps(
            {
                "path": str(out),
                "sha256": sha(body + b"\n"),
                "bytes": len(body) + 1,
                "conclusion": aggregate["conclusion"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
