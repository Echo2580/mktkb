"""Replay public artifacts only. Run from repo root with the project .venv and -B."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import types

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "backend/src"))


def deny(*args, **kwargs):
    raise AssertionError("SAFE-DIAG replay forbids network")


socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny

from mktkb.evaluation import p2_score_run as drive
from mktkb.evaluation import p2_scoring as current

BASE = "a751889bd4673fe43ba9c631f4e2ea13ce4fe585"
name = "mktkb.evaluation._h2map_baseline_scoring"
baseline = types.ModuleType(name)
sys.modules[name] = baseline
source = subprocess.check_output(["git", "show", BASE + ":backend/src/mktkb/evaluation/p2_scoring.py"])
baseline.__file__ = str(ROOT / "backend/src/mktkb/evaluation/p2_scoring.py")
exec(compile(source, baseline.__file__, "exec"), baseline.__dict__)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


root = ROOT / "docs/reports/OBS-EVAL/P2/T207"
codes = drive.load_document_codes(root / "cases/document-codes.json")
report = {"baseline_commit": BASE, "new_real_calls": 0, "public_runs": [], "p1_sources": []}
for label, archived in (("R1", "R1-fixed"), ("R2", "R2-fixed"), ("R4", "R4")):
    run_dir = root / ("p2-t207-" + label.lower() + "-20261111-01")
    cases = drive.load_cases_file(root / ("cases/" + label + ".jsonl"))
    after = drive.score_run(run_dir, cases=cases, document_codes=codes)
    rows = drive.read_cases_jsonl(run_dir / "cases.jsonl")
    index = drive.source_index_from_rows(rows) or None
    before_scores = tuple(baseline.score_public_case(case, rows.get(case.case_id), document_codes=codes,
                         source_index=index, execution_mode=after.execution_mode, real_calls=0).score
                         for case in cases)
    before_value = {"case_scores": [score.to_dict() for score in before_scores],
                    "scorecard": baseline.score_public_suites(before_scores, run_id=after.run_id,
                                                               config_hash=after.config_hash).to_dict()}
    after_value = {"case_scores": [score.to_dict() for score in after.scores],
                   "scorecard": after.scorecard.to_dict()}
    assert before_value == after_value, label + " baseline/current mismatch"
    stored = json.loads((root / "scoring" / archived / "case_scores.json").read_text(encoding="utf-8"))
    assert stored["case_scores"] == after_value["case_scores"], label + " archived scores mismatch"
    normalized = []
    for row in rows.values():
        for turn in row.get("turns") or ():
            old = baseline.outcome_to_dict(baseline.normalize_product_outcome(turn, document_codes=codes,
                                                                             source_index=index))
            new = current.outcome_to_dict(current.normalize_product_outcome(turn, document_codes=codes,
                                                                            source_index=index))
            assert old == new, label + " normalization mismatch"
            normalized.append(new)
    report["public_runs"].append({"run": label, "cases": len(cases), "turns": len(normalized),
        "all_case_score_values_equal": True, "public_scorecard_equal": True,
        "archived_case_scores_equal": True,
        "baseline_sha256": sha(before_value), "current_sha256": sha(after_value),
        "default_normalization_equal": True, "normalization_sha256": sha(normalized)})

for path in ("backend/src/mktkb/evaluation/scorers.py", "backend/src/mktkb/evaluation/runner.py"):
    original = subprocess.check_output(["git", "show", BASE + ":" + path])
    working = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
    assert original.replace(b"\r\n", b"\n") == working, path
    report["p1_sources"].append({"path": path, "normalized_bytes_equal": True,
                                  "sha256": hashlib.sha256(working).hexdigest()})

report["fixed_file_hashes_match_handoff"] = True
for path, expected in {
    "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl": "1648405845fd5e19b593e610b92f8505fdfd78a9e57079648dc14673576785d7",
    "docs/evidence/LOCAL-R1-20261101/budget/budget.json": "79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json": "3ed427f42ac2eeedff489505b94f730eadba1dc38f1b9adecf94d25750b02a7c",
}.items():
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path

target = Path(__file__).with_name("default-differential.json")
target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"public_runs": report["public_runs"], "new_real_calls": 0}, ensure_ascii=False))


