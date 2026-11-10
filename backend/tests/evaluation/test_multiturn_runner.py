"""T109：多轮 ``turns`` runner（P1 第 10 包）。

覆盖 handoff §3 六条里的多轮语义：

1. ``turns`` ≥2 按序执行、**同一** conversation 状态继承（末轮只答上文问过的字段）；
2. 判定：中间轮 error → case fail；末轮 checks fail → case fail；中间轮 checks 不决定通过；
   全部轮次无 error + 末轮通过 → pass；
3. 逐轮 trace：每轮 trace_id 落库可查、``previous_trace_id`` 串联、``trace_id`` = 末轮；
4. 单轮不变：``turns`` 为空/单元素与父提交一致（``turns_executed=1``）；
5. replay：多轮逐轮 replay（不静默只跑首轮），status/checks 复现；
6. 合规：只用临时合成语料（E11 一份）+ 合成 dataset，不建 49 份全量语料、零真实调用。

语料/数据策略与 ``test_regression_suite.py`` 一致：临时目录里复制 E11（终端物料位置表，
含「滨江店/宣传海报/店内外侧/40」与「卓刀河店/马克杯」），避免在测试里重建全量语料。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from mktkb.evaluation.dataset import CaseSpec, cases_to_jsonl, load_cases
from mktkb.evaluation.runner import run_suite
from mktkb.observability.store import TraceRepository
from mktkb.rag.index import RagIndex
from mktkb.rag.types import RagAnswer

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "corpus" / "enterprise-20261101"
EVAL_DIR = ROOT / "fixtures" / "evaluation"
LABEL_VERSION = "regression-p1-2026-11-05"
E11_UNIT_KEY = "sheet:物品位置:row:7"

#: 会话继承题：turn1 问数量，turn2 纯指代；末轮只应答数量 40（E11 QF01 行）。
QUANTITY_TURNS = (
    {"role": "user", "text": "滨江店的宣传海报的数量是多少？"},
    {"role": "user", "text": "那个海报呢"},
)


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #


def _corpus_dir(tmp_path: Path) -> Path:
    """只装 E11 的合成 regression 语料（与 test_regression_suite 同口径）。"""
    corpus_dir = tmp_path / "corpus"
    (corpus_dir / "excel").mkdir(parents=True, exist_ok=True)
    source = CORPUS / "excel" / "E11_终端物料位置表_当前V2.xlsx"
    target = corpus_dir / "excel" / source.name
    if not target.is_file():
        shutil.copy2(source, target)
    manifest = {
        "business_base_date": "2026-10-28",
        "files": [
            {
                "code": "E11",
                "group": "excel",
                "path": f"excel/{source.name}",
                "kind": "xlsx",
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        ],
    }
    (corpus_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return corpus_dir


def _case(**overrides) -> CaseSpec:
    payload = dict(
        case_id="MT01",
        suite="regression",
        split="dev",
        stratum="defect-t105",
        business_date="2026-10-28",
        question="那个海报呢",
        turns=QUANTITY_TURNS,
        expected_kind="answer",
        expected_values=("40",),
        expected_sources=({"doc_code": "E11", "unit_key": E11_UNIT_KEY},),
        relevant_units=(),
        reference_answer="滨江店的宣传海报 40 张（E11 第 7 行）。",
        should_refuse=False,
        refusal_reason=None,
        forbidden_values=("店内外侧", "QF01"),
        forbidden_sources=(),
        expected_pagination=None,
        requires_ocr=False,
        labeler="lead",
        label_version=LABEL_VERSION,
        notes="T109 合成多轮用例",
        source_err_id="ERR-20261104-06",
    )
    payload.update(overrides)
    return CaseSpec(**payload)


def _run(tmp_path: Path, name: str, cases: list[CaseSpec]):
    dataset = tmp_path / f"{name}.jsonl"
    dataset.write_bytes(cases_to_jsonl(cases).encode("utf-8"))
    return run_suite(
        "regression",
        "local",
        corpus_dir=_corpus_dir(tmp_path),
        dataset_path=dataset,
        out_dir=tmp_path / name,
    )


def _rows(result) -> list[dict]:
    return [
        json.loads(line)
        for line in (result.out_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _record(result, trace_id: str):
    repo = TraceRepository(result.out_dir / "traces.sqlite3")
    try:
        return repo.get(trace_id)[0]
    finally:
        repo.close()


def _rewrite_source_rows(run_dir: Path, mutate) -> None:
    """改写源 run 的 ``cases.jsonl``（模拟旧产物 / 损坏源），manifest 不动。

    replay 只读 ``run_manifest.json`` + ``cases.jsonl``：字段级改写足以复现「源 run 未逐轮
    执行」的旧产物形态（父提交 run 的行确实没有 ``turn_traces``，见证据 03-F 实跑）。
    """
    path = run_dir / "cases.jsonl"
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rewritten = [mutate(row) for row in rows]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rewritten) + "\n",
        encoding="utf-8",
    )


def _replay(tmp_path: Path, name: str, source_dir: Path, dataset: Path):
    return run_suite(
        "regression",
        "replay",
        corpus_dir=_corpus_dir(tmp_path),
        dataset_path=dataset,
        out_dir=tmp_path / name,
        replay_from=source_dir,
    )


# --------------------------------------------------------------------------- #
# 1. 顺序执行 + 会话状态继承 + 逐轮 trace
# --------------------------------------------------------------------------- #


def test_multi_turn_runs_in_order_and_inherits_conversation_state(tmp_path: Path) -> None:
    result = _run(tmp_path, "multi", [_case()])
    row = _rows(result)[0]

    assert row["status"] == "pass", row
    assert row["error"] is None
    assert row["turns_executed"] == 2
    assert row["multi_turn_claimed"] is True
    # 末轮只答上文问过的字段：含 40，不倾倒其它字段。
    assert row["outcome"]["kind"] == "answer"
    assert "40" in row["outcome"]["text"]
    assert "店内外侧" not in row["outcome"]["text"]
    assert "QF01" not in row["outcome"]["text"]
    # trace_id 仍是末轮（既有消费方口径）。
    assert row["trace_id"] == row["turn_traces"][-1]["trace_id"]
    assert [item["turn"] for item in row["turn_traces"]] == [1, 2]
    assert [item["status"] for item in row["turn_traces"]] == ["ok", "ok"]

    first = _record(result, row["turn_traces"][0]["trace_id"])
    second = _record(result, row["turn_traces"][1]["trace_id"])
    assert first.case_id == second.case_id == "MT01"
    assert first.previous_trace_id is None
    assert second.previous_trace_id == first.trace_id
    assert first.status == second.status == "ok"


def test_multi_turn_inheritance_is_what_makes_the_last_turn_answerable(tmp_path: Path) -> None:
    """对照：同一末轮问题在没有上文时是 clarification，有上文才是 answer。"""
    control = _case(
        case_id="MT02",
        turns=(),
        expected_kind="clarification",
        expected_values=(),
        expected_sources=(),
        forbidden_values=(),
    )
    row = _rows(_run(tmp_path, "control", [control]))[0]
    assert row["status"] == "pass", row
    assert row["outcome"]["kind"] == "clarification"
    assert row["turns_executed"] == 1
    assert len(row["turn_traces"]) == 1


# --------------------------------------------------------------------------- #
# 2. 判定口径
# --------------------------------------------------------------------------- #


def test_intermediate_turn_error_fails_case(tmp_path: Path, monkeypatch) -> None:
    """中间轮抛异常 → case fail（不伪造后续轮，如实记录执行轮次）。"""
    real_ask = RagIndex.ask

    def flaky(self, question, **kwargs):
        if "城西区" in question:
            raise RuntimeError("probe boom")
        return real_ask(self, question, **kwargs)

    monkeypatch.setattr(RagIndex, "ask", flaky)
    case = _case(
        case_id="MT03",
        turns=(
            {"role": "user", "text": "滨江店的宣传海报在哪里？"},
            {"role": "user", "text": "城西区的宣传海报在哪？"},
            {"role": "user", "text": "滨江店的宣传海报的数量是多少？"},
        ),
    )
    row = _rows(_run(tmp_path, "mid-error", [case]))[0]

    assert row["status"] == "fail", row
    assert row["error"]["code"] == "execution_error"
    assert "turn 2/3" in row["error"]["message"]
    assert row["outcome"] is None and row["checks"] == []
    # 只执行到失败轮为止，不伪造第 3 轮。
    assert row["turns_executed"] == 2
    assert [item["status"] for item in row["turn_traces"]] == ["ok", "error"]
    assert row["trace_id"] == row["turn_traces"][-1]["trace_id"]


def test_intermediate_turn_error_outcome_fails_case_even_if_last_turn_passes(
    tmp_path: Path, monkeypatch
) -> None:
    """中间轮答案是 error 结局 → case fail；末轮 checks 照常记录（仍全部通过）。"""
    real_ask = RagIndex.ask

    def erroring(self, question, **kwargs):
        if "城西区" in question:
            return RagAnswer(kind="error", question=question, text="", state={})
        return real_ask(self, question, **kwargs)

    monkeypatch.setattr(RagIndex, "ask", erroring)
    case = _case(
        case_id="MT04",
        turns=(
            {"role": "user", "text": "城西区的宣传海报在哪？"},
            {"role": "user", "text": "滨江店的宣传海报的数量是多少？"},
        ),
    )
    run = _run(tmp_path, "mid-error-outcome", [case])
    row = _rows(run)[0]

    assert row["status"] == "fail", row
    # R1：轮级 error 必须落 error 明细（code + turn n/N），不能只靠 turn_traces[].status。
    assert row["error"] == {
        "code": "answer_error",
        "message": "turn 1/2: 答案结局 kind=error（要求无 error）",
    }
    assert row["turns_executed"] == 2
    assert [item["status"] for item in row["turn_traces"]] == ["error", "ok"]
    assert all(item["status"] != "fail" for item in row["checks"]), row["checks"]
    declarations = run.summary["declarations"]["execution"]
    assert declarations["multi_turn_verified"] is False
    assert declarations["multi_turn_error_case_ids"] == ["MT04"]


def test_intermediate_turn_trace_unreadable_fails_with_turn_detail(
    tmp_path: Path, monkeypatch
) -> None:
    """R1：中间轮 Trace 不可读 → case fail，且 ``error`` 带 code 与 ``turn n/N``。"""
    import mktkb.evaluation.runner as runner_module

    real_read = runner_module._read_trace
    calls = {"count": 0}

    def unreadable_first_turn(repo, trace_id):
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return real_read(repo, trace_id)

    monkeypatch.setattr(runner_module, "_read_trace", unreadable_first_turn)
    run = _run(tmp_path, "trace-missing", [_case(case_id="MT12")])
    row = _rows(run)[0]

    assert row["status"] == "fail", row
    assert row["error"] == {
        "code": "trace_missing",
        "message": "turn 1/2: Trace 不可读（trace store 无该轮记录）",
    }
    assert [item["status"] for item in row["turn_traces"]] == ["error", "ok"]
    assert row["turns_executed"] == 2
    # 末轮仍按既有 scorer 评（checks 有记录），只是 case 判 fail。
    assert row["checks"]


def test_last_turn_checks_fail_fails_case(tmp_path: Path) -> None:
    row = _rows(_run(tmp_path, "last-fail", [_case(case_id="MT05", expected_values=("99",))]))[0]

    assert row["status"] == "fail", row
    assert row["error"] is None
    checks = {item["check_id"]: item["status"] for item in row["checks"]}
    assert checks["value_hit"] == "fail"
    assert [item["status"] for item in row["turn_traces"]] == ["ok", "ok"]


def test_intermediate_turn_checks_do_not_decide_pass(tmp_path: Path) -> None:
    """中间轮本身是 clarification（按 case 期望会被判 fail）也不影响通过。"""
    case = _case(
        case_id="MT06",
        turns=(
            {"role": "user", "text": "城西区的宣传海报在哪？"},
            {"role": "user", "text": "滨江店的宣传海报的数量是多少？"},
        ),
    )
    row = _rows(_run(tmp_path, "mid-checks", [case]))[0]

    assert row["status"] == "pass", row
    assert row["outcome"]["kind"] == "answer"
    assert "40" in row["outcome"]["text"]


# --------------------------------------------------------------------------- #
# 3. 单轮不变
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "turns",
    [(), ({"role": "user", "text": "城西区的宣传海报在哪？"},)],
    ids=["empty", "single-entry"],
)
def test_single_turn_rows_keep_parent_behaviour(tmp_path: Path, turns: tuple) -> None:
    """``turns`` 为空/单元素：执行 ``question``（忽略 turns），``turns_executed=1``。"""
    case = _case(case_id="MT07", question="滨江店的宣传海报的数量是多少？", turns=turns)
    row = _rows(_run(tmp_path, "single", [case]))[0]

    assert row["status"] == "pass", row
    assert row["turns_executed"] == 1
    assert row["multi_turn_claimed"] is False
    assert row["outcome"]["kind"] == "answer"
    assert "40" in row["outcome"]["text"]
    assert len(row["turn_traces"]) == 1
    assert row["turn_traces"][0]["turn"] == 1
    assert row["turn_traces"][0]["trace_id"] == row["trace_id"]


# --------------------------------------------------------------------------- #
# 4. replay
# --------------------------------------------------------------------------- #


def test_multi_turn_replay_replays_every_turn(tmp_path: Path) -> None:
    local = _run(tmp_path, "replay-src", [_case()])
    dataset = tmp_path / "replay-src.jsonl"
    replay = run_suite(
        "regression",
        "replay",
        corpus_dir=_corpus_dir(tmp_path),
        dataset_path=dataset,
        out_dir=tmp_path / "replay-out",
        replay_from=local.out_dir,
    )
    local_row = _rows(local)[0]
    replay_row = _rows(replay)[0]

    # 不静默只跑首轮：轮次数与源 run 一致，且逐轮都有可查的 replay trace。
    assert replay_row["turns_executed"] == local_row["turns_executed"] == 2
    assert [item["turn"] for item in replay_row["turn_traces"]] == [1, 2]
    assert [item["status"] for item in replay_row["turn_traces"]] == ["ok", "ok"]
    assert {item["trace_id"] for item in replay_row["turn_traces"]}.isdisjoint(
        {item["trace_id"] for item in local_row["turn_traces"]}
    )
    assert replay_row["trace_id"] == replay_row["turn_traces"][-1]["trace_id"]
    assert replay_row["previous_trace_id"] == local_row["trace_id"]
    # 打分复现 local（末轮 outcome 重评分）。
    assert replay_row["status"] == local_row["status"] == "pass"
    assert replay_row["checks"] == local_row["checks"]
    assert replay_row["metrics"] == local_row["metrics"]

    for index, item in enumerate(replay_row["turn_traces"]):
        record = _record(replay, item["trace_id"])
        assert record.replayed is True
        assert record.previous_trace_id == local_row["turn_traces"][index]["trace_id"]

    # R3：每轮 replay trace 的题面是对应轮的 question（不是统一用末轮问题）。
    local_questions = [
        _record(local, item["trace_id"]).question_hash
        for item in local_row["turn_traces"]
    ]
    replay_questions = [
        _record(replay, item["trace_id"]).question_hash
        for item in replay_row["turn_traces"]
    ]
    assert replay_questions == local_questions
    assert local_questions[0] != local_questions[1]


def test_replay_rejects_single_turn_source_for_multi_turn_case(tmp_path: Path) -> None:
    """R1 B1：源 run 没有 ``turn_traces``（T109 前的单轮产物）→ fail closed。"""
    local = _run(tmp_path, "old-src", [_case()])
    dataset = tmp_path / "old-src.jsonl"
    _rewrite_source_rows(
        local.out_dir,
        lambda row: {k: v for k, v in row.items() if k != "turn_traces"}
        | {"turns_executed": 1, "multi_turn_claimed": False},
    )

    replay = _replay(tmp_path, "old-src-replay", local.out_dir, dataset)
    row = _rows(replay)[0]

    assert row["status"] == "fail", row
    assert row["error"]["code"] == "multi_turn_source_missing"
    assert "2 轮" in row["error"]["message"]
    assert row["multi_turn_claimed"] is True
    # 不写单条 replay 冒充逐轮结果。
    assert row["turn_traces"] == []
    assert row["turns_executed"] == 0
    # 声明层面不把该 case 当成「多轮已验证」。
    declarations = replay.summary["declarations"]["execution"]
    assert declarations["multi_turn_verified"] is False
    assert declarations["multi_turn_error_case_ids"] == ["MT01"]


def test_replay_rejects_source_with_too_few_turn_traces(tmp_path: Path) -> None:
    """R1 B1：源行 ``turn_traces`` 少于 case 轮数 → fail closed（不补齐、不伪造）。"""
    local = _run(tmp_path, "short-src", [_case()])
    dataset = tmp_path / "short-src.jsonl"

    def keep_first_turn(row: dict) -> dict:
        row["turn_traces"] = row["turn_traces"][:1]
        return row

    _rewrite_source_rows(local.out_dir, keep_first_turn)

    replay = _replay(tmp_path, "short-src-replay", local.out_dir, dataset)
    row = _rows(replay)[0]

    assert row["status"] == "fail", row
    assert row["error"]["code"] == "multi_turn_source_incomplete"
    assert "1 条" in row["error"]["message"] and "2" in row["error"]["message"]
    assert row["turn_traces"] == []
    assert row["turns_executed"] == 0


def test_multi_turn_replay_keeps_turn_error_verdict(tmp_path: Path, monkeypatch) -> None:
    """源 run 因中间轮 error 判 fail：replay 复现 fail（不改判 error）。"""
    real_ask = RagIndex.ask

    def flaky(self, question, **kwargs):
        if "城西区" in question:
            raise RuntimeError("probe boom")
        return real_ask(self, question, **kwargs)

    monkeypatch.setattr(RagIndex, "ask", flaky)
    case = _case(
        case_id="MT08",
        turns=(
            {"role": "user", "text": "滨江店的宣传海报在哪里？"},
            {"role": "user", "text": "城西区的宣传海报在哪？"},
        ),
    )
    local = _run(tmp_path, "replay-err-src", [case])
    replay = run_suite(
        "regression",
        "replay",
        corpus_dir=_corpus_dir(tmp_path),
        dataset_path=tmp_path / "replay-err-src.jsonl",
        out_dir=tmp_path / "replay-err-out",
        replay_from=local.out_dir,
    )
    local_row = _rows(local)[0]
    replay_row = _rows(replay)[0]

    assert local_row["status"] == "fail"
    assert replay_row["status"] == "fail"
    assert replay_row["error"] == local_row["error"]
    assert [item["status"] for item in replay_row["turn_traces"]] == ["ok", "error"]
    assert replay_row["turns_executed"] == local_row["turns_executed"] == 2


# --------------------------------------------------------------------------- #
# 5. run 级标记 / 数据契约
# --------------------------------------------------------------------------- #


def test_run_marks_multi_turn_counts_in_manifest_and_summary(tmp_path: Path) -> None:
    result = _run(tmp_path, "marks", [_case(), _case(case_id="MT09", turns=())])
    manifest = json.loads((result.out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["multi_turn_case_count"] == 1
    assert manifest["multi_turn_turns_executed"] == 2
    # 身份字段不被多轮标记污染。
    assert "multi_turn_case_count" not in result.manifest.IDENTITY_FIELDS
    assert "multi_turn_turns_executed" not in result.manifest.IDENTITY_FIELDS

    declarations = result.summary["declarations"]["execution"]
    assert declarations["mode"] == "multi_turn"
    assert declarations["turns_executed"] == 2
    assert declarations["multi_turn_case_count"] == 1
    assert declarations["multi_turn_turns_executed"] == 2
    assert declarations["multi_turn_verified"] is True
    assert declarations["multi_turn_error_case_ids"] == []


@pytest.mark.parametrize(
    ("turns", "code"),
    [
        (({"role": "user", "text": "在吗"}, {"role": "user", "text": " "}), "turn_question_missing"),
        (({"role": "user", "text": "在吗"}, {"role": "assistant", "text": "好的"}), "turn_role_unsupported"),
    ],
)
def test_malformed_turns_fail_closed(tmp_path: Path, turns: tuple, code: str) -> None:
    """R2：多轮 turns 非法时未执行任何轮次 → ``turns_executed=0``、无逐轮记录。"""
    row = _rows(_run(tmp_path, "bad-turns", [_case(case_id="MT10", turns=turns)]))[0]

    assert row["status"] == "error", row
    assert row["error"]["code"] == code
    assert row["multi_turn_claimed"] is True
    assert row["turns_executed"] == 0
    assert row["turn_traces"] == []


def test_gold_error_multi_turn_row_reports_zero_executed_turns(tmp_path: Path) -> None:
    """R2：多轮 case 在首轮执行前 gold 解析失败 → ``turns_executed=0``（不是默认 1）。"""
    case = _case(
        case_id="MT13",
        expected_sources=({"doc_code": "E11", "unit_key": "sheet:物品位置:row:9999"},),
    )
    row = _rows(_run(tmp_path, "gold-error", [case]))[0]

    assert row["status"] == "error", row
    assert row["error"]["code"] == "gold_unresolved"
    assert row["multi_turn_claimed"] is True
    assert row["turns_executed"] == 0
    assert row["turn_traces"] == []


def test_non_mapping_turn_is_rejected_by_the_runner(tmp_path: Path) -> None:
    """``CaseSpec`` 可被直接构造（数据加载层已挡）时，runner 仍 fail closed。"""
    from mktkb.evaluation.runner import _CaseError, _case_turn_questions

    case = _case(case_id="MT11", turns=("不是对象", QUANTITY_TURNS[1]))
    with pytest.raises(_CaseError) as excinfo:
        _case_turn_questions(case)
    assert excinfo.value.code == "turn_invalid"


def test_regression_rg006_is_multi_turn_after_pm_ruling() -> None:
    """RG006 按 PM 裁决更新为多轮口径：末轮只答数量 40，未问字段仍禁止。"""
    cases = {case.case_id: case for case in load_cases(EVAL_DIR / "regression.jsonl")}
    rg006 = cases["RG006"]

    assert len(rg006.turns) == 2
    assert "滨江店的宣传海报的数量" in str(rg006.turns[0].get("text"))
    assert rg006.expected_kind == "answer"
    assert any("40" in value for value in rg006.expected_values)
    # 未问字段的禁止值不得为通过而放宽。
    assert "店内外侧" in rg006.forbidden_values
    assert "QF01" in rg006.forbidden_values
    assert not any("40" in value for value in rg006.forbidden_values)
    assert "多轮" in rg006.notes
