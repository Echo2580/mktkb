"""T005：Replay / Local runner 与运行清单（P0 设计 §7.3 / §8.5 / §9）。

两种模式共用一个入口 :func:`run_suite`：

- ``local``：按 suite 装配**隔离索引**（``provider_mode="offline"``，确定性替身），对
  数据集逐条直接调用 ``RagIndex.ask``；每次执行写一条 ``mode=local`` 的 Trace。
- ``replay``：只读上一轮 local run 的 ``run_manifest.json`` + ``cases.jsonl``，
  重建 ``EvalOutcome`` 后重新打分；**不建索引、不写索引库、不调 provider**；
  每次重放写一条 ``replayed=True`` 的 Trace（Span 集合为空，复用 T003d 口径）。

产物（只写 ``out_dir``，生产默认 ``var/eval/runs/<run_id>/``）：

- ``run_manifest.json``：版本绑定字段（dataset/corpus/business_date/index_revision/
  pipeline_version/gate_version/mode/scope）；
- ``cases.jsonl``：一行一个 case，持久化 ``status/trace_id/checks``、**有序
  ``retrieved``** 与 citation 的 ``unit_ids``（由 chunk 真实归属 ``RagChunk.unit_ids``
  填充），以及本轮解析出的 gold unit 集合；
- ``summary.json``：逐 case 重聚合指标 + P0 单轮/分页/gold 口径声明。

fail closed 口径：

- ``record_code`` 不是解析键：gold 引用只有 ``record_code``（既无 ``unit_key`` 也无
  ``locator``）时在 runner 层直接标 ``error``，不静默扩为整文档 gold；
- OCR case 只标 ``skipped_requires_ocr``，不解析、不调用 provider、不进任何指标分母；
- 有 gold 的 case 在引用/检索存在时缺 ``unit_ids`` → 行 ``error``（replay 同样），
  不静默算 0；
- replay 必须显式给出 ``replay_from``；缺失时 ``ValueError``，不静默降级为 local。

P1 T108（holdout 防污染，设计 §4）：

- ``suite="holdout"`` 走 :func:`_run_local_holdout`：题目来自仓库导出（无答案），答案在
  运行时从 ``--holdout-labels`` / ``MKTKB_HOLDOUT_LABELS`` 读取；
- 默认只写 ``run_manifest.json`` + ``summary.json``（聚合），**不写** ``cases.jsonl``，
  且 trace 落在临时目录随运行删除；``--allow-holdout-details`` 才写逐题 + ``holdout_audit.json``；
- CI/门禁环境（``CI`` / ``GITHUB_ACTIONS`` / ``MKTKB_CI``）带 details 直接拒绝；
- holdout 只支持 ``mode="local"``；replay 需要源 run 的 ``cases.jsonl``，T108 不提供。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import MISSING, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Mapping, Sequence

from ..observability.contracts import GATE_SCHEMA_VERSION, TraceMode
from ..observability.store import TraceRepository
from ..observability.tracer import TraceContext, start_trace
from ..observability.versioning import (
    CONFIG_HASH_FIELDS,
    config_hash as _versioning_config_hash,
    pipeline_version as _pipeline_version,
)
from .corpus import (
    SUITES,
    Corpus,
    build_suite_index,
    default_corpus_dir,
    default_dataset_path,
    load_suite_corpus,
    offline_eval_config,
)
from .dataset import (
    DEFAULT_HOLDOUT_POLICY,
    HOLDOUT_QUESTIONS_PATH,
    HOLDOUT_SUITE,
    CaseSpec,
    HoldoutDataset,
    HoldoutError,
    HoldoutPolicy,
    ci_environment,
    dataset_version,
    load_cases,
    load_holdout_dataset,
)
from .gold import GoldUnresolved, ResolvedGold, ResolvedSource, resolve_case
from .scorers import (
    CaseCheck,
    CaseResult,
    EvalCitation,
    EvalFact,
    EvalOutcome,
    EvalRetrieved,
    aggregate_metrics,
    score_case,
)

__all__ = [
    "HOLDOUT_SUITE",
    "IDENTITY_FIELDS",
    "MANIFEST_SUITES",
    "MODES",
    "RunManifest",
    "RunResult",
    "run_suite",
]

PROJECT_ROOT = Path(__file__).resolve().parents[4]
RUNS_ROOT = PROJECT_ROOT / "var" / "eval" / "runs"
MODES = ("local", "replay")
#: ``run_manifest.suite`` 允许值：P0 三套 + P1 holdout（T108）。
MANIFEST_SUITES = frozenset(set(SUITES) | {HOLDOUT_SUITE})
TRACE_STORE_NAME = "traces.sqlite3"
HOLDOUT_OPERATOR_ENV = "MKTKB_HOLDOUT_OPERATOR"
HOLDOUT_LABELS_ENV = "MKTKB_HOLDOUT_LABELS"

#: PM 裁决（T004a 验收遗留）：N06/N11 是会话跟进题但数据集 turns 为空；
#: P0 单轮执行，不在 runner 里发明多轮结构，只做显式声明。
P0_SINGLE_TURN_CASES: dict[str, tuple[str, ...]] = {"badcase": ("N06", "N11")}

#: 运行清单的“身份字段”：同输入两次 local run 必须完全相同（仅 run_id/时间戳可变）。
IDENTITY_FIELDS: tuple[str, ...] = (
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
    "config_hash",
    "case_count",
)


class _CaseError(Exception):
    """单 case 可归因失败：写入 ``cases.jsonl`` 的 ``error.code``，不吞掉其他 case。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = str(code)
        self.message = str(message)
        super().__init__(f"{self.code}: {self.message}")


# --------------------------------------------------------------------------- #
# 清单与结果
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RunManifest:
    """一轮运行的身份清单（设计 §7.3 版本绑定字段 + 产物定位）。"""

    IDENTITY_FIELDS: ClassVar[tuple[str, ...]] = IDENTITY_FIELDS

    run_id: str
    mode: str
    scope: str
    suite: str
    dataset_version: str
    dataset_sha256: str
    corpus_manifest_sha256: str
    business_date: str
    index_revision: int
    pipeline_version: str
    gate_version: str
    label_version: str
    created_at: str
    case_count: int
    config_hash: str
    trace_store: str = TRACE_STORE_NAME
    dataset_path: str = ""
    corpus_dir: str | None = None
    replay_from: str | None = None
    source_run_id: str | None = None
    #: P1 T108：holdout 逐题详情是否落盘（默认 ``False`` = 只出聚合，不写 ``cases.jsonl``）。
    holdout_details: bool = False
    #: holdout labels 的 sha256（本地文件，永不入库）；其它 suite 为空串。
    holdout_labels_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        """按字段表返回可 JSON 序列化的普通对象（字段顺序稳定）。"""
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunManifest":
        """从 ``run_manifest.json`` 重建；缺字段或非法枚举 fail closed。"""
        if not isinstance(payload, Mapping):
            raise ValueError("run_manifest 必须是 JSON 对象")
        required = [
            field.name
            for field in fields(cls)
            if field.default is MISSING and field.default_factory is MISSING
        ]
        missing = [name for name in required if name not in payload]
        if missing:
            raise ValueError(f"run_manifest 缺少字段: {missing}")
        for name in (
            "run_id",
            "scope",
            "suite",
            "dataset_version",
            "dataset_sha256",
            "corpus_manifest_sha256",
            "business_date",
            "pipeline_version",
            "gate_version",
            "label_version",
            "created_at",
            "config_hash",
        ):
            value = payload.get(name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"run_manifest.{name} 必须是非空字符串，收到 {value!r}")
        if payload["suite"] not in MANIFEST_SUITES:
            raise ValueError(
                f"run_manifest.suite 非法: {payload['suite']!r}（允许 {sorted(MANIFEST_SUITES)}）"
            )
        mode = str(payload["mode"])
        if mode not in MODES:
            raise ValueError(f"run_manifest.mode 非法: {mode!r}（允许 {MODES}）")
        holdout_details = payload.get("holdout_details", False)
        if not isinstance(holdout_details, bool):
            raise ValueError(
                f"run_manifest.holdout_details 必须是布尔值，收到 {holdout_details!r}"
            )
        holdout_labels_sha256 = payload.get("holdout_labels_sha256", "")
        if not isinstance(holdout_labels_sha256, str):
            raise ValueError("run_manifest.holdout_labels_sha256 必须是字符串")
        case_count = payload["case_count"]
        if isinstance(case_count, bool) or not isinstance(case_count, int) or case_count < 0:
            raise ValueError(f"run_manifest.case_count 必须是非负整数，收到 {case_count!r}")
        index_revision = payload["index_revision"]
        if isinstance(index_revision, bool) or not isinstance(index_revision, int) or index_revision < 0:
            raise ValueError(
                f"run_manifest.index_revision 必须是非负整数，收到 {index_revision!r}"
            )
        values = {
            field.name: payload[field.name]
            for field in fields(cls)
            if field.name in payload
        }
        values.update(
            mode=mode,
            case_count=case_count,
            index_revision=index_revision,
            holdout_details=holdout_details,
            holdout_labels_sha256=holdout_labels_sha256,
        )
        return cls(**values)


@dataclass(frozen=True)
class RunResult:
    """``run_suite`` 的返回值：清单、产物目录、逐 case 行与汇总。"""

    manifest: RunManifest
    out_dir: Path
    cases: tuple[Mapping[str, Any], ...]
    summary: Mapping[str, Any]

    @property
    def manifest_path(self) -> Path:
        return self.out_dir / "run_manifest.json"

    @property
    def cases_path(self) -> Path:
        return self.out_dir / "cases.jsonl"

    @property
    def summary_path(self) -> Path:
        return self.out_dir / "summary.json"


# --------------------------------------------------------------------------- #
# 公共入口
# --------------------------------------------------------------------------- #


def run_suite(
    suite: str,
    mode: str,
    *,
    corpus_dir: Path | str | None = None,
    out_dir: Path | str | None = None,
    scope: str = "end_to_end",
    replay_from: Path | str | None = None,
    dataset_path: Path | str | None = None,
    config: Any | None = None,
    holdout_labels: Path | str | None = None,
    allow_holdout_details: bool = False,
    holdout_policy: HoldoutPolicy | None = None,
    holdout_operator: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> RunResult:
    """跑一个 suite：``mode="local"`` 建隔离索引直接 ask；``"replay"`` 只重评分。

    参数与 handoff §5.1 一致；``dataset_path`` 仅供测试/复现覆盖默认
    ``fixtures/evaluation/<suite>.jsonl``。

    P1 T108（holdout 防污染）：

    - ``suite="holdout"`` 只允许 ``mode="local"``；题目来自仓库导出
      ``fixtures/evaluation/holdout-questions.jsonl``，答案来自 ``holdout_labels``
      （或环境变量 ``MKTKB_HOLDOUT_LABELS``），缺失一律 fail closed；
    - 默认**只写聚合**（``run_manifest.json`` / ``summary.json``，不写 ``cases.jsonl``）；
      ``allow_holdout_details=True`` 才写逐题结果 + ``holdout_audit.json``；
    - CI/门禁环境（``CI`` / ``GITHUB_ACTIONS`` / ``MKTKB_CI`` 任一为真）带
      ``allow_holdout_details`` 直接拒绝（非零退出，不执行任何 case）；
    - holdout 参数用于其它 suite 时也直接拒绝（避免误把 holdout 策略带到 b0/badcase）。
    """
    environ_map: Mapping[str, str] = os.environ if environ is None else environ
    if suite != HOLDOUT_SUITE and (
        holdout_labels is not None
        or allow_holdout_details
        or holdout_policy is not None
        or holdout_operator is not None
    ):
        raise ValueError(
            "holdout 参数（--holdout-labels / --allow-holdout-details）只用于 --suite holdout；"
            f"当前 suite={suite!r}"
        )
    if suite not in MANIFEST_SUITES:
        raise ValueError(f"未知 suite {suite!r}；只允许 {sorted(MANIFEST_SUITES)}")
    if mode not in MODES:
        raise ValueError(f"未知 mode {mode!r}；只允许 {list(MODES)}")
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("scope 必须是非空字符串（P0 为 end_to_end）")
    dataset = Path(dataset_path) if dataset_path is not None else _default_dataset(suite)

    if suite == HOLDOUT_SUITE:
        if mode != "local":
            raise ValueError(
                "holdout 只允许 mode='local'（聚合运行）；逐题 replay 待 T109/T110 再评估，"
                "不得用聚合 run 冒充 replay 源"
            )
        labels = (
            Path(holdout_labels)
            if holdout_labels is not None
            else _holdout_labels_from_env(environ_map)
        )
        return _run_local_holdout(
            scope=scope,
            corpus_dir=Path(corpus_dir) if corpus_dir is not None else default_corpus_dir("regression"),
            out_dir=None if out_dir is None else Path(out_dir),
            questions_path=dataset,
            labels_path=labels,
            policy=DEFAULT_HOLDOUT_POLICY if holdout_policy is None else holdout_policy,
            allow_details=allow_holdout_details,
            operator=holdout_operator,
            environ=environ_map,
            config=config,
        )

    if mode == "local":
        if replay_from is not None:
            raise ValueError("mode='local' 不接受 replay_from；replay_from 只属于 replay")
        return _run_local(
            suite=suite,
            scope=scope,
            corpus_dir=Path(corpus_dir) if corpus_dir is not None else default_corpus_dir(suite),
            out_dir=None if out_dir is None else Path(out_dir),
            dataset_path=dataset,
            config=config,
        )
    if replay_from is None:
        raise ValueError(
            "mode='replay' 必须提供 replay_from（上一轮 local run 目录）；不得静默降级为 local"
        )
    return _run_replay(
        suite=suite,
        scope=scope,
        replay_from=Path(replay_from),
        out_dir=None if out_dir is None else Path(out_dir),
        dataset_path=dataset,
    )


def _default_dataset(suite: str) -> Path:
    """holdout 的默认数据集是仓库导出（无答案）；其它 suite 走冻结 fixture。"""
    if suite == HOLDOUT_SUITE:
        return HOLDOUT_QUESTIONS_PATH
    return default_dataset_path(suite)


def _holdout_labels_from_env(environ: Mapping[str, str]) -> Path | None:
    value = environ.get(HOLDOUT_LABELS_ENV)
    if value is None or not value.strip():
        return None
    return Path(value)


def _holdout_operator(operator: str | None, environ: Mapping[str, str]) -> str:
    """审计用操作人：显式参数 → ``MKTKB_HOLDOUT_OPERATOR`` → USER/USERNAME → unknown。"""
    if operator is not None and operator.strip():
        return operator.strip()
    for name in (HOLDOUT_OPERATOR_ENV, "USERNAME", "USER"):
        value = environ.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"


# --------------------------------------------------------------------------- #
# local
# --------------------------------------------------------------------------- #


def _run_local(
    *,
    suite: str,
    scope: str,
    corpus_dir: Path,
    out_dir: Path | None,
    dataset_path: Path,
    config: Any | None,
) -> RunResult:
    cases = load_cases(dataset_path)
    business_date = _single_business_date(cases)
    label_version = _single_label_version(cases)
    ds_version = dataset_version(cases, label_version)
    ds_sha = _sha256_file(dataset_path)

    corpus = load_suite_corpus(
        suite,
        corpus_dir,
        business_date=business_date,
        required_codes=_required_doc_codes(cases),
    )
    if corpus.business_date is not None and corpus.business_date != business_date:
        raise ValueError(
            "语料 manifest 业务日期与数据集不一致："
            f"{corpus.business_date!r} != {business_date!r}"
        )

    run_id = _new_run_id(suite, "local")
    target = _prepare_out_dir(out_dir, run_id)
    repo = TraceRepository(target / TRACE_STORE_NAME)
    try:
        with tempfile.TemporaryDirectory(prefix="mktkb-eval-index-") as temp_dir:
            cfg = config or offline_eval_config(Path(temp_dir), business_date)
            if getattr(cfg, "provider_mode", None) != "offline":
                raise ValueError(
                    "评测只允许 provider_mode='offline'（零真实调用），收到 "
                    f"{getattr(cfg, 'provider_mode', None)!r}"
                )
            index, index_stats = build_suite_index(
                corpus, Path(temp_dir) / "rag.sqlite3", config=cfg
            )
            try:
                manifest = RunManifest(
                    run_id=run_id,
                    mode="local",
                    scope=scope,
                    suite=suite,
                    dataset_version=ds_version,
                    dataset_sha256=ds_sha,
                    corpus_manifest_sha256=corpus.manifest_sha256,
                    business_date=business_date,
                    index_revision=int(index_stats["revision"]),
                    pipeline_version=_pipeline_version(),
                    gate_version=GATE_SCHEMA_VERSION,
                    label_version=label_version,
                    created_at=_utc_now(),
                    case_count=len(cases),
                    config_hash=_config_hash(cfg),
                    trace_store=TRACE_STORE_NAME,
                    dataset_path=str(dataset_path.resolve()),
                    corpus_dir=str(corpus_dir.resolve()),
                )
                rows = [
                    _local_case_row(case, index, repo, manifest) for case in cases
                ]
            finally:
                index.close()
    finally:
        repo.close()

    summary = _build_summary(manifest, cases, rows)
    _write_artifacts(target, manifest, rows, summary)
    return RunResult(manifest=manifest, out_dir=target, cases=tuple(rows), summary=summary)


def _run_local_holdout(
    *,
    scope: str,
    corpus_dir: Path,
    out_dir: Path | None,
    questions_path: Path,
    labels_path: Path | None,
    policy: HoldoutPolicy,
    allow_details: bool,
    operator: str | None,
    environ: Mapping[str, str],
    config: Any | None,
) -> RunResult:
    """holdout local run：默认只出聚合；``allow_details`` 才写逐题 + 审计。"""
    if allow_details:
        ci_var = ci_environment(environ)
        if ci_var is not None:
            raise HoldoutError(
                "CI/门禁环境禁止 --allow-holdout-details"
                f"（命中环境变量 {ci_var}）：holdout 逐题详情只能在本地受限环境生成"
            )
    if labels_path is None:
        raise HoldoutError(
            "holdout 缺少 labels：请用 --holdout-labels <path> 或 "
            f"{HOLDOUT_LABELS_ENV} 指向本地 labels.jsonl（labels 永不入库）"
        )
    dataset: HoldoutDataset = load_holdout_dataset(questions_path, labels_path, policy=policy)
    cases = list(dataset.cases)
    business_date = _single_business_date(cases)
    label_version = _single_label_version(cases)
    ds_version = dataset_version(cases, label_version)
    ds_sha = dataset.questions.sha256

    # holdout 语料 = 全量企业语料（与 regression 同一装配口径）：
    # 引用到的 doc_code 必须全部解析成功，不让 gold 悄悄退化成 GoldUnresolved。
    corpus = load_suite_corpus(
        "regression",
        corpus_dir,
        business_date=business_date,
        required_codes=_required_doc_codes(cases),
    )
    if corpus.business_date is not None and corpus.business_date != business_date:
        raise ValueError(
            "语料 manifest 业务日期与数据集不一致："
            f"{corpus.business_date!r} != {business_date!r}"
        )

    run_id = _new_run_id(HOLDOUT_SUITE, "local")
    target = _prepare_out_dir(out_dir, run_id)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mktkb-eval-holdout-") as temp_dir:
        # 聚合 run 的 trace 只落在临时目录（随后随目录删除）：产物里不留逐题痕迹。
        trace_path = (
            target / TRACE_STORE_NAME if allow_details else Path(temp_dir) / TRACE_STORE_NAME
        )
        repo = TraceRepository(trace_path)
        try:
            cfg = config or offline_eval_config(Path(temp_dir), business_date)
            if getattr(cfg, "provider_mode", None) != "offline":
                raise ValueError(
                    "评测只允许 provider_mode='offline'（零真实调用），收到 "
                    f"{getattr(cfg, 'provider_mode', None)!r}"
                )
            index, index_stats = build_suite_index(
                corpus, Path(temp_dir) / "rag.sqlite3", config=cfg
            )
            try:
                manifest = RunManifest(
                    run_id=run_id,
                    mode="local",
                    scope=scope,
                    suite=HOLDOUT_SUITE,
                    dataset_version=ds_version,
                    dataset_sha256=ds_sha,
                    corpus_manifest_sha256=corpus.manifest_sha256,
                    business_date=business_date,
                    index_revision=int(index_stats["revision"]),
                    pipeline_version=_pipeline_version(),
                    gate_version=GATE_SCHEMA_VERSION,
                    label_version=label_version,
                    created_at=_utc_now(),
                    case_count=len(cases),
                    config_hash=_config_hash(cfg),
                    trace_store=TRACE_STORE_NAME if allow_details else "",
                    dataset_path=str(questions_path.resolve()),
                    corpus_dir=str(corpus_dir.resolve()),
                    holdout_details=allow_details,
                    holdout_labels_sha256=dataset.labels.sha256,
                )
                rows = [_local_case_row(case, index, repo, manifest) for case in cases]
            finally:
                index.close()
        finally:
            repo.close()

    summary = _build_summary(
        manifest,
        cases,
        rows,
        holdout=dataset,
        redact_case_ids=not allow_details,
    )
    _write_artifacts(target, manifest, rows, summary, include_cases=allow_details)
    if allow_details:
        _write_holdout_audit(
            target,
            manifest=manifest,
            dataset=dataset,
            out_dir=target,
            scope=scope,
            questions_path=questions_path,
            labels_path=Path(labels_path),
            corpus_dir=corpus_dir,
            operator=_holdout_operator(operator, environ),
        )
    return RunResult(manifest=manifest, out_dir=target, cases=tuple(rows), summary=summary)


def _write_holdout_audit(
    target: Path,
    *,
    manifest: RunManifest,
    dataset: HoldoutDataset,
    out_dir: Path,
    scope: str,
    questions_path: Path,
    labels_path: Path,
    corpus_dir: Path,
    operator: str,
) -> Path:
    """写 ``holdout_audit.json``：操作人/时间/参数/run_id/数据 sha/label_version。

    只记元数据与路径，**不含任何题干或答案原文**。
    """
    payload = {
        "audit_schema_version": "mktkb.holdout.audit.v0.1",
        "run_id": manifest.run_id,
        "suite": manifest.suite,
        "mode": manifest.mode,
        "scope": scope,
        "operator": operator,
        "created_at": manifest.created_at,
        "parameters": {
            "allow_holdout_details": True,
            "out_dir": str(Path(out_dir).resolve()),
            "corpus_dir": str(Path(corpus_dir).resolve()),
            "config_hash": manifest.config_hash,
        },
        "data": {
            "questions_path": str(Path(questions_path).resolve()),
            "questions_sha256": dataset.questions.sha256,
            "labels_path": str(Path(labels_path).resolve()),
            "labels_sha256": dataset.labels.sha256,
            "label_version": manifest.label_version,
            "case_count": manifest.case_count,
            "strata": dict(sorted(dataset.questions.strata.items())),
            "metadata_mismatch_count": dataset.metadata_mismatch_count,
        },
        "note": "holdout 逐题详情仅供本地受限分析；不得入库、不得进入报告或证据。",
    }
    path = Path(target) / "holdout_audit.json"
    _write_json(path, payload)
    return path


def _local_case_row(
    case: CaseSpec, index: Any, repo: TraceRepository, manifest: RunManifest
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        _assert_gold_references(case)
        gold = resolve_case(case, index)
        _assert_gold_unit_ids(case, gold)
    except GoldUnresolved as exc:
        return _error_row(
            case, manifest, repo, "gold_unresolved", str(exc), duration_ms=_elapsed_ms(started)
        )
    except _CaseError as exc:
        return _error_row(
            case, manifest, repo, exc.code, exc.message, duration_ms=_elapsed_ms(started)
        )
    except Exception as exc:  # noqa: BLE001 - 单 case 失败不吞掉其他 case
        return _error_row(
            case,
            manifest,
            repo,
            "gold_resolution_error",
            f"{type(exc).__name__}: {exc}",
            duration_ms=_elapsed_ms(started),
        )

    if gold.skipped:
        trace_id = _write_provenance_trace(case, manifest, repo)
        result = score_case(case, gold, EvalOutcome(kind="no_answer"))
        return _row_from_result(
            case,
            result,
            gold,
            outcome=None,
            trace_id=trace_id,
            previous_trace_id=None,
            replayed=False,
            duration_ms=_elapsed_ms(started),
        )

    trace: TraceContext | None = None
    try:
        with start_trace(
            http_request_id=f"{manifest.run_id}:{case.case_id}",
            mode=TraceMode.LOCAL,
            scope=manifest.scope,
            path="rag",
            question=case.question,
            case_id=case.case_id,
            repo=repo,
        ) as active:
            trace = active
            _annotate_trace_identity(trace, manifest)
            answer = index.ask(
                case.question,
                user_id="eval",
                conversation_id=f"{manifest.run_id}:{case.case_id}",
            )
            trace.set_outcome(answer.kind, reason=answer.reason)
        trace_record = _read_trace(repo, trace.trace_id)
        outcome = _normalise_answer(case, answer, index, trace.trace_id)
        result = score_case(case, gold, outcome, trace_record)
        return _row_from_result(
            case,
            result,
            gold,
            outcome=outcome,
            trace_id=trace.trace_id,
            previous_trace_id=None,
            replayed=False,
            duration_ms=_elapsed_ms(started),
        )
    except _CaseError as exc:
        return _error_row(
            case,
            manifest,
            repo,
            exc.code,
            exc.message,
            trace_id=None if trace is None else trace.trace_id,
            duration_ms=_elapsed_ms(started),
        )
    except Exception as exc:  # noqa: BLE001 - 单 case 失败不吞掉其他 case
        return _error_row(
            case,
            manifest,
            repo,
            "execution_error",
            f"{type(exc).__name__}: {exc}",
            trace_id=None if trace is None else trace.trace_id,
            duration_ms=_elapsed_ms(started),
        )


# --------------------------------------------------------------------------- #
# replay
# --------------------------------------------------------------------------- #


def _run_replay(
    *,
    suite: str,
    scope: str,
    replay_from: Path,
    out_dir: Path | None,
    dataset_path: Path,
) -> RunResult:
    source_manifest_path = replay_from / "run_manifest.json"
    if not source_manifest_path.is_file():
        raise ValueError(f"replay_from 缺少 run_manifest.json: {source_manifest_path}")
    try:
        source = RunManifest.from_dict(
            json.loads(source_manifest_path.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取源 run 清单 {source_manifest_path}: {exc}") from exc
    if source.mode != "local":
        raise ValueError(
            f"replay_from 必须是 local run（收到 mode={source.mode!r}）；replay 只重放 local 产物"
        )
    if source.suite != suite:
        raise ValueError(f"replay_from.suite={source.suite!r} 与请求 suite={suite!r} 不一致")
    if source.scope != scope:
        raise ValueError(
            f"replay scope 必须与源 run 一致：{source.scope!r} != {scope!r}"
        )

    cases = load_cases(dataset_path)
    ds_sha = _sha256_file(dataset_path)
    if ds_sha != source.dataset_sha256:
        raise ValueError(
            "replay 数据集与源 run 不一致（dataset_sha256）："
            f"{ds_sha} != {source.dataset_sha256}"
        )
    label_version = _single_label_version(cases)
    if label_version != source.label_version:
        raise ValueError(
            f"replay label_version 不一致：{label_version!r} != {source.label_version!r}"
        )
    if dataset_version(cases, label_version) != source.dataset_version:
        raise ValueError("replay 数据集 dataset_version 与源 run 不一致")
    if _single_business_date(cases) != source.business_date:
        raise ValueError("replay 数据集 business_date 与源 run 不一致")

    source_rows = _read_cases_jsonl(replay_from / "cases.jsonl")
    if len(source_rows) != len(cases):
        raise ValueError(
            f"源 run cases.jsonl 行数 {len(source_rows)} != 数据集行数 {len(cases)}"
        )
    source_case_ids = [str(row.get("case_id") or "") for row in source_rows]
    dataset_case_ids = [case.case_id for case in cases]
    if source_case_ids != dataset_case_ids:
        raise ValueError("源 run cases.jsonl 与数据集 case 顺序/集合不一致")

    run_id = _new_run_id(suite, "replay")
    target = _prepare_out_dir(out_dir, run_id)
    manifest = RunManifest(
        run_id=run_id,
        mode="replay",
        scope=scope,
        suite=suite,
        dataset_version=source.dataset_version,
        dataset_sha256=source.dataset_sha256,
        corpus_manifest_sha256=source.corpus_manifest_sha256,
        business_date=source.business_date,
        index_revision=source.index_revision,
        pipeline_version=source.pipeline_version,
        gate_version=source.gate_version,
        label_version=source.label_version,
        created_at=_utc_now(),
        case_count=len(cases),
        config_hash=source.config_hash,
        trace_store=TRACE_STORE_NAME,
        dataset_path=str(dataset_path.resolve()),
        corpus_dir=source.corpus_dir,
        replay_from=str(replay_from.resolve()),
        source_run_id=source.run_id,
    )
    repo = TraceRepository(target / TRACE_STORE_NAME)
    rows: list[dict[str, Any]] = []
    try:
        for case, source_row in zip(cases, source_rows):
            rows.append(_replay_case_row(case, source_row, repo, manifest))
    finally:
        repo.close()

    summary = _build_summary(manifest, cases, rows)
    _write_artifacts(target, manifest, rows, summary)
    return RunResult(manifest=manifest, out_dir=target, cases=tuple(rows), summary=summary)


def _replay_case_row(
    case: CaseSpec,
    source_row: Mapping[str, Any],
    repo: TraceRepository,
    manifest: RunManifest,
) -> dict[str, Any]:
    started = time.perf_counter()
    previous_trace_id = source_row.get("trace_id")
    previous_trace_id = None if previous_trace_id in (None, "") else str(previous_trace_id)

    persisted_error = source_row.get("error")
    if isinstance(persisted_error, Mapping) and persisted_error:
        code = str(persisted_error.get("code") or "persisted_error")
        message = str(persisted_error.get("message") or "源 run 已标记 error")
        trace_id = _write_provenance_trace(
            case, manifest, repo, previous_trace_id=previous_trace_id, replayed=True
        )
        return _error_row(
            case,
            manifest,
            repo,
            code,
            message,
            trace_id=trace_id,
            previous_trace_id=previous_trace_id,
            replayed=True,
            duration_ms=_elapsed_ms(started),
        )

    try:
        _assert_gold_references(case)
        gold = _gold_from_dict(case, source_row.get("gold"))
        _assert_gold_unit_ids(case, gold)
        outcome_payload = source_row.get("outcome")
        if gold.skipped:
            outcome = None
            result = score_case(case, gold, EvalOutcome(kind="no_answer"))
        else:
            if outcome_payload is None:
                raise _CaseError(
                    "outcome_missing", f"{case.case_id}: 非 OCR case 缺少持久化 outcome"
                )
            outcome = _outcome_from_dict(case, outcome_payload)
            result = score_case(case, gold, outcome, None)
        _assert_same_score(case, source_row, result)
        trace_id = _write_provenance_trace(
            case,
            manifest,
            repo,
            outcome=outcome,
            previous_trace_id=previous_trace_id,
            replayed=True,
        )
        return _row_from_result(
            case,
            result,
            gold,
            outcome=outcome,
            trace_id=trace_id,
            previous_trace_id=previous_trace_id,
            replayed=True,
            duration_ms=_elapsed_ms(started),
        )
    except _CaseError as exc:
        trace_id = _write_provenance_trace(
            case, manifest, repo, previous_trace_id=previous_trace_id, replayed=True
        )
        return _error_row(
            case,
            manifest,
            repo,
            exc.code,
            exc.message,
            trace_id=trace_id,
            previous_trace_id=previous_trace_id,
            replayed=True,
            duration_ms=_elapsed_ms(started),
        )


# --------------------------------------------------------------------------- #
# 归一化与持久化
# --------------------------------------------------------------------------- #


def _normalise_answer(
    case: CaseSpec, answer: Any, index: Any, trace_id: str
) -> EvalOutcome:
    """把 ``RagAnswer`` 归一化为 ``EvalOutcome``；unit 归属只取索引里的 chunk 真值。"""
    citation_ids = [str(item.source_id) for item in answer.citations]
    try:
        evidence_ids = [str(item) for item in (answer.diagnostics.get("evidence_ids") or ())]
    except AttributeError as exc:  # pragma: no cover - RagAnswer 契约固定
        raise _CaseError("answer_payload_invalid", f"{case.case_id}: {exc}") from exc
    ordered_ids = _dedupe(citation_ids + evidence_ids)
    if any(not item for item in ordered_ids):
        raise _CaseError("chunk_id_missing", f"{case.case_id}: 引用/检索缺少 chunk_id")
    chunks = {chunk.chunk_id: chunk for chunk in index.chunks_by_ids(ordered_ids)}
    missing = [chunk_id for chunk_id in ordered_ids if chunk_id not in chunks]
    if missing:
        raise _CaseError(
            "chunk_not_found",
            f"{case.case_id}: 引用/检索 chunk 不在当前索引: {missing[:3]}",
        )
    # T005 PM 追加（T004b 验收 MEDIUM-4）：引用/检索项必须同时保留
    # doc_code + unit_key/locator，否则下游 security_leak 的 forbidden_sources
    # （按 unit_key 匹配）会漏报。这里按 chunk 的真实 unit 归属逐 unit 展开：
    # 每个引用项只带一个 unit_id + 该 unit 的真实 unit_key，不猜、不合并。
    unit_keys = _unit_keys(index, [unit_id for chunk in chunks.values() for unit_id in chunk.unit_ids])

    citations: list[EvalCitation] = []
    for item in answer.citations:
        chunk = chunks[str(item.source_id)]
        if not chunk.unit_ids:
            raise _CaseError(
                "citation_unit_ids_missing",
                f"{case.case_id}: 引用 chunk {chunk.chunk_id} 没有 unit 归属",
            )
        for unit_id in chunk.unit_ids:
            citations.append(
                EvalCitation(
                    doc_code=str(item.doc_id),
                    unit_key=unit_keys.get(str(unit_id)),
                    unit_ids=(str(unit_id),),
                    locator=dict(item.locator or {}),
                    text=str(item.text),
                    kind=str(item.kind),
                )
            )

    retrieved: list[EvalRetrieved] = []
    for chunk_id in evidence_ids:
        chunk = chunks[chunk_id]
        if not chunk.unit_ids:
            raise _CaseError(
                "retrieved_unit_ids_missing",
                f"{case.case_id}: 检索 chunk {chunk.chunk_id} 没有 unit 归属",
            )
        for unit_id in chunk.unit_ids:
            retrieved.append(
                EvalRetrieved(
                    doc_code=str(chunk.doc_id),
                    unit_ids=(str(unit_id),),
                    unit_key=unit_keys.get(str(unit_id)),
                    locator=dict(chunk.locator or {}),
                    chunk_id=str(chunk.chunk_id),
                )
            )

    facts = tuple(
        EvalFact(
            doc_code=str(item.doc_id),
            unit_id=None if item.source_unit_id is None else str(item.source_unit_id),
            entity_key=str(item.entity_key),
            field_role=str(item.field_role),
            field_label=str(item.field_label),
            value=str(item.value),
        )
        for item in answer.facts
    )

    pagination: dict[str, Any] = {}
    if bool(answer.state.get("enumerate")):
        # 分页契约只在 enumerate 模式成立；普通检索的 total/has_more 不是分页语义。
        pagination = {
            key: answer.diagnostics.get(key)
            for key in ("total", "returned", "has_more", "next_page")
        }

    return EvalOutcome(
        kind=str(answer.kind),
        text=str(answer.text),
        citations=tuple(citations),
        facts=facts,
        pagination=pagination,
        trace_id=trace_id,
        path="rag",
        retrieved=tuple(retrieved),
    )


def _unit_keys(index: Any, unit_ids: Sequence[str]) -> dict[str, str]:
    """批量读取 unit_id -> unit_key（真实归属，不是猜）；缺行时调用方写 null。"""
    ordered = _dedupe([str(item) for item in unit_ids if str(item)])
    if not ordered:
        return {}
    from sqlalchemy import select

    from ..rag.models import RagUnit

    with index.session() as session:
        rows = session.execute(
            select(RagUnit.unit_id, RagUnit.unit_key).where(RagUnit.unit_id.in_(ordered))
        ).all()
    return {str(row[0]): str(row[1]) for row in rows}


def _outcome_to_dict(outcome: EvalOutcome) -> dict[str, Any]:    return {
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
        "facts": [
            {
                "doc_code": item.doc_code,
                "unit_id": item.unit_id,
                "unit_key": item.unit_key,
                "entity_key": item.entity_key,
                "field_role": item.field_role,
                "field_label": item.field_label,
                "value": item.value,
            }
            for item in outcome.facts
        ],
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


def _outcome_from_dict(case: CaseSpec, payload: Any) -> EvalOutcome:
    if not isinstance(payload, Mapping):
        raise _CaseError("outcome_payload_invalid", f"{case.case_id}: outcome 必须是对象")
    citations_payload = payload.get("citations")
    retrieved_payload = payload.get("retrieved")
    if not isinstance(citations_payload, list) or not isinstance(retrieved_payload, list):
        raise _CaseError(
            "outcome_payload_invalid", f"{case.case_id}: citations/retrieved 必须是数组"
        )
    citations: list[EvalCitation] = []
    for index, raw in enumerate(citations_payload):
        if not isinstance(raw, Mapping):
            raise _CaseError(
                "outcome_payload_invalid", f"{case.case_id}: citations[{index}] 不是对象"
            )
        unit_ids = _unit_tuple(raw.get("unit_ids"), case, f"citations[{index}]")
        if not unit_ids:
            raise _CaseError(
                "citation_unit_ids_missing",
                f"{case.case_id}: citations[{index}] 缺 unit_ids（不得静默算 0）",
            )
        locator = raw.get("locator") or {}
        if not isinstance(locator, Mapping):
            raise _CaseError(
                "outcome_payload_invalid", f"{case.case_id}: citations[{index}].locator 不是对象"
            )
        citations.append(
            EvalCitation(
                doc_code=str(raw.get("doc_code") or ""),
                unit_key=None if raw.get("unit_key") is None else str(raw["unit_key"]),
                unit_ids=unit_ids,
                locator=dict(locator),
                text=str(raw.get("text") or ""),
                kind=str(raw.get("kind") or ""),
            )
        )
    retrieved: list[EvalRetrieved] = []
    for index, raw in enumerate(retrieved_payload):
        if not isinstance(raw, Mapping):
            raise _CaseError(
                "outcome_payload_invalid", f"{case.case_id}: retrieved[{index}] 不是对象"
            )
        unit_ids = _unit_tuple(raw.get("unit_ids"), case, f"retrieved[{index}]")
        if not unit_ids:
            raise _CaseError(
                "retrieved_unit_ids_missing",
                f"{case.case_id}: retrieved[{index}] 缺 unit_ids（不得静默算 0）",
            )
        locator = raw.get("locator") or {}
        if not isinstance(locator, Mapping):
            raise _CaseError(
                "outcome_payload_invalid", f"{case.case_id}: retrieved[{index}].locator 不是对象"
            )
        retrieved.append(
            EvalRetrieved(
                doc_code=str(raw.get("doc_code") or ""),
                unit_ids=unit_ids,
                unit_key=None if raw.get("unit_key") is None else str(raw["unit_key"]),
                locator=dict(locator),
                chunk_id=None if raw.get("chunk_id") is None else str(raw["chunk_id"]),
                hard_filter_violation=(
                    None
                    if raw.get("hard_filter_violation") is None
                    else str(raw["hard_filter_violation"])
                ),
            )
        )
    facts_payload = payload.get("facts") or []
    if not isinstance(facts_payload, list):
        raise _CaseError("outcome_payload_invalid", f"{case.case_id}: facts 必须是数组")
    facts = tuple(
        EvalFact(
            doc_code=str(raw.get("doc_code") or ""),
            unit_id=None if raw.get("unit_id") is None else str(raw["unit_id"]),
            unit_key=None if raw.get("unit_key") is None else str(raw["unit_key"]),
            entity_key=str(raw.get("entity_key") or ""),
            field_role=str(raw.get("field_role") or ""),
            field_label=str(raw.get("field_label") or ""),
            value=str(raw.get("value") or ""),
        )
        for raw in facts_payload
        if isinstance(raw, Mapping)
    )
    pagination = payload.get("pagination") or {}
    if not isinstance(pagination, Mapping):
        raise _CaseError("outcome_payload_invalid", f"{case.case_id}: pagination 必须是对象")
    path = payload.get("path")
    trace_id = payload.get("trace_id")
    return EvalOutcome(
        kind=str(payload.get("kind") or ""),
        text=str(payload.get("text") or ""),
        citations=tuple(citations),
        facts=facts,
        pagination=dict(pagination),
        trace_id=None if trace_id is None else str(trace_id),
        path="rag" if path is None else str(path),
        retrieved=tuple(retrieved),
    )


def _gold_to_dict(gold: ResolvedGold) -> dict[str, Any]:
    return {
        "case_id": gold.case_id,
        "requires_ocr": bool(gold.requires_ocr),
        "skipped": bool(gold.skipped),
        "sources": [
            {
                "doc_code": source.doc_code,
                "doc_id": source.doc_id,
                "unit_ids": list(source.unit_ids),
                "unit_keys": list(source.unit_keys),
            }
            for source in gold.sources
        ],
        "unit_ids": list(gold.unit_ids),
        "relevant_unit_ids": list(gold.relevant_unit_ids),
    }


def _gold_from_dict(case: CaseSpec, payload: Any) -> ResolvedGold:
    if not isinstance(payload, Mapping):
        raise _CaseError("gold_payload_invalid", f"{case.case_id}: gold 必须是对象")
    if str(payload.get("case_id") or "") != case.case_id:
        raise _CaseError("gold_payload_invalid", f"{case.case_id}: gold.case_id 不一致")
    sources_payload = payload.get("sources") or []
    if not isinstance(sources_payload, list):
        raise _CaseError("gold_payload_invalid", f"{case.case_id}: gold.sources 必须是数组")
    sources: list[ResolvedSource] = []
    for index, raw in enumerate(sources_payload):
        if not isinstance(raw, Mapping):
            raise _CaseError(
                "gold_payload_invalid", f"{case.case_id}: gold.sources[{index}] 不是对象"
            )
        sources.append(
            ResolvedSource(
                doc_code=str(raw.get("doc_code") or ""),
                doc_id=str(raw.get("doc_id") or ""),
                unit_ids=_unit_tuple(raw.get("unit_ids"), case, f"gold.sources[{index}]"),
                unit_keys=tuple(str(item) for item in (raw.get("unit_keys") or ())),
            )
        )
    gold = ResolvedGold(
        case_id=case.case_id,
        requires_ocr=bool(payload.get("requires_ocr")),
        skipped=bool(payload.get("skipped")),
        sources=tuple(sources),
        unit_ids=_unit_tuple(payload.get("unit_ids"), case, "gold.unit_ids"),
        relevant_unit_ids=_unit_tuple(
            payload.get("relevant_unit_ids"), case, "gold.relevant_unit_ids"
        ),
    )
    if gold.requires_ocr != bool(case.requires_ocr) or gold.skipped != bool(case.requires_ocr):
        raise _CaseError(
            "gold_payload_mismatch", f"{case.case_id}: gold OCR 标记与数据集不一致"
        )
    if not gold.skipped and case.expected_sources and len(gold.sources) != len(case.expected_sources):
        raise _CaseError(
            "gold_payload_mismatch",
            f"{case.case_id}: gold.sources 数 {len(gold.sources)} != expected_sources 数 "
            f"{len(case.expected_sources)}",
        )
    return gold


def _row_from_result(
    case: CaseSpec,
    result: CaseResult,
    gold: ResolvedGold,
    *,
    outcome: EvalOutcome | None,
    trace_id: str,
    previous_trace_id: str | None,
    replayed: bool,
    duration_ms: int,
) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "suite": case.suite,
        "status": result.status,
        "trace_id": trace_id,
        "previous_trace_id": previous_trace_id,
        "replayed": bool(replayed),
        "checks": [item.to_dict() for item in result.checks],
        "metrics": dict(result.metrics),
        "refused": result.refused,
        "should_refuse": bool(result.should_refuse),
        "path": result.path,
        "latency_ms": result.latency_ms,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "cost_cny": result.cost_cny,
        "duration_ms": int(duration_ms),
        "turns_executed": 1,
        "multi_turn_claimed": False,
        "outcome": None if outcome is None else _outcome_to_dict(outcome),
        "gold": _gold_to_dict(gold),
        "error": None,
    }


def _error_row(
    case: CaseSpec,
    manifest: RunManifest,
    repo: TraceRepository,
    code: str,
    message: str,
    *,
    trace_id: str | None = None,
    previous_trace_id: str | None = None,
    replayed: bool = False,
    duration_ms: int = 0,
    outcome: EvalOutcome | None = None,
    gold: ResolvedGold | None = None,
) -> dict[str, Any]:
    if trace_id is None:
        trace_id = _write_provenance_trace(
            case, manifest, repo, previous_trace_id=previous_trace_id, replayed=replayed
        )
    return {
        "case_id": case.case_id,
        "suite": case.suite,
        "status": "error",
        "trace_id": trace_id,
        "previous_trace_id": previous_trace_id,
        "replayed": bool(replayed),
        "checks": [],
        "metrics": {},
        "refused": None,
        "should_refuse": bool(case.should_refuse),
        "path": None,
        "latency_ms": None,
        "tokens_in": None,
        "tokens_out": None,
        "cost_cny": None,
        "duration_ms": int(duration_ms),
        "turns_executed": 1,
        "multi_turn_claimed": False,
        "outcome": None if outcome is None else _outcome_to_dict(outcome),
        "gold": None if gold is None else _gold_to_dict(gold),
        "error": {"code": str(code), "message": str(message)},
    }


# --------------------------------------------------------------------------- #
# gold 防御 / 一致性
# --------------------------------------------------------------------------- #


def _assert_gold_references(case: CaseSpec) -> None:
    """T004a 验收遗留：``record_code`` 不是解析键，不能静默扩为整文档 gold。

    整篇级 gold（只给 ``doc_code``，如 N09）是设计允许的**范围型**引用，不在拒绝范围；
    只有“只有 record_code、没有 unit_key/locator”的引用才是危险形态。
    """
    for ref in (*case.expected_sources, *case.relevant_units):
        if "record_code" in ref and "unit_key" not in ref and "locator" not in ref:
            raise _CaseError(
                "record_code_only_gold",
                f"{case.case_id}: 引用只有 record_code（不是解析键），必须补 unit_key 或 "
                f"locator，不得扩为整文档 gold: {dict(ref)!r}",
            )


def _assert_gold_unit_ids(case: CaseSpec, gold: ResolvedGold) -> None:
    if gold.skipped:
        return
    refs = (*case.expected_sources, *case.relevant_units)
    if not refs:
        return
    if not gold.unit_ids:
        raise _CaseError(
            "gold_unit_ids_missing",
            f"{case.case_id}: gold 引用存在但 unit_ids 为空（不得静默扩为整文档）",
        )
    if not gold.relevant_unit_ids:
        raise _CaseError(
            "gold_unit_ids_missing",
            f"{case.case_id}: gold 引用存在但 relevant_unit_ids 为空",
        )


def _assert_same_score(
    case: CaseSpec, source_row: Mapping[str, Any], result: CaseResult
) -> None:
    """replay 必须复现 local 的 checks/metrics/status；任何漂移按 case error 暴露。"""
    expected = result.to_dict()
    if source_row.get("checks") != expected["checks"]:
        raise _CaseError(
            "replay_score_mismatch", f"{case.case_id}: replay 重算 checks 与源 run 不一致"
        )
    if source_row.get("metrics") != expected["metrics"]:
        raise _CaseError(
            "replay_score_mismatch", f"{case.case_id}: replay 重算 metrics 与源 run 不一致"
        )
    if source_row.get("status") != expected["status"]:
        raise _CaseError(
            "replay_score_mismatch", f"{case.case_id}: replay 重算 status 与源 run 不一致"
        )


# --------------------------------------------------------------------------- #
# summary / 产物
# --------------------------------------------------------------------------- #


def _result_from_row(row: Mapping[str, Any]) -> CaseResult:
    checks = tuple(
        CaseCheck(
            check_id=str(item.get("check_id") or ""),
            status=str(item.get("status") or ""),
            evidence=dict(item.get("evidence") or {}),
        )
        for item in (row.get("checks") or ())
        if isinstance(item, Mapping)
    )
    return CaseResult(
        case_id=str(row.get("case_id") or ""),
        status=str(row.get("status") or ""),
        checks=checks,
        metrics=dict(row.get("metrics") or {}),
        refused=row.get("refused"),
        should_refuse=bool(row.get("should_refuse")),
        trace_id=None if row.get("trace_id") is None else str(row.get("trace_id")),
        path=None if row.get("path") is None else str(row.get("path")),
        latency_ms=row.get("latency_ms"),
        tokens_in=row.get("tokens_in"),
        tokens_out=row.get("tokens_out"),
        cost_cny=row.get("cost_cny"),
    )


def _build_summary(
    manifest: RunManifest,
    cases: Sequence[CaseSpec],
    rows: Sequence[Mapping[str, Any]],
    *,
    holdout: HoldoutDataset | None = None,
    redact_case_ids: bool = False,
) -> dict[str, Any]:
    aligned_cases: list[CaseSpec] = []
    results: list[CaseResult] = []
    excluded_errors: list[str] = []
    for case, row in zip(cases, rows):
        if row.get("status") == "error":
            excluded_errors.append(case.case_id)
            continue
        aligned_cases.append(case)
        results.append(_result_from_row(row))
    metrics = aggregate_metrics(aligned_cases, results)
    status_counts = Counter(str(row.get("status")) for row in rows)
    summary = {
        "run_id": manifest.run_id,
        "mode": manifest.mode,
        "suite": manifest.suite,
        "scope": manifest.scope,
        "dataset_version": manifest.dataset_version,
        "dataset_sha256": manifest.dataset_sha256,
        "corpus_manifest_sha256": manifest.corpus_manifest_sha256,
        "business_date": manifest.business_date,
        "index_revision": manifest.index_revision,
        "pipeline_version": manifest.pipeline_version,
        "gate_version": manifest.gate_version,
        "case_count": len(rows),
        "scored_count": sum(
            1 for row in rows if row.get("status") in {"pass", "fail"}
        ),
        "skipped_ocr_count": int(status_counts.get("skipped_requires_ocr", 0)),
        "error_count": int(status_counts.get("error", 0)),
        "status_counts": dict(sorted(status_counts.items())),
        "metrics": metrics,
        "metrics_scope": {
            "cases_in_denominator": len(aligned_cases),
            "excluded_error_case_ids": excluded_errors,
            "ocr_excluded_by_scorer": int(status_counts.get("skipped_requires_ocr", 0)),
            "note": (
                "error case 不进任何指标分母（unknown，不是 0）；OCR case 由 scorer 的 "
                "skipped_requires_ocr 语义排除"
            ),
        },
        "declarations": _declarations(manifest, cases, rows),
    }
    if redact_case_ids:
        _redact_case_ids(summary)
    if holdout is not None:
        summary["holdout"] = {
            "aggregate_only": not manifest.holdout_details,
            "details_written": manifest.holdout_details,
            "audit_file": "holdout_audit.json" if manifest.holdout_details else None,
            "questions_sha256": holdout.questions.sha256,
            "labels_sha256": holdout.labels.sha256,
            "label_version": manifest.label_version,
            "strata": dict(sorted(holdout.questions.strata.items())),
            "metadata_mismatch_count": holdout.metadata_mismatch_count,
            "traces_persisted": manifest.holdout_details,
            "note": (
                "holdout 默认只出聚合（无 cases.jsonl / 逐题题干 / 答案 / 逐题结果）；"
                "逐题详情需 --allow-holdout-details 并在本地受限环境使用，永不入库"
            ),
        }
    return summary


def _redact_case_ids(summary: dict[str, Any]) -> None:
    """把汇总里的逐 case 列表换成计数（holdout 聚合 run 的防污染要求）。"""
    scope = summary.get("metrics_scope")
    if isinstance(scope, dict):
        excluded = scope.pop("excluded_error_case_ids", [])
        scope["excluded_error_count"] = len(excluded) if isinstance(excluded, list) else 0
    declarations = summary.get("declarations")
    if not isinstance(declarations, dict):
        return
    replacements = {
        "single_turn_case_ids": "single_turn_case_count",
        "expected_pagination_case_ids": "expected_pagination_case_count",
        "range_gold_case_ids": "range_gold_case_count",
    }
    for block in declarations.values():
        if not isinstance(block, dict):
            continue
        for key, count_key in replacements.items():
            if key in block:
                value = block.pop(key)
                block[count_key] = len(value) if isinstance(value, list) else 0


def _declarations(
    manifest: RunManifest, cases: Sequence[CaseSpec], rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    case_ids = {case.case_id for case in cases}
    single_turn_ids = [
        case_id
        for case_id in P0_SINGLE_TURN_CASES.get(manifest.suite, ())
        if case_id in case_ids
    ]
    range_gold_ids = [
        case.case_id
        for case in cases
        if any(
            "unit_key" not in ref
            for ref in (*case.expected_sources, *case.relevant_units)
        )
    ]
    pagination_expected = [
        case.case_id for case in cases if case.expected_pagination is not None
    ]
    return {
        "execution": {
            "mode": "single_turn",
            "turns_executed": 1,
            "multi_turn_verified": False,
            "single_turn_case_ids": single_turn_ids,
            "note": (
                "P0 为单轮执行；N06/N11 不证明多轮能力"
                if single_turn_ids
                else "P0 为单轮执行；runner 不声明任何多轮能力"
            ),
        },
        "pagination": {
            "claimed": bool(pagination_expected),
            "expected_pagination_case_ids": pagination_expected,
            "note": (
                "P0 数据集 expected_pagination 全为 null；N05 的 expected_min_total 只在 notes，"
                "runner 不声称分页契约覆盖"
                if not pagination_expected
                else "仅当 case 显式给出 expected_pagination 时才声称分页契约覆盖"
            ),
        },
        "gold": {
            "record_code_only_allowed": False,
            "range_gold_case_ids": range_gold_ids,
            "note": (
                "locator / 整篇级引用是范围型 gold（unit 集合），检索指标按集合计；"
                "record_code-only 引用在 runner 层 fail closed"
            ),
        },
    }


def _write_artifacts(
    target: Path,
    manifest: RunManifest,
    rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    *,
    include_cases: bool = True,
) -> None:
    """写产物；``include_cases=False``（holdout 聚合）不写 ``cases.jsonl``。"""
    _write_json(target / "run_manifest.json", manifest.to_dict())
    if include_cases:
        payload = "".join(
            json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        )
        (target / "cases.jsonl").write_bytes(payload.encode("utf-8"))
    _write_json(target / "summary.json", summary)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    data = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.write_bytes(data.encode("utf-8"))


# --------------------------------------------------------------------------- #
# trace 工具
# --------------------------------------------------------------------------- #


def _annotate_trace_identity(trace: TraceContext, manifest: RunManifest) -> None:
    trace.annotate(
        dataset_version=manifest.dataset_version,
        run_id=manifest.run_id,
        index_revision=str(manifest.index_revision),
        manifest_sha256=manifest.corpus_manifest_sha256,
        pipeline_version=manifest.pipeline_version,
        config_hash=manifest.config_hash,
    )


def _write_provenance_trace(
    case: CaseSpec,
    manifest: RunManifest,
    repo: TraceRepository,
    *,
    outcome: EvalOutcome | None = None,
    previous_trace_id: str | None = None,
    replayed: bool = False,
) -> str:
    """写一条无执行 Span 的 provenance Trace（OCR 跳过 / gold error / replay）。"""
    path = None if outcome is None else outcome.path
    with start_trace(
        http_request_id=f"{manifest.run_id}:{case.case_id}:provenance",
        mode=TraceMode.REPLAY if replayed else TraceMode.LOCAL,
        scope=manifest.scope,
        path=path,
        question=case.question,
        case_id=case.case_id,
        replayed=replayed,
        previous_trace_id=previous_trace_id,
        repo=repo,
    ) as trace:
        _annotate_trace_identity(trace, manifest)
        if outcome is not None:
            trace.set_outcome(outcome.kind)
    return trace.trace_id


def _read_trace(repo: TraceRepository, trace_id: str) -> Any:
    try:
        record, _spans = repo.get(trace_id)
    except KeyError:  # best-effort 写入失败：打分不编造运行时数值
        return None
    return record


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #


def _new_run_id(suite: str, mode: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{suite}-{mode}-{stamp}-{uuid.uuid4().hex[:8]}"


def _prepare_out_dir(out_dir: Path | None, run_id: str) -> Path:
    target = RUNS_ROOT / run_id if out_dir is None else Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    return target.resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _elapsed_ms(started_monotonic: float) -> int:
    return max(0, int(round((time.perf_counter() - started_monotonic) * 1000.0)))


def _sha256_file(path: Path) -> str:
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取文件 {path}: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()


def _required_doc_codes(cases: Sequence[CaseSpec]) -> tuple[str, ...]:
    """数据集 gold 引用到的 ``doc_code``（去重、确定性排序）。

    ``regression`` 语料层用它 fail closed：引用的资料必须全部解析成功，
    不让 gold 悄悄退化成 ``GoldUnresolved``。
    """
    codes = {
        str(ref["doc_code"])
        for case in cases
        for ref in (*case.expected_sources, *case.relevant_units)
        if ref.get("doc_code")
    }
    return tuple(sorted(codes))


def _single_business_date(cases: Sequence[CaseSpec]) -> str:
    dates = {case.business_date for case in cases}
    if len(dates) != 1:
        raise ValueError(f"同一数据集 business_date 必须唯一，收到 {sorted(dates)}")
    return next(iter(dates))


def _single_label_version(cases: Sequence[CaseSpec]) -> str:
    versions = {case.label_version for case in cases}
    if len(versions) != 1:
        raise ValueError(f"同一数据集 label_version 必须唯一，收到 {sorted(versions)}")
    return next(iter(versions))


def _config_hash(config: Any) -> str:
    payload = {
        name: getattr(config, name)
        for name in CONFIG_HASH_FIELDS
        if hasattr(config, name)
    }
    return _versioning_config_hash(payload)


def _unit_tuple(value: Any, case: CaseSpec, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _CaseError(
            "payload_invalid", f"{case.case_id}: {name} 必须是字符串数组"
        )
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise _CaseError(
                "payload_invalid", f"{case.case_id}: {name}[{index}] 必须是非空字符串"
            )
        items.append(item)
    return tuple(items)


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _read_cases_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取 cases.jsonl {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"cases.jsonl 不是 UTF-8: {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} 第 {line_number} 行 JSON 解析失败: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name} 第 {line_number} 行必须是 JSON 对象")
        if not payload.get("case_id"):
            raise ValueError(f"{path.name} 第 {line_number} 行缺少 case_id")
        rows.append(payload)
    return rows
