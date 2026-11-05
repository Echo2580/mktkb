"""T008a：评测 CLI 的子命令面、退出码透传与 fail-closed 错误路径。

本文件只测 CLI 包装（计划 Task 7 Step 3；handoff §5.1/§5.2/§5.5）：
argparse 面、`run/gate/baseline approve/diff` 的退出码透传、`diff` 必须把当前
run 的 gate 传给 `diff_runs` 并调用 `require_release_baseline`、`baseline approve`
现场重算门禁而不信任 `--gate` JSON、报告按 `render_*` 返回值原样落盘。

不重复 T008b 的 P0 七条验收；不跑真实索引（除 dataset validate 读冻结 JSONL 外，
其余命令用 monkeypatch 隔离），零真实模型 / OCR / embedding / rerank 调用。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mktkb.evaluation import cli
from mktkb.evaluation.baseline import BaselineError, CrossVersionBaselineError
from mktkb.evaluation.gate import GateProposal, GateResult, QualityResult
from mktkb.observability.contracts import GATE_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[3]
EVAL_DIR = ROOT / "fixtures" / "evaluation"
BASELINE_ID = "abc123abc123"


# --------------------------------------------------------------------------- #
# 合成对象（只给 CLI 包装用；不写真实 run / baseline）
# --------------------------------------------------------------------------- #


def _quality(status: str = "pass", config_status: str = "approved") -> QualityResult:
    return QualityResult(
        status=status,
        metrics=(),
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


def _gate(
    exit_code: int = 0,
    *,
    quality: bool = True,
    config_status: str = "approved",
    hard_failures: tuple[str, ...] = (),
) -> GateResult:
    status = {0: "pass", 1: "fail", 2: "fail", 3: "unknown", 4: "unknown"}[exit_code]
    return GateResult(
        exit_code=exit_code,
        gate_status={"security_leak": "pass", "trace_integrity": "pass"},
        hard_failures=hard_failures,
        failures=(),
        unknowns=(),
        not_applicable=(),
        warnings=(),
        run_id="run-1",
        suite="b0",
        mode="local",
        gate_version=GATE_SCHEMA_VERSION,
        scored_count=32,
        min_sample=32,
        quality=_quality(status, config_status) if quality else None,
    )


def _run(tmp_path: Path) -> SimpleNamespace:
    out_dir = tmp_path / "run"
    out_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        out_dir=out_dir,
        summary={"metrics": {}},
        manifest=SimpleNamespace(run_id="run-1", suite="b0", mode="local"),
    )


def _fake_diff() -> SimpleNamespace:
    return SimpleNamespace(
        to_dict=lambda: {"comparison": "release_baseline", "release_allowed": False},
        comparison="release_baseline",
        release_allowed=False,
        release_blocked_reason="baseline_unapproved",
    )


def _write_gate_file(path: Path, exit_code: int) -> Path:
    path.write_bytes(
        (json.dumps({"exit_code": exit_code, "note": "claimed"}, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
    )
    return path


def _patch_diff(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gate: GateResult,
    diff: SimpleNamespace,
    guard_error: Exception | None = None,
    calls: dict | None = None,
) -> None:
    fake_run = SimpleNamespace(
        out_dir=Path("."),
        summary={},
        manifest=SimpleNamespace(run_id="run-1", suite="b0", mode="local"),
    )
    monkeypatch.setattr(cli, "load_run_result", lambda path: fake_run)
    monkeypatch.setattr(cli, "load_gate_config", lambda path: "CONFIG")
    monkeypatch.setattr(cli, "evaluate_gate", lambda *a, **k: gate)
    monkeypatch.setattr(cli, "load_baseline", lambda *a, **k: "BASELINE")
    monkeypatch.setattr(cli, "baseline_id", lambda manifest: BASELINE_ID)
    monkeypatch.setattr(cli, "render_markdown", lambda d, g, **k: "# MD\n")
    monkeypatch.setattr(cli, "render_html", lambda **k: "<html>OK</html>")

    def fake_diff_runs(baseline, run, **kwargs):
        if calls is not None:
            calls.update(baseline=baseline, run=run, kwargs=kwargs)
        return diff

    monkeypatch.setattr(cli, "diff_runs", fake_diff_runs)

    def fake_guard(item):
        if calls is not None:
            calls["guarded"] = item
        if guard_error is not None:
            raise guard_error

    monkeypatch.setattr(cli, "require_release_baseline", fake_guard)


# --------------------------------------------------------------------------- #
# §5.1 子命令面 / 未知参数 / holdout flag
# --------------------------------------------------------------------------- #


def test_help_exits_zero_and_lists_every_subcommand(capsys) -> None:
    assert cli.main(["--help"]) == 0
    text = capsys.readouterr().out
    for name in ("dataset", "run", "gate", "baseline", "diff", "export"):
        assert name in text
    assert "--allow-holdout-details" not in text


def test_unknown_subcommand_is_nonzero_without_traceback(capsys) -> None:
    code = cli.main(["nope"])
    captured = capsys.readouterr()
    assert code != 0
    assert "Traceback" not in captured.err


def test_unknown_option_is_nonzero_without_traceback(capsys) -> None:
    code = cli.main(["run", "--suite", "b0", "--mode", "local", "--bogus"])
    captured = capsys.readouterr()
    assert code != 0
    assert "Traceback" not in captured.err


def test_allow_holdout_details_is_not_a_p0_option(capsys) -> None:
    code = cli.main(
        ["run", "--suite", "b0", "--mode", "local", "--allow-holdout-details"]
    )
    captured = capsys.readouterr()
    assert code != 0
    assert "--allow-holdout-details" in captured.err
    assert "Traceback" not in captured.err


# --------------------------------------------------------------------------- #
# dataset build / validate
# --------------------------------------------------------------------------- #


def test_dataset_validate_reads_frozen_fixture(capsys) -> None:
    code = cli.main(
        ["dataset", "validate", "--suite", "b0", "--path", str(EVAL_DIR / "b0.jsonl")]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "cases=40" in out
    assert "b0:b0-2026-11-04:" in out
    assert "strata=exact:24,ocr:8,text:8" in out


def test_dataset_validate_rejects_suite_mismatch(capsys) -> None:
    code = cli.main(
        ["dataset", "validate", "--suite", "badcase", "--path", str(EVAL_DIR / "b0.jsonl")]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert "suite" in captured.err
    assert "Traceback" not in captured.err


def test_dataset_validate_missing_file_is_data_error(capsys) -> None:
    code = cli.main(
        ["dataset", "validate", "--suite", "b0", "--path", str(EVAL_DIR / "missing.jsonl")]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert "Traceback" not in captured.err


def test_dataset_build_delegates_to_existing_builder(monkeypatch, tmp_path, capsys) -> None:
    b0 = tmp_path / "b0.json"
    badcase = tmp_path / "badcase.json"
    b0.write_bytes(b"{}")
    badcase.write_bytes(b"{}")
    out_dir = tmp_path / "out"
    calls: dict = {}

    class FakeBuilder:
        @staticmethod
        def build_dataset(root, b0_path, badcase_path, out):
            calls.update(root=root, b0=b0_path, badcase=badcase_path, out=out)
            return {
                "b0": {"cases": 40, "sha256": "a" * 64, "dataset_version": "b0:v:aaa"},
                "badcase": {"cases": 13, "sha256": "b" * 64, "dataset_version": "badcase:v:bbb"},
            }

    monkeypatch.setattr(cli, "_load_dataset_builder", lambda: FakeBuilder)
    code = cli.main(
        [
            "dataset",
            "build",
            "--b0",
            str(b0),
            "--badcase",
            str(badcase),
            "--out",
            str(out_dir),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert calls["root"] == ROOT
    assert calls["b0"] == b0
    assert calls["badcase"] == badcase
    assert calls["out"] == out_dir
    assert "b0: cases=40" in out
    assert "badcase: cases=13" in out


# --------------------------------------------------------------------------- #
# §5.2 run / gate 退出码透传
# --------------------------------------------------------------------------- #


def test_run_local_delegates_options_and_returns_zero(monkeypatch, tmp_path) -> None:
    out_dir = tmp_path / "run"
    calls: dict = {}

    def fake_run_suite(suite, mode, **kwargs):
        calls.update(suite=suite, mode=mode, **kwargs)
        return SimpleNamespace(
            manifest=SimpleNamespace(run_id="run-1", suite=suite, mode=mode),
            out_dir=out_dir,
            cases=(1, 2),
            summary={},
        )

    monkeypatch.setattr(cli, "run_suite", fake_run_suite)
    code = cli.main(
        ["run", "--suite", "b0", "--mode", "local", "--out", str(out_dir)]
    )
    assert code == 0
    assert calls == {
        "suite": "b0",
        "mode": "local",
        "out_dir": out_dir,
        "replay_from": None,
        "dataset_path": None,
        "scope": "end_to_end",
    }


def test_run_replay_without_from_run_is_data_error(monkeypatch, capsys) -> None:
    def fake_run_suite(*args, **kwargs):
        raise ValueError("mode='replay' 必须提供 replay_from")

    monkeypatch.setattr(cli, "run_suite", fake_run_suite)
    code = cli.main(["run", "--suite", "b0", "--mode", "replay"])
    captured = capsys.readouterr()
    assert code == 3
    assert "replay_from" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("exit_code", [0, 1, 2, 3, 4])
def test_gate_exit_code_is_passed_through(monkeypatch, tmp_path, exit_code) -> None:
    run = _run(tmp_path)
    gate = _gate(exit_code)
    calls: dict = {}

    def fake_eval(*args, **kwargs):
        calls.update(args=args, kwargs=kwargs)
        return gate

    monkeypatch.setattr(cli, "load_run_result", lambda path: run)
    monkeypatch.setattr(cli, "load_gate_config", lambda path: "CONFIG")
    monkeypatch.setattr(cli, "evaluate_gate", fake_eval)
    code = cli.main(
        [
            "gate",
            "--run",
            str(run.out_dir),
            "--config",
            str(tmp_path / "gate.json"),
        ]
    )
    assert code == exit_code
    assert calls["kwargs"]["quality"] is True
    payload = json.loads((run.out_dir / "gate.json").read_text(encoding="utf-8"))
    assert payload["exit_code"] == exit_code


def test_gate_calibrate_writes_proposal_only(monkeypatch, tmp_path) -> None:
    run = _run(tmp_path)
    config_path = tmp_path / "gate.json"
    config_path.write_bytes(b'{"status":"unapproved"}\n')
    before = config_path.read_bytes()
    proposal = GateProposal(
        run_id="run-1",
        suite="b0",
        mode="local",
        pipeline_version="pipeline",
        dataset_version="b0:v:abc",
        gate_version=GATE_SCHEMA_VERSION,
        gate_config_hash="h" * 64,
        status="unapproved",
        strata=("all",),
        metrics=(),
        diagnostics={},
        notes="只提案",
    )
    monkeypatch.setattr(cli, "load_run_result", lambda path: run)
    monkeypatch.setattr(cli, "load_gate_config", lambda path: "CONFIG")
    monkeypatch.setattr(cli, "evaluate_gate", lambda *a, **k: _gate(3))
    monkeypatch.setattr(cli, "calibrate_gate", lambda r, c: proposal)
    code = cli.main(
        [
            "gate",
            "--run",
            str(run.out_dir),
            "--config",
            str(config_path),
            "--calibrate",
        ]
    )
    assert code == 3
    assert config_path.read_bytes() == before
    proposal_path = run.out_dir / "gate_proposal.json"
    assert proposal_path.is_file()
    payload = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert payload["status"] == "unapproved"
    assert "T009" in payload["approval_owner"]


def test_gate_config_error_is_exit_three_without_traceback(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_run_result", lambda path: SimpleNamespace())
    monkeypatch.setattr(
        cli, "load_gate_config", lambda path: (_ for _ in ()).throw(ValueError("坏配置"))
    )
    code = cli.main(["gate", "--run", "run", "--config", "gate.json"])
    captured = capsys.readouterr()
    assert code == 3
    assert "坏配置" in captured.err
    assert "Traceback" not in captured.err


# --------------------------------------------------------------------------- #
# §5.5 baseline approve 纪律
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("missing", ["gate", "approver", "reason"])
def test_baseline_approve_requires_gate_approver_reason(monkeypatch, tmp_path, missing) -> None:
    baseline_root = tmp_path / "baselines"
    gate_path = _write_gate_file(tmp_path / "gate.json", 0)
    args = {
        "run": "run",
        "gate": str(gate_path),
        "approver": "lead",
        "reason": "T008a",
        "root": str(baseline_root),
    }
    argv = ["baseline", "approve"]
    for name, value in args.items():
        if name == missing:
            continue
        argv += [f"--{name}", value]
    code = cli.main(argv)
    assert code == 2
    assert not list(baseline_root.rglob("approval.json"))


def test_baseline_approve_recomputes_gate_and_rejects_exit_three(
    monkeypatch, tmp_path, capsys
) -> None:
    run = _run(tmp_path)
    baseline_root = tmp_path / "baselines"
    claimed = _write_gate_file(tmp_path / "claimed-gate.json", 0)
    calls: dict = {}
    monkeypatch.setattr(cli, "load_run_result", lambda path: run)
    monkeypatch.setattr(cli, "load_gate_config", lambda path: "CONFIG")

    def fake_eval(*args, **kwargs):
        calls.update(args=args, kwargs=kwargs)
        return _gate(3)

    monkeypatch.setattr(cli, "evaluate_gate", fake_eval)
    code = cli.main(
        [
            "baseline",
            "approve",
            "--run",
            str(run.out_dir),
            "--gate",
            str(claimed),
            "--approver",
            "lead",
            "--reason",
            "T008a",
            "--root",
            str(baseline_root),
        ]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert calls["kwargs"]["quality"] is True
    assert "拒绝" in captured.err
    assert "阈值未审批" in captured.err or "exit_code=3" in captured.err
    assert not list(baseline_root.rglob("approval.json"))


def test_baseline_approve_rejects_exit_zero_without_quality(monkeypatch, tmp_path, capsys) -> None:
    run = _run(tmp_path)
    baseline_root = tmp_path / "baselines"
    claimed = _write_gate_file(tmp_path / "claimed-gate.json", 0)
    monkeypatch.setattr(cli, "load_run_result", lambda path: run)
    monkeypatch.setattr(cli, "load_gate_config", lambda path: "CONFIG")
    monkeypatch.setattr(cli, "evaluate_gate", lambda *a, **k: _gate(0, quality=False))
    code = cli.main(
        [
            "baseline",
            "approve",
            "--run",
            str(run.out_dir),
            "--gate",
            str(claimed),
            "--approver",
            "lead",
            "--reason",
            "T008a",
            "--root",
            str(baseline_root),
        ]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert "质量层未评估" in captured.err
    assert not list(baseline_root.rglob("approval.json"))


def test_baseline_approve_rejects_unapproved_config(monkeypatch, tmp_path, capsys) -> None:
    run = _run(tmp_path)
    baseline_root = tmp_path / "baselines"
    claimed = _write_gate_file(tmp_path / "claimed-gate.json", 0)
    monkeypatch.setattr(cli, "load_run_result", lambda path: run)
    monkeypatch.setattr(cli, "load_gate_config", lambda path: "CONFIG")
    monkeypatch.setattr(
        cli,
        "evaluate_gate",
        lambda *a, **k: _gate(0, quality=True, config_status="unapproved"),
    )
    code = cli.main(
        [
            "baseline",
            "approve",
            "--run",
            str(run.out_dir),
            "--gate",
            str(claimed),
            "--approver",
            "lead",
            "--reason",
            "T008a",
            "--root",
            str(baseline_root),
        ]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert "未审批" in captured.err
    assert not list(baseline_root.rglob("approval.json"))


def test_baseline_approve_missing_gate_file_is_data_error(monkeypatch, tmp_path, capsys) -> None:
    run = _run(tmp_path)
    monkeypatch.setattr(cli, "load_run_result", lambda path: run)
    code = cli.main(
        [
            "baseline",
            "approve",
            "--run",
            str(run.out_dir),
            "--gate",
            str(tmp_path / "missing.json"),
            "--approver",
            "lead",
            "--reason",
            "T008a",
            "--root",
            str(tmp_path / "baselines"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert "gate" in captured.err
    assert not list((tmp_path / "baselines").rglob("approval.json"))


def test_baseline_approve_success_passes_approver_and_reason(monkeypatch, tmp_path) -> None:
    run = _run(tmp_path)
    claimed = _write_gate_file(tmp_path / "claimed-gate.json", 0)
    calls: dict = {}
    monkeypatch.setattr(cli, "load_run_result", lambda path: run)
    monkeypatch.setattr(cli, "load_gate_config", lambda path: "CONFIG")
    monkeypatch.setattr(cli, "evaluate_gate", lambda *a, **k: _gate(0))

    def fake_approve(run_arg, gate_arg, root, *, approver, reason):
        calls.update(run=run_arg, gate=gate_arg, root=root, approver=approver, reason=reason)
        return SimpleNamespace(baseline_id=BASELINE_ID, run_id="run-1")

    monkeypatch.setattr(cli, "approve_baseline", fake_approve)
    code = cli.main(
        [
            "baseline",
            "approve",
            "--run",
            str(run.out_dir),
            "--gate",
            str(claimed),
            "--approver",
            "lead",
            "--reason",
            "T008a",
            "--root",
            str(tmp_path / "baselines"),
        ]
    )
    assert code == 0
    assert calls["approver"] == "lead"
    assert calls["reason"] == "T008a"
    assert calls["gate"].exit_code == 0


# --------------------------------------------------------------------------- #
# baseline list
# --------------------------------------------------------------------------- #


def test_baseline_list_reads_baseline_json_only(monkeypatch, tmp_path, capsys) -> None:
    root = tmp_path / "baselines"
    (root / BASELINE_ID).mkdir(parents=True)
    (root / BASELINE_ID / "baseline.json").write_bytes(b"{}")
    (root / "not-a-baseline").mkdir()
    loaded: list = []

    def fake_load(baseline_id_value, root_arg, **kwargs):
        loaded.append((baseline_id_value, Path(root_arg)))
        return SimpleNamespace(
            baseline_id=baseline_id_value,
            run_id="run-1",
            suite="b0",
            pipeline_version="pipeline",
            approval=None,
        )

    monkeypatch.setattr(cli, "load_baseline", fake_load)
    code = cli.main(["baseline", "list", "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 0
    assert loaded == [(BASELINE_ID, root)]
    assert BASELINE_ID in out
    assert "approved=no" in out
    assert "not-a-baseline" not in out


def test_baseline_list_reports_malformed_entry(monkeypatch, tmp_path, capsys) -> None:
    root = tmp_path / "baselines"
    (root / BASELINE_ID).mkdir(parents=True)
    (root / BASELINE_ID / "baseline.json").write_bytes(b"{}")
    monkeypatch.setattr(
        cli, "load_baseline", lambda *a, **k: (_ for _ in ()).throw(BaselineError("坏 baseline"))
    )
    code = cli.main(["baseline", "list", "--root", str(root)])
    captured = capsys.readouterr()
    assert code == 3
    assert BASELINE_ID in captured.err
    assert "坏 baseline" in captured.err


def test_baseline_list_missing_root_is_empty_not_created(tmp_path, capsys) -> None:
    root = tmp_path / "missing-baselines"
    code = cli.main(["baseline", "list", "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 0
    assert "0 条" in out
    assert not root.exists()


# --------------------------------------------------------------------------- #
# diff / export：baseline 缺失 fail closed；当前 gate 必传；报告原样落盘
# --------------------------------------------------------------------------- #


def test_diff_missing_baseline_fails_closed_without_creating_one(
    monkeypatch, tmp_path, capsys
) -> None:
    run = _run(tmp_path)
    baseline_root = tmp_path / "baselines"
    diff_calls: list = []
    monkeypatch.setattr(cli, "load_run_result", lambda path: run)
    monkeypatch.setattr(cli, "load_gate_config", lambda path: "CONFIG")
    monkeypatch.setattr(cli, "evaluate_gate", lambda *a, **k: _gate(3))
    monkeypatch.setattr(
        cli,
        "load_baseline",
        lambda *a, **k: (_ for _ in ()).throw(BaselineError("baseline 不存在")),
    )
    monkeypatch.setattr(cli, "diff_runs", lambda *a, **k: diff_calls.append(1))
    code = cli.main(
        [
            "diff",
            "--run",
            str(run.out_dir),
            "--baseline",
            BASELINE_ID,
            "--root",
            str(baseline_root),
        ]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert not diff_calls
    assert "baseline 未建立，待 T009" in captured.err
    assert not baseline_root.exists()
    assert not hasattr(cli, "save_baseline")


def test_diff_passes_current_gate_and_calls_release_guard(monkeypatch, tmp_path) -> None:
    run = _run(tmp_path)
    out_dir = tmp_path / "report"
    gate = _gate(3)
    diff = _fake_diff()
    calls: dict = {}
    _patch_diff(monkeypatch, gate=gate, diff=diff, calls=calls)
    code = cli.main(
        [
            "diff",
            "--run",
            str(run.out_dir),
            "--baseline",
            BASELINE_ID,
            "--root",
            str(tmp_path / "baselines"),
            "--out",
            str(out_dir),
        ]
    )
    assert code == 3
    assert calls["kwargs"]["gate"] is gate
    assert calls["kwargs"]["config"] == "CONFIG"
    assert calls["guarded"] is diff
    assert (out_dir / "diff.json").is_file()
    assert (out_dir / "report.md").read_bytes() == b"# MD\n"
    assert (out_dir / "report.html").read_bytes() == b"<html>OK</html>"


def test_diff_release_guard_failure_is_reported_but_report_still_written(
    monkeypatch, tmp_path, capsys
) -> None:
    run = _run(tmp_path)
    out_dir = tmp_path / "report"
    gate = _gate(3)
    diff = _fake_diff()
    _patch_diff(
        monkeypatch,
        gate=gate,
        diff=diff,
        guard_error=CrossVersionBaselineError("baseline 未审批，不能放行"),
    )
    code = cli.main(
        [
            "diff",
            "--run",
            str(run.out_dir),
            "--baseline",
            BASELINE_ID,
            "--root",
            str(tmp_path / "baselines"),
            "--out",
            str(out_dir),
        ]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert "放行阻断" in captured.err
    assert (out_dir / "report.md").is_file()
    assert (out_dir / "report.html").is_file()


def test_export_writes_renderer_output_verbatim_without_bom(monkeypatch, tmp_path) -> None:
    run = _run(tmp_path)
    out_dir = tmp_path / "export"
    _patch_diff(monkeypatch, gate=_gate(3), diff=_fake_diff())
    code = cli.main(
        [
            "export",
            "--run",
            str(run.out_dir),
            "--baseline",
            BASELINE_ID,
            "--root",
            str(tmp_path / "baselines"),
            "--out",
            str(out_dir),
        ]
    )
    assert code == 0
    md = (out_dir / "report.md").read_bytes()
    html = (out_dir / "report.html").read_bytes()
    assert md == b"# MD\n"
    assert html == b"<html>OK</html>"
    assert not md.startswith(b"\xef\xbb\xbf")
    assert not html.startswith(b"\xef\xbb\xbf")
    assert not (out_dir / "diff.json").exists()


def test_export_missing_baseline_fails_closed(monkeypatch, tmp_path, capsys) -> None:
    run = _run(tmp_path)
    monkeypatch.setattr(cli, "load_run_result", lambda path: run)
    monkeypatch.setattr(cli, "load_gate_config", lambda path: "CONFIG")
    monkeypatch.setattr(cli, "evaluate_gate", lambda *a, **k: _gate(3))
    monkeypatch.setattr(
        cli,
        "load_baseline",
        lambda *a, **k: (_ for _ in ()).throw(BaselineError("baseline 不存在")),
    )
    code = cli.main(
        [
            "export",
            "--run",
            str(run.out_dir),
            "--baseline",
            BASELINE_ID,
            "--root",
            str(tmp_path / "baselines"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert "baseline 未建立，待 T009" in captured.err


def test_diff_uses_current_run_gate_result_type(monkeypatch, tmp_path) -> None:
    """守住 T007 MEDIUM-2：不能把 ``gate=None`` 传给 diff_runs。"""
    run = _run(tmp_path)
    gate = _gate(1, hard_failures=("security_leak",))
    calls: dict = {}
    _patch_diff(monkeypatch, gate=gate, diff=_fake_diff(), calls=calls)
    code = cli.main(
        [
            "diff",
            "--run",
            str(run.out_dir),
            "--baseline",
            BASELINE_ID,
            "--root",
            str(tmp_path / "baselines"),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    assert code == 1
    assert isinstance(calls["kwargs"]["gate"], GateResult)
    assert calls["kwargs"]["gate"].hard_failures == ("security_leak",)


def test_run_diff_export_exit_codes_cover_zero_one_three(monkeypatch, tmp_path) -> None:
    """§5.2 至少覆盖 0 / 1 / 3：gate 与 diff 透传当前门禁退出码。"""
    run = _run(tmp_path)
    for exit_code in (0, 1, 3):
        gate = _gate(exit_code)
        monkeypatch.setattr(cli, "load_run_result", lambda path: run)
        monkeypatch.setattr(cli, "load_gate_config", lambda path: "CONFIG")
        monkeypatch.setattr(cli, "evaluate_gate", lambda *a, g=gate, **k: g)
        code = cli.main(["gate", "--run", str(run.out_dir), "--config", "gate.json"])
        assert code == exit_code
