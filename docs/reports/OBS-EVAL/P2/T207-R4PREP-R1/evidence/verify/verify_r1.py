
"""P2-T207-R4PREP-R1 独立复验探针（只读、零网络、零真实调用）。

复算：① 15 个 R4 产物/账本/预算/固定 GO 的 sha 与 R4PREP 验收快照逐字节比较；② 计划契约逐值；
③ 账本分 run / 分中心复算；④ cost §8 的算术；⑤ 0.04096 与 fail-closed 边界；⑥ 稳定码与行号漂移；
⑦ 提交面（R2/LIVECAP 未碰计划/case/GO）。输出只到 stdout（调用方落盘）。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[7]
T207 = REPO / "docs/reports/OBS-EVAL/P2/T207"
R4PREP = REPO / "docs/reports/OBS-EVAL/P2/T207-R4PREP"
LEDGER = REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
BUDGET = REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
FIXED_GO = REPO / "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json"
sys.path.insert(0, str(REPO / "backend/src"))

from mktkb.evaluation.p2_contracts import P2RunPlan  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8").stdout


def scope_check() -> dict:
    snap = json.loads((R4PREP / "evidence/verify/package-hashes-after.json").read_text(encoding="utf-8-sig"))
    rows, changed = [], []
    for entry in snap:
        path = REPO / entry["path"]
        row = {"path": entry["path"], "snapshot_sha256": entry["sha256"]}
        if not path.is_file():
            row["now"] = "MISSING"
            changed.append(entry["path"])
        else:
            row["now_sha256"] = sha(path)
            row["now_bytes"] = path.stat().st_size
            row["match"] = row["now_sha256"] == entry["sha256"] and row["now_bytes"] == entry["bytes"]
            if not row["match"]:
                changed.append(entry["path"])
        rows.append(row)
    return {"files": len(snap), "changed": changed, "all_match": not changed, "rows": rows}


def plan_check() -> dict:
    doc = json.loads((T207 / "PM/T207-plan-R4-v0_1.json").read_text(encoding="utf-8"))
    plan = P2RunPlan.from_dict(doc)
    return {
        "file_sha256": sha(T207 / "PM/T207-plan-R4-v0_1.json"),
        "plan_sha256": plan.plan_sha256,
        "items": len(plan.items),
        "total_requests": plan.total_requests,
        "by_operation": plan.requests_by_operation(),
        "max_requests": plan.max_requests,
        "worst_case_cny": plan.worst_case_cny,
        "reserve_peak_cny": plan.reserve_peak_cny,
        "estimated_success_cny": plan.estimated_success_cny,
        "page_count": plan.page_count,
        "operations": sorted(plan.operations),
        "centers": plan.cost_centers_cny,
        "center_needs_cny": {k: str(v) for k, v in plan.center_needs_cny().items()},
    }


def go_check() -> dict:
    go = json.loads((T207 / "PM/T207-GO-R4.CANDIDATE-DRAFT.json").read_text(encoding="utf-8"))
    plan = P2RunPlan.from_dict(json.loads((T207 / "PM/T207-plan-R4-v0_1.json").read_text(encoding="utf-8")))
    return {
        "file_sha256": sha(T207 / "PM/T207-GO-R4.CANDIDATE-DRAFT.json"),
        "plan_sha_bound": go["scope"]["plan_sha256"] == plan.plan_sha256,
        "plan_id_bound": go["scope"]["plan_id"] == plan.plan_id,
        "operations": go["scope"]["operations"],
        "has_ocr": "ocr" in go["scope"]["operations"],
        "max_requests": go["scope"]["max_requests"],
        "max_request_cny": go["scope"]["max_request_cny"],
        "centers": go["scope"]["cost_centers_cny"],
        "ledger_sha": go["budget_ledger_sha256"],
        "issued_utc": go["issued_utc"],
        "expires_utc": go["expires_utc"],
    }


def cases_check() -> dict:
    rows = [json.loads(line) for line in (T207 / "cases/R4.jsonl").read_text(encoding="utf-8").splitlines() if line]
    codes = json.loads((T207 / "cases/document-codes.json").read_text(encoding="utf-8"))
    return {
        "sha256": sha(T207 / "cases/R4.jsonl"),
        "order": [r["case_id"] for r in rows],
        "expected_kinds": [r["expected_kind"] for r in rows],
        "forbidden_doc_codes": [[f["doc_code"] for f in r.get("forbidden_sources") or []] for r in rows],
        "label_version": rows[0]["label_version"],
        "doc_code_keys_have_V03_V06": {"V03": "V03" in codes, "V06": "V06" in codes},
        "document_codes_sha256": sha(T207 / "cases/document-codes.json"),
    }


def ingest_plan_check() -> dict:
    doc = json.loads((T207 / "PM/T207-ingest-plan-R4.json").read_text(encoding="utf-8"))
    return {
        "sha256": sha(T207 / "PM/T207-ingest-plan-R4.json"),
        "schema_version": doc["schema_version"],
        "sources": len(doc["sources"]),
        "order": [{"path": Path(s["path"]).name, "name": s.get("name"),
                   "document_ref": s.get("document_ref"), "publish": bool(s.get("publish", True))}
                  for s in doc["sources"]],
    }


def ledger_check() -> dict:
    lines = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line]
    reserved = [r for r in lines if r["event"] == "reserved"]
    results = [r for r in lines if r["event"] == "result"]
    by_stage, by_run, by_center = {}, {}, {}
    for rec in results:
        by_stage[rec["stage"]] = by_stage.get(rec["stage"], 0.0) + float(rec.get("conservative_charge_cny") or 0)
    for rec in results:
        if rec.get("run_id"):
            by_run[rec["run_id"]] = by_run.get(rec["run_id"], 0.0) + float(rec.get("conservative_charge_cny") or 0)
    for rec in results:
        if rec["stage"] == "P2-LIVE":
            by_center[rec["kind"]] = by_center.get(rec["kind"], 0.0) + float(rec.get("conservative_charge_cny") or 0)
    hist = sum(float(r.get("accounted_cny") or 0) for r in lines if r["event"] == "historical_import")
    run_counts = {}
    for rec in reserved:
        if rec.get("run_id"):
            run_counts[rec["run_id"]] = run_counts.get(rec["run_id"], 0) + 1
    return {
        "ledger_sha256": sha(LEDGER),
        "budget_sha256": sha(BUDGET),
        "fixed_go_sha256": sha(FIXED_GO),
        "bytes": LEDGER.stat().st_size,
        "lines": len(lines),
        "reserved": len(reserved),
        "results": len(results),
        "historical_import_cny": hist,
        "by_stage_cny": {k: round(v, 7) for k, v in by_stage.items()},
        "p2_live_by_center_cny": {k: round(v, 7) for k, v in by_center.items()},
        "p2_live_by_run_cny": {k: round(v, 7) for k, v in by_run.items()},
        "reservations_by_run": run_counts,
    }


def arithmetic_check() -> dict:
    from decimal import Decimal

    plan = P2RunPlan.from_dict(json.loads((T207 / "PM/T207-plan-R4-v0_1.json").read_text(encoding="utf-8")))
    per_op = {
        "index_embedding": (6, "0.002048"),
        "query_embedding": (3, "0.002048"),
        "rerank": (3, "0.004800"),
        "query_expansion": (3, "0.018688"),
        "answer": (3, "0.018688"),
    }
    worst = sum((Decimal(n) * Decimal(unit) for n, unit in per_op.values()), Decimal(0))
    stage_used, project_used, req_used = Decimal("6.5409604"), Decimal("21.6119049"), 691
    q = lambda value: Decimal(value).quantize(Decimal("0.0000001"))
    stage_after = stage_used + worst
    project_after = project_used + worst
    checks = {
        "worst_case_matches_plan": Decimal(str(plan.worst_case_cny)) == worst == Decimal("0.144960"),
        "requests_691_plus_18_eq_709": req_used + plan.total_requests == 709,
        "request_headroom_760_minus_691": 760 - 691 == 69,
        "stage_after_r4": q(stage_after) == Decimal("6.6859204"),
        "project_after_r4": q(project_after) == Decimal("21.7568649"),
        "center_after_r4": q(Decimal("0.3909604") + worst) == Decimal("0.5359204"),
        "stage_remainder_post_r4_is_13_3140796": q(Decimal(20) - stage_after) == Decimal("13.3140796"),
        "project_remainder_post_r4_is_18_2431351": q(Decimal(40) - project_after) == Decimal("18.2431351"),
        "doc_stage_remainder_13_4590_is_pre_r4": q(Decimal(20) - stage_used) == Decimal("13.4590396"),
        "doc_project_remainder_18_3880_is_pre_r4": q(Decimal(40) - project_used) == Decimal("18.3880951"),
    }
    return {"worst_case_recomputed": str(worst), "checks": checks, "all_hold": all(checks.values()),
            "post_r4_remainders": {"stage": str(q(Decimal(20) - stage_after)),
                                   "project": str(q(Decimal(40) - project_after)),
                                   "requests": 1600 - (req_used + plan.total_requests)}}


def ceiling_check() -> dict:
    from mktkb.rag.config import RagConfig
    from mktkb.evaluation.p2_live import P2LiveConfigError, provider_single_request_bounds, resolve_request_ceiling

    cfg = RagConfig()
    bounds = provider_single_request_bounds(cfg)
    ok = resolve_request_ceiling(cfg, plan_peak_cny=0.018688, authorization_cny=0.5)
    boundary = resolve_request_ceiling(cfg, plan_peak_cny=0.018688, authorization_cny=0.04096)
    failure = None
    try:
        resolve_request_ceiling(cfg, plan_peak_cny=0.018688, authorization_cny=0.040959)
    except P2LiveConfigError as exc:
        failure = {"code": getattr(exc, "reason", None) or getattr(exc, "code", None)}
    return {
        "provider_bounds_cny": {k: round(v, 8) for k, v in bounds.items()},
        "effective_with_go_0_5": ok.as_dict(),
        "effective_at_boundary_0_04096": boundary.effective_cny,
        "boundary_passes": boundary.effective_cny == 0.04096,
        "insufficient_below_boundary": failure,
        "embedding_formula": round(81920 * 0.5 / 1_000_000, 8),
        "chat_formula": round(6144 * 2 / 1_000_000 + 800 * 8 / 1_000_000, 8),
        "rerank_formula": round(30000 * 0.8 / 1_000_000, 8),
    }


def citation_check() -> dict:
    source = (REPO / "backend/src/mktkb/evaluation/product_adapter.py").read_text(encoding="utf-8").splitlines()
    needle = 'text=str(payload.get("text")'
    now = next(i + 1 for i, line in enumerate(source) if needle in line)
    at_489 = git("show", "489aadd:backend/src/mktkb/evaluation/product_adapter.py").splitlines()
    old = next(i + 1 for i, line in enumerate(at_489) if needle in line)
    scorers = (REPO / "backend/src/mktkb/evaluation/scorers.py").read_text(encoding="utf-8").splitlines()
    return {
        "product_adapter_payload_text_line_at_489aadd": old,
        "product_adapter_payload_text_line_now": now,
        "drift_lines": now - old,
        "citation_2137_still_valid": old == 2137 and now == 2137,
        "scorers_632_content": scorers[631].strip(),
        "scorers_632_still_valid": scorers[631].strip() == "text = outcome.text",
    }


def run_artifact_surface() -> dict:
    run_dir = T207 / "p2-t207-r1-20261111-01"
    summary = (run_dir / "summary.json").read_text(encoding="utf-8")
    manifest = (run_dir / "run_manifest.json").read_text(encoding="utf-8")
    runner = (REPO / "backend/src/mktkb/evaluation/p2_runner.py").read_text(encoding="utf-8")
    return {
        "r1_summary_has_index_status": "index_status" in summary,
        "r1_summary_has_degraded": "degraded" in summary,
        "r1_manifest_has_degraded": "degraded" in manifest,
        "runner_copies_degraded_into_manifest": '"degraded"' in runner,
        "wiring_as_dict_exposes_request_ceiling": '"request_ceiling"' in (
            REPO / "backend/src/mktkb/evaluation/p2_live.py"
        ).read_text(encoding="utf-8"),
        "note": "R1 产物早于 LIVECAP；request_ceiling 由 wiring.as_dict() 提供，修复后应出现",
    }


def commit_surface() -> dict:
    def files(rev: str) -> list[str]:
        return [line for line in git("show", "--pretty=format:", "--name-only", rev).splitlines() if line]

    r2 = files("24f9cde")
    lc = files("1dca413")
    touches = lambda rows: [p for p in rows if "/PM/" in p or "/cases/" in p or p.endswith("P2-LIVE-GO.json")]
    return {
        "head": git("rev-parse", "--short", "HEAD").strip(),
        "r2_commit": "24f9cde",
        "r2_files": r2,
        "r2_touches_plan_case_go": touches(r2),
        "livecap_commit": "1dca413",
        "livecap_files": lc,
        "livecap_touches_plan_case_go": touches(lc),
    }


def code_strings() -> dict:
    live = (REPO / "backend/src/mktkb/evaluation/p2_live.py").read_text(encoding="utf-8")
    runbook = (T207 / "PM/T207-runbook.md").read_text(encoding="utf-8")
    return {
        "code_has_live_request_ceiling_insufficient": "live_request_ceiling_insufficient" in live,
        "runbook_mentions_code": "live_request_ceiling_insufficient" in runbook,
        "runbook_expected_ledger_sha_6b053520": "6b053520" in runbook,
        "runbook_expected_ledger_bytes_1050298": "1,050,298" in runbook,
        "current_ledger_sha_prefix": sha(LEDGER)[:8],
        "current_ledger_bytes": LEDGER.stat().st_size,
    }


payload = {
    "scope": scope_check(),
    "plan": plan_check(),
    "go": go_check(),
    "cases": cases_check(),
    "ingest_plan": ingest_plan_check(),
    "ledger": ledger_check(),
    "arithmetic": arithmetic_check(),
    "ceiling": ceiling_check(),
    "citation": citation_check(),
    "run_artifact_surface": run_artifact_surface(),
    "commit_surface": commit_surface(),
    "code_strings": code_strings(),
}
print(json.dumps(payload, ensure_ascii=False, indent=1))
