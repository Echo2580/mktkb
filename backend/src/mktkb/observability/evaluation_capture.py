"""A1 受控评测观察器：产品边界内的轻量内存 sink、作用域与固定事件协议。

设计约束（见 T207 第一步任务单 A1）：
- 默认关闭：未安装 sink 时 emit 为 no-op，不改变产品 API 判定/检索/重试/计费；
- 产品模块只导入本模块；本模块不导入 evaluation、Fernet 或写盘入口；
- 固定事件种类与白名单字段：未知 kind/字段/类型/超限直接使 sink 失败，
  emit_capture_event 不向产品抛错，但启用观察的评测器必须据 sink 失败/缺事件阻断后续发送；
- capture_scope(sink) 可嵌套且退出必恢复；并发隔离依赖 contextvars；
- 事件只含最小事实，不采认证头、token、网关对象 repr。
"""

from __future__ import annotations

import contextvars
import copy
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

CAPTURE_SCHEMA_VERSION = "mktkb.eval-capture/v0.1"
MAX_EVENTS = 4096
MAX_TEXT_CHARS = 16384
MAX_LIST_ITEMS = 512
MAX_EVIDENCE_ITEMS = 128
MAX_EVIDENCE_TEXT_CHARS = 16384
MAX_ERRORS = 64


class CaptureError(RuntimeError):
    """观察器错误基类；不改变产品业务判定。"""

    code = "capture_error"


class CaptureStateError(CaptureError):
    code = "capture_scope_invalid"


class CaptureEventError(CaptureError):
    code = "capture_event_invalid"


class CaptureOverflow(CaptureError):
    code = "capture_event_overflow"


# --------------------------------------------------------------------------- #
# 固定事件协议
# --------------------------------------------------------------------------- #

_STR = "str"
_OPT_STR = "opt_str"
_INT = "int"
_OPT_INT = "opt_int"
_BOOL = "bool"
_LIST_STR = "list_str"
_OPT_LIST_STR = "opt_list_str"
_DICT_STR = "dict_str"
_EVIDENCE = "evidence"
_OPT_DICT_INT = "opt_dict_int"
_JSON_OBJ = "json_obj"
_FACTS = "facts"


@dataclass(frozen=True)
class _Field:
    kind: str
    required: bool = True


EVENT_FIELDS: dict[str, dict[str, _Field]] = {
    "claim_observed": {
        "request_id": _Field(_STR),
        "conversation_id": _Field(_STR),
        "attempt": _Field(_INT),
        "authenticated_user_id": _Field(_STR),
        "owner_user_id": _Field(_STR),
        "user_message_id": _Field(_OPT_STR),
        "user_message_seq": _Field(_OPT_INT),
        "initial_revision": _Field(_INT),
        "replay": _Field(_BOOL),
    },
    "context_observed": {
        "request_id": _Field(_STR),
        "count": _Field(_INT),
        "empty": _Field(_BOOL),
    },
    "context_message": {
        "request_id": _Field(_STR),
        "message_id": _Field(_STR),
        "owner_user_id": _Field(_STR),
        "role": _Field(_STR),
        "seq": _Field(_INT),
        "text": _Field(_STR),
        "origin": _Field(_STR),
    },
    "entity_inheritance": {
        "request_id": _Field(_STR),
        "entity_type": _Field(_STR),
        "entity_key": _Field(_STR),
        "source_message_id": _Field(_OPT_STR),
        "source_unit_id": _Field(_STR),
        "source": _Field(_STR),
    },
    "query_state_observed": {
        "request_id": _Field(_OPT_STR),
        "user_id": _Field(_STR),
        "conversation_id": _Field(_STR),
        "stored_user_id": _Field(_OPT_STR),
        "stored_conversation_id": _Field(_OPT_STR),
        "row_present": _Field(_BOOL),
        "state_keys": _Field(_LIST_STR),
        "state_json": _Field(_JSON_OBJ),
        "pending_slot": _Field(_OPT_STR),
        "last_kind": _Field(_OPT_STR),
        "turn": _Field(_OPT_INT),
    },
    "query_state_saved": {
        "request_id": _Field(_OPT_STR),
        "user_id": _Field(_STR),
        "conversation_id": _Field(_STR),
        "previous_user_id": _Field(_OPT_STR),
        "previous_conversation_id": _Field(_OPT_STR),
        "row_present": _Field(_BOOL),
        "state_keys": _Field(_LIST_STR),
        "state_json": _Field(_JSON_OBJ),
        "pending_slot": _Field(_OPT_STR),
        "last_kind": _Field(_OPT_STR),
        "turn": _Field(_OPT_INT),
    },
    "query_state_cleared": {
        "request_id": _Field(_OPT_STR),
        "user_id": _Field(_STR),
        "conversation_id": _Field(_STR),
        "row_present": _Field(_BOOL),
        "state_json": _Field(_JSON_OBJ),
    },
    "plan_observed": {
        "request_id": _Field(_STR),
        "path": _Field(_STR),
        "mode": _Field(_STR),
        "filters": _Field(_DICT_STR),
        "terms": _Field(_LIST_STR),
        "as_of": _Field(_OPT_STR),
        "include_future": _Field(_BOOL),
        "enumerate": _Field(_BOOL),
        "clarification": _Field(_BOOL),
        "state_keys": _Field(_LIST_STR),
        "state_as_of": _Field(_OPT_STR),
        "state_pending_slot": _Field(_OPT_STR),
        "state_last_kind": _Field(_OPT_STR),
        # R0-CAPTURE-ROLES：只补枚举级角色码（不含正文/字段中文名/实体/值）。
        # 两个键均可选：旧 envelope 没有它们时清洗/校验结果逐键不变。
        "field_role": _Field(_OPT_STR, required=False),
        "field_roles": _Field(_OPT_LIST_STR, required=False),
        "stores_state": _Field(_STR, required=False),
        "stores_count": _Field(_OPT_INT, required=False),
        "role_unknown_count": _Field(_INT, required=False),
        "safe_roles": _Field(_LIST_STR, required=False),
        "roles_state": _Field(_STR, required=False),
    },
    "retrieval_observed": {
        "request_id": _Field(_OPT_STR),
        "scope": _Field(_STR),
        "unit_ids": _Field(_LIST_STR),
        "candidate": _Field(_BOOL),
        "truncated": _Field(_BOOL),
        "empty": _Field(_BOOL),
        # R0-CAPTURE-DROP：只补枚举级丢弃原因码（不含正文/字段中文名/实体/值）。
        # 可选键：旧 envelope 没有它时清洗/校验结果逐键不变。
        "candidate_dropped_reason": _Field(_OPT_STR, required=False),
        # R0-CAPTURE-DROP 按面：记录面/正文面各一个码，与合成值同事件并存
        # （同一 8 码闭集，复用下方 ``CANDIDATE_DROP_REASONS``；缺键 = 该面未观测）。
        "candidate_dropped_reason_record": _Field(_OPT_STR, required=False),
        "candidate_dropped_reason_document": _Field(_OPT_STR, required=False),
        # R0-CAPTURE-KEYS：候选单元的**身份**（unit_key 列表，形如 sheet:<表>:row:<行号>），
        # 只用于把 candidate_id 解析成稳定标识符；不是正文/值/实体名。两个键均可选且
        # 只在 scope == "rag_candidate_upper_bound" 的事件上携带；缺键 = 未观测，不合成。
        "candidate_unit_keys": _Field(_LIST_STR, required=False),
        "candidate_unit_keys_truncated": _Field(_BOOL, required=False),
        "effective_roles": _Field(_LIST_STR, required=False),
        "effective_mode": _Field(_STR, required=False),
        "effective_enumerate": _Field(_BOOL, required=False),
        "role_unknown_count": _Field(_INT, required=False),
        "roles_state": _Field(_STR, required=False),
        "stores_state": _Field(_STR, required=False),
        "stores_count": _Field(_OPT_INT, required=False),
        "store_join_status": _Field(_STR, required=False),
        "candidate_count": _Field(_INT, required=False),
        "candidate_scope_limit": _Field(_STR, required=False),
        "page_has_more": _Field(_BOOL, required=False),
    },
    "model_input": {
        "request_id": _Field(_STR),
        "purpose": _Field(_STR),
        "question": _Field(_STR),
        "context_questions": _Field(_LIST_STR),
        "context_entities": _Field(_DICT_STR),
        "evidence": _Field(_EVIDENCE),
    },
    "model_output": {
        "request_id": _Field(_STR),
        "purpose": _Field(_STR),
        "status": _Field(_STR),
        "text": _Field(_OPT_STR),
        "source_ids": _Field(_LIST_STR),
        "query_terms": _Field(_LIST_STR),
        "provider_request_id": _Field(_OPT_STR),
        "usage": _Field(_OPT_DICT_INT),
        "error_code": _Field(_OPT_STR),
        "retryable": _Field(_BOOL),
    },
    "answer_result": {
        "request_id": _Field(_STR),
        "kind": _Field(_STR),
        "text": _Field(_STR),
        "source_ids": _Field(_LIST_STR),
        "candidates": _Field(_INT),
        "conflicts": _Field(_INT),
        "missing_fields": _Field(_LIST_STR),
        "error_code": _Field(_OPT_STR),
        "reason": _Field(_OPT_STR),
    },
    "direct_rag_answer": {
        "request_id": _Field(_OPT_STR),
        "kind": _Field(_STR),
        "text": _Field(_STR),
        "reason": _Field(_OPT_STR),
        "answer_source": _Field(_OPT_STR),
        "cited_unit_ids": _Field(_LIST_STR),
        "fact_count": _Field(_INT),
        "facts": _Field(_FACTS),
        "state_keys": _Field(_LIST_STR),
    },
    "commit_observed": {
        "request_id": _Field(_STR),
        "message_id": _Field(_OPT_STR),
        "assistant_seq": _Field(_OPT_INT),
        "kind": _Field(_STR),
        "requested_kind": _Field(_STR),
        "text": _Field(_STR),
        "source_ids": _Field(_LIST_STR),
        "revision_before": _Field(_INT),
        "revision_after": _Field(_INT),
        "knowledge_changed": _Field(_BOOL),
        "error_code": _Field(_OPT_STR),
    },
    "capture_error": {
        "stage": _Field(_STR),
        "code": _Field(_STR),
        "request_id": _Field(_OPT_STR),
        "detail": _Field(_STR),
    },
}
FIXED_EVENT_KINDS = frozenset(EVENT_FIELDS)

#: R0/C12 候选丢弃原因的枚举闭集：``retrieval_observed.candidate_dropped_reason``
#: 只允许这些固定码（无正文/字段中文名/实体/值，只用于诊断）。
CANDIDATE_DROP_REASONS: frozenset[str] = frozenset(
    {
        "filter_miss",
        "kind_miss",
        "term_miss",
        "vector_unavailable",
        "dedup_dropped",
        "limit_dropped",
        "no_drop",
        "not_applicable",
    }
)

SAFE_FIELD_ROLES = frozenset({"location", "contact", "phone", "address", "status", "quantity", "price", "note", "date", "effective_from", "effective_to", "spec", "height", "clause"})
STORE_JOIN_OBSERVATIONS = frozenset({"unknown", "not_applicable", "not_record_or_enumerate", "roles_not_cross_level", "item_filter_missing", "multiple_items", "multiple_stores", "item_row_not_unique", "store_value_missing", "store_value_ambiguous", "store_row_missing", "store_row_ambiguous", "joined", "already_present"})


def safe_roles(values: Any) -> tuple[list[str], int]:
    if type(values) not in (list, tuple):
        return [], 1
    return [v for v in values if type(v) is str and v in SAFE_FIELD_ROLES], sum(
        1 for v in values if type(v) is not str or v not in SAFE_FIELD_ROLES
    )


def safe_stores(state: Any) -> tuple[str, int | None]:
    try:
        value = getattr(state, "stores", None)
    except Exception:
        return "unknown", None
    if type(value) not in (tuple, list):
        return "unknown", None
    return "available", len(value)

#: 枚举级字段的闭集约束（既有类型机制的唯一补充）：(事件 kind, 字段名) -> 允许值。
#: 与 ``_Field`` 的类型/上限校验同处一条清洗路径，未知码 = 事件非法（fail-closed）。
#: 三个候选丢弃原因键共用同一份 ``CANDIDATE_DROP_REASONS``（不复制码表）。
_ENUM_VALUES: dict[tuple[str, str], frozenset[str]] = {
    ("retrieval_observed", "candidate_dropped_reason"): CANDIDATE_DROP_REASONS,
    ("retrieval_observed", "candidate_dropped_reason_record"): CANDIDATE_DROP_REASONS,
    ("retrieval_observed", "candidate_dropped_reason_document"): CANDIDATE_DROP_REASONS,
    ("plan_observed", "stores_state"): frozenset({"available", "unknown"}),
    ("retrieval_observed", "stores_state"): frozenset({"available", "unknown"}),
    ("retrieval_observed", "store_join_status"): STORE_JOIN_OBSERVATIONS,
    ("retrieval_observed", "candidate_scope_limit"): frozenset({"unknown"}),
    ("retrieval_observed", "effective_mode"): frozenset({"record", "document", "unknown"}),
    ("plan_observed", "roles_state"): frozenset({"available", "unknown"}),
    ("retrieval_observed", "roles_state"): frozenset({"available", "unknown"}),
}


# --------------------------------------------------------------------------- #
# 字段校验（固定类型/上限；bool 不得冒充 int）
# --------------------------------------------------------------------------- #


def _clean_optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise CaptureEventError(f"{name}_must_be_str")
    if len(value) > MAX_TEXT_CHARS:
        raise CaptureEventError(f"{name}_too_long")
    return value


def _clean_text(value: Any, name: str) -> str:
    text = _clean_optional_text(value, name)
    if text is None:
        raise CaptureEventError(f"{name}_required")
    return text


def _clean_int(value: Any, name: str) -> int:
    if type(value) is not int:  # 显式拒绝 bool
        raise CaptureEventError(f"{name}_must_be_int")
    return value


def _clean_optional_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _clean_int(value, name)


def _clean_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise CaptureEventError(f"{name}_must_be_bool")
    return value


def _clean_list_text(value: Any, name: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise CaptureEventError(f"{name}_must_be_list")
    if len(value) > MAX_LIST_ITEMS:
        raise CaptureEventError(f"{name}_too_many_items")
    items: list[str] = []
    for item in value:
        if type(item) is not str:
            raise CaptureEventError(f"{name}_item_must_be_str")
        if len(item) > MAX_TEXT_CHARS:
            raise CaptureEventError(f"{name}_item_too_long")
        items.append(item)
    return items


def _clean_optional_list_text(value: Any, name: str) -> list[str]:
    """可选枚举码列表：显式 None 归一为空列表，其余与 :func:`_clean_list_text` 同口径。

    只用于可选键（``required=False``）：缺键不进入本函数，清洗结果也不合成该键。
    """
    if value is None:
        return []
    return _clean_list_text(value, name)


def _clean_dict_text(value: Any, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise CaptureEventError(f"{name}_must_be_mapping")
    if len(value) > MAX_LIST_ITEMS:
        raise CaptureEventError(f"{name}_too_many_keys")
    cleaned: dict[str, str] = {}
    for key, item in value.items():
        if type(key) is not str or type(item) is not str:
            raise CaptureEventError(f"{name}_must_be_str_map")
        if len(key) > 256 or len(item) > MAX_TEXT_CHARS:
            raise CaptureEventError(f"{name}_value_too_long")
        cleaned[key] = item
    return cleaned


def _clean_evidence(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        raise CaptureEventError(f"{name}_must_be_list")
    if len(value) > MAX_EVIDENCE_ITEMS:
        raise CaptureEventError(f"{name}_too_many_items")
    cleaned: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise CaptureEventError(f"{name}_item_must_be_mapping")
        extra = set(item) - {"source_id", "text", "fields"}
        if extra:
            raise CaptureEventError(f"{name}_unknown_item_fields")
        source_id = item.get("source_id")
        text = item.get("text")
        fields = item.get("fields") or {}
        if type(source_id) is not str or len(source_id) > 256:
            raise CaptureEventError(f"{name}_bad_source_id")
        if type(text) is not str or len(text) > MAX_EVIDENCE_TEXT_CHARS:
            raise CaptureEventError(f"{name}_bad_text")
        if not isinstance(fields, Mapping):
            raise CaptureEventError(f"{name}_bad_fields")
        clean_fields: dict[str, Any] = {}
        for key, field_value in fields.items():
            if type(key) is not str or len(key) > 256:
                raise CaptureEventError(f"{name}_bad_field_key")
            if not _json_scalar(field_value):
                raise CaptureEventError(f"{name}_bad_field_value")
            clean_fields[key] = field_value
        cleaned.append({"source_id": source_id, "text": text, "fields": clean_fields})
    return cleaned


def _json_scalar(value: Any) -> bool:
    if value is None or type(value) in (str, int, float, bool):
        return not (type(value) is str and len(value) > MAX_EVIDENCE_TEXT_CHARS)
    if isinstance(value, (list, tuple)) and len(value) <= 64:
        return all(_json_scalar(item) for item in value)
    return False


def _clean_optional_dict_int(value: Any, name: str) -> dict[str, int] | None:
    """usage 映射：值必须是显式 int（bool 不算计数），None 与缺字段由字段声明区分。"""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise CaptureEventError(f"{name}_must_be_mapping")
    if len(value) > MAX_LIST_ITEMS:
        raise CaptureEventError(f"{name}_too_many_keys")
    cleaned: dict[str, int] = {}
    for key, item in value.items():
        if type(key) is not str or len(key) > 256:
            raise CaptureEventError(f"{name}_bad_key")
        if type(item) is not int:
            raise CaptureEventError(f"{name}_value_must_be_int")
        cleaned[key] = item
    return cleaned


def _json_value_ok(value: Any, depth: int = 0) -> bool:
    if value is None or type(value) in (int, float, bool):
        return True
    if type(value) is str:
        return len(value) <= MAX_TEXT_CHARS
    if depth >= 3:
        return False
    if isinstance(value, (list, tuple)):
        return len(value) <= MAX_LIST_ITEMS and all(_json_value_ok(item, depth + 1) for item in value)
    if isinstance(value, Mapping):
        return len(value) <= MAX_LIST_ITEMS and all(
            type(key) is str and len(key) <= 256 and _json_value_ok(item, depth + 1)
            for key, item in value.items()
        )
    return False


def _clean_json_obj(value: Any, name: str) -> dict[str, Any]:
    """原始状态 JSON：保留原值（不转摘要），拒绝非 JSON 类型/超限。"""
    if not isinstance(value, Mapping):
        raise CaptureEventError(f"{name}_must_be_mapping")
    if not _json_value_ok(value):
        raise CaptureEventError(f"{name}_must_be_json")
    return copy.deepcopy(dict(value))


_FACT_FIELDS = (
    "entity_key",
    "entity_label",
    "field_role",
    "field_label",
    "value",
    "source_chunk_id",
    "source_unit_id",
    "doc_id",
    "version_id",
)


def _clean_facts(value: Any, name: str) -> list[dict[str, Any]]:
    """直接 RAG 事实原值：固定字段、不得以计数代替。"""
    if not isinstance(value, (list, tuple)):
        raise CaptureEventError(f"{name}_must_be_list")
    if len(value) > MAX_EVIDENCE_ITEMS:
        raise CaptureEventError(f"{name}_too_many_items")
    cleaned: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise CaptureEventError(f"{name}_item_must_be_mapping")
        if set(item) != set(_FACT_FIELDS) | {"revision"}:
            raise CaptureEventError(f"{name}_unknown_item_fields")
        row: dict[str, Any] = {}
        for key in _FACT_FIELDS:
            text = item.get(key)
            if type(text) is not str or len(text) > MAX_TEXT_CHARS:
                raise CaptureEventError(f"{name}_bad_{key}")
            row[key] = text
        revision = item.get("revision")
        if type(revision) is not int:
            raise CaptureEventError(f"{name}_bad_revision")
        row["revision"] = revision
        cleaned.append(row)
    return cleaned


def _clean_value(field_spec: _Field, value: Any, name: str) -> Any:
    kind = field_spec.kind
    if kind == _STR:
        return _clean_text(value, name)
    if kind == _OPT_STR:
        return _clean_optional_text(value, name)
    if kind == _INT:
        return _clean_int(value, name)
    if kind == _OPT_INT:
        return _clean_optional_int(value, name)
    if kind == _BOOL:
        return _clean_bool(value, name)
    if kind == _LIST_STR:
        return _clean_list_text(value, name)
    if kind == _OPT_LIST_STR:
        return _clean_optional_list_text(value, name)
    if kind == _DICT_STR:
        return _clean_dict_text(value, name)
    if kind == _EVIDENCE:
        return _clean_evidence(value, name)
    if kind == _OPT_DICT_INT:
        return _clean_optional_dict_int(value, name)
    if kind == _JSON_OBJ:
        return _clean_json_obj(value, name)
    if kind == _FACTS:
        return _clean_facts(value, name)
    raise CaptureEventError(f"{name}_unsupported_kind")


def clean_event_payload(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """校验并返回固定协议事件 payload；未知 kind/字段一律拒绝。"""
    spec = EVENT_FIELDS.get(kind)
    if spec is None:
        raise CaptureEventError("unknown_event_kind")
    if not isinstance(payload, Mapping):
        raise CaptureEventError("payload_must_be_mapping")
    unknown = sorted(set(payload) - set(spec))
    if unknown:
        raise CaptureEventError("unknown_event_fields:" + ",".join(str(name) for name in unknown))
    cleaned: dict[str, Any] = {}
    for name, field_spec in spec.items():
        if name not in payload:
            if field_spec.required:
                raise CaptureEventError(f"missing_field:{name}")
            # 可选键缺省 = “该事实未观测”：不合成任何值，保证旧 payload 的清洗结果
            # 与加键前逐键相同（旧证据校验路径行为零变化）。
            continue
        cleaned[name] = _clean_value(field_spec, payload[name], name)
        allowed = _ENUM_VALUES.get((kind, name))
        if allowed is not None and cleaned[name] is not None and cleaned[name] not in allowed:
            raise CaptureEventError(f"{name}_not_in_enum")
        if name in ("stores_count", "role_unknown_count", "candidate_count") and cleaned[name] is not None and cleaned[name] < 0:
            raise CaptureEventError(f"{name}_negative")
        if name in ("safe_roles", "effective_roles") and any(v not in SAFE_FIELD_ROLES for v in cleaned[name]):
            raise CaptureEventError(f"{name}_not_in_enum")
    if "stores_state" in cleaned and "stores_count" in cleaned:
        if (cleaned["stores_state"] == "unknown") != (cleaned["stores_count"] is None):
            raise CaptureEventError("stores_state_count_mismatch")
    if kind == "retrieval_observed" and cleaned.get("scope") == "direct_rag_retrieval" and "candidate_count" in cleaned:
        count = cleaned["candidate_count"]
        ids = cleaned["unit_ids"]
        if (not cleaned["candidate"] or len(ids) != min(count, MAX_LIST_ITEMS)
                or len(set(ids)) != len(ids) or cleaned["empty"] != (count == 0)
                or cleaned["truncated"] != (count > MAX_LIST_ITEMS)):
            raise CaptureEventError("candidate_observation_inconsistent")
    return cleaned


# --------------------------------------------------------------------------- #
# sink / 作用域 / 发射器
# --------------------------------------------------------------------------- #


@dataclass
class CaptureSink:
    """一次受控观察窗口的内存事件收集器；失败后继续发射不再写入。"""

    sink_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    status: str = "active"  # active | failed | sealed
    seq: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    def emit(self, kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self.status != "active":
                raise CaptureStateError("capture_sink_not_active")
            if len(self.events) >= MAX_EVENTS:
                self._fail_locked("capture_event_overflow", "emit", request_id=None, detail="")
                raise CaptureOverflow("capture_event_overflow")
            cleaned = clean_event_payload(kind, payload)
            self.seq += 1
            event = {"seq": self.seq, "kind": kind, "payload": cleaned}
            self.events.append(event)
            return event

    def fail(self, code: str, stage: str, *, request_id: str | None = None, detail: str = "") -> None:
        with self._lock:
            self._fail_locked(code, stage, request_id=request_id, detail=detail)

    def _fail_locked(self, code: str, stage: str, *, request_id: str | None, detail: str) -> None:
        if self.status == "failed":
            return
        self.status = "failed"
        if len(self.errors) < MAX_ERRORS:
            self.errors.append(
                {
                    "code": str(code)[:128],
                    "stage": str(stage)[:128],
                    "request_id": None if request_id is None else str(request_id)[:128],
                    "detail": str(detail)[:256],
                }
            )

    def seal(self) -> None:
        with self._lock:
            if self.status == "active":
                self.status = "sealed"

    def __repr__(self) -> str:
        # 严格白名单：repr 只给计数/状态，绝不回显事件 payload 文本或错误详情。
        with self._lock:
            return (
                f"CaptureSink(status={self.status!r}, seq={self.seq!r}, "
                f"event_count={len(self.events)!r}, error_count={len(self.errors)!r})"
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": CAPTURE_SCHEMA_VERSION,
                "sink_id": self.sink_id,
                "status": self.status,
                "seq": self.seq,
                "event_count": len(self.events),
                "events": copy.deepcopy(self.events),
                "errors": copy.deepcopy(self.errors),
            }


_current_sink: contextvars.ContextVar[CaptureSink | None] = contextvars.ContextVar(
    "mktkb_evaluation_capture_sink", default=None
)


def current_capture_sink() -> CaptureSink | None:
    return _current_sink.get()


def capture_enabled() -> bool:
    sink = _current_sink.get()
    return sink is not None and sink.status == "active"


@contextmanager
def capture_scope(sink: CaptureSink) -> Iterator[CaptureSink]:
    """安装/恢复观察 sink；可嵌套，退出必恢复上一层（含异常路径）。"""
    if not isinstance(sink, CaptureSink):
        raise CaptureStateError("capture_sink_required")
    if sink.status != "active":
        raise CaptureStateError("capture_sink_not_active")
    token = _current_sink.set(sink)
    try:
        yield sink
    finally:
        _current_sink.reset(token)


def emit_capture_event(kind: str, /, **payload: Any) -> CaptureSink | None:
    """固定协议事件发射；无 sink 时 no-op，观察器错误不向产品抛错。

    返回当前 sink 便于调用方断言；未知/非法事件只在 sink 上记固定 capture_error，
    由评测器在回合结束时阻断，不允许吞错后宣称采集成功。
    """
    sink = _current_sink.get()
    if sink is None or sink.status != "active":
        return None
    try:
        sink.emit(kind, payload)
    except CaptureEventError as exc:
        sink.fail("capture_event_invalid", str(kind)[:128], detail=str(exc))
    except CaptureOverflow:
        return None
    except Exception as exc:  # noqa: BLE001 - 观察器自身异常不得改变产品行为
        sink.fail("capture_internal_error", str(kind)[:128], detail=type(exc).__name__)
    return sink
