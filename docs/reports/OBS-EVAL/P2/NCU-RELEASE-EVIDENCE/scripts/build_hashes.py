"""生成 evidence/artifact-hashes.json 与 SHA256SUMS（可复现，返工 R1-2/3）。

- artifact-hashes：原始 run 工件、冻结题集与评分 bundle、门槛文件、测试文件、evidence/*.json
  （均从仓库或 `D:\\mktkb-p2-run\\t207` 原始位置只读计算）；
- SHA256SUMS：交付目录内除自身外全部文件的 SHA-256（最后一步执行）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[6]
BASE = ROOT / "docs/reports/OBS-EVAL/P2/T207"
OUT = HERE.parents[1]
EVIDENCE = OUT / "evidence"
ORIGIN = Path(r"D:\mktkb-p2-run\t207")
SCORES = {"R1": "R1-fixed", "R2": "R2-fixed", "R4": "R4"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


hashes: dict[str, str] = {}
for run, label in [("R1", "R1-fixed"), ("R2", "R2-fixed"), ("R4", "R4")]:
    tag = run.lower()
    rd = BASE / f"p2-t207-{tag}-20261111-01"
    hashes[f"{run}.run_manifest.json"] = sha(rd / "run_manifest.json")
    hashes[f"{run}.run_result.json"] = sha(rd / "run_result.json")
    hashes[f"{run}.cases.jsonl"] = sha(rd / "cases.jsonl")
    hashes[f"{run}.gate.json"] = sha(rd / "gate.json")
    hashes[f"{run}.summary.json"] = sha(rd / "summary.json")
    hashes[f"{run}.frozen_cases.jsonl"] = sha(BASE / "cases" / f"{run}.jsonl")
    hashes[f"{run}.case_scores.json"] = sha(BASE / "scoring" / label / "case_scores.json")
    hashes[f"{run}.scorecard.json"] = sha(BASE / "scoring" / label / "scorecard.json")
    hashes[f"{run}.trace_db"] = sha(ORIGIN / run / "data" / "observability" / "qa-traces.sqlite3")
    hashes[f"{run}.rag_index"] = sha(ORIGIN / run / "data" / "rag-index.sqlite3")
    hashes[f"{run}.run_dataset.jsonl"] = sha(ORIGIN / run / "p2-run" / "dataset.jsonl")
hashes["R2.product_db"] = sha(ORIGIN / "R2" / "data" / "mktkb.sqlite3")
hashes["u-controls.json"] = sha(BASE / "scoring" / "u-controls.json")
hashes["matrix_observation.json"] = sha(BASE / "scoring" / "closeout" / "matrix_observation.json")
hashes["verification.json"] = sha(BASE / "scoring" / "closeout" / "verification.json")
hashes["h2-artifact-audit.json"] = sha(BASE / "scoring" / "closeout" / "h2-artifact-audit.json")
hashes["gate_v0_3.json"] = sha(ROOT / "docs" / "evaluation" / "gate_v0_3.json")
hashes["gate_v0_3_approved.json"] = sha(ROOT / "docs" / "evaluation" / "gate_v0_3_approved.json")
hashes["test_t09_mutation.py"] = sha(ROOT / "backend" / "tests" / "acceptance" / "test_t09_mutation.py")
hashes["netguard.py"] = sha(ROOT / "backend" / "tests" / "acceptance" / "support" / "netguard.py")
for name in ("gate_recompute.json", "gate_recompute_r2.json", "negative-tests.json", "trace-adjudication.json", "u01-citation-reconstruction.json"):
    hashes[name] = sha(EVIDENCE / name)

(EVIDENCE / "artifact-hashes.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

sums = []
for path in sorted(p for p in OUT.rglob("*") if p.is_file() and p.name not in {"SHA256SUMS", "review.md"}):
    sums.append(f"{sha(path)}  {path.relative_to(OUT).as_posix()}")
(OUT / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
print(json.dumps({"artifact_hashes": len(hashes), "sums_entries": len(sums), "artifact_hashes_sha256": sha(EVIDENCE / "artifact-hashes.json")}, ensure_ascii=False))
