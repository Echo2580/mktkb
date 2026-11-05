"""T005：Replay / Local runner 验收测试（设计 §7.3 / §8.5 / §9；handoff §5）。

覆盖 handoff §5 六条：
1. 三件套 + 双模式（b0/badcase × local/replay）；
2. 版本绑定（manifest 身份字段稳定）；
3. 零真实调用（provider spy = 0、socket guard = 0、不实例化 Settings）；
4. replay 确定性（不建索引、不写索引库、不调 provider；checks 与 local 逐条一致）；
5. unit 级口径闭合（cases.jsonl 自带 chunk 真实 unit_ids；replay 指标一致；OCR 不进分母）；
6. 本包测试与回归（命令见 handoff §6）。
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import socket
from pathlib import Path

import pytest
from sqlalchemy import select

from mktkb.evaluation.corpus import BADCASE_CODES, B0_NON_OCR_KINDS
from mktkb.evaluation.dataset import dataset_version, load_cases, write_cases
from mktkb.evaluation.runner import RunManifest, run_suite
from mktkb.observability.contracts import (
    GATE_SCHEMA_VERSION,
    TraceMode,
    validate_required_spans,
)
from mktkb.observability.store import TraceRepository
from mktkb.rag.models import RagUnit

ROOT = Path(__file__).resolve().parents[3]
ACCEPTANCE = ROOT / "fixtures" / "acceptance"
ENTERPRISE_CORPUS = ROOT / "corpus" / "enterprise-20261101"
B0_DATASET = ROOT / "fixtures" / "evaluation" / "b0.jsonl"
BADCASE_DATASET = ROOT / "fixtures" / "evaluation" / "badcase.jsonl"

REQUIRED_MANIFEST_FIELDS = (
    "run_id",
    "mode",
    "scope",
    "dataset_version",
    "dataset_sha256",
    "corpus_manifest_sha256",
    "business_date",
    "index_revision",
    "pipeline_version",
    "gate_version",
)

IDENTITY_EXCLUDING_MODE = tuple(
    name for name in RunManifest.IDENTITY_FIELDS if name != "mode"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copytree_without_traces(source: Path, target: Path) -> Path:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("traces.sqlite3*"))
    return target


# --------------------------------------------------------------------------- #
# session 级真实运行夹具（每个 suite 只建一次隔离索引）
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def b0_local(tmp_path_factory):
    out = tmp_path_factory.mktemp("t005-b0") / "local"
    return run_suite(
        "b0",
        "local",
        corpus_dir=ACCEPTANCE,
        out_dir=out,
        scope="end_to_end",
        replay_from=None,
    )


@pytest.fixture(scope="module")
def badcase_local(tmp_path_factory):
    out = tmp_path_factory.mktemp("t005-badcase") / "local"
    return run_suite(
        "badcase",
        "local",
        corpus_dir=ENTERPRISE_CORPUS,
        out_dir=out,
        scope="end_to_end",
        replay_from=None,
    )


@pytest.fixture(scope="module")
def b0_replay(tmp_path_factory, b0_local):
    out = tmp_path_factory.mktemp("t005-b0") / "replay"
    return run_suite(
        "b0",
        "replay",
        corpus_dir=ACCEPTANCE,
        out_dir=out,
        scope="end_to_end",
        replay_from=b0_local.out_dir,
    )


# --------------------------------------------------------------------------- #
# 1. 三件套 + 双模式
# --------------------------------------------------------------------------- #


def test_local_b0_produces_three_artifacts_and_all_case_rows(b0_local, b0_cases) -> None:
    assert (b0_local.out_dir / "run_manifest.json").is_file()
    assert (b0_local.out_dir / "cases.jsonl").is_file()
    assert (b0_local.out_dir / "summary.json").is_file()

    rows = _read_jsonl(b0_local.out_dir / "cases.jsonl")
    assert len(rows) == len(b0_cases) == 40
    assert [row["case_id"] for row in rows] == [case.case_id for case in b0_cases]
    for row in rows:
        assert {"case_id", "status", "trace_id", "checks"} <= set(row)
        assert row["status"] in {"pass", "fail", "skipped_requires_ocr", "error"}
        assert row["turns_executed"] == 1
        assert row["multi_turn_claimed"] is False
        assert row["error"] is None

    statuses = {row["status"] for row in rows}
    assert "skipped_requires_ocr" in statuses
    assert len([row for row in rows if row["status"] == "skipped_requires_ocr"]) == 8

    manifest = _read_json(b0_local.out_dir / "run_manifest.json")
    assert manifest["mode"] == "local"
    assert manifest["suite"] == "b0"
    assert manifest["scope"] == "end_to_end"
    assert manifest["case_count"] == 40


def test_local_badcase_produces_all_13_rows(badcase_local, badcase_cases) -> None:
    rows = _read_jsonl(badcase_local.out_dir / "cases.jsonl")
    assert len(rows) == len(badcase_cases) == 13
    assert [row["case_id"] for row in rows] == [case.case_id for case in badcase_cases]
    for case_id in ("N10", "N12", "N13"):
        row = next(item for item in rows if item["case_id"] == case_id)
        assert row["status"] != "skipped_requires_ocr"
        assert row["metrics"]["gold_units"] == 0
        assert row["gold"]["relevant_unit_ids"] == []
    assert _read_json(badcase_local.out_dir / "summary.json")["metrics"]["case_count"] == 13


def test_local_badcase_does_not_parse_ocr_only_b0_documents() -> None:
    # B0 只允许 D01–D06；扫描 PDF / 图片的 kind 不得进入装配白名单，也不得被解析。
    from mktkb.evaluation.corpus import load_suite_corpus

    assert B0_NON_OCR_KINDS == {"xlsx", "docx", "pdf-text"}
    assert set(BADCASE_CODES) == {"E03", "E11", "P03", "W01"}
    corpus = load_suite_corpus("b0", ACCEPTANCE, business_date="2026-10-28")
    codes = [spec.doc_id for spec, _units in corpus.documents]
    assert codes == ["D01", "D02", "D03", "D04", "D05", "D06"]
    skipped = {item["code"]: item["reason"] for item in corpus.skipped}
    assert set(skipped) == {"D07", "D08", "D09", "D10"}
    assert all(reason.startswith("not_offline_kind:") for reason in skipped.values())


# --------------------------------------------------------------------------- #
# 2. 版本绑定
# --------------------------------------------------------------------------- #


def test_manifest_binds_dataset_corpus_index_pipeline_gate(b0_local, b0_cases) -> None:
    manifest = _read_json(b0_local.out_dir / "run_manifest.json")
    for name in REQUIRED_MANIFEST_FIELDS:
        assert name in manifest, name

    assert manifest["dataset_sha256"] == _sha256(B0_DATASET)
    assert manifest["corpus_manifest_sha256"] == _sha256(ACCEPTANCE / "manifest.json")
    assert manifest["dataset_version"] == dataset_version(b0_cases, "b0-2026-11-04")
    assert manifest["business_date"] == "2026-10-28"
    assert manifest["index_revision"] == 6
    assert manifest["gate_version"] == GATE_SCHEMA_VERSION
    assert isinstance(manifest["run_id"], str) and manifest["run_id"]
    assert len(manifest["pipeline_version"]) == 12
    assert manifest["trace_store"] == "traces.sqlite3"


def test_two_local_runs_keep_identity_fields_stable(tmp_path, badcase_local) -> None:
    second = run_suite(
        "badcase",
        "local",
        corpus_dir=ENTERPRISE_CORPUS,
        out_dir=tmp_path / "second",
        scope="end_to_end",
        replay_from=None,
    )
    first_manifest = badcase_local.manifest.to_dict()
    second_manifest = second.manifest.to_dict()
    assert first_manifest["run_id"] != second_manifest["run_id"]
    assert first_manifest["created_at"] != second_manifest["created_at"]
    for name in IDENTITY_EXCLUDING_MODE:
        assert first_manifest[name] == second_manifest[name], name
    assert first_manifest["index_revision"] == second_manifest["index_revision"] == 4


# --------------------------------------------------------------------------- #
# 3. 零真实调用
# --------------------------------------------------------------------------- #


def test_local_run_makes_zero_real_provider_calls_and_never_reads_env(
    monkeypatch, tmp_path
) -> None:
    import mktkb.config as app_config
    import mktkb.rag.providers as providers

    calls: list[str] = []
    connects: list[object] = []

    def provider_guard(*args, **kwargs):
        calls.append("called")
        raise AssertionError("真实 provider 不应在 local 模式被调用")

    def socket_guard(self, address):
        connects.append(address)
        raise AssertionError("local 模式不应尝试 socket 出网")

    monkeypatch.setattr(providers.BailianEmbeddingProvider, "embed", provider_guard)
    monkeypatch.setattr(providers.BailianRerankProvider, "rerank", provider_guard)
    monkeypatch.setattr(providers.DeepSeekChatProvider, "complete", provider_guard)
    monkeypatch.setattr(socket.socket, "connect", socket_guard)
    monkeypatch.setattr(app_config.Settings, "__init__", provider_guard)

    result = run_suite(
        "badcase",
        "local",
        corpus_dir=ENTERPRISE_CORPUS,
        out_dir=tmp_path / "offline",
    )
    assert calls == []
    assert connects == []
    rows = _read_jsonl(result.out_dir / "cases.jsonl")
    assert len(rows) == 13


# --------------------------------------------------------------------------- #
# 4. replay 确定性
# --------------------------------------------------------------------------- #


def test_replay_matches_local_checks_and_retrieval_metrics(b0_local, b0_replay) -> None:
    local_rows = _read_jsonl(b0_local.out_dir / "cases.jsonl")
    replay_rows = _read_jsonl(b0_replay.out_dir / "cases.jsonl")
    assert len(replay_rows) == len(local_rows)
    assert b0_replay.manifest.mode == "replay"
    for name in IDENTITY_EXCLUDING_MODE:
        assert b0_replay.manifest.to_dict()[name] == b0_local.manifest.to_dict()[name], name

    for local_row, replay_row in zip(local_rows, replay_rows):
        assert replay_row["case_id"] == local_row["case_id"]
        assert replay_row["status"] == local_row["status"]
        assert replay_row["checks"] == local_row["checks"]
        assert replay_row["metrics"] == local_row["metrics"]
        assert replay_row["replayed"] is True
        assert replay_row["previous_trace_id"] == local_row["trace_id"]

    local_summary = _read_json(b0_local.out_dir / "summary.json")["metrics"]
    replay_summary = _read_json(b0_replay.out_dir / "summary.json")["metrics"]
    for name in ("Recall@10", "MRR@10", "nDCG@10"):
        assert replay_summary[name] == local_summary[name], name


def test_badcase_replay_produces_three_artifacts_and_matches_local(badcase_local, tmp_path) -> None:
    replay = run_suite(
        "badcase",
        "replay",
        corpus_dir=ENTERPRISE_CORPUS,
        out_dir=tmp_path / "badcase-replay",
        replay_from=badcase_local.out_dir,
    )
    assert (replay.out_dir / "run_manifest.json").is_file()
    assert (replay.out_dir / "cases.jsonl").is_file()
    assert (replay.out_dir / "summary.json").is_file()
    local_rows = _read_jsonl(badcase_local.out_dir / "cases.jsonl")
    replay_rows = _read_jsonl(replay.out_dir / "cases.jsonl")
    assert len(replay_rows) == 13
    for local_row, replay_row in zip(local_rows, replay_rows):
        assert replay_row["checks"] == local_row["checks"]
        assert replay_row["metrics"] == local_row["metrics"]
    local_metrics = _read_json(badcase_local.out_dir / "summary.json")["metrics"]
    replay_metrics = _read_json(replay.out_dir / "summary.json")["metrics"]
    for key in (
        "case_count",
        "scored_count",
        "skipped_count",
        "Recall@10",
        "MRR@10",
        "nDCG@10",
        "value_hit",
        "source_hit",
        "kind_correct",
        "citation_precision",
        "citation_recall",
        "refusal_recall",
        "false_refusal_rate",
        "refusal_precision",
        "hard_filter_violation_rate",
        "empty_recall_rate",
    ):
        assert replay_metrics[key] == local_metrics[key], key


def test_replay_requires_replay_from_and_rejects_mode_conflict(tmp_path) -> None:
    with pytest.raises(ValueError, match="replay_from"):
        run_suite("b0", "replay", corpus_dir=ACCEPTANCE, out_dir=tmp_path / "r1")
    with pytest.raises(ValueError, match="replay_from"):
        run_suite(
            "b0",
            "local",
            corpus_dir=ACCEPTANCE,
            out_dir=tmp_path / "r2",
            replay_from=tmp_path / "r2",
        )


def test_replay_does_not_build_index_or_call_provider(monkeypatch, tmp_path, b0_local) -> None:
    import mktkb.evaluation.runner as runner_module
    import mktkb.rag.providers as providers

    calls: list[str] = []

    def forbidden(*args, **kwargs):
        calls.append("called")
        raise AssertionError("replay 不应建索引或调用 provider")

    monkeypatch.setattr(runner_module, "build_suite_index", forbidden)
    monkeypatch.setattr(providers.BailianEmbeddingProvider, "embed", forbidden)
    monkeypatch.setattr(providers.BailianRerankProvider, "rerank", forbidden)
    monkeypatch.setattr(providers.DeepSeekChatProvider, "complete", forbidden)

    def socket_guard(self, address):
        calls.append("socket")
        raise AssertionError("replay 不应尝试 socket 出网")

    monkeypatch.setattr(socket.socket, "connect", socket_guard)

    out = tmp_path / "replay-no-index"
    run_suite("b0", "replay", corpus_dir=ACCEPTANCE, out_dir=out, replay_from=b0_local.out_dir)
    assert calls == []
    assert {path.name for path in out.iterdir()} == {
        "run_manifest.json",
        "cases.jsonl",
        "summary.json",
        "traces.sqlite3",
    }


def test_replay_writes_replayed_traces_without_spans(b0_local, b0_replay) -> None:
    local_rows = _read_jsonl(b0_local.out_dir / "cases.jsonl")
    replay_rows = _read_jsonl(b0_replay.out_dir / "cases.jsonl")
    repo = TraceRepository(b0_replay.out_dir / "traces.sqlite3")
    try:
        for local_row, replay_row in zip(local_rows, replay_rows):
            record, spans = repo.get(replay_row["trace_id"])
            assert record.replayed is True
            assert record.mode == TraceMode.REPLAY.value
            assert record.previous_trace_id == local_row["trace_id"]
            assert record.status == "replayed"
            assert spans == []
    finally:
        repo.close()


def test_replay_fails_closed_on_missing_unit_ids(tmp_path, b0_local) -> None:
    rows = _read_jsonl(b0_local.out_dir / "cases.jsonl")
    assert rows[0]["outcome"]["citations"]
    assert rows[0]["outcome"]["retrieved"]

    missing_citation = _copytree_without_traces(b0_local.out_dir, tmp_path / "missing-citation")
    payload = _read_jsonl(missing_citation / "cases.jsonl")
    payload[0]["outcome"]["citations"][0]["unit_ids"] = []
    (missing_citation / "cases.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in payload), encoding="utf-8"
    )
    result = run_suite(
        "b0", "replay", corpus_dir=ACCEPTANCE, out_dir=tmp_path / "replay-citation",
        replay_from=missing_citation,
    )
    first = _read_jsonl(result.out_dir / "cases.jsonl")[0]
    assert first["status"] == "error"
    assert first["error"]["code"] == "citation_unit_ids_missing"

    missing_gold = _copytree_without_traces(b0_local.out_dir, tmp_path / "missing-gold")
    payload = _read_jsonl(missing_gold / "cases.jsonl")
    target = next(row for row in payload if row["case_id"] == "Q02")
    target["gold"]["unit_ids"] = []
    target["gold"]["relevant_unit_ids"] = []
    (missing_gold / "cases.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in payload), encoding="utf-8"
    )
    result = run_suite(
        "b0", "replay", corpus_dir=ACCEPTANCE, out_dir=tmp_path / "replay-gold",
        replay_from=missing_gold,
    )
    second = next(row for row in _read_jsonl(result.out_dir / "cases.jsonl") if row["case_id"] == "Q02")
    assert second["status"] == "error"
    assert second["error"]["code"] == "gold_unit_ids_missing"
    assert _read_json(result.out_dir / "summary.json")["error_count"] == 1


def test_replay_detects_persisted_score_drift(tmp_path, b0_local) -> None:
    drifted = _copytree_without_traces(b0_local.out_dir, tmp_path / "drifted")
    payload = _read_jsonl(drifted / "cases.jsonl")
    target = next(row for row in payload if row["status"] == "pass")
    target["checks"][0]["status"] = "fail"
    (drifted / "cases.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in payload), encoding="utf-8"
    )
    result = run_suite(
        "b0", "replay", corpus_dir=ACCEPTANCE, out_dir=tmp_path / "replay-drift",
        replay_from=drifted,
    )
    row = next(row for row in _read_jsonl(result.out_dir / "cases.jsonl") if row["case_id"] == target["case_id"])
    assert row["status"] == "error"
    assert row["error"]["code"] == "replay_score_mismatch"


def test_replay_rejects_changed_dataset(tmp_path, b0_local) -> None:
    changed = tmp_path / "b0-changed.jsonl"
    cases = load_cases(B0_DATASET)
    corrupted = dataclasses.replace(cases[0], question=cases[0].question + "（已改）")
    write_cases(changed, [corrupted, *cases[1:]])
    with pytest.raises(ValueError, match="dataset_sha256"):
        run_suite(
            "b0", "replay", corpus_dir=ACCEPTANCE, out_dir=tmp_path / "changed",
            replay_from=b0_local.out_dir, dataset_path=changed,
        )


# --------------------------------------------------------------------------- #
# 5. unit 级口径闭合
# --------------------------------------------------------------------------- #


def _real_unit_keys(index) -> dict[str, str]:
    with index.session() as session:
        return {
            str(row.unit_id): str(row.unit_key)
            for row in session.execute(select(RagUnit)).scalars()
        }


def test_unit_ids_come_from_real_chunks(b0_local, b0_index, badcase_local, badcase_index) -> None:
    for run, index in ((b0_local, b0_index), (badcase_local, badcase_index)):
        real_keys = _real_unit_keys(index)
        real_ids = set(real_keys)
        rows = _read_jsonl(run.out_dir / "cases.jsonl")
        for row in rows:
            if row["gold"] is not None:
                for source in row["gold"]["sources"]:
                    assert set(source["unit_ids"]) <= real_ids
                assert set(row["gold"]["unit_ids"]) <= real_ids
                assert set(row["gold"]["relevant_unit_ids"]) <= real_ids
            if row["outcome"] is None:
                continue
            for citation in row["outcome"]["citations"]:
                assert citation["doc_code"]
                assert len(citation["unit_ids"]) == 1, row["case_id"]
                assert citation["unit_ids"][0] in real_ids
                assert citation["unit_key"] == real_keys[citation["unit_ids"][0]]
                assert isinstance(citation["locator"], dict)
            for item in row["outcome"]["retrieved"]:
                assert item["doc_code"]
                assert len(item["unit_ids"]) == 1, row["case_id"]
                assert item["unit_ids"][0] in real_ids
                assert item["unit_key"] == real_keys[item["unit_ids"][0]]
                assert isinstance(item["locator"], dict)
        outcomes = [row for row in rows if row["outcome"] is not None]
        assert any(row["outcome"]["citations"] for row in outcomes)
        assert any(row["outcome"]["retrieved"] for row in outcomes)


def test_persisted_unit_key_keeps_forbidden_sources_matchable(b0_local) -> None:
    """T004b MEDIUM-4：只写 unit_ids 时 forbidden_sources 的 unit_key 会漏报。"""
    from mktkb.evaluation.scorers import check_source

    rows = _read_jsonl(b0_local.out_dir / "cases.jsonl")
    citation = next(
        citation
        for row in rows
        if row["outcome"] is not None
        for citation in row["outcome"]["citations"]
    )
    assert citation["unit_key"]
    ref = {"doc_code": citation["doc_code"], "unit_key": citation["unit_key"]}
    assert check_source(ref, citation) is True


def test_ocr_cases_are_skipped_and_excluded_from_denominators(b0_local) -> None:
    rows = _read_jsonl(b0_local.out_dir / "cases.jsonl")
    summary = _read_json(b0_local.out_dir / "summary.json")
    metrics = summary["metrics"]
    ocr_rows = [row for row in rows if row["status"] == "skipped_requires_ocr"]
    assert len(ocr_rows) == 8
    for row in ocr_rows:
        assert row["checks"] == [
            {
                "check_id": "scored",
                "status": "skipped",
                "evidence": {"reason": "skipped_requires_ocr"},
            }
        ]
        assert row["outcome"] is None
    assert metrics["case_count"] == 40
    assert metrics["scored_count"] == 32
    assert metrics["skipped_count"] == 8

    applicable = [
        row["metrics"]["Recall@10"]
        for row in rows
        if row["status"] != "skipped_requires_ocr"
        and (row["metrics"].get("gold_units") or 0) > 0
    ]
    assert metrics["Recall@10"] == pytest.approx(sum(applicable) / len(applicable))


def test_local_traces_are_written_and_cover_required_spans(b0_local) -> None:
    rows = _read_jsonl(b0_local.out_dir / "cases.jsonl")
    repo = TraceRepository(b0_local.out_dir / "traces.sqlite3")
    try:
        for row in rows:
            record, spans = repo.get(row["trace_id"])
            assert record.case_id == row["case_id"]
            assert record.dataset_version == b0_local.manifest.dataset_version
            assert record.run_id == b0_local.manifest.run_id
            assert record.index_revision == str(b0_local.manifest.index_revision)
            assert record.manifest_sha256 == b0_local.manifest.corpus_manifest_sha256
            assert record.pipeline_version == b0_local.manifest.pipeline_version
            names = [span.name for span in spans]
            if row["status"] == "skipped_requires_ocr":
                assert record.status == "incomplete"
                assert spans == []
            else:
                assert validate_required_spans(record, names) == [], row["case_id"]
    finally:
        repo.close()


def test_badcase_declarations_single_turn_and_pagination_not_claimed(badcase_local) -> None:
    summary = _read_json(badcase_local.out_dir / "summary.json")
    declarations = summary["declarations"]
    assert declarations["execution"]["turns_executed"] == 1
    assert declarations["execution"]["multi_turn_verified"] is False
    assert declarations["execution"]["single_turn_case_ids"] == ["N06", "N11"]
    assert "N06/N11" in declarations["execution"]["note"]
    assert declarations["pagination"]["claimed"] is False
    assert "N05" in declarations["pagination"]["note"]
    assert declarations["gold"]["range_gold_case_ids"] == ["N05", "N09"]
    assert declarations["gold"]["record_code_only_allowed"] is False

    rows = _read_jsonl(badcase_local.out_dir / "cases.jsonl")
    assert next(row for row in rows if row["case_id"] == "N09")["status"] != "error"
    n09 = next(row for row in rows if row["case_id"] == "N09")
    assert len(n09["gold"]["relevant_unit_ids"]) == 17
    n05 = next(row for row in rows if row["case_id"] == "N05")
    assert len(n05["gold"]["relevant_unit_ids"]) == 11


# --------------------------------------------------------------------------- #
# 6. T004a 遗留：record_code-only gold 必须 fail closed
# --------------------------------------------------------------------------- #


def test_record_code_only_gold_fails_closed(tmp_path) -> None:
    cases = load_cases(B0_DATASET)
    bad_case = dataclasses.replace(
        cases[0],
        expected_sources=({"doc_code": "D01", "record_code": "P01"},),
        relevant_units=(),
    )
    dataset = tmp_path / "b0-record-code-only.jsonl"
    write_cases(dataset, [bad_case, *cases[1:]])

    result = run_suite(
        "b0",
        "local",
        corpus_dir=ACCEPTANCE,
        out_dir=tmp_path / "run",
        dataset_path=dataset,
    )
    rows = _read_jsonl(result.out_dir / "cases.jsonl")
    assert len(rows) == 40
    first = rows[0]
    assert first["case_id"] == bad_case.case_id
    assert first["status"] == "error"
    assert first["error"]["code"] == "record_code_only_gold"
    assert first["gold"] is None
    assert first["outcome"] is None
    assert first["checks"] == []
    assert _read_json(result.out_dir / "summary.json")["error_count"] == 1
    # 其余 case 仍然逐行产出（失败不吞掉数据集行数）。
    assert {row["status"] for row in rows[1:]} & {"pass", "fail"}

    replay = run_suite(
        "b0",
        "replay",
        corpus_dir=ACCEPTANCE,
        out_dir=tmp_path / "replay",
        replay_from=result.out_dir,
        dataset_path=dataset,
    )
    replay_rows = _read_jsonl(replay.out_dir / "cases.jsonl")
    replay_first = replay_rows[0]
    assert replay_first["status"] == "error"
    assert replay_first["error"]["code"] == "record_code_only_gold"
    assert replay_first["previous_trace_id"] == first["trace_id"]
