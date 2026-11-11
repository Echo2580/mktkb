# -*- coding: utf-8 -*-
"""独立验收附加探针：诊断审计的边界（不是 PASS/FAIL 判据，用于写限制）。

1) 诊断子树内**键名**不套 forbidden 名单：{} 是否放行？
2) 未执行/不可达状态 skipped_ocr 会不会破坏 sum(errors_by_code)==errors（潜在口径缺口）。
3) 诊断对象本身不是 Mapping / 数组 → fail-closed。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("D:/GPT项目/市场部AI知识库")
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_runner as runner  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_runner import ERROR_HOLDOUT_SCORECARD_LEAK, P2RunError  # noqa: E402
from mktkb.evaluation.p2_scoring import P2HoldoutCaseScore  # noqa: E402
from mktkb.evaluation.product_adapter import P2RunDataset  # noqa: E402

Q = "探针题干探针"
case = CaseSpec(case_id="VPR-01", suite="p2-holdout", split="holdout", stratum="paraphrase",
                business_date="2026-10-28", question=Q, expected_kind="answer",
                expected_values=("甲值",), expected_sources=({"doc_code": "D01", "unit_key": "k"},),
                reference_answer="参考答复", label_version="vprobe")
dataset = P2RunDataset(visibility="holdout", cases=(case,),
                       identity={"dataset_version": "VPR", "label_version": "vprobe",
                                 "suite": "p2-holdout", "manifest_sha256": "b" * 64,
                                 "case_count": 1, "strata": {"paraphrase": 1}})


def audit(payload):
    try:
        runner._assert_holdout_scorecard_payload({"diagnostics": payload}, dataset)
        return "PASS(未拦)"
    except P2RunError as exc:
        return "BLOCKED " + str(exc.code)


print("== 1) 诊断内层键名 vs forbidden 名单 ==")
for name in ("question", "reference_answer", "answer", "case_id"):
    payload = {"kind_matrix": {"answer": {name: 1}}}
    print("  nested key", repr(name), "->", audit(payload))
print("  （对照）同名键在诊断**外**：",
      end="")
try:
    runner._assert_holdout_scorecard_payload({"blocks": [{"question": 1}], "diagnostics": None}, dataset)
    print("PASS(未拦)")
except P2RunError as exc:
    print("BLOCKED", exc.code)

print()
print("== 2) 非 Mapping / 数组形状 ==")
for bad in ([1, 2, 3], "err_kind", 7):
    print("  diagnostics =", repr(bad), "->", audit(bad))

print()
print("== 3) 潜在口径缺口：状态不在 {error, not_executed} 的 error 类题 ==")
marks = (
    P2HoldoutCaseScore(case_id="VPR-01", stratum="paraphrase", status="skipped_requires_ocr"),
    P2HoldoutCaseScore(case_id="VPR-02", stratum="paraphrase", status="error"),
)
diag = runner._holdout_diagnostics((case,), marks, runner._HoldoutScoring())
print("  status=skipped_requires_ocr 时 diagnostics.errors_by_code =", json.dumps(diag["errors_by_code"]))
print("  若卡按 total-passed-failed 计 errors=2 → 和=1 不相等（该状态在 H2 打分链上不可达：")
print("  score_public_case 把 OCR 跳过改判 error，见 p2_scoring.py:901-912）")
print()
print("== 4) 计数表键排序（产物可比对） ==")
diag2 = runner._holdout_diagnostics((case,), marks[:1], runner._HoldoutScoring())
print("  kind_matrix 键顺序 =", list(diag2["kind_matrix"]), " refusal 键 =", list(diag2["refusal_matrix"]))
