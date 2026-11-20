"""R0 第五轮：C21/C27 的 **facts 层准入阶梯**（合成 / 去身份化，只断言计数与固定角色码）。

背景（SAFE 已确证，不在测试里重测）
------------------------------------
真实两案的 L1 DB 单元 / L2 被引单元 / L3 可映射角色都满，L4 ``answer.facts`` 少值：
C21 0/1、C27 1/2，且与提交文本逐值相同 ⇒ 值是在“可映射角色 -> facts”这一步丢的。

本文件把这一步做成可复现的阶梯：在**产品真实路径**（parse -> retrieve -> answer ->
validate）上，对每个被引记录行枚举 ``(role, value)`` 候选，按固定拒绝码定性：

- ``fact_built``：该角色在 ``plan.field_roles`` 里，值进了 ``answer.facts``；
- ``role_not_requested``：角色可映射、但**没有被问题请求**（facts 构造只遍历被请求角色）；
- ``role_value_missing``：请求了该角色，但被引行没有这个角色（fail-closed）；
- ``value_rejected_by_validate`` / ``cross_field_conflict``：整条回答被 FactValidator 拒；
- ``dedup_dropped``：同角色同值的重复列被去重；
- ``all_fields_representative_only``：无字段请求的全字段枚举只造 1 条代表事实。

结构断言（不是按题号特判）：
1. 同一行、同一份代码，**只请求一端** ⇒ 另一端 ``role_not_requested``（红形态）；
2. **显式请求两端** ⇒ 两端都 ``fact_built``（绿形态）——facts 层本身是忠实的；
3. 任何形状下 ``undetermined == 0``、``cross_field_conflict == 0``；
4. 非全字段枚举下，出现在正文里的值一定也出现在 facts 里（无静默丢列）。
"""

from __future__ import annotations

import hashlib
from collections import Counter

from mktkb.rag import AtomicUnit, DocumentSpec
from mktkb.rag.chunking import field_role
from mktkb.retrieval.tokenize import normalize

CODES = (
    "fact_built",
    "role_not_requested",
    "role_value_missing",
    "value_rejected_by_validate",
    "cross_field_conflict",
    "dedup_dropped",
    "all_fields_representative_only",
    "undetermined",
)

#: 角色清单取自真实 cited_roles（只有角色名，没有值/题面）。
C21_ROW = {
    "标识": "L01",
    "门店": "甲店",
    "物品": "立牌",
    "别名": "牌牌",
    "位置": "甲区一号位",
    "生效日期": "2026-01-05",
    "失效日期": "2026-09-30",
}
C27_ROW = {
    "门店": "甲店",
    "联系人": "张经理",
    "联系电话": "010-1000-1001",
    "门店地址": "合成区长街 1 号",
    "合作状态": "合作中",
    "生效日期": "2026-01-05",
    "失效日期": "2026-09-30",
}


def _add_row(rag_index, fields: dict, *, doc_id: str, row: int = 7) -> None:
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
        unit_id=f"{doc_id}-row{row}",
        doc_id=doc.doc_id,
        version_id=doc.version_id,
        kind="table_row",
        ordinal=0,
        unit_key=f"sheet:合成表:row:{row}",
        text="；".join(f"{name}: {value}" for name, value in fields.items()),
        fields=dict(fields),
        sheet="合成表",
        locator={"sheet": "合成表", "row": row, "header_row": 0},
        header_row=0,
        row_number=row,
        title="合成台账",
    )
    rag_index.add_document(doc, [unit], embed=False)


def _plan_roles(plan) -> tuple[str, ...]:
    roles = tuple(getattr(plan, "field_roles", ()) or ())
    return roles or ((plan.field_role,) if plan.field_role else ())


def _cited_rows(index, answer) -> list:
    rows, seen = [], set()
    for citation in answer.citations:
        chunk_id = str(getattr(citation, "source_id", "") or "")
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        chunk = index.get_chunk(chunk_id, require_visible=True)
        if chunk is not None and chunk.kind == "record":
            rows.append(chunk)
    return rows


def _ladder(index, question: str, *, conversation_id: str) -> dict:
    """跑一次产品路径，把被引行的非实体角色候选逐条定性（只返回码与角色名）。"""
    from mktkb.rag.query import build_lexicon, parse_query

    previous = index.load_state("u", conversation_id)
    plan = parse_query(
        question,
        previous=previous,
        lexicon=build_lexicon(index.lexicon_data()),
        business_date=index.config.business_date,
        page_size=index.config.page_size,
    )
    answer = index.ask(question, user_id="u", conversation_id=conversation_id)
    requested = _plan_roles(plan)
    entity_roles = {"store", "item", "product", "channel", "price_type", "identifier", "alias", "unit"}
    facts = {(fact.field_role, fact.value) for fact in answer.facts}
    codes: Counter[str] = Counter({code: 0 for code in CODES})
    answer_kind = str(answer.kind)
    answer_reason = str(answer.reason or "none")
    rendered_but_not_fact = 0
    rows = _cited_rows(index, answer)
    for chunk in rows:
        fields = dict(chunk.fields or {})
        occurrences: Counter[tuple[str, str]] = Counter()
        for name, raw in fields.items():
            role = field_role(name)
            text = "" if raw is None else str(raw).strip()
            if role and text:
                occurrences[(role, normalize(text))] += 1
        for role, values in dict(chunk.role_values or {}).items():
            if role in entity_roles:
                continue
            for value in values:
                pair = (role, str(value))
                if not plan.field_role:
                    code = "fact_built" if pair in facts else "all_fields_representative_only"
                elif role not in requested:
                    code = "role_not_requested"
                elif pair in facts:
                    code = "fact_built"
                elif answer_kind != "answer" and answer_reason == "CROSS_FIELD":
                    code = "cross_field_conflict"
                elif answer_kind != "answer" and answer_reason in {
                    "FORGED_VALUE",
                    "CROSS_ENTITY",
                    "STALE_SOURCE",
                    "UNSUPPORTED_CLAIM",
                }:
                    code = "value_rejected_by_validate"
                else:
                    code = "undetermined"
                codes[code] += 1
                if code == "fact_built":
                    extra = occurrences[(role, normalize(str(value)))] - 1
                    if extra > 0:
                        codes["dedup_dropped"] += extra
                if (
                    answer_kind == "answer"
                    and plan.field_role
                    and code not in ("fact_built", "role_not_requested")
                    and normalize(str(value)) in normalize(answer.text)
                ):
                    rendered_but_not_fact += 1
    for role in requested:
        if role in entity_roles:
            continue
        if not any(role in dict(chunk.role_values or {}) for chunk in rows):
            codes["role_value_missing"] += 1
    return {
        "plan_roles": requested,
        "answer_kind": answer_kind,
        "answer_reason": answer_reason,
        "fact_roles": sorted({fact.field_role for fact in answer.facts}),
        "fact_values": [fact.value for fact in answer.facts],
        "facts": facts,
        "rows": rows,
        "codes": codes,
        "rendered_but_not_fact": rendered_but_not_fact,
    }


# --------------------------------------------------------------------------- #
# 红形态：只请求一端 ⇒ 另一端 role_not_requested（= 真实两案 facts 少一项）
# --------------------------------------------------------------------------- #


def test_c21_shape_single_end_leaves_other_end_out_of_facts(rag_index):
    _add_row(rag_index, dict(C21_ROW), doc_id="D-adm-c21a")
    state = _ladder(rag_index, "列出甲店立牌的失效日期", conversation_id="adm-c21a")
    assert state["answer_kind"] == "answer"
    assert state["plan_roles"] == ("effective_to",)
    assert state["codes"]["fact_built"] == 1
    # 可映射但未被请求：effective_from + location。
    assert state["codes"]["role_not_requested"] == 2
    assert state["codes"]["undetermined"] == 0
    assert state["rendered_but_not_fact"] == 0


def test_c27_shape_single_phone_leaves_address_out_of_facts(rag_index):
    _add_row(rag_index, dict(C27_ROW), doc_id="D-adm-c27a")
    state = _ladder(rag_index, "列出甲店的联系电话", conversation_id="adm-c27a")
    assert state["answer_kind"] == "answer"
    assert state["plan_roles"] == ("phone",)
    assert state["codes"]["fact_built"] == 1
    # 可映射但未被请求：address/contact/status/effective_from/effective_to。
    assert state["codes"]["role_not_requested"] == 5
    assert state["codes"]["undetermined"] == 0


# --------------------------------------------------------------------------- #
# 绿形态：同一行 + 显式请求两端 ⇒ 两端都进 facts（代码未改）
# --------------------------------------------------------------------------- #


def test_c21_shape_requesting_both_ends_builds_both_facts(rag_index):
    _add_row(rag_index, dict(C21_ROW), doc_id="D-adm-c21b")
    state = _ladder(rag_index, "列出甲店立牌的生效日期和失效日期", conversation_id="adm-c21b")
    assert state["answer_kind"] == "answer"
    assert set(state["plan_roles"]) == {"effective_from", "effective_to"}
    assert state["codes"]["fact_built"] == 2
    assert {"effective_from", "effective_to"} <= set(state["fact_roles"])
    assert state["codes"]["role_not_requested"] == 1  # 只剩 location


def test_c27_shape_requesting_both_contact_columns_builds_both(rag_index):
    _add_row(rag_index, dict(C27_ROW), doc_id="D-adm-c27b")
    state = _ladder(rag_index, "列出甲店的门店地址和联系电话", conversation_id="adm-c27b")
    assert state["answer_kind"] == "answer"
    assert set(state["plan_roles"]) == {"phone", "address"}
    assert state["codes"]["fact_built"] == 2
    assert {"address", "phone"} <= set(state["fact_roles"])


def test_c27_real_facts_two_shape_is_two_requested_roles(rag_index):
    """真实 C27 的 facts=2 同形：两个被请求角色各 1 列 ⇒ 2 条 facts、4 条未请求。"""
    _add_row(rag_index, dict(C27_ROW), doc_id="D-adm-c27c")
    state = _ladder(rag_index, "列出甲店的合作状态和联系电话", conversation_id="adm-c27c")
    assert state["codes"]["fact_built"] == 2
    assert state["codes"]["role_not_requested"] == 4


# --------------------------------------------------------------------------- #
# 同角色多列 / 去重 / 全字段：证明其他“可能丢值”的闸都不在此路径
# --------------------------------------------------------------------------- #


def test_same_role_two_columns_both_enter_facts(rag_index):
    _add_row(
        rag_index,
        {"标识": "L02", "门店": "甲店", "物品": "立牌", "参考供价": "5", "零售价": "7"},
        doc_id="D-adm-price1",
    )
    state = _ladder(rag_index, "列出甲店立牌的价格", conversation_id="adm-price1")
    assert state["codes"]["fact_built"] == 2
    assert state["codes"]["dedup_dropped"] == 0


def test_same_role_same_value_is_deduped_not_dropped(rag_index):
    _add_row(
        rag_index,
        {"标识": "L03", "门店": "甲店", "物品": "立牌", "参考供价": "5", "零售价": "5"},
        doc_id="D-adm-price2",
    )
    state = _ladder(rag_index, "列出甲店立牌的价格", conversation_id="adm-price2")
    assert state["codes"]["fact_built"] == 1
    assert state["codes"]["dedup_dropped"] == 1


def test_all_fields_enumeration_builds_one_representative_fact(rag_index):
    _add_row(rag_index, dict(C21_ROW), doc_id="D-adm-all")
    state = _ladder(rag_index, "列出甲店立牌的全部信息", conversation_id="adm-all")
    assert state["answer_kind"] == "answer"
    assert state["plan_roles"] == ()
    assert state["fact_roles"] == ["identifier"]
    assert state["codes"]["all_fields_representative_only"] == 3


def test_requested_role_absent_is_fail_closed(rag_index):
    _add_row(
        rag_index,
        {"标识": "L04", "门店": "甲店", "物品": "立牌", "位置": "甲区一号位"},
        doc_id="D-adm-nodate",
    )
    state = _ladder(rag_index, "列出甲店立牌的失效日期", conversation_id="adm-nodate")
    assert state["answer_kind"] == "no_answer"
    assert state["fact_values"] == []
    assert state["codes"]["role_value_missing"] == 1


# --------------------------------------------------------------------------- #
# 反例 ①：单字段问法不夹带其他字段
# --------------------------------------------------------------------------- #


def test_single_field_questions_do_not_drag_other_columns(rag_index):
    _add_row(rag_index, dict(C21_ROW), doc_id="D-adm-one1")
    _add_row(rag_index, dict(C27_ROW), doc_id="D-adm-one2")
    cases = [
        ("列出甲店立牌的失效日期", {"effective_to"}),
        ("列出甲店立牌什么时候生效？", {"effective_from"}),
        ("列出甲店的联系电话", {"phone"}),
        ("列出甲店的门店地址", {"address"}),
    ]
    for question, expected in cases:
        state = _ladder(rag_index, question, conversation_id="adm-one-" + question[-4:])
        assert set(state["fact_roles"]) == expected, (question, state["fact_roles"])


# --------------------------------------------------------------------------- #
# 反例 ③：进 facts 的值必须是被引行里的真实单元格值（不产生 value_no_fabricated）
# --------------------------------------------------------------------------- #


def test_every_fact_value_comes_from_the_cited_row(rag_index):
    for doc_id, fields in (("D-adm-nofab1", C21_ROW), ("D-adm-nofab2", C27_ROW)):
        _add_row(rag_index, dict(fields), doc_id=doc_id)
    for question in (
        "列出甲店立牌的生效日期和失效日期",
        "列出甲店的门店地址和联系电话",
        "列出甲店立牌的价格",
    ):
        state = _ladder(rag_index, question, conversation_id="adm-nofab-" + str(len(question)))
        allowed = {str(value) for chunk in state["rows"] for value in dict(chunk.fields or {}).values()}
        if not state["rows"]:
            continue
        for value in state["fact_values"]:
            assert value in allowed, (question, value, allowed)


# --------------------------------------------------------------------------- #
# 红/绿因果对照：只把“计划少请求一项”注入，facts 立刻少一项（其余代码不动）
# --------------------------------------------------------------------------- #


def test_plan_under_request_reproduces_the_facts_deficit(rag_index, monkeypatch):
    """同一行、同一句“两个都问”的话：把 ``_match_fields`` 收窄成只留首个角色后，

    被请求角色从 2 变 1 ⇒ ``fact_built`` 2→1、另一端变 ``role_not_requested``。
    这正是真实 C21/C27 的 L4 形态；恢复计划层即回到绿 ⇒ 修复点不在 facts 层。
    """
    from mktkb.rag import query as query_module

    _add_row(rag_index, dict(C21_ROW), doc_id="D-adm-red1")
    original = query_module._match_fields
    monkeypatch.setattr(
        query_module, "_match_fields", lambda question: tuple(original(question))[:1]
    )
    state = _ladder(
        rag_index, "列出甲店立牌的生效日期和失效日期", conversation_id="adm-red1"
    )
    assert state["plan_roles"] == ("effective_to",)
    assert state["codes"]["fact_built"] == 1
    assert state["codes"]["role_not_requested"] == 2
    assert state["codes"]["undetermined"] == 0


# --------------------------------------------------------------------------- #
# 不变量：非全字段路径下不存在“渲染了却没进 facts”的静默丢值
# --------------------------------------------------------------------------- #


def test_no_silent_drop_under_non_all_fields(rag_index):
    _add_row(rag_index, dict(C21_ROW), doc_id="D-adm-inv1")
    _add_row(rag_index, dict(C27_ROW), doc_id="D-adm-inv2")
    for question in (
        "列出甲店立牌的失效日期",
        "列出甲店立牌的生效日期和失效日期",
        "列出甲店的联系电话",
        "列出甲店的门店地址和联系电话",
        "列出甲店立牌的价格",
    ):
        state = _ladder(rag_index, question, conversation_id="adm-inv-" + str(len(question)))
        assert state["codes"]["undetermined"] == 0, (question, state["codes"])
        assert state["codes"]["cross_field_conflict"] == 0, (question, state["codes"])
        assert state["rendered_but_not_fact"] == 0, (question, state["codes"])
