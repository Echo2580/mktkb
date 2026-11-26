"""Independent reviewer probe for P2 FU-4 (public-layer path redaction).

Reviewer-authored, offline. Three synthetic samples are pushed through
  (a) the public helper API `mktkb.evaluation.p2_safe_output`, and
  (b) the *real* public exit of both controlled H2 CLIs (`_emit` / `_public_detail`),
then the emitted public strings are scanned for the literal restricted text.

Usage: python fu4_probe.py --root <CHECKOUT> --out <json>
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

SAMPLES = {
    # synthetic Windows absolute path inside a restricted holdout root
    "windows_restricted": (
        r"D:\mktkb-p2-holdout\batch-R3-20261119\cases\U02\legacy-response.fernet"
    ),
    # restricted path containing spaces (key material + spaced directory names)
    "spaced_path": r"C:\Users\Review User\Private Holdout V3\evidence keys\batch key.key",
    # an exception string with embedded newlines and an absolute path
    "multiline_exception": (
        'Traceback (most recent call last):\n  File "D:\\mktkb-p2-holdout\\scripts\\run.py", '
        "line 42, in <module>\n    raise SystemExit('refused: D:\\\\mktkb-p2-holdout\\\\batch\\\\x')\n"
        "RuntimeError: batch D:\\mktkb-p2-holdout\\batch\\x refused"
    ),
}
PUBLIC_KEYS = ("detail", "path", "card_file", "binding_file", "receipt_path", "error_code")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def _load_tool(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _capture_emit(module: Any, payload: dict[str, Any], strict: bool | None = None) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        if strict is None:
            module._emit(payload)
        else:
            module._emit(payload, strict=strict)
    return buffer.getvalue()


def main() -> int:
    args = _args()
    root = Path(args.root).resolve()
    sys.path.insert(0, str(root / "backend" / "src"))
    from mktkb.evaluation import p2_safe_output as safe

    report: dict[str, Any] = {"probe": "reviewer-fu4", "root": str(root), "samples": {}}

    for name, sample in SAMPLES.items():
        entry: dict[str, Any] = {"input_length": len(sample)}
        kind = safe.path_kind(sample)
        entry["path_kind"] = kind
        entry["is_restricted"] = safe.is_restricted(sample) if kind else None
        if kind:
            cleaned = safe.redact_value(sample)
        else:
            cleaned = safe.redact_text(sample)
        entry["redacted"] = cleaned
        fragments = []
        for finding in safe.scan_public_text(sample)["findings"]:
            start, length = finding["offset"], finding["length"]
            fragments.append(sample[start : start + length])
        entry["sensitive_fragments"] = fragments
        entry["leaked_fragments"] = [f for f in fragments if f and f in cleaned]
        entry["leaks_original"] = bool(entry["leaked_fragments"])
        entry["contains_redaction_token"] = "redacted" in cleaned or "truncated" in cleaned
        entry["scan_after"] = safe.scan_public_text(cleaned)
        entry["scan_before"] = safe.scan_public_text(sample)
        entry["idempotent"] = (
            safe.redact_text(cleaned) if kind is None else safe.redact_value(cleaned)
        ) == cleaned
        report["samples"][name] = entry

    # Real public exits: feed each sample through the production `_emit` of both tools.
    v3 = _load_tool(root / "tools/p2_h2_v3_controlled_execute.py", "review_v3_tool")
    v2 = _load_tool(root / "tools/p2_h2_controlled_execute.py", "review_v2_tool")
    payload = {
        "command": "derive-cards",
        "ok": False,
        "error_code": "derive_output_in_forbidden_root",
        "detail": SAMPLES["multiline_exception"],
        "paths": {"as_public": {k: v for k, v in SAMPLES.items()}},
        "card_file": {"path": SAMPLES["windows_restricted"]},
        "binding_file": SAMPLES["spaced_path"],
        "counts": {"cases": 24, "turns": 36},
        "reason_codes": ["holdout_hard_failure_unverified"],
        "thresholds_approved": False,
    }
    exits: dict[str, Any] = {}
    for label, text in (
        ("v3_default", _capture_emit(v3, payload)),
        ("v3_strict", _capture_emit(v3, payload, strict=True)),
        ("v2_default", _capture_emit(v2, payload)),
    ):
        parsed = json.loads(text)
        blob = json.dumps(parsed, ensure_ascii=False)
        hits = {name: (sample in blob) for name, sample in SAMPLES.items()}
        fragments = {
            "holdout_root_name": "mktkb-p2-holdout" in blob,
            "spaced_dir_name": "Private Holdout V3" in blob,
            "key_file_name": "batch key.key" in blob,
        }
        exits[label] = {
            "hits": hits,
            "fragments": fragments,
            "kept_error_code": parsed.get("error_code"),
            "kept_counts": parsed.get("counts"),
            "kept_reason_codes": parsed.get("reason_codes"),
            "kept_threshold_flag": parsed.get("thresholds_approved"),
            "contains_token": "redacted" in blob,
            "emitted": blob if len(blob) < 3000 else blob[:3000],
        }
    report["public_exits"] = exits
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v["hits"] for k, v in exits.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
