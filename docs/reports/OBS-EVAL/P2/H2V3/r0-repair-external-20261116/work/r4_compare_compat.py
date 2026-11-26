"""第四轮 compat 对照：四个档位产物逐轴逐值比对（只读）。

只输出白名单：case_id、固定 state/reason、整数、布尔、sha256、compat 版本串。
不输出题面/答案/实体/来源/私有路径。顶层 try/except，异常只出固定码。

用法：
    python r4_compare_compat.py --out <比较结果.json> ^
        --v01 <axes-v0.1.json> --v03 <axes-v0.3.json> ^
        --v04 <axes-v0.4.json> --v05 <axes-v0.5.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys
from typing import Any, Mapping, Sequence

AXES = ("safety", "cross_user", "cross_entity", "stale_source")
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CASE_RE = re.compile(r"^H2V3-C[0-9]{2}$")
COMPAT_RE = re.compile(r"^p2-refusal-compat/v0\.[1-9]$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
FILE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
ALLOWED_KEYS = frozenset(
    {
        "ok",
        "role",
        "case_count",
        "axis_value_count",
        "axis_values_total",
        "files",
        "compat_order",
        "values",
        "diffs",
        "from",
        "to",
        "case_id",
        "axis",
        "left_state",
        "left_reason",
        "right_state",
        "right_reason",
        "state",
        "reason",
        "quality",
        "quality_status",
        "changed_axis_count",
        "changed_axes",
        "hard_failed",
        "unknown_pairs",
        "unknown_pair_count",
        "unknown_cases",
        "empty_scope_proof",
        "injected",
        "control",
        "proven",
        "unchanged_axis_values",
        "flip_count",
        "flip_pairs",
        "byte_equal_groups",
        "sha256",
        "name",
        "steps",
        "equal",
        "netguard",
        "consistency_passed",
        "compat_calls_per_run",
        "compat_empty_scope_calls",
        "default_unchanged",
        "v04_vs_v03",
        "v05_vs_v04",
        "v03_vs_v01",
        "quality_all_equal",
        "axis_values_total",
        "safety",
        "cross_user",
        "cross_entity",
        "stale_source",
        "blocked_attempts",
        "positive_control_attempts",
        "positive_control_blocked",
        "outbound_allowed",
        "unchanged_axis_values",
        "flip_count",
        "flip_pairs",
    }
)


def _fail(code: str) -> None:
    print(json.dumps({"ok": False, "error": code}, sort_keys=True))
    raise SystemExit(2)


def _safe(node: Any, depth: int = 0) -> None:
    if depth > 8:
        _fail("output_too_deep")
    if type(node) in (bool, int):
        if type(node) is int and (node < 0 or node > 10**9):
            _fail("output_int_out_of_range")
        return
    if type(node) is str:
        if (
            CASE_RE.fullmatch(node)
            or COMPAT_RE.fullmatch(node)
            or SHA_RE.fullmatch(node)
            or FILE_RE.fullmatch(node)
            or CODE_RE.fullmatch(node)
        ):
            return
        _fail("unsafe_output_string")
    if isinstance(node, list):
        if len(node) > 4096:
            _fail("output_list_too_long")
        for item in node:
            _safe(item, depth + 1)
        return
    if isinstance(node, dict):
        if len(node) > 256:
            _fail("output_object_too_large")
        for key, value in node.items():
            if type(key) is not str:
                _fail("unsafe_output_key")
            dynamic_key_ok = bool(
                CASE_RE.fullmatch(key) or COMPAT_RE.fullmatch(key) or key.isdigit()
            )
            if key not in ALLOWED_KEYS and not dynamic_key_ok:
                _fail("unsafe_output_key")
            _safe(value, depth + 1)
        return
    _fail("unsafe_output_type")


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _axis_map(doc: Mapping[str, Any]) -> dict[str, dict[str, tuple[str, str]]]:
    runs = doc.get("runs")
    if not isinstance(runs, list) or len(runs) != 1:
        _fail("single_run_required")
    out: dict[str, dict[str, tuple[str, str]]] = {}
    for row in runs[0]["cases"]:
        case_id = str(row["case_id"])
        out[case_id] = {
            axis: (str(row["new_axes"][axis]["state"]), str(row["new_axes"][axis]["reason"]))
            for axis in AXES
        }
    if len(out) != 12:
        _fail("case_count_not_12")
    return out


def _diff(
    left: Mapping[str, Mapping[str, tuple[str, str]]],
    right: Mapping[str, Mapping[str, tuple[str, str]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_id in sorted(left):
        for axis in AXES:
            l_state, l_reason = left[case_id][axis]
            r_state, r_reason = right[case_id][axis]
            if (l_state, l_reason) != (r_state, r_reason):
                rows.append(
                    {
                        "case_id": case_id,
                        "axis": axis,
                        "left_state": l_state,
                        "left_reason": l_reason,
                        "right_state": r_state,
                        "right_reason": r_reason,
                    }
                )
    return rows


def _unknown_pairs(map_: Mapping[str, Mapping[str, tuple[str, str]]]) -> list[dict[str, Any]]:
    return [
        {"case_id": case_id, "axis": axis, "state": state, "reason": reason}
        for case_id in sorted(map_)
        for axis in AXES
        for state, reason in (map_[case_id][axis],)
        if state == "unknown"
    ]


def _hard_failed(doc: Mapping[str, Any]) -> list[str]:
    return sorted(str(item["case_id"]) for item in doc["runs"][0]["cases"] if bool(item["hard_failed"]))


def _quality(map_doc: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(row["case_id"]): str(row["quality_status"]) for row in map_doc["runs"][0]["cases"]
    }


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--v01", required=True)
    parser.add_argument("--v03", required=True)
    parser.add_argument("--v04", required=True)
    parser.add_argument("--v05", required=True)
    args = parser.parse_args(list(argv))

    paths = {
        "p2-refusal-compat/v0.1": pathlib.Path(args.v01),
        "p2-refusal-compat/v0.3": pathlib.Path(args.v03),
        "p2-refusal-compat/v0.4": pathlib.Path(args.v04),
        "p2-refusal-compat/v0.5": pathlib.Path(args.v05),
    }
    docs: dict[str, Mapping[str, Any]] = {}
    for compat, path in paths.items():
        docs[compat] = json.loads(path.read_text(encoding="utf-8"))
        if str(docs[compat]["compat"]["mode"]) != compat:
            _fail("compat_mode_mismatch")
    maps = {compat: _axis_map(doc) for compat, doc in docs.items()}
    cases = sorted(maps["p2-refusal-compat/v0.5"])

    v01, v03, v04, v05 = (
        maps["p2-refusal-compat/v0.1"],
        maps["p2-refusal-compat/v0.3"],
        maps["p2-refusal-compat/v0.4"],
        maps["p2-refusal-compat/v0.5"],
    )
    diff_01_03 = _diff(v01, v03)
    diff_03_04 = _diff(v03, v04)
    diff_04_05 = _diff(v04, v05)
    total_values = len(cases) * len(AXES)
    flip_pairs = sorted(
        {(row["case_id"], row["axis"]) for row in diff_04_05}
    )

    quality_by_compat = {
        compat: _quality(docs[compat]) for compat in paths
    }
    quality_equal = all(
        quality_by_compat[compat] == quality_by_compat["p2-refusal-compat/v0.5"]
        for compat in quality_by_compat
    )

    empty_scope = {
        compat: {
            str(row["case_id"]): {
                axis: bool(
                    (row.get("empty_scope_proof") or {})
                    .get("empty_scope_proven", {})
                    .get("injected", {})
                    .get(axis)
                )
                for axis in ("cross_entity", "stale_source")
            }
            for row in docs[compat]["runs"][0]["cases"]
            if row.get("empty_scope_proof")
        }
        for compat in paths
    }

    result = {
        "ok": True,
        "role": "compat_axis_value_compare",
        "case_count": len(cases),
        "axis_value_count": len(AXES),
        "axis_values_total": total_values,
        "compat_order": list(paths),
        "files": {
            compat: {"name": path.name, "sha256": _sha256(path)}
            for compat, path in paths.items()
        },
        "values": {
            compat: {
                case_id: {
                    axis: {"state": maps[compat][case_id][axis][0], "reason": maps[compat][case_id][axis][1]}
                    for axis in AXES
                }
                for case_id in cases
            }
            for compat in paths
        },
        "quality": quality_by_compat,
        "v03_vs_v01": {
            "flip_count": len(diff_01_03),
            "flip_pairs": [
                {"case_id": row["case_id"], "axis": row["axis"], "left_state": row["left_state"],
                 "left_reason": row["left_reason"], "right_state": row["right_state"],
                 "right_reason": row["right_reason"]}
                for row in diff_01_03
            ],
        },
        "v04_vs_v03": {
            "flip_count": len(diff_03_04),
            "flip_pairs": [
                {"case_id": row["case_id"], "axis": row["axis"], "left_state": row["left_state"],
                 "left_reason": row["left_reason"], "right_state": row["right_state"],
                 "right_reason": row["right_reason"]}
                for row in diff_03_04
            ],
        },
        "v05_vs_v04": {
            "flip_count": len(diff_04_05),
            "flip_pairs": [
                {"case_id": row["case_id"], "axis": row["axis"], "left_state": row["left_state"],
                 "left_reason": row["left_reason"], "right_state": row["right_state"],
                 "right_reason": row["right_reason"]}
                for row in diff_04_05
            ],
            "unchanged_axis_values": total_values - len(diff_04_05),
        },
        "flip_pairs": [{"case_id": cid, "axis": axis} for cid, axis in flip_pairs],
        "unknown_pairs": {
            compat: _unknown_pairs(maps[compat]) for compat in paths
        },
        "unknown_pair_count": {
            compat: len(_unknown_pairs(maps[compat])) for compat in paths
        },
        "unknown_cases": {
            compat: sorted({row["case_id"] for row in _unknown_pairs(maps[compat])})
            for compat in paths
        },
        "hard_failed": {compat: _hard_failed(docs[compat]) for compat in paths},
        "quality_all_equal": quality_equal,
        "empty_scope_proof": empty_scope,
        "consistency_passed": {
            compat: bool(docs[compat]["consistency"]["passed"]) for compat in paths
        },
        "compat_calls_per_run": {
            compat: dict(docs[compat]["compat"]["calls_per_run"]) for compat in paths
        },
        "compat_empty_scope_calls": {
            compat: {
                str(run): dict(block["injected_calls"])
                for run, block in docs[compat]["compat"]["empty_scope_injection"]["per_run"].items()
            }
            for compat in paths
        },
        "default_unchanged": {
            compat: bool(docs[compat]["compat"]["default_unchanged"]) for compat in paths
        },
        "netguard": {compat: docs[compat]["netguard"] for compat in paths},
    }
    # 硬性自证：v0.5 的翻转集必须恰为 4 对，且其余 44 个轴值逐值不变。
    if len(diff_04_05) != 4 or total_values - len(diff_04_05) != total_values - 4:
        _fail("v05_flip_set_not_exact")
    if {row["case_id"] for row in diff_04_05} != {"H2V3-C16", "H2V3-C17"}:
        _fail("v05_flip_cases_unexpected")
    if diff_03_04:
        _fail("v04_differs_from_v03")
    _safe(result)
    path = pathlib.Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "wrote": path.name,
                "flip_count_v05_vs_v04": len(diff_04_05),
                "unknown_pair_count": result["unknown_pair_count"],
                "hard_failed": result["hard_failed"],
                "quality_all_equal": quality_equal,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - 只出固定码
        print(json.dumps({"ok": False, "error": "compare_failed"}, sort_keys=True))
        raise SystemExit(3) from None
