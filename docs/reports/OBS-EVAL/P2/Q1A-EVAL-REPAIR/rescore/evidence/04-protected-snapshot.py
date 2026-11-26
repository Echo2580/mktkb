"""保护件快照：对 C 冻结 12 / 旧 run 树 / 合同密文 / Q1a-1·Q1a-1b 模块与契约 / 账本·预算·GO 取 SHA256。

用法：python 04-protected-snapshot.py before|after > 04-protected-<label>.json
只输出路径与 hash；不读内容语义、不打印任何题面/答案/目标值。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(REPO / "tools"))

RUN_ROOT = Path(r"D:\mktkb-p2-t207-h2-20261114")
CONTRACT_CIPHER = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v1.fernet")
HOLDOUT_ROOT = Path(r"D:\mktkb-p2-holdout\v2")
CUSTODY = Path(
    r"C:\Users\dell1712\.codex\visualizations\2026\11\12\01a1cd24-bccf-7e00-80df-0b75f57f7d1c\t207-custody"
)

REPO_FILES = [
    "backend/src/mktkb/evaluation/p2_hard_evidence.py",
    "backend/src/mktkb/evaluation/p2_evidence_rescore.py",
    "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py",
    "backend/src/mktkb/evaluation/p2_holdout_scenarios.py",
    "backend/src/mktkb/evaluation/p2_evidence_io.py",
    "backend/src/mktkb/evaluation/p2_dataset.py",
    "docs/evaluation/p2-evidence-rescore-v0_1.md",
    "docs/evaluation/p2-evidence-rescore-v0_2.md",
    "docs/evaluation/q1a-scope-targets-contract-v1.md",
    "docs/evaluation/p2-holdout-v2.manifest.json",
    "docs/evaluation/p2-holdout-v2.source-map.json",
    "docs/evaluation/p2-h2-scenarios-v0_2.json",
    "docs/evaluation/p2-h2-custody-annotations-v0_2.md",
    "tools/p2_h2_controlled_execute.py",
    "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/manager-acceptance.json",
    "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V2/review-aggregate.json",
    "docs/reports/OBS-EVAL/P2/T207-CUSTODY-V3/manager-acceptance.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/manager-acceptance.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/annotation-aggregate.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/scope-contract/review-aggregate.json",
    "docs/reports/OBS-EVAL/P2/T207-SAFETY-TRIAGE-20261114/manager-receipt.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/evaluator/manager-receipt.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/manager-acceptance.json",
]

EXTERNAL_DIRS = {
    "old_run_tree": RUN_ROOT,
    "holdout_root": HOLDOUT_ROOT,
    "custody_annotations": CUSTODY,
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "before"
    import p2_h2_controlled_execute as entry

    repo_rows = {}
    for rel in REPO_FILES:
        path = REPO / rel
        repo_rows[rel] = {"sha256": sha(path.read_bytes()), "bytes": path.stat().st_size}

    external = {}
    for name, root in EXTERNAL_DIRS.items():
        digest = entry.tree_digest(root)
        external[name] = {
            "root": str(root),
            "file_count": digest["file_count"],
            "bytes": digest["bytes"],
            "tree_sha256": digest["tree_sha256"],
            "files": {row["path"]: row["sha256"] for row in digest["files"]},
        }
    external["contract_ciphertext"] = {
        "root": str(CONTRACT_CIPHER),
        "sha256": sha(CONTRACT_CIPHER.read_bytes()),
        "bytes": CONTRACT_CIPHER.stat().st_size,
    }

    print(
        json.dumps(
            {
                "schema_version": "q1a3-protected-snapshot/v0.1",
                "label": label,
                "repo_files": repo_rows,
                "external": external,
                "calls": {"network": 0, "socket": 0, "dns": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
