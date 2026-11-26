"""R3 public-side privacy scan.

Builds needles from the authorized private inputs (case ids, questions, answers,
target/forbidden values, entity keys, record codes, unit ids, document names)
and scans the public aggregate/report/probe outputs. Prints only category counts,
never the matched text or the needle values.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
for path in (
    HERE,
    REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r2",
    REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1",
    REPO / "backend/src",
    REPO / "tools",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import _common_r2 as C  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402
from mktkb.evaluation.p2_evidence_io import read_encrypted_evidence  # noqa: E402
from mktkb.evaluation.p2_evidence_rescore import _used_layers  # noqa: E402

PUBLIC_FILES = [
    HERE.parent / "rescore-aggregate-r3.json",
    HERE.parent / "rescore-report-r3.md",
    *sorted(HERE.glob("*.out.json")),
    HERE / "06-netguard.json",
]
CONTRACT_V2 = Path(r"D:\mktkb-q1a2-scope-contract\scope-targets-contract-v2.fernet")
KEY = Path(r"D:\mktkb-p2-holdout\keys\v2.key")
OUT = HERE / "08-privacy-scan.json"


def main() -> int:
    bundle = C.load_bundle()
    contract = json.loads(Fernet(KEY.read_bytes()).decrypt(CONTRACT_V2.read_bytes()).decode("utf-8"))
    needles: dict[str, set[str]] = {
        "case_id": set(),
        "question": set(),
        "reference_answer": set(),
        "expected_value": set(),
        "forbidden_value": set(),
        "entity_key": set(),
        "record_code": set(),
        "unit_id": set(),
        "document_name": set(),
    }
    for case in bundle.dataset.cases:
        needles["case_id"].add(case.case_id)
        if case.question:
            needles["question"].add(case.question)
        for turn in case.turns:
            q = turn.get("question")
            if isinstance(q, str) and q:
                needles["question"].add(q)
        if case.reference_answer:
            needles["reference_answer"].add(case.reference_answer)
        needles["expected_value"].update(str(value) for value in case.expected_values if len(str(value)) >= 4)
        needles["forbidden_value"].update(str(value) for value in case.forbidden_values if len(str(value)) >= 4)
        for collection in ("expected_sources", "relevant_units", "forbidden_sources"):
            for ref in getattr(case, collection):
                if ref.get("record_code"):
                    needles["record_code"].add(str(ref["record_code"]))
                if ref.get("unit_key"):
                    needles["unit_id"].add(str(ref["unit_key"]))
    for case in contract["cases"]:
        for axis in case["axes"].values():
            for target in axis.get("targets") or []:
                if isinstance(target, dict) and isinstance(target.get("entity_key"), str):
                    needles["entity_key"].add(target["entity_key"])
    # document names and observed unit ids from the public ingest/old evidence
    ingest = json.loads((REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json").read_bytes())
    for row in ingest["sources"]:
        path = row.get("path")
        if isinstance(path, str):
            needles["document_name"].add(Path(path.replace("\\", "/")).name)
        name = row.get("name")
        if isinstance(name, str) and name:
            needles["document_name"].add(name)
    for index in range(4):
        run = C.OLD_RUN / "runs" / f"r{index}"
        plan = json.loads((run / "out" / "controlled" / "case-plan.json").read_bytes())
        key = (run / "ev.key").read_bytes()
        ev_dir = next(p for p in (run / "evidence").iterdir() if p.is_dir())
        for case in plan.get("cases") or []:
            for turn in case.get("turns") or []:
                if turn.get("status") != "executed":
                    continue
                env = read_encrypted_evidence(ev_dir / turn["evidence_file"], key=key)
                for unit_id in _used_layers(env.get("capture", {}).get("events") or []):
                    needles["unit_id"].add(str(unit_id))

    # drop very short needles to avoid incidental count/date matches; record codes are
    # short by design and are scanned at length >= 1.
    needles = {
        category: {
            value
            for value in values
            if len(value) >= (1 if category == "record_code" else 4)
        }
        for category, values in needles.items()
    }
    texts: dict[str, str] = {}
    for path in PUBLIC_FILES:
        if path.is_file():
            texts[str(path.relative_to(REPO))] = path.read_text(encoding="utf-8", errors="replace")
    hits: Counter[str] = Counter()
    hit_files: Counter[str] = Counter()
    for category, values in needles.items():
        for value in values:
            for name, text in texts.items():
                if value in text:
                    hits[category] += 1
                    hit_files[name] += 1
                    break
    payload = {
        "schema_version": "q1a3r3-privacy-scan/v0.1",
        "scanned_files": sorted(texts),
        "needle_counts": {category: len(values) for category, values in sorted(needles.items())},
        "hit_counts": dict(sorted(hits.items())),
        "hit_file_counts": dict(sorted(hit_files.items())),
        "verdict": "clean" if sum(hits.values()) == 0 else "needle_hit",
        "note": "only category counts and file names are reported; no needle value or matched text is printed",
    }
    OUT.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    print(json.dumps({"verdict": payload["verdict"], "hits": payload["hit_counts"]}, ensure_ascii=True))
    return 0 if payload["verdict"] == "clean" else 1


if __name__ == "__main__":
    raise SystemExit(main())
