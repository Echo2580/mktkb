"""T209-PREP 独立验收：边界/残余刻画（不参与 PASS/FAIL 判定，只记录残余）。

1. 执行轴聚合状态：4 个 run 全部 failed 时的 aggregate 状态（观察项）；
2. 报告事实不可认证：把 blocked 归档的 report 换成"全绿"合成报告并重算
   report_sha256，verify 是否接受；若接受，是否仍不可发布/不可 release（残余）；
3. 自由文本字段（note/detail）不做内容扫描（字段级拒绝的边界）；
4. diff_candidates 对无效归档是否 fail-closed。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend/src"))

from mktkb.evaluation import p2_candidate_report as pr  # noqa: E402
from mktkb.evaluation import baseline as baseline_module  # noqa: E402
from mktkb.evaluation.baseline import load_baseline, save_baseline  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, write_cases  # noqa: E402
from mktkb.evaluation.gate import GateResult  # noqa: E402
from mktkb.evaluation.report import diff_runs  # noqa: E402
from mktkb.evaluation.runner import RunManifest, RunResult  # noqa: E402
from mktkb.observability.contracts import GATE_SCHEMA_VERSION  # noqa: E402

OBS: list[str] = []
ROUND = "T209P-INDEP-EDGE-ROUND"


def obs(name: str, value: object) -> None:
    line = f"{name}={value}"
    OBS.append(line)
    print("[OBS] " + line)


def cases(prefix: str = "EDGE") -> tuple[CaseSpec, ...]:
    return tuple(
        CaseSpec(
            case_id=f"{prefix}{index:03d}", suite="b0", split="dev", stratum="exact",
            business_date="2026-10-28", question=f"synthetic {index}", expected_kind="answer",
            expected_values=("SYNTH",),
            expected_sources=({"doc_code": "D01", "unit_key": f"sheet:E:row:{index}"},),
            labeler="synthetic", label_version="dev-1",
        )
        for index in range(1, 31)
    )


def build_run(base: Path, run_id: str, *, suite: str = "b0") -> RunResult:
    case_set = cases()
    dataset = base / f"{run_id}.dataset.jsonl"
    write_cases(dataset, list(case_set))
    manifest = RunManifest(
        run_id=run_id, mode="local", scope="end_to_end", suite=suite,
        dataset_version="b0:dev-1:0123456789ab", dataset_sha256="a" * 64,
        corpus_manifest_sha256="b" * 64, business_date="2026-10-28", index_revision=1,
        pipeline_version="pipelineEDGE", gate_version=GATE_SCHEMA_VERSION,
        label_version="dev-1", created_at="2026-11-14T00:00:00.000+00:00",
        case_count=30, config_hash="c" * 12, dataset_path=str(dataset),
    )
    rows = tuple({"case_id": case.case_id, "status": "pass"} for case in case_set)
    run_dir = base / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "cases.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    summary = {"run_id": run_id, "suite": suite, "mode": "local"}
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return RunResult(manifest=manifest, out_dir=run_dir, cases=rows, summary=summary)


def clean_report() -> pr.SplitReport:
    axes = tuple(
        pr.AxisEvidence.create(axis=a, planned=30, passed=30, not_applicable=0, unknown=0, violations=0)
        for a in pr.AXES
    )
    return pr.build_split_report(
        reference=pr.ReferenceSource.create(
            source_kind="synthetic-mirror",
            document="docs/reports/OBS-EVAL/P2/T209-PREP/independent/mirror.json",
            plan_id=ROUND, code_version="synthetic",
        ),
        execution=pr.build_execution(
            round_id=ROUND, runs=(pr.RunOutcome("s0", "s", "succeeded", 30, 30),)
        ),
        quality=pr.build_quality(
            round_id=ROUND, total=30, passed=30, failed=0, errors=0, safety_violations=0,
            min_pass=24, thresholds_approved=False, verified=True,
            scenario_verifications=(("s0", True),),
        ),
        evidence=pr.build_evidence(
            round_id=ROUND, total=30, missing_evidence_cases=0, axes=axes, verified=True
        ),
        soft=(pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="synthetic"),),
        funding=pr.FundingStatus.create(
            ledger_current_sha256="1" * 64, ledger_previous_sha256="2" * 64,
            ledger_change_cause="legitimate_spend", go_current_sha256="3" * 64,
            go_archived_sha256="4" * 64, archived_line_moment="edge",
        ),
    )


def blocked_report() -> pr.SplitReport:
    axes = (
        pr.AxisEvidence.create(axis="safety", planned=30, passed=1, not_applicable=24, unknown=3, violations=2, unknown_reason="undetermined"),
        pr.AxisEvidence.create(axis="cross_user", planned=30, passed=27, not_applicable=0, unknown=3, violations=0, unknown_reason="undetermined"),
        pr.AxisEvidence.create(axis="cross_entity", planned=30, passed=3, not_applicable=0, unknown=27, violations=0, unknown_reason="real_scope_targets_contract_not_generated"),
        pr.AxisEvidence.create(axis="stale_source", planned=30, passed=25, not_applicable=0, unknown=5, violations=0, unknown_reason="undetermined"),
    )
    return pr.build_split_report(
        reference=pr.ReferenceSource.create(
            source_kind="synthetic-mirror",
            document="docs/reports/OBS-EVAL/P2/T209-PREP/independent/mirror.json",
            plan_id=ROUND, code_version="synthetic",
        ),
        execution=pr.build_execution(round_id=ROUND, runs=(pr.RunOutcome("s0", "s", "succeeded", 30, 30),)),
        quality=pr.build_quality(
            round_id=ROUND, total=30, passed=19, failed=11, errors=0, safety_violations=2,
            min_pass=24, thresholds_approved=False, verified=False,
            scenario_verifications=(("s0", False),),
        ),
        evidence=pr.build_evidence(
            round_id=ROUND, total=30, missing_evidence_cases=27, axes=axes, verified=False
        ),
        soft=(pr.SoftStatus.unknown("auxiliary", recorded_status="unavailable", detail="s"),),
        funding=pr.FundingStatus.create(
            ledger_current_sha256="1" * 64, ledger_previous_sha256="2" * 64,
            ledger_change_cause="legitimate_spend", go_current_sha256="3" * 64,
            go_archived_sha256="4" * 64, archived_line_moment="edge",
        ),
    )


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="t209p-indep-edge-"))
    try:
        # 1. 全部 failed 的 aggregate 状态
        failed_exec = pr.build_execution(
            round_id=ROUND,
            runs=tuple(
                pr.RunOutcome(f"r{index}", "s", "failed", 1, 1, errors=1)
                for index in range(4)
            ),
        )
        obs("all_failed_aggregate_status", failed_exec.status)
        obs("all_failed_succeeded_runs", failed_exec.succeeded_runs)
        obs("all_failed_failed_runs", failed_exec.failed_runs)
        obs("failed_status_reachable_by_builder", "failed" in {
            pr.build_execution(round_id="x", runs=(pr.RunOutcome("r", "s", "failed", 1, 1),)).status,
            pr.build_execution(round_id="x", runs=(pr.RunOutcome("r", "s", "not_run", 0, 0),)).status,
        })

        # 2. 伪造报告：blocked → 全绿，重算 report_sha256，verify 是否接受
        root = base / "baselines"
        run = build_run(base, "run-edge-forge")
        saved = save_baseline(run, root)
        out = base / "candidates" / "blocked"
        pr.archive_candidate(
            baseline_id_value=saved.baseline_id, root=root, out_dir=out,
            report=blocked_report(), reason="edge blocked",
        )
        manifest_path = out / pr.CANDIDATE_FILENAME
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["report"] = clean_report().to_dict()
        payload["report_sha256"] = hashlib.sha256(
            json.dumps(payload["report"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        payload["state"] = "candidate"
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        forged = pr.verify_candidate_archive(out)
        obs("forged_report_verify_accepted", True)
        obs("forged_report_state", forged.state)
        obs("forged_report_publishable", forged.publishable)
        obs("forged_report_release_baseline", forged.release_baseline)
        obs("forged_report_gate_approved", forged.gate_approved)
        obs("forged_report_has_approval", forged.has_approval)
        restore_root = base / "restore"
        restored = pr.restore_candidate(out, restore_root)
        reloaded = load_baseline(restored.baseline_id, restore_root)
        obs("forged_restore_approval_is_none", reloaded.approval is None)
        current = build_run(base, "run-edge-current")
        gate = GateResult(
            exit_code=0, gate_status={}, hard_failures=(), failures=(), unknowns=(),
            not_applicable=(), warnings=(), run_id=current.manifest.run_id, suite="b0",
            mode="local", gate_version=GATE_SCHEMA_VERSION, scored_count=30, min_sample=None,
            quality=None,
        )
        diff = diff_runs(reloaded, current, gate=gate)
        obs("forged_restore_release_allowed", diff.release_allowed)
        obs("forged_restore_release_blocked_reason", diff.release_blocked_reason)

        # 3. 自由文本字段不做内容扫描：把题干文本塞进 note/detail 是否被接受
        leaky = clean_report().to_dict()
        leaky["quality"]["note"] = "H2 原题：请列出某公司营收？"
        leaky["soft"][0]["detail"] = "逐题答案 A01"
        try:
            rebuilt = pr.SplitReport.from_dict(leaky)
        except pr.CandidateReportError as exc:
            obs("free_text_private_content_rejected", str(exc))
        else:
            obs("free_text_private_content_rejected", False)
            obs("free_text_roundtrip_ok", rebuilt.to_dict() == leaky)

        # 4. diff_candidates 对无效归档 fail-closed
        bad = base / "candidates" / "invalid"
        bad.mkdir()
        (bad / pr.CANDIDATE_FILENAME).write_text("{}", encoding="utf-8")
        try:
            pr.diff_candidates(out, bad)
        except pr.CandidateArchiveError as exc:
            obs("diff_rejects_invalid_archive", True)
            obs("diff_rejects_invalid_reason", str(exc)[:120])
        else:
            obs("diff_rejects_invalid_archive", False)

        print("\nRESULT=OBSERVATIONS_RECORDED")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
