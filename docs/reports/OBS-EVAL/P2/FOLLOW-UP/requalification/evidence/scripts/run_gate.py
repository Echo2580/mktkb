"""正式跨场景门禁（新 B0 已重新登记后的同一候选）。

用法（仓库根）：
    .venv\\Scripts\\python.exe -X utf8 <本文件> --out-dir <dir>

做法：
1. 复用已交付的正式接线脚本 ``wire_real_ncu.build_inputs``（真实 N/C/U + H2 聚合 + 历史绑定/适用性
   证明），**不改它**；
2. 只把输入清单里的 ``b0`` 换成本轮新接收的基线（2b40ee9b4740 / p2-t209-b0-20261121-01，摘要取自
   登记目录实数），``candidate_pipeline`` 仍由 ``pipeline_source_sha256()`` 现算（= 13a962ed…）；
3. 重发绑定/适用性证明后调正式入口 ``evaluate_release_gate``；
4. 结果写 ``gate/inputs.json``、``gate/gate-result.json``。

只读历史证据与旧门禁快照；不覆盖 ``CROSS-SCENARIO-GATE/`` 下的任何既有文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]
SCRIPTS = ROOT / "docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(SCRIPTS))
    import wire_real_ncu as W  # noqa: E402

    from mktkb.evaluation.p2_b0 import pipeline_source_sha256  # noqa: E402
    from mktkb.evaluation.p2_release_gate import (  # noqa: E402
        emit_applicability_proof,
        emit_binding_proof,
        evaluate_release_gate,
    )
    from mktkb.evaluation.p2_release_inputs import B0_BASELINE_ID, B0_RUN_ID, B0_REGISTRY_ROOT  # noqa: E402

    registry = B0_REGISTRY_ROOT / B0_BASELINE_ID
    # ``build_inputs`` 自带的两步发证会在"b0 仍写旧基线"的中间态触发身份门（门禁已重新登记）。
    # 这里先只让它组装 payload，再由本脚本在**换好 b0 之后**用同一对正式函数发证。
    real_binding, real_applicability = W.emit_binding_proof, W.emit_applicability_proof
    W.emit_binding_proof = lambda *_a, **_k: {"written": {}}  # type: ignore[assignment]
    W.emit_applicability_proof = lambda *_a, **_k: {"written": {}}  # type: ignore[assignment]
    try:
        inputs_path, payload = W.build_inputs(out_dir / "work")
    finally:
        W.emit_binding_proof, W.emit_applicability_proof = real_binding, real_applicability
    before_b0 = json.loads(json.dumps(payload["b0"]))
    payload["candidate_pipeline"]["pipeline_source_sha256"] = pipeline_source_sha256()
    payload["b0"] = {
        "baseline_root": str(B0_REGISTRY_ROOT.relative_to(ROOT)).replace("\\", "/"),
        "baseline_id": B0_BASELINE_ID,
        "run_id": B0_RUN_ID,
        "baseline_sha256": file_sha256(registry / "baseline.json"),
        "admission_sha256": file_sha256(registry / "b0-admission.json"),
        "approval_sha256": file_sha256(registry / "b0-approval-receipt.json"),
    }
    inputs_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 重发两份证明，使它们与最终输入清单一致（证明本身只绑 run 身份）。
    binding = emit_binding_proof(inputs_path, out_dir=out_dir / "binding-proofs")
    for run in payload["public"]["runs"]:
        written = binding["written"].get(run["run_id"])
        if written:
            run["binding_proof"] = {"path": written["path"], "sha256": written["sha256"]}
    written = binding["written"].get(payload["u"]["real"]["run_id"])
    if written:
        payload["u"]["real"]["binding_proof"] = {"path": written["path"], "sha256": written["sha256"]}
    inputs_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    applicability = emit_applicability_proof(inputs_path, out_dir=out_dir / "applicability-proofs")
    for run in payload["public"]["runs"]:
        written = applicability["written"].get(run["run_id"])
        if written:
            run["applicability"] = {"path": written["path"], "sha256": written["sha256"]}
    written = applicability["written"].get(payload["u"]["real"]["run_id"])
    if written:
        payload["u"]["real"]["applicability"] = {"path": written["path"], "sha256": written["sha256"]}
    final_inputs = out_dir / "inputs.json"
    final_inputs.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = evaluate_release_gate(final_inputs)
    summary = result.to_dict()
    summary["inputs_sha256"] = file_sha256(final_inputs)
    summary["b0_registration_change"] = {"before": before_b0, "after": payload["b0"]}
    (out_dir / "gate-result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    rows = {row["row_id"]: row for row in summary["rows"]}
    print(json.dumps(
        {
            "decision": summary["decision"],
            "counts": summary["counts"],
            "blocked_rows": [row["row_id"] for row in summary["rows"] if row["decision"] == "blocked"],
            "pending": summary["pending"],
            "candidate_pipeline": rows["candidate.pipeline"]["decision"],
            "b0_admission": rows["b0.admission"]["decision"],
            "evidence_provenance": rows.get("evidence_provenance", {}).get("decision"),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if summary["decision"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
