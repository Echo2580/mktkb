"""fix-2 独立窄验收探针（本包自建，不复用开发用例的输入/断言）。

覆盖同一条机制的两个方向，全部离线（临时 SQLite + offline provider + socket 拦截）：
  A 类：本轮点名"2 门店 + 1 物品 + 记录字段"且题面顺带提及资料字样/回指词
        → 信息足够，必须直接作答（不得判澄清、不得交回 legacy）。
  A 反例：真歧义仍澄清（两店×两物品交叉 / 纯指代 / 词表外门店+纯指代 / 未收录资料）。
  B 类：首轮点名门店+物品、措辞不是字段词、句中有回指词
        → 命中作答（不得在检索前收口成"未记录该字段"）。
  B 反例：真无覆盖仍 not_found 且 0 引用不编造；追问口径不回退；首轮纯指代仍澄清。
  回归：fix-1 多目标枚举正例、fix-1r1 纯指代反例。

支持改前/改后对照：
  MKTKB_PROBE_SRC  覆盖 mktkb 包路径（指向"改前重建版"）；
  MKTKB_PROBE_OUT  覆盖输出 JSON 路径。
输出：independent-probe.json（机读）+ stdout 摘要。真实题面/答案未读取、未打印。
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[6]
_SRC = Path(os.environ.get("MKTKB_PROBE_SRC") or (_REPO / "backend" / "src")).resolve()
sys.path.insert(0, str(_SRC))

OUT = Path(os.environ.get("MKTKB_PROBE_OUT") or (_HERE / "independent-probe.json"))
OUTBOUND: list[str] = []


def _guard() -> None:
    def deny(*args: Any, **kwargs: Any) -> Any:
        OUTBOUND.append(f"blocked:{args!r}")
        raise OSError("netguard: outbound blocked")

    socket.socket.connect = deny  # type: ignore[assignment]
    socket.socket.connect_ex = deny  # type: ignore[assignment]
    socket.create_connection = deny  # type: ignore[assignment]
    socket.getaddrinfo = deny  # type: ignore[assignment]


from mktkb.conversations.service import _rag_owns_turn  # noqa: E402
from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402
from mktkb.rag.query import DocumentRef, Lexicon, parse_query  # noqa: E402
from mktkb.rag.types import QueryState  # noqa: E402

# 词表取自公开语料（fixtures/acceptance-h2v3 的记录身份），不含真实题面。
LEXICON = Lexicon(
    stores=("城东店", "城西店", "城北店"),
    items=("宣传海报", "易拉宝", "促销贴纸", "价签卡纸"),
    field_labels=("位置", "联系人", "电话", "地址"),
    documents=(
        DocumentRef(doc_id="0a11c0de-0000-4000-8000-0000000000d1", title="D01_物品位置表.xlsx"),
        DocumentRef(doc_id="0a11c0de-0000-4000-8000-0000000000d2", title="D02_合作店家信息.xlsx"),
        DocumentRef(doc_id="0a11c0de-0000-4000-8000-0000000000v7", title="V07_物料位置独立通知.pdf"),
    ),
)

# 自建记录：注意「城东店 + 价签卡纸」故意无记录（真无覆盖反例用）。
ROWS = [
    {"标识": "K01", "门店": "城东店", "物品": "宣传海报", "位置": "北区一排货架"},
    {"标识": "K02", "门店": "城西店", "物品": "宣传海报", "位置": "西区二排货架"},
    {"标识": "K03", "门店": "城东店", "物品": "易拉宝", "位置": "前台内侧墙面"},
    {"标识": "K04", "门店": "城西店", "物品": "易拉宝", "位置": "电梯口立柱"},
    {"标识": "K05", "门店": "城东店", "物品": "促销贴纸", "位置": "收银台正面"},
    {"标识": "K06", "门店": "城西店", "物品": "价签卡纸", "位置": "生鲜区端头"},
]
VALUES = [row["位置"] for row in ROWS]


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
    out = []
    for ordinal, row in enumerate(rows):
        out.append(
            AtomicUnit(
                unit_id=f"{doc.doc_id}-{ordinal}-{uuid.uuid4().hex[:6]}",
                doc_id=doc.doc_id,
                version_id=doc.version_id,
                kind="table_row",
                ordinal=ordinal,
                unit_key=f"sheet:{sheet}:row:{8 + ordinal}",
                text="；".join(f"{k}: {v}" for k, v in row.items()),
                fields=dict(row),
                sheet=sheet,
                locator={"sheet": sheet, "row": 8 + ordinal, "header_row": 7},
                row_number=8 + ordinal,
                title=doc.title,
            )
        )
    return out


def _planner_dict(plan: Any) -> dict[str, Any]:
    return {
        "mode": plan.mode,
        "reason": plan.reason,
        "clarification": plan.clarification,
        "enumerate": bool(plan.enumerate),
        "field_role": plan.field_role,
        "filters": dict(plan.filters),
        "stores": list(plan.state.stores or ()),
        "missing_stores": list(plan.missing_stores or ()),
        "turn": int(getattr(plan.state, "turn", 0) or 0),
        "rag_owns_turn": bool(_rag_owns_turn(QueryState(), plan)),
    }


def _ask(index: RagIndex, question: str, tag: str, conversation: str | None = None) -> dict[str, Any]:
    answer = index.ask(
        question, user_id="u-independent", conversation_id=conversation or f"c-{tag}"
    )
    text = str(answer.text or "")
    present = {value: (value in text) for value in VALUES}
    return {
        "kind": answer.kind,
        "reason": answer.reason,
        "returned": (answer.diagnostics or {}).get("returned"),
        "citations": len(answer.citations or ()),
        "values_present": present,
        "any_value_present": any(present.values()),
        "text_len": len(text),
    }


CASES: dict[str, dict[str, Any]] = {
    # ---------------- A 正例：信息足够 -> 直接作答
    "A1_doc_word_qingdan": {
        "group": "A_positive",
        "question": "城东店和城西店的易拉宝那个位置，查物料清单确认下",
        "expect": {
            "reason": "MULTI_TARGET_ENUMERATE",
            "clarification_none": True,
            "enumerate": True,
            "owns": True,
            "kind": "answer",
            "returned": 2,
            "present": ["前台内侧墙面", "电梯口立柱"],
            "absent": ["北区一排货架", "西区二排货架", "收银台正面", "生鲜区端头"],
        },
    },
    "A2_two_doc_codes": {
        "group": "A_positive",
        "question": "城东店和城西店的宣传海报那个位置在D01和D02里分别是怎么写的",
        "expect": {
            "reason": "MULTI_TARGET_ENUMERATE",
            "clarification_none": True,
            "enumerate": True,
            "owns": True,
            "kind": "answer",
            "returned": 2,
            "present": ["北区一排货架", "西区二排货架"],
            "absent": ["前台内侧墙面", "电梯口立柱"],
        },
    },
    "A3_doc_word_ziliao": {
        "group": "A_positive",
        "question": "城东店和城西店的宣传海报那个位置，对照存档资料核一下",
        "expect": {
            "reason": "MULTI_TARGET_ENUMERATE",
            "clarification_none": True,
            "enumerate": True,
            "owns": True,
            "kind": "answer",
            "returned": 2,
            "present": ["北区一排货架", "西区二排货架"],
            "absent": ["前台内侧墙面", "电梯口立柱"],
        },
    },
    "A4_contact_merge_refused": {
        "group": "A_positive_security",
        "question": "城东店和城西店的易拉宝那个位置，连门店的联系电话一起发我",
        "expect": {
            "reason": "SECURITY_RESTRICTED_CONTACT",
            "clarification_none": True,
            "owns": True,
            "kind": "no_answer",
            "no_values": True,
            "citations": 0,
        },
    },
    # ---------------- A 反例：真歧义仍澄清
    "N1_two_stores_two_items": {
        "group": "A_negative",
        "question": "城东店和城西店的易拉宝和宣传海报分别摆在哪",
        "expect": {
            "clarification_required": True,
            "owns": False,
            "kind": "clarification",
            "no_values": True,
        },
    },
    "N2_bare_anaphora": {
        "group": "A_negative",
        "question": "城东店和城西店的这两个分别摆在哪",
        "expect": {
            "clarification_required": True,
            "owns": False,
            "kind": "clarification",
            "no_values": True,
        },
    },
    "N3_unknown_store_anaphora": {
        "group": "A_negative",
        "question": "城东店和郊野店的这几个分别摆在哪",
        "expect": {
            "clarification_required": True,
            "owns": False,
            "kind": "clarification",
            "no_values": True,
        },
    },
    "N4_missing_document_still": {
        "group": "A_negative",
        "question": "促销活动台账在哪",
        "expect": {
            "reason": "DOCUMENT_NOT_FOUND",
            "clarification_required": True,
            "owns": False,
        },
    },
    # ---------------- B 正例：显式实体 -> 命中作答
    "B1_first_turn_explicit": {
        "group": "B_positive",
        "question": "城东店的易拉宝那个张贴要求是怎么说的",
        "expect": {
            "reason_not": "ANAPHORA_NEW_CONTENT",
            "clarification_none": True,
            "enumerate": True,
            "owns": True,
            "kind": "answer",
            "citations_min": 1,
            "present": ["前台内侧墙面"],
            "absent": ["电梯口立柱", "生鲜区端头"],
        },
    },
    "B2_first_turn_explicit": {
        "group": "B_positive",
        "question": "城西店的易拉宝那个补给节奏如何安排",
        "expect": {
            "reason_not": "ANAPHORA_NEW_CONTENT",
            "clarification_none": True,
            "enumerate": True,
            "owns": True,
            "kind": "answer",
            "citations_min": 1,
            "present": ["电梯口立柱"],
            "absent": ["前台内侧墙面"],
        },
    },
    # ---------------- B 反例：真无覆盖 / 追问口径
    "B3_no_coverage_not_found": {
        "group": "B_negative",
        "question": "城东店的价签卡纸那个张贴要求是怎么说的",
        "expect": {"kind": "no_answer", "citations": 0, "no_values": True},
    },
    "B4_followup_collapse_kept": {
        "group": "B_negative",
        "question": "城东店的易拉宝在哪里？",
        "followup": "城东店的易拉宝那个印刷材质呢",
        "expect": {"kind": "answer"},
        "followup_expect": {
            "kind": "no_answer",
            "reason": "ANAPHORA_NEW_CONTENT",
            "citations": 0,
            "no_values": True,
        },
    },
    "B5_first_turn_bare_anaphora": {
        "group": "B_negative",
        "question": "这两个分别摆在哪",
        "expect": {"kind": "clarification", "no_values": True},
    },
    # ---------------- 回归
    "R1_fix1_multi_target": {
        "group": "regression_fix1",
        "question": "城东店和城西店的宣传海报分别摆在哪",
        "expect": {
            "reason": "MULTI_TARGET_ENUMERATE",
            "owns": True,
            "kind": "answer",
            "returned": 2,
            "present": ["北区一排货架", "西区二排货架"],
        },
    },
    "R2_fix1r1_pure_anaphora_with_store_pair": {
        "group": "regression_fix1r1",
        "question": "城东店和城西店的这几个分别摆在哪",
        "expect": {
            "reason": "MULTIPLE_ENTITIES",
            "clarification_required": True,
            "owns": False,
            "kind": "clarification",
            "no_values": True,
        },
    },
    "R3_fix1_anaphora_they_planner": {
        # 「它们」不是量化指代，fix-1/A 的 N5 只断言"不按多目标放行、不归内核"。
        # 本包按同一口径断言，并如实记录 legacy 侧结局（不宣称它被澄清）。
        "group": "regression_fix1",
        "question": "城东店和城西店的它们分别摆在哪",
        "expect": {"reason_not": "MULTI_TARGET_ENUMERATE", "owns": False},
    },
}


def _check(planner: dict[str, Any], e2e: dict[str, Any], exp: dict[str, Any]) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    if "reason" in exp:
        checks["reason"] = planner["reason"] == exp["reason"]
    if "reason_not" in exp:
        checks["reason_not"] = planner["reason"] != exp["reason_not"]
    if "clarification_none" in exp:
        checks["clarification_none"] = planner["clarification"] is None
    if "clarification_required" in exp:
        checks["clarification_required"] = bool(planner["clarification"])
    if "enumerate" in exp:
        checks["enumerate"] = planner["enumerate"] == exp["enumerate"]
    if "owns" in exp:
        checks["owns"] = planner["rag_owns_turn"] == exp["owns"]
    if "kind" in exp:
        checks["kind"] = e2e["kind"] == exp["kind"]
    if "returned" in exp:
        checks["returned"] = e2e["returned"] == exp["returned"]
    if "citations" in exp:
        checks["citations"] = e2e["citations"] == exp["citations"]
    if "citations_min" in exp:
        checks["citations_min"] = e2e["citations"] >= exp["citations_min"]
    for value in exp.get("present", []):
        checks[f"present:{value}"] = bool(e2e["values_present"].get(value))
    for value in exp.get("absent", []):
        checks[f"absent:{value}"] = not e2e["values_present"].get(value)
    if exp.get("no_values"):
        checks["no_values"] = not e2e["any_value_present"]
    return checks


def main() -> int:
    _guard()
    tmp = Path(tempfile.mkdtemp(prefix="v3-fix2-indep-"))
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
    doc = _doc("0a11c0de-0000-4000-8000-0000000000d1", "D01_物品位置表.xlsx")
    index.add_document(doc, _units(doc, ROWS, "物品位置"), embed=True)

    rows: dict[str, Any] = {}
    failures: list[str] = []
    try:
        for name, case in CASES.items():
            first_plan = parse_query(
                case["question"], previous=None, lexicon=LEXICON, business_date="2026-10-15"
            )
            planner = _planner_dict(first_plan)
            e2e = _ask(index, case["question"], name)
            checks = _check(planner, e2e, case["expect"])
            followup = None
            if case.get("followup"):
                # 同一会话 + 上一轮 state：才等价于线上"追问"轮。
                f_plan_obj = parse_query(
                    case["followup"],
                    previous=first_plan.state,
                    lexicon=LEXICON,
                    business_date="2026-10-15",
                )
                f_planner = _planner_dict(f_plan_obj)
                f_e2e = _ask(index, case["followup"], name, conversation=f"c-{name}")
                checks.update(
                    {f"f_{k}": v for k, v in _check(f_planner, f_e2e, case["followup_expect"]).items()}
                )
                followup = {"question": case["followup"], "planner": f_planner, "e2e": f_e2e}
            ok = all(checks.values())
            if not ok:
                failures.append(name)
            rows[name] = {
                "group": case["group"],
                "question": case["question"],
                "planner": planner,
                "e2e": e2e,
                "followup": followup,
                "checks": checks,
                "failed_checks": [k for k, v in checks.items() if not v],
                "ok": ok,
            }
    finally:
        index.close()

    summary: dict[str, dict[str, Any]] = {}
    for group in sorted({c["group"] for c in CASES.values()}):
        members = [rows[n] for n, c in CASES.items() if c["group"] == group]
        summary[group] = {
            "cases": len(members),
            "passed": sum(1 for m in members if m["ok"]),
            "failed": [m["question"] for m in members if not m["ok"]],
        }

    payload = {
        "schema_version": "v3-fix2-independent-probe/v0.1",
        "src_used": str(_SRC),
        "lexicon": {"stores": list(LEXICON.stores), "items": list(LEXICON.items)},
        "records": ROWS,
        "cases": rows,
        "groups": summary,
        "failures": failures,
        "cases_total": len(CASES),
        "cases_passed": sum(1 for r in rows.values() if r["ok"]),
        "outbound_attempts": OUTBOUND,
        "notes": [
            "本包自建问句与记录值，未复用开发用例的输入/断言；未读取真实 H2 题面/答案。",
            "A 类正例必须 MULTI_TARGET_ENUMERATE + 内核作答 + 只含目标内取值。",
            "A/B 反例要求真歧义仍澄清、真无覆盖仍 not_found 且零引用零取值。",
            "B4 为多轮：第 2 轮追问口径必须仍是 ANAPHORA_NEW_CONTENT 收口。",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")

    brief = {
        n: {
            "ok": r["ok"],
            "reason": r["planner"]["reason"],
            "clar": bool(r["planner"]["clarification"]),
            "owns": r["planner"]["rag_owns_turn"],
            "kind": r["e2e"]["kind"],
            "returned": r["e2e"]["returned"],
            "cites": r["e2e"]["citations"],
            "failed": r["failed_checks"],
        }
        for n, r in rows.items()
    }
    print(json.dumps({"groups": summary, "failures": failures, "cases": brief,
                      "outbound_attempts": len(OUTBOUND)}, ensure_ascii=False, indent=1))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
