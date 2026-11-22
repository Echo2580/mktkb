"""T301 隔离环境验收测试：正常入口生成样本 → 独立复算 → Trace 探针，三项对账一致。

运行方式（在 backend/ 目录下）：
    ..\\.venv\\Scripts\\python.exe -B -m pytest -c pyproject.toml \
        ../docs/reports/OBS-EVAL/P3/T301-isolated/tests/test_t301_isolated.py
"""

from __future__ import annotations

import t301_generate_samples as gen
import t301_recompute as recompute
import t301_trace_probe as probe

EXPECTED_KINDS = {
    "S01": "answer", "S02": "answer", "S03": "not_found", "S04": "clarification",
    "S05": "conflict", "S06": "answer", "S07": "answer", "S08": "service_error",
    "S09": "knowledge_changed", "S10": "answer", "S11": "answer", "S12": "answer",
    "S15": "answer", "S17": "answer", "S18": "answer",
}


def test_t301_isolated_acceptance_matrix_and_recompute() -> None:
    matrix = gen.main()
    results = recompute.compute()
    probe_result = probe.compute()

    samples = {s["sample_id"]: s for s in matrix["samples"]}

    # 场景覆盖：期望结果类型与实测一致
    for sid, expected_kind in EXPECTED_KINDS.items():
        assert samples[sid]["response_kind"] == expected_kind, (
            f"{sid} kind={samples[sid]['response_kind']} expected={expected_kind}"
        )

    # 受控样本标注
    assert samples["S16"]["source"] == "controlled"
    assert samples["S19"]["source"] == "controlled"
    assert samples["S17"]["source"] == "controlled"
    assert samples["S18"]["source"] == "controlled"

    # 独立复算全部对账一致
    inconsistent = [c for c in results["expected_vs_actual"]["checks"] if not c["consistent"]]
    assert inconsistent == [], f"复算不一致：{inconsistent}"

    # 六类分布
    six = results["six_distribution"]
    assert six == {
        "answer": 8, "clarification": 1, "not_found": 1, "conflict": 1,
        "service_error": 1, "knowledge_changed": 1,
    }

    # 午夜边界归属
    for item in results["midnight_boundary"]:
        assert item["consistent"], item

    # 已删除会话两侧排除
    assert all(item["consistent"] for item in results["deleted_conversation"])

    # 引用去重：同文档多行只计一次；冲突行剔除出最终计数
    citations = results["citations"]
    assert citations["document_dedup_pairs"] == 6
    assert citations["version_dedup_pairs"] == 6
    assert citations["conflict_message_rows_excluded"] == 2

    # Trace 覆盖率状态
    coverage = results["trace_coverage"]
    assert coverage["completed_denominator"] == 13
    assert coverage["covered"] == 10
    assert coverage["states"] == {"covered": 10, "disabled": 1, "untracked": 2}
    assert len(coverage["replay_traces"]) == 1

    # 探针：三条执行路径均被观测到；重放配对；关闭态无 Trace
    inventory = probe_result["path_span_inventory"]
    assert {"rag", "legacy", "legacy_with_rag_candidates"} <= set(inventory)
    assert len(probe_result["replay"]["pairs"]) == 1
    replay_pair = probe_result["replay"]["pairs"][0]
    assert replay_pair["replay_span_count"] == 0
    assert replay_pair["original_trace_ids"]
    disabled = probe_result["disabled_state"]
    assert len(disabled) == 1
    assert disabled[0]["trace_row_found"] is False
    assert disabled[0]["trace_header_present"] is False

    # 旧版引用字段可展示
    fields = probe_result["old_version_citation_fields"]["field_keys"]
    assert {"document_name", "version_number", "status", "locator", "published_at"} <= set(fields)
