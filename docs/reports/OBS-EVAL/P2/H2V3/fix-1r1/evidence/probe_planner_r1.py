"""v3-fix-1/R1 纯指代假放行：改前/改后同输入对照探针（离线，零真实调用）。

对照两臂：
- baseline：fix-1/A 之前的 ``query.py``（由独立验收反向还原、SHA 5a7ed26b…，只读复用）；
- current：本工作树的 ``query.py``（运行时 = 本次改动前或改动后，取决于执行时机）。

每个用例记录：两臂的 planner 计划、产品层 ``_rag_owns_turn`` 路由、legacy 意图层澄清、
以及两臂在合成 offline 索引上的内核直答（``RagIndex.ask``）。问句/记录全部为合成数据，
不读真实 H2 题面/答案；不建产品库、不调模型/embedding/rerank、不发外部请求。

网络口径：导入即删除全部代理环境变量；socket 外部出站一律拦截并计数，回环放行并计数；
四个正对照（DNS / 直连 / urllib ProxyHandler({}) / httpx trust_env=False）先跑并记录。

用法：
    python probe_planner_r1.py <输出 JSON 路径>
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
sys.path.insert(0, str(REPO / "backend" / "src"))
BASELINE = (
    REPO
    / "docs"
    / "reports"
    / "OBS-EVAL"
    / "P2"
    / "H2V3"
    / "fix-1"
    / "independent"
    / "_reconstructed_query.py"
)
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "planner-before-after.json"

EXTERNAL: list[dict[str, str]] = []
LOOPBACK: list[dict[str, str]] = []
CONTROLS: list[dict[str, object]] = []

_ORIG_CONNECT = socket.socket.connect
_ORIG_CONNECT_EX = socket.socket.connect_ex
_ORIG_CREATE_CONNECTION = socket.create_connection
_ORIG_GETADDRINFO = socket.getaddrinfo
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def _strip_proxy_env() -> list[str]:
    removed: list[str] = []
    for key in list(os.environ):
        lowered = key.lower()
        if lowered.endswith("_proxy") or lowered in {
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
        }:
            os.environ.pop(key, None)
            removed.append(key)
    return removed


REMOVED_ENV = _strip_proxy_env()


def _is_loopback(address: object) -> bool:
    if isinstance(address, (str, bytes)):
        return True
    if isinstance(address, tuple) and address:
        host = str(address[0]).strip().lower()
        return host in _LOOPBACK_HOSTS or host.startswith("127.")
    return False


def _deny(kind: str, detail: object) -> None:
    EXTERNAL.append({"kind": kind, "detail": str(detail)[:200]})
    raise OSError(f"netguard: {kind} blocked")


def _install_guard() -> None:
    def connect(self, address):  # noqa: ANN001
        if _is_loopback(address):
            LOOPBACK.append({"kind": "socket.connect", "detail": str(address)[:120]})
            return _ORIG_CONNECT(self, address)
        _deny("socket.connect", address)

    def connect_ex(self, address):  # noqa: ANN001
        if _is_loopback(address):
            LOOPBACK.append({"kind": "socket.connect_ex", "detail": str(address)[:120]})
            return _ORIG_CONNECT_EX(self, address)
        _deny("socket.connect_ex", address)

    def create_connection(address, *args, **kwargs):  # noqa: ANN002, ANN003
        if _is_loopback(address):
            LOOPBACK.append({"kind": "socket.create_connection", "detail": str(address)[:120]})
            return _ORIG_CREATE_CONNECTION(address, *args, **kwargs)
        _deny("socket.create_connection", address)

    def getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if _is_loopback((host, port)):
            LOOPBACK.append({"kind": "socket.getaddrinfo", "detail": f"{host}:{port}"})
            return _ORIG_GETADDRINFO(host, port, *args, **kwargs)
        _deny("socket.getaddrinfo", (host, port))

    socket.socket.connect = connect  # type: ignore[assignment]
    socket.socket.connect_ex = connect_ex  # type: ignore[assignment]
    socket.create_connection = create_connection  # type: ignore[assignment]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]


def _control(name: str, fn) -> dict[str, object]:  # noqa: ANN001
    before = len(EXTERNAL)
    blocked = False
    error = ""
    try:
        fn()
    except BaseException as exc:  # noqa: BLE001 - 正对照只关心“出不去”
        blocked = True
        error = f"{type(exc).__name__}: {exc}"
    return {
        "probe": name,
        "blocked": blocked,
        "attempts": len(EXTERNAL) - before,
        "error": error[:160],
    }


def _run_controls() -> None:
    import httpx
    import urllib.request

    CONTROLS.extend(
        [
            _control("dns", lambda: socket.getaddrinfo("example.invalid", 80)),
            _control("direct", lambda: socket.create_connection(("192.0.2.1", 80), timeout=0.2)),
            _control(
                "urllib",
                lambda: urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                    "http://example.invalid/", timeout=0.2
                ),
            ),
            _control(
                "httpx",
                lambda: httpx.Client(trust_env=False, timeout=0.2).get("http://example.invalid/"),
            ),
        ]
    )


_install_guard()
_run_controls()
_CONTROL_ATTEMPTS = len(EXTERNAL)


def _load_baseline():
    if not BASELINE.exists():
        raise SystemExit(f"missing baseline: {BASELINE}")
    spec = importlib.util.spec_from_file_location("mktkb.rag.query_baseline", BASELINE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["mktkb.rag.query_baseline"] = module
    spec.loader.exec_module(module)
    return module


baseline = _load_baseline()

from mktkb.conversations import intent as legacy_intent  # noqa: E402
from mktkb.conversations.service import _rag_owns_turn  # noqa: E402
from mktkb.rag import AtomicUnit, DocumentSpec, RagConfig, RagIndex  # noqa: E402
from mktkb.rag import answer as rag_answer  # noqa: E402
from mktkb.rag import query as current  # noqa: E402
from mktkb.rag.types import QueryState  # noqa: E402

LEXICON = current.Lexicon(
    stores=("城东店", "城西店", "城北店"),
    items=("宣传海报", "易拉宝", "展架"),
    field_labels=("位置", "电话"),
)
ENTITY_LEXICON = legacy_intent.EntityLexicon(
    store_labels=("城东店", "城西店", "城北店"),
    item_labels=("宣传海报", "易拉宝", "展架"),
    alias_to_labels={},
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

CASES: dict[str, dict[str, Any]] = {
    "P1_two_stores_one_item": {
        "class": "A 正例：两店一物品",
        "question": "城东店和城西店的宣传海报在哪里？",
    },
    "P2_one_store_two_items": {
        "class": "A 正例：一店两物品",
        "question": "城东店的宣传海报和易拉宝在哪里？",
    },
    "P3_two_stores_phone": {
        "class": "A 正例：两店门店级字段（电话）",
        "question": "城东店和城西店的电话是多少？",
    },
    "P4_two_stores_one_item_enumerate_word": {
        "class": "A 正例：两店一物品 + 分别",
        "question": "城东店和城西店的宣传海报分别在哪里？",
    },
    "C1a_anaphora_this_two_with_stores": {
        "class": "反例1：纯指代 + 已点名门店（这两个）",
        "question": "城东店和城西店的这两个分别放在哪里？",
    },
    "C1b_anaphora_these_with_stores": {
        "class": "反例1：纯指代 + 已点名门店（这几个）",
        "question": "城东店和城西店的这几个分别放在哪里？",
    },
    "C1c_anaphora_they_with_stores": {
        "class": "反例1 对照：既有指代词（它们）",
        "question": "城东店和城西店的它们分别放在哪里？",
    },
    "C1d_resumptive_this_two_stores": {
        "class": "反例1 对照：复指限定语（这两个店 + 显式枚举）",
        "question": "城东店和城西店这两个店的宣传海报在哪里？",
    },
    "C2_anaphora_bare": {
        "class": "反例2：纯指代 + 未点名",
        "question": "这两个分别放在哪里？",
    },
    "C3a_mixed_item_dimension": {
        "class": "反例3：混合（显式物品 + 指代，物品维）",
        "question": "城东店的宣传海报、易拉宝和这两个分别放在哪里？",
    },
    "C3b_mixed_store_dimension": {
        "class": "反例3：混合（显式物品 + 指代，门店维）",
        "question": "城东店和城西店的宣传海报和这两个分别放在哪里？",
    },
    "C4a_cross_turn_turn1": {
        "class": "反例4：跨轮指代（上一轮显式多目标）",
        "question": "城东店和城西店的宣传海报在哪里？",
    },
    "C4b_cross_turn_turn2": {
        "class": "反例4：跨轮指代（本轮纯指代）",
        "question": "这两个分别放在哪里？",
        "previous_case": "C4a_cross_turn_turn1",
    },
    "C5a_anaphora_unknown_store": {
        "class": "反例5：指代 + 词表外门店（城东店 + 城南店）",
        "question": "城东店和城南店的这两个分别放在哪里？",
    },
    "C5b_explicit_unknown_store": {
        "class": "反例5 对照：显式枚举 + 词表外门店（无指代）",
        "question": "城东店和城南店的宣传海报在哪里？",
    },
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


def _build_index(root: Path) -> RagIndex:
    config = RagConfig(
        provider_mode="offline",
        data_dir=root,
        business_date="2026-10-15",
        chunk_max_chars=420,
        chunk_max_units=3,
        chunk_overlap_units=1,
        top_k=5,
        page_size=10,
        vector_candidate_limit=50,
        rerank_top_n=20,
    )
    index = RagIndex(root / "rag.sqlite3", config=config)
    position = _doc("物品位置表", "D01")
    phone = _doc("合作店家信息", "D02")
    index.add_document(position, _units(position, POSITION_ROWS, "物品位置"), embed=True)
    index.add_document(phone, _units(phone, PHONE_ROWS, "合作店家"), embed=True)
    return index


def _ask(index: RagIndex, question: str, tag: str, *, turns: int = 1) -> dict[str, Any]:
    answer = None
    for _ in range(turns):
        answer = index.ask(question, user_id="u-r1", conversation_id=f"c-{tag}")
    assert answer is not None
    text = str(answer.text or "")
    return {
        "kind": answer.kind,
        "reason": answer.reason,
        "returned": (answer.diagnostics or {}).get("returned"),
        "citations": len(answer.citations or ()),
        "text": text,
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="v3-fix1r1-"))
    index = _build_index(tmp)

    # 先算纯函数计划（跨轮用例需要上一轮 QueryState）。
    plans: dict[str, dict[str, Any]] = {}
    for name, case in CASES.items():
        question = case["question"]
        previous_name = case.get("previous_case")
        baseline_previous = (
            QueryState.from_dict(plans[previous_name]["baseline"]["state_dict"])
            if previous_name
            else none_state()
        )
        current_previous = (
            QueryState.from_dict(plans[previous_name]["current"]["state_dict"])
            if previous_name
            else none_state()
        )
        baseline_plan = benchmark_plan(baseline, question, baseline_previous)
        current_plan = benchmark_plan(current, question, current_previous)
        plans[name] = {
            "class": case["class"],
            "question": question,
            "baseline": baseline_plan,
            "current": current_plan,
            "legacy_intent": {
                "clarification": legacy_intent.parse_question(
                    question, lexicon=ENTITY_LEXICON
                ).clarification
            },
        }

    # 再跑内核直答（两臂各用独立会话；跨轮按同一会话请求两次）。
    baseline_parse = rag_answer.parse_query
    for name, case in CASES.items():
        if case.get("previous_case"):
            continue
        question = case["question"]
        rag_answer.parse_query = baseline.parse_query  # type: ignore[assignment]
        try:
            plans[name]["baseline"]["kernel_ask"] = _ask(
                index, question, f"base-{name}", turns=1
            )
        finally:
            rag_answer.parse_query = baseline_parse  # type: ignore[assignment]
        plans[name]["current"]["kernel_ask"] = _ask(
            index, question, f"cur-{name}", turns=1
        )

    # 跨轮：同一会话先问上一轮，再问本轮；两臂分别会话。
    cross = CASES["C4b_cross_turn_turn2"]["question"]
    prior = CASES["C4a_cross_turn_turn1"]["question"]
    rag_answer.parse_query = baseline.parse_query  # type: ignore[assignment]
    try:
        plans["C4a_cross_turn_turn1"]["baseline"]["kernel_ask"] = _ask(
            index, prior, "base-cross", turns=1
        )
        plans["C4b_cross_turn_turn2"]["baseline"]["kernel_ask"] = _ask(
            index, cross, "base-cross", turns=1
        )
    finally:
        rag_answer.parse_query = baseline_parse  # type: ignore[assignment]
    plans["C4a_cross_turn_turn1"]["current"]["kernel_ask"] = _ask(
        index, prior, "cur-cross", turns=1
    )
    plans["C4b_cross_turn_turn2"]["current"]["kernel_ask"] = _ask(
        index, cross, "cur-cross", turns=1
    )

    index.close()

    summary = {
        "baseline_source": {
            "path": str(BASELINE),
            "exists": BASELINE.exists(),
            "sha256": _sha256(BASELINE) if BASELINE.exists() else None,
        },
        "code_under_test": {
            "backend/src/mktkb/rag/query.py": _sha256(
                REPO / "backend" / "src" / "mktkb" / "rag" / "query.py"
            ),
            "backend/src/mktkb/conversations/service.py": _sha256(
                REPO / "backend" / "src" / "mktkb" / "conversations" / "service.py"
            ),
        },
        "questions_are_synthetic": True,
        "real_h2_surface_read": False,
        "proxy_env_removed": sorted(REMOVED_ENV),
        "positive_controls": CONTROLS,
        "all_controls_blocked": all(bool(item["blocked"]) for item in CONTROLS),
        "external_attempts_total": len(EXTERNAL),
        "external_attempts_during_probe": len(EXTERNAL) - _CONTROL_ATTEMPTS,
        "external_attempts": EXTERNAL,
        "loopback_attempts_total": len(LOOPBACK),
        "cases": plans,
        "baseline_never_multi_target": all(
            row["baseline"]["reason"] != "MULTI_TARGET_ENUMERATE" for row in plans.values()
        ),
        "schema_version": "v3-fix1r1-probe/v0.1",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "out": str(OUT),
                "query_sha256": summary["code_under_test"]["backend/src/mktkb/rag/query.py"],
                "external_attempts_during_probe": summary[
                    "external_attempts_during_probe"
                ],
                "all_controls_blocked": summary["all_controls_blocked"],
                "cases": {
                    name: {
                        "base": (row["baseline"]["reason"], row["baseline"]["rag_owns_turn"]),
                        "cur": (row["current"]["reason"], row["current"]["rag_owns_turn"]),
                        "cur_kernel": (row["current"]["kernel_ask"]["kind"], row["current"]["kernel_ask"]["returned"]),
                    }
                    for name, row in plans.items()
                },
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


def none_state() -> QueryState:
    return QueryState()


def benchmark_plan(module, question: str, previous: QueryState) -> dict[str, Any]:
    plan = module.parse_query(
        question, previous=previous, lexicon=LEXICON, business_date="2026-10-15"
    )
    return {
        "reason": plan.reason,
        "clarification": plan.clarification,
        "enumerate": bool(plan.enumerate),
        "mode": plan.mode,
        "field_role": plan.field_role,
        "filters": dict(plan.filters),
        "stores": list(plan.state.stores),
        "items": list(getattr(plan.state, "items", ()) or ()),
        "missing_stores": list(plan.missing_stores),
        "pending_slot": plan.state.pending_slot,
        "rag_owns_turn": bool(_rag_owns_turn(previous, plan)),
        "state_dict": plan.state.to_dict(),
    }


if __name__ == "__main__":
    sys.exit(main())
