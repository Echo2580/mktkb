"""Q1a-3 阻断项取证：旧卡是否含逐题四轴 verdict，以及模块 API 的必需输入。

只读 4 张旧卡 / case-plan / 回执 / seal-manifest 的**键**与聚合计数；
不打印任何题面/答案/目标值/逐题内容。
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import sys
from pathlib import Path

REPO = Path(r"D:\GPT项目\市场部AI知识库")
sys.path.insert(0, str(REPO / "backend" / "src"))
RUN_ROOT = Path(r"D:\mktkb-p2-t207-h2-20261114")
AXES = ("safety", "cross_user", "cross_entity", "stale_source")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def key_tree(value, prefix: str = "", depth: int = 0, max_depth: int = 4):
    """返回 (键路径, 类型, 容器长度) 列表；不返回值。"""
    rows = []
    if isinstance(value, dict) and depth <= max_depth:
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            rows.append((path, type(item).__name__, len(item) if hasattr(item, "__len__") and not isinstance(item, bool) else None))
            rows.extend(key_tree(item, path, depth + 1, max_depth))
    elif isinstance(value, list) and value and depth <= max_depth:
        rows.append((f"{prefix}[0]", type(value[0]).__name__, None))
        rows.extend(key_tree(value[0], f"{prefix}[0]", depth + 1, max_depth))
    return rows


def main() -> int:
    import mktkb.evaluation.p2_evidence_rescore as q1a1
    import mktkb.evaluation.p2_evidence_rescore_axes as q1a1b

    cards = {}
    axis_aggregate = {axis: {"planned": 0, "passed": 0, "not_applicable": 0, "unknown": 0, "violations": 0, "checked": 0} for axis in AXES}
    per_run = {}
    failed_cases_total = 0
    passed_cases_total = 0
    for idx in range(4):
        run_dir = RUN_ROOT / "runs" / f"r{idx}"
        card_path = run_dir / "card.json"
        card = json.loads(card_path.read_text(encoding="utf-8"))
        plan = json.loads((run_dir / "out" / "controlled" / "case-plan.json").read_text(encoding="utf-8"))
        he = card["hard_evidence"]
        per_run[f"r{idx}"] = {
            "run_id": card["run_id"],
            "card_sha256": sha(card_path.read_bytes()),
            "card_bytes": card_path.stat().st_size,
            "detail_export": card["detail_export"],
            "top_level_keys": sorted(card.keys()),
            "has_per_case_array": any(
                isinstance(card.get(k), list) and card.get(k) and isinstance(card[k][0], dict) and "case_id" in card[k][0]
                for k in card.keys()
            ),
            "hard_evidence_keys": sorted(he.keys()),
            "hard_evidence_axes": {axis: dict(he["axes"][axis]) for axis in AXES},
            "case_plan_cases": len(plan["cases"]),
            "case_plan_quality_status_counts": {
                status: sum(1 for c in plan["cases"] if c["quality_status"] == status)
                for status in sorted({c["quality_status"] for c in plan["cases"]})
            },
            "case_plan_case_row_keys": sorted(plan["cases"][0].keys()),
            "case_plan_turn_row_keys": sorted(plan["cases"][0]["turns"][0].keys()),
        }
        for axis in AXES:
            for key in axis_aggregate[axis]:
                axis_aggregate[axis][key] += int(he["axes"][axis][key])
        failed_cases_total += int(card["failed"])
        passed_cases_total += int(card["passed"])

    # 旧聚合自洽（冻结口径）
    consistency = {}
    for axis in AXES:
        row = axis_aggregate[axis]
        consistency[axis] = {
            "planned_eq_sum": row["planned"] == row["passed"] + row["not_applicable"] + row["unknown"] + row["violations"],
            "checked_eq_sum": row["checked"] == row["passed"] + row["not_applicable"] + row["violations"],
            "checked_plus_unknown_eq_planned": row["checked"] + row["unknown"] == row["planned"],
        }

    # 模块 API 必需输入（键名与签名，不含任何输入值）
    api = {
        "q1a1_rescore_run_required_params": [
            name for name, p in inspect.signature(q1a1.rescore_run).parameters.items() if p.default is inspect.Parameter.empty
        ],
        "q1a1_OldCardCase_fields": [f.name for f in dataclasses.fields(q1a1.OldCardCase)],
        "q1a1_SafetyCaseView_fields": [f.name for f in dataclasses.fields(q1a1.SafetyCaseView)],
        "q1a1b_AxesCaseView_fields": [f.name for f in dataclasses.fields(q1a1b.AxesCaseView)],
        "q1a1b_rescore_axes_run_required_params": [
            name for name, p in inspect.signature(q1a1b.rescore_axes_run).parameters.items() if p.default is inspect.Parameter.empty
        ],
        "q1a1b_axes_case_from_q1a2_view_required_kwargs": [
            name
            for name, p in inspect.signature(q1a1b.axes_case_from_q1a2_view).parameters.items()
            if p.default is inspect.Parameter.empty and p.kind is inspect.Parameter.KEYWORD_ONLY
        ],
        "q1a1_OldCardCase_axis_key_requirement": "set(self.axes) == set(AXES) 且每轴 state∈AXIS_STATES、reason 非空（p2_evidence_rescore.OldCardCase.__post_init__）",
    }

    # fail-closed 实证：先给一个合法的 RescoreIdentity（用实测 hash），再传空 cases
    fail_closed = {}
    module_sha = sha((REPO / "backend/src/mktkb/evaluation/p2_evidence_rescore.py").read_bytes())
    contract_sha = sha((REPO / "docs/evaluation/p2-evidence-rescore-v0_1.md").read_bytes())
    binding_path = RUN_ROOT / "plans2" / "run-binding.json"
    binding_payload_sha = sha(
        json.dumps(
            {k: v for k, v in json.loads(binding_path.read_text(encoding="utf-8")).items() if k != "binding_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    try:
        identity = q1a1.RescoreIdentity(
            old_run_id="p2-h2-20261114-r1-r1-base_b0",
            old_binding={"old_run_binding_payload_sha256": binding_payload_sha},
            old_binding_sha256=binding_payload_sha,
            old_evidence_tree_sha256="0" * 64,
            old_card_sha256="0" * 64,
            contract_sha256=contract_sha,
            evaluator_sha256=module_sha,
        )
        try:
            q1a1.rescore_run(identity=identity, cases=[])
            fail_closed["rescore_run_empty_cases"] = "NOT_REFUSED"
        except q1a1.RescoreError as exc:
            fail_closed["rescore_run_empty_cases"] = f"refused:{exc.code}"
        fail_closed["identity_constructed"] = True
    except q1a1.RescoreError as exc:
        fail_closed["identity_constructed"] = f"refused:{exc.code}"

    print(
        json.dumps(
            {
                "schema_version": "q1a3-blocked-input-proof/v0.1",
                "per_run": per_run,
                "aggregate_old_axes_from_cards": axis_aggregate,
                "aggregate_old_axes_consistency": consistency,
                "cases": {
                    "total": sum(v["case_plan_cases"] for v in per_run.values()),
                    "passed_from_cards": passed_cases_total,
                    "failed_from_cards": failed_cases_total,
                },
                "module_api_required_inputs": api,
                "fail_closed_probe": fail_closed,
                "conclusion": (
                    "4 张旧卡均为聚合卡：detail_export=false，顶层无逐题行，hard_evidence 只有 axes 计数；"
                    "case-plan 只有 case_id/quality_status/turns(evidence_file,status,turn_index,error)，无轴 state/reason。"
                    "而 OldCardCase 要求逐题四轴 state+reason、SafetyCaseView/AxesCaseView 均要求该对象，"
                    "故四轴重评分/11 分诊逐题归属/27 unknown 可判化/敏感性带计数在现有留存物上不可执行。"
                ),
                "calls": {"network": 0, "socket": 0, "dns": 0, "provider": 0, "model": 0, "retrieval": 0, "real": 0},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
