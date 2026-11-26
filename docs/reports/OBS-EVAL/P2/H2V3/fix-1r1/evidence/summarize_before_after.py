"""v3-fix-1/R1 改前/改后同输入对照汇总（只读两个探针 JSON，生成紧凑表）。

用法：
    python summarize_before_after.py <before.json> <after.json> <out.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    before_path, after_path, out_path = sys.argv[1:4]
    before = _load(before_path)
    after = _load(after_path)
    rows = {}
    for name, row in after["cases"].items():
        old = before["cases"][name]
        base = row["baseline"]
        pre = old["current"]
        post = row["current"]
        rows[name] = {
            "class": row["class"],
            "question": row["question"],
            "legacy_intent_clarification": row.get("legacy_intent", {}).get(
                "clarification"
            ),
            "baseline_fix1_legacy": {
                "reason": base["reason"],
                "clarification": bool(base["clarification"]),
                "rag_owns_turn": base["rag_owns_turn"],
                "kernel_kind": base.get("kernel_ask", {}).get("kind"),
                "kernel_returned": base.get("kernel_ask", {}).get("returned"),
            },
            "before_r1_fix1_a": {
                "reason": pre["reason"],
                "clarification": bool(pre["clarification"]),
                "rag_owns_turn": pre["rag_owns_turn"],
                "kernel_kind": pre.get("kernel_ask", {}).get("kind"),
                "kernel_returned": pre.get("kernel_ask", {}).get("returned"),
            },
            "after_r1": {
                "reason": post["reason"],
                "clarification": bool(post["clarification"]),
                "rag_owns_turn": post["rag_owns_turn"],
                "kernel_kind": post.get("kernel_ask", {}).get("kind"),
                "kernel_returned": post.get("kernel_ask", {}).get("returned"),
            },
            "before_eq_after": all(
                pre[key] == post[key] for key in ("reason", "rag_owns_turn", "clarification")
            ),
            "after_restores_baseline_route": (
                post["rag_owns_turn"] == base["rag_owns_turn"]
            ),
        }
    payload = {
        "schema_version": "v3-fix1r1-before-after/v0.1",
        "before": {
            "path": before_path,
            "query_sha256": before["code_under_test"]["backend/src/mktkb/rag/query.py"],
            "external_attempts_during_probe": before["external_attempts_during_probe"],
            "all_controls_blocked": before["all_controls_blocked"],
        },
        "after": {
            "path": after_path,
            "query_sha256": after["code_under_test"]["backend/src/mktkb/rag/query.py"],
            "external_attempts_during_probe": after["external_attempts_during_probe"],
            "all_controls_blocked": after["all_controls_blocked"],
        },
        "baseline_source": after["baseline_source"],
        "rows": rows,
        "r1_fixed_cases": [
            name
            for name, row in rows.items()
            if row["before_r1_fix1_a"]["reason"] == "MULTI_TARGET_ENUMERATE"
            and row["after_r1"]["reason"] != "MULTI_TARGET_ENUMERATE"
        ],
        "r1_changed_cases": [
            name
            for name, row in rows.items()
            if row["before_r1_fix1_a"]["reason"] != row["after_r1"]["reason"]
            or row["before_r1_fix1_a"]["rag_owns_turn"] != row["after_r1"]["rag_owns_turn"]
        ],
        "positive_cases_still_released": [
            name
            for name, row in rows.items()
            if name.startswith("P")
            and row["after_r1"]["reason"] == "MULTI_TARGET_ENUMERATE"
            and row["after_r1"]["rag_owns_turn"] is True
        ],
    }
    Path(out_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "before_query_sha256": payload["before"]["query_sha256"],
                "after_query_sha256": payload["after"]["query_sha256"],
                "r1_fixed_cases": payload["r1_fixed_cases"],
                "r1_changed_cases": payload["r1_changed_cases"],
                "positive_cases_still_released": payload[
                    "positive_cases_still_released"
                ],
                "rows": {
                    name: {
                        "base": (r["baseline_fix1_legacy"]["reason"],
                                 r["baseline_fix1_legacy"]["rag_owns_turn"]),
                        "before": (r["before_r1_fix1_a"]["reason"],
                                   r["before_r1_fix1_a"]["rag_owns_turn"],
                                   r["before_r1_fix1_a"]["kernel_kind"],
                                   r["before_r1_fix1_a"]["kernel_returned"]),
                        "after": (r["after_r1"]["reason"],
                                  r["after_r1"]["rag_owns_turn"],
                                  r["after_r1"]["kernel_kind"],
                                  r["after_r1"]["kernel_returned"]),
                    }
                    for name, r in rows.items()
                },
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
