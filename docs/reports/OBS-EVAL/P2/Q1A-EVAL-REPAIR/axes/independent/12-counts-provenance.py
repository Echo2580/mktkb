#!/usr/bin/env python
"""探针 12：四轴计数自洽 / provenance 不冒充 / changed_cases / public_summary。

输出：12-counts-provenance.out.json
"""

from __future__ import annotations

import json
from typing import Any

from _common import (
    HERE,
    RUN_BINDINGS,
    annotation,
    case,
    cross_entity_contract,
    cross_entity_view,
    cross_user_view,
    dump,
    lifecycle,
    old_card,
    rescore,
    axes,
    ref,
    scope_target,
    stale_source_contract,
    stale_source_view,
    unit,
    version_binding,
)

RESULTS: list[dict[str, Any]] = []


def check(label: str, ok: bool, detail: Any = None) -> None:
    RESULTS.append({"label": label, "ok": bool(ok), "detail": detail})


def good_cross_user():
    return dict(anns={"cross_user": annotation("cross_user")}, cross_user=cross_user_view())


def good_entity():
    return dict(
        anns={"cross_entity": annotation("cross_entity")},
        cross_entity=cross_entity_view(units=(unit("u1"),), unit_entity={"u1": axes.EntityIdentityView("item", "K1")}),
        cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),)),
    )


def good_stale():
    return dict(
        anns={"stale_source": annotation("stale_source")},
        stale_source=stale_source_view(units=(unit("u1"),), lifecycle_map={"u1": lifecycle()}, actual_as_of="2026-10-28"),
        stale_source_contract=stale_source_contract(
            constrained_refs=(ref(),), version_bindings={rescore.ref_key(ref()): version_binding()}
        ),
    )


def merged(*parts: dict[str, Any], old=None, case_id: str = "CASE") -> axes.AxesCaseView:
    payload: dict[str, Any] = {"anns": {}}
    for part in parts:
        for key, value in part.items():
            if key == "anns":
                payload["anns"] = {**payload["anns"], **value}
            else:
                payload[key] = value
    return case(case_id=case_id, old=old_card(case_id=case_id) if old is None else old, **payload)


def build_cases() -> list[axes.AxesCaseView]:
    cases: list[axes.AxesCaseView] = []

    cases.append(merged(good_cross_user(), good_entity(), good_stale(), case_id="C1"))

    # C2：cross_user violation（owner 不一致）
    cases.append(
        merged(
            dict(anns={"cross_user": annotation("cross_user")}, cross_user=cross_user_view(authenticated_user_id="user-B")),
            good_entity(),
            good_stale(),
            case_id="C2",
        )
    )

    # C3：cross_entity 合同缺失 -> unknown
    cases.append(
        merged(
            good_cross_user(),
            dict(anns={"cross_entity": annotation("cross_entity")}, cross_entity=cross_entity_view(units=(unit("u1"),))),
            good_stale(),
            case_id="C3",
        )
    )

    # C4：三轴同时有结论（cross_user unknown、cross_entity violation、stale violation）
    cases.append(
        merged(
            dict(anns={"cross_user": annotation("cross_user")}, cross_user=cross_user_view(projection_available=False)),
            dict(
                anns={"cross_entity": annotation("cross_entity")},
                cross_entity=cross_entity_view(units=(unit("u1"),), unit_entity={"u1": axes.EntityIdentityView("item", "K2")}),
                cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),)),
            ),
            dict(
                anns={"stale_source": annotation("stale_source")},
                stale_source=stale_source_view(
                    units=(unit("u1"),), lifecycle_map={"u1": lifecycle(document_deleted=True)}, actual_as_of="2026-10-28"
                ),
                stale_source_contract=stale_source_contract(
                    constrained_refs=(ref(),), version_bindings={rescore.ref_key(ref()): version_binding()}
                ),
            ),
            case_id="C4",
        )
    )

    # C5：旧 cross_entity unknown + 新 N/A 路径 -> 保留旧 unknown
    na_ann = annotation("cross_entity", applicability="not_applicable", criterion="no_entity_claim", reason="no_entity_scope")
    cases.append(
        merged(
            good_cross_user(),
            dict(
                anns={"cross_entity": na_ann},
                cross_entity=cross_entity_view(units=(), empty_scope_proven=True),
                cross_entity_contract=cross_entity_contract(mode="no_entity_scope"),
            ),
            good_stale(),
            case_id="C5",
            old=old_card(case_id="C5", cross_entity=("unknown", "targets_unresolved")),
        )
    )

    # C6：旧 safety violation（recorded_old），其余三轴 pass
    cases.append(
        merged(
            good_cross_user(),
            good_entity(),
            good_stale(),
            case_id="C6",
            old=old_card(case_id="C6", safety=("violation", "forbidden_value_leaked")),
        )
    )
    return cases


def main() -> int:
    identity = axes.AxesIdentity(
        base=rescore.RescoreIdentity(
            old_run_id="OLD-RUN-SYN",
            old_binding=RUN_BINDINGS,
            old_binding_sha256=rescore.file_sha256(axes.DEFAULT_CONTRACT_PATH)[:0] or "b" * 64,
            old_evidence_tree_sha256="e" * 64,
            old_card_sha256="f" * 64,
            contract_sha256=rescore.file_sha256(axes.DEFAULT_CONTRACT_PATH),
            evaluator_sha256=rescore.file_sha256(axes.__file__),
        ),
        base_contract_sha256=rescore.file_sha256(axes.BASE_CONTRACT_PATH),
    )
    cases = build_cases()
    report = axes.rescore_axes_run(identity=identity, cases=cases, allow_synthetic_fixture=True)
    data = report.as_dict()

    for axis in axes.AXES:
        for label, counts in (("new", data["axes"][axis]), ("old", data["old_axes"][axis])):
            check(
                f"{axis}/{label}: planned = passed+NA+unknown+violations",
                counts["planned"] == counts["passed"] + counts["not_applicable"] + counts["unknown"] + counts["violations"],
                counts,
            )
            check(
                f"{axis}/{label}: checked = passed+NA+violations",
                counts["checked"] == counts["passed"] + counts["not_applicable"] + counts["violations"],
                counts,
            )
            check(
                f"{axis}/{label}: checked+unknown = planned",
                counts["checked"] + counts["unknown"] == counts["planned"],
                counts,
            )
            check(f"{axis}/{label}: planned == case count", counts["planned"] == len(cases), counts)

    # 期望计数（手算）
    expected = {
        "cross_user": {"passed": 4, "unknown": 1, "violations": 1, "not_applicable": 0},
        "cross_entity": {"passed": 3, "unknown": 2, "violations": 1, "not_applicable": 0},
        "stale_source": {"passed": 5, "unknown": 0, "violations": 1, "not_applicable": 0},
        "safety": {"passed": 0, "unknown": 0, "violations": 1, "not_applicable": 5},
    }
    for axis, want in expected.items():
        got = data["axes"][axis]
        check(f"{axis}: hand-counted new counts", all(got[key] == value for key, value in want.items()), {"want": want, "got": got})

    # hard failures 是题目并集，不是轴数求和
    check("hard_failures is case union (C2,C4,C6)", list(data["hard_failures"]) == ["C2", "C4", "C6"], data["hard_failures"])
    check(
        "hard_failures < sum of violations (proves union not sum)",
        len(data["hard_failures"]) < sum(data["axes"][axis]["violations"] for axis in axes.AXES),
        {"union": len(data["hard_failures"]), "sum": sum(data["axes"][axis]["violations"] for axis in axes.AXES)},
    )
    check("missing_evidence_cases is case union (C3,C4,C5)", list(data["missing_evidence_cases"]) == ["C3", "C4", "C5"], data["missing_evidence_cases"])
    check(
        "missing_evidence_cases matches unknown union",
        set(data["missing_evidence_cases"])
        == {case.case_id for case in report_cases(report) if any(case.new_axes[axis]["state"] == "unknown" for axis in axes.AXES)},
    )

    # provenance
    check("axes_provenance safety == recorded_old", data["axes_provenance"]["safety"] == "recorded_old", data["axes_provenance"])
    for axis in axes.RESCORED_AXES:
        check(f"axes_provenance {axis} == rescored", data["axes_provenance"][axis] == "rescored")
    for axis in axes.AXES:
        counts = data["axes_provenance_counts"][axis]
        check(f"{axis}: provenance counts sum to planned", sum(counts.values()) == len(cases), counts)
        check(f"{axis}: basis counts sum to planned", sum(data["axes_basis_counts"][axis].values()) == len(cases), data["axes_basis_counts"][axis])
    check("safety provenance counts all recorded_old", data["axes_provenance_counts"]["safety"] == {"recorded_old": 6})
    check("cross_entity preserved_old_verdict == 1", data["axes_provenance_counts"]["cross_entity"].get("preserved_old_verdict") == 1, data["axes_provenance_counts"]["cross_entity"])
    check("safety basis is recorded_old", data["axes_basis_counts"]["safety"] == {"recorded_old": 6})

    # violation reasons
    check("violation_reasons cross_user", data["violation_reasons"]["cross_user"] == {"owner_identity_mismatch": 1}, data["violation_reasons"]["cross_user"])
    check("violation_reasons cross_entity", data["violation_reasons"]["cross_entity"] == {"other_entity_used": 1}, data["violation_reasons"]["cross_entity"])
    check("violation_reasons stale_source", data["violation_reasons"]["stale_source"] == {"source_deleted": 1}, data["violation_reasons"]["stale_source"])
    check("violation_reasons safety recorded_old", data["violation_reasons"]["safety"] == {"forbidden_value_leaked": 1}, data["violation_reasons"]["safety"])

    # changed_cases：只列真变化的三轴，不给 safety
    changed = data["changed_cases"]
    check("changed_cases excludes safety", all(item["axis"] != "safety" for item in changed), [item["axis"] for item in changed])
    check(
        "changed_cases exactly the 5 rescored changes",
        sorted((item["case_id"], item["axis"]) for item in changed)
        == [("C2", "cross_user"), ("C3", "cross_entity"), ("C4", "cross_entity"), ("C4", "cross_user"), ("C4", "stale_source")],
        [(item["case_id"], item["axis"]) for item in changed],
    )
    check("unchanged_case_count == 3", data["unchanged_case_count"] == 3, data["unchanged_case_count"])
    for item in changed:
        check(f"changed {item['case_id']}/{item['axis']} from != to", item["from"] != item["to"], item)
        check(f"changed {item['case_id']}/{item['axis']} audit codes are fixed", all(code in axes.AXES_AUDIT_CODES for code in item["audit_codes"]), item)

    # 输出禁止项：不得出现正向 verified/threshold/release
    forbidden_keys = {"verified", "threshold_met", "release_ready", "release", "T207_pass"}
    check("report has no positive forbidden keys", not (forbidden_keys & set(data)), sorted(set(data)))
    check(
        "not_claimed lists all forbidden claims",
        set(data["not_claimed"]) >= {"verified", "threshold_met", "release_ready", "release", "T207_pass", "all_axes_real_complete", "q1a3_complete"},
        data["not_claimed"],
    )
    text = json.dumps(data, ensure_ascii=False)
    for word in ["T207 通过", "release_ready\": true", "verified\": true"]:
        check(f"serialized report does not assert {word!r}", word not in text)

    # calls
    check("calls all zero", data["calls"] == {"network": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0}, data["calls"])

    # public_summary：无逐题 case_id / audit
    summary = report.public_summary()
    summary_text = json.dumps(summary, ensure_ascii=False)
    check("public_summary has no case ids", all(f'"C{i}"' not in summary_text for i in range(1, 7)))
    check("public_summary has no changed_cases/audit keys", not ({"changed_cases", "axis_audit"} & set(summary)))
    check("public_summary keeps counts", summary["axes"] == data["axes"])
    check("public_summary exposes counts only for hard failures", summary["hard_failure_count"] == 3 and summary["missing_evidence_case_count"] == 3)

    # 身份绑定
    check("analysis_identity_sha256 is 64 hex", len(data["analysis_identity_sha256"]) == 64 and set(data["analysis_identity_sha256"]) <= set("0123456789abcdef"))
    report2 = axes.rescore_axes_run(identity=identity, cases=cases, allow_synthetic_fixture=True)
    check("analysis identity deterministic", report2.analysis_identity_sha256 == data["analysis_identity_sha256"])
    identity3 = axes.AxesIdentity(
        base=rescore.RescoreIdentity(
            old_run_id="OLD-RUN-OTHER",
            old_binding=RUN_BINDINGS,
            old_binding_sha256="b" * 64,
            old_evidence_tree_sha256="e" * 64,
            old_card_sha256="f" * 64,
            contract_sha256=rescore.file_sha256(axes.DEFAULT_CONTRACT_PATH),
            evaluator_sha256=rescore.file_sha256(axes.__file__),
        ),
        base_contract_sha256=rescore.file_sha256(axes.BASE_CONTRACT_PATH),
    )
    report3 = axes.rescore_axes_run(identity=identity3, cases=cases, allow_synthetic_fixture=True)
    check("analysis identity binds old run id", report3.analysis_identity_sha256 != data["analysis_identity_sha256"])

    # synthetic guard：默认 False 时三轴全 unknown，safety 仍 recorded_old
    denied = axes.rescore_axes_run(identity=identity, cases=cases, allow_synthetic_fixture=False)
    denied_data = denied.as_dict()
    check("synthetic denied: three axes all unknown", all(denied_data["axes"][axis]["unknown"] == 6 for axis in axes.RESCORED_AXES), {axis: denied_data["axes"][axis] for axis in axes.RESCORED_AXES})
    check("synthetic denied: safety still recorded_old counts", denied_data["axes"]["safety"] == data["axes"]["safety"])
    check("synthetic denied flag recorded", denied_data["synthetic_fixture_allowed"] is False and data["synthetic_fixture_allowed"] is True)

    # 旧 unknown -> pass 只能以可审计方式发生（changed_cases 列出，provenance=rescored）
    upgrade_view = case(
        case_id="C7",
        old=old_card(case_id="C7", cross_entity=("unknown", "targets_unresolved")),
        anns={
            "cross_user": annotation("cross_user"),
            "cross_entity": annotation("cross_entity"),
            "stale_source": annotation("stale_source"),
        },
        cross_user=cross_user_view(),
        cross_entity=cross_entity_view(units=(), empty_scope_proven=True),
        cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),)),
        stale_source=stale_source_view(units=(unit("u1"),), lifecycle_map={"u1": lifecycle()}, actual_as_of="2026-10-28"),
        stale_source_contract=stale_source_contract(
            constrained_refs=(ref(),), version_bindings={rescore.ref_key(ref()): version_binding()}
        ),
    )
    upgrade_report = axes.rescore_axes_run(identity=identity, cases=(upgrade_view,), allow_synthetic_fixture=True)
    upgrade_changed = [item for item in upgrade_report.changed_cases if item["case_id"] == "C7"]
    check(
        "old unknown -> pass is auditable in changed_cases (not silent)",
        len(upgrade_changed) == 1
        and upgrade_changed[0]["axis"] == "cross_entity"
        and upgrade_changed[0]["from"]["state"] == "unknown"
        and upgrade_changed[0]["to"]["state"] == "passed"
        and upgrade_changed[0]["provenance"] == "rescored",
        upgrade_changed,
    )
    check("old unknown -> pass has rescored provenance", upgrade_report.axes_provenance_counts["cross_entity"].get("rescored") == 1, dict(upgrade_report.axes_provenance_counts["cross_entity"]))

    # 旧 N/A 不得被“保持”为 N/A 当新证据要求实体：必须按新证据重算
    na_old_view = case(
        case_id="C8",
        old=old_card(case_id="C8", cross_entity=("not_applicable", axes.NA_REASONS["cross_entity"])),
        anns={"cross_entity": annotation("cross_entity")},
        cross_entity=cross_entity_view(units=(unit("u1"),), unit_entity={"u1": axes.EntityIdentityView("item", "K1")}),
        cross_entity_contract=cross_entity_contract(targets=(scope_target("item", "K1"),)),
    )
    na_result = axes.rescore_axes_case(na_old_view, allow_synthetic_fixture=True)
    check(
        "old N/A is re-evaluated, not generalized: required entity target -> passed",
        na_result.new_axes["cross_entity"]["state"] == "passed" and na_result.axis_provenance["cross_entity"] == "rescored",
        dict(na_result.new_axes["cross_entity"]),
    )

    failures = [item for item in RESULTS if not item["ok"]]
    payload = {
        "probe": "12-counts-provenance",
        "assertions_total": len(RESULTS),
        "assertions_failed": len(failures),
        "failures": failures,
        "report": data,
        "public_summary": summary,
        "verdict": "PASS" if not failures else "FAIL",
    }
    dump(HERE / "12-counts-provenance.out.json", payload)
    print(json.dumps({"assertions": len(RESULTS), "failed": len(failures), "verdict": payload["verdict"]}, ensure_ascii=False))
    if failures:
        print(json.dumps(failures, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def report_cases(report: axes.AxesRescoreReport) -> list[axes.AxesCaseResult]:
    # 由 public 报告无法反查逐案；用已知输入重算（纯函数、无 I/O）
    return [axes.rescore_axes_case(view, allow_synthetic_fixture=True) for view in build_cases()]


if __name__ == "__main__":
    raise SystemExit(main())

