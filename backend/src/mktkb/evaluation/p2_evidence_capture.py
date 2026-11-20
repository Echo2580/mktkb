"""A2 同实例独立 DB 投影与逐回合原始证据构造（T207 第一步）。

边界：
- 只采集事实，不注入业务日期、不改产品判定、不给四轴 verdict；
- 观察事件来自 observability.evaluation_capture 的同一固定协议；hook payload 不被当成
  DB 事实——所有消息/请求/来源身份在本模块内用同一隔离实例的只读 session 重新查询；
- 每个声明已使用的 unit_id 都必须有 resolved/unresolved 结果，坏 ID 保留不静默丢弃；
- revision 前后不一致、请求/会话缺行、来源缺失均记 incomplete，不用事后 DB 反填历史。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..observability.evaluation_capture import CaptureSink, capture_scope

EVIDENCE_SCHEMA_VERSION = "p2-hard-evidence-capture/v0.1"
MAX_PROJECTION_MESSAGES = 60
MAX_PROJECTION_UNITS = 128
MAX_TEXT_CHARS = 16384
#: 产品 _load_context 的同一上限（backend/src/mktkb/conversations/service.py MAX_CONTEXT_QUESTIONS）。
#: 用于独立核对上下文条数/身份；产品上限若变化，必须同步本契约并重核准。
MAX_EXPECTED_CONTEXT_MESSAGES = 3

#: 逐回合证据 envelope 必须绑定的身份键（本包全部用 local_mock 合成 fixture）。
BINDING_KEYS = (
    "run_id",
    "plan_id",
    "plan_sha256",
    "dataset_version",
    "manifest_sha256",
    "label_version",
    "suite",
    "scenario_id",
    "scenario_contract_sha256",
    "assignment_sha256",
    "custody_sha256",
    "config_sha256",
    "pipeline_version",
    "index_revision",
    "code_version",
    "fixture_kind",
)
REQUIRED_EVENT_KINDS = (
    "claim_observed",
    "context_observed",
    "plan_observed",
    "answer_result",
    "commit_observed",
)
#: 05 live versioned 扩展：仍保留 local_mock，新增受控真实证据 kind。
#: 顶层/绑定层的 fixture_kind 必须同值（io 强一致），live_h2 不能被当成 local_mock。
FIXTURE_KINDS = ("local_mock", "live_h2")
LIVE_FIXTURE_KIND = "live_h2"
#: live_h2 证据的 versioned schema（local_mock 仍用 EVIDENCE_SCHEMA_VERSION=v0.1）。
LIVE_EVIDENCE_SCHEMA_VERSION = "p2-hard-evidence-capture/v0.2-live"
#: A-R2 新版本：在旧顶层键集上**只增加** `runtime_snapshot`（必填）。旧调用默认仍写
#: v0.1/v0.2-live；新链路必须**显式**选择 v0.3（不静默放宽旧字段集合）。
EVIDENCE_SCHEMA_VERSION_V03 = "p2-hard-evidence-capture/v0.3"
LIVE_EVIDENCE_SCHEMA_VERSION_V03 = "p2-hard-evidence-capture/v0.3-live"
RUNTIME_SNAPSHOT_SCHEMA_VERSION = "p2-runtime-snapshot/v0.1"
LOCAL_EVIDENCE_SCHEMA_VERSIONS = (EVIDENCE_SCHEMA_VERSION, EVIDENCE_SCHEMA_VERSION_V03)
LIVE_EVIDENCE_SCHEMA_VERSIONS = (LIVE_EVIDENCE_SCHEMA_VERSION, LIVE_EVIDENCE_SCHEMA_VERSION_V03)
RUNTIME_SNAPSHOT_VERSIONS = (EVIDENCE_SCHEMA_VERSION_V03, LIVE_EVIDENCE_SCHEMA_VERSION_V03)
PRODUCT_RESPONSE_AVAILABILITY = ("available", "absent", "unavailable")
TRACE_AVAILABILITY = ("available", "absent", "unavailable")
USAGE_AVAILABILITY = ("complete", "partial", "unavailable")
#: 计划阶段无法预知产品 ingest 后的 index_revision；受控入口先以该占位符构造配置，
#: session.bind() 必须用适配器实际 revision 覆盖它，磁盘 envelope/manifest 只允许数字。
LIVE_PENDING_INDEX_REVISION = "pending_post_ingest"
#: live envelope/manifest 必带的本 run 绑定（9 键）：plan/go/ledger/business_date/code/config
#: 与 attempt 范围身份，均来自受控入口在**发送前**已核实的实际对象，不是调用方任意字符串。
RUN_BINDING_KEYS = (
    "plan_sha256",
    "run_id",
    "scenario_id",
    "go_sha256",
    "ledger_sha256",
    "business_date",
    "code_version",
    "config_sha256",
    "attempt_scope_sha256",
)
RUN_BINDING_HASH_KEYS = tuple(
    key for key in RUN_BINDING_KEYS if key not in {"business_date", "run_id", "scenario_id"}
)
_RUN_BINDING_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RUN_BINDING_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
#: run binding 中与 16 个证据绑定键重复、必须逐值相等的键。
RUN_BINDING_CROSS_KEYS = ("run_id", "plan_sha256", "scenario_id", "code_version", "config_sha256")
#: bind() 会按 adapter 实际身份合并的绑定键；其余键在首个回合前已确定，
#: writer 的期望绑定必须与 session 一致，不得被首回合静默覆盖。
ADAPTER_MERGED_BINDING_KEYS = (
    "dataset_version",
    "manifest_sha256",
    "label_version",
    "suite",
    "pipeline_version",
    "index_revision",
)
WRITER_PINNED_BINDING_KEYS = tuple(
    key for key in BINDING_KEYS if key not in ADAPTER_MERGED_BINDING_KEYS
)


class EvidenceCaptureError(RuntimeError):
    code = "evidence_capture_failed"


class EvidenceCaptureConfigError(EvidenceCaptureError):
    code = "evidence_capture_config_error"


class EvidenceCaptureIncomplete(EvidenceCaptureError):
    code = "evidence_capture_incomplete"


class EvidenceCaptureBlocked(EvidenceCaptureError):
    code = "evidence_capture_blocked"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def assert_evidence_root_outside_repo(root: Path) -> Path:
    """证据根必须是仓外新目录；拒绝仓库、旧封存根与符号链接逃逸。"""
    resolved = Path(root).expanduser().resolve(strict=False)
    repo = _repo_root().resolve()
    forbidden = [repo, Path("D:/mktkb-p2-holdout").resolve(strict=False)]
    for blocked in forbidden:
        try:
            resolved.relative_to(blocked)
        except ValueError:
            continue
        raise EvidenceCaptureConfigError(
            f"evidence_root_inside_forbidden:{blocked.as_posix()}"
        )
    if resolved == repo or resolved.as_posix() == "/":
        raise EvidenceCaptureConfigError("evidence_root_invalid")
    return resolved


def attempt_scope_sha256(
    *,
    run_id: str,
    plan_sha256: str,
    scenario_id: str,
    go_sha256: str,
    ledger_sha256: str,
) -> str:
    """本 run 的尝试范围身份：run/plan/scenario/GO/账本前缀的规范摘要（可独立复算）。

    它不是某一次预留的摘要，而是"这一 run 的尝试落在哪段共享账本、用哪份 GO"的身份；
    08/复核方可用同一 5 个值重算，因此不能由调用方任意填写。
    """
    payload = {
        "run_id": str(run_id),
        "plan_sha256": str(plan_sha256),
        "scenario_id": str(scenario_id),
        "go_sha256": str(go_sha256),
        "ledger_sha256": str(ledger_sha256),
    }
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_run_binding(
    value: Any, bindings: Mapping[str, str]
) -> dict[str, str]:
    """live_h2 run binding：固定 9 键 + 64-hex/ISO 日期 + 与 16 键绑定的交叉一致性。"""
    if not isinstance(value, Mapping):
        raise EvidenceCaptureConfigError("run_binding_required")
    unknown = sorted(str(key) for key in set(value) - set(RUN_BINDING_KEYS))
    if unknown:
        raise EvidenceCaptureConfigError("run_binding_unknown_keys:" + ",".join(unknown))
    missing = [key for key in RUN_BINDING_KEYS if key not in value]
    if missing:
        raise EvidenceCaptureConfigError("run_binding_missing:" + ",".join(missing))
    resolved: dict[str, str] = {}
    for key in RUN_BINDING_HASH_KEYS:
        item = value[key]
        if not isinstance(item, str) or _RUN_BINDING_HASH_RE.fullmatch(item) is None:
            raise EvidenceCaptureConfigError("run_binding_hash_invalid:" + key)
        resolved[key] = item
    for key, limit in (("run_id", 96), ("scenario_id", 64)):
        item = value[key]
        if not isinstance(item, str) or not item.strip() or len(item) > limit:
            raise EvidenceCaptureConfigError("run_binding_token_invalid:" + key)
        resolved[key] = item.strip()
    date = value["business_date"]
    if not isinstance(date, str) or _RUN_BINDING_DATE_RE.fullmatch(date) is None:
        raise EvidenceCaptureConfigError("run_binding_business_date_invalid")
    resolved["business_date"] = date
    for key in RUN_BINDING_CROSS_KEYS:
        if resolved[key] != str(bindings.get(key) or ""):
            raise EvidenceCaptureConfigError("run_binding_mismatch:" + key)
    expected_scope = attempt_scope_sha256(
        run_id=resolved["run_id"],
        plan_sha256=resolved["plan_sha256"],
        scenario_id=resolved["scenario_id"],
        go_sha256=resolved["go_sha256"],
        ledger_sha256=resolved["ledger_sha256"],
    )
    if resolved["attempt_scope_sha256"] != expected_scope:
        raise EvidenceCaptureConfigError("run_binding_scope_mismatch")
    return resolved


@dataclass(frozen=True)
class EvidenceCaptureConfig:
    """显式启用的观察配置；默认不构造 = 产品行为逐值不变。"""

    root_dir: Path
    bindings: Mapping[str, str] = field(default_factory=dict)
    fixture_kind: str = "local_mock"
    strict: bool = True
    writer: Any | None = None
    #: live_h2 必填；local_mock 必须为 None（live 不能冒充 mock，反之亦然）。
    run_binding: Mapping[str, str] | None = None
    #: A-R2 显式证据版本；None = 旧默认（local_mock v0.1 / live_h2 v0.2-live）。
    capture_schema_version: str | None = None

    def __repr__(self) -> str:
        # 严格白名单：配置 repr 只给根目录/夹具/严格位，不回显绑定字典/run binding。
        return (
            f"EvidenceCaptureConfig(root_dir={self.root_dir!r}, "
            f"fixture_kind={self.fixture_kind!r}, strict={self.strict!r})"
        )

    def resolved_schema_version(self) -> str:
        """按夹具与显式选择给出唯一 schema 版本；旧调用不传时逐值保持旧默认。"""
        if self.fixture_kind == LIVE_FIXTURE_KIND:
            allowed = LIVE_EVIDENCE_SCHEMA_VERSIONS
            default = LIVE_EVIDENCE_SCHEMA_VERSION
        else:
            allowed = LOCAL_EVIDENCE_SCHEMA_VERSIONS
            default = EVIDENCE_SCHEMA_VERSION
        if self.capture_schema_version is None:
            return default
        version = str(self.capture_schema_version)
        if version not in allowed:
            raise EvidenceCaptureConfigError("unsupported_capture_schema_version")
        return version

    def validated_bindings(self) -> dict[str, str]:
        if self.fixture_kind not in FIXTURE_KINDS:
            raise EvidenceCaptureConfigError("unsupported_fixture_kind")
        resolved: dict[str, str] = {}
        for key in BINDING_KEYS:
            value = self.bindings.get(key)
            if not isinstance(value, str) or not value.strip():
                raise EvidenceCaptureConfigError(f"missing_binding:{key}")
            resolved[key] = value.strip()
        resolved["fixture_kind"] = self.fixture_kind
        if self.fixture_kind == LIVE_FIXTURE_KIND:
            revision = resolved["index_revision"]
            if revision != LIVE_PENDING_INDEX_REVISION and not revision.isdigit():
                raise EvidenceCaptureConfigError("live_index_revision_invalid")
        assert_evidence_root_outside_repo(self.root_dir)
        return resolved

    def validated_run_binding(self) -> dict[str, str] | None:
        """live_h2 必须有 run binding；local_mock 显式禁止（防止 live 冒充）。"""
        if self.fixture_kind != LIVE_FIXTURE_KIND:
            if self.run_binding is not None:
                raise EvidenceCaptureConfigError("run_binding_not_allowed")
            return None
        if self.run_binding is None:
            raise EvidenceCaptureConfigError("run_binding_required")
        return validate_run_binding(self.run_binding, self.validated_bindings())


@dataclass
class TurnCapture:
    """一个产品回合的观察窗口（sink + 身份 + 时点）。"""

    turn_index: int
    client_request_id: str
    conversation_id: str
    authenticated_user_id: str
    question_sha256: str
    pre_revision: int | None
    sink: CaptureSink = field(default_factory=CaptureSink)
    started_utc: str = field(default_factory=_utc_now)
    captured_evidence: dict[str, Any] | None = None
    _entered: bool = False

    def __repr__(self) -> str:
        # 严格白名单：不回显 sink 事件、证据正文或问题摘要原文。
        return (
            f"TurnCapture(turn_index={self.turn_index!r}, "
            f"client_request_id={self.client_request_id!r}, "
            f"conversation_id={self.conversation_id!r}, "
            f"pre_revision={self.pre_revision!r}, "
            f"event_count={len(self.sink.events)!r}, "
            f"captured={'yes' if self.captured_evidence is not None else 'no'})"
        )

    def scope(self):
        if self._entered:
            raise EvidenceCaptureError("turn_scope_already_entered")
        self._entered = True
        return capture_scope(self.sink)


def _open_business_session(db_factory: Any):
    if db_factory is None:
        raise EvidenceCaptureConfigError("db_factory_required")
    session_method = getattr(db_factory, "session", None)
    if callable(session_method):
        return session_method()
    if callable(db_factory):
        return db_factory()
    raise EvidenceCaptureConfigError("db_factory_unsupported")


def _json_friendly(value: Any) -> Any:
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_friendly(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_friendly(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def _bounded_text(value: Any) -> str:
    return _bounded_text_flag(value)[0]


def _bounded_text_flag(value: Any) -> tuple[str, bool]:
    """有界文本：截断必须显式返回标志（不得静默裁剪后宣称完整）。"""
    text = "" if value is None else str(value)
    if len(text) <= MAX_TEXT_CHARS:
        return text, False
    return text[:MAX_TEXT_CHARS], True


#: 投影截断码 -> 完整性固定错误码（截断必然令回合 incomplete）。
TRUNCATION_ERRORS = {
    "messages_limit": "projection_messages_truncated",
    "message_text": "projection_message_text_truncated",
    "units_limit": "projection_units_truncated",
    "unit_text": "projection_unit_text_truncated",
}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _event_unit_ids(events: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            ids.append(text)

    for event in events:
        kind = event.get("kind")
        payload = event.get("payload") or {}
        if kind == "model_input":
            for item in payload.get("evidence") or ():
                if isinstance(item, Mapping):
                    add(item.get("source_id"))
        elif kind == "retrieval_observed":
            for value in payload.get("unit_ids") or ():
                add(value)
        elif kind == "direct_rag_answer":
            for value in payload.get("cited_unit_ids") or ():
                add(value)
            for fact in payload.get("facts") or ():
                if isinstance(fact, Mapping):
                    add(fact.get("source_unit_id"))
        elif kind == "entity_inheritance":
            add(payload.get("source_unit_id"))
        elif kind in {"answer_result", "commit_observed"}:
            for value in payload.get("source_ids") or ():
                add(value)
    return ids


# --------------------------------------------------------------------------- #
# A-R2 runtime_snapshot：产品响应切片 / trace 白名单 / 检索使用派生索引
# --------------------------------------------------------------------------- #


def _payloads_of(events: list[dict[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    return [
        event.get("payload") or {}
        for event in events
        if str(event.get("kind")) == kind
    ]


def _is_replay_events(events: list[dict[str, Any]]) -> bool:
    claims = _payloads_of(events, "claim_observed")
    return len(claims) == 1 and bool(claims[0].get("replay") is True)


def _usage_from_events(events: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """把当次事件派生成固定六层；同一实现同时用于构造与完整性复核（防两侧漂移）。"""
    candidates: list[dict[str, Any]] = []
    model_evidence: list[dict[str, Any]] = []
    direct_rag_facts: list[dict[str, Any]] = []
    direct_rag_citations: list[str] = []
    final_citations: list[str] = []
    inheritance: list[dict[str, Any]] = []
    for event in events:
        kind = str(event.get("kind"))
        payload = event.get("payload") or {}
        seq = event.get("seq")
        if kind == "retrieval_observed":
            candidates.append(
                {
                    "scope": str(payload.get("scope") or ""),
                    "candidate": bool(payload.get("candidate")),
                    "unit_ids": [str(item) for item in payload.get("unit_ids") or ()],
                    "truncated": bool(payload.get("truncated")),
                    "empty": bool(payload.get("empty")),
                    "seq": seq if type(seq) is int else 0,
                }
            )
        elif kind == "model_input":
            model_evidence.append(
                {
                    "purpose": str(payload.get("purpose") or ""),
                    "unit_ids": [
                        str(item.get("source_id"))
                        for item in payload.get("evidence") or ()
                        if isinstance(item, Mapping)
                    ],
                    "seq": seq if type(seq) is int else 0,
                }
            )
        elif kind == "direct_rag_answer":
            for fact in payload.get("facts") or ():
                if not isinstance(fact, Mapping):
                    continue
                direct_rag_facts.append(
                    {
                        "entity_key": str(fact.get("entity_key") or ""),
                        "source_unit_id": str(fact.get("source_unit_id") or ""),
                        "doc_id": str(fact.get("doc_id") or ""),
                        "version_id": str(fact.get("version_id") or ""),
                        "revision": int(fact.get("revision") or 0),
                    }
                )
            for value in payload.get("cited_unit_ids") or ():
                text = str(value or "")
                if text and text not in direct_rag_citations:
                    direct_rag_citations.append(text)
        elif kind in {"answer_result", "commit_observed"}:
            for value in payload.get("source_ids") or ():
                text = str(value or "")
                if text and text not in final_citations:
                    final_citations.append(text)
        elif kind == "entity_inheritance":
            inheritance.append(
                {
                    "entity_type": str(payload.get("entity_type") or ""),
                    "entity_key": str(payload.get("entity_key") or ""),
                    "source_unit_id": str(payload.get("source_unit_id") or ""),
                    "source_message_id": (
                        None
                        if payload.get("source_message_id") is None
                        else str(payload.get("source_message_id"))
                    ),
                    "source": str(payload.get("source") or ""),
                }
            )
    return {
        "candidates": candidates,
        "model_evidence": model_evidence,
        "direct_rag_facts": direct_rag_facts,
        "direct_rag_citations": direct_rag_citations,
        "final_citations": final_citations,
        "inheritance": inheritance,
    }


def _usage_status(
    events: list[dict[str, Any]],
    *,
    sink_status: str | None,
    http_status: int | None,
    timed_out: bool,
) -> tuple[str, str | None]:
    if _is_replay_events(events):
        return "unavailable", "replay"
    if sink_status == "failed":
        return "unavailable", "capture_sink_failed"
    if timed_out:
        return "partial", "turn_timed_out"
    if http_status is None:
        return "partial", "product_response_absent"
    return "complete", None


def _pagination_block(value: Any) -> tuple[dict[str, Any] | None, bool]:
    if value is None:
        return None, True
    if not isinstance(value, Mapping):
        return None, False
    for key in ("page", "page_size", "total", "returned"):
        if type(value.get(key)) is not int:
            return None, False
    if type(value.get("has_more")) is not bool:
        return None, False
    next_page = value.get("next_page")
    if next_page is not None and type(next_page) is not int:
        return None, False
    return (
        {
            "page": int(value["page"]),
            "page_size": int(value["page_size"]),
            "total": int(value["total"]),
            "returned": int(value["returned"]),
            "has_more": bool(value["has_more"]),
            "next_page": None if next_page is None else int(next_page),
        },
        True,
    )


def _pagination_semantically_valid(value: Mapping[str, Any]) -> bool:
    page = value.get("page")
    page_size = value.get("page_size")
    total = value.get("total")
    returned = value.get("returned")
    if not all(type(item) is int for item in (page, page_size, total, returned)):
        return False
    if page < 1 or page_size < 1 or total < 0 or returned < 0 or returned > total:
        return False
    if bool(value.get("has_more")) and value.get("next_page") is None:
        return False
    if not bool(value.get("has_more")) and value.get("next_page") is not None:
        return False
    return True


def _empty_product_response(http_status: int | None, timed_out: bool) -> dict[str, Any]:
    return {
        "request_id": None,
        "message_id": None,
        "kind": None,
        "revision": None,
        "http_status": None if http_status is None else int(http_status),
        "timed_out": bool(timed_out),
        "sources": [],
        "pagination": None,
        "missing_fields": [],
        "error_code": None,
        "retryable": False,
    }


def _product_response_block(
    payload: Any, *, http_status: int | None, timed_out: bool
) -> dict[str, Any]:
    """只保全产品响应白名单切片；坏响应显式 unavailable，不静默丢弃/填空。"""
    block = _empty_product_response(http_status, timed_out)
    if timed_out:
        return {"availability": "absent", "reason": "turn_timed_out", **block}
    if payload is None:
        if http_status is not None:
            # 收到响应但响应体不可解析（非 JSON / 非对象 / 空 body）：阶段不可证。
            return {"availability": "unavailable", "reason": "product_response_unparsable", **block}
        return {"availability": "absent", "reason": "product_response_not_available", **block}
    if not isinstance(payload, Mapping):
        return {"availability": "unavailable", "reason": "product_response_unparsable", **block}

    def _opt_text(value: Any) -> str | None:
        return value if type(value) is str and len(value) <= MAX_TEXT_CHARS else None

    for required_key in ("missing_fields", "retryable"):
        if required_key not in payload:
            return {"availability": "unavailable", "reason": "product_response_invalid", **block}
    request_id = payload.get("request_id")
    message_id = payload.get("message_id")
    revision = payload.get("revision")
    kind = payload.get("kind")
    retryable = payload.get("retryable")
    if request_id is not None and type(request_id) is not str:
        return {"availability": "unavailable", "reason": "product_response_invalid", **block}
    if message_id is not None and type(message_id) is not str:
        return {"availability": "unavailable", "reason": "product_response_invalid", **block}
    if revision is not None and type(revision) is not int:
        return {"availability": "unavailable", "reason": "product_response_invalid", **block}
    if kind is not None and type(kind) is not str:
        return {"availability": "unavailable", "reason": "product_response_invalid", **block}
    if type(retryable) is not bool:
        return {"availability": "unavailable", "reason": "product_response_invalid", **block}
    missing_fields = payload.get("missing_fields")
    if not isinstance(missing_fields, (list, tuple)) or not all(
        type(item) is str for item in missing_fields
    ):
        return {"availability": "unavailable", "reason": "product_response_invalid", **block}
    error_code = payload.get("error_code")
    if error_code is not None and not isinstance(error_code, str):
        return {"availability": "unavailable", "reason": "product_response_invalid", **block}

    sources: list[dict[str, Any]] = []
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, (list, tuple)):
        return {"availability": "unavailable", "reason": "product_sources_invalid", **block}
    for item in raw_sources:
        if not isinstance(item, Mapping):
            return {"availability": "unavailable", "reason": "product_sources_invalid", **block}
        source_id = item.get("source_id")
        document_name = item.get("document_name")
        version_number = item.get("version_number")
        status = item.get("status")
        locator = item.get("locator")
        published_at = item.get("published_at")
        if type(source_id) is not str or not source_id:
            return {"availability": "unavailable", "reason": "product_sources_invalid", **block}
        if type(document_name) is not str or type(status) is not str:
            return {"availability": "unavailable", "reason": "product_sources_invalid", **block}
        if type(version_number) is not int:
            return {"availability": "unavailable", "reason": "product_sources_invalid", **block}
        if not isinstance(locator, Mapping):
            return {"availability": "unavailable", "reason": "product_sources_invalid", **block}
        if published_at is not None and type(published_at) is not str:
            return {"availability": "unavailable", "reason": "product_sources_invalid", **block}
        sources.append(
            {
                "source_id": source_id,
                "document_name": document_name,
                "version_number": int(version_number),
                "status": status,
                "locator": _json_friendly(dict(locator)),
                "published_at": published_at,
            }
        )

    pagination, pagination_ok = _pagination_block(payload.get("pagination"))
    if not pagination_ok:
        return {"availability": "unavailable", "reason": "runtime_pagination_invalid", **block}
    if pagination is not None and not _pagination_semantically_valid(pagination):
        # 结构可读但语义非法（page=0/returned>total/has_more 与 next 矛盾）：
        # 记 unavailable 以便**仍能落盘保留真实阶段**，而不是被严格 writer 整条拒绝。
        return {"availability": "unavailable", "reason": "runtime_pagination_invalid", **block}
    return {
        "availability": "available",
        "reason": None,
        "request_id": request_id,
        "message_id": message_id,
        "kind": kind,
        "revision": revision,
        "http_status": None if http_status is None else int(http_status),
        "timed_out": False,
        "sources": sources,
        "pagination": pagination,
        "missing_fields": [str(item) for item in missing_fields],
        "error_code": error_code,
        "retryable": bool(retryable) if retryable is not None else False,
    }


def _trace_block(trace_observation: Any) -> dict[str, Any]:
    """只保全 trace 白名单字段；原文/headers/attrs dump 一律不进入证据。"""
    observation = trace_observation if isinstance(trace_observation, Mapping) else {}
    trace_id = observation.get("trace_id")
    record = observation.get("record")
    empty = {
        "trace_id": None if trace_id is None else str(trace_id),
        "path": None,
        "outcome": None,
        "status": None,
        "spans": [],
        "model_failure_reason": None,
    }
    if trace_id is None:
        return {"availability": "absent", "reason": "trace_disabled", **empty}
    if not isinstance(record, Mapping):
        return {"availability": "unavailable", "reason": "trace_record_missing", **empty}
    spans = record.get("spans")
    if not isinstance(spans, (list, tuple)) or not all(type(item) is str for item in spans):
        return {"availability": "unavailable", "reason": "trace_record_invalid", **empty}
    reason = record.get("model_failure_reason")
    if reason is not None and type(reason) is not str:
        reason = None
    return {
        "availability": "available",
        "reason": None,
        "trace_id": str(trace_id),
        "path": None if record.get("path") is None else str(record.get("path")),
        "outcome": None if record.get("outcome") is None else str(record.get("outcome")),
        "status": None if record.get("status") is None else str(record.get("status")),
        "spans": [str(item) for item in spans],
        "model_failure_reason": reason,
    }


def build_runtime_snapshot(
    *,
    turn: "TurnCapture",
    events: list[dict[str, Any]],
    projection: Mapping[str, Any],
    post_revision: int | None,
    runtime_observation: Mapping[str, Any] | None,
    sink_status: str | None,
) -> dict[str, Any]:
    """当次回合结束时的唯一快照：产品响应原值 + trace 白名单 + 事件派生使用索引。"""
    observation = runtime_observation if isinstance(runtime_observation, Mapping) else {}
    http_status = observation.get("http_status")
    http_status = http_status if type(http_status) is int else None
    timed_out = bool(observation.get("timed_out"))
    replay = _is_replay_events(events)
    if replay:
        product_response = {
            "availability": "absent",
            "reason": "replay_no_new_product_response",
            **_empty_product_response(http_status, False),
        }
        trace = {
            "availability": "absent",
            "reason": "replay_no_trace",
            "trace_id": None,
            "path": None,
            "outcome": None,
            "status": None,
            "spans": [],
            "model_failure_reason": None,
        }
        usage_status, usage_reason = "unavailable", "replay"
    else:
        product_response = _product_response_block(
            observation.get("product_response_payload"),
            http_status=http_status,
            timed_out=timed_out,
        )
        trace = _trace_block(observation)
        usage_status, usage_reason = _usage_status(
            events,
            sink_status=sink_status,
            http_status=http_status,
            timed_out=timed_out,
        )
    usage = _usage_from_events(events)
    usage["availability"] = usage_status
    usage["reason"] = usage_reason
    if replay:
        usage["candidate_observation"] = {"availability": "not_observed", "reason": "replay"}
    else:
        observed = any(
            str(event.get("kind")) == "retrieval_observed" for event in events
        )
        if observed:
            usage["candidate_observation"] = {"availability": "observed", "reason": None}
        else:
            plans = [
                event.get("payload") or {}
                for event in events
                if str(event.get("kind")) == "plan_observed"
            ]
            path = str(plans[0].get("path") or "") if len(plans) == 1 else ""
            usage["candidate_observation"] = {
                "availability": "not_observed",
                "reason": (
                    "candidate_layer_not_observed" if path == "rag" else "no_retrieval_observed"
                ),
            }
    return {
        "schema_version": RUNTIME_SNAPSHOT_SCHEMA_VERSION,
        "captured_utc": _utc_now(),
        "binding": {
            "client_request_id": str(turn.client_request_id),
            "conversation_id": str(turn.conversation_id),
            "pre_revision": turn.pre_revision,
            "post_revision": post_revision,
            "capture_revision": projection.get("capture_revision"),
        },
        "product_response": product_response,
        "trace": trace,
        "retrieval_use": usage,
    }


def _runtime_snapshot_errors(
    *,
    snapshot: Any,
    events: list[dict[str, Any]],
    projection: Mapping[str, Any],
    turn_identity: Mapping[str, Any] | None,
    post_revision: int | None,
    http_status: int | None,
    timed_out: bool,
    sink_status: str | None,
) -> list[str]:
    """runtime_snapshot 完整性：绑定/响应/轨迹/使用索引与事件逐值一致。"""
    errors: list[str] = []
    if not isinstance(snapshot, Mapping):
        return ["runtime_snapshot_missing"]
    if str(snapshot.get("schema_version")) != RUNTIME_SNAPSHOT_SCHEMA_VERSION:
        errors.append("runtime_snapshot_schema_invalid")
    identity = turn_identity if isinstance(turn_identity, Mapping) else {}
    binding = snapshot.get("binding")
    expected_binding = {
        "client_request_id": str(identity.get("client_request_id") or ""),
        "conversation_id": str(identity.get("conversation_id") or ""),
        "pre_revision": identity.get("pre_revision"),
        "post_revision": post_revision,
        "capture_revision": projection.get("capture_revision"),
    }
    if not isinstance(binding, Mapping) or any(
        binding.get(key) != value for key, value in expected_binding.items()
    ):
        errors.append("runtime_snapshot_binding_mismatch")

    replay = _is_replay_events(events)
    if replay:
        product = snapshot.get("product_response")
        trace = snapshot.get("trace")
        usage = snapshot.get("retrieval_use")
        if (
            not isinstance(product, Mapping)
            or product.get("availability") != "absent"
            or product.get("reason") != "replay_no_new_product_response"
        ):
            errors.append("runtime_snapshot_replay_invalid")
        if (
            not isinstance(trace, Mapping)
            or trace.get("availability") != "absent"
            or trace.get("reason") != "replay_no_trace"
        ):
            errors.append("runtime_snapshot_replay_invalid")
        if (
            not isinstance(usage, Mapping)
            or usage.get("availability") != "unavailable"
            or usage.get("reason") != "replay"
        ):
            errors.append("runtime_snapshot_replay_invalid")
        elif usage.get("candidate_observation") != {
            "availability": "not_observed",
            "reason": "replay",
        }:
            errors.append("runtime_candidate_observation_inconsistent")
        return errors

    # ---- 产品响应：正常结束必须有可用且身份完整的切片；来源版本与投影逐值一致 ----
    product = snapshot.get("product_response")
    if not isinstance(product, Mapping):
        errors.append("runtime_product_response_missing")
        product = {}
    availability = product.get("availability")
    if availability not in PRODUCT_RESPONSE_AVAILABILITY:
        errors.append("runtime_snapshot_schema_invalid")
    if timed_out:
        if availability != "absent" or product.get("reason") != "turn_timed_out":
            errors.append("runtime_product_response_inconsistent")
    elif http_status is not None:
        if availability != "available":
            if product.get("reason") == "runtime_pagination_invalid":
                errors.append("runtime_pagination_invalid")
            else:
                errors.append("runtime_product_response_missing")
        elif product.get("reason") is not None:
            errors.append("runtime_product_response_inconsistent")
    elif availability == "available":
        errors.append("runtime_product_response_inconsistent")

    claims = _payloads_of(events, "claim_observed")
    claim = claims[0] if len(claims) == 1 else None
    commits = _payloads_of(events, "commit_observed")
    commit = commits[0] if len(commits) == 1 else None
    answers = _payloads_of(events, "answer_result")
    answer = answers[0] if len(answers) == 1 else None
    if availability == "available":
        # 200 响应必须带齐可核身份；缺任一项即无法证明“这是该回合的响应”。
        identity_ok = True
        if not (type(product.get("request_id")) is str and product.get("request_id")):
            identity_ok = False
        if not (type(product.get("message_id")) is str and product.get("message_id")):
            identity_ok = False
        if type(product.get("revision")) is not int:
            identity_ok = False
        if not (type(product.get("kind")) is str and product.get("kind")):
            identity_ok = False
        if not identity_ok:
            errors.append("runtime_product_response_incomplete")
        if claim is not None and product.get("request_id") is not None:
            if str(product.get("request_id")) != str(claim.get("request_id")):
                errors.append("runtime_product_response_inconsistent")
        if commit is not None and product.get("message_id") is not None:
            if str(product.get("message_id")) != str(commit.get("message_id")):
                errors.append("runtime_product_response_inconsistent")
        if answer is not None and product.get("kind") is not None:
            if str(product.get("kind")) != str(answer.get("kind")):
                errors.append("runtime_product_response_inconsistent")
        # 产品返回来源必须覆盖已提交的最终引用；两份来源集合不能互相矛盾都算真。
        if commit is not None:
            product_source_ids = {
                str(row.get("source_id"))
                for row in product.get("sources") or ()
                if isinstance(row, Mapping)
            }
            committed = {
                str(item)
                for item in (commit.get("source_ids") or ())
                if str(item)
            }
            if committed - product_source_ids:
                errors.append("runtime_product_response_inconsistent")
        if (
            product.get("revision") is not None
            and post_revision is not None
            and int(product.get("revision")) != int(post_revision)
        ):
            errors.append("runtime_product_response_inconsistent")
        units = {
            str(row.get("unit_id")): row
            for row in (projection.get("units") or ())
            if isinstance(row, Mapping)
        }
        unresolved = {
            str(row.get("unit_id"))
            for row in (projection.get("unresolved_unit_ids") or ())
            if isinstance(row, Mapping)
        }
        for row in product.get("sources") or ():
            if not isinstance(row, Mapping):
                errors.append("runtime_snapshot_schema_invalid")
                continue
            unit_id = str(row.get("source_id"))
            unit = units.get(unit_id)
            if unit is None:
                if unit_id not in unresolved:
                    errors.append("runtime_source_unresolved")
                continue
            if (
                int(row.get("version_number")) != int(unit.get("version_number"))
                or str(row.get("document_name")) != str(unit.get("document_name"))
            ):
                errors.append("runtime_projection_version_mismatch")
        pagination = product.get("pagination")
        if pagination is not None:
            if not isinstance(pagination, Mapping):
                errors.append("runtime_pagination_invalid")
            else:
                ok = (
                    all(type(pagination.get(key)) is int for key in ("page", "page_size", "total", "returned"))
                    and type(pagination.get("has_more")) is bool
                    and (pagination.get("next_page") is None or type(pagination.get("next_page")) is int)
                )
                if not ok:
                    errors.append("runtime_pagination_invalid")
                elif int(pagination.get("page")) < 1 or int(pagination.get("page_size")) < 1:
                    errors.append("runtime_pagination_invalid")
                elif int(pagination.get("total")) < 0 or int(pagination.get("returned")) < 0:
                    errors.append("runtime_pagination_invalid")
                elif int(pagination.get("returned")) > int(pagination.get("total")):
                    errors.append("runtime_pagination_invalid")
                elif bool(pagination.get("has_more")) and pagination.get("next_page") is None:
                    errors.append("runtime_pagination_invalid")
                elif not bool(pagination.get("has_more")) and pagination.get("next_page") is not None:
                    errors.append("runtime_pagination_invalid")

    # ---- trace：absent 必须是“未开启”的如实记录，unavailable/坏形状一律 incomplete ----
    trace = snapshot.get("trace")
    if not isinstance(trace, Mapping):
        errors.append("runtime_snapshot_schema_invalid")
    else:
        trace_availability = trace.get("availability")
        if trace_availability not in TRACE_AVAILABILITY:
            errors.append("runtime_snapshot_schema_invalid")
        elif trace_availability == "unavailable":
            errors.append("runtime_trace_unresolved")
        elif trace_availability == "available":
            if trace.get("trace_id") is None:
                errors.append("runtime_trace_unresolved")
        elif trace.get("reason") != "trace_disabled":
            errors.append("runtime_trace_unresolved")

    # ---- 使用索引：必须与事件逐值一致，且 availability 与真实阶段一致 ----
    usage = snapshot.get("retrieval_use")
    if not isinstance(usage, Mapping):
        errors.append("runtime_snapshot_schema_invalid")
    else:
        derived = _usage_from_events(events)
        for key, value in derived.items():
            if usage.get(key) != value:
                errors.append("runtime_usage_inconsistent")
                break
        expected_status, expected_reason = _usage_status(
            events,
            sink_status=sink_status,
            http_status=http_status,
            timed_out=timed_out,
        )
        if usage.get("availability") != expected_status or usage.get("reason") != expected_reason:
            errors.append("runtime_usage_inconsistent")
        if usage.get("availability") == "partial":
            errors.append("runtime_usage_partial")
        observed = any(str(event.get("kind")) == "retrieval_observed" for event in events)
        if observed:
            expected_candidate = {"availability": "observed", "reason": None}
        else:
            plans = [
                event.get("payload") or {}
                for event in events
                if str(event.get("kind")) == "plan_observed"
            ]
            path = str(plans[0].get("path") or "") if len(plans) == 1 else ""
            expected_candidate = {
                "availability": "not_observed",
                "reason": (
                    "candidate_layer_not_observed" if path == "rag" else "no_retrieval_observed"
                ),
            }
        if usage.get("candidate_observation") != expected_candidate:
            errors.append("runtime_candidate_observation_inconsistent")
    return errors


def read_turn_projection(
    *,
    db_factory: Any,
    qa: Any | None,
    conversation_id: str,
    client_request_id: str,
    unit_ids: list[str],
    pre_revision: int | None,
    snapshot_utc: str,
) -> dict[str, Any]:
    """同一隔离实例的只读 DB 投影：以 DB 为事实，不复制 hook payload。"""
    from sqlalchemy import func, select

    from ..conversations.models import Conversation, ConversationMessage, ConversationRequest, MessageSource
    from ..documents.lifecycle import get_revision
    from ..documents.models import Document, DocumentVersion, SourceUnit

    projection: dict[str, Any] = {
        "schema_version": "p2-hard-evidence-capture-db/v0.1",
        "snapshot_utc": snapshot_utc,
        "pre_revision": pre_revision,
        "capture_revision": None,
        "conversation": None,
        "request": None,
        "messages": [],
        "message_sources": [],
        "units": [],
        "unresolved_unit_ids": [],
        "query_states": [],
        "query_states_available": False,
        "rag_business_date": None,
        "truncations": [],
        "errors": [],
    }
    truncations: set[str] = set()
    session = _open_business_session(db_factory)
    try:
        try:
            conversation_uuid = uuid.UUID(str(conversation_id))
            request_uuid = uuid.UUID(str(client_request_id))
        except (ValueError, AttributeError, TypeError):
            projection["errors"].append("projection_id_invalid")
            return projection
        projection["capture_revision"] = int(get_revision(session))
        conversation_uuid = uuid.UUID(str(conversation_id))
        conversation = session.get(Conversation, conversation_uuid)
        if conversation is None:
            projection["errors"].append("conversation_missing")
        else:
            projection["conversation"] = {
                "id": str(conversation.id),
                "owner_user_id": str(conversation.user_id),
                "deleted": conversation.deleted_at is not None,
                "deleted_at": _iso(conversation.deleted_at),
                "created_at": _iso(conversation.created_at),
                "updated_at": _iso(conversation.updated_at),
            }

        request_uuid = uuid.UUID(str(client_request_id))
        request = session.scalar(
            select(ConversationRequest).where(
                ConversationRequest.conversation_id == conversation_uuid,
                ConversationRequest.client_request_id == request_uuid,
            )
        )
        if request is None:
            projection["errors"].append("request_missing")
        else:
            projection["request"] = {
                "id": str(request.id),
                "conversation_id": str(request.conversation_id),
                "user_id": str(request.user_id),
                "status": str(request.status),
                "attempt": int(request.attempt),
                "payload_sha256": str(request.payload_sha256),
                "user_message_id": _iso(request.user_message_id),
                "result_message_id": _iso(request.result_message_id),
                "error_code": request.error_code,
                "error_retryable": bool(request.error_retryable),
                "created_at": _iso(request.created_at),
                "started_at": _iso(request.started_at),
                "finished_at": _iso(request.finished_at),
            }

        message_total = int(
            session.scalar(
                select(func.count()).select_from(ConversationMessage).where(
                    ConversationMessage.conversation_id == conversation_uuid
                )
            )
            or 0
        )
        # 只保留最近窗口：多轮长会话的当前回合上下文在末尾；被裁掉的旧消息显式记 truncation。
        messages = list(
            reversed(
                session.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == conversation_uuid)
                    .order_by(ConversationMessage.seq.desc())
                    .limit(MAX_PROJECTION_MESSAGES)
                ).all()
            )
        )
        if message_total > len(messages):
            truncations.add("messages_limit")
        message_rows: list[dict[str, Any]] = []
        for message in messages:
            text, text_cut = _bounded_text_flag(message.text)
            if text_cut:
                truncations.add("message_text")
            message_rows.append(
                {
                    "id": str(message.id),
                    "conversation_id": str(message.conversation_id),
                    "owner_user_id": str(message.user_id),
                    "role": str(message.role),
                    "seq": int(message.seq),
                    "kind": message.kind,
                    "revision": None if message.revision is None else int(message.revision),
                    "error_code": message.error_code,
                    "text": text,
                    "created_at": _iso(message.created_at),
                }
            )
        projection["messages"] = message_rows

        if projection["request"] is not None and projection["request"]["result_message_id"]:
            result_uuid = uuid.UUID(projection["request"]["result_message_id"])
            source_rows = session.scalars(
                select(MessageSource).where(MessageSource.message_id == result_uuid)
            ).all()
            projection["message_sources"] = [
                {
                    "message_id": str(row.message_id),
                    "source_id": str(row.source_id),
                    "document_id": str(row.document_id),
                    "version_id": str(row.version_id),
                }
                for row in source_rows
            ]

        from ..retrieval.models import RetrievalUnitIndex

        wanted: list[uuid.UUID] = []
        valid_raw: dict[str, str] = {}
        unique_unit_ids = list(dict.fromkeys(str(item) for item in unit_ids))
        if len(unique_unit_ids) > MAX_PROJECTION_UNITS:
            truncations.add("units_limit")
        for raw in unique_unit_ids[:MAX_PROJECTION_UNITS]:
            try:
                parsed = uuid.UUID(str(raw))
            except (ValueError, AttributeError, TypeError):
                projection["unresolved_unit_ids"].append({"unit_id": str(raw), "reason": "unit_id_invalid"})
                continue
            wanted.append(parsed)
            valid_raw[str(parsed)] = str(raw)
        if wanted:
            rows = session.execute(
                select(SourceUnit, DocumentVersion, Document, RetrievalUnitIndex)
                .join(DocumentVersion, SourceUnit.version_id == DocumentVersion.id)
                .join(Document, SourceUnit.document_id == Document.id)
                .outerjoin(RetrievalUnitIndex, RetrievalUnitIndex.unit_id == SourceUnit.id)
                .where(SourceUnit.id.in_(wanted))
            ).all()
            resolved: set[str] = set()
            for unit, version, document, entity_row in rows:
                resolved.add(str(unit.id))
                raw_fields = _json_friendly(dict(unit.fields or {}))
                date_fields = {
                    str(key): value
                    for key, value in (unit.fields or {}).items()
                    if "日期" in str(key) or "date" in str(key).lower()
                }
                text, text_cut = _bounded_text_flag(unit.text)
                if text_cut:
                    truncations.add("unit_text")
                projection["units"].append(
                    {
                        "unit_id": str(unit.id),
                        "unit_key": str(unit.unit_key),
                        "kind": str(unit.kind),
                        "locator": _json_friendly(dict(unit.locator or {})),
                        "text": text,
                        "raw_fields": raw_fields,
                        "date_fields": _json_friendly(date_fields),
                        "entity_type": None if entity_row is None else _iso(entity_row.entity_type),
                        "entity_key": None if entity_row is None else _iso(entity_row.entity_key),
                        "entity_filters": _json_friendly(dict((entity_row.entity_filters if entity_row else {}) or {})),
                        "document_id": str(document.id),
                        "document_name": str(document.name),
                        "document_deleted": bool(document.deleted),
                        "version_id": str(version.id),
                        "version_number": int(version.number),
                        "version_state": str(version.state),
                        "active_version_id": _iso(document.active_version_id),
                        "active": str(document.active_version_id) == str(version.id),
                        "published_at": _iso(version.published_at),
                    }
                )
            for raw, parsed in valid_raw.items():
                if raw not in resolved:
                    projection["unresolved_unit_ids"].append({"unit_id": raw, "reason": "unit_not_found"})
    finally:
        session.close()

    if qa is not None:
        try:
            from sqlalchemy import select as _select

            from ..rag.models import RagQueryStateRow

            index = qa.index()
            with index.session() as index_session:
                rows = index_session.scalars(
                    _select(RagQueryStateRow).where(
                        RagQueryStateRow.conversation_id == str(conversation_id)
                    )
                ).all()
                for row in rows:
                    raw_state = dict(row.state_json or {})
                    projection["query_states"].append(
                        {
                            "stored_user_id": str(row.user_id),
                            "stored_conversation_id": str(row.conversation_id),
                            "state_json": _json_friendly(raw_state),
                            "keys": sorted(str(key) for key in raw_state.keys()),
                        }
                    )
                projection["query_states_available"] = True
        except Exception as exc:  # noqa: BLE001 - 观察面失败如实记 unavailable
            projection["errors"].append("query_state_unavailable:" + type(exc).__name__)
        projection["rag_business_date"] = getattr(getattr(qa, "config", None), "business_date", None)
    projection["truncations"] = sorted(truncations)
    return projection


def _check_sequence(events: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seqs = [event.get("seq") for event in events]
    if seqs != list(range(1, len(events) + 1)):
        errors.append("event_seq_not_contiguous")
    return errors


def evaluate_completeness(
    *,
    events: list[dict[str, Any]],
    projection: Mapping[str, Any],
    timed_out: bool,
    capture_status: str | None = None,
    capture_errors: list[Mapping[str, Any]] | None = None,
    post_revision: int | None = None,
    authenticated_user_id: str | None = None,
    http_status: int | None = None,
    runtime_snapshot: Mapping[str, Any] | None = None,
    turn_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """只据事件/投影事实给完整性状态；不产生任何四轴 verdict。

    除事件缺项外，本函数还核对：sink 失败状态、投影截断、上下文声明与 DB 身份/顺序/原值、
    领取/提交与 DB 行、revision 同时点、直接 RAG 事实与实体继承的独立可核性。
    任何无法证明同一时点/原值的情况一律 incomplete（不以最新 DB 反填历史）。
    """
    errors: list[str] = list(_check_sequence(events))
    kinds = [str(event.get("kind")) for event in events]
    payloads = [event.get("payload") or {} for event in events]
    by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for kind, payload in zip(kinds, payloads):
        by_kind.setdefault(kind, []).append(payload)
    missing: list[str] = []
    status = "complete"

    claims = by_kind.get("claim_observed", [])
    claim = claims[0] if len(claims) == 1 else None
    if len(claims) != 1:
        errors.append("claim_count_invalid")
    replay = bool(claim and claim.get("replay") is True)
    claim_request_id = str(claim.get("request_id") or "") if claim is not None else ""
    # replay 语义：当且仅当唯一事件是 claim_observed(replay=true)。附带其它事件即为伪造/矛盾。
    if replay and any(kind != "claim_observed" for kind in kinds):
        errors.append("replay_with_unexpected_events")

    # ---- sink 失败/观察错误：失败状态与错误码必须令回合 incomplete ----
    if capture_status is None:
        errors.append("capture_status_unavailable")
    elif capture_status == "failed":
        errors.append("capture_sink_failed")
    elif capture_status not in {"active", "sealed"}:
        errors.append("capture_status_invalid")
    error_rows = list(capture_errors or ())
    if error_rows:
        errors.append("capture_sink_errors")
        codes = sorted(
            {
                str(item.get("code"))[:64]
                for item in error_rows
                if isinstance(item, Mapping) and item.get("code")
            }
        )
        for code in codes:
            errors.append("capture_error:" + code)

    # ---- 投影截断必须显式缺项，不得静默裁剪后 complete ----
    for code in projection.get("truncations") or ():
        errors.append(TRUNCATION_ERRORS.get(str(code), "projection_truncation_unknown"))

    # ---- 模型输入/输出配对 ----
    model_inputs = by_kind.get("model_input", [])
    model_outputs = by_kind.get("model_output", [])
    for purpose in sorted({str(item.get("purpose")) for item in model_inputs}):
        matched = [item for item in model_outputs if str(item.get("purpose")) == purpose]
        expected = [item for item in model_inputs if str(item.get("purpose")) == purpose]
        if len(matched) != len(expected):
            errors.append("model_output_mismatch:" + purpose)
    if model_outputs and not model_inputs:
        errors.append("model_output_without_input")
    if not replay:
        purposes = [str(item.get("purpose")) for item in model_inputs]
        if len(purposes) != len(set(purposes)):
            errors.append("model_input_duplicate_purpose")

    # ---- 计划路径与直接 RAG 事实 ----
    plan_payloads = by_kind.get("plan_observed", [])
    if len(plan_payloads) != 1 and not replay:
        errors.append("plan_observation_count_invalid")
    plan_path = str(plan_payloads[0].get("path") or "") if plan_payloads else ""
    rag_answers = by_kind.get("direct_rag_answer", [])
    if plan_path == "rag":
        if len(rag_answers) != 1:
            missing.append("direct_rag_answer")
    elif rag_answers:
        errors.append("direct_rag_answer_without_rag_plan")

    # ---- 投影基础事实 ----
    if not projection.get("conversation"):
        errors.append("projection_conversation_missing")
    if not projection.get("request"):
        errors.append("projection_request_missing")
    if projection.get("query_states_available") is not True:
        errors.append("projection_query_state_unavailable")
    if projection.get("errors"):
        errors.extend(str(item) for item in projection.get("errors"))

    projection_messages = [
        item for item in (projection.get("messages") or ()) if isinstance(item, Mapping)
    ]
    by_message = {str(item.get("id")): item for item in projection_messages}
    units_by_id = {
        str(item.get("unit_id")): item
        for item in (projection.get("units") or ())
        if isinstance(item, Mapping)
    }
    unresolved_unit_ids = {
        str(item.get("unit_id"))
        for item in (projection.get("unresolved_unit_ids") or ())
        if isinstance(item, Mapping)
    }

    def _seq(item: Mapping[str, Any]) -> int | None:
        value = item.get("seq")
        return value if type(value) is int else None

    # ---- 上下文声明 vs 实际消息（数量/身份/顺序/原值） ----
    context_observed = by_kind.get("context_observed", [])
    context_messages = by_kind.get("context_message", [])
    if not replay:
        if len(context_observed) != 1:
            errors.append("context_observation_count_invalid")
        if len(context_observed) == 1:
            observation = context_observed[0]
            if claim_request_id and str(observation.get("request_id") or "") != claim_request_id:
                errors.append("context_request_id_mismatch")
            declared = observation.get("count")
            if declared != len(context_messages):
                errors.append("context_count_mismatch")
            if bool(observation.get("empty")) != (declared == 0):
                errors.append("context_empty_mismatch")
        for message in context_messages:
            if claim_request_id and str(message.get("request_id") or "") != claim_request_id:
                errors.append("context_request_id_mismatch")
        sequence = [_seq(item) for item in context_messages]
        if any(item is None for item in sequence) or sequence != sorted(sequence) or len(set(sequence)) != len(sequence):
            errors.append("context_message_order_invalid")
        for message in context_messages:
            row = by_message.get(str(message.get("message_id")))
            if row is None:
                errors.append("context_message_unresolved")
                continue
            if (
                str(row.get("owner_user_id")) != str(message.get("owner_user_id"))
                or str(row.get("role")) != str(message.get("role"))
                or _seq(row) != message.get("seq")
                or str(row.get("text")) != str(message.get("text"))
            ):
                errors.append("context_message_mismatch")
        current_seq = claim.get("user_message_seq") if claim is not None else None
        if type(current_seq) is not int:
            errors.append("context_current_message_unavailable")
        else:
            history = [
                item
                for item in projection_messages
                if str(item.get("role")) == "user" and (_seq(item) or 0) < current_seq
            ]
            history.sort(key=lambda item: _seq(item) or 0)
            expected_count = min(MAX_EXPECTED_CONTEXT_MESSAGES, len(history))
            if len(context_messages) != expected_count:
                errors.append("context_count_mismatch")
            expected = history[-expected_count:] if expected_count else []
            if [str(item.get("id")) for item in expected] != [
                str(item.get("message_id")) for item in context_messages
            ]:
                errors.append("context_message_selection_mismatch")

    # ---- 领取身份 vs 独立 DB 投影 ----
    conversation = projection.get("conversation")
    request_row = projection.get("request")
    if claim is not None:
        if isinstance(conversation, Mapping):
            if str(claim.get("conversation_id")) != str(conversation.get("id")):
                errors.append("claim_conversation_mismatch")
            if str(claim.get("owner_user_id")) != str(conversation.get("owner_user_id")):
                errors.append("claim_owner_mismatch")
        if isinstance(request_row, Mapping):
            if str(claim.get("request_id")) != str(request_row.get("id")):
                errors.append("claim_request_mismatch")
            if str(claim.get("conversation_id")) != str(request_row.get("conversation_id")):
                errors.append("claim_request_conversation_mismatch")
            if str(claim.get("owner_user_id")) != str(request_row.get("user_id")):
                errors.append("claim_request_owner_mismatch")
            if str(claim.get("authenticated_user_id")) != str(request_row.get("user_id")):
                errors.append("claim_authenticated_user_mismatch")
        if authenticated_user_id is not None and str(claim.get("authenticated_user_id")) != str(
            authenticated_user_id
        ):
            errors.append("claim_turn_user_mismatch")
        if replay and isinstance(request_row, Mapping):
            if str(request_row.get("status")) != "succeeded":
                errors.append("replay_request_not_succeeded")
        if not replay:
            user_message_id = claim.get("user_message_id")
            user_row = by_message.get(str(user_message_id)) if user_message_id is not None else None
            if user_row is None:
                errors.append("claim_user_message_unresolved")
            elif str(user_row.get("role")) != "user" or _seq(user_row) != claim.get("user_message_seq"):
                errors.append("claim_user_message_mismatch")

    # ---- 提交结果 vs DB 消息原值 ----
    commits = by_kind.get("commit_observed", [])
    if not replay:
        if len(commits) != 1:
            errors.append("commit_count_invalid")
    if len(commits) == 1:
        commit = commits[0]
        if claim is not None and str(commit.get("request_id")) != claim_request_id:
            errors.append("commit_request_mismatch")
        message_id = commit.get("message_id")
        commit_row = by_message.get(str(message_id)) if message_id is not None else None
        if commit_row is None:
            errors.append("commit_message_unresolved")
        elif (
            str(commit_row.get("role")) != "assistant"
            or _seq(commit_row) != commit.get("assistant_seq")
            or str(commit_row.get("kind")) != str(commit.get("kind"))
            or str(commit_row.get("text")) != str(commit.get("text"))
        ):
            errors.append("commit_message_mismatch")

    # ---- 最终回答 vs 领取/提交 ----
    answers = by_kind.get("answer_result", [])
    if not replay and len(answers) != 1:
        errors.append("answer_result_count_invalid")
    if len(answers) == 1:
        answer = answers[0]
        if claim is not None and str(answer.get("request_id")) != claim_request_id:
            errors.append("answer_request_mismatch")
        if len(commits) == 1 and str(answer.get("kind")) != str(commits[0].get("requested_kind")):
            errors.append("answer_commit_kind_mismatch")

    # ---- 直接 RAG 事实：完整事实而非计数；来源必须可解析 ----
    for answer in rag_answers:
        facts = answer.get("facts") or ()
        if type(answer.get("fact_count")) is int and answer.get("fact_count") != len(facts):
            errors.append("direct_rag_fact_count_mismatch")
        if claim is not None and answer.get("request_id") is not None:
            if str(answer.get("request_id")) != claim_request_id:
                errors.append("direct_rag_request_mismatch")
        for fact in facts:
            if not isinstance(fact, Mapping):
                errors.append("direct_rag_fact_invalid")
                continue
            source_unit = str(fact.get("source_unit_id") or "")
            if source_unit and source_unit not in units_by_id and source_unit not in unresolved_unit_ids:
                errors.append("direct_rag_fact_source_unresolved")

    # ---- 实体继承：来源单元/消息与 entity_filters 独立核对 ----
    expected_owner: str | None = None
    if isinstance(conversation, Mapping):
        expected_owner = str(conversation.get("owner_user_id"))
    elif claim is not None:
        expected_owner = str(claim.get("owner_user_id"))
    # 本轮边界 seq：非 replay 用 claim 快照；replay 无本轮 user_message 时用同一请求的 DB 投影定位。
    current_user_seq: int | None = None
    if claim is not None and type(claim.get("user_message_seq")) is int:
        current_user_seq = claim.get("user_message_seq")
    elif isinstance(request_row, Mapping) and request_row.get("user_message_id") is not None:
        request_user_row = by_message.get(str(request_row.get("user_message_id")))
        if request_user_row is not None and str(request_user_row.get("role")) == "user":
            current_user_seq = _seq(request_user_row)
    for inheritance in by_kind.get("entity_inheritance", []):
        if claim is not None and claim_request_id and str(inheritance.get("request_id") or "") != claim_request_id:
            errors.append("entity_inheritance_request_mismatch")
        unit = units_by_id.get(str(inheritance.get("source_unit_id")))
        if unit is None:
            errors.append("entity_inheritance_source_unresolved")
        else:
            filters = unit.get("entity_filters")
            filter_value = filters.get(str(inheritance.get("entity_type"))) if isinstance(filters, Mapping) else None
            if str(filter_value) != str(inheritance.get("entity_key")):
                errors.append("entity_inheritance_mismatch")
        source_message_id = inheritance.get("source_message_id")
        if source_message_id is None:
            errors.append("entity_inheritance_message_unresolved")
            continue
        source_row = by_message.get(str(source_message_id))
        if source_row is None:
            errors.append("entity_inheritance_message_unresolved")
            continue
        if str(source_row.get("role")) != "assistant":
            errors.append("entity_inheritance_message_not_assistant")
            continue
        if expected_owner is not None and str(source_row.get("owner_user_id")) != expected_owner:
            errors.append("entity_inheritance_message_owner_mismatch")
        if (
            isinstance(conversation, Mapping)
            and source_row.get("conversation_id") is not None
            and str(source_row.get("conversation_id")) != str(conversation.get("id"))
        ):
            errors.append("entity_inheritance_message_conversation_mismatch")
        source_seq = _seq(source_row)
        if current_user_seq is None:
            errors.append("entity_inheritance_current_turn_unavailable")
        elif source_seq is None or source_seq >= current_user_seq:
            errors.append("entity_inheritance_message_not_prior")

    # ---- 模型上下文与已声明上下文一致 ----
    if not replay and claim is not None:
        context_texts = [str(item.get("text")) for item in context_messages]
        for model_input in model_inputs:
            if str(model_input.get("request_id") or "") != claim_request_id:
                errors.append("model_input_request_mismatch")
            if [str(item) for item in (model_input.get("context_questions") or ())] != context_texts:
                errors.append("model_input_context_mismatch")

    # ---- revision 与时点：无法证明同一时点即 incomplete ----
    pre_revision = projection.get("pre_revision")
    capture_revision = projection.get("capture_revision")
    if pre_revision is None or capture_revision is None or post_revision is None:
        errors.append("revision_unavailable")
    else:
        pre_value, capture_value, post_value = (
            int(pre_revision),
            int(capture_revision),
            int(post_revision),
        )
        if pre_value > capture_value:
            errors.append("revision_unstable")
        if capture_value != post_value:
            errors.append("revision_snapshot_mismatch")
        if claim is not None and type(claim.get("initial_revision")) is int:
            if claim["initial_revision"] != pre_value:
                errors.append("revision_claim_mismatch")
        if len(commits) == 1:
            commit = commits[0]
            if commit.get("revision_before") != pre_value:
                errors.append("revision_commit_before_mismatch")
            if commit.get("revision_after") != post_value:
                errors.append("revision_commit_after_mismatch")

    # ---- 必需事件（replay 只要求 claim） ----
    if replay:
        if kinds.count("claim_observed") != 1:
            missing.append("claim_observed")
        status = "replayed"
    else:
        for required in REQUIRED_EVENT_KINDS:
            if required not in kinds:
                missing.append(required)
    if timed_out:
        errors.append("turn_timed_out")
    if runtime_snapshot is not None:
        errors.extend(
            _runtime_snapshot_errors(
                snapshot=runtime_snapshot,
                events=events,
                projection=projection,
                turn_identity=turn_identity,
                post_revision=post_revision,
                http_status=http_status,
                timed_out=timed_out,
                sink_status=capture_status,
            )
        )
    if missing or errors:
        status = "incomplete"
    result = {
        "status": status,
        "replay": replay,
        "required_event_kinds": list(REQUIRED_EVENT_KINDS),
        "missing_event_kinds": sorted(set(missing)),
        "errors": sorted(set(errors)),
    }
    if runtime_snapshot is not None:
        result["scoring_readiness"] = _scoring_readiness(status, runtime_snapshot)
    return result


def _scoring_readiness(status: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """显式区分“采集完整 / 四轴可判 / 质量评分输入可重建”，不用一个 pass 概括。"""
    reasons: list[str] = []
    four_axis = status == "complete"
    if status == "replayed":
        reasons.append("replay")
    elif not four_axis:
        reasons.append("completeness_not_complete")
    product = snapshot.get("product_response")
    trace = snapshot.get("trace")
    product_ok = isinstance(product, Mapping) and product.get("availability") == "available"
    trace_ok = isinstance(trace, Mapping) and trace.get("availability") in {"available", "absent"}
    if not product_ok:
        reasons.append("product_response_unavailable")
    if not trace_ok:
        reasons.append("trace_unavailable")
    return {
        "four_axis": bool(four_axis),
        "quality_rescore": bool(four_axis and product_ok and trace_ok),
        "reasons": sorted(set(reasons)),
    }


def build_turn_evidence(
    *,
    turn: TurnCapture,
    bindings: Mapping[str, str],
    adapter_components: Mapping[str, Any] | None,
    http_status: int | None,
    timed_out: bool,
    db_factory: Any,
    qa: Any | None,
    post_revision: int | None,
    writer_receipt: Mapping[str, Any] | None = None,
    run_binding: Mapping[str, str] | None = None,
    schema_version: str = EVIDENCE_SCHEMA_VERSION,
    runtime_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = turn.sink.snapshot()
    events = snapshot["events"]
    unit_ids = _event_unit_ids(events)
    snap_utc = _utc_now()
    projection = read_turn_projection(
        db_factory=db_factory,
        qa=qa,
        conversation_id=turn.conversation_id,
        client_request_id=turn.client_request_id,
        unit_ids=unit_ids,
        pre_revision=turn.pre_revision,
        snapshot_utc=snap_utc,
    )
    runtime_snapshot: dict[str, Any] | None = None
    if str(schema_version) in RUNTIME_SNAPSHOT_VERSIONS:
        runtime_snapshot = build_runtime_snapshot(
            turn=turn,
            events=events,
            projection=projection,
            post_revision=post_revision,
            runtime_observation=runtime_observation,
            sink_status=str(snapshot.get("status")),
        )
    completeness = evaluate_completeness(
        events=events,
        projection=projection,
        timed_out=timed_out,
        capture_status=str(snapshot.get("status")),
        capture_errors=list(snapshot.get("errors") or ()),
        post_revision=post_revision,
        authenticated_user_id=str(turn.authenticated_user_id),
        http_status=http_status,
        runtime_snapshot=runtime_snapshot,
        turn_identity={
            "client_request_id": str(turn.client_request_id),
            "conversation_id": str(turn.conversation_id),
            "pre_revision": turn.pre_revision,
        },
    )
    evidence: dict[str, Any] = {
        "schema_version": str(schema_version),
        "fixture_kind": str(bindings.get("fixture_kind") or "local_mock"),
        "bindings": {str(key): str(value) for key, value in bindings.items()},
        "adapter_components": _json_friendly(dict(adapter_components or {})),
        "turn": {
            "turn_index": int(turn.turn_index),
            "client_request_id": str(turn.client_request_id),
            "conversation_id": str(turn.conversation_id),
            "authenticated_user_id": str(turn.authenticated_user_id),
            "question_sha256": str(turn.question_sha256),
            "http_status": None if http_status is None else int(http_status),
            "timed_out": bool(timed_out),
            "started_utc": str(turn.started_utc),
            "captured_utc": snap_utc,
            "pre_revision": turn.pre_revision,
            "post_revision": post_revision,
            "capture_revision": projection.get("capture_revision"),
        },
        "capture": snapshot,
        "db_projection": projection,
        "completeness": completeness,
    }
    if runtime_snapshot is not None:
        evidence["runtime_snapshot"] = runtime_snapshot
    if run_binding is not None:
        evidence["run_binding"] = {str(key): str(value) for key, value in run_binding.items()}
    if writer_receipt is not None:
        evidence["sealed"] = _json_friendly(dict(writer_receipt))
    return evidence


def public_capture_summary(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """公开层只允许固定键/计数，不含题面、答案、题号或逐题 hash。"""
    completeness = dict(evidence.get("completeness") or {})
    projection = dict(evidence.get("db_projection") or {})
    summary: dict[str, Any] = {
        "schema_version": str(evidence.get("schema_version")),
        "fixture_kind": str(evidence.get("fixture_kind")),
        "turn_index": int(dict(evidence.get("turn") or {}).get("turn_index") or 0),
        "http_status": dict(evidence.get("turn") or {}).get("http_status"),
        "timed_out": bool(dict(evidence.get("turn") or {}).get("timed_out")),
        "capture_status": str(dict(evidence.get("capture") or {}).get("status")),
        "event_count": int(dict(evidence.get("capture") or {}).get("event_count") or 0),
        "completeness_status": str(completeness.get("status")),
        "missing_event_count": len(completeness.get("missing_event_kinds") or ()),
        "error_count": len(completeness.get("errors") or ()),
        "resolved_unit_count": len(projection.get("units") or ()),
        "unresolved_unit_count": len(projection.get("unresolved_unit_ids") or ()),
        "query_state_row_count": len(projection.get("query_states") or ()),
    }
    snapshot = evidence.get("runtime_snapshot")
    if isinstance(snapshot, Mapping):
        product = snapshot.get("product_response")
        trace = snapshot.get("trace")
        usage = snapshot.get("retrieval_use")
        readiness = completeness.get("scoring_readiness")
        summary["runtime_product_response_present"] = (
            isinstance(product, Mapping) and product.get("availability") == "available"
        )
        summary["runtime_trace_status"] = (
            str(trace.get("availability")) if isinstance(trace, Mapping) else "unavailable"
        )
        summary["runtime_usage_status"] = (
            str(usage.get("availability")) if isinstance(usage, Mapping) else "unavailable"
        )
        summary["scoring_quality_rescore"] = bool(
            isinstance(readiness, Mapping) and readiness.get("quality_rescore") is True
        )
    return summary


@dataclass
class EvidenceCaptureSession:
    """一次 run 的观察会话：显式配置、逐回合记录、失败即阻断后续发送。"""

    config: EvidenceCaptureConfig
    bindings: dict[str, str] = field(default_factory=dict)
    adapter_components: dict[str, Any] = field(default_factory=dict)
    turns: list[dict[str, Any]] = field(default_factory=list)
    blocked: bool = False
    last_error: str | None = None
    bound: bool = False
    started_utc: str = field(default_factory=_utc_now)
    #: live_h2 的 run binding（local_mock 恒为空）；只在受控入口给出且已交叉校验后填写。
    run_binding: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.bindings = dict(self.config.validated_bindings())
        self.run_binding = dict(self.config.validated_run_binding() or {})

    def bind(self, adapter_bindings: Mapping[str, Any] | None = None) -> None:
        if self.bound:
            return
        merge: dict[str, str] = {}
        for key in ("dataset_version", "manifest_sha256", "label_version", "suite"):
            value = None if not adapter_bindings else adapter_bindings.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
                merge[key] = str(value).strip()
        if adapter_bindings is not None and adapter_bindings.get("pipeline_version"):
            merge["pipeline_version"] = str(adapter_bindings["pipeline_version"])
        if adapter_bindings is not None and adapter_bindings.get("index_revision") is not None:
            merge["index_revision"] = str(adapter_bindings["index_revision"])
        for key, value in merge.items():
            if key in self.bindings:
                self.bindings[key] = value
        for key in BINDING_KEYS:
            if not self.bindings.get(key):
                raise EvidenceCaptureConfigError(f"missing_binding:{key}")
        if self.config.fixture_kind == LIVE_FIXTURE_KIND:
            # 计划期的占位 revision 不得进入任何 envelope/manifest：必须已被适配器实际值覆盖。
            revision = str(self.bindings.get("index_revision") or "")
            if revision == LIVE_PENDING_INDEX_REVISION or not revision.isdigit():
                self.blocked = True
                self.last_error = "evidence_binding_pending"
                raise EvidenceCaptureConfigError("evidence_binding_pending")
        self.adapter_components = dict(adapter_bindings or {})
        self.bound = True

    def begin_turn(
        self,
        *,
        turn_index: int,
        client_request_id: str,
        conversation_id: str,
        authenticated_user_id: str,
        question_sha256: str,
        pre_revision: int | None,
    ) -> TurnCapture:
        if self.blocked:
            raise EvidenceCaptureBlocked("evidence_capture_session_blocked")
        return TurnCapture(
            turn_index=int(turn_index),
            client_request_id=str(client_request_id),
            conversation_id=str(conversation_id),
            authenticated_user_id=str(authenticated_user_id),
            question_sha256=str(question_sha256),
            pre_revision=pre_revision,
        )

    def finish_turn(
        self,
        turn: TurnCapture,
        *,
        http_status: int | None,
        timed_out: bool,
        db_factory: Any,
        qa: Any | None,
        post_revision: int | None,
        runtime_observation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 采集收尾即封存 sink：写盘快照必须携带 sealed 终态（failed 保持不变），
        # 否则磁盘密文永远是 active，受控消费端只能判 sink_unsealed。
        turn.sink.seal()
        evidence = build_turn_evidence(
            turn=turn,
            bindings=self.bindings,
            adapter_components=self.adapter_components,
            http_status=http_status,
            timed_out=timed_out,
            db_factory=db_factory,
            qa=qa,
            post_revision=post_revision,
            run_binding=self.run_binding or None,
            schema_version=self.config.resolved_schema_version(),
            runtime_observation=runtime_observation,
        )
        if self.config.writer is not None:
            try:
                self._verify_writer_bindings()
            except EvidenceCaptureIncomplete:
                # 首回合前已知绑定不一致：固定失败、保留已构造证据、阻断后续发送；
                # 绝不把 writer 期望绑定静默覆盖成 session 绑定。
                turn.captured_evidence = evidence
                self.turns.append(evidence)
                raise
            # 只有 bind() 声明可合并的 adapter 实际身份（dataset/pipeline/index 等）才同步给 writer。
            try:
                self.config.writer.bindings = dict(self.bindings)
            except AttributeError:
                pass
            try:
                receipt = self.config.writer.write_turn(evidence)
            except Exception:
                # 写入/读回失败：保留已构造的原始证据与固定失败状态，阻断后续发送。
                turn.captured_evidence = evidence
                self.turns.append(evidence)
                self.blocked = True
                self.last_error = "evidence_write_failed"
                raise EvidenceCaptureIncomplete("evidence_write_failed")
            evidence["sealed"] = dict(receipt)
        turn.captured_evidence = evidence
        self.turns.append(evidence)
        status = str(evidence["completeness"]["status"])
        # replay 是合法状态（契约 §2：只要求 claim_observed(replay=true)），strict 不阻断。
        if status not in {"complete", "replayed"} and self.config.strict:
            self.blocked = True
            self.last_error = "evidence_capture_incomplete"
            raise EvidenceCaptureIncomplete("evidence_capture_incomplete")
        return evidence

    def _verify_writer_bindings(self) -> None:
        """writer 的首回合前已知绑定必须与 session 一致；不一致即固定失败，绝不静默覆盖。"""
        writer = self.config.writer
        if writer is None:
            return
        provided = getattr(writer, "bindings", None)
        if not isinstance(provided, Mapping):
            self.blocked = True
            self.last_error = "evidence_writer_binding_missing"
            raise EvidenceCaptureIncomplete("evidence_writer_binding_missing")
        for key in WRITER_PINNED_BINDING_KEYS:
            expected = str(self.bindings.get(key) or "")
            actual = provided.get(key)
            if actual is None:
                self.blocked = True
                self.last_error = "evidence_writer_binding_incomplete"
                raise EvidenceCaptureIncomplete("evidence_writer_binding_incomplete:" + key)
            if str(actual) != expected:
                self.blocked = True
                self.last_error = "evidence_writer_binding_mismatch"
                raise EvidenceCaptureIncomplete("evidence_writer_binding_mismatch:" + key)
        if str(getattr(writer, "fixture_kind", "")) != str(self.config.fixture_kind):
            self.blocked = True
            self.last_error = "evidence_writer_fixture_kind_mismatch"
            raise EvidenceCaptureIncomplete("evidence_writer_fixture_kind_mismatch")

    def __repr__(self) -> str:
        # 严格白名单：不回显回合证据/正文/绑定值。
        return (
            f"EvidenceCaptureSession(turn_count={len(self.turns)!r}, "
            f"blocked={self.blocked!r}, last_error={self.last_error!r}, "
            f"fixture_kind={self.config.fixture_kind!r})"
        )

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.turns:
            status = str(dict(item.get("completeness") or {}).get("status"))
            counts[status] = counts.get(status, 0) + 1
        return {
            "schema_version": self.config.resolved_schema_version(),
            "fixture_kind": self.config.fixture_kind,
            "started_utc": self.started_utc,
            "turn_count": len(self.turns),
            "status_counts": counts,
            "blocked": bool(self.blocked),
            "bindings": dict(self.bindings),
        }

    def finalize(self) -> dict[str, Any]:
        live = self.config.fixture_kind == LIVE_FIXTURE_KIND
        if live and not self.bound:
            # 没有实际产品绑定就没有真实 index_revision：拒绝写"看似完整"的 live manifest。
            self.blocked = True
            self.last_error = "evidence_binding_pending"
            raise EvidenceCaptureIncomplete("evidence_binding_pending")
        manifest = {
            "schema_version": self.config.resolved_schema_version(),
            "fixture_kind": self.config.fixture_kind,
            "started_utc": self.started_utc,
            "bindings": dict(self.bindings),
            "adapter_components": _json_friendly(dict(self.adapter_components)),
            "summary": self.summary(),
            "turns": [public_capture_summary(item) for item in self.turns],
        }
        if live:
            manifest["run_binding"] = dict(self.run_binding)
        if self.config.writer is not None:
            self._verify_writer_bindings()
            try:
                self.config.writer.bindings = dict(self.bindings)
            except AttributeError:
                pass
            receipt = self.config.writer.write_manifest(manifest)
            manifest["sealed"] = dict(receipt)
        return manifest
