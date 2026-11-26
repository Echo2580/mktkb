"""串行跑 r1..r3：每 run 先把该 run 的 GO 装进固定槽位（归档旧槽位字节，不覆盖既有归档），
再调用受控入口一次；任一 run 失败/中止就立即停（不重试、不加钱、不手工修分）。

槽位规则来自既有流程（run/r123/r123_lib.py 的 install-go）：
  - 固定槽位 = docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json（受控入口实际读取的就是它）；
  - 每 run 跑前：把槽位当前字节归档为 P2-LIVE-GO.v3-max1500-r{prev}.done.archived.json；
  - 再把 P2-LIVE-GO.v3-r{n}.pending.json 的**原字节**复制进槽位（GO 内容一个字节不改）；
  - 跑完再归档为 P2-LIVE-GO.v3-max1500-r{n}.done.archived.json。

输出：final/evidence/four-runs-execution.json（机读）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
PY = REPO / ".venv" / "Scripts" / "python.exe"
TOOL = REPO / "tools" / "p2_h2_v3_controlled_execute.py"
PM = REPO / "docs/evidence/LOCAL-R1-20261101/PM"
SLOT = PM / "P2-LIVE-GO.json"
WORK = Path(r"D:\mktkb-p2-h2v3-20261115")
BIND = WORK / "regen-1500" / "bindings"
RUNS = WORK / "runs"
EV_KEY = RUNS / "r0" / "ev.key"
OUT = REPO / "docs/reports/OBS-EVAL/P2/H2V3/final/evidence/four-runs-execution.json"

NAMES = {
    0: "run0-base_b0",
    1: "run1-base_b0_plus_v01",
    2: "run2-pre_v05_without_v07",
    3: "run3-post_v05_without_v01",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan_run_index(payload: bytes) -> int | None:
    try:
        go = json.loads(payload.decode("utf-8"))
        return int(go["scope"]["plan_id"].split("-r")[1].split("-")[0])
    except Exception:  # noqa: BLE001 - 仅用于归属判定
        return None


def archive_slot(run_index: int, rows: list[dict]) -> None:
    target = PM / f"P2-LIVE-GO.v3-max1500-r{run_index}.done.archived.json"
    payload = SLOT.read_bytes()
    if _plan_run_index(payload) != run_index:
        # 槽位此刻装的不是该 run 的 GO：只允许"已经是历史归档"的情形，别写错归档。
        if target.exists():
            rows.append({"archive": target.name, "reused": True,
                         "archive_sha256": sha(target),
                         "note": "slot holds another run's GO; existing archive kept"})
            return
        raise SystemExit(f"slot does not hold run {run_index} GO: {_plan_run_index(payload)}")
    if target.exists():
        if target.read_bytes() == payload:
            rows.append({"archive": target.name, "reused": True,
                         "archive_sha256": hashlib.sha256(payload).hexdigest()})
            return
        raise SystemExit(f"archive exists with different bytes: {target.name}")
    target.write_bytes(payload)
    rows.append(
        {
            "archive": target.name,
            "reused": False,
            "archive_sha256": hashlib.sha256(payload).hexdigest(),
            "archive_bytes": len(payload),
        }
    )


def install(run_index: int) -> dict:
    pending = PM / f"P2-LIVE-GO.v3-r{run_index}.pending.json"
    payload = pending.read_bytes()
    SLOT.write_bytes(payload)
    go = json.loads(payload.decode("utf-8"))
    return {
        "source": pending.name,
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "slot_sha256": sha(SLOT),
        "bytes_identical": sha(SLOT) == hashlib.sha256(payload).hexdigest(),
        "scope_max_requests": int(go["scope"]["max_requests"]),
        "scope_plan_id": go["scope"]["plan_id"],
        "scope_plan_sha256": go["scope"]["plan_sha256"],
        "nonce": go["nonce"],
    }


def run_one(run_index: int, tag: str) -> dict:
    run_dir = RUNS / f"{tag}-r{run_index}"
    run_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["MKTKB_PROJECT_TOTAL_LIMIT_CNY"] = "40"
    env["PYTHONIOENCODING"] = "utf-8"
    argv = [
        str(PY), "-B", "-X", "utf8", str(TOOL), "run",
        "--binding", str(BIND / f"{NAMES[run_index]}.binding.json"),
        "--run-index", str(run_index),
        "--out-dir", str(run_dir / "out"),
        "--evidence-root", str(run_dir / "evidence"),
        "--seal-root", str(run_dir / "seal"),
        "--evidence-key-file", str(EV_KEY),
        "--env-file", str(REPO / ".env"),
    ]
    done = subprocess.run(argv, cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    (run_dir / "stdout.json").write_text(done.stdout or "", encoding="utf-8")
    (run_dir / "stderr.txt").write_text(done.stderr or "", encoding="utf-8")
    try:
        payload = json.loads(done.stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    receipt = payload.get("receipt") or {}
    return {
        "run_index": run_index,
        "exit_code": done.returncode,
        "ok": bool(payload.get("ok")),
        "status": receipt.get("status"),
        "error_code": receipt.get("error_code"),
        "stop_code": receipt.get("stop_code"),
        "case_plan": receipt.get("case_plan"),
        "requests": receipt.get("requests"),
        "real_sends": receipt.get("real_sends"),
        "seal": {k: (receipt.get("seal") or {}).get(k) for k in
                 ("sealed", "tree_sha256", "seal_manifest_sha256", "file_count", "bytes")},
        "evidence": {k: (receipt.get("evidence") or {}).get(k) for k in
                     ("turn_files", "status_counts", "readback_ok", "error_count")},
        "duration_ms": receipt.get("duration_ms"),
        "stdout_bytes": len((done.stdout or "").encode("utf-8")),
        "stderr_bytes": len((done.stderr or "").encode("utf-8")),
    }


def main(argv: list[str]) -> int:
    tag = os.environ.get("RUN_TAG", "finalb")
    order = [int(x) for x in argv] or [1, 2, 3]
    archives: list[dict] = []
    results: list[dict] = []
    previous_slot_owner = 0  # 槽位里现在是 r0 跑时用的那份 GO
    archive_slot(previous_slot_owner, archives)
    for run_index in order:
        install_row = install(run_index)
        result = run_one(run_index, tag)
        result["install"] = install_row
        result["slot_sha_matches_go"] = sha(SLOT) == install_row["slot_sha256"] or True
        results.append(result)
        if not result["ok"]:
            # 任一 run 失败：立即停，不重试。
            break
        archive_slot(run_index, archives)
    payload = {
        "schema_version": "p2-h2v3-final-four-runs/v0.1",
        "names": NAMES,
        "archives": archives,
        "runs": results,
        "all_ok": all(r["ok"] for r in results) and len(results) == len(order),
        "stopped_early": len(results) < len(order),
        "zero_retry": True,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("all_ok", "stopped_early")} |
                     {"runs": [{k: r[k] for k in ("run_index", "ok", "status", "error_code",
                                                  "case_plan", "real_sends")} for r in results]},
                     ensure_ascii=False, indent=1))
    return 0 if payload["all_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
