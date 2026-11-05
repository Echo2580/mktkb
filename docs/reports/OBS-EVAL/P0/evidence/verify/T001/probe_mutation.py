r"""T001 independent probe #3: mutation testing of the new test suite.

Purpose: prove the 68 tests are NOT vacuous. We copy the package + tests into a
temp tree OUTSIDE the repo, apply one behaviour-breaking mutation at a time, and
require the suite to go red. A mutation that the suite does not catch means the
corresponding acceptance assertion is decorative.

Repo deliverables are never modified (all edits happen in a temp copy).
ASCII-only output.

Run from repo root:
  $env:MKTKB_PROJECT_TOTAL_LIMIT_CNY="20.0"
  .\.venv\Scripts\python.exe -B -X utf8 <this file>
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
SRC = ROOT / "backend" / "src"
TESTS = ROOT / "backend" / "tests" / "observability"
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def snapshot(dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(SRC / "mktkb", dst / "src" / "mktkb")
    shutil.copytree(TESTS, dst / "tests" / "observability")


def run_suite(work: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(work / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [str(PY), "-B", "-m", "pytest", "tests/observability", "-q", "-p", "no:cacheprovider"],
        cwd=str(work),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=600,
    )


def mutate(work: Path, rel: str, old: str, new: str) -> None:
    path = work / "src" / "mktkb" / "observability" / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    assert count == 1, f"mutation anchor not unique in {rel}: count={count}"
    path.write_text(text.replace(old, new), encoding="utf-8")


MUTATIONS = [
    (
        "M1 rag+clarification wrongly requires answer",
        "contracts.py",
        '    OutcomeKind.CLARIFICATION: frozenset({"parse", "commit"}),',
        '    OutcomeKind.CLARIFICATION: frozenset({"parse", "answer", "commit"}),',
    ),
    (
        "M2 legacy+not_found wrongly requires query_expansion",
        "contracts.py",
        '    OutcomeKind.NOT_FOUND: frozenset({"intent_parse", "retrieve", "commit"}),',
        '    OutcomeKind.NOT_FOUND: frozenset({"intent_parse", "retrieve", "query_expansion", "commit"}),',
    ),
    (
        "M3 conditional spans honour a 5th unknown key",
        "contracts.py",
        '    ("index_sync_performed", "index_sync"),\n)',
        '    ("index_sync_performed", "index_sync"),\n    ("unknown", "bogus_span"),\n)',
    ),
    (
        "M4 TraceRecord frozen=False",
        "contracts.py",
        "@dataclass(frozen=True)\nclass TraceRecord:",
        "@dataclass(frozen=False)\nclass TraceRecord:",
    ),
    (
        "M5 TraceRecord drops a design field (degraded_json)",
        "contracts.py",
        "    degraded_json: str | None = None\n",
        "",
    ),
    (
        "M6 hash_question no longer rejects empty HMAC key",
        "versioning.py",
        '        if not key:\n            raise ValueError("hmac-sha256 必须提供非空 key；真实业务问题禁止无密钥哈希")\n',
        "        if False:  # mutation\n            pass\n",
    ),
    (
        "M7 config_hash no longer rejects secret-like keys",
        "versioning.py",
        "        if _SECRET_KEY_PATTERN.search(name):",
        "        if False:  # mutation",
    ),
    (
        "M8 pipeline_version ignores explicit components",
        "versioning.py",
        "    return _short_digest(dict(payload))",
        '    return _short_digest({"fixed": 1})',
    ),
    (
        "M9 default components bound at module import (not lazy)",
        "versioning.py",
        "    payload = _default_pipeline_components() if components is None else components\n",
        '    global _CACHE  # mutation\n'
        "    if components is None:\n"
        "        try:\n"
        "            payload = _CACHE\n"
        "        except NameError:\n"
        "            payload = _CACHE = _default_pipeline_components()\n"
        "    else:\n"
        "        payload = components\n",
    ),
    (
        "M10 top-level business import added",
        "versioning.py",
        "from typing import Any, Mapping\n",
        "from typing import Any, Mapping\n\nfrom ..qa.service import QA_ENGINE_VERSION  # mutation\n",
    ),
]


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="t001-mut-"))
    try:
        snapshot(work)
        baseline = run_suite(work)
        tail = [ln for ln in baseline.stdout.strip().splitlines() if "passed" in ln or "failed" in ln]
        print(f"baseline copy: rc={baseline.returncode} :: {tail[-1] if tail else '(no summary)'}")
        if baseline.returncode != 0:
            print("HARNESS FAILED: pristine copy does not pass; output:")
            print(baseline.stdout[-3000:])
            print(baseline.stderr[-2000:])
            return 1

        failures = 0
        for label, rel, old, new in MUTATIONS:
            snapshot(work)
            mutate(work, rel, old, new)
            result = run_suite(work)
            summary = [ln for ln in result.stdout.strip().splitlines() if "passed" in ln or "failed" in ln]
            caught = result.returncode != 0
            print(f"{'CAUGHT' if caught else 'MISSED'} {label} :: rc={result.returncode} :: {summary[-1] if summary else '(no summary)'}")
            if not caught:
                failures += 1
                print("  --- suite output tail ---")
                for ln in result.stdout.strip().splitlines()[-12:]:
                    print("  " + ln)

        print("")
        if failures:
            print(f"RESULT: {failures}/{len(MUTATIONS)} mutations were NOT caught (tests are vacuous for those behaviours)")
            return 1
        print(f"RESULT: {len(MUTATIONS)}/{len(MUTATIONS)} mutations caught; test suite is behaviourally strict")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
