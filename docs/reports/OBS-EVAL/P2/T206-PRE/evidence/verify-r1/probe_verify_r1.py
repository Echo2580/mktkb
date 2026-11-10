"""P2-T206-PRE-R1 独立复验探针（证伪优先；全 Mock/离线；零真实调用）。

只读仓库、只写 stdout 与临时目录：不写仓库任何文件、不 commit/push、不联网。

  .venv\Scripts\python.exe -B -X utf8 docs/reports/OBS-EVAL/P2/T206-PRE/evidence/verify-r1/probe_verify_r1.py

复验点：
  A. R-1 config_hash 缺/异 fail-closed（双侧各判、只补一侧仍阻断、manifest 缺失不重复）
  B. R-2 gate 行 retrieved 是否=产品真实检索只读重放（用产品自己的检索 API 独立重算对比）；
     正例 citation subset 才 pass；drop/foreign/partial/缺键 fail；非作答轮不采集；
     失败路径返回空；采集只读（revision/行数不变）；config_hash 两次一致
  C. R-3 契约 §8 顺序与代码一致：原生清单不全 → run_manifest_incomplete；清单补全而
     trace 未绑（config_hash 置 NULL）→ trace_integrity=version_binding fail
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(REPO / "backend" / "src"))
sys.path.insert(0, str(REPO / "backend" / "tests" / "evaluation"))

import test_p2_runner as H  # noqa: E402  - 只复用测试夹具的构造（数据集/计划/授权）

from mktkb.conversations import intent as intent_module  # noqa: E402
from mktkb.conversations import service as conv_service  # noqa: E402
from mktkb.conversations.models import (  # noqa: E402
    Conversation,
    ConversationMessage,
    ConversationRequest,
)
from mktkb.documents.models import Document, SourceUnit  # noqa: E402
from mktkb.evaluation import p2_scoring as ps  # noqa: E402
from mktkb.evaluation.p2_runner import run_p2  # noqa: E402
from mktkb.evaluation.product_adapter import MockChatBackend, ProductEvalAdapter  # noqa: E402
from mktkb.rag.query import build_lexicon, parse_query  # noqa: E402
from mktkb.rag.types import QueryState  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

DOCUMENT_CODES = {H.D01.name: "D01", H.D04.name: "D04"}
FOREIGN_UNIT = "99999999-9999-4999-8999-999999999999"
CHECKS: list[dict] = []
LIMITATIONS: list[str] = []


def check(cid: str, ok: bool, detail=None) -> None:
    CHECKS.append({"id": cid, "ok": bool(ok), "detail": detail})


def gate_for(*, manifest_hash: str | None, public_hash, holdout_hash) -> dict:
    """evaluate_p2_gate 的最小可判定输入；返回 codes/severity/release。"""
    config = ps.load_p2_gate_config()
    manifest = {
        "run_id": "p2run-r1-verify",
        "scope": ps.P2_RUN_SCOPE,
        "mode": ps.P2_RUN_MODE,
        "gate_version": config.gate_version,
        "gate_config_hash": config.config_hash,
    }
    if manifest_hash is not None:
        manifest["config_hash"] = manifest_hash
    public = ps.score_public_suites([], run_id="p2run-r1-verify", config_hash=public_hash)
    holdout = ps.aggregate_holdout(
        [], thresholds_approved=False, run_id="p2run-r1-verify", config_hash=holdout_hash
    )
    decision = ps.evaluate_p2_gate(
        config=config,
        run_manifest=manifest,
        run_summary={"status": "succeeded", "stop_code": None, "cases": {}},
        hard_gate=None,
        public=public,
        holdout=holdout,
        citation_evidence_complete=True,
    )
    return {
        "codes": [block.code for block in decision.blocks],
        "severities": sorted({block.severity for block in decision.blocks}),
        "release_allowed": decision.release_allowed,
        "quality_exit_code": decision.quality_exit_code,
    }


def full_manifest() -> dict:
    config = ps.load_p2_gate_config()
    return {
        "run_id": "p2run-r1-verify",
        "scope": ps.P2_RUN_SCOPE,
        "mode": ps.P2_RUN_MODE,
        "gate_version": config.gate_version,
        "gate_config_hash": config.config_hash,
        "config_hash": "a" * 64,
    }


def tamper_rows(rows, *, mode: str, cited_units: dict[str, list[str]]):
    out = []
    for row in rows:
        copy = dict(row)
        outcome = copy.get("outcome")
        if isinstance(outcome, dict) and outcome.get("kind") == "answer":
            outcome = dict(outcome)
            if mode == "drop":
                outcome["retrieved"] = []
            elif mode == "foreign":
                outcome["retrieved"] = [
                    {
                        "doc_code": "",
                        "unit_ids": [FOREIGN_UNIT],
                        "unit_key": "sheet:无关:row:99",
                        "locator": {"sheet": "无关", "row": 99},
                        "chunk_id": None,
                        "hard_filter_violation": None,
                    }
                ]
            elif mode == "missing_key":
                outcome.pop("retrieved", None)
            elif mode == "partial":
                units = cited_units.get(str(copy.get("case_id"))) or []
                drop = units[:1]
                outcome["retrieved"] = [
                    item
                    for item in outcome.get("retrieved") or ()
                    if not (set(item.get("unit_ids") or ()) & set(drop))
                ]
            elif mode == "copy_citations":
                # 攻击面：把引用抄成候选（gate 无法区分）——预期 pass，记录信任边界
                outcome["retrieved"] = [
                    {
                        "doc_code": item.get("doc_code", ""),
                        "unit_ids": list(item.get("unit_ids") or ()),
                        "unit_key": item.get("unit_key"),
                        "locator": dict(item.get("locator") or {}),
                        "chunk_id": None,
                        "hard_filter_violation": None,
                    }
                    for item in outcome.get("citations") or ()
                ]
            copy["outcome"] = outcome
        out.append(copy)
    return tuple(out)


def replay_rag(qa, question: str, state) -> set[str]:
    """用产品自己的 rag 内核 API 独立重算候选（不复用适配器方法）。"""
    index = qa.index()
    plan = parse_query(
        question,
        previous=state,
        lexicon=build_lexicon(index.lexicon_data()),
        business_date=qa.config.business_date,
        page_size=qa.config.page_size,
    )
    return {str(item) for item in qa.candidate_unit_ids(plan) if str(item)}


def replay_legacy(app, qa, question, conversation_id, client_request_id, revision) -> set[str]:
    """用产品自己的 legacy 检索入口独立重算候选（不复用适配器方法）。"""
    db_factory = app.state.db
    db = db_factory.session()
    try:
        conv = db.get(Conversation, uuid.UUID(str(conversation_id)))
        if conv is None:
            return set()
        req = db.scalar(
            select(ConversationRequest).where(
                ConversationRequest.conversation_id == conv.id,
                ConversationRequest.client_request_id == uuid.UUID(str(client_request_id)),
            )
        )
        msg = db.get(ConversationMessage, req.user_message_id) if req is not None else None
        questions, entities = conv_service._load_context(db, conv, msg.seq)
        plan = intent_module.parse_question(
            str(question),
            lexicon=intent_module.load_lexicon(db),
            context_entities=entities,
            context_questions=questions,
        )
        if plan.intent is None:
            return set()
        cand = None
        if qa is not None and str(plan.intent.mode) == "record":
            cand = qa.candidate_unit_ids_for_intent(
                mode="record",
                terms=plan.intent.terms,
                entity_filters=plan.intent.entity_filters,
            )
        evidence = conv_service._retrieve(
            db_factory, plan.intent, int(revision), limit=100, candidate_ids=cand
        )
        return {str(unit.id) for unit in evidence.units if getattr(unit, "id", None) is not None}
    finally:
        db.close()


async def run_once(case_specs, *, base_dir: Path):
    """跑一次 P2 mock run，并捕获每轮检索快照输入 + 独立重放结果。"""
    config = ps.load_p2_gate_config()
    plan = H.make_plan(case_specs)
    adapter = ProductEvalAdapter(
        base_dir,
        chat=MockChatBackend(),
        dataset=H.make_dataset(case_specs),
        ingest_plan=H.make_ingest_plan(),
    )
    captured: dict[str, dict] = {}
    original = adapter.retrieval_candidates

    def spy(question, *, conversation_id, client_request_id, trace_path, revision, state):
        out = original(
            question,
            conversation_id=conversation_id,
            client_request_id=client_request_id,
            trace_path=trace_path,
            revision=revision,
            state=state,
        )
        captured[str(client_request_id)] = {
            "question": str(question),
            "conversation_id": str(conversation_id),
            "trace_path": None if trace_path is None else str(trace_path),
            "revision": revision,
            "state": None if state is None else state.to_dict(),
            "returned_units": sorted(
                {unit for item in out for unit in item.get("unit_ids") or ()}
            ),
        }
        return out

    adapter.retrieval_candidates = spy  # type: ignore[assignment]
    try:
        result = await run_p2(
            plan,
            adapter=adapter,
            authorization=H.dry_run_authorization(plan),
            now=H.NOW,
            gate_config=config,
        )
        assert result.status == "succeeded", result.as_dict()
        return adapter, captured, plan
    except Exception:
        await adapter.close()
        raise


def main() -> dict:
    config = ps.load_p2_gate_config()

    # ---------------- A. R-1 ----------------
    good = full_manifest()
    baseline = gate_for(manifest_hash=good["config_hash"], public_hash=good["config_hash"], holdout_hash=good["config_hash"])
    check("R1.baseline_no_config_hash_block", not [c for c in baseline["codes"] if c.startswith("config_hash")], baseline)

    both_missing = gate_for(manifest_hash=good["config_hash"], public_hash=None, holdout_hash=None)
    both_missing_blocks = [
        {"code": block.code, "severity": block.severity}
        for block in ps.evaluate_p2_gate(
            config=ps.load_p2_gate_config(),
            run_manifest=good,
            run_summary={"status": "succeeded", "stop_code": None, "cases": {}},
            hard_gate=None,
            public=ps.score_public_suites([], run_id="p2run-r1-verify", config_hash=None),
            holdout=ps.aggregate_holdout([], thresholds_approved=False, run_id="p2run-r1-verify", config_hash=None),
            citation_evidence_complete=True,
        ).blocks
    ]
    check(
        "R1.both_missing_two_unbound",
        both_missing["codes"].count("config_hash_unbound") == 2 and both_missing["release_allowed"] is False,
        both_missing,
    )
    half = gate_for(manifest_hash=good["config_hash"], public_hash=good["config_hash"], holdout_hash=None)
    check(
        "R1.half_fix_still_blocked",
        half["codes"].count("config_hash_unbound") == 1 and half["release_allowed"] is False,
        half,
    )
    other = gate_for(manifest_hash=good["config_hash"], public_hash="b" * 64, holdout_hash=good["config_hash"])
    check(
        "R1.declared_mismatch_blocks",
        other["codes"].count("config_hash_binding_mismatch") == 1 and other["release_allowed"] is False,
        other,
    )
    manifest_missing = gate_for(manifest_hash=None, public_hash=None, holdout_hash=None)
    check(
        "R1.manifest_missing_single_unbound",
        manifest_missing["codes"].count("config_hash_unbound") == 1 and manifest_missing["release_allowed"] is False,
        manifest_missing,
    )
    config_hash_blocks = [b for b in both_missing_blocks if b["code"].startswith("config_hash")]
    check(
        "R1.config_hash_blocks_are_unknown",
        len(config_hash_blocks) == 2 and all(b["severity"] == "unknown" for b in config_hash_blocks),
        config_hash_blocks,
    )
    check("R1.quality_exit_nonzero", both_missing["quality_exit_code"] != 0, both_missing["quality_exit_code"])

    # ---------------- B. R-2 ----------------
    multi = H.make_case(
        "P02",
        H.FOLLOWUP_QUESTION,
        turns=(
            {"role": "user", "question": H.RAG_QUESTION},
            {"role": "user", "question": H.FOLLOWUP_QUESTION},
        ),
        stratum="multi_turn",
    )
    multi2 = H.make_case(
        "P05",
        "那城西店呢？",
        turns=(
            {"role": "user", "question": H.RAG_QUESTION},
            {"role": "user", "question": "那城西店呢？"},
        ),
        stratum="multi_turn",
    )
    cases = (
        H.make_case("P01", H.RAG_QUESTION),
        H.make_case("P03", H.LEGACY_QUESTION),
        H.make_case("P04", H.UNKNOWN_QUESTION, stratum="negative"),
        multi,
        multi2,
    )
    tmp = Path(tempfile.mkdtemp(prefix="p2-r1-verify-"))
    adapter, captured, _ = asyncio.run(run_once(cases, base_dir=tmp / "run_a"))
    try:
        run_dir = adapter.paths.run_dir
        manifest = H.read_json(run_dir / "run_manifest.json")
        summary = H.read_json(run_dir / "summary.json")
        case_rows = H.read_jsonl(run_dir / "cases.jsonl")
        by_id = {row["case_id"]: row for row in case_rows}
        qa = adapter._qa
        app = adapter.app

        # B1 记录 = 产品检索 API 的独立重放（rag 用发送前状态；legacy 用产品检索入口）
        per_turn = []
        for row in case_rows:
            for turn in row["turns"]:
                product = turn["product"]
                rid = str(turn.get("client_request_id") or product.get("client_request_id") or "")
                snap = captured.get(rid)
                recorded = {
                    unit for item in product.get("retrieved") or () for unit in item.get("unit_ids") or ()
                }
                cited = {str(item.get("source_id")) for item in product.get("sources") or ()}
                item = {
                    "case_id": row["case_id"],
                    "turn": turn.get("turn"),
                    "kind": product.get("kind"),
                    "path": product.get("trace_path"),
                    "captured": snap is not None,
                    "captured_revision": None if snap is None else snap["revision"],
                    "product_revision": product.get("revision"),
                    "recorded_units": len(recorded),
                    "cited_units": len(cited),
                    "cited_subset": cited <= recorded,
                    "extra_units": sorted(recorded - cited),
                }
                if snap is not None and product.get("kind") == "answer":
                    if snap["trace_path"] == "rag":
                        state = QueryState.from_dict(snap["state"])
                        replay = replay_rag(qa, snap["question"], state)
                    elif snap["trace_path"] in {"legacy", "legacy_with_rag_candidates"}:
                        replay = replay_legacy(
                            app,
                            qa,
                            snap["question"],
                            snap["conversation_id"],
                            rid,
                            snap["revision"],
                        )
                    else:
                        replay = set()
                    item["replay_units"] = len(replay)
                    item["recorded_equals_replay"] = replay == recorded
                    item["replay_not_citations"] = replay != cited
                per_turn.append(item)

        answer_turns = [t for t in per_turn if t["kind"] == "answer"]
        check("R2.all_answer_turns_captured", all(t["captured"] for t in answer_turns), per_turn)
        check("R2.citations_subset_records", all(t["cited_subset"] for t in answer_turns), per_turn)
        check(
            "R2.recorded_equals_real_retrieval_replay",
            all(t.get("recorded_equals_replay") for t in answer_turns),
            per_turn,
        )
        check(
            "R2.replay_not_citations",
            any(t.get("replay_not_citations") for t in answer_turns),
            [t for t in answer_turns if not t.get("replay_not_citations")],
        )
        multi_turn_answers = [
            t for t in per_turn
            if t["case_id"] in {"P02", "P05"} and t["kind"] == "answer"
        ]
        check(
            "R2.multi_turn_answer_turn_replayed_from_context",
            len(multi_turn_answers) >= 2
            and all(t.get("recorded_equals_replay") for t in multi_turn_answers),
            multi_turn_answers,
        )
        # 快照语义：mock 下 rag 持久状态不推进（实测 turn=0），因此"发送前快照 vs 事后重放"
        # 没有差分证据；这里只如实记录，不把"无差分"当成"已验证"。
        final_states = {
            rid: qa.load_state("employee", snap["conversation_id"]).to_dict() for rid, snap in captured.items()
        }
        state_advanced = [
            rid
            for rid, snap in captured.items()
            if json.dumps(final_states[rid], sort_keys=True, ensure_ascii=False)
            != json.dumps(snap["state"], sort_keys=True, ensure_ascii=False)
        ]
        LIMITATIONS.append(
            "rag 持久状态在 mock 下不推进（%d/%d 轮 state 前后相同），"
            "'发送前快照 vs 事后重放'无差分证据；顺序依据代码位置 product_adapter.ask_turn 快照在 POST 之前。"
            % (len(captured) - len(state_advanced), len(captured))
        )

        # B1b 候选池 vs 「返回给模型的证据」：rag 的 candidate_unit_ids 是召回并集
        # （exact/lexical/vector/fused），可能比 fused[:top_k] 更宽——如实量化。
        pool = {}
        for rid, snap in captured.items():
            if snap["trace_path"] != "rag":
                continue
            state0 = QueryState.from_dict(snap["state"])
            index = qa.index()
            plan0 = parse_query(
                snap["question"],
                previous=state0,
                lexicon=build_lexicon(index.lexicon_data()),
                business_date=qa.config.business_date,
                page_size=qa.config.page_size,
            )
            result0 = qa.search(plan0)
            candidates0 = {str(item) for item in qa.candidate_unit_ids(plan0) if str(item)}
            returned0 = {
                str(unit) for ev in result0.evidence for unit in (ev.citation.unit_ids or ())
            }
            pool[snap["question"]] = {
                "candidates": len(candidates0),
                "returned_evidence": len(returned0),
                "returned_subset_of_candidates": returned0 <= candidates0,
                "candidates_not_returned": len(candidates0 - returned0),
            }
        check(
            "R2.rag_returned_evidence_subset_of_candidates",
            all(item["returned_subset_of_candidates"] for item in pool.values()),
            pool,
        )
        LIMITATIONS.append(
            "rag 的 retrieved 是召回并集（exact/lexical/vector/fused），可宽于 fused[:top_k] 返回证据；"
            "本探针实测 %s。gate 语义是'引用 ⊆ 检索候选'，不是'引用 ⊆ 模型实际看到的那一页'。"
            % json.dumps(pool, ensure_ascii=False)
        )

        # B2 候选是真实产品来源单元（库内存在、文档在本 run 内、unit_key/locator 非空）
        db = app.state.db.session()
        try:
            ingested = {str(receipt.document_id) for receipt in adapter.ingest_receipts}
            seen = set()
            for row in case_rows:
                for turn in row["turns"]:
                    for item in turn["product"].get("retrieved") or ():
                        for unit_id in item.get("unit_ids") or ():
                            seen.add(str(unit_id))
            rows = db.execute(
                select(SourceUnit, Document)
                .join(Document, SourceUnit.document_id == Document.id)
                .where(SourceUnit.id.in_([uuid.UUID(u) for u in sorted(seen)]))
            ).all()
            resolved = {str(unit.id): doc for unit, doc in rows}
            check("R2.retrieved_units_exist_in_product_db", resolved.keys() == seen, sorted(seen - set(resolved)))
            check(
                "R2.retrieved_units_inside_run_docs",
                all(str(doc.id) in ingested for doc in resolved.values()),
                {uid: str(doc.id) for uid, doc in resolved.items() if str(doc.id) not in ingested},
            )
            check(
                "R2.retrieved_has_identity",
                all(
                    item.get("unit_key") and item.get("locator")
                    for row in case_rows
                    for turn in row["turns"]
                    for item in turn["product"].get("retrieved") or ()
                ),
                None,
            )
        finally:
            db.close()

        # B3 非作答轮不采集
        p04 = by_id["P04"]["turns"][0]["product"]
        check("R2.not_found_not_collected", p04.get("kind") == "not_found" and not p04.get("retrieved"), p04.get("retrieved"))
        p04_calls = [snap for snap in captured.values() if snap["question"] == H.UNKNOWN_QUESTION]
        check("R2.not_found_no_retrieval_call", not p04_calls, p04_calls)

        # B4 gate 正例 + 反例
        scored = [
            ps.score_public_case(
                case,
                by_id[case.case_id],
                document_codes=DOCUMENT_CODES,
                allowed_doc_codes=set(DOCUMENT_CODES.values()),
            )
            for case in cases
        ]
        rows = ps.build_gate_rows(cases, scored)
        gate_run = ps.build_gate_run(
            run_dir=run_dir, manifest=manifest, cases=cases, rows=rows, summary=summary
        )
        positive = ps.evaluate_p2_hard_gates(gate_run, config=config, require_trace=True)
        check(
            "R2.positive_citation_required_pass",
            positive.gate_status.get("citation_required") == "pass",
            {"status": positive.gate_status.get("citation_required"), "failures": [f.check_id for f in positive.failures]},
        )
        check(
            "R2.rows_carry_product_retrieved",
            all(
                {u for item in (row["outcome"] or {}).get("retrieved") or () for u in item["unit_ids"]}
                == {u for item in by_id[row["case_id"]]["turns"][-1]["product"].get("retrieved") or () for u in item["unit_ids"]}
                for row in rows
                if row["outcome"] and row["outcome"].get("kind") == "answer"
            ),
            None,
        )
        cited_units = {
            row["case_id"]: [u for item in (row["outcome"] or {}).get("citations") or () for u in item["unit_ids"]]
            for row in rows
        }
        negatives = {}
        for mode in ("drop", "foreign", "partial", "missing_key", "copy_citations"):
            tampered = ps.build_gate_run(
                run_dir=run_dir,
                manifest=manifest,
                cases=cases,
                rows=tamper_rows(rows, mode=mode, cited_units=cited_units),
                summary=summary,
            )
            hard = ps.evaluate_p2_hard_gates(tampered, config=config, require_trace=True)
            negatives[mode] = {
                "status": hard.gate_status.get("citation_required"),
                "listed": "citation_required" in hard.hard_failures,
                "check_ids": sorted({f.check_id for f in hard.failures if f.gate_id == "citation_required"}),
            }
        for mode in ("drop", "foreign", "partial", "missing_key"):
            check(
                f"R2.negative_{mode}_fails",
                negatives[mode]["status"] == "fail"
                and negatives[mode]["listed"]
                and "citation_not_in_evidence" in negatives[mode]["check_ids"],
                negatives[mode],
            )
        check("R2.copy_citations_passes_gate_trust_boundary", negatives["copy_citations"]["status"] == "pass", negatives["copy_citations"])

        # B5 失败路径一律返回空（不放宽）+ 只读
        check("R2.revision_none_returns_empty", adapter.retrieval_candidates(
            "x", conversation_id="c", client_request_id="r", trace_path="rag", revision=None, state=None
        ) == (), None)
        check("R2.unknown_path_returns_empty", adapter.retrieval_candidates(
            "x", conversation_id="c", client_request_id="r", trace_path="mystery", revision=1, state=None
        ) == (), None)
        check("R2.rag_without_state_returns_empty", adapter.retrieval_candidates(
            "x", conversation_id="c", client_request_id="r", trace_path="rag", revision=1, state=None
        ) == (), None)
        rev_before = adapter.product_revision()
        db = app.state.db.session()
        try:
            units_before = int(db.scalar(select(func.count()).select_from(SourceUnit)) or 0)
        finally:
            db.close()
        empty = adapter.retrieval_candidates(
            "不存在的会话问题", conversation_id=str(uuid.uuid4()), client_request_id=str(uuid.uuid4()),
            trace_path="legacy", revision=rev_before, state=None,
        )
        rev_after = adapter.product_revision()
        db = app.state.db.session()
        try:
            units_after = int(db.scalar(select(func.count()).select_from(SourceUnit)) or 0)
        finally:
            db.close()
        check("R2.bad_legacy_returns_empty_no_raise", empty == (), None)
        check(
            "R2.retrieval_read_only_revision",
            rev_before == rev_after and units_before == units_after,
            {"revision": [rev_before, rev_after], "source_units": [units_before, units_after]},
        )

        # B6 零真实调用 + 两次 run 的 config_hash 稳定
        check(
            "R2.no_real_calls",
            int(summary["requests"]["real_requests"]) == 0 and float(summary["requests"]["billed_cny"]) == 0.0,
            summary["requests"],
        )
        adapter2, _, _ = asyncio.run(run_once(cases, base_dir=tmp / "run_b"))
        try:
            manifest2 = H.read_json(adapter2.paths.run_dir / "run_manifest.json")
            check(
                "R2.config_hash_stable_across_runs",
                manifest2["config_hash"] == manifest["config_hash"] and manifest2["run_id"] != manifest["run_id"],
                {"a": manifest["config_hash"], "b": manifest2["config_hash"]},
            )
        finally:
            asyncio.run(adapter2.close())

        # ---------------- C. R-3 ----------------
        native = {
            "run_id": "p2run-r1-verify",
            "mode": ps.P2_RUN_MODE,
            "scope": ps.P2_RUN_SCOPE,
            "suite": "p2-holdout",
            "dataset_version": "p2-synthetic-v1",
            "dataset_sha256": "b" * 64,
            "corpus_manifest_sha256": manifest["corpus_manifest_sha256"],
            "business_date": "2026-11-10",
            "index_revision": manifest["index_revision"],
            "pipeline_version": manifest["pipeline_version"],
            "gate_version": config.gate_version,
            "label_version": "synthetic-v1",
            "created_at": "2026-11-10T12:00:00+00:00",
            "case_count": len(cases),
        }
        try:
            ps.build_gate_run(run_dir=run_dir, manifest=native, cases=cases, rows=rows, summary=summary)
            code = None
        except ps.P2ScoringError as exc:
            code = exc.code
        check("R3.native_manifest_first_run_manifest_incomplete", code == "run_manifest_incomplete", code)

        # 清单补全（有 config_hash）但 trace 侧 config_hash 置 NULL → version_binding fail
        declared = str(manifest.get("trace_store") or "traces.sqlite3")
        trace_db = Path(declared)
        if not trace_db.is_absolute():
            trace_db = Path(run_dir) / trace_db
        check("R3.trace_store_found", trace_db.is_file(), str(trace_db))
        conn = sqlite3.connect(str(trace_db))
        try:
            conn.execute("UPDATE traces SET config_hash = NULL")
            conn.commit()
        finally:
            conn.close()
        complete = dict(manifest)
        unbound_run = ps.build_gate_run(
            run_dir=run_dir, manifest=complete, cases=cases, rows=rows, summary=summary
        )
        unbound = ps.evaluate_p2_hard_gates(unbound_run, config=config, require_trace=True)
        binding_checks = sorted({f.check_id for f in unbound.failures if f.gate_id == "trace_integrity"})
        check(
            "R3.completed_manifest_trace_unbound_version_binding",
            unbound.gate_status.get("trace_integrity") == "fail" and "version_binding" in binding_checks,
            {"status": unbound.gate_status.get("trace_integrity"), "checks": binding_checks},
        )

        report = {
            "run_id": manifest["run_id"],
            "config_hash": manifest["config_hash"],
            "turn_summary": per_turn,
            "negative_cases": negatives,
            "trace_integrity_after_unbind": unbound.gate_status.get("trace_integrity"),
        }
    finally:
        asyncio.run(adapter.close())

    return {
        "checks": CHECKS,
        "ok": all(item["ok"] for item in CHECKS),
        "failed": [item for item in CHECKS if not item["ok"]],
        "limitations": LIMITATIONS,
        "run": report,
    }


if __name__ == "__main__":
    payload = main()
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
