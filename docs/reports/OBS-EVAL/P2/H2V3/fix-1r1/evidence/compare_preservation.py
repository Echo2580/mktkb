"""v3-fix-1/R1 保全对照：本轮结束快照 vs 独立验收结束快照（只读比较，不写产品文件）。

用法：
    python compare_preservation.py <baseline-snapshot.json> <now-snapshot.json> <out.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _diff_map(before: dict, after: dict) -> dict[str, dict]:
    changed: dict[str, dict] = {}
    for key in sorted(set(before) | set(after)):
        left = before.get(key)
        right = after.get(key)
        if left != right:
            changed[key] = {"before": left, "after": right}
    return changed


def main() -> int:
    baseline_path, now_path, out_path = sys.argv[1:4]
    before = _load(baseline_path)
    now = _load(now_path)

    before_tracked = {row["path"]: row.get("sha256") for row in before["tracked_modified"]}
    now_tracked = {row["path"]: row.get("sha256") for row in now["tracked_modified"]}
    tracked_diff = _diff_map(before_tracked, now_tracked)

    freeze_before = {row["id"]: row.get("match") for row in before["v3_freeze_32"]["items"]}
    freeze_now = {row["id"]: row.get("match") for row in now["v3_freeze_32"]["items"]}

    payload = {
        "schema_version": "v3-fix1r1-preservation/v0.1",
        "baseline": baseline_path,
        "now": now_path,
        "head": {"before": before.get("head"), "now": now.get("head"),
                 "identical": before.get("head") == now.get("head")},
        "branch": {"before": before.get("branch"), "now": now.get("branch"),
                   "identical": before.get("branch") == now.get("branch")},
        "staged_paths": {"before": before.get("staged_paths"), "now": now.get("staged_paths"),
                         "empty": not now.get("staged_paths")},
        "tracked_modified_count": {"before": before.get("tracked_modified_count"),
                                   "now": now.get("tracked_modified_count")},
        "tracked_modified_changed": tracked_diff,
        "c_freeze_12_changed": _diff_map(before["c_freeze_12"], now["c_freeze_12"]),
        "protected_repo_changed": _diff_map(before["protected_repo"], now["protected_repo"]),
        "external_ciphertext_and_corpus_changed": _diff_map(
            before["external_ciphertext_and_corpus"], now["external_ciphertext_and_corpus"]
        ),
        "fixtures_acceptance_h2v3_changed": _diff_map(
            before["fixtures_acceptance_h2v3"]["files"], now["fixtures_acceptance_h2v3"]["files"]
        ),
        "v3_freeze_32": {
            "before_matched": before["v3_freeze_32"]["matched"],
            "now_matched": now["v3_freeze_32"]["matched"],
            "before_mismatched": before["v3_freeze_32"]["mismatched"],
            "now_mismatched": now["v3_freeze_32"]["mismatched"],
            "match_status_changed": _diff_map(freeze_before, freeze_now),
        },
        "untracked_entries": {"before": before.get("untracked_entries"),
                              "now": now.get("untracked_entries")},
    }
    Path(out_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "head_identical": payload["head"]["identical"],
        "branch_identical": payload["branch"]["identical"],
        "staged_empty": payload["staged_paths"]["empty"],
        "tracked_modified_changed": sorted(tracked_diff),
        "c_freeze_12_changed": sorted(payload["c_freeze_12_changed"]),
        "protected_repo_changed": sorted(payload["protected_repo_changed"]),
        "external_changed": sorted(payload["external_ciphertext_and_corpus_changed"]),
        "fixtures_changed": sorted(payload["fixtures_acceptance_h2v3_changed"]),
        "freeze32_before": payload["v3_freeze_32"]["before_matched"],
        "freeze32_now": payload["v3_freeze_32"]["now_matched"],
        "freeze32_mismatched_now": payload["v3_freeze_32"]["now_mismatched"],
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
