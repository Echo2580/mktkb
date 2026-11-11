r"""P2-T207-FIX-H2SCORE-R1 附带证据：p2-score --holdout-cases 与 runner 卡的逐题口径差异（N6）。

用法（工作目录=仓库根）：
  .venv\Scripts\python.exe -B -X utf8 docs\reports\OBS-EVAL\P2\T207-FIX-H2SCORE-R1\evidence\verify\probe_p2score_cli.py

做法：复用 probe_independent 的自建合成封存与“23 对 7 错”产品观测，把同一批逐题行
（含 product.text/sources/evidence）写到系统 TEMP（仓外），按 runbook 的可选复核命令跑
真实 p2-score --visibility holdout --holdout-cases，再与 runner 卡读数对照。
零真实出站（纯离线评分，不走网络）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[7]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(HERE.parent))

import probe_independent as P  # noqa: E402  (自建合成封存/产品观测，独立于开发测试)
from mktkb.evaluation import p2_dataset as p2d  # noqa: E402
from mktkb.evaluation.p2_runner import holdout_document_codes  # noqa: E402
from mktkb.evaluation.product_adapter import case_questions  # noqa: E402


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="p2cli-"))
    print(f"repo={ROOT}")
    print(f"temp={base}")
    sealed = P.write_sealed(base)
    dataset = P.load_dataset(sealed)
    products = P.answering_products(dataset, all_correct=False)
    rows = []
    for case in dataset.cases:
        questions = case_questions(case)
        payload = products[questions[0]].as_dict(include_text=True)
        rows.append(
            {
                "schema_version": "p2-run-case/v0.1",
                "run_id": "p2run-cli-verify",
                "case_id": case.case_id,
                "suite": case.suite,
                "stratum": case.stratum,
                "visibility": "holdout",
                "conversation_id": "conv",
                "turns": [
                    {"turn": i, "item_id": f"{case.case_id}:turn{i}:answer", "status": "ok",
                     "error_code": None, "product": payload}
                    for i in range(1, len(questions) + 1)
                ],
                "status": "ok",
                "error_code": None,
                "planned_turns": len(questions),
                "turns_executed": len(questions),
            }
        )
    rows_path = base / "rows.jsonl"
    rows_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    codes_path = base / "codes.json"
    codes_path.write_text(
        json.dumps(holdout_document_codes(P.ingest_plan()), ensure_ascii=False), encoding="utf-8"
    )
    run_dir = base / "rundir"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": "p2run-cli-verify", "config_hash": "c" * 64, "execution": "dry_run"}),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps({"network": {"available": True, "outbound_attempts": 0}}), encoding="utf-8"
    )
    out_dir = base / "score"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend" / "src")
    env[p2d.HOLDOUT_ROOT_ENV] = str(sealed.root)
    env[p2d.HOLDOUT_KEY_FILE_ENV] = str(sealed.key_file)
    command = [
        sys.executable, "-B", "-X", "utf8", "-m", "mktkb.evaluation.cli", "p2-score",
        "--visibility", "holdout",
        "--holdout-manifest", str(sealed.manifest_path),
        "--run-dir", str(run_dir),
        "--holdout-cases", str(rows_path),
        "--document-codes", str(codes_path),
        "--out", str(out_dir),
    ]
    print("cmd: " + " ".join(command[1:]))
    proc = subprocess.run(
        command, cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    print(f"exit={proc.returncode}")
    print("stdout=" + (proc.stdout or "").strip())
    if proc.stderr:
        print("stderr=" + (proc.stderr or "").strip()[-600:])
    card_path = out_dir / "holdout_scorecard.json"
    if not card_path.is_file():
        print("no card written")
        return
    card = json.loads(card_path.read_text(encoding="utf-8"))
    print("p2-score card: " + json.dumps(
        {key: card[key] for key in ("total", "executed", "passed", "failed", "errors",
                                    "hard_failures", "threshold_met", "thresholds_approved",
                                    "release_ready", "execution_mode", "real_calls")},
        ensure_ascii=False, sort_keys=True))
    print(f"card key count={len(card)} keys={sorted(card)}")
    print("blocks=" + str([b["code"] for b in card["blocks"]]))

    print()
    print("对照：同一批逐题行经 runner 的 _holdout_scorecard（source_index=evidence 索引）")
    ledger = P.P2RunLedger(run_id="p2run-cli-verify", plan_id="p2-plan",
                           plan_sha256="a" * 64, execution="dry_run", production_ready=False)
    for row in rows:
        ledger.record_scoring_case(row)
    runner_card = P.runner._holdout_scorecard(
        ledger, dataset, ingest_plan=P.ingest_plan(), execution="dry_run", real_calls=0,
        binding={"config_hash": "c" * 64}, gate_config=None,
    )
    print("runner card: " + json.dumps(
        {key: runner_card[key] for key in ("total", "executed", "passed", "failed", "errors",
                                           "hard_failures", "threshold_met", "thresholds_approved",
                                           "release_ready", "execution_mode", "real_calls")},
        ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
