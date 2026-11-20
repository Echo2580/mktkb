"""R2-206A / C29 contact 闸门过度拒答最小修复（合成件）。

机制出处（已确证，不重做）：``rag/query.py`` 的规划层早退点
（``SECURITY_RESTRICTED_CONTACT``，``parse_query`` 内）把**整题**判成安全拒答：

    if not is_policy_question(question) and (
        ((bool(item_hits) or identifier is not None) and set(field_roles) & REFUSAL_CONTACT_ROLES)
        or is_contract_credential_question(question)
    ):
        return QueryPlan(..., reason="SECURITY_RESTRICTED_CONTACT")

C29 的题面被抽出 ``field_roles = (location, phone, status)`` ⇒ 命中 ``phone`` ⇒ 整题拒答
（``kind=not_found``、facts=0、``source=refusal``、值 0/2、来源 0/2）。冻结标签
``should_refuse=false`` / ``expected_kind=answer`` / 2 个文本值 / 数字期望 0 ⇒ 期望答案
**不含电话值**：``phone`` 是被顺带抽到的角色（干扰），不是本问要答的字段。

本文件只走产品链路（上传 → 解析 → 发布 → ``POST /conversations/{id}/messages``），
全部实体/值虚构（青禾店 / 白鹭店 / 折叠桌 / 折叠凳），不读 fixtures、题面、真实 case_id
或真实期望值。覆盖：

1. **G1（红 → 绿）**：物品 + 位置 + 合作状态 + 电话（三/四角色混合）→ 不再整题拒答，
   正文含位置值与合作状态值、**不含任何电话/地址值**，``sources`` ≥1。
2. **G2（不变）**：物品 + 只问电话 → 仍整题拒答，``kind/text/sources`` 与改前逐字节相同。
3. **G3**：物品 + 只问 contact（对接人）→ 返回同店对接人及店家来源，正文和模型载荷无电话、地址。
4. **G4（不变）**：凭据族（合同/结算账号）→ 仍整题拒答，逐字节相同。
5. **敏感性**：把 ``REFUSAL_CONTACT_ROLES`` 在运行时扩到本轮全部角色 ⇒ 混合形态重新落回
   改前早退（restricted 之外没有可答角色）⇒ G1 回红；撤销即绿。
6. **零出站**：``t09_network_guard`` + 本文件自备 ``no_subprocess``，并显式断言
   ``external == []``、子进程 0 次。

「改前」基线由本文件的 ``BEFORE`` 常量冻结：它取自**未打补丁**的工作树在同一 app 装配下
实测到的 ``(kind, text, sources)``（见 ``evidence/10-attempt2/R2-206A-REPORT.md``）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

# ``acceptance.support.netguard`` 需要 ``backend/tests`` 在 sys.path 上；显式补一次，
# 避免依赖其它测试模块的导入顺序。
_TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))
from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402
from mktkb.rag import query as q  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard", "no_subprocess")

# --------------------------------------------------------------------------- #
# 合成数据集（虚构）
# --------------------------------------------------------------------------- #

ITEM_DOC = "物品位置台账.xlsx"
STORE_DOC = "合作店家信息.xlsx"
ITEM_DOC_TITLE = "物品位置台账"
STORE_DOC_TITLE = "合作店家信息"
ITEM_HEADERS = ["门店", "物品", "标识", "位置", "数量"]
ITEM_ROWS = [
    ["青禾店", "折叠桌", "P01", "甲区1号架", "4"],
    ["白鹭店", "折叠凳", "P03", "乙区1号架", "9"],
]
#: 店家行同时带 contact / phone / address / status：混合题的四类角色都有真实单元格可渲染。
STORE_HEADERS = ["标识", "店家", "联系人", "电话", "地址", "合作状态"]
STORE_ROWS = [
    ["S01", "青禾店", "合成对接人·甲", "010-00000001", "示例路18号", "合作中"],
    ["S02", "白鹭店", "合成对接人·乙", "010-00000002", "示例路26号", "暂停合作"],
]

STORE = "青禾店"
ITEM = "折叠桌"
ITEM_LOCATION = "甲区1号架"
STORE_STATUS = "合作中"
CONTACT_VALUE = "合成对接人·甲"
PHONE_VALUE = "010-00000001"
ADDRESS_VALUE = "示例路18号"

#: G1（三角色混合：物品 + 位置 + 合作状态 + 电话）。C29 的 ``field_roles`` 同形
#: （``location`` / ``phone`` / ``status``）：受限角色是顺带抽取的干扰，不是本问要答的字段。
QUESTION_MIXED_3 = f"{STORE}的{ITEM}放在哪个位置，合作状态分别是什么，电话是多少？"
#: G1b（四角色混合：再加地址）。
QUESTION_MIXED_4 = f"{STORE}的{ITEM}放在哪个位置，合作状态分别是什么，电话和地址是多少？"
#: G2（不变）：物品 + 只问电话。R0/C12 冻结拒答面。
QUESTION_PHONE_ONLY = f"{STORE}的{ITEM}电话是多少？"
#: G3：物品 + 只问 contact（对接人）。R0/C12 合法放行面。
QUESTION_CONTACT_ONLY = f"{STORE}的{ITEM}由谁对接？"
#: G4（不变）：凭据族（R1/102c M5 同形）。
QUESTION_CREDENTIAL = f"{STORE}的{ITEM}放在哪，由谁对接，完整合同和结算账号是多少？"

#: 改前基线（**未打补丁**的工作树，同一 app 装配、同一数据集实测）：``kind``/``text``/
#: ``sources`` 三元组逐字节冻结。取自本文件在 ``rag/query.py`` 未改动时的红态运行输出
#: （``evidence/10-attempt2/R2-206A-REPORT.md`` §3 有原文），因此“改前/改后”对照不是
#: 同版本自比。
REFUSAL_TEXT = (
    "该请求要把物品记录与店家联系人、电话或地址等个人联系信息合并提供，属于受限个人信息范围，"
    "不能据此作答；这不是资料中没有答案，也不代表该信息未被登记；请改为只询问物品位置等"
    "非个人联系信息后重新提问。"
)
BEFORE: dict[str, dict] = {
    "g2": {"kind": "not_found", "text": REFUSAL_TEXT, "sources": []},
    "g4": {"kind": "not_found", "text": REFUSAL_TEXT, "sources": []},
}

#: 混合题正文里一律不得出现的值（电话/地址 + 未请求的联系人姓名）。
FORBIDDEN_VALUES = (PHONE_VALUE, ADDRESS_VALUE, CONTACT_VALUE)


# --------------------------------------------------------------------------- #
# 夹具：零子进程
# --------------------------------------------------------------------------- #


@pytest.fixture
def no_subprocess(monkeypatch):
    """合成链路不得启动子进程：拦截 ``subprocess`` 并逐个断言 0 次。

    ``t09_network_guard`` 只覆盖本进程内的 socket/httpx 出站；子进程会绕过它，
    所以这里额外封死 ``subprocess.Popen``/``run``（调用即失败，计数为 0）。
    """

    calls: list[tuple] = []

    def _blocked(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append((args, tuple(sorted(kwargs))))
        raise AssertionError("合成链路不得启动子进程")

    monkeypatch.setattr(subprocess, "Popen", _blocked)
    monkeypatch.setattr(subprocess, "run", _blocked)
    yield calls
    assert calls == [], calls


# --------------------------------------------------------------------------- #
# 夹具装配（真实上传 / 解析 / 发布）
# --------------------------------------------------------------------------- #


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


def _plan(app, session: SimpleNamespace, conversation_id: str, question: str):
    """产品同一入口的查询计划（``QaEngine.prepare``）：只读键/角色/原因码。"""

    qa = app.state.qa
    qa.ensure_ready()
    me = session.client.get("/api/v1/auth/me").json()
    return qa.prepare(question, str(me["user"]["id"]), conversation_id)[1]


def _shape(body: dict) -> dict:
    """“逐字节”对照面：只有 ``kind`` / ``text`` / ``sources``（不含时间戳等易变字段）。"""

    return {
        "kind": body.get("kind"),
        "text": body.get("text") or "",
        "sources": [str(item.get("document_name") or "") for item in body.get("sources") or []],
    }


def _ask_info(app, session: SimpleNamespace, question: str) -> dict:
    conversation_id = _conversation(session)
    plan = _plan(app, session, conversation_id, question)
    body = _ask(session, conversation_id, question)
    return {
        "body": body,
        "shape": _shape(body),
        "kind": body.get("kind"),
        "text": body.get("text") or "",
        "sources": _shape(body)["sources"],
        "reason": getattr(plan, "reason", None),
        "plan_field_roles": tuple(getattr(plan, "field_roles", ()) or ()),
        "state_field_roles": tuple(getattr(plan.state, "field_roles", ()) or ()),
        "mode": str(getattr(plan, "mode", "")),
        "enumerate": bool(getattr(plan, "enumerate", False)),
        "filters": sorted(str(key) for key in dict(getattr(plan, "filters", {}) or {})),
    }


def _assert_byte_identical(name: str, info: dict) -> None:
    observed = info["shape"]
    assert BEFORE.get(name) == observed, (
        f"{name}: 改前/改后不一致\n改前={json.dumps(BEFORE.get(name), ensure_ascii=False)}"
        f"\n改后={json.dumps(observed, ensure_ascii=False)}"
    )


def _forced_early_return_shape(app, session: SimpleNamespace, question: str) -> dict:
    """改前等价控制：运行时把 ``REFUSAL_CONTACT_ROLES`` 扩到本轮全部角色。

    这样 ``restricted - others`` 恒为空集合 ⇒ ``parse_query`` 走改前的整题早退分支，
    于是能在**同一次运行、同一 app** 里对照“改前/改后”的用户可见字节（kind/text/sources）。
    """

    patcher = pytest.MonkeyPatch()
    try:
        patcher.setattr(
            q, "REFUSAL_CONTACT_ROLES", frozenset({"phone", "address", "location", "status"})
        )
        return _ask_info(app, session, question)["shape"]
    finally:
        patcher.undo()


# --------------------------------------------------------------------------- #
# 1) G1：混合角色不再整题拒答（改前红：整题 SECURITY_RESTRICTED_CONTACT）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("question", [QUESTION_MIXED_3, QUESTION_MIXED_4])
def test_g1_mixed_roles_are_answered_without_contact_values(
    chat_app, chat_admin, chat_employee, chat_model, question
):
    """物品 + 位置 + 合作状态 + 电话/地址 → ``kind=answer``、两类值都在、无电话/地址值。"""

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, question)

    # 计划层：早退点不再把整题判成受限；受限角色不进 field_roles / requested_fields。
    assert info["reason"] is None, info
    assert info["plan_field_roles"] == ("location", "status"), info
    assert info["state_field_roles"] == ("location", "status"), info
    assert info["mode"] == "record", info
    assert info["enumerate"] is True, info
    # 答案层：正常作答，两类值都在，来源覆盖两份资料。
    assert info["kind"] == "answer", info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS in info["text"], info
    assert sorted(set(info["sources"])) == sorted({ITEM_DOC, STORE_DOC}), info
    assert len(info["sources"]) >= 1, info
    # 安全面：电话/地址/未请求的联系人值一个都不许进正文。
    for value in FORBIDDEN_VALUES:
        assert value not in info["text"], (value, info["text"])
    # 仍是结构化直答：模型 0 调用。
    assert chat_model.calls == [], chat_model.calls


@pytest.mark.parametrize("question", [QUESTION_MIXED_3, QUESTION_MIXED_4])
def test_g1_facts_and_citations_exclude_restricted_roles(
    chat_app, chat_admin, chat_employee, chat_model, question
):
    """证据面：facts 只含 location/status；引用覆盖两份资料；电话/地址值不在 facts。"""

    _dataset(chat_app, chat_admin)
    qa = chat_app.state.qa
    qa.ensure_ready()
    me = chat_employee.client.get("/api/v1/auth/me").json()
    answer = qa.answer(question, str(me["user"]["id"]), _conversation(chat_employee))

    assert answer.kind == "answer", (answer.kind, answer.reason, answer.text)
    roles = {(fact.field_role, fact.value) for fact in answer.facts}
    assert ("location", ITEM_LOCATION) in roles, roles
    assert ("status", STORE_STATUS) in roles, roles
    assert {role for role, _value in roles} == {"location", "status"}, roles
    fact_values = {value for _role, value in roles}
    assert fact_values.isdisjoint(FORBIDDEN_VALUES), fact_values
    assert len({citation.doc_id for citation in answer.citations}) >= 1, answer.citations
    assert chat_model.calls == [], chat_model.calls


def test_g1_non_enumerate_mixed_shape_is_unchanged_fail_closed(
    chat_app, chat_admin, chat_employee, chat_model
):
    """非枚举混合形态：规划层不再早退，但**产品层旧有的第二道闸门**仍整题拒答。

    ``conversations/intent.py`` 对“物品/标识 + 联系人/电话/地址字段”同样整体拒答
    （``RESTRICTED_CONTACT_FIELDS``，本批不在可改面内）。于是非枚举形态（legacy 取证/模型
    路径）保持拒答：与改前（规划层早退）**逐字节相同**，且电话/地址值不进正文。
    这里的“改前”用运行时把 ``REFUSAL_CONTACT_ROLES`` 扩到本轮全部角色来等价复现（同一 app、
    同一题），而不是同版本自比。
    """

    _dataset(chat_app, chat_admin)
    question = f"{STORE}的{ITEM}放在哪个位置，合作状态如何，电话是多少？"

    patcher = pytest.MonkeyPatch()
    try:
        patcher.setattr(
            q, "REFUSAL_CONTACT_ROLES", frozenset({"phone", "address", "location", "status"})
        )
        before = _ask_info(chat_app, chat_employee, question)  # 改前等价：规划层早退
    finally:
        patcher.undo()
    after = _ask_info(chat_app, chat_employee, question)

    # 规划层：本批之后不再早退（角色里已没有 phone）；拒答由下游旧闸门承担。
    assert after["reason"] is None, after
    assert after["plan_field_roles"] == ("location", "status"), after
    assert after["state_field_roles"] == ("location", "status"), after
    # 但用户可见结果与改前逐字节相同：仍是安全拒答。
    assert after["shape"] == before["shape"], (before["shape"], after["shape"])
    assert after["kind"] == "not_found", after
    assert after["sources"] == [], after
    for value in FORBIDDEN_VALUES:
        assert value not in after["text"], (value, after["text"])
    assert chat_model.calls == [], "拒答在模型之前收口"


# --------------------------------------------------------------------------- #
# 2) G2 / G4 对照改前快照，G3 验证现行放行行为
# --------------------------------------------------------------------------- #


def test_g2_item_plus_phone_only_is_still_refused(chat_app, chat_admin, chat_employee, chat_model):
    """G2：物品 + 只问电话 → 早退点原样拒答（不改一字）。"""

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_PHONE_ONLY)

    assert info["reason"] == "SECURITY_RESTRICTED_CONTACT", info
    assert info["plan_field_roles"] == (), info
    assert info["state_field_roles"] == ("phone",), info
    assert info["kind"] == "not_found", info
    assert info["sources"] == [], info
    assert PHONE_VALUE not in info["text"], info
    assert chat_model.calls == [], "安全拒答不得调用模型"
    _assert_byte_identical("g2", info)
    # 同 app 对照（改前等价）：把受限集扩到本轮全部角色 ⇒ 规划层走原早退 ⇒ 用户可见结果全等。
    assert _forced_early_return_shape(chat_app, chat_employee, QUESTION_PHONE_ONLY) == info["shape"]


def test_g3_item_plus_contact_only_is_still_answered(chat_app, chat_admin, chat_employee, chat_model):
    """G3：只问物品对接人时，应取得同店对接人。旧快照只回显物品行，已随 C12 修复退役。"""

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_CONTACT_ONLY)

    assert info["reason"] is None, info
    assert info["plan_field_roles"] == ("contact",), info
    assert info["kind"] == "answer", info
    assert info["sources"] == [STORE_DOC], info
    assert CONTACT_VALUE in info["text"], info
    assert chat_model.calls, "放行面必须走到模型作答路径"
    payload = json.dumps(chat_model.calls, ensure_ascii=False)
    for row in STORE_ROWS:
        for value in row[3:5]:
            assert value not in info["text"]
            assert value not in payload


def test_g4_credential_family_is_still_refused(chat_app, chat_admin, chat_employee, chat_model):
    """G4：凭据族（合同/结算账号）→ 始终整题拒答（R1/102c），逐字节相同。"""

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_CREDENTIAL)

    assert info["reason"] == "SECURITY_RESTRICTED_CONTACT", info
    assert info["kind"] == "not_found", info
    assert info["sources"] == [], info
    for value in (ITEM_LOCATION, STORE_STATUS, *FORBIDDEN_VALUES):
        assert value not in info["text"], (value, info["text"])
    assert chat_model.calls == [], "安全拒答不得调用模型"
    _assert_byte_identical("g4", info)
    # 同 app 对照（改前等价）：强制规划层原早退 ⇒ 用户可见结果全等。
    assert _forced_early_return_shape(chat_app, chat_employee, QUESTION_CREDENTIAL) == info["shape"]


# --------------------------------------------------------------------------- #
# 3) 敏感性：把受限角色扩到本轮全部角色 ⇒ 混合形态回落到改前早退 ⇒ G1 回红
# --------------------------------------------------------------------------- #


def test_g1_sensitivity_forcing_original_early_return_restores_red(
    chat_app, chat_admin, chat_employee, chat_model
):
    """``restricted - others`` 判定恒走原早退 ⇒ G1 回红；撤销补丁即绿（同一 app、同一题）。"""

    _dataset(chat_app, chat_admin)
    patcher = pytest.MonkeyPatch()
    try:
        # 让本轮全部角色都落进受限集：restricted 之外没有可答角色 ⇒ 原早退条件成立。
        patcher.setattr(
            q, "REFUSAL_CONTACT_ROLES", frozenset({"phone", "address", "location", "status"})
        )
        red = _ask_info(chat_app, chat_employee, QUESTION_MIXED_3)
    finally:
        patcher.undo()

    assert red["reason"] == "SECURITY_RESTRICTED_CONTACT", red
    assert red["kind"] == "not_found", red
    assert red["sources"] == [], red
    assert red["text"] == _shape({"kind": "not_found", "text": red["text"]})["text"]
    for value in (ITEM_LOCATION, STORE_STATUS):
        assert value not in red["text"], (value, red["text"])
    assert chat_model.calls == [], "敏感性对照组不得调用模型"

    green = _ask_info(chat_app, chat_employee, QUESTION_MIXED_3)
    assert green["reason"] is None, green
    assert green["kind"] == "answer", green
    assert ITEM_LOCATION in green["text"] and STORE_STATUS in green["text"], green


# --------------------------------------------------------------------------- #
# 4) 零出站 / 零子进程：本文件全部用例都在模块级守卫下；这里再显式断言一次
# --------------------------------------------------------------------------- #


def test_offline_chain_has_zero_external_network_and_no_subprocess(
    t09_network_guard, no_subprocess, chat_app, chat_admin, chat_employee, chat_model
):
    """合成链路零出站、零子进程：跑完 G1—G4 后审计守卫账本。"""

    _dataset(chat_app, chat_admin)
    for question in (
        QUESTION_MIXED_3,
        QUESTION_MIXED_4,
        QUESTION_PHONE_ONLY,
        QUESTION_CONTACT_ONLY,
        QUESTION_CREDENTIAL,
    ):
        _ask(chat_employee, _conversation(chat_employee), question)

    snapshot = t09_network_guard.snapshot()
    assert snapshot["external"] == [], snapshot["external"]
    assert no_subprocess == [], no_subprocess
