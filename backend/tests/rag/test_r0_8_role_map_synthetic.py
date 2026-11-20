"""R0 第四轮：用**投影出来的固定码形状**做红→绿（去身份化合成件，无 case 特判）。

投影来源：``docs/reports/.../r0-repair-external-20261116/evidence/08-role-map/role-map.json``
（``work/r0_role_map.py`` 产出，只含固定角色码/整数/布尔/sha256）。投影结论：

- C21：``facts=1, expected=1, missing=1``，被引行**字段角色候选全域** =
  ``{effective_from, effective_to, location}`` ⇒ ``facts=1`` 强制“恰好 1 个被请求角色、
  该角色恰好 1 列”。故 ``role_not_requested`` 恒为 ``3-1=2``，与真实
  ``fact_built=1 / role_not_requested=2`` 同形。
- C27：``facts=2, expected=2, missing=1``，候选全域 =
  ``{address, contact, effective_from, effective_to, phone, status}``（6 个）⇒ 被请求角色
  1 或 2 个（1 角色×2 列 或 2 角色×1 列），``role_not_requested`` 落在 ``{4, 5}``。

本文件只用这三组固定码构造合成件，断言：

1. 投影形状可复现真实两案的阶梯计数（1/2 与 2/(4|5)）；
2. 因果杠杆唯一：只要候选角色进了 ``plan.field_roles``，该角色的列必成 fact（绿）；
   把它从计划里拿掉，该列必不进 facts（红）——即“补词表 = 补被请求角色”，不是改 facts 层；
3. 反例①：只问单端/单字段时不夹带另一端；
4. 反例③：每个 fact 值都等于被引行里的某个单元格值（不捏造）；
5. 守卫：投影出来的 7 个候选角色当前**全部**可被词表请求到（缺的是词形，不是角色表），
   以及索引侧可映射但问句侧无词形的角色只剩 ``issued_quantity``（不在任何候选全域内）。

所有中文串都是合成问法/合成表头，不含任何真实题面、真实实体或真实业务值。
"""

from __future__ import annotations

import hashlib

import pytest

from mktkb.rag import AtomicUnit, DocumentSpec

#: 投影 09 节：被引行字段角色候选全域（固定角色码，按字母序）。
_C21_UNIVERSE = ("effective_from", "effective_to", "location")
_C27_UNIVERSE = ("address", "contact", "effective_from", "effective_to", "phone", "status")
#: 候选角色 -> 合成问法用的**已登记词形**（产品词表里已有的字段词，不是业务值）。
_WORD = {
    "effective_from": "生效日期",
    "effective_to": "失效日期",
    "location": "位置",
    "address": "地址",
    "contact": "联系人",
    "phone": "电话",
    "status": "合作状态",
}
#: 实体/条件角色：不构造 fact，不参与 ``role_not_requested`` 计数。
_ENTITY_ROLES = frozenset(
    {"identifier", "store", "item", "product", "channel", "price_type", "alias", "unit"}
)

_C21_ROW = {
    "标识": "L-0001",
    "门店": "甲店",
    "物品": "立牌",
    "生效日期": "2026-01-05",
    "失效日期": "2026-09-30",
    "位置": "甲区三层",
}
_C27_ROW = {
    "标识": "S-0001",
    "门店": "丙店",
    "地址": "丙区一号",
    "联系人": "丁",
    "电话": "000-0000-0001",
    "合作状态": "在营",
    "生效日期": "2026-02-01",
    "失效日期": "2026-08-31",
}
_ROWS = {"c21": (_C21_ROW, "甲店", "立牌"), "c27": (_C27_ROW, "丙店", None)}


def _add_row(rag_index, fields: dict, *, doc_id: str) -> None:
    doc = DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"corpus/{doc_id}.xlsx",
        title="合成台账",
        file_kind="xlsx",
        version_id=f"V-{doc_id}",
        version_label="当前",
        sha256=hashlib.sha256(doc_id.encode()).hexdigest(),
        is_current=True,
        state="active",
        business_date="2026-10-28",
    )
    unit = AtomicUnit(
        unit_id=f"{doc_id}-row7",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key="sheet:合成表:row:7",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=dict(fields),
        sheet="合成表",
        locator={"sheet": "合成表", "row": 7, "header_row": 0},
        header_row=0,
        row_number=7,
        title=doc.title,
    )
    rag_index.add_document(doc, [unit], embed=False)


def _plan_roles(plan) -> tuple[str, ...]:
    roles = tuple(getattr(plan, "field_roles", ()) or ())
    return roles or ((plan.field_role,) if plan.field_role else ())


def _cited_row(index, answer):
    for citation in answer.citations:
        chunk_id = str(getattr(citation, "source_id", "") or "")
        if not chunk_id:
            continue
        chunk = index.get_chunk(chunk_id, require_visible=True)
        if chunk is not None and chunk.kind == "record":
            return chunk
    return None


def _ledger(index, question: str, *, conversation_id: str) -> dict:
    """跑一次产品路径，返回固定码视图（plan 角色 / facts / 未请求角色计数）。"""
    from mktkb.rag.query import build_lexicon, parse_query

    plan = parse_query(
        question,
        previous=index.load_state("u", conversation_id),
        lexicon=build_lexicon(index.lexicon_data()),
        business_date=index.config.business_date,
        page_size=index.config.page_size,
    )
    answer = index.ask(question, user_id="u", conversation_id=conversation_id)
    requested = _plan_roles(plan)
    facts = {(fact.field_role, fact.value) for fact in answer.facts}
    row = _cited_row(index, answer)
    role_not_requested = 0
    row_roles: set[str] = set()
    if row is not None:
        for role, values in dict(row.role_values or {}).items():
            if role in _ENTITY_ROLES:
                continue
            row_roles.add(role)
            if role not in requested:
                role_not_requested += len(values)
    return {
        "kind": str(answer.kind),
        "plan_roles": requested,
        "facts": facts,
        "fact_roles": sorted({fact.field_role for fact in answer.facts}),
        "fact_values": [fact.value for fact in answer.facts],
        "role_not_requested": role_not_requested,
        "row_roles": row_roles,
        "row_fields": dict(getattr(row, "fields", None) or {}),
        "text": answer.text,
    }


def _ask(rag_index, question: str, *, conversation_id: str) -> dict:
    return _ledger(rag_index, question, conversation_id=conversation_id)


# --------------------------------------------------------------------------- #
# 1. 投影形状 <-> 真实阶梯计数
# --------------------------------------------------------------------------- #


def test_c21_projected_shape_reproduces_fact_one_role_not_requested_two(rag_index):
    """C21 投影：facts=1 + 候选 3 个 ⇒ 单角色问法必然 ``fact_built=1 / role_not_requested=2``。"""
    _add_row(rag_index, dict(_C21_ROW), doc_id="D-rm-c21")
    for role in _C21_UNIVERSE:
        state = _ask(rag_index, f"列出甲店立牌的{_WORD[role]}", conversation_id=f"rm-c21-{role}")
        assert state["kind"] == "answer", state["kind"]
        assert state["plan_roles"] == (role,), state["plan_roles"]
        assert len(state["facts"]) == 1
        assert state["role_not_requested"] == len(_C21_UNIVERSE) - 1
        # 合成件的被引行字段角色 == 投影出来的候选全域（形状对得上投影）。
        assert state["row_roles"] == set(_C21_UNIVERSE), state["row_roles"]


def test_c27_projected_shape_role_not_requested_is_four_or_five(rag_index):
    """C27 投影：facts=2 + 候选 6 个 ⇒ 未请求数落在 {4, 5}（对应真实 ``2 / (4 或 5)``）。"""
    _add_row(rag_index, dict(_C27_ROW), doc_id="D-rm-c27")
    single = _ask(rag_index, f"列出丙店的{_WORD['phone']}", conversation_id="rm-c27-one")
    assert single["plan_roles"] == ("phone",), single["plan_roles"]
    assert len(single["facts"]) == 1
    assert single["role_not_requested"] == 5

    pair = _ask(
        rag_index, f"列出丙店的{_WORD['address']}和{_WORD['phone']}", conversation_id="rm-c27-two"
    )
    assert set(pair["plan_roles"]) == {"address", "phone"}, pair["plan_roles"]
    assert len(pair["facts"]) == 2
    assert pair["role_not_requested"] == 4


# --------------------------------------------------------------------------- #
# 2. 红 -> 绿：唯一杠杆是 plan.field_roles（补词表 = 补被请求角色）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", [*_C21_UNIVERSE, *_C27_UNIVERSE])
def test_each_projected_candidate_role_turns_green_once_requested(rag_index, monkeypatch, role):
    """对投影出的每个候选角色：请求到它 ⇒ 该列进 facts（绿）；把它从计划里拿掉 ⇒ 该列丢（红）。

    同一行、同一句“两个都问”的话，只改“计划请求了哪些角色”：
    因果注入只把目标角色从 ``_match_fields`` 的结果里过滤掉，不动 facts 层 —— 这正是
    “补词表”唯一的作用面。红档形状 = 真实两案（``fact_built=1`` + 目标角色落进
    ``role_not_requested``）。
    """
    case = "c21" if role in _C21_UNIVERSE else "c27"
    universe = _C21_UNIVERSE if case == "c21" else _C27_UNIVERSE
    partner = next(item for item in universe if item != role)
    row, store, item = _ROWS[case]
    _add_row(rag_index, dict(row), doc_id=f"D-rm-pair-{case}-{role}")
    subject = f"{store}{item or ''}"
    question = f"列出{subject}的{_WORD[role]}和{_WORD[partner]}"

    green = _ask(rag_index, question, conversation_id=f"rm-green-{case}-{role}")
    assert set(green["plan_roles"]) == {role, partner}, green["plan_roles"]
    assert set(green["fact_roles"]) == {role, partner}, green["fact_roles"]
    assert len(green["facts"]) == 2

    from mktkb.rag import query as query_module

    original = query_module._match_fields
    monkeypatch.setattr(
        query_module,
        "_match_fields",
        lambda text: tuple(item for item in original(text) if item != role),
    )
    red = _ask(rag_index, question, conversation_id=f"rm-red-{case}-{role}")
    monkeypatch.setattr(query_module, "_match_fields", original)
    assert red["plan_roles"] == (partner,), red["plan_roles"]
    assert role not in red["fact_roles"], red["fact_roles"]
    assert len(red["facts"]) == 1
    # 红档里目标角色必然落进“未被请求”，与真实两案的缺项固定码同形。
    assert role in red["row_roles"], red["row_roles"]
    assert role not in red["plan_roles"]


# --------------------------------------------------------------------------- #
# 3. 反例①：只问单端/单字段不得夹带另一端
# --------------------------------------------------------------------------- #


def test_single_end_question_does_not_carry_the_other_end(rag_index):
    _add_row(rag_index, dict(_C21_ROW), doc_id="D-rm-single-end")
    state = _ask(rag_index, "列出甲店立牌的失效日期", conversation_id="rm-single-end")
    assert state["plan_roles"] == ("effective_to",)
    assert [fact_role for fact_role, _ in state["facts"]] == ["effective_to"]
    assert state["fact_values"] == ["2026-09-30"]


def test_single_phone_question_does_not_carry_address(rag_index):
    _add_row(rag_index, dict(_C27_ROW), doc_id="D-rm-single-phone")
    state = _ask(rag_index, "列出丙店的电话", conversation_id="rm-single-phone")
    assert state["plan_roles"] == ("phone",)
    assert state["fact_roles"] == ["phone"]


# --------------------------------------------------------------------------- #
# 4. 反例③：不捏造（每个 fact 值都来自被引行单元格）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", [*_C21_UNIVERSE, *_C27_UNIVERSE])
def test_every_fact_value_comes_from_the_cited_row(rag_index, role):
    case = "c21" if role in _C21_UNIVERSE else "c27"
    row, store, item = _ROWS[case]
    _add_row(rag_index, dict(row), doc_id=f"D-rm-nofab-{case}-{role}")
    state = _ask(
        rag_index, f"列出{store}{item or ''}的{_WORD[role]}", conversation_id=f"rm-nofab-{role}"
    )
    cells = {str(value) for value in state["row_fields"].values()}
    assert state["fact_values"], state["fact_roles"]
    for value in state["fact_values"]:
        assert value in cells, state["fact_roles"]


# --------------------------------------------------------------------------- #
# 5. 守卫：候选角色当前全部可请求（缺的是词形），词表缺口只剩不在候选内的角色
# --------------------------------------------------------------------------- #


def test_every_projected_candidate_role_is_reachable_from_the_word_table():
    """投影结论“缺的是词形、不是角色表”的可执行守卫：7 个候选角色都至少有一个已登记词形。"""
    from mktkb.rag.query import FIELD_WORDS, _EXTRA_FIELD_ROLE_WORDS, _match_field

    for role in [*_C21_UNIVERSE, *_C27_UNIVERSE]:
        words = tuple(FIELD_WORDS.get(role, ())) + tuple(_EXTRA_FIELD_ROLE_WORDS.get(role, ()))
        assert words, role
        assert any(_match_field(word) == role for word in words), role


def test_only_non_candidate_record_role_without_query_word_is_issued_quantity():
    """``issued_quantity`` 是唯一“索引侧有角色、问句侧零词形”的记录字段角色。

    它不在 C21/C27 的任何候选全域里（``cited_roles`` 无该码），所以**不是**本轮两案的
    缺项原因；这里把它钉成已知缺口，避免以后被误当回归，也避免被当成“修好了”。
    用子集断言：以后若补上它，本测试仍绿；只有冒出**新的**无词形角色才会红。
    """
    from mktkb.rag.chunking import ROLE_SYNONYMS
    from mktkb.rag.query import FIELD_WORDS, _EXTRA_FIELD_ROLE_WORDS

    covered = set(FIELD_WORDS) | set(_EXTRA_FIELD_ROLE_WORDS)
    record_roles = {
        role
        for role in ROLE_SYNONYMS
        if role not in {"identifier", "product", "channel", "price_type", "store", "item", "alias", "unit"}
    }
    missing = set(record_roles - covered)
    assert missing <= {"issued_quantity"}, sorted(missing)
