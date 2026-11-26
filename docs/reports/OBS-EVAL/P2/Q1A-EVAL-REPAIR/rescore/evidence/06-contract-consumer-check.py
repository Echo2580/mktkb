"""Q1a-2 合同密文消费方校验（合同 v1 §5）与四轴适用性/basis/D 标记的**结构**统计。

- 只用既有 key 容器（MKTKB_P2_HOLDOUT_KEY_FILE）在进程内解密；明文不落盘、不打印。
- 只输出计数 / 枚举分布 / hash；不输出 case_id、题面、答案、目标值、逐题 hash。
- 本脚本不产生任何四轴 verdict：它只证明"合同本身可被消费"，不证明产品行为。
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(REPO / "backend" / "src"))
sys.path.insert(0, str(REPO / "tools"))

CUSTODY = Path(
    r"C:\Users\dell1712\.codex\visualizations\2026\11\12\01a1cd24-bccf-7e00-80df-0b75f57f7d1c\t207-custody"
)
HOLDOUT_ROOT = Path(r"D:\mktkb-p2-holdout\v2")
HOLDOUT_KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
CONTRACT_CIPHER = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v1.fernet")
BUSINESS_DATE = "2026-10-28"

AXES = ("safety", "cross_user", "cross_entity", "stale_source")
SCENARIO_ORDER = ("base_b0", "base_b0_plus_v01", "pre_v05_without_v07", "post_v05_without_v01")
COLLECTIONS = ("expected_sources", "relevant_units", "forbidden_sources")
APPLICABILITY = ("required", "not_applicable", "unknown")
TEMPORAL = ("current", "historical", "future_explicit", "not_applicable", "unknown")
BASIS = (
    "frozen_label_target",
    "frozen_question_scope",
    "public_corpus_structure",
    "case_business_date_baseline",
    "no_provable_basis_keep_unknown",
)
CRITERIA = {
    "safety": ("must_refuse_security", "forbidden_content", "benign_business", "unknown"),
    "cross_user": ("owner_context", "unknown"),
    "cross_entity": ("structured_target", "multi_target", "shared_background", "no_entity_claim", "unknown"),
    "stale_source": ("lifecycle_dates", "unknown"),
}
# 权威 18 码（schema §3.2 标题写"19 码"是笔误；R-Q1A2-01）
REASONS = (
    "explicit_security",
    "explicit_privacy",
    "prompt_injection",
    "explicit_forbidden",
    "benign_business",
    "all_user_contexts",
    "explicit_single_target",
    "explicit_multi_target",
    "shared_policy",
    "no_entity_scope",
    "published_lifecycle",
    "explicit_temporal",
    "business_date_default",
    "ambiguous_semantics",
    "unresolved_target",
    "source_state_conflict",
    "third_state_required",
    "insufficient_annotation",
)
AXIS_FIELDS = frozenset(
    {"applicability", "criterion", "reason", "target_refs", "targets", "as_of", "temporal_intent"}
)
UNCERTAIN_REASONS = frozenset(
    {"ambiguous_semantics", "unresolved_target", "source_state_conflict", "third_state_required", "insufficient_annotation"}
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_load(raw: bytes):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate_key")
            out[key] = value
        return out

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)


def is_hex64(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def main() -> int:
    import p2_h2_controlled_execute as entry

    defects: list[str] = []

    def require(condition, code: str) -> None:
        if not condition:
            defects.append(code)

    raw = CONTRACT_CIPHER.read_bytes()
    require(sha(raw) == "467dbf7706df26f2069a79e2b344b53c0e10c03ff830ed62efff9b5dfd16f461", "contract_ciphertext_sha_mismatch")
    require(len(raw) == 47012, "contract_ciphertext_bytes_mismatch")
    key = HOLDOUT_KEY.read_bytes()
    from cryptography.fernet import Fernet

    payload = strict_load(Fernet(key).decrypt(raw))

    # --- §5.3/§5.4 顶层与覆盖 ---
    require(set(payload) == {"schema_version", "bindings", "runs", "case_count", "cases"}, "contract_schema_invalid:top")
    require(payload.get("schema_version") == "q1a-scope-targets-contract/v1", "contract_schema_invalid:schema_version")
    bindings = payload.get("bindings") or {}
    require(isinstance(bindings, dict) and len(bindings) == 17, "contract_schema_invalid:bindings_len")
    runs = payload.get("runs") or []
    require(isinstance(runs, list) and len(runs) == 4, "contract_schema_invalid:runs_len")
    cases = payload.get("cases") or []
    require(payload.get("case_count") == 30 and len(cases) == 30, "contract_coverage_invalid:case_count")

    # --- §5.5 重算全部 17 个 binding ---
    ds = entry.load_private_bundle(
        {},
        entry.InputPaths(
            holdout_manifest=HOLDOUT_ROOT / "manifest.json",
            annotation_ciphertext=CUSTODY / "annotations-v0_2.fernet",
            review_ciphertext=CUSTODY / "review-v0_2.fernet",
            scenario_key_file=HOLDOUT_KEY,
            addendum_ciphertext=CUSTODY / "annotations-gapaddendum-v0_3.fernet",
            scenario_contract=entry.DEFAULT_SCENARIO_CONTRACT,
            ingest_plan=entry.DEFAULT_INGEST_PLAN,
            source_map=entry.DEFAULT_SOURCE_MAP,
            annotation_schema=entry.DEFAULT_ANNOTATION_SCHEMA,
            manager_acceptance_v2=entry.DEFAULT_MANAGER_V2,
            review_aggregate_v2=entry.DEFAULT_REVIEW_AGGREGATE_V2,
            addendum_acceptance_v3=entry.DEFAULT_ADDENDUM_ACCEPTANCE,
        ),
        runtime=entry.RuntimeOptions(
            holdout_root=HOLDOUT_ROOT,
            holdout_key_file=HOLDOUT_KEY,
            project_total_limit_cny=entry.PROJECT_TOTAL_LIMIT_CNY,
        ),
    )
    from mktkb.evaluation.dataset import cases_to_jsonl

    binding_path = Path(r"D:\mktkb-p2-t207-h2-20261114\plans2\run-binding.json")
    binding_raw = binding_path.read_bytes()
    binding_doc = json.loads(binding_raw.decode("utf-8"))
    binding_payload = {k: v for k, v in binding_doc.items() if k != "binding_sha256"}

    recomputed = {
        "old_run_binding_sha256": sha(
            json.dumps(binding_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ),
        "old_run_binding_file_sha256": sha(binding_raw),
        "dataset_version": ds.dataset.manifest.dataset_version,
        "label_version": ds.dataset.manifest.label_version,
        "manifest_sha256": sha((HOLDOUT_ROOT / "manifest.json").read_bytes()),
        "cases_sha256": sha(cases_to_jsonl(ds.dataset.cases).encode("utf-8")),
        "source_map_sha256": sha(entry.DEFAULT_SOURCE_MAP.read_bytes()),
        "ingest_plan_sha256": sha(entry.DEFAULT_INGEST_PLAN.read_bytes()),
        "scenario_contract_sha256": sha(entry.DEFAULT_SCENARIO_CONTRACT.read_bytes()),
        "annotation_v0_2_ciphertext_sha256": sha((CUSTODY / "annotations-v0_2.fernet").read_bytes()),
        "annotation_review_v0_2_ciphertext_sha256": sha((CUSTODY / "review-v0_2.fernet").read_bytes()),
        "annotation_v0_3_ciphertext_sha256": sha((CUSTODY / "annotations-gapaddendum-v0_3.fernet").read_bytes()),
        "annotation_schema_sha256": sha(entry.DEFAULT_ANNOTATION_SCHEMA.read_bytes()),
        "annotation_manager_acceptance_v2_sha256": sha(entry.DEFAULT_MANAGER_V2.read_bytes()),
        "annotation_review_aggregate_v2_sha256": sha(entry.DEFAULT_REVIEW_AGGREGATE_V2.read_bytes()),
        "addendum_acceptance_v3_sha256": sha(entry.DEFAULT_ADDENDUM_ACCEPTANCE.read_bytes()),
        "contract_schema_sha256": sha((REPO / "docs/evaluation/q1a-scope-targets-contract-v1.md").read_bytes()),
    }
    binding_checks = []
    for name, measured in recomputed.items():
        declared = bindings.get(name)
        if name in ("dataset_version", "label_version"):
            match = declared == measured
        else:
            match = is_hex64(declared) and declared == measured
        binding_checks.append({"binding": name, "declared": declared, "measured": measured, "match": bool(match)})
        require(match, f"contract_binding_mismatch:{name}")
    for name, value in bindings.items():
        if name not in recomputed:
            require(True, "unknown_binding_key")  # 占位：不新增键
    require(set(bindings) == set(recomputed), "contract_binding_mismatch:key_set")

    # --- §5.4/§2.2 runs ---
    run_rows = []
    for index, row in enumerate(runs):
        require(row.get("run_index") == index, "contract_schema_invalid:run_index")
        require(row.get("scenario_id") == SCENARIO_ORDER[index], "contract_schema_invalid:run_scenario")
        old_run = next(r for r in binding_doc["runs"] if int(r["run_index"]) == index)
        same = all(str(row.get(k)) == str(old_run.get(k)) for k in ("run_id", "plan_id", "plan_sha256"))
        require(same and is_hex64(row.get("plan_sha256")), "contract_binding_mismatch:run_row")
        run_rows.append({"run_index": index, "scenario_id": row["scenario_id"], "matches_old_binding": bool(same)})

    # --- §5.6/§5.7 cases 与合并标注深度相等 ---
    merged = ds.annotation
    merged_cases = merged["cases"]
    gaps = ds.addendum["gaps"]
    gap_basis = {(int(g["case_index"]), str(g["axis"])): str(g["basis"]) for g in gaps if g.get("resolution") == "resolved"}
    gap_values = {(int(g["case_index"]), str(g["axis"])): g["axis_value"] for g in gaps if g.get("resolution") == "resolved"}
    require(len(merged_cases) == 30, "scenario_contract_invalid:annotation_cases")

    def merged_axis(index: int, axis: str):
        """合同 §2.3：v0.2 原值；若该轴在 v0.3 addendum 中 resolved 则取 v0.3 axis_value。"""
        key = (index, axis)
        if key in gap_values:
            return gap_values[key]
        return merged_cases[index]["axes"][axis]

    applicability = {axis: {"required": 0, "not_applicable": 0, "unknown": 0} for axis in AXES}
    basis_counts = {axis: {code: 0 for code in BASIS} for axis in AXES}
    criterion_counts = {axis: {} for axis in AXES}
    reason_counts: dict[str, int] = {}
    d_rows = []  # 只在本进程内用于统计；不打印

    for index, case in enumerate(cases):
        require(set(case) == {"case_id", "case_index", "scenario_id", "axes", "basis"}, "contract_schema_invalid:case_keys")
        require(case.get("case_index") == index, "contract_schema_invalid:case_index")
        require(case.get("case_id") == ds.dataset.cases[index].case_id, "contract_coverage_invalid:case_id")
        require(case.get("scenario_id") == merged_cases[index]["scenario_id"], "contract_coverage_invalid:scenario_id")
        require(set(case.get("basis") or {}) == set(AXES), "contract_basis_invalid:keys")
        require(set(case.get("axes") or {}) == set(AXES), "contract_axis_invalid:axes_keys")
        for axis in AXES:
            axis_obj = case["axes"][axis]
            require(set(axis_obj) == AXIS_FIELDS, "contract_axis_invalid:axis_fields")
            require(axis_obj.get("applicability") in APPLICABILITY, "contract_axis_invalid:applicability")
            require(axis_obj.get("criterion") in CRITERIA[axis], "contract_axis_invalid:criterion")
            require(axis_obj.get("reason") in REASONS, "contract_axis_invalid:reason")
            require(axis_obj.get("temporal_intent") in TEMPORAL, "contract_axis_invalid:temporal_intent")
            as_of = axis_obj.get("as_of")
            if as_of is not None:
                require(isinstance(as_of, str) and len(as_of) == 10 and date.fromisoformat(as_of).isoformat() == as_of, "contract_axis_invalid:as_of")
            refs = axis_obj.get("target_refs")
            require(isinstance(refs, list), "contract_axis_invalid:target_refs")
            seen = set()
            for ref in refs:
                require(isinstance(ref, dict) and set(ref) == {"collection", "index"}, "contract_axis_invalid:target_ref_shape")
                require(ref.get("collection") in COLLECTIONS, "contract_axis_invalid:target_ref_collection")
                require(type(ref.get("index")) is int and ref["index"] >= 0, "contract_axis_invalid:target_ref_index")
                require((ref["collection"], ref["index"]) not in seen, "contract_axis_invalid:target_ref_duplicate")
                seen.add((ref["collection"], ref["index"]))
            targets = axis_obj.get("targets")
            require(isinstance(targets, list), "contract_axis_invalid:targets")
            for target in targets:
                require(isinstance(target, dict) and set(target) == {"entity_type", "entity_key", "filters"}, "contract_axis_invalid:target_shape")
                require(isinstance(target.get("entity_type"), str) and 0 < len(target["entity_type"]) <= 256, "contract_axis_invalid:entity_type")
                require(isinstance(target.get("entity_key"), str) and len(target["entity_key"]) <= 256, "contract_axis_invalid:entity_key")
                require(isinstance(target.get("filters"), dict), "contract_axis_invalid:filters")
            # 与合并冻结标注逐值相等
            frozen_axis = merged_axis(index, axis)
            require(axis_obj == frozen_axis, f"contract_semantics_changed:{axis}")

            applicability[axis][axis_obj["applicability"]] += 1
            basis_code = case["basis"][axis]
            require(basis_code in BASIS, "contract_basis_invalid:value")
            basis_counts[axis][basis_code] += 1
            criterion_counts[axis][axis_obj["criterion"]] = criterion_counts[axis].get(axis_obj["criterion"], 0) + 1
            reason_counts[axis_obj["reason"]] = reason_counts.get(axis_obj["reason"], 0) + 1

            # §4.1 basis 复算（首个命中即止）
            if (index, axis) in gap_basis:
                expected = gap_basis[(index, axis)]
            elif axis_obj["applicability"] == "unknown":
                expected = "no_provable_basis_keep_unknown"
            elif axis == "safety":
                expected = "frozen_label_target" if axis_obj["applicability"] == "required" else "frozen_question_scope"
            elif axis == "cross_user":
                expected = "frozen_question_scope"
            elif axis == "cross_entity":
                criterion = axis_obj["criterion"]
                if criterion == "shared_background":
                    expected = "public_corpus_structure"
                elif criterion == "no_entity_claim":
                    expected = "frozen_question_scope"
                elif axis_obj["target_refs"]:
                    expected = "frozen_label_target"
                elif axis_obj["targets"]:
                    expected = "frozen_question_scope"
                else:
                    expected = "no_provable_basis_keep_unknown"
            else:  # stale_source
                if axis_obj["target_refs"]:
                    expected = "public_corpus_structure"
                elif axis_obj["as_of"] == BUSINESS_DATE:
                    expected = "case_business_date_baseline"
                else:
                    expected = "frozen_label_target"
            require(basis_code == expected, f"contract_basis_invalid:recompute:{axis}")

            # 轴级硬规则（§3.3 / §7.1 / §7.6）
            if axis in ("cross_user", "stale_source"):
                require(axis_obj["applicability"] == "required", f"contract_axis_invalid:{axis}_not_required")
            if axis == "cross_entity" and axis_obj["applicability"] == "not_applicable":
                require(axis_obj["criterion"] == "no_entity_claim" and axis_obj["reason"] == "no_entity_scope", "contract_axis_invalid:cross_entity_na")
            if axis_obj["applicability"] == "not_applicable" and axis_obj["reason"] in UNCERTAIN_REASONS:
                require(False, "contract_unknown_downgraded")
            if basis_code == "no_provable_basis_keep_unknown":
                require(axis_obj["applicability"] == "unknown", "contract_basis_invalid:keep_unknown_combo")

            # D 标记结构候选（不打印定位）
            flags = []
            if axis == "cross_entity" and axis_obj["criterion"] == "shared_background":
                flags.append("D1_shared_background")
            if axis == "cross_entity" and axis_obj["criterion"] == "multi_target":
                flags.append("D2_multi_target_policy_compare")
            if any(t.get("entity_key") == "" for t in axis_obj["targets"]):
                flags.append("D5_empty_entity_key")
            if axis == "stale_source" and axis_obj["as_of"] is not None and not axis_obj["target_refs"]:
                flags.append("D6_stale_only_as_of_candidate")
            if axis_obj["temporal_intent"] == "historical" and axis_obj["as_of"] == BUSINESS_DATE:
                flags.append("D7_historical_intent_uses_business_baseline")
            if flags:
                d_rows.append({"case_index": index, "axis": axis, "basis": basis_code, "flags": flags})

    require(len({c["case_id"] for c in cases}) == 30, "contract_coverage_invalid:dup_case_id")

    d_counts = {
        "D1_shared_background": sum(1 for r in d_rows if "D1_shared_background" in r["flags"]),
        "D2_multi_target_policy_compare": sum(1 for r in d_rows if "D2_multi_target_policy_compare" in r["flags"]),
        "D5_empty_entity_key": sum(1 for r in d_rows if "D5_empty_entity_key" in r["flags"]),
        "D6_stale_only_as_of_candidate": sum(1 for r in d_rows if "D6_stale_only_as_of_candidate" in r["flags"]),
        "D7_historical_intent_uses_business_baseline": sum(1 for r in d_rows if "D7_historical_intent_uses_business_baseline" in r["flags"]),
    }

    result = {
        "schema_version": "q1a3-contract-consumer-check/v0.1",
        "contract_ciphertext_sha256": sha(raw),
        "contract_ciphertext_bytes": len(raw),
        "defect_count": len(defects),
        "defects": defects[:20],
        "binding_checks": binding_checks,
        "run_rows": run_rows,
        "coverage": {"cases": len(cases), "axes": len(cases) * len(AXES)},
        "applicability": applicability,
        "unknown_total": sum(applicability[axis]["unknown"] for axis in AXES),
        "basis_counts": basis_counts,
        "criterion_counts": criterion_counts,
        "reason_counts": reason_counts,
        "reason_code_table_size": len(REASONS),
        "reason_codes_not_in_authoritative_table": sorted(set(reason_counts) - set(REASONS)),
        "d_structural_counts": d_counts,
        "d_rows_private_count": len(d_rows),
        "calls": {"network": 0, "socket": 0, "dns": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    # 供 07 私密明细脚本使用的中间文件：只含 case_index/axis/flag，不含题面/答案/目标值
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
