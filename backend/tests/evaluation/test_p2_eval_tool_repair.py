"""T207 评测工具修复：任务1/2 的定向红/绿反例（进程内分类入口）。

覆盖：
- live_h2 合法 run_binding 不再被结构门误判 unknown_usage_field；
- 缺失/坏/跨身份 run_binding、local_mock 带 run_binding 不得 pass；
- A 缺键/坏类型/非 mapping 事件在进程内绕过 reader 时仍不得 pass；
- 每个出现的合法模型 purpose 必须 input=1/output=1；单侧 → model_events_missing；
- 重复/错分支/跨请求凑对/顺序不成立 → branch_evidence_inconsistent；
- legacy 非空使用层删除全部模型事件 → 全轴 unknown（aggregate unverified/missing/checked 下降）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import sys

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_EVALUATION_TESTS = Path(__file__).resolve().parent
if str(_EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(_EVALUATION_TESTS))

from evaluation import test_p2_hard_evidence as H  # noqa: E402
from mktkb.evaluation import p2_evidence_capture as capture  # noqa: E402
from mktkb.evaluation import p2_evidence_io as evidence_io  # noqa: E402
from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402

SENTINEL = "P2REPAIR_SECRET_SENTINEL_a1b2c3"


def _live_bindings(**overrides: str) -> dict[str, str]:
    values = {key: "a" * 64 for key in capture.BINDING_KEYS}
    values.update(
        run_id="run-live-repair",
        plan_id="plan-live-repair",
        plan_sha256="b" * 64,
        dataset_version="synthetic-repair-v1",
        manifest_sha256="c" * 64,
        label_version="synthetic-repair-v1",
        suite="p2-holdout",
        scenario_id="base_b0",
        scenario_contract_sha256="d" * 64,
        assignment_sha256="e" * 64,
        custody_sha256="f" * 64,
        config_sha256="1" * 64,
        pipeline_version="synthetic-pipeline",
        index_revision="7",
        code_version="2" * 64,
        fixture_kind=capture.LIVE_FIXTURE_KIND,
    )
    values.update(overrides)
    return values


def _run_binding(bindings: dict[str, str], **overrides: str) -> dict[str, str]:
    values = {
        "run_id": bindings["run_id"],
        "plan_sha256": bindings["plan_sha256"],
        "scenario_id": bindings["scenario_id"],
        "go_sha256": "3" * 64,
        "ledger_sha256": "4" * 64,
        "business_date": "2026-10-28",
        "code_version": bindings["code_version"],
        "config_sha256": bindings["config_sha256"],
    }
    values["attempt_scope_sha256"] = capture.attempt_scope_sha256(
        run_id=values["run_id"],
        plan_sha256=values["plan_sha256"],
        scenario_id=values["scenario_id"],
        go_sha256=values["go_sha256"],
        ledger_sha256=values["ledger_sha256"],
    )
    values.update(overrides)
    return values


def _to_live(
    envelope: dict[str, Any],
    *,
    bindings: dict[str, str] | None = None,
    run_binding: dict[str, str] | None | object = ...,
) -> dict[str, Any]:
    env = copy.deepcopy(envelope)
    resolved = dict(bindings or _live_bindings())
    env["fixture_kind"] = capture.LIVE_FIXTURE_KIND
    env["schema_version"] = capture.LIVE_EVIDENCE_SCHEMA_VERSION
    env["bindings"] = resolved
    if run_binding is ...:
        env["run_binding"] = _run_binding(resolved)
    elif run_binding is None:
        env.pop("run_binding", None)
    else:
        env["run_binding"] = dict(run_binding)  # type: ignore[arg-type]
    return env


def _assert_unknown(result: Any, reason: str) -> None:
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown", (axis, result.as_dict())
        assert result.axis(axis).reason == reason, (axis, result.axis(axis))


def _strip_events(envelope: dict[str, Any], predicate: Any) -> dict[str, Any]:
    env = copy.deepcopy(envelope)
    events = env["capture"]["events"]
    events[:] = [event for event in events if not predicate(event)]
    for seq, event in enumerate(events, 1):
        event["seq"] = seq
    env["capture"]["seq"] = len(events)
    env["capture"]["event_count"] = len(events)
    return env


def _model_pair(purpose: str = "answer") -> tuple[dict[str, Any], dict[str, Any]]:
    """（保留占位，便于后续扩反例；当前用例直接操作 capture 事件。）"""
    envelope = H.build_evidence()
    inputs = [event for event in envelope["capture"]["events"] if event["kind"] == "model_input"]
    outputs = [event for event in envelope["capture"]["events"] if event["kind"] == "model_output"]
    return copy.deepcopy(inputs[0]["payload"]), copy.deepcopy(outputs[0]["payload"])


# --------------------------------------------------------------------------- #
# 任务1：live_h2 合法绑定 / 缺键 / 冒充
# --------------------------------------------------------------------------- #


def test_live_h2_valid_run_binding_reaches_axis_facts() -> None:
    case, annotation = H._passing_nonempty_annotation()
    live = _to_live(H._passing_nonempty_envelope())
    # A 协议权威先接受该信封（证明是合法实际采集格式，而不是测试自造协议）。
    evidence_io.validate_turn_evidence(live, phase="any")
    result = H.classify(case, annotation, live)
    assert result.axis("stale_source").state == "passed", result.as_dict()
    assert result.axis("cross_entity").state == "passed", result.as_dict()
    for axis in hard.AXES:
        assert result.axis(axis).reason != "unknown_usage_field", (axis, result.axis(axis))


def test_live_h2_missing_or_bad_run_binding_is_unknown() -> None:
    case, annotation = H._passing_nonempty_annotation()
    baseline = _to_live(H._passing_nonempty_envelope())
    assert H.classify(case, annotation, baseline).axis("stale_source").state == "passed"

    mutated: list[dict[str, Any]] = []
    mutated.append(_to_live(H._passing_nonempty_envelope(), run_binding=None))
    bad_scope = _run_binding(_live_bindings(), attempt_scope_sha256="0" * 64)
    mutated.append(_to_live(H._passing_nonempty_envelope(), run_binding=bad_scope))
    cross_run = _live_bindings(run_id="run-other")
    mutated.append(
        _to_live(
            H._passing_nonempty_envelope(),
            bindings=cross_run,
            run_binding=_run_binding(_live_bindings()),
        )
    )
    mutated.append(_to_live(H._passing_nonempty_envelope(), run_binding={}))
    for envelope in mutated:
        result = H.classify(case, annotation, envelope)
        _assert_unknown(result, "branch_evidence_missing")


def test_local_mock_with_run_binding_is_distinct_and_unknown() -> None:
    case, annotation = H._passing_nonempty_annotation()
    envelope = H._passing_nonempty_envelope()
    envelope["run_binding"] = _run_binding(_live_bindings())
    result = H.classify(case, annotation, envelope)
    _assert_unknown(result, "branch_evidence_missing")
    # 未知顶层键仍保持既有固定 reason（不被冒充键的检查吞并）。
    unknown_key = H._passing_nonempty_envelope()
    unknown_key["retrieval_usage"] = ["unit-x"]
    assert H.classify(case, annotation, unknown_key).axis("stale_source").reason == "unknown_usage_field"


@pytest.mark.parametrize(
    "mutation",
    [
        "capture_errors_missing",
        "turn_http_status_missing",
        "schema_version_missing",
        "bindings_missing",
        "completeness_errors_missing",
        "projection_errors_missing",
        "projection_truncations_missing",
        "event_row_not_mapping",
    ],
)
def test_r6_missing_envelope_keys_are_unknown_in_process(mutation: str) -> None:
    case, annotation = H._passing_nonempty_annotation()
    envelope = H._passing_nonempty_envelope(skip_validate=True)
    if mutation == "capture_errors_missing":
        envelope["capture"].pop("errors")
    elif mutation == "turn_http_status_missing":
        envelope["turn"].pop("http_status")
    elif mutation == "schema_version_missing":
        envelope.pop("schema_version")
    elif mutation == "bindings_missing":
        envelope.pop("bindings")
    elif mutation == "completeness_errors_missing":
        envelope["completeness"].pop("errors")
    elif mutation == "projection_errors_missing":
        envelope["db_projection"].pop("errors")
    elif mutation == "projection_truncations_missing":
        envelope["db_projection"].pop("truncations")
    else:
        envelope["capture"]["events"].append("not-a-mapping")
        envelope["capture"]["seq"] = len(envelope["capture"]["events"])
        envelope["capture"]["event_count"] = len(envelope["capture"]["events"])
    result = H.classify(case, annotation, envelope)
    _assert_unknown(result, "branch_evidence_missing")


def test_bad_binding_error_does_not_echo_secret() -> None:
    case, annotation = H._passing_nonempty_annotation()
    bad = _run_binding(_live_bindings(), attempt_scope_sha256=SENTINEL)
    result = H.classify(case, annotation, _to_live(H._passing_nonempty_envelope(), run_binding=bad))
    payload = json.dumps(result.as_dict(), ensure_ascii=False)
    assert SENTINEL not in payload
    assert "unknown_usage_field" in payload or "branch_evidence_missing" in payload


# --------------------------------------------------------------------------- #
# 任务2：模型事件硬门（非空 passing turn 同样适用）
# --------------------------------------------------------------------------- #


def test_legacy_legal_pair_baseline_passes() -> None:
    case, annotation = H._passing_nonempty_annotation()
    result = H.classify(case, annotation, H._passing_nonempty_envelope())
    assert result.axis("stale_source").state == "passed", result.as_dict()
    assert result.axis("cross_entity").state == "passed", result.as_dict()


@pytest.mark.parametrize("kind", ["model_input", "model_output"])
def test_single_sided_model_event_blocks_all_axes(kind: str) -> None:
    case, annotation = H._passing_nonempty_annotation()
    envelope = _strip_events(H._passing_nonempty_envelope(), lambda event: event["kind"] == kind)
    result = H.classify(case, annotation, envelope)
    _assert_unknown(result, "model_events_missing")


def test_legacy_removed_all_model_events_on_nonempty_usage_is_unknown() -> None:
    case, annotation = H._passing_nonempty_annotation()
    envelope = _strip_events(
        H._passing_nonempty_envelope(), lambda event: event["kind"] in ("model_input", "model_output")
    )
    result = H.classify(case, annotation, envelope)
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown", (axis, result.as_dict())
    assert result.axis("stale_source").reason in {"empty_set_not_proven", "model_events_missing"}
    assert result.axis("cross_entity").reason in {"empty_set_not_proven", "model_events_missing"}


def test_legacy_no_model_with_explicit_empty_retrieval_still_passes() -> None:
    case = H._one_case()
    result = H.classify(case, H._single(case), H.legacy_no_model_empty_scope())
    assert result.axis("stale_source").state == "passed", result.as_dict()
    assert result.axis("cross_entity").state == "passed", result.as_dict()


def test_rag_query_expansion_single_side_blocks_all_axes() -> None:
    case = H._one_case()
    baseline = H._rag_empty_scope(use_model=True, purposes=["query_expansion"])
    assert H.classify(case, H._single(case), baseline).axis("stale_source").state == "passed"
    for kind in ("model_input", "model_output"):
        envelope = _strip_events(baseline, lambda event, kind=kind: event["kind"] == kind)
        result = H.classify(case, H._single(case), envelope)
        _assert_unknown(result, "model_events_missing")


def test_model_pair_cross_request_is_inconsistent() -> None:
    case, annotation = H._passing_nonempty_annotation()
    envelope = copy.deepcopy(H._passing_nonempty_envelope())
    output = next(event for event in envelope["capture"]["events"] if event["kind"] == "model_output")
    output["payload"]["request_id"] = "another-request"
    result = H.classify(case, annotation, envelope)
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown"
        assert result.axis(axis).reason == "branch_evidence_inconsistent"


def test_model_output_before_input_is_inconsistent() -> None:
    case, annotation = H._passing_nonempty_annotation()
    envelope = copy.deepcopy(H._passing_nonempty_envelope())
    events = envelope["capture"]["events"]
    input_index = next(i for i, event in enumerate(events) if event["kind"] == "model_input")
    output_index = next(i for i, event in enumerate(events) if event["kind"] == "model_output")
    # 保持 seq 连续（先过 A schema），只把 output 事件挪到 input 之前：配对顺序不成立。
    events[input_index], events[output_index] = events[output_index], events[input_index]
    for seq, event in enumerate(events, 1):
        event["seq"] = seq
    result = H.classify(case, annotation, envelope)
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown"
        assert result.axis(axis).reason == "branch_evidence_inconsistent"


def test_duplicate_model_events_still_inconsistent() -> None:
    case, annotation = H._passing_nonempty_annotation()
    envelope = copy.deepcopy(H._passing_nonempty_envelope())
    events = envelope["capture"]["events"]
    source = next(event for event in events if event["kind"] == "model_input")
    events.append({"seq": len(events) + 1, "kind": "model_input", "payload": copy.deepcopy(source["payload"])})
    envelope["capture"]["seq"] = len(events)
    envelope["capture"]["event_count"] = len(events)
    result = H.classify(case, annotation, envelope)
    for axis in hard.AXES:
        assert result.axis(axis).state == "unknown"
        assert result.axis(axis).reason == "branch_evidence_inconsistent"


def test_aggregate_single_side_event_cannot_be_verified() -> None:
    cases = H.make_cases()
    annotation = hard.prepare_annotation(H.make_annotation(cases), cases)
    good = H.model_answer_empty_scope()
    missing = H.model_answer_empty_scope(missing_model_output=True)
    results = []
    for index, case in enumerate(cases):
        results.append(
            hard.classify_case_evidence(case, annotation, H.make_audit(case, missing if index == 0 else good))
        )
    card = hard.aggregate_hard_evidence(results, total=30, run_id="run-repair-gap", config_hash="e" * 64)
    hard_evidence = card["hard_evidence"]
    assert hard_evidence["verified"] is False
    assert hard_evidence["missing_evidence_cases"] == 1
    for axis in hard.AXES:
        assert hard_evidence["axes"][axis]["unknown"] == 1, (axis, hard_evidence["axes"][axis])
        assert hard_evidence["axes"][axis]["checked"] == 29, (axis, hard_evidence["axes"][axis])
    codes = [block["code"] for block in card["blocks"]]
    assert "holdout_hard_failure_unverified" in codes
    assert "holdout_hard_evidence_missing" in codes
    assert card["release_ready"] is False
