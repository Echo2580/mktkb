"""T209-PREP 独立验收：坏输入 fail-closed（自建、与开发测试不同构）。

每个反例都独立构造：先复制一个**已验证通过**的 candidate 归档或独立合成 baseline，
再施加单一篡改；断言被拒绝、错误类型为 CandidateArchiveError，且不留下半成品
（目标目录不存在、父目录无 .staging-* 残留）。覆盖开发测试未覆盖/不同构的输入：
缺 manifest、坏 JSON、字段类型错误、candidate manifest 路径逃逸、run_id/suite/identity
不匹配、payload 内 approval.json、payload 摘要互换、归档根/payload 为 junction、
已审批源、holdout 源、非 SplitReport、非目录路径。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend/src"))

from mktkb.evaluation import p2_candidate_report as pr  # noqa: E402
from mktkb.evaluation.baseline import (  # noqa: E402
    APPROVAL_FILENAME,
    approve_baseline,
    baseline_id as compute_baseline_id,
    save_baseline,
)
from mktkb.evaluation.dataset import CaseSpec, write_cases  # noqa: E402
from mktkb.evaluation.gate import GateResult, QualityResult  # noqa: E402
from mktkb.evaluation.runner import RunManifest, RunResult  # noqa: E402
from mktkb.observability.contracts import GATE_SCHEMA_VERSION  # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []
ROUND = "T209P-INDEP-BAD-ROUND"


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def expect_reject(archive_dir: Path, name: str, *needles: str) -> None:
    try:
        pr.verify_candidate_archive(archive_dir)
    except pr.CandidateArchiveError as exc:
        text = str(exc)
        ok = not needles or any(needle in text for needle in needles)
        check(ok, name, f"rejected={text}")
    except Exception as exc:  # noqa: BLE001
        check(False, name, f"unexpected {type(exc).__name__}: {exc}")
    else:
        check(False, name, "not rejected")


def make_cases(total: int = 30, *, suite: str = "b0", split: str = "dev", prefix: str = "BAD") -> tuple[CaseSpec, ...]:
    return tuple(
        CaseSpec(
            case_id=f"{prefix}{index:03d}",
            suite=suite,
            split=split,
            stratum="exact",
            business_date="2026-10-28",
            question=f"synthetic {index}",
            expected_kind="answer",
            expected_values=("SYNTH",),
            expected_sources=({"doc_code": "D01", "unit_key": f"sheet:B:row:{index}"},),
            labeler="synthetic",
            label_version="dev-1",
        )
        for index in range(1, total + 1)
    )


def build_run(
    base: Path,
    *,
    run_id: str,
    pipeline: str = "pipelineBAD1",
    suite: str = "b0",
    split: str = "dev",
    case_prefix: str = "BAD",
) -> RunResult:
    case_set = make_cases(suite=suite, split=split, prefix=case_prefix)
    dataset = base / f"{run_id}.dataset.jsonl"
    write_cases(dataset, list(case_set))
    manifest = RunManifest(
        run_id=run_id,
        mode="local",
        scope="end_to_end",
        suite=suite,
        dataset_version="b0:dev-1:0123456789ab",
        dataset_sha256="a" * 64,
        corpus_manifest_sha256="b" * 64,
        business_date="2026-10-28",
        index_revision=1,
        pipeline_version=pipeline,
        gate_version=GATE_SCHEMA_VERSION,
        label_version="dev-1",
        created_at="2026-11-14T00:00:00.000+00:00",
        case_count=len(case_set),
        config_hash="c" * 12,
        dataset_path=str(dataset),
    )
    rows = tuple({"case_id": case.case_id, "status": "pass"} for case in case_set)
    run_dir = base / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "cases.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary = {"run_id": run_id, "suite": suite, "mode": "local"}
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return RunResult(manifest=manifest, out_dir=run_dir, cases=rows, summary=summary)


def clean_report(*, round_id: str = ROUND) -> pr.SplitReport:
    axes = tuple(
        pr.AxisEvidence.create(axis=axis, planned=30, passed=30, not_applicable=0, unknown=0, violations=0)
        for axis in pr.AXES
    )
    return pr.build_split_report(
        reference=pr.ReferenceSource.create(
            source_kind="synthetic-mirror",
            document="docs/reports/OBS-EVAL/P2/T209-PREP/independent/mirror.json",
            plan_id=round_id,
            code_version="synthetic",
        ),
        execution=pr.build_execution(
            round_id=round_id, runs=(pr.RunOutcome("s0", "synthetic", "succeeded", 30, 30),)
        ),
        quality=pr.build_quality(
            round_id=round_id, total=30, passed=30, failed=0, errors=0, safety_violations=0,
            min_pass=24, thresholds_approved=False, verified=True,
            scenario_verifications=(("s0", True),),
        ),
        evidence=pr.build_evidence(
            round_id=round_id, total=30, missing_evidence_cases=0, axes=axes, verified=True
        ),
        soft=(pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="synthetic"),),
        funding=pr.FundingStatus.create(
            ledger_current_sha256="1" * 64, ledger_previous_sha256="2" * 64,
            ledger_change_cause="legitimate_spend", go_current_sha256="3" * 64,
            go_archived_sha256="4" * 64, archived_line_moment="indep",
        ),
    )


def good_archive(
    base: Path,
    *,
    name: str,
    run_id: str,
    pipeline: str = "pipelineBAD1",
    case_prefix: str = "BAD",
) -> Path:
    root = base / f"baselines-{name}"
    run = build_run(base, run_id=run_id, pipeline=pipeline, case_prefix=case_prefix)
    saved = save_baseline(run, root)
    out = base / "candidates" / name
    pr.archive_candidate(
        baseline_id_value=saved.baseline_id, root=root, out_dir=out,
        report=clean_report(), reason="independent bad-input fixture",
    )
    return out


def copy_archive(source: Path, base: Path, name: str) -> Path:
    target = base / "tampered" / name
    shutil.copytree(source, target)
    return target


def rewrite_manifest(archive: Path, mutate) -> None:
    path = archive / pr.CANDIDATE_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def no_partial(out: Path) -> bool:
    if out.exists():
        return False
    return not list(out.parent.glob(".staging-*")) if out.parent.exists() else True


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="t209p-indep-bad-"))
    junctions: list[Path] = []
    try:
        source_a = good_archive(base, name="good-a", run_id="run-bad-a")
        source_b = good_archive(
            base, name="good-b", run_id="run-bad-b", pipeline="pipelineBAD2", case_prefix="GOODB"
        )
        check(pr.verify_candidate_archive(source_a).state == "candidate", "G0 基线样例可用")

        # 1. 缺 candidate manifest
        missing = copy_archive(source_a, base, "missing-manifest")
        (missing / pr.CANDIDATE_FILENAME).unlink()
        expect_reject(missing, "B01 缺 candidate_manifest.json 被拒绝", "缺少")

        # 2. 坏 JSON / 截断
        corrupt = copy_archive(source_a, base, "corrupt-json")
        (corrupt / pr.CANDIDATE_FILENAME).write_text('{"schema_version": ', encoding="utf-8")
        expect_reject(corrupt, "B02 截断 JSON 被拒绝", "UTF-8", "JSON")

        # 3/4. 字段集合/类型错误（新构：类型而非布尔翻转）
        extra = copy_archive(source_a, base, "extra-field")
        rewrite_manifest(extra, lambda payload: payload.__setitem__("signature", "deadbeef"))
        expect_reject(extra, "B03 manifest 额外字段 signature 被拒绝", "字段集合")

        wrong = copy_archive(source_a, base, "wrong-state-type")
        rewrite_manifest(wrong, lambda payload: payload.__setitem__("state", 1))
        expect_reject(wrong, "B04a state 为整数被拒绝", "state")
        wrong = copy_archive(source_a, base, "wrong-files-type")
        rewrite_manifest(wrong, lambda payload: payload["payload"].__setitem__("files", []))
        expect_reject(wrong, "B04b payload.files 为数组被拒绝", "payload")
        wrong = copy_archive(source_a, base, "wrong-identity-type")
        rewrite_manifest(wrong, lambda payload: payload.__setitem__("identity", "not-a-mapping"))
        expect_reject(wrong, "B04c identity 为字符串被拒绝", "identity", "对象")
        wrong = copy_archive(source_a, base, "wrong-report-type")
        rewrite_manifest(wrong, lambda payload: payload.__setitem__("report", []))
        expect_reject(wrong, "B04d report 为数组被拒绝", "report", "对象")

        # 5. candidate manifest payload 路径逃逸（开发测试只覆盖内层 manifest 逃逸）
        escape = copy_archive(source_a, base, "payload-escape")
        rewrite_manifest(
            escape,
            lambda payload: payload["payload"]["files"].__setitem__("payload/../evil.json", "0" * 64),
        )
        expect_reject(escape, "B05 candidate manifest payload 路径逃逸被拒绝", "路径")

        # 6. run_id 不匹配
        bad_run = copy_archive(source_a, base, "run-id-mismatch")
        rewrite_manifest(bad_run, lambda payload: payload.__setitem__("run_id", "run-imposter"))
        expect_reject(bad_run, "B06 manifest run_id 与 payload 不匹配被拒绝", "run_id")

        # 7. suite 不匹配
        bad_suite = copy_archive(source_a, base, "suite-mismatch")
        rewrite_manifest(bad_suite, lambda payload: payload.__setitem__("suite", "holdout"))
        expect_reject(bad_suite, "B07 manifest suite 与 payload 不匹配被拒绝", "suite")

        # 8. identity 篡改：pipeline 改掉导致 baseline_id 不能重算
        bad_identity = copy_archive(source_a, base, "identity-mismatch")
        rewrite_manifest(
            bad_identity,
            lambda payload: payload["identity"].__setitem__("pipeline_version", "pipeline-EVIL"),
        )
        expect_reject(bad_identity, "B08 identity 被改（baseline_id 不可重算）被拒绝", "identity", "baseline_id")

        # 9. payload 内出现 approval.json（合成假审批）
        approval = copy_archive(source_a, base, "payload-approval")
        fake = approval / "payload" / APPROVAL_FILENAME
        fake.write_text('{"schema_version": "synthetic-approval", "approved": true}\n', encoding="utf-8")
        import hashlib

        digest = hashlib.sha256(fake.read_bytes()).hexdigest()
        rewrite_manifest(
            approval,
            lambda payload: payload["payload"]["files"].__setitem__(f"payload/{APPROVAL_FILENAME}", digest),
        )
        expect_reject(approval, "B09 payload 内 approval.json 被拒绝", "approval", "文件集合", "证据链", "摘要")

        # 10. payload 摘要互换（把另一个归档的 cases.jsonl 覆盖进来，文件集合不变）
        swapped = copy_archive(source_a, base, "payload-swap")
        shutil.copyfile(
            source_b / "payload" / "run" / "cases.jsonl",
            swapped / "payload" / "run" / "cases.jsonl",
        )
        expect_reject(swapped, "B10 payload 文件摘要互换被拒绝", "sha256", "摘要", "证据链")

        # 11. 归档根是 junction（重解析点）
        if len(sys.argv) > 1 and sys.argv[1] == "--skip-junction":
            check(True, "B11 junction 归档根（按参数跳过）")
        else:
            link_target = copy_archive(source_a, base, "junction-root-target")
            link = base / "tampered" / "junction-root-link"
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(link_target)],
                capture_output=True, text=True, check=False,
            )
            if completed.returncode != 0:
                check(False, "B11 junction 归档根被拒绝", f"mklink failed: {completed.stderr or completed.stdout}")
            else:
                junctions.append(link)
                expect_reject(link, "B11 junction 归档根被拒绝", "重解析")

            # 12. payload 目录是 junction
            payload_link_parent = copy_archive(source_a, base, "junction-payload")
            payload_dir = payload_link_parent / "payload"
            outside = base / "outside-payload"
            outside.mkdir(exist_ok=True)
            (outside / "keep.txt").write_text("outside", encoding="utf-8")
            shutil.rmtree(payload_dir)
            # 用真实 payload 目录作为 junction 目标，保持文件存在但目录是重解析
            real_payload = base / "real-payload"
            shutil.copytree(source_a / "payload", real_payload)
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(payload_dir), str(real_payload)],
                capture_output=True, text=True, check=False,
            )
            if completed.returncode != 0:
                check(False, "B12 payload 目录 junction 被拒绝", f"mklink failed: {completed.stderr or completed.stdout}")
            else:
                junctions.append(payload_dir)
                expect_reject(payload_link_parent, "B12 payload 目录 junction 被拒绝", "普通目录", "重解析")

        # 13. 非目录路径
        regular = base / "not-a-dir.json"
        regular.write_text("{}", encoding="utf-8")
        expect_reject(regular, "B13 非目录归档路径被拒绝", "不存在")

        # 14. 已审批源（独立构造审批，非开发夹具）
        approved_root = base / "baselines-approved"
        approved_run = build_run(base, run_id="run-bad-approved")
        quality = QualityResult(
            status="pass", metrics=(), strata=("all",), stratum_status={"all": "pass"},
            failures=(), unknowns=(), waived=(), diagnostics={}, warnings=(),
            config_status="approved", gate_config_hash="f" * 64,
            baseline_run_id=None, baseline_pipeline_version=None,
        )
        gate = GateResult(
            exit_code=0, gate_status={}, hard_failures=(), failures=(), unknowns=(),
            not_applicable=(), warnings=(), run_id=approved_run.manifest.run_id, suite="b0",
            mode="local", gate_version=GATE_SCHEMA_VERSION, scored_count=30, min_sample=None,
            quality=quality,
        )
        approve_baseline(approved_run, gate, approved_root, approver="indep", reason="negative fixture")
        out_approved = base / "candidates" / "approved-source"
        try:
            pr.archive_candidate(
                baseline_id_value=compute_baseline_id(approved_run),
                root=approved_root, out_dir=out_approved, report=clean_report(),
                reason="must reject approved source",
            )
        except pr.CandidateArchiveError as exc:
            check("已审批" in str(exc) and no_partial(out_approved), "B14 已审批源归档被拒绝且无半成品", str(exc))
        else:
            check(False, "B14 已审批源归档被拒绝且无半成品", "not rejected")

        # 15. holdout 源
        holdout_root = base / "baselines-holdout"
        holdout_run = build_run(base, run_id="run-bad-holdout", suite="holdout", split="holdout")
        holdout_saved = save_baseline(holdout_run, holdout_root)
        out_holdout = base / "candidates" / "holdout-source"
        try:
            pr.archive_candidate(
                baseline_id_value=holdout_saved.baseline_id, root=holdout_root,
                out_dir=out_holdout, report=clean_report(),
                reason="must reject holdout",
            )
        except pr.CandidateArchiveError as exc:
            check("holdout" in str(exc) and no_partial(out_holdout), "B15 holdout 源归档被拒绝且无半成品", str(exc))
        else:
            check(False, "B15 holdout 源归档被拒绝且无半成品", "not rejected")

        # 16. 已存在目标（独立构造，不覆盖既有内容）
        existing_root = base / "baselines-existing"
        existing_run = build_run(base, run_id="run-bad-existing")
        existing_saved = save_baseline(existing_run, existing_root)
        occupied = base / "candidates" / "occupied"
        occupied.mkdir(parents=True, exist_ok=True)
        marker = occupied / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        try:
            pr.archive_candidate(
                baseline_id_value=existing_saved.baseline_id, root=existing_root,
                out_dir=occupied, report=clean_report(), reason="must reject existing target",
            )
        except pr.CandidateArchiveError as exc:
            check(
                "已存在" in str(exc)
                and marker.read_text(encoding="utf-8") == "keep"
                and not list(occupied.parent.glob(".staging-*")),
                "B17 已存在目标被拒绝且原内容未动", str(exc),
            )
        else:
            check(False, "B17 已存在目标被拒绝且原内容未动", "not rejected")

        # 18. 缺 artifact（payload 内必需产物缺失）
        missing_artifact = copy_archive(source_a, base, "missing-artifact")
        (missing_artifact / "payload" / "run" / "summary.json").unlink()
        expect_reject(missing_artifact, "B18 缺 artifact 被拒绝", "文件集合")

        # 19. report 不是 SplitReport
        try:
            pr.archive_candidate(
                baseline_id_value=source_a.name, root=base / "baselines-good-a",
                out_dir=base / "candidates" / "bad-report", report={"not": "a report"},
                reason="must reject bad report",
            )
        except pr.CandidateArchiveError as exc:
            check("SplitReport" in str(exc), "B16 非 SplitReport 被拒绝", str(exc))
        else:
            check(False, "B16 非 SplitReport 被拒绝", "not rejected")

        failed = [name for ok, name, _ in RESULTS if not ok]
        print(f"\nchecks={len(RESULTS)} failed={len(failed)}")
        print("RESULT=" + ("PASS" if not failed else "FAIL"))
        for name in failed:
            print("FAILED_CHECK=" + name)
        return 0 if not failed else 1
    finally:
        for junction in junctions:
            subprocess.run(["cmd", "/c", "rmdir", str(junction)], capture_output=True, text=True, check=False)
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
