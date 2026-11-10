"""T008a：P0 评测 CLI（设计 §8.4 / §8.5；计划 Task 7 Step 3）。

只做薄包装，不复制评测逻辑：

- ``dataset build`` 复用既有 ``tools/build_eval_dataset.py``（惰性导入，不复制转换规则）；
- ``run`` 直接调 ``run_suite``，P0 只允许 ``local`` / ``replay``；
- ``gate`` 现场 ``evaluate_gate(..., quality=True)`` 并把结果写 ``gate.json``；
  ``--calibrate`` 只写 ``gate_proposal.json``，绝不改写 gate 配置；
- ``baseline approve`` 必须现场重算门禁（``--gate`` 文件只做审计，不作为审批依据），
  拒绝时返回该门禁退出码且不写 ``approval.json``；
- ``baseline archive / verify / restore`` 只移植既有证据链：归档 ``baseline.json`` /
  ``approval.json`` / run 三件套 / ``gate.json`` 并写 ``archive_manifest.json``，
  restore 只重写 ``baseline.json.run_dir``，不改 identity / approval / artifact 摘要；
  holdout 相关 run、已存在目标目录、缺文件或哈希不符一律拒绝（E 工作流，fail closed）；
- ``diff`` 必须把当前 run 的 ``GateResult`` 传给 ``diff_runs`` 并调用
  ``require_release_baseline``（T007 MEDIUM-2），baseline 缺失时 fail closed；
- ``export`` 只写 ``render_markdown`` / ``render_html`` 的返回值（UTF-8 无 BOM）。

P1 T108（holdout 防污染）：

- ``run --suite holdout`` 默认只出聚合；``--allow-holdout-details`` 才写逐题 +
  ``holdout_audit.json``，且在 CI/门禁环境（``CI`` / ``GITHUB_ACTIONS`` / ``MKTKB_CI``）
  硬失败（非零退出）；
- 答案只从 ``--holdout-labels`` / ``MKTKB_HOLDOUT_LABELS`` 指向的本地文件读取；
- ``dataset export-holdout-questions`` 把本地题目逐字节导出为仓库 fixture（校验 sha 与
  无答案字段）；``dataset validate --suite holdout`` 只校验仓库导出（无答案）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .baseline import (
    BaselineApprovalError,
    BaselineComparabilityError,
    BaselineError,
    CrossVersionBaselineError,
    approve_baseline,
    archive_baseline,
    baseline_id,
    load_baseline,
    restore_baseline,
    verify_archive,
)
from .dataset import (
    HOLDOUT_QUESTIONS_SHA256,
    HOLDOUT_SUITE,
    dataset_version,
    export_holdout_questions,
    load_cases,
    load_holdout_questions,
)
from .gate import (
    DEFAULT_GATE_CONFIG_PATH,
    GateConfig,
    GateResult,
    calibrate_gate,
    evaluate_gate,
    load_gate_config,
    load_run_result,
    write_gate_proposal,
)
from .report import (
    COMPARISON_ANALYSIS,
    COMPARISON_CROSS_VERSION,
    COMPARISON_RELEASE,
    diff_runs,
    render_html,
    render_markdown,
    require_release_baseline,
)
from .runner import HOLDOUT_LABELS_ENV, run_suite

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_BASELINE_ROOT = PROJECT_ROOT / "var" / "eval" / "baselines"
EXIT_DATA = 3
EXIT_USAGE = 2
SUITES = ("b0", "badcase", "regression", HOLDOUT_SUITE)
MODES = ("local", "replay")


class CliError(RuntimeError):
    """CLI 可预期的失败：打印一行错误、返回指定退出码，不抛栈。"""

    def __init__(self, message: str, exit_code: int = EXIT_DATA) -> None:
        super().__init__(str(message))
        self.exit_code = int(exit_code)


# --------------------------------------------------------------------------- #
# 通用 IO（报告与 JSON 一律 UTF-8 无 BOM）
# --------------------------------------------------------------------------- #


def _write_text(path: Path, text: str) -> Path:
    """原样写字符串：不追加换行、不做行尾转换、无 BOM。"""
    if not isinstance(text, str):
        raise TypeError(f"报告内容必须是字符串，收到 {type(text).__name__}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    text = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return _write_text(path, text)


def _read_json(path: Path) -> Any:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8"))


def _resolve_config(value: str | None) -> GateConfig:
    return load_gate_config(Path(value) if value else DEFAULT_GATE_CONFIG_PATH)


# --------------------------------------------------------------------------- #
# dataset build / validate
# --------------------------------------------------------------------------- #


def _load_dataset_builder() -> Any:
    """惰性导入既有数据机构建器，避免复制 T004a 的转换规则。"""
    tools_dir = PROJECT_ROOT / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import build_eval_dataset  # noqa: PLC0415 - 只在 dataset build 时需要

    return build_eval_dataset


def _cmd_dataset_build(args: argparse.Namespace) -> int:
    b0_path = Path(args.b0).resolve()
    badcase_path = Path(args.badcase).resolve()
    out_dir = Path(args.out).resolve()
    for path, label in ((b0_path, "B0"), (badcase_path, "BadCase")):
        if not path.is_file():
            raise CliError(f"{label} 题目文件不存在: {path}")
    builder = _load_dataset_builder()
    try:
        stats = builder.build_dataset(PROJECT_ROOT, b0_path, badcase_path, out_dir)
    except Exception as exc:  # 构建器把 gold 不可定位等统一抛 BuildError
        raise CliError(f"dataset build 失败: {type(exc).__name__}: {exc}") from exc
    # ``dataset build`` 只构建 b0/badcase；regression 是手工维护的种子集。
    for suite in ("b0", "badcase"):
        payload = stats.get(suite, {}) if isinstance(stats, Mapping) else {}
        print(
            f"{suite}: cases={payload.get('cases')} sha256={payload.get('sha256')} "
            f"dataset_version={payload.get('dataset_version')}"
        )
    print(f"wrote {out_dir / 'b0.jsonl'} and {out_dir / 'badcase.jsonl'}")
    return 0


def _cmd_dataset_validate(args: argparse.Namespace) -> int:
    path = Path(args.path)
    raw = path.read_bytes()
    if args.suite == HOLDOUT_SUITE:
        # holdout 仓库导出只有题目（无答案）：只做题目契约校验，不加载 labels。
        questions = load_holdout_questions(path)
        strata_text = ",".join(
            f"{name}:{count}" for name, count in sorted(questions.strata.items())
        )
        print(
            f"suite={HOLDOUT_SUITE} cases={len(questions.rows)} "
            f"label_version={questions.label_version} "
            f"answers=none sha256={questions.sha256} strata={strata_text}"
        )
        return 0
    cases = load_cases(path)
    if not cases:
        raise CliError(f"数据集为空: {path}")
    suites = {case.suite for case in cases}
    if suites != {args.suite}:
        raise CliError(
            f"数据集 suite 不匹配：--suite={args.suite!r}，文件内={sorted(suites)!r}"
        )
    versions = {case.label_version for case in cases}
    if len(versions) != 1:
        raise CliError(f"数据集 label_version 不唯一: {sorted(versions)!r}")
    version = dataset_version(cases, next(iter(versions)))
    strata = Counter(case.stratum for case in cases)
    strata_text = ",".join(f"{name}:{count}" for name, count in sorted(strata.items()))
    print(
        f"suite={args.suite} cases={len(cases)} dataset_version={version} "
        f"sha256={hashlib.sha256(raw).hexdigest()} strata={strata_text}"
    )
    return 0


def _cmd_dataset_export_holdout(args: argparse.Namespace) -> int:
    expected = args.expected_sha256 or HOLDOUT_QUESTIONS_SHA256
    digest = export_holdout_questions(
        Path(args.from_path), Path(args.out), expected_sha256=expected
    )
    print(f"wrote {Path(args.out)} sha256={digest} answers=none")
    return 0


def _cmd_dataset(args: argparse.Namespace) -> int:
    if args.dataset_command == "build":
        return _cmd_dataset_build(args)
    if args.dataset_command == "export-holdout-questions":
        return _cmd_dataset_export_holdout(args)
    return _cmd_dataset_validate(args)


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #


def _cmd_run(args: argparse.Namespace) -> int:
    result = run_suite(
        args.suite,
        args.mode,
        out_dir=Path(args.out) if args.out else None,
        scope=args.scope,
        replay_from=Path(args.from_run) if args.from_run else None,
        dataset_path=Path(args.dataset) if args.dataset else None,
        holdout_labels=Path(args.holdout_labels) if args.holdout_labels else None,
        allow_holdout_details=bool(args.allow_holdout_details),
    )
    details = ""
    if result.manifest.suite == HOLDOUT_SUITE:
        details = f" details={str(result.manifest.holdout_details).lower()}"
    print(
        f"run_id={result.manifest.run_id} suite={result.manifest.suite} "
        f"mode={result.manifest.mode} cases={len(result.cases)} out={result.out_dir}{details}"
    )
    return 0


# --------------------------------------------------------------------------- #
# gate / calibrate
# --------------------------------------------------------------------------- #


def _quality_config_status(gate: GateResult) -> str:
    quality = gate.quality
    return "not_evaluated" if quality is None else str(quality.config_status)


def _cmd_gate(args: argparse.Namespace) -> int:
    run = load_run_result(Path(args.run))
    config = _resolve_config(args.config)
    gate = evaluate_gate(run, config=config, quality=True)
    gate_path = _write_json(Path(run.out_dir) / "gate.json", gate.to_dict())
    print(
        f"gate exit_code={gate.exit_code} run_id={gate.run_id} suite={gate.suite} "
        f"mode={gate.mode} scored={gate.scored_count}/{gate.min_sample} "
        f"hard_failures={list(gate.hard_failures)} quality={gate.quality_status} "
        f"config_status={_quality_config_status(gate)}"
    )
    print(f"wrote {gate_path}")
    if args.calibrate:
        proposal = calibrate_gate(run, config)
        proposal_path = write_gate_proposal(
            proposal, Path(run.out_dir) / "gate_proposal.json", overwrite=True
        )
        print(
            f"proposal={proposal_path} status={proposal.status} "
            "（T009 人工门审批前不生效，未改写 gate 配置）"
        )
    return gate.exit_code


# --------------------------------------------------------------------------- #
# baseline approve / list
# --------------------------------------------------------------------------- #


def _read_claimed_gate(path: Path) -> Mapping[str, Any]:
    """只校验 ``--gate`` 参数的格式；其 verdict 不参与审批判定。"""
    try:
        payload = _read_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CliError(f"--gate 不是合法 UTF-8 JSON {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CliError("--gate 必须是 JSON 对象")
    exit_code = payload.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise CliError("--gate.exit_code 必须是整数")
    return payload


def _cmd_baseline_approve(args: argparse.Namespace) -> int:
    run = load_run_result(Path(args.run))
    claimed_path = Path(args.gate)
    if not claimed_path.is_file():
        raise CliError(f"--gate 文件不存在: {claimed_path}")
    claimed = _read_claimed_gate(claimed_path)
    config = _resolve_config(args.config)
    gate = evaluate_gate(run, config=config, quality=True)
    print(
        f"现场重算 gate exit_code={gate.exit_code}（--gate 声明 "
        f"exit_code={claimed.get('exit_code')}；仅审计，不作为审批依据）"
    )
    try:
        baseline = approve_baseline(
            run, gate, Path(args.root), approver=args.approver, reason=args.reason
        )
    except BaselineApprovalError as exc:
        print(f"baseline approve 拒绝: {exc}", file=sys.stderr)
        return gate.exit_code if gate.exit_code != 0 else EXIT_DATA
    print(
        f"baseline approved baseline_id={baseline.baseline_id} run_id={baseline.run_id} "
        f"approver={args.approver}"
    )
    return 0


def _cmd_baseline_list(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if not root.is_dir():
        print(f"baseline 目录不存在（0 条）: {root}")
        return 0
    entries = sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "baseline.json").is_file()
    )
    if not entries:
        print(f"baseline 0 条（{root}）")
        return 0
    code = 0
    for directory in entries:
        try:
            baseline = load_baseline(directory.name, root)
        except BaselineError as exc:
            print(f"invalid baseline {directory.name}: {exc}", file=sys.stderr)
            code = EXIT_DATA
            continue
        approved = "yes" if baseline.approval is not None else "no"
        print(
            f"baseline_id={baseline.baseline_id} run_id={baseline.run_id} "
            f"suite={baseline.suite} pipeline_version={baseline.pipeline_version} "
            f"approved={approved}"
        )
    return code


def _cmd_baseline_archive(args: argparse.Namespace) -> int:
    record = archive_baseline(args.baseline, Path(args.root), Path(args.out))
    approved = "yes" if record.has_approval else "no"
    print(
        f"archive baseline_id={record.baseline_id} run_id={record.run_id} "
        f"suite={record.suite} files={len(record.files)} approved={approved}"
    )
    print(f"wrote {Path(args.out)}")
    return 0


def _cmd_baseline_verify(args: argparse.Namespace) -> int:
    record = verify_archive(Path(args.archive))
    approved = "yes" if record.has_approval else "no"
    print(
        f"archive ok baseline_id={record.baseline_id} run_id={record.run_id} "
        f"suite={record.suite} files={len(record.files)} approved={approved} "
        f"schema={record.schema_version}"
    )
    if record.source_run_dir:
        print(f"source run_dir={record.source_run_dir}")
    return 0


def _cmd_baseline_restore(args: argparse.Namespace) -> int:
    result = restore_baseline(
        Path(args.archive),
        Path(args.root),
        runs_root=Path(args.runs_root) if args.runs_root else None,
    )
    approved = "yes" if result.baseline.approval is not None else "no"
    print(
        f"restored baseline_id={result.baseline_id} run_id={result.baseline.run_id} "
        f"run_dir={result.run_dir} approved={approved} files={len(result.files)}"
    )
    print(f"wrote {result.baseline_dir} {result.run_dir}")
    return 0


def _cmd_baseline(args: argparse.Namespace) -> int:
    if args.baseline_command == "approve":
        return _cmd_baseline_approve(args)
    if args.baseline_command == "archive":
        return _cmd_baseline_archive(args)
    if args.baseline_command == "verify":
        return _cmd_baseline_verify(args)
    if args.baseline_command == "restore":
        return _cmd_baseline_restore(args)
    return _cmd_baseline_list(args)


# --------------------------------------------------------------------------- #
# diff / export
# --------------------------------------------------------------------------- #


def _load_diff_context(
    args: argparse.Namespace,
) -> tuple[Any, GateResult, str, Any]:
    """读 run + 现场门禁 + baseline + diff；baseline 缺失一律 fail closed。"""
    run = load_run_result(Path(args.run))
    config = _resolve_config(args.config)
    gate = evaluate_gate(run, config=config, quality=True)
    baseline_id_value = args.baseline or baseline_id(run.manifest)
    try:
        baseline = load_baseline(
            baseline_id_value,
            Path(args.root),
            expected=run.manifest,
            compare_with=args.compare_with,
        )
    except (CrossVersionBaselineError, BaselineComparabilityError) as exc:
        raise CliError(f"baseline 不可比（{baseline_id_value}）：{exc}") from exc
    except BaselineError as exc:
        raise CliError(
            f"baseline 未建立，待 T009（{baseline_id_value}）：{exc}"
        ) from exc
    diff = diff_runs(
        baseline,
        run,
        comparison=args.comparison,
        compare_with=args.compare_with,
        config=config,
        gate=gate,
    )
    return run, gate, baseline_id_value, diff


def _release_guard(diff: Any) -> str | None:
    """调用发布放行守卫；失败只记录原因，不吞掉报告生成。"""
    try:
        require_release_baseline(diff)
    except CrossVersionBaselineError as exc:
        return str(exc)
    return None


def _cmd_diff(args: argparse.Namespace) -> int:
    run, gate, baseline_id_value, diff = _load_diff_context(args)
    release_error = _release_guard(diff)
    out_dir = Path(args.out) if args.out else Path(run.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_path = _write_json(out_dir / "diff.json", diff.to_dict())
    report_md = _write_text(out_dir / "report.md", render_markdown(diff, gate, summary=run.summary))
    report_html = _write_text(
        out_dir / "report.html",
        render_html(summary=run.summary, diff=diff, gate=gate),
    )
    print(
        f"diff run_id={run.manifest.run_id} baseline_id={baseline_id_value} "
        f"comparison={diff.comparison} release_allowed={diff.release_allowed} "
        f"blocked={diff.release_blocked_reason} gate_exit={gate.exit_code}"
    )
    print(f"wrote {diff_path} {report_md} {report_html}")
    if release_error:
        print(f"放行阻断: {release_error}", file=sys.stderr)
    return gate.exit_code


def _cmd_export(args: argparse.Namespace) -> int:
    run, gate, baseline_id_value, diff = _load_diff_context(args)
    release_error = _release_guard(diff)
    out_dir = Path(args.out) if args.out else Path(run.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_md = _write_text(out_dir / "report.md", render_markdown(diff, gate, summary=run.summary))
    report_html = _write_text(
        out_dir / "report.html",
        render_html(summary=run.summary, diff=diff, gate=gate),
    )
    print(
        f"export run_id={run.manifest.run_id} baseline_id={baseline_id_value} "
        f"gate_exit={gate.exit_code} release_allowed={diff.release_allowed}"
    )
    print(f"wrote {report_md} {report_html}")
    if release_error:
        print(f"放行阻断: {release_error}", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #


def _add_run_selector(parser: argparse.ArgumentParser, *, with_comparison: bool) -> None:
    parser.add_argument("--run", required=True, help="当前 run 目录（run_manifest.json 所在）")
    parser.add_argument(
        "--baseline",
        default=None,
        help="baseline_id（12 位十六进制）；省略时按当前 run 身份推导",
    )
    parser.add_argument(
        "--root",
        default=str(DEFAULT_BASELINE_ROOT),
        help=f"baseline 根目录（默认 {DEFAULT_BASELINE_ROOT}）",
    )
    parser.add_argument("--config", default=None, help="gate 配置路径（默认 docs/evaluation/gate_v0_1.json）")
    parser.add_argument("--out", default=None, help="输出目录（默认写到 run 目录）")
    if with_comparison:
        parser.add_argument(
            "--comparison",
            choices=(COMPARISON_RELEASE, COMPARISON_ANALYSIS, COMPARISON_CROSS_VERSION),
            default=None,
            help="对比方式；跨版本必须显式 compare_with，且只分析不放行",
        )
        parser.add_argument(
            "--compare-with",
            default=None,
            help="跨 pipeline_version 分析时必须显式给出 baseline_id",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag_eval",
        description="P0 评测 CLI：dataset / run / gate / baseline / diff / export（零真实调用）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    dataset = sub.add_parser("dataset", help="构建或校验评测数据集")
    dataset_sub = dataset.add_subparsers(dest="dataset_command", required=True)
    build = dataset_sub.add_parser("build", help="从题目源构建 b0/badcase JSONL")
    build.add_argument("--b0", required=True, help="B0 题目 JSON")
    build.add_argument("--badcase", required=True, help="Bad Case 题目 JSON")
    build.add_argument("--out", required=True, help="输出目录")
    build.set_defaults(handler=_cmd_dataset)

    validate = dataset_sub.add_parser("validate", help="校验 JSONL 数据集与版本")
    validate.add_argument("--suite", required=True, choices=SUITES)
    validate.add_argument("--path", required=True, help="JSONL 路径")
    validate.set_defaults(handler=_cmd_dataset)

    export_holdout = dataset_sub.add_parser(
        "export-holdout-questions",
        help="把本地 holdout questions.jsonl 逐字节导出为仓库 fixture（无答案）",
    )
    export_holdout.add_argument(
        "--from",
        dest="from_path",
        required=True,
        help="本地 questions.jsonl 副本（不读 holdout 目录本身）",
    )
    export_holdout.add_argument(
        "--out",
        default=str(PROJECT_ROOT / "fixtures" / "evaluation" / "holdout-questions.jsonl"),
        help="仓库导出路径（默认 fixtures/evaluation/holdout-questions.jsonl）",
    )
    export_holdout.add_argument(
        "--expected-sha256",
        default=None,
        help=f"期望的源文件 sha256（默认冻结值 {HOLDOUT_QUESTIONS_SHA256[:12]}…）",
    )
    export_holdout.set_defaults(handler=_cmd_dataset)

    run = sub.add_parser("run", help="跑 local / replay suite")
    run.add_argument("--suite", required=True, choices=SUITES)
    run.add_argument("--mode", choices=MODES, default="local")
    run.add_argument("--out", default=None, help="输出目录（默认 var/eval/runs/<run_id>）")
    run.add_argument("--from-run", default=None, help="replay 的上一轮 local run 目录")
    run.add_argument("--dataset", default=None, help="覆盖默认 fixtures/evaluation/<suite>.jsonl")
    run.add_argument("--scope", default="end_to_end")
    run.add_argument(
        "--holdout-labels",
        default=None,
        help=f"holdout 本地 labels.jsonl 路径（也可用环境变量 {HOLDOUT_LABELS_ENV}）",
    )
    run.add_argument(
        "--allow-holdout-details",
        action="store_true",
        help="允许写 holdout 逐题详情 + holdout_audit.json（CI/门禁环境硬失败）",
    )
    run.set_defaults(handler=_cmd_run)

    gate = sub.add_parser("gate", help="评估硬门禁 + 质量层；--calibrate 只写提案")
    gate.add_argument("--run", required=True)
    gate.add_argument("--config", default=None)
    gate.add_argument("--calibrate", action="store_true", help="写 gate_proposal.json（不审批）")
    gate.set_defaults(handler=_cmd_gate)

    baseline = sub.add_parser(
        "baseline", help="baseline 审批 / 列表 / 归档 / 校验 / 恢复（移植不改 identity）"
    )
    baseline_sub = baseline.add_subparsers(dest="baseline_command", required=True)
    approve = baseline_sub.add_parser("approve", help="现场重算门禁后审批 baseline")
    approve.add_argument("--run", required=True)
    approve.add_argument("--gate", required=True, help="门禁 JSON（只审计，不参与审批判定）")
    approve.add_argument("--approver", required=True)
    approve.add_argument("--reason", required=True)
    approve.add_argument("--root", default=str(DEFAULT_BASELINE_ROOT))
    approve.add_argument("--config", default=None)
    approve.set_defaults(handler=_cmd_baseline)
    listing = baseline_sub.add_parser("list", help="列出 <root>/<baseline_id>/baseline.json")
    listing.add_argument("--root", default=str(DEFAULT_BASELINE_ROOT))
    listing.set_defaults(handler=_cmd_baseline)
    archive = baseline_sub.add_parser(
        "archive",
        help="把 baseline 证据链归档到 --out（fail closed；holdout 一律拒绝）",
    )
    archive.add_argument("--baseline", required=True, help="baseline_id（12 位十六进制）")
    archive.add_argument(
        "--root",
        default=str(DEFAULT_BASELINE_ROOT),
        help=f"源 baseline 根目录（默认 {DEFAULT_BASELINE_ROOT}）",
    )
    archive.add_argument("--out", required=True, help="新归档目录（必须不存在，不覆盖）")
    archive.set_defaults(handler=_cmd_baseline)
    verify = baseline_sub.add_parser(
        "verify", help="只读校验归档（文件 sha256 / 身份 / 审批关系）"
    )
    verify.add_argument("--archive", required=True, help="归档目录（含 archive_manifest.json）")
    verify.set_defaults(handler=_cmd_baseline)
    restore = baseline_sub.add_parser(
        "restore",
        help="把归档恢复成隔离根下的 baseline（只重写 run_dir，不覆盖已存在目录）",
    )
    restore.add_argument("--archive", required=True, help="归档目录（含 archive_manifest.json）")
    restore.add_argument(
        "--root", required=True, help="目标 baseline 根目录（新建，如 <tmp>/eval/baselines）"
    )
    restore.add_argument(
        "--runs-root",
        default=None,
        help="目标 run 根目录（默认 <root>/../runs）",
    )
    restore.set_defaults(handler=_cmd_baseline)

    diff = sub.add_parser("diff", help="baseline vs 当前 run 的 diff + 报告")
    _add_run_selector(diff, with_comparison=True)
    diff.set_defaults(handler=_cmd_diff)

    export = sub.add_parser("export", help="只导出 report.md / report.html（非门禁层）")
    _add_run_selector(export, with_comparison=True)
    export.set_defaults(handler=_cmd_export)
    return parser


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None) -> int:
    """解析并执行；argparse 错误返回 2，可预期失败返回对应退出码，不抛栈。"""
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:  # --help / argparse 参数错误
        return int(exc.code or 0)
    try:
        return int(args.handler(args))
    except CliError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.exit_code
    except BaselineError as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_DATA
    except (ValueError, OSError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_DATA
    except Exception as exc:  # CLI 边界：不把栈抛给用户
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_DATA


if __name__ == "__main__":  # pragma: no cover - 由 tools/rag_eval.py 调用
    raise SystemExit(main())
