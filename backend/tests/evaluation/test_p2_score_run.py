"""P2-T207-FIX-A F5：run 产物 -> 评分/聚合/观测矩阵驱动（离线、零真实调用）。

被测契约（fix-scope §F5 + PM 决定 §2/§3）：
- 公开 run 产物只读打分：缺题/error/未执行如实出 block（not_executed / case_error），不补不猜；
- evaluate_p2_gate 对未审批配置必然 unknown（gate_config_unapproved），不得写 release；
- H2 只出聚合（无 case_id/题干；含 hard_failures/by_stratum/分母），判定表必须逐题对齐；
- 观测矩阵 composition=multi_run_scenario_isolated、release_decision=false、U 行 L/R 逐行标。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mktkb.evaluation.dataset import write_cases
from mktkb.evaluation.p2_public_cases import load_acceptance_cases, load_b0_cases, u01_case
from mktkb.evaluation.p2_score_run import (
    RunScoreError,
    aggregate_holdout_bundle,
    build_matrix_observation,
    decide_run,
    holdout_case_scores_from_rows,
    holdout_case_scores_from_verdicts,
    matrix_from_files,
    parse_junit_controls,
    read_cases_jsonl,
    score_run,
    write_score_bundle,
)
from mktkb.evaluation.p2_scoring import (
    CASE_STATUS_ERROR,
    CASE_STATUS_NOT_EXECUTED,
    CASE_STATUS_PASS,
    P2_HOLDOUT_STRATA,
    load_p2_gate_config,
)

GATE_HASH = load_p2_gate_config().config_hash
#: 产品文档名 -> doc_code 的显式映射（测试用：覆盖 N/C/U 题可能引用的全部 fixture 代号）。
DOC_CODES = {f"{code}_fixture.bin": code for code in
             [f"D{index:02d}" for index in range(1, 11)] + [f"V{index:02d}" for index in range(1, 8)]}
DOC_CODES["D01_物品位置表.xlsx"] = "D01"
DOC_CODES["V01_临时物料位置通知.pdf"] = "V01"
UNIT_KEY = "sheet:物品位置:row:8"


def _product(
    *,
    kind: str,
    text: str,
    sources: tuple[dict, ...] = (),
    trace_id: str = "trace-1",
) -> dict:
    # 产品来源只给 source_id/文档名/版本；单位级身份在 evidence 里（adapter 的只读回执）。
    evidence = [
        {
            "unit_id": str(item["source_id"]),
            "unit_key": item.get("unit_key"),
            "locator": dict(item.get("locator") or {}),
            "verified": item.get("status") == "active",
        }
        for item in sources
    ]
    retrieved = [
        {
            "unit_ids": [str(item["source_id"])],
            "document_name": item.get("document_name"),
            "unit_key": item.get("unit_key"),
            "locator": dict(item.get("locator") or {}),
        }
        for item in sources
    ]
    return {
        "kind": kind,
        "text": text,
        "trace_id": trace_id,
        "trace_path": "rag" if kind != "not_found" else "legacy",
        "sources": [dict(item) for item in sources],
        "evidence": evidence,
        "retrieved": retrieved,
        "http_status": 200,
    }


def _answer_source(version: int = 2) -> dict:
    return {
        "source_id": "11111111-1111-4111-8111-111111111111",
        "document_name": "D01_物品位置表.xlsx",
        "version_number": version,
        "status": "active",
        "unit_key": UNIT_KEY,
        "locator": {"sheet": "物品位置", "row": 8},
    }


def _row(case_id: str, product: dict | None, *, suite: str, stratum: str) -> dict:
    turns = [] if product is None else [
        {"turn": 1, "status": "ok", "error_code": None, "product": product}
    ]
    return {
        "case_id": case_id,
        "suite": suite,
        "stratum": stratum,
        "conversation_id": f"conv-{case_id}",
        "status": "ok",
        "error_code": None,
        "planned_turns": 1,
        "turns_executed": len(turns),
        "turns": turns,
    }


def build_run_dir(
    root: Path,
    *,
    cases,
    rows: list[dict],
    execution: str = "live",
    outbound: int = 12,
    run_id: str = "p2-unit-r1",
) -> Path:
    run = root / "run"
    run.mkdir(parents=True, exist_ok=True)
    dataset_path = run / "dataset.jsonl"
    write_cases(dataset_path, cases)
    (run / "cases.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    manifest = {
        "run_id": run_id,
        "mode": "end_to_end",
        "scope": "end_to_end",
        "suite": "p2-cli",
        "dataset_version": "p2-unit-v1",
        "dataset_sha256": "a" * 64,
        "corpus_manifest_sha256": "b" * 64,
        "business_date": "2026-10-28",
        "index_revision": 7,
        "pipeline_version": "pipeline-unit-1",
        "gate_version": "mktkb.gate.v0.3",
        "label_version": "p2-unit-labels",
        "created_at": "2026-11-11T00:00:00.000+00:00",
        "case_count": len(cases),
        "config_hash": "c" * 64,
        "gate_config_hash": GATE_HASH,
        "execution": execution,
        "dataset_path": str(dataset_path),
        "trace_store": str(run / "traces.sqlite3"),
    }
    (run / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    summary = {
        "status": "succeeded",
        "stop_code": None,
        "cases": {"planned": len(cases), "executed": len(rows), "with_error": 0, "not_executed": 0},
        "attempts": {"available": True, "reserved": outbound, "expected_reservations": outbound},
        "network": {"available": True, "outbound_attempts": outbound},
        "execution": execution,
    }
    (run / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    (run / "gate.json").write_text(
        json.dumps({"citation_evidence": {"complete": False, "issues": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return run


DOC_NAMES = {code: name for name, code in DOC_CODES.items()}


def gold_rows(cases) -> list[dict]:
    """按 gold 造**产物行**（只为驱动/分母链路测试；不是产品行为，也不进任何报告）。"""
    rows: list[dict] = []
    for case in cases:
        if case.should_refuse or case.expected_kind == "not_found":
            product = _product(kind="not_found", text="资料中没有相关记录。", trace_id=f"trace-{case.case_id}")
        elif case.expected_kind == "clarification":
            product = _product(
                kind="clarification",
                text="请说明是哪一家：城东店还是城西店？",
                trace_id=f"trace-{case.case_id}",
            )
        else:
            sources = []
            for index, ref in enumerate(case.expected_sources):
                doc_code = str(ref["doc_code"])
                sources.append(
                    {
                        "source_id": f"unit-{case.case_id}-{index}",
                        "document_name": DOC_NAMES.get(doc_code, f"{doc_code}.xlsx"),
                        "version_number": 2,
                        "status": "active",
                        "unit_key": ref.get("unit_key") or f"unit:{doc_code}:{index}",
                        "locator": dict(ref.get("locator") or {"row": index + 1}),
                    }
                )
            product = _product(
                kind=case.expected_kind,
                text="；".join(case.expected_values) or "已确认",
                sources=tuple(sources),
                trace_id=f"trace-{case.case_id}",
            )
        rows.append(_row(case.case_id, product, suite=case.suite, stratum=case.stratum))
    return rows


def full_public_cases():
    b0 = load_b0_cases()
    nc = load_acceptance_cases()
    return tuple(b0) + tuple(nc) + (u01_case(),)


def small_cases():
    b0 = {case.case_id: case for case in load_b0_cases()}
    nc = {case.case_id: case for case in load_acceptance_cases()}
    cases = (b0["Q01"], nc["N01"], nc["C01"], u01_case())
    # 计划内但产物里没有的一题：必须如实记 not_executed，不许补。
    planned = cases + (nc["C02"],)
    return planned, cases


def test_score_run_marks_pass_not_executed_and_error_without_guessing(tmp_path: Path) -> None:
    planned, given = small_cases()
    b0_q01, nc_n01, nc_c01, u01 = given
    rows = [
        _row(
            "Q01",
            _product(kind="answer", text="城东店的宣传海报位于 B区1号货架第二层。", sources=(_answer_source(),)),
            suite="b0",
            stratum="exact",
        ),
        _row(
            "N01",
            _product(kind="not_found", text="资料中没有城东店的联系人记录。"),
            suite="negative",
            stratum="negative",
        ),
        _row(
            "C01",
            _product(kind="clarification", text="请说明是哪家店：城东店还是城西店？"),
            suite="boundary",
            stratum="ambiguity_conflict",
        ),
        _row("U01", None, suite="update_delete", stratum="mutation"),
    ]
    run = build_run_dir(tmp_path, cases=planned, rows=rows)
    bundle = score_run(run, cases=planned, document_codes=DOC_CODES)
    by_id = {score.case_id: score for score in bundle.scores}
    assert by_id["Q01"].status == CASE_STATUS_PASS
    assert by_id["N01"].status == CASE_STATUS_PASS
    assert by_id["C01"].status == CASE_STATUS_PASS
    assert by_id["U01"].status == CASE_STATUS_NOT_EXECUTED
    assert by_id["C02"].status == CASE_STATUS_NOT_EXECUTED
    assert bundle.execution_mode == "live" and bundle.real_calls == 12
    assert bundle.scorecard.real_calls == 0, "逐题不虚构真实调用归属（run 级实测值在 bundle 上）"
    suites = bundle.scorecard.suites
    assert suites["b0"].passed == 1
    assert suites["negative"].passed == 1
    assert suites["boundary"].passed == 1
    assert suites["boundary"].not_executed == 5, "C02-C06 都不在产物里：如实记 not_executed"
    assert suites["update_delete"].not_executed == 10, "U01 行没有 product，U02-U10 不在产物里"
    codes = {block.code for block in bundle.scorecard.blocks}
    assert "not_executed_cases" not in codes
    assert "case_not_executed" in codes and "missing_case" in codes
    # 分母是冻结的：Q02-Q40 等未提供的题如实记 missing（不是静默少算）。
    assert bundle.scorecard.suites["b0"].planned == 40
    assert bundle.scorecard.release_ready is False


def test_scoring_keeps_error_rows_as_error(tmp_path: Path) -> None:
    planned, _given = small_cases()
    rows = [_row("Q01", None, suite="b0", stratum="exact")]
    rows[0]["status"] = "error"
    rows[0]["error_code"] = "turn_timeout"
    run = build_run_dir(tmp_path, cases=planned, rows=rows)
    bundle = score_run(run, cases=planned, document_codes=DOC_CODES)
    by_id = {score.case_id: score for score in bundle.scores}
    assert by_id["Q01"].status == CASE_STATUS_ERROR
    assert any(issue.code == "case_error" for issue in by_id["Q01"].issues)
    assert "case_error" in {block.code for block in bundle.scorecard.blocks}


def test_decision_is_unknown_and_never_releases(tmp_path: Path) -> None:
    planned = full_public_cases()
    rows = gold_rows(planned)
    run = build_run_dir(tmp_path, cases=planned, rows=rows)
    bundle = decide_run(score_run(run, cases=planned, document_codes=DOC_CODES), cases=planned)
    decision = bundle.decision
    assert decision is not None
    assert decision.decision == "unknown"
    assert decision.release_allowed is False
    assert decision.execution_exit_code == 0
    codes = {block.code for block in decision.blocks}
    assert "gate_config_unapproved" in codes
    # 没有硬失败：硬门禁只可能因"缺 trace/样本"记 unknown，不能记 fail。
    assert decision.hard_failures == ()
    assert all(block.severity != "hard" for block in decision.blocks), [
        (block.code, block.severity) for block in decision.blocks
    ]
    assert decision.hard_gate_status["exact_value_contract"] == "pass"
    assert decision.hard_gate_status["citation_required"] == "pass"
    assert decision.run_id == "p2-unit-r1"
    written = write_score_bundle(bundle, tmp_path / "out")
    assert set(written) == {"scorecard", "case_scores", "p2_decision"}
    payload = json.loads(written["p2_decision"].read_text(encoding="utf-8"))
    assert payload["release_allowed"] is False and payload["decision"] == "unknown"


def test_matrix_is_multi_run_and_never_a_release(tmp_path: Path) -> None:
    # 真实拆分：U01 只在 R2（R1 = B0 40 + N8 + C01-C04）。
    r1_cases = full_public_cases()[:-1]
    r1 = build_run_dir(
        tmp_path / "r1", cases=r1_cases, rows=gold_rows(r1_cases), run_id="p2-unit-r1"
    )
    bundle_r1 = score_run(r1, cases=r1_cases, document_codes=DOC_CODES)
    u01 = u01_case()
    r2 = build_run_dir(
        tmp_path / "r2", cases=(u01,), rows=gold_rows((u01,)), run_id="p2-unit-r2", outbound=4
    )
    bundle_r2 = score_run(r2, cases=(u01,), document_codes=DOC_CODES)
    controls = {
        "schema_version": "p2-u-local-controls/v0.1",
        "source": "backend/tests/acceptance/test_t09_mutation.py",
        "basis": "L",
        "cases": {f"U{index:02d}": {"case_id": f"U{index:02d}", "status": "pass", "tests": []} for index in range(2, 11)},
    }
    matrix = build_matrix_observation([bundle_r1, bundle_r2], u_controls=controls)
    assert matrix["composition"] == "multi_run_scenario_isolated"
    assert matrix["release_decision"] is False and matrix["not_a_release_decision"] is True
    assert matrix["gate"]["block_reason"] == "gate_config_unapproved"
    # T207-FIX-A-R1 阻断 1：FIX-S 已修 Q39「日期+时间」值匹配（p2_scoring 的 cross_explicit_space
    # 只在 P2 路径打开；默认口径逐值不变），因此 b0 从 39/1 变为 40/0。这里按 FIX-S 现状钉住，
    # 不再把 Q39 当"已知 fail"（旧注释描述的缺口已不存在）。
    assert matrix["tallies"]["b0"]["passed"] == 40
    assert matrix["tallies"]["b0"]["failed"] == 0
    assert matrix["tallies"]["b0"]["missing"] == 0
    q39 = next(row for row in matrix["cases"] if row["case_id"] == "Q39")
    assert q39["status"] == "pass", q39
    assert matrix["tallies"]["negative"]["passed"] == 8
    assert matrix["tallies"]["boundary"]["passed"] == 6
    assert matrix["tallies"]["u"] == {
        "planned": 10,
        "passed": 10,
        "failed": 0,
        "errors": 0,
        "not_executed": 0,
        "missing": 0,
    }
    by_case = {row["case_id"]: row for row in matrix["u_table"]}
    assert by_case["U01"]["basis"] == "R" and by_case["U01"]["run_id"] == "p2-unit-r2"
    assert by_case["U02"]["basis"] == "L" and by_case["U02"]["run_id"] is None
    q01 = next(row for row in matrix["cases"] if row["case_id"] == "Q01")
    assert q01["run_id"] == "p2-unit-r1"
    assert q01["index_revision"] == 7 and q01["config_hash"] == "c" * 64
    assert q01["basis"] == "R"
    # 同一 case 出现在两次 run：显式记重复，不静默覆盖。
    duplicated = build_matrix_observation([bundle_r1, bundle_r1], u_controls=controls)
    assert duplicated["duplicated_cases"]["Q01"] == ["p2-unit-r1"]
    assert "U01" not in duplicated["duplicated_cases"]

    out_r1 = write_score_bundle(bundle_r1, tmp_path / "out-r1")["case_scores"]
    out_r2 = write_score_bundle(bundle_r2, tmp_path / "out-r2")["case_scores"]
    controls_path = tmp_path / "u-controls.json"
    controls_path.write_text(json.dumps(controls, ensure_ascii=False), encoding="utf-8")
    from_files = matrix_from_files([out_r1, out_r2], u_controls_path=controls_path)
    assert from_files["composition"] == matrix["composition"]
    assert from_files["tallies"]["u"]["passed"] == 10


def test_junit_controls_map_to_u_ids_and_require_all_variants() -> None:
    xml = """
    <testsuites><testsuite>
      <testcase name="test_u02_publish_switches" />
      <testcase name="test_u03_phone" />
      <testcase name="test_u04_removed_row" ><failure message="boom" /></testcase>
      <testcase name="test_u09_late_ocr_result[variant=delete]" />
      <testcase name="test_u09_late_ocr_result[variant=cancel_pending_version]" ><failure message="x" /></testcase>
      <testcase name="test_u10_client_request_id" ><skipped message="no reason" /></testcase>
      <testcase name="test_public_financial_controls" />
    </testsuite></testsuites>
    """
    payload = parse_junit_controls(xml, source="backend/tests/acceptance/test_t09_mutation.py")
    assert payload["basis"] == "L"
    cases = payload["cases"]
    assert set(cases) == {"U02", "U03", "U04", "U09", "U10"}
    assert cases["U02"]["status"] == "pass"
    assert cases["U04"]["status"] == "fail"
    assert cases["U09"]["status"] == "fail", "同一 U 的任一 parametrize 变体失败就是 fail"
    assert len(cases["U09"]["tests"]) == 2
    assert cases["U10"]["status"] == "skipped"


def _holdout_cases():
    """30 题 / 36 回合的合成 H2 case 行（分层与冻结 P2_HOLDOUT_STRATA 一致）。"""
    from mktkb.evaluation.dataset import CaseSpec

    cases = []
    for stratum, count in P2_HOLDOUT_STRATA.items():
        turns = 3 if stratum == "multi_turn" else 2 if stratum == "multi_turn" else 1
        for index in range(count):
            case_id = f"h2-{stratum}-{index:02d}"
            cases.append(
                CaseSpec(
                    case_id=case_id,
                    suite="p2-holdout",
                    split="holdout",
                    stratum=stratum,
                    business_date="2026-10-28",
                    question=f"合成题 {stratum} {index}",
                    turns=() if stratum != "multi_turn" else (
                        {"question": "一"}, {"question": "二"}
                    ) if index == 0 else (),
                    expected_kind="answer",
                    expected_values=(),
                    labeler="custodian",
                    label_version="h2-unit",
                )
            )
    return tuple(cases)


def test_cli_holdout_requires_exactly_one_sealed_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T207-FIX-A-R1 阻断 3：缺输入必须回契约承诺的稳定码，不是 TypeError。

    断言：①两输入都缺 -> exit 3 + `holdout_input_missing`，且在读数据集/解封之前拒绝
    （不需要 MKTKB_P2_HOLDOUT_ROOT/KEY_FILE）、不写任何产物；②两个都给 -> `holdout_input_conflict`
    （不静默择一）。
    """
    from mktkb.evaluation import cli as cli_module

    manifest = Path(__file__).resolve().parents[3] / "docs" / "evaluation" / "p2-holdout-v2.manifest.json"
    out_dir = tmp_path / "holdout-score"
    base = [
        "p2-score",
        "--run-dir",
        str(tmp_path / "no-such-run"),
        "--visibility",
        "holdout",
        "--holdout-manifest",
        str(manifest),
        "--out",
        str(out_dir),
    ]
    code = cli_module.main(base)
    payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False and payload["error_code"] == "holdout_input_missing"
    assert not out_dir.exists(), "缺输入不得写产物（不按计数编造 pass/fail）"

    both = base + [
        "--holdout-cases",
        str(tmp_path / "sealed-cases.jsonl"),
        "--verdicts",
        str(tmp_path / "sealed-verdicts.jsonl"),
    ]
    code = cli_module.main(both)
    payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False and payload["error_code"] == "holdout_input_conflict"
    assert not out_dir.exists()


def test_holdout_aggregation_outputs_counts_only_and_stays_unapproved() -> None:
    cases = _holdout_cases()
    assert len(cases) == 30
    verdicts = [
        {"case_id": case.case_id, "status": "pass" if index < 24 else "fail"}
        for index, case in enumerate(cases)
    ]
    scores = holdout_case_scores_from_verdicts(cases, verdicts)
    card = aggregate_holdout_bundle(scores, thresholds_approved=False)
    payload = card.to_dict()
    assert payload["total"] == 30 and payload["passed"] == 24
    assert payload["hard_failures"] == 0
    assert set(payload["by_stratum"]) == set(P2_HOLDOUT_STRATA)
    assert payload["threshold_met"] is True
    assert payload["release_ready"] is False
    assert "holdout_threshold_unapproved" in {block.code for block in card.blocks}
    # 聚合产物不得含 case_id / 题干。
    text = json.dumps(payload, ensure_ascii=False)
    for case in cases:
        assert case.case_id not in text
    assert "case_id" not in payload


def test_holdout_verdicts_must_cover_every_case_and_use_known_hard_failures() -> None:
    cases = _holdout_cases()
    short = [{"case_id": case.case_id, "status": "pass"} for case in cases[:-1]]
    with pytest.raises(RunScoreError) as excinfo:
        holdout_case_scores_from_verdicts(cases, short)
    assert excinfo.value.code == "holdout_verdicts_case_mismatch"
    bad = [{"case_id": case.case_id, "status": "pass", "hard_failure": "not_a_kind"} for case in cases]
    with pytest.raises(RunScoreError) as excinfo:
        holdout_case_scores_from_verdicts(cases, bad)
    assert excinfo.value.code == "holdout_hard_failure_kind_invalid"
    extra_field = [{"case_id": case.case_id, "status": "pass", "question": "泄漏"} for case in cases]
    with pytest.raises(RunScoreError) as excinfo:
        holdout_case_scores_from_verdicts(cases, extra_field)
    assert excinfo.value.code == "holdout_verdicts_invalid"


def test_holdout_rows_path_flags_unclassified_source_issues() -> None:
    cases = _holdout_cases()[:1]
    rows = {
        cases[0].case_id: _row(
            cases[0].case_id,
            _product(
                kind="answer",
                text="答案",
                sources=(
                    {
                        "source_id": "22222222-2222-4222-8222-222222222222",
                        "document_name": "D01_物品位置表.xlsx",
                        "version_number": 1,
                        "status": "active",
                        "locator": {"row": 8},
                    },
                ),
            ),
            suite=cases[0].suite,
            stratum=cases[0].stratum,
        )
    }
    scores, unclassified = holdout_case_scores_from_rows(
        cases, rows, document_codes=DOC_CODES, allowed_doc_codes={"D02"}
    )
    assert len(scores) == 1
    assert scores[0].hard_failure is None
    assert "source_outside_run" in unclassified
