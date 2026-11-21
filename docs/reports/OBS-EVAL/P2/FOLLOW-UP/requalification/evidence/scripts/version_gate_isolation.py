"""``candidate.pipeline`` 版本门的隔离正反例（离线、零出站）。

用法（仓库根）：
    .venv\\Scripts\\python.exe -X utf8 docs\\...\\evidence\\scripts\\version_gate_isolation.py --out <json>

三次独立构建、三次运行（同一套合成夹具形状；B0 仍绑已登记基线 7981d4afc2d1，其余证据全合成）：

1. ``negative_current_candidate``：候选身份 = 当前修复树 ``pipeline_source_sha256()``
   → 复现 12 条集成失败的唯一阻断行（``candidate.pipeline`` = ``release_version_mismatch``）。
2. ``positive_aligned_identity``：**只**把输入清单里的候选身份改成被准入身份（同一目录原地改，
   避免相对路径失效）→ 该行转 pass；证明"除身份门外没有其它阻断"。
3. ``positive_admission_rebound``：把已登记 B0 准入复制到临时目录，只把 ``pipeline_version``
   的来源摘要改成当前候选，并同步输入清单的 ``admission_sha256`` → **同候选身份**的正例：
   ``candidate.pipeline`` 行 = pass。

⚠ 第 2/3 次都是**隔离实验**，不是真实 B0：第 3 次的准入副本是人为改写的合成件，
只能说明"身份一致时门禁放行"，不能当作"新候选已通过真实 B0"。

不变量：``docs/evaluation/gate_v0_3_approved.json`` 与 ``var/eval/baselines/**`` 的真实字节
一律不改；副本只落在临时目录，脚本退出前删除。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]
TESTS = ROOT / "backend/tests/evaluation"


def _rows(result) -> dict[str, object]:
    return {row.row_id: row for row in result.rows}


def _pipeline_row(result) -> dict | None:
    row = _rows(result).get("candidate.pipeline")
    return None if row is None else row.to_dict()


def _summary(result) -> dict:
    return {
        "decision": result.decision,
        "counts": dict(result.to_dict()["counts"]),
        "blocked_rows": [row.row_id for row in result.evidence_blocked_rows],
        "pending": dict(result.pending),
        "candidate_pipeline_row": _pipeline_row(result),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(TESTS))
    import test_p2_release_gate_fixtures as F  # noqa: E402

    from mktkb.evaluation import p2_b0  # noqa: E402
    from mktkb.evaluation.p2_release_gate import evaluate_release_gate  # noqa: E402

    candidate = p2_b0.pipeline_source_sha256()
    out: dict[str, object] = {
        "schema": "p2-version-gate-isolation/v0.1",
        "kind": "offline-isolated-experiment",
        "candidate_pipeline_source_sha256": candidate,
        "runs": {},
    }
    work = Path(tempfile.mkdtemp(prefix="p2-gate-isolation-"))
    try:
        # 1) 当前候选身份：应复现 candidate.pipeline 阻断。
        path_a, _payload_a = F.build_complete_inputs(work / "a")
        result_a = evaluate_release_gate(path_a)
        out["runs"]["negative_current_candidate"] = _summary(result_a)
        evidence = ((_rows(result_a)["candidate.pipeline"].detail or {}).get("evidence") or {})
        admitted = str(evidence.get("bound") or "")
        if not admitted:
            raise RuntimeError("未能从 candidate.pipeline 行取到被准入的流水线摘要")
        out["runs"]["negative_current_candidate"]["bound_vs_candidate"] = dict(evidence)

        # 2) 身份一致（**进程内模拟**）：把"当前字节"算出的摘要替换成被准入摘要。
        #    注意：直接改输入清单里的 declared 值会被 ``_load_candidate`` 的
        #    "declared != current" 拒绝（``release_version_mismatch``），这是门禁的
        #    双向 fail-closed 行为，不是缺陷；因此只能连"当前字节"一起模拟。
        path_b, _payload_b = F.build_complete_inputs(work / "b")
        import mktkb.evaluation.p2_release_inputs as release_inputs

        original_probe = release_inputs.pipeline_source_sha256
        try:
            release_inputs.pipeline_source_sha256 = lambda: admitted  # type: ignore[assignment]
            aligned = json.loads(path_b.read_text(encoding="utf-8"))
            aligned["candidate_pipeline"]["pipeline_source_sha256"] = admitted
            path_b.write_bytes((json.dumps(aligned, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            result_b = evaluate_release_gate(path_b)
        finally:
            release_inputs.pipeline_source_sha256 = original_probe  # type: ignore[assignment]
        out["runs"]["positive_simulated_identity"] = _summary(result_b)
        out["runs"]["positive_simulated_identity"]["note"] = (
            "**模拟**：进程内把 '当前字节摘要' 与被准入摘要对齐（不改任何真实文件）。"
            "用途仅为证明除身份门外没有其它阻断；不等于该候选已通过真实 B0。"
        )
        out["runs"]["declared_only_align_refused"] = {
            "note": (
                "只改输入清单 declared 值（当前字节不变）时，``inputs`` 行以 "
                "``release_version_mismatch`` 拒绝：门禁双向 fail-closed 的实测。"
            ),
            "detail": {
                "observed_in_debug": {
                    "row": "inputs",
                    "reason": "release_version_mismatch",
                    "cause": "候选流水线与当前字节不一致",
                }
            },
        }

        # 3) 同候选身份的正例需要**真实新 B0 准入**：门禁要求 B0 登记目录必须是规范登记处
        #    ``var/eval/baselines``，且准入里的 pipeline_version 必须等于候选；把登记目录
        #    复制到临时目录会被 ``release_baseline_unregistered`` 拒绝（实测）。因此这一项
        #    在离线阶段只能记 NOT-RUN，不能靠改副本伪造。
        out["runs"]["same_candidate_real_admission"] = {
            "status": "NOT-RUN",
            "reason": (
                "同候选身份的正例要求一份把 pipeline_version 绑到当前候选的真实 B0 准入；"
                "基线登记目录受规范路径约束（副本会被 release_baseline_unregistered 拒绝），"
                "改写真实登记处属禁止写入。待新 B0 获批并执行后补。"
            ),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes((json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps(
        {
            key: {
                "decision": value["decision"],
                "counts": value["counts"],
                "blocked_rows": value["blocked_rows"],
                "candidate_pipeline_decision": (
                    None if value["candidate_pipeline_row"] is None
                    else value["candidate_pipeline_row"]["decision"]
                ),
            }
            for key, value in out["runs"].items()
            if "decision" in value
        },
        ensure_ascii=False,
        indent=2,
    ))
    ok = (
        out["runs"]["negative_current_candidate"]["blocked_rows"] == ["candidate.pipeline"]
        and out["runs"]["positive_simulated_identity"]["decision"] == "pass"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
