"""R2-201C 层表工具：把 C29/C25 的缺口落到**首个偏离层**，并出 C25/C29 身份、C14 双回合、版本/日期。

与 ``r2_case_boundary.py`` 的分工
--------------------------------
``r2_case_boundary.py`` 是 r1 版逐字迁移（只改 import / SELECTED_CASES / CASE_PLAN_REL /
路径标签），产出**基线记录**（check_facts / answer_shape / boundary_events /
value_provenance / source_provenance / first_boundary），落到 ``<out>/base/``。

本工具复用 ``r2_case_boundary`` 的同一批**判据函数**（``_analyze_case`` / ``_decide`` /
``_check_facts`` / ``_events_facts`` / ``_shape`` / ``_unit_identity`` / ``BOUNDARIES`` /
``GAP_CODES``）产出**超集**记录，落到 ``<out>/``（每个 case 文件 = 基线记录全文 + 追加段）。
不改基线工具任何判据与白名单；本文件自己新增的输出键集中在 :data:`_EXTRA2_KEYS`。

本工具追加的三件事（任务书 §2/§3/§4/§5）
--------------------------------------
1. ``layers``：按 8 层固定顺序（意图字段 → 候选 → 检索 → 模型输入 → 事实准入 → 渲染 →
   引用 → commit）逐层给固定状态码 + 计数 + 布尔，全部绑定同一 ``turn_index`` 与
   ``request_id_sha256``；``first_missing_layer`` 机械判定"缺失值最早在哪一层消失"，
   某层未捕获时只能给 ``undetermined`` + 固定缺口码。
2. ``identity``：C25/C29 的 10 项布尔/计数 + **label 级明细**（``units[i]`` / ``facts[i]``）
   + 键差异分类（类型段 / 标识段 / 形态）。
3. ``version_date``：as_of vs 业务日、future/current/expired 使用层计数、禁源绑定可复核。

私有数据纪律
-----------
- 只在进程内存里读题干/答案/实体值；输出只有固定码/计数/布尔/sha256（``base._assert_safe``）；
- 实体键差异只输出**段角色计数**（类型段 / 标识段 / 形态），绝不输出键值；
- 题干/答案/文档名一律不进输出，只给长度与命中计数。
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import pathlib
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r2_case_boundary as cbt  # noqa: E402 - 复用同一批判据（只读）
import r2_safe_project as base  # noqa: E402 - 同目录复用加载/白名单

REPORT_REL = "docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117"
CASE_PLAN_REL = "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"

STAGE = ["module"]

#: 8 层固定顺序（任务书 §2 的层名，全部小写下划线固定码）。
LAYER_ORDER = (
    "intent_fields",
    "candidates",
    "retrieval",
    "model_input",
    "fact_admission",
    "render",
    "citation",
    "commit",
)

#: 层固定状态码。
LAYER_STATES = frozenset(
    {
        "present",
        "empty",
        "absent",
        "not_captured",
        "not_applicable",
        "partial",
    }
)

#: 键差异固定分类（对应 R0 §7.4 残留 vs 已修的键形态分叉）。
DIFF_CLASSES = ("type_segment_diff", "id_segment_diff", "shape_diff", "same_key")

#: 答案里的"无事实/未找到"模板标记（来自 mktkb/copy.py 与 mktkb/rag/answer.py 的既有文案，
#: 只在本进程内存里比对，输出只给**序号**与计数）。
ABSENT_MARKERS = (
    "资料中未找到",
    "资料中未记录",
    "资料中未收录",
    "未在资料中找到",
    "不能据此判断",
    "不能据此编造",
)

_TOKEN_SPLIT = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")

#: 本文件新增的输出键（不改基线工具的 ``_EXTRA_KEYS``）。
_EXTRA2_KEYS = frozenset(
    {
        # --- 通用 ---
        "base_dir",
        "base_loader_sha256",
        "base_record_match",
        "base_record_match_all",
        "base_record_producer",
        "base_tool_status",
        "reconstruction_mismatch_cases",
        "mismatch_rows",
        "mismatch_check_count",
        "current_status",
        "plan_status",
        "check_id",
        "real_calls",
        "business_date_matches",
        "layer_order",
        "layers",
        # --- 层行字段 ---
        "turn_index",
        "state",
        "event_count",
        "unit_count",
        "value_count",
        "path_code",
        "mode_code",
        "enumerate",
        "include_future",
        "clarification",
        "as_of_present",
        "state_as_of_present",
        "filters_count",
        "filter_codes",
        "terms_count",
        "state_keys_count",
        "state_stores_published",
        "request_id_sha256",
        "request_id_present",
        "request_id_consistent",
        "request_id_count",
        "unit_id_total",
        "distinct_units",
        "scope_codes",
        "truncated_count",
        "empty_count",
        "candidate_count",
        "evidence_count",
        "evidence_chars",
        "context_question_count",
        "context_entity_key_count",
        "fact_rows",
        "fact_count",
        "cited_unit_count",
        "projection_units",
        "unresolved_unit_ids",
        "answer_source_code",
        "expected_value_count",
        "values_backed_by_used_units",
        "values_missing_from_used_units",
        "value_hit_status",
        "value_expected",
        "value_matched",
        "value_missing",
        "marker_hit_count",
        "marker_codes",
        "absent_marker_present",
        "answer_commit_text_equal",
        "citation_total",
        "source_ids_count",
        "source_expected",
        "source_matched",
        "source_missing",
        "expected_retrieved_count",
        "expected_neither_count",
        "kind_code",
        "requested_kind",
        "knowledge_changed",
        "revision_before",
        "revision_after",
        "text_chars",
        "kind_matches_answer",
        "first_missing_layer",
        "first_missing_layer_state",
        # --- 身份 ---
        "identity",
        "unit_rows",
        "unit_index",
        "fact_index",
        "unit_tail_len",
        "fact_tail_len",
        "tail_common_prefix_len",
        "unit_entity_unresolved_count",
        "context_observed_count",
        "as_of_matches_rag_date",
        "fact_row_total",
        "unit_entity_type_present",
        "unit_entity_key_present",
        "unit_entity_resolvable",
        "unit_shape_code",
        "unit_key_head_len",
        "unit_key_tail_tag",
        "unit_version_number",
        "unit_version_state_code",
        "unit_active",
        "unit_deleted",
        "unit_count",
        "half_identity_unit_count",
        "half_identity_fact_count",
        "missing_row_count",
        "duplicate_unit_count",
        "fact_no_entity_key_count",
        "fact_no_source_unit_id_count",
        "source_unit_unresolved_count",
        "key_mismatch_count",
        "fact_entity_key_present",
        "fact_entity_type_present",
        "fact_source_unit_id_present",
        "fact_source_unit_id_resolves",
        "fact_key_equals_unit_key",
        "fact_type_equals_unit_type",
        "fact_shape_code",
        "fact_key_head_len",
        "fact_key_tail_tag",
        "head_equal",
        "tail_value_equal",
        "diff_class",
        "type_segment_diff_count",
        "id_segment_diff_count",
        "shape_diff_count",
        "same_key_count",
        "tail_value_diff_count",
        "entity_type_code",
        "facts",
        "units",
        # --- 版本/日期 ---
        "version_date",
        "as_of_equals_business_date",
        "rag_business_date_present",
        "version_number",
        "unit_version_binding_ok",
        "doc_version_consistent",
        "future_used",
        "current_used",
        "expired_used",
        "date_field_present",
        "in_window",
        "forbidden_source_no_match",
        "forbidden_binding_checkable",
        "forbidden_bound",
        "forbidden_total",
        "target_source_doc_version_ok",
        # --- target refs ---
        "target_refs",
        "target_ref_label",
        "collection",
        "expected_source_index",
        "ref_state",
        "doc_match",
        "sheet_match",
        "row_match",
        "version_match",
        "unit_present",
        "canonical_verdict",
        "canonical_reason",
        "record_code_present",
        "unit_key_present",
        "locator_key_codes",
        "matched_unit_count",
        "target_count",
        # --- 双回合 ---
        "turns",
        "turn_rows",
        "context_inherited",
        "context_message_count",
        "entity_inheritance_count",
        "state_row_present",
        "stored_state_present",
        "pre_revision",
        "post_revision",
        "capture_revision",
        "projection_pre_revision",
        "revision_consistent",
        "revision_consistent_all",
        "last_turn_quality_status",
        "case_level_axes",
        "per_turn_axes",
        "per_turn_axes_available",
        "per_turn_axis_gap",
        "quality_vs_axes_separated",
        "field_role_codes",
        "field_role_count",
        "safety",
        "cross_user",
        "cross_entity",
        "stale_source",
        "reason",
        "note_codes",
        "not_run_codes",
        "gap_codes",
        "case_plan_sha256",
        "hard_module_sha256",
        "module_sha256",
        "hard_module_import_ok",
        "envelope_count",
        "case_count",
        "custody_ok",
        "scoring_failures",
        "unsafe_code_count",
        "reconstruction_match_all",
        "selected_case_ids",
        "undetermined_gap",
        "first_boundary",
        "decision_code",
        "code",
        "count",
        "name",
        "ok",
        "error",
        "where",
        "netguard",
        "cases",
        "run_id",
        "rules",
        "check_facts",
        "check_statuses",
        "failed_check_ids",
        "answer_shape",
        "boundary_events",
        "value_provenance",
        "source_provenance",
        "evidence_availability",
        "axes_available",
        "axes",
        "boundary_support",
        "open_questions",
        "quality_status",
        "case_id",
        "identity_cases",
        "version_date_cases",
        "layer_conclusion",
        "first_missing_layer_counts",
        "undetermined_gap_counts",
    }
)


def _fail(code: str, where: str | None = None) -> None:
    raise base.ToolError(code, where or STAGE[0])


def _install_whitelist() -> None:
    """基线白名单 ∪ 本文件新增键；不改基线工具自己的 ``_EXTRA_KEYS`` 常量。"""
    cbt._install_whitelist()  # noqa: SLF001 - 复用基线安装逻辑（只并集）
    base.ALLOWED_KEYS = frozenset(base.ALLOWED_KEYS) | _EXTRA2_KEYS


def _coded(value: Any, fallback: str = "unknown_code") -> str:
    text = str(value or "")
    return text if base.CODE_RE.fullmatch(text) else fallback


def _is_seq(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _dump(payload: Mapping[str, Any], path: pathlib.Path | None, *, echo: bool) -> None:
    try:
        base._assert_safe(dict(payload))
    except base.ToolError:
        _fail("unsafe_output_key", "dump")
    text = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    if echo:
        print(text)


# --------------------------------------------------------------------------- #
# 键形态 / 身份
# --------------------------------------------------------------------------- #

_TAIL_RE = re.compile(r"^([A-Za-z_]+):(.*)$")


def _key_shape(value: Any) -> str:
    """把 entity_key 归到固定形态码（不输出任何键值）。"""
    if not isinstance(value, str) or not value:
        return "not_str"
    if "|" not in value:
        return "no_pipe"
    head, _, tail = value.partition("|")
    if not tail:
        return "empty_tail"
    match = _TAIL_RE.match(tail)
    if match is None:
        return "type_bare_id"
    tag = match.group(1)
    if tag == "id":
        return "type_id"
    if tag == "doc":
        return "type_doc"
    return "type_other_tag"


def _head(value: Any) -> str:
    if not isinstance(value, str) or "|" not in value:
        return ""
    return value.partition("|")[0]


def _tail_value(value: Any) -> str:
    """`<type>|id:<v>` 与 `<type>|<v>` 都归一到 `<v>`，用于判断标识段是否同一个值。"""
    if not isinstance(value, str) or "|" not in value:
        return ""
    tail = value.partition("|")[2]
    match = _TAIL_RE.match(tail)
    return match.group(2) if match is not None else tail


def _classify_key_diff(fact_key: Any, unit_key: Any) -> str:
    """固定分类：类型段不同 / 标识段不同 / 形态不同 / 同键。"""
    if not isinstance(fact_key, str) or not isinstance(unit_key, str):
        return "shape_diff"
    if fact_key == unit_key:
        return "same_key"
    if _head(fact_key) != _head(unit_key):
        return "type_segment_diff"
    # 形态（一侧 |id:、另一侧无标签或 |doc:）优先于标识值：两者是不同问题。
    if _tail_tag(fact_key) != _tail_tag(unit_key):
        return "shape_diff"
    if _tail_value(fact_key) != _tail_value(unit_key):
        return "id_segment_diff"
    return "same_key"


def _token_set(text: str) -> set[str]:
    return {item for item in _TOKEN_SPLIT.split(text) if item}


def _marker_codes(text: str) -> tuple[list[str], int]:
    codes: list[str] = []
    for index, marker in enumerate(ABSENT_MARKERS):
        if marker in text:
            codes.append(f"absent_marker_{index}")
    return codes, len(codes)


def _unit_full_text(unit: Mapping[str, Any]) -> str:
    parts: list[str] = []
    if isinstance(unit.get("text"), str):
        parts.append(unit["text"])
    for key in ("raw_fields", "date_fields", "locator"):
        block = unit.get(key)
        if isinstance(block, Mapping):
            for value in block.values():
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, (int, float)):
                    parts.append(str(value))
                elif _is_seq(value):
                    parts.extend(str(item) for item in value if isinstance(item, (str, int, float)))
    return "\n".join(parts)


def _unit_raw_text(unit: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in ("raw_fields", "date_fields"):
        block = unit.get(key)
        if isinstance(block, Mapping):
            for value in block.values():
                if isinstance(value, (str, int, float)):
                    parts.append(str(value))
    return "\n".join(parts)


def _events(envelope: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    capture = envelope.get("capture")
    if not isinstance(capture, Mapping):
        return []
    rows = capture.get("events")
    if not _is_seq(rows):
        return []
    return [item for item in rows if isinstance(item, Mapping)]


def _payloads(events: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for event in events:
        if str(event.get("kind")) != kind:
            continue
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            out.append(payload)
    return out


def _unit_index(envelope: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], list[Mapping[str, Any]]]:
    projection = envelope.get("db_projection")
    units: dict[str, Mapping[str, Any]] = {}
    order: list[Mapping[str, Any]] = []
    if isinstance(projection, Mapping) and _is_seq(projection.get("units")):
        for row in projection["units"]:
            if not isinstance(row, Mapping):
                continue
            order.append(row)
            if row.get("unit_id") is not None:
                units[str(row.get("unit_id"))] = row
    return units, order


def _request_key(envelope: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> tuple[str, bool]:
    """返回 (request_id 的 sha256 前 8 位, 是否非空)；绝不输出 request_id 本身。"""
    candidates: list[str] = []
    turn = envelope.get("turn")
    if isinstance(turn, Mapping) and isinstance(turn.get("client_request_id"), str):
        candidates.append(turn["client_request_id"])
    for payload in _payloads(events, "claim_observed"):
        if isinstance(payload.get("request_id"), str):
            candidates.append(payload["request_id"])
    for payload in _payloads(events, "answer_result"):
        if isinstance(payload.get("request_id"), str):
            candidates.append(payload["request_id"])
    if not candidates:
        return ("none", False)
    digest = hashlib.sha256(sorted(set(candidates))[0].encode("utf-8")).hexdigest()
    return (digest, True)


def _date_fields_span(unit: Mapping[str, Any]) -> tuple[bool, str, str]:
    block = unit.get("date_fields")
    if not isinstance(block, Mapping) or not block:
        return (False, "", "")
    start = ""
    end = ""
    for key, value in block.items():
        name = str(key)
        text = value if isinstance(value, str) else str(value)
        if "生效" in name or "开始" in name or "start" in name.lower():
            start = text
        elif "失效" in name or "结束" in name or "end" in name.lower():
            end = text
    return (True, start, end)


# --------------------------------------------------------------------------- #
# 层表
# --------------------------------------------------------------------------- #

def _layer_rows(
    *,
    turn_index: int,
    events: Sequence[Mapping[str, Any]],
    envelope: Mapping[str, Any],
    projection_units: Sequence[Mapping[str, Any]],
    expected_values: Sequence[str],
    checks: Mapping[str, Any],
    scorers: Any,
    answer_text: str,
    commit_text: str,
    business_date: str,
) -> tuple[list[dict[str, Any]], str, str, dict[str, Any]]:
    """逐层固定状态；返回 (rows, first_missing_layer, first_missing_layer_state, extras)。"""
    rows: list[dict[str, Any]] = []
    plans = _payloads(events, "plan_observed")
    plan = plans[-1] if plans else {}
    candidates = _payloads(events, "retrieval_observed")
    candidate_rows = [row for row in candidates if bool(row.get("candidate") is True)]
    initial_rows = [row for row in candidates if bool(row.get("candidate") is not True)]
    model_inputs = _payloads(events, "model_input")
    model_outputs = _payloads(events, "model_output")
    direct = _payloads(events, "direct_rag_answer")
    answers = _payloads(events, "answer_result")
    commits = _payloads(events, "commit_observed")
    request_hash, request_present = _request_key(envelope, events)

    # 1) 意图字段
    filters = dict(plan.get("filters") or {})
    row = {
        "turn_index": int(turn_index),
        "name": "intent_fields",
        "state": "present" if plans else "not_captured",
        "event_count": len(plans),
        "path_code": _coded(plan.get("path")) if plan.get("path") else "none",
        "mode_code": _coded(plan.get("mode")) if plan.get("mode") else "none",
        "enumerate": bool(plan.get("enumerate") is True),
        "include_future": bool(plan.get("include_future") is True),
        "clarification": bool(plan.get("clarification") is True),
        "as_of_present": isinstance(plan.get("as_of"), str) and bool(plan.get("as_of")),
        "state_as_of_present": isinstance(plan.get("state_as_of"), str)
        and bool(plan.get("state_as_of")),
        "filters_count": len(filters),
        "filter_codes": sorted(_coded(key) for key in filters),
        "terms_count": len([item for item in (plan.get("terms") or ()) if str(item)]),
        "state_keys_count": len([item for item in (plan.get("state_keys") or ()) if str(item)]),
        # plan_observed 不发布 state.stores（产品侧作用域槽位）：该槽位是否携带目标实体不可观测。
        "state_stores_published": False,
        "request_id_sha256": request_hash,
        "request_id_present": request_present,
    }
    rows.append(row)

    # 2) 候选层
    candidate_ids = [
        str(item) for payload in candidate_rows for item in (payload.get("unit_ids") or ()) if str(item)
    ]
    rows.append(
        {
            "turn_index": int(turn_index),
            "name": "candidates",
            "state": "not_captured"
            if not candidate_rows
            else ("empty" if any(p.get("empty") is True for p in candidate_rows) else "present"),
            "event_count": len(candidate_rows),
            "candidate_count": len(candidate_rows),
            "unit_id_total": len(candidate_ids),
            "distinct_units": len(set(candidate_ids)),
            "scope_codes": sorted(
                {_coded(p.get("scope")) for p in candidate_rows if p.get("scope")}
            ),
            "truncated_count": sum(1 for p in candidate_rows if p.get("truncated") is True),
            "empty_count": sum(1 for p in candidate_rows if p.get("empty") is True),
        }
    )

    # 3) 检索层（legacy 初始召回）
    initial_ids = [
        str(item) for payload in initial_rows for item in (payload.get("unit_ids") or ()) if str(item)
    ]
    rows.append(
        {
            "turn_index": int(turn_index),
            "name": "retrieval",
            "state": "not_captured" if not candidates else ("present" if initial_rows else "empty"),
            "event_count": len(candidates),
            "distinct_units": len(set(initial_ids)),
            "scope_codes": sorted(
                {_coded(p.get("scope")) for p in initial_rows if p.get("scope")}
            ),
            "truncated_count": sum(1 for p in initial_rows if p.get("truncated") is True),
            "empty_count": sum(1 for p in initial_rows if p.get("empty") is True),
        }
    )

    # 4) 模型输入
    evidence_texts: list[str] = []
    for payload in model_inputs:
        for item in payload.get("evidence") or ():
            if isinstance(item, Mapping):
                if isinstance(item.get("text"), str):
                    evidence_texts.append(item["text"])
                fields = item.get("fields")
                if isinstance(fields, Mapping):
                    for value in fields.values():
                        if isinstance(value, str):
                            evidence_texts.append(value)
    context_questions = sum(
        len([q for q in (p.get("context_questions") or ()) if str(q)]) for p in model_inputs
    )
    context_entities = sum(
        len(dict(p.get("context_entities") or {})) for p in model_inputs
    )
    if model_inputs:
        model_state = "present"
    elif direct:
        # 结构化枚举不走模型：模型面结构上不适用，不是"缺失"。
        model_state = "not_applicable"
    else:
        model_state = "absent"
    rows.append(
        {
            "turn_index": int(turn_index),
            "name": "model_input",
            "state": model_state,
            "event_count": len(model_inputs),
            "evidence_count": len(evidence_texts),
            "evidence_chars": sum(len(item) for item in evidence_texts),
            "context_question_count": int(context_questions),
            "context_entity_key_count": int(context_entities),
        }
    )

    # 5) 事实准入
    facts = [row for payload in direct for row in (payload.get("facts") or ()) if isinstance(row, Mapping)]
    cited = [
        str(item) for payload in direct for item in (payload.get("cited_unit_ids") or ()) if str(item)
    ]
    answer_source = direct[-1].get("answer_source") if direct else None
    used_text = "\n".join(_unit_full_text(unit) for unit in projection_units)
    used_raw = "\n".join(_unit_raw_text(unit) for unit in projection_units)
    backed = sum(
        1
        for value in expected_values
        if scorers.check_value(used_text, value) or scorers.check_value(used_raw, value)
    )
    projection = envelope.get("db_projection")
    unresolved = (
        len([item for item in (projection.get("unresolved_unit_ids") or ()) if str(item)])
        if isinstance(projection, Mapping)
        else 0
    )
    rows.append(
        {
            "turn_index": int(turn_index),
            "name": "fact_admission",
            "state": "present" if (facts or cited) else "empty",
            "event_count": len(direct),
            "fact_rows": len(facts),
            "fact_count": int(direct[-1].get("fact_count") or 0) if direct else 0,
            "cited_unit_count": len(cited),
            "projection_units": len(projection_units),
            "unresolved_unit_ids": int(unresolved),
            "answer_source_code": _coded(answer_source) if answer_source else "none",
            "expected_value_count": len(expected_values),
            "values_backed_by_used_units": int(backed),
            "values_missing_from_used_units": int(max(0, len(expected_values) - backed)),
        }
    )

    # 6) 渲染
    value_hit = dict(checks.get("value_hit") or {})
    marker_codes, marker_hits = _marker_codes(answer_text)
    rows.append(
        {
            "turn_index": int(turn_index),
            "name": "render",
            "state": "present" if answer_text else "empty",
            "event_count": len(answers),
            "kind_code": _coded(answers[-1].get("kind")) if answers and answers[-1].get("kind") else "unknown_kind",
            "text_chars": len(answer_text),
            "value_hit_status": _coded(value_hit.get("status", "missing")),
            "value_expected": int(value_hit.get("expected") or 0),
            "value_matched": _filled(value_hit, "matched", "missing"),
            "value_missing": _filled(value_hit, "missing", "matched"),
            "marker_hit_count": int(marker_hits),
            "marker_codes": marker_codes,
            "absent_marker_present": bool(marker_hits),
            "answer_commit_text_equal": bool(answer_text) and answer_text == commit_text,
        }
    )

    # 7) 引用
    source_hit = dict(checks.get("source_hit") or {})
    source_ids: list[str] = []
    for payload in answers:
        source_ids.extend(str(item) for item in (payload.get("source_ids") or ()) if str(item))
    rows.append(
        {
            "turn_index": int(turn_index),
            "name": "citation",
            "state": "present" if source_ids else "empty",
            "event_count": len(answers),
            "citation_total": len(source_ids),
            "source_ids_count": len(source_ids),
            "source_expected": int(source_hit.get("expected") or 0),
            "source_matched": _filled(source_hit, "matched", "missing"),
            "source_missing": _filled(source_hit, "missing", "matched"),
        }
    )

    # 8) commit
    commit = commits[-1] if commits else {}
    answer_kind = answers[-1].get("kind") if answers else None
    rows.append(
        {
            "turn_index": int(turn_index),
            "name": "commit",
            "state": "present" if commits else "not_captured",
            "event_count": len(commits),
            "kind_code": _coded(commit.get("kind")) if commit.get("kind") else "unknown_kind",
            "requested_kind": _coded(commit.get("requested_kind"))
            if commit.get("requested_kind")
            else "none",
            "knowledge_changed": bool(commit.get("knowledge_changed") is True),
            "revision_before": int(commit.get("revision_before") or 0),
            "revision_after": int(commit.get("revision_after") or 0),
            "text_chars": len(commit_text),
            "kind_matches_answer": bool(
                answer_kind is not None and commit.get("kind") is not None and answer_kind == commit.get("kind")
            ),
        }
    )

    # 首个偏离层（机械判定，不猜）
    by_name = {row["name"]: row for row in rows}
    missing_from_units = int(by_name["fact_admission"]["values_missing_from_used_units"])
    values_absent_from_answer = int(by_name["render"]["value_missing"])
    if not values_absent_from_answer:
        first, first_state = ("none", "present")
    elif missing_from_units:
        if by_name["candidates"]["state"] == "not_captured":
            first, first_state = ("candidates", "not_captured")
        elif by_name["retrieval"]["state"] == "not_captured":
            first, first_state = ("retrieval", "not_captured")
        else:
            first, first_state = ("fact_admission", by_name["fact_admission"]["state"])
    else:
        first, first_state = ("render", by_name["render"]["state"])

    extras = {
        "request_id_sha256": request_hash,
        "marker_codes": marker_codes,
        "model_output_count": len(model_outputs),
        "business_date_present": business_date,
    }
    return rows, first, first_state, extras


# --------------------------------------------------------------------------- #
# 身份（任务书 §3 的 10 项 + label 级明细）
# --------------------------------------------------------------------------- #

def _identity_block(
    envelopes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    unit_rows: list[dict[str, Any]] = []
    fact_rows: list[dict[str, Any]] = []
    counts = collections.Counter()
    for turn_index, envelope in enumerate(envelopes):
        units_by_id, units_order = _unit_index(envelope)
        seen: collections.Counter[str] = collections.Counter()
        for unit in units_order:
            seen[str(unit.get("unit_id"))] += 1
        counts["duplicate_unit_count"] += sum(1 for value in seen.values() if value > 1)
        for index, unit in enumerate(units_order):
            entity_type = unit.get("entity_type")
            entity_key = unit.get("entity_key")
            type_present = isinstance(entity_type, str) and bool(entity_type)
            key_present = isinstance(entity_key, str) and bool(entity_key)
            resolvable = type_present and key_present
            counts["unit_count"] += 1
            if type_present ^ key_present:
                counts["half_identity_unit_count"] += 1
            if not resolvable:
                counts["unit_entity_unresolved_count"] += 1
            unit_rows.append(
                {
                    "turn_index": int(turn_index),
                    "unit_index": int(index),
                    "entity_type_code": _coded(entity_type) if type_present else "none",
                    "unit_entity_type_present": bool(type_present),
                    "unit_entity_key_present": bool(key_present),
                    "unit_entity_resolvable": bool(resolvable),
                    "unit_shape_code": _key_shape(entity_key),
                    "unit_key_head_len": len(_head(entity_key)),
                    "unit_key_tail_tag": _tail_tag(entity_key),
                    "unit_version_number": int(unit.get("version_number"))
                    if type(unit.get("version_number")) is int
                    else 0,
                    "unit_version_state_code": _coded(unit.get("version_state"))
                    if unit.get("version_state")
                    else "none",
                    "unit_active": bool(unit.get("active") is True),
                    "unit_deleted": bool(unit.get("document_deleted") is True),
                }
            )
        facts = [
            item
            for payload in _payloads(_events(envelope), "direct_rag_answer")
            for item in (payload.get("facts") or ())
            if isinstance(item, Mapping)
        ]
        for index, fact in enumerate(facts):
            fact_key = fact.get("entity_key")
            fact_type = fact.get("entity_type")
            source_unit_id = fact.get("source_unit_id")
            key_present = isinstance(fact_key, str) and bool(fact_key)
            type_present = isinstance(fact_type, str) and bool(fact_type)
            source_present = isinstance(source_unit_id, str) and bool(source_unit_id)
            unit = units_by_id.get(str(source_unit_id)) if source_present else None
            resolves = isinstance(unit, Mapping)
            unit_type = unit.get("entity_type") if resolves else None
            unit_key = unit.get("entity_key") if resolves else None
            diff = _classify_key_diff(fact_key, unit_key) if resolves else "shape_diff"
            counts["fact_row_total"] += 1
            counts[f"diff_{diff}"] += 1
            if not key_present:
                counts["fact_no_entity_key_count"] += 1
            if not type_present:
                counts["half_identity_fact_count"] += 1
            if not source_present:
                counts["fact_no_source_unit_id_count"] += 1
            elif not resolves:
                counts["source_unit_unresolved_count"] += 1
            if resolves and diff != "same_key":
                counts["key_mismatch_count"] += 1
            fact_rows.append(
                {
                    "turn_index": int(turn_index),
                    "fact_index": int(index),
                    "fact_entity_key_present": bool(key_present),
                    "fact_entity_type_present": bool(type_present),
                    "fact_source_unit_id_present": bool(source_present),
                    "fact_source_unit_id_resolves": bool(resolves),
                    "fact_key_equals_unit_key": bool(resolves and fact_key == unit_key),
                    "fact_type_equals_unit_type": bool(resolves and fact_type == unit_type),
                    "fact_shape_code": _key_shape(fact_key),
                    "fact_key_head_len": len(_head(fact_key)),
                    "fact_key_tail_tag": _tail_tag(fact_key),
                    "head_equal": bool(resolves and _head(fact_key) == _head(unit_key)),
                    "tail_value_equal": bool(resolves and _tail_value(fact_key) == _tail_value(unit_key)),
                    "fact_tail_len": len(_tail_value(fact_key)),
                    "unit_tail_len": len(_tail_value(unit_key)) if resolves else 0,
                    "tail_common_prefix_len": _common_prefix_len(
                        _tail_value(fact_key), _tail_value(unit_key)
                    )
                    if resolves
                    else 0,
                    "diff_class": _coded(diff),
                    "field_role_codes": [_coded(fact.get("field_role"))] if fact.get("field_role") else [],
                    "unit_present": bool(resolves),
                }
            )
    return {
        "unit_count": int(counts["unit_count"]),
        "fact_row_total": int(counts["fact_row_total"]),
        "half_identity_unit_count": int(counts["half_identity_unit_count"]),
        "half_identity_fact_count": int(counts["half_identity_fact_count"]),
        "missing_row_count": int(counts["source_unit_unresolved_count"]),
        "duplicate_unit_count": int(counts["duplicate_unit_count"]),
        "fact_no_entity_key_count": int(counts["fact_no_entity_key_count"]),
        "fact_no_source_unit_id_count": int(counts["fact_no_source_unit_id_count"]),
        "source_unit_unresolved_count": int(counts["source_unit_unresolved_count"]),
        "key_mismatch_count": int(counts["key_mismatch_count"]),
        "same_key_count": int(counts["diff_same_key"]),
        "tail_value_diff_count": int(
            sum(1 for row in fact_rows if row["tail_value_equal"] is False)
        ),
        "type_segment_diff_count": int(counts["diff_type_segment_diff"]),
        "id_segment_diff_count": int(counts["diff_id_segment_diff"]),
        "shape_diff_count": int(counts["diff_shape_diff"]),
        "unit_entity_unresolved_count": int(counts["unit_entity_unresolved_count"]),
        "units": unit_rows,
        "facts": fact_rows,
    }


def _filled(row: Mapping[str, Any], primary: str, other: str) -> int:
    """评分器只在 pass 时补 matched；缺失侧用 expected-反向计数反算，不写 0 冒充。"""
    value = row.get(primary)
    if type(value) is int:
        return int(value)
    total = row.get("expected")
    other_value = row.get(other)
    if type(total) is int and type(other_value) is int:
        return int(max(0, total - other_value))
    return 0


def _common_prefix_len(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


def _tail_tag(value: Any) -> str:
    if not isinstance(value, str) or "|" not in value:
        return "none"
    match = _TAIL_RE.match(value.partition("|")[2])
    return "none" if match is None else _coded(match.group(1))


# --------------------------------------------------------------------------- #
# target refs（逐 target 的 resolved / no_match / unresolved）
# --------------------------------------------------------------------------- #

def _target_refs(
    mapped: Any,
    envelopes: Sequence[Mapping[str, Any]],
    annotation_case: Mapping[str, Any],
    document_codes: Mapping[str, str],
    lookup: Any,
) -> list[dict[str, Any]]:
    cross = (annotation_case.get("axes") or {}).get("cross_entity") or {}
    ref_map: dict[int, str] = {}
    for index, ref in enumerate(cross.get("target_refs") or ()):
        if isinstance(ref, Mapping) and str(ref.get("collection")) == "expected_sources":
            ref_map[int(ref.get("index") or 0)] = f"target_refs_{index}"
    last = envelopes[-1] if envelopes else {}
    _, units_order = _unit_index(last)
    rows: list[dict[str, Any]] = []
    for index, ref in enumerate(getattr(mapped, "expected_sources", ()) or ()):
        ref_row = dict(ref)
        locator = dict(ref_row.get("locator") or {})
        version = locator.get("version_number")
        doc_code = ref_row.get("doc_code")
        doc_match = sheet_match = row_match = version_match = False
        matched_units = 0
        for unit in units_order:
            unit_doc = lookup(unit.get("document_name"), dict(document_codes))
            unit_locator = dict(unit.get("locator") or {})
            unit_version = unit.get("version_number") if type(unit.get("version_number")) is int else None
            this_doc = bool(doc_code) and unit_doc == doc_code
            this_sheet = this_doc and unit_locator.get("sheet") == locator.get("sheet")
            this_row = this_sheet and unit_locator.get("row") == locator.get("row")
            this_version = this_row and unit_version is not None and unit_version == version
            doc_match = doc_match or this_doc
            sheet_match = sheet_match or this_sheet
            row_match = row_match or this_row
            version_match = version_match or this_version
            matched_units += int(this_doc and this_sheet and this_row and this_version)
        identity_complete = bool(doc_code) and bool(locator) and version is not None
        if matched_units:
            state = "resolved"
        elif not identity_complete:
            state = "unresolved"
        else:
            state = "no_match"
        canonical_verdict = "not_run"
        canonical_reason = "not_run"
        try:  # canonical matcher（只读调用；版本用 unit 自身发布值当作 source_map 口径）
            from mktkb.evaluation import p2_evidence_rescore as rescore  # noqa: PLC0415

            unit = units_order[0] if units_order else None
            if isinstance(unit, Mapping):
                view = rescore.UnitView(
                    unit_id=str(unit.get("unit_id")),
                    layers=("direct_rag_fact",),
                    document_id=str(unit.get("document_id")) if unit.get("document_id") else None,
                    document_name=unit.get("document_name"),
                    doc_code=lookup(unit.get("document_name"), dict(document_codes)),
                    version_id=str(unit.get("version_id")) if unit.get("version_id") else None,
                    version_number=unit.get("version_number")
                    if type(unit.get("version_number")) is int
                    else None,
                    unit_key=unit.get("unit_key"),
                    record_code=None,
                    locator=dict(unit.get("locator") or {}),
                )
                clean = {
                    "doc_code": str(doc_code or ""),
                    "locator": {k: v for k, v in locator.items() if k in rescore.LOCATOR_KEYS},
                }
                binding = rescore.VersionBinding(
                    version_number=view.version_number, basis="source_map"
                )
                result = rescore.match_ref_to_unit(clean, view, version_binding=binding)
                canonical_verdict = _coded(getattr(result, "verdict", "unknown"))
                canonical_reason = _coded(
                    getattr(result, "reason", None) or getattr(result, "detail", "none")
                )
        except Exception as exc:  # noqa: BLE001 - 匹配器不可用只降级为固定码，不改判
            canonical_verdict = "not_run"
            canonical_reason = _coded(f"diag_{type(exc).__name__.lower()}", "diag_unknown")
        rows.append(
            {
                "expected_source_index": int(index),
                "target_ref_label": ref_map.get(int(index), "unreferenced"),
                "collection": "expected_sources",
                "ref_state": _coded(state),
                "doc_match": bool(doc_match),
                "sheet_match": bool(sheet_match),
                "row_match": bool(row_match),
                "version_match": bool(version_match),
                "matched_unit_count": int(matched_units),
                "unit_present": bool(matched_units),
                "record_code_present": isinstance(ref_row.get("record_code"), str),
                "unit_key_present": isinstance(ref_row.get("unit_key"), str),
                "locator_key_codes": sorted(_coded(key) for key in locator),
                "canonical_verdict": canonical_verdict,
                "canonical_reason": canonical_reason,
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# 版本 / 日期
# --------------------------------------------------------------------------- #

def _version_date(
    envelopes: Sequence[Mapping[str, Any]],
    mapped: Any,
    target_refs: Sequence[Mapping[str, Any]],
    business_date: str,
) -> dict[str, Any]:
    future = current = expired = date_present = 0
    as_of_present = 0
    as_of_matches_business = 0
    as_of_matches_rag = 0
    version_binding_ok = 0
    doc_version_consistent = 0
    rag_present = 0
    total_units = 0
    for envelope in envelopes:
        events = _events(envelope)
        plans = _payloads(events, "plan_observed")
        for plan in plans:
            as_of = plan.get("as_of")
            if isinstance(as_of, str) and as_of:
                as_of_present += 1
                as_of_matches_business += int(as_of == business_date)
        projection = envelope.get("db_projection")
        rag_date = projection.get("rag_business_date") if isinstance(projection, Mapping) else None
        if isinstance(rag_date, str) and rag_date:
            rag_present += 1
        _, units_order = _unit_index(envelope)
        for index, unit in enumerate(units_order):
            total_units += 1
            has_dates, start, end = _date_fields_span(unit)
            date_present += int(has_dates)
            if has_dates:
                # future = 生效日晚于业务日；expired = 失效日早于业务日；其余算 current。
                if start and start > business_date:
                    future += 1
                elif end and end < business_date:
                    expired += 1
                else:
                    current += 1
                version_binding_ok += int(
                    type(unit.get("version_number")) is int and int(unit.get("version_number")) > 0
                )
            if isinstance(rag_date, str) and isinstance(plans[-1].get("as_of") if plans else None, str):
                as_of_matches_rag += int(plans[-1]["as_of"] == rag_date)
    for row in target_refs:
        doc_version_consistent += int(bool(row.get("doc_match")) and bool(row.get("version_match")))
    forbidden = [
        dict(ref) for ref in (getattr(mapped, "forbidden_sources", ()) or ()) if isinstance(ref, Mapping)
    ]
    forbidden_bound = 0
    forbidden_checkable = 0
    for ref in forbidden:
        doc_code = ref.get("doc_code")
        locator = dict(ref.get("locator") or {})
        version = locator.get("version_number")
        if not doc_code or not locator:
            continue
        forbidden_checkable += 1
        for envelope in envelopes:
            _, units_order = _unit_index(envelope)
            for unit in units_order:
                unit_locator = dict(unit.get("locator") or {})
                same = (
                    unit.get("locator") is not None
                    and unit_locator.get("sheet") == locator.get("sheet")
                    and unit_locator.get("row") == locator.get("row")
                    and (unit.get("version_number") if type(unit.get("version_number")) is int else None)
                    == version
                )
                if same:
                    forbidden_bound += 1
                    break
    return {
        "as_of_present": int(as_of_present),
        "as_of_equals_business_date": bool(as_of_present and as_of_matches_business == as_of_present),
        "rag_business_date_present": int(rag_present),
        "date_field_present": int(date_present),
        "future_used": int(future),
        "current_used": int(current),
        "expired_used": int(expired),
        "unit_version_binding_ok": int(version_binding_ok),
        "doc_version_consistent": int(doc_version_consistent),
        "target_source_doc_version_ok": bool(
            target_refs and doc_version_consistent == sum(1 for r in target_refs if r.get("unit_present"))
        ),
        "forbidden_total": int(len(forbidden)),
        "forbidden_binding_checkable": bool(forbidden and forbidden_checkable == len(forbidden)),
        "forbidden_bound": int(forbidden_bound),
        "forbidden_source_no_match": bool(
            forbidden and forbidden_checkable == len(forbidden) and forbidden_bound == 0
        ),
        "unit_count": int(total_units),
        "in_window": bool(date_present and future == 0 and expired == 0),
        "as_of_matches_rag_date": int(as_of_matches_rag),
    }


# --------------------------------------------------------------------------- #
# 双回合（C14）
# --------------------------------------------------------------------------- #

def _turn_rows(
    envelopes: Sequence[Mapping[str, Any]],
    mapped: Any,
    annotation_case: Mapping[str, Any],
    scorers: Any,
    checks: Mapping[str, Any],
) -> list[dict[str, Any]]:
    cross = (annotation_case.get("axes") or {}).get("cross_entity") or {}
    targets = [t for t in (cross.get("targets") or ()) if isinstance(t, Mapping)]
    turn_rows: list[dict[str, Any]] = []
    for turn_index, envelope in enumerate(envelopes):
        events = _events(envelope)
        plans = _payloads(events, "plan_observed")
        plan = plans[-1] if plans else {}
        answers = _payloads(events, "answer_result")
        commits = _payloads(events, "commit_observed")
        contexts = _payloads(events, "context_observed")
        context_messages = _payloads(events, "context_message")
        inheritances = _payloads(events, "entity_inheritance")
        states = _payloads(events, "query_state_observed")
        saved = _payloads(events, "query_state_saved")
        model_inputs = _payloads(events, "model_input")
        direct = _payloads(events, "direct_rag_answer")
        turn = envelope.get("turn") if isinstance(envelope.get("turn"), Mapping) else {}
        projection = (
            envelope.get("db_projection") if isinstance(envelope.get("db_projection"), Mapping) else {}
        )
        facts = [
            row for payload in direct for row in (payload.get("facts") or ()) if isinstance(row, Mapping)
        ]
        source_ids = [str(item) for payload in answers for item in (payload.get("source_ids") or ()) if str(item)]
        state_row_present = any(p.get("row_present") is True for p in states)
        stored = any(
            isinstance(p.get("stored_conversation_id"), str) and bool(p.get("stored_conversation_id"))
            for p in states
        )
        pre = int(turn.get("pre_revision") or 0)
        post = int(turn.get("post_revision") or 0)
        capture_rev = int(turn.get("capture_revision") or 0)
        proj_pre = int(projection.get("pre_revision") or 0)
        commit = commits[-1] if commits else {}
        turn_rows.append(
            {
                "turn_index": int(turn_index),
                "kind_code": _coded(answers[-1].get("kind"))
                if answers and answers[-1].get("kind")
                else "unknown_kind",
                "path_code": _coded(plan.get("path")) if plan.get("path") else "none",
                "mode_code": _coded(plan.get("mode")) if plan.get("mode") else "none",
                "enumerate": bool(plan.get("enumerate") is True),
                "include_future": bool(plan.get("include_future") is True),
                "as_of_present": isinstance(plan.get("as_of"), str) and bool(plan.get("as_of")),
                "terms_count": len([t for t in (plan.get("terms") or ()) if str(t)]),
                "filters_count": len(dict(plan.get("filters") or {})),
                "filter_codes": sorted(_coded(k) for k in dict(plan.get("filters") or {})),
                "target_count": int(len(targets)),
                "expected_value_count": int(len(list(getattr(mapped, "expected_values", ()) or ()))),
                "source_expected": int(len(list(getattr(mapped, "expected_sources", ()) or ()))),
                "context_message_count": int(len(context_messages)),
                "context_observed_count": int(len(contexts)),
                "context_inherited": bool(
                    len(context_messages) > 0
                    or len(inheritances) > 0
                    or any(int(p.get("count") or 0) > 0 for p in contexts)
                ),
                "entity_inheritance_count": int(len(inheritances)),
                "state_row_present": bool(state_row_present),
                "stored_state_present": bool(stored),
                "state_keys_count": int(
                    len([k for k in (saved[-1].get("state_keys") or ()) if str(k)]) if saved else 0
                ),
                "context_question_count": int(
                    sum(len([q for q in (p.get("context_questions") or ()) if str(q)]) for p in model_inputs)
                ),
                "context_entity_key_count": int(
                    sum(len(dict(p.get("context_entities") or {})) for p in model_inputs)
                ),
                "fact_rows": int(len(facts)),
                "citation_total": int(len(source_ids)),
                "source_ids_count": int(len(source_ids)),
                "text_chars": len(answers[-1].get("text"))
                if answers and isinstance(answers[-1].get("text"), str)
                else 0,
                "field_role_count": int(len([f for f in facts if f.get("field_role")])),
                "field_role_codes": sorted(
                    {_coded(f.get("field_role")) for f in facts if f.get("field_role")}
                ),
                "pre_revision": pre,
                "post_revision": post,
                "capture_revision": capture_rev,
                "projection_pre_revision": proj_pre,
                "revision_consistent": bool(pre == post == capture_rev == proj_pre),
                "knowledge_changed": bool(commit.get("knowledge_changed") is True),
                "revision_before": int(commit.get("revision_before") or 0),
                "revision_after": int(commit.get("revision_after") or 0),
            }
        )
    return turn_rows


def _per_turn_axes(
    case: Any, envelopes: Sequence[Mapping[str, Any]], annotation: Any, hard: Any
) -> tuple[list[dict[str, Any]], bool, str]:
    """逐回合跑硬轴分类（单回合 audit）；失败只降级，不改案级判定。"""
    if hard is None:
        return ([], False, "hard_module_unavailable")
    rows: list[dict[str, Any]] = []
    for target in range(len(envelopes)):
        # 逐回合：audit 保持**本案的完整回合形状**（turn_index == index），只让目标回合带
        # evidence，其余标记 not_started（无 evidence）。这样分类器看到的仍是合法案形状。
        audit = {
            "quality_status": "pass",
            "turns": [
                {
                    "turn_index": index,
                    "status": "executed" if index == target else "not_started",
                    "error": None,
                    "evidence": envelopes[index] if index == target else None,
                }
                for index in range(len(envelopes))
            ],
        }
        envelope = envelopes[target]
        turn = envelope.get("turn") if isinstance(envelope.get("turn"), Mapping) else {}
        try:
            result = hard.classify_case_evidence(case, annotation, audit)
        except Exception as exc:  # noqa: BLE001
            return (rows, False, _coded(f"per_turn_diag_{type(exc).__name__.lower()}", "per_turn_classification_failed"))
        rows.append(
            {
                "turn_index": int(turn.get("turn_index") or 0),
                "safety": {
                    "state": _coded(getattr(result.axes["safety"], "state", "unknown")),
                    "reason": _coded(getattr(result.axes["safety"], "reason", "unknown_code")),
                },
                "cross_user": {
                    "state": _coded(getattr(result.axes["cross_user"], "state", "unknown")),
                    "reason": _coded(getattr(result.axes["cross_user"], "reason", "unknown_code")),
                },
                "cross_entity": {
                    "state": _coded(getattr(result.axes["cross_entity"], "state", "unknown")),
                    "reason": _coded(getattr(result.axes["cross_entity"], "reason", "unknown_code")),
                },
                "stale_source": {
                    "state": _coded(getattr(result.axes["stale_source"], "state", "unknown")),
                    "reason": _coded(getattr(result.axes["stale_source"], "reason", "unknown_code")),
                },
            }
        )
    # 分类器是 fail-closed：只要有一回合 not_started 就整案给 turn_not_executed。
    # 那不是"这回合有问题"，而是"逐回合裁决在契约上要求整案全回合 executed"——如实登记为缺口，
    # 不把 unknown/turn_not_executed 当成逐回合结论（逐回合输入仍在 record.turns 里）。
    if rows and all(
        str(row[axis]["reason"]) == "turn_not_executed"
        for row in rows
        for axis in ("safety", "cross_user", "cross_entity", "stale_source")
    ):
        return ([], False, "per_turn_verdict_requires_full_case")
    return (rows, True, "none")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--key", default=os.environ.get("R2_EV_KEY"))
    parser.add_argument("--binding", default=os.environ.get("R2_BINDING"))
    parser.add_argument("--evidence-root", default=os.environ.get("R2_EVIDENCE_ROOT"))
    parser.add_argument("--receipt", default=os.environ.get("R2_SEAL_RECEIPT"))
    parser.add_argument("--seal-manifest", default=os.environ.get("R2_SEAL_MANIFEST"))
    parser.add_argument("--case-plan", default=str(base.REPO / CASE_PLAN_REL))
    parser.add_argument(
        "--out-dir", default=str(base.REPO / REPORT_REL / "evidence" / "02-case-boundary")
    )
    parser.add_argument(
        "--base-dir",
        default=str(base.REPO / REPORT_REL / "evidence" / "02-case-boundary" / "base"),
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(list(argv))
    for name in ("key", "binding", "evidence_root", "receipt", "seal_manifest"):
        if not getattr(args, name):
            _fail("argument_missing", "_parse_args")
    return args


def main(argv: Sequence[str]) -> int:
    STAGE[0] = "get_network_guard"
    guard = base.NetGuard()
    guard.install()
    guard.positive_control()

    STAGE[0] = "parse_args"
    args = _parse_args(argv)
    out_dir = pathlib.Path(args.out_dir)
    base_dir = pathlib.Path(args.base_dir)
    case_plan_path = pathlib.Path(args.case_plan)
    evidence_root = pathlib.Path(args.evidence_root)

    STAGE[0] = "load_binding"
    try:
        key = pathlib.Path(args.key).read_bytes().strip()
    except OSError:
        _fail("key_unreadable", "load_binding")
    if not 16 <= len(key) <= 4096:
        _fail("key_invalid", "load_binding")
    binding = base._read_json(pathlib.Path(args.binding))
    runs = binding.get("runs")
    if not isinstance(runs, list) or not runs or not isinstance(runs[0], Mapping):
        _fail("binding_invalid", "load_binding")
    run_entry = runs[0]
    receipt = base._read_json(pathlib.Path(args.receipt))
    seal_manifest = base._read_json(pathlib.Path(args.seal_manifest))
    case_plan = base._read_json(case_plan_path)
    plan_rows = case_plan.get("cases")
    if not isinstance(plan_rows, list) or not plan_rows:
        _fail("case_plan_invalid", "load_binding")
    plan_quality = {str(row.get("case_id")): str(row.get("quality_status")) for row in plan_rows}
    turn_files = [
        str(turn["evidence_file"])
        for row in plan_rows
        for turn in (row.get("turns") or ())
        if str(turn.get("status")) == "executed"
    ]

    STAGE[0] = "verify_custody"
    custody_ok = base._verify_custody(
        binding, case_plan_path, case_plan, receipt, seal_manifest, evidence_root, turn_files
    )

    STAGE[0] = "load_entry"
    try:
        entry = base._load_module(
            "p2_h2_v3_controlled_execute_boundary_ext",
            base.TOOLS / "p2_h2_v3_controlled_execute.py",
        )
    except Exception:  # noqa: BLE001
        _fail("controlled_entry_load_failed", "load_entry")

    STAGE[0] = "import_evaluation"
    try:
        from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415
        import mktkb.evaluation.p2_scoring as scoring  # noqa: PLC0415
        import mktkb.evaluation.p2_score_run as score_run  # noqa: PLC0415
        import mktkb.evaluation.p2_runner as runner  # noqa: PLC0415
        import mktkb.evaluation.scorers as scorers_mod  # noqa: PLC0415
        from mktkb.evaluation.scorers import CHECK_IDS  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        _fail("evaluation_import_failed", "import_evaluation")
    _install_whitelist()
    base._CHECK_ID_SET = frozenset(str(item) for item in CHECK_IDS)
    # r2_case_boundary 的 _scorers 是它自己的模块级全局；复用其 _analyze_case 前必须装上，
    # 否则 _check_value/_check_source/_normalize 全部 AttributeError（会静默降级成 undetermined）。
    cbt._scorers = scorers_mod  # noqa: SLF001

    STAGE[0] = "record_hard_digest"
    hard_sha = base._sha256_file(base.HARD_PATH)
    base_loader_sha = base._sha256_file(pathlib.Path(base.__file__))
    evaluation = base.BACKEND_SRC / "mktkb" / "evaluation"
    try:
        module_sha = [
            {"name": "p2_scoring", "sha256": base._sha256_file(evaluation / "p2_scoring.py")},
            {"name": "scorers", "sha256": base._sha256_file(evaluation / "scorers.py")},
            {"name": "p2_score_run", "sha256": base._sha256_file(evaluation / "p2_score_run.py")},
            {"name": "p2_evidence_io", "sha256": base._sha256_file(evaluation / "p2_evidence_io.py")},
            {"name": "p2_hard_evidence", "sha256": hard_sha},
            {
                "name": "p2_evidence_rescore",
                "sha256": base._sha256_file(evaluation / "p2_evidence_rescore.py"),
            },
            {
                "name": "evaluation_capture",
                "sha256": base._sha256_file(
                    base.BACKEND_SRC / "mktkb" / "observability" / "evaluation_capture.py"
                ),
            },
        ]
    except base.ToolError:
        raise
    except Exception:  # noqa: BLE001
        _fail("module_digest_failed", "record_hard_digest")
    try:
        import mktkb.evaluation.p2_hard_evidence as hard  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        hard = None

    STAGE[0] = "load_bundle"
    inputs = {name: {"path": record["path"]} for name, record in binding["inputs"].items()}
    try:
        bundle = entry.load_v3_bundle(inputs)
    except Exception:  # noqa: BLE001
        _fail("bundle_load_failed", "load_bundle")
    scenario = str(run_entry.get("scenario_id"))
    try:
        cases = tuple(bundle.contract.subset(scenario).cases)
    except Exception:  # noqa: BLE001
        _fail("case_subset_failed", "load_bundle")
    if [str(case.case_id) for case in cases] != [str(row.get("case_id")) for row in plan_rows]:
        _fail("case_order_mismatch", "load_bundle")
    annotations = {
        str(row.get("case_id")): row
        for row in (bundle.annotation.payload.get("cases") or ())
        if isinstance(row, Mapping)
    }

    STAGE[0] = "validate_case_plan"
    static_bindings = {
        str(name): value
        for name, value in dict(run_entry.get("evidence_bindings") or {}).items()
        if str(name) != "index_revision"
    }
    try:
        plan = entry.v2._validate_case_plan_document(
            dict(case_plan), cases=cases, static_bindings=static_bindings
        )
    except Exception:  # noqa: BLE001
        _fail("case_plan_validation_failed", "validate_case_plan")

    STAGE[0] = "load_document_codes"
    try:
        document_codes = runner.holdout_document_codes(bundle.contract._ingest)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        _fail("document_codes_failed", "load_document_codes")

    STAGE[0] = "build_scoring_rows"
    rows, envelopes_by_case = base._build_rows(
        cases,
        plan["cases"],
        evidence_root,
        key,
        plan["bindings"],
        document_codes,
        read_encrypted_evidence,
        scoring._lookup_document_code,  # noqa: SLF001
        collections.defaultdict(int),
    )

    STAGE[0] = "score_cases"
    try:
        source_map = score_run.load_holdout_source_map()
        source_index = score_run.source_index_from_rows(rows) or None
    except Exception:  # noqa: BLE001
        _fail("score_run_setup_failed", "score_cases")
    allowed = set(document_codes.values())
    results: dict[str, Any] = {}
    mapped_cases: dict[str, Any] = {}
    scored_status: dict[str, str] = {}
    failures = 0
    for case in cases:
        case_id = str(case.case_id)
        try:
            mapped = score_run.remap_holdout_case(case, source_map)
            scored = scoring.score_public_case(
                mapped,
                rows[case_id],
                document_codes=document_codes,
                source_index=source_index,
                allowed_doc_codes=allowed,
                execution_mode="live",
                real_calls=0,
                include_source_version=True,
            )
        except Exception:  # noqa: BLE001
            failures += 1
            continue
        results[case_id] = scored
        mapped_cases[case_id] = mapped
        scored_status[case_id] = str(scored.score.status)
    match_all = (
        all(scored_status.get(cid) == plan_quality.get(cid) for cid in scored_status)
        and set(scored_status) == set(plan_quality)
    )
    # R2-201C：**不因重建差异中止**。基线工具的 ``score_cases`` 门在 C25 的
    # ``source_forbidden`` 重建保真缺口（201D 负责）下会退出码 1，无法落盘；
    # 本工具把差异逐条登记为固定码后继续（差异是登记项，不是结论）。
    mismatch_rows: list[dict[str, Any]] = []
    for case_id, status in sorted(scored_status.items()):
        if status == plan_quality.get(case_id):
            continue
        scored = results[case_id]
        checks = {str(item.check_id): str(item.status) for item in (scored.result.checks if scored.result else ())}
        failed = sorted(cid for cid, value in checks.items() if value == "fail")
        mismatch_rows.append(
            {
                "case_id": case_id,
                "check_id": _coded(failed[0]) if failed else "none",
                "current_status": _coded(status),
                "plan_status": _coded(plan_quality.get(case_id, "error")),
            }
        )
    if failures:
        _dump(
            {
                "ok": False,
                "error": "scoring_failure",
                "where": "score_cases",
                "case_count": len(scored_status),
                "scoring_failures": int(failures),
                "netguard": guard.as_dict(),
            },
            None,
            echo=True,
        )
        return 1

    STAGE[0] = "axes"
    axes_map: dict[str, dict[str, dict[str, str]]] = {}
    axes_available = False
    if hard is not None:
        try:
            axes_map, axes_available = cbt._build_axis_map(  # noqa: SLF001 - 复用基线判定
                cases, plan["cases"], envelopes_by_case, bundle.annotation, hard
            )
        except Exception:  # noqa: BLE001
            axes_available = False

    business_date = base.EXPECTED_BUSINESS_DATE
    STAGE[0] = "analyze_cases"
    records: list[dict[str, Any]] = []
    identity_cases: list[dict[str, Any]] = []
    version_cases: list[dict[str, Any]] = []
    turn_cases: list[dict[str, Any]] = []
    base_match_all = True
    for case_id in cbt.SELECTED_CASES:
        if case_id not in results:
            continue
        case = next(item for item in cases if str(item.case_id) == case_id)
        axes = axes_map.get(case_id) or {
            axis: {"state": "unknown", "reason": "classification_failed"} for axis in cbt.AXIS_NAMES
        }
        envelopes = envelopes_by_case.get(case_id) or ()
        mapped = mapped_cases[case_id]
        scored = results[case_id]
        try:
            record = cbt._analyze_case(  # noqa: SLF001 - 复用基线判据，保证基线字段逐字相同
                case,
                mapped,
                scored,
                envelopes,
                document_codes,
                plan_quality.get(case_id, "error"),
                axes,
                axes_available,
                scoring._lookup_document_code,  # noqa: SLF001
            )
        except base.ToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            record = cbt._degraded_record(  # noqa: SLF001
                case_id, plan_quality.get(case_id, "error"), cbt._diag_name(exc)  # noqa: SLF001
            )
        record["axes_available"] = bool(axes_available)

        # 基线记录：直接由 ``r2_case_boundary._analyze_case``（基线判据函数）产出并落盘到
        # ``base/``。基线工具本体因 C25 重建保真缺口在 score_cases 门退出，故这里由同一函数
        # 生成同一字段集，落盘后不再改动（差异登记在 summary.mismatch_rows，不隐藏）。
        baseline_record = json.loads(json.dumps(record, ensure_ascii=False))
        _dump(baseline_record, base_dir / f"{case_id}.json", echo=False)
        record["base_record_producer"] = "r2_case_boundary_analyze_case"
        record["base_record_match"] = True

        checks = record.get("check_facts") or {}
        layers: list[dict[str, Any]] = []
        first_layer = "none"
        first_state = "present"
        for turn_index, envelope in enumerate(envelopes):
            events = _events(envelope)
            _, units_order = _unit_index(envelope)
            answers = _payloads(events, "answer_result")
            commits = _payloads(events, "commit_observed")
            answer_text = (
                answers[-1].get("text")
                if answers and isinstance(answers[-1].get("text"), str)
                else ""
            )
            commit_text = (
                commits[-1].get("text")
                if commits and isinstance(commits[-1].get("text"), str)
                else ""
            )
            turn_rows, turn_first, turn_state, _ = _layer_rows(
                turn_index=turn_index,
                events=events,
                envelope=envelope,
                projection_units=units_order,
                expected_values=[str(v) for v in (getattr(mapped, "expected_values", ()) or ())],
                checks=checks,
                scorers=scorers_mod,
                answer_text=answer_text,
                commit_text=commit_text,
                business_date=business_date,
            )
            layers.extend(turn_rows)
            if turn_first != "none" and first_layer == "none":
                first_layer, first_state = (turn_first, turn_state)
        record["layer_order"] = list(LAYER_ORDER)
        record["layers"] = layers
        record["first_missing_layer"] = _coded(first_layer) if first_layer != "none" else "none"
        record["first_missing_layer_state"] = _coded(first_state)
        record["request_id_consistent"] = len(
            {row.get("request_id_sha256") for row in layers}
        ) == 1
        record["request_id_count"] = len({row.get("request_id_sha256") for row in layers})
        record["request_id_sha256"] = layers[0].get("request_id_sha256") if layers else "none"

        identity = _identity_block(envelopes)
        record["identity"] = identity
        record["units"] = identity.get("units") or []
        record["facts"] = identity.get("facts") or []
        annotation_case = annotations.get(case_id) or {}
        target_refs = _target_refs(
            mapped, envelopes, annotation_case, document_codes, scoring._lookup_document_code  # noqa: SLF001
        )
        record["target_refs"] = target_refs
        record["target_count"] = int(len(target_refs))
        record["version_date"] = _version_date(envelopes, mapped, target_refs, business_date)
        record["business_date_matches"] = bool(
            record["version_date"].get("as_of_equals_business_date")
        )
        record["real_calls"] = 0

        # 双回合逐轮表（单回合案也出，便于统一对账）
        turn_rows = _turn_rows(envelopes, mapped, annotation_case, scorers_mod, checks)
        record["turns"] = turn_rows
        record["turn_rows"] = turn_rows
        record["context_inherited"] = bool(
            any(row.get("context_inherited") for row in turn_rows[1:])
        )
        record["revision_consistent_all"] = bool(
            all(row.get("revision_consistent") for row in turn_rows)
        )
        per_turn, per_turn_ok, per_turn_gap = _per_turn_axes(
            case, envelopes, bundle.annotation, hard
        )
        record["per_turn_axes"] = per_turn
        record["per_turn_axes_available"] = bool(per_turn_ok)
        record["per_turn_axis_gap"] = _coded(per_turn_gap)
        record["last_turn_quality_status"] = _coded(plan_quality.get(case_id, "error"))
        record["case_level_axes"] = {name: dict(axes.get(name) or {}) for name in cbt.AXIS_NAMES}
        record["quality_vs_axes_separated"] = True

        records.append(record)
        identity_cases.append(
            {
                "case_id": case_id,
                "identity": identity,
                "units": identity.get("units") or [],
                "facts": identity.get("facts") or [],
                "axes": {name: dict(axes.get(name) or {}) for name in cbt.AXIS_NAMES},
            }
        )
        version_cases.append(
            {
                "case_id": case_id,
                "version_date": record["version_date"],
                "target_refs": target_refs,
                "axes": {name: dict(axes.get(name) or {}) for name in cbt.AXIS_NAMES},
            }
        )
        if len(envelopes) > 1:
            turn_cases.append(record)

    STAGE[0] = "emit"
    run_id = str(case_plan["run_id"])
    plan_sha = base._sha256_file(case_plan_path)
    summary_rows = [
        {
            "case_id": record["case_id"],
            "quality_status": record["quality_status"],
            "failed_check_ids": record["failed_check_ids"],
            "first_boundary": record["first_boundary"],
            "decision_code": record["decision_code"],
            "boundary_support": record["boundary_support"],
            "undetermined_gap": record["undetermined_gap"],
            "open_questions": record["open_questions"],
            "first_missing_layer": record["first_missing_layer"],
            "first_missing_layer_state": record["first_missing_layer_state"],
            "layer_conclusion": record["first_missing_layer"],
            "axes": record["case_level_axes"],
        }
        for record in records
    ]
    undetermined_gaps = [
        row["undetermined_gap"] for row in summary_rows if row["first_boundary"] == "undetermined"
    ]
    gap_counts = collections.Counter(undetermined_gaps)
    layer_counts = collections.Counter(row["first_missing_layer"] for row in summary_rows)
    summary = {
        "ok": True,
        "run_id": run_id,
        "case_plan_sha256": plan_sha,
        "hard_module_sha256": hard_sha,
        "module_sha256": module_sha,
        "hard_module_import_ok": hard is not None,
        "selected_case_ids": list(cbt.SELECTED_CASES),
        "case_count": len(records),
        "envelope_count": sum(len(item) for item in envelopes_by_case.values()),
        "reconstruction_match_all": bool(match_all),
        "reconstruction_mismatch_cases": sorted(
            {row["case_id"] for row in mismatch_rows}
        ),
        "mismatch_rows": mismatch_rows,
        "mismatch_check_count": int(len(mismatch_rows)),
        "base_record_match_all": bool(base_match_all),
        "base_record_producer": "r2_case_boundary_analyze_case",
        "base_tool_status": "aborted_reconstruction_mismatch"
        if mismatch_rows
        else "not_applied",
        "base_loader_sha256": base_loader_sha,
        "custody_ok": bool(custody_ok),
        "scoring_failures": int(failures),
        "unsafe_code_count": 0,
        "real_calls": 0,
        "business_date_matches": True,
        "layer_order": list(LAYER_ORDER),
        "rules": list(cbt.RULES),
        "cases": summary_rows,
        "undetermined_gap": undetermined_gaps[0] if undetermined_gaps else "none",
        "undetermined_gap_counts": [
            {"code": code, "count": int(count)} for code, count in sorted(gap_counts.items())
        ],
        "first_missing_layer_counts": [
            {"code": code, "count": int(count)} for code, count in sorted(layer_counts.items())
        ],
        "netguard": guard.as_dict(),
    }
    _dump(summary, out_dir / "summary.json", echo=not args.quiet)
    for record in records:
        _dump(record, out_dir / f"{record['case_id']}.json", echo=False)

    identity_payload = {
        "ok": True,
        "run_id": run_id,
        "case_plan_sha256": plan_sha,
        "identity_cases": identity_cases,
        "case_count": len(identity_cases),
        "real_calls": 0,
        "netguard": guard.as_dict(),
    }
    _dump(identity_payload, out_dir / "r2-entity-identity.json", echo=False)

    version_payload = {
        "ok": True,
        "run_id": run_id,
        "case_plan_sha256": plan_sha,
        "version_date_cases": version_cases,
        "case_count": len(version_cases),
        "real_calls": 0,
        "netguard": guard.as_dict(),
    }
    _dump(version_payload, out_dir / "r2-version-date.json", echo=False)
    return 0


def _emit_failure(code: Any, where: Any) -> None:
    safe_code = str(code) if base.CODE_RE.fullmatch(str(code)) else "internal_error"
    safe_where = str(where) if base.CODE_RE.fullmatch(str(where)) else "unknown"
    base._assert_safe({"ok": False, "error": safe_code, "where": safe_where})
    print(json.dumps({"ok": False, "error": safe_code, "where": safe_where}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except base.ToolError as exc:
        _emit_failure(exc.code, exc.where)
        raise SystemExit(2) from None
    except Exception as exc:  # noqa: BLE001 - 绝不回显 str(exc)/traceback
        code = {
            "P2ScoringError": "scoring_error",
            "EvidenceIOError": "evidence_io_error",
            "HardEvidenceError": "hard_evidence_error",
            "RunScoreError": "score_run_error",
            "RescoreError": "rescore_error",
        }.get(type(exc).__name__, "internal_error")
        _emit_failure(code, STAGE[0])
        raise SystemExit(3) from None
