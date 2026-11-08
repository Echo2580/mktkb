"""T107：regression suite 与 Case 契约扩展（P1 第 2 包）。

覆盖四类验收：

1. ``fixtures/evaluation/regression.jsonl`` 加载/校验 + 7 项必修缺陷逐条映射；
2. ``source_err_id`` 可选字段向后兼容：b0/badcase 规范字节与 ``dataset_version`` 不变；
3. ``regression`` 套件接入 corpus/runner/cli/gate，``run --suite regression --mode local``
   可跑出 CaseResult，缺 ``hard_gate_min_sample`` 时 gate fail closed（unknown / 3）；
4. 非法输入（UUID、重复 case_id、缺 source_err_id、未知字段）一律拒绝。

本文件只用临时合成语料（E11 一份）跑 run→gate，避免在测试里重建 49 份全量语料；
全量 regression run 的证据在 ``docs/reports/OBS-EVAL/P1/evidence/T107/``。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from mktkb.evaluation import cli
from mktkb.evaluation.corpus import (
    SUITES,
    default_corpus_dir,
    default_dataset_path,
)
from mktkb.evaluation.dataset import (
    CASE_FIELDS,
    OPTIONAL_CASE_FIELDS,
    CaseSpec,
    cases_to_jsonl,
    dataset_version,
    load_cases,
    validate_case,
)
from mktkb.evaluation.gate import (
    DEFAULT_GATE_CONFIG_PATH,
    evaluate_gate,
    load_gate_config,
)
from mktkb.evaluation.runner import RunManifest, run_suite

ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = ROOT / "fixtures" / "evaluation"
CORPUS = ROOT / "corpus" / "enterprise-20261101"
REGRESSION_LABEL = "regression-p1-2026-11-05"
DEFECTS = {
    "defect-t101": "ERR-20261104-03",
    "defect-t102": {"ERR-20261104-01", "ERR-20261104-02"},
    "defect-t103": "ERR-20261104-04",
    "defect-t104": "ERR-20261104-07",
    "defect-t105": "ERR-20261104-06",
    "defect-t106": "ERR-20261104-05",
}


def _regression_case(**overrides) -> CaseSpec:
    payload = dict(
        case_id="RGX01",
        suite="regression",
        split="dev",
        stratum="defect-t102",
        business_date="2026-10-28",
        question="滨江店的宣传海报在哪里？",
        turns=(),
        expected_kind="answer",
        expected_values=("店内外侧",),
        expected_sources=({"doc_code": "E11", "unit_key": "sheet:物品位置:row:7"},),
        relevant_units=(),
        reference_answer="滨江店的宣传海报在店内外侧。",
        should_refuse=False,
        refusal_reason=None,
        forbidden_values=(),
        forbidden_sources=(),
        expected_pagination=None,
        requires_ocr=False,
        labeler="lead",
        label_version=REGRESSION_LABEL,
        notes="T107 测试用临时 case",
        source_err_id="ERR-20261104-01",
    )
    payload.update(overrides)
    return CaseSpec(**payload)


# --------------------------------------------------------------------------- #
# 1. 种子映射 / 加载
# --------------------------------------------------------------------------- #


def test_regression_fixture_maps_every_p1_defect() -> None:
    cases = load_cases(EVAL_DIR / "regression.jsonl")

    assert len(cases) >= 7
    assert {case.suite for case in cases} == {"regression"}
    assert {case.split for case in cases} == {"dev"}
    assert {case.business_date for case in cases} == {"2026-10-28"}
    assert {case.label_version for case in cases} == {REGRESSION_LABEL}
    assert {case.requires_ocr for case in cases} == {False}

    by_stratum: dict[str, set[str]] = {}
    for case in cases:
        assert case.source_err_id, f"{case.case_id} 缺 source_err_id"
        if case.expected_kind == "no_answer":
            # scorer 把 no_answer 视为拒答；否则 refusal_unexpected 会误判。
            assert case.should_refuse is True
            assert case.refusal_reason
        by_stratum.setdefault(case.stratum, set()).add(case.source_err_id)
    assert set(by_stratum) == set(DEFECTS)
    for stratum, expected in DEFECTS.items():
        if isinstance(expected, str):
            assert by_stratum[stratum] == {expected}
        else:
            assert by_stratum[stratum] == expected
    assert {case.source_err_id for case in cases} == {
        "ERR-20261104-01",
        "ERR-20261104-02",
        "ERR-20261104-03",
        "ERR-20261104-04",
        "ERR-20261104-05",
        "ERR-20261104-06",
        "ERR-20261104-07",
    }


def test_regression_fixture_is_canonical_and_versioned() -> None:
    path = EVAL_DIR / "regression.jsonl"
    raw = path.read_bytes()
    cases = load_cases(path)

    assert cases_to_jsonl(cases).encode("utf-8") == raw
    assert b"source_err_id" in raw
    assert dataset_version(cases, REGRESSION_LABEL) == (
        f"regression:{REGRESSION_LABEL}:{hashlib.sha256(raw).hexdigest()[:12]}"
    )


# --------------------------------------------------------------------------- #
# 2. 契约扩展向后兼容
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "label_version", "sha256", "dataset_version_value"),
    [
        (
            "b0",
            "b0-2026-11-04",
            "bd4f0f7ccc6e9f50ba630598c01b3519804447d4e0f3bfbc2facd54a5a521e4f",
            "b0:b0-2026-11-04:bd4f0f7ccc6e",
        ),
        (
            "badcase",
            "badcase-2026-11-04",
            "e5f0662af3f2bf51ac9354cf467ab55be9bd3b97444ae2ba7d359d3d907b371a",
            "badcase:badcase-2026-11-04:e5f0662af3f2",
        ),
    ],
)
def test_legacy_fixtures_keep_canonical_bytes_and_dataset_version(
    name: str, label_version: str, sha256: str, dataset_version_value: str
) -> None:
    path = EVAL_DIR / f"{name}.jsonl"
    raw = path.read_bytes()
    cases = load_cases(path)

    assert hashlib.sha256(raw).hexdigest() == sha256
    assert b"source_err_id" not in raw
    assert cases_to_jsonl(cases).encode("utf-8") == raw
    assert dataset_version(cases, label_version) == dataset_version_value
    for case in cases:
        assert set(case.to_dict()) == set(CASE_FIELDS)
        assert case.source_err_id is None


def test_optional_field_only_appears_when_set() -> None:
    case = _regression_case()
    assert set(case.to_dict()) == set(CASE_FIELDS) | set(OPTIONAL_CASE_FIELDS)
    assert case.to_dict()["source_err_id"] == "ERR-20261104-01"

    legacy = _regression_case(case_id="RGX02", suite="b0", label_version="b0-2026-11-04")
    legacy = CaseSpec(**{**legacy.__dict__, "source_err_id": None})
    assert set(legacy.to_dict()) == set(CASE_FIELDS)
    assert "source_err_id" not in legacy.to_dict()


# --------------------------------------------------------------------------- #
# 3. 校验拒绝
# --------------------------------------------------------------------------- #


def test_regression_without_source_err_id_is_rejected(tmp_path: Path) -> None:
    row = _regression_case().to_dict()
    row.pop("source_err_id")
    path = tmp_path / "missing.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source_err_id"):
        load_cases(path)

    case = CaseSpec.from_dict(row)
    with pytest.raises(ValueError, match="source_err_id"):
        validate_case(case)


def test_regression_rejects_unknown_fields_and_uuid_sources(tmp_path: Path) -> None:
    row = _regression_case().to_dict()
    unknown = tmp_path / "unknown.jsonl"
    unknown.write_text(
        json.dumps({**row, "unexpected": 1}, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="未知字段"):
        load_cases(unknown)

    uuid_case = _regression_case(
        expected_sources=(
            {"doc_code": "E11", "unit_key": "0b6f9c1e-3a6f-4d2b-9f5f-1b2c3d4e5f60"},
        )
    )
    with pytest.raises(ValueError):
        validate_case(uuid_case)
    chunk_case = _regression_case(
        expected_sources=({"doc_code": "E11", "chunk_id": "abc123"},)
    )
    with pytest.raises(ValueError):
        validate_case(chunk_case)


def test_regression_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    payload = cases_to_jsonl([_regression_case()]) * 2
    path = tmp_path / "dup.jsonl"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match="重复"):
        load_cases(path)


# --------------------------------------------------------------------------- #
# 4. suite 接入：corpus / cli / runner / gate
# --------------------------------------------------------------------------- #


def test_suite_whitelists_and_defaults_include_regression() -> None:
    assert "regression" in SUITES
    assert set(SUITES) == {"b0", "badcase", "regression"}
    assert default_corpus_dir("regression") == CORPUS
    assert default_dataset_path("regression") == EVAL_DIR / "regression.jsonl"
    assert "regression" in cli.SUITES

    parser = cli.build_parser()
    args = parser.parse_args(["run", "--suite", "regression", "--mode", "local"])
    assert args.suite == "regression"
    args = parser.parse_args(
        ["dataset", "validate", "--suite", "regression", "--path", str(EVAL_DIR / "regression.jsonl")]
    )
    assert args.suite == "regression"


def _write_synthetic_regression_corpus(tmp_path: Path) -> Path:
    corpus_dir = tmp_path / "corpus"
    (corpus_dir / "excel").mkdir(parents=True)
    source = CORPUS / "excel" / "E11_终端物料位置表_当前V2.xlsx"
    target = corpus_dir / "excel" / source.name
    shutil.copy2(source, target)
    manifest = {
        "business_base_date": "2026-10-28",
        "files": [
            {
                "code": "E11",
                "group": "excel",
                "path": f"excel/{source.name}",
                "kind": "xlsx",
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        ],
    }
    (corpus_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return corpus_dir


def test_regression_run_and_gate_fail_closed_without_min_sample(tmp_path: Path) -> None:
    corpus_dir = _write_synthetic_regression_corpus(tmp_path)
    dataset_path = tmp_path / "regression.jsonl"
    dataset_path.write_bytes(cases_to_jsonl([_regression_case()]).encode("utf-8"))
    out_dir = tmp_path / "run"

    result = run_suite(
        "regression",
        "local",
        corpus_dir=corpus_dir,
        dataset_path=dataset_path,
        out_dir=out_dir,
    )

    assert result.manifest.suite == "regression"
    assert result.manifest.dataset_version.startswith(f"regression:{REGRESSION_LABEL}:")
    assert result.manifest.case_count == 1
    assert result.cases[0]["status"] == "pass"
    assert result.cases[0]["error"] is None
    assert result.summary["suite"] == "regression"

    restored = RunManifest.from_dict(result.manifest.to_dict())
    assert restored.suite == "regression"
    bad_suite = result.manifest.to_dict()
    bad_suite["suite"] = "holdout-typo"  # P1 T108：holdout 已是合法 suite
    with pytest.raises(ValueError, match="suite"):
        RunManifest.from_dict(bad_suite)

    config = load_gate_config(DEFAULT_GATE_CONFIG_PATH)
    assert config.min_sample_for("regression") is None
    gate = evaluate_gate(result, config=config, quality=True)

    assert gate.suite == "regression"
    assert gate.min_sample is None
    assert gate.hard_failures == ()
    assert gate.exit_code == 3
    assert any(
        item.gate_id == "min_sample" and item.check_id == "min_sample_missing"
        for item in gate.unknowns
    )
