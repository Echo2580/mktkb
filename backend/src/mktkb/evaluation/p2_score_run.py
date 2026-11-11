"""P2-T207-FIX-A F5：run 产物 -> 逐题评分 -> 公开分母 / H2 聚合 / 观测矩阵的驱动。

背景（fix-scope §F5）：score_public_case / score_public_suites / aggregate_holdout /
build_gate_run 在 src 里只有定义、没有调用者 —— 跑完 p2-run 只得到产物，没有任何东西把它
变成 scorecard / 决策。本模块就是那层"只读产物"的接线：

- 公开：read run/cases.jsonl + run_manifest.json + summary.json -> 逐题 P2CaseScore
  -> score_public_suites（缺题/error/未执行如实出 block，不补不猜）-> scorecard.json；
  再走 build_gate_rows/build_gate_run/evaluate_p2_hard_gates/evaluate_p2_gate -> p2_decision.json。
- H2：在受控进程里 load_p2_dataset(visibility="holdout") 取 CaseSpec/分层，再用**封存目录内**
  的逐题行（或只有判定的 verdicts）算 P2HoldoutCaseScore -> aggregate_holdout，只写聚合。
- 矩阵：合并 R1/R2/R3 的逐题分数 + U 证据表 -> matrix_observation.json，明确
  composition=multi_run_scenario_isolated、release_decision=false、gate_config_unapproved。

纪律：
- 只读 run 产物，不重跑产品、不改判定；
- 缺产物/缺字段 -> 稳定 code + unknown（不猜 pass/fail）；
- H2 路径的输入文件必须在工作区外；聚合产物不得含 case_id/题干（交给 aggregate_holdout 兜底）；
- gate_v0_3 未审批 -> 决策必然是 unknown，不写 release。
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .dataset import CaseSpec, validate_case
from .p2_scoring import (
    CASE_STATUS_ERROR,
    CASE_STATUS_NOT_EXECUTED,
    CASE_STATUS_PASS,
    DECISION_BLOCKED,
    DECISION_PASS,
    DECISION_UNKNOWN,
    EXECUTION_MODE_LIVE,
    EXECUTION_MODE_LOCAL_MOCK,
    P2_B0_IDS,
    P2_BOUNDARY_IDS,
    P2_NEGATIVE_IDS,
    P2_UPDATE_DELETE_IDS,
    P2CaseScore,
    P2GateConfig,
    P2GateDecision,
    P2HoldoutCaseScore,
    P2HoldoutScorecard,
    P2PublicScorecard,
    P2ScoringError,
    P2ScoredCase,
    build_gate_rows,
    build_gate_run,
    citation_evidence_status,
    evaluate_p2_gate,
    evaluate_p2_hard_gates,
    load_p2_gate_config,
    normalize_product_outcome,
    score_public_case,
    score_public_suites,
)
from .p2_scoring import P2Block, SEVERITY_UNKNOWN
from .p2_scoring import aggregate_holdout
from .p2_scoring import P2_HOLDOUT_HARD_FAILURE_KINDS, P2_HOLDOUT_MAX_HARD_FAILURES, P2_HOLDOUT_MIN_PASS

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SCORE_BUNDLE_SCHEMA_VERSION = "p2-score-bundle/v0.1"
MATRIX_SCHEMA_VERSION = "p2-matrix-observation/v0.1"
U_CONTROLS_SCHEMA_VERSION = "p2-u-local-controls/v0.1"
HOLDOUT_VERDICTS_SCHEMA_VERSION = "p2-holdout-verdicts/v0.1"
DEFAULT_HOLDOUT_MANIFEST = PROJECT_ROOT / "docs" / "evaluation" / "p2-holdout-v2.manifest.json"
DEFAULT_U_CONTROLS_TEST = PROJECT_ROOT / "backend" / "tests" / "acceptance" / "test_t09_mutation.py"
#: U 行在 test_t09_mutation.py 里的命名约定：test_uNN_*（逐题一一对应）。
U_TEST_NAME_RE = re.compile(r"^test_u(?P<number>\d{2})_")
#: U 证据表里允许的 basis：R = 本矩阵内真实 smoke；L = 本地控制（product_mutation_test）。
BASIS_LOCAL = "L"
BASIS_REAL = "R"


class RunScoreError(ValueError):
    """驱动层可预期的失败：稳定 code（不吞产物、不猜判定）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = str(code)
        self.detail = str(detail)


# --------------------------------------------------------------------------- #
# 0. 只读产物
# --------------------------------------------------------------------------- #


def _read_json(path: Path, *, name: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise RunScoreError(f"{name}_missing", path.name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RunScoreError(f"{name}_invalid", path.name) from None
    if not isinstance(payload, Mapping):
        raise RunScoreError(f"{name}_invalid", path.name)
    return payload


def read_cases_jsonl(path: Path | str) -> dict[str, Mapping[str, Any]]:
    """读 run 的逐题行（只按 case_id 索引；重复 case_id 直接拒绝）。"""
    target = Path(path)
    if not target.is_file():
        raise RunScoreError("run_cases_missing", target.name)
    rows: dict[str, Mapping[str, Any]] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise RunScoreError("run_cases_invalid", target.name) from None
        if not isinstance(row, Mapping):
            raise RunScoreError("run_cases_invalid", target.name)
        case_id = str(row.get("case_id") or "")
        if not case_id:
            raise RunScoreError("run_cases_invalid", "缺少 case_id")
        if case_id in rows:
            raise RunScoreError("run_cases_duplicated", case_id)
        rows[case_id] = row
    return rows


def source_index_from_rows(
    rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """从 run 的 product.evidence 建 unit_id -> unit_key/locator 索引（只读、不发明身份）。

    product.sources 只给 source_id/文档名/版本号；单位级 unit_key 在 evidence 里
    （adapter.citation_evidence 的只读回执）。没有 evidence 就不建索引 —— 逐题打分
    会因此把"缺单位身份"如实判成 source_hit 不成立，而不是按文档名放行。
    """
    index: dict[str, dict[str, Any]] = {}
    for row in rows.values():
        for turn in row.get("turns") or ():
            if not isinstance(turn, Mapping):
                continue
            product = turn.get("product")
            if not isinstance(product, Mapping):
                continue
            raw = product.get("evidence")
            if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
                continue
            for item in raw:
                if not isinstance(item, Mapping):
                    continue
                unit_id = str(item.get("unit_id") or "").strip()
                if not unit_id:
                    continue
                index[unit_id] = {
                    "unit_key": None if item.get("unit_key") is None else str(item["unit_key"]),
                    "locator": dict(item.get("locator") or {}),
                }
    return index


def _execution_context(manifest: Mapping[str, Any], summary: Mapping[str, Any]) -> tuple[str, int]:
    """执行模式/真实调用数：live 必须显式（manifest.execution），真实数取**实测**出站。"""
    execution = str(manifest.get("execution") or "").strip()
    if execution == "live":
        network = summary.get("network") if isinstance(summary.get("network"), Mapping) else {}
        if network.get("available") is True and network.get("outbound_attempts") is not None:
            return EXECUTION_MODE_LIVE, int(network["outbound_attempts"])
        attempts = summary.get("attempts") if isinstance(summary.get("attempts"), Mapping) else {}
        counted = attempts.get("reserved")
        if counted is None:
            raise RunScoreError("network_measurement_unavailable", "live run 既无实测出站也无尝试计数")
        return EXECUTION_MODE_LIVE, int(counted)
    return EXECUTION_MODE_LOCAL_MOCK, 0


def load_cases_file(path: Path | str) -> tuple[CaseSpec, ...]:
    """读计划内的 CaseSpec JSONL（与 p2-run --cases 同一份；逐行 validate_case）。"""
    target = Path(path)
    if not target.is_file():
        raise RunScoreError("cases_missing", target.name)
    cases: list[CaseSpec] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            case = CaseSpec.from_dict(json.loads(line))
            validate_case(case)
        except ValueError as exc:
            raise RunScoreError("cases_invalid", str(exc)) from None
        cases.append(case)
    return tuple(cases)


def load_document_codes(path: Path | str) -> dict[str, str]:
    """显式映射：产品文档名 -> 数据集 doc_code（不猜、不自动生成）。"""
    payload = _read_json(Path(path), name="document_codes")
    mapping: dict[str, str] = {}
    for key, value in payload.items():
        name = str(key).strip()
        code = str(value).strip()
        if not name or not code:
            raise RunScoreError("document_codes_invalid", repr(key))
        mapping[name] = code
    if not mapping:
        raise RunScoreError("document_codes_invalid", "空映射")
    return mapping


# --------------------------------------------------------------------------- #
# 1. 公开矩阵：run 产物 -> scorecard + 决策
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RunScore:
    """一次 run 的评分结果（不含题干；case 行从这里安全聚合）。"""

    run_dir: Path
    run_id: str
    config_hash: str
    index_revision: int | None
    execution_mode: str
    real_calls: int
    scorecard: P2PublicScorecard
    scores: tuple[P2CaseScore, ...]
    decision: P2GateDecision | None = None
    #: gate 行需要的 outcome/result（不序列化；case_scores.json 只落 P2CaseScore）。
    scored: tuple[P2ScoredCase, ...] = dataclasses.field(default=(), repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCORE_BUNDLE_SCHEMA_VERSION,
            "run_dir": str(self.run_dir),
            "run_id": self.run_id,
            "config_hash": self.config_hash,
            "index_revision": self.index_revision,
            "execution_mode": self.execution_mode,
            "real_calls": int(self.real_calls),
            "scorecard": self.scorecard.to_dict(),
            "case_scores": [score.to_dict() for score in self.scores],
            "decision": None if self.decision is None else self.decision.to_dict(),
        }


def score_run(
    run_dir: Path | str,
    *,
    cases: Sequence[CaseSpec],
    document_codes: Mapping[str, str],
    source_index: Mapping[str, Mapping[str, Any]] | None = None,
    allowed_doc_codes: Iterable[str] | None = None,
    require_manifest_count: bool = True,
) -> RunScore:
    """只读 run 产物逐题打分；缺题/error/未执行如实记 not_executed（不补不猜）。"""
    root = Path(run_dir)
    manifest = _read_json(root / "run_manifest.json", name="run_manifest")
    summary = _read_json(root / "summary.json", name="run_summary")
    rows = read_cases_jsonl(root / "cases.jsonl")
    run_id = str(manifest.get("run_id") or "").strip()
    if not run_id:
        raise RunScoreError("run_id_missing", "run_manifest")
    config_hash = str(manifest.get("config_hash") or "").strip()
    if not config_hash:
        raise RunScoreError("config_hash_missing", "run_manifest")
    planned = len(cases)
    declared = manifest.get("case_count")
    if require_manifest_count and declared is not None and int(declared) != planned:
        raise RunScoreError(
            "case_count_mismatch", f"manifest={declared} planned={planned}（不给 --cases 换分母的机会）"
        )
    execution_mode, real_calls = _execution_context(manifest, summary)
    if source_index is None:
        source_index = source_index_from_rows(rows) or None
    issues: list[P2Block] = []
    if execution_mode == EXECUTION_MODE_LIVE and "available" in (
        summary.get("network") if isinstance(summary.get("network"), Mapping) else {}
    ) and summary["network"].get("available") is not True:
        issues.append(
            P2Block(
                "network_measurement_unavailable",
                SEVERITY_UNKNOWN,
                "live run 的网络边界未通过交叉校验：不把未核对的计数当真实调用数",
                {"run_id": run_id},
            )
        )
    unknown_rows = sorted(set(rows) - {case.case_id for case in cases})
    if unknown_rows:
        issues.append(
            P2Block(
                "run_case_outside_plan",
                SEVERITY_UNKNOWN,
                "run 产物里有计划外 case（分母不可信）",
                {"case_ids": unknown_rows[:10]},
            )
        )
    scored: list[P2ScoredCase] = []
    for case in cases:
        scored.append(
            score_public_case(
                case,
                rows.get(case.case_id),
                document_codes=document_codes,
                source_index=source_index,
                allowed_doc_codes=allowed_doc_codes,
                execution_mode=execution_mode,
                # 逐题**不虚构**真实调用归属：run 级实测值记在 bundle.real_calls，
                # 逐题一律 0（否则 N 题相加会把一次 run 的调用数放大 N 倍）。
                real_calls=0,
            )
        )
    scores = tuple(item.score for item in scored)
    scorecard = score_public_suites(scores, run_id=run_id, config_hash=config_hash)
    if issues:
        scorecard = dataclasses.replace(scorecard, blocks=tuple(scorecard.blocks) + tuple(issues))
    index_revision = manifest.get("index_revision")
    return RunScore(
        run_dir=root,
        run_id=run_id,
        config_hash=config_hash,
        index_revision=None if index_revision is None else int(index_revision),
        execution_mode=execution_mode,
        real_calls=real_calls,
        scorecard=scorecard,
        scores=scores,
        scored=tuple(scored),
    )


def decide_run(
    bundle: RunScore,
    *,
    cases: Sequence[CaseSpec],
    gate_config: P2GateConfig | None = None,
    citation_complete: bool | None = None,
) -> RunScore:
    """把 scorecard 接到既有 gate 链；gate_v0_3 未审批 -> unknown（不放行、不写 release）。"""
    root = Path(bundle.run_dir)
    manifest = _read_json(root / "run_manifest.json", name="run_manifest")
    summary = _read_json(root / "summary.json", name="run_summary")
    rows = read_cases_jsonl(root / "cases.jsonl")
    config = gate_config or load_p2_gate_config()
    scored = bundle.scored or _rescore_for_gate(cases, rows, bundle)
    gate_rows = build_gate_rows(cases, scored, document_codes=None)
    run_result = build_gate_run(
        run_dir=root,
        manifest=manifest,
        cases=cases,
        rows=gate_rows,
        summary=summary,
    )
    hard_gate = evaluate_p2_hard_gates(
        run_result,
        config=config,
        dataset_path=manifest.get("dataset_path") or None,
        require_trace=True,
    )
    if citation_complete is None:
        gate_payload = None
        gate_path = root / "gate.json"
        if gate_path.is_file():
            gate_payload = _read_json(gate_path, name="run_gate")
        recorded = None
        if isinstance(gate_payload, Mapping):
            citation = gate_payload.get("citation_evidence")
            if isinstance(citation, Mapping):
                recorded = bool(citation.get("complete"))
        recomputed = citation_evidence_status(gate_rows).get("complete") is True
        citation_complete = bool(recomputed and (recorded if recorded is not None else True))
    decision = evaluate_p2_gate(
        config=config,
        run_manifest=manifest,
        run_summary=summary,
        hard_gate=hard_gate,
        public=bundle.scorecard,
        holdout=None,
        citation_evidence_complete=bool(citation_complete),
        execution_mode=bundle.execution_mode,
        run_id=bundle.run_id,
    )
    return dataclasses.replace(bundle, decision=decision)


def _rescore_for_gate(
    cases: Sequence[CaseSpec],
    rows: Mapping[str, Mapping[str, Any]],
    bundle: RunScore,
) -> tuple[P2ScoredCase, ...]:
    """gate 行需要 outcome/result，故按同一口径重放逐题打分（只读、确定性）。"""
    document_codes: dict[str, str] = {}
    scored: list[P2ScoredCase] = []
    for case in cases:
        row = rows.get(case.case_id)
        scored.append(
            score_public_case(
                case,
                row,
                document_codes=document_codes,
                execution_mode=bundle.execution_mode,
                real_calls=bundle.real_calls,
            )
        )
    return tuple(scored)


def write_score_bundle(
    bundle: RunScore, out_dir: Path | str | None = None, *, write_decision: bool = True
) -> dict[str, Path]:
    """写 scorecard.json / case_scores.json /（有决策时）p2_decision.json。"""
    target = Path(out_dir) if out_dir is not None else Path(bundle.run_dir) / "score"
    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    scorecard_path = target / "scorecard.json"
    scorecard_path.write_text(
        json.dumps(bundle.scorecard.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    written["scorecard"] = scorecard_path
    scores_path = target / "case_scores.json"
    scores_path.write_text(
        json.dumps(
            {
                "schema_version": SCORE_BUNDLE_SCHEMA_VERSION,
                "run_id": bundle.run_id,
                "config_hash": bundle.config_hash,
                "index_revision": bundle.index_revision,
                "execution_mode": bundle.execution_mode,
                "real_calls": bundle.real_calls,
                "case_scores": [score.to_dict() for score in bundle.scores],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    written["case_scores"] = scores_path
    if write_decision and bundle.decision is not None:
        decision_path = target / "p2_decision.json"
        decision_path.write_text(
            json.dumps(bundle.decision.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written["p2_decision"] = decision_path
    return written


# --------------------------------------------------------------------------- #
# 2. H2（受限）：只输出聚合
# --------------------------------------------------------------------------- #


def load_holdout_dataset(manifest_path: Path | str | None = None) -> Any:
    """受限加载 H2 数据集（需要 MKTKB_P2_HOLDOUT_ROOT/KEY_FILE）；延迟导入避免默认触密文。"""
    from .p2_dataset import P2DatasetError, load_p2_dataset

    target = Path(manifest_path) if manifest_path is not None else DEFAULT_HOLDOUT_MANIFEST
    try:
        return load_p2_dataset(target, visibility="holdout")
    except P2DatasetError as exc:
        raise RunScoreError(str(exc.reason), exc.detail) from None


def holdout_case_scores_from_rows(
    cases: Sequence[CaseSpec],
    rows: Mapping[str, Mapping[str, Any]],
    *,
    document_codes: Mapping[str, str],
    source_index: Mapping[str, Mapping[str, Any]] | None = None,
    allowed_doc_codes: Iterable[str] | None = None,
    execution_mode: str = EXECUTION_MODE_LOCAL_MOCK,
    real_calls: int = 0,
) -> tuple[tuple[P2HoldoutCaseScore, ...], list[str]]:
    """用封存目录内的逐题行算 H2 单题判定；返回 (scores, 未分类的问题码)。"""
    scores: list[P2HoldoutCaseScore] = []
    unclassified: list[str] = []
    for case in cases:
        row = rows.get(case.case_id)
        item = score_public_case(
            case,
            row,
            document_codes=document_codes,
            source_index=source_index,
            allowed_doc_codes=allowed_doc_codes,
            execution_mode=execution_mode,
            real_calls=real_calls,
        )
        hard_failure = None
        for issue in item.score.issues:
            if issue.code in {
                "source_forbidden_document",
                "source_outside_run",
                "citation_not_unit_level",
                "source_not_active",
            }:
                # 这些是"来源/安全"类的结构问题，但具体硬失败类别要由封存标注方判定：
                # 驱动层不替它分类，只把它记进未分类清单（聚合必须带 block）。
                unclassified.append(issue.code)
                break
        scores.append(
            P2HoldoutCaseScore(
                case_id=case.case_id,
                stratum=str(case.stratum),
                status=item.score.status,
                hard_failure=hard_failure,
            )
        )
    return tuple(scores), unclassified


def holdout_case_scores_from_verdicts(
    cases: Sequence[CaseSpec], verdicts: Sequence[Mapping[str, Any]]
) -> tuple[P2HoldoutCaseScore, ...]:
    """用封存判定表（case_id/status/hard_failure）算 H2 单题结论；集合必须逐题对齐。"""
    by_id = {str(item.get("case_id") or ""): item for item in verdicts}
    expected = {case.case_id for case in cases}
    if set(by_id) != expected:
        missing = sorted(expected - set(by_id))
        extra = sorted(set(by_id) - expected)
        raise RunScoreError("holdout_verdicts_case_mismatch", f"missing={len(missing)} extra={len(extra)}")
    scores: list[P2HoldoutCaseScore] = []
    for case in cases:
        item = by_id[case.case_id]
        unknown = set(item) - {"case_id", "status", "hard_failure"}
        if unknown:
            raise RunScoreError("holdout_verdicts_invalid", f"未知字段 {sorted(unknown)}")
        hard_failure = item.get("hard_failure")
        if hard_failure is not None and str(hard_failure) not in P2_HOLDOUT_HARD_FAILURE_KINDS:
            raise RunScoreError("holdout_hard_failure_kind_invalid", str(hard_failure))
        scores.append(
            P2HoldoutCaseScore(
                case_id=case.case_id,
                stratum=str(case.stratum),
                status=str(item.get("status") or ""),
                hard_failure=None if hard_failure is None else str(hard_failure),
            )
        )
    return tuple(scores)


def aggregate_holdout_bundle(
    scores: Sequence[P2HoldoutCaseScore],
    *,
    expected_strata: Mapping[str, int] | None = None,
    min_pass: int = P2_HOLDOUT_MIN_PASS,
    hard_failures_max: int = P2_HOLDOUT_MAX_HARD_FAILURES,
    thresholds_approved: bool = False,
    execution_mode: str = EXECUTION_MODE_LOCAL_MOCK,
    real_calls: int = 0,
    run_id: str | None = None,
    config_hash: str | None = None,
    extra_blocks: Sequence[P2Block] = (),
) -> P2HoldoutScorecard:
    """折成聚合；任何"未分类/未核实"都作为 block 带进去（宁可 unknown，不冒充通过）。"""
    card = aggregate_holdout(
        scores,
        min_pass=int(min_pass),
        hard_failures_max=int(hard_failures_max),
        thresholds_approved=bool(thresholds_approved),
        expected_strata=expected_strata,
        execution_mode=execution_mode,
        real_calls=int(real_calls),
        run_id=run_id,
        config_hash=config_hash,
    )
    if extra_blocks:
        card = dataclasses.replace(card, blocks=tuple(card.blocks) + tuple(extra_blocks))
    return card


def load_holdout_verdicts(path: Path | str) -> tuple[dict[str, Any], ...]:
    """读封存判定表（JSONL，工作区外）；schema 只认 case_id/status/hard_failure。"""
    target = Path(path)
    if not target.is_file():
        raise RunScoreError("holdout_verdicts_missing", target.name)
    assert_outside_workspace(target, what="H2 判定表")
    verdicts: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise RunScoreError("holdout_verdicts_invalid", target.name) from None
        if not isinstance(row, Mapping):
            raise RunScoreError("holdout_verdicts_invalid", target.name)
        verdicts.append(dict(row))
    return tuple(verdicts)


def assert_outside_workspace(path: Path | str, *, what: str = "文件") -> Path:
    """H2 相关文件（计划/判定/逐题行）必须留在工作区外。"""
    target = Path(path).resolve(strict=False)
    root = PROJECT_ROOT.resolve()
    if target == root or root in target.parents:
        raise RunScoreError("holdout_path_inside_workspace", f"{what}不得落在仓库内：{target.name}")
    return target


# --------------------------------------------------------------------------- #
# 3. U 本地控制导出器（不改 test_t09_mutation.py）
# --------------------------------------------------------------------------- #


def parse_junit_controls(raw: str | bytes, *, source: str) -> dict[str, Any]:
    """把 junit XML 折成逐 U 的判定：同一 U 的所有用例都 pass 才算 pass。"""
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise RunScoreError("junit_invalid", source) from None
    cases: dict[str, dict[str, Any]] = {}
    for testcase in root.iter("testcase"):
        name = str(testcase.get("name") or "")
        match = U_TEST_NAME_RE.match(name)
        if match is None:
            continue
        case_id = f"U{match.group('number')}"
        outcome = "pass"
        detail = ""
        for child in testcase:
            tag = str(child.tag)
            if tag in {"failure", "error"}:
                outcome = "fail"
                detail = str(child.get("message") or "")[:120]
                break
            if tag == "skipped":
                outcome = "skipped"
                detail = str(child.get("message") or "")[:120]
        entry = cases.setdefault(case_id, {"case_id": case_id, "status": "pass", "tests": []})
        entry["tests"].append({"name": name, "status": outcome, "detail": detail})
        if outcome == "fail":
            entry["status"] = "fail"
        elif outcome == "skipped" and entry["status"] == "pass":
            entry["status"] = "skipped"
    return {
        "schema_version": U_CONTROLS_SCHEMA_VERSION,
        "source": source,
        "basis": BASIS_LOCAL,
        "cases": {case_id: cases[case_id] for case_id in sorted(cases)},
    }


def export_local_controls(
    out_path: Path | str,
    *,
    test_path: Path | str | None = None,
    pytest_args: Sequence[str] = (),
    python: str | None = None,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """跑既有 pytest 并导出逐 U 判定（不改测试、不新增 skip；junit XML 只是观测面）。"""
    target = Path(test_path) if test_path is not None else DEFAULT_U_CONTROLS_TEST
    if not target.is_file():
        raise RunScoreError("u_controls_test_missing", target.name)
    with tempfile.TemporaryDirectory(prefix="p2-u-controls-") as directory:
        junit = Path(directory) / "junit.xml"
        command = [
            python or sys.executable,
            "-m",
            "pytest",
            str(target),
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junit-xml={junit}",
            *pytest_args,
        ]
        # T207-FIX-A-R1：Windows 下 text=True 用 locale(cp936) 解码 pytest 的 UTF-8 输出，
        # 会在读取线程抛 UnicodeDecodeError（命令 exit 0/结果正确，但日志被污染）。
        # 两边都钉成 UTF-8：子进程 PYTHONIOENCODING 显式给定，父进程按 utf-8/replace 解码。
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=timeout_seconds,
        )
        if not junit.is_file():
            raise RunScoreError("u_controls_junit_missing", f"exit={completed.returncode}")
        payload = parse_junit_controls(
            junit.read_bytes(), source=str(target.relative_to(PROJECT_ROOT))
        )
    payload["exit_code"] = int(completed.returncode)
    payload["generated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_u_controls(path: Path | str) -> dict[str, Any]:
    payload = _read_json(Path(path), name="u_controls")
    cases = payload.get("cases")
    if not isinstance(cases, Mapping) or not cases:
        raise RunScoreError("u_controls_invalid", "cases")
    for case_id, item in cases.items():
        if not isinstance(item, Mapping) or str(item.get("status") or "") not in {
            "pass",
            "fail",
            "skipped",
        }:
            raise RunScoreError("u_controls_invalid", str(case_id))
    return dict(payload)


# --------------------------------------------------------------------------- #
# 4. 观测矩阵（多 run，明确非 release）
# --------------------------------------------------------------------------- #

MATRIX_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("b0", tuple(P2_B0_IDS)),
    ("negative", tuple(P2_NEGATIVE_IDS)),
    ("boundary", tuple(P2_BOUNDARY_IDS)),
    ("update_delete", tuple(P2_UPDATE_DELETE_IDS)),
)

#: U01 由 R2 的真实 smoke 提供；其余 U 行取本地控制（L）。
U_REAL_IDS = ("U01",)
U_LOCAL_IDS = tuple(f"U{i:02d}" for i in range(2, 11))


def _tally_rows(statuses: Iterable[str]) -> dict[str, int]:
    rows = list(statuses)
    return {
        "planned": len(rows),
        "passed": rows.count(CASE_STATUS_PASS),
        "failed": rows.count("fail"),
        "errors": rows.count(CASE_STATUS_ERROR),
        "not_executed": rows.count(CASE_STATUS_NOT_EXECUTED),
        "missing": rows.count("missing"),
    }


def build_matrix_observation(
    bundles: Sequence[RunScore],
    *,
    u_controls: Mapping[str, Any] | None = None,
    u_real_run: str = "R2",
) -> dict[str, Any]:
    """合并多次 run 的逐题分数 + U 证据表；明确 composition 与"非 release"。"""
    if not bundles:
        raise RunScoreError("matrix_runs_missing", "至少一次 run")
    by_case: dict[str, dict[str, Any]] = {}
    run_index: list[dict[str, Any]] = []
    for bundle in bundles:
        run_index.append(
            {
                "run_id": bundle.run_id,
                "run_dir": str(bundle.run_dir),
                "execution_mode": bundle.execution_mode,
                "real_calls": int(bundle.real_calls),
                "index_revision": bundle.index_revision,
                "config_hash": bundle.config_hash,
                "cases": len(bundle.scores),
                "decision": None if bundle.decision is None else bundle.decision.decision,
            }
        )
        for score in bundle.scores:
            if score.case_id in by_case:
                # 同一 case 出现在多个 run：以先到者为准并显式记重复（不静默覆盖）。
                by_case[score.case_id]["duplicated_in"].append(bundle.run_id)
                continue
            by_case[score.case_id] = {
                "case_id": score.case_id,
                "suite": score.suite,
                "stratum": score.stratum,
                "status": score.status,
                "run_id": bundle.run_id,
                "index_revision": bundle.index_revision,
                "config_hash": bundle.config_hash,
                "basis": BASIS_REAL,
                "execution_mode": score.execution_mode,
                "real_calls": int(score.real_calls),
                "duplicated_in": [],
            }
    tallies: dict[str, dict[str, int]] = {}
    for group, ids in MATRIX_GROUPS:
        tallies[group] = _tally_rows(
            by_case[case_id]["status"] if case_id in by_case else "missing" for case_id in ids
        )
    u_table: list[dict[str, Any]] = []
    for case_id in U_REAL_IDS:
        entry = by_case.get(case_id)
        u_table.append(
            {
                "case_id": case_id,
                "basis": BASIS_REAL,
                "status": None if entry is None else entry["status"],
                "run_id": None if entry is None else entry["run_id"],
                "source": f"real-run:{u_real_run}",
                "note": "计划绑定的有限真实更新 smoke（docs/fixtures U01 断言）",
            }
        )
    control_cases = (u_controls or {}).get("cases") or {}
    for case_id in U_LOCAL_IDS:
        item = control_cases.get(case_id) if isinstance(control_cases, Mapping) else None
        u_table.append(
            {
                "case_id": case_id,
                "basis": BASIS_LOCAL,
                "status": None if item is None else str(item.get("status")),
                "run_id": None,
                "source": None if u_controls is None else str(u_controls.get("source")),
                "note": "product_mutation_test 本地控制；不作为真实模型能力",
            }
        )
    u_statuses = [row["status"] or "missing" for row in u_table]
    tallies["u"] = _tally_rows(u_statuses)
    run_ids = {bundle.run_id for bundle in bundles}
    duplicated = {
        case_id: entry["duplicated_in"]
        for case_id, entry in by_case.items()
        if entry["duplicated_in"]
    }
    return {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "composition": "multi_run_scenario_isolated",
        "release_decision": False,
        "not_a_release_decision": True,
        "gate": {
            "decision": DECISION_UNKNOWN,
            "block_reason": "gate_config_unapproved",
            "why": "gate_v0_3 未审批；本矩阵只给执行观测值，放行权在 T209",
        },
        "runs": run_index,
        "run_ids": sorted(run_ids),
        "cases": sorted(by_case.values(), key=lambda item: item["case_id"]),
        "tallies": tallies,
        "u_table": u_table,
        "u_basis": {"R": list(U_REAL_IDS), "L": list(U_LOCAL_IDS)},
        "duplicated_cases": duplicated,
        "notes": [
            "R1/R2/R3 是三个独立 run（各自独立门、独立灌库）；同一 case 不跨 run 取最好成绩",
            "B0/N/C 行为 live run 产物；U01 取 R2 的真实 smoke，U02-U10 只取本地控制（L）",
            "本矩阵不得表述为 release/质量达标；baseline 与阈值由 T209 决定",
        ],
    }


def matrix_from_files(
    case_scores_paths: Sequence[Path | str],
    *,
    u_controls_path: Path | str | None = None,
) -> dict[str, Any]:
    """从 p2-score 落盘的 case_scores.json 组矩阵（不重跑产品、不重算判定）。"""
    bundles: list[RunScore] = []
    for path in case_scores_paths:
        payload = _read_json(Path(path), name="case_scores")
        scores = tuple(
            P2CaseScore(
                case_id=str(item["case_id"]),
                suite=str(item.get("suite") or ""),
                stratum=str(item.get("stratum") or ""),
                status=str(item["status"]),
                requires_ocr=bool(item.get("requires_ocr", False)),
                planned_turns=int(item.get("planned_turns") or 1),
                executed_turns=int(item.get("executed_turns") or 0),
                execution_mode=str(item.get("execution_mode") or EXECUTION_MODE_LOCAL_MOCK),
                real_calls=int(item.get("real_calls") or 0),
            )
            for item in payload.get("case_scores") or ()
            if isinstance(item, Mapping)
        )
        if not scores:
            raise RunScoreError("case_scores_empty", Path(path).name)
        bundles.append(
            RunScore(
                run_dir=Path(path).parent,
                run_id=str(payload.get("run_id") or ""),
                config_hash=str(payload.get("config_hash") or ""),
                index_revision=payload.get("index_revision"),
                execution_mode=str(payload.get("execution_mode") or EXECUTION_MODE_LOCAL_MOCK),
                real_calls=int(payload.get("real_calls") or 0),
                scorecard=score_public_suites(scores),
                scores=scores,
            )
        )
    u_controls = load_u_controls(u_controls_path) if u_controls_path is not None else None
    return build_matrix_observation(bundles, u_controls=u_controls)
