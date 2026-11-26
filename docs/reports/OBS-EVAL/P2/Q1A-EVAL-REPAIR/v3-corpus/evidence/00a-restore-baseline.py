"""重建「开工前基线」快照（仅在 00 被误重跑后使用；本文件即事件记录）。

发生了什么：``00-snapshot-before.py`` 原本每次都写 ``00-snapshot-before.json``。收尾阶段
把整条流水线重跑一遍时，它把真正的『之前』覆盖成了『之后』。已给 00 加上「存在即拒绝」
的幂等保护；这里做**减法重建**，并把重建依据写在文件里，避免任何隐形改动。

重建口径（逐字段说明来源）：
- ``branch`` / ``head`` / ``staged`` / ``tracked_modified`` / ``v2_corpus`` / ``c_freeze_12`` /
  ``readonly_inputs``：这些在收尾时**重新实测**与开工时逐字相同（07-preservation 的
  ``branch_unchanged`` / ``head_unchanged_no_commits`` / ``staged_empty`` /
  ``tracked_modified_paths_unchanged`` / ``v2_corpus_byte_identical`` /
  ``c_freeze_12_unchanged`` / ``readonly_inputs_unchanged`` 全为 true），故直接沿用当前实测值；
- ``untracked``：用当前 untracked 列表减去本轮**新增的两个**顶层 untracked 条目
  （``docs/evaluation/p2-holdout-v3.source-map.json``、``fixtures/acceptance-h2v3/``）；
  本轮 evidence 目录位于一个**本来就 untracked** 的父目录下，不产生新的顶层条目。
  减法后的条数必须等于开工时记录的 222。

零真实调用；只读 git 与文件。
用法：``.venv\\Scripts\\python.exe 00a-restore-baseline.py``
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
HERE = Path(__file__).resolve().parent
OUT = HERE / "00-snapshot-before.json"
C_FREEZE_BASELINE = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json"
ADDED_THIS_ROUND = (
    "docs/evaluation/p2-holdout-v3.source-map.json",
    "fixtures/acceptance-h2v3/",
)
EXPECTED_PRIOR_UNTRACKED = 222
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
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True)
    return result.stdout.decode("utf-8", "replace")


def main() -> int:
    status = git("status", "--porcelain").splitlines()
    tracked_modified = sorted(line[3:] for line in status if line[:2].strip() not in ("??", ""))
    untracked_now = sorted(line[3:] for line in status if line[:2] == "??")
    untracked_prior = [path for path in untracked_now if path not in ADDED_THIS_ROUND]
    if len(untracked_prior) != EXPECTED_PRIOR_UNTRACKED:
        raise SystemExit(f"减法重建条数不符：{len(untracked_prior)} != {EXPECTED_PRIOR_UNTRACKED}（停止，不猜）")
    v2_root = ROOT / "fixtures/acceptance"
    v2_files = {
        str(path.relative_to(v2_root)).replace("\\", "/"): {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(v2_root.rglob("*"))
        if path.is_file()
    }
    baseline = json.loads(C_FREEZE_BASELINE.read_text(encoding="utf-8"))["c_freeze_12"]
    c_freeze_now = {rel: sha256(ROOT / rel) for rel in sorted(baseline)}
    payload = {
        "schema_version": "p2h2v3-corpus-snapshot/v0.1",
        "phase": "before",
        "capture_note": "重建件：00-snapshot-before.py 在收尾重跑时被误覆盖，本文件由 00a-restore-baseline.py 以『当前实测 - 本轮新增 untracked』重算；不变量字段均为收尾实测且与开工值相等。",
        "reconstruction": {
            "tool": "00a-restore-baseline.py",
            "removed_untracked_entries": list(ADDED_THIS_ROUND),
            "prior_untracked_expected": EXPECTED_PRIOR_UNTRACKED,
            "prior_untracked_actual": len(untracked_prior),
        },
        "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "head": git("rev-parse", "HEAD").strip(),
        "staged": [line for line in git("diff", "--cached", "--name-only").splitlines() if line.strip()],
        "tracked_modified": tracked_modified,
        "tracked_modified_count": len(tracked_modified),
        "untracked_count": len(untracked_prior),
        "untracked": untracked_prior,
        "v2_corpus": v2_files,
        "v2_corpus_file_count": len(v2_files),
        "c_freeze_12_baseline_ref": str(C_FREEZE_BASELINE.relative_to(ROOT)).replace("\\", "/"),
        "c_freeze_12": {
            rel: {"expected": baseline[rel], "actual": c_freeze_now[rel], "equal": c_freeze_now[rel] == baseline[rel]}
            for rel in sorted(baseline)
        },
        "c_freeze_12_mismatch_count": sum(1 for rel in baseline if c_freeze_now[rel] != baseline[rel]),
        "readonly_inputs": {rel: {"bytes": (ROOT / rel).stat().st_size, "sha256": sha256(ROOT / rel)} for rel in READONLY_INPUTS},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "restored": str(OUT),
        "tracked_modified_count": payload["tracked_modified_count"],
        "staged": len(payload["staged"]),
        "untracked_count": payload["untracked_count"],
        "c_freeze_mismatch": payload["c_freeze_12_mismatch_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
