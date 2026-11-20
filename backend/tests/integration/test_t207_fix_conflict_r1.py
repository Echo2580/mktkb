"""T207-FIX-CONFLICT-R1 回归：图片类问题的收窄边界 + 冲突复核的异常兜底。

只闭环独立验收对本包提出的两项（不扩大改动面）：

1. **MEDIUM-1 收窄过度拦截**：`image_source_question` 原先把"已发布资料 + 图名"的提问
   （"组织架构图中…""流程图里…""根据物料领用通知图片要求…""从物料位置表截图…"）也判成
   图片输入、按范围外拒答。收窄后这些必须走正常问答路径（answer + 来源），而 N08 那类
   "以照片为事实来源"的问题仍按范围外 not_found（由 `test_t207_fix_conflict.py` 锁定）。
2. **LOW 异常兜底**：`_same_entity_evidence` 原只捕获 3 类检索异常，DB 层 `OperationalError`
   会冒泡成 500。补一层兜底后复核放弃（fail-closed：不披露冲突），由既有路径给出结论。

零真实调用：文档走真实解析/worker/HTTP/检索；模型是 `EvidenceEchoGateway`；D07/D09 的
OCR 用 `acceptance.support.ocr_transcripts` 的受控转录替身，不出网。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:  # 复用既有受控 OCR 转录表（不复制页面文字）
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.support import ocr_transcripts  # noqa: E402
from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (零出网闸门)

from mktkb.conversations import intent as intent_module  # noqa: E402
from mktkb.conversations import service as service_module  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.providers.types import OCRPageResult  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
NORMAL = ROOT / "fixtures" / "acceptance" / "normal"
D01 = NORMAL / "D01_物品位置表.xlsx"
D03 = NORMAL / "D03_市场部工作指南.docx"
D07 = NORMAL / "D07_活动申请扫描件.pdf"
D09 = NORMAL / "D09_物料领用通知.png"

#: 图片范围外拒答文案的特征词（命中即说明走了图片拒答而不是正常问答）
IMAGE_REFUSAL_MARKERS = ("范围外", "不做实物识别")

pytestmark = pytest.mark.usefixtures("t09_network_guard")


class _OcrStub:
    """受控 OCR 替身：按 file_id 回该文件的受控转录，逐次计数；不发网络请求。"""

    def __init__(self, file_id: str) -> None:
        self.file_id = file_id
        self.calls = 0

    def recognize(self, page, *, mode: str) -> OCRPageResult:
        self.calls += 1
        pages = ocr_transcripts.OCR_BINDINGS[self.file_id]["pages"]
        return OCRPageResult(
            text="\n".join(pages[page.page]),
            provider_request_id=f"r1-stub-{self.file_id}-{page.page}",
            confidence=90.0,
        )


def _run_worker(app, *, ocr=None) -> None:
    db = app.state.db.session()
    try:
        result = run_one_job(db, app.state.store, ocr=ocr)
    finally:
        db.close()
    assert result.state == "succeeded", result


def _publish(app, admin, *, path, ocr=None) -> dict:
    receipt = admin.upload(path=path)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    _run_worker(app, ocr=ocr)
    detail = admin.client.get(f"/api/v1/documents/{record['document']['id']}").json()
    published = admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        json={"expected_active_version_id": None, "expected_revision": detail["revision"]},
        headers=admin.headers,
    )
    assert published.status_code == 200, published.text
    return record


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


def test_published_document_image_phrases_use_normal_answer_path(
    chat_app, chat_admin, chat_employee
):
    """资料名 + 图名 / 裸"图中、图里"：走正常问答路径给出答案，不得按图片范围外拒答。"""
    _publish(chat_app, chat_admin, path=D01)
    _publish(chat_app, chat_admin, path=D03)
    d07 = _OcrStub("D07")
    d09 = _OcrStub("D09")
    _publish(chat_app, chat_admin, path=D07, ocr=d07)
    _publish(chat_app, chat_admin, path=D09, ocr=d09)
    assert d07.calls >= 1 and d09.calls >= 1, "扫描件/图片资料应真实走过受控 OCR 替身"

    for question in (
        "组织架构图中市场部向谁汇报？",  # 裸"图中"
        "流程图里第三步是谁审批？",  # 裸"图里"
        "根据物料领用通知图片要求先填写什么？",  # 资料名 + 图片
        "从物料位置表截图中能看出城东店的宣传海报放在哪？",  # 资料名 + 截图
    ):
        assert intent_module.image_source_question(question) is False, question
        payload = _ask(chat_employee, question)
        assert payload["kind"] == "answer", (question, payload)
        assert payload["sources"], (question, payload)
        for marker in IMAGE_REFUSAL_MARKERS:
            assert marker not in payload["text"], (question, payload["text"])

    # 裸"能看出什么"没有可定位的记录：走既有的补槽澄清（正常路径），仍不得是图片拒答。
    payload = _ask(chat_employee, "从物料位置表截图里能看出什么？")
    assert payload["kind"] == "clarification", payload
    for marker in IMAGE_REFUSAL_MARKERS:
        assert marker not in payload["text"], payload["text"]


def test_image_source_question_boundaries():
    """收窄口径：短修饰图名命中；资料名 + 图名、裸"图中/图里"不命中。"""
    for question in (
        "组织架构图中市场部向谁汇报？",
        "流程图里第三步是谁审批？",
        "根据物料领用通知图片要求先填写什么？",
        "从物料位置表截图里能看出什么？",
        "物料领用通知图片要求谁确认？",
        "巡检照片重复使用或者跨店套用，会被认定成什么？",
    ):
        assert intent_module.image_source_question(question) is False, question
    for question in (
        "根据货架照片告诉我没有标记物品的位置",
        "看这张图，告诉我城东店海报在哪",
        "照片里没有标记的物品放在哪",
        "从这张截图看，城东店的海报在哪",
        "看看货架照片，促销贴纸在哪",
    ):
        assert intent_module.image_source_question(question) is True, question


def test_conflict_recheck_db_error_is_fail_closed_not_500(
    chat_app, chat_admin, chat_employee, monkeypatch
):
    """同实体复核遇到 DB 层 OperationalError：放弃复核（不披露冲突），不得冒泡成 500。"""
    _publish(chat_app, chat_admin, path=D01)
    original = service_module._retrieve
    probes = {"count": 0}

    def retrieve_raises_on_probe(
        db_factory, intent, revision, limit=20, *, candidate_ids=None, as_of=None
    ):
        if candidate_ids is None and getattr(intent, "mode", None) == "record":
            probes["count"] += 1
            raise OperationalError("SELECT 1", {}, Exception("database is locked"))
        return original(
            db_factory, intent, revision, limit=limit, candidate_ids=candidate_ids, as_of=as_of
        )

    monkeypatch.setattr(service_module, "_retrieve", retrieve_raises_on_probe)

    payload = _ask(chat_employee, "城东店的宣传海报现在放在哪里？")

    assert probes["count"] == 1, "同实体复核探针必须真的执行过（否则本用例空转）"
    assert payload["kind"] == "answer", payload
    assert payload["conflicts"] == [], payload
    assert payload["sources"], payload
