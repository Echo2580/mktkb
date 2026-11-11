
r"""T207-FIX-SCORE 验收复跑 1/2：默认参数（P1 口径）old(HEAD) vs new(worktree) 逐字节差分。

用法（cwd=仓库根）：
  git archive HEAD backend/src | tar -x -C <临时目录>
  set PYTHONPATH=<临时目录>\backend\src
  .venv\Scripts\python.exe -X utf8 -B <本文件> --out old.json
  set PYTHONPATH=%CD%\backend\src
  .venv\Scripts\python.exe -X utf8 -B <本文件> --out new.json

输入：60 条冻结夹具（b0/badcase/regression）× 4 文本变体 × 2 引用状态 = 480 条；
      R1/R2/R3 真实产物 55 条（52+2+1）。
判定：仅调用默认参数（不传 allowed_number_keys），两次 json.dumps 逐字节相等。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import mktkb
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.gold import ResolvedGold
from mktkb.evaluation.p2_scoring import _resolved_without_index, normalize_product_outcome
from mktkb.evaluation.scorers import EvalCitation, EvalOutcome, score_case

ROOT = Path(r"D:/GPT项目/市场部AI知识库")
FIXTURES = [ROOT / "fixtures/evaluation" / n for n in ("b0.jsonl", "badcase.jsonl", "regression.jsonl")]
RUNS = [ROOT / "docs/reports/OBS-EVAL/P2/T207" / n for n in (
    "p2-t207-r1-20261111-01", "p2-t207-r2-20261111-01", "p2-t207-r3-20261111-01")]
DOC_CODES = ROOT / "docs/reports/OBS-EVAL/P2/T207/cases/document-codes.json"

CITATION = EvalCitation(
    doc_code="D02", unit_key=None, unit_ids=("unit-1",),
    locator={"sheet": "店家信息", "row": 5, "header_row": 4, "column_index": 3,
             "document_name": "D02_合作店家信息.xlsx",
             "cells": [{"display": "010-00000001"}, {"display": "示例市示例路18号（模拟）"}]},
    text="", kind="active",
)


def gold(case: CaseSpec) -> ResolvedGold:
    return ResolvedGold(case_id=case.case_id, requires_ocr=bool(case.requires_ocr),
                        skipped=False, sources=(), unit_ids=(), relevant_unit_ids=())


def variants(case: CaseSpec) -> dict[str, str]:
    echo = case.reference_answer or "；".join(case.expected_values) or case.question
    return {"echo": echo, "echo_plus_99": echo + "。另有 99 件在库。",
            "echo_plus_citation_numbers": echo + "。电话 010-00000001，地址示例市示例路18号。",
            "refusal": "没有找到相关资料，无法回答。"}


def fixture_records() -> list[dict]:
    records = []
    for path in FIXTURES:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = CaseSpec.from_dict(json.loads(line))
            for name, text in variants(case).items():
                for cite_name, cites in (("cited", (CITATION,)), ("uncited", ())):
                    outcome = EvalOutcome(kind=str(case.expected_kind or "answer"), text=text,
                                          citations=cites, path="rag")
                    result = score_case(case, gold(case), outcome)
                    records.append({"id": f"{path.stem}:{case.case_id}:{name}:{cite_name}",
                                    "result": result.to_dict()})
    return records


def run_records() -> list[dict]:
    codes = json.loads(DOC_CODES.read_text(encoding="utf-8"))
    records = []
    for run in RUNS:
        cases = {c.case_id: c for c in (CaseSpec.from_dict(json.loads(line))
                 for line in (run / "dataset.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())}
        for line in (run / "cases.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            case = cases.get(row.get("case_id"))
            turns = row.get("turns") or ()
            if case is None or not turns or not isinstance(turns[-1].get("product"), dict):
                continue
            outcome = normalize_product_outcome(turns[-1], document_codes=codes)
            result = score_case(case, _resolved_without_index(case), outcome, cross_explicit_space=True)
            records.append({"id": f"{run.name}:{case.case_id}", "result": result.to_dict()})
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = {"module": mktkb.__file__, "fixture_records": fixture_records(),
               "run_records": run_records()}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"module": payload["module"],
                      "fixture_records": len(payload["fixture_records"]),
                      "run_records": len(payload["run_records"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
