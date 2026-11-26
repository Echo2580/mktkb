"""v3 四轴用 matcher v2 重算（axes-v2，零真实调用）。

用途
----
v3 首轮四轴是用冻结 `p2_hard_evidence._ref_matches_unit`（只按 unit_key/locator）算的，
对版本不敏感，已知会把"旧版 D01v2 的 forbidden ref"与"当前 V04(v3) 同一 (sheet,row)"
判成同一来源，制造 `forbidden_source_used` 假违规（C25）。本脚本在**既有密封证据**上
用 Q1a 已交付的 matcher v2 重算四轴：

- safety 轴走 Q1a-1 路径（`p2_evidence_rescore.rescore_run`）；
- cross_user / cross_entity / stale_source 走 Q1a-1b 路径
  （`p2_evidence_rescore_axes.rescore_axes_run`）；
- 版本身份只来自：v3 L1（`p2-stale-source-criterion-v1_1.md` 语义 + `p2-source-lifecycle-v1.json`）
  + `p2-holdout-v3.source-map.json`（v0.2：doc_code -> (base_doc_code, version_number)）
  + 每 run 的 `business_date`。**不使用**"证据里只剩一个版本"之类推断。

边界
----
- 不改任何冻结件：`p2_hard_evidence.py`、Q1a-1/1b 两模块、v2/v3 语料与密文、
  评测模块、账本/GO/预算、30 题/标签/阈值一律只读。
- 零真实调用：本脚本只读本地文件；出站由 `netguard_axesv2` 在 socket 原语层拦截。
- 只做只读投影：调用 `p2_hard_evidence` 的纯读辅助（`_events` / `_used_unit_layers` /
  `_units_by_id` / `_unresolved_unit_ids` / `_facts` / `_empty_use_scope_proof` /
  `_payloads` / `_messages_by_id`），不 monkeypatch、不写回、不改其行为。
- 输出只含固定码与计数；不含题面、答案、query 文本、逐题 hash。

用法
----
    cd <repo>
    $env:PYTHONPATH="<repo>\\docs\\reports\\OBS-EVAL\\P2\\H2V3\\axes-v2\\evidence\\netguard"
    $env:NETGUARD_OUT="<...>\\netguard-recompute-run.json"
    .venv\\Scripts\\python.exe -X utf8 <本文件>
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import pathlib
import re
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

# --------------------------------------------------------------------------- #
# 路径与只读输入
# --------------------------------------------------------------------------- #

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
WORK = pathlib.Path(r"D:\mktkb-p2-h2v3-fullverify-20261116")
RUN_DIR_NAMES = {0: "r0", 1: "r1", 2: "r2", 3: "r3"}
OUT = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/evidence"

SCHEMA_VERSION = "p2-h2v3-axes-v2-recompute/v0.1"
MATCHER_VERSION = "ref-unit-matcher/v2"

BACKEND_SRC = REPO / "backend" / "src"
TOOLS = REPO / "tools"
for _entry in (str(BACKEND_SRC), str(TOOLS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

V0_1_CONTRACT = REPO / "docs/evaluation/p2-evidence-rescore-v0_1.md"
V0_2_CONTRACT = REPO / "docs/evaluation/p2-evidence-rescore-v0_2.md"
L1_CRITERION = REPO / "docs/evaluation/p2-stale-source-criterion-v1_1.md"
LIFECYCLE = REPO / "docs/evaluation/p2-source-lifecycle-v1.json"
SOURCE_MAP = REPO / "docs/evaluation/p2-holdout-v3.source-map.json"
CORPUS_MANIFEST = REPO / "fixtures/acceptance-h2v3/manifest.json"
V1_RESULTS = (
    REPO / "docs/reports/OBS-EVAL/P2/H2V3/compose/evidence/recompute-four-runs.json"
)
ANNOTATION_SCHEMA = REPO / "docs/evaluation/p2-h2-custody-annotations-v0_2.md"

SCENARIOS: tuple[tuple[str, int], ...] = (
    ("run0-base_b0.binding.json", 0),
    ("run1-base_b0_plus_v01.binding.json", 1),
    ("run2-pre_v05_without_v07.binding.json", 2),
    ("run3-post_v05_without_v01.binding.json", 3),
)
AXES: tuple[str, ...] = ("safety", "cross_user", "cross_entity", "stale_source")
RESCORED_AXES: tuple[str, ...] = ("cross_user", "cross_entity", "stale_source")

UNIT_KEY_RE = re.compile(r"^sheet:(?P<sheet>.+):row:(?P<row>[0-9]+)$")

#: 轴 basis / 来源标记（只进 provenance，不参与 verdict 折叠）。
AXIS_BASIS: dict[str, str] = {
    "cross_user": "frozen_contract",
    "cross_entity": "frozen_label_target",
    "stale_source": "case_business_date_baseline",
}
AXIS_SOURCE: dict[str, str] = {
    "cross_user": "frozen_contract",
    "cross_entity": "frozen_contract",
    "stale_source": "case_business_date",
}


def sha256_bytes(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return sha256_bytes(path.read_bytes())


def _load_module(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ENTRY = _load_module("p2_h2_v3_ce", TOOLS / "p2_h2_v3_controlled_execute.py")

from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: E402
import mktkb.evaluation.p2_evidence_rescore as rescore  # noqa: E402
import mktkb.evaluation.p2_evidence_rescore_axes as rescore_axes  # noqa: E402

hard = ENTRY.hard

# --------------------------------------------------------------------------- #
# 版本绑定来源（source-map v0.2 + L1 lifecyle + business_date）
# --------------------------------------------------------------------------- #


def load_version_sources() -> dict[str, Any]:
    payload = json.loads(SOURCE_MAP.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "p2-holdout-source-map/v0.2":
        raise RuntimeError("source map schema is not v0.2")
    sources = payload["sources"]
    inverse: dict[tuple[str, int], str] = {}
    for code, record in sources.items():
        identity = (str(record["base_doc_code"]), int(record["version_number"]))
        if identity in inverse:
            raise RuntimeError("source map identity is not bijective")
        inverse[identity] = code
    lifecycle = json.loads(LIFECYCLE.read_text(encoding="utf-8"))
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    record_codes: dict[tuple[str, str, int], str] = {}
    for code, record in manifest["sources"].items():
        key = (str(record["file"]), str(record["sheet"]), int(record["row"]))
        if key in record_codes and record_codes[key] != code:
            raise RuntimeError("corpus manifest record identity is ambiguous")
        record_codes[key] = code
    bases = {str(record["base_doc_code"]) for record in sources.values()}
    return {
        "source_map": sources,
        "inverse": inverse,
        "bases": bases,
        "record_codes": record_codes,
        "lifecycle_schema": lifecycle.get("schema_version"),
        "source_map_sha256": sha256_file(SOURCE_MAP),
        "lifecycle_sha256": sha256_file(LIFECYCLE),
        "corpus_manifest_sha256": sha256_file(CORPUS_MANIFEST),
        "l1_criterion_sha256": sha256_file(L1_CRITERION),
        "code_count": len(sources),
        "bijective_pairs": len(inverse),
    }


def base_doc_of(document_name: Any) -> str | None:
    name = str(document_name or "")
    if "_" not in name:
        return None
    base = name.split("_", 1)[0]
    return base or None


def doc_code_for(unit: Mapping[str, Any], vs: Mapping[str, Any]) -> str | None:
    """unit 的版本身份 -> 数据集 doc_code（双射反查）；版本未声明则 unresolved。"""
    base = base_doc_of(unit.get("document_name"))
    version_number = unit.get("version_number")
    if base is None or base not in vs["bases"]:
        return None
    if type(version_number) is not int or version_number < 1:
        return None
    return vs["inverse"].get((base, int(version_number)))


def record_code_for(unit: Mapping[str, Any], vs: Mapping[str, Any]) -> str | None:
    """unit_key -> record_code 的显式映射（来自冻结语料 manifest，不猜）。"""
    match = UNIT_KEY_RE.match(str(unit.get("unit_key") or ""))
    if match is None:
        return None
    base = base_doc_of(unit.get("document_name"))
    if base is None:
        return None
    return vs["record_codes"].get((base, match.group("sheet"), int(match.group("row"))))


def binding_for(ref: Mapping[str, Any], vs: Mapping[str, Any]) -> rescore.VersionBinding | None:
    record = vs["source_map"].get(str(ref.get("doc_code") or ""))
    if record is None:
        return None
    return rescore.VersionBinding(version_number=int(record["version_number"]), basis="source_map")


#: L1 (=p2-stale-source-criterion-v1_1) 的日期语义：哨兵"未声明"= effective_to null
#: = not_asserted（既不是"无限有效"也不是 unknown）。
EFFECTIVE_FROM_KEYS = ("生效日期",)
EFFECTIVE_TO_KEYS = ("失效日期",)
NOT_ASSERTED_SENTINELS = ("未声明",)
ISO_DATE_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if ISO_DATE_RE.match(text) is None:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def effective_range(unit: Mapping[str, Any]) -> tuple[str, str | None, str | None]:
    """date_state = none / range / ambiguous / unavailable（L1 语义）。"""
    fields = unit.get("date_fields")
    if not isinstance(fields, Mapping) or not fields:
        fields = unit.get("raw_fields")
    if not isinstance(fields, Mapping):
        return ("unavailable", None, None)
    start_raw = next((fields[k] for k in EFFECTIVE_FROM_KEYS if k in fields), None)
    end_raw = next((fields[k] for k in EFFECTIVE_TO_KEYS if k in fields), None)
    has_start = any(k in fields for k in EFFECTIVE_FROM_KEYS)
    has_end = any(k in fields for k in EFFECTIVE_TO_KEYS)
    start = _iso(start_raw)
    end = _iso(end_raw)
    if start_raw is not None and start is None and str(start_raw).strip() not in NOT_ASSERTED_SENTINELS:
        return ("ambiguous", None, None)
    if end_raw is not None and end is None and str(end_raw).strip() not in NOT_ASSERTED_SENTINELS:
        return ("ambiguous", None, None)
    if start is None and end is None:
        if has_start or has_end:
            # 列存在但两侧都未断言 -> 无日期约束（L1: null 不等于无限有效，也不等于 unknown）。
            return ("none", None, None)
        return ("none", None, None)
    return ("range", start, end)


# --------------------------------------------------------------------------- #
# 只读证据投影
# --------------------------------------------------------------------------- #


def build_units(
    projection: Mapping[str, Any],
    layers: Mapping[str, list[str]],
    vs: Mapping[str, Any],
) -> tuple[rescore.UnitView, ...]:
    rows = hard._units_by_id(projection)
    units: list[rescore.UnitView] = []
    for unit_id, layer_names in layers.items():
        row = rows.get(unit_id)
        if row is None:
            continue
        version_number = row.get("version_number")
        version_number = version_number if type(version_number) is int and version_number > 0 else None
        locator = row.get("locator")
        units.append(
            rescore.UnitView(
                unit_id=unit_id,
                layers=tuple(name for name in rescore.USE_LAYERS if name in layer_names),
                document_id=None if row.get("document_id") is None else str(row["document_id"]),
                document_name=None if row.get("document_name") is None else str(row["document_name"]),
                doc_code=doc_code_for(row, vs),
                version_id=None if row.get("version_id") is None else str(row["version_id"]),
                version_number=version_number,
                unit_key=None if row.get("unit_key") is None else str(row["unit_key"]),
                record_code=record_code_for(row, vs),
                locator=dict(locator) if isinstance(locator, Mapping) else {},
            )
        )
    return tuple(units)


def build_safety_turns(
    audit: Mapping[str, Any],
) -> tuple[tuple[rescore.TurnView, ...], dict[str, Any]]:
    """把单题 audit 投影成 Q1a-1 的 `TurnView` 序列。

    `turn_index` 用**题内回合序号** 0..n-1（Q1a-1 的 `SafetyCaseView` 入口要求），
    原始 run 级全局回合序号只在本函数内用于定位密文文件，不进报告。
    """
    turns: list[rescore.TurnView] = []
    stats = {"executed": 0, "gate": {}}
    for ordinal, entry in enumerate(audit["turns"]):
        status = str(entry["status"])
        if status != "executed":
            turns.append(rescore.TurnView(turn_index=ordinal, status=status))
            continue
        envelope = entry["evidence"]
        gate = turn_gate(envelope)
        if gate is not None:
            stats["gate"][gate] = stats["gate"].get(gate, 0) + 1
        try:
            events = rescore._event_rows(envelope)
        except rescore.RescoreError:
            events = []
        final_kind, final_text = rescore._final_outcome(events)
        stats["executed"] += 1
        turns.append(
            rescore.TurnView(
                turn_index=ordinal,
                status=status,
                units=build_units(
                    hard._projection(envelope), rescore._used_layers(events), CURRENT_VS
                ),
                final_kind=final_kind,
                final_text=final_text,
                gate=gate,
            )
        )
    return tuple(turns), stats


def turn_gate(envelope: Mapping[str, Any]) -> str | None:
    """复现 v1 冻结件 `_classify_turn` 的 turn 级证据门（只读复用其判定函数）。

    顺序与 v1 完全一致：结构闭包 -> 完整性 -> 分支矩阵（hard/soft 都按该 turn 的缺口处理，
    fail-closed），最后落到 `completeness`。返回的码必须在 Q1a-1 的 `GATE_CODES` 内，
    否则用 `branch_evidence_missing`（同样是 fail-closed 的固定码）。
    """
    code = hard._structural_closure_violation(envelope)
    if code is None:
        code = hard._turn_integrity_violation(envelope)
    if code is None:
        matrix = hard._turn_branch_matrix_violation(envelope)
        if matrix is not None:
            code = matrix[0]
    completeness = envelope.get("completeness")
    if code is None and (
        not isinstance(completeness, Mapping) or str(completeness.get("status")) != "complete"
    ):
        code = "evidence_incomplete"
    if code is None:
        return None
    return code if code in rescore.GATE_CODES else "branch_evidence_missing"


def build_cross_user(envelope: Mapping[str, Any], units: Sequence[rescore.UnitView]) -> Any:
    projection = hard._projection(envelope)
    events = hard._events(envelope)
    turn = envelope.get("turn") if isinstance(envelope.get("turn"), Mapping) else {}
    conversation = projection.get("conversation")
    request_row = projection.get("request")
    if not isinstance(conversation, Mapping) or not isinstance(request_row, Mapping):
        return rescore_axes.CrossUserEvidenceView(projection_available=False)
    messages = hard._messages_by_id(projection)
    claims = tuple(
        rescore_axes.ClaimView(
            authenticated_user_id=_str_or_none(item.get("authenticated_user_id")),
            owner_user_id=_str_or_none(item.get("owner_user_id")),
            conversation_id=_str_or_none(item.get("conversation_id")),
            request_id=_str_or_none(item.get("request_id")),
        )
        for item in hard._payloads(events, "claim_observed")
    )
    observations = hard._payloads(events, "context_observed")
    observation = observations[0] if len(observations) == 1 else {}
    context_messages = tuple(
        rescore_axes.ContextMessageView(
            seq=item.get("seq") if type(item.get("seq")) is int else None,
            owner_user_id=_str_or_none(item.get("owner_user_id")),
            request_id=_str_or_none(item.get("request_id")),
        )
        for item in hard._payloads(events, "context_message")
    )
    states_available = projection.get("query_states_available")
    state_rows = tuple(
        rescore_axes.QueryStateRowView(
            stored_user_id=_str_or_none(row.get("stored_user_id")),
            stored_conversation_id=_str_or_none(row.get("stored_conversation_id")),
        )
        for row in (projection.get("query_states") or ())
        if isinstance(row, Mapping)
    )
    request_id = _str_or_none(request_row.get("id"))
    conversation_id = _str_or_none(conversation.get("id"))
    same_rows = [
        row
        for row in (projection.get("query_states") or ())
        if isinstance(row, Mapping)
        and str(row.get("stored_conversation_id")) == str(conversation_id)
    ]
    state_events: list[Any] = []
    for kind in ("query_state_observed", "query_state_saved", "query_state_cleared"):
        for item in hard._payloads(events, kind):
            state_json_matches: bool | None = None
            if kind == "query_state_saved":
                state_json = item.get("state_json")
                if isinstance(state_json, Mapping):
                    state_json_matches = bool(same_rows) and any(
                        dict(row.get("state_json") or {}) == dict(state_json) for row in same_rows
                    )
            elif kind == "query_state_cleared":
                row_present = item.get("row_present")
                if isinstance(row_present, bool):
                    state_json_matches = False if not (row_present and same_rows) else True
            state_events.append(
                rescore_axes.QueryStateEventView(
                    kind=kind,
                    user_id=_str_or_none(item.get("user_id")),
                    conversation_id=_str_or_none(item.get("conversation_id")),
                    stored_user_id=_str_or_none(item.get("stored_user_id")),
                    stored_conversation_id=_str_or_none(item.get("stored_conversation_id")),
                    row_present=item.get("row_present") if isinstance(item.get("row_present"), bool) else None,
                    state_json_matches=state_json_matches,
                )
            )
    inheritances: list[Any] = []
    for item in hard._payloads(events, "entity_inheritance"):
        source_id = item.get("source_message_id")
        row = messages.get(str(source_id)) if source_id is not None else None
        inheritances.append(
            rescore_axes.EntityInheritanceView(
                source_message_id=_str_or_none(source_id),
                source_owner_user_id=None if row is None else _str_or_none(row.get("owner_user_id")),
                source_role=None if row is None else _str_or_none(row.get("role")),
            )
        )
    result_message_id = request_row.get("result_message_id")
    result_row = messages.get(str(result_message_id)) if result_message_id is not None else None
    result_message = (
        None
        if result_row is None
        else rescore_axes.ResultMessageView(
            result_message_id=_str_or_none(result_message_id),
            owner_user_id=_str_or_none(result_row.get("owner_user_id")),
            role=_str_or_none(result_row.get("role")),
        )
    )
    return rescore_axes.CrossUserEvidenceView(
        projection_available=True,
        owner_user_id=_str_or_none(conversation.get("owner_user_id")),
        conversation_id=conversation_id,
        authenticated_user_id=_str_or_none(turn.get("authenticated_user_id")),
        request_id=request_id,
        request_user_id=_str_or_none(request_row.get("user_id")),
        request_conversation_id=_str_or_none(request_row.get("conversation_id")),
        claims=claims,
        context_observation_count=(
            observation.get("count") if type(observation.get("count")) is int else None
        ),
        context_observation_empty=(
            observation.get("empty") if isinstance(observation.get("empty"), bool) else None
        ),
        context_observation_request_id=_str_or_none(observation.get("request_id")),
        context_messages=context_messages,
        query_states_available=states_available if isinstance(states_available, bool) else None,
        query_states=state_rows,
        query_state_events=tuple(state_events),
        entity_inheritance=tuple(inheritances),
        result_message=result_message,
    )


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def build_cross_entity_case_level(
    envelopes: Sequence[Mapping[str, Any]],
    units: Sequence[rescore.UnitView],
    vs: Mapping[str, Any],
) -> Any:
    """case 级使用范围：union(逐 turn unit) + facts；plan_filters 取 plan_observed。"""
    unit_entity: dict[str, Any] = {}
    facts: list[Any] = []
    seen_facts: set[tuple[str, str, str]] = set()
    plan_filters: Mapping[str, Any] | None = None
    empty_proven: bool | None = None
    empty_reason: str | None = None
    for envelope in envelopes:
        projection = hard._projection(envelope)
        events = hard._events(envelope)
        rows = hard._units_by_id(projection)
        for unit in units:
            row = rows.get(unit.unit_id)
            if row is None:
                continue
            unit_entity[unit.unit_id] = rescore_axes.EntityIdentityView(
                entity_type=_str_or_none(row.get("entity_type")),
                entity_key=_str_or_none(row.get("entity_key")),
                filters=dict(row.get("entity_filters") or {})
                if isinstance(row.get("entity_filters"), Mapping)
                else {},
            )
        for fact in hard._facts(events):
            key = (
                str(fact.get("entity_key")),
                str(fact.get("source_unit_id")),
                str(fact.get("layer") or "direct_rag_fact"),
            )
            if key in seen_facts:
                continue
            seen_facts.add(key)
            facts.append(
                rescore_axes.EntityFactView(
                    entity_key=_str_or_none(fact.get("entity_key")),
                    source_unit_id=_str_or_none(fact.get("source_unit_id")),
                    layer="direct_rag_fact",
                )
            )
        plans = hard._payloads(events, "plan_observed")
        if len(plans) == 1 and isinstance(plans[0].get("filters"), Mapping):
            plan_filters = {str(k): v for k, v in plans[0]["filters"].items()}
        if not units and not facts:
            ok, reason = hard._empty_use_scope_proof(envelope)
            empty_proven = bool(ok)
            if not ok:
                empty_reason = (
                    reason
                    if reason in rescore_axes.UNKNOWN_REASONS["cross_entity"]
                    else "empty_set_not_proven"
                )
    return rescore_axes.CrossEntityEvidenceView(
        units=tuple(units),
        unit_entity=unit_entity,
        facts=tuple(facts),
        plan_filters=plan_filters,
        bindings=None,
        empty_scope_proven=empty_proven,
        empty_scope_reason=empty_reason,
    )


def build_stale_case_level(
    envelopes: Sequence[Mapping[str, Any]],
    units: Sequence[rescore.UnitView],
) -> Any:
    lifecycle: dict[str, Any] = {}
    actual_as_of: str | None = None
    include_future: bool | None = None
    empty_proven: bool | None = None
    empty_reason: str | None = None
    for envelope in envelopes:
        projection = hard._projection(envelope)
        events = hard._events(envelope)
        rows = hard._units_by_id(projection)
        sources = {
            str(row.get("source_id")): row
            for row in (projection.get("message_sources") or ())
            if isinstance(row, Mapping)
        }
        for unit in units:
            row = rows.get(unit.unit_id)
            if row is None:
                continue
            date_state, start, end = effective_range(row)
            source_row = sources.get(unit.unit_id)
            lifecycle[unit.unit_id] = rescore_axes.LifecycleView(
                unit_id=unit.unit_id,
                document_deleted=(
                    row.get("document_deleted") if isinstance(row.get("document_deleted"), bool) else None
                ),
                version_state=(
                    str(row.get("version_state"))
                    if str(row.get("version_state")) in ("published", "not_published", "unknown")
                    else None
                ),
                active=row.get("active") if isinstance(row.get("active"), bool) else None,
                active_version_id=_str_or_none(row.get("active_version_id")),
                date_state=date_state,
                effective_from=start,
                effective_to=end,
                citation_source_document_id=(
                    None if source_row is None else _str_or_none(source_row.get("document_id"))
                ),
                citation_source_version_id=(
                    None if source_row is None else _str_or_none(source_row.get("version_id"))
                ),
            )
        plans = hard._payloads(events, "plan_observed")
        if len(plans) == 1:
            payload = plans[0]
            candidate = _iso(payload.get("as_of")) or _iso(projection.get("rag_business_date"))
            if candidate is not None:
                actual_as_of = candidate
            value = payload.get("include_future")
            if isinstance(value, bool):
                include_future = value
        if not units:
            ok, reason = hard._empty_use_scope_proof(envelope)
            empty_proven = bool(ok)
            if not ok:
                empty_reason = (
                    reason
                    if reason in rescore_axes.UNKNOWN_REASONS["stale_source"]
                    else "empty_set_not_proven"
                )
    return rescore_axes.StaleSourceEvidenceView(
        units=tuple(units),
        lifecycle=lifecycle,
        actual_as_of=actual_as_of,
        include_future=include_future,
        bindings=None,
        empty_scope_proven=empty_proven,
        empty_scope_reason=empty_reason,
    )


def merge_units(per_turn: Sequence[Sequence[rescore.UnitView]]) -> tuple[rescore.UnitView, ...]:
    merged: dict[str, rescore.UnitView] = {}
    for units in per_turn:
        for unit in units:
            existing = merged.get(unit.unit_id)
            if existing is None:
                merged[unit.unit_id] = unit
                continue
            layers = tuple(
                name
                for name in rescore.USE_LAYERS
                if name in set(existing.layers) | set(unit.layers)
            )
            merged[unit.unit_id] = dataclasses.replace(existing, layers=layers)
    return tuple(merged.values())


# --------------------------------------------------------------------------- #
# 合同 / 注解
# --------------------------------------------------------------------------- #


def all_refs(case: Any) -> dict[str, tuple[dict[str, Any], ...]]:
    return {
        "expected_sources": tuple(dict(ref) for ref in case.expected_sources),
        "relevant_units": tuple(dict(ref) for ref in case.relevant_units),
        "forbidden_sources": tuple(dict(ref) for ref in case.forbidden_sources),
    }


def version_bindings_for(
    refs: Mapping[str, Sequence[Mapping[str, Any]]], vs: Mapping[str, Any]
) -> dict[str, rescore.VersionBinding]:
    bindings: dict[str, rescore.VersionBinding] = {}
    unresolved: list[str] = []
    for rows in refs.values():
        for ref in rows:
            binding = binding_for(ref, vs)
            if binding is None:
                unresolved.append(str(ref.get("doc_code")))
                continue
            bindings[rescore.ref_key(ref)] = binding
    return bindings


def make_annotation(axis: str, payload: Mapping[str, Any]) -> Any:
    enriched = dict(payload)
    enriched["basis"] = AXIS_BASIS[axis]
    enriched["source"] = AXIS_SOURCE[axis]
    return rescore_axes.AxisAnnotation.from_mapping(axis, enriched)


def mode_for(annotation: Any) -> str:
    return rescore_axes._cross_entity_mode_from_annotation(annotation)


def contract_bindings(plan: Mapping[str, Any]) -> dict[str, str]:
    """合同/证据共同的 {run_id, plan_id, plan_sha256}（来自已校验 case-plan 与 frozen bindings）。"""
    bindings = plan["bindings"]
    return {
        "run_id": str(plan["run_id"]),
        "plan_id": str(bindings["plan_id"]),
        "plan_sha256": str(bindings["plan_sha256"]),
    }


def build_axes_view(
    *,
    old: rescore.OldCardCase,
    annotations: Mapping[str, Any],
    cross_user: Any,
    cross_entity: Any,
    stale_source: Any,
    refs: Mapping[str, Sequence[Mapping[str, Any]]],
    version_bindings: Mapping[str, rescore.VersionBinding],
    bindings: Mapping[str, str],
    cross_entity_mode: str,
    targets: Sequence[Mapping[str, Any]],
    case_id: str,
) -> Any:
    bindings_map = dict(bindings)
    entity_view = dataclasses.replace(cross_entity, bindings=bindings_map)
    stale_view = dataclasses.replace(stale_source, bindings=bindings_map)
    shared = bindings_map

    entity_contract = rescore_axes.CrossEntityContract(
        case_id=case_id,
        mode=cross_entity_mode,
        targets=tuple(
            rescore_axes.ScopeTarget(
                entity_type=str(target.get("entity_type") or ""),
                entity_key=str(target.get("entity_key") or ""),
                filters={
                    str(k): v
                    for k, v in (target.get("filters") or {}).items()
                }
                if isinstance(target.get("filters"), Mapping)
                else {},
            )
            for target in targets
        ),
        shared_background=(),
        bindings=shared,
        refs={name: tuple(rows) for name, rows in refs.items()},
        version_bindings=dict(version_bindings),
    )

    constrained: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in ("relevant_units", "expected_sources"):
        for ref in refs.get(name, ()):
            key = rescore.ref_key(ref)
            if key in seen:
                continue
            seen.add(key)
            constrained.append(dict(ref))
    stale_contract = rescore_axes.StaleSourceContract(
        case_id=case_id,
        bindings=shared,
        constrained_refs=tuple(constrained),
        refs={name: tuple(rows) for name, rows in refs.items()},
        version_bindings=dict(version_bindings),
    )

    return rescore_axes.AxesCaseView(
        old=old,
        annotations=annotations,
        cross_user=cross_user,
        cross_entity=entity_view,
        cross_entity_contract=entity_contract,
        stale_source=stale_view,
        stale_source_contract=stale_contract,
    )


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


CURRENT_VS: dict[str, Any] = {}


def build_old_card(row: Mapping[str, Any]) -> rescore.OldCardCase:
    axes = {
        name: {
            "state": str(row["axes"][name]["state"]),
            "reason": str(row["axes"][name]["reason"]),
        }
        for name in AXES
    }
    return rescore.OldCardCase(
        case_id=str(row["case_id"]),
        stratum=str(row["stratum"]),
        quality_status=str(row["quality_status"]),
        axes=axes,
        missing_codes=tuple(str(code) for code in row["missing_codes"]),
        evidence_complete=bool(row["evidence_complete"]),
    )


def fold_turns(parts: Sequence[tuple[str, str]]) -> tuple[str, str]:
    """v0.2 §6.1 折叠：violation > unknown > not_applicable > passed。"""
    for state in ("violation", "unknown"):
        for item_state, item_reason in parts:
            if item_state == state:
                return state, item_reason
    if parts and all(item_state == "not_applicable" for item_state, _ in parts):
        return "not_applicable", parts[0][1]
    return "passed", (parts[0][1] if parts else "passed")


def main() -> int:
    global CURRENT_VS
    vs = load_version_sources()
    CURRENT_VS = vs
    v1 = json.loads(V1_RESULTS.read_text(encoding="utf-8"))
    v1_by_run = {int(run["run_index"]): run for run in v1["runs"]}
    v1_rows: dict[str, Mapping[str, Any]] = {}
    for run in v1["runs"]:
        for row in run["cases"]:
            v1_rows[str(row["case_id"])] = row

    key = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\runs3\ev.key").read_bytes().strip()
    v0_1_sha = sha256_file(V0_1_CONTRACT)
    v0_2_sha = sha256_file(V0_2_CONTRACT)
    rescore_sha = sha256_file(REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore.py")
    axes_sha = sha256_file(REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py")

    runs_out: list[dict[str, Any]] = []
    case_records: list[dict[str, Any]] = []
    for binding_name, run_index in SCENARIOS:
        binding = json.loads(
            (pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-single-01\bindings") / binding_name).read_text(encoding="utf-8")
        )
        inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
        bundle = ENTRY.load_v3_bundle(inputs)
        run_entry = binding["runs"][0]
        run_id = str(run_entry["run_id"])
        scenario = str(run_entry["scenario_id"])
        cases = bundle.contract.subset(scenario).cases
        case_plan_payload = json.loads(
            (WORK / RUN_DIR_NAMES[run_index] / "out" / "controlled" / "case-plan.json").read_text(
                encoding="utf-8"
            )
        )
        static_bindings = {
            name: value
            for name, value in dict(run_entry["evidence_bindings"]).items()
            if name != "index_revision"
        }
        plan = ENTRY.v2._validate_case_plan_document(
            case_plan_payload, cases=cases, static_bindings=static_bindings
        )
        root = WORK / RUN_DIR_NAMES[run_index] / "evidence" / run_id
        receipt = json.loads(
            (WORK / RUN_DIR_NAMES[run_index] / "seal" / run_id / "run-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        business_date = str(receipt["business_date"])
        if business_date != str(case_plan_payload.get("run_binding", {}).get("business_date")):
            raise RuntimeError("business_date mismatch between receipt and case plan")

        envelopes_by_case: dict[str, list[Mapping[str, Any]]] = {}
        ordered_by_case: dict[str, list[Mapping[str, Any] | None]] = {}
        audit_by_case: dict[str, Mapping[str, Any]] = {}
        for case, row in zip(cases, plan["cases"]):
            entries: list[dict[str, Any]] = []
            envelopes: list[Mapping[str, Any]] = []
            ordered: list[Mapping[str, Any] | None] = []
            for turn_row in row["turns"]:
                track = {
                    "turn_index": int(turn_row["turn_index"]),
                    "status": str(turn_row["status"]),
                    "error": turn_row.get("error"),
                    "evidence": None,
                }
                if track["status"] == "executed":
                    envelope = read_encrypted_evidence(
                        root / str(turn_row["evidence_file"]),
                        key=key,
                        expected_bindings=dict(plan["bindings"]),
                    )
                    track["evidence"] = envelope
                    envelopes.append(envelope)
                    ordered.append(envelope)
                else:
                    ordered.append(None)
                entries.append(track)
            envelopes_by_case[case.case_id] = envelopes
            ordered_by_case[case.case_id] = ordered
            audit_by_case[case.case_id] = {
                "quality_status": str(row["quality_status"]),
                "turns": entries,
            }

        v1_run = v1_by_run[run_index]
        if int(v1_run["case_count"]) != len(cases):
            raise RuntimeError("v1 case count mismatch")
        old_cards = {
            case.case_id: build_old_card(v1_rows[case.case_id]) for case in cases
        }

        safety_views: list[rescore.SafetyCaseView] = []
        axes_views: list[Any] = []
        per_turn_axes: dict[str, dict[str, list[tuple[str, str]]]] = {}
        for case in cases:
            annotation_map, _basis = hard.annotation_for_case(bundle.annotation, case)
            refs = all_refs(case)
            bindings = version_bindings_for(refs, vs)
            old = old_cards[case.case_id]

            turns, _turn_stats = build_safety_turns(audit_by_case[case.case_id])
            safety_views.append(
                rescore.SafetyCaseView(
                    old=old,
                    safety_applicability=str(annotation_map["safety"]["applicability"]),
                    safety_criterion=str(annotation_map["safety"]["criterion"]),
                    safety_reason=str(annotation_map["safety"]["reason"]),
                    should_refuse=bool(getattr(case, "should_refuse", False)),
                    forbidden_values=tuple(str(value) for value in case.forbidden_values),
                    forbidden_sources=refs["forbidden_sources"],
                    expected_sources=refs["expected_sources"],
                    version_bindings=bindings,
                    turns=turns,
                )
            )

            annotations = {
                axis: make_annotation(axis, annotation_map[axis]) for axis in RESCORED_AXES
            }
            envelopes = envelopes_by_case[case.case_id]
            per_turn_units = [turn.units for turn in turns if turn.status == "executed"]
            merged_units = merge_units(per_turn_units)
            first_envelope = envelopes[0] if envelopes else None
            cross_user_view = (
                build_cross_user(first_envelope, merged_units)
                if first_envelope is not None
                else rescore_axes.CrossUserEvidenceView(projection_available=False)
            )
            axes_views.append(
                build_axes_view(
                    old=old,
                    annotations=annotations,
                    cross_user=cross_user_view,
                    cross_entity=build_cross_entity_case_level(envelopes, merged_units, vs),
                    stale_source=build_stale_case_level(envelopes, merged_units),
                    refs=refs,
                    version_bindings=bindings,
                    bindings=contract_bindings(plan),
                    cross_entity_mode=mode_for(annotations["cross_entity"]),
                    targets=annotations["cross_entity"].targets,
                    case_id=case.case_id,
                )
            )

            if len(turns) > 1:
                parts: dict[str, list[tuple[str, str]]] = {axis: [] for axis in RESCORED_AXES}
                for turn in turns:
                    if turn.status != "executed":
                        continue
                    single_envelope = ordered_by_case[case.case_id][turn.turn_index]
                    if single_envelope is None:
                        continue
                    single_view = build_axes_view(
                        old=old,
                        annotations=annotations,
                        cross_user=build_cross_user(single_envelope, turn.units),
                        cross_entity=build_cross_entity_case_level(
                            [single_envelope], turn.units, vs
                        ),
                        stale_source=build_stale_case_level([single_envelope], turn.units),
                        refs=refs,
                        version_bindings=bindings,
                        bindings=contract_bindings(plan),
                        cross_entity_mode=mode_for(annotations["cross_entity"]),
                        targets=annotations["cross_entity"].targets,
                        case_id=case.case_id,
                    )
                    single_result = rescore_axes.rescore_axes_case(
                        single_view, allow_synthetic_fixture=False
                    )
                    for axis in RESCORED_AXES:
                        parts[axis].append(
                            (
                                str(single_result.new_axes[axis]["state"]),
                                str(single_result.new_axes[axis]["reason"]),
                            )
                        )
                per_turn_axes[case.case_id] = parts

        old_card_bytes = rescore.canonical_json_bytes(dict(v1_run["card"]))
        binding_payload = {str(k): str(v) for k, v in plan["bindings"].items()}
        binding_bytes = rescore.canonical_json_bytes(binding_payload)
        base_identity = rescore.RescoreIdentity(
            old_run_id=run_id,
            old_binding=binding_payload,
            old_binding_sha256=sha256_bytes(binding_bytes),
            old_evidence_tree_sha256=str(receipt["seal"]["evidence_tree_sha256"]),
            old_card_sha256=sha256_bytes(old_card_bytes),
            contract_sha256=v0_1_sha,
            evaluator_sha256=rescore_sha,
            old_binding_bytes=binding_bytes,
            old_card_bytes=old_card_bytes,
        )
        safety_report = rescore.rescore_run(identity=base_identity, cases=tuple(safety_views))

        axes_identity = rescore_axes.AxesIdentity(
            base=dataclasses.replace(
                base_identity, contract_sha256=v0_2_sha, evaluator_sha256=axes_sha
            ),
            base_contract_sha256=v0_1_sha,
        )
        axes_report = rescore_axes.rescore_axes_run(
            identity=axes_identity,
            cases=tuple(axes_views),
            allow_synthetic_fixture=False,
        )

        safety_by_case = {item["case_id"]: item for item in safety_report.changed_cases}
        axes_changed: dict[str, list[Mapping[str, Any]]] = {}
        for item in axes_report.changed_cases:
            axes_changed.setdefault(str(item["case_id"]), []).append(item)

        run_case_rows: list[dict[str, Any]] = []
        for index, case in enumerate(cases):
            old = old_cards[case.case_id]
            safety_case = rescore.rescore_case(safety_views[index])
            axes_case = rescore_axes.rescore_axes_case(
                axes_views[index], allow_synthetic_fixture=False
            )
            new_axes = {
                "safety": dict(safety_case.new_axes["safety"]),
            }
            for axis in RESCORED_AXES:
                new_axes[axis] = {
                    "state": str(axes_case.new_axes[axis]["state"]),
                    "reason": str(axes_case.new_axes[axis]["reason"]),
                    "provenance": str(axes_case.new_axes[axis]["provenance"]),
                }
            old_axes = {axis: dict(old.axes[axis]) for axis in AXES}
            changed_axes = [
                axis
                for axis in AXES
                if (new_axes[axis]["state"], new_axes[axis]["reason"])
                != (old_axes[axis]["state"], old_axes[axis]["reason"])
            ]
            equivalence: dict[str, Any] = {}
            if case.case_id in per_turn_axes:
                for axis in RESCORED_AXES:
                    folded = fold_turns(per_turn_axes[case.case_id][axis])
                    merged = (new_axes[axis]["state"], new_axes[axis]["reason"])
                    equivalence[axis] = {
                        "merged_view": {"state": merged[0], "reason": merged[1]},
                        "per_turn_fold": {"state": folded[0], "reason": folded[1]},
                        "equal_state": folded[0] == merged[0],
                        "equal_state_reason": folded == merged,
                    }
            run_case_rows.append(
                {
                    "case_id": case.case_id,
                    "run_index": run_index,
                    "scenario_id": scenario,
                    "stratum": old.stratum,
                    "quality_status": old.quality_status,
                    "evidence_complete": old.evidence_complete,
                    "missing_codes": list(old.missing_codes),
                    "old_axes": old_axes,
                    "new_axes": new_axes,
                    "changed_axes": changed_axes,
                    "safety_audit_codes": sorted({row.code for row in safety_case.safety_audit}),
                    "axes_audit_codes": {
                        axis: sorted({row.code for row in axes_case.axis_audit[axis]})
                        for axis in RESCORED_AXES
                    },
                    "axes_basis": {axis: str(axes_case.axis_basis[axis]) for axis in RESCORED_AXES},
                    "axes_provenance": {
                        axis: str(axes_case.axis_provenance[axis]) for axis in RESCORED_AXES
                    },
                    "safety_provenance": safety_case.safety_provenance,
                    "multi_turn_equivalence": equivalence,
                }
            )
            case_records.append(run_case_rows[-1])

        run_reason_counts = {
            axis: {
                reason: sum(
                    1
                    for row in run_case_rows
                    if row["new_axes"][axis]["state"] == "violation"
                    and row["new_axes"][axis]["reason"] == reason
                )
                for reason in sorted(
                    {
                        row["new_axes"][axis]["reason"]
                        for row in run_case_rows
                        if row["new_axes"][axis]["state"] == "violation"
                    }
                )
            }
            for axis in AXES
        }
        runs_out.append(
            {
                "run_index": run_index,
                "run_id": run_id,
                "scenario_id": scenario,
                "business_date": business_date,
                "case_count": len(cases),
                "safety_report": safety_report.as_dict(),
                "axes_report": axes_report.public_summary(),
                "violation_reasons": run_reason_counts,
                "cases": run_case_rows,
            }
        )
        print(
            f"r{run_index} {scenario} cases={len(cases)} "
            f"safety={safety_report.axes['safety']} "
            f"cross_user={axes_report.axes['cross_user']} "
            f"cross_entity={axes_report.axes['cross_entity']} "
            f"stale_source={axes_report.axes['stale_source']}"
        )

    # ---------------- 聚合 ----------------
    def axis_counts(selector: str, run: Mapping[str, Any] | None = None) -> dict[str, dict[str, int]]:
        rows = run["cases"] if run is not None else case_records
        out: dict[str, dict[str, int]] = {}
        for axis in AXES:
            counts = {
                "planned": len(rows),
                "passed": 0,
                "not_applicable": 0,
                "unknown": 0,
                "violations": 0,
            }
            for row in rows:
                axis_value = row["new_axes" if selector == "new" else "old_axes"][axis]
                state = str(axis_value["state"])
                counts["violations" if state == "violation" else state] += 1
            counts["checked"] = counts["passed"] + counts["not_applicable"] + counts["violations"]
            out[axis] = counts
        return out

    new_axes_counts = axis_counts("new")
    old_axes_counts = axis_counts("old")
    for axis in AXES:
        counts = new_axes_counts[axis]
        assert counts["planned"] == counts["passed"] + counts["not_applicable"] + counts["unknown"] + counts["violations"]
        assert counts["checked"] == counts["passed"] + counts["not_applicable"] + counts["violations"]
        assert counts["checked"] + counts["unknown"] == counts["planned"]

    def hard_failures(selector: str, rows: Sequence[Mapping[str, Any]]) -> list[str]:
        return sorted(
            {
                str(row["case_id"])
                for row in rows
                if any(str(row[selector][axis]["state"]) == "violation" for axis in AXES)
            }
        )

    new_hard = hard_failures("new_axes", case_records)
    old_hard = hard_failures("old_axes", case_records)
    new_unknown = sorted(
        {
            str(row["case_id"])
            for row in case_records
            if any(str(row["new_axes"][axis]["state"]) == "unknown" for axis in AXES)
        }
    )

    changed_cases = [
        {
            "case_id": row["case_id"],
            "run_index": row["run_index"],
            "scenario_id": row["scenario_id"],
            "changed_axes": row["changed_axes"],
            "state_changed_axes": [
                axis
                for axis in row["changed_axes"]
                if row["old_axes"][axis]["state"] != row["new_axes"][axis]["state"]
            ],
            "reason_only_axes": [
                axis
                for axis in row["changed_axes"]
                if row["old_axes"][axis]["state"] == row["new_axes"][axis]["state"]
            ],
            "transitions": [
                {
                    "axis": axis,
                    "from": {
                        "state": row["old_axes"][axis]["state"],
                        "reason": row["old_axes"][axis]["reason"],
                    },
                    "to": {
                        "state": row["new_axes"][axis]["state"],
                        "reason": row["new_axes"][axis]["reason"],
                    },
                    "provenance": row["new_axes"][axis].get("provenance", "recorded_old")
                    if axis != "safety"
                    else row["safety_provenance"],
                    "audit_codes": (
                        row["safety_audit_codes"]
                        if axis == "safety"
                        else row["axes_audit_codes"][axis]
                    ),
                }
                for axis in row["changed_axes"]
            ],
        }
        for row in case_records
        if row["changed_axes"]
    ]
    state_change_cases = sorted(
        {item["case_id"] for item in changed_cases if item["state_changed_axes"]}
    )
    reason_only_cases = sorted(
        {
            item["case_id"]
            for item in changed_cases
            if item["changed_axes"] and not item["state_changed_axes"]
        }
    )
    axis_state_change_counts = {
        axis: sum(1 for item in changed_cases if axis in item["state_changed_axes"])
        for axis in AXES
    }

    #: v0.2 `CrossUserEvidenceView` 不承载 turn 级 branch-matrix 门；被 v1 该门判 unknown 的题
    #: 在 cross_user 上只能按 owner/context/querystate 逐项判定。此处显式给出"按 v1 门保守保留"
    #: 的对照计数，避免把门面收窄读成 matcher 结论。
    gate_surface_affected = sorted(
        {
            row["case_id"]
            for row in case_records
            if row["new_axes"]["cross_user"]["state"] == "passed"
            and row["old_axes"]["cross_user"]["state"] == "unknown"
            and "model_events_missing" in row["missing_codes"]
        }
    )
    conservative_cross_user = dict(new_axes_counts["cross_user"])
    if gate_surface_affected:
        conservative_cross_user["passed"] -= len(gate_surface_affected)
        conservative_cross_user["unknown"] += len(gate_surface_affected)
        conservative_cross_user["checked"] = (
            conservative_cross_user["passed"]
            + conservative_cross_user["not_applicable"]
            + conservative_cross_user["violations"]
        )

    reason_distribution: dict[str, dict[str, int]] = {}
    for entry in changed_cases:
        for transition in entry["transitions"]:
            key = (
                f"{transition['axis']}:{transition['from']['state']}"
                f"/{transition['from']['reason']}->{transition['to']['state']}"
                f"/{transition['to']['reason']}"
            )
            reason_distribution[key] = reason_distribution.get(key, 0) + 1

    equivalence_rows = [
        {
            "case_id": row["case_id"],
            "run_index": row["run_index"],
            "axes": row["multi_turn_equivalence"],
        }
        for row in case_records
        if row["multi_turn_equivalence"]
    ]

    c25 = _c25_detail(case_records, vs, old_hard, new_hard)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "matcher_version": MATCHER_VERSION,
        "analysis_id": rescore.ANALYSIS_ID,
        "evaluator_phase": rescore_axes.EVALUATOR_PHASE,
        "inputs": {
            "v0_1_contract_sha256": v0_1_sha,
            "v0_2_contract_sha256": v0_2_sha,
            "l1_criterion_sha256": vs["l1_criterion_sha256"],
            "lifecycle_sha256": vs["lifecycle_sha256"],
            "source_map_sha256": vs["source_map_sha256"],
            "corpus_manifest_sha256": vs["corpus_manifest_sha256"],
            "rescore_module_sha256": rescore_sha,
            "rescore_axes_module_sha256": axes_sha,
            "annotation_schema_sha256": sha256_file(ANNOTATION_SCHEMA),
            "v1_results_sha256": sha256_file(V1_RESULTS),
        },
        "version_binding": {
            "declared_codes": vs["code_count"],
            "bijective_pairs": vs["bijective_pairs"],
            "basis": "source_map",
            "refs_bound_by": "p2-holdout-v3.source-map/v0.2 (doc_code -> base_doc_code, version_number)",
            "date_semantics": "L1 p2-stale-source-criterion-v1_1 (sentinel 未声明 => effective_to null / not_asserted)",
            "business_dates": {
                str(run["run_index"]): run["business_date"] for run in runs_out
            },
            "inference_used": False,
        },
        "aggregate": {
            "case_count": len(case_records),
            "new_axes": new_axes_counts,
            "old_axes": old_axes_counts,
            "hard_failures": new_hard,
            "old_hard_failures": old_hard,
            "unknown_cases": new_unknown,
            "changed_case_count": len(changed_cases),
            "state_change_cases": state_change_cases,
            "state_change_case_count": len(state_change_cases),
            "reason_only_cases": reason_only_cases,
            "reason_only_case_count": len(reason_only_cases),
            "axis_state_change_counts": axis_state_change_counts,
            "unchanged_case_count": len(case_records) - len(changed_cases),
            "reason_distribution": reason_distribution,
            "cross_user_gate_surface_affected": gate_surface_affected,
            "cross_user_conservative": conservative_cross_user,
        },
        "runs": runs_out,
        "changed_cases": changed_cases,
        "multi_turn_equivalence": equivalence_rows,
        "c25": c25,
        "calls": {"network": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
        "not_claimed": [
            "verified",
            "threshold_met",
            "release_ready",
            "release",
            "T207_pass",
            "all_axes_real_complete",
            "q1a3_complete",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "recompute-v2.json"
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("wrote", target)
    print("new_hard_failures:", new_hard)
    print("old_hard_failures:", old_hard)
    print("changed_case_count:", len(changed_cases))
    print("new_axes:", json.dumps(new_axes_counts, ensure_ascii=False))
    print("old_axes:", json.dumps(old_axes_counts, ensure_ascii=False))
    return 0


def _c25_detail(
    records: Sequence[Mapping[str, Any]],
    vs: Mapping[str, Any],
    old_hard: Sequence[str],
    new_hard: Sequence[str],
) -> dict[str, Any]:
    row = next((item for item in records if item["case_id"] == "H2V3-C25"), None)
    if row is None:
        return {"present": False}
    return {
        "present": True,
        "run_index": row["run_index"],
        "scenario_id": row["scenario_id"],
        "old_safety": row["old_axes"]["safety"],
        "new_safety": {
            "state": row["new_axes"]["safety"]["state"],
            "reason": row["new_axes"]["safety"]["reason"],
        },
        "safety_provenance": row["safety_provenance"],
        "safety_audit_codes": row["safety_audit_codes"],
        "old_in_hard_failures": "H2V3-C25" in old_hard,
        "new_in_hard_failures": "H2V3-C25" in new_hard,
        "changed_axes": row["changed_axes"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
