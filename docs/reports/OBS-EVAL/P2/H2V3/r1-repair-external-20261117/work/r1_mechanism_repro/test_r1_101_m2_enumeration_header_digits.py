"""R1-101 / M2：枚举页头 ``共 {total} 条，当前第 {page} 页显示 {returned} 条`` 按当前口径不再算编造。

口径更新（2026-11-17 主人批准的 T-R1-102a 增量）：``value_no_fabricated`` 的允许集合
= 金标/问题/参考答 ∪ 引用证据数字（``citation_number_keys``）∪ **结构 token**
（locator 整数 + ``outcome.pagination`` 的页头计数 ``total``/``page``/``page_size``/
``returned``/``next_page``，仅 int）。因此：
- 页头计数由产品分页自述背书 → 当前口径下 ``value_no_fabricated == pass``；
- 页头写一个分页里没有的计数、或产品没给 pagination 时，同一段文本仍判编造（对照）。

合成数据：甲店 + 立牌两条记录，位置分别是甲区/乙区（纯文本，不含数字）。
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

ROWS = (
    {"门店": "甲店", "物品": "立牌", "位置": "甲区"},
    {"门店": "甲店", "物品": "立牌", "位置": "乙区"},
)
QUESTION = "列出甲店立牌的位置"
HEADER = re.compile(r"共 (\d+) 条，当前第 (\d+) 页显示 (\d+) 条")


def _locator(row: int, fields: dict) -> dict:
    return {
        "sheet": "合成表",
        "row": row,
        "header_row": 6,
        "cells": [
            {"column": chr(65 + index), "display": str(value), "header": str(name)}
            for index, (name, value) in enumerate(fields.items())
        ],
    }


def _index(tmp_path: Path, rows=ROWS, name: str = "m2") -> RagIndex:
    index = RagIndex(
        tmp_path / f"{name}.sqlite3",
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
        doc_id="D-syn-m2",
        logical_id="L-syn-m2",
        source_path="corpus/synthetic-m2.xlsx",
        title="合成物品资料",
        file_kind="xlsx",
        version_id="V-syn-m2-v1",
        version_label="当前",
        sha256=hashlib.sha256(b"synthetic-m2").hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    units = []
    for ordinal, fields in enumerate(rows):
        row = 7 + ordinal
        units.append(
            AtomicUnit(
                unit_id=f"U-syn-m2-row{row}",
                doc_id=doc.doc_id,
                version_id=doc.version_id,
                kind="table_row",
                ordinal=ordinal,
                unit_key=f"sheet:合成表:row:{row}",
                text="；".join(f"{name}: {value}" for name, value in fields.items()),
                fields=dict(fields),
                sheet="合成表",
                locator=_locator(row, fields),
                header_row=6,
                row_number=row,
                title=doc.title,
            )
        )
    index.add_document(doc, units, embed=False)
    return index


def _case() -> CaseSpec:
    return CaseSpec(
        case_id="SYN-M2",
        suite="synthetic",
        split="train",
        stratum="exact",
        business_date="2026-10-28",
        question=QUESTION,
        expected_kind="answer",
        expected_values=("甲区",),
        reference_answer="甲区",
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


def _outcome(answer, *, text: str | None = None, pagination: dict | None = None) -> EvalOutcome:
    citations = tuple(
        EvalCitation(
            doc_code="D01",
            unit_key=f"sheet:合成表:row:{7 + ordinal}",
            unit_ids=(f"U-syn-m2-row{7 + ordinal}",),
            locator=_locator(7 + ordinal, fields),
            text="",
            kind="active",
        )
        for ordinal, fields in enumerate(ROWS)
    )
    return EvalOutcome(
        kind=answer.kind,
        text=answer.text if text is None else text,
        citations=citations,
        pagination=_pagination(answer) if pagination is None else dict(pagination),
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


def _checks(outcome: EvalOutcome) -> dict[str, tuple[str, dict]]:
    gold = ResolvedGold(
        case_id="SYN-M2",
        requires_ocr=False,
        skipped=False,
        sources=(),
        unit_ids=tuple(f"U-syn-m2-row{7 + ordinal}" for ordinal in range(len(ROWS))),
        relevant_unit_ids=(),
    )
    scored = score_case(
        _case(),
        gold,
        outcome,
        cross_explicit_space=True,
        allowed_number_keys=citation_number_keys(outcome.citations),
        structural_number_keys=_structural_keys(outcome),
    )
    return {check.check_id: (check.status, dict(check.evidence)) for check in scored.checks}


def _answer(tmp_path: Path):
    index = _index(tmp_path)
    try:
        return index.ask(QUESTION, user_id="u", conversation_id="c-m2")
    finally:
        index.close()


def test_m2_enumeration_header_counts_are_not_scored_as_fabricated(tmp_path: Path) -> None:
    """绿（当前口径）：页头计数由 ``outcome.pagination`` 背书，value_no_fabricated pass。"""

    answer = _answer(tmp_path)
    assert answer.kind == "answer"
    header = HEADER.search(answer.text)
    assert header is not None, answer.text
    outcome = _outcome(answer)
    checks = _checks(outcome)
    assert checks["value_hit"][0] == "pass", checks
    status, evidence = checks["value_no_fabricated"]
    assert evidence.get("extra") is None, evidence
    assert status == "pass", evidence
    assert evidence.get("structural_numbers", 0) >= 2, evidence


def test_m2_page_counts_come_from_pagination_not_from_citation_text(tmp_path: Path) -> None:
    """绿（口径锚点）：计数不在 citation_number_keys 里，只由结构集合（分页）提供。"""

    answer = _answer(tmp_path)
    header = HEADER.search(answer.text)
    assert header is not None, answer.text
    total, page, returned = header.groups()
    outcome = _outcome(answer)
    evidence_keys = citation_number_keys(outcome.citations)
    structural_keys = _structural_keys(outcome)
    for count in (total, page, returned):
        assert count not in evidence_keys, (count, sorted(evidence_keys))
        assert count in structural_keys, (count, sorted(structural_keys))


def test_m2_header_claiming_more_than_pagination_still_fails(tmp_path: Path) -> None:
    """对照：页头写 3 条、产品分页计数是 2 → 3 没有出处，仍判编造。"""

    answer = _answer(tmp_path)
    claim = HEADER.search(answer.text)
    assert claim is not None, answer.text
    total = claim.group(1)
    fabricated = _outcome(answer, text=answer.text.replace(f"共 {total} 条", "共 3 条", 1))
    checks = _checks(fabricated)
    status, evidence = checks["value_no_fabricated"]
    assert status == "fail", evidence
    assert evidence.get("extra") == ["3"], evidence


def test_m2_header_without_pagination_still_fails(tmp_path: Path) -> None:
    """对照：同一段页头答案但产品没给 pagination → 计数没有出处，仍判编造。"""

    answer = _answer(tmp_path)
    checks = _checks(_outcome(answer, pagination={}))
    status, evidence = checks["value_no_fabricated"]
    assert status == "fail", evidence
    assert set(evidence.get("extra", ())) == {"1", "2"}, evidence


def test_m2_adjacent_single_record_field_answer_is_unchanged(tmp_path: Path) -> None:
    """绿：单条记录的单字段问法不受影响（区分“页头计数”与“字段值渲染”）。"""

    index = _index(tmp_path, rows=ROWS[:1], name="m2-single")
    try:
        answer = index.ask("甲店立牌的位置在哪？", user_id="u", conversation_id="c-m2-single")
    finally:
        index.close()
    assert answer.kind == "answer"
    assert "甲区" in answer.text and "乙区" not in answer.text
    assert [fact.value for fact in answer.facts] == ["甲区"]
