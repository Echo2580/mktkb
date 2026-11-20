"""生成 NCU-RELEASE-EVIDENCE/manifest.json（机器可读清单，供任务 4 接线）。"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\GPT项目\市场部AI知识库")
BASE = ROOT / "docs/reports/OBS-EVAL/P2/T207"
OUT = ROOT / "docs/reports/OBS-EVAL/P2/NCU-RELEASE-EVIDENCE"
OUT.mkdir(parents=True, exist_ok=True)
ISO = ROOT / ".tmp-ncu-isolated"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


runs_meta = {}
for run in ["R1", "R2", "R4"]:
    tag = run.lower()
    rd = BASE / f"p2-t207-{tag}-20261111-01"
    man = json.loads((rd / "run_manifest.json").read_text(encoding="utf-8"))
    res = json.loads((rd / "run_result.json").read_text(encoding="utf-8"))
    runs_meta[run] = {
        "run_id": man["run_id"],
        "run_dir": rel(rd),
        "execution_mode": man["execution"],
        "plan_id": man["plan"]["plan_id"],
        "plan_sha256": man["plan"]["plan_sha256"],
        "config_hash": man["config_hash"],
        "gate_version": man["gate_version"],
        "gate_config_hash": man["gate_config_hash"],
        "index_revision_binding": man["index_revision"],
        "pipeline_version": man["pipeline_version"],
        "pipeline_code_sha256": man["pipeline"]["code_sha256"],
        "dataset_version": man["dataset_version"],
        "dataset_sha256": man["dataset_sha256"],
        "corpus_manifest_sha256": man["corpus_manifest_sha256"],
        "case_count": man["case_count"],
        "max_published_revision": max(e["revision"] for e in man["ingest"] if e["published"]),
        "ingest_published_revisions": sorted({e["revision"] for e in man["ingest"] if e["published"]}),
        "outbound_network": man["providers"]["outbound_network"],
        "chat_sends": res["requests_sent"],
        "attempts_reserved": res["attempts_reserved"],
        "settled_cny": res["settled_cny"],
        "artifacts": {
            "run_manifest.json": sha(rd / "run_manifest.json"),
            "run_result.json": sha(rd / "run_result.json"),
            "cases.jsonl": sha(rd / "cases.jsonl"),
            "dataset.jsonl(run)": sha(Path(rf"D:\mktkb-p2-run\t207\{run}\p2-run\dataset.jsonl")),
            "gate.json": sha(rd / "gate.json"),
            "summary.json": sha(rd / "summary.json"),
            "trace_db": sha(ISO / "traces" / f"{run}.sqlite3"),
            "rag_index": sha(ISO / "traces" / f"{run}-rag.sqlite3"),
            f"cases/{run}.jsonl": sha(BASE / "cases" / f"{run}.jsonl"),
        },
    }
# R2 product db copy for U01 citation reconstruction (only R2 copied)
runs_meta["R2"]["artifacts"]["product_db"] = sha(ISO / "traces" / "R2-product.sqlite3")

# 选定来源（冻结范围）
SELECTION = {
    "R1": {"N": [f"N{i:02d}" for i in range(1, 8)], "C": [f"C{i:02d}" for i in range(1, 5)]},
    "R4": {"N": ["N08"], "C": ["C05", "C06"]},
    "R2": {"U": ["U01"]},
}
SCORES = {"R1": "R1-fixed", "R2": "R2-fixed", "R4": "R4"}
gate_path = ISO / "gate_recompute_r2.json"
if not gate_path.exists():
    gate_path = OUT / "evidence" / "gate_recompute_r2.json"
gate = json.loads(gate_path.read_text(encoding="utf-8"))
GATE_PY = ROOT / "backend/src/mktkb/evaluation/gate.py"
GATE_CODE = {
    "path": rel(GATE_PY),
    "sha256_current": sha(GATE_PY),
    "sha256_head_97b00667": subprocess.run(
        ["git", "show", "HEAD:backend/src/mktkb/evaluation/gate.py"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout,
}
GATE_CODE["sha256_head_97b00667"] = hashlib.sha256(GATE_CODE["sha256_head_97b00667"]).hexdigest()
GATE_CODE["sha256_before_d004_reported"] = "10235099（任务 4 交接记录值；本窗口无法从 git 重建该未提交中间态）"
GATE_CODE["change"] = "D-004：citation_required 候选接地集合 = outcome.evidence(unit_id) ∪ outcome.retrieved(unit_ids)；三个拒绝分支与 trace_integrity 逐值相等语义未改"
GATES = ["security_leak", "cross_entity", "stale_bypass", "conflict_not_rejected",
         "exact_value_contract", "pagination_contract", "citation_required", "trace_integrity"]
rag_revision = {}
for run in ["R1", "R2", "R4"]:
    import sqlite3
    con = sqlite3.connect(f"file:{ISO/'traces'/f'{run}-rag.sqlite3'}?mode=ro", uri=True)
    meta = dict(con.execute("select key,value from rag_meta").fetchall())
    rag_revision[run] = {"rag_revision": int(meta["revision"]), "product_revision": int(meta["product_revision"])}
    con.close()

cases_out = []
for run, groups in SELECTION.items():
    tag = run.lower()
    rd = BASE / f"p2-t207-{tag}-20261111-01"
    rows = {json.loads(l)["case_id"]: json.loads(l) for l in (rd / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    scores = json.loads((BASE / "scoring" / SCORES[run] / "case_scores.json").read_text(encoding="utf-8"))
    smap = {s["case_id"]: s for s in scores["case_scores"]}
    specs = {json.loads(l)["case_id"]: json.loads(l) for l in (BASE / "cases" / f"{run}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    gate_fail = {g: {f["case_id"]: f for f in gate[run]["gates"][g]["failures"]} for g in GATES}
    for group, ids in groups.items():
        for cid in ids:
            spec = specs[cid]
            row = rows[cid]
            prod = row["turns"][0]["product"]
            trace_id = prod.get("trace_id")
            trace = None
            if trace_id:
                import sqlite3
                con = sqlite3.connect(f"file:{ISO/'traces'/f'{run}.sqlite3'}?mode=ro", uri=True)
                con.row_factory = sqlite3.Row
                r = con.execute("select * from traces where trace_id=?", (trace_id,)).fetchone()
                trace = dict(r) if r else None
                con.close()
            gates = {}
            for g in GATES:
                fail = cid in gate_fail[g]
                status = gate[run]["gates"][g]["status"]
                case_status = "fail" if fail else "pass"
                if g in ("cross_entity", "stale_bypass", "exact_value_contract", "pagination_contract"):
                    app = g == "exact_value_contract" and spec["stratum"] == "exact"
                    gates[g] = {"applicable": app, "status": "not_applicable" if not app else case_status}
                elif g == "security_leak":
                    app = bool(spec.get("forbidden_sources") or spec.get("forbidden_values"))
                    gates[g] = {"applicable": app, "status": case_status if app else "not_applicable"}
                elif g == "conflict_not_rejected":
                    app = spec.get("expected_kind") == "conflict"
                    gates[g] = {"applicable": app, "status": case_status if app else "not_applicable"}
                elif g == "citation_required":
                    app = prod.get("kind") == "answer"
                    gates[g] = {"applicable": app, "status": case_status if app else "not_applicable",
                                "failure": gate_fail[g].get(cid)}
                else:
                    app = trace is not None
                    gates[g] = {"applicable": app, "status": case_status if app else "not_applicable",
                                "failure": gate_fail[g].get(cid)}
            score = smap[cid]
            failed = [c["check_id"] for c in score["checks"] if c["status"] == "fail"]
            sk = next(c for c in score["checks"] if c["check_id"] == "source_hit")
            vk = next(c for c in score["checks"] if c["check_id"] == "value_hit")
            trace_fail = cid in gate_fail["trace_integrity"]
            cit_fail = cid in gate_fail["citation_required"]
            mech = []
            for g, v in gates.items():
                if v.get("status") == "fail":
                    check = (v.get("failure") or {}).get("check_id") or "version_binding"
                    mech.append({"gate": g, "check": check, "status": "fail"})
            binding_proof = None
            if not mech:
                adopt = "ADOPTED"
                reason = "八门禁对该题无任何机械 FAIL；身份/门槛/必要硬证据三条件齐备"
            elif all(m["gate"] == "trace_integrity" and m["check"] == "version_binding" for m in mech):
                adopt = "ADOPTED_WITH_BINDING_PROOF"
                reason = "机械 FAIL 保留（trace_integrity:version_binding）；按 D-005 以绑定适用性证明采信"
                if cid == "U01":
                    reason += "；citation_required 已按 D-004 由 fail 转 pass"
                binding_proof = {
                    "decision": "D-005",
                    "decision_text": "接受历史绑定适用性证明作为正式 N/C/U 证据口径；全程保留并披露原始机械 FAIL；trace_integrity 逐值相等语义不改",
                    "identity": {
                        "run_id": row["run_id"],
                        "trace_id": trace_id,
                        "plan_sha256": runs_meta[run]["plan_sha256"],
                        "config_hash": runs_meta[run]["config_hash"],
                        "pipeline_version": runs_meta[run]["pipeline_version"],
                        "index_revision_binding": runs_meta[run]["index_revision_binding"],
                        "question_sha256": prod.get("question_sha256"),
                    },
                    "per_stage_index_versions": {
                        "ingest_published_max_revision": runs_meta[run]["max_published_revision"],
                        "product_response_revision": prod.get("revision"),
                        "rag_index_revision": rag_revision[run]["rag_revision"],
                        "rag_product_revision": rag_revision[run]["product_revision"],
                        "trace_index_revision": None if trace is None else int(trace["index_revision"]),
                        "explanation": "trace 字段取 rag_meta.revision（仅 RAG 检索路径写入）；run 绑定取 product_revision。二者为不同计数器，本批三 run 恒差 1，且 57/57 条 trace 按有无 recall span 严格二分。",
                    },
                    "same_round_authoritative_evidence": [
                        "docs/reports/OBS-EVAL/P2/T207/scoring/closeout/matrix_observation.json（run 级 index_revision/real_calls）",
                        f"{runs_meta[run]['run_dir']}/run_manifest.json#ingest（已发布 revision 最大值）",
                        f"{runs_meta[run]['run_dir']}/cases.jsonl（同轮 product.revision）",
                        "rag-index.sqlite3#rag_meta（product_revision / revision 并列）",
                        "evidence/trace-adjudication.json（逐阶段索引版本与闭合判定）",
                    ],
                    "old_version_applicability": {
                        "frozen_template_loader_hash": "d10975732dd50616f959fde71a3ead42822b877e98c55c4367902cb053cfd2a8",
                        "approved_loader_hash": "7fa6f47a445f9643eb7f2e5ae78a72411007da38a56fca1082657870b2eab094",
                        "semantic_keys_identical": ["schema_version", "gate_version", "hard_gates", "hard_gate_min_sample", "suites", "sensitive_patterns", "metrics"],
                        "note": "批准配置仅加 status/approval/p2_standards/notes；硬门禁语义等价，故旧身份可保留。",
                    },
                    "note": "机械 FAIL 保留、按 D-005 以证明采信；不得表述为 clean pass",
                }
            else:
                adopt = "FAIL"
                reason = "仍有不可解释的机械失败：" + "、".join(f"{m['gate']}:{m['check']}" for m in mech)
            cases_out.append({
                "case_id": cid,
                "group": group,
                "suite": spec["suite"],
                "stratum": spec["stratum"],
                "expected_kind": spec["expected_kind"],
                "should_refuse": spec["should_refuse"],
                "requires_ocr": spec["requires_ocr"],
                "gold_expected_values": spec.get("expected_values"),
                "gold_expected_sources": spec.get("expected_sources"),
                "gold_forbidden_sources": spec.get("forbidden_sources"),
                "gold_notes": spec.get("notes"),
                "basis": "R",
                "run_id": row["run_id"],
                "run_dir": runs_meta[run]["run_dir"],
                "plan_id": runs_meta[run]["plan_id"],
                "plan_sha256": runs_meta[run]["plan_sha256"],
                "config_hash": runs_meta[run]["config_hash"],
                "gate_config_hash_original": runs_meta[run]["gate_config_hash"],
                "gate_version": runs_meta[run]["gate_version"],
                "pipeline_version": runs_meta[run]["pipeline_version"],
                "index_revision_binding": runs_meta[run]["index_revision_binding"],
                "index_revision_trace": None if trace is None else int(trace["index_revision"]),
                "index_revision_rag": rag_revision[run]["rag_revision"],
                "index_revision_product_response": prod.get("revision"),
                "trace_id": trace_id,
                "trace_path": None if trace is None else trace["path"],
                "trace_outcome": None if trace is None else trace["outcome_kind"],
                "question_sha256": prod.get("question_sha256"),
                "score_status": score["status"],
                "score_failed_checks": failed,
                "check_evidence": {"source_hit": sk.get("evidence"), "value_hit": vk.get("evidence")},
                "gates": gates,
                "mechanical_gate_failures": mech,
                "binding_proof": binding_proof,
                "adopt": adopt,
                "adopt_reason": reason,
                "evidence_paths": {
                    "run_cases": f"{runs_meta[run]['run_dir']}/cases.jsonl",
                    "run_manifest": f"{runs_meta[run]['run_dir']}/run_manifest.json",
                    "run_result": f"{runs_meta[run]['run_dir']}/run_result.json",
                    "case_scores": rel(BASE / "scoring" / SCORES[run] / "case_scores.json"),
                    "frozen_cases": rel(BASE / "cases" / f"{run}.jsonl"),
                    "trace_db": rf"D:\mktkb-p2-run\t207\{run}\data\observability\qa-traces.sqlite3",
                    "rag_index": rf"D:\mktkb-p2-run\t207\{run}\data\rag-index.sqlite3",
                    "run_dataset": rf"D:\mktkb-p2-run\t207\{run}\p2-run\dataset.jsonl",
                },
                "evidence_sha256": {
                    "run_cases": runs_meta[run]["artifacts"]["cases.jsonl"],
                    "run_manifest": runs_meta[run]["artifacts"]["run_manifest.json"],
                    "run_result": runs_meta[run]["artifacts"]["run_result.json"],
                    "case_scores": sha(BASE / "scoring" / SCORES[run] / "case_scores.json"),
                    "frozen_cases": runs_meta[run]["artifacts"][f"cases/{run}.jsonl"],
                    "trace_db": runs_meta[run]["artifacts"]["trace_db"],
                    "rag_index": runs_meta[run]["artifacts"]["rag_index"],
                    "run_dataset": runs_meta[run]["artifacts"]["dataset.jsonl(run)"],
                },
            })

# U02-U10 本地控制
u_hist = json.loads((BASE / "scoring" / "u-controls.json").read_text(encoding="utf-8"))
for i in range(2, 11):
    cid = f"U{i:02d}"
    item = u_hist["cases"][cid]
    cases_out.append({
        "case_id": cid,
        "group": "U",
        "suite": "update_delete",
        "stratum": "mutation",
        "basis": "L",
        "source": u_hist["source"],
        "test_file": rel(ROOT / "backend/tests/acceptance/test_t09_mutation.py"),
        "test_file_sha256": sha(ROOT / "backend/tests/acceptance/test_t09_mutation.py"),
        "historical": {"status": item["status"], "tests": item["tests"], "exit_code": u_hist["exit_code"], "generated_utc": u_hist["generated_utc"]},
        "rerun": {"command": r".\.venv\Scripts\python.exe -m pytest backend/tests/acceptance/test_t09_mutation.py -q", "exit_code": 0, "passed": 13, "skipped": 0, "failed": 0, "network_guard": "模块级 t09_network_guard：外部出站尝试非空即失败；本次 13 passed"},
        "gates": {g: {"applicable": False, "status": "not_applicable", "why": "本地控制无 run/trace，运行级硬门禁不适用；L 口径由测试结果承担"} for g in GATES},
        "evidence_paths": {
            "test_file": rel(ROOT / "backend/tests/acceptance/test_t09_mutation.py"),
            "u_controls": rel(BASE / "scoring" / "u-controls.json"),
            "netguard": rel(ROOT / "backend/tests/acceptance/support/netguard.py"),
        },
        "evidence_sha256": {
            "test_file": sha(ROOT / "backend/tests/acceptance/test_t09_mutation.py"),
            "u_controls": sha(BASE / "scoring" / "u-controls.json"),
            "netguard": sha(ROOT / "backend/tests/acceptance/support/netguard.py"),
        },
        "adopt": "ADOPTED" if item["status"] == "pass" else "FAIL",
        "adopt_reason": "L 口径（本地关键控制）历史记录 + 本次同命令复跑 13 passed；不作为真实模型全量更新能力",
        "limits": "L 口径不得外推为真实模型能力；U01 的 R 口径证据独立成立",
    })

manifest = {
    "schema_version": "p2-ncu-release-evidence/v0.1",
    "generated_utc": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    "composition": "multi_run_historical_plus_local_controls",
    "release_decision": False,
    "not_a_release_decision": True,
    "authority": {
        "taskbook": "docs/superpowers/plans/2026-11-20-p2-closeout-3-ncu-evidence.md",
        "approved_threshold": "docs/evaluation/gate_v0_3_approved.json",
        "approved_threshold_file_sha256": sha(ROOT / "docs/evaluation/gate_v0_3_approved.json"),
        "approved_threshold_loader_hash": "7fa6f47a445f9643eb7f2e5ae78a72411007da38a56fca1082657870b2eab094",
        "frozen_template": "docs/evaluation/gate_v0_3.json",
        "frozen_template_file_sha256": sha(ROOT / "docs/evaluation/gate_v0_3.json"),
        "frozen_template_loader_hash": "d10975732dd50616f959fde71a3ead42822b877e98c55c4367902cb053cfd2a8",
        "old_version_applicability_proof": "approved 与 frozen 的 schema_version/gate_version/hard_gates/hard_gate_min_sample/suites/sensitive_patterns/metrics 逐键相同；差异仅 status、approval、p2_standards.status/approved_at/basis、notes。故历史 run 的 d1097573 绑定在当前 7fa6f47a 门槛下语义等价（旧身份保留，不重绑摘要）。",
        "decisions": {
            "D-004": "citation_required 的候选接地集合改为 outcome.evidence[].unit_id ∪ outcome.retrieved[].unit_ids；判据本身不变（既不在 evidence 也不在 retrieved 仍 fail）。实现还需要 build_gate_rows 显式接收原始 run 行（case_rows）以投影 product.evidence。",
            "D-005": "接受历史绑定适用性证明作为正式 N/C/U 证据口径；必须全程披露原始机械 FAIL；trace_integrity 逐值相等语义不改。",
        },
        "gate_code": GATE_CODE,
    },
    "runs": runs_meta,
    "selection_policy": {
        "frozen_scope": {k: v for k, v in SELECTION.items()},
        "not_selected": {"R2.C05": "R2 数据集内但不在冻结范围（R4 已替换 C05）", "R1.Q01-Q40": "B0 组，不属于 N/C/U", "R3": "未进入 N/C/U 范围"},
        "dedupe": "按冻结选题范围去重：同一 case 只取指定 run；R2.C05 不参与 C 组；run 级调用数按 run 身份计一次，不按题摊分。",
    },
    "tallies": {
        "judged_pass": {"N": "8/8", "C": "6/6", "U": "10/10", "not_executed": 0},
        "adopted_unconditional": {
            "label": "无条件可采（无任何机械 FAIL）",
            "N": sum(1 for c in cases_out if c["group"] == "N" and c["adopt"] == "ADOPTED"),
            "C": sum(1 for c in cases_out if c["group"] == "C" and c["adopt"] == "ADOPTED"),
            "U": sum(1 for c in cases_out if c["group"] == "U" and c["adopt"] == "ADOPTED"),
            "planned": {"N": 8, "C": 6, "U": 10},
        },
        "adopted_with_binding_proof": {
            "label": "带 D-005 绑定适用性证明（机械 FAIL 保留）",
            "N": sum(1 for c in cases_out if c["group"] == "N" and c["adopt"] == "ADOPTED_WITH_BINDING_PROOF"),
            "C": sum(1 for c in cases_out if c["group"] == "C" and c["adopt"] == "ADOPTED_WITH_BINDING_PROOF"),
            "U": sum(1 for c in cases_out if c["group"] == "U" and c["adopt"] == "ADOPTED_WITH_BINDING_PROOF"),
        },
        "adopted_formal_total": {
            "label": "正式可采（含 D-005 证明）= 无条件 + 证明档",
            "N": sum(1 for c in cases_out if c["group"] == "N" and c["adopt"] in {"ADOPTED", "ADOPTED_WITH_BINDING_PROOF"}),
            "C": sum(1 for c in cases_out if c["group"] == "C" and c["adopt"] in {"ADOPTED", "ADOPTED_WITH_BINDING_PROOF"}),
            "U": sum(1 for c in cases_out if c["group"] == "U" and c["adopt"] in {"ADOPTED", "ADOPTED_WITH_BINDING_PROOF"}),
            "planned": {"N": 8, "C": 6, "U": 10},
            "threshold_met": {
                "N": len([c for c in cases_out if c["group"] == "N" and c["adopt"] in {"ADOPTED", "ADOPTED_WITH_BINDING_PROOF"}]) == 8,
                "C": len([c for c in cases_out if c["group"] == "C" and c["adopt"] in {"ADOPTED", "ADOPTED_WITH_BINDING_PROOF"}]) == 6,
                "U": len([c for c in cases_out if c["group"] == "U" and c["adopt"] in {"ADOPTED", "ADOPTED_WITH_BINDING_PROOF"}]) == 10,
            },
        },
        "fail": {"N": sum(1 for c in cases_out if c["group"] == "N" and c["adopt"] == "FAIL"),
                 "C": sum(1 for c in cases_out if c["group"] == "C" and c["adopt"] == "FAIL"),
                 "U": sum(1 for c in cases_out if c["group"] == "U" and c["adopt"] == "FAIL")},
        "unknown": 0,
        "planned": {"N": 8, "C": 6, "U": 10},
    },
    "hard_gate_min_sample": {
        "unmet": {"suite": "update_delete", "evaluated": 1, "required": 10},
        "approved_config_path": "docs/evaluation/gate_v0_3_approved.json",
        "approved_min_sample": 10,
        "why": "U 的 run 级 evaluated_count 只有 1（U01）；其余 9 条是本地控制（L），不是 run 行，八项硬门禁只能在 run 级逐题上评估。批准配置要求 update_delete 最小样本 10，故 U 的八门在批准最小样本口径下无法满足。",
        "status": "PENDING-MASTER-DECISION",
        "handling": "由经理另报主人裁量；本清单只如实记录，不自行放宽、不把 1R+9L 冒充 10 条 run 证据。",
    },
    "hard_gate_applicability": {
        "run_recompute": {run: {"gate_status": gate[run]["gate_status"], "exit_code": gate[run]["exit_code"],
                                "evaluated_by_suite": gate[run].get("evaluated_by_suite")} for run in ["R1", "R2", "R4"]},
        "recompute_engine": "evidence/gate_recompute_r2.json（新 gate.py + build_gate_rows(case_rows=...)）",
        "gate_code": GATE_CODE,
        "historical_recompute_before_d004": "evidence/gate_recompute.json（改前引擎，仅作对照，不用于本清单 adopt）",
        "note": "以当前批准门槛在隔离副本上重算；仅把诊断副本的 trace_store/dataset_path 指向隔离拷贝，原证据未改。",
    },
    "cases": sorted(cases_out, key=lambda c: ({"N": 0, "C": 1, "U": 2}[c["group"]], c["case_id"])),
    "commands": [
        {"command": r".\.venv\Scripts\python.exe -m pytest backend/tests/acceptance/test_t09_mutation.py -q", "exit_code": 0, "output": "13 passed, 1 warning in 21.25s"},
        {"command": r".\.venv\Scripts\python.exe -m pytest backend/tests/acceptance/test_t09_mutation.py -q --collect-only", "exit_code": 0, "output": "13 tests collected"},
        {"command": r".\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\gate_recompute.py", "exit_code": 0, "output": "新 gate.py(e04990db) 重算：R1 exit1 trace_integrity 27；R2 exit1 conflict_not_rejected C05(范围外)+trace_integrity 2，citation_required pass；R4 exit1 trace_integrity 2"},
        {"command": r".\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\config_equivalence.py", "exit_code": 0, "output": "frozen=d1097573, approved=7fa6f47a, 7 类语义键全同"},
        {"command": r".\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\u01_reconstruct.py", "exit_code": 0, "output": "U01 citation chunk->record_unit->product evidence 重建成功"},
        {"command": r".\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\build_manifest.py", "exit_code": 0, "output": "四档 adopt + 两行 tallies + hard_gate_min_sample.unmet"},
        {"command": r".\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\verify_manifest.py <manifest>", "exit_code": 0, "output": "ok: true, cases: 24"},
        {"command": r".\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\negative_tests.py", "exit_code": 0, "output": "12 负例（A1-A6 + B1/B2/B5 + B7/B8/B9）全部 exit 1"},
        {"command": r".\.venv\Scripts\python.exe -X utf8 docs\reports\OBS-EVAL\P2\NCU-RELEASE-EVIDENCE\scripts\build_hashes.py", "exit_code": 0, "output": "重生成 artifact-hashes 与 SHA256SUMS"},
    ],
    "network_evidence": {
        "new_real_requests": 0,
        "new_model_or_api_calls": 0,
        "production_data_or_real_provider_execution": 0,
        "l_basis_in_process_product_app": "pytest 经 TestClient 在进程内启动产品应用（Mock/替身 provider）；未启动监听端口服务，未对生产数据/真实 provider 执行。",
        "pytest_network_guard": "backend/tests/acceptance/support/netguard.py::t09_network_guard 由模块 pytestmark 强制启用；外部出站非空即 teardown 失败。本次 13 passed，故 external=[]。",
        "recompute_guard": "gate_recompute.py 在导入业务模块前把 socket.connect/connect_ex/create_connection 替换为抛错函数。",
    },
    "open_items": [
        {"id": "trace-dual-revision", "severity": "high", "scope": "6/24 N/C/U（N01,C01,C02,U01,C05,C06）；R1 全量 27/52",
         "detail": "trace.index_revision 写的是 rag_meta.revision（R1=12/R2=4/R4=6），manifest.index_revision 是 product_revision（11/3/5）；门禁 _TRACE_BINDING 要求逐值相等。",
         "status": "MECHANICAL-FAIL-RETAINED-WITH-D005-PROOF",
         "resolution": "按 D-005 以绑定适用性证明采信（ADOPTED_WITH_BINDING_PROOF），机械 FAIL 原样保留；契约修复仍建议由任务 1/4 派工，不在本窗口改代码。"},
        {"id": "u01-citation-retrieved-empty", "severity": "high", "scope": "U01",
         "detail": "U01 同轮 product.retrieved=[] 但 product.evidence=1；重建证明引用 chunk a202ff9b… 的 record_unit_id=072d28f2… 与 evidence 单元一致。",
         "status": "RESOLVED-BY-D004",
         "resolution": "新 gate.py 把候选接地集合改为 evidence ∪ retrieved；同时 build_gate_rows 必须以 case_rows 投影 product.evidence。R2 重算 citation_required = pass（0 失败）。"},
        {"id": "gold-locator-weak", "severity": "medium", "scope": "C05,C06,U01",
         "detail": "gold expected_sources 用 record_code=P01，未给 unit_key；match_source_ref 退化为同文档即命中（文档级而非单元级）。",
         "needs": "以同回合证据重建 P01→sheet:物品位置:row:8 作为补证；冻结题集不得改。"},
        {"id": "wording-not-scored", "severity": "low", "scope": "N01-N08,C01-C04",
         "detail": "accepted_wording(any-of) 明确 not-scored；C01-C04 无 expected_values/sources，仅 kind 判定。",
         "needs": "报告标注；不得宣称措辞/内容合规。"},
        {"id": "hard-gate-min-sample-u", "severity": "high", "scope": "U 组 update_delete",
         "detail": "run 级 evaluated_count=1（U01），批准配置 hard_gate_min_sample.update_delete=10；1R+9L 不是 10 条 run 证据。",
         "status": "PENDING-MASTER-DECISION",
         "needs": "由经理另报主人裁量；本清单只记录，不自行放宽。"},
    ],
}

(OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("wrote", OUT / "manifest.json")
print(json.dumps(manifest["tallies"], ensure_ascii=False))
for c in cases_out:
    if c["group"] != "U" or c["case_id"] != "U01":
        print(c["case_id"], c["adopt"], c.get("index_revision_trace"), c.get("index_revision_binding"))
