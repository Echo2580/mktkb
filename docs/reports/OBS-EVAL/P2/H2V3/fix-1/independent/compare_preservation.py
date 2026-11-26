"""前后保全快照比较（只读）。"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
start = json.loads((BASE / "00-snapshot-start.json").read_text(encoding="utf-8"))
end = json.loads((BASE / "00-snapshot-end.json").read_text(encoding="utf-8"))
OUT = BASE / "preservation-compare.json"

sm = {row["path"]: row for row in start["tracked_modified"]}
em = {row["path"]: row for row in end["tracked_modified"]}
removed = sorted(set(sm) - set(em))
added = sorted(set(em) - set(sm))
changed = sorted(p for p in set(sm) & set(em) if sm[p]["sha256"] != em[p]["sha256"])

freeze_s = {r["id"]: r for r in start["v3_freeze_32"]["items"]}
freeze_e = {r["id"]: r for r in end["v3_freeze_32"]["items"]}
freeze_changed = sorted(k for k in freeze_s if freeze_s[k]["now"] != freeze_e[k]["now"])

c_changed = sorted(
    p for p in start["c_freeze_12"] if start["c_freeze_12"][p] != end["c_freeze_12"][p]
)
ext_changed = sorted(
    p for p in start["external_ciphertext_and_corpus"]
    if start["external_ciphertext_and_corpus"][p] != end["external_ciphertext_and_corpus"][p]
)
fx_changed = sorted(
    p for p in start["fixtures_acceptance_h2v3"]["files"]
    if start["fixtures_acceptance_h2v3"]["files"][p] != end["fixtures_acceptance_h2v3"]["files"][p]
)
prot_changed = {}
for p in start["protected_repo"]:
    if start["protected_repo"][p] != end["protected_repo"][p]:
        prot_changed[p] = {"before": start["protected_repo"][p], "after": end["protected_repo"][p]}

expected_prot = {
    "docs/evidence/LOCAL-R1-20261101/budget/budget.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.v3-r1.pending.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.v3-r2.pending.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.v3-r3.pending.json",
}

payload = {
    "schema_version": "v3-fix1-independent-preservation-compare/v0.1",
    "git": {
        "head_same": start["head"] == end["head"],
        "branch_same": start["branch"] == end["branch"],
        "commits_same": start["commits"] == end["commits"],
        "commits": end["commits"],
        "staged_before": len(start["staged_paths"]),
        "staged_after": len(end["staged_paths"]),
        "tracked_modified_before": start["tracked_modified_count"],
        "tracked_modified_after": end["tracked_modified_count"],
        "tracked_removed": removed,
        "tracked_added": added,
        "tracked_common_sha_changed": changed,
        "untracked_before": start["untracked_entries"],
        "untracked_after": end["untracked_entries"],
    },
    "c_freeze_12_changed": c_changed,
    "c_freeze_12_all_equal": not c_changed,
    "v3_freeze_32": {
        "matched_before": start["v3_freeze_32"]["matched"],
        "matched_after": end["v3_freeze_32"]["matched"],
        "changed": freeze_changed,
        "mismatched_ids": start["v3_freeze_32"]["mismatched"],
    },
    "external_ciphertext_corpus_changed": ext_changed,
    "fixtures_acceptance_h2v3_changed": fx_changed,
    "protected_repo_changed": prot_changed,
    "protected_changes_expected": sorted(prot_changed) == sorted(expected_prot),
    "ledger_unchanged": (
        start["protected_repo"]["docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"]
        == end["protected_repo"]["docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"]
    ),
    "budget_after": end["protected_repo"]["docs/evidence/LOCAL-R1-20261101/budget/budget.json"]["sha256"],
    "scenarios_py_unchanged": (
        start["protected_repo"]["backend/src/mktkb/evaluation/p2_holdout_scenarios.py"]
        == end["protected_repo"]["backend/src/mktkb/evaluation/p2_holdout_scenarios.py"]
    ),
    "scenarios_v3_py_unchanged": (
        start["protected_repo"]["backend/src/mktkb/evaluation/p2_holdout_scenarios_v3.py"]
        == end["protected_repo"]["backend/src/mktkb/evaluation/p2_holdout_scenarios_v3.py"]
    ),
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
               encoding="utf-8")
print(json.dumps({k: payload[k] for k in (
    "git", "c_freeze_12_all_equal", "external_ciphertext_corpus_changed",
    "fixtures_acceptance_h2v3_changed", "protected_changes_expected",
    "ledger_unchanged", "budget_after", "scenarios_py_unchanged",
    "scenarios_v3_py_unchanged")}, ensure_ascii=False, indent=1))
