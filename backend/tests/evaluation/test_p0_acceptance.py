"""T008b：P0 七条验收（设计 §11）落成可重复执行的测试。

七条对应：

1. 业务行为不变：真实 HTTP 问答（真实检索 + 确定性模型替身）归一化易变字段后与
   ``golden/chat_response.json`` 比对，并断言响应头含 ``X-Trace-ID``；
2. ``trace_id`` 端到端可查：``X-Trace-ID`` → 仓储记录（``request_id`` 即响应体
   ``request_id``）、``spans`` 非空、换一个只读仓储实例仍可查到；
3. b0 / badcase 可独立回归：两次 ``run_suite`` 各自产出三件套 + ``summary.json``；
4. 结果绑定 ``dataset_version`` / ``index_revision`` / ``pipeline_version``
   （run 清单 + summary + trace 记录三处一致）；
5. baseline + diff + JSON 报告：默认配置（未审批）→ exit 3 且拒绝审批；**测试内**
   审批配置（``%TEMP%`` 内）→ gate 0、baseline 审批、diff/report 产物齐全；
6. 硬门禁失败 → 非零退出码（敏感来源 case → ``security_leak`` → exit 1）；
7. 零真实调用：provider spy=0、socket connect=0、未读 ``.env``，业务问答 0 次模型调用。

**golden 来源与归一化**（详见 ``golden/chat_response.json`` 的 ``_meta``）：
golden 由仓库外一次性采集脚本在 commit ``5152298``（代码基线 ``f2c0209``，T008b 不改
业务代码）上记录，采集命令与场景写在 ``_meta.capture_command`` / ``_meta.scenario``；
测试只读取 golden、从不回写，归一化规则列在 :data:`NORMALISED_FIELDS` 并由 #1 断言与
``_meta.normalised_fields`` 一致，避免文档与实现漂移、也不循环自证。

成本：每个 suite 一轮 local 约 2 秒；本文件不新增依赖、零真实模型/OCR/embedding/rerank
调用、不读 ``.env``、产物只写 pytest ``--basetemp``。
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import uuid
from pathlib import Path
from typing import Any, Mapping

import openpyxl
import pytest

from mktkb.documents.lifecycle import get_revision
from mktkb.evaluation import cli
from mktkb.evaluation.corpus import default_dataset_path
from mktkb.evaluation.dataset import dataset_version, load_cases
from mktkb.evaluation.gate import DEFAULT_GATE_CONFIG_PATH, evaluate_gate, load_gate_config
from mktkb.evaluation.runner import run_suite
from mktkb.ingestion.worker import run_one_job
from mktkb.observability import OutcomeKind, TracePath, required_spans, validate_required_spans
from mktkb.observability.contracts import GATE_SCHEMA_VERSION
from mktkb.observability.store import TraceRepository
from observability.conftest import T003D_HEADERS, T003D_ROWS, open_session

ROOT = Path(__file__).resolve().parents[3]
ACCEPTANCE = ROOT / "fixtures" / "acceptance"
B0_DATASET = ROOT / "fixtures" / "evaluation" / "b0.jsonl"
GOLDEN = Path(__file__).resolve().parent / "golden" / "chat_response.json"

#: 纯 RAG 枚举题（``_rag_owns_turn`` 为真）：真实检索 + 确定性作答，不调模型。
CHAT_QUESTION = "把城东店和滨江店的宣传海报记录都列出来"
TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
UUID_TEXT_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
ISO_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?")
#: 答案里的“记录 <8 位>”由 doc/version/unit 派生；version_id 是本轮上传的随机 UUID。
RECORD_REF_RE = re.compile(r"（记录 [0-9a-f]{8}）")

#: 归一化清单（golden._meta.normalised_fields 必须与它逐字一致）。
NORMALISED_FIELDS: tuple[str, ...] = (
    "body.request_id: 每次请求生成的 UUID → <uuid>",
    "body.message_id: 每次作答生成的 UUID → <uuid>",
    "body.text 中的『（记录 [0-9a-f]{8}）』: 由本轮上传的随机 version UUID 派生 → 『（记录 <record-ref>）』",
    "body.sources[].source_id: 本轮索引内的 UUID → <uuid>",
    "body.sources[].published_at: 发布时间戳 → <timestamp>",
    "body.conflicts[].entries[].source_id: UUID → <uuid>",
)
#: 只断言、不记录值的响应头（避免把随机 trace_id 写进 golden 造成"自证"）。
ASSERTED_NOT_RECORDED: tuple[str, ...] = (
    "X-Trace-ID: 必须存在且为 32 位小写十六进制（值随机，不写入 golden）",
    "X-Request-ID: 必须存在（值随机，不写入 golden）",
)


# --------------------------------------------------------------------------- #
# golden 归一化（实现必须与 NORMALISED_FIELDS 一致）
# --------------------------------------------------------------------------- #


def normalise_chat_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """把问答响应归一化为与 golden 可比的对象；只剔除易变字段，不裁剪业务语义。"""
    body: dict[str, Any] = json.loads(json.dumps(dict(payload), ensure_ascii=False))
    for key in ("request_id", "message_id"):
        value = body.get(key)
        assert isinstance(value, str) and UUID_TEXT_RE.fullmatch(value), (key, value)
        body[key] = "<uuid>"
    text = body.get("text")
    assert isinstance(text, str) and text
    body["text"] = RECORD_REF_RE.sub("（记录 <record-ref>）", text)
    for source in body.get("sources") or ():
        value = source.get("source_id")
        assert isinstance(value, str) and UUID_TEXT_RE.fullmatch(value), value
        source["source_id"] = "<uuid>"
        if source.get("published_at") is not None:
            assert ISO_TIMESTAMP_RE.match(str(source["published_at"])), source["published_at"]
            source["published_at"] = "<timestamp>"
    for conflict in body.get("conflicts") or ():
        for entry in conflict.get("entries") or ():
            value = entry.get("source_id")
            assert isinstance(value, str) and UUID_TEXT_RE.fullmatch(value), value
            entry["source_id"] = "<uuid>"
    return body


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 业务问答场景（真实 HTTP + 真实检索 + 确定性模型替身）
# --------------------------------------------------------------------------- #


def _dataset_xlsx(path: Path) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "台账"
    worksheet.cell(row=1, column=1, value="物品位置台账")
    for column, header in enumerate(T003D_HEADERS, start=1):
        worksheet.cell(row=6, column=column, value=header)
    for offset, row in enumerate(T003D_ROWS):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=7 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _publish_dataset(app) -> None:
    """管理员上传 → worker → 发布；文件名固定（标题会进入证据文本）。"""
    admin = open_session(app, "admin", "AdminPass-1")
    receipt = admin.upload(path=_dataset_xlsx(Path(app.state.settings.data_dir) / "t003d-dataset.xlsx"))
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
        revision = get_revision(db)
    finally:
        db.close()
    published = admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=admin.headers,
        json={"expected_active_version_id": None, "expected_revision": revision},
    )
    assert published.status_code == 200, published.text


def _ask(app):
    """员工新建会话并提问，返回原始响应（用于状态码/响应头/body 断言）。"""
    employee = open_session(app, "employee", "EmployeePass-1")
    conversation = employee.client.post("/api/v1/conversations", json={}, headers=employee.headers)
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    return employee.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": CHAT_QUESTION},
        headers=employee.headers,
    )


def _chat_scenario(app):
    _publish_dataset(app)
    response = _ask(app)
    assert response.status_code == 200, response.text
    return response


# --------------------------------------------------------------------------- #
# 1. 业务行为不变（归一化后与 golden 比对 + X-Trace-ID）
# --------------------------------------------------------------------------- #


def test_acceptance_01_business_behavior_unchanged(trace_chat_app) -> None:
    assert GOLDEN.is_file(), f"golden 缺失: {GOLDEN}"
    golden = _read_json(GOLDEN)
    meta = golden["_meta"]
    # golden 的可信性：来源、采集命令、归一化清单必须与实现一致（文档不得静默漂移）。
    assert meta["captured_from_commit"] and meta["capture_command"]
    assert tuple(meta["normalised_fields"]) == NORMALISED_FIELDS
    assert tuple(meta["asserted_not_recorded"]) == ASSERTED_NOT_RECORDED

    response = _chat_scenario(trace_chat_app)
    assert response.status_code == golden["http_status"] == 200
    trace_header = response.headers.get("X-Trace-ID")
    assert trace_header and TRACE_ID_RE.fullmatch(trace_header), trace_header
    assert response.headers.get("X-Request-ID"), "业务响应必须带 X-Request-ID"

    actual = normalise_chat_payload(response.json())
    assert actual == golden["normalised_body"]
    # 归一化必须真的剔除了易变字段：golden 与实测里都不应残留 UUID / 时间戳。
    serialised = json.dumps(actual, ensure_ascii=False)
    assert not UUID_TEXT_RE.search(serialised), serialised[:400]
    assert not ISO_TIMESTAMP_RE.search(serialised), serialised[:400]

    # 重跑稳定：同一应用内再开一个会话问同一句，归一化结果仍等于 golden（非一次性巧合）。
    repeated = normalise_chat_payload(_ask(trace_chat_app).json())
    assert repeated == actual == golden["normalised_body"]


# --------------------------------------------------------------------------- #
# 2. trace_id 端到端可查
# --------------------------------------------------------------------------- #


def test_acceptance_02_trace_id_is_queryable_end_to_end(trace_chat_app, trace_db_path) -> None:
    response = _chat_scenario(trace_chat_app)
    body = response.json()
    trace_id = response.headers["X-Trace-ID"]
    assert TRACE_ID_RE.fullmatch(trace_id)

    record, spans = trace_chat_app.state.trace_repo.get(trace_id)
    assert record.trace_id == trace_id
    assert record.request_id == body["request_id"], "trace.request_id 必须是本次业务请求"
    assert record.http_request_id == response.headers["X-Request-ID"]
    assert record.path == TracePath.RAG.value
    assert record.outcome_kind == OutcomeKind.ANSWER.value
    assert record.status == "ok"
    assert spans, "trace 必须至少有一个 Span"
    names = {span.name for span in spans}
    assert required_spans(TracePath.RAG, OutcomeKind.ANSWER) <= names
    assert validate_required_spans(record, names) == []

    # 端到端可查：换一个只读仓储实例（重新打开落盘库）仍能按同一 trace_id 查到。
    reopened = TraceRepository(trace_db_path)
    try:
        persisted, persisted_spans = reopened.get(trace_id)
    finally:
        reopened.close()
    assert persisted.trace_id == trace_id
    assert persisted.request_id == body["request_id"]
    assert {span.name for span in persisted_spans} == names


# --------------------------------------------------------------------------- #
# 3. b0 / badcase 可独立回归
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def b0_local_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("t008b-b0") / "local"
    return run_suite("b0", "local", corpus_dir=ACCEPTANCE, out_dir=out, scope="end_to_end")


@pytest.fixture(scope="module")
def badcase_local_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("t008b-badcase") / "local"
    return run_suite("badcase", "local", out_dir=out, scope="end_to_end")


def test_acceptance_03_b0_and_badcase_regress_independently(
    b0_local_run, badcase_local_run
) -> None:
    expectations = (
        (b0_local_run, "b0", 40, 32, 8),
        (badcase_local_run, "badcase", 13, 13, 0),
    )
    for run, suite, case_count, scored, skipped_ocr in expectations:
        assert (run.out_dir / "summary.json").is_file()
        assert (run.out_dir / "run_manifest.json").is_file()
        assert (run.out_dir / "cases.jsonl").is_file()
        assert (run.out_dir / "traces.sqlite3").is_file()
        summary = _read_json(run.summary_path)
        assert summary["suite"] == suite
        assert summary["case_count"] == case_count
        assert summary["scored_count"] == scored
        assert summary["skipped_ocr_count"] == skipped_ocr
        assert summary["error_count"] == 0
        assert len(run.cases) == case_count
        assert all(str(row["suite"]) == suite for row in run.cases)

    # 独立：不同 run_manifest、不同 case 集合、不同产物目录（互不覆盖）。
    b0_ids = {str(row["case_id"]) for row in b0_local_run.cases}
    badcase_ids = {str(row["case_id"]) for row in badcase_local_run.cases}
    assert b0_ids.isdisjoint(badcase_ids)
    assert b0_local_run.out_dir != badcase_local_run.out_dir
    assert b0_local_run.manifest.run_id != badcase_local_run.manifest.run_id
    assert b0_local_run.manifest.dataset_sha256 != badcase_local_run.manifest.dataset_sha256

    # badcase 的检索分母口径（T006b）：13 条里 10 条有 gold，3 条无 gold。
    badcase_cases = load_cases(default_dataset_path("badcase"))
    assert len(badcase_cases) == 13
    assert sum(1 for case in badcase_cases if case.expected_sources or case.relevant_units) == 10


# --------------------------------------------------------------------------- #
# 4. 结果绑定 dataset_version / index_revision / pipeline_version
# --------------------------------------------------------------------------- #


def test_acceptance_04_results_bind_versions(b0_local_run, badcase_local_run) -> None:
    expectations = (
        (b0_local_run, "b0", 6),
        (badcase_local_run, "badcase", 4),
    )
    for run, suite, revision in expectations:
        manifest = _read_json(run.manifest_path)
        summary = _read_json(run.summary_path)
        cases = load_cases(default_dataset_path(suite))
        assert manifest["dataset_version"] == dataset_version(cases, manifest["label_version"])
        assert summary["dataset_version"] == manifest["dataset_version"]
        assert manifest["dataset_sha256"] == hashlib.sha256(
            default_dataset_path(suite).read_bytes()
        ).hexdigest()
        assert manifest["index_revision"] == summary["index_revision"] == revision
        assert len(manifest["pipeline_version"]) == 12
        assert summary["pipeline_version"] == manifest["pipeline_version"]
        assert manifest["gate_version"] == summary["gate_version"] == GATE_SCHEMA_VERSION

        # trace 与 run 清单同绑定（不只写在某个 JSON 里）。
        repo = TraceRepository(run.out_dir / "traces.sqlite3")
        try:
            row = next(row for row in run.cases if row["status"] == "pass")
            record, _spans = repo.get(str(row["trace_id"]))
        finally:
            repo.close()
        assert record.dataset_version == manifest["dataset_version"]
        assert record.index_revision == str(revision)
        assert record.pipeline_version == manifest["pipeline_version"]
        assert record.run_id == manifest["run_id"]

    # 同一代码跑两个 suite：pipeline_version 必须一致（版本绑定的是实现，不是数据）。
    assert b0_local_run.manifest.pipeline_version == badcase_local_run.manifest.pipeline_version
    assert b0_local_run.manifest.dataset_version != badcase_local_run.manifest.dataset_version


# --------------------------------------------------------------------------- #
# 5. baseline + diff + JSON 报告（测试内审批配置，真实审批仍待 T009）
# --------------------------------------------------------------------------- #

#: 测试内审批配置覆盖的指标：检索 5 + 答案 5；refusal / runtime 指标需要真实成本/延迟
#: 样本，P0 离线跑没有成本数据，故本配置不覆盖它们（不是 T009 审批，也不代表质量达标）。
TEST_APPROVED_METRICS: tuple[str, ...] = (
    "Recall@10",
    "MRR@10",
    "nDCG@10",
    "hard_filter_violation_rate",
    "empty_recall_rate",
    "value_hit",
    "source_hit",
    "kind_correct",
    "citation_precision",
    "citation_recall",
)


def _write_test_approved_config(directory: Path) -> Path:
    payload = json.loads(DEFAULT_GATE_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["status"] = "approved"
    payload["notes"] = (
        "T008b 测试内审批配置（仅验证 gate/baseline/diff/报告机制）；"
        "不是 T009 人工审批，也不代表质量达标。"
    )
    metrics = []
    for spec in payload["metrics"]:
        if spec["name"] not in TEST_APPROVED_METRICS:
            continue
        spec = dict(spec)
        spec["min_sample"] = 1
        if spec["direction"] == "higher_is_better":
            spec["absolute_min"] = 0.0
        else:
            spec["absolute_max"] = 1e9
        metrics.append(spec)
    payload["metrics"] = metrics
    path = directory / "gate_test_approved.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_acceptance_05_baseline_diff_and_json_report(tmp_path: Path) -> None:
    config = _write_test_approved_config(tmp_path)
    run_dir = tmp_path / "run"
    baselines = tmp_path / "baselines"

    assert cli.main(["run", "--suite", "b0", "--out", str(run_dir)]) == 0
    manifest = _read_json(run_dir / "run_manifest.json")

    # (a) 默认配置 = 阈值未审批 → exit 3，且不允许建立/审批 baseline。
    assert cli.main(["gate", "--run", str(run_dir)]) == 3
    default_gate = _read_json(run_dir / "gate.json")
    assert default_gate["exit_code"] == 3
    assert default_gate["quality"]["config_status"] == "unapproved"
    assert cli.main(
        [
            "baseline",
            "approve",
            "--run",
            str(run_dir),
            "--gate",
            str(run_dir / "gate.json"),
            "--approver",
            "t008b-test-only",
            "--reason",
            "must be rejected: thresholds unapproved",
            "--root",
            str(baselines),
        ]
    ) == 3
    assert list(baselines.rglob("approval.json")) == [], "未审批配置不得写 approval.json"

    # (b) 测试内审批配置 → gate 0；baseline 审批绑定该次门禁结果。
    assert cli.main(["gate", "--run", str(run_dir), "--config", str(config)]) == 0
    approved_gate = _read_json(run_dir / "gate.json")
    assert approved_gate["exit_code"] == 0
    assert approved_gate["quality"]["status"] == "pass"
    assert approved_gate["quality"]["config_status"] == "approved"
    assert cli.main(
        [
            "baseline",
            "approve",
            "--run",
            str(run_dir),
            "--gate",
            str(run_dir / "gate.json"),
            "--approver",
            "t008b-test-only",
            "--reason",
            "test-only approval for acceptance #5; real baseline waits for T009",
            "--root",
            str(baselines),
            "--config",
            str(config),
        ]
    ) == 0
    baseline_dirs = [path for path in baselines.iterdir() if path.is_dir()]
    assert len(baseline_dirs) == 1
    approval = _read_json(baseline_dirs[0] / "approval.json")
    baseline = _read_json(baseline_dirs[0] / "baseline.json")
    assert baseline["baseline_id"] == baseline_dirs[0].name
    assert baseline["run_id"] == manifest["run_id"]
    assert approval["gate_exit_code"] == 0
    assert approval["quality_status"] == "pass"
    assert approval["approver"] == "t008b-test-only"
    # 审批绑定的是**具体一份**门禁结果：approval 摘要 = 该 gate.json 的 canonical SHA-256。
    canonical = json.dumps(approved_gate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert approval["gate_result_sha256"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert baseline["gate"]["gate_result_sha256"] == approval["gate_result_sha256"]

    # (c) diff：release 基线对比 + JSON 报告 + Markdown/HTML 渲染。
    assert cli.main(
        [
            "diff",
            "--run",
            str(run_dir),
            "--root",
            str(baselines),
            "--config",
            str(config),
        ]
    ) == 0
    diff = _read_json(run_dir / "diff.json")
    assert diff["comparison"] == "release_baseline"
    assert diff["release_allowed"] is True
    assert diff["release_blocked_reason"] in (None, "")
    assert diff["baseline_run_id"] == diff["run_id"] == manifest["run_id"]
    assert diff["metric_deltas"], "diff 必须逐指标列出（JSON 报告）"
    assert diff["empty"] is True
    assert {item["status"] for item in diff["metric_deltas"]} == {"unchanged"}
    assert diff["new_failures"] == [] and diff["new_errors"] == []
    for name in ("report.md", "report.html"):
        artifact = run_dir / name
        assert artifact.is_file() and artifact.stat().st_size > 0, name


# --------------------------------------------------------------------------- #
# 6. 硬门禁失败 → 非零退出码（敏感来源 case → security_leak → 1）
# --------------------------------------------------------------------------- #


def _b0_with_forbidden_source(directory: Path) -> Path:
    """把 Q01 自己的 gold unit 声明为 forbidden：真实引用它就是敏感来源泄漏。"""
    rows = [
        json.loads(line)
        for line in B0_DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    target = next(row for row in rows if row["case_id"] == "Q01")
    assert target["expected_sources"], "Q01 必须有 gold 引用"
    target["forbidden_sources"] = [dict(target["expected_sources"][0])]
    path = directory / "b0_forbidden_source.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def test_acceptance_06_hard_gate_failure_returns_nonzero_exit(tmp_path: Path) -> None:
    dataset = _b0_with_forbidden_source(tmp_path)
    run_dir = tmp_path / "run"
    assert cli.main(
        ["run", "--suite", "b0", "--dataset", str(dataset), "--out", str(run_dir)]
    ) == 0

    assert cli.main(["gate", "--run", str(run_dir)]) == 1
    gate = _read_json(run_dir / "gate.json")
    assert gate["exit_code"] == 1
    assert "security_leak" in gate["hard_failures"]
    assert gate["gate_status"]["security_leak"] == "fail"
    hits = [
        failure
        for failure in gate["failures"]
        if failure["gate_id"] == "security_leak" and failure["case_id"] == "Q01"
    ]
    assert any(failure["check_id"] == "forbidden_source_citation" for failure in hits), hits
    # 样本充足（不让 exit 1 被误读成样本不足或配置错误）。
    assert gate["scored_count"] == 32 and gate["min_sample"] == 32


# --------------------------------------------------------------------------- #
# 7. 零真实调用（provider spy=0 / socket=0 / 不读 .env）
# --------------------------------------------------------------------------- #


def test_acceptance_07_zero_real_calls(tmp_path: Path, monkeypatch, trace_chat_app, chat_model) -> None:
    import mktkb.config as app_config
    import mktkb.rag.providers as providers

    calls: list[str] = []
    connects: list[object] = []
    env_reads: list[str] = []
    original_connect = socket.socket.connect

    def provider_guard(*args, **kwargs):
        calls.append("called")
        raise AssertionError("P0 验收不得调用真实 provider")

    def socket_guard(self, address):
        connects.append(address)
        raise AssertionError("P0 验收不得尝试 socket 出网")

    real_read_bytes = Path.read_bytes
    real_read_text = Path.read_text

    def guarded_read_bytes(self):
        if self.name == ".env":
            env_reads.append(str(self))
        return real_read_bytes(self)

    def guarded_read_text(self, *args, **kwargs):
        if self.name == ".env":
            env_reads.append(str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(providers.BailianEmbeddingProvider, "embed", provider_guard)
    monkeypatch.setattr(providers.BailianRerankProvider, "rerank", provider_guard)
    monkeypatch.setattr(providers.DeepSeekChatProvider, "complete", provider_guard)
    monkeypatch.setattr(socket.socket, "connect", socket_guard)
    monkeypatch.setattr(app_config.Settings, "__init__", provider_guard)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    # 评测全流程（local run + 门禁）在 socket / provider / Settings 守卫下运行：
    # 默认配置不可判定 → exit 3，不是失败。
    run = run_suite("badcase", "local", out_dir=tmp_path / "offline")
    gate = evaluate_gate(run, config=load_gate_config(DEFAULT_GATE_CONFIG_PATH), quality=True)
    assert len(run.cases) == 13
    assert gate.exit_code == 3
    assert gate.quality is not None and gate.quality.config_status == "unapproved"
    assert calls == [] and connects == []
    # ``socket.socket.connect`` 的拦截会误伤 asyncio 自管道（TestClient 的 loopback socketpair），
    # 因此业务问答阶段只保留 provider / Settings / .env 守卫；socket 守卫只作用于评测全流程。
    monkeypatch.setattr(socket.socket, "connect", original_connect)

    # 业务问答（真实 HTTP + 真实检索）同样零模型调用：RAG 路径由内核作答。
    response = _chat_scenario(trace_chat_app)
    assert response.status_code == 200

    assert calls == [], f"provider 被调用: {calls}"
    assert connects == [], f"发生 socket 连接: {connects}"
    assert env_reads == [], f"读取了 .env: {env_reads}"
    assert chat_model.calls == [], f"业务路径调用了模型: {chat_model.calls}"
    # 测试进程的 Settings 默认 env_file 已被隔离（不会读仓库根 .env）。
    from mktkb.config import Settings

    assert Settings.model_config.get("env_file") is None
