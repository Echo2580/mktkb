from pathlib import Path
import difflib
import hashlib
import json

root = Path(__file__).resolve().parents[6]
out = Path(__file__).resolve().parent
changed = [
    "backend/src/mktkb/rag/query.py",
    "backend/src/mktkb/rag/retrieval.py",
    "backend/src/mktkb/rag/answer.py",
    "backend/src/mktkb/conversations/intent.py",
    "backend/src/mktkb/conversations/service.py",
    "tools/p2_h2_controlled_execute.py",
]
added = [
    "backend/tests/rag/test_t207_title_prefix_synthetic.py",
    "backend/tests/rag/test_t207_multi_store_synthetic.py",
    "backend/tests/rag/test_t207_security_precedence_synthetic.py",
    "backend/tests/rag/test_t207_conflict_synthetic.py",
    "backend/tests/rag/test_t207_candidate_scope_synthetic.py",
    "backend/tests/rag/test_t207_v8_enumeration_synthetic.py",
    "backend/tests/unit/test_t207_record_duplicate_synthetic.py",
    "backend/tests/unit/test_t207_context_sources_synthetic.py",
    "backend/tests/unit/test_t207_v8_followup_synthetic.py",
    "backend/tests/unit/test_t207_v8_safety_contract_synthetic.py",
    "backend/tests/evaluation/test_t207_binding_retention_synthetic.py",
]
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

diff = []
for name in changed + added:
    before = out / "baseline" / name
    old = before.read_text(encoding="utf-8").splitlines(keepends=True) if before.exists() else []
    new = (root / name).read_text(encoding="utf-8").splitlines(keepends=True)
    diff.extend(difflib.unified_diff(old, new, fromfile="a/" + name if before.exists() else "/dev/null",
                                     tofile="b/" + name))
(out / "round-increment.diff").write_text("".join(diff), encoding="utf-8")
before = json.loads((out / "baseline-protection.json").read_text(encoding="utf-8-sig"))
protection = [{"path": x["Path"], "before": x["Hash"].lower(), "after": sha(Path(x["Path"]))}
              for x in before]
for row in protection:
    row["same"] = row["before"] == row["after"]
(out / "final-protection.json").write_text(json.dumps(protection, ensure_ascii=False, indent=2), encoding="utf-8")
snapshot = json.loads((root / "docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence/preservation-after.json").read_text(encoding="utf-8"))
historical = []
for name, item in snapshot["protected_repo"].items():
    if name.endswith("live-ledger.jsonl"):
        continue  # the ledger changed in a later authorized real run; today's own baseline covers it
    current = sha(root / name)
    historical.append({"path": name, "snapshot": item["sha256"], "after": current,
                       "same": current == item["sha256"]})
(out / "historical-protection-compare.json").write_text(json.dumps(historical, ensure_ascii=False, indent=2), encoding="utf-8")
manifest = {name: sha(root / name) for name in changed + added}
for name in ("round-increment.diff", "baseline-tracked.diff", "baseline-protection.json", "final-protection.json",
             "historical-protection-compare.json", "final-binding-v2.json", "final-product.json", "final-record.json",
             "socketpair-probe.py", "socketpair-probe-receipt-v2.json", "v6-final-targeted-v2.json", "v6-final-record.json",
             "v8-final-product-v2.json", "v8-final-record-v2.json",
             "DEV-progress.md", "FINAL-REVIEW-PACK.md", "CONTROLLED-DIAG-PROPOSAL.md",
             "HTTP-RECHECK.md", "http_recheck_guard.py", "http-escalated-single-netguard.json",
             "http-escalated-single-trust.json", "http-escalated-targeted-netguard.json",
             "http-escalated-targeted-trust.json"):
    manifest[str((out / name).relative_to(root)).replace("\\", "/")] = sha(out / name)
(out / "delivery-sha256.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"root": str(root), "protection_same": all(x["same"] for x in protection),
                  "historical_protection_same": all(x["same"] for x in historical),
                  "files": len(manifest)}, ensure_ascii=False))
