"""T207 B 包：四轴确定性重算 / 新版聚合 / 场景组合 / 独立 CLI 定向测试。

约束（与派单一致）：
- 只用自建合成数据 + 公开 fixtures + MockChatBackend；零真实模型/产品/付费/预留；
- 不读真实 H2 题面/标签/保管会话/私有密文/真实 key/.env；
- 先红后绿；断言不 skip/xfail；每个 PASS 都由本文件实际执行证明。
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_EVALUATION_TESTS = Path(__file__).resolve().parent
if str(_EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(_EVALUATION_TESTS))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb import copy as product_copy  # noqa: E402
from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, cases_to_jsonl, write_cases  # noqa: E402
from mktkb.evaluation.p2_diagnostics import (  # noqa: E402
    STRATA as DIAGNOSTIC_STRATA,
    validate_diagnostics,
    validate_scorecard,
)
from mktkb.evaluation.p2_evidence_capture import BINDING_KEYS as CAPTURE_BINDING_KEYS  # noqa: E402
from mktkb.evaluation.p2_evidence_io import (  # noqa: E402
    EvidenceWriter,
    read_encrypted_evidence,
    validate_turn_evidence,
)
from mktkb.evaluation.p2_holdout_scenarios import (  # noqa: E402
    AXIS_CRITERIA as SCENARIO_AXIS_CRITERIA,
    BINDING_KEYS as SCENARIO_BINDING_KEYS,
    REASONS as SCENARIO_REASONS,
    compose_hard_evidence_runs,
    validate_hard_evidence_composition,
)
from mktkb.evaluation.p2_scoring import (  # noqa: E402
    P2_HOLDOUT_HARD_FAILURE_KINDS,
    P2_HARD_EVIDENCE_SCORING_SCHEMA_VERSION,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "docs" / "evaluation" / "p2-h2-custody-annotations-v0_2.md"
CONTRACT = ROOT / "docs" / "evaluation" / "p2-h2-scenarios-v0_2.json"
SAFE_DIAG_EVIDENCE = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207-SAFE-DIAG-R1" / "evidence" / "independent"
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"
SENTINEL = "P2HARD_SYNTHETIC_SENTINEL_DO_NOT_EXPORT_beef01"

AUTH_USER = "user-owner-1"
OTHER_USER = "user-other-2"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def asyncio_test(func):
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


# --------------------------------------------------------------------------- #
# 合成冻结 CaseSpec / v0.2 annotation / v0.3 addendum
# --------------------------------------------------------------------------- #


def make_cases(count: int = 30, *, prefix: str = "SYN") -> tuple[CaseSpec, ...]:
    """自建合成 30 题：分层/题序固定；题面/答案均为合成文本，不引用真实 H2。"""
    cases: list[CaseSpec] = []
    for index in range(count):
        stratum = hard.STRATA[index % len(hard.STRATA)]
        multi = index % 6 == 0
        turns: tuple[dict[str, Any], ...] = (
            (
                {"question": "合成第一回合问题" + str(index)},
                {"question": "合成第二回合问题" + str(index)},
            )
            if multi
            else ()
        )
        cases.append(
            CaseSpec(
                case_id=prefix + "-" + f"{index:02d}",
                suite="p2-holdout",
                split="holdout",
                stratum=stratum,
                business_date="2026-10-28",
                question="" if multi else ("合成问题" + str(index) + "：" + SENTINEL),
                turns=turns,
                expected_values=(),
                expected_sources=(),
                relevant_units=(),
                should_refuse=False,
                labeler="synthetic-fixture",
                label_version="synthetic-v1",
            )
        )
    return tuple(cases)


def default_axes(*, safety_na: bool = True) -> dict[str, dict[str, Any]]:
    return {
        "safety": {
            "applicability": "not_applicable" if safety_na else "required",
            "criterion": "benign_business" if safety_na else "forbidden_content",
            "reason": "benign_business" if safety_na else "explicit_forbidden",
            "target_refs": [],
            "targets": [],
            "as_of": None,
            "temporal_intent": "not_applicable" if safety_na else "current",
        },
        "cross_user": {
            "applicability": "required",
            "criterion": "owner_context",
            "reason": "all_user_contexts",
            "target_refs": [],
            "targets": [],
            "as_of": None,
            "temporal_intent": "current",
        },
        "cross_entity": {
            "applicability": "required",
            "criterion": "structured_target",
            "reason": "explicit_single_target",
            "target_refs": [],
            "targets": [],
            "as_of": None,
            "temporal_intent": "current",
        },
        "stale_source": {
            "applicability": "required",
            "criterion": "lifecycle_dates",
            "reason": "business_date_default",
            "target_refs": [],
            "targets": [],
            "as_of": None,
            "temporal_intent": "current",
        },
    }


def make_annotation(
    cases: tuple[CaseSpec, ...],
    *,
    overrides: dict[str, dict[str, dict[str, Any]]] | None = None,
    scenario_ids: tuple[str, ...] = hard.SCENARIO_IDS,
) -> dict[str, Any]:
    bindings = {
        "manifest_sha256": "a" * 64,
        "dataset_version": "synthetic-dataset-v1",
        "label_version": "synthetic-v1",
        "cases_sha256": _sha(cases_to_jsonl(cases).encode("utf-8")),
        "source_map_sha256": "b" * 64,
        "ingest_plan_sha256": "c" * 64,
        "schema_sha256": _sha(SCHEMA.read_bytes()),
        "scenario_contract_sha256": _sha(CONTRACT.read_bytes()),
    }
    rows = []
    for index, case in enumerate(cases):
        axes = default_axes()
        for name, value in ((overrides or {}).get(case.case_id) or {}).items():
            axis = dict(axes[name])
            axis.update(value)
            axes[name] = axis
        rows.append(
            dict(
                case_id=case.case_id,
                scenario_id=scenario_ids[index % len(scenario_ids)],
                axes=axes,
            )
        )
    return {"schema_version": "p2-h2-custody/v0.2", "bindings": bindings, "cases": rows}


def _gap(
    cases: tuple[CaseSpec, ...],
    annotation: dict[str, Any],
    *,
    case_index: int,
    axis: str,
    gap_kind: str,
    resolution: str = "resolved",
    basis: str,
    disclosures: tuple[str, ...],
    axis_value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    original = annotation["cases"][case_index]["axes"][axis]
    if resolution == "kept_unknown":
        assert axis_value is None
        changed: list[str] = []
        value = dict(original)
    else:
        assert axis_value is not None
        changed = sorted(key for key in hard.AXIS_KEYS if axis_value[key] != original[key])
        value = axis_value
    return {
        "case_index": case_index,
        "case_id": cases[case_index].case_id,
        "axis": axis,
        "gap_kind": gap_kind,
        "resolution": resolution,
        "basis": basis,
        "source_refs": [
            {"source": "frozen_question", "doc_code": None, "field": "question", "locator": None},
        ],
        "changed_fields": changed,
        "disclosures": sorted(disclosures),
        "axis_value": value,
    }


def _resolved_entity_axis() -> dict[str, Any]:
    return {
        "applicability": "required",
        "criterion": "structured_target",
        "reason": "explicit_single_target",
        "target_refs": [],
        "targets": [{"entity_type": "store", "entity_key": "SYN-STORE-1", "filters": {}}],
        "as_of": None,
        "temporal_intent": "current",
    }


def _resolved_date_axis() -> dict[str, Any]:
    return {
        "applicability": "required",
        "criterion": "lifecycle_dates",
        "reason": "business_date_default",
        "target_refs": [],
        "targets": [],
        "as_of": "2026-10-28",
        "temporal_intent": "current",
    }


SYNTHETIC_ANNOTATION_CIPHER_SHA = "9d" * 32


def make_addendum(
    cases: tuple[CaseSpec, ...],
    annotation: dict[str, Any],
    *,
    kept_unknown_index: int | None = None,
    annotation_cipher_sha256: str | None = None,
) -> dict[str, Any]:
    entity_axis = _resolved_entity_axis()
    date_axis = _resolved_date_axis()
    gaps = [
        _gap(
            cases,
            annotation,
            case_index=3,
            axis="cross_entity",
            gap_kind="unresolved_entity_target",
            basis="frozen_question_scope",
            disclosures=("request_scoped_collection_no_runtime_record_identity",),
            axis_value=entity_axis,
        ),
        _gap(
            cases,
            annotation,
            case_index=4,
            axis="stale_source",
            gap_kind="unresolved_date_anchor",
            basis="case_business_date_baseline",
            disclosures=("business_date_baseline_not_actual_product_date",),
            axis_value=date_axis,
        ),
        _gap(
            cases,
            annotation,
            case_index=7,
            axis="cross_entity",
            gap_kind="unresolved_entity_target",
            basis="frozen_label_target",
            disclosures=("request_scoped_collection_no_runtime_record_identity",),
            axis_value=dict(entity_axis),
        ),
        _gap(
            cases,
            annotation,
            case_index=9,
            axis="stale_source",
            gap_kind="unresolved_date_anchor",
            basis="case_business_date_baseline",
            disclosures=("business_date_baseline_not_actual_product_date",),
            axis_value=dict(date_axis),
        ),
    ]
    if kept_unknown_index is not None:
        index = kept_unknown_index
        gaps[index] = _gap(
            cases,
            annotation,
            case_index=gaps[index]["case_index"],
            axis=gaps[index]["axis"],
            gap_kind=gaps[index]["gap_kind"],
            resolution="kept_unknown",
            basis="no_provable_basis_keep_unknown",
            disclosures=("historical_intent_date_not_fabricated",),
        )
    bindings = dict(annotation["bindings"])
    payload = {
        "schema_version": "p2-h2-custody-gapaddendum/v0.3",
        "bindings": {
            "annotations_v0_2_sha256": (
                annotation_cipher_sha256
                if annotation_cipher_sha256 is not None
                else _sha(_json_bytes(annotation))
            ),
            "manifest_sha256": bindings["manifest_sha256"],
            "dataset_version": bindings["dataset_version"],
            "label_version": bindings["label_version"],
            "cases_sha256": bindings["cases_sha256"],
            "source_map_sha256": bindings["source_map_sha256"],
            "ingest_plan_sha256": bindings["ingest_plan_sha256"],
            "scenario_contract_sha256": bindings["scenario_contract_sha256"],
            "schema_sha256": bindings["schema_sha256"],
        },
        "gap_summary": {
            "gap_total": len(gaps),
            "resolved_count": sum(1 for gap in gaps if gap["resolution"] == "resolved"),
            "kept_unknown_count": sum(1 for gap in gaps if gap["resolution"] == "kept_unknown"),
            "entity_target_gap_count": sum(1 for gap in gaps if gap["gap_kind"] == "unresolved_entity_target"),
            "date_anchor_gap_count": sum(1 for gap in gaps if gap["gap_kind"] == "unresolved_date_anchor"),
        },
        "gaps": gaps,
    }
    return payload


# --------------------------------------------------------------------------- #
# 合成证据 envelope 构造器（结构必须能过 A/R1 validate_turn_evidence）
# --------------------------------------------------------------------------- #

EVIDENCE_BINDINGS = {key: "local_mock-" + key for key in CAPTURE_BINDING_KEYS}
EVIDENCE_BINDINGS["fixture_kind"] = "local_mock"


def _message(
    message_id: str,
    *,
    role: str = "user",
    seq: int = 1,
    owner_user_id: str = AUTH_USER,
    conversation_id: str = "conv-1",
    kind: str | None = None,
    text: str = "合成消息",
    revision: int = 1,
    error_code: str | None = None,
) -> dict[str, Any]:
    return {
        "id": message_id,
        "conversation_id": conversation_id,
        "owner_user_id": owner_user_id,
        "role": role,
        "seq": seq,
        "kind": kind,
        "revision": revision,
        "error_code": error_code,
        "text": text,
        "created_at": "2026-11-13T00:00:00+00:00",
    }


def _unit_row(
    unit_id: str,
    *,
    unit_key: str | None = None,
    entity_type: str | None = None,
    entity_key: str | None = None,
    entity_filters: dict[str, Any] | None = None,
    raw_fields: dict[str, Any] | None = None,
    text: str = "合成来源正文",
    document_id: str = "doc-1",
    version_id: str = "ver-1",
    version_state: str = "published",
    active: bool = True,
    active_version_id: str | None = None,
    document_deleted: bool = False,
    version_number: int = 1,
    document_name: str = "合成资料",
    locator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "unit_key": unit_key or ("key:" + unit_id),
        "kind": "table_row",
        "locator": locator or {"sheet": "合成表", "row": 8},
        "text": text,
        "raw_fields": raw_fields or {},
        "date_fields": {},
        "entity_type": entity_type,
        "entity_key": entity_key,
        "entity_filters": entity_filters or {},
        "document_id": document_id,
        "document_name": document_name,
        "document_deleted": document_deleted,
        "version_id": version_id,
        "version_number": version_number,
        "version_state": version_state,
        "active_version_id": active_version_id or version_id,
        "active": active,
        "published_at": "2026-10-01T00:00:00+00:00",
    }


def _fact_row(
    source_unit_id: str,
    *,
    entity_key: str = "",
    entity_label: str = "",
    field_role: str = "value",
    field_label: str = "字段",
    value: str = "合成值",
    doc_id: str = "doc-1",
    version_id: str = "ver-1",
    revision: int = 1,
) -> dict[str, Any]:
    return {
        "entity_key": entity_key,
        "entity_label": entity_label,
        "field_role": field_role,
        "field_label": field_label,
        "value": value,
        "source_chunk_id": "chunk-1",
        "source_unit_id": source_unit_id,
        "doc_id": doc_id,
        "version_id": version_id,
        "revision": revision,
    }


def build_evidence(**opts: Any) -> dict[str, Any]:
    """构造结构合法的 turn envelope；默认是“全部可核”的干净回合。"""
    conversation_id = str(opts.get("conversation_id", "conv-1"))
    request_id = str(opts.get("request_id", "req-1"))
    client_request_id = str(opts.get("client_request_id", "client-1"))
    owner = str(opts.get("owner_user_id", AUTH_USER))
    authenticated = str(opts.get("authenticated_user_id", AUTH_USER))
    request_user = str(opts.get("request_user_id", owner))
    context = list(opts.get("context") or ())
    extra_messages = list(opts.get("extra_messages") or ())
    units = [dict(item) for item in (opts.get("units") or ())]
    for index, unit in enumerate(units):
        unit.setdefault("unit_id", "unit-" + str(index + 1))
    unit_rows = [_unit_row(**dict(unit)) for unit in units]
    used_ids = list(opts.get("used_unit_ids", [row["unit_id"] for row in unit_rows]))
    model_evidence = opts.get("model_evidence")
    if model_evidence is None:
        model_evidence = list(used_ids)
    final_source_ids = opts.get("final_source_ids")
    if final_source_ids is None:
        final_source_ids = list(used_ids)
    facts = [dict(item) for item in (opts.get("facts") or ())]
    plan = {
        "path": "legacy",
        "mode": "record",
        "filters": {},
        "terms": [],
        "as_of": None,
        "include_future": False,
        "enumerate": False,
        "clarification": False,
        "state_keys": [],
        "state_as_of": None,
        "state_pending_slot": None,
        "state_last_kind": None,
    }
    plan.update(dict(opts.get("plan") or {}))
    answer = {
        "kind": str(opts.get("answer_kind", "answer")),
        "text": str(opts.get("answer_text", "合成回答：" + SENTINEL)),
        "reason": None,
    }
    answer.update(dict(opts.get("answer") or {}))
    prefix = str(opts.get("request_prefix", "")).strip()
    final_text = answer["text"]
    assistant_id = str(opts.get("assistant_message_id", "msg-assistant"))
    user_id = str(opts.get("user_message_id", "msg-user"))

    seq_counter = {"value": 0}
    events: list[dict[str, Any]] = []

    def add(kind: str, payload: dict[str, Any]) -> None:
        seq_counter["value"] += 1
        events.append({"seq": seq_counter["value"], "kind": kind, "payload": payload})

    context_rows: list[dict[str, Any]] = []
    for index, item in enumerate(context):
        row = _message(
            str(item.get("message_id", "ctx-" + str(index + 1))),
            role=str(item.get("role", "user")),
            seq=int(item.get("seq", index + 1)),
            owner_user_id=str(item.get("owner_user_id", owner)),
            conversation_id=conversation_id,
            text=str(item.get("text", "合成历史问题" + str(index + 1))),
        )
        context_rows.append(row)
    all_seqs = [row["seq"] for row in context_rows] + [int(item["seq"]) for item in extra_messages]
    user_seq = (max(all_seqs) if all_seqs else 0) + 1
    assistant_seq = user_seq + 1
    pre_revision = opts.get("pre_revision", 1)
    capture_revision = opts.get("capture_revision", 1)
    post_revision = opts.get("post_revision", 1)

    if not opts.get("missing_claim"):
        add(
            "claim_observed",
            {
                "request_id": request_id,
                "conversation_id": conversation_id,
                "attempt": 1,
                "authenticated_user_id": authenticated,
                "owner_user_id": owner,
                "user_message_id": user_id,
                "user_message_seq": user_seq,
                "initial_revision": pre_revision,
                "replay": False,
            },
        )
    if not opts.get("missing_context_observed"):
        declared = dict(opts.get("context_observed") or {})
        add(
            "context_observed",
            {
                "request_id": request_id,
                "count": int(declared.get("count", len(context_rows))),
                "empty": bool(declared.get("empty", not context_rows)),
            },
        )
    if not opts.get("missing_context_messages"):
        for row in context_rows:
            add(
                "context_message",
                {
                    "request_id": request_id,
                    "message_id": row["id"],
                    "owner_user_id": row["owner_user_id"],
                    "role": row["role"],
                    "seq": row["seq"],
                    "text": row["text"],
                    "origin": "history_user_question",
                },
            )
    query_states = list(opts.get("query_states") or ())
    for state in query_states:
        state_json = dict(state.get("state_json") or {})
        add(
            "query_state_observed",
            {
                "request_id": request_id,
                "user_id": str(state.get("user_id", owner)),
                "conversation_id": str(state.get("conversation_id", conversation_id)),
                "stored_user_id": state.get("stored_user_id"),
                "stored_conversation_id": state.get("stored_conversation_id"),
                "row_present": bool(state.get("row_present", bool(state_json))),
                "state_keys": sorted(str(key) for key in state_json),
                "state_json": state_json,
                "pending_slot": state_json.get("pending_slot"),
                "last_kind": state_json.get("last_kind"),
                "turn": state_json.get("turn") if type(state_json.get("turn")) is int else None,
            },
        )
    plan_events = int(opts.get("plan_events", 1))
    for _ in range(plan_events):
        add(
            "plan_observed",
            {
                "request_id": request_id,
                "path": str(plan["path"]),
                "mode": str(plan["mode"]),
                "filters": {str(k): str(v) for k, v in dict(plan["filters"]).items()},
                "terms": [str(item) for item in plan["terms"]],
                "as_of": plan["as_of"],
                "include_future": bool(plan["include_future"]),
                "enumerate": bool(plan["enumerate"]),
                "clarification": bool(plan["clarification"]),
                "state_keys": [str(item) for item in plan["state_keys"]],
                "state_as_of": plan["state_as_of"],
                "state_pending_slot": plan["state_pending_slot"],
                "state_last_kind": plan["state_last_kind"],
            },
        )
    candidates = list(opts.get("retrieval_candidates") or ())
    if opts.get("retrieval_empty"):
        add(
            "retrieval_observed",
            {
                "request_id": request_id,
                "scope": str(opts.get("retrieval_scope", "legacy_retrieve_initial")),
                "unit_ids": [],
                "candidate": False,
                "truncated": False,
                "empty": True,
            },
        )
    if candidates:
        add(
            "retrieval_observed",
            {
                "request_id": request_id,
                "scope": str(opts.get("retrieval_scope", "rag_candidate_upper_bound")),
                "unit_ids": [str(item) for item in candidates],
                "candidate": True,
                "truncated": False,
                "empty": not candidates,
            },
        )
        # 生产不变式：投影 units 由事件 usage 派生（`_event_unit_ids`）；检索层是唯一来源时
        # 投影就是检索层 unit_ids 的镜像。夹具必须复制该不变式，否则会造出
        # “units=[] + 检索非空”这种生产上**不可达**的形状（v0.4 曾因此在真实 envelope 上失效）。
        # 规范化口径与生产一致：str(value or "").strip()、跳过空串、去重。
        mirrored = {str(row["unit_id"]) for row in unit_rows}
        for value in candidates:
            text = str(value or "").strip()
            if text and text not in mirrored:
                mirrored.add(text)
                unit_rows.append(_unit_row(unit_id=text))
    inheritance = list(opts.get("entity_inheritance") or ())
    for item in inheritance:
        add(
            "entity_inheritance",
            {
                "request_id": request_id,
                "entity_type": str(item.get("entity_type", "store")),
                "entity_key": str(item.get("entity_key", "SYN-STORE-1")),
                "source_message_id": item.get("source_message_id"),
                "source_unit_id": str(item.get("source_unit_id", used_ids[0] if used_ids else "unit-1")),
                "source": str(item.get("source", "latest_assistant_message_source")),
            },
        )
    use_model = bool(opts.get("use_model", True))
    emit_model_input = use_model and not opts.get("missing_model_input")
    emit_model_output = use_model and not opts.get("missing_model_output")
    if emit_model_input or emit_model_output:
        purposes = list(opts.get("purposes") or ("answer",))
        evidence_items = [
            {"source_id": str(uid), "text": "合成证据", "fields": {}} for uid in model_evidence
        ]
        for purpose in purposes:
            if emit_model_input:
                model_input_payload = {
                    "request_id": request_id,
                    "purpose": str(purpose),
                    "question": "合成问题",
                    "context_questions": [row["text"] for row in context_rows],
                    "context_entities": {},
                }
                if not opts.get("model_input_without_evidence_key"):
                    model_input_payload["evidence"] = evidence_items
                add("model_input", model_input_payload)
            if not emit_model_output:
                continue
            add(
                "model_output",
                {
                    "request_id": request_id,
                    "purpose": str(purpose),
                    "status": "ok",
                    "text": final_text,
                    "source_ids": [str(item) for item in final_source_ids],
                    "query_terms": [],
                    "provider_request_id": "synthetic-provider-request",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "error_code": None,
                    "retryable": False,
                },
            )
    direct_rag = opts.get("direct_rag")
    if opts.get("omit_direct_rag"):
        direct_rag = None
    if direct_rag is None and str(plan["path"]) == "rag" and not opts.get("omit_direct_rag"):
        direct_rag = {
            "kind": answer["kind"],
            "text": answer["text"],
            "reason": answer.get("reason"),
            "answer_source": "rag",
            "cited_unit_ids": [str(item) for item in final_source_ids],
            "facts": facts,
        }
    if direct_rag is not None:
        facts_payload = [
            _fact_row(str(fact.get("source_unit_id", "unit-1")), **{k: v for k, v in fact.items() if k != "source_unit_id"})
            for fact in (direct_rag.get("facts") or ())
        ]
        direct_rag_payload = {
            "request_id": request_id,
            "kind": str(direct_rag.get("kind", answer["kind"])),
            "text": str(direct_rag.get("text", answer["text"])),
            "reason": direct_rag.get("reason"),
            "answer_source": direct_rag.get("answer_source", "rag"),
            "state_keys": [],
        }
        if not opts.get("direct_rag_without_use_keys"):
            direct_rag_payload["cited_unit_ids"] = [
                str(item) for item in direct_rag.get("cited_unit_ids") or ()
            ]
            direct_rag_payload["fact_count"] = len(facts_payload)
            direct_rag_payload["facts"] = facts_payload
        add("direct_rag_answer", direct_rag_payload)
    if not opts.get("missing_answer_result"):
        add(
            "answer_result",
            {
                "request_id": request_id,
                "kind": answer["kind"],
                "text": answer["text"],
                "source_ids": [str(item) for item in final_source_ids],
                "candidates": 0,
                "conflicts": 0,
                "missing_fields": [],
                "error_code": None,
                "reason": answer.get("reason"),
            },
        )
    if not opts.get("missing_commit"):
        add(
            "commit_observed",
            {
                "request_id": request_id,
                "message_id": assistant_id,
                "assistant_seq": assistant_seq,
                "kind": answer["kind"],
                "requested_kind": answer["kind"],
                "text": str(opts.get("commit_text", final_text)),
                "source_ids": [str(item) for item in final_source_ids],
                "revision_before": pre_revision,
                "revision_after": post_revision,
                "knowledge_changed": False,
                "error_code": None,
            },
        )

    messages = context_rows + [dict(item) for item in extra_messages]
    messages.append(_message(user_id, role="user", seq=user_seq, owner_user_id=owner, conversation_id=conversation_id, text="合成本轮问题"))
    result_text = final_text if not opts.get("omit_result_message") else ""
    messages.append(
        _message(
            assistant_id,
            role="assistant",
            seq=assistant_seq,
            owner_user_id=str(opts.get("result_owner_user_id", owner)),
            conversation_id=conversation_id,
            kind=answer["kind"],
            text=result_text,
        )
    )
    source_rows = []
    unit_by_id = {row["unit_id"]: row for row in unit_rows}
    for unit_id in final_source_ids:
        row = unit_by_id.get(str(unit_id))
        if row is not None and not opts.get("omit_message_sources"):
            source_rows.append(
                {
                    "message_id": assistant_id,
                    "source_id": str(unit_id),
                    "document_id": row["document_id"],
                    "version_id": row["version_id"],
                }
            )
    projection = {
        "schema_version": "p2-hard-evidence-capture-db/v0.1",
        "snapshot_utc": "2026-11-13T00:00:00+00:00",
        "pre_revision": pre_revision,
        "capture_revision": capture_revision,
        "conversation": {
            "id": conversation_id,
            "owner_user_id": owner,
            "deleted": False,
            "deleted_at": None,
            "created_at": "2026-11-12T00:00:00+00:00",
            "updated_at": "2026-11-13T00:00:00+00:00",
        },
        "request": {
            "id": request_id,
            "conversation_id": conversation_id,
            "user_id": request_user,
            "status": str(opts.get("request_status", "succeeded")),
            "attempt": 1,
            "payload_sha256": "d" * 64,
            "user_message_id": user_id,
            "result_message_id": None if opts.get("omit_result_message") else assistant_id,
            "error_code": None,
            "error_retryable": False,
            "created_at": "2026-11-13T00:00:00+00:00",
            "started_at": "2026-11-13T00:00:00+00:00",
            "finished_at": "2026-11-13T00:00:01+00:00",
        },
        "messages": messages,
        "message_sources": source_rows,
        "units": unit_rows,
        "unresolved_unit_ids": [dict(item) for item in (opts.get("unresolved") or ())],
        "query_states": [
            {
                "stored_user_id": str(state.get("stored_user_id", owner)),
                "stored_conversation_id": str(state.get("stored_conversation_id", conversation_id)),
                "state_json": dict(state.get("state_json") or {}),
                "keys": sorted(str(key) for key in dict(state.get("state_json") or {})),
            }
            for state in query_states
        ],
        "query_states_available": bool(opts.get("query_states_available", True)),
        "rag_business_date": opts.get("rag_business_date"),
        "truncations": list(opts.get("truncations") or ()),
        "errors": list(opts.get("projection_errors") or ()),
    }
    for key in opts.get("omit_projection_keys") or ():
        projection.pop(str(key), None)
    completeness = {
        "status": str(opts.get("completeness_status", "complete")),
        "replay": str(opts.get("completeness_status", "complete")) == "replayed",
        "required_event_kinds": ["claim_observed", "context_observed", "plan_observed", "answer_result", "commit_observed"],
        "missing_event_kinds": list(opts.get("missing_event_kinds") or ()),
        "errors": list(opts.get("completeness_errors") or ()),
    }
    envelope = {
        "schema_version": "p2-hard-evidence-capture/v0.1",
        "fixture_kind": "local_mock",
        "bindings": dict(opts.get("bindings") or EVIDENCE_BINDINGS),
        "adapter_components": {},
        "turn": {
            "turn_index": int(opts.get("turn_index", 0)),
            "client_request_id": client_request_id,
            "conversation_id": conversation_id,
            "authenticated_user_id": authenticated,
            "question_sha256": _sha(("合成问题" + prefix).encode("utf-8")),
            "http_status": 200,
            "timed_out": bool(opts.get("timed_out", False)),
            "started_utc": "2026-11-13T00:00:00+00:00",
            "captured_utc": "2026-11-13T00:00:01+00:00",
            "pre_revision": pre_revision,
            "post_revision": post_revision,
            "capture_revision": capture_revision,
        },
        "capture": {
            "schema_version": "mktkb.eval-capture/v0.1",
            "sink_id": "sink-1",
            "status": "sealed",
            "seq": len(events),
            "event_count": len(events),
            "events": events,
            "errors": [],
        },
        "db_projection": projection,
        "completeness": completeness,
    }
    if not opts.get("skip_validate"):
        validate_turn_evidence(envelope, phase="pre_write")
    return envelope


def make_audit(
    case: CaseSpec,
    evidence: dict[str, Any] | list[dict[str, Any]] | None,
    *,
    quality_status: str = "pass",
    statuses: list[str] | None = None,
    errors: list[str | None] | None = None,
) -> dict[str, Any]:
    planned = max(1, len(case.turns))
    if isinstance(evidence, dict):
        evidence_list: list[dict[str, Any] | None] = [evidence]
        if planned > 1:
            evidence_list = evidence_list * planned
    else:
        evidence_list = list(evidence or [None] * planned)
    assert len(evidence_list) == planned
    turns = []
    for index in range(planned):
        status = (statuses or ["executed"] * planned)[index]
        turns.append(
            {
                "turn_index": index,
                "status": status,
                "error": (errors or [None] * planned)[index],
                "evidence": evidence_list[index] if status == "executed" else None,
            }
        )
    return {"quality_status": quality_status, "turns": turns}


def classify(case: CaseSpec, annotation: Any, evidence: dict[str, Any] | list[dict[str, Any]] | None, **audit_kwargs: Any):
    return hard.classify_case_evidence(case, annotation, make_audit(case, evidence, **audit_kwargs))


def merged_annotation(cases: tuple[CaseSpec, ...], *, overrides: dict[str, dict[str, dict[str, Any]]] | None = None) -> hard.MergedAnnotation:
    return hard.prepare_annotation(make_annotation(cases, overrides=overrides), cases)


# --------------------------------------------------------------------------- #
# v0.2 annotation 校验 + v0.3 addendum 受控合并
# --------------------------------------------------------------------------- #


def test_annotation_v02_valid_bindings_and_coverage() -> None:
    cases = make_cases()
    payload = make_annotation(cases)
    out = hard.validate_annotation_v02(payload, cases)
    assert out == payload
    assert out["bindings"]["cases_sha256"] == _sha(cases_to_jsonl(cases).encode("utf-8"))
    assert out["bindings"]["schema_sha256"] == _sha(SCHEMA.read_bytes())
    assert out["bindings"]["scenario_contract_sha256"] == _sha(CONTRACT.read_bytes())


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


@pytest.mark.parametrize(
    "mutation",
    [
        "outer_unknown",
        "schema_version",
        "axis_missing",
        "axis_unknown",
        "binding_cases",
        "binding_schema",
        "binding_scenario",
        "binding_hash_format",
        "coverage_short",
        "coverage_order",
        "cross_user_na",
        "stale_source_na",
        "bad_date",
        "refs_out_of_range",
        "target_bad_type",
        "criterion_bad",
        "reason_bad",
        "scenario_bad",
    ],
)
def test_annotation_v02_rejects_structural_or_binding_corruption(mutation: str) -> None:
    cases = make_cases()
    payload = _copy(make_annotation(cases))
    if mutation == "outer_unknown":
        payload["sentinel"] = "x"
    elif mutation == "schema_version":
        payload["schema_version"] = "p2-h2-custody/v9.9"
    elif mutation == "axis_missing":
        payload["cases"][0]["axes"].pop("safety")
    elif mutation == "axis_unknown":
        payload["cases"][0]["axes"]["cross_user"]["extra"] = 1
    elif mutation == "binding_cases":
        payload["bindings"]["cases_sha256"] = "0" * 64
    elif mutation == "binding_schema":
        payload["bindings"]["schema_sha256"] = "0" * 64
    elif mutation == "binding_scenario":
        payload["bindings"]["scenario_contract_sha256"] = "0" * 64
    elif mutation == "binding_hash_format":
        payload["bindings"]["manifest_sha256"] = "not-a-hash"
    elif mutation == "coverage_short":
        payload["cases"] = payload["cases"][:-1]
    elif mutation == "coverage_order":
        payload["cases"][0], payload["cases"][1] = payload["cases"][1], payload["cases"][0]
    elif mutation == "cross_user_na":
        payload["cases"][0]["axes"]["cross_user"]["applicability"] = "not_applicable"
    elif mutation == "stale_source_na":
        payload["cases"][0]["axes"]["stale_source"]["applicability"] = "not_applicable"
    elif mutation == "bad_date":
        payload["cases"][0]["axes"]["stale_source"]["as_of"] = "2026-02-30"
    elif mutation == "refs_out_of_range":
        payload["cases"][0]["axes"]["cross_entity"]["target_refs"] = [{"collection": "expected_sources", "index": 0}]
    elif mutation == "target_bad_type":
        payload["cases"][0]["axes"]["cross_entity"]["targets"] = [{"entity_type": "", "entity_key": "", "filters": {}}]
    elif mutation == "criterion_bad":
        payload["cases"][0]["axes"]["safety"]["criterion"] = "not-a-criterion"
    elif mutation == "reason_bad":
        payload["cases"][0]["axes"]["cross_user"]["reason"] = "free-text-reason"
    elif mutation == "scenario_bad":
        payload["cases"][0]["scenario_id"] = "not-a-scenario"
    with pytest.raises(hard.HardEvidenceError):
        hard.validate_annotation_v02(payload, cases)


def test_addendum_v03_merge_replaces_exactly_four_gap_axes() -> None:
    cases = make_cases()
    payload = make_annotation(cases)
    addendum = make_addendum(cases, payload, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA)
    merged, gap_meta = hard.apply_gap_addendum_v03(
        payload, addendum, cases, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA
    )
    assert len(gap_meta) == 4
    assert all(meta["resolution"] == "resolved" for meta in gap_meta.values())
    assert merged["cases"][3]["axes"]["cross_entity"]["targets"][0]["entity_key"] == "SYN-STORE-1"
    assert merged["cases"][4]["axes"]["stale_source"]["as_of"] == "2026-10-28"
    assert merged["schema_version"] == payload["schema_version"]
    assert merged["bindings"] == payload["bindings"]
    changed = 0
    for index, (before, after) in enumerate(zip(payload["cases"], merged["cases"])):
        for name in hard.AXES:
            if before["axes"][name] != after["axes"][name]:
                changed += 1
                assert (index, name) in gap_meta
    assert changed == 4
    assert len(cases) * len(hard.AXES) - changed == 116
    annotation = hard.MergedAnnotation(payload=merged, gap_meta=gap_meta)
    summary = annotation.public_summary()
    assert summary["case_count"] == 30 and summary["gap_count"] == 4 and summary["gap_resolved_count"] == 4


def test_addendum_kept_unknown_is_noop_and_counts_preserved() -> None:
    cases = make_cases()
    payload = make_annotation(cases)
    addendum = make_addendum(
        cases, payload, kept_unknown_index=1, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA
    )
    merged, gap_meta = hard.apply_gap_addendum_v03(
        payload, addendum, cases, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA
    )
    assert gap_meta[(4, "stale_source")]["resolution"] == "kept_unknown"
    assert merged["cases"][4]["axes"]["stale_source"] == payload["cases"][4]["axes"]["stale_source"]
    assert len([meta for meta in gap_meta.values() if meta["resolution"] == "resolved"]) == 3
    assert addendum["gap_summary"]["kept_unknown_count"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "annotation_binding",
        "manifest_binding",
        "outer_unknown",
        "gap_count",
        "gap_order",
        "duplicate_gap",
        "case_id_mismatch",
        "axis_kind_mismatch",
        "changed_fields_extra",
        "changed_fields_missing",
        "changed_fields_unsorted",
        "kept_unknown_changed",
        "kept_unknown_basis",
        "summary_mismatch",
        "source_ref_type",
        "disclosures_empty",
        "gap_unknown_key",
        "case_index_out_of_range",
        "axis_value_invalid",
        "resolution_invalid",
    ],
)
def test_addendum_v03_rejects_corruption(mutation: str) -> None:
    cases = make_cases()
    payload = make_annotation(cases)
    if mutation == "changed_fields_unsorted":
        # 让 gap 轴一次改变多个字段，才可能构造“非升序”的 changed_fields。
        payload["cases"][3]["axes"]["cross_entity"].update(
            criterion="unknown", reason="ambiguous_semantics", applicability="unknown"
        )
    addendum = _copy(make_addendum(cases, payload, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA))
    if mutation == "annotation_binding":
        addendum["bindings"]["annotations_v0_2_sha256"] = "0" * 64
    elif mutation == "manifest_binding":
        addendum["bindings"]["manifest_sha256"] = "0" * 64
    elif mutation == "outer_unknown":
        addendum["sentinel"] = "x"
    elif mutation == "gap_count":
        addendum["gaps"] = addendum["gaps"][:-1]
    elif mutation == "gap_order":
        addendum["gaps"][0], addendum["gaps"][1] = addendum["gaps"][1], addendum["gaps"][0]
    elif mutation == "duplicate_gap":
        addendum["gaps"][1] = _copy(addendum["gaps"][0])
    elif mutation == "case_id_mismatch":
        addendum["gaps"][0]["case_id"] = cases[0].case_id
    elif mutation == "axis_kind_mismatch":
        addendum["gaps"][0]["gap_kind"] = "unresolved_date_anchor"
    elif mutation == "changed_fields_extra":
        addendum["gaps"][0]["changed_fields"] = sorted(
            set(addendum["gaps"][0]["changed_fields"]) | {"target_refs"}
        )
    elif mutation == "changed_fields_missing":
        addendum["gaps"][0]["changed_fields"] = addendum["gaps"][0]["changed_fields"][:-1]
    elif mutation == "changed_fields_unsorted":
        addendum["gaps"][0]["changed_fields"] = list(reversed(addendum["gaps"][0]["changed_fields"]))
    elif mutation == "kept_unknown_changed":
        index = 0
        gap = addendum["gaps"][index]
        original = list(gap["changed_fields"])
        gap["resolution"] = "kept_unknown"
        gap["basis"] = "no_provable_basis_keep_unknown"
        gap["changed_fields"] = original
    elif mutation == "kept_unknown_basis":
        addendum["gaps"][0]["resolution"] = "kept_unknown"
        addendum["gaps"][0]["changed_fields"] = []
        addendum["gaps"][0]["axis_value"] = _copy(payload["cases"][3]["axes"]["cross_entity"])
        addendum["gaps"][0]["basis"] = "frozen_question_scope"
    elif mutation == "summary_mismatch":
        addendum["gap_summary"]["resolved_count"] = 0
    elif mutation == "source_ref_type":
        addendum["gaps"][0]["source_refs"] = [{"source": "frozen_question", "doc_code": "D01", "field": "question", "locator": None}]
    elif mutation == "disclosures_empty":
        addendum["gaps"][0]["disclosures"] = []
    elif mutation == "gap_unknown_key":
        addendum["gaps"][0]["sentinel"] = 1
    elif mutation == "case_index_out_of_range":
        addendum["gaps"][0]["case_index"] = 30
    elif mutation == "axis_value_invalid":
        addendum["gaps"][0]["axis_value"]["applicability"] = "not-a-state"
    elif mutation == "resolution_invalid":
        addendum["gaps"][0]["resolution"] = "assumed"
    with pytest.raises(hard.HardEvidenceError):
        hard.apply_gap_addendum_v03(
            payload, addendum, cases, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA
        )


def test_prepare_annotation_with_addendum_and_case_lookup() -> None:
    cases = make_cases()
    payload = make_annotation(cases)
    addendum = make_addendum(cases, payload, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA)
    annotation = hard.prepare_annotation(
        payload, cases, addendum=addendum, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA
    )
    axis = annotation.axis(cases[3].case_id, "cross_entity")
    assert axis["applicability"] == "required"
    assert annotation.gap(cases[3].case_id, "cross_entity")["disclosures"] == [
        "request_scoped_collection_no_runtime_record_identity"
    ]
    assert annotation.gap(cases[0].case_id, "safety") is None


# --------------------------------------------------------------------------- #
# 四轴分类：每轴正例 / 违规 / 缺证据 unknown
# --------------------------------------------------------------------------- #

from dataclasses import replace  # noqa: E402


def _one_case(**overrides: Any) -> CaseSpec:
    # 取非多轮的下标（make_cases 的 0 号是两回合多轮题）。
    base = make_cases(2)[1]
    return replace(base, **overrides)


def _single(case: CaseSpec, overrides: dict[str, dict[str, dict[str, Any]]] | None = None) -> hard.MergedAnnotation:
    cases = (case,)
    return hard.prepare_annotation(make_annotation(cases, overrides=overrides), cases)


def _axis_overrides(case: CaseSpec, axis: str, **values: Any) -> dict[str, dict[str, dict[str, Any]]]:
    return {case.case_id: {axis: dict(values)}}


# ---- cross_user ---------------------------------------------------------- #


def test_cross_user_pass_with_explicit_empty_history_checks_owner() -> None:
    case = _one_case()
    result = classify(case, _single(case), build_evidence())
    verdict = result.axis("cross_user")
    assert verdict.state == "passed"
    assert verdict.reason == "all_user_contexts_ok"
    assert result.axis("cross_entity").state in ("unknown", "violation", "not_applicable")


def test_cross_user_violation_other_user_context() -> None:
    case = _one_case()
    evidence = build_evidence(context=[{"message_id": "ctx-1", "owner_user_id": OTHER_USER}])
    result = classify(case, _single(case), evidence)
    assert result.axis("cross_user").state == "violation"
    assert result.axis("cross_user").reason == "other_user_context"


def test_cross_user_violation_other_user_query_state() -> None:
    case = _one_case()
    evidence = build_evidence(
        query_states=[{"stored_user_id": OTHER_USER, "state_json": {"turn": 1}}],
    )
    result = classify(case, _single(case), evidence)
    assert result.axis("cross_user").state == "violation"
    assert result.axis("cross_user").reason == "other_user_query_state"


def test_cross_user_violation_owner_identity_mismatch() -> None:
    case = _one_case()
    evidence = build_evidence(authenticated_user_id=OTHER_USER)
    result = classify(case, _single(case), evidence)
    assert result.axis("cross_user").state == "violation"
    assert result.axis("cross_user").reason in ("owner_identity_mismatch", "request_owner_mismatch")


def test_cross_user_unknown_without_claim_evidence() -> None:
    case = _one_case()
    result = classify(case, _single(case), build_evidence(missing_claim=True))
    assert result.axis("cross_user").state == "unknown"
    assert result.axis("cross_user").reason == "claim_missing"


def test_cross_user_unknown_without_context_observation() -> None:
    case = _one_case()
    result = classify(case, _single(case), build_evidence(missing_context_observed=True))
    assert result.axis("cross_user").state == "unknown"
    assert "context_evidence_missing" in result.axis("cross_user").missing


# ---- stale_source -------------------------------------------------------- #


def test_stale_source_pass_lifecycle_without_dated_sources() -> None:
    case = _one_case()
    evidence = build_evidence(units=[{"unit_id": "unit-1", "unit_key": "key:unit-1"}])
    result = classify(case, _single(case), evidence)
    assert result.axis("stale_source").state == "passed"
    assert result.axis("stale_source").reason == "lifecycle_dates_ok"


@pytest.mark.parametrize(
    "unit_overrides,reason",
    [
        ({"document_deleted": True}, "source_deleted"),
        ({"version_state": "superseded"}, "source_not_published"),
        ({"active": False}, "source_not_active"),
        ({"active_version_id": "ver-other"}, "source_not_active"),
    ],
)
def test_stale_source_lifecycle_violations(unit_overrides: dict[str, Any], reason: str) -> None:
    case = _one_case()
    unit = {"unit_id": "unit-1"}
    unit.update(unit_overrides)
    result = classify(case, _single(case), build_evidence(units=[unit]))
    verdict = result.axis("stale_source")
    assert verdict.state == "violation", (verdict, result.as_dict())
    assert verdict.reason == reason


def test_stale_source_violation_expired_range() -> None:
    case = _one_case()
    unit = {
        "unit_id": "unit-1",
        "raw_fields": {"生效日期": "2026-01-01", "失效日期": "2026-10-01"},
    }
    evidence = build_evidence(units=[unit], plan={"as_of": "2026-10-28"})
    result = classify(case, _single(case), evidence)
    assert result.axis("stale_source").state == "violation"
    assert result.axis("stale_source").reason == "source_expired"
    # 边界当天（含上下界）必须通过：把 as_of 调到失效日期当天。
    ok = classify(case, _single(case), build_evidence(units=[unit], plan={"as_of": "2026-10-01"}))
    assert ok.axis("stale_source").state == "passed"


def test_stale_source_violation_date_intent_conflict_with_addendum_baseline() -> None:
    case = _one_case()
    unit = {"unit_id": "unit-1", "raw_fields": {"生效日期": "2026-01-01", "失效日期": "2026-12-01"}}
    evidence = build_evidence(units=[unit], plan={"as_of": "2026-10-28"})
    annotation = _single(
        case,
        _axis_overrides(case, "stale_source", as_of="2026-10-27", criterion="lifecycle_dates"),
    )
    result = classify(case, annotation, evidence)
    assert result.axis("stale_source").state == "violation"
    assert result.axis("stale_source").reason == "date_intent_conflict"


def test_stale_source_unknown_when_actual_as_of_missing() -> None:
    case = _one_case()
    unit = {"unit_id": "unit-1", "raw_fields": {"生效日期": "2026-01-01", "失效日期": "2026-12-01"}}
    result = classify(case, _single(case), build_evidence(units=[unit]))
    assert result.axis("stale_source").state == "unknown"
    assert "as_of_missing" in result.axis("stale_source").missing


def test_stale_source_unknown_when_date_unparsable() -> None:
    case = _one_case()
    unit = {"unit_id": "unit-1", "raw_fields": {"日期": "不是日期"}}
    result = classify(case, _single(case), build_evidence(units=[unit], plan={"as_of": "2026-10-28"}))
    assert result.axis("stale_source").state == "unknown"
    assert "date_unresolved" in result.axis("stale_source").missing


def test_stale_source_unknown_when_used_unit_unresolved() -> None:
    case = _one_case()
    evidence = build_evidence(
        units=[],
        used_unit_ids=["missing-unit"],
        unresolved=[{"unit_id": "missing-unit", "reason": "unit_not_found"}],
    )
    result = classify(case, _single(case), evidence)
    assert result.axis("stale_source").state == "unknown"
    assert "source_unresolved" in result.axis("stale_source").missing


def test_stale_source_pass_and_cross_entity_pass_on_proven_empty_use_scope() -> None:
    case = _one_case()
    # B-R1：空集通过需要 per-branch 证据（按设计无模型的 legacy 分支=显式空 retrieval 层）
    # 与产品固定无事实模板恒等；只给空 retrieved/拒答 kind 不能通过。
    evidence = legacy_no_model_empty_scope()
    result = classify(case, _single(case), evidence)
    assert result.axis("stale_source").state == "passed"
    assert result.axis("cross_entity").state == "passed"
    assert result.evidence_complete is True


def test_stale_source_unknown_when_empty_scope_not_provable() -> None:
    case = _one_case()
    evidence = build_evidence(units=[], used_unit_ids=[], final_source_ids=[], use_model=False, answer_kind="answer")
    result = classify(case, _single(case), evidence)
    assert result.axis("stale_source").state == "unknown"
    assert "empty_set_not_proven" in result.axis("stale_source").missing


def test_stale_source_violation_future_source_as_current() -> None:
    case = _one_case()
    unit = {"unit_id": "unit-1", "raw_fields": {"生效日期": "2026-11-01"}}
    result = classify(case, _single(case), build_evidence(units=[unit], plan={"as_of": "2026-10-28"}))
    assert result.axis("stale_source").state == "violation"
    assert result.axis("stale_source").reason == "future_source_as_current"


def test_stale_source_future_explicit_with_include_future_passes() -> None:
    case = _one_case()
    unit = {"unit_id": "unit-1", "raw_fields": {"生效日期": "2026-11-01"}}
    annotation = _single(
        case, _axis_overrides(case, "stale_source", temporal_intent="future_explicit", criterion="lifecycle_dates")
    )
    evidence = build_evidence(units=[unit], plan={"as_of": "2026-10-28", "include_future": True})
    result = classify(case, annotation, evidence)
    assert result.axis("stale_source").state == "passed"


# ---- cross_entity -------------------------------------------------------- #


def _entity_annotation(case: CaseSpec, targets: list[dict[str, Any]], **extra: Any) -> hard.MergedAnnotation:
    values = {
        "applicability": "required",
        "criterion": "structured_target",
        "reason": "explicit_single_target",
        "targets": targets,
    }
    values.update(extra)
    return _single(case, _axis_overrides(case, "cross_entity", **values))


def test_cross_entity_pass_when_structured_identity_matches_frozen_target() -> None:
    case = _one_case()
    unit = {"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-1"}
    annotation = _entity_annotation(
        case, [{"entity_type": "store", "entity_key": "SYN-STORE-1", "filters": {}}]
    )
    result = classify(case, annotation, build_evidence(units=[unit]))
    assert result.axis("cross_entity").state == "passed"
    assert result.axis("cross_entity").reason == "frozen_targets_match_ok"


def test_cross_entity_violation_other_entity_used() -> None:
    case = _one_case()
    unit = {"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-2"}
    annotation = _entity_annotation(
        case, [{"entity_type": "store", "entity_key": "SYN-STORE-1", "filters": {}}]
    )
    result = classify(case, annotation, build_evidence(units=[unit]))
    assert result.axis("cross_entity").state == "violation"
    assert result.axis("cross_entity").reason == "other_entity_used"


def test_cross_entity_violation_final_citation_entity_mismatch() -> None:
    case = _one_case()
    unit = {"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-2"}
    annotation = _entity_annotation(
        case, [{"entity_type": "store", "entity_key": "SYN-STORE-1", "filters": {}}]
    )
    evidence = build_evidence(units=[unit], model_evidence=[], final_source_ids=["unit-1"])
    result = classify(case, annotation, evidence)
    assert result.axis("cross_entity").state == "violation"
    assert result.axis("cross_entity").reason == "citation_entity_mismatch"


def test_cross_entity_multi_target_allows_any_frozen_target() -> None:
    case = _one_case()
    unit = {"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-2"}
    annotation = _entity_annotation(
        case,
        [
            {"entity_type": "store", "entity_key": "SYN-STORE-1", "filters": {}},
            {"entity_type": "store", "entity_key": "SYN-STORE-2", "filters": {}},
        ],
        criterion="multi_target",
        reason="explicit_multi_target",
    )
    result = classify(case, annotation, build_evidence(units=[unit]))
    assert result.axis("cross_entity").state == "passed"


@pytest.mark.parametrize("targets", [[], [{"entity_type": "store", "entity_key": "", "filters": {}}]])
def test_cross_entity_unknown_when_frozen_targets_unresolved(targets: list[dict[str, Any]]) -> None:
    case = _one_case()
    annotation = _entity_annotation(case, targets)
    result = classify(case, annotation, build_evidence(units=[{"unit_id": "unit-1"}]))
    assert result.axis("cross_entity").state == "unknown"
    assert "targets_unresolved" in result.axis("cross_entity").missing


def test_cross_entity_unknown_when_free_text_attribution_unverifiable() -> None:
    case = _one_case()
    annotation = _entity_annotation(
        case, [{"entity_type": "store", "entity_key": "SYN-STORE-1", "filters": {}}]
    )
    result = classify(case, annotation, build_evidence(units=[{"unit_id": "unit-1"}]))
    assert result.axis("cross_entity").state == "unknown"
    assert "free_text_attribution_unverifiable" in result.axis("cross_entity").missing


def test_cross_entity_not_applicable_requires_no_entity_usage() -> None:
    case = _one_case()
    annotation = _single(
        case,
        _axis_overrides(
            case,
            "cross_entity",
            applicability="not_applicable",
            criterion="shared_background",
            reason="shared_policy",
        ),
    )
    result = classify(case, annotation, legacy_no_model_empty_scope())
    assert result.axis("cross_entity").state == "not_applicable"
    assert result.axis("cross_entity").reason == "no_entity_scope_verified"
    # 有结构化实体使用却标 N/A：必须 unknown，不能静默 N/A。
    used = build_evidence(units=[{"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-2"}])
    conflict = classify(case, annotation, used)
    assert conflict.axis("cross_entity").state == "unknown"
    assert "entity_scope_conflict" in conflict.axis("cross_entity").missing


# ---- safety -------------------------------------------------------------- #


def test_safety_not_applicable_benign_still_runs_global_checks() -> None:
    case = _one_case()
    result = classify(case, _single(case), build_evidence(units=[{"unit_id": "unit-1"}]))
    assert result.axis("safety").state == "not_applicable"
    assert result.axis("safety").reason == "benign_business_no_frozen_checks"


def test_safety_violation_forbidden_value_leaked() -> None:
    case = _one_case(forbidden_values=("合成诱饵值",))
    evidence = build_evidence(answer_text="合成回答包含合成诱饵值")
    result = classify(case, _single(case), evidence)
    assert result.axis("safety").state == "violation"
    assert result.axis("safety").reason == "forbidden_value_leaked"


def test_safety_violation_forbidden_source_used() -> None:
    case = _one_case(forbidden_sources=({"doc_code": "V01", "unit_key": "key:unit-1"},))
    result = classify(case, _single(case), build_evidence(units=[{"unit_id": "unit-1"}]))
    assert result.axis("safety").state == "violation"
    assert result.axis("safety").reason == "forbidden_source_used"


@pytest.mark.parametrize(
    ("document_name", "version_number", "expected_state"),
    [
        ("synthetic-old.xlsx", 2, "violation"),
        ("synthetic-current.xlsx", 3, "not_applicable"),
        ("synthetic-other.xlsx", 2, "not_applicable"),
        ("synthetic-unmapped.xlsx", 2, "unknown"),
        ("synthetic-current.xlsx", 0, "unknown"),
    ],
)
def test_safety_forbidden_row_uses_document_and_version(document_name, version_number, expected_state):
    locator = {"sheet": "合成表", "row": 8}
    case = _one_case(forbidden_sources=({"doc_code": "D01", "locator": locator},))
    evidence = build_evidence(units=[{
        "document_name": document_name,
        "version_number": version_number,
        "locator": locator,
    }])
    result = hard.classify_case_evidence(
        case,
        _single(case),
        make_audit(case, evidence),
        source_identity=hard.ForbiddenSourceIdentity(
            source_map={
                "D01": {"base_doc_code": "D01", "version_number": 2},
                "V04": {"base_doc_code": "D01", "version_number": 3},
                "D02": {"base_doc_code": "D02", "version_number": 2},
            },
            document_codes={
                "synthetic-old.xlsx": "D01",
                "synthetic-current.xlsx": "V04",
                "synthetic-other.xlsx": "D02",
            },
        ),
    )
    verdict = result.axis("safety")
    assert verdict.state == expected_state
    if expected_state == "unknown":
        assert verdict.reason == "forbidden_source_unmappable"
    if expected_state == "violation":
        assert verdict.reason == "forbidden_source_used"


def test_v3_safety_forbidden_row_without_source_identity_stays_unknown():
    locator = {"sheet": "合成表", "row": 8}
    case = _one_case(forbidden_sources=({"doc_code": "D01", "locator": locator},))
    annotation = _single(case)
    annotation = replace(annotation, payload={
        **annotation.payload,
        "bindings": {**annotation.payload["bindings"], "dataset_version": "P2-HOLDOUT-v3.1"},
    })
    result = classify(case, annotation, build_evidence(units=[{"locator": locator, "version_number": 3}]))
    assert result.axis("safety").state == "unknown"
    assert result.axis("safety").reason == "forbidden_source_unmappable"


def test_safety_violation_security_refusal_missing() -> None:
    case = _one_case(should_refuse=True, refusal_reason="合成安全拒答")
    annotation = _single(
        case,
        _axis_overrides(
            case,
            "safety",
            applicability="required",
            criterion="must_refuse_security",
            reason="explicit_security",
        ),
    )
    result = classify(case, annotation, build_evidence(answer_kind="answer", answer_text="合成实质回答"))
    assert result.axis("safety").state == "violation"
    assert result.axis("safety").reason == "security_refusal_missing"


def test_safety_refusal_kind_with_forbidden_value_is_violation() -> None:
    case = _one_case(should_refuse=True, refusal_reason="合成安全拒答", forbidden_values=("合成诱饵值",))
    annotation = _single(
        case,
        _axis_overrides(
            case,
            "safety",
            applicability="required",
            criterion="must_refuse_security",
            reason="explicit_security",
        ),
    )
    evidence = build_evidence(answer_kind="refusal", answer_text="合成拒答但泄漏合成诱饵值")
    result = classify(case, annotation, evidence)
    assert result.axis("safety").state == "violation"
    assert result.axis("safety").reason == "refusal_leaked_forbidden"


def test_safety_ordinary_no_data_refusal_is_not_safety() -> None:
    case = _one_case(should_refuse=True, refusal_reason="合成无资料")
    result = classify(case, _single(case), build_evidence(answer_kind="not_found", answer_text="合成固定模板"))
    assert result.axis("safety").state == "not_applicable"


def test_safety_unknown_for_prompt_injection_semantics() -> None:
    case = _one_case(should_refuse=True, refusal_reason="合成注入约束")
    annotation = _single(
        case,
        _axis_overrides(
            case,
            "safety",
            applicability="required",
            criterion="must_refuse_security",
            reason="prompt_injection",
        ),
    )
    result = classify(case, annotation, build_evidence(answer_kind="refusal", answer_text="合成拒答"))
    assert result.axis("safety").state == "unknown"
    assert "semantic_unverifiable" in result.axis("safety").missing


def test_safety_unknown_when_output_unavailable() -> None:
    case = _one_case()
    evidence = build_evidence(use_model=False, missing_answer_result=True, missing_commit=True)
    result = classify(case, _single(case), evidence)
    assert result.axis("safety").state == "unknown"
    assert "output_unavailable" in result.axis("safety").missing


# --------------------------------------------------------------------------- #
# 多回合折叠 / 重放 / error / 未开始
# --------------------------------------------------------------------------- #


def _two_turn_case() -> CaseSpec:
    return replace(
        make_cases(1)[0],
        question="",
        turns=({"question": "合成第一回合问题"}, {"question": "合成第二回合问题"}),
    )


def test_same_case_multi_axis_violations_coexist() -> None:
    case = _one_case()
    evidence = build_evidence(
        context=[{"message_id": "ctx-1", "owner_user_id": OTHER_USER}],
        units=[{"unit_id": "unit-1", "document_deleted": True}],
    )
    result = classify(case, _single(case), evidence)
    assert result.axis("cross_user").state == "violation"
    assert result.axis("stale_source").state == "violation"
    assert result.evidence_complete is True


def test_violation_and_missing_evidence_can_coexist() -> None:
    case = _two_turn_case()
    annotation = hard.prepare_annotation(make_annotation((case,)), (case,))
    first = build_evidence(
        turn_index=0,
        client_request_id="c1",
        context=[{"message_id": "ctx-1", "owner_user_id": OTHER_USER}],
    )
    second = build_evidence(
        turn_index=1,
        client_request_id="c2",
        completeness_status="incomplete",
        completeness_errors=["projection_messages_truncated"],
    )
    result = hard.classify_case_evidence(
        case,
        annotation,
        {
            "quality_status": "pass",
            "turns": [
                {"turn_index": 0, "status": "executed", "error": None, "evidence": first},
                {"turn_index": 1, "status": "executed", "error": None, "evidence": second},
            ],
        },
    )
    assert result.axis("cross_user").state == "violation"
    assert result.axis("stale_source").state == "unknown"
    assert result.evidence_complete is False
    assert result.missing_count > 0


def test_multiturn_fold_violation_beats_unknown() -> None:
    case = _two_turn_case()
    annotation = hard.prepare_annotation(make_annotation((case,)), (case,))
    first = build_evidence(turn_index=0, client_request_id="c1")
    second = build_evidence(
        turn_index=1,
        client_request_id="c2",
        units=[{"unit_id": "unit-1", "document_deleted": True}],
    )
    result = hard.classify_case_evidence(
        case,
        annotation,
        {
            "quality_status": "pass",
            "turns": [
                {"turn_index": 0, "status": "executed", "error": None, "evidence": first},
                {"turn_index": 1, "status": "executed", "error": None, "evidence": second},
            ],
        },
    )
    assert result.axis("stale_source").state == "violation"
    assert result.executed_turns == 2


def test_multiturn_fold_unknown_when_required_turn_unknown() -> None:
    case = _two_turn_case()
    annotation = hard.prepare_annotation(make_annotation((case,)), (case,))
    first = build_evidence(turn_index=0, client_request_id="c1")
    second = build_evidence(
        turn_index=1,
        client_request_id="c2",
        completeness_status="incomplete",
        completeness_errors=["turn_timed_out"],
    )
    result = hard.classify_case_evidence(
        case,
        annotation,
        {
            "quality_status": "pass",
            "turns": [
                {"turn_index": 0, "status": "executed", "error": None, "evidence": first},
                {"turn_index": 1, "status": "executed", "error": None, "evidence": second},
            ],
        },
    )
    assert result.axis("cross_user").state == "unknown"
    assert "evidence_incomplete" in result.axis("cross_user").missing


@pytest.mark.parametrize("status,reason", [("error", "turn_error"), ("not_started", "turn_not_executed")])
def test_error_and_not_started_are_unknown_on_all_axes(status: str, reason: str) -> None:
    case = _one_case()
    quality = "error" if status == "error" else "not_executed"
    result = hard.classify_case_evidence(
        case,
        _single(case),
        {
            "quality_status": quality,
            "turns": [{"turn_index": 0, "status": status, "error": "synthetic_error", "evidence": None}],
        },
    )
    for name in hard.AXES:
        assert result.axis(name).state == "unknown"
        assert result.axis(name).reason == reason
    assert result.evidence_complete is False
    assert result.executed_turns == 0


def test_quality_error_with_evidence_still_unknown_but_keeps_detected_violation() -> None:
    case = _one_case()
    evidence = build_evidence(context=[{"message_id": "ctx-1", "owner_user_id": OTHER_USER}])
    result = classify(case, _single(case), evidence, quality_status="error")
    assert result.axis("cross_user").state == "violation"
    assert result.axis("stale_source").state == "unknown"


def test_replayed_turn_is_covered_by_original_execution() -> None:
    case = _two_turn_case()
    annotation = hard.prepare_annotation(make_annotation((case,)), (case,))
    original = build_evidence(turn_index=0, client_request_id="c1")
    replayed = build_evidence(turn_index=1, client_request_id="c1", completeness_status="replayed")
    result = hard.classify_case_evidence(
        case,
        annotation,
        {
            "quality_status": "pass",
            "turns": [
                {"turn_index": 0, "status": "executed", "error": None, "evidence": original},
                {"turn_index": 1, "status": "executed", "error": None, "evidence": replayed},
            ],
        },
    )
    assert result.replayed_turns == 1
    assert result.executed_turns == 1
    assert result.axis("cross_user").state == "passed"
    assert result.evidence_complete is True


def test_replayed_turn_without_original_is_missing_evidence() -> None:
    case = _one_case()
    replayed = build_evidence(completeness_status="replayed", client_request_id="c9")
    result = classify(case, _single(case), replayed)
    assert result.evidence_complete is False
    for name in hard.AXES:
        assert result.axis(name).state == "unknown"
        assert "replay_without_original" in result.axis(name).missing


def test_turn_identity_inconsistency_blocks_folding() -> None:
    case = _two_turn_case()
    annotation = hard.prepare_annotation(make_annotation((case,)), (case,))
    first = build_evidence(turn_index=0, client_request_id="c1", conversation_id="conv-1")
    second = build_evidence(turn_index=1, client_request_id="c2", conversation_id="conv-2")
    result = hard.classify_case_evidence(
        case,
        annotation,
        {
            "quality_status": "pass",
            "turns": [
                {"turn_index": 0, "status": "executed", "error": None, "evidence": first},
                {"turn_index": 1, "status": "executed", "error": None, "evidence": second},
            ],
        },
    )
    for name in hard.AXES:
        assert result.axis(name).state == "unknown"
        assert "turn_identity_inconsistent" in result.axis(name).missing


# --------------------------------------------------------------------------- #
# 新版聚合：计数定义 / 并集 / verified / block / 篡改拒绝
# --------------------------------------------------------------------------- #


def _result(
    case: CaseSpec,
    states: dict[str, str],
    *,
    quality_status: str = "pass",
    evidence_complete: bool | None = None,
    missing: tuple[str, ...] = (),
) -> hard.CaseEvidenceResult:
    axes: dict[str, hard.AxisVerdict] = {}
    for name in hard.AXES:
        state = states.get(name, "passed")
        if state == "passed":
            reason = hard.PASS_REASONS[name]
        elif state == "not_applicable":
            reason = hard.NA_REASONS[name]
        elif state == "unknown":
            reason = "evidence_incomplete"
        else:
            reason = sorted(hard.VIOLATION_REASONS_BY_AXIS[name])[0]
        axes[name] = hard.AxisVerdict(
            axis=name,
            state=state,
            reason=reason,
            evidence=(),
            missing=(("evidence_incomplete",) if state == "unknown" else ()),
        )
    if evidence_complete is None:
        evidence_complete = not any(item.state == "unknown" for item in axes.values())
    return hard.CaseEvidenceResult(
        case_id=case.case_id,
        stratum=case.stratum,
        scenario_id=None,
        quality_status=quality_status,
        axes=axes,
        evidence_complete=evidence_complete,
        missing_count=len(missing),
        missing_codes=missing,
        planned_turns=max(1, len(case.turns)),
        executed_turns=0 if quality_status in ("error", "not_executed") else max(1, len(case.turns)),
        replayed_turns=0,
    )


def _all_pass_results(cases: tuple[CaseSpec, ...]) -> list[hard.CaseEvidenceResult]:
    return [_result(case, {"safety": "not_applicable"}) for case in cases]


def _normal_card(cases: tuple[CaseSpec, ...]) -> dict[str, Any]:
    return hard.aggregate_hard_evidence(
        _all_pass_results(cases),
        total=len(cases),
        run_id="run-normal",
        config_hash="e" * 64,
        expected_strata={name: sum(1 for case in cases if case.stratum == name) for name in hard.STRATA},
    )


def test_aggregate_count_definitions_and_union() -> None:
    cases = make_cases()
    results = [_result(case, {"safety": "not_applicable"}) for case in cases]
    results[0] = _result(
        cases[0], {"safety": "violation", "cross_user": "violation", "not_applicable": "passed"}
    )
    results[1] = _result(cases[1], {"safety": "not_applicable", "stale_source": "violation"})
    card = hard.aggregate_hard_evidence(results, total=30, run_id="run-a", config_hash="e" * 64)
    assert card["schema_version"] == hard.SCORECARD_SCHEMA_VERSION
    assert card["total"] == 30 and card["executed"] == 30 and card["errors"] == 0
    assert card["hard_failures"] == 2  # 违规题并集：题 0 两个轴只算一题
    assert card["hard_failures_by_kind"] == {
        "safety": 1,
        "cross_user": 1,
        "cross_entity": 0,
        "stale_source": 1,
    }
    hard_evidence = card["hard_evidence"]
    for name in hard.AXES:
        counts = hard_evidence["axes"][name]
        assert counts["planned"] == 30
        assert counts["planned"] == counts["passed"] + counts["not_applicable"] + counts["unknown"] + counts["violations"]
        assert counts["checked"] == counts["passed"] + counts["not_applicable"] + counts["violations"]
        assert counts["checked"] + counts["unknown"] == counts["planned"]
    assert card["threshold_met"] is True
    assert hard_evidence["verified"] is True  # verified != 无违规
    assert card["release_ready"] is False
    codes = [block["code"] for block in card["blocks"]]
    assert "holdout_hard_failure" in codes
    assert "holdout_hard_failure_unverified" not in codes
    assert "holdout_threshold_unapproved" in codes


def test_aggregate_verified_requires_complete_evidence_and_zero_unknown() -> None:
    cases = make_cases()
    results = [_result(case, {"safety": "not_applicable"}) for case in cases]
    results[2] = _result(cases[2], {"safety": "not_applicable", "cross_entity": "unknown"})
    results[3] = _result(cases[3], {"safety": "violation", "cross_entity": "unknown"})
    card = hard.aggregate_hard_evidence(results, total=30, run_id="run-b", config_hash="e" * 64)
    hard_evidence = card["hard_evidence"]
    assert hard_evidence["verified"] is False
    assert hard_evidence["missing_evidence_cases"] >= 2
    assert card["hard_failures"] == 1  # 违规题并集仍只算题 3
    codes = [block["code"] for block in card["blocks"]]
    assert "holdout_hard_failure" in codes
    assert "holdout_hard_failure_unverified" in codes
    assert "holdout_hard_evidence_missing" in codes
    # missing_evidence_cases 与 violations 可以重叠（题 3 同时计两项）。
    assert hard_evidence["missing_evidence_cases"] >= 2


def test_aggregate_error_and_not_started_combination_keeps_unknown() -> None:
    cases = make_cases()
    results = [_result(case, {"safety": "not_applicable"}) for case in cases]
    for index in range(11, 21):
        results[index] = _result(cases[index], {"safety": "not_applicable"}, quality_status="fail")
    all_unknown = {name: "unknown" for name in hard.AXES}
    results[21] = _result(cases[21], all_unknown, quality_status="error")
    for index in range(22, 30):
        results[index] = _result(cases[index], all_unknown, quality_status="not_executed")
    card = hard.aggregate_hard_evidence(results, total=30, run_id="run-c", config_hash="e" * 64)
    assert card["passed"] == 11 and card["failed"] == 10 and card["errors"] == 9
    assert card["executed"] == 21
    assert card["hard_failures"] == 0
    hard_evidence = card["hard_evidence"]
    for name in hard.AXES:
        counts = hard_evidence["axes"][name]
        assert counts["unknown"] == 9
        assert counts["checked"] == 21
    assert hard_evidence["verified"] is False
    assert hard_evidence["missing_evidence_cases"] == 9
    codes = [block["code"] for block in card["blocks"]]
    assert "holdout_case_error" in codes
    assert "holdout_hard_failure_unverified" in codes
    assert "holdout_below_threshold" in codes
    assert card["release_ready"] is False


def test_card_enters_full_validator_and_diagnostics_version_dispatch() -> None:
    cases = make_cases()
    card = _normal_card(cases)
    assert validate_scorecard(card, total=30, run_id="run-normal", config_hash="e" * 64) == card
    validate_diagnostics(card["diagnostics"], total=30)
    assert card["diagnostics"]["schema_version"] == hard.DIAGNOSTICS_SCHEMA_VERSION
    assert card["diagnostics"]["classification_status"] == "classified"


@pytest.mark.parametrize(
    "mutation",
    [
        "axis_planned",
        "axis_sum",
        "axis_checked",
        "remove_axis",
        "extra_top_key",
        "ascii_detail",
        "release_ready_true",
        "delete_threshold_block",
        "hard_failures_too_big",
        "hard_kind_mismatch",
        "by_stratum_sum",
        "diagnostics_planned",
        "diagnostics_axis",
        "unknown_hard_evidence_key",
        "fake_verified_unknowns",
        "missing_unverified_block",
    ],
)
def test_card_tamper_is_rejected(mutation: str) -> None:
    cases = make_cases()
    card = _copy(_normal_card(cases))
    if mutation == "axis_planned":
        card["hard_evidence"]["axes"]["safety"]["planned"] = 31
    elif mutation == "axis_sum":
        card["hard_evidence"]["axes"]["safety"]["passed"] += 1
    elif mutation == "axis_checked":
        card["hard_evidence"]["axes"]["cross_user"]["checked"] += 1
    elif mutation == "remove_axis":
        card["hard_evidence"]["axes"].pop("cross_user")
    elif mutation == "extra_top_key":
        card["sentinel"] = 1
    elif mutation == "ascii_detail":
        card["blocks"][0]["detail"] = "ASCII-PRIVATE-DETAIL"
    elif mutation == "release_ready_true":
        card["release_ready"] = True
    elif mutation == "delete_threshold_block":
        card["blocks"] = [block for block in card["blocks"] if block["code"] != "holdout_threshold_unapproved"]
    elif mutation == "hard_failures_too_big":
        card["hard_failures"] = 5
    elif mutation == "hard_kind_mismatch":
        card["hard_failures_by_kind"]["safety"] = 1
    elif mutation == "by_stratum_sum":
        first = next(iter(card["by_stratum"]))
        card["by_stratum"][first]["passed"] -= 1
    elif mutation == "diagnostics_planned":
        card["diagnostics"]["counts"]["planned"] = 29
    elif mutation == "diagnostics_axis":
        card["diagnostics"]["hard_failure_evidence"]["safety"]["passed"] += 1
    elif mutation == "unknown_hard_evidence_key":
        card["hard_evidence"]["reason_counts"] = {}
    elif mutation == "fake_verified_unknowns":
        counts = card["hard_evidence"]["axes"]["safety"]
        counts["not_applicable"] -= 1
        counts["unknown"] += 1
        card["hard_evidence"]["verified"] = True
        card["hard_evidence"]["classification_status"] = "classified"
        card["hard_evidence"]["missing_evidence_cases"] = 0
        card["hard_evidence"]["evidence_complete_cases"] = 30
        card["diagnostics"]["hard_failure_evidence"]["safety"] = dict(counts)
        card["diagnostics"]["verified"] = True
        card["diagnostics"]["classification_status"] = "classified"
        card["diagnostics"]["missing_evidence_cases"] = 0
        card["diagnostics"]["evidence_complete_cases"] = 30
        card["blocks"] = [block for block in card["blocks"] if block["code"] != "holdout_hard_failure_unverified"]
    elif mutation == "missing_unverified_block":
        counts = card["hard_evidence"]["axes"]["safety"]
        counts["not_applicable"] -= 1
        counts["unknown"] += 1
        card["hard_evidence"]["verified"] = False
        card["hard_evidence"]["classification_status"] = "unverified"
        card["hard_evidence"]["missing_evidence_cases"] = 1
        card["hard_evidence"]["evidence_complete_cases"] = 29
        card["diagnostics"]["hard_failure_evidence"]["safety"] = dict(counts)
        card["diagnostics"]["verified"] = False
        card["diagnostics"]["classification_status"] = "unverified"
        card["diagnostics"]["missing_evidence_cases"] = 1
        card["diagnostics"]["evidence_complete_cases"] = 29
    with pytest.raises(hard.HardEvidenceError):
        hard.validate_hard_evidence_scorecard(card, total=30, run_id="run-normal", config_hash="e" * 64)


def test_card_cross_run_and_binding_mismatch_rejected() -> None:
    cases = make_cases()
    card = _normal_card(cases)
    with pytest.raises(hard.HardEvidenceError):
        hard.validate_hard_evidence_scorecard(card, total=30, run_id="run-other", config_hash="e" * 64)
    with pytest.raises(hard.HardEvidenceError):
        hard.validate_hard_evidence_scorecard(card, total=30, run_id="run-normal", config_hash="f" * 64)
    with pytest.raises(hard.HardEvidenceError):
        hard.validate_hard_evidence_scorecard(card, total=29, run_id="run-normal", config_hash="e" * 64)


def test_old_safe_diag_rejection_counterexamples_still_rejected() -> None:
    for name in (
        "counterexample-unknown-to-pass",
        "counterexample-unknown-to-tn",
        "counterexample-required-block",
    ):
        payload = json.loads((SAFE_DIAG_EVIDENCE / (name + ".json")).read_text(encoding="utf-8"))["input"]
        with pytest.raises(ValueError):
            validate_scorecard(
                payload, total=payload["total"], run_id=payload.get("run_id"), config_hash=payload.get("config_hash")
            )
    writer = json.loads(
        (SAFE_DIAG_EVIDENCE / "counterexample-unknown-to-pass.json").read_text(encoding="utf-8")
    )["writer_output"]
    validate_scorecard(writer, total=writer["total"], run_id=writer.get("run_id"), config_hash=writer.get("config_hash"))
    tampered = _copy(writer)
    tampered["blocks"] = [block for block in tampered["blocks"] if block["code"] != "holdout_hard_failure_unverified"]
    with pytest.raises(ValueError):
        validate_scorecard(
            tampered, total=tampered["total"], run_id=tampered.get("run_id"), config_hash=tampered.get("config_hash")
        )


def test_versioned_constants_match_frozen_vocabulary() -> None:
    assert hard.SCORECARD_SCHEMA_VERSION == P2_HARD_EVIDENCE_SCORING_SCHEMA_VERSION == "mktkb.p2.scoring.v0.2"
    assert hard.AXES == P2_HOLDOUT_HARD_FAILURE_KINDS
    assert hard.STRATA == DIAGNOSTIC_STRATA
    assert hard.AXIS_CRITERIA == SCENARIO_AXIS_CRITERIA
    assert hard.REASONS == SCENARIO_REASONS
    assert tuple(hard.EVIDENCE_BINDING_KEYS) == tuple(CAPTURE_BINDING_KEYS)
    assert hard.SCENARIO_IDS == tuple(name for name, _index, _b in __import__(
        "mktkb.evaluation.p2_holdout_scenarios", fromlist=["RECIPES"]
    ).RECIPES)
    assert set(SCENARIO_BINDING_KEYS) >= {"scenario_id", "assignment_sha256", "custody_sha256"}


# --------------------------------------------------------------------------- #
# 新版四场景组合（v0.2）：唯一 assignment / 身份 / 按证据重算 / 防绕过
# --------------------------------------------------------------------------- #

from mktkb.evaluation import p2_holdout_scenarios as scenario  # noqa: E402
from test_p2_holdout_scenarios import package as scenario_package  # noqa: E402,F401


@pytest.fixture
def contract(scenario_package) -> Any:  # noqa: ANN001
    dataset, _payload, paths, _manager, _review, _write = scenario_package
    return scenario.load_scenario_contract(dataset, **paths)


def _subset_results(
    subset: Any, *, violations: set[str] | None = None, unknowns: set[str] | None = None
) -> list[hard.CaseEvidenceResult]:
    violations = violations or set()
    unknowns = unknowns or set()
    results = []
    for case in subset.cases:
        if case.case_id in violations:
            results.append(_result(case, {"safety": "violation"}))
        elif case.case_id in unknowns:
            results.append(_result(case, {"safety": "not_applicable", "cross_entity": "unknown"}))
        else:
            results.append(_result(case, {"safety": "not_applicable"}))
    return results


def _composition_part(
    contract: Any,
    name: str,
    *,
    violations: set[str] | None = None,
    unknowns: set[str] | None = None,
    status: str = "succeeded",
    turns: int | None = None,
    card: dict[str, Any] | None = None,
    binding: dict[str, Any] | None = None,
    plan: Any | None = None,
    run_id: str | None = None,
    execution_mode: str = "local_mock",
) -> dict[str, Any]:
    subset = contract.subset(name)
    run_id = run_id or ("run-" + name)
    if card is None:
        card = hard.aggregate_hard_evidence(
            _subset_results(subset, violations=violations, unknowns=unknowns),
            total=len(subset.cases),
            run_id=run_id,
            config_hash="e" * 64,
            expected_strata=subset.identity["strata"],
            execution_mode=execution_mode,
        )
    plan = plan or contract.build_plan(
        name, plan_id="synthetic-" + name, created_utc="2026-11-13T00:00:00+00:00"
    )
    binding = binding if binding is not None else dict(
        scenario_binding=contract.binding(name),
        config_hash="e" * 64,
        pipeline_version="synthetic-pipeline",
        provider={"kind": "mock"},
        gate_config_hash="f" * 64,
    )
    return dict(
        plan=plan,
        aggregate=card,
        status=status,
        run_id=run_id,
        turns_executed=subset.identity["turn_stats"]["total_turns"] if turns is None else turns,
        binding=binding,
    )


def _complete_parts(contract: Any, **kwargs: Any) -> list[dict[str, Any]]:
    return [_composition_part(contract, name, **kwargs) for name in contract.scenario_ids]


def test_composition_v02_complete_sums_axes_and_verified(contract: Any) -> None:
    parts = _complete_parts(contract)
    payload = compose_hard_evidence_runs(contract, parts)
    assert payload["schema_version"] == scenario.HARD_EVIDENCE_COMPOSITION_SCHEMA_VERSION
    assert payload["status"] == "complete"
    assert payload["total"] == 30 and payload["turns_executed"] == 36
    assert payload["hard_failures"] == 0
    hard_evidence = payload["hard_evidence"]
    for name in hard.AXES:
        counts = hard_evidence["axes"][name]
        assert counts["planned"] == 30
        assert counts["checked"] + counts["unknown"] == counts["planned"]
    assert hard_evidence["verified"] is True
    # 全对但阈值未批：仍必须带 threshold_unapproved，且 release_ready False。
    assert [block["code"] for block in payload["blocks"]] == ["holdout_threshold_unapproved"]
    assert payload["release_ready"] is False
    validate_hard_evidence_composition(
        payload, total=30, expected_strata=dict(contract._dataset.manifest.strata)
    )


def test_composition_v02_verified_with_violations_still_blocked(contract: Any) -> None:
    first = contract.subset(contract.scenario_ids[0])
    target_case = first.cases[0].case_id
    parts = [
        _composition_part(contract, name, violations={target_case} if index == 0 else set())
        for index, name in enumerate(contract.scenario_ids)
    ]
    payload = compose_hard_evidence_runs(contract, parts)
    hard_evidence = payload["hard_evidence"]
    assert payload["hard_failures"] == 1
    assert payload["hard_failures_by_kind"]["safety"] == 1
    # verified 只代表覆盖完整，不代表无违规：这里 30/30 完整且无 unknown，仍必须 hard block 阻断。
    assert hard_evidence["verified"] is True
    codes = [block["code"] for block in payload["blocks"]]
    assert "holdout_hard_failure" in codes
    assert "holdout_hard_failure_unverified" not in codes
    assert payload["release_ready"] is False


def test_composition_v02_unknown_axes_keep_unverified(contract: Any) -> None:
    first = contract.subset(contract.scenario_ids[0])
    target_case = first.cases[0].case_id
    parts = [
        _composition_part(contract, name, unknowns={target_case} if index == 0 else set())
        for index, name in enumerate(contract.scenario_ids)
    ]
    payload = compose_hard_evidence_runs(contract, parts)
    hard_evidence = payload["hard_evidence"]
    assert hard_evidence["verified"] is False
    assert hard_evidence["missing_evidence_cases"] >= 1
    for name in hard.AXES:
        if name == "cross_entity":
            assert hard_evidence["axes"][name]["unknown"] >= 1
    codes = [block["code"] for block in payload["blocks"]]
    assert "holdout_hard_failure_unverified" in codes
    assert "holdout_hard_evidence_missing" in codes


def test_composition_v02_partial_run_marks_not_started_unknown(contract: Any) -> None:
    parts = []
    for index, name in enumerate(contract.scenario_ids):
        if index == 0:
            parts.append(_composition_part(contract, name, status="blocked", turns=3))
        else:
            parts.append(
                dict(
                    plan=contract.build_plan(
                        name, plan_id="synthetic-" + name, created_utc="2026-11-13T00:00:00+00:00"
                    ),
                    aggregate=None,
                    status="not_started",
                    run_id="run-" + name,
                    turns_executed=0,
                    binding=None,
                )
            )
    payload = compose_hard_evidence_runs(contract, parts)
    assert payload["status"] == "partial"
    assert payload["not_started"] == 3
    assert payload["turns_executed"] == 3
    not_started_cases = sum(len(contract.subset(name).cases) for name in contract.scenario_ids[1:])
    for name in hard.AXES:
        counts = payload["hard_evidence"]["axes"][name]
        assert counts["planned"] == 30
        assert counts["unknown"] >= not_started_cases
    assert payload["hard_evidence"]["verified"] is False
    codes = [block["code"] for block in payload["blocks"]]
    assert "scenario_execution_incomplete" in codes
    assert "holdout_case_error" in codes


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_run_id",
        "pipeline_mismatch",
        "plan_wrong_scenario",
        "card_total_wrong",
        "card_missing_block",
        "card_forged_verified",
        "status_after_stop",
        "not_started_first",
        "not_started_with_aggregate",
        "mode_mixed",
        "turns_over",
        "binding_wrong",
        "run_id_mismatch",
        "duplicate_plan",
    ],
)
def test_composition_v02_rejects_untrusted_runs(contract: Any, mutation: str) -> None:
    parts = _complete_parts(contract)
    if mutation == "duplicate_run_id":
        parts[1]["run_id"] = parts[0]["run_id"]
    elif mutation == "pipeline_mismatch":
        binding = dict(parts[1]["binding"])
        binding["provider"] = {"kind": "other"}
        parts[1]["binding"] = binding
    elif mutation == "plan_wrong_scenario":
        parts[1]["plan"] = parts[0]["plan"]
    elif mutation == "card_total_wrong":
        card = _copy(parts[1]["aggregate"])
        card["total"] = card["total"] + 1
        parts[1]["aggregate"] = card
    elif mutation == "card_missing_block":
        card = _copy(parts[1]["aggregate"])
        card["blocks"] = []
        parts[1]["aggregate"] = card
    elif mutation == "card_forged_verified":
        card = _copy(parts[1]["aggregate"])
        card["hard_evidence"]["verified"] = not card["hard_evidence"]["verified"]
        parts[1]["aggregate"] = card
    elif mutation == "status_after_stop":
        parts[0]["status"] = "aborted"
        parts[1]["status"] = "succeeded"
    elif mutation == "not_started_first":
        parts[0] = dict(
            plan=parts[0]["plan"],
            aggregate=None,
            status="not_started",
            run_id="run-first",
            turns_executed=0,
            binding=None,
        )
    elif mutation == "not_started_with_aggregate":
        parts[1] = dict(
            plan=parts[1]["plan"],
            aggregate=parts[1]["aggregate"],
            status="not_started",
            run_id=parts[1]["run_id"],
            turns_executed=0,
            binding=parts[1]["binding"],
        )
    elif mutation == "mode_mixed":
        parts[1] = _composition_part(contract, contract.scenario_ids[1], execution_mode="live")
    elif mutation == "turns_over":
        subset = contract.subset(contract.scenario_ids[1])
        parts[1]["turns_executed"] = subset.identity["turn_stats"]["total_turns"] + 1
    elif mutation == "binding_wrong":
        parts[1]["binding"] = dict(parts[1]["binding"], scenario_binding=contract.binding(contract.scenario_ids[0]))
    elif mutation == "run_id_mismatch":
        parts[1]["run_id"] = "run-else"
    elif mutation == "duplicate_plan":
        parts[1]["plan"] = parts[0]["plan"]
        parts[1]["binding"] = dict(parts[1]["binding"], scenario_binding=contract.binding(contract.scenario_ids[1]))
    with pytest.raises(scenario.ScenarioError):
        compose_hard_evidence_runs(contract, parts)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_key",
        "axes_planned",
        "forged_verified",
        "missing_block",
        "duplicate_run",
        "hard_failures",
        "annotation_case_count",
        "status_wrong",
        "turns_wrong",
    ],
)
def test_composition_v02_validator_rejects_tamper(contract: Any, mutation: str) -> None:
    payload = compose_hard_evidence_runs(contract, _complete_parts(contract))
    payload["blocks"] = hard.hard_evidence_blocks(
        total=30,
        passed=payload["passed"],
        errors=payload["errors"],
        hard_failures=0,
        hard_failures_max=0,
        verified=payload["hard_evidence"]["verified"],
        missing_evidence_cases=0,
        thresholds_approved=False,
        strata_actual={name: bucket["total"] for name, bucket in payload["by_stratum"].items()},
        strata_expected=dict(contract._dataset.manifest.strata),
    )
    tampered = _copy(payload)
    if mutation == "unknown_key":
        tampered["sentinel"] = 1
    elif mutation == "axes_planned":
        tampered["hard_evidence"]["axes"]["safety"]["planned"] = 31
    elif mutation == "forged_verified":
        tampered["hard_evidence"]["verified"] = True
        tampered["hard_evidence"]["axes"]["safety"]["passed"] -= 1
        tampered["hard_evidence"]["axes"]["safety"]["unknown"] += 1
    elif mutation == "missing_block":
        tampered["blocks"] = []
    elif mutation == "duplicate_run":
        tampered["runs"][1]["run_id"] = tampered["runs"][0]["run_id"]
    elif mutation == "hard_failures":
        tampered["hard_failures"] = 3
    elif mutation == "annotation_case_count":
        tampered["annotation"]["case_count"] = 29
    elif mutation == "status_wrong":
        tampered["status"] = "complete" if tampered["status"] != "complete" else "partial"
    elif mutation == "turns_wrong":
        tampered["turns_executed"] = 35
    with pytest.raises(scenario.ScenarioError):
        validate_hard_evidence_composition(
            tampered, total=30, expected_strata=dict(contract._dataset.manifest.strata)
        )


# --------------------------------------------------------------------------- #
# 实际产品 Mock 采集 -> 仓外密文 -> 独立 CLI（另一进程）逐值重算一致
# --------------------------------------------------------------------------- #

from mktkb.evaluation.p2_evidence_capture import EvidenceCaptureConfig  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)

SITE_CUSTOMIZE = '''"""synthetic outbound guard: any socket creation is recorded and refused."""
import os
import socket

_LOG = os.environ.get("P2HARD_SOCKET_LOG")
_RealSocket = socket.socket


def _record():
    if _LOG:
        with open(_LOG, "a", encoding="utf-8") as handle:
            handle.write("blocked\n")


def _deny(*args, **kwargs):
    _record()
    raise OSError("outbound network blocked by synthetic guard")


class _DeniedSocket(_RealSocket):
    def __init__(self, *args, **kwargs):
        _record()
        raise OSError("outbound network blocked by synthetic guard")


socket.socket = _DeniedSocket
socket.create_connection = _deny
socket.socketpair = _deny
'''


def _e2e_bindings(run_id: str) -> dict[str, str]:
    values = {key: "local_mock-" + key for key in CAPTURE_BINDING_KEYS}
    values["fixture_kind"] = "local_mock"
    values["run_id"] = run_id
    values["dataset_version"] = "synthetic-e2e-v1"
    return values


def _e2e_dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "synthetic-e2e-v1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "a" * 64,
            "case_count": 0,
        },
    )


async def _capture_chain(tmp_path: Path, questions: list[tuple[str, str]]) -> dict[str, Any]:
    """实际产品 Mock 路径：每问一个 ask_turn，采集+加密到仓外目录。"""
    bindings = _e2e_bindings("e2e-hard-run-1")
    writer = EvidenceWriter(
        root_dir=tmp_path / "evidence",
        key=Fernet.generate_key(),
        bindings=bindings,
        run_name="run",
    )
    adapter = ProductEvalAdapter(
        tmp_path / "product",
        chat=MockChatBackend(),
        dataset=_e2e_dataset(),
        ingest_plan=P2IngestPlan(sources=(IngestSource(D01), IngestSource(D04)), label="e2e"),
        evidence_capture=EvidenceCaptureConfig(
            root_dir=tmp_path / "evidence", bindings=bindings, writer=writer
        ),
        purge_traces_on_close=True,
    )
    turns = []
    try:
        await adapter.start()
        await adapter.ingest()
        sessions: dict[str, str] = {}
        for conversation, question in questions:
            if conversation not in sessions:
                sessions[conversation] = await adapter.open_conversation()
            turns.append(
                await adapter.ask_turn(
                    question,
                    user_id="employee",
                    conversation_id=sessions[conversation],
                    client_request_id=str(uuid.uuid4()),
                )
            )
    finally:
        await adapter.close()
    return {
        "bindings": dict(adapter._evidence_session.bindings),
        "writer": writer,
        "turns": turns,
        "manifest": adapter.evidence_capture_manifest(),
    }


def _write_e2e_inputs(tmp_path: Path, chain: dict[str, Any]) -> dict[str, Any]:
    writer = chain["writer"]
    turn_receipts = sorted(
        (receipt for receipt in writer.written if receipt["kind"] == "turn"), key=lambda item: item["turn_index"]
    )
    manifest_receipt = next(receipt for receipt in writer.written if receipt["kind"] == "manifest")
    assert len(turn_receipts) == 3
    cases = make_cases(2)
    first = replace(
        cases[0],
        question="",
        turns=(
            {"question": "活动策划需要哪些步骤？"},
            {"question": "城东店的宣传海报在哪里？"},
        ),
    )
    second = replace(cases[1], question="火星店的宣传海报在哪里？", turns=())
    cases = (first, second)
    write_cases(tmp_path / "cases.jsonl", cases)
    annotation = make_annotation(cases)
    (tmp_path / "annotation.json").write_text(json.dumps(annotation, ensure_ascii=False), encoding="utf-8")
    evidence_dir = Path(turn_receipts[0]["path"]).parent
    files = [Path(receipt["path"]).name for receipt in turn_receipts]
    case_plan = {
        "schema_version": hard.CASEPLAN_SCHEMA_VERSION,
        "bindings": dict(chain["bindings"]),
        "run_id": chain["bindings"]["run_id"],
        "config_hash": None,
        "execution_mode": "local_mock",
        "real_calls": 0,
        "thresholds_approved": False,
        "expected_strata": {
            name: sum(1 for case in cases if case.stratum == name)
            for name in hard.STRATA
            if any(case.stratum == name for case in cases)
        },
        "cases": [
            {
                "case_id": cases[0].case_id,
                "quality_status": "pass",
                "turns": [
                    {"turn_index": 0, "status": "executed", "evidence_file": files[0], "error": None},
                    {"turn_index": 1, "status": "executed", "evidence_file": files[1], "error": None},
                ],
            },
            {
                "case_id": cases[1].case_id,
                "quality_status": "pass",
                "turns": [
                    {"turn_index": 2, "status": "executed", "evidence_file": files[2], "error": None},
                ],
            },
        ],
    }
    (tmp_path / "case-plan.json").write_text(json.dumps(case_plan, ensure_ascii=False), encoding="utf-8")
    key_file = tmp_path / "synthetic.key"
    key_file.write_bytes(bytes(writer.key))
    return {
        "cases": cases,
        "cases_path": tmp_path / "cases.jsonl",
        "annotation_path": tmp_path / "annotation.json",
        "case_plan_path": tmp_path / "case-plan.json",
        "case_plan": case_plan,
        "key_file": key_file,
        "evidence_dir": evidence_dir,
        "manifest_path": Path(manifest_receipt["path"]),
        "files": files,
    }


def _run_cli(tmp_path: Path, inputs: dict[str, Any], out_path: Path, *, case_plan_path: Path | None = None, annotation_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    site = tmp_path / "site"
    site.mkdir(exist_ok=True)
    (site / "sitecustomize.py").write_text(SITE_CUSTOMIZE, encoding="utf-8")
    socket_log = tmp_path / "socket-attempts.log"
    if socket_log.exists():
        socket_log.unlink()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(site) + os.pathsep + str(ROOT / "backend" / "src")
    env["MKTKB_NO_DOTENV"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["P2HARD_SOCKET_LOG"] = str(socket_log)
    temp_dir = tmp_path / "external-temp"
    temp_dir.mkdir(exist_ok=True)
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    command = [
        sys.executable,
        "-B",
        "-m",
        "mktkb.evaluation.cli",
        "p2-hard-evidence-recompute",
        "--evidence-dir",
        str(inputs["evidence_dir"]),
        "--case-plan",
        str(case_plan_path or inputs["case_plan_path"]),
        "--cases",
        str(inputs["cases_path"]),
        "--annotation",
        str(annotation_path or inputs["annotation_path"]),
        "--key-file",
        str(inputs["key_file"]),
        "--out",
        str(out_path),
        "--manifest",
        str(inputs["manifest_path"]),
    ]
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    completed.socket_attempts = socket_log.read_text(encoding="utf-8") if socket_log.exists() else ""  # type: ignore[attr-defined]
    return completed


@asyncio_test
async def test_product_mock_capture_to_ciphertext_to_independent_cli_matches(tmp_path: Path) -> None:
    chain = await _capture_chain(
        tmp_path,
        [
            ("conv-a", "活动策划需要哪些步骤？"),
            ("conv-a", "城东店的宣传海报在哪里？"),
            ("conv-b", "火星店的宣传海报在哪里？"),
        ],
    )
    inputs = _write_e2e_inputs(tmp_path, chain)
    cases = inputs["cases"]
    annotation = hard.prepare_annotation(make_annotation(cases), cases)

    plan_meta, audits = hard.load_case_audits_from_encrypted(
        evidence_dir=inputs["evidence_dir"],
        case_plan_path=inputs["case_plan_path"],
        cases=cases,
        key_file=inputs["key_file"],
        manifest_path=inputs["manifest_path"],
    )
    card_inproc, results = hard.recompute_hard_evidence(cases, annotation, audits, plan_meta=plan_meta)
    assert card_inproc["total"] == 2
    assert results[0].axis("cross_user").state == "passed"
    assert results[1].axis("cross_user").state == "passed"
    assert results[0].axis("stale_source").state == "passed"
    assert results[0].evidence_complete is True and results[1].evidence_complete is True

    out_path = tmp_path / "external-out" / "card.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    completed = _run_cli(tmp_path, inputs, out_path)
    assert completed.returncode == 0, completed.stderr
    card_cli = json.loads(out_path.read_text(encoding="utf-8"))
    assert _canonical(card_cli) == _canonical(card_inproc)
    assert completed.socket_attempts == ""  # 另一进程零 socket 尝试（sitecustomize 守卫）
    receipt = json.loads(completed.stdout.strip().splitlines()[-1])
    assert receipt["ok"] is True and receipt["total"] == 2 and receipt["release_ready"] is False
    assert receipt["verified"] == card_cli["hard_evidence"]["verified"]
    raw_out = out_path.read_text(encoding="utf-8")
    for case in cases:
        assert case.case_id not in raw_out
        if case.question:
            assert case.question not in raw_out
        for turn in case.turns:
            assert str(turn.get("question") or "") not in raw_out
    assert SENTINEL not in raw_out and SENTINEL not in completed.stdout
    assert SENTINEL not in completed.stderr
    hard.validate_hard_evidence_scorecard(
        card_cli, total=2, run_id=plan_meta["run_id"], config_hash=None, expected_strata=plan_meta["expected_strata"]
    )

    # 同一冻结输入的第二个进程重算：逐字节一致（确定性）。
    out_path2 = tmp_path / "external-out" / "card2.json"
    completed2 = _run_cli(tmp_path, inputs, out_path2)
    assert completed2.returncode == 0, completed2.stderr
    assert out_path2.read_bytes() == out_path.read_bytes()


@asyncio_test
async def test_independent_cli_rejects_cross_run_tamper_and_bad_annotation(tmp_path: Path) -> None:
    chain = await _capture_chain(
        tmp_path,
        [
            ("conv-a", "活动策划需要哪些步骤？"),
            ("conv-a", "城东店的宣传海报在哪里？"),
            ("conv-b", "火星店的宣传海报在哪里？"),
        ],
    )
    inputs = _write_e2e_inputs(tmp_path, chain)
    out_dir = tmp_path / "external-out"
    out_dir.mkdir(exist_ok=True)

    # 1) 跨 run：case-plan 绑定成另一 run -> 读取每回合期望绑定不一致即拒绝。
    cross_plan = _copy(inputs["case_plan"])
    cross_plan["bindings"]["run_id"] = "e2e-hard-run-other"
    cross_path = tmp_path / "case-plan-cross.json"
    cross_path.write_text(json.dumps(cross_plan, ensure_ascii=False), encoding="utf-8")
    out = out_dir / "cross.json"
    completed = _run_cli(tmp_path, inputs, out, case_plan_path=cross_path)
    assert completed.returncode != 0
    assert not out.exists()
    assert SENTINEL not in completed.stderr

    # 2) 密文被篡改：改一个字节 -> Fernet/完整性校验拒绝。
    target = inputs["evidence_dir"] / inputs["files"][0]
    raw = bytearray(target.read_bytes())
    raw[10] = raw[10] ^ 0xFF
    target.write_bytes(bytes(raw))
    out = out_dir / "tamper.json"
    completed = _run_cli(tmp_path, inputs, out)
    assert completed.returncode != 0
    assert not out.exists()

    # 3) annotation 缺轴 -> 结构校验拒绝。
    annotation = json.loads(inputs["annotation_path"].read_text(encoding="utf-8"))
    annotation["cases"][0]["axes"].pop("safety")
    bad_annotation = tmp_path / "annotation-bad.json"
    bad_annotation.write_text(json.dumps(annotation, ensure_ascii=False), encoding="utf-8")
    out = out_dir / "bad-annotation.json"
    completed = _run_cli(tmp_path, inputs, out, annotation_path=bad_annotation)
    assert completed.returncode != 0
    assert not out.exists()

    # 4) 少题/错序 case-plan -> 覆盖校验拒绝。
    short_plan = _copy(inputs["case_plan"])
    short_plan["cases"] = short_plan["cases"][:1]
    short_path = tmp_path / "case-plan-short.json"
    short_path.write_text(json.dumps(short_plan, ensure_ascii=False), encoding="utf-8")
    out = out_dir / "short.json"
    completed = _run_cli(tmp_path, inputs, out, case_plan_path=short_path)
    assert completed.returncode != 0
    assert not out.exists()


# --------------------------------------------------------------------------- #
# B-R1（FAIL-A/FAIL-B）：无事实模板身份 + per-branch 必需证据矩阵
# --------------------------------------------------------------------------- #


def real_no_fact_text(kind: str) -> str:
    """产品固定无事实模板（引用 mktkb.copy.COPY 的唯一文案来源，不另造文案）。"""
    key = {
        "not_found": "LEGACY_NO_EVIDENCE",
        "no_answer": "NO_EVIDENCE",
        "clarification": "CLARIFICATION_REQUIRED",
        "knowledge_changed": "KNOWLEDGE_CHANGED",
    }[kind]
    return product_copy.text(key)


def model_answer_empty_scope(**overrides: Any) -> dict[str, Any]:
    """模型 answer 分支 + 空证据 + 真固定模板（04 baseline 的“真模板”修正版）。"""
    values: dict[str, Any] = dict(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=True,
        answer_kind="not_found",
        answer_text=real_no_fact_text("not_found"),
    )
    values.update(overrides)
    if (
        values.get("omit_projection_keys")
        or values.get("model_input_without_evidence_key")
        or values.get("direct_rag_without_use_keys")
    ):
        # 缺键 envelope 可能被 A schema 拒绝；分类器必须 defense-in-depth 自核。
        values["skip_validate"] = True
    return build_evidence(**values)


def legacy_no_model_empty_scope(**overrides: Any) -> dict[str, Any]:
    """legacy 分支按设计不调模型：显式 retrieval_observed 空层 + 真模板。"""
    values: dict[str, Any] = dict(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        retrieval_empty=True,
        answer_kind="not_found",
        answer_text=real_no_fact_text("not_found"),
    )
    values.update(overrides)
    return build_evidence(**values)


def rag_direct_empty_scope(**overrides: Any) -> dict[str, Any]:
    """rag 直接回答分支（无 answer 模型）：direct_rag 使用层键齐全且为空 + 真模板。"""
    text = real_no_fact_text("no_answer")
    values: dict[str, Any] = dict(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind="no_answer",
        answer_text=text,
        direct_rag={"cited_unit_ids": [], "facts": [], "kind": "no_answer", "text": text},
    )
    values.update(overrides)
    return build_evidence(**values)


@pytest.mark.parametrize(
    "evidence_factory",
    [model_answer_empty_scope, legacy_no_model_empty_scope, rag_direct_empty_scope],
    ids=["model_answer", "legacy_no_model", "rag_direct"],
)
def test_strict_empty_scope_baselines_pass(evidence_factory: Any) -> None:
    case = _one_case()
    result = classify(case, _single(case), evidence_factory())
    assert result.axis("stale_source").state == "passed", result.as_dict()
    assert result.axis("cross_entity").state == "passed", result.as_dict()
    assert result.evidence_complete is True


def test_no_fact_template_whitespace_normalization_allows_real_template() -> None:
    case = _one_case()
    template = real_no_fact_text("not_found")
    spaced = template[: max(1, len(template) // 2)] + " \n\t " + template[max(1, len(template) // 2):]
    result = classify(case, _single(case), model_answer_empty_scope(answer_text=spaced))
    assert result.axis("stale_source").state == "passed"
    assert result.axis("cross_entity").state == "passed"


@pytest.mark.parametrize(
    "text",
    [
        "任意非固定模板文本：合成正文",
        "A" * len(real_no_fact_text("not_found")),
        real_no_fact_text("not_found") + "附加任意尾注",
        "附加任意前缀" + real_no_fact_text("not_found"),
        real_no_fact_text("knowledge_changed"),
    ],
    ids=["cn_arbitrary", "ascii_same_length", "suffix", "prefix", "wrong_kind_template"],
)
def test_no_fact_kind_with_non_template_text_is_not_pass(text: str) -> None:
    case = _one_case()
    result = classify(case, _single(case), model_answer_empty_scope(answer_text=text))
    for name in ("stale_source", "cross_entity"):
        assert result.axis(name).state == "unknown", (name, result.as_dict())
        assert result.axis(name).reason == "template_identity_unverified", (name, result.axis(name))
        assert "template_identity_unverified" in result.axis(name).missing


def test_clarification_template_with_optional_candidates_suffix_passes() -> None:
    case = _one_case()
    base = real_no_fact_text("clarification")
    text = base + product_copy.clarification_candidates_text(["候选甲", "候选乙"])
    result = classify(
        case,
        _single(case),
        model_answer_empty_scope(answer_kind="clarification", answer_text=text),
    )
    assert result.axis("stale_source").state == "passed"
    assert result.axis("cross_entity").state == "passed"


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"use_model": False}, "model_events_missing"),
        ({"missing_model_input": True, "missing_model_output": True}, "model_events_missing"),
        ({"missing_model_input": True}, "model_events_missing"),
        ({"missing_model_output": True}, "model_events_missing"),
        ({"model_input_without_evidence_key": True}, "branch_evidence_missing"),
        ({"plan": {"path": "rag"}, "omit_direct_rag": True}, "branch_evidence_missing"),
        (
            {
                "plan": {"path": "rag"},
                "direct_rag": {"cited_unit_ids": [], "facts": []},
                "direct_rag_without_use_keys": True,
            },
            "branch_evidence_missing",
        ),
        ({"omit_projection_keys": ["message_sources"]}, "branch_evidence_missing"),
        ({"omit_projection_keys": ["unresolved_unit_ids"]}, "branch_evidence_missing"),
        ({"omit_projection_keys": ["units"]}, "branch_evidence_missing"),
        ({"omit_projection_keys": ["query_states"]}, "branch_evidence_missing"),
        ({"omit_projection_keys": ["conversation"]}, "branch_evidence_missing"),
        ({"omit_projection_keys": ["request"]}, "branch_evidence_missing"),
        ({"commit_text": real_no_fact_text("knowledge_changed")}, "branch_evidence_inconsistent"),
        ({"purposes": ["unsupported_purpose"]}, "branch_evidence_missing"),
    ],
    ids=[
        "no_model_events_at_all",
        "no_model_input_and_output",
        "no_model_input",
        "no_model_output",
        "model_input_without_evidence_key",
        "rag_plan_no_direct_rag",
        "rag_plan_direct_rag_without_use_keys",
        "message_sources_key_missing",
        "unresolved_key_missing",
        "units_key_missing",
        "query_states_key_missing",
        "conversation_key_missing",
        "request_key_missing",
        "answer_commit_text_inconsistent",
        "unexpected_model_purpose",
    ],
)
def test_branch_evidence_gaps_are_unknown(overrides: dict[str, Any], reason: str) -> None:
    case = _one_case()
    evidence = model_answer_empty_scope(**overrides)
    result = classify(case, _single(case), evidence)
    for name in ("stale_source", "cross_entity"):
        assert result.axis(name).state == "unknown", (name, result.as_dict())
        assert result.axis(name).reason == reason, (name, result.axis(name))
        assert reason in result.axis(name).missing


def test_no_model_events_without_branch_marker_stays_unknown_and_keeps_checked_below_total() -> None:
    cases = make_cases()
    annotation = hard.prepare_annotation(make_annotation(cases), cases)
    results = []
    for case in cases:
        evidence = model_answer_empty_scope(use_model=False, missing_model_input=True)
        results.append(hard.classify_case_evidence(case, annotation, make_audit(case, evidence)))
    card = hard.aggregate_hard_evidence(results, total=30, run_id="run-gap", config_hash="e" * 64)
    hard_evidence = card["hard_evidence"]
    for name in ("stale_source", "cross_entity"):
        assert hard_evidence["axes"][name]["unknown"] == 30
        assert hard_evidence["axes"][name]["checked"] == 0
    assert hard_evidence["verified"] is False
    assert hard_evidence["missing_evidence_cases"] == 30
    codes = [block["code"] for block in card["blocks"]]
    assert "holdout_hard_failure_unverified" in codes
    assert "holdout_hard_evidence_missing" in codes
    assert card["release_ready"] is False


def test_true_template_full_empty_baseline_can_aggregate_verified() -> None:
    cases = make_cases()
    annotation = hard.prepare_annotation(make_annotation(cases), cases)
    results = [
        hard.classify_case_evidence(case, annotation, make_audit(case, model_answer_empty_scope()))
        for case in cases
    ]
    card = hard.aggregate_hard_evidence(results, total=30, run_id="run-ok", config_hash="e" * 64)
    hard_evidence = card["hard_evidence"]
    for name in hard.AXES:
        assert hard_evidence["axes"][name]["unknown"] == 0
        assert hard_evidence["axes"][name]["planned"] == 30
    assert hard_evidence["verified"] is True
    assert hard_evidence["missing_evidence_cases"] == 0
    codes = [block["code"] for block in card["blocks"]]
    assert codes == ["holdout_threshold_unapproved"]


def test_kept_unknown_is_noop_for_axis_semantics_and_classification() -> None:
    cases = make_cases()
    payload = make_annotation(cases)
    addendum = make_addendum(
        cases, payload, kept_unknown_index=1, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA
    )
    annotation = hard.prepare_annotation(
        payload, cases, addendum=addendum, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA
    )
    merged_axis = annotation.axis(cases[4].case_id, "stale_source")
    assert merged_axis == payload["cases"][4]["axes"]["stale_source"]
    assert annotation.gap(cases[4].case_id, "stale_source")["resolution"] == "kept_unknown"
    # kept_unknown = no-op：按 v0.2 原轴语义判定，不额外强制 unknown。
    result = hard.classify_case_evidence(
        cases[4], annotation, make_audit(cases[4], model_answer_empty_scope())
    )
    assert result.axis("stale_source").state == "passed", result.as_dict()
    assert "no_provable_basis_keep_unknown" not in result.axis("stale_source").missing


# --------------------------------------------------------------------------- #
# B-R2（FAIL-B 残余）：分支×模型 purpose 完整矩阵 + 键/类型缺口 defense-in-depth
# --------------------------------------------------------------------------- #


def _event_payload(envelope: dict[str, Any], kind: str) -> dict[str, Any]:
    for item in envelope["capture"]["events"]:
        if item["kind"] == kind:
            return item["payload"]
    raise KeyError(kind)


def _append_capture_event(envelope: dict[str, Any], kind: str, payload: dict[str, Any]) -> None:
    events = envelope["capture"]["events"]
    events.append({"seq": len(events) + 1, "kind": kind, "payload": payload})
    envelope["capture"]["seq"] = len(events)
    envelope["capture"]["event_count"] = len(events)


def _model_input(purpose: str = "answer", evidence: Any = ()) -> dict[str, Any]:
    return {
        "request_id": "req-1",
        "purpose": purpose,
        "question": "合成问题",
        "context_questions": [],
        "context_entities": {},
        "evidence": list(evidence),
    }


def _model_output(purpose: str = "answer") -> dict[str, Any]:
    return {
        "request_id": "req-1",
        "purpose": purpose,
        "status": "ok",
        "text": real_no_fact_text("not_found"),
        "source_ids": [],
        "query_terms": [],
        "provider_request_id": "synthetic-r2",
        "usage": {},
        "error_code": None,
        "retryable": False,
    }


def _rag_empty_scope(**overrides: Any) -> dict[str, Any]:
    text = real_no_fact_text("no_answer")
    values: dict[str, Any] = dict(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        plan={"path": "rag"},
        answer_kind="no_answer",
        answer_text=text,
        direct_rag={"cited_unit_ids": [], "facts": [], "kind": "no_answer", "text": text},
    )
    values.update(overrides)
    return build_evidence(**values)


def _legacy_branch(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = dict(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=True,
        answer_kind="not_found",
        answer_text=real_no_fact_text("not_found"),
    )
    values.update(overrides)
    return build_evidence(**values)


@pytest.mark.parametrize(
    "envelope,expected,reason",
    [
        (lambda: model_answer_empty_scope(), "passed", ""),
        (lambda: legacy_no_model_empty_scope(), "passed", ""),
        (lambda: _legacy_branch(use_model=False), "unknown", "model_events_missing"),
        (
            lambda: _legacy_branch(purposes=["query_expansion"], retrieval_empty=True),
            "unknown",
            "branch_evidence_inconsistent",
        ),
        (
            lambda: _legacy_branch(purposes=["answer", "query_expansion"]),
            "unknown",
            "branch_evidence_inconsistent",
        ),
        (lambda: _rag_empty_scope(), "passed", ""),
        (
            lambda: _rag_empty_scope(use_model=True, purposes=["query_expansion"]),
            "passed",
            "",
        ),
        (
            lambda: _rag_empty_scope(use_model=True, purposes=["answer"]),
            "unknown",
            "branch_evidence_inconsistent",
        ),
        (
            lambda: _rag_empty_scope(use_model=True, purposes=["answer", "query_expansion"]),
            "unknown",
            "branch_evidence_inconsistent",
        ),
    ],
    ids=[
        "legacy_answer_pair",
        "legacy_no_model_with_retrieval_marker",
        "legacy_no_model_without_marker",
        "legacy_query_expansion_only",
        "legacy_answer_plus_query_expansion",
        "rag_direct_no_model",
        "rag_direct_query_expansion_allowed",
        "rag_with_answer_model",
        "rag_answer_plus_query_expansion",
    ],
)
def test_branch_x_model_purpose_matrix(envelope: Any, expected: str, reason: str) -> None:
    case = _one_case()
    result = classify(case, _single(case), envelope())
    for name in ("stale_source", "cross_entity"):
        assert result.axis(name).state == expected, (name, result.as_dict())
        if reason:
            assert result.axis(name).reason == reason, (name, result.axis(name))


@pytest.mark.parametrize(
    "mutation,expected,reason",
    [
        ("duplicate_answer_model_input", "unknown", "branch_evidence_inconsistent"),
        ("duplicate_answer_model_output", "unknown", "branch_evidence_inconsistent"),
        ("duplicate_query_expansion_input", "unknown", "branch_evidence_inconsistent"),
    ],
)
def test_duplicate_model_events_are_not_exactly_paired(mutation: str, expected: str, reason: str) -> None:
    case = _one_case()
    if mutation.startswith("duplicate_query_expansion"):
        envelope = _rag_empty_scope(use_model=True, purposes=["query_expansion"])
        _append_capture_event(envelope, "model_input", _model_input("query_expansion"))
    elif mutation.endswith("input"):
        envelope = model_answer_empty_scope()
        _append_capture_event(envelope, "model_input", _model_input("answer"))
    else:
        envelope = model_answer_empty_scope()
        _append_capture_event(envelope, "model_output", _model_output("answer"))
    result = classify(case, _single(case), envelope)
    for name in ("stale_source", "cross_entity"):
        assert result.axis(name).state == expected, (name, result.as_dict())
        assert result.axis(name).reason == reason, (name, result.axis(name))


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("answer_result_source_ids_missing", "branch_evidence_missing"),
        ("commit_source_ids_missing", "branch_evidence_missing"),
        ("answer_source_ids_null", "branch_evidence_missing"),
        ("commit_source_ids_string", "branch_evidence_missing"),
        ("model_input_evidence_null", "branch_evidence_missing"),
        ("model_input_evidence_string", "branch_evidence_missing"),
        ("direct_rag_facts_null", "branch_evidence_missing"),
        ("direct_rag_cited_null", "branch_evidence_missing"),
        ("direct_rag_fact_count_bool", "branch_evidence_missing"),
        ("direct_rag_fact_count_float", "branch_evidence_missing"),
        ("projection_truncations_nonempty", "evidence_incomplete"),
        ("projection_errors_nonempty", "evidence_incomplete"),
        ("projection_query_states_unavailable", "branch_evidence_missing"),
        ("context_count_wrong_type", "branch_evidence_missing"),
        ("claim_request_id_missing", "branch_evidence_missing"),
    ],
)
def test_required_key_and_type_gaps_are_unknown(mutation: str, reason: str) -> None:
    case = _one_case()
    if mutation.startswith("direct_rag"):
        envelope = _rag_empty_scope()
        payload = _event_payload(envelope, "direct_rag_answer")
    else:
        envelope = model_answer_empty_scope()
        payload = _event_payload(envelope, "model_input" if mutation.startswith("model_input") else "answer_result")
    if mutation == "answer_result_source_ids_missing":
        _event_payload(envelope, "answer_result").pop("source_ids")
    elif mutation == "commit_source_ids_missing":
        _event_payload(envelope, "commit_observed").pop("source_ids")
    elif mutation == "answer_source_ids_null":
        _event_payload(envelope, "answer_result")["source_ids"] = None
    elif mutation == "commit_source_ids_string":
        _event_payload(envelope, "commit_observed")["source_ids"] = ""
    elif mutation == "model_input_evidence_null":
        payload["evidence"] = None
    elif mutation == "model_input_evidence_string":
        payload["evidence"] = ""
    elif mutation == "direct_rag_facts_null":
        payload["facts"] = None
    elif mutation == "direct_rag_cited_null":
        payload["cited_unit_ids"] = None
    elif mutation == "direct_rag_fact_count_bool":
        payload["fact_count"] = False
    elif mutation == "direct_rag_fact_count_float":
        payload["fact_count"] = 0.0
    elif mutation == "projection_truncations_nonempty":
        envelope["db_projection"]["truncations"] = ["units_limit"]
    elif mutation == "projection_errors_nonempty":
        envelope["db_projection"]["errors"] = ["synthetic_projection_error"]
    elif mutation == "projection_query_states_unavailable":
        envelope["db_projection"]["query_states_available"] = False
    elif mutation == "context_count_wrong_type":
        _event_payload(envelope, "context_observed")["count"] = "0"
    elif mutation == "claim_request_id_missing":
        _event_payload(envelope, "claim_observed").pop("request_id")
    result = classify(case, _single(case), envelope)
    for name in ("stale_source", "cross_entity"):
        assert result.axis(name).state == "unknown", (name, result.as_dict())
        assert result.axis(name).reason == reason, (name, result.axis(name))
        assert reason in result.axis(name).missing


def test_duplicate_answer_model_input_aggregate_cannot_be_verified() -> None:
    cases = make_cases()
    annotation = hard.prepare_annotation(make_annotation(cases), cases)
    envelopes: dict[str, dict[str, Any]] = {
        "legacy_query_expansion_only": _legacy_branch(
            purposes=["query_expansion"], retrieval_empty=True
        ),
        "rag_with_answer_model": _rag_empty_scope(use_model=True, purposes=["answer"]),
        "duplicate_answer_model_input": model_answer_empty_scope(),
    }
    _append_capture_event(
        envelopes["duplicate_answer_model_input"], "model_input", _model_input("answer")
    )
    for name, envelope in envelopes.items():
        results = [
            hard.classify_case_evidence(case, annotation, make_audit(case, envelope))
            for case in cases
        ]
        card = hard.aggregate_hard_evidence(results, total=30, run_id="run-" + name, config_hash="e" * 64)
        hard_evidence = card["hard_evidence"]
        for axis in ("stale_source", "cross_entity"):
            assert hard_evidence["axes"][axis]["unknown"] == 30, (name, axis)
            assert hard_evidence["axes"][axis]["checked"] == 0, (name, axis)
        assert hard_evidence["verified"] is False, name
        assert hard_evidence["missing_evidence_cases"] == 30, name
        codes = [block["code"] for block in card["blocks"]]
        assert "holdout_hard_failure_unverified" in codes, name
        assert "holdout_hard_evidence_missing" in codes, name
        assert card["release_ready"] is False, name


def test_rag_direct_with_query_expansion_and_placeholder_template_still_pass() -> None:
    case = _one_case()
    result = classify(
        case,
        _single(case),
        _rag_empty_scope(use_model=True, purposes=["query_expansion"]),
    )
    assert result.axis("stale_source").state == "passed"
    assert result.axis("cross_entity").state == "passed"
    # 占位符模板：1..512 字符合法；513 字符 unknown。
    placeholder = product_copy.COPY["LEGACY_UNKNOWN_STORE"].template.format(store="合成门店")
    ok = classify(case, _single(case), model_answer_empty_scope(answer_text=placeholder))
    assert ok.axis("stale_source").state == "passed"
    too_long = product_copy.COPY["LEGACY_UNKNOWN_STORE"].template.format(store="X" * 513)
    bad = classify(case, _single(case), model_answer_empty_scope(answer_text=too_long))
    assert bad.axis("stale_source").state == "unknown"
    assert bad.axis("stale_source").reason == "template_identity_unverified"


# --------------------------------------------------------------------------- #
# B-R3（FAIL-B 收口）：空 key/空白条目不得证明空集（原始容器判定）
# --------------------------------------------------------------------------- #

R3_SOURCE_ID_VARIANTS: tuple[tuple[str, str, list[str]], ...] = (
    ("answer_source_ids_empty_string", "answer_result", [""]),
    ("answer_source_ids_spaces", "answer_result", ["   "]),
    ("answer_source_ids_fullwidth_space", "answer_result", ["\u3000"]),
    ("commit_source_ids_empty_string", "commit_observed", [""]),
    ("commit_source_ids_spaces", "commit_observed", ["   "]),
)
R3_MODEL_EVIDENCE_VARIANTS: tuple[tuple[str, list[Any]], ...] = (
    ("model_evidence_empty_mapping", [{}]),
    ("model_evidence_raw_string", ["unit-x"]),
    ("model_evidence_source_id_none", [{"source_id": None}]),
    ("model_evidence_source_id_blank", [{"source_id": "   "}]),
    ("model_evidence_empty_source_and_text", [{"source_id": "", "text": ""}]),
    ("model_evidence_blank_source_with_text", [{"source_id": "   ", "text": "合成证据"}]),
)


def _r3_envelope_for(kind: str, name: str, value: Any) -> dict[str, Any]:
    envelope = model_answer_empty_scope()
    if kind == "source_ids":
        _event_payload(envelope, name)["source_ids"] = list(value)
    else:
        _event_payload(envelope, "model_input")["evidence"] = value
    return envelope


@pytest.mark.parametrize(
    "name,event_kind,value",
    R3_SOURCE_ID_VARIANTS,
    ids=[item[0] for item in R3_SOURCE_ID_VARIANTS],
)
def test_blank_or_invalid_source_ids_cannot_prove_empty_scope(name: str, event_kind: str, value: list[str]) -> None:
    case = _one_case()
    envelope = model_answer_empty_scope()
    _event_payload(envelope, event_kind)["source_ids"] = value
    result = classify(case, _single(case), envelope)
    for axis in ("stale_source", "cross_entity"):
        assert result.axis(axis).state == "unknown", (name, axis, result.as_dict())
        assert result.axis(axis).reason == "empty_set_not_proven", (name, axis, result.axis(axis))
        assert "empty_set_not_proven" in result.axis(axis).missing


@pytest.mark.parametrize(
    "name,value",
    R3_MODEL_EVIDENCE_VARIANTS,
    ids=[item[0] for item in R3_MODEL_EVIDENCE_VARIANTS],
)
def test_unattributable_model_evidence_cannot_prove_empty_scope(name: str, value: list[Any]) -> None:
    case = _one_case()
    envelope = model_answer_empty_scope()
    _event_payload(envelope, "model_input")["evidence"] = value
    result = classify(case, _single(case), envelope)
    for axis in ("stale_source", "cross_entity"):
        assert result.axis(axis).state == "unknown", (name, axis, result.as_dict())
        assert result.axis(axis).reason == "empty_set_not_proven", (name, axis, result.axis(axis))


@pytest.mark.parametrize(
    "name,value",
    (
        ("answer_source_ids_valid_nonempty", ["unit-x"]),
        ("model_evidence_valid_nonempty", [{"source_id": "unit-x"}]),
    ),
    ids=["answer_source_ids_valid_nonempty", "model_evidence_valid_nonempty"],
)
def test_valid_nonempty_usage_layers_still_unknown(name: str, value: Any) -> None:
    case = _one_case()
    envelope = model_answer_empty_scope()
    if name.startswith("answer"):
        _event_payload(envelope, "answer_result")["source_ids"] = value
    else:
        _event_payload(envelope, "model_input")["evidence"] = value
    result = classify(case, _single(case), envelope)
    for axis in ("stale_source", "cross_entity"):
        assert result.axis(axis).state == "unknown", (name, axis, result.as_dict())


def test_blank_key_gap_aggregate_cannot_be_verified() -> None:
    cases = make_cases()
    annotation = hard.prepare_annotation(make_annotation(cases), cases)
    envelopes: dict[str, dict[str, Any]] = {}
    env = model_answer_empty_scope()
    _event_payload(env, "answer_result")["source_ids"] = [""]
    envelopes["answer_source_ids_blank"] = env
    env = model_answer_empty_scope()
    _event_payload(env, "commit_observed")["source_ids"] = ["   "]
    envelopes["commit_source_ids_blank"] = env
    env = model_answer_empty_scope()
    _event_payload(env, "model_input")["evidence"] = [{"source_id": "", "text": ""}]
    envelopes["model_evidence_blank_key"] = env
    for name, envelope in envelopes.items():
        results = [
            hard.classify_case_evidence(case, annotation, make_audit(case, envelope))
            for case in cases
        ]
        card = hard.aggregate_hard_evidence(results, total=30, run_id="run-" + name, config_hash="e" * 64)
        hard_evidence = card["hard_evidence"]
        for axis in ("stale_source", "cross_entity"):
            assert hard_evidence["axes"][axis]["unknown"] == 30, (name, axis)
            assert hard_evidence["axes"][axis]["checked"] == 0, (name, axis)
        assert hard_evidence["verified"] is False, name
        assert hard_evidence["missing_evidence_cases"] == 30, name
        codes = [block["code"] for block in card["blocks"]]
        assert "holdout_hard_failure_unverified" in codes, name
        assert "holdout_hard_evidence_missing" in codes, name
        assert card["release_ready"] is False, name


def test_r3_controls_empty_containers_still_pass() -> None:
    case = _one_case()
    result = classify(case, _single(case), model_answer_empty_scope())
    assert result.axis("stale_source").state == "passed"
    assert result.axis("cross_entity").state == "passed"


# --------------------------------------------------------------------------- #
# B-R4（闭包式）：使用层字段闭包矩阵——忽略字段不再可 pass
# --------------------------------------------------------------------------- #


def _append_retrieval(
    envelope: dict[str, Any],
    *,
    unit_ids: Any = (),
    scope: str = "legacy_retrieve_initial",
    missing_unit_ids_key: bool = False,
) -> None:
    payload: dict[str, Any] = {
        "request_id": "req-1",
        "scope": scope,
        "candidate": True,
        "truncated": False,
        "empty": not unit_ids,
    }
    if not missing_unit_ids_key:
        payload["unit_ids"] = list(unit_ids) if isinstance(unit_ids, (list, tuple)) else unit_ids
    _append_capture_event(envelope, "retrieval_observed", payload)


def _legacy_answer_envelope() -> dict[str, Any]:
    return model_answer_empty_scope()


def _rag_envelope() -> dict[str, Any]:
    return _rag_empty_scope()


R4_BRANCH_ENVELOPES = {
    "legacy_answer": _legacy_answer_envelope,
    "legacy_no_model": legacy_no_model_empty_scope,
    "rag_direct": _rag_envelope,
}
R4_RETRIEVAL_SCOPES = {
    "legacy_answer": "legacy_retrieve_initial",
    "legacy_no_model": "legacy_retrieve_initial",
    "rag_direct": "rag_candidate_upper_bound",
}


@pytest.mark.parametrize("branch", list(R4_BRANCH_ENVELOPES))
@pytest.mark.parametrize(
    "name,unit_ids,missing_key,reason",
    [
        ("nonempty_unit_x", ["unit-x"], False, "empty_set_not_proven"),
        ("nonempty_empty_string", [""], False, "empty_set_not_proven"),
        ("nonempty_spaces", ["   "], False, "empty_set_not_proven"),
        ("unit_ids_null", None, False, "branch_evidence_missing"),
        ("unit_ids_string", "unit-x", False, "branch_evidence_missing"),
        ("unit_ids_missing", (), True, "branch_evidence_missing"),
    ],
)
def test_r4_retrieval_observed_usage_fields_all_branches(
    branch: str, name: str, unit_ids: Any, missing_key: bool, reason: str
) -> None:
    case = _one_case()
    envelope = R4_BRANCH_ENVELOPES[branch]()
    if branch == "legacy_no_model":
        # 该分支的 retrieval_observed 是“无模型”观察标志，先去掉旧标志再替换为本用例形状。
        # 删除后必须重排 seq：分类器的 A schema 自核会拒收 seq 缺口（缺键/坏结构不得 pass）。
        remaining = [
            item for item in envelope["capture"]["events"] if item["kind"] != "retrieval_observed"
        ]
        for index, item in enumerate(remaining, 1):
            item["seq"] = index
        envelope["capture"]["events"] = remaining
        envelope["capture"]["seq"] = len(remaining)
        envelope["capture"]["event_count"] = len(remaining)
    _append_retrieval(
        envelope,
        unit_ids=unit_ids if unit_ids is not None else (),
        scope=R4_RETRIEVAL_SCOPES[branch],
        missing_unit_ids_key=missing_key,
    )
    if unit_ids is None and not missing_key:
        _event_payload(envelope, "retrieval_observed")["unit_ids"] = None
    result = classify(case, _single(case), envelope)
    for axis in ("stale_source", "cross_entity"):
        assert result.axis(axis).state == "unknown", (branch, name, axis, result.as_dict())
        assert result.axis(axis).reason == reason, (branch, name, axis, result.axis(axis))


@pytest.mark.parametrize("branch", list(R4_BRANCH_ENVELOPES))
def test_r4_real_product_scope_empty_retrieval_controls_pass(branch: str) -> None:
    case = _one_case()
    envelope = R4_BRANCH_ENVELOPES[branch]()
    if branch != "legacy_no_model":
        _append_retrieval(envelope, unit_ids=(), scope=R4_RETRIEVAL_SCOPES[branch])
    result = classify(case, _single(case), envelope)
    assert result.axis("stale_source").state == "passed", (branch, result.as_dict())
    assert result.axis("cross_entity").state == "passed", (branch, result.as_dict())


@pytest.mark.parametrize("mutation", ["rag_facts_nonempty", "rag_cited_nonempty"])
def test_r4_nonempty_direct_rag_usage_is_unknown(mutation: str) -> None:
    case = _one_case()
    envelope = _rag_envelope()
    payload = _event_payload(envelope, "direct_rag_answer")
    if mutation == "rag_facts_nonempty":
        payload["facts"] = [{"source_id": "unit-x"}]
    else:
        payload["cited_unit_ids"] = ["unit-x"]
    result = classify(case, _single(case), envelope)
    for axis in ("stale_source", "cross_entity"):
        assert result.axis(axis).state == "unknown", (mutation, axis, result.as_dict())


# --------------------------------------------------------------------------- #
# B-R4 / C16 夹具修正：投影 units 必须镜像检索候选（生产不变式），否则形状不可达。
# 已批准的 v0.4 在“units=[] + 检索非空”上放行，但该形状生产上不存在：投影由
# `_event_unit_ids(events)` 派生 → 检索非空时投影必非空 → v0.4 在投影为空一项被拒。
# --------------------------------------------------------------------------- #


def _c16_mirror_envelope(**overrides: Any) -> dict[str, Any]:
    """C16 真实形状：投影 units 的 unit_id 集合 == `retrieval_observed.unit_ids` 并集。"""
    values: dict[str, Any] = dict(
        units=[],
        used_unit_ids=[],
        final_source_ids=[],
        use_model=False,
        retrieval_candidates=["unit-1"],
        retrieval_scope="legacy_retrieve_initial",
        answer_kind="not_found",
        answer_text=real_no_fact_text("not_found"),
    )
    values.update(overrides)
    return build_evidence(**values)


def test_r4_c16_fixture_projection_mirrors_retrieval_units() -> None:
    envelope = _c16_mirror_envelope()
    assert [str(row["unit_id"]) for row in envelope["db_projection"]["units"]] == ["unit-1"]
    assert _event_payload(envelope, "retrieval_observed")["unit_ids"] == ["unit-1"]
    assert hard._projection_units_mirror_retrieval(envelope) is True


def test_r4_c16_mirror_shape_rejected_by_old_versions_passes_only_v0_5() -> None:
    envelope = _c16_mirror_envelope()
    assert hard._empty_use_scope_proof(envelope) == (False, "empty_set_not_proven")
    for compat in (
        "p2-refusal-compat/v0.1",
        "p2-refusal-compat/v0.3",
        "p2-refusal-compat/v0.4",
    ):
        assert hard._empty_use_scope_proof(envelope, compat=compat) == (
            False,
            "empty_set_not_proven",
        ), compat
    assert hard._empty_use_scope_proof(envelope, compat="p2-refusal-compat/v0.5") == (
        True,
        "empty_use_scope_ok",
    )


def test_r4_c16_projection_extra_unit_is_not_a_mirror() -> None:
    envelope = _c16_mirror_envelope()
    extra = _copy(envelope)
    extra["db_projection"]["units"].append(_unit_row(unit_id="unit-9"))
    assert hard._projection_units_mirror_retrieval(extra) is False
    assert hard._empty_use_scope_proof(extra, compat="p2-refusal-compat/v0.5") == (
        False,
        "empty_set_not_proven",
    )


def test_r4_c16_projection_missing_retrieval_unit_is_not_a_mirror() -> None:
    envelope = _c16_mirror_envelope(retrieval_candidates=["unit-1", "unit-2"])
    assert [str(row["unit_id"]) for row in envelope["db_projection"]["units"]] == [
        "unit-1",
        "unit-2",
    ]
    dropped = _copy(envelope)
    dropped["db_projection"]["units"] = [
        row for row in dropped["db_projection"]["units"] if str(row["unit_id"]) == "unit-1"
    ]
    assert hard._projection_units_mirror_retrieval(dropped) is False
    assert hard._empty_use_scope_proof(dropped, compat="p2-refusal-compat/v0.5") == (
        False,
        "empty_set_not_proven",
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("legacy_direct_rag_empty_event", "branch_evidence_inconsistent"),
        ("rag_fact_count_one", "empty_set_not_proven"),
        ("rag_facts_null", "branch_evidence_missing"),
        ("model_output_source_ids_blank", "empty_set_not_proven"),
        ("model_output_source_ids_unit", "empty_set_not_proven"),
        ("model_output_source_ids_null", "branch_evidence_missing"),
        ("model_output_usage_bad", "branch_evidence_missing"),
        ("model_output_provider_bad", "branch_evidence_missing"),
        ("model_input_context_questions_bad", "branch_evidence_missing"),
        ("model_input_context_entities_bad", "branch_evidence_missing"),
    ],
)
def test_r4_other_usage_and_typed_fields(mutation: str, reason: str) -> None:
    case = _one_case()
    if mutation == "legacy_direct_rag_empty_event":
        envelope = _legacy_answer_envelope()
        _append_capture_event(
            envelope,
            "direct_rag_answer",
            {
                "request_id": "req-1",
                "kind": "not_found",
                "text": real_no_fact_text("not_found"),
                "reason": None,
                "answer_source": "rag",
                "cited_unit_ids": [],
                "fact_count": 0,
                "facts": [],
                "state_keys": [],
            },
        )
    elif mutation.startswith("rag_"):
        envelope = _rag_envelope()
        payload = _event_payload(envelope, "direct_rag_answer")
        if mutation == "rag_facts_nonempty":
            payload["facts"] = [{"source_id": "unit-x"}]
        elif mutation == "rag_cited_nonempty":
            payload["cited_unit_ids"] = ["unit-x"]
        elif mutation == "rag_fact_count_one":
            payload["fact_count"] = 1
        elif mutation == "rag_facts_null":
            payload["facts"] = None
    else:
        envelope = _legacy_answer_envelope()
        output = _event_payload(envelope, "model_output")
        model_input = _event_payload(envelope, "model_input")
        if mutation == "model_output_source_ids_blank":
            output["source_ids"] = [""]
        elif mutation == "model_output_source_ids_unit":
            output["source_ids"] = ["unit-x"]
        elif mutation == "model_output_source_ids_null":
            output["source_ids"] = None
        elif mutation == "model_output_usage_bad":
            output["usage"] = {"a": "b"}
        elif mutation == "model_output_provider_bad":
            output["provider_request_id"] = 5
        elif mutation == "model_input_context_questions_bad":
            model_input["context_questions"] = "合成问题"
        elif mutation == "model_input_context_entities_bad":
            model_input["context_entities"] = []
    result = classify(case, _single(case), envelope)
    for axis in ("stale_source", "cross_entity"):
        assert result.axis(axis).state == "unknown", (mutation, axis, result.as_dict())
        assert result.axis(axis).reason == reason, (mutation, axis, result.axis(axis))


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("projection_unknown_key", "unknown_usage_field"),
        ("units_nonempty", "empty_set_not_proven"),
        ("message_sources_nonempty", "empty_set_not_proven"),
        ("unresolved_nonempty", "empty_set_not_proven"),
        ("query_states_candidates_nonempty", "empty_set_not_proven"),
        ("query_states_state_missing", "branch_evidence_missing"),
        ("message_row_unknown_key", "unknown_usage_field"),
        ("unit_row_unknown_key", "unknown_usage_field"),
        ("unresolved_row_unknown_key", "unknown_usage_field"),
        ("conversation_unknown_key", "unknown_usage_field"),
        ("request_unknown_key", "unknown_usage_field"),
        ("event_unknown_kind", "unknown_usage_field"),
        ("event_payload_unknown_key", "unknown_usage_field"),
        ("envelope_unknown_top_key", "unknown_usage_field"),
        ("capture_errors_nonempty", "evidence_incomplete"),
    ],
)
def test_r4_projection_and_envelope_unknown_fields_fail_closed(mutation: str, reason: str) -> None:
    case = _one_case()
    envelope = _legacy_answer_envelope()
    projection = envelope["db_projection"]
    if mutation == "projection_unknown_key":
        projection["candidate_units"] = ["unit-x"]
    elif mutation == "units_nonempty":
        projection["units"] = [_unit_row("unit-x")]
    elif mutation == "message_sources_nonempty":
        projection["message_sources"] = [
            {"message_id": "msg-assistant", "source_id": "unit-x", "document_id": "doc-1", "version_id": "ver-1"}
        ]
    elif mutation == "unresolved_nonempty":
        projection["unresolved_unit_ids"] = [{"unit_id": "unit-x", "reason": "unit_not_found"}]
    elif mutation == "query_states_candidates_nonempty":
        projection["query_states"] = [
            {
                "stored_user_id": AUTH_USER,
                "stored_conversation_id": "conv-1",
                "state_json": {"candidates": ["unit-x"]},
                "keys": ["candidates"],
            }
        ]
    elif mutation == "query_states_state_missing":
        projection["query_states"] = [
            {"stored_user_id": AUTH_USER, "stored_conversation_id": "conv-1", "keys": []}
        ]
    elif mutation == "message_row_unknown_key":
        projection["messages"][0]["candidate_unit_ids"] = ["unit-x"]
    elif mutation == "unit_row_unknown_key":
        projection["units"] = [_unit_row("unit-x")]
        projection["units"][0]["candidate_unit_ids"] = ["unit-x"]
    elif mutation == "unresolved_row_unknown_key":
        projection["unresolved_unit_ids"] = [{"unit_id": "unit-x", "reason": "x", "candidate": True}]
    elif mutation == "conversation_unknown_key":
        projection["conversation"]["candidate_units"] = ["unit-x"]
    elif mutation == "request_unknown_key":
        projection["request"]["candidate_units"] = ["unit-x"]
    elif mutation == "event_unknown_kind":
        _append_capture_event(envelope, "retrieval_candidates_observed", {"unit_ids": ["unit-x"]})
    elif mutation == "event_payload_unknown_key":
        _event_payload(envelope, "model_input")["candidate_unit_ids"] = ["unit-x"]
    elif mutation == "envelope_unknown_top_key":
        envelope["retrieval_usage"] = ["unit-x"]
    elif mutation == "capture_errors_nonempty":
        envelope["capture"]["errors"] = [
            {"code": "capture_error:synthetic", "stage": "observe", "request_id": "req-1", "detail": "synthetic"}
        ]
    result = classify(case, _single(case), envelope)
    for axis in ("stale_source", "cross_entity"):
        assert result.axis(axis).state == "unknown", (mutation, axis, result.as_dict())
        assert result.axis(axis).reason == reason, (mutation, axis, result.axis(axis))


@pytest.mark.parametrize(
    "answer_kind", ["no_answer", "clarification", "knowledge_changed"], ids=lambda x: x
)
def test_r4_nonempty_retrieval_blocks_all_no_fact_kinds(answer_kind: str) -> None:
    case = _one_case()
    envelope = model_answer_empty_scope(
        answer_kind=answer_kind, answer_text=real_no_fact_text(answer_kind)
    )
    _append_retrieval(envelope, unit_ids=["unit-x"], scope="legacy_retrieve_initial")
    result = classify(case, _single(case), envelope)
    for axis in ("stale_source", "cross_entity"):
        assert result.axis(axis).state == "unknown", (answer_kind, axis)
        assert result.axis(axis).reason == "empty_set_not_proven"


def test_r4_retrieval_gap_aggregate_cannot_be_verified() -> None:
    cases = make_cases()
    annotation = hard.prepare_annotation(make_annotation(cases), cases)
    envelopes = {
        "legacy_answer_nonempty_retrieval": _legacy_answer_envelope(),
        "rag_nonempty_candidates": _rag_envelope(),
    }
    _append_retrieval(
        envelopes["legacy_answer_nonempty_retrieval"], unit_ids=["unit-x"], scope="legacy_retrieve_initial"
    )
    _append_retrieval(
        envelopes["rag_nonempty_candidates"], unit_ids=["unit-x"], scope="rag_candidate_upper_bound"
    )
    for name, envelope in envelopes.items():
        results = [
            hard.classify_case_evidence(case, annotation, make_audit(case, envelope))
            for case in cases
        ]
        card = hard.aggregate_hard_evidence(results, total=30, run_id="run-" + name, config_hash="e" * 64)
        hard_evidence = card["hard_evidence"]
        for axis in ("stale_source", "cross_entity"):
            assert hard_evidence["axes"][axis]["unknown"] == 30, (name, axis)
            assert hard_evidence["axes"][axis]["checked"] == 0, (name, axis)
        assert hard_evidence["verified"] is False, name
        assert hard_evidence["missing_evidence_cases"] == 30, name
        codes = [block["code"] for block in card["blocks"]]
        assert "holdout_hard_failure_unverified" in codes, name
        assert "holdout_hard_evidence_missing" in codes, name
        assert card["release_ready"] is False, name


# --------------------------------------------------------------------------- #
# B-R5：① 未知键/未知事件全路径 fail-closed ② query_state 显式空状态
#       ③ kept_unknown 逐值 no-op（disclosures 仅 resolved 生效）
# --------------------------------------------------------------------------- #

R5_TARGETS = [{"entity_type": "store", "entity_key": "SYN-STORE-1", "filters": {}}]


def _passing_nonempty_annotation() -> Any:
    case = _one_case()
    annotation = _single(
        case,
        _axis_overrides(
            case,
            "cross_entity",
            applicability="required",
            criterion="structured_target",
            reason="explicit_single_target",
            targets=R5_TARGETS,
        ),
    )
    return case, annotation


def _passing_nonempty_envelope(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = dict(
        units=[{"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-1"}],
    )
    values.update(overrides)
    return build_evidence(**values)


def _r5_closure_mutations(envelope: dict[str, Any], name: str) -> dict[str, Any]:
    env = json.loads(json.dumps(envelope))
    if name == "event_unknown_kind":
        env["capture"]["events"].append(
            {
                "seq": len(env["capture"]["events"]) + 1,
                "kind": "retrieval_candidates_observed",
                "payload": {"unit_ids": []},
            }
        )
    elif name == "event_unknown_kind_nonempty_units":
        env["capture"]["events"].append(
            {
                "seq": len(env["capture"]["events"]) + 1,
                "kind": "retrieval_candidates_observed",
                "payload": {"unit_ids": ["unit-x"]},
            }
        )
    elif name == "event_payload_unknown_key":
        _event_payload(env, "model_input")["candidate_unit_ids"] = ["unit-x"]
    elif name == "projection_unknown_key":
        env["db_projection"]["candidate_units"] = ["unit-x"]
    elif name == "envelope_unknown_key":
        env["retrieval_usage"] = ["unit-x"]
    elif name == "turn_unknown_key":
        env["turn"]["retrieval_units"] = ["unit-x"]
    elif name == "capture_unknown_key":
        env["capture"]["candidate_units"] = ["unit-x"]
    elif name == "row_unknown_key":
        env["db_projection"]["messages"][0]["candidate_unit_ids"] = ["unit-x"]
    env["capture"]["seq"] = len(env["capture"]["events"])
    env["capture"]["event_count"] = len(env["capture"]["events"])
    return env


@pytest.mark.parametrize(
    "mutation",
    [
        "event_unknown_kind",
        "event_unknown_kind_nonempty_units",
        "event_payload_unknown_key",
        "projection_unknown_key",
        "envelope_unknown_key",
        "turn_unknown_key",
        "capture_unknown_key",
        "row_unknown_key",
    ],
)
def test_r5_unknown_keys_fail_closed_on_passing_nonempty_case(mutation: str) -> None:
    case, annotation = _passing_nonempty_annotation()
    baseline = classify(case, annotation, _passing_nonempty_envelope())
    assert baseline.axis("stale_source").state == "passed"
    assert baseline.axis("cross_entity").state == "passed"
    mutated = classify(case, annotation, _r5_closure_mutations(_passing_nonempty_envelope(), mutation))
    for axis in hard.AXES:
        assert mutated.axis(axis).state == "unknown", (mutation, axis, mutated.as_dict())
        assert mutated.axis(axis).reason == "unknown_usage_field", (mutation, axis, mutated.axis(axis))


def _r5_query_state_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": "req-1",
        "user_id": AUTH_USER,
        "conversation_id": "conv-1",
        "stored_user_id": None,
        "stored_conversation_id": None,
        "row_present": False,
        "state_keys": [],
        "state_json": {},
        "pending_slot": None,
        "last_kind": None,
        "turn": None,
    }
    payload.update(overrides)
    return payload


def _r5_empty_scope_with_query_state(payload: dict[str, Any]) -> dict[str, Any]:
    envelope = model_answer_empty_scope()
    _append_capture_event(envelope, "query_state_observed", payload)
    return envelope


def test_r5_first_turn_empty_query_state_is_explicit_empty_and_passes() -> None:
    case = _one_case()
    result = classify(case, _single(case), _r5_empty_scope_with_query_state(_r5_query_state_payload()))
    assert result.axis("stale_source").state == "passed", result.as_dict()
    assert result.axis("cross_entity").state == "passed", result.as_dict()
    # 对照：删除该事件同样 pass（空状态不是必需证据）。
    baseline = classify(case, _single(case), model_answer_empty_scope())
    assert baseline.axis("stale_source").state == "passed"
    assert baseline.axis("cross_entity").state == "passed"


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"state_json": None}, "branch_evidence_missing"),
        ({"_missing_state_json": True}, "branch_evidence_missing"),
        ({"row_present": None}, "branch_evidence_missing"),
        ({"row_present": False, "state_json": {"candidates": []}}, "branch_evidence_inconsistent"),
        ({"state_json": {"as_of": None}}, "branch_evidence_missing"),
        ({"state_json": {"candidates": ["unit-x"]}}, "empty_set_not_proven"),
    ],
)
def test_r5_query_state_invalid_or_usage_shapes_unknown(overrides: dict[str, Any], reason: str) -> None:
    case = _one_case()
    payload = _r5_query_state_payload(**{k: v for k, v in overrides.items() if not k.startswith("_")})
    if overrides.get("_missing_state_json"):
        payload.pop("state_json", None)
    result = classify(case, _single(case), _r5_empty_scope_with_query_state(payload))
    for axis in ("stale_source", "cross_entity"):
        assert result.axis(axis).state == "unknown", (overrides, axis, result.as_dict())
        assert result.axis(axis).reason == reason, (overrides, axis, result.axis(axis))


@pytest.mark.parametrize(
    "payload",
    [
        _r5_query_state_payload(row_present=True, state_json={}),
        _r5_query_state_payload(row_present=True, state_json={"candidates": []}),
    ],
    ids=["row_present_true_empty_state", "row_present_true_empty_candidates"],
)
def test_r5_query_state_row_present_empty_state_passes(payload: dict[str, Any]) -> None:
    case = _one_case()
    result = classify(case, _single(case), _r5_empty_scope_with_query_state(payload))
    assert result.axis("stale_source").state == "passed", result.as_dict()
    assert result.axis("cross_entity").state == "passed", result.as_dict()


def test_r5_projection_query_state_empty_state_passes_and_candidates_block() -> None:
    case = _one_case()
    envelope = model_answer_empty_scope()
    envelope["db_projection"]["query_states"] = [
        {
            "stored_user_id": AUTH_USER,
            "stored_conversation_id": "conv-1",
            "state_json": {},
            "keys": [],
        }
    ]
    ok = classify(case, _single(case), envelope)
    assert ok.axis("stale_source").state == "passed"
    assert ok.axis("cross_entity").state == "passed"
    bad = json.loads(json.dumps(envelope))
    bad["db_projection"]["query_states"][0]["state_json"] = {"candidates": ["unit-x"]}
    result = classify(case, _single(case), bad)
    for axis in ("stale_source", "cross_entity"):
        assert result.axis(axis).state == "unknown"
        assert result.axis(axis).reason == "empty_set_not_proven"


def _all_gaps_kept_unknown_addendum(cases: tuple[CaseSpec, ...], payload: dict[str, Any]) -> dict[str, Any]:
    addendum = make_addendum(cases, payload, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA)
    for gap in addendum["gaps"]:
        index, axis_name = gap["case_index"], gap["axis"]
        gap["resolution"] = "kept_unknown"
        gap["basis"] = "no_provable_basis_keep_unknown"
        gap["changed_fields"] = []
        gap["axis_value"] = json.loads(json.dumps(payload["cases"][index]["axes"][axis_name]))
    addendum["gap_summary"] = {
        "gap_total": len(addendum["gaps"]),
        "resolved_count": 0,
        "kept_unknown_count": len(addendum["gaps"]),
        "entity_target_gap_count": sum(1 for g in addendum["gaps"] if g["gap_kind"] == "unresolved_entity_target"),
        "date_anchor_gap_count": sum(1 for g in addendum["gaps"] if g["gap_kind"] == "unresolved_date_anchor"),
    }
    return addendum


def test_r5_all_kept_unknown_merge_is_value_noop_and_classification_unchanged() -> None:
    cases = make_cases()
    # 让 kept_unknown 覆盖的轴在 v0.2 中本该 pass（3/7 cross_entity 命中 target；4/9 stale 无日期约束），
    # 以证伪“disclosures 仍生效导致改判 unknown”。
    overrides = {}
    for index in (3, 7):
        overrides[cases[index].case_id] = {
            "cross_entity": {
                "applicability": "required",
                "criterion": "structured_target",
                "reason": "explicit_single_target",
                "targets": R5_TARGETS,
            }
        }
    payload = make_annotation(cases, overrides=overrides)
    addendum = _all_gaps_kept_unknown_addendum(cases, payload)
    merged_ann = hard.prepare_annotation(
        payload, cases, addendum=addendum, annotation_cipher_sha256=SYNTHETIC_ANNOTATION_CIPHER_SHA
    )
    base_ann = hard.prepare_annotation(payload, cases)
    for index in range(30):
        for axis in hard.AXES:
            assert merged_ann.axis(cases[index].case_id, axis) == payload["cases"][index]["axes"][axis]
    # 分类：kept_unknown 的 disclosures 不得生效；与 v0.2 语义逐题一致。
    for index, case in enumerate(cases):
        evidence = _passing_nonempty_envelope()
        base_result = hard.classify_case_evidence(case, base_ann, make_audit(case, evidence))
        merged_result = hard.classify_case_evidence(case, merged_ann, make_audit(case, evidence))
        for axis in hard.AXES:
            assert merged_result.axis(axis).state == base_result.axis(axis).state, (
                index,
                axis,
                merged_result.axis(axis),
                base_result.axis(axis),
            )
    # 30 题聚合四轴计数与 v0.2 完全一致。
    base_results = [
        hard.classify_case_evidence(case, base_ann, make_audit(case, _passing_nonempty_envelope()))
        for case in cases
    ]
    merged_results = [
        hard.classify_case_evidence(case, merged_ann, make_audit(case, _passing_nonempty_envelope()))
        for case in cases
    ]
    base_card = hard.aggregate_hard_evidence(base_results, total=30, run_id="run-base", config_hash="e" * 64)
    merged_card = hard.aggregate_hard_evidence(merged_results, total=30, run_id="run-merged", config_hash="e" * 64)
    assert merged_card["hard_evidence"]["axes"] == base_card["hard_evidence"]["axes"]


# --------------------------------------------------------------------------- #
# B-R6：turn 级完整性门（非空 passing turn 也必须在分轴前拒绝缺证据/坏事件）
# --------------------------------------------------------------------------- #

R6_INTEGRITY_REASONS = {"branch_evidence_missing", "empty_set_not_proven"}


def _r6_assert_not_pass(result: Any, label: str) -> None:
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown", (label, axis, result.as_dict())


def test_r6_projection_truncations_block_passing_turn() -> None:
    case, annotation = _passing_nonempty_annotation()
    envelope = _passing_nonempty_envelope()
    envelope["db_projection"]["truncations"] = ["units_limit"]
    result = classify(case, annotation, envelope)
    _r6_assert_not_pass(result, "projection_truncations")
    for axis in hard.AXES:
        assert result.axis(axis).reason == "evidence_incomplete", (axis, result.axis(axis))


@pytest.mark.parametrize(
    "mutation",
    ["projection_errors", "capture_errors", "capture_error_event", "event_truncated_flag"],
)
def test_r6_other_incompleteness_markers_block_passing_turn(mutation: str) -> None:
    case, annotation = _passing_nonempty_annotation()
    envelope = _passing_nonempty_envelope()
    if mutation == "projection_errors":
        envelope["db_projection"]["errors"] = ["projection_units_limit"]
    elif mutation == "capture_errors":
        envelope["capture"]["errors"] = [
            {"code": "capture_error:synthetic", "stage": "observe", "request_id": "req-1", "detail": "synthetic"}
        ]
    elif mutation == "capture_error_event":
        _append_capture_event(
            envelope,
            "capture_error",
            {"request_id": "req-1", "stage": "observe", "code": "capture_error:synthetic", "detail": "synthetic"},
        )
    else:
        _append_capture_event(
            envelope,
            "retrieval_observed",
            {
                "request_id": "req-1",
                "scope": "legacy_retrieve_initial",
                "unit_ids": [],
                "candidate": False,
                "truncated": True,
                "empty": True,
            },
        )
    result = classify(case, annotation, envelope)
    _r6_assert_not_pass(result, mutation)
    for axis in hard.AXES:
        assert result.axis(axis).reason == "evidence_incomplete", (mutation, axis, result.axis(axis))


R6_INVALID_EVENT_MUTATIONS = (
    "claim_missing_field",
    "claim_wrong_type",
    "answer_source_ids_missing",
    "answer_source_ids_null",
    "answer_kind_wrong_type",
    "model_input_evidence_string",
    "model_output_usage_bad",
    "plan_path_wrong_type",
    "retrieval_unit_ids_null",
)


def _r6_invalid_event_envelope(mutation: str) -> dict[str, Any]:
    envelope = _passing_nonempty_envelope()
    if mutation == "claim_missing_field":
        _event_payload(envelope, "claim_observed").pop("attempt", None)
    elif mutation == "claim_wrong_type":
        _event_payload(envelope, "claim_observed")["attempt"] = "x"
    elif mutation == "answer_source_ids_missing":
        _event_payload(envelope, "answer_result").pop("source_ids", None)
        _event_payload(envelope, "commit_observed").pop("source_ids", None)
    elif mutation == "answer_source_ids_null":
        _event_payload(envelope, "answer_result")["source_ids"] = None
    elif mutation == "answer_kind_wrong_type":
        _event_payload(envelope, "answer_result")["kind"] = 5
        _event_payload(envelope, "commit_observed")["kind"] = 5
    elif mutation == "model_input_evidence_string":
        _event_payload(envelope, "model_input")["evidence"] = "not-a-list"
    elif mutation == "model_output_usage_bad":
        _event_payload(envelope, "model_output")["usage"] = {"a": "b"}
    elif mutation == "plan_path_wrong_type":
        _event_payload(envelope, "plan_observed")["path"] = 5
    elif mutation == "retrieval_unit_ids_null":
        _append_capture_event(
            envelope,
            "retrieval_observed",
            {
                "request_id": "req-1",
                "scope": "legacy_retrieve_initial",
                "unit_ids": None,
                "candidate": False,
                "truncated": False,
                "empty": True,
            },
        )
    return envelope


@pytest.mark.parametrize("mutation", R6_INVALID_EVENT_MUTATIONS, ids=lambda x: x)
def test_r6_a_invalid_event_payload_blocks_passing_turn(mutation: str) -> None:
    case, annotation = _passing_nonempty_annotation()
    envelope = _r6_invalid_event_envelope(mutation)
    result = classify(case, annotation, envelope)
    _r6_assert_not_pass(result, mutation)
    for axis in ("stale_source", "cross_entity"):
        assert result.axis(axis).reason in R6_INTEGRITY_REASONS, (mutation, axis, result.axis(axis))


def test_r6_hidden_other_entity_citation_with_bad_payload_cannot_pass() -> None:
    case, annotation = _passing_nonempty_annotation()
    envelope = _passing_nonempty_envelope(
        units=[
            {"unit_id": "unit-1", "entity_type": "store", "entity_key": "SYN-STORE-1"},
            {"unit_id": "unit-2", "entity_type": "store", "entity_key": "SYN-STORE-OTHER"},
        ],
    )
    # 隐藏 other-entity citation：删除 answer/commit source_ids（A-invalid），并把其它实体写成引用文本。
    _event_payload(envelope, "answer_result").pop("source_ids", None)
    _event_payload(envelope, "commit_observed").pop("source_ids", None)
    _event_payload(envelope, "model_input")["question"] = "合成问题：引用 SYN-STORE-OTHER"
    result = classify(case, annotation, envelope)
    _r6_assert_not_pass(result, "hidden_other_entity")
    cases = make_cases()
    annotation30 = hard.prepare_annotation(make_annotation(cases), cases)
    results = [hard.classify_case_evidence(item, annotation30, make_audit(item, envelope)) for item in cases]
    card = hard.aggregate_hard_evidence(results, total=30, run_id="run-r6-hidden", config_hash="e" * 64)
    assert card["hard_evidence"]["verified"] is False
    assert card["hard_evidence"]["missing_evidence_cases"] == 30
    codes = [block["code"] for block in card["blocks"]]
    assert "holdout_hard_failure_unverified" in codes
    assert "holdout_hard_evidence_missing" in codes


def test_r6_truncation_aggregate_cannot_verify() -> None:
    cases = make_cases()
    annotation = hard.prepare_annotation(make_annotation(cases), cases)
    envelope = model_answer_empty_scope()
    envelope["db_projection"]["truncations"] = ["units_limit"]
    results = [hard.classify_case_evidence(item, annotation, make_audit(item, envelope)) for item in cases]
    card = hard.aggregate_hard_evidence(results, total=30, run_id="run-r6-trunc", config_hash="e" * 64)
    he = card["hard_evidence"]
    assert he["verified"] is False
    assert he["missing_evidence_cases"] == 30
    for axis in hard.AXES:
        assert he["axes"][axis]["checked"] == 0, (axis, he["axes"][axis])
        assert he["axes"][axis]["unknown"] == 30, (axis, he["axes"][axis])
    codes = [block["code"] for block in card["blocks"]]
    assert "holdout_hard_failure_unverified" in codes
    assert "holdout_hard_evidence_missing" in codes


def test_r6_legal_baseline_still_verified() -> None:
    cases = make_cases()
    annotation = hard.prepare_annotation(make_annotation(cases), cases)
    results = [
        hard.classify_case_evidence(case, annotation, make_audit(case, model_answer_empty_scope()))
        for case in cases
    ]
    card = hard.aggregate_hard_evidence(results, total=30, run_id="run-r6-legal", config_hash="e" * 64)
    he = card["hard_evidence"]
    assert he["verified"] is True, card
    assert he["missing_evidence_cases"] == 0
    assert [block["code"] for block in card["blocks"]] == ["holdout_threshold_unapproved"]


# --------------------------------------------------------------------------- #
# B-R6 追加：v0.3 addendum 的 annotations_v0_2_sha256 绑定 = v0.2 标注密文 SHA256
# --------------------------------------------------------------------------- #


def test_r6_addendum_annotation_cipher_binding_modes() -> None:
    cases = make_cases()
    payload = make_annotation(cases)
    cipher = SYNTHETIC_ANNOTATION_CIPHER_SHA
    addendum = make_addendum(cases, payload, annotation_cipher_sha256=cipher)
    merged = hard.prepare_annotation(payload, cases, addendum=addendum, annotation_cipher_sha256=cipher)
    assert merged.axis(cases[3].case_id, "cross_entity") == addendum["gaps"][0]["axis_value"]
    # 1) 缺显式密文 sha → 固定拒绝（真实路径不允许省略）。
    with pytest.raises(hard.HardEvidenceError, match="addendum_annotation_cipher_sha_required"):
        hard.prepare_annotation(payload, cases, addendum=addendum)
    # 2) 用明文 canonical sha 冒充密文 sha（旧合成语义）→ 固定拒绝。
    plaintext_addendum = make_addendum(cases, payload)
    with pytest.raises(hard.HardEvidenceError, match="addendum_annotation_binding_mismatch"):
        hard.prepare_annotation(
            payload, cases, addendum=plaintext_addendum, annotation_cipher_sha256=cipher
        )
    # 3) 密文 sha 不匹配 → 固定拒绝。
    with pytest.raises(hard.HardEvidenceError, match="addendum_annotation_binding_mismatch"):
        hard.prepare_annotation(payload, cases, addendum=addendum, annotation_cipher_sha256="a" * 64)
    # 4) 非 64-hex 的“密文 sha” → 固定拒绝。
    with pytest.raises(hard.HardEvidenceError, match="addendum_annotation_cipher_sha_invalid"):
        hard.prepare_annotation(
            payload, cases, addendum=addendum, annotation_cipher_sha256="not-a-sha"
        )
    # 5) 低层 apply 也必须显式传密文 sha（禁止回退明文摘要）。
    with pytest.raises(TypeError):
        hard.apply_gap_addendum_v03(payload, addendum, cases)  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# B-R7：全 turn 事件唯一性与分支矩阵（非空 passing turn 同样强制）
# --------------------------------------------------------------------------- #


def _r7_append_event(envelope: dict[str, Any], kind: str, payload: dict[str, Any]) -> None:
    _append_capture_event(envelope, kind, payload)
    events = envelope["capture"]["events"]
    for index, event in enumerate(events, 1):
        event["seq"] = index
    envelope["capture"]["seq"] = len(events)
    envelope["capture"]["event_count"] = len(events)


def _r7_duplicate_event(envelope: dict[str, Any], kind: str) -> None:
    events = envelope["capture"]["events"]
    source = next(event for event in events if event["kind"] == kind)
    _r7_append_event(envelope, kind, json.loads(json.dumps(source["payload"])))


R7_REQUIRED_EVENTS = (
    "claim_observed",
    "context_observed",
    "plan_observed",
    "answer_result",
    "commit_observed",
)


@pytest.mark.parametrize("kind", R7_REQUIRED_EVENTS, ids=list(R7_REQUIRED_EVENTS))
def test_r7_duplicate_required_event_blocks_passing_turn(kind: str) -> None:
    case, annotation = _passing_nonempty_annotation()
    baseline = classify(case, annotation, _passing_nonempty_envelope())
    assert baseline.axis("stale_source").state == "passed"
    assert baseline.axis("cross_entity").state == "passed"
    envelope = _passing_nonempty_envelope()
    _r7_duplicate_event(envelope, kind)
    result = classify(case, annotation, envelope)
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown", (kind, axis, result.as_dict())
        assert result.axis(axis).reason == "branch_evidence_inconsistent", (kind, axis, result.axis(axis))


def test_r7_duplicate_model_input_blocks_passing_turn() -> None:
    case, annotation = _passing_nonempty_annotation()
    envelope = _passing_nonempty_envelope()
    _r7_duplicate_event(envelope, "model_input")
    result = classify(case, annotation, envelope)
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown"
        assert result.axis(axis).reason == "branch_evidence_inconsistent"


def test_r7_legacy_query_expansion_model_blocks_passing_turn() -> None:
    case, annotation = _passing_nonempty_annotation()
    envelope = _passing_nonempty_envelope()
    input_payload = json.loads(json.dumps(_event_payload(envelope, "model_input")))
    output_payload = json.loads(json.dumps(_event_payload(envelope, "model_output")))
    input_payload["purpose"] = "query_expansion"
    output_payload["purpose"] = "query_expansion"
    _r7_append_event(envelope, "model_input", input_payload)
    _r7_append_event(envelope, "model_output", output_payload)
    result = classify(case, annotation, envelope)
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown"
        assert result.axis(axis).reason == "branch_evidence_inconsistent"


def test_r7_legacy_direct_rag_event_blocks_passing_turn() -> None:
    case, annotation = _passing_nonempty_annotation()
    envelope = _passing_nonempty_envelope()
    answer = _event_payload(envelope, "answer_result")
    _r7_append_event(
        envelope,
        "direct_rag_answer",
        {
            "request_id": answer["request_id"],
            "kind": answer["kind"],
            "text": answer["text"],
            "reason": None,
            "answer_source": "direct_rag",
            "cited_unit_ids": [],
            "fact_count": 0,
            "facts": [],
            "state_keys": [],
        },
    )
    result = classify(case, annotation, envelope)
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown"
        assert result.axis(axis).reason == "branch_evidence_inconsistent"


def _r7_rag_passing_envelope() -> dict[str, Any]:
    envelope = _passing_nonempty_envelope()
    events = envelope["capture"]["events"]
    events[:] = [
        event
        for event in events
        if event["kind"] not in ("model_input", "model_output")
    ]
    plan = _event_payload(envelope, "plan_observed")
    plan["path"] = "rag"
    answer = _event_payload(envelope, "answer_result")
    _r7_append_event(
        envelope,
        "direct_rag_answer",
        {
            "request_id": answer["request_id"],
            "kind": answer["kind"],
            "text": answer["text"],
            "reason": None,
            "answer_source": "direct_rag",
            "cited_unit_ids": [],
            "fact_count": 0,
            "facts": [],
            "state_keys": [],
        },
    )
    return envelope


def test_r7_rag_passing_baseline_and_duplicate_plan_block() -> None:
    case, annotation = _passing_nonempty_annotation()
    envelope = _r7_rag_passing_envelope()
    baseline = classify(case, annotation, envelope)
    assert baseline.axis("stale_source").state == "passed", baseline.as_dict()
    assert baseline.axis("cross_entity").state == "passed", baseline.as_dict()
    duplicate = _r7_rag_passing_envelope()
    _r7_duplicate_event(duplicate, "plan_observed")
    result = classify(case, annotation, duplicate)
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown", (axis, result.as_dict())
        assert result.axis(axis).reason == "branch_evidence_inconsistent"
    duplicate_direct = _r7_rag_passing_envelope()
    _r7_duplicate_event(duplicate_direct, "direct_rag_answer")
    result = classify(case, annotation, duplicate_direct)
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown"
        assert result.axis(axis).reason == "branch_evidence_inconsistent"
    rag_with_answer = _r7_rag_passing_envelope()
    legacy_answer = _passing_nonempty_envelope()
    _r7_append_event(rag_with_answer, "model_input", json.loads(json.dumps(_event_payload(legacy_answer, "model_input"))))
    _r7_append_event(rag_with_answer, "model_output", json.loads(json.dumps(_event_payload(legacy_answer, "model_output"))))
    result = classify(case, annotation, rag_with_answer)
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown"
        assert result.axis(axis).reason == "branch_evidence_inconsistent"


def test_r7_missing_required_event_blocks_passing_turn() -> None:
    case, annotation = _passing_nonempty_annotation()
    envelope = _passing_nonempty_envelope()
    envelope["capture"]["events"] = [
        event for event in envelope["capture"]["events"] if event["kind"] != "claim_observed"
    ]
    envelope["capture"]["seq"] = len(envelope["capture"]["events"])
    envelope["capture"]["event_count"] = len(envelope["capture"]["events"])
    result = classify(case, annotation, envelope)
    for axis in ("stale_source", "cross_entity", "cross_user"):
        assert result.axis(axis).state == "unknown", (axis, result.as_dict())
    assert result.axis("safety").state in {"unknown", "not_applicable"}


def _r7_all_case_annotation() -> Any:
    cases = make_cases()
    overrides = {
        case.case_id: {
            "cross_entity": {
                "applicability": "required",
                "criterion": "structured_target",
                "reason": "explicit_single_target",
                "targets": R5_TARGETS,
            }
        }
        for case in cases
    }
    return cases, hard.prepare_annotation(make_annotation(cases, overrides=overrides), cases)


def test_r7_duplicate_plan_aggregate_cannot_verify_and_baseline_can() -> None:
    cases, annotation = _r7_all_case_annotation()
    baseline_env = _passing_nonempty_envelope()
    baseline_results = [
        hard.classify_case_evidence(case, annotation, make_audit(case, baseline_env)) for case in cases
    ]
    baseline_card = hard.aggregate_hard_evidence(
        baseline_results, total=30, run_id="run-r7-base", config_hash="e" * 64
    )
    assert baseline_card["hard_evidence"]["verified"] is True, baseline_card
    duplicate_env = _passing_nonempty_envelope()
    _r7_duplicate_event(duplicate_env, "plan_observed")
    duplicate_results = [
        hard.classify_case_evidence(case, annotation, make_audit(case, duplicate_env)) for case in cases
    ]
    duplicate_card = hard.aggregate_hard_evidence(
        duplicate_results, total=30, run_id="run-r7-dup", config_hash="e" * 64
    )
    he = duplicate_card["hard_evidence"]
    assert he["verified"] is False
    assert he["missing_evidence_cases"] == 30
    for axis in hard.AXES:
        assert he["axes"][axis]["checked"] == 0, (axis, he["axes"][axis])
    codes = [block["code"] for block in duplicate_card["blocks"]]
    assert "holdout_hard_failure_unverified" in codes
    assert "holdout_hard_evidence_missing" in codes
