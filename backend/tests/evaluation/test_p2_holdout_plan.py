"""P2-T207-FIX-A F1：H2 受限计划生成器（合成元数据；不触真实 H2）。

被测契约：
- 只接受 {schema_version, dataset_version, cases[{case_id, turns}]}，题干/答案字段一律拒绝；
- 与 H2 manifest 交叉校验：题数/总轮数/最大轮数/turn_histogram/multi_turn 分层；
- 每回合 4 项（query_embedding/rerank/query_expansion/answer 各 1）+ 1 个 index_embedding
  项请求数 = B；无 OCR 项；生成物必须能过 P2RunPlan 严格校验且 sha 稳定；
- 计划文件不得落在工作区内；CLI 的 stdout 只回 sha 与计数，不回 case_id。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mktkb.evaluation import cli as cli_module
from mktkb.evaluation import p2_holdout_plan as h2
from mktkb.evaluation.p2_contracts import P2RunPlan

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs" / "evaluation" / "p2-holdout-v2.manifest.json"
CREATED_UTC = "2026-11-11T08:30:00+08:00"


def synthetic_cases() -> list[tuple[str, int]]:
    """30 题 / 36 回合的结构副本（case_id 全是合成名，不来自 H2）。"""
    cases = [(f"syn-one-{index:02d}", 1) for index in range(25)]
    cases += [(f"syn-two-{index:02d}", 2) for index in range(4)]
    cases.append(("syn-three-00", 3))
    return cases


def synthetic_metadata(*, cases=None, dataset_version: str = "P2-HOLDOUT-v2") -> dict:
    chosen = synthetic_cases() if cases is None else cases
    return {
        "schema_version": h2.H2_CASES_METADATA_SCHEMA_VERSION,
        "dataset_version": dataset_version,
        "cases": [{"case_id": case_id, "turns": turns} for case_id, turns in chosen],
    }


def test_crosscheck_matches_the_repo_manifest_and_builds_a_valid_plan() -> None:
    manifest = h2.load_holdout_manifest(MANIFEST)
    dataset_version, cases = h2.parse_cases_metadata(synthetic_metadata())
    crosschecked = h2.crosscheck_metadata(dataset_version, cases, manifest)
    assert crosschecked["cases"] == 30
    assert crosschecked["total_turns"] == 36
    assert crosschecked["turn_histogram"] == {"1": 25, "2": 4, "3": 1}
    assert crosschecked["multi_turn_cases"] == manifest.strata["multi_turn"] == 5

    plan = h2.build_holdout_plan(
        cases=cases,
        ingest_batches=68,
        plan_id="P2-H2-SYNTHETIC",
        plan_version="v0.1",
        created_utc=CREATED_UTC,
    )
    # 生成物必须是合法 P2RunPlan（再走一次 from_dict 证明可被 runner 读回）。
    again = P2RunPlan.from_dict(plan.as_dict())
    assert again.plan_sha256 == plan.plan_sha256
    assert plan.case_count == 31  # 30 题 + INGEST 伪 case
    assert plan.turn_count == 37  # 36 回合 + INGEST 的 turn=1
    assert len(plan.items) == 1 + 36 * 4
    assert plan.page_count == 0, "H2 不含 OCR 页，计划里不得出现 ocr 项"
    assert plan.requests_by_operation() == {
        "index_embedding": 68,
        "query_embedding": 36,
        "rerank": 36,
        "query_expansion": 36,
        "answer": 36,
    }
    assert plan.total_requests == 144 + 68
    index_items = [item for item in plan.items if item.operation == "index_embedding"]
    assert len(index_items) == 1 and index_items[0].requests == 68
    per_turn = {}
    for item in plan.items:
        if item.operation == "index_embedding":
            continue
        per_turn.setdefault((item.case_id, item.turn), set()).add(item.operation)
    assert len(per_turn) == 36
    assert all(operations == {"query_embedding", "rerank", "query_expansion", "answer"} for operations in per_turn.values())
    assert plan.worst_case_cny == pytest.approx(1.731328)
    assert plan.max_requests == 1100


def test_crosscheck_rejects_metadata_that_does_not_match_the_manifest() -> None:
    manifest = h2.load_holdout_manifest(MANIFEST)
    short = synthetic_cases()[:-1]
    dataset_version, cases = h2.parse_cases_metadata(synthetic_metadata(cases=short))
    with pytest.raises(h2.HoldoutPlanError) as excinfo:
        h2.crosscheck_metadata(dataset_version, cases, manifest)
    assert excinfo.value.code == "case_count_mismatch"

    wrong_turns = synthetic_cases()
    wrong_turns[0] = (wrong_turns[0][0], 2)
    dataset_version, cases = h2.parse_cases_metadata(synthetic_metadata(cases=wrong_turns))
    with pytest.raises(h2.HoldoutPlanError) as excinfo:
        h2.crosscheck_metadata(dataset_version, cases, manifest)
    assert excinfo.value.code in {"turn_histogram_mismatch", "total_turns_mismatch"}

    dataset_version, cases = h2.parse_cases_metadata(
        synthetic_metadata(dataset_version="P2-HOLDOUT-v1")
    )
    with pytest.raises(h2.HoldoutPlanError) as excinfo:
        h2.crosscheck_metadata(dataset_version, cases, manifest)
    assert excinfo.value.code == "dataset_version_mismatch"


def test_metadata_schema_refuses_question_or_answer_fields() -> None:
    payload = synthetic_metadata()
    payload["cases"][0]["question"] = "不许出现在元数据里"
    with pytest.raises(h2.HoldoutPlanError) as excinfo:
        h2.parse_cases_metadata(payload)
    assert excinfo.value.code == "metadata_case_unknown_field"

    dup = synthetic_metadata()
    dup["cases"][1]["case_id"] = dup["cases"][0]["case_id"]
    with pytest.raises(h2.HoldoutPlanError) as excinfo:
        h2.parse_cases_metadata(dup)
    assert excinfo.value.code == "metadata_case_id_duplicate"

    bad = synthetic_metadata(cases=[("bad id with space", 1)])
    with pytest.raises(h2.HoldoutPlanError) as excinfo:
        h2.parse_cases_metadata(bad)
    assert excinfo.value.code == "metadata_case_id_invalid"


def test_ingest_batches_and_workspace_guard_are_enforced() -> None:
    cases = synthetic_cases()
    with pytest.raises(h2.HoldoutPlanError) as excinfo:
        h2.build_holdout_plan(
            cases=cases,
            ingest_batches=0,
            plan_id="P2-H2-SYNTHETIC",
            plan_version="v0.1",
            created_utc=CREATED_UTC,
        )
    assert excinfo.value.code == "ingest_batches_invalid"
    with pytest.raises(h2.HoldoutPlanError) as excinfo:
        h2.build_holdout_plan(
            cases=cases,
            ingest_batches=h2.H2_MAX_INGEST_BATCHES + 1,
            plan_id="P2-H2-SYNTHETIC",
            plan_version="v0.1",
            created_utc=CREATED_UTC,
        )
    assert excinfo.value.code == "ingest_batches_over_envelope"
    with pytest.raises(h2.HoldoutPlanError) as excinfo:
        h2.assert_outside_workspace(ROOT / "docs" / "h2-plan.json", what="H2 计划文件")
    assert excinfo.value.code == "plan_out_inside_workspace"


def test_cli_prints_only_sha_and_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # CLI 的"工作区外"闸门用模块常量判定；测试里把它挪到 tmp 的父层，闸门逻辑仍然生效。
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(h2, "PROJECT_ROOT", tmp_path / "workspace")
    metadata_path = outside / "metadata.json"
    metadata_path.write_text(json.dumps(synthetic_metadata(), ensure_ascii=False), encoding="utf-8")
    plan_out = outside / "h2-plan.json"
    code = cli_module.main(
        [
            "p2-h2-plan",
            "--cases-metadata",
            str(metadata_path),
            "--holdout-manifest",
            str(MANIFEST),
            "--ingest-batches",
            "68",
            "--plan-out",
            str(plan_out),
            "--plan-id",
            "P2-H2-SYNTHETIC",
            "--created-utc",
            CREATED_UTC,
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["cases"] == 30 and payload["turns"] == 36
    assert payload["total_requests"] == 212
    assert len(payload["plan_sha256"]) == 64
    assert plan_out.is_file()
    # stdout 不得出现任何合成 case_id（生成的计划文件里必然有，那是工作区外文件）。
    for case_id, _turns in synthetic_cases():
        assert case_id not in captured.out
        assert case_id not in captured.err
