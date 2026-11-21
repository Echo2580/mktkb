"""FU-2 缺口 B 的**可行性探针**（不是端到端派生）。

用途：确认"完全合成的 v3 单 run 材料"能否通过**产品侧正式校验器**，从而判定
``derive-cards`` 能否在不触碰任何真实受限件的前提下端到端跑通。

做法：
1. 复用本仓库既有的合成 v3 包构造器（``backend/tests/evaluation/test_p2_v3_wiring._package``，
   corpus='v3'：合成封存 dataset 30 题/36 回合 + v3 语料 ingest + 合成 custody 元数据）；
2. 用**正式** ``hard.prepare_annotation``（真实 ``p2-h2-custody-annotations-v0_2.md`` 与
   真实 v3 scenario contract）校验该合成注解；
3. 输出结论与轴计数。

边界：本探针**不**跑 ``derive-cards`` CLI、**不**产出评分卡；端到端派生仍为 NOT-RUN
（需再构造 case-plan、逐回合密文证据与封存回执，属后续工作）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "backend/tests/evaluation"))
    import test_p2_v3_wiring as W  # noqa: E402

    from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
    from mktkb.evaluation import p2_holdout_scenarios_v3 as C3  # noqa: E402
    from mktkb.evaluation.dataset import cases_to_jsonl  # noqa: E402

    def sha(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    class _Env:
        def setenv(self, key: str, value: str) -> None:
            import os

            os.environ[key] = value

    work = Path(tempfile.mkdtemp(prefix="p2-fu2-feasibility-"))
    package = W._package(work, _Env(), corpus="v3")
    paths = package.paths
    bindings = {
        "manifest_sha256": package.dataset.manifest.manifest_sha256,
        "dataset_version": package.dataset.manifest.dataset_version,
        "label_version": package.dataset.manifest.label_version,
        "cases_sha256": sha(cases_to_jsonl(package.dataset.cases).encode("utf-8")),
        "source_map_sha256": sha(Path(paths["source_map_path"]).read_bytes()),
        "ingest_plan_sha256": sha(Path(paths["ingest_path"]).read_bytes()),
        "schema_sha256": sha(C3.V3_SCHEMA.read_bytes()),
        "scenario_contract_sha256": sha(C3.V3_SCENARIO_CONTRACT.read_bytes()),
    }
    priority = ["base_b0", "base_b0_plus_v01", "pre_v05_without_v07", "post_v05_without_v01"]
    payload = W._annotation_payload(package.dataset, priority, bindings)
    result: dict[str, object] = {
        "schema": "p2-fu2-feasibility/v0.1",
        "kind": "offline-feasibility-probe",
        "scope": "confirms the synthetic v3 bundle passes the real annotation validator; NOT an end-to-end derive-cards run",
        "dataset": {
            "cases": len(package.dataset.cases),
            "turns": sum(len(case.turns) if len(case.turns) >= 2 else 1 for case in package.dataset.cases),
            "manifest_sha256": bindings["manifest_sha256"],
        },
        "real_inputs_used": {
            "scenario_contract": str(C3.V3_SCENARIO_CONTRACT.relative_to(ROOT)).replace("\\", "/"),
            "annotation_schema": str(C3.V3_SCHEMA.relative_to(ROOT)).replace("\\", "/"),
            "corpus_root": "fixtures/acceptance-h2v3",
        },
        "private_material_read": False,
    }
    try:
        annotation = hard.prepare_annotation(
            payload,
            package.dataset.cases,
            schema_path=C3.V3_SCHEMA,
            scenario_path=C3.V3_SCENARIO_CONTRACT,
        )
    except Exception as exc:  # noqa: BLE001 - 探针如实记录任何拒绝
        result["annotation_validator"] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        ok = False
    else:
        result["annotation_validator"] = {
            "ok": True,
            "public_summary": annotation.public_summary(),
        }
        result["end_to_end_derive_cards"] = {
            "status": "NOT-RUN",
            "reason": (
                "端到端还需再构造：v3 case-plan（36 回合逐题行）、每回合 Fernet 密文证据"
                "（须与 run_binding/control 逐值一致并满足 classify_case_evidence 的事件结构）、"
                "封存回执或封存 manifest，以及 14 项 inputs 记录的绑定文档。"
                "本轮未完成，未产出评分卡；不得据此声称 FU-2 成功分支已独立复现。"
            ),
        }
        ok = True
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps(
        {
            "annotation_ok": result["annotation_validator"]["ok"],
            "cases": result["dataset"]["cases"],
            "turns": result["dataset"]["turns"],
            "end_to_end": result.get("end_to_end_derive_cards", {}).get("status", "FAILED"),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
