"""T209-PREP 独立验收：零真实调用证据（独立探针，不复用开发脚本）。

1. 源码扫描：新模块/新测试不得出现 provider/网络/环境变量读取 token；
2. 子进程 A：import 前替换 socket.create_connection/getaddrinfo/socket.connect，
   只 import + 构造/渲染分列报告，断言外部尝试 0；
3. 子进程 B：用 sitecustomize 在解释器启动时替换 socket/DNS，完整运行独立的
   candidate 归档/校验/恢复/diff 探针（03），断言外部尝试 0 且探针仍 PASS。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
INDEP = ROOT / "docs/reports/OBS-EVAL/P2/T209-PREP/independent"
MODULE = ROOT / "backend/src/mktkb/evaluation/p2_candidate_report.py"
TEST = ROOT / "backend/tests/evaluation/test_p2_candidate_report.py"
PY = str(ROOT / ".venv/Scripts/python.exe")

FORBIDDEN_MODULE = re.compile(
    r"httpx|requests|urllib|openai|deepseek|anthropic|dashscope|tencentcloud|"
    r"socket|urlopen|score_ragas|product_adapter|QaEngine|subprocess|Popen|"
    r"os\.environ|getenv|dotenv|load_dotenv|approve_baseline\(",
    re.IGNORECASE,
)
#: 测试文件允许 ``socket``：它只用于「import 前替换并断言 0 次尝试」的 guard 探针。
FORBIDDEN_TEST = re.compile(
    r"httpx|requests|urllib|openai|deepseek|anthropic|dashscope|tencentcloud|"
    r"urlopen|score_ragas|product_adapter|QaEngine|os\.environ|load_dotenv",
    re.IGNORECASE,
)

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def scan(path: Path, pattern: re.Pattern[str]) -> list[str]:
    hits: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if pattern.search(line):
            hits.append(f"{number}:{line.strip()}")
    return hits


CHILD_A = r"""
import socket, sys
attempts = []
def blocked(*a, **k):
    attempts.append(repr(a[:1]))
    raise RuntimeError("T209P guard: external attempt forbidden")
socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socket.connect = blocked
sys.path.insert(0, r"{src}")
import mktkb.evaluation.p2_candidate_report as pr
axes = tuple(pr.AxisEvidence.create(axis=a, planned=30, passed=30, not_applicable=0, unknown=0, violations=0) for a in pr.AXES)
report = pr.build_split_report(
    reference=pr.ReferenceSource.create(source_kind="synthetic-mirror", document="docs/reports/OBS-EVAL/P2/T209-PREP/independent/mirror.json", plan_id="ZERO", code_version="synthetic"),
    execution=pr.build_execution(round_id="ZERO", runs=(pr.RunOutcome("s0", "s", "succeeded", 30, 30),)),
    quality=pr.build_quality(round_id="ZERO", total=30, passed=30, failed=0, errors=0, safety_violations=0, min_pass=24, thresholds_approved=False, verified=True, scenario_verifications=(("s0", True),)),
    evidence=pr.build_evidence(round_id="ZERO", total=30, missing_evidence_cases=0, axes=axes, verified=True),
    soft=(pr.SoftStatus.not_run("ragas", recorded_status="NOT-RUN", detail="s"),),
    funding=pr.FundingStatus.create(ledger_current_sha256="1"*64, ledger_previous_sha256="2"*64, ledger_change_cause="legitimate_spend", go_current_sha256="3"*64, go_archived_sha256="4"*64, archived_line_moment="z"),
)
text = pr.render_split_markdown(report)
state = pr.candidate_state_for_report(report)
print("RENDER_OK", len(text), state)
print("ATTEMPTS", len(attempts))
assert attempts == [], attempts
"""

SITECUSTOMIZE = r"""
import atexit, os, socket
attempts = []
def blocked(*a, **k):
    attempts.append(repr(a[:1]))
    raise RuntimeError("T209P guard: external attempt forbidden")
socket.create_connection = blocked
socket.getaddrinfo = blocked
socket.socket.connect = blocked
@atexit.register
def _dump():
    path = os.environ.get("T209P_ATTEMPT_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(str(len(attempts)))
"""


def main() -> int:
    for label, path, pattern in (
        ("module", MODULE, FORBIDDEN_MODULE),
        ("test", TEST, FORBIDDEN_TEST),
    ):
        hits = scan(path, pattern)
        check(
            not hits,
            f"Z1 {label} 源码无 provider/网络/环境变量读取 token",
            f"hits={len(hits)}" + (f" first={hits[0]}" if hits else ""),
        )

    # 子进程 A：import 前打补丁
    completed = subprocess.run(
        [PY, "-c", CHILD_A.format(src=str(ROOT / "backend/src"))],
        capture_output=True, text=True, check=False, cwd=str(ROOT),
        encoding="utf-8", errors="replace",
        env={**os.environ, "MKTKB_NO_DOTENV": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    out = completed.stdout
    check(completed.returncode == 0, "Z2 子进程 import+构造+渲染 退出码 0", completed.stderr.strip()[-300:])
    check("RENDER_OK" in out and "ATTEMPTS 0" in out, "Z3 子进程 import+渲染外部尝试 0", out.strip().replace("\n", " | "))

    # 子进程 B：sitecustomize 在启动时打补丁，完整跑 candidate 链
    work = Path(tempfile.mkdtemp(prefix="t209p-indep-zero-"))
    try:
        (work / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
        attempt_file = work / "attempts.txt"
        env = {
            **os.environ,
            "PYTHONPATH": str(work),
            "T209P_ATTEMPT_FILE": str(attempt_file),
            "MKTKB_NO_DOTENV": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        completed = subprocess.run(
            [PY, str(INDEP / "03_candidate_probe.py"), "--zero-child"],
            capture_output=True, text=True, check=False, cwd=str(ROOT), env=env,
            encoding="utf-8", errors="replace",
        )
        attempts = int(attempt_file.read_text(encoding="utf-8")) if attempt_file.exists() else -1
        check(
            completed.returncode == 0 and "RESULT=PASS" in completed.stdout,
            "Z4 子进程完整 candidate 链仍 PASS",
            completed.stderr.strip()[-300:],
        )
        check(attempts == 0, "Z5 完整 candidate 链外部 socket/DNS 尝试 0", f"attempts={attempts}")
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)

    # 运行时内建检测：模块未绑定这些名字
    sys.path.insert(0, str(ROOT / "backend/src"))
    import mktkb.evaluation.p2_candidate_report as pr  # noqa: E402

    banned_attrs = [name for name in ("httpx", "requests", "openai", "socket", "subprocess") if hasattr(pr, name)]
    check(not banned_attrs, "Z6 模块运行期未绑定网络/provider 模块", str(banned_attrs))

    failed = [name for ok, name, _ in RESULTS if not ok]
    print(f"\nchecks={len(RESULTS)} failed={len(failed)}")
    print("RESULT=" + ("PASS" if not failed else "FAIL"))
    for name in failed:
        print("FAILED_CHECK=" + name)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
