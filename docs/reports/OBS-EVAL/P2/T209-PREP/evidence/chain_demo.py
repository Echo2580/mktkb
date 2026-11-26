"""T209-PREP 证据：公共/合成 run 的 candidate 归档全链演示（零真实调用）。

在系统临时目录（非仓库、非正式 registry）完成：
archive → verify → restore → list → diff → 一次坏输入拒绝（metadata 抬升）。
输出稳定文本供 dev-report 引用；结束后清理临时目录。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_candidate_report as pr  # noqa: E402
from mktkb.evaluation.baseline import load_baseline, save_baseline  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, write_cases  # noqa: E402
from mktkb.evaluation.runner import RunManifest, RunResult  # noqa: E402
from mktkb.observability.contracts import GATE_SCHEMA_VERSION  # noqa: E402

ROUND = "T209-PREP-SYNTHETIC-ROUND"


def make_cases(total: int = 30) -> tuple[CaseSpec, ...]:
    return tuple(
        CaseSpec(
            case_id=f"Q{index:03d}",
            suite="b0",
            split="dev",
            stratum="exact",
            business_date="2026-10-28",
            question=f"合成问题 {index}",
            expected_kind="answer",
            expected_values=("合成答案",),
            expected_sources=({"doc_code": "D01", "unit_key": "sheet:合成:row:8"},),
            labeler="synthetic",
            label_version="dev-1",
        )
        for index in range(1, total + 1)
    )


def make_run(base: Path) -> RunResult:
    cases = make_cases()
    dataset_path = base / "dataset.jsonl"
    write_cases(dataset_path, list(cases))
    manifest = RunManifest(
        run_id="run-t209-synthetic",
        mode="local",
        scope="end_to_end",
        suite="b0",
        dataset_version="b0:dev-1:0123456789ab",
        dataset_sha256="a" * 64,
        corpus_manifest_sha256="b" * 64,
        business_date="2026-10-28",
        index_revision=1,
        pipeline_version="pipeline-synthetic",
        gate_version=GATE_SCHEMA_VERSION,
        label_version="dev-1",
        created_at="2026-11-14T00:00:00.000+00:00",
        case_count=len(cases),
        config_hash="c" * 12,
        dataset_path=str(dataset_path),
    )
    rows = tuple({"case_id": case.case_id, "status": "pass"} for case in cases)
    run_dir = base / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "cases.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary = {"run_id": manifest.run_id, "suite": manifest.suite, "mode": manifest.mode}
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return RunResult(manifest=manifest, out_dir=run_dir, cases=rows, summary=summary)


def clean_report() -> pr.SplitReport:
    axes = tuple(
        pr.AxisEvidence.create(
            axis=axis,
            planned=30,
            passed=30,
            not_applicable=0,
            unknown=0,
            violations=0,
        )
        for axis in pr.AXES
    )
    return pr.build_split_report(
        reference=pr.ReferenceSource.create(
            source_kind="synthetic-mirror",
            document="docs/reports/OBS-EVAL/P2/T209-PREP/evidence/synthetic-mirror.json",
            plan_id=ROUND,
            code_version="synthetic",
        ),
        execution=pr.build_execution(
            round_id=ROUND,
            runs=(pr.RunOutcome("s0", "synthetic_clean", "succeeded", 30, 30),),
        ),
        quality=pr.build_quality(
            round_id=ROUND,
            total=30,
            passed=30,
            failed=0,
            errors=0,
            safety_violations=0,
            min_pass=24,
            thresholds_approved=False,
            verified=True,
            scenario_verifications=(("s0", True),),
        ),
        evidence=pr.build_evidence(
            round_id=ROUND,
            total=30,
            missing_evidence_cases=0,
            axes=axes,
            verified=True,
        ),
        soft=(pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="合成"),),
        funding=pr.FundingStatus.create(
            ledger_current_sha256="1" * 64,
            ledger_previous_sha256="2" * 64,
            ledger_change_cause="legitimate_spend",
            go_current_sha256="3" * 64,
            go_archived_sha256="4" * 64,
            archived_line_moment="合成历史时刻",
        ),
    )


def main() -> int:
    lines: list[str] = []

    def emit(message: str) -> None:
        lines.append(message)
        print(message)

    base = Path(tempfile.mkdtemp(prefix="t209-prep-chain-"))
    try:
        run = make_run(base)
        root = base / "baselines"
        baseline = save_baseline(run, root)
        out = base / "candidates" / "candidate-a"
        report = clean_report()
        emit(f"source_baseline={baseline.baseline_id} run={baseline.run_id} approved={baseline.approved}")
        emit(f"report_state={pr.candidate_state_for_report(report)}")

        record = pr.archive_candidate(
            baseline_id_value=baseline.baseline_id,
            root=root,
            out_dir=out,
            report=report,
            reason="T209-PREP 合成链路演示（不发布）",
        )
        emit(f"archive state={record.state} publishable={record.publishable} "
             f"release_baseline={record.release_baseline} files={len(record.files)}")

        verified = pr.verify_candidate_archive(out)
        emit(f"verify state={verified.state} baseline_id={verified.baseline_id} "
             f"has_approval={verified.has_approval} files={len(verified.files)}")

        restored = pr.restore_candidate(out, base / "restore" / "baselines")
        reloaded = load_baseline(restored.baseline_id, base / "restore" / "baselines")
        emit(f"restore state={restored.state} run={restored.run_id} "
             f"approval_is_none={reloaded.approval is None} "
             f"baseline_is_approved={reloaded.approved}")

        listing = pr.list_candidates(base / "candidates")
        emit(f"list count={len(listing)} " + ";".join(
            f"{item.archive_dir.split(chr(92))[-1]}:{item.state}:publishable={item.publishable}"
            for item in listing
        ))

        diff = pr.diff_candidates(out, out)
        emit(f"diff same_identity={diff.same_identity} same_round={diff.same_round} "
             f"files_changed={len(diff.files_changed)} scores_comparable={diff.scores_comparable} "
             f"score_merge_allowed={diff.score_merge_allowed}")

        tampered = base / "tampered"
        shutil.copytree(out, tampered)
        manifest_path = tampered / pr.CANDIDATE_FILENAME
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["publishable"] = True
        manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            pr.verify_candidate_archive(tampered)
        except pr.CandidateArchiveError as exc:
            emit(f"tamper_rejected={exc}")
        else:
            raise AssertionError("篡改 publishable=True 未被拒绝")
        emit("chain_demo=OK")
        if len(sys.argv) > 1:
            Path(sys.argv[1]).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
