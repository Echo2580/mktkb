"""C1-P2 合成测试：空使用集闭包证明替代实现 + 与 C 冻结原语差分。

只使用自建合成 envelope；不读真实 H2 题面/标签/答案/私有密文/key/.env，不调用
模型/检索/产品/网络。``t09_network_guard`` 在 teardown 断言 external=0。

差分口径
--------
- 同一批合成输入下，逐例比较 ``prove_empty_use_scope`` 与冻结原语
  ``_empty_use_scope_proof`` 的 **proven 布尔结论**。
- 结论一致的例不要求 reason 逐字相同（本实现对未证明形状统一固定码
  ``empty_set_not_proven``；冻结原语有更细的 reason 词表）。
- 结论不一致的每一例都必须在 ``DIVERGENCE_REASONS`` 中有固定码与明确理由：
  - ``ours=True, frozen=False``：本实现覆盖了冻结原语把候选层当使用层等形状；
  - ``ours=False, frozen=True``：本实现更严（只可能出现在冻结原语漏计的使用层）。
- 未编码的不一致一律 fail；不允许“看起来差不多”的静默放过。
"""

from __future__ import annotations

import ast
import copy
import functools
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.copy import COPY, clarification_candidates_text  # noqa: E402
from mktkb.evaluation import p2_empty_scope_proof as proof  # noqa: E402
from mktkb.evaluation.p2_empty_scope_proof import (  # noqa: E402
    EMPTY_SET_NOT_PROVEN,
    EMPTY_USE_SCOPE_OK,
    empty_use_scope_proof,
    prove_empty_use_scope,
)
from mktkb.evaluation.p2_hard_evidence import _empty_use_scope_proof  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
FROZEN_MODULE = ROOT / "backend" / "src" / "mktkb" / "evaluation" / "p2_hard_evidence.py"
# 2026-11-17 授权变更（v0.6 纯文档正文 cross_entity 增量，**返工后：v0.6 继承 v0.5**）：
# 主人已批准该增量后，本 pin 随授权后的字节更新。
# 授权与范围：.claude/handoffs/T-R1-108-compat-v06/handoff.md（§1 目标、§3 实现要求）与返工指令
#             （v0.6 = v0.5 全部行为 + 纯文档回合 cross_entity N/A）；契约 docs/evaluation/p2-refusal-compat-v0_6.md。
# 变更性质：新增 v0.6 版本常量 + 继承表项（v0.6 → v0.5）+ “纯文档正文回合”判据，并在
#           `_check_cross_entity` 末段兜底（matched==0 且无违规/未知）多一条 v0.6 的 not_applicable
#           分支与审计 ref；`_projection_mirror_relaxable` 的版本条件由“精确等于 v0.5”改为
#           “v0.5 在继承链上”（v0.5 自身结果不变，v0.6 才因此拿到 v0.5 的空集/镜像放行）。
#           v0.1/v0.3/v0.4/v0.5 判据逐字不变（test_p2_hard_evidence.py 289 passed + 27 pre-existing
#           夹具 setup errors、test_r0_repair_refusal_compat.py / test_r0_repair_c16_empty_scope.py /
#           test_r0_repair_v05_projection_mirror.py 全绿，test_r1_108_compat_v06.py 覆盖继承、
#           v0.5 反例逐条一致、新 N/A 与全部反例）。这是内容 pin，不是行为断言。
# 旧值（v0.6 增量前 = v0.5 批准字节）：7956b2b7159d6bc740a7ecff156605c85ad75c00ef57c45f99f282f19e14ba19
# 返工说明：同日中间的“独立档”版本字节（82919196d1e0694ad56c5b39d1166d14547c6b9d57fdb52df590a9f88fd3f518）
#           未交付，已被本值取代；回退方式见契约 §6（删常量/继承项/判据/分支，pin 回 7956b2b7…）。
# 2026-11-16 授权变更（v0.5 空用集增补：投影 units 逐值镜像检索层）：主人批准 v0.5 后，
# 本 pin 随授权后的字节再次更新。
# 授权与范围：docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/C16-EMPTY-SCOPE-PROPOSAL.md
#             §5 与本次主人对 v0.5 的批准；契约 docs/evaluation/p2-refusal-compat-v0_5.md。
# 变更性质：只新增 v0.5 版本常量 + 链式继承解析（v0.5 → v0.4 → v0.3）+ “投影 units 逐值镜像
#           检索层”的窄放行判据与审计码 `projection_mirrors_retrieval`；v0.1/v0.3/v0.4 判据逐字不变
#           （test_r0_repair_refusal_compat.py 62 passed、test_r0_repair_c16_empty_scope.py 29 passed，
#           test_r0_repair_v05_projection_mirror.py 覆盖新放行与全部反例）。这是内容 pin，不是行为断言。
# 旧值（v0.5 增量前 = v0.4 批准字节）：8f206ee9f016b9fbf5d9d0c0568117f05692849c540fe232c3ec50b5c42c5bec
# 2026-11-16 授权变更（C16 空用集兼容增量 v0.4）：主人批准 C16-EMPTY-SCOPE-PROPOSAL.md §5 第 1 项后，
# 本 pin 随授权后的字节再次更新。
# 授权与范围：docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/C16-EMPTY-SCOPE-PROPOSAL.md
#             §2（v0.4 窄放行：仅“检索到候选但一个事实都没用”的固定无事实结局）与 §5 第 1 项。
# 变更性质：只新增 v0.4 版本常量/继承表 + 窄放行判据与调用方审计码 `retrieval_observed_unused`；
#           v0.1/v0.3 判据逐字不变（test_r0_repair_refusal_compat.py 仍 62 passed，
#           test_r0_repair_c16_empty_scope.py 覆盖新放行与全部反例）。这是内容 pin，不是行为断言。
# 旧值（C16 增量前）：84f53a517e4c2e5eeb50cd4319462ef7d966f2d946083794c406cd2605bd485b
# 2026-11-16 授权变更：主人批准 R0-3 冻结兼容增量后，本 pin 随授权后的字节更新。
# 授权与范围：docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/REFUSAL-COMPATIBILITY-PROPOSAL.md
#             （§9 第 1 项已获主人批准）与 R0-3-REPORT.md。
# 变更性质：只新增版本开关常量 + keyword-only `compat`（默认 v0.1），未改任何既有判定、
#           阈值、词表本体或匹配器版本；旧版默认行为逐字不变（test_r0_repair_refusal_compat.py 覆盖）。
# 旧值（授权前）：fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b
# 2026-11-19 主人批准 C25 硬轴禁源身份修复。空集证明和拒答兼容判据未改。
FROZEN_SHA = "49aa66cc443e96995ba8256f1b49688371d851e4faea716c82a79180a9bcd2e8"
SENTINEL = "P2EMPTY_SYNTHETIC_SENTINEL_DO_NOT_EXPORT_c1p2"

_MISSING = object()

FROZEN_REASONS = frozenset(
    {
        "empty_use_scope_ok",
        "empty_set_not_proven",
        "model_events_missing",
        "branch_evidence_missing",
        "branch_evidence_inconsistent",
        "template_identity_unverified",
        "unknown_usage_field",
        "evidence_incomplete",
    }
)

DIVERGENCE_REASONS: dict[str, str] = {
    "frozen_retrieval_candidates_are_usage": (
        "冻结原语把 retrieval_observed.unit_ids / projection.units 当作使用层，候选非空即不可证明；"
        "本实现只把真正进入模型输入、引用、事实、提交、DB message_sources 或实体继承的来源计为使用。"
    ),
    "frozen_query_state_candidates_are_usage": (
        "冻结原语把 query_states[].state_json.candidates 当作使用层；该字段是会话级检索候选，"
        "不是本回合已使用来源。本实现按候选层处理。"
    ),
    "frozen_requires_retrieval_marker_for_legacy_no_model": (
        "冻结原语要求 legacy 无模型分支必须有 retrieval_observed 观察标志；v0.3 runtime_snapshot "
        "已显式声明 candidate_observation=not_observed/no_retrieval_observed 时仍返回 model_events_missing。"
    ),
    "frozen_does_not_track_entity_inheritance": (
        "冻结原语不把 entity_inheritance.source_unit_id 计入使用层；本实现按保守口径计为使用，"
        "因此只可能比冻结原语更严，不会产生假 proven。"
    ),
}

#: 冻结原语把检索/查询态候选层当使用层的固定码；用于差分结果分类。
FROZEN_CANDIDATE_LAYER_CODE = "frozen_retrieval_candidates_are_usage"
FROZEN_QUERY_STATE_CODE = "frozen_query_state_candidates_are_usage"
FROZEN_NO_RETRIEVAL_CODE = "frozen_requires_retrieval_marker_for_legacy_no_model"
FROZEN_INHERITANCE_CODE = "frozen_does_not_track_entity_inheritance"


# --------------------------------------------------------------------------- #
# 合成 envelope 构造（结构合法；默认即“可证明空集”）
# --------------------------------------------------------------------------- #


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _no_fact_text(kind: str) -> str:
    key = {
        "not_found": "LEGACY_NO_EVIDENCE",
        "no_answer": "NO_EVIDENCE",
        "clarification": "CLARIFICATION_REQUIRED",
        "knowledge_changed": "KNOWLEDGE_CHANGED",
    }[kind]
    return COPY[key].template


def _message_row(
    message_id: str,
    *,
    role: str,
    seq: int,
    kind: str | None = None,
    text: str = "合成消息",
) -> dict[str, Any]:
    return {
        "id": message_id,
        "conversation_id": "conv-1",
        "owner_user_id": "user-1",
        "role": role,
        "seq": seq,
        "kind": kind,
        "revision": 1,
        "error_code": None,
        "text": text,
        "created_at": "2026-11-13T00:00:00+00:00",
    }


def _unit_row(unit_id: str) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "unit_key": "key:" + unit_id,
        "kind": "table_row",
        "locator": {"sheet": "合成表", "row": 1},
        "text": "合成单元正文 " + SENTINEL,
        "raw_fields": {},
        "date_fields": {},
        "entity_type": "store",
        "entity_key": "store-1",
        "entity_filters": {},
        "document_id": "doc-1",
        "document_name": "合成资料",
        "document_deleted": False,
        "version_id": "ver-1",
        "version_number": 1,
        "version_state": "published",
        "active_version_id": "ver-1",
        "active": True,
        "published_at": "2026-10-01T00:00:00+00:00",
    }


def _fact_row(unit_id: str) -> dict[str, Any]:
    return {
        "entity_key": "store-1",
        "entity_label": "合成门店",
        "field_role": "value",
        "field_label": "合成字段",
        "value": "合成值",
        "source_chunk_id": "chunk-1",
        "source_unit_id": unit_id,
        "doc_id": "doc-1",
        "version_id": "ver-1",
        "revision": 1,
    }


def _turn_payload() -> dict[str, Any]:
    return {
        "turn_index": 0,
        "client_request_id": "client-1",
        "conversation_id": "conv-1",
        "authenticated_user_id": "user-1",
        "question_sha256": "0" * 64,
        "http_status": 200,
        "timed_out": False,
        "started_utc": "2026-11-13T00:00:00+00:00",
        "captured_utc": "2026-11-13T00:00:01+00:00",
        "pre_revision": 1,
        "post_revision": 1,
        "capture_revision": 1,
    }


def _with_projection_row_extra(envelope: dict[str, Any]) -> dict[str, Any]:
    envelope["db_projection"]["units"][0]["extra"] = 1
    return envelope


def _no_retrieval_snapshot() -> dict[str, Any]:
    return {
        "schema_version": "p2-runtime-snapshot/v0.1",
        "captured_utc": "2026-11-13T00:00:01+00:00",
        "binding": {},
        "product_response": {},
        "trace": {},
        "retrieval_use": {
            "candidates": [],
            "model_evidence": [],
            "direct_rag_facts": [],
            "direct_rag_citations": [],
            "final_citations": [],
            "inheritance": [],
            "availability": "complete",
            "reason": None,
            "candidate_observation": {
                "availability": "not_observed",
                "reason": "no_retrieval_observed",
            },
        },
    }


def build_evidence(**opts: Any) -> dict[str, Any]:
    """构造结构合法的 turn envelope；默认是 legacy 无模型 + 显式空检索的可证明回合。"""

    plan_path = str(opts.get("plan_path", "legacy"))
    kind = str(opts.get("kind", "not_found"))
    text = opts.get("text")
    if text is None:
        text = _no_fact_text(kind)
    model_purposes = tuple(str(item) for item in opts.get("model_purposes", ()))
    model_mode = str(opts.get("model_mode", "pair"))
    model_evidence_ids = tuple(str(item) for item in opts.get("model_evidence_ids", ()))
    model_output_source_ids = tuple(str(item) for item in opts.get("model_output_source_ids", ()))
    final_source_ids = tuple(str(item) for item in opts.get("final_source_ids", ()))
    answer_source_ids = tuple(str(item) for item in opts.get("answer_source_ids", final_source_ids))
    commit_source_ids = tuple(str(item) for item in opts.get("commit_source_ids", final_source_ids))
    answer_kind = str(opts.get("answer_kind", kind))
    commit_kind = str(opts.get("commit_kind", kind))
    answer_text = opts.get("answer_text", text)
    commit_text = opts.get("commit_text", text)

    retrieval_present = bool(opts.get("retrieval_present", True))
    retrieval_unit_ids = tuple(str(item) for item in opts.get("retrieval_unit_ids", ()))
    retrieval_scope = str(opts.get("retrieval_scope", "legacy_retrieve_initial"))
    retrieval_candidate = bool(opts.get("retrieval_candidate", False))

    direct_rag_opt = opts.get("direct_rag")
    direct_rag: dict[str, Any] | None = None
    if plan_path == "rag" and not opts.get("omit_direct_rag", False):
        direct_rag = dict(direct_rag_opt) if isinstance(direct_rag_opt, Mapping) else {}
    elif isinstance(direct_rag_opt, Mapping):
        direct_rag = dict(direct_rag_opt)
    if direct_rag is not None:
        facts = [dict(item) for item in opts.get("direct_rag_facts", ())]
        direct_rag.setdefault("request_id", "req-1")
        direct_rag.setdefault("kind", kind)
        direct_rag.setdefault("text", text)
        direct_rag.setdefault("reason", None)
        direct_rag.setdefault("answer_source", None)
        direct_rag.setdefault("cited_unit_ids", list(opts.get("direct_rag_cited_ids", ())))
        direct_rag.setdefault("facts", facts)
        if opts.get("direct_rag_fact_count") is None:
            direct_rag.setdefault("fact_count", len(facts))
        else:
            direct_rag["fact_count"] = int(opts["direct_rag_fact_count"])
        direct_rag.setdefault("state_keys", [])

    seq = {"value": 0}
    events: list[dict[str, Any]] = []

    def add(event_kind: str, payload: dict[str, Any]) -> None:
        seq["value"] += 1
        events.append({"seq": seq["value"], "kind": event_kind, "payload": payload})

    if "claim_observed" not in opts.get("omit_events", ()):
        add(
            "claim_observed",
            {
                "request_id": "req-1",
                "conversation_id": "conv-1",
                "attempt": 1,
                "authenticated_user_id": "user-1",
                "owner_user_id": "user-1",
                "user_message_id": "msg-user",
                "user_message_seq": 1,
                "initial_revision": 1,
                "replay": False,
            },
        )
    if "context_observed" not in opts.get("omit_events", ()):
        context_messages = list(opts.get("context_messages", ()))
        add(
            "context_observed",
            {
                "request_id": "req-1",
                "count": len(context_messages),
                "empty": not context_messages,
            },
        )
        for item in context_messages:
            add(
                "context_message",
                {
                    "request_id": "req-1",
                    "message_id": str(item.get("id", "ctx")),
                    "owner_user_id": "user-1",
                    "role": str(item.get("role", "user")),
                    "seq": int(item.get("seq", 1)),
                    "text": str(item.get("text", "合成历史消息 " + SENTINEL)),
                    "origin": "conversation",
                },
            )
    if "plan_observed" not in opts.get("omit_events", ()):
        add(
            "plan_observed",
            {
                "request_id": "req-1",
                "path": plan_path,
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
            },
        )
    if retrieval_present and "retrieval_observed" not in opts.get("omit_events", ()):
        add(
            "retrieval_observed",
            {
                "request_id": "req-1",
                "scope": retrieval_scope,
                "unit_ids": list(retrieval_unit_ids),
                "candidate": retrieval_candidate,
                "truncated": False,
                "empty": not retrieval_unit_ids,
            },
        )
    if "answer_result" not in opts.get("omit_events", ()):
        add(
            "answer_result",
            {
                "request_id": "req-1",
                "kind": answer_kind,
                "text": answer_text,
                "source_ids": list(answer_source_ids),
                "candidates": 0,
                "conflicts": 0,
                "missing_fields": [],
                "error_code": None,
                "reason": None,
            },
        )
    if "commit_observed" not in opts.get("omit_events", ()):
        add(
            "commit_observed",
            {
                "request_id": "req-1",
                "message_id": "msg-assistant",
                "assistant_seq": 2,
                "kind": commit_kind,
                "requested_kind": commit_kind,
                "text": commit_text,
                "source_ids": list(commit_source_ids),
                "revision_before": 1,
                "revision_after": 1,
                "knowledge_changed": False,
                "error_code": None,
            },
        )
    if direct_rag is not None:
        add("direct_rag_answer", direct_rag)
    for unit_id in opts.get("entity_inheritance_ids", ()):
        add(
            "entity_inheritance",
            {
                "request_id": "req-1",
                "entity_type": "store",
                "entity_key": "store-1",
                "source_message_id": None,
                "source_unit_id": str(unit_id),
                "source": "synthetic",
            },
        )
    if opts.get("capture_error_event"):
        add(
            "capture_error",
            {
                "stage": "capture",
                "code": "synthetic_capture_error",
                "request_id": "req-1",
                "detail": "synthetic",
            },
        )

    # 模型事件：按 purpose 成对/单边；重复用于反例。
    if model_purposes and model_mode != "none":
        evidence_rows = opts.get("model_input_evidence")
        if evidence_rows is None:
            evidence_rows = [
                {"source_id": source_id, "text": "合成证据 " + SENTINEL, "fields": {}}
                for source_id in model_evidence_ids
            ]
        for purpose in model_purposes:
            if model_mode in ("pair", "input_only"):
                payload: dict[str, Any] = {
                    "request_id": "req-1",
                    "purpose": purpose,
                    "question": "合成问题 " + SENTINEL,
                    "context_questions": [],
                    "context_entities": {},
                }
                if not opts.get("model_input_without_evidence"):
                    payload["evidence"] = copy.deepcopy(evidence_rows)
                add("model_input", payload)
            if model_mode in ("pair", "output_only"):
                add(
                    "model_output",
                    {
                        "request_id": "req-1",
                        "purpose": purpose,
                        "status": "ok",
                        "text": None,
                        "source_ids": list(model_output_source_ids),
                        "query_terms": [],
                        "provider_request_id": None,
                        "usage": None,
                        "error_code": None,
                        "retryable": False,
                    },
                )
        duplicate_purpose = opts.get("duplicate_model_purpose")
        if duplicate_purpose is not None:
            purpose = str(duplicate_purpose)
            if model_mode in ("pair", "input_only"):
                add(
                    "model_input",
                    {
                        "request_id": "req-1",
                        "purpose": purpose,
                        "question": "合成问题 " + SENTINEL,
                        "context_questions": [],
                        "context_entities": {},
                        "evidence": copy.deepcopy(evidence_rows),
                    },
                )
            if model_mode in ("pair", "output_only"):
                add(
                    "model_output",
                    {
                        "request_id": "req-1",
                        "purpose": purpose,
                        "status": "ok",
                        "text": None,
                        "source_ids": list(model_output_source_ids),
                        "query_terms": [],
                        "provider_request_id": None,
                        "usage": None,
                        "error_code": None,
                        "retryable": False,
                    },
                )

    omit_events = set(opts.get("omit_events", ()))
    if omit_events:
        events = [event for event in events if event["kind"] not in omit_events]
    duplicate_event = opts.get("duplicate_event")
    if duplicate_event:
        source = next((event for event in events if event["kind"] == duplicate_event), None)
        if source is not None:
            events.append(copy.deepcopy(source))
    extra_event = opts.get("extra_event")
    if extra_event is not None:
        events.append(copy.deepcopy(dict(extra_event)))

    for index, event in enumerate(events, start=1):
        event["seq"] = index

    # 投影：多轮上下文 + 当前 user/assistant 消息。
    context_messages = list(opts.get("context_messages", ()))
    message_rows = [
        _message_row(
            str(item.get("id", "ctx")),
            role=str(item.get("role", "user")),
            seq=int(item.get("seq", 1)),
            kind=item.get("kind"),
            text=str(item.get("text", "合成历史消息 " + SENTINEL)),
        )
        for item in context_messages
    ]
    message_rows.append(_message_row("msg-user", role="user", seq=len(message_rows) + 1, text="合成问题 " + SENTINEL))
    message_rows.append(
        _message_row(
            "msg-assistant",
            role="assistant",
            seq=len(message_rows) + 1,
            kind=commit_kind,
            text=commit_text,
        )
    )

    projection_units = tuple(str(item) for item in opts.get("projection_units", ()))
    projection_unresolved = tuple(str(item) for item in opts.get("projection_unresolved", ()))
    projection_message_sources = tuple(
        str(item) for item in opts.get("projection_message_sources", ())
    )
    query_state_candidates = opts.get("query_state_candidates")
    query_state_rows: list[dict[str, Any]] = []
    if query_state_candidates is not None:
        state_json: dict[str, Any] = (
            {} if opts.get("query_state_empty_state") else {"candidates": list(query_state_candidates)}
        )
        query_state_rows.append(
            {
                "stored_user_id": "user-1",
                "stored_conversation_id": "conv-1",
                "state_json": state_json,
                "keys": sorted(state_json),
            }
        )

    projection: dict[str, Any] = {
        "schema_version": "p2-hard-evidence-capture-db/v0.1",
        "snapshot_utc": "2026-11-13T00:00:01+00:00",
        "pre_revision": 1,
        "capture_revision": 1,
        "conversation": {
            "id": "conv-1",
            "owner_user_id": "user-1",
            "deleted": False,
            "deleted_at": None,
            "created_at": "2026-11-13T00:00:00+00:00",
            "updated_at": "2026-11-13T00:00:00+00:00",
        },
        "request": {
            "id": "req-1",
            "conversation_id": "conv-1",
            "user_id": "user-1",
            "status": "succeeded",
            "attempt": 1,
            "payload_sha256": "0" * 64,
            "user_message_id": "msg-user",
            "result_message_id": "msg-assistant",
            "error_code": None,
            "error_retryable": False,
            "created_at": "2026-11-13T00:00:00+00:00",
            "started_at": "2026-11-13T00:00:00+00:00",
            "finished_at": "2026-11-13T00:00:01+00:00",
        },
        "messages": message_rows,
        "message_sources": [
            {
                "message_id": "msg-assistant",
                "source_id": source_id,
                "document_id": "doc-1",
                "version_id": "ver-1",
            }
            for source_id in projection_message_sources
        ],
        "units": [_unit_row(unit_id) for unit_id in projection_units],
        "unresolved_unit_ids": [
            {"unit_id": unit_id, "reason": "unit_not_found"} for unit_id in projection_unresolved
        ],
        "query_states": query_state_rows,
        "query_states_available": bool(opts.get("query_states_available", True)),
        "rag_business_date": "2026-11-13",
        "truncations": list(opts.get("projection_truncations", ())),
        "errors": list(opts.get("projection_errors", ())),
    }

    runtime_snapshot = opts.get("runtime_snapshot")
    schema_version = opts.get("schema_version")
    if schema_version is None:
        schema_version = (
            "p2-hard-evidence-capture/v0.3"
            if runtime_snapshot is not None
            else "p2-hard-evidence-capture/v0.1"
        )
    capture = {
        "schema_version": str(schema_version),
        "sink_id": "sink-1",
        "status": "ok",
        "seq": len(events),
        "event_count": len(events),
        "events": events,
        "errors": list(opts.get("capture_errors", ())),
    }
    envelope: dict[str, Any] = {
        "schema_version": str(schema_version),
        "fixture_kind": str(opts.get("fixture_kind", "local_mock")),
        "bindings": {},
        "adapter_components": {},
        "turn": _turn_payload(),
        "capture": capture,
        "db_projection": projection,
        "completeness": {"status": str(opts.get("completeness_status", "complete"))},
        "sealed": {},
    }
    if runtime_snapshot is not None:
        envelope["runtime_snapshot"] = copy.deepcopy(dict(runtime_snapshot))

    capture_value = opts.get("capture_value", _MISSING)
    if capture_value is not _MISSING:
        envelope["capture"] = capture_value
    projection_value = opts.get("projection_value", _MISSING)
    if projection_value is not _MISSING:
        envelope["db_projection"] = projection_value
    turn_value = opts.get("turn_value", _MISSING)
    if turn_value is not _MISSING:
        envelope["turn"] = turn_value
    completeness_value = opts.get("completeness_value", _MISSING)
    if completeness_value is not _MISSING:
        envelope["completeness"] = completeness_value

    for key in opts.get("omit_envelope", ()):
        envelope.pop(str(key), None)
    for key in opts.get("omit_capture", ()):
        if isinstance(envelope.get("capture"), dict):
            envelope["capture"].pop(str(key), None)
    for key in opts.get("omit_projection", ()):
        if isinstance(envelope.get("db_projection"), dict):
            envelope["db_projection"].pop(str(key), None)
    for key, value in dict(opts.get("extra_envelope") or {}).items():
        envelope[str(key)] = value
    for key, value in dict(opts.get("extra_capture") or {}).items():
        if isinstance(envelope.get("capture"), dict):
            envelope["capture"][str(key)] = value
    for key, value in dict(opts.get("extra_projection") or {}).items():
        if isinstance(envelope.get("db_projection"), dict):
            envelope["db_projection"][str(key)] = value
    return envelope


# --------------------------------------------------------------------------- #
# 差分语料
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Case:
    name: str
    evidence: dict[str, Any]
    expect_proven: bool
    divergence: str | None = None
    stricter: bool = False
    note: str = ""


@functools.lru_cache(maxsize=1)
def _corpus() -> list[_Case]:
    clarification_base = _no_fact_text("clarification")
    clarification_with_suffix = clarification_base + clarification_candidates_text(["候选甲", "候选乙"])
    history = (
        {"id": "ctx-1", "role": "user", "seq": 1, "text": "合成历史问题一 " + SENTINEL},
        {"id": "ctx-2", "role": "assistant", "seq": 2, "text": "合成历史回答一 " + SENTINEL},
    )
    default = build_evidence()
    cases: list[_Case] = [
        # ---- 冻结原语可证明：等价 proven ----
        _Case("legacy_no_model_retrieval_empty", default, True),
        _Case(
            "legacy_model_answer_no_retrieval",
            build_evidence(model_purposes=("answer",), retrieval_present=False),
            True,
        ),
        _Case(
            "legacy_model_answer_retrieval_empty",
            build_evidence(model_purposes=("answer",)),
            True,
        ),
        _Case(
            "rag_direct_empty",
            build_evidence(plan_path="rag", model_purposes=()),
            True,
        ),
        _Case(
            "rag_query_expansion_empty",
            build_evidence(plan_path="rag", model_purposes=("query_expansion",)),
            True,
        ),
        _Case(
            "clarification_template_suffix",
            build_evidence(kind="clarification", text=clarification_with_suffix),
            True,
        ),
        _Case(
            "clarification_template_base",
            build_evidence(kind="clarification", text=clarification_base),
            True,
        ),
        _Case("knowledge_changed_template", build_evidence(kind="knowledge_changed"), True),
        _Case(
            "projection_query_state_empty_candidates",
            build_evidence(query_state_candidates=()),
            True,
        ),
        _Case(
            "projection_query_state_empty_state",
            build_evidence(query_state_candidates=(), query_state_empty_state=True),
            True,
        ),
        _Case(
            "context_history_no_usage",
            build_evidence(context_messages=history),
            True,
        ),
        _Case(
            "template_whitespace_normalized",
            build_evidence(
                text=_no_fact_text("not_found")[:8] + " \n\t " + _no_fact_text("not_found")[8:]
            ),
            True,
        ),
        # ---- 冻结原语不可证明：等价 not proven ----
        _Case("factual_answer_kind", build_evidence(kind="answer", text="合成事实回答"), False),
        _Case(
            "legacy_no_model_no_retrieval_no_marker",
            build_evidence(retrieval_present=False),
            False,
        ),
        _Case(
            "model_input_without_output",
            build_evidence(model_purposes=("answer",), model_mode="input_only"),
            False,
        ),
        _Case(
            "model_output_without_input",
            build_evidence(model_purposes=("answer",), model_mode="output_only"),
            False,
        ),
        _Case(
            "duplicate_model_answer",
            build_evidence(model_purposes=("answer",), duplicate_model_purpose="answer"),
            False,
        ),
        _Case(
            "legacy_query_expansion_model",
            build_evidence(model_purposes=("query_expansion",)),
            False,
        ),
        _Case(
            "rag_answer_model",
            build_evidence(plan_path="rag", model_purposes=("answer",)),
            False,
        ),
        _Case(
            "rag_missing_direct_rag",
            build_evidence(plan_path="rag", model_purposes=(), omit_direct_rag=True),
            False,
        ),
        _Case(
            "legacy_with_direct_rag",
            build_evidence(direct_rag={"kind": "not_found", "text": _no_fact_text("not_found")}),
            False,
        ),
        _Case(
            "retrieval_candidate_used_in_model",
            build_evidence(
                model_purposes=("answer",),
                retrieval_unit_ids=("u1",),
                model_evidence_ids=("u1",),
                projection_units=("u1",),
            ),
            False,
        ),
        _Case(
            "retrieval_candidate_used_in_final",
            build_evidence(
                retrieval_unit_ids=("u1",),
                final_source_ids=("u1",),
                projection_units=("u1",),
            ),
            False,
        ),
        _Case(
            "message_sources_nonempty",
            build_evidence(projection_message_sources=("u1",)),
            False,
        ),
        _Case(
            "projection_unit_usage",
            build_evidence(
                model_purposes=("answer",),
                model_evidence_ids=("u1",),
                projection_units=("u1",),
            ),
            False,
        ),
        _Case(
            "projection_unresolved_usage",
            build_evidence(
                model_purposes=("answer",),
                model_evidence_ids=("u1",),
                projection_unresolved=("u1",),
            ),
            False,
        ),
        _Case("template_mismatch", build_evidence(text="合成任意非模板文本"), False),
        _Case(
            "commit_answer_text_mismatch",
            build_evidence(commit_text="合成任意不一致文本"),
            False,
        ),
        _Case(
            "commit_answer_kind_mismatch",
            build_evidence(answer_kind="not_found", commit_kind="no_answer"),
            False,
        ),
        _Case("unknown_envelope_key", build_evidence(extra_envelope={"extra": 1}), False),
        _Case("unknown_capture_key", build_evidence(extra_capture={"extra": 1}), False),
        _Case(
            "unknown_event_key",
            build_evidence(
                extra_event={
                    "seq": 99,
                    "kind": "retrieval_observed",
                    "payload": {
                        "request_id": "req-1",
                        "scope": "legacy_retrieve_initial",
                        "unit_ids": [],
                        "candidate": False,
                        "truncated": False,
                        "empty": True,
                    },
                    "extra": 1,
                }
            ),
            False,
        ),
        _Case(
            "unknown_event_field",
            build_evidence(
                extra_event={
                    "seq": 99,
                    "kind": "retrieval_observed",
                    "payload": {
                        "request_id": "req-1",
                        "scope": "legacy_retrieve_initial",
                        "unit_ids": [],
                        "candidate": False,
                        "truncated": False,
                        "empty": True,
                        "extra": 1,
                    },
                }
            ),
            False,
        ),
        _Case("unknown_projection_key", build_evidence(extra_projection={"extra": 1}), False),
        _Case(
            "unknown_projection_row_key",
            _with_projection_row_extra(
                build_evidence(projection_units=("u1",), retrieval_unit_ids=("u1",))
            ),
            False,
        ),
        _Case("missing_projection_units", build_evidence(omit_projection=("units",)), False),
        _Case("missing_capture_errors", build_evidence(omit_capture=("errors",)), False),
        _Case(
            "capture_errors_present",
            build_evidence(capture_errors=({"stage": "capture", "code": "x", "detail": "y"},)),
            False,
        ),
        _Case(
            "projection_truncations_present",
            build_evidence(projection_truncations=("messages_limit",)),
            False,
        ),
        _Case(
            "projection_errors_present",
            build_evidence(projection_errors=("projection_id_invalid",)),
            False,
        ),
        _Case("query_states_unavailable", build_evidence(query_states_available=False), False),
        _Case("missing_completeness", build_evidence(omit_envelope=("completeness",)), False),
        _Case(
            "completeness_incomplete",
            build_evidence(completeness_status="incomplete"),
            False,
        ),
        _Case("missing_required_event", build_evidence(omit_events=("commit_observed",)), False),
        _Case("duplicate_required_event", build_evidence(duplicate_event="answer_result"), False),
        _Case(
            "model_input_missing_evidence",
            build_evidence(model_purposes=("answer",), model_input_without_evidence=True),
            False,
        ),
        _Case(
            "direct_rag_fact_count_mismatch",
            build_evidence(plan_path="rag", model_purposes=(), direct_rag_fact_count=1),
            False,
        ),
        _Case(
            "direct_rag_facts_nonempty",
            build_evidence(
                plan_path="rag",
                model_purposes=(),
                direct_rag_facts=(_fact_row("u1"),),
            ),
            False,
        ),
        _Case(
            "model_output_sources_nonempty",
            build_evidence(model_purposes=("answer",), model_output_source_ids=("u1",)),
            False,
        ),
        _Case("answer_sources_nonempty", build_evidence(answer_source_ids=("u1",)), False),
        _Case("commit_sources_nonempty", build_evidence(commit_source_ids=("u1",)), False),
        _Case(
            "retrieval_blank_unit_id",
            build_evidence(retrieval_unit_ids=("   ",)),
            False,
        ),
        _Case(
            "query_state_candidates_used",
            build_evidence(
                model_purposes=("answer",),
                model_evidence_ids=("u1",),
                query_state_candidates=("u1",),
            ),
            False,
        ),
        _Case("capture_error_event", build_evidence(capture_error_event=True), False),
        _Case(
            "plan_unknown_path",
            build_evidence(plan_path="other", retrieval_present=False),
            False,
        ),
        _Case("missing_turn", build_evidence(turn_value=None), False),
        _Case("missing_capture", build_evidence(capture_value=None), False),
        _Case("missing_projection", build_evidence(projection_value=None), False),
        _Case(
            "unattributable_projection_unit",
            build_evidence(projection_units=("u1",)),
            False,
        ),
        _Case(
            "entity_inheritance_usage_with_projection_row",
            build_evidence(
                model_purposes=("answer",),
                entity_inheritance_ids=("u1",),
                projection_units=("u1",),
            ),
            False,
        ),
        # ---- 本实现覆盖、冻结原语不可用：扩展 proven（固定码 + 理由） ----
        _Case(
            "retrieval_candidates_unused_legacy_no_model",
            build_evidence(retrieval_unit_ids=("u1",), projection_units=("u1",)),
            True,
            FROZEN_CANDIDATE_LAYER_CODE,
        ),
        _Case(
            "retrieval_candidates_unused_legacy_model",
            build_evidence(
                model_purposes=("answer",),
                retrieval_unit_ids=("u1",),
                projection_units=("u1",),
            ),
            True,
            FROZEN_CANDIDATE_LAYER_CODE,
        ),
        _Case(
            "retrieval_candidates_unused_rag",
            build_evidence(
                plan_path="rag",
                model_purposes=(),
                retrieval_unit_ids=("u1",),
                projection_units=("u1",),
            ),
            True,
            FROZEN_CANDIDATE_LAYER_CODE,
        ),
        _Case(
            "retrieval_candidates_unused_clarification",
            build_evidence(
                kind="clarification",
                text=clarification_with_suffix,
                model_purposes=("answer",),
                retrieval_unit_ids=("u1",),
                projection_units=("u1",),
            ),
            True,
            FROZEN_CANDIDATE_LAYER_CODE,
        ),
        _Case(
            "retrieval_candidates_unused_no_answer",
            build_evidence(
                kind="no_answer",
                retrieval_unit_ids=("u1",),
                projection_units=("u1",),
            ),
            True,
            FROZEN_CANDIDATE_LAYER_CODE,
        ),
        _Case(
            "retrieval_candidates_unused_with_unresolved",
            build_evidence(
                retrieval_unit_ids=("u1", "u2"),
                projection_units=("u1",),
                projection_unresolved=("u2",),
            ),
            True,
            FROZEN_CANDIDATE_LAYER_CODE,
        ),
        _Case(
            "retrieval_candidates_unused_knowledge_changed",
            build_evidence(
                kind="knowledge_changed",
                retrieval_unit_ids=("u1",),
                projection_units=("u1",),
            ),
            True,
            FROZEN_CANDIDATE_LAYER_CODE,
        ),
        _Case(
            "query_state_candidates_unused",
            build_evidence(
                model_purposes=("answer",),
                query_state_candidates=("u-prior",),
            ),
            True,
            FROZEN_QUERY_STATE_CODE,
        ),
        _Case(
            "multi_turn_partial_empty",
            build_evidence(
                model_purposes=("answer",),
                retrieval_unit_ids=("u-now",),
                projection_units=("u-now",),
                query_state_candidates=("u-prior",),
                context_messages=history,
            ),
            True,
            FROZEN_QUERY_STATE_CODE,
        ),
        _Case(
            "no_retrieval_positive_snapshot_legacy_no_model",
            build_evidence(retrieval_present=False, runtime_snapshot=_no_retrieval_snapshot()),
            True,
            FROZEN_NO_RETRIEVAL_CODE,
        ),
        _Case(
            "no_retrieval_positive_snapshot_with_context",
            build_evidence(
                retrieval_present=False,
                runtime_snapshot=_no_retrieval_snapshot(),
                context_messages=history,
            ),
            True,
            FROZEN_NO_RETRIEVAL_CODE,
        ),
        # ---- 本实现更严（冻结原语漏计实体继承）：stricter ----
        _Case(
            "entity_inheritance_without_projection_row",
            build_evidence(model_purposes=("answer",), entity_inheritance_ids=("u1",)),
            False,
            FROZEN_INHERITANCE_CODE,
            stricter=True,
        ),
    ]
    return cases


def _case_map() -> dict[str, _Case]:
    return {case.name: case for case in _corpus()}


# --------------------------------------------------------------------------- #
# 测试
# --------------------------------------------------------------------------- #


def test_frozen_module_sha_is_expected() -> None:
    assert _sha256_file(FROZEN_MODULE) == FROZEN_SHA


def test_module_does_not_import_frozen_implementation() -> None:
    source = Path(proof.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    forbidden = ("p2_hard_evidence", "p2_evidence_capture", "p2_evidence_io")
    for module_name in imported:
        for name in forbidden:
            assert name not in module_name, (module_name, name)


def test_module_import_does_not_load_providers_or_frozen_modules() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MKTKB_NO_DOTENV"] = "1"
    src = str(ROOT / "backend" / "src")
    code = (
        "import importlib\n"
        "import sys\n"
        "import types\n"
        f"src = {src!r}\n"
        "sys.path.insert(0, src)\n"
        "pkg = types.ModuleType('mktkb')\n"
        "pkg.__path__ = [src + '/mktkb']\n"
        "sys.modules['mktkb'] = pkg\n"
        "m = importlib.import_module('mktkb.evaluation.p2_empty_scope_proof')\n"
        "bad = sorted(\n"
        "    name for name in sys.modules\n"
        "    if name.startswith('mktkb.providers')\n"
        "    or name in {\n"
        "        'mktkb.evaluation.p2_hard_evidence',\n"
        "        'mktkb.evaluation.p2_evidence_capture',\n"
        "        'mktkb.evaluation.p2_evidence_io',\n"
        "    }\n"
        ")\n"
        "assert not bad, bad\n"
        "print('ok')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=ROOT / "backend",
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


@pytest.mark.parametrize("case", [case for case in _corpus() if case.expect_proven], ids=lambda case: case.name)
def test_proven_cases(case: _Case) -> None:
    result = prove_empty_use_scope(case.evidence)
    assert result.proven is True, result.as_dict()
    assert result.code == EMPTY_USE_SCOPE_OK
    assert result.usage_layers == ()
    assert SENTINEL not in json.dumps(result.as_dict(), ensure_ascii=False)
    frozen_proven, frozen_reason = _empty_use_scope_proof(case.evidence)
    if not frozen_proven:
        assert case.divergence in DIVERGENCE_REASONS, case.name
        assert case.stricter is False
        assert frozen_reason in FROZEN_REASONS


@pytest.mark.parametrize(
    "case", [case for case in _corpus() if not case.expect_proven], ids=lambda case: case.name
)
def test_not_proven_cases(case: _Case) -> None:
    result = prove_empty_use_scope(case.evidence)
    assert result.proven is False, result.as_dict()
    assert result.code == EMPTY_SET_NOT_PROVEN
    assert SENTINEL not in json.dumps(result.as_dict(), ensure_ascii=False)
    frozen_proven, frozen_reason = _empty_use_scope_proof(case.evidence)
    assert frozen_reason in FROZEN_REASONS
    if frozen_proven:
        assert case.stricter is True, case.name
        assert case.divergence == FROZEN_INHERITANCE_CODE


def test_differential_against_frozen_primitive() -> None:
    before = _sha256_file(FROZEN_MODULE)
    assert before == FROZEN_SHA
    summary = {
        "equivalent_proven": 0,
        "equivalent_not_proven": 0,
        "extension_proven": 0,
        "stricter_not_proven": 0,
    }
    uncoded: list[str] = []
    rows: list[dict[str, Any]] = []
    for case in _corpus():
        ours = prove_empty_use_scope(case.evidence)
        frozen_proven, frozen_reason = _empty_use_scope_proof(case.evidence)
        assert ours.proven == case.expect_proven, case.name
        assert frozen_reason in FROZEN_REASONS, (case.name, frozen_reason)
        if ours.proven == frozen_proven:
            assert case.divergence is None, case.name
            key = "equivalent_proven" if ours.proven else "equivalent_not_proven"
            summary[key] += 1
            verdict = "equal"
        elif ours.proven and not frozen_proven:
            if case.divergence not in DIVERGENCE_REASONS:
                uncoded.append(case.name)
            assert case.stricter is False
            summary["extension_proven"] += 1
            verdict = "extension"
        else:
            if case.divergence not in DIVERGENCE_REASONS:
                uncoded.append(case.name)
            assert case.stricter is True, case.name
            summary["stricter_not_proven"] += 1
            verdict = "stricter"
        rows.append(
            {
                "case": case.name,
                "ours_proven": ours.proven,
                "ours_code": ours.code,
                "ours_shape": ours.shape,
                "frozen_proven": frozen_proven,
                "frozen_reason": frozen_reason,
                "verdict": verdict,
                "divergence_code": case.divergence,
                "divergence_reason": DIVERGENCE_REASONS.get(case.divergence or ""),
            }
        )
    assert uncoded == [], uncoded
    assert summary["extension_proven"] > 0
    assert summary["stricter_not_proven"] == 1
    assert summary["equivalent_proven"] > 0
    assert summary["equivalent_not_proven"] > 0
    after = _sha256_file(FROZEN_MODULE)
    assert after == before == FROZEN_SHA
    # 结果表只用于本测试内存断言；evidence/ 下的差分探针会生成可审计 JSON。
    assert all(row["ours_code"] in {EMPTY_USE_SCOPE_OK, EMPTY_SET_NOT_PROVEN} for row in rows)


def test_shape_coverage() -> None:
    results = [prove_empty_use_scope(case.evidence) for case in _corpus()]
    branches = {result.branch for result in results}
    retrievals = {result.retrieval for result in results}
    outcome_classes = {result.outcome_class for result in results}
    assert branches == set(proof.BRANCH_SHAPES)
    assert retrievals == set(proof.RETRIEVAL_SHAPES)
    assert outcome_classes == set(proof.OUTCOME_CLASSES)


def test_fail_closed_for_unknown_or_missing_shapes() -> None:
    for value in (None, [], {}, "not-a-mapping", 0):
        result = prove_empty_use_scope(value)
        assert result.proven is False
        assert result.code == EMPTY_SET_NOT_PROVEN


def test_entrypoint_matches_frozen_pair_shape() -> None:
    assert empty_use_scope_proof(build_evidence()) == (True, EMPTY_USE_SCOPE_OK)
    assert empty_use_scope_proof(build_evidence(text="合成任意非模板文本")) == (
        False,
        EMPTY_SET_NOT_PROVEN,
    )


def test_adapter_and_rich_proof_agree_on_all_cases() -> None:
    for case in _corpus():
        rich = prove_empty_use_scope(case.evidence)
        assert empty_use_scope_proof(case.evidence) == (rich.proven, rich.code), case.name


def test_no_retrieval_requires_positive_marker() -> None:
    without_marker = prove_empty_use_scope(build_evidence(retrieval_present=False))
    assert without_marker.proven is False
    assert without_marker.detail == "legacy_no_model_without_retrieval_or_positive_no_retrieval_marker"
    with_marker = prove_empty_use_scope(
        build_evidence(retrieval_present=False, runtime_snapshot=_no_retrieval_snapshot())
    )
    assert with_marker.proven is True
    assert with_marker.retrieval == "retrieval_absent"
    malformed = prove_empty_use_scope(
        build_evidence(
            retrieval_present=False,
            runtime_snapshot={"schema_version": "p2-runtime-snapshot/v0.1", "retrieval_use": {}},
        )
    )
    assert malformed.proven is False


def test_retrieval_unused_is_proven_only_when_usage_layers_are_explicitly_empty() -> None:
    unused = prove_empty_use_scope(
        build_evidence(retrieval_unit_ids=("u1",), projection_units=("u1",))
    )
    assert unused.proven is True
    assert unused.retrieval == "retrieval_candidates_unused"
    used = prove_empty_use_scope(
        build_evidence(
            model_purposes=("answer",),
            retrieval_unit_ids=("u1",),
            model_evidence_ids=("u1",),
            projection_units=("u1",),
        )
    )
    assert used.proven is False
    assert "model_evidence" in used.usage_layers
    assert used.code == EMPTY_SET_NOT_PROVEN


def test_query_state_candidates_are_candidates_not_usage() -> None:
    result = prove_empty_use_scope(
        build_evidence(model_purposes=("answer",), query_state_candidates=("u-prior",))
    )
    assert result.proven is True
    assert "projection_query_state_candidates" in result.candidate_sources
    assert result.usage_layers == ()


def test_entity_inheritance_is_conservatively_usage() -> None:
    result = prove_empty_use_scope(
        build_evidence(model_purposes=("answer",), entity_inheritance_ids=("u1",))
    )
    assert result.proven is False
    assert "entity_inheritance" in result.usage_layers
    frozen_proven, _ = _empty_use_scope_proof(
        build_evidence(model_purposes=("answer",), entity_inheritance_ids=("u1",))
    )
    assert frozen_proven is True


def test_unknown_projection_row_key_fails_closed() -> None:
    envelope = build_evidence(retrieval_unit_ids=("u1",), projection_units=("u1",))
    envelope["db_projection"]["units"][0]["extra"] = 1
    result = prove_empty_use_scope(envelope)
    assert result.proven is False
    assert result.code == EMPTY_SET_NOT_PROVEN
    frozen_proven, frozen_reason = _empty_use_scope_proof(envelope)
    assert frozen_proven is False
    assert frozen_reason in FROZEN_REASONS


def test_bad_event_payload_type_fails_closed() -> None:
    envelope = build_evidence(retrieval_unit_ids=("u1",), projection_units=("u1",))
    for event in envelope["capture"]["events"]:
        if event["kind"] == "retrieval_observed":
            event["payload"]["unit_ids"] = "u1"
            break
    result = prove_empty_use_scope(envelope)
    assert result.proven is False
    assert result.code == EMPTY_SET_NOT_PROVEN
    frozen_proven, _ = _empty_use_scope_proof(envelope)
    assert frozen_proven is False


def test_evidence_with_private_sentinel_does_not_leak_into_proof() -> None:
    envelope = build_evidence(
        plan_path="rag",
        model_purposes=(),
        retrieval_unit_ids=("u1",),
        projection_units=("u1",),
    )
    envelope["capture"]["events"].append(
        {
            "seq": 999,
            "kind": "capture_error",
            "payload": {
                "stage": SENTINEL,
                "code": SENTINEL,
                "request_id": "req-1",
                "detail": SENTINEL,
            },
        }
    )
    result = prove_empty_use_scope(envelope)
    assert result.proven is False
    assert SENTINEL not in json.dumps(result.as_dict(), ensure_ascii=False)


def test_explicit_zero_external_network(t09_network_guard: Any) -> None:
    prove_empty_use_scope(build_evidence())
    assert t09_network_guard.snapshot()["external"] == []
