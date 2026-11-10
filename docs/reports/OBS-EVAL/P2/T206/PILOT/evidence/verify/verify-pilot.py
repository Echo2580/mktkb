
# P2-T206 pilot independent verification (read-only; no network; no mktkb import).
import hashlib, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve()
while not (ROOT / "docs" / "evidence" / "LOCAL-R1-20261101").exists():
    if ROOT.parent == ROOT:
        raise SystemExit("repo root not found")
    ROOT = ROOT.parent
P = lambda rel: ROOT / rel
def bsha(raw): return hashlib.sha256(raw).hexdigest()
def fsha(rel): return bsha(P(rel).read_bytes())
def canon(obj, ensure_ascii=False):
    return json.dumps(obj, ensure_ascii=ensure_ascii, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
def payload_sha(obj): return bsha(canon(obj))

out = {"schema": "p2-t206-pilot-verify/v0.1", "read_only": True}

LEDGER = "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
BUDGET = "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
GO = "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json"
PILOT = "docs/reports/OBS-EVAL/P2/T206/PILOT/"
PLAN = "docs/reports/OBS-EVAL/P2/T206/PM/p2-pilot-plan-v0_2.json"

raw_ledger = P(LEDGER).read_bytes()
go = json.loads(P(GO).read_text(encoding="utf-8"))
budget = json.loads(P(BUDGET).read_text(encoding="utf-8"))
plan = json.loads(P(PLAN).read_text(encoding="utf-8"))
gate = json.loads(P(PILOT + "gate.json").read_text(encoding="utf-8"))
summary = json.loads(P(PILOT + "summary.json").read_text(encoding="utf-8"))
manifest = json.loads(P(PILOT + "run_manifest.json").read_text(encoding="utf-8"))
run_result = json.loads(P(PILOT + "run_result.json").read_text(encoding="utf-8"))
record = json.loads(P(PILOT + "pilot-record.json").read_text(encoding="utf-8"))
cases = [json.loads(l) for l in P(PILOT + "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

events = [json.loads(l) for l in raw_ledger.decode("utf-8").splitlines() if l.strip()]
RUN = "p2-t206-pilot-20261111-01"

# ---------- 1. hashes / identity
def historical_prefix_bytes(raw):
    buf = bytearray(); seen = False
    for line in raw.splitlines(keepends=True):
        if not line.strip(): continue
        if json.loads(line).get("event") != "historical_import": break
        buf.extend(line); seen = True
    if not seen: raise SystemExit("no historical_import")
    return bytes(buf)

prefix = historical_prefix_bytes(raw_ledger)
pilot_idx = [i for i, e in enumerate(events) if e.get("run_id") == RUN]
cut = pilot_idx[0]
prefix_at_cut = b"".join(l + b"\n" for l in raw_ledger.decode("utf-8").split("\n")[:cut][:-1]) if False else None
pre_bytes = raw_ledger.decode("utf-8").split("\n")
pre_txt = "\n".join(pre_bytes[:cut]) + "\n"
out["identity"] = {
    "ledger_pre_pilot_sha256": bsha(pre_txt.encode("utf-8")),
    "ledger_pre_pilot_lines": cut,
    "ledger_pre_pilot_bytes": len(pre_txt.encode("utf-8")),
    "ledger_now_sha256": bsha(raw_ledger),
    "ledger_now_lines": len(events),
    "ledger_now_bytes": len(raw_ledger),
    "historical_prefix_sha256": bsha(prefix),
    "budget_raw_sha256": fsha(BUDGET),
    "budget_canonical_sha256": payload_sha(budget),
    "go_raw_sha256": fsha(GO),
    "go_canonical_sha256": payload_sha(go),
    "plan_raw_sha256": fsha(PLAN),
}

# ---------- 2. plan projection -> plan_sha256 (independent reimplementation of P2RunPlan.as_dict)
def proj_item(it):
    return {
        "item_id": it["item_id"], "operation": it["operation"], "cost_center": it["cost_center"],
        "case_id": it["case_id"], "turn": int(it["turn"]), "page": int(it["page"]),
        "requests": int(it["requests"]),
        "price_profile": dict(it["price_profile"]),
        "expected_success_cny": float(it["expected_success_cny"]),
    }
plan_proj = {
    "schema_version": plan["schema_version"], "plan_id": plan["plan_id"],
    "plan_version": plan["plan_version"], "mode": plan["mode"], "stage": plan["stage"],
    "created_utc": plan["created_utc"],
    "project_total_limit_cny": float(plan["project_total_limit_cny"]),
    "stage_limit_cny": float(plan["stage_limit_cny"]),
    "max_requests": int(plan["max_requests"]),
    "cost_centers_cny": {k: float(v) for k, v in plan["cost_centers_cny"].items()},
    "items": [proj_item(i) for i in plan["items"]],
}
plan_sha = payload_sha(plan_proj)
out["plan"] = {
    "plan_sha256_recomputed": plan_sha,
    "matches_go_scope": plan_sha == go["scope"]["plan_sha256"],
    "items": len(plan["items"]),
    "requests_total": sum(int(i["requests"]) for i in plan["items"]),
    "by_operation": {},
    "max_requests": plan["max_requests"],
}
for it in plan["items"]:
    out["plan"]["by_operation"][it["operation"]] = out["plan"]["by_operation"].get(it["operation"], 0) + int(it["requests"])

def per_request_bound(pp):
    if pp["kind"] == "chat":
        return (pp["prompt_tokens_cap"] * pp["input_price_per_million_cny"]
                + pp["completion_tokens_cap"] * pp["output_price_per_million_cny"]) / 1e6
    if pp["kind"] in ("embedding", "rerank"):
        return pp["total_tokens_cap"] * pp["unit_price_per_million_cny"] / 1e6
    return pp["price_cny_per_page"] * pp["pages_per_request"]

bounds = [(i["item_id"], per_request_bound(i["price_profile"]), int(i["requests"])) for i in plan["items"]]
worst = sum(b * n for _, b, n in bounds)
out["plan"]["worst_case_cny_recomputed"] = round(worst, 6)
out["plan"]["reserve_peak_cny_recomputed"] = max(b for _, b, _ in bounds)
out["plan"]["over_go_max_request_cny"] = [i for i, b, _ in bounds if b > go["scope"]["max_request_cny"]]

# ---------- 3. GO surface
def days_between(a, b):
    from datetime import datetime
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 86400.0

required = ["document", "schema_version", "stage", "authorization", "issued_by", "nonce",
            "issued_utc", "expires_utc", "budget_ledger_path", "budget_ledger_sha256",
            "budget_total_limit_cny", "scope"]
missing = [k for k in required if k not in go]
scope = go["scope"]
plan_ops = set(out["plan"]["by_operation"])
plan_centers = set(plan["cost_centers_cny"])
out["go"] = {
    "missing_fields": missing,
    "is_draft": "DRAFT" in json.dumps(go, ensure_ascii=False).upper() or go.get("issued_by", "").lower().startswith("pm-candidate"),
    "document": go["document"], "stage": go["stage"],
    "nonce_len": len(go["nonce"]),
    "validity_days": round(days_between(go["issued_utc"], go["expires_utc"]), 3),
    "budget_total_limit_cny": go["budget_total_limit_cny"],
    "max_requests": scope["max_requests"],
    "max_requests_ok": 61 <= scope["max_requests"] <= 1000,
    "max_request_cny": scope["max_request_cny"],
    "operations": scope["operations"],
    "operations_cover_plan": plan_ops.issubset(set(scope["operations"])),
    "cost_centers_cny": scope["cost_centers_cny"],
    "cost_centers_cover_plan": plan_centers.issubset(set(scope["cost_centers_cny"])),
    "cost_centers_sum": sum(scope["cost_centers_cny"].values()),
    "stage_limits_cny": scope["stage_limits_cny"],
    "ledger_binding_matches_prefix": scope is not None and go["budget_ledger_sha256"] == bsha(prefix),
    "ledger_binding_matches_pre_pilot_file": go["budget_ledger_sha256"] == bsha(pre_txt.encode("utf-8")),
    "ledger_path_matches_fixed": go["budget_ledger_path"].replace("\\", "/") == LEDGER,
}

# ---------- 4. budget surface
stages = budget["stages"]
alloc_sum = sum(float(v) for v in stages.values())
out["budget"] = {
    "limit_cny": budget["limit_cny"],
    "p2_live_allocation_cny": stages.get("P2-LIVE"),
    "stage_allocation_sum": round(alloc_sum, 8),
    "arithmetic_closes": abs(alloc_sum + float(budget["historical_conservative_accounted_cny"]) - float(budget["limit_cny"])) <= 1e-9,
    "historical_conservative_accounted_cny": budget["historical_conservative_accounted_cny"],
    "historical_success_estimated_list_price_cny": budget["historical_success_estimated_list_price_cny"],
    "remaining_conservative_cny_at_start": budget["remaining_conservative_cny_at_start"],
    "remaining_matches_limit_minus_historical": round(float(budget["limit_cny"]) - float(budget["historical_conservative_accounted_cny"]), 7),
    "stage_revision_present": "stage_revision" in budget,
    "stage_revision_revised_at": budget.get("stage_revision", {}).get("revised_at"),
    "budget_mtime_utc": __import__("datetime").datetime.utcfromtimestamp(P(BUDGET).stat().st_mtime).isoformat() + "Z",
}

# ---------- 5. ledger delta
pilot = [e for e in events if e.get("run_id") == RUN]
reserved = [e for e in pilot if e["event"] == "reserved"]
results = [e for e in pilot if e["event"] == "result"]
rids = {e["reservation_id"] for e in reserved}
cids = {e["reservation_id"] for e in results}
sum_reserve = sum(float(e["reserve_cny"]) for e in reserved)
sum_charge = sum(float(e.get("conservative_charge_cny") or 0) for e in results)
center_reserve, center_charge, op_count, kind_count = {}, {}, {}, {}
for e in reserved:
    center_reserve[e.get("cost_center")] = round(center_reserve.get(e.get("cost_center"), 0.0) + float(e["reserve_cny"]), 7)
    op_count[e["metadata"]["operation"]] = op_count.get(e["metadata"]["operation"], 0) + 1
    kind_count[e["kind"]] = kind_count.get(e["kind"], 0) + 1
for e in results:
    m = next(x for x in reserved if x["reservation_id"] == e["reservation_id"])["metadata"]
    center_charge[m["cost_center"]] = round(center_charge.get(m["cost_center"], 0.0) + float(e.get("conservative_charge_cny") or 0), 7)
hist = next(e for e in events if e["event"] == "historical_import")["accounted_cny"]
total_charge_all = sum(float(e.get("conservative_charge_cny") or 0) for e in events if e["event"] == "result")
out["ledger_delta"] = {
    "events": len(pilot), "reserved": len(reserved), "results": len(results),
    "contiguous_block": pilot_idx == list(range(cut, cut + len(pilot))),
    "stages": sorted({e["stage"] for e in pilot}),
    "reserve_cny_sum": round(sum_reserve, 7),
    "charge_cny_sum": round(sum_charge, 7),
    "center_reserve": center_reserve, "center_charge": center_charge,
    "by_operation": op_count, "by_kind": kind_count,
    "reservations_without_result": sorted(rids - cids),
    "results_without_reservation": sorted(cids - rids),
    "statuses": {s: sum(1 for e in results if e["status"] == s) for s in {e["status"] for e in results}},
    "settlement_rejected": sum(1 for e in pilot if e.get("settlement_rejected")),
    "boundary_anomaly": sum(1 for e in pilot if e.get("boundary_anomaly") is True),
    "global_reservations": sum(1 for e in events if e["event"] == "reserved"),
    "p2_live_reservations_total": sum(1 for e in events if e["event"] == "reserved" and e["stage"] == "P2-LIVE"),
    "accounted_total_recomputed": round(float(hist) + total_charge_all, 7),
    "accounted_before_pilot": round(float(hist) + sum(float(e.get("conservative_charge_cny") or 0)
        for e in events[:cut] if e["event"] == "result"), 7),
    "recorded_prior_accounted_first": reserved[0]["prior_accounted_cny"],
    "recorded_stage_limit": reserved[0]["stage_limit_cny"],
    "recorded_total_limit": reserved[0]["total_limit_cny"],
    "unpaid_refusal_charge_cny": round(sum(float(e.get("conservative_charge_cny") or 0)
        for e in results if e["status"] == "failed"), 7),
    "paid_charge_cny": round(sum(float(e.get("conservative_charge_cny") or 0)
        for e in results if e["status"] == "succeeded"), 7),
    "failed_error_codes": sorted({e.get("error_code") for e in results if e["status"] != "succeeded"}),
}

# ---------- 6. artifact reconciliation
receipts = gate["attempts"]["receipts"]
rec_res = [r for r in receipts if r["phase"] == "reserve"]
rec_set = [r for r in receipts if r["phase"] != "reserve"]
out["reconciliation"] = {
    "gate_expected_reservations": gate["attempts"]["expected_reservations"],
    "gate_reserved": gate["attempts"]["gate_reserved"],
    "gate_reservations_non_answer": gate["attempts"]["reservations"],
    "gate_answer_reserved": gate["attempts"]["answer_reserved"],
    "gate_receipt_count": gate["attempts"]["receipt_count"],
    "gate_center_stage_total_cny": gate["attempts"]["center_stage_total_cny"],
    "gate_center_total_with_answers_cny": gate["attempts"]["center_total_with_answers_cny"],
    "gate_by_center": gate["attempts"]["by_center_cny"],
    "gate_answer_by_center": gate["attempts"]["answer_by_center_cny"],
    "receipts_reserve_sum_cny": round(sum(float(r.get("bound_cny") or 0) for r in rec_res), 7),
    "receipts_charged_sum_cny": round(sum(float(r.get("charged_cny") or 0) for r in rec_set), 7),
    "receipt_reservation_ids_match_ledger": {r["reservation_id"] for r in rec_res} == rids,
    "ledger_nonanswer_charge_cny": round(center_charge.get("ocr", 0.0) + (center_charge.get("answer_retrieval", 0.0) - gate["attempts"]["answer_by_center_cny"]["answer_retrieval"]), 7),
    "run_result_reserved_cny": run_result["reserved_cny"],
    "run_result_settled_cny": run_result["settled_cny"],
    "run_result_requests_reserved": run_result["requests_reserved"],
    "run_result_requests_sent": run_result["requests_sent"],
    "summary_requests": summary["requests"],
    "summary_network_outbound": summary["network"]["outbound_attempts"],
    "summary_transport_outbound": summary["network"]["detail"]["transport_outbound"],
    "ledger_outbound_recomputed": op_count,
    "record_totals": record["totals"],
    "record_centers": record["centers"],
    "record_ledger_before": record["ledger_before"],
    "record_ledger_after": record["ledger_after"],
    "record_go_sha256_matches_file": record["authorization"]["go_sha256"] == fsha(GO),
    "record_budget_sha256_matches_file": record["authorization"]["budget_sha256"] == fsha(BUDGET),
    "record_ledger_before_sha_matches": record["ledger_before"]["sha256"] == bsha(pre_txt.encode("utf-8")),
    "record_ledger_after_sha_matches": record["ledger_after"]["sha256"] == bsha(raw_ledger),
    "gate_go_canonical_sha256": gate["authorization"]["go_sha256"] == payload_sha(go),
    "gate_budget_canonical_sha256": gate["authorization"]["budget_sha256"] == payload_sha(budget),
    "gate_ledger_binding_is_prefix": gate["authorization"]["ledger_sha256"] == bsha(prefix),
    "gate_plan_sha256_matches": gate["authorization"]["plan_sha256"] == plan_sha,
    "gate_max_requests": gate["authorization"]["max_requests"],
    "gate_requests_used_pre_run": gate["authorization"]["requests_used"],
    "gate_requests_remaining_pre_run": gate["authorization"]["requests_remaining"],
    "pilot_record_requests": record["totals"]["requests_reserved"],
    "pilot_record_planned": record["totals"]["planned_requests"],
}

# ---------- 7. dataset / binding
ds_lines = P(PILOT + "dataset.jsonl").read_text(encoding="utf-8").splitlines()
ds_lf = "\n".join(l.rstrip("\r") for l in ds_lines if l.strip()) + "\n"
b0 = [l.rstrip("\r") for l in P("fixtures/evaluation/b0.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
rg = [l.rstrip("\r") for l in P("fixtures/evaluation/regression.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
fixtures = {json.loads(l)["case_id"]: l for l in b0 + rg}
line_check = {json.loads(l)["case_id"]: (l.rstrip("\r") == fixtures[json.loads(l)["case_id"]])
              for l in ds_lines if l.strip()}
out["binding"] = {
    "dataset_lf_bytes": len(ds_lf.encode("utf-8")),
    "dataset_lf_sha256": bsha(ds_lf.encode("utf-8")),
    "binding_complete": gate["binding"]["complete"],
    "binding_missing": gate["binding"]["missing"],
    "binding_dataset_sha256_is_lf_digest": gate["binding"]["dataset_sha256"] == bsha(ds_lf.encode("utf-8")),
    "dataset_lines_match_frozen_fixtures": line_check,
    "index_revision": gate["binding"]["index_revision"],
    "trace_identity_bound": gate["binding"]["trace_identity_bound"],
    "manifest_ingest_documents": len(manifest["ingest"]),
    "manifest_index": manifest["pipeline"]["index"],
    "manifest_ingest_separate_document_ids": len({d["document_id"] for d in manifest["ingest"]}),
}

# ---------- 8. citation evidence vs cases
ev = [(c["case_id"], t["turn"], (t.get("product") or {}).get("evidence") or []) for c in cases for t in c["turns"]]
out["citations"] = {
    "answered_turns": sum(1 for _, _, e in ev if e),
    "turns_total": len(ev),
    "citations": sum(len(e) for _, _, e in ev),
    "verified": sum(1 for _, _, e in ev for x in e if x.get("verified")),
    "active": sum(1 for _, _, e in ev for x in e if x.get("active")),
    "in_run": sum(1 for _, _, e in ev for x in e if x.get("in_run")),
    "gate_citation_evidence": gate["citation_evidence"],
    "citation_complete": gate["citation_evidence"]["complete"],
}
out["quality_signals"] = {
    "gate_status": gate["status"], "quality_gate": gate["quality_gate"],
    "failure": gate["failure"], "stop_code": gate["stop_code"],
    "cases": {c["case_id"]: {"status": c["status"], "stratum": c["stratum"],
              "outcomes": [(t["turn"], (t.get("product") or {}).get("kind"), bool(t.get("paid_attempt", None)),
                            len((t.get("product") or {}).get("evidence") or [])) for t in c["turns"]]}
              for c in cases},
    "expected_kind_per_case": {},
}
for c in cases:
    expected = json.loads([l for l in ds_lines if l.strip() and json.loads(l)["case_id"] == c["case_id"]][0]).get("expected_kind")
    out["quality_signals"]["expected_kind_per_case"][c["case_id"]] = expected


# ---------- 8b. per-event charge recompute (usage x plan rates)
pol_by_rid = {e["reservation_id"]: e.get("settlement_policy") for e in reserved}
recomp, recomp_bad = 0, []
chat_ok, chat_bad = 0, []
tot_ok, tot_bad = 0, []
for e in results:
    st = e.get("settlement") or {}
    rc = st.get("recomputed_conservative_charge_cny")
    if rc is not None:
        if abs(float(rc) - float(e["conservative_charge_cny"])) <= 1e-9: recomp += 1
        else: recomp_bad.append(e["reservation_id"])
    pol, u = pol_by_rid.get(e["reservation_id"]), e.get("usage")
    if not pol or not u: continue
    rates = pol.get("rates") or {}
    if e["kind"] == "chat":
        calc = (int(u.get("prompt_tokens") or 0) * float(rates["input_per_million_cny"])
                + int(u.get("completion_tokens") or 0) * float(rates["output_per_million_cny"])) / 1e6
        okc = abs(calc - float(e["conservative_charge_cny"])) <= 1e-9
        chat_ok += 1 if okc else 0
        if not okc: chat_bad.append(e["reservation_id"])
    elif e["kind"] in ("embedding", "rerank"):
        calc = int(u.get("total_tokens") or 0) * float(rates["unit_per_million_cny"]) / 1e6
        okt = abs(calc - float(e["conservative_charge_cny"])) <= 1e-9
        tot_ok += 1 if okt else 0
        if not okt: tot_bad.append(e["reservation_id"])
out["charge_recompute"] = {
    "results_with_recomputed_field": recomp, "results_recomputed_mismatch": recomp_bad,
    "chat_reproduced_from_usage": chat_ok, "chat_mismatch": chat_bad,
    "embedding_rerank_reproduced_from_usage": tot_ok, "embedding_rerank_mismatch": tot_bad,
    "ocr_charges": [{"charge": e["conservative_charge_cny"], "usage": e.get("usage")} for e in results if e["kind"] == "ocr"],
    "failed_results_charged_full_bound": [
        {"item_id": next(x for x in reserved if x["reservation_id"] == e["reservation_id"])["metadata"]["item_id"],
         "charge": e["conservative_charge_cny"],
         "reserve": next(x for x in reserved if x["reservation_id"] == e["reservation_id"])["reserve_cny"]}
        for e in results if e["status"] == "failed"],
}

# ---------- 9. schema / reporting nits (facts, no verdict)
reqs = [json.loads(l) for l in P(PILOT + "requests.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
out["reconciliation"]["receipts_subset_of_ledger_ids"] = {r["reservation_id"] for r in rec_res}.issubset(rids)
out["reconciliation"]["answer_reservations_absent_from_receipts"] = len(rids - {r["reservation_id"] for r in rec_res})
out["evidence_nits"] = {
    "paid_attempt_key_only_on_refusals": {
        c["case_id"] + f"-t{t['turn']}": ("paid_attempt" in t, t.get("paid_attempt"))
        for c in cases for t in c["turns"]},
    "requests_billed_true_with_zero_chat": [
        {"item_id": r["item_id"], "billed": r["billed"], "charged_cny": r["charged_cny"],
         "provider_calls": r["provider_calls"]}
        for r in reqs if r["provider_calls"]["chat"] == 0],
    "summary_settled_failure": summary["requests"]["settled_failure"],
    "ledger_failed_result_events": sum(1 for e in results if e["status"] == "failed"),
    "summary_billed_cny": summary["requests"]["billed_cny"],
    "summary_billed_recomputed": round(sum(r["charged_cny"] for r in reqs if r["provider_calls"]["outbound"] > 0), 7),
    "run_result_scope": "answer-only (6 chat reservations)",
    "ledger_scope": "all P2-LIVE operations (42 reservations)",
    "settlement_output_valid_false_on_chat": sum(1 for e in results if e["kind"] == "chat" and (e.get("settlement") or {}).get("output_valid") is False),
    "note_output_valid": "build_chat_evidence() never sets output_valid -> dataclass default False (not a quality signal)",
}
# quality: frozen-label mechanical check
import re
for c in cases:
    d = next(json.loads(l.rstrip("\r")) for l in ds_lines if l.strip() and json.loads(l.rstrip("\r"))["case_id"] == c["case_id"])
    rec = {"expected_kind": d.get("expected_kind"), "expected_values": d.get("expected_values") or [],
           "forbidden_values": d.get("forbidden_values") or [], "turns": []}
    for t2 in c["turns"]:
        txt = (t2.get("product") or {}).get("text") or ""
        rec["turns"].append({
            "turn": t2["turn"], "outcome": (t2.get("product") or {}).get("kind"),
            "expected_value_hits": [v for v in rec["expected_values"] if v in txt],
            "forbidden_hits": [v for v in rec["forbidden_values"] if v in txt],
            "evidence": len((t2.get("product") or {}).get("evidence") or []),
        })
    out.setdefault("quality_label_check", {})[c["case_id"]] = rec

outpath = Path(__file__).with_name("verify-pilot-out.json")
outpath.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8", newline="\n")

def flag(x): return "OK" if x is True else ("n/a" if x is None else "CHECK")
lines = []
def emit(k, v): lines.append(f"{k:<58} {v}")
emit("ledger pre-pilot sha256 (1011 lines)", out["identity"]["ledger_pre_pilot_sha256"][:16] + "… " + str(out["identity"]["ledger_pre_pilot_bytes"]) + "B")
emit("ledger now sha256 (1095 lines)", out["identity"]["ledger_now_sha256"][:16] + "…");
emit("pilot delta 42 reserved + 42 result, all P2-LIVE", flag(out["ledger_delta"]["contiguous_block"] and out["ledger_delta"]["stages"] == ["P2-LIVE"]))
emit("reserve sum / charge sum", f"{out['ledger_delta']['reserve_cny_sum']} / {out['ledger_delta']['charge_cny_sum']}")
emit("centers ocr / answer_retrieval (charged)", f"{out['ledger_delta']['center_charge']['ocr']} / {out['ledger_delta']['center_charge']['answer_retrieval']}")
emit("global reservations (pre 505 + 42)", str(out["ledger_delta"]["global_reservations"]))
emit("plan_sha256 recomputed == GO scope", flag(out["plan"]["matches_go_sha256"] if "matches_go_sha256" in out["plan"] else out["plan"]["matches_go_scope"]))
emit("plan worst case / reserve peak", f"{out['plan']['worst_case_cny_recomputed']} / {out['plan']['reserve_peak_cny_recomputed']}")
emit("GO required fields missing", str(out["go"]["missing_fields"]))
emit("GO validity days / max_requests / centers sum", f"{out['go']['validity_days']} / {out['go']['max_requests']} / {out['go']['cost_centers_sum']}")
emit("GO ledger binding == historical prefix", flag(out["go"]["ledger_binding_matches_prefix"]))
emit("budget limit / P2-LIVE / arithmetic closes", f"{out['budget']['limit_cny']} / {out['budget']['p2_live_allocation_cny']} / {flag(out['budget']['arithmetic_closes'])}")
emit("budget remaining_conservative_cny_at_start (stale?)", str(out["budget"]["remaining_conservative_cny_at_start"]))
emit("gate receipts subset of ledger / answers outside", f"{flag(out['reconciliation']['receipts_subset_of_ledger_ids'])} / {out['reconciliation']['answer_reservations_absent_from_receipts']}")
emit("dataset LF digest == binding", flag(out["binding"]["binding_dataset_sha256_is_lf_digest"]))
emit("dataset lines == frozen fixtures", flag(all(out["binding"]["dataset_lines_match_frozen_fixtures"].values())))
emit("citations verified / turns with evidence", f"{out['citations']['verified']} / {out['citations']['answered_turns']}")
emit("unpaid-refusal conservative charge", str(out["ledger_delta"]["unpaid_refusal_charge_cny"]))
emit("charge recompute: recomputed-field / chat / embedding+rerank", f'{out["charge_recompute"]["results_with_recomputed_field"]} ok, {len(out["charge_recompute"]["results_recomputed_mismatch"])} bad / {out["charge_recompute"]["chat_reproduced_from_usage"]} ok, {len(out["charge_recompute"]["chat_mismatch"])} bad / {out["charge_recompute"]["embedding_rerank_reproduced_from_usage"]} ok, {len(out["charge_recompute"]["embedding_rerank_mismatch"])} bad')
emit("ledger failed results vs summary.settled_failure", f"{out['ledger_delta']['statuses'].get('failed')} vs {out['evidence_nits']['summary_settled_failure']}")
txtpath = Path(__file__).with_name("verify-pilot-out.txt")
txtpath.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print("\n".join(lines))
print("\nwrote", outpath)

