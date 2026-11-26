"""R0 第六轮判定链交叉核对：只出 case_id / 固定码 / 整数 / 布尔 / sha256。

离线只读。绝不打印题干、答案、实体、值或私有路径。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPORT = HERE.parent
EVID = REPORT / "evidence" / "11-round6-chain"
RUN_ROOT = pathlib.Path(r"D:\mktkb-p2-h2v3-r0fix6-20261116\r0")
BINDING = pathlib.Path(
    r"D:\mktkb-p2-h2v3-20261115\custody-plan-20261116-final5\bindings\run0-base_b0.binding.json"
)
OUT = EVID / "chain-crosscheck-round6.json"

AXES_V05 = EVID / "axes-v2-round6-v05.json"
AXES_V04 = EVID / "axes-v2-round6-v04-control.json"
QUALITY_V05 = EVID / "quality-per-run-v2-compat-v05.json"
SUMMARY_V05 = EVID / "final-summary-v2-compat-v05.json"
SAFE = REPORT / "work" / "out" / "round6-safe" / "r0-quality-checks.json"
CASE_PLAN = RUN_ROOT / "out" / "controlled" / "case-plan.json"

AXES = ("safety", "cross_user", "cross_entity", "stale_source")


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _case_map(axes_doc) -> dict:
    run = axes_doc["runs"][0]
    return {str(c["case_id"]): c for c in run["cases"]}, run


def _unknown_pairs(axes_doc) -> list:
    cases, _run = _case_map(axes_doc)
    pairs = []
    for case_id, case in cases.items():
        for axis in AXES:
            node = (case.get("new_axes") or {}).get(axis) or {}
            if str(node.get("state")) == "unknown":
                pairs.append({"case_id": case_id, "axis": axis, "reason": str(node.get("reason") or "")})
    return sorted(pairs, key=lambda item: (item["case_id"], item["axis"]))


def _axis_states(axes_doc) -> dict:
    cases, _run = _case_map(axes_doc)
    out = {}
    for case_id, case in cases.items():
        for axis in AXES:
            node = (case.get("new_axes") or {}).get(axis) or {}
            out[(case_id, axis)] = (str(node.get("state") or ""), str(node.get("reason") or ""))
    return out


def _main() -> dict:
    v05 = _load(AXES_V05)
    v04 = _load(AXES_V04)
    quality = _load(QUALITY_V05)
    summary = _load(SUMMARY_V05)
    safe = _load(SAFE)
    case_plan = _load(CASE_PLAN)

    cases05, run05 = _case_map(v05)
    plan_status = {str(c.get("case_id")): str(c.get("quality_status")) for c in case_plan["cases"]}
    safe_status = {str(c.get("case_id")): str(c.get("quality_status")) for c in safe["cases"]}
    axes_status = {cid: str(c.get("quality_status")) for cid, c in cases05.items()}
    q_cases = quality.get("cases") or []
    quality_status = {str(c.get("case_id")): str(c.get("quality_status")) for c in q_cases}

    case_ids = sorted(plan_status)
    three_way = [
        {
            "case_id": cid,
            "case_plan": plan_status.get(cid),
            "safe_reconstruction": safe_status.get(cid),
            "axes_v05": axes_status.get(cid),
            "quality_artifact": quality_status.get(cid),
            "all_equal": len({plan_status.get(cid), safe_status.get(cid), axes_status.get(cid), quality_status.get(cid)}) == 1,
        }
        for cid in case_ids
    ]
    quality_status_safe = {
        str(c.get("case_id")): {
            "quality_status": str(c.get("quality_status")),
            "failed_check_ids": [str(x) for x in (c.get("failed_check_ids") or [])],
        }
        for c in safe["cases"]
    }

    states05 = _axis_states(v05)
    states04 = _axis_states(v04)
    flips = [
        {"case_id": cid, "axis": axis, "v05": states05[(cid, axis)][0], "v04": states04[(cid, axis)][0]}
        for (cid, axis) in states05
        if states05.get((cid, axis)) != states04.get((cid, axis))
    ]
    unchanged = sum(1 for key in states05 if states05.get(key) == states04.get(key))

    pairs05 = _unknown_pairs(v05)
    pairs04 = _unknown_pairs(v04)

    hard = {
        "new_hard_failures": [str(x) for x in (run05.get("new_hard_failures") or [])],
        "initial_hard_failures": [str(x) for x in (run05.get("initial_hard_failures") or [])],
        "historical_hard_failures": [str(x) for x in (run05.get("historical_hard_failures") or [])],
    }
    refs = {
        str(name): str((node or {}).get("value") or "")
        for name, node in ((run05.get("card_origin") or {}).get("fields") or {}).items()
        if isinstance(node, dict)
    }
    binding = _load(BINDING)
    run_quality = dict(run05.get("quality") or {})
    return {
        "ok": True,
        "round": 6,
        "run_root_sha256_of_case_plan": _sha(CASE_PLAN),
        "plan_sha256": refs.get("plan_sha256", ""),
        "code_version": refs.get("code_version", ""),
        "evidence_tree_sha256": refs.get("evidence_tree_sha256", ""),
        "binding_sha256": str(binding.get("binding_sha256") or ""),
        "classifier_module_sha256": str((v05.get("inputs") or {}).get("classifier_module_sha256") or ""),
        "compat": str(run05.get("compat") or ""),
        "case_count": len(case_ids),
        "quality": {
            "pass": int(run_quality.get("pass", -1)),
            "fail": int(run_quality.get("fail", -1)),
            "fail_cases": [cid for cid in case_ids if plan_status.get(cid) == "fail"],
            "per_case": quality_status_safe,
            "three_way_all_equal": all(item["all_equal"] for item in three_way),
            "three_way": three_way,
            "quality_case_plan_match": bool(run05.get("quality_case_plan_match")),
        },
        "axes_v05": {axis: dict((run05.get("new_axes") or {}).get(axis) or {}) for axis in AXES},
        "unknown_pairs_v05": pairs05,
        "unknown_pairs_v05_count": len(pairs05),
        "unknown_pairs_v04": pairs04,
        "unknown_pairs_v04_count": len(pairs04),
        "v05_vs_v04": {
            "flip_count": len(flips),
            "unchanged_axis_values": unchanged,
            "flips": flips,
        },
        "hard_failures": hard,
        "consistency_passed": bool((v05.get("consistency") or {}).get("passed")),
        "consistency_checks": list((v05.get("consistency") or {}).get("checks") or ()),
        "netguard": dict(v05.get("netguard") or {}),
        "compat_classify_calls": int(run05.get("compat_classify_calls", -1)),
        "t207": dict(summary.get("judgement") or {}),
        "summary": {
            "case_count": summary.get("case_count"),
            "quality": summary.get("quality"),
            "hard_failures": summary.get("hard_failures"),
        },
        "sha256": {
            "axes_v05": _sha(AXES_V05),
            "axes_v04": _sha(AXES_V04),
            "quality_v05": _sha(QUALITY_V05),
            "summary_v05": _sha(SUMMARY_V05),
            "safe_projection": _sha(SAFE),
        },
    }


def main() -> int:
    try:
        result = _main()
    except Exception:
        result = {"ok": False, "error": "crosscheck_failed"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    brief = {
        "ok": result.get("ok"),
        "quality": result.get("quality", {}).get("pass"),
        "fail": result.get("quality", {}).get("fail"),
        "three_way_all_equal": result.get("quality", {}).get("three_way_all_equal"),
        "unknown_v05": result.get("unknown_pairs_v05_count"),
        "unknown_v04": result.get("unknown_pairs_v04_count"),
        "hard": result.get("hard_failures", {}).get("new_hard_failures"),
        "flips": result.get("v05_vs_v04", {}).get("flip_count"),
        "consistency": result.get("consistency_passed"),
    }
    print(json.dumps(brief, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
