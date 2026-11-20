"""A3 仓外认证密文证据 IO：严格 schema 校验、Fernet 认证加密、独立 DB 对齐核验。

R1 边界（T207 EVIDENCE-CAPTURE R1）：
- 严格校验按 schema 区分必需/可选字段：投影行缺 owner/FK/生命周期/原值等必需字段、
  嵌套坏类型、合法 null 与缺字段混同、sealed 写前/写后阶段错位都会被拒；
- 写入前 . 读取后两个阶段显式区分（pre_write 不允许 sealed；post_write 必须提交回执）；
- 明文只在进程内存；密文只写当前执行环境允许的**仓外新目录**（拒绝仓库与旧封存根）；
- 公开层只输出固定键/枚举/计数，不含题面、答案、逐题 ID 或逐题 hash。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from cryptography.fernet import Fernet, InvalidToken

from ..observability.evaluation_capture import FIXED_EVENT_KINDS, clean_event_payload
from .p2_evidence_capture import (
    BINDING_KEYS,
    EVIDENCE_SCHEMA_VERSION,
    EVIDENCE_SCHEMA_VERSION_V03,
    FIXTURE_KINDS,
    LIVE_EVIDENCE_SCHEMA_VERSION,
    LIVE_EVIDENCE_SCHEMA_VERSION_V03,
    LIVE_EVIDENCE_SCHEMA_VERSIONS,
    LIVE_FIXTURE_KIND,
    LOCAL_EVIDENCE_SCHEMA_VERSIONS,
    RUNTIME_SNAPSHOT_VERSIONS,
    TRUNCATION_ERRORS,
    EvidenceCaptureConfigError,
    assert_evidence_root_outside_repo,
    validate_run_binding,
)

EVIDENCE_IO_SCHEMA_VERSION = "p2-hard-evidence-io/v0.1"
MAX_ENVELOPE_BYTES = 16 * 1024 * 1024
MAX_TURN_COUNT = 64
MAX_ROWS = 4096
MAX_JSON_DEPTH = 6

#: 校验阶段：写前（writer 入参）必须没有回执；写后（读取器）必须带认证回执。
VALIDATION_PHASES = ("pre_write", "post_write", "any")


class EvidenceIOError(RuntimeError):
    code = "evidence_io_failed"


class EvidenceIntegrityError(EvidenceIOError):
    code = "evidence_integrity_error"


class EvidencePathError(EvidenceIOError):
    code = "evidence_path_forbidden"


class EvidenceWriteError(EvidenceIOError):
    code = "evidence_write_failed"


def canonical_json_bytes(payload: Any) -> bytes:
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise EvidenceIntegrityError("payload_not_canonical_json") from exc
    return text.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json_loads(data: bytes) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        if len(set(keys)) != len(keys):
            raise EvidenceIntegrityError("duplicate_json_key")
        return dict(pairs)

    def reject_constant(value: str) -> Any:
        raise EvidenceIntegrityError("invalid_json_constant")

    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceIntegrityError("invalid_utf8") from exc
    try:
        return json.loads(
            decoded,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except EvidenceIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise EvidenceIntegrityError("invalid_json") from exc


# --------------------------------------------------------------------------- #
# 基础校验器：只给固定错误码/字段名，绝不回显字段值（防合成秘密回显）
# --------------------------------------------------------------------------- #


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceIntegrityError(name + "_must_be_mapping")
    return value


def _require_str(value: Any, name: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if type(value) is not str:
        raise EvidenceIntegrityError(name + "_must_be_str")
    if len(value) > 65536:
        raise EvidenceIntegrityError(name + "_too_long")
    return value


def _require_int(value: Any, name: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if type(value) is not int:  # 拒绝 bool 冒充计数
        raise EvidenceIntegrityError(name + "_must_be_int")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise EvidenceIntegrityError(name + "_must_be_bool")
    return value


def _require_hash_text(value: Any, name: str, *, allow_none: bool = False) -> str | None:
    text = _require_str(value, name, allow_none=allow_none)
    if text is None:
        return None
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise EvidenceIntegrityError(name + "_must_be_sha256")
    return text


def _require_json_value(value: Any, name: str, depth: int = 0) -> None:
    if value is None or type(value) in (int, float, bool):
        return
    if type(value) is str:
        if len(value) > 65536:
            raise EvidenceIntegrityError(name + "_too_long")
        return
    if depth >= MAX_JSON_DEPTH:
        raise EvidenceIntegrityError(name + "_too_deep")
    if isinstance(value, list):
        if len(value) > MAX_ROWS:
            raise EvidenceIntegrityError(name + "_too_many_items")
        for item in value:
            _require_json_value(item, name, depth + 1)
        return
    if isinstance(value, Mapping):
        if len(value) > MAX_ROWS:
            raise EvidenceIntegrityError(name + "_too_many_keys")
        for key, item in value.items():
            if type(key) is not str:
                raise EvidenceIntegrityError(name + "_key_must_be_str")
            _require_json_value(item, name, depth + 1)
        return
    raise EvidenceIntegrityError(name + "_must_be_json")


def _v_str(value: Any, name: str) -> None:
    _require_str(value, name)


def _v_text(value: Any, name: str) -> None:
    _require_str(value, name)


def _v_id(value: Any, name: str) -> None:
    text = _require_str(value, name)
    if not text:
        raise EvidenceIntegrityError(name + "_empty")


def _v_opt_str(value: Any, name: str) -> None:
    _require_str(value, name, allow_none=True)


def _v_opt_id(value: Any, name: str) -> None:
    text = _require_str(value, name, allow_none=True)
    if text is not None and not text:
        raise EvidenceIntegrityError(name + "_empty")


def _v_int(value: Any, name: str) -> None:
    _require_int(value, name)


def _v_opt_int(value: Any, name: str) -> None:
    _require_int(value, name, allow_none=True)


def _v_bool(value: Any, name: str) -> None:
    _require_bool(value, name)


def _v_list_str(value: Any, name: str) -> None:
    if not isinstance(value, list) or len(value) > MAX_ROWS:
        raise EvidenceIntegrityError(name + "_invalid")
    if not all(type(item) is str for item in value):
        raise EvidenceIntegrityError(name + "_item_must_be_str")


def _v_json_obj(value: Any, name: str) -> None:
    _require_mapping(value, name)
    _require_json_value(value, name)


def _v_sha256(value: Any, name: str) -> None:
    _require_hash_text(value, name)


def _v_opt_sha256(value: Any, name: str) -> None:
    _require_hash_text(value, name, allow_none=True)


def _v_date(value: Any, name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise EvidenceIntegrityError(name + "_invalid")


def _v_map_int(value: Any, name: str) -> None:
    mapping = _require_mapping(value, name)
    for key, item in mapping.items():
        if type(key) is not str:
            raise EvidenceIntegrityError(name + "_key_must_be_str")
        if type(item) is not int:
            raise EvidenceIntegrityError(name + "_value_must_be_int")


def _enum(allowed: tuple[str, ...]) -> Callable[[Any, str], None]:
    allowed_set = set(allowed)

    def _validator(value: Any, name: str) -> None:
        if type(value) is not str or value not in allowed_set:
            raise EvidenceIntegrityError(name + "_invalid")

    return _validator


def _v_rows(schema: dict[str, tuple[Callable[[Any, str], None], bool]], max_items: int = MAX_ROWS):
    def _validator(value: Any, name: str) -> None:
        if not isinstance(value, list) or len(value) > max_items:
            raise EvidenceIntegrityError(name + "_invalid")
        for row in value:
            _validate_row(row, schema, name)

    return _validator


def _v_opt_row(schema: dict[str, tuple[Callable[[Any, str], None], bool]]):
    def _validator(value: Any, name: str) -> None:
        if value is None:
            return
        _validate_row(value, schema, name)

    return _validator


def _v_row(schema: dict[str, tuple[Callable[[Any, str], None], bool]]):
    def _validator(value: Any, name: str) -> None:
        _validate_row(value, schema, name)

    return _validator


def _validate_row(value: Any, schema: dict[str, tuple[Callable[[Any, str], None], bool]], name: str) -> None:
    mapping = _require_mapping(value, name)
    unknown = sorted(set(mapping) - set(schema))
    if unknown:
        raise EvidenceIntegrityError(name + "_unknown_keys:" + ",".join(str(key) for key in unknown))
    missing = sorted(key for key, (_, required) in schema.items() if required and key not in mapping)
    if missing:
        raise EvidenceIntegrityError(name + "_missing_required:" + ",".join(missing))
    for key, (validator, _required) in schema.items():
        if key in mapping:
            validator(mapping[key], name + "." + key)


# --------------------------------------------------------------------------- #
# schema：区分必需/可选、合法 null 与缺字段
# --------------------------------------------------------------------------- #

_V_STR = (_v_str, True)
_V_TEXT = (_v_text, True)
_V_ID = (_v_id, True)
_V_OPT_STR = (_v_opt_str, True)
_V_OPT_ID = (_v_opt_id, True)
_V_INT = (_v_int, True)
_V_OPT_INT = (_v_opt_int, True)
_V_BOOL = (_v_bool, True)
_V_LIST_STR = (_v_list_str, True)
_V_JSON = (_v_json_obj, True)
_V_SHA = (_v_sha256, True)
_V_OPT_SHA = (_v_opt_sha256, True)
_V_MAP_INT = (_v_map_int, True)

_CONVERSATION_SCHEMA = {
    "id": _V_ID,
    "owner_user_id": _V_ID,
    "deleted": _V_BOOL,
    "deleted_at": _V_OPT_STR,
    "created_at": _V_OPT_STR,
    "updated_at": _V_OPT_STR,
}
_REQUEST_SCHEMA = {
    "id": _V_ID,
    "conversation_id": _V_ID,
    "user_id": _V_ID,
    "status": _V_TEXT,
    "attempt": _V_INT,
    "payload_sha256": _V_TEXT,
    "user_message_id": _V_OPT_ID,
    "result_message_id": _V_OPT_ID,
    "error_code": _V_OPT_STR,
    "error_retryable": _V_BOOL,
    "created_at": _V_OPT_STR,
    "started_at": _V_OPT_STR,
    "finished_at": _V_OPT_STR,
}
_MESSAGE_SCHEMA = {
    "id": _V_ID,
    "conversation_id": _V_ID,
    "owner_user_id": _V_ID,
    "role": _V_TEXT,
    "seq": _V_INT,
    "kind": _V_OPT_STR,
    "revision": _V_OPT_INT,
    "error_code": _V_OPT_STR,
    "text": _V_TEXT,
    "created_at": _V_OPT_STR,
}
_SOURCE_SCHEMA = {
    "message_id": _V_ID,
    "source_id": _V_ID,
    "document_id": _V_ID,
    "version_id": _V_ID,
}
_UNIT_SCHEMA = {
    "unit_id": _V_ID,
    "unit_key": _V_TEXT,
    "kind": _V_TEXT,
    "locator": _V_JSON,
    "text": _V_TEXT,
    "raw_fields": _V_JSON,
    "date_fields": _V_JSON,
    "entity_type": _V_OPT_STR,
    "entity_key": _V_OPT_STR,
    "entity_filters": _V_JSON,
    "document_id": _V_ID,
    "document_name": _V_TEXT,
    "document_deleted": _V_BOOL,
    "version_id": _V_ID,
    "version_number": _V_INT,
    "version_state": _V_TEXT,
    "active_version_id": _V_OPT_ID,
    "active": _V_BOOL,
    "published_at": _V_OPT_STR,
}
_UNRESOLVED_SCHEMA = {
    "unit_id": _V_TEXT,
    "reason": _V_TEXT,
}
_QUERY_STATE_SCHEMA = {
    "stored_user_id": _V_TEXT,
    "stored_conversation_id": _V_TEXT,
    "state_json": _V_JSON,
    "keys": _V_LIST_STR,
}
_CAPTURE_EVENT_SCHEMA = {
    "seq": _V_INT,
    "kind": _V_STR,
    "payload": _V_JSON,
}
_CAPTURE_ERROR_SCHEMA = {
    "code": _V_STR,
    "stage": _V_STR,
    "request_id": _V_OPT_STR,
    "detail": _V_STR,
}
_CAPTURE_SCHEMA = {
    "schema_version": _V_STR,
    "sink_id": _V_ID,
    "status": (_enum(("active", "failed", "sealed")), True),
    "seq": _V_INT,
    "event_count": _V_INT,
    "events": (_v_rows(_CAPTURE_EVENT_SCHEMA), True),
    "errors": (_v_rows(_CAPTURE_ERROR_SCHEMA, max_items=64), True),
}
_TURN_SCHEMA = {
    "turn_index": _V_INT,
    "client_request_id": _V_ID,
    "conversation_id": _V_ID,
    "authenticated_user_id": _V_ID,
    "question_sha256": _V_SHA,
    "http_status": _V_OPT_INT,
    "timed_out": _V_BOOL,
    "started_utc": _V_STR,
    "captured_utc": _V_STR,
    "pre_revision": _V_OPT_INT,
    "post_revision": _V_OPT_INT,
    "capture_revision": _V_OPT_INT,
}
_COMPLETENESS_SCHEMA = {
    "status": (_enum(("complete", "incomplete", "replayed")), True),
    "replay": _V_BOOL,
    "required_event_kinds": _V_LIST_STR,
    "missing_event_kinds": _V_LIST_STR,
    "errors": _V_LIST_STR,
}
_PROJECTION_SCHEMA = {
    "schema_version": _V_STR,
    "snapshot_utc": _V_STR,
    "pre_revision": _V_OPT_INT,
    "capture_revision": _V_OPT_INT,
    "conversation": (_v_opt_row(_CONVERSATION_SCHEMA), True),
    "request": (_v_opt_row(_REQUEST_SCHEMA), True),
    "messages": (_v_rows(_MESSAGE_SCHEMA), True),
    "message_sources": (_v_rows(_SOURCE_SCHEMA), True),
    "units": (_v_rows(_UNIT_SCHEMA), True),
    "unresolved_unit_ids": (_v_rows(_UNRESOLVED_SCHEMA), True),
    "query_states": (_v_rows(_QUERY_STATE_SCHEMA), True),
    "query_states_available": _V_BOOL,
    "rag_business_date": _V_OPT_STR,
    "truncations": _V_LIST_STR,
    "errors": _V_LIST_STR,
}
_SEALED_SCHEMA = {
    "path": _V_STR,
    "sha256": _V_SHA,
    "bytes": _V_INT,
    "turn_index": _V_INT,
    "kind": _V_STR,
}
#: live_h2 专属：本 run 绑定（9 键），与 16 键 bindings 交叉一致且 attempt scope 可复算。
_RUN_BINDING_SCHEMA = {
    "plan_sha256": _V_SHA,
    "run_id": _V_ID,
    "scenario_id": _V_ID,
    "go_sha256": _V_SHA,
    "ledger_sha256": _V_SHA,
    "business_date": (_v_date, True),
    "code_version": _V_SHA,
    "config_sha256": _V_SHA,
    "attempt_scope_sha256": _V_SHA,
}
_ENVELOPE_SCHEMA = {
    "schema_version": _V_STR,
    "fixture_kind": _V_STR,
    "bindings": _V_JSON,
    "adapter_components": _V_JSON,
    "turn": (_v_opt_row(_TURN_SCHEMA), False),  # 必需性在 validate_turn_evidence 显式检查
    "capture": (_v_opt_row(_CAPTURE_SCHEMA), False),
    "db_projection": (_v_opt_row(_PROJECTION_SCHEMA), False),
    "completeness": (_v_opt_row(_COMPLETENESS_SCHEMA), False),
    "sealed": (_v_opt_row(_SEALED_SCHEMA), False),
}
_SUMMARY_ROW_SCHEMA = {
    "schema_version": _V_STR,
    "fixture_kind": _V_STR,
    "turn_index": _V_INT,
    "http_status": _V_OPT_INT,
    "timed_out": _V_BOOL,
    "capture_status": _V_STR,
    "event_count": _V_INT,
    "completeness_status": _V_STR,
    "missing_event_count": _V_INT,
    "error_count": _V_INT,
    "resolved_unit_count": _V_INT,
    "unresolved_unit_count": _V_INT,
    "query_state_row_count": _V_INT,
}
_SUMMARY_SCHEMA = {
    "schema_version": _V_STR,
    "fixture_kind": _V_STR,
    "started_utc": _V_STR,
    "turn_count": _V_INT,
    "status_counts": _V_MAP_INT,
    "blocked": _V_BOOL,
    "bindings": _V_JSON,
}
_MANIFEST_SCHEMA = {
    "schema_version": _V_STR,
    "fixture_kind": _V_STR,
    "started_utc": _V_STR,
    "bindings": _V_JSON,
    "adapter_components": _V_JSON,
    "summary": (_v_opt_row(_SUMMARY_SCHEMA), False),
    "turns": (_v_rows(_SUMMARY_ROW_SCHEMA, max_items=MAX_TURN_COUNT), False),
    "sealed": (_v_opt_row(_SEALED_SCHEMA), False),
}
#: live envelope/manifest 在 v0.1 键集上**只增加** run_binding（必填）；
#: local_mock 未知键仍拒绝，live_h2 缺 run_binding 也拒绝（双向强区分）。
_ENVELOPE_SCHEMA_LIVE = {
    **_ENVELOPE_SCHEMA,
    "run_binding": (_v_opt_row(_RUN_BINDING_SCHEMA), True),
}
_MANIFEST_SCHEMA_LIVE = {
    **_MANIFEST_SCHEMA,
    "run_binding": (_v_opt_row(_RUN_BINDING_SCHEMA), True),
}

#: A-R2 runtime_snapshot（`p2-runtime-snapshot/v0.1`）：产品响应切片 / trace 白名单 /
#: 事件派生使用索引。只允许固定键；未知键/坏类型严格拒绝。
_RS_BINDING_SCHEMA = {
    "client_request_id": _V_ID,
    "conversation_id": _V_ID,
    "pre_revision": _V_OPT_INT,
    "post_revision": _V_OPT_INT,
    "capture_revision": _V_OPT_INT,
}
_RS_SOURCE_SCHEMA = {
    "source_id": _V_ID,
    "document_name": _V_TEXT,
    "version_number": _V_INT,
    "status": _V_TEXT,
    "locator": _V_JSON,
    "published_at": _V_OPT_STR,
}
_RS_PAGINATION_SCHEMA = {
    "page": _V_INT,
    "page_size": _V_INT,
    "total": _V_INT,
    "returned": _V_INT,
    "has_more": _V_BOOL,
    "next_page": _V_OPT_INT,
}
_RS_PRODUCT_SCHEMA = {
    "availability": (_enum(("available", "absent", "unavailable")), True),
    "reason": _V_OPT_STR,
    "request_id": _V_OPT_ID,
    "message_id": _V_OPT_ID,
    "kind": _V_OPT_STR,
    "revision": _V_OPT_INT,
    "http_status": _V_OPT_INT,
    "timed_out": _V_BOOL,
    "sources": (_v_rows(_RS_SOURCE_SCHEMA), True),
    "pagination": (_v_opt_row(_RS_PAGINATION_SCHEMA), True),
    "missing_fields": _V_LIST_STR,
    "error_code": _V_OPT_STR,
    "retryable": _V_BOOL,
}
_RS_TRACE_SCHEMA = {
    "availability": (_enum(("available", "absent", "unavailable")), True),
    "reason": _V_OPT_STR,
    "trace_id": _V_OPT_ID,
    "path": _V_OPT_STR,
    "outcome": _V_OPT_STR,
    "status": _V_OPT_STR,
    "spans": _V_LIST_STR,
    "model_failure_reason": _V_OPT_STR,
}
_RS_CANDIDATE_SCHEMA = {
    "scope": _V_TEXT,
    "candidate": _V_BOOL,
    "unit_ids": _V_LIST_STR,
    "truncated": _V_BOOL,
    "empty": _V_BOOL,
    "seq": _V_INT,
}
_RS_MODEL_EVIDENCE_SCHEMA = {
    "purpose": _V_TEXT,
    "unit_ids": _V_LIST_STR,
    "seq": _V_INT,
}
_RS_FACT_SCHEMA = {
    "entity_key": _V_TEXT,
    "source_unit_id": _V_TEXT,
    "doc_id": _V_TEXT,
    "version_id": _V_TEXT,
    "revision": _V_INT,
}
_RS_INHERITANCE_SCHEMA = {
    "entity_type": _V_TEXT,
    "entity_key": _V_TEXT,
    "source_unit_id": _V_TEXT,
    "source_message_id": _V_OPT_ID,
    "source": _V_TEXT,
}
_RS_CANDIDATE_OBSERVATION_SCHEMA = {
    "availability": (_enum(("observed", "not_observed")), True),
    "reason": _V_OPT_STR,
}
_RS_USAGE_SCHEMA = {
    "availability": (_enum(("complete", "partial", "unavailable")), True),
    "reason": _V_OPT_STR,
    "candidates": (_v_rows(_RS_CANDIDATE_SCHEMA), True),
    "model_evidence": (_v_rows(_RS_MODEL_EVIDENCE_SCHEMA), True),
    "direct_rag_facts": (_v_rows(_RS_FACT_SCHEMA), True),
    "direct_rag_citations": _V_LIST_STR,
    "final_citations": _V_LIST_STR,
    "inheritance": (_v_rows(_RS_INHERITANCE_SCHEMA), True),
    "candidate_observation": (_v_row(_RS_CANDIDATE_OBSERVATION_SCHEMA), True),
}
_RS_SCHEMA = {
    "schema_version": _V_STR,
    "captured_utc": _V_STR,
    "binding": (_v_row(_RS_BINDING_SCHEMA), True),
    "product_response": (_v_row(_RS_PRODUCT_SCHEMA), True),
    "trace": (_v_row(_RS_TRACE_SCHEMA), True),
    "retrieval_use": (_v_row(_RS_USAGE_SCHEMA), True),
}

_SCORING_READINESS_SCHEMA = {
    "four_axis": _V_BOOL,
    "quality_rescore": _V_BOOL,
    "reasons": _V_LIST_STR,
}
_COMPLETENESS_SCHEMA_V03 = {
    **_COMPLETENESS_SCHEMA,
    "scoring_readiness": (_v_row(_SCORING_READINESS_SCHEMA), True),
}
_ENVELOPE_SCHEMA_V03 = {
    **_ENVELOPE_SCHEMA,
    "completeness": (_v_opt_row(_COMPLETENESS_SCHEMA_V03), False),
    "runtime_snapshot": (_v_row(_RS_SCHEMA), True),
}
_ENVELOPE_SCHEMA_V03_LIVE = {
    **_ENVELOPE_SCHEMA_LIVE,
    "completeness": (_v_opt_row(_COMPLETENESS_SCHEMA_V03), False),
    "runtime_snapshot": (_v_row(_RS_SCHEMA), True),
}
_SUMMARY_ROW_SCHEMA_V03 = {
    **_SUMMARY_ROW_SCHEMA,
    "runtime_product_response_present": _V_BOOL,
    "runtime_trace_status": (_enum(("available", "absent", "unavailable")), True),
    "runtime_usage_status": (_enum(("complete", "partial", "unavailable")), True),
    "scoring_quality_rescore": _V_BOOL,
}
_MANIFEST_SCHEMA_V03 = {
    **_MANIFEST_SCHEMA,
    "turns": (_v_rows(_SUMMARY_ROW_SCHEMA_V03, max_items=MAX_TURN_COUNT), False),
}
_MANIFEST_SCHEMA_V03_LIVE = {
    **_MANIFEST_SCHEMA_LIVE,
    "turns": (_v_rows(_SUMMARY_ROW_SCHEMA_V03, max_items=MAX_TURN_COUNT), False),
}


def _require_exact_keys(
    value: Mapping[str, Any],
    schema: dict[str, tuple[Callable[[Any, str], None], bool]],
    name: str,
) -> None:
    """按 schema 做精确校验：未知键、缺失必需字段、嵌套坏类型一律拒绝。

    可选/可空字段必须**存在**（值可为 None）；缺字段与合法 null 明确区分。
    """
    unknown = sorted(set(value) - set(schema))
    if unknown:
        raise EvidenceIntegrityError(name + "_unknown_keys:" + ",".join(str(key) for key in unknown))
    missing = sorted(key for key, (_, required) in schema.items() if required and key not in value)
    if missing:
        raise EvidenceIntegrityError(name + "_missing_required:" + ",".join(missing))
    for key, (validator, _required) in schema.items():
        if key in value:
            validator(value[key], name + "." + key)


def _validate_bindings(value: Any) -> dict[str, str]:
    bindings = _require_mapping(value, "bindings")
    _require_exact_keys(bindings, {key: _V_STR for key in BINDING_KEYS}, "bindings")
    resolved: dict[str, str] = {}
    for key in BINDING_KEYS:
        text = _require_str(bindings.get(key), "binding_" + key)
        if not text or not text.strip():
            raise EvidenceIntegrityError("binding_" + key + "_empty")
        resolved[key] = text
    if resolved["fixture_kind"] not in FIXTURE_KINDS:
        raise EvidenceIntegrityError("unsupported_fixture_kind")
    if resolved["fixture_kind"] == LIVE_FIXTURE_KIND:
        # 磁盘上的 live 证据必须已绑定真实 ingest 后 revision，占位符/非数字一律拒绝。
        if re.fullmatch(r"[0-9]{1,12}", resolved["index_revision"]) is None:
            raise EvidenceIntegrityError("live_index_revision_pending")
    return resolved


def _validate_fixture_identity(top_value: Any, bindings: Mapping[str, str]) -> str:
    """顶层 fixture_kind 必须属于枚举且与 bindings 逐字一致（live_h2 不能冒充 local_mock）。"""
    top = _require_str(top_value, "fixture_kind")
    if top not in FIXTURE_KINDS:
        raise EvidenceIntegrityError("unsupported_fixture_kind")
    if top != bindings["fixture_kind"]:
        raise EvidenceIntegrityError("fixture_kind_mismatch")
    return top


def _is_runtime_version(schema_version: Any) -> bool:
    return str(schema_version) in RUNTIME_SNAPSHOT_VERSIONS


def _allowed_schema_versions(fixture_kind: str) -> tuple[str, ...]:
    return (
        LIVE_EVIDENCE_SCHEMA_VERSIONS
        if str(fixture_kind) == LIVE_FIXTURE_KIND
        else LOCAL_EVIDENCE_SCHEMA_VERSIONS
    )


def _validate_schema_version(schema_version: Any, fixture_kind: str, code: str) -> None:
    if str(schema_version) not in _allowed_schema_versions(fixture_kind):
        raise EvidenceIntegrityError(code)


def _envelope_schema_for(schema_version: Any, fixture_kind: Any) -> dict[str, Any]:
    live = str(fixture_kind) == LIVE_FIXTURE_KIND
    if live:
        return _ENVELOPE_SCHEMA_V03_LIVE if _is_runtime_version(schema_version) else _ENVELOPE_SCHEMA_LIVE
    return _ENVELOPE_SCHEMA_V03 if _is_runtime_version(schema_version) else _ENVELOPE_SCHEMA


def _manifest_schema_for(schema_version: Any, fixture_kind: Any) -> dict[str, Any]:
    live = str(fixture_kind) == LIVE_FIXTURE_KIND
    if live:
        return _MANIFEST_SCHEMA_V03_LIVE if _is_runtime_version(schema_version) else _MANIFEST_SCHEMA_LIVE
    return _MANIFEST_SCHEMA_V03 if _is_runtime_version(schema_version) else _MANIFEST_SCHEMA


def _validate_run_binding_identity(
    value: Any, bindings: Mapping[str, str], fixture_kind: str
) -> None:
    """live 必须带可复算的 run binding；local_mock 出现该键即拒绝（强区分，不静默忽略）。"""
    if fixture_kind != LIVE_FIXTURE_KIND:
        if value is not None:
            raise EvidenceIntegrityError("run_binding_not_allowed")
        return
    try:
        validate_run_binding(value, bindings)
    except EvidenceCaptureConfigError as exc:
        raise EvidenceIntegrityError(str(exc)) from exc


def _validate_capture(value: Any) -> None:
    capture = _require_mapping(value, "capture")
    _require_exact_keys(capture, _CAPTURE_SCHEMA, "capture")
    if capture.get("schema_version") != "mktkb.eval-capture/v0.1":
        raise EvidenceIntegrityError("capture_schema_version_invalid")
    seq = _require_int(capture.get("seq"), "capture_seq")
    count = _require_int(capture.get("event_count"), "capture_event_count")
    events = capture.get("events")
    if not isinstance(events, list) or len(events) > 4096:
        raise EvidenceIntegrityError("capture_events_invalid")
    if count is not None and len(events) != count:
        raise EvidenceIntegrityError("capture_event_count_mismatch")
    seen: list[int] = []
    for event in events:
        item = _require_mapping(event, "capture_event")
        _require_exact_keys(item, _CAPTURE_EVENT_SCHEMA, "capture_event")
        event_seq = _require_int(item.get("seq"), "capture_event_seq")
        kind = _require_str(item.get("kind"), "capture_event_kind")
        if kind not in FIXED_EVENT_KINDS:
            raise EvidenceIntegrityError("capture_event_unknown_kind")
        try:
            clean_event_payload(str(kind), _require_mapping(item.get("payload"), "capture_event_payload"))
        except Exception as exc:  # noqa: BLE001 - 统一转固定完整性错误
            raise EvidenceIntegrityError("capture_event_payload_invalid") from exc
        seen.append(int(event_seq))
    if seen != list(range(1, len(seen) + 1)):
        raise EvidenceIntegrityError("capture_event_seq_invalid")
    if seq is not None and seq != len(seen) and capture.get("status") == "sealed":
        raise EvidenceIntegrityError("capture_seq_mismatch")


def _validate_projection(value: Any) -> None:
    projection = _require_mapping(value, "db_projection")
    _require_exact_keys(projection, _PROJECTION_SCHEMA, "db_projection")
    if projection.get("schema_version") != "p2-hard-evidence-capture-db/v0.1":
        raise EvidenceIntegrityError("projection_schema_version_invalid")
    for code in projection.get("truncations") or ():
        if code not in TRUNCATION_ERRORS:
            raise EvidenceIntegrityError("projection_truncation_unknown")


def _validate_completeness(value: Any, *, runtime_version: bool = False) -> None:
    completeness = _require_mapping(value, "completeness")
    _require_exact_keys(
        completeness,
        _COMPLETENESS_SCHEMA_V03 if runtime_version else _COMPLETENESS_SCHEMA,
        "completeness",
    )
    if runtime_version:
        readiness = _require_mapping(
            completeness.get("scoring_readiness"), "completeness.scoring_readiness"
        )
        _require_exact_keys(readiness, _SCORING_READINESS_SCHEMA, "scoring_readiness")


def _validate_turn_fields(value: Any) -> None:
    turn = _require_mapping(value, "turn")
    _require_exact_keys(turn, _TURN_SCHEMA, "turn")


def _validate_sealed(value: Any) -> None:
    sealed = _require_mapping(value, "sealed")
    _require_exact_keys(sealed, _SEALED_SCHEMA, "sealed")


def _validate_runtime_snapshot(value: Any) -> None:
    """runtime_snapshot 固定键/类型 + availability 与 reason 的互斥语义。"""
    snapshot = _require_mapping(value, "runtime_snapshot")
    _require_exact_keys(snapshot, _RS_SCHEMA, "runtime_snapshot")
    if snapshot.get("schema_version") != "p2-runtime-snapshot/v0.1":
        raise EvidenceIntegrityError("runtime_snapshot_schema_invalid")
    product = _require_mapping(snapshot.get("product_response"), "runtime_snapshot.product_response")
    availability = str(product.get("availability"))
    if availability == "available":
        if product.get("reason") is not None:
            raise EvidenceIntegrityError("runtime_product_response_reason_invalid")
    elif not product.get("reason"):
        raise EvidenceIntegrityError("runtime_product_response_reason_required")
    pagination = product.get("pagination")
    if pagination is not None:
        page = pagination.get("page")
        page_size = pagination.get("page_size")
        total = pagination.get("total")
        returned = pagination.get("returned")
        if isinstance(page, int) and page < 1:
            raise EvidenceIntegrityError("runtime_pagination_invalid")
        if isinstance(page_size, int) and page_size < 1:
            raise EvidenceIntegrityError("runtime_pagination_invalid")
        if isinstance(total, int) and total < 0:
            raise EvidenceIntegrityError("runtime_pagination_invalid")
        if isinstance(returned, int) and returned < 0:
            raise EvidenceIntegrityError("runtime_pagination_invalid")
        if isinstance(total, int) and isinstance(returned, int) and returned > total:
            raise EvidenceIntegrityError("runtime_pagination_invalid")
        if pagination.get("has_more") is True and pagination.get("next_page") is None:
            raise EvidenceIntegrityError("runtime_pagination_invalid")
        if pagination.get("has_more") is False and pagination.get("next_page") is not None:
            raise EvidenceIntegrityError("runtime_pagination_invalid")
    trace = _require_mapping(snapshot.get("trace"), "runtime_snapshot.trace")
    trace_availability = str(trace.get("availability"))
    if trace_availability == "available":
        if trace.get("trace_id") is None or trace.get("reason") is not None:
            raise EvidenceIntegrityError("runtime_trace_invalid")
    elif not trace.get("reason"):
        raise EvidenceIntegrityError("runtime_trace_reason_required")
    usage = _require_mapping(snapshot.get("retrieval_use"), "runtime_snapshot.retrieval_use")
    usage_availability = str(usage.get("availability"))
    if usage_availability == "complete":
        if usage.get("reason") is not None:
            raise EvidenceIntegrityError("runtime_usage_reason_invalid")
    elif not usage.get("reason"):
        raise EvidenceIntegrityError("runtime_usage_reason_required")
    candidate = _require_mapping(
        usage.get("candidate_observation"), "runtime_snapshot.retrieval_use.candidate_observation"
    )
    if str(candidate.get("availability")) == "observed":
        if candidate.get("reason") is not None:
            raise EvidenceIntegrityError("runtime_candidate_observation_invalid")
    elif not candidate.get("reason"):
        raise EvidenceIntegrityError("runtime_candidate_observation_reason_required")


def _validate_phase(phase: str) -> None:
    if phase not in VALIDATION_PHASES:
        raise EvidenceIntegrityError("validation_phase_invalid")


def _validate_sealed_phase(envelope: Mapping[str, Any], phase: str) -> None:
    if phase == "pre_write" and "sealed" in envelope:
        raise EvidenceIntegrityError("sealed_present_before_write")
    if phase == "post_write" and "sealed" not in envelope:
        raise EvidenceIntegrityError("sealed_missing_after_write")


def validate_turn_evidence(
    payload: Any,
    *,
    expected_bindings: Mapping[str, str] | None = None,
    phase: str = "any",
) -> dict[str, Any]:
    """严格校验单个 turn envelope；unknown/缺失必需/坏类型/绑定/阶段错位一律拒绝。"""
    _validate_phase(phase)
    envelope = _require_mapping(payload, "envelope")
    kind = envelope.get("fixture_kind")
    schema_version = envelope.get("schema_version")
    runtime_version = _is_runtime_version(schema_version)
    _require_exact_keys(envelope, _envelope_schema_for(schema_version, kind), "envelope")
    _validate_sealed_phase(envelope, phase)
    bindings = _validate_bindings(envelope.get("bindings"))
    fixture = _validate_fixture_identity(kind, bindings)
    _validate_schema_version(schema_version, fixture, "envelope_schema_version_invalid")
    _validate_run_binding_identity(envelope.get("run_binding"), bindings, fixture)
    _require_mapping(envelope.get("adapter_components"), "adapter_components")
    _require_json_value(envelope.get("adapter_components"), "adapter_components")
    required_keys = ["turn", "capture", "db_projection", "completeness"]
    if runtime_version:
        required_keys.append("runtime_snapshot")
    for required in required_keys:
        if envelope.get(required) is None:
            raise EvidenceIntegrityError("envelope_missing_required:" + required)
    _validate_turn_fields(envelope.get("turn"))
    _validate_capture(envelope.get("capture"))
    _validate_projection(envelope.get("db_projection"))
    _validate_completeness(envelope.get("completeness"), runtime_version=runtime_version)
    if runtime_version:
        _validate_runtime_snapshot(envelope.get("runtime_snapshot"))
    if "sealed" in envelope:
        _validate_sealed(envelope.get("sealed"))
    if expected_bindings is not None:
        for key, value in expected_bindings.items():
            if bindings.get(key) != str(value):
                raise EvidenceIntegrityError("cross_binding_mismatch:" + str(key))
    return dict(envelope)


def validate_manifest(
    payload: Any,
    *,
    expected_bindings: Mapping[str, str] | None = None,
    phase: str = "any",
) -> dict[str, Any]:
    _validate_phase(phase)
    manifest = _require_mapping(payload, "manifest")
    kind = manifest.get("fixture_kind")
    schema_version = manifest.get("schema_version")
    _require_exact_keys(manifest, _manifest_schema_for(schema_version, kind), "manifest")
    _validate_sealed_phase(manifest, phase)
    bindings = _validate_bindings(manifest.get("bindings"))
    fixture = _validate_fixture_identity(kind, bindings)
    _validate_schema_version(schema_version, fixture, "manifest_schema_version_invalid")
    _validate_run_binding_identity(manifest.get("run_binding"), bindings, fixture)
    _require_mapping(manifest.get("adapter_components"), "adapter_components")
    _require_json_value(manifest.get("adapter_components"), "adapter_components")
    _require_str(manifest.get("started_utc"), "manifest_started_utc")
    if manifest.get("summary") is None:
        raise EvidenceIntegrityError("manifest_missing_required:summary")
    summary = _require_mapping(manifest.get("summary"), "summary")
    _require_exact_keys(summary, _SUMMARY_SCHEMA, "summary")
    if manifest.get("turns") is None:
        raise EvidenceIntegrityError("manifest_missing_required:turns")
    if "sealed" in manifest:
        _validate_sealed(manifest.get("sealed"))
    if expected_bindings is not None:
        for key, value in expected_bindings.items():
            if bindings.get(key) != str(value):
                raise EvidenceIntegrityError("cross_binding_mismatch:" + str(key))
    return dict(manifest)


def verify_db_alignment(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """独立 DB 对齐核验：只报原始差异，不产生四轴 verdict。"""
    projection = _require_mapping(evidence.get("db_projection"), "db_projection")
    turn = _require_mapping(evidence.get("turn"), "turn")
    checks: dict[str, bool] = {}
    findings: list[str] = []

    conversation = projection.get("conversation")
    request = projection.get("request")
    checks["conversation_present"] = isinstance(conversation, Mapping)
    checks["request_present"] = isinstance(request, Mapping)
    if isinstance(conversation, Mapping) and isinstance(request, Mapping):
        checks["request_belongs_to_conversation"] = (
            str(request.get("conversation_id")) == str(conversation.get("id"))
        )
        checks["request_user_matches_conversation_owner"] = (
            str(request.get("user_id")) == str(conversation.get("owner_user_id"))
        )
        checks["authenticated_user_matches_conversation_owner"] = (
            str(turn.get("authenticated_user_id")) == str(conversation.get("owner_user_id"))
        )
        checks["request_client_id_matches_turn"] = (
            str(request.get("user_message_id") or "") != ""
        )
    else:
        checks["request_belongs_to_conversation"] = False
        checks["request_user_matches_conversation_owner"] = False
        checks["authenticated_user_matches_conversation_owner"] = False
        checks["request_client_id_matches_turn"] = False

    messages = projection.get("messages") or []
    message_ids = {str(item.get("id")) for item in messages if isinstance(item, Mapping)}
    owner_mismatches = [
        str(item.get("id"))
        for item in messages
        if isinstance(item, Mapping)
        and isinstance(conversation, Mapping)
        and str(item.get("owner_user_id")) != str(conversation.get("owner_user_id"))
    ]
    checks["context_message_owner_consistent"] = not owner_mismatches
    if owner_mismatches:
        findings.append("context_owner_mismatch_count:" + str(len(owner_mismatches)))
    result_message_id = None if not isinstance(request, Mapping) else request.get("result_message_id")
    checks["result_message_present"] = bool(result_message_id) and str(result_message_id) in message_ids

    units = projection.get("units") or []
    unit_checks: list[bool] = []
    for unit in units:
        if not isinstance(unit, Mapping):
            unit_checks.append(False)
            continue
        unit_checks.append(
            bool(unit.get("version_state") == "published")
            and bool(unit.get("document_deleted") is False)
            and bool(unit.get("active_version_id"))
        )
    checks["units_have_lifecycle_projection"] = all(unit_checks) if units else False
    checks["unresolved_units_retained"] = isinstance(projection.get("unresolved_unit_ids"), list)

    query_states = projection.get("query_states") or []
    state_mismatches = [
        str(item.get("stored_conversation_id"))
        for item in query_states
        if isinstance(item, Mapping)
        and str(item.get("stored_conversation_id")) != str(turn.get("conversation_id"))
    ]
    checks["query_state_conversation_consistent"] = not state_mismatches
    if state_mismatches:
        findings.append("query_state_conversation_mismatch_count:" + str(len(state_mismatches)))

    pre_revision = projection.get("pre_revision")
    capture_revision = projection.get("capture_revision")
    checks["revision_not_regressed"] = (
        pre_revision is None or capture_revision is None or int(capture_revision) >= int(pre_revision)
    )
    if not checks["revision_not_regressed"]:
        findings.append("revision_regressed")
    return {"ok": all(checks.values()), "checks": checks, "findings": findings}


def _safe_component(value: str) -> str:
    text = "".join(char for char in str(value) if char.isalnum() or char in {"-", "_"})[:64]
    return text or "evidence"


@dataclass
class EvidenceWriter:
    """认证加密 writer：校验 -> 加密 -> 仓外原子写 -> 读回校验。"""

    root_dir: Path
    key: bytes
    bindings: Mapping[str, str]
    fixture_kind: str = "local_mock"
    max_envelope_bytes: int = MAX_ENVELOPE_BYTES
    run_name: str = "run"
    written: list[dict[str, Any]] = field(default_factory=list)
    status: str = "active"
    last_error: str | None = None

    def __repr__(self) -> str:
        # 严格白名单：绝不回显 Fernet key/绑定/密文路径。
        return (
            f"EvidenceWriter(root_dir={self.root_dir!r}, fixture_kind={self.fixture_kind!r}, "
            f"status={self.status!r}, written={len(self.written)!r})"
        )

    def __post_init__(self) -> None:
        self.root_dir = assert_evidence_root_outside_repo(Path(self.root_dir))
        self.root_dir.mkdir(parents=True, exist_ok=True)
        if self.fixture_kind not in FIXTURE_KINDS:
            raise EvidenceCaptureConfigError("unsupported_fixture_kind")
        if not isinstance(self.key, (bytes, bytearray)) or not self.key:
            raise EvidenceCaptureConfigError("evidence_key_required")
        self._fernet = Fernet(bytes(self.key))
        self.bindings = {str(k): str(v) for k, v in dict(self.bindings).items()}
        self.run_name = _safe_component(self.run_name)

    def _target_path(self, name: str) -> Path:
        root = self.root_dir.resolve()
        stem, dot, suffix = str(name).partition(".")
        safe_name = _safe_component(stem) + (("." + _safe_component(suffix)) if dot else "")
        target = (root / self.run_name / safe_name).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise EvidencePathError("evidence_target_outside_root") from exc
        return target

    def _seal(self, payload: Mapping[str, Any], *, kind: str, turn_index: int) -> dict[str, Any]:
        if self.status != "active":
            raise EvidenceWriteError("evidence_writer_not_active")
        try:
            if kind == "turn":
                validate_turn_evidence(payload, expected_bindings=self.bindings, phase="pre_write")
            else:
                validate_manifest(payload, expected_bindings=self.bindings, phase="pre_write")
            plaintext = canonical_json_bytes(payload)
            if len(plaintext) > self.max_envelope_bytes:
                raise EvidenceIntegrityError("envelope_too_large")
            token = self._fernet.encrypt(plaintext)
            if len(token) > self.max_envelope_bytes:
                raise EvidenceIntegrityError("ciphertext_too_large")
            target = self._target_path(f"{kind}-{turn_index:04d}.fernet")
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, tmp_name = tempfile.mkstemp(prefix=".evidence-", suffix=".tmp", dir=str(target.parent))
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(token)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp_name, target)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass
                raise
            readback = read_encrypted_evidence(
                target, key=bytes(self.key), expected_bindings=self.bindings
            )
            if canonical_json_bytes(readback) != plaintext:
                raise EvidenceIntegrityError("readback_payload_mismatch")
            digest = sha256_hex(token)
            receipt = {
                "path": str(target),
                "sha256": digest,
                "bytes": len(token),
                "turn_index": int(turn_index),
                "kind": kind,
            }
            self.written.append(receipt)
            return receipt
        except EvidenceIOError as exc:
            self.status = "failed"
            self.last_error = exc.code
            raise
        except Exception as exc:  # noqa: BLE001 - 统一固定失败状态
            self.status = "failed"
            self.last_error = "evidence_io_failed"
            raise EvidenceWriteError("evidence_io_failed") from exc

    def write_turn(self, evidence: Mapping[str, Any]) -> dict[str, Any]:
        return self._seal(evidence, kind="turn", turn_index=int(dict(evidence.get("turn") or {}).get("turn_index") or 0))

    def write_manifest(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        return self._seal(manifest, kind="manifest", turn_index=len(self.written))


def read_encrypted_evidence(
    path: Path, *, key: bytes, expected_bindings: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """先验密文与全部绑定，再返回内存对象；拒绝截断/坏 key/跨 run/阶段错位。"""
    raw_path = Path(path)
    try:
        token = raw_path.read_bytes()
    except OSError as exc:
        raise EvidenceIntegrityError("evidence_read_failed") from exc
    if not token or len(token) > MAX_ENVELOPE_BYTES:
        raise EvidenceIntegrityError("evidence_size_invalid")
    try:
        plaintext = Fernet(bytes(key)).decrypt(token)
    except (InvalidToken, ValueError, TypeError) as exc:
        raise EvidenceIntegrityError("fernet_decrypt_failed") from exc
    if len(plaintext) > MAX_ENVELOPE_BYTES:
        raise EvidenceIntegrityError("plaintext_too_large")
    payload = _strict_json_loads(plaintext)
    if not isinstance(payload, Mapping):
        raise EvidenceIntegrityError("envelope_must_be_mapping")
    # 磁盘密文是写入前的 envelope（sealed 回执只存在于写后内存对象，见契约 §3）。
    if "turn" in payload and "capture" in payload:
        return validate_turn_evidence(
            payload, expected_bindings=expected_bindings, phase="pre_write"
        )
    return validate_manifest(payload, expected_bindings=expected_bindings, phase="pre_write")
