#!/usr/bin/env python
"""T207-FIX-S 独立验收探针（零真实调用）。

子命令：
  dump <out.json>   在**当前加载到的 mktkb 包**上跑：全量 fixtures 的 check_value /
                    _value_pattern / score_case 结果 + Q39 默认口径结果。
  compare <head.json> <cur.json>
                    比较两份 dump 的逐值分歧（必须为 0）。
  q39               走 P2 评分路径（P2CaseScore）的 Q39 通过/拒绝矩阵。
  narrow            opt-in 窄度：只有含内部空白的期望值行为可能变化。
  integration       独立复算 test_p2_score_run 的 b0 计数（不改该测试）。

运行方式（HEAD 副本在工作区外 temp 目录）：
  PYTHONPATH=<temp>/backend/src   python verify_probe.py dump head.json
  PYTHONPATH=backend/src          python verify_probe.py dump cur.json
  python verify_probe.py compare head.json cur.json
  python verify_probe.py q39
  python verify_probe.py narrow

dump 只调用默认参数（cross_explicit_space 不传），因此 HEAD 包（无该参数）也能跑。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(r"D:/GPT项目/市场部AI知识库")

FIXTURE_FILES = (
    "fixtures/evaluation/b0.jsonl",
    "fixtures/evaluation/regression.jsonl",
    "fixtures/evaluation/badcase.jsonl",
    "docs/reports/OBS-EVAL/P2/T207/cases/R1.jsonl",
    "docs/reports/OBS-EVAL/P2/T207/cases/R2.jsonl",
    "docs/reports/OBS-EVAL/P2/T207/cases/R3.jsonl",
)


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _load_cases():
    from mktkb.evaluation.dataset import load_cases

    rows = []
    for rel in FIXTURE_FILES:
        path = ROOT / rel
        if not path.exists():
            print(f"WARN missing fixture {rel}", file=sys.stderr)
            continue
        cases = load_cases(path)
        print(f"fixture {rel}: {len(cases)} cases")
        rows.extend((rel, case) for case in cases)
    return rows


def _variants(value: str) -> list[str]:
    """期望值自身的文本变体：判分只看这些文本里出现与否。"""
    items = [
        value,
        f"答案：{value}",
        f"答案：{value.replace(' ', '')}",
        f"答案：{value.replace(' ', '   ')}",
        f"答案：{value.replace(' ', chr(10))}",
        f"答案：{value.replace(' ', chr(12288))}",
        f"9{value}",
        f"{value}9",
        f"{value}。",
    ]
    if " " in value:
        items.append(f"答案：{value.replace(' ', '  ')}")  # 只把显式空白处的空白加倍
    return items


def _dump(path: str) -> None:
    import mktkb
    from mktkb.evaluation import scorers
    from mktkb.evaluation.gold import ResolvedGold
    from mktkb.evaluation.scorers import EvalOutcome, score_case

    rows = _load_cases()
    cases = [case for _, case in rows]

    # ---- 文本 / 取值语料（全量 fixtures 的逐值 × 文本变体，另加跨 case 全域对） ----
    texts: list[str] = []
    seen_texts: set[str] = set()

    def add_text(text: str) -> None:
        if text and text not in seen_texts:
            seen_texts.add(text)
            texts.append(text)

    for case in cases:
        add_text(case.reference_answer)
        add_text(case.question)
        for value in tuple(case.expected_values) + tuple(case.forbidden_values):
            for item in _variants(value):
                add_text(item)

    values: list[str] = []
    seen_values: set[str] = set()

    def add_value(value: str) -> None:
        if value and value not in seen_values:
            seen_values.add(value)
            values.append(value)

    for case in cases:
        for value in tuple(case.expected_values) + tuple(case.forbidden_values):
            add_value(value)

    pairs = []
    for text in texts:
        for value in values:
            pairs.append((text, value))

    results = [scorers.check_value(text, value) for text, value in pairs]
    patterns = [
        scorers._value_pattern(scorers.normalize_text(value).replace(" ", "")).pattern
        for value in values
    ]

    # opt-in 窄度的两侧（HEAD 无该参数，用签名探测跳过）
    signature = scorers.check_value.__code__.co_varnames[: scorers.check_value.__code__.co_argcount]
    has_optin = "cross_explicit_space" in scorers.check_value.__code__.co_varnames
    loose = None
    if has_optin:
        loose = [scorers.check_value(text, value, cross_explicit_space=True) for text, value in pairs]
        needle_ok = all(
            scorers._explicit_space_needle(value)[0]
            == scorers.normalize_text(value).replace(" ", "")
            for value in values
        )
    else:
        needle_ok = None

    # ---- score_case 默认参数差分（合成 gold/outcome，覆盖 12 项 check 全链路） ----
    case_results = []
    for case in cases:
        gold = ResolvedGold(
            case_id=case.case_id,
            requires_ocr=bool(case.requires_ocr),
            skipped=False,
            sources=(),
            unit_ids=(),
            relevant_unit_ids=(),
        )
        answer = case.reference_answer or " ".join(case.expected_values)
        for label, outcome in (
            ("answer", EvalOutcome(kind="answer", text=answer)),
            ("no_answer", EvalOutcome(kind="no_answer")),
        ):
            result = score_case(case, gold, outcome)
            case_results.append({"case_id": case.case_id, "outcome": label, "result": result.to_dict()})

    payload = {
        "package": str(Path(mktkb.__file__).resolve()),
        "scorers_sha256": hashlib.sha256(Path(scorers.__file__).read_bytes()).hexdigest(),
        "cases": len(cases),
        "texts": texts,
        "values": values,
        "pairs": results,
        "patterns": patterns,
        "loose": loose,
        "needle_consistent": needle_ok,
        "case_results": case_results,
        "whitespace_values": sorted(v for v in values if " " in v),
        "forbidden_with_space": sorted(
            v for case in cases for v in case.forbidden_values if " " in v
        ),
        "q39": None,
    }

    for case in cases:
        if case.case_id == "Q39":
            payload["q39"] = {
                "stratum": case.stratum,
                "expected_values": list(case.expected_values),
                "reference_answer": case.reference_answer,
                "reference_answer_value_hit": str(
                    score_case(
                        case,
                        ResolvedGold(
                            case_id=case.case_id,
                            requires_ocr=True,
                            skipped=False,
                            sources=(),
                            unit_ids=(),
                            relevant_unit_ids=(),
                        ),
                        EvalOutcome(kind="answer", text=case.reference_answer),
                    ).check("value_hit").status
                ),
            }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path}: cases={len(cases)} values={len(values)} texts={len(texts)} pairs={len(pairs)}")


def _compare(head_path: str, cur_path: str) -> None:
    head = json.loads(Path(head_path).read_text(encoding="utf-8"))
    cur = json.loads(Path(cur_path).read_text(encoding="utf-8"))
    print(f"HEAD package : {head['package']}")
    print(f"HEAD sha256  : {head['scorers_sha256']}")
    print(f"CUR  package : {cur['package']}")
    print(f"CUR  sha256  : {cur['scorers_sha256']}")
    assert head["scorers_sha256"] != cur["scorers_sha256"], "两次 dump 加载了同一份 scorers.py"
    assert head["texts"] == cur["texts"] and head["values"] == cur["values"]
    print(f"fixtures: cases={head['cases']} values={len(head['values'])} texts={len(head['texts'])}")
    print(f"check_value pairs={len(head['pairs'])}")
    diff = [i for i, (a, b) in enumerate(zip(head["pairs"], cur["pairs"])) if a != b]
    print(f"check_value divergences = {len(diff)}")
    for index in diff[:10]:
        print(f"  DIFF text={head['texts'][index // len(head['values'])]!r} "
              f"value={head['values'][index % len(head['values'])]!r} head={head['pairs'][index]} cur={cur['pairs'][index]}")
    pattern_diff = [i for i, (a, b) in enumerate(zip(head["patterns"], cur["patterns"])) if a != b]
    print(f"_value_pattern divergences = {len(pattern_diff)}")
    for index in pattern_diff[:10]:
        print(f"  DIFF value={head['values'][index]!r}\n    head={head['patterns'][index]!r}\n    cur ={cur['patterns'][index]!r}")
    case_diff = []
    for a, b in zip(head["case_results"], cur["case_results"]):
        if a != b:
            case_diff.append((a["case_id"], a["outcome"], a, b))
    print(f"score_case divergences = {len(case_diff)} (over {len(head['case_results'])} case×outcome)")
    for case_id, label, a, b in case_diff[:5]:
        print(f"  DIFF {case_id}/{label}\n    head={json.dumps(a['result'], ensure_ascii=False)}\n    cur ={json.dumps(b['result'], ensure_ascii=False)}")
    print(f"Q39 HEAD default value_hit = {head['q39']['reference_answer_value_hit'] if head['q39'] else 'n/a'}")
    print(f"Q39 CUR  default value_hit = {cur['q39']['reference_answer_value_hit'] if cur['q39'] else 'n/a'}")
    print(f"Q39 stratum = {cur['q39']['stratum'] if cur['q39'] else 'n/a'}")
    print(f"values with internal whitespace = {len(cur['whitespace_values'])}: {cur['whitespace_values']}")
    print(f"forbidden values with internal whitespace = {len(cur['forbidden_with_space'])}: {cur['forbidden_with_space']}")
    if cur["loose"] is not None:
        print(f"opt-in needle == normalize+strip-space for all values: {cur['needle_consistent']}")
        changed_values = set()
        for index, (strict, loose) in enumerate(zip(cur["pairs"], cur["loose"])):
            if strict != loose:
                changed_values.add(cur["values"][index % len(cur["values"])])
        print(f"opt-in changes results for {len(changed_values)} value(s): {sorted(changed_values)}")
        no_space_changed = [
            cur["values"][i % len(cur["values"])]
            for i, (strict, loose) in enumerate(zip(cur["pairs"], cur["loose"]))
            if strict != loose and " " not in cur["values"][i % len(cur["values"])]
        ]
        print(f"opt-in changes results for values WITHOUT internal whitespace = {len(no_space_changed)}")
    print("VERDICT:", "IDENTICAL" if not diff and not pattern_diff and not case_diff else "DIVERGED")


def _q39() -> None:
    import mktkb

    sys.path.insert(0, str(ROOT / "backend" / "tests" / "evaluation"))
    import test_p2_scoring as harness  # noqa: E402

    case = harness.q39_case()
    print(f"package={Path(mktkb.__file__).resolve()}")
    print(f"Q39 case_id={case.case_id} stratum={case.stratum} requires_ocr={case.requires_ocr} "
          f"expected_values={tuple(case.expected_values)!r}")

    # 期望的 value_hit（我作为验收方独立判定）：
    #   pass = 同一日期同一时刻的等价书写（空白/全角/无空白）；fail = 数字不同/缺失/拆位/改写/重排/12h。
    # 实际 value_hit 用 P2 路径（P2CaseScore 的 value_hit check）读取；case 状态另列。
    matrix = [
        ("正确：单空格", "城东店海报的盘点时间为 2026-10-30 16:00，请提前准备。", "pass"),
        ("正确：多余空白", "城东店海报的盘点时间为 2026-10-30   16:00。", "pass"),
        ("正确：制表符", "城东店海报的盘点时间为 2026-10-30\t16:00。", "pass"),
        ("正确：换行", "城东店海报的盘点时间为 2026-10-30\n16:00。", "pass"),
        ("正确：无空白", "城东店海报的盘点时间为 2026-10-3016:00。", "pass"),
        ("正确：全角", "城东店海报的盘点时间为 ２０２６－１０－３０ １６：００。", "pass"),
        ("正确：日期符带空格", "城东店海报的盘点时间为 2026 - 10 - 30 16:00。", "pass"),
        ("范围外：ISO T 分隔", "城东店海报的盘点时间为 2026-10-30T16:00。", "fail"),
        ("窄度：间隔无关文字", "盘点时间为 2026-10-30，另见 16:00。", "fail"),
        ("窄度：日期与时间分句", "盘点日期 2026-10-30。盘点时间 16:00。", "fail"),
        ("错日期", "城东店海报的盘点时间为 2026-11-30 16:00。", "fail"),
        ("错年份", "城东店海报的盘点时间为 2025-10-30 16:00。", "fail"),
        ("错时间", "城东店海报的盘点时间为 2026-10-30 15:00。", "fail"),
        ("缺时间", "城东店海报的盘点时间为 2026-10-30。", "fail"),
        ("缺日期", "盘点时间为 16:00。", "fail"),
        ("时间拆位 1 6:00", "城东店海报的盘点时间为 2026-10-30 1 6:00。", "fail"),
        ("日期拆位 2026-10-3 0", "城东店海报的盘点时间为 2026-10-3 0 16:00。", "fail"),
        ("时间尾部多数字", "城东店海报的盘点时间为 2026-10-30 16:000。", "fail"),
        ("时间截断", "城东店海报的盘点时间为 2026-10-30 16:0。", "fail"),
        ("时间加秒（子串口径）", "城东店海报的盘点时间为 2026-10-30 16:00:30。", "pass"),
        ("中文日期改写（范围外）", "城东店海报的盘点时间为 2026年10月30日 16:00。", "fail"),
        ("12 小时制（范围外）", "城东店海报的盘点时间为 2026-10-30 下午 4:00。", "fail"),
        ("日期时间顺序颠倒", "盘点时间为 16:00 2026-10-30。", "fail"),
        ("被更大数字包住", "城东店海报的盘点时间为 12026-10-30 16:00。", "fail"),
    ]
    print(f"{'期望hit':<7} {'实际hit':<7} {'case':<5} 场景 | 文本")
    bad = []
    for label, text, expected_hit in matrix:
        scored = harness.q39_score(text)
        checks = harness.q39_checks(scored)
        hit = checks.get("value_hit")
        status = scored.score.status
        print(f"{expected_hit:<7} {str(hit):<7} {status:<5} {label} | {text!r}")
        if hit != expected_hit:
            bad.append((label, expected_hit, hit, status, checks))
        if status == "pass" and hit != "pass":
            bad.append((label, "case-pass-without-value-hit", hit, status, checks))
    print(f"value_hit judgement mismatches = {len(bad)}")
    for item in bad:
        print(f"  MISMATCH {item}")
    # 值命中但 case 仍 fail 的原因（与值匹配无关的 check）
    for label, text, expected_hit in matrix:
        if expected_hit != "pass":
            continue
        scored = harness.q39_score(text)
        checks = harness.q39_checks(scored)
        if checks.get("value_hit") == "pass" and scored.score.status != "pass":
            other = {k: v for k, v in checks.items() if v == "fail"}
            print(f"  NOTE {label}: value_hit=pass but case={scored.score.status}, failed checks={other}")
    # opt-in 只在显式空白处跨空白：同一日期/时间被非空白字符隔开不得命中
    from mktkb.evaluation.scorers import check_value

    for text in ("2026-10-30，16:00", "2026-10-30T16:00", "2026-10-30 与 16:00"):
        print(f"  narrow check {text!r}: strict={check_value(text, '2026-10-30 16:00')} "
              f"optin={check_value(text, '2026-10-30 16:00', cross_explicit_space=True)}")


def _narrow() -> None:
    """直接证明 opt-in 的窄度：跨全部 fixture 值，只有显式空白处才可能改变。"""
    import json as _json

    head_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    cur_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    if not head_path or not cur_path:
        print("usage: narrow <head.json> <cur.json>")
        return
    head = _json.loads(head_path.read_text(encoding="utf-8"))
    cur = _json.loads(cur_path.read_text(encoding="utf-8"))
    n_values = len(cur["values"])
    print("per-value opt-in delta (strict -> loose), grouped by value:")
    for index, value in enumerate(cur["values"]):
        strict_hits = [cur["pairs"][i] for i in range(index, len(cur["pairs"]), n_values)]
        loose_hits = [cur["loose"][i] for i in range(index, len(cur["pairs"]), n_values)]
        if strict_hits != loose_hits:
            delta = sum(1 for a, b in zip(strict_hits, loose_hits) if a != b)
            print(f"  {value!r}: {delta} of {len(strict_hits)} text variants change")
    print("values with no change:", n_values - sum(
        1
        for index in range(n_values)
        if any(
            cur["pairs"][i] != cur["loose"][i]
            for i in range(index, len(cur["pairs"]), n_values)
        )
    ), "of", n_values)

def _integration() -> None:
    """独立复算 FIX-A 冻结矩阵里的 b0 计数：预期 40 passed / 0 failed。"""
    import tempfile

    import mktkb

    sys.path.insert(0, str(ROOT / "backend" / "tests" / "evaluation"))
    import test_p2_score_run as harness  # noqa: E402
    from mktkb.evaluation.p2_score_run import build_matrix_observation, score_run

    print(f"package={Path(mktkb.__file__).resolve()}")
    tmp = Path(tempfile.mkdtemp(prefix="t207fixs-integration-"))
    r1_cases = harness.full_public_cases()[:-1]
    r1 = harness.build_run_dir(
        tmp / "r1", cases=r1_cases, rows=harness.gold_rows(r1_cases), run_id="p2-unit-r1"
    )
    bundle_r1 = score_run(r1, cases=r1_cases, document_codes=harness.DOC_CODES)
    u01 = harness.u01_case()
    r2 = harness.build_run_dir(
        tmp / "r2", cases=(u01,), rows=harness.gold_rows((u01,)), run_id="p2-unit-r2", outbound=4
    )
    bundle_r2 = score_run(r2, cases=(u01,), document_codes=harness.DOC_CODES)
    controls = {
        "schema_version": "p2-u-local-controls/v0.1",
        "source": "backend/tests/acceptance/test_t09_mutation.py",
        "basis": "L",
        "cases": {
            f"U{index:02d}": {"case_id": f"U{index:02d}", "status": "pass", "tests": []}
            for index in range(2, 11)
        },
    }
    matrix = build_matrix_observation([bundle_r1, bundle_r2], u_controls=controls)
    print(f"tallies.b0 = {json.dumps(matrix['tallies']['b0'], ensure_ascii=False, sort_keys=True)}")
    print(f"tallies.negative = {json.dumps(matrix['tallies']['negative'], ensure_ascii=False, sort_keys=True)}")
    print(f"tallies.boundary = {json.dumps(matrix['tallies']['boundary'], ensure_ascii=False, sort_keys=True)}")
    print(f"tallies.u = {json.dumps(matrix['tallies']['u'], ensure_ascii=False, sort_keys=True)}")
    q39 = next(row for row in matrix["cases"] if row["case_id"] == "Q39")
    print(f"Q39 matrix row = {json.dumps(q39, ensure_ascii=False, sort_keys=True)}")
    print("test_p2_score_run.py:334 expects passed==39 -> now",
          matrix["tallies"]["b0"]["passed"], "(fix should move it to 40)")


def main() -> None:
    _utf8()
    if len(sys.argv) < 2:
        print(__doc__)
        return
    command = sys.argv[1]
    if command == "dump":
        _dump(sys.argv[2])
    elif command == "compare":
        _compare(sys.argv[2], sys.argv[3])
    elif command == "q39":
        _q39()
    elif command == "narrow":
        _narrow()
    elif command == "integration":
        _integration()
    else:
        raise SystemExit(f"unknown command {command}")


if __name__ == "__main__":
    main()
