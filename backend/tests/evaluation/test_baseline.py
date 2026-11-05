"""T007：baseline 身份 / 建立 / 审批 / 加载 / 跨版本守卫（handoff §5.1–§5.3）。

口径（设计 §8.3，T006b 验收约束 1）：

``baseline_id = sha256(dataset_version + pipeline_version + mode + scope +
gate_version + corpus_sha256)[:12]``，六字段按顺序**字面拼接**后取 SHA-256 前 12 位；
门禁侧 ``max_regression_pp`` 只比较 pipeline/suite/dataset，不足以充当 baseline 身份。

全部用合成 ``RunResult`` 产物 + 合成 ``GateResult``（``tmp_path``），零真实模型 /
OCR / embedding / rerank 调用，不读 ``.env``，不写 ``var/``。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

import mktkb.evaluation.baseline as baseline_module
from mktkb.evaluation.baseline import (
    BASELINE_ID_FIELDS,
    BaselineApproval,
    BaselineApprovalError,
    BaselineComparabilityError,
    BaselineError,
    BaselineIdentity,
    BaselineIdentityError,
    CrossVersionBaselineError,
    approve_baseline,
    baseline_id,
    baseline_identity,
    gate_result_digest,
    load_baseline,
    save_baseline,
)
from mktkb.evaluation.dataset import CaseSpec, write_cases
from mktkb.evaluation.gate import GateResult, QualityResult
from mktkb.evaluation.runner import RunManifest, RunResult
from mktkb.observability.contracts import GATE_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[3]
DS_VERSION = "b0:dev-1:0123456789ab"
CORPUS_SHA = "b" * 64


# --------------------------------------------------------------------------- #
# 合成 run / gate
# --------------------------------------------------------------------------- #


def make_manifest(**overrides) -> RunManifest:
    payload = {
        "run_id": "run-b0-a",
        "mode": "local",
        "scope": "end_to_end",
        "suite": "b0",
        "dataset_version": DS_VERSION,
        "dataset_sha256": "a" * 64,
        "corpus_manifest_sha256": CORPUS_SHA,
        "business_date": "2026-10-28",
        "index_revision": 6,
        "pipeline_version": "pipeline1234",
        "gate_version": GATE_SCHEMA_VERSION,
        "label_version": "dev-1",
        "created_at": "2026-11-05T00:00:00.000+00:00",
        "case_count": 1,
        "config_hash": "c" * 12,
        "dataset_path": "",
    }
    payload.update(overrides)
    return RunManifest(**payload)


def make_case(case_id: str = "Q01", **overrides) -> CaseSpec:
    payload = {
        "case_id": case_id,
        "suite": "b0",
        "split": "dev",
        "stratum": "exact",
        "business_date": "2026-10-28",
        "question": f"{case_id} 的问题",
        "expected_kind": "answer",
        "expected_values": ("P01",),
        "expected_sources": ({"doc_code": "D01", "unit_key": "sheet:A:row:8"},),
        "labeler": "lead",
        "label_version": "dev-1",
    }
    payload.update(overrides)
    return CaseSpec(**payload)


def make_row(case: CaseSpec, **overrides) -> dict:
    row = {
        "case_id": case.case_id,
        "suite": case.suite,
        "status": "pass",
        "trace_id": f"trace-{case.case_id}",
        "previous_trace_id": None,
        "replayed": False,
        "checks": [],
        "metrics": {
            "Recall@10": 1.0,
            "MRR@10": 1.0,
            "nDCG@10": 1.0,
            "hard_filter_violations": 0,
            "retrieved_units": 1,
            "empty_recall": 0.0,
            "value_hit": 1.0,
            "source_hit": 1.0,
            "kind_correct": 1.0,
            "citation_precision": 1.0,
            "citation_recall": 1.0,
        },
        "refused": False,
        "should_refuse": bool(case.should_refuse),
        "path": "rag",
        "latency_ms": 10,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_cny": None,
        "duration_ms": 10,
        "turns_executed": 1,
        "multi_turn_claimed": False,
        "outcome": {"kind": "answer", "text": "P01", "citations": [], "retrieved": []},
        "gold": {"case_id": case.case_id, "sources": []},
        "error": None,
    }
    row.update(overrides)
    return row


def write_run(
    tmp_path: Path,
    name: str,
    *,
    cases: list[CaseSpec],
    rows: list[dict],
    manifest: RunManifest | None = None,
) -> RunResult:
    """写三件套（dataset + manifest/cases/summary）；不建 trace、不调 provider。"""
    run_dir = tmp_path / name
    run_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = tmp_path / f"{name}.dataset.jsonl"
    write_cases(dataset_path, cases)
    base = manifest or make_manifest(suite=cases[0].suite if cases else "b0")
    manifest = dataclasses.replace(
        base, dataset_path=str(dataset_path), case_count=len(cases)
    )
    (run_dir / "run_manifest.json").write_bytes(
        (json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
    )
    (run_dir / "cases.jsonl").write_bytes(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows
        ).encode("utf-8")
    )
    summary = {"run_id": manifest.run_id, "suite": manifest.suite, "mode": manifest.mode}
    (run_dir / "summary.json").write_bytes(
        (json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    return RunResult(manifest=manifest, out_dir=run_dir, cases=tuple(rows), summary=summary)


def make_gate(
    exit_code: int = 0,
    *,
    quality: bool = True,
    quality_status: str | None = None,
    config_status: str | None = None,
    run_id: str = "run-b0-a",
    suite: str = "b0",
    gate_version: str = GATE_SCHEMA_VERSION,
    hard_failures: tuple[str, ...] = (),
) -> GateResult:
    status = quality_status or {
        0: "pass",
        1: "pass",
        2: "fail",
        3: "unknown",
        4: "unknown",
    }.get(exit_code, "unknown")
    quality_result = (
        QualityResult(
            status=status,
            metrics=(),
            strata=("all",),
            stratum_status={"all": status},
            failures=(),
            unknowns=(),
            waived=(),
            diagnostics={},
            warnings=(),
            config_status=config_status or ("approved" if exit_code == 0 else "unapproved"),
            gate_config_hash="f" * 64,
            baseline_run_id=None,
            baseline_pipeline_version=None,
        )
        if quality
        else None
    )
    return GateResult(
        exit_code=exit_code,
        gate_status={gate_id: ("fail" if gate_id in hard_failures else "pass") for gate_id in ("security_leak", "citation_required")},
        hard_failures=hard_failures,
        failures=(),
        unknowns=(),
        not_applicable=(),
        warnings=(),
        run_id=run_id,
        suite=suite,
        mode="local",
        gate_version=gate_version,
        scored_count=1,
        min_sample=1,
        quality=quality_result,
    )


def one_case_run(tmp_path: Path, name: str = "run-a", **manifest_overrides) -> RunResult:
    case = make_case()
    manifest = make_manifest(**manifest_overrides)
    return write_run(tmp_path, name, cases=[case], rows=[make_row(case)], manifest=manifest)


# --------------------------------------------------------------------------- #
# §5.1 baseline 身份
# --------------------------------------------------------------------------- #


def test_baseline_id_matches_documented_formula():
    """身份口径写死：六字段按序字面拼接 → sha256 → 前 12 位（不是门禁的弱校验）。"""
    manifest = make_manifest()
    identity = baseline_identity(manifest)
    payload = "".join(
        [
            manifest.dataset_version,
            manifest.pipeline_version,
            manifest.mode,
            manifest.scope,
            manifest.gate_version,
            manifest.corpus_manifest_sha256,
        ]
    )
    expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    assert identity.baseline_id == expected
    assert baseline_id(manifest) == expected
    assert baseline_id(manifest.to_dict()) == expected
    assert identity.to_dict()["corpus_sha256"] == manifest.corpus_manifest_sha256
    assert tuple(identity.to_dict())[:6] == BASELINE_ID_FIELDS


def test_baseline_id_is_stable_for_same_identity():
    """run_id / 时间戳 / dataset_path 不参与身份：同输入必须稳定。"""
    first = make_manifest(run_id="run-1", created_at="2026-11-05T00:00:00.000+00:00")
    second = make_manifest(
        run_id="run-2",
        created_at="2026-11-06T12:00:00.000+00:00",
        dataset_path="D:/tmp/other.jsonl",
    )
    assert baseline_id(first) == baseline_id(second)


def test_baseline_id_changes_when_any_field_changes():
    """逐字段验证（尤其 pipeline_version）：任一字段变 → id 变。"""
    base = make_manifest()
    base_id = baseline_id(base)
    overrides = {
        "dataset_version": "b0:dev-2:0123456789ab",
        "pipeline_version": "pipeline9999",
        "mode": "replay",
        "scope": "retrieval_only",
        "gate_version": "mktkb.gate.v9.9",
        "corpus_manifest_sha256": "d" * 64,
    }
    assert set(overrides) == {
        "corpus_manifest_sha256" if name == "corpus_sha256" else name
        for name in BASELINE_ID_FIELDS
    }
    for field, value in overrides.items():
        changed = make_manifest(**{field: value})
        assert baseline_id(changed) != base_id, field
        assert baseline_identity(changed).to_dict()[field if field != "corpus_manifest_sha256" else "corpus_sha256"] == value


def test_baseline_id_fails_closed_on_missing_or_invalid_identity():
    with pytest.raises(BaselineIdentityError):
        baseline_id(make_manifest(dataset_version=""))
    with pytest.raises(BaselineIdentityError):
        baseline_id(make_manifest(pipeline_version=""))
    with pytest.raises(BaselineIdentityError):
        baseline_id(make_manifest(corpus_manifest_sha256=""))
    with pytest.raises(BaselineIdentityError):
        baseline_id(make_manifest(mode="live"))
    with pytest.raises(BaselineIdentityError):
        BaselineIdentity(
            dataset_version=DS_VERSION,
            pipeline_version="p",
            mode="live",
            scope="end_to_end",
            gate_version=GATE_SCHEMA_VERSION,
            corpus_sha256=CORPUS_SHA,
        )


def test_baseline_identity_roundtrip():
    identity = baseline_identity(make_manifest())
    restored = BaselineIdentity.from_dict(identity.to_dict())
    assert restored == identity
    assert restored.baseline_id == identity.baseline_id
    assert baseline_id(identity.to_dict()) == identity.baseline_id
    assert baseline_identity(identity.to_dict()) == identity
    with pytest.raises(BaselineIdentityError):
        BaselineIdentity.from_dict({"dataset_version": DS_VERSION})


def test_no_copy_or_rename_api():
    """设计 §8.3：禁止复制 / 改名旧 baseline 冒充新版本。"""
    names = [name for name in dir(baseline_module) if "copy" in name.lower() or "rename" in name.lower()]
    assert names == []
    assert not any("copy" in item.lower() or "rename" in item.lower() for item in baseline_module.__all__)


# --------------------------------------------------------------------------- #
# §5.2 保存 / 加载（自校验完整身份）
# --------------------------------------------------------------------------- #


def test_save_and_load_baseline_roundtrip(tmp_path: Path):
    run = one_case_run(tmp_path)
    saved = save_baseline(run, tmp_path / "baselines")
    assert saved.baseline_id == baseline_id(run.manifest)
    assert saved.identity == baseline_identity(run.manifest)
    assert saved.run_id == run.manifest.run_id
    assert saved.approval is None and saved.approved is False
    assert set(saved.artifact_sha256) == {"run_manifest.json", "cases.jsonl", "summary.json"}

    loaded = load_baseline(saved.baseline_id, tmp_path / "baselines")
    assert loaded.baseline_id == saved.baseline_id
    assert loaded.identity == saved.identity
    assert loaded.run_id == run.manifest.run_id
    assert loaded.load_run().manifest.pipeline_version == run.manifest.pipeline_version
    assert loaded.load_run().cases[0]["case_id"] == "Q01"


def test_save_baseline_requires_run_artifacts(tmp_path: Path):
    run = one_case_run(tmp_path)
    (run.out_dir / "cases.jsonl").unlink()
    with pytest.raises(BaselineError):
        save_baseline(run, tmp_path / "baselines")


def test_save_baseline_refuses_rebinding_same_identity_to_another_run(tmp_path: Path):
    """同身份（同 dataset/pipeline/mode/scope/gate/corpus）只能绑定一个 run。"""
    first = one_case_run(tmp_path, "run-a", run_id="run-b0-a")
    save_baseline(first, tmp_path / "baselines")
    second = one_case_run(tmp_path, "run-b", run_id="run-b0-b")
    assert baseline_id(first.manifest) == baseline_id(second.manifest)
    with pytest.raises(BaselineError):
        save_baseline(second, tmp_path / "baselines")


def test_load_baseline_rejects_tampered_identity_and_bad_id(tmp_path: Path):
    run = one_case_run(tmp_path)
    saved = save_baseline(run, tmp_path / "baselines")
    path = tmp_path / "baselines" / saved.baseline_id / "baseline.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["identity"]["pipeline_version"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BaselineIdentityError):
        load_baseline(saved.baseline_id, tmp_path / "baselines")

    for bad in ("", "0123456789abc", "ABCDEF012345", "../escape"):
        with pytest.raises(BaselineIdentityError):
            load_baseline(bad, tmp_path / "baselines")


# --------------------------------------------------------------------------- #
# §5.2 审批硬约束
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("kwargs", [{"approver": "", "reason": "ok"}, {"approver": "owner", "reason": " "}])
def test_approval_requires_approver_and_reason(tmp_path: Path, kwargs):
    run = one_case_run(tmp_path)
    with pytest.raises(BaselineApprovalError):
        approve_baseline(run, make_gate(0), tmp_path / "baselines", **kwargs)
    assert not (tmp_path / "baselines").exists()


@pytest.mark.parametrize("exit_code", [1, 2, 3, 4])
def test_approval_rejects_nonzero_gate(tmp_path: Path, exit_code: int):
    run = one_case_run(tmp_path)
    gate = make_gate(exit_code, quality_status="unknown")
    with pytest.raises(BaselineApprovalError) as excinfo:
        approve_baseline(
            run, gate, tmp_path / "baselines", approver="owner", reason="thresholds approved"
        )
    message = str(excinfo.value)
    assert f"exit_code={exit_code}" in message
    assert "baseline" in message
    if exit_code == 3:
        assert "阈值未审批" in message
    assert not (tmp_path / "baselines").exists()


def test_approval_rejects_unapproved_thresholds_exit_three(tmp_path: Path):
    """T006b 约束 4：quality=True 的干净 run 在阈值未审批时必然 exit 3 → 必须拒绝。"""
    run = one_case_run(tmp_path)
    gate = make_gate(3, quality_status="unknown")
    with pytest.raises(BaselineApprovalError, match="不可判定"):
        approve_baseline(run, gate, tmp_path / "baselines", approver="owner", reason="try")
    with pytest.raises(BaselineApprovalError, match="阈值未审批"):
        approve_baseline(run, gate, tmp_path / "baselines", approver="owner", reason="try")


def test_approval_rejects_exit_zero_without_quality_layer(tmp_path: Path):
    """quality=False 的 exit 0 只代表硬门禁通过，不能当 baseline 审批依据。"""
    run = one_case_run(tmp_path)
    with pytest.raises(BaselineApprovalError, match="质量层未评估"):
        approve_baseline(
            run,
            make_gate(0, quality=False),
            tmp_path / "baselines",
            approver="owner",
            reason="hard gate only",
        )


def test_approval_rejects_unapproved_config_status(tmp_path: Path):
    """T006b 约束 2：只有 top-level status=approved 才可能审批，quality status 只是元数据。"""
    run = one_case_run(tmp_path)
    gate = make_gate(0, quality_status="pass", config_status="unapproved")
    with pytest.raises(BaselineApprovalError, match="config_status"):
        approve_baseline(run, gate, tmp_path / "baselines", approver="owner", reason="forged")
    assert not (tmp_path / "baselines").exists()


def test_load_run_rejects_tampered_artifacts(tmp_path: Path):
    run = one_case_run(tmp_path)
    saved = save_baseline(run, tmp_path / "baselines")
    (run.out_dir / "cases.jsonl").write_bytes(b'{"tampered": true}\n')
    loaded = load_baseline(saved.baseline_id, tmp_path / "baselines")
    with pytest.raises(BaselineIdentityError):
        loaded.load_run()


def test_approval_rejects_gate_for_another_run(tmp_path: Path):
    run = one_case_run(tmp_path)
    with pytest.raises(BaselineApprovalError, match="run_id"):
        approve_baseline(
            run,
            make_gate(0, run_id="run-other"),
            tmp_path / "baselines",
            approver="owner",
            reason="wrong run",
        )


def test_approval_writes_complete_approval_json(tmp_path: Path):
    run = one_case_run(tmp_path)
    gate = make_gate(0)
    root = tmp_path / "baselines"
    approved = approve_baseline(
        run, gate, root, approver="owner", reason="T009 阈值审批 fixture"
    )
    assert approved.approved is True
    assert approved.gate is not None and approved.gate.exit_code == 0
    approval_path = root / approved.baseline_id / "approval.json"
    assert approval_path.is_file()
    payload = json.loads(approval_path.read_text(encoding="utf-8"))
    for key in (
        "run_id",
        "gate_result_sha256",
        "dataset_version",
        "pipeline_version",
        "corpus_sha256",
        "approver",
        "reason",
        "approved_at",
    ):
        assert key in payload and payload[key], key
    assert payload["run_id"] == run.manifest.run_id
    assert payload["gate_result_sha256"] == gate_result_digest(gate)
    assert payload["dataset_version"] == run.manifest.dataset_version
    assert payload["pipeline_version"] == run.manifest.pipeline_version
    assert payload["corpus_sha256"] == run.manifest.corpus_manifest_sha256
    assert payload["approver"] == "owner"
    assert payload["reason"] == "T009 阈值审批 fixture"
    assert payload["gate_exit_code"] == 0

    loaded = load_baseline(approved.baseline_id, root)
    assert isinstance(loaded.approval, BaselineApproval)
    assert loaded.approval.gate_result_sha256 == gate_result_digest(gate)
    assert loaded.approval.approver == "owner"


def test_approval_is_idempotent_but_never_overwritten(tmp_path: Path):
    run = one_case_run(tmp_path)
    gate = make_gate(0)
    root = tmp_path / "baselines"
    first = approve_baseline(run, gate, root, approver="owner", reason="ok")
    again = approve_baseline(run, gate, root, approver="owner", reason="ok")
    assert again.approval == first.approval
    with pytest.raises(BaselineApprovalError):
        approve_baseline(run, gate, root, approver="other", reason="rewrite")
    payload = json.loads((root / first.baseline_id / "approval.json").read_text(encoding="utf-8"))
    assert payload["approver"] == "owner"


# --------------------------------------------------------------------------- #
# §5.3 跨版本默认拒绝 / 显式 compare_with 仅分析
# --------------------------------------------------------------------------- #


def test_cross_version_load_requires_explicit_compare_with(tmp_path: Path):
    run = one_case_run(tmp_path, "run-p1", pipeline_version="pipeline-p1")
    saved = save_baseline(run, tmp_path / "baselines")
    other = one_case_run(tmp_path, "run-p2", pipeline_version="pipeline-p2", run_id="run-b0-p2")

    with pytest.raises(CrossVersionBaselineError):
        load_baseline(saved.baseline_id, tmp_path / "baselines", expected=other.manifest)
    with pytest.raises(CrossVersionBaselineError):
        load_baseline(
            saved.baseline_id,
            tmp_path / "baselines",
            expected=other.manifest,
            compare_with="ffffffffffff",
        )
    loaded = load_baseline(
        saved.baseline_id,
        tmp_path / "baselines",
        expected=other.manifest,
        compare_with=saved.baseline_id,
    )
    assert loaded.identity.pipeline_version == "pipeline-p1"


def test_load_baseline_rejects_incomparable_dataset(tmp_path: Path):
    run = one_case_run(tmp_path, "run-a")
    saved = save_baseline(run, tmp_path / "baselines")
    other = one_case_run(
        tmp_path,
        "run-b",
        dataset_version="b0:dev-2:ffffffffffff",
        run_id="run-b0-b",
    )
    with pytest.raises(BaselineComparabilityError):
        load_baseline(
            saved.baseline_id,
            tmp_path / "baselines",
            expected=other.manifest,
            compare_with=saved.baseline_id,
        )
