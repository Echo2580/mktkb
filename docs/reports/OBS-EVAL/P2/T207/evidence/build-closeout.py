"""T207 A 路径：只读公开运行重评分、固定范围取证与账本快照；不调用产品。"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend/src"))
os.environ["MKTKB_NO_DOTENV"] = "1"


def deny_network(*args, **kwargs):
    raise AssertionError("closeout_network_forbidden")


socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network

from mktkb.evaluation.p2_authorization import read_ledger_snapshot  # noqa: E402
from mktkb.evaluation.p2_score_run import (  # noqa: E402
    build_matrix_observation, load_cases_file, load_document_codes, load_u_controls, score_run,
)

BASE = ROOT / "docs/reports/OBS-EVAL/P2/T207"
OUT = BASE / "scoring/closeout"
FIXED = {
    "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl":
        "1648405845fd5e19b593e610b92f8505fdfd78a9e57079648dc14673576785d7",
    "docs/evidence/LOCAL-R1-20261101/budget/budget.json":
        "79b21700b630be92148e2a8498ed47386dab08d6daa401601dc3d22a910b1a9e",
    "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json":
        "3ed427f42ac2eeedff489505b94f730eadba1dc38f1b9adecf94d25750b02a7c",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


before = {name: sha(ROOT / name) for name in FIXED}
assert before == FIXED, "fixed_files_drifted"
codes = load_document_codes(BASE / "cases/document-codes.json")
# 固定政策来自 T207 PM §11–12：只用 R4 替换三条既定重测范围，保留两条 B0 失败。
selection = {
    "R1-fixed": ("R1", {f"Q{i:02d}" for i in range(1, 41)}
                 | {f"N{i:02d}" for i in range(1, 8)} | {f"C{i:02d}" for i in range(1, 5)}),
    "R4": ("R4", {"N08", "C05", "C06"}),
    "R2-fixed": ("R2", {"U01"}),
}
bundles, inputs, rescore_checks = [], [], []
failures = []
for label, (run, selected_ids) in selection.items():
    run_dir = BASE / f"p2-t207-{run.lower()}-20261111-01"
    cases_path = BASE / f"cases/{run}.jsonl"
    saved_path = BASE / f"scoring/{label}/case_scores.json"
    bundle = score_run(run_dir, cases=load_cases_file(cases_path), document_codes=codes)
    saved = read(saved_path)
    current = {item.case_id: item.status for item in bundle.scores}
    assert current == {item["case_id"]: item["status"] for item in saved["case_scores"]}
    assert bundle.execution_mode == saved["execution_mode"] == "live"
    assert bundle.run_id == saved["run_id"] and bundle.config_hash == saved["config_hash"]
    assert bundle.index_revision == saved["index_revision"] and bundle.real_calls == saved["real_calls"]
    selected = tuple(item for item in bundle.scores if item.case_id in selected_ids)
    assert {item.case_id for item in selected} == selected_ids
    bundles.append(dataclasses.replace(bundle, scores=selected, run_dir=run_dir.relative_to(ROOT)))
    rescore_checks.append({"source": label, "cases_rechecked": len(current), "status_equal": True,
                           "selected_ids": sorted(selected_ids), "selected_count": len(selected)})
    for item in selected:
        if item.status != "pass":
            failures.append({"case_id": item.case_id, "status": item.status,
                             "failed_checks": [c["check_id"] for c in item.checks if c["status"] == "fail"]})
    for path in (cases_path, saved_path, run_dir / "cases.jsonl", run_dir / "run_manifest.json"):
        inputs.append({"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)})

controls_path = BASE / "scoring/u-controls.json"
controls = load_u_controls(controls_path)
assert controls["exit_code"] == 0
assert set(controls["cases"]) == {f"U{i:02d}" for i in range(1, 11)}
assert all(item["status"] == "pass" for item in controls["cases"].values())
matrix = build_matrix_observation(bundles, u_controls=controls, u_real_run="R2")
assert matrix["duplicated_cases"] == {}
for group, planned, passed in (("b0", 40, 38), ("negative", 8, 8), ("boundary", 6, 6), ("u", 10, 10)):
    tally = matrix["tallies"][group]
    assert (tally["planned"], tally["passed"]) == (planned, passed)
    assert tally["errors"] == tally["not_executed"] == tally["missing"] == 0
assert {item["case_id"] for item in failures} == {"Q25", "Q33"}
assert len(matrix["cases"]) == 55
assert matrix["release_decision"] is False
matrix["selection_policy"] = {
    "authority": "T207-PM-decisions-01.md §11–12、§14；主人选择 A 收口",
    "scope": {label: sorted(ids) for label, (_, ids) in selection.items()},
    "why": "R4 仅替换预先确定的 N08/C05/C06；不按分数挑选，不删除 Q25/Q33 失败。",
}
matrix["notes"] = [
    "多 run、不同代码时点/配置/索引的组合观测；不是同版本完整 baseline，也不是放行结论。",
    "R1-fixed 取 B0/N01-N07/C01-C04；R4 取 N08/C05/C06；R2-fixed 仅取 U01。",
    "U01 是计划绑定真实 smoke；U02-U10 是本地控制，不代表真实模型全量更新验证。",
    "runs.real_calls 是原完整 run 的出站量，不是所选 case 的分摊；逐题 real_calls=0 不等于零调用。",
    "update_delete 是真实行覆盖（1/10）；u 是 U 证据表（R1+L9，10/10）；两者不可混读。",
    "N/C 的 any-of 措辞未自动评分；版本禁用来源代号存在基槽映射盲区，见最终报告。",
]
snapshot = dataclasses.asdict(read_ledger_snapshot())
h2_card_path = BASE / "p2-t207-h2-20261111-01-aborted/holdout_scorecard.json"
h2 = read(h2_card_path)
assert [h2[k] for k in ("total", "executed", "passed", "failed", "errors")] == [30, 21, 11, 10, 9]
assert h2["release_ready"] is False
run_accounting = []
for tag in ("r1", "r2", "r3", "r4", "h2"):
    suffix = "-aborted" if tag == "h2" else ""
    result_path = BASE / f"p2-t207-{tag}-20261111-01{suffix}/run_result.json"
    result = read(result_path)
    run_accounting.append({
        "run": tag.upper(), "status": result["status"],
        "reservations": result["attempts_reserved"], "chat_sends": result["requests_sent"],
        "conservative_accounted_cny": round(sum(result["attempts_by_center_cny"].values()), 7),
        "answer_side_settled_cny": round(result["settled_cny"], 7),
    })
    inputs.append({"path": result_path.relative_to(ROOT).as_posix(), "sha256": sha(result_path)})
assert sum(item["reservations"] for item in run_accounting) == 227
assert abs(sum(item["conservative_accounted_cny"] for item in run_accounting) + 0.5713583
           - snapshot["p2_stage_accounted_cny"]) < 1e-8
h2_aggregate_path = h2_card_path.with_name("holdout_aggregate.json")
h2_aggregate = read(h2_aggregate_path)
h2_started = h2_aggregate["cases"]["executed"]
assert h2_started == 22 and h2_aggregate["cases"]["with_error"] == 1
after = {name: sha(ROOT / name) for name in FIXED}
assert after == before
for path in (controls_path, h2_card_path, h2_aggregate_path, BASE / "cases/document-codes.json"):
    inputs.append({"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)})
write(OUT / "matrix_observation.json", matrix)
write(OUT / "verification.json", {
    "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "schema_version": "p2-t207-closeout-verification/v0.1", "new_real_calls": 0,
    "network_policy": "socket connect/connect_ex/create_connection denied; no product execution",
    "fixed_files_before": before, "fixed_files_after": after, "ledger_snapshot": snapshot,
    "run_accounting": run_accounting,
    "u_controls_reexecution": "本次宿主复跑在B0构建阶段无进展，已中止；这里只核对原控制产物，不声称本次复跑通过",
    "inputs": inputs, "public_rescore": rescore_checks, "remaining_public_failures": failures,
    "exact_passed": sum(s.status == "pass" and s.stratum == "exact" for b in bundles for s in b.scores),
    "ocr_passed": sum(s.status == "pass" and s.requires_ocr for b in bundles for s in b.scores),
    "h2": {k: h2[k] for k in ("total", "executed", "passed", "failed", "errors", "by_stratum",
                               "hard_failures", "release_ready", "threshold_met")},
    "h2_execution": {"cases_started": h2_started, "cases_with_error": 1,
                     "cases_not_started": 30 - h2_started, "cases_scored": h2["executed"]},
    "h2_status": "aborted/未达标；errors=9含1题出错+8题未尝试，不能将9全部称为从未尝试",
})
print(json.dumps({"ok": True, "tallies": matrix["tallies"], "remaining_public_failures": failures,
                  "fixed_files_unchanged": True, "new_real_calls": 0}, ensure_ascii=False))
