"""P1-FIX/A：越界财务指标拒答 + 同义改写/正向控制的公开回归数据。

数据文件：``fixtures/evaluation/refusal-controls-2026-11-10.jsonl``（独立新增、带固定
``label_version``；不改冻结的 b0/badcase/regression 历史）。本文件只读公开语料
``corpus/enterprise-20261101`` 构建 offline 索引（零真实 provider、零网络），验证：

1. 公司级经营/财务指标（营收/利润率/净利润等）在语料无支持时明确拒答，不编造来源；
2. 同义改写/不同句式同样拒答（不是只匹配 RG005/RG007 两句）；
3. 确有已发布资料支持的问题、法规/制度/采购价格/台账查询不被误拒答；
4. 冻结 regression 的 RG005/RG007 原检查通过（kind=no_answer / refusal_expected）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mktkb.evaluation.corpus import build_suite_index, load_suite_corpus
from mktkb.rag.query import (
    financial_metric_question,
    texts_support_financial_metric,
)

ROOT = Path(__file__).resolve().parents[3]
CONTROLS = ROOT / "fixtures" / "evaluation" / "refusal-controls-2026-11-10.jsonl"
REGRESSION = ROOT / "fixtures" / "evaluation" / "regression.jsonl"
LABEL_VERSION = "p1fix-refusal-controls-2026-11-10"
FORBIDDEN_REFUSAL_CLAIMS = ("MODEL_UNAVAILABLE", "服务暂不可用", "服务调用失败")


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def regression_index(tmp_path_factory: pytest.TempPathFactory):
    """离线索引（只读公开语料）；同一模块内复用，零真实调用。"""
    root = tmp_path_factory.mktemp("p1fix-refusal")
    corpus = load_suite_corpus("regression")
    index, _stats = build_suite_index(corpus, root / "index.sqlite3")
    try:
        yield index
    finally:
        index.close()


def _ask(index, question: str, conversation: str):
    return index.ask(question, user_id="p1fix", conversation_id=conversation)


# ---------------------------------------------------------------------------
# 1. 数据文件契约（独立版本、与冻结套件隔离）
# ---------------------------------------------------------------------------


def test_control_fixture_is_independent_and_versioned() -> None:
    cases = _load_jsonl(CONTROLS)
    assert len(cases) >= 20
    assert {case["label_version"] for case in cases} == {LABEL_VERSION}
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert all(case["question"].strip() for case in cases)
    # 明确不是冻结套件的一部分（不改历史 fixture / 评分规则）。
    assert CONTROLS.name not in {"b0.jsonl", "badcase.jsonl", "regression.jsonl", "holdout-questions.jsonl"}

    no_answer = [case for case in cases if case["should_refuse"]]
    supported = [case for case in cases if not case["should_refuse"]]
    assert len(no_answer) >= 10
    assert len(supported) >= 10


# ---------------------------------------------------------------------------
# 2. 意图/资料支持判定的单元口径
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    (
        "公司今年营收是多少",
        "公司今年的利润率是多少",
        "公司今年的营业收入是多少？",
        "今年公司营业额多少？",
        "帮我查一下公司今年的营收数据",
        "公司今年净利润是多少？",
        "公司今年的毛利率是多少？",
        "公司去年的亏损是多少？",
    ),
)
def test_financial_metric_detection_covers_paraphrases(question: str) -> None:
    assert financial_metric_question(question) is not None


@pytest.mark.parametrize(
    "question",
    (
        "《明码标价和禁止价格欺诈规定》自何时起施行？",
        "《明码标价和禁止价格欺诈规定》对价格欺诈的处罚是什么？",
        "活动预算4000元找谁审批？",
        "黄金陈列位的高度区间是多少？",
        "促销费用率是多少？",
        "滨江店的宣传海报的采购价格是多少？",
        "滨江店的宣传海报在哪里？",
        "Q3 销量是多少？",
        "档期物料要提前多少天提报需求？",
    ),
)
def test_policy_regulation_price_and_ledger_questions_are_not_out_of_scope(question: str) -> None:
    """法规/制度/价格/台账/已支持指标题不得被“财务指标越界”规则识别。"""
    assert financial_metric_question(question) is None


def test_metric_support_judgement_requires_metric_value_in_evidence() -> None:
    assert texts_support_financial_metric("营收", ["2026 年公司营收 4812 万元，环比 +6.4%"])
    assert texts_support_financial_metric("利润率", ["Q3 净利润率 8.6%，超过目标"])
    # 只提到指标词、没有数值：不能当作“资料支持”。
    assert not texts_support_financial_metric("毛利", ["特价申请须同时提交毛利影响测算，并由财务部会签。"])
    assert not texts_support_financial_metric("营收", ["公司资料管理规范"])
    assert not texts_support_financial_metric("营收", [""])


# ---------------------------------------------------------------------------
# 3. 语料级：越界拒答 + 正向控制
# ---------------------------------------------------------------------------


def test_out_of_scope_financial_questions_refuse_without_fabricated_sources(regression_index) -> None:
    cases = [case for case in _load_jsonl(CONTROLS) if case["should_refuse"]]
    assert cases
    for case in cases:
        answer = _ask(regression_index, case["question"], f"refusal:{case['case_id']}")
        assert answer.kind == "no_answer", (case["case_id"], answer.kind, answer.text)
        assert answer.reason == case["expect_reason"], (case["case_id"], answer.reason)
        assert answer.reason == "UNSUPPORTED_FINANCIAL_METRIC"
        assert "没有可支撑" in answer.text, answer.text
        assert "根据资料" not in answer.text, answer.text
        assert answer.citations == [], answer.text
        for claim in FORBIDDEN_REFUSAL_CLAIMS:
            assert claim not in answer.text, (claim, answer.text)


def test_supported_questions_are_still_answered(regression_index) -> None:
    cases = [case for case in _load_jsonl(CONTROLS) if not case["should_refuse"]]
    assert cases
    for case in cases:
        answer = _ask(regression_index, case["question"], f"control:{case['case_id']}")
        assert answer.kind == case["expected_kind"], (
            case["case_id"],
            answer.kind,
            answer.reason,
            answer.text,
        )
        assert answer.reason != "UNSUPPORTED_FINANCIAL_METRIC", (case["case_id"], answer.text)
        for value in case.get("expect_values") or ():
            assert value in answer.text, (case["case_id"], value, answer.text)
        for value in case.get("forbidden") or ():
            assert value not in answer.text, (case["case_id"], value, answer.text)
        if case["expected_kind"] == "answer":
            # 正常答案有内部 citations（产品层在同一可见性/版本下映射为来源）。
            assert answer.citations, (case["case_id"], answer.text)


# ---------------------------------------------------------------------------
# 4. 冻结 regression 的 RG005/RG007 原检查
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", ("RG005", "RG007"))
def test_frozen_regression_refusals_still_pass(regression_index, case_id: str) -> None:
    cases = {case["case_id"]: case for case in _load_jsonl(REGRESSION)}
    case = cases[case_id]
    answer = _ask(regression_index, case["question"], f"frozen:{case_id}")
    assert answer.kind == case["expected_kind"], (case_id, answer.kind, answer.text)
    assert answer.kind == "no_answer", answer.text
    assert bool(case["should_refuse"]) is True
    assert answer.citations == [], answer.text
