"""r0 同轮适配与一致性校验（纯函数；导入期零 IO、零网络、零 dotenv）。

本模块只承担 r0 修复的三件确定性工作，不重建评测框架：

1. **同轮初判卡**：把本轮冻结分类器 ``p2_hard_evidence.classify_case_evidence`` 返回的
   ``CaseEvidenceResult`` 适配成 ``p2_evidence_rescore.OldCardCase``。四轴只取
   ``state/reason``，``quality_status / evidence_complete / missing_codes / stratum`` 全部取
   本轮结果，不接受任何历史卡或调用方自报值。
2. **来源证明**：``card_origin_record`` 为每个身份字段、每张卡逐项记录“值 + 原始来源对象 +
   所属轮次 + sha256”。``assert_same_round`` 只认 ``round == "current"`` 的来源；run_id /
   plan_id / plan_sha256 / evidence_tree / case 集合任一不符即抛固定错误码。
   **哈希相等只证明字节未变，不能代替跨轮来源正确**，因此来源对象与轮次是独立字段。
3. **硬失败与聚合一致性**：``derive_hard_failed`` 从经校验的逐题四轴 violation 导出硬失败
   集合，并与 ``aggregate.hard_failures``、``aggregate.case_count``、逐题 flag、每轴四态计数
   双向核对；``check_consistency`` 追加 case 覆盖、逐题质量总和、unknown 不被隐去等检查。
   缺字段/不一致一律抛 ``SameRoundError``，绝不默认空集合，也绝不在失败后出具成功结论。

边界：
- 只读导入冻结模块（``p2_hard_evidence`` / ``p2_evidence_rescore``），不 monkeypatch、不写回；
- 不改任何冻结 reason 词表，不把 unknown 变 N/A/pass；
- 本模块不做文件、环境变量、网络访问；调用方负责把私有输入留在受控进程内。
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from mktkb.evaluation import p2_evidence_rescore as rescore
from mktkb.evaluation.p2_hard_evidence import CaseEvidenceResult

__all__ = [
    "AXES",
    "AXIS_STATES",
    "QUALITY_STATUSES",
    "SameRoundError",
    "assert_same_round",
    "build_current_card",
    "build_quality_payload",
    "card_origin_record",
    "card_payload",
    "card_sha256",
    "check_consistency",
    "derive_hard_failed",
]
AXES: tuple[str, ...] = ("safety", "cross_user", "cross_entity", "stale_source")
AXIS_STATES: tuple[str, ...] = ("passed", "not_applicable", "unknown", "violation")
QUALITY_STATUSES: tuple[str, ...] = ("pass", "fail", "error", "not_executed")

#: 卡来源证明必须覆盖的身份字段（顺序稳定，便于逐字段审阅）。
ORIGIN_IDENTITY_FIELDS: tuple[str, ...] = (
    "run_id",
    "plan_id",
    "plan_sha256",
    "evidence_tree_sha256",
    "business_date",
    "scenario_id",
    "code_version",
    "analysis_version",
)
#: 其中必须与 expected 逐值相等的四个（其余只要求“有当前轮来源证明”）。
ORIGIN_MATCHED_FIELDS: tuple[str, ...] = (
    "run_id",
    "plan_id",
    "plan_sha256",
    "evidence_tree_sha256",
)
ORIGIN_ROUNDS: tuple[str, ...] = ("current", "historical")
#: 四类绑定不符的固定错误码（字段名不直接拼进 code，避免码表漂移）。
ORIGIN_MISMATCH_CODES: dict[str, str] = {
    "run_id": "run_id_mismatch",
    "plan_id": "plan_id_mismatch",
    "plan_sha256": "plan_sha256_mismatch",
    "evidence_tree_sha256": "evidence_tree_mismatch",
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SameRoundError(Exception):
    """固定码失败：``code`` 可直接进报告，``detail`` 只放字段名/固定枚举。"""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}" if self.detail else self.code)


def _require(condition: Any, code: str, detail: str = "") -> None:
    if not condition:
        raise SameRoundError(code, detail)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def card_payload(card: rescore.OldCardCase) -> dict[str, Any]:
    """卡的可复算投影（只含四轴 state/reason 与质量事实，不含私有文本）。"""
    _require(isinstance(card, rescore.OldCardCase), "classifier_result_invalid", "card")
    return {
        "case_id": str(card.case_id),
        "stratum": str(card.stratum),
        "quality_status": str(card.quality_status),
        "axes": {
            name: {
                "state": str(card.axes[name]["state"]),
                "reason": str(card.axes[name]["reason"]),
            }
            for name in AXES
        },
        "missing_codes": list(card.missing_codes),
        "evidence_complete": bool(card.evidence_complete),
    }


def card_sha256(card: rescore.OldCardCase) -> str:
    """卡投影的规范 JSON 摘要；与 ``RescoreIdentity.old_card_sha256`` 同一算法口径。"""
    return _sha256_bytes(rescore.canonical_json_bytes(card_payload(card)))


def build_current_card(result: CaseEvidenceResult) -> rescore.OldCardCase:
    """只用**本轮**分类器结果构造初判卡；任何缺轴/坏状态/词表不兼容都 fail closed。

    显式不做的事：不读历史卡、不按 case_id 回填旧值、不把 unknown 改写成 pass/N/A、
    不补造 ``missing_codes``。若本轮 ``safety`` reason 不在冻结重评分词表内，
    ``OldCardCase`` 会以 ``rescore_vocabulary_incompatible`` 终止，由调用方上报而不是静默映射。
    """
    _require(isinstance(result, CaseEvidenceResult), "classifier_result_invalid", "result")
    _require(_nonempty_str(result.case_id), "classifier_result_invalid", "case_id")
    _require(result.quality_status in QUALITY_STATUSES, "classifier_result_invalid", "quality_status")
    _require(isinstance(result.axes, Mapping), "classifier_result_invalid", "axes")
    _require(isinstance(result.missing_codes, (list, tuple)), "classifier_result_invalid", "missing_codes")
    _require(all(_nonempty_str(code) for code in result.missing_codes), "classifier_result_invalid", "missing_codes")
    _require(isinstance(result.evidence_complete, bool), "classifier_result_invalid", "evidence_complete")
    axes: dict[str, dict[str, str]] = {}
    for name in AXES:
        verdict = result.axes.get(name)
        _require(verdict is not None, "classifier_result_missing_axis", name)
        state = getattr(verdict, "state", None)
        reason = getattr(verdict, "reason", None)
        _require(state in AXIS_STATES, "classifier_result_invalid", f"{name}.state")
        _require(_nonempty_str(reason), "classifier_result_invalid", f"{name}.reason")
        axes[name] = {"state": str(state), "reason": str(reason)}
    try:
        return rescore.OldCardCase(
            case_id=str(result.case_id),
            stratum=str(result.stratum),
            quality_status=str(result.quality_status),
            axes=axes,
            missing_codes=tuple(str(code) for code in result.missing_codes),
            evidence_complete=bool(result.evidence_complete),
        )
    except rescore.RescoreError as exc:  # 冻结词表不兼容：停止，不映射、不降级
        raise SameRoundError(
            "rescore_vocabulary_incompatible", str(getattr(exc, "code", "") or type(exc).__name__)
        ) from None


def _origin_field(value: Any, source: Mapping[str, Any]) -> dict[str, Any]:
    """一个身份字段的“值 + 原始来源对象 + 轮次”；来源不合法直接拒绝。"""
    _require(_nonempty_str(value), "same_round_origin_missing", "value")
    _require(isinstance(source, Mapping), "same_round_origin_missing", "source")
    obj = source.get("object")
    round_name = source.get("round")
    _require(_nonempty_str(obj), "same_round_origin_missing", "source.object")
    _require(round_name in ORIGIN_ROUNDS, "same_round_origin_missing", "source.round")
    field = source.get("field")
    _require(field is None or _nonempty_str(field), "same_round_origin_missing", "source.field")
    return {
        "value": str(value),
        "source": {"object": str(obj), "field": None if field is None else str(field), "round": str(round_name)},
    }


def card_origin_record(
    *,
    identity: Mapping[str, Any],
    identity_sources: Mapping[str, Mapping[str, Any]],
    cards: Sequence[rescore.OldCardCase],
    classifier_sha256: str,
    classifier_source: Mapping[str, Any],
    card_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """记录一个 run 的本轮初判卡来源证明（身份字段 + 逐卡摘要 + 分类器摘要）。

    ``card_source`` 默认 ``{"object": "classify_case_evidence", "round": "current"}``；
    历史卡冒充本轮时必须显式传入 ``round="historical"`` 的来源，后面的
    ``assert_same_round`` 会以 ``same_round_origin_not_current`` 拒绝。
    """
    _require(isinstance(identity, Mapping), "same_round_origin_missing", "identity")
    _require(isinstance(identity_sources, Mapping), "same_round_origin_missing", "identity_sources")
    _require(isinstance(cards, (list, tuple)) and bool(cards), "same_round_origin_missing", "cards")
    _require(isinstance(card_source, Mapping) or card_source is None, "same_round_origin_missing", "card_source")
    source = dict(card_source or {"object": "classify_case_evidence", "round": "current"})
    _require(_nonempty_str(source.get("object")), "same_round_origin_missing", "card_source.object")
    _require(source.get("round") in ORIGIN_ROUNDS, "same_round_origin_missing", "card_source.round")
    _require(_is_sha256(classifier_sha256), "same_round_origin_missing", "classifier_sha256")
    _require(isinstance(classifier_source, Mapping), "same_round_origin_missing", "classifier_source")
    _require(_nonempty_str(classifier_source.get("object")), "same_round_origin_missing", "classifier_source.object")
    _require(classifier_source.get("round") in ORIGIN_ROUNDS, "same_round_origin_missing", "classifier_source.round")

    fields: dict[str, Any] = {}
    for name in ORIGIN_IDENTITY_FIELDS:
        _require(name in identity, "same_round_origin_missing", f"identity.{name}")
        _require(name in identity_sources, "same_round_origin_missing", f"identity_sources.{name}")
        fields[name] = _origin_field(identity[name], identity_sources[name])
        if name in ("plan_sha256", "evidence_tree_sha256"):
            _require(_is_sha256(fields[name]["value"]), "same_round_origin_missing", name)

    case_rows = []
    for card in cards:
        _require(isinstance(card, rescore.OldCardCase), "same_round_origin_missing", "card")
        case_rows.append(
            {
                "case_id": str(card.case_id),
                "sha256": card_sha256(card),
                "source": {
                    "object": str(source["object"]),
                    "round": str(source["round"]),
                    "classifier_sha256": str(classifier_sha256),
                },
            }
        )
    return {
        "schema_version": "r0-same-round-card-origin/v1",
        "fields": fields,
        "classifier": {
            "sha256": str(classifier_sha256),
            "source": {
                "object": str(classifier_source["object"]),
                "round": str(classifier_source["round"]),
            },
        },
        "cards": case_rows,
    }


def assert_same_round(binding: Mapping[str, Any]) -> None:
    """校验“本轮初判卡确实来自本轮”；不相等即抛固定码，不吞异常。

    ``binding = {"expected": {...}, "origin": card_origin_record(...)}``。
    五类拒绝：run_id / plan_id / plan_sha256 / evidence_tree / 来源证明缺失；
    另含 case 集合不符（缺失、重复、多余）与历史来源冒充本轮。
    """
    _require(isinstance(binding, Mapping), "same_round_binding_invalid", "binding")
    expected = binding.get("expected")
    origin = binding.get("origin")
    _require(isinstance(expected, Mapping), "same_round_binding_invalid", "expected")
    _require(isinstance(origin, Mapping), "same_round_origin_missing", "origin")
    fields = origin.get("fields")
    _require(isinstance(fields, Mapping), "same_round_origin_missing", "origin.fields")

    for name in ORIGIN_MATCHED_FIELDS:
        wanted = expected.get(name)
        _require(_nonempty_str(wanted), "same_round_binding_invalid", f"expected.{name}")
        node = fields.get(name)
        _require(isinstance(node, Mapping), "same_round_origin_missing", name)
        _require("value" in node and isinstance(node.get("source"), Mapping), "same_round_origin_missing", name)
        source = node["source"]
        _require(_nonempty_str(source.get("object")), "same_round_origin_missing", f"{name}.source.object")
        _require(
            source.get("round") == "current",
            "same_round_origin_not_current",
            f"{name}:{source.get('round')}",
        )
        _require(
            str(node.get("value")) == str(wanted),
            ORIGIN_MISMATCH_CODES[name],
            f"expected={wanted} origin={node.get('value')}",
        )

    # 其余身份字段只要求“有当前轮来源证明”，不参与四类绑定比对。
    for name in ORIGIN_IDENTITY_FIELDS:
        node = fields.get(name)
        _require(isinstance(node, Mapping) and isinstance(node.get("source"), Mapping),
                 "same_round_origin_missing", name)
        _require(_nonempty_str(node["source"].get("object")), "same_round_origin_missing", f"{name}.source")
        _require(
            node["source"].get("round") == "current",
            "same_round_origin_not_current",
            f"{name}:{node['source'].get('round')}",
        )

    classifier = origin.get("classifier")
    _require(isinstance(classifier, Mapping), "same_round_origin_missing", "origin.classifier")
    _require(_is_sha256(classifier.get("sha256")), "same_round_origin_missing", "origin.classifier.sha256")
    classifier_source = classifier.get("source")
    _require(isinstance(classifier_source, Mapping), "same_round_origin_missing", "classifier.source")
    _require(
        classifier_source.get("round") == "current",
        "same_round_origin_not_current",
        f"classifier:{classifier_source.get('round')}",
    )
    wanted_classifier = expected.get("classifier_sha256")
    if wanted_classifier is not None:
        _require(_is_sha256(wanted_classifier), "same_round_binding_invalid", "expected.classifier_sha256")
        _require(
            str(classifier.get("sha256")) == str(wanted_classifier),
            "classifier_mismatch",
            "",
        )

    wanted_ids = expected.get("case_ids")
    _require(
        isinstance(wanted_ids, (list, tuple)) and bool(wanted_ids)
        and all(_nonempty_str(item) for item in wanted_ids),
        "same_round_binding_invalid",
        "expected.case_ids",
    )
    _require(len(set(map(str, wanted_ids))) == len(wanted_ids), "same_round_binding_invalid", "case_ids_duplicate")

    cards = origin.get("cards")
    _require(isinstance(cards, (list, tuple)) and bool(cards), "same_round_origin_missing", "origin.cards")
    got_ids: list[str] = []
    card_shas: dict[str, str] = {}
    for row in cards:
        _require(isinstance(row, Mapping), "same_round_origin_missing", "card")
        case_id = row.get("case_id")
        _require(_nonempty_str(case_id), "same_round_origin_missing", "card.case_id")
        _require(_is_sha256(row.get("sha256")), "same_round_origin_missing", f"{case_id}.sha256")
        source = row.get("source")
        _require(isinstance(source, Mapping), "same_round_origin_missing", f"{case_id}.source")
        _require(_nonempty_str(source.get("object")), "same_round_origin_missing", f"{case_id}.source.object")
        _require(
            source.get("round") == "current",
            "same_round_origin_not_current",
            f"{case_id}:{source.get('round')}",
        )
        _require(
            _is_sha256(source.get("classifier_sha256")),
            "same_round_origin_missing",
            f"{case_id}.source.classifier_sha256",
        )
        got_ids.append(str(case_id))
        card_shas[str(case_id)] = str(row["sha256"])
    _require(len(got_ids) == len(set(got_ids)), "case_set_mismatch", "duplicate")
    _require(set(got_ids) == set(map(str, wanted_ids)), "case_set_mismatch", "set")

    wanted_shas = expected.get("card_sha256")
    if wanted_shas is not None:
        _require(isinstance(wanted_shas, Mapping), "same_round_binding_invalid", "expected.card_sha256")
        _require(set(map(str, wanted_shas)) == set(got_ids), "case_set_mismatch", "card_sha256")
        for case_id, want in wanted_shas.items():
            _require(_is_sha256(want), "same_round_binding_invalid", f"card_sha256.{case_id}")
            _require(card_shas[str(case_id)] == str(want), "card_sha256_mismatch", str(case_id))


def _case_rows(cases: Any, axes_key: str) -> list[Mapping[str, Any]]:
    _require(isinstance(cases, (list, tuple)) and bool(cases), "consistency_missing_field", "cases")
    rows: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for case in cases:
        _require(isinstance(case, Mapping), "consistency_missing_field", "cases[]")
        case_id = case.get("case_id")
        _require(_nonempty_str(case_id), "consistency_missing_field", "case_id")
        _require(case_id not in seen, "consistency_duplicate_case", str(case_id))
        seen.add(str(case_id))
        axes = case.get(axes_key)
        _require(isinstance(axes, Mapping), "consistency_missing_field", f"{case_id}.{axes_key}")
        for name in AXES:
            axis = axes.get(name)
            _require(isinstance(axis, Mapping), "consistency_missing_field", f"{case_id}.{axes_key}.{name}")
            state = axis.get("state")
            _require(state in AXIS_STATES, "consistency_invalid_state", f"{case_id}.{name}:{state}")
            _require(_nonempty_str(axis.get("reason")), "consistency_missing_field", f"{case_id}.{name}.reason")
        rows.append(case)
    return rows


def _derive_axis_sets(
    rows: Sequence[Mapping[str, Any]], axes_key: str
) -> tuple[dict[str, set[str]], set[str], set[str]]:
    per_axis: dict[str, set[str]] = {name: set() for name in AXES}
    for case in rows:
        case_id = str(case["case_id"])
        for name in AXES:
            if str(case[axes_key][name]["state"]) == "violation":
                per_axis[name].add(case_id)
    hard = set().union(*per_axis.values())
    unknown = {
        str(case["case_id"])
        for case in rows
        if any(str(case[axes_key][name]["state"]) == "unknown" for name in AXES)
    }
    return per_axis, hard, unknown


def _validate_axis_counts(
    counts: Any,
    rows: Sequence[Mapping[str, Any]],
    axes_key: str,
    per_axis: Mapping[str, set[str]],
) -> None:
    _require(isinstance(counts, Mapping), "consistency_missing_field", "new_axes")
    _require(set(counts) >= set(AXES), "consistency_missing_field", "new_axes")
    total = len(rows)
    for name in AXES:
        table = counts[name]
        _require(isinstance(table, Mapping), "consistency_missing_field", f"new_axes.{name}")
        for key in ("planned", "passed", "not_applicable", "unknown", "violations"):
            _require(type(table.get(key)) is int and table[key] >= 0, "consistency_missing_field", f"new_axes.{name}.{key}")
        _require(table["planned"] == total, "axis_planned_mismatch", f"{name}:{table['planned']}!={total}")
        _require(
            table["passed"] + table["not_applicable"] + table["unknown"] + table["violations"] == total,
            "axis_counts_mismatch",
            name,
        )
        _require(table["violations"] == len(per_axis[name]), "axis_violations_mismatch", name)
        state_counts = Counter(str(case[axes_key][name]["state"]) for case in rows)
        _require(
            table["passed"] == state_counts.get("passed", 0)
            and table["not_applicable"] == state_counts.get("not_applicable", 0)
            and table["unknown"] == state_counts.get("unknown", 0),
            "axis_counts_mismatch",
            name,
        )


def derive_hard_failed(
    cases: Sequence[Mapping[str, Any]],
    aggregate: Mapping[str, Any],
    *,
    axes_key: str = "new_axes",
) -> set[str]:
    """从经校验的逐题四轴 violation 导出硬失败集合（题目并集）。

    同时双向核对：``aggregate.hard_failures``、``aggregate.case_count``、逐题 ``hard_failed``
    flag、每轴四态计数。缺字段/不一致/重复 case 一律抛固定码；合法空集合只有在上面的
    逐题证据完整且计数自洽时才返回 ``set()``。
    """
    rows = _case_rows(cases, axes_key)
    _require(isinstance(aggregate, Mapping), "consistency_missing_field", "aggregate")
    for key in ("case_count", "hard_failures", "new_axes"):
        _require(key in aggregate, "consistency_missing_field", f"aggregate.{key}")
    per_axis, hard, _unknown = _derive_axis_sets(rows, axes_key)

    declared = aggregate["hard_failures"]
    _require(isinstance(declared, (list, tuple)), "consistency_missing_field", "aggregate.hard_failures")
    _require(all(_nonempty_str(item) for item in declared), "consistency_invalid_case_id", "hard_failures")
    _require(len(set(map(str, declared))) == len(declared), "hard_failures_duplicate", "")
    _require(set(map(str, declared)) == hard, "hard_failures_mismatch", "aggregate")
    _require(
        type(aggregate["case_count"]) is int and aggregate["case_count"] == len(rows),
        "case_coverage_mismatch",
        f"aggregate={aggregate['case_count']} cases={len(rows)}",
    )
    for case in rows:
        if "hard_failed" in case:
            _require(type(case["hard_failed"]) is bool, "consistency_missing_field", "hard_failed")
            _require(
                case["hard_failed"] == (str(case["case_id"]) in hard),
                "hard_failed_flag_mismatch",
                str(case["case_id"]),
            )
    _validate_axis_counts(aggregate["new_axes"], rows, axes_key, per_axis)
    return hard


def check_consistency(
    payload: Mapping[str, Any],
    *,
    axes_key: str = "new_axes",
) -> None:
    """整份分析的一致性前置门；任一不成立即抛错，调用方不得再出具成功结论。

    覆盖：case_id 唯一且精确覆盖、逐题质量总和=run 质量、硬失败 flags=硬失败并集、
    每轴四态计数=题数、unknown 不被隐去。历史对照字段（``historical_*``）不参与任何判断。
    """
    _require(isinstance(payload, Mapping), "consistency_missing_field", "payload")
    runs = payload.get("runs")
    _require(isinstance(runs, (list, tuple)) and bool(runs), "consistency_missing_field", "runs")
    aggregate = payload.get("aggregate")
    _require(isinstance(aggregate, Mapping), "consistency_missing_field", "aggregate")

    all_cases: list[Mapping[str, Any]] = []
    run_hard_union: set[str] = set()
    run_unknown_union: set[str] = set()
    declared_run_hard: set[str] | None = set()
    declared_run_unknown: set[str] | None = set()
    for run in runs:
        _require(isinstance(run, Mapping), "consistency_missing_field", "runs[]")
        run_index = run.get("run_index")
        _require(type(run_index) is int and run_index >= 0, "consistency_missing_field", "run_index")
        rows = _case_rows(run.get("cases"), axes_key)
        _require(
            type(run.get("case_count")) is int and run["case_count"] == len(rows),
            "case_coverage_mismatch",
            f"run{run_index}",
        )
        quality = run.get("quality")
        _require(isinstance(quality, Mapping), "consistency_missing_field", f"run{run_index}.quality")
        counted = Counter(str(case.get("quality_status")) for case in rows)
        _require(
            all(status in QUALITY_STATUSES for status in counted),
            "quality_status_invalid",
            f"run{run_index}",
        )
        for status in QUALITY_STATUSES:
            _require(
                type(quality.get(status, 0)) is int and int(quality.get(status, 0)) == counted.get(status, 0),
                "run_quality_mismatch",
                f"run{run_index}:{status}",
            )
        _require(
            sum(int(quality.get(status, 0)) for status in QUALITY_STATUSES) == len(rows),
            "run_quality_mismatch",
            f"run{run_index}:total",
        )
        if "case_ids" in run:
            declared_ids = run["case_ids"]
            _require(
                isinstance(declared_ids, (list, tuple))
                and [str(item) for item in declared_ids] == [str(case["case_id"]) for case in rows],
                "case_set_mismatch",
                f"run{run_index}.case_ids",
            )
        per_axis, hard, unknown = _derive_axis_sets(rows, axes_key)
        if "new_axes" in run:
            _validate_axis_counts(run["new_axes"], rows, axes_key, per_axis)
        if "hard_failures" in run:
            declared = run["hard_failures"]
            _require(
                isinstance(declared, (list, tuple))
                and len(set(map(str, declared))) == len(declared)
                and set(map(str, declared)) == hard,
                "hard_failures_mismatch",
                f"run{run_index}",
            )
            declared_run_hard |= {str(item) for item in declared}
        else:
            declared_run_hard = None
        if "unknown_cases" in run:
            declared_unknown = run["unknown_cases"]
            _require(
                isinstance(declared_unknown, (list, tuple))
                and len(set(map(str, declared_unknown))) == len(declared_unknown)
                and set(map(str, declared_unknown)) == unknown,
                "unknown_hidden",
                f"run{run_index}",
            )
            declared_run_unknown |= {str(item) for item in declared_unknown}
        else:
            declared_run_unknown = None
        run_hard_union |= hard
        run_unknown_union |= unknown
        all_cases.extend(rows)

    ids = [str(case["case_id"]) for case in all_cases]
    _require(len(ids) == len(set(ids)), "consistency_duplicate_case", "runs")
    _require(
        type(aggregate.get("case_count")) is int and aggregate["case_count"] == len(ids),
        "case_coverage_mismatch",
        f"aggregate={aggregate.get('case_count')} runs={len(ids)}",
    )

    hard = derive_hard_failed(all_cases, aggregate, axes_key=axes_key)
    _require(
        declared_run_hard is None or declared_run_hard == hard,
        "hard_failures_mismatch",
        "runs-vs-aggregate",
    )
    _require(hard == run_hard_union, "hard_failures_mismatch", "union")

    unknown = {
        str(case["case_id"])
        for case in all_cases
        if any(str(case[axes_key][name]["state"]) == "unknown" for name in AXES)
    }
    declared_unknown = aggregate.get("unknown_cases")
    _require(isinstance(declared_unknown, (list, tuple)), "consistency_missing_field", "aggregate.unknown_cases")
    _require(all(_nonempty_str(item) for item in declared_unknown), "consistency_invalid_case_id", "unknown_cases")
    _require(
        len(set(map(str, declared_unknown))) == len(declared_unknown),
        "unknown_hidden",
        "duplicate",
    )
    _require(set(map(str, declared_unknown)) == unknown, "unknown_hidden", "aggregate")
    _require(
        declared_run_unknown is None or declared_run_unknown == unknown,
        "unknown_hidden",
        "runs-vs-aggregate",
    )
    _require(unknown == run_unknown_union, "unknown_hidden", "union")


def build_quality_payload(
    axes_payload: Mapping[str, Any],
    case_plan_by_run: Mapping[int, Mapping[str, Any]],
    *,
    schema_version: str = "p2-h2v3-final-quality/v0.2",
) -> dict[str, Any]:
    """用**经校验的逐题四轴**生成 quality 聚合（修复 D3 的 ``new_hard_failures`` 错层级）。

    同时修复 D2：逐题 ``quality_status`` 与本轮重算明细交叉核对，不一致即停止；
    不再从历史卡读质量字段，也不把 ``hard_failed`` 默认成空集合。

    ``axes_payload`` 形状与 ``recompute_axes_fullverify_v2.py`` 输出一致：
    ``{"runs": [{"run_index", "scenario_id", "business_date", "case_count", "cases": [...]}],
    "aggregate": {...}}``；每个 case 需有 ``case_id / quality_status / new_axes``。
    """
    _require(isinstance(axes_payload, Mapping), "consistency_missing_field", "axes_payload")
    runs = axes_payload.get("runs")
    _require(isinstance(runs, (list, tuple)) and bool(runs), "consistency_missing_field", "runs")
    aggregate = axes_payload.get("aggregate")
    _require(isinstance(aggregate, Mapping), "consistency_missing_field", "aggregate")

    rows_by_run: dict[int, list[Mapping[str, Any]]] = {}
    all_rows: list[Mapping[str, Any]] = []
    for run in runs:
        _require(isinstance(run, Mapping), "consistency_missing_field", "runs[]")
        run_index = run.get("run_index")
        _require(type(run_index) is int and run_index >= 0, "consistency_missing_field", "run_index")
        rows = _case_rows(run.get("cases"), "new_axes")
        _require(
            type(run.get("case_count")) is int and run["case_count"] == len(rows),
            "case_coverage_mismatch",
            f"run{run_index}",
        )
        rows_by_run[run_index] = rows
        all_rows.extend(rows)

    ids = [str(case["case_id"]) for case in all_rows]
    _require(len(ids) == len(set(ids)), "consistency_duplicate_case", "runs")
    hard = derive_hard_failed(all_rows, aggregate, axes_key="new_axes")

    run_rows: list[dict[str, Any]] = []
    quality_total: Counter[str] = Counter()
    cases_out: list[dict[str, Any]] = []
    for run in runs:
        run_index = int(run["run_index"])
        plan = case_plan_by_run.get(run_index)
        _require(isinstance(plan, Mapping), "consistency_missing_field", f"case_plan[{run_index}]")
        plan_cases = plan.get("cases")
        _require(isinstance(plan_cases, (list, tuple)) and bool(plan_cases), "consistency_missing_field", f"case_plan[{run_index}].cases")
        axes_by_id = {str(case["case_id"]): case for case in rows_by_run[run_index]}
        _require(
            set(map(str, (item.get("case_id") for item in plan_cases))) == set(axes_by_id),
            "quality_case_set_mismatch",
            f"run{run_index}",
        )
        _require(
            len(set(map(str, (item.get("case_id") for item in plan_cases)))) == len(plan_cases),
            "quality_case_set_mismatch",
            f"run{run_index}:duplicate",
        )
        quality: Counter[str] = Counter()
        turns_total = 0
        for item in plan_cases:
            case_id = str(item.get("case_id"))
            status = str(item.get("quality_status"))
            _require(status in QUALITY_STATUSES, "quality_status_invalid", f"{case_id}:{status}")
            _require(
                str(axes_by_id[case_id].get("quality_status")) == status,
                "quality_axes_mismatch",
                case_id,
            )
            turns = item.get("turns")
            _require(isinstance(turns, (list, tuple)), "consistency_missing_field", f"{case_id}.turns")
            turns_total += len(turns)
            quality[status] += 1
            cases_out.append(
                {
                    "case_id": case_id,
                    "code": case_id.split("-")[-1],
                    "run_index": run_index,
                    "quality_status": status,
                    "hard_failed": case_id in hard,
                    "new_axes": axes_by_id[case_id]["new_axes"],
                }
            )
        quality_total.update(quality)
        run_rows.append(
            {
                "run_index": run_index,
                "scenario_id": run.get("scenario_id"),
                "business_date": run.get("business_date"),
                "case_count": len(plan_cases),
                "turn_count": turns_total,
                "pass": int(quality.get("pass", 0)),
                "fail": int(quality.get("fail", 0)),
                "error": int(quality.get("error", 0)),
                "not_executed": int(quality.get("not_executed", 0)),
                "hard_failures": sorted(case_id for case_id in hard if case_id in axes_by_id),
            }
        )

    return {
        "schema_version": schema_version,
        "hard_failed_source": "validated_per_case_axes.new_axes[*].state==violation",
        "runs": run_rows,
        "totals": {
            "cases": sum(row["case_count"] for row in run_rows),
            "turns": sum(row["turn_count"] for row in run_rows),
            "pass": int(quality_total.get("pass", 0)),
            "fail": int(quality_total.get("fail", 0)),
            "error": int(quality_total.get("error", 0)),
            "not_executed": int(quality_total.get("not_executed", 0)),
            "hard_failures": len(hard),
        },
        "cases": sorted(cases_out, key=lambda item: (item["code"], item["run_index"])),
    }
