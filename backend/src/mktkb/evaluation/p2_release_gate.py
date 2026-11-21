"""P2 正式跨场景门禁：单一入口（证据齐备性 / 质量门 / 主人发布决定三分离）。

用法（CLI 见 ``evaluation/cli.py`` 的 ``p2-release-gate``）::

    from mktkb.evaluation.p2_release_gate import evaluate_release_gate
    result = evaluate_release_gate("docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/inputs.json")

判定语义：

* 逐行判定（``ReleaseRow``）——缺证 / 未执行 / 必需未知 / 硬失败 / 版本不符 / 身份不符
  都用 ``p2_release_model`` 的固定原因码阻断；
* 总门（``decision``）——任一阻断即阻断；否则任一待交付即待交付；否则通过；
* **技术门不等于发布**：``release_allowed`` 恒为 ``False``，正式发布由主人决定；
  技术门只作为 T900 独立总验收的输入。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .p2_release_h2 import H2Evidence, assess_h2
from .p2_release_h2_aggregate import assess_h2_aggregate
from .p2_release_inputs import (
    GATE_SUITE_NAME,
    PENDING_SECTIONS,
    H2_SCENARIO_ORDER,
    ReleaseInputs,
    RunBinding,
    load_release_inputs,
)
from .p2_release_model import (
    DECISION_BLOCKED,
    DECISION_OBSERVED,
    DECISION_PASS,
    DECISION_PENDING,
    PENDING_MARKERS,
    R_CITATION_GROUNDING_MISSING,
    R_EVIDENCE_MISSING,
    R_HARD_FAILURE,
    R_INPUTS_INVALID,
    R_PENDING_INPUT,
    R_HARD_GATE_MIN_SAMPLE_UNMET,
    R_ROWS_INCOMPLETE,
    R_SAMPLE_BELOW_MIN,
    R_REQUIRED_UNKNOWN,
    RESULT_SCHEMA_VERSION,
    ReleaseGateError,
    ReleaseRow,
    file_sha256,
    gate_decision,
    payload_sha256,
    row_blocked,
    row_ok,
    row_pending,
)
from .p2_release_binding import assess_binding
from .p2_release_public import (
    B0Evidence,
    HardGateSource,
    SuiteEvidence,
    citation_grounding_gaps,
    cross_check_evidence_manifest,
    aggregate_hard_gates,
    assess_applicability,
    assess_b0,
    assess_suite,
    assess_u,
    collect_suite,
)
from .p2_scoring import P2_BOUNDARY_IDS, P2_NEGATIVE_IDS

#: 结果里明确标注的"等外部输入"的固定清单。
PENDING_TASK2_ROWS: tuple[str, ...] = (
    "h2",
    "h2.composition",
    "h2.source_proof",
    "h2.coverage",
    "h2.strata",
    "h2.quality",
    "h2.hard_failures",
    "h2.required_axes",
    "h2.non_required_axes",
    "h2.card_verified",
)
PENDING_TASK3_ROWS: tuple[str, ...] = (
    "negative",
    "boundary",
    "u",
    "u.local",
    "hard_gates.negative",
    "hard_gates.boundary",
    "hard_gates.update_delete",
    "applicability",
    "hard_gates",
)
#: 按输入段细分的待交付行（避免同一行被重复记为 PENDING）。
PENDING_PUBLIC_ROWS: tuple[str, ...] = (
    "negative",
    "boundary",
    "hard_gates.negative",
    "hard_gates.boundary",
    "applicability",
)
PENDING_U_ROWS: tuple[str, ...] = ("u", "u.local", "hard_gates.update_delete")


@dataclass(frozen=True)
class ReleaseGateResult:
    """一次正式门禁的完整结果（脱敏：只有计数、摘要与固定原因码）。"""

    inputs_path: Path
    inputs_sha256: str
    gate_config_hash: str | None
    candidate_pipeline_version: str | None
    decision: str
    rows: tuple[ReleaseRow, ...]
    pending: Mapping[str, str] = field(default_factory=dict)
    b0: B0Evidence | None = None
    suites: Mapping[str, SuiteEvidence] = field(default_factory=dict)
    h2: H2Evidence | None = None

    @property
    def evidence_blocked_rows(self) -> tuple[ReleaseRow, ...]:
        return tuple(row for row in self.rows if row.decision == DECISION_BLOCKED)

    @property
    def pending_rows(self) -> tuple[ReleaseRow, ...]:
        return tuple(row for row in self.rows if row.decision == DECISION_PENDING)

    @property
    def failed_rows(self) -> tuple[ReleaseRow, ...]:
        return tuple(row for row in self.rows if row.decision in {DECISION_BLOCKED, DECISION_PENDING})

    def to_dict(self) -> dict[str, Any]:
        """脱敏结果：不含题干、回答、标签、密钥与本地绝对路径。"""
        counts = {
            "pass": sum(1 for row in self.rows if row.decision == DECISION_PASS),
            "blocked": sum(1 for row in self.rows if row.decision == DECISION_BLOCKED),
            "pending": sum(1 for row in self.rows if row.decision == DECISION_PENDING),
            "observed": sum(1 for row in self.rows if row.decision == DECISION_OBSERVED),
        }
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "inputs_sha256": self.inputs_sha256,
            "gate_config_hash": self.gate_config_hash,
            "candidate_pipeline_version": self.candidate_pipeline_version,
            "decision": self.decision,
            "release_allowed": False,
            "release_authority": "owner",
            "owner_release_decision": "not_decided",
            "technical_gate": self.decision,
            "counts": counts,
            "reason_codes": sorted({code for row in self.rows for code in row.reasons}),
            "pending": dict(self.pending),
            "rows": [row.to_dict() for row in self.rows],
            "notes": [
                "技术门通过只作为 T900 独立总验收输入，不构成发布决定",
                "缺证/未执行/必需未知/硬失败/版本不符/身份不符一律阻断",
                "不许用调用方自报布尔或名称白名单当必要证据",
                "硬门禁最小样本按 suite 计划题数计（主人 D-011），run 级子集由 "
                "hard_gate_min_sample.run_level_subset 披露；该行是要求的输出行，"
                "消费方不得删除，冻结时应把行数与行 id 集合一并入册",
                "单看 technical_gate=pass 不读 disclosure 行，会误读为'10 条 run 级证据都过了门'——"
                "U 的八项硬门禁实际只在 1 条 run 级样本上评估",
            ],
        }


def _pending_rows(section: str, marker: str) -> tuple[ReleaseRow, ...]:
    if section == "h2":
        return tuple(row_pending(row_id, _title(row_id), marker) for row_id in PENDING_TASK2_ROWS)
    rows = PENDING_PUBLIC_ROWS if section == "public" else PENDING_U_ROWS
    return tuple(row_pending(row_id, _title(row_id), marker) for row_id in rows)


_TITLES: Mapping[str, str] = {
    "negative": "N 8/8（真实公开 run）",
    "boundary": "C 6/6（真实公开 run）",
    "u": "U 10/10（1 真实 smoke + 9 本地控制）",
    "u.local": "U 本地控制 U02–U10（L）",
    "applicability": "历史 run 适用性证明",
    "hard_gates": "八项硬门禁汇总",
    "hard_gates.negative": "N · 八项硬门禁",
    "hard_gates.boundary": "C · 八项硬门禁",
    "hard_gates.update_delete": "U · 八项硬门禁",
    "h2": "H2 同批聚合（严格校验）",
    "h2.composition": "H2 四场景组合严格校验",
    "h2.source_proof": "H2 同批来源证明",
    "h2.coverage": "H2 同批 30 题 36 回合",
    "h2.strata": "H2 五层齐全（10/5/5/5/5）",
    "h2.quality": "H2 正确 ≥24/30",
    "h2.hard_failures": "H2 硬失败 0",
    "h2.required_axes": "H2 必需轴无未知",
    "h2.non_required_axes": "H2 非必需轴未知（C25 原口径）",
    "h2.card_verified": "H2 整卡 verified",
}


def _title(row_id: str) -> str:
    return _TITLES.get(row_id, row_id)


def _public_assignment(inputs: ReleaseInputs) -> Mapping[str, Mapping[str, str]]:
    """从已校验的冻结选题范围取逐题归属（先定范围、再复算）。"""
    from .p2_release_inputs import validate_selection

    runs = {item.run_id: item for item in inputs.public_runs}
    return validate_selection(inputs.selection, runs)


def _run_cases(binding: Any) -> tuple[Any, ...]:
    from .p2_score_run import load_cases_file

    return load_cases_file(binding.run_dir / "dataset.jsonl")


def _assess_public(
    inputs: ReleaseInputs, *, project_root: Path | None
) -> tuple[tuple[ReleaseRow, ...], Mapping[str, SuiteEvidence]]:
    import tempfile

    rows: list[ReleaseRow] = []
    suites: dict[str, SuiteEvidence] = {}
    work_dir = Path(tempfile.mkdtemp(prefix="p2-release-binding-"))
    try:
        assignment = _public_assignment(inputs)
        codes = inputs.document_codes.payload
        if not isinstance(codes, Mapping) or not codes:
            raise ReleaseGateError(R_EVIDENCE_MISSING, "document_codes 为空")
        document_codes = {str(key): str(value) for key, value in codes.items()}
        runs = {item.run_id: item for item in inputs.public_runs}
        scopes: dict[str, list[Any]] = {}
        statuses: dict[str, str] = {}
        resolvers: dict[str, Any] = {}
        for run_id, run in runs.items():
            binding_row, replay = assess_binding(
                run, cases=_run_cases(run), gate_config=inputs.gate_config,
                document_codes=document_codes, work_dir=work_dir,
            )
            if binding_row is not None:
                rows.append(binding_row)
            if run.rag_db is not None:
                for suite, case_ids in assignment.items():
                    for case_id in case_ids:
                        if case_ids[case_id] == run_id:
                            resolvers[case_id] = run.rag_db.path
        for suite, ids in (("negative", P2_NEGATIVE_IDS), ("boundary", P2_BOUNDARY_IDS)):
            evidence = collect_suite(
                suite, assignment[suite], runs,
                document_codes=document_codes,
                gate_config=inputs.gate_config,
                project_root=project_root,
                rag_resolvers=resolvers,
            )
            suites[suite] = evidence
            title = _title(suite)
            rows.extend(assess_suite(evidence, title=title, row_prefix=suite,
                                     required=len(ids), gate_config=inputs.gate_config))
            for case in evidence.cases:
                scopes.setdefault(evidence.assignment[case.case_id], []).append(case)
            statuses.update(evidence.statuses)
        rows.extend(assess_applicability(
            runs, scopes, statuses, gate_config=inputs.gate_config,
            gate_config_path=inputs.gate_config_path,
        ))
    except ReleaseGateError as exc:
        rows.append(exc.to_row("public", "N/C 公开证据"))
    except Exception as exc:  # 结构/复算异常：按缺证阻断，不猜结论
        failed_run = getattr(exc, "run_id", None)
        reason = getattr(exc, "reason", R_EVIDENCE_MISSING)
        cause = getattr(exc, "cause", f"public_evidence_failed:{exc}")
        rows.append(row_blocked("public", "N/C 公开证据", reason, cause=str(cause),
                                detail={"run_id": failed_run} if failed_run else None))
    return tuple(rows), suites


def _assess_u(
    inputs: ReleaseInputs, *, project_root: Path | None
) -> tuple[tuple[ReleaseRow, ...], SuiteEvidence | None]:
    import tempfile

    work_dir = Path(tempfile.mkdtemp(prefix="p2-release-binding-u-"))
    try:
        real = inputs.u_real
        if real is None:
            raise ReleaseGateError(R_EVIDENCE_MISSING, "U 真实 smoke 未绑定")
        codes = inputs.document_codes.payload if inputs.document_codes is not None else {}
        if not isinstance(codes, Mapping) or not codes:
            raise ReleaseGateError(R_EVIDENCE_MISSING, "U 复算缺少 document_codes 绑定")
        assignment = {str(case_id): real.run_id
                      for case_id in (inputs.u.get("real") or {}).get("case_ids") or ()}
        from .p2_release_binding import assess_binding as _assess_binding

        rows: list[ReleaseRow] = []
        binding_row, replay = _assess_binding(
            real, cases=_run_cases(real), gate_config=inputs.gate_config,
            document_codes={str(k): str(v) for k, v in codes.items()},
            work_dir=work_dir,
        )
        if binding_row is not None:
            rows.append(binding_row)
        evidence = collect_suite("update_delete", assignment, {real.run_id: real},
                                 document_codes={str(k): str(v) for k, v in codes.items()},
                                 gate_config=inputs.gate_config, project_root=project_root,
                                 rag_resolvers=({case_id: real.rag_db.path
                                                 for case_id in assignment}
                                                if real.rag_db is not None else None))
        rows.extend(assess_u(inputs, evidence=evidence, project_root=project_root))
        rows.extend(assess_applicability(
            {real.run_id: real}, {real.run_id: list(evidence.cases)}, dict(evidence.statuses),
            gate_config=inputs.gate_config,
            gate_config_path=inputs.gate_config_path,
        ))
        return tuple(rows), evidence
    except ReleaseGateError as exc:
        return (exc.to_row("u", _title("u")),), None
    except Exception as exc:
        return (row_blocked("u", _title("u"), R_EVIDENCE_MISSING,
                            cause=f"u_evidence_failed:{exc}"),), None


def _provenance_rows(inputs: Any, *, project_root: Path | None) -> tuple[ReleaseRow, ...]:
    """FU-3 回源校验行；任何异常都折成固定原因码的阻断行（fail closed）。"""
    from .p2_release_model import R_EVIDENCE_MISSING, row_blocked
    from .p2_release_provenance import check_evidence_provenance, provenance_rows

    try:
        report = check_evidence_provenance(inputs, project_root=project_root)
    except Exception as exc:  # noqa: BLE001 - 回源失败一律阻断，不放过
        return (row_blocked(
            "evidence_provenance", "N/C/U 回源校验（题目/证据/trace）",
            R_EVIDENCE_MISSING, cause=f"provenance_error:{type(exc).__name__}",
            detail={"error": str(exc)[:200]},
        ),)
    return provenance_rows(report)


def evaluate_release_gate(
    inputs_path: Path | str, *, project_root: Path | str | None = None
) -> ReleaseGateResult:
    """加载输入 -> 逐项判定 -> 总门；任何异常都折成固定原因码的阻断行。"""
    root = Path(project_root) if project_root is not None else None
    try:
        inputs = load_release_inputs(inputs_path, project_root=root)
    except ReleaseGateError as exc:
        row = exc.to_row("inputs", "输入契约加载")
        return ReleaseGateResult(
            inputs_path=Path(inputs_path), inputs_sha256="", gate_config_hash=None,
            candidate_pipeline_version=None, decision=DECISION_BLOCKED, rows=(row,),
        )
    rows: list[ReleaseRow] = []
    rows.append(row_ok("gate_config", "已批准正式配置", detail={
        "config_hash": inputs.gate_config.config_hash,
        "gate_version": inputs.gate_config.gate_version,
        "status": inputs.gate_config.status,
    }, evidence=(f"gate_config:{inputs.gate_config_path.name}",)))
    rows.append(row_ok("inputs", "输入契约（逐字节绑定）", detail={
        "inputs_sha256": inputs.sha256,
        "pending": dict(inputs.pending),
    }))

    b0_rows, b0 = assess_b0(inputs)
    rows.extend(b0_rows)

    suites: dict[str, SuiteEvidence] = {}
    if "public" in inputs.pending:
        rows.extend(_pending_rows("public", inputs.pending["public"]))
    else:
        public_rows, suites = _assess_public(inputs, project_root=root)
        rows.extend(public_rows)

    u_evidence: SuiteEvidence | None = None
    if "u" in inputs.pending:
        rows.extend(_pending_rows("u", inputs.pending["u"]))
    else:
        u_rows, u_evidence = _assess_u(inputs, project_root=root)
        rows.extend(u_rows)

    if inputs.evidence_manifest is not None:
        rows.extend(cross_check_evidence_manifest(inputs, suites=suites, u_evidence=u_evidence))
        # FU-3：送检清单默认做逐题回源（题目摘要/证据路径与摘要/trace 归属/U 类型）。
        # 缺权威来源或任一项不符 → 固定原因码阻断；不以"清单自称"替代回源。
        rows.extend(_provenance_rows(inputs, project_root=root))

    # 批准配置的硬门禁最小样本：D-011 后按 **suite 计划题数** 判覆盖；
    # 仅在覆盖不成立（计划题数 < 最小样本）时给固定行，交主人裁量。
    if u_evidence is not None:
        from .p2_release_public import min_sample_coverage

        coverage = min_sample_coverage(
            standards=inputs.gate_config.standards, gate_config=inputs.gate_config,
            suite="update_delete", run_level_evaluated=int(u_evidence.scored_count),
        )
        required = coverage["required_min_sample"]
        evaluated = int(u_evidence.scored_count)
        if not coverage["covered"]:
            rows.append(row_pending(
                "hard_gate_min_sample.unmet",
                "硬门禁最小样本未满足（PENDING-MASTER-DECISION）",
                "PENDING-MASTER-DECISION",
                reason=R_HARD_GATE_MIN_SAMPLE_UNMET,
                detail={
                    "suite": "update_delete",
                    "suite_planned_cases": coverage["suite_planned_cases"],
                    "required": int(required),
                    "run_level_evaluated": evaluated,
                    "basis": coverage["basis"],
                    "approved_config": "docs/evaluation/gate_v0_3_approved.json",
                    "handling": "不自行放宽、不改配置数值；由主人裁量。",
                },
            ))

    h2_evidence: H2Evidence | None = None
    if "h2" in inputs.pending:
        rows.extend(_pending_rows("h2", inputs.pending["h2"]))
    elif inputs.h2_cards_index is not None:
        # D-001 受限模式：卡本体在仓外，只用聚合视图 + 卡索引 + 完整来源证明做外层核验。
        h2_rows, h2_evidence = assess_h2_aggregate(inputs)
        rows.extend(h2_rows)
    else:
        h2_rows, h2_evidence = assess_h2(inputs, project_root=root)
        rows.extend(h2_rows)

    # 八项硬门禁汇总：任一来源待交付 -> 汇总待交付（不拿半个覆盖面冒充通过）。
    pending_gate_sections = [section for section in ("public", "u") if section in inputs.pending]
    if pending_gate_sections:
        rows.append(row_pending("hard_gates", _title("hard_gates"),
                                inputs.pending[pending_gate_sections[0]],
                                detail={"pending_sources": pending_gate_sections}))
    else:
        sources: list[HardGateSource] = []
        if b0 is not None:
            sources.append(HardGateSource("b0", b0.admission.proof["hard_gate"]))
        for suite, evidence in suites.items():
            sources.append(HardGateSource(suite, evidence.gate_proof))
        u_pending = None
        if u_evidence is not None:
            u_status = dict(u_evidence.gate_proof.get("gate_status") or {})
            from .p2_release_public import min_sample_coverage as _coverage

            u_coverage = _coverage(
                standards=inputs.gate_config.standards, gate_config=inputs.gate_config,
                suite="update_delete", run_level_evaluated=int(u_evidence.scored_count),
            )
            if not u_coverage["covered"]:
                u_pending = (R_SAMPLE_BELOW_MIN, "u_sample_scope")
            elif u_status.get("citation_required") == "fail" and citation_grounding_gaps(inputs, u_evidence):
                u_pending = (R_CITATION_GROUNDING_MISSING, "u01_citation_grounding")
            if u_pending is None:
                sources.append(HardGateSource("update_delete", u_evidence.gate_proof))
        if u_pending is not None:
            rows.append(row_pending(
                "hard_gates", _title("hard_gates"), "PENDING-MASTER-DECISION",
                reason=u_pending[0],
                detail={"pending_sources": ["update_delete"], "cause": u_pending[1]},
            ))
        else:
            rows.append(aggregate_hard_gates(sources, config=inputs.gate_config))

    # 不变量：参与判定的每个 run 都必须同时有 binding.<run_id> 与 applicability.<run_id> 行，
    # 否则总门会被"少一行"静默抬高（T4-R1 缺陷 1 的防回归断言）。
    assessed_runs: dict[str, Any] = {}
    for item in inputs.public_runs:
        assessed_runs[item.run_id] = item
    if inputs.u_real is not None:
        assessed_runs[inputs.u_real.run_id] = inputs.u_real
    present = {row.row_id for row in rows}
    for run_id in assessed_runs:
        missing = [name for name in (f"binding.{run_id}", f"applicability.{run_id}")
                   if name not in present]
        if missing:
            # 每个 run 一条独立行（多 run 同时缺行时不得共用一个 row_id，否则会被去重/覆盖）。
            rows.append(row_blocked(
                f"rows.completeness.{run_id}", f"门禁结果行完整性 · {run_id}",
                R_ROWS_INCOMPLETE, cause="run_rows_missing",
                detail={"run_id": run_id, "missing": missing},
            ))
    decision = gate_decision(rows)
    return ReleaseGateResult(
        inputs_path=inputs.path,
        inputs_sha256=inputs.sha256,
        gate_config_hash=inputs.gate_config.config_hash,
        candidate_pipeline_version=inputs.candidate_pipeline_version,
        decision=decision,
        rows=tuple(rows),
        pending=dict(inputs.pending),
        b0=b0,
        suites=suites,
        h2=h2_evidence,
    )


def emit_applicability_proof(
    inputs_path: Path | str,
    *,
    out_dir: Path | str,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """按输入清单里的冻结选题范围，为每个历史 run 重算并落盘适用性证明。

    证明由门禁同一段代码生成，接线后门禁会再重算一次并要求逐字段相等；
    因此"补证明"不能放宽判定，只能把可复算的事实落到文件里。
    """
    from .p2_release_inputs import validate_selection
    from .p2_release_public import build_applicability_proof, scorer_source_sha256
    from .p2_score_run import load_cases_file, load_document_codes, score_run

    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[4]
    inputs = load_release_inputs(inputs_path, project_root=root)
    if inputs.public is None or inputs.selection is None or inputs.document_codes is None:
        raise ReleaseGateError(R_EVIDENCE_MISSING, "public 段未交付，无法生成适用性证明")
    runs = {item.run_id: item for item in inputs.public_runs}
    if inputs.u_real is not None:
        runs[inputs.u_real.run_id] = inputs.u_real
    assignment = validate_selection(inputs.selection, runs)
    scope: dict[str, list[str]] = {}
    for suite, rows in assignment.items():
        for case_id, run_id in rows.items():
            scope.setdefault(run_id, []).append(case_id)
    if inputs.u_real is not None:
        scope.setdefault(inputs.u_real.run_id, []).extend(
            str(item) for item in (inputs.u.get("real") or {}).get("case_ids") or ()
        )
    codes = load_document_codes(inputs.document_codes.path)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, Any] = {}
    for run_id, case_ids in scope.items():
        binding = runs[run_id]
        all_cases = load_cases_file(binding.run_dir / "dataset.jsonl")
        scored = score_run(binding.run_dir, cases=all_cases, document_codes=codes)
        by_id = {item.score.case_id: item.score.status for item in scored.scored}
        cases = tuple(case for case in all_cases if case.case_id in set(case_ids))
        missing = sorted(set(case_ids) - {case.case_id for case in cases})
        if missing:
            raise ReleaseGateError(R_EVIDENCE_MISSING, "选题范围里的题不在该 run",
                                   {"run_id": run_id, "missing": missing})
        statuses = {case.case_id: by_id[case.case_id] for case in cases}
        proof = build_applicability_proof(
            binding, cases, statuses,
            gate_config=inputs.gate_config,
            gate_config_path=inputs.gate_config_path,
        )
        path = target / f"applicability-{run_id}.json"
        path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        written[run_id] = {
            "path": str(path),
            "sha256": file_sha256(path),
            "cases": list(case_ids),
            "scorer_source_sha256": scorer_source_sha256(),
        }
    return {"ok": True, "inputs_sha256": inputs.sha256, "written": written}


def emit_binding_proof(
    inputs_path: Path | str,
    *,
    out_dir: Path | str,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """为声明了 rag_db 的 run 重算并落盘"历史绑定适用性证明"。"""
    import tempfile

    from .p2_release_binding import build_binding_proof, replay_gate_binding
    from .p2_score_run import load_document_codes

    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[4]
    inputs = load_release_inputs(inputs_path, project_root=root)
    if inputs.document_codes is None:
        raise ReleaseGateError(R_EVIDENCE_MISSING, "生成绑定证明需要 public.document_codes")
    codes = load_document_codes(inputs.document_codes.path)
    runs = {item.run_id: item for item in inputs.public_runs}
    if inputs.u_real is not None:
        runs[inputs.u_real.run_id] = inputs.u_real
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="p2-release-binding-emit-") as directory:
        for run_id, binding in runs.items():
            if binding.rag_db is None:
                continue
            cases = _run_cases(binding)
            replay = replay_gate_binding(
                binding, cases=cases, gate_config=inputs.gate_config, document_codes=codes,
                rag_db=binding.rag_db.path, work_dir=Path(directory),
            )
            proof = build_binding_proof(
                binding, rag_db=binding.rag_db.path,
                replay={key: replay[key] for key in
                        ("original_binding_failures", "corrected_binding_failures",
                         "rewritten_trace_rows", "trace_rows_total",
                         "trace_rows_not_at_attested", "post_update_not_at_attested",
                         "original_trace_db_sha256")},
            )
            path = target / f"binding-{run_id}.json"
            path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
            written[run_id] = {
                "path": str(path),
                "sha256": file_sha256(path),
                "recorded_index_revision": proof["recorded_index_revision"],
                "attested_index_revision": proof["attested_index_revision"],
                "original_binding_failures": len(proof["gate_replay"]["original_binding_failures"]),
            }
    return {"ok": True, "inputs_sha256": inputs.sha256, "written": written}


__all__ = [
    "PENDING_TASK2_ROWS",
    "PENDING_TASK3_ROWS",
    "ReleaseGateResult",
    "emit_applicability_proof",
    "emit_binding_proof",
    "evaluate_release_gate",
]
