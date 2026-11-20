"""生成正式门禁的输入清单模板（B0 绑定已登记基线，N/C/U 与 H2 标 PENDING）。

用法（仓库根）：

    .\\.venv\\Scripts\\python.exe docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/build_template_inputs.py

本脚本只写 ``inputs.template.json``，不发任何真实请求。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

def _project_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "backend" / "src" / "mktkb").is_dir():
            return candidate
    raise SystemExit("找不到仓库根（backend/src/mktkb）")


ROOT = _project_root()
if str(ROOT / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "src"))

from mktkb.evaluation.p2_b0 import load_approved_b0_config, pipeline_source_sha256  # noqa: E402
from mktkb.evaluation.p2_release_model import file_sha256  # noqa: E402


def main() -> int:
    registry = ROOT / "var" / "eval" / "baselines" / "7981d4afc2d1"
    approved = ROOT / "docs" / "evaluation" / "gate_v0_3_approved.json"
    config = load_approved_b0_config(approved)
    payload = {
        "schema_version": "p2-release-gate-inputs/v0.1",
        "gate_config": {"path": "docs/evaluation/gate_v0_3_approved.json",
                        "sha256": file_sha256(approved)},
        "candidate_pipeline": {
            "pipeline_source_sha256": pipeline_source_sha256(),
            "pipeline_version": f"candidate-{config.gate_version}",
        },
        "b0": {
            "baseline_root": "var/eval/baselines",
            "baseline_id": "7981d4afc2d1",
            "run_id": "p2-t209-b0-20261120-02",
            "baseline_sha256": file_sha256(registry / "baseline.json"),
            "admission_sha256": file_sha256(registry / "b0-admission.json"),
            "approval_sha256": file_sha256(registry / "b0-approval-receipt.json"),
        },
        "pending": {"public": "PENDING-TASK3", "u": "PENDING-TASK3", "h2": "PENDING-TASK2"},
    }
    target = ROOT / "docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/inputs.template.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(target), "sha256": file_sha256(target)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
