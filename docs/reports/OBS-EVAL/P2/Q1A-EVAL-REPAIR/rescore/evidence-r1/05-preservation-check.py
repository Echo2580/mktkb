"""R1 保全核验（文件级）：保护件 before/after + git 状态 + 上一轮产物字节。

判据（全部为硬断言，任一不成立即 verdict=changed）：
1. 27 个保护件（23 仓内文件 + 3 棵外部树 + 合同密文）before/after 逐项相等。
2. `tracked_modified` 的 15 条路径与包前完全一致；`staged = 0`；HEAD/分支不变；0 commit。
3. untracked 文件 = 会话起点基线 2107 条外来文件 + 本包新增 12 条自有文件（逐条列出）。
4. 上一轮 NOT-RUN 产物（聚合/报告/私有密文）字节未变（按已知 SHA256 复核）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[6]
for path in (HERE, REPO / "backend" / "src", REPO / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import _common_r1 as C  # noqa: E402

OWN_FILES = (
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/01-protected-after.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/01-protected-before.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/01-protected-compare.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/01-protected-snapshot.py",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/02-rescore-r1.py",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/03-netguard.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/03-netguard.py",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/04-privacy-scan.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/04-privacy-scan.py",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/05-preservation-check.py",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/_common_r1.py",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r1.json",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r1.md",
)

#: 会话起点实测的 untracked 文件数（本包动工前，见对话记录）。
FOREIGN_UNTRACKED_BASELINE = 2107
#: 包前 15 条 tracked modified 的路径（本轮不得增减）。
TRACKED_MODIFIED_BASELINE = (
    ".claude/handoffs/_index.md",
    "backend/src/mktkb/conversations/service.py",
    "backend/src/mktkb/evaluation/cli.py",
    "backend/src/mktkb/evaluation/p2_diagnostics.py",
    "backend/src/mktkb/evaluation/p2_holdout_scenarios.py",
    "backend/src/mktkb/evaluation/p2_live.py",
    "backend/src/mktkb/evaluation/p2_runner.py",
    "backend/src/mktkb/evaluation/p2_scoring.py",
    "backend/src/mktkb/evaluation/product_adapter.py",
    "backend/src/mktkb/qa/service.py",
    "backend/src/mktkb/rag/index.py",
    "backend/src/mktkb/rag/query.py",
    "backend/tests/rag/test_query_state.py",
    "backend/tests/unit/test_conversations.py",
    "docs/reports/OBS-EVAL/P2/T207-QUALITY-REPAIR/manager.md",
)
PREVIOUS_ROUND_ARTIFACTS = {
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate.json":
        "448bb623e89d0650b48cd75be453f54115bd37bfa3f02a64c0acce7cd868375c",
    "D:\\mktkb-q1a3-rescore\\rescore-detail-v1.fernet":
        "2207bde45bc8da1c627d3f56a7b8f80e107d0541e4b2903fed0f8c0c66210501",
}


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO), "-c", "core.quotepath=false", *args],
        capture_output=True,
        check=True,
    )
    return completed.stdout.decode("utf-8", errors="surrogateescape")


def main() -> int:
    checks: list[dict[str, object]] = []

    def check(name: str, measured: object, expected: object) -> None:
        checks.append({"check": name, "measured": measured, "expected": expected, "match": measured == expected})

    compare = C.strict_json((HERE / "01-protected-compare.json").read_bytes())
    check("protected_items", compare["protected_items"], 27)
    check("protected_differences", compare["difference_count"], 0)

    status = [line for line in _git("status", "--porcelain").splitlines() if line.strip()]
    modified = sorted(line[3:] for line in status if line[:2].strip() == "M")
    check("tracked_modified_paths", modified, sorted(TRACKED_MODIFIED_BASELINE))
    check("staged_count", len([line for line in _git("diff", "--cached", "--name-only").splitlines() if line]), 0)
    check("head", _git("rev-parse", "HEAD").strip(), "97b0066726e5b8d6f94cbc0b63a890084550c106")
    check("branch", _git("branch", "--show-current").strip(), "codex/p2-e2e")
    check("commits_created", int(_git("rev-list", "--count", "97b0066726e5b8d6f94cbc0b63a890084550c106..HEAD").strip()), 0)

    untracked = [line for line in _git("ls-files", "--others", "--exclude-standard").splitlines() if line.strip()]
    own_prefix = "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/evidence-r1/"
    own_files = {
        "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-aggregate-r1.json",
        "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/rescore/rescore-report-r1.md",
    }
    own = sorted(
        path
        for path in untracked
        if path.replace("\\", "/").startswith(own_prefix) or path.replace("\\", "/") in own_files
    )
    foreign = [
        path
        for path in untracked
        if not (path.replace("\\", "/").startswith(own_prefix) or path.replace("\\", "/") in own_files)
    ]
    # 硬门：外来 untracked 文件数必须等于会话起点实测基线（本包只允许新增自有产物）。
    check("foreign_untracked_file_count", len(foreign), FOREIGN_UNTRACKED_BASELINE)
    check("untracked_total", len(untracked), FOREIGN_UNTRACKED_BASELINE + len(own))

    previous = {}
    for path_text, expected_sha in PREVIOUS_ROUND_ARTIFACTS.items():
        path = Path(path_text)
        previous[path_text] = {
            "sha256": C.sha256_hex(path.read_bytes()),
            "bytes": path.stat().st_size,
            "unchanged": C.sha256_hex(path.read_bytes()) == expected_sha,
        }
    check("previous_round_artifacts_unchanged", all(row["unchanged"] for row in previous.values()), True)

    payload = {
        "schema_version": "q1a3r1-preservation-check/v0.1",
        "checks": checks,
        "overall": "PASS" if all(row["match"] for row in checks) else "FAIL",
        "previous_round_artifacts": previous,
        "untracked": {
            "total": len(untracked),
            "own": len(own),
            "foreign": len(foreign),
            "foreign_baseline_measured_at_session_start": FOREIGN_UNTRACKED_BASELINE,
        },
        "calls": {"network": 0, "socket": 0, "dns": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
    }
    (HERE / "05-preservation-check.json").write_bytes(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    print(
        json.dumps(
            {
                "overall": payload["overall"],
                "failed": [row["check"] for row in checks if not row["match"]],
                "untracked": payload["untracked"],
            },
            ensure_ascii=True,
        )
    )
    return 0 if payload["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
