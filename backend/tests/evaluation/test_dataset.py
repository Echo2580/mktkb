"""T004a：评测数据集 Case 契约、装载与版本（设计 §7.1 / §7.3）。"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import Path

import pytest

from mktkb.evaluation.dataset import (
    CASE_FIELDS,
    CASE_SCHEMA_VERSION,
    CaseSpec,
    cases_to_jsonl,
    dataset_version,
    load_cases,
    validate_case,
    write_cases,
)

ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = ROOT / "fixtures" / "evaluation"


def _base_case(**overrides) -> CaseSpec:
    payload = dict(
        case_id="C01",
        suite="b0",
        split="dev",
        stratum="exact",
        business_date="2026-10-28",
        question="城东店的宣传海报在哪里？",
        turns=(),
        expected_kind="answer",
        expected_values=("B区1号货架第二层",),
        expected_sources=({"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"},),
        relevant_units=(),
        reference_answer="",
        should_refuse=False,
        refusal_reason=None,
        forbidden_values=(),
        forbidden_sources=(),
        expected_pagination=None,
        requires_ocr=False,
        labeler="lead",
        label_version="b0-2026-11-04",
        notes="",
    )
    payload.update(overrides)
    return CaseSpec(**payload)


# ---------------------------------------------------------------- 素材装载


def test_load_b0_cases_counts_fields_and_strata() -> None:
    cases = load_cases(EVAL_DIR / "b0.jsonl")

    assert len(cases) == 40
    assert [case.case_id for case in cases] == [f"Q{index:02d}" for index in range(1, 41)]
    assert {case.suite for case in cases} == {"b0"}
    assert {case.split for case in cases} == {"dev"}
    assert {case.business_date for case in cases} == {"2026-10-28"}
    assert {case.label_version for case in cases} == {"b0-2026-11-04"}
    assert {case.requires_ocr for case in cases} == {False, True}
    strata = {name: sum(1 for case in cases if case.stratum == name) for name in ("exact", "text", "ocr")}
    assert strata == {"exact": 24, "text": 8, "ocr": 8}
    assert sum(1 for case in cases if case.requires_ocr) == 8
    for case in cases:
        assert set(case.to_dict()) == set(CASE_FIELDS)
        assert case.expected_kind == "answer"
        assert case.should_refuse is False
        assert case.refusal_reason is None


def test_load_badcase_cases_records_source_group_and_refusal_labels() -> None:
    cases = load_cases(EVAL_DIR / "badcase.jsonl")

    assert len(cases) == 13
    assert [case.case_id for case in cases] == [f"N{index:02d}" for index in range(1, 14)]
    assert {case.suite for case in cases} == {"badcase"}
    assert {case.split for case in cases} == {"dev"}
    assert {case.business_date for case in cases} == {"2026-10-28"}
    assert {case.label_version for case in cases} == {"badcase-2026-11-04"}
    groups = {name: sum(1 for case in cases if case.stratum == name) for name in ("poster", "policy", "price", "notice", "clarify", "safety")}
    assert groups == {"poster": 2, "policy": 1, "price": 4, "notice": 2, "clarify": 2, "safety": 2}
    kinds = {case.expected_kind for case in cases}
    assert kinds == {"answer", "ambiguous", "no_answer"}
    by_id = {case.case_id: case for case in cases}
    for case_id in ("N12", "N13"):
        assert by_id[case_id].should_refuse is True
        assert by_id[case_id].refusal_reason
    for case_id in ("N01", "N03", "N04", "N05", "N06", "N08", "N09", "N11"):
        assert by_id[case_id].should_refuse is False
    # 负样本/歧义样本没有 gold；其余 badcase 都有可解析来源。
    assert by_id["N10"].expected_sources == ()
    assert by_id["N12"].expected_sources == ()
    assert by_id["N13"].expected_sources == ()
    for case_id in ("N01", "N02", "N03", "N04", "N05", "N06", "N07", "N08", "N09", "N11"):
        assert by_id[case_id].expected_sources
    # N05 的“至少 1 条”原始期望保留在 notes，不伪装成四分页契约。
    assert "expected_min_total=1" in by_id["N05"].notes


def test_ocr_cases_keep_page_locator_and_never_image_or_table_row_keys() -> None:
    cases = [case for case in load_cases(EVAL_DIR / "b0.jsonl") if case.requires_ocr]

    assert len(cases) == 8
    for case in cases:
        assert case.expected_sources, f"{case.case_id} 应保留页级来源"
        for source in case.expected_sources:
            assert set(source) <= {"doc_code", "record_code", "unit_key", "locator"}
            assert "unit_key" not in source
            locator = dict(source.get("locator") or {})
            assert locator == {"page": locator["page"]}, f"{case.case_id} 只保留 page: {locator}"
            assert isinstance(locator["page"], int) and locator["page"] >= 1


def test_fixture_files_contain_no_opaque_ids() -> None:
    uuid_re = re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    )
    hex32_re = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])")
    for name in ("b0", "badcase"):
        text = (EVAL_DIR / f"{name}.jsonl").read_text(encoding="utf-8")
        assert "chunk_id" not in text
        assert "unit_id" not in text
        assert uuid_re.search(text) is None
        assert hex32_re.search(text) is None


# ---------------------------------------------------------------- 校验规则


def test_case_schema_accepts_bundled_rows() -> None:
    for path in (EVAL_DIR / "b0.jsonl", EVAL_DIR / "badcase.jsonl"):
        for case in load_cases(path):
            validate_case(case)


@pytest.mark.parametrize(
    "source",
    [
        {"doc_code": "D01", "chunk_id": "abc123"},
        {"doc_code": "D01", "unit_id": "0b6f9c1e-3a6f-4d2b-9f5f-1b2c3d4e5f60"},
        {"doc_code": "D01", "unit_key": "0b6f9c1e-3a6f-4d2b-9f5f-1b2c3d4e5f60"},
        {"doc_code": "D01", "unit_key": "a" * 32},
        {"doc_code": "D01", "locator": {"image": True}},
        {"doc_code": "D01", "locator": {"page": 1, "bbox": [0, 0, 1, 1]}},
        {"unit_key": "sheet:物品位置:row:8"},
    ],
)
def test_case_schema_rejects_opaque_ids_and_unknown_locator_keys(source: dict) -> None:
    case = _base_case(expected_sources=(source,))
    with pytest.raises(ValueError):
        validate_case(case)


def test_case_schema_rejects_invalid_expected_kind() -> None:
    with pytest.raises(ValueError):
        validate_case(_base_case(expected_kind="looks_right"))


def test_case_schema_rejects_refusal_without_reason() -> None:
    with pytest.raises(ValueError):
        validate_case(_base_case(should_refuse=True, refusal_reason=None))
    validate_case(_base_case(should_refuse=True, refusal_reason="未收录门店，不得编造"))


def test_case_schema_rejects_question_and_turns_both_empty() -> None:
    with pytest.raises(ValueError):
        validate_case(_base_case(question="   ", turns=()))
    validate_case(_base_case(question="滨江店", turns=({"role": "user", "text": "宣传海报在哪里？"},)))


def test_case_schema_rejects_invalid_relevant_units_and_pagination() -> None:
    with pytest.raises(ValueError):
        validate_case(_base_case(relevant_units=({"doc_code": "D01", "unit_id": "x"},)))
    with pytest.raises(ValueError):
        validate_case(_base_case(expected_pagination={"unknown": 1}))
    with pytest.raises(ValueError):
        validate_case(_base_case(expected_pagination={"total": -1}))


def test_load_cases_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    payload = cases_to_jsonl([_base_case()]) * 2
    path = tmp_path / "dup.jsonl"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        load_cases(path)


def test_load_cases_rejects_unknown_and_missing_fields_and_bad_json(tmp_path: Path) -> None:
    row = _base_case().to_dict()
    unknown = tmp_path / "unknown.jsonl"
    unknown.write_text(json.dumps({**row, "extra": 1}, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(unknown)

    missing = dict(row)
    missing.pop("expected_sources")
    missing_path = tmp_path / "missing.jsonl"
    missing_path.write_text(json.dumps(missing, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(missing_path)

    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="第 1 行"):
        load_cases(bad)


# ---------------------------------------------------------------- 版本


def test_dataset_version_matches_file_sha256_and_is_stable() -> None:
    assert CASE_SCHEMA_VERSION == "mktkb.eval.case.v0.1"
    for suite, label_version in (("b0", "b0-2026-11-04"), ("badcase", "badcase-2026-11-04")):
        cases = load_cases(EVAL_DIR / f"{suite}.jsonl")
        version = dataset_version(cases, label_version)
        assert re.fullmatch(rf"{suite}:{label_version}:[0-9a-f]{{12}}", version)
        digest = hashlib.sha256((EVAL_DIR / f"{suite}.jsonl").read_bytes()).hexdigest()[:12]
        assert version.endswith(digest)
        assert dataset_version(cases, label_version) == version


def test_dataset_version_changes_with_content_and_rejects_mismatched_labels() -> None:
    cases = load_cases(EVAL_DIR / "b0.jsonl")
    changed = list(cases)
    changed[0] = dataclasses.replace(changed[0], question=changed[0].question + "（改写）")
    assert dataset_version(changed, "b0-2026-11-04") != dataset_version(cases, "b0-2026-11-04")
    with pytest.raises(ValueError):
        dataset_version(cases, "badcase-2026-11-04")
    with pytest.raises(ValueError):
        dataset_version(list(cases) + [load_cases(EVAL_DIR / "badcase.jsonl")[0]], "b0-2026-11-04")
    with pytest.raises(ValueError):
        dataset_version([], "b0-2026-11-04")


def test_write_cases_is_exact_bytes_and_roundtrips(tmp_path: Path) -> None:
    cases = load_cases(EVAL_DIR / "badcase.jsonl")
    target = tmp_path / "badcase.jsonl"
    digest = write_cases(target, cases)
    payload = target.read_bytes()
    assert payload == cases_to_jsonl(cases).encode("utf-8")
    assert b"\r" not in payload
    assert hashlib.sha256(payload).hexdigest() == digest
    assert load_cases(target) == cases
