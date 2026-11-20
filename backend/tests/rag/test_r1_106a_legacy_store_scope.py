"""T-R1-106a：legacy 路径的唯一门店范围（C13 同形：异店记录行不得进入证据面）。

合成数据（全部为假数据，不读 fixtures）：甲店/乙店各一行「立牌」记录（位置不同），
另有一份调拨政策正文（没有门店列，属共享背景）。

三回合：点名甲店的立牌位置 → 换话题问调拨政策 → 只问物品（“同一件吗/现在登记的货架”）。

红线：
- 第 1/3 回合的 ``sources`` 与 model evidence 里不得出现乙店行，答案只出甲区；
- 第 2 回合政策答案不受影响（政策正文是共享背景，不因单店作用域被裁掉）。

反例：显式点名两家店时仍按两家作答（不因保留的单店作用域被收窄）；
同门店「物品 + 店家级字段」跨表 join 仍工作。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from mktkb.documents.lifecycle import prepare_version_index
from mktkb.documents.models import (
    Document,
    DocumentVersion,
    KnowledgeState,
    SourceUnit,
)

ROW_JIA = {"门店": "甲店", "物品": "立牌", "位置": "甲区A层1号货架"}
ROW_YI = {"门店": "乙店", "物品": "立牌", "位置": "乙区B层2号货架"}
POLICY = "调拨必须由区域经理同意。"
ROW_COOPERATION = {"门店": "甲店", "合作状态": "已签约"}

TURN_SCOPE = "甲店立牌放在哪里？"
TURN_TOPIC = "调拨需要谁同意？"
TURN_SAME_ITEM = "“展示牌”和“立牌”是同一件吗？现在登记的货架是哪一层？"


def _add_document(app, *, name: str, file_type: str, units: list[dict]) -> list[str]:
    """直写一条已发布资料（跳过上传/worker：本用例只关心证据面与作用域）。"""

    db = app.state.db.session()
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
        return unit_ids
    finally:
        db.close()


def _row_unit(fields: dict, *, row: int) -> dict:
    return {
        "kind": "table_row",
        "unit_key": f"sheet:合成表:row:{row}",
        "sheet": "合成表",
        "locator": {"sheet": "合成表", "row": row, "header_row": 1},
        "text": "；".join(f"{key}: {value}" for key, value in fields.items()),
        "fields": dict(fields),
    }


def _seed(app, *, extra_rows: tuple[dict, ...] = ()) -> dict[str, str]:
    rows = [ROW_JIA, ROW_YI, *extra_rows]
    row_ids = _add_document(
        app,
        name="合成物品位置表.xlsx",
        file_type="xlsx",
        units=[_row_unit(fields, row=7 + index) for index, fields in enumerate(rows)],
    )
    policy_ids = _add_document(
        app,
        name="合成调拨制度.pdf",
        file_type="pdf",
        units=[
            {
                "kind": "paragraph",
                "unit_key": "paragraph:1",
                "locator": {"paragraph": 1},
                "text": POLICY,
                "fields": {},
            }
        ],
    )
    return {
        "jia": row_ids[0],
        "yi": row_ids[1],
        "policy": policy_ids[0],
        "extra": row_ids[2] if len(row_ids) > 2 else "",
    }


def _ask(ns: SimpleNamespace, conversation: str | None, question: str) -> tuple[dict, str]:
    if conversation is None:
        created = ns.client.post("/api/v1/conversations", json={}, headers=ns.headers)
        assert created.status_code == 201, created.text
        conversation = created.json()["id"]
    response = ns.client.post(
        f"/api/v1/conversations/{conversation}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=ns.headers,
    )
    assert response.status_code == 200, response.text
    return response.json(), conversation


def _answer_calls(chat_model, start: int) -> list[list[dict]]:
    return [
        call["evidence"]
        for call in chat_model.calls[start:]
        if call["purpose"] == "answer"
    ]


def _evidence_texts(calls: list[list[dict]]) -> str:
    return "\n".join(
        str(item.get("text") or "") for evidence in calls for item in evidence
    )


def _source_rows(body: dict) -> list[int]:
    return [
        int(source["locator"]["row"])
        for source in body.get("sources", [])
        if isinstance(source.get("locator"), dict) and "row" in source["locator"]
    ]


# --------------------------------------------------------------- 主红线（三回合）


def test_legacy_followup_keeps_unique_store_scope(chat_app, chat_employee, chat_model):
    """第 3 回合只问物品时，唯一门店范围必须仍生效：乙店行不得进证据/引用。"""

    ids = _seed(chat_app)

    mark = len(chat_model.calls)
    first, conversation = _ask(chat_employee, None, TURN_SCOPE)
    assert first["kind"] == "answer", first
    assert "甲区" in first["text"] and "乙区" not in first["text"], first["text"]
    assert _source_rows(first) == [7], first.get("sources")
    first_evidence = _evidence_texts(_answer_calls(chat_model, mark))
    assert "乙店" not in first_evidence, first_evidence

    mark = len(chat_model.calls)
    topic, conversation = _ask(chat_employee, conversation, TURN_TOPIC)
    assert topic["kind"] == "answer", topic
    assert "区域经理" in topic["text"], topic["text"]
    assert _source_rows(topic) == [], topic.get("sources")
    assert ids["policy"] in [str(source["source_id"]) for source in topic["sources"]]

    mark = len(chat_model.calls)
    third, _ = _ask(chat_employee, conversation, TURN_SAME_ITEM)
    assert third["kind"] == "answer", third
    assert "甲区" in third["text"], third["text"]
    assert "乙区" not in third["text"], third["text"]
    assert 8 not in _source_rows(third), third.get("sources")
    third_calls = _answer_calls(chat_model, mark)
    assert third_calls, "第 3 回合必须真实调用模型（legacy 路径）"
    assert "乙店" not in _evidence_texts(third_calls), _evidence_texts(third_calls)


# -------------------------------------------------------------------- 合法反例


def test_explicit_two_store_question_still_lists_both(chat_app, chat_employee):
    """显式点名两家店时仍按两家作答：保留的单店作用域不得收窄多店枚举。"""

    _seed(chat_app)
    _, conversation = _ask(chat_employee, None, TURN_SCOPE)
    _ask(chat_employee, conversation, TURN_TOPIC)

    both, _ = _ask(chat_employee, conversation, "甲店和乙店的立牌位置分别是什么？")
    assert both["kind"] == "answer", both
    assert "甲区" in both["text"] and "乙区" in both["text"], both["text"]


def test_same_store_cross_table_join_still_works(chat_app, chat_employee):
    """同一门店的「物品 + 店家级字段」跨表 join 不受门店作用域影响。"""

    _seed(chat_app, extra_rows=(ROW_COOPERATION,))
    body, _ = _ask(chat_employee, None, "甲店的合作状态和立牌位置在哪？")
    assert body["kind"] == "answer", body
    assert "已签约" in body["text"], body["text"]
    assert "甲区" in body["text"], body["text"]
    assert "乙区" not in body["text"], body["text"]


# ------------------------------------------------------------------ 作用域取值面


def test_scope_helper_never_narrows_multi_store_turns():
    """作用域只取结构化单店条件：没有计划/多店状态时必须返回 ``None``（不收窄）。"""

    from mktkb.conversations.service import _legacy_store_scope
    from mktkb.rag.types import QueryPlan, QueryState

    def plan(filters: dict, state: QueryState) -> QueryPlan:
        return QueryPlan(
            question="q",
            mode="document",
            query_text="q",
            field_role=None,
            field_label=None,
            filters=filters,
            terms=("立牌",),
            state=state,
        )

    assert _legacy_store_scope(None) is None
    assert _legacy_store_scope(plan({"store": "甲店"}, QueryState())) == "甲店"
    assert _legacy_store_scope(plan({}, QueryState(store="甲店"))) == "甲店"
    assert _legacy_store_scope(plan({}, QueryState(stores=("甲店",)))) == "甲店"
    # 显式多店枚举：计划里没有 store 过滤，状态里是两个门店。
    assert _legacy_store_scope(plan({}, QueryState(stores=("甲店", "乙店")))) is None
    assert _legacy_store_scope(plan({}, QueryState())) is None
