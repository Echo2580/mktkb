"""SAFE 输出扫描器：逐字段检查目录内全部 JSON，只打印计数与命中「类别」。

检查项：
1. 私有路径痕迹：盘符路径、`mktkb-`、`holdout`、`.fernet`、`\\Users\\`、环境变量样子。
2. 字符串形状：路径分隔符 / 换行 / 超长文本（题面/答案正文的典型形状）。
3. 交叉一致性：每个 axes-*.json 的逐题 quality_status 必须与同名 quality 产物、
   以及 SAFE 重建产物逐题相等；硬失败集合必须一致。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

PRIVATE_PATTERNS = {
    "drive_path": re.compile(r"[A-Za-z]:[\\/]"),
    "private_root": re.compile(r"mktkb-p2-", re.IGNORECASE),
    "holdout_root": re.compile(r"mktkb-p2-holdout", re.IGNORECASE),
    "fernet": re.compile(r"\.fernet", re.IGNORECASE),
    "users_dir": re.compile(r"\\\\Users\\\\|/Users/", re.IGNORECASE),
    "env_name": re.compile(r"^[A-Z][A-Z0-9_]{3,}$"),
}
SUSPICIOUS_SHAPE = {
    "has_backslash": re.compile(r"\\"),
    "has_newline": re.compile(r"[\r\n]"),
    "long_text": re.compile(r".{80,}"),
}


def walk(node, hits, shapes):  # noqa: ANN001
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str):
                for name, pattern in PRIVATE_PATTERNS.items():
                    if pattern.search(key):
                        hits[name] = hits.get(name, 0) + 1
            walk(value, hits, shapes)
        return
    if isinstance(node, list):
        for item in node:
            walk(item, hits, shapes)
        return
    if isinstance(node, str):
        for name, pattern in PRIVATE_PATTERNS.items():
            if pattern.search(node):
                hits[name] = hits.get(name, 0) + 1
        for name, pattern in SUSPICIOUS_SHAPE.items():
            if pattern.search(node):
                shapes[name] = shapes.get(name, 0) + 1


def _axes_quality(payload: dict) -> dict[str, str]:
    return {
        row["case_id"]: row["quality_status"]
        for run in payload["runs"]
        for row in run["cases"]
    }


def main() -> int:
    evid = pathlib.Path(sys.argv[1])
    files = sorted(evid.glob("*.json"))
    report: dict[str, object] = {}
    payloads: dict[str, dict] = {}
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payloads[path.name] = payload
        hits: dict[str, int] = {}
        shapes: dict[str, int] = {}
        walk(payload, hits, shapes)
        report[path.name] = {"private_hits": hits, "shape_hits": shapes}

    checks_name = next((name for name in payloads if name.startswith("r0-quality-checks")), None)
    safe_quality = (
        {row["case_id"]: row["quality_status"] for row in payloads[checks_name]["cases"]}
        if checks_name
        else None
    )
    cross: dict[str, object] = {}
    for name, payload in payloads.items():
        if not name.startswith("axes-"):
            continue
        tag = name[len("axes-v2-r0-post-repair") : -len(".json")]  # "" or "-compat-v03"
        quality_name = f"quality-per-run-v2{tag}.json"
        axes_quality = _axes_quality(payload)
        entry = {
            "case_count": len(axes_quality),
            "pass": sum(1 for value in axes_quality.values() if value == "pass"),
            "fail": sum(1 for value in axes_quality.values() if value == "fail"),
            "fail_ids": sorted(k for k, v in axes_quality.items() if v != "pass"),
            "hard_failures": payload["aggregate"]["hard_failures"],
            "unknown_cases": payload["aggregate"]["unknown_cases"],
            "vs_safe_checks_equal": (axes_quality == safe_quality) if safe_quality else None,
            "quality_artifact": quality_name,
        }
        if quality_name in payloads:
            q = payloads[quality_name]
            entry["vs_quality_artifact_equal"] = axes_quality == {
                row["case_id"]: row["quality_status"] for row in q["cases"]
            }
            entry["quality_hard_failures"] = q["totals"]["hard_failures"]
        cross[name] = entry
    report["cross_check"] = cross
    print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
