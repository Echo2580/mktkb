"""H2MAP: synthetic sources only; no sealed dataset, adapter or network calls."""
from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mktkb.evaluation import p2_runner as runner
from mktkb.evaluation import p2_score_run as drive
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.p2_scoring import (
    P2ScoringError, _version_source_checks, normalize_product_outcome, score_public_case,
)
from mktkb.evaluation.product_adapter import P2RunDataset
from mktkb.evaluation.scorers import CaseCheck, CaseResult


def case(code="V04", *, unit_key=None, locator=None):
    ref = {"doc_code": code, "locator": locator or {"sheet": "synthetic", "row": 7}}
    if unit_key:
        ref["unit_key"] = unit_key
    return CaseSpec(case_id="SYNTHETIC-MAP", suite="holdout", split="holdout",
                    stratum="paraphrase", business_date="2026-10-28", question="合成问题",
                    expected_values=("合成答案",), expected_sources=(ref,))


def row(version=3, *, row_number=7, unit_key="unit-synthetic", status="active"):
    source = {"source_id": "unit-synthetic", "document_name": "D01_synthetic.xlsx",
              "status": status, "unit_key": unit_key,
              "locator": {"sheet": "synthetic", "row": row_number}}
    if version is not None:
        source["version_number"] = version
    return {"case_id": "SYNTHETIC-MAP", "status": "ok", "turns": [{"status": "ok",
            "product": {"kind": "answer", "text": "合成答案", "sources": [source]}}]}


CODES = {"D01_synthetic.xlsx": "D01", "D02_synthetic.xlsx": "D02"}


@pytest.mark.parametrize("code,version", [("V03", 1), ("V04", 3), ("V05", 4), ("V06", 2)])
def test_version_file_maps_to_base_slot_and_real_product_version(code, version):
    item = row(version)
    if code == "V06":
        item["turns"][0]["product"]["sources"][0]["document_name"] = "D02_synthetic.xlsx"
    scores, _ = drive.holdout_case_scores_from_rows((case(code),), {item["case_id"]: item},
                                                    document_codes=CODES)
    assert scores[0].status == "pass"


@pytest.mark.parametrize("version", [2, 4, None, True, "3", 3.0])
def test_wrong_missing_or_invalid_product_version_cannot_hit(version):
    item = row(version)
    scores, _ = drive.holdout_case_scores_from_rows((case(),), {item["case_id"]: item},
                                                    document_codes=CODES)
    assert scores[0].status == "fail"


@pytest.mark.parametrize("version,row_number,want", [(3, 7, "pass"), (2, 7, "fail"),
                                                     (3, 8, "fail")])
def test_unit_key_cannot_bypass_version_or_original_locator(version, row_number, want):
    item = row(version, row_number=row_number)
    scores, _ = drive.holdout_case_scores_from_rows((case(unit_key="unit-synthetic"),),
                           {item["case_id"]: item}, document_codes=CODES)
    assert scores[0].status == want


@pytest.mark.parametrize("version,want", [(3, 1.0), (2, 0.0), (4, 0.0), (None, 0.0)])
def test_version_check_reaches_source_hit_metric(version, want):
    mapped = drive.remap_holdout_case(case(unit_key="unit-synthetic"), drive.load_holdout_source_map())
    scored = score_public_case(mapped, row(version), document_codes=CODES, include_source_version=True)
    assert scored.result.metrics["source_hit"] == want


@pytest.mark.parametrize("status", ["error", "skipped_requires_ocr"])
def test_version_check_preserves_non_quality_result_status(status):
    mapped = drive.remap_holdout_case(case(), drive.load_holdout_source_map())
    outcome = normalize_product_outcome(row(3)["turns"][0], document_codes=CODES,
                                        include_source_version=True)
    original = CaseResult(mapped.case_id, status, (CaseCheck("source_hit", "pass"),))
    assert _version_source_checks(mapped, outcome, original) is original


def test_correct_version_does_not_erase_other_quality_failures():
    mapped = drive.remap_holdout_case(case(), drive.load_holdout_source_map())
    item = row(3)
    item["turns"][0]["product"]["text"] = "错误答案"
    scored = score_public_case(mapped, item, document_codes=CODES, include_source_version=True)
    assert scored.result.metrics["source_hit"] == 1.0
    assert scored.result.metrics["value_hit"] == 0.0
    assert scored.score.status == "fail"


def test_matching_unit_and_version_must_come_from_same_citation():
    item = row(2)
    source = copy.deepcopy(row(3, row_number=8, unit_key="other-unit")["turns"][0]["product"]["sources"][0])
    source["source_id"] = "other-unit"
    item["turns"][0]["product"]["sources"].append(source)
    scores, _ = drive.holdout_case_scores_from_rows((case(unit_key="unit-synthetic"),),
                        {"SYNTHETIC-MAP": item}, document_codes=CODES)
    assert scores[0].status == "fail"


def test_mapped_locator_conflict_and_unknown_code_fail_closed():
    for value in (case(locator={"row": 7, "version_number": 4}), case("V08")):
        with pytest.raises(drive.RunScoreError) as caught:
            drive.holdout_case_scores_from_rows((value,), {"SYNTHETIC-MAP": row()},
                                                document_codes=CODES)
        assert caught.value.code == "holdout_document_code_unmapped"


def test_product_version_is_opt_in_and_cannot_be_forged_by_locator():
    item = row(None)
    item["turns"][0]["product"]["sources"][0]["locator"]["version_number"] = 3
    normal = normalize_product_outcome(item["turns"][0], document_codes=CODES)
    assert normal.citations[0].locator["version_number"] == 3
    scores, _ = drive.holdout_case_scores_from_rows((case(),), {item["case_id"]: item},
                                                    document_codes=CODES)
    assert scores[0].status == "fail"


def test_source_index_version_conflict_is_rejected_and_missing_product_version_not_invented():
    index = {"unit-synthetic": {"unit_key": "unit-synthetic",
              "locator": {"sheet": "synthetic", "row": 7, "version_number": 4}}}
    with pytest.raises(P2ScoringError) as caught:
        drive.holdout_case_scores_from_rows((case(),), {"SYNTHETIC-MAP": row(3)},
                                            document_codes=CODES, source_index=index)
    assert caught.value.code == "source_version_conflict"
    index["unit-synthetic"]["locator"]["version_number"] = 3
    scores, _ = drive.holdout_case_scores_from_rows((case(),), {"SYNTHETIC-MAP": row(None)},
                                                    document_codes=CODES, source_index=index)
    assert scores[0].status == "fail"


def test_plain_base_source_and_public_scoring_stay_unchanged():
    original = case("D01")
    before = copy.deepcopy(original.to_dict())
    for version in (None, 2, 3, 4):
        item = row(version)
        public = score_public_case(original, item, document_codes=CODES)
        scores, _ = drive.holdout_case_scores_from_rows((original,), {item["case_id"]: item},
                                                        document_codes=CODES)
        assert public.score.status == scores[0].status == "pass"
        assert "version_number" not in public.outcome.citations[0].locator
    assert original.to_dict() == before


def test_forbidden_source_need_not_exist_in_imported_corpus():
    original = dataclasses.replace(case("D01"), forbidden_sources=({"doc_code": "V01"},))
    scores, _ = drive.holdout_case_scores_from_rows((original,), {"SYNTHETIC-MAP": row()},
                                                    document_codes=CODES)
    assert scores[0].status == "pass"


def plan(*, wrong_order=False):
    names = [("V03_old.xlsx", "D01_synthetic.xlsx", None),
             ("D01_base.xlsx", None, "D01_synthetic.xlsx"),
             ("V04_new.xlsx", None, "D01_synthetic.xlsx"),
             ("V05_delete.xlsx", None, "D01_synthetic.xlsx")]
    if wrong_order:
        names[2], names[3] = names[3], names[2]
    return SimpleNamespace(sources=tuple(SimpleNamespace(path=Path(path), name=name,
                                      document_ref=ref) for path, name, ref in names))


def marks(*, ingest=None, product_row=None):
    value = case()
    dataset = P2RunDataset("holdout", (value,), {"dataset_version": "synthetic",
              "label_version": "synthetic", "suite": "p2-holdout", "manifest_sha256": "b" * 64,
              "case_count": 1, "strata": {"paraphrase": 1}})
    ledger = runner.P2RunLedger("synthetic", "synthetic", "a" * 64, "dry_run", False,
                                scoring_cases=[product_row or row()])
    blocks = []
    scored, _ = runner._holdout_score_marks(ledger, dataset, ingest_plan=ingest or plan(),
                                            execution="dry_run", blocks=blocks)
    return scored, blocks


def test_runner_real_scoring_boundary_uses_map_and_checks_plan_order():
    scored, blocks = marks()
    assert scored[0].status == "pass"
    assert "holdout_document_code_unmapped" not in {item.code for item in blocks}
    scored, blocks = marks(ingest=plan(wrong_order=True))
    assert scored[0].status == "error"
    assert "holdout_document_code_unmapped" in {item.code for item in blocks}


def r1_indexed_row(raw_locator, index_locator, *, version=3):
    item = row(version)
    product = item["turns"][0]["product"]
    product["sources"][0]["locator"] = raw_locator
    product["evidence"] = [{"unit_id": "unit-synthetic", "unit_key": "unit-synthetic",
                            "locator": index_locator}]
    return item, drive.source_index_from_rows({item["case_id"]: item})


@pytest.mark.parametrize("index_version", [None, 3])
@pytest.mark.parametrize("raw_version", [4, True, "3", None])
def test_r1_raw_locator_version_cannot_be_hidden_by_nonempty_index(index_version, raw_version):
    index_locator = {"sheet": "synthetic", "row": 7}
    if index_version is not None:
        index_locator["version_number"] = index_version
    item, index = r1_indexed_row({"sheet": "synthetic", "row": 7,
                                  "version_number": raw_version}, index_locator)
    with pytest.raises(P2ScoringError) as caught:
        drive.holdout_case_scores_from_rows((case(unit_key="unit-synthetic"),),
            {item["case_id"]: item}, document_codes=CODES, source_index=index)
    assert caught.value.code == "source_version_conflict"


@pytest.mark.parametrize("key,value", [("row", 8), ("sheet", "other-sheet")])
def test_r1_raw_locator_conflict_cannot_be_hidden_by_index(key, value):
    raw = {"sheet": "synthetic", "row": 7}
    raw[key] = value
    item, index = r1_indexed_row(raw, {"sheet": "synthetic", "row": 7})
    with pytest.raises(P2ScoringError) as caught:
        drive.holdout_case_scores_from_rows((case(unit_key="unit-synthetic"),),
            {item["case_id"]: item}, document_codes=CODES, source_index=index)
    assert caught.value.code == "source_locator_conflict"


@pytest.mark.parametrize("version", [True, "3", None, 4])
def test_r1_index_locator_version_assertions_remain_strict(version):
    item, index = r1_indexed_row({"sheet": "synthetic", "row": 7, "version_number": 3},
        {"sheet": "synthetic", "row": 7, "version_number": version})
    with pytest.raises(P2ScoringError) as caught:
        drive.holdout_case_scores_from_rows((case(),), {item["case_id"]: item},
                                            document_codes=CODES, source_index=index)
    assert caught.value.code == "source_version_conflict"


@pytest.mark.parametrize("version", [None, True, "3", 3.0])
def test_r1_locators_cannot_supply_missing_or_invalid_product_version(version):
    locator = {"sheet": "synthetic", "row": 7, "version_number": 3}
    item, index = r1_indexed_row(dict(locator), dict(locator), version=version)
    scores, _ = drive.holdout_case_scores_from_rows((case(unit_key="unit-synthetic"),),
        {item["case_id"]: item}, document_codes=CODES, source_index=index)
    assert scores[0].status == "fail"


@pytest.mark.parametrize("raw,index_locator", [
    ({"sheet": "synthetic", "row": 7, "version_number": 3},
     {"sheet": "synthetic", "row": 7, "version_number": 3}),
    ({"row": 7}, {"sheet": "synthetic", "row": 7}),
    ({"sheet": "synthetic", "row": 7}, {"row": 7}),
])
def test_r1_consistent_or_one_sided_locator_fields_keep_existing_selection(raw, index_locator):
    item, index = r1_indexed_row(raw, index_locator)
    outcome = normalize_product_outcome(item["turns"][0], document_codes=CODES,
                                        source_index=index, include_source_version=True)
    assert outcome.citations[0].locator == {**index_locator, "version_number": 3}
    scores, _ = drive.holdout_case_scores_from_rows((case(unit_key="unit-synthetic"),),
        {item["case_id"]: item}, document_codes=CODES, source_index=index)
    assert scores[0].status == ("pass" if "sheet" in index_locator else "fail")


def test_r1_default_scoring_preserves_nonempty_index_selection_despite_raw_conflict():
    item, index = r1_indexed_row({"sheet": "other-sheet", "row": 8, "version_number": "4"},
                               {"sheet": "synthetic", "row": 7})
    outcome = normalize_product_outcome(item["turns"][0], document_codes=CODES, source_index=index)
    assert outcome.citations[0].locator == {"sheet": "synthetic", "row": 7}
    assert score_public_case(case("D01"), item, document_codes=CODES,
                             source_index=index).score.status == "pass"


def test_runner_known_version_absent_from_ingest_plan_blocks():
    ingest = plan()
    ingest.sources = ingest.sources[:2]
    scored, blocks = marks(ingest=ingest)
    assert scored[0].status == "error"
    assert "holdout_document_code_unmapped" in {item.code for item in blocks}


def test_full_public_h2_ingest_recipe_is_wired_to_runner_without_corpus_reads():
    root = Path(__file__).resolve().parents[3]
    payload = json.loads((root / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json").read_text(encoding="utf-8"))
    ingest = SimpleNamespace(sources=tuple(SimpleNamespace(path=Path(item["path"]),
                         name=item.get("name"), document_ref=item.get("document_ref"))
                         for item in payload["sources"]))
    item = row(3)
    item["turns"][0]["product"]["sources"][0]["document_name"] = "D01_物品位置表.xlsx"
    scored, blocks = marks(ingest=ingest, product_row=item)
    assert scored[0].status == "pass"
    assert "holdout_document_code_unmapped" not in {block.code for block in blocks}


@pytest.mark.parametrize("kind", ["missing", "schema", "duplicate", "bad_version", "collision"])
def test_bad_map_stably_blocks_offline_and_runner(tmp_path, monkeypatch, kind):
    target = tmp_path / "map.json"
    if kind != "missing":
        payload = {"schema_version": "p2-holdout-source-map/v0.1", "basis": ["synthetic"],
                   "sources": {code: {"base_doc_code": base, "version_number": version}
                               for code, base, version in [("V03", "D01", 1), ("V04", "D01", 3),
                                                            ("V05", "D01", 4), ("V06", "D02", 2)]}}
        if kind == "schema":
            payload["schema_version"] = "wrong"
        elif kind == "bad_version":
            payload["sources"]["V04"]["version_number"] = True
        elif kind == "collision":
            payload["sources"]["V05"]["version_number"] = 3
        text = json.dumps(payload)
        if kind == "duplicate":
            text = text.replace('"version_number": 3', '"version_number": 3, "version_number": 4')
        target.write_text(text, encoding="utf-8")
    monkeypatch.setattr(drive, "DEFAULT_HOLDOUT_SOURCE_MAP", target, raising=False)
    with pytest.raises(drive.RunScoreError) as caught:
        drive.holdout_case_scores_from_rows((case(),), {"SYNTHETIC-MAP": row()}, document_codes=CODES)
    assert caught.value.code == "holdout_document_code_unmapped"
    scored, blocks = marks()
    assert scored[0].status == "error"
    assert "holdout_document_code_unmapped" in {item.code for item in blocks}
