"""P2-T207-FIX-A F3：N/C 只读转换器与 run case 文件（零真实调用）。

断言的是"转换规则可审、逐字段不漂移"：N01-N08 / C01-C06 的 suite/kind/值/来源/forbidden
必须能逐项回溯到 fixtures/acceptance/questions.json 的同一条目；U01 的镜像必须与
backend/tests/acceptance/test_t09_mutation.py 的 U01 断言同源；R1/R2/R3 的拆分与
PM 决定（R1 52 回合 / R2 2 / R3 1；Q01 只在 R1）逐项对齐。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mktkb.evaluation.dataset import validate_case
from mktkb.evaluation.p2_public_cases import (
    ACCEPTANCE_QUESTIONS_PATH,
    B0_DATASET_PATH,
    PublicCaseError,
    acceptance_case,
    acceptance_label_version,
    load_acceptance_cases,
    load_b0_cases,
    run_case_sets,
    u01_case,
    write_run_case_files,
)
from mktkb.evaluation.p2_scoring import P2_B0_IDS, P2_BOUNDARY_IDS, P2_NEGATIVE_IDS

ROOT = Path(__file__).resolve().parents[3]
MUTATION_TEST = ROOT / "backend" / "tests" / "acceptance" / "test_t09_mutation.py"


def _questions() -> dict:
    return json.loads(ACCEPTANCE_QUESTIONS_PATH.read_text(encoding="utf-8"))


def _item(case_id: str) -> dict:
    return next(row for row in _questions()["questions"] if row["id"] == case_id)


def test_every_nc_case_maps_back_to_the_frozen_fixture_field_by_field() -> None:
    cases = load_acceptance_cases()
    assert tuple(case.case_id for case in cases) == tuple(P2_NEGATIVE_IDS) + tuple(P2_BOUNDARY_IDS)
    assert len(cases) == 14
    for case in cases:
        validate_case(case)
        item = _item(case.case_id)
        scenario = item["scenario"]
        assert case.question == item["question"]
        assert case.expected_kind == scenario["expected_kind"]
        assert case.split == "dev" and case.business_date == "2026-10-28"
        assert case.requires_ocr is False
        assert case.reference_answer == ""
        assert case.labeler == "acceptance-fixture"
        assert case.label_version == acceptance_label_version()
        assert item["id"] in case.notes and item["group"] in case.notes
        if case.expected_kind in {"answer", "conflict"}:
            assert list(case.expected_values) == list(item["expected_values"])
        else:
            # any-of 措辞在 CaseSpec 里表达不了：值置空，措辞进 notes。**T207-FIX-A-R1 更正**：
            # 这几行因此比验收口径**更松**（只判 expected_kind），不是更严——口径缺口已在模块头如实记录，
            # 不改冻结判据；下面再把「哪些题受影响」显式钉住，避免被读成产品通过。
            assert case.expected_values == ()
            accepted = "|".join(item["expected_values"])
            assert f"accepted_wording(any-of,not-scored)={accepted}" in case.notes
        # not_found 必须用 should_refuse 表达（否则 p2_scoring 会判 refusal_unexpected 失败）。
        assert case.should_refuse is (case.expected_kind == "not_found")
        if case.should_refuse:
            assert case.refusal_reason
        assert case.suite == {"negative": "negative", "ambiguity_conflict": "boundary"}[item["group"]]


def test_clarification_rows_are_scored_by_kind_only_and_that_gap_is_pinned() -> None:
    """T207-FIX-A-R1：把「clarification 只判 kind」这个口径缺口显式钉住。

    独立验收 §3-9 指出：C01–C04 的可接受措辞（any-of）没有进评分，只判 `expected_kind`，
    比验收口径**更松**。本包不改冻结判据（value_hit 是「全含」，表达不了 any-of），只把事实钉成断言，
    以免后续把「C 组 pass」误读成「措辞也对」；是否在评分器里表达 any-of 由 T209 决定。
    """
    cases = {case.case_id: case for case in load_acceptance_cases()}
    clarified = [case_id for case_id, case in cases.items() if case.expected_kind == "clarification"]
    assert clarified == ["C01", "C02", "C03", "C04"], clarified
    assert P2_BOUNDARY_IDS[:4] == ("C01", "C02", "C03", "C04")
    for case_id in clarified:
        case = cases[case_id]
        assert case.expected_values == (), "措辞不进 value_hit（全含口径会把正确回答判 fail）"
        assert "accepted_wording(any-of,not-scored)=" in case.notes
        assert case.should_refuse is False


def test_source_refs_and_forbidden_sources_are_mapped_without_invention() -> None:
    cases = {case.case_id: case for case in load_acceptance_cases()}
    for case_id in ("N01", "N05", "C01"):
        assert cases[case_id].expected_sources == ()
        assert cases[case_id].forbidden_sources == ()
    c05 = cases["C05"]
    assert [dict(ref) for ref in c05.expected_sources] == [
        {"doc_code": "D01", "record_code": "P01"},
        {"doc_code": "V01", "locator": {"page": 1}},
    ]
    assert [dict(ref) for ref in c05.forbidden_sources] == [{"doc_code": "V03"}]
    assert "dropped_free_text_locator=heading" in c05.notes
    c06 = cases["C06"]
    assert [dict(ref) for ref in c06.expected_sources] == [
        {"doc_code": "D02", "record_code": "S01"},
        {"doc_code": "V02", "locator": {"page": 1}},
    ]
    assert [dict(ref) for ref in c06.forbidden_sources] == [{"doc_code": "V06"}]


def test_u01_mirror_is_the_same_frozen_entry_as_the_mutation_test() -> None:
    case = u01_case()
    validate_case(case)
    item = _item("U01")
    assert case.case_id == "U01"
    assert case.suite == "update_delete" and case.stratum == "mutation"
    assert case.question == item["question"]
    assert list(case.expected_values) == list(item["expected_values"])
    assert case.expected_kind == item["scenario"]["expected_kind"]
    assert [dict(ref) for ref in case.expected_sources] == [
        {"doc_code": ref["file"], "record_code": ref["record"]} for ref in item["expected_sources"]
    ]
    # 镜像来源必须指回既有测试（不改它）：该文件里仍有 U01 用例且用的是同一份冻结题集条目。
    text = MUTATION_TEST.read_text(encoding="utf-8")
    assert "def test_u01_" in text
    assert 'QUESTIONS["U01"]' in text


def test_converter_refuses_rows_it_cannot_map() -> None:
    u02 = _item("U02")
    with pytest.raises(PublicCaseError) as excinfo:
        acceptance_case(u02, label_version="x")
    assert excinfo.value.code == "group_not_convertible"
    missing_kind = dict(_item("N01"))
    missing_kind["scenario"] = {"initial_state": "B0"}
    with pytest.raises(PublicCaseError) as excinfo:
        acceptance_case(missing_kind, label_version="x")
    assert excinfo.value.code == "expected_kind_missing"


def test_run_case_sets_follow_the_manager_split() -> None:
    sets = run_case_sets()
    assert {name: len(cases) for name, cases in sets.items()} == {"R1": 52, "R2": 2, "R3": 1}
    r1_ids = [case.case_id for case in sets["R1"]]
    assert r1_ids[:40] == list(P2_B0_IDS)
    assert r1_ids[40:48] == list(P2_NEGATIVE_IDS)
    assert r1_ids[48:] == ["C01", "C02", "C03", "C04"]
    assert [case.case_id for case in sets["R2"]] == ["U01", "C05"]
    assert [case.case_id for case in sets["R3"]] == ["C06"]
    # Q01 只在 R1；R2/R3 不重复付费同一题。
    assert "Q01" in r1_ids
    assert "Q01" not in {case.case_id for case in sets["R2"] + sets["R3"]}
    for cases in sets.values():
        for case in cases:
            validate_case(case)
    assert len(load_b0_cases()) == 40
    assert B0_DATASET_PATH.is_file()


def test_write_run_case_files_is_byte_stable_and_round_trips(tmp_path: Path) -> None:
    first = write_run_case_files(tmp_path)
    second = write_run_case_files(tmp_path)
    assert {name: item["sha256"] for name, item in first.items()} == {
        name: item["sha256"] for name, item in second.items()
    }
    for name, item in first.items():
        rows = [
            json.loads(line)
            for line in (tmp_path / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(rows) == item["cases"]
        assert [row["case_id"] for row in rows] == item["case_ids"]


def test_repo_run_inputs_are_consistent() -> None:
    """仓库里随包交付的 run 输入（ingest plan / doc-code 映射 / case 文件）必须自洽且可复现。"""
    from mktkb.evaluation.p2_score_run import load_document_codes
    from mktkb.evaluation.product_adapter import ingest_plan_from_document

    pm = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207" / "PM"
    cases_dir = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207" / "cases"
    codes = load_document_codes(cases_dir / "document-codes.json")
    expected_counts = {"R1": 12, "R2": 4, "R3": 2}
    for name, count in expected_counts.items():
        payload = json.loads((pm / f"T207-ingest-plan-{name}.json").read_text(encoding="utf-8"))
        plan = ingest_plan_from_document(payload)
        assert len(plan.sources) == count, name
        for source in plan.sources:
            assert source.path.is_file(), source.path
            if source.document_ref:
                assert source.document_ref in codes, source.document_ref
            elif source.name and source.name != source.path.name:
                # 只有版本槽第一步才改名（V03 以 D01 的文件名建槽）
                assert source.name in codes, source.name
    # 版本槽三步必须写在同一份逻辑资料上，且第 3 版不发布。
    r1 = ingest_plan_from_document(
        json.loads((pm / "T207-ingest-plan-R1.json").read_text(encoding="utf-8"))
    )
    assert r1.sources[0].document_ref is None and r1.sources[0].name == "D01_物品位置表.xlsx"
    assert r1.sources[1].document_ref == "D01_物品位置表.xlsx"
    assert r1.sources[2].document_ref == "D01_物品位置表.xlsx" and r1.sources[2].publish is False
    # 提交进仓库的 case 文件必须与转换器当前输出逐字节一致（防漂移；只比较、不写仓库）。
    from mktkb.evaluation.dataset import cases_to_jsonl

    for name, run_cases in run_case_sets().items():
        expected = cases_to_jsonl(run_cases).encode("utf-8")
        actual = (cases_dir / f"{name}.jsonl").read_bytes()
        assert actual == expected, name
        assert actual, name
