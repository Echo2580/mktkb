"""生成并校验负例（含复核窗口 B1/B2/B5 内容级篡改）；每个负例必须 exit 1。"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = Path(__import__("os").environ.get("NCU_REPO_ROOT", str(HERE.parents[6])))
MAN = ROOT / "docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/manifest.json"
VER = ROOT / "docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE/scripts/verify_manifest.py"
NEG = ROOT / ".tmp-ncu-isolated" / "negatives"
NEG.mkdir(parents=True, exist_ok=True)
base = json.loads(MAN.read_text(encoding="utf-8"))


def find(m, cid):
    return next(c for c in m["cases"] if c["case_id"] == cid)


def mutate(fn):
    m = copy.deepcopy(base)
    fn(m)
    return m


def swap_trace(m):
    a, b = find(m, "N02"), find(m, "N03")
    a["trace_id"], b["trace_id"] = b["trace_id"], a["trace_id"]


NEGATIVES = {
    # 原有 6 类（A1–A6）
    "A1-wrong-binding": lambda m: find(m, "N02").__setitem__("plan_sha256", "0" * 64),
    "A2-duplicate-case": lambda m: m["cases"].append(copy.deepcopy(find(m, "N02"))),
    "A3-u-type-mixed": lambda m: (find(m, "U05").__setitem__("basis", "R"), find(m, "U05").__setitem__("run_id", "p2-t207-r2-20261111-01")),
    "A4-sample-insufficient": lambda m: m["cases"].remove(find(m, "C06")),
    "A5-missing-trace": lambda m: find(m, "N03").__setitem__("trace_id", None),
    "A6-missing-citation": lambda m: (find(m, "U01")["check_evidence"].pop("source_hit", None), find(m, "U01")["gates"].pop("citation_required", None)),
    # 复核窗口 B1/B2/B5（内容级篡改）
    "B1-question-hash": lambda m: find(m, "N05").__setitem__("question_sha256", "0123456789abcdef" * 4),
    "B2-evidence-path": lambda m: find(m, "N02")["evidence_paths"].__setitem__("run_cases", "docs/reports/OBS-EVAL/P2/T207/does-not-exist-R1.jsonl"),
    "B5-trace-swap": swap_trace,
    # 返工 R2：四档状态篡改
    "B7-binding-proof-no-mech": lambda m: find(m, "N01").__setitem__("mechanical_gate_failures", []),
    "B8-binding-proof-missing": lambda m: find(m, "N01").pop("binding_proof", None),
    "B9-binding-proof-gate-pass": lambda m: find(m, "N01")["gates"]["trace_integrity"].__setitem__("status", "pass"),
}
EXPECT = {
    "A1": "WRONG_BINDING", "A2": "DUPLICATE_CASE", "A3": "U_TYPE_MIXED", "A4": "SAMPLE_INSUFFICIENT",
    "A5": "MISSING_TRACE", "A6": "MISSING_CITATION_EVIDENCE",
    "B1": "QUESTION_HASH_MISMATCH", "B2": "EVIDENCE_PATH_MISSING", "B5": "TRACE_CASE_MISMATCH",
    "B7": "BINDING_PROOF_WITHOUT_MECHANICAL_FAIL", "B8": "BINDING_PROOF_MISSING",
    "B9": "BINDING_PROOF_WITHOUT_MECHANICAL_FAIL",
}
results = {}
for name, fn in NEGATIVES.items():
    p = NEG / f"{name}.json"
    p.write_text(json.dumps(mutate(fn), ensure_ascii=False, indent=2), encoding="utf-8")
    proc = subprocess.run([sys.executable, "-X", "utf8", str(VER), str(p)], capture_output=True, text=True, encoding="utf-8")
    out = (proc.stdout or "").strip()
    tag = name.split("-")[0]
    ok = proc.returncode == 1 and EXPECT[tag] in out
    print(f"== {name}: exit={proc.returncode} expect={EXPECT[tag]} {'OK' if ok else 'FAIL'}")
    print("   ", out[:700])
    results[name] = {"exit_code": proc.returncode, "expected_code": EXPECT[tag], "ok": ok, "output": out}
(NEG / "negative-tests.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", NEG / "negative-tests.json")
