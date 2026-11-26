"""独立验收 A：planner 单轮多目标（自建正例 + 自建 ≥4 类真歧义反例）。

零真实调用：临时 SQLite + offline provider + 纯函数；socket 出站全部拦截并计数。
不读取真实 H2 题面/答案；全部为合成问句与合成记录。
"""
from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(REPO / "backend" / "src"))

OUT = Path(__file__).resolve().parent / "A-planner-multi-target.json"
OUTBOUND: list[str] = []


def _guard() -> None:
    def deny(*args: Any, **kwargs: Any) -> Any:
        OUTBOUND.append(f"connect:{args!r}")
        raise OSError("netguard: outbound blocked")

    socket.socket.connect = deny  # type: ignore[assignment]
    socket.socket.connect_ex = deny  # type: ignore[assignment]
    socket.create_connection = deny  # type: ignore[assignment]
    socket.getaddrinfo = deny  # type: ignore[assignment]


from mktkb.conversations.service import _rag_owns_turn  # noqa: E402
from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402
from mktkb.rag.chunking import effective_dates  # noqa: E402
from mktkb.rag.query import Lexicon, parse_query  # noqa: E402
from mktkb.rag.types import QueryState  # noqa: E402

LEXICON = Lexicon(
    stores=("城东店", "城西店", "城北店"),
    items=("宣传海报", "易拉宝", "展架"),
    field_labels=("位置", "电话"),
)

POSITION_ROWS = [
    {"标识": "Q01", "门店": "城东店", "物品": "宣传海报", "位置": "A区1号架"},
    {"标识": "Q02", "门店": "城西店", "物品": "宣传海报", "位置": "B区2号架"},
    {"标识": "Q03", "门店": "城东店", "物品": "易拉宝", "位置": "C区门口"},
    {"标识": "Q04", "门店": "城西店", "物品": "易拉宝", "位置": "D区立柱"},
    {"标识": "Q05", "门店": "城北店", "物品": "展架", "位置": "E区仓库"},
]
PHONE_ROWS = [
    {"标识": "R01", "门店": "城东店", "联系人": "甲", "电话": "010-11110001"},
    {"标识": "R02", "门店": "城西店", "联系人": "乙", "电话": "010-11110002"},
]


def _plan(question: str) -> dict[str, Any]:
    plan = parse_query(question, previous=None, lexicon=LEXICON, business_date="2026-10-15")
    return {
        "mode": plan.mode,
        "reason": plan.reason,
        "clarification": plan.clarification,
        "enumerate": bool(plan.enumerate),
        "field_role": plan.field_role,
        "filters": dict(plan.filters),
        "stores": list(plan.state.stores),
        "items": list(getattr(plan.state, "items", ()) or ()),
        "missing_stores": list(plan.missing_stores),
        "pending_slot": plan.state.pending_slot,
        "rag_owns_turn": bool(_rag_owns_turn(QueryState(), plan)),
    }


def _doc(title: str, doc_id: str) -> DocumentSpec:
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
        body = "；".join(f"{k}: {v}" for k, v in row.items())
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


def _ask(index: RagIndex, question: str, tag: str) -> dict[str, Any]:
    answer = index.ask(question, user_id="u-independent", conversation_id=f"c-{tag}")
    text = str(answer.text or "")
    return {
        "kind": answer.kind,
        "reason": answer.reason,
        "returned": answer.diagnostics.get("returned") if answer.diagnostics else None,
        "text": text,
        "citations": len(answer.citations or ()),
        "values_present": {
            "A区1号架": "A区1号架" in text,
            "B区2号架": "B区2号架" in text,
            "C区门口": "C区门口" in text,
            "D区立柱": "D区立柱" in text,
            "E区仓库": "E区仓库" in text,
            "010-11110001": "010-11110001" in text,
            "010-11110002": "010-11110002" in text,
            "城南店": "城南店" in text,
        },
    }


def main() -> int:
    _guard()
    tmp = Path(tempfile.mkdtemp(prefix="v3-fix1-A-"))
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
    pos = _doc("物品位置表", "D01")
    phone = _doc("合作店家信息", "D02")
    index.add_document(pos, _units(pos, POSITION_ROWS, "物品位置"), embed=True)
    index.add_document(phone, _units(phone, PHONE_ROWS, "合作店家"), embed=True)

    cases = {
        "P1_two_stores_one_item": {
            "question": "城东店和城西店的宣传海报在哪里？",
            "expect": {"reason": "MULTI_TARGET_ENUMERATE", "clarification": None,
                       "enumerate": True, "owns": True,
                       "answer_kind": "answer", "returned": 2,
                       "present": ["A区1号架", "B区2号架"],
                       "absent": ["C区门口", "D区立柱"]},
        },
        "P2_one_store_two_items": {
            "question": "城东店的宣传海报和易拉宝在哪里？",
            "expect": {"reason": "MULTI_TARGET_ENUMERATE", "clarification": None,
                       "enumerate": True, "owns": True,
                       "answer_kind": "answer", "returned": 2,
                       "present": ["A区1号架", "C区门口"],
                       "absent": ["B区2号架", "D区立柱"]},
        },
        "P3_two_stores_phone": {
            "question": "城东店和城西店的电话是多少？",
            "expect": {"reason": "MULTI_TARGET_ENUMERATE", "clarification": None,
                       "enumerate": True, "owns": True,
                       "answer_kind": "answer", "returned": 2,
                       "present": ["010-11110001", "010-11110002"], "absent": []},
        },
        "N1_two_stores_two_items_cross": {
            "question": "城东店和城西店的宣传海报和易拉宝在哪里？",
            "expect": {"reason": "ITEM_AMBIGUOUS", "clarification": "required",
                       "enumerate": False, "owns": False, "answer_kind": "clarification"},
        },
        "N1b_cross_with_store_per_item": {
            "question": "城东店的宣传海报和城西店的易拉宝在哪里？",
            "expect": {"reason": "ITEM_AMBIGUOUS", "clarification": "required",
                       "enumerate": False, "owns": False, "answer_kind": "clarification"},
        },
        "N2_pure_anaphora_this_two": {
            "question": "城东店和城西店的这两个分别放在哪里？",
            "expect": {"reason": "NOT_MULTI", "clarification": "required",
                       "owns": False, "answer_kind": "clarification"},
        },
        "N2b_pure_anaphora_these": {
            "question": "城东店和城西店的这几个分别放在哪里？",
            "expect": {"reason": "NOT_MULTI", "clarification": "required",
                       "owns": False, "answer_kind": "clarification"},
        },
        "N2c_pure_anaphora_bare": {
            "question": "这两个分别放在哪里？",
            "expect": {"reason": "NOT_MULTI", "clarification": "required",
                       "owns": False, "answer_kind": "clarification"},
        },
        "N3_unknown_store": {
            "question": "城东店和城南店的宣传海报在哪里？",
            "expect": {"reason": "NOT_MULTI", "owns": False,
                       "missing_contains": "城南店", "enumerate": False,
                       "absent": ["城南店"]},
        },
        "N4_no_field_role": {
            "question": "城东店和城西店的宣传海报和易拉宝",
            "expect": {"reason": "NOT_MULTI", "owns": False, "enumerate": False},
        },
        "N5_anaphora_they": {
            "question": "城东店和城西店的它们分别放在哪里？",
            "expect": {"reason": "NOT_MULTI", "owns": False},
        },
        "N6_two_by_two_with_enumerate_word": {
            "question": "城东店和城西店的宣传海报和易拉宝分别在哪里？",
            "expect": {"reason": "ITEM_AMBIGUOUS", "clarification": "required",
                       "owns": False, "answer_kind": "clarification"},
        },
        "P4_two_stores_one_item_enumerate_word": {
            "question": "城东店和城西店的宣传海报分别在哪里？",
            "expect": {"reason": "MULTI_TARGET_ENUMERATE", "clarification": None,
                       "enumerate": True, "owns": True,
                       "answer_kind": "answer", "returned": 2,
                       "present": ["A区1号架", "B区2号架"],
                       "absent": ["C区门口", "D区立柱"]},
        },
    }

    rows: dict[str, Any] = {}
    failures: list[str] = []
    for name, case in cases.items():
        q = case["question"]
        planner = _plan(q)
        e2e = _ask(index, q, name)
        exp = case["expect"]
        checks: dict[str, bool] = {}
        if "reason" in exp:
            checks["reason"] = (planner["reason"] != "MULTI_TARGET_ENUMERATE"
                                if exp["reason"] == "NOT_MULTI"
                                else planner["reason"] == exp["reason"])
        if "clarification" in exp:
            if exp["clarification"] == "required":
                checks["clarification"] = bool(planner["clarification"])
            else:
                checks["clarification"] = planner["clarification"] == exp["clarification"]
        if "enumerate" in exp:
            checks["enumerate"] = planner["enumerate"] == exp["enumerate"]
        if "owns" in exp:
            checks["owns"] = planner["rag_owns_turn"] == exp["owns"]
        if "missing_contains" in exp:
            checks["missing"] = exp["missing_contains"] in planner["missing_stores"]
        if "answer_kind" in exp:
            checks["answer_kind"] = e2e["kind"] == exp["answer_kind"]
        if "returned" in exp:
            checks["returned"] = e2e["returned"] == exp["returned"]
        for value in exp.get("present", []):
            checks[f"present:{value}"] = e2e["values_present"].get(value, False)
        for value in exp.get("absent", []):
            checks[f"absent:{value}"] = not e2e["values_present"].get(value, True)
        ok = all(checks.values())
        if not ok:
            failures.append(name)
        rows[name] = {"question": q, "planner": planner, "e2e": e2e,
                      "checks": checks, "ok": ok}

    index.close()
    payload = {
        "schema_version": "v3-fix1-independent-A/v0.1",
        "lexicon": {"stores": list(LEXICON.stores), "items": list(LEXICON.items)},
        "cases": rows,
        "failures": failures,
        "outbound_attempts": OUTBOUND,
        "notes": [
            "P1/P2/P3 为自建正例：要求 MULTI_TARGET_ENUMERATE、答案逐条、证据面只含目标内行。",
            "N1/N1b/N3/N4/N5 为自建真歧义/拒绝面；N2 系自建纯指代类（'这两个/这几个'）。",
            "所有记录与问句均为合成，不含真实 H2 题面/答案。",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({"failures": failures,
                      "cases": {k: {"ok": v["ok"], "planner_reason": v["planner"]["reason"],
                                    "e2e_kind": v["e2e"]["kind"], "returned": v["e2e"]["returned"]}
                                for k, v in rows.items()},
                      "outbound_attempts": len(OUTBOUND)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
