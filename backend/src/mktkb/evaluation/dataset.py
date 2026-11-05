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
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..observability.contracts import CASE_SCHEMA_VERSION, OutcomeKind

__all__ = [
    "ALLOWED_KINDS",
    "CASE_FIELDS",
    "CASE_SCHEMA_VERSION",
    "CaseSpec",
    "LOCATOR_KEYS",
    "OPTIONAL_CASE_FIELDS",
    "cases_to_jsonl",
    "dataset_version",
    "load_cases",
    "validate_case",
    "write_cases",
]

SOURCE_KEYS = frozenset({"doc_code", "record_code", "unit_key", "locator"})
LOCATOR_KEYS = frozenset({"kind", "sheet", "row", "heading", "page", "paragraph", "table", "column"})
PAGINATION_KEYS = frozenset({"total", "returned", "has_more", "next_page", "min_total"})
ALLOWED_KINDS = frozenset(kind.value for kind in OutcomeKind)
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


# 供测试/构建脚本核对字段表；dataclass 字段必须与 CASE_FIELDS + 可选字段完全一致。
if tuple(item.name for item in fields(CaseSpec)) != CASE_FIELDS + OPTIONAL_CASE_FIELDS:  # pragma: no cover
    raise AssertionError("CASE_FIELDS/OPTIONAL_CASE_FIELDS 与 CaseSpec 字段不一致")
