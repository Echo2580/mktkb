"""汇总独立验收证据，生成 c1-1/p3/review-aggregate.json（机器可读）。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
TARGET = HERE.parent / "review-aggregate.json"


def load(name: str) -> dict:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    contract = load("01-contract.json")
    chain = load("02-mock-chain.json")
    failclosed = load("03-failclosed.json")
    redlines = load("04-redlines.json")
    zero = load("05-zero-call.json")
    preservation = load("06-preservation.json")
    tests = load("07-test-quality.json")
    key_space = load("08-entity-key-space.json")
    public_fixture = load("08b-public-fixture-entity-shape.json")

    residuals = [
        {
            "id": "R-01",
            "severity": "medium",
            "topic": "class C / empty_set_candidate 口径与 M-C1P2-01 冲突",
            "detail": (
                "契约 §7.1 将『9 层 observed + 计数 0』直接称为空集充分条件，未要求 retrieval marker；"
                "读回校验接受 class C 载荷的 empty_set_candidate=true（实测 ACCEPTED）。"
            ),
            "evidence": ["out/04-redlines.json", "docs/evaluation/p2-hard-evidence-capture-v0_3.md:437"],
            "owner": "P3 契约文本 + 校验器；P4 必须按 M-C1P2-01 处理",
        },
        {
            "id": "R-02",
            "severity": "medium",
            "topic": "§8 运行期 id 白名单只查键名不查值",
            "detail": "entity_key 可携带 doc:<uuid>|unit:<uuid>（无 id 表头表格行）或 document|<uuid>，均通过校验。",
            "evidence": ["out/04-redlines.json"],
            "owner": "P3 实现",
        },
        {
            "id": "R-03",
            "severity": "medium",
            "topic": "entity_document_level 指标覆盖不足（M-C1P1-01 护栏失真）",
            "detail": "只数 entity_type=='document'；实测 8 行中 4 行为段落级（record_level=false、entity absent），计数为 0。",
            "evidence": ["out/04-redlines.json"],
            "owner": "P3 实现 + 公开摘要；P4 必须按 record_level/entity_code 判粒度",
        },
        {
            "id": "R-04",
            "severity": "medium",
            "topic": "目标侧与运行期 entity_key 键空间不同构",
            "detail": (
                "合同 v2 R-ENT-1（chunking._entity）产出名称型 item|门店|物品；运行期在公开 D01 上为 "
                "item|id:p01/p02；无 id 表头时为含 uuid 的 run-unstable 复合键。§7.2(3) 的等式匹配不可直接执行，"
                "最简单结果是系统性 no-match（cross_entity 继续 unknown）。"
            ),
            "evidence": ["out/08-entity-key-space.json", "out/08b-public-fixture-entity-shape.json"],
            "owner": "跨包（P1/P4）",
        },
        {
            "id": "R-05",
            "severity": "medium",
            "topic": "读回侧不强制 record_code == record_key",
            "detail": "把 record_code 改为 W99（record_key=W01）并重算摘要后校验通过；契约 §5.1 的赋值规则未被强制。",
            "evidence": ["out/04-redlines.json"],
            "owner": "P3 实现；P4 若依赖 record_code 需自行复算",
        },
        {
            "id": "R-06",
            "severity": "low",
            "topic": "entity_filters 的键名绕过运行期 id 检查",
            "detail": "entity_filters.document_id=… 通过校验，与 §8『任何位置一律拒绝』矛盾。",
            "evidence": ["out/04-redlines.json"],
            "owner": "P3 实现",
        },
        {
            "id": "R-07",
            "severity": "low",
            "topic": "凭证/会话值检测为形态启发式",
            "detail": "x-auth-header='sid=deadbeefcafe'、32-hex token 作 user_ref 均通过；契约只承诺『形似』检测。",
            "evidence": ["out/04-redlines.json"],
            "owner": "P3 实现（已文档化限制）",
        },
        {
            "id": "R-08",
            "severity": "low",
            "topic": "baseline 非冒充只靠自声明布尔",
            "detail": "declared_baseline_business_date == as_of 且 baseline_used_as_effective=false 通过校验，读回侧无法重算。",
            "evidence": ["out/04-redlines.json"],
            "owner": "P3 实现",
        },
        {
            "id": "R-09",
            "severity": "low",
            "topic": "snapshot_io_failed 可达但开发未测；4 个防御码只有 2 个文档注记",
            "detail": "io_failed 用文件占位 run 目录真实触发；readback_mismatch/run_binding_absent/run_binding_unexpected 正常不可达，故障注入可触发。",
            "evidence": ["out/03-failclosed.json"],
            "owner": "P3 测试/文档",
        },
        {
            "id": "R-10",
            "severity": "low",
            "topic": "测试套件无 49 码覆盖断言",
            "detail": "26 项测试无 skip/xfail/恒真、断言到字段级，但 45/49 码仅在 OBSERVED_CODES 记录，无覆盖断言。",
            "evidence": ["out/07-test-quality.json"],
            "owner": "P3 测试",
        },
        {
            "id": "R-11",
            "severity": "low",
            "topic": "builder 侧 empty_set_candidate=true 不可达",
            "detail": "all_use_layers_observed 要求 entity_inheritance 事件，而该事件必带非空 source_unit_id → 计数≥1；3 个合成回合均为 false。",
            "evidence": ["out/04-redlines.json", "out/02-mock-chain.json"],
            "owner": "P3 实现；P2/P4 不得期待该标记翻 true",
        },
    ]

    aggregate = {
        "schema_version": "c1p3-independent-review/v1",
        "date": "2026-11-14",
        "role": "C1-P3 全新独立验收（非开发、非经理）",
        "branch": preservation["git"]["branch"],
        "head": preservation["git"]["head"],
        "staged": preservation["git"]["staged_count"],
        "commits_created": 0,
        "verdict": "PASS_WITH_DISAGREEMENTS",
        "verdict_basis": {
            "taskbook_requirements": "3/3 成立（版本化契约、合成+Mock 落盘读回断言、fail-closed 固定码）",
            "red_lines": "M-C1P1-01 行级护栏生效；M-C1P2-01 在契约层留下 class C 口子（R-01）",
            "blocking_for_clean_pass": ["R-01", "R-02", "R-03", "R-04", "R-05"],
        },
        "items": {
            "contract_completeness": {
                "status": "PASS",
                "field_rows_generated": contract["field_rows_generated"],
                "field_rows_doc": contract["field_rows_doc"],
                "field_rows_identical": not contract["field_row_mismatch"]
                and not contract["field_missing_in_doc"]
                and not contract["field_extra_in_doc"],
                "required_fields": contract["required_generated"],
                "nullable_fields": contract["nullable_generated"],
                "code_families_module": contract["codes_module"],
                "code_families_doc": contract["codes_doc"],
                "code_families_identical": not contract["codes_missing_in_doc"]
                and not contract["codes_extra_in_doc"],
                "public_summary_keys": contract["public_summary_keys"],
                "use_layers": contract["use_layers"],
                "candidate_layers": contract["candidate_layers"],
            },
            "fail_closed": {
                "status": "PASS",
                "counterexamples": failclosed["counterexamples"],
                "defensive_experiments": failclosed["defensive_experiments"],
                "triggered_code_families": failclosed["triggered_families"],
                "untouched_code_families": failclosed["untouched_code_families"],
                "unexpected_accepts": failclosed["failures"],
                "defensive_reachability": {
                    "snapshot_io_failed": "reachable-but-untested",
                    "snapshot_readback_mismatch": "fault-injection-only",
                    "snapshot_run_binding_absent": "shadowed-by-frozen-validator",
                    "snapshot_run_binding_unexpected": "shadowed-by-frozen-validator",
                },
            },
            "mock_full_chain": {
                "status": "PASS",
                "turns": chain["turns"],
                "leaf_equality_total": chain["leaf_total"],
                "checks": len(chain["checks"]),
                "failed_checks": [item for item in chain["checks"] if not item["ok"]],
                "key_fields": {
                    "record_code": "W01 (doc S01 / sheet / row 2) on disk readback",
                    "as_of": "2026-09-01 via plan_observed",
                    "empty_use_input": "9 use + 3 candidate layers; nonempty declared; empty_set_candidate=false",
                },
                "adapter_outbound_attempts": chain["adapter_outbound_attempts"],
                "netguard": chain["netguard"]["counts"],
            },
            "collection_boundary": {
                "status": "PASS_WITH_RESIDUAL",
                "contract_forbids": [
                    "password hash",
                    "session token",
                    "HTTP auth header",
                    "runtime database row id",
                ],
                "refusals": redlines["collection_refusals"],
                "refused": sum(1 for item in redlines["collection_refusals"] if item["refused"]),
                "total": len(redlines["collection_refusals"]),
                "residual": "R-07（值级形态启发式）",
            },
            "preservation": {
                "status": "PASS",
                "c_freeze_12": preservation["c_freeze_12"]["item_count"],
                "c_freeze_mismatch": preservation["c_freeze_12"]["changed_count"],
                "tracked_modified": preservation["tracked_modified_15"]["item_count"],
                "tracked_modified_mismatch": preservation["tracked_modified_15"]["changed_count"],
                "q1a1_protected": preservation["q1a1_protected"]["item_count"],
                "q1a1_mismatch": preservation["q1a1_protected"]["changed_count"],
                "repo_files_28": preservation["repo_files_28"]["item_count"],
                "repo_files_mismatch": preservation["repo_files_28"]["changed_count"],
                "foreign_untracked_baseline": preservation["foreign_untracked"]["baseline_file_count"],
                "foreign_untracked_changed": preservation["foreign_untracked"]["changed_count"],
                "foreign_untracked_missing": preservation["foreign_untracked"]["missing_count"],
                "disallowed_added": preservation["foreign_untracked"]["disallowed_added"],
                "contract_v2_unchanged": preservation["contract_v2"]["unchanged"],
                "git": preservation["git"],
            },
            "zero_call": {
                "status": "PASS",
                "clean_external_attempts": zero["clean_phase"]["external_attempts"],
                "positive_control": {
                    "attempts": len(zero["positive_control"]["attempts"]),
                    "blocked": zero["positive_control"]["blocked_count"],
                    "external_attempts_recorded": zero["positive_control"]["external_attempts"],
                },
                "negative_control": zero["negative_control_uncleared"],
            },
            "test_quality": {
                "status": "PASS",
                "exit_code": tests["pytest"]["exit_code"],
                "test_functions": tests["static"]["test_functions"],
                "assert_statements": tests["static"]["assert_statements"],
                "tests_with_fixed_code_path_assertion": tests["static"]["tests_with_fixed_code_path_assertion"],
                "skip_xfail": tests["pytest"]["skipped_or_xfail_markers"],
                "always_true": tests["static"]["always_true_assertions"],
                "mock_or_patch": tests["static"]["mock_or_patch_usage"],
                "code_families_referenced": tests["static"]["code_families_referenced"],
                "coverage_assertion_for_49_codes": tests["static"]["has_coverage_assertion_for_49_codes"],
                "residual": "R-10",
            },
            "red_line_M_C1P1_01": {
                "status": "PASS_WITH_SEAMS",
                "paragraph_rows": redlines["redline_M_C1P1_01"]["paragraph_rows"],
                "record_level_rows": redlines["redline_M_C1P1_01"]["record_level_rows"],
                "paragraph_rows_entity_matchable": redlines["redline_M_C1P1_01"]["paragraph_rows_entity_matchable"],
                "summary_entity_document_level": redlines["redline_M_C1P1_01"]["summary_entity_document_level"],
                "public_summary_not_record_level_count": redlines["redline_M_C1P1_01"]["public_summary_not_record_level_count"],
                "naive_document_level_matches": redlines["redline_M_C1P1_01"]["naive_document_level_matches"],
                "entity_key_runtime_id_rows": redlines["redline_M_C1P1_01"]["entity_key_runtime_id_rows"],
                "seams": ["R-02", "R-03", "R-04"],
            },
            "red_line_M_C1P2_01": {
                "status": "PASS_WITH_SEAM",
                "genuine_class_c_turns": redlines["redline_M_C1P2_01"]["genuine_class_c_turns"],
                "class_c_payload": redlines["redline_M_C1P2_01"]["class_c_payload_validation"]["outcome"],
                "class_c_flags": redlines["redline_M_C1P2_01"]["class_c_flags"],
                "builder_empty_attempts": redlines["redline_M_C1P2_01"]["builder_empty_attempts"],
                "seams": ["R-01", "R-11"],
            },
            "entity_key_space": {
                "status": "MISMATCH",
                "target_side_key": key_space["target_side_computed"]["entity_key"],
                "runtime_side_keys": key_space["runtime_side_keys"],
                "public_fixture_runtime_keys": public_fixture["id_style_runtime_keys"],
                "residual": "R-04",
            },
        },
        "residuals": residuals,
        "self_computed_evidence": {
            "probe_scripts": sorted(path.name for path in HERE.glob("*.py")),
            "out_files": sorted(path.name for path in OUT.glob("*.json")),
            "review_sha256": sha256(HERE.parent / "independent-review.md"),
        },
        "not_claimed": [
            "P3 质量通过",
            "T207 通过",
            "release/threshold/baseline 批准",
            "C1-2 授权",
            "P2 完成",
            "真实 H2 采集行为",
        ],
    }
    TARGET.write_text(json.dumps(aggregate, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: aggregate["items"][k]["status"] for k in aggregate["items"]}, ensure_ascii=False, indent=1))
    print("verdict", aggregate["verdict"], "residuals", len(residuals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
