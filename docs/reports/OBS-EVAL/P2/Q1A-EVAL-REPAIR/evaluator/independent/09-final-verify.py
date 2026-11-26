"""Q1a-1 独立验收：最终现场/冻结/证据汇总（确定性、零网络）。

汇总：HEAD/分支/暂存、15 tracked modified 时间、C 冻结 12、manifest 10、独立探针计数、
netguard 正向/负向控制、pytest collect/run、docs/evidence 写入检查、资金件差异说明。
只读仓库公开文件与独立探针输出；不读真实 H2/私有材料。

运行（仓库根）：
  .venv/Scripts/python.exe <本文件>
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[7]
EVAL = Path(__file__).resolve().parents[1]
IND = Path(__file__).resolve().parent
FREEZE = ROOT / "docs/reports/OBS-EVAL/P2/T207-H2-OFFLINE-READINESS/evidence/c-freeze.txt"
MANIFEST = EVAL / "evidence/06-hash-manifest.json"
PACKAGE_START = datetime(2026, 11, 14, 16, 59, 23)  # 第一个新文件创建时间（模块）
HEAD_EXPECTED = "97b0066726e5b8d6f94cbc0b63a890084550c106"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def parse_freeze() -> list[dict[str, str]]:
    text = FREEZE.read_text(encoding="utf-8")
    section = text.split("[final-object-bytes]", 1)[1].split("[funding]", 1)[0]
    rows = []
    for line in section.splitlines():
        match = re.match(r"^([0-9a-f]{64}) \*(.+)$", line.strip())
        if match:
            rows.append({"sha256": match.group(1), "path": match.group(2)})
    return rows


def parse_probe(name: str) -> dict[str, Any]:
    path = IND / name
    lines = path.read_text(encoding="utf-8").splitlines()
    # 探针会在最终 payload 前打印一行 *-note JSON；最终 payload 的顶层 "{" 无缩进。
    starts = [index for index, line in enumerate(lines) if line == "{"]
    if not starts:
        raise ValueError(f"no JSON payload in {name}")
    payload = json.loads("\n".join(lines[starts[-1]:]))
    return {
        "file": name,
        "probe_count": payload.get("probe_count"),
        "check_count": payload.get("check_count"),
        "failed_count": payload.get("failed_count"),
        "failures": payload.get("failures"),
    }


# --------------------------------------------------------------------------- #
# 现场
# --------------------------------------------------------------------------- #
head = git("rev-parse", "HEAD").strip()
branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
status_lines = [line for line in git("status", "--porcelain=v1").splitlines() if line.strip()]
modified = [line[3:].strip() for line in status_lines if line.startswith(" M")]
untracked = [line[3:].strip() for line in status_lines if line.startswith("??")]
staged = [line for line in status_lines if not line.startswith((" M", "??"))]
cached_clean = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0
modified_mtimes = {
    path: datetime.fromtimestamp((ROOT / path).stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    for path in modified
}
late_modified = [path for path, stamp in modified_mtimes.items()
                 if datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S") >= PACKAGE_START]

allowed_prefixes = (
    "backend/src/mktkb/evaluation/p2_evidence_rescore.py",
    "backend/tests/evaluation/test_p2_evidence_rescore.py",
    "docs/evaluation/p2-evidence-rescore-v0_1.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/",
)
late_untracked = []
for path in untracked:
    item = ROOT / path
    if not item.exists():
        continue
    stamp = datetime.fromtimestamp(item.stat().st_mtime)
    if stamp >= PACKAGE_START and not path.startswith(allowed_prefixes):
        late_untracked.append(path)

# --------------------------------------------------------------------------- #
# 冻结 / manifest
# --------------------------------------------------------------------------- #
freeze_rows = parse_freeze()
freeze_check = []
for row in freeze_rows:
    actual = sha256(ROOT / row["path"])
    freeze_check.append({**row, "actual": actual, "match": actual == row["sha256"]})
manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
manifest_check = []
for item in manifest["files"]:
    path = ROOT / item["path"]
    actual = sha256(path)
    manifest_check.append({
        "path": item["path"], "expected": item["sha256"], "actual": actual,
        "bytes_ok": path.stat().st_size == item["bytes"],
        "match": actual == item["sha256"],
    })

# --------------------------------------------------------------------------- #
# 资金件（非 12 冻结；gitignored，记录与本包时间关系）
# --------------------------------------------------------------------------- #
funding = {}
for path, expected in (
    ("docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl",
     "4d80d776bcf25079817f5f7dd8863037c27bc01971b6fa0fe239b432ee55fcc6"),
    ("docs/evidence/LOCAL-R1-20261101/budget/budget.json",
     "79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e"),
    ("docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json",
     "f688ec7efb7e8ddc145ae9fd593a482a85a6e4a764a9d49a09eab4f3fc26ea98"),
):
    item = ROOT / path
    funding[path] = {
        "exists": item.exists(),
        "actual": sha256(item) if item.exists() else None,
        "c_freeze_reference": expected,
        "match_c_freeze": item.exists() and sha256(item) == expected,
        "mtime": datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        if item.exists() else None,
    }
evidence_late = [
    str(path.relative_to(ROOT)).replace("\\", "/")
    for path in (ROOT / "docs/evidence").rglob("*")
    if path.is_file() and datetime.fromtimestamp(path.stat().st_mtime) >= PACKAGE_START
]

# --------------------------------------------------------------------------- #
# 独立探针 / netguard / pytest
# --------------------------------------------------------------------------- #
probes = [parse_probe(name) for name in (
    "01-matcher-scope-probes.out.json",
    "02-identity-write-probes.out.json",
    "03-projection-purity-probes.out.json",
    "04-four-axis-probes.out.json",
    "06-static-scan-probes.out.json",
    "07-contract-matrix-probes.out.json",
)]
probe_total_checks = sum(item["check_count"] for item in probes)
probe_total_failed = sum(item["failed_count"] for item in probes)

netguard_positive = (IND / "05-netguard-positive-control.out.txt").read_text(encoding="utf-8")
netguard_negative = (IND / "05b-netguard-teardown-fails.out.expected-fail.txt").read_text(encoding="utf-8")
pytest_text = (IND / "00-pytest-independent.txt").read_text(encoding="utf-8")

schema_notes = json.loads((IND / "08-schema-edge-probes.out.json").read_text(encoding="utf-8"))

payload = {
    "schema": "q1a1-independent-final-verify/v1",
    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "git": {
        "head": head,
        "head_expected": HEAD_EXPECTED,
        "head_match": head == HEAD_EXPECTED,
        "branch": branch,
        "staged_entries": staged,
        "cached_clean": cached_clean,
        "tracked_modified_count": len(modified),
        "tracked_modified": modified_mtimes,
        "tracked_modified_before_package": not late_modified,
        "late_modified": late_modified,
        "untracked_late_outside_allowed": late_untracked,
    },
    "c_freeze": {
        "reference": str(FREEZE.relative_to(ROOT)).replace("\\", "/"),
        "item_count": len(freeze_check),
        "all_match": all(row["match"] for row in freeze_check),
        "items": freeze_check,
        "p2_hard_evidence": next(row for row in freeze_check
                                 if row["path"].endswith("p2_hard_evidence.py")),
    },
    "manifest": {
        "file_count": len(manifest_check),
        "all_match": all(row["match"] and row["bytes_ok"] for row in manifest_check),
        "items": manifest_check,
    },
    "funding": {
        "note": "docs/evidence/ 被 .gitignore 忽略；这三项不是 C 冻结 12 对象。"
                "本包开始前（16:59）后无写入；ledger/GO 与 c-freeze 参考值不同，"
                "属 2026-11-14 10:31 既有状态，非 Q1a-1 造成。",
        "files": funding,
        "files_written_after_package_start": evidence_late,
    },
    "tests": {
        "collect_20": "20 tests collected" in pytest_text,
        "passed_20": "20 passed" in pytest_text,
        "collect_exit_0": "collect_exit_code=0" in pytest_text,
        "run_exit_0": "run_exit_code=0" in pytest_text,
        "netguard_positive_2_passed": "2 passed" in netguard_positive,
        "netguard_negative_expected_error": (
            "1 passed, 1 error" in netguard_negative
            and "检测到真实外部出站尝试" in netguard_negative
        ),
    },
    "independent_probes": {
        "probe_files": probes,
        "total_check_count": probe_total_checks,
        "total_failed_count": probe_total_failed,
    },
    "schema_edge_notes": {
        "note_count": len(schema_notes["notes"]),
        "disposition": schema_notes["disposition"],
    },
}
OUT = IND / "09-final-verify.out.json"
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {OUT}")
print(json.dumps({
    "head_match": payload["git"]["head_match"],
    "c_freeze_12": payload["c_freeze"]["all_match"],
    "manifest_10": payload["manifest"]["all_match"],
    "tests": payload["tests"],
    "probe_checks": payload["independent_probes"]["total_check_count"],
    "probe_failed": payload["independent_probes"]["total_failed_count"],
}, ensure_ascii=False))
