"""阶段二：把任务 3 交付的真实 N/C/U 证据接进正式门禁入口（H2 仍 PENDING-TASK2）。

只读历史 run 与任务 3 清单；零真实请求。产出脱敏判定 JSON。

用法（仓库根）：

    .\\.venv\\Scripts\\python.exe docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py

前置：本机存在 ``D:\\mktkb-p2-run\\t207\\R{1,2,4}\\data``（历史 rag/trace 库）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

def _project_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "backend" / "src" / "mktkb").is_dir():
            return candidate
    raise SystemExit("找不到仓库根（backend/src/mktkb）")


ROOT = _project_root()
if str(ROOT / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation.p2_b0 import pipeline_source_sha256  # noqa: E402
from mktkb.evaluation.p2_release_gate import (  # noqa: E402
    emit_applicability_proof,
    emit_binding_proof,
    evaluate_release_gate,
)
from mktkb.evaluation.p2_release_model import file_sha256  # noqa: E402

NCU = ROOT / "docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE"
H2 = ROOT / "docs/reports/OBS-EVAL/P2/H2-REBUILT-CARDS"
T207 = ROOT / "docs/reports/OBS-EVAL/P2/T207"
FROZEN_CONFIG = ROOT / "docs/evaluation/gate_v0_3.json"
APPROVED_CONFIG = ROOT / "docs/evaluation/gate_v0_3_approved.json"
REGISTRY = ROOT / "var/eval/baselines/7981d4afc2d1"
RAG_ROOTS = {
    "p2-t207-r1-20261111-01": Path(r"D:\mktkb-p2-run\t207\R1\data"),
    "p2-t207-r2-20261111-01": Path(r"D:\mktkb-p2-run\t207\R2\data"),
    "p2-t207-r4-20261111-01": Path(r"D:\mktkb-p2-run\t207\R4\data"),
}
OUT = Path(os.environ.get("P2_RELEASE_NCU_OUT")
           or (ROOT / "docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/gate-result.real-ncu.json"))
SELECTION_SUITE = {"N": "negative", "C": "boundary", "U": "update_delete"}
TARGET_SUITE = {"negative", "boundary", "update_delete"}


def run_ref(run_id: str, suite: str) -> dict:
    run_dir = T207 / run_id
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    rag_db = RAG_ROOTS[run_id] / "rag-index.sqlite3"
    if not rag_db.is_file():
        raise SystemExit(f"缺少历史 rag 库：{rag_db}")
    return {
        "suite": suite,
        "run_id": run_id,
        "run_dir": str(run_dir.relative_to(ROOT)),
        "artifacts": {name: file_sha256(run_dir / name)
                      for name in ("run_manifest.json", "summary.json", "dataset.jsonl", "cases.jsonl")},
        "original": {
            "gate_config_path": str(FROZEN_CONFIG.relative_to(ROOT)),
            "gate_config_sha256": file_sha256(FROZEN_CONFIG),
            "gate_config_hash": manifest["gate_config_hash"],
            "pipeline_version": manifest["pipeline_version"],
            "index_revision": manifest["index_revision"],
            "dataset_version": manifest["dataset_version"],
        },
        "rag_db": {"path": str(rag_db), "sha256": file_sha256(rag_db)},
    }


def build_inputs(work: Path) -> tuple[Path, dict]:
    """组装真实 N/C/U 输入清单（含 binding/applicability 证明回填），返回 (路径, payload)。"""
    work.mkdir(parents=True, exist_ok=True)
    manifest_path = NCU / "manifest.json"
    report_path = NCU / "report.md"
    sums_path = NCU / "SHA256SUMS"
    ncu = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs = {key: str(item.get("run_id")) for key, item in (ncu.get("runs") or {}).items()}
    frozen = (ncu.get("selection_policy") or {}).get("frozen_scope") or {}
    assignments = []
    per_suite_run: dict[tuple[str, str], list[str]] = {}
    for run_key, groups in frozen.items():
        for group, case_ids in (groups or {}).items():
            suite = SELECTION_SUITE[group]
            for case_id in case_ids:
                assignments.append({"suite": suite, "case_id": str(case_id),
                                    "run_id": runs[run_key]})
                per_suite_run.setdefault((suite, runs[run_key]), []).append(str(case_id))
    selection = {
        "schema_version": "p2-release-selection/v0.1",
        "authority": {
            "document": str(manifest_path.relative_to(ROOT)),
            "sha256": file_sha256(manifest_path),
            "section": "selection_policy.frozen_scope（任务 3 v2 清单）",
        },
        "assignments": assignments,
    }
    selection_path = work / "selection.json"
    selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    public_runs = []
    for (suite, run_id) in sorted(per_suite_run):
        if suite in {"negative", "boundary"}:
            public_runs.append(run_ref(run_id, suite))
    u_cases = sorted(per_suite_run.get(("update_delete", runs.get("R2", "")), []))
    if not u_cases:
        raise SystemExit("任务 3 清单缺少 U 组冻结范围")
    u_real = run_ref(runs["R2"], "update_delete")
    u_real["case_ids"] = u_cases
    controls = T207 / "scoring" / "u-controls.json"
    payload = {
        "schema_version": "p2-release-gate-inputs/v0.1",
        "gate_config": {"path": str(APPROVED_CONFIG.relative_to(ROOT)),
                        "sha256": file_sha256(APPROVED_CONFIG)},
        "candidate_pipeline": {"pipeline_source_sha256": pipeline_source_sha256(),
                               "pipeline_version": "candidate-mktkb.gate.v0.3"},
        "b0": {
            "baseline_root": "var/eval/baselines",
            "baseline_id": "7981d4afc2d1",
            "run_id": "p2-t209-b0-20261120-02",
            "baseline_sha256": file_sha256(REGISTRY / "baseline.json"),
            "admission_sha256": file_sha256(REGISTRY / "b0-admission.json"),
            "approval_sha256": file_sha256(REGISTRY / "b0-approval-receipt.json"),
        },
        "evidence_manifest": {
            "manifest": {"path": str(manifest_path.relative_to(ROOT)),
                         "sha256": file_sha256(manifest_path)},
            "report": {"path": str(report_path.relative_to(ROOT)),
                       "sha256": file_sha256(report_path)},
            "sha256sums": {"path": str(sums_path.relative_to(ROOT)),
                           "sha256": file_sha256(sums_path)},
        },
        "document_codes": {"path": str((T207 / "cases" / "document-codes.json").relative_to(ROOT)),
                           "sha256": file_sha256(T207 / "cases" / "document-codes.json")},
        "public": {
            "selection": {"path": str(selection_path), "sha256": file_sha256(selection_path)},
            "runs": public_runs,
        },
        "u": {
            "real": u_real,
            "local_controls": {"path": str(controls.relative_to(ROOT)),
                               "sha256": file_sha256(controls)},
        },
        "h2": {
            # D-001 受限边界：只喂聚合视图 + 卡索引 + 完整来源证明；卡本体不读。
            "source_proof": {"path": str((H2 / "h2-source-proof.full.json").relative_to(ROOT)),
                             "sha256": file_sha256(H2 / "h2-source-proof.full.json")},
            "composition_aggregate": {
                "path": str((H2 / "h2-composition-aggregate.json").relative_to(ROOT)),
                "sha256": file_sha256(H2 / "h2-composition-aggregate.json"),
            },
            "cards_index": {"path": str((H2 / "cards-index.json").relative_to(ROOT)),
                            "sha256": file_sha256(H2 / "cards-index.json")},
        },
    }
    inputs = work / "inputs.json"
    inputs.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    binding = emit_binding_proof(inputs, out_dir=work / "binding-proofs")
    for run in payload["public"]["runs"]:
        written = binding["written"].get(run["run_id"])
        if written:
            run["binding_proof"] = {"path": written["path"], "sha256": written["sha256"]}
    written = binding["written"].get(u_real["run_id"])
    if written:
        payload["u"]["real"]["binding_proof"] = {"path": written["path"], "sha256": written["sha256"]}
    inputs.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    applicability = emit_applicability_proof(inputs, out_dir=work / "applicability-proofs")
    for run in payload["public"]["runs"]:
        written = applicability["written"].get(run["run_id"])
        if written:
            run["applicability"] = {"path": written["path"], "sha256": written["sha256"]}
    written = applicability["written"].get(u_real["run_id"])
    if written:
        payload["u"]["real"]["applicability"] = {"path": written["path"],
                                                 "sha256": written["sha256"]}
    inputs.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return inputs, payload


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="p2-release-real-"))
    inputs, payload = build_inputs(work)
    manifest_path = NCU / "manifest.json"
    report_path = NCU / "report.md"
    sums_path = NCU / "SHA256SUMS"
    result = evaluate_release_gate(inputs)
    summary = result.to_dict()
    # 输入清单在临时目录重建（含临时证明路径），其摘要不稳定；产物只保留可复算工件摘要。
    summary.pop("inputs_sha256", None)
    for row in summary["rows"]:
        if row["row_id"] == "inputs":
            detail = dict(row.get("detail") or {})
            detail.pop("inputs_sha256", None)
            detail["inputs_digest"] = "omitted: 临时派生物（含临时证明路径），不写入产物"
            row["detail"] = detail
    summary["evidence_manifest"] = {
        "manifest_sha256": file_sha256(manifest_path),
        "report_sha256": file_sha256(report_path),
        "sha256sums_sha256": file_sha256(sums_path),
    }
    tiers = next((row["detail"]["tiers"] for row in summary["rows"]
                  if row["row_id"] == "evidence_manifest" and row["decision"] == "pass"), None)
    tallies = {row["row_id"]: row["detail"] for row in summary["rows"]
               if row["row_id"] in {"tallies.unconditional", "tallies.formal"}}
    h2_rows = {row["row_id"]: row for row in summary["rows"]
               if row["row_id"].startswith("h2.")}
    summary["ncu"] = {"tiers": tiers, "tallies": tallies, "sha256sums_verified": True}
    summary["h2"] = {
        "boundary": "D-001 受限：卡本体在仓外，只做聚合外层核验",
        "files": {
            "source_proof": file_sha256(H2 / "h2-source-proof.full.json"),
            "composition_aggregate": file_sha256(H2 / "h2-composition-aggregate.json"),
            "cards_index": file_sha256(H2 / "cards-index.json"),
        },
        "rows": {row_id: row["decision"] for row_id, row in h2_rows.items()},
    }
    rows = {row["row_id"]: row for row in summary["rows"]}
    summary["binding_proofs"] = {
        row_id.split(".", 1)[1]: {
            "recorded_index_revision": detail.get("recorded_index_revision"),
            "attested_index_revision": detail.get("attested_index_revision"),
            "rewritten_trace_rows": detail.get("rewritten_trace_rows"),
            "trace_rows_total": detail.get("trace_rows_total"),
            "zero_rewrite_legal": detail.get("zero_rewrite_legal"),
            "status": row["decision"],
        }
        for row_id, row in rows.items() if row_id.startswith("binding.")
        for detail in [row["detail"] if "recorded_index_revision" in row["detail"]
                       else (row["detail"].get("evidence") or {})]
    }
    # 输入清单每次在临时目录重建（证明文件路径不同），其摘要不稳定，故不写进产物；
    # 产物只保留**可复算**的工件摘要（任务 3 三件、H2 三件、proof 摘要等）。
    summary["probe_work_dir_note"] = "临时目录，不随交付保留"
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "decision": result.decision, "out": str(OUT),
                      "counts": summary["counts"], "reason_codes": summary["reason_codes"]},
                     ensure_ascii=False))
    return 0 if result.decision == "pass" else (4 if result.decision == "pending" else 3)


if __name__ == "__main__":
    raise SystemExit(main())
