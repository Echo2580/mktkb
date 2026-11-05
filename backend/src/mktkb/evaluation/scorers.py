"""确定性评测打分器（P0 设计 §7.2 / §8.2；P0 计划 Task 4 Step 4）。

本模块只做**纯函数式打分**：输入是归一化后的 ``EvalOutcome``、``CaseSpec``、
``ResolvedGold`` 与可选 ``TraceRecord``，输出冻结的 ``CaseResult``。不调用任何
provider、不访问数据库、不读环境变量、不依赖时钟/随机数，同一输入重复打分结果
完全一致（``to_dict`` 的 JSON 可直接比较）。

数值口径（全模块统一）：

- 所有比率都是 **0–1**（不是 0–100）；
- 无法计算/不适用的指标返回 ``None``，且不进入聚合分母；
- 检索指标是 **macro average**：先逐 case 计算，再对适用 case 取均值；
- 无 gold（``ResolvedGold.relevant_unit_ids`` 为空）的 case 不进入
  ``Recall@10`` / ``MRR@10`` / ``nDCG@10`` / ``hard_filter_violation_rate`` /
  ``empty_recall_rate`` 的分母（T003c/P1 负样本口径；负样本泄漏由门禁
  ``security_leak`` 另外检查，不混入质量指标分母）；
- 拒答三指标来自同一张 2×2 混淆矩阵，但各自独立计算、互不替代：
  ``refusal_recall``（应拒答中真拒答）、``false_refusal_rate``（可答中误拒）、
  ``refusal_precision``（拒答中应拒答）。

拒答口径：``no_answer``（RAG）、``not_found``（legacy）与归一化兼容值
``refusal`` 视为"拒答"；``clarification`` / ``conflict`` / ``ambiguous`` 是交互或
冲突结局，不算拒答；``error`` / ``service_error`` 是执行失败（由 kind 正确率与门禁处理）。

unit 级口径：引用/检索项以 ``unit_ids`` 展开后按 unit 去重，同一 unit 的多个
chunk 只算一次。缺少 ``unit_ids`` 的引用项仍计入精确率分母（不可虚增），但无法
命中 gold unit（fail closed）；检索项的 unit 身份同理。

分页契约（见 :func:`score_case`）：

- ``total`` / ``returned`` 是非负整数，且 ``returned <= total``；
- ``has_more`` 是布尔值；``total > returned`` 时必须为 true，``total == returned``
  时必须为 false；
- ``has_more=true`` 时 ``next_page`` 必须是 ≥1 的整数；``has_more=false`` 时必须
  是 ``None``；
- ``expected_pagination`` 可给 ``total`` / ``returned`` / ``has_more`` /
  ``next_page`` 精确值，或 ``min_total`` 下界；契约违规优先于"与期望一致"。

``EvalOutcome.retrieved`` 是本包对计划接口的**最小扩展**：检索指标需要有序的
"本轮检索到的 unit 列表"，而计划列出的 ``citations`` / ``facts`` 只有引用集、
没有排名。该字段仍是归一化输入，不依赖任何 provider 返回类型。

``EvalOutcome.facts`` 只作为归一化数据保留；当前打分口径以回答文本（值命中）与
``citations``（来源命中/引用指标）为准，不重复计入 facts。
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence

from ..observability.contracts import TraceRecord
from .dataset import CaseSpec
from .gold import ResolvedGold, ResolvedSource

__all__ = [
    "CHECK_IDS",
    "CaseCheck",
    "CaseResult",
    "EvalCitation",
    "EvalFact",
    "EvalOutcome",
    "EvalRetrieved",
    "PAGINATION_CHECK_IDS",
    "REFUSAL_KINDS",
    "aggregate_metrics",
    "answer_metrics",
    "check_source",
    "check_value",
    "cost_metrics",
    "is_refusal",
    "latency_metrics",
    "match_source_ref",
    "normalize_text",
    "refusal_metrics",
    "retrieval_metrics",
    "score_case",
]

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_SKIPPED = "skipped"
STATUS_SKIPPED_OCR = "skipped_requires_ocr"

PAGINATION_CHECK_IDS: tuple[str, ...] = (
    "pagination_total",
    "pagination_returned",
    "pagination_has_more",
    "pagination_next_page",
)

#: 每个成功打分的 case 必然包含的 check（顺序固定；OCR 跳过时只有 ``scored``）。
CHECK_IDS: tuple[str, ...] = (
    "value_hit",
    "value_forbidden",
    "value_no_fabricated",
    "source_hit",
    "source_forbidden",
    "kind_correct",
    "refusal_expected",
    "refusal_unexpected",
    *PAGINATION_CHECK_IDS,
)

#: 视为"拒答"的结局；error/service_error 是失败，不是拒答。
#: ``refusal`` 是归一化兼容值（设计 ``OutcomeKind`` 无此成员），同样按拒答计。
REFUSAL_KINDS = frozenset({"no_answer", "not_found", "refusal"})

_INVISIBLE = frozenset("\u200b\u200c\u200d\u2060\ufeff")
_WHITESPACE_RE = re.compile(r"\s+")
_NUMBER_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?")
_NUMERIC_ONLY_RE = re.compile(r"(\d+(?:\.\d+)?)(%?)")


# --------------------------------------------------------------------------- #
# 归一化输入
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EvalCitation:
    """归一化后的引用（不依赖 ``rag.types.Citation`` 类型）。

    ``unit_ids`` 是本次引用实际指向的 unit（一个 chunk 可能覆盖多个 unit）；
    多个 chunk 指向同一 unit 时由引用指标按 unit 去重。
    """

    doc_code: str
    unit_key: str | None = None
    unit_ids: tuple[str, ...] = ()
    locator: Mapping[str, Any] = field(default_factory=dict)
    text: str = ""
    kind: str = ""


@dataclass(frozen=True)
class EvalFact:
    """归一化后的结构化事实；P0 scorer 不参与判分，保留给后续包使用。"""

    doc_code: str
    unit_id: str | None = None
    unit_key: str | None = None
    entity_key: str = ""
    field_role: str = ""
    field_label: str = ""
    value: str = ""


@dataclass(frozen=True)
class EvalRetrieved:
    """检索结果中的一项（通常是一个 chunk），顺序即排名（已按融合分数排序）。

    ``unit_ids`` 用于 unit 级去重；``hard_filter_violation`` 是上游归一化时给出的
    硬过滤违规原因（例如 ``forbidden_source`` / ``stale`` / ``cross_entity``），
    ``None`` 表示未违规。即使不填，命中了 case 的 ``forbidden_sources`` 也会被判违规。
    """

    doc_code: str
    unit_ids: tuple[str, ...] = ()
    unit_key: str | None = None
    locator: Mapping[str, Any] = field(default_factory=dict)
    chunk_id: str | None = None
    hard_filter_violation: str | None = None


@dataclass(frozen=True)
class EvalOutcome:
    """一次执行的归一化输出；由 runner 从 ``RagAnswer`` / legacy 返回归一化而来。"""

    kind: str
    text: str = ""
    citations: tuple[EvalCitation, ...] = ()
    facts: tuple[EvalFact, ...] = ()
    pagination: Mapping[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    path: str = "rag"
    retrieved: tuple[EvalRetrieved, ...] = ()


@dataclass(frozen=True)
class CaseCheck:
    """一个逐项检查；``check_id`` 稳定，``evidence`` 必须可 JSON 序列化。"""

    check_id: str
    status: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class CaseResult:
    """一条 case 的打分结果：逐项 check + 可聚合指标 + 运行成本字段。"""

    case_id: str
    status: str
    checks: tuple[CaseCheck, ...]
    metrics: Mapping[str, Any] = field(default_factory=dict)
    refused: bool | None = None
    should_refuse: bool = False
    trace_id: str | None = None
    path: str | None = None
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_cny: float | None = None

    def check(self, check_id: str) -> CaseCheck | None:
        """按 id 取 check；不存在返回 ``None``。"""
        for item in self.checks:
            if item.check_id == check_id:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "checks": [item.to_dict() for item in self.checks],
            "metrics": dict(self.metrics),
            "refused": self.refused,
            "should_refuse": self.should_refuse,
            "trace_id": self.trace_id,
            "path": self.path,
            "latency_ms": self.latency_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_cny": self.cost_cny,
        }


# --------------------------------------------------------------------------- #
# 文本 / 数值归一化
# --------------------------------------------------------------------------- #


def normalize_text(value: str) -> str:
    """NFKC（全角→半角）→ casefold（大小写）→ 去不可见字符 → 空白折叠为单空格。"""
    if not isinstance(value, str):
        raise TypeError("normalize_text 只接受字符串")
    text = unicodedata.normalize("NFKC", value).casefold()
    text = "".join(character for character in text if character not in _INVISIBLE)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _value_pattern(needle: str) -> re.Pattern[str]:
    """把期望值编译为"字符间允许空白"的模式；数字与数字之间不允许跨空白。"""
    parts: list[str] = []
    previous = ""
    for character in needle:
        if previous and not (previous.isdigit() and character.isdigit()):
            parts.append(r"\s*")
        parts.append(re.escape(character))
        previous = character
    return re.compile("".join(parts))


def _percent_after(text: str, index: int) -> bool:
    while index < len(text) and text[index] == " ":
        index += 1
    return index < len(text) and text[index] == "%"


def _number_continues_right(text: str, index: int) -> bool:
    return index + 1 < len(text) and text[index] == "." and text[index + 1].isdigit()


def _number_continues_left(text: str, index: int) -> bool:
    return index >= 2 and text[index - 1] == "." and text[index - 2].isdigit()


def _minus_before(text: str, index: int) -> bool:
    """同一数字前紧邻的负号（允许中间有空格）表示负数，不能当作正数命中。"""
    cursor = index - 1
    while cursor >= 0 and text[cursor] == " ":
        cursor -= 1
    return cursor >= 0 and text[cursor] == "-"


def check_value(text: str, expected: str) -> bool:
    """判断 ``expected`` 是否作为**完整数值/子串**出现在 ``text`` 中（归一化后）。

    - 全角/半角、大小写、多余空白不敏感；
    - 纯数值期望按数值 token 比较：``12`` 不命中 ``120`` / ``12.5``，但命中 ``012``；
    - 混合文本期望不允许数字被更大数字包住：``B区1号`` 不命中 ``B区12号``；
    - 期望值带 ``%`` 时要求文本中对应数字后（允许空格）紧跟 ``%``。
    """
    if not isinstance(text, str) or not isinstance(expected, str):
        raise TypeError("check_value 只接受字符串")
    haystack = normalize_text(text)
    needle = normalize_text(expected).replace(" ", "")
    if not needle:
        return False

    numeric = _NUMERIC_ONLY_RE.fullmatch(needle)
    if numeric:
        try:
            target = Decimal(numeric.group(1))
        except InvalidOperation:  # pragma: no cover - 正则可保证合法数字
            return False
        wants_percent = numeric.group(2) == "%"
        for match in _NUMBER_TOKEN_RE.finditer(haystack):
            if _minus_before(haystack, match.start()):
                continue
            if wants_percent and not _percent_after(haystack, match.end()):
                continue
            try:
                if Decimal(match.group(0)) == target:
                    return True
            except InvalidOperation:  # pragma: no cover
                continue
        return False

    pattern = _value_pattern(needle)
    for match in pattern.finditer(haystack):
        start, end = match.start(), match.end()
        if needle[0].isdigit() and start > 0 and haystack[start - 1].isdigit():
            continue
        if needle[0].isdigit() and _minus_before(haystack, start):
            continue
        if _number_continues_left(haystack, start):
            continue
        if needle[-1].isdigit() and end < len(haystack) and haystack[end].isdigit():
            continue
        if _number_continues_right(haystack, end):
            continue
        return True
    return False


def _number_key(token: str) -> str:
    """把数字 token 归一为稳定字符串（``01`` → ``1``，``1.50`` → ``1.5``）。"""
    try:
        number = Decimal(token)
        if number == number.to_integral_value():
            return str(int(number))
        return format(number.normalize(), "f")
    except (InvalidOperation, ValueError):  # pragma: no cover - 正则保证合法
        return token


def _number_keys(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    return [_number_key(match.group(0)) for match in _NUMBER_TOKEN_RE.finditer(normalize_text(text))]


def _gold_number_keys(case: CaseSpec) -> frozenset[str]:
    """允许出现在回答中的数字：期望值、参考答案、问题、业务日期。"""
    parts: list[str] = [case.business_date, case.question, case.reference_answer]
    parts.extend(case.expected_values)
    keys: set[str] = set()
    for part in parts:
        keys.update(_number_keys(part))
    return frozenset(keys)


# --------------------------------------------------------------------------- #
# 来源匹配
# --------------------------------------------------------------------------- #


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual is expected
    if actual is None or expected is None:
        return actual is expected
    return actual == expected or str(actual) == str(expected)


def _canonical_locator(locator: Mapping[str, Any]) -> str:
    return json.dumps(dict(locator), ensure_ascii=False, sort_keys=True, default=str)


def _locator_matches(
    expected: Mapping[str, Any], actual: Mapping[str, Any] | None
) -> bool:
    if not isinstance(actual, Mapping) or not actual:
        return False
    return all(_same(actual.get(key), value) for key, value in expected.items())


def match_source_ref(
    ref: Mapping[str, Any],
    *,
    doc_code: str,
    unit_ids: Sequence[str] = (),
    unit_key: str | None = None,
    locator: Mapping[str, Any] | None = None,
    resolved_source: ResolvedSource | None = None,
) -> bool:
    """把一条稳定引用（case 的 expected/forbidden source）与一个来源身份比对。

    ``doc_code`` 必须一致；然后按身份强度依次匹配：已解析 unit_id → ``unit_key``
    → ``locator`` 子集；只给 ``doc_code``（整篇级 gold）时同文档即命中。
    """
    if not isinstance(ref, Mapping):
        raise TypeError("来源引用必须是映射")
    ref_doc = ref.get("doc_code")
    if ref_doc is None or str(ref_doc) != str(doc_code):
        return False

    if resolved_source is not None and resolved_source.unit_ids:
        expected_ids = {str(item) for item in resolved_source.unit_ids}
        if any(str(item) in expected_ids for item in unit_ids):
            return True

    ref_key = ref.get("unit_key")
    ref_locator = ref.get("locator")
    if ref_key is not None:
        if unit_key is not None:
            return str(ref_key) == str(unit_key)
        if isinstance(ref_locator, Mapping) and ref_locator:
            return _locator_matches(ref_locator, locator)
        return False
    if isinstance(ref_locator, Mapping) and ref_locator:
        return _locator_matches(ref_locator, locator)
    return True


def _citation_parts(
    citation: EvalCitation | Mapping[str, Any],
) -> tuple[str, str | None, tuple[str, ...], Mapping[str, Any]]:
    """把 ``EvalCitation`` 或等价映射拆成 (doc_code, unit_key, unit_ids, locator)。"""
    if isinstance(citation, EvalCitation):
        return citation.doc_code, citation.unit_key, citation.unit_ids, citation.locator
    if isinstance(citation, Mapping):
        doc_code = citation.get("doc_code")
        if doc_code is None:
            raise ValueError("引用映射必须包含 doc_code")
        raw_ids = citation.get("unit_ids") or ()
        if isinstance(raw_ids, (str, bytes)):
            raw_ids = (raw_ids,)
        locator = citation.get("locator") or {}
        if not isinstance(locator, Mapping):
            raise TypeError("引用 locator 必须是映射")
        return (
            str(doc_code),
            citation.get("unit_key"),
            tuple(str(item) for item in raw_ids),
            locator,
        )
    raise TypeError("引用必须是 EvalCitation 或映射")


def check_source(
    ref: Mapping[str, Any],
    citation: EvalCitation | Mapping[str, Any],
    resolved_source: ResolvedSource | None = None,
) -> bool:
    """判断一条 case 引用是否命中一个归一化引用（``EvalCitation`` 或等价映射）。"""
    doc_code, unit_key, unit_ids, locator = _citation_parts(citation)
    return match_source_ref(
        ref,
        doc_code=doc_code,
        unit_ids=unit_ids,
        unit_key=unit_key,
        locator=locator,
        resolved_source=resolved_source,
    )


def _citation_identities(citation: EvalCitation) -> tuple[tuple[str, str], ...]:
    ids = tuple(("unit", str(item)) for item in citation.unit_ids if str(item))
    if ids:
        return ids
    if citation.unit_key:
        return (("key", f"{citation.doc_code}|{citation.unit_key}"),)
    if citation.locator:
        return (("locator", f"{citation.doc_code}|{_canonical_locator(citation.locator)}"),)
    return (("document", str(citation.doc_code)),)


def _retrieved_identities(item: EvalRetrieved) -> tuple[tuple[str, str], ...]:
    ids = tuple(("unit", str(unit)) for unit in item.unit_ids if str(unit))
    if ids:
        return ids
    if item.unit_key:
        return (("key", f"{item.doc_code}|{item.unit_key}"),)
    if item.locator:
        return (("locator", f"{item.doc_code}|{_canonical_locator(item.locator)}"),)
    if item.chunk_id:
        return (("chunk", f"{item.doc_code}|{item.chunk_id}"),)
    return (("document", str(item.doc_code)),)


# --------------------------------------------------------------------------- #
# 逐项 check
# --------------------------------------------------------------------------- #


def _pass(check_id: str, evidence: Mapping[str, Any] | None = None) -> CaseCheck:
    return CaseCheck(check_id=check_id, status=STATUS_PASS, evidence=dict(evidence or {}))


def _fail(check_id: str, evidence: Mapping[str, Any] | None = None) -> CaseCheck:
    return CaseCheck(check_id=check_id, status=STATUS_FAIL, evidence=dict(evidence or {}))


def _skipped(check_id: str, evidence: Mapping[str, Any] | None = None) -> CaseCheck:
    return CaseCheck(check_id=check_id, status=STATUS_SKIPPED, evidence=dict(evidence or {}))


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def _value_checks(case: CaseSpec, outcome: EvalOutcome) -> tuple[CaseCheck, ...]:
    text = outcome.text
    expected = tuple(case.expected_values)
    checks: list[CaseCheck] = []

    if case.should_refuse:
        checks.append(_skipped("value_hit", {"reason": "should_refuse"}))
    elif not expected:
        checks.append(_skipped("value_hit", {"reason": "no_expected_values"}))
    else:
        missing = [value for value in expected if not check_value(text, value)]
        if missing:
            checks.append(_fail("value_hit", {"expected": len(expected), "missing": missing}))
        else:
            checks.append(_pass("value_hit", {"expected": len(expected), "missing": []}))

    forbidden = tuple(case.forbidden_values)
    if not forbidden:
        checks.append(_skipped("value_forbidden", {"reason": "no_forbidden_values"}))
    else:
        leaked = [value for value in forbidden if check_value(text, value)]
        if leaked:
            checks.append(_fail("value_forbidden", {"leaked": leaked}))
        else:
            checks.append(_pass("value_forbidden", {"checked": len(forbidden)}))

    if case.should_refuse:
        checks.append(_skipped("value_no_fabricated", {"reason": "should_refuse"}))
    elif not expected:
        checks.append(_skipped("value_no_fabricated", {"reason": "no_expected_values"}))
    else:
        allowed = _gold_number_keys(case)
        extra = sorted({key for key in _number_keys(text) if key not in allowed})
        if extra:
            checks.append(
                _fail("value_no_fabricated", {"extra": extra, "checked": len(expected)})
            )
        else:
            checks.append(_pass("value_no_fabricated", {"checked": len(expected)}))
    return tuple(checks)


def _source_checks(
    case: CaseSpec, outcome: EvalOutcome, resolved: ResolvedGold
) -> tuple[CaseCheck, ...]:
    expected = tuple(case.expected_sources)
    paired = resolved.sources if len(resolved.sources) == len(expected) else ()
    checks: list[CaseCheck] = []

    if not expected:
        checks.append(_skipped("source_hit", {"reason": "no_expected_sources"}))
    elif case.should_refuse:
        checks.append(_skipped("source_hit", {"reason": "should_refuse"}))
    else:
        missing: list[int] = []
        for index, ref in enumerate(expected):
            resolved_source = paired[index] if paired else None
            if not any(
                check_source(ref, citation, resolved_source) for citation in outcome.citations
            ):
                missing.append(index)
        if missing:
            checks.append(
                _fail("source_hit", {"expected": len(expected), "missing_index": missing})
            )
        else:
            checks.append(_pass("source_hit", {"expected": len(expected), "matched": len(expected)}))

    forbidden = tuple(case.forbidden_sources)
    if not forbidden:
        checks.append(_skipped("source_forbidden", {"reason": "no_forbidden_sources"}))
    else:
        violations = [
            index
            for index, ref in enumerate(forbidden)
            if any(check_source(ref, citation) for citation in outcome.citations)
        ]
        if violations:
            checks.append(_fail("source_forbidden", {"violations_index": violations}))
        else:
            checks.append(_pass("source_forbidden", {"checked": len(forbidden)}))
    return tuple(checks)


def _kind_text(value: Any) -> str:
    """把 str / ``StrEnum`` / 其它结局值统一成纯 ``str``（不泄漏枚举实例）。"""
    return format(value, "")


def is_refusal(kind: Any) -> bool:
    """``no_answer`` / ``not_found`` / ``refusal`` 视为拒答；其它结局不算。"""
    return _kind_text(kind) in REFUSAL_KINDS


def _kind_checks(case: CaseSpec, outcome: EvalOutcome) -> tuple[tuple[CaseCheck, ...], bool]:
    expected_kind = _kind_text(case.expected_kind)
    actual_kind = _kind_text(outcome.kind)
    if actual_kind == expected_kind:
        kind_check = _pass("kind_correct", {"expected": expected_kind, "actual": actual_kind})
    else:
        kind_check = _fail("kind_correct", {"expected": expected_kind, "actual": actual_kind})

    refused = is_refusal(actual_kind)
    if case.should_refuse:
        refusal_expected = (
            _pass("refusal_expected", {"should_refuse": True, "refused": refused, "kind": actual_kind})
            if refused
            else _fail(
                "refusal_expected", {"should_refuse": True, "refused": refused, "kind": actual_kind}
            )
        )
        refusal_unexpected = _skipped(
            "refusal_unexpected", {"should_refuse": True, "refused": refused, "kind": actual_kind}
        )
    else:
        refusal_expected = _skipped(
            "refusal_expected", {"should_refuse": False, "refused": refused, "kind": actual_kind}
        )
        refusal_unexpected = (
            _fail(
                "refusal_unexpected", {"should_refuse": False, "refused": refused, "kind": actual_kind}
            )
            if refused
            else _pass(
                "refusal_unexpected", {"should_refuse": False, "refused": refused, "kind": actual_kind}
            )
        )
    return (kind_check, refusal_expected, refusal_unexpected), refused


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _pagination_checks(case: CaseSpec, outcome: EvalOutcome) -> tuple[CaseCheck, ...]:
    expected = dict(case.expected_pagination or {})
    actual = dict(outcome.pagination or {})
    if not expected and not actual:
        return tuple(
            _skipped(check_id, {"reason": "no_expected_pagination"})
            for check_id in PAGINATION_CHECK_IDS
        )

    total = actual.get("total")
    returned = actual.get("returned")
    has_more = actual.get("has_more")
    next_page = actual.get("next_page")
    return (
        _pagination_total(expected, actual, total, returned),
        _pagination_returned(expected, actual, total, returned),
        _pagination_has_more(expected, actual, has_more, total, returned),
        _pagination_next_page(expected, actual, has_more, next_page),
    )


def _pagination_total(
    expected: Mapping[str, Any], actual: Mapping[str, Any], total: Any, returned: Any
) -> CaseCheck:
    if "total" not in actual:
        return _fail("pagination_total", {"reason": "missing", "expected": _safe(expected.get("total"))})
    if not _is_non_negative_int(total):
        return _fail("pagination_total", {"reason": "type", "actual": _safe(total)})
    if _is_non_negative_int(returned) and returned > total:
        return _fail(
            "pagination_total", {"reason": "inconsistent", "total": total, "returned": returned}
        )
    if "min_total" in expected and total < expected["min_total"]:
        return _fail(
            "pagination_total",
            {"reason": "below_min_total", "actual": total, "min_total": _safe(expected["min_total"])},
        )
    if "total" in expected and total != expected["total"]:
        return _fail(
            "pagination_total",
            {"reason": "mismatch", "actual": total, "expected": _safe(expected["total"])},
        )
    return _pass(
        "pagination_total",
        {"actual": total, "expected": _safe(expected.get("total")), "min_total": _safe(expected.get("min_total"))},
    )


def _pagination_returned(
    expected: Mapping[str, Any], actual: Mapping[str, Any], total: Any, returned: Any
) -> CaseCheck:
    if "returned" not in actual:
        return _fail(
            "pagination_returned", {"reason": "missing", "expected": _safe(expected.get("returned"))}
        )
    if not _is_non_negative_int(returned):
        return _fail("pagination_returned", {"reason": "type", "actual": _safe(returned)})
    if _is_non_negative_int(total) and returned > total:
        return _fail(
            "pagination_returned", {"reason": "inconsistent", "total": total, "returned": returned}
        )
    if "returned" in expected and returned != expected["returned"]:
        return _fail(
            "pagination_returned",
            {"reason": "mismatch", "actual": returned, "expected": _safe(expected["returned"])},
        )
    return _pass(
        "pagination_returned", {"actual": returned, "expected": _safe(expected.get("returned"))}
    )


def _pagination_has_more(
    expected: Mapping[str, Any], actual: Mapping[str, Any], has_more: Any, total: Any, returned: Any
) -> CaseCheck:
    if "has_more" not in actual:
        return _fail("pagination_has_more", {"reason": "missing", "expected": _safe(expected.get("has_more"))})
    if not isinstance(has_more, bool):
        return _fail("pagination_has_more", {"reason": "type", "actual": _safe(has_more)})
    if _is_non_negative_int(total) and _is_non_negative_int(returned):
        if total > returned and not has_more:
            return _fail(
                "pagination_has_more",
                {"reason": "inconsistent", "total": total, "returned": returned, "has_more": has_more},
            )
        if total == returned and has_more:
            return _fail(
                "pagination_has_more",
                {"reason": "inconsistent", "total": total, "returned": returned, "has_more": has_more},
            )
    if "has_more" in expected and has_more is not expected["has_more"]:
        return _fail(
            "pagination_has_more",
            {"reason": "mismatch", "actual": has_more, "expected": _safe(expected["has_more"])},
        )
    return _pass("pagination_has_more", {"actual": has_more, "expected": _safe(expected.get("has_more"))})


def _pagination_next_page(
    expected: Mapping[str, Any], actual: Mapping[str, Any], has_more: Any, next_page: Any
) -> CaseCheck:
    if "next_page" not in actual:
        return _fail(
            "pagination_next_page", {"reason": "missing", "expected": _safe(expected.get("next_page"))}
        )
    if isinstance(has_more, bool):
        if has_more:
            if not (isinstance(next_page, int) and not isinstance(next_page, bool) and next_page >= 1):
                reason = "type" if next_page is not None and not isinstance(next_page, int) else "inconsistent"
                return _fail(
                    "pagination_next_page",
                    {"reason": reason, "has_more": True, "actual": _safe(next_page)},
                )
        elif next_page is not None:
            return _fail(
                "pagination_next_page",
                {"reason": "inconsistent", "has_more": False, "actual": _safe(next_page)},
            )
    else:
        if next_page is not None and not (
            isinstance(next_page, int) and not isinstance(next_page, bool) and next_page >= 1
        ):
            return _fail("pagination_next_page", {"reason": "type", "actual": _safe(next_page)})
    if "next_page" in expected and not _same(next_page, expected["next_page"]):
        return _fail(
            "pagination_next_page",
            {"reason": "mismatch", "actual": _safe(next_page), "expected": _safe(expected["next_page"])},
        )
    return _pass(
        "pagination_next_page", {"actual": _safe(next_page), "expected": _safe(expected.get("next_page"))}
    )


# --------------------------------------------------------------------------- #
# 指标
# --------------------------------------------------------------------------- #


def _binary_status(check: CaseCheck) -> float | None:
    if check.status == STATUS_PASS:
        return 1.0
    if check.status == STATUS_FAIL:
        return 0.0
    return None


def _citation_case_metrics(
    case: CaseSpec, outcome: EvalOutcome, resolved: ResolvedGold, refused: bool
) -> tuple[float | None, float | None]:
    relevant = {("unit", str(item)) for item in resolved.relevant_unit_ids}
    if not relevant or resolved.skipped or case.should_refuse or refused:
        return None, None

    cited: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for citation in outcome.citations:
        for identity in _citation_identities(citation):
            if identity not in seen:
                seen.add(identity)
                cited.append(identity)

    hits = sum(1 for identity in cited if identity in relevant)
    precision = hits / len(cited) if cited else 0.0
    recall = hits / len(relevant)
    return precision, recall


def _retrieved_violation(case: CaseSpec, item: EvalRetrieved) -> str | None:
    if item.hard_filter_violation is not None:
        return str(item.hard_filter_violation)
    for ref in case.forbidden_sources:
        if match_source_ref(
            ref,
            doc_code=item.doc_code,
            unit_ids=item.unit_ids,
            unit_key=item.unit_key,
            locator=item.locator,
        ):
            return "forbidden_source"
    return None


def _retrieval_case_metrics(
    case: CaseSpec, outcome: EvalOutcome, resolved: ResolvedGold
) -> dict[str, Any]:
    ordered: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    violating: set[tuple[str, str]] = set()
    for item in outcome.retrieved:
        identities = _retrieved_identities(item)
        for identity in identities:
            if identity not in seen:
                seen.add(identity)
                ordered.append(identity)
        if _retrieved_violation(case, item) is not None:
            violating.update(identities)

    retrieved_units = len(ordered)
    relevant = {("unit", str(item)) for item in resolved.relevant_unit_ids}
    metrics: dict[str, Any] = {
        "gold_units": len(relevant),
        "retrieved_units": retrieved_units,
        "hard_filter_violations": len(violating),
        "Recall@10": None,
        "MRR@10": None,
        "nDCG@10": None,
        "empty_recall": None,
    }
    if not relevant or resolved.skipped:
        return metrics

    top = ordered[:10]
    hits = [index for index, identity in enumerate(top) if identity in relevant]
    metrics["Recall@10"] = len(hits) / len(relevant)
    metrics["MRR@10"] = 1.0 / (hits[0] + 1) if hits else 0.0
    dcg = sum(1.0 / math.log2(index + 2) for index in hits)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant), 10) + 1))
    metrics["nDCG@10"] = dcg / ideal if ideal else 0.0
    metrics["empty_recall"] = 1.0 if retrieved_units == 0 else 0.0
    return metrics


# --------------------------------------------------------------------------- #
# Trace 数值
# --------------------------------------------------------------------------- #


def _json_object(payload: Any) -> Mapping[str, Any] | None:
    if not isinstance(payload, str):
        return None
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, Mapping) else None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _trace_latency(trace: TraceRecord | None) -> int | None:
    if trace is None:
        return None
    return _non_negative_int(getattr(trace, "latency_ms", None))


def _trace_tokens(trace: TraceRecord | None) -> tuple[int | None, int | None]:
    if trace is None:
        return None, None
    payload = _json_object(getattr(trace, "token_usage_json", None))
    if payload is None:
        return None, None
    tokens_in = _non_negative_int(payload.get("input"))
    if tokens_in is None:
        tokens_in = _non_negative_int(payload.get("prompt_tokens"))
    tokens_out = _non_negative_int(payload.get("output"))
    if tokens_out is None:
        tokens_out = _non_negative_int(payload.get("completion_tokens"))
    return tokens_in, tokens_out


def _trace_cost(trace: TraceRecord | None) -> float | None:
    if trace is None:
        return None
    payload = _json_object(getattr(trace, "cost_json", None))
    if payload is None:
        return None
    for key in ("cny", "cost_cny"):
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)
    return None


# --------------------------------------------------------------------------- #
# 单 case 打分
# --------------------------------------------------------------------------- #


def score_case(
    case: CaseSpec,
    resolved: ResolvedGold,
    outcome: EvalOutcome,
    trace: TraceRecord | None = None,
) -> CaseResult:
    """对单条 case 做确定性打分，返回逐项 check + 可聚合指标 + 运行成本字段。

    - ``resolved.skipped``（OCR）→ ``status="skipped_requires_ocr"``，只有 1 个
      ``scored`` check，不参与任何指标分母；
    - 否则固定输出 :data:`CHECK_IDS` 的 12 个 check；
    - ``status`` 为 ``fail`` 当且仅当有 check 为 ``fail``；``skipped`` 不算失败；
    - 延迟 / Token / 成本从 ``trace`` 读取（非法/负值忽略为 ``None``，不编造）。
    """
    if not isinstance(case, CaseSpec):
        raise TypeError("score_case 只接受 CaseSpec")
    if not isinstance(resolved, ResolvedGold):
        raise TypeError("score_case 只接受 ResolvedGold")
    if not isinstance(outcome, EvalOutcome):
        raise TypeError("score_case 只接受 EvalOutcome")
    if resolved.case_id != case.case_id:
        raise ValueError(
            f"resolved.case_id={resolved.case_id!r} 与 case.case_id={case.case_id!r} 不一致"
        )
    if trace is not None and not isinstance(trace, TraceRecord):
        raise TypeError("trace 必须是 TraceRecord 或 None")

    latency_ms = _trace_latency(trace)
    tokens_in, tokens_out = _trace_tokens(trace)
    cost_cny = _trace_cost(trace)
    trace_id = (trace.trace_id if trace is not None and trace.trace_id else None) or outcome.trace_id
    path = None if outcome.path is None else _kind_text(outcome.path)

    if resolved.skipped:
        return CaseResult(
            case_id=case.case_id,
            status=STATUS_SKIPPED_OCR,
            checks=(_skipped("scored", {"reason": STATUS_SKIPPED_OCR}),),
            metrics={},
            refused=None,
            should_refuse=bool(case.should_refuse),
            trace_id=trace_id,
            path=path,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_cny=cost_cny,
        )

    checks: list[CaseCheck] = []
    checks.extend(_value_checks(case, outcome))
    checks.extend(_source_checks(case, outcome, resolved))
    kind_checks, refused = _kind_checks(case, outcome)
    checks.extend(kind_checks)
    checks.extend(_pagination_checks(case, outcome))

    citation_precision, citation_recall = _citation_case_metrics(case, outcome, resolved, refused)
    retrieval = _retrieval_case_metrics(case, outcome, resolved)

    metrics: dict[str, Any] = {
        "value_hit": _binary_status(_check_by_id(checks, "value_hit")),
        "source_hit": _binary_status(_check_by_id(checks, "source_hit")),
        "kind_correct": _binary_status(_check_by_id(checks, "kind_correct")),
        "citation_precision": citation_precision,
        "citation_recall": citation_recall,
        "gold_units": retrieval["gold_units"],
        "retrieved_units": retrieval["retrieved_units"],
        "hard_filter_violations": retrieval["hard_filter_violations"],
        "Recall@10": retrieval["Recall@10"],
        "MRR@10": retrieval["MRR@10"],
        "nDCG@10": retrieval["nDCG@10"],
        "empty_recall": retrieval["empty_recall"],
    }
    status = STATUS_FAIL if any(item.status == STATUS_FAIL for item in checks) else STATUS_PASS

    return CaseResult(
        case_id=case.case_id,
        status=status,
        checks=tuple(checks),
        metrics=metrics,
        refused=refused,
        should_refuse=bool(case.should_refuse),
        trace_id=trace_id,
        path=path,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_cny=cost_cny,
    )


def _check_by_id(checks: Sequence[CaseCheck], check_id: str) -> CaseCheck:
    for item in checks:
        if item.check_id == check_id:
            return item
    raise AssertionError(f"内部错误：缺少 check {check_id}")


# --------------------------------------------------------------------------- #
# 聚合指标（全部为 0–1；None 表示无适用样本）
# --------------------------------------------------------------------------- #


def _scored(results: Sequence[CaseResult]) -> tuple[CaseResult, ...]:
    return tuple(item for item in results if item.status != STATUS_SKIPPED_OCR)


def _aligned(
    cases: Sequence[CaseSpec], results: Sequence[CaseResult]
) -> tuple[tuple[CaseSpec, ...], tuple[CaseResult, ...]]:
    case_items = tuple(cases)
    result_items = tuple(results)
    if len(case_items) != len(result_items):
        raise ValueError(f"cases 与 results 数量不一致：{len(case_items)} != {len(result_items)}")
    for case, result in zip(case_items, result_items):
        if case.case_id != result.case_id:
            raise ValueError(
                f"cases/results 顺序不一致：{case.case_id!r} != {result.case_id!r}"
            )
    return case_items, result_items


def _mean(values: Iterable[float | int | None]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return sum(numbers) / len(numbers) if numbers else None


def answer_metrics(results: Sequence[CaseResult]) -> dict[str, float | None]:
    """答案类指标：value_hit / source_hit / kind_correct / citation_precision/recall。"""
    scored = _scored(results)
    return {
        "value_hit": _mean(item.metrics.get("value_hit") for item in scored),
        "source_hit": _mean(item.metrics.get("source_hit") for item in scored),
        "kind_correct": _mean(item.metrics.get("kind_correct") for item in scored),
        "citation_precision": _mean(item.metrics.get("citation_precision") for item in scored),
        "citation_recall": _mean(item.metrics.get("citation_recall") for item in scored),
    }


def retrieval_metrics(results: Sequence[CaseResult]) -> dict[str, float | None]:
    """检索指标：unit 级 macro；无 gold 的 case 不进入任一指标的分母。

    ``hard_filter_violation_rate`` = 违规检索 unit 数 / 全部检索 unit 数，分母与
    其它检索指标一致（有 gold 且未跳过的 case）；负样本的泄漏由门禁
    ``security_leak`` 检查，不进入本质量指标。
    """
    scored = _scored(results)
    gold = [item for item in scored if int(item.metrics.get("gold_units") or 0) > 0]
    retrieved_total = sum(int(item.metrics.get("retrieved_units") or 0) for item in gold)
    violations_total = sum(int(item.metrics.get("hard_filter_violations") or 0) for item in gold)
    return {
        "Recall@10": _mean(item.metrics.get("Recall@10") for item in gold),
        "MRR@10": _mean(item.metrics.get("MRR@10") for item in gold),
        "nDCG@10": _mean(item.metrics.get("nDCG@10") for item in gold),
        "hard_filter_violation_rate": (
            violations_total / retrieved_total if retrieved_total else None
        ),
        "empty_recall_rate": _mean(item.metrics.get("empty_recall") for item in gold),
    }


def refusal_metrics(
    cases: Sequence[CaseSpec], results: Sequence[CaseResult]
) -> dict[str, float | None]:
    """拒答三指标：由同一 2×2 混淆矩阵派生，但三个字段各自独立计算。"""
    case_items, result_items = _aligned(cases, results)
    true_positive = false_positive = true_negative = false_negative = 0
    for case, result in zip(case_items, result_items):
        if result.status == STATUS_SKIPPED_OCR:
            continue
        refused = bool(result.refused)
        if case.should_refuse:
            if refused:
                true_positive += 1
            else:
                false_negative += 1
        elif refused:
            false_positive += 1
        else:
            true_negative += 1

    should_refuse_total = true_positive + false_negative
    answerable_total = false_positive + true_negative
    refused_total = true_positive + false_positive
    return {
        "refusal_recall": (
            true_positive / should_refuse_total if should_refuse_total else None
        ),
        "false_refusal_rate": false_positive / answerable_total if answerable_total else None,
        "refusal_precision": true_positive / refused_total if refused_total else None,
    }


def _percentile(values: Sequence[int], fraction: float) -> int | None:
    """nearest-rank 百分位（``P50``/``P95``），输入为空返回 ``None``。"""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def latency_metrics(results: Sequence[CaseResult]) -> dict[str, int | None]:
    """P50/P95 延迟（毫秒；nearest-rank）。"""
    values = [item.latency_ms for item in _scored(results) if item.latency_ms is not None]
    return {"p50_latency_ms": _percentile(values, 0.50), "p95_latency_ms": _percentile(values, 0.95)}


def cost_metrics(results: Sequence[CaseResult]) -> dict[str, float | int | None]:
    """Token 总和与成本：单题成本 = 有成本数据的 case 的总额 / 这些 case 数。"""
    scored = _scored(results)
    inputs = [item.tokens_in for item in scored if item.tokens_in is not None]
    outputs = [item.tokens_out for item in scored if item.tokens_out is not None]
    costs = [item.cost_cny for item in scored if item.cost_cny is not None]
    total_cost = sum(costs) if costs else None
    return {
        "tokens_in_total": sum(inputs) if inputs else None,
        "tokens_out_total": sum(outputs) if outputs else None,
        "cost_total_cny": total_cost,
        "cost_per_case_cny": (total_cost / len(costs)) if total_cost is not None else None,
    }


def aggregate_metrics(
    cases: Sequence[CaseSpec], results: Sequence[CaseResult]
) -> dict[str, Any]:
    """汇总一轮评测的全部指标；OCR 跳过 case 只进 ``skipped_count``，不进分母。"""
    case_items, result_items = _aligned(cases, results)
    scored = _scored(result_items)
    metrics: dict[str, Any] = {
        "case_count": len(result_items),
        "scored_count": len(scored),
        "skipped_count": len(result_items) - len(scored),
    }
    metrics.update(answer_metrics(result_items))
    metrics.update(retrieval_metrics(result_items))
    metrics.update(refusal_metrics(case_items, result_items))
    metrics.update(latency_metrics(result_items))
    metrics.update(cost_metrics(result_items))
    return metrics
