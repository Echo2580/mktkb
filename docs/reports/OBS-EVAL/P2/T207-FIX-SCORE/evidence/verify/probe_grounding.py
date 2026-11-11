
r"""T207-FIX-SCORE 验收复跑 2/2：数字判定边界（引用证据 pass / 非证据仍 fail / 不洗白）。

用法（cwd=仓库根，PYTHONPATH=backend/src）：
  .venv\Scripts\python.exe -X utf8 -B <本文件>
"""
from __future__ import annotations

import json
from pathlib import Path

from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.gold import ResolvedGold
from mktkb.evaluation.p2_scoring import normalize_product_outcome
from mktkb.evaluation.scorers import (
    EvalCitation,
    EvalFact,
    EvalOutcome,
    EvalRetrieved,
    citation_number_keys,
    score_case,
)

ROOT = Path(r"D:/GPT项目/市场部AI知识库")
CASES = {c.case_id: c for c in (
    CaseSpec.from_dict(json.loads(line))
    for line in (ROOT / "fixtures/evaluation/b0.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
)}
Q09 = CASES["Q09"]
UNIT_ID = "11111111-1111-4111-8111-111111111111"
ROW_LOCATOR = {
    "sheet": "店家信息", "header_row": 4, "row": 5, "column_index": 3,
    "cells": [
        {"column": "A", "column_index": 1, "display": "S01", "header": "标识"},
        {"column": "B", "column_index": 2, "display": "城东店", "header": "店家"},
        {"column": "C", "column_index": 3, "display": "模拟联系人·陈宁", "header": "联系人"},
        {"column": "D", "column_index": 4, "display": "010-00000001", "header": "电话"},
        {"column": "E", "column_index": 5, "display": "示例市示例路18号（模拟）", "header": "地址"},
        {"column": "F", "column_index": 6, "display": "合作中", "header": "合作状态"},
    ],
}
ROW_TEXT = ("城东店的联系人：模拟联系人·陈宁；店家：城东店；电话：010-00000001；"
            "地址：示例市示例路18号（模拟）；合作状态：合作中。")


def gold() -> ResolvedGold:
    return ResolvedGold(case_id=Q09.case_id, requires_ocr=False, skipped=False,
                        sources=(), unit_ids=(), relevant_unit_ids=())


def cite(locator=None, text="", doc_code="D02") -> EvalCitation:
    return EvalCitation(doc_code=doc_code, unit_key="sheet:店家信息:row:5", unit_ids=(UNIT_ID,),
                        locator={} if locator is None else locator, text=text, kind="active")


def score(text: str, citations, **kwargs) -> dict:
    outcome = EvalOutcome(kind="answer", text=text, citations=tuple(citations), path="rag")
    kwargs.setdefault("allowed_number_keys", citation_number_keys(outcome.citations))
    result = score_case(Q09, gold(), outcome, **kwargs)
    check = result.check("value_no_fabricated")
    return {"case": result.status, "vnf": check.status, "evidence": dict(check.evidence),
            "checks": {c.check_id: c.status for c in result.checks}}


def keys(locator, text="") -> list[str]:
    return sorted(citation_number_keys([cite(locator, text=text)]))

result: dict[str, object] = {}

# Q09 冻结题的应答原文；被引用行就是 D02 店家信息 row 5。
result["real_row_keys"] = keys(ROW_LOCATOR)
default_checks = score(ROW_TEXT, [cite(ROW_LOCATOR)], allowed_number_keys=None)
optin = score(ROW_TEXT, [cite(ROW_LOCATOR)])
result["A_row_echo_default"] = default_checks
result["A_row_echo_optin"] = optin
result["A_only_vnf_changes"] = {k: (default_checks["checks"][k], optin["checks"][k])
                                for k in optin["checks"] if default_checks["checks"][k] != optin["checks"][k]}

# 同一段回答、无引用证据。
result["B_no_citation"] = score(ROW_TEXT, [])
# 引用行里没有的数字。
result["C_extra_7"] = score(ROW_TEXT + "另有 7 家分店正在装修。", [cite(ROW_LOCATOR)])

# 容器键：document_name / file_name / path / sheet 里的编号不进入允许集。
container = {"document_name": "D02_合作店家信息.xlsx", "file_name": "D02-店家信息.xlsx",
             "path": "corpus/D02_合作店家信息.xlsx", "sheet": "店家信息"}
result["D_container_keys"] = keys(container)
result["D_container_score"] = score("模拟联系人·陈宁，见 D02 文件。", [cite(container)])
result["D2_nested_container_keys"] = keys({"meta": {"document_name": "D02_合作店家信息.xlsx",
                                                   "file_name": "D02.xlsx", "doc_name": "D02"}})

# 整数型 locator 键（row/header_row/column_index）不参与。
ints = {"sheet": "店家信息", "row": 5, "header_row": 4, "column_index": 3}
result["E_int_keys"] = keys(ints)
result["E_int_score"] = score("模拟联系人·陈宁，第 5 行。", [cite(ints)])

# locator 的键名里有数字也不算。
result["F_keyname_keys"] = keys({"cell_18": {"display": "城东店"}})
result["F_keyname_score"] = score("模拟联系人·陈宁，18 号。", [cite({"cell_18": {"display": "城东店"}})])

# citation.text 属于允许来源（本包设计口径）；默认路径仍忽略。
cited_text = "联系人：模拟联系人·陈宁，分机 8021"
result["G_text_keys"] = keys({}, text=cited_text)
result["G_text_optin"] = score("模拟联系人·陈宁，分机 8021。", [cite({}, text=cited_text)])
result["G_text_default"] = score("模拟联系人·陈宁，分机 8021。", [cite({}, text=cited_text)],
                                 allowed_number_keys=None)

# retrieved / facts 不是证据。
retrieved_outcome = EvalOutcome(kind="answer", text="模拟联系人·陈宁，另有 7 件。", citations=(),
                                retrieved=(EvalRetrieved(doc_code="D02", unit_ids=(UNIT_ID,),
                                                         locator={"cells": [{"display": "7"}]}),))
r = score_case(Q09, gold(), retrieved_outcome, allowed_number_keys=citation_number_keys(retrieved_outcome.citations))
result["H_retrieved_only"] = {"case": r.status, "vnf": r.check("value_no_fabricated").status,
                              "evidence": dict(r.check("value_no_fabricated").evidence)}
facts_outcome = EvalOutcome(kind="answer", text="模拟联系人·陈宁，另有 7 件。", citations=(),
                            facts=(EvalFact(doc_code="D02", entity_key="e", value="7"),))
r = score_case(Q09, gold(), facts_outcome, allowed_number_keys=citation_number_keys(facts_outcome.citations))
result["I_facts_only"] = {"case": r.status, "vnf": r.check("value_no_fabricated").status,
                          "evidence": dict(r.check("value_no_fabricated").evidence)}

# 产品 source 级 document_name（不在 locator 里）不能被当成证据。
product = {"kind": "answer", "text": "模拟联系人·陈宁，见第 2 页。",
           "sources": [{"source_id": UNIT_ID, "document_name": "D02_合作店家信息.xlsx",
                        "version_number": 1, "status": "active", "locator": {"sheet": "店家信息"}}]}
outcome = normalize_product_outcome({"product": product}, document_codes={"D02_合作店家信息.xlsx": "D02"})
r = score_case(Q09, gold(), outcome, allowed_number_keys=citation_number_keys(outcome.citations))
result["J_source_document_name"] = {"keys": sorted(citation_number_keys(outcome.citations)),
                                    "case": r.status, "vnf": r.check("value_no_fabricated").status,
                                    "evidence": dict(r.check("value_no_fabricated").evidence)}

# 已知边界：locator 里非内容元数据字符串（number_format / sheet / column）也会成为数字来源。
meta_keys = {
    "number_format_0_00": keys({"sheet": "店家信息", "cells": [{"display": "城东店", "number_format": "0.00"}]}),
    "sheet_year": keys({"sheet": "2026Q4", "cells": [{"display": "城东店"}]}),
    "column_ref_A1": keys({"sheet": "店家信息", "cells": [{"column": "A1", "display": "城东店"}]}),
    "generic_title": keys({"title": "2026年Q4渠道价目表"}),
}
result["K_metadata_keys"] = meta_keys

# 已知边界：允许集合是"本轮全部引用"的并集，不是"逐条声明"；多引一行即可洗白该行数字。
row5 = cite(ROW_LOCATOR)
row7 = cite({"sheet": "店家信息", "row": 7,
             "cells": [{"display": "S03"}, {"display": "南湖店"}, {"display": "8"}]})
multi = score(ROW_TEXT + "另有 8 家分店。", [row5, row7])
result["L_multi_citation_union"] = {"keys": sorted(citation_number_keys([row5, row7])),
                                    "case": multi["case"], "vnf": multi["vnf"],
                                    "evidence": multi["evidence"]}

print(json.dumps(result, ensure_ascii=False, indent=1))
