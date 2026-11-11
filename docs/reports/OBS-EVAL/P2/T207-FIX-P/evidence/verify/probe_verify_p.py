"""P2-T207-FIX-P 独立验收探针（零真实调用；全 Mock / 离线）。

只读复核开发报告的四项断言，不引用开发自述：
  A. 修复前后对照（同一"正确回答"输入）：旧 HEAD 代码 vs 当前工作树
  B. 不弱化：既不在问题、也不在引用来源里的值仍必须被拒；未引用行的值仍必须被拒
  C. 记录型调用（不带 question）逐字不变：旧/新实现同输入同输出 + 调用点源码对照
  D. 根因重定性复核：意图 mode、Mock 首条证据前 3 字段、F02 金标数字、F04 标签二难
  E. 零真实出站计数

用法（仓库根目录）：
    .venv/Scripts/python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T207-FIX-P/evidence/verify/probe_verify_p.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT / "backend" / "src"))

import mktkb.conversations.intent as intent_module  # noqa: E402
import mktkb.conversations.service as svc  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_scoring import score_public_case  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    ChatBehavior,
    IngestSource,
    MockChatBackend,
    P2IngestPlan,
    P2RunDataset,
    ProductEvalAdapter,
)
from mktkb.providers.types import CompletionOutput, ModelOutputInvalid  # noqa: E402
from mktkb.rag.providers import post_counters, reset_post_counters  # noqa: E402

FIX = ROOT / "corpus" / "enterprise-20261101"
FILES = (
    FIX / "excel" / "E10_市场部KPI月报.xlsx",
    FIX / "word" / "W03_促销活动申请审批与结案流程管理办法.docx",
    FIX / "excel" / "E03_2026年Q4渠道价目表.xlsx",
)
DOCUMENTS = {
    "E10_市场部KPI月报.xlsx": "E10",
    "W03_促销活动申请审批与结案流程管理办法.docx": "W03",
    "E03_2026年Q4渠道价目表.xlsx": "E03",
}

#: 冻结的 5 条公开财务题（与 T205/测试同名同问，答案由本探针喂给 Mock，不由产品生成）。
CASES = (
    ("F01", "陈列达标率的计算口径和年度目标是什么？",
     "陈列达标率的年度目标是 90%；计算口径：检核合格门店数 ÷ 抽检门店数 ×100%。"),
    ("F02", "单场预算 8000 元的活动由谁审批？",
     "单场预算 8000 元的活动由市场部经理审批。"),
    ("F03", "2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价是多少？",
     "2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价为 2.99 元/瓶。"),
    ("F04", "2026年Q4渠道价目表中 咸味饼干 120g 的批发价是多少？",
     "资料中未记录咸味饼干 120g 的批发价。"),
    ("F05", "活动结束后几日内上交结案报告？",
     "第十二条 活动结束后 6 个自然日内上交结案报告，逾期计入核销及时率扣分。"),
)


def load_head_service():
    """把 git HEAD 版 service.py 复制到工作区外的临时目录并按包内模块加载（不改工作区）。"""
    source = subprocess.run(
        ["git", "show", "HEAD:backend/src/mktkb/conversations/service.py"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    tmp = Path(tempfile.mkdtemp(prefix="p2-t207-fix-p-head-"))
    target = tmp / "service_head.py"
    target.write_bytes(source)
    spec = importlib.util.spec_from_file_location("mktkb.conversations._service_head", target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, tmp


def empty_dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public",
        cases=(),
        identity={
            "dataset_version": "t207-fix-p-verify-v1",
            "label_version": "public-financial-2026-11-10",
            "suite": "p2-holdout",
            "manifest_sha256": "d" * 64,
            "case_count": 0,
        },
    )


async def run_answers(*, old_semantics: bool, old_module) -> dict:
    """走产品真实链路（隔离应用 + Mock chat）喂"正确回答"，收集 kind/error_code 与模型入参证据。"""
    reset_post_counters()
    bodies: list[dict] = []
    chat = MockChatBackend(
        behaviors=tuple(ChatBehavior(answer=answer) for _cid, _q, answer in CASES),
        before_call=lambda index, body: bodies.append({"index": index, "body": body}),
    )
    original = svc._validate_answer
    if old_semantics:
        def _head_semantics(output, allowed, facts, *, evidence=None, other_store_labels=(),
                            store_scope=None, question=""):
            # 逐字复刻 HEAD 调用点：记录型传参集合不变，正文型也**不**传问题。
            return old_module._validate_answer(
                output, allowed, facts,
                evidence=evidence, other_store_labels=other_store_labels, store_scope=store_scope,
            )
        svc._validate_answer = _head_semantics
    work = Path(tempfile.mkdtemp(prefix="t207-fix-p-verify-"))
    adapter = ProductEvalAdapter(
        work / "app",
        chat=chat,
        dataset=empty_dataset(),
        ingest_plan=P2IngestPlan(
            sources=tuple(IngestSource(path=path) for path in FILES), label="t207-fix-p-verify"
        ),
    )
    rows = []
    try:
        await adapter.start()
        await adapter.ingest()
        conversation_id = await adapter.open_conversation()
        for index, (case_id, question, _answer) in enumerate(CASES, start=1):
            turn = await adapter.ask_turn(
                question,
                user_id="employee",
                conversation_id=conversation_id,
                client_request_id=f"00000000-0000-4000-8000-{900 + index:012d}",
            )
            rows.append({
                "case_id": case_id,
                "kind": turn.kind,
                "error_code": turn.error_code,
                "http_status": turn.http_status,
                "text": turn.text,
                "sources": len(turn.sources),
            })
        counters = adapter.provider_calls()
        rag_posts = int(sum(int(v) for v in (post_counters().get("attempts") or {}).values()))
    finally:
        svc._validate_answer = original
        await adapter.close()
    return {
        "rows": rows,
        "model_bodies": bodies,
        "outbound_network": counters["outbound_network"],
        "chat_calls": counters["chat"]["calls"],
        "rag_provider_posts": rag_posts,
    }


def units_from_body(body: dict) -> tuple[SimpleNamespace, ...]:
    return tuple(
        SimpleNamespace(id=str(item.get("source_id")), text=str(item.get("text") or ""),
                        fields=dict(item.get("fields") or {}))
        for item in body.get("evidence") or ()
    )


def verdict(fn, *, question=None, text, ids, units, facts=()) -> str:
    try:
        if question is None:
            fn(CompletionOutput(text=text, source_ids=tuple(ids)), set(ids), list(facts), evidence=units)
        else:
            fn(CompletionOutput(text=text, source_ids=tuple(ids)), set(ids), list(facts),
               evidence=units, question=question)
    except ModelOutputInvalid as exc:
        return f"REJECT: {exc}"
    return "ACCEPT"


def unit_compare(old_module, captured, bodies) -> list[dict]:
    """用产品自己本轮真实下发的 evidence 逐题对照旧/新实现。"""
    out = []
    for entry in bodies:
        index = entry["index"]
        case_id, question, answer = CASES[index]
        body = entry["body"]
        units = units_from_body(body)
        ids = [unit.id for unit in units][:2]
        record = {
            "case_id": case_id,
            "question": question,
            "answer": answer,
            "evidence_units": len(units),
            "source_ids_used": ids,
            "evidence_first_fields": list((units[0].fields if units else {}).keys()),
            "old(HEAD)": verdict(old_module._validate_answer, question=None, text=answer, ids=ids, units=units),
            "new(worktree)": verdict(svc._validate_answer, question=question, text=answer, ids=ids, units=units),
        }
        out.append(record)
    return out


def not_weakened(old_module, bodies) -> list[dict]:
    """不弱化：新口径下仍必须拒绝的输入 + 唯一被有意放宽的边界。"""
    f03 = next(item for item in bodies if item["index"] == 2)["body"]
    units = units_from_body(f03)
    case, question, _answer = CASES[2]
    rows: list[dict] = []

    # 1) 编造值：既不在问题、也不在引用来源 → 新旧都必须拒绝
    text = "2026年Q4 启沣柠檬茶（500ml PET）在NKA卖场的档期特价为 1.88 元/瓶。"
    ids = [unit.id for unit in units][:2]
    rows.append({"case": "fabricated_not_in_question_nor_citation", "text": text, "cited": len(ids),
                 "old(HEAD)": verdict(old_module._validate_answer, question=None, text=text, ids=ids, units=units),
                 "new(worktree)": verdict(svc._validate_answer, question=question, text=text, ids=ids, units=units)})

    # 2) 引用 A 行却用未引用 B 行的值：只引用第一条证据，取只出现在其后证据里的数字
    first, rest = units[0], units[1:]
    first_tokens = svc._value_tokens(first.text + " " + " ".join(f"{k} {v}" for k, v in first.fields.items()))
    stolen = ""
    for unit in rest:
        corpus = unit.text + " " + " ".join(f"{k} {v}" for k, v in unit.fields.items())
        candidates = sorted(svc._value_tokens(corpus) - first_tokens)
        if candidates:
            stolen = candidates[0]
            break
    text = f"价格单号：{stolen}；档期特价为 2.99 元/瓶。"
    rows.append({"case": "uncited_row_value", "text": text, "cited": 1,
                 "stolen_token_from_uncited_unit": stolen,
                 "old(HEAD)": verdict(old_module._validate_answer, question=None, text=text, ids=[first.id], units=units),
                 "new(worktree)": verdict(svc._validate_answer, question=question, text=text, ids=[first.id], units=units)})

    # 3) 唯一被有意放宽的边界：问题里的前提值被模型写成"门槛/区间"，不再是复述
    f02 = next(item for item in bodies if item["index"] == 1)["body"]
    f02_units = units_from_body(f02)
    f02_ids = [unit.id for unit in f02_units][:2]
    widened = "审批门槛为 8000 元，由市场部经理审批。"
    w03 = freeze("W03_促销活动申请审批与结案流程管理办法.docx", {"heading": "第三章 审批权限"})
    rows.append({
        "case": "question_token_moved_to_value_position",
        "text": widened,
        "old(HEAD)": verdict(old_module._validate_answer, question=None, text=widened, ids=f02_ids, units=f02_units),
        "new(worktree)": verdict(svc._validate_answer, question=CASES[1][1], text=widened, ids=f02_ids, units=f02_units),
        "scorer": score(F02_CASE, text=widened, sources=w03) if "F02_CASE" in globals() else "scored-later",
    })
    return rows


def record_path_invariance(old_module, bodies) -> dict:
    """记录型（不传 question）口径逐字不变：同输入同输出（含接受侧正例）。"""
    unit = SimpleNamespace(
        id="u-rule",
        text="门店：城东店 / 联系电话：021-5000-0001 / 负责人：张三",
        fields={"门店": "城东店", "联系电话": "021-5000-0001", "负责人": "张三"},
    )
    samples = [
        ("accepted_baseline", "根据资料：城东店的电话是 021-5000-0001。", []),
        ("facts_binding_ok", "根据资料：城东店的电话是 021-5000-0001。", [("联系电话", "021-5000-0001")]),
        ("unsourced_value", "根据资料：城东店的电话是 021-9999-0001。", []),
        ("question_like_year_value", "根据资料：城东店的电话是 021-5000-0001，2026 年更新。", []),
        ("facts_mismatch", "根据资料：城东店的电话是 021-5000-0001。", [("联系电话", "021-8888-0001")]),
    ]
    rows = []
    for name, text, facts in samples:
        rows.append({
            "case": name,
            "old(HEAD)": verdict(old_module._validate_answer, question=None, text=text, ids=["u-rule"], units=(unit,), facts=facts),
            "new(worktree, question 缺省)": verdict(svc._validate_answer, question=None, text=text, ids=["u-rule"], units=(unit,), facts=facts),
        })
    head_source = subprocess.run(["git", "show", "HEAD:backend/src/mktkb/conversations/service.py"],
                                 cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    work_source = (ROOT / "backend" / "src" / "mktkb" / "conversations" / "service.py").read_text(encoding="utf-8")
    needle = "                text, source_ids = _validate_answer(output, allowed, facts)"
    return {
        "samples": rows,
        "all_samples_identical": all(row["old(HEAD)"] == row["new(worktree, question 缺省)"] for row in rows),
        "record_call_site_head": needle in head_source,
        "record_call_site_worktree": needle in work_source,
        "head_signature_has_question": "question: str = \"\"" in head_source,
        "worktree_signature_has_question": 'question: str = ""' in work_source,
        "question_call_sites_worktree": work_source.count("question=question,"),
        "head_service_sha256": __import__("hashlib").sha256(head_source.encode("utf-8")).hexdigest()[:16],
        "worktree_service_sha256": __import__("hashlib").sha256(work_source.encode("utf-8")).hexdigest()[:16],
    }


async def intent_modes() -> dict:
    """(a) F01-F05 的意图分类：mode / requested_fields / entities（用产品自己的库与词典）。"""
    work = Path(tempfile.mkdtemp(prefix="t207-fix-p-intent-"))
    chat = MockChatBackend()
    adapter = ProductEvalAdapter(
        work / "app", chat=chat, dataset=empty_dataset(),
        ingest_plan=P2IngestPlan(sources=tuple(IngestSource(path=p) for p in FILES), label="intent"),
    )
    out = []
    try:
        await adapter.start()
        await adapter.ingest()
        db = adapter._app.state.db.session()
        try:
            lexicon = intent_module.load_lexicon(db)
            for case_id, question, _answer in CASES:
                plan = intent_module.parse_question(question, lexicon=lexicon)
                out.append({
                    "case_id": case_id,
                    "mode": plan.mode,
                    "requested_fields": list(plan.requested_fields),
                    "entities": dict(plan.entities),
                    "missing_fields": list(plan.missing_fields),
                    "clarification": plan.clarification,
                })
            header = {"stores": len(lexicon.store_labels), "items": len(lexicon.item_labels),
                      "identifiers": len(lexicon.identifier_labels)}
        finally:
            db.close()
    finally:
        await adapter.close()
    return {"lexicon": header, "plans": out}


# --------------------------------------------------------------------------- #
# 冻结标签的可达性（用评测器自身判定，不改标签）
# --------------------------------------------------------------------------- #

KPI_TARGET_REFERENCE = "月份：2026-09；指标：陈列达标率；计算口径：检核合格门店数 ÷ 抽检门店数 ×100%；年度目标：90%"

F01_CASE = CaseSpec(case_id="F01", suite="b0", split="dev", stratum="exact", business_date="2026-10-28",
                    question=CASES[0][1], expected_kind="answer", expected_values=("90%",),
                    expected_sources=({"doc_code": "E10", "locator": {"sheet": "KPI月报", "row": 103}},),
                    reference_answer=KPI_TARGET_REFERENCE, labeler="lead",
                    label_version="public-financial-2026-11-10")
F02_CASE = CaseSpec(case_id="F02", suite="b0", split="dev", stratum="exact", business_date="2026-10-28",
                    question=CASES[1][1], expected_kind="answer", expected_values=("市场部经理",),
                    expected_sources=({"doc_code": "W03", "locator": {"heading": "第三章 审批权限"}},),
                    forbidden_values=("事业部总经理", "通路行销主管"), labeler="lead",
                    label_version="public-financial-2026-11-10")
F03_CASE = CaseSpec(case_id="F03", suite="b0", split="dev", stratum="exact", business_date="2026-10-28",
                    question=CASES[2][1], expected_kind="answer", expected_values=("2.99",),
                    expected_sources=({"doc_code": "E03", "locator": {"sheet": "NKA卖场", "row": 7}},),
                    forbidden_values=("2.5",), labeler="lead",
                    label_version="public-financial-2026-11-10")
F04_CASE = CaseSpec(case_id="F04", suite="badcase", split="dev", stratum="negative",
                    business_date="2026-10-28", question=CASES[3][1], expected_kind="not_found",
                    expected_values=(), expected_sources=(), labeler="lead",
                    label_version="public-financial-2026-11-10")


def _row(case, turn):
    return {"case_id": case.case_id, "suite": case.suite, "stratum": case.stratum,
            "conversation_id": "conv-verify", "status": "ok", "error_code": None,
            "planned_turns": 1, "turns_executed": 1,
            "turns": [{"turn": 1, "status": "ok", "error_code": None, "product": turn}]}


def score(case, *, text, kind="answer", sources=()):
    turn = {"kind": kind, "text": text, "trace_id": f"verify-{case.case_id}", "trace_path": "legacy",
            "sources": [dict(s) for s in sources], "http_status": 200}
    scored = score_public_case(case, _row(case, turn), document_codes=DOCUMENTS,
                               allowed_doc_codes=set(DOCUMENTS.values()))
    return {"status": scored.score.status,
            "failed": [c["check_id"] for c in scored.score.checks if c["status"] == "fail"],
            "skipped": [c["check_id"] for c in scored.score.checks if c["status"] == "skipped"]}


def freeze(document: str, locator: dict):
    return ({"source_id": f"src-{document}", "document_name": document, "version_number": 1,
             "status": "active", "locator": dict(locator)},)


def labels_recheck() -> dict:
    from mktkb.evaluation.scorers import _gold_number_keys
    w03 = freeze("W03_促销活动申请审批与结案流程管理办法.docx", {"heading": "第三章 审批权限"})
    e03 = freeze("E03_2026年Q4渠道价目表.xlsx", {"sheet": "NKA卖场", "row": 7})
    return {
        "F02_gold_number_keys": sorted(_gold_number_keys(F02_CASE)),
        "F02_only_matching_tier_clause": score(
            F02_CASE, text="5000 元至 20000 元由市场部经理审批。", sources=w03),
        "F02_approver_only": score(F02_CASE, text="单场预算 8000 元的活动由市场部经理审批。", sources=w03),
        "F02_full_sixth_article": score(
            F02_CASE,
            text=("第六条 审批权限按单场预算分档：5000 元（含）以内由通路行销主管审批；"
                  "5000 元至 20000 元由市场部经理审批；20000 元至 100000 元由事业部总经理审批；"
                  "100000 元以上须经财务部与总经理联签。"),
            sources=w03),
        "F04_should_refuse": F04_CASE.should_refuse,
        "F04_expected_kind": F04_CASE.expected_kind,
        "F04_correct_refusal(not_found)": score(
            F04_CASE, text="资料中未记录咸味饼干 120g 的批发价。", kind="not_found"),
        "F04_answer_like(answer)": score(
            F04_CASE, text="咸味饼干 120g 的批发价是 3.5 元/袋。", kind="answer", sources=e03),
        "F03_stale_2025_row": score(
            F03_CASE, text="价格单号：PX-0020；档期特价：2.5 元/瓶（2025-10-01 生效）",
            sources=freeze("E03_2026年Q4渠道价目表.xlsx", {"sheet": "NKA卖场", "row": 20})),
    }


def model_truncation(bodies) -> list[dict]:
    """(b) Mock 是否只回首条证据前 3 个字段 —— 用真实下发的 evidence 复算并与产品原样回答对齐。"""
    out = []
    for entry in bodies:
        index = entry["index"]
        units = units_from_body(entry["body"])
        if not units:
            out.append({"case_id": CASES[index][0], "evidence": 0})
            continue
        first = units[0]
        first_three = "；".join(f"{k}：{v}" for k, v in list(first.fields.items())[:3])
        out.append({
            "case_id": CASES[index][0],
            "first_unit_fields": list(first.fields.keys()),
            "mock_first_three": first_three if first.fields else first.text,
        })
    return out


async def main() -> None:
    old_module, old_dir = load_head_service()

    after = await run_answers(old_semantics=False, old_module=old_module)
    before = await run_answers(old_semantics=True, old_module=old_module)

    report = {
        "A_fix_before_after": {
            "after(worktree)": after["rows"],
            "before(HEAD semantics)": before["rows"],
            "unit_level_same_evidence": unit_compare(old_module, None, after["model_bodies"]),
        },
        "B_not_weakened": not_weakened(old_module, after["model_bodies"]),
        "C_record_path_invariance": record_path_invariance(old_module, after["model_bodies"]),
        "D_root_cause": {
            "intent_modes": await intent_modes(),
            "mock_truncation": model_truncation(after["model_bodies"]),
            "labels": labels_recheck(),
        },
        "E_zero_outbound": {
            "after": {k: after[k] for k in ("outbound_network", "chat_calls", "rag_provider_posts")},
            "before": {k: before[k] for k in ("outbound_network", "chat_calls", "rag_provider_posts")},
        },
        "meta": {"head_service_copy_dir_outside_workspace": str(old_dir),
                 "repo_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                             capture_output=True, check=True).stdout.decode().strip()},
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
