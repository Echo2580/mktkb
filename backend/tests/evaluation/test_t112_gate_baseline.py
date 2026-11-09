"""P1 T112：gate v0.2 解析/校准、全量 live 守卫与 P1 release baseline 机制。

全部离屏：fake embedder/reranker + 临时目录；不读真实 ``.env``、不发网络、不写共享
账本/GO、不改仓库 ``gate_v0_2.json``（只读）。真实 b0 全量 live 由 R0 在包内单独执行。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from mktkb.evaluation import live as live_module
from mktkb.evaluation.baseline import (
    BaselineApprovalError,
    BaselineIdentity,
    BaselineIdentityError,
    approve_baseline,
    baseline_id,
    load_baseline,
)
from mktkb.evaluation.dataset import load_cases, write_cases
from mktkb.evaluation.gate import (
    CONFIG_SCHEMA_VERSION_V0_2,
    DEFAULT_GATE_CONFIG_PATH,
    GATE_VERSION_V0_2,
    P1_GATE_CONFIG_PATH,
    RETRIEVAL_METRIC_DIRECTIONS,
    calibrate_gate,
    evaluate_gate,
    load_gate_config,
    write_gate_proposal,
)
from mktkb.evaluation.live import (
    FROZEN_FULL_LIVE_DATASET,
    LIVE_SCOPE,
    LiveConfigError,
    LiveRuntime,
    validate_full_live_dataset,
)
from mktkb.evaluation.runner import run_suite
from mktkb.observability.contracts import GATE_SCHEMA_VERSION
from mktkb.rag.config import RagConfig
from mktkb.rag.types import EmbeddingResponse, RerankResponse, RerankResult


# --------------------------------------------------------------------------- #
# fake provider（离线；不读凭据/不写账本）
# --------------------------------------------------------------------------- #


class _FakeBudget:
    def __init__(self, *, stage_remaining: float = 3.0, reservation_count: int = 381) -> None:
        self._summary = SimpleNamespace(
            stage="P1-RETRIEVAL",
            stage_limit_cny=3.0,
            stage_accounted_cny=0.0,
            stage_remaining_cny=stage_remaining,
            total_limit_cny=20.0,
            historical_conservative_cny=15.0566296,
            accounted_cny=15.0566296,
            remaining_cny=20.0 - 15.0566296,
            success_estimated_list_price_cny=0.0,
            provider_billed_cny=None,
            reservation_count=reservation_count,
            result_count=reservation_count,
        )

    def summary(self) -> SimpleNamespace:
        return self._summary


class _FakeEmbedder:
    provider = "bailian"
    model = "text-embedding-v4"
    dimensions = 1024

    def embed(self, texts, *, purpose: str = "document") -> EmbeddingResponse:
        vectors = tuple((1.0,) + (0.0,) * 1023 for _ in texts)
        return EmbeddingResponse(
            vectors=vectors,
            model=self.model,
            dimensions=self.dimensions,
            provider=self.provider,
            usage={"total_tokens": max(1, len(texts) * 10)},
        )

    def close(self) -> None:
        return None


class _FakeReranker:
    provider = "bailian"
    model = "gte-rerank-v2"

    def rerank(self, query, documents, *, top_n=None) -> RerankResponse:
        return RerankResponse(
            results=tuple(
                RerankResult(index=index, score=1.0 / (index + 1))
                for index in range(len(documents))
            ),
            model=self.model,
            provider=self.provider,
            usage={"total_tokens": max(1, len(documents) * 10)},
        )

    def close(self) -> None:
        return None


def _runtime(tmp_path: Path) -> LiveRuntime:
    config = RagConfig(
        provider_mode="live",
        data_dir=tmp_path / "index",
        business_date="2026-10-28",
        embedding_api_key="unit-test-key",
        rerank_api_key="unit-test-key",
        embedding_batch_size=5,
        chunk_max_chars=420,
        chunk_max_units=3,
        chunk_overlap_units=1,
        top_k=8,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=10,
        max_request_cny=0.05,
        max_retries=0,
        require_zero_retries=True,
        stage="P1-RETRIEVAL",
        stage_limit_cny=3.0,
    )
    return LiveRuntime(
        config=config,
        budget=_FakeBudget(),
        stage="P1-RETRIEVAL",
        service="rag",
        stage_limit_cny=3.0,
        max_requests=1000,
        max_request_cny=0.05,
        authorization=None,
        ledger_path=None,
        budget_path=None,
        go_path=None,
        credentials_source="unit-test",
        embedder=_FakeEmbedder(),
        reranker=_FakeReranker(),
    )


def _run_full_live(tmp_path: Path, dataset: Path = FROZEN_FULL_LIVE_DATASET):
    return run_suite(
        "b0",
        "live",
        scope=LIVE_SCOPE,
        dataset_path=dataset,
        out_dir=tmp_path / "run",
        allow_full_live=True,
        live_runtime=_runtime(tmp_path),
        live_env_file=None,
    )


@pytest.fixture(scope="module")
def full_live_run(tmp_path_factory) -> object:
    """用 fake provider 跑一次与真实全量同形状的 40 题 live run（零网络）。"""
    root = tmp_path_factory.mktemp("t112-full-live")
    return _run_full_live(root)


def _payload() -> dict:
    return json.loads(P1_GATE_CONFIG_PATH.read_text(encoding="utf-8"))


def _write_payload(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "gate.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# v0.2 配置契约
# --------------------------------------------------------------------------- #


def test_gate_v0_2_config_contract() -> None:
    config = load_gate_config(P1_GATE_CONFIG_PATH)
    assert config.schema_version == CONFIG_SCHEMA_VERSION_V0_2
    assert config.gate_version == GATE_VERSION_V0_2
    assert config.status == "unapproved"
    assert len(config.hard_gates) == 8
    assert "regression" in config.suites
    assert dict(config.min_sample) == {"b0": 32, "badcase": 13, "regression": 7}
    assert len(config.config_hash) == 64

    retrieval = {spec.name: spec for spec in config.metrics if spec.group == "retrieval"}
    assert set(retrieval) == set(RETRIEVAL_METRIC_DIRECTIONS)
    for name, direction in RETRIEVAL_METRIC_DIRECTIONS.items():
        assert retrieval[name].direction == direction

    raw = _payload()
    for item in raw["metrics"]:
        assert {"min_sample", "absolute_min", "absolute_max", "max_regression_pp"} <= set(item)
    assert raw["status"] == "unapproved"


def test_v0_1_config_still_loads_unchanged() -> None:
    config = load_gate_config(DEFAULT_GATE_CONFIG_PATH)
    assert config.schema_version == "mktkb.gate.config.v0.1"
    assert config.gate_version == GATE_SCHEMA_VERSION
    assert config.suites == ()
    assert len(config.metrics) == 15


def test_gate_v0_2_rejects_incomplete_config(tmp_path: Path) -> None:
    payload = _payload()
    payload.pop("suites")
    with pytest.raises(ValueError, match="regression"):
        load_gate_config(_write_payload(tmp_path, payload))

    payload = _payload()
    payload["suites"] = ["b0", "badcase"]
    with pytest.raises(ValueError, match="regression"):
        load_gate_config(_write_payload(tmp_path, payload))

    payload = _payload()
    payload["gate_version"] = "mktkb.gate.v0.1"
    with pytest.raises(ValueError, match="gate_version"):
        load_gate_config(_write_payload(tmp_path, payload))

    payload = _payload()
    payload["metrics"] = [item for item in payload["metrics"] if item["name"] != "MRR@10"]
    with pytest.raises(ValueError, match="检索 5 指标"):
        load_gate_config(_write_payload(tmp_path, payload))

    payload = _payload()
    payload["metrics"][0].pop("max_regression_pp")
    with pytest.raises(ValueError, match="v0.2 必填字段"):
        load_gate_config(_write_payload(tmp_path, payload))


# --------------------------------------------------------------------------- #
# 全量 live 守卫
# --------------------------------------------------------------------------- #


def test_full_live_guard_accepts_only_frozen_b0_40(tmp_path: Path) -> None:
    cases = load_cases(FROZEN_FULL_LIVE_DATASET)
    digest = validate_full_live_dataset(
        suite="b0", dataset_path=FROZEN_FULL_LIVE_DATASET, cases=cases
    )
    assert digest == hashlib.sha256(FROZEN_FULL_LIVE_DATASET.read_bytes()).hexdigest()

    with pytest.raises(LiveConfigError, match="suite='b0'"):
        validate_full_live_dataset(
            suite="badcase", dataset_path=FROZEN_FULL_LIVE_DATASET, cases=cases
        )

    short = tmp_path / "b0-39.jsonl"
    write_cases(short, cases[:39])
    with pytest.raises(LiveConfigError, match="恰好 40"):
        validate_full_live_dataset(suite="b0", dataset_path=short, cases=load_cases(short))

    tampered = tmp_path / "b0-tampered.jsonl"
    write_cases(tampered, [replace(cases[0], question=cases[0].question + "（改）"), *cases[1:]])
    with pytest.raises(LiveConfigError, match="字节级"):
        validate_full_live_dataset(
            suite="b0", dataset_path=tampered, cases=load_cases(tampered)
        )


def test_full_live_rejects_pilot_combination_and_wrong_suite(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    with pytest.raises(LiveConfigError, match="互斥"):
        run_suite(
            "b0",
            "live",
            scope=LIVE_SCOPE,
            dataset_path=FROZEN_FULL_LIVE_DATASET,
            pilot_cases=10,
            out_dir=tmp_path / "pilot",
            allow_full_live=True,
            live_runtime=runtime,
            live_env_file=None,
        )
    with pytest.raises(LiveConfigError, match="suite='b0'"):
        run_suite(
            "badcase",
            "live",
            scope=LIVE_SCOPE,
            dataset_path=FROZEN_FULL_LIVE_DATASET,
            out_dir=tmp_path / "badcase",
            allow_full_live=True,
            live_runtime=_runtime(tmp_path),
            live_env_file=None,
        )


def test_live_cli_without_allow_full_live_refuses_before_go() -> None:
    # 默认关闭：40 题数据集在 GO/凭据检查前就被拒绝（exit 3，零 HTTP/零预留）。
    assert live_module.main(
        ["--suite", "b0", "--dataset", str(FROZEN_FULL_LIVE_DATASET), "--dry-run"]
    ) == 3


# --------------------------------------------------------------------------- #
# live run 的 manifest 与 gate v0.2 判定
# --------------------------------------------------------------------------- #


def test_full_live_manifest_versions(full_live_run) -> None:
    manifest = full_live_run.manifest
    assert manifest.mode == "live"
    assert manifest.scope == LIVE_SCOPE
    assert manifest.suite == "b0"
    assert manifest.case_count == 40
    assert manifest.gate_version == GATE_VERSION_V0_2
    assert manifest.dataset_sha256 == hashlib.sha256(
        FROZEN_FULL_LIVE_DATASET.read_bytes()
    ).hexdigest()
    live_block = dict(full_live_run.summary.get("live") or {})
    assert live_block["full_live"] is True
    assert live_block["pilot"] is False
    assert live_block["chat_calls"] == 0
    assert live_block["retries"] == 0
    assert full_live_run.aborted is False
    assert len(full_live_run.cases) == 40


def test_live_gate_v0_2_is_unknown_not_pass(full_live_run) -> None:
    config = load_gate_config(P1_GATE_CONFIG_PATH)
    result = evaluate_gate(full_live_run, config=config, quality=True)
    assert result.exit_code == 3, result.to_dict()
    assert result.hard_failures == ()
    assert result.gate_version == GATE_VERSION_V0_2
    assert result.quality is not None
    assert result.quality.config_status == "unapproved"
    assert result.quality.status == "unknown"
    assert {item.group for item in result.quality.metrics} == {"retrieval"}
    assert any(
        unknown.check_id == "thresholds_unapproved" for unknown in result.unknowns
    )
    # 答案类硬门禁在 retrieval_only 下显式 not_applicable，不伪造通过。
    assert result.gate_status["exact_value_contract"] == "not_applicable"
    assert result.gate_status["citation_required"] == "not_applicable"


def test_live_gate_v0_1_still_exits_four(full_live_run) -> None:
    config = load_gate_config(DEFAULT_GATE_CONFIG_PATH)
    assert evaluate_gate(full_live_run, config=config).exit_code == 4


# --------------------------------------------------------------------------- #
# 校准可复现 / 不写回配置
# --------------------------------------------------------------------------- #


def test_calibration_is_reproducible_and_never_writes_config(tmp_path: Path, full_live_run) -> None:
    config = load_gate_config(P1_GATE_CONFIG_PATH)
    before = P1_GATE_CONFIG_PATH.read_bytes()

    first = calibrate_gate(full_live_run, config)
    second = calibrate_gate(full_live_run, config)
    path_a = write_gate_proposal(first, tmp_path / "a.json")
    path_b = write_gate_proposal(second, tmp_path / "b.json")
    assert path_a.read_bytes() == path_b.read_bytes()

    proposal = json.loads(path_a.read_text(encoding="utf-8"))
    assert proposal["status"] == "unapproved"
    assert proposal["run_id"] == full_live_run.manifest.run_id
    assert proposal["gate_config_hash"] == config.config_hash
    assert {row["group"] for row in proposal["metrics"]} == {"retrieval"}
    assert {row["metric"] for row in proposal["metrics"]} == set(RETRIEVAL_METRIC_DIRECTIONS)
    assert all(row["status"] == "unapproved" for row in proposal["metrics"])

    with pytest.raises(ValueError, match="不得用校准提案覆盖"):
        write_gate_proposal(first, P1_GATE_CONFIG_PATH, overwrite=True)
    assert P1_GATE_CONFIG_PATH.read_bytes() == before


# --------------------------------------------------------------------------- #
# P1 release baseline：身份 / 审批前置 / 审批接受
# --------------------------------------------------------------------------- #


def test_live_baseline_identity_requires_gate_v0_2(full_live_run) -> None:
    identity = BaselineIdentity.from_dict(
        {
            "dataset_version": full_live_run.manifest.dataset_version,
            "pipeline_version": full_live_run.manifest.pipeline_version,
            "mode": "live",
            "scope": LIVE_SCOPE,
            "gate_version": GATE_VERSION_V0_2,
            "corpus_sha256": full_live_run.manifest.corpus_manifest_sha256,
        }
    )
    assert identity.baseline_id == baseline_id(full_live_run.manifest)

    with pytest.raises(BaselineIdentityError):
        baseline_id(replace(full_live_run.manifest, gate_version=GATE_SCHEMA_VERSION))
    with pytest.raises(BaselineIdentityError):
        BaselineIdentity(
            dataset_version=full_live_run.manifest.dataset_version,
            pipeline_version=full_live_run.manifest.pipeline_version,
            mode="live",
            scope=LIVE_SCOPE,
            gate_version=GATE_SCHEMA_VERSION,
            corpus_sha256=full_live_run.manifest.corpus_manifest_sha256,
        )


def test_baseline_approve_refuses_unapproved_gate(tmp_path: Path, full_live_run) -> None:
    config = load_gate_config(P1_GATE_CONFIG_PATH)
    gate = evaluate_gate(full_live_run, config=config, quality=True)
    with pytest.raises(BaselineApprovalError, match="门禁未通过"):
        approve_baseline(
            full_live_run,
            gate,
            tmp_path / "baselines",
            approver="pm",
            reason="owner-approved",
        )
    with pytest.raises(BaselineApprovalError, match="approver"):
        approve_baseline(full_live_run, gate, tmp_path / "baselines", approver="", reason="x")
    assert not (tmp_path / "baselines").exists()


def _approved_live_config(tmp_path: Path) -> Path:
    payload = _payload()
    payload["status"] = "approved"
    for item in payload["metrics"]:
        if item["group"] != "retrieval":
            continue
        item["min_sample"] = 1
        item["absolute_min"] = 0.0
        item["absolute_max"] = 1.0
        item["max_regression_pp"] = 2.0
    return _write_payload(tmp_path, payload)


def test_baseline_approve_accepts_approved_live_gate(tmp_path: Path, full_live_run) -> None:
    config = load_gate_config(_approved_live_config(tmp_path))
    assert config.status == "approved"
    gate = evaluate_gate(full_live_run, config=config, quality=True)
    assert gate.exit_code == 0, gate.to_dict()

    root = tmp_path / "baselines"
    baseline = approve_baseline(
        full_live_run, gate, root, approver="pm", reason="owner-approved"
    )
    assert baseline.approved
    assert baseline.approval is not None
    assert baseline.approval.run_id == full_live_run.manifest.run_id
    assert baseline.approval.approver == "pm"
    assert baseline.identity.mode == "live"
    assert baseline.identity.scope == LIVE_SCOPE
    assert baseline.identity.gate_version == GATE_VERSION_V0_2

    loaded = load_baseline(
        baseline.baseline_id, root, expected=full_live_run.manifest
    )
    assert loaded.approved
    assert loaded.baseline_id == baseline.baseline_id
