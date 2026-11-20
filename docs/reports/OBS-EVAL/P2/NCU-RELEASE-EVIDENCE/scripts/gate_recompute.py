"""隔离副本上只读复算 8 项硬门禁；只改诊断副本里的 trace_store/dataset_path 路径。"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(ROOT / "backend/src"))
os.environ["MKTKB_NO_DOTENV"] = "1"


def deny_network(*a, **k):
    raise AssertionError("network_forbidden_in_recompute")


socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network

from mktkb.evaluation.p2_score_run import (  # noqa: E402
    load_cases_file, read_cases_jsonl, score_run,
)
from mktkb.evaluation.p2_scoring import (  # noqa: E402
    build_gate_rows, build_gate_run, evaluate_p2_hard_gates, load_p2_gate_config,
)

BASE = ROOT / "docs/reports/OBS-EVAL/P2/T207"
ISO = ROOT / ".tmp-ncu-isolated" / "runs"
ISO.mkdir(parents=True, exist_ok=True)
EVIDENCE = ROOT / "docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE" / "evidence"
EVIDENCE.mkdir(parents=True, exist_ok=True)
GATE_PATH = ROOT / "backend/src/mktkb/evaluation/gate.py"
GATE_SHA = hashlib.sha256(GATE_PATH.read_bytes()).hexdigest()
codes = json.loads((BASE / "cases/document-codes.json").read_text(encoding="utf-8"))
config = load_p2_gate_config(ROOT / "docs/evaluation/gate_v0_3_approved.json")
print("gate config:", config.config.gate_version, "status:", config.config.status, "hash:", config.config_hash)
print("gate.py sha256:", GATE_SHA)

out = {}
for run in ["R1", "R2", "R4"]:
    tag = run.lower()
    src = BASE / f"p2-t207-{tag}-20261111-01"
    ext = Path(rf"D:\mktkb-p2-run\t207\{run}")
    iso = ISO / run
    if iso.exists():
        shutil.rmtree(iso)
    iso.mkdir(parents=True)
    shutil.copy2(src / "cases.jsonl", iso / "cases.jsonl")
    shutil.copy2(src / "summary.json", iso / "summary.json")
    shutil.copy2(ext / "p2-run" / "dataset.jsonl", iso / "dataset.jsonl")
    shutil.copy2(ROOT / ".tmp-ncu-isolated" / "traces" / f"{run}.sqlite3", iso / "traces.sqlite3")
    manifest = json.loads((src / "run_manifest.json").read_text(encoding="utf-8"))
    original = {
        "cases": hashlib.sha256((src / "cases.jsonl").read_bytes()).hexdigest(),
        "summary": hashlib.sha256((src / "summary.json").read_bytes()).hexdigest(),
        "manifest": hashlib.sha256((src / "run_manifest.json").read_bytes()).hexdigest(),
        "dataset": hashlib.sha256((ext / "p2-run" / "dataset.jsonl").read_bytes()).hexdigest(),
        "trace_db": hashlib.sha256((ROOT / ".tmp-ncu-isolated/traces" / f"{run}.sqlite3").read_bytes()).hexdigest(),
    }
    manifest["trace_store"] = str(iso / "traces.sqlite3")
    manifest["dataset_path"] = str(iso / "dataset.jsonl")
    (iso / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    cases = load_cases_file(BASE / "cases" / f"{run}.jsonl")
    bundle = score_run(iso, cases=cases, document_codes=codes)
    rows = read_cases_jsonl(iso / "cases.jsonl")
    # 主人 D-004 的接线：build_gate_rows 需显式接收原始 run 行，才能把同轮
    # product.evidence 的 unit 投影进 outcome.evidence（否则 gate 侧看不到 evidence）。
    gate_rows = build_gate_rows(cases, bundle.scored, document_codes=None, case_rows=rows)
    run_result = build_gate_run(run_dir=iso, manifest=manifest, cases=cases, rows=gate_rows, summary=json.loads((iso / "summary.json").read_text(encoding="utf-8")))
    hard = evaluate_p2_hard_gates(run_result, config=config, dataset_path=str(iso / "dataset.jsonl"), require_trace=True)

    per_gate = {}
    for gate_id, status in hard.gate_status.items():
        fails = [f for f in hard.failures if f.gate_id == gate_id]
        unks = [u for u in hard.unknowns if u.gate_id == gate_id]
        per_gate[gate_id] = {
            "status": status,
            "failures": [
                {"case_id": f.case_id, "check_id": f.check_id, "evidence": f.evidence}
                for f in fails
            ],
            "unknowns": [
                {"case_id": u.case_id, "check_id": u.check_id, "reason": u.reason}
                for u in unks
            ],
        }
    out[run] = {
        "run_id": bundle.run_id,
        "original_sha256": original,
        "diagnostic_copy_changes": ["trace_store/dataset_path repointed to isolated copies"],
        "gate_status": dict(hard.gate_status),
        "exit_code": hard.exit_code,
        "evaluated_by_suite": {
            suite: sum(1 for s in bundle.scores if s.suite == suite and s.status in {"pass", "fail"} and not s.requires_ocr)
            for suite in sorted({s.suite for s in bundle.scores})
        },
        "gates": per_gate,
        "case_status": {s.case_id: s.status for s in bundle.scores},
    }
    print("=" * 30, run, "exit", hard.exit_code)
    for gate_id, item in per_gate.items():
        print(f"  {gate_id:24s} {item['status']:14s} fails={len(item['failures'])} unknowns={len(item['unknowns'])}")
        for f in item["failures"][:8]:
            print("      FAIL", f["case_id"], f["check_id"], json.dumps(f["evidence"], ensure_ascii=False)[:260])
        for u in item["unknowns"][:5]:
            print("      UNK ", u["case_id"], u["check_id"], str(u["reason"])[:160])

payload = {
    "_meta": {
        "schema_version": "p2-ncu-gate-recompute-r2/v0.1",
        "decision": "D-004（citation_required 候选接地集合 = outcome.evidence ∪ outcome.retrieved；判据不变）",
        "gate_py": str(GATE_PATH),
        "gate_py_sha256": GATE_SHA,
        "gate_config": "docs/evaluation/gate_v0_3_approved.json",
        "gate_config_loader_hash": config.config_hash,
        "trace_integrity_semantics": "逐值相等，未改动",
        "generated_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
    },
    **out,
}
(ISO.parent / "gate_recompute_r2.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
(EVIDENCE / "gate_recompute_r2.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print("written", EVIDENCE / "gate_recompute_r2.json")
