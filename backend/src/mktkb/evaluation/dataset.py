"""评测数据集 Case 契约 v0.1（P0 设计 §7.1 / §7.3）。

一行一个 case 的 JSONL；本模块只做**数据契约**，不跑评测、不建索引：

- ``CaseSpec``：冻结的 Case 记录；字段顺序即 JSONL 字段顺序，保证字节稳定；
- ``validate_case``：逐条校验字段规则（gold 只允许稳定引用、拒绝 chunk_id/unit_id UUID、
  ``should_refuse`` 必须有原因、``turns`` 与 ``question`` 不能同时为空、``expected_kind`` 枚举合法）；
- ``load_cases`` / ``write_cases`` / ``cases_to_jsonl``：UTF-8、``ensure_ascii=False``、
  ``\\n`` 行尾、`pathlib`；读入时拒绝未知/缺失字段与重复 ``case_id``；
- ``dataset_version``：``suite:label_version:sha256[:12]``，摘要就是同一份规范 JSONL 的
  SHA-256（与落盘文件字节一致），因此版本可复算、连续构建字节一致。

稳定引用（设计 §7.2）只允许 ``doc_code`` + ``unit_key`` / ``locator``（及 ``record_code``）；
``locator`` 只接受设计定义的结构键（kind / sheet / row / heading / page / paragraph / table /
column）。OCR 题保留 ``locator.page``；``requires_ocr=true`` 由 gold 解析层显式跳过。

P1 T108 追加 holdout 数据集层（本文件末尾）：仓库只导出**无答案**的
``holdout-questions.jsonl``（13 键、sha256 冻结），答案在本地 ``labels.jsonl``
（11 键、sha256 冻结、永不入库），运行时按 ``HoldoutPolicy`` 合并并 fail closed。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..observability.contracts import CASE_SCHEMA_VERSION, OutcomeKind

__all__ = [
    "ALLOWED_KINDS",
    "CASE_FIELDS",
    "CASE_SCHEMA_VERSION",
    "CaseSpec",
    "CI_ENV_VARS",
    "DEFAULT_HOLDOUT_POLICY",
    "HOLDOUT_ANSWER_FIELDS",
    "HOLDOUT_CASE_COUNT",
    "HOLDOUT_LABEL_FIELDS",
    "HOLDOUT_LABEL_VERSION",
    "HOLDOUT_LABELS_SHA256",
    "HOLDOUT_QUESTION_FIELDS",
    "HOLDOUT_QUESTIONS_PATH",
    "HOLDOUT_QUESTIONS_SHA256",
    "HOLDOUT_STRATA",
    "HOLDOUT_SUITE",
    "HoldoutDataset",
    "HoldoutError",
    "HoldoutLabels",
    "HoldoutPolicy",
    "HoldoutQuestions",
    "LOCATOR_KEYS",
    "OPTIONAL_CASE_FIELDS",
    "cases_to_jsonl",
    "ci_environment",
    "dataset_version",
    "export_holdout_questions",
    "load_cases",
    "load_holdout_dataset",
    "load_holdout_labels",
    "load_holdout_questions",
    "validate_case",
    "write_cases",
]

SOURCE_KEYS = frozenset({"doc_code", "record_code", "unit_key", "locator"})
LOCATOR_KEYS = frozenset({"kind", "sheet", "row", "heading", "page", "paragraph", "table", "column"})
PAGINATION_KEYS = frozenset({"total", "returned", "has_more", "next_page", "min_total"})
#: P1 holdout 命题协议（设计 §4.1）用 ``refusal`` 标「应拒答」，``OutcomeKind`` 枚举里
#: 没有同名成员，但 ``scorers.REFUSAL_KINDS`` 已把它当拒答处理；这里作为 case 级兼容值
#: 允许写入 ``expected_kind``（向后兼容：既有 b0/badcase/regression 数据不含该值）。
COMPATIBLE_EXPECTED_KINDS = frozenset({"refusal"})
ALLOWED_KINDS = frozenset(kind.value for kind in OutcomeKind) | COMPATIBLE_EXPECTED_KINDS
ALLOWED_SPLITS = frozenset({"dev", "holdout", "test"})
FORBIDDEN_KEYS = frozenset({"chunk_id", "unit_id"})

CASE_FIELDS: tuple[str, ...] = (
    "case_id",
    "suite",
    "split",
    "stratum",
    "business_date",
    "question",
    "turns",
    "expected_kind",
    "expected_values",
    "expected_sources",
    "relevant_units",
    "reference_answer",
    "should_refuse",
    "refusal_reason",
    "forbidden_values",
    "forbidden_sources",
    "expected_pagination",
    "requires_ocr",
    "labeler",
    "label_version",
    "notes",
)

#: 可选扩展字段（P1 T107）：只在显式给出时写入规范 JSONL；缺省**不输出**，
#: 因此 b0/badcase 的规范字节与 ``dataset_version`` 保持不变。
#: ``regression`` 套件必须提供 ``source_err_id``（错误台账编号，如 ERR-20261104-03）。
OPTIONAL_CASE_FIELDS: tuple[str, ...] = ("source_err_id",)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CODE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_OPAQUE_HEX_RE = re.compile(r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{64})$")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} 必须是字符串")
    if not allow_empty and not value.strip():
        raise ValueError(f"{name} 不能为空")
    return value


def _require_sequence(value: object, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} 必须是数组")
    return value


def _reject_opaque(value: str, name: str) -> None:
    """拒绝把 chunk_id / unit_id 这类不透明 id 写进 gold。"""
    if _UUID_RE.fullmatch(value) or _OPAQUE_HEX_RE.fullmatch(value):
        raise ValueError(f"{name} 不允许写入 chunk_id/unit_id 等不透明 id: {value!r}")


def _reject_forbidden_keys(value: object, name: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in FORBIDDEN_KEYS:
                raise ValueError(f"{name} 不允许出现字段 {key!r}（禁止 chunk_id/unit_id）")
            _reject_forbidden_keys(item, name)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_forbidden_keys(item, name)


def _validate_source_ref(ref: object, name: str) -> dict[str, Any]:
    if not isinstance(ref, Mapping):
        raise ValueError(f"{name} 必须是对象")
    unknown = set(ref) - SOURCE_KEYS
    if unknown:
        raise ValueError(f"{name} 含不允许的字段: {sorted(str(key) for key in unknown)}")
    _reject_forbidden_keys(ref, name)
    if "doc_code" not in ref:
        raise ValueError(f"{name} 必须包含 doc_code")
    code = _require_text(ref["doc_code"], f"{name}.doc_code")
    if not _CODE_RE.fullmatch(code):
        raise ValueError(f"{name}.doc_code 含非法字符: {code!r}")
    for key in ("record_code", "unit_key"):
        if key in ref:
            text = _require_text(ref[key], f"{name}.{key}")
            _reject_opaque(text, f"{name}.{key}")
    if "locator" in ref:
        locator = ref["locator"]
        if not isinstance(locator, Mapping):
            raise ValueError(f"{name}.locator 必须是对象")
        unknown_locator = set(locator) - LOCATOR_KEYS
        if unknown_locator:
            raise ValueError(
                f"{name}.locator 只允许 {sorted(LOCATOR_KEYS)}，收到 {sorted(str(key) for key in unknown_locator)}"
            )
        for key, value in locator.items():
            if isinstance(value, bool):
                continue
            if _is_int(value):
                if value < 0:
                    raise ValueError(f"{name}.locator.{key} 不能为负数")
                continue
            text = _require_text(value, f"{name}.locator.{key}")
            _reject_opaque(text, f"{name}.locator.{key}")
    if not ({"unit_key", "locator", "record_code"} & set(ref)):
        # 整篇级 gold（例如 badcase N09 只给 doc_code）合法；这里只做显式记录，不报错。
        pass
    return {str(key): value for key, value in ref.items()}


def _validate_sources(value: object, name: str) -> None:
    for index, ref in enumerate(_require_sequence(value, name)):
        _validate_source_ref(ref, f"{name}[{index}]")


def _validate_texts(value: object, name: str) -> None:
    for index, item in enumerate(_require_sequence(value, name)):
        _require_text(item, f"{name}[{index}]")


def _validate_turns(value: object) -> None:
    for index, turn in enumerate(_require_sequence(value, "turns")):
        if not isinstance(turn, Mapping) or not turn:
            raise ValueError(f"turns[{index}] 必须是非空对象")
        _reject_forbidden_keys(turn, f"turns[{index}]")


def _validate_pagination(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError("expected_pagination 必须是对象或 null")
    unknown = set(value) - PAGINATION_KEYS
    if unknown:
        raise ValueError(f"expected_pagination 含不允许的字段: {sorted(str(key) for key in unknown)}")
    for key in ("total", "returned", "min_total"):
        if key in value and (not _is_int(value[key]) or value[key] < 0):
            raise ValueError(f"expected_pagination.{key} 必须是非负整数")
    if "has_more" in value and not isinstance(value["has_more"], bool):
        raise ValueError("expected_pagination.has_more 必须是布尔值")
    if "next_page" in value and value["next_page"] is not None:
        if not _is_int(value["next_page"]) or value["next_page"] < 0:
            raise ValueError("expected_pagination.next_page 必须是非负整数或 null")


@dataclass(frozen=True)
class CaseSpec:
    """一条评测用例；字段与设计 §7.1 一一对应。"""

    case_id: str
    suite: str
    split: str
    stratum: str
    business_date: str
    question: str
    turns: tuple[Mapping[str, Any], ...] = ()
    expected_kind: str = "answer"
    expected_values: tuple[str, ...] = ()
    expected_sources: tuple[Mapping[str, Any], ...] = ()
    relevant_units: tuple[Mapping[str, Any], ...] = ()
    reference_answer: str = ""
    should_refuse: bool = False
    refusal_reason: str | None = None
    forbidden_values: tuple[str, ...] = ()
    forbidden_sources: tuple[Mapping[str, Any], ...] = ()
    expected_pagination: Mapping[str, Any] | None = None
    requires_ocr: bool = False
    labeler: str = "lead"
    label_version: str = ""
    notes: str = ""
    #: 缺陷台账编号（可选；``regression`` 必填）。缺省时不出现在规范 JSONL 中。
    source_err_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """按 ``CASE_FIELDS`` 顺序返回可 JSON 序列化的普通对象。

        ``source_err_id`` 只在非 ``None`` 时追加到末尾，保证既有 b0/badcase
        的规范字节与 ``dataset_version`` 不变。
        """
        payload: dict[str, Any] = {
            "case_id": self.case_id,
            "suite": self.suite,
            "split": self.split,
            "stratum": self.stratum,
            "business_date": self.business_date,
            "question": self.question,
            "turns": [dict(turn) for turn in self.turns],
            "expected_kind": self.expected_kind,
            "expected_values": list(self.expected_values),
            "expected_sources": [dict(ref) for ref in self.expected_sources],
            "relevant_units": [dict(ref) for ref in self.relevant_units],
            "reference_answer": self.reference_answer,
            "should_refuse": self.should_refuse,
            "refusal_reason": self.refusal_reason,
            "forbidden_values": list(self.forbidden_values),
            "forbidden_sources": [dict(ref) for ref in self.forbidden_sources],
            "expected_pagination": None if self.expected_pagination is None else dict(self.expected_pagination),
            "requires_ocr": self.requires_ocr,
            "labeler": self.labeler,
            "label_version": self.label_version,
            "notes": self.notes,
        }
        if self.source_err_id is not None:
            payload["source_err_id"] = self.source_err_id
        unknown = set(payload) - set(CASE_FIELDS) - set(OPTIONAL_CASE_FIELDS)
        missing = set(CASE_FIELDS) - set(payload)
        if unknown or missing:  # pragma: no cover - 字段表与序列化漂移时立即失败
            raise AssertionError(
                f"CaseSpec.to_dict 与 CASE_FIELDS/OPTIONAL_CASE_FIELDS 不一致: "
                f"unknown={sorted(unknown)} missing={sorted(missing)}"
            )
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CaseSpec":
        if not isinstance(payload, Mapping):
            raise ValueError("case 行必须是 JSON 对象")
        unknown = set(payload) - set(CASE_FIELDS) - set(OPTIONAL_CASE_FIELDS)
        if unknown:
            raise ValueError(f"case 含未知字段: {sorted(str(key) for key in unknown)}")
        missing = [name for name in CASE_FIELDS if name not in payload]
        if missing:
            raise ValueError(f"case 缺少字段: {missing}")
        source_err_id = payload.get("source_err_id")
        if source_err_id is not None:
            source_err_id = _require_text(source_err_id, "source_err_id")

        def as_tuple_of_mappings(value: object, name: str) -> tuple[Mapping[str, Any], ...]:
            items = []
            for index, item in enumerate(_require_sequence(value, name)):
                if not isinstance(item, Mapping):
                    raise ValueError(f"{name}[{index}] 必须是对象")
                items.append({str(key): item[key] for key in item})
            return tuple(items)

        def as_texts(value: object, name: str) -> tuple[str, ...]:
            return tuple(
                _require_text(item, f"{name}[{index}]")
                for index, item in enumerate(_require_sequence(value, name))
            )

        pagination = payload["expected_pagination"]
        case = cls(
            case_id=_require_text(payload["case_id"], "case_id"),
            suite=_require_text(payload["suite"], "suite"),
            split=_require_text(payload["split"], "split"),
            stratum=_require_text(payload["stratum"], "stratum"),
            business_date=_require_text(payload["business_date"], "business_date"),
            question=_require_text(payload["question"], "question", allow_empty=True),
            turns=as_tuple_of_mappings(payload["turns"], "turns"),
            expected_kind=_require_text(payload["expected_kind"], "expected_kind"),
            expected_values=as_texts(payload["expected_values"], "expected_values"),
            expected_sources=as_tuple_of_mappings(payload["expected_sources"], "expected_sources"),
            relevant_units=as_tuple_of_mappings(payload["relevant_units"], "relevant_units"),
            reference_answer=payload["reference_answer"],
            should_refuse=payload["should_refuse"],
            refusal_reason=payload["refusal_reason"],
            forbidden_values=as_texts(payload["forbidden_values"], "forbidden_values"),
            forbidden_sources=as_tuple_of_mappings(payload["forbidden_sources"], "forbidden_sources"),
            expected_pagination=None if pagination is None else {str(key): pagination[key] for key in pagination},
            requires_ocr=payload["requires_ocr"],
            labeler=_require_text(payload["labeler"], "labeler"),
            label_version=_require_text(payload["label_version"], "label_version"),
            notes=_require_text(payload["notes"], "notes", allow_empty=True),
            source_err_id=source_err_id,
        )
        return case


def validate_case(case: CaseSpec) -> None:
    """逐条校验 Case 字段规则；任何违规都抛 ``ValueError``（fail closed）。"""
    if not isinstance(case, CaseSpec):
        raise ValueError("validate_case 只接受 CaseSpec")
    _require_text(case.case_id, "case_id")
    suite = _require_text(case.suite, "suite")
    if not _CODE_RE.fullmatch(suite):
        raise ValueError(f"suite 含非法字符: {suite!r}")
    if case.split not in ALLOWED_SPLITS:
        raise ValueError(f"split 必须是 {sorted(ALLOWED_SPLITS)} 之一，收到 {case.split!r}")
    _require_text(case.stratum, "stratum")
    if not _DATE_RE.fullmatch(_require_text(case.business_date, "business_date")):
        raise ValueError(f"business_date 必须是 YYYY-MM-DD，收到 {case.business_date!r}")
    _require_text(case.question, "question", allow_empty=True)
    if case.expected_kind not in ALLOWED_KINDS:
        raise ValueError(f"expected_kind 非法: {case.expected_kind!r}（允许 {sorted(ALLOWED_KINDS)}）")
    _validate_turns(case.turns)
    if not case.question.strip() and not case.turns:
        raise ValueError("question 与 turns 不能同时为空")
    _validate_texts(case.expected_values, "expected_values")
    _validate_sources(case.expected_sources, "expected_sources")
    _validate_sources(case.relevant_units, "relevant_units")
    if not isinstance(case.reference_answer, str):
        raise ValueError("reference_answer 必须是字符串")
    if not isinstance(case.should_refuse, bool):
        raise ValueError("should_refuse 必须是布尔值")
    if case.should_refuse:
        if case.refusal_reason is None:
            raise ValueError("should_refuse=true 必须提供 refusal_reason")
        _require_text(case.refusal_reason, "refusal_reason")
    elif case.refusal_reason is not None:
        _require_text(case.refusal_reason, "refusal_reason")
    _validate_texts(case.forbidden_values, "forbidden_values")
    _validate_sources(case.forbidden_sources, "forbidden_sources")
    _validate_pagination(case.expected_pagination)
    if not isinstance(case.requires_ocr, bool):
        raise ValueError("requires_ocr 必须是布尔值")
    _require_text(case.labeler, "labeler")
    _require_text(case.label_version, "label_version")
    if not isinstance(case.notes, str):
        raise ValueError("notes 必须是字符串")
    if case.suite == "regression":
        if case.source_err_id is None:
            raise ValueError("regression 套件必须提供 source_err_id（错误台账编号）")
        _require_text(case.source_err_id, "source_err_id")
    elif case.source_err_id is not None:
        _require_text(case.source_err_id, "source_err_id")


def load_cases(path: Path | str) -> list[CaseSpec]:
    """读取 JSONL 数据集；空行跳过，其余任何问题都抛 ``ValueError``。"""
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取数据集 {target}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"数据集 {target} 不是 UTF-8: {exc}") from exc
    cases: list[CaseSpec] = []
    seen: set[str] = set()
    for line_number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{target.name} 第 {line_number} 行 JSON 解析失败: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{target.name} 第 {line_number} 行必须是 JSON 对象")
        try:
            case = CaseSpec.from_dict(payload)
            validate_case(case)
        except ValueError as exc:
            raise ValueError(f"{target.name} 第 {line_number} 行: {exc}") from exc
        if case.case_id in seen:
            raise ValueError(f"{target.name} 第 {line_number} 行: case_id 重复 {case.case_id!r}")
        seen.add(case.case_id)
        cases.append(case)
    return cases


def cases_to_jsonl(cases: Sequence[CaseSpec]) -> str:
    """规范 JSONL：字段顺序固定、UTF-8、``ensure_ascii=False``、``\\n`` 行尾。"""
    return "".join(
        json.dumps(case.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n" for case in cases
    )


def write_cases(path: Path | str, cases: Sequence[CaseSpec]) -> str:
    """校验后按字节写入（不做行尾转换），返回文件 SHA-256。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        validate_case(case)
    payload = cases_to_jsonl(cases).encode("utf-8")
    target.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def dataset_version(cases: Sequence[CaseSpec], label_version: str) -> str:
    """``suite:label_version:sha256[:12]``；摘要即规范 JSONL 字节的 SHA-256 前 12 位。"""
    items = list(cases)
    if not items:
        raise ValueError("dataset_version 需要至少一个 case")
    for case in items:
        validate_case(case)
    suites = {case.suite for case in items}
    if len(suites) != 1:
        raise ValueError(f"同一数据集只能有一个 suite，收到 {sorted(suites)}")
    versions = {case.label_version for case in items}
    if versions != {label_version}:
        raise ValueError(f"label_version 不一致: 参数 {label_version!r}，数据 {sorted(versions)}")
    digest = hashlib.sha256(cases_to_jsonl(items).encode("utf-8")).hexdigest()[:12]
    suite = next(iter(suites))
    return f"{suite}:{label_version}:{digest}"


# --------------------------------------------------------------------------- #
# P1 T108：holdout 数据集（仓库只导出题目，答案在本地 labels，运行时合并）
# --------------------------------------------------------------------------- #
#
# 防污染口径（设计 §4）：
#
# - 仓库内只放**无答案**的 ``fixtures/evaluation/holdout-questions.jsonl``：逐字节等于本地
#   ``questions.jsonl``（sha256 固定，见 :data:`HOLDOUT_QUESTIONS_SHA256`），字段严格 13 个；
# - 答案只在本地 ``labels.jsonl``（sha256 固定，见 :data:`HOLDOUT_LABELS_SHA256`），
#   **永不入库**；运行时由 ``--holdout-labels`` / ``MKTKB_HOLDOUT_LABELS`` 指向；
# - 合并后仍走 :func:`validate_case`（稳定引用 / 拒答原因 / 枚举），任何不一致 fail closed；
# - ``questions`` 是题目/元数据权威，``labels`` 是答案与标注权威；两者重叠的
#   ``expected_kind`` / ``should_refuse`` 以 labels 为准，差异只计数（不中断运行），
#   计数写入 summary 的 holdout 块，便于验收方发现数据问题。

HOLDOUT_SUITE = "holdout"
HOLDOUT_CASE_COUNT = 30
HOLDOUT_STRATA: dict[str, int] = {
    "paraphrase": 10,
    "multi_turn": 5,
    "negative": 5,
    "stale_conflict": 5,
    "cross_doc_security": 5,
}
HOLDOUT_LABEL_VERSION = "holdout-2026-11-04"
HOLDOUT_QUESTIONS_SHA256 = "a8c8aa7f028ce14047173e3e57db36dda72d3a13b3578ad82ec8cd1b86cd6738"
HOLDOUT_LABELS_SHA256 = "8f713a2a22fe605cad53cec7c2679c0e5606421d2ac6baa34d17521650f4c1bf"
HOLDOUT_QUESTIONS_PATH = (
    Path(__file__).resolve().parents[4] / "fixtures" / "evaluation" / "holdout-questions.jsonl"
)

#: ``questions.jsonl`` 的 13 个键（设计 §4.1）：题干 + 元数据，**不含答案**。
HOLDOUT_QUESTION_FIELDS: tuple[str, ...] = (
    "case_id",
    "suite",
    "split",
    "stratum",
    "business_date",
    "question",
    "turns",
    "expected_kind",
    "should_refuse",
    "requires_ocr",
    "labeler",
    "label_version",
    "notes",
)
#: ``labels.jsonl`` 的 11 个键（设计 §4.2）：答案与标注，**不含题干**。
HOLDOUT_LABEL_FIELDS: tuple[str, ...] = (
    "case_id",
    "expected_kind",
    "expected_values",
    "expected_sources",
    "relevant_units",
    "reference_answer",
    "should_refuse",
    "refusal_reason",
    "forbidden_values",
    "forbidden_sources",
    "notes",
)
#: labels 可选携带 ``label_version``；出现时必须与 questions 的一致（缺失不算错误）。
HOLDOUT_LABEL_OPTIONAL_FIELDS: tuple[str, ...] = ("label_version",)
#: 题目导出里绝不能出现的答案字段（逐字节拷贝之外的额外防线）。
HOLDOUT_ANSWER_FIELDS = frozenset(
    {
        "reference_answer",
        "expected_values",
        "expected_sources",
        "relevant_units",
        "forbidden_values",
        "forbidden_sources",
    }
)
#: CI / 门禁环境探测变量（任一为真即视为受限环境）。
CI_ENV_VARS: tuple[str, ...] = ("CI", "GITHUB_ACTIONS", "MKTKB_CI")
_TRUTHY = frozenset({"1", "true", "yes", "on", "y"})


class HoldoutError(ValueError):
    """holdout 数据/策略违规；调用方必须 fail closed（CLI 非零退出）。"""


def ci_environment(environ: Mapping[str, str] | None = None) -> str | None:
    """返回第一个为真的 CI/门禁环境变量名；都没有则 ``None``。"""
    source = os.environ if environ is None else environ
    for name in CI_ENV_VARS:
        value = source.get(name)
        if isinstance(value, str) and value.strip().lower() in _TRUTHY:
            return name
    return None


@dataclass(frozen=True)
class HoldoutPolicy:
    """holdout 冻结契约；``None`` 表示该维度不钉死（仅供合成夹具使用）。

    默认值 = P1-PRE-1 交付的真实契约（30 题 / 10-5-5-5-5 / 两文件 sha / label_version）。
    """

    case_count: int = HOLDOUT_CASE_COUNT
    strata: Mapping[str, int] = field(default_factory=lambda: dict(HOLDOUT_STRATA))
    questions_sha256: str | None = HOLDOUT_QUESTIONS_SHA256
    labels_sha256: str | None = HOLDOUT_LABELS_SHA256
    label_version: str | None = HOLDOUT_LABEL_VERSION


DEFAULT_HOLDOUT_POLICY = HoldoutPolicy()


@dataclass(frozen=True)
class HoldoutQuestions:
    """``questions.jsonl`` 的校验结果（无答案，可安全打印聚合信息）。"""

    path: Path
    sha256: str
    rows: tuple[Mapping[str, Any], ...]
    label_version: str
    strata: Mapping[str, int]


@dataclass(frozen=True)
class HoldoutLabels:
    """``labels.jsonl`` 的校验结果（含答案，只允许留在内存/本地目录）。"""

    path: Path
    sha256: str
    rows: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class HoldoutDataset:
    """questions + labels 合并后的可执行数据集。"""

    questions: HoldoutQuestions
    labels: HoldoutLabels
    cases: tuple[CaseSpec, ...]
    metadata_mismatch_count: int


def _holdout_rows(path: Path | str, label: str) -> tuple[bytes, list[tuple[int, dict[str, Any]]]]:
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise HoldoutError(f"{label} 不可读 {target}: {exc}") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise HoldoutError(f"{label} 不能带 UTF-8 BOM: {target}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HoldoutError(f"{label} 不是 UTF-8: {target}: {exc}") from exc
    rows: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HoldoutError(f"{label} 第 {line_number} 行 JSON 解析失败: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise HoldoutError(f"{label} 第 {line_number} 行必须是 JSON 对象")
        rows.append((line_number, payload))
    return raw, rows


def _check_holdout_sha(
    raw: bytes, expected: str | None, label: str, label_version: str | None
) -> str:
    actual = hashlib.sha256(raw).hexdigest()
    if expected is not None and actual != expected:
        raise HoldoutError(
            f"{label} sha256 不符：期望 {expected}，实际 {actual}"
            f"（label_version={label_version}）"
        )
    return actual


def _reject_answer_fields(payload: Mapping[str, Any], label: str, line_number: int) -> None:
    leaked = sorted(HOLDOUT_ANSWER_FIELDS & set(payload))
    if leaked:
        raise HoldoutError(
            f"{label} 第 {line_number} 行出现答案字段 {leaked}：题目导出不允许携带答案"
        )


def _require_exact_keys(
    payload: Mapping[str, Any],
    allowed: Sequence[str],
    optional: Sequence[str],
    *,
    label: str,
    line_number: int,
) -> None:
    missing = [name for name in allowed if name not in payload]
    if missing:
        raise HoldoutError(f"{label} 第 {line_number} 行缺少字段: {missing}")
    unknown = sorted(set(payload) - set(allowed) - set(optional))
    if unknown:
        raise HoldoutError(f"{label} 第 {line_number} 行含不允许的字段: {unknown}")


def _require_turn_texts(value: object, *, label: str, line_number: int) -> tuple[str, ...]:
    items = _require_sequence(value, f"{label} 第 {line_number} 行的 turns")
    turns: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, str) or not item.strip():
            raise HoldoutError(f"{label} 第 {line_number} 行 turns[{index}] 必须是非空字符串")
        turns.append(item)
    return tuple(turns)


def _require_text_list(value: object, name: str, *, label: str, line_number: int) -> tuple[str, ...]:
    items = _require_sequence(value, name)
    texts: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise HoldoutError(f"{label} 第 {line_number} 行 {name}[{index}] 必须是字符串")
        texts.append(item)
    return tuple(texts)


def _require_ref_list(value: object, name: str, *, label: str, line_number: int) -> tuple[Mapping[str, Any], ...]:
    items = _require_sequence(value, name)
    refs: list[Mapping[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise HoldoutError(f"{label} 第 {line_number} 行 {name}[{index}] 必须是对象")
        refs.append({str(key): item[key] for key in item})
    return tuple(refs)


def _question_row(
    payload: Mapping[str, Any],
    line_number: int,
    policy: HoldoutPolicy,
    *,
    label: str,
) -> dict[str, Any]:
    _reject_answer_fields(payload, label, line_number)
    _require_exact_keys(
        payload, HOLDOUT_QUESTION_FIELDS, (), label=label, line_number=line_number
    )
    case_id = _require_text(payload["case_id"], f"{label} 第 {line_number} 行的 case_id")
    if payload["suite"] != HOLDOUT_SUITE:
        raise HoldoutError(
            f"{label} 第 {line_number} 行 suite 必须是 {HOLDOUT_SUITE!r}，收到 {payload['suite']!r}"
        )
    if payload["split"] != HOLDOUT_SUITE:
        raise HoldoutError(
            f"{label} 第 {line_number} 行 split 必须是 {HOLDOUT_SUITE!r}，收到 {payload['split']!r}"
        )
    _require_text(payload["stratum"], f"{label} 第 {line_number} 行的 stratum")
    if not _DATE_RE.fullmatch(_require_text(payload["business_date"], "business_date")):
        raise HoldoutError(
            f"{label} 第 {line_number} 行 business_date 必须是 YYYY-MM-DD，"
            f"收到 {payload['business_date']!r}"
        )
    if not isinstance(payload["question"], str):
        raise HoldoutError(f"{label} 第 {line_number} 行 question 必须是字符串")
    turns = _require_turn_texts(payload["turns"], label=label, line_number=line_number)
    if not payload["question"].strip() and not turns:
        raise HoldoutError(f"{label} 第 {line_number} 行 question 与 turns 不能同时为空")
    if payload["expected_kind"] not in ALLOWED_KINDS:
        raise HoldoutError(
            f"{label} 第 {line_number} 行 expected_kind 非法: {payload['expected_kind']!r}"
        )
    if not isinstance(payload["should_refuse"], bool):
        raise HoldoutError(f"{label} 第 {line_number} 行 should_refuse 必须是布尔值")
    if not isinstance(payload["requires_ocr"], bool):
        raise HoldoutError(f"{label} 第 {line_number} 行 requires_ocr 必须是布尔值")
    _require_text(payload["labeler"], f"{label} 第 {line_number} 行的 labeler")
    label_version = _require_text(
        payload["label_version"], f"{label} 第 {line_number} 行的 label_version"
    )
    if policy.label_version is not None and label_version != policy.label_version:
        raise HoldoutError(
            f"{label} 第 {line_number} 行 label_version 与数据集契约不一致："
            f"{label_version!r} != {policy.label_version!r}"
        )
    if not isinstance(payload["notes"], str):
        raise HoldoutError(f"{label} 第 {line_number} 行 notes 必须是字符串")
    return {
        "case_id": case_id,
        "stratum": str(payload["stratum"]),
        "business_date": str(payload["business_date"]),
        "question": payload["question"],
        "turns": turns,
        "expected_kind": str(payload["expected_kind"]),
        "should_refuse": payload["should_refuse"],
        "requires_ocr": payload["requires_ocr"],
        "labeler": str(payload["labeler"]),
        "label_version": label_version,
        "notes": payload["notes"],
    }


def load_holdout_questions(
    path: Path | str, *, policy: HoldoutPolicy = DEFAULT_HOLDOUT_POLICY
) -> HoldoutQuestions:
    """读取并校验仓库内的 holdout 题目导出（无答案）；任何违规 :class:`HoldoutError`。"""
    target = Path(path)
    raw, rows = _holdout_rows(target, "holdout questions")
    digest = _check_holdout_sha(raw, policy.questions_sha256, "holdout questions", policy.label_version)
    if len(rows) != policy.case_count:
        raise HoldoutError(
            f"holdout questions 行数 {len(rows)} != 契约 {policy.case_count}"
        )
    seen: set[str] = set()
    parsed: list[Mapping[str, Any]] = []
    versions: set[str] = set()
    strata: Counter[str] = Counter()
    for line_number, payload in rows:
        try:
            item = _question_row(payload, line_number, policy, label="holdout questions")
        except HoldoutError:
            raise
        except ValueError as exc:  # 行内基础类型校验（如空 label_version）统一成 HoldoutError
            raise HoldoutError(str(exc)) from exc
        if item["case_id"] in seen:
            raise HoldoutError(
                f"holdout questions 第 {line_number} 行 case_id 重复 {item['case_id']!r}"
            )
        seen.add(item["case_id"])
        versions.add(item["label_version"])
        strata[item["stratum"]] += 1
        parsed.append(item)
    if len(versions) != 1:
        raise HoldoutError(f"holdout questions 的 label_version 必须唯一，收到 {sorted(versions)}")
    expected_strata = {str(name): int(count) for name, count in policy.strata.items()}
    actual_strata = dict(sorted(strata.items()))
    if actual_strata != dict(sorted(expected_strata.items())):
        raise HoldoutError(
            f"holdout questions 分层不符：契约 {dict(sorted(expected_strata.items()))}，"
            f"实际 {actual_strata}"
        )
    return HoldoutQuestions(
        path=target,
        sha256=digest,
        rows=tuple(parsed),
        label_version=next(iter(versions)),
        strata=actual_strata,
    )


def _label_row(
    payload: Mapping[str, Any], line_number: int, policy: HoldoutPolicy
) -> dict[str, Any]:
    _require_exact_keys(
        payload,
        HOLDOUT_LABEL_FIELDS,
        HOLDOUT_LABEL_OPTIONAL_FIELDS,
        label="holdout labels",
        line_number=line_number,
    )
    if "label_version" in payload:
        version = _require_text(payload["label_version"], "labels.label_version")
        if policy.label_version is not None and version != policy.label_version:
            raise HoldoutError(
                f"holdout labels 第 {line_number} 行 label_version 与数据集契约不一致："
                f"{version!r} != {policy.label_version!r}"
            )
    case_id = _require_text(payload["case_id"], f"holdout labels 第 {line_number} 行的 case_id")
    if payload["expected_kind"] not in ALLOWED_KINDS:
        raise HoldoutError(
            f"holdout labels 第 {line_number} 行 expected_kind 非法: {payload['expected_kind']!r}"
        )
    if not isinstance(payload["reference_answer"], str):
        raise HoldoutError(f"holdout labels 第 {line_number} 行 reference_answer 必须是字符串")
    if not isinstance(payload["should_refuse"], bool):
        raise HoldoutError(f"holdout labels 第 {line_number} 行 should_refuse 必须是布尔值")
    refusal_reason = payload["refusal_reason"]
    if refusal_reason is not None and not isinstance(refusal_reason, str):
        raise HoldoutError(f"holdout labels 第 {line_number} 行 refusal_reason 必须是字符串或 null")
    if not isinstance(payload["notes"], str):
        raise HoldoutError(f"holdout labels 第 {line_number} 行 notes 必须是字符串")
    return {
        "case_id": case_id,
        "expected_kind": str(payload["expected_kind"]),
        "expected_values": _require_text_list(
            payload["expected_values"], "expected_values", label="holdout labels", line_number=line_number
        ),
        "expected_sources": _require_ref_list(
            payload["expected_sources"], "expected_sources", label="holdout labels", line_number=line_number
        ),
        "relevant_units": _require_ref_list(
            payload["relevant_units"], "relevant_units", label="holdout labels", line_number=line_number
        ),
        "reference_answer": payload["reference_answer"],
        "should_refuse": payload["should_refuse"],
        "refusal_reason": refusal_reason,
        "forbidden_values": _require_text_list(
            payload["forbidden_values"], "forbidden_values", label="holdout labels", line_number=line_number
        ),
        "forbidden_sources": _require_ref_list(
            payload["forbidden_sources"], "forbidden_sources", label="holdout labels", line_number=line_number
        ),
        "notes": payload["notes"],
    }


def load_holdout_labels(
    path: Path | str, *, policy: HoldoutPolicy = DEFAULT_HOLDOUT_POLICY
) -> HoldoutLabels:
    """读取并校验本地 ``labels.jsonl``（含答案，只留在本地/内存）。"""
    target = Path(path)
    raw, rows = _holdout_rows(target, "holdout labels")
    digest = _check_holdout_sha(raw, policy.labels_sha256, "holdout labels", policy.label_version)
    if len(rows) != policy.case_count:
        raise HoldoutError(f"holdout labels 行数 {len(rows)} != 契约 {policy.case_count}")
    parsed: dict[str, Mapping[str, Any]] = {}
    for line_number, payload in rows:
        try:
            item = _label_row(payload, line_number, policy)
        except HoldoutError:
            raise
        except ValueError as exc:  # 行内基础类型校验统一成 HoldoutError
            raise HoldoutError(str(exc)) from exc
        if item["case_id"] in parsed:
            raise HoldoutError(
                f"holdout labels 第 {line_number} 行 case_id 重复 {item['case_id']!r}"
            )
        parsed[item["case_id"]] = item
    return HoldoutLabels(path=target, sha256=digest, rows=parsed)


def export_holdout_questions(
    source: Path | str,
    target: Path | str,
    *,
    expected_sha256: str | None = HOLDOUT_QUESTIONS_SHA256,
) -> str:
    """把本地 ``questions.jsonl`` 逐字节导出为仓库 fixture（无答案）。

    只做**结构 + 摘要**校验（13 键白名单、禁止答案字段、JSON 对象、case_id 非空），
    30 题 / 10-5-5-5-5 / label_version 的冻结契约由 :func:`load_holdout_questions`
    在运行/validate 时执行。返回写出文件的 sha256。
    """
    source_path = Path(source)
    raw, rows = _holdout_rows(source_path, "holdout questions")
    digest = _check_holdout_sha(raw, expected_sha256, "holdout questions", None)
    seen: set[str] = set()
    for line_number, payload in rows:
        _reject_answer_fields(payload, "holdout questions", line_number)
        _require_exact_keys(
            payload, HOLDOUT_QUESTION_FIELDS, (), label="holdout questions", line_number=line_number
        )
        try:
            case_id = _require_text(
                payload["case_id"], f"holdout questions 第 {line_number} 行的 case_id"
            )
        except ValueError as exc:
            raise HoldoutError(str(exc)) from exc
        if case_id in seen:
            raise HoldoutError(f"holdout questions 第 {line_number} 行 case_id 重复 {case_id!r}")
        seen.add(case_id)
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(raw)
    return digest


def load_holdout_dataset(
    questions_path: Path | str,
    labels_path: Path | str,
    *,
    policy: HoldoutPolicy = DEFAULT_HOLDOUT_POLICY,
) -> HoldoutDataset:
    """合并 questions + labels，逐条 :func:`validate_case`；任何不一致 fail closed。"""
    questions = load_holdout_questions(questions_path, policy=policy)
    labels = load_holdout_labels(labels_path, policy=policy)
    question_ids = [str(row["case_id"]) for row in questions.rows]
    label_ids = set(labels.rows)
    if set(question_ids) != label_ids:
        missing = sorted(set(question_ids) - label_ids)
        extra = sorted(label_ids - set(question_ids))
        raise HoldoutError(
            "holdout questions 与 labels 的 case_id 集合不相等："
            f"questions={len(question_ids)} labels={len(label_ids)} "
            f"missing_in_labels={missing[:10]} extra_in_labels={extra[:10]}"
        )
    cases: list[CaseSpec] = []
    mismatches = 0
    for row in questions.rows:
        case_id = str(row["case_id"])
        label_row = labels.rows[case_id]
        if (
            row["expected_kind"] != label_row["expected_kind"]
            or row["should_refuse"] != label_row["should_refuse"]
        ):
            mismatches += 1
        case = CaseSpec(
            case_id=case_id,
            suite=HOLDOUT_SUITE,
            split=HOLDOUT_SUITE,
            stratum=str(row["stratum"]),
            business_date=str(row["business_date"]),
            question=str(row["question"]),
            # questions.turns 是字符串数组（设计 §4.1）；P0/T108 按单轮执行，
            # 这里只做显式规范化，多轮执行留给 T109。
            turns=tuple({"question": turn} for turn in row["turns"]),
            expected_kind=str(label_row["expected_kind"]),
            expected_values=tuple(label_row["expected_values"]),
            expected_sources=tuple(dict(ref) for ref in label_row["expected_sources"]),
            relevant_units=tuple(dict(ref) for ref in label_row["relevant_units"]),
            reference_answer=str(label_row["reference_answer"]),
            should_refuse=bool(label_row["should_refuse"]),
            refusal_reason=label_row["refusal_reason"],
            forbidden_values=tuple(label_row["forbidden_values"]),
            forbidden_sources=tuple(dict(ref) for ref in label_row["forbidden_sources"]),
            expected_pagination=None,
            requires_ocr=bool(row["requires_ocr"]),
            labeler=str(row["labeler"]),
            label_version=str(row["label_version"]),
            notes=str(row["notes"]),
        )
        try:
            validate_case(case)
        except ValueError as exc:
            raise HoldoutError(f"holdout case {case_id} 合并后不合规: {exc}") from exc
        cases.append(case)
    return HoldoutDataset(
        questions=questions,
        labels=labels,
        cases=tuple(cases),
        metadata_mismatch_count=mismatches,
    )


# 供测试/构建脚本核对字段表；dataclass 字段必须与 CASE_FIELDS + 可选字段完全一致。
if tuple(item.name for item in fields(CaseSpec)) != CASE_FIELDS + OPTIONAL_CASE_FIELDS:  # pragma: no cover
    raise AssertionError("CASE_FIELDS/OPTIONAL_CASE_FIELDS 与 CaseSpec 字段不一致")
