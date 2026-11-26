"""FU-2 复现：旧正式入口（v2 ``recompute``）拒绝 v3 单 run binding。

零真实模型调用、零 OCR、零出站；仅合成数据。凭据源被重定向到**合成** env 文件，
仓库 ``.env`` 从不读取（脚本不引用、不打开它）。

用法（仓库根运行）::

    .venv\\Scripts\\python.exe -B docs/reports/OBS-EVAL/P2/FOLLOW-UP/FU2/evidence/scripts/repro_v3_reject.py \
        --out docs/reports/OBS-EVAL/P2/FOLLOW-UP/FU2/evidence/reproduction.json

输出只有固定码/退出码/计数，不含任何路径。
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

V3_KEYS = (
    "schema_version", "created_utc", "fixture_kind", "execution_mode", "holdout_root",
    "anchor_business_date", "business_date", "code_version", "config_sha256", "config",
    "dataset", "inputs", "runs", "binding_sha256",
)
RUN_KEYS = (
    "run_index", "scenario_id", "run_id", "plan_id", "plan_sha256", "plan_file",
    "plan_file_sha256", "business_date", "rag_business_date", "manifest_business_date",
    "case_count", "turn_count", "total_requests", "worst_case_cny", "reserve_peak_cny",
    "ingest_batches", "ingest_sources", "scenario_binding", "evidence_bindings",
    "contract_validate_run", "source_map",
)


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "tools" / "p2_h2_controlled_execute.py").is_file():
            return parent
    return Path.cwd()


def _mask(item: str, work: Path) -> str:
    """公开记录口径：工作区内的合成路径只留角色，不留扩展名/目录名。"""
    text = str(item)
    prefix = str(work)
    if not text.startswith(prefix):
        return text
    name = Path(text).name.lower()
    if name == ".env" or name.startswith(".env."):
        role = "env-file"
    elif name.endswith(".key"):
        role = "key-file"
    elif name.endswith(".fernet"):
        role = "ciphertext"
    elif name.endswith(".json"):
        role = "json"
    else:
        role = "dir"
    return "<TMP:repro-workspace:" + role + ">"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--repo", default=None)
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else repo_root()
    os.environ.setdefault("MKTKB_PROJECT_TOTAL_LIMIT_CNY", "40.0")
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.path.insert(0, str(repo / "backend" / "src"))
    from cryptography.fernet import Fernet

    work = Path(tempfile.mkdtemp(prefix="p2-fu2-repro-"))
    try:
        spec = importlib.util.spec_from_file_location(
            "_p2_fu2_repro_v2", repo / "tools" / "p2_h2_controlled_execute.py"
        )
        assert spec is not None and spec.loader is not None
        entry = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = entry
        spec.loader.exec_module(entry)

        auth = work / "auth" / ".env"
        auth.parent.mkdir(parents=True, exist_ok=True)
        auth.write_text(
            "\n".join(
                [
                    "MKTKB_MODEL_API_KEY=SYNTHETIC-FU2-CHAT",
                    "MKTKB_MODEL_BASE_URL=https://api.deepseek.com",
                    "MKTKB_MODEL_NAME=deepseek-flash",
                    "DASHSCOPE_API_KEY=SYNTHETIC-FU2-DASHSCOPE",
                    "MKTKB_OCR_SECRET_ID=SYNTHETIC-FU2-OCR",
                    "MKTKB_OCR_SECRET_KEY=SYNTHETIC-FU2-OCR",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        entry.AUTHORIZED_ENV_PATH = auth

        holdout = work / "holdout-root"
        holdout.mkdir(parents=True, exist_ok=True)
        (holdout / "manifest.fernet").write_bytes(b"synthetic-holdout-manifest")
        holdout_key = work / "holdout.key"
        holdout_key.write_bytes(Fernet.generate_key())
        evidence_key = work / "evidence.key"
        evidence_key.write_bytes(Fernet.generate_key())

        document = {
            "schema_version": "p2-h2v3-controlled-runbinding/v0.1",
            "created_utc": "2026-11-15T05:00:00+08:00",
            "fixture_kind": "live_h2",
            "execution_mode": "live",
            "holdout_root": str(holdout),
            "anchor_business_date": "2026-10-15",
            "business_date": "2026-11-15",
            "code_version": "0" * 64,
            "config_sha256": "1" * 64,
            "config": {},
            "dataset": {
                "case_count": 30,
                "total_turns": 36,
                "scenario_counts": {
                    "base_b0": 12,
                    "base_b0_plus_v01": 8,
                    "pre_v05_without_v07": 5,
                    "post_v05_without_v01": 5,
                },
                "manifest_sha256": "2" * 64,
                "anchor_business_date": "2026-10-15",
                "dataset_version": "P2-HOLDOUT-v3-synthetic",
                "label_version": "v0.2",
                "suite": "holdout",
            },
            "inputs": {},
            "runs": [
                {
                    "run_index": 0,
                    "scenario_id": "base_b0",
                    "run_id": "p2-h2v3-synthetic-r0-base_b0",
                    "plan_id": "P2-H2V3-SYNTHETIC-r0-base_b0",
                    "plan_sha256": "3" * 64,
                    "plan_file": str(work / "plan.json"),
                    "plan_file_sha256": "4" * 64,
                    "business_date": "2026-11-15",
                    "rag_business_date": "2026-11-15",
                    "manifest_business_date": "2026-11-15",
                    "case_count": 12,
                    "turn_count": 14,
                    "total_requests": 185,
                    "worst_case_cny": 0.5,
                    "reserve_peak_cny": 0.5,
                    "ingest_batches": 9,
                    "ingest_sources": 7,
                    "scenario_binding": {},
                    "evidence_bindings": {},
                    "contract_validate_run": {"ok": True},
                    "source_map": {
                        "schema_version": "p2-holdout-source-map/v0.2",
                        "code_count": 12,
                        "sha256": "5" * 64,
                    },
                }
            ],
            "binding_sha256": "6" * 64,
        }
        assert set(document) == set(V3_KEYS) and set(document["runs"][0]) == set(RUN_KEYS)
        binding = work / "v3-single-run.binding.json"
        binding.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

        command = [
            "recompute",
            "--env-file", str(auth),
            "--run-binding", str(binding),
            "--run-index", "0",
            "--evidence-dir", str(work / "evidence"),
            "--evidence-key-file", str(evidence_key),
            "--case-plan", str(work / "case-plan.json"),
            "--holdout-root", str(holdout),
            "--holdout-key-file", str(holdout_key),
            "--project-total-limit-cny", "40",
        ]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = entry.main(command)
        lines = [line for line in out.getvalue().splitlines() if line.strip()]
        payload = json.loads(lines[-1]) if lines else None
        evidence = {
            "schema_version": "p2-fu2-reproduction/v0.1",
            "case": "old formal entry (v2 recompute) vs synthetic v3 single-run binding",
            "command": [".venv/Scripts/python.exe", "tools/p2_h2_controlled_execute.py"]
            + [_mask(item, work) for item in command],
            "exit_code": code,
            "stdout_lines": len(lines),
            "stderr_lines": len([line for line in err.getvalue().splitlines() if line.strip()]),
            "payload": payload,
            "repo_env_read": False,
            "real_model_calls": 0,
            "outbound": 0,
        }
        target = Path(args.out)
        if not target.is_absolute():
            target = repo / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            shown = target.relative_to(repo).as_posix()
        except ValueError:
            shown = target.name
        print(json.dumps({"ok": True, "out": shown, "exit_code": code, "error_code": (payload or {}).get("error_code")}, ensure_ascii=False))
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
