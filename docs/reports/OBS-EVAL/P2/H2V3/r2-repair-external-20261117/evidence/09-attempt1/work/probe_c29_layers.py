"""R2-205D：attempt1 单个 case 的**逐层结构探针**（只读、零出站、只出固定码/计数/布尔/哈希）。

用途
----
`r2_boundary_ext.py` 的 8 层表把 ``plan_observed`` 只投影成 path/mode/enumerate/filters/terms，
把 ``direct_rag_answer`` 只投影成 fact_count/cited/answer_source。本批诊断还需要三样它没有投影的
**固定码**（不含任何题干/答案/实体/业务数字）：

1. ``plan_observed.field_role`` / ``field_roles`` / ``state_pending_slot`` / ``state_last_kind``；
2. ``direct_rag_answer.reason`` —— 把它与产品源码里的**固定常量码集合**做 sha256 等值匹配，
   命中即报码名；不命中只说形状（大写码/小写码/其它）+ 长度 + sha256 前 16 位，不回显原文；
3. 拒绝文案的**模板族计数**：只统计一组产品文案固定词元的出现次数（不输出文本本身）。

本文件不 import 产品代码、不构造索引、不跑检索，只解封一轮 envelope 后读事件协议字段。
出站阻断复用 ``r2_safe_project.NetGuard``（socket/urllib/httpx + 子进程守卫 + 正对照）。

运行（私有路径一律命令行传入，不写进本文件）
------------------------------------------
    .venv\\Scripts\\python.exe -X utf8 probe_c29_layers.py ^
      --key <ev.key> --case-plan <case-plan.json> --evidence-root <run 证据目录> ^
      --case H2V3-C29 --out <输出 json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from typing import Any, Mapping, Sequence

_WORK = pathlib.Path(__file__).resolve().parents[3] / "work"
if str(_WORK) not in sys.path:
    sys.path.insert(0, str(_WORK))

import r2_safe_project as base  # noqa: E402 - 复用出站阻断与固定码工具

CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
UPPER_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
HEX_RE = re.compile(r"^[0-9a-f]{8,64}$")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
CASE_ID_RE = re.compile(r"^H2V3-C[0-9]{2}$")

#: 产品源码里"拒答/驳回"固定码的候选集合（``rag/answer.py`` 的 ``_no_answer`` 实参 +
#: ``rag/errors.py`` 的 ``FactRejected`` 子类码 + ``rag/copy.py`` 的模板键）。全部是产品常量，
#: 不是题干/答案/实体/业务值；只用于把记录里的 reason **反向匹配成码名**。
KNOWN_REASON_CODES = (
    "ANAPHORA_NEW_CONTENT",
    "CHAT_ERROR",
    "CHAT_UNAVAILABLE",
    "CONFLICTING_VALUES",
    "CROSS_ENTITY",
    "CROSS_FIELD",
    "DOCUMENT_NOT_FOUND",
    "EFFECTIVE_WINDOW_CONFLICT",
    "EFFECTIVE_WINDOW_EXPIRED",
    "EMPTY_QUERY",
    "FACT_REJECTED",
    "FIELD_NOT_RECORDED",
    "FORGED_VALUE",
    "MISSING_SLOT",
    "MODEL_OUTPUT_INVALID",
    "MULTIPLE_ENTITIES",
    "NOT_YET_EFFECTIVE",
    "NO_ENUMERABLE_RECORD",
    "NO_EVIDENCE",
    "NO_RECORD_FOR_ENTITY",
    "NO_SUPPORTING_SENTENCE",
    "PAGE_OUT_OF_RANGE",
    "POLICY_TOPIC_NOT_FOUND",
    "RECORD_ONLY",
    "SECURITY_RESTRICTED_CONTACT",
    "STALE_SOURCE",
    "UNKNOWN_STORE",
    "UNSUPPORTED_CLAIM",
    "UNSUPPORTED_FINANCIAL_METRIC",
)

#: 产品固定码：``rag/query.py`` 的字段角色闭集（用于把字段角色**反匹配成角色名**）。
KNOWN_FIELD_ROLES = (
    "address",
    "clause",
    "contact",
    "date",
    "effective_from",
    "effective_to",
    "height",
    "identifier",
    "location",
    "note",
    "phone",
    "price",
    "price_type",
    "quantity",
    "spec",
    "status",
)

#: 产品固定词表：``rag/query.py`` 的 ``CONTRACT_CREDENTIAL_WORDS``（R1/102c 凭据族）。
#: 只在本进程内做"策略词是否出现在本轮 plan.terms 里"的**计数/索引**判定，不输出任何文本。
CONTRACT_CREDENTIAL_WORDS = (
    "合同",
    "账号",
    "账户",
    "银行卡",
    "凭证",
    "开户行",
    "开户银行",
    "税号",
    "密码",
)

#: 拒绝/作答文案里的**产品固定词元**（不是业务值）：只统计出现次数，不输出文本。
#: 键是固定 ASCII 码（供出口白名单），值是产品文案词元；报告里只出现码与计数。
TEXT_TOKENS = (
    ("according_to_source", "根据资料"),
    ("source_in", "资料中"),
    ("not_in_source", "未在资料"),
    ("not_found_word", "未找到"),
    ("not_recorded", "未记录"),
    ("not_collected", "未收录"),
    ("no_record", "无记录"),
    ("no_have", "没有"),
    ("cannot", "不能"),
    ("unable", "无法"),
    ("please", "请"),
    ("store_word", "门店"),
    ("item_word", "物品"),
    ("price_word", "价格"),
    ("location_word", "地点"),
    ("field_word", "字段"),
    ("record_word", "记录"),
    ("query_word", "查询"),
    ("piece_word", "条"),
    ("that_word", "该"),
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _payloads(events: Sequence[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for event in events:
        if isinstance(event, Mapping) and str(event.get("kind")) == kind:
            payload = event.get("payload")
            if isinstance(payload, Mapping):
                rows.append(payload)
    return rows


def _code(value: Any) -> str:
    text = str(value or "")
    return text if CODE_RE.fullmatch(text) else "unknown_code"


def _str_shape(value: Any) -> dict[str, Any]:
    """字符串字段的**形状**投影：是否出现、长度、形状类别、（可选）命中固定码名。"""
    if not isinstance(value, str) or not value:
        return {"present": False, "chars": 0, "shape": "absent", "sha256": "none", "known_code": "none"}
    sha = _sha(value)
    known = "unmatched"
    for candidate in KNOWN_REASON_CODES:
        if _sha(candidate) == sha:
            known = candidate
            break
    if UPPER_RE.fullmatch(value):
        shape = "upper_code"
    elif CODE_RE.fullmatch(value):
        shape = "lower_code"
    elif DATE_RE.fullmatch(value):
        shape = "date"
    else:
        shape = "other"
    return {"present": True, "chars": len(value), "shape": shape, "sha256": sha[:16], "known_code": known}


def _field_role_name(value: Any) -> str:
    """把字段角色**反匹配成产品角色名**（只比 sha256，不回显取值）。"""
    if not isinstance(value, str) or not value:
        return "none"
    sha = _sha(value)
    for candidate in KNOWN_FIELD_ROLES:
        if _sha(candidate) == sha:
            return candidate
    return "unmatched"


def _credential_term_hits(terms: Any) -> tuple[int, list[int]]:
    """产品凭据词族在本轮 plan.terms 上的命中**计数与族内索引**（不输出词/题面）。"""
    joined = "".join(str(item) for item in (terms or ()) if str(item))
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", joined.lower())
    hits = [index for index, word in enumerate(CONTRACT_CREDENTIAL_WORDS) if word in normalized]
    return len(hits), hits


def _list_codes(values: Any, limit: int = 16) -> list[str]:
    out: list[str] = []
    if not isinstance(values, (list, tuple)):
        return out
    for item in values:
        code = _code(item)
        if code not in out:
            out.append(code)
        if len(out) >= limit:
            break
    return out


def _token_counts(text: str) -> dict[str, int]:
    return {code: int(text.count(token)) for code, token in TEXT_TOKENS}


def _assert_safe(node: Any, depth: int = 0) -> None:
    """自建出口白名单：只允许 int/bool/None/list/dict 与固定码/哈希形态的字符串。"""
    if depth > 8:
        raise base.ToolError("unsafe_output_depth", "assert_safe")
    if node is None or isinstance(node, bool) or isinstance(node, int):
        return
    if isinstance(node, str):
        if CODE_RE.fullmatch(node) or UPPER_RE.fullmatch(node) or HEX_RE.fullmatch(node):
            return
        if CASE_ID_RE.fullmatch(node):
            return
        raise base.ToolError("unsafe_output_string", "assert_safe")
    if isinstance(node, Mapping):
        for key, value in node.items():
            if not isinstance(key, str) or not (CODE_RE.fullmatch(key) or UPPER_RE.fullmatch(key)):
                raise base.ToolError("unsafe_output_key", "assert_safe")
            _assert_safe(value, depth + 1)
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _assert_safe(item, depth + 1)
        return
    raise base.ToolError("unsafe_output_type", "assert_safe")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--case-plan", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--case", default="H2V3-C29")
    parser.add_argument("--out", default=None)
    return parser.parse_args(list(argv))


def main(argv: Sequence[str]) -> int:
    guard = base.NetGuard()
    guard.install()
    guard.positive_control()

    args = _parse_args(argv)
    try:
        key = pathlib.Path(args.key).read_bytes().strip()
    except OSError:
        raise base.ToolError("key_unreadable", "main") from None
    if not 16 <= len(key) <= 4096:
        raise base.ToolError("key_invalid", "main")

    case_plan = base._read_json(pathlib.Path(args.case_plan))
    rows = [row for row in (case_plan.get("cases") or ()) if str(row.get("case_id")) == args.case]
    if len(rows) != 1:
        raise base.ToolError("case_not_in_plan", "main")
    turns = [turn for turn in (rows[0].get("turns") or ()) if str(turn.get("status")) == "executed"]
    if not turns:
        raise base.ToolError("case_turn_not_executed", "main")
    turn_row = turns[-1]

    from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: PLC0415

    path = pathlib.Path(args.evidence_root) / str(turn_row["evidence_file"])
    bindings = {str(name): str(value) for name, value in dict(case_plan.get("bindings") or {}).items()}
    envelope: dict[str, Any] | None = None
    binding_mode = "checked"
    try:
        envelope = read_encrypted_evidence(path, key=key, expected_bindings=bindings)
    except Exception:  # noqa: BLE001 - 绑定口径不符时退回结构读取，但**登记**这一事实
        try:
            envelope = read_encrypted_evidence(path, key=key, expected_bindings=None)
            binding_mode = "unchecked"
        except Exception:  # noqa: BLE001 - 仍失败只报固定码
            raise base.ToolError("envelope_read_failed", "main") from None

    events = [
        event
        for event in ((envelope.get("capture") or {}).get("events") or ())
        if isinstance(event, Mapping)
    ]
    plans = _payloads(events, "plan_observed")
    retrievals = _payloads(events, "retrieval_observed")
    model_inputs = _payloads(events, "model_input")
    model_outputs = _payloads(events, "model_output")
    directs = _payloads(events, "direct_rag_answer")
    answers = _payloads(events, "answer_result")
    commits = _payloads(events, "commit_observed")
    projection = envelope.get("db_projection") if isinstance(envelope.get("db_projection"), Mapping) else {}

    plan = plans[-1] if plans else {}
    direct = directs[-1] if directs else {}
    answer = answers[-1] if answers else {}
    commit = commits[-1] if commits else {}

    facts = [row for row in (direct.get("facts") or ()) if isinstance(row, Mapping)]
    answer_text = answer.get("text") if isinstance(answer.get("text"), str) else ""
    direct_text = direct.get("text") if isinstance(direct.get("text"), str) else ""
    commit_text = commit.get("text") if isinstance(commit.get("text"), str) else ""

    kind_counts: dict[str, int] = {}
    for event in events:
        code = _code(event.get("kind"))
        kind_counts[code] = kind_counts.get(code, 0) + 1

    report = {
        "ok": True,
        "case_id": args.case if CASE_ID_RE.fullmatch(str(args.case)) else "unknown_case",
        "turn_index": int(turn_row["turn_index"]),
        "binding_mode": "checked" if binding_mode == "checked" else "unchecked",
        "event_kind_counts": dict(sorted(kind_counts.items())),
        "intent_fields": {
            "event_count": len(plans),
            "path_code": _code(plan.get("path")),
            "mode_code": _code(plan.get("mode")),
            "enumerate": bool(plan.get("enumerate") is True),
            "include_future": bool(plan.get("include_future") is True),
            "clarification_present": bool(plan.get("clarification")),
            "as_of_present": isinstance(plan.get("as_of"), str) and bool(plan.get("as_of")),
            "terms_count": len([item for item in (plan.get("terms") or ()) if str(item)]),
            "filters_count": len(dict(plan.get("filters") or {})),
            "filter_codes": sorted(_code(key) for key in dict(plan.get("filters") or {})),
            "field_role": _str_shape(plan.get("field_role")),
            "field_role_name": _field_role_name(plan.get("field_role")),
            "field_roles_codes": _list_codes(plan.get("field_roles")),
            "field_roles_count": len([item for item in (plan.get("field_roles") or ()) if str(item)]),
            "credential_term_hit_count": _credential_term_hits(plan.get("terms"))[0],
            "credential_term_hit_indices": _credential_term_hits(plan.get("terms"))[1],
            "state_keys_count": len([item for item in (plan.get("state_keys") or ()) if str(item)]),
            "state_as_of_present": isinstance(plan.get("state_as_of"), str) and bool(plan.get("state_as_of")),
            "state_pending_slot": _str_shape(plan.get("state_pending_slot")),
            "state_last_kind": _str_shape(plan.get("state_last_kind")),
        },
        "candidates": {
            "event_count": sum(1 for row in retrievals if row.get("candidate") is True),
            "unit_total": sum(
                len(row.get("unit_ids") or ()) for row in retrievals if row.get("candidate") is True
            ),
            "state": "not_captured" if not any(row.get("candidate") is True for row in retrievals) else "present",
        },
        "retrieval": {
            "event_count": len(retrievals),
            "initial_rows": sum(1 for row in retrievals if row.get("candidate") is not True),
            "unit_total": sum(
                len(row.get("unit_ids") or ()) for row in retrievals if row.get("candidate") is not True
            ),
            "truncated_count": sum(1 for row in retrievals if row.get("truncated") is True),
            "empty_count": sum(1 for row in retrievals if row.get("empty") is True),
            "state": "not_captured" if not retrievals else "present",
        },
        "model_input": {
            "input_event_count": len(model_inputs),
            "output_event_count": len(model_outputs),
            "state": "present" if model_inputs else ("not_applicable" if directs else "absent"),
        },
        "fact_admission": {
            "event_count": len(directs),
            "kind_code": _code(direct.get("kind")),
            "answer_source_code": _code(direct.get("answer_source")),
            "reason": _str_shape(direct.get("reason")),
            "fact_count": int(direct.get("fact_count") or 0),
            "fact_rows": len(facts),
            "cited_unit_count": len([item for item in (direct.get("cited_unit_ids") or ()) if str(item)]),
            "fact_entity_label_present": sum(1 for row in facts if isinstance(row.get("entity_label"), str)),
            "fact_entity_key_present": sum(1 for row in facts if isinstance(row.get("entity_key"), str)),
            "fact_source_unit_id_present": sum(1 for row in facts if isinstance(row.get("source_unit_id"), str)),
            "fact_field_role_codes": _list_codes([row.get("field_role") for row in facts]),
            "state_keys_count": len([item for item in (direct.get("state_keys") or ()) if str(item)]),
        },
        "render": {
            "kind_code": _code(answer.get("kind")),
            "text_chars": len(answer_text),
            "digits_present": bool(re.search(r"\d", answer_text)),
            "lines": len([line for line in answer_text.splitlines() if line.strip()]),
            "token_counts": _token_counts(answer_text),
            "text_sha256": _sha(answer_text)[:16] if answer_text else "none",
            "direct_text_chars": len(direct_text),
            "direct_text_sha256": _sha(direct_text)[:16] if direct_text else "none",
            "direct_text_equal_answer_text": bool(answer_text) and answer_text == direct_text,
        },
        "citation": {
            "source_ids_count": len([item for item in (answer.get("source_ids") or ()) if str(item)]),
            "missing_fields_count": len([item for item in (answer.get("missing_fields") or ()) if str(item)]),
            "candidates_count": int(answer.get("candidates") or 0),
            "conflicts_count": int(answer.get("conflicts") or 0),
            "error_code": _code(answer.get("error_code")) if answer.get("error_code") else "none",
            "reason": _str_shape(answer.get("reason")),
        },
        "commit": {
            "event_count": len(commits),
            "kind_code": _code(commit.get("kind")),
            "requested_kind": _code(commit.get("requested_kind")),
            "text_chars": len(commit_text),
            "text_equal_answer_text": bool(commit_text) and commit_text == answer_text,
            "revision_before": int(commit.get("revision_before") or 0),
            "revision_after": int(commit.get("revision_after") or 0),
            "knowledge_changed": bool(commit.get("knowledge_changed") is True),
            "error_code": _code(commit.get("error_code")) if commit.get("error_code") else "none",
        },
        "projection": {
            "units_total": len([row for row in (projection.get("units") or ()) if isinstance(row, Mapping)]),
            "message_sources_total": len(
                [row for row in (projection.get("message_sources") or ()) if isinstance(row, Mapping)]
            ),
            "unresolved_unit_ids_total": len(
                [item for item in (projection.get("unresolved_unit_ids") or ()) if str(item)]
            ),
            "request_keys": sorted(_code(key) for key in dict(projection.get("request") or {})),
            "pre_revision": int(projection.get("pre_revision") or 0),
        },
        "netguard": guard.as_dict(),
    }
    _assert_safe(report)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        target = pathlib.Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def _emit_failure(code: Any) -> None:
    safe = str(code) if CODE_RE.fullmatch(str(code)) else "internal_error"
    print(json.dumps({"ok": False, "error": safe}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except base.ToolError as exc:  # 只回显固定码
        _emit_failure(exc.code)
        raise SystemExit(2) from None
    except Exception:  # noqa: BLE001 - 绝不回显 str(exc)/traceback
        _emit_failure("internal_error")
        raise SystemExit(3) from None
