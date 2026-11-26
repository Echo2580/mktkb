"""独立验收：fix-1/R1 纯指代守卫的自建探针（不照抄开发用例）。

覆盖：
- N2：纯指代 + 已点名门店（“这两个/这几个”）→ 必须澄清，不得枚举作答；
- A 正例：两店一物品 / 一店两物品 / 两店电话 / 两店一物品+分别 → MULTI_TARGET_ENUMERATE；
- 自造新回归面：混合（1 显式 + 1 指代）、跨轮指代、指代+词表外门店、
  显式枚举含歧义物品、复指限定语（不得过度拦截）、门店维指代；
- null/bare：bare 指代 → MISSING_SLOT；指代+物品维歧义 → ITEM_AMBIGUOUS。

改前对照：用本轮 diff 反向应用重建的 fix-1 终态 `query.py`（f73fc735）加载为独立模块，
逐用例比较 planner 与产品层 `_rag_owns_turn`；内核 ask 只跑当前代码。

零真实调用：临时 SQLite + offline provider；socket 出站全部拦截并计数。
不读取真实 H2 题面/答案；全部为合成问句与合成记录。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
sys.path.insert(0, str(REPO / "backend" / "src"))
sys.path.insert(0, str(HERE))

OUT = HERE / "probe-fix1r1.json"
PRE_R1_SOURCE = HERE / "_pre_r1_query.py"
PRE_FIX1_SOURCE = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fix-1/independent/_reconstructed_query.py"
PRE_FIX1_EXPECTED = "5a7ed26b73a3ab658deff6384b5fdcc67596860345153cec4ec4f72cb350e1e1"
OUTBOUND: list[str] = []


def _guard() -> None:
    def deny(*args: Any, **kwargs: Any) -> Any:
        OUTBOUND.append(f"outbound:{args!r}"[:240])
        raise OSError("netguard: outbound blocked")

    socket.socket.connect = deny  # type: ignore[assignment]
    socket.socket.connect_ex = deny  # type: ignore[assignment]
    socket.create_connection = deny  # type: ignore[assignment]
    socket.getaddrinfo = deny  # type: ignore[assignment]


_guard()

import verify_diff  # noqa: E402

import mktkb.rag.answer as rag_answer  # noqa: E402
from mktkb.conversations.intent import EntityLexicon, parse_question  # noqa: E402
from mktkb.conversations.service import _rag_owns_turn  # noqa: E402
from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402
from mktkb.rag import query as current_query  # noqa: E402
from mktkb.rag.query import Lexicon  # noqa: E402
from mktkb.rag.types import QueryState  # noqa: E402

LEXICON = Lexicon(
    stores=("北苑店", "南湖店"),
    items=("桌牌", "横幅"),
    field_labels=("位置", "电话"),
)
STORE_LABELS = LEXICON.stores
ITEM_LABELS = LEXICON.items

ITEM_ROWS = [
    {"标识": "X01", "门店": "北苑店", "物品": "桌牌", "位置": "一层东侧"},
    {"标识": "X02", "门店": "南湖店", "物品": "桌牌", "位置": "二层西侧"},
    {"标识": "X03", "门店": "北苑店", "物品": "横幅", "位置": "三层中庭"},
    {"标识": "X04", "门店": "南湖店", "物品": "横幅", "位置": "四层入口"},
    {"标识": "X05", "门店": "东篱店", "物品": "展架", "位置": "五层仓库"},
]
PHONE_ROWS = [
    {"标识": "Y01", "门店": "北苑店", "联系人": "甲", "电话": "010-20000001"},
    {"标识": "Y02", "门店": "南湖店", "联系人": "乙", "电话": "010-20000002"},
]
POSITIONS = [row["位置"] for row in ITEM_ROWS]
PHONES = [row["电话"] for row in PHONE_ROWS]


def _reconstruct_pre_r1() -> dict[str, Any]:
    """用本轮 diff 反向应用重建 fix-1 终态 query.py（不改工作树）。"""
    patch_text = (REPO / "docs/reports/OBS-EVAL/P2/H2V3/fix-1r1/evidence/fix-r1.diff").read_text(
        encoding="utf-8"
    )
    body = "\n".join(patch_text.split("\n")[1:])
    sections = verify_diff.parse_patch(body)
    target = "backend/src/mktkb/rag/query.py"
    section = next(
        item
        for item in sections
        if verify_diff.display_path(item["new_path"]) == target
    )
    current_path = REPO / target
    current_text, newline = verify_diff.read_text_keep_newline(current_path)
    pre_text = verify_diff.apply_section(current_text, section, reverse=True)
    raw = pre_text.replace("\n", "\r\n").encode("utf-8") if newline == "\r\n" else pre_text.encode("utf-8")
    PRE_R1_SOURCE.write_bytes(raw)
    return {
        "path": str(PRE_R1_SOURCE.relative_to(REPO)).replace("\\", "/"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "expected_sha256": "f73fc7353501e09e65a474fc2599fa4235e1db5d72fc4ea802e0e881f680c372",
        "matches": hashlib.sha256(raw).hexdigest()
        == "f73fc7353501e09e65a474fc2599fa4235e1db5d72fc4ea802e0e881f680c372",
    }


def _load_pre_r1_module():
    spec = importlib.util.spec_from_file_location("mktkb.rag._pre_r1_query", PRE_R1_SOURCE)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load pre-R1 query module")
    module = importlib.util.module_from_spec(spec)
    sys.modules["mktkb.rag._pre_r1_query"] = module
    spec.loader.exec_module(module)
    return module


def _load_pre_fix1_module():
    """fix-1/A 之前的基线（上一轮独立验收重建，SHA 5a7ed26b…），仅用于证明 D1/D2 非新回归。"""
    if not PRE_FIX1_SOURCE.exists():
        return None
    spec = importlib.util.spec_from_file_location("mktkb.rag._pre_fix1_query", PRE_FIX1_SOURCE)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["mktkb.rag._pre_fix1_query"] = module
    spec.loader.exec_module(module)
    return module


def _doc(doc_id: str, title: str) -> DocumentSpec:
    return DocumentSpec(
        doc_id=doc_id,
        logical_id=doc_id,
        source_path=f"fixtures/synthetic/{doc_id}.xlsx",
        title=title,
        file_kind="xlsx",
        version_id=f"{doc_id}-v1",
        version_label="当前",
        sha256=hashlib.sha256(doc_id.encode()).hexdigest(),
        business_date="2026-10-15",
    )


def _units(doc: DocumentSpec, rows: list[dict[str, Any]], sheet: str) -> list[AtomicUnit]:
    units = []
    for ordinal, row in enumerate(rows):
        body = "；".join(f"{key}: {value}" for key, value in row.items())
        units.append(
            AtomicUnit(
                unit_id=f"{doc.doc_id}-{ordinal}-{uuid.uuid4().hex[:6]}",
                doc_id=doc.doc_id,
                version_id=doc.version_id,
                kind="table_row",
                ordinal=ordinal,
                unit_key=f"sheet:{sheet}:row:{8 + ordinal}",
                text=body,
                fields=dict(row),
                sheet=sheet,
                locator={"sheet": sheet, "row": 8 + ordinal, "header_row": 7},
                row_number=8 + ordinal,
                title=doc.title,
            )
        )
    return units


def _plan(module, question: str, previous: QueryState | None = None) -> dict[str, Any]:
    plan = module.parse_query(
        question, previous=previous, lexicon=LEXICON, business_date="2026-10-15"
    )
    return {
        "mode": plan.mode,
        "reason": plan.reason,
        "clarification": plan.clarification,
        "enumerate": bool(plan.enumerate),
        "field_role": plan.field_role,
        "filters": dict(plan.filters),
        "stores": list(plan.state.stores),
        "items": list(getattr(plan.state, "items", ()) or ()),
        "item": plan.state.item,
        "pending_slot": plan.state.pending_slot,
        "missing_stores": list(plan.missing_stores),
        "term_count": len(plan.terms),
        "rag_owns_turn": bool(_rag_owns_turn(QueryState(), plan)),
    }


def _answer(index: RagIndex, question: str, tag: str, conversation_id: str | None = None) -> dict[str, Any]:
    answer = index.ask(
        question, user_id="u-independent-r1", conversation_id=conversation_id or f"c-r1-{tag}"
    )
    text = str(answer.text or "")
    return {
        "kind": answer.kind,
        "reason": answer.reason,
        "returned": (answer.diagnostics or {}).get("returned"),
        "text": text,
        "state": dict(answer.state),
        "positions_present": {value: value in text for value in POSITIONS},
        "phones_present": {value: value in text for value in PHONES},
    }


def _legacy(question: str) -> dict[str, Any]:
    plan = parse_question(
        question,
        lexicon=EntityLexicon(store_labels=STORE_LABELS, item_labels=ITEM_LABELS),
    )
    return {
        "mode": plan.mode,
        "clarification": plan.clarification,
        "unknown_store": plan.unknown_store,
        "unknown_identifier": plan.unknown_identifier,
        "entity_filters": dict((plan.intent.entity_filters if plan.intent else {}) or {}),
    }


def _absent_all(answer: dict[str, Any]) -> bool:
    return not any(answer["positions_present"].values())


def _present_only(answer: dict[str, Any], positions: list[str]) -> bool:
    text = answer["text"]
    return all(value in text for value in positions) and not any(
        value in text for value in POSITIONS if value not in positions
    )


CASES: list[dict[str, Any]] = [
    # ---------------------------------------------------------------- N2
    {
        "id": "N2a_this_two_with_named_stores",
        "cls": "N2 纯指代 + 已点名门店",
        "question": "北苑店和南湖店的这两个分别放在哪里？",
        "must": {
            "clarified": True,
            "not_multi_release": True,
            "no_product_release": True,
            "no_enumeration": True,
        },
    },
    {
        "id": "N2b_these_with_named_stores",
        "cls": "N2 纯指代 + 已点名门店（这几个）",
        "question": "北苑店和南湖店的这几个分别放在哪里？",
        "must": {
            "clarified": True,
            "not_multi_release": True,
            "no_product_release": True,
            "no_enumeration": True,
        },
    },
    {
        "id": "N2c_this_two_phone_dimension",
        "cls": "N2 纯指代 + 门店维字段（电话）",
        "question": "北苑店和南湖店的这两个电话是多少？",
        "must": {
            "clarified": True,
            "not_multi_release": True,
            "no_product_release": True,
            "no_enumeration": True,
        },
    },
    {
        "id": "N2d_this_two_no_field_word",
        "cls": "N2 纯指代 + 已点名门店（无字段词）",
        "question": "北苑店和南湖店的这两个呢？",
        "must": {
            "clarified": True,
            "not_multi_release": True,
            "no_product_release": True,
            "no_enumeration": True,
        },
    },
    {
        "id": "N2e_single_store_this_two_bounded",
        "cls": "N2 对照：单店 + 纯指代（门店维不得冒充多目标）",
        "question": "北苑店的这两个分别放在哪里？",
        "must": {
            "not_multi_release": True,
            "answer": True,
            "returned": 2,
            "present": ["一层东侧", "三层中庭"],
            "only_positions": ["一层东侧", "三层中庭"],
        },
    },
    # ---------------------------------------------------------------- A 正例
    {
        "id": "P1_two_stores_one_item",
        "cls": "A 正例：两店一物品",
        "question": "北苑店和南湖店的桌牌在哪里？",
        "must": {
            "multi_release": True,
            "answer": True,
            "returned": 2,
            "present": ["一层东侧", "二层西侧"],
            "only_positions": ["一层东侧", "二层西侧"],
        },
    },
    {
        "id": "P2_one_store_two_items",
        "cls": "A 正例：一店两物品",
        "question": "北苑店的桌牌和横幅在哪里？",
        "must": {
            "multi_release": True,
            "answer": True,
            "returned": 2,
            "present": ["一层东侧", "三层中庭"],
            "only_positions": ["一层东侧", "三层中庭"],
        },
    },
    {
        "id": "P3_two_stores_phone",
        "cls": "A 正例：两店电话",
        "question": "北苑店和南湖店的电话是多少？",
        "must": {
            "multi_release": True,
            "answer": True,
            "returned": 2,
            "phones": ["010-20000001", "010-20000002"],
            "no_positions": True,
        },
    },
    {
        "id": "P4_two_stores_one_item_fenbie",
        "cls": "A 正例：两店一物品 + 分别",
        "question": "北苑店和南湖店的桌牌分别在哪里？",
        "must": {
            "multi_release": True,
            "answer": True,
            "returned": 2,
            "present": ["一层东侧", "二层西侧"],
            "only_positions": ["一层东侧", "二层西侧"],
        },
    },
    # ------------------------------------------------ 新回归面 1：混合（1 显式 + 1 指代）
    {
        "id": "R1a_mixed_one_item_one_anaphora_single_store",
        "cls": "新回归面：混合（1 显式物品 + 指代，单店）",
        "question": "北苑店的桌牌和这两个分别放在哪里？",
        "must": {
            "not_multi_release": True,
            "no_whole_table": True,
            "answer": True,
            "returned": 1,
            "present": ["一层东侧"],
            "only_positions": ["一层东侧"],
        },
    },
    {
        "id": "R1b_mixed_one_item_one_anaphora_two_stores",
        "cls": "新回归面：混合（1 显式物品 + 指代，两店）",
        "question": "北苑店和南湖店的桌牌和这两个分别放在哪里？",
        "must": {
            "not_multi_release": True,
            "no_whole_table": True,
            "answer": True,
            "returned": 2,
            "present": ["一层东侧", "二层西侧"],
            "only_positions": ["一层东侧", "二层西侧"],
        },
    },
    {
        "id": "R1d_mixed_one_item_one_anaphora_no_enumerate_word",
        "cls": "新回归面：混合（1 显式物品 + 指代，无“分别”）",
        "question": "北苑店和南湖店的桌牌和这两个在哪里？",
        "must": {"not_multi_release": True, "no_whole_table": True},
    },
    {
        "id": "R1c_mixed_two_items_one_anaphora",
        "cls": "新回归面：混合（2 显式物品 + 指代）",
        "question": "北苑店的桌牌、横幅和这两个分别放在哪里？",
        "must": {"clarified": True, "item_ambiguous": True, "not_multi_release": True},
    },
    # ------------------------------------------------ 新回归面 2：跨轮指代
    {
        "id": "R2_cross_turn_two_stores_one_item",
        "cls": "新回归面：跨轮指代（上一轮两店一物品）",
        "turns": ["北苑店和南湖店的桌牌在哪里？", "这两个分别放在哪里？"],
        "must": {"clarified_or_bounded": True, "not_multi_release": True, "no_whole_table": True},
    },
    # ------------------------------------------------ 新回归面 3：指代 + 词表外门店
    {
        "id": "R3a_anaphora_unknown_store",
        "cls": "新回归面：指代 + 词表外门店",
        "question": "北苑店和西郊店的这两个分别放在哪里？",
        "must": {"clarified": True, "not_multi_release": True},
    },
    {
        "id": "R3b_explicit_unknown_store_no_anaphora",
        "cls": "对照：显式枚举 + 词表外门店（无指代）",
        "question": "北苑店和西郊店的桌牌在哪里？",
        "must": {"not_multi_release": True},
    },
    # ------------------------------------------------ 新回归面 4：显式枚举含歧义物品
    {
        "id": "R4a_explicit_two_by_two_item_ambiguous",
        "cls": "新回归面：显式枚举含歧义物品（两店×两物品）",
        "question": "北苑店和南湖店的桌牌和横幅在哪里？",
        "must": {"clarified": True, "item_ambiguous": True, "not_multi_release": True},
    },
    {
        "id": "R4b_anaphora_plus_item_ambiguity",
        "cls": "新回归面：指代 + 物品维歧义",
        "question": "北苑店的这两个和桌牌、横幅分别放在哪里？",
        "must": {"clarified": True, "item_ambiguous": True, "not_multi_release": True},
    },
    # ------------------------------------------------ null / bare
    {
        "id": "B1_bare_this_two",
        "cls": "bare 指代：这两个",
        "question": "这两个分别放在哪里？",
        "must": {"clarified": True, "missing_slot": True, "not_multi_release": True},
    },
    {
        "id": "B2_bare_this_two_phone",
        "cls": "bare 指代：这两个电话",
        "question": "这两个电话是多少？",
        "must": {"clarified": True, "missing_slot": True, "not_multi_release": True},
    },
    # ------------------------------------------------ 复指限定语（不得过度拦截）
    {
        "id": "S1_resumptive_items_this_two",
        "cls": "复指：前置枚举 + 这两个",
        "question": "北苑店的桌牌和横幅这两个分别放在哪里？",
        "must": {
            "multi_release": True,
            "answer": True,
            "returned": 2,
            "present": ["一层东侧", "三层中庭"],
            "only_positions": ["一层东侧", "三层中庭"],
        },
    },
    {
        "id": "S2_resumptive_items_this_two_noun",
        "cls": "复指：前置枚举 + 这两个物品",
        "question": "北苑店的桌牌和横幅这两个物品分别放在哪里？",
        "must": {"multi_release": True, "not_clarified": True},
    },
    {
        "id": "S3_resumptive_stores_these_two",
        "cls": "复指：两店 + 这两家",
        "question": "北苑店和南湖店这两家的电话是多少？",
        "must": {
            "multi_release": True,
            "answer": True,
            "returned": 2,
            "phones": ["010-20000001", "010-20000002"],
        },
    },
    # ------------------------------------------------ 相邻量化形式（残余观察，不计硬失败）
    {
        "id": "Z1_residual_colloquial_this_pair",
        "cls": "残余观察：这俩（不在本包正则内）",
        "question": "北苑店和南湖店的这俩分别放在哪里？",
        "residual": True,
        "must": {},
    },
    {
        "id": "Z2_residual_these",
        "cls": "残余观察：这些（不在本包正则内）",
        "question": "北苑店和南湖店的这些分别放在哪里？",
        "residual": True,
        "must": {},
    },
    {
        "id": "Z3_residual_digit_two",
        "cls": "残余观察：这2个（不在本包正则内）",
        "question": "北苑店和南湖店的这2个分别放在哪里？",
        "residual": True,
        "must": {},
    },
    # ------------------------------------------------ 相邻既有面（非本轮目标，观察用）
    {
        "id": "X1_policy_two_flows_no_context",
        "cls": "相邻观察：政策题含“这两个”",
        "question": "这两个流程要提前几天提报？",
        "must": {"not_multi_release": True},
    },
]

# 两轮用例的上一轮状态：先用内核跑第一轮，再把 state 交给 planner 对照。
CROSS_TURN = {"R2_cross_turn_two_stores_one_item"}


def main() -> int:
    pre_info = _reconstruct_pre_r1()
    pre_module = _load_pre_r1_module()

    tmp = Path(tempfile.mkdtemp(prefix="v3-fix1r1-"))
    config = RagConfig(
        provider_mode="offline",
        data_dir=tmp,
        business_date="2026-10-15",
        chunk_max_chars=420,
        chunk_max_units=3,
        chunk_overlap_units=1,
        top_k=5,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
    )
    index = RagIndex(tmp / "rag.sqlite3", config=config)
    items_doc = _doc("S01", "物料位置表")
    phone_doc = _doc("S02", "合作店家信息")
    index.add_document(items_doc, _units(items_doc, ITEM_ROWS, "物品位置"), embed=True)
    index.add_document(phone_doc, _units(phone_doc, PHONE_ROWS, "合作店家"), embed=True)

    rows: dict[str, Any] = {}
    failures: list[str] = []
    for case in CASES:
        case_id = case["id"]
        if case_id in CROSS_TURN:
            first_q, second_q = case["turns"]
            conversation_id = f"c-r1-{case_id}"
            first = _answer(index, first_q, f"{case_id}-t1", conversation_id=conversation_id)
            previous = QueryState.from_dict(first["state"])
            plan_current = _plan(current_query, second_q, previous=previous)
            plan_pre = _plan(pre_module, second_q, previous=previous)
            second = _answer(index, second_q, f"{case_id}-t2", conversation_id=conversation_id)
            answers = {"turn1": first, "turn2": second}
            legacy = None
        else:
            question = case["question"]
            plan_current = _plan(current_query, question)
            plan_pre = _plan(pre_module, question)
            answers = {"main": _answer(index, question, case_id)}
            legacy = _legacy(question)

        # 改前内核对照：只临时替换 answer 模块里引用的 parse_query，跑完立即恢复。
        pre_answers: dict[str, Any] | None = None
        original_parse = rag_answer.parse_query
        rag_answer.parse_query = pre_module.parse_query  # type: ignore[assignment]
        try:
            if case_id in CROSS_TURN:
                first_q, second_q = case["turns"]
                pre_conversation = f"c-r1-pre-{case_id}"
                pre_answers = {
                    "turn1": _answer(index, first_q, f"pre-{case_id}-t1", conversation_id=pre_conversation),
                    "turn2": _answer(index, second_q, f"pre-{case_id}-t2", conversation_id=pre_conversation),
                }
            else:
                pre_answers = {"main": _answer(index, case["question"], f"pre-{case_id}")}
        finally:
            rag_answer.parse_query = original_parse  # type: ignore[assignment]

        answer = answers.get("turn2") or answers["main"]
        checks: dict[str, bool] = {}
        must = case["must"]
        if must.get("clarified"):
            checks["planner_clarification"] = bool(plan_current["clarification"])
            checks["kernel_clarification"] = answer["kind"] == "clarification"
        if must.get("not_clarified"):
            checks["planner_not_clarified"] = not plan_current["clarification"]
        if must.get("multi_release"):
            checks["reason_multi"] = plan_current["reason"] == "MULTI_TARGET_ENUMERATE"
            checks["owns"] = plan_current["rag_owns_turn"] is True
        if must.get("not_multi_release"):
            checks["reason_not_multi"] = plan_current["reason"] != "MULTI_TARGET_ENUMERATE"
        if must.get("no_product_release"):
            checks["owns_false_or_clarified"] = (
                plan_current["rag_owns_turn"] is False or bool(plan_current["clarification"])
            )
        if must.get("clarified_or_bounded"):
            checks["clarified_or_bounded"] = (
                answer["kind"] in {"clarification", "not_found"}
                or (answer["kind"] == "answer" and (answer["returned"] or 0) <= 2)
            )
        if must.get("missing_slot"):
            checks["missing_slot"] = plan_current["reason"] == "MISSING_SLOT"
        if must.get("item_ambiguous"):
            checks["item_ambiguous"] = plan_current["reason"] == "ITEM_AMBIGUOUS"
        if must.get("answer"):
            checks["answer_kind"] = answer["kind"] == "answer"
        if "returned" in must:
            checks["returned"] = answer["returned"] == must["returned"]
        if must.get("only_positions"):
            checks["only_positions"] = _present_only(answer, must["only_positions"])
        if must.get("no_positions"):
            checks["no_positions"] = _absent_all(answer)
        for value in must.get("present", []):
            checks[f"present:{value}"] = answer["positions_present"].get(value, False)
        for value in must.get("phones", []):
            checks[f"phone:{value}"] = answer["phones_present"].get(value, False)
        if must.get("no_enumeration"):
            checks["no_positions"] = _absent_all(answer)
            checks["no_phone_values"] = not any(answer["phones_present"].values())
            checks["returned_none"] = answer["returned"] is None
        if must.get("no_whole_table"):
            table_values = [value for value in POSITIONS if value in answer["text"]]
            checks["not_all_four"] = len(table_values) < 4
        ok = all(checks.values())
        if not ok and not case.get("residual"):
            failures.append(case_id)
        rows[case_id] = {
            "class": case["cls"],
            "question": case.get("question") or case.get("turns"),
            "residual_observation": bool(case.get("residual")),
            "planner_current": plan_current,
            "planner_pre_r1": plan_pre,
            "changed_by_r1": plan_current != plan_pre,
            "product_gate_changed_by_r1": plan_current["rag_owns_turn"]
            != plan_pre["rag_owns_turn"],
            "answers": answers,
            "answers_pre_r1_kernel": pre_answers,
            "legacy_fallback": legacy,
            "checks": checks,
            "ok": ok,
        }

    index.close()

    # fix-1/A 之前的基线：证明 D1/D2 是既有有界作答，不是 fix-1/A 或 R1 引入。
    pre_fix1 = _load_pre_fix1_module()
    pre_fix1_baseline: dict[str, Any] = {}
    if pre_fix1 is not None:
        pre_fix1_sha = hashlib.sha256(PRE_FIX1_SOURCE.read_bytes()).hexdigest()
        questions = {
            "R1a_mixed_single_store": "北苑店的桌牌和这两个分别放在哪里？",
            "R1b_mixed_two_stores": "北苑店和南湖店的桌牌和这两个分别放在哪里？",
            "R2_cross_turn_turn2": "这两个分别放在哪里？",
        }
        original_parse = rag_answer.parse_query
        rag_answer.parse_query = pre_fix1.parse_query  # type: ignore[assignment]
        try:
            for key, question in questions.items():
                if key == "R2_cross_turn_turn2":
                    first_q = "北苑店和南湖店的桌牌在哪里？"
                    conversation = "c-r1-prefix1-cross"
                    first = _answer(index, first_q, "prefix1-t1", conversation_id=conversation)
                    previous = QueryState.from_dict(first["state"])
                    plan = _plan(pre_fix1, question, previous=previous)
                    answer = _answer(index, question, "prefix1-t2", conversation_id=conversation)
                else:
                    plan = _plan(pre_fix1, question)
                    answer = _answer(index, question, f"prefix1-{key}")
                pre_fix1_baseline[key] = {
                    "question": question,
                    "planner": plan,
                    "kernel": {
                        "kind": answer["kind"],
                        "returned": answer["returned"],
                        "text": answer["text"],
                    },
                }
        finally:
            rag_answer.parse_query = original_parse  # type: ignore[assignment]
        pre_fix1_baseline["source"] = {
            "path": str(PRE_FIX1_SOURCE.relative_to(REPO)).replace("\\", "/"),
            "sha256": pre_fix1_sha,
            "expected": PRE_FIX1_EXPECTED,
            "matches": pre_fix1_sha == PRE_FIX1_EXPECTED,
        }

    payload = {
        "schema_version": "v3-fix1r1-independent-probe/v0.1",
        "lexicon": {"stores": list(LEXICON.stores), "items": list(LEXICON.items)},
        "records": {"item_rows": ITEM_ROWS, "phone_rows": PHONE_ROWS},
        "pre_r1_reconstruction": pre_info,
        "pre_r1_planner_used_for_comparison": True,
        "pre_fix1_baseline": pre_fix1_baseline,
        "cases": rows,
        "failures": failures,
        "residuals": {
            key: {
                "question": value["question"],
                "current_reason": value["planner_current"]["reason"],
                "current_owns": value["planner_current"]["rag_owns_turn"],
                "pre_reason": value["planner_pre_r1"]["reason"],
                "pre_owns": value["planner_pre_r1"]["rag_owns_turn"],
                "kernel_kind": value["answers"]["main"]["kind"],
                "returned": value["answers"]["main"]["returned"],
            }
            for key, value in rows.items()
            if value["residual_observation"]
        },
        "outbound_attempts": OUTBOUND,
        "notes": [
            "问句、门店、物品、位置、电话全部为自建合成数据，不复用开发用例。",
            "N2 要求 planner 澄清 + 产品层不归内核 + 内核直接 ask 也澄清且不返回任何行。",
            "A 正例要求 MULTI_TARGET_ENUMERATE、answers 逐条、目标外行不进证据面。",
            "改前对照为 fix-1 终态（f73fc735）的 planner + _rag_owns_turn，用于区分新回归与既有行为。",
            "Z 系列为相邻量化形式的残余观察，不计入本轮硬失败；它们在本轮前后行为相同。",
            "pre_fix1_baseline 为 fix-1/A 之前的 5a7ed26b 基线，仅用于证明 D1/D2 非新回归。",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "pre_r1": pre_info,
        "failures": failures,
        "outbound_attempts": len(OUTBOUND),
        "cases": {
            key: {
                "ok": value["ok"],
                "current_reason": value["planner_current"]["reason"],
                "current_clarified": bool(value["planner_current"]["clarification"]),
                "current_owns": value["planner_current"]["rag_owns_turn"],
                "pre_reason": value["planner_pre_r1"]["reason"],
                "pre_owns": value["planner_pre_r1"]["rag_owns_turn"],
                "changed_by_r1": value["changed_by_r1"],
                "answer_kind": (value["answers"].get("turn2") or value["answers"]["main"])["kind"],
                "returned": (value["answers"].get("turn2") or value["answers"]["main"])["returned"],
            }
            for key, value in rows.items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if not failures and pre_info["matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
