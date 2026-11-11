"""P2-T205：确定性评分与公开分母（离线，零真实调用）。

锁定任务书 T205 第一条：

- 40 题 / 精确 Q01-Q24 24/24 / N01-N08 / C01-C06 / U01-U10 的分母口径；
- OCR 题不得静默跳过并算通过；
- error / 未执行不得进入正确答案数；
- H2 只聚合（无 case_id / 题干），硬失败与阈值分开判。

全部用小型人工可手算样本（不需要产品、索引、模型、网络）。
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.gold import ResolvedGold
from mktkb.evaluation.p2_public_cases import load_b0_cases
from mktkb.evaluation.p2_scoring import (
    P2_B0_EXACT_IDS,
    P2_B0_EXACT_TOTAL,
    P2_B0_IDS,
    P2_B0_MIN_PASS,
    P2_B0_OCR_IDS,
    P2_B0_OCR_TOTAL,
    P2_B0_TOTAL,
    P2_BOUNDARY_IDS,
    P2_BOUNDARY_TOTAL,
    P2_HOLDOUT_HARD_FAILURE_KINDS,
    P2_HOLDOUT_MIN_PASS,
    P2_HOLDOUT_STRATA,
    P2_HOLDOUT_TOTAL,
    P2_NEGATIVE_IDS,
    P2_NEGATIVE_TOTAL,
    P2_UPDATE_DELETE_IDS,
    P2_UPDATE_DELETE_TOTAL,
    CASE_STATUS_ERROR,
    CASE_STATUS_FAIL,
    CASE_STATUS_NOT_EXECUTED,
    CASE_STATUS_PASS,
    CASE_STATUS_SKIPPED_OCR,
    EXECUTION_MODE_LIVE,
    EXECUTION_MODE_LOCAL_MOCK,
    P2CaseScore,
    P2ScoredCase,
    P2HoldoutCaseScore,
    P2HoldoutScorecard,
    P2ScoringError,
    SEVERITY_HARD,
    SEVERITY_UNKNOWN,
    P2_BINDING_VERSION,
    aggregate_holdout,
    binding_config_hash,
    check_scenario_isolation,
    check_source_isolation,
    citation_evidence_status,
    evaluate_p2_gate,
    load_p2_gate_config,
    normalize_product_outcome,
    score_public_case,
    score_public_suites,
)
from mktkb.evaluation.scorers import EvalOutcome, check_value, score_case

UNIT_KEY = "sheet:物品位置:row:8"
UNIT_ID = "11111111-1111-4111-8111-111111111111"
DOC_NAME = "D01_物品位置表.xlsx"

DOCUMENT_CODES = {DOC_NAME: "D01"}
SOURCE_INDEX = {UNIT_ID: {"doc_code": "D01", "unit_key": UNIT_KEY, "locator": {}}}


def make_case(
    case_id: str = "Q01",
    *,
    suite: str = "b0",
    stratum: str = "exact",
    expected_values: tuple[str, ...] = ("B区1号货架第二层",),
    expected_kind: str = "answer",
    should_refuse: bool = False,
    requires_ocr: bool = False,
    turns: tuple[dict, ...] = (),
) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        suite=suite,
        split="dev",
        stratum=stratum,
        business_date="2026-10-28",
        question="城东店的宣传海报在哪里？",
        turns=turns,
        expected_kind=expected_kind,
        expected_values=expected_values,
        expected_sources=({"doc_code": "D01", "unit_key": UNIT_KEY},),
        labeler="lead",
        label_version="dev-1",
        should_refuse=should_refuse,
        requires_ocr=requires_ocr,
    )


def product(
    *,
    text: str = "城东店的宣传海报位于 B区1号货架第二层。",
    kind: str = "answer",
    trace_id: str = "trace-1",
    path: str = "legacy",
    sources: tuple[dict, ...] | None = None,
) -> dict:
    if sources is None:
        sources = (
            {
                "source_id": UNIT_ID,
                "document_name": DOC_NAME,
                "version_number": 1,
                "status": "active",
                "locator": {"sheet": "物品位置", "row": 8},
            },
        )
    return {
        "kind": kind,
        "text": text,
        "trace_id": trace_id,
        "trace_path": path,
        "sources": [dict(item) for item in sources],
        "http_status": 200,
    }


def turn_row(payload: dict, *, turn: int = 1, status: str = "ok") -> dict:
    return {"turn": turn, "status": status, "error_code": None, "product": payload}


def case_row(case: CaseSpec, turns: list[dict], *, conversation: str = "conv-1", status: str = "ok") -> dict:
    return {
        "case_id": case.case_id,
        "suite": case.suite,
        "stratum": case.stratum,
        "conversation_id": conversation,
        "status": status,
        "error_code": None,
        "planned_turns": max(1, len(case.turns)),
        "turns_executed": len(turns),
        "turns": turns,
    }


def score(
    case: CaseSpec,
    *,
    status: str = CASE_STATUS_PASS,
    requires_ocr: bool | None = None,
) -> P2CaseScore:
    return P2CaseScore(
        case_id=case.case_id,
        suite=case.suite,
        stratum=case.stratum,
        status=status,
        requires_ocr=bool(case.requires_ocr if requires_ocr is None else requires_ocr),
        planned_turns=1,
        executed_turns=0 if status == CASE_STATUS_NOT_EXECUTED else 1,
    )


def full_scores(*, b0_fail: tuple[str, ...] = (), extra: dict[str, str] | None = None) -> list[P2CaseScore]:
    """40 + 8 + 6 + 10 的全通过样本；b0_fail 指定要改成 fail 的 case。"""
    scores: list[P2CaseScore] = []
    for case_id in P2_B0_IDS:
        case = make_case(case_id, requires_ocr=case_id in P2_B0_OCR_IDS, stratum="ocr" if case_id in P2_B0_OCR_IDS else "exact")
        status = CASE_STATUS_FAIL if case_id in b0_fail else CASE_STATUS_PASS
        scores.append(score(case, status=status))
    for case_id in P2_NEGATIVE_IDS:
        scores.append(score(make_case(case_id, suite="badcase", stratum="negative", expected_kind="not_found", should_refuse=True)))
    for case_id in P2_BOUNDARY_IDS:
        scores.append(score(make_case(case_id, suite="boundary", stratum="conflict", expected_kind="clarification")))
    for case_id in P2_UPDATE_DELETE_IDS:
        scores.append(score(make_case(case_id, suite="update_delete", stratum="mutation")))
    if extra:
        for case_id, status in extra.items():
            scores.append(
                P2CaseScore(
                    case_id=case_id,
                    suite="b0",
                    stratum="exact",
                    status=status,
                    requires_ocr=False,
                    planned_turns=1,
                    executed_turns=0,
                )
            )
    return scores


# --------------------------------------------------------------------------- #
# 1. 分母冻结 + 手算通过数
# --------------------------------------------------------------------------- #


def test_frozen_denominators_match_acceptance_matrix() -> None:
    assert P2_B0_TOTAL == 40 and len(P2_B0_IDS) == 40
    assert P2_B0_EXACT_TOTAL == 24 and P2_B0_EXACT_IDS == tuple(f"Q{index:02d}" for index in range(1, 25))
    assert P2_B0_OCR_TOTAL == 8 and P2_B0_OCR_IDS == ("Q33", "Q34", "Q35", "Q36", "Q37", "Q38", "Q39", "Q40")
    assert P2_NEGATIVE_TOTAL == 8 and P2_BOUNDARY_TOTAL == 6 and P2_UPDATE_DELETE_TOTAL == 10
    assert P2_HOLDOUT_TOTAL == 30 and P2_HOLDOUT_MIN_PASS == 24
    assert P2_HOLDOUT_STRATA == {"paraphrase": 10, "multi_turn": 5, "negative": 5, "stale_conflict": 5, "cross_doc_security": 5}
    assert P2_B0_MIN_PASS == 36


def test_public_scorecard_hand_counts() -> None:
    card = score_public_suites(full_scores())
    assert card.release_ready is True
    b0 = card.suites["b0"]
    assert (b0.planned, b0.executed, b0.passed, b0.failed) == (40, 40, 40, 0)
    assert (b0.exact_planned, b0.exact_passed) == (24, 24)
    assert (b0.ocr_planned, b0.ocr_executed, b0.ocr_passed) == (8, 8, 8)
    assert card.suites["negative"].passed == 8
    assert card.suites["boundary"].passed == 6
    assert card.suites["update_delete"].passed == 10
    assert card.blocks == ()

    # 4 道 text 题失败：40 题里 36 通过 → 仍然满足 B0≥36/40，且不碰精确 24/24。
    card = score_public_suites(full_scores(b0_fail=("Q25", "Q26", "Q27", "Q28")))
    b0 = card.suites["b0"]
    assert (b0.passed, b0.failed) == (36, 4)
    assert b0.required_passed is True
    assert card.release_ready is True


def test_ocr_rows_cannot_be_silently_skipped() -> None:
    scores = full_scores()
    skipped = [item for item in scores if item.case_id == "Q33"][0]
    scores[scores.index(skipped)] = P2CaseScore(
        case_id="Q33",
        suite="b0",
        stratum="ocr",
        status=CASE_STATUS_SKIPPED_OCR,
        requires_ocr=True,
        planned_turns=1,
        executed_turns=1,
    )
    card = score_public_suites(scores)
    assert card.release_ready is False
    codes = {block.code for block in card.blocks}
    assert "ocr_not_executed" in codes
    assert "case_error" in codes
    b0 = card.suites["b0"]
    assert b0.passed == 39  # 跳过不等于通过，也不计入正确数
    assert b0.ocr_executed == 7


def test_error_and_not_executed_do_not_count_as_correct() -> None:
    scores = full_scores()
    for case_id, status in (("Q30", CASE_STATUS_ERROR), ("Q29", CASE_STATUS_NOT_EXECUTED)):
        index = [item.case_id for item in scores].index(case_id)
        case = make_case(case_id, stratum="text")
        scores[index] = score(case, status=status)
    card = score_public_suites(scores)
    b0 = card.suites["b0"]
    assert (b0.passed, b0.errors, b0.not_executed) == (38, 1, 1)
    assert b0.executed == 38
    codes = [block.code for block in card.blocks]
    assert "case_error" in codes and "case_not_executed" in codes
    assert card.release_ready is False


def test_missing_case_keeps_denominator_and_blocks() -> None:
    scores = [item for item in full_scores() if item.case_id != "Q40"]
    card = score_public_suites(scores)
    b0 = card.suites["b0"]
    assert b0.planned == 40 and b0.executed == 39
    codes = {block.code for block in card.blocks}
    assert "missing_case" in codes
    assert card.release_ready is False


def test_exact_miss_is_hard_block_even_if_total_pass() -> None:
    scores = full_scores(b0_fail=("Q05",))
    card = score_public_suites(scores)
    assert card.suites["b0"].passed == 39
    hard = [block for block in card.blocks if block.code == "exact_below_24_of_24"]
    assert hard and hard[0].severity == SEVERITY_HARD
    assert card.release_ready is False


def test_unexpected_case_blocks() -> None:
    scores = full_scores()
    scores.append(
        P2CaseScore(
            case_id="Q99",
            suite="b0",
            stratum="exact",
            status=CASE_STATUS_PASS,
            requires_ocr=False,
            planned_turns=1,
            executed_turns=1,
        )
    )
    card = score_public_suites(scores)
    assert "unexpected_case" in {block.code for block in card.blocks}
    assert card.release_ready is False


# --------------------------------------------------------------------------- #
# 2. 产品响应规范化
# --------------------------------------------------------------------------- #


def test_normalize_product_outcome_is_unit_level_and_keeps_pagination() -> None:
    payload = turn_row(product(text="B区1号货架第二层"))
    payload["pagination"] = {"total": 3, "returned": 1, "has_more": True, "next_page": 2}
    outcome = normalize_product_outcome(
        payload, document_codes=DOCUMENT_CODES, source_index=SOURCE_INDEX
    )
    assert outcome.kind == "answer"
    assert outcome.text == "B区1号货架第二层"
    assert outcome.trace_id == "trace-1" and outcome.path == "legacy"
    assert len(outcome.citations) == 1
    citation = outcome.citations[0]
    assert citation.doc_code == "D01"
    assert citation.unit_key == UNIT_KEY
    assert citation.unit_ids == (UNIT_ID,)
    assert outcome.pagination["total"] == 3


def test_normalize_product_outcome_fails_closed_on_identity_gaps() -> None:
    with pytest.raises(P2ScoringError) as excinfo:
        normalize_product_outcome(
            turn_row(product(sources=({"source_id": "x", "document_name": "未登记.docx"},))),
            document_codes=DOCUMENT_CODES,
        )
    assert excinfo.value.code == "source_document_unmapped"

    bad_kind = turn_row(product())
    bad_kind["product"]["kind"] = ""
    with pytest.raises(P2ScoringError) as excinfo:
        normalize_product_outcome(bad_kind, document_codes=DOCUMENT_CODES)
    assert excinfo.value.code == "product_kind_missing"

    with pytest.raises(P2ScoringError) as excinfo:
        normalize_product_outcome({"turn": 1, "status": "ok"}, document_codes=DOCUMENT_CODES)
    assert excinfo.value.code == "product_missing"


def test_source_isolation_flags_foreign_and_stale_sources() -> None:
    outcome = normalize_product_outcome(
        turn_row(product(text="B区1号货架第二层")),
        document_codes=DOCUMENT_CODES,
        source_index=SOURCE_INDEX,
    )
    assert check_source_isolation(outcome.citations, allowed_doc_codes={"D01"}) == ()

    foreign = check_source_isolation(outcome.citations, allowed_doc_codes={"D02"})
    assert [item.code for item in foreign] == ["source_outside_run"]

    stale = normalize_product_outcome(
        turn_row(
            product(
                sources=(
                    {
                        "source_id": UNIT_ID,
                        "document_name": DOC_NAME,
                        "version_number": 1,
                        "status": "superseded",
                        "locator": {"sheet": "物品位置", "row": 8},
                    },
                )
            )
        ),
        document_codes=DOCUMENT_CODES,
        source_index=SOURCE_INDEX,
    )
    assert [item.code for item in check_source_isolation(stale.citations)] == ["source_not_active"]
    forbidden = check_source_isolation(
        outcome.citations, allowed_doc_codes={"D01"}, forbidden_doc_codes={"D01"}
    )
    assert [item.code for item in forbidden] == ["source_forbidden_document"]


def test_scenario_isolation_flags_shared_conversation_and_turn_gaps() -> None:
    rows = [
        case_row(make_case("Q01"), [turn_row(product())], conversation="conv-1"),
        case_row(make_case("Q02"), [turn_row(product())], conversation="conv-1"),
    ]
    codes = [item.code for item in check_scenario_isolation(rows)]
    assert "scenario_conversation_shared" in codes

    multi = make_case("Q03", turns=({"question": "第一轮"}, {"question": "第二轮"}))
    rows = [case_row(multi, [turn_row(product(), turn=2)], conversation="conv-3")]
    assert "turn_sequence_gap" in [item.code for item in check_scenario_isolation(rows)]

    rows = [case_row(multi, [turn_row(product()), turn_row(product(), turn=2)], conversation=None)]
    assert "scenario_conversation_missing" in [item.code for item in check_scenario_isolation(rows)]


# --------------------------------------------------------------------------- #
# 3. 逐题打分：OCR 不跳过、多轮只按末轮、中间轮 error
# --------------------------------------------------------------------------- #


def test_ocr_case_is_scored_not_skipped() -> None:
    case = make_case("Q33", stratum="ocr", requires_ocr=True)
    wrong = case_row(case, [turn_row(product(text="市场部"))])
    scored = score_public_case(
        case,
        wrong,
        document_codes=DOCUMENT_CODES,
        source_index=SOURCE_INDEX,
        allowed_doc_codes={"D01"},
    )
    # 期望值不匹配 → fail，而不是 skipped_requires_ocr
    assert scored.score.status == CASE_STATUS_FAIL
    assert scored.result is not None and scored.result.status == "fail"
    assert any(
        check["check_id"] == "value_hit" and check["status"] == "fail"
        for check in scored.score.checks
    )

    right = case_row(case, [turn_row(product(text="B区1号货架第二层"))])
    scored = score_public_case(
        case,
        right,
        document_codes=DOCUMENT_CODES,
        source_index=SOURCE_INDEX,
        allowed_doc_codes={"D01"},
    )
    assert scored.score.status == CASE_STATUS_PASS


def test_multi_turn_scores_final_turn_only() -> None:
    case = make_case(
        "U02",
        suite="update_delete",
        stratum="mutation",
        expected_values=("D区暂存柜",),
        turns=({"question": "P01 在哪？"}, {"question": "发布后在哪？"}),
    )
    turns = [
        turn_row(product(text="B区1号货架第二层"), turn=1),
        turn_row(product(text="D区暂存柜，来源新版"), turn=2),
    ]
    scored = score_public_case(
        case,
        case_row(case, turns, conversation="conv-9"),
        document_codes=DOCUMENT_CODES,
        source_index=SOURCE_INDEX,
        allowed_doc_codes={"D01"},
    )
    assert scored.score.status == CASE_STATUS_PASS
    assert scored.score.turn_kinds == ("answer", "answer")

    # 中间轮 error → 整题 error（不能拿末轮凑正确）
    failed_middle = [
        turn_row(product(text="B区1号货架第二层"), turn=1, status="error"),
        turn_row(product(text="D区暂存柜"), turn=2),
    ]
    scored = score_public_case(
        case,
        case_row(case, failed_middle, conversation="conv-9"),
        document_codes=DOCUMENT_CODES,
        source_index=SOURCE_INDEX,
    )
    assert scored.score.status == CASE_STATUS_ERROR
    assert scored.score.issues[0].code == "turn_error"


def test_case_not_executed_and_ocr_not_executed_are_distinct() -> None:
    plain = make_case("Q10")
    scored = score_public_case(plain, None, document_codes=DOCUMENT_CODES)
    assert scored.score.status == CASE_STATUS_NOT_EXECUTED
    assert scored.score.issues[0].code == "case_not_executed"

    ocr = make_case("Q35", stratum="ocr", requires_ocr=True)
    scored = score_public_case(ocr, case_row(ocr, []), document_codes=DOCUMENT_CODES)
    assert scored.score.status == CASE_STATUS_NOT_EXECUTED
    assert scored.score.issues[0].code == "ocr_not_executed"


# --------------------------------------------------------------------------- #
# 4. H2：只聚合、硬失败、样本/分层/error
# --------------------------------------------------------------------------- #


def holdout_scores(
    *,
    passed: int = 24,
    hard: dict[str, str] | None = None,
    errors: int = 0,
) -> list[P2HoldoutCaseScore]:
    scores: list[P2HoldoutCaseScore] = []
    strata = [name for name, count in P2_HOLDOUT_STRATA.items() for _ in range(count)]
    assert len(strata) == P2_HOLDOUT_TOTAL
    for index, stratum in enumerate(strata):
        if index < passed:
            status = CASE_STATUS_PASS
        elif index < passed + errors:
            status = CASE_STATUS_ERROR
        else:
            status = CASE_STATUS_FAIL
        hard_kind = (hard or {}).get(f"H2-{index:02d}")
        scores.append(
            P2HoldoutCaseScore(
                case_id=f"H2-{index:02d}", stratum=stratum, status=status, hard_failure=hard_kind
            )
        )
    return scores


def test_holdout_aggregate_only_and_threshold() -> None:
    card = aggregate_holdout(holdout_scores(), thresholds_approved=False)
    assert (card.total, card.executed, card.passed, card.failed) == (30, 30, 24, 6)
    assert card.threshold_met is True
    assert card.hard_failures == 0
    assert card.release_ready is False  # 阈值未审批 → unknown
    codes = [block.code for block in card.blocks]
    assert codes == ["holdout_threshold_unapproved"]

    payload = card.to_dict()
    assert payload["detail_export"] is False
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "H2-" not in encoded
    assert "case_id" not in encoded
    assert "question" not in encoded


def test_holdout_hard_failure_is_hard_block() -> None:
    card = aggregate_holdout(
        holdout_scores(hard={"H2-28": "safety"}), thresholds_approved=True
    )
    assert card.hard_failures == 1
    assert card.hard_failures_by_kind["safety"] == 1
    hard = [block for block in card.blocks if block.code == "holdout_hard_failure"]
    assert hard and hard[0].severity == SEVERITY_HARD
    assert card.release_ready is False
    assert P2_HOLDOUT_HARD_FAILURE_KINDS == ("safety", "cross_user", "cross_entity", "stale_source")


def test_holdout_error_and_sample_mismatch_block() -> None:
    card = aggregate_holdout(holdout_scores(passed=24, errors=6), thresholds_approved=True)
    assert card.errors == 6
    codes = {block.code for block in card.blocks}
    assert "holdout_case_error" in codes
    assert card.passed == 24  # error 不计入正确数，也不冒充通过
    assert card.release_ready is False

    short = aggregate_holdout(holdout_scores()[:29], thresholds_approved=True)
    assert "holdout_sample_missing" in {block.code for block in short.blocks}

    wrong_strata = holdout_scores()
    wrong_strata[0] = P2HoldoutCaseScore(
        case_id="H2-00", stratum="multi_turn", status=CASE_STATUS_PASS
    )
    card = aggregate_holdout(wrong_strata, thresholds_approved=True)
    assert "holdout_strata_mismatch" in {block.code for block in card.blocks}


def test_holdout_rejects_detail_payload() -> None:
    card = aggregate_holdout(holdout_scores(), thresholds_approved=True)
    leaky = P2HoldoutScorecard(
        total=card.total,
        executed=card.executed,
        errors=card.errors,
        passed=card.passed,
        failed=card.failed,
        hard_failures=card.hard_failures,
        hard_failures_by_kind=card.hard_failures_by_kind,
        by_stratum={"paraphrase": {"total": 1}, "case_id": {"total": 0}},  # 故意泄漏明细字段
        min_pass=card.min_pass,
        hard_failures_max=card.hard_failures_max,
        thresholds_approved=True,
    )
    with pytest.raises(P2ScoringError) as excinfo:
        leaky.to_dict()
    assert excinfo.value.code == "holdout_detail_leak"


# --------------------------------------------------------------------------- #
# 5. C1：执行模式 / 真实调用标记（验收 2b 项）
# --------------------------------------------------------------------------- #


def test_case_score_defaults_to_local_mock_and_live_must_be_explicit() -> None:
    """默认保守记 local_mock/0；要标 live 必须显式传，且 mock 上不许有真实调用。"""
    default = score(make_case("Q01"))
    assert (default.execution_mode, default.real_calls) == (EXECUTION_MODE_LOCAL_MOCK, 0)
    payload = default.to_dict()
    assert payload["execution_mode"] == "local_mock" and payload["real_calls"] == 0

    live = replace(score(make_case("Q01")), execution_mode=EXECUTION_MODE_LIVE, real_calls=3)
    assert (live.execution_mode, live.real_calls) == ("live", 3)
    assert live.to_dict()["real_calls"] == 3

    # 1) mock 链上声称真实调用 = 谎报，直接拒绝
    with pytest.raises(P2ScoringError) as excinfo:
        replace(default, real_calls=1)
    assert excinfo.value.code == "real_calls_without_live_mode"
    # 2) 拼错的模式名不猜、不兜底
    with pytest.raises(P2ScoringError) as excinfo:
        replace(default, execution_mode="real")
    assert excinfo.value.code == "execution_mode_invalid"
    # 3) 负数调用数同样拒绝
    with pytest.raises(P2ScoringError) as excinfo:
        replace(default, execution_mode=EXECUTION_MODE_LIVE, real_calls=-1)
    assert excinfo.value.code == "real_calls_invalid"


def test_public_scorecard_derives_execution_mark_and_rejects_mixed_modes() -> None:
    card = score_public_suites(full_scores(), run_id="p2run-mock")
    assert (card.execution_mode, card.real_calls, card.run_id) == ("local_mock", 0, "p2run-mock")
    payload = card.to_dict()
    assert payload["execution_mode"] == "local_mock" and payload["run_id"] == "p2run-mock"

    live_scores = [
        replace(item, execution_mode=EXECUTION_MODE_LIVE, real_calls=1)
        for item in full_scores()
    ]
    live_card = score_public_suites(live_scores, run_id="p2run-live")
    assert live_card.execution_mode == "live"
    assert live_card.real_calls == sum(item.real_calls for item in live_scores)
    assert live_card.real_calls > 0

    mixed = [replace(live_scores[0], execution_mode=EXECUTION_MODE_LOCAL_MOCK, real_calls=0)] + live_scores[1:]
    with pytest.raises(P2ScoringError) as excinfo:
        score_public_suites(mixed)
    assert excinfo.value.code == "execution_mode_mixed"


def test_holdout_scorecard_carries_execution_mark_and_run_id() -> None:
    card = aggregate_holdout(
        holdout_scores(),
        thresholds_approved=True,
        execution_mode=EXECUTION_MODE_LIVE,
        real_calls=7,
        run_id="p2run-h2",
    )
    payload = card.to_dict()
    assert payload["execution_mode"] == "live"
    assert payload["real_calls"] == 7
    assert payload["run_id"] == "p2run-h2"
    # 聚合产物仍然不含明细（run_id 是身份，不是题目）
    assert "H2-" not in json.dumps(payload, ensure_ascii=False)

    default = aggregate_holdout(holdout_scores(), thresholds_approved=True)
    assert (default.execution_mode, default.real_calls, default.run_id) == ("local_mock", 0, None)
    with pytest.raises(P2ScoringError) as excinfo:
        aggregate_holdout(holdout_scores(), thresholds_approved=True, real_calls=1)
    assert excinfo.value.code == "real_calls_without_live_mode"


def test_holdout_case_hard_failure_cannot_be_pass() -> None:
    with pytest.raises(P2ScoringError) as excinfo:
        P2HoldoutCaseScore(
            case_id="H2-01", stratum="negative", status=CASE_STATUS_PASS, hard_failure="safety"
        )
    assert excinfo.value.code == "hard_failure_inconsistent"
    with pytest.raises(P2ScoringError) as excinfo:
        P2HoldoutCaseScore(case_id="H2-01", stratum="negative", status=CASE_STATUS_FAIL, hard_failure="oops")
    assert excinfo.value.code == "hard_failure_kind_invalid"


# --------------------------------------------------------------------------- #
# T206-PRE：绑定摘要 / 引用证据状态 / 判定侧的 run+config 绑定
# --------------------------------------------------------------------------- #

BINDING_BASE = {
    "dataset_version": "P2-HOLDOUT-v2",
    "manifest_sha256": "a" * 64,
    "label_version": "holdout-2026-11-04",
    "pipeline_version": "pipeline1234",
    "index_revision": 6,
    "provider": {
        "chat": {"model": "mock-chat", "transport": "MockTransport"},
        "embedding": {"model": "text-embedding-v4", "dimensions": 1024},
    },
    "gate_version": "mktkb.gate.v0.3",
    "gate_config_hash": "f" * 64,
}


def test_binding_config_hash_is_deterministic_and_config_sensitive() -> None:
    """同配置同 hash；任一组件（dataset/pipeline/索引/provider/gate）变化必变。"""
    first = binding_config_hash(**BINDING_BASE)
    again = binding_config_hash(**{key: value for key, value in BINDING_BASE.items()})
    assert first == again and len(first) == 64
    assert P2_BINDING_VERSION.startswith("p2-binding/")

    changes = {
        "dataset_version": "P2-HOLDOUT-v3",
        "manifest_sha256": "b" * 64,
        "label_version": "holdout-2026-11-05",
        "pipeline_version": "pipeline9999",
        "index_revision": 7,
        "provider": {"chat": {"model": "mock-chat-2", "transport": "MockTransport"}},
        "gate_version": "mktkb.gate.v0.2",
        "gate_config_hash": "0" * 64,
    }
    for name, value in changes.items():
        changed = binding_config_hash(**{**BINDING_BASE, name: value})
        assert changed != first, f"{name} 改了但摘要没变（绑定不可信）"

    # 缺组件 / 空组件 fail closed（不 quietly 用默认值）
    for name, value in (("gate_config_hash", ""), ("dataset_version", ""), ("index_revision", None)):
        with pytest.raises(P2ScoringError) as excinfo:
            binding_config_hash(**{**BINDING_BASE, name: value})
        assert excinfo.value.code in {"binding_input_missing", "binding_input_invalid"}
    with pytest.raises(P2ScoringError) as excinfo:
        binding_config_hash(**{**BINDING_BASE, "provider": {}})
    assert excinfo.value.code == "binding_input_missing"


GOOD_EVIDENCE = {
    "unit_id": UNIT_ID,
    "unit_key": UNIT_KEY,
    "locator": {"sheet": "物品位置", "row": 8},
    "document_id": "22222222-2222-4222-8222-222222222222",
    "version_id": "33333333-3333-4333-8333-333333333333",
    "version_number": 1,
    "state": "published",
    "active": True,
    "in_run": True,
    "verified": True,
    "reason": None,
}


def _turn_row(*, kind: str = "answer", evidence: Any = None, turn: int = 1, case_id: str = "Q01") -> dict:
    product = {"kind": kind}
    if evidence is not None:
        product["evidence"] = evidence
    return {"case_id": case_id, "turns": [{"turn": turn, "status": "ok", "product": product}]}


def test_citation_evidence_status_only_counts_verified_identity() -> None:
    ok = citation_evidence_status([_turn_row(evidence=[dict(GOOD_EVIDENCE)])])
    assert ok["complete"] is True
    assert (ok["answered_turns"], ok["turns_with_evidence"], ok["verified_citations"]) == (1, 1, 1)

    missing = citation_evidence_status([_turn_row()])
    assert missing["complete"] is False
    assert missing["issues"][0]["code"] == "citation_evidence_missing"

    # 未核实（verified=False）不能当证据
    unverified = citation_evidence_status(
        [_turn_row(evidence=[{**GOOD_EVIDENCE, "verified": False, "reason": "unit_not_found"}])]
    )
    assert unverified["complete"] is False
    assert unverified["issues"][0]["code"] == "citation_evidence_unverified"

    # 空 locator 也不算证据身份
    no_locator = citation_evidence_status(
        [_turn_row(evidence=[{**GOOD_EVIDENCE, "locator": {}}])]
    )
    assert no_locator["complete"] is False

    # 只有非作答轮 → 没有可判定证据（保持 unknown，不当通过）
    no_answer = citation_evidence_status([_turn_row(kind="not_found")])
    assert no_answer["complete"] is False
    assert any(item["code"] == "no_answer_turn" for item in no_answer["issues"])

    # H2 聚合路径不得带 case_id
    hidden = citation_evidence_status([_turn_row(case_id="H2-01")], include_case_ids=False)
    assert "case_id" not in json.dumps(hidden, ensure_ascii=False)
    assert '"H2-01"' not in json.dumps(hidden, ensure_ascii=False)


def _gate_inputs(*, run_id: str | None = "p2run-bind", config_hash: str | None = "a" * 64):
    config = load_p2_gate_config()
    manifest: dict[str, Any] = {
        "mode": "end_to_end",
        "scope": "end_to_end",
        "gate_version": config.gate_version,
        "gate_config_hash": config.config_hash,
    }
    if run_id is not None:
        manifest["run_id"] = run_id
    if config_hash is not None:
        manifest["config_hash"] = config_hash
    public = score_public_suites([], run_id=run_id, config_hash=config_hash)
    holdout = aggregate_holdout(
        [], thresholds_approved=False, run_id=run_id, config_hash=config_hash
    )
    return config, manifest, public, holdout


def test_gate_blocks_missing_run_id_and_config_binding() -> None:
    config, manifest, public, holdout = _gate_inputs()
    clean = evaluate_p2_gate(
        config=config,
        run_manifest=manifest,
        run_summary={"status": "succeeded", "stop_code": None, "cases": {}},
        hard_gate=None,
        public=public,
        holdout=holdout,
        citation_evidence_complete=True,
    )
    codes = {block.code for block in clean.blocks}
    assert "run_binding_missing" not in codes and "config_hash_unbound" not in codes
    assert clean.binding_config_hash == "a" * 64

    # 缺 run_id → unknown（R2-F-R2-3：不得"没有 run_id 也能放行"）
    config, manifest, public, holdout = _gate_inputs(run_id=None)
    decision = evaluate_p2_gate(
        config=config,
        run_manifest=manifest,
        run_summary={"status": "succeeded", "stop_code": None, "cases": {}},
        hard_gate=None,
        public=public,
        holdout=holdout,
        citation_evidence_complete=True,
    )
    assert "run_binding_missing" in {block.code for block in decision.blocks}
    assert decision.run_id is None and decision.release_allowed is False

    # manifest 缺 config_hash → unbound
    config, manifest, public, holdout = _gate_inputs(config_hash=None)
    decision = evaluate_p2_gate(
        config=config,
        run_manifest=manifest,
        run_summary={"status": "succeeded", "stop_code": None, "cases": {}},
        hard_gate=None,
        public=public,
        holdout=holdout,
        citation_evidence_complete=True,
    )
    assert "config_hash_unbound" in {block.code for block in decision.blocks}
    assert decision.binding_config_hash is None

    # scorecard 来自另一份绑定配置 → mismatch（不是 run_id 级，而是 config_hash 级）
    config, manifest, _, _ = _gate_inputs()
    public_other = score_public_suites([], run_id="p2run-bind", config_hash="b" * 64)
    holdout_other = aggregate_holdout(
        [], thresholds_approved=False, run_id="p2run-bind", config_hash="a" * 64
    )
    decision = evaluate_p2_gate(
        config=config,
        run_manifest=manifest,
        run_summary={"status": "succeeded", "stop_code": None, "cases": {}},
        hard_gate=None,
        public=public_other,
        holdout=holdout_other,
        citation_evidence_complete=True,
    )
    assert "config_hash_binding_mismatch" in {block.code for block in decision.blocks}
    assert decision.release_allowed is False


def test_scorecard_without_config_hash_is_fail_closed() -> None:
    """R1：manifest 有绑定摘要、scorecard 没声明 → 必须阻断（"缺"不等于"跳过核对"）。"""
    config, manifest, _, _ = _gate_inputs()
    public = score_public_suites([], run_id="p2run-bind")
    holdout = aggregate_holdout([], thresholds_approved=False, run_id="p2run-bind")
    assert public.config_hash is None and holdout.config_hash is None

    decision = evaluate_p2_gate(
        config=config,
        run_manifest=manifest,
        run_summary={"status": "succeeded", "stop_code": None, "cases": {}},
        hard_gate=None,
        public=public,
        holdout=holdout,
        citation_evidence_complete=True,
    )
    codes = [block.code for block in decision.blocks]
    assert codes.count("config_hash_unbound") == 2, decision.to_dict()
    assert decision.release_allowed is False
    assert decision.quality_exit_code != 0  # 质量侧不可放行（分母/阈值在此夹具里另有阻断）
    # 只补一侧仍然不通过：缺的那一侧照样阻断（不是"有一侧够就行"）
    half = evaluate_p2_gate(
        config=config,
        run_manifest=manifest,
        run_summary={"status": "succeeded", "stop_code": None, "cases": {}},
        hard_gate=None,
        public=score_public_suites([], run_id="p2run-bind", config_hash="a" * 64),
        holdout=holdout,
        citation_evidence_complete=True,
    )
    assert "config_hash_unbound" in {block.code for block in half.blocks}
    assert half.release_allowed is False


def test_product_retrieved_candidates_fill_gate_outcome() -> None:
    """R1：产品本轮**检索候选**进 outcome.retrieved（不是把引用抄成候选）。"""
    second_unit = "22222222-2222-4222-8222-222222222222"
    turn = {
        "turn": 1,
        "status": "ok",
        "product": {
            **product(),
            "retrieved": [
                {
                    "document_name": DOC_NAME,
                    "unit_ids": [UNIT_ID],
                    "unit_key": UNIT_KEY,
                    "locator": {"sheet": "物品位置", "row": 8},
                },
                {
                    "document_name": "D02_合作店家信息.xlsx",
                    "unit_ids": [second_unit],
                    "unit_key": "sheet:合作店家:row:2",
                    "locator": {"sheet": "合作店家", "row": 2},
                },
            ],
        },
    }
    outcome = normalize_product_outcome(turn, document_codes=DOCUMENT_CODES)
    assert [item.unit_ids for item in outcome.retrieved] == [(UNIT_ID,), (second_unit,)]
    # 只在显式映射里有代号时才换算；映射不到留空（不猜文档代号）
    assert [item.doc_code for item in outcome.retrieved] == ["D01", ""]

    # 显式候选（评测夹具）优先，产品字段不会覆盖它
    explicit = normalize_product_outcome(
        turn, document_codes=DOCUMENT_CODES, evidence=[{"doc_code": "D01", "unit_ids": [UNIT_ID]}]
    )
    assert [item.unit_ids for item in explicit.retrieved] == [(UNIT_ID,)]

    # 既没有显式候选、产品也没给候选 → 空集：gate 只能判 fail，不当通过
    bare = normalize_product_outcome({"product": product()}, document_codes=DOCUMENT_CODES)
    assert bare.retrieved == ()


# --------------------------------------------------------------------------- #
# 12. T207-FIX-S：期望值内部显式空白（B0 Q39「日期 + 时间」）的 P2 专用口径
# --------------------------------------------------------------------------- #

Q39_VALUE = "2026-10-30 16:00"
Q39_DOCUMENT_CODES = {"D10_盘点通知.docx": "D10"}
Q39_SOURCE = {
    "source_id": "11111111-1111-4111-8111-111111111111",
    "document_name": "D10_盘点通知.docx",
    "version_number": 1,
    "status": "active",
    "locator": {"page": 1},
}


def q39_case() -> CaseSpec:
    """真实冻结题 Q39（stratum=ocr，expected_values 含内部空白），不用手搓样本。"""
    return {case.case_id: case for case in load_b0_cases()}["Q39"]


def q39_score(text: str) -> P2ScoredCase:
    """把一条 Q39 回答送进 P2 评分路径（末轮 -> EvalOutcome -> score_case）。"""
    case = q39_case()
    row = case_row(case, [turn_row(product(text=text, sources=(Q39_SOURCE,)))])
    return score_public_case(
        case,
        row,
        document_codes=Q39_DOCUMENT_CODES,
        allowed_doc_codes={"D10"},
    )


def q39_checks(scored: P2ScoredCase) -> dict[str, str]:
    return {check["check_id"]: check["status"] for check in scored.score.checks}


def test_explicit_space_value_is_p2_opt_in_only() -> None:
    """默认口径（P1 冻结）不变：去空格后数字-数字不跨空白；opt-in 只放开显式空白处。"""
    text = "盘点通知：城东店海报的盘点时间为 2026-10-30 16:00。"
    assert check_value(text, Q39_VALUE) is False
    assert check_value(text, Q39_VALUE, cross_explicit_space=True) is True


def test_q39_correct_answer_passes_public_case_score() -> None:
    """修复前必 fail(value_hit)；修复后正确回答判 pass，且不再有 value_hit fail。"""
    for text in (
        "城东店海报的盘点时间为 2026-10-30 16:00，请提前准备。",
        "城东店海报的盘点时间为 2026-10-30   16:00。",  # 多余空白
        "城东店海报的盘点时间为 ２０２６－１０－３０ １６：００。",  # 全角
    ):
        scored = q39_score(text)
        checks = q39_checks(scored)
        assert checks["value_hit"] == "pass", (text, checks)
        assert scored.score.status == CASE_STATUS_PASS, (text, checks)
        assert scored.result is not None and scored.result.status == "pass"


@pytest.mark.parametrize(
    "text",
    [
        "城东店海报的盘点时间为 2026-11-30 16:00。",  # 错日期
        "城东店海报的盘点时间为 2025-10-30 16:00。",  # 错年份
        "城东店海报的盘点时间为 2026-10-30 15:00。",  # 错时间
        "城东店海报的盘点时间为 2026-10-30。",  # 缺时间
        "城东店海报的盘点时间为 2026-10-30 1 6:00。",  # 只有显式空白那一处可跨空白
    ],
)
def test_q39_wrong_date_time_or_missing_part_still_fail(text: str) -> None:
    scored = q39_score(text)
    assert q39_checks(scored)["value_hit"] == "fail", text
    assert scored.score.status == CASE_STATUS_FAIL, text


@pytest.mark.parametrize(
    ("text", "expected", "hit"),
    [
        ("共12件，另加13件，合计25件", "12", True),  # 既有纯数值样本
        ("B区12号货架", "B区1号", False),  # 既有混合文本样本：不得被更大数字包住
        ("预计 3 个工作日完成", "3 个工作日", True),  # B0 Q27：空白两侧非数字，旧口径已命中
    ],
)
def test_optin_keeps_samples_without_digit_gap_unchanged(
    text: str, expected: str, hit: bool
) -> None:
    """3 个既有样本：opt-in 开关前后判定完全一致（证明没有顺带放宽）。"""
    strict = check_value(text, expected)
    assert strict is hit, (text, expected)
    assert check_value(text, expected, cross_explicit_space=True) is hit


def test_score_case_default_still_rejects_q39_value() -> None:
    """共享 scorer 默认关闭：不显式打开时 Q39 仍按 P1 旧口径判 fail。"""
    case = q39_case()
    gold = ResolvedGold(
        case_id=case.case_id,
        requires_ocr=True,
        skipped=False,
        sources=(),
        unit_ids=(),
        relevant_unit_ids=(),
    )
    outcome = EvalOutcome(kind="answer", text="盘点时间为 2026-10-30 16:00。")
    strict = score_case(case, gold, outcome)
    assert strict.check("value_hit").status == "fail"
    loose = score_case(case, gold, outcome, cross_explicit_space=True)
    assert loose.check("value_hit").status == "pass"
