"""P1 T111：live 检索评测的配置接线、成本预检与运行 CLI。

本模块只负责“真实调用前”的接线，不执行检索循环（循环在
:mod:`mktkb.evaluation.runner` 的 live 分支）：

- 固定阶段 ``P1-RETRIEVAL`` / 服务 ``rag`` / 作用域 ``retrieval_only``；
- 从既有 ``.env`` 配置体系读取凭据（``DASHSCOPE_API_KEY``），**不打印、不落盘**；
- 用固定 GO + 共享账本 + ``budget.json`` 收敛闸门（``resolve_live_gate``），
  并把运行期 embedding/rerank 供应商配置逐项与 GO ``scope.bindings.rag`` 核对；
- 构造**只含 embedding/rerank** 的 :class:`RagConfig`（chat 字段保持空），
  从配置层保证 chat provider 不会被创建；
- 提供运行前成本预检（语料 embedding token 上界 + 每 case 1 次 query embedding
  + 1 次 rerank），超阶段剩余/单请求上限即拒绝；
- ``python -m mktkb.evaluation.live`` 是 pilot/预检入口：只跑单个 suite，
  pilot 上限 10 题，不做任何自动全量。

凭据只从 ``os.environ`` 或 ``.env`` 读取；异常文本只描述字段/状态，不回显值。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlsplit

from dotenv import dotenv_values

from ..live_authorization import (
    LiveAuthorization,
    LiveGateError,
    assert_provider_binding,
    load_live_authorization,
    resolve_live_gate,
)
from ..rag.budget import BudgetLedger
from ..rag.chunking import build_chunks
from ..rag.config import DEFAULT_EMBEDDING_BASE_URL, RagConfig, safe_config_summary
from ..rag.providers import MAX_EMBEDDING_REQUEST_TOKENS
from ..rag.settlement_policy import (
    EMBEDDING_TOTAL_TOKENS_CAP,
    SETTLEMENT_VERSION,
)
from .corpus import Corpus, default_corpus_dir, load_suite_corpus
from .dataset import CaseSpec, load_cases

__all__ = [
    "DEFAULT_ENV_FILE",
    "FROZEN_FULL_LIVE_DATASET",
    "LIVE_FULL_LIVE_CASES",
    "LIVE_FULL_LIVE_SUITE",
    "LIVE_MAX_PILOT_CASES",
    "LIVE_RETRIEVAL_LIMIT",
    "LIVE_SCOPE",
    "LIVE_SERVICE",
    "LIVE_STAGE",
    "LiveBudgetRefused",
    "LiveConfigError",
    "LiveCostEstimate",
    "LiveRuntime",
    "budget_snapshot",
    "httpx_compatible_proxy_env",
    "ledger_event_counts",
    "load_live_runtime",
    "main",
    "plan_live_cost",
    "validate_full_live_dataset",
    "validate_pilot_dataset",
]

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
#: P1 T112 全量 live 的唯一允许口径（默认关闭；打开只放行这一种）。
LIVE_FULL_LIVE_SUITE = "b0"
LIVE_FULL_LIVE_CASES = 40
FROZEN_FULL_LIVE_DATASET = PROJECT_ROOT / "fixtures" / "evaluation" / "b0.jsonl"

LIVE_STAGE = "P1-RETRIEVAL"
LIVE_SERVICE = "rag"
LIVE_SCOPE = "retrieval_only"
LIVE_MAX_PILOT_CASES = 10
#: 评测输出深度：Recall@10/MRR@10/nDCG@10 需要 top-10（不改变产品 top_k 配置）。
LIVE_RETRIEVAL_LIMIT = 10
TOTAL_LIMIT_ENV = "MKTKB_PROJECT_TOTAL_LIMIT_CNY"
STAGE_LIMIT_ENV = "MKTKB_RAG_STAGE_LIMIT_CNY"
MAX_REQUESTS_ENV = "MKTKB_RAG_MAX_REQUESTS"

#: 评测专用 chunk/rerank 参数（与 T004a offline 评测口径一致；仅 embedding batch 缩小，
#: 降低单请求 settlement cap 风险，不改变向量结果）。
EVAL_CHUNK_MAX_CHARS = 420
EVAL_CHUNK_MAX_UNITS = 3
EVAL_CHUNK_OVERLAP_UNITS = 1
EVAL_TOP_K = 8
EVAL_PAGE_SIZE = 10
EVAL_VECTOR_CANDIDATE_LIMIT = 50
EVAL_RERANK_TOP_N = 10
EVAL_EMBEDDING_BATCH_SIZE = 5


class LiveConfigError(ValueError):
    """live 配置/授权/预检失败（调用方必须在首个真实请求前拒绝）。"""


class LiveBudgetRefused(LiveConfigError):
    """成本预检拒绝（超阶段剩余/请求上限/单请求上限）。"""


@dataclass(frozen=True)
class LiveRuntime:
    """已通过 GO/预算校验的 live 运行期；``repr`` 不含任何凭据。"""

    config: RagConfig
    budget: Any
    stage: str
    service: str
    stage_limit_cny: float
    max_requests: int
    max_request_cny: float
    authorization: LiveAuthorization | None
    ledger_path: Path | None
    budget_path: Path | None
    go_path: Path | None
    credentials_source: str
    #: 仅测试注入：生产为 None，由 ``RagIndex`` 构造真实 provider。
    embedder: Any | None = None
    reranker: Any | None = None

    def __repr__(self) -> str:  # 不包含 config/Key
        return (
            f"LiveRuntime(stage={self.stage!r}, service={self.service!r}, "
            f"stage_limit_cny={self.stage_limit_cny!r})"
        )


@dataclass(frozen=True)
class LiveCostEstimate:
    """运行前保守成本预检结果（CNY；不是供应商账单）。"""

    suite: str
    case_count: int
    documents: int
    chunks: int
    embedding_requests: int
    query_embedding_requests: int
    rerank_requests: int
    total_requests: int
    embedding_index_cny: float
    query_embedding_cny: float
    rerank_cny: float
    estimated_cny: float
    max_single_reserve_cny: float
    stage_remaining_cny: float
    request_remaining: int
    max_request_cny: float
    reasons: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return not self.reasons

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "case_count": self.case_count,
            "documents": self.documents,
            "chunks": self.chunks,
            "estimated_cny": round(self.estimated_cny, 8),
            "embedding_index_cny": round(self.embedding_index_cny, 8),
            "query_embedding_cny": round(self.query_embedding_cny, 8),
            "rerank_cny": round(self.rerank_cny, 8),
            "embedding_requests": self.embedding_requests,
            "query_embedding_requests": self.query_embedding_requests,
            "rerank_requests": self.rerank_requests,
            "total_requests": self.total_requests,
            "max_single_reserve_cny": round(self.max_single_reserve_cny, 8),
            "stage_remaining_cny": round(self.stage_remaining_cny, 8),
            "request_remaining": int(self.request_remaining),
            "max_request_cny": round(self.max_request_cny, 8),
            "accepted": self.accepted,
            "reasons": list(self.reasons),
            "basis": (
                "语料 chunk 文本 UTF-8 字节数作 token 上界 + 每题 1 次 query embedding "
                "+ 每题 1 次 rerank（按请求预留上界）；不是供应商账单"
            ),
        }

    def assert_accepted(self) -> None:
        if self.reasons:
            raise LiveBudgetRefused(
                "live 成本预检拒绝："
                + ", ".join(self.reasons)
                + f"；估算 {self.estimated_cny:.8f} 元（含单请求预留 "
                f"{self.max_single_reserve_cny:.8f}），阶段剩余 "
                f"{self.stage_remaining_cny:.8f} 元，请求剩余 {self.request_remaining}"
            )


# --------------------------------------------------------------------------- #
# 凭据与闸门
# --------------------------------------------------------------------------- #


def _dotenv_map(env_file: Path | None) -> dict[str, str]:
    if env_file is None:
        return {}
    path = Path(env_file)
    if not path.is_file():
        return {}
    try:
        values = dotenv_values(path)
    except Exception as exc:  # noqa: BLE001 - 解析失败默认拒绝，且不回显文件内容
        raise LiveConfigError(f".env 不可解析：{type(exc).__name__}") from None
    return {str(key): str(value) for key, value in values.items() if value is not None}


def _credential(env: Mapping[str, str], dotenv: Mapping[str, str], name: str) -> tuple[str, str]:
    value = str(env.get(name) or "").strip()
    if value:
        return value, "environment"
    value = str(dotenv.get(name) or "").strip()
    if value:
        return value, "env_file"
    raise LiveConfigError(f"缺少 {name}（环境变量或 .env），拒绝真实调用")


def _env_positive_float(env: Mapping[str, str], name: str) -> float | None:
    raw = env.get(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        raise LiveConfigError(f"{name} 必须是有限正数") from None
    if not math.isfinite(value) or value <= 0:
        raise LiveConfigError(f"{name} 必须是有限正数")
    return value


def _env_positive_int(env: Mapping[str, str], name: str) -> int | None:
    raw = env.get(name)
    if raw is None or not str(raw).strip():
        return None
    text = str(raw).strip()
    if not text.isdigit() or int(text) <= 0:
        raise LiveConfigError(f"{name} 必须是正整数")
    return int(text)


def _cny(tokens: float, price_per_million: float) -> float:
    return float(tokens) * float(price_per_million) / 1_000_000.0


@contextmanager
def httpx_compatible_proxy_env() -> Iterator[None]:
    """临时移除 ``NO_PROXY`` 里 httpx 0.28.1 无法解析的 IPv6 条目。

    某些 Windows/代理客户端会把 ``[::1]`` 写进 ``NO_PROXY``；httpx 0.28.1 的
    ``URLPattern`` 会在构造 ``Client`` 时把它当 URL 解析并抛
    ``InvalidURL: Invalid port``（与供应商/业务代码无关）。T111 运行器只在 live
    索引/检索期间临时去掉括号 IPv6 与 ``::1`` 条目，保留 localhost/127.0.0.1 等
    原有 bypass；结束后逐值恢复，不改变长期环境。
    """
    names = ("NO_PROXY", "no_proxy")
    saved = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            value = saved[name]
            if not value:
                continue
            cleaned = [
                item.strip()
                for item in value.split(",")
                if item.strip()
                and not item.strip().startswith("[")
                and item.strip() != "::1"
            ]
            os.environ[name] = ",".join(cleaned)
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def embedding_reserve_cny(config: RagConfig) -> float:
    """单次 embedding 请求预留（官方单请求 81,920 token × 费率）。"""
    return _cny(MAX_EMBEDDING_REQUEST_TOKENS, config.embedding_price_per_million_cny)


def rerank_reserve_cny(config: RagConfig) -> float:
    """单次 rerank 请求预留（请求 token 上限 × 费率）。"""
    return max(
        0.001,
        _cny(config.rerank_max_request_tokens, config.rerank_price_per_million_cny),
    )


def _provider_region(host: str) -> str:
    return {
        "dashscope.aliyuncs.com": "beijing",
        "dashscope-intl.aliyuncs.com": "intl",
    }.get(host, "unknown")


def _assert_live_bindings(authorization: LiveAuthorization, config: RagConfig) -> None:
    host = urlsplit(config.embedding_base_url).hostname or ""
    try:
        assert_provider_binding(
            authorization,
            LIVE_SERVICE,
            base_url_host=host,
            embedding_provider="bailian",
            embedding_model=config.embedding_model,
            embedding_dimensions=config.embedding_dimensions,
            embedding_host=host,
            embedding_region="cn-beijing",
            rerank_provider="bailian",
            rerank_model=config.rerank_model,
            rerank_host=host,
            rerank_region="cn-beijing",
            region=_provider_region(host),
            settlement_version=SETTLEMENT_VERSION,
        )
    except LiveGateError as exc:
        raise LiveConfigError(f"GO 供应商绑定不匹配：{exc}") from None


def _live_config(
    *,
    gate: Any,
    data_dir: Path,
    business_date: str | None,
    embedding_key: str,
    rerank_key: str,
    base_url: str,
) -> RagConfig:
    return RagConfig(
        provider_mode="live",
        data_dir=Path(data_dir),
        business_date=business_date,
        embedding_base_url=base_url,
        rerank_base_url=base_url,
        embedding_api_key=embedding_key,
        rerank_api_key=rerank_key,
        embedding_batch_size=EVAL_EMBEDDING_BATCH_SIZE,
        embedding_timeout_seconds=30.0,
        rerank_timeout_seconds=30.0,
        chunk_max_chars=EVAL_CHUNK_MAX_CHARS,
        chunk_max_units=EVAL_CHUNK_MAX_UNITS,
        chunk_overlap_units=EVAL_CHUNK_OVERLAP_UNITS,
        top_k=EVAL_TOP_K,
        page_size=EVAL_PAGE_SIZE,
        vector_candidate_limit=EVAL_VECTOR_CANDIDATE_LIMIT,
        rerank_top_n=EVAL_RERANK_TOP_N,
        max_request_cny=gate.max_request_cny,
        max_retries=0,
        require_zero_retries=True,
        # chat 字段保持空：RagIndex 不会构造任何 chat provider。
        chat_model="",
        chat_base_url="",
        chat_api_key="",
        stage=gate.stage,
        stage_limit_cny=gate.stage_limit_cny,
        budget_ledger_path=gate.ledger_path,
        budget_json_path=gate.budget_path,
    )


def load_live_runtime(
    *,
    data_dir: Path,
    business_date: str | None,
    run_id: str | None = None,
    stage: str = LIVE_STAGE,
    service: str = LIVE_SERVICE,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
    go_path: Path | None = None,
    ledger_path: Path | None = None,
    budget_path: Path | None = None,
    request_bound_cny: float | None = None,
) -> LiveRuntime:
    """加载 live 运行期：总上限 → GO → 共享预算 → 凭据 → 供应商绑定。

    任一步失败都在首个真实请求前抛 :class:`LiveConfigError`；异常文本不含 Key。
    """
    env = os.environ if environ is None else environ
    if not str(env.get(TOTAL_LIMIT_ENV) or "").strip():
        raise LiveConfigError(
            f"必须显式设置 {TOTAL_LIMIT_ENV}=20.0（与共享预算 limit_cny 相等）"
        )
    try:
        authorization = load_live_authorization(
            stage=stage, service=service, go_path=go_path, ledger_path=ledger_path
        )
    except LiveGateError as exc:
        raise LiveConfigError(f"GO 授权拒绝：{exc}") from None
    stage_limit = _env_positive_float(env, STAGE_LIMIT_ENV) or authorization.stage_limit_cny
    max_requests = (
        _env_positive_int(env, MAX_REQUESTS_ENV) or authorization.max_requests
    )
    bound = (
        float(request_bound_cny)
        if request_bound_cny is not None
        else _cny(
            MAX_EMBEDDING_REQUEST_TOKENS,
            RagConfig().embedding_price_per_million_cny,
        )
    )
    try:
        gate = resolve_live_gate(
            stage=stage,
            service=service,
            requested_stage_limit_cny=stage_limit,
            requested_max_requests=max_requests,
            request_bound_cny=bound,
            go_path=go_path,
            ledger_path=ledger_path,
            budget_path=budget_path,
        )
    except LiveGateError as exc:
        raise LiveConfigError(f"GO/预算闸门拒绝：{exc}") from None

    dotenv = _dotenv_map(env_file)
    embedding_key, embedding_source = _credential(env, dotenv, "DASHSCOPE_API_KEY")
    rerank_key, rerank_source = _credential(env, dotenv, "DASHSCOPE_API_KEY")
    source = embedding_source if embedding_source == rerank_source else "mixed"
    base_url = str(
        env.get("DASHSCOPE_BASE_URL")
        or dotenv.get("DASHSCOPE_BASE_URL")
        or DEFAULT_EMBEDDING_BASE_URL
    ).rstrip("/")
    config = _live_config(
        gate=gate,
        data_dir=Path(data_dir),
        business_date=business_date,
        embedding_key=embedding_key,
        rerank_key=rerank_key,
        base_url=base_url,
    )
    _assert_live_bindings(gate.authorization, config)
    budget = BudgetLedger(
        gate.ledger_path,
        gate.budget_path,
        stage=gate.stage,
        stage_limit_cny=gate.stage_limit_cny,
        max_requests=gate.max_requests,
        run_id=run_id,
        request_guard=gate.refresh_limits,
        post_reserve_guard=gate.recheck_after_reserve,
    )
    return LiveRuntime(
        config=config,
        budget=budget,
        stage=gate.stage,
        service=gate.service,
        stage_limit_cny=gate.stage_limit_cny,
        max_requests=gate.max_requests,
        max_request_cny=gate.max_request_cny,
        authorization=gate.authorization,
        ledger_path=gate.ledger_path,
        budget_path=gate.budget_path,
        go_path=gate.go_path,
        credentials_source=source,
    )


# --------------------------------------------------------------------------- #
# 成本预检
# --------------------------------------------------------------------------- #


def _batch_cost_cny(
    tokens: float,
    *,
    price_per_million: float,
    cap_tokens: int,
    reserve_cny: float,
) -> float:
    """token 上界对应的保守结算金额；超过 settlement cap 时按全额预留计。"""
    if tokens > cap_tokens:
        return reserve_cny
    return _cny(tokens, price_per_million)


def plan_live_cost(
    corpus: Corpus,
    cases: Sequence[CaseSpec],
    config: RagConfig,
    *,
    stage_remaining_cny: float,
    request_remaining: int,
    max_request_cny: float,
) -> LiveCostEstimate:
    """运行前保守估算（不调用供应商、不写账本）。"""
    embedding_price = config.embedding_price_per_million_cny
    embedding_reserve = embedding_reserve_cny(config)
    rerank_reserve = rerank_reserve_cny(config)
    chunks_total = 0
    embedding_requests = 0
    embedding_index_cny = 0.0
    batch_size = max(1, int(config.embedding_batch_size))
    for spec, units in corpus.documents:
        chunks = build_chunks(spec, units, config)
        chunks_total += len(chunks)
        for offset in range(0, len(chunks), batch_size):
            batch = chunks[offset : offset + batch_size]
            tokens = sum(len(chunk.text.encode("utf-8")) for chunk in batch)
            embedding_requests += 1
            embedding_index_cny += _batch_cost_cny(
                tokens,
                price_per_million=embedding_price,
                cap_tokens=EMBEDDING_TOTAL_TOKENS_CAP,
                reserve_cny=embedding_reserve,
            )
    query_cases = [case for case in cases if not case.requires_ocr]
    query_embedding_cny = 0.0
    for case in query_cases:
        tokens = len(case.question.encode("utf-8"))
        query_embedding_cny += _batch_cost_cny(
            tokens,
            price_per_million=embedding_price,
            cap_tokens=EMBEDDING_TOTAL_TOKENS_CAP,
            reserve_cny=embedding_reserve,
        )
    query_requests = len(query_cases)
    rerank_requests = len(query_cases)
    rerank_cny = rerank_reserve * rerank_requests
    estimated = embedding_index_cny + query_embedding_cny + rerank_cny
    total_requests = embedding_requests + query_requests + rerank_requests
    max_single_reserve = max(embedding_reserve, rerank_reserve)
    reasons: list[str] = []
    if estimated + max_single_reserve > stage_remaining_cny + 1e-12:
        reasons.append("stage_remaining_insufficient")
    if total_requests > request_remaining:
        reasons.append("request_limit_insufficient")
    if max_single_reserve > max_request_cny + 1e-12:
        reasons.append("single_request_cap_exceeded")
    return LiveCostEstimate(
        suite=corpus.suite,
        case_count=len(cases),
        documents=len(corpus.documents),
        chunks=chunks_total,
        embedding_requests=embedding_requests,
        query_embedding_requests=query_requests,
        rerank_requests=rerank_requests,
        total_requests=total_requests,
        embedding_index_cny=embedding_index_cny,
        query_embedding_cny=query_embedding_cny,
        rerank_cny=rerank_cny,
        estimated_cny=estimated,
        max_single_reserve_cny=max_single_reserve,
        stage_remaining_cny=stage_remaining_cny,
        request_remaining=int(request_remaining),
        max_request_cny=max_request_cny,
        reasons=tuple(reasons),
    )


# --------------------------------------------------------------------------- #
# 预算/账本摘要（可写入证据；不含凭据、不写整本 sha）
# --------------------------------------------------------------------------- #


def budget_snapshot(summary: Any) -> dict[str, Any]:
    """把 ``BudgetSummary`` 转成可 JSON 序列化的保守口径摘要。"""

    def number(name: str) -> float | None:
        value = getattr(summary, name, None)
        if value is None:
            return None
        try:
            return round(float(value), 8)
        except (TypeError, ValueError):
            return None

    def integer(name: str) -> int | None:
        value = getattr(summary, name, None)
        return None if value is None else int(value)

    return {
        "stage": getattr(summary, "stage", None),
        "stage_limit_cny": number("stage_limit_cny"),
        "stage_accounted_cny": number("stage_accounted_cny"),
        "stage_remaining_cny": number("stage_remaining_cny"),
        "total_limit_cny": number("total_limit_cny"),
        "historical_conservative_cny": number("historical_conservative_cny"),
        "accounted_cny": number("accounted_cny"),
        "remaining_cny": number("remaining_cny"),
        "success_estimated_list_price_cny": number("success_estimated_list_price_cny"),
        "provider_billed_cny": number("provider_billed_cny"),
        "reservation_count": integer("reservation_count"),
        "result_count": integer("result_count"),
    }


def ledger_event_counts(ledger_path: Path | None, run_id: str | None) -> dict[str, Any] | None:
    """按 ``run_id`` 统计账本事件类型/kind（零 chat 证明）；不返回事件原文。"""
    if ledger_path is None or run_id is None:
        return None
    path = Path(ledger_path)
    if not path.is_file():
        return None
    reserved: Counter[str] = Counter()
    results: Counter[str] = Counter()
    matched = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"error": "ledger_unreadable"}
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return {"error": "ledger_not_jsonl"}
        if not isinstance(event, dict) or event.get("run_id") != run_id:
            continue
        matched += 1
        kind = str(event.get("kind") or "")
        if event.get("event") == "reserved":
            reserved[kind] += 1
        elif event.get("event") == "result":
            results[kind] += 1
    return {
        "matched_events": matched,
        "reserved": dict(sorted(reserved.items())),
        "results": dict(sorted(results.items())),
        "chat_reserved": int(reserved.get("chat", 0)),
        "chat_results": int(results.get("chat", 0)),
    }


# --------------------------------------------------------------------------- #
# pilot 数据集校验 / 预检
# --------------------------------------------------------------------------- #


def validate_pilot_dataset(cases: Sequence[CaseSpec], pilot_cases: int | None) -> None:
    """pilot 只允许 1–10 题，且数据集文件必须恰好是这 N 题。"""
    if pilot_cases is None:
        raise LiveConfigError(
            "live 全量需要主人放行（allow_full_live=True）；T111 只允许 pilot ≤10 题"
        )
    if isinstance(pilot_cases, bool) or not isinstance(pilot_cases, int):
        raise LiveConfigError("pilot_cases 必须是整数")
    if not 1 <= pilot_cases <= LIVE_MAX_PILOT_CASES:
        raise LiveConfigError(
            f"pilot_cases 必须在 1–{LIVE_MAX_PILOT_CASES}，收到 {pilot_cases}"
        )
    if len(cases) != pilot_cases:
        raise LiveConfigError(
            f"pilot 数据集必须恰好 {pilot_cases} 题（当前 {len(cases)} 题）；"
            "请用独立子集文件，避免只跑前 N 题却绑定全量 dataset_sha256"
        )


def _sha256_file(path: Path) -> str:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise LiveConfigError(f"数据集不可读：{Path(path)}（{type(exc).__name__}）") from None
    return hashlib.sha256(data).hexdigest()


def validate_full_live_dataset(
    *,
    suite: str,
    dataset_path: Path | str,
    cases: Sequence[CaseSpec],
) -> str:
    """全量 live 守卫：仅 b0 + 冻结 ``b0.jsonl`` 字节级 sha256 + 恰好 40 题。

    返回冻结数据集的 sha256（可写入证据；不含题目/答案原文）。默认关闭的全量开关
    由调用方（``run_suite`` / ``preview_live_run``）决定是否调用本函数。
    """
    if suite != LIVE_FULL_LIVE_SUITE:
        raise LiveConfigError(
            f"全量 live 只允许 suite={LIVE_FULL_LIVE_SUITE!r}，收到 {suite!r}"
        )
    if len(cases) != LIVE_FULL_LIVE_CASES:
        raise LiveConfigError(
            f"全量 live 必须恰好 {LIVE_FULL_LIVE_CASES} 题，收到 {len(cases)} 题"
        )
    frozen = FROZEN_FULL_LIVE_DATASET
    if not frozen.is_file():
        raise LiveConfigError(f"冻结数据集不存在：{frozen}")
    expected = _sha256_file(frozen)
    actual = _sha256_file(Path(dataset_path))
    if actual != expected:
        raise LiveConfigError(
            "全量 live 数据集必须与冻结 b0.jsonl 字节级一致："
            f"sha256={actual[:12]}… != {expected[:12]}…"
        )
    return expected


def _single_business_date(cases: Sequence[CaseSpec]) -> str:
    dates = {case.business_date for case in cases}
    if len(dates) != 1:
        raise LiveConfigError(f"同一数据集 business_date 必须唯一，收到 {sorted(dates)}")
    return next(iter(dates))


def _single_label_version(cases: Sequence[CaseSpec]) -> str:
    versions = {case.label_version for case in cases}
    if len(versions) != 1:
        raise LiveConfigError(f"同一数据集 label_version 必须唯一，收到 {sorted(versions)}")
    return next(iter(versions))


def _required_doc_codes(cases: Sequence[CaseSpec]) -> tuple[str, ...]:
    codes = {
        str(ref["doc_code"])
        for case in cases
        for ref in (*case.expected_sources, *case.relevant_units)
        if isinstance(ref, Mapping) and ref.get("doc_code")
    }
    return tuple(sorted(codes))


def preview_live_run(
    *,
    suite: str,
    dataset_path: Path,
    pilot_cases: int | None,
    allow_full_live: bool = False,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
) -> tuple[LiveCostEstimate, dict[str, Any]]:
    """只读预检：GO/账本/凭据/绑定 + 成本估算；零预留、零 HTTP。"""
    cases = load_cases(dataset_path)
    if allow_full_live:
        if pilot_cases is not None:
            raise LiveConfigError(
                "--allow-full-live 与 --pilot 互斥：全量预检不接受 pilot 题数"
            )
        validate_full_live_dataset(suite=suite, dataset_path=dataset_path, cases=cases)
    else:
        validate_pilot_dataset(cases, pilot_cases)
    business_date = _single_business_date(cases)
    corpus = load_suite_corpus(
        suite,
        default_corpus_dir(suite),
        business_date=business_date,
        required_codes=_required_doc_codes(cases),
    )
    runtime = load_live_runtime(
        data_dir=PROJECT_ROOT / "var" / "eval" / "runs" / "preview" / "index",
        business_date=business_date,
        environ=environ,
        env_file=env_file,
    )
    before = budget_snapshot(runtime.budget.summary())
    estimate = plan_live_cost(
        corpus,
        cases,
        runtime.config,
        stage_remaining_cny=float(before["stage_remaining_cny"] or 0.0),
        request_remaining=max(
            0, int(runtime.max_requests) - int(before["reservation_count"] or 0)
        ),
        max_request_cny=float(runtime.max_request_cny),
    )
    return estimate, {
        "stage": runtime.stage,
        "service": runtime.service,
        "scope": LIVE_SCOPE,
        "full_live": bool(allow_full_live),
        "budget_before": before,
        "credentials_source": runtime.credentials_source,
        "config": safe_config_summary(runtime.config),
        "go": None if runtime.authorization is None else runtime.authorization.as_dict(),
    }


# --------------------------------------------------------------------------- #
# CLI（pilot/预检；不自动全量）
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mktkb.evaluation.live",
        description="P1 live 检索评测（retrieval_only；pilot ≤10 题；默认零 chat）",
    )
    parser.add_argument("--suite", required=True, choices=("b0", "badcase", "regression"))
    parser.add_argument("--dataset", required=True, help="pilot 子集 JSONL（必须恰好 N 题）")
    parser.add_argument("--pilot", type=int, default=None, help="pilot 题数（1–10）")
    parser.add_argument(
        "--allow-full-live",
        action="store_true",
        help="显式放行 b0 全量 40 题（仅 suite=b0 + 冻结 b0.jsonl 字节级 sha + 40 题）",
    )
    parser.add_argument("--out", default=None, help="输出目录（默认 var/eval/runs/<run_id>）")
    parser.add_argument("--dry-run", action="store_true", help="只做 GO/账本/成本预检，不发请求")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="凭据 .env 路径")
    return parser


def _print_estimate(estimate: LiveCostEstimate, extra: Mapping[str, Any]) -> None:
    before = dict(extra.get("budget_before") or {})
    print(
        "mode=live scope=retrieval_only "
        f"suite={estimate.suite} cases={estimate.case_count} "
        f"full_live={str(bool(extra.get('full_live'))).lower()} dry_run=true"
    )
    print(
        f"stage={extra.get('stage')} stage_limit_cny={before.get('stage_limit_cny')} "
        f"stage_accounted_cny={before.get('stage_accounted_cny')} "
        f"stage_remaining_cny={before.get('stage_remaining_cny')} "
        f"reservations={before.get('reservation_count')}"
    )
    print(
        f"precheck accepted={str(estimate.accepted).lower()} "
        f"estimated_cny={estimate.estimated_cny:.8f} "
        f"embedding_index_cny={estimate.embedding_index_cny:.8f} "
        f"query_embedding_cny={estimate.query_embedding_cny:.8f} "
        f"rerank_cny={estimate.rerank_cny:.8f}"
    )
    print(
        f"precheck requests total={estimate.total_requests} "
        f"embedding_batches={estimate.embedding_requests} "
        f"query_embeddings={estimate.query_embedding_requests} "
        f"rerank={estimate.rerank_requests} "
        f"max_single_reserve_cny={estimate.max_single_reserve_cny:.8f} "
        f"reasons={','.join(estimate.reasons) or 'none'}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    environ = os.environ
    env_file = Path(args.env_file) if args.env_file else None
    dataset_path = Path(args.dataset)
    if args.dry_run:
        try:
            estimate, extra = preview_live_run(
                suite=args.suite,
                dataset_path=dataset_path,
                pilot_cases=args.pilot,
                allow_full_live=bool(args.allow_full_live),
                environ=environ,
                env_file=env_file,
            )
        except Exception as exc:  # noqa: BLE001 - CLI 边界：任何失败都拒绝且不回显凭据
            print(f"live precheck refused: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 3
        _print_estimate(estimate, extra)
        return 0 if estimate.accepted else 3

    from .runner import run_suite  # 延迟导入，避免 runner ↔ live 模块循环

    try:
        result = run_suite(
            args.suite,
            "live",
            scope=LIVE_SCOPE,
            out_dir=Path(args.out) if args.out else None,
            dataset_path=dataset_path,
            pilot_cases=args.pilot,
            allow_full_live=bool(args.allow_full_live),
            environ=environ,
            live_env_file=env_file,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 边界：任何失败都拒绝且不回显凭据
        print(f"live run refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    live = dict(result.summary.get("live") or {})
    precheck = dict(live.get("precheck") or {})
    before = dict(live.get("budget_before") or {})
    after = dict(live.get("budget_after") or {})
    metrics = dict(result.summary.get("metrics") or {})
    requests = dict(live.get("provider_requests") or {})
    attempts = dict(requests.get("attempts") or {})
    print(
        f"run_id={result.manifest.run_id} suite={result.manifest.suite} "
        f"mode={result.manifest.mode} scope={result.manifest.scope} "
        f"cases={len(result.cases)} out={result.out_dir}"
    )
    print(
        f"precheck_estimated_cny={precheck.get('estimated_cny')} "
        f"precheck_requests={precheck.get('total_requests')} "
        f"pilot={live.get('pilot')}"
    )
    print(
        f"ledger_stage={live.get('stage')} "
        f"stage_accounted_before={before.get('stage_accounted_cny')} "
        f"stage_accounted_after={after.get('stage_accounted_cny')} "
        f"stage_remaining_after={after.get('stage_remaining_cny')} "
        f"reservations_before={before.get('reservation_count')} "
        f"reservations_after={after.get('reservation_count')}"
    )
    print(
        f"provider_requests embedding={attempts.get('embedding', 0)} "
        f"rerank={attempts.get('rerank', 0)} chat={attempts.get('chat', 0)}"
    )
    print(
        "metrics "
        f"Recall@10={metrics.get('Recall@10')} "
        f"MRR@10={metrics.get('MRR@10')} "
        f"nDCG@10={metrics.get('nDCG@10')} "
        f"hard_filter_violation_rate={metrics.get('hard_filter_violation_rate')} "
        f"empty_recall_rate={metrics.get('empty_recall_rate')}"
    )
    print(f"aborted={str(bool(result.aborted)).lower()}")
    return 3 if result.aborted else 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
