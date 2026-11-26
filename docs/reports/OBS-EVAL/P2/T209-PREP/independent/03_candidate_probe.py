"""T209-PREP 独立验收：candidate 不可发布 / 正常归档可恢复（独立构造）。

在系统临时目录完成：未审批 baseline 的 archive→verify→restore→list→diff；
核对 publishable/release_baseline/gate_approved/has_approval 恒 false、恢复后
approval=None、无 approval.json、diff_runs 返回 baseline_unapproved、approve_baseline
调用次数为 0；并独立验证改元数据 / 改 state / 加 approved 字段不能抬升为可发布。
不写正式 registry，不读取真实私有材料。
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
from mktkb.evaluation.baseline import (  # noqa: E402
    APPROVAL_FILENAME,
    Baseline,
    baseline_identity,
    load_baseline,
    save_baseline,
)
from mktkb.evaluation.dataset import CaseSpec, write_cases  # noqa: E402
from mktkb.evaluation.gate import GateResult  # noqa: E402
from mktkb.evaluation.report import diff_runs, require_release_baseline  # noqa: E402
from mktkb.evaluation.runner import RunManifest, RunResult  # noqa: E402
from mktkb.observability.contracts import GATE_SCHEMA_VERSION  # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []
ROUND = "T209P-INDEP-CAND-ROUND"
FINANCE = dict(
    ledger_current_sha256="ca9dceb9019790eb6ba4e25cfaf88232915b607d756d0eae21ad7cdf10c6fec9",
    ledger_previous_sha256="4d80d776bcf25079817f5f7dd8863037c27bc01971b6fa0fe239b432ee55fcc6",
    ledger_change_cause="legitimate_spend",
    go_current_sha256="c72dc7abf6ba135fb6c53f77c35b40dda34e97cf535d3be212467c6734b27324",
    go_archived_sha256="f688ec7efb7e8ddc145ae9fd593a482a85a6e4a764a9d49a09eab4f3fc26ea98",
    archived_line_moment="indep synthetic moment",
)
APPROVE_CALLS = {"n": 0}
ORIGINAL_APPROVE = baseline_module.approve_baseline


def fake_approve(*args, **kwargs):  # noqa: ANN002, ANN003
    APPROVE_CALLS["n"] += 1
    raise AssertionError("candidate 流程不得调用 approve_baseline")


baseline_module.approve_baseline = fake_approve


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def cases(total: int = 30) -> tuple[CaseSpec, ...]:
    return tuple(
        CaseSpec(
            case_id=f"IND{index:03d}",
            suite="b0",
            split="dev",
            stratum="exact",
            business_date="2026-10-28",
            question=f"synthetic question {index}",
            expected_kind="answer",
            expected_values=("SYNTH",),
            expected_sources=({"doc_code": "D01", "unit_key": f"sheet:S:row:{index}"},),
            labeler="synthetic",
            label_version="dev-1",
        )
        for index in range(1, total + 1)
    )


def build_run(base: Path, *, run_id: str, pipeline: str, rows=None, scope: str = "end_to_end") -> RunResult:
    case_set = cases()
    dataset = base / f"{run_id}.dataset.jsonl"
    write_cases(dataset, list(case_set))
    manifest = RunManifest(
        run_id=run_id,
        mode="local",
        scope=scope,
        suite="b0",
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
    row_payload = rows or tuple({"case_id": case.case_id, "status": "pass"} for case in case_set)
    run_dir = base / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "cases.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in row_payload),
        encoding="utf-8",
    )
    summary = {"run_id": run_id, "suite": "b0", "mode": "local"}
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return RunResult(manifest=manifest, out_dir=run_dir, cases=tuple(row_payload), summary=summary)


def clean_report(*, round_id: str = ROUND, passed: int = 30) -> pr.SplitReport:
    axes = tuple(
        pr.AxisEvidence.create(
            axis=axis, planned=30, passed=passed, not_applicable=30 - passed, unknown=0, violations=0
        )
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
            round_id=round_id,
            runs=(pr.RunOutcome("s0", "synthetic", "succeeded", 30, 30),),
        ),
        quality=pr.build_quality(
            round_id=round_id,
            total=30,
            passed=passed,
            failed=30 - passed,
            errors=0,
            safety_violations=0,
            min_pass=24,
            thresholds_approved=False,
            verified=True,
            scenario_verifications=(("s0", True),),
        ),
        evidence=pr.build_evidence(
            round_id=round_id, total=30, missing_evidence_cases=0, axes=axes, verified=True
        ),
        soft=(pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="synthetic"),),
        funding=pr.FundingStatus.create(**FINANCE),
    )


def blocked_report(*, round_id: str = ROUND) -> pr.SplitReport:
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
            plan_id=round_id,
            code_version="synthetic",
        ),
        execution=pr.build_execution(
            round_id=round_id,
            runs=(pr.RunOutcome("s0", "synthetic", "succeeded", 30, 30),),
        ),
        quality=pr.build_quality(
            round_id=round_id, total=30, passed=19, failed=11, errors=0, safety_violations=2,
            min_pass=24, thresholds_approved=False, verified=False,
            scenario_verifications=(("s0", False),),
        ),
        evidence=pr.build_evidence(
            round_id=round_id, total=30, missing_evidence_cases=27, axes=axes, verified=False
        ),
        soft=(pr.SoftStatus.unknown("auxiliary", recorded_status="unavailable", detail="syn"),),
        funding=pr.FundingStatus.create(**FINANCE),
    )


def digest_tree(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(Path(directory).rglob("*"))
        if path.is_file()
    }


def expect_archive_error(fn, needle: str, name: str) -> None:
    try:
        fn()
    except pr.CandidateArchiveError as exc:
        check(needle in str(exc), name, f"rejected={exc}")
    except Exception as exc:  # noqa: BLE001
        check(False, name, f"unexpected {type(exc).__name__}: {exc}")
    else:
        check(False, name, "not rejected")


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="t209p-indep-cand-"))
    try:
        root = base / "baselines"
        run = build_run(base, run_id="run-indep-candidate", pipeline="pipelineIND1")
        saved = save_baseline(run, root)
        check(saved.approval is None and saved.approved is False, "S0 源 baseline 未审批")
        out = base / "candidates" / "candidate-a"
        report = clean_report()
        check(pr.candidate_state_for_report(report) == "candidate", "S1 干净报告派生 candidate")
        record = pr.archive_candidate(
            baseline_id_value=saved.baseline_id,
            root=root,
            out_dir=out,
            report=report,
            reason="independent synthetic candidate (never publishable)",
        )
        check(record.state == "candidate", "S2 archive state=candidate")
        check(
            all(getattr(record, field) is False for field in ("publishable", "release_baseline", "gate_approved", "has_approval", "approved")),
            "S3 CandidateArchive 五项发布属性恒 false",
        )
        check(len(record.files) == 5, "S4 archive files=5", str(sorted(record.files)))
        check(not (out / "payload" / APPROVAL_FILENAME).exists(), "S5 归档 payload 无 approval.json")
        manifest = json.loads((out / pr.CANDIDATE_FILENAME).read_text(encoding="utf-8"))
        check(set(manifest) == pr.CANDIDATE_MANIFEST_KEYS and len(pr.CANDIDATE_MANIFEST_KEYS) == 18, "S6 manifest 18 字段固定")
        check(all(manifest[key] is False for key in ("publishable", "release_baseline", "gate_approved", "has_approval")), "S7 manifest 四项恒 false")
        check(manifest["report"]["quality"]["release_ready"] is False, "S8 manifest 报告 release_ready=false")
        check(manifest["baseline_id"] == saved.baseline_id and manifest["run_id"] == saved.run_id, "S9 manifest 绑定 payload 身份/run")

        verified = pr.verify_candidate_archive(out)
        check(verified.identity == saved.identity and verified.run_id == saved.run_id, "S10 verify 重算身份/run 一致")
        check(verified.state == "candidate" and verified.has_approval is False, "S11 verify state/candidate + has_approval=false")

        restore_root = base / "restore" / "baselines"
        before = digest_tree(base / "candidates")
        restored = pr.restore_candidate(out, restore_root)
        check(digest_tree(base / "candidates") == before, "S12 restore 不改源归档字节")
        reloaded = load_baseline(restored.baseline_id, restore_root)
        check(reloaded.approval is None and reloaded.approved is False, "S13 恢复后 approval=None / approved=False")
        check(not (Path(restored.baseline_dir) / APPROVAL_FILENAME).exists(), "S14 恢复目录无 approval.json")
        check(reloaded.identity == saved.identity and reloaded.run_id == saved.run_id, "S15 恢复身份/run 一致")
        check(restored.publishable is False and restored.release_baseline is False, "S16 RestoreResult 发布属性 false")

        # candidate 永远不能成为 release baseline
        current = build_run(base, run_id="run-indep-current", pipeline="pipelineIND1")
        gate = GateResult(
            exit_code=0, gate_status={}, hard_failures=(), failures=(), unknowns=(),
            not_applicable=(), warnings=(), run_id=current.manifest.run_id, suite="b0",
            mode="local", gate_version=GATE_SCHEMA_VERSION, scored_count=30, min_sample=None,
            quality=None,
        )
        diff = diff_runs(reloaded, current, gate=gate)
        check(diff.release_allowed is False, "S17 diff_runs 不放行 candidate")
        check(diff.release_blocked_reason == "baseline_unapproved", "S18 release_blocked_reason=baseline_unapproved", str(diff.release_blocked_reason))
        try:
            require_release_baseline(diff)
        except ValueError:
            check(True, "S19 require_release_baseline 拒绝")
        else:
            check(False, "S19 require_release_baseline 拒绝", "not raised")

        # blocked 归档
        root_b = base / "baselines-b"
        run_b = build_run(base, run_id="run-indep-blocked", pipeline="pipelineIND2")
        saved_b = save_baseline(run_b, root_b)
        out_b = base / "candidates" / "blocked-b"
        record_b = pr.archive_candidate(
            baseline_id_value=saved_b.baseline_id, root=root_b, out_dir=out_b,
            report=blocked_report(round_id="T209P-INDEP-CAND-ROUND-B"),
            reason="independent blocked (quality fail)",
        )
        check(record_b.state == "blocked" and record_b.publishable is False, "S20 质量 FAIL 归档 state=blocked 且不可发布")
        manifest_b = json.loads((out_b / pr.CANDIDATE_FILENAME).read_text(encoding="utf-8"))
        check(manifest_b["report"]["quality"]["status"] == "fail" and manifest_b["report"]["evidence"]["missing_evidence_cases"] == 27, "S21 blocked manifest 保留 FAIL/27 缺证据")

        # list 确定性
        first = pr.list_candidates(base / "candidates")
        second = pr.list_candidates(base / "candidates")
        check(first == second, "S22 list 两次结果一致")
        check([item.archive_dir for item in first] == sorted(item.archive_dir for item in first), "S23 list 按 archive_dir 排序")
        check([item.state for item in first] == ["blocked", "candidate"] or [item.state for item in first] == ["candidate", "blocked"], "S24 list 覆盖 candidate/blocked", str([item.state for item in first]))
        check(all(item.publishable is False and item.release_baseline is False for item in first), "S25 list 行发布属性 false")

        # diff 语义
        same = pr.diff_candidates(out, out)
        check(same.same_identity and same.same_round and same.files_changed == (), "S26 自 diff 同身份/同轮/无变化")
        check(same.scores_comparable is True and same.score_merge_allowed is False, "S27 同身份可对比但禁止合并")
        cross_round = pr.diff_candidates(out, out_b)
        check(cross_round.same_round is False and cross_round.scores_comparable is False and cross_round.score_merge_allowed is False, "S28 跨轮 scores_comparable=false / merge=false")
        check("跨轮" in cross_round.scores_reason, "S29 跨轮原因显式")

        # 同 round 不同 pipeline
        root_c = base / "baselines-c"
        run_c = build_run(base, run_id="run-indep-pipe", pipeline="pipelineIND9")
        saved_c = save_baseline(run_c, root_c)
        out_c = base / "candidates" / "pipe-c"
        pr.archive_candidate(baseline_id_value=saved_c.baseline_id, root=root_c, out_dir=out_c, report=clean_report(), reason="indep pipeline diff")
        pipe = pr.diff_candidates(out, out_c)
        check(pipe.same_round is True and pipe.same_identity is False, "S30 同轮不同 pipeline identity 不同")
        check(pipe.scores_comparable is False and pipe.score_merge_allowed is False, "S31 跨 pipeline 不可比/禁合并")
        check(any(name == "pipeline_version" for name, _l, _r in pipe.identity_changes), "S32 identity_changes 含 pipeline_version")

        # 同 round 不同 scope
        root_d = base / "baselines-d"
        run_d = build_run(base, run_id="run-indep-scope", pipeline="pipelineIND1", scope="retrieval_only")
        saved_d = save_baseline(run_d, root_d)
        out_d = base / "candidates" / "scope-d"
        pr.archive_candidate(baseline_id_value=saved_d.baseline_id, root=root_d, out_dir=out_d, report=clean_report(), reason="indep scope diff")
        scope_diff = pr.diff_candidates(out, out_d)
        check(scope_diff.same_round is True and scope_diff.same_identity is False, "S32b 同轮不同 scope identity 不同")
        check(scope_diff.scores_comparable is False and scope_diff.score_merge_allowed is False, "S32c 跨 scope 不可比/禁合并")
        check(any(name == "scope" for name, _l, _r in scope_diff.identity_changes), "S32d identity_changes 含 scope")

        # 元数据/state/approved 抬升不可发布
        tamper = base / "tamper-copy"
        shutil.copytree(out, tamper)
        mp = tamper / pr.CANDIDATE_FILENAME
        original = json.loads(mp.read_text(encoding="utf-8"))
        for key in ("publishable", "release_baseline", "gate_approved", "has_approval"):
            payload = json.loads(json.dumps(original))
            payload[key] = True
            mp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            expect_archive_error(lambda: pr.verify_candidate_archive(tamper), key, f"S33 改 {key}=true 被拒绝")
        payload = json.loads(json.dumps(original))
        payload["approved"] = True
        mp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        expect_archive_error(lambda: pr.verify_candidate_archive(tamper), "字段", "S34 加 approved 字段被拒绝")
        payload = json.loads(json.dumps(original))
        payload["state"] = "blocked"
        mp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        expect_archive_error(lambda: pr.verify_candidate_archive(tamper), "state", "S35 state 翻转被拒绝")
        payload = json.loads(json.dumps(original))
        payload["report"]["quality"]["release_ready"] = True
        payload["report_sha256"] = hashlib.sha256(
            json.dumps(payload["report"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        mp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        expect_archive_error(lambda: pr.verify_candidate_archive(tamper), "规范形式", "S36 报告 release_ready=true 抬升被拒绝")
        shutil.rmtree(tamper)

        # 正式 registry / 受保护目录 / 归档内部
        formal = ROOT / "var" / "eval" / "baselines"
        formal_before = sorted(path.name for path in formal.iterdir()) if formal.exists() else []
        expect_archive_error(
            lambda: pr.archive_candidate(
                baseline_id_value=saved.baseline_id, root=root,
                out_dir=formal / "t209-indep-should-not-exist", report=report,
                reason="must be rejected",
            ),
            "正式", "S37 归档到正式 registry 被拒绝",
        )
        expect_archive_error(
            lambda: pr.archive_candidate(
                baseline_id_value=saved.baseline_id, root=root,
                out_dir=ROOT / "docs/reports/OBS-EVAL/P2/T209-PREP/independent/should-not-exist",
                report=report, reason="must be rejected",
            ),
            "受保护", "S38 归档到受保护 docs/reports 被拒绝",
        )
        check(
            (sorted(path.name for path in formal.iterdir()) if formal.exists() else []) == formal_before
            and not (formal / "t209-indep-should-not-exist").exists()
            and not (ROOT / "docs/reports/OBS-EVAL/P2/T209-PREP/independent/should-not-exist").exists(),
            "S39 正式 registry/受保护目录无任何新写入",
        )
        expect_archive_error(
            lambda: pr.restore_candidate(out, formal / "t209-indep-restore"),
            "正式", "S40 恢复到正式 registry 被拒绝",
        )
        check(not (formal / "t209-indep-restore").exists(), "S41 正式 registry 无恢复残留")
        expect_archive_error(
            lambda: pr.restore_candidate(out, out / "inside"),
            "内部", "S42 恢复到归档内部被拒绝",
        )

        # 审批从未被调用
        check(APPROVE_CALLS["n"] == 0, "S43 candidate 全链 approve_baseline 调用次数=0", str(APPROVE_CALLS))
        check(not hasattr(pr, "approve_baseline"), "S44 新模块未绑定 approve_baseline 名称")
        # 全链内未出现 approval.json（临时树搜索，排除源 formal）
        approvals = [path for path in base.rglob(APPROVAL_FILENAME)]
        check(not approvals, "S45 临时树无 approval.json", str(approvals))

        failed = [name for ok, name, _ in RESULTS if not ok]
        print(f"\nchecks={len(RESULTS)} failed={len(failed)}")
        print("RESULT=" + ("PASS" if not failed else "FAIL"))
        for name in failed:
            print("FAILED_CHECK=" + name)
        return 0 if not failed else 1
    finally:
        baseline_module.approve_baseline = ORIGINAL_APPROVE
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
