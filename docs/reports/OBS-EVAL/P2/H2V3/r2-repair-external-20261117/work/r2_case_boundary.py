"""R2-201C 五案定位：为 C08 / C14 / C19 / C25 / C29 产出**去身份化 SAFE 事实表**与首个偏离边界。

本工具不改产品、不改评分器、不改契约/冻结件/旧证据/case-plan，只读封存 r2 证据并输出
白名单事实。加载链、解密、评分行重建、白名单输出全部复用 `r2_safe_project.py`
（`import` 该模块，只读其常量与函数；不改其文件、不 monkeypatch 其逻辑）。

R2 改动清单（相对 r1-repair-external-20261117/work/r1_case_boundary.py，**只动这五项**）
--------------------------------------------------------------------------------
A. `import r2_safe_project as base`（原 `r1_safe_project`）。
B. `SELECTED_CASES` → C08 / C14 / C19 / C25 / C29（R2 五题）。
C. `CASE_PLAN_REL` → `fullverify-20261116/run/r2-final/case-plan.json`。
D. `REPORT_REL` → `r2-repair-external-20261117`。
E. 路径/轮次标签：模块名 `r2_case_boundary`、环境变量前缀 `R2_*`、诊断码里的文件名匹配。
判据（`BOUNDARIES` / `GAP_CODES` / `DECISION_CODES` / `RULES` / `_decide`）、
白名单（`_EXTRA_KEYS`）、检查读法（`_CHECK_ORDER` / `_LIST_KEYS`）**一字未改**。

输出四类事实（每案一份，全部为固定码 / 固定事件名 / 整数 / 布尔 / sha256）
--------------------------------------------------------------------
1. `check_facts`：`kind_correct` / `value_hit` / `value_no_fabricated` /
   `source_hit` 的 status 与**计数**（expected / matched / missing / extra /
   checked / evidence_numbers）。检查 evidence 里的原文值一律只取 `len()`。
2. `answer_shape`：最终 `kind`（固定枚举码）、`text` 字符数、数字 token 数、
   日期形态 token 数、单位词 token 数、尾部省略号布尔、行数。不含任何文本。
3. `boundary_events`：envelope 事件协议里的固定 kind 计数与固定 reason/error 码。
4. `value_provenance` / `source_provenance`：期望值缺失时哪些**形态改写族**命中；
   编造数字出现在哪一层；期望来源是否被检索到、是否被引用。

首个偏离边界只允许取 8 个固定枚举值（见 :data:BOUNDARIES）；`undetermined` 必须
同时给出 `undetermined_gap` 固定码，说明缺哪一项。单案分析自身抛错的兜底记录用
`diag_<异常类型名小写>_<本文件行号>` 作缺口码（只回显异常类型与行号，不回显消息）。

私有数据纪律
-----------
- 私有输入只在**进程内存**里读；
- 绝不 `print` 题干/答案/实体名/来源正文/私有路径；不打印 `str(exc)`、不打印
  `traceback`；
- 所有输出过 `base._assert_safe`（键白名单 + 字符串白名单 + 类型白名单）；
- 顶层 try/except：异常只输出 `{ok: false, error: <固定码>, where: <函数名>}`。

运行（私有路径一律命令行/环境变量传入，不写进本文件）
--------------------------------------------------

    .venv\\Scripts\\python.exe -X utf8 r2_case_boundary.py ^
      --key <ev.key> --binding <run2-pre_v05_without_v07.binding.json> ^
      --evidence-root <...\\r2\\evidence\\p2-h2v3-20261115-r2-pre_v05_without_v07> ^
      --receipt <...\\r2\\seal\\...\\run-receipt.json> ^
      --seal-manifest <...\\r2\\seal\\...\\seal-manifest.json>
"""
from __future__ import annotations

import argparse
import collections
import difflib
import json
import os
import pathlib
import re
import sys
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

_WORK = pathlib.Path(__file__).resolve().parent
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r2_safe_project as base  # noqa: E402 - 同目录复用加载/白名单

REPORT_REL = "docs/reports/OBS-EVAL/P2/H2V3/r2-repair-external-20261117"
CASE_PLAN_REL = "docs/reports/OBS-EVAL/P2/H2V3/fullverify-20261116/run/r2-final/case-plan.json"

STAGE = ["module"]


def _fail(code: str, where: str | None = None) -> None:
    raise base.ToolError(code, where or STAGE[0])


# --------------------------------------------------------------------------- #
# 固定枚举
# --------------------------------------------------------------------------- #

SELECTED_CASES = ("H2V3-C08", "H2V3-C14", "H2V3-C19", "H2V3-C25", "H2V3-C29")
AXIS_NAMES = ("safety", "cross_user", "cross_entity", "stale_source")

#: 允许的首个偏离边界（任务单 §六 R0-4 的固定枚举）。
BOUNDARIES = (
    "answer_value_absent",
    "answer_value_reformatted",
    "answer_value_truncated",
    "answer_value_extra_fabricated",
    "retrieval_missed_expected_source",
    "citation_omitted",
    "wrong_entity_scope",
    "undetermined",
)

#: 产品 json ``kind`` 的固定枚举（conversations/service 与 p2_hard_evidence 的取值域）。
KIND_CODES = frozenset(
    {
        "answer",
        "not_found",
        "no_answer",
        "clarification",
        "conflict",
        "service_error",
        "knowledge_changed",
        "refusal",
        "ambiguous",
    }
)

#: 判定支撑码（固定码，全部小写下划线）。
DECISION_CODES = frozenset(
    {
        "axis_cross_entity_violation",
        "axis_stale_source_violation",
        "source_hit_fail",
        "cited_none",
        "cited_partial",
        "expected_not_retrieved",
        "expected_retrieved_but_uncited",
        "value_hit_fail",
        "value_hit_missing_all",
        "value_hit_missing_partial",
        "value_no_fabricated_extra",
        "extra_numbers_backed_by_evidence",
        "extra_numbers_unbacked",
        "extra_in_cited_units",
        "extra_in_uncited_retrieved",
        "extra_in_model_evidence",
        "extra_in_facts",
        "extra_in_fact_ids",
        "extra_in_unit_identity",
        "extra_in_document_name",
        "extra_in_context",
        "extra_in_line_markers",
        "reformat_thousands_separator",
        "reformat_date_shape",
        "reformat_percent_decimal",
        "reformat_wan_unit",
        "reformat_wording",
        "truncation_signal",
        "truncation_partial_prefix",
        "answer_text_empty",
        "insufficient_evidence",
    }
)

#: ``undetermined`` 的缺口码。
GAP_CODES = frozenset(
    {
        "none",
        "axes_unavailable",
        "no_failed_check",
        "check_evidence_absent",
        "retrieval_events_absent",
        "unit_texts_absent",
        "pagination_not_reconstructed",
        "extra_origin_ambiguous",
        "citation_identity_weak",
        "source_ref_unresolved",
        "answer_text_unavailable",
        "scorer_helper_missing",
    }
)

#: 判定之外仍然开放的鉴别点（固定码）：说明"封存证据里缺哪一项"，不是结论。
OPEN_QUESTION_CODES = frozenset(
    {
        "single_digit_key_unattributable",
        "field_role_not_captured",
        "retrieval_not_captured_for_rag_path",
        "pagination_not_reconstructed",
    }
)

#: 判定规则顺序（写入 summary，供复核）。
RULES = (
    "axis_violation_first",
    "source_neither_retrieved_nor_cited_is_retrieval_miss",
    "source_retrieved_but_uncited_is_citation_omission",
    "fabrication_origin_split_value_vs_identity",
    "truncation_before_reformat",
    "reformat_before_absent",
)

#: 追加到 base 白名单的键（其余键沿用 base 的 ALLOWED_KEYS）。
_EXTRA_KEYS = frozenset(
    {
        "hard_module_sha256",
        "module_sha256",
        "name",
        "sha256",
        "hard_module_import_ok",
        "selected_case_ids",
        "reconstruction_match_all",
        "cases",
        "summary",
        "check_facts",
        "status",
        "value_hit",
        "value_no_fabricated",
        "source_hit",
        "kind_correct",
        "expected",
        "matched",
        "missing",
        "extra",
        "checked",
        "evidence_numbers",
        "leaked",
        "reason_code",
        "answer_shape",
        "kind_code",
        "answer_text_chars",
        "commit_text_chars",
        "answer_commit_text_equal",
        "text_chars",
        "digit_token_count",
        "digit_span_count",
        "date_token_count",
        "unit_token_count",
        "tail_ellipsis",
        "line_count",
        "has_digit",
        "has_date",
        "has_unit",
        "boundary_events",
        "event_kinds",
        "kind",
        "count",
        "capture_status",
        "capture_error_count",
        "capture_error_codes",
        "completeness_status",
        "truncations",
        "projection_errors",
        "retrieval_event_count",
        "retrieved_unit_total",
        "retrieved_unit_distinct",
        "retrieval_truncated_count",
        "retrieval_empty_count",
        "retrieval_candidate_count",
        "retrieval_scope_codes",
        "plan_path_code",
        "plan_mode_code",
        "plan_as_of_present",
        "plan_terms_count",
        "plan_filters_count",
        "plan_clarification_count",
        "plan_enumerate_count",
        "model_output_count",
        "model_input_event_count",
        "model_output_status_codes",
        "model_output_error_codes",
        "model_output_retryable_count",
        "model_output_source_ids_total",
        "model_input_evidence_count",
        "model_input_chars_total",
        "answer_candidates",
        "answer_conflicts",
        "answer_missing_fields",
        "answer_error_code",
        "answer_reason_code",
        "direct_rag_present",
        "direct_rag_fact_count",
        "direct_rag_cited_units",
        "direct_rag_reason_code",
        "query_state_event_count",
        "query_state_row_present_count",
        "query_state_nonempty_count",
        "query_state_last_kinds",
        "http_status",
        "timed_out",
        "value_provenance",
        "expected_count",
        "missing_count",
        "numeric_expected_count",
        "text_expected_count",
        "reformat_family_counts",
        "thousands_separator",
        "date_shape",
        "percent_decimal",
        "wan_unit",
        "wording",
        "partial_prefix",
        "best_common_block_permille",
        "extra_count",
        "extra_key_max_chars",
        "answer_digit_keys_total",
        "extra_in_line_markers",
        "extra_in_cited_units",
        "extra_in_uncited_retrieved",
        "extra_in_model_evidence",
        "extra_in_facts",
        "extra_in_fact_ids",
        "extra_in_unit_identity",
        "extra_in_document_name",
        "extra_in_context",
        "extra_in_line_markers",
        "extra_in_none",
        "evidence_availability",
        "unit_rows_total",
        "unit_rows_with_text",
        "unit_rows_with_raw_fields",
        "unit_rows_with_date_fields",
        "cited_units_present",
        "cited_unit_text_chars",
        "fact_rows_total",
        "fact_value_chars",
        "model_input_events",
        "context_message_count",
        "retrieved_ids_resolved",
        "retrieved_ids_unresolved",
        "source_provenance",
        "cited_matched",
        "citation_total",
        "citation_unit_id_count",
        "expected_retrieved_count",
        "expected_retrieved_any_version",
        "expected_retrieved_not_cited",
        "expected_neither_count",
        "expected_doc_only_count",
        "axes_available",
        "safety",
        "cross_entity",
        "stale_source",
        "first_boundary",
        "boundary_support",
        "open_questions",
        "single_digit_key_unattributable",
        "field_role_not_captured",
        "retrieval_not_captured_for_rag_path",
        "pagination_not_reconstructed",
        "decision_code",
        "undetermined_gap",
        "rules",
        "code",
        "where",
        "ok",
        "error",
        "netguard",
        "blocked_attempts",
        "positive_control_attempts",
        "positive_control_blocked",
        "outbound_allowed",
        "scoring_failures",
        "unsafe_code_count",
        "case_plan_sha256",
        "run_id",
    }
)


def _install_whitelist() -> None:
    base.ALLOWED_KEYS = frozenset(base.ALLOWED_KEYS) | _EXTRA_KEYS


def _coded(value: Any, fallback: str = "unknown_code") -> str:
    """把自由字符串降级为固定码形态；不改变语义，只保证可输出。"""
    text = str(value or "")
    return text if base.CODE_RE.fullmatch(text) else fallback


def _is_seq(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _dump(payload: Mapping[str, Any], path: pathlib.Path | None, *, echo: bool) -> None:
    try:
        base._assert_safe(dict(payload))
    except base.ToolError:
        # 白名单校验失败时只报固定码：不回显任何键名/取值，避免把私有内容带出来。
        _fail("unsafe_output_key", "dump")
    text = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    if echo:
        print(text)


# --------------------------------------------------------------------------- #
# 文本形态度量（只输出计数，绝不输出文本）
# --------------------------------------------------------------------------- #

_DIGIT_SPAN_RE = re.compile(r"\d+(?:[.,]\d+)*")
_DIGIT_GROUP_RE = re.compile(r"\d+")
_DATE_RE = re.compile(
    r"\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?"
    r"|\d{1,2}\s*[:：]\s*\d{2}"
    r"|\d{4}\s*年\s*\d{1,2}\s*月"
)
_UNIT_WORDS = (
    "个", "元", "万", "年", "月", "日", "份", "条", "人", "次", "套", "项",
    "%", "％", "公斤", "千克", "吨", "天", "小时", "分钟",
)
_ELLIPSIS_TAIL = ("…", "...", "⋯")
_NUMERIC_ONLY = re.compile(r"(\d+(?:\.\d+)?)(%?)")
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

_scorers: Any = None


def _normalize(text: str) -> str:
    helper = getattr(_scorers, "normalize_text", None)
    return helper(text) if helper is not None else str(text)


def _number_keys(text: str) -> set[str]:
    """与评分器同口径的数字 key（``01``→``1``，``1.50``→``1.5``）。"""
    helper = getattr(_scorers, "_number_keys", None)
    if helper is not None:
        return {str(item) for item in helper(text)}
    keys: set[str] = set()
    for token in _DIGIT_SPAN_RE.findall(_normalize(text)):
        try:
            number = Decimal(token)
            keys.add(
                str(int(number))
                if number == number.to_integral_value()
                else format(number.normalize(), "f")
            )
        except (InvalidOperation, ValueError):
            keys.add(token)
    return keys


def _check_value(text: str, expected: str, *, cross: bool = True) -> bool:
    """只读包装评分器的值匹配（P2 公开口径：``cross_explicit_space=True``）。"""
    return bool(_scorers.check_value(text, expected, cross_explicit_space=cross))


def _check_source(ref: Mapping[str, Any], citation: Any) -> bool:
    """只读包装评分器的来源匹配（``EvalCitation`` 或等价映射）。"""
    return bool(_scorers.check_source(ref, citation))


def _shape(text: str) -> dict[str, Any]:
    raw = text if isinstance(text, str) else ""
    spans = _DIGIT_SPAN_RE.findall(raw)
    dates = _DATE_RE.findall(raw)
    units = sum(raw.count(word) for word in _UNIT_WORDS)
    stripped = raw.rstrip()
    return {
        "text_chars": len(raw),
        "line_count": (raw.count("\n") + 1) if raw else 0,
        "digit_span_count": len(spans),
        "digit_token_count": sum(len(_DIGIT_GROUP_RE.findall(item)) for item in spans),
        "date_token_count": len(dates),
        "unit_token_count": int(units),
        "has_digit": bool(spans),
        "has_date": bool(dates),
        "has_unit": bool(units),
        "tail_ellipsis": bool(stripped) and stripped.endswith(_ELLIPSIS_TAIL),
    }


def _best_block_permille(text: str, needles: Sequence[str]) -> int:
    haystack = _normalize(text)
    best = 0
    for raw in needles:
        needle = _normalize(str(raw))
        if not needle or not haystack:
            continue
        matcher = difflib.SequenceMatcher(None, needle, haystack, autojunk=False)
        size = matcher.find_longest_match(0, len(needle), 0, len(haystack)).size
        best = max(best, int(1000 * size / max(1, len(needle))))
    return min(best, 1000)


def _reformat_families(text: str, missing: Sequence[str]) -> dict[str, int]:
    """对每个缺失期望值探测**确定性改写族**；只返回命中族计数。"""
    families = {
        "thousands_separator": 0,
        "date_shape": 0,
        "percent_decimal": 0,
        "wan_unit": 0,
        "wording": 0,
        "partial_prefix": 0,
    }
    haystack = _normalize(text)
    keys = _number_keys(text)
    for raw in missing:
        needle = _normalize(str(raw))
        if not needle:
            continue
        matched = False
        numeric = _NUMERIC_ONLY.fullmatch(needle)
        if numeric:
            base_value, percent = numeric.group(1), bool(numeric.group(2))
            try:
                number: Decimal | None = Decimal(base_value)
            except InvalidOperation:
                number = None
            if number is not None and re.fullmatch(r"\d{4,}", base_value):
                if f"{int(number):,}" in haystack:
                    families["thousands_separator"] += 1
                    matched = True
            if number is not None and not matched:
                candidate = number / Decimal(100) if percent else number * Decimal(100)
                form = format(candidate.normalize(), "f")
                if percent:
                    if form in keys:
                        families["percent_decimal"] += 1
                        matched = True
                elif f"{form}%" in haystack or f"{form}％" in haystack:
                    families["percent_decimal"] += 1
                    matched = True
            if number is not None and not matched and abs(number) >= 10000 and "万" in haystack:
                form = format((number / Decimal(10000)).normalize(), "f")
                if f"{form}万" in haystack or f"{form} 万" in haystack:
                    families["wan_unit"] += 1
                    matched = True
            if matched:
                continue
        iso = _ISO_DATE.fullmatch(needle)
        if iso:
            year, month, day = iso.groups()
            variants = (
                f"{year}年{int(month)}月{int(day)}日",
                f"{year}年{month}月{day}日",
                f"{year}/{month}/{day}",
                f"{year}.{month}.{day}",
                f"{year}{month}{day}",
            )
            if any(item in haystack for item in variants):
                families["date_shape"] += 1
            continue
        if haystack and len(needle) >= 3:
            matcher = difflib.SequenceMatcher(None, needle, haystack, autojunk=False)
            size = matcher.find_longest_match(0, len(needle), 0, len(haystack)).size
            ratio = int(1000 * size / max(1, len(needle)))
            if size >= 2 and ratio >= 600:
                families["wording"] += 1
            elif size >= 2 and 400 <= ratio < 600:
                families["partial_prefix"] += 1
    return families


# --------------------------------------------------------------------------- #
# 事件事实（只取固定 kind / 固定码 / 计数）
# --------------------------------------------------------------------------- #

_EVENT_KIND_ORDER = (
    "claim_observed",
    "context_observed",
    "context_message",
    "entity_inheritance",
    "query_state_observed",
    "query_state_saved",
    "query_state_cleared",
    "plan_observed",
    "retrieval_observed",
    "model_input",
    "model_output",
    "answer_result",
    "direct_rag_answer",
    "commit_observed",
    "capture_error",
)


def _payloads(events: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping) or str(event.get("kind")) != kind:
            continue
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            rows.append(payload)
    return rows


def _codes(values: Iterable[Any], limit: int = 16) -> list[str]:
    out: list[str] = []
    for value in values:
        code = _coded(value)
        if code not in out:
            out.append(code)
        if len(out) >= limit:
            break
    return out


def _evidence_texts(payload: Mapping[str, Any]) -> list[str]:
    rows = payload.get("evidence")
    texts: list[str] = []
    if not _is_seq(rows):
        return texts
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        if isinstance(item.get("text"), str):
            texts.append(item["text"])
        fields = item.get("fields")
        if isinstance(fields, Mapping):
            for value in fields.values():
                if isinstance(value, str):
                    texts.append(value)
                elif _is_seq(value):
                    texts.extend(str(part) for part in value if isinstance(part, (str, int, float)))
    return texts


def _fact_texts(payload: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """把事实行拆成 (值类文本, 身份类标识文本)：后者是容器 id，不是业务值。"""
    rows = payload.get("facts")
    values: list[str] = []
    ids: list[str] = []
    if not _is_seq(rows):
        return values, ids
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        for key in ("value", "field_label", "entity_label", "entity_key", "field_role"):
            if isinstance(item.get(key), str):
                values.append(item[key])
        for key in ("source_chunk_id", "source_unit_id", "doc_id", "version_id"):
            if isinstance(item.get(key), str):
                ids.append(item[key])
    return values, ids


def _walk_strings(value: Any, depth: int = 0) -> list[str]:
    if depth > 4:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        out: list[str] = []
        for item in value.values():
            out.extend(_walk_strings(item, depth + 1))
        return out
    if _is_seq(value):
        out = []
        for item in value:
            out.extend(_walk_strings(item, depth + 1))
        return out
    return []


def _unit_texts(unit: Mapping[str, Any]) -> list[str]:
    texts: list[str] = []
    if isinstance(unit.get("text"), str):
        texts.append(unit["text"])
    for key in ("locator", "raw_fields", "date_fields"):
        block = unit.get(key)
        if isinstance(block, Mapping):
            texts.extend(_walk_strings(block))
    return texts


def _unit_identity(
    unit: Mapping[str, Any], document_codes: Mapping[str, str], lookup: Any
) -> Mapping[str, Any] | None:
    """把 projection 的 unit 行还原成 ``check_source`` 可吃的引用映射。"""
    name = unit.get("document_name")
    if not isinstance(name, str) or not name:
        return None
    try:
        doc_code = lookup(name, dict(document_codes))
    except Exception:  # noqa: BLE001
        doc_code = dict(document_codes).get(name)
    if not doc_code:
        return None
    locator = dict(unit.get("locator") or {})
    version = unit.get("version_number")
    if type(version) is int and version > 0:
        locator["version_number"] = version
    return {
        "doc_code": str(doc_code),
        "unit_key": unit.get("unit_key"),
        "unit_ids": [str(unit.get("unit_id"))],
        "locator": locator,
    }


def _events_facts(
    envelopes: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """返回 (可输出的 boundary_events, 只在内存里用的内部上下文)。"""
    kind_counts: dict[str, int] = {}
    capture_errors: list[Mapping[str, Any]] = []
    capture_status: list[Any] = []
    completeness: list[Any] = []
    truncations = 0
    projection_errors = 0
    retrieval_events = 0
    retrieved_ids: list[str] = []
    retrieval_truncated = 0
    retrieval_empty = 0
    retrieval_candidate = 0
    retrieval_scopes: list[Any] = []
    plan_paths: list[Any] = []
    plan_modes: list[Any] = []
    plan_as_of = 0
    plan_terms = 0
    plan_filters = 0
    plan_clar = 0
    plan_enum = 0
    model_statuses: list[Any] = []
    model_errors: list[Any] = []
    model_retryable = 0
    model_source_ids = 0
    model_evidence_count = 0
    model_input_events = 0
    model_chars = 0
    model_evidence_texts: list[str] = []
    answers: list[Mapping[str, Any]] = []
    direct: list[Mapping[str, Any]] = []
    query_events = 0
    query_row_present = 0
    query_nonempty = 0
    query_last_kinds: list[Any] = []
    http_status: list[int] = []
    timed_out = 0
    context_texts: list[str] = []
    projects: list[Mapping[str, Any]] = []

    for envelope in envelopes:
        events: list[Mapping[str, Any]] = []
        capture = envelope.get("capture")
        if isinstance(capture, Mapping):
            capture_status.append(capture.get("status"))
            errors = capture.get("errors")
            if _is_seq(errors):
                capture_errors.extend(item for item in errors if isinstance(item, Mapping))
            raw_events = capture.get("events")
            if _is_seq(raw_events):
                events = [item for item in raw_events if isinstance(item, Mapping)]
        for event in events:
            kind = _coded(event.get("kind"))
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        projection = envelope.get("db_projection")
        if isinstance(projection, Mapping):
            projects.append(projection)
            rows = projection.get("truncations")
            truncations += len(rows) if _is_seq(rows) else 0
            rows = projection.get("errors")
            projection_errors += len(rows) if _is_seq(rows) else 0
        block = envelope.get("completeness")
        if isinstance(block, Mapping):
            completeness.append(block.get("status"))
        turn = envelope.get("turn")
        if isinstance(turn, Mapping):
            status = turn.get("http_status")
            if type(status) is int:
                http_status.append(status)
            timed_out += int(turn.get("timed_out") is True)

        for payload in _payloads(events, "retrieval_observed"):
            retrieval_events += 1
            ids = payload.get("unit_ids")
            if _is_seq(ids):
                retrieved_ids.extend(str(item) for item in ids if str(item))
            retrieval_truncated += int(payload.get("truncated") is True)
            retrieval_empty += int(payload.get("empty") is True)
            retrieval_candidate += int(payload.get("candidate") is True)
            retrieval_scopes.append(payload.get("scope"))
        for payload in _payloads(events, "plan_observed"):
            plan_paths.append(payload.get("path"))
            plan_modes.append(payload.get("mode"))
            plan_as_of += int(isinstance(payload.get("as_of"), str) and bool(payload.get("as_of")))
            terms = payload.get("terms")
            plan_terms += len(terms) if _is_seq(terms) else 0
            filters = payload.get("filters")
            plan_filters += len(filters) if isinstance(filters, Mapping) else 0
            plan_clar += int(payload.get("clarification") is True)
            plan_enum += int(payload.get("enumerate") is True)
        for payload in _payloads(events, "model_output"):
            model_statuses.append(payload.get("status"))
            if payload.get("error_code"):
                model_errors.append(payload.get("error_code"))
            model_retryable += int(payload.get("retryable") is True)
            ids = payload.get("source_ids")
            model_source_ids += len(ids) if _is_seq(ids) else 0
        for payload in _payloads(events, "model_input"):
            model_input_events += 1
            texts = _evidence_texts(payload)
            model_evidence_count += len(texts)
            model_chars += sum(len(item) for item in texts)
            model_evidence_texts.extend(texts)
        answers.extend(_payloads(events, "answer_result"))
        direct.extend(_payloads(events, "direct_rag_answer"))
        for kind in ("query_state_observed", "query_state_saved", "query_state_cleared"):
            for payload in _payloads(events, kind):
                query_events += 1
                query_row_present += int(payload.get("row_present") is True)
                state = payload.get("state_json")
                query_nonempty += int(isinstance(state, Mapping) and bool(state))
                if payload.get("last_kind"):
                    query_last_kinds.append(payload.get("last_kind"))
        for payload in _payloads(events, "context_message"):
            if isinstance(payload.get("text"), str):
                context_texts.append(payload["text"])

    answer = answers[-1] if answers else {}
    direct_row = direct[-1] if direct else {}
    fact_values, fact_ids = _fact_texts(direct_row)
    facts = {
        "turn_count": len(envelopes),
        "event_kinds": [
            {"kind": kind, "count": kind_counts.get(kind, 0)}
            for kind in _EVENT_KIND_ORDER
            if kind_counts.get(kind)
        ],
        "capture_status": _coded(capture_status[-1]) if capture_status else "missing",
        "capture_error_count": len(capture_errors),
        "capture_error_codes": _codes([item.get("code") for item in capture_errors]),
        "completeness_status": _coded(completeness[-1]) if completeness else "missing",
        "truncations": truncations,
        "projection_errors": projection_errors,
        "retrieval_event_count": retrieval_events,
        "retrieved_unit_total": len(retrieved_ids),
        "retrieved_unit_distinct": len(set(retrieved_ids)),
        "retrieval_truncated_count": retrieval_truncated,
        "retrieval_empty_count": retrieval_empty,
        "retrieval_candidate_count": retrieval_candidate,
        "retrieval_scope_codes": _codes(retrieval_scopes),
        "plan_path_code": _coded(plan_paths[-1]) if plan_paths else "missing",
        "plan_mode_code": _coded(plan_modes[-1]) if plan_modes else "missing",
        "plan_as_of_present": plan_as_of,
        "plan_terms_count": plan_terms,
        "plan_filters_count": plan_filters,
        "plan_clarification_count": plan_clar,
        "plan_enumerate_count": plan_enum,
        "model_output_count": len(model_statuses),
        "model_input_event_count": model_input_events,
        "model_output_status_codes": _codes(model_statuses),
        "model_output_error_codes": _codes(model_errors),
        "model_output_retryable_count": model_retryable,
        "model_output_source_ids_total": model_source_ids,
        "model_input_evidence_count": model_evidence_count,
        "model_input_chars_total": model_chars,
        "answer_candidates": int(answer.get("candidates") or 0),
        "answer_conflicts": int(answer.get("conflicts") or 0),
        "answer_missing_fields": len(answer.get("missing_fields")) if _is_seq(answer.get("missing_fields")) else 0,
        "answer_error_code": _coded(answer.get("error_code")) if answer.get("error_code") else "none",
        "answer_reason_code": _coded(answer.get("reason")) if answer.get("reason") else "none",
        "direct_rag_present": bool(direct_row),
        "direct_rag_fact_count": int(direct_row.get("fact_count") or 0),
        "direct_rag_cited_units": len(direct_row.get("cited_unit_ids")) if _is_seq(direct_row.get("cited_unit_ids")) else 0,
        "direct_rag_reason_code": _coded(direct_row.get("reason")) if direct_row.get("reason") else "none",
        "query_state_event_count": query_events,
        "query_state_row_present_count": query_row_present,
        "query_state_nonempty_count": query_nonempty,
        "query_state_last_kinds": _codes(query_last_kinds),
        "http_status": http_status[-1] if http_status else 0,
        "timed_out": timed_out,
    }
    internal = {
        "retrieved_ids": retrieved_ids,
        "model_evidence_texts": model_evidence_texts,
        "context_texts": context_texts,
        "fact_values": fact_values,
        "fact_ids": fact_ids,
        "projects": projects,
        "answer": answer,
    }
    return facts, internal


# --------------------------------------------------------------------------- #
# 检查事实
# --------------------------------------------------------------------------- #

_CHECK_ORDER = ("kind_correct", "value_hit", "value_no_fabricated", "source_hit")
_COUNT_KEYS = ("expected", "checked", "evidence_numbers", "matched")
_LIST_KEYS = {
    "missing": "missing",
    "missing_index": "missing",
    "extra": "extra",
    "leaked": "leaked",
    "violations_index": "leaked",
}


def _check_facts(checks: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for check_id in _CHECK_ORDER:
        check = checks.get(check_id)
        if check is None:
            out[check_id] = {"status": "missing"}
            continue
        evidence = dict(getattr(check, "evidence", {}) or {})
        status = _coded(getattr(check, "status", "unknown"))
        row: dict[str, Any] = {"status": status}
        for key in _COUNT_KEYS:
            value = evidence.get(key)
            if type(value) is int:
                row[key] = int(value)
        for key, target in _LIST_KEYS.items():
            value = evidence.get(key)
            if _is_seq(value):
                row[target] = len(value)
        if "reason" in evidence:
            row["reason_code"] = _coded(evidence.get("reason"))
        if status == "pass" and check_id in ("value_hit", "source_hit") and "expected" in row:
            row.setdefault("matched", int(row["expected"]))
            row.setdefault("missing", 0)
        out[check_id] = row
    return out


# --------------------------------------------------------------------------- #
# 首个偏离边界判定（固定规则表）
# --------------------------------------------------------------------------- #

_SUPPORT_CODES: frozenset[str] = frozenset(DECISION_CODES)
_SUPPORT_READY = False


def _support_codes() -> frozenset[str]:
    """支撑码白名单 = 本工具固定码 ∪ 冻结模块 AST 扫出的固定 reason 码。"""
    global _SUPPORT_CODES, _SUPPORT_READY
    if _SUPPORT_READY:
        return _SUPPORT_CODES
    try:
        reasons = frozenset(base._reason_allowlist())
    except Exception:  # noqa: BLE001 - 扫不出就用固定码子集
        reasons = frozenset()
    _SUPPORT_CODES = frozenset(DECISION_CODES) | reasons
    _SUPPORT_READY = True
    return _SUPPORT_CODES


def _support(code: str, count: int) -> dict[str, Any]:
    text = str(code)
    if text not in _support_codes() or not base.CODE_RE.fullmatch(text):
        text = "insufficient_evidence"
    return {"code": text, "count": int(count)}


def _decide(
    *,
    facts: Mapping[str, Any],
    shape: Mapping[str, Any],
    boundary: Mapping[str, Any],
    value_prov: Mapping[str, Any],
    source_prov: Mapping[str, Any],
    availability: Mapping[str, Any],
    axes: Mapping[str, Mapping[str, str]],
    axes_available: bool,
    retrieved_events: int,
    model_evidence: int,
) -> dict[str, Any]:
    """规则表：轴违规 → 来源根因 → 编造来源拆分 → 截断 → 改写 → 缺失 → undetermined。"""
    value_status = str(facts.get("value_hit", {}).get("status"))
    fab_status = str(facts.get("value_no_fabricated", {}).get("status"))
    source_status = str(facts.get("source_hit", {}).get("status"))

    # 规则 1：轴违规优先（作用域/实体/时效错是根因，值缺失是其下游）
    if axes_available:
        cross = axes.get("cross_entity", {})
        stale = axes.get("stale_source", {})
        if str(cross.get("state")) == "violation":
            return {
                "code": "wrong_entity_scope",
                "support": [
                    _support("axis_cross_entity_violation", 1),
                    _support(str(cross.get("reason")), 1),
                ],
                "gap": "none",
            }
        if str(stale.get("state")) == "violation":
            return {
                "code": "wrong_entity_scope",
                "support": [
                    _support("axis_stale_source_violation", 1),
                    _support(str(stale.get("reason")), 1),
                ],
                "gap": "none",
            }

    # 规则 2：来源是根因时先判来源。逐引用判定：某条期望来源「既没被检索到也没被引用」
    # = 检索没取到；「检索到了但没被引用」= 引用没带出来。两者是不同边界，不能合并。
    if source_status == "fail":
        expected = int(source_prov.get("expected_count") or 0)
        cited = int(source_prov.get("cited_matched") or 0)
        retrieved = int(source_prov.get("expected_retrieved_count") or 0)
        not_retrieved = int(source_prov.get("expected_neither_count") or 0)
        retrieved_uncited = int(source_prov.get("expected_retrieved_not_cited") or 0)
        unresolved = int(source_prov.get("retrieved_ids_unresolved") or 0)
        support = [
            _support("source_hit_fail", 1),
            _support("cited_partial" if cited else "cited_none", max(0, expected - cited)),
            _support("expected_not_retrieved", not_retrieved),
        ]
        if retrieved_uncited:
            support.append(_support("expected_retrieved_but_uncited", retrieved_uncited))
        if retrieved_events == 0 and retrieved == 0:
            return {"code": "undetermined", "support": support, "gap": "retrieval_events_absent"}
        if not_retrieved and unresolved:
            # 有候选身份没能还原成 (doc_code, unit_key)，无法断言"没检索到"。
            return {"code": "undetermined", "support": support, "gap": "source_ref_unresolved"}
        if not_retrieved:
            return {"code": "retrieval_missed_expected_source", "support": support, "gap": "none"}
        if retrieved_uncited:
            return {"code": "citation_omitted", "support": support, "gap": "none"}
        return {"code": "undetermined", "support": support, "gap": "citation_identity_weak"}

    # 规则 3：编造 → 拆分「证据里有」与「哪里都没有」。
    # 证据面 = 已引单位正文 / 未引候选单位正文 / 模型证据 / 事实值 / 记录标识 / 上下文。
    if fab_status == "fail" and int(value_prov.get("extra_count") or 0) > 0:
        extra = int(value_prov.get("extra_count") or 0)
        unbacked = int(value_prov.get("extra_in_none") or 0)
        value_surfaces = (
            int(value_prov.get("extra_in_cited_units") or 0)
            + int(value_prov.get("extra_in_uncited_retrieved") or 0)
            + int(value_prov.get("extra_in_model_evidence") or 0)
            + int(value_prov.get("extra_in_facts") or 0)
        )
        identity_surfaces = (
            int(value_prov.get("extra_in_fact_ids") or 0)
            + int(value_prov.get("extra_in_unit_identity") or 0)
            + int(value_prov.get("extra_in_document_name") or 0)
        )
        backed = value_surfaces + identity_surfaces
        support = [
            _support("value_no_fabricated_extra", extra),
            _support("extra_numbers_backed_by_evidence", backed),
            _support("extra_numbers_unbacked", unbacked),
        ]
        for key in (
            "extra_in_cited_units",
            "extra_in_uncited_retrieved",
            "extra_in_model_evidence",
            "extra_in_facts",
            "extra_in_fact_ids",
            "extra_in_unit_identity",
            "extra_in_document_name",
            "extra_in_context",
        ):
            if int(value_prov.get(key) or 0):
                support.append(_support(key, int(value_prov.get(key) or 0)))
        # 没有任何被判分器采信的「证据正文」可核对（既无引用正文也无事实值）→ 不下结论
        no_surface = (
            int(availability.get("cited_unit_text_chars") or 0) == 0
            and int(availability.get("fact_value_chars") or 0) == 0
            and model_evidence == 0
        )
        if no_surface and backed == 0:
            return {"code": "undetermined", "support": support, "gap": "unit_texts_absent"}
        if backed == 0:
            return {"code": "answer_value_extra_fabricated", "support": support, "gap": "none"}
        if int(value_prov.get("extra_key_max_chars") or 0) <= 2:
            # 1–2 位数字 key 在任何证据面都会命中：来源归属不可判，不硬判
            support.append(_support("insufficient_evidence", 1))
            if int(value_prov.get("extra_in_line_markers") or 0):
                support.append(
                    _support("extra_in_line_markers", int(value_prov.get("extra_in_line_markers") or 0))
                )
            return {"code": "undetermined", "support": support, "gap": "extra_origin_ambiguous"}
        if value_surfaces == 0:
            # 数字只出现在记录标识/单位标识里 → 业务值没跑偏，是引用没把这些数字带出来
            return {"code": "citation_omitted", "support": support, "gap": "none"}
        if int(value_prov.get("extra_in_cited_units") or 0) == 0 and int(
            value_prov.get("extra_in_facts") or 0
        ) == 0:
            return {"code": "citation_omitted", "support": support, "gap": "none"}
        return {"code": "answer_value_extra_fabricated", "support": support, "gap": "none"}

    # 规则 4：值缺失 → 截断 / 改写 / 真缺失
    if value_status == "fail":
        missing = int(value_prov.get("missing_count") or 0)
        expected = int(value_prov.get("expected_count") or 0)
        support = [
            _support("value_hit_fail", 1),
            _support(
                "value_hit_missing_all" if missing >= expected else "value_hit_missing_partial",
                missing,
            ),
        ]
        truncation_signals = (
            int(boundary.get("retrieval_truncated_count") or 0)
            + int(boundary.get("truncations") or 0)
            + int(bool(shape.get("tail_ellipsis")))
        )
        partial = int(value_prov.get("partial_prefix") or 0)
        if partial and truncation_signals:
            support.append(_support("truncation_signal", truncation_signals))
            support.append(_support("truncation_partial_prefix", partial))
            return {"code": "answer_value_truncated", "support": support, "gap": "none"}
        reformat_total = 0
        for family, code in (
            ("thousands_separator", "reformat_thousands_separator"),
            ("date_shape", "reformat_date_shape"),
            ("percent_decimal", "reformat_percent_decimal"),
            ("wan_unit", "reformat_wan_unit"),
            ("wording", "reformat_wording"),
        ):
            hits = int(value_prov.get(family) or 0)
            if hits:
                support.append(_support(code, hits))
                reformat_total += hits
        if reformat_total:
            return {"code": "answer_value_reformatted", "support": support, "gap": "none"}
        if str(shape.get("kind_code")) in ("", "unknown_kind"):
            return {"code": "undetermined", "support": support, "gap": "answer_text_unavailable"}
        if int(shape.get("text_chars") or 0) == 0:
            support.append(_support("answer_text_empty", 1))
        return {"code": "answer_value_absent", "support": support, "gap": "none"}

    return {
        "code": "undetermined",
        "support": [_support("insufficient_evidence", 1)],
        "gap": "no_failed_check",
    }


# --------------------------------------------------------------------------- #
# 单案分析
# --------------------------------------------------------------------------- #

def _analyze_case(
    case: Any,
    mapped: Any,
    scored: Any,
    envelopes: Sequence[Mapping[str, Any]],
    document_codes: Mapping[str, str],
    plan_quality: str,
    axes: Mapping[str, Mapping[str, str]],
    axes_available: bool,
    lookup: Any,
) -> dict[str, Any]:
    outcome = scored.outcome
    checks = {str(item.check_id): item for item in (scored.result.checks if scored.result else ())}
    facts = _check_facts(checks)

    answer_payload: Mapping[str, Any] = {}
    commit_payload: Mapping[str, Any] = {}
    if envelopes:
        events = [
            item
            for item in ((envelopes[-1].get("capture") or {}).get("events") or [])
            if isinstance(item, Mapping)
        ]
        rows = _payloads(events, "answer_result")
        answer_payload = rows[-1] if rows else {}
        rows = _payloads(events, "commit_observed")
        commit_payload = rows[-1] if rows else {}

    answer_text = answer_payload.get("text") if isinstance(answer_payload.get("text"), str) else ""
    commit_text = commit_payload.get("text") if isinstance(commit_payload.get("text"), str) else ""
    product_text = str(getattr(outcome, "text", "") or "")
    shape = _shape(product_text)
    kind_raw = str(getattr(outcome, "kind", "") or "")
    shape["kind_code"] = kind_raw if kind_raw in KIND_CODES else "unknown_kind"
    shape["answer_text_chars"] = len(answer_text)
    shape["commit_text_chars"] = len(commit_text)
    shape["answer_commit_text_equal"] = bool(answer_text) and answer_text == commit_text

    boundary, internal = _events_facts(envelopes)

    expected_values = tuple(str(item) for item in getattr(mapped, "expected_values", ()) or ())
    hit_evidence = dict(getattr(checks.get("value_hit"), "evidence", {}) or {})
    fab_evidence = dict(getattr(checks.get("value_no_fabricated"), "evidence", {}) or {})
    missing_rows = [str(item) for item in (hit_evidence.get("missing") or ())] if _is_seq(
        hit_evidence.get("missing")
    ) else []
    extra_rows = [str(item) for item in (fab_evidence.get("extra") or ())] if _is_seq(
        fab_evidence.get("extra")
    ) else []
    numeric_expected = sum(1 for item in expected_values if _NUMERIC_ONLY.fullmatch(_normalize(item)))
    families = _reformat_families(product_text, missing_rows)
    value_prov: dict[str, Any] = {
        "expected_count": len(expected_values),
        "missing_count": len(missing_rows),
        "numeric_expected_count": numeric_expected,
        "text_expected_count": len(expected_values) - numeric_expected,
        "reformat_family_counts": dict(families),
        "best_common_block_permille": _best_block_permille(product_text, missing_rows),
        "extra_count": len(extra_rows),
    }
    for key in (
        "thousands_separator",
        "date_shape",
        "percent_decimal",
        "wan_unit",
        "wording",
        "partial_prefix",
    ):
        value_prov[key] = int(families.get(key, 0))

    citations = list(getattr(outcome, "citations", ()) or ())
    cited_ids: list[str] = []
    for citation in citations:
        cited_ids.extend(str(item) for item in getattr(citation, "unit_ids", ()) or () if str(item))
    units: dict[str, Mapping[str, Any]] = {}
    for projection in internal["projects"]:
        rows = projection.get("units")
        if not _is_seq(rows):
            continue
        for row in rows:
            if isinstance(row, Mapping) and row.get("unit_id") is not None:
                units[str(row.get("unit_id"))] = row

    cited_texts: list[str] = []
    cited_unit_text_chars = 0
    cited_units_present = 0
    for unit_id in dict.fromkeys(cited_ids):
        unit = units.get(unit_id)
        if isinstance(unit, Mapping):
            cited_units_present += 1
            cited_unit_text_chars += len(unit.get("text")) if isinstance(unit.get("text"), str) else 0
            cited_texts.extend(_unit_texts(unit))
    cited_set = set(cited_ids)
    uncited_texts: list[str] = []
    for unit_id in dict.fromkeys(internal["retrieved_ids"]):
        if unit_id in cited_set:
            continue
        unit = units.get(unit_id)
        if isinstance(unit, Mapping):
            uncited_texts.extend(_unit_texts(unit))

    unit_identity_texts: list[str] = []
    document_name_texts: list[str] = []
    for unit in units.values():
        for key in ("unit_id", "unit_key", "document_id"):
            if isinstance(unit.get(key), str):
                unit_identity_texts.append(unit[key])
        if isinstance(unit.get("document_name"), str):
            document_name_texts.append(unit["document_name"])

    def _keys_of(texts: Sequence[str]) -> set[str]:
        keys: set[str] = set()
        for text in texts:
            keys |= _number_keys(text)
        return keys

    cited_keys = _keys_of(cited_texts)
    uncited_keys = _keys_of(uncited_texts)
    model_keys = _keys_of(internal["model_evidence_texts"])
    fact_keys = _keys_of(internal["fact_values"])
    fact_id_keys = _keys_of(internal["fact_ids"])
    unit_id_keys = _keys_of(unit_identity_texts)
    document_name_keys = _keys_of(document_name_texts)
    context_keys = _keys_of(internal["context_texts"])

    counters = {
        "extra_in_cited_units": 0,
        "extra_in_uncited_retrieved": 0,
        "extra_in_model_evidence": 0,
        "extra_in_facts": 0,
        "extra_in_fact_ids": 0,
        "extra_in_unit_identity": 0,
        "extra_in_document_name": 0,
        "extra_in_context": 0,
        "extra_in_none": 0,
    }
    for key in extra_rows:
        hit = False
        for name, keys in (
            ("extra_in_cited_units", cited_keys),
            ("extra_in_uncited_retrieved", uncited_keys),
            ("extra_in_model_evidence", model_keys),
            ("extra_in_facts", fact_keys),
            ("extra_in_fact_ids", fact_id_keys),
            ("extra_in_unit_identity", unit_id_keys),
            ("extra_in_document_name", document_name_keys),
            ("extra_in_context", context_keys),
        ):
            if key in keys:
                counters[name] += 1
                hit = True
        if not hit:
            counters["extra_in_none"] += 1
    value_prov.update(counters)
    longest_extra = max((len(key) for key in extra_rows), default=0)
    value_prov["extra_key_max_chars"] = int(longest_extra)
    value_prov["answer_digit_keys_total"] = len(_number_keys(product_text))
    # 候选解释：答案的行序号标记（``1.`` / ``2)`` …）本身就是数字 token，且不在任何证据面。
    line_markers = {str(index) for index in range(1, max(1, int(shape.get("line_count") or 0)) + 1)}
    value_prov["extra_in_line_markers"] = sum(1 for key in extra_rows if key in line_markers)
    fact_value_chars = sum(len(item) for item in internal["fact_values"])
    availability = {
        "unit_rows_total": len(units),
        "unit_rows_with_text": sum(
            1 for unit in units.values() if isinstance(unit.get("text"), str) and unit.get("text")
        ),
        "unit_rows_with_raw_fields": sum(
            1 for unit in units.values() if isinstance(unit.get("raw_fields"), Mapping) and unit.get("raw_fields")
        ),
        "unit_rows_with_date_fields": sum(
            1 for unit in units.values() if isinstance(unit.get("date_fields"), Mapping) and unit.get("date_fields")
        ),
        "cited_units_present": cited_units_present,
        "cited_unit_text_chars": cited_unit_text_chars,
        "fact_rows_total": int(boundary.get("direct_rag_fact_count") or 0),
        "fact_value_chars": fact_value_chars,
        "model_input_events": int(boundary.get("model_input_event_count") or 0),
        "context_message_count": len(internal["context_texts"]),
    }

    expected_refs = list(getattr(mapped, "expected_sources", ()) or ())
    cited_matched = 0
    retrieved_matched = 0
    retrieved_any_version = 0
    doc_only = 0
    retrieved_not_cited = 0
    neither = 0
    resolved_ids = 0
    for unit_id in dict.fromkeys(internal["retrieved_ids"]):
        unit = units.get(unit_id)
        if isinstance(unit, Mapping) and _unit_identity(unit, document_codes, lookup) is not None:
            resolved_ids += 1
    for ref in expected_refs:
        ref_map = dict(ref)
        locator = dict(ref_map.get("locator") or {})
        if not locator and not ref_map.get("unit_key"):
            doc_only += 1
        cited_ok = any(_check_source(ref_map, citation) for citation in citations)
        cited_matched += int(cited_ok)
        loose = dict(ref_map)
        loose["locator"] = {key: value for key, value in locator.items() if key != "version_number"}
        retrieved_ok = False
        retrieved_loose = False
        for unit_id in dict.fromkeys(internal["retrieved_ids"]):
            unit = units.get(unit_id)
            if not isinstance(unit, Mapping):
                continue
            identity = _unit_identity(unit, document_codes, lookup)
            if identity is None:
                continue
            if _check_source(ref_map, identity):
                retrieved_ok = True
            if _check_source(loose, identity):
                retrieved_loose = True
        retrieved_matched += int(retrieved_ok)
        retrieved_any_version += int(retrieved_loose)
        retrieved_not_cited += int(retrieved_ok and not cited_ok)
        neither += int((not retrieved_ok) and (not cited_ok))
    source_prov = {
        "expected_count": len(expected_refs),
        "cited_matched": cited_matched,
        "citation_total": len(citations),
        "citation_unit_id_count": len(cited_ids),
        "expected_retrieved_count": retrieved_matched,
        "expected_retrieved_any_version": retrieved_any_version,
        "expected_retrieved_not_cited": retrieved_not_cited,
        "expected_neither_count": neither,
        "expected_doc_only_count": doc_only,
        "retrieved_ids_resolved": resolved_ids,
        "retrieved_ids_unresolved": len(set(internal["retrieved_ids"])) - resolved_ids,
    }

    decision = _decide(
        facts=facts,
        shape=shape,
        boundary=boundary,
        value_prov=value_prov,
        source_prov=source_prov,
        availability=availability,
        axes=axes,
        axes_available=axes_available,
        retrieved_events=int(boundary.get("retrieval_event_count") or 0),
        model_evidence=int(boundary.get("model_input_evidence_count") or 0),
    )

    # 判定之外仍然开放的鉴别点（固定码）：写清"证据里没有哪一项"，避免看起来已闭环。
    open_questions: list[str] = []
    if extra_rows and int(value_prov.get("extra_key_max_chars") or 0) <= 2:
        open_questions.append("single_digit_key_unattributable")
    # 事件协议未采集 plan.field_role：无法区分"整行枚举"与"按字段取值"两条渲染分支。
    open_questions.append("field_role_not_captured")
    if str(boundary.get("plan_path_code")) == "rag" and int(boundary.get("retrieval_event_count") or 0) == 0:
        open_questions.append("retrieval_not_captured_for_rag_path")
    if str(facts.get("value_hit", {}).get("status")) == "fail":
        # 重建的评分行不带 pagination，截断类假设只能靠文本形态与 retrieval.truncated 间接判。
        open_questions.append("pagination_not_reconstructed")

    return {
        "case_id": str(case.case_id),
        "quality_status": _coded(plan_quality),
        "failed_check_ids": sorted(
            check_id for check_id, row in facts.items() if row.get("status") == "fail"
        ),
        "check_statuses": {check_id: row.get("status", "unknown") for check_id, row in facts.items()},
        "check_facts": facts,
        "answer_shape": shape,
        "boundary_events": boundary,
        "value_provenance": value_prov,
        "source_provenance": source_prov,
        "evidence_availability": availability,
        "axes_available": bool(axes_available),
        "axes": {name: dict(axes.get(name) or {}) for name in AXIS_NAMES},
        "first_boundary": decision["code"],
        "boundary_support": decision["support"],
        "decision_code": decision["support"][0]["code"] if decision["support"] else "insufficient_evidence",
        "undetermined_gap": decision["gap"] if decision["gap"] in GAP_CODES else "none",
        "open_questions": open_questions,
    }


# --------------------------------------------------------------------------- #
# 交叉轴（只出 state / reason）
# --------------------------------------------------------------------------- #

def _build_axis_map(
    cases: Sequence[Any],
    plan_rows: Sequence[Mapping[str, Any]],
    envelopes_by_case: Mapping[str, Sequence[Mapping[str, Any]]],
    annotation: Any,
    hard: Any,
) -> tuple[dict[str, dict[str, dict[str, str]]], bool]:
    out: dict[str, dict[str, dict[str, str]]] = {}
    ok = True
    for index, case in enumerate(cases):
        case_id = str(case.case_id)
        if case_id not in SELECTED_CASES:
            continue
        plan_row = plan_rows[index]
        entries = [
            {
                "turn_index": int(row["turn_index"]),
                "status": str(row["status"]),
                "error": row.get("error"),
                "evidence": None,
            }
            for row in (plan_row.get("turns") or ())
        ]
        cursor = 0
        envelopes = envelopes_by_case.get(case_id) or ()
        for entry in entries:
            if entry["status"] == "executed":
                if cursor < len(envelopes):
                    entry["evidence"] = envelopes[cursor]
                cursor += 1
        audit = {"quality_status": str(plan_row.get("quality_status")), "turns": entries}
        try:
            result = hard.classify_case_evidence(case, annotation, audit)
            axes = {}
            for axis in AXIS_NAMES:
                verdict = result.axes[axis]
                axes[axis] = {
                    "state": _coded(getattr(verdict, "state", "unknown")),
                    "reason": _coded(getattr(verdict, "reason", "unknown_code")),
                }
            out[case_id] = axes
        except Exception:  # noqa: BLE001 - 单题分类失败不改写结论，只标记不可用
            ok = False
            out[case_id] = {
                axis: {"state": "unknown", "reason": "classification_failed"} for axis in AXIS_NAMES
            }
    return out, ok


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
    parser.add_argument("--out-dir", default=str(base.REPO / REPORT_REL / "evidence" / "02-case-boundary"))
    parser.add_argument("--cases", default=",".join(SELECTED_CASES))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(list(argv))
    for name in ("key", "binding", "evidence_root", "receipt", "seal_manifest"):
        if not getattr(args, name):
            _fail("argument_missing", "_parse_args")
    return args


def _diag_name(exc: BaseException) -> str:
    """临时诊断：只回显异常**类型名 + 本文件行号**（不含消息），定位 SAFE 构建失败点。"""
    name = type(exc).__name__
    line = 0
    tb = exc.__traceback__
    while tb is not None:
        if str(tb.tb_frame.f_code.co_filename).endswith("r2_case_boundary.py"):
            line = int(tb.tb_lineno)
        tb = tb.tb_next
    slug = "".join(ch for ch in name.lower() if ch.isalnum() or ch == "_")
    return f"diag_{slug}_{line}"


def _degraded_record(case_id: str, plan_quality: str, gap: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "quality_status": _coded(plan_quality),
        "failed_check_ids": [],
        "check_statuses": {},
        "check_facts": {},
        "answer_shape": {},
        "boundary_events": {},
        "value_provenance": {},
        "source_provenance": {},
        "evidence_availability": {},
        "axes_available": False,
        "axes": {axis: {"state": "unknown", "reason": "classification_failed"} for axis in AXIS_NAMES},
        "first_boundary": "undetermined",
        "boundary_support": [_support("insufficient_evidence", 1)],
        "open_questions": ["field_role_not_captured"],
        "decision_code": "insufficient_evidence",
        "undetermined_gap": gap,
    }


def main(argv: Sequence[str]) -> int:
    global _scorers
    STAGE[0] = "get_network_guard"
    guard = base.NetGuard()
    guard.install()
    guard.positive_control()

    STAGE[0] = "parse_args"
    args = _parse_args(argv)
    out_dir = pathlib.Path(args.out_dir)
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
            "p2_h2_v3_controlled_execute_case_boundary",
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
    _scorers = scorers_mod
    _install_whitelist()
    base._CHECK_ID_SET = frozenset(str(item) for item in CHECK_IDS)

    STAGE[0] = "record_hard_digest"
    hard_sha = base._sha256_file(base.HARD_PATH)
    evaluation = base.BACKEND_SRC / "mktkb" / "evaluation"
    try:
        module_sha = [
            {"name": "p2_scoring", "sha256": base._sha256_file(evaluation / "p2_scoring.py")},
            {"name": "scorers", "sha256": base._sha256_file(evaluation / "scorers.py")},
            {"name": "p2_score_run", "sha256": base._sha256_file(evaluation / "p2_score_run.py")},
            {"name": "p2_evidence_io", "sha256": base._sha256_file(evaluation / "p2_evidence_io.py")},
            {"name": "p2_hard_evidence", "sha256": hard_sha},
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
    if not match_all or failures:
        _dump(
            {
                "ok": False,
                "error": "reconstruction_mismatch",
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
            axes_map, axes_available = _build_axis_map(
                cases, plan["cases"], envelopes_by_case, bundle.annotation, hard
            )
        except Exception:  # noqa: BLE001
            axes_available = False

    STAGE[0] = "analyze_cases"
    records: list[dict[str, Any]] = []
    for case_id in SELECTED_CASES:
        if case_id not in results:
            records.append(_degraded_record(case_id, plan_quality.get(case_id, "error"), "check_evidence_absent"))
            continue
        axes = axes_map.get(case_id) or {
            axis: {"state": "unknown", "reason": "classification_failed"} for axis in AXIS_NAMES
        }
        case = next(item for item in cases if str(item.case_id) == case_id)
        try:
            record = _analyze_case(
                case,
                mapped_cases[case_id],
                results[case_id],
                envelopes_by_case.get(case_id) or (),
                document_codes,
                plan_quality.get(case_id, "error"),
                axes,
                axes_available,
                scoring._lookup_document_code,  # noqa: SLF001
            )
        except base.ToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - 单案失败降级为 undetermined，不猜
            record = _degraded_record(
                case_id, plan_quality.get(case_id, "error"), _diag_name(exc)
            )
        record["axes_available"] = bool(axes_available)
        records.append(record)

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
        }
        for record in records
    ]
    undetermined_gaps = [
        row["undetermined_gap"] for row in summary_rows if row["first_boundary"] == "undetermined"
    ]
    summary = {
        "ok": True,
        "run_id": run_id,
        "case_plan_sha256": plan_sha,
        "hard_module_sha256": hard_sha,
        "module_sha256": module_sha,
        "hard_module_import_ok": hard is not None,
        "selected_case_ids": list(SELECTED_CASES),
        "case_count": len(records),
        "envelope_count": sum(len(item) for item in envelopes_by_case.values()),
        "reconstruction_match_all": bool(match_all),
        "custody_ok": bool(custody_ok),
        "scoring_failures": int(failures),
        "unsafe_code_count": 0,
        "rules": list(RULES),
        "cases": summary_rows,
        "undetermined_gap": undetermined_gaps[0] if undetermined_gaps else "none",
        "netguard": guard.as_dict(),
    }
    _dump(summary, out_dir / "summary.json", echo=not args.quiet)
    for record in records:
        _dump(record, out_dir / f"{record['case_id']}.json", echo=False)
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
        }.get(type(exc).__name__, "internal_error")
        _emit_failure(code, STAGE[0])
        raise SystemExit(3) from None
