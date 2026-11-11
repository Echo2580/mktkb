
r"""T207-FIX-SCORE 验收复跑：打分路径零出站 / 不读 .env / 不读 H1/H2 的运行时证明。

用法（cwd=仓库根，PYTHONPATH=backend/src）：
  .venv\Scripts\python.exe -X utf8 -B <本文件>
"""
from __future__ import annotations

import json
import socket
from pathlib import Path

from mktkb.evaluation.p2_score_run import (
    decide_run,
    load_cases_file,
    load_document_codes,
    score_run,
)

ROOT = Path(r"D:/GPT项目/市场部AI知识库")
RUN = ROOT / "docs/reports/OBS-EVAL/P2/T207/p2-t207-r1-20261111-01"
CASES = ROOT / "docs/reports/OBS-EVAL/P2/T207/cases/R1.jsonl"
CODES = ROOT / "docs/reports/OBS-EVAL/P2/T207/cases/document-codes.json"

connects: list[str] = []
env_reads: list[str] = []
secret_reads: list[str] = []

original_connect = socket.socket.connect


def guard(self, address):  # noqa: ANN001
    connects.append(str(address))
    raise AssertionError("scoring path attempted a network connect")


socket.socket.connect = guard

original_bytes = Path.read_bytes
original_text = Path.read_text


def guarded_bytes(self: Path) -> bytes:
    path = str(self)
    if self.name == ".env":
        env_reads.append(path)
    if any(part in path for part in ("H1", "H2", "holdout", "HO")):
        secret_reads.append(path)
    return original_bytes(self)


def guarded_text(self: Path, *args, **kwargs):
    path = str(self)
    if self.name == ".env":
        env_reads.append(path)
    if any(part in path for part in ("H1", "H2", "holdout", "HO")):
        secret_reads.append(path)
    return original_text(self, *args, **kwargs)


Path.read_bytes = guarded_bytes
Path.read_text = guarded_text

bundle = score_run(RUN, cases=load_cases_file(CASES), document_codes=load_document_codes(CODES))
bundle = decide_run(bundle, cases=load_cases_file(CASES))
print(json.dumps({
    "socket_connects": connects,
    "env_reads": env_reads,
    "h1_h2_reads": secret_reads,
    "real_calls_from_manifest": bundle.real_calls,
    "b0_passed": bundle.scorecard.suites["b0"].passed,
    "b0_exact_passed": bundle.scorecard.suites["b0"].exact_passed,
    "release_ready": bundle.scorecard.release_ready,
    "decision": bundle.decision.decision,
    "hard_failures": list(bundle.decision.hard_failures),
}, ensure_ascii=False))
