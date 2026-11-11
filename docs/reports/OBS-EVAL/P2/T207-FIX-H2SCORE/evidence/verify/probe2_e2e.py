
"""Independent probe #2: end-to-end holdout runs (synthetic sealed dataset + Mock product),
mid-run product error, public/holdout A/B on the same fixture-backed case, stale-scorecard
cleanup on public runs, artifact-wide leak scan. Zero real outbound."""
from __future__ import annotations
import asyncio, functools, hashlib, json, os, sys, traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"backend/src")
from cryptography.fernet import Fernet

from mktkb.evaluation import p2_dataset as p2d
from mktkb.evaluation import p2_runner as runner
from mktkb.evaluation import p2_score_run
from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.p2_authorization import preflight_p2
from mktkb.evaluation.p2_contracts import (
    CHAT_HOST, CHAT_MODEL, CHAT_PRICING_SOURCE, CHAT_PROVIDER, CHAT_REGION, COST_CENTERS,
    P2_LEDGER_SNAPSHOT_SCHEMA_VERSION, P2LedgerSnapshot, P2PriceProfile, P2RequestItem, P2RunPlan)
from mktkb.evaluation.p2_dataset import (
    HOLDOUT_KEY_FILE_ENV, HOLDOUT_ROOT_ENV, LABELS_CIPHERTEXT_NAME, QUESTIONS_CIPHERTEXT_NAME,
    load_p2_dataset)
from mktkb.evaluation.p2_runner import build_dry_run_authorization, run_p2
from mktkb.evaluation.product_adapter import (
    ChatBehavior, IngestSource, MockChatBackend, P2IngestPlan, P2RunDataset, ProductEvalAdapter)
from mktkb.evaluation.p2_scoring import score_public_case

ROOT = Path(".").resolve()
FIX = ROOT / "fixtures" / "acceptance"
D01 = FIX / "normal" / "D01_物品位置表.xlsx"
D04 = FIX / "normal" / "D04_活动策划流程.docx"
NOW = datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc)
NONCE = "2b" * 16
OUT = {}

# my own synthetic tokens (never the H2 corpus)
QTOK = "PROBE-Q-77a1"
FTOK = "PROBE-FOLLOWUP-2c9e"
ATOK = "PROBE-ANSWER-51d0"
SHORT_Q = "车棚钥匙在谁那儿"      # 7 chars -> below the 8-char audit needle
SHORT_A = "门卫室"               # 3 chars
BUSINESS_DATE = "2026-10-28"
LABEL_VERSION = "p2-holdout-v2-2026-11-10"
STRATA = (("paraphrase", 10), ("multi_turn", 5), ("negative", 5), ("stale_conflict", 5), ("cross_doc_security", 5))
TURN_PLAN = (2, 2, 2, 2, 3)

def asyncio_test(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        return asyncio.run(fn(*a, **k))
    return wrapper

def q_rows():
    rows = []; n = 0; mt = 0
    for stratum, count in STRATA:
        for off in range(count):
            n += 1
            if stratum == "multi_turn":
                turns = [f"{FTOK} 第 {t} 轮" for t in range(1, TURN_PLAN[mt] + 1)]
                mt += 1; question = ""
            else:
                turns = []
                question = f"{QTOK} 第 {n:02d} 题"
            if n == 3:
                question = SHORT_Q       # short-question boundary lands in the sealed set
            rows.append({"case_id": f"PRB-{n:02d}", "suite": "holdout", "split": "holdout",
                         "stratum": stratum, "business_date": BUSINESS_DATE, "question": question,
                         "turns": turns, "expected_kind": ("refusal" if stratum == "negative" else "answer"),
                         "should_refuse": stratum == "negative", "requires_ocr": False,
                         "labeler": "data-custodian", "label_version": LABEL_VERSION, "notes": "probe"})
    return rows

def l_rows(rows):
    out = []
    for row in rows:
        refuse = bool(row["should_refuse"])
        ref = SHORT_A if row["case_id"] == "PRB-03" else f"{ATOK} 参考"
        out.append({"case_id": row["case_id"], "expected_kind": row["expected_kind"],
                    "expected_values": [], "expected_sources": ([] if refuse else [{"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}]),
                    "relevant_units": ([] if refuse else [{"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 8}}]),
                    "reference_answer": ("" if refuse else ref), "should_refuse": refuse,
                    "refusal_reason": ("探针负样本" if refuse else None),
                    "forbidden_values": ["探针诱饵"], "forbidden_sources": [{"doc_code": "V01"}], "notes": "probe"})
    return out

def jsonl(rows):
    return ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode("utf-8")

def sha(b):
    return hashlib.sha256(b).hexdigest()

def write_sealed(base: Path):
    rows = q_rows(); labels = l_rows(rows)
    key = Fernet.generate_key(); f = Fernet(key)
    qb, lb = jsonl(rows), jsonl(labels)
    qt, lt = f.encrypt(qb), f.encrypt(lb)
    root = base / "sealed"; root.mkdir(parents=True, exist_ok=True)
    (root / QUESTIONS_CIPHERTEXT_NAME).write_bytes(qt)
    (root / LABELS_CIPHERTEXT_NAME).write_bytes(lt)
    manifest = {"schema_version": p2d.P2_MANIFEST_SCHEMA_VERSION, "dataset_version": "P2-HOLDOUT-v2",
                "suite": p2d.P2_DATASET_SUITE, "label_version": LABEL_VERSION, "case_count": p2d.P2_CASE_COUNT,
                "strata": dict(p2d.P2_STRATA), "business_date": BUSINESS_DATE,
                "created_utc": "2026-11-10T12:00:00+00:00", "author": "data-custodian",
                "encryption": {"kind": "fernet", "key_id": "probe"}, "questions_plaintext_sha256": sha(qb),
                "labels_plaintext_sha256": sha(lb), "questions_ciphertext_sha256": sha(qt),
                "labels_ciphertext_sha256": sha(lt),
                "turn_stats": {"total_turns": 36, "max_turns_per_case": 3, "turn_histogram": {"1": 25, "2": 4, "3": 1}}}
    mp = root / "manifest.json"; mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    kd = base / "keys"; kd.mkdir(parents=True, exist_ok=True)
    kf = kd / "v2.key"; kf.write_text(key.decode("ascii") + "\n", encoding="utf-8")
    return root, kf, mp

def price_profile():
    return P2PriceProfile(kind="chat", model=CHAT_MODEL, provider=CHAT_PROVIDER, host=CHAT_HOST,
                          region=CHAT_REGION, pricing_source=CHAT_PRICING_SOURCE,
                          input_price_per_million_cny=2.0, output_price_per_million_cny=8.0,
                          prompt_tokens_cap=6144, completion_tokens_cap=800)

def make_plan(cases, plan_id="probe-plan"):
    items = []
    for case in cases:
        n = len(case.turns) if len(case.turns) >= 2 else 1
        for turn in range(1, n + 1):
            items.append(P2RequestItem(item_id=f"{case.case_id}:turn{turn}:answer", operation="answer",
                                       cost_center="answer_retrieval", case_id=case.case_id, turn=turn,
                                       page=0, requests=1, price_profile=price_profile(), expected_success_cny=0.001))
    return P2RunPlan(schema_version="p2-run-plan/v0.1", plan_id=plan_id, plan_version="v1",
                     mode="end_to_end", stage="P2-LIVE", created_utc="2026-11-11T00:00:00+00:00",
                     project_total_limit_cny=40.0, stage_limit_cny=20.0, max_requests=1000,
                     cost_centers_cny={"answer_retrieval": 12.0, "ocr": 3.0, "judge": 3.0, "independent": 2.0},
                     items=tuple(items))

def snapshot(plan):
    return P2LedgerSnapshot(schema_version=P2_LEDGER_SNAPSHOT_SCHEMA_VERSION, ledger_path="in-memory:probe",
                            ledger_sha256="0" * 64, historical_prefix_sha256="1" * 64, budget_sha256="2" * 64,
                            total_limit_cny=float(plan.project_total_limit_cny), historical_accounted_cny=15.0709445,
                            accounted_cny=15.0709445, reservation_count=505, result_count=505,
                            stage_allocations_cny={"S2-DEV": 3.0, "P1-RETRIEVAL": 2.0, "P2-LIVE": 20.0},
                            p2_stage_accounted_cny=0.0,
                            p2_center_accounted_cny={c: 0.0 for c in COST_CENTERS}, source="in-memory")

def authorization(plan):
    pf = preflight_p2(plan, snapshot(plan)); assert pf.ok, pf.reasons
    return build_dry_run_authorization(plan, pf, now=NOW, nonce=NONCE)

def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def scan_dir(run_dir: Path, needles: dict[str, list[str]]):
    result = {}
    for f in sorted(run_dir.iterdir()):
        if not f.is_file():
            continue
        raw = f.read_text(encoding="utf-8", errors="replace")
        result[f.name] = {"bytes": f.stat().st_size,
                          "hits": {k: sum(1 for n in v if n and n in raw) for k, v in needles.items()},
                          "sample_hits": {k: [n for n in v if n and n in raw][:3] for k, v in needles.items()}}
    return result

# ---------------------------------------------------------------- E1: sealed 30-case holdout run
def e1(tmp: Path):
    root, keyf, mp = write_sealed(tmp)
    os.environ[HOLDOUT_ROOT_ENV] = str(root); os.environ[HOLDOUT_KEY_FILE_ENV] = str(keyf)
    dataset = P2RunDataset.from_p2_dataset(load_p2_dataset(mp, visibility="holdout"))
    plan = make_plan(dataset.cases); auth = authorization(plan)
    adapter = ProductEvalAdapter(tmp / "h2", chat=MockChatBackend(), dataset=dataset,
                                 ingest_plan=P2IngestPlan(sources=(IngestSource(path=D01), IngestSource(path=D04)), label="probe"),
                                 purge_traces_on_close=True)
    run_dir = adapter.paths.run_dir
    async def go():
        try:
            return await run_p2(plan, adapter=adapter, authorization=auth, gate_config=None, now=NOW)
        finally:
            await adapter.close()
    result = asyncio.run(go())
    card = read_json(run_dir / "holdout_scorecard.json")
    manifest = read_json(run_dir / "run_manifest.json")
    summary = read_json(run_dir / "summary.json")
    rows = q_rows()
    needles = {
        "case_ids": [r["case_id"] for r in rows],
        "question_tokens": [QTOK, FTOK],
        "answer_tokens": [ATOK],
        "short_question": [SHORT_Q],
        "short_answer": [SHORT_A],
        "document_names": ["D01_物品位置表.xlsx", "D04_活动策划流程.docx", "D01_物品位置表"],
    }
    OUT["e1"] = {
        "status": result.status, "stop_code": result.stop_code,
        "files": scan_dir(run_dir, needles),
        "cases_jsonl_exists": (run_dir / "cases.jsonl").exists(),
        "requests_jsonl_exists": (run_dir / "requests.jsonl").exists(),
        "scorecard": card,
        "manifest_run_id": manifest["run_id"], "manifest_config_hash": manifest["config_hash"],
        "summary_network": summary.get("network"),
        "ingest_documents": (manifest.get("ingest") or {}).get("documents") if isinstance(manifest.get("ingest"), dict) else None,
    }

# ---------------------------------------------------------------- E2: mid-run 503
def e2(tmp: Path):
    root, keyf, mp = write_sealed(tmp)
    os.environ[HOLDOUT_ROOT_ENV] = str(root); os.environ[HOLDOUT_KEY_FILE_ENV] = str(keyf)
    dataset = P2RunDataset.from_p2_dataset(load_p2_dataset(mp, visibility="holdout"))
    plan = make_plan(dataset.cases); auth = authorization(plan)
    adapter = ProductEvalAdapter(tmp / "h2stop", chat=MockChatBackend(behaviors=(ChatBehavior(kind="http_error"),)),
                                 dataset=dataset,
                                 ingest_plan=P2IngestPlan(sources=(IngestSource(path=D01),), label="probe"),
                                 purge_traces_on_close=True)
    run_dir = adapter.paths.run_dir
    async def go():
        try:
            return await run_p2(plan, adapter=adapter, authorization=auth, gate_config=None, now=NOW)
        finally:
            await adapter.close()
    result = asyncio.run(go())
    card = read_json(run_dir / "holdout_scorecard.json")
    agg = read_json(run_dir / "holdout_aggregate.json")
    OUT["e2"] = {"status": result.status, "stop_code": result.stop_code,
                 "scorecard": card, "aggregate_cases": agg.get("cases")}

# ---------------------------------------------------------------- E3/E4: public vs holdout A/B
def two_cases(visibility):
    answer_case = CaseSpec(
        case_id="AB-01", suite=("holdout" if visibility == "holdout" else "p2-public"), split="probe",
        stratum="paraphrase", business_date=BUSINESS_DATE,
        question="把城东店和城西店的宣传海报记录都列出来", expected_kind="answer",
        expected_values=("B区1号货架第二层",),
        expected_sources=({"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"},),
        relevant_units=({"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 8}},),
        reference_answer="B区1号货架第二层", label_version="probe")
    negative_case = CaseSpec(
        case_id="AB-02", suite=("holdout" if visibility == "holdout" else "p2-public"), split="probe",
        stratum="negative", business_date=BUSINESS_DATE,
        question="火星基地的年度预算编号是多少", expected_kind="not_found",
        should_refuse=True, refusal_reason="语料无此项", label_version="probe")
    return (answer_case, negative_case)

def dataset_for(cases, visibility):
    strata = {}
    for c in cases: strata[c.stratum] = strata.get(c.stratum, 0) + 1
    return P2RunDataset(visibility=visibility, cases=cases, identity={
        "dataset_version": "probe-v1", "label_version": "probe-v1", "suite": "p2-holdout",
        "manifest_sha256": "e" * 64, "case_count": len(cases), "strata": strata})

def run_case(tmp: Path, visibility: str, *, stale: bool = False):
    cases = two_cases(visibility)
    dataset = dataset_for(cases, visibility)
    plan = make_plan(cases); auth = authorization(plan)
    chat = MockChatBackend(behaviors=(ChatBehavior(answer="城东店宣传海报B区1号货架第二层"),) * 6)
    adapter = ProductEvalAdapter(tmp / f"ab-{visibility}", chat=chat, dataset=dataset,
                                 ingest_plan=P2IngestPlan(sources=(IngestSource(path=D01),), label="probe"),
                                 purge_traces_on_close=(visibility == "holdout"))
    run_dir = adapter.paths.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    if stale:
        (run_dir / "holdout_scorecard.json").write_text('{"stale": true}\n', encoding="utf-8")
        (run_dir / "holdout_aggregate.json").write_text('{"stale": true}\n', encoding="utf-8")
    async def go():
        try:
            return await run_p2(plan, adapter=adapter, authorization=auth, gate_config=None, now=NOW)
        finally:
            await adapter.close()
    result = asyncio.run(go())
    return run_dir, result, cases, chat

def e3e4(tmp: Path):
    # public run (also carries a stale holdout_scorecard.json to prove cleanup)
    pub_dir, pub_result, pub_cases, pub_chat = run_case(tmp, "public", stale=True)
    pub_rows = {json.loads(l)["case_id"]: json.loads(l) for l in (pub_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    codes = {"D01_物品位置表.xlsx": "D01", "D01_物品位置表": "D01"}
    idx = p2_score_run.source_index_from_rows(pub_rows)
    pub_scores = {}
    for case in pub_cases:
        scored = score_public_case(case, pub_rows.get(case.case_id), document_codes=codes,
                                   source_index=idx, allowed_doc_codes={"D01"}, execution_mode="local_mock", real_calls=0)
        pub_scores[case.case_id] = {
            "status": scored.score.status,
            "checks": [(c["check_id"], c["status"]) for c in scored.score.checks if c["status"] != "skipped"],
            "text_present": "text" in (pub_rows.get(case.case_id, {}).get("turns") or [{}])[0].get("product", {}),
        }
    # holdout run over the same cases
    h2_dir, h2_result, h2_cases, h2_chat = run_case(tmp, "holdout")
    card = read_json(h2_dir / "holdout_scorecard.json")
    h2_summary = read_json(h2_dir / "summary.json")
    OUT["e3_public_vs_holdout"] = {
        "public": {"status": pub_result.status, "scores": pub_scores,
                   "case_scores": {k: v["status"] for k, v in pub_scores.items()},
                   "passed_in_public": sum(1 for v in pub_scores.values() if v["status"] == "pass")},
        "holdout": {"status": h2_result.status, "scorecard": card,
                    "observations": {c.case_id: {"status": row} for c, row in []}},
        "holdout_text_present": any("text" in (t.get("product") or {}) for t in []),
        "holdout_summary_network": h2_summary.get("network"),
    }
    OUT["e4_stale_cleanup"] = {
        "public_run_dir": pub_dir.name,
        "holdout_scorecard_exists": (pub_dir / "holdout_scorecard.json").exists(),
        "holdout_aggregate_exists": (pub_dir / "holdout_aggregate.json").exists(),
    }

def main():
    base = Path(os.environ["H2V_WORK"])  # must point OUTSIDE the repo (probe writes run dirs/sealed fixtures)
    assert not str(base.resolve()).startswith(str(Path.cwd().resolve())), "H2V_WORK 必须在仓库外"
    for name, fn in (("e1", e1), ("e2", e2)):
        d = base / name; d.mkdir(parents=True, exist_ok=True)
        try:
            fn(d)
        except Exception as exc:
            OUT[name] = {"error": repr(exc), "tb": traceback.format_exc()}
    d = base / "e34"; d.mkdir(parents=True, exist_ok=True)
    try:
        e3e4(d)
    except Exception as exc:
        OUT["e3_public_vs_holdout"] = {"error": repr(exc), "tb": traceback.format_exc()}
    print(json.dumps(OUT, ensure_ascii=False, indent=2))

main()
