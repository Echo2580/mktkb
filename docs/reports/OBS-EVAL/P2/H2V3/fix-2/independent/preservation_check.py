"""独立保全核对：C 冻结 12 / 语料 / 评测模块 / git 状态，全部现算。

上一轮基线取 safety-fix 的独立产物 preservation-after.json（既有路径→SHA 映射），
本包**重新计算**当前 SHA 并逐项比对，不引用开发方 fix-2 的 snapshot 结论。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
BASE = REPO / "docs/reports/OBS-EVAL/P2/H2V3/safety-fix/evidence/preservation-after.json"
OUT = HERE / "preservation-check.json"
ROUND_START_MTIME = 1794726180  # 2026-11-15 15:43 本地（本轮开始，用于"评测模块未被本包改动"）


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entries(block: object) -> dict[str, str]:
    """兼容两种记录形态：{path: sha} 或 {path: {sha256: ...}} / {"files": {...}}。"""
    if isinstance(block, dict) and "files" in block and isinstance(block["files"], dict):
        block = block["files"]
    out: dict[str, str] = {}
    for rel, row in (block or {}).items():
        if isinstance(row, dict):
            if row.get("exists") is False:
                continue
            out[rel] = str(row.get("sha256"))
        else:
            out[rel] = str(row)
    return out


def compare(block: object, label: str) -> dict[str, object]:
    mapping = _entries(block)
    rows = {}
    changed, missing = [], []
    for rel, expected in sorted(mapping.items()):
        target = REPO / rel
        if not target.exists():
            missing.append(rel)
            continue
        now = sha(target)
        rows[rel] = {"expected": expected, "now": now, "same": now == expected}
        if now != expected:
            changed.append(rel)
    return {"label": label, "count": len(mapping), "changed": changed, "missing": missing,
            "all_same": not changed and not missing, "rows": rows}


def git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return (done.stdout or "").strip()


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    c_freeze = compare(base["c_freeze_12"], "c_freeze_12")
    corpus = compare(base["fixtures_acceptance_h2v3"], "fixtures_acceptance_h2v3")

    evaluation = sorted((REPO / "backend/src/mktkb/evaluation").glob("*.py"))
    eval_rows = {
        str(p.relative_to(REPO)): {"sha256": sha(p), "mtime": p.stat().st_mtime}
        for p in evaluation
    }
    eval_touched = [rel for rel, row in eval_rows.items() if row["mtime"] >= ROUND_START_MTIME]

    staged = [line for line in git("diff", "--cached", "--name-only").splitlines() if line]
    tracked_modified = [line for line in git("diff", "--name-only").splitlines() if line]
    untracked = [line for line in git("ls-files", "--others", "--exclude-standard").splitlines() if line]

    payload = {
        "schema_version": "v3-fix2-independent-preservation/v0.1",
        "baseline": str(BASE.relative_to(REPO)),
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "c_freeze_12": c_freeze,
        "fixtures_acceptance_h2v3": corpus,
        "evaluation_module": {
            "files": eval_rows,
            "count": len(eval_rows),
            "touched_since_round_start": eval_touched,
            "round_start_mtime_used": ROUND_START_MTIME,
            "unchanged_in_this_round": not eval_touched,
        },
        "git_state": {
            "staged_paths": staged,
            "staged_count": len(staged),
            "tracked_modified_count": len(tracked_modified),
            "untracked_count": len(untracked),
            "untracked_in_fix2_dir": [p for p in untracked if "H2V3/fix-2/" in p.replace("\\", "/")][:5],
        },
        "conclusion": {
            "c_freeze_12_all_same": c_freeze["all_same"],
            "corpus_all_same": corpus["all_same"],
            "evaluation_module_unchanged_in_round": not eval_touched,
            "staged_empty": not staged,
            "head_matches_expected": git("rev-parse", "HEAD").startswith("97b0066726e5"),
        },
    }
    payload["conclusion"]["all_ok"] = all(payload["conclusion"].values())
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({"conclusion": payload["conclusion"],
                      "c_freeze_changed": c_freeze["changed"],
                      "corpus_changed": corpus["changed"],
                      "eval_touched": eval_touched,
                      "staged": staged,
                      "tracked_modified_count": len(tracked_modified)}, ensure_ascii=False, indent=1))
    return 0 if payload["conclusion"]["all_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
