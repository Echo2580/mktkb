"""三路逐题质量对比：case-plan / 四轴重评分 / SAFE 重建 + 检查码对比。

只输出：case_id、固定 quality_status、固定 check_id、整数、布尔、sha256 前 16。
不输出题面/答案/实体/来源内容。
用法：python three_way.py <case-plan> <axes-v04> <quality-doc> [<old-quality-doc>]
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

CHECK_IDS = (
    "kind_correct",
    "pagination_has_more",
    "pagination_next_page",
    "pagination_returned",
    "pagination_total",
    "refusal_expected",
    "refusal_unexpected",
    "source_forbidden",
    "source_hit",
    "value_forbidden",
    "value_hit",
    "value_no_fabricated",
)


def sha16(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main(argv: list[str]) -> int:
    plan_path, axes_path, quality_path = (pathlib.Path(p) for p in argv[:3])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    axes = json.loads(axes_path.read_text(encoding="utf-8"))
    quality = json.loads(quality_path.read_text(encoding="utf-8"))

    plan_q = {str(c["case_id"]): str(c["quality_status"]) for c in plan["cases"]}
    axes_q = {str(c["case_id"]): str(c["quality_status"]) for c in axes["runs"][0]["cases"]}
    safe_q = {str(c["case_id"]): str(c["quality_status"]) for c in quality["cases"]}
    checks = {str(c["case_id"]): sorted(str(x) for x in c["failed_check_ids"]) for c in quality["cases"]}

    print("sha256_16 case_plan=%s axes=%s quality=%s" % (sha16(plan_path), sha16(axes_path), sha16(quality_path)))
    print("case_sets_equal plan==axes: %s, plan==safe: %s" % (set(plan_q) == set(axes_q), set(plan_q) == set(safe_q)))
    mismatch_axes = sorted(c for c in plan_q if axes_q.get(c) != plan_q[c])
    mismatch_safe = sorted(c for c in plan_q if safe_q.get(c) != plan_q[c])
    print("quality_mismatch axes=%s safe=%s" % (mismatch_axes, mismatch_safe))
    print("quality_counts plan=%s axes=%s safe=%s" % (
        json.dumps({k: list(plan_q.values()).count(k) for k in sorted(set(plan_q.values()))}),
        json.dumps({k: list(axes_q.values()).count(k) for k in sorted(set(axes_q.values()))}),
        json.dumps({k: list(safe_q.values()).count(k) for k in sorted(set(safe_q.values()))}),
    ))
    for case_id in sorted(plan_q):
        print("%s plan=%s axes=%s safe=%s failed=%s" % (
            case_id, plan_q[case_id], axes_q.get(case_id), safe_q.get(case_id), json.dumps(checks.get(case_id, []))
        ))
    totals = {check_id: sum(1 for c in checks.values() if check_id in c) for check_id in CHECK_IDS}
    print("check_id_totals=%s" % json.dumps(totals, sort_keys=True))
    print("doc_flags=%s" % json.dumps({k: quality.get(k) for k in (
        "ok", "reconstruction_match", "scoring_paths_agree", "custody_ok", "unsafe_code_count",
        "case_count", "turn_count", "envelope_count")}, sort_keys=True))

    if len(argv) > 3:
        old_path = pathlib.Path(argv[3])
        old = json.loads(old_path.read_text(encoding="utf-8"))
        old_q = {str(c["case_id"]): str(c["quality_status"]) for c in old["cases"]}
        old_checks = {str(c["case_id"]): sorted(str(x) for x in c["failed_check_ids"]) for c in old["cases"]}
        print("old_sha256_16=%s" % sha16(old_path))
        for case_id in ("H2V3-C12", "H2V3-C21", "H2V3-C27", "H2V3-C02"):
            print("compare %s old=%s/%s new=%s/%s same=%s" % (
                case_id, old_q.get(case_id), json.dumps(old_checks.get(case_id, [])),
                safe_q.get(case_id), json.dumps(checks.get(case_id, [])),
                old_checks.get(case_id) == checks.get(case_id) and old_q.get(case_id) == safe_q.get(case_id),
            ))
        moved = sorted(c for c in set(old_q) & set(safe_q) if old_q[c] != safe_q[c] or old_checks.get(c) != checks.get(c))
        print("quality_or_check_moved=%s" % (moved,))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
