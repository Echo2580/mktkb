"""C1-P5 preservation check: prove no accepted artifact changed and the old run is intact."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
P5 = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p5"
P4_PROTECTED = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/evidence/protected-after.json"
R2_AGG = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r2.json"
OLD = Path(r"D:\mktkb-p2-t207-h2-20261114")
CONTRACT_DIR = Path(r"D:\mktkb-q1a2-scope-contract")

R2_COMPONENTS = {
    "contract_ciphertext_sha256": "467dbf7706df26f2069a79e2b344b53c0e10c03ff830ed62efff9b5dfd16f461",
    "contract_schema_sha256": "cb1257fac56a68e5eef791c23cffba9d4e915e5e9a840abce7bde5b96e0e4690",
    "q1a1_module_sha256": "d8260256b4c3572f206a39f39dc8fe2847fa4946dc9b7bd05e93c5fd7841f3e9",
    "q1a1b_module_sha256": "57495943c763977e62fa7acded407e99ba360336fc5ee8c822f5e084f200f08e",
    "q1a1_contract_sha256": "e0487f256524558ae12b00e6a9d961a7360e92f1437ab4d7d0c55702f375588d",
    "q1a1b_contract_sha256": "747e3656bfbaf0bb4f0e40444d96d20d2b30806d80d061fbca13b962a46c8db5",
}
Q1A1_MODULE = ROOT / "backend/src/mktkb/evaluation/p2_evidence_rescore.py"
Q1A1B_MODULE = ROOT / "backend/src/mktkb/evaluation/p2_evidence_rescore_axes.py"
Q1A1_CONTRACT = ROOT / "docs/evaluation/p2-evidence-rescore-v0_1.md"
Q1A1B_CONTRACT = ROOT / "docs/evaluation/p2-evidence-rescore-v0_2.md"

#: P3/P4 deliverables that this package only imports / reads. Session start
#: (2026-11-14T22:10:45+08:00) is the reference; a newer mtime would prove a write.
SESSION_START = "2026-11-14T22:10:45+08:00"
READONLY_FILES = (
    "backend/src/mktkb/evaluation/p2_evidence_axes_adapter_v2.py",
    "backend/src/mktkb/evaluation/p2_evidence_snapshot_v03.py",
    "backend/tests/evaluation/test_p2_evidence_axes_adapter_v2.py",
    "docs/evaluation/p2-hard-evidence-capture-v0_3.md",
    "docs/evaluation/q1a-scope-targets-contract-v2.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p4/dev-report.md",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    ).stdout


def main() -> int:
    p4 = json.loads(P4_PROTECTED.read_text(encoding="utf-8"))
    freeze = {path: sha(ROOT / path) for path in p4["c_freeze_12"]}
    freeze_ok = {path: freeze[path] == expected for path, expected in p4["c_freeze_12"].items()}
    tracked = {path: sha(ROOT / path) for path in p4["tracked_modified"]}
    tracked_ok = {path: tracked[path] == expected for path, expected in p4["tracked_modified"].items()}

    head = git("rev-parse", "HEAD").strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    staged = [line for line in git("diff", "--cached", "--name-only").splitlines() if line.strip()]
    untracked_all = [
        line[3:] for line in git("status", "--porcelain=v1", "--untracked-files=all").splitlines()
        if line.startswith("?? ")
    ]
    p5_new = sorted(path for path in untracked_all if "Q1A-EVAL-REPAIR/c1-1/p5/" in path)
    other_new = sorted(path for path in untracked_all if "Q1A-EVAL-REPAIR/c1-1/p5/" not in path)

    r2 = json.loads(R2_AGG.read_text(encoding="utf-8"))
    run_binding = OLD / "plans2/run-binding.json"
    binding_payload = json.loads(run_binding.read_text(encoding="utf-8"))
    run_checks = {}
    for run, expected in r2["identity"]["per_run"].items():
        card = OLD / "runs" / run / "card.json"
        seals = sorted((OLD / "runs" / run / "seal").glob("*/seal-manifest.json"))
        seal = json.loads(seals[0].read_text(encoding="utf-8"))
        evidence_dir = OLD / "runs" / run / "evidence"
        sealed_files_ok = all(
            sha(evidence_dir / item["path"]) == item["sha256"]
            for item in seal["evidence_root"]["files"]
        )
        run_checks[run] = {
            "card_sha256": sha(card),
            "card_matches_r2": sha(card) == expected["card_sha256"],
            "seal_tree_sha256": seal["evidence_root"]["tree_sha256"],
            "seal_tree_matches_r2": seal["evidence_root"]["tree_sha256"] == expected["evidence_tree_sha256"],
            "evidence_files_match_seal": sealed_files_ok,
            "evidence_file_count": len(seal["evidence_root"]["files"]),
        }

    q1a1_module = sha(Q1A1_MODULE) if Q1A1_MODULE.exists() else None
    q1a1b_module = sha(Q1A1B_MODULE) if Q1A1B_MODULE.exists() else None
    q1a1_contract = sha(Q1A1_CONTRACT) if Q1A1_CONTRACT.exists() else None
    q1a1b_contract = sha(Q1A1B_CONTRACT) if Q1A1B_CONTRACT.exists() else None
    from datetime import datetime

    session_start = datetime.fromisoformat(SESSION_START)
    readonly = {}
    for rel in READONLY_FILES:
        path = ROOT / rel
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=session_start.tzinfo)
        readonly[rel] = {
            "sha256": sha(path),
            "mtime_before_session": mtime < session_start,
        }

    result = {
        "probe": "06-preservation-check",
        "head": head,
        "branch": branch,
        "head_expected": "97b0066726e5b8d6f94cbc0b63a890084550c106",
        "head_ok": head == "97b0066726e5b8d6f94cbc0b63a890084550c106",
        "branch_ok": branch == "codex/p2-e2e",
        "staged_count": len(staged),
        "staged_empty": not staged,
        "c_freeze_12_all_match": all(freeze_ok.values()),
        "c_freeze_12": freeze_ok,
        "tracked_modified_all_match": all(tracked_ok.values()),
        "tracked_modified": tracked_ok,
        "contract_v1_ciphertext_sha256": sha(CONTRACT_DIR / "scope-targets-contract-v1.fernet"),
        "contract_v1_ciphertext_matches_r2": sha(CONTRACT_DIR / "scope-targets-contract-v1.fernet") == R2_COMPONENTS["contract_ciphertext_sha256"],
        "contract_v1_schema_sha256": sha(ROOT / "docs/evaluation/q1a-scope-targets-contract-v1.md"),
        "contract_v1_schema_matches_r2": sha(ROOT / "docs/evaluation/q1a-scope-targets-contract-v1.md") == R2_COMPONENTS["contract_schema_sha256"],
        "contract_v2_ciphertext_sha256": sha(CONTRACT_DIR / "scope-targets-contract-v2.fernet"),
        "contract_v2_ciphertext_bytes": (CONTRACT_DIR / "scope-targets-contract-v2.fernet").stat().st_size,
        "contract_v2_schema_sha256": sha(ROOT / "docs/evaluation/q1a-scope-targets-contract-v2.md"),
        "run_binding_file_sha256": sha(run_binding),
        "run_binding_file_matches_r2": sha(run_binding) == r2["identity"]["components"]["old_run_binding_file_sha256"],
        "run_binding_payload_sha256": binding_payload.get("binding_sha256"),
        "run_binding_payload_matches_r2": binding_payload.get("binding_sha256") == r2["identity"]["components"]["old_run_binding_payload_sha256"],
        "old_run_checks": run_checks,
        "q1a1_module_sha256": q1a1_module,
        "q1a1_module_matches_r2": q1a1_module == R2_COMPONENTS["q1a1_module_sha256"],
        "q1a1b_module_sha256": q1a1b_module,
        "q1a1b_module_matches_r2": q1a1b_module == R2_COMPONENTS["q1a1b_module_sha256"],
        "q1a1_contract_sha256": q1a1_contract,
        "q1a1_contract_matches_r2": q1a1_contract == R2_COMPONENTS["q1a1_contract_sha256"],
        "q1a1b_contract_sha256": q1a1b_contract,
        "q1a1b_contract_matches_r2": q1a1b_contract == R2_COMPONENTS["q1a1b_contract_sha256"],
        "readonly_files": readonly,
        "readonly_all_untouched": all(item["mtime_before_session"] for item in readonly.values()),
        "p5_new_file_count": len(p5_new),
        "p5_new_files": p5_new,
        "untracked_outside_p5_count": len(other_new),
    }
    result["preserved"] = all(
        [
            result["head_ok"],
            result["branch_ok"],
            result["staged_empty"],
            result["c_freeze_12_all_match"],
            result["tracked_modified_all_match"],
            result["contract_v1_ciphertext_matches_r2"],
            result["contract_v1_schema_matches_r2"],
            result["run_binding_file_matches_r2"],
            result["run_binding_payload_matches_r2"],
            result["q1a1_module_matches_r2"],
            result["q1a1b_module_matches_r2"],
            result["q1a1_contract_matches_r2"],
            result["q1a1b_contract_matches_r2"],
            result["readonly_all_untouched"],
            all(item["card_matches_r2"] and item["seal_tree_matches_r2"] and item["evidence_files_match_seal"] for item in run_checks.values()),
        ]
    )
    (P5 / "evidence" / "06-preservation-check.out.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(
        {k: result[k] for k in (
            "head_ok", "branch_ok", "staged_empty", "c_freeze_12_all_match",
            "tracked_modified_all_match", "contract_v1_ciphertext_matches_r2",
            "contract_v1_schema_matches_r2", "run_binding_file_matches_r2",
            "run_binding_payload_matches_r2", "q1a1_module_matches_r2",
            "q1a1b_module_matches_r2", "q1a1_contract_matches_r2",
            "q1a1b_contract_matches_r2", "p5_new_file_count",
            "untracked_outside_p5_count", "preserved")},
        ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["preserved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
