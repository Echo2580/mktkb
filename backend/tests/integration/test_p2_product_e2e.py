"""P2-T203：产品端到端（隔离应用 + Mock provider）的集成检查。

这里断言的是**产品行为**，不是评测器行为：所有动作都经由隔离应用的 HTTP 路由
（上传 -> worker 解析 -> 发布 -> 提问 -> 消息列表 -> 来源详情）完成，评测代码只做驱动与观测。

覆盖任务书 T203 的产品面要求：
- 隔离：独立业务库/索引库/存储/trace/账号，全部落在 pytest 临时目录，不碰原 ``var/``；
- 灌库走产品上传/解析/发布路径，发布后资料当前有效版本可被问答引用；
- RAG 分支与 legacy 分支都经过用户同一入口（``POST /conversations/{id}/messages``），
  引用从 source_id 转换到产品来源摘要/详情，消息与会话持久化；
- 来源详情权限（本人 200、他人 403）与有效版本复核（旧版本 410 superseded）；
- 同 ``client_request_id`` 重复提交不新增消息、不重复调用模型（不重复付费）；
- 多轮同一会话逐轮 trace；知识库在轮中变化时产品返回 ``knowledge_changed``；
- 默认不构造真实 provider：没有注入 chat 后端时 ``app.state.model_gateway is None``，
  问答明确返回 ``MODEL_NOT_CONFIGURED``；
- 真实出站 0：外层网络闸门 + 供应商 POST 计数 + provider 调用计数三方互证。
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有验收级网络闸门（不复制实现）
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.evaluation.product_adapter import (
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)
from mktkb.rag.providers import post_counters, reset_post_counters

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "acceptance"
D01 = FIXTURES / "normal" / "D01_物品位置表.xlsx"
D02 = FIXTURES / "normal" / "D02_合作店家信息.xlsx"
D04 = FIXTURES / "normal" / "D04_活动策划流程.docx"
V03 = FIXTURES / "variants" / "V03_物品位置表_历史V1.xlsx"
V04 = FIXTURES / "variants" / "V04_物品位置表_新版V3.xlsx"

RAG_QUESTION = "把城东店和城西店的宣传海报记录都列出来"
LEGACY_QUESTION = "活动策划需要哪些步骤？"
FOLLOWUP_QUESTION = "那城西店呢？"


def asyncio_test(func):
    """仓库没有 pytest-asyncio：同一事件循环跑一个 async 用例（保留 fixture 签名）。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


def ingest_plan(*extra: IngestSource) -> P2IngestPlan:
    return P2IngestPlan(
        sources=(IngestSource(path=D01), IngestSource(path=D02), IngestSource(path=D04)) + tuple(extra),
        label="t203-e2e",
    )


def empty_dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "p2-e2e-v1",
            "label_version": "synthetic-v1",
            "suite": "p2-holdout",
            "manifest_sha256": "d" * 64,
            "case_count": 0,
        },
    )


def revised_positions_xlsx(directory: Path, *, note: str) -> Path:
    """把 D01 复制成"另一个字节"的版本（产品会拒绝与当前有效版本字节相同的新版本）。

    只改文件头的业务更新日期，记录行原值不动——这样版本切换是真的产品发布，而不是
    评测器手改知识库。
    """
    import openpyxl

    workbook = openpyxl.load_workbook(D01)
    worksheet = workbook.worksheets[0]
    worksheet.cell(row=3, column=1, value=f"业务更新：{note}")
    target = Path(directory) / f"D01_物品位置表_{note}.xlsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)
    return target


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------- #
# 1. 产品主链路：隔离应用 + 灌库 + 两分支问答 + 引用 + 权限 + 版本复核 + 幂等
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_product_path_end_to_end_with_mock_providers(tmp_path: Path) -> None:
    reset_post_counters()
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        tmp_path / "e2e",
        chat=chat,
        dataset=empty_dataset(),
        ingest_plan=ingest_plan(),
    )
    try:
        await adapter.start()
        # ---------------------------------------------------------- 隔离
        settings = adapter.app.state.settings
        assert adapter.paths.root == tmp_path / "e2e"
        for path in (
            adapter.paths.business_db,
            adapter.paths.index_db,
            adapter.paths.storage,
            adapter.paths.trace_db,
        ):
            assert str(path).startswith(str(tmp_path)), path
        assert settings.data_dir == adapter.paths.data_dir
        assert settings.resolved_rag_index_path == adapter.paths.index_db
        assert "mktkb.sqlite3" in str(settings.resolved_database_url())
        assert str(ROOT / "var") not in str(settings.data_dir)

        # ---------------------------------------------------------- 灌库（产品路径）
        receipts = await adapter.ingest()
        assert [receipt.upload_status for receipt in receipts] == [202, 202, 202]
        assert [receipt.job_state for receipt in receipts] == ["succeeded"] * 3
        assert [receipt.publish_status for receipt in receipts] == [200, 200, 200]
        assert all(receipt.published for receipt in receipts)
        assert all((receipt.units or 0) > 0 for receipt in receipts)
        assert adapter.product_revision() == 3
        status = adapter.index_status()
        assert status["ready"] is True and int(status["documents"]) == 3

        # ---------------------------------------------------------- 两个分支都走产品入口
        conversation_id = await adapter.open_conversation()
        rag_turn = await adapter.ask_turn(
            RAG_QUESTION,
            user_id="employee",
            conversation_id=conversation_id,
            client_request_id="11111111-1111-4111-8111-111111111111",
        )
        assert rag_turn.http_status == 200
        assert rag_turn.kind == "answer", rag_turn.as_dict(include_text=True)
        assert rag_turn.trace_path == "rag"
        assert rag_turn.trace_outcome == "answer"
        assert rag_turn.trace_id and rag_turn.message_id and rag_turn.request_id
        assert rag_turn.source_ids, "RAG 回答必须带产品引用"

        legacy_turn = await adapter.ask_turn(
            LEGACY_QUESTION,
            user_id="employee",
            conversation_id=conversation_id,
            client_request_id="22222222-2222-4222-8222-222222222222",
        )
        assert legacy_turn.http_status == 200
        assert legacy_turn.kind == "answer", legacy_turn.as_dict(include_text=True)
        assert legacy_turn.trace_path == "legacy"
        assert legacy_turn.source_ids
        assert chat.call_count >= 1, "legacy 分支必须真的调用过（Mock）chat 后端"
        assert set(chat.counts_by_purpose()) <= {"answer", "query_expansion"}

        # ---------------------------------------------------------- 持久化 + 引用转换
        code, listing = await adapter.list_messages(conversation_id)
        assert code == 200
        assert listing["total"] == 4
        assistant = [item for item in listing["items"] if item["role"] == "assistant"]
        assert len(assistant) == 2
        first = assistant[0]
        assert first["kind"] == "answer"
        assert first["sources"], "消息列表必须回放引用摘要"
        source = first["sources"][0]
        assert source["status"] == "active"
        assert int(source["version_number"]) >= 1
        assert source["document_name"]
        assert isinstance(source["locator"], dict) and source["locator"]
        assert source["published_at"]

        # 来源详情：本人 200 且带正文/字段/原件链接；他人 403。
        detail_code, detail = await adapter.source_detail(
            first["id"], source["source_id"]
        )
        assert detail_code == 200
        assert detail["status"] == "active"
        assert detail["text"]
        assert detail["file_url"].endswith("/file")
        other_code, _ = await adapter.source_detail(
            first["id"], source["source_id"], user_id="admin"
        )
        assert other_code == 403

        # ---------------------------------------------------------- 有效版本复核
        old_source_id = source["source_id"]
        revised = revised_positions_xlsx(tmp_path / "uploads", note="2026-11-10")
        new_receipt = await adapter.ingest(
            P2IngestPlan(
                sources=(
                    IngestSource(
                        path=revised,
                        document_id=receipts[0].document_id,
                        expected_active_version_id=receipts[0].version_id,
                    ),
                ),
                label="t203-e2e-v2",
            )
        )
        assert new_receipt[0].published is True
        superseded_code, superseded = await adapter.source_detail(
            first["id"], old_source_id
        )
        assert superseded_code == 410, superseded
        details = superseded["error"]["details"]
        assert details["status"] == "superseded"
        assert int(details["version_number"]) == 1
        assert "text" not in details, "失效来源不得回显正文"

        # 新版本生效后，同样的枚举问题仍然只引用当前有效版本。
        refreshed = await adapter.ask_turn(
            RAG_QUESTION,
            user_id="employee",
            conversation_id=conversation_id,
            client_request_id="33333333-3333-4333-8333-333333333333",
        )
        assert refreshed.kind == "answer"
        assert all(item["version_number"] >= 2 for item in refreshed.sources if item["document_name"].startswith("D01_"))

        # ---------------------------------------------------------- 幂等：同请求不重复提交
        before_chat = chat.call_count
        code_before, listing_before = await adapter.list_messages(conversation_id)
        replay = await adapter.ask_turn(
            RAG_QUESTION,
            user_id="employee",
            conversation_id=conversation_id,
            client_request_id="11111111-1111-4111-8111-111111111111",
        )
        code_after, listing_after = await adapter.list_messages(conversation_id)
        assert replay.message_id == rag_turn.message_id
        assert replay.request_id == rag_turn.request_id
        assert listing_after["total"] == listing_before["total"]
        assert adapter.messages_in_db(conversation_id) == listing_after["total"]
        assert chat.call_count == before_chat, "重复提交不得再调用模型（不重复付费）"
        assert replay.text == rag_turn.text

        # ---------------------------------------------------------- 多轮：同会话逐轮 trace
        multi = await adapter.open_conversation()
        turn1 = await adapter.ask_turn(
            RAG_QUESTION,
            user_id="employee",
            conversation_id=multi,
            client_request_id="44444444-4444-4444-8444-444444444444",
        )
        turn2 = await adapter.ask_turn(
            FOLLOWUP_QUESTION,
            user_id="employee",
            conversation_id=multi,
            client_request_id="55555555-5555-4555-8555-555555555555",
        )
        assert turn1.kind == "answer" and turn2.kind == "answer"
        assert turn1.trace_id != turn2.trace_id
        assert turn2.trace_path in {"rag", "legacy", "legacy_with_rag_candidates"}
        _, multi_listing = await adapter.list_messages(multi)
        assert multi_listing["total"] == 4

        # ---------------------------------------------------------- 0 真实调用三方互证
        calls = adapter.provider_calls()
        assert calls["chat"]["transport"] == "httpx.MockTransport"
        assert calls["chat"]["calls"] == chat.call_count >= 1
        assert calls["embedding"]["calls"] > 0
        assert calls["rerank"]["calls"] > 0
        # F1：出站数是**实测**的：MockTransport 接住了每一次调用，所以出站 0、拦截 >0。
        assert calls["outbound_network"] == 0
        assert calls["network"]["outbound_attempts"] == 0
        assert calls["network"]["mock_intercepted"] >= 1
        assert calls["network"]["chat_outbound_attempts"] == 0
        assert all(
            value == 0
            for kind in post_counters().values()
            for value in kind.values()
        ), "RAG 供应商真实 POST 计数必须为 0"
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 2. 默认不构建真实 provider
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_default_adapter_builds_no_real_provider(tmp_path: Path) -> None:
    reset_post_counters()
    adapter = ProductEvalAdapter(
        tmp_path / "noprovider", chat=None, dataset=empty_dataset(), ingest_plan=ingest_plan()
    )
    try:
        await adapter.ingest()
        # 没有注入 chat 后端、也没有模型配置：应用里根本没有网关可发。
        assert adapter.app.state.model_gateway is None
        assert adapter.real_provider_built is False
        assert adapter.chat is None
        conversation_id = await adapter.open_conversation()
        turn = await adapter.ask_turn(
            LEGACY_QUESTION,
            user_id="employee",
            conversation_id=conversation_id,
            client_request_id="66666666-6666-4666-8666-666666666666",
        )
        assert turn.kind == "service_error"
        assert turn.error_code == "MODEL_NOT_CONFIGURED"
        assert turn.source_ids == ()
        assert adapter.provider_calls()["chat"]["calls"] == 0
        assert all(
            value == 0 for kind in post_counters().values() for value in kind.values()
        )
        assert not list((tmp_path / "noprovider").rglob("*.pem"))
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 3. 知识库在轮中变化：产品自己给出 knowledge_changed
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_knowledge_changed_while_turn_in_flight(tmp_path: Path) -> None:
    adapter_holder: dict[str, ProductEvalAdapter] = {}
    published: list[bool] = []

    async def publish_once(_index: int, _body: Any) -> None:
        if published:
            return
        published.append(True)
        adapter = adapter_holder["adapter"]
        revised = revised_positions_xlsx(
            adapter.paths.root / "uploads", note="2026-11-10-midturn"
        )
        await adapter.ingest(
            P2IngestPlan(
                sources=(
                    IngestSource(
                        path=revised,
                        document_id=adapter.ingest_receipts[0].document_id,
                        expected_active_version_id=adapter.ingest_receipts[0].version_id,
                    ),
                ),
                label="t203-midturn",
            )
        )

    chat = MockChatBackend(before_call=publish_once)
    adapter = ProductEvalAdapter(
        tmp_path / "midturn", chat=chat, dataset=empty_dataset(), ingest_plan=ingest_plan()
    )
    adapter_holder["adapter"] = adapter
    try:
        await adapter.ingest()
        conversation_id = await adapter.open_conversation()
        turn = await adapter.ask_turn(
            LEGACY_QUESTION,
            user_id="employee",
            conversation_id=conversation_id,
            client_request_id="77777777-7777-4777-8777-777777777777",
        )
        assert published == [True]
        assert turn.http_status == 200
        assert turn.kind == "knowledge_changed", json.dumps(
            turn.as_dict(include_text=True), ensure_ascii=False
        )
        assert turn.trace_outcome == "knowledge_changed"
        # 产品没有把旧 revision 的答案提交成事实：消息里没有引用。
        assert turn.source_ids == ()
        _, listing = await adapter.list_messages(conversation_id)
        assistant = [item for item in listing["items"] if item["role"] == "assistant"]
        assert assistant and assistant[-1]["kind"] == "knowledge_changed"
        assert adapter.product_revision() >= 4
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 4. 反例：Mock 供应商 5xx / 断网 / 迟到都要停在产品入口，不产生真实调用
# --------------------------------------------------------------------------- #


@asyncio_test
async def test_mock_provider_failures_never_escape_to_network(tmp_path: Path) -> None:
    reset_post_counters()
    behaviors = (
        ChatBehavior(kind="http_error", status_code=429),
        ChatBehavior(kind="connect_error"),
        ChatBehavior(kind="invalid_json"),
    )
    chat = MockChatBackend(behaviors=behaviors)
    adapter = ProductEvalAdapter(
        tmp_path / "failures", chat=chat, dataset=empty_dataset(), ingest_plan=ingest_plan()
    )
    try:
        await adapter.ingest()
        conversation_id = await adapter.open_conversation()
        codes: list[str] = []
        for index in range(2):
            turn = await adapter.ask_turn(
                LEGACY_QUESTION,
                user_id="employee",
                conversation_id=conversation_id,
                client_request_id=f"8888888{index}-8888-4888-8888-88888888888{index}",
            )
            assert turn.http_status == 200
            assert turn.kind == "service_error", turn.as_dict(include_text=True)
            codes.append(str(turn.error_code))
            assert turn.trace_outcome == "service_error"
        assert all(
            code in {"MODEL_UNAVAILABLE", "MODEL_TIMEOUT", "MODEL_CALL_FAILED"}
            for code in codes
        ), codes
        assert chat.call_count == 2
        assert all(
            value == 0 for kind in post_counters().values() for value in kind.values()
        )
    finally:
        await adapter.close()


# --------------------------------------------------------------------------- #
# 5. T207-FIX-A §D：同一份资料的版本槽（历史版 -> 当前版 -> 未生效版）
# --------------------------------------------------------------------------- #


def version_slot_plan() -> P2IngestPlan:
    """V03 以 D01 的文件名首次上传（建槽）-> D01 作为同槽 v2 发布 -> V04 作为 v3 只处理不发布。

    只用 document_ref（本次 ingest 内按上传名解析 document_id），**不用** allow_same_name：
    后者建的是第二份独立文档，正是 T206 的失败形态（fix-scope §D）。
    """
    name = "D01_物品位置表.xlsx"
    return P2IngestPlan(
        sources=(
            IngestSource(path=V03, name=name),
            IngestSource(path=D01, document_ref=name),
            IngestSource(path=V04, document_ref=name, publish=False),
        ),
        label="t207-version-slot",
    )


def document_versions(adapter: ProductEvalAdapter, document_id: str) -> tuple[dict[str, Any], list[str]]:
    """只读产品库：返回 (文档摘要, 逐版本 state)；断言用，不写任何业务字段。"""
    import uuid

    from mktkb.documents.models import Document, DocumentVersion

    db = adapter.app.state.db.session()
    try:
        document = db.get(Document, uuid.UUID(document_id))
        assert document is not None, document_id
        versions = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.number)
            .all()
        )
        summary = {
            "name": document.name,
            "latest_version_number": int(document.latest_version_number),
            "active_version_number": next(
                (int(item.number) for item in versions if item.id == document.active_version_id), None
            ),
            "version_ids": {int(item.number): str(item.id) for item in versions},
        }
        return summary, [str(item.state) for item in versions]
    finally:
        db.close()


@asyncio_test
async def test_version_slot_keeps_history_current_and_unpublished(tmp_path: Path) -> None:
    reset_post_counters()
    # 记录型答案：产品会校验"答案值必须来自本轮 evidence"，所以这条固定答案只有在
    # 当前有效版是 v2（B区1号货架第二层）时才会被接受；v1/v3 都会因值不在 evidence 被拒。
    chat = MockChatBackend(
        behaviors=(ChatBehavior(answer="位置：B区1号货架第二层"),)
    )
    adapter = ProductEvalAdapter(
        tmp_path / "version-slot",
        chat=chat,
        dataset=empty_dataset(),
        ingest_plan=version_slot_plan(),
    )
    try:
        await adapter.start()
        receipts = await adapter.ingest()
        assert len(receipts) == 3
        assert [receipt.upload_status for receipt in receipts] == [202, 202, 202]
        assert [receipt.job_state for receipt in receipts] == ["succeeded"] * 3
        assert [receipt.publish_status for receipt in receipts] == [200, 200, None]
        assert [receipt.published for receipt in receipts] == [True, True, False]
        # 三份资料落在**同一个** document_id 上（版本槽），不是三份独立文档。
        assert len({receipt.document_id for receipt in receipts}) == 1
        assert [receipt.sha256 for receipt in receipts] == [
            hashlib.sha256(V03.read_bytes()).hexdigest(),
            hashlib.sha256(D01.read_bytes()).hexdigest(),
            hashlib.sha256(V04.read_bytes()).hexdigest(),
        ]
        document_map = adapter.ingest_document_map
        assert set(document_map) == {"D01_物品位置表.xlsx"}
        assert document_map["D01_物品位置表.xlsx"]["document_id"] == receipts[0].document_id
        assert document_map["D01_物品位置表.xlsx"]["active_version_id"] == receipts[1].version_id

        summary, states = document_versions(adapter, receipts[0].document_id)
        assert summary["latest_version_number"] == 3
        assert summary["active_version_number"] == 2
        assert states == ["superseded", "published", "review_required"]
        assert summary["version_ids"][2] != summary["version_ids"][3]
        # revision 只随发布递增：两次发布 = +2（v3 的处理与不发布都不入 revision）。
        assert adapter.product_revision() == 2
        status = adapter.index_status()
        assert status["ready"] is True and int(status["documents"]) == 1

        conversation_id = await adapter.open_conversation()
        turn = await adapter.ask_turn(
            "城东店的宣传海报在哪里？",
            user_id="employee",
            conversation_id=conversation_id,
            client_request_id="99999999-9999-4999-8999-999999999999",
        )
        assert turn.http_status == 200 and turn.kind == "answer", turn.as_dict(include_text=True)
        assert "B区1号货架第二层" in turn.text
        assert "D区暂存柜" not in turn.text, "未生效的 v3 不得进入回答"
        assert turn.sources, "产品回答必须带引用"
        cited = turn.sources[0]
        assert str(cited["document_name"]).startswith("D01_物品位置表")
        assert int(cited["version_number"]) == 2, "引用必须落在当前有效版（v2）"
        assert cited["status"] == "active"
        code, detail = await adapter.source_detail(turn.message_id or "", cited["source_id"])
        assert code == 200, detail
        assert detail["fields"]["位置"] == "B区1号货架第二层"
        assert detail["status"] == "active"
    finally:
        await adapter.close()


@asyncio_test
async def test_document_ref_unknown_fails_closed(tmp_path: Path) -> None:
    adapter = ProductEvalAdapter(
        tmp_path / "unknown-ref",
        chat=MockChatBackend(),
        dataset=empty_dataset(),
        ingest_plan=P2IngestPlan(
            sources=(IngestSource(path=D01, document_ref="从来没有上传过的名字.xlsx"),),
            label="t207-unknown-ref",
        ),
    )
    try:
        with pytest.raises(RuntimeError) as excinfo:
            await adapter.ingest()
        assert "document_ref" in str(excinfo.value)
        assert adapter.ingest_receipts == []
    finally:
        await adapter.close()


def test_ingest_source_rejects_ref_mixed_with_document_id_or_same_name() -> None:
    with pytest.raises(ValueError):
        IngestSource(path=D01, document_id="11111111-1111-4111-8111-111111111111", document_ref="x")
    with pytest.raises(ValueError):
        IngestSource(path=D01, document_ref="x", allow_same_name=True)
    with pytest.raises(ValueError):
        IngestSource(path=D01, document_ref="   ")


def test_ingest_plan_document_loader_and_cli_mutual_exclusion(tmp_path: Path) -> None:
    from mktkb.evaluation import cli as cli_module
    from mktkb.evaluation.product_adapter import (
        P2_INGEST_PLAN_DOCUMENT_SCHEMA_VERSION,
        ingest_plan_from_document,
    )

    payload = {
        "schema_version": P2_INGEST_PLAN_DOCUMENT_SCHEMA_VERSION,
        "label": "r1",
        "sources": [
            {"path": str(V03), "name": "D01_物品位置表.xlsx"},
            {"path": str(D01), "document_ref": "D01_物品位置表.xlsx"},
            {"path": str(V04), "document_ref": "D01_物品位置表.xlsx", "publish": False},
        ],
    }
    plan = ingest_plan_from_document(payload)
    assert plan.label == "r1"
    assert [source.document_ref for source in plan.sources] == [None, "D01_物品位置表.xlsx", "D01_物品位置表.xlsx"]
    assert [source.publish for source in plan.sources] == [True, True, False]
    assert plan.sources[0].name == "D01_物品位置表.xlsx"
    with pytest.raises(ValueError):
        ingest_plan_from_document({**payload, "document_id": "x"})
    with pytest.raises(ValueError):
        ingest_plan_from_document(
            {**payload, "sources": [{"path": str(D01), "document_id": "11111111-1111-4111-8111-111111111111"}]}
        )
    with pytest.raises(ValueError):
        ingest_plan_from_document({**payload, "schema_version": "p2-ingest-plan/v9"})

    # --ingest 与 --ingest-plan 互斥（argparse 层拒绝，退出码 2，不构造适配器）。
    plan_file = tmp_path / "plan.json"
    plan_file.write_text("{}", encoding="utf-8")
    ingest_file = tmp_path / "ingest-plan.json"
    ingest_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    code = cli_module.main(
        [
            "p2-run",
            "--plan",
            str(plan_file),
            "--out",
            str(tmp_path / "out"),
            "--ingest",
            str(D01),
            "--ingest-plan",
            str(ingest_file),
        ]
    )
    assert code == 2
