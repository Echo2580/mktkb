"""T101：法规题整段抽取（`rag/answer.py` 窄分支）单元用例。

- 法规题（`is_regulation_question`）走整段引用，同一段的“施行 + 废止”两句一起返回；
- 非法规题仍按原单句抽取，`根据资料，<最佳单句>` 逐字节不变。
"""

from __future__ import annotations

from typing import Any

from mktkb.rag import answer as answer_module
from mktkb.rag.answer import _best_sentence, _document_fallback
from mktkb.rag.query import is_regulation_question
from mktkb.rag.types import (
    Citation,
    EvidenceItem,
    QueryPlan,
    QueryState,
    RetrievalResult,
)

LEGAL_QUESTION = "《明码标价和禁止价格欺诈规定》自何时起施行？同时废止了哪两个规定？"
P39 = (
    "第二十七条 本规定自 2022年7月1日起施行。"
    "2000年10月31日原中华人民共和国国家发展计划委员会令第8号发布的《关于商品和服务实行明码标价的规定》、"
    "2001年11月7日原中华人民共和国国家发展计划委员会令第9号发布的《禁止价格欺诈行为的规定》同时废止。"
)


class _Index:
    def revision(self) -> int:
        return 1


class _Validator:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def validate_document_text(self, text: str, evidence: Any) -> None:
        self.texts.append(text)


def _evidence(chunk_id: str, text: str, unit_key: str) -> EvidenceItem:
    citation = Citation(
        source_id=chunk_id,
        doc_id="L02",
        source_path="legal/明码标价和禁止价格欺诈规定（国家市场监督管理总局令第56号）.docx",
        title="明码标价和禁止价格欺诈规定（国家市场监督管理总局令第56号）",
        version_id="L02-v1",
        version_label="当前",
        revision=1,
        locator={"unit_keys": [unit_key]},
        text=text,
        kind="text",
    )
    return EvidenceItem(
        chunk_id=chunk_id,
        doc_id="L02",
        source_path=citation.source_path,
        title=citation.title,
        version_id="L02-v1",
        version_label="当前",
        revision=1,
        kind="text",
        text=text,
        sheet=None,
        locator={"unit_keys": [unit_key]},
        fields={},
        citation=citation,
    )


def _run(question: str, evidence: list[EvidenceItem], monkeypatch) -> tuple[Any, list[EvidenceItem]]:
    monkeypatch.setattr(answer_module, "_citation", lambda index, chunk: chunk.citation)
    plan = QueryPlan(
        question=question,
        mode="document",
        query_text=question,
        field_role=None,
        field_label=None,
        filters={},
        terms=(),
        state=QueryState(),
    )
    result = RetrievalResult(
        plan=plan,
        revision=1,
        evidence=list(evidence),
        total=len(evidence),
        returned=len(evidence),
    )
    answer = _document_fallback(_Index(), plan, result, _Validator(), {}, 0.0, reason=None)
    return answer, evidence


def _fixture_evidence() -> list[EvidenceItem]:
    return [
        _evidence(
            "chunk-p7",
            "正文（原文）\n《明码标价和禁止价格欺诈规定》已经\n2022年3月22日市场监管总局第5次局务会议通过，自2022年7月1日起施行。",
            "paragraph:7",
        ),
        _evidence("chunk-p39", f"正文（原文）\n{P39}", "paragraph:39"),
    ]


def test_regulation_question_returns_whole_clause_paragraph(monkeypatch) -> None:
    answer, _ = _run(LEGAL_QUESTION, _fixture_evidence(), monkeypatch)

    assert answer.kind == "answer"
    assert answer.text == f"根据资料，{P39}"
    assert "2022年7月1日" in answer.text
    assert "《关于商品和服务实行明码标价的规定》" in answer.text
    assert "《禁止价格欺诈行为的规定》" in answer.text
    assert answer.citations[0].locator["unit_keys"] == ["paragraph:39"]


def test_non_regulation_question_keeps_single_sentence(monkeypatch) -> None:
    question = "2022年3月22日通过了什么？"
    assert not is_regulation_question(question)
    evidence = _fixture_evidence()
    answer, _ = _run(question, evidence, monkeypatch)

    expected_sentence = _best_sentence(question, evidence)
    assert expected_sentence is not None
    assert answer.text == f"根据资料，{expected_sentence}"
    assert P39 not in answer.text
