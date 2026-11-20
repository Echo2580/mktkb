"""Approval and portable archive for the T209 public B0 baseline."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .baseline import (
    APPROVAL_FILENAME, ARCHIVE_BASELINE_DIR, ARCHIVE_MANIFEST_FILENAME, ARCHIVE_RUN_DIR,
    BASELINE_FILENAME, Baseline, BaselineApproval, BaselineArchive, BaselineArchiveError,
    BaselineGate, BaselineRestoreResult, _build_archive_manifest, _pack_archive, _publish_staging,
    _utc_now, _write_json, baseline_identity, load_baseline,
)
from .p2_b0 import (
    B0_ARTIFACTS, B0_DOCUMENT_CODES, B0_DOCUMENT_CODES_SHA256, B0_GATE_FILE_SHA256, B0Admission,
    check_b0_admission, load_approved_b0_config, public_json, read_member, require, safe_path, sha256,
)
from .p2_contracts import payload_sha256

_ADMISSION = "b0-admission.json"
_RECEIPT = "b0-approval-receipt.json"
_CONFIG = "gate-config.json"
_DOCUMENT_CODES = "document-codes.json"
B0_BASELINE_ARTIFACTS = (_ADMISSION, _RECEIPT, _CONFIG, _DOCUMENT_CODES)
B0_RECEIPT_SCHEMA = "mktkb.p2.b0.approval.v0.1"
_RECEIPT_KEYS = {
    "schema_version", "scope", "decision", "run_id", "baseline_id", "evidence_sha256",
    "approver", "approved_at", "reason",
}


def evidence_sha256(admission: B0Admission) -> str:
    return payload_sha256(admission.proof)


def _approval(admission: B0Admission, receipt: Any) -> BaselineApproval:
    identity = baseline_identity(admission.run)
    run_id = admission.run.manifest.run_id
    digest = evidence_sha256(admission)
    require(
        isinstance(receipt, Mapping) and set(receipt) == _RECEIPT_KEYS
        and receipt["schema_version"] == B0_RECEIPT_SCHEMA and receipt["scope"] == "t209_b0_baseline"
        and receipt["decision"] == "approved" and receipt["baseline_id"] == identity.baseline_id
        and receipt["run_id"] == run_id and receipt["evidence_sha256"] == digest,
        "b0_approval_receipt_mismatch",
    )
    approved_at = datetime.fromisoformat(receipt["approved_at"])
    require(approved_at.tzinfo is not None, "b0_approval_receipt_date_invalid")
    return BaselineApproval(
        baseline_id=identity.baseline_id, run_id=run_id, gate_result_sha256=digest,
        quality_status="pass", approver=receipt["approver"], approved_at=receipt["approved_at"],
        reason=receipt["reason"], **identity.to_dict(),
    )


def _gate(admission: B0Admission) -> BaselineGate:
    proof = admission.proof["hard_gate"]
    return BaselineGate(
        exit_code=proof["exit_code"], quality_status="pass", gate_status=proof["gate_status"],
        hard_failures=tuple(proof["hard_failures"]), gate_version=admission.run.manifest.gate_version,
        gate_result_sha256=evidence_sha256(admission), run_id=admission.run.manifest.run_id, suite="b0",
    )


def _stage_directory(target: Path) -> Path:
    target = safe_path(target)
    require(not target.exists(), "b0_target_exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))


def _publish_new(staging: Path, target: Path) -> None:
    require(not safe_path(target).exists(), "b0_target_exists")
    _publish_staging(staging, target)


def approve_b0_baseline(
    run_dir: Path, gate_config_path: Path, receipt_path: Path, root: Path,
) -> Baseline:
    config = load_approved_b0_config(gate_config_path)
    admission = check_b0_admission(run_dir, config)
    receipt_raw = read_member(receipt_path)
    approval = _approval(admission, public_json(receipt_raw))
    identity = baseline_identity(admission.run)
    manifest = admission.run.manifest
    baseline = Baseline(
        baseline_id=identity.baseline_id, identity=identity, run_id=manifest.run_id,
        run_dir=str(admission.run.out_dir), suite="b0", dataset_sha256=manifest.dataset_sha256,
        label_version=manifest.label_version, case_count=manifest.case_count, created_at=_utc_now(),
        artifact_sha256=admission.proof["artifact_sha256"], gate=_gate(admission), approval=approval,
    )
    target = safe_path(root) / baseline.baseline_id
    staging = _stage_directory(target)
    try:
        _write_json(staging / BASELINE_FILENAME, baseline.to_dict())
        _write_json(staging / APPROVAL_FILENAME, approval.to_dict())
        _write_json(staging / _ADMISSION, admission.proof)
        (staging / _RECEIPT).write_bytes(receipt_raw)
        (staging / _CONFIG).write_bytes(read_member(gate_config_path))
        (staging / _DOCUMENT_CODES).write_bytes(read_member(B0_DOCUMENT_CODES))
        validate_b0_baseline(baseline, staging, Path(baseline.run_dir))
        _publish_new(staging, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return load_baseline(baseline.baseline_id, root)


def validate_b0_baseline(baseline: Baseline, evidence_dir: Path, run_dir: Path) -> B0Admission:
    require(baseline.approval is not None and baseline.gate is not None, "b0_approval_evidence_missing")
    raw_baseline = public_json(read_member(evidence_dir / BASELINE_FILENAME))
    raw_approval = public_json(read_member(evidence_dir / APPROVAL_FILENAME))
    require(raw_baseline == baseline.to_dict() and raw_approval == baseline.approval.to_dict(),
            "b0_baseline_record_mismatch")
    portable = public_json(read_member(evidence_dir / _ADMISSION))
    config = load_approved_b0_config(evidence_dir / _CONFIG)
    admission = check_b0_admission(
        run_dir, config, portable_proof=portable, document_codes_path=evidence_dir / _DOCUMENT_CODES,
    )
    manifest = admission.run.manifest
    require(
        baseline.suite == "b0" and baseline.identity == baseline_identity(admission.run)
        and baseline.run_id == manifest.run_id and baseline.case_count == manifest.case_count
        and baseline.dataset_sha256 == manifest.dataset_sha256 and baseline.label_version == manifest.label_version
        and baseline.artifact_sha256 == admission.proof["artifact_sha256"] and baseline.gate == _gate(admission)
        and baseline.approval == _approval(admission, public_json(read_member(evidence_dir / _RECEIPT))),
        "b0_baseline_evidence_mismatch",
    )
    return admission


def archive_b0_baseline(
    baseline: Baseline, evidence_dir: Path, target: Path, archived_at: str | None,
) -> BaselineArchive:
    run_dir = Path(baseline.run_dir)
    admission = validate_b0_baseline(baseline, evidence_dir, run_dir)
    entries = [
        (f"{ARCHIVE_BASELINE_DIR}/{name}", read_member(evidence_dir / name))
        for name in (BASELINE_FILENAME, APPROVAL_FILENAME, *B0_BASELINE_ARTIFACTS)
    ]
    entries.extend((f"{ARCHIVE_RUN_DIR}/{name}", data) for name, data in admission.raw_artifacts.items())
    manifest = _build_archive_manifest(
        baseline, entries, excluded=(), archived_at=archived_at or _utc_now(),
        source_baseline_dir=evidence_dir, source_run_dir=run_dir,
    )
    manifest["note"] = "原始公开运行字节、B0 重评分与独立审批证据。P2 发布仍受 N/C/U/H2 证据约束。"
    return _pack_archive(safe_path(target), entries, manifest)


def validate_b0_archive(
    root: Path, baseline: Baseline, content: Mapping[str, bytes], manifest: Mapping[str, Any],
) -> None:
    expected = {
        *(f"{ARCHIVE_RUN_DIR}/{name}" for name in B0_ARTIFACTS),
        *(f"{ARCHIVE_BASELINE_DIR}/{name}" for name in (
            BASELINE_FILENAME, APPROVAL_FILENAME, *B0_BASELINE_ARTIFACTS,
        )),
    }
    require(set(content) == expected and manifest["has_approval"] is True, "b0_archive_members_invalid")
    require(set(manifest) == {
        "schema_version", "tool", "archived_at", "baseline_id", "identity", "run_id", "suite",
        "source", "has_approval", "approval", "gate", "files", "excluded", "note",
    } and manifest["excluded"] == [], "b0_archive_metadata_invalid")
    public_json(read_member(root / ARCHIVE_MANIFEST_FILENAME))
    require(
        sha256(content[f"{ARCHIVE_BASELINE_DIR}/{_CONFIG}"]) == B0_GATE_FILE_SHA256
        and sha256(content[f"{ARCHIVE_BASELINE_DIR}/{_DOCUMENT_CODES}"]) == B0_DOCUMENT_CODES_SHA256,
        "b0_archive_source_config_invalid",
    )
    validate_b0_baseline(baseline, root / ARCHIVE_BASELINE_DIR, root / ARCHIVE_RUN_DIR)
    require(all(read_member(root / rel) == data for rel, data in content.items()), "b0_archive_changed")


def restore_b0_archive(
    source: Path, archive: BaselineArchive, root: Path, runs_root: Path | str | None,
) -> BaselineRestoreResult:
    root = safe_path(root)
    runs = safe_path(Path(runs_root)) if runs_root is not None else root.parent / "runs"
    baseline_target = root / archive.baseline_id
    run_target = runs / archive.run_id
    require(not safe_path(baseline_target).exists() and not safe_path(run_target).exists(), "b0_target_exists")
    require(not baseline_target.is_relative_to(run_target) and not run_target.is_relative_to(baseline_target),
            "b0_restore_target_overlap")
    baseline_staging = _stage_directory(baseline_target)
    run_staging = None
    run_published = False
    try:
        run_staging = _stage_directory(run_target)
        for rel, expected in archive.files.items():
            group, name = rel.split("/", 1)
            data = read_member(source / rel)
            require(sha256(data) == expected, "b0_archive_changed")
            if group == ARCHIVE_RUN_DIR:
                (run_staging / name).write_bytes(data)
            elif name == BASELINE_FILENAME:
                payload = public_json(data)
                payload["run_dir"] = str(run_target)
                _write_json(baseline_staging / name, payload)
            else:
                (baseline_staging / name).write_bytes(data)
        original = Baseline.from_dict(
            public_json(read_member(baseline_staging / BASELINE_FILENAME)),
            approval=BaselineApproval.from_dict(public_json(read_member(baseline_staging / APPROVAL_FILENAME))),
        )
        validate_b0_baseline(original, baseline_staging, run_staging)
        _publish_new(run_staging, run_target)
        run_published = True
        _publish_new(baseline_staging, baseline_target)
    except BaseException:
        if run_published:
            shutil.rmtree(run_target, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(baseline_staging, ignore_errors=True)
        if run_staging is not None:
            shutil.rmtree(run_staging, ignore_errors=True)
    restored = load_baseline(archive.baseline_id, root)
    return BaselineRestoreResult(
        baseline=restored, baseline_dir=str(baseline_target), run_dir=str(run_target),
        files=tuple(sorted(archive.files)),
    )


def diff_b0_baseline(
    run_dir: Path, gate_config_path: Path, root: Path, baseline: str | None, compare_with: str | None,
) -> dict[str, Any]:
    from .report import diff_runs

    config = load_approved_b0_config(gate_config_path)
    current = check_b0_admission(run_dir, config, allow_quality_regression=True)
    identity = baseline_identity(current.run)
    baseline = baseline or compare_with or identity.baseline_id
    previous = load_baseline(baseline, root, expected=identity, compare_with=compare_with)
    require(previous.dataset_sha256 == current.run.manifest.dataset_sha256, "b0_diff_dataset_mismatch")
    diff = diff_runs(previous, current.run, comparison="analysis", compare_with=compare_with, config=config.config)
    return {
        **diff.to_dict(),
        "baseline_approved": True,
        "current_b0": current.proof["b0"],
        "p2_release_status": current.proof["p2_release_status"],
    }
