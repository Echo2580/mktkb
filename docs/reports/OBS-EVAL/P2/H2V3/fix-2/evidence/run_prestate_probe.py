"""把 ``backend/src/mktkb`` 复制到临时目录，并**反向重建** fix-2 之前的两份源码，用于产出
“改前”复现证据（不修改工作区任何文件）。

重建后逐文件校验 SHA-256 等于 safety-fix 报告 §7.1 记录的改后值（= 本轮改前基线）；不等即失败。
随后在该 PYTHONPATH 下运行给定探针脚本。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
EVIDENCE = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence"
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"


def _load_reverse() -> tuple[dict[str, list[tuple[str, str]]], dict[str, str]]:
    spec = importlib.util.spec_from_file_location("build_fix_sha_for_prestate", EVIDENCE / "build_fix_sha.py")
    module = importlib.util.module_from_spec(spec)
    sys.argv = ["build_fix_sha"]
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    return module.REVERSE, module.BASELINE_SHA


def main(argv: list[str]) -> int:
    script = EVIDENCE / argv[0]
    out_name = argv[1]
    netguard_receipt = argv[2] if len(argv) > 2 else ""
    reverse, baseline = _load_reverse()

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mktkb-fix2-pre-"))
    src = tmp / "src"
    shutil.copytree(REPO / "backend" / "src" / "mktkb", src / "mktkb")
    rebuilt: list[dict[str, object]] = []
    for relative, replacements in reverse.items():
        name = pathlib.PurePosixPath(relative).name
        target = src / "mktkb" / "rag" / name
        text = target.read_bytes().decode("utf-8")
        uses_crlf = "\r\n" in text
        before = text.replace("\r\n", "\n")
        for new, old in replacements:
            if new not in before:
                raise SystemExit(f"reverse pattern missing in {relative}")
            before = before.replace(new, old, 1)
        if uses_crlf:
            before = before.replace("\n", "\r\n")
        target.write_bytes(before.encode("utf-8"))
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        rebuilt.append(
            {
                "path": relative,
                "rebuilt_sha256": digest,
                "expected_baseline_sha256": baseline[relative],
                "matches": digest == baseline[relative],
            }
        )
    if not all(bool(item["matches"]) for item in rebuilt):
        raise SystemExit("pre-state reconstruction mismatch: " + json.dumps(rebuilt, ensure_ascii=False))

    env = dict(os.environ)
    env["PYTHONPATH"] = str(src)
    env["P2_FIX2_SRC"] = str(src)
    env["PYTHONIOENCODING"] = "utf-8"
    args = [str(PYTHON), str(EVIDENCE / "netguard_script.py"), netguard_receipt or str(EVIDENCE / "netguard-pre.json"), str(script), out_name]
    completed = subprocess.run(args, cwd=str(REPO), env=env, capture_output=True, text=True, encoding="utf-8")
    payload = {
        "temp_root": str(tmp),
        "rebuilt_files": rebuilt,
        "all_match": all(bool(item["matches"]) for item in rebuilt),
        "probe_script": str(script.name),
        "probe_output": out_name,
        "netguard_receipt": netguard_receipt,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-2000:],
        "stderr": completed.stderr[-2000:],
    }
    (EVIDENCE / "reconstructed-pre-round.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({"all_match": payload["all_match"], "returncode": completed.returncode}, ensure_ascii=False))
    print(completed.stdout[-500:])
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
