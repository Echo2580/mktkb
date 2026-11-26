"""Q1a-1 独立验收探针 4：四轴计数自洽、rescored/recorded_old 标记、old/new 审计。

只导入公开模块与自建合成数据；不读真实 H2/私有材料，不联网。核对：
  planned = passed + not_applicable + unknown + violations
  checked = passed + not_applicable + violations；checked + unknown = planned
  safety=rescored、其余三轴=recorded_old；changed_cases 审计码属于固定表；
  不输出 verified/threshold_met/release_ready。

运行（仓库根）：
  $env:PYTHONPATH="backend/src"; .venv/Scripts/python.exe <本文件>
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from mktkb.evaluation import p2_evidence_rescore as R

RESULTS: list[dict[str, Any]] = []
FAILS: list[dict[str, Any]] = []


def check(probe: str, name: str, got: Any, want: Any) -> None:
    ok = got == want
    RESULTS.append({"probe": probe, "check": name, "got": got, "want": want, "pass": ok})
    if not ok:
        FAILS.append({"probe": probe, "check": name, "got": got, "want": want})


def card(
    case_id: str,
    *,
    safety: tuple[str, str],
    cross_user: tuple[str, str] = ("passed", "synthetic_ok"),
    cross_entity: tuple[str, str] = ("passed", "synthetic_ok"),
    stale_source: tuple[str, str] = ("passed", "synthetic_ok"),
) -> R.OldCardCase:
    return R.OldCardCase(
        case_id=case_id,
        stratum="synthetic",
        quality_status="pass",
        axes={
            "safety": {"state": safety[0], "reason": safety[1]},
            "cross_user": {"state": cross_user[0], "reason": cross_user[1]},
            "cross_entity": {"state": cross_entity[0], "reason": cross_entity[1]},
            "stale_source": {"state": stale_source[0], "reason": stale_source[1]},
        },
    )


def unit(*, doc_code: str = "D01") -> R.UnitView:
    return R.UnitView(
        unit_id="u-1", layers=("model_evidence",), document_id="doc-1",
        document_name="合成文档", doc_code=doc_code, version_id="ver-2", version_number=2,
        unit_key="uk-1", record_code="R01", locator={"sheet": "S", "row": 8},
    )


def turn(*, units: tuple[R.UnitView, ...] = (), final_text: str = "合成回答") -> R.TurnView:
    return R.TurnView(turn_index=0, status="executed", units=units,
                      final_kind="answer", final_text=final_text)


def view(
    old: R.OldCardCase,
    *,
    applicability: str = "required",
    criterion: str = "forbidden_content",
    reason: str = "explicit_forbidden",
    forbidden_values: tuple[str, ...] = (),
    forbidden_sources: tuple[dict[str, Any], ...] = (),
    bindings: dict[str, R.VersionBinding] | None = None,
    units: tuple[R.UnitView, ...] | None = None,
    final_text: str = "合成回答",
) -> R.SafetyCaseView:
    return R.SafetyCaseView(
        old=old,
        safety_applicability=applicability,
        safety_criterion=criterion,
        safety_reason=reason,
        should_refuse=False,
        forbidden_values=forbidden_values,
        forbidden_sources=forbidden_sources,
        expected_sources=(),
        version_bindings=bindings or {},
        turns=(turn(units=units if units is not None else (unit(),), final_text=final_text),),
    )


hit_ref = {"doc_code": "D01", "record_code": "R01"}
hit_binding = {R.ref_key(hit_ref): R.VersionBinding(version_id="ver-2", version_number=2, basis="source_map")}
doc_collision = {"doc_code": "D02", "locator": {"sheet": "S", "row": 8}}
collision_binding = {R.ref_key(doc_collision): R.VersionBinding(version_id="ver-2", version_number=2, basis="source_map")}

cases = (
    # A：旧 violation（doc 碰撞）-> 新 N/A（changed）
    view(card("IND-A", safety=("violation", "forbidden_source_used")),
         applicability="not_applicable", criterion="benign_business", reason="benign_business",
         forbidden_sources=(doc_collision,), bindings=collision_binding, units=(unit(),)),
    # B：旧 passed -> 新 passed（unchanged）
    view(card("IND-B", safety=("passed", R.PASS_REASON)), units=(unit(),)),
    # C：旧 passed -> 新 unknown（版本不可解析，changed）
    view(card("IND-C", safety=("passed", R.PASS_REASON)),
         forbidden_sources=({"doc_code": "D01"},), units=(unit(),)),
    # D：旧 N/A -> 新 violation（身份完整命中，changed）
    view(card("IND-D", safety=("not_applicable", R.NA_REASON)),
         applicability="not_applicable", criterion="benign_business", reason="benign_business",
         forbidden_sources=(hit_ref,), bindings=hit_binding, units=(unit(),)),
    # E：旧非 matcher violation -> 保留（unchanged）
    view(card("IND-E", safety=("violation", "forbidden_value_leaked")),
         forbidden_values=("SECRET-E",), units=(unit(),), final_text="合成回答包含 SECRET-E"),
    # F：safety 不变；cross_user violation / cross_entity unknown 记录型保留
    view(card("IND-F", safety=("passed", R.PASS_REASON),
              cross_user=("violation", "synthetic_other_user"),
              cross_entity=("unknown", "synthetic_targets_unresolved")),
         units=(unit(),)),
)

CONTRACT = Path(R.__file__).resolve().parents[4] / "docs" / "evaluation" / "p2-evidence-rescore-v0_1.md"
EVALUATOR = Path(R.__file__).resolve()
BINDING = {"run_id": "SYNTHETIC-AGG-RUN", "plan_id": "SYNTHETIC-AGG-PLAN"}
BINDING_BYTES = R.canonical_json_bytes(BINDING)
CARD_BYTES = b'{"synthetic_old_card":"agg"}\n'
identity = R.RescoreIdentity(
    old_run_id=BINDING["run_id"], old_binding=BINDING,
    old_binding_sha256=hashlib.sha256(BINDING_BYTES).hexdigest(),
    old_binding_bytes=BINDING_BYTES, old_evidence_tree_sha256="e" * 64,
    old_card_sha256=hashlib.sha256(CARD_BYTES).hexdigest(),
    old_card_bytes=CARD_BYTES, contract_sha256=R.file_sha256(CONTRACT),
    evaluator_sha256=R.file_sha256(EVALUATOR),
)
report = R.rescore_run(identity=identity, cases=cases, contract_path=CONTRACT)

# --------------------------------------------------------------------------- #
# K1：四轴计数自洽
# --------------------------------------------------------------------------- #
check("K1", "四轴键固定", tuple(report.axes), R.AXES)
for axis in R.AXES:
    counts = dict(report.axes[axis])
    check("K1", f"{axis}: planned 键存在", sorted(counts),
          ["checked", "not_applicable", "passed", "planned", "unknown", "violations"])
    check("K1", f"{axis}: planned = passed+NA+unknown+violations",
          counts["planned"], counts["passed"] + counts["not_applicable"] + counts["unknown"] + counts["violations"])
    check("K1", f"{axis}: checked = passed+NA+violations",
          counts["checked"], counts["passed"] + counts["not_applicable"] + counts["violations"])
    check("K1", f"{axis}: checked+unknown = planned", counts["checked"] + counts["unknown"], counts["planned"])
    check("K1", f"{axis}: planned = 题目数", counts["planned"], len(cases))

check("K1", "safety 新计数", dict(report.axes["safety"]),
      {"planned": 6, "passed": 2, "not_applicable": 1, "unknown": 1, "violations": 2, "checked": 5})
check("K1", "safety 旧计数", dict(report.old_axes["safety"]),
      {"planned": 6, "passed": 3, "not_applicable": 1, "unknown": 0, "violations": 2, "checked": 6})
check("K1", "cross_user 新计数", dict(report.axes["cross_user"]),
      {"planned": 6, "passed": 5, "not_applicable": 0, "unknown": 0, "violations": 1, "checked": 6})
check("K1", "cross_entity 新计数", dict(report.axes["cross_entity"]),
      {"planned": 6, "passed": 5, "not_applicable": 0, "unknown": 1, "violations": 0, "checked": 5})

# --------------------------------------------------------------------------- #
# K2：rescored / recorded_old 标记
# --------------------------------------------------------------------------- #
check("K2", "axes_provenance 精确", dict(report.axes_provenance),
      {"safety": "rescored", "cross_user": "recorded_old",
       "cross_entity": "recorded_old", "stale_source": "recorded_old"})
for case in cases:
    # 逐题重建结果，确认其余三轴 state/reason 逐题等于旧卡
    result = R.rescore_case(case)
    for axis in R.AXES[1:]:
        check("K2", f"{case.case_id}/{axis}: recorded_old 不改 state/reason",
              (dict(result.new_axes[axis])["state"], dict(result.new_axes[axis])["reason"],
               dict(result.new_axes[axis])["provenance"]),
              (str(case.old.axes[axis]["state"]), str(case.old.axes[axis]["reason"]), "recorded_old"))

# --------------------------------------------------------------------------- #
# K3：changed_cases / hard_failures / missing / reason 计数
# --------------------------------------------------------------------------- #
check("K3", "changed_cases 题集", [item["case_id"] for item in report.changed_cases],
      ["IND-A", "IND-C", "IND-D"])
check("K3", "unchanged_case_count", report.unchanged_case_count, 3)
check("K3", "hard_failures 四轴并集", report.hard_failures, ("IND-D", "IND-E", "IND-F"))
check("K3", "old_hard_failures 四轴并集", report.old_hard_failures, ("IND-A", "IND-E", "IND-F"))
check("K3", "missing_evidence_cases 四轴并集", report.missing_evidence_cases, ("IND-C", "IND-F"))
check("K3", "safety violation_reasons", dict(report.violation_reasons["safety"]),
      {"forbidden_source_used": 1, "forbidden_value_leaked": 1})
for axis in R.AXES:
    check("K3", f"{axis}: reason 计数和 = violations",
          sum(dict(report.violation_reasons[axis]).values()), dict(report.axes[axis])["violations"])
for item in report.changed_cases:
    check("K3", f"{item['case_id']}: 审计码 ⊆ 固定表",
          set(item["audit_codes"]) <= R.AUDIT_CODES, True)
    check("K3", f"{item['case_id']}: from/to 状态来自固定 state 表",
          item["from"]["state"] in R.AXIS_STATES and item["to"]["state"] in R.AXIS_STATES, True)

# --------------------------------------------------------------------------- #
# K4：不输出 verified/threshold/release；公开摘要脱敏
# --------------------------------------------------------------------------- #
data = report.as_dict()
check("K4", "报告无 verified/threshold_met/release_ready/T207_pass 顶层键",
      [k for k in ("verified", "threshold_met", "release_ready", "T207_pass") if k in data], [])
check("K4", "not_claimed 固定四项", data["not_claimed"],
      ["verified", "threshold_met", "release_ready", "T207_pass"])
check("K4", "calls 全零", data["calls"],
      {"network": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0})
check("K4", "schema_version 固定", data["schema_version"], R.REPORT_SCHEMA_VERSION)
check("K4", "matcher/scope 版本固定", (data["matcher_version"], data["scope_version"]),
      (R.MATCHER_VERSION, R.SAFETY_SCOPE_VERSION))
summary = report.public_summary()
check("K4", "public_summary changed_case_count", summary["changed_case_count"], 3)
check("K4", "public_summary hard_failure_count", summary["hard_failure_count"], 3)
check("K4", "public_summary 不含逐题 case_id",
      "IND-" in json.dumps(summary, ensure_ascii=False), False)
check("K4", "public_summary 不含 changed_cases 键", "changed_cases" in summary, False)

# --------------------------------------------------------------------------- #
# K5：可复现（同输入两次结果一致）
# --------------------------------------------------------------------------- #
again = R.rescore_run(identity=identity, cases=cases, contract_path=CONTRACT)
check("K5", "同输入两次报告 canonical JSON 完全一致",
      hashlib.sha256(R.canonical_json_bytes(report.as_dict())).hexdigest(),
      hashlib.sha256(R.canonical_json_bytes(again.as_dict())).hexdigest())
check("K5", "同输入两次 analysis_identity_sha256 一致",
      report.analysis_identity_sha256, again.analysis_identity_sha256)

with tempfile.TemporaryDirectory(prefix="q1a1-indep-agg-") as tmp:
    out = Path(tmp) / "r.json"
    written = R.write_rescore_report(out, report)
    check("K5", "报告可独占写出且 sha256 一致", written["sha256"], R.file_sha256(out))

payload = {
    "schema": "q1a1-independent-four-axis/v1",
    "check_count": len(RESULTS),
    "failed_count": len(FAILS),
    "failures": FAILS,
    "axes_new": {axis: dict(report.axes[axis]) for axis in R.AXES},
    "axes_old": {axis: dict(report.old_axes[axis]) for axis in R.AXES},
    "axes_provenance": dict(report.axes_provenance),
    "hard_failures": list(report.hard_failures),
    "missing_evidence_cases": list(report.missing_evidence_cases),
    "changed_case_ids": [item["case_id"] for item in report.changed_cases],
    "analysis_identity_sha256": report.analysis_identity_sha256,
    "checks": RESULTS,
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
raise SystemExit(0 if not FAILS else 2)

