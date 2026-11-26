"""v3 语料返工 R1：开工前基线（本目录新增文件的「之前」侧）。

与上一轮 ``../evidence/00-snapshot-before.py`` 的差别（上一轮出过「快照覆盖基线」的过程问题）：
- **幂等保护写死**：``00r1-baseline.json`` 已存在即拒绝执行，不提供「重建」开关；
- 明确把本轮的**授权改动面**单列成 ``authorized_change_targets``（L1 / 规格 / v3 语料 / manifest /
  source-map），保全核对只对「授权集合之外」的变动报违规，不把「本轮本该改的件」和「越界改动」混成一堆；
- 把产品解析器 ``ingestion/parsers/excel.py`` 与冻结分类器 ``p2_hard_evidence.py`` 都放进
  ``frozen_inputs``，用来证明「本轮没动产品代码」。

采集内容（只读、零调用）：
- git：分支 / HEAD / 暂存区 / tracked modified 全量 / untracked 全量
- v2 语料 ``fixtures/acceptance/**`` 逐文件 SHA256（35 个，必须一个字节都不变）
- C 冻结 12 与 ``axes/evidence/04-protected-hashes-before.json`` 逐项比对
- ``frozen_inputs``：本轮不得改的只读输入件（含产品解析器）
- ``authorized_change_targets``：本轮授权改动的件及其**改前** SHA256（旧值，供报告对照）
- ``r1_start_delivery``：``fixtures/acceptance-h2v3/**`` 13 个文件改前 SHA256

用法：``.venv\\Scripts\\python.exe 00r1-baseline.py``（只能跑一次；已存在即拒绝）
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[7]
OUT = HERE / "00r1-baseline.json"

C_FREEZE_BASELINE = ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/axes/evidence/04-protected-hashes-before.json"
V2_ROOT = ROOT / "fixtures/acceptance"
V3_ROOT = ROOT / "fixtures/acceptance-h2v3"

#: 本轮**不得**改动的只读输入件（产品代码、冻结判据、上游计划、v2 身份件）。
FROZEN_INPUTS = (
    "docs/superpowers/plans/2026-11-15-h2-v3-authoring-plan.md",
    "docs/evaluation/p2-stale-source-criterion-v1_1.md",
    "docs/evaluation/p2-holdout-v2.source-map.json",
    "fixtures/acceptance/manifest.json",
    "backend/src/mktkb/evaluation/p2_holdout_scenarios.py",
    "backend/src/mktkb/evaluation/p2_hard_evidence.py",
    "backend/src/mktkb/ingestion/parsers/excel.py",
    "backend/src/mktkb/retrieval/index.py",
    "backend/src/mktkb/retrieval/tokenize.py",
    "backend/src/mktkb/rag/chunking.py",
    "backend/src/mktkb/rag/retrieval.py",
)

#: 本轮**授权**改动的件（改前值必须留档，否则「旧 SHA 对照」无从谈起）。
AUTHORIZED_CHANGE_TARGETS = (
    "docs/evaluation/p2-source-lifecycle-v1.json",
    "docs/superpowers/plans/2026-11-15-h2-v3-corpus-modification-spec.md",
    "docs/evaluation/p2-holdout-v3.source-map.json",
    "fixtures/acceptance-h2v3/manifest.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True).stdout.decode("utf-8", "replace")


def inventory(root: Path) -> dict:
    return {
        str(path.relative_to(root)).replace("\\", "/"): {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def main() -> int:
    if OUT.exists():
        raise SystemExit(
            f"{OUT.name} 已存在：R1 基线只采一次（上一轮的教训：重复采集会把『之前』覆盖成『之后』）。"
            "本脚本**不**提供重建开关；核对该文件后继续。"
        )
    status = git("status", "--porcelain").splitlines()
    tracked_modified = sorted(line[3:] for line in status if line[:2].strip() not in ("??", ""))
    untracked = sorted(line[3:] for line in status if line[:2] == "??")
    baseline = json.loads(C_FREEZE_BASELINE.read_text(encoding="utf-8"))["c_freeze_12"]
    c_freeze_now = {rel: sha256(ROOT / rel) for rel in sorted(baseline)}
    payload = {
        "schema_version": "p2h2v3-corpus-r1-snapshot/v0.1",
        "phase": "before-r1",
        "role": "v3 语料返工 R1（普通开发）",
        "why_r1": "上一轮判 PARTIAL：V05/V06 的 失效日期 整列为空 ⇒ 产品 _find_header_index 把数据行当表头 ⇒ 7 条 target 不可对齐。经理裁定：暂缓修产品解析器，改数据侧用显式哨兵值。",
        "capture_note": "单次采集；脚本内 已存在即拒绝。本轮所有写入都发生在该文件落盘之后。",
        "git": {
            "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
            "head": git("rev-parse", "HEAD").strip(),
            "staged": [line for line in git("diff", "--cached", "--name-only").splitlines() if line.strip()],
            "tracked_modified": tracked_modified,
            "tracked_modified_count": len(tracked_modified),
            "untracked": untracked,
            "untracked_count": len(untracked),
        },
        "v2_corpus": inventory(V2_ROOT),
        "v2_corpus_file_count": len(inventory(V2_ROOT)),
        "c_freeze_12_baseline_ref": str(C_FREEZE_BASELINE.relative_to(ROOT)).replace("\\", "/"),
        "c_freeze_12": {
            rel: {"expected": baseline[rel], "actual": c_freeze_now[rel], "equal": c_freeze_now[rel] == baseline[rel]}
            for rel in sorted(baseline)
        },
        "c_freeze_12_mismatch_count": sum(1 for rel in baseline if c_freeze_now[rel] != baseline[rel]),
        "frozen_inputs": {rel: {"bytes": (ROOT / rel).stat().st_size, "sha256": sha256(ROOT / rel)} for rel in FROZEN_INPUTS},
        "authorized_change_targets": {
            rel: {"bytes": (ROOT / rel).stat().st_size, "sha256": sha256(ROOT / rel)}
            for rel in AUTHORIZED_CHANGE_TARGETS
            if (ROOT / rel).is_file()
        },
        "r1_start_delivery": inventory(V3_ROOT),
        "r1_start_delivery_file_count": len(inventory(V3_ROOT)),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "phase": payload["phase"],
                "branch": payload["git"]["branch"],
                "head": payload["git"]["head"],
                "staged": len(payload["git"]["staged"]),
                "tracked_modified_count": payload["git"]["tracked_modified_count"],
                "untracked_count": payload["git"]["untracked_count"],
                "v2_corpus_file_count": payload["v2_corpus_file_count"],
                "c_freeze_mismatch": payload["c_freeze_12_mismatch_count"],
                "r1_start_delivery_file_count": payload["r1_start_delivery_file_count"],
                "out": str(OUT),
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if payload["c_freeze_12_mismatch_count"] == 0 and not payload["git"]["staged"] else 1


if __name__ == "__main__":
    sys.exit(main())
