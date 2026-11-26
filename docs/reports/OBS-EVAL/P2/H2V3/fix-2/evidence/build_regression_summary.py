"""汇总 fix-2 的回归结果（机读）：上一轮/上一轮修复的正例反例是否仍绿。

内容：
1. 逐文件 pytest 计数（重新跑一遍，保证可复算）；
2. fix-1/A 独立验收探针（13 例）的 ``failures`` 与出站计数；
3. safety-fix 两个探针（安全拒答 / 跨实体继承）在**本轮代码**上的结局（只取 kind/引用数/模型调用数，
   不搬答案文本）；
4. netguard 定向回执的计数。

输出：``regression-summary.json``。
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

REPO = pathlib.Path(r"D:\GPT项目\市场部AI知识库")
EVIDENCE = REPO / "docs/reports/OBS-EVAL/P2/H2V3/fix-2/evidence"
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
BACKEND = REPO / "backend"

FILES = [
    ("fix-2 A（本轮新增：记录范围不被资料缺失/歧义抢占）", "tests/rag/test_v3_fix2_record_scope_not_clarified.py"),
    ("fix-2 B（本轮新增：首轮显式实体不再判未记录）", "tests/rag/test_v3_fix2_first_turn_record_answer.py"),
    ("fix-1/A planner 多目标枚举", "tests/rag/test_v3_fix1_multi_target.py"),
    ("fix-1/B 业务日过滤", "tests/rag/test_v3_fix1_business_date_filter.py"),
    ("fix-1r1 纯指代仍澄清", "tests/rag/test_v3_fix1r1_anaphora_multi_target.py"),
    ("fix-1 产品接线", "tests/unit/test_v3_fix1_wiring.py"),
    ("safety-fix 安全拒答策略（拒答缺失修复）", "tests/unit/test_v3_safety_fix_policy.py"),
    ("safety-fix 端到端（含跨实体继承）", "tests/integration/test_v3_safety_fix_e2e.py"),
    ("多目标 trace 路径（observability）", "tests/observability/test_paths_e2e.py"),
]

_PASSED = re.compile(r"(\d+) passed")
_FAILED = re.compile(r"(\d+) failed")
_ERROR = re.compile(r"(\d+) error")


def run_pytest(target: str) -> dict[str, object]:
    completed = subprocess.run(
        [str(PYTHON), "-m", "pytest", target, "-q", "--tb=no"],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    tail = (completed.stdout or "").strip().splitlines()
    summary = next((line for line in reversed(tail) if "passed" in line or "failed" in line or "error" in line), "")
    passed = _PASSED.search(summary)
    failed = _FAILED.search(summary)
    error = _ERROR.search(summary)
    return {
        "target": target,
        "summary": summary.strip(),
        "passed": int(passed.group(1)) if passed else 0,
        "failed": int(failed.group(1)) if failed else 0,
        "errors": int(error.group(1)) if error else 0,
        "exit_code": completed.returncode,
    }


def _load(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def main() -> int:
    rows = [{"label": label, **run_pytest(target)} for label, target in FILES]

    planner = _load("A-planner-multi-target.json")
    regression = {
        "pytest": rows,
        "pytest_totals": {
            "passed": sum(row["passed"] for row in rows),
            "failed": sum(row["failed"] for row in rows),
            "errors": sum(row["errors"] for row in rows),
            "all_exit_zero": all(row["exit_code"] == 0 for row in rows),
        },
        "fix1_A_independent_probe": {
            "cases": len(planner.get("cases") or {}),
            "failures": planner.get("failures"),
            "outbound_attempts": len(planner.get("outbound_attempts") or []),
            "all_ok": planner.get("failures") == [],
        },
    }

    security = _load("probe-security-regression.json")["questions"]
    regression["safety_fix_security_probe"] = {
        label: {
            "kind": record.get("kind"),
            "model_calls": record.get("model_calls"),
            "citations": len(record.get("evidence") or []),
        }
        for label, record in security.items()
    }
    refused_positives = {label: record for label, record in security.items() if label.startswith("S")}
    answered_negatives = {label: record for label, record in security.items() if label.startswith("N")}
    regression["safety_fix_security_probe_positives_all_refused"] = all(
        record.get("kind") == "not_found" and int(record.get("model_calls") or 0) == 0 and not record.get("evidence")
        for record in refused_positives.values()
    )
    # 反例逐个记录，由报告按“与上一轮逐例相同”判读（不在此处对单个 case 硬编码期望）。
    regression["safety_fix_security_probe_negatives"] = {
        label: record.get("kind") for label, record in answered_negatives.items()
    }
    baseline_security = json.loads(
        (REPO / "docs/reports/OBS-EVAL/P2/H2V3/safety-fix/evidence/probe-security-after.json").read_text(
            encoding="utf-8"
        )
    )["questions"]
    regression["safety_fix_security_probe_identical_to_previous_round"] = all(
        baseline_security.get(label, {}).get("kind") == record.get("kind")
        and int(baseline_security.get(label, {}).get("model_calls") or 0) == int(record.get("model_calls") or 0)
        for label, record in security.items()
    ) and set(baseline_security) == set(security)

    entity = _load("probe-other-entity-regression.json")["cases"]
    entity_rows = {}
    for label, turns in entity.items():
        entity_rows[label] = [
            {
                "kind": turn.get("kind"),
                "stores": [item.get("store") for item in turn.get("evidence") or []],
                "items": [item.get("item") for item in turn.get("evidence") or []],
            }
            for turn in turns
        ]
    regression["safety_fix_entity_probe"] = entity_rows
    baseline_entity = json.loads(
        (REPO / "docs/reports/OBS-EVAL/P2/H2V3/safety-fix/evidence/probe-other-entity-after.json").read_text(
            encoding="utf-8"
        )
    )["cases"]
    regression["safety_fix_entity_probe_identical_to_previous_round"] = all(
        [(turn.get("kind"), sorted(str(item.get("store")) for item in turn.get("evidence") or [])) for turn in turns]
        == [
            (turn.get("kind"), sorted(str(item.get("store")) for item in turn.get("evidence") or []))
            for turn in (baseline_entity.get(label) or [])
        ]
        for label, turns in entity.items()
    ) and set(baseline_entity) == set(entity)

    netguard = _load("netguard-targeted-run.json")
    regression["netguard_targeted"] = {
        "counts": netguard["counts"],
        "all_controls_blocked": netguard["all_controls_blocked"],
        "external_attempts_during_session": netguard["external_attempts_during_session"],
        "exitstatus": netguard["exitstatus"],
        "proxy_env_removed": netguard["proxy_env_removed"],
    }

    (EVIDENCE / "regression-summary.json").write_text(
        json.dumps(regression, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "pytest_totals": regression["pytest_totals"],
                "fix1_A_probe": regression["fix1_A_independent_probe"],
                "security_positives_all_refused": regression["safety_fix_security_probe_positives_all_refused"],
                "security_negatives": regression["safety_fix_security_probe_negatives"],
                "security_identical": regression["safety_fix_security_probe_identical_to_previous_round"],
                "entity_identical": regression["safety_fix_entity_probe_identical_to_previous_round"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
