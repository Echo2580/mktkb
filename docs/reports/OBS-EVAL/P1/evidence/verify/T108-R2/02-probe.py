"""T108 R2 定向复验探针（F1 真实 holdout 可评分 / B2 out 目录防污染 / B3 from-run）。

约束：
- 真实 labels 只作为运行时输入；本脚本只打印计数/状态/结构，不打印任何题干、答案、
  case_id 原文。真实 run 产物落在 %TEMP%，扫描后删除。
- 合成夹具只用临时文件；不写 var/eval/runs。
- 零真实模型/embedding/rerank：holdout local 强制 offline（runner.py:580-585）。

运行（cwd=仓库根）：
  $env:PYTHONPATH="backend/src"; .venv\\Scripts\\python.exe -B <此文件>
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path

def _find_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "backend" / "src" / "mktkb").is_dir() and (
            candidate / "fixtures" / "evaluation"
        ).is_dir():
            return candidate
    raise SystemExit("repo root not found")


ROOT = _find_root(Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import cli as cli_mod  # noqa: E402
from mktkb.evaluation.dataset import (  # noqa: E402
    HOLDOUT_ANSWER_FIELDS,
    HOLDOUT_CASE_COUNT,
    HOLDOUT_LABELS_SHA256,
    HOLDOUT_QUESTIONS_PATH,
    HoldoutError,
    HoldoutPolicy,
    load_holdout_dataset,
)
from mktkb.evaluation.runner import run_suite  # noqa: E402

TEMP_ROOT = Path(tempfile.gettempdir()) / "T108-R2"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
REAL_LABELS = ROOT / "docs" / "evidence" / "LOCAL-R1-20261101" / "P1-HOLDOUT" / "labels.jsonl"
CORPUS = ROOT / "corpus" / "enterprise-20261101"
CI_VARS = ("CI", "GITHUB_ACTIONS", "MKTKB_CI")

SYNTH_LABEL = "holdout-synthetic-r2"
SYNTH_STRATA = {"paraphrase": 2, "negative": 1}
SYNTH_CASE_COUNT = 3
Q_MARKER = "R2合成题干-唯一标记"
A_MARKER = "R2合成答案-唯一标记"
CASE_IDS = ("V01", "V02", "V03")


def clean_ci_env() -> None:
    for name in CI_VARS:
        os.environ.pop(name, None)


def cli(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli_mod.main(args)
    return code, out.getvalue(), err.getvalue()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(directory: Path) -> dict[str, str]:
    if not directory.exists():
        return {}
    return {
        item.name: sha256(item)
        for item in sorted(directory.iterdir())
        if item.is_file()
    }


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def artifact_blob(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        if path.is_file():
            parts.append(path.name)
            parts.append(path.read_bytes().decode("utf-8", errors="ignore"))
    return "\n".join(parts)


def recurse_keys(obj, acc: set[str]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            acc.add(str(key))
            recurse_keys(value, acc)
    elif isinstance(obj, list):
        for value in obj:
            recurse_keys(value, acc)


def leak_counts(blob: str, questions: list[dict], labels: list[dict]) -> dict:
    q_texts = [str(row.get("question", "")) for row in questions]
    turns = [str(t) for row in questions for t in (row.get("turns") or [])]
    case_ids = [str(row.get("case_id", "")) for row in questions]
    answers = [str(row.get("reference_answer", "")) for row in labels]
    values = [str(v) for row in labels for v in (row.get("expected_values") or [])]
    return {
        "question_hits": sum(1 for t in q_texts if t and t in blob),
        "turn_hits": sum(1 for t in turns if t and t in blob),
        "case_id_hits": sum(1 for t in case_ids if t and t in blob),
        "reference_answer_hits": sum(1 for t in answers if t and t in blob),
        "expected_value_hits_total": sum(1 for t in values if t and t in blob),
        "expected_value_hits_len_ge4": sum(
            1 for t in values if len(t) >= 4 and t in blob
        ),
    }


def q_row(case_id: str, **overrides) -> dict:
    row = {
        "case_id": case_id,
        "suite": "holdout",
        "split": "holdout",
        "stratum": "paraphrase",
        "business_date": "2026-10-28",
        "question": "R2 合成题干",
        "turns": [],
        "expected_kind": "answer",
        "should_refuse": False,
        "requires_ocr": False,
        "labeler": "holdout-author",
        "label_version": SYNTH_LABEL,
        "notes": "T108 R2 合成夹具",
    }
    row.update(overrides)
    return row


def l_row(case_id: str, **overrides) -> dict:
    row = {
        "case_id": case_id,
        "expected_kind": "answer",
        "expected_values": [A_MARKER],
        "expected_sources": [{"doc_code": "E11", "unit_key": "sheet:物品位置:row:7"}],
        "relevant_units": [{"doc_code": "E11", "unit_key": "sheet:物品位置:row:7"}],
        "reference_answer": f"R2 合成答案：{A_MARKER}",
        "should_refuse": False,
        "refusal_reason": None,
        "forbidden_values": [],
        "forbidden_sources": [],
        "notes": "R2 合成出处",
    }
    row.update(overrides)
    return row


def synth_questions() -> list[dict]:
    return [
        q_row("V01", question=f"{Q_MARKER}：物品位置？"),
        q_row("V02", question="R2 另一个问题", turns=["R2 追问一", "R2 追问二"]),
        q_row(
            "V03",
            stratum="negative",
            question="R2 负样本合成题干",
            expected_kind="refusal",
            should_refuse=True,
        ),
    ]


def synth_labels(*, refusal_relevant: bool = False) -> list[dict]:
    relevant = (
        [{"doc_code": "E11", "unit_key": "sheet:物品位置:row:7"}]
        if refusal_relevant
        else []
    )
    return [
        l_row("V01"),
        l_row("V02"),
        l_row(
            "V03",
            expected_kind="refusal",
            expected_values=[],
            expected_sources=[],
            relevant_units=relevant,
            reference_answer="R2 合成拒答",
            should_refuse=True,
            refusal_reason="R2 合成拒答原因",
        ),
    ]


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    )
    return path


def synth_policy(**overrides) -> HoldoutPolicy:
    base = {
        "case_count": SYNTH_CASE_COUNT,
        "strata": dict(SYNTH_STRATA),
        "questions_sha256": None,
        "labels_sha256": None,
        "label_version": SYNTH_LABEL,
    }
    base.update(overrides)
    return HoldoutPolicy(**base)


def make_corpus(destination: Path) -> Path:
    destination.mkdir(parents=True)
    (destination / "excel").mkdir()
    source = CORPUS / "excel" / "E11_终端物料位置表_当前V2.xlsx"
    target = destination / "excel" / source.name
    shutil.copy2(source, target)
    manifest = {
        "business_base_date": "2026-10-28",
        "files": [
            {
                "code": "E11",
                "group": "excel",
                "path": f"excel/{source.name}",
                "kind": "xlsx",
                "sha256": sha256(target),
            }
        ],
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return destination


def synth_run(
    tmp: Path,
    name: str,
    *,
    out_dir: Path | None = None,
    labels_override: list[dict] | None = None,
    **kwargs,
):
    questions = write_jsonl(tmp / name / "questions.jsonl", synth_questions())
    labels = write_jsonl(
        tmp / name / "labels.jsonl",
        synth_labels() if labels_override is None else labels_override,
    )
    target = out_dir if out_dir is not None else tmp / name / "run"
    result = run_suite(
        "holdout",
        "local",
        corpus_dir=make_corpus(tmp / name / "corpus"),
        dataset_path=questions,
        out_dir=target,
        holdout_labels=labels,
        holdout_policy=synth_policy(),
        **kwargs,
    )
    return result, questions, labels


def print_json(label: str, payload) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def main() -> int:
    clean_ci_env()
    os.environ.pop("MKTKB_HOLDOUT_LABELS", None)
    print("R2 tmp_root:", TEMP_ROOT)
    print("R2 real_labels_exists:", REAL_LABELS.is_file(), "size:", REAL_LABELS.stat().st_size)

    questions_fixture = read_jsonl(HOLDOUT_QUESTIONS_PATH)
    real_labels_rows = read_jsonl(REAL_LABELS)

    # ------------------------------------------------------------------ #
    # F1-a. 真实 holdout 默认聚合 run
    # ------------------------------------------------------------------ #
    started = time.time()
    real_agg = TEMP_ROOT / f"real-agg-{uuid.uuid4().hex[:10]}"
    code, out, err = cli(
        [
            "run",
            "--suite",
            "holdout",
            "--mode",
            "local",
            "--holdout-labels",
            str(REAL_LABELS),
            "--out",
            str(real_agg),
        ]
    )
    summary = read_json(real_agg / "summary.json") if (real_agg / "summary.json").exists() else {}
    manifest = (
        read_json(real_agg / "run_manifest.json")
        if (real_agg / "run_manifest.json").exists()
        else {}
    )
    files_agg = sorted(item.name for item in real_agg.iterdir()) if real_agg.exists() else []
    blob_agg = artifact_blob([real_agg / name for name in files_agg])
    print_json(
        "F1a agg",
        {
            "exit": code,
            "elapsed_s": round(time.time() - started, 1),
            "files": files_agg,
            "case_count": manifest.get("case_count"),
            "details": manifest.get("holdout_details"),
            "status_counts": summary.get("status_counts"),
            "error_count": summary.get("error_count"),
            "scored_count": summary.get("scored_count"),
            "denominator": (summary.get("metrics_scope") or {}).get("cases_in_denominator"),
            "excluded_errors": (summary.get("metrics_scope") or {}).get("excluded_error_count"),
            "refusal_recall": (summary.get("metrics") or {}).get("refusal_recall"),
            "refusal_precision": (summary.get("metrics") or {}).get("refusal_precision"),
            "false_refusal_rate": (summary.get("metrics") or {}).get("false_refusal_rate"),
            "Recall@10": (summary.get("metrics") or {}).get("Recall@10"),
            "holdout": {
                key: (summary.get("holdout") or {}).get(key)
                for key in (
                    "aggregate_only",
                    "details_written",
                    "traces_persisted",
                    "metadata_mismatch_count",
                    "label_version",
                    "strata",
                )
            },
            "stderr_head": err.strip().splitlines()[-1][:200] if err.strip() else "",
            "leak": leak_counts(blob_agg, questions_fixture, real_labels_rows),
        },
    )
    if code != 0:
        print("F1a FAILED stdout_tail:", out.strip()[-300:])
    # gate on aggregate
    gate_code, gate_out, gate_err = cli(["gate", "--run", str(real_agg)])
    gate_path = real_agg / "gate.json"
    gate = read_json(gate_path) if gate_path.exists() else {}
    print_json(
        "F1a gate",
        {
            "exit": gate_code,
            "hard": gate.get("hard_failures"),
            "unknowns": sorted(item.get("check_id") for item in gate.get("unknowns") or []),
            "traceback": "Traceback" in gate_err,
        },
    )
    agg_gate_blob = artifact_blob([gate_path])
    print_json(
        "F1a gate_leak",
        leak_counts(agg_gate_blob, questions_fixture, real_labels_rows),
    )
    shutil.rmtree(real_agg, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # F1-b. 真实 holdout details run
    # ------------------------------------------------------------------ #
    started = time.time()
    real_det = TEMP_ROOT / f"real-det-{uuid.uuid4().hex[:10]}"
    code_det, out_det, err_det = cli(
        [
            "run",
            "--suite",
            "holdout",
            "--mode",
            "local",
            "--allow-holdout-details",
            "--holdout-labels",
            str(REAL_LABELS),
            "--out",
            str(real_det),
        ]
    )
    det_summary = (
        read_json(real_det / "summary.json") if (real_det / "summary.json").exists() else {}
    )
    det_manifest = (
        read_json(real_det / "run_manifest.json")
        if (real_det / "run_manifest.json").exists()
        else {}
    )
    rows = (
        read_jsonl(real_det / "cases.jsonl") if (real_det / "cases.jsonl").exists() else []
    )
    files_det = sorted(item.name for item in real_det.iterdir()) if real_det.exists() else []
    former_shape = []
    for row in rows:
        gold = row.get("gold") or {}
        if (
            row.get("should_refuse") is True
            and not (gold.get("unit_ids") or [])
            and (gold.get("relevant_unit_ids") or [])
        ):
            former_shape.append(row)
    audit = read_json(real_det / "holdout_audit.json") if (real_det / "holdout_audit.json").exists() else {}
    audit_text = json.dumps(audit, ensure_ascii=False)
    audit_keys: set[str] = set()
    recurse_keys(audit, audit_keys)
    detail_meta_blob = artifact_blob(
        [real_det / "run_manifest.json", real_det / "summary.json", real_det / "holdout_audit.json"]
    )
    print_json(
        "F1b details",
        {
            "exit": code_det,
            "elapsed_s": round(time.time() - started, 1),
            "files": files_det,
            "rows": len(rows),
            "case_count": det_manifest.get("case_count"),
            "status_counts": det_summary.get("status_counts"),
            "error_count": det_summary.get("error_count"),
            "denominator": (det_summary.get("metrics_scope") or {}).get(
                "cases_in_denominator"
            ),
            "former_refusal_shape": {
                "count": len(former_shape),
                "status_counts": dict(
                    sorted(Counter(str(row.get("status")) for row in former_shape).items())
                ),
                "error_none": sum(1 for row in former_shape if row.get("error") is None),
                "refusal_check_not_skipped": sum(
                    1
                    for row in former_shape
                    if any(
                        check.get("check_id") == "refusal_expected"
                        and check.get("status") != "skipped"
                        for check in (row.get("checks") or [])
                    )
                ),
                "gold_unit_ids_empty": sum(
                    1 for row in former_shape if not (row.get("gold") or {}).get("unit_ids")
                ),
                "relevant_nonempty": sum(
                    1
                    for row in former_shape
                    if (row.get("gold") or {}).get("relevant_unit_ids")
                ),
            },
            "all_rows_unit_ids_empty_relevant_nonempty": sum(
                1
                for row in rows
                if not (row.get("gold") or {}).get("unit_ids")
                and (row.get("gold") or {}).get("relevant_unit_ids")
            ),
            "refusal_confusion": {
                "should_refuse": sum(1 for row in rows if row.get("should_refuse") is True),
                "refused": sum(1 for row in rows if row.get("refused") is True),
                "tp": sum(
                    1
                    for row in rows
                    if row.get("should_refuse") is True and row.get("refused") is True
                ),
                "fp": sum(
                    1
                    for row in rows
                    if row.get("should_refuse") is not True and row.get("refused") is True
                ),
                "fn": sum(
                    1
                    for row in rows
                    if row.get("should_refuse") is True and row.get("refused") is not True
                ),
                "tn": sum(
                    1
                    for row in rows
                    if row.get("should_refuse") is not True and row.get("refused") is not True
                ),
            },
            "refusal_metrics_match": {
                name: (
                    round(float((det_summary.get("metrics") or {}).get(name)), 6)
                    == round(float(value), 6)
                )
                for name, value in {
                    "refusal_recall": (
                        sum(
                            1
                            for row in rows
                            if row.get("should_refuse") is True
                            and row.get("refused") is True
                        )
                        / max(
                            1,
                            sum(1 for row in rows if row.get("should_refuse") is True),
                        )
                    ),
                    "refusal_precision": (
                        sum(
                            1
                            for row in rows
                            if row.get("should_refuse") is True
                            and row.get("refused") is True
                        )
                        / max(1, sum(1 for row in rows if row.get("refused") is True))
                    ),
                    "false_refusal_rate": (
                        sum(
                            1
                            for row in rows
                            if row.get("should_refuse") is not True
                            and row.get("refused") is True
                        )
                        / max(
                            1,
                            sum(1 for row in rows if row.get("should_refuse") is not True),
                        )
                    ),
                }.items()
            },
            "audit_keys": sorted(audit_keys),
            "audit_meta": {
                "operator_nonempty": bool(audit.get("operator")),
                "operator_is_not_unknown": audit.get("operator") != "unknown",
                "run_id_matches": audit.get("run_id") == det_manifest.get("run_id"),
                "created_matches": audit.get("created_at")
                == det_manifest.get("created_at"),
                "questions_sha256_head": str(
                    (audit.get("data") or {}).get("questions_sha256", "")
                )[:8],
                "labels_sha256_head": str(
                    (audit.get("data") or {}).get("labels_sha256", "")
                )[:8],
                "label_version": (audit.get("data") or {}).get("label_version"),
            },
            "audit_forbidden_keys": sorted(
                audit_keys
                & {
                    "question",
                    "turns",
                    "reference_answer",
                    "expected_values",
                    "expected_sources",
                    "relevant_units",
                    "case_id",
                }
            ),
            "audit_leak": leak_counts(audit_text, questions_fixture, real_labels_rows),
            "manifest_summary_leak": leak_counts(
                detail_meta_blob, questions_fixture, real_labels_rows
            ),
            "stderr_head": err_det.strip().splitlines()[-1][:200] if err_det.strip() else "",
        },
    )
    if code_det != 0:
        print("F1b FAILED stdout_tail:", out_det.strip()[-300:])
    # gate details dev + CI
    gate_dev_code, _, gate_dev_err = cli(["gate", "--run", str(real_det)])
    gate_dev = read_json(real_det / "gate.json") if (real_det / "gate.json").exists() else {}
    os.environ["GITHUB_ACTIONS"] = "1"
    try:
        gate_ci_code, _, gate_ci_err = cli(["gate", "--run", str(real_det)])
    finally:
        os.environ.pop("GITHUB_ACTIONS", None)
    gate_ci = read_json(real_det / "gate.json") if (real_det / "gate.json").exists() else {}
    print_json(
        "F1b gate",
        {
            "dev_exit": gate_dev_code,
            "dev_unknowns": sorted(
                item.get("check_id") for item in gate_dev.get("unknowns") or []
            ),
            "dev_hard": gate_dev.get("hard_failures"),
            "dev_traceback": "Traceback" in gate_dev_err,
            "ci_exit": gate_ci_code,
            "ci_unknowns": sorted(
                item.get("check_id") for item in gate_ci.get("unknowns") or []
            ),
            "ci_reason_names_var": any(
                "GITHUB_ACTIONS" in str(item.get("reason", ""))
                for item in gate_ci.get("unknowns") or []
            ),
            "ci_hard": gate_ci.get("hard_failures"),
            "ci_traceback": "Traceback" in gate_ci_err,
        },
    )
    shutil.rmtree(real_det, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # B2. out 目录防污染
    # ------------------------------------------------------------------ #
    with tempfile.TemporaryDirectory(prefix="t108r2-synth-") as td:
        tmp = Path(td)
        # 合成基线（空目录可跑 / 默认聚合泄漏）
        empty_dir = tmp / "empty-run"
        empty_dir.mkdir()
        result, qsyn, lsyn = synth_run(tmp, "base", out_dir=empty_dir)
        print_json(
            "B2 empty_dir_ok",
            {
                "files": sorted(item.name for item in result.out_dir.iterdir()),
                "status_counts": result.summary.get("status_counts"),
                "denominator": result.summary["metrics_scope"]["cases_in_denominator"],
                "holdout": result.summary.get("holdout"),
                "leak": leak_counts(
                    artifact_blob(
                        [result.out_dir / "run_manifest.json", result.out_dir / "summary.json"]
                    ),
                    synth_questions(),
                    synth_labels(),
                ),
            },
        )

        stale_cases = tmp / "stale-cases"
        stale_cases.mkdir()
        (stale_cases / "cases.jsonl").write_text('{"case_id":"OLD"}\n', encoding="utf-8")
        before = snapshot(stale_cases)
        code, _, err = cli(
            [
                "run",
                "--suite",
                "holdout",
                "--mode",
                "local",
                "--dataset",
                str(qsyn),
                "--holdout-labels",
                str(lsyn),
                "--out",
                str(stale_cases),
            ]
        )
        print_json(
            "B2 stale_cases_default",
            {
                "exit": code,
                "msg": "拒绝复用" in err,
                "traceback": "Traceback" in err,
                "unchanged": snapshot(stale_cases) == before,
                "files": sorted(snapshot(stale_cases)),
            },
        )

        stale_audit = tmp / "stale-audit"
        stale_audit.mkdir()
        (stale_audit / "holdout_audit.json").write_text("{}", encoding="utf-8")
        before = snapshot(stale_audit)
        code, _, err = cli(
            [
                "run",
                "--suite",
                "holdout",
                "--mode",
                "local",
                "--allow-holdout-details",
                "--dataset",
                str(qsyn),
                "--holdout-labels",
                str(lsyn),
                "--out",
                str(stale_audit),
            ]
        )
        print_json(
            "B2 stale_audit_details_cli",
            {
                "exit": code,
                "msg": "拒绝复用" in err,
                "traceback": "Traceback" in err,
                "unchanged": snapshot(stale_audit) == before,
                "files": sorted(snapshot(stale_audit)),
            },
        )
        try:
            synth_run(tmp, "b2-audit", out_dir=stale_audit, allow_holdout_details=True)
            runner_rejected = False
        except HoldoutError as exc:
            runner_rejected = "拒绝复用" in str(exc)
        print_json(
            "B2 stale_audit_details_runner",
            {"holdout_error": runner_rejected, "unchanged": snapshot(stale_audit) == before},
        )

        stale_trace = tmp / "stale-trace"
        stale_trace.mkdir()
        (stale_trace / "traces.sqlite3").write_bytes(b"SQLite format 3\x00old")
        before = snapshot(stale_trace)
        code, _, err = cli(
            [
                "run",
                "--suite",
                "holdout",
                "--mode",
                "local",
                "--dataset",
                str(qsyn),
                "--holdout-labels",
                str(lsyn),
                "--out",
                str(stale_trace),
            ]
        )
        print_json(
            "B2 stale_trace",
            {
                "exit": code,
                "msg": "拒绝复用" in err,
                "unchanged": snapshot(stale_trace) == before,
                "files": sorted(snapshot(stale_trace)),
            },
        )

        stale_other = tmp / "stale-other"
        stale_other.mkdir()
        (stale_other / "keep.txt").write_text("old", encoding="utf-8")
        before = snapshot(stale_other)
        code, _, err = cli(
            [
                "run",
                "--suite",
                "holdout",
                "--mode",
                "local",
                "--dataset",
                str(qsyn),
                "--holdout-labels",
                str(lsyn),
                "--out",
                str(stale_other),
            ]
        )
        print_json(
            "B2 stale_unrelated_file",
            {
                "exit": code,
                "msg": "非空 out 目录" in err,
                "unchanged": snapshot(stale_other) == before,
                "files": sorted(snapshot(stale_other)),
            },
        )

    # ------------------------------------------------------------------ #
    # B3. holdout 拒绝 --from-run
    # ------------------------------------------------------------------ #
    with tempfile.TemporaryDirectory(prefix="t108r2-b3-") as td:
        tmp = Path(td)
        questions = write_jsonl(tmp / "questions.jsonl", synth_questions())
        labels = write_jsonl(tmp / "labels.jsonl", synth_labels())
        out = tmp / "run"
        try:
            run_suite(
                "holdout",
                "local",
                corpus_dir=make_corpus(tmp / "corpus"),
                dataset_path=questions,
                holdout_labels=labels,
                holdout_policy=synth_policy(),
                replay_from=tmp / "previous-run",
                out_dir=out,
            )
            runner_rejected = False
        except HoldoutError:
            runner_rejected = False
        except ValueError as exc:
            runner_rejected = "replay_from" in str(exc)
        print_json(
            "B3 runner",
            {"value_error": runner_rejected, "out_created": out.exists()},
        )

        out_cli = tmp / "cli-run"
        code, _, err = cli(
            [
                "run",
                "--suite",
                "holdout",
                "--mode",
                "local",
                "--from-run",
                str(tmp / "previous-run"),
                "--out",
                str(out_cli),
            ]
        )
        print_json(
            "B3 cli",
            {
                "exit": code,
                "msg_replay_from": "replay_from" in err,
                "traceback": "Traceback" in err,
                "out_created": out_cli.exists(),
            },
        )
        code_mode, _, err_mode = cli(
            [
                "run",
                "--suite",
                "holdout",
                "--mode",
                "replay",
                "--from-run",
                str(tmp / "previous-run"),
                "--out",
                str(tmp / "cli-mode"),
            ]
        )
        print_json(
            "B3 replay_mode",
            {
                "exit": code_mode,
                "msg_local_only": "只允许 mode='local'" in err_mode,
                "out_created": (tmp / "cli-mode").exists(),
            },
        )

    # ------------------------------------------------------------------ #
    # 不变项抽查
    # ------------------------------------------------------------------ #
    with tempfile.TemporaryDirectory(prefix="t108r2-inv-") as td:
        tmp = Path(td)
        # CI 三变量 + details 硬失败（无 labels 也先被 CI 检查拦截）
        ci_results = {}
        for name in CI_VARS:
            out_ci = tmp / f"ci-{name}"
            os.environ[name] = "1"
            try:
                code, _, err = cli(
                    [
                        "run",
                        "--suite",
                        "holdout",
                        "--mode",
                        "local",
                        "--allow-holdout-details",
                        "--out",
                        str(out_ci),
                    ]
                )
            finally:
                os.environ.pop(name, None)
            ci_results[name] = {
                "exit": code,
                "msg": "CI/门禁环境禁止" in err,
                "names_var": name in err,
                "traceback": "Traceback" in err,
                "out_created": out_ci.exists(),
            }
        print_json("INV ci_details", ci_results)

        # CI 下聚合 run 仍可跑（合成夹具）
        os.environ["CI"] = "true"
        try:
            result, _, _ = synth_run(tmp, "ci-agg")
        finally:
            os.environ.pop("CI", None)
        print_json(
            "INV ci_aggregate",
            {
                "details": result.manifest.holdout_details,
                "files": sorted(item.name for item in result.out_dir.iterdir()),
            },
        )

        # fail-closed 抽查
        questions = write_jsonl(tmp / "q.jsonl", synth_questions())
        labels = write_jsonl(tmp / "l.jsonl", synth_labels(refusal_relevant=True))
        out_nolabels = tmp / "nolabels"
        code, _, err = cli(
            [
                "run",
                "--suite",
                "holdout",
                "--mode",
                "local",
                "--out",
                str(out_nolabels),
            ]
        )
        print_json(
            "INV missing_labels",
            {
                "exit": code,
                "msg": "缺少 labels" in err,
                "out_created": out_nolabels.exists(),
            },
        )

        tampered = tmp / "tampered-questions.jsonl"
        tampered.write_text((questions.read_text(encoding="utf-8") + "\n"), encoding="utf-8")
        out_tampered = tmp / "tampered-run"
        code, _, err = cli(
            [
                "run",
                "--suite",
                "holdout",
                "--mode",
                "local",
                "--dataset",
                str(tampered),
                "--holdout-labels",
                str(labels),
                "--out",
                str(out_tampered),
            ]
        )
        # 重复 --holdout-labels 不是重点；用合成 policy 无法走 CLI，此处只看 CLI 默认
        # 真实 policy 会先拒绝合成 sha（pinned questions sha 不符）。
        print_json(
            "INV cli_pinned_sha_or_usage",
            {
                "exit": code,
                "msg_sha": "sha256 不符" in err or "sha256" in err,
                "out_created": out_tampered.exists(),
            },
        )

        try:
            load_holdout_dataset(questions, labels, policy=synth_policy(case_count=30))
            row_count_rejected = False
        except HoldoutError as exc:
            row_count_rejected = "行数" in str(exc)
        try:
            missing_version = synth_questions()
            for row in missing_version:
                row.pop("label_version", None)
            q_nover = write_jsonl(tmp / "q_nover.jsonl", missing_version)
            load_holdout_dataset(q_nover, labels, policy=synth_policy())
            version_rejected = False
        except HoldoutError as exc:
            version_rejected = "label_version" in str(exc)
        print_json(
            "INV loader_fail_closed",
            {"row_count": row_count_rejected, "label_version": version_rejected},
        )

        # 负样例（expected_sources=[] + relevant_units 非空 + should_refuse）不再 error
        result, _, _ = synth_run(
            tmp, "refusal-fix", labels_override=synth_labels(refusal_relevant=True)
        )
        refusal_row = next(row for row in result.cases if row["case_id"] == "V03")
        print_json(
            "INV refusal_scored",
            {
                "status": refusal_row["status"],
                "error": refusal_row["error"],
                "denominator": result.summary["metrics_scope"]["cases_in_denominator"],
                "error_count": result.summary["error_count"],
                "refusal_recall": result.summary["metrics"]["refusal_recall"],
                "gold_unit_ids": refusal_row["gold"]["unit_ids"],
                "relevant_nonempty": bool(refusal_row["gold"]["relevant_unit_ids"]),
            },
        )

    # ------------------------------------------------------------------ #
    # 仓库导出 / labels 未入库
    # ------------------------------------------------------------------ #
    fixture_bytes = HOLDOUT_QUESTIONS_PATH.read_bytes()
    fixture_rows = read_jsonl(HOLDOUT_QUESTIONS_PATH)
    answer_fields = sorted(
        {
            key
            for row in fixture_rows
            for key in row
            if key in HOLDOUT_ANSWER_FIELDS
        }
    )
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    ).stdout.splitlines()
    history = subprocess.run(
        ["git", "log", "--all", "--name-only", "--pretty=format:"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    ).stdout.splitlines()
    print_json(
        "EXPORT fixture",
        {
            "lines": len(fixture_rows),
            "case_count_const": HOLDOUT_CASE_COUNT,
            "sha256": sha256(HOLDOUT_QUESTIONS_PATH),
            "keys": len(fixture_rows[0]) if fixture_rows else 0,
            "answer_fields": answer_fields,
            "labels_sha256": sha256(REAL_LABELS),
            "labels_sha_const": HOLDOUT_LABELS_SHA256,
            "labels_tracked": [path for path in tracked if path.endswith("labels.jsonl")],
            "labels_in_history": [
                path for path in history if path.endswith("labels.jsonl")
            ],
            "fixtures_labels_files": sorted(
                path.name
                for path in (ROOT / "fixtures" / "evaluation").glob("*labels*")
            ),
        },
    )

    # 实测真实 labels 与 questions 的重叠键/答案键只做计数
    print_json(
        "EXPORT labels_shape",
        {
            "rows": len(real_labels_rows),
            "keys": len(real_labels_rows[0]) if real_labels_rows else 0,
            "has_answer_fields": sorted(
                key for key in (real_labels_rows[0] if real_labels_rows else {}) if key in HOLDOUT_ANSWER_FIELDS
            ),
        },
    )
    print("R2 done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
