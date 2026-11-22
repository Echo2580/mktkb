"""T301 隔离样本生成：经 FastAPI 正常接口链路产生验收记录；罕见状态受控构造并标注来源。

产出：
- 隔离库 evidence/data/{mktkb.sqlite3, rag-index.sqlite3, qa-traces.sqlite3, storage/}
- 样本矩阵 evidence/matrix/sample-matrix.json

所有外部模型/OCR 均为替身；不调用真实付费服务；不读写 var/。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import t301_common as common
from t301_common import (
    DATA_DIR,
    EVIDENCE_DIR,
    FIXTURES_ROOT,
    MATRIX_DIR,
    TRACE_DB,
    MockGateway,
    Session,
    build_settings,
    conflict_xlsx_bytes,
    cached_formula_xlsx_bytes,
    publish,
    reset_isolated_data_dir,
    run_worker,
    uncached_formula_xlsx_bytes,
    upload_published,
)

SHANGHAI = timezone(timedelta(hours=8))

D01 = FIXTURES_ROOT / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES_ROOT / "normal" / "D02_合作店家信息.xlsx"
D03 = FIXTURES_ROOT / "normal" / "D03_市场部工作指南.docx"
V03 = FIXTURES_ROOT / "variants" / "V03_物品位置表_历史V1.xlsx"
V04 = FIXTURES_ROOT / "variants" / "V04_物品位置表_新版V3.xlsx"

LEGACY_DOC_QUESTION = "领取活动物料需要哪些步骤？"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_request_row(db, request_id: str) -> dict[str, Any]:
    from sqlalchemy import select  # noqa: F401

    from mktkb.conversations.models import ConversationRequest

    row = db.get(ConversationRequest, uuid.UUID(request_id))
    if row is None:
        return {}
    return {
        "request_id": str(row.id),
        "client_request_id": str(row.client_request_id),
        "status": row.status,
        "attempt": row.attempt,
        "user_message_id": str(row.user_message_id) if row.user_message_id else None,
        "result_message_id": str(row.result_message_id) if row.result_message_id else None,
        "error_code": row.error_code,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


def _sources_for_message(db, message_id: str | None) -> list[dict[str, Any]]:
    if not message_id:
        return []
    from sqlalchemy import select

    from mktkb.conversations.models import MessageSource

    rows = db.scalars(select(MessageSource).where(MessageSource.message_id == uuid.UUID(message_id))).all()
    return [
        {
            "source_id": str(row.source_id),
            "document_id": str(row.document_id),
            "version_id": str(row.version_id),
        }
        for row in rows
    ]


def main() -> dict[str, Any]:
    reset_isolated_data_dir()
    MATRIX_DIR.mkdir(parents=True, exist_ok=True)

    registry: list[dict[str, Any]] = []
    corpus: dict[str, Any] = {}

    # ---- App A：Trace 启用（正常执行 Trace 落独立 Trace 库） ----
    settings = build_settings(trace_enabled=True)
    gateway = MockGateway()
    app = common.create_app(settings, model_gateway=gateway)
    admin = Session(app, "admin", "AdminPass-1")
    employee = Session(app, "employee", "EmployeePass-1")

    # 1) 基线语料：位置表先以历史 V03 作为 v1 发布（换版样本前置），D02 店家、D03 指南。
    p_v1 = upload_published(app, admin, path=V03, name="T301-物品位置表.xlsx")
    corpus["positions"] = {
        "document_id": p_v1["record"]["document"]["id"],
        "v1_version_id": p_v1["record"]["version"]["id"],
        "v1_job_id": p_v1["record"]["job"]["id"],
        "job_state": p_v1["job_state"],
    }
    p02 = upload_published(app, admin, path=D02, name="D02_合作店家信息.xlsx")
    corpus["stores"] = {
        "document_id": p02["record"]["document"]["id"],
        "version_id": p02["record"]["version"]["id"],
        "job_id": p02["record"]["job"]["id"],
        "job_state": p02["job_state"],
    }
    p03 = upload_published(app, admin, path=D03, name="D03_市场部工作指南.docx")
    corpus["guide"] = {
        "document_id": p03["record"]["document"]["id"],
        "version_id": p03["record"]["version"]["id"],
        "job_id": p03["record"]["job"]["id"],
        "job_state": p03["job_state"],
    }

    # 冲突双侧资料：同标识 QF001、不同位置；门店/物品刻意避开位置表既有实体，避免串扰歧义。
    c1 = upload_published(
        app, admin,
        content=conflict_xlsx_bytes([["QF001", "城北店", "指示牌", None, "B区1号货架第二层"]]),
        name="T301-冲突资料A.xlsx",
    )
    c2 = upload_published(
        app, admin,
        content=conflict_xlsx_bytes([["QF001", "城北店", "指示牌", None, "D区暂存柜"]]),
        name="T301-冲突资料B.xlsx",
    )
    corpus["conflict_a"] = {"document_id": c1["record"]["document"]["id"], "version_id": c1["record"]["version"]["id"]}
    corpus["conflict_b"] = {"document_id": c2["record"]["document"]["id"], "version_id": c2["record"]["version"]["id"]}

    def ask_and_record(sample_id: str, scenario: str, question: str, *,
                       source: str, conversation_id: str | None = None,
                       client_request_id: uuid.UUID | None = None,
                       trace_enabled: bool = True, expected_kind: str | None = None,
                       extra: dict[str, Any] | None = None) -> dict[str, Any]:
        conv_id = conversation_id or employee.create_conversation()
        response = employee.ask(conv_id, question, client_request_id=client_request_id)
        body = response.json() if response.status_code == 200 else {"kind": None, "error": response.text}
        db = app.state.db.session()
        try:
            from mktkb.conversations.models import ConversationRequest

            row = None
            if body.get("request_id"):
                row = db.get(ConversationRequest, uuid.UUID(str(body["request_id"])))
            if row is None:
                from sqlalchemy import select

                cid = uuid.UUID(conv_id)
                row = db.scalar(
                    select(ConversationRequest).where(ConversationRequest.conversation_id == cid)
                )
            req = _load_request_row(db, str(row.id)) if row else {}
            sources = _sources_for_message(db, req.get("result_message_id") or body.get("message_id"))
        finally:
            db.close()

        record = {
            "sample_id": sample_id,
            "scenario": scenario,
            "source": source,
            "trace_enabled": trace_enabled,
            "conversation_id": conv_id,
            "question": question,
            "http_request_id": response.headers.get("X-Request-ID"),
            "trace_id": response.headers.get("X-Trace-ID"),
            "request": req,
            "response_kind": body.get("kind"),
            "response_error_code": body.get("error_code"),
            "citations": sources,
            "conflicts": body.get("conflicts") or [],
            "expected_kind": expected_kind,
            "finished_at": req.get("finished_at"),
            "extra": extra or {},
        }
        registry.append(record)
        return record

    # S11 换版前：引用历史 v1（V03）
    ask_and_record(
        "S11", "换版前：引用历史 v1", "城东店的宣传海报在哪里？",
        source="normal_entry", expected_kind="answer",
        extra={"document_id": corpus["positions"]["document_id"], "version_number": 1},
    )

    # 位置表换版：D01 作为同一文档 v2 发布；旧 v1 转 superseded。
    v2 = upload_published(
        app, admin, path=D01, name="T301-物品位置表.xlsx",
        document_id=corpus["positions"]["document_id"],
        expected_active_version_id=corpus["positions"]["v1_version_id"],
    )
    corpus["positions"]["v2_version_id"] = v2["record"]["version"]["id"]

    # S12 换版后：引用生效 v2；旧版引用标识仍可在历史消息中展示
    ask_and_record(
        "S12", "换版后：引用生效 v2；旧版引用标识仍可展示", "城东店的宣传海报在哪里？",
        source="normal_entry", expected_kind="answer",
        extra={"document_id": corpus["positions"]["document_id"], "version_number": 2},
    )

    # S01 RAG 枚举作答：同一回答引用同一文档多行（P01/P02 同属位置表文档）
    ask_and_record(
        "S01", "RAG 正常作答 + 同文档多条引用行", "把城东店和城西店的宣传海报记录都列出来",
        source="normal_entry", expected_kind="answer",
    )
    # S02 单引用作答（作为 S06 重放的基线请求）
    replay_conv = employee.create_conversation()
    replay_request_id = uuid.uuid4()
    ask_and_record(
        "S02", "正常带引用（单引用）", "城东店的宣传海报在哪里？",
        source="normal_entry", conversation_id=replay_conv,
        client_request_id=replay_request_id, expected_kind="answer",
    )
    # S03 not_found
    ask_and_record("S03", "未找到 not_found", "城南店联系人是谁？", source="normal_entry", expected_kind="not_found")
    # S04 clarification
    ask_and_record("S04", "澄清 clarification", "宣传海报在哪里？", source="normal_entry", expected_kind="clarification")
    # S05 conflict（两方来源在结果 JSON 的 conflicts）
    ask_and_record("S05", "冲突 conflict（两方来源取自 conflicts）", "QF001在哪里？", source="normal_entry", expected_kind="conflict")
    # S06 幂等重放：同 client_request_id 二次提交，不增量、可辨认
    ask_and_record(
        "S06", "幂等重放（同请求 ID 二次提交不增量）", "城东店的宣传海报在哪里？",
        source="normal_entry", conversation_id=replay_conv,
        client_request_id=replay_request_id, expected_kind="answer",
        extra={"replay_of_sample": "S02"},
    )
    # S07 legacy 正文型作答（D03 docx）
    ask_and_record("S07", "legacy 路径正文作答", LEGACY_DOC_QUESTION, source="normal_entry", expected_kind="answer")

    # S08 service_error：注入模型不可用（替身错误，非真实调用）
    gateway.error = common.ModelUnavailable("T301 注入：模型暂不可用")
    ask_and_record("S08", "服务错误 service_error", LEGACY_DOC_QUESTION, source="normal_entry", expected_kind="service_error")
    gateway.error = None

    # S09 knowledge_changed：检索阶段注入 revision 变更异常（正常 HTTP 入口 + 故障替身缝）
    from mktkb.conversations import service as conversations_service
    from mktkb.retrieval.types import KnowledgeRevisionChanged

    original_retrieve = conversations_service._retrieve

    def _boom(*args: Any, **kwargs: Any):
        raise KnowledgeRevisionChanged("T301 注入：检索阶段 revision 变化")

    conversations_service._retrieve = _boom
    ask_and_record(
        "S09", "知识库已变更 knowledge_changed", "城东店的展架在哪里？",
        source="normal_entry_injected_seam", expected_kind="knowledge_changed",
    )
    conversations_service._retrieve = original_retrieve

    # S10 已删除会话：先作答，再逻辑删除；统计与明细两侧均应排除
    deleted_conv = employee.create_conversation()
    deleted = ask_and_record(
        "S10", "已逻辑删除会话（两侧排除）", "城西店的易拉宝在哪里？",
        source="normal_entry", conversation_id=deleted_conv, expected_kind="answer",
    )
    deleted_response = employee.delete_conversation(deleted_conv)
    deleted["extra"]["delete_status_code"] = deleted_response.status_code

    # S13 失败导入（无缓存公式 → 整单失败）
    fail = admin.upload(content=uncached_formula_xlsx_bytes(), name="T301-失败导入.xlsx")
    assert fail.status_code == 202, fail.text
    fail_record = fail.json()
    fail_job = run_worker(app)
    registry.append({
        "sample_id": "S13",
        "scenario": "失败导入任务",
        "source": "normal_entry",
        "trace_enabled": True,
        "document_id": fail_record["document"]["id"],
        "version_id": fail_record["version"]["id"],
        "job_id": fail_record["job"]["id"],
        "job_state": fail_job.state,
        "job_error_code": fail_job.error_code,
        "finished_at": None,
        "extra": {"expected_version_state": "failed"},
    })

    # S14 待审核版本（缓存公式行 → 任务成功、版本 review_required）
    review = admin.upload(content=cached_formula_xlsx_bytes(), name="T301-待审核版本.xlsx")
    assert review.status_code == 202, review.text
    review_record = review.json()
    review_job = run_worker(app)
    registry.append({
        "sample_id": "S14",
        "scenario": "待审核版本 review_required",
        "source": "normal_entry",
        "trace_enabled": True,
        "document_id": review_record["document"]["id"],
        "version_id": review_record["version"]["id"],
        "job_id": review_record["job"]["id"],
        "job_state": review_job.state,
        "finished_at": None,
        "extra": {"expected_version_state": "review_required"},
    })

    # ---- App B：Trace 关闭（独立库不产生 Trace 记录） ----
    settings_off = build_settings(trace_enabled=False)
    gateway_off = MockGateway()
    app_off = common.create_app(settings_off, model_gateway=gateway_off)
    employee_off = Session(app_off, "employee", "EmployeePass-1")

    off_conv = employee_off.create_conversation()
    off_response = employee_off.ask(off_conv, LEGACY_DOC_QUESTION)
    off_body = off_response.json()
    db_off = app_off.state.db.session()
    try:
        from sqlalchemy import select

        from mktkb.conversations.models import ConversationRequest

        off_row = db_off.scalar(
            select(ConversationRequest).where(ConversationRequest.conversation_id == uuid.UUID(off_conv))
        )
        off_req = _load_request_row(db_off, str(off_row.id)) if off_row else {}
        off_sources = _sources_for_message(db_off, off_req.get("result_message_id"))
    finally:
        db_off.close()
    registry.append({
        "sample_id": "S15",
        "scenario": "Trace 关闭状态：不产生执行 Trace",
        "source": "normal_entry",
        "trace_enabled": False,
        "conversation_id": off_conv,
        "question": LEGACY_DOC_QUESTION,
        "http_request_id": off_response.headers.get("X-Request-ID"),
        "trace_id": off_response.headers.get("X-Trace-ID"),
        "request": off_req,
        "response_kind": off_body.get("kind"),
        "citations": off_sources,
        "conflicts": [],
        "finished_at": off_req.get("finished_at"),
        "extra": {"trace_header_present": off_response.headers.get("X-Trace-ID") is not None},
    })

    # ---- 受控样本：直接写隔离库（明确标注，非正常入口产物） ----
    db = app.state.db.session()
    try:
        from mktkb.auth.models import User
        from mktkb.conversations.models import (
            Conversation,
            ConversationMessage,
            ConversationRequest,
        )

        employee_user = db.scalar(select(User).where(User.username == "employee"))
        now = _now()

        def _make_interrupted(sample_id: str, status: str, note: str) -> None:
            conv = Conversation(user_id=employee_user.id, title=f"T301 受控-{sample_id}", created_at=now, updated_at=now)
            db.add(conv)
            db.flush()
            user_msg = ConversationMessage(
                conversation_id=conv.id, user_id=employee_user.id, seq=1, role="user",
                text=f"T301 受控未提交中断（{status}）", created_at=now,
            )
            db.add(user_msg)
            db.flush()
            req = ConversationRequest(
                conversation_id=conv.id, user_id=employee_user.id,
                client_request_id=uuid.uuid4(), payload_sha256="controlled",
                question=user_msg.text, status=status, attempt=1,
                user_message_id=user_msg.id, result_message_id=None,
                result_json=None, error_code=None, error_retryable=False,
                created_at=now, started_at=now, deadline_at=now + timedelta(seconds=30),
                finished_at=None if status == "running" else now,
            )
            db.add(req)
            db.flush()
            registry.append({
                "sample_id": sample_id,
                "scenario": note,
                "source": "controlled",
                "trace_enabled": True,
                "conversation_id": str(conv.id),
                "request": {
                    "request_id": str(req.id),
                    "client_request_id": str(req.client_request_id),
                    "status": req.status,
                    "attempt": req.attempt,
                    "user_message_id": str(user_msg.id),
                    "result_message_id": None,
                    "finished_at": req.finished_at.isoformat() if req.finished_at else None,
                },
                "response_kind": None,
                "citations": [],
                "conflicts": [],
                "finished_at": req.finished_at.isoformat() if req.finished_at else None,
                "extra": {"controlled_construction": "直接写隔离库；非正常入口产物"},
            })

        _make_interrupted("S16", "running", "未提交中断：running 请求无结果消息（不入六类）")
        _make_interrupted("S19", "expired", "未提交中断：过期请求（不入六类）")

        def _make_midnight(sample_id: str, finished_shanghai: datetime, day_label: str) -> None:
            finished_utc = finished_shanghai.astimezone(timezone.utc)
            conv = Conversation(user_id=employee_user.id, title=f"T301 受控-{sample_id}", created_at=now, updated_at=now)
            db.add(conv)
            db.flush()
            user_msg = ConversationMessage(
                conversation_id=conv.id, user_id=employee_user.id, seq=1, role="user",
                text=f"T301 受控午夜边界（{day_label}）", created_at=now,
            )
            db.add(user_msg)
            db.flush()
            assistant = ConversationMessage(
                conversation_id=conv.id, user_id=employee_user.id, seq=2, role="assistant",
                text="受控午夜边界答案", kind="answer", revision=0, created_at=finished_utc,
            )
            db.add(assistant)
            db.flush()
            req = ConversationRequest(
                conversation_id=conv.id, user_id=employee_user.id,
                client_request_id=uuid.uuid4(), payload_sha256="controlled",
                question=user_msg.text, status="succeeded", attempt=1,
                user_message_id=user_msg.id, result_message_id=assistant.id,
                result_json={"kind": "answer", "text": assistant.text, "sources": [], "conflicts": []},
                error_code=None, error_retryable=False,
                created_at=now, started_at=now, deadline_at=now + timedelta(seconds=30),
                finished_at=finished_utc,
            )
            db.add(req)
            db.flush()
            registry.append({
                "sample_id": sample_id,
                "scenario": f"午夜边界：{day_label}",
                "source": "controlled",
                "trace_enabled": True,
                "conversation_id": str(conv.id),
                "request": {
                    "request_id": str(req.id),
                    "client_request_id": str(req.client_request_id),
                    "status": req.status,
                    "attempt": req.attempt,
                    "user_message_id": str(user_msg.id),
                    "result_message_id": str(assistant.id),
                    "finished_at": req.finished_at.astimezone(timezone.utc).isoformat(),
                },
                "response_kind": "answer",
                "citations": [],
                "conflicts": [],
                "finished_at": req.finished_at.astimezone(timezone.utc).isoformat(),
                "extra": {
                    "expected_shanghai_day": day_label,
                    "finished_at_shanghai": finished_shanghai.isoformat(),
                    "controlled_construction": "直接写隔离库；完成时间按边界固定，非真实墙钟",
                },
            })

        before = datetime(2026, 11, 20, 23, 59, 59, 750_000, tzinfo=SHANGHAI)
        after = datetime(2026, 11, 21, 0, 0, 0, 250_000, tzinfo=SHANGHAI)
        _make_midnight("S17", before, "2026-11-20")
        _make_midnight("S18", after, "2026-11-21")
        db.commit()
    finally:
        db.close()

    # 关闭句柄
    app.state.qa.close()
    app.state.db.dispose()
    app_off.state.qa.close()
    app_off.state.db.dispose()

    matrix = {
        "generated_at": _now().isoformat(),
        "trace_db": str(TRACE_DB.relative_to(EVIDENCE_DIR.parent)),
        "business_db": str(common.BUSINESS_DB.relative_to(EVIDENCE_DIR.parent)),
        "corpus": corpus,
        "samples": registry,
    }
    MATRIX_DIR.mkdir(parents=True, exist_ok=True)
    (MATRIX_DIR / "sample-matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return matrix


if __name__ == "__main__":
    result = main()
    print(f"samples={len(result['samples'])}")
