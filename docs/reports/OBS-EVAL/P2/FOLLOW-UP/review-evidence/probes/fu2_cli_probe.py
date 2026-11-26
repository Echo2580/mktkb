"""Independent reviewer probe for P2 FU-2 (v3 `derive-cards` CLI surface & output-root guard).

Reviewer-authored; offline. Only `--help` and refuse-branch invocations, so no private input is
read: the output-root guard runs before any binding/evidence file is opened.

Usage:
    python fu2_cli_probe.py --root <CHECKOUT> --out <json>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

V3 = "tools/p2_h2_v3_controlled_execute.py"
V2 = "tools/p2_h2_controlled_execute.py"
DUMMY = Path(r"D:\mktkb-fu-review\probes\__nonexistent__")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--python", default=sys.executable)
    return parser.parse_args()


def _run(root: Path, python: str, argv: list[str]) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [python, "-X", "utf8", *argv],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    stdout = proc.stdout.strip()
    payload: Any = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            try:
                payload = json.loads(stdout.splitlines()[-1])
            except json.JSONDecodeError:
                payload = None
    return {
        "argv": argv,
        "exit": proc.returncode,
        "stdout_tail": stdout.splitlines()[-1] if stdout else "",
        "stdout_lines": len(stdout.splitlines()),
        "stderr_tail": (proc.stderr.strip().splitlines() or [""])[-1],
        "error_code": (payload or {}).get("error_code") if isinstance(payload, dict) else None,
        "command": (payload or {}).get("command") if isinstance(payload, dict) else None,
        "ok": (payload or {}).get("ok") if isinstance(payload, dict) else None,
        "payload": payload if isinstance(payload, dict) and len(json.dumps(payload)) < 4000 else None,
    }


def main() -> int:
    args = _args()
    root = Path(args.root).resolve()
    report: dict[str, Any] = {"probe": "reviewer-fu2-cli", "root": str(root), "cases": {}}

    report["cases"]["v3_help"] = _run(root, args.python, [V3, "--help"])
    report["cases"]["v3_derive_help"] = _run(root, args.python, [V3, "derive-cards", "--help"])
    report["cases"]["v2_help"] = _run(root, args.python, [V2, "--help"])
    report["cases"]["v2_derive_rejected"] = _run(root, args.python, [V2, "derive-cards", "--help"])
    report["cases"]["v3_no_args"] = _run(root, args.python, [V3])

    # Illegal output directories (must refuse before reading inputs; must not create anything).
    repo = str(root)
    illegal = {
        "repo_root_child": repo + r"\__review_derive_out__",
        "repo_root_dotdot": repo + r"\tmp-review-x\..\__review_derive_out__",
        "repo_root_case_variant": repo + r"\DOCS\__review_derive_out__",
        "repo_var": repo + r"\var\__review_derive_out__",
        "repo_trailing_slash": repo + r"\__review_derive_out_2__" + "/",
    }
    for label, out_dir in illegal.items():
        argv = [
            V3,
            "derive-cards",
            "--binding",
            str(DUMMY / "binding.json"),
            "--run-index",
            "0",
            "--evidence-dir",
            str(DUMMY / "evidence"),
            "--case-plan",
            str(DUMMY / "case-plan.json"),
            "--evidence-key-file",
            str(DUMMY / "evidence.key"),
            "--out-dir",
            out_dir,
        ]
        result = _run(root, args.python, argv)
        created = Path(out_dir).exists()
        result["created"] = created
        result["out_dir"] = out_dir
        report["cases"][f"illegal_out_dir::{label}"] = result
    report["repo_entries_after"] = sorted(p.name for p in root.iterdir())

    # A legal (out-of-repo) output dir is NOT rejected by the guard: it must move on to the
    # input checks and fail with the input-specific fixed code instead.
    legal = r"D:\mktkb-fu-review\runs\fu2-legal-out"
    if Path(legal).exists():
        for child in sorted(Path(legal).rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        Path(legal).rmdir()
    legal_result = _run(
        root,
        args.python,
        [
            V3,
            "derive-cards",
            "--binding",
            str(DUMMY / "binding.json"),
            "--run-index",
            "0",
            "--evidence-dir",
            str(DUMMY / "evidence"),
            "--case-plan",
            str(DUMMY / "case-plan.json"),
            "--evidence-key-file",
            str(DUMMY / "evidence.key"),
            "--out-dir",
            legal,
        ],
    )
    legal_result["created"] = Path(legal).exists()
    report["cases"]["legal_out_dir_with_missing_input"] = legal_result

    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name, case in report["cases"].items():
        print(
            f"{name}: exit={case['exit']} code={case.get('error_code')} "
            f"created={case.get('created')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
