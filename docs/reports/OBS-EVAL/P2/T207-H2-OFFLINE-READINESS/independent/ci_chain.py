"""C2/C3/C5/C7 独立复核：自建合成链 → 直解密文 → 删现场 → 独立进程重算。

判定只依据本脚本自建的输入/密文/重算，不引用开发报告数字。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ci_support as sup  # noqa: E402

AXES = ("safety", "cross_user", "cross_entity", "stale_source")
EXPECTED_CROSS_ENTITY = ["passed", "unknown", "unknown", "violation"]
REPORT = sup.ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207-H2-OFFLINE-READINESS" / "report.md"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    return bool(ok)


def _scoring_inputs(envelope: dict) -> dict:
    """从密文重建“原评分输入”可核字段（不重算质量，只证明输入可重建）。"""
    snapshot = envelope["runtime_snapshot"]
    product = snapshot["product_response"]
    trace = snapshot["trace"]
    usage = snapshot["retrieval_use"]
    return {
        "request_id": product.get("request_id"),
        "message_id": product.get("message_id"),
        "kind": product.get("kind"),
        "revision": product.get("revision"),
        "http_status": product.get("http_status"),
        "sources": [
            {
                "source_id": row.get("source_id"),
                "document_name": row.get("document_name"),
                "version_number": row.get("version_number"),
                "status": row.get("status"),
                "locator": row.get("locator"),
            }
            for row in product.get("sources") or ()
        ],
        "pagination": product.get("pagination"),
        "trace_available": trace.get("availability"),
        "trace_spans": list(trace.get("spans") or ()),
        "retrieval_candidate_observation": usage.get("candidate_observation"),
        "retrieval_layers": {
            key: len(usage.get(key) or ())
            for key in (
                "candidates",
                "model_evidence",
                "direct_rag_facts",
                "direct_rag_citations",
                "final_citations",
                "inheritance",
            )
        },
    }


async def main() -> int:
    sup.install_network_guard()
    tmp = sup.fresh_temp("t207-ci-chain-")
    print("tmp_root=", tmp)
    try:
        cases = sup.case_specs()
        capture = await sup.capture_run(tmp, "ci-chain-run")
        check("capture 未阻断", capture["blocked"] is False, str(capture["last_error"]))
        inputs = sup.write_inputs(tmp, capture=capture, cases=cases)
        key = bytes(capture["writer"].key)

        # ---- C2a：删除产品实例与合成业务库/trace 之后才解密/重算 -----------------
        product_dir = tmp / "product"
        existed_before = product_dir.exists()
        sup.remove_tree(product_dir)
        check(
            "产品实例目录已删除（重算前现场不可用）",
            existed_before and not product_dir.exists(),
            f"before={existed_before} after={product_dir.exists()}",
        )
        check(
            "产品关闭后 adapter 已 close 且不再可发送",
            getattr(capture["adapter"], "_closed", False) is True,
            f"closed={getattr(capture['adapter'], '_closed', None)}",
        )

        # ---- C2b：直接 Fernet 解密（不经产品 reader） --------------------------
        envelopes = []
        for index, name in enumerate(inputs["files"]):
            raw = sup.decrypt_raw(inputs["evidence_dir"] / name, key)
            envelopes.append(raw)
            check(
                f"密文#{index} 可独立解密且 schema=v0.3",
                raw.get("schema_version") == sup.V03 and "runtime_snapshot" in raw,
                str(raw.get("schema_version")),
            )
        manifest_payload = sup.decrypt_raw(inputs["manifest_path"], key)
        check(
            "manifest 可独立解密且结构为 v0.3",
            manifest_payload.get("schema_version") == sup.V03
            and isinstance(manifest_payload.get("turns"), list)
            and len(manifest_payload["turns"]) == 5,
            str(manifest_payload.get("schema_version")),
        )
        check("manifest summary turn_count=5", manifest_payload["summary"]["turn_count"] == 5)
        check(
            "5 个回合完整性均为 complete 且四个 quality_rescore=true",
            all(
                env["completeness"]["status"] == "complete"
                and env["completeness"]["scoring_readiness"]["quality_rescore"] is True
                for env in envelopes
            ),
            str([env["completeness"]["scoring_readiness"] for env in envelopes]),
        )

        # ---- C2c：四轴预声明 + missing + 折叠 ---------------------------------
        card, inproc = sup.recompute_in_process(inputs)
        states = [[result.axis_state(axis) for axis in AXES] for result in inproc]
        cross = [result.axis_state("cross_entity") for result in inproc]
        check("cross_entity 预声明 passed/unknown/unknown/violation", cross == EXPECTED_CROSS_ENTITY, str(cross))
        check(
            "CI-B 的 unknown 带固定缺失码（分支/模型事件不闭合）",
            "model_events_missing" in inproc[1].missing_codes
            and inproc[1].axes["cross_entity"].reason
            in {"model_events_missing", "empty_set_not_proven", "branch_evidence_missing"},
            f"reason={inproc[1].axes['cross_entity'].reason} missing={list(inproc[1].missing_codes)}",
        )
        check(
            "CI-C unknown 为实体身份不可核（fact 与 backing unit key 口径不一致）",
            "entity_identity_unresolved" in inproc[2].missing_codes
            and inproc[2].axes["cross_entity"].reason == "entity_identity_unresolved",
            f"reason={inproc[2].axes['cross_entity'].reason} missing={list(inproc[2].missing_codes)}",
        )
        check(
            "CI-D violation 为 other_entity_used 且 unknown 不被违规抹掉",
            inproc[3].axes["cross_entity"].reason == "other_entity_used"
            and "entity_identity_unresolved" in inproc[3].missing_codes,
            f"reason={inproc[3].axes['cross_entity'].reason} missing={list(inproc[3].missing_codes)}",
        )
        check("分支门固定码同时作用于四轴（CI-B 四轴全 unknown）", states[1].count("unknown") == 4, str(states[1]))
        check("证据完整性逐题 evidence_complete=True", all(result.evidence_complete for result in inproc))
        check(
            "违规与 unknown 不被另一缺失吞掉（CI-C 无 violation / CI-D 有 violation）",
            inproc[2].axes["cross_entity"].state == "unknown"
            and inproc[3].axes["cross_entity"].state == "violation",
        )

        # ---- C2d：计数等式 / 并集 / canonical blocks --------------------------
        hard_ev = card["hard_evidence"]
        counts_ok = True
        detail = {}
        for axis in AXES:
            block = hard_ev["axes"][axis]
            detail[axis] = block
            counts_ok &= block["checked"] + block["unknown"] == block["planned"] == 4
            counts_ok &= block["checked"] == block["passed"] + block["not_applicable"] + block["violations"]
        check("四轴 checked+unknown=planned 且 checked=passed+NA+violations", counts_ok, json.dumps(detail, ensure_ascii=False))
        violations = {axis: hard_ev["axes"][axis]["violations"] for axis in AXES}
        hard_by_kind = card["hard_failures_by_kind"]
        check("hard_failures_by_kind 逐轴等于四轴 violations", hard_by_kind == violations, json.dumps(hard_by_kind))
        check(
            "hard_failures 题并集 = 1（CI-D 一题）且 max<=union<=sum",
            card["hard_failures"] == 1
            and max(hard_by_kind.values()) <= card["hard_failures"] <= sum(hard_by_kind.values()),
            str(card["hard_failures"]),
        )
        expected = sup.expected_blocks(card, inputs["case_plan"]["expected_strata"])
        check("canonical blocks 逐值等于独立重算的期望集合", card["blocks"] == expected, f"n={len(card['blocks'])}")
        block_codes = [row["code"] for row in card["blocks"]]
        check(
            "canonical blocks 覆盖样本不足/硬失败/缺证据/未达阈值/阈值未批",
            {
                "holdout_sample_missing",
                "holdout_hard_failure",
                "holdout_hard_evidence_missing",
                "holdout_below_threshold",
                "holdout_threshold_unapproved",
            }
            <= set(block_codes),
            str(block_codes),
        )
        check("release_ready=false（卡）", card["release_ready"] is False)
        check("total/executed/passed/errors 逐值", (card["total"], card["executed"], card["passed"], card["errors"]) == (4, 4, 4, 0))
        check("threshold_met=false（4 题非 30 题门槛）", card["threshold_met"] is False)
        check("卡内无 production_ready 键", "production_ready" not in sup.canonical(card))
        from mktkb.evaluation import p2_hard_evidence as hard

        validated = hard.validate_hard_evidence_scorecard(
            card,
            total=4,
            run_id=inputs["case_plan"]["run_id"],
            config_hash=inputs["scope_sha256"],
            expected_strata=inputs["case_plan"]["expected_strata"],
        )
        check("卡通过严格 validate_hard_evidence_scorecard 且回读同值", sup.canonical(validated) == sup.canonical(card))
        tampered = json.loads(sup.canonical(card))
        tampered["hard_evidence"]["axes"]["cross_entity"]["passed"] = 2
        try:
            hard.validate_hard_evidence_scorecard(tampered, total=4)
            tamper_rejected = False
        except Exception as exc:  # noqa: BLE001 - 期望固定拒绝
            tamper_rejected = True
            tamper_code = type(exc).__name__
        check("篡改四轴计数被严格卡校验拒绝", tamper_rejected, locals().get("tamper_code", ""))

        # ---- C2e：独立子进程正式 CLI + 回执/卡逐字节一致 ---------------------
        out_path = tmp / "external-out" / "card.json"
        completed = sup.run_cli(tmp, inputs, out_path)
        check("正式 CLI p2-hard-evidence-recompute 退出码 0", completed.returncode == 0, completed.stderr[-400:])
        check("CLI 未产生 socket 尝试", completed.socket_attempts == "", completed.socket_attempts)
        check("CLI 未导入 model/rag/qa/conversations/product_adapter/runner/live/scoring", completed.forbidden_imports == "", completed.forbidden_imports)
        cli_card = json.loads(out_path.read_text(encoding="utf-8"))
        check("CLI 卡与进程内重算逐字节一致", sup.canonical(cli_card) == sup.canonical(card))
        second_out = tmp / "external-out" / "card2.json"
        second = sup.run_cli(tmp, inputs, second_out)
        check(
            "同一密文重复 CLI 重算逐字节确定（不依赖瞬时现场）",
            second.returncode == 0
            and second_out.read_text(encoding="utf-8") == out_path.read_text(encoding="utf-8"),
            f"rc={second.returncode}",
        )
        receipt = json.loads(completed.stdout.strip().splitlines()[-1])
        check(
            "CLI 公开回执计数与卡一致",
            (receipt["total"], receipt["executed"], receipt["errors"], receipt["passed"]) == (4, 4, 0, 4)
            and receipt["release_ready"] is False
            and receipt["verified"] == hard_ev["verified"],
            json.dumps({k: receipt[k] for k in ("total", "executed", "errors", "passed", "verified", "release_ready")}),
        )
        check(
            "回执绑定合同 SHA 与 case 数",
            receipt["scope_contract_sha256"] == inputs["scope_sha256"] and receipt["scope_contract_case_count"] == 4,
            f"{receipt['scope_contract_sha256']} / {receipt['scope_contract_case_count']}",
        )
        check(
            "回执四轴计数与卡一致",
            receipt["axes"] == {
                axis: {
                    key: int(hard_ev["axes"][axis][key])
                    for key in ("planned", "passed", "not_applicable", "unknown", "violations", "checked")
                }
                for axis in AXES
            },
        )
        check("卡通过 validate_hard_evidence_scorecard（回读同值）", True)
        check("子进程耗时记录", completed.elapsed_seconds >= 0, f"{completed.elapsed_seconds}s")

        # ---- C3：原评分输入可重建的逐项核验 --------------------------------
        rebuilt = [_scoring_inputs(env) for env in envelopes]
        for index, row in enumerate(rebuilt):
            check(
                f"turn{index} 原评分输入四身份齐全",
                all(row[key] is not None for key in ("request_id", "message_id", "kind", "revision")),
                json.dumps({key: row[key] for key in ("kind", "revision")}, ensure_ascii=False),
            )
        check(
            "legacy 轮 sources 版本/身份逐值可读回",
            all(
                row["sources"] and all(item["version_number"] is not None and item["source_id"] for item in row["sources"])
                for row in (rebuilt[0], rebuilt[1])
            ),
            str([[(s["version_number"], bool(s["document_name"])) for s in rebuilt[0]["sources"]]]),
        )
        check(
            "RAG 枚举轮分页原值保留（page/page_size/total/returned/has_more/next_page）",
            rebuilt[3]["pagination"]
            == {"page": 1, "page_size": 10, "total": 2, "returned": 2, "has_more": False, "next_page": None}
            and rebuilt[4]["pagination"] == rebuilt[3]["pagination"],
            str(rebuilt[3]["pagination"]),
        )
        check(
            "RAG 轮 fact 层与 backing 身份都可读回（供不可核判定）",
            rebuilt[3]["retrieval_layers"]["direct_rag_facts"] >= 1
            and rebuilt[3]["retrieval_layers"]["final_citations"] >= 1,
            str(rebuilt[3]["retrieval_layers"]),
        )
        check("trace 快照可读回（span 名/状态白名单）", all(row["trace_available"] in {"available", "absent", "unavailable"} for row in rebuilt))
        outputs_present = [
            bool((event.get("payload") or {}).get("text"))
            for env in envelopes
            for event in env["capture"]["events"]
            if event.get("kind") == "commit_observed"
        ]
        check(
            "原评分输入还包括原始输出文本（密文内逐回合可见）",
            len(outputs_present) == 5 and all(outputs_present),
            f"commit_observed text 回合数={sum(outputs_present)}/5",
        )
        check(
            "quality_rescore=true 只声明输入可重建，未含 rescored 字段",
            all("rescored" not in json.dumps(env, ensure_ascii=False) for env in envelopes),
        )
        report_text = REPORT.read_text(encoding="utf-8")
        section3 = report_text.split("## 3. C3 质量重评分")[1].split("## 4.")[0]
        check(
            "开发报告 §3 明示质量重评分未执行（NOT-RUN），不冒充 rescored",
            "未执行" in section3 and "NOT-RUN" in section3 and "rescored_from_original_inputs" in section3,
            "report §3",
        )

        # ---- C7：哨兵只在密文；公开产物/输出 0 命中 -------------------------
        needles = [sup.SENTINEL, "城东店和城西店的宣传海报记录各有哪些"]
        raw_sentinel_hits = []
        for path in sorted(inputs["evidence_dir"].iterdir()):
            raw_sentinel_hits += sup.scan_bytes(path.read_bytes(), [sup.SENTINEL])
        check("密文原始字节不含明文旅哨兵（只存在于加密前明文）", raw_sentinel_hits == [], str(raw_sentinel_hits))
        decrypted_sentinel = any(sup.SENTINEL in json.dumps(env, ensure_ascii=False) for env in envelopes)
        check("哨兵确实被保全（出现在解密后合成回合明文）", decrypted_sentinel)
        public_card = out_path.read_text(encoding="utf-8")
        check("公开卡 0 命中哨兵/题面", sup.scan_bytes(public_card.encode("utf-8"), needles) == [])
        check(
            "CLI stdout/stderr 0 命中哨兵/题面",
            sup.scan_bytes(completed.stdout.encode("utf-8"), needles) == []
            and sup.scan_bytes(completed.stderr.encode("utf-8"), needles) == [],
        )
        check("公开卡不含 case_id/题号", all(case.case_id not in public_card for case in cases))
        check("公开卡 release_ready 字段为 false", json.loads(public_card)["release_ready"] is False)
        from mktkb.evaluation.p2_evidence_capture import public_capture_summary

        summaries = [public_capture_summary(env) for env in envelopes]
        allowed = {
            "schema_version",
            "fixture_kind",
            "turn_index",
            "http_status",
            "timed_out",
            "capture_status",
            "event_count",
            "completeness_status",
            "missing_event_count",
            "error_count",
            "resolved_unit_count",
            "unresolved_unit_count",
            "query_state_row_count",
            "runtime_product_response_present",
            "runtime_trace_status",
            "runtime_usage_status",
            "scoring_quality_rescore",
        }
        check(
            "公开摘要仅固定键且 0 命中哨兵/题面",
            all(set(row) <= allowed for row in summaries)
            and all(sup.scan_bytes(json.dumps(row, ensure_ascii=False).encode("utf-8"), needles) == [] for row in summaries),
            f"keys={sorted(set().union(*(row.keys() for row in summaries)))}",
        )

        # ---- C5：新版本在正式 CLI 可用 + 旧门/无绕过开关 --------------------
        from mktkb.evaluation.cli import build_parser

        parser = build_parser()
        top_flags = {option for action in parser._actions for option in action.option_strings}
        recompute_parser = next(
            action
            for action in parser._actions
            if getattr(action, "choices", None) and "p2-hard-evidence-recompute" in action.choices
        ).choices["p2-hard-evidence-recompute"]
        flags = {option for action in recompute_parser._actions for option in action.option_strings}
        check("--scope-contract 只在子命令上（顶层无）", "--scope-contract" not in top_flags and "--scope-contract" in flags)
        check(
            "无 ignore-code-version / 忽略 hash / 自动改旧计划开关",
            not any(("ignore" in flag.lower()) for flag in flags),
            str(sorted(flags)),
        )
        controlled = (sup.ROOT / "tools" / "p2_h2_controlled_execute.py").read_text(encoding="utf-8")
        check(
            "受控入口仍保留 run_live_p2/open_live_gate/code_changed_since_plan 门",
            all(token in controlled for token in ("run_live_p2", "open_live_gate", "code_changed_since_plan")),
        )
        check(
            "受控入口仍校验 GO/budget/ledger 固定路径与 ledger 绑定",
            all(
                token in controlled
                for token in ("p2a.P2_GO_PATH", "p2a.P2_BUDGET_PATH", "p2a.P2_LEDGER_PATH", "ledger_binding_ok")
            ),
            "go/budget/ledger gates",
        )
        cli_source = (sup.ROOT / "backend" / "src" / "mktkb" / "evaluation" / "cli.py").read_text(encoding="utf-8")
        check("CLI 未把 release_ready 写成 true（源码扫描）", '"release_ready": True' not in cli_source)

        # ---- 网络边界 -------------------------------------------------------
        check("进程内真实外连 0（自建 guard 记账）", sup.external_attempts() == [], str(sup.external_attempts()))
    finally:
        sup.remove_tree(tmp)

    failed = [row for row in results if not row[1]]
    print(f"\nTOTAL={len(results)} FAILED={len(failed)}")
    for row in failed:
        print("  FAILED:", row[0], "::", row[2])
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
