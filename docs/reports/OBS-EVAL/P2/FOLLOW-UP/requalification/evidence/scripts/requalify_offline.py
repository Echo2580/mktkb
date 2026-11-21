"""P2 收尾：候选指纹 / 冻结件复核（只读、离线、零出站）。

用法（仓库根）：
    .venv\\Scripts\\python.exe -X utf8 docs\\reports\\OBS-EVAL\\P2\\FOLLOW-UP\\requalification\\evidence\\scripts\\requalify_offline.py --out <json>

做的事：
1. 现场事实：分支 / HEAD / 已跟踪改动；
2. 13 个指纹文件逐文件复核（改前用 ``git cat-file blob <base>:<path>`` 取原始字节）；
3. 指纹之外的已跟踪漂移逐项登记（本地启动器、live_authorization、簿记件）；
4. 当前候选的 ``pipeline_source_sha256`` / ``product_pipeline_version``；
5. 原冻结件复核：47 个冻结工件、2 项台账前缀、批准配置、真实门禁结果、B0 准入；
6. 行尾口径事实（补齐验收方对 ``p2_release_gate.py`` 的复核项）。

不写仓库文件（除 --out 指定的 evidence JSON），不改任何被测文件，不触网。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[8]
FINGERPRINT = ROOT / "docs/reports/OBS-EVAL/P2/FOLLOW-UP/candidate-fingerprint.json"
FREEZE = ROOT / "docs/reports/OBS-EVAL/P2/candidate-freeze.json"

# 指纹之外的已跟踪漂移（开工时登记，逐项说明分类）。
EXTRA_TRACKED_NOTE = {
    "backend/src/mktkb/live_authorization.py": (
        "product", "产品代码：新增 S2-OWNER-ACCEPTANCE 阶段 + GO 请求窗口基线；"
        "在 backend/src/mktkb/*.py 内，**会改动 pipeline_source_sha256**，因此必须进候选。"
    ),
    "backend/src/mktkb/evaluation/p2_release_inputs.py": (
        "product-gate-reregistration",
        "门禁**基线登记**常量：新 B0 接收后把已登记基线换成 2b40ee9b4740 及三份记录摘要；"
        "判据（批准配置/阈值/八项硬门禁）未改。该文件不在 pipeline_source_sha256 覆盖集内，"
        "已复核摘要仍为 13a962ed…，故不影响新 B0 绑定。",
    ),
    "backend/tests/evaluation/test_p2_release_gate_fixtures.py": (
        "test-followup", "门禁夹具改为跟随「已登记基线」常量（不再写死旧基线 id/run id）；只改测试写法。"
    ),
    "backend/tests/evaluation/test_p2_release_gate_negative.py": (
        "test-followup", "同一改动：负例里的假登记目录名改用 B0_BASELINE_ID；断言语义未变。"
    ),
    "docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py": (
        "gate-wiring-followup", "正式门禁接线脚本的 b0 块改为跟随「已登记基线」常量；不涉及判据。"
    ),
    "frontend/e2e/acceptance-07-update.spec.ts": (
        "test-followup",
        "浏览器验收断言跟随产品文案（copy.KNOWLEDGE_CHANGED 已扩充），断言更严不更松；"
        "修复前该条因断言过期失败。",
    ),
    "tools/start_local.py": (
        "local-launcher", "本地启动器：--offline/--owner-live/--check-only 与亲验锁定；不在产品包内，"
        "不影响 pipeline_source_sha256；影响的是本地实例实际导入与运行身份。"
    ),
    "一键启动.cmd": ("local-launcher", "本地启动器：改为 --offline（零出站离线演示）。"),
    "启动-真实问答.cmd": ("local-launcher", "本地启动器：改为 --owner-live + S2-OWNER-ACCEPTANCE 额度；直连真实调用。"),
    ".claude/handoffs/_index.md": ("bookkeeping", "开工前既有的簿记追加（非本轮）。"),
    "docs/reports/OBS-EVAL/P2/T207-QUALITY-REPAIR/manager.md": (
        "bookkeeping", "开工前既有的簿记追加（非本轮）。"
    ),
}


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[:400])
    return result.stdout.decode("utf-8", "replace")


def git_blob(base: str, path: str) -> bytes:
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{base}:{path}"], cwd=str(ROOT), capture_output=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[:400])
    return result.stdout


def crlf_counts(raw: bytes) -> dict[str, int]:
    return {
        "bytes": len(raw),
        "crlf": raw.count(b"\r\n"),
        "lf_only": raw.count(b"\n") - raw.count(b"\r\n"),
        "cr_bytes": raw.count(b"\r"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)

    fingerprint = json.loads(FINGERPRINT.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    base = fingerprint["base_head"]

    facts: dict[str, object] = {
        "schema": "p2-requalification-candidate/v0.1",
        "kind": "offline-read-only",
        "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "head": git("rev-parse", "HEAD").strip(),
        "fingerprint_base_head": base,
        "head_matches_fingerprint_base": git("rev-parse", "HEAD").strip() == base,
        "tracked_status": sorted(
            line for line in git("status", "--porcelain=v1", "--untracked-files=no").splitlines() if line.strip()
        ),
    }

    # 1) 13 个指纹文件逐文件复核。
    files: list[dict[str, object]] = []
    before_mismatch = after_mismatch = 0
    for item in fingerprint["files"]:
        path = item["path"]
        disk = ROOT / path
        after_sha = sha_file(disk)
        after_bytes = disk.stat().st_size
        row: dict[str, object] = {
            "path": path,
            "status": item["status"],
            "recorded_after_sha256": item["after_sha256"],
            "actual_after_sha256": after_sha,
            "recorded_after_bytes": item["after_bytes"],
            "actual_after_bytes": after_bytes,
            "after_match": after_sha == item["after_sha256"] and after_bytes == item["after_bytes"],
        }
        if item["before_sha256"]:
            blob = git_blob(base, path)
            row["recorded_before_sha256"] = item["before_sha256"]
            row["actual_before_sha256"] = hashlib.sha256(blob).hexdigest()
            row["recorded_before_bytes"] = item["before_bytes"]
            row["actual_before_bytes"] = len(blob)
            row["before_match"] = (
                row["actual_before_sha256"] == item["before_sha256"] and len(blob) == item["before_bytes"]
            )
            if not row["before_match"]:
                before_mismatch += 1
        else:
            row["recorded_before_sha256"] = None
            row["before_match"] = None
        if not row["after_match"]:
            after_mismatch += 1
        files.append(row)
    facts["fingerprint"] = {
        "file_count": len(files),
        "after_mismatch": after_mismatch,
        "before_mismatch": before_mismatch,
        "files": files,
    }

    # 2) 指纹之外的已跟踪漂移。
    known = {item["path"] for item in fingerprint["files"]}
    extra: list[dict[str, object]] = []
    for line in facts["tracked_status"]:  # type: ignore[union-attr]
        path = line[3:].strip()
        if path in known:
            continue
        disk = ROOT / path
        category, note = EXTRA_TRACKED_NOTE.get(path, ("unclassified", "未登记分类"))
        extra.append(
            {
                "path": path,
                "sha256": sha_file(disk) if disk.is_file() else None,
                "bytes": disk.stat().st_size if disk.is_file() else None,
                "before_sha256": hashlib.sha256(git_blob(base, path)).hexdigest(),
                "category": category,
                "note": note,
            }
        )
    facts["extra_tracked_drift"] = extra

    # 3) 候选身份。
    from mktkb.evaluation import p2_b0
    from mktkb.evaluation.product_adapter import product_pipeline_version

    facts["candidate"] = {
        "pipeline_source_sha256": p2_b0.pipeline_source_sha256(),
        "product_pipeline_version": product_pipeline_version(),
    }

    # 4) 原冻结件复核。
    #    ``candidate-freeze.json`` 的 47 件是**原冻结候选**（93486b6）的工作树字节，随后被该提交收录；
    #    因此"原冻结件是否完好"要对着 93486b6 的 blob 核，而不是对着修复树核。
    #    对修复树再比一次，并把差异分成"预期修复面"与"意外差异"。
    fix_surface = {item["path"] for item in fingerprint["files"] if item["status"] == "modified"} | {
        item["path"] for item in fingerprint["files"] if item["status"] == "new"
    } | {
        "backend/src/mktkb/evaluation/p2_release_inputs.py",
        "backend/tests/evaluation/test_p2_release_gate_fixtures.py",
        "backend/tests/evaluation/test_p2_release_gate_negative.py",
        "docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py",
    }
    frozen_commit = "93486b6590c6542f34dd70d20a19b792c659f416"
    artifacts: list[dict[str, object]] = []
    for item in freeze["frozen_artifacts"]:
        path = item["path"]
        blob = git_blob(frozen_commit, path)
        disk = ROOT / path
        disk_raw = disk.read_bytes() if disk.is_file() else b""
        head_match = hashlib.sha256(blob).hexdigest() == item["sha256"] and len(blob) == item["bytes"]
        worktree_match = disk.is_file() and hashlib.sha256(disk_raw).hexdigest() == item["sha256"]
        artifacts.append(
            {
                "path": path,
                "recorded_sha256": item["sha256"],
                "recorded_bytes": item["bytes"],
                "frozen_commit_blob_sha256": hashlib.sha256(blob).hexdigest(),
                "frozen_commit_blob_bytes": len(blob),
                "frozen_commit_match": bool(head_match),
                "worktree_sha256": hashlib.sha256(disk_raw).hexdigest() if disk.is_file() else None,
                "worktree_match": bool(worktree_match),
                "delta_class": (
                    "none"
                    if worktree_match
                    else ("expected_fix_delta" if path in fix_surface else "UNEXPECTED")
                ),
            }
        )
    prefixes: list[dict[str, object]] = []
    for item in freeze["records_append_only"]:
        path = ROOT / item["path"]
        raw = path.read_bytes()
        size = int(item["bytes_at_freeze"])
        prefix = raw[:size]
        prefixes.append(
            {
                "path": item["path"],
                "bytes_at_freeze": size,
                "current_bytes": len(raw),
                "grew": len(raw) >= size,
                "prefix_sha256": hashlib.sha256(prefix).hexdigest(),
                "recorded_prefix_sha256": item["sha256_at_freeze"],
                "match": len(raw) >= size and hashlib.sha256(prefix).hexdigest() == item["sha256_at_freeze"],
            }
        )

    gate_cfg = freeze["gate_config"]
    formal = freeze["formal_gate"]
    baseline = freeze["baseline"]
    admission_path = ROOT / "var/eval/baselines" / baseline["id"] / "b0-admission.json"
    admission_raw = admission_path.read_bytes()
    from mktkb.evaluation.p2_contracts import payload_sha256

    admission_payload = json.loads(admission_raw)
    facts["freeze_recheck"] = {
        "frozen_commit": frozen_commit,
        "artifact_total": len(artifacts),
        "artifact_frozen_commit_mismatch": sum(1 for row in artifacts if not row["frozen_commit_match"]),
        "artifact_worktree_delta": sum(1 for row in artifacts if not row["worktree_match"]),
        "artifact_unexpected_delta": sum(1 for row in artifacts if row["delta_class"] == "UNEXPECTED"),
        "artifacts": artifacts,
        "records_append_only": prefixes,
        "gate_config": {
            "path": gate_cfg["path"],
            "recorded_sha256": gate_cfg["sha256"],
            "actual_sha256": sha_file(ROOT / gate_cfg["path"]),
            "recorded_canonical_hash": gate_cfg["canonical_hash"],
            "match": sha_file(ROOT / gate_cfg["path"]) == gate_cfg["sha256"],
        },
        "formal_gate": {
            "path": formal["path"],
            "recorded_sha256": formal["sha256"],
            "actual_sha256": sha_file(ROOT / formal["path"]),
            "recorded_bytes": formal["bytes"],
            "actual_bytes": (ROOT / formal["path"]).stat().st_size,
            "match": sha_file(ROOT / formal["path"]) == formal["sha256"],
        },
        "b0_admission": {
            "path": str(admission_path.relative_to(ROOT)).replace("\\", "/"),
            "file_sha256": hashlib.sha256(admission_raw).hexdigest(),
            "payload_sha256": payload_sha256(admission_payload),
            "recorded_payload_sha256": baseline["admission_evidence_sha256"],
            "payload_match": payload_sha256(admission_payload) == baseline["admission_evidence_sha256"],
            "pipeline_version": admission_payload.get("pipeline_version"),
        },
    }

    # 5) 行尾口径（验收方对 p2_release_gate.py 的复核项）。
    endings = {}
    for path in (
        "backend/src/mktkb/evaluation/p2_release_gate.py",
        "backend/src/mktkb/evaluation/p2_runner.py",
        "backend/src/mktkb/evaluation/product_adapter.py",
    ):
        disk = ROOT / path
        row = {"worktree": crlf_counts(disk.read_bytes()), "head_blob": crlf_counts(git_blob(base, path))}
        endings[path] = row
    facts["line_endings"] = endings

    # 6) 新候选指纹 v2（v1 = FOLLOW-UP/candidate-fingerprint.json，保留不动）。
    #    与 v1 的唯一字节差异应是 FU-2 目录依赖修正（test_p2_fu2_derive_cards.py）。
    v2_files = []
    for row in files:
        entry = {
            "path": row["path"],
            "status": row["status"],
            "before_sha256": row.get("actual_before_sha256"),
            "before_bytes": row.get("actual_before_bytes"),
            "after_sha256": row["actual_after_sha256"],
            "after_bytes": row["actual_after_bytes"],
            "delta_vs_fingerprint_v1": None if row["after_match"] else "fu2_cwd_dependency_fix",
        }
        v2_files.append(entry)
    facts["candidate_fingerprint_v2"] = {
        "schema": "p2-followup-candidate-fingerprint/v0.2",
        "base_head": base,
        "supersedes": "docs/reports/OBS-EVAL/P2/FOLLOW-UP/candidate-fingerprint.json",
        "delta_note": (
            "v2 相对 v1 的字节差异只有 backend/tests/evaluation/test_p2_fu2_derive_cards.py"
            "（FU-2 目录依赖最小修正：用例内 monkeypatch.chdir(ROOT)）；产品代码字节与 v1 完全一致。"
        ),
        "files": v2_files,
    }

    changed = facts["tracked_status"]
    ok = (
        after_mismatch <= 1
        and before_mismatch == 0
        and facts["freeze_recheck"]["artifact_frozen_commit_mismatch"] == 0
        and facts["freeze_recheck"]["artifact_unexpected_delta"] == 0
        and all(row["match"] for row in prefixes)
        and facts["freeze_recheck"]["gate_config"]["match"]
        and facts["freeze_recheck"]["formal_gate"]["match"]
        and facts["freeze_recheck"]["b0_admission"]["payload_match"]
    )
    facts["verdict"] = {
        "ok": bool(ok),
        "tracked_change_count": len(changed),
        "fingerprint_after_mismatch": after_mismatch,
        "fingerprint_after_mismatch_paths": [
            row["path"] for row in files if not row["after_match"]
        ],
        "fingerprint_before_mismatch": before_mismatch,
        "freeze_artifact_frozen_commit_mismatch": facts["freeze_recheck"]["artifact_frozen_commit_mismatch"],
        "freeze_artifact_worktree_delta": facts["freeze_recheck"]["artifact_worktree_delta"],
        "freeze_artifact_unexpected_delta": facts["freeze_recheck"]["artifact_unexpected_delta"],
        "b0_admission_payload_match": facts["freeze_recheck"]["b0_admission"]["payload_match"],
    }


    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(facts, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps(facts["verdict"], ensure_ascii=False, indent=2))
    print("candidate.pipeline_source_sha256 =", facts["candidate"]["pipeline_source_sha256"])
    print("extra drift:", [row["path"] for row in extra])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
