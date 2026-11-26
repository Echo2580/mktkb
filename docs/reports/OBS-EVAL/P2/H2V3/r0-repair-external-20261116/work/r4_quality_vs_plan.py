"""第四轮质量对账：SAFE 质量产物 vs case-plan 逐题 quality_status（只读）。

只输出：case_id 列表、整数、布尔、sha256、固定 quality 码。
用法：python r4_quality_vs_plan.py --quality <json> --case-plan <json> --out <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from typing import Any, Mapping, Sequence

CASE_RE = re.compile(r"^H2V3-C[0-9]{2}$")
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_KEYS = frozenset(
    {
        "ok",
        "role",
        "case_count",
        "equal_count",
        "mismatch_count",
        "mismatch_cases",
        "missing_in_quality",
        "missing_in_case_plan",
        "quality_counts",
        "case_plan_sha256",
        "quality_sha256",
        "all_equal",
        "netguard",
        "blocked_attempts",
        "positive_control_attempts",
        "positive_control_blocked",
        "outbound_allowed",
        "pass",
        "fail",
        "error",
        "not_executed",
    }
)


def _fail(code: str) -> None:
    print(json.dumps({"ok": False, "error": code}, sort_keys=True))
    raise SystemExit(2)


def _safe(node: Any, depth: int = 0) -> None:
    if depth > 6:
        _fail("output_too_deep")
    if type(node) in (bool, int):
        if type(node) is int and (node < 0 or node > 10**9):
            _fail("output_int_out_of_range")
        return
    if type(node) is str:
        if CASE_RE.fullmatch(node) or SHA_RE.fullmatch(node) or CODE_RE.fullmatch(node):
            return
        _fail("unsafe_output_string")
    if isinstance(node, list):
        for item in node:
            _safe(item, depth + 1)
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if type(key) is not str:
                _fail("unsafe_output_key")
            if key not in ALLOWED_KEYS and not (CASE_RE.fullmatch(key) or key.isdigit()):
                _fail("unsafe_output_key")
            _safe(value, depth + 1)
        return
    _fail("unsafe_output_type")


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--quality", required=True)
    parser.add_argument("--case-plan", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(list(argv))

    quality_path = pathlib.Path(args.quality)
    plan_path = pathlib.Path(args.case_plan)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    plan_quality = {
        str(row.get("case_id")): str(row.get("quality_status")) for row in plan["cases"]
    }
    got_quality = {
        str(row.get("case_id")): str(row.get("quality_status")) for row in quality["cases"]
    }
    mismatch = sorted(
        case_id
        for case_id in set(plan_quality) | set(got_quality)
        if plan_quality.get(case_id) != got_quality.get(case_id)
    )
    counts = {status: 0 for status in ("pass", "fail", "error", "not_executed")}
    for value in got_quality.values():
        if value in counts:
            counts[value] += 1
    result = {
        "ok": True,
        "role": "quality_vs_case_plan",
        "case_count": len(plan_quality),
        "equal_count": len(plan_quality) - len(mismatch),
        "mismatch_count": len(mismatch),
        "mismatch_cases": mismatch,
        "missing_in_quality": sorted(set(plan_quality) - set(got_quality)),
        "missing_in_case_plan": sorted(set(got_quality) - set(plan_quality)),
        "quality_counts": counts,
        "all_equal": not mismatch,
        "case_plan_sha256": _sha256(plan_path),
        "quality_sha256": _sha256(quality_path),
    }
    _safe(result)
    path = pathlib.Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "case_count": result["case_count"], "equal_count": result["equal_count"],
                      "mismatch_count": result["mismatch_count"], "quality_counts": counts,
                      "wrote": path.name}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - 只出固定码
        print(json.dumps({"ok": False, "error": "quality_compare_failed"}, sort_keys=True))
        raise SystemExit(3) from None
