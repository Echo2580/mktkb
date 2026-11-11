
"""P2-T207-FIX-A-R1 独立复验探针（零真实调用 / 零出网；只读仓库 + TEMP 产物）。

A numbers  —— 逐项复算 cost/runbook/template/A-report 的数值（不引用开发自述）。
B cli      —— p2-h2-plan 的 plan_id/规模（合成元数据，计划写 TEMP）；p2-score holdout 的
              两输入缺失/冲突/单输入聚合（合成封存数据集，TEMP）。
C h2state  —— 产品 Mock 路径独立重跑 H2 灌库（T207-ingest-plan-H2.json 的 12 source），
              逐文档/版本核对终态、假设、批数 B=sum(ceil(texts/5))、post_counters=0；
              另跑 13 source（+V02）验证 "+1 source => B=15" 的最小替代说法。

用法（仓库根）：.venv/Scripts/python.exe -B -X utf8 <this> [--out-h2 <json>]
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[7]  # .../T207-FIX-A-R1/evidence/verify/<this> -> 仓库根
sys.path.insert(0, str(REPO / "backend" / "src"))
PY = sys.executable
TMP = Path(tempfile.mkdtemp(prefix="p2-r1-verify-"))
BT = chr(96)


def sha256(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def sha16(p) -> str:
    return sha256(p)[:16]


def nlines(p) -> int:
    return len(Path(p).read_text(encoding="utf-8").splitlines())


def close(a, b, tol=1e-9) -> bool:
    return abs(float(a) - float(b)) <= tol


def cli(*args, env_extra=None, timeout=900):
    env = {k: v for k, v in os.environ.items() if not k.startswith("MKTKB_P2_HOLDOUT")}
    env["PYTHONPATH"] = str(REPO / "backend" / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    done = subprocess.run(
        [PY, "-B", "-X", "utf8", "-m", "mktkb.evaluation.cli", *args],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=env, timeout=timeout,
    )
    payload = None
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                pass
    return {"exit": done.returncode, "stdout": done.stdout[-4000:], "stderr": done.stderr[-2000:], "payload": payload}


# --------------------------------------------------------------------------- #
# A. 数值独立复算（cost / runbook / template / A report §1）
# --------------------------------------------------------------------------- #
def section_numbers() -> dict:
    from mktkb.evaluation import p2_authorization as pa
    from mktkb.evaluation.p2_contracts import (
        CHAT_COMPLETION_TOKENS_CAP, CHAT_INPUT_PRICE_FLOOR, CHAT_OUTPUT_PRICE_FLOOR,
        CHAT_PROMPT_TOKENS_CAP, EMBEDDING_TOTAL_TOKENS_CAP, EMBEDDING_UNIT_PRICE_FLOOR,
        HARD_MAX_REQUESTS, P2RunPlan,
        RERANK_TOTAL_TOKENS_CAP, RERANK_UNIT_PRICE_FLOOR,
    )
    from mktkb.evaluation.p2_contracts import OCR_TEXT_PRICE_CNY, OCR_TABLE_PRICE_CNY
    from mktkb.evaluation.p2_holdout_plan import H2_DEFAULT_PLAN_ID

    chat = (float(CHAT_PROMPT_TOKENS_CAP) * float(CHAT_INPUT_PRICE_FLOOR) / 1e6
            + float(CHAT_COMPLETION_TOKENS_CAP) * float(CHAT_OUTPUT_PRICE_FLOOR) / 1e6)
    embed = float(EMBEDDING_TOTAL_TOKENS_CAP) * float(EMBEDDING_UNIT_PRICE_FLOOR) / 1e6
    rerank = float(RERANK_TOTAL_TOKENS_CAP) * float(RERANK_UNIT_PRICE_FLOOR) / 1e6
    rnd = chat + chat + embed + rerank

    ledger = REPO / "docs/evidence/LOCAL-R1-20261101/budget/live-ledger.jsonl"
    budget = REPO / "docs/evidence/LOCAL-R1-20261101/budget/budget.json"
    go = REPO / "docs/evidence/LOCAL-R1-20261101/PM/P2-LIVE-GO.json"
    before = {"ledger": sha256(ledger), "budget": sha256(budget), "go": sha256(go),
              "bytes": ledger.stat().st_size, "lines": nlines(ledger)}
    snap = pa.read_ledger_snapshot()
    main_plan = json.loads((REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-plan-v0_1.json").read_text(encoding="utf-8"))
    plan = P2RunPlan.from_dict(main_plan)
    pre = pa.preflight_p2(plan, snap)
    after = {"ledger": sha256(ledger), "budget": sha256(budget), "go": sha256(go)}

    by_op = dict(plan.requests_by_operation())
    ocr_worst = 0.0
    ocr_items = [i for i in plan.items if i.operation == "ocr"]
    for item in ocr_items:
        model = str(getattr(item.price_profile, "model", ""))
        unit = OCR_TEXT_PRICE_CNY if model == "GeneralAccurateOCR" else OCR_TABLE_PRICE_CNY
        ocr_worst += item.requests * float(unit)

    # cost §3：三次 run（回合 4 项 + 各自灌库批；R1 另含 12 页 OCR）
    r1 = 52 * rnd + 22 * embed + ocr_worst
    r2 = 2 * rnd + 7 * embed
    r3 = 1 * rnd + 2 * embed
    h2_turn = 36 * rnd
    h2_ingest14 = 14 * embed

    stage_acc = float(snap.p2_stage_accounted_cny)
    accounted = float(snap.accounted_cny)
    stage_alloc = float(snap.stage_allocations_cny["P2-LIVE"])
    total_limit = float(snap.total_limit_cny)
    req = {"used": snap.reservation_count, "public": 263, "h2_turns": 144, "h2_ingest": 14,
           "t208": math.floor(3.00 / chat), "t900": math.floor(2.00 / chat)}
    subtotal = sum(req.values())
    corpus_req = 547 + 263 + 144 + 994
    corpus_cny = stage_acc + (r1 + r2 + r3) + h2_turn + 994 * embed

    # A report §1 表逐文件复算
    report = (REPO / "docs/reports/OBS-EVAL/P2/T207-FIX-A/report.md").read_text(encoding="utf-8")
    section = report.split("## 1 改动清单", 1)[1].split("## 2", 1)[0]
    rows = []
    for line in section.splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or "sha16" in cells[2]:
            continue
        names = re.findall(BT + "([^" + BT + "]+)" + BT, cells[0])
        if not names:
            continue
        rows.append({"cell_name": cells[0], "names": names, "num_cell": cells[1], "sha_cell": cells[2]})

    def expand(row):
        """把 report 表里的合并行（test_p2_{a,b,c}.py）展开成逐文件三行。"""
        shas = re.findall(r"[0-9a-f]{16}", row["sha_cell"])
        nums = re.findall(r"\d+", row["num_cell"])
        names = row["names"]
        if len(names) == 1 and "{" in names[0]:
            head, rest = names[0].split("{", 1)
            body, tail = rest.split("}", 1)
            parts = body.split(",")
            return [{"name": head + part + tail,
                     "doc_lines": int(nums[index]) if len(nums) > index else None,
                     "doc_sha16": shas[index] if len(shas) > index else None}
                    for index, part in enumerate(parts)]
        return [{"name": names[0],
                 "doc_lines": int(nums[0]) if nums else None,
                 "doc_sha16": shas[0] if shas else None}]

    checked = []
    for row in rows:
        for item in expand(row):
            if "*" in item["name"]:
                continue
            candidates = [
                REPO / item["name"],
                REPO / "backend" / item["name"],
                REPO / "backend" / "src" / "mktkb" / item["name"],
                REPO / "backend" / "tests" / "evaluation" / item["name"],
                REPO / "backend" / "tests" / "integration" / item["name"],
            ]
            cand = next((p for p in candidates if p.is_file()), None)
            checked.append({
                "name": item["name"], "found": cand is not None,
                "doc_lines": item["doc_lines"], "real_lines": nlines(cand) if cand else None,
                "doc_sha16": item["doc_sha16"], "real_sha16": sha16(cand) if cand else None,
            })
    template = json.loads((REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-plan-h2-v0_1.template.json").read_text(encoding="utf-8"))
    go_h2 = json.loads((REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-GO-h2.CANDIDATE-DRAFT.json").read_text(encoding="utf-8"))
    runbook = (REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-runbook.md").read_text(encoding="utf-8")
    cost = (REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-cost-and-quota.md").read_text(encoding="utf-8")
    tpl = template["scale"]

    return {
        "prices": {"chat": round(chat, 6), "embed": round(embed, 6), "rerank": round(rerank, 6),
                   "round4": round(rnd, 6), "doc": {"chat": 0.018688, "embed": 0.002048,
                                                    "rerank": 0.0048, "round4": 0.044224}},
        "ledger": {"before": before, "after": after, "unchanged": before["ledger"] == after["ledger"]
                   and before["budget"] == after["budget"] and before["go"] == after["go"]},
        "snapshot": {"accounted": accounted, "stage_accounted": stage_acc,
                     "reservation_count": snap.reservation_count, "result_count": snap.result_count,
                     "center_accounted": {k: float(v) for k, v in snap.p2_center_accounted_cny.items()},
                     "historical_prefix": snap.historical_prefix_sha256,
                     "ledger_sha": snap.ledger_sha256,
                     "stage_alloc": {k: float(v) for k, v in snap.stage_allocations_cny.items()}},
        "preflight": {"ok": pre.ok, "reasons": list(pre.reasons),
                      "stage_remaining": round(float(pre.stage_remaining_cny), 7),
                      "requests_remaining": pre.requests_remaining,
                      "requests_planned": pre.requests_planned},
        "stage_remaining_calc": round(stage_alloc - stage_acc, 7),
        "project_remaining_calc": round(total_limit - accounted, 7),
        "hard_cap": HARD_MAX_REQUESTS,
        "requests_remaining_effective": min(HARD_MAX_REQUESTS, plan.max_requests) - snap.reservation_count,
        "requests_remaining_vs_hard_cap": HARD_MAX_REQUESTS - snap.reservation_count,
        "plan": {"plan_id": plan.plan_id, "plan_sha256": plan.plan_sha256, "items": len(plan.items),
                 "total_requests": plan.total_requests, "max_requests": plan.max_requests,
                 "worst_case_cny": round(plan.worst_case_cny, 6), "reserve_peak": round(plan.reserve_peak_cny, 6),
                 "center_needs": {k: round(v, 6) for k, v in plan.center_needs_cny().items()},
                 "by_operation": by_op, "ocr_items": len(ocr_items), "ocr_worst_calc": round(ocr_worst, 6),
                 "worst_calc": round(55 * rnd + embed * by_op.get("index_embedding", 0) + ocr_worst, 6),
                 "doc_sha256": "0b4e55a4cd3a46f968e89fe495ffca3c6931c8f49f1f258a3dd753f83e24a194"},
        "runs_calc": {"r1": round(r1, 6), "r2": round(r2, 6), "r3": round(r3, 6),
                      "sum": round(r1 + r2 + r3, 6),
                      "doc": {"r1": 7.994704, "r2": 0.102784, "r3": 0.04832, "sum": 8.145808},
                      "requests_calc": {"r1": 52 * 4 + 22 + 12, "r2": 2 * 4 + 7, "r3": 4 + 2},
                      "requests_doc": {"r1": 242, "r2": 15, "r3": 6, "sum": 263}},
        "center_check": {"sum_r1r2r3_answer_retrieval": round(r1 - ocr_worst + r2 + r3, 6),
                         "doc_center_need": 2.938048, "doc_center_total": 3.0094063,
                         "with_snapshot": round(float(snap.p2_center_accounted_cny.get("answer_retrieval", 0.0))
                                                + r1 - ocr_worst + r2 + r3, 7),
                         "r2_attribution_doc": 0.545024, "r2_calc": round(r2, 6)},
        "h2": {"turn_worst": round(h2_turn, 6), "ingest14": round(h2_ingest14, 6),
               "total158": round(h2_turn + h2_ingest14, 6),
               "doc": {"turn_worst": 1.592064, "ingest14": 0.028672, "total": 1.620736},
               "template": tpl,
               "template_ok": bool(tpl["items_total"] == 145 and tpl["total_requests"] == 158
                                   and close(tpl["worst_case_cny"], 1.620736)
                                   and tpl["page_count"] == 0 and tpl["ingest_batches"] == 14
                                   and tpl["ingest_batches_upper_bound"] == 20)},
        "h2_ids": {"code": H2_DEFAULT_PLAN_ID, "go_scope": go_h2["scope"]["plan_id"],
                   "template": template["plan_id"],
                   "runbook_command_present": "--plan-id P2-T207-H2-20261111" in runbook,
                   "go_max_requests": go_h2["scope"]["max_requests"],
                   "go_centers": go_h2["scope"]["cost_centers_cny"],
                   "go_ops": go_h2["scope"]["operations"],
                   "all_equal": H2_DEFAULT_PLAN_ID == go_h2["scope"]["plan_id"] == template["plan_id"]},
        "cost6_calc": {"req": req, "subtotal": subtotal, "x1.2": round(subtotal * 1.2, 3),
                       "doc": {"subtotal": 1235, "x1.2": 1482}},
        "cost5_corpus": {"req": corpus_req, "req_with_t208_t900": corpus_req + 160 + 107,
                         "cny": round(corpus_cny, 4), "cny_with_ocr": round(corpus_cny + 5.65, 4),
                         "doc_req": 1948, "doc_cny": 12.34, "doc_with_ocr": 17.99},
        "cost7_calc": {"stage_public": round(stage_acc + r1 + r2 + r3, 7),
                       "stage_with_h2": round(stage_acc + r1 + r2 + r3 + h2_turn + h2_ingest14, 7),
                       "project_public": round(accounted + r1 + r2 + r3, 7),
                       "project_with_h2": round(accounted + r1 + r2 + r3 + h2_turn + h2_ingest14, 7),
                       "stage_with_ocr": round(stage_acc + r1 + r2 + r3 + h2_turn + h2_ingest14 + 5.65, 7),
                       "doc": {"stage_public": 8.7171663, "stage_with_h2": 10.3379023,
                               "project_public": 23.7881108, "project_with_h2": 25.4088468,
                               "stage_with_ocr": 15.99}},
        "A_report_table": checked,
        "build_plan_comment_windows": [ln.strip() for ln in (REPO / "docs/reports/OBS-EVAL/P2/T207/evidence/build-plan.py").read_text(encoding="utf-8").splitlines() if "547+254" in ln],
        "runbook_grep": {"go_plan_id_mismatch_count": runbook.count("go_plan_id_mismatch"),
                         "le242": "≤242" in runbook, "B14": "B = 14" in runbook,
                         "req158": "total_requests=158" in runbook, "items145": "items=145" in runbook,
                         "windows_801_807_822": all(w in runbook for w in ("801", "807", "822"))},
        "cost_grep": {"hard1600": "**1600**" in cost, "rem653": "**余 653**" in cost,
                      "corpus_only_request_side": "只在请求侧" in cost},
    }


# --------------------------------------------------------------------------- #
# B. CLI 独立构造（p2-h2-plan / p2-score holdout）
# --------------------------------------------------------------------------- #
def synthetic_metadata() -> dict:
    """30 题 / 36 回合 / histogram 25-4-1 / 5 个 multi_turn（与 manifest 交叉校验口径一致）。"""
    cases = []
    index = 0
    for stratum, count in (("paraphrase", 10), ("negative", 5), ("stale_conflict", 5), ("cross_doc_security", 5)):
        for _ in range(count):
            index += 1
            cases.append({"case_id": "zprobe-%02d" % index, "turns": 1})
    for turns in (3, 2, 2, 2, 2):
        index += 1
        cases.append({"case_id": "zprobe-%02d" % index, "turns": turns})
    return {"schema_version": "p2-h2-cases-metadata/v0.1",
            "dataset_version": "P2-HOLDOUT-v2", "cases": cases}


def build_sealed_dataset(root: Path) -> dict:
    """合成封存数据集（TEMP）：自有 key / 密文 / manifest；不碰真实 H2 目录与 key。"""
    from cryptography.fernet import Fernet

    root.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fernet = Fernet(key)
    key_path = root.parent / "probe.key"
    key_path.write_bytes(key)

    strata = [("paraphrase", 10, 1), ("negative", 5, 1), ("stale_conflict", 5, 1),
              ("cross_doc_security", 5, 1), ("multi_turn", 5, None)]
    questions, labels, ids = [], [], []
    turn_plan = [3, 2, 2, 2, 2]
    number = 0
    for stratum, count, turns in strata:
        for slot in range(count):
            number += 1
            cid = "zsealed-%02d" % number
            ids.append(cid)
            turns_n = turns if turns is not None else turn_plan[slot]
            q = {"case_id": cid, "suite": "holdout", "split": "holdout", "stratum": stratum,
                 "business_date": "2026-10-28",
                 "question": "" if turns_n > 1 else "合成题 %d" % number,
                 "turns": ["第%d问" % i for i in range(1, turns_n + 1)] if turns_n > 1 else [],
                 "expected_kind": "answer", "should_refuse": False, "requires_ocr": False,
                 "labeler": "probe", "label_version": "probe-label-v0", "notes": ""}
            questions.append(q)
            labels.append({"case_id": cid, "expected_kind": "answer", "expected_values": [],
                           "expected_sources": [], "relevant_units": [], "reference_answer": "",
                           "should_refuse": False, "refusal_reason": None, "forbidden_values": [],
                           "forbidden_sources": [], "notes": ""})
    q_raw = ("\n".join(json.dumps(r, ensure_ascii=False) for r in questions) + "\n").encode("utf-8")
    l_raw = ("\n".join(json.dumps(r, ensure_ascii=False) for r in labels) + "\n").encode("utf-8")
    q_tok = fernet.encrypt(q_raw)
    l_tok = fernet.encrypt(l_raw)
    (root / "questions.jsonl.fernet").write_bytes(q_tok)
    (root / "labels.jsonl.fernet").write_bytes(l_tok)
    manifest = {
        "schema_version": "p2-holdout-manifest/v0.1", "dataset_version": "P2-PROBE-v0",
        "suite": "p2-holdout", "label_version": "probe-label-v0", "case_count": len(questions),
        "strata": {"paraphrase": 10, "multi_turn": 5, "negative": 5,
                   "stale_conflict": 5, "cross_doc_security": 5},
        "business_date": "2026-10-28", "created_utc": "2026-11-11T00:00:00Z", "author": "probe",
        "encryption": {"kind": "fernet", "key_id": "probe"},
        "questions_plaintext_sha256": hashlib.sha256(q_raw).hexdigest(),
        "labels_plaintext_sha256": hashlib.sha256(l_raw).hexdigest(),
        "questions_ciphertext_sha256": hashlib.sha256(q_tok).hexdigest(),
        "labels_ciphertext_sha256": hashlib.sha256(l_tok).hexdigest(),
        "turn_stats": {"total_turns": 36, "max_turns_per_case": 3,
                       "turn_histogram": {"1": 25, "2": 4, "3": 1}},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"root": str(root), "key": str(key_path), "cases": ids}


def section_cli() -> dict:
    from mktkb.evaluation.p2_contracts import P2RunPlan
    from mktkb.evaluation.p2_holdout_plan import H2_DEFAULT_PLAN_ID

    meta_path = TMP / "h2-meta.json"
    meta_path.write_text(json.dumps(synthetic_metadata(), ensure_ascii=False), encoding="utf-8")
    repo_manifest = "docs/evaluation/p2-holdout-v2.manifest.json"
    plan_out = TMP / "h2-plan.json"
    out = {}

    # B1 默认 plan-id（不带 --plan-id）
    run = cli("p2-h2-plan", "--cases-metadata", str(meta_path), "--holdout-manifest", repo_manifest,
              "--ingest-batches", "14", "--plan-out", str(plan_out))
    payload = run["payload"] or {}
    plan_doc = json.loads(plan_out.read_text(encoding="utf-8")) if plan_out.is_file() else None
    plan = P2RunPlan.from_dict(plan_doc) if plan_doc else None
    out["h2plan_default"] = {
        "exit": run["exit"], "payload_keys": sorted(payload.keys()),
        "plan_id": payload.get("plan_id"), "plan_id_is_default": payload.get("plan_id") == H2_DEFAULT_PLAN_ID,
        "items": payload.get("items"), "total_requests": payload.get("total_requests"),
        "worst_case_cny": payload.get("worst_case_cny"), "page_count": payload.get("page_count"),
        "cases": payload.get("cases"), "turns": payload.get("turns"),
        "center_needs": payload.get("center_needs_cny"), "max_requests": payload.get("max_requests"),
        "stdout_has_synthetic_id": "zprobe-" in (run["stdout"] or ""),
        "plan_file_plan_id": plan.plan_id if plan else None,
        "plan_items_by_op": ({op: plan.requests_by_operation()[op] for op in plan.operations} if plan else None),
        "plan_total_requests": plan.total_requests if plan else None,
        "plan_outside_workspace": TMP.is_relative_to(REPO) is False,
    }

    # B2 +1 source => B=15 的请求数（核对 报告里 165 的说法）
    plan15 = TMP / "h2-plan-b15.json"
    run15 = cli("p2-h2-plan", "--cases-metadata", str(meta_path), "--holdout-manifest", repo_manifest,
                "--ingest-batches", "15", "--plan-out", str(plan15))
    out["h2plan_b15"] = {"exit": run15["exit"], "total_requests": (run15["payload"] or {}).get("total_requests"),
                         "worst_case_cny": (run15["payload"] or {}).get("worst_case_cny"),
                         "doc_claim": 165, "calc_144_plus_B": 144 + 15}

    # B3 plan-out 落在工作区内 -> fail closed 且不写文件
    inside = REPO / "docs/reports/OBS-EVAL/P2/T207-FIX-A-R1/evidence/verify/_must_not_exist.json"
    run_inside = cli("p2-h2-plan", "--cases-metadata", str(meta_path), "--holdout-manifest", repo_manifest,
                     "--ingest-batches", "14", "--plan-out", str(inside))
    out["h2plan_inside"] = {"exit": run_inside["exit"],
                            "error_code": (run_inside["payload"] or {}).get("error_code"),
                            "wrote_file": inside.exists()}
    # metadata 落在工作区内同样拒
    run_meta_inside = cli("p2-h2-plan", "--cases-metadata", repo_manifest, "--holdout-manifest", repo_manifest,
                          "--ingest-batches", "14", "--plan-out", str(TMP / "h2-plan-x.json"))
    out["h2plan_meta_inside"] = {"exit": run_meta_inside["exit"],
                                 "error_code": (run_meta_inside["payload"] or {}).get("error_code")}

    # B4 holdout：两输入都缺 / 都给 / 单输入正常聚合
    no_run = TMP / "no-such-run"
    missing_out = TMP / "h-missing"
    run_missing = cli("p2-score", "--run-dir", str(no_run), "--visibility", "holdout",
                      "--holdout-manifest", repo_manifest, "--out", str(missing_out))
    out["holdout_missing"] = {"exit": run_missing["exit"],
                              "error_code": (run_missing["payload"] or {}).get("error_code"),
                              "out_dir_created": missing_out.exists()}
    both_out = TMP / "h-both"
    run_both = cli("p2-score", "--run-dir", str(no_run), "--visibility", "holdout",
                   "--holdout-manifest", repo_manifest, "--out", str(both_out),
                   "--holdout-cases", str(TMP / "sealed-cases.jsonl"),
                   "--verdicts", str(TMP / "sealed-verdicts.jsonl"))
    out["holdout_both"] = {"exit": run_both["exit"],
                           "error_code": (run_both["payload"] or {}).get("error_code"),
                           "out_dir_created": both_out.exists()}

    sealed = build_sealed_dataset(TMP / "sealed")
    verdicts_path = TMP / "sealed-verdicts.jsonl"
    verdicts = []
    for position, cid in enumerate(sealed["cases"]):
        verdicts.append({"case_id": cid, "status": "pass" if position < 25 else "fail"})
    verdicts_path.write_text("\n".join(json.dumps(v, ensure_ascii=False) for v in verdicts) + "\n", encoding="utf-8")
    run_dir = TMP / "probe-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_manifest.json").write_text(json.dumps(
        {"run_id": "probe-h2", "config_hash": "a" * 64, "execution": "local_mock"}, ensure_ascii=False), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps({"attempts": {"reserved": 0}}, ensure_ascii=False), encoding="utf-8")
    score_out = TMP / "h-score"
    env = {"MKTKB_P2_HOLDOUT_ROOT": sealed["root"], "MKTKB_P2_HOLDOUT_KEY_FILE": sealed["key"]}
    run_single = cli("p2-score", "--run-dir", str(run_dir), "--visibility", "holdout",
                     "--holdout-manifest", str(Path(sealed["root"]) / "manifest.json"),
                     "--verdicts", str(verdicts_path), "--out", str(score_out), env_extra=env)
    card_path = score_out / "holdout_scorecard.json"
    card = json.loads(card_path.read_text(encoding="utf-8")) if card_path.is_file() else None
    card_text = card_path.read_text(encoding="utf-8") if card_path.is_file() else ""
    out["holdout_single"] = {
        "exit": run_single["exit"], "payload": run_single["payload"],
        "stderr_tail": (run_single["stderr"] or "")[-400:],
        "scorecard_written": card_path.is_file(),
        "total": (card or {}).get("total"), "passed": (card or {}).get("passed"),
        "failed": (card or {}).get("failed"), "errors": (card or {}).get("errors"),
        "blocks": [b.get("code") for b in (card or {}).get("blocks", [])],
        "release_ready": (card or {}).get("release_ready"),
        "leaks_case_id": "zsealed-" in card_text or "case_id" in card_text,
    }

    # B5 ingest plan / 报告 / 模板 / GO 里不得出现 H2 case_id 或题干
    plan_path = REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json"
    ingest = json.loads(plan_path.read_text(encoding="utf-8"))
    watched = {
        "ingest_plan": plan_path,
        "h2_template": REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-plan-h2-v0_1.template.json",
        "go_h2": REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-GO-h2.CANDIDATE-DRAFT.json",
        "r1_report": REPO / "docs/reports/OBS-EVAL/P2/T207-FIX-A-R1/report.md",
    }
    scan = {}
    for name, file in watched.items():
        text = file.read_text(encoding="utf-8")
        scan[name] = {
            "h2_case_id_like": sorted(set(re.findall(r"\bh2-[a-z_]+-\d+\b", text)))[:5],
            "question_field": bool(re.search(r"\"question\"\s*:", text)),
            "key_like": bool(re.search(r"MKTKB_P2_HOLDOUT_KEY_FILE\s*=", text)),
        }
    out["leak_scan"] = scan
    out["ingest_plan"] = {"schema_version": ingest.get("schema_version"), "label": ingest.get("label"),
                          "sources": len(ingest.get("sources", [])),
                          "order": [Path(s["path"]).name for s in ingest["sources"]],
                          "document_refs": [s.get("document_ref") for s in ingest["sources"]]}
    return out


# --------------------------------------------------------------------------- #
# C. H2 灌库终态 / 五假设 / 批数 B（产品 Mock 路径，独立重跑）
# --------------------------------------------------------------------------- #
class _EmbedRecorder:
    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def embed(self, texts, *, purpose="document"):
        self.calls.append(len(texts))
        return self.inner.embed(texts, purpose=purpose)


def _documents(adapter):
    from sqlalchemy import func, select

    from mktkb.documents.models import Document, DocumentVersion, SourceUnit

    db = adapter.app.state.db.session()
    try:
        rows = []
        for document in db.scalars(select(Document).order_by(Document.name)).all():
            versions = db.scalars(
                select(DocumentVersion).where(DocumentVersion.document_id == document.id)
                .order_by(DocumentVersion.number)
            ).all()
            per = []
            for version in versions:
                units = db.scalars(
                    select(SourceUnit).where(SourceUnit.version_id == version.id)
                    .order_by(SourceUnit.ordinal)
                ).all()
                per.append({
                    "number": int(version.number), "state": str(version.state),
                    "sha256": str(version.sha256), "is_active": version.id == document.active_version_id,
                    "published_at": None if getattr(version, "published_at", None) is None else "set",
                    "units": len(units),
                    "unit_keys": [str(u.unit_key) for u in units],
                    "phones": sorted(set(re.findall(r"0\d{2,3}-\d{8}", " ".join(str(u.text) for u in units)))),
                    "mentions_b_area": any("B区" in str(u.text) for u in units),
                    "mentions_d_area": any("D区" in str(u.text) for u in units),
                })
            rows.append({"name": str(document.name), "document_id": str(document.id),
                         "latest": int(document.latest_version_number),
                         "active": next((v["number"] for v in per if v["is_active"]), None),
                         "versions": per})
        return rows
    finally:
        db.close()


async def h2_state(plan_path: Path, extra_sources=None) -> dict:
    from mktkb.evaluation.product_adapter import (
        ChatBehavior, MockChatBackend, P2RunDataset, ProductEvalAdapter, ingest_plan_from_document,
    )
    from mktkb.rag.providers import post_counters

    raw = json.loads(plan_path.read_text(encoding="utf-8"))
    if extra_sources:
        raw = {**raw, "sources": list(raw["sources"]) + list(extra_sources)}
    plan = ingest_plan_from_document(raw)
    work = TMP / ("h2-" + ("13" if extra_sources else "12"))
    chat = MockChatBackend(behaviors=(ChatBehavior(answer="（离线探针不问答）"),))
    dataset = P2RunDataset(
        visibility="public", cases=(),
        identity={"dataset_version": "p2-probe", "label_version": "p2-probe", "suite": "p2-holdout",
                  "manifest_sha256": "d" * 64, "case_count": 0},
    )
    adapter = ProductEvalAdapter(work, chat=chat, dataset=dataset, ingest_plan=plan,
                                 purge_traces_on_close=True)
    recorder = _EmbedRecorder(adapter._embedder)
    adapter._embedder = recorder
    try:
        await adapter.start()
        receipts = await adapter.ingest()
        adapter._qa.ensure_ready()
        rows = _documents(adapter)
        status = adapter.index_status()
        result = {
            "sources": len(plan.sources),
            "receipts": [{"name": r.name, "published": bool(r.published), "units": r.units} for r in receipts],
            "documents": rows,
            "embedding_calls": [{"texts": n, "batches": math.ceil(n / 5)} for n in recorder.calls],
            "batches_B": sum(math.ceil(n / 5) for n in recorder.calls),
            "batch_upper_bound": sum(max(1, math.ceil(r.units / 5)) for r in receipts),
            "index_status": {k: status.get(k) for k in ("ready", "documents", "units", "chunks",
                                                        "provider_mode", "product_revision", "error_code")},
            "product_revision": adapter.product_revision(),
            "mock_mode": adapter.is_mock,
            "post_counters": {k: dict(v) for k, v in post_counters().items()},
        }
    finally:
        await adapter.close()
    fixtures = REPO / "fixtures/acceptance"
    sha = {}
    for code, rel in {
        "D01": "normal/D01_物品位置表.xlsx", "D02": "normal/D02_合作店家信息.xlsx",
        "D03": "normal/D03_市场部工作指南.docx", "D04": "normal/D04_活动策划流程.docx",
        "D05": "normal/D05_物料领用规范.pdf", "D06": "normal/D06_店家资料维护说明.pdf",
        "V01": "variants/V01_临时物料位置通知.pdf", "V02": "variants/V02_店家联系方式变更通知.pdf",
        "V03": "variants/V03_物品位置表_历史V1.xlsx", "V04": "variants/V04_物品位置表_新版V3.xlsx",
        "V05": "variants/V05_物品位置表_新版V3_移除P01.xlsx", "V06": "variants/V06_合作店家信息_新电话.xlsx",
        "V07": "variants/V07_物料位置独立通知.pdf",
    }.items():
        sha[code] = sha256(fixtures / rel)

    by_name = {row["name"]: row for row in rows}

    def version_of(doc_name, fixture_code):
        document = by_name.get(doc_name) or {}
        return next((v for v in document.get("versions", []) if v["sha256"] == sha[fixture_code]), None)

    p01 = by_name.get("D01_物品位置表.xlsx") or {}
    v03 = version_of("D01_物品位置表.xlsx", "V03")
    v04 = version_of("D01_物品位置表.xlsx", "V04")
    v05 = version_of("D01_物品位置表.xlsx", "V05")
    d01 = version_of("D01_物品位置表.xlsx", "D01")
    v06 = version_of("D02_合作店家信息.xlsx", "V06")
    d02 = version_of("D02_合作店家信息.xlsx", "D02")
    v07 = by_name.get("V07_物料位置独立通知.pdf") or {}
    v01 = by_name.get("V01_临时物料位置通知.pdf") or {}
    removed = sorted(set((v04 or {}).get("unit_keys", [])) - set((v05 or {}).get("unit_keys", [])))
    result["hypotheses"] = {
        "H1_only_v03_historical": bool(v03) and v03["state"] == "superseded" and not v03["is_active"]
        and v03["number"] == 1,
        "H2_v04_published_as_v3": bool(v04) and v04["number"] == 3 and v04["published_at"] == "set",
        "H3_v01_and_d01_both_active": (v01.get("active") == 1 and p01.get("active") == 4
                                        and v01["versions"][0]["mentions_d_area"]),
        "H4_v06_replaces_d02": bool(v06) and v06["is_active"] and (by_name.get("D02_合作店家信息.xlsx") or {}).get("latest") == 2,
        "H5_v05_published_and_v07_valid": bool(v05) and v05["state"] == "published" and v05["is_active"]
        and v05["units"] == (v04 or {}).get("units", 0) - 1 and v07.get("active") == 1,
    }
    result["identity"] = {
        "D01_v1_is_V03": (v03 or {}).get("number") == 1, "D01_v2_is_D01": (d01 or {}).get("number") == 2,
        "D01_v3_is_V04": (v04 or {}).get("number") == 3, "D01_v4_is_V05": (v05 or {}).get("number") == 4,
        "D02_v1_is_D02": (d02 or {}).get("number") == 1, "D02_v2_is_V06": (v06 or {}).get("number") == 2,
        "removed_unit_keys": removed, "removed_count": len(removed),
        "v01_phones": (v01.get("versions") or [{}])[0].get("phones"),
        "v07_phones": (v07.get("versions") or [{}])[0].get("phones"),
        "d01_phones": (v04 or {}).get("phones"),
        "v05_phones": (v05 or {}).get("phones"),
        "D02_phones": (d02 or {}).get("phones"), "V06_phones": (v06 or {}).get("phones"),
        "d01_v4_mentions_b_area": (v04 or {}).get("mentions_b_area"),
        "v05_mentions_b_area": (v05 or {}).get("mentions_b_area"),
        "v01_v1_mentions_d_area": ((v01.get("versions") or [{}])[0]).get("mentions_d_area"),
        "v07_v1_mentions_b_area": ((v07.get("versions") or [{}])[0]).get("mentions_b_area"),
    }
    result["summary"] = {
        "d01_slot": {"latest": p01.get("latest"), "active": p01.get("active"),
                     "states": [(v["number"], v["state"]) for v in p01.get("versions", [])]},
        "d02_slot": {"latest": (by_name.get("D02_合作店家信息.xlsx") or {}).get("latest"),
                     "active": (by_name.get("D02_合作店家信息.xlsx") or {}).get("active"),
                     "states": [(v["number"], v["state"]) for v in (by_name.get("D02_合作店家信息.xlsx") or {}).get("versions", [])]},
        "others": {name: {"latest": row["latest"], "active": row["active"],
                          "states": [(v["number"], v["state"]) for v in row["versions"]]}
                   for name, row in by_name.items() if name not in ("D01_物品位置表.xlsx", "D02_合作店家信息.xlsx")},
        "hypotheses_all_hold": all(result["hypotheses"].values()),
    }
    return result


async def section_h2() -> dict:
    plan_path = REPO / "docs/reports/OBS-EVAL/P2/T207/PM/T207-ingest-plan-H2.json"
    twelve = await h2_state(plan_path)
    v02 = {"path": "fixtures/acceptance/variants/V02_店家联系方式变更通知.pdf"}
    thirteen = await h2_state(plan_path, extra_sources=[v02])
    return {
        "twelve_source": twelve,
        "thirteen_source_plus_V02": {
            "batches_B": thirteen["batches_B"], "sources": thirteen["sources"],
            "requests": 144 + thirteen["batches_B"],
            "v02_phones": thirteen["identity"].get("v01_phones"),
            "d02_phones": thirteen["identity"].get("D02_phones"),
            "v06_phones": thirteen["identity"].get("V06_phones"),
            "v02_document": next((r for r in thirteen["documents"]
                                  if r["name"].startswith("V02")), None),
        },
    }


def main() -> None:
    out_h2 = None
    if "--out-h2" in sys.argv:
        out_h2 = Path(sys.argv[sys.argv.index("--out-h2") + 1])
    result = {"temp": str(TMP)}
    for name, fn in (("numbers", section_numbers), ("cli", section_cli)):
        try:
            result[name] = fn()
        except Exception as exc:  # noqa: BLE001 - 探针要如实报错而不是假装通过
            result[name] = {"error": type(exc).__name__, "detail": str(exc)[:600]}
    try:
        h2 = asyncio.run(section_h2())
        result["h2"] = {k: (v if k != "twelve_source" else v) for k, v in h2.items()}
        result["h2"]["twelve_source"] = h2["twelve_source"]
        if out_h2 is not None:
            out_h2.write_text(json.dumps(h2, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        result["h2"] = {"error": type(exc).__name__, "detail": str(exc)[:600]}
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
