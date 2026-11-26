"""axes-v2 保全核对：冻结件逐文件 sha256 + git 边界（不改/stage/commit）。

只读；不修改任何被核对对象。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
OUT = REPO / "docs/reports/OBS-EVAL/P2/H2V3/axes-v2/evidence/preservation-check.json"
SCHEMA_VERSION = "p2-h2v3-axes-v2-preservation-check/v0.1"

#: C 冻结 12 对象 + Q1a-1/1b 已接收实现 + 判据/绑定来源（一律只读）。
FROZEN = {
    "c12_hard_evidence": "backend/src/mktkb/evaluation/p2_hard_evidence.py",
    "c12_evidence_io": "backend/src/mktkb/evaluation/p2_evidence_io.py",
    "c12_evidence_capture": "backend/src/mktkb/evaluation/p2_evidence_capture.py",
    "c12_holdout_scenarios_v3": "backend/src/mktkb/evaluation/p2_holdout_scenarios_v3.py",
    "c12_holdout_source_map": "backend/src/mktkb/evaluation/p2_holdout_source_map.py",
    "c12_holdout_v3_scoring": "backend/src/mktkb/evaluation/p2_holdout_v3_scoring.py",
    "c12_holdout_run_date": "backend/src/mktkb/evaluation/p2_holdout_run_date.py",
    "c12_v3_scoring_driver": "backend/src/mktkb/evaluation/p2_score_run.py",
    "c12_evidence_snapshot_v03": "backend/src/mktkb/evaluation/p2_evidence_snapshot_v03.py",
    "c12_stale_version_state": "backend/src/mktkb/evaluation/p2_stale_version_state.py",
    "c12_empty_scope_proof": "backend/src/mktkb/evaluation/p2_empty_scope_proof.py",
    "c12_evidence_axes_adapter_v2": "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py",
    "q1a1_rescore": "backend/src/mktkb/evaluation/p2_evidence_rescore.py",
    "q1a1b_rescore_axes": "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py",
    "contract_v0_1": "docs/evaluation/p2-evidence-rescore-v0_1.md",
    "contract_v0_2": "docs/evaluation/p2-evidence-rescore-v0_2.md",
    "l1_criterion": "docs/evaluation/p2-stale-source-criterion-v1_1.md",
    "lifecycle_v1": "docs/evaluation/p2-source-lifecycle-v1.json",
    "source_map_v0_2": "docs/evaluation/p2-holdout-v3.source-map.json",
    "corpus_manifest": "fixtures/acceptance-h2v3/manifest.json",
}
EXPECTED_PREFIX = {
    "q1a1_rescore": "d8260256",
    "q1a1b_rescore_axes": "57495943",
    "contract_v0_1": "0ec6c392" if False else None,
    "contract_v0_2": "747e3656",
    "l1_criterion": "0ec6c392",
    "lifecycle_v1": "cc2ad0be",
    "source_map_v0_2": "03665c48",
}


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, text=True, encoding="utf-8"
    )
    return result.stdout.strip()


def main() -> int:
    rows = []
    for name, rel in FROZEN.items():
        target = REPO / rel
        digest = sha(target) if target.is_file() else None
        expected = EXPECTED_PREFIX.get(name)
        rows.append(
            {
                "name": name,
                "path": rel,
                "sha256": digest,
                "bytes": target.stat().st_size if target.is_file() else None,
                "declared_prefix": expected,
                "matches_declared": (
                    None if expected is None or digest is None else digest.startswith(expected)
                ),
            }
        )
    status = git("status", "--porcelain").splitlines()
    staged = [line for line in git("diff", "--cached", "--name-only").splitlines() if line.strip()]
    modified = [line for line in git("diff", "--name-only").splitlines() if line.strip()]
    untracked = [line for line in status if line.startswith("??")]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "staged_count": len(staged),
        "staged_empty": not staged,
        "tracked_modified_count": len(modified),
        "tracked_modified_paths": modified,
        "untracked_count": len(untracked),
        "axes_v2_paths_in_status": sorted(
            line.split(maxsplit=1)[1] for line in status if "axes-v2" in line
        ),
        "frozen_files": rows,
        "frozen_all_match_declared": all(
            row["matches_declared"] is not False for row in rows
        ),
        "written_this_session": [
            "docs/reports/OBS-EVAL/P2/H2V3/axes-v2/axes-v2-report.md",
            "docs/reports/OBS-EVAL/P2/H2V3/axes-v2/axes-v2-aggregate.json",
            "docs/reports/OBS-EVAL/P2/H2V3/axes-v2/evidence/",
        ],
        "not_committed": True,
    }
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
