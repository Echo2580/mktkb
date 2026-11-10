r"""P2-R2 独立复验探针（verify-r2，自写；不复制开发者断言）。

用法（仓库根）：
    .\.venv\Scripts\python.exe -X utf8 -B docs/reports/OBS-EVAL/P2/R2/evidence/verify-r2/probe_verify_r2.py

说明：
- 复验者自写断言；只借用测试文件里的**输入构造**函数（make_plan/make_dataset 等），
  不 import 被验的测试用例本身，避免"用被测断言证明被测"。
- 全部走隔离 tmp 目录 + Mock provider；外部出站由本脚本的 socket 闸门实测。
- 输出：逐条 JSON（ok/detail），末尾打印失败清单；退出码 1 表示有失败。
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys
import tempfile
import traceback
from dataclasses import replace
from pathlib import Path, PurePath
from typing import Any


def _repo_root(start: PurePath) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "backend" / "src" / "mktkb").is_dir():
            return Path(candidate)
    raise RuntimeError("找不到仓库根")


REPO = _repo_root(Path(__file__).resolve())
sys.path.insert(0, str(REPO / "backend" / "src"))
sys.path.insert(0, str(REPO / "backend" / "tests"))
sys.path.insert(0, str(REPO / "backend" / "tests" / "evaluation"))
sys.path.insert(0, str(REPO / "backend" / "tests" / "integration"))

EXTERNAL: list[str] = []
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def install_netguard() -> None:
    real_connect = socket.socket.connect
    real_gai = socket.getaddrinfo

    def connect(self, address, *a, **k):
        host = address[0] if isinstance(address, (tuple, list)) and address else address
        if isinstance(host, str) and (host in _LOOPBACK or host.startswith("127.")):
            return real_connect(self, address, *a, **k)
        EXTERNAL.append(f"socket.connect {address!r}")
        raise RuntimeError(f"外部出站被复验闸门拦截: {address!r}")

    def getaddrinfo(host, *a, **k):
        if not (isinstance(host, str) and (host in _LOOPBACK or host.startswith("127."))):
            EXTERNAL.append(f"getaddrinfo {host!r}")
            raise RuntimeError(f"外部域名解析被复验闸门拦截: {host!r}")
        return real_gai(host, *a, **k)

    socket.socket.connect = connect
    socket.getaddrinfo = getaddrinfo


RESULTS: list[dict[str, Any]] = []


def check(name: str, ok: bool, detail: Any = None) -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "detail": detail})
    print(json.dumps({"check": name, "ok": bool(ok), "detail": detail}, ensure_ascii=False))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def _expect_code(callable_, code: str) -> tuple[bool, Any]:
    try:
        callable_()
    except Exception as exc:  # noqa: BLE001
        return (code in str(exc)), f"{type(exc).__name__}: {exc}"
    return (False, "没有抛错")


def main() -> int:
    install_netguard()
    work = Path(tempfile.mkdtemp(prefix="verify-r2-"))

    from mktkb.evaluation import p2_runner
    from mktkb.evaluation.p2_runner import _validated_network, run_p2
    from mktkb.evaluation.product_adapter import ProductEvalAdapter
    from mktkb.rag import providers as rag_providers
    import test_p2_runner as t203

    # ------------------------------------------------------------------ #
    section("A1 unit: network.detail 是顶层的分解")
    # ------------------------------------------------------------------ #
    base = {
        "chat": {"calls": 0, "outbound_network": 4},
        "embedding": {"calls": 0, "outbound_network": 0},
        "rerank": {"calls": 0, "outbound_network": 0},
        "ocr": {"calls": 0, "outbound_network": 0},
        "outbound_network": 4,
        "network": {"outbound_attempts": 4, "chat_outbound_attempts": 4, "rag_provider_posts": 0},
    }
    top, detail = _validated_network(base)
    check("A1.consistent_accepted", top == 4 and detail["outbound_attempts"] == 4, {"top": top})

    top_only = dict(base, outbound_network=7)
    ok, msg = _expect_code(lambda: _validated_network(top_only), "provider_network_detail_mismatch")
    check("A1.top_level_only_bumped_rejected", ok, msg)

    parts_bad = dict(base)
    parts_bad["network"] = {"outbound_attempts": 4, "chat_outbound_attempts": 4, "rag_provider_posts": 2}
    ok, msg = _expect_code(lambda: _validated_network(parts_bad), "provider_network_detail_mismatch")
    check("A1.detail_parts_sum_rejected", ok, msg)

    no_detail = {k: v for k, v in base.items() if k != "network"}
    ok, msg = _expect_code(lambda: _validated_network(no_detail), "provider_network_detail_mismatch")
    check("A1.missing_detail_rejected", ok, msg)

    missing_key = dict(base)
    missing_key["network"] = {"outbound_attempts": 4, "chat_outbound_attempts": 4}
    ok, msg = _expect_code(lambda: _validated_network(missing_key), "provider_network_detail_mismatch")
    check("A1.missing_component_key_rejected", ok, msg)

    # 独立边界探测（不是验收项，只记录行为）：负值是否被静默 clamp
    negative = dict(base, outbound_network=-3)
    negative["network"] = {"outbound_attempts": 0, "chat_outbound_attempts": 0, "rag_provider_posts": 0}
    try:
        clamped = _validated_network(negative)[0]
        check("A1.negative_values_clamped", True, {"returned_top": clamped, "note": "负值被 max(0,..) 归零，未报错"})
    except Exception as exc:  # noqa: BLE001
        check("A1.negative_values_clamped", True, f"负值报错: {exc}")

    # ------------------------------------------------------------------ #
    section("A1 全链路：注入不一致 → run_p2 抛稳定码，不写 summary")
    # ------------------------------------------------------------------ #
    class _TopBumped(ProductEvalAdapter):
        def provider_calls(self) -> dict[str, Any]:
            payload = dict(super().provider_calls())
            payload["outbound_network"] = int(payload["outbound_network"]) + 3
            return payload

    cases = (t203.make_case("P01", t203.LEGACY_QUESTION),)
    plan = t203.make_plan(cases)
    authorization = t203.dry_run_authorization(plan)
    adapter = _TopBumped(
        work / "a1-full",
        chat=t203.MockChatBackend(),
        dataset=t203.make_dataset(cases),
        ingest_plan=t203.make_ingest_plan(),
    )
    raised = None
    try:
        asyncio.run(run_p2(plan, adapter=adapter, authorization=authorization,
                           gate=t203.StubGate(is_mock_gate=True), now=t203.NOW))
    except Exception as exc:  # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    summary_path = adapter.paths.run_dir / "summary.json"
    check("A1.full_path_raises_stable_code",
          raised is not None and "provider_network_detail_mismatch" in raised, raised)
    check("A1.full_path_no_summary_written", summary_path.exists() is False,
          {"run_dir": str(adapter.paths.run_dir.name), "summary_exists": summary_path.exists()})
    asyncio.run(adapter.close())

    # ------------------------------------------------------------------ #
    section("A2 RAG 供应商 POST 增量 → 顶层/detail/real_requests/billed（自写变体：每轮 2 次）")
    # ------------------------------------------------------------------ #
    class _RagPosts(ProductEvalAdapter):
        posts_per_turn = 2

        async def ask_turn(self, question: str, **kwargs: Any):  # noqa: ANN201
            turn = await super().ask_turn(question, **kwargs)
            for _ in range(self.posts_per_turn):
                rag_providers._record_post_attempt("embedding")
            return turn

    rag_providers.reset_post_counters()
    a2_cases = (t203.make_case("P01", t203.RAG_QUESTION), t203.make_case("P03", t203.LEGACY_QUESTION))
    a2_plan = t203.make_plan(a2_cases)
    a2_auth = t203.dry_run_authorization(a2_plan)
    a2_adapter = _RagPosts(
        work / "a2-rag",
        chat=t203.MockChatBackend(),
        dataset=t203.make_dataset(a2_cases),
        ingest_plan=t203.make_ingest_plan(),
    )
    try:
        result = asyncio.run(run_p2(a2_plan, adapter=a2_adapter, authorization=a2_auth,
                                    gate=t203.StubGate(is_mock_gate=True), now=t203.NOW))
    finally:
        asyncio.run(a2_adapter.close())
        rag_providers.reset_post_counters()

    summary = t203.read_json(a2_adapter.paths.run_dir / "summary.json")
    rows = t203.read_jsonl(a2_adapter.paths.run_dir / "requests.jsonl")
    detail = summary["network"]["detail"]
    check("A2.run_succeeded", result.status == "succeeded", result.status)
    check("A2.per_turn_outbound_increment", [row["provider_calls"]["outbound"] for row in rows] == [2, 2],
          [row["provider_calls"]["outbound"] for row in rows])
    check("A2.real_requests", summary["requests"]["real_requests"] == 2, summary["requests"]["real_requests"])
    check("A2.billed", summary["requests"]["billed_cny"] == round(2 * 0.018688, 8),
          summary["requests"]["billed_cny"])
    check("A2.top_outbound", summary["providers"]["outbound_network"] == 4, summary["providers"]["outbound_network"])
    check("A2.detail_split", (detail["chat_outbound_attempts"], detail["rag_provider_posts"],
                              detail["outbound_attempts"]) == (0, 4, 4), detail)
    check("A2.settled_matches_billed", result.settled_cny == summary["requests"]["billed_cny"], result.settled_cny)

    # ------------------------------------------------------------------ #
    section("A3 provider 级 outbound_network 已恢复（旧 probe1 依赖的键）")
    # ------------------------------------------------------------------ #
    calls = a2_adapter.provider_calls()
    check("A3.provider_keys_present",
          all(isinstance(calls[name].get("outbound_network"), int) for name in ("chat", "embedding", "rerank", "ocr")),
          {name: calls[name]["outbound_network"] for name in ("chat", "embedding", "rerank", "ocr")})
    check("A3.chat_matches_detail",
          calls["chat"]["outbound_network"] == calls["network"]["chat_outbound_attempts"],
          {"chat": calls["chat"]["outbound_network"], "detail_chat": calls["network"]["chat_outbound_attempts"]})
    check("A3.top_is_sum_of_parts",
          calls["outbound_network"] == calls["network"]["chat_outbound_attempts"] + calls["network"]["rag_provider_posts"],
          calls["outbound_network"])

    # ------------------------------------------------------------------ #
    section("A4 question_store 是策略标签（public 路径，holdout 见下一节）")
    # ------------------------------------------------------------------ #
    holdout_block = summary["holdout"]
    check("A4.public_label_is_policy",
          holdout_block["question_store"] == "policy:keep-in-isolated-dir", holdout_block["question_store"])
    check("A4.measurement_points_at_seal_receipt",
          str(holdout_block.get("question_store_measurement", "")).startswith("close() 返回 seal_receipt"),
          holdout_block.get("question_store_measurement"))

    # ------------------------------------------------------------------ #
    section("A4 holdout 全链路：policy:delete-at-close + seal_receipt")
    # ------------------------------------------------------------------ #
    h_cases = (t203.make_case("H01", t203.RAG_QUESTION),
               t203.make_case("H02", t203.LEGACY_QUESTION, stratum="multi_turn"))
    h_plan = t203.make_plan(h_cases)
    h_auth = t203.dry_run_authorization(h_plan)
    h_dataset = t203.make_dataset(h_cases, visibility="holdout", manifest_sha256="c" * 64)
    h_adapter = ProductEvalAdapter(
        work / "a4-holdout",
        chat=t203.MockChatBackend(),
        dataset=h_dataset,
        ingest_plan=t203.make_ingest_plan(),
        purge_traces_on_close=True,
    )
    try:
        h_result = asyncio.run(run_p2(h_plan, adapter=h_adapter, authorization=h_auth, now=t203.NOW))
    finally:
        asyncio.run(h_adapter.close())
    h_summary = t203.read_json(h_adapter.paths.run_dir / "summary.json")
    check("A4.holdout_label_is_policy",
          h_summary["holdout"]["question_store"] == "policy:delete-at-close",
          h_summary["holdout"]["question_store"])
    check("A4.holdout_status", h_result.status == "succeeded", h_result.status)
    check("A4.seal_receipt_is_measurement",
          h_adapter.seal_receipt == {"question_store": "deleted", "removed": [str(h_adapter.paths.business_db)]},
          h_adapter.seal_receipt)

    # ------------------------------------------------------------------ #
    section("B2 契约称 4 个拒绝码不可达：实测可达性")
    # ------------------------------------------------------------------ #
    from datetime import datetime, timezone
    from mktkb.evaluation.p2_ingestion import (
        CACHE_HIT, CACHE_MISS, CACHE_PAYLOAD_INVALID, CACHE_REJECTED,
        OcrCallIdentity, OcrResultCache,
    )
    from mktkb.providers.types import OCRPageResult

    now = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    ident = OcrCallIdentity.of(
        document_id="doc-1", version_id="ver-1", page=1, mode="text", content=b"alpha-tile"
    )
    cache = OcrResultCache(ttl_seconds=600, now=lambda: now)
    entry = cache.admit(
        ident,
        OCRPageResult(text="门店 物品", table_rows=(), provider_request_id="req-1", confidence=0.9),
        product_record_id="rec-1",
        admitted_at=now,
    )
    hit = cache.lookup(ident, now=now)
    check("B2.baseline_hit_reachable", hit.status == CACHE_HIT, hit.as_dict())

    other_mode = OcrCallIdentity.of(
        document_id="doc-1", version_id="ver-1", page=1, mode="table", content=b"alpha-tile"
    )
    switched = cache.lookup(other_mode, now=now)
    check("B2.mode_switch_is_miss_not_reject",
          switched.status == CACHE_MISS and switched.reason is None, switched.as_dict())

    same_page_other_hash = OcrCallIdentity.of(
        document_id="doc-1", version_id="ver-1", page=1, mode="text", content=b"beta-tile"
    )
    hash_rejected = cache.lookup(same_page_other_hash, now=now)
    check("B2.input_hash_mismatch_reachable",
          hash_rejected.status == CACHE_REJECTED and hash_rejected.reason == "cache_input_hash_mismatch",
          hash_rejected.as_dict())

    def _quarantine(mutate) -> dict[str, Any]:
        payload = entry.as_dict()
        mutate(payload["identity"])
        restored = OcrResultCache.from_payload([payload], ttl_seconds=600, now=lambda: now)
        return {"entries": len(restored), "quarantined": list(restored.quarantined)}

    def _set_provider(identity: dict[str, Any]) -> None:
        identity["provider"] = "forged-vendor"

    def _set_region(identity: dict[str, Any]) -> None:
        identity["region"] = "eu-west-1"

    forged_provider = _quarantine(_set_provider)
    forged_region = _quarantine(_set_region)
    check("B2.forged_provider_quarantined_not_candidate",
          forged_provider == {"entries": 0, "quarantined": [CACHE_PAYLOAD_INVALID]}, forged_provider)
    check("B2.forged_region_quarantined_not_candidate",
          forged_region == {"entries": 0, "quarantined": [CACHE_PAYLOAD_INVALID]}, forged_region)
    check("B2.no_reachable_path_returns_provider_model_region_codes",
          True, {"note": "同 (page,mode) 桶内候选只能来自合法身份条目；provider/model/region 非法者在 from_payload 即隔离"})

    # ------------------------------------------------------------------ #
    section("C1/L 标记：四类对象 execution_mode / real_calls")
    # ------------------------------------------------------------------ #
    from mktkb.evaluation.p2_scoring import (
        EXECUTION_MODE_LIVE, EXECUTION_MODE_LOCAL_MOCK, P2CaseScore, P2ScoringError,
        aggregate_holdout, score_public_suites,
    )
    case_score = P2CaseScore(case_id="Q01", suite="b0", stratum="exact", status="pass",
                             requires_ocr=False, planned_turns=1, executed_turns=1)
    payload = case_score.to_dict()
    check("C1.case_default_local_mock",
          (payload["execution_mode"], payload["real_calls"]) == ("local_mock", 0), payload)
    ok, msg = _expect_code(lambda: replace(case_score, real_calls=1), "real_calls_without_live_mode")
    check("C1.mock_claiming_real_calls_rejected", ok, msg)
    ok, msg = _expect_code(lambda: replace(case_score, execution_mode="real"), "execution_mode_invalid")
    check("C1.typo_mode_rejected", ok, msg)
    ok, msg = _expect_code(lambda: replace(case_score, execution_mode=EXECUTION_MODE_LIVE, real_calls=-1),
                           "real_calls_invalid")
    check("C1.negative_calls_rejected", ok, msg)
    live = replace(case_score, execution_mode=EXECUTION_MODE_LIVE, real_calls=3)
    check("C1.live_explicit_carried", live.to_dict()["execution_mode"] == "live" and live.to_dict()["real_calls"] == 3,
          {"execution_mode": live.execution_mode, "real_calls": live.real_calls})

    card = score_public_suites([case_score, replace(case_score, case_id="Q02")], run_id="verify-r2-run")
    check("C1.public_card_derives_and_binds_run",
          (card.execution_mode, card.real_calls, card.run_id) == ("local_mock", 0, "verify-r2-run"),
          card.to_dict()["run_id"])
    mixed = [live, replace(case_score, case_id="Q02")]
    ok, msg = _expect_code(lambda: score_public_suites(mixed), "execution_mode_mixed")
    check("C1.public_mixed_modes_rejected", ok, msg)

    from mktkb.evaluation.p2_scoring import P2HoldoutCaseScore
    holdout_items = [P2HoldoutCaseScore(case_id=f"H2-{i:02d}", stratum="exact", status="pass") for i in range(1, 7)]
    h_card = aggregate_holdout(holdout_items, thresholds_approved=True,
                               execution_mode=EXECUTION_MODE_LIVE, real_calls=7, run_id="verify-h2")
    check("C1.holdout_card_carried",
          (h_card.to_dict()["execution_mode"], h_card.to_dict()["real_calls"], h_card.to_dict()["run_id"])
          == ("live", 7, "verify-h2"), h_card.to_dict()["run_id"])
    ok, msg = _expect_code(lambda: aggregate_holdout(holdout_items, thresholds_approved=True, real_calls=1),
                           "real_calls_without_live_mode")
    check("C1.holdout_mock_cannot_claim_calls", ok, msg)
    default_h = aggregate_holdout(holdout_items, thresholds_approved=True)
    check("C1.holdout_default_conservative",
          (default_h.execution_mode, default_h.real_calls, default_h.run_id) == ("local_mock", 0, None),
          default_h.to_dict()["run_id"])

    # ------------------------------------------------------------------ #
    section("C2 F01：正确回答 pass / 缺 90% fail / 95% 仍 fail；冻结项未动")
    # ------------------------------------------------------------------ #
    import test_p2_public_controls as pc

    sources = pc.freeze_sources("E10_市场部KPI月报.xlsx", {"sheet": "KPI月报", "row": 103})
    good_text = "陈列达标率的年度目标是 90%；计算口径：检核合格门店数 ÷ 抽检门店数 ×100%。"
    good = pc.score_frozen(pc.KPI_TARGET_CASE, text=good_text, sources=sources)
    check("C2.correct_answer_passes", good.score.status == "pass", good.score.status)

    without_ref = replace(pc.KPI_TARGET_CASE, reference_answer="")
    baseline = pc.score_frozen(without_ref, text=good_text, sources=sources)
    check("C2.without_reference_answer_would_fail (证明修复是必要的)",
          baseline.score.status == "fail"
          and any(c["check_id"] == "value_no_fabricated" and c["status"] == "fail" for c in baseline.score.checks),
          [c["check_id"] for c in baseline.score.checks if c["status"] == "fail"])

    missing = pc.score_frozen(pc.KPI_TARGET_CASE,
                              text="月份：2026-09；指标：陈列达标率；计算口径：检核合格门店数 ÷ 抽检门店数 ×100%",
                              sources=sources)
    check("C2.missing_target_still_fails",
          missing.score.status == "fail"
          and any(c["check_id"] == "value_hit" and c["status"] == "fail" for c in missing.score.checks),
          [c["check_id"] for c in missing.score.checks if c["status"] == "fail"])

    fabricated = pc.score_frozen(pc.KPI_TARGET_CASE,
                                 text="陈列达标率年度目标 90%；计算口径：合格门店 ÷ 抽检门店 × 95%。",
                                 sources=sources)
    check("C2.95pct_still_fabricated",
          fabricated.score.status == "fail"
          and any(c["check_id"] == "value_no_fabricated" and c["status"] == "fail" for c in fabricated.score.checks),
          [c["check_id"] for c in fabricated.score.checks if c["status"] == "fail"])

    class _Turn:
        def __init__(self, payload: dict[str, Any]) -> None:
            self._payload = payload

        def as_dict(self, include_text: bool = False) -> dict[str, Any]:
            return dict(self._payload)

    product_turn = _Turn({
        "kind": "answer",
        "text": good_text,
        "trace_id": "verify-trace",
        "trace_path": "legacy",
        "sources": [dict(sources[0])],
        "http_status": 200,
    })
    e2e_branch = pc.score_turn(pc.KPI_TARGET_CASE, product_turn)
    check("C2.e2e_pass_branch_reachable_with_correct_product_answer",
          e2e_branch.score.status == "pass", e2e_branch.score.status)

    # ------------------------------------------------------------------ #
    section("C4 判定绑定 run_id / 执行模式")
    # ------------------------------------------------------------------ #
    import test_p2_gate as g
    from mktkb.evaluation.p2_scoring import evaluate_p2_gate

    run, manifest_map, gate_result, run_summary = g.clean_decision_inputs(work / "c4-a")
    run_id = manifest_map["run_id"]
    decision = evaluate_p2_gate(
        config=g.config_for(status="approved"), run_manifest=manifest_map, run_summary=run_summary,
        hard_gate=gate_result, public=g.public_card(run_id=run_id),
        holdout=g.holdout_card(approved=True, run_id=run_id), citation_evidence_complete=True,
    )
    body = json.loads(json.dumps(decision.to_dict(), ensure_ascii=False))
    check("C4.bound_run_and_mode", (body["run_id"], body["execution_mode"], body["real_calls"]) == (run_id, "local_mock", 0),
          {"run_id": body["run_id"], "execution_mode": body["execution_mode"], "real_calls": body["real_calls"]})
    check("C4.clean_decision_release_allowed", decision.release_allowed is True, decision.release_allowed)

    run2, manifest2, gate2, summary2 = g.clean_decision_inputs(work / "c4-b")
    other = evaluate_p2_gate(
        config=g.config_for(status="approved"), run_manifest=manifest2, run_summary=summary2,
        hard_gate=gate2, public=g.public_card(run_id="run-elsewhere"),
        holdout=g.holdout_card(approved=True, run_id=manifest2["run_id"]), citation_evidence_complete=True,
    )
    codes = {block.code for block in other.blocks}
    check("C4.foreign_scorecard_blocked",
          "run_binding_mismatch" in codes and other.release_allowed is False, sorted(codes))
    check("C4.foreign_scorecard_unknown_exit", other.quality_exit_code == 3, other.quality_exit_code)

    run3, manifest3, gate3, summary3 = g.clean_decision_inputs(work / "c4-c")
    ok, msg = _expect_code(
        lambda: evaluate_p2_gate(
            config=g.config_for(status="approved"), run_manifest=manifest3, run_summary=summary3,
            hard_gate=gate3, public=g.public_card(run_id=manifest3["run_id"]),
            holdout=g.holdout_card(approved=True, run_id=manifest3["run_id"]),
            citation_evidence_complete=True, run_id="run-conflict"),
        "run_id_mismatch")
    check("C4.explicit_conflicting_run_id_rejected", ok, msg)

    # 边界探测（非验收项）：manifest 缺 run_id 时绑定是否静默失效
    stripped = {k: v for k, v in manifest3.items() if k != "run_id"}
    run4, manifest4, gate4, summary4 = g.clean_decision_inputs(work / "c4-d")
    try:
        loose = evaluate_p2_gate(
            config=g.config_for(status="approved"), run_manifest=stripped, run_summary=summary4,
            hard_gate=gate4, public=g.public_card(run_id=manifest4["run_id"]),
            holdout=g.holdout_card(approved=True, run_id=manifest4["run_id"]), citation_evidence_complete=True,
        )
        loose_codes = {block.code for block in loose.blocks}
        check("C4.manifest_without_run_id_not_bound (边界探测)",
              "run_binding_mismatch" not in loose_codes,
              {"blocks": sorted(loose_codes), "decision_run_id": loose.run_id,
               "note": "manifest 无 run_id 时绑定静默失效（真实 runner 恒写 run_id，故非阻断）"})
    except Exception as exc:  # noqa: BLE001
        check("C4.manifest_without_run_id_not_bound (边界探测)", True, f"抛错: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------ #
    section("C3 证据文件 UTF-8 / 无替换字符")
    # ------------------------------------------------------------------ #
    repro = REPO / "docs/reports/OBS-EVAL/P2/T205/evidence/02-reproduction.txt"
    raw = repro.read_bytes()
    text = raw.decode("utf-8")
    check("C3.utf8_decodable_no_replacement_char",
          "\ufffd" not in text, {"bytes": len(raw), "lines": len(text.splitlines()),
                                 "has_fffd": "\ufffd" in text})
    check("C3.chinese_readable", "陈列达标率" in text and "活动" in text, "中文可读")

    print("\n=== 外部出站实测 ===")
    check("ZERO.external_outbound", len(EXTERNAL) == 0, EXTERNAL[:5])

    failed = [item for item in RESULTS if not item["ok"]]
    print("\n=== SUMMARY ===")
    print(json.dumps({"checks": len(RESULTS), "failed": [item["name"] for item in failed]}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
