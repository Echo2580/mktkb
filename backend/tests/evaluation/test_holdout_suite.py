"""T108：holdout 支持与防污染（P1 第 9 包）。

覆盖五类验收（handoff §4）：

1. 默认聚合：``run --suite holdout --mode local`` 只写 ``run_manifest.json`` /
   ``summary.json``，**不写** ``cases.jsonl``，产物/ stdout 不含题干、答案、逐题结果；
2. ``--allow-holdout-details`` 才写逐题 + ``holdout_audit.json``（操作人/时间/参数/
   run_id/数据 sha/label_version，且审计文件不含题干或答案）；
3. CI/门禁环境（``CI`` / ``GITHUB_ACTIONS`` / ``MKTKB_CI``）带 details 硬失败；
   ``gate --run`` 对聚合 run 可用（exit 3 + 显式 unknown，不抛异常、不泄漏逐题）；
4. 拒绝条件逐项：缺 labels / 缺 label_version / 行数 / 分层 / case_id 集合 / sha 不符；
5. 仓库导出 ``fixtures/evaluation/holdout-questions.jsonl`` 无答案字段、sha 固定。

R1 返工（`rework-R1.md`）：

6. 拒答负样例（``expected_sources=[]`` + ``relevant_units`` 非空 + ``should_refuse``）不得
   判 error、须进入指标分母；``expected_sources`` 非空但 unit_ids 空仍 error；
7. holdout 拒绝复用非空 / 含旧详情三件套的 out 目录（details 同口径）；
8. ``run --suite holdout --mode local --from-run`` 明确拒绝，不静默忽略。

红线：测试只用**临时合成** holdout 夹具（E11 一份合成语料），不读真实 labels，
证据/断言里不出现真实题干或答案。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from mktkb.evaluation import cli, runner
from mktkb.evaluation.dataset import (
    DEFAULT_HOLDOUT_POLICY,
    HOLDOUT_ANSWER_FIELDS,
    HOLDOUT_LABEL_FIELDS,
    HOLDOUT_LABELS_SHA256,
    HOLDOUT_QUESTION_FIELDS,
    HOLDOUT_QUESTIONS_PATH,
    HOLDOUT_QUESTIONS_SHA256,
    HOLDOUT_STRATA,
    HOLDOUT_SUITE,
    HoldoutError,
    HoldoutPolicy,
    ci_environment,
    load_holdout_dataset,
    load_holdout_labels,
    load_holdout_questions,
    validate_case,
)
from mktkb.evaluation.gate import (
    DEFAULT_GATE_CONFIG_PATH,
    evaluate_gate,
    load_gate_config,
    load_run_result,
)
from mktkb.evaluation.runner import run_suite

ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = ROOT / "fixtures" / "evaluation"
CORPUS = ROOT / "corpus" / "enterprise-20261101"
SYNTH_LABEL = "holdout-synthetic-2026-11-08"
SYNTH_STRATA = {"paraphrase": 2, "negative": 1}
SYNTH_CASE_COUNT = 3
#: 唯一标记：只在合成题干里出现，用来证明聚合产物不含题干。
SYNTH_QUESTION_MARKER = "合成题干-丙-唯一标记"
#: 答案原文：只在 labels / 逐题详情里出现，用来证明聚合产物不含答案。
SYNTH_ANSWER_MARKER = "店内外侧"


# --------------------------------------------------------------------------- #
# 合成夹具（不接触真实 holdout 内容）
# --------------------------------------------------------------------------- #


def _q_row(case_id: str, **overrides) -> dict:
    row = {
        "case_id": case_id,
        "suite": "holdout",
        "split": "holdout",
        "stratum": "paraphrase",
        "business_date": "2026-10-28",
        "question": "滨江店的宣传海报在哪里？",
        "turns": [],
        "expected_kind": "answer",
        "should_refuse": False,
        "requires_ocr": False,
        "labeler": "holdout-author",
        "label_version": SYNTH_LABEL,
        "notes": "T108 合成夹具",
    }
    row.update(overrides)
    return row


def _l_row(case_id: str, **overrides) -> dict:
    row = {
        "case_id": case_id,
        "expected_kind": "answer",
        "expected_values": [SYNTH_ANSWER_MARKER],
        "expected_sources": [{"doc_code": "E11", "unit_key": "sheet:物品位置:row:7"}],
        "relevant_units": [{"doc_code": "E11", "unit_key": "sheet:物品位置:row:7"}],
        "reference_answer": f"宣传海报在{SYNTH_ANSWER_MARKER}。",
        "should_refuse": False,
        "refusal_reason": None,
        "forbidden_values": [],
        "forbidden_sources": [],
        "notes": "答案出处说明（合成）",
    }
    row.update(overrides)
    return row


def _questions() -> list[dict]:
    return [
        _q_row("S01"),
        _q_row(
            "S02",
            turns=["那另一个店呢？", "库存还有多少？"],
            question="滨江店的宣传海报在哪里？",
        ),
        _q_row(
            "S03",
            stratum="negative",
            question=f"{SYNTH_QUESTION_MARKER}：有没有配过档期特价？",
            expected_kind="refusal",
            should_refuse=True,
            notes="T108 合成负样本",
        ),
    ]


def _labels() -> list[dict]:
    return [
        _l_row("S01"),
        _l_row("S02"),
        _l_row(
            "S03",
            expected_kind="refusal",
            expected_values=[],
            expected_sources=[],
            relevant_units=[],
            reference_answer="语料未记录该事项（合成）",
            should_refuse=True,
            refusal_reason="语料未记录该事项",
        ),
    ]


def _labels_refusal_with_relevant_units() -> list[dict]:
    """真实 holdout 负样例形态（R1/F1）：``expected_sources=[]`` + ``relevant_units`` 非空。

    默认 ``_labels()`` 的 S03 是 ``relevant_units=[]``，触发不到旧断言的 error 分支；
    这里补上检索相关 unit，复现真实 3/30 的 ``gold_unit_ids_missing``。
    """
    labels = _labels()
    labels[-1] = _l_row(
        "S03",
        expected_kind="refusal",
        expected_values=[],
        expected_sources=[],
        relevant_units=[{"doc_code": "E11", "unit_key": "sheet:物品位置:row:7"}],
        reference_answer="语料未记录该事项（合成）",
        should_refuse=True,
        refusal_reason="语料未记录该事项",
    )
    return labels


def _policy(**overrides) -> HoldoutPolicy:
    base: dict = {
        "case_count": SYNTH_CASE_COUNT,
        "strata": dict(SYNTH_STRATA),
        "questions_sha256": None,
        "labels_sha256": None,
        "label_version": SYNTH_LABEL,
    }
    base.update(overrides)
    return HoldoutPolicy(**base)


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_bytes(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    )
    return path


def _fixture(
    tmp_path: Path,
    *,
    questions: list[dict] | None = None,
    labels: list[dict] | None = None,
) -> tuple[Path, Path]:
    base = tmp_path / "holdout"
    base.mkdir(parents=True, exist_ok=True)
    q = _write_jsonl(base / "questions.jsonl", questions or _questions())
    labels_path = _write_jsonl(base / "labels.jsonl", labels or _labels())
    return q, labels_path


def _write_synthetic_corpus(tmp_path: Path) -> Path:
    """只放 E11 一份语料（与 T107 同一做法），避免在测试里重建全量语料。"""
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


def _run(tmp_path: Path, **kwargs):
    labels_override = kwargs.pop("labels", None)
    questions, labels = _fixture(tmp_path, labels=labels_override)
    policy = kwargs.pop("policy", _policy())
    corpus_dir = kwargs.pop("corpus_dir", None) or _write_synthetic_corpus(tmp_path)
    out_dir = kwargs.pop("out_dir", tmp_path / "run")
    return run_suite(
        HOLDOUT_SUITE,
        "local",
        corpus_dir=corpus_dir,
        dataset_path=questions,
        out_dir=out_dir,
        holdout_labels=labels,
        holdout_policy=policy,
        **kwargs,
    )


def _artifact_blob(out_dir: Path) -> str:
    """把 run 目录下所有文件拼成一段可搜索文本（二进制按 UTF-8 容错解码）。"""
    parts: list[str] = []
    for path in sorted(Path(out_dir).rglob("*")):
        if path.is_file():
            parts.append(path.name)
            parts.append(path.read_bytes().decode("utf-8", errors="ignore"))
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# 1. 默认聚合
# --------------------------------------------------------------------------- #


def test_default_run_writes_aggregate_only_and_never_leaks_text(tmp_path: Path) -> None:
    result = _run(tmp_path)
    out_dir = result.out_dir

    assert result.manifest.suite == HOLDOUT_SUITE
    assert result.manifest.holdout_details is False
    assert result.manifest.holdout_labels_sha256 == hashlib.sha256(
        (tmp_path / "holdout" / "labels.jsonl").read_bytes()
    ).hexdigest()
    assert sorted(path.name for path in out_dir.iterdir()) == [
        "run_manifest.json",
        "summary.json",
    ]
    assert not (out_dir / "cases.jsonl").exists()
    assert result.summary["holdout"]["aggregate_only"] is True
    assert result.summary["holdout"]["details_written"] is False
    assert result.summary["holdout"]["traces_persisted"] is False
    assert result.summary["case_count"] == SYNTH_CASE_COUNT
    assert result.summary["holdout"]["strata"] == SYNTH_STRATA

    blob = _artifact_blob(out_dir)
    assert SYNTH_QUESTION_MARKER not in blob
    assert SYNTH_ANSWER_MARKER not in blob
    for case_id in ("S01", "S02", "S03"):
        assert case_id not in blob
    # 逐题列表被换成计数（holdout 聚合不得带逐 case 身份）
    assert "excluded_error_case_ids" not in blob
    assert "excluded_error_count" in blob


def test_details_flag_writes_cases_and_audit_without_leaking_into_audit(tmp_path: Path) -> None:
    result = _run(tmp_path, allow_holdout_details=True, holdout_operator="tester")
    out_dir = result.out_dir

    assert result.manifest.holdout_details is True
    cases_text = (out_dir / "cases.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in cases_text.split("\n") if line.strip()]
    assert [row["case_id"] for row in rows] == ["S01", "S02", "S03"]
    assert SYNTH_ANSWER_MARKER in cases_text  # 逐题详情确实带答案 → 所以必须 flag + 审计

    audit = json.loads((out_dir / "holdout_audit.json").read_text(encoding="utf-8"))
    assert audit["operator"] == "tester"
    assert audit["run_id"] == result.manifest.run_id
    assert audit["data"]["questions_sha256"] == hashlib.sha256(
        (tmp_path / "holdout" / "questions.jsonl").read_bytes()
    ).hexdigest()
    assert audit["data"]["labels_sha256"] == result.manifest.holdout_labels_sha256
    assert audit["data"]["label_version"] == SYNTH_LABEL
    assert audit["parameters"]["allow_holdout_details"] is True
    assert audit["created_at"] == result.manifest.created_at
    audit_text = json.dumps(audit, ensure_ascii=False)
    assert SYNTH_QUESTION_MARKER not in audit_text
    assert SYNTH_ANSWER_MARKER not in audit_text
    assert "滨江店" not in audit_text


def test_operator_falls_back_to_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MKTKB_HOLDOUT_OPERATOR", "env-operator")
    result = _run(tmp_path, allow_holdout_details=True)
    audit = json.loads((result.out_dir / "holdout_audit.json").read_text(encoding="utf-8"))
    assert audit["operator"] == "env-operator"


def test_multi_turn_turns_are_normalised_but_not_claimed(tmp_path: Path) -> None:
    questions, labels = _fixture(tmp_path)
    dataset = load_holdout_dataset(questions, labels, policy=_policy())
    multi = next(case for case in dataset.cases if case.case_id == "S02")
    assert multi.turns == (
        {"question": "那另一个店呢？"},
        {"question": "库存还有多少？"},
    )

    result = _run(tmp_path)
    execution = result.summary["declarations"]["execution"]
    assert execution["multi_turn_verified"] is False
    assert result.cases[1]["multi_turn_claimed"] is False


# --------------------------------------------------------------------------- #
# 2. CI / 门禁环境禁 flag
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["CI", "GITHUB_ACTIONS", "MKTKB_CI"])
def test_details_flag_fails_closed_in_ci(tmp_path: Path, monkeypatch, name: str) -> None:
    monkeypatch.setenv(name, "1")
    with pytest.raises(ValueError, match="CI/门禁环境禁止"):
        _run(tmp_path, allow_holdout_details=True)
    assert not (tmp_path / "run").exists() or not (
        tmp_path / "run" / "cases.jsonl"
    ).exists()


def test_ci_detection_reads_environment_mapping() -> None:
    assert ci_environment({}) is None
    assert ci_environment({"CI": "0"}) is None
    assert ci_environment({"CI": "false"}) is None
    assert ci_environment({"MKTKB_CI": "TRUE"}) == "MKTKB_CI"
    assert ci_environment({"CI": "1", "GITHUB_ACTIONS": "1"}) == "CI"


def test_aggregate_run_allowed_in_ci(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CI", "true")
    result = _run(tmp_path)
    assert result.manifest.holdout_details is False


# --------------------------------------------------------------------------- #
# 3. gate：聚合可用 / 详情拒绝
# --------------------------------------------------------------------------- #


def test_gate_accepts_aggregate_run_without_cases_jsonl(tmp_path: Path) -> None:
    result = _run(tmp_path)
    loaded = load_run_result(result.out_dir)
    assert loaded.cases == ()

    config = load_gate_config(DEFAULT_GATE_CONFIG_PATH)
    gate = evaluate_gate(loaded, config=config, quality=True, environ={})

    assert gate.suite == HOLDOUT_SUITE
    assert gate.exit_code == 3
    assert gate.hard_failures == ()
    assert gate.failures == ()
    assert [(item.gate_id, item.check_id) for item in gate.unknowns] == [
        (HOLDOUT_SUITE, "holdout_aggregate_only")
    ]
    assert gate.quality is None
    gate_text = json.dumps(gate.to_dict(), ensure_ascii=False)
    assert SYNTH_QUESTION_MARKER not in gate_text
    assert SYNTH_ANSWER_MARKER not in gate_text


def test_gate_cli_on_aggregate_run_is_usable(tmp_path: Path, capsys) -> None:
    result = _run(tmp_path)
    code = cli.main(["gate", "--run", str(result.out_dir)])
    captured = capsys.readouterr()
    assert code == 3
    assert "hard_failures=[]" in captured.out
    assert "Traceback" not in captured.err
    assert SYNTH_QUESTION_MARKER not in captured.out


def test_gate_rejects_details_run_and_names_ci_variable(tmp_path: Path) -> None:
    result = _run(tmp_path, allow_holdout_details=True)
    loaded = load_run_result(result.out_dir)
    config = load_gate_config(DEFAULT_GATE_CONFIG_PATH)

    dev = evaluate_gate(loaded, config=config, quality=True, environ={})
    assert dev.exit_code == 3
    assert dev.unknowns[0].check_id == "holdout_details_not_gated"

    ci = evaluate_gate(loaded, config=config, quality=True, environ={"GITHUB_ACTIONS": "1"})
    assert ci.exit_code == 3
    assert ci.unknowns[0].check_id == "holdout_details_forbidden_in_ci"
    assert "GITHUB_ACTIONS" in ci.unknowns[0].reason
    assert ci.failures == ()


def test_aggregate_run_rejects_smuggled_cases_jsonl(tmp_path: Path) -> None:
    result = _run(tmp_path)
    (result.out_dir / "cases.jsonl").write_text('{"case_id":"S01"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="不应包含 cases.jsonl"):
        load_run_result(result.out_dir)


# --------------------------------------------------------------------------- #
# 4. 拒绝条件（fail closed）
# --------------------------------------------------------------------------- #


def test_missing_labels_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MKTKB_HOLDOUT_LABELS", raising=False)
    questions, _ = _fixture(tmp_path)
    with pytest.raises(ValueError, match="缺少 labels"):
        run_suite(
            HOLDOUT_SUITE,
            "local",
            corpus_dir=_write_synthetic_corpus(tmp_path),
            dataset_path=questions,
            out_dir=tmp_path / "run",
            holdout_policy=_policy(),
        )


def test_labels_from_environment_are_used(tmp_path: Path, monkeypatch) -> None:
    questions, labels = _fixture(tmp_path)
    monkeypatch.setenv("MKTKB_HOLDOUT_LABELS", str(labels))
    result = run_suite(
        HOLDOUT_SUITE,
        "local",
        corpus_dir=_write_synthetic_corpus(tmp_path),
        dataset_path=questions,
        out_dir=tmp_path / "run",
        holdout_policy=_policy(),
    )
    assert result.manifest.holdout_labels_sha256 == hashlib.sha256(labels.read_bytes()).hexdigest()


def test_missing_label_version_is_rejected(tmp_path: Path) -> None:
    questions = _questions()
    questions[0]["label_version"] = ""
    q, labels = _fixture(tmp_path, questions=questions)
    with pytest.raises(HoldoutError, match="label_version"):
        load_holdout_dataset(q, labels, policy=_policy())


def test_wrong_label_version_is_rejected(tmp_path: Path) -> None:
    questions = _questions()
    questions[0]["label_version"] = "holdout-2026-12-01"
    q, labels = _fixture(tmp_path, questions=questions)
    with pytest.raises(HoldoutError, match="label_version"):
        load_holdout_dataset(q, labels, policy=_policy())


def test_row_count_must_match_contract(tmp_path: Path) -> None:
    q, labels = _fixture(tmp_path)
    with pytest.raises(HoldoutError, match="行数"):
        load_holdout_dataset(q, labels, policy=_policy(case_count=30))


def test_strata_must_match_contract(tmp_path: Path) -> None:
    q, labels = _fixture(tmp_path)
    with pytest.raises(HoldoutError, match="分层不符"):
        load_holdout_dataset(q, labels, policy=_policy(strata={"paraphrase": 3}))


def test_case_id_sets_must_match(tmp_path: Path) -> None:
    # 行数相同、case_id 不同：必须由「集合不相等」而不是行数拦下。
    labels = _labels()
    labels[-1] = _l_row("S99")
    q, labels_path = _fixture(tmp_path, labels=labels)
    with pytest.raises(HoldoutError, match="case_id 集合不相等"):
        load_holdout_dataset(q, labels_path, policy=_policy())


def test_sha_mismatch_is_rejected(tmp_path: Path) -> None:
    q, labels = _fixture(tmp_path)
    with pytest.raises(HoldoutError, match="questions sha256 不符"):
        load_holdout_dataset(q, labels, policy=_policy(questions_sha256="0" * 64))
    with pytest.raises(HoldoutError, match="labels sha256 不符"):
        load_holdout_dataset(q, labels, policy=_policy(labels_sha256="0" * 64))


def test_questions_cannot_carry_answers(tmp_path: Path) -> None:
    questions = _questions()
    questions[0]["expected_values"] = [SYNTH_ANSWER_MARKER]
    q, _ = _fixture(tmp_path, questions=questions)
    with pytest.raises(HoldoutError, match="答案字段"):
        load_holdout_questions(q, policy=_policy())


def test_questions_reject_unknown_fields_and_duplicates(tmp_path: Path) -> None:
    questions = _questions()
    questions[0]["unexpected"] = 1
    q, _ = _fixture(tmp_path, questions=questions)
    with pytest.raises(HoldoutError, match="不允许的字段"):
        load_holdout_questions(q, policy=_policy())

    duplicate = _questions()
    duplicate[1]["case_id"] = duplicate[0]["case_id"]
    q2, _ = _fixture(tmp_path / "dup", questions=duplicate)
    with pytest.raises(HoldoutError, match="重复"):
        load_holdout_questions(q2, policy=_policy())


def test_labels_reject_unknown_fields_and_bad_refs(tmp_path: Path) -> None:
    labels = _labels()
    labels[0]["unexpected"] = 1
    _, labels_path = _fixture(tmp_path, labels=labels)
    q, _ = _fixture(tmp_path / "q", labels=_labels())
    with pytest.raises(HoldoutError, match="不允许的字段"):
        load_holdout_labels(labels_path, policy=_policy())

    bad_refs = _labels()
    bad_refs[0]["expected_sources"] = [
        {"doc_code": "E11", "unit_key": "0b6f9c1e-3a6f-4d2b-9f5f-1b2c3d4e5f60"}
    ]
    _, bad_path = _fixture(tmp_path / "bad", labels=bad_refs)
    with pytest.raises(HoldoutError, match="合并后不合规"):
        load_holdout_dataset(q, bad_path, policy=_policy())


def test_metadata_mismatch_is_counted_not_fatal(tmp_path: Path) -> None:
    labels = _labels()
    labels[0]["expected_kind"] = "conflict"
    q, labels_path = _fixture(tmp_path, labels=labels)
    dataset = load_holdout_dataset(q, labels_path, policy=_policy())
    assert dataset.metadata_mismatch_count == 1
    assert dataset.cases[0].expected_kind == "conflict"  # labels 是答案/标注权威


def test_holdout_flags_are_rejected_for_other_suites(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="只用于 --suite holdout"):
        run_suite("b0", "local", allow_holdout_details=True)
    with pytest.raises(ValueError, match="只用于 --suite holdout"):
        run_suite("badcase", "local", holdout_labels=tmp_path / "labels.jsonl")


def test_holdout_replay_is_rejected(tmp_path: Path) -> None:
    questions, labels = _fixture(tmp_path)
    with pytest.raises(ValueError, match="只允许 mode='local'"):
        run_suite(
            HOLDOUT_SUITE,
            "replay",
            replay_from=tmp_path,
            dataset_path=questions,
            holdout_labels=labels,
            holdout_policy=_policy(),
        )
    assert validate_case  # 契约函数在本文件被引用（避免误删导入）


# --------------------------------------------------------------------------- #
# 5. 仓库导出 + CLI 面
# --------------------------------------------------------------------------- #


def test_repository_export_is_answer_free_and_pinned() -> None:
    raw = HOLDOUT_QUESTIONS_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == HOLDOUT_QUESTIONS_SHA256
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"\n")
    lines = [line for line in raw.decode("utf-8").split("\n") if line.strip()]
    assert len(lines) == 30

    keys: set[str] = set()
    for line in lines:
        row = json.loads(line)
        assert set(row) <= set(HOLDOUT_QUESTION_FIELDS)
        assert not (set(row) & HOLDOUT_ANSWER_FIELDS)
        keys |= set(row)
    assert keys == set(HOLDOUT_QUESTION_FIELDS)

    questions = load_holdout_questions(HOLDOUT_QUESTIONS_PATH)
    assert dict(questions.strata) == HOLDOUT_STRATA
    assert questions.label_version == DEFAULT_HOLDOUT_POLICY.label_version
    # labels 永不入库：fixtures/evaluation 下没有任何 labels 文件。
    assert not [path for path in EVAL_DIR.iterdir() if "labels" in path.name]
    assert HOLDOUT_LABELS_SHA256  # 契约常量仍固定在 dataset 层（不落任何文件）


def test_cli_dataset_validate_holdout_prints_aggregate_only(capsys) -> None:
    code = cli.main(
        ["dataset", "validate", "--suite", "holdout", "--path", str(HOLDOUT_QUESTIONS_PATH)]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "cases=30" in out
    assert "answers=none" in out
    assert HOLDOUT_QUESTIONS_SHA256 in out
    assert "paraphrase:10" in out


def test_cli_export_copies_bytes_and_rejects_tampering(tmp_path: Path, capsys) -> None:
    source = _write_jsonl(tmp_path / "questions.jsonl", _questions())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    target = tmp_path / "export" / "holdout-questions.jsonl"

    code = cli.main(
        [
            "dataset",
            "export-holdout-questions",
            "--from",
            str(source),
            "--out",
            str(target),
            "--expected-sha256",
            digest,
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert target.read_bytes() == source.read_bytes()
    assert captured.out.count("answers=none") == 1

    tampered = _write_jsonl(tmp_path / "tampered.jsonl", _questions() + [_q_row("S99")])
    code = cli.main(
        [
            "dataset",
            "export-holdout-questions",
            "--from",
            str(tampered),
            "--out",
            str(tmp_path / "export2.jsonl"),
            "--expected-sha256",
            digest,
        ]
    )
    assert code != 0
    assert "sha256 不符" in capsys.readouterr().err
    assert not (tmp_path / "export2.jsonl").exists()


def test_cli_export_rejects_answers_in_questions(tmp_path: Path, capsys) -> None:
    questions = _questions()
    questions[0]["reference_answer"] = SYNTH_ANSWER_MARKER
    source = _write_jsonl(tmp_path / "questions.jsonl", questions)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    code = cli.main(
        [
            "dataset",
            "export-holdout-questions",
            "--from",
            str(source),
            "--out",
            str(tmp_path / "out.jsonl"),
            "--expected-sha256",
            digest,
        ]
    )
    assert code != 0
    assert "答案字段" in capsys.readouterr().err


def test_cli_run_holdout_aggregate_stdout_has_no_details(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    questions, labels = _fixture(tmp_path)
    corpus_dir = _write_synthetic_corpus(tmp_path)
    real_run_suite = cli.run_suite

    def with_policy(*args, **kwargs):
        kwargs["holdout_policy"] = _policy()
        return real_run_suite(*args, **kwargs)

    monkeypatch.setattr(cli, "run_suite", with_policy)
    code = cli.main(
        [
            "run",
            "--suite",
            "holdout",
            "--dataset",
            str(questions),
            "--holdout-labels",
            str(labels),
            "--out",
            str(tmp_path / "run"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "details=false" in captured.out
    assert f"cases={SYNTH_CASE_COUNT}" in captured.out
    assert SYNTH_QUESTION_MARKER not in captured.out
    assert SYNTH_ANSWER_MARKER not in captured.out


def test_cli_details_flag_hard_fails_in_ci(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CI", "1")
    questions, labels = _fixture(tmp_path)
    code = cli.main(
        [
            "run",
            "--suite",
            "holdout",
            "--dataset",
            str(questions),
            "--holdout-labels",
            str(labels),
            "--allow-holdout-details",
            "--out",
            str(tmp_path / "run"),
        ]
    )
    captured = capsys.readouterr()
    assert code != 0
    assert "CI/门禁环境禁止" in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "run" / "cases.jsonl").exists()


def test_cli_rejects_holdout_flag_for_b0(capsys) -> None:
    code = cli.main(
        ["run", "--suite", "b0", "--mode", "local", "--allow-holdout-details"]
    )
    captured = capsys.readouterr()
    assert code != 0
    assert "只用于 --suite holdout" in captured.err
    assert "Traceback" not in captured.err


# --------------------------------------------------------------------------- #
# 6. R1 返工：拒答负样例可评分（F1）/ out 目录防污染 / from-run 拒绝
# --------------------------------------------------------------------------- #


def test_refusal_case_with_relevant_units_is_scored_not_error(tmp_path: Path) -> None:
    """F1 回归：``expected_sources=[]`` + ``relevant_units`` 非空 + 拒答必须可评分。"""
    result = _run(tmp_path, labels=_labels_refusal_with_relevant_units())

    row = next(item for item in result.cases if item["case_id"] == "S03")
    assert row["status"] in {"pass", "fail"}
    assert row["error"] is None
    assert row["should_refuse"] is True
    assert row["gold"]["unit_ids"] == []
    assert row["gold"]["relevant_unit_ids"]
    assert any(
        check["check_id"] == "refusal_expected" and check["status"] != "skipped"
        for check in row["checks"]
    )

    summary = result.summary
    assert summary["error_count"] == 0
    assert summary["scored_count"] == SYNTH_CASE_COUNT
    assert summary["metrics_scope"]["cases_in_denominator"] == SYNTH_CASE_COUNT
    assert summary["metrics_scope"]["excluded_error_count"] == 0
    # 负样例进入拒答 2×2 与检索分母（不是 unknown / 不进分母）
    assert summary["metrics"]["refusal_recall"] is not None
    assert summary["metrics"]["Recall@10"] is not None


def test_expected_sources_still_require_unit_ids(tmp_path: Path, monkeypatch) -> None:
    """``expected_sources`` 非空但 unit_ids 空仍须 error（不得放宽成静默扩文档）。"""
    real_resolve = runner.resolve_case

    def resolve_without_units(case, index):
        gold = real_resolve(case, index)
        if case.case_id == "S01":
            return dataclasses.replace(gold, unit_ids=())
        return gold

    monkeypatch.setattr(runner, "resolve_case", resolve_without_units)
    result = _run(tmp_path, labels=_labels_refusal_with_relevant_units())

    positive = next(item for item in result.cases if item["case_id"] == "S01")
    assert positive["status"] == "error"
    assert positive["error"]["code"] == "gold_unit_ids_missing"
    # 同一轮里负样例（expected_sources=[]）不因 unit_ids 空被判 error
    negative = next(item for item in result.cases if item["case_id"] == "S03")
    assert negative["status"] != "error"


def test_holdout_rejects_out_dir_with_old_details(tmp_path: Path) -> None:
    """默认聚合 run 复用带旧 ``cases.jsonl`` 的目录 → 明确拒绝，旧文件不动。"""
    stale = tmp_path / "stale"
    stale.mkdir()
    old_cases = stale / "cases.jsonl"
    old_cases.write_text('{"case_id":"OLD"}\n', encoding="utf-8")

    with pytest.raises(HoldoutError, match="拒绝复用含逐题详情"):
        _run(tmp_path, out_dir=stale)

    assert old_cases.read_text(encoding="utf-8") == '{"case_id":"OLD"}\n'
    assert not (stale / "run_manifest.json").exists()
    assert not (stale / "summary.json").exists()


def test_holdout_rejects_reused_nonempty_out_dir(tmp_path: Path) -> None:
    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / "keep.txt").write_text("old", encoding="utf-8")

    with pytest.raises(HoldoutError, match="拒绝复用非空 out 目录"):
        _run(tmp_path, out_dir=stale)

    assert sorted(path.name for path in stale.iterdir()) == ["keep.txt"]


def test_holdout_details_flag_rejects_dir_with_old_details(tmp_path: Path) -> None:
    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / "holdout_audit.json").write_text("{}", encoding="utf-8")

    with pytest.raises(HoldoutError, match="逐题详情"):
        _run(tmp_path, out_dir=stale, allow_holdout_details=True)

    assert sorted(path.name for path in stale.iterdir()) == ["holdout_audit.json"]


def test_holdout_accepts_existing_empty_out_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    result = _run(tmp_path, out_dir=empty)

    assert sorted(path.name for path in result.out_dir.iterdir()) == [
        "run_manifest.json",
        "summary.json",
    ]


def test_cli_holdout_rejects_reused_out_dir(tmp_path: Path, capsys) -> None:
    questions, labels = _fixture(tmp_path)
    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / "cases.jsonl").write_text('{"case_id":"OLD"}\n', encoding="utf-8")

    code = cli.main(
        [
            "run",
            "--suite",
            "holdout",
            "--mode",
            "local",
            "--dataset",
            str(questions),
            "--holdout-labels",
            str(labels),
            "--out",
            str(stale),
        ]
    )
    captured = capsys.readouterr()
    assert code != 0
    assert "拒绝复用" in captured.err
    assert "Traceback" not in captured.err
    assert sorted(path.name for path in stale.iterdir()) == ["cases.jsonl"]


def test_holdout_local_rejects_from_run(tmp_path: Path) -> None:
    questions, labels = _fixture(tmp_path)
    out = tmp_path / "run"

    with pytest.raises(ValueError, match="replay_from"):
        run_suite(
            HOLDOUT_SUITE,
            "local",
            dataset_path=questions,
            holdout_labels=labels,
            holdout_policy=_policy(),
            replay_from=tmp_path / "previous-run",
            out_dir=out,
        )

    assert not out.exists()


def test_cli_holdout_rejects_from_run(tmp_path: Path, capsys) -> None:
    questions, labels = _fixture(tmp_path)
    out = tmp_path / "run"

    code = cli.main(
        [
            "run",
            "--suite",
            "holdout",
            "--mode",
            "local",
            "--dataset",
            str(questions),
            "--holdout-labels",
            str(labels),
            "--from-run",
            str(tmp_path / "previous-run"),
            "--out",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert code != 0
    assert "replay_from" in captured.err
    assert "Traceback" not in captured.err
    assert not out.exists()
