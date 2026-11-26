"""T-R1-104 探针（非 pytest）：``score_case`` **默认路径**签名，用于 HEAD vs 工作树 A/B。

只调用 ``score_case(case, gold, outcome, cross_explicit_space=True)``——不传
``allowed_number_keys``，也不传 102a 新增的 ``structural_number_keys``。同一脚本用
两套源码各跑一次（``PYTHONPATH=<HEAD 导出>/backend/src`` 与工作树），输出必须逐字相同：

- ``"87"`` 是自造业务数字（不在金句/金标/引用 locator/分页里）→ 默认路径必须 fail；
- ``第 7 行`` + locator ``row=7`` → 默认路径**不**认结构 token（P1 口径），必须 fail 且
  extra 含 ``"7"``——这正是 102a 声明「默认路径逐字不变」的可执行对照。

用法（仓根，两行各跑一次）::

    $env:PYTHONPATH=''; .venv\\Scripts\\python.exe -B <本文件>
    $env:PYTHONPATH=$env:TEMP+'\\r1104-head\\backend\\src'; .venv\\Scripts\\python.exe -B <本文件>
"""

from __future__ import annotations

import json
import sys

from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.gold import ResolvedGold
from mktkb.evaluation.scorers import EvalCitation, EvalOutcome, score_case

QUESTION = "列出甲店立牌的记录"
FIELDS_LOCATOR = {
    "sheet": "合成表",
    "row": 7,
    "header_row": 6,
    "cells": [
        {"column": "A", "display": "甲店", "header": "门店"},
        {"column": "B", "display": "甲区", "header": "位置"},
    ],
}


def _case() -> CaseSpec:
    return CaseSpec(
        case_id="R1104-SIG",
        suite="synthetic",
        split="train",
        stratum="exact",
        business_date="2026-10-28",
        question=QUESTION,
        expected_kind="answer",
        expected_values=("甲区",),
        reference_answer="甲店立牌的位置是甲区",
    )


def _outcome(text: str) -> EvalOutcome:
    citation = EvalCitation(
        doc_code="D01",
        unit_key="sheet:合成表:row:7",
        unit_ids=("U-sig-row7",),
        locator=dict(FIELDS_LOCATOR),
        text="",
        kind="active",
    )
    return EvalOutcome(kind="answer", text=text, citations=(citation,))


def _gold() -> ResolvedGold:
    return ResolvedGold(
        case_id="R1104-SIG",
        requires_ocr=False,
        skipped=False,
        sources=(),
        unit_ids=("U-sig-row7",),
        relevant_unit_ids=(),
    )


def _run(text: str) -> dict:
    result = score_case(_case(), _gold(), _outcome(text), cross_explicit_space=True)
    return {
        "status": result.status,
        "checks": [
            {"check_id": check.check_id, "status": check.status, "evidence": dict(check.evidence)}
            for check in result.checks
            if check.check_id in {"value_hit", "value_no_fabricated"}
        ],
    }


def main() -> int:
    payload = {
        "module": __import__("mktkb.evaluation.scorers", fromlist=["x"]).__file__,
        "fabricated_87": _run("甲区。另有 87 家分店正在装修。"),
        "locator_row_7_in_text": _run("甲区，见合成表第 7 行。"),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
