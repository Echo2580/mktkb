"""Q1a-3-R1 共享投影层：真实 H2 只读证据 -> Q1a-1 / Q1a-1b 的显式只读视图。

边界（硬约束）：
- 只经既有受控 loader 解封：`tools/p2_h2_controlled_execute.py::load_private_bundle`、
  `p2_dataset.load_p2_dataset`、`p2_holdout_scenarios.load_scenario_contract`、
  `p2_evidence_io.read_encrypted_evidence`。key 只在进程内存。
- 只投影确定性结构字段（身份/owner/版本/日期/实体/引用/状态码/计数）。
  `final_text` 仅供 Q1a-1 已定义的**确定性禁值子串判定**使用，绝不打印/落盘/公开/回传。
- **不构造 `OldCardCase`**：旧逐题四轴值在本包标 `NOT_AVAILABLE`；本层只产出新侧视图。
- 所有适配点做**显式 required 校验**（缺键/坏类型 -> 固定 ProjectionError 码），
  禁止 `getattr(..., default)` 式 fail-open。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

REPO = Path(r"D:\GPT项目\市场部AI知识库")
CUSTODY = Path(
    r"C:\Users\dell1712\.codex\visualizations\2026\11\12\01a1cd24-bccf-7e00-80df-0b75f57f7d1c\t207-custody"
)
HOLDOUT_ROOT = Path(r"D:\mktkb-p2-holdout\v2")
HOLDOUT_KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
OLD_RUN = Path(r"D:\mktkb-p2-t207-h2-20261114")
CONTRACT_CIPHER = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v1.fernet")
OUT_PRIVATE_DIR = Path(r"D:\mktkb-q1a3-rescore")
OUT_PRIVATE_FILE = OUT_PRIVATE_DIR / "rescore-detail-r1.fernet"

#: 本包固定期望值（逐字节绑定；不一致即停）。
EXPECTED = {
    "contract_ciphertext_sha256": "467dbf7706df26f2069a79e2b344b53c0e10c03ff830ed62efff9b5dfd16f461",
    "contract_ciphertext_bytes": 47012,
    "contract_schema_sha256": "cb1257fac56a68e5eef791c23cffba9d4e915e5e9a840abce7bde5b96e0e4690",
    "q1a1_module_sha256": "d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9",
    "q1a1_contract_sha256": "e0487f256524558ae12b00e6a9d961a7360e92f1437ab4d7d0c55702f375588d",
    "q1a1b_module_sha256": "57495943c763977e62fa7acded407e99ba360336fc5ee8c822f5e084f200f08e",
    "q1a1b_contract_sha256": "747e3656bfbaf0bb4f0e40444d96d20d2b30806d80d061fbca13b962a46c8db5",
    "old_run_binding_payload_sha256": "291cfec9d99446c88f0063d533c92632cef15594c1f6ce3da2269cef98ae65d4",
    "hard_evidence_module_sha256": "fba6e606991cd4bcf06f9e2ef1a50b60fd5d302979844a53de3bfb45a843529b",
    "analysis_id": "Q1A-RESCORE-20261114-r1",
    "case_count": 30,
    "turn_count": 36,
    "business_date": "2026-10-28",
}

#: 合同 18 码权威 reason 表（manager acceptance R-Q1A2-01：文档写「19 码」为笔误）。
AUTHORITATIVE_REASON_CODES_18 = (
    "explicit_security",
    "explicit_privacy",
    "prompt_injection",
    "explicit_forbidden",
    "benign_business",
    "all_user_contexts",
    "explicit_single_target",
    "explicit_multi_target",
    "shared_policy",
    "no_entity_scope",
    "published_lifecycle",
    "explicit_temporal",
    "business_date_default",
    "ambiguous_semantics",
    "unresolved_target",
    "source_state_conflict",
    "third_state_required",
    "insufficient_annotation",
)


class ProjectionError(RuntimeError):
    """固定错误码；消息只含码，不含输入值（防注入/防泄漏）。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def need(condition: Any, code: str) -> None:
    if not condition:
        raise ProjectionError(code)


def need_map(value: Any, code: str) -> Mapping[str, Any]:
    need(isinstance(value, Mapping), code)
    return value


def need_list(value: Any, code: str) -> list[Any]:
    need(isinstance(value, (list, tuple)), code)
    return list(value)


def need_str(value: Any, code: str) -> str:
    need(isinstance(value, str) and bool(value.strip()), code)
    return str(value)


def need_opt_str(value: Any, code: str) -> str | None:
    if value is None:
        return None
    need(isinstance(value, str), code)
    text = str(value)
    return text if text.strip() else None


def need_int(value: Any, code: str, *, minimum: int | None = None) -> int:
    need(type(value) is int, code)
    if minimum is not None:
        need(value >= minimum, code)
    return int(value)


def need_bool(value: Any, code: str) -> bool:
    need(isinstance(value, bool), code)
    return bool(value)


def sha256_hex(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def strict_json(raw: bytes) -> Any:
    """严格 JSON：拒绝重复键、非 UTF-8、NaN/Infinity。"""

    def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise ProjectionError("strict_json_duplicate_key")
            out[key] = value
        return out

    def _const(name: str) -> Any:
        raise ProjectionError("strict_json_bad_constant")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectionError("strict_json_not_utf8") from exc
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_const)


def load_bundle() -> Any:
    """既有受控入口：`load_private_bundle`（内部 load_p2_dataset + load_scenario_contract）。"""
    import sys

    for path in (REPO / "tools", REPO / "backend" / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import p2_h2_controlled_execute as entry

    paths = entry.InputPaths(
        holdout_manifest=HOLDOUT_ROOT / "manifest.json",
        annotation_ciphertext=CUSTODY / "annotations-v0_2.fernet",
        review_ciphertext=CUSTODY / "review-v0_2.fernet",
        scenario_key_file=HOLDOUT_KEY,
        addendum_ciphertext=CUSTODY / "annotations-gapaddendum-v0_3.fernet",
        scenario_contract=entry.DEFAULT_SCENARIO_CONTRACT,
        ingest_plan=entry.DEFAULT_INGEST_PLAN,
        source_map=entry.DEFAULT_SOURCE_MAP,
        annotation_schema=entry.DEFAULT_ANNOTATION_SCHEMA,
        manager_acceptance_v2=entry.DEFAULT_MANAGER_V2,
        review_aggregate_v2=entry.DEFAULT_REVIEW_AGGREGATE_V2,
        addendum_acceptance_v3=entry.DEFAULT_ADDENDUM_ACCEPTANCE,
    )
    runtime = entry.RuntimeOptions(
        holdout_root=HOLDOUT_ROOT,
        holdout_key_file=HOLDOUT_KEY,
        project_total_limit_cny=entry.PROJECT_TOTAL_LIMIT_CNY,
    )
    return entry.load_private_bundle({}, paths, runtime=runtime)


def load_contract_payload() -> tuple[dict[str, Any], dict[str, Any]]:
    """复用既有 key 容器在进程内解密合同；返回 (payload, fact)。不打印明文。"""
    from cryptography.fernet import Fernet

    raw = CONTRACT_CIPHER.read_bytes()
    fact = {"path": str(CONTRACT_CIPHER), "sha256": sha256_hex(raw), "bytes": len(raw)}
    need(fact["sha256"] == EXPECTED["contract_ciphertext_sha256"], "contract_ciphertext_sha_mismatch")
    need(fact["bytes"] == EXPECTED["contract_ciphertext_bytes"], "contract_ciphertext_bytes_mismatch")
    key = HOLDOUT_KEY.read_bytes()
    try:
        plaintext = Fernet(key).decrypt(raw)
    except Exception as exc:  # noqa: BLE001 - 解密失败统一固定码
        raise ProjectionError("contract_decrypt_failed") from exc
    payload = strict_json(plaintext)
    need(isinstance(payload, dict), "contract_schema_invalid")
    return payload, fact


def document_codes_from_public_corpus() -> tuple[dict[str, str], dict[str, Any]]:
    """产品 `document_name` -> 数据集 `doc_code` 的**显式**映射。

    规则（只来自公开语料结构，不猜）：
    - `doc_code` 全集取自 source map 的 `base_doc_code`；
    - `document_name` 取自原 12-source ingest plan 的 `name` / `document_ref`（及 path basename）；
    - 名称前缀（首个 `_` 之前）必须落在 `doc_code` 全集内才建立映射，否则不映射（unresolved）。
    """
    source_map = strict_json((REPO / "docs/evaluation/p2-holdout-v2.source-map.json").read_bytes())
    ingest = strict_json(
        (REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json").read_bytes()
    )
    sources = need_map(source_map.get("sources"), "source_map_invalid")
    universe: set[str] = set()
    for _code, row in sources.items():
        entry = need_map(row, "source_map_invalid")
        universe.add(need_str(entry.get("base_doc_code"), "source_map_invalid"))
    names: set[str] = set()
    for row in need_list(ingest.get("sources"), "ingest_plan_invalid"):
        entry = need_map(row, "ingest_plan_invalid")
        for key in ("name", "document_ref"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                names.add(value.strip())
        path = entry.get("path")
        if isinstance(path, str) and path.strip():
            names.add(Path(path.replace("\\", "/")).name)
    mapping: dict[str, str] = {}
    for name in sorted(names):
        prefix = name.split("_", 1)[0]
        if prefix in universe:
            mapping[name] = prefix
    fact = {
        # 只记计数：doc_code 字面值可能与实体键同形，公开侧不落字面值。
        "doc_code_count": len(universe),
        "ingest_names": len(names),
        "mapped_names": len(mapping),
        "rule": "name_prefix_in_source_map_base_doc_code_universe",
    }
    return mapping, fact


# --------------------------------------------------------------------------- #
# 单回合投影
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TurnProjection:
    """一轮的只读投影（同时供 safety 与三轴使用）。"""

    turn_index: int
    status: str
    gate: str | None
    units: tuple[Any, ...]
    final_kind: str | None
    final_text: str | None
    events: tuple[Mapping[str, Any], ...] = ()
    projection: Mapping[str, Any] = field(default_factory=dict)
    envelope_bindings: Mapping[str, str] = field(default_factory=dict)
    completeness_status: str | None = None
    authenticated_user_id: str | None = None
    evidence_turn_index: int | None = None


def _unit_views(
    events: tuple[Mapping[str, Any], ...],
    projection: Mapping[str, Any],
    document_codes: Mapping[str, str],
) -> tuple[Any, ...]:
    from mktkb.evaluation.p2_evidence_rescore import UnitView, _used_layers

    rows = need_list(projection.get("units"), "projection_units_invalid")
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        entry = need_map(row, "projection_unit_invalid")
        unit_id = need_str(entry.get("unit_id"), "projection_unit_invalid")
        by_id[unit_id] = entry
    units: list[Any] = []
    for unit_id, layer_names in _used_layers(list(events)).items():
        row = by_id.get(unit_id, {})
        document_name = need_opt_str(row.get("document_name"), "projection_unit_invalid")
        unit_key = need_opt_str(row.get("unit_key"), "projection_unit_invalid")
        locator = row.get("locator")
        need(isinstance(locator, Mapping), "projection_unit_invalid")
        version_number = row.get("version_number")
        version_number = version_number if type(version_number) is int and version_number > 0 else None
        version_id = need_opt_str(row.get("version_id"), "projection_unit_invalid")
        document_id = need_opt_str(row.get("document_id"), "projection_unit_invalid")
        units.append(
            UnitView(
                unit_id=unit_id,
                layers=tuple(layer_names),
                document_id=document_id,
                document_name=document_name,
                doc_code=None if document_name is None else document_codes.get(document_name),
                version_id=version_id,
                version_number=version_number,
                unit_key=unit_key,
                record_code=None,  # 无冻结 unit_key->record_code 显式映射：保持 unresolved，不猜
                locator=dict(locator),
            )
        )
    return tuple(units)


def project_turn(
    envelope: Mapping[str, Any] | None,
    *,
    turn_index: int,
    status: str,
    document_codes: Mapping[str, str],
    evidence_turn_index: int | None = None,
) -> TurnProjection:
    """把一轮 envelope 投影成 `TurnProjection`（显式 required 校验，不 fail-open）。

    `turn_index` 是**题内**序号（Q1a-1 `TurnView` 要求 0..n-1 连续）；run 级全局回合号由
    `evidence_turn_index` 显式传入并逐值核对（case-plan 记录的全局号 == envelope 内值）。
    """
    from mktkb.evaluation.p2_evidence_rescore import _final_outcome

    need(type(turn_index) is int and turn_index >= 0, "case_plan_turn_invalid")
    need(status in ("executed", "error", "not_started"), "case_plan_turn_status_invalid")
    if status != "executed":
        need(envelope is None, "case_plan_turn_evidence_unexpected")
        return TurnProjection(
            turn_index, status, None, (), None, None, evidence_turn_index=evidence_turn_index
        )
    envelope = need_map(envelope, "evidence_envelope_missing")
    turn = need_map(envelope.get("turn"), "evidence_turn_missing")
    observed_index = need_int(turn.get("turn_index"), "evidence_turn_invalid", minimum=0)
    if evidence_turn_index is not None:
        need(type(evidence_turn_index) is int and evidence_turn_index >= 0, "case_plan_turn_invalid")
        need(observed_index == evidence_turn_index, "evidence_turn_index_mismatch")
    capture = need_map(envelope.get("capture"), "evidence_capture_missing")
    events = tuple(
        need_map(item, "evidence_event_invalid")
        for item in need_list(capture.get("events"), "evidence_events_invalid")
    )
    projection = need_map(envelope.get("db_projection"), "evidence_projection_missing")
    completeness = need_map(envelope.get("completeness"), "evidence_completeness_missing")
    completeness_status = str(completeness.get("status") or "")
    gate = None if completeness_status == "complete" else "evidence_incomplete"
    final_kind, final_text = _final_outcome(list(events))
    bindings = need_map(envelope.get("bindings"), "evidence_bindings_missing")
    resolved_bindings: dict[str, str] = {}
    for key in ("run_id", "plan_id", "plan_sha256"):
        resolved_bindings[key] = need_str(bindings.get(key), "evidence_bindings_invalid")
    units = _unit_views(events, projection, document_codes)
    return TurnProjection(
        turn_index=turn_index,
        status=status,
        gate=gate,
        units=units,
        final_kind=final_kind,
        final_text=final_text,
        events=events,
        projection=projection,
        envelope_bindings=resolved_bindings,
        completeness_status=completeness_status,
        authenticated_user_id=need_str(turn.get("authenticated_user_id"), "evidence_turn_invalid"),
        evidence_turn_index=observed_index,
    )


def safety_turn_views(turns: list[TurnProjection]) -> tuple[Any, ...]:
    from mktkb.evaluation.p2_evidence_rescore import TurnView

    views: list[Any] = []
    for index, turn in enumerate(turns):
        need(turn.turn_index == index, "turn_index_not_contiguous")
        if turn.status != "executed":
            views.append(TurnView(turn_index=turn.turn_index, status=turn.status))
            continue
        views.append(
            TurnView(
                turn_index=turn.turn_index,
                status=turn.status,
                units=turn.units,
                final_kind=turn.final_kind,
                final_text=turn.final_text,
                gate=turn.gate,
            )
        )
    return tuple(views)


# --------------------------------------------------------------------------- #
# 三轴证据视图（每回合一份；按回合折叠到题级）
# --------------------------------------------------------------------------- #


def _payloads_of_kind(events: Mapping[str, Any] | tuple[Any, ...], kind: str) -> list[Mapping[str, Any]]:
    """取固定 kind 事件的 payload（显式校验 payload 必须是对象）。"""
    rows: list[Mapping[str, Any]] = []
    for item in list(events):
        event = need_map(item, "evidence_event_invalid")
        if str(event.get("kind")) != kind:
            continue
        rows.append(need_map(event.get("payload"), "evidence_event_payload_invalid"))
    return rows


def cross_user_view(turn: TurnProjection) -> Any:
    from mktkb.evaluation.p2_evidence_rescore_axes import (
        ClaimView,
        ContextMessageView,
        CrossUserEvidenceView,
        EntityInheritanceView,
        QueryStateEventView,
        QueryStateRowView,
        ResultMessageView,
    )

    projection = turn.projection
    conversation = need_map(projection.get("conversation"), "projection_conversation_missing")
    request = need_map(projection.get("request"), "projection_request_missing")
    owner = need_str(conversation.get("owner_user_id"), "projection_conversation_invalid")
    conversation_id = need_str(conversation.get("id"), "projection_conversation_invalid")
    request_id = need_str(request.get("id"), "projection_request_invalid")
    messages = [
        need_map(row, "projection_message_invalid")
        for row in need_list(projection.get("messages"), "projection_messages_invalid")
    ]
    message_by_id = {need_str(row.get("id"), "projection_message_invalid"): row for row in messages}

    claims = tuple(
        ClaimView(
            authenticated_user_id=need_opt_str(payload.get("authenticated_user_id"), "claim_invalid"),
            owner_user_id=need_opt_str(payload.get("owner_user_id"), "claim_invalid"),
            conversation_id=need_opt_str(payload.get("conversation_id"), "claim_invalid"),
            request_id=need_opt_str(payload.get("request_id"), "claim_invalid"),
        )
        for payload in _payloads_of_kind(turn.events, "claim_observed")
    )

    observations = _payloads_of_kind(turn.events, "context_observed")
    observation_count: int | None = None
    observation_empty: bool | None = None
    observation_request_id: str | None = None
    if len(observations) == 1:
        payload = observations[0]
        observation_count = need_int(payload.get("count"), "context_observed_invalid", minimum=0)
        observation_empty = need_bool(payload.get("empty"), "context_observed_invalid")
        observation_request_id = need_opt_str(payload.get("request_id"), "context_observed_invalid")

    context_messages = tuple(
        ContextMessageView(
            seq=payload.get("seq") if type(payload.get("seq")) is int else None,
            owner_user_id=need_opt_str(payload.get("owner_user_id"), "context_message_invalid"),
            request_id=need_opt_str(payload.get("request_id"), "context_message_invalid"),
        )
        for payload in _payloads_of_kind(turn.events, "context_message")
    )

    query_states_available = projection.get("query_states_available")
    need(isinstance(query_states_available, bool), "projection_query_states_invalid")
    state_rows = [
        need_map(row, "projection_query_state_invalid")
        for row in need_list(projection.get("query_states"), "projection_query_states_invalid")
    ]
    same_rows = [row for row in state_rows if str(row.get("stored_conversation_id")) == conversation_id]
    query_states = tuple(
        QueryStateRowView(
            stored_user_id=need_opt_str(row.get("stored_user_id"), "projection_query_state_invalid"),
            stored_conversation_id=need_opt_str(
                row.get("stored_conversation_id"), "projection_query_state_invalid"
            ),
        )
        for row in state_rows
    )

    state_events: list[Any] = []
    for kind in ("query_state_observed", "query_state_saved", "query_state_cleared"):
        for payload in _payloads_of_kind(turn.events, kind):
            state_json = payload.get("state_json")
            matches: bool | None = None
            if isinstance(state_json, Mapping):
                matches = any(dict(row.get("state_json") or {}) == dict(state_json) for row in same_rows)
            row_present = payload.get("row_present")
            state_events.append(
                QueryStateEventView(
                    kind=kind,
                    user_id=need_opt_str(payload.get("user_id"), "query_state_event_invalid"),
                    conversation_id=need_opt_str(payload.get("conversation_id"), "query_state_event_invalid"),
                    stored_user_id=need_opt_str(payload.get("stored_user_id"), "query_state_event_invalid"),
                    stored_conversation_id=need_opt_str(
                        payload.get("stored_conversation_id"), "query_state_event_invalid"
                    ),
                    row_present=row_present if isinstance(row_present, bool) else None,
                    state_json_matches=matches,
                )
            )

    inheritance: list[Any] = []
    for payload in _payloads_of_kind(turn.events, "entity_inheritance"):
        source_id = need_opt_str(payload.get("source_message_id"), "entity_inheritance_invalid")
        row = message_by_id.get(source_id) if source_id is not None else None
        inheritance.append(
            EntityInheritanceView(
                source_message_id=source_id,
                source_owner_user_id=None
                if row is None
                else need_opt_str(row.get("owner_user_id"), "projection_message_invalid"),
                source_role=None if row is None else need_opt_str(row.get("role"), "projection_message_invalid"),
            )
        )

    result_message_id = need_opt_str(request.get("result_message_id"), "projection_request_invalid")
    result_row = message_by_id.get(result_message_id) if result_message_id is not None else None
    result_message = (
        None
        if result_row is None
        else ResultMessageView(
            result_message_id=result_message_id,
            owner_user_id=need_opt_str(result_row.get("owner_user_id"), "projection_message_invalid"),
            role=need_opt_str(result_row.get("role"), "projection_message_invalid"),
        )
    )

    return CrossUserEvidenceView(
        projection_available=True,
        owner_user_id=owner,
        conversation_id=conversation_id,
        authenticated_user_id=turn.authenticated_user_id,
        request_id=request_id,
        request_user_id=need_opt_str(request.get("user_id"), "projection_request_invalid"),
        request_conversation_id=need_opt_str(request.get("conversation_id"), "projection_request_invalid"),
        claims=claims,
        context_observation_count=observation_count,
        context_observation_empty=observation_empty,
        context_observation_request_id=observation_request_id,
        context_messages=context_messages,
        query_states_available=query_states_available,
        query_states=query_states,
        query_state_events=tuple(state_events),
        entity_inheritance=tuple(inheritance),
        result_message=result_message,
    )


def cross_entity_view(turn: TurnProjection) -> Any:
    from mktkb.evaluation.p2_evidence_rescore_axes import (
        CrossEntityEvidenceView,
        EntityFactView,
        EntityIdentityView,
    )

    projection = turn.projection
    unit_rows = [
        need_map(row, "projection_unit_invalid")
        for row in need_list(projection.get("units"), "projection_units_invalid")
    ]
    unit_entity: dict[str, Any] = {}
    for row in unit_rows:
        unit_id = need_str(row.get("unit_id"), "projection_unit_invalid")
        entity_type = need_opt_str(row.get("entity_type"), "projection_unit_invalid")
        entity_key = need_opt_str(row.get("entity_key"), "projection_unit_invalid")
        filters = row.get("entity_filters")
        need(isinstance(filters, Mapping), "projection_unit_invalid")
        if entity_type is None and entity_key is None:
            continue
        unit_entity[unit_id] = EntityIdentityView(
            entity_type=entity_type, entity_key=entity_key, filters=dict(filters)
        )

    facts: list[Any] = []
    for payload in _payloads_of_kind(turn.events, "direct_rag_answer"):
        for fact in need_list(payload.get("facts"), "direct_rag_fact_invalid"):
            row = need_map(fact, "direct_rag_fact_invalid")
            facts.append(
                EntityFactView(
                    entity_key=need_opt_str(row.get("entity_key"), "direct_rag_fact_invalid"),
                    source_unit_id=need_opt_str(row.get("source_unit_id"), "direct_rag_fact_invalid"),
                    layer="direct_rag_fact",
                )
            )

    plan_rows = _payloads_of_kind(turn.events, "plan_observed")
    plan_filters = None
    if len(plan_rows) == 1:
        filters = plan_rows[0].get("filters")
        if isinstance(filters, Mapping):
            plan_filters = dict(filters)

    return CrossEntityEvidenceView(
        units=turn.units,
        unit_entity=unit_entity,
        facts=tuple(facts),
        plan_filters=plan_filters,
        bindings=dict(turn.envelope_bindings),
        # 空使用集闭包证明由 C 冻结模块实现；本包不重写也不冒充：显式标「未证明」-> fail closed。
        empty_scope_proven=False,
        empty_scope_reason="empty_set_not_proven",
    )


def stale_source_view(turn: TurnProjection) -> Any:
    from mktkb.evaluation.p2_evidence_rescore_axes import LifecycleView, StaleSourceEvidenceView

    projection = turn.projection
    unit_rows = [
        need_map(row, "projection_unit_invalid")
        for row in need_list(projection.get("units"), "projection_units_invalid")
    ]
    by_id = {need_str(row.get("unit_id"), "projection_unit_invalid"): row for row in unit_rows}
    sources = [
        need_map(row, "projection_message_source_invalid")
        for row in need_list(projection.get("message_sources"), "projection_message_sources_invalid")
    ]
    source_by_id = {
        need_str(row.get("source_id"), "projection_message_source_invalid"): row for row in sources
    }

    lifecycle: dict[str, Any] = {}
    for unit in turn.units:
        row = by_id.get(unit.unit_id)
        if row is None:
            continue
        date_fields = row.get("date_fields")
        need(isinstance(date_fields, Mapping), "projection_unit_invalid")
        # 本批全部使用 unit 的 date_fields 均为空；非空结构无冻结投影定义 -> fail closed。
        date_state = "none" if not date_fields else "unavailable"
        version_state_raw = need_opt_str(row.get("version_state"), "projection_unit_invalid")
        version_state = version_state_raw if version_state_raw in ("published", "not_published") else None
        source_row = source_by_id.get(unit.unit_id) if "final_citation" in unit.layers else None
        lifecycle[unit.unit_id] = LifecycleView(
            unit_id=unit.unit_id,
            document_deleted=need_bool(row.get("document_deleted"), "projection_unit_invalid"),
            version_state=version_state,
            active=need_bool(row.get("active"), "projection_unit_invalid"),
            active_version_id=need_opt_str(row.get("active_version_id"), "projection_unit_invalid"),
            date_state=date_state,
            effective_from=None,
            effective_to=None,
            citation_source_document_id=None
            if source_row is None
            else need_opt_str(source_row.get("document_id"), "projection_message_source_invalid"),
            citation_source_version_id=None
            if source_row is None
            else need_opt_str(source_row.get("version_id"), "projection_message_source_invalid"),
        )

    plan_rows = _payloads_of_kind(turn.events, "plan_observed")
    actual_as_of = None
    include_future = None
    if len(plan_rows) == 1:
        actual_as_of = need_opt_str(plan_rows[0].get("as_of"), "plan_observed_invalid")
        include = plan_rows[0].get("include_future")
        include_future = include if isinstance(include, bool) else None

    return StaleSourceEvidenceView(
        units=turn.units,
        lifecycle=lifecycle,
        actual_as_of=actual_as_of,
        include_future=include_future,
        bindings=dict(turn.envelope_bindings),
        empty_scope_proven=False,
        empty_scope_reason="empty_set_not_proven",
    )
