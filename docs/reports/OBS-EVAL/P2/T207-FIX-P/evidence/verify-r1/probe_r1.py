"""T207-FIX-P-R1 独立验收探针：旧/新口径的边界对照（零真实调用，不构造 Provider）。

由来：验收任务要求独立证明 P-R1 的 (a)/(d) 在旧口径下不成立、并复核 (b)/(c) 的断言方向。

复跑方式（全部在工作区之外，不改工作区）：
  1) 建临时目录 <TMP>，把 backend/src/mktkb 整包复制到 <TMP>/src/mktkb；
  2) 用修复前的 service.py 覆盖：
       git show HEAD~1:backend/src/mktkb/conversations/service.py > <TMP>/src/mktkb/conversations/service.py
     （HEAD=ffc9fe5 为 T207-FIX-P 提交；HEAD~1 版 service.py 2408→2398 行、sha256(16)=8b2dbc7539a4f62e，
      无 question 形参）
  3) 新口径：PYTHONPATH=<repo>/backend/src python probe_r1.py
     旧口径：PYTHONPATH=<TMP>/src            python probe_r1.py
输出为 JSON：每项含 case/result/msg；signature 显示是否已带 question 形参。

用例与 P-R1 单测一一对应：
  a  前提值 8000 进"值位置"（有/无 question 对照）
  b  同句式 1.88（问题与来源都没有）仍拒
  c  记录型三样本（不带 question）
  d  对抗性前提 3000（有/无 question 对照）
  x  既有单测#3 的"引用 A 行、用未引用 B 行值"方向复核（两行都在 allowed/evidence，但只引用 A 行）
"""

import inspect
import json
import sys
from types import SimpleNamespace

import mktkb
from mktkb.conversations.service import _validate_answer
from mktkb.providers.types import CompletionOutput, ModelOutputInvalid

ROW = SimpleNamespace(
    id="u-row",
    text="价格单号：PX-0001 / 价格类型：档期特价 / 价格(元)：2.99",
    fields={"价格单号": "PX-0001", "价格类型": "档期特价", "价格(元)": "2.99"},
)
OTHER = SimpleNamespace(
    id="u-other",
    text="价格单号：PX-0020 / 价格类型：档期特价 / 价格(元)：2.5",
    fields={"价格单号": "PX-0020", "价格类型": "档期特价", "价格(元)": "2.5"},
)
POLICY = SimpleNamespace(
    id="u-policy",
    text="第六条 审批权限：单场预算按分档审批，由市场部经理审批。",
    fields={},
)
QUESTION = "2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价是多少？"


def _out(text, *ids):
    return CompletionOutput(text=text, source_ids=tuple(ids))


def _call(name, text, question=None, evidence=(POLICY,), allowed=("u-policy",), cited=("u-policy",), facts=()):
    kwargs = {} if question is None else {"question": question}
    try:
        value, ids = _validate_answer(
            _out(text, *cited), set(allowed), list(facts), evidence=evidence, **kwargs
        )
        return {"case": name, "result": "ACCEPT", "value": value, "ids": ids}
    except ModelOutputInvalid as exc:
        return {"case": name, "result": "REJECT", "msg": str(exc)}
    except TypeError as exc:
        return {"case": name, "result": "TYPE_ERROR", "msg": str(exc)}


def main():
    premise = "单场预算 8000 元的活动由谁审批？"
    report = []
    report.append({
        "signature": "question" in inspect.signature(_validate_answer).parameters,
        "module": mktkb.__file__,
    })
    # a
    report.append(_call("a_8000_value_position_with_question", "审批门槛为 8000 元，由市场部经理审批。", premise))
    report.append(_call("a_8000_value_position_without_question", "审批门槛为 8000 元，由市场部经理审批。"))
    # b
    report.append(_call("b_1.88_with_question", "审批门槛为 1.88 元，由市场部经理审批。", premise))
    # c（记录型三样本：不带 question）
    report.append(_call("c1_record_facts", "位置是B区1号货架第二层。", None,
                        evidence=None, allowed=("u-row",), cited=("u-row",),
                        facts=(("位置", "B区1号货架第二层"),)))
    report.append(_call("c2_ok_verbatim", "价格单号：PX-0001；价格(元)：2.99", None,
                        evidence=(ROW,), allowed=("u-row",), cited=("u-row",)))
    report.append(_call("c3_extra_phone", "价格单号：PX-0001；价格(元)：2.99，联系 010-99999999。", None,
                        evidence=(ROW,), allowed=("u-row",), cited=("u-row",)))
    # d
    bad = "单场预算 3000 元的活动由谁审批？"
    report.append(_call("d_wrong_premise_with_question", "单场预算 3000 元的活动由市场部经理审批。", bad))
    report.append(_call("d_wrong_premise_without_question", "单场预算 3000 元的活动由市场部经理审批。"))
    # x：既有单测#3 的方向（allowed/evidence 含两行，但只引用 u-row）
    tail = "2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价为 2.5 元/瓶。"
    report.append(_call("x_uncited_row_cited_A_only", tail, QUESTION,
                        evidence=(ROW, OTHER), allowed=("u-row", "u-other"), cited=("u-row",)))
    report.append(_call("x_both_rows_cited", tail, QUESTION,
                        evidence=(ROW, OTHER), allowed=("u-row", "u-other"), cited=("u-row", "u-other")))
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
