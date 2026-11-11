# -*- coding: utf-8 -*-
"""附加探针：逐题打分抛错（unscorable）时诊断是否仍自洽、是否保留异常码。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("D:/GPT项目/市场部AI知识库")
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_runner as runner  # noqa: E402
from mktkb.evaluation import p2_score_run  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_runner import P2RunLedger  # noqa: E402
from mktkb.evaluation.p2_scoring import P2ScoringError  # noqa: E402
from mktkb.evaluation.product_adapter import P2RunDataset  # noqa: E402

cases = tuple(
    CaseSpec(case_id="VUS-0" + str(i), suite="p2-holdout", split="holdout", stratum="paraphrase",
             business_date="2026-10-28", question="探针题干" + str(i), expected_kind="answer",
             expected_values=("甲值",), reference_answer="参考答复", label_version="vus")
    for i in (1, 2)
)
dataset = P2RunDataset(visibility="holdout", cases=cases,
                       identity={"dataset_version": "VUS", "label_version": "vus",
                                 "suite": "p2-holdout", "manifest_sha256": "b" * 64,
                                 "case_count": 2, "strata": {"paraphrase": 2}})
ledger = P2RunLedger(run_id="p2run-vus", plan_id="p2-vus", plan_sha256="a" * 64,
                     execution="dry_run", production_ready=False)
for case in cases:
    ledger.record_scoring_case({"case_id": case.case_id, "status": "ok", "error_code": None,
                                "planned_turns": 1, "turns": []})

orig = p2_score_run.score_public_case


def boom(*_args, **_kwargs):
    raise P2ScoringError("synthetic_scoring_boom", "probe")


p2_score_run.score_public_case = boom
try:
    card = runner._holdout_scorecard(ledger, dataset, ingest_plan=None, execution="dry_run",
                                     real_calls=0, binding={}, gate_config=None)
finally:
    p2_score_run.score_public_case = orig

print("card counts:", json.dumps({k: card[k] for k in ("total", "executed", "passed", "failed", "errors")}))
print("blocks:", [(b["code"], b.get("evidence")) for b in card["blocks"]])
print("diagnostics:", json.dumps(card["diagnostics"], ensure_ascii=False, indent=2, sort_keys=True))
print("sum(errors_by_code) =", sum(card["diagnostics"]["errors_by_code"].values()),
      "card.errors =", card["errors"])
runner._assert_holdout_scorecard_payload(card, dataset)
print("audit ok")
