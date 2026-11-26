"""v3 语料：收尾保全核对（「之前」快照 vs 现在）。

逐项证明本轮**没有**动到别人的东西：
1. 分支/HEAD 不变（0 commit）、暂存区 0；
2. 15 个 tracked modified 路径逐条不变；
3. untracked：之前 222 条必须仍是 now 的子集，新增只允许出现在本轮三个新增路径下；
4. ``fixtures/acceptance/**`` 35 个文件逐字节不变（v2 语料只读）；
5. C 冻结 12 与基线清单逐项相等；
6. 10 份只读输入件（计划/判据/L1/v2 source-map/v2 manifest/p2_holdout_scenarios.py/
   retrieval/index.py/rag/chunking.py/retrieval/tokenize.py）SHA256 不变；
7. 交付件盘点：v3 语料 13 个文件 + 源映射。

零真实调用；只读 git 与文件。
用法：``.venv\\Scripts\\python.exe 07-preservation.py``
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
HERE = Path(__file__).resolve().parent
BEFORE = HERE / "00-snapshot-before.json"
OUT = HERE / "07-preservation.json"
V3_ROOT = ROOT / "fixtures/acceptance-h2v3"
SOURCE_MAP = ROOT / "docs/evaluation/p2-holdout-v3.source-map.json"

ALLOWED_NEW_PREFIXES = (
    "fixtures/acceptance-h2v3/",
    "docs/evaluation/p2-holdout-v3.source-map.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-corpus/",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True)
    return result.stdout.decode("utf-8", "replace")


def main() -> int:
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    status = git("status", "--porcelain").splitlines()
    tracked_modified = sorted(line[3:] for line in status if line[:2].strip() not in ("??", ""))
    untracked = sorted(line[3:] for line in status if line[:2] == "??")
    head = git("rev-parse", "HEAD").strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    staged = [line for line in git("diff", "--cached", "--name-only").splitlines() if line.strip()]

    new_untracked = [path for path in untracked if path not in set(before["untracked"])]
    lost_untracked = [path for path in before["untracked"] if path not in set(untracked)]
    outside_scope = [path for path in new_untracked if not any(path.startswith(prefix) or path == prefix.rstrip("/") for prefix in ALLOWED_NEW_PREFIXES)]

    v2_roots = sorted((ROOT / "fixtures/acceptance").rglob("*"))
    v2_files = {str(path.relative_to(ROOT / "fixtures/acceptance")).replace("\\", "/"): sha256_file(path) for path in v2_roots if path.is_file()}
    v2_before = {rel: entry["sha256"] for rel, entry in before["v2_corpus"].items()}
    v2_changed = sorted(rel for rel in set(v2_files) | set(v2_before) if v2_files.get(rel) != v2_before.get(rel))

    baseline = json.loads((ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json").read_text(encoding="utf-8"))["c_freeze_12"]
    c_freeze = {rel: {"expected": baseline[rel], "actual": sha256_file(ROOT / rel)} for rel in sorted(baseline)}
    c_freeze_mismatch = sorted(rel for rel, item in c_freeze.items() if item["expected"] != item["actual"])

    readonly = {rel: sha256_file(ROOT / rel) for rel in before["readonly_inputs"]}
    readonly_changed = sorted(rel for rel in readonly if readonly[rel] != before["readonly_inputs"][rel]["sha256"])

    v3_files = {
        str(path.relative_to(V3_ROOT)).replace("\\", "/"): {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(V3_ROOT.rglob("*"))
        if path.is_file()
    }
    checks = {
        "branch_unchanged": branch == before["branch"],
        "head_unchanged_no_commits": head == before["head"],
        "staged_empty": not staged,
        "tracked_modified_paths_unchanged": tracked_modified == before["tracked_modified"],
        "tracked_modified_count_15": len(tracked_modified) == 15,
        "prior_untracked_preserved": not lost_untracked,
        "new_untracked_inside_declared_scope": not outside_scope,
        "v2_corpus_byte_identical": not v2_changed,
        "v2_corpus_file_count_unchanged": len(v2_files) == before["v2_corpus_file_count"],
        "c_freeze_12_unchanged": not c_freeze_mismatch,
        "readonly_inputs_unchanged": not readonly_changed,
        "v3_corpus_13_files": len(v3_files) == 13,
        "source_map_present": SOURCE_MAP.is_file(),
    }
    payload = {
        "schema_version": "p2h2v3-preservation/v0.1",
        "phase": "preservation",
        "before_ref": str(BEFORE.relative_to(ROOT)).replace("\\", "/"),
        "git": {
            "branch": branch,
            "head": head,
            "staged": staged,
            "tracked_modified": tracked_modified,
            "tracked_modified_count": len(tracked_modified),
            "untracked_count": len(untracked),
            "new_untracked": new_untracked,
            "lost_untracked": lost_untracked,
            "new_untracked_outside_scope": outside_scope,
        },
        "v2_corpus": {"files": len(v2_files), "changed": v2_changed},
        "c_freeze_12": {"mismatch": c_freeze_mismatch, "checked": len(c_freeze)},
        "readonly_inputs": {"changed": readonly_changed, "checked": len(readonly)},
        "v3_corpus": v3_files,
        "source_map": {"path": "docs/evaluation/p2-holdout-v3.source-map.json", "sha256": sha256_file(SOURCE_MAP), "bytes": SOURCE_MAP.stat().st_size} if SOURCE_MAP.is_file() else None,
        "checks": checks,
        "result": "PRESERVED" if all(checks.values()) else "VIOLATION",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"checks": checks, "result": payload["result"],
                      "new_untracked_count": len(new_untracked), "untracked_count": len(untracked)}, ensure_ascii=False, indent=1))
    return 0 if payload["result"] == "PRESERVED" else 1


if __name__ == "__main__":
    sys.exit(main())
