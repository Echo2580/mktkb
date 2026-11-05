"""T007 independent acceptance probe (no delivery test fixtures imported).

Modes:
  (default) functional probe: identity / approval / cross-version / diff / report
  --mutations: run delivered tests against runtime-mutated modules; each must fail.

All writes go under %TEMP%. No network, no provider calls, no .env read.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend" / "src" / "mktkb").is_dir():
            return parent
    return Path(r"D:\GPT项目\市场部AI知识库")


REPO = _repo_root()
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass
SRC = REPO / "backend" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import mktkb.evaluation.baseline as baseline_module
from mktkb.evaluation.baseline import (
    BaselineApprovalError,
    CrossVersionBaselineError,
    approve_baseline,
    baseline_id,
    load_baseline,
    save_baseline,
)
from mktkb.evaluation.dataset import CaseSpec, write_cases
from mktkb.evaluation.gate import (
    GateFailure,
    GateResult,
    QualityCheck,
    QualityMetricResult,
    QualityResult,
    evaluate_gate,
    load_gate_config,
    load_run_result,
)
from mktkb.evaluation.report import diff_runs, render_html, render_markdown, require_release_baseline
from mktkb.evaluation.runner import RunManifest, RunResult

TMP = Path(os.environ["TEMP"]) / "t007-verify" / "functional"
shutil.rmtree(TMP, ignore_errors=True)
TMP.mkdir(parents=True, exist_ok=True)
GATE_VERSION = "mktkb.gate.v0.1"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" :: " + detail if detail else ""))


def expect_error(name: str, fn, exc_type) -> None:
    try:
        fn()
    except exc_type as exc:
        check(name, True, f"{type(exc).__name__}: {str(exc)[:100]}")
    except Exception as exc:  # noqa: BLE001
        check(name, False, f"wrong exception {type(exc).__name__}: {exc}")
    else:
        check(name, False, "no exception raised")


def case(case_id: str, stratum: str) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        suite="b0",
        split="dev",
        stratum=stratum,
        business_date="2026-10-28",
        question=f"question {case_id}",
        expected_kind="answer",
        expected_values=("P01",),
        expected_sources=({"doc_code": "D01", "unit_key": "sheet:A:row:8"},),
        labeler="lead",
        label_version="dev-1",
    )


CASES = (case("Q01", "exact"), case("Q02", "text"), case("Q03", "exact"))


def row(spec: CaseSpec, status: str, value_hit: float, latency: int | None,
        cost: float | None = None) -> dict:
    return {
        "case_id": spec.case_id,
        "suite": spec.suite,
        "status": status,
        "trace_id": f"trace-{spec.case_id}",
        "previous_trace_id": None,
        "replayed": False,
        "checks": [],
        "metrics": {
            "Recall@10": value_hit,
            "MRR@10": value_hit,
            "nDCG@10": value_hit,
            "hard_filter_violations": 0,
            "retrieved_units": 1,
            "empty_recall": 0.0 if value_hit else 1.0,
            "value_hit": value_hit,
            "source_hit": value_hit,
            "kind_correct": value_hit,
            "citation_precision": value_hit,
            "citation_recall": value_hit,
        },
        "refused": False,
        "should_refuse": False,
        "path": "rag",
        "latency_ms": latency,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_cny": cost,
        "duration_ms": int(latency or 0),
        "turns_executed": 1,
        "multi_turn_claimed": False,
        "outcome": {"kind": "answer", "text": "P01", "citations": [], "retrieved": []},
        "gold": {"case_id": spec.case_id, "sources": []},
        "error": {"code": "boom"} if status == "error" else None,
    }


def manifest(name: str, **overrides) -> RunManifest:
    payload = dict(
        run_id=name,
        mode="local",
        scope="end_to_end",
        suite="b0",
        dataset_version="b0:dev-1:0123456789ab",
        dataset_sha256="a" * 64,
        corpus_manifest_sha256="b" * 64,
        business_date="2026-10-28",
        index_revision=6,
        pipeline_version="pipeline-v1",
        gate_version=GATE_VERSION,
        label_version="dev-1",
        created_at="2026-11-05T00:00:00.000+00:00",
        case_count=len(CASES),
        config_hash="c" * 12,
        dataset_path="",
    )
    payload.update(overrides)
    return RunManifest(**payload)


def write_run(name: str, rows: list[dict], **overrides) -> RunResult:
    run_dir = TMP / name
    run_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = TMP / f"{name}.dataset.jsonl"
    write_cases(dataset_path, list(CASES))
    man = dataclasses.replace(manifest(name, **overrides), dataset_path=str(dataset_path))
    (run_dir / "run_manifest.json").write_bytes(
        (json.dumps(man.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    (run_dir / "cases.jsonl").write_bytes(
        "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in rows).encode("utf-8")
    )
    summary = {"run_id": man.run_id, "suite": man.suite, "mode": man.mode, "status_counts": {}}
    (run_dir / "summary.json").write_bytes(
        (json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )
    return RunResult(manifest=man, out_dir=run_dir, cases=tuple(rows), summary=summary)


def quality(status: str = "pass", config_status: str = "approved",
            metrics: tuple[QualityMetricResult, ...] = ()) -> QualityResult:
    return QualityResult(
        status=status,
        metrics=metrics,
        strata=("all",),
        stratum_status={"all": status},
        failures=(),
        unknowns=(),
        waived=(),
        diagnostics={},
        warnings=(),
        config_status=config_status,
        gate_config_hash="f" * 64,
        baseline_run_id=None,
        baseline_pipeline_version=None,
    )


def gate(exit_code: int = 0, *, run_id: str, quality_obj: QualityResult | None = None,
         hard_failures: tuple[str, ...] = ()) -> GateResult:
    return GateResult(
        exit_code=exit_code,
        gate_status={gid: ("fail" if gid in hard_failures else "pass")
                     for gid in ("security_leak", "citation_required")},
        hard_failures=hard_failures,
        failures=(GateFailure("citation_required", "Q03", "missing_citation", {}),) if hard_failures else (),
        unknowns=(),
        not_applicable=(),
        warnings=(),
        run_id=run_id,
        suite="b0",
        mode="local",
        gate_version=GATE_VERSION,
        scored_count=3,
        min_sample=3,
        quality=quality_obj,
    )


def value_metric() -> QualityMetricResult:
    return QualityMetricResult(
        metric="value_hit", group="answer", stratum="all", direction="higher_is_better",
        observed=2.0 / 3.0, denominator=3, dataset_sample=3,
        denominator_basis="scored_cases_non_ocr", source="cases.jsonl", status="pass",
        checks=(QualityCheck("approval", "pass", observed=2.0 / 3.0, denominator=3,
                             detail={"reason": "thresholds_unapproved"}),),
    )


def independent_id(man: RunManifest) -> str:
    raw = (man.dataset_version + man.pipeline_version + man.mode + man.scope
           + man.gate_version + man.corpus_manifest_sha256)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def functional() -> None:
    print("== functional probe (synthetic runs, fresh root) ==")
    base_man = manifest("run-base")
    expected = independent_id(base_man)
    check("5.1 independent formula matches baseline_id", baseline_id(base_man) == expected, expected)
    other_meta = manifest("run-other", created_at="2026-01-01T00:00:00.000+00:00",
                          dataset_path="x.jsonl")
    check("5.1 run_id/time/path do not enter identity", baseline_id(other_meta) == expected)
    per_field = {
        "dataset_version": "b0:dev-2:ffffffffffff",
        "pipeline_version": "pipeline-v2",
        "mode": "replay",
        "scope": "retrieval_only",
        "gate_version": "mktkb.gate.v9.9",
        "corpus_manifest_sha256": "d" * 64,
    }
    baseline_sample = expected
    for field, value in per_field.items():
        mutated = manifest("run-" + field, **{field: value})
        got = baseline_id(mutated)
        check(f"5.1 field {field} changes id", got != baseline_sample, got)
        if field == "mode":
            check("5.1 mode=live rejected", _live_rejected())

    base_rows = [row(CASES[0], "fail", 1.0, 10), row(CASES[1], "fail", 0.0, 20),
                 row(CASES[2], "pass", 0.5, 30)]
    run_base = write_run("run-base", base_rows)
    root = TMP / "baselines"
    saved = save_baseline(run_base, root)
    check("5.1 save/load roundtrip id", load_baseline(saved.baseline_id, root).baseline_id == saved.baseline_id)
    check("5.1 no copy/rename API", not [n for n in dir(baseline_module)
          if "copy" in n.lower() or "rename" in n.lower()])

    # §5.2 approval guards
    expect_error("5.2 missing approver rejected",
                 lambda: approve_baseline(run_base, gate(0, run_id=run_base.manifest.run_id,
                                                         quality_obj=quality()),
                                         TMP / "root-missing-approver", approver="", reason="x"),
                 BaselineApprovalError)
    check("5.2 missing approver writes nothing", not (TMP / "root-missing-approver").exists())
    expect_error("5.2 blank reason rejected",
                 lambda: approve_baseline(run_base, gate(0, run_id=run_base.manifest.run_id,
                                                         quality_obj=quality()),
                                         TMP / "root-blank-reason", approver="owner", reason="  "),
                 BaselineApprovalError)
    check("5.2 blank reason writes nothing", not (TMP / "root-blank-reason").exists())
    g3 = gate(3, run_id=run_base.manifest.run_id,
              quality_obj=quality("unknown", config_status="unapproved"))
    try:
        approve_baseline(run_base, g3, TMP / "root-exit3", approver="owner", reason="try")
    except BaselineApprovalError as exc:
        check("5.2 exit 3 rejected with reason", "阈值未审批" in str(exc), str(exc)[:120])
    else:
        check("5.2 exit 3 rejected with reason", False, "no exception")
    check("5.2 exit 3 writes no baseline/approval",
          not (TMP / "root-exit3").exists())

    ok_gate = gate(0, run_id=run_base.manifest.run_id, quality_obj=quality(metrics=(value_metric(),)))
    approved = approve_baseline(run_base, ok_gate, root, approver="owner",
                                reason="T007 acceptance probe")
    approval_path = root / approved.baseline_id / "approval.json"
    check("5.2 approval.json exists", approval_path.is_file())
    payload = json.loads(approval_path.read_text(encoding="utf-8"))
    required = ("run_id", "gate_result_sha256", "dataset_version", "pipeline_version",
                "corpus_sha256", "approver", "reason", "approved_at")
    check("5.2 approval.json has 8 required fields",
          all(payload.get(key) for key in required), ",".join(required))
    canonical = json.dumps(ok_gate.to_dict(), ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    check("5.2 gate_result_sha256 independently matches", payload["gate_result_sha256"] == digest)
    check("5.2 approval binds identity", payload["dataset_version"] == base_man.dataset_version
          and payload["pipeline_version"] == base_man.pipeline_version
          and payload["corpus_sha256"] == base_man.corpus_manifest_sha256)
    expect_error("5.2 approval cannot be overwritten",
                 lambda: approve_baseline(run_base, ok_gate, root, approver="other", reason="x"),
                 BaselineApprovalError)

    # §5.3 cross-version
    p1_root = TMP / "baselines-p1"
    p1_run = write_run("run-p1", base_rows, pipeline_version="pipeline-p1", run_id="run-p1")
    p1_saved = save_baseline(p1_run, p1_root)
    p2_run = write_run("run-p2", base_rows, pipeline_version="pipeline-p2", run_id="run-p2")
    expect_error("5.3 diff cross-version rejected without compare_with",
                 lambda: diff_runs(p1_saved, p2_run), CrossVersionBaselineError)
    expect_error("5.3 load cross-version rejected without compare_with",
                 lambda: load_baseline(p1_saved.baseline_id, p1_root,
                                       expected=p2_run.manifest), CrossVersionBaselineError)
    cross = diff_runs(p1_saved, p2_run, compare_with=p1_saved.baseline_id)
    check("5.3 explicit compare marks explicit_cross_version",
          cross.comparison == "explicit_cross_version" and cross.release_allowed is False,
          f"{cross.comparison}/{cross.release_allowed}")
    expect_error("5.3 release path rejects cross-version",
                 lambda: require_release_baseline(cross), CrossVersionBaselineError)
    check("5.3 explicit load works", load_baseline(
        p1_saved.baseline_id, p1_root, expected=p2_run.manifest,
        compare_with=p1_saved.baseline_id).baseline_id == p1_saved.baseline_id)

    # §5.4 diff
    current_rows = [row(CASES[0], "pass", 1.0, 10), row(CASES[1], "fail", 0.0, 20),
                    row(CASES[2], "fail", 1.0, 40)]
    run_cur = write_run("run-cur", current_rows, run_id="run-cur")
    unapproved = diff_runs(saved, run_cur)
    check("5.4 new/fixed/still by case_id",
          unapproved.new_failures == ("Q03",)
          and unapproved.fixed_failures == ("Q01",)
          and unapproved.still_failing == ("Q02",),
          f"{unapproved.new_failures}/{unapproved.fixed_failures}/{unapproved.still_failing}")
    check("5.4 release blocked for unapproved baseline",
          unapproved.release_allowed is False
          and unapproved.release_blocked_reason == "baseline_unapproved",
          f"allowed={unapproved.release_allowed} reason={unapproved.release_blocked_reason} "
          f"approval={saved.approval!r}")
    check("5.4 strata all/exact/text", set(unapproved.strata) == {"all", "exact", "text"})

    def delta(metric, stratum):
        found = [d for d in unapproved.metric_deltas
                 if d.metric == metric and d.stratum == stratum]
        assert len(found) == 1, (metric, stratum)
        return found[0]

    d_all = delta("value_hit", "all")
    check("5.4 overall metric delta", abs(d_all.baseline - 0.5) < 1e-12
          and abs(d_all.current - 2.0 / 3.0) < 1e-12
          and abs(d_all.delta - 1.0 / 6.0) < 1e-12, f"{d_all.baseline}->{d_all.current}")
    check("5.4 exact stratum delta", abs(delta("value_hit", "exact").baseline - 0.75) < 1e-12
          and abs(delta("value_hit", "exact").current - 1.0) < 1e-12)
    cost = delta("cost_per_case_cny", "all")
    check("5.4 zero-sample cost stays unknown/non-zero",
          cost.baseline is None and cost.current is None and cost.delta is None
          and cost.status == "unknown" and cost.baseline_denominator == 0
          and "zero_sample" in (cost.reason or ""), cost.reason or "")
    latency = delta("p95_latency_ms", "all")
    check("5.4 p95 no-SLA is regression not pass",
          latency.status == "regressed" and latency.threshold_configured is False)

    run_same = write_run("run-same", [dict(item) for item in base_rows], run_id="run-same")
    same = diff_runs(saved, run_same)
    check("5.4 identical runs -> empty=True, no exception",
          same.empty is True and same.new_failures == () and same.fixed_failures == ()
          and same.status_changes == ())
    base3 = save_baseline(run_base, TMP / "baselines-gate3", gate=g3)
    trans = diff_runs(base3, run_cur, gate=gate(0, run_id=run_cur.manifest.run_id,
                                               quality_obj=quality()))
    check("5.4 gate transition fields 3->0",
          trans.baseline_exit_code == 3 and trans.current_exit_code == 0
          and trans.gate_exit_transition == "3->0" and trans.gate_exit_changed is True,
          trans.gate_exit_transition)
    for code in (1, 2):
        base_i = save_baseline(
            run_base, TMP / f"baselines-g{code}",
            gate=gate(code, run_id=run_base.manifest.run_id,
                      quality_obj=quality("fail" if code == 2 else "unknown",
                                          config_status="unapproved")),
        )
        diff_i = diff_runs(base_i, run_cur, gate=gate(
            0, run_id=run_cur.manifest.run_id, quality_obj=quality()))
        check(f"5.4 gate transition fields {code}->0",
              diff_i.gate_exit_transition == f"{code}->0"
              and diff_i.gate_exit_changed is True, diff_i.gate_exit_transition)

    err_base_rows = [row(CASES[0], "pass", 1.0, 10), row(CASES[1], "error", 0.0, None),
                     row(CASES[2], "pass", 1.0, 30)]
    err_base = write_run("run-errbase", err_base_rows, run_id="run-errbase")
    err_root = TMP / "baselines-err"
    err_saved = save_baseline(err_base, err_root)
    err_cur_rows = [row(CASES[0], "pass", 1.0, 10), row(CASES[1], "pass", 1.0, 20),
                    row(CASES[2], "error", 1.0, None)]
    err_cur = write_run("run-errcur", err_cur_rows, run_id="run-errcur")
    err_diff = diff_runs(err_saved, err_cur)
    check("5.4 error rows separate from pass/fail",
          err_diff.resolved_errors == ("Q02",) and err_diff.new_errors == ("Q03",)
          and err_diff.persistent_errors == ()
          and err_diff.new_failures == () and err_diff.fixed_failures == (),
          f"new_err={err_diff.new_errors} resolved={err_diff.resolved_errors}")
    blocked = diff_runs(load_baseline(saved.baseline_id, root), run_cur,
                        gate=gate(2, run_id=run_cur.manifest.run_id,
                                  quality_obj=quality("fail")))
    check("5.4 failed current gate blocks release",
          blocked.release_allowed is False and blocked.release_blocked_reason == "current_gate_exit_2")
    released = diff_runs(load_baseline(saved.baseline_id, root), run_cur,
                         gate=gate(0, run_id=run_cur.manifest.run_id, quality_obj=quality()))
    check("5.4 approved same-version + exit0 allows release",
          released.release_allowed is True and released.comparison == "release_baseline")
    require_release_baseline(released)
    no_gate = diff_runs(load_baseline(saved.baseline_id, root), run_cur)
    check("OBSERVE no-gate call reports release_allowed", no_gate.release_allowed is True,
          "risk: current gate unknown but release_allowed=True")

    # §5.5 reports
    rgate = gate(1, run_id=run_cur.manifest.run_id,
                 quality_obj=quality("unknown", config_status="unapproved", metrics=(value_metric(),)),
                 hard_failures=("citation_required",))
    md = render_markdown(unapproved, rgate, summary=run_cur.summary)
    html = render_html(run_cur.summary, unapproved, rgate)
    first_section = md.split("## ")[1]
    check("5.5 markdown hard gate first", first_section.startswith("1. 硬门禁（置顶）"), first_section[:20])
    check("5.5 markdown shows exit and hard failure",
          "exit_code: 1" in md and "citation_required" in md)
    check("5.5 markdown unknown thresholds not pass",
          "阈值未审批" in md and "质量通过" not in md)
    check("5.5 html single file no script/link/external",
          html.startswith("<!DOCTYPE html>") and "<style>" in html
          and re.search(r"<script", html, re.I) is None
          and re.search(r"https?://", html) is None
          and re.search(r"\bsrc\s*=", html, re.I) is None
          and re.search(r"\bhref\s*=", html, re.I) is None
          and re.search(r"<link\b", html, re.I) is None,
          f"bytes={len(html.encode('utf-8'))}")
    for token in (saved.baseline_id, run_cur.manifest.run_id, "Q03", "citation_required"):
        check(f"5.5 md/html share token {token}", token in md and token in html)
    gate_source = (SRC / "mktkb" / "evaluation" / "gate.py").read_text(encoding="utf-8").lower()
    check("5.5 gate source never mentions report", "report" not in gate_source)
    before = sorted(p.name for p in run_cur.out_dir.iterdir())
    render_markdown(unapproved, rgate, summary=run_cur.summary)
    render_html(run_cur.summary, unapproved, rgate)
    check("5.5 renderers leave run dir untouched",
          before == sorted(p.name for p in run_cur.out_dir.iterdir()))

    # real %TEMP% artifacts (generated by T007, read-only recheck)
    real = Path(os.environ["TEMP"]) / "t007-baseline-report"
    if (real / "run-baseline" / "run_manifest.json").is_file():
        print("== real %TEMP% artifacts recheck ==")
        real_base = load_run_result(real / "run-baseline")
        rid = baseline_id(real_base.manifest)
        check("real baseline id c0ce2856938f", rid == "c0ce2856938f", rid)
        check("real id independent recompute", rid == independent_id(real_base.manifest))
        real_gate = evaluate_gate(real_base, quality=True,
                                  dataset_path=REPO / "fixtures" / "evaluation" / "b0.jsonl")
        unknown_reasons = sorted({u.check_id or "" for u in real_gate.unknowns})
        check("real clean run default quality=True -> exit 3",
              real_gate.exit_code == 3 and real_gate.quality is not None
              and real_gate.quality.config_status == "unapproved",
              f"exit={real_gate.exit_code} unknowns={len(real_gate.unknowns)}")
        check("real exit 3 unknown reason thresholds_unapproved",
              unknown_reasons == ["thresholds_unapproved"], str(unknown_reasons))
        try:
            approve_baseline(real_base, real_gate, TMP / "real-reject",
                             approver="acceptance", reason="must reject")
        except BaselineApprovalError as exc:
            check("real approval rejected", "阈值未审批" in str(exc), str(exc)[:100])
        else:
            check("real approval rejected", False, "no exception")
        check("real rejection writes no root", not (TMP / "real-reject").exists())

        if (real / "run-current" / "run_manifest.json").is_file() and (
                real / "gate-fixture-approved.json").is_file():
            real_cur = load_run_result(real / "run-current")
            fixture = load_gate_config(real / "gate-fixture-approved.json")
            real_base_saved = load_baseline("c0ce2856938f", real / "baselines")
            cur_gate = evaluate_gate(real_cur, config=fixture, quality=True,
                                     dataset_path=REPO / "fixtures" / "evaluation" / "b0.jsonl")
            real_diff = diff_runs(real_base_saved, real_cur, gate=cur_gate, config=fixture)
            check("real diff new Q27 / still Q25,Q26,Q31",
                  real_diff.new_failures == ("Q27",)
                  and real_diff.still_failing == ("Q25", "Q26", "Q31")
                  and real_diff.fixed_failures == (),
                  f"new={real_diff.new_failures} still={real_diff.still_failing}")
            check("real gate transition 0->2", real_diff.gate_exit_transition == "0->2",
                  real_diff.gate_exit_transition)
            real_md = render_markdown(real_diff, cur_gate, summary=real_cur.summary)
            real_html = render_html(real_cur.summary, real_diff, cur_gate)
            counts = (len(re.findall(r"<script", real_html, re.I)),
                      len(re.findall(r"https?://", real_html)),
                      len(re.findall(r"<link\b", real_html, re.I)))
            check("real html self-check 0/0/0", counts == (0, 0, 0), str(counts))
            check("real html <style> inline", "<style>" in real_html)
            check("real md first section hard gate",
                  real_md.split("## ")[1].startswith("1. 硬门禁（置顶）"))
            print(f"INFO real md bytes={len(real_md.encode('utf-8'))} lines={real_md.count(chr(10))}")
            print(f"INFO real html bytes={len(real_html.encode('utf-8'))}")
    else:
        print("SKIP real %TEMP% artifacts not found")

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\nfunctional: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed))


def _live_rejected() -> bool:
    try:
        baseline_id(manifest("live", mode="live"))
    except baseline_module.BaselineIdentityError:
        return True
    return False


PLUGIN_SOURCE = {
    "id": """
import mktkb.evaluation.baseline as b
_f = b.BASELINE_ID_FIELDS[:-1]
def _canonical(self):
    return "".join(getattr(self, n) for n in _f)
b.BaselineIdentity.canonical = _canonical
""",
    "approval": """
import mktkb.evaluation.baseline as b
b._reject_approval = lambda run, gate: None
""",
    "cross": """
import mktkb.evaluation.baseline as b
import mktkb.evaluation.report as r
_noop = lambda *a, **k: None
b._ensure_comparable = _noop
r._ensure_comparable = _noop
""",
    "html": """
import mktkb.evaluation.report as r
_orig = r.render_html
def _render(*a, **k):
    out = _orig(*a, **k)
    return out.replace("</head>", "<link rel='stylesheet' href='https://example.com/x.css'>\\n</head>")
r.render_html = _render
""",
}
MUTATION_TESTS = {
    "id": ["backend/tests/evaluation/test_baseline.py::test_baseline_id_matches_documented_formula",
           "backend/tests/evaluation/test_baseline.py::test_baseline_id_changes_when_any_field_changes"],
    "approval": ["backend/tests/evaluation/test_baseline.py::test_approval_rejects_nonzero_gate",
                 "backend/tests/evaluation/test_baseline.py::test_approval_rejects_unapproved_thresholds_exit_three"],
    "cross": ["backend/tests/evaluation/test_baseline.py::test_cross_version_load_requires_explicit_compare_with",
              "backend/tests/evaluation/test_report.py::test_diff_cross_version_is_rejected_by_default"],
    "html": ["backend/tests/evaluation/test_report.py::test_html_is_single_file_inline_css_no_script_no_external"],
}


def mutations() -> None:
    print("== mutation probe (repo unmodified; plugin lives in %TEMP%) ==")
    plugdir = Path(os.environ["TEMP"]) / "t007-verify" / "mutplugins"
    plugdir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(plugdir) + os.pathsep + env.get("PYTHONPATH", "")
    env["MKTKB_PROJECT_TOTAL_LIMIT_CNY"] = "20.0"
    env["PYTHONIOENCODING"] = "utf-8"
    ok_all = True
    for mode, source in PLUGIN_SOURCE.items():
        plugin = plugdir / f"mut_{mode}_plugin.py"
        plugin.write_text(source, encoding="utf-8")
        cmd = [sys.executable, "-B", "-m", "pytest", *MUTATION_TESTS[mode],
               "-q", "-p", "no:cacheprovider", "-p", f"mut_{mode}_plugin"]
        proc = subprocess.run(cmd, cwd=str(REPO), env=env, text=True,
                              encoding="utf-8", errors="replace",
                              capture_output=True, timeout=300)
        tail = "\n".join(proc.stdout.strip().splitlines()[-4:])
        caught = proc.returncode != 0 and "failed" in proc.stdout
        ok_all = ok_all and caught
        print(("PASS " if caught else "FAIL ")
              + f"mutation '{mode}' turns tests red (exit={proc.returncode})")
        print("  " + tail.replace("\n", "\n  "))
    print(f"\nmutation: {'all caught' if ok_all else 'ESCAPED'}")
    if not ok_all:
        RESULTS.append(("mutation", False, "escaped"))


if __name__ == "__main__":
    if "--mutations" in sys.argv:
        mutations()
        sys.exit(1 if any(not ok for _, ok, _ in RESULTS) else 0)
    functional()
    sys.exit(0 if all(ok for _, ok, _ in RESULTS) else 1)
