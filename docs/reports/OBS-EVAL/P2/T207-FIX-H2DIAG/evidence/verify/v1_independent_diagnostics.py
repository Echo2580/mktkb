# -*- coding: utf-8 -*-
"""独立验收 P2-T207-FIX-H2DIAG：自建 30 题合成封存，逐值核对 diagnostics。

零真实调用：只用内存夹具（不联网、不读 .env / 真实 H2 / key、不写仓库内产物）。
设计者：独立验收助手（未复用开发侧测试夹具 _diag_specs/_diag_rows）。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path

ROOT = Path("D:/GPT项目/市场部AI知识库")
sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation import p2_runner as runner  # noqa: E402
from mktkb.evaluation import p2_score_run  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_runner import (  # noqa: E402
    ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED,
    ERROR_HOLDOUT_SCORECARD_LEAK,
    P2RunError,
    P2RunLedger,
)
from mktkb.evaluation.product_adapter import P2RunDataset, ProductTurn  # noqa: E402

BUSINESS_DATE = "2026-10-28"
VALUE = "甲方命中值"          # 金标值（答案题必须命中）
OTHER = "别的结论"            # 错答
Q = "验收合成问句"
U1 = "7f0e5d3c-0000-4000-8000-00000000a001"
U2 = "7f0e5d3c-0000-4000-8000-00000000a002"
U3 = "7f0e5d3c-0000-4000-8000-00000000a003"
K1 = "sheet:合成:row:1"
K2 = "sheet:合成:row:2"
KBAD = "sheet:合成:row:99"
DOC1 = "D01_合成甲.xlsx"
DOC2 = "D02_合成乙.xlsx"
DOC3 = "D03_合成丙.docx"

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), name, detail))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else ("  <-- " + str(detail)[:600])))
    return bool(ok)


# --------------------------------------------------------------------------- #
# 夹具：30 题（10-5-5-5-5），题面/答案/来源全部自建
# --------------------------------------------------------------------------- #
STRATA = (("paraphrase", 10), ("multi_turn", 5), ("negative", 5),
          ("stale_conflict", 5), ("cross_doc_security", 5))


def _case(n: int, stratum: str, *, kind="answer", refuse=False, values=(), sources=()):
    multi = stratum == "multi_turn"
    turns = ({"question": Q + "-跟随-" + str(n) + "-1"}, {"question": Q + "-跟随-" + str(n) + "-2"}) if multi else ()
    return CaseSpec(
        case_id="VDG-" + str(n).zfill(2),
        suite="p2-holdout",
        split="holdout",
        stratum=stratum,
        business_date=BUSINESS_DATE,
        question="" if multi else Q + "-" + str(n).zfill(2),
        turns=turns,
        expected_kind=kind,
        expected_values=tuple(values),
        expected_sources=tuple(sources),
        reference_answer="" if refuse else "参考答复甲",
        should_refuse=refuse,
        label_version="vdg-v1",
    )


def _src(code, key="row:1"):
    return {"doc_code": code, "unit_key": "sheet:合成:row:" + key}


def build_cases():
    out = []
    for n in range(1, 11):  # paraphrase 01-10
        out.append(_case(n, "paraphrase", values=(VALUE,), sources=(_src("D01", "1"),)))
    for n in range(11, 16):  # multi_turn 11-15
        out.append(_case(n, "multi_turn", values=(VALUE,), sources=(_src("D01", "1"),)))
    for n in range(16, 21):  # negative 16-20
        out.append(_case(n, "negative", kind="refusal", refuse=True))
    for n in range(21, 26):  # stale_conflict 21-25
        out.append(_case(n, "stale_conflict", kind="conflict"))
    for n in range(26, 31):  # cross_doc_security 26-30
        out.append(_case(n, "cross_doc_security", values=(VALUE,), sources=(_src("D01", "1"),)))
    # 26 号期望两份来源（D01 命中、D02 缺）；27 号期望语料里没有的 V07
    out[25] = _case(26, "cross_doc_security", values=(VALUE,),
                    sources=(_src("D01", "1"), _src("D02", "2")))
    out[26] = _case(27, "cross_doc_security", values=(VALUE,), sources=(_src("V07", "1"),))
    return tuple(out)


def _turn(question, *, kind="answer", text="", unit_id=U1, unit_key=K1,
          status="active", doc=DOC1, evidence=True):
    sources = ()
    unit_ids = ()
    evidence_items = ()
    if unit_id:
        sources = ({"source_id": unit_id, "document_name": doc, "status": status},)
        unit_ids = (unit_id,)
        if evidence:
            evidence_items = ({"unit_id": unit_id, "unit_key": unit_key,
                               "locator": {"sheet": "合成", "row": int(unit_key.rsplit(":", 1)[1])},
                               "verified": True},)
    return ProductTurn(
        question_sha256=hashlib.sha256(question.encode("utf-8")).hexdigest(),
        question_chars=len(question), client_request_id="vdg-req", http_status=200,
        kind=kind, text=text, message_id="vdg-msg", request_id="vdg-res", revision=1,
        error_code=None, retryable=False, source_ids=unit_ids, sources=sources,
        missing_fields=(), candidates=0, trace_id=None, trace_path=None,
        trace_outcome=None, trace_status=None, trace_spans=(), replayed=False,
        elapsed_ms=1, evidence=evidence_items,
    )


def _ok_row(case, products):
    return {
        "case_id": case.case_id,
        "status": "ok",
        "error_code": None,
        "planned_turns": len(products),
        "conversation_id": "conv-" + case.case_id,
        "turns": [
            {"turn": i, "item_id": case.case_id + ":turn" + str(i) + ":answer",
             "status": "ok", "error_code": None,
             "product": p.as_dict(include_text=True)}
            for i, p in enumerate(products, start=1)
        ],
    }


def build_rows(cases):
    rows = {}
    for case in cases:
        n = int(case.case_id.rsplit("-", 1)[1])
        if n == 6:            # 06：没有逐题行 → 未执行
            continue
        if case.stratum == "multi_turn":
            qs = [t["question"] for t in case.turns]
            if n == 15:       # 15：第 2 轮 turn error → 整题 error
                rows[case.case_id] = {
                    "case_id": case.case_id, "status": "error", "error_code": None,
                    "planned_turns": 2,
                    "turns": [
                        {"turn": 1, "status": "ok", "error_code": None,
                         "product": _turn(qs[0], text="资料写着" + VALUE).as_dict(include_text=True)},
                        {"turn": 2, "status": "error", "error_code": "MODEL_TIMEOUT",
                         "product": None},
                    ],
                }
                continue
            if n == 12:       # 12：第 1 轮 not_found、末轮 answer → kind 取末轮
                rows[case.case_id] = _ok_row(case, [
                    _turn(qs[0], kind="not_found", text="", unit_id=None),
                    _turn(qs[1], text="资料写着" + VALUE),
                ])
                continue
            rows[case.case_id] = _ok_row(case, [
                _turn(qs[0], text="资料写着" + VALUE),
                _turn(qs[1], text="资料写着" + VALUE),
            ])
            continue
        q = case.question
        if n == 7:            # 07：行级 schema 错误
            rows[case.case_id] = {
                "case_id": case.case_id, "status": "error",
                "error_code": "MODEL_OUTPUT_INVALID", "planned_turns": 1,
                "turns": [{"turn": 1, "status": "error",
                           "error_code": "MODEL_OUTPUT_INVALID", "product": None}],
            }
            continue
        if n == 4:            # 04：答错值
            rows[case.case_id] = _ok_row(case, [_turn(q, text="资料写着" + OTHER)])
        elif n == 5:          # 05：期望作答却拒答（not_found、无引用）
            rows[case.case_id] = _ok_row(case, [_turn(q, kind="not_found", text="", unit_id=None)])
        elif case.stratum == "negative":
            if n == 20:       # 20：该拒答却作答
                rows[case.case_id] = _ok_row(case, [_turn(q, text="资料写着" + VALUE, unit_id=None)])
            else:
                rows[case.case_id] = _ok_row(case, [_turn(q, kind="not_found", text="", unit_id=None)])
        elif case.stratum == "stale_conflict":
            if n == 24:       # 24：引用 superseded 版本 → 结构问题 source_not_active
                rows[case.case_id] = _ok_row(case, [_turn(q, kind="conflict", text="两份不一致（合成）",
                                                          status="superseded")])
            elif n == 25:     # 25：期望 conflict 却 not_found
                rows[case.case_id] = _ok_row(case, [_turn(q, kind="not_found", text="", unit_id=None)])
            else:
                rows[case.case_id] = _ok_row(case, [_turn(q, kind="conflict", text="两份不一致（合成）",
                                                          unit_id=None)])
        elif n == 26:         # 26：期望 D01+D02，只引 D01
            rows[case.case_id] = _ok_row(case, [_turn(q, text="资料写着" + VALUE)])
        elif n == 27:         # 27：期望 V07（语料没有），作答但无引用
            rows[case.case_id] = _ok_row(case, [_turn(q, text="资料写着" + VALUE, unit_id=None)])
        elif n == 28:         # 28：对文档、错单位
            rows[case.case_id] = _ok_row(case, [_turn(q, text="资料写着" + VALUE, unit_id=U3, unit_key=KBAD)])
        elif n == 29:         # 29：引错文档（D03）
            rows[case.case_id] = _ok_row(case, [_turn(q, text="资料写着" + VALUE,
                                                      unit_id=U2, unit_key=K2, doc=DOC3)])
        else:
            rows[case.case_id] = _ok_row(case, [_turn(q, text="资料写着" + VALUE)])
    return rows


class _Source:
    def __init__(self, name, *, ref=None):
        self.path = Path("fixtures") / name
        self.name = name
        self.document_ref = ref


class _Plan:
    def __init__(self, *sources):
        self.sources = tuple(sources)


def _plan():
    return _Plan(_Source(DOC1), _Source(DOC2), _Source(DOC3))


def _dataset(cases, *, visibility="holdout"):
    strata = {}
    for case in cases:
        strata[case.stratum] = strata.get(case.stratum, 0) + 1
    return P2RunDataset(
        visibility=visibility,
        cases=cases,
        identity={"dataset_version": "VDG-v1", "label_version": "vdg-v1",
                  "suite": "p2-holdout", "manifest_sha256": "b" * 64,
                  "case_count": len(cases), "strata": strata},
    )


def _ledger(rows, run_id="p2run-vdg-verify"):
    led = P2RunLedger(run_id=run_id, plan_id="p2-vdg", plan_sha256="a" * 64,
                      execution="dry_run", production_ready=False)
    for row in rows.values():
        led.record_scoring_case(row)
    return led


def _card(cases, rows, *, plan=None, ledger=None):
    return runner._holdout_scorecard(
        ledger or _ledger(rows), _dataset(cases), ingest_plan=_plan() if plan is None else plan,
        execution="dry_run", real_calls=0, binding={"config_hash": "c" * 64}, gate_config=None,
    )


# --------------------------------------------------------------------------- #
# A. 自建 30 题的逐值期望（手算，先于看实现写死）
# --------------------------------------------------------------------------- #
EXPECTED = {
    "schema_version": "p2-holdout-diagnostics/v0.1",
    "detail_available": True,
    "total": 30,
    "ends_observed": 27,   # 30 - 06(未执行) - 07(error) - 15(error)
    "kind_matrix": {
        "answer": {"answer": 16, "error": 2, "not_executed": 1, "not_found": 1},
        "conflict": {"conflict": 4, "not_found": 1},
        "refusal": {"answer": 1, "not_found": 4},
    },
    "refusal_matrix": {
        "true": {"refused": 4, "not_refused": 1},
        "false": {"refused": 2, "not_refused": 20},
    },
    "failing_checks": {
        "kind_correct": 3,
        "refusal_expected": 1,
        "refusal_unexpected": 2,
        "source_hit": 5,
        "value_hit": 2,
    },
    "source_mapping": {
        "doc_codes_available": 3,
        "doc_codes_expected": 3,
        "doc_codes_missing": 1,
        "expected_cases": 20,
        "expected_cases_mapped": 19,
        "source_hit_failed_cases": 5,
        "by_doc_code": {
            "D01": {"expected_cases": 19, "source_hit_failed": 3, "mapped": True},
            "D02": {"expected_cases": 1, "source_hit_failed": 1, "mapped": True},
            "V07": {"expected_cases": 1, "source_hit_failed": 1, "mapped": False},
        },
    },
    "errors_by_code": {
        "MODEL_OUTPUT_INVALID": 1,
        "MODEL_TIMEOUT": 1,
        "not_executed": 1,
        "source_not_active": 1,
    },
    "by_stratum": {
        "paraphrase": {
            "kind_matrix": {"answer": {"answer": 7, "error": 1, "not_executed": 1, "not_found": 1}},
            "refusal_matrix": {"true": {"refused": 0, "not_refused": 0},
                               "false": {"refused": 1, "not_refused": 7}},
            "failing_checks": {"kind_correct": 1, "refusal_unexpected": 1,
                               "source_hit": 1, "value_hit": 2},
            "errors_by_code": {"MODEL_OUTPUT_INVALID": 1, "not_executed": 1},
        },
        "multi_turn": {
            "kind_matrix": {"answer": {"answer": 4, "error": 1}},
            "refusal_matrix": {"true": {"refused": 0, "not_refused": 0},
                               "false": {"refused": 0, "not_refused": 4}},
            "failing_checks": {},
            "errors_by_code": {"MODEL_TIMEOUT": 1},
        },
        "negative": {
            "kind_matrix": {"refusal": {"answer": 1, "not_found": 4}},
            "refusal_matrix": {"true": {"refused": 4, "not_refused": 1},
                               "false": {"refused": 0, "not_refused": 0}},
            "failing_checks": {"kind_correct": 1, "refusal_expected": 1},
            "errors_by_code": {},
        },
        "stale_conflict": {
            "kind_matrix": {"conflict": {"conflict": 4, "not_found": 1}},
            "refusal_matrix": {"true": {"refused": 0, "not_refused": 0},
                               "false": {"refused": 1, "not_refused": 4}},
            "failing_checks": {"kind_correct": 1, "refusal_unexpected": 1},
            "errors_by_code": {"source_not_active": 1},
        },
        "cross_doc_security": {
            "kind_matrix": {"answer": {"answer": 5}},
            "refusal_matrix": {"true": {"refused": 0, "not_refused": 0},
                               "false": {"refused": 0, "not_refused": 5}},
            "failing_checks": {"source_hit": 4},
            "errors_by_code": {},
        },
    },
}


def diff(actual, expected, path=""):
    out = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in actual:
                out.append(path + "/" + str(key) + ": 缺")
            elif key not in expected:
                out.append(path + "/" + str(key) + ": 多=" + repr(actual[key]))
            else:
                out.extend(diff(actual[key], expected[key], path + "/" + str(key)))
    elif actual != expected:
        out.append(path + ": 期望=" + repr(expected) + " 实际=" + repr(actual))
    return out


def main():
    cases = build_cases()
    rows = build_rows(cases)
    card = _card(cases, rows)
    diag = card["diagnostics"]

    print("=== 自建合成（30 题 / 10-5-5-5-5）card ===")
    print(json.dumps({k: card[k] for k in ("total", "executed", "passed", "failed", "errors")},
                     ensure_ascii=False, sort_keys=True))
    print("BLOCKS", [b["code"] for b in card["blocks"]])
    print("=== diagnostics ===")
    print(json.dumps(diag, ensure_ascii=False, indent=2, sort_keys=True))

    check(diff(diag, EXPECTED) == [], "A1 diagnostics 逐值等于手算期望", diff(diag, EXPECTED))
    check((card["total"], card["executed"], card["passed"], card["failed"], card["errors"])
          == (30, 26, 18, 8, 4), "A2 计数卡与手算一致（诊断不改口径）",
          (card["total"], card["executed"], card["passed"], card["failed"], card["errors"]))
    check(diag["kind_matrix"]["answer"]["answer"] == 16,
          "A3 kind 取末轮（12 号第1轮 not_found 不计入）", diag["kind_matrix"])

    # B. 不变量
    total_kind = sum(sum(c.values()) for c in diag["kind_matrix"].values())
    ends = sum(c for row in diag["refusal_matrix"].values() for c in row.values())
    check(total_kind == diag["total"] == card["total"], "B1 kind 矩阵覆盖全部题", total_kind)
    check(ends == diag["ends_observed"], "B2 拒答矩阵总和 = ends_observed", (ends, diag["ends_observed"]))
    check(sum(diag["errors_by_code"].values()) == card["errors"],
          "B3 sum(errors_by_code) == card.errors", (sum(diag["errors_by_code"].values()), card["errors"]))
    for stratum, tables in diag["by_stratum"].items():
        ksum = sum(sum(c.values()) for c in tables["kind_matrix"].values())
        esum = sum(c for row in tables["refusal_matrix"].values() for c in row.values())
        ok = (ksum == card["by_stratum"][stratum]["total"]
              and esum <= ksum
              and sum(tables["errors_by_code"].values()) <= card["by_stratum"][stratum]["errors"])
        check(ok, "B4 分层自洽 " + stratum, (ksum, card["by_stratum"][stratum]))
    blocks = {b["code"]: b for b in card["blocks"]}
    check(blocks[ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED]["evidence"]
          == {"missing": ["V07"], "mapped": 3},
          "B5 映射缺失 block 与 source_mapping 同源", blocks.get(ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED))
    check(diag["source_mapping"]["doc_codes_available"]
          == blocks[ERROR_HOLDOUT_DOCUMENT_CODE_UNMAPPED]["evidence"]["mapped"], "B6 available==mapped")
    check(diag["source_mapping"]["by_doc_code"]["D01"]["source_hit_failed"] == 3,
          "B7 已命中的 D01 未被 26 号冤枉（26 号只记 D02）",
          diag["source_mapping"]["by_doc_code"])

    # C. 泄漏：诊断子树全文纯 ASCII（无题干/答案/文档内容），产物无 case_id
    raw_diag = json.dumps(diag, ensure_ascii=False)
    check(all(ord(ch) < 128 for ch in raw_diag), "C1 诊断子树无任何非 ASCII（CJK/全角）字符")
    raw_card = json.dumps(card, ensure_ascii=False)
    leaks = [case.case_id for case in cases if case.case_id in raw_card]
    leaks += [q for q in (VALUE, OTHER, Q, "参考答复甲") if q in raw_card]
    check(leaks == [], "C2 卡全文扫描 0 命中（case_id/题干/答案/文档内容）", leaks)

    # D. additive：旧字段逐字不变
    base_blocks = []
    marks, mode, scoring = runner._holdout_score_marks(
        _ledger(rows), _dataset(cases), ingest_plan=_plan(), execution="dry_run", blocks=base_blocks)
    base = runner._aggregate_marks(
        marks, dataset=_dataset(cases), ledger=_ledger(rows),
        binding={"config_hash": "c" * 64}, gate_config=None,
        execution_mode=mode, real_calls=0, blocks=base_blocks)
    stripped = {key: value for key, value in card.items() if key != "diagnostics"}
    check(stripped == base, "D1 去掉 diagnostics 后与既有聚合逐字相同", diff(stripped, base))
    check(set(card) - set(base) == {"diagnostics"}, "D2 卡上只新增 diagnostics 一个键",
          set(card) ^ set(base))

    # E. score_sink：返回形状不变
    from mktkb.evaluation.p2_score_run import holdout_case_scores_from_rows
    sink = []
    a, ua = holdout_case_scores_from_rows(cases, rows, document_codes=runner.holdout_document_codes(_plan()))
    b, ub = holdout_case_scores_from_rows(cases, rows, document_codes=runner.holdout_document_codes(_plan()),
                                          score_sink=sink)
    check((a, ua) == (b, ub), "E1 传/不传 score_sink 返回值完全相同")
    check(len(sink) == 30, "E2 score_sink 收到 30 条逐题明细（只读口）", len(sink))
    default = inspect.signature(holdout_case_scores_from_rows).parameters["score_sink"].default
    check(default is None, "E3 score_sink 默认 None（既有调用不受影响）", default)

    # F. 6 类坏形态 fail-closed（独立构造，不复用开发侧用例）
    dataset = _dataset(cases)
    GOOD = {"schema_version": "p2-holdout-diagnostics/v0.1", "detail_available": True,
            "total": 30, "kind_matrix": {"answer": {"answer": 30}},
            "refusal_matrix": {"true": {"refused": 0, "not_refused": 0},
                               "false": {"refused": 0, "not_refused": 30}},
            "errors_by_code": {"MODEL_OUTPUT_INVALID": 3}}

    def _only(**kwargs):
        payload = dict(GOOD)
        payload.update(kwargs)
        return {"diagnostics": payload}

    try:
        runner._assert_holdout_scorecard_payload(_only(), dataset)
        check(True, "F0 正常诊断卡不误报（0 命中）")
    except Exception as exc:  # noqa: BLE001
        check(False, "F0 正常诊断卡不误报（0 命中）", repr(exc))

    BAD = {
        "F1 自由文本 kind 键（题干原文）": {"kind_matrix": {"answer": {Q + "-01": 1}}},
        "F2a 含空格的自由文本值": {"failing_checks": {"value_hit": "answer not_found"}},
        "F2b 超长串值（65 字）": {"failing_checks": {"value_hit": "a" * 65}},
        "F3 数组夹带": {"errors_by_code": {"MODEL_X": ["MODEL_X"]}},
        "F4 未登记顶层键": {"totals_extra": 1},
        "F5 H2- 前缀键": {"kind_matrix": {"H2-07": {"answer": 1}}},
        "F6 题干片段值": {"failing_checks": {"value_hit": Q}},
        "F7 未登记 schema 版本": {"schema_version": "p2-holdout-diagnostics/v9.9"},
    }
    for name, patch in BAD.items():
        try:
            runner._assert_holdout_scorecard_payload(_only(**patch), dataset)
            check(False, name, "未抛错（未 fail-closed）")
        except P2RunError as exc:
            check(exc.code == ERROR_HOLDOUT_SCORECARD_LEAK, name, exc.code)

    # F8：形态白名单之外的兜底——ASCII 题干（恰好符合代码形态）由逐题 needle 扫描拦下
    ascii_case = _case(77, "paraphrase", values=(VALUE,), sources=(_src("D01", "1"),))
    ascii_case = CaseSpec(**{**ascii_case.to_dict(), "question": "WhatIsTheAnswerValue"})
    payload = {"diagnostics": {"kind_matrix": {"answer": {"WhatIsTheAnswerValue": 1}}}}
    try:
        runner._assert_holdout_diagnostics(payload["diagnostics"])
        shape_ok = True
    except P2RunError:
        shape_ok = False
    try:
        runner._assert_holdout_scorecard_payload(payload, _dataset((ascii_case,)))
        needle_blocks = False
    except P2RunError as exc:
        needle_blocks = exc.code == ERROR_HOLDOUT_SCORECARD_LEAK
    check(shape_ok and needle_blocks,
          "F8 代码形态的 ASCII 题干：白名单放过、needle 扫描拦下（纵深防御）",
          (shape_ok, needle_blocks))

    # G. 端到端 fail-closed：坏诊断 → 全 error + 稳定 block + 不写明文
    poison = {"schema_version": "p2-holdout-diagnostics/v0.1", "detail_available": True,
              "total": 30, "errors_by_code": {}, "kind_matrix": {"answer": {Q + "-01": 1}}}
    orig = runner._holdout_diagnostics
    runner._holdout_diagnostics = lambda *a, **k: dict(poison)
    try:
        bad_payload = runner._holdout_scorecard_artifact(
            _ledger(rows), _dataset(cases), ingest_plan=_plan(), execution="dry_run",
            real_calls=0, binding={"config_hash": "c" * 64}, gate_config=None)
    finally:
        runner._holdout_diagnostics = orig
    bad_diag = bad_payload["diagnostics"]
    codes = {b["code"] for b in bad_payload["blocks"]}
    check((bad_payload["total"], bad_payload["executed"], bad_payload["passed"],
           bad_payload["failed"], bad_payload["errors"]) == (30, 0, 0, 0, 30),
          "G1 坏诊断 → 退化为全 error 卡", {k: bad_payload[k] for k in ("total", "executed", "passed", "failed", "errors")})
    check(ERROR_HOLDOUT_SCORECARD_LEAK in codes, "G2 稳定 block 码 holdout_scorecard_leak", codes)
    check(bad_diag == {"schema_version": "p2-holdout-diagnostics/v0.1",
                       "detail_available": False, "total": 30,
                       "errors_by_code": {ERROR_HOLDOUT_SCORECARD_LEAK: 30}},
          "G3 兜底卡诊断只给原因码 x 总数", bad_diag)
    check(Q not in json.dumps(bad_payload, ensure_ascii=False), "G4 兜底卡不残留明文题干")
    try:
        runner._assert_holdout_scorecard_payload(bad_payload, _dataset(cases))
        check(True, "G5 兜底卡自身通过泄漏审计")
    except Exception as exc:  # noqa: BLE001
        check(False, "G5 兜底卡自身通过泄漏审计", repr(exc))

    # H. 正常路径走完整 artifact（含审计）→ 诊断与手算一致，无 fallback
    normal = runner._holdout_scorecard_artifact(
        _ledger(rows), _dataset(cases), ingest_plan=_plan(), execution="dry_run",
        real_calls=0, binding={"config_hash": "c" * 64}, gate_config=None)
    check(normal["diagnostics"] == EXPECTED and normal["passed"] == 18,
          "H1 正常 artifact 诊断=手算、pass=18（未被误判成泄漏）",
          diff(normal["diagnostics"], EXPECTED))

    # I. aborted 语义（1 条错误行 + 29 条未执行）
    row1 = {
        "case_id": cases[0].case_id, "status": "error", "error_code": "MODEL_UNAVAILABLE",
        "planned_turns": 1,
        "turns": [{"turn": 1, "status": "error", "error_code": "MODEL_UNAVAILABLE",
                   "product": _turn(cases[0].question, kind="service_error", text="",
                                    unit_id=None).as_dict(include_text=True)}],
    }
    led = P2RunLedger(run_id="p2run-vdg-abort", plan_id="p2-vdg", plan_sha256="a" * 64,
                      execution="dry_run", production_ready=False)
    led.record_scoring_case(row1)
    aborted = _card(cases, rows, ledger=led)
    exp_abort = {
        "schema_version": "p2-holdout-diagnostics/v0.1",
        "detail_available": True,
        "total": 30,
        "ends_observed": 0,
        "kind_matrix": {"answer": {"not_executed": 19, "service_error": 1},
                        "conflict": {"not_executed": 5},
                        "refusal": {"not_executed": 5}},
        "refusal_matrix": {"true": {"refused": 0, "not_refused": 0},
                           "false": {"refused": 0, "not_refused": 0}},
        "failing_checks": {},
        "source_mapping": {
            "doc_codes_available": 3, "doc_codes_expected": 3, "doc_codes_missing": 1,
            "expected_cases": 20, "expected_cases_mapped": 19, "source_hit_failed_cases": 0,
            "by_doc_code": {
                "D01": {"expected_cases": 19, "source_hit_failed": 0, "mapped": True},
                "D02": {"expected_cases": 1, "source_hit_failed": 0, "mapped": True},
                "V07": {"expected_cases": 1, "source_hit_failed": 0, "mapped": False},
            },
        },
        "errors_by_code": {"MODEL_UNAVAILABLE": 1, "not_executed": 29},
        "by_stratum": {},  # 分层表单独核对（下面按层验证总数）
    }
    got = dict(aborted["diagnostics"])
    got_stratum = got.pop("by_stratum")
    exp_cmp = dict(exp_abort)
    exp_cmp.pop("by_stratum")
    check(diff(got, exp_cmp) == [], "I1 aborted 诊断逐值（已执行 1 + not_executed 29）", diff(got, exp_cmp))
    check(sum(aborted["diagnostics"]["errors_by_code"].values()) == aborted["errors"] == 30,
          "I2 aborted: sum(errors_by_code)==errors==30")
    check(sorted(got_stratum) == sorted(["paraphrase", "multi_turn", "negative",
                                         "stale_conflict", "cross_doc_security"]),
          "I3 aborted 仍按层拆表", sorted(got_stratum))
    per = {name: sum(sum(c.values()) for c in t["kind_matrix"].values())
           for name, t in got_stratum.items()}
    check(per == {"paraphrase": 10, "multi_turn": 5, "negative": 5,
                  "stale_conflict": 5, "cross_doc_security": 5},
          "I4 aborted 分层覆盖率完整", per)

    # J. CLI 路径不产出 diagnostics / 无诊断卡仍可审计（向后兼容）
    import mktkb.evaluation.p2_score_run as psr
    code_lines = [ln for ln in inspect.getsource(psr).splitlines()
                  if "diagnostics" in ln and not ln.strip().startswith("#")]
    check(code_lines == [], "J1 p2-score CLI 侧代码不含 diagnostics", code_lines)
    try:
        runner._assert_holdout_scorecard_payload({"total": 30, "blocks": []}, _dataset(cases))
        check(True, "J2 无 diagnostics 的卡仍可审计（向后兼容）")
    except Exception as exc:  # noqa: BLE001
        check(False, "J2 无 diagnostics 的卡仍可审计（向后兼容）", repr(exc))

    bad = [name for ok, name, _ in RESULTS if not ok]
    print()
    print("=== SUMMARY: " + str(len(RESULTS) - len(bad)) + " PASS / " + str(len(bad)) + " FAIL ===")
    if bad:
        print("FAILED: " + json.dumps(bad, ensure_ascii=False))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
