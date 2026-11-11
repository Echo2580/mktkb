
"""Independent probe #3: single-variable A/B — same product observation, text present vs absent."""
from __future__ import annotations
import asyncio, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"backend/src")
from mktkb.evaluation import p2_score_run
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.p2_authorization import preflight_p2
from mktkb.evaluation.p2_contracts import (
    CHAT_HOST, CHAT_MODEL, CHAT_PRICING_SOURCE, CHAT_PROVIDER, CHAT_REGION, COST_CENTERS,
    P2_LEDGER_SNAPSHOT_SCHEMA_VERSION, P2LedgerSnapshot, P2PriceProfile, P2RequestItem, P2RunPlan)
from mktkb.evaluation.p2_runner import build_dry_run_authorization, run_p2
from mktkb.evaluation.product_adapter import (
    ChatBehavior, IngestSource, MockChatBackend, P2IngestPlan, P2RunDataset, ProductEvalAdapter)
from mktkb.evaluation.p2_scoring import score_public_case, load_p2_gate_config

ROOT = Path(".").resolve()
D01 = ROOT / "fixtures/acceptance/normal/D01_物品位置表.xlsx"
NOW = datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc)
ANSWER = "宣传海报存放在货架第二层"       # no digits -> no value_no_fabricated noise
OUT = {}

def price():
    return P2PriceProfile(kind="chat", model=CHAT_MODEL, provider=CHAT_PROVIDER, host=CHAT_HOST,
                          region=CHAT_REGION, pricing_source=CHAT_PRICING_SOURCE,
                          input_price_per_million_cny=2.0, output_price_per_million_cny=8.0,
                          prompt_tokens_cap=6144, completion_tokens_cap=800)

def plan_for(cases):
    items = []
    for c in cases:
        for t in range(1, (len(c.turns) if len(c.turns) >= 2 else 1) + 1):
            items.append(P2RequestItem(item_id=f"{c.case_id}:turn{t}:answer", operation="answer",
                                       cost_center="answer_retrieval", case_id=c.case_id, turn=t, page=0,
                                       requests=1, price_profile=price(), expected_success_cny=0.001))
    return P2RunPlan(schema_version="p2-run-plan/v0.1", plan_id="probe-ab", plan_version="v1", mode="end_to_end",
                     stage="P2-LIVE", created_utc="2026-11-11T00:00:00+00:00", project_total_limit_cny=40.0,
                     stage_limit_cny=20.0, max_requests=1000, cost_centers_cny={"answer_retrieval": 12.0, "ocr": 3.0,
                     "judge": 3.0, "independent": 2.0}, items=tuple(items))

def auth(plan):
    snap = P2LedgerSnapshot(schema_version=P2_LEDGER_SNAPSHOT_SCHEMA_VERSION, ledger_path="in-memory:probe",
        ledger_sha256="0"*64, historical_prefix_sha256="1"*64, budget_sha256="2"*64,
        total_limit_cny=40.0, historical_accounted_cny=15.0, accounted_cny=15.0, reservation_count=500,
        result_count=500, stage_allocations_cny={"S2-DEV":3.0,"P1-RETRIEVAL":2.0,"P2-LIVE":20.0},
        p2_stage_accounted_cny=0.0, p2_center_accounted_cny={c:0.0 for c in COST_CENTERS}, source="in-memory")
    pf = preflight_p2(plan, snap); assert pf.ok, pf.reasons
    return build_dry_run_authorization(plan, pf, now=NOW, nonce="3c"*16)

def cases(visibility):
    return (
        CaseSpec(case_id="AB-01", suite=("holdout" if visibility=="holdout" else "p2-public"), split="probe",
                 stratum="paraphrase", business_date="2026-10-28",
                 question="把城东店和城西店的宣传海报记录都列出来", expected_kind="answer",
                 expected_values=("第二层",), expected_sources=({"doc_code":"D01","unit_key":"sheet:物品位置:row:8"},),
                 relevant_units=({"doc_code":"D01","locator":{"sheet":"物品位置","row":8}},),
                 reference_answer="货架第二层", label_version="probe"),
        CaseSpec(case_id="AB-02", suite=("holdout" if visibility=="holdout" else "p2-public"), split="probe",
                 stratum="negative", business_date="2026-10-28", question="火星基地的年度预算编号是多少",
                 expected_kind="not_found", should_refuse=True, refusal_reason="语料无此项", label_version="probe"),
    )

def ds(cases_, vis):
    strata = {}
    for c in cases_: strata[c.stratum] = strata.get(c.stratum, 0) + 1
    return P2RunDataset(visibility=vis, cases=cases_, identity={"dataset_version":"probe-v1","label_version":"probe-v1",
        "suite":"p2-holdout","manifest_sha256":"e"*64,"case_count":len(cases_),"strata":strata})

def run(base: Path, vis: str, gate_config=None):
    cs = cases(vis); dataset = ds(cs, vis); plan = plan_for(cs); a = auth(plan)
    chat = MockChatBackend(behaviors=(ChatBehavior(answer=ANSWER),) * 6)
    adapter = ProductEvalAdapter(base / vis, chat=chat, dataset=dataset,
                                 ingest_plan=P2IngestPlan(sources=(IngestSource(path=D01),), label="probe"),
                                 purge_traces_on_close=(vis == "holdout"))
    try:
        result = asyncio.run(run_p2(plan, adapter=adapter, authorization=a, gate_config=gate_config, now=NOW))
    finally:
        asyncio.run(adapter.close())
    return adapter.paths.run_dir, result, chat

base = Path(os.environ["H2V_WORK"]) / "ab3"
assert not str(base.resolve()).startswith(str(Path.cwd().resolve())), "H2V_WORK 必须在仓库外"
base.mkdir(parents=True, exist_ok=True)
pub_dir, pub_res, pub_chat = run(base, "public")
rows = {}
for line in (pub_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        r = json.loads(line); rows[r["case_id"]] = r
codes = {"D01_物品位置表.xlsx":"D01","D01_物品位置表":"D01"}
idx = p2_score_run.source_index_from_rows(rows)
cs_pub = cases("public")
scores = {}
for case in cs_pub:
    sc = score_public_case(case, rows.get(case.case_id), document_codes=codes, source_index=idx,
                           allowed_doc_codes={"D01"}, execution_mode="local_mock", real_calls=0)
    scores[case.case_id] = {"status": sc.score.status,
                            "checks": [(c["check_id"], c["status"]) for c in sc.score.checks if c["status"] != "skipped"]}
# strip text from the very same row -> simulate the H2 row shape
stripped = json.loads(json.dumps(rows))
for case_id, row in stripped.items():
    for turn in row.get("turns") or ():
        (turn.get("product") or {}).pop("text", None)
idx2 = p2_score_run.source_index_from_rows(stripped)
scores_no_text = {}
for case in cs_pub:
    sc = score_public_case(case, stripped.get(case.case_id), document_codes=codes, source_index=idx2,
                           allowed_doc_codes={"D01"}, execution_mode="local_mock", real_calls=0)
    scores_no_text[case.case_id] = {"status": sc.score.status,
                                    "checks": [(c["check_id"], c["status"]) for c in sc.score.checks if c["status"] != "skipped"]}
obs = {}
for case_id, row in rows.items():
    turns = row.get("turns") or []
    prod = (turns[0].get("product") if turns else {}) or {}
    obs[case_id] = {"kind": prod.get("kind"), "sources": prod.get("sources"), "text_present": "text" in prod,
                    "text": prod.get("text")}
h2_dir, h2_res, h2_chat = run(base, "holdout")
card = json.loads((h2_dir / "holdout_scorecard.json").read_text(encoding="utf-8"))
gate = load_p2_gate_config()
h2g_dir, h2g_res, _ = run(base / "gated", "holdout", gate_config=gate)
card_g = json.loads((h2g_dir / "holdout_scorecard.json").read_text(encoding="utf-8"))
manifest_g = json.loads((h2g_dir / "run_manifest.json").read_text(encoding="utf-8"))
OUT = {
  "public": {"status": pub_res.status, "observations": obs, "scores_with_text": scores,
             "scores_after_stripping_text": scores_no_text, "chat_calls": pub_chat.call_count},
  "holdout": {"status": h2_res.status, "scorecard": card, "files": sorted(p.name for p in h2_dir.iterdir())},
  "holdout_with_gate": {"status": h2g_res.status, "card_subset": {k: card_g[k] for k in ("run_id","config_hash","execution_mode","real_calls","thresholds_approved","release_ready","min_pass","hard_failures_max")},
     "manifest": {"run_id": manifest_g.get("run_id"), "config_hash": manifest_g.get("config_hash"), "execution": manifest_g.get("execution")},
     "equal_run_id": card_g["run_id"] == manifest_g.get("run_id"),
     "equal_config_hash": card_g["config_hash"] == manifest_g.get("config_hash")},
}
print(json.dumps(OUT, ensure_ascii=False, indent=2))
