"""独立验收：本轮前后的保全快照与对照（不复用开发脚本）。

基线：上一轮独立验收 `fix-1/independent/00-snapshot-end.json`（fix-1 收尾时点）。
本轮只做：
- 重算 C 冻结 12、外部 v2/v3 密文与语料、fixtures/acceptance-h2v3、保护仓文件；
- 重算 22 条 tracked modified 的哈希，指出哪几条变化（应只有 fix-1/R1 的 2 条）；
- 记录 HEAD / 分支 / commit 数 / 暂存 / 未跟踪条目数；只哈希，不读取受保护内容。

输出：independent/preservation-after.json、independent/preservation-compare.json。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
BASE = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fix-1/independent/00-snapshot-end.json"
EXTERNAL_ROOT = Path(r"D:\mktkb-p2-holdout")
OUT_AFTER = HERE / "preservation-after.json"
OUT_COMPARE = HERE / "preservation-compare.json"


def sha(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"exists": False, "bytes": 0, "sha256": None}
    data = path.read_bytes()
    return {"exists": True, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def status_rows() -> list[dict[str, str]]:
    rows = []
    for line in git("status", "--porcelain=v1", "--untracked-files=all").splitlines():
        if not line:
            continue
        code, path = line[:2], line[3:]
        rows.append({"code": code, "path": path})
    return rows


def group_hashes(root: Path, keys: list[str]) -> dict[str, Any]:
    return {key: sha(root / key) for key in keys}


def compare_group(
    baseline: dict[str, Any], now: dict[str, Any]
) -> dict[str, Any]:
    changed = {
        key: {"before": baseline[key], "after": now[key]}
        for key in baseline
        if key in now and baseline[key] != now[key]
    }
    missing = [key for key in baseline if key not in now]
    added = [key for key in now if key not in baseline]
    return {"changed": changed, "missing": missing, "added": added, "count": len(now)}


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))

    # --- 受保护仓内组
    c_freeze = group_hashes(REPO, list(base["c_freeze_12"].keys()))
    protected = group_hashes(REPO, list(base["protected_repo"].keys()))
    fixtures_keys = list(base["fixtures_acceptance_h2v3"]["files"].keys())
    fixtures = group_hashes(REPO, fixtures_keys)

    # --- 外部密文/语料（v2/v3，排除 keys/）
    external = group_hashes(EXTERNAL_ROOT, list(base["external_ciphertext_and_corpus"].keys()))
    external_extra: list[str] = []
    for version in ("v2", "v3"):
        directory = EXTERNAL_ROOT / version
        if directory.is_dir():
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    rel_parts = path.relative_to(directory).parts
                    if "keys" in rel_parts:
                        continue
                    rel = f"{version}/{path.relative_to(directory).as_posix()}"
                    if rel not in external:
                        external_extra.append(rel)

    # --- v3 冻结 32：逐条按记录值重算
    v3_items = []
    for item in base["v3_freeze_32"]["items"]:
        path = Path(item["path"])
        now = sha(path)
        v3_items.append(
            {
                "id": item["id"],
                "group": item["group"],
                "path": item["path"],
                "recorded": item["recorded"],
                "recorded_bytes": item["recorded_bytes"],
                "now": now,
                "match": now.get("sha256") == item["recorded"],
            }
        )
    v3_matched = sum(1 for item in v3_items if item["match"])
    v3_mismatched = [item["id"] for item in v3_items if not item["match"]]

    # --- Git 状态
    rows = status_rows()
    tracked = [
        {
            "code": row["code"],
            "path": row["path"],
            "exists": (REPO / row["path"]).is_file(),
            "bytes": (REPO / row["path"]).stat().st_size if (REPO / row["path"]).is_file() else 0,
            "sha256": sha(REPO / row["path"])["sha256"],
        }
        for row in rows
        if not row["code"].strip().startswith("?")
    ]
    staged_paths = [line for line in git("diff", "--cached", "--name-only").splitlines() if line]
    untracked = [row["path"] for row in rows if row["code"] == "??"]

    after = {
        "schema_version": "v3-fix1r1-independent-preservation/v0.1",
        "label": "fix-1r1-independent-after",
        "head": git("rev-parse", "HEAD").strip(),
        "branch": git("branch", "--show-current").strip(),
        "commits": int(git("rev-list", "--count", "HEAD").strip()),
        "staged_paths": staged_paths,
        "tracked_modified": tracked,
        "tracked_modified_count": len(tracked),
        "tracked_modified_paths": [row["path"] for row in tracked],
        "untracked_entries": len(untracked),
        "c_freeze_12": c_freeze,
        "external_ciphertext_and_corpus": external,
        "external_extra_files": external_extra,
        "fixtures_acceptance_h2v3": {"count": len(fixtures), "files": fixtures},
        "protected_repo": protected,
        "v3_freeze_32": {
            "count": len(v3_items),
            "items": v3_items,
            "matched": v3_matched,
            "mismatched": v3_mismatched,
        },
    }

    # --- 对照
    base_tracked = {row["path"]: row["sha256"] for row in base["tracked_modified"]}
    now_tracked = {row["path"]: row["sha256"] for row in tracked}
    tracked_changed = {
        path: {"before": base_tracked.get(path), "after": now_tracked.get(path)}
        for path in sorted(set(base_tracked) | set(now_tracked))
        if base_tracked.get(path) != now_tracked.get(path)
    }
    compare = {
        "schema_version": "v3-fix1r1-independent-preservation-compare/v0.1",
        "baseline": "docs/reports/OBS-EVAL/P2/H2V3/fix-1/independent/00-snapshot-end.json",
        "now": "docs/reports/OBS-EVAL/P2/H2V3/fix-1r1/independent/preservation-after.json",
        "head": {
            "before": base["head"],
            "now": after["head"],
            "identical": base["head"] == after["head"],
        },
        "branch": {
            "before": base["branch"],
            "now": after["branch"],
            "identical": base["branch"] == after["branch"],
        },
        "commits": {
            "before": base["commits"],
            "now": after["commits"],
            "identical": base["commits"] == after["commits"],
        },
        "staged_paths": {
            "before": base["staged_paths"],
            "now": staged_paths,
            "empty": not staged_paths,
        },
        "tracked_modified_count": {
            "before": base["tracked_modified_count"],
            "now": after["tracked_modified_count"],
            "identical": base["tracked_modified_count"] == after["tracked_modified_count"],
        },
        "tracked_modified_changed": tracked_changed,
        "c_freeze_12": compare_group(base["c_freeze_12"], c_freeze),
        "external_ciphertext_and_corpus": compare_group(
            base["external_ciphertext_and_corpus"], external
        ),
        "external_extra_files": external_extra,
        "fixtures_acceptance_h2v3": compare_group(
            base["fixtures_acceptance_h2v3"]["files"], fixtures
        ),
        "protected_repo": compare_group(base["protected_repo"], protected),
        "v3_freeze_32": {
            "before_matched": base["v3_freeze_32"]["matched"],
            "before_mismatched": base["v3_freeze_32"]["mismatched"],
            "now_matched": v3_matched,
            "now_mismatched": v3_mismatched,
            "match_status_changed": (
                base["v3_freeze_32"]["mismatched"] != v3_mismatched
            ),
        },
        "untracked_entries": {
            "before": base["untracked_entries"],
            "now": after["untracked_entries"],
        },
    }

    OUT_AFTER.write_text(
        json.dumps(after, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    OUT_COMPARE.write_text(
        json.dumps(compare, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "head": compare["head"],
                "branch": compare["branch"],
                "commits": compare["commits"],
                "staged": staged_paths,
                "tracked_modified_count": compare["tracked_modified_count"],
                "tracked_modified_changed": sorted(tracked_changed),
                "c_freeze_12_changed": list(compare["c_freeze_12"]["changed"]),
                "external_changed": list(compare["external_ciphertext_and_corpus"]["changed"]),
                "external_extra": external_extra,
                "fixtures_changed": list(compare["fixtures_acceptance_h2v3"]["changed"]),
                "protected_changed": list(compare["protected_repo"]["changed"]),
                "v3_freeze_32": compare["v3_freeze_32"],
                "untracked_entries": compare["untracked_entries"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
