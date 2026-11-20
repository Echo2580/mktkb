"""R2-206B 增量独立复验探针（外部复验者自建，合成件）。

被复验增量：``backend/src/mktkb/rag/query.py`` 单 hunk（+27/−2），
``mixed_restricted_roles = bool(restricted) and len(other_roles) >= 2 and not is_policy_question``，
命中物品/标识时从 ``field_roles`` 与 ``state.field_roles`` 剔除 ``phone``/``address``。

本文件**不是**开发方测试的复制：实体、值、文档名、问句全部独立虚构
（松涛店/竹溪店、电热壶/文件柜、020-00000011/示范巷27号），断言逐面独立
（正文 / sources[].locator / facts / 模型证据 / 捕获 envelope / 多回合状态继承）。

同时充当「改前/改后」对照工具：设 ``MKTKB_206B_DUMP=<path>`` 时把冻结用例的
**全表面规范化快照**写到该文件；在改动前树（工作树外沙箱 + 反向补丁）里跑同一
文件、同一数据集，两份 dump 逐字节比较即得"行为是否与改前相同"。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import openpyxl
import pytest

_TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))
from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from mktkb import copy as copy_module  # noqa: E402
from mktkb.conversations import intent as conv_intent  # noqa: E402
from mktkb.conversations import service as conv_service  # noqa: E402
from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.observability import evaluation_capture as cap  # noqa: E402
from mktkb.providers.deepseek import DeepSeekClient  # noqa: E402
from mktkb.rag import query as rag_query  # noqa: E402
from mktkb.rag.types import QueryState  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard", "no_subprocess")

# --------------------------------------------------------------------------- #
# 合成数据集（虚构；与开发方 206A 测试的实体/值不重叠）
# --------------------------------------------------------------------------- #

ITEM_DOC = "物品位置台账草案B.xlsx"
STORE_DOC = "合作店家名册草案B.xlsx"
ITEM_DOC_TITLE = "物品位置台账草案B"
STORE_DOC_TITLE = "合作店家名册草案B"
ITEM_HEADERS = ["门店", "物品", "标识", "位置", "数量"]
ITEM_ROWS = [
    ["松涛店", "电热壶", "Q07", "丙区2号架", "6"],
    ["竹溪店", "文件柜", "Q09", "丁区4号架", "3"],
]
STORE_HEADERS = ["标识", "店家", "联系人", "电话", "地址", "合作状态"]
STORE_ROWS = [
    ["S07", "松涛店", "合成负责人·丙", "020-00000011", "示范巷27号", "合作中"],
    ["S08", "竹溪店", "合成负责人·丁", "020-00000012", "示范巷35号", "暂停合作"],
]

STORE = "松涛店"
ITEM = "电热壶"
LOCATION_VALUE = "丙区2号架"
STATUS_VALUE = "合作中"
CONTACT_VALUE = "合成负责人·丙"
PHONE_VALUE = "020-00000011"
ADDRESS_VALUE = "示范巷27号"
FORBIDDEN_VALUES = (PHONE_VALUE, ADDRESS_VALUE, CONTACT_VALUE)

#: A：三角色混合（物品 + 位置 + 状态 + 电话）——本批要转绿的形态。
QUESTION_MIXED_3 = f"{STORE}的{ITEM}放在哪个位置，合作状态分别是什么，电话是多少？"
#: A：四角色混合（再加地址）。
QUESTION_MIXED_4 = f"{STORE}的{ITEM}放在哪个位置，合作状态分别是什么，电话和地址是多少？"
#: B1：物品 + 只问电话（冻结拒答面）。
QUESTION_PHONE_ONLY = f"{STORE}的{ITEM}电话是多少？"
#: B2：物品 + 只问 contact（冻结放行面）。
QUESTION_CONTACT_ONLY = f"{STORE}的{ITEM}由谁对接？"
#: B3：凭据族（R1/102c 冻结拒答面）。
QUESTION_CREDENTIAL = f"{STORE}的{ITEM}放在哪，由谁对接，完整合同和结算账号是多少？"
#: B4a：双角色混合“位置 + 联系电话”⇒ others=1 ⇒ 应仍拒答。
QUESTION_DUAL_LOCATION_PHONE = f"{STORE}的{ITEM}放在什么位置，联系电话是多少？"
#: B4b：双角色混合“找谁对接 + 电话和地址”⇒ others=1 ⇒ 应仍拒答。
QUESTION_DUAL_CONTACT_PHONE_ADDRESS = f"{STORE}的{ITEM}找谁对接，电话和地址是多少？"
#: 扩展观察：others=2 但既非 C29 同形（位置 + 数量 + 电话）⇒ 设计上会被放行。
QUESTION_MIXED_LOCATION_QUANTITY_PHONE = f"{STORE}的{ITEM}放在哪个位置，数量是多少，电话是多少？"
#: D：legacy（非枚举）混合形态——第二道闸门（conversations/intent.py:507-527）的靶子。
QUESTION_LEGACY_MIX = f"{STORE}的{ITEM}放在哪个位置，合作状态如何，电话是多少？"

FROZEN_QUESTIONS = {
    "b1_phone_only": QUESTION_PHONE_ONLY,
    "b2_contact_only": QUESTION_CONTACT_ONLY,
    "b3_credential": QUESTION_CREDENTIAL,
    "b4a_location_phone": QUESTION_DUAL_LOCATION_PHONE,
    "b4b_contact_phone_address": QUESTION_DUAL_CONTACT_PHONE_ADDRESS,
}
MIXED_QUESTIONS = {"a1_mixed3": QUESTION_MIXED_3, "a2_mixed4": QUESTION_MIXED_4}

#: 与 ``refusal`` 文案无关的稳定拒绝原因码（开发方声明未改文案；这里只锁码与面）。
REFUSAL_REASON = "SECURITY_RESTRICTED_CONTACT"


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #


@pytest.fixture
def no_subprocess(monkeypatch):
    calls: list[tuple] = []

    def _blocked(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append((args, tuple(sorted(kwargs))))
        raise AssertionError("合成链路不得启动子进程")

    monkeypatch.setattr(subprocess, "Popen", _blocked)
    monkeypatch.setattr(subprocess, "run", _blocked)
    yield calls
    assert calls == [], calls


def _xlsx(path: Path, headers: list[str], rows: list[list[object]], title: str) -> Path:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "台账"
    worksheet.cell(row=1, column=1, value=title)
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=3, column=column, value=header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            worksheet.cell(row=4 + offset, column=column, value=value)
    workbook.save(path)
    return path


def _publish(app, admin: SimpleNamespace, path: Path) -> None:
    receipt = admin.upload(path=path)
    assert receipt.status_code == 202, receipt.text
    record = receipt.json()
    db = app.state.db.session()
    try:
        assert run_one_job(db, app.state.store).state == "succeeded"
    finally:
        db.close()
    db = app.state.db.session()
    try:
        revision = get_revision(db)
    finally:
        db.close()
    published = admin.client.post(
        f"/api/v1/documents/{record['document']['id']}/versions/{record['version']['id']}/publish",
        headers=admin.headers,
        json={"expected_active_version_id": None, "expected_revision": revision},
    )
    assert published.status_code == 200, published.text


def _dataset(app, admin: SimpleNamespace) -> None:
    for name, headers, rows, title in (
        (ITEM_DOC, ITEM_HEADERS, ITEM_ROWS, ITEM_DOC_TITLE),
        (STORE_DOC, STORE_HEADERS, STORE_ROWS, STORE_DOC_TITLE),
    ):
        _publish(app, admin, _xlsx(Path(app.state.settings.data_dir) / name, headers, rows, title))


def _conversation(session: SimpleNamespace) -> str:
    response = session.client.post("/api/v1/conversations", json={}, headers=session.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _ask(session: SimpleNamespace, conversation_id: str, question: str) -> dict:
    response = session.client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"client_request_id": str(uuid.uuid4()), "question": question},
        headers=session.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _user_id(session: SimpleNamespace) -> str:
    return str(session.client.get("/api/v1/auth/me").json()["user"]["id"])


def _plan_view(plan) -> dict:
    return {
        "reason": getattr(plan, "reason", None),
        "mode": str(getattr(plan, "mode", "")),
        "field_role": getattr(plan, "field_role", None),
        "field_roles": list(getattr(plan, "field_roles", ()) or ()),
        "state_field_role": getattr(plan.state, "field_role", None),
        "state_field_roles": list(getattr(plan.state, "field_roles", ()) or ()),
        "enumerate": bool(getattr(plan, "enumerate", False)),
        "clarification": bool(getattr(plan, "clarification", None)),
        "filters": dict(getattr(plan, "filters", {}) or {}),
        "term_count": len(getattr(plan, "terms", ()) or ()),
    }


def _rag_view(answer) -> dict:
    return {
        "kind": answer.kind,
        "text": answer.text or "",
        "reason": answer.reason,
        "answer_source": getattr(answer, "answer_source", None),
        "facts": sorted(
            (str(f.field_role), str(f.value)) for f in (getattr(answer, "facts", ()) or ())
        ),
        "citations": [
            {"title": c.title, "locator": dict(c.locator or {})}
            for c in (getattr(answer, "citations", ()) or ())
        ],
        "diagnostics": answer.diagnostics,
    }


def _body_view(body: dict) -> dict:
    return {
        "kind": body.get("kind"),
        "text": body.get("text") or "",
        "sources": [
            {
                "document_name": item.get("document_name"),
                "version_number": item.get("version_number"),
                "status": item.get("status"),
                "locator": item.get("locator") or {},
            }
            for item in (body.get("sources") or [])
        ],
        "candidates": [c.get("label") for c in (body.get("candidates") or [])],
        "missing_fields": list(body.get("missing_fields") or []),
        "pagination": body.get("pagination"),
        "error_code": body.get("error_code"),
    }


def _capture_view(sink) -> dict:
    """捕获 envelope 的规范化投影（不采 id / 时间戳）。"""

    events = []
    for event in sink.events or []:
        payload = event.get("payload") or {}
        kind = event.get("kind")
        kept: dict[str, Any] = {}
        for key, value in payload.items():
            if key in _EXCLUDED_KEYS:
                continue
            if kind == "model_input" and key == "evidence":
                kept[key] = [
                    {"text": item.get("text"), "fields": dict(item.get("fields") or {})}
                    for item in (value or [])
                ]
            else:
                kept[key] = value
        events.append({"kind": kind, "payload": kept})
    return {"status": sink.status, "error_count": len(sink.errors or []), "events": events}


_EXCLUDED_KEYS = {
    "request_id",
    "message_id",
    "conversation_id",
    "user_id",
    "authenticated_user_id",
    "owner_user_id",
    "source_id",
    "source_ids",
    "document_id",
    "version_id",
    "unit_ids",
    "published_at",
    "created_at",
    "provider_request_id",
    "revision",
    "initial_revision",
    "elapsed_ms",
    "budget",
    "budget_error",
    # 单次运行的切块内容哈希（32 位 hex），不是行为面。
    "evidence_ids",
}

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)?")


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize(item)
            for key, item in value.items()
            if key not in _EXCLUDED_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, str):
        return _TS_RE.sub("<ts>", _UUID_RE.sub("<uuid>", value))
    return value


def _probe(app, session: SimpleNamespace, question: str) -> dict:
    """同一题的四条独立面：规划层 / rag 内核 / HTTP 用户面 / 捕获 envelope。"""

    qa = app.state.qa
    qa.ensure_ready()
    user_id = _user_id(session)

    state, plan = qa.prepare(question, user_id, _conversation(session))
    rag_answer = qa.answer(question, user_id, _conversation(session))

    sink = cap.CaptureSink()
    with cap.capture_scope(sink):
        body = _ask(session, _conversation(session), question)

    return {
        "question": question,
        "state_view": {
            "field_role": getattr(state, "field_role", None),
            "field_roles": list(getattr(state, "field_roles", ()) or ()),
        },
        # 产品层是否把该回合交给 rag 内核（否则走 legacy + 第二道闸门）。
        "rag_owns_turn": conv_service._rag_owns_turn(QueryState(), plan),
        "plan": _plan_view(plan),
        "rag": _rag_view(rag_answer),
        "body": _body_view(body),
        "capture": _capture_view(sink),
    }


def _ask_info(app, session: SimpleNamespace, question: str) -> dict:
    gateway = app.state.model_gateway
    start = len(gateway.calls)
    info = _probe(app, session, question)
    info["model_calls"] = [
        {
            "purpose": call.get("purpose"),
            "question": call.get("question"),
            "evidence": [
                {"text": item.get("text"), "fields": dict(item.get("fields") or {})}
                for item in (call.get("evidence") or [])
            ],
        }
        for call in gateway.calls[start:]
    ]
    return info


def _flatten(info: dict) -> str:
    return json.dumps(_normalize(info), ensure_ascii=False, sort_keys=True)


def _refusal_text() -> str:
    return copy_module.text(REFUSAL_REASON)


# --------------------------------------------------------------------------- #
# A：混合形态转绿 + 不泄漏
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", sorted(MIXED_QUESTIONS))
def test_a_mixed_roles_answer_without_contact_values(
    chat_app, chat_admin, chat_employee, chat_model, key
):
    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, MIXED_QUESTIONS[key])
    plan, body, rag = info["plan"], info["body"], info["rag"]

    # 规划层：不再整题受限；受限角色已从本轮角色集合剔除。
    assert plan["reason"] is None, plan
    assert "phone" not in plan["field_roles"], plan
    assert "address" not in plan["field_roles"], plan
    assert "phone" not in plan["state_field_roles"], plan
    assert "address" not in plan["state_field_roles"], plan
    assert set(plan["field_roles"]) == {"location", "status"}, plan
    assert plan["mode"] == "record" and plan["enumerate"] is True, plan

    # 用户面：正常作答，位置值与状态值同时出现，来源 ≥1。
    assert body["kind"] == "answer", body
    assert LOCATION_VALUE in body["text"], body["text"]
    assert STATUS_VALUE in body["text"], body["text"]
    assert len(body["sources"]) >= 1, body
    assert {item["document_name"] for item in body["sources"]} == {ITEM_DOC, STORE_DOC}, body
    for value in FORBIDDEN_VALUES:
        assert value not in body["text"], (value, body["text"])

    # 内核面：facts 只含 location/status；结构化枚举下模型 0 调用。
    assert rag["kind"] == "answer", rag
    assert {role for role, _value in rag["facts"]} == {"location", "status"}, rag["facts"]
    assert {value for _role, value in rag["facts"]}.isdisjoint(FORBIDDEN_VALUES), rag["facts"]
    assert info["model_calls"] == [], info["model_calls"]


def test_a_mixed_dump(chat_app, chat_admin, chat_employee, chat_model):
    """把混合形态的全表面快照写到 ``MKTKB_206B_MIXED_DUMP``（改前/改后行为对照用）。"""

    _dataset(chat_app, chat_admin)
    dump = {
        key: _ask_info(chat_app, chat_employee, question)
        for key, question in sorted(MIXED_QUESTIONS.items())
    }
    path = os.environ.get("MKTKB_206B_MIXED_DUMP")
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(_normalize(dump), ensure_ascii=False, sort_keys=True, indent=1),
            encoding="utf-8",
        )
    assert dump["a1_mixed3"]["body"]["kind"] == "answer"
    assert dump["a2_mixed4"]["body"]["kind"] == "answer"


def test_a_mixed_roles_are_identical_across_three_and_four_role_forms(
    chat_app, chat_admin, chat_employee, chat_model
):
    """四角色（再加 address）与三角色应同形：答案、facts、角色集合一致。"""

    _dataset(chat_app, chat_admin)
    three = _ask_info(chat_app, chat_employee, QUESTION_MIXED_3)
    four = _ask_info(chat_app, chat_employee, QUESTION_MIXED_4)
    assert three["body"]["kind"] == "answer" and four["body"]["kind"] == "answer"
    assert three["plan"]["field_roles"] == four["plan"]["field_roles"], (three["plan"], four["plan"])
    assert three["rag"]["facts"] == four["rag"]["facts"], (three["rag"]["facts"], four["rag"]["facts"])
    for value in FORBIDDEN_VALUES:
        assert value not in four["body"]["text"], (value, four["body"]["text"])


# --------------------------------------------------------------------------- #
# B：冻结面（含改前/改后逐字节对照由 dump 比对完成）
# --------------------------------------------------------------------------- #


def test_b1_item_plus_phone_only_still_refused(chat_app, chat_admin, chat_employee, chat_model):
    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_PHONE_ONLY)

    assert info["plan"]["reason"] == REFUSAL_REASON, info["plan"]
    assert info["body"]["kind"] == "not_found", info["body"]
    assert info["body"]["sources"] == [], info["body"]
    assert info["rag"]["facts"] == [] and info["rag"]["citations"] == [], info["rag"]
    assert info["rag"]["kind"] == "no_answer", info["rag"]
    assert PHONE_VALUE not in info["body"]["text"], info["body"]["text"]
    assert info["body"]["text"] == _refusal_text(), info["body"]["text"]
    assert info["model_calls"] == [], "拒答必须早于模型"
    assert "phone" in info["plan"]["state_field_roles"], info["plan"]


def test_b2_item_plus_contact_only_still_answered(chat_app, chat_admin, chat_employee, chat_model):
    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_CONTACT_ONLY)

    assert info["plan"]["reason"] is None, info["plan"]
    assert info["plan"]["field_roles"] == ["contact"], info["plan"]
    assert info["body"]["kind"] == "answer", info["body"]
    assert info["body"]["sources"], info["body"]
    assert PHONE_VALUE not in info["body"]["text"], info["body"]["text"]
    assert ADDRESS_VALUE not in json.dumps(info["body"]["sources"], ensure_ascii=False)


def test_b3_credential_family_still_refused(chat_app, chat_admin, chat_employee, chat_model):
    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_CREDENTIAL)

    assert info["plan"]["reason"] == REFUSAL_REASON, info["plan"]
    assert info["body"]["kind"] == "not_found", info["body"]
    assert info["body"]["sources"] == [], info["body"]
    assert info["rag"]["facts"] == [] and info["rag"]["citations"] == [], info["rag"]
    for value in (LOCATION_VALUE, STATUS_VALUE, *FORBIDDEN_VALUES):
        assert value not in info["body"]["text"], (value, info["body"]["text"])
    assert info["model_calls"] == [], "拒答必须早于模型"


@pytest.mark.parametrize(
    ("key", "question"),
    [
        ("b4a", QUESTION_DUAL_LOCATION_PHONE),
        ("b4b", QUESTION_DUAL_CONTACT_PHONE_ADDRESS),
    ],
)
def test_b4_dual_role_mixed_still_refused(
    chat_app, chat_admin, chat_employee, chat_model, key, question
):
    """``others == 1`` 的双角色混合：**必须**保持整题拒答（>=2 的阈值不是放宽到 >=1）。"""

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, question)

    assert info["plan"]["reason"] == REFUSAL_REASON, (key, info["plan"])
    assert info["plan"]["field_roles"] == [], info["plan"]
    assert info["body"]["kind"] == "not_found", (key, info["body"])
    assert info["body"]["sources"] == [], (key, info["body"])
    assert info["rag"]["kind"] == "no_answer", (key, info["rag"])
    assert info["rag"]["facts"] == [] and info["rag"]["citations"] == [], (key, info["rag"])
    for value in (LOCATION_VALUE, *FORBIDDEN_VALUES):
        assert value not in info["body"]["text"], (key, value, info["body"]["text"])
    assert info["model_calls"] == [], (key, "拒答必须早于模型")

    # 规划层必须仍走**同一条**早退分支（不是靠下游文案兜底）。
    roles = rag_query.field_roles_for_question(question, has_entity=True)
    assert "phone" in roles or "address" in roles, roles
    others = set(roles) - {"phone", "address"}
    assert len(others) == 1, (key, roles)
    assert info["body"]["text"] == _refusal_text(), info["body"]["text"]


def test_b4_threshold_is_two_others_not_one(chat_app, chat_admin, chat_employee, chat_model):
    """阈值边界：``others == 1`` 与 ``others == 2`` 的差别只体现在**规划层**。

    观察（不是开发方声明）：``others == 2`` 的非枚举形态（位置 + 数量 + 电话）规划层
    不再拒答，但产品层的 legacy 第二道闸门仍整题拒答 ⇒ 用户面仍是 ``not_found``，
    即本批"转绿"只在 ``_rag_owns_turn`` 为真的枚举轮次生效。
    """

    _dataset(chat_app, chat_admin)
    one = _ask_info(chat_app, chat_employee, QUESTION_DUAL_LOCATION_PHONE)
    two = _ask_info(chat_app, chat_employee, QUESTION_MIXED_LOCATION_QUANTITY_PHONE)

    assert len(set(rag_query.field_roles_for_question(QUESTION_DUAL_LOCATION_PHONE)) - {"phone", "address"}) == 1
    assert len(
        set(rag_query.field_roles_for_question(QUESTION_MIXED_LOCATION_QUANTITY_PHONE)) - {"phone", "address"}
    ) == 2

    assert one["plan"]["reason"] == REFUSAL_REASON and one["body"]["kind"] == "not_found", one["body"]
    assert two["plan"]["reason"] is None, two["plan"]
    assert "phone" not in two["plan"]["field_roles"], two["plan"]
    assert two["rag_owns_turn"] is False, two
    assert two["body"]["kind"] == "not_found", two["body"]
    assert two["body"]["text"] == _refusal_text(), two["body"]["text"]
    assert PHONE_VALUE not in two["body"]["text"], two["body"]["text"]


def test_b_dump_frozen_surfaces(chat_app, chat_admin, chat_employee, chat_model):
    """把冻结用例的全表面规范化快照写到 ``MKTKB_206B_DUMP``（供跨树逐字节比对）。"""

    _dataset(chat_app, chat_admin)
    dump = {
        key: _ask_info(chat_app, chat_employee, question)
        for key, question in sorted(FROZEN_QUESTIONS.items())
    }
    # 冻结面自身的断言（不依赖 dump 比对）
    assert dump["b1_phone_only"]["body"]["kind"] == "not_found"
    assert dump["b2_contact_only"]["body"]["kind"] == "answer"
    assert dump["b3_credential"]["body"]["kind"] == "not_found"
    assert dump["b4a_location_phone"]["body"]["kind"] == "not_found"
    assert dump["b4b_contact_phone_address"]["body"]["kind"] == "not_found"

    path = os.environ.get("MKTKB_206B_DUMP")
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(_normalize(dump), ensure_ascii=False, sort_keys=True, indent=1),
            encoding="utf-8",
        )


# --------------------------------------------------------------------------- #
# C：泄漏面逐面断言（正文 / sources[].locator / facts / 模型证据 / 捕获 envelope）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", sorted(MIXED_QUESTIONS))
def test_c_locator_cells_must_not_expose_restricted_values(chat_app, chat_admin, chat_employee, chat_model, key):
    """C-2（用户面 ``sources[].locator.cells``）：不得出现电话/地址/联系人的值。

    这是本文件的核心证伪点。观测到的现状（见 evidence/10-attempt2/R2-206B-REVIEW.md）：
    店家行引用的 ``locator.cells[*].display`` 把整行每个单元格的值都列了出来，其中包含
    ``电话`` 与 ``地址`` 两列 ⇒ 混合题在被放行后把受限值带进了用户可读的
    ``sources[].locator``。改前该题整题拒答、``sources == []``，因此这是本批**新引入**的暴露面。
    """

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, MIXED_QUESTIONS[key])
    assert info["body"]["kind"] == "answer", info["body"]
    serialized = json.dumps(info["body"]["sources"], ensure_ascii=False)
    leaked = [value for value in FORBIDDEN_VALUES if value in serialized]
    assert leaked == [], (
        f"{key}: sources[].locator 内出现受限值 {leaked}；"
        f"用户可读的 locator={serialized[:1200]}"
    )


def test_c_store_level_citation_locator_is_a_preexisting_surface(
    chat_app, chat_admin, chat_employee, chat_model
):
    """归因对照：**店家级**问题（本批未改动的既有放行面）是否同样把整行值带进 locator。

    若同样带出，则 ``locator.cells`` 的全行取值是 citation 设计的既有行为，本批的问题是
    "让一个原本整题拒答的混合题首次走到该面"，而不是本批新写了泄漏代码。
    """

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, f"{STORE}的合作状态是什么？")
    assert info["body"]["kind"] == "answer", info["body"]
    serialized = json.dumps(info["body"]["sources"], ensure_ascii=False)
    leaked = [value for value in FORBIDDEN_VALUES if value in serialized]
    # 只记录、不断言为通过：这里把观测值写进断言消息，便于人工裁决归因。
    assert info["body"]["sources"], info["body"]
    print("STORE_ONLY_LOCATOR_LEAK " + json.dumps(leaked, ensure_ascii=False))


@pytest.mark.parametrize("key", sorted(MIXED_QUESTIONS))
def test_c_closed_surfaces_text_facts_model_capture(
    chat_app, chat_admin, chat_employee, chat_model, key
):
    _dataset(chat_app, chat_admin)
    question = MIXED_QUESTIONS[key]
    info = _ask_info(chat_app, chat_employee, question)

    # C-1 正文
    for value in FORBIDDEN_VALUES:
        assert value not in info["body"]["text"], ("text", value)

    # C-3 facts（内核结构化事实）
    fact_values = {value for _role, value in info["rag"]["facts"]}
    assert fact_values.isdisjoint(FORBIDDEN_VALUES), fact_values
    # facts 与 citations 的 role 集合不含受限角色
    assert not ({"phone", "address"} & {role for role, _v in info["rag"]["facts"]})

    # C-4 模型证据字段：结构化枚举轮次 0 调用 ⇒ 证据面不可达；若有调用则逐项断言。
    for call in info["model_calls"]:
        payload = json.dumps(call, ensure_ascii=False)
        for value in FORBIDDEN_VALUES:
            assert value not in payload, ("model_evidence", value, call.get("purpose"))

    # C-5 捕获 envelope：plan_observed 里不得出现 phone/address 角色；
    #     任何 model_input 事件的 evidence 都逐项断言不含受限值。
    plan_events = [
        event for event in info["capture"]["events"] if event["kind"] == "plan_observed"
    ]
    assert plan_events, info["capture"]
    for event in plan_events:
        roles = set(event["payload"].get("field_roles") or [])
        assert not ({"phone", "address"} & roles), event
        assert event["payload"].get("field_role") not in {"phone", "address"}, event
    for event in info["capture"]["events"]:
        if event["kind"] != "model_input":
            continue
        payload = json.dumps(event["payload"], ensure_ascii=False)
        for value in FORBIDDEN_VALUES:
            assert value not in payload, ("capture.model_input", value)

    # C-5b 整个捕获 envelope（含 direct_rag_answer.facts / answer_result / commit_observed）
    capture_json = json.dumps(info["capture"]["events"], ensure_ascii=False)
    for value in FORBIDDEN_VALUES:
        assert value not in capture_json, ("capture", value)

    # C-6 捕获 envelope 里不存在名为 requested_fields 的键（本仓 envelope 的角色码键是
    #     plan_observed.field_role(s)）；若未来新增该键，本断言会提醒复核其内容。
    for event in info["capture"]["events"]:
        assert "requested_fields" not in event["payload"], event


def test_c_multi_turn_inherited_state_does_not_leak_phone(
    chat_app, chat_admin, chat_employee, chat_model
):
    """多回合：先被拒的“只问电话”轮次把 phone 写进 state.field_roles；后续**裸追问**不得泄漏。"""

    _dataset(chat_app, chat_admin)
    qa = chat_app.state.qa
    qa.ensure_ready()
    user_id = _user_id(chat_employee)
    conversation_id = _conversation(chat_employee)

    first = _ask(chat_employee, conversation_id, QUESTION_PHONE_ONLY)
    assert first["kind"] == "not_found", first
    second = _ask(chat_employee, conversation_id, "还有呢？")
    second_text = second.get("text") or ""
    for value in FORBIDDEN_VALUES:
        assert value not in second_text, ("turn2", value, second_text)
    third = _ask(chat_employee, conversation_id, "那位置呢？")
    third_text = third.get("text") or ""
    for value in FORBIDDEN_VALUES:
        assert value not in third_text, ("turn3", value, third_text)
    assert LOCATION_VALUE in third_text, third_text
    for call in chat_app.state.model_gateway.calls:
        payload = json.dumps(
            [
                {"text": item.get("text"), "fields": dict(item.get("fields") or {})}
                for item in (call.get("evidence") or [])
            ],
            ensure_ascii=False,
        )
        for value in (PHONE_VALUE, ADDRESS_VALUE):
            assert value not in payload, ("multi_turn_model_evidence", value)


# --------------------------------------------------------------------------- #
# D：第二道闸门（conversations/intent.py:507-527）
# --------------------------------------------------------------------------- #


def test_d_legacy_second_gate_still_refuses_non_enumerated_mixed(
    chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin)

    # 1) 规划层：该题**不是**枚举轮（因此产品层把回合交给 legacy 路径），且规划层已把
    #    phone 从角色集合剔除 —— 也就是说，下游 intent 闸门是这条路径上唯一的拒答点。
    info = _ask_info(chat_app, chat_employee, QUESTION_LEGACY_MIX)
    assert info["plan"]["reason"] is None, info["plan"]
    assert info["plan"]["enumerate"] is False, info["plan"]
    assert "phone" not in info["plan"]["field_roles"], info["plan"]
    assert info["rag_owns_turn"] is False, info

    # 2) 第二道闸门本体：直接解析同一题，必须给出受限拒答原因码。
    db = chat_app.state.db.session()
    try:
        lexicon = conv_intent.load_lexicon(db)
    finally:
        db.close()
    intent_plan = conv_intent.parse_question(QUESTION_LEGACY_MIX, lexicon=lexicon)
    assert intent_plan.security_refusal == REFUSAL_REASON, intent_plan
    assert "电话" in intent_plan.requested_fields, intent_plan.requested_fields

    # 3) 用户面：仍是整题拒答，零来源、零事实、零模型调用，且不含任何受限值。
    assert info["body"]["kind"] == "not_found", info["body"]
    assert info["body"]["sources"] == [], info["body"]
    assert info["body"]["text"] == _refusal_text(), info["body"]["text"]
    for value in (LOCATION_VALUE, STATUS_VALUE, *FORBIDDEN_VALUES):
        assert value not in info["body"]["text"], (value, info["body"]["text"])
    assert info["model_calls"] == [], "legacy 闸门必须早于模型"


# --------------------------------------------------------------------------- #
# E：店家记录正文回显（只问状态时不得附带未请求的联系人/电话/地址）
# --------------------------------------------------------------------------- #


def test_e_store_status_does_not_echo_unrequested_contact_fields(
    chat_app, chat_admin, chat_employee, chat_model
):
    """只问合作状态：正文只应回答状态及公开对象名，不得附带整行联系字段。"""

    _dataset(chat_app, chat_admin)
    chat_model.answer_text = f"根据资料：合作状态：{STATUS_VALUE}。"

    body = _ask(chat_employee, _conversation(chat_employee), f"{STORE}的合作状态是什么？")

    assert body["kind"] == "answer", body
    assert STATUS_VALUE in body["text"], body["text"]
    for value in FORBIDDEN_VALUES:
        assert value not in body["text"], (value, body["text"])
    assert [item["document_name"] for item in body["sources"]] == [STORE_DOC], body["sources"]
    source = body["sources"][0]
    assert source["status"] == "active" and source["version_number"] == 1, source
    assert source["locator"].get("sheet") == "台账", source
    assert source["locator"].get("row") == 4, source
    assert "cells" not in source["locator"], source


def test_e_status_model_echo_is_not_promoted_to_user_text(
    chat_app, chat_admin, chat_employee, chat_model
):
    """模型即使回显整行联系值，只问状态时正文也只保留已校验状态和公开对象名。"""

    _dataset(chat_app, chat_admin)
    chat_model.answer_text = (
        f"根据资料：合作状态：{STATUS_VALUE}；联系人：{CONTACT_VALUE}；"
        f"电话：{PHONE_VALUE}；地址：{ADDRESS_VALUE}。"
    )

    body = _ask(chat_employee, _conversation(chat_employee), f"{STORE}的合作状态是什么？")

    assert body["kind"] == "answer", body
    assert STATUS_VALUE in body["text"], body["text"]
    for value in FORBIDDEN_VALUES:
        assert value not in body["text"], (value, body["text"])
    assert body["sources"][0]["locator"].get("row") == 4, body["sources"]


def test_e_status_filter_uses_existing_header_aliases(chat_app, chat_admin, chat_employee, chat_model):
    """行内使用登记别名（负责人/联系方式/门店地址）时，只问状态仍不得附带这些值。"""

    alias_doc = "合成验收别名店家.xlsx"
    _publish(
        chat_app,
        chat_admin,
        _xlsx(
            Path(chat_app.state.settings.data_dir) / alias_doc,
            ["标识", "店家", "负责人", "联系方式", "门店地址", "合作状态"],
            [["SX-ALIAS", STORE, CONTACT_VALUE, PHONE_VALUE, ADDRESS_VALUE, STATUS_VALUE]],
            "合成验收别名店家",
        ),
    )
    chat_model.answer_text = f"根据资料：合作状态：{STATUS_VALUE}。"

    body = _ask(chat_employee, _conversation(chat_employee), f"{STORE}的合作状态是什么？")

    assert body["kind"] == "answer", body
    assert STATUS_VALUE in body["text"], body["text"]
    for value in FORBIDDEN_VALUES:
        assert value not in body["text"], (value, body["text"])
    assert [item["document_name"] for item in body["sources"]] == [alias_doc], body["sources"]
    assert body["sources"][0]["locator"].get("row") == 4, body["sources"]


def test_e_new_answer_replay_and_history_are_echo_clean(
    chat_app, chat_admin, chat_employee, chat_model
):
    """本次新生成回答的重放和历史读取：同一已校验正文，三个合成标记零命中。"""

    _dataset(chat_app, chat_admin)
    chat_model.answer_text = f"根据资料：合作状态：{STATUS_VALUE}。"
    conversation_id = _conversation(chat_employee)
    request_id = str(uuid.uuid4())
    url = f"/api/v1/conversations/{conversation_id}/messages"
    payload = {"client_request_id": request_id, "question": f"{STORE}的合作状态是什么？"}

    first = chat_employee.client.post(url, json=payload, headers=chat_employee.headers)
    assert first.status_code == 200, first.text
    first_body = first.json()
    replay = chat_employee.client.post(url, json=payload, headers=chat_employee.headers)
    assert replay.status_code == 200, replay.text
    replay_body = replay.json()

    assert first_body["kind"] == replay_body["kind"] == "answer", (first_body, replay_body)
    assert first_body["message_id"] == replay_body["message_id"]
    assert first_body["text"] == replay_body["text"], (first_body["text"], replay_body["text"])
    for body in (first_body, replay_body):
        for value in FORBIDDEN_VALUES:
            assert value not in body["text"], (value, body["text"])
        assert body["sources"][0]["locator"].get("row") == 4, body["sources"]

    history = chat_employee.client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=chat_employee.headers
    )
    assert history.status_code == 200, history.text
    assistant = [item for item in history.json()["items"] if item["role"] == "assistant"]
    assert len(assistant) == 1, assistant
    assert assistant[0]["text"] == first_body["text"], assistant[0]["text"]
    for value in FORBIDDEN_VALUES:
        assert value not in assistant[0]["text"], (value, assistant[0]["text"])
    assert assistant[0]["sources"][0]["locator"].get("row") == 4, assistant[0]["sources"]
    assert "cells" not in assistant[0]["sources"][0]["locator"], assistant[0]["sources"]


@pytest.mark.parametrize(
    ("asked_field", "asked_value"),
    [
        ("联系人", CONTACT_VALUE),
        ("电话", PHONE_VALUE),
        ("地址", ADDRESS_VALUE),
    ],
)
def test_e_explicitly_requested_contact_field_still_answered(
    chat_app, chat_admin, chat_employee, chat_model, asked_field, asked_value
):
    """显式请求且既有策略允许的字段继续作答；不改变既有“同行联系人随电话回显”等契约。"""

    _dataset(chat_app, chat_admin)
    chat_model.answer_text = f"根据资料：{asked_field}：{asked_value}。"

    body = _ask(chat_employee, _conversation(chat_employee), f"{STORE}的{asked_field}是什么？")

    assert body["kind"] == "answer", body
    assert asked_value in body["text"], body["text"]
    assert body["sources"], body
    assert body["sources"][0]["locator"].get("row") == 4, body["sources"]


def test_e_store_level_credential_request_still_refused(
    chat_app, chat_admin, chat_employee, chat_model
):
    """既有凭据族在店家级问法下仍整题拒答，正文不含状态或联系值。"""

    _dataset(chat_app, chat_admin)
    body = _ask(
        chat_employee,
        _conversation(chat_employee),
        f"{STORE}的合作状态是什么，完整合同和结算账号是多少？",
    )

    assert body["kind"] == "not_found", body
    assert body["sources"] == [], body
    for value in (STATUS_VALUE, *FORBIDDEN_VALUES):
        assert value not in body["text"], (value, body["text"])
    assert chat_model.calls == [], "拒答必须早于模型"


@pytest.mark.parametrize(
    ("field", "value"),
    [("合作状态", STATUS_VALUE), ("联系人", CONTACT_VALUE), ("电话", PHONE_VALUE), ("地址", ADDRESS_VALUE)],
)
def test_record_provider_payload_only_contains_requested_contact_values(
    chat_app, chat_admin, chat_employee, chat_model, monkeypatch, field, value
):
    _dataset(chat_app, chat_admin)
    captured = []

    def reply(request):
        payload = json.loads(request.content)
        message = json.loads(payload["messages"][1]["content"])
        captured.append(message)
        answer = {"answer": f"{field}：{value}。", "source_ids": [message["evidence"][0]["source_id"]]}
        return httpx.Response(200, json={"choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps(answer, ensure_ascii=False)}}
        ]})

    async def complete(request, *, timeout_seconds):
        client = DeepSeekClient(
            base_url="https://provider.invalid", model="offline-test", api_key="fake",
            transport=httpx.MockTransport(reply),
        )
        try:
            return await client.complete(request, timeout_seconds=timeout_seconds)
        finally:
            await client.aclose()

    monkeypatch.setattr(chat_model, "complete", complete)
    body = _ask(chat_employee, _conversation(chat_employee), f"{STORE}的{field}是什么？")
    assert body["kind"] == "answer", body
    assert value in body["text"]
    assert body["sources"][0]["locator"]["row"] == 4
    (message,) = captured
    (evidence,) = message["evidence"]
    assert value in evidence["fields"].values()
    encoded = json.dumps(message, ensure_ascii=False)
    for forbidden in FORBIDDEN_VALUES:
        if forbidden != value:
            assert forbidden not in encoded


def test_zz_tree_identity():
    """记录本次运行实际 import 的 ``mktkb`` 与 ``rag/query.py`` 摘要（跨树对照的自证）。"""

    import hashlib

    query_path = Path(rag_query.__file__).resolve()
    digest = hashlib.sha256(query_path.read_bytes()).hexdigest()
    payload = {"mktkb": str(Path(sys.modules["mktkb"].__file__).resolve()), "query_py": str(query_path), "query_sha256": digest}
    print("TREE " + json.dumps(payload, ensure_ascii=False))
    path = os.environ.get("MKTKB_206B_TREE")
    if path:
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    assert query_path.exists()


# --------------------------------------------------------------------------- #
# 离线：零出站 / 零子进程
# --------------------------------------------------------------------------- #


def test_offline_chain_zero_external_and_zero_subprocess(
    t09_network_guard, no_subprocess, chat_app, chat_admin, chat_employee, chat_model
):
    _dataset(chat_app, chat_admin)
    for question in (
        QUESTION_MIXED_3,
        QUESTION_MIXED_4,
        QUESTION_PHONE_ONLY,
        QUESTION_CONTACT_ONLY,
        QUESTION_CREDENTIAL,
        QUESTION_DUAL_LOCATION_PHONE,
        QUESTION_DUAL_CONTACT_PHONE_ADDRESS,
        QUESTION_LEGACY_MIX,
    ):
        _ask(chat_employee, _conversation(chat_employee), question)
    snapshot = t09_network_guard.snapshot()
    assert snapshot["external"] == [], snapshot["external"]
    assert no_subprocess == [], no_subprocess
