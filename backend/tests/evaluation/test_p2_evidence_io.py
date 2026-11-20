"""A3 定向测试：严格 schema、Fernet 认证加密读写、路径/绑定/泄漏防线与 DB 对齐。

全部合成数据与本次现生成 Fernet key；不读真实 key/密文/凭据，不发真实网络请求。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation.p2_evidence_capture import (  # noqa: E402
    BINDING_KEYS,
    EVIDENCE_SCHEMA_VERSION,
    EvidenceCaptureConfigError,
)
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    EvidenceIOError,
    EvidenceIntegrityError,
    EvidenceWriter,
    canonical_json_bytes,
    read_encrypted_evidence,
    validate_manifest,
    validate_turn_evidence,
    verify_db_alignment,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

SENTINEL = "P2CAPTURE_SENTINEL_DO_NOT_EXPORT_77aa"


def _bindings() -> dict[str, str]:
    values = {key: "local_mock-" + key for key in BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    return values


def _projection() -> dict:
    return {
        "schema_version": "p2-hard-evidence-capture-db/v0.1",
        "snapshot_utc": "2026-01-01T00:00:00+00:00",
        "pre_revision": 0,
        "capture_revision": 0,
        "conversation": {
            "id": "c1",
            "owner_user_id": "u1",
            "deleted": False,
            "deleted_at": None,
            "created_at": None,
            "updated_at": None,
        },
        "request": {
            "id": "r1",
            "conversation_id": "c1",
            "user_id": "u1",
            "status": "succeeded",
            "attempt": 1,
            "payload_sha256": "0" * 64,
            "user_message_id": "m0",
            "result_message_id": "m1",
            "error_code": None,
            "error_retryable": False,
            "created_at": None,
            "started_at": None,
            "finished_at": None,
        },
        "messages": [
            {
                "id": "m1",
                "conversation_id": "c1",
                "owner_user_id": "u1",
                "role": "assistant",
                "seq": 2,
                "kind": "answer",
                "revision": 0,
                "error_code": None,
                "text": SENTINEL + " answer",
                "created_at": None,
            }
        ],
        "message_sources": [],
        "units": [
            {
                "unit_id": "unit-1",
                "unit_key": "row:2",
                "kind": "table_row",
                "locator": {"row": 2},
                "text": SENTINEL + " unit",
                "raw_fields": {"门店": "城东店"},
                "date_fields": {},
                "entity_type": "record",
                "entity_key": "城东店",
                "entity_filters": {"store": "城东店", "item": "宣传海报"},
                "document_id": "d1",
                "document_name": "D01",
                "document_deleted": False,
                "version_id": "v1",
                "version_number": 1,
                "version_state": "published",
                "active_version_id": "v1",
                "active": True,
                "published_at": None,
            }
        ],
        "unresolved_unit_ids": [],
        "query_states": [],
        "query_states_available": True,
        "rag_business_date": None,
        "truncations": [],
        "errors": [],
    }


def _envelope(*, bindings: dict | None = None) -> dict:
    event = {"seq": 1, "kind": "context_observed", "payload": {"request_id": "r1", "count": 0, "empty": True}}
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "fixture_kind": "local_mock",
        "bindings": dict(bindings or _bindings()),
        "adapter_components": {},
        "turn": {
            "turn_index": 0,
            "client_request_id": "c1-request",
            "conversation_id": "c1",
            "authenticated_user_id": "u1",
            "question_sha256": "a" * 64,
            "http_status": 200,
            "timed_out": False,
            "started_utc": "2026-01-01T00:00:00+00:00",
            "captured_utc": "2026-01-01T00:00:01+00:00",
            "pre_revision": 0,
            "post_revision": 0,
            "capture_revision": 0,
        },
        "capture": {
            "schema_version": "mktkb.eval-capture/v0.1",
            "sink_id": "sink-1",
            "status": "sealed",
            "seq": 1,
            "event_count": 1,
            "events": [event],
            "errors": [],
        },
        "db_projection": _projection(),
        "completeness": {
            "status": "incomplete",
            "replay": False,
            "required_event_kinds": [],
            "missing_event_kinds": [],
            "errors": [],
        },
    }


def _manifest() -> dict:
    bindings = _bindings()
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "fixture_kind": "local_mock",
        "started_utc": "2026-01-01T00:00:00+00:00",
        "bindings": bindings,
        "adapter_components": {},
        "summary": {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "fixture_kind": "local_mock",
            "started_utc": "2026-01-01T00:00:00+00:00",
            "turn_count": 0,
            "status_counts": {},
            "blocked": False,
            "bindings": bindings,
        },
        "turns": [],
    }


def _writer(tmp_path: Path, *, max_bytes: int = 16 * 1024 * 1024) -> EvidenceWriter:
    return EvidenceWriter(
        root_dir=tmp_path / "evidence-root",
        key=Fernet.generate_key(),
        bindings=_bindings(),
        run_name="run-1",
        max_envelope_bytes=max_bytes,
    )


def test_turn_and_manifest_roundtrip_with_ciphertext_only(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    turn_receipt = writer.write_turn(_envelope())
    manifest_receipt = writer.write_manifest(_manifest())
    assert Path(turn_receipt["path"]).suffix == ".fernet"
    assert Path(manifest_receipt["path"]).suffix == ".fernet"
    assert turn_receipt["bytes"] == Path(turn_receipt["path"]).stat().st_size
    assert manifest_receipt["kind"] == "manifest"
    token = Path(turn_receipt["path"]).read_bytes()
    assert SENTINEL.encode("utf-8") not in token
    read_back = read_encrypted_evidence(
        Path(turn_receipt["path"]), key=writer.key, expected_bindings=writer.bindings
    )
    assert canonical_json_bytes(read_back) == canonical_json_bytes(_envelope())
    manifest = read_encrypted_evidence(
        Path(manifest_receipt["path"]), key=writer.key, expected_bindings=writer.bindings
    )
    validate_manifest(manifest)
    assert writer.status == "active"


def test_duplicate_json_key_truncation_and_wrong_key_are_rejected(tmp_path: Path) -> None:
    key = Fernet.generate_key()
    fernet = Fernet(key)
    directory = tmp_path / "evidence-root" / "run-1"
    directory.mkdir(parents=True)
    duplicate = directory / "duplicate.fernet"
    duplicate.write_bytes(fernet.encrypt(b'{"schema_version":"x","schema_version":"y"}'))
    with pytest.raises(EvidenceIntegrityError):
        read_encrypted_evidence(duplicate, key=key)

    good_path = directory / "good.fernet"
    good_path.write_bytes(fernet.encrypt(canonical_json_bytes(_manifest())))
    truncated = directory / "truncated.fernet"
    token = good_path.read_bytes()
    truncated.write_bytes(token[: max(1, len(token) // 2)])
    with pytest.raises(EvidenceIntegrityError):
        read_encrypted_evidence(truncated, key=key)
    with pytest.raises(EvidenceIntegrityError):
        read_encrypted_evidence(good_path, key=Fernet.generate_key())


def test_writer_rejects_unknown_keys_bool_as_int_and_bad_event_seq(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    unknown = _envelope()
    unknown["unexpected"] = 1
    with pytest.raises(EvidenceIOError):
        writer.write_turn(unknown)
    assert writer.status == "failed"

    writer2 = _writer(tmp_path)
    bad_int = _envelope()
    bad_int["turn"]["http_status"] = True
    with pytest.raises(EvidenceIOError):
        writer2.write_turn(bad_int)

    writer3 = _writer(tmp_path)
    bad_seq = _envelope()
    bad_seq["capture"]["events"][0]["seq"] = 2
    with pytest.raises(EvidenceIOError):
        writer3.write_turn(bad_seq)

    writer4 = _writer(tmp_path)
    bad_payload = _envelope()
    bad_payload["capture"]["events"][0]["payload"]["unknown_field"] = "x"
    with pytest.raises(EvidenceIOError):
        writer4.write_turn(bad_payload)


def test_cross_run_binding_mismatch_is_rejected(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    receipt = writer.write_turn(_envelope())
    other = _bindings()
    other["run_id"] = "another-run"
    with pytest.raises(EvidenceIntegrityError):
        read_encrypted_evidence(
            Path(receipt["path"]), key=writer.key, expected_bindings=other
        )


def test_oversize_fails_closed_and_cleans_partial_files(tmp_path: Path) -> None:
    writer = _writer(tmp_path, max_bytes=128)
    with pytest.raises(EvidenceIOError):
        writer.write_turn(_envelope())
    assert writer.status == "failed"
    run_dir = tmp_path / "evidence-root" / "run-1"
    assert list(run_dir.glob("*.fernet")) == []


def test_writer_root_inside_repo_or_old_seal_root_is_forbidden(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    with pytest.raises(EvidenceCaptureConfigError):
        EvidenceWriter(
            root_dir=repo_root / "inline-evidence-capture",
            key=Fernet.generate_key(),
            bindings=_bindings(),
        )
    with pytest.raises(EvidenceCaptureConfigError):
        EvidenceWriter(
            root_dir=Path("D:/mktkb-p2-holdout/v2/forbidden-new-dir"),
            key=Fernet.generate_key(),
            bindings=_bindings(),
        )


def test_full_envelope_validation_rejects_strictly() -> None:
    validate_turn_evidence(_envelope(), expected_bindings=_bindings())
    broken = _envelope()
    broken["completeness"]["status"] = "passed"
    with pytest.raises(EvidenceIntegrityError):
        validate_turn_evidence(broken)


def test_verify_db_alignment_reports_owner_and_lifecycle_mismatches() -> None:
    good = _envelope()
    report = verify_db_alignment(good)
    assert report["ok"] is True, report
    assert report["checks"]["context_message_owner_consistent"] is True

    tampered = _envelope()
    projection = tampered["db_projection"]
    projection["request"] = copy.deepcopy(projection["request"])
    projection["request"]["user_id"] = "u2"
    projection["messages"] = copy.deepcopy(projection["messages"])
    projection["messages"][0]["owner_user_id"] = "u2"
    projection["units"][0]["document_deleted"] = True
    projection["units"][0]["active_version_id"] = "v2"
    projection["query_states"] = [
        {"stored_user_id": "u2", "stored_conversation_id": "other-conversation", "state_json": {}, "keys": []}
    ]
    report = verify_db_alignment(tampered)
    assert report["ok"] is False
    assert report["checks"]["context_message_owner_consistent"] is False
    assert report["checks"]["units_have_lifecycle_projection"] is False
    assert report["checks"]["query_state_conversation_consistent"] is False
    assert report["findings"]

# --------------------------------------------------------------------------- #
# R1 反例：必需/可选字段、嵌套坏类型、sealed 阶段与秘密不回显
# --------------------------------------------------------------------------- #


def _sealed_payload() -> dict:
    return {"path": "synthetic/turn-0000.fernet", "sha256": "a" * 64, "bytes": 1, "turn_index": 0, "kind": "turn"}


def test_required_projection_fields_and_nested_types_are_enforced() -> None:
    """投影行缺 owner/FK/生命周期/原值等必需字段、嵌套坏类型必须被拒。"""
    validate_turn_evidence(_envelope(), expected_bindings=_bindings())

    broken = _envelope()
    broken["db_projection"]["conversation"] = {"id": "c1"}
    with pytest.raises(EvidenceIntegrityError, match="conversation_missing_required"):
        validate_turn_evidence(broken)

    broken = _envelope()
    broken["db_projection"]["conversation"] = dict(_projection()["conversation"])
    broken["db_projection"]["conversation"]["deleted"] = "no"
    with pytest.raises(EvidenceIntegrityError, match="conversation.deleted_must_be_bool"):
        validate_turn_evidence(broken)

    broken = _envelope()
    broken["db_projection"]["messages"] = [{"id": "m1", "owner_user_id": "u1", "role": "user", "seq": 1}]
    with pytest.raises(EvidenceIntegrityError, match="messages_missing_required"):
        validate_turn_evidence(broken)

    broken = _envelope()
    broken["db_projection"]["units"] = [{"unit_id": "u", "unit_key": "k"}]
    with pytest.raises(EvidenceIntegrityError, match="units_missing_required"):
        validate_turn_evidence(broken)

    broken = _envelope()
    broken["db_projection"]["request"] = {"id": "r1"}
    with pytest.raises(EvidenceIntegrityError, match="request_missing_required"):
        validate_turn_evidence(broken)

    # 合法 null 与缺字段必须区分：error_code=None 合法，缺 error_code 非法。
    broken = _envelope()
    broken["db_projection"]["request"] = dict(_projection()["request"])
    broken["db_projection"]["request"].pop("error_code")
    with pytest.raises(EvidenceIntegrityError, match="request_missing_required:error_code"):
        validate_turn_evidence(broken)
    broken = _envelope()
    broken["db_projection"]["request"] = dict(_projection()["request"])
    broken["db_projection"]["request"]["error_code"] = None
    validate_turn_evidence(broken)


def test_manifest_summary_and_public_turn_rows_are_enforced() -> None:
    validate_manifest(_manifest())
    broken = _manifest()
    broken["summary"] = dict(broken["summary"])
    broken["summary"].pop("status_counts")
    with pytest.raises(EvidenceIntegrityError, match="summary_missing_required:status_counts"):
        validate_manifest(broken)
    broken = _manifest()
    broken["summary"] = dict(broken["summary"], status_counts={"complete": True})
    with pytest.raises(EvidenceIntegrityError, match="summary.status_counts_value_must_be_int"):
        validate_manifest(broken)
    broken = _manifest()
    broken["turns"] = [{"schema_version": "p2-hard-evidence-capture/v0.1", "fixture_kind": "local_mock"}]
    with pytest.raises(EvidenceIntegrityError, match="turns_missing_required"):
        validate_manifest(broken)


def test_sealed_phase_is_defined_for_write_and_read(tmp_path: Path) -> None:
    """写前不得带 sealed；写后（内存回执）必须带 sealed。"""
    writer = _writer(tmp_path)
    with_sealed = _envelope()
    with_sealed["sealed"] = _sealed_payload()
    with pytest.raises(EvidenceIOError, match="sealed_present_before_write"):
        writer.write_turn(with_sealed)
    assert writer.status == "failed"

    with pytest.raises(EvidenceIntegrityError, match="sealed_missing_after_write"):
        validate_turn_evidence(_envelope(), phase="post_write")
    receipted = _envelope()
    receipted["sealed"] = _sealed_payload()
    validate_turn_evidence(receipted, phase="post_write")
    with pytest.raises(EvidenceIntegrityError, match="sealed_present_before_write"):
        validate_turn_evidence(receipted, phase="pre_write")
    with pytest.raises(EvidenceIntegrityError, match="validation_phase_invalid"):
        validate_turn_evidence(_envelope(), phase="after_write")


def test_exception_chain_and_repr_never_echo_payload_secret(tmp_path: Path, capsys) -> None:
    """未知键/错误的异常链与 repr 不得回显合成秘密（stdout/stderr 同样）。"""
    import traceback

    secret = SENTINEL
    bad = _envelope()
    bad["db_projection"]["units"][0]["document_deleted"] = secret
    try:
        validate_turn_evidence(bad)
    except EvidenceIntegrityError as exc:
        assert secret not in str(exc)
        assert secret not in repr(exc)
        chain = traceback.format_exc()
        assert secret not in chain
    else:  # pragma: no cover - 必须抛错
        raise AssertionError("坏类型必须被拒")

    writer = _writer(tmp_path)
    wrong = _envelope()
    wrong["turn"]["question_sha256"] = secret
    try:
        writer.write_turn(wrong)
    except EvidenceIOError as exc:
        assert secret not in str(exc)
        assert secret not in repr(exc)
        assert secret not in traceback.format_exc()
    else:  # pragma: no cover - 必须抛错
        raise AssertionError("坏 hash 必须被拒")
    assert repr(writer.key) not in repr(writer)
    captured = capsys.readouterr()
    assert secret not in captured.out and secret not in captured.err

# --------------------------------------------------------------------------- #
# R1-1：envelope/manifest 顶层 fixture_kind 不得伪造
# --------------------------------------------------------------------------- #


def test_top_level_fixture_kind_must_be_local_mock_and_match_bindings() -> None:
    """本包(v0.1)只允许 local_mock；顶层必须与 bindings 一致，未知值/live 一律拒绝。"""
    validate_turn_evidence(_envelope(), expected_bindings=_bindings())
    validate_manifest(_manifest())

    forged = _envelope()
    forged["fixture_kind"] = "live"
    with pytest.raises(EvidenceIntegrityError, match="unsupported_fixture_kind"):
        validate_turn_evidence(forged)

    unknown = _envelope()
    unknown["fixture_kind"] = "real_go"
    with pytest.raises(EvidenceIntegrityError, match="unsupported_fixture_kind"):
        validate_turn_evidence(unknown)

    missing = _envelope()
    missing.pop("fixture_kind")
    with pytest.raises(EvidenceIntegrityError, match="envelope_missing_required:fixture_kind"):
        validate_turn_evidence(missing)

    null_top = _envelope()
    null_top["fixture_kind"] = None
    with pytest.raises(EvidenceIntegrityError, match="fixture_kind_must_be_str"):
        validate_turn_evidence(null_top)

    forged_manifest = _manifest()
    forged_manifest["fixture_kind"] = "live"
    with pytest.raises(EvidenceIntegrityError, match="unsupported_fixture_kind"):
        validate_manifest(forged_manifest)


