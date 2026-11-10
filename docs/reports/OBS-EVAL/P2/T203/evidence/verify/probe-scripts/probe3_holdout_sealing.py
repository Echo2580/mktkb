"""T203 独立验收探针 3：holdout 只写聚合 + trace 删除 + 产物无题干（合成夹具）。

自写断言：
1. holdout run 只产 holdout_aggregate.json；无 cases.jsonl / requests.jsonl；
2. close(purge_traces_on_close=True) 后 trace 库不存在；
3. p2-run 产物（manifest/summary/run_result/gate/holdout_aggregate）里没有题干、没有 case_id；
4. 额外：不删 trace 时，trace 库（content_mode=hash）里也没有题干明文；
5. 如实报告隔离 out_dir 里**其它**文件是否含题干（业务库/索引库属产品数据）；
6. 公开 run 与 holdout 互斥：holdout 分支不得回退成逐题落盘。
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[8]
sys.path.insert(0, str(REPO / "backend" / "src"))

from mktkb.evaluation.dataset import CaseSpec  # noqa: E402
from mktkb.evaluation.p2_authorization import preflight_p2  # noqa: E402
from mktkb.evaluation.p2_contracts import (  # noqa: E402
    CHAT_HOST, CHAT_MODEL, CHAT_PRICING_SOURCE, CHAT_PROVIDER, CHAT_REGION, COST_CENTERS,
    P2_LEDGER_SNAPSHOT_SCHEMA_VERSION, P2LedgerSnapshot, P2PriceProfile, P2RequestItem, P2RunPlan,
)
from mktkb.evaluation.p2_runner import build_dry_run_authorization, run_p2  # noqa: E402
from mktkb.evaluation.product_adapter import (  # noqa: E402
    MockChatBackend, P2RunDataset, ProductEvalAdapter,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
MARKER = "验收探针专属题干MARKER9Z7Q"
CASE_ID = "VH01"


def profile() -> P2PriceProfile:
    return P2PriceProfile(
        kind="chat", model=CHAT_MODEL, provider=CHAT_PROVIDER, host=CHAT_HOST,
        region=CHAT_REGION, pricing_source=CHAT_PRICING_SOURCE,
        input_price_per_million_cny=2.0, output_price_per_million_cny=8.0,
        prompt_tokens_cap=6144, completion_tokens_cap=800,
    )


def plan() -> P2RunPlan:
    case = CaseSpec(case_id=CASE_ID, suite="probe", split="holdout", stratum="paraphrase",
                    business_date="2026-11-10", question=MARKER, turns=(), label_version="probe")
    return P2RunPlan(
        schema_version="p2-run-plan/v0.1", plan_id="verify-probe3", plan_version="v1",
        mode="end_to_end", stage="P2-LIVE", created_utc="2026-11-10T00:00:00+00:00",
        project_total_limit_cny=40.0, stage_limit_cny=20.0, max_requests=1000,
        cost_centers_cny={"answer_retrieval": 12.0, "ocr": 3.0, "judge": 3.0, "independent": 2.0},
        items=(P2RequestItem(item_id=f"{CASE_ID}:turn1:answer", operation="answer",
                             cost_center="answer_retrieval", case_id=CASE_ID, turn=1, page=0,
                             requests=1, price_profile=profile(), expected_success_cny=0.001),),
    )


def snapshot(p: P2RunPlan) -> P2LedgerSnapshot:
    return P2LedgerSnapshot(
        schema_version=P2_LEDGER_SNAPSHOT_SCHEMA_VERSION, ledger_path="in-memory:verify",
        ledger_sha256="0" * 64, historical_prefix_sha256="1" * 64, budget_sha256="2" * 64,
        total_limit_cny=float(p.project_total_limit_cny), historical_accounted_cny=15.0709445,
        accounted_cny=15.0709445, reservation_count=505, result_count=505,
        stage_allocations_cny={"S2-DEV": 3.0, "P1-RETRIEVAL": 2.0, "P2-LIVE": 20.0},
        p2_stage_accounted_cny=0.0, p2_center_accounted_cny={c: 0.0 for c in COST_CENTERS},
        source="in-memory",
    )


def dataset() -> P2RunDataset:
    case = CaseSpec(case_id=CASE_ID, suite="probe", split="holdout", stratum="paraphrase",
                    business_date="2026-11-10", question=MARKER, turns=(), label_version="probe")
    return P2RunDataset(
        visibility="holdout", cases=(case,),
        identity={"dataset_version": "verify-probe3", "label_version": "probe", "suite": "probe",
                  "manifest_sha256": "f" * 64, "case_count": 1},
    )


def scan(root: Path, needle: str) -> list[str]:
    hits = []
    raw = needle.encode("utf-8")
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if raw in data:
            hits.append(str(path.relative_to(root)))
    return hits


def main() -> int:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="p2t203-probe3-"))
    result: dict = {"probe": "holdout_sealing", "ok": False, "checks": []}
    result["scratch_root"] = str(root)

    def check(name, ok, detail=None):
        result["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise AssertionError(f"{name}: {detail!r}")

    p, ds = plan(), dataset()
    pre = preflight_p2(p, snapshot(p))
    auth = build_dry_run_authorization(p, pre, now=NOW, nonce="0f" * 16)

    async def scenario() -> None:
        chat = MockChatBackend()
        adapter = ProductEvalAdapter(root / "holdout", chat=chat, dataset=ds,
                                     purge_traces_on_close=True)
        run_dir = adapter.paths.run_dir
        try:
            res = await run_p2(p, adapter=adapter, authorization=auth, now=NOW)
            aggregate = json.loads((run_dir / "holdout_aggregate.json").read_text(encoding="utf-8"))
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            files = sorted(x.name for x in run_dir.iterdir())
        finally:
            await adapter.close()

        check("holdout_run_not_failed_by_authorization", res.stop_code not in
              {"plan_authorization_mismatch", "authorization_expired"}, res.as_dict())
        check("holdout_no_cases_file", "cases.jsonl" not in files, files)
        check("holdout_no_requests_file", "requests.jsonl" not in files, files)
        check("holdout_aggregate_present", "holdout_aggregate.json" in files, files)
        check("holdout_detail_export_false", aggregate["detail_export"] is False, aggregate.get("detail_export"))
        check("holdout_no_case_id_in_aggregate", CASE_ID not in json.dumps(aggregate, ensure_ascii=False),
              "case_id 出现在聚合里")
        check("holdout_no_question_in_aggregate", MARKER not in json.dumps(aggregate, ensure_ascii=False),
              "题干出现在聚合里")
        check("holdout_trace_purged", not adapter.paths.trace_db.exists(), str(adapter.paths.trace_db))
        check("holdout_summary_policy", summary["holdout"] == {"aggregate_only": True,
                                                               "trace_retention": "purged-at-close"},
              summary.get("holdout"))
        artifact_hits = [name for name in files if MARKER in (run_dir / name).read_text(encoding="utf-8", errors="ignore")]
        check("holdout_artifacts_no_question", artifact_hits == [], artifact_hits)

        # 4) 不删 trace 时：hash 模式 trace 库不含题干明文
        adapter2 = ProductEvalAdapter(root / "keep-trace", chat=MockChatBackend(), dataset=ds,
                                      purge_traces_on_close=False)
        try:
            await run_p2(p, adapter=adapter2, authorization=auth, now=NOW)
            trace_db = adapter2.paths.trace_db
            trace_hits = scan(adapter2.paths.root, MARKER)
            trace_exists = trace_db.exists()
        finally:
            await adapter2.close()
        check("trace_db_exists_without_purge", trace_exists, str(trace_db))
        check("trace_db_has_no_plaintext_question",
              all("qa-traces" not in hit for hit in trace_hits), trace_hits)

        # 5) 如实报告：隔离 out_dir 里其它文件（产品业务库/索引库）是否含题干
        all_hits = scan(root, MARKER)
        result["question_text_found_in_files"] = all_hits
        result["product_data_files_with_question"] = [
            hit for hit in all_hits if "p2-run" not in hit.replace("\\", "/")
        ]

    try:
        asyncio.run(scenario())
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()[-2000:]
    Path(__file__).resolve().with_name("probe3_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": result.get("ok"), "error": result.get("error"),
                      "failed": [c["name"] for c in result["checks"] if not c["ok"]],
                      "question_in_files": result.get("question_text_found_in_files")}, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
