"""独立验收：前后保全快照（只读）。用法: python preservation_snapshot.py <label> <out.json>"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[7]  # docs/reports/OBS-EVAL/P2/H2V3/fix-1/independent -> repo
LABEL = sys.argv[1]
OUT = Path(sys.argv[2])
EXT = Path(r"D:\mktkb-p2-holdout")

C_FREEZE = [
    "backend/src/mktkb/evaluation/p2_evidence_capture.py",
    "backend/src/mktkb/evaluation/p2_evidence_io.py",
    "backend/src/mktkb/evaluation/product_adapter.py",
    "backend/src/mktkb/evaluation/p2_hard_evidence.py",
    "backend/src/mktkb/evaluation/cli.py",
    "tools/p2_h2_historical_audit.py",
    "docs/evaluation/p2-hard-evidence-capture-v0_2.md",
    "docs/evaluation/p2-hard-evidence-classification-v0_2.md",
    "backend/tests/evaluation/test_p2_capture_contract_v02.py",
    "backend/tests/evaluation/test_p2_capture_contract_v02_e2e.py",
    "backend/tests/evaluation/test_p2_cross_entity_scope_v02.py",
    "backend/tests/evaluation/test_p2_capture_entity_readiness_e2e.py",
]

PROTECTED_REPO = [
    "backend/src/mktkb/evaluation/p2_holdout_scenarios.py",
    "backend/src/mktkb/evaluation/p2_holdout_scenarios_v3.py",
    "docs/evaluation/p2-h2-scenarios-H2v3.json",
    "docs/evaluation/p2-holdout-v3.source-map.json",
    "docs/evaluation/p2-source-lifecycle-v1.json",
    "docs/evaluation/p2-stale-source-criterion-v1_1.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/pre-registration.json",
    "docs/reports/OBS-EVAL/P2/H2V3/PM/p2-ingest-plan-H2-v3.json",
    "docs/evidence/LOCAL-R1-20261101/budget/budget.json",
    "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.v3-r1.pending.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.v3-r2.pending.json",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.v3-r3.pending.json",
]


def sha(p: Path) -> dict:
    if not p.exists():
        return {"exists": False}
    h = hashlib.sha256()
    n = 0
    with p.open("rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            n += len(b)
            h.update(b)
    return {"exists": True, "bytes": n, "sha256": h.hexdigest()}


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=False).stdout


def git_lines(*args: str) -> list[str]:
    raw = git(*args)
    return [x.decode("utf-8", "surrogateescape") for x in raw.split(b"\0") if x]


state = {
    "label": LABEL,
    "head": git("rev-parse", "HEAD").decode().strip(),
    "branch": git("rev-parse", "--abbrev-ref", "HEAD").decode().strip(),
    "commits": int(git("rev-list", "--count", "HEAD").decode().strip()),
    "staged_paths": git_lines("diff", "--cached", "--name-only", "-z"),
    "tracked_modified": [],
    "untracked_entries": 0,
}

status = git_lines("status", "--porcelain=v1", "-z", "-uall")
i = 0
while i < len(status):
    rec = status[i]
    if rec.startswith("??"):
        state["untracked_entries"] += 1
        i += 1
        continue
    code, path = rec[:2], rec[3:]
    if code.strip() == "M" or code.strip() == "A" or code.strip() == "D":
        state["tracked_modified"].append({"code": code, "path": path, **sha(REPO / path)})
    i += 1
state["tracked_modified"].sort(key=lambda r: r["path"])
state["tracked_modified_count"] = len(state["tracked_modified"])
state["tracked_modified_paths"] = [r["path"] for r in state["tracked_modified"]]

state["c_freeze_12"] = {p: sha(REPO / p) for p in C_FREEZE}
state["protected_repo"] = {p: sha(REPO / p) for p in PROTECTED_REPO}

freeze = json.loads((REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-freeze/"
                     "p2-holdout-v3.freeze.json").read_text(encoding="utf-8"))
art = []
for a in freeze["artifacts"]:
    base = EXT if a.get("root") == "external" else REPO
    p = Path(a["path"])
    p = p if p.is_absolute() else base / p
    now = sha(p)
    art.append({"id": a["id"], "group": a["group"], "path": a["path"],
                "recorded": a["sha256"], "recorded_bytes": a["bytes"],
                "now": now, "match": now.get("sha256") == a["sha256"]})
state["v3_freeze_32"] = {
    "count": len(art),
    "matched": sum(1 for r in art if r["match"]),
    "mismatched": [r["id"] for r in art if not r["match"]],
    "items": art,
}

ext = {}
for sub in ("v2", "v3"):
    for p in sorted((EXT / sub).glob("*")):
        if p.is_file():
            ext[f"{sub}/{p.name}"] = sha(p)
state["external_ciphertext_and_corpus"] = ext

# 语料：fixtures/acceptance-h2v3 全树（12 源 + manifest）
fx = {}
for p in sorted((REPO / "fixtures/acceptance-h2v3").rglob("*")):
    if p.is_file():
        fx[p.relative_to(REPO).as_posix()] = sha(p)
state["fixtures_acceptance_h2v3"] = {"count": len(fx), "files": fx}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
               encoding="utf-8")
print(json.dumps({
    "label": LABEL, "head": state["head"], "staged": len(state["staged_paths"]),
    "tracked_modified": state["tracked_modified_count"],
    "untracked": state["untracked_entries"],
    "c_freeze_12": {p: (v.get("sha256") or "MISSING")[:8] for p, v in state["c_freeze_12"].items()},
    "freeze32": f'{state["v3_freeze_32"]["matched"]}/{state["v3_freeze_32"]["count"]}',
    "budget": state["protected_repo"]["docs/evidence/LOCAL-R1-20261101/budget/budget.json"].get("sha256"),
}, ensure_ascii=False, indent=1))
