"""R0-1 合成测试：同轮初判输入、来源证明、硬失败派生与一致性门。

覆盖任务单 §三：
- 历史卡同 case_id 但 run/plan_id/plan_sha256/evidence-tree/来源证明缺失 -> 拒绝；
- 旧 fail -> 本轮 pass、旧 error/缺证据 -> 本轮不同状态，本轮 error/缺证据仍拒绝假通过；
- ``hard_failed`` 一致性（新增/重复/缺失 case、硬失败存在但 flag=false、缺 aggregate）；
- unknown 不被隐去；rescore 冻结词表兼容；
- D3：``hard_failed`` 不再读不存在的顶层 ``new_hard_failures``。

全程只读公开源码/合成对象：不读私有路径、不读 .env、不联网。
文件 IO 与 socket/urllib/httpx 由 autouse fixture 阻断，并有正对照自证。
"""

from __future__ import annotations

import builtins
import copy
import importlib.util
import io
import socket
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import pytest

from mktkb.evaluation import p2_evidence_rescore as rescore
from mktkb.evaluation import p2_hard_evidence as hard
from mktkb.evaluation.p2_hard_evidence import AxisVerdict, CaseEvidenceResult

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/work"
CLASSIFIER_SHA = "a" * 64
SHA_B = "b" * 64


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


S = _load_module("r0_same_round_under_test", WORK / "r0_same_round.py")


# --------------------------------------------------------------------------- #
# 离线 / 私有路径守卫（autouse）+ 正对照
# --------------------------------------------------------------------------- #

_PRIVATE_MARKERS = (
    "mktkb-p2-h2v3-20261115",
    "mktkb-p2-h2v3-fullverify-20261116",
    "p1-holdout",
    ".env",
    "ev.key",
)


class GuardTripped(RuntimeError):
    """守卫主动拦截（不是真实网络/文件错误）。"""


def _is_private_path(value: Any) -> bool:
    if isinstance(value, int):
        return False
    try:
        text = str(value)
    except Exception:  # noqa: BLE001 - 无法转字符串的 fd 不拦截
        return False
    normalized = text.replace("\\", "/").lower()
    return any(marker in normalized for marker in _PRIVATE_MARKERS)


@pytest.fixture(autouse=True)
def _offline_and_private_path_guard(monkeypatch: pytest.MonkeyPatch) -> Any:
    real_io_open = io.open

    def guarded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if _is_private_path(file):
            raise GuardTripped(f"private_path_blocked:{file}")
        return real_io_open(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(builtins, "open", guarded_open)

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise GuardTripped("network_blocked")

    async def blocked_async(*_args: Any, **_kwargs: Any) -> Any:
        raise GuardTripped("network_blocked")

    monkeypatch.setattr(socket.socket, "connect", lambda self, address: blocked())
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, address: blocked())
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    try:
        import httpx
    except Exception:  # noqa: BLE001 - 未安装时只保留 socket/urllib 守卫
        httpx = None
    if httpx is not None:
        monkeypatch.setattr(httpx.Client, "send", blocked)
        monkeypatch.setattr(httpx.AsyncClient, "send", blocked_async)
    yield


def test_offline_guard_positive_controls() -> None:
    """守卫自证：网络与私有路径都被主动拦截，普通读文件仍可用。"""
    with pytest.raises(GuardTripped):
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)
    with pytest.raises(GuardTripped):
        urllib.request.urlopen("http://127.0.0.1:9/")
    with pytest.raises(GuardTripped):
        Path(r"D:\mktkb-p2-h2v3-fullverify-20261116\forbidden.json").read_bytes()
    assert Path(__file__).read_text(encoding="utf-8").strip()


def test_same_round_module_import_reads_no_data_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """导入期零数据 IO：除模块自身源码外，不打开任何文件。"""
    module_path = (WORK / "r0_same_round.py").resolve()
    seen: list[str] = []
    real_io_open = io.open

    def recording_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if not isinstance(file, int):
            seen.append(str(Path(file).resolve()))
        return real_io_open(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", recording_open)
    monkeypatch.setattr(builtins, "open", recording_open)
    _load_module("r0_same_round_import_probe", WORK / "r0_same_round.py")
    assert set(seen) <= {str(module_path)}


# --------------------------------------------------------------------------- #
# 合成结果 / 卡 / 来源证明
# --------------------------------------------------------------------------- #

_IDENTITY: dict[str, Any] = {
    "run_id": "run-current-01",
    "plan_id": "plan-current-01",
    "plan_sha256": "1" * 64,
    "evidence_tree_sha256": "2" * 64,
    "business_date": "2026-11-16",
    "scenario_id": "run0-base_b0",
    "code_version": "code-sha",
    "analysis_version": f"{rescore.ANALYSIS_ID}+{rescore.MATCHER_VERSION}",
}


def _identity_sources() -> dict[str, dict[str, Any]]:
    return {
        "run_id": {"object": "v3-binding.runs[0].run_id", "field": "run_id", "round": "current"},
        "plan_id": {"object": "plan-file.plan_id", "field": "plan_id", "round": "current"},
        "plan_sha256": {"object": "plan-file.plan_sha256", "field": "plan_sha256", "round": "current"},
        "evidence_tree_sha256": {
            "object": "run-receipt.seal.evidence_tree_sha256",
            "field": "seal.evidence_tree_sha256",
            "round": "current",
        },
        "business_date": {"object": "run-receipt.business_date", "field": "business_date", "round": "current"},
        "scenario_id": {"object": "v3-binding.runs[0].scenario_id", "field": "scenario_id", "round": "current"},
        "code_version": {"object": "case-plan.bindings.code_version", "field": "code_version", "round": "current"},
        "analysis_version": {"object": "p2_evidence_rescore.ANALYSIS_ID", "field": "analysis_id", "round": "current"},
    }


def _verdict(name: str, state: str, reason: str) -> AxisVerdict:
    return AxisVerdict(axis=name, state=state, reason=reason, evidence=(), missing=())


def _axes(
    *,
    safety: tuple[str, str] | None = None,
    cross_user: tuple[str, str] | None = None,
    cross_entity: tuple[str, str] | None = None,
    stale_source: tuple[str, str] | None = None,
) -> dict[str, AxisVerdict]:
    values = {
        "safety": safety or ("not_applicable", hard.NA_REASONS["safety"]),
        "cross_user": cross_user or ("passed", hard.PASS_REASONS["cross_user"]),
        "cross_entity": cross_entity or ("passed", hard.PASS_REASONS["cross_entity"]),
        "stale_source": stale_source or ("passed", hard.PASS_REASONS["stale_source"]),
    }
    return {name: _verdict(name, *values[name]) for name in hard.AXES}


def _result(
    case_id: str = "H2V3-C02",
    *,
    quality_status: str = "pass",
    stratum: str = "paraphrase",
    evidence_complete: bool = True,
    missing_codes: tuple[str, ...] = (),
    **axes: tuple[str, str],
) -> CaseEvidenceResult:
    return CaseEvidenceResult(
        case_id=case_id,
        stratum=stratum,
        scenario_id=None,
        quality_status=quality_status,
        axes=_axes(**axes),
        evidence_complete=evidence_complete,
        missing_count=len(missing_codes),
        missing_codes=missing_codes,
        planned_turns=1,
        executed_turns=1,
        replayed_turns=0,
    )


def _card(case_id: str = "H2V3-C02", **kwargs: Any) -> rescore.OldCardCase:
    return S.build_current_card(_result(case_id, **kwargs))


def _historical_card(
    case_id: str = "H2V3-C26",
    *,
    quality_status: str = "fail",
    safety: tuple[str, str] = ("violation", "security_refusal_missing"),
    evidence_complete: bool = True,
    missing_codes: tuple[str, ...] = (),
) -> rescore.OldCardCase:
    return rescore.OldCardCase(
        case_id=case_id,
        stratum="cross_doc_security",
        quality_status=quality_status,
        axes={
            "safety": {"state": safety[0], "reason": safety[1]},
            "cross_user": {"state": "passed", "reason": hard.PASS_REASONS["cross_user"]},
            "cross_entity": {"state": "unknown", "reason": "entity_identity_unresolved"},
            "stale_source": {"state": "unknown", "reason": "source_unresolved"},
        },
        missing_codes=missing_codes,
        evidence_complete=evidence_complete,
    )


def _origin(
    cards: list[rescore.OldCardCase],
    *,
    identity: Mapping[str, Any] | None = None,
    identity_sources: Mapping[str, Mapping[str, Any]] | None = None,
    card_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return S.card_origin_record(
        identity=dict(identity or _IDENTITY),
        identity_sources=dict(identity_sources or _identity_sources()),
        cards=cards,
        classifier_sha256=CLASSIFIER_SHA,
        classifier_source={"object": "backend/src/mktkb/evaluation/p2_hard_evidence.py", "round": "current"},
        card_source=card_source,
    )


def _expected(cards: list[rescore.OldCardCase], **overrides: Any) -> dict[str, Any]:
    expected = {
        "run_id": _IDENTITY["run_id"],
        "plan_id": _IDENTITY["plan_id"],
        "plan_sha256": _IDENTITY["plan_sha256"],
        "evidence_tree_sha256": _IDENTITY["evidence_tree_sha256"],
        "case_ids": [card.case_id for card in cards],
        "classifier_sha256": CLASSIFIER_SHA,
        "card_sha256": {card.case_id: S.card_sha256(card) for card in cards},
    }
    expected.update(overrides)
    return expected


def _view(card: rescore.OldCardCase) -> rescore.SafetyCaseView:
    return rescore.SafetyCaseView(
        old=card,
        safety_applicability="not_applicable",
        safety_criterion="benign_business",
        safety_reason="benign_business",
        should_refuse=False,
        forbidden_values=(),
        forbidden_sources=(),
        expected_sources=(),
        version_bindings={},
        turns=(
            rescore.TurnView(
                turn_index=0,
                status="executed",
                units=(),
                final_kind="not_found",
                final_text="暂不提供该信息",
            ),
        ),
    )


# --------------------------------------------------------------------------- #
# 词表兼容（固化 rescore/hard 等值）
# --------------------------------------------------------------------------- #


def test_rescore_vocabulary_matches_frozen_classifier() -> None:
    assert hard.PASS_REASONS["safety"] == rescore.PASS_REASON
    assert hard.NA_REASONS["safety"] == rescore.NA_REASON
    assert hard.AXIS_STATES == rescore.AXIS_STATES
    assert hard.QUALITY_STATUSES == rescore.QUALITY_STATUSES
    assert hard.VIOLATION_REASONS_BY_AXIS["safety"] == rescore.SAFETY_VIOLATION_REASONS
    assert hard.UNKNOWN_REASONS_BY_AXIS["safety"] == (
        rescore.SAFETY_UNKNOWN_REASONS - {"turn_identity_inconsistent"}
    )


@pytest.mark.parametrize(
    "safety",
    [
        ("passed", hard.PASS_REASONS["safety"]),
        ("not_applicable", hard.NA_REASONS["safety"]),
        ("unknown", "evidence_incomplete"),
        ("unknown", "turn_identity_inconsistent"),
        ("violation", "security_refusal_missing"),
        ("violation", "forbidden_source_used"),
    ],
)
def test_build_current_card_accepts_every_safety_vocabulary_state(safety: tuple[str, str]) -> None:
    card = _card(safety=safety)
    assert card.case_id == "H2V3-C02"
    assert card.axes["safety"] == {"state": safety[0], "reason": safety[1]}


def test_build_current_card_rejects_reason_outside_frozen_vocabulary() -> None:
    result = _result(safety=("passed", "made_up_reason"))
    with pytest.raises(S.SameRoundError) as info:
        S.build_current_card(result)
    assert info.value.code == "rescore_vocabulary_incompatible"


def test_build_current_card_takes_quality_fields_from_current_result() -> None:
    result = _result(
        quality_status="error",
        evidence_complete=False,
        missing_codes=("turn_error", "evidence_incomplete"),
        stratum="multi_turn",
    )
    card = S.build_current_card(result)
    assert card.quality_status == "error"
    assert card.evidence_complete is False
    assert card.missing_codes == ("turn_error", "evidence_incomplete")
    assert card.stratum == "multi_turn"
    assert S.card_payload(card)["quality_status"] == "error"


# --------------------------------------------------------------------------- #
# D1：历史卡“结构上能过”但同轮来源校验必须拒绝
# --------------------------------------------------------------------------- #


def test_historical_card_passes_structural_identity_but_same_round_rejects() -> None:
    """红：旧适配把历史卡字节配上本轮 identity，冻结 RescoreIdentity 照收。

    绿：``assert_same_round`` 只认当前轮来源，历史来源被固定码拒绝。
    """
    current = _card(case_id="H2V3-C26", quality_status="pass")
    historical = _historical_card("H2V3-C26")
    current_origin = _origin([current])
    S.assert_same_round({"expected": _expected([current]), "origin": current_origin})

    # 旧适配 (:962-975)：历史卡字节 + 本轮 run/binding/tree 放进同一个 RescoreIdentity。
    historical_bytes = rescore.canonical_json_bytes(S.card_payload(historical))
    mixed = rescore.RescoreIdentity(
        old_run_id=_IDENTITY["run_id"],
        old_binding={"plan_id": _IDENTITY["plan_id"], "plan_sha256": _IDENTITY["plan_sha256"]},
        old_binding_sha256="3" * 64,
        old_evidence_tree_sha256=_IDENTITY["evidence_tree_sha256"],
        old_card_sha256=hard_hash(historical_bytes),
        contract_sha256="4" * 64,
        evaluator_sha256="5" * 64,
        old_binding_bytes=rescore.canonical_json_bytes(
            {"plan_id": _IDENTITY["plan_id"], "plan_sha256": _IDENTITY["plan_sha256"]}
        ),
        old_card_bytes=historical_bytes,
    )
    assert mixed.old_run_id == _IDENTITY["run_id"]
    assert mixed.old_card_sha256 != S.card_sha256(current)

    historical_origin = _origin(
        [historical],
        card_source={
            "object": "compose/evidence/recompute-four-runs.json#runs[i].card",
            "round": "historical",
        },
    )
    with pytest.raises(S.SameRoundError) as info:
        S.assert_same_round({"expected": _expected([current]), "origin": historical_origin})
    assert info.value.code == "same_round_origin_not_current"


def hard_hash(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def test_mixed_current_and_historical_cards_rejected() -> None:
    current = _card(case_id="H2V3-C01")
    historical = _historical_card("H2V3-C26")
    origin = _origin(
        [current, historical],
        card_source={"object": "compose/evidence/recompute-four-runs.json", "round": "historical"},
    )
    with pytest.raises(S.SameRoundError) as info:
        S.assert_same_round({"expected": _expected([current, historical]), "origin": origin})
    assert info.value.code == "same_round_origin_not_current"


# --------------------------------------------------------------------------- #
# §三：五类拒绝（run / plan_id / plan_sha256 / evidence-tree / 缺失来源证明）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("run_id", "run-other-99", "run_id_mismatch"),
        ("plan_id", "plan-other-99", "plan_id_mismatch"),
        ("plan_sha256", SHA_B, "plan_sha256_mismatch"),
        ("evidence_tree_sha256", "c" * 64, "evidence_tree_mismatch"),
    ],
)
def test_assert_same_round_rejects_cross_round_identity(
    field: str, value: str, code: str
) -> None:
    card = _card()
    with pytest.raises(S.SameRoundError) as info:
        S.assert_same_round(
            {"expected": _expected([card], **{field: value}), "origin": _origin([card])}
        )
    assert info.value.code == code


def test_assert_same_round_rejects_missing_source_proof() -> None:
    card = _card()
    origin = _origin([card])
    del origin["fields"]["plan_id"]["source"]
    with pytest.raises(S.SameRoundError) as info:
        S.assert_same_round({"expected": _expected([card]), "origin": origin})
    assert info.value.code == "same_round_origin_missing"


def test_assert_same_round_rejects_missing_classifier_proof() -> None:
    card = _card()
    origin = _origin([card])
    del origin["classifier"]["sha256"]
    with pytest.raises(S.SameRoundError) as info:
        S.assert_same_round({"expected": _expected([card]), "origin": origin})
    assert info.value.code == "same_round_origin_missing"


def test_assert_same_round_rejects_missing_case_card_sha() -> None:
    card = _card()
    origin = _origin([card])
    del origin["cards"][0]["sha256"]
    with pytest.raises(S.SameRoundError) as info:
        S.assert_same_round({"expected": _expected([card]), "origin": origin})
    assert info.value.code == "same_round_origin_missing"


def test_origin_record_covers_every_identity_field_with_source() -> None:
    card = _card()
    origin = _origin([card])
    for name in S.ORIGIN_IDENTITY_FIELDS:
        node = origin["fields"][name]
        assert node["value"]
        assert node["source"]["object"]
        assert node["source"]["round"] == "current"
    assert origin["classifier"]["sha256"] == CLASSIFIER_SHA
    assert origin["classifier"]["source"]["round"] == "current"
    assert origin["cards"][0]["source"]["classifier_sha256"] == CLASSIFIER_SHA


def test_assert_same_round_rejects_case_set_problems() -> None:
    a, b = _card(case_id="H2V3-C01"), _card(case_id="H2V3-C02")
    origin = _origin([a, b])
    with pytest.raises(S.SameRoundError) as missing:
        S.assert_same_round({"expected": _expected([a, b, _card(case_id="H2V3-C03")]), "origin": origin})
    assert missing.value.code == "case_set_mismatch"

    duplicated = _origin([a, b])
    duplicated["cards"].append(copy.deepcopy(duplicated["cards"][0]))
    with pytest.raises(S.SameRoundError) as duplicate:
        S.assert_same_round({"expected": _expected([a, b]), "origin": duplicated})
    assert duplicate.value.code == "case_set_mismatch"

    extra_card = _card(case_id="H2V3-C03")
    with pytest.raises(S.SameRoundError) as extra:
        S.assert_same_round(
            {"expected": _expected([a, b]), "origin": _origin([a, b, extra_card])}
        )
    assert extra.value.code == "case_set_mismatch"


def test_assert_same_round_rejects_tampered_card_sha() -> None:
    card = _card()
    expected = _expected([card])
    expected["card_sha256"] = {card.case_id: SHA_B}
    with pytest.raises(S.SameRoundError) as info:
        S.assert_same_round({"expected": expected, "origin": _origin([card])})
    assert info.value.code == "card_sha256_mismatch"


def test_assert_same_round_rejects_binding_without_expected_fields() -> None:
    card = _card()
    expected = _expected([card])
    del expected["run_id"]
    with pytest.raises(S.SameRoundError) as info:
        S.assert_same_round({"expected": expected, "origin": _origin([card])})
    assert info.value.code == "same_round_binding_invalid"


# --------------------------------------------------------------------------- #
# D1/D2：旧 fail / 旧 error 不驱动本轮 verdict；本轮 error 仍拒绝假通过
# --------------------------------------------------------------------------- #


def test_old_fail_does_not_drive_current_verdict() -> None:
    historical = _historical_card("H2V3-C26", quality_status="fail")
    current = _card("H2V3-C26", quality_status="pass")

    historical_result = rescore.rescore_case(_view(historical))
    assert historical_result.new_axes["safety"]["state"] == "violation"
    assert historical_result.safety_provenance == "preserved_old_verdict"

    current_result = rescore.rescore_case(_view(current))
    assert current_result.new_axes["safety"]["state"] == "not_applicable"
    assert current_result.safety_provenance == "rescored"
    # 同一题、同一份 turn 证据：输入卡不同 -> 结论不同，证明旧卡会污染本轮。
    assert (
        historical_result.new_axes["safety"]["state"]
        != current_result.new_axes["safety"]["state"]
    )


def test_old_error_and_missing_evidence_do_not_leak_into_current_state() -> None:
    historical_error = _historical_card(
        "H2V3-C26", quality_status="error", safety=("unknown", "turn_error")
    )
    current = _card("H2V3-C26", quality_status="pass")
    assert rescore.rescore_case(_view(historical_error)).new_axes["safety"]["state"] == "unknown"
    assert rescore.rescore_case(_view(current)).new_axes["safety"]["state"] == "not_applicable"

    historical_incomplete = _historical_card(
        "H2V3-C26",
        quality_status="pass",
        safety=("not_applicable", hard.NA_REASONS["safety"]),
        evidence_complete=False,
        missing_codes=("evidence_incomplete",),
    )
    current_complete = _card("H2V3-C26", quality_status="pass")
    assert (
        rescore.rescore_case(_view(historical_incomplete)).new_axes["safety"]["state"]
        == "unknown"
    )
    assert (
        rescore.rescore_case(_view(current_complete)).new_axes["safety"]["state"]
        == "not_applicable"
    )


def test_current_error_or_missing_evidence_still_refuses_fake_pass() -> None:
    error_card = _card("H2V3-C16", quality_status="error")
    error_result = rescore.rescore_case(_view(error_card))
    assert error_result.new_axes["safety"]["state"] == "unknown"
    assert error_result.new_axes["safety"]["reason"] == "turn_error"

    incomplete_card = _card("H2V3-C16", quality_status="pass", evidence_complete=False)
    incomplete_result = rescore.rescore_case(_view(incomplete_card))
    assert incomplete_result.new_axes["safety"]["state"] == "unknown"
    assert incomplete_result.new_axes["safety"]["reason"] == "evidence_incomplete"

    control = rescore.rescore_case(_view(_card("H2V3-C16", quality_status="pass")))
    assert control.new_axes["safety"]["state"] == "not_applicable"


def test_same_round_card_preserves_non_matcher_violation() -> None:
    """同一轮初判卡的非 matcher violation 仍按冻结合同保留，不被 matcher v2 洗白。"""
    current = _card("H2V3-C26", quality_status="pass", safety=("violation", "security_refusal_missing"))
    result = rescore.rescore_case(_view(current))
    assert result.new_axes["safety"]["state"] == "violation"
    assert result.new_axes["safety"]["reason"] == "security_refusal_missing"
    assert result.safety_provenance == "preserved_old_verdict"
    assert "old_verdict_preserved" in {row.code for row in result.safety_audit}


# --------------------------------------------------------------------------- #
# hard_failed / 聚合一致性（合成）
# --------------------------------------------------------------------------- #


def _axis_reason(name: str, state: str) -> str:
    if state == "passed":
        return hard.PASS_REASONS[name]
    if state == "not_applicable":
        return hard.NA_REASONS[name]
    if state == "unknown":
        return sorted(hard.UNKNOWN_REASONS_BY_AXIS[name])[0]
    return sorted(hard.VIOLATION_REASONS_BY_AXIS[name])[0]


def _axes_row(state: str = "passed", *, axis: str = "safety") -> dict[str, dict[str, str]]:
    row = {
        name: {"state": "passed", "reason": hard.PASS_REASONS[name]} for name in hard.AXES
    }
    row[axis] = {"state": state, "reason": _axis_reason(axis, state)}
    return row


def _case_row(
    case_id: str = "H2V3-C02",
    *,
    state: str = "passed",
    axis: str = "safety",
    quality: str = "pass",
    hard_failed: bool | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "case_id": case_id,
        "quality_status": quality,
        "new_axes": _axes_row(state, axis=axis),
    }
    if hard_failed is not None:
        row["hard_failed"] = hard_failed
    return row


def _counts(rows: list[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for name in hard.AXES:
        counter = Counter(str(row["new_axes"][name]["state"]) for row in rows)
        out[name] = {
            "planned": len(rows),
            "passed": counter.get("passed", 0),
            "not_applicable": counter.get("not_applicable", 0),
            "unknown": counter.get("unknown", 0),
            "violations": counter.get("violation", 0),
            "checked": len(rows) - counter.get("unknown", 0),
        }
    return out


def _aggregate(rows: list[Mapping[str, Any]], **overrides: Any) -> dict[str, Any]:
    hard_ids = sorted(
        str(row["case_id"])
        for row in rows
        if any(str(row["new_axes"][name]["state"]) == "violation" for name in hard.AXES)
    )
    unknown_ids = sorted(
        str(row["case_id"])
        for row in rows
        if any(str(row["new_axes"][name]["state"]) == "unknown" for name in hard.AXES)
    )
    aggregate = {
        "case_count": len(rows),
        "new_axes": _counts(rows),
        "hard_failures": hard_ids,
        "unknown_cases": unknown_ids,
    }
    aggregate.update(overrides)
    return aggregate


def test_derive_hard_failed_unions_violation_axes() -> None:
    rows = [
        _case_row("H2V3-C02", state="violation", axis="cross_entity", hard_failed=True),
        _case_row("H2V3-C12"),
    ]
    assert S.derive_hard_failed(rows, _aggregate(rows)) == {"H2V3-C02"}


def test_derive_hard_failed_unions_multiple_axes_once() -> None:
    row = _case_row("H2V3-C26", hard_failed=True)
    row["new_axes"]["safety"] = {
        "state": "violation",
        "reason": sorted(hard.VIOLATION_REASONS_BY_AXIS["safety"])[0],
    }
    row["new_axes"]["stale_source"] = {
        "state": "violation",
        "reason": sorted(hard.VIOLATION_REASONS_BY_AXIS["stale_source"])[0],
    }
    assert S.derive_hard_failed([row], _aggregate([row])) == {"H2V3-C26"}


def test_derive_hard_failed_rejects_false_flag() -> None:
    rows = [_case_row("H2V3-C02", state="violation", hard_failed=False)]
    with pytest.raises(S.SameRoundError) as info:
        S.derive_hard_failed(rows, _aggregate(rows))
    assert info.value.code == "hard_failed_flag_mismatch"


def test_derive_hard_failed_allows_legit_empty_set() -> None:
    rows = [_case_row("H2V3-C01"), _case_row("H2V3-C02", state="not_applicable")]
    assert S.derive_hard_failed(rows, _aggregate(rows)) == set()


def test_derive_hard_failed_rejects_extra_or_missing_hard_case() -> None:
    rows = [_case_row("H2V3-C02", state="violation", hard_failed=True)]
    aggregate = _aggregate(rows)
    aggregate["hard_failures"] = ["H2V3-C02", "H2V3-C99"]
    with pytest.raises(S.SameRoundError) as extra:
        S.derive_hard_failed(rows, aggregate)
    assert extra.value.code == "hard_failures_mismatch"

    aggregate = _aggregate(rows)
    aggregate["hard_failures"] = []
    with pytest.raises(S.SameRoundError) as missing:
        S.derive_hard_failed(rows, aggregate)
    assert missing.value.code == "hard_failures_mismatch"


def test_derive_hard_failed_rejects_duplicate_case() -> None:
    rows = [_case_row("H2V3-C02"), _case_row("H2V3-C02")]
    with pytest.raises(S.SameRoundError) as info:
        S.derive_hard_failed(rows, _aggregate(rows))
    assert info.value.code == "consistency_duplicate_case"


def test_derive_hard_failed_requires_aggregate_and_axis_fields() -> None:
    rows = [_case_row()]
    with pytest.raises(S.SameRoundError) as missing:
        S.derive_hard_failed(rows, None)  # type: ignore[arg-type]
    assert missing.value.code == "consistency_missing_field"

    aggregate = _aggregate(rows)
    del aggregate["new_axes"]
    with pytest.raises(S.SameRoundError) as no_axes:
        S.derive_hard_failed(rows, aggregate)
    assert no_axes.value.code == "consistency_missing_field"

    broken = [_case_row()]
    del broken[0]["new_axes"]["safety"]
    with pytest.raises(S.SameRoundError) as no_axis:
        S.derive_hard_failed(broken, _aggregate([_case_row()]))
    assert no_axis.value.code == "consistency_missing_field"


def test_derive_hard_failed_rejects_case_count_and_axis_count_mismatch() -> None:
    rows = [_case_row()]
    aggregate = _aggregate(rows)
    aggregate["case_count"] = 2
    with pytest.raises(S.SameRoundError) as count:
        S.derive_hard_failed(rows, aggregate)
    assert count.value.code == "case_coverage_mismatch"

    aggregate = _aggregate(rows)
    aggregate["new_axes"]["safety"]["planned"] = 2
    with pytest.raises(S.SameRoundError) as planned:
        S.derive_hard_failed(rows, aggregate)
    assert planned.value.code == "axis_planned_mismatch"

    aggregate = _aggregate(rows)
    aggregate["new_axes"]["safety"]["passed"] = 0
    aggregate["new_axes"]["safety"]["violations"] = 1
    with pytest.raises(S.SameRoundError) as violations:
        S.derive_hard_failed(rows, aggregate)
    assert violations.value.code == "axis_violations_mismatch"


# --------------------------------------------------------------------------- #
# §5 check_consistency：覆盖 / 质量总和 / flags / 四态 / unknown
# --------------------------------------------------------------------------- #


def _run_payload(
    run_index: int,
    rows: list[Mapping[str, Any]],
    *,
    quality: Mapping[str, int] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    counts = Counter(str(row["quality_status"]) for row in rows)
    payload: dict[str, Any] = {
        "run_index": run_index,
        "case_count": len(rows),
        "case_ids": [str(row["case_id"]) for row in rows],
        "quality": {
            status: int((quality or {}).get(status, counts.get(status, 0)))
            for status in S.QUALITY_STATUSES
        },
        "cases": list(rows),
        "new_axes": _counts(rows),
        "hard_failures": _aggregate(rows)["hard_failures"],
        "unknown_cases": _aggregate(rows)["unknown_cases"],
    }
    payload.update(overrides)
    return payload


def _payload(runs: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    all_rows = [row for run in runs for row in run["cases"]]
    aggregate = _aggregate(all_rows)
    aggregate.update(overrides)
    return {"runs": runs, "aggregate": aggregate}


def test_check_consistency_accepts_well_formed_payload() -> None:
    runs = [
        _run_payload(0, [_case_row("H2V3-C01"), _case_row("H2V3-C02", state="unknown")]),
        _run_payload(1, [_case_row("H2V3-C21", state="violation", hard_failed=True)]),
    ]
    assert S.check_consistency(_payload(runs)) is None


def test_check_consistency_rejects_duplicate_or_missing_case() -> None:
    runs = [_run_payload(0, [_case_row("H2V3-C01")])]
    duplicated = [_run_payload(0, [_case_row("H2V3-C01")]), _run_payload(1, [_case_row("H2V3-C01")])]
    with pytest.raises(S.SameRoundError) as duplicate:
        S.check_consistency(_payload(duplicated))
    assert duplicate.value.code == "consistency_duplicate_case"

    with pytest.raises(S.SameRoundError) as coverage:
        S.check_consistency(_payload(runs, case_count=2))
    assert coverage.value.code == "case_coverage_mismatch"

    bad_run = _run_payload(0, [_case_row("H2V3-C01")], case_count=2)
    with pytest.raises(S.SameRoundError) as run_coverage:
        S.check_consistency(_payload([bad_run]))
    assert run_coverage.value.code == "case_coverage_mismatch"


def test_check_consistency_rejects_run_quality_mismatch() -> None:
    run = _run_payload(0, [_case_row("H2V3-C01"), _case_row("H2V3-C02", quality="fail")])
    run["quality"] = {"pass": 2, "fail": 0, "error": 0, "not_executed": 0}
    with pytest.raises(S.SameRoundError) as info:
        S.check_consistency(_payload([run]))
    assert info.value.code == "run_quality_mismatch"


def test_check_consistency_rejects_hard_failed_flag_and_run_list() -> None:
    row = _case_row("H2V3-C02", state="violation", hard_failed=False)
    run = _run_payload(0, [row])
    with pytest.raises(S.SameRoundError) as flag:
        S.check_consistency(_payload([run]))
    assert flag.value.code == "hard_failed_flag_mismatch"

    run = _run_payload(0, [_case_row("H2V3-C02", state="violation", hard_failed=True)])
    run["hard_failures"] = []
    with pytest.raises(S.SameRoundError) as run_hard:
        S.check_consistency(_payload([run]))
    assert run_hard.value.code == "hard_failures_mismatch"


def test_check_consistency_rejects_hidden_unknown() -> None:
    rows = [_case_row("H2V3-C02", state="unknown")]
    runs = [_run_payload(0, rows)]
    with pytest.raises(S.SameRoundError) as hidden:
        S.check_consistency(_payload(runs, unknown_cases=[]))
    assert hidden.value.code == "unknown_hidden"

    with pytest.raises(S.SameRoundError) as extra:
        S.check_consistency(_payload(runs, unknown_cases=["H2V3-C02", "H2V3-C99"]))
    assert extra.value.code == "unknown_hidden"

    run = _run_payload(0, rows)
    run["unknown_cases"] = []
    with pytest.raises(S.SameRoundError) as run_hidden:
        S.check_consistency(_payload([run]))
    assert run_hidden.value.code == "unknown_hidden"


def test_check_consistency_rejects_axis_count_mismatch() -> None:
    run = _run_payload(0, [_case_row("H2V3-C01")])
    run["new_axes"]["safety"]["passed"] = 0
    with pytest.raises(S.SameRoundError) as info:
        S.check_consistency(_payload([run]))
    assert info.value.code == "axis_counts_mismatch"


def test_check_consistency_requires_aggregate() -> None:
    runs = [_run_payload(0, [_case_row("H2V3-C01")])]
    with pytest.raises(S.SameRoundError) as info:
        S.check_consistency({"runs": runs})
    assert info.value.code == "consistency_missing_field"


def test_check_consistency_ignores_historical_comparison_fields() -> None:
    """历史对照字段即使自相矛盾也不得影响本轮门状态。"""
    runs = [_run_payload(0, [_case_row("H2V3-C01")])]
    payload = _payload(runs)
    payload["aggregate"]["historical_hard_failures"] = ["H2V3-C99"]
    payload["aggregate"]["historical_unknown_cases"] = ["H2V3-C99"]
    payload["runs"][0]["historical_hard_failures"] = ["H2V3-C99"]
    assert S.check_consistency(payload) is None


# --------------------------------------------------------------------------- #
# D3：quality 聚合的 hard_failed 必须由逐题 axes 派生
# --------------------------------------------------------------------------- #


def _axes_payload(run_index: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "runs": [
            {
                "run_index": run_index,
                "scenario_id": "run0-base_b0",
                "business_date": "2026-11-16",
                "case_count": len(rows),
                "cases": rows,
            }
        ],
        "aggregate": _aggregate(rows),
    }


def _case_plan(rows: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "cases": [
            {
                "case_id": case_id,
                "quality_status": quality,
                "turns": [{"turn_index": 0, "status": "executed"}],
            }
            for case_id, quality in rows
        ]
    }


def test_quality_hard_failed_derives_from_axes_not_missing_top_level_field() -> None:
    rows = [
        _case_row("H2V3-C01", quality="pass"),
        _case_row("H2V3-C02", state="violation", axis="cross_entity", quality="fail"),
    ]
    axes_payload = _axes_payload(0, rows)
    # 旧 D3 公式：读顶层 new_hard_failures（字段不存在）-> 全部 false。
    old_formula = {
        row["case_id"].split("-")[-1]
        for row in rows
        if row["case_id"].split("-")[-1] in axes_payload.get("new_hard_failures", [])
    }
    assert old_formula == set()

    quality = S.build_quality_payload(
        axes_payload,
        {0: _case_plan([("H2V3-C01", "pass"), ("H2V3-C02", "fail")])},
    )
    flags = {row["case_id"]: row["hard_failed"] for row in quality["cases"]}
    assert flags == {"H2V3-C01": False, "H2V3-C02": True}
    assert quality["totals"]["hard_failures"] == 1
    assert quality["runs"][0]["hard_failures"] == ["H2V3-C02"]


def test_quality_requires_matching_quality_status_between_axes_and_case_plan() -> None:
    rows = [_case_row("H2V3-C02", quality="fail")]
    with pytest.raises(S.SameRoundError) as info:
        S.build_quality_payload(
            _axes_payload(0, rows), {0: _case_plan([("H2V3-C02", "pass")])}
        )
    assert info.value.code == "quality_axes_mismatch"


def test_quality_requires_exact_case_plan_set() -> None:
    rows = [_case_row("H2V3-C02")]
    with pytest.raises(S.SameRoundError) as info:
        S.build_quality_payload(
            _axes_payload(0, rows), {0: _case_plan([("H2V3-C99", "pass")])}
        )
    assert info.value.code == "quality_case_set_mismatch"


def test_quality_allows_legit_empty_hard_set() -> None:
    rows = [_case_row("H2V3-C01"), _case_row("H2V3-C02", state="not_applicable")]
    quality = S.build_quality_payload(
        _axes_payload(0, rows),
        {0: _case_plan([("H2V3-C01", "pass"), ("H2V3-C02", "pass")])},
    )
    assert quality["totals"]["hard_failures"] == 0
    assert all(row["hard_failed"] is False for row in quality["cases"])
