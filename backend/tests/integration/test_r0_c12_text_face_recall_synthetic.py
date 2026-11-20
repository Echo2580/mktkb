"""R0/C12 正文面召回的合成复现（无真实业务数据、不读 fixtures）。

结构性质（去身份化的最小形状）：
- 记录行 docA（xlsx）：``{门店: 甲店, 物品: 立牌, 位置: 甲区}`` → 记录单元 U-row；
- 正文 docB（pdf）：「通知：甲店立牌下月起迁至乙区」 → 正文单元 U-text；
- 问题「甲店立牌在哪里？」是 record 型意图（``terms=()``、``requested_fields=('位置',)``）。

**C12 的根因**：记录型意图不带检索词，``candidate_unit_ids_for_intent`` 里补正文面的
那份计划 （``qa/service.py``） 既没有 terms 也没有可用 filters（text chunk 的
``filters_norm`` 是空字典，``rag/retrieval.py`` 对非 record 模式也不应用 store/item 过滤），
于是 ``match_expression(())`` 返回 None，lexical 直接空集——正文单元只能靠全库向量
top-50 偶然命中，候选上界恒为 1。修复是给正文面计划喂题面词（记录面计划不变）。

本文件断言的是**产品路径**（不是直接调内部函数）：产品调用
``candidate_unit_ids_for_intent`` 时是否把 ``document_terms(question)`` 交下去、候选上界
是否因此包含正文单元、以及候选变大是否改变 legacy 的作答。
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from datetime import datetime, timezone

from mktkb.conversations import intent as intent_module
from mktkb.documents.lifecycle import prepare_version_index
from mktkb.documents.models import (
    Document,
    DocumentVersion,
    KnowledgeState,
    SourceUnit,
)

QUESTION = "甲店立牌在哪里？"
NOTICE_TEXT = "通知：甲店立牌下月起迁至乙区"


def _session(app):
    return app.state.db.session()


def _add_published_document(
    app,
    *,
    name: str,
    file_type: str,
    units: list[dict],
) -> tuple[str, list[str]]:
    """直接写入一条已发布资料（跳过上传/worker：本用例只关心召回与作答形状）。

    与 ``test_lifecycle`` 的直写装配同口径：Document + published DocumentVersion +
    SourceUnit，然后把 ``KnowledgeState.revision`` 推进一格（rag 侧据此增量同步），
    最后 ``prepare_version_index`` 建 legacy 检索索引（FTS/实体/字段索引）。
    返回 (doc_id, [unit_id, ...])。
    """

    db = _session(app)
    try:
        now = datetime.now(timezone.utc)
        document = Document(
            id=uuid.uuid4(),
            name=name,
            name_key=name,
            file_type=file_type,
            latest_version_number=1,
            deleted=False,
            created_at=now,
        )
        db.add(document)
        db.flush()
        version = DocumentVersion(
            id=uuid.uuid4(),
            document_id=document.id,
            number=1,
            state="published",
            sha256=hashlib.sha256(name.encode("utf-8")).hexdigest(),
            size_bytes=1,
            stored_path=f"synthetic/{name}",
            uploaded_at=now,
            published_at=now,
        )
        db.add(version)
        db.flush()
        document.active_version_id = version.id
        unit_ids: list[str] = []
        for ordinal, unit in enumerate(units):
            unit_id = uuid.uuid4()
            db.add(
                SourceUnit(
                    id=unit_id,
                    document_id=document.id,
                    version_id=version.id,
                    kind=unit["kind"],
                    ordinal=ordinal,
                    unit_key=unit["unit_key"],
                    sheet=unit.get("sheet"),
                    locator=dict(unit["locator"]),
                    text=unit["text"],
                    fields=dict(unit.get("fields") or {}),
                    warnings=None,
                )
            )
            unit_ids.append(str(unit_id))
        state = db.get(KnowledgeState, 1)
        if state is None:
            db.add(
                KnowledgeState(
                    id=1,
                    revision=1,
                    active_document_count=1,
                    active_excel_row_count=0,
                    updated_at=now,
                )
            )
        else:
            state.revision = int(state.revision) + 1
            state.updated_at = now
        db.commit()
        assert prepare_version_index(db, version.id).ready
        return str(document.id), unit_ids
    finally:
        db.close()


def _seed(app) -> dict[str, str]:
    """docA 记录行 + docB 正文通知；返回单元/资料 ID。"""

    record_doc, (row_unit,) = _add_published_document(
        app,
        name="合成物品位置表.xlsx",
        file_type="xlsx",
        units=[
            {
                "kind": "table_row",
                "unit_key": "sheet:合成表:row:7",
                "sheet": "合成表",
                "locator": {"sheet": "合成表", "row": 7, "header_row": 1},
                "text": "门店: 甲店；物品: 立牌；位置: 甲区",
                "fields": {"门店": "甲店", "物品": "立牌", "位置": "甲区"},
            }
        ],
    )
    text_doc, (text_unit,) = _add_published_document(
        app,
        name="合成物料位置通知.pdf",
        file_type="pdf",
        units=[
            {
                "kind": "paragraph",
                "unit_key": "paragraph:1",
                "locator": {"paragraph": 1},
                "text": NOTICE_TEXT,
                "fields": {},
            }
        ],
    )
    return {
        "record_doc": record_doc,
        "row_unit": row_unit,
        "text_doc": text_doc,
        "text_unit": text_unit,
    }


def _ask(ns, question: str) -> dict:
    created = ns.client.post("/api/v1/conversations", json={}, headers=ns.headers)
    assert created.status_code == 201, created.text
    conversation = created.json()["id"]
    response = ns.client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=ns.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _disable_query_embedding(qa) -> None:
    """确定性复现 live 的"正文面拿不到向量召回"。

    合成索引只有 2 条资料，向量 top-50 必然包含正文单元，正文面因此会被"偶然"救回来；
    C12 的真实运行条件是正文单元**不在**向量窗口内（live 每轮只允许一次 query embedding），
    这时正文面只剩 lexical 通路。``disable_query_embedding`` 是 RagConfig 里已有的、
    运行时拦得住的能力开关（rag/retrieval.py 读它），用它把"向量窗口不覆盖正文"变成
    确定性条件；修复前后的差别只落在 lexical 通路上。
    """

    config = dataclasses.replace(qa.config, disable_query_embedding=True)
    qa.config = config
    index = qa.index()
    index.config = config


class _CandidateSpy:
    """记录产品实际交给 rag 的召回参数与返回值（不改变返回值）。"""

    def __init__(self, qa) -> None:
        self._qa = qa
        self._original = qa.candidate_unit_ids_for_intent
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        result = self._original(**kwargs)
        self.calls.append({**kwargs, "result": set(result)})
        return result

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr(self._qa, "candidate_unit_ids_for_intent", self)


# --------------------------------------------------------------------------- #
# 主断言：record 型问题的候选上界必须确定性包含正文通知单元
# --------------------------------------------------------------------------- #


def test_c12_record_intent_upper_bound_includes_notice_text(chat_app, chat_employee, monkeypatch):
    ids = _seed(chat_app)
    qa = chat_app.state.qa
    _disable_query_embedding(qa)
    spy = _CandidateSpy(qa)
    spy.install(monkeypatch)

    payload = _ask(chat_employee, QUESTION)

    # 记录问题的作答面不变：答案是记录行的位置值。
    assert payload["kind"] == "answer", payload
    assert "甲区" in payload["text"], payload["text"]

    assert spy.calls, "record 型问题必须走 legacy 的 rag 候选上界"
    call = spy.calls[-1]
    # 修复后候选上界同时含记录行与正文单元；修复前只有记录行（正文面没有检索词）。
    assert ids["row_unit"] in call["result"], call["result"]
    assert ids["text_unit"] in call["result"], call["result"]
    # 修复点：正文面计划的检索词来自题面（不是常量、不是题号）。
    assert call.get("document_terms") == intent_module.document_terms(QUESTION), call


# --------------------------------------------------------------------------- #
# 反例①：候选变大不改变单来源问题的答案文本与引用
# --------------------------------------------------------------------------- #


def test_c12_single_source_answer_unchanged_when_candidates_grow(chat_app, chat_employee, monkeypatch):
    ids = _seed(chat_app)
    qa = chat_app.state.qa
    narrow = {ids["row_unit"]}
    wide = {ids["row_unit"], ids["text_unit"]}

    monkeypatch.setattr(qa, "candidate_unit_ids_for_intent", lambda **_kw: narrow)
    before = _ask(chat_employee, QUESTION)
    monkeypatch.setattr(qa, "candidate_unit_ids_for_intent", lambda **_kw: wide)
    after = _ask(chat_employee, QUESTION)

    # legacy 只选记录行：答案文本与引用逐字不变（不含正文里的“乙区”）。
    assert before["kind"] == after["kind"] == "answer", (before, after)
    assert after["text"] == before["text"], (before["text"], after["text"])
    assert "乙区" not in after["text"], after["text"]
    assert [source["document_name"] for source in after["sources"]] == [
        source["document_name"] for source in before["sources"]
    ]
    assert {source["document_name"] for source in after["sources"]} == {"合成物品位置表.xlsx"}
