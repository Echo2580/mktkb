"""v3 语料返工 R1：收尾保全核对（``00r1-baseline.json`` 的「之前」 vs 现在）。

逐项证明 R1 **没有**动到别人的东西：
1. 分支 / HEAD 不变（0 commit）、暂存区 0；
2. 15 个 tracked modified 路径逐条不变、条数仍为 15；
3. untracked：R0 基线的 224 条一条不少；新增条目必须落在 ``fixtures/acceptance-h2v3/``、
   v3 source-map、或本报告目录下（本轮这三处本来就在 untracked 里，故预期新增 0）；
4. ``fixtures/acceptance/**`` 35 个文件逐字节不变（v2 语料只读）；
5. C 冻结 12 与基线清单逐项相等；
6. ``frozen_inputs``（含产品解析器 ``ingestion/parsers/excel.py``、冻结分类器、三个键空间规则件、
   上游计划与判据）SHA256 不变 —— 这就是「本轮没改产品代码」的证明；
7. ``authorized_change_targets``：逐件给出 R0→R1 的 SHA 对照，并断言**只有**预期的那几件变了；
8. 交付件盘点：v3 语料 13 个文件 + source map + L1 + 规格。

零真实调用；只读 git 与文件。
用法：``.venv\\Scripts\\python.exe 09r1-preservation.py``
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[7]
BASELINE = HERE / "00r1-baseline.json"
OUT = HERE / "09r1-preservation.json"
V3_ROOT = ROOT / "fixtures/acceptance-h2v3"
SOURCE_MAP = ROOT / "docs/evaluation/p2-holdout-v3.source-map.json"

ALLOWED_NEW_PREFIXES = (
    "fixtures/acceptance-h2v3/",
    "docs/evaluation/p2-holdout-v3.source-map.json",
    "docs/evaluation/p2-source-lifecycle-v1.json",
    "docs/superpowers/plans/2026-11-15-h2-v3-corpus-modification-spec.md",
    "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True).stdout.decode("utf-8", "replace")


def main() -> int:
    before = json.loads(BASELINE.read_text(encoding="utf-8"))
    status = git("status", "--porcelain").splitlines()
    tracked_modified = sorted(line[3:] for line in status if line[:2].strip() not in ("??", ""))
    untracked = sorted(line[3:] for line in status if line[:2] == "??")
    head = git("rev-parse", "HEAD").strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
    staged = [line for line in git("diff", "--cached", "--name-only").splitlines() if line.strip()]

    baseline_git = before["git"]
    new_untracked = [path for path in untracked if path not in set(baseline_git["untracked"])]
    lost_untracked = [path for path in baseline_git["untracked"] if path not in set(untracked)]
    outside_scope = [path for path in new_untracked if not any(path.startswith(prefix) or path == prefix.rstrip("/") for prefix in ALLOWED_NEW_PREFIXES)]

    v2_root = ROOT / "fixtures/acceptance"
    v2_files = {str(path.relative_to(v2_root)).replace("\\", "/"): sha256_file(path) for path in sorted(v2_root.rglob("*")) if path.is_file()}
    v2_before = {rel: entry["sha256"] for rel, entry in before["v2_corpus"].items()}
    v2_changed = sorted(rel for rel in set(v2_files) | set(v2_before) if v2_files.get(rel) != v2_before.get(rel))

    baseline = json.loads((ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json").read_text(encoding="utf-8"))["c_freeze_12"]
    c_freeze = {rel: {"expected": baseline[rel], "actual": sha256_file(ROOT / rel)} for rel in sorted(baseline)}
    c_freeze_mismatch = sorted(rel for rel, item in c_freeze.items() if item["expected"] != item["actual"])

    frozen = {
        rel: {
            "r0": entry["sha256"],
            "r1": sha256_file(ROOT / rel),
        }
        for rel, entry in before["frozen_inputs"].items()
    }
    frozen_changed = sorted(rel for rel, item in frozen.items() if item["r0"] != item["r1"])

    authorized = {
        rel: {"r0": entry["sha256"], "r1": sha256_file(ROOT / rel) if (ROOT / rel).is_file() else None}
        for rel, entry in before["authorized_change_targets"].items()
    }
    for rel, item in authorized.items():
        item["changed"] = item["r0"] != item["r1"]
    authorized_expected_changed = {
        "docs/evaluation/p2-source-lifecycle-v1.json",
        "docs/superpowers/plans/2026-11-15-h2-v3-corpus-modification-spec.md",
        "docs/evaluation/p2-holdout-v3.source-map.json",
        "fixtures/acceptance-h2v3/manifest.json",
    }
    authorized_changed = {rel for rel, item in authorized.items() if item["changed"]}

    v3_files = {
        str(path.relative_to(V3_ROOT)).replace("\\", "/"): {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(V3_ROOT.rglob("*"))
        if path.is_file()
    }
    r0_delivery = before["r1_start_delivery"]
    delivery_changed = sorted(rel for rel in set(v3_files) | set(r0_delivery) if v3_files.get(rel, {}).get("sha256") != r0_delivery.get(rel, {}).get("sha256"))
    delivery_unchanged_6 = sorted(rel for rel, item in v3_files.items() if r0_delivery.get(rel, {}).get("sha256") == item["sha256"])

    # R1 只动了 失效日期 有 null 格的两个工作簿（V05 / V06）+ manifest（它嵌 L1 的 SHA）；
    # 其余 4 个 xlsx 的 失效日期 本来全是日期、一格未动，故字节与 R0 逐字节相同。
    expected_changed_paths = {
        "variants/V05_物品位置表_新版V3_移除P01.xlsx",
        "variants/V06_合作店家信息_新电话.xlsx",
        "manifest.json",
    }
    expected_unchanged_paths = {
        "normal/D01_物品位置表.xlsx",
        "normal/D02_合作店家信息.xlsx",
        "normal/D03_市场部工作指南.docx",
        "normal/D04_活动策划流程.docx",
        "normal/D05_物料领用规范.pdf",
        "normal/D06_店家资料维护说明.pdf",
        "variants/V01_临时物料位置通知.pdf",
        "variants/V03_物品位置表_历史V1.xlsx",
        "variants/V04_物品位置表_新版V3.xlsx",
        "variants/V07_物料位置独立通知.pdf",
    }

    checks = {
        "branch_unchanged": branch == baseline_git["branch"],
        "head_unchanged_no_commits": head == baseline_git["head"],
        "staged_empty": not staged,
        "tracked_modified_paths_unchanged": tracked_modified == baseline_git["tracked_modified"],
        "tracked_modified_count_15": len(tracked_modified) == 15,
        "prior_untracked_preserved": not lost_untracked,
        "new_untracked_inside_declared_scope": not outside_scope,
        "v2_corpus_byte_identical": not v2_changed,
        "v2_corpus_file_count_unchanged": len(v2_files) == before["v2_corpus_file_count"],
        "c_freeze_12_unchanged": not c_freeze_mismatch,
        "frozen_inputs_unchanged": not frozen_changed,
        "product_parser_unchanged": frozen["backend/src/mktkb/ingestion/parsers/excel.py"]["r0"]
        == frozen["backend/src/mktkb/ingestion/parsers/excel.py"]["r1"],
        "authorized_changes_are_exactly_the_expected_set": authorized_changed == authorized_expected_changed,
        "v3_corpus_13_files": len(v3_files) == 13,
        "source_map_present": SOURCE_MAP.is_file(),
        "delivery_changed_exactly_V05_V06_plus_manifest": set(delivery_changed) == expected_changed_paths,
        "delivery_other_10_files_byte_identical_to_r0": set(delivery_unchanged_6) == expected_unchanged_paths,
    }
    payload = {
        "schema_version": "p2h2v3-preservation/v0.2-r1",
        "phase": "preservation-r1",
        "before_ref": str(BASELINE.relative_to(ROOT)).replace("\\", "/"),
        "git": {
            "branch": branch,
            "head": head,
            "staged": staged,
            "tracked_modified": tracked_modified,
            "tracked_modified_count": len(tracked_modified),
            "untracked_count": len(untracked),
            "new_untracked": new_untracked,
            "lost_untracked": lost_untracked,
            "new_untracked_outside_scope": outside_scope,
        },
        "v2_corpus": {"files": len(v2_files), "changed": v2_changed},
        "c_freeze_12": {"mismatch": c_freeze_mismatch, "checked": len(c_freeze)},
        "frozen_inputs": {"changed": frozen_changed, "checked": len(frozen), "per_file": frozen},
        "authorized_change_targets": authorized,
        "authorized_changed": sorted(authorized_changed),
        "delivery": {
            "file_count": len(v3_files),
            "changed": delivery_changed,
            "unchanged": delivery_unchanged_6,
            "files": v3_files,
        },
        "source_map": {"path": "docs/evaluation/p2-holdout-v3.source-map.json", "sha256": sha256_file(SOURCE_MAP), "bytes": SOURCE_MAP.stat().st_size} if SOURCE_MAP.is_file() else None,
        "checks": checks,
        "result": "PRESERVED" if all(checks.values()) else "VIOLATION",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "checks": checks,
                "result": payload["result"],
                "new_untracked_count": len(new_untracked),
                "untracked_count": len(untracked),
                "authorized_changed": sorted(authorized_changed),
                "delivery_changed": delivery_changed,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if payload["result"] == "PRESERVED" else 1


if __name__ == "__main__":
    sys.exit(main())
