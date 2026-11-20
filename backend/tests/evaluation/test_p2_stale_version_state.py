"""`stale_source` 判据 v1 分类器的合成测试（数据集无关、零真实调用）。

覆盖（规范 §12.3 的 G-1..G-10 + §9 的 F-1..F-12）：

- 两模式同一条代码路径（同一 case 在 ``version_state`` / ``date_window`` 下的两种结论）。
- active 推导（位置序 + 版本号标签 + ``UNDECLARED`` 第三值）。
- 四路歧义：多 active / 0 active / 号序与位置序冲突 / 窗口与位置序不一致。
- F-1..F-12 逐条反例（每条都断言**等值固定码**，不只断言“是 unknown”）。
- 多轮折叠 ``violation > unknown > not_applicable > passed`` 与被折叠码保留。
- 21 码全部可达、14 个保留码一个不产出。
- 计数三公式 + ``not_applicable == 0`` + ``passed == version_only + version_plus_date``。

全部代码/日期/路径均为虚构，且刻意避开规范 §12.2 禁止的数据集字面量
（本文件不出现任何真实 source code、scenario id 或数据集日期常量）。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb.evaluation import p2_stale_version_state as stale  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard")

CRITERION = stale.CRITERION_VERSION
AS_OF = "2031-03-01"
LATER = "2033-01-01"
FIXTURE_SHA = "a" * 64

#: 虚构上传计划：唯一槽位 ``R10`` 三次上传（变体 -> 正常 -> 变体），``R11`` 一次。
_SOURCES: list[dict[str, Any]] = [
    {"path": "variants/Z20_slot_a.xlsx", "name": "R10_item.xlsx"},
    {"path": "normal/R10_item.xlsx"},
    {"path": "variants/Z21_slot_a.xlsx", "document_ref": "R10_item.xlsx"},
    {"path": "normal/R11_item.pdf"},
]
_SOURCE_MAP: dict[str, Any] = {
    "sources": {
        "Z20": {"base_doc_code": "R10", "version_number": 1},
        "Z21": {"base_doc_code": "R10", "version_number": 3},
        "R11": {"base_doc_code": "R11"},
        "Z99": {"base_doc_code": "R99"},
    }
}
_SCENARIO: dict[str, Any] = {
    "scenario_id": "S_syn",
    "source_indices": [0, 1, 2, 3],
    "ingest_batches": 99,
}

#: 干净的窗口 fixture：2031-03-01 时 R10 组只有 Z21 覆盖，R11 open ended。
_WINDOW_ROWS: dict[str, Any] = {
    "Z20": {"effective_from": "2029-01-01", "effective_to": "2030-01-01"},
    "R10": {"effective_from": "2030-01-01", "effective_to": "2031-01-01"},
    "Z21": {"effective_from": "2031-01-01", "effective_to": "2032-01-01"},
    "R11": {"effective_from": "2031-01-01"},
}


# --------------------------------------------------------------------------- #
# 构造器
# --------------------------------------------------------------------------- #


def _annotation(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "applicability": "required",
        "criterion": "lifecycle_dates",
        "reason": "published_lifecycle",
        "as_of": None,
        "temporal_intent": "current",
    }
    values.update(overrides)
    return values


def _unit(code: Any, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "unit_id": f"u-{code}",
        "code": code,
        "record_code": f"rec-{code}",
    }
    values.update(overrides)
    return values


def _usage(units: Any, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "observed": True,
        "units": copy.deepcopy(units),
        "turn_status": "complete",
    }
    values.update(overrides)
    return values


def _evidence(*, units: Any = None, with_usage: bool = True, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "case_id": "K1",
        "annotation": _annotation(),
    }
    if with_usage:
        values["usage"] = _usage([] if units is None else units)
    values.update(overrides)
    return values


def _grounding(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "mode": "version_state",
        "fixture_sha256": None,
        "scenario": copy.deepcopy(_SCENARIO),
        "ingest_plan": {
            "schema_version": "p2-ingest-plan/synth",
            "sources": copy.deepcopy(_SOURCES),
        },
        "source_map": copy.deepcopy(_SOURCE_MAP),
        "windows": None,
    }
    values.update(overrides)
    return values


def _windows(
    rows: dict[str, Any] | None = None,
    *,
    open_ended: Any = None,
    **overrides: Any,
) -> dict[str, Any]:
    source_rows = copy.deepcopy(_WINDOW_ROWS if rows is None else rows)
    if open_ended is None:
        open_ended = [code for code, row in source_rows.items() if "effective_to" not in row]
    values: dict[str, Any] = {
        "schema_version": stale.WINDOW_SCHEMA_VERSION,
        "bindings": {
            "source_map_sha256": "b" * 64,
            "ingest_plan_sha256": "c" * 64,
        },
        "windows": source_rows,
        "open_ended": list(open_ended),
        "basis": "owner_ruling",
        "evidence_ref": "synthetic-fixture",
    }
    values.update(overrides)
    return values


def _determine(grounding: dict[str, Any], evidence: dict[str, Any]) -> stale.CaseDetermination:
    return stale.determine_stale_case(CRITERION, grounding, evidence)


def _open_dated_grounding(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "mode": "date_window",
        "fixture_sha256": FIXTURE_SHA,
        "windows": _windows(),
    }
    values.update(overrides)
    return _grounding(**values)


# --------------------------------------------------------------------------- #
# G-1 / G-2：两模式同一路径 + active 推导
# --------------------------------------------------------------------------- #


def test_version_state_active_used_passes_and_superseded_is_violation():
    active = _determine(_grounding(), _evidence(units=[_unit("Z21")]))
    assert active.state == "passed"
    assert active.reason == "stale_active_version_used"
    assert active.evidence_grade == "version_only"

    superseded_variant = _determine(_grounding(), _evidence(units=[_unit("Z20")]))
    assert superseded_variant.state == "violation"
    assert superseded_variant.reason == "stale_superseded_version_used"

    # 同一槽位里更早上传的正常文件同样已被取代（位置 1 < 2）。
    superseded_base = _determine(_grounding(), _evidence(units=[_unit("R10")]))
    assert superseded_base.state == "violation"
    assert superseded_base.reason == "stale_superseded_version_used"

    # 单成员槽位：位置序 active 就是它自己。
    single = _determine(_grounding(), _evidence(units=[_unit("R11")]))
    assert single.state == "passed"
    assert single.reason == "stale_active_version_used"


def test_same_case_in_two_modes_differs_only_by_grounding_mode():
    evidence = _evidence(units=[_unit("Z21")], as_of=AS_OF)
    version_state = _determine(_grounding(), evidence)
    date_window = _determine(_open_dated_grounding(), evidence)
    assert (version_state.state, version_state.reason) == ("passed", "stale_active_version_used")
    assert version_state.evidence_grade == "version_only"
    assert (date_window.state, date_window.reason) == ("passed", "stale_source_dates_ok")
    assert date_window.evidence_grade == "version_plus_date"
    assert version_state.provenance["grounding_mode"] == "version_state"
    assert date_window.provenance["grounding_mode"] == "date_window"


def test_undeclared_version_number_is_third_value_not_one():
    sources = [
        {"path": "variants/Z30_slot_b.xlsx", "name": "R12_item.xlsx"},
        {"path": "normal/R12_item.xlsx"},
    ]
    source_map = {
        "sources": {
            "Z30": {"base_doc_code": "R12", "version_number": 1},
            "R12": {"base_doc_code": "R12"},
        }
    }
    scenario = {"scenario_id": "S_syn_b", "source_indices": [0, 1], "ingest_batches": 3}
    grounding = _grounding(
        scenario=scenario,
        ingest_plan={"sources": sources},
        source_map=source_map,
    )

    # F-1：号缺失不阻止位置序判定；非 active 仍判 superseded，不得判 version_unresolved。
    superseded = _determine(grounding, _evidence(units=[_unit("Z30")]))
    assert superseded.state == "violation"
    assert superseded.reason == "stale_superseded_version_used"

    active = _determine(grounding, _evidence(units=[_unit("R12")]))
    assert active.state == "passed"
    assert active.reason == "stale_active_version_used"
    assert active.provenance["active_versions"]["R12"]["version_number"] is None
    assert "stale_version_number_undeclared" in active.provenance["audit"]
    # 组内含 UNDECLARED 成员 → R-AV-5 跳过并留审计。
    assert "stale_active_version_from_position" in active.provenance["audit"]


# --------------------------------------------------------------------------- #
# G-3：四路歧义（多 active / 0 active / 号序冲突 / 窗口-位置冲突）
# --------------------------------------------------------------------------- #


def test_f2_duplicate_source_indices_are_ambiguous_not_pick_one():
    grounding = _grounding(scenario={**_SCENARIO, "source_indices": [0, 1, 1]})
    determination = _determine(grounding, _evidence(units=[_unit("Z21")]))
    assert determination.state == "unknown"
    assert determination.reason == "stale_active_version_ambiguous"
    assert "stale_duplicate_source_indices" in determination.provenance["audit"]


def test_f3_zero_active_is_ambiguous_not_violation():
    # Z99 在 source map 里（base R99），但本 scenario 从未上传该槽位。
    determination = _determine(_grounding(), _evidence(units=[_unit("Z99")]))
    assert determination.state == "unknown"
    assert determination.reason == "stale_active_version_ambiguous"
    assert any(
        "stale_usage_source_not_in_scenario" in token
        for token in determination.provenance["audit"]
    )
    assert determination.state != "violation"


def test_f9_declared_version_order_conflict_is_ambiguous():
    source_map = copy.deepcopy(_SOURCE_MAP)
    source_map["sources"]["R10"] = {"base_doc_code": "R10", "version_number": 5}
    determination = _determine(
        _grounding(source_map=source_map), _evidence(units=[_unit("Z21")])
    )
    assert determination.state == "unknown"
    assert determination.reason == "stale_active_version_ambiguous"
    assert "stale_version_order_conflict" in determination.provenance["audit"]


def test_window_multiple_covering_sources_is_ambiguous():
    rows = copy.deepcopy(_WINDOW_ROWS)
    rows["R10"] = {"effective_from": "2030-06-01", "effective_to": "2031-06-01"}
    determination = _determine(
        _open_dated_grounding(windows=_windows(rows)),
        _evidence(units=[_unit("Z21")], as_of=AS_OF),
    )
    assert determination.state == "unknown"
    assert determination.reason == "stale_active_version_ambiguous"


def test_window_and_position_disagreement_is_ambiguous_not_pick_one():
    rows = copy.deepcopy(_WINDOW_ROWS)
    rows["R10"] = {"effective_from": "2030-01-01", "effective_to": "2031-06-01"}
    rows["Z21"] = {"effective_from": "2032-01-01", "effective_to": "2033-01-01"}
    determination = _determine(
        _open_dated_grounding(windows=_windows(rows)),
        _evidence(units=[_unit("R10")], as_of=AS_OF),
    )
    assert determination.state == "unknown"
    assert determination.reason == "stale_active_version_ambiguous"
    assert any(
        "stale_grounding_crosscheck_disagreement" in token
        for token in determination.provenance["audit"]
    )


# --------------------------------------------------------------------------- #
# G-4 / F-7 / F-8：使用集与空集闭包
# --------------------------------------------------------------------------- #


def _proven_empty_usage() -> dict[str, Any]:
    return {
        "observed": True,
        "units": [],
        "turn_status": "complete",
        "use_layers": {
            "model_evidence": {"observed": True, "count": 0, "refs": []},
            "direct_rag_fact": {"observed": True, "count": 0, "refs": []},
        },
        "retrieval": {"observed": True, "count": 0, "refs": [], "truncated": False},
    }


def test_empty_use_scope_proven_is_passed_not_not_applicable():
    evidence = _evidence(with_usage=False, usage=_proven_empty_usage())
    determination = _determine(_grounding(), evidence)
    assert determination.state == "passed"
    assert determination.reason == "stale_empty_use_scope_proven"
    assert determination.evidence_grade == "version_only"
    assert determination.state != "not_applicable"


def test_f8_forged_closure_boolean_is_not_proof():
    usage = {
        "observed": True,
        "units": [],
        "turn_status": "complete",
        "closure_proven": True,
        "empty_set_candidate": True,
    }
    determination = _determine(
        _grounding(), _evidence(with_usage=False, usage=usage)
    )
    assert determination.state == "unknown"
    assert determination.reason == "empty_set_not_proven"


def test_f8_truncated_retrieval_candidates_are_not_proof():
    usage = _proven_empty_usage()
    usage["retrieval"]["truncated"] = True
    determination = _determine(
        _grounding(), _evidence(with_usage=False, usage=usage)
    )
    assert determination.state == "unknown"
    assert determination.reason == "empty_set_not_proven"


def test_f7_zero_usage_observation_is_unknown_not_pass():
    for usage in (
        {"observed": False, "units": []},
        {"observed": True, "turn_status": "complete"},
        {"observed": True, "units": "not-a-list"},
    ):
        determination = _determine(
            _grounding(), _evidence(with_usage=False, usage=usage)
        )
        assert determination.state == "unknown"
        assert determination.reason == "stale_usage_set_missing"


def test_missing_usage_key_is_unknown():
    determination = _determine(_grounding(), _evidence(with_usage=False))
    assert determination.state == "unknown"
    assert determination.reason == "stale_usage_set_missing"


# --------------------------------------------------------------------------- #
# G-5：单向加严（version_state）与窗口 active（date_window）
# --------------------------------------------------------------------------- #


def test_version_state_overlay_covering_window_adds_date_grade():
    determination = _determine(
        _grounding(fixture_sha256=FIXTURE_SHA, windows=_windows()),
        _evidence(units=[_unit("Z21")], as_of=AS_OF),
    )
    assert determination.state == "passed"
    assert determination.reason == "stale_active_version_used"
    assert determination.evidence_grade == "version_plus_date"


def test_version_state_overlay_not_covering_window_is_violation():
    rows = copy.deepcopy(_WINDOW_ROWS)
    rows["Z21"] = {"effective_from": "2029-01-01", "effective_to": "2030-01-01"}
    determination = _determine(
        _grounding(fixture_sha256=FIXTURE_SHA, windows=_windows(rows)),
        _evidence(units=[_unit("Z21")], as_of=AS_OF),
    )
    assert determination.state == "violation"
    assert determination.reason == "stale_out_of_window"


def test_version_state_broken_window_never_creates_unknown():
    # 半端且未列 open_ended → 整份 fixture 拒收；只丢弃，不改 verdict（F-10 的 P4 侧口径）。
    rows = {"Z21": {"effective_from": "2031-01-01"}}
    determination = _determine(
        _grounding(
            fixture_sha256=FIXTURE_SHA,
            windows=_windows(rows, open_ended=[]),
        ),
        _evidence(units=[_unit("Z21")], as_of=AS_OF),
    )
    assert determination.state == "passed"
    assert determination.reason == "stale_active_version_used"
    assert determination.evidence_grade == "version_only"
    assert "stale_date_fixture_rejected" in determination.provenance["audit"]


def test_f10_window_fixture_rejected_for_corpus_constant_and_basis():
    cases = [
        _grounding(
            fixture_sha256=FIXTURE_SHA,
            windows=_windows(),
            built_at="2031-01-01",
        ),
        _grounding(
            fixture_sha256=FIXTURE_SHA,
            windows=_windows(),
            corpus_header_dates=["2031-01-01"],
        ),
        _grounding(
            fixture_sha256=FIXTURE_SHA,
            windows=_windows(basis="inferred_from_upload_order"),
        ),
        _grounding(
            fixture_sha256=FIXTURE_SHA,
            windows=_windows(evidence_ref=""),
        ),
        _grounding(
            fixture_sha256=FIXTURE_SHA,
            windows=_windows(
                {"Z20": {"effective_from": "2030-01-01"}, "R10": {"effective_from": "2030-01-01"}},
                open_ended=["Z20", "R10"],
            ),
        ),
    ]
    for grounding in cases:
        version_state = _determine(grounding, _evidence(units=[_unit("Z21")], as_of=AS_OF))
        assert version_state.state == "passed"
        assert version_state.reason == "stale_active_version_used"
        assert version_state.evidence_grade == "version_only"
        assert "stale_date_fixture_rejected" in version_state.provenance["audit"]

        date_window = _determine(
            {**grounding, "mode": "date_window"},
            _evidence(units=[_unit("Z21")], as_of=AS_OF),
        )
        assert date_window.state == "unknown"
        assert date_window.reason == "stale_window_unresolved"


def test_date_window_requires_bound_fixture():
    bad_bindings = _windows()
    bad_bindings["bindings"] = {"source_map_sha256": "b" * 64}
    for grounding in (
        _open_dated_grounding(fixture_sha256=None),
        _open_dated_grounding(windows=None),
        _open_dated_grounding(windows=bad_bindings),
    ):
        determination = _determine(grounding, _evidence(units=[_unit("Z21")], as_of=AS_OF))
        assert determination.state == "unknown"
        assert determination.reason == "stale_window_unresolved"


def test_f4_all_windows_exclude_as_of_is_violation_not_not_applicable():
    determination = _determine(
        _open_dated_grounding(),
        _evidence(units=[_unit("Z21")], as_of=LATER),
    )
    assert determination.state == "violation"
    assert determination.reason == "stale_out_of_window"
    assert determination.state != "not_applicable"


def test_date_window_used_source_outside_window_is_violation():
    determination = _determine(
        _open_dated_grounding(),
        _evidence(units=[_unit("Z20")], as_of=AS_OF),
    )
    assert determination.state == "violation"
    assert determination.reason == "stale_out_of_window"


def test_date_window_missing_as_of_is_unknown():
    determination = _determine(
        _open_dated_grounding(),
        _evidence(units=[_unit("Z21")], as_of=None),
    )
    assert determination.state == "unknown"
    assert determination.reason == "as_of_missing"


def test_date_window_member_window_missing_is_unresolved():
    rows = copy.deepcopy(_WINDOW_ROWS)
    del rows["Z20"]
    determination = _determine(
        _open_dated_grounding(windows=_windows(rows)),
        _evidence(units=[_unit("Z21")], as_of=AS_OF),
    )
    assert determination.state == "unknown"
    assert determination.reason == "stale_window_unresolved"


# --------------------------------------------------------------------------- #
# G-6 / F-12：多轮折叠
# --------------------------------------------------------------------------- #


def _turn(turn_index: int, usage: dict[str, Any]) -> dict[str, Any]:
    return {"turn_index": turn_index, "state_inputs": {"usage": usage}}


def test_f12_violation_wins_but_unknown_turn_is_preserved():
    evidence = _evidence(with_usage=False)
    evidence["turns"] = [
        _turn(0, _usage([])),
        _turn(1, _usage([_unit("Z20")])),
    ]
    determination = _determine(_grounding(), evidence)
    assert determination.state == "violation"
    assert determination.reason == "stale_superseded_version_used"
    assert [turn.reason for turn in determination.per_turn] == [
        "empty_set_not_proven",
        "stale_superseded_version_used",
    ]
    assert any("turn[0]:unknown:empty_set_not_proven" == token for token in determination.provenance["audit"])


def test_folding_unknown_outranks_passed_and_keeps_both_turns():
    evidence = _evidence(with_usage=False)
    evidence["turns"] = [
        _turn(0, {"observed": False, "units": []}),
        _turn(1, _usage([_unit("Z21")])),
    ]
    determination = _determine(_grounding(), evidence)
    assert determination.state == "unknown"
    assert determination.reason == "stale_usage_set_missing"
    assert [turn.state for turn in determination.per_turn] == ["unknown", "passed"]
    assert any("turn[1]:passed:stale_active_version_used" == token for token in determination.provenance["audit"])


def test_folding_tie_breaks_on_smallest_turn_index():
    evidence = _evidence(with_usage=False)
    evidence["turns"] = [
        _turn(3, _usage([_unit("Z21")])),
        _turn(1, _usage([_unit("Z20")])),
    ]
    determination = _determine(_grounding(), evidence)
    assert determination.state == "violation"
    assert determination.reason == "stale_superseded_version_used"
    assert determination.per_turn[0].turn_index == 1
    assert determination.provenance["audit"][-1] == "turn[3]:passed:stale_active_version_used"


def test_explicit_turns_require_per_turn_usage():
    evidence = _evidence(with_usage=False)
    evidence["turns"] = [{"turn_index": 0, "state_inputs": {}}, _turn(1, _usage([_unit("Z21")]))]
    determination = _determine(_grounding(), evidence)
    assert determination.state == "unknown"
    assert determination.reason == "stale_usage_set_missing"


# --------------------------------------------------------------------------- #
# G-7 / F-11：not_applicable 不可达
# --------------------------------------------------------------------------- #


def test_f11_not_applicable_annotation_is_unknown():
    evidence = _evidence(
        units=[_unit("Z21")],
        annotation=_annotation(applicability="not_applicable", reason="no_entity_scope"),
    )
    determination = _determine(_grounding(), evidence)
    assert determination.state == "unknown"
    assert determination.reason == "annotation_unknown"
    assert determination.state != "not_applicable"
    assert "scope_mode_mismatch" in determination.provenance["audit"]


def test_f11_wrong_criterion_and_bad_reason_are_unknown():
    for annotation in (
        _annotation(criterion="no_entity_claim"),
        _annotation(reason="bogus_reason"),
        _annotation(reason=["published_lifecycle"]),
        _annotation(applicability={"x": 1}),
        _annotation(temporal_intent=["current"]),
    ):
        determination = _determine(
            _grounding(), _evidence(units=[_unit("Z21")], annotation=annotation)
        )
        assert determination.state == "unknown"
        assert determination.reason == "annotation_unknown"


def test_not_applicable_is_not_in_the_code_table():
    assert "not_applicable" not in set(stale.STATE_BY_CODE.values())
    with pytest.raises(stale.CriterionError):
        stale.TurnDetermination(
            turn_index=0,
            state="not_applicable",
            reason="annotation_unknown",
            evidence_grade="none",
        )


# --------------------------------------------------------------------------- #
# F-5 / F-6：模式声明与 scenario 契约
# --------------------------------------------------------------------------- #


def test_f5_mode_declaration_variants_are_invalid():
    cases = [
        "p2-stale-source-criterion/v0",
    ]
    for criterion_version in cases:
        determination = stale.determine_stale_case(
            criterion_version, _grounding(), _evidence(units=[_unit("Z21")])
        )
        assert determination.state == "unknown"
        assert determination.reason == "stale_grounding_mode_invalid"

    groundings = [
        {key: value for key, value in _grounding().items() if key != "mode"},
        _grounding(mode=["version_state", "date_window"]),
        _grounding(mode="both"),
        _grounding(mode={"mode": "version_state"}),
        {**_grounding(), "stale_grounding": {"mode": "version_state"}},
    ]
    for grounding in groundings:
        determination = _determine(grounding, _evidence(units=[_unit("Z21")]))
        assert determination.state == "unknown"
        assert determination.reason == "stale_grounding_mode_invalid"


def test_f6_scenario_contract_variants_are_undeclared():
    groundings = [
        _grounding(scenario=None),
        _grounding(scenario={"scenario_id": "S_syn", "source_indices": "0,1,2,3"}),
        _grounding(scenario={"scenario_id": "S_syn"}),
        _grounding(scenario={"scenario_id": "S_syn", "source_indices": [0, 1, 2, 99]}),
        _grounding(scenario={"scenario_id": "S_syn", "source_indices": [0, -1]}),
        _grounding(scenario={"scenario_id": "S_syn", "source_indices": [0, True]}),
        _grounding(ingest_plan=None),
    ]
    for grounding in groundings:
        determination = _determine(grounding, _evidence(units=[_unit("Z21")]))
        assert determination.state == "unknown"
        assert determination.reason == "stale_scenario_undeclared"


# --------------------------------------------------------------------------- #
# 身份 / citation / 日期意图
# --------------------------------------------------------------------------- #


def test_identity_unresolved_variants_are_source_unresolved():
    for unit in (
        {"unit_id": "u1", "code": "Z21"},
        {"unit_id": "u1", "code": "Z21", "record_code": ""},
        {"unit_id": "u1", "code": "Z21", "record_code": "rec", "answer": "leak"},
        "not-a-mapping",
    ):
        determination = _determine(_grounding(), _evidence(units=[unit]))
        assert determination.state == "unknown"
        assert determination.reason == "source_unresolved"


def test_unknown_code_is_version_unresolved():
    determination = _determine(_grounding(), _evidence(units=[_unit("NOPE")]))
    assert determination.state == "unknown"
    assert determination.reason == "version_unresolved"


def test_usage_source_not_uploaded_in_this_scenario_is_ambiguous():
    source_map = copy.deepcopy(_SOURCE_MAP)
    source_map["sources"]["Z22"] = {"base_doc_code": "R10", "version_number": 4}
    determination = _determine(
        _grounding(source_map=source_map), _evidence(units=[_unit("Z22")])
    )
    assert determination.state == "unknown"
    assert determination.reason == "stale_active_version_ambiguous"


def test_citation_layer_matching_and_mismatch():
    unit = _unit("Z21", document_id="doc-1", version_id="ver-3")
    matching = _evidence(
        units=[unit],
        citations=[{"unit_id": "u-Z21", "document_id": "doc-1", "version_id": "ver-3"}],
    )
    assert _determine(_grounding(), matching).state == "passed"

    mismatching = _evidence(
        units=[unit],
        citations=[{"unit_id": "u-Z21", "document_id": "doc-1", "version_id": "ver-9"}],
    )
    determination = _determine(_grounding(), mismatching)
    assert determination.state == "violation"
    assert determination.reason == "citation_version_mismatch"

    missing_row = _evidence(
        units=[unit], citations=[{"unit_id": "u-other", "document_id": "d", "version_id": "v"}]
    )
    determination = _determine(_grounding(), missing_row)
    assert determination.state == "unknown"
    assert determination.reason == "source_unresolved"

    no_projection = _evidence(units=[_unit("Z21")], citations=[
        {"unit_id": "u-Z21", "document_id": "doc-1", "version_id": "ver-3"}
    ])
    determination = _determine(_grounding(), no_projection)
    assert determination.state == "unknown"
    assert determination.reason == "source_unresolved"


def test_date_intent_conflict_is_product_side_violation():
    evidence = _evidence(
        units=[_unit("Z21")], as_of=AS_OF, annotation=_annotation(as_of="2030-01-01")
    )
    determination = _determine(_grounding(), evidence)
    assert determination.state == "violation"
    assert determination.reason == "date_intent_conflict"

    equal = _evidence(
        units=[_unit("Z21")], as_of=AS_OF, annotation=_annotation(as_of=AS_OF)
    )
    assert _determine(_grounding(), equal).state == "passed"


# --------------------------------------------------------------------------- #
# G-8：21 码全部可达 + 14 个保留码不产出
# --------------------------------------------------------------------------- #


def _coverage_cases() -> list[stale.CaseDetermination]:
    empty_usage = _proven_empty_usage()
    mismatch_window_rows = copy.deepcopy(_WINDOW_ROWS)
    mismatch_window_rows["Z21"] = {"effective_from": "2029-01-01", "effective_to": "2030-01-01"}
    return [
        _determine(_grounding(), _evidence(units=[_unit("Z21")])),
        _determine(_grounding(), _evidence(units=[_unit("Z20")])),
        _determine(_open_dated_grounding(), _evidence(units=[_unit("Z21")], as_of=AS_OF)),
        _determine(
            _grounding(fixture_sha256=FIXTURE_SHA, windows=_windows(mismatch_window_rows)),
            _evidence(units=[_unit("Z21")], as_of=AS_OF),
        ),
        _determine(
            _grounding(),
            _evidence(
                units=[_unit("Z21", document_id="doc-1", version_id="ver-3")],
                citations=[{"unit_id": "u-Z21", "document_id": "doc-1", "version_id": "ver-9"}],
            ),
        ),
        _determine(
            _grounding(),
            _evidence(units=[_unit("Z21")], as_of=AS_OF, annotation=_annotation(as_of="2030-01-01")),
        ),
        _determine(_grounding(), _evidence(with_usage=False, usage=empty_usage)),
        _determine(_grounding(), _evidence(units=[_unit("Z99")])),
        _determine(_grounding(scenario=None), _evidence(units=[_unit("Z21")])),
        _determine(_grounding(), _evidence(with_usage=False)),
        _determine(_open_dated_grounding(fixture_sha256=None), _evidence(units=[_unit("Z21")])),
        _determine(_grounding(mode="unknown-mode"), _evidence(units=[_unit("Z21")])),
        _determine(
            _grounding(),
            _evidence(
                units=[_unit("Z21")],
                annotation=_annotation(applicability="not_applicable"),
            ),
        ),
        _determine(_grounding(), _evidence(units=[{"unit_id": "u", "code": "Z21"}])),
        _determine(_grounding(), _evidence(units=[_unit("UNKNOWN")])),
        _determine(_grounding(), _evidence(with_usage=False, usage={"observed": True, "units": []})),
        _determine(_open_dated_grounding(), _evidence(units=[_unit("Z21")], as_of=None)),
        _determine(
            _grounding(),
            _evidence(with_usage=False, usage={"observed": False, "reason": "turn_not_executed"}),
        ),
        _determine(
            _grounding(),
            _evidence(with_usage=False, usage={"observed": False, "reason": "turn_error"}),
        ),
        _determine(
            _grounding(),
            _evidence(
                with_usage=False,
                usage={"observed": False, "reason": "replay_without_original"},
            ),
        ),
        _determine(
            _grounding(),
            _evidence(with_usage=False, usage={"observed": False, "reason": "evidence_incomplete"}),
        ),
    ]


def test_g8_every_determination_code_is_reachable():
    reasons = {case.reason for case in _coverage_cases()}
    assert reasons == set(stale.DETERMINATION_CODES)
    assert len(stale.DETERMINATION_CODES) == 21
    assert len(stale.NEW_CODES) == 9
    assert len(stale.INHERITED_CODES) == 12
    assert len(stale.RETIRED_CODES) == 14


def test_g8_retired_codes_are_never_produced():
    produced = {case.reason for case in _coverage_cases()}
    assert produced.isdisjoint(stale.RETIRED_CODES)
    for case in _coverage_cases():
        assert case.reason in stale.DETERMINATION_CODES
        assert stale.STATE_BY_CODE[case.reason] == case.state


# --------------------------------------------------------------------------- #
# G-9：形状与计数不变量
# --------------------------------------------------------------------------- #


def test_g9_case_shape_and_two_grade_counts():
    passed_version_only = _determine(_grounding(), _evidence(units=[_unit("Z21")]))
    passed_both = _determine(
        _open_dated_grounding(), _evidence(units=[_unit("Z21")], as_of=AS_OF)
    )
    unknown = _determine(_grounding(), _evidence(with_usage=False))
    violation = _determine(_grounding(), _evidence(units=[_unit("Z20")]))

    payload = passed_version_only.as_dict()
    assert set(payload) == {
        "case_id",
        "scenario_id",
        "state",
        "reason",
        "evidence_grade",
        "per_turn",
        "provenance",
    }
    assert set(payload["per_turn"][0]) == {"turn_index", "state", "reason"}
    assert set(payload["provenance"]) == {"grounding_mode", "active_versions", "audit"}

    aggregate = stale.aggregate_cases(
        [passed_version_only, passed_both, unknown, violation]
    )
    counts = aggregate["counts"]
    assert counts["planned"] == 4
    assert counts["passed"] == 2
    assert counts["not_applicable"] == 0
    assert counts["unknown"] == 1
    assert counts["violations"] == 1
    assert counts["checked"] == 3
    assert counts["passed_version_only"] == 1
    assert counts["passed_version_plus_date"] == 1
    assert counts["passed"] == counts["passed_version_only"] + counts["passed_version_plus_date"]
    assert aggregate["axes_provenance"] == "rescored"
    assert aggregate["criterion_version"] == CRITERION


def test_g9_empty_aggregate_is_consistent():
    counts = stale.aggregate_cases([])["counts"]
    assert counts == {
        "planned": 0,
        "passed": 0,
        "not_applicable": 0,
        "unknown": 0,
        "violations": 0,
        "checked": 0,
        "passed_version_only": 0,
        "passed_version_plus_date": 0,
    }


def test_g9_output_never_carries_release_tokens():
    payload = _determine(_grounding(), _evidence(units=[_unit("Z21")])).as_dict()

    def _keys(value: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, child in value.items():
                found.add(str(key))
                found |= _keys(child)
        elif isinstance(value, list):
            for child in value:
                found |= _keys(child)
        return found

    keys = _keys(payload)
    for token in ("verified", "threshold", "release"):
        assert not any(token in key.lower() for key in keys)
    assert stale.STATE_BY_CODE[payload["reason"]] == payload["state"]


# --------------------------------------------------------------------------- #
# G-10：零数据集字面量 / 零网络（fixture 已在 pytestmark 上）
# --------------------------------------------------------------------------- #


def test_g10_implementation_has_no_dataset_literals():
    source = Path(stale.__file__).read_text(encoding="utf-8")
    forbidden = [f"D{index:02d}" for index in range(1, 7)]
    forbidden += [f"V{index:02d}" for index in range(1, 8)]
    forbidden += ["-".join(("2026", "10", "27")), "-".join(("2026", "10", "28"))]
    forbidden += [
        "_".join(("base", "b0")),
        "_".join(("base", "b0", "plus", "v01")),
        "_".join(("pre", "v05", "without", "v07")),
        "_".join(("post", "v05", "without", "v01")),
    ]
    for token in forbidden:
        assert token not in source, token


def test_g10_zero_external_attempts_across_full_workload(t09_network_guard):
    determinations = _coverage_cases()
    assert len(determinations) == 21
    # 与 netguard fixture 的 teardown 双重断言：全工作量下 external 恒为 0。
    assert t09_network_guard.snapshot()["external"] == []


def test_g10_no_network_or_provider_imports():
    source = Path(stale.__file__).read_text(encoding="utf-8")
    for token in ("requests", "httpx", "socket", "urllib", "openai", "anthropic"):
        assert token not in source


# --------------------------------------------------------------------------- #
# G-10 补充：非标量输入不得抛裸异常（IR-01 的教训同样适用于本模块）
# --------------------------------------------------------------------------- #


def _hostile_mutators() -> list[Any]:
    def set_grounding(key: str):
        def mutate(grounding: dict[str, Any], evidence: dict[str, Any], value: Any) -> None:
            grounding[key] = value

        return mutate

    def set_nested(outer: str, inner: str):
        def mutate(grounding: dict[str, Any], evidence: dict[str, Any], value: Any) -> None:
            grounding[outer][inner] = value

        return mutate

    def set_annotation(field: str):
        def mutate(grounding: dict[str, Any], evidence: dict[str, Any], value: Any) -> None:
            evidence["annotation"][field] = value

        return mutate

    def set_usage(field: str):
        def mutate(grounding: dict[str, Any], evidence: dict[str, Any], value: Any) -> None:
            evidence["usage"][field] = value

        return mutate

    def set_unit(field: str):
        def mutate(grounding: dict[str, Any], evidence: dict[str, Any], value: Any) -> None:
            evidence["usage"]["units"][0][field] = value

        return mutate

    def set_evidence(key: str):
        def mutate(grounding: dict[str, Any], evidence: dict[str, Any], value: Any) -> None:
            evidence[key] = value

        return mutate

    return [
        set_grounding("mode"),
        set_grounding("fixture_sha256"),
        set_grounding("scenario"),
        set_grounding("ingest_plan"),
        set_grounding("source_map"),
        set_grounding("windows"),
        set_grounding("built_at"),
        set_grounding("corpus_header_dates"),
        set_nested("scenario", "source_indices"),
        set_nested("ingest_plan", "sources"),
        set_nested("source_map", "sources"),
        set_evidence("annotation"),
        set_evidence("usage"),
        set_evidence("turns"),
        set_annotation("applicability"),
        set_annotation("criterion"),
        set_annotation("reason"),
        set_annotation("as_of"),
        set_annotation("temporal_intent"),
        set_usage("observed"),
        set_usage("units"),
        set_usage("turn_status"),
        set_usage("reason"),
        set_unit("code"),
        set_unit("record_code"),
        set_unit("unit_id"),
    ]


def test_hostile_non_scalar_inputs_never_raise():
    for mutate in _hostile_mutators():
        for value in (["x"], {"x": 1}, None, True):
            grounding = _grounding(fixture_sha256=FIXTURE_SHA, windows=_windows())
            evidence = _evidence(units=[_unit("Z21")], as_of=AS_OF)
            mutate(grounding, evidence, copy.deepcopy(value))
            determination = _determine(grounding, evidence)
            assert isinstance(determination, stale.CaseDetermination)
            assert stale.STATE_BY_CODE[determination.reason] == determination.state


# --------------------------------------------------------------------------- #
# G-10 补充：上传序按 idx 升序、ingest_batches 不参与判定、顶层未知键拒绝
# --------------------------------------------------------------------------- #


def test_source_indices_are_sorted_by_index_and_position_is_the_raw_index():
    # 声明顺序 [1,2,0,3]：R-AV-1 要求按 idx 升序上传，pos 取 plan 下标（0..3）。
    # 若误按“声明顺序”编号，Z21 会落到位置 1、Z20 落到位置 2，结论会翻转。
    grounding = _grounding(scenario={**_SCENARIO, "source_indices": [1, 2, 0, 3]})
    determination = _determine(grounding, _evidence(units=[_unit("Z21")]))
    assert determination.state == "passed"
    assert determination.reason == "stale_active_version_used"
    assert determination.provenance["active_versions"]["R10"]["position"] == 2
    assert determination.provenance["active_versions"]["R10"]["code"] == "Z21"

    superseded = _determine(grounding, _evidence(units=[_unit("Z20")]))
    assert superseded.state == "violation"
    assert superseded.reason == "stale_superseded_version_used"


def test_ingest_batches_is_opaque_and_only_audited():
    for batches in (7, "opaque", {"x": 1}):
        grounding = _grounding(scenario={**_SCENARIO, "ingest_batches": batches})
        determination = _determine(grounding, _evidence(units=[_unit("Z21")]))
        assert determination.state == "passed"
        assert "stale_batch_count_opaque" in determination.provenance["audit"]

    scenario = {key: value for key, value in _SCENARIO.items() if key != "ingest_batches"}
    determination = _determine(_grounding(scenario=scenario), _evidence(units=[_unit("Z21")]))
    assert "stale_batch_count_opaque" not in determination.provenance["audit"]


def test_unknown_top_level_keys_are_rejected_not_ignored():
    evidence = _evidence(units=[_unit("Z21")])
    evidence["answer"] = "leak"
    determination = _determine(_grounding(), evidence)
    assert determination.state == "unknown"
    assert determination.reason == "evidence_incomplete"
    assert "criterion_field_invalid:answer" in determination.provenance["audit"]

    # 非标量/混合类型键也不得抛裸异常（IR-01 的教训）。
    evidence = _evidence(units=[_unit("Z21")])
    evidence[1] = "int-key"
    determination = _determine(_grounding(), evidence)
    assert determination.state == "unknown"
    assert determination.reason == "evidence_incomplete"

    grounding = _grounding()
    grounding["scratch"] = 1
    determination = _determine(grounding, _evidence(units=[_unit("Z21")]))
    assert determination.state == "unknown"
    assert determination.reason == "stale_grounding_mode_invalid"
    assert "criterion_field_invalid:scratch" in determination.provenance["audit"]

    grounding = _grounding()
    grounding[2] = "int-key"
    determination = _determine(grounding, _evidence(units=[_unit("Z21")]))
    assert determination.state == "unknown"
    assert determination.reason == "stale_grounding_mode_invalid"


# --------------------------------------------------------------------------- #
# 规范 §7 十四行一致性表（全部虚构：V20/V21/V30/D10/D11、S_syn）
# --------------------------------------------------------------------------- #

_S7_SOURCES: list[dict[str, Any]] = [
    {"path": "variants/V20_d10_a.xlsx", "name": "D10_d10.xlsx"},
    {"path": "normal/D10_d10.xlsx"},
    {"path": "variants/V21_d10_b.xlsx", "document_ref": "D10_d10.xlsx"},
    {"path": "normal/D11_d11.pdf"},
]
_S7_MAP: dict[str, Any] = {
    "sources": {
        "V20": {"base_doc_code": "D10", "version_number": 1},
        "V21": {"base_doc_code": "D10", "version_number": 3},
        "V30": {"base_doc_code": "V30", "version_number": 1},
    }
}
_S7_SCENARIO: dict[str, Any] = {
    "scenario_id": "S_syn",
    "source_indices": [0, 1, 2, 3],
    "ingest_batches": 99,
}


def _s7_windows(v21_to: str | None) -> dict[str, Any]:
    rows: dict[str, Any] = {
        "V20": {"effective_from": "2025-01-01", "effective_to": "2025-06-30"},
        "D10": {"effective_from": "2025-07-01", "effective_to": "2025-12-31"},
        "V21": {"effective_from": "2026-01-01"},
    }
    if v21_to is not None:
        rows["V21"]["effective_to"] = v21_to
    return rows


def _s7_grounding(
    *,
    mode: str = "version_state",
    rows: dict[str, Any] | None = None,
    sha: str | None = None,
) -> dict[str, Any]:
    windows = None if rows is None else _windows(rows, open_ended=[])
    return _grounding(
        mode=mode,
        fixture_sha256=sha,
        scenario=_S7_SCENARIO,
        ingest_plan={"sources": _S7_SOURCES},
        source_map=_S7_MAP,
        windows=windows,
    )


def _s7_evidence(
    units: list[dict[str, Any]],
    *,
    as_of: str | None = None,
    closure: bool = False,
    unobserved: bool = False,
) -> dict[str, Any]:
    if unobserved:
        usage: dict[str, Any] = {"observed": False, "units": list(units)}
    else:
        usage = {"observed": True, "units": list(units), "turn_status": "complete"}
        if closure:
            usage["use_layers"] = {
                "model_evidence": {"observed": True, "count": 0, "refs": []},
                "direct_rag_fact": {"observed": True, "count": 0, "refs": []},
            }
            usage["retrieval"] = {
                "observed": True,
                "count": 0,
                "refs": [],
                "truncated": False,
            }
    return {
        "case_id": "S7",
        "as_of": as_of,
        "annotation": _annotation(),
        "usage": usage,
    }


def test_section7_fourteen_row_table_matches_criterion():
    table = [
        _determine(_s7_grounding(), _s7_evidence([_unit("V21")])),
        _determine(_s7_grounding(), _s7_evidence([_unit("V20")])),
        _determine(_s7_grounding(), _s7_evidence([_unit("D10")])),
        _determine(_s7_grounding(), _s7_evidence([_unit("D11")])),
        _determine(_s7_grounding(), _s7_evidence([_unit("V30")])),
        _determine(_s7_grounding(), _s7_evidence([], closure=True)),
        _determine(_s7_grounding(), _s7_evidence([])),
        _determine(_s7_grounding(), _s7_evidence([], unobserved=True)),
        _determine(
            _s7_grounding(rows=_s7_windows("2026-06-30"), sha=FIXTURE_SHA),
            _s7_evidence([_unit("V21")], as_of="2026-03-01"),
        ),
        _determine(
            _s7_grounding(rows=_s7_windows("2026-02-01"), sha=FIXTURE_SHA),
            _s7_evidence([_unit("V21")], as_of="2026-03-01"),
        ),
        _determine(
            _s7_grounding(rows=_s7_windows(None), sha=FIXTURE_SHA),
            _s7_evidence([_unit("V21")], as_of="2026-03-01"),
        ),
        _determine(
            _s7_grounding(mode="date_window", rows=None, sha=None),
            _s7_evidence([_unit("V21")], as_of="2026-03-01"),
        ),
        _determine(
            _s7_grounding(mode="date_window", rows=_s7_windows("2026-02-01"), sha=FIXTURE_SHA),
            _s7_evidence([_unit("V21")], as_of="2026-03-01"),
        ),
    ]
    expected = [
        ("passed", "stale_active_version_used", "version_only"),
        ("violation", "stale_superseded_version_used", "none"),
        ("violation", "stale_superseded_version_used", "none"),
        ("passed", "stale_active_version_used", "version_only"),
        ("unknown", "stale_active_version_ambiguous", "none"),
        ("passed", "stale_empty_use_scope_proven", "version_only"),
        ("unknown", "empty_set_not_proven", "none"),
        ("unknown", "stale_usage_set_missing", "none"),
        ("passed", "stale_active_version_used", "version_plus_date"),
        ("violation", "stale_out_of_window", "none"),
        ("passed", "stale_active_version_used", "version_only"),
        ("unknown", "stale_window_unresolved", "none"),
        ("violation", "stale_out_of_window", "none"),
    ]
    actual = [
        (case.state, case.reason, case.evidence_grade) for case in table
    ]
    assert actual == expected

    # 第 14 行：t1 pass、t2 用 V20 → violation，且 t1 保留。
    multi_turn = _evidence(with_usage=False)
    multi_turn["turns"] = [
        _turn(0, _usage([_unit("V21")])),
        _turn(1, _usage([_unit("V20")])),
    ]
    folded = _determine(_s7_grounding(), multi_turn)
    assert (folded.state, folded.reason) == ("violation", "stale_superseded_version_used")
    assert [(turn.state, turn.reason) for turn in folded.per_turn] == [
        ("passed", "stale_active_version_used"),
        ("violation", "stale_superseded_version_used"),
    ]
    assert any(
        token == "turn[0]:passed:stale_active_version_used"
        for token in folded.provenance["audit"]
    )
