"""C1-P2 独立验收：终态保全核对。

对比 10-snapshot-start.json 与 10-snapshot-end.json，并独立核对：
- HEAD/分支/暂存/15 tracked/commit 数；
- R2 28 保护文件 + C 冻结 12 + 15 tracked + axes 38 Q1a-1 保护 + 2 只读参考；
- 7 个外部/私密项（只 hash 字节）；
- 外来 untracked 2086 个基线文件逐字节不变；
- 本会话新增文件只落在 c1-1/p2/independent/ 与两份报告。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
IND = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/independent"
AXES = REPO / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json"
OUT = IND / "15-final-compare.json"
PY = REPO / ".venv/Scripts/python.exe"

DEV_FILES_START = {
    "backend/src/mktkb/evaluation/p2_empty_scope_proof.py": "1f503d16d91d3423da969a659c2f97fe811e9c2af859158585ecee16878f28ea",
    "backend/tests/evaluation/test_p2_empty_scope_proof.py": "a2b20218ccf1178482fdb66b8d6bcedaf8a46eb3e4f85af1d0eac4fcf89685a1",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/dev-report.md": "2b6fad41af025c4120f646bffe0f69c8a6553b8bf5e00be372f84de4aeadd064",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/differential.json": "0528591da48152036d72c7f866c8e6a9ed0d509350a3f357be597f2967c21016",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/differential_probe.py": "99aa8d5999e068c1db5a64fd7e7a4cbfc45778da2b34ea99691021a7a8ae4dae",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/frozen-sha.json": "192c2c799f26bb8dca77ae396c719de0fdb30983bdec29fa390f9d98b252d8f1",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/frozen_probe.py": "fc810e01e3c193976ba2acd29665245ec2864263726a4165d0f81f6f3ae0d0b6",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/protected-after.json": "84c97dec512933375610d07e6daa2118f3e268320225f745bc0b602dad9c4cae",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/protected-compare.json": "f1fe89b7d850ca6320134bff27c1efe523eb33adfdf135442e0361066d795a9b",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/protected_compare.py": "eaab612b3c40ac8b00c14bd048b048111017fb44a04a17480e51d3bf06aab1c2",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/pytest-collect.txt": "b1cbb5ce4e8840b5bb2b5a47ad0af69a2e1b666d5f450eaedafd3988cebc1e90",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/pytest.txt": "7fdefd44ae878db319140e74dd37ec2e7089aba82ff1c9beb4c1247997d01a90",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/zero-call.json": "55183cca68eebbe159a8ea65c0973c7083849922e89205d811f40910cb1ea7f9",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/evidence/zero_call_probe.py": "d29a3fa1e9799465c2beb3ae4260002b9c01c17864241685548cce6cd78ac4b3",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    start = json.loads((IND / "10-snapshot-start.json").read_text(encoding="utf-8"))
    completed = subprocess.run(
        [str(PY), "-B", str(IND / "10-snapshot.py"), "end"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr)
        return 5
    end = json.loads((IND / "10-snapshot-end.json").read_text(encoding="utf-8"))
    axes = json.loads(AXES.read_text(encoding="utf-8"))

    # ---- git ----
    git_fields = ("head", "branch", "staged", "tracked_modified", "commit_count")
    git_diff = {
        field: {"start": start["git"].get(field), "end": end["git"].get(field)}
        for field in git_fields
        if start["git"].get(field) != end["git"].get(field)
    }
    # ---- 基线组 ----
    groups = {}
    for name in ("repo_files", "c_freeze_12", "tracked_modified_15"):
        groups[name] = {
            "start_mismatch": start[name]["mismatch"],
            "end_mismatch": end[name]["mismatch"],
            "count": end[name]["count"],
            "ok": not start[name]["mismatch"] and not end[name]["mismatch"],
        }
    # ---- 外部项 start vs end ----
    external = {}
    for name in start["external"]:
        a, b = start["external"][name], end["external"][name]
        if a.get("kind") == "tree":
            same = a["rows"] == b["rows"] and a["missing"] == b["missing"] and a["extra"] == b["extra"]
            external[name] = {"kind": "tree", "start_end_equal": same, "files": a["expected_count"], "all_match": a["all_match"] and b["all_match"]}
        else:
            same = a["actual"] == b["actual"]
            external[name] = {"kind": "file", "start_end_equal": same, "match": a["match"] and b["match"]}
    # ---- 外来 untracked start vs end ----
    foreign_same = start["foreign_tree"]["rows"] == end["foreign_tree"]["rows"]
    added_start = set(start["foreign_tree"]["added_since_baseline"])
    added_end = set(end["foreign_tree"]["added_since_baseline"])
    new_since_start = sorted(added_end - added_start)
    allowed_prefixes = (
        "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/independent/",
        "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/independent-review.md",
        "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p2/review-aggregate.json",
    )
    concurrent_prefixes = (
        "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/c1-1/p1/",
    )
    my_products = [p for p in new_since_start if p.startswith(allowed_prefixes)]
    concurrent_products = [p for p in new_since_start if p.startswith(concurrent_prefixes)]
    unexpected_new = [p for p in new_since_start if p not in my_products and p not in concurrent_products]
    # ---- axes 38 + 2 ----
    q1a1 = {}
    for rel, expected in axes["q1a1_protected"].items():
        full = REPO / rel.replace("/", os.sep)
        actual = sha256_file(full) if full.is_file() else None
        q1a1[rel] = {"expected": expected, "actual": actual, "match": actual == expected}
    readonly = {}
    for rel, expected in axes["readonly_references"].items():
        full = REPO / rel.replace("/", os.sep)
        actual = sha256_file(full) if full.is_file() else None
        readonly[rel] = {"expected": expected, "actual": actual, "match": actual == expected}
    # ---- 开发文件 start vs end ----
    dev = {}
    for rel, expected in DEV_FILES_START.items():
        full = REPO / rel.replace("/", os.sep)
        actual = sha256_file(full) if full.is_file() else None
        dev[rel] = {"start": expected, "end": actual, "match": actual == expected}

    payload = {
        "schema_version": "c1p2-independent-final-compare/v0.1",
        "git_diff": git_diff,
        "git_ok": not git_diff,
        "groups": groups,
        "groups_ok": all(row["ok"] for row in groups.values()),
        "external": external,
        "external_ok": all(row["start_end_equal"] and row.get("all_match", row.get("match", False)) for row in external.values()),
        "foreign_tree": {
            "baseline_files_start_end_equal": foreign_same,
            "baseline_missing_end": end["foreign_tree"]["missing"],
            "baseline_changed_end": end["foreign_tree"]["changed"],
            "added_start": len(added_start),
            "added_end": len(added_end),
            "new_since_start": new_since_start,
            "my_products": my_products,
            "concurrent_products": concurrent_products,
            "unexpected_new": unexpected_new,
            "ok": foreign_same
            and not end["foreign_tree"]["missing"]
            and not end["foreign_tree"]["changed"]
            and not unexpected_new,
        },
        "q1a1_protected_38": {
            "count": len(q1a1),
            "mismatch": sorted(rel for rel, row in q1a1.items() if not row["match"]),
        },
        "readonly_references_2": {
            "count": len(readonly),
            "mismatch": sorted(rel for rel, row in readonly.items() if not row["match"]),
        },
        "dev_files": {
            "count": len(dev),
            "mismatch": sorted(rel for rel, row in dev.items() if not row["match"]),
        },
        "end_summary": {
            "head": end["git"]["head"],
            "branch": end["git"]["branch"],
            "staged": end["git"]["staged"],
            "tracked_modified": end["git"]["tracked_modified"],
            "commit_count": end["git"]["commit_count"],
        },
    }
    payload["verdict"] = all(
        [
            payload["git_ok"],
            payload["groups_ok"],
            payload["external_ok"],
            payload["foreign_tree"]["ok"],
            not payload["q1a1_protected_38"]["mismatch"],
            not payload["readonly_references_2"]["mismatch"],
            not payload["dev_files"]["mismatch"],
        ]
    )
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k not in {"external"}}, ensure_ascii=False, indent=1))
    return 0 if payload["verdict"] else 6


if __name__ == "__main__":
    raise SystemExit(main())
