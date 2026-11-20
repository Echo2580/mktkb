"""R2-202A / C29 同形合成复现：跨文档「物品行 + 店家行」在 direct-RAG 枚举轮次的缺口。

全部实体/表头/值均为虚构（青禾店/白鹭店/折叠桌/折叠凳…）；不读 fixtures、题面、私有材料、
真实 case_id、真实期望答案或真实实体值。只走产品链路：上传 → 解析 → 发布 →
``POST /api/v1/conversations/{id}/messages``。

本文件证明三件事：

1. **机制已由 R2-202C 修复**（修前对应 C29 的质量失败码 ``value_hit`` 2→1 与
   ``source_hit`` 2→1）：只点名物品、问「位置 + 合作状态」时，``filters=[item]`` +
   ``enumerate`` 把本轮交给 rag 内核直答；R2-202C 在候选层按唯一物品行反推门店、并入
   同门店店家行（``rag/retrieval.py::_store_join_chunks``），正文与 ``sources`` 因此
   同时覆盖两类值/两份资料，模型仍零调用。修前红态实测见 R2-202A 报告与
   ``test_r2_202c_c29_join_rag.py`` 的同形用例。
2. **R0/C12 的 join 补丁不在这条路上**：同问法即使点名门店（``filters=[item, store]``）
   仍走 rag 直答；R0 的 `_store_join_ids` 只在 legacy 取证路径生效
   （用 R0 形态的问法 + 关闭补丁做敏感性对照，见 ``test_r0_join_...``）。
3. **缺口不是单层**：候选层之外还有三处同类判定（答案侧单角色裁剪、事实实体绑定、
   行文本实体归属）；R2-202C 逐层收口，下面按**修复后**的行为逐层钉住，不再用
   monkeypatch 模拟"提案 hunk"——每层都有自己的正例与 fail-closed 反例。

零出站：模块级 ``t09_network_guard``（仓库既有守卫）+ ``no_subprocess``（本文件自备）。
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

# ``acceptance.support.netguard`` 需要 ``backend/tests`` 在 sys.path 上（``tests/`` 下只有部分
# 目录是包）；这里显式补一次，避免依赖其它测试模块的导入顺序。
_TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))
from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401  (pytest fixture)

from mktkb.documents.lifecycle import get_revision  # noqa: E402
from mktkb.ingestion.worker import run_one_job  # noqa: E402

pytestmark = pytest.mark.usefixtures("t09_network_guard", "no_subprocess")

# --------------------------------------------------------------------------- #
# 合成数据集（虚构）
# --------------------------------------------------------------------------- #

ITEM_DOC = "物品位置台账.xlsx"
STORE_DOC = "合作店家信息.xlsx"
ITEM_HEADERS = ["门店", "物品", "标识", "位置", "数量"]
ITEM_ROWS = [
    ["青禾店", "折叠桌", "P01", "甲区1号架", "4"],
    ["青禾店", "折叠椅", "P02", "甲区2号架", "6"],
    ["白鹭店", "折叠凳", "P03", "乙区1号架", "9"],
]
STORE_HEADERS = ["标识", "店家", "联系人", "合作状态"]
STORE_ROWS = [
    ["S01", "青禾店", "合成对接人·甲", "合作中"],
    ["S02", "白鹭店", "合成对接人·乙", "暂停合作"],
]

STORE = "青禾店"
ITEM = "折叠桌"
ITEM_LOCATION = "甲区1号架"
STORE_STATUS = "合作中"
ITEM_DOC_TITLE = "物品位置台账"
STORE_DOC_TITLE = "合作店家信息"

#: A：只点名物品，问物品字段 + 店家级字段（C29 历史 intent 形态：filters=[item]）。
QUESTION_A = "折叠桌的位置在哪里，合作状态分别是什么？"
#: B：同时点名门店与物品（R0/C12 join 的触发形态）。
QUESTION_B = "青禾店的折叠桌放在哪个位置，合作状态分别是什么？"
#: B-legacy：同 B 但去掉枚举词 → 走 legacy 取证路径（R0 补丁的生效面）。
QUESTION_B_LEGACY = "青禾店的折叠桌放在哪个位置，合作状态如何？"
B_LEGACY_ANSWER = f"根据资料：{STORE}的{ITEM}位置：{ITEM_LOCATION}；合作状态：{STORE_STATUS}。"
#: C1：只问物品位置（不得多出店家级值/来源）。与 A 同路径（record + enumerate）。
QUESTION_C1 = "折叠桌分别放在哪个位置？"
#: C2：只问店家属性（目标不得被改写成物品）。
QUESTION_C2 = f"{STORE}的合作状态是什么？"
#: C3（安全反例）：物品 + 电话仍在检索/模型之前整体拒答。
QUESTION_PHONE = f"{STORE}的{ITEM}电话是多少？"


#: 只想看计数时用的行类型（合成值，可写）。
ITEM_ROW_MARK = "item"
STORE_ROW_MARK = "store"


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
# 夹具装配（真实上传/解析/发布）
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


def _dataset(
    app,
    admin: SimpleNamespace,
    *,
    item_rows: list[list[object]] | None = None,
    store_rows: list[list[object]] | None = None,
    store_headers: list[str] | None = None,
) -> None:
    for name, headers, rows, title in (
        (ITEM_DOC, ITEM_HEADERS, item_rows or ITEM_ROWS, ITEM_DOC_TITLE),
        (STORE_DOC, store_headers or STORE_HEADERS, store_rows or STORE_ROWS, STORE_DOC_TITLE),
    ):
        path = _xlsx(Path(app.state.settings.data_dir) / name, headers, rows, title)
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
    """产品同一入口的查询计划（``QaEngine.prepare``）：只读 filters/roles 的**键**。"""

    qa = app.state.qa
    qa.ensure_ready()
    me = session.client.get("/api/v1/auth/me").json()
    return qa.prepare(question, str(me["user"]["id"]), conversation_id)[1]


def _source_docs(body: dict) -> list[str]:
    return [str(item.get("document_name") or "") for item in body.get("sources") or []]


def _ask_info(app, session: SimpleNamespace, question: str) -> dict:
    """一次真实产品链路问答 + 计划形态摘要（只计数/布尔/合成值）。"""

    conversation_id = _conversation(session)
    plan = _plan(app, session, conversation_id, question)
    body = _ask(session, conversation_id, question)
    return {
        "body": body,
        "kind": body.get("kind"),
        "text": body.get("text") or "",
        "sources": _source_docs(body),
        "mode": str(getattr(plan, "mode", "")),
        "enumerate": bool(getattr(plan, "enumerate", False)),
        "filters": sorted(str(key) for key in dict(getattr(plan, "filters", {}) or {})),
        "filter_values": dict(getattr(plan, "filters", {}) or {}),
        "field_role": getattr(plan, "field_role", None),
        "field_roles": tuple(getattr(plan, "field_roles", ()) or ()),
        "state_stores": tuple(getattr(plan.state, "stores", ()) or ()),
    }



# --------------------------------------------------------------------------- #
# 1) 机制复现（R2-202C 修后形态）：A / B 在 direct-RAG 枚举轮次覆盖两类值/两条来源
# --------------------------------------------------------------------------- #


def test_a_item_only_cross_table_question_now_covers_both_sources(
    chat_app, chat_admin, chat_employee, chat_model
):
    """A（C29 历史形态 filters=[item]）：R2-202C 后两类值/两条来源同时到齐。

    修前实测（红）：kind=answer；正文含位置值、不含合作状态值；sources=1（物品文档）；
    模型 0 调用。修后实测（绿）：正文含位置值与合作状态值；sources=2（两份资料）；
    计划 filters=[item]、enumerate=True、请求角色含 location 与 status；模型仍 0 调用。
    """

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_A)

    assert info["kind"] == "answer", info
    assert info["mode"] == "record", info
    assert info["enumerate"] is True, info
    assert info["filters"] == ["item"], info
    assert set(info["field_roles"]) == {"location", "status"}, info
    assert info["state_stores"] == (), info
    # 值：两级值都在（C29 的 value_hit 2/2）。
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS in info["text"], info
    # 来源：两条、分别来自两份资料（C29 的 source_hit 2/2）。
    assert sorted(set(info["sources"])) == sorted({ITEM_DOC, STORE_DOC}), info
    assert len(info["sources"]) == 2, info
    # 直答路径不调用模型（这也是 retrieval_observed 缺失的同一条路径）。
    assert chat_model.calls == [], chat_model.calls


def test_b_store_plus_item_enumerate_turn_also_joins(
    chat_app, chat_admin, chat_employee, chat_model
):
    """B（点名门店 + 物品）：枚举轮次由内核直答，R2-202C 后同样覆盖两类值/两条来源。

    这条同时界定 R0 补丁的作用面：``filters`` 里已有 store，但取值仍由 rag 内核完成
    （R0 的 ``_store_join_ids`` 只在 legacy 取证路径生效，见 ``test_r0_join_...``）。
    """

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_B)

    assert info["filters"] == ["item", "store"], info
    assert info["enumerate"] is True, info
    assert info["kind"] == "answer", info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS in info["text"], info
    assert sorted(set(info["sources"])) == sorted({ITEM_DOC, STORE_DOC}), info
    assert len(info["sources"]) == 2, info
    assert chat_model.calls == [], chat_model.calls


def test_first_loss_layer_is_the_rag_candidate_filter(chat_app, chat_admin, chat_employee):
    """首次丢失层 = 候选层（`rag/retrieval.py::_base_stmt` 的逐块等值 AND）。

    合成语料 5 个记录块：2 个店家行（青禾店/白鹭店）+ 3 个物品行。A 的计划只带
    ``item`` 一个过滤键 → 记录面基础候选 1 条（物品行），青禾店家行（合作状态的唯一
    来源）被 ``$.item`` 判定排除；R2-202C 的联结在 ``_exact_recall`` 里按唯一物品行的
    门店再取一次店家行（同一 ``_base_stmt`` 上界），因此精确面是"物品行 + 联结店家行"，
    而记录面基础候选仍是 1 条——两个口径的差额就是本层修复点。
    """

    from sqlalchemy import select

    from mktkb.rag import retrieval as rag_retrieval
    from mktkb.rag.models import RagChunk

    _dataset(chat_app, chat_admin)
    index = chat_app.state.qa.index()
    with index.session() as session:
        rows = session.execute(select(RagChunk)).scalars().all()
    store_rows = [row for row in rows if row.entity_type == STORE_ROW_MARK]
    item_rows = [row for row in rows if row.entity_type == ITEM_ROW_MARK]
    assert len(rows) == 5, len(rows)
    assert len(store_rows) == 2, len(store_rows)
    assert len(item_rows) == 3, len(item_rows)

    conversation_id = _conversation(chat_employee)
    plan = _plan(chat_app, chat_employee, conversation_id, QUESTION_A)
    assert plan.filters == {"item": ITEM}
    with index.session() as session:
        base = rag_retrieval._load(
            session, rag_retrieval._base_stmt(session, plan, require_record=True)
        )
        diagnostics: dict = {}
        exact = rag_retrieval._exact_recall(session, index, plan, diagnostics)
    # 记录面基础候选仍只 1 条：``$.item`` 等值过滤把店家行排除（本层确实存在）。
    assert [chunk.entity_type for chunk in base] == [ITEM_ROW_MARK], base
    # 精确面 = 物品行 + 同门店店家行，且联结来源在 diagnostics 里可审计。
    assert [chunk.entity_type for chunk in exact] == [ITEM_ROW_MARK, STORE_ROW_MARK], exact
    assert diagnostics["store_join"]["store"] == STORE, diagnostics["store_join"]
    assert diagnostics["store_join"]["chunk_ids"] == [exact[-1].chunk_id], diagnostics
    # 店家行确实在语料里（不是"资料里没有"），只是被 item 等值排除后由联结补回。
    assert any(
        (row.filters_norm or {}).get("store") == STORE for row in store_rows
    ), [row.filters_norm for row in store_rows]


# --------------------------------------------------------------------------- #
# 2) 后续三层（R2-202C 修后行为逐层钉住，不再模拟"提案 hunk"）
# --------------------------------------------------------------------------- #


def test_second_loss_is_answer_side_single_role_filter(
    chat_app, chat_admin, chat_employee, chat_model
):
    """第 2 层（答案侧单角色裁剪）：修后不再丢联结行 —— 页码两条、正文两行。

    修前：只补候选层时"共 2 条"但"显示 1 条"（``exact`` 按 ``plan.field_role`` 单角色
    裁剪，店家行没有 location 角色被丢掉）。修后：联结行按检索层写入的
    ``result.diagnostics["store_join"]`` 显式身份保留，故"显示 2 条"。
    """

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_A)

    assert info["kind"] == "answer", info
    assert "共 2 条" in info["text"], info  # 候选层并入
    assert "显示 2 条" in info["text"], info  # 答案侧不再按单角色裁剪
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS in info["text"], info
    assert chat_model.calls == [], chat_model.calls


def test_third_loss_is_fact_entity_binding(
    chat_app, chat_admin, chat_employee, chat_model, monkeypatch
):
    """第 3 层（事实实体绑定）：只在"联结门店与该行门店逐字相等"时放行。

    `rag/facts.py` 的实体过滤比对仍逐键执行；唯一例外是本轮显式联结进来的店家行
    （``FactValidator.joined_store`` == 该行门店值）。这里用"把联结门店换成另一家店"
    的负例证明该例外没有退化成"忽略过滤"。
    """

    from mktkb.rag import retrieval as rag_retrieval

    _dataset(chat_app, chat_admin)
    green = _ask_info(chat_app, chat_employee, QUESTION_A)
    assert green["kind"] == "answer", green
    assert STORE_STATUS in green["text"], green

    real = rag_retrieval._store_join_chunks

    def mismatched(session, plan):
        store_value, rows = real(session, plan)
        if not rows:
            return store_value, rows
        return "白鹭店", rows  # 门店值与店家行不一致：显式绑定不成立

    monkeypatch.setattr(rag_retrieval, "_store_join_chunks", mismatched)
    red = _ask_info(chat_app, chat_employee, QUESTION_A)

    assert red["kind"] == "not_found", red
    assert "事实来源不满足问题实体条件" in red["text"], red
    assert red["sources"] == [], red
    assert chat_model.calls == [], chat_model.calls


def test_fourth_loss_is_line_entity_attribution(
    chat_app, chat_admin, chat_employee, chat_model
):
    """第 4 层（行内实体归属）：修后靠"分实体分行 + 记录指纹"绑定，不放宽任何匹配。

    `_assert_entity_value_binding` 的"同一行混入多个实体"检查原样保留：联结轮次里每行
    都带 ``（记录 xxxxxxxx）`` 指纹，归属由记录身份决定（与 ``_record_line`` 同一口径），
    所以物品行标签虽含店名，也不会被判成"同一行混了两个实体"。
    """

    import re

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_A)

    assert info["kind"] == "answer", info
    lines = [line for line in info["text"].splitlines() if line.startswith("- ")]
    assert len(lines) == 2, lines
    refs = [re.search(r"（记录 ([0-9a-f]{8})）", line) for line in lines]
    assert all(match is not None for match in refs), lines
    assert len({match.group(1) for match in refs}) == 2, lines
    item_line = next(line for line in lines if ITEM_LOCATION in line)
    store_line = next(line for line in lines if STORE_STATUS in line)
    assert item_line != store_line, lines
    assert STORE_STATUS not in item_line, item_line
    assert ITEM_LOCATION not in store_line, store_line


# --------------------------------------------------------------------------- #
# 3) 反例（正常 + 相邻安全）：不得多带、不得改写目标、不得放宽安全
# --------------------------------------------------------------------------- #


def test_c1_single_item_field_does_not_carry_store_value(
    chat_app, chat_admin, chat_employee, chat_model
):
    """C1（只问位置，提案全开）：仍只有物品行一条来源，不出现店家级值/来源。"""

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_C1)

    assert info["kind"] == "answer", info
    assert info["enumerate"] is True, info
    assert info["field_roles"] == ("location",), info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert info["sources"] == [ITEM_DOC], info
    assert "合作状态" not in info["text"], info
    assert chat_model.calls == [], chat_model.calls


def test_c2_store_only_question_keeps_store_target(
    chat_app, chat_admin, chat_employee, chat_model
):
    """C2（只问店家属性，提案全开）：目标仍是店家行，不被改写成物品、不多带位置。"""

    _dataset(chat_app, chat_admin)
    info = _ask_info(chat_app, chat_employee, QUESTION_C2)

    assert info["kind"] == "answer", info
    assert info["filters"] == ["store"], info
    assert STORE_STATUS in info["text"], info
    assert ITEM_LOCATION not in info["text"], info
    assert info["sources"] == [STORE_DOC], info
    evidence = chat_model.calls[0]["evidence"]
    assert len(evidence) == 1, evidence
    assert "合作状态" in evidence[0]["fields"], evidence
    assert "位置" not in evidence[0]["fields"], evidence


def test_c3_item_plus_phone_is_still_refused_before_model(
    chat_app, chat_admin, chat_employee, chat_model
):
    """C3（相邻安全反例）：物品 + 电话仍在检索/模型之前整体拒答（安全面不放宽）。"""

    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)
    body = _ask(chat_employee, conversation_id, QUESTION_PHONE)

    assert body["kind"] == "not_found", body
    assert body["sources"] == [], body
    assert chat_model.calls == [], "安全拒答不得调用模型"


def test_c4_multiple_item_targets_do_not_join(
    chat_app, chat_admin, chat_employee, chat_model
):
    """C4（正常反例）：同名物品落在两家门店 → 门店不唯一 → 不 join（fail-closed）。"""

    _dataset(
        chat_app,
        chat_admin,
        item_rows=[
            ["青禾店", ITEM, "P01", ITEM_LOCATION, "4"],
            ["白鹭店", ITEM, "P09", "乙区9号架", "2"],
            ["青禾店", "折叠椅", "P02", "甲区2号架", "6"],
        ],
    )
    info = _ask_info(chat_app, chat_employee, QUESTION_A)

    assert info["kind"] == "answer", info
    # 两个物品目标都在（既有枚举口径），但没有任何店家行被并入。
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert set(info["sources"]) == {ITEM_DOC}, info


def test_c5_expired_store_row_is_not_joined(
    chat_app, chat_admin, chat_employee, chat_model
):
    """C5（正常反例）：店家行已过有效期 → 不并入（业务日窗口同样作用于 join 行）。"""

    _dataset(
        chat_app,
        chat_admin,
        store_rows=[
            ["S01", STORE, "合成对接人·甲", STORE_STATUS, "2026-10-31"],
        ],
        store_headers=[*STORE_HEADERS, "失效日期"],
    )
    info = _ask_info(
        chat_app, chat_employee, "截至2026-11-01，折叠桌的位置在哪里，合作状态分别是什么？"
    )

    assert info["kind"] == "answer", info
    assert ITEM_LOCATION in info["text"], info
    assert STORE_STATUS not in info["text"], info
    assert info["sources"] == [ITEM_DOC], info


# --------------------------------------------------------------------------- #
# 5) 零出站：本文件全部用例都在模块级守卫下；这里再显式断言一次
# --------------------------------------------------------------------------- #

def test_offline_chain_has_zero_external_network_and_no_subprocess(
    t09_network_guard, no_subprocess, chat_app, chat_admin, chat_employee, chat_model
):
    """合成链路零出站、零子进程：跑完 A/B/C1/C2 后审计守卫账本。"""

    _dataset(chat_app, chat_admin)
    for question in (QUESTION_A, QUESTION_B, QUESTION_C1, QUESTION_C2):
        _ask(chat_employee, _conversation(chat_employee), question)

    snapshot = t09_network_guard.snapshot()
    assert snapshot["external"] == [], snapshot["external"]
    assert no_subprocess == [], no_subprocess



# --------------------------------------------------------------------------- #
# 4) R0/C12 补丁的敏感性对照（legacy 形态）
# --------------------------------------------------------------------------- #


def test_r0_join_is_the_switch_on_legacy_shape(
    chat_app, chat_admin, chat_employee, chat_model, monkeypatch
):
    """R0 形态（无枚举词 → legacy 取证）：补丁开着两类值/两条来源都在；关掉即转红。

    这条既是 R0 补丁仍生效的证明，也是"A 的缺口不是 R0 补丁能覆盖的"的对照：
    同一份数据、同样两个字段，只有走 legacy 路径时补丁才起作用。
    """

    from mktkb.retrieval import service as retrieval_service

    _dataset(chat_app, chat_admin)
    conversation_id = _conversation(chat_employee)
    chat_model.answer_text = B_LEGACY_ANSWER
    body = _ask(chat_employee, conversation_id, QUESTION_B_LEGACY)

    assert body["kind"] == "answer", body
    assert ITEM_LOCATION in body["text"], body["text"]
    assert STORE_STATUS in body["text"], body["text"]
    assert set(_source_docs(body)) == {ITEM_DOC, STORE_DOC}, body["sources"]
    evidence = chat_model.calls[0]["evidence"]
    assert any("位置" in item["fields"] for item in evidence), evidence
    assert any("合作状态" in item["fields"] for item in evidence), evidence

    # 敏感性对照：只关掉 R0 的并集开关，其余不变 → 店家行消失，回答无法背书。
    monkeypatch.setattr(retrieval_service, "_store_join_ids", lambda db, intent: set())
    conversation_id = _conversation(chat_employee)
    chat_model.calls.clear()
    chat_model.answer_text = B_LEGACY_ANSWER
    red = _ask(chat_employee, conversation_id, QUESTION_B_LEGACY)

    assert red["kind"] == "service_error", red
    evidence = chat_model.calls[0]["evidence"]
    assert len(evidence) == 1, evidence
    assert "合作状态" not in evidence[0]["fields"], evidence
