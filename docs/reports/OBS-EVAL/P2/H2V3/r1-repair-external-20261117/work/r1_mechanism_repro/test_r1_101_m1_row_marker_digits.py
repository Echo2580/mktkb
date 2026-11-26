"""R1-101 / M1：整行渲染的 ``第 {row} 行``（结构数字）按**当前口径**不再算编造。

口径更新（2026-11-17 主人批准的 T-R1-102a 增量）：``value_no_fabricated`` 的允许集合
= 金标/问题/参考答 ∪ 引用证据数字（``citation_number_keys``）∪ **结构 token**
（``citation_structural_number_keys`` 的 locator 整数 + ``outcome.pagination`` 的页头计数）。
产品仍原样写 ``第 N 行`` 是既定行为，本文件不再断言“正文不得出现行号”，改为断言：
- 该形状在当前口径下 ``value_no_fabricated == pass``（``rag/answer.py:594-608`` 的产物）；
- 抽掉结构来源或写入真正未背书的数字，同一答案立刻 fail（对照，防止断言空转）；
- 记录指纹 ``（记录 {ref}）`` 仍为纯 a–f（R0-4/C02 的既有修复，不含十进制数字）。

只用合成实体：甲店 / 立牌 / 两件 / 甲区，行号 7。
运行：``.venv\\Scripts\\python.exe -B -m pytest <本文件> -q -p no:cacheprovider``
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

for _root in Path(__file__).resolve().parents:
    if (_root / "backend" / "src").is_dir():
        sys.path.insert(0, str(_root / "backend" / "src"))
        break

from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.gold import ResolvedGold  # noqa: E402
from mktkb.evaluation.p2_scoring import P2_PAGINATION_NUMBER_KEYS  # noqa: E402
from mktkb.evaluation.scorers import (  # noqa: E402
    EvalCitation,
    EvalOutcome,
    citation_number_keys,
    citation_structural_number_keys,
    score_case,
)
from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402

ROW = 7
FIELDS = {"门店": "甲店", "物品": "立牌", "数量": "两件", "位置": "甲区"}
QUESTION = "列出甲店立牌的全部信息"
UNIT_KEY = f"sheet:合成表:row:{ROW}"


def _locator() -> dict:
    return {
        "sheet": "合成表",
        "row": ROW,
        "header_row": 6,
        "cells": [
            {"column": "A", "display": "甲店", "header": "门店"},
            {"column": "B", "display": "立牌", "header": "物品"},
            {"column": "C", "display": "两件", "header": "数量"},
            {"column": "D", "display": "甲区", "header": "位置"},
        ],
    }


def _index(tmp_path: Path) -> RagIndex:
    index = RagIndex(
        tmp_path / "m1.sqlite3",
        config=RagConfig(
            provider_mode="offline",
            data_dir=tmp_path,
            business_date="2026-10-28",
            chunk_max_chars=420,
            chunk_max_units=3,
            chunk_overlap_units=1,
            top_k=5,
            page_size=10,
            vector_candidate_limit=50,
            rerank_top_n=20,
        ),
    )
    doc = DocumentSpec(
        doc_id="D-syn-m1",
        logical_id="L-syn-m1",
        source_path="corpus/synthetic-m1.xlsx",
        title="合成物品资料",
        file_kind="xlsx",
        version_id="V-syn-m1-v1",
        version_label="当前",
        sha256=hashlib.sha256(b"synthetic-m1").hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    unit = AtomicUnit(
        unit_id=f"U-syn-m1-row{ROW}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key=UNIT_KEY,
        text="；".join(f"{name}: {value}" for name, value in FIELDS.items()),
        fields=dict(FIELDS),
        sheet="合成表",
        locator=_locator(),
        header_row=6,
        row_number=ROW,
        title=doc.title,
    )
    index.add_document(doc, [unit], embed=False)
    return index


def _case() -> CaseSpec:
    return CaseSpec(
        case_id="SYN-M1",
        suite="synthetic",
        split="train",
        stratum="exact",
        business_date="2026-10-28",
        question=QUESTION,
        expected_kind="answer",
        expected_values=("甲区",),
        reference_answer="甲店立牌的位置是甲区",
    )


def _pagination(answer) -> dict:
    """产品自述的分页计数（rag 层等价物）：只取 102a 认的五个计数键。"""

    diagnostics = dict(answer.diagnostics or {})
    plan = dict(diagnostics.get("plan") or {})
    payload = {
        "total": diagnostics.get("total"),
        "page": plan.get("page"),
        "page_size": plan.get("page_size"),
        "returned": diagnostics.get("returned"),
        "has_more": diagnostics.get("has_more"),
        "next_page": diagnostics.get("next_page"),
    }
    return {name: value for name, value in payload.items() if value is not None}


def _outcome(answer, *, text: str | None = None) -> EvalOutcome:
    """按 P2 口径：引用只带 unit locator（含 int 行号与单元格 display），不带答案正文。"""

    citation = EvalCitation(
        doc_code="D01",
        unit_key=UNIT_KEY,
        unit_ids=(f"U-syn-m1-row{ROW}",),
        locator=_locator(),
        text="",
        kind="active",
    )
    return EvalOutcome(
        kind=answer.kind,
        text=answer.text if text is None else text,
        citations=(citation,),
        pagination=_pagination(answer),
    )


def _structural_keys(outcome: EvalOutcome) -> frozenset[str]:
    """102a 的结构集合：locator 整数 + 分页计数（仅 int）；口径与 P2 打分入口一致。"""

    counts = {
        str(value)
        for name in P2_PAGINATION_NUMBER_KEYS
        for value in (outcome.pagination.get(name),)
        if isinstance(value, int) and not isinstance(value, bool)
    }
    return citation_structural_number_keys(outcome.citations) | counts


def _checks(outcome: EvalOutcome, *, structural: bool = True) -> dict[str, tuple[str, dict]]:
    gold = ResolvedGold(
        case_id="SYN-M1",
        requires_ocr=False,
        skipped=False,
        sources=(),
        unit_ids=(f"U-syn-m1-row{ROW}",),
        relevant_unit_ids=(),
    )
    scored = score_case(
        _case(),
        gold,
        outcome,
        cross_explicit_space=True,
        allowed_number_keys=citation_number_keys(outcome.citations),
        structural_number_keys=_structural_keys(outcome) if structural else None,
    )
    return {check.check_id: (check.status, dict(check.evidence)) for check in scored.checks}


def _answer(tmp_path: Path):
    index = _index(tmp_path)
    try:
        return index.ask(QUESTION, user_id="u", conversation_id="c-m1")
    finally:
        index.close()


def test_m1_record_reference_marker_carries_no_decimal_digits(tmp_path: Path) -> None:
    """绿（R0-4/C02 既有修复）：记录指纹只用 a–f，标识数字不得回到答案正文。"""

    answer = _answer(tmp_path)
    assert answer.kind == "answer"
    marker = re.search(r"（记录 ([^）]+)）", answer.text)
    assert marker is not None, answer.text
    assert re.fullmatch(r"[a-f]{8}", marker.group(1)), marker.group(1)


def test_m1_row_number_is_grounded_by_locator_structure(tmp_path: Path) -> None:
    """绿（当前口径）：产品写 ``第 7 行`` 是既定行为，由 locator 整数背书，不算编造。"""

    answer = _answer(tmp_path)
    assert answer.kind == "answer"
    assert "第 7 行" in answer.text, answer.text
    outcome = _outcome(answer)
    checks = _checks(outcome)
    assert checks["value_hit"][0] == "pass", checks
    status, evidence = checks["value_no_fabricated"]
    assert evidence.get("extra") is None, evidence
    assert status == "pass", evidence
    assert evidence.get("structural_numbers", 0) >= 1, evidence


def test_m1_without_structural_source_the_row_number_is_extra(tmp_path: Path) -> None:
    """对照：抽掉结构来源（不传 structural_number_keys），行号立刻变成未背书数字。"""

    answer = _answer(tmp_path)
    checks = _checks(_outcome(answer), structural=False)
    status, evidence = checks["value_no_fabricated"]
    assert status == "fail", evidence
    assert "7" in evidence.get("extra", []), evidence


def test_m1_ungrounded_number_still_fails(tmp_path: Path) -> None:
    """对照：答案里写一个真正没有出处的数字，结构 token 不放行。"""

    answer = _answer(tmp_path)
    fabricated = _outcome(answer, text=answer.text + "\n另有 9 家分店正在装修。")
    checks = _checks(fabricated)
    status, evidence = checks["value_no_fabricated"]
    assert status == "fail", evidence
    assert evidence.get("extra") == ["9"], evidence
