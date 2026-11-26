"""r0 修复版落盘器：D3 逐题 hard_failed + §5 一致性门（另存；不改原件）。

与 ``fullverify-20261116/work/build_fullverify_artifacts.py`` 的差异：

1. **D3**：逐题 ``hard_failed`` 不再读顶层 ``axes.get("new_hard_failures", [])``
   （该字段不存在 → 旧产物全部 false）。改为
   ``r0_same_round.derive_hard_failed(per_case_axes, aggregate)``：
   从**经校验的逐题四轴 violation** 导出题目并集，并与 ``aggregate.hard_failures``、
   ``aggregate.case_count``、逐题 flag、每轴四态计数双向核对；缺字段/不一致即停止。
2. **D2 交叉核**：逐题质量取本轮 case-plan，但必须与重算明细的本轮 ``quality_status``
   逐个相等；不一致（历史 8/12 vs 7/12 那类）直接停止，不落“成功”产物。
3. **§5 一致性**：落盘前调用 ``r0_same_round.check_consistency``；任一不成立即终止。
4. **不覆盖旧产物**：固定写 ``quality-per-run-v2.json`` / ``final-summary-v2.json``，
   默认输出到 ``r0-repair-external-20261116/work/out/artifacts-v2/``，可用 ``--out-dir``
   改到仓外受控位置；已存在默认拒绝（``--overwrite`` 才覆盖本脚本输出）。

只读输入：新 ``recompute-v2-r0-repair.json``、私有 run 回执/case-plan（受控角色执行）、
账本/预算（只读 hash）。不读题面/答案/query 文本；输出只含固定码、计数、hash。

修复后一轮（r0fix-20261116）适配：CLI 化，默认行为不变
-----------------------------------------------------
- ``--work <根>``：旧 ``--runs-root`` 的同义参数（旧布局 ``<根>/r0``；也接受单 run 根）。
- ``--runs 0``：逗号分隔的 run_index 子集；默认仍是四个 run 全跑。
- ``--out-dir``/``--axes``/``--overwrite``：原样保留。
- 阈值口径：``MIN_PASS=24`` / ``HARD_MAX=0`` 是**四 run 全量（30 题）**的声明阈值；
  只跑子集时仍按同一条规则计算，但显式标注 ``threshold_scope`` 与 ``subset``，
  避免把 12 题子集读成通过全量闸。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pathlib
import re
import sys
from collections import Counter
from typing import Any, Mapping, Sequence

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
H2V3 = REPO / "docs/reports/OBS-EVAL/P2/H2V3"
WORK = pathlib.Path(r"D:\mktkb-p2-h2v3-fullverify-20261116")
DEFAULT_AXES = (
    H2V3
    / "r0-repair-external-20261116/work/out/recompute-v2-r0-repair.json"
)
DEFAULT_OUT_DIR = H2V3 / "r0-repair-external-20261116/work/out/artifacts-v2"
OLD_QUALITY = H2V3 / "fullverify-20261116/evidence/quality-per-run.json"
OLD_SUMMARY = H2V3 / "fullverify-20261116/run/final-summary.json"
LEDGER = REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
BUDGET = REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
OUT_DIRS = {0: "r0", 1: "r1", 2: "r2", 3: "r3"}
MIN_PASS = 24
HARD_MAX = 0
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
WORK_DIR = pathlib.Path(__file__).resolve().parent


def _load_module(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module_not_loadable:{path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


S = _load_module("r0_same_round_build", WORK_DIR / "r0_same_round.py")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return sha256_bytes(path.read_bytes())


def ledger_state() -> dict[str, Any]:
    raw = LEDGER.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    reserved = [row for row in rows if row.get("event") == "reserved"]
    results = [row for row in rows if row.get("event") == "result"]
    historical = sum(
        float(row.get("accounted_cny") or 0)
        for row in rows
        if row.get("event") == "historical_import"
    )
    project = historical + sum(float(row.get("conservative_charge_cny") or 0) for row in results)
    stage = sum(
        float(row.get("conservative_charge_cny") or 0)
        for row in results
        if row.get("stage") == "P2-LIVE"
    )
    return {
        "file_sha256": sha256_bytes(raw),
        "lines": raw.count(b"\n"),
        "reservation_count": len(reserved),
        "result_count": len(results),
        "paired": len(reserved) == len(results),
        "project_accounted_cny": round(project, 10),
        "stage_p2_live_cny": round(stage, 10),
        "budget_sha256": sha256_file(BUDGET),
    }


def _parse_runs(text: str) -> list[int]:
    """``--runs 0`` / ``--runs 0,2``；空串=全部（默认行为不变）。"""
    if text is None or not str(text).strip():
        return sorted(OUT_DIRS)
    picked: list[int] = []
    for item in str(text).split(","):
        token = item.strip()
        if not token:
            raise SystemExit("runs_argument_invalid")
        try:
            value = int(token)
        except ValueError:
            raise SystemExit("runs_argument_invalid") from None
        if value not in OUT_DIRS or value in picked:
            raise SystemExit("runs_argument_invalid")
        picked.append(value)
    if not picked:
        raise SystemExit("runs_argument_invalid")
    return picked


def _resolve_run_dir(runs_root: pathlib.Path, run_index: int) -> pathlib.Path:
    """旧布局 ``<根>/r0`` 优先；否则把根本身当单 run 根；都没有就拒绝。"""
    nested = runs_root / OUT_DIRS[run_index]
    if (nested / "out" / "controlled" / "case-plan.json").is_file():
        return nested
    if (runs_root / "out" / "controlled" / "case-plan.json").is_file():
        return runs_root
    raise SystemExit(f"run_root_not_found:{run_index}")


def _load_run_inputs(
    runs_root: pathlib.Path, run_index: int
) -> tuple[dict[str, Any], dict[str, Any], pathlib.Path]:
    run_root = _resolve_run_dir(runs_root, run_index)
    receipt_path = next((run_root / "seal").rglob("run-receipt.json"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    sidecar_path = next(run_root.glob("v3-entry-*.json"))
    case_plan_path = run_root / "out" / "controlled" / "case-plan.json"
    case_plan = json.loads(case_plan_path.read_text(encoding="utf-8"))
    return receipt, case_plan, sidecar_path


def _sha_run_file(runs_root: pathlib.Path, run_index: int, relative: str) -> str:
    return sha256_file(_resolve_run_dir(runs_root, run_index) / relative)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="r0 fullverify artifacts v2 (D3 + consistency)")
    parser.add_argument("--axes", default=str(DEFAULT_AXES), help="r0 修复版四轴重算 JSON")
    parser.add_argument(
        "--runs-root",
        "--work",
        dest="runs_root",
        default=str(WORK),
        help="run 私有输出根（旧布局 <根>/r0..；也接受本身就是单 run 根）",
    )
    parser.add_argument(
        "--runs",
        default="",
        help="逗号分隔的 run_index；默认四个 run（旧行为不变）",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="输出目录（不覆盖旧产物）")
    parser.add_argument(
        "--tag",
        default="",
        help="输出文件名后缀（例：compat-v03 → quality-per-run-v2-compat-v03.json）",
    )
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖本脚本已存在的 -v2 输出")
    args = parser.parse_args(argv)
    selected_runs = _parse_runs(args.runs)
    runs_root = pathlib.Path(args.runs_root)
    tag = str(args.tag or "")
    if tag and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", tag):
        raise SystemExit("tag_invalid")
    suffix = f"-{tag}" if tag else ""

    axes_path = pathlib.Path(args.axes)
    out_dir = pathlib.Path(args.out_dir)
    quality_path = out_dir / f"quality-per-run-v2{suffix}.json"
    summary_path = out_dir / f"final-summary-v2{suffix}.json"
    for target in (quality_path, summary_path):
        if target.resolve() in (OLD_QUALITY.resolve(), OLD_SUMMARY.resolve()):
            raise SystemExit("refuse_to_overwrite_protected_output")
        if target.exists() and not args.overwrite:
            raise SystemExit(f"output_already_exists:{target.name}")

    axes = json.loads(axes_path.read_text(encoding="utf-8"))
    if not isinstance(axes, Mapping) or not isinstance(axes.get("runs"), list):
        raise SystemExit("axes_payload_invalid")
    # §5：case 覆盖 / 逐题质量 / 硬失败 flag / 每轴四态 / unknown 一致性。
    S.check_consistency(axes)
    aggregate = axes["aggregate"]
    case_records = [row for run in axes["runs"] for row in run["cases"]]
    derived_hard = S.derive_hard_failed(case_records, aggregate)
    if derived_hard != set(aggregate["hard_failures"]):
        raise SystemExit("hard_failures_mismatch")

    runs_root = pathlib.Path(args.runs_root)
    receipts: dict[int, dict[str, Any]] = {}
    case_plans: dict[int, dict[str, Any]] = {}
    sidecars: dict[int, pathlib.Path] = {}
    axes_by_run = {int(run["run_index"]): run for run in axes["runs"]}
    for run_index in selected_runs:
        run = axes_by_run.get(run_index)
        if run is None:
            raise SystemExit(f"axes_run_missing:{run_index}")
        receipt, case_plan, sidecar = _load_run_inputs(runs_root, run_index)
        if str(receipt.get("run_id")) != str(run.get("run_id")):
            raise SystemExit(f"receipt_run_id_mismatch:{run_index}")
        if str(receipt.get("scenario_id")) != str(run.get("scenario_id")):
            raise SystemExit(f"receipt_scenario_mismatch:{run_index}")
        if str(receipt.get("business_date")) != str(run.get("business_date")):
            raise SystemExit(f"receipt_business_date_mismatch:{run_index}")
        if int(run.get("case_count")) != len(case_plan.get("cases") or []):
            raise SystemExit(f"case_count_mismatch:{run_index}")
        receipts[run_index] = receipt
        case_plans[run_index] = case_plan
        sidecars[run_index] = sidecar

    quality_payload = S.build_quality_payload(axes, case_plans)
    flag_ids = {row["case_id"] for row in quality_payload["cases"] if row["hard_failed"]}
    if flag_ids != derived_hard:
        raise SystemExit("quality_hard_failed_flag_mismatch")
    totals = quality_payload["totals"]
    if int(totals["hard_failures"]) != len(derived_hard):
        raise SystemExit("quality_hard_failure_count_mismatch")
    if int(totals["cases"]) != int(aggregate["case_count"]):
        raise SystemExit("quality_case_count_mismatch")

    out_dir.mkdir(parents=True, exist_ok=True)

    run_rows: list[dict[str, Any]] = []
    quality_by_run = {int(row["run_index"]): row for row in quality_payload["runs"]}
    for run_index in selected_runs:
        receipt = receipts[run_index]
        case_plan = case_plans[run_index]
        run = axes_by_run[run_index]
        quality = quality_by_run[run_index]
        cases = case_plan["cases"]
        turn_status = Counter(
            str(turn.get("status")) for case in cases for turn in case["turns"]
        )
        turn_errors = Counter(
            str(turn.get("error") or "none") for case in cases for turn in case["turns"]
        )
        run_rows.append(
            {
                "run_index": run_index,
                "scenario_id": receipt["scenario_id"],
                "business_date": receipt["business_date"],
                "run_id": receipt["run_id"],
                "status": receipt["status"],
                "ok": receipt["ok"],
                "error_code": receipt["error_code"],
                "stop_code": receipt["stop_code"],
                "case_count": len(cases),
                "turn_count": sum(turn_status.values()),
                "quality": {
                    status: int(quality[status])
                    for status in ("pass", "fail", "error", "not_executed")
                },
                "pass": int(quality["pass"]),
                "fail": int(quality["fail"]),
                "error": int(quality["error"]),
                "turn_executed": int(turn_status.get("executed", 0)),
                "turn_error_codes": {
                    key: value for key, value in turn_errors.items() if key != "none"
                },
                "requests_attempts_reserved": receipt["requests"]["attempts_reserved"],
                "real_sends": receipt["real_sends"],
                "settled_cny": receipt["requests"]["settled_cny"],
                "hard_failures": list(quality["hard_failures"]),
                "quality_source": quality_payload["hard_failed_source"],
                "axes_file_sha256": sha256_file(axes_path),
                "case_plan_sha256": _sha_run_file(
                    runs_root, run_index, "out/controlled/case-plan.json"
                ),
                "run_receipt_sha256": sha256_file(
                    next((_resolve_run_dir(runs_root, run_index) / "seal").rglob("run-receipt.json"))
                ),
                "v3_entry_sidecar_sha256": sha256_file(sidecars[run_index]),
            }
        )

    hard_failures = sorted(derived_hard)
    summary = {
        "schema_version": "p2-h2v3-final-summary/v0.2-r0-same-round",
        "role": (
            "fullverify-20261116 四 run 汇总（r0 修复版：同轮初判 + 校验后硬失败）"
            if sorted(selected_runs) == sorted(OUT_DIRS)
            else "fullverify 子集汇总（r0 修复版：同轮初判 + 校验后硬失败；run 子集见 subset）"
        ),
        "source_round": "current",
        "tag": tag,
        "subset": {
            "runs": list(selected_runs),
            "case_count": int(totals["cases"]),
            "is_full_suite": sorted(selected_runs) == sorted(OUT_DIRS),
        },
        "axes_file": {
            "path_role": axes_path.name,
            "sha256": sha256_file(axes_path),
            "schema_version": axes.get("schema_version"),
            "scope_contract_passed": (axes.get("scope_contract") or {}).get("passed"),
            "matcher_version": axes.get("matcher_version"),
            "compat": (axes.get("compat") or {}).get("mode"),
        },
        "hard_failure_source": "validated_per_case_axes.new_axes[*].state==violation",
        "runs": run_rows,
        "totals": totals,
        "requests": {
            "attempts_reserved_sum": sum(
                row["requests_attempts_reserved"] for row in run_rows
            ),
            "real_sends_sum": sum(int(row["real_sends"] or 0) for row in run_rows),
            "settled_cny_sum": round(
                sum(float(row["settled_cny"] or 0) for row in run_rows), 10
            ),
        },
        "axes_matcher_v2": aggregate["new_axes"],
        "axes_matcher_v2_initial": aggregate.get("initial_axes"),
        "axes_matcher_v2_previous_historical": aggregate.get("historical_axes"),
        "axes_matcher_v2_previous_historical_meaning": "compose historical card; comparison only",
        "axes_matcher_v2_version": axes.get("matcher_version"),
        "hard_failures": hard_failures,
        "hard_failure_count": len(hard_failures),
        "hard_failures_initial": sorted(aggregate.get("initial_hard_failures") or []),
        "hard_failures_previous_historical": sorted(
            aggregate.get("historical_hard_failures") or []
        ),
        "thresholds": {
            "min_pass": MIN_PASS,
            "hard_failures_max": HARD_MAX,
            "declared_scope": "full suite (4 runs / 30 cases)",
            "evaluated_scope": f"subset {list(selected_runs)} / {int(totals['cases'])} cases",
            "threshold_applicable_to_this_artifact": sorted(selected_runs) == sorted(OUT_DIRS),
        },
        "judgement": {
            "pass": int(totals["pass"]),
            "min_pass": MIN_PASS,
            "pass_threshold_met": int(totals["pass"]) >= MIN_PASS,
            "hard_failures": len(hard_failures),
            "hard_threshold_met": len(hard_failures) <= HARD_MAX,
            "t207_passed": int(totals["pass"]) >= MIN_PASS and len(hard_failures) <= HARD_MAX,
            "note": "t207 是按全量 30 题声明的闸；子集产物沿用同一规则计算，不代表全量通过",
        },
        "consistency": {
            "passed": True,
            "checks": [
                "axes_case_id_unique_exact_coverage",
                "axes_per_case_quality_sum_equals_run_quality",
                "axes_hard_failed_flags_equal_violation_union",
                "axes_axis_four_state_counts_equal_case_count",
                "axes_unknown_cases_not_hidden",
                "quality_cases_equal_case_plan_set",
                "quality_status_equals_axes_quality_status",
                "quality_hard_failed_flags_equal_derived_union",
                "receipt_run_scenario_business_date_match_axes",
            ],
        },
        "ledger": {"after": ledger_state()},
        "not_claimed": ["release", "T207_pass", "all_axes_real_complete"],
    }
    quality_path.write_text(
        json.dumps(quality_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "totals": totals,
                "hard_failures": hard_failures,
                "quality": str(quality_path),
                "summary": str(summary_path),
                "t207": summary["judgement"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
