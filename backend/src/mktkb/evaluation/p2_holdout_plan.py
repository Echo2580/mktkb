"""P2-T207-FIX-A F1：H2（受限）计划生成器 —— 只看回合结构，不读题干/答案。

为什么必须单独一个生成器（fix-scope §F1）：计划项按 (operation, case_id, turn) 解析
（runner 的 plan_item_missing / live 的 attempt_item_unknown 都在**发送前**拒），而 H2 的
case_id 只存在于封存密文里。因此 H2 计划只能在封存/受控进程内、由"已知 case_id 与轮数"的
元数据生成，计划文件写在工作区外，仓库里只留 plan_sha256。

输入（都是元数据，不含题干/答案）：
- --cases-metadata：{"schema_version","dataset_version","cases":[{"case_id","turns"}]}
  由经理在运行期按 custodian-report 的 case_id/轮数准备，放在工作区外；
- --holdout-manifest：仓库内 repo-safe 元数据（30 题/36 回合/分层），用于**交叉校验**：
  题数、轮数、turn_histogram、以及 multi_turn 分层计数（cases with turns>=2）；
- --ingest-batches：本次 H2 语料包要花的 embedding 批数（保管方声明，见 cost §5 的 B<=68 包络）。

规则（固定、可审）：
- 每个 (case_id, turn) 生成 4 项：query_embedding / rerank / query_expansion / answer，各 1 次；
- 1 个 index_embedding 项，requests = --ingest-batches（未用的不花）；
- 不生成 OCR 项（H2 声明 requires_ocr 全 false；含 OCR 页就必须先改语料包声明并重算阶段额）；
- 中心 8.5/6.5/3/2（= 阶段 20.00，OCR 归属由公开矩阵占用），max_requests 默认 1100。

安全约束：
- 计划里出现 case_id 是**必须**的（runner 逐项解析），所以输出路径必须在仓库外；
  违反即以 plan_out_inside_workspace 拒绝（不写文件）；
- stdout 只打印 plan_sha256 与计数（题数/回合数/项数/请求数/金额），不打印 case_id；
- 本模块只读 metadata/manifest，不 import 解密路径、不读 key、不读题干。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .p2_contracts import (
    CHAT_COMPLETION_TOKENS_CAP,
    CHAT_HOST,
    CHAT_INPUT_PRICE_FLOOR,
    CHAT_MODEL,
    CHAT_OUTPUT_PRICE_FLOOR,
    CHAT_PRICING_SOURCE,
    CHAT_PROMPT_TOKENS_CAP,
    CHAT_PROVIDER,
    CHAT_REGION,
    EMBEDDING_MODEL,
    EMBEDDING_PRICING_SOURCE,
    EMBEDDING_PROVIDER,
    EMBEDDING_TOTAL_TOKENS_CAP,
    EMBEDDING_UNIT_PRICE_FLOOR,
    OPERATION_COST_CENTER,
    COST_CENTERS,
    P2_RUN_PLAN_SCHEMA_VERSION,
    P2RunPlan,
    RERANK_MODEL,
    RERANK_PRICING_SOURCE,
    RERANK_PROVIDER,
    RERANK_TOTAL_TOKENS_CAP,
    RERANK_UNIT_PRICE_FLOOR,
    P2_STAGE,
)
from .p2_dataset import P2Manifest

PROJECT_ROOT = Path(__file__).resolve().parents[4]
H2_CASES_METADATA_SCHEMA_VERSION = "p2-h2-cases-metadata/v0.1"
H2_PLAN_METADATA_KEYS = frozenset({"schema_version", "dataset_version", "cases"})
H2_CASE_KEYS = frozenset({"case_id", "turns"})
#: 阶段内四中心（与公开矩阵同一张 20.00 的阶段额度；见 PM/T207-cost-and-quota.md §4）。
H2_COST_CENTERS_CNY: Mapping[str, float] = {
    "answer_retrieval": 8.5,
    "ocr": 6.5,
    "judge": 3.0,
    "independent": 2.0,
}
H2_STAGE_LIMIT_CNY = 20.0
H2_PROJECT_TOTAL_LIMIT_CNY = 40.0
H2_MAX_REQUESTS = 1100
#: H2 语料包批数的请求包络上界（cost §5 的包络；实际批数由产品 chunker 离线实算，见 B）。
H2_MAX_INGEST_BATCHES = 68
#: H2 计划 id 的**单一来源**：CLI 默认值、候选 GO 的 scope.plan_id、runbook 命令都取这里。
#: T207-FIX-A-R1 阻断 2：此前 GO 写 P2-T207-H2-20261111、runbook/CLI 写 P2-H2-20261111，
#: 按文档生成会被 go_plan_id_mismatch 拒（fail-closed 但跑不通）。
H2_DEFAULT_PLAN_ID = "P2-T207-H2-20261111"
_CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
#: 每回合四项（operation, item_id 前缀）；顺序固定，便于逐项审。
TURN_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("query_embedding", "embed"),
    ("rerank", "rerank"),
    ("query_expansion", "expand"),
    ("answer", "answer"),
)


class HoldoutPlanError(ValueError):
    """H2 计划生成失败：稳定 code + 只含 id/计数（不回显题干）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = str(code)
        self.detail = str(detail)


def _chat_profile() -> dict[str, Any]:
    return {
        "kind": "chat",
        "model": CHAT_MODEL,
        "provider": CHAT_PROVIDER,
        "host": CHAT_HOST,
        "region": CHAT_REGION,
        "pricing_source": CHAT_PRICING_SOURCE,
        "input_price_per_million_cny": float(CHAT_INPUT_PRICE_FLOOR),
        "output_price_per_million_cny": float(CHAT_OUTPUT_PRICE_FLOOR),
        "prompt_tokens_cap": int(CHAT_PROMPT_TOKENS_CAP),
        "completion_tokens_cap": int(CHAT_COMPLETION_TOKENS_CAP),
    }


def _embedding_profile() -> dict[str, Any]:
    return {
        "kind": "embedding",
        "model": EMBEDDING_MODEL,
        "provider": EMBEDDING_PROVIDER,
        "host": "dashscope.aliyuncs.com",
        "region": "cn-beijing",
        "pricing_source": EMBEDDING_PRICING_SOURCE,
        "unit_price_per_million_cny": float(EMBEDDING_UNIT_PRICE_FLOOR),
        "total_tokens_cap": int(EMBEDDING_TOTAL_TOKENS_CAP),
    }


def _rerank_profile() -> dict[str, Any]:
    return {
        "kind": "rerank",
        "model": RERANK_MODEL,
        "provider": RERANK_PROVIDER,
        "host": "dashscope.aliyuncs.com",
        "region": "cn-beijing",
        "pricing_source": RERANK_PRICING_SOURCE,
        "unit_price_per_million_cny": float(RERANK_UNIT_PRICE_FLOOR),
        "total_tokens_cap": int(RERANK_TOTAL_TOKENS_CAP),
    }


def _item(
    item_id: str,
    operation: str,
    case_id: str,
    turn: int,
    requests: int,
    profile: Mapping[str, Any],
    expected: float,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "operation": operation,
        "cost_center": OPERATION_COST_CENTER[operation],
        "case_id": case_id,
        "turn": int(turn),
        "page": 0,
        "requests": int(requests),
        "price_profile": dict(profile),
        "expected_success_cny": float(expected),
    }


def load_holdout_manifest(path: Path | str) -> P2Manifest:
    """读 H2 manifest 并做严格解析（repo-safe 元数据；不触密文/不读 key）。"""
    import hashlib

    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise HoldoutPlanError("manifest_unreadable", type(exc).__name__) from None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HoldoutPlanError("manifest_json_invalid", target.name) from None
    try:
        return P2Manifest.from_dict(payload, manifest_sha256=hashlib.sha256(raw).hexdigest())
    except ValueError as exc:
        code = getattr(exc, "reason", None) or "manifest_invalid"
        raise HoldoutPlanError(str(code), str(getattr(exc, "detail", "") or "")) from None


def parse_cases_metadata(payload: Any) -> tuple[str, tuple[tuple[str, int], ...]]:
    """解析 --cases-metadata：只接受 {schema_version, dataset_version, cases[{case_id,turns}]}。"""
    if not isinstance(payload, Mapping):
        raise HoldoutPlanError("metadata_not_object", "")
    unknown = sorted(str(key) for key in set(payload) - H2_PLAN_METADATA_KEYS)
    if unknown:
        raise HoldoutPlanError("metadata_unknown_field", ",".join(unknown))
    missing = sorted(H2_PLAN_METADATA_KEYS - set(payload))
    if missing:
        raise HoldoutPlanError("metadata_missing_field", ",".join(missing))
    if str(payload.get("schema_version") or "") != H2_CASES_METADATA_SCHEMA_VERSION:
        raise HoldoutPlanError("metadata_schema_version_invalid", "")
    dataset_version = str(payload.get("dataset_version") or "").strip()
    if not dataset_version:
        raise HoldoutPlanError("metadata_dataset_version_missing", "")
    raw_cases = payload.get("cases")
    if isinstance(raw_cases, (str, bytes)) or not isinstance(raw_cases, Sequence):
        raise HoldoutPlanError("metadata_cases_invalid", "")
    if not raw_cases:
        raise HoldoutPlanError("metadata_cases_empty", "")
    parsed: list[tuple[str, int]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_cases):
        if not isinstance(item, Mapping):
            raise HoldoutPlanError("metadata_case_not_object", f"cases[{index}]")
        unknown_keys = sorted(str(key) for key in set(item) - H2_CASE_KEYS)
        if unknown_keys:
            # 题干/答案/标签这类字段一律拒绝：元数据只允许 case_id 与轮数。
            raise HoldoutPlanError("metadata_case_unknown_field", f"cases[{index}]:{unknown_keys}")
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or not _CASE_ID_RE.fullmatch(case_id):
            raise HoldoutPlanError("metadata_case_id_invalid", f"cases[{index}]")
        turns = item.get("turns")
        if isinstance(turns, bool) or not isinstance(turns, int) or turns < 1:
            raise HoldoutPlanError("metadata_turns_invalid", f"cases[{index}]")
        if case_id in seen:
            raise HoldoutPlanError("metadata_case_id_duplicate", f"cases[{index}]")
        seen.add(case_id)
        parsed.append((case_id, int(turns)))
    return dataset_version, tuple(parsed)


def crosscheck_metadata(
    dataset_version: str, cases: Sequence[tuple[str, int]], manifest: P2Manifest
) -> dict[str, Any]:
    """与 H2 manifest 交叉校验：题数/总轮数/最大轮数/histogram/multi_turn 分层。"""
    if str(dataset_version) != str(manifest.dataset_version):
        raise HoldoutPlanError("dataset_version_mismatch", "")
    if len(cases) != int(manifest.case_count):
        raise HoldoutPlanError("case_count_mismatch", f"{len(cases)} != {manifest.case_count}")
    histogram: dict[str, int] = {}
    for _case_id, turns in cases:
        histogram[str(turns)] = histogram.get(str(turns), 0) + 1
    expected_histogram = {
        str(key): int(value) for key, value in manifest.turn_stats["turn_histogram"].items()
    }
    if histogram != expected_histogram:
        raise HoldoutPlanError("turn_histogram_mismatch", "")
    total_turns = sum(turns for _case_id, turns in cases)
    if total_turns != int(manifest.turn_stats["total_turns"]):
        raise HoldoutPlanError("total_turns_mismatch", f"{total_turns}")
    max_turns = max(turns for _case_id, turns in cases)
    if max_turns != int(manifest.turn_stats["max_turns_per_case"]):
        raise HoldoutPlanError("max_turns_mismatch", f"{max_turns}")
    multi_turn_expected = int(manifest.strata.get("multi_turn", 0))
    multi_turn_actual = sum(1 for _case_id, turns in cases if turns >= 2)
    if multi_turn_expected and multi_turn_actual != multi_turn_expected:
        raise HoldoutPlanError(
            "multi_turn_stratum_mismatch", f"{multi_turn_actual} != {multi_turn_expected}"
        )
    return {
        "cases": len(cases),
        "total_turns": total_turns,
        "max_turns_per_case": max_turns,
        "turn_histogram": histogram,
        "multi_turn_cases": multi_turn_actual,
        "strata": {name: int(value) for name, value in manifest.strata.items()},
        "label_version": manifest.label_version,
    }


def assert_outside_workspace(path: Path | str, *, what: str = "输出") -> Path:
    """计划/元数据文件不得落在仓库内（计划里必然含 case_id）。"""
    target = Path(path).resolve(strict=False)
    root = PROJECT_ROOT.resolve()
    if target == root or root in target.parents:
        raise HoldoutPlanError("plan_out_inside_workspace", f"{what}必须写在工作区外：{target.name}")
    return target


def build_holdout_plan(
    *,
    cases: Sequence[tuple[str, int]],
    ingest_batches: int,
    plan_id: str,
    plan_version: str,
    created_utc: str,
    max_requests: int | str = H2_MAX_REQUESTS,
    cost_centers_cny: Mapping[str, float] | None = None,
    stage_limit_cny: float = H2_STAGE_LIMIT_CNY,
    project_total_limit_cny: float = H2_PROJECT_TOTAL_LIMIT_CNY,
    scenario_binding: Mapping[str, str] | None = None,
) -> P2RunPlan:
    """按 (case_id, turn) 生成 P2RunPlan；任何规模/额度不成立都在构造期拒绝。"""
    if isinstance(ingest_batches, bool) or not isinstance(ingest_batches, int):
        raise HoldoutPlanError("ingest_batches_invalid", "")
    if ingest_batches < 1:
        raise HoldoutPlanError("ingest_batches_invalid", "必须 >= 1")
    if ingest_batches > H2_MAX_INGEST_BATCHES:
        raise HoldoutPlanError(
            "ingest_batches_over_envelope", f"{ingest_batches} > {H2_MAX_INGEST_BATCHES}"
        )
    if not cases:
        raise HoldoutPlanError("metadata_cases_empty", "")
    items: list[dict[str, Any]] = [
        _item(
            "ingest-index-embedding",
            "index_embedding",
            "INGEST",
            1,
            ingest_batches,
            _embedding_profile(),
            0.0003,
        )
    ]
    for case_id, turns in cases:
        for turn in range(1, int(turns) + 1):
            for operation, prefix in TURN_OPERATIONS:
                if operation in {"query_embedding"}:
                    profile, expected = _embedding_profile(), 0.0003
                elif operation == "rerank":
                    profile, expected = _rerank_profile(), 0.001
                else:
                    profile, expected = _chat_profile(), 0.004
                items.append(
                    _item(
                        f"{prefix}-{case_id}-t{turn}",
                        operation,
                        case_id,
                        turn,
                        1,
                        profile,
                        expected,
                    )
                )
    document = {
        "schema_version": P2_RUN_PLAN_SCHEMA_VERSION,
        "plan_id": str(plan_id),
        "plan_version": str(plan_version),
        "mode": "end_to_end",
        "stage": P2_STAGE,
        "created_utc": str(created_utc),
        "project_total_limit_cny": float(project_total_limit_cny),
        "stage_limit_cny": float(stage_limit_cny),
        "max_requests": max_requests,
        "cost_centers_cny": {
            center: float((cost_centers_cny or H2_COST_CENTERS_CNY)[center])
            for center in COST_CENTERS
        },
        "items": items,
    }
    if scenario_binding is not None:
        document['scenario_binding'] = dict(scenario_binding)
    try:
        return P2RunPlan.from_dict(document)
    except ValueError as exc:
        raise HoldoutPlanError(
            str(getattr(exc, "reason", None) or "plan_invalid"),
            str(getattr(exc, "detail", "") or ""),
        ) from None


def summarize(plan: P2RunPlan) -> dict[str, Any]:
    """只回计数与金额（不含 case_id / item_id 之外的任何明文）。"""
    return {
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "cases": plan.case_count - 1,  # INGEST 伪 case 不计入题数
        "turns": plan.turn_count - 1,  # 同上
        "items": len(plan.items),
        "total_requests": plan.total_requests,
        "max_requests": plan.max_requests,
        "page_count": plan.page_count,
        "worst_case_cny": plan.worst_case_cny,
        "reserve_peak_cny": plan.reserve_peak_cny,
        "center_needs_cny": dict(plan.center_needs_cny()),
        "by_operation": plan.requests_by_operation(),
        "operations": list(plan.operations),
    }
