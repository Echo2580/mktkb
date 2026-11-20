"""R0/C12 正文面召回的确定性单元复现（合成索引，无真实数据）。

与集成用例（``tests/integration/test_r0_c12_text_face_recall_synthetic.py``）互补：
这里不开向量通道（合成索引 ``embed=False``），只留 lexical/exact 两条通路——即 live 下
"正文单元不在向量窗口内"时的确定性形状。

- 记录面：``_exact_recall`` 靠 filters 命中记录行（与 terms 无关）；
- 正文面：filters 对 text chunk 无效（``filters_norm`` 是空字典），只有 terms 能用；
  修复前正文面 ``terms=()`` → ``match_expression(()) is None`` → 空集（C12 根因）。
"""

from __future__ import annotations

import hashlib

from mktkb.conversations import intent as intent_module
from mktkb.qa.service import QaEngine
from mktkb.rag import AtomicUnit, DocumentSpec

QUESTION = "甲店立牌在哪里？"
NOTICE_TEXT = "通知：甲店立牌下月起迁至乙区"


def _doc(
    *,
    doc_id: str,
    title: str,
    source_path: str,
    file_kind: str,
    state: str = "active",
    is_current: bool = True,
    version_label: str = "当前",
) -> DocumentSpec:
    return DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=source_path,
        title=title,
        file_kind=file_kind,
        version_id=f"V-{doc_id}",
        version_label=version_label,
        sha256=hashlib.sha256(doc_id.encode("utf-8")).hexdigest(),
        is_current=is_current,
        state=state,
        business_date="2026-10-28",
    )


def _record_unit(doc: DocumentSpec) -> AtomicUnit:
    fields = {"门店": "甲店", "物品": "立牌", "位置": "甲区"}
    return AtomicUnit(
        unit_id="U-c12-row",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key="sheet:合成表:row:7",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=fields,
        sheet="合成表",
        locator={"sheet": "合成表", "row": 7, "header_row": 1},
        header_row=1,
        row_number=7,
        title=doc.title,
    )


def _notice_unit(doc: DocumentSpec, *, unit_id: str) -> AtomicUnit:
    return AtomicUnit(
        unit_id=unit_id,
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="paragraph",
        ordinal=0,
        unit_key="paragraph:1",
        text=NOTICE_TEXT,
        fields={},
        sheet=None,
        locator={"paragraph": 1},
        title=doc.title,
    )


def _engine(rag_index, tmp_path) -> QaEngine:
    """把 fixture 索引挂到产品入口上（只为复用同一份合成索引，不建库）。"""

    engine = QaEngine(db_factory=None, index_path=tmp_path / "qa-index.sqlite3")
    engine._index = rag_index  # noqa: SLF001 - 合成装配：跳过从产品库同步
    engine.ensure_ready = lambda **_kwargs: None  # noqa: SLF001 - 同上
    return engine


def _seed(rag_index):
    """docA 记录行（xlsx）+ docB 正文通知（pdf），都不建向量。"""

    row_doc = _doc(
        doc_id="D-c12-row",
        title="合成物品位置表",
        source_path="synthetic/D-c12-row.xlsx",
        file_kind="xlsx",
    )
    row = _record_unit(row_doc)
    rag_index.add_document(row_doc, [row], embed=False)

    notice_doc = _doc(
        doc_id="D-c12-notice",
        title="合成物料位置通知",
        source_path="synthetic/D-c12-notice.pdf",
        file_kind="pdf",
    )
    notice = _notice_unit(notice_doc, unit_id="U-c12-text")
    rag_index.add_document(notice_doc, [notice], embed=False)

    lexicon = intent_module.EntityLexicon(store_labels=("甲店",), item_labels=("立牌",))
    plan = intent_module.parse_question(QUESTION, lexicon=lexicon)
    assert plan.intent is not None and plan.intent.mode == "record"
    assert plan.intent.terms == (), "记录型意图不带检索词（C12 的前提）"
    return plan, row, notice


def test_c12_document_face_recall_comes_from_question_terms(rag_index, tmp_path):
    plan, row, notice = _seed(rag_index)
    engine = _engine(rag_index, tmp_path)

    # 修复前的形状：产品只交记录面参数 → 正文单元不可召回（只剩记录行）。
    record_only = engine.candidate_unit_ids_for_intent(
        mode="record",
        terms=plan.intent.terms,
        entity_filters=plan.intent.entity_filters,
    )
    assert record_only == {row.unit_id}, record_only

    # 修复后：正文面拿到题面派生的检索词 → lexical 命中正文通知。
    document_terms = intent_module.document_terms(QUESTION)
    assert "甲店" in document_terms and "立牌" in document_terms, document_terms
    full = engine.candidate_unit_ids_for_intent(
        mode="record",
        terms=plan.intent.terms,
        entity_filters=plan.intent.entity_filters,
        document_terms=document_terms,
    )
    assert full == {row.unit_id, notice.unit_id}, full


def test_c12_superseded_notice_text_stays_outside_candidates(rag_index, tmp_path):
    """反例②：旧版本（state=superseded）正文同样含“迁至乙区”，也不得进候选。

    这是 ``rag/retrieval.py`` 基表 ``state == "active" and is_current`` 的效果，
    不能因为正文面有了检索词就被放大召回。
    """

    plan, row, notice = _seed(rag_index)
    old_doc = _doc(
        doc_id="D-c12-old",
        title="合成物料位置通知（历史）",
        source_path="synthetic/D-c12-old.pdf",
        file_kind="pdf",
        state="superseded",
        is_current=False,
        version_label="历史",
    )
    old = _notice_unit(old_doc, unit_id="U-c12-old")
    rag_index.add_document(old_doc, [old], embed=False)

    engine = _engine(rag_index, tmp_path)
    full = engine.candidate_unit_ids_for_intent(
        mode="record",
        terms=plan.intent.terms,
        entity_filters=plan.intent.entity_filters,
        document_terms=intent_module.document_terms(QUESTION),
    )
    assert row.unit_id in full and notice.unit_id in full, full
    assert old.unit_id not in full, full
