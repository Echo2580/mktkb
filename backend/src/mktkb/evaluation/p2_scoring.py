"""P2-T205：产品响应规范化、公开分母、H2 聚合与 P2 门禁判定（离线，零真实调用）。

本模块只做三件事：

1. **规范化**：把产品一轮问答的观测（cases.jsonl 里的 product）转成既有
   EvalOutcome，再交给既有的确定性 score_case；不复制打分规则、不改冻结期望。
2. **口径**：按验收矩阵 §1/§3/§4/§5 冻结的分母（B0 40 题 / 精确 Q01-Q24 24/24 /
   N01-N08 / C01-C06 / U01-U10 / H2 30 题）统计；error 与「未执行」不计入正确数，
   OCR 题不得静默跳过算通过；H2 只出聚合（不含 case_id / 题干）。
3. **门禁**：复用 gate.evaluate_gate 跑 8 项硬门禁，再叠加 P2 配置绑定与分母判定。
   **执行退出码与质量门禁码分开记录**；gate_v0_3 初始 unapproved → 任何放行判定都
   fail closed（release_allowed=False）。

设计约束（任务书 §5/§6、T205）：

- **fail closed**：缺 trace / 缺来源身份 / 缺配置绑定 / 缺样本 / 跨 scope / 同
  gate_version 改了配置 / 旧 gate 配置 / 不完整 run → 都不能放行；「无适用样本」是
  not_applicable，「缺必要数据」是 unknown，两者不混同。
- **零真实调用**：本模块不建索引、不调 provider、不读 .env；输入全部是产物/内存对象。
- **不按 H2 调参**：本模块不读 H2 题干/标签，只接受受限进程算好的逐题 pass/fail 计数。

P2 产物没有 P1 的「检索证据 id」与「评测身份绑定的 trace」，这两点在
evaluate_p2_gate 里分别是 citation_evidence_complete 与 run_manifest["gate_config_hash"]
显式入参：不提供就记 unknown，不按通过处理。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .dataset import CaseSpec
from .gate import (
    CONFIG_SCHEMA_VERSION_V0_3,
    EXIT_HARD_FAILURE,
    EXIT_PASS,
    EXIT_QUALITY_REGRESSION,
    EXIT_UNKNOWN,
    GATE_STATUS_NOT_APPLICABLE,
    GATE_STATUS_NOT_EVALUATED,
    GATE_VERSION_V0_3,
    HARD_GATE_IDS,
    P2_GATE_CONFIG_PATH,
    GateConfig,
    GateResult,
    evaluate_gate,
    load_gate_config,
)
from .gold import ResolvedGold
from .runner import RunManifest, RunResult
from .scorers import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIPPED_OCR,
    CaseResult,
    EvalCitation,
    EvalOutcome,
    EvalRetrieved,
    score_case,
)

__all__ = [
    "P2_B0_EXACT_IDS",
    "P2_B0_EXACT_TOTAL",
    "P2_B0_IDS",
    "P2_B0_MIN_PASS",
    "P2_B0_OCR_IDS",
    "P2_B0_OCR_TOTAL",
    "P2_B0_TEXT_IDS",
    "P2_B0_TOTAL",
    "P2_BOUNDARY_IDS",
    "P2_BOUNDARY_TOTAL",
    "P2_HOLDOUT_MAX_HARD_FAILURES",
    "P2_HOLDOUT_MIN_PASS",
    "P2_HOLDOUT_STRATA",
    "P2_HOLDOUT_TOTAL",
    "P2_NEGATIVE_IDS",
    "P2_NEGATIVE_TOTAL",
    "P2_UPDATE_DELETE_IDS",
    "P2_UPDATE_DELETE_TOTAL",
    "P2Block",
    "P2CaseScore",
    "P2GateConfig",
    "P2GateDecision",
    "P2HoldoutCaseScore",
    "P2HoldoutScorecard",
    "P2IsolationIssue",
    "P2PublicScorecard",
    "P2ScoredCase",
    "P2ScoringError",
    "P2Standards",
    "P2SuiteTally",
    "P2_BINDING_VERSION",
    "aggregate_holdout",
    "binding_config_hash",
    "build_gate_rows",
    "citation_evidence_status",
    "build_gate_run",
    "check_scenario_isolation",
    "check_source_isolation",
    "evaluate_p2_gate",
    "evaluate_p2_hard_gates",
    "load_p2_gate_config",
    "normalize_product_outcome",
    "score_public_case",
    "score_public_suites",
]

P2_SCORING_SCHEMA_VERSION = "mktkb.p2.scoring.v0.1"
#: P2 run 的作用域与模式（T203 契约：end-to-end 产品问答，不是 P1 的 retrieval_only）。
P2_RUN_SCOPE = "end_to_end"
P2_RUN_MODE = "end_to_end"

#: T206-PRE：绑定摘要的口径版本。改了参与摘要的组件集合就必须升版本（否则同 hash
#: 会被误当成"同一份身份"）。
P2_BINDING_VERSION = "p2-binding/v0.1"
#: 绑定摘要必须覆盖的组件（缺任何一项都 fail closed，不 quietly 跳过）。
P2_BINDING_FIELDS: tuple[str, ...] = (
    "dataset_version",
    "manifest_sha256",
    "label_version",
    "pipeline_version",
    "index_revision",
    "provider",
    "gate_version",
    "gate_config_hash",
)

# --------------------------------------------------------------------------- #
# 冻结分母（验收矩阵 §1/§3/§4/§5；任务书 §5）
# --------------------------------------------------------------------------- #

P2_B0_IDS: tuple[str, ...] = tuple(f"Q{index:02d}" for index in range(1, 41))
#: 精确字段题：Q01-Q24 必须 24/24（验收矩阵 §1）。
P2_B0_EXACT_IDS: tuple[str, ...] = P2_B0_IDS[:24]
#: text 题：Q25-Q32（质量口径，不设硬门槛）。
P2_B0_TEXT_IDS: tuple[str, ...] = P2_B0_IDS[24:32]
#: OCR 题：Q33-Q40 —— 必须真的执行并打分，**不得**静默跳过算通过。
P2_B0_OCR_IDS: tuple[str, ...] = P2_B0_IDS[32:]
P2_NEGATIVE_IDS: tuple[str, ...] = tuple(f"N{index:02d}" for index in range(1, 9))
P2_BOUNDARY_IDS: tuple[str, ...] = tuple(f"C{index:02d}" for index in range(1, 7))
P2_UPDATE_DELETE_IDS: tuple[str, ...] = tuple(f"U{index:02d}" for index in range(1, 11))

P2_B0_TOTAL = 40
P2_B0_MIN_PASS = 36
P2_B0_EXACT_TOTAL = 24
P2_B0_EXACT_MIN_PASS = 24
P2_B0_OCR_TOTAL = 8
P2_NEGATIVE_TOTAL = 8
P2_BOUNDARY_TOTAL = 6
P2_UPDATE_DELETE_TOTAL = 10
P2_HOLDOUT_TOTAL = 30
P2_HOLDOUT_MIN_PASS = 24
P2_HOLDOUT_MAX_HARD_FAILURES = 0

#: H2 冻结分层（T202 P2_STRATA；这里复制字面量，避免把 holdout 依赖带进公开路径）。
P2_HOLDOUT_STRATA: Mapping[str, int] = MappingProxyType(
    {
        "paraphrase": 10,
        "multi_turn": 5,
        "negative": 5,
        "stale_conflict": 5,
        "cross_doc_security": 5,
    }
)
#: H2 硬失败类别（安全/跨用户/跨实体/失效来源）：任一 >0 → 不放行。
P2_HOLDOUT_HARD_FAILURE_KINDS: tuple[str, ...] = (
    "safety",
    "cross_user",
    "cross_entity",
    "stale_source",
)

CASE_STATUS_PASS = STATUS_PASS
CASE_STATUS_FAIL = STATUS_FAIL
CASE_STATUS_ERROR = "error"
CASE_STATUS_NOT_EXECUTED = "not_executed"
CASE_STATUS_SKIPPED_OCR = STATUS_SKIPPED_OCR

SEVERITY_HARD = "hard"
SEVERITY_UNKNOWN = "unknown"
SEVERITY_QUALITY = "quality"

DECISION_PASS = "pass"
DECISION_BLOCKED = "blocked"
DECISION_UNKNOWN = "unknown"

#: C1(2b)：执行模式标记。默认是**保守**的本地/Mock；要标 live 必须由调用方显式传入，
#: 且只有 live 模式才允许 real_calls > 0（mock 链绝不能"顺手"标成真实调用）。
EXECUTION_MODE_LOCAL_MOCK = "local_mock"
EXECUTION_MODE_LIVE = "live"
EXECUTION_MODES: tuple[str, ...] = (EXECUTION_MODE_LOCAL_MOCK, EXECUTION_MODE_LIVE)

_P2_STATUSES = frozenset(
    {CASE_STATUS_PASS, CASE_STATUS_FAIL, CASE_STATUS_ERROR, CASE_STATUS_NOT_EXECUTED, CASE_STATUS_SKIPPED_OCR}
)
_EXECUTED_STATUSES = frozenset({CASE_STATUS_PASS, CASE_STATUS_FAIL})


class P2ScoringError(ValueError):
    """P2 评分/门禁输入不合规（fail closed；带稳定 code，不吞异常）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code)
        self.detail = str(detail)
        message = f"{self.code}: {detail}" if detail else self.code
        super().__init__(message)


def _execution_mark(execution_mode: str, real_calls: int, *, owner: str) -> tuple[str, int]:
    """校验执行模式/真实调用标记（C1）。

    - 只接受 ``local_mock`` / ``live``；拼写错误即报错（不猜）；
    - ``real_calls`` 不能为负；
    - 非 live 模式不允许 ``real_calls > 0``：mock 链上说"有真实调用"就是谎报，直接拒绝；
    - live 模式允许 0 次真实调用（规则路径/全部拒答也是合法结果），但**必须显式**标 live。
    """
    mode = str(execution_mode)
    if mode not in EXECUTION_MODES:
        raise P2ScoringError("execution_mode_invalid", f"{owner}: {mode!r}")
    calls = int(real_calls)
    if calls < 0:
        raise P2ScoringError("real_calls_invalid", f"{owner}: real_calls={calls}")
    if mode != EXECUTION_MODE_LIVE and calls > 0:
        raise P2ScoringError(
            "real_calls_without_live_mode",
            f"{owner}: execution_mode={mode!r} 却声称 real_calls={calls}（mock 不得标真实调用）",
        )
    return mode, calls


# --------------------------------------------------------------------------- #
# 绑定摘要 + 引用证据（T206-PRE）
# --------------------------------------------------------------------------- #


def _binding_component(value: Any, name: str) -> Any:
    """绑定组件规范化：字符串必须非空（去空白），映射按 canonical JSON 递归排序。

    不做"缺字段给默认值"：缺/空一律抛 ``binding_input_missing``（fail closed）。
    """
    if isinstance(value, Mapping):
        if not value:
            raise P2ScoringError("binding_input_missing", f"{name} 不能为空对象")
        return {
            str(key): _binding_component(item, f"{name}.{key}")
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_binding_component(item, f"{name}[]") for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if int(value) < 0:
            raise P2ScoringError("binding_input_invalid", f"{name} 不能为负：{value}")
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise P2ScoringError("binding_input_missing", f"{name} 不能为空字符串")
        return text
    if value is None:
        raise P2ScoringError("binding_input_missing", f"{name} 缺失（None）")
    raise P2ScoringError("binding_input_invalid", f"{name} 只接受 str/int/bool/映射，收到 {type(value).__name__}")


def binding_config_hash(
    *,
    dataset_version: str,
    manifest_sha256: str,
    label_version: str,
    pipeline_version: str,
    index_revision: int,
    provider: Mapping[str, Any],
    gate_version: str,
    gate_config_hash: str,
) -> str:
    """由 dataset manifest / pipeline / 索引 / provider / gate 身份算**确定性**绑定摘要。

    - 同配置同 hash：所有组件先规范化（去空白、键排序、类型收紧）再 canonical JSON；
    - 改配置必变：任一组件变化都会改变摘要（不做"近似相等"）；
    - 缺任一组件 → ``binding_input_missing``，声明了 ``P2_BINDING_VERSION`` 以免跨口径复用；
    - 摘要只含身份/版本/模型名，不含题面、答案、凭据或路径。
    """
    if index_revision is None:
        raise P2ScoringError("binding_input_missing", "index_revision 缺失（None）")
    if isinstance(index_revision, bool) or not isinstance(index_revision, int) or index_revision < 0:
        raise P2ScoringError("binding_input_invalid", f"index_revision 必须是非负整数，收到 {index_revision!r}")
    payload = {
        "binding_version": P2_BINDING_VERSION,
        "dataset_version": _binding_component(dataset_version, "dataset_version"),
        "manifest_sha256": _binding_component(manifest_sha256, "manifest_sha256"),
        "label_version": _binding_component(label_version, "label_version"),
        "pipeline_version": _binding_component(pipeline_version, "pipeline_version"),
        "index_revision": int(index_revision),
        "provider": _binding_component(provider, "provider"),
        "gate_version": _binding_component(gate_version, "gate_version"),
        "gate_config_hash": _binding_component(gate_config_hash, "gate_config_hash"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def citation_evidence_status(
    case_rows: Sequence[Mapping[str, Any]],
    *,
    include_case_ids: bool = True,
) -> dict[str, Any]:
    """从 P2 逐题行判定"引用是否落在本轮可核对的证据身份上"（不伪造）。

    只对 ``kind == "answer"` 的轮次要求引用；每条引用必须有稳定的 ``unit_id``、
    非空 ``locator``，且产品库侧解析 ``verified is True``（当前有效版本 + 本 run 灌入）。
    任一轮缺证据、任一引用未核实、或根本没有作答轮 → ``complete=False``（unknown），
    绝不用"计数看起来对"代替核实。

    ``include_case_ids=False`` 时 issue 里不带 case_id（H2 聚合路径用）。
    """
    answered = 0
    turns_with_evidence = 0
    citations = 0
    verified = 0
    issues: list[dict[str, Any]] = []
    for row in case_rows:
        if not isinstance(row, Mapping):
            raise P2ScoringError("case_row_invalid", "citation_evidence_status 只接受对象行")
        case_id = str(row.get("case_id") or "")
        for turn in row.get("turns") or ():
            if not isinstance(turn, Mapping):
                raise P2ScoringError("turn_invalid", "case 行的 turns 必须是对象数组")
            product = turn.get("product")
            if not isinstance(product, Mapping):
                continue
            if str(product.get("kind") or "") != "answer":
                continue
            answered += 1
            raw = product.get("evidence")
            items = (
                [item for item in raw if isinstance(item, Mapping)]
                if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes))
                else []
            )
            if not items:
                issue = {"code": "citation_evidence_missing", "turn": int(turn.get("turn") or 0)}
                if include_case_ids:
                    issue["case_id"] = case_id
                issues.append(issue)
                continue
            turns_with_evidence += 1
            for item in items:
                citations += 1
                ok = (
                    bool(str(item.get("unit_id") or "").strip())
                    and bool(item.get("locator") or {})
                    and item.get("verified") is True
                )
                if ok:
                    verified += 1
                else:
                    issue = {
                        "code": "citation_evidence_unverified",
                        "turn": int(turn.get("turn") or 0),
                        "unit_id": str(item.get("unit_id") or ""),
                        "reason": item.get("reason"),
                    }
                    if include_case_ids:
                        issue["case_id"] = case_id
                    issues.append(issue)
    if answered == 0:
        issues.append({"code": "no_answer_turn"})
    return {
        "complete": bool(answered > 0 and not issues),
        "answered_turns": answered,
        "turns_with_evidence": turns_with_evidence,
        "citations": citations,
        "verified_citations": verified,
        "issues": issues,
    }


# --------------------------------------------------------------------------- #
# 门禁块（结构性阻断项；severity 决定质量退出码）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class P2Block:
    """一条「不能放行」的理由：稳定 code + severity + 证据。"""

    code: str
    severity: str
    detail: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in {SEVERITY_HARD, SEVERITY_UNKNOWN, SEVERITY_QUALITY}:
            raise P2ScoringError("block_severity_invalid", repr(self.severity))
        if not str(self.code).strip():
            raise P2ScoringError("block_code_missing", "P2Block.code 不能为空")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }


# --------------------------------------------------------------------------- #
# 产品响应规范化（product -> EvalOutcome）
# --------------------------------------------------------------------------- #


def _text(value: Any, name: str, *, allow_empty: bool = True) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise P2ScoringError("product_field_invalid", f"{name} 必须是字符串，收到 {type(value).__name__}")
    text = value.strip() if not allow_empty else value
    return text


def _lookup_document_code(name: str, mapping: Mapping[str, str]) -> str | None:
    """按「含扩展名 -> 去扩展名 -> 去扩展名后再去前缀编号以外」逐级匹配文档代号。"""
    raw = str(name or "").strip()
    if not raw:
        return None
    for key in (raw, Path(raw).stem, Path(raw).name):
        found = mapping.get(key)
        if found:
            return str(found)
    return None


def _source_identity(
    item: Mapping[str, Any],
    *,
    document_codes: Mapping[str, str],
    source_index: Mapping[str, Mapping[str, Any]] | None,
) -> EvalCitation:
    source_id = str(item.get("source_id") or "").strip()
    if not source_id:
        raise P2ScoringError("source_identity_missing", "产品来源缺少 source_id，无法做单位级引用比对")
    document_name = str(item.get("document_name") or "").strip()
    indexed = source_index.get(source_id) if source_index is not None else None
    doc_code = None
    unit_key = None
    locator: Mapping[str, Any] = {}
    if indexed is not None:
        doc_code = str(indexed.get("doc_code") or "").strip() or None
        unit_key = indexed.get("unit_key")
        raw_locator = indexed.get("locator")
        if isinstance(raw_locator, Mapping):
            locator = dict(raw_locator)
    if doc_code is None:
        doc_code = _lookup_document_code(document_name, document_codes)
    if not doc_code:
        raise P2ScoringError(
            "source_document_unmapped",
            f"产品来源 {document_name!r} 没有可用的文档代号映射（不允许静默用空字符串比对）",
        )
    if not locator:
        raw_locator = item.get("locator")
        if isinstance(raw_locator, Mapping):
            locator = dict(raw_locator)
    if unit_key is not None and not isinstance(unit_key, str):
        raise P2ScoringError("source_identity_invalid", "source_index.unit_key 必须是字符串或 None")
    return EvalCitation(
        doc_code=doc_code,
        unit_key=unit_key,
        unit_ids=(source_id,),
        locator=locator,
        text="",
        kind=str(item.get("status") or ""),
    )


def normalize_product_outcome(
    turn: Mapping[str, Any],
    *,
    document_codes: Mapping[str, str],
    source_index: Mapping[str, Mapping[str, Any]] | None = None,
    evidence: Sequence[Mapping[str, Any]] = (),
) -> EvalOutcome:
    """把一轮产品观测规范化为 EvalOutcome；任何身份不清都抛错（fail closed）。

    turn 可以是 P2 cases.jsonl 的轮次行（带 product）或直接是 product 字典。
    document_codes 是「产品文档名 -> 数据集 doc_code」的显式映射（不猜）：
    产品 API 只回 document_name，gold 用 doc_code，两者必须显式绑定。
    """
    if not isinstance(turn, Mapping):
        raise P2ScoringError("turn_invalid", "turn 必须是对象")
    product = turn.get("product")
    if not isinstance(product, Mapping):
        raise P2ScoringError("product_missing", "该轮没有产品响应（product），不能打分")
    kind = str(product.get("kind") or "").strip()
    if not kind:
        raise P2ScoringError("product_kind_missing", "产品响应缺少 kind，无法判定结局")
    text = _text(product.get("text"), "product.text")
    sources = product.get("sources") or ()
    if isinstance(sources, (str, bytes)) or not isinstance(sources, Sequence):
        raise P2ScoringError("product_sources_invalid", "product.sources 必须是数组")
    citations: list[EvalCitation] = []
    for item in sources:
        if not isinstance(item, Mapping):
            raise P2ScoringError("product_sources_invalid", "product.sources 的每项必须是对象")
        citations.append(
            _source_identity(item, document_codes=document_codes, source_index=source_index)
        )

    # T206-PRE-R1：候选集合优先用调用方显式给的（评测夹具），否则用产品本轮
    # **真实检索候选**（``product.retrieved``，不是引用）。两者都没有 = 空集，
    # gate 的 citation_required 会因此判 fail —— 不静默当通过。
    raw_retrieved: Sequence[Any] = evidence
    if not raw_retrieved:
        payload_retrieved = product.get("retrieved")
        if isinstance(payload_retrieved, Sequence) and not isinstance(payload_retrieved, (str, bytes)):
            raw_retrieved = payload_retrieved
    retrieved: list[EvalRetrieved] = []
    for item in raw_retrieved:
        if not isinstance(item, Mapping):
            raise P2ScoringError("evidence_invalid", "evidence 的每项必须是对象")
        raw_ids = item.get("unit_ids") or ()
        if isinstance(raw_ids, (str, bytes)):
            raw_ids = (raw_ids,)
        doc_code = str(item.get("doc_code") or "")
        if not doc_code:
            # 产品只回文档名：按调用方给的显式映射换算代号；映射不到就留空，
            # 让引用子集判定按 unit_id 进行（不猜文档代号、也不因此放宽）。
            doc_code = _lookup_document_code(str(item.get("document_name") or ""), document_codes) or ""
        retrieved.append(
            EvalRetrieved(
                doc_code=doc_code,
                unit_ids=tuple(str(value) for value in raw_ids if str(value)),
                unit_key=item.get("unit_key"),
                locator=dict(item.get("locator") or {}),
                chunk_id=item.get("chunk_id"),
                hard_filter_violation=item.get("hard_filter_violation"),
            )
        )

    pagination = turn.get("pagination") or product.get("pagination") or {}
    if not isinstance(pagination, Mapping):
        raise P2ScoringError("pagination_invalid", "pagination 必须是对象")
    trace_id = product.get("trace_id") or turn.get("trace_id")
    path = product.get("trace_path") or turn.get("trace_path")
    return EvalOutcome(
        kind=kind,
        text=text,
        citations=tuple(citations),
        facts=(),
        pagination=dict(pagination),
        trace_id=None if trace_id is None else str(trace_id),
        path="rag" if path is None else str(path),
        retrieved=tuple(retrieved),
    )


def outcome_to_dict(outcome: EvalOutcome) -> dict[str, Any]:
    """EvalOutcome 的线上 JSON 形态（与 P1 cases.jsonl.outcome 同键；gate 读它）。"""
    return {
        "kind": outcome.kind,
        "text": outcome.text,
        "path": outcome.path,
        "trace_id": outcome.trace_id,
        "pagination": dict(outcome.pagination),
        "citations": [
            {
                "doc_code": item.doc_code,
                "unit_key": item.unit_key,
                "unit_ids": list(item.unit_ids),
                "locator": dict(item.locator),
                "text": item.text,
                "kind": item.kind,
            }
            for item in outcome.citations
        ],
        "facts": [],
        "retrieved": [
            {
                "doc_code": item.doc_code,
                "unit_ids": list(item.unit_ids),
                "unit_key": item.unit_key,
                "locator": dict(item.locator),
                "chunk_id": item.chunk_id,
                "hard_filter_violation": item.hard_filter_violation,
            }
            for item in outcome.retrieved
        ],
    }


# --------------------------------------------------------------------------- #
# 隔离校验（场景状态 / 来源身份）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class P2IsolationIssue:
    code: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


def check_source_isolation(
    citations: Sequence[EvalCitation],
    *,
    allowed_doc_codes: Iterable[str] | None = None,
    forbidden_doc_codes: Iterable[str] = (),
    allowed_statuses: Iterable[str] = ("active", ""),
) -> tuple[P2IsolationIssue, ...]:
    """来源身份隔离：本轮引用只能指向本次 run 灌进来的资料与有效版本。

    - 引用文档不在 allowed_doc_codes → source_outside_run（跨 run / 跨场景串用）；
    - 命中 forbidden_doc_codes → source_forbidden_document；
    - 引用不是 unit 级（没有 source_id 单位）→ citation_not_unit_level；
    - 来源状态不是 active（旧/失效版本）→ source_not_active。
    """
    allowed = None if allowed_doc_codes is None else {str(item) for item in allowed_doc_codes}
    forbidden = {str(item) for item in forbidden_doc_codes}
    statuses = {str(item) for item in allowed_statuses}
    issues: list[P2IsolationIssue] = []
    for citation in citations:
        if not citation.unit_ids:
            issues.append(P2IsolationIssue("citation_not_unit_level", citation.doc_code))
        if citation.doc_code in forbidden:
            issues.append(P2IsolationIssue("source_forbidden_document", citation.doc_code))
        elif allowed is not None and citation.doc_code not in allowed:
            issues.append(P2IsolationIssue("source_outside_run", citation.doc_code))
        if str(citation.kind) not in statuses:
            issues.append(P2IsolationIssue("source_not_active", f"{citation.doc_code}:{citation.kind}"))
    return tuple(issues)


def check_scenario_isolation(case_rows: Sequence[Mapping[str, Any]]) -> tuple[P2IsolationIssue, ...]:
    """场景隔离：一个 case 一个会话；轮次必须从 1 连续；多轮题必须有会话。

    复用既有 U 测试的语义（同会话多轮、状态不跨 case 泄漏），只做结构检查，不改产品。
    """
    issues: list[P2IsolationIssue] = []
    seen: dict[str, str] = {}
    for row in case_rows:
        case_id = str(row.get("case_id") or "")
        conversation = row.get("conversation_id")
        turns = row.get("turns") or ()
        if conversation:
            key = str(conversation)
            if key in seen:
                issues.append(
                    P2IsolationIssue("scenario_conversation_shared", f"{seen[key]} 与 {case_id} 共用会话")
                )
            else:
                seen[key] = case_id
        elif len(turns) > 1:
            issues.append(P2IsolationIssue("scenario_conversation_missing", case_id))
        numbers = [int(turn.get("turn") or 0) for turn in turns if isinstance(turn, Mapping)]
        if numbers and numbers != list(range(1, len(numbers) + 1)):
            issues.append(P2IsolationIssue("turn_sequence_gap", f"{case_id}:{numbers}"))
    return tuple(issues)


# --------------------------------------------------------------------------- #
# 逐题打分（复用 score_case；OCR 不跳过）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class P2CaseScore:
    """一条 case 的评分结论（不含题干/回答文本，可安全聚合）。"""

    case_id: str
    suite: str
    stratum: str
    status: str
    requires_ocr: bool
    planned_turns: int
    executed_turns: int
    checks: tuple[Mapping[str, Any], ...] = ()
    issues: tuple[P2IsolationIssue, ...] = ()
    trace_ids: tuple[str, ...] = ()
    turn_kinds: tuple[str, ...] = ()
    #: C1(2b)：执行模式（默认 local_mock）与该题的真实调用次数；live 必须显式传入。
    execution_mode: str = EXECUTION_MODE_LOCAL_MOCK
    real_calls: int = 0

    def __post_init__(self) -> None:
        _execution_mark(self.execution_mode, self.real_calls, owner=f"case {self.case_id}")
        if not str(self.case_id).strip():
            raise P2ScoringError("case_id_missing", "P2CaseScore.case_id 不能为空")
        if self.status not in _P2_STATUSES:
            raise P2ScoringError("case_status_invalid", repr(self.status))
        if self.planned_turns < 0 or self.executed_turns < 0:
            raise P2ScoringError("turn_count_invalid", "轮次数不能为负")
        if self.executed_turns > self.planned_turns:
            raise P2ScoringError(
                "turn_count_invalid", f"{self.case_id}: executed={self.executed_turns} > planned={self.planned_turns}"
            )

    @property
    def executed(self) -> bool:
        return self.status in _EXECUTED_STATUSES

    @property
    def passed(self) -> bool:
        return self.status == CASE_STATUS_PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "suite": self.suite,
            "stratum": self.stratum,
            "status": self.status,
            "requires_ocr": bool(self.requires_ocr),
            "planned_turns": int(self.planned_turns),
            "executed_turns": int(self.executed_turns),
            "checks": [dict(item) for item in self.checks],
            "issues": [item.to_dict() for item in self.issues],
            "turn_kinds": list(self.turn_kinds),
            "trace_ids": list(self.trace_ids),
            "execution_mode": self.execution_mode,
            "real_calls": int(self.real_calls),
        }


@dataclass(frozen=True)
class P2ScoredCase:
    """逐题打分 + 原始 outcome / CaseResult（供构建 gate 行；不落 H2 产物）。"""

    score: P2CaseScore
    outcome: EvalOutcome | None = field(default=None, repr=False)
    result: CaseResult | None = field(default=None, repr=False)


def _resolved_without_index(case: CaseSpec) -> ResolvedGold:
    """不依赖索引的 gold：只做「来源引用 -> 单位身份」比对，OCR 不置 skipped。

    P1 的 resolve_case 把 requires_ocr 一律标 skipped（P0 没有 OCR 链路）。P2 的 OCR
    真的执行了，跳过就等于把 OCR 题静默当通过，故这里显式不跳过；来源匹配交给
    EvalCitation 的 unit_id / unit_key / locator（match_source_ref 的同一口径）。
    """
    return ResolvedGold(
        case_id=case.case_id,
        requires_ocr=bool(case.requires_ocr),
        skipped=False,
        sources=(),
        unit_ids=(),
        relevant_unit_ids=(),
    )


def score_public_case(
    case: CaseSpec,
    case_row: Mapping[str, Any] | None,
    *,
    document_codes: Mapping[str, str],
    source_index: Mapping[str, Mapping[str, Any]] | None = None,
    allowed_doc_codes: Iterable[str] | None = None,
    forbidden_doc_codes: Iterable[str] = (),
    evidence: Sequence[Mapping[str, Any]] = (),
    execution_mode: str = EXECUTION_MODE_LOCAL_MOCK,
    real_calls: int = 0,
) -> P2ScoredCase:
    """给一条 public case 打分：多轮取末轮、中间轮 error 即整题 error、OCR 不跳过。

    ``execution_mode``/``real_calls`` 由 run 上下文显式传入（C1）：默认保守地记
    ``local_mock``/0；真实链必须在构造时明确标 ``live`` 并给出实测出站次数，
    不允许"默认当成真实"或"mock 上顺手标真实"。
    """
    if not isinstance(case, CaseSpec):
        raise P2ScoringError("case_invalid", "score_public_case 只接受 CaseSpec")
    base = {
        "case_id": case.case_id,
        "suite": str(case.suite),
        "stratum": str(case.stratum),
        "requires_ocr": bool(case.requires_ocr),
        "planned_turns": max(1, len(case.turns)),
        "execution_mode": execution_mode,
        "real_calls": int(real_calls),
    }
    if case_row is None:
        return P2ScoredCase(
            score=P2CaseScore(
                **base,
                status=CASE_STATUS_NOT_EXECUTED,
                executed_turns=0,
                issues=(P2IsolationIssue("case_not_executed", case.case_id),),
            )
        )
    if not isinstance(case_row, Mapping):
        raise P2ScoringError("case_row_invalid", f"{case.case_id}: case 行必须是对象")
    if str(case_row.get("case_id") or "") != case.case_id:
        raise P2ScoringError(
            "case_id_mismatch", f"{case.case_id}: 行 case_id={case_row.get('case_id')!r} 不一致"
        )
    turns = case_row.get("turns") or ()
    if isinstance(turns, (str, bytes)) or not isinstance(turns, Sequence):
        raise P2ScoringError("turns_invalid", f"{case.case_id}: turns 必须是数组")
    turns = tuple(item for item in turns if isinstance(item, Mapping))
    executed_turns = len(turns)
    turn_kinds = tuple(str((turn.get("product") or {}).get("kind") or "") for turn in turns)
    trace_ids = tuple(
        str((turn.get("product") or {}).get("trace_id") or turn.get("trace_id") or "")
        for turn in turns
    )
    planned = max(int(base["planned_turns"]), int(case_row.get("planned_turns") or 0))
    base.update(planned_turns=planned, executed_turns=executed_turns)
    base.update(turn_kinds=turn_kinds, trace_ids=trace_ids)

    def _failed(status: str, issues: Sequence[P2IsolationIssue]) -> P2ScoredCase:
        return P2ScoredCase(score=P2CaseScore(**base, status=status, issues=tuple(issues)))

    if str(case_row.get("status") or "") == "error" or case_row.get("error_code"):
        return _failed(
            CASE_STATUS_ERROR,
            (
                P2IsolationIssue(
                    "case_error",
                    f"{case.case_id}:{case_row.get('error_code') or 'error'}",
                ),
            ),
        )
    if executed_turns == 0:
        issue = (
            P2IsolationIssue("ocr_not_executed", case.case_id)
            if case.requires_ocr
            else P2IsolationIssue("case_not_executed", case.case_id)
        )
        return _failed(CASE_STATUS_NOT_EXECUTED, (issue,))
    if executed_turns < planned:
        return _failed(
            CASE_STATUS_ERROR,
            (
                P2IsolationIssue(
                    "turns_incomplete", f"{case.case_id}: {executed_turns}/{planned}"
                ),
            ),
        )
    for turn in turns:
        if str(turn.get("status") or "") != "ok" or turn.get("error_code"):
            return _failed(
                CASE_STATUS_ERROR,
                (
                    P2IsolationIssue(
                        "turn_error",
                        f"{case.case_id}#{turn.get('turn')}:{turn.get('error_code') or turn.get('status')}",
                    ),
                ),
            )
        if not isinstance(turn.get("product"), Mapping):
            return _failed(
                CASE_STATUS_ERROR,
                (
                    P2IsolationIssue(
                        "product_missing", f"{case.case_id}#{turn.get('turn')}"
                    ),
                ),
            )
    final_turn = turns[-1]
    outcome = normalize_product_outcome(
        final_turn,
        document_codes=document_codes,
        source_index=source_index,
        evidence=evidence,
    )
    issues = list(
        check_source_isolation(
            outcome.citations,
            allowed_doc_codes=allowed_doc_codes,
            forbidden_doc_codes=forbidden_doc_codes,
        )
    )
    result = score_case(case, _resolved_without_index(case), outcome)
    if result.status == STATUS_SKIPPED_OCR:
        issues.append(P2IsolationIssue("ocr_silently_skipped", case.case_id))
        return P2ScoredCase(
            score=P2CaseScore(
                **base,
                status=CASE_STATUS_ERROR,
                checks=tuple(item.to_dict() for item in result.checks),
                issues=tuple(issues),
            ),
            outcome=outcome,
            result=result,
        )
    checks = tuple(item.to_dict() for item in result.checks)
    status = CASE_STATUS_PASS if result.status == STATUS_PASS else CASE_STATUS_FAIL
    return P2ScoredCase(
        score=P2CaseScore(**base, status=status, checks=checks, issues=tuple(issues)),
        outcome=outcome,
        result=result,
    )


# --------------------------------------------------------------------------- #
# 公开分母（B0 40 / 精确 24 / N8 / C6 / U10）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class P2SuiteTally:
    """一个公开 suite 的分母口径计数（计划/执行/打分/通过 + OCR 与精确子口径）。"""

    suite: str
    planned: int
    executed: int
    scored: int
    passed: int
    failed: int
    errors: int
    not_executed: int
    skipped: int
    ocr_planned: int
    ocr_executed: int
    ocr_passed: int
    exact_planned: int
    exact_passed: int
    required_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "planned": self.planned,
            "executed": self.executed,
            "scored": self.scored,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "not_executed": self.not_executed,
            "skipped": self.skipped,
            "ocr_planned": self.ocr_planned,
            "ocr_executed": self.ocr_executed,
            "ocr_passed": self.ocr_passed,
            "exact_planned": self.exact_planned,
            "exact_passed": self.exact_passed,
            "required_passed": self.required_passed,
        }


@dataclass(frozen=True)
class P2PublicScorecard:
    """公开控制矩阵：分母 + 结构性阻断项；release_ready 只表示「没有已知阻断」。

    C1(2b)：``execution_mode``/``real_calls`` 来自逐题打分（同一 run 必须同模式，混用即报错）；
    C4：``run_id`` 记录本矩阵出自哪个 run，供门禁核对"这份分母是不是这次 run 的"。
    """

    suites: Mapping[str, P2SuiteTally]
    blocks: tuple[P2Block, ...] = ()
    execution_mode: str = EXECUTION_MODE_LOCAL_MOCK
    real_calls: int = 0
    run_id: str | None = None
    #: T206-PRE：本矩阵所属 run 的绑定摘要（与 run_manifest.config_hash 同源）。
    config_hash: str | None = None

    def __post_init__(self) -> None:
        _execution_mark(self.execution_mode, self.real_calls, owner="public scorecard")
        if self.config_hash is not None and not str(self.config_hash).strip():
            raise P2ScoringError("config_hash_invalid", "public scorecard 的 config_hash 不能为空字符串")

    @property
    def release_ready(self) -> bool:
        return not self.blocks and all(item.required_passed for item in self.suites.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": P2_SCORING_SCHEMA_VERSION,
            "suites": {name: tally.to_dict() for name, tally in self.suites.items()},
            "blocks": [item.to_dict() for item in self.blocks],
            "release_ready": bool(self.release_ready),
            "execution_mode": self.execution_mode,
            "real_calls": int(self.real_calls),
            "run_id": self.run_id,
            "config_hash": self.config_hash,
        }


def _tally(
    suite: str,
    ids: Sequence[str],
    scores: Mapping[str, P2CaseScore],
    *,
    min_pass: int,
    exact_ids: Sequence[str] = (),
    ocr_ids: Sequence[str] = (),
) -> tuple[P2SuiteTally, list[P2Block]]:
    blocks: list[P2Block] = []
    statuses: list[str] = []
    missing: list[str] = []
    for case_id in ids:
        score = scores.get(case_id)
        if score is None:
            missing.append(case_id)
            statuses.append(CASE_STATUS_NOT_EXECUTED)
            continue
        statuses.append(score.status)
    if missing:
        blocks.append(
            P2Block(
                "missing_case",
                SEVERITY_UNKNOWN,
                f"{suite} 缺少 {len(missing)} 条计划内 case",
                {"suite": suite, "missing": missing[:10], "planned": len(ids)},
            )
        )
    passed = statuses.count(CASE_STATUS_PASS)
    failed = statuses.count(CASE_STATUS_FAIL)
    errors = statuses.count(CASE_STATUS_ERROR) + statuses.count(CASE_STATUS_SKIPPED_OCR)
    not_executed = statuses.count(CASE_STATUS_NOT_EXECUTED)
    executed = passed + failed
    if errors:
        blocks.append(
            P2Block(
                "case_error",
                SEVERITY_UNKNOWN,
                f"{suite} 有 {errors} 条 case 执行失败（error/skipped），不得计入正确数",
                {"suite": suite, "errors": errors},
            )
        )
    if not_executed:
        blocks.append(
            P2Block(
                "case_not_executed",
                SEVERITY_UNKNOWN,
                f"{suite} 有 {not_executed} 条 case 未执行",
                {"suite": suite, "not_executed": not_executed},
            )
        )
    ocr_statuses = [statuses[ids.index(case_id)] for case_id in ocr_ids if case_id in ids]
    ocr_executed = sum(1 for item in ocr_statuses if item in _EXECUTED_STATUSES)
    ocr_passed = ocr_statuses.count(CASE_STATUS_PASS)
    if ocr_ids:
        blocked_ocr = [
            case_id
            for case_id in ocr_ids
            if case_id in ids and statuses[ids.index(case_id)] not in _EXECUTED_STATUSES
        ]
        if blocked_ocr:
            blocks.append(
                P2Block(
                    "ocr_not_executed",
                    SEVERITY_UNKNOWN,
                    "OCR 题必须真的执行；不得静默跳过并算通过",
                    {"suite": suite, "case_ids": blocked_ocr, "planned": len(ocr_ids)},
                )
            )
    exact_executed_passed = sum(
        1
        for case_id in exact_ids
        if case_id in ids and statuses[ids.index(case_id)] == CASE_STATUS_PASS
    )
    exact_missing = [
        case_id
        for case_id in exact_ids
        if case_id in ids and statuses[ids.index(case_id)] != CASE_STATUS_PASS
    ]
    if exact_ids and exact_missing:
        blocks.append(
            P2Block(
                "exact_below_24_of_24",
                SEVERITY_HARD,
                "精确字段题必须 24/24（与 exact_value_contract 硬门禁同口径）",
                {"suite": suite, "missing": exact_missing[:10], "passed": exact_executed_passed},
            )
        )
    if executed and passed < min_pass:
        blocks.append(
            P2Block(
                "suite_below_threshold",
                SEVERITY_QUALITY,
                f"{suite} 通过数 {passed} < 门槛 {min_pass}",
                {"suite": suite, "passed": passed, "min_pass": min_pass, "executed": executed},
            )
        )
    if len(ids) != len(set(ids)):
        raise P2ScoringError("suite_ids_duplicated", suite)
    tally = P2SuiteTally(
        suite=suite,
        planned=len(ids),
        executed=executed,
        scored=passed + failed,
        passed=passed,
        failed=failed,
        errors=errors,
        not_executed=not_executed,
        skipped=errors,
        ocr_planned=len(ocr_ids),
        ocr_executed=ocr_executed,
        ocr_passed=ocr_passed,
        exact_planned=len(exact_ids),
        exact_passed=exact_executed_passed,
        required_passed=(
            not missing
            and not errors
            and not not_executed
            and passed >= min_pass
            and (not exact_ids or exact_executed_passed == len(exact_ids))
            and (not ocr_ids or ocr_executed == len(ocr_ids))
        ),
    )
    return tally, blocks


def score_public_suites(
    scores: Iterable[P2CaseScore],
    *,
    run_id: str | None = None,
    config_hash: str | None = None,
) -> P2PublicScorecard:
    """汇总公开控制矩阵；分母固定，缺题/多题/error/未执行/OCR 跳过都不放行。

    C1：矩阵的执行模式/真实调用数由逐题打分派生（同一 run 内必须一致，混用即报错）；
    空输入时保守记 ``local_mock``/0——不因为"没数据"就默认成真实或默认成 mock 以外的值。
    """
    by_id: dict[str, P2CaseScore] = {}
    blocks: list[P2Block] = []
    for score in scores:
        if not isinstance(score, P2CaseScore):
            raise P2ScoringError("score_invalid", "score_public_suites 只接受 P2CaseScore")
        if score.case_id in by_id:
            blocks.append(
                P2Block(
                    "duplicate_case",
                    SEVERITY_HARD,
                    f"case {score.case_id} 出现多次评分",
                    {"case_id": score.case_id},
                )
            )
            continue
        by_id[score.case_id] = score

    known = set(P2_B0_IDS) | set(P2_NEGATIVE_IDS) | set(P2_BOUNDARY_IDS) | set(P2_UPDATE_DELETE_IDS)
    unexpected = sorted(set(by_id) - known)
    if unexpected:
        blocks.append(
            P2Block(
                "unexpected_case",
                SEVERITY_UNKNOWN,
                "出现计划外的 case（分母不可信）",
                {"case_ids": unexpected[:10]},
            )
        )

    b0, b0_blocks = _tally(
        "b0",
        P2_B0_IDS,
        by_id,
        min_pass=P2_B0_MIN_PASS,
        exact_ids=P2_B0_EXACT_IDS,
        ocr_ids=P2_B0_OCR_IDS,
    )
    negative, negative_blocks = _tally(
        "negative", P2_NEGATIVE_IDS, by_id, min_pass=P2_NEGATIVE_TOTAL
    )
    boundary, boundary_blocks = _tally(
        "boundary", P2_BOUNDARY_IDS, by_id, min_pass=P2_BOUNDARY_TOTAL
    )
    update_delete, update_delete_blocks = _tally(
        "update_delete", P2_UPDATE_DELETE_IDS, by_id, min_pass=P2_UPDATE_DELETE_TOTAL
    )
    blocks.extend(b0_blocks)
    blocks.extend(negative_blocks)
    blocks.extend(boundary_blocks)
    blocks.extend(update_delete_blocks)
    suites = MappingProxyType(
        {
            "b0": b0,
            "negative": negative,
            "boundary": boundary,
            "update_delete": update_delete,
        }
    )
    modes = {score.execution_mode for score in by_id.values()}
    if len(modes) > 1:
        raise P2ScoringError(
            "execution_mode_mixed", f"同一张公开矩阵混用执行模式 {sorted(modes)}"
        )
    mode = next(iter(modes), EXECUTION_MODE_LOCAL_MOCK)
    return P2PublicScorecard(
        suites=suites,
        blocks=tuple(blocks),
        execution_mode=mode,
        real_calls=sum(score.real_calls for score in by_id.values()),
        run_id=run_id,
        config_hash=config_hash,
    )


# --------------------------------------------------------------------------- #
# H2：只聚合（不含 case_id / 题干 / 回答）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class P2HoldoutCaseScore:
    """H2 单题结论：只在受限进程内存里出现，不落盘、不导出。"""

    case_id: str
    stratum: str
    status: str
    hard_failure: str | None = None

    def __post_init__(self) -> None:
        if not str(self.case_id).strip():
            raise P2ScoringError("case_id_missing", "H2 case_id 不能为空")
        if self.status not in _P2_STATUSES:
            raise P2ScoringError("case_status_invalid", repr(self.status))
        if self.hard_failure is not None and self.hard_failure not in P2_HOLDOUT_HARD_FAILURE_KINDS:
            raise P2ScoringError("hard_failure_kind_invalid", repr(self.hard_failure))
        if self.hard_failure is not None and self.status == CASE_STATUS_PASS:
            raise P2ScoringError(
                "hard_failure_inconsistent", f"{self.case_id}: 通过题不能同时记硬失败"
            )


@dataclass(frozen=True)
class P2HoldoutScorecard:
    """H2 聚合结果：只有计数与分层通过数，没有 case_id / 题干 / 回答。"""

    total: int
    executed: int
    errors: int
    passed: int
    failed: int
    hard_failures: int
    hard_failures_by_kind: Mapping[str, int]
    by_stratum: Mapping[str, Mapping[str, int]]
    min_pass: int
    hard_failures_max: int
    thresholds_approved: bool
    blocks: tuple[P2Block, ...] = ()
    detail_export: bool = False
    #: C1：执行模式/真实调用数由调用方从 run 上下文显式传入（默认保守 local_mock/0）。
    execution_mode: str = EXECUTION_MODE_LOCAL_MOCK
    real_calls: int = 0
    #: C4：该聚合出自哪个 run（门禁据此核对绑定）。
    run_id: str | None = None
    #: T206-PRE：该聚合所属 run 的绑定摘要（缺失 → 门禁按 unknown 处理）。
    config_hash: str | None = None

    def __post_init__(self) -> None:
        _execution_mark(self.execution_mode, self.real_calls, owner="holdout scorecard")
        if self.config_hash is not None and not str(self.config_hash).strip():
            raise P2ScoringError("config_hash_invalid", "holdout scorecard 的 config_hash 不能为空字符串")

    @property
    def threshold_met(self) -> bool:
        return self.total == P2_HOLDOUT_TOTAL and self.passed >= self.min_pass

    @property
    def release_ready(self) -> bool:
        return (
            self.thresholds_approved
            and not self.blocks
            and self.threshold_met
            and self.hard_failures <= self.hard_failures_max
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": P2_SCORING_SCHEMA_VERSION,
            "total": int(self.total),
            "executed": int(self.executed),
            "errors": int(self.errors),
            "passed": int(self.passed),
            "failed": int(self.failed),
            "min_pass": int(self.min_pass),
            "threshold_met": bool(self.threshold_met),
            "hard_failures": int(self.hard_failures),
            "hard_failures_max": int(self.hard_failures_max),
            "hard_failures_by_kind": dict(self.hard_failures_by_kind),
            "by_stratum": {name: dict(counts) for name, counts in self.by_stratum.items()},
            "thresholds_approved": bool(self.thresholds_approved),
            "detail_export": False,
            "blocks": [item.to_dict() for item in self.blocks],
            "release_ready": bool(self.release_ready),
            "execution_mode": self.execution_mode,
            "real_calls": int(self.real_calls),
            "run_id": self.run_id,
            "config_hash": self.config_hash,
        }
        _assert_no_holdout_detail(payload)
        return payload


def _assert_no_holdout_detail(payload: Mapping[str, Any]) -> None:
    """防御：聚合产物不得含 case_id / 题面 / 回答字段（泄漏即报错，不静默）。"""
    forbidden = ("case_id", "question", "text", "answer", "reference_answer", "labels")
    stack: list[Any] = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, Mapping):
            for key, value in item.items():
                if str(key) in forbidden:
                    raise P2ScoringError("holdout_detail_leak", f"聚合产物含明细字段 {key!r}")
                stack.append(value)
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
        elif isinstance(item, str) and item.startswith("H2-"):
            raise P2ScoringError("holdout_detail_leak", "聚合产物含 H2 case_id")


def aggregate_holdout(
    scores: Sequence[P2HoldoutCaseScore],
    *,
    min_pass: int = P2_HOLDOUT_MIN_PASS,
    hard_failures_max: int = P2_HOLDOUT_MAX_HARD_FAILURES,
    thresholds_approved: bool = False,
    expected_strata: Mapping[str, int] | None = None,
    execution_mode: str = EXECUTION_MODE_LOCAL_MOCK,
    real_calls: int = 0,
    run_id: str | None = None,
    config_hash: str | None = None,
) -> P2HoldoutScorecard:
    """只把逐题 pass/fail 折成计数；不返回、不记录任何单题信息。"""
    strata_expected = dict(expected_strata or P2_HOLDOUT_STRATA)
    scores = tuple(scores)
    for item in scores:
        if not isinstance(item, P2HoldoutCaseScore):
            raise P2ScoringError("holdout_score_invalid", "aggregate_holdout 只接受 P2HoldoutCaseScore")
    total = len(scores)
    passed = sum(1 for item in scores if item.status == CASE_STATUS_PASS)
    failed = sum(1 for item in scores if item.status == CASE_STATUS_FAIL)
    errors = total - passed - failed
    hard_by_kind: dict[str, int] = {kind: 0 for kind in P2_HOLDOUT_HARD_FAILURE_KINDS}
    for item in scores:
        if item.hard_failure:
            hard_by_kind[item.hard_failure] = hard_by_kind.get(item.hard_failure, 0) + 1
    strata_counts: dict[str, dict[str, int]] = {}
    for item in scores:
        bucket = strata_counts.setdefault(str(item.stratum), {"total": 0, "passed": 0, "failed": 0, "errors": 0})
        bucket["total"] += 1
        if item.status == CASE_STATUS_PASS:
            bucket["passed"] += 1
        elif item.status == CASE_STATUS_FAIL:
            bucket["failed"] += 1
        else:
            bucket["errors"] += 1

    blocks: list[P2Block] = []
    if total != P2_HOLDOUT_TOTAL:
        blocks.append(
            P2Block(
                "holdout_sample_missing",
                SEVERITY_UNKNOWN,
                f"H2 样本数 {total} != 冻结题数 {P2_HOLDOUT_TOTAL}",
                {"total": total, "expected": P2_HOLDOUT_TOTAL},
            )
        )
    actual_strata = {name: counts["total"] for name, counts in strata_counts.items()}
    if actual_strata != strata_expected:
        blocks.append(
            P2Block(
                "holdout_strata_mismatch",
                SEVERITY_UNKNOWN,
                "H2 分层计数与冻结分层不一致",
                {
                    "actual": actual_strata,
                    "expected": strata_expected,
                },
            )
        )
    if errors:
        blocks.append(
            P2Block(
                "holdout_case_error",
                SEVERITY_UNKNOWN,
                "H2 存在未执行/error 题，不得并入正确数",
                {"errors": errors},
            )
        )
    hard_total = sum(hard_by_kind.values())
    if hard_total > hard_failures_max:
        blocks.append(
            P2Block(
                "holdout_hard_failure",
                SEVERITY_HARD,
                f"H2 硬失败 {hard_total} > 上限 {hard_failures_max}",
                {"hard_failures": hard_total, "max": hard_failures_max},
            )
        )
    if passed < min_pass:
        blocks.append(
            P2Block(
                "holdout_below_threshold",
                SEVERITY_QUALITY,
                f"H2 通过 {passed} < 门槛 {min_pass}/{P2_HOLDOUT_TOTAL}",
                {"passed": passed, "min_pass": min_pass},
            )
        )
    if not thresholds_approved:
        blocks.append(
            P2Block(
                "holdout_threshold_unapproved",
                SEVERITY_UNKNOWN,
                "H2 阈值/门禁版本未审批（gate_v0_3 初始 unapproved），不得按通过处理",
                {"gate_status": "unapproved"},
            )
        )
    return P2HoldoutScorecard(
        total=total,
        executed=passed + failed,
        errors=errors,
        passed=passed,
        failed=failed,
        hard_failures=hard_total,
        hard_failures_by_kind=MappingProxyType(hard_by_kind),
        by_stratum=MappingProxyType(
            {name: MappingProxyType(counts) for name, counts in strata_counts.items()}
        ),
        min_pass=int(min_pass),
        hard_failures_max=int(hard_failures_max),
        thresholds_approved=bool(thresholds_approved),
        blocks=tuple(blocks),
        execution_mode=execution_mode,
        real_calls=int(real_calls),
        run_id=run_id,
        config_hash=config_hash,
    )


# --------------------------------------------------------------------------- #
# P2 门禁配置（gate_v0_3；初始 unapproved）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class P2Standards:
    """主人已批准的质量目标（评测口径，不是已批准的 gate 阈值）。"""

    b0_total: int
    b0_min_pass: int
    b0_exact_total: int
    b0_exact_min_pass: int
    b0_ocr_total: int
    negative_total: int
    boundary_total: int
    update_delete_total: int
    holdout_total: int
    holdout_min_pass: int
    holdout_hard_failures_max: int
    holdout_strata: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "b0": {
                "total": self.b0_total,
                "min_pass": self.b0_min_pass,
                "exact_total": self.b0_exact_total,
                "exact_min_pass": self.b0_exact_min_pass,
                "ocr_total": self.b0_ocr_total,
            },
            "negative": {"total": self.negative_total},
            "boundary": {"total": self.boundary_total},
            "update_delete": {"total": self.update_delete_total},
            "holdout": {
                "total": self.holdout_total,
                "min_pass": self.holdout_min_pass,
                "hard_failures_max": self.holdout_hard_failures_max,
                "strata": dict(self.holdout_strata),
            },
        }


@dataclass(frozen=True)
class P2GateConfig:
    """gate 配置 + P2 标准块；旧版本配置（v0.1/v0.2）可以加载，但 standards=None。"""

    config: GateConfig
    standards: P2Standards | None
    raw: Mapping[str, Any]

    @property
    def gate_version(self) -> str:
        return self.config.gate_version

    @property
    def schema_version(self) -> str:
        return self.config.schema_version

    @property
    def status(self) -> str:
        return self.config.status

    @property
    def config_hash(self) -> str:
        return self.config.config_hash

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_version": self.gate_version,
            "schema_version": self.schema_version,
            "status": self.status,
            "config_hash": self.config_hash,
            "standards": None if self.standards is None else self.standards.to_dict(),
        }


def _require_int(payload: Mapping[str, Any], key: str, name: str) -> int:
    if not isinstance(payload, Mapping):
        raise P2ScoringError("p2_standards_invalid", f"{name} 必须是对象")
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise P2ScoringError("p2_standards_invalid", f"{name}.{key} 必须是整数，收到 {value!r}")
    return value


def _parse_standards(payload: Any) -> P2Standards:
    if not isinstance(payload, Mapping):
        raise P2ScoringError("p2_standards_missing", "gate_v0_3 必须声明 p2_standards 块")
    b0 = payload.get("b0")
    negative = payload.get("negative")
    boundary = payload.get("boundary")
    update_delete = payload.get("update_delete")
    holdout = payload.get("holdout")
    if not isinstance(holdout, Mapping):
        raise P2ScoringError("p2_standards_invalid", "p2_standards.holdout 必须是对象")
    strata = holdout.get("strata")
    if not isinstance(strata, Mapping):
        raise P2ScoringError("p2_standards_invalid", "p2_standards.holdout.strata 必须是对象")
    standards = P2Standards(
        b0_total=_require_int(b0, "total", "p2_standards.b0"),
        b0_min_pass=_require_int(b0, "min_pass", "p2_standards.b0"),
        b0_exact_total=_require_int(b0, "exact_total", "p2_standards.b0"),
        b0_exact_min_pass=_require_int(b0, "exact_min_pass", "p2_standards.b0"),
        b0_ocr_total=_require_int(b0, "ocr_total", "p2_standards.b0"),
        negative_total=_require_int(negative, "total", "p2_standards.negative"),
        boundary_total=_require_int(boundary, "total", "p2_standards.boundary"),
        update_delete_total=_require_int(update_delete, "total", "p2_standards.update_delete"),
        holdout_total=_require_int(holdout, "total", "p2_standards.holdout"),
        holdout_min_pass=_require_int(holdout, "min_pass", "p2_standards.holdout"),
        holdout_hard_failures_max=_require_int(holdout, "hard_failures_max", "p2_standards.holdout"),
        holdout_strata=MappingProxyType({str(k): _require_int(strata, str(k), "p2_standards.holdout.strata") for k in strata}),
    )
    expected = P2Standards(
        b0_total=P2_B0_TOTAL,
        b0_min_pass=P2_B0_MIN_PASS,
        b0_exact_total=P2_B0_EXACT_TOTAL,
        b0_exact_min_pass=P2_B0_EXACT_MIN_PASS,
        b0_ocr_total=P2_B0_OCR_TOTAL,
        negative_total=P2_NEGATIVE_TOTAL,
        boundary_total=P2_BOUNDARY_TOTAL,
        update_delete_total=P2_UPDATE_DELETE_TOTAL,
        holdout_total=P2_HOLDOUT_TOTAL,
        holdout_min_pass=P2_HOLDOUT_MIN_PASS,
        holdout_hard_failures_max=P2_HOLDOUT_MAX_HARD_FAILURES,
        holdout_strata=P2_HOLDOUT_STRATA,
    )
    if standards.to_dict() != expected.to_dict():
        raise P2ScoringError(
            "p2_standards_mismatch",
            "gate_v0_3 的 p2_standards 与冻结口径不一致（不允许用改配置的方式放宽分母/阈值）",
        )
    return standards


def load_p2_gate_config(path: Path | str | None = None) -> P2GateConfig:
    """加载 P2 门禁配置；任何读/解析失败都抛错（fail closed，不默认通过）。"""
    target = Path(path) if path is not None else P2_GATE_CONFIG_PATH
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise P2ScoringError("gate_config_unreadable", f"{target}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise P2ScoringError("gate_config_invalid", f"{target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise P2ScoringError("gate_config_invalid", "gate 配置必须是 JSON 对象")
    try:
        config = load_gate_config(target)
    except ValueError as exc:
        raise P2ScoringError("gate_config_invalid", str(exc)) from exc
    standards = None
    if config.schema_version == CONFIG_SCHEMA_VERSION_V0_3:
        standards = _parse_standards(payload.get("p2_standards"))
    return P2GateConfig(config=config, standards=standards, raw=dict(payload))


def _severity_exit_code(blocks: Sequence[P2Block]) -> int:
    severities = {item.severity for item in blocks}
    if SEVERITY_HARD in severities:
        return EXIT_HARD_FAILURE
    if SEVERITY_UNKNOWN in severities:
        return EXIT_UNKNOWN
    if SEVERITY_QUALITY in severities:
        return EXIT_QUALITY_REGRESSION
    return EXIT_PASS


@dataclass(frozen=True)
class P2GateDecision:
    """一次 P2 放行判定：执行退出码与质量门禁码**分开**记录，不互相冒充。"""

    gate_version: str
    config_hash: str
    config_status: str
    execution_exit_code: int
    quality_exit_code: int
    decision: str
    release_allowed: bool
    blocks: tuple[P2Block, ...]
    hard_gate_status: Mapping[str, str]
    hard_failures: tuple[str, ...]
    hard_gate_exit_code: int | None
    public: Mapping[str, Any] | None = None
    holdout: Mapping[str, Any] | None = None
    notes: tuple[str, ...] = ()
    #: C1(2b)：执行模式与真实调用次数（默认 local_mock/0；live 必须显式传入且与 scorecard 一致）。
    execution_mode: str = EXECUTION_MODE_LOCAL_MOCK
    real_calls: int = 0
    #: C4：本判定所依据的 run_id（来自 run_manifest，不能由调用方随口给另一个）。
    run_id: str | None = None
    #: T206-PRE：本判定所依据的**绑定摘要**（run_manifest.config_hash）；
    #: 与 ``config_hash``（gate 配置自己的 hash）语义不同，不可混用。
    binding_config_hash: str | None = None

    def __post_init__(self) -> None:
        _execution_mark(self.execution_mode, self.real_calls, owner="gate decision")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": P2_SCORING_SCHEMA_VERSION,
            "gate_version": self.gate_version,
            "config_hash": self.config_hash,
            "config_status": self.config_status,
            "execution_exit_code": int(self.execution_exit_code),
            "quality_exit_code": int(self.quality_exit_code),
            "decision": self.decision,
            "release_allowed": bool(self.release_allowed),
            "hard_gate_status": dict(self.hard_gate_status),
            "hard_failures": list(self.hard_failures),
            "hard_gate_exit_code": None if self.hard_gate_exit_code is None else int(self.hard_gate_exit_code),
            "blocks": [item.to_dict() for item in self.blocks],
            "public": None if self.public is None else dict(self.public),
            "holdout": None if self.holdout is None else dict(self.holdout),
            "notes": list(self.notes),
            "execution_mode": self.execution_mode,
            "real_calls": int(self.real_calls),
            "run_id": self.run_id,
            "binding_config_hash": self.binding_config_hash,
        }


def evaluate_p2_gate(
    *,
    config: P2GateConfig,
    run_manifest: Mapping[str, Any] | None,
    run_summary: Mapping[str, Any] | None,
    hard_gate: GateResult | None,
    public: P2PublicScorecard | None,
    holdout: P2HoldoutScorecard | None,
    citation_evidence_complete: bool = False,
    execution_mode: str | None = None,
    real_calls: int | None = None,
    run_id: str | None = None,
) -> P2GateDecision:
    """P2 放行判定：8 硬门禁 + 配置绑定 + 分母 + H2；任何未知都不放行。

    - 执行退出码只看 run 是否成功完成（run_summary.status/stop_code）；
    - 质量门禁码只看「配置/证据/分母/硬门禁」这些质量侧证据；两者分开记录；
    - gate_v0_3 初始 unapproved → gate_config_unapproved（unknown，exit 3）。
    """
    if not isinstance(config, P2GateConfig):
        raise P2ScoringError("gate_config_invalid", "evaluate_p2_gate 需要 P2GateConfig")
    blocks: list[P2Block] = []
    notes: list[str] = []

    # 1) 配置身份：旧 gate / 同版本改配置 / 未审批
    if (
        config.schema_version != CONFIG_SCHEMA_VERSION_V0_3
        or config.gate_version != GATE_VERSION_V0_3
        or config.standards is None
    ):
        blocks.append(
            P2Block(
                "legacy_gate_config",
                SEVERITY_UNKNOWN,
                "P2 判定只接受 mktkb.gate.v0.3；旧 gate 配置不得复用",
                {"gate_version": config.gate_version, "schema_version": config.schema_version},
            )
        )
    if str(config.status) != "approved":
        blocks.append(
            P2Block(
                "gate_config_unapproved",
                SEVERITY_UNKNOWN,
                "gate_v0_3 未审批：质量阈值未获批，不得放行",
                {"status": config.status, "config_hash": config.config_hash},
            )
        )

    # 2) run 身份绑定（gate_version / config_hash / scope / mode）
    manifest = run_manifest if isinstance(run_manifest, Mapping) else {}
    if not manifest:
        blocks.append(
            P2Block(
                "run_manifest_missing",
                SEVERITY_UNKNOWN,
                "缺少 run_manifest，无法核对 gate 绑定与作用域",
                {},
            )
        )
    else:
        # T206-PRE：run 身份/绑定摘要必须显式给出（R2-F-R2-3：缺 run_id 不得"静默可放行"）。
        if not str(manifest.get("run_id") or "").strip():
            blocks.append(
                P2Block(
                    "run_binding_missing",
                    SEVERITY_UNKNOWN,
                    "run_manifest 没有 run_id：无法证明 scorecard/判定属于同一 run，不得放行",
                    {},
                )
            )
        if not str(manifest.get("config_hash") or "").strip():
            blocks.append(
                P2Block(
                    "config_hash_unbound",
                    SEVERITY_UNKNOWN,
                    "run_manifest 没有 config_hash：无法证明 dataset/pipeline/索引/provider/gate 同源",
                    {},
                )
            )
        if str(manifest.get("scope") or "") != P2_RUN_SCOPE or str(manifest.get("mode") or "") != P2_RUN_MODE:
            blocks.append(
                P2Block(
                    "cross_scope_run",
                    SEVERITY_UNKNOWN,
                    "run 的 mode/scope 不是 P2 end_to_end，不得用 P2 门禁放行",
                    {"mode": manifest.get("mode"), "scope": manifest.get("scope")},
                )
            )
        manifest_gate = str(manifest.get("gate_version") or "").strip()
        if not manifest_gate:
            blocks.append(
                P2Block(
                    "gate_config_unbound",
                    SEVERITY_UNKNOWN,
                    "run_manifest 没有记录 gate_version，无法证明与配置同版本",
                    {},
                )
            )
        elif manifest_gate != config.gate_version:
            blocks.append(
                P2Block(
                    "gate_version_mismatch",
                    SEVERITY_UNKNOWN,
                    "run 的 gate_version 与配置不一致（旧 gate 产物不得复用）",
                    {"manifest": manifest_gate, "config": config.gate_version},
                )
            )
        manifest_hash = str(manifest.get("gate_config_hash") or "").strip()
        if not manifest_hash:
            blocks.append(
                P2Block(
                    "gate_config_unbound",
                    SEVERITY_UNKNOWN,
                    "run_manifest 没有记录 gate_config_hash，无法证明没有同版本改配置",
                    {},
                )
            )
        elif manifest_hash != config.config_hash:
            blocks.append(
                P2Block(
                    "gate_config_changed_same_version",
                    SEVERITY_HARD,
                    "同一 gate_version 下的配置已变化（阈值/口径不可比），不得放行",
                    {"manifest": manifest_hash, "config": config.config_hash},
                )
            )

    # 3) run 完整性
    execution_ok = False
    if not isinstance(run_summary, Mapping):
        blocks.append(
            P2Block(
                "run_summary_missing",
                SEVERITY_UNKNOWN,
                "缺少 run summary，无法证明 run 完整",
                {},
            )
        )
    else:
        status = str(run_summary.get("status") or "")
        stop_code = run_summary.get("stop_code")
        cases = run_summary.get("cases") if isinstance(run_summary.get("cases"), Mapping) else {}
        execution_ok = status == "succeeded" and not stop_code
        if not execution_ok:
            blocks.append(
                P2Block(
                    "incomplete_run",
                    SEVERITY_UNKNOWN,
                    "run 未成功完成（status/stop_code），不得放行",
                    {"status": status, "stop_code": stop_code},
                )
            )
        if int(cases.get("not_executed") or 0) or int(cases.get("with_error") or 0):
            blocks.append(
                P2Block(
                    "incomplete_run",
                    SEVERITY_UNKNOWN,
                    "run 有未执行/error 的 case，分母不完整",
                    {
                        "not_executed": int(cases.get("not_executed") or 0),
                        "with_error": int(cases.get("with_error") or 0),
                    },
                )
            )

    # 4) 8 项硬门禁
    gate_status: dict[str, str] = {gate_id: GATE_STATUS_NOT_EVALUATED for gate_id in HARD_GATE_IDS}
    hard_failures: tuple[str, ...] = ()
    hard_exit: int | None = None
    if hard_gate is None:
        blocks.append(
            P2Block(
                "hard_gate_missing",
                SEVERITY_UNKNOWN,
                "没有 8 项硬门禁结果，无法放行",
                {},
            )
        )
    elif not isinstance(hard_gate, GateResult):
        raise P2ScoringError("hard_gate_invalid", "hard_gate 必须是 GateResult")
    else:
        gate_status = {key: str(value) for key, value in hard_gate.gate_status.items()}
        hard_failures = tuple(hard_gate.hard_failures)
        hard_exit = int(hard_gate.exit_code)
        if hard_failures or hard_gate.exit_code == EXIT_HARD_FAILURE:
            blocks.append(
                P2Block(
                    "hard_gate_failed",
                    SEVERITY_HARD,
                    "硬门禁失败（不可豁免）",
                    {"hard_failures": list(hard_failures), "exit_code": int(hard_gate.exit_code)},
                )
            )
        if hard_gate.exit_code == 4:
            blocks.append(
                P2Block(
                    "live_unauthorized",
                    SEVERITY_HARD,
                    "live 未授权（gate 自身拒绝）",
                    {"exit_code": 4},
                )
            )
        if hard_gate.unknowns:
            blocks.append(
                P2Block(
                    "hard_gate_unknown",
                    SEVERITY_UNKNOWN,
                    "硬门禁存在 unknown（数据/配置/gold 不可用或样本不足）",
                    {"unknowns": len(hard_gate.unknowns)},
                )
            )
        not_evaluated = [key for key, value in gate_status.items() if value == GATE_STATUS_NOT_EVALUATED]
        if not_evaluated:
            blocks.append(
                P2Block(
                    "hard_gate_not_evaluated",
                    SEVERITY_UNKNOWN,
                    "有硬门禁未评估（不是 not_applicable）",
                    {"gates": not_evaluated},
                )
            )
        applicable = [key for key, value in gate_status.items() if value != GATE_STATUS_NOT_APPLICABLE]
        if not applicable:
            blocks.append(
                P2Block(
                    "hard_gates_not_applicable",
                    SEVERITY_UNKNOWN,
                    "8 项硬门禁全部 not_applicable：没有任何可判定证据，不能算通过",
                    {},
                )
            )
    if not citation_evidence_complete:
        blocks.append(
            P2Block(
                "citation_evidence_unavailable",
                SEVERITY_UNKNOWN,
                "P2 产物没有本轮检索证据 id，无法证明引用落在 evidence 内（T206 需补采集）",
                {},
            )
        )

    # 5) 公开分母 + H2 聚合
    public_payload = None
    if public is None:
        blocks.append(
            P2Block(
                "public_scorecard_missing",
                SEVERITY_UNKNOWN,
                "缺少公开控制矩阵（40/24/N8/C6/U10），不得放行",
                {},
            )
        )
    else:
        if not isinstance(public, P2PublicScorecard):
            raise P2ScoringError("public_scorecard_invalid", "public 必须是 P2PublicScorecard")
        blocks.extend(public.blocks)
        public_payload = public.to_dict()
    holdout_payload = None
    if holdout is None:
        blocks.append(
            P2Block(
                "holdout_missing",
                SEVERITY_UNKNOWN,
                "缺少 H2 聚合结果，不得放行",
                {},
            )
        )
    else:
        if not isinstance(holdout, P2HoldoutScorecard):
            raise P2ScoringError("holdout_invalid", "holdout 必须是 P2HoldoutScorecard")
        blocks.extend(holdout.blocks)
        holdout_payload = holdout.to_dict()

    # 5b) C1/C4：执行模式、真实调用数与 run 身份必须与 scorecard/manifest 对得上
    cards = [("public", public), ("holdout", holdout)]
    card_modes = {name: card.execution_mode for name, card in cards if card is not None}
    if len(set(card_modes.values())) > 1:
        raise P2ScoringError(
            "execution_mode_mismatch", f"public/holdout 执行模式不一致 {card_modes}"
        )
    derived_mode = next(iter(card_modes.values()), EXECUTION_MODE_LOCAL_MOCK)
    derived_calls = sum(int(card.real_calls) for _, card in cards if card is not None)
    if execution_mode is not None and str(execution_mode) != derived_mode:
        raise P2ScoringError(
            "execution_mode_mismatch",
            f"调用方声明 execution_mode={execution_mode!r}，scorecard 却是 {derived_mode!r}",
        )
    if real_calls is not None and int(real_calls) != derived_calls:
        raise P2ScoringError(
            "real_calls_mismatch",
            f"调用方声明 real_calls={real_calls}，scorecard 合计 {derived_calls}",
        )
    manifest_run_id = str(manifest.get("run_id") or "").strip()
    manifest_binding_hash = str(manifest.get("config_hash") or "").strip()
    if run_id is not None and manifest_run_id and str(run_id) != manifest_run_id:
        raise P2ScoringError(
            "run_id_mismatch", f"run_id={run_id!r} 与 run_manifest.run_id={manifest_run_id!r} 不一致"
        )
    bound_run_id = str(run_id) if run_id is not None else (manifest_run_id or None)
    for name, card in cards:
        if card is None or card.run_id is None:
            continue
        if manifest_run_id and str(card.run_id) != manifest_run_id:
            blocks.append(
                P2Block(
                    "run_binding_mismatch",
                    SEVERITY_UNKNOWN,
                    f"{name} scorecard 不是本次 run 的产物，分母/阈值不可比，不得放行",
                    {"manifest_run_id": manifest_run_id, "scorecard_run_id": str(card.run_id)},
                )
            )

    # 5c) T206-PRE + R1：scorecard 声明的绑定摘要必须与本 run 的 config_hash 一致；
    #     **未声明也算不通过**（fail-closed）——manifest 有绑定摘要、scorecard 却没有，
    #     就无法证明这张分母/阈值出自同一份 dataset/pipeline/索引/provider/gate。
    #     manifest 自己也缺摘要时已在上文记 config_hash_unbound，这里不重复记。
    for name, card in cards:
        if card is None:
            continue
        if card.config_hash is None:
            if manifest_binding_hash:
                blocks.append(
                    P2Block(
                        "config_hash_unbound",
                        SEVERITY_UNKNOWN,
                        f"{name} scorecard 未声明 config_hash：无法证明与本次 run 同一份绑定配置",
                        {"manifest_config_hash": manifest_binding_hash},
                    )
                )
            continue
        declared = str(card.config_hash).strip()
        if not manifest_binding_hash:
            blocks.append(
                P2Block(
                    "config_hash_unbound",
                    SEVERITY_UNKNOWN,
                    f"{name} scorecard 声明了绑定摘要，但 run_manifest 没有 config_hash",
                    {"scorecard_config_hash": declared},
                )
            )
        elif declared != manifest_binding_hash:
            blocks.append(
                P2Block(
                    "config_hash_binding_mismatch",
                    SEVERITY_UNKNOWN,
                    f"{name} scorecard 来自另一份绑定配置（dataset/pipeline/索引/provider/gate 不同源）",
                    {"manifest_config_hash": manifest_binding_hash, "scorecard_config_hash": declared},
                )
            )

    # 6) 退出码：执行/质量分开；执行未成功也不能把质量判成通过
    execution_exit_code = EXIT_PASS if execution_ok else EXIT_UNKNOWN
    quality_exit_code = _severity_exit_code(blocks)
    if not execution_ok and quality_exit_code == EXIT_PASS:
        quality_exit_code = EXIT_UNKNOWN
    release_allowed = bool(execution_ok and not blocks)
    if release_allowed:
        decision = DECISION_PASS
    elif any(item.severity == SEVERITY_HARD for item in blocks):
        decision = DECISION_BLOCKED
    else:
        decision = DECISION_UNKNOWN
    if config.status != "approved":
        notes.append("gate_v0_3 初始 unapproved：本判定只报告观测值，不构成放行")
    return P2GateDecision(
        gate_version=config.gate_version,
        config_hash=config.config_hash,
        config_status=str(config.status),
        execution_exit_code=execution_exit_code,
        quality_exit_code=quality_exit_code,
        decision=decision,
        release_allowed=release_allowed,
        blocks=tuple(blocks),
        hard_gate_status=gate_status,
        hard_failures=hard_failures,
        hard_gate_exit_code=hard_exit,
        public=public_payload,
        holdout=holdout_payload,
        notes=tuple(notes),
        execution_mode=derived_mode,
        real_calls=derived_calls,
        run_id=bound_run_id,
        binding_config_hash=manifest_binding_hash or None,
    )


def evaluate_p2_hard_gates(
    run: RunResult,
    *,
    config: P2GateConfig,
    dataset_path: Path | str | None = None,
    require_trace: bool = True,
) -> GateResult:
    """8 项硬门禁（复用 gate.evaluate_gate；质量层留给公开矩阵，不混用阈值）。"""
    if not isinstance(config, P2GateConfig):
        raise P2ScoringError("gate_config_invalid", "evaluate_p2_hard_gates 需要 P2GateConfig")
    return evaluate_gate(
        run,
        None,
        config.config,
        require_trace=require_trace,
        dataset_path=dataset_path,
        quality=False,
    )


# --------------------------------------------------------------------------- #
# P2 行 / RunResult 桥接（让既有 gate 能读 P2 产物）
# --------------------------------------------------------------------------- #


def build_gate_rows(
    cases: Sequence[CaseSpec],
    scored: Sequence[P2ScoredCase],
    *,
    document_codes: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], ...]:
    """把 P2 逐题打分转成 gate 能读的 cases.jsonl 行（P1 同键）。

    error / not_executed 一律写 status="error" + error.code：gate 会把它们排除在
    evaluated_count 之外并记 case_error unknown —— 不静默当通过。
    """
    by_id = {item.score.case_id: item for item in scored}
    rows: list[dict[str, Any]] = []
    for case in cases:
        item = by_id.get(case.case_id)
        if item is None:
            item = P2ScoredCase(
                score=P2CaseScore(
                    case_id=case.case_id,
                    suite=str(case.suite),
                    stratum=str(case.stratum),
                    status=CASE_STATUS_NOT_EXECUTED,
                    requires_ocr=bool(case.requires_ocr),
                    planned_turns=max(1, len(case.turns)),
                    executed_turns=0,
                    issues=(P2IsolationIssue("case_not_executed", case.case_id),),
                )
            )
        score = item.score
        result = item.result
        outcome = item.outcome
        status = score.status
        if status in {CASE_STATUS_ERROR, CASE_STATUS_NOT_EXECUTED, CASE_STATUS_SKIPPED_OCR}:
            row_status = "error"
        else:
            row_status = status
        error = None
        if row_status == "error":
            code = score.issues[0].code if score.issues else "case_not_executed"
            detail = score.issues[0].detail if score.issues else ""
            error = {"code": str(code), "message": str(detail)}
        trace_id = (outcome.trace_id if outcome is not None else None) or (
            score.trace_ids[-1] if score.trace_ids else None
        )
        rows.append(
            {
                "case_id": case.case_id,
                "suite": str(case.suite),
                "status": row_status,
                "trace_id": trace_id,
                "previous_trace_id": None,
                "replayed": False,
                "checks": [dict(check) for check in score.checks],
                "metrics": dict(result.metrics) if result is not None else {},
                "refused": None if result is None else result.refused,
                "should_refuse": bool(case.should_refuse),
                "path": None if outcome is None else outcome.path,
                "latency_ms": None if result is None else result.latency_ms,
                "tokens_in": None if result is None else result.tokens_in,
                "tokens_out": None if result is None else result.tokens_out,
                "cost_cny": None if result is None else result.cost_cny,
                "duration_ms": 0,
                "turns_executed": int(score.executed_turns),
                "multi_turn_claimed": len(case.turns) > 1,
                "outcome": None if outcome is None else outcome_to_dict(outcome),
                "gold": None,
                "error": error,
                "turn_traces": [
                    {"turn": index, "trace_id": trace, "status": "ok"}
                    for index, trace in enumerate(score.trace_ids, start=1)
                ],
            }
        )
    return tuple(rows)


_GATE_MANIFEST_REQUIRED: tuple[str, ...] = (
    "run_id",
    "mode",
    "scope",
    "suite",
    "dataset_version",
    "dataset_sha256",
    "corpus_manifest_sha256",
    "business_date",
    "index_revision",
    "pipeline_version",
    "gate_version",
    "label_version",
    "created_at",
    "case_count",
    "config_hash",
)


def build_gate_run(
    *,
    run_dir: Path | str,
    manifest: Mapping[str, Any],
    cases: Sequence[CaseSpec],
    rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any] | None = None,
) -> RunResult:
    """用 P2 run 的身份字段构造 RunResult；缺字段 fail closed（不猜默认值）。"""
    if not isinstance(manifest, Mapping):
        raise P2ScoringError("run_manifest_invalid", "manifest 必须是对象")
    missing = [name for name in _GATE_MANIFEST_REQUIRED if manifest.get(name) in (None, "")]
    if missing:
        raise P2ScoringError("run_manifest_incomplete", f"manifest 缺少 {missing}")
    case_ids = [case.case_id for case in cases]
    row_ids = [str(row.get("case_id") or "") for row in rows]
    if case_ids != row_ids:
        raise P2ScoringError(
            "dataset_row_mismatch",
            f"cases={len(case_ids)} rows={len(row_ids)}；顺序/集合必须一致",
        )
    payload = {name: manifest[name] for name in _GATE_MANIFEST_REQUIRED}
    # gate 的 mode 是「执行环境」（local/replay/live），P2 的 mode 是「run 类型」
    # （end_to_end）。P2 的隔离应用 + Mock provider 就是 local 执行：显式映射，
    # 不做隐式放行；其它未知 mode 直接拒绝。
    raw_mode = str(payload.get("mode") or "")
    if raw_mode == P2_RUN_MODE:
        payload["mode"] = "local"
    elif raw_mode not in {"local", "replay"}:
        raise P2ScoringError(
            "gate_mode_unsupported", f"P2 run 的 mode={raw_mode!r} 无法映射到 gate 的 local/replay"
        )
    payload.setdefault("trace_store", str(manifest.get("trace_store") or "traces.sqlite3"))
    payload["dataset_path"] = str(manifest.get("dataset_path") or "")
    payload["case_count"] = int(manifest["case_count"])
    payload["index_revision"] = int(manifest["index_revision"])
    try:
        run_manifest = RunManifest(**payload)
    except (TypeError, ValueError) as exc:
        raise P2ScoringError("run_manifest_invalid", str(exc)) from exc
    return RunResult(
        manifest=run_manifest,
        out_dir=Path(run_dir),
        cases=tuple(rows),
        summary=dict(summary or {}),
        aborted=False,
    )
