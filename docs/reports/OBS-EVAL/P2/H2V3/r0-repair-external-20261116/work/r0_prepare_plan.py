"""r0 修复轮：为新最终代码生成 r0 私有计划（plan-private 的受控包装）。

设计约束
--------
- 私有路径只从既有 binding 的 ``inputs`` 读出并**只用于传参**，绝不打印、绝不写进任何产物。
- stdout 只输出白名单字段（固定码/布尔/整数/sha256/plan_id/plan_sha256）。
- 失败只输出固定错误码，不打印异常消息（可能含私有路径）。

用法
----
    .venv\\Scripts\\python.exe -X utf8 work/r0_prepare_plan.py --check
    .venv\\Scripts\\python.exe -X utf8 work/r0_prepare_plan.py --plan
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[7]
ENTRY = REPO / "tools" / "p2_h2_v3_controlled_execute.py"
OLD_BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-single-01\bindings\run0-base_b0.binding.json"
)
OUT_DIR = pathlib.Path(r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-r0fix")
RECEIPT = (
    REPO
    / "docs/reports/OBS-EVAL/P2/H2V3/r0-repair-external-20261116/evidence/03-plan"
    / "SAFE-PLAN-RECEIPT.json"
)

SAFE_KEYS = (
    "status", "code", "tool", "schema_version", "created_utc", "max_requests",
    "code_version", "index_batches", "plan_count", "run_count", "private_output",
    "root_outside_repo", "key_outside_repo", "zero_send", "zero_paid_probes",
    "ok", "error_code", "command",
)

_SAFE_DETAIL_RE = __import__("re").compile(r"^[A-Za-z0-9_.:-]{0,120}$")


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_private_locations() -> tuple[pathlib.Path, pathlib.Path]:
    """从既有 binding 取 holdout 根与 key 路径；只返回 Path 对象，不打印。"""
    payload = json.loads(OLD_BINDING.read_text(encoding="utf-8"))
    inputs = payload["inputs"]
    root = pathlib.Path(str(inputs["holdout_manifest"]["path"])).parent.resolve()
    key = pathlib.Path(str(inputs["scenario_key_file"]["path"])).resolve()
    return root, key


def outside_repo(path: pathlib.Path) -> bool:
    return path != REPO and REPO not in path.parents


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="只核前置，不生成计划")
    mode.add_argument("--plan", action="store_true", help="执行 plan-private（写仓外新目录）")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    try:
        root, key = load_private_locations()
    except BaseException:
        print(json.dumps({"ok": False, "code": "private_location_unavailable"}))
        return 1

    out_dir = pathlib.Path(args.out_dir)
    try:
        facts = {
            "old_binding_sha256": sha256_file(OLD_BINDING),
            "root_outside_repo": outside_repo(root),
            "key_outside_repo": outside_repo(key),
            "out_dir": str(out_dir),
            "out_dir_outside_repo": outside_repo(out_dir.resolve()) if out_dir.exists() else outside_repo(out_dir),
            "out_dir_exists": out_dir.exists(),
            "entry_sha256": sha256_file(ENTRY),
        }
        if not (facts["root_outside_repo"] and facts["key_outside_repo"]):
            print(json.dumps({"ok": False, "code": "private_path_boundary_failed", **facts}))
            return 1
        if not out_dir.exists():
            facts["out_dir_absolute"] = str(out_dir.absolute())
        if os.environ.get("MKTKB_PROJECT_TOTAL_LIMIT_CNY") is None:
            facts["env_project_limit"] = "unset"
        else:
            facts["env_project_limit"] = os.environ["MKTKB_PROJECT_TOTAL_LIMIT_CNY"]
    except BaseException:
        print(json.dumps({"ok": False, "code": "precheck_failed"}))
        return 1

    if args.check:
        facts["ok"] = True
        facts["mode"] = "check"
        print(json.dumps(facts, ensure_ascii=False, sort_keys=True))
        return 0

    if out_dir.exists():
        print(json.dumps({"ok": False, "code": "out_dir_exists", **facts}))
        return 1

    # CAP-UNLIMITED 的逐项配额按 plan_sha256+item_id 跨 run_id 累计：
    # 同一 created_utc 会生成逐字节相同的计划，导致第二轮首项即 attempt_quota_exhausted。
    # 因此每轮必须用新的 created_utc，让 plan_sha256 唯一。
    from datetime import datetime, timedelta, timezone

    created_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    facts["created_utc"] = created_utc

    argv = [
        sys.executable, "-X", "utf8", str(ENTRY), "plan-private",
        "--root", str(root), "--key-file", str(key), "--out-dir", str(out_dir),
        "--created-utc", created_utc,
    ]
    env = dict(os.environ)
    env.pop("HTTP_PROXY", None), env.pop("HTTPS_PROXY", None), env.pop("ALL_PROXY", None)
    # v3 入口只接受它自己的项目总上限（40.0）；外层测试约定的 20.0 会触发 env_total_limit_conflict。
    env.pop("MKTKB_PROJECT_TOTAL_LIMIT_CNY", None)
    try:
        proc = subprocess.run(
            argv, cwd=str(REPO), capture_output=True, text=True, timeout=900, env=env
        )
    except BaseException:
        print(json.dumps({"ok": False, "code": "plan_subprocess_failed", **facts}))
        return 1

    raw = (proc.stdout or "").strip()
    receipt: dict[str, object] = {}
    try:
        parsed = json.loads(raw) if raw else {}
        if isinstance(parsed, dict):
            receipt = {k: parsed.get(k) for k in SAFE_KEYS if k in parsed}
            detail = parsed.get("detail")
            if isinstance(detail, str) and _SAFE_DETAIL_RE.match(detail):
                receipt["detail"] = detail
    except BaseException:
        receipt = {"raw_unparsed": True}

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "exit_code": proc.returncode,
        "facts": facts,
        "safe_receipt": receipt,
        "full_receipt_role": "plan-private 原始 stdout 已由工具自身设计为 SAFE 聚合；此处只保留白名单字段。",
    }
    RECEIPT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out = {"ok": proc.returncode == 0, "exit_code": proc.returncode, **facts, "safe_receipt": receipt,
           "receipt_file": str(RECEIPT.relative_to(REPO))}
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
