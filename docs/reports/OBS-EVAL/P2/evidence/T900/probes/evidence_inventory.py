"""T900 phase-1 package evidence inventory (read-only).

1) Maps current SHA-256 of backend evaluation sources/tests.
2) Extracts 64-hex tokens from each package's report/review/receipt files and
   reports exact matches to current files (heuristic: a digest quoted in the
   document equals the current file hash byte-for-byte).
3) Emits machine JSON; no writes outside the output path.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
P2 = ROOT / "docs/reports/OBS-EVAL/P2"
TOKEN = re.compile(r"\b[0-9a-fA-F]{64}\b")
PREFIX = re.compile(r"\b[0-9a-fA-F]{16}\b")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_hashes() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for base in ("backend/src/mktkb", "backend/tests", "docs/evaluation", "frontend/e2e"):
        root = ROOT / base
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".py", ".json", ".ts", ".tsx", ".md"}:
                continue
            try:
                out.setdefault(sha(path), []).append(str(path.relative_to(ROOT)))
            except OSError:
                continue
    return out


PACKAGES = {
    "T201": P2 / "T201",
    "T202": P2 / "T202",
    "T203": P2 / "T203",
    "T204": P2 / "T204",
    "T205": P2 / "T205",
    "R2": P2 / "R2",
    "T206": P2 / "T206",
    "T206-LIVE": P2 / "T206-LIVE",
    "T206-PRE": P2 / "T206-PRE",
    "T207": P2 / "T207",
    "T207-RETEST-20261119": P2 / "T207-RETEST-20261119",
    "T208": P2 / "T208-REAL-JUDGE-LIVE",
    "T208-GATE-WIRING-OFFLINE": P2 / "T208-GATE-WIRING-OFFLINE",
    "T208-REAL-JUDGE-IA": P2 / "T208-REAL-JUDGE-IA",
    "T209-PREP": P2 / "T209-PREP",
    "T209-ENGINEERING-CLOSEOUT": P2 / "T209-ENGINEERING-CLOSEOUT",
    "H2-DOC-REBUILD": P2 / "H2-DOC-REBUILD",
    "NCU-RELEASE-EVIDENCE": P2 / "NCU-RELEASE-EVIDENCE",
    "CROSS-SCENARIO-GATE": P2 / "CROSS-SCENARIO-GATE",
    "H2-REBUILT-CARDS": P2 / "H2-REBUILT-CARDS",
}


def main() -> int:
    hashes = current_hashes()
    report = {"root": str(ROOT), "packages": {}, "note": "digest match is a heuristic traceability check"}
    for name, directory in PACKAGES.items():
        entry = {
            "dir_exists": directory.exists(),
            "files": [],
            "layers": {"dev": [], "independent": [], "manager": []},
            "matched_current_files": {},
            "matched_prefixes": {},
            "unmatched_digest_count": 0,
        }
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".txt"}:
                    continue
                rel = str(path.relative_to(ROOT))
                low = path.name.lower()
                entry["files"].append(rel)
                if "review" in low or "independent" in low or low.startswith("b0-wiring-independent"):
                    entry["layers"]["independent"].append(rel)
                if "manager" in low or "pm-acceptance" in low or "receipt" in low:
                    entry["layers"]["manager"].append(rel)
                if low in {"report.md", "dev-report.md", "dev-report-r03.md", "report-r1.md"}:
                    entry["layers"]["dev"].append(rel)
                try:
                    text = path.read_text("utf-8", errors="ignore")
                except OSError:
                    continue
                for token in sorted({t.lower() for t in TOKEN.findall(text)}):
                    if token in hashes:
                        entry["matched_current_files"].setdefault(token, sorted(set(hashes[token])))
                    else:
                        entry["unmatched_digest_count"] += 1
                for prefix in sorted({t.lower() for t in PREFIX.findall(text)}):
                    if len(prefix) != 16:
                        continue
                    hits = sorted({f for h, files in hashes.items() if h.startswith(prefix) for f in files})
                    if hits:
                        entry["matched_prefixes"].setdefault(prefix, hits)
        report["packages"][name] = entry
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out is not None:
        out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
