"""P2-T207-FIX-A 独立验收探针合集（零真实调用；按节顺序执行）。

本文件由各独立探针串联而成，便于在 evidence/verify/ 下保留“脚本 + 输出”两份证据。
所有网络/产品路径均为离线 mock；不读 .env/H1/H2 密文/key；不写账本/预算/GO。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(r"D:/GPT项目/市场部AI知识库")


# ==============================================================================
# SECTION: PLAN/GO 重建、预检、授权、负例、只读证明
# (source: 01-plan-go-probe.py)
# ==============================================================================
"""独立验收探针 1：计划/GO 重建 + 预检/授权/负例（只读；零发送）。
只读 PM 计划/候选 GO/固定路径 GO/真实账本快照；不写账本/预算/GO。
"""
# (future import removed: combined file already has it)

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(r"D:/GPT项目/市场部AI知识库")
PM = REPO / "docs/reports/OBS-EVAL/P2/T207/PM"
sys.path.insert(0, str(REPO / "backend/src"))

from mktkb.evaluation import p2_authorization as pa
from mktkb.evaluation.p2_contracts import HARD_MAX_REQUESTS, P2LedgerSnapshot, P2RunPlan


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def real() -> P2LedgerSnapshot:
    return pa.read_ledger_snapshot()


def mem(real_snapshot: P2LedgerSnapshot, **overrides):
    data = dict(
        schema_version=real_snapshot.schema_version,
        ledger_path=real_snapshot.ledger_path,
        ledger_sha256=real_snapshot.ledger_sha256,
        historical_prefix_sha256=real_snapshot.historical_prefix_sha256,
        budget_sha256=real_snapshot.budget_sha256,
        total_limit_cny=real_snapshot.total_limit_cny,
        historical_accounted_cny=real_snapshot.historical_accounted_cny,
        accounted_cny=real_snapshot.accounted_cny,
        reservation_count=real_snapshot.reservation_count,
        result_count=real_snapshot.result_count,
        stage_allocations_cny=dict(real_snapshot.stage_allocations_cny),
        p2_stage_accounted_cny=real_snapshot.p2_stage_accounted_cny,
        p2_center_accounted_cny=dict(real_snapshot.p2_center_accounted_cny),
        source="in-memory",
    )
    data.update(overrides)
    return P2LedgerSnapshot(**data)


plan_doc = json.loads((PM / "T207-plan-v0_1.json").read_text(encoding="utf-8"))
plan_file_sha = sha(PM / "T207-plan-v0_1.json")
plan = P2RunPlan.from_dict(plan_doc)

spec = importlib.util.spec_from_file_location(
    "build_plan", REPO / "docs/reports/OBS-EVAL/P2/T207/evidence/build-plan.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)  # 只 import，不执行 main()
rebuilt_doc = builder.build_public_plan()
rebuilt = P2RunPlan.from_dict(rebuilt_doc)

out = {
    "step": "plan_rebuild",
    "plan_file_sha256": plan_file_sha,
    "plan_file_sha16": plan_file_sha[:16],
    "plan_sha256_from_file": plan.plan_sha256,
    "plan_sha256_rebuilt": rebuilt.plan_sha256,
    "file_equals_rebuilt": plan.as_dict() == rebuilt.as_dict(),
    "items": len(plan.items),
    "cases": plan.case_count,
    "turns": plan.turn_count,
    "ocr_pages": plan.page_count,
    "total_requests": plan.total_requests,
    "max_requests": plan.max_requests,
    "worst_case_cny": plan.worst_case_cny,
    "reserve_peak_cny": plan.reserve_peak_cny,
    "estimated_success_cny": plan.estimated_success_cny,
    "by_operation": plan.requests_by_operation(),
    "center_needs_cny": dict(plan.center_needs_cny()),
    "center_limits_cny": dict(plan.cost_centers_cny),
    "hard_max_requests": HARD_MAX_REQUESTS,
    "stage_limit_cny": plan.stage_limit_cny,
    "project_total_limit_cny": plan.project_total_limit_cny,
}
print(json.dumps(out, ensure_ascii=False, indent=1))

real_snapshot = real()
pre = pa.preflight_p2(plan, real_snapshot)
print(json.dumps({
    "step": "preflight_real_snapshot",
    "ok": pre.ok,
    "reasons": list(pre.reasons),
    "stage_remaining": pre.stage_remaining_cny,
    "total_remaining": pre.total_remaining_cny,
    "requests_used": pre.requests_used,
    "requests_remaining": pre.requests_remaining,
    "requests_planned": pre.requests_planned,
    "worst_case": pre.worst_case_cny,
    "reserve_peak": pre.reserve_peak_cny,
    "center_remaining": dict(pre.center_remaining_cny),
    "production_ready": pre.production_ready,
    "snapshot_reservation_count": real_snapshot.reservation_count,
    "snapshot_stage_accounted": real_snapshot.p2_stage_accounted_cny,
    "snapshot_centers": dict(real_snapshot.p2_center_accounted_cny),
    "snapshot_total_accounted": real_snapshot.accounted_cny,
}, ensure_ascii=False, indent=1))

go = json.loads((PM / "T207-GO.CANDIDATE-DRAFT.json").read_text(encoding="utf-8"))
print(json.dumps({
    "step": "go_candidate_shape",
    "document": go["document"],
    "plan_id": go["scope"]["plan_id"],
    "plan_sha256": go["scope"]["plan_sha256"],
    "bound_to_plan_sha": go["scope"]["plan_sha256"] == plan.plan_sha256,
    "max_requests": go["scope"]["max_requests"],
    "max_request_cny": go["scope"]["max_request_cny"],
    "cost_centers": go["scope"]["cost_centers_cny"],
    "operations": go["scope"]["operations"],
    "budget_ledger_sha256_matches_prefix": go["budget_ledger_sha256"] == real_snapshot.historical_prefix_sha256,
    "issued_by": go.get("issued_by"),
    "expires_minus_issued_days": (datetime.fromisoformat(go["expires_utc"]) - datetime.fromisoformat(go["issued_utc"])).days,
}, ensure_ascii=False, indent=1))

now = datetime(2026, 11, 11, 9, 0, tzinfo=timezone(timedelta(hours=8)))
auth = pa.authorize_p2(plan, go_payload=go, budget_payload=pa.load_budget_payload(),
                       ledger_snapshot=mem(real_snapshot), now=now)
print(json.dumps({
    "step": "authorize_candidate",
    "production_ready": auth.production_ready,
    "go_sha256": auth.go_sha256,
    "plan_sha256": auth.plan_sha256,
    "max_requests": auth.max_requests,
    "requests_used": auth.requests_used,
    "requests_remaining": auth.requests_remaining,
    "stage_remaining_cny": auth.stage_remaining_cny,
}, ensure_ascii=False, indent=1))

# 固定路径旧 GO：必须按稳定码拒（本包未写该文件）
fixed_go_path = pa.P2_GO_PATH
fixed = None
if fixed_go_path.is_file():
    fixed_payload = json.loads(fixed_go_path.read_text(encoding="utf-8"))
    try:
        pa.authorize_p2(plan, go_payload=fixed_payload, budget_payload=pa.load_budget_payload(),
                        ledger_snapshot=mem(real_snapshot), now=now)
        fixed = {"case": "fixed_path_old_go", "result": "UNEXPECTED-PASS"}
    except Exception as exc:  # noqa: BLE001
        fixed = {"case": "fixed_path_old_go", "reason": getattr(exc, "reason", type(exc).__name__),
                 "fixed_go_plan_id": fixed_payload.get("scope", {}).get("plan_id"),
                 "fixed_go_plan_sha256": fixed_payload.get("scope", {}).get("plan_sha256")}
else:
    fixed = {"case": "fixed_path_old_go", "exists": False}
print(json.dumps({"step": "fixed_path_go", **fixed}, ensure_ascii=False, indent=1))

negatives = []

def record(label, fn, expect):
    try:
        outcome = fn()
        negatives.append({
            "case": label,
            "expected": expect,
            "outcome": "accepted",
            "result_max_requests": getattr(outcome, "max_requests", None),
            "result_ok": getattr(outcome, "ok", None),
        })
    except Exception as exc:  # noqa: BLE001
        negatives.append({
            "case": label,
            "expected": expect,
            "outcome": "rejected",
            "reason": getattr(exc, "reason", None) or getattr(exc, "code", None) or type(exc).__name__,
        })


def mutated(**changes):
    doc = json.loads(json.dumps(plan_doc))
    doc.update(changes)
    return doc


record("plan_1201_vs_go_1200", lambda: pa.authorize_p2(
    P2RunPlan.from_dict(mutated(max_requests=1201)), go_payload=go,
    budget_payload=pa.load_budget_payload(), ledger_snapshot=mem(real_snapshot), now=now),
    "go_max_requests_below_plan")
plan_1201 = P2RunPlan.from_dict(mutated(max_requests=1201))
go_bound_1201 = json.loads(json.dumps(go))
go_bound_1201["scope"]["plan_sha256"] = plan_1201.plan_sha256
go_bound_1201["scope"]["max_requests"] = 1200
record("plan_1201_bound_go_1200", lambda: pa.authorize_p2(
    plan_1201, go_payload=go_bound_1201, budget_payload=pa.load_budget_payload(),
    ledger_snapshot=mem(real_snapshot), now=now), "go_max_requests_below_plan")

record("plan_1601", lambda: P2RunPlan.from_dict(mutated(max_requests=1601)),
       "request_cap_over_hard_limit")
record("plan_1600", lambda: P2RunPlan.from_dict(mutated(max_requests=1600)), "accepted")
record("plan_1200", lambda: P2RunPlan.from_dict(mutated(max_requests=1200)), "accepted")

go_1201 = json.loads(json.dumps(go))
go_1201["scope"]["max_requests"] = 1201
record("go_1201_vs_plan_1200", lambda: pa.authorize_p2(
    plan, go_payload=go_1201, budget_payload=pa.load_budget_payload(),
    ledger_snapshot=mem(real_snapshot), now=now), "（见结论：码不拒，按 min(plan,GO) 生效）")

go_1601 = json.loads(json.dumps(go))
go_1601["scope"]["max_requests"] = 1601
record("go_1601_over_hard_cap", lambda: pa.authorize_p2(
    plan, go_payload=go_1601, budget_payload=pa.load_budget_payload(),
    ledger_snapshot=mem(real_snapshot), now=now), "go_max_requests_over_hard_cap")

old_plan = P2RunPlan.from_dict(mutated(plan_version="v0.1-old-sha"))
record("old_plan_sha_vs_new_go", lambda: pa.authorize_p2(
    old_plan, go_payload=go, budget_payload=pa.load_budget_payload(),
    ledger_snapshot=mem(real_snapshot), now=now), "go_plan_sha256_mismatch")

print(json.dumps({"step": "negatives", "rows": negatives}, ensure_ascii=False, indent=1))

# 真实账本/预算只读证明
print(json.dumps({
    "step": "read_only_proof",
    "ledger_sha": sha(REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"),
    "budget_sha": sha(REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"),
    "go_sha": sha(pa.P2_GO_PATH),
    "go_bytes": pa.P2_GO_PATH.stat().st_size,
}, ensure_ascii=False, indent=1))


# ==============================================================================
# SECTION: 拆 run 题集/转换/灌库源/批量/授权窗口/顺序反证
# (source: 02-cases-ingest-probe.py)
# ==============================================================================
"""独立验收探针 2：拆 run 题集/转换逐字段/灌库源与批量/授权窗口与顺序（只读、零发送）。"""
# (future import removed: combined file already has it)

import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path

REPO = Path(r"D:/GPT项目/市场部AI知识库")
T207 = REPO / "docs/reports/OBS-EVAL/P2/T207"
sys.path.insert(0, str(REPO / "backend/src"))
sys.path.insert(0, str(REPO / "backend/tests"))

from mktkb.evaluation import p2_authorization as pa
from mktkb.evaluation.dataset import CaseSpec, validate_case, write_cases
from mktkb.evaluation.p2_contracts import P2LedgerSnapshot, P2RunPlan
from mktkb.evaluation.p2_public_cases import (
    acceptance_label_version,
    load_acceptance_cases,
    run_case_sets,
    u01_case,
)
from mktkb.evaluation.p2_contracts import OPERATION_COST_CENTER  # noqa: F401


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------- 1. 逐字段来源复核（N/C/U01） ----------
questions = json.loads((REPO / "fixtures/acceptance/questions.json").read_text(encoding="utf-8"))
by_id = {row["id"]: row for row in questions["questions"]}
STRICT = ("kind", "sheet", "row", "page", "paragraph", "table", "column")
label_version = acceptance_label_version()
rows = []
problems = []
for case in load_acceptance_cases():
    src = by_id[case.case_id]
    scenario = src["scenario"]
    expect_values = () if scenario["expected_kind"] in {"not_found", "clarification"} else tuple(
        str(v) for v in src.get("expected_values") or ()
    )
    expect_sources = []
    dropped_heading = False
    for ref in src.get("expected_sources") or ():
        item = {"doc_code": ref["file"]}
        if str(ref.get("record") or "").strip():
            item["record_code"] = ref["record"]
        locator = {k: v for k, v in (ref.get("locator") or {}).items() if k in STRICT}
        if "heading" in (ref.get("locator") or {}):
            dropped_heading = True
        if locator:
            item["locator"] = locator
        expect_sources.append(item)
    expect_forbidden = [{"doc_code": f} for f in (scenario.get("forbidden_sources") or ())]
    checks = {
        "question": case.question == src["question"],
        "suite": case.suite == ("negative" if src["group"] == "negative" else "boundary"),
        "stratum": case.stratum == (src.get("category") or src["group"]),
        "expected_kind": case.expected_kind == scenario["expected_kind"],
        "expected_values": list(case.expected_values) == list(expect_values),
        "expected_sources": [dict(r) for r in case.expected_sources] == expect_sources,
        "forbidden_sources": [dict(r) for r in case.forbidden_sources] == expect_forbidden,
        "should_refuse": case.should_refuse == (scenario["expected_kind"] == "not_found"),
        "requires_ocr_false": case.requires_ocr is False,
        "business_date": case.business_date == "2026-10-28",
        "label_version": case.label_version == label_version,
        "notes_source": f"source=fixtures/acceptance/questions.json id={case.case_id}" in case.notes,
    }
    bad = [name for name, ok in checks.items() if not ok]
    if bad:
        problems.append({"case_id": case.case_id, "failed": bad})
    rows.append({"case_id": case.case_id, "group": src["group"], "kind": scenario["expected_kind"],
                 "values": len(case.expected_values), "sources": len(case.expected_sources),
                 "dropped_heading": dropped_heading, "all_fields_from_source": not bad})

u01 = u01_case()
u01_src = by_id["U01"]
print(json.dumps({
    "step": "nc_field_trace",
    "cases": len(rows),
    "all_pass": not problems,
    "problems": problems,
    "rows": rows,
    "u01": {
        "question_matches": u01.question == u01_src["question"],
        "values_match": list(u01.expected_values) == [str(v) for v in u01_src["expected_values"]],
        "sources_match": [dict(r) for r in u01.expected_sources] == [
            {"doc_code": ref["file"], **({"record_code": ref["record"]} if ref.get("record") else {}),
             **({"locator": {k: v for k, v in (ref.get("locator") or {}).items() if k in STRICT}}
                if any(k in STRICT for k in (ref.get("locator") or {})) else {})}
            for ref in u01_src.get("expected_sources") or ()
        ],
        "suite": u01.suite,
        "kind": u01.expected_kind,
        "notes_has_mirror": "mirror=backend/tests/acceptance/test_t09_mutation.py::test_u01" in u01.notes,
    },
}, ensure_ascii=False, indent=1))

# ---------- 2. R1/R2/R3 文件：行数/sha/逐字节可复现/内容与冻结题集一致 ----------
sets = run_case_sets()
summary = {}
with tempfile.TemporaryDirectory(prefix="p2-cases-verify-") as tmp:
    for name, cases in sets.items():
        target = Path(tmp) / f"{name}.jsonl"
        canonical_sha = write_cases(target, cases)
        actual = (T207 / "cases" / f"{name}.jsonl")
        actual_bytes = actual.read_bytes()
        summary[name] = {
            "cases": len(cases),
            "ids": [case.case_id for case in cases],
            "expected_sha256": canonical_sha,
            "actual_sha256": sha(actual_bytes),
            "bytes_equal_canonical": actual_bytes == target.read_bytes(),
            "lines": len(actual_bytes.decode("utf-8").splitlines()),
            "q01_present": any(case.case_id == "Q01" for case in cases),
            "all_validate": all(validate_case(CaseSpec.from_dict(json.loads(line))) is None
                                for line in actual_bytes.decode("utf-8").splitlines() if line.strip()),
        }
print(json.dumps({"step": "case_files", **summary}, ensure_ascii=False, indent=1))

# ---------- 3. 每 run 的 expected/forbidden 文档是否都在该 run 的灌库源里 ----------
logical = {}
for name in ("R1", "R2", "R3"):
    plan_doc = json.loads((T207 / "PM" / f"T207-ingest-plan-{name}.json").read_text(encoding="utf-8"))
    logical[name] = {}
    for src in plan_doc["sources"]:
        code = src.get("name") or Path(src["path"]).name
        logical[name][code] = src
    needed = set()
    forbidden = set()
    for case in sets[name]:
        for ref in case.expected_sources:
            if ref.get("doc_code"):
                needed.add(ref["doc_code"])
        for ref in case.forbidden_sources:
            if ref.get("doc_code"):
                forbidden.add(ref["doc_code"])
    # 产品侧文档名 -> doc_code（与 cases/document-codes.json 同口径）
    codes = json.loads((T207 / "cases/document-codes.json").read_text(encoding="utf-8"))
    available_codes = {codes.get(name_) for name_ in logical[name] if name_ in codes}
    # 版本槽逻辑：V03 以 D01 名上传 -> D01 可用；V04 同槽；其它按文件名
    missing = sorted(code for code in needed if code not in available_codes)
    print(json.dumps({
        "step": "ingest_coverage",
        "run": name,
        "sources": len(plan_doc["sources"]),
        "source_names": list(logical[name]),
        "publishes": {k: bool(v.get("publish", True)) for k, v in logical[name].items()},
        "document_refs": {k: v.get("document_ref") for k, v in logical[name].items() if v.get("document_ref")},
        "cases": [case.case_id for case in sets[name]],
        "needed_doc_codes": sorted(needed),
        "forbidden_doc_codes": sorted(forbidden),
        "available_doc_codes": sorted(code for code in available_codes if code),
        "missing_doc_codes": sorted(code for code in needed if code not in available_codes),
        "forbidden_not_ingested": sorted(code for code in forbidden if code not in available_codes),
    }, ensure_ascii=False, indent=1))

# ---------- 4. 灌库批量与请求/金额算式 ----------
from mktkb.ingestion.parsers import ParseServices, parse_document
from mktkb.rag.chunking import adapt_parsed_unit, build_chunks
from mktkb.rag.config import RagConfig
from mktkb.rag.types import DocumentSpec

CONFIG = RagConfig(provider_mode="offline")
BATCH = 5


def batches_for(rel_path: str) -> int:
    path = REPO / rel_path
    parsed = list(parse_document(path, path.suffix.lower().lstrip("."), ParseServices()))
    spec = DocumentSpec(doc_id=rel_path, logical_id=rel_path, source_path=rel_path,
                        title=path.stem, file_kind=path.suffix.lower().lstrip("."),
                        version_id="v1", version_label="当前",
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    units = [adapt_parsed_unit(u, doc=spec, unit_id=f"u{i}", ordinal=i) for i, u in enumerate(parsed)]
    chunks = build_chunks(spec, units, CONFIG)
    unique = {c.content_sha256 for c in chunks}
    return math.ceil(len(unique) / BATCH)


batch_rows = {}
for name in ("R1", "R2", "R3"):
    plan_doc = json.loads((T207 / "PM" / f"T207-ingest-plan-{name}.json").read_text(encoding="utf-8"))
    rows_ = []
    for src in plan_doc["sources"]:
        if any(token in src["path"] for token in ("D07", "D08", "D09", "D10")):
            rows_.append({"path": src["path"], "batches": "ocr:upper-bound-not-measured"})
            continue
        rows_.append({"path": src["path"], "batches": batches_for(src["path"])})
    measured = sum(r["batches"] for r in rows_ if isinstance(r["batches"], int))
    batch_rows[name] = {"rows": rows_, "measured_non_ocr_batches": measured}

turns = {name: len(cases) for name, cases in sets.items()}
ARITH = {
    "R1": {"turns": turns["R1"], "turn_requests": turns["R1"] * 4, "ingest_non_ocr": batch_rows["R1"]["measured_non_ocr_batches"],
           "ocr_upper_bound": 11, "ocr_pages": 12},
    "R2": {"turns": turns["R2"], "turn_requests": turns["R2"] * 4, "ingest": batch_rows["R2"]["measured_non_ocr_batches"]},
    "R3": {"turns": turns["R3"], "turn_requests": turns["R3"] * 4, "ingest": batch_rows["R3"]["measured_non_ocr_batches"]},
}
ARITH["R1"]["ingest_index_batches"] = ARITH["R1"]["ingest_non_ocr"] + ARITH["R1"]["ocr_upper_bound"]
ARITH["R1"]["ocr_page_requests"] = 12
ARITH["R1"]["requests"] = (ARITH["R1"]["turn_requests"] + ARITH["R1"]["ingest_index_batches"]
                           + ARITH["R1"]["ocr_page_requests"])
ARITH["R1"]["worst_cny"] = round(turns["R1"] * 0.044224 + ARITH["R1"]["ingest_index_batches"] * 0.002048 + 5.65, 6)
ARITH["R2"]["requests"] = ARITH["R2"]["turn_requests"] + ARITH["R2"]["ingest"]
ARITH["R2"]["worst_cny"] = round(turns["R2"] * 0.044224 + ARITH["R2"]["ingest"] * 0.002048, 6)
ARITH["R3"]["requests"] = ARITH["R3"]["turn_requests"] + ARITH["R3"]["ingest"]
ARITH["R3"]["worst_cny"] = round(turns["R3"] * 0.044224 + ARITH["R3"]["ingest"] * 0.002048, 6)
ARITH["cumulative"] = {
    "requests": sum(ARITH[r]["requests"] for r in ("R1", "R2", "R3")),
    "worst_cny": round(sum(ARITH[r]["worst_cny"] for r in ("R1", "R2", "R3")), 6),
}
print(json.dumps({"step": "batch_arith", "batch_size": BATCH, "runs": ARITH,
                  "batch_detail": batch_rows}, ensure_ascii=False, indent=1))

# ---------- 5. 授权窗口 + 顺序反证（真实快照只读） ----------
real = pa.read_ledger_snapshot()
plan = P2RunPlan.from_dict(json.loads((T207 / "PM" / "T207-plan-v0_1.json").read_text(encoding="utf-8")))


def snapshot(**overrides):
    data = dict(
        schema_version=real.schema_version, ledger_path=real.ledger_path,
        ledger_sha256=real.ledger_sha256, historical_prefix_sha256=real.historical_prefix_sha256,
        budget_sha256=real.budget_sha256, total_limit_cny=real.total_limit_cny,
        historical_accounted_cny=real.historical_accounted_cny, accounted_cny=real.accounted_cny,
        reservation_count=real.reservation_count, result_count=real.result_count,
        stage_allocations_cny=dict(real.stage_allocations_cny),
        p2_stage_accounted_cny=real.p2_stage_accounted_cny,
        p2_center_accounted_cny=dict(real.p2_center_accounted_cny), source="in-memory",
    )
    data.update(overrides)
    return P2LedgerSnapshot(**data)


windows = []
used = int(real.reservation_count)
stage = float(real.p2_stage_accounted_cny)
centers = {k: float(v) for k, v in real.p2_center_accounted_cny.items()}
for name in ("R3", "R2", "R1"):
    pre = pa.preflight_p2(plan, snapshot(reservation_count=used, p2_stage_accounted_cny=stage,
                                        p2_center_accounted_cny=dict(centers)))
    windows.append({"run": name, "used_before": used, "plan_requests": pre.requests_planned,
                    "ceiling_used_plus_plan": used + pre.requests_planned,
                    "per_run_requests": ARITH[name]["requests"],
                    "per_run_ceiling": used + ARITH[name]["requests"],
                    "preflight_ok": pre.ok, "reasons": list(pre.reasons),
                    "stage_remaining": pre.stage_remaining_cny,
                    "ocr_remaining": pre.center_remaining_cny["ocr"]})
    used += ARITH[name]["requests"]
    stage = round(stage + ARITH[name]["worst_cny"], 10)
    centers["answer_retrieval"] = round(centers.get("answer_retrieval", 0.0)
                                        + (ARITH[name]["worst_cny"] - (5.65 if name == "R1" else 0.0)), 10)
    if name == "R1":
        centers["ocr"] = round(centers.get("ocr", 0.0) + 5.65, 10)

# 反证：先跑 R1
stage_r1 = round(float(real.p2_stage_accounted_cny) + ARITH["R1"]["worst_cny"], 10)
c_r1 = {k: float(v) for k, v in real.p2_center_accounted_cny.items()}
c_r1["answer_retrieval"] = round(c_r1.get("answer_retrieval", 0.0) + ARITH["R1"]["worst_cny"] - 5.65, 10)
c_r1["ocr"] = round(c_r1.get("ocr", 0.0) + 5.65, 10)
after_r1 = pa.preflight_p2(plan, snapshot(reservation_count=int(real.reservation_count) + ARITH["R1"]["requests"],
                                          p2_stage_accounted_cny=stage_r1, p2_center_accounted_cny=c_r1))
print(json.dumps({
    "step": "authorization_windows",
    "order": ["R3", "R2", "R1"],
    "windows": windows,
    "cumulative_requests": ARITH["cumulative"]["requests"],
    "cumulative_cny": ARITH["cumulative"]["worst_cny"],
    "reorder_if_r1_first": {"ok": after_r1.ok, "reasons": list(after_r1.reasons),
                            "requests_remaining": after_r1.requests_remaining,
                            "ocr_remaining": after_r1.center_remaining_cny["ocr"]},
}, ensure_ascii=False, indent=1))


# ==============================================================================
# SECTION: p2-h2-plan 生成与拒绝（合成元数据，不读 H2）
# (source: 03-h2-score-probe.py)
# ==============================================================================
"""独立验收探针 3：p2-h2-plan 离线生成/拒绝（零真实调用、零 H2 读取）。"""
# (future import removed: combined file already has it)

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(r"D:/GPT项目/市场部AI知识库")
PY = str(REPO / ".venv/Scripts/python.exe")
MANIFEST = REPO / "docs/evaluation/p2-holdout-v2.manifest.json"
sys.path.insert(0, str(REPO / "backend/src"))

from mktkb.evaluation.p2_contracts import P2RunPlan

TMPBASE = Path(tempfile.mkdtemp(prefix="t207fixa-verify-", dir=str(Path(tempfile.gettempdir()))))
ENV = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}


def run_cli(args):
    completed = subprocess.run([PY, "-B", "-X", "utf8", "-m", "mktkb.evaluation.cli", *args],
                               cwd=str(REPO), capture_output=True, text=True, env=ENV, timeout=300)
    return completed.returncode, completed.stdout, completed.stderr


def metadata(histogram, version="P2-HOLDOUT-v2", extra_case_field=None):
    cases = []
    index = 0
    for turns, count in histogram.items():
        for _ in range(count):
            index += 1
            item = {"case_id": f"SYN-{index:02d}", "turns": int(turns)}
            if extra_case_field:
                item.update(extra_case_field)
            cases.append(item)
    return {"schema_version": "p2-h2-cases-metadata/v0.1", "dataset_version": version, "cases": cases}


print(json.dumps({"step": "tmp", "tmp": str(TMPBASE)}, ensure_ascii=False))

tmp = TMPBASE
meta_ok = tmp / "h2-cases-metadata.json"
meta_ok.write_text(json.dumps(metadata({"1": 25, "2": 4, "3": 1})), encoding="utf-8")
plan_out = tmp / "h2-plan.json"
code, out, err = run_cli([
    "p2-h2-plan", "--cases-metadata", str(meta_ok), "--holdout-manifest", str(MANIFEST),
    "--ingest-batches", "68", "--plan-out", str(plan_out), "--plan-id", "P2-H2-VERIFY",
    "--created-utc", "2026-11-11T08:30:00+08:00",
])
payload = json.loads(out) if out.strip().startswith("{") else {}
plan = P2RunPlan.from_dict(json.loads(plan_out.read_text(encoding="utf-8"))) if plan_out.is_file() else None
print(json.dumps({
    "step": "h2_plan_ok",
    "exit": code,
    "stdout_has_case_id": "case_id" in out or "SYN-" in out,
    "stdout": out.strip()[:900],
    "stderr": err.strip()[:300],
    "payload_cases_turns_items_requests": [payload.get("cases"), payload.get("turns"),
                                           payload.get("items"), payload.get("total_requests")],
    "plan_summary": None if plan is None else {
        "items": len(plan.items), "total_requests": plan.total_requests,
        "cases": plan.case_count - 1, "turns": plan.turn_count - 1,
        "page_count": plan.page_count, "max_requests": plan.max_requests,
        "worst_case_cny": plan.worst_case_cny, "reserve_peak_cny": plan.reserve_peak_cny,
        "center_needs": dict(plan.center_needs_cny()), "by_operation": plan.requests_by_operation(),
        "plan_sha256": plan.plan_sha256,
    },
    "plan_file_has_case_ids": plan_out.is_file() and "SYN-01" in plan_out.read_text(encoding="utf-8"),
}, ensure_ascii=False, indent=1))

negatives = []
code, out, err = run_cli([
    "p2-h2-plan", "--cases-metadata", str(meta_ok), "--holdout-manifest", str(MANIFEST),
    "--ingest-batches", "68",
    "--plan-out", str(REPO / "docs/reports/OBS-EVAL/P2/T207-FIX-A/evidence/verify/should-not-exist.json"),
    "--plan-id", "P2-H2-VERIFY",
])
negatives.append({"case": "plan_out_inside_workspace", "exit": code, "stdout": out.strip()[:300],
                  "wrote_file": (REPO / "docs/reports/OBS-EVAL/P2/T207-FIX-A/evidence/verify/should-not-exist.json").exists()})

meta_inside = REPO / "docs/reports/OBS-EVAL/P2/T207-FIX-A/evidence/verify/metadata-inside.json"
meta_inside.write_text(json.dumps(metadata({"1": 25, "2": 4, "3": 1})), encoding="utf-8")
code, out, err = run_cli([
    "p2-h2-plan", "--cases-metadata", str(meta_inside), "--holdout-manifest", str(MANIFEST),
    "--ingest-batches", "68", "--plan-out", str(tmp / "h2-plan-2.json"), "--plan-id", "P2-H2-VERIFY",
])
negatives.append({"case": "metadata_inside_workspace", "exit": code, "stdout": out.strip()[:300]})
meta_inside.unlink()

for label, hist, kwargs in (
    ("histogram_mismatch", {"1": 26, "2": 3, "3": 1}, {}),
    ("dataset_version_mismatch", {"1": 25, "2": 4, "3": 1}, {"version": "P2-HOLDOUT-v9"}),
    ("case_extra_field", {"1": 25, "2": 4, "3": 1}, {"extra_case_field": {"question": "leak"}}),
):
    meta = tmp / f"meta-{label}.json"
    meta.write_text(json.dumps(metadata(hist, **kwargs)), encoding="utf-8")
    code, out, err = run_cli([
        "p2-h2-plan", "--cases-metadata", str(meta), "--holdout-manifest", str(MANIFEST),
        "--ingest-batches", "68", "--plan-out", str(tmp / f"plan-{label}.json"), "--plan-id", "P2-H2-VERIFY",
    ])
    negatives.append({"case": label, "exit": code, "stdout": out.strip()[:250]})

code, out, err = run_cli([
    "p2-h2-plan", "--cases-metadata", str(meta_ok), "--holdout-manifest", str(MANIFEST),
    "--ingest-batches", "69", "--plan-out", str(tmp / "plan-b69.json"), "--plan-id", "P2-H2-VERIFY",
])
negatives.append({"case": "ingest_batches_69", "exit": code, "stdout": out.strip()[:250]})
print(json.dumps({"step": "h2_negatives", "rows": negatives}, ensure_ascii=False, indent=1))


# ==============================================================================
# SECTION: p2-score 公开/缺题/error、p2-matrix、holdout 聚合（假数据集）、p2-u-controls
# (source: 04-score-matrix-holdout-probe.py)
# ==============================================================================
"""独立验收探针 4：p2-score 公开/缺题/error + p2-matrix + holdout 聚合 + u-controls（离线）。"""
# (future import removed: combined file already has it)

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(r"D:/GPT项目/市场部AI知识库")
PY = str(REPO / ".venv/Scripts/python.exe")
T207 = REPO / "docs/reports/OBS-EVAL/P2/T207"
sys.path.insert(0, str(REPO / "backend/src"))

from mktkb.evaluation import cli as cli_module
from mktkb.evaluation import p2_score_run as score_mod
from mktkb.evaluation.dataset import CaseSpec, write_cases
from mktkb.evaluation.p2_scoring import P2_HOLDOUT_STRATA, load_p2_gate_config

TMP = Path(tempfile.mkdtemp(prefix="t207fixa-score-", dir=str(Path(tempfile.gettempdir()))))
ENV = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
GATE_HASH = load_p2_gate_config().config_hash


def run_cli(args):
    completed = subprocess.run([PY, "-B", "-X", "utf8", "-m", "mktkb.evaluation.cli", *args],
                               cwd=str(REPO), capture_output=True, text=True, env=ENV, timeout=600)
    return completed.returncode, completed.stdout, completed.stderr


def load_cases(path):
    return tuple(CaseSpec.from_dict(json.loads(line))
                 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())


def make_run(root, *, cases, rows, execution="live", outbound=3, run_id="verify-r2"):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    dataset_path = root / "dataset.jsonl"
    write_cases(dataset_path, cases)
    (root / "cases.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                                      encoding="utf-8")
    manifest = {
        "run_id": run_id, "mode": "end_to_end", "scope": "end_to_end", "suite": "p2-cli",
        "dataset_version": "verify-v1", "dataset_sha256": "a" * 64,
        "corpus_manifest_sha256": "b" * 64, "business_date": "2026-10-28",
        "index_revision": 5, "pipeline_version": "pipeline-verify", "gate_version": "mktkb.gate.v0.3",
        "label_version": "verify-labels", "created_at": "2026-11-11T00:00:00.000+00:00",
        "case_count": len(cases), "config_hash": "c" * 64, "gate_config_hash": GATE_HASH,
        "execution": execution, "dataset_path": str(dataset_path),
        "trace_store": str(root / "traces.sqlite3"),
    }
    (root / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (root / "summary.json").write_text(json.dumps({
        "status": "succeeded", "stop_code": None,
        "cases": {"planned": len(cases), "executed": len(rows), "with_error": 1, "not_executed": 1},
        "attempts": {"available": True, "reserved": outbound, "expected_reservations": outbound},
        "network": {"available": True, "outbound_attempts": outbound}, "execution": execution,
    }, ensure_ascii=False), encoding="utf-8")
    (root / "gate.json").write_text(json.dumps({"citation_evidence": {"complete": False, "issues": []}}),
                                    encoding="utf-8")
    return root


# ---- 1) 公开评分：R2 计划 2 题，只给 U01（status=error），C05 缺失 ----
cases_r2 = load_cases(T207 / "cases/R2.jsonl")
row_u01 = {"case_id": "U01", "suite": "update_delete", "stratum": "mutation", "status": "error",
           "error_code": "turn_timeout", "planned_turns": 1, "turns_executed": 0, "turns": []}
run_dir = make_run(TMP / "run-r2", cases=cases_r2, rows=[row_u01], execution="live", outbound=4)
code, out, err = run_cli(["p2-score", "--run-dir", str(run_dir), "--cases", str(T207 / "cases/R2.jsonl"),
                          "--document-codes", str(T207 / "cases/document-codes.json")])
score_out = run_dir / "score"
scorecard = json.loads((score_out / "scorecard.json").read_text(encoding="utf-8")) if (score_out / "scorecard.json").is_file() else {}
case_scores = json.loads((score_out / "case_scores.json").read_text(encoding="utf-8")) if (score_out / "case_scores.json").is_file() else {}
decision = json.loads((score_out / "p2_decision.json").read_text(encoding="utf-8")) if (score_out / "p2_decision.json").is_file() else {}
print(json.dumps({
    "step": "p2_score_public_missing_error",
    "exit": code, "stdout": out.strip()[:900], "stderr": err.strip()[:300],
    "files": sorted(p.name for p in score_out.glob("*")) if score_out.is_dir() else [],
    "case_statuses": {row["case_id"]: row["status"] for row in case_scores.get("case_scores", [])},
    "suites": {name: {"planned": data.get("planned"), "passed": data.get("passed"),
                      "failed": data.get("failed"), "errors": data.get("errors"),
                      "not_executed": data.get("not_executed")}
               for name, data in (scorecard.get("suites") or {}).items()},
    "scorecard_blocks": [block.get("code") for block in scorecard.get("blocks") or []],
    "release_ready": scorecard.get("release_ready"),
    "decision": decision.get("decision"), "release_allowed": decision.get("release_allowed"),
    "decision_blocks": [block.get("code") for block in decision.get("blocks") or []],
    "real_calls_run_level": case_scores.get("real_calls"),
    "real_calls_per_case": {row["case_id"]: row.get("real_calls") for row in case_scores.get("case_scores", [])},
}, ensure_ascii=False, indent=1))

# ---- 2) 观测矩阵：只有 R2 的 case_scores，无 u-controls ----
matrix_path = TMP / "matrix.json"
code, out, err = run_cli(["p2-matrix", "--case-scores", str(score_out / "case_scores.json"),
                          "--out", str(matrix_path)])
matrix = json.loads(matrix_path.read_text(encoding="utf-8")) if matrix_path.is_file() else {}
print(json.dumps({
    "step": "p2_matrix",
    "exit": code, "stdout": out.strip()[:600], "stderr": err.strip()[:300],
    "composition": matrix.get("composition"), "release_decision": matrix.get("release_decision"),
    "gate": matrix.get("gate"), "tallies": matrix.get("tallies"),
    "u_table": matrix.get("u_table"),
    "provenance_keys": sorted((matrix.get("cases") or [{}])[0]) if matrix.get("cases") else [],
}, ensure_ascii=False, indent=1))

# ---- 3) holdout：假数据集（不读 H2） + 判定表；只写聚合 ----
def synthetic_holdout_cases():
    cases = []
    for stratum, count in P2_HOLDOUT_STRATA.items():
        for index in range(count):
            cases.append(CaseSpec(
                case_id=f"SYNTH-{stratum}-{index:02d}", suite="p2-holdout", split="holdout",
                stratum=stratum, business_date="2026-10-28",
                question=f"synthetic {stratum} {index}", turns=(),
                expected_kind="answer", expected_values=(), labeler="verify", label_version="verify-h2",
            ))
    return tuple(cases)


HOLDOUT_CASES = synthetic_holdout_cases()
manifest = json.loads((REPO / "docs/evaluation/p2-holdout-v2.manifest.json").read_text(encoding="utf-8"))


class FakeDataset:
    class _Manifest:
        pass

    def __init__(self):
        self.cases = HOLDOUT_CASES
        self.manifest = self._Manifest()
        self.manifest.strata = dict(manifest["strata"])


original_loader = score_mod.load_holdout_dataset
score_mod.load_holdout_dataset = lambda path=None: FakeDataset()

verdicts_path = TMP / "h2-verdicts.jsonl"
verdicts_path.write_text("".join(json.dumps({
    "case_id": case.case_id, "status": "pass" if index < 24 else "fail"}) + "\n"
    for index, case in enumerate(HOLDOUT_CASES)), encoding="utf-8")

h2_run = TMP / "h2-run"
h2_run.mkdir(parents=True, exist_ok=True)
(h2_run / "run_manifest.json").write_text(json.dumps({"run_id": "verify-h2", "config_hash": "h2-config", "execution": "local_mock"}), encoding="utf-8")
(h2_run / "summary.json").write_text(json.dumps({}), encoding="utf-8")
holdout_out = TMP / "h2-out"
buffer = io.StringIO()
with contextlib.redirect_stdout(buffer):
    holdout_exit = cli_module.main([
        "p2-score", "--visibility", "holdout", "--run-dir", str(h2_run),
        "--holdout-manifest", str(REPO / "docs/evaluation/p2-holdout-v2.manifest.json"),
        "--verdicts", str(verdicts_path), "--out", str(holdout_out),
    ])
holdout_stdout = buffer.getvalue().strip()
holdout_json = json.loads(holdout_stdout)
card_text = (holdout_out / "holdout_scorecard.json").read_text(encoding="utf-8")
print(json.dumps({
    "step": "p2_score_holdout_verdicts",
    "exit": holdout_exit,
    "stdout": holdout_stdout[:700],
    "total_passed_failed": [holdout_json.get("total"), holdout_json.get("passed"), holdout_json.get("failed")],
    "blocks": holdout_json.get("blocks"),
    "release_ready": holdout_json.get("release_ready"),
    "output_has_case_id_key": "case_id" in card_text,
    "output_has_synthetic_ids": any(case.case_id in card_text for case in HOLDOUT_CASES),
    "output_keys": sorted(json.loads(card_text).keys()),
}, ensure_ascii=False, indent=1))

# 3b) 缺输入（既无 --holdout-cases 也无 --verdicts）
buffer = io.StringIO()
missing_exit = None
missing_error = None
try:
    with contextlib.redirect_stdout(buffer):
        missing_exit = cli_module.main([
            "p2-score", "--visibility", "holdout", "--run-dir", str(h2_run),
            "--holdout-manifest", str(REPO / "docs/evaluation/p2-holdout-v2.manifest.json"),
            "--out", str(TMP / "h2-missing-out"),
        ])
except Exception as exc:  # noqa: BLE001
    missing_error = f"{type(exc).__name__}: {exc}"
print(json.dumps({"step": "p2_score_holdout_missing_inputs", "cli_exit": missing_exit,
                  "raised": missing_error, "stdout": buffer.getvalue().strip()[:300],
                  "documented_code_present_in_repo": False}, ensure_ascii=False, indent=1))

# 3c) --holdout-cases 缺 --document-codes
rows_path = TMP / "h2-cases.jsonl"
rows_path.write_text(json.dumps({"case_id": HOLDOUT_CASES[0].case_id, "turns": []}) + "\n", encoding="utf-8")
buffer = io.StringIO()
with contextlib.redirect_stdout(buffer):
    bad_exit = cli_module.main([
        "p2-score", "--visibility", "holdout", "--run-dir", str(h2_run),
        "--holdout-manifest", str(REPO / "docs/evaluation/p2-holdout-v2.manifest.json"),
        "--holdout-cases", str(rows_path), "--out", str(TMP / "h2-bad-out"),
    ])
print(json.dumps({"step": "p2_score_holdout_rows_no_codes", "exit": bad_exit,
                  "stdout": buffer.getvalue().strip()[:400]}, ensure_ascii=False, indent=1))

score_mod.load_holdout_dataset = original_loader

# ---- 4) p2-u-controls：跑既有 test_t09_mutation.py，导出逐 U 判定；不改测试 ----
test_path = REPO / "backend/tests/acceptance/test_t09_mutation.py"
before_sha = hashlib.sha256(test_path.read_bytes()).hexdigest()
code, out, err = run_cli(["p2-u-controls", "--out", str(TMP / "u-controls.json")])
after_sha = hashlib.sha256(test_path.read_bytes()).hexdigest()
controls = json.loads((TMP / "u-controls.json").read_text(encoding="utf-8")) if (TMP / "u-controls.json").is_file() else {}
print(json.dumps({
    "step": "p2_u_controls",
    "exit": code, "stdout": out.strip()[:500], "stderr": err.strip()[:500],
    "test_file_sha_unchanged": before_sha == after_sha,
    "cases": {name: item["status"] for name, item in (controls.get("cases") or {}).items()},
    "basis": controls.get("basis"),
}, ensure_ascii=False, indent=1))
print(json.dumps({"step": "tmp", "tmp": str(TMP)}, ensure_ascii=False))


# ==============================================================================
# SECTION: tools/p2_live_execute.py 白名单/零回显/拒绝 .env
# (source: 05-wrapper-probe.py)
# ==============================================================================
"""独立验收探针 5：tools/p2_live_execute.py（显式 env-file、白名单、零回显、默认不读 .env）。"""
# (future import removed: combined file already has it)

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(r"D:/GPT项目/市场部AI知识库")
PY = str(REPO / ".venv/Scripts/python.exe")
TMP = Path(tempfile.mkdtemp(prefix="t207fixa-wrapper-", dir=str(Path(tempfile.gettempdir()))))
SENTINEL = "S3CRET-VALUE-never-printed-9f1c"

spec = importlib.util.spec_from_file_location("p2_live_execute", REPO / "tools/p2_live_execute.py")
sys.path.insert(0, str(REPO / "tools"))
import p2_live_execute as module  # noqa: E402

BASE_ENV = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}


def run(args, env=None):
    completed = subprocess.run([PY, "-B", "-X", "utf8", str(REPO / "tools/p2_live_execute.py"), *args],
                               cwd=str(REPO), capture_output=True, text=True,
                               env={**BASE_ENV, **(env or {})}, timeout=300)
    return completed.returncode, completed.stdout, completed.stderr


full = {
    "MKTKB_MODEL_API_KEY": SENTINEL,
    "MKTKB_MODEL_BASE_URL": "https://model.invalid/" + SENTINEL,
    "MKTKB_MODEL_NAME": "model-" + SENTINEL,
    "DASHSCOPE_API_KEY": SENTINEL,
    "DASHSCOPE_BASE_URL": "https://dashscope.invalid/" + SENTINEL,
    "MKTKB_OCR_SECRET_ID": SENTINEL,
    "MKTKB_OCR_SECRET_KEY": SENTINEL,
    "MKTKB_OCR_REGION": "cn-" + SENTINEL,
    "MKTKB_OCR_DISABLED": "0",
    "MKTKB_PROJECT_TOTAL_LIMIT_CNY": "40.0",
}
env_file = TMP / "p2-live.env"
env_file.write_text("\n".join(f"{k}={v}" for k, v in full.items()) + "\n", encoding="utf-8")

rows = []
code, out, err = run(["--env-file", str(env_file), "--check-only"])
rows.append({"case": "check_only_ok", "exit": code,
             "stdout": out.strip(), "stderr_has_sentinel": SENTINEL in err,
             "sentinel_occurrences": (out + err).count(SENTINEL)})

# 父进程里有同名旧值也不得泄漏/混入（build_child_env 先剔除白名单同名项）
parent_sentinel = "PARENT-OLD-VALUE-should-not-survive"
child = module.build_child_env(str(env_file), base_env={**BASE_ENV, "MKTKB_MODEL_API_KEY": parent_sentinel})
rows.append({"case": "parent_value_overridden", "model_key_is_file_value": child["MKTKB_MODEL_API_KEY"] == SENTINEL,
             "parent_value_gone": parent_sentinel not in child.values(),
             "no_dotenv_flag": child.get("MKTKB_NO_DOTENV") == "1",
             "pythonpath_has_backend_src": str(REPO / "backend/src") in child.get("PYTHONPATH", "")})

missing = dict(full)
for name in ("MKTKB_MODEL_NAME", "DASHSCOPE_API_KEY", "MKTKB_OCR_SECRET_ID", "MKTKB_OCR_SECRET_KEY"):
    missing.pop(name)
missing_file = TMP / "missing.env"
missing_file.write_text("\n".join(f"{k}={v}" for k, v in missing.items()) + "\n", encoding="utf-8")
code, out, err = run(["--env-file", str(missing_file), "--check-only"])
rows.append({"case": "missing_required_names_only", "exit": code, "stdout": out.strip(),
             "sentinel_occurrences": (out + err).count(SENTINEL)})

foreign_file = TMP / "foreign.env"
foreign_file.write_text("\n".join(f"{k}={v}" for k, v in full.items()) + "\nAWS_SECRET_ACCESS_KEY=AKIA-SENTINEL\n",
                        encoding="utf-8")
code, out, err = run(["--env-file", str(foreign_file), "--check-only"])
rows.append({"case": "foreign_name_rejected", "exit": code, "stdout": out.strip(),
             "sentinel_occurrences": (out + err).count(SENTINEL)})

dotenv = TMP / ".env"
dotenv.write_text("\n".join(f"{k}={v}" for k, v in full.items()) + "\n", encoding="utf-8")
code, out, err = run(["--env-file", str(dotenv), "--check-only"])
rows.append({"case": "dotenv_name_rejected", "exit": code, "stdout": out.strip(),
             "sentinel_occurrences": (out + err).count(SENTINEL)})

# 子进程路径：bogus plan（真实 CLI，零网络）；哨兵不得出现在任何输出
code, out, err = run(["--env-file", str(env_file), "--", "p2-run", "--plan", str(TMP / "no-such-plan.json"),
                      "--out", str(TMP / "out")])
rows.append({"case": "child_bogus_plan", "exit": code, "stdout": out.strip()[:500], "stderr": err.strip()[:300],
             "sentinel_occurrences": (out + err).count(SENTINEL)})

# 不读 .env：仓库里存在 .env，但默认路径（不给 --env-file）必须只是参数错误，不加载任何文件
code, out, err = run(["--check-only"])
rows.append({"case": "no_env_file_arg", "exit": code, "stdout": out.strip()[:200],
             "stderr": err.strip()[:200], "sentinel_occurrences": (out + err).count(SENTINEL)})

# 被禁止的名字/值不得进入 EnvLoading 的 repr
print(json.dumps({"step": "wrapper", "rows": rows,
                  "envloading_repr_redacted": "redacted" in repr(module.load_env_file(env_file)),
                  "file_values_in_repr": SENTINEL in repr(module.load_env_file(env_file))},
                 ensure_ascii=False, indent=1))


# ==============================================================================
# SECTION: Q39 值匹配：scorers 默认口径 vs p2_scoring 当前口径
# (source: 07-q39-probe.py)
# ==============================================================================
"""独立探针 7：Q39「日期 + 时间」值匹配（scorers 默认口径 vs p2_scoring 的显式空格口径）。"""
# (future import removed: combined file already has it)

import json
import sys
from pathlib import Path

REPO = Path(r"D:/GPT项目/市场部AI知识库")
sys.path.insert(0, str(REPO / "backend/src"))

from mktkb.evaluation.dataset import CaseSpec
from mktkb.evaluation.scorers import score_case
from mktkb.evaluation.scorers import check_value
from mktkb.evaluation.p2_scoring import normalize_product_outcome, score_public_case, _resolved_without_index

b0 = [json.loads(line) for line in (REPO / "fixtures/evaluation/b0.jsonl").read_text(encoding="utf-8").splitlines() if line]
q39 = CaseSpec.from_dict(next(row for row in b0 if row["case_id"] == "Q39"))
row = {
    "case_id": "Q39", "status": "ok", "planned_turns": 1, "turns_executed": 1,
    "turns": [{"turn": 1, "status": "ok", "error_code": None, "product": {
        "kind": "answer", "text": "盘点时间为 2026-10-30 16:00。", "trace_id": "trace-q39",
        "sources": [{"source_id": "s1", "document_name": "D10_盘点通知.jpg", "version_number": 1,
                     "status": "active", "locator": {"page": 1}}],
        "evidence": [{"unit_id": "s1", "unit_key": "page:1", "locator": {"page": 1}, "verified": True}],
        "retrieved": [{"unit_ids": ["s1"], "document_name": "D10_盘点通知.jpg", "unit_key": "page:1",
                       "locator": {"page": 1}}],
        "http_status": 200,
    }}],
}


def outcome_of():
    return normalize_product_outcome(row["turns"][-1], document_codes={"D10_盘点通知.jpg": "D10"},
                                     source_index={"s1": {"unit_key": "page:1", "locator": {"page": 1}}})


def resolved():
    return _resolved_without_index(q39)


out = {
    "check_value_space": check_value("2026-10-30 16:00", "2026-10-30 16:00"),
    "check_value_nospace": check_value("2026-10-3016:00", "2026-10-30 16:00"),
}
default_result = score_case(q39, resolved(), outcome_of())
explicit_result = score_case(q39, resolved(), outcome_of(), cross_explicit_space=True)
out["score_case_default"] = {"status": default_result.status,
                             "checks": [c.to_dict() for c in default_result.checks]}
out["score_case_cross_space"] = {"status": explicit_result.status,
                                 "checks": [c.to_dict() for c in explicit_result.checks]}
scored = score_public_case(q39, row, document_codes={"D10_盘点通知.jpg": "D10"},
                           source_index={"s1": {"unit_key": "page:1", "locator": {"page": 1}}},
                           execution_mode="local_mock", real_calls=0)
out["p2_score_public_case"] = {"status": scored.score.status,
                               "issues": [i.to_dict() for i in scored.score.issues]}
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


# ==============================================================================
# SECTION: R2 同一 run 内 U01 与 C05 的场景隔离（离线产品链）
# (source: 08-r2-scenario-probe.py)
# ==============================================================================
"""独立探针 8：R2 把 U01 与 C05 放进同一 run 后，U01 的 KB 是否被 V01 污染（离线产品链）。"""
# (future import removed: combined file already has it)

import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(r"D:/GPT项目/市场部AI知识库")
sys.path.insert(0, str(REPO / "backend/src"))
sys.path.insert(0, str(REPO / "backend/tests"))

from mktkb.evaluation.product_adapter import (
    ChatBehavior,
    MockChatBackend,
    P2RunDataset,
    ProductEvalAdapter,
    ingest_plan_from_document,
)

TMP = Path(tempfile.mkdtemp(prefix="t207fixa-r2-", dir=str(Path(tempfile.gettempdir()))))


def empty_dataset() -> P2RunDataset:
    return P2RunDataset(
        visibility="public", cases=(),
        identity={"dataset_version": "verify", "label_version": "verify", "suite": "verify",
                  "manifest_sha256": "0" * 64, "case_count": 0},
    )


async def ask(plan_path: Path, question: str, answer: str) -> dict:
    plan = ingest_plan_from_document(json.loads(plan_path.read_text(encoding="utf-8")))
    adapter = ProductEvalAdapter(
        TMP / f"run-{uuid.uuid4().hex[:8]}",
        chat=MockChatBackend(behaviors=(ChatBehavior(answer=answer),)),
        dataset=empty_dataset(),
        ingest_plan=plan,
    )
    try:
        await adapter.start()
        receipts = await adapter.ingest()
        conversation = await adapter.open_conversation()
        turn = await adapter.ask_turn(
            question, user_id="employee", conversation_id=conversation,
            client_request_id=str(uuid.uuid4()),
        )
        return {
            "ingest": {
                "documents": adapter.ingest_document_map,
                "receipts": [{"name": None, "published": r.published,
                              "state": r.job_state, "publish_status": r.publish_status} for r in receipts],
            },
            "turn": {"http_status": turn.http_status, "kind": turn.kind,
                     "text": turn.text[:300],
                     "sources": [{k: s.get(k) for k in ("document_name", "version_number", "status")}
                                 for s in (turn.sources or ())]},
        }
    finally:
        await adapter.close()


async def main() -> None:
    r2 = REPO / "docs/reports/OBS-EVAL/P2/T207/cases/R2.jsonl"
    # 仅 V03->D01->V04(未发布) 的版本槽（U01 的最小场景，无 V01）
    u01_plan = TMP / "u01-only.json"
    full = json.loads((REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-R2.json").read_text(encoding="utf-8"))
    u01_plan.write_text(json.dumps({**full, "sources": full["sources"][:3]}, ensure_ascii=False), encoding="utf-8")

    q_u01 = "P01 位置改版未发布时，城东店宣传海报在哪？"
    q_c05 = "城东店的宣传海报现在放在哪里？"
    out = {
        "u01_without_V01": await ask(u01_plan, q_u01, "位置：B区1号货架第二层"),
        "u01_with_R2_full_plan": await ask(REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-R2.json",
                                           q_u01, "位置：B区1号货架第二层"),
        "c05_with_R2_full_plan": await ask(REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-R2.json",
                                           q_c05, "位置：B区1号货架第二层 或 D区暂存柜"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))


asyncio.run(main())


# ==============================================================================
# SECTION: 红测试修正：T201 存档/历史前缀/追加后篡改的可检测性
# (source: 09-red-test-probe.py)
# ==============================================================================
"""独立探针 9：T207-FIX-A §8 红测试修正的可证伪性（历史前缀 vs 整文；不改真实账本）。"""
# (future import removed: combined file already has it)

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(r"D:/GPT项目/市场部AI知识库")
sys.path.insert(0, str(REPO / "backend/src"))

from mktkb import live_authorization

LEDGER = REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
SNAPSHOT = REPO / "docs/reports/OBS-EVAL/P2/T201/candidates/p2-ledger-snapshot.CANDIDATE-DRAFT.json"
T201 = "1f46d1b9e846528d5a1635db5175a997eab9da075d61a90a8cbf803f3fde7390"

snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
raw = LEDGER.read_bytes()
current_prefix = live_authorization.historical_prefix_sha256(LEDGER)
out = {
    "snapshot_sha_matches_T201": snapshot["ledger_sha256"] == T201,
    "snapshot_prefix_matches_current": snapshot["historical_prefix_sha256"] == current_prefix,
    "current_full_sha_equals_snapshot": hashlib.sha256(raw).hexdigest() == snapshot["ledger_sha256"],
    "current_full_sha": hashlib.sha256(raw).hexdigest(),
    "current_prefix": current_prefix,
    "snapshot_reservation_count": snapshot["reservation_count"],
    "current_reservation_count": 547,
    "ledger_bytes": len(raw),
    "ledger_lines": len(raw.decode("utf-8").splitlines()),
}

TMP = Path(tempfile.mkdtemp(prefix="t207fixa-red-", dir=str(Path(tempfile.gettempdir()))))


def prefix_end_offset(data: bytes) -> int:
    offset = 0
    found = False
    for line in data.splitlines(keepends=True):
        text = line.strip()
        if not text:
            continue
        if json.loads(text).get("event") != "historical_import":
            break
        offset += len(line)
        found = True
    if not found:
        raise SystemExit("no historical_import prefix")
    return offset


def flip_digit(data: bytes, start: int, end: int) -> bytes:
    for index in range(start, end):
        if data[index:index + 1] == b"0":
            return data[:index] + b"1" + data[index + 1:]
    raise SystemExit("no digit to flip")


prefix_end = prefix_end_offset(raw)
out["prefix_end_offset"] = prefix_end
post = prefix_end + 10
post_end = min(len(raw), post + 200)
post_variant = flip_digit(raw, post, post_end)
historical_variant = flip_digit(raw, 0, prefix_end)

for name, data in (("post-import", post_variant), ("historical-import", historical_variant)):
    path = TMP / f"{name}.jsonl"
    path.write_bytes(data)
    out[f"tamper_{name.replace('-', '_')}"] = {
        "full_sha": hashlib.sha256(data).hexdigest(),
        "full_changed": hashlib.sha256(data).hexdigest() != out["current_full_sha"],
        "prefix": live_authorization.historical_prefix_sha256(path),
        "prefix_changed": live_authorization.historical_prefix_sha256(path) != out["current_prefix"],
        "bytes_same_length": len(data) == len(raw),
    }

out["new_test_would_pass_after_post_import_tamper"] = (
    snapshot["ledger_sha256"] == T201
    and snapshot["historical_prefix_sha256"] == out["tamper_post_import"]["prefix"]
    and snapshot["reservation_count"] >= 505
)
out["new_test_would_pass_after_historical_tamper"] = (
    snapshot["ledger_sha256"] == T201
    and snapshot["historical_prefix_sha256"] == out["tamper_historical_import"]["prefix"]
    and snapshot["reservation_count"] >= 505
)
print(json.dumps(out, ensure_ascii=False, indent=1))


# ============================================================================
# SECTION: 收口只读事实（H2 GO/runbook 的 plan_id 差、固定路径 SHA、HEAD）
# ============================================================================
import hashlib

PM = REPO / "docs/reports/OBS-EVAL/P2/T207/PM"
h2_go = json.loads((PM / "T207-GO-h2.CANDIDATE-DRAFT.json").read_text(encoding="utf-8"))
runbook = (PM / "T207-runbook.md").read_text(encoding="utf-8")
print(json.dumps({
    "step": "h2_plan_id_vs_runbook",
    "candidate_go_plan_id": h2_go["scope"]["plan_id"],
    "runbook_command_has_plan_id_P2-H2-20261111": "--plan-id P2-H2-20261111" in runbook,
    "ids_equal": h2_go["scope"]["plan_id"] == "P2-H2-20261111",
    "consequence": "authorize_p2 会以 go_plan_id_mismatch 拒绝（fail-closed，但按文档跑不通）",
    "holdout_input_missing_in_backend": subprocess.run(
        ["git", "grep", "-rn", "holdout_input_missing", "--", "backend"],
        cwd=str(REPO), capture_output=True, text=True).stdout.strip() or "(no occurrence)",
}, ensure_ascii=False, indent=1))

fixed = [
    REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl",
    REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json",
    REPO / "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json",
]
print(json.dumps({
    "step": "final_hashes",
    "head": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO),
                           capture_output=True, text=True).stdout.strip(),
    "fixed": [{"path": str(p.relative_to(REPO)), "bytes": p.stat().st_size,
               "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in fixed],
}, ensure_ascii=False, indent=1))
print("=== DONE ===")
