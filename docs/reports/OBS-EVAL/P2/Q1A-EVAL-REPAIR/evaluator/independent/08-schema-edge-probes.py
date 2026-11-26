"""Q1a-1 独立验收探针 8：输入 schema 边界（缺字段时的 fail-open 风险记录）。

发现并记录（不作为 Q1a-1 FAIL，因契约 §3 已规定输入形状；Q1a-3 必须传冻结 CaseSpec）：
  - `safety_view_from_old_evidence` 对 `case.forbidden_values/forbidden_sources/
    expected_sources/should_refuse` 使用 getattr 默认值；若调用方漏传，按“空/False”处理，
    required 题可能被算成 passed（fail-open），Q1a-3 调用层必须显式 required 校验；
  - `audit["quality_status"]` 缺失时默认 "pass"（仅用于投影校验；折叠用旧卡
    `OldCardCase.quality_status`，故不单独构成 fail-open）；
  - `audit.turns=[]`、非法映射值、非法 VersionBinding 均固定拒绝（fail closed）。

运行（仓库根）：
  $env:PYTHONPATH="backend/src"; .venv/Scripts/python.exe <本文件>
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from mktkb.evaluation import p2_evidence_rescore as R

RESULTS: list[dict[str, Any]] = []
NOTES: list[dict[str, Any]] = []


def note(name: str, value: Any) -> None:
    NOTES.append({"check": name, "observed": value})


def old_card() -> R.OldCardCase:
    return R.OldCardCase(
        case_id="IND-SCHEMA-01",
        stratum="synthetic",
        quality_status="fail",
        axes={
            "safety": {"state": "not_applicable", "reason": R.NA_REASON},
            "cross_user": {"state": "passed", "reason": "synthetic_ok"},
            "cross_entity": {"state": "passed", "reason": "synthetic_ok"},
            "stale_source": {"state": "passed", "reason": "synthetic_ok"},
        },
    )


def audit() -> dict[str, Any]:
    return {
        "quality_status": "fail",
        "turns": [
            {
                "turn_index": 0,
                "status": "executed",
                "evidence": {
                    "completeness": {"status": "complete"},
                    "capture": {"events": [
                        {"seq": 1, "kind": "commit_observed",
                         "payload": {"kind": "answer", "text": "合成回答"}},
                    ]},
                    "db_projection": {"units": []},
                },
            }
        ],
    }


axis_required = {"applicability": "required", "criterion": "forbidden_content",
                 "reason": "explicit_forbidden"}
axis_na = {"applicability": "not_applicable", "criterion": "benign_business",
           "reason": "benign_business"}

def error_code(fn) -> str | None:
    try:
        fn()
    except R.RescoreError as exc:
        return exc.code
    return None


# --------------------------------------------------------------------------- #
# N1：缺 case.forbidden_sources / forbidden_values / expected_sources
# --------------------------------------------------------------------------- #
minimal_case = SimpleNamespace(case_id="IND-SCHEMA-01")
view = R.safety_view_from_old_evidence(
    case=minimal_case, safety_axis=axis_required, audit=audit(),
    old_card_case=old_card(), document_codes={},
)
note("缺 forbidden_sources/values -> 投影为空元组",
     (view.forbidden_sources, view.forbidden_values, view.expected_sources))
verdict, _, _ = R.rescore_safety(view)
note("required 且禁源列表被默认空 -> 新 verdict（fail-open 风险）",
     (verdict.state, verdict.reason))

# --------------------------------------------------------------------------- #
# N2：缺 audit quality_status -> 默认 pass
# --------------------------------------------------------------------------- #
no_quality = audit()
no_quality.pop("quality_status")
view2 = R.safety_view_from_old_evidence(
    case=SimpleNamespace(case_id="IND-SCHEMA-01", should_refuse=False,
                         forbidden_values=(), forbidden_sources=(), expected_sources=()),
    safety_axis=axis_na, audit=no_quality,
    old_card_case=old_card(), document_codes={},
)
note("缺 audit.quality_status -> 投影成功（折叠仍用旧卡 quality_status）",
     view2.old.quality_status)
verdict2, _, _ = R.rescore_safety(view2)
note("缺 audit.quality_status 时 N/A verdict", (verdict2.state, verdict2.reason))
bad_quality = audit()
bad_quality["quality_status"] = "bogus"
note("audit.quality_status 非法 -> 固定拒绝", error_code(lambda: R.safety_view_from_old_evidence(
    case=SimpleNamespace(case_id="IND-SCHEMA-01"),
    safety_axis=axis_na, audit=bad_quality,
    old_card_case=old_card(), document_codes={},
)))

# --------------------------------------------------------------------------- #
# N3：严格失败路径（缺 turns / 非法映射值 / 非法 version binding）
# --------------------------------------------------------------------------- #
note("audit.turns=[] -> 固定拒绝", error_code(lambda: R.safety_view_from_old_evidence(
    case=SimpleNamespace(case_id="IND-SCHEMA-01"),
    safety_axis=axis_na, audit={**audit(), "turns": []},
    old_card_case=old_card(), document_codes={},
)))
note("document_codes 非字符串值 -> 固定拒绝", error_code(lambda: R.safety_view_from_old_evidence(
    case=SimpleNamespace(case_id="IND-SCHEMA-01"),
    safety_axis=axis_na, audit=audit(),
    old_card_case=old_card(), document_codes={1: "D01"},
)))
note("UnitView 空 doc_code -> 固定拒绝", error_code(
    lambda: R.UnitView(unit_id="u", layers=("model_evidence",), doc_code="")))
note("VersionBinding(unresolved 携带 version_id) -> 固定拒绝", error_code(
    lambda: R.VersionBinding(basis="unresolved", version_id="ver-1")))
note("VersionBinding(非 unresolved 无版本值) -> 固定拒绝", error_code(
    lambda: R.VersionBinding(basis="source_map")))

print(json.dumps({
    "schema": "q1a1-independent-schema-edges/v1",
    "notes": NOTES,
    "disposition": "Q1a-3 调用层必须显式 required 校验 case 字段与 quality_status；"
                   "Q1a-1 契约 §3 已规定输入形状，本包不以合成缺字段作为验收通过依据。",
}, ensure_ascii=False, indent=2))
raise SystemExit(0)
