"""v3 语料：开工前基线快照（本目录新增文件的「之前」侧）。

采集内容（只读、零调用）：
- git 事实：分支 / HEAD / 暂存区 / tracked modified / untracked 全量
- v2 语料（fixtures/acceptance/**）逐文件 SHA256：本轮必须一个字节都不变
- C 冻结 12（含 3 个键空间规则件）与基线清单逐项比对
- 8 份只读输入件 SHA256：两份计划、判据 v1.1、L1、v2 source-map、v2 manifest、
  p2_holdout_scenarios.py、retrieval/index.py / rag/chunking.py / retrieval/tokenize.py

用法：``.venv\\Scripts\\python.exe 00-snapshot-before.py``
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
OUT = Path(__file__).resolve().parent / "00-snapshot-before.json"

C_FREEZE_BASELINE = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json"

READONLY_INPUTS = (
    "docs/superpowers/plans/2026-11-15-h2-v3-corpus-modification-spec.md",
    "docs/superpowers/plans/2026-11-15-h2-v3-authoring-plan.md",
    "docs/evaluation/p2-stale-source-criterion-v1_1.md",
    "docs/evaluation/p2-source-lifecycle-v1.json",
    "docs/evaluation/p2-holdout-v2.source-map.json",
    "fixtures/acceptance/manifest.json",
    "backend/src/mktkb/evaluation/p2_holdout_scenarios.py",
    "backend/src/mktkb/retrieval/index.py",
    "backend/src/mktkb/rag/chunking.py",
    "backend/src/mktkb/retrieval/tokenize.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, check=True
    )
    return result.stdout.decode("utf-8", "replace")


def main() -> int:
    if OUT.exists():
        raise SystemExit(
            f"{OUT.name} 已存在：基线只允许采一次（重复采集会把『之前』覆盖成『之后』）。"
            "如需重建，用 00a-restore-baseline.py 并在报告里写明来源。"
        )
    status = git("status", "--porcelain").splitlines()
    tracked_modified = sorted(line[3:] for line in status if line[:2].strip() not in ("??", ""))
    untracked = sorted(line[3:] for line in status if line[:2] == "??")
    v2_root = ROOT / "fixtures/acceptance"
    v2_files = {
        str(path.relative_to(v2_root)).replace("\\", "/"): {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(v2_root.rglob("*"))
        if path.is_file()
    }
    baseline = json.loads(C_FREEZE_BASELINE.read_text(encoding="utf-8"))
    c_freeze_baseline = baseline["c_freeze_12"]
    c_freeze_now = {rel: sha256(ROOT / rel) for rel in sorted(c_freeze_baseline)}
    payload = {
        "schema_version": "p2h2v3-corpus-snapshot/v0.1",
        "phase": "before",
        "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "head": git("rev-parse", "HEAD").strip(),
        "staged": [line for line in git("diff", "--cached", "--name-only").splitlines() if line.strip()],
        "tracked_modified": tracked_modified,
        "tracked_modified_count": len(tracked_modified),
        "untracked_count": len(untracked),
        "untracked": untracked,
        "v2_corpus": v2_files,
        "v2_corpus_file_count": len(v2_files),
        "c_freeze_12_baseline_ref": str(C_FREEZE_BASELINE.relative_to(ROOT)).replace("\\", "/"),
        "c_freeze_12": {
            rel: {"expected": c_freeze_baseline[rel], "actual": c_freeze_now[rel], "equal": c_freeze_now[rel] == c_freeze_baseline[rel]}
            for rel in sorted(c_freeze_baseline)
        },
        "c_freeze_12_mismatch_count": sum(1 for rel in c_freeze_baseline if c_freeze_now[rel] != c_freeze_baseline[rel]),
        "readonly_inputs": {
            rel: {"bytes": (ROOT / rel).stat().st_size, "sha256": sha256(ROOT / rel)} for rel in READONLY_INPUTS
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "phase": "before",
                "branch": payload["branch"],
                "head": payload["head"],
                "staged": len(payload["staged"]),
                "tracked_modified_count": payload["tracked_modified_count"],
                "untracked_count": payload["untracked_count"],
                "v2_corpus_file_count": payload["v2_corpus_file_count"],
                "c_freeze_mismatch": payload["c_freeze_12_mismatch_count"],
                "out": str(OUT),
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload["c_freeze_12_mismatch_count"] == 0 and not payload["staged"] else 1


if __name__ == "__main__":
    sys.exit(main())
