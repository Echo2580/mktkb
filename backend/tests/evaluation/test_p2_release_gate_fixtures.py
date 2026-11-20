"""正式门禁的**合成**证据工厂（零真实请求：不联网、不调模型/OCR/检索）。

用途：在任务 2/3 的真实工件到位前，先把"证据齐备时门禁能不能通过""缺一组输入会不会
被拒"验证清楚。这里的 run 目录、卡、组合、来源证明、选题清单全部是本地构造的假数据，
只用于验证门禁机制，**不代表任何真实模型能力或真实评测结论**。

约定：
* 合成 run 的 `run_id` 一律以 ``synthetic-`` 开头；
* 合成 N/C/U 用例复用冻结 b0 题面作模板，仅换 ``case_id`` / ``suite``，不冒充语义覆盖；
* 合成 H2 卡由 :func:`_canonical_blocks` 等既有校验器同源函数构造，保证"结构合法"。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from mktkb.evaluation.dataset import CaseSpec, cases_to_jsonl
from mktkb.evaluation.p2_b0 import B0_DOCUMENT_CODES, frozen_b0_cases
from mktkb.evaluation.p2_release_model import (
    file_sha256,
    payload_sha256,
    sha256_bytes,
)

ROOT = Path(__file__).resolve().parents[3]
APPROVED_CONFIG = ROOT / "docs" / "evaluation" / "gate_v0_3_approved.json"
FROZEN_CONFIG = ROOT / "docs" / "evaluation" / "gate_v0_3.json"
FROZEN_CONFIG_SHA256 = "3af301dba2d4dbd1bcc9d8f17c656f8a80755820fa2a8559b787974f20b5619d"
FROZEN_CONFIG_HASH = "d10975732dd50616f959fde71a3ead42822b877e98c55c4367902cb053cfd2a8"
REGISTRY = ROOT / "var" / "eval" / "baselines" / "7981d4afc2d1"
B0_RUN_DIR = ROOT / "var" / "eval" / "runs" / "p2-t209-b0-20261120-02" / "p2-run"
H2_AUTHORITY = ROOT / "docs" / "superpowers" / "plans" / "2026-11-20-p2-closeout-2-h2-cards.md"
SELECTION_AUTHORITY = ROOT / "docs" / "reports" / "OBS-EVAL" / "P2" / "T207" / "PM" / "T207-PM-decisions-01.md"

_TEMPLATES: dict[str, CaseSpec] | None = None


def templates() -> dict[str, CaseSpec]:
    global _TEMPLATES
    if _TEMPLATES is None:
        _TEMPLATES = {case.case_id: case for case in frozen_b0_cases()}
    return _TEMPLATES


def make_cases(prefix: str, ids: Sequence[str], suite: str) -> tuple[CaseSpec, ...]:
    """用冻结 b0 题面做模板，换 id/suite（合成用例，不代表语义覆盖）。"""
    import dataclasses

    source = templates()
    pool = [source[f"Q{index:02d}"] for index in range(1, 41)]
    cases = []
    for offset, case_id in enumerate(ids):
        cases.append(dataclasses.replace(pool[offset % len(pool)], case_id=case_id, suite=suite,
                                         stratum=suite))
    return tuple(cases)


def document_codes_for(cases: Sequence[CaseSpec]) -> dict[str, str]:
    """覆盖所有冻结模板 + 传入用例的文档名映射（合成语料名，避免名字白名单效应）。"""
    codes: dict[str, str] = {}
    for case in list(templates().values()) + list(cases):
        for ref in case.expected_sources:
            code = str(ref.get("doc_code") or "")
            if code:
                codes.setdefault(f"{code}-合成文档", code)
    return dict(sorted(codes.items()))


# --------------------------------------------------------------------------- #
# 合成 run 目录
# --------------------------------------------------------------------------- #


def write_run(
    root: Path,
    *,
    run_id: str,
    suite: str,
    cases: Sequence[CaseSpec],
    failing: Sequence[str] = (),
    not_executed: Sequence[str] = (),
    gate_config_hash: str = FROZEN_CONFIG_HASH,
    config_hash: str | None = None,
    pipeline_version: str = "synthetic-pipeline",
    index_revision: int = 11,
    dataset_version: str = "synthetic-public-v0.1",
    execution: str = "live",
    case_rows_override: Sequence[Mapping[str, Any]] | None = None,
) -> Path:
    """写一个结构合法的 run 目录（dataset/cases/manifest/summary）。"""
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    codes = document_codes_for(cases)
    by_code = {code: name for name, code in codes.items()}
    dataset = cases_to_jsonl(cases).encode("utf-8")
    (run_dir / "dataset.jsonl").write_bytes(dataset)
    rows: list[dict[str, Any]] = []
    for case in cases:
        if case.case_id in not_executed:
            continue
        ref = case.expected_sources[0]
        code = str(ref.get("doc_code") or "")
        name = by_code.get(code, f"{code}-合成文档")
        locator = dict(ref.get("locator") or {"page": 1})
        unit = f"unit-{case.case_id}"
        text = "无关回答" if case.case_id in failing else case.reference_answer
        product = {
            "trace_id": f"trace-{case.case_id}", "trace_status": "ok", "trace_path": "legacy",
            "replayed": False, "http_status": 200, "kind": "answer", "text": text,
            "question_sha256": sha256_bytes(case.question.encode("utf-8")),
            "client_request_id": f"request-{case.case_id}",
            "sources": [{"source_id": unit, "document_name": name, "locator": locator}],
            "retrieved": [{"unit_ids": [unit], "document_name": name}],
            "evidence": [{"unit_id": unit, "unit_key": ref.get("unit_key"), "locator": locator,
                          "verified": True, "document_id": f"doc-{code}", "version_id": f"ver-{code}",
                          "version_number": 1, "state": "published", "active": True, "in_run": True}],
        }
        rows.append({
            "schema_version": "p2-run-case/v0.1", "run_id": run_id, "case_id": case.case_id,
            "suite": suite, "stratum": case.stratum, "visibility": "public",
            "conversation_id": f"conv-{case.case_id}", "status": "ok", "error_code": None,
            "planned_turns": 1, "turns_executed": 1,
            "turns": [{"turn": 1, "status": "ok", "error_code": None, "item_id": f"answer-{case.case_id}",
                       "kind": "answer", "trace_id": f"trace-{case.case_id}", "trace_path": "legacy",
                       "product": product}],
        })
    if case_rows_override is not None:
        rows = [dict(item) for item in case_rows_override]
    (run_dir / "cases.jsonl").write_bytes(
        ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode("utf-8")
    )
    executed = len(rows)
    real_calls = executed if execution == "live" else 0
    manifest = {
        "schema_version": "p2-run-manifest/v0.1", "run_id": run_id, "mode": "end_to_end",
        "scope": "end_to_end", "suite": suite, "dataset_version": dataset_version,
        "dataset_sha256": sha256_bytes(dataset), "corpus_manifest_sha256": "c" * 64,
        "business_date": "2026-10-28", "index_revision": index_revision,
        "pipeline_version": pipeline_version, "gate_version": "mktkb.gate.v0.3",
        "label_version": dataset_version, "created_at": "2026-11-20T00:00:00+00:00",
        "case_count": len(cases),
        "config_hash": config_hash or sha256_bytes(f"{run_id}:config".encode()),
        "gate_config_hash": gate_config_hash, "execution": execution,
        "dataset_path": str(run_dir / "dataset.jsonl"),
        "plan": {"plan_id": f"plan-{run_id}", "plan_sha256": sha256_bytes(f"plan:{run_id}".encode())},
    }
    summary = {
        "schema_version": "p2-run-summary/v0.1", "run_id": run_id, "status": "succeeded",
        "stop_code": None, "failure": None, "execution": execution,
        "cases": {"planned": len(cases), "executed": executed, "with_error": 0,
                  "not_executed": len(cases) - executed},
        "turns": {"planned": len(cases), "executed": executed,
                  "with_product_result": executed},
        "network": {"available": True, "outbound_attempts": real_calls,
                    "detail": {"mock_intercepted": 0 if execution == "live" else real_calls}},
        "attempts": {"reserved": real_calls, "gate_reserved": real_calls},
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return run_dir


def run_ref(run_dir: Path, *, suite: str) -> dict[str, Any]:
    """把一个合成 run 目录折成输入清单里的 run 绑定。"""
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    return {
        "suite": suite,
        "run_id": manifest["run_id"],
        "run_dir": str(run_dir),
        "artifacts": {name: file_sha256(run_dir / name)
                      for name in ("run_manifest.json", "summary.json", "dataset.jsonl", "cases.jsonl")},
        "original": {
            "gate_config_path": str(FROZEN_CONFIG),
            "gate_config_sha256": FROZEN_CONFIG_SHA256,
            "gate_config_hash": manifest["gate_config_hash"],
            "pipeline_version": manifest["pipeline_version"],
            "index_revision": manifest["index_revision"],
            "dataset_version": manifest["dataset_version"],
        },
    }


# --------------------------------------------------------------------------- #
# 合成 H2：四张 v0.2 卡 + 组合 + 来源证明
# --------------------------------------------------------------------------- #

SCENARIOS = ("base_b0", "base_b0_plus_v01", "pre_v05_without_v07", "post_v05_without_v01")
SCENARIO_CASES = {"base_b0": 12, "base_b0_plus_v01": 8, "pre_v05_without_v07": 5,
                  "post_v05_without_v01": 5}
SCENARIO_TURNS = {"base_b0": 14, "base_b0_plus_v01": 10, "pre_v05_without_v07": 6,
                  "post_v05_without_v01": 6}
STRATA = ("paraphrase", "multi_turn", "negative", "stale_conflict", "cross_doc_security")
STRATA_ALLOC = {
    "base_b0": {"paraphrase": 6, "multi_turn": 2, "negative": 1, "stale_conflict": 1,
                "cross_doc_security": 2},
    "base_b0_plus_v01": {"paraphrase": 3, "multi_turn": 1, "negative": 1, "stale_conflict": 1,
                         "cross_doc_security": 2},
    "pre_v05_without_v07": {"paraphrase": 1, "multi_turn": 1, "negative": 1, "stale_conflict": 1,
                            "cross_doc_security": 1},
    "post_v05_without_v01": {"paraphrase": 0, "multi_turn": 1, "negative": 2, "stale_conflict": 2,
                             "cross_doc_security": 0},
}
PASSED = {"base_b0": 10, "base_b0_plus_v01": 7, "pre_v05_without_v07": 4,
          "post_v05_without_v01": 3}
ANNOTATION_AXES = {
    "safety": {"required": 8, "not_applicable": 22, "unknown": 0},
    "cross_user": {"required": 30, "not_applicable": 0, "unknown": 0},
    "cross_entity": {"required": 10, "not_applicable": 20, "unknown": 0},
    "stale_source": {"required": 0, "not_applicable": 29, "unknown": 1},
}


def _card_axes(total: int, *, non_required_unknown: int = 1, violate: bool = False) -> tuple[dict, dict, int]:
    from mktkb.evaluation.p2_hard_evidence import AXES

    axes: dict[str, dict[str, int]] = {}
    violations: dict[str, int] = {}
    for name in AXES:
        unknown = non_required_unknown if name == "stale_source" else 0
        violation = 1 if (violate and name == "safety") else 0
        not_applicable = max(0, total - unknown - violation - max(1, total - 2))
        passed = total - unknown - violation - not_applicable
        axes[name] = {
            "planned": total, "passed": passed, "not_applicable": not_applicable,
            "unknown": unknown, "violations": violation,
            "checked": passed + not_applicable + violation,
        }
        violations[name] = violation
    return axes, violations, sum(violations.values())


def build_card(
    *,
    scenario: str,
    run_id: str | None = None,
    config_hash: str | None = None,
    passed: int | None = None,
    non_required_unknown: int = 1,
    violate: bool = False,
    schema_version: str | None = None,
) -> dict[str, Any]:
    """按 v0.2 契约构造一张结构合法的卡（数字由调用方给，结构由既有校验器同源函数定）。"""
    from mktkb.evaluation import p2_hard_evidence as hard

    total = SCENARIO_CASES[scenario]
    passed_count = PASSED[scenario] if passed is None else passed
    if violate and passed is not None:
        passed_count = min(passed, total - 1)
    alloc = dict(STRATA_ALLOC[scenario])
    failed_left = total - passed_count
    by_stratum: dict[str, dict[str, int]] = {}
    for name in STRATA:
        bucket_total = alloc[name]
        take = min(bucket_total, failed_left)
        failed_left -= take
        by_stratum[name] = {"total": bucket_total, "passed": bucket_total - take,
                            "failed": take, "errors": 0}
    if failed_left:
        raise AssertionError("分层容量不足以容纳失败题")
    axes, violations, union = _card_axes(total, non_required_unknown=non_required_unknown,
                                         violate=violate)
    unknown_total = sum(item["unknown"] for item in axes.values())
    verified = bool(unknown_total == 0 and total > 0)
    card = {
        "schema_version": schema_version or hard.SCORECARD_SCHEMA_VERSION,
        "total": total,
        "executed": passed_count + (total - passed_count),
        "errors": 0,
        "passed": passed_count,
        "failed": total - passed_count,
        "min_pass": 24,
        "threshold_met": bool(total == 30 and passed_count >= 24),
        "hard_failures": union,
        "hard_failures_max": 0,
        "hard_failures_by_kind": dict(violations),
        "by_stratum": by_stratum,
        "thresholds_approved": False,
        "detail_export": False,
        "blocks": hard._canonical_blocks(
            total=total, passed=passed_count, errors=0, hard_failures=union,
            hard_failures_max=0, verified=verified, missing_evidence_cases=0,
            thresholds_approved=False,
        ),
        "release_ready": False,
        "execution_mode": "local_mock",
        "real_calls": 0,
        "run_id": run_id or f"synthetic-h2-{scenario}",
        "config_hash": config_hash or sha256_bytes(f"cfg:{scenario}".encode()),
        "hard_evidence": {
            "schema_version": hard.HARD_EVIDENCE_SCHEMA_VERSION,
            "axes": axes,
            "hard_failures_by_kind": dict(violations),
            "missing_evidence_cases": 0,
            "evidence_complete_cases": total,
            "verified": verified,
            "classification_status": hard._classification_status(verified),
            "annotation_gap_count": 1 if non_required_unknown else 0,
            "annotation_gap_resolved_count": 1 if non_required_unknown else 0,
        },
        "diagnostics": {
            "schema_version": hard.DIAGNOSTICS_SCHEMA_VERSION,
            "counts": {"planned": total, "scored": total, "errors": 0, "not_executed": 0},
            "by_stratum": {name: {"planned": bucket["total"], "scored": bucket["total"],
                                  "errors": 0, "not_executed": 0}
                           for name, bucket in by_stratum.items()},
            "hard_failure_evidence": axes,
            "missing_evidence_cases": 0,
            "evidence_complete_cases": total,
            "verified": verified,
            "classification_status": hard._classification_status(verified),
            "classification_owner": "runtime_classifier",
        },
    }
    if schema_version in (None, hard.SCORECARD_SCHEMA_VERSION):
        hard.validate_hard_evidence_scorecard(
            card, total=total, run_id=card["run_id"], config_hash=card["config_hash"]
        )
    return card


def build_h2(root: Path, *, annotation_axes: Mapping[str, Mapping[str, int]] | None = None,
             hard_failure: bool = False, card_schema: str | None = None,
             c25_count: int | None = None) -> dict[str, Path]:
    """写四张卡 + 组合 + 来源证明；返回各文件路径。"""
    from mktkb.evaluation import p2_holdout_scenarios as scenarios
    from mktkb.evaluation.p2_release_h2 import classifier_source_sha256

    root.mkdir(parents=True, exist_ok=True)
    cards_dir = root / "cards"
    cards_dir.mkdir(exist_ok=True)
    cards: list[dict[str, Any]] = []
    paths: list[Path] = []
    for scenario in SCENARIOS:
        card = build_card(
            scenario=scenario,
            config_hash=sha256_bytes(f"h2-config:{scenario}".encode()),
            violate=hard_failure and scenario == "base_b0",
            schema_version=card_schema,
            non_required_unknown=1 if scenario == "base_b0" else 0,
        )
        cards.append(card)
        path = cards_dir / f"{scenario}.json"
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        paths.append(path)
    shared = {
        "manifest_sha256": "1" * 64, "full_cases_sha256": "2" * 64,
        "assignment_sha256": "3" * 64,
        "schema_sha256": "4" * 64, "scenario_contract_sha256": "5" * 64,
        "custody_sha256": "6" * 64, "source_map_sha256": "7" * 64,
        "ingest_plan_sha256": "8" * 64, "review_sha256": "9" * 64,
    }
    runs = []
    proof_scenarios = []
    for index, (scenario, card) in enumerate(zip(SCENARIOS, cards)):
        subset = sha256_bytes(f"subset:{scenario}".encode())
        plan_sha = sha256_bytes(f"plan:{scenario}".encode())
        binding = {**shared, "scenario_id": scenario, "subset_sha256": subset,
                   "scenario_ingest_sha256": sha256_bytes(f"ingest:{scenario}".encode())}
        aggregate = payload_sha256(card)
        runs.append({
            "scenario_id": scenario, "run_id": card["run_id"],
            "plan_sha256": plan_sha, "binding": binding,
            "status": "succeeded", "aggregate_sha256": aggregate,
            "config_hash": card["config_hash"],
            "hard_evidence_sha256": payload_sha256(card["hard_evidence"]),
        })
        proof_scenarios.append({
            "scenario_id": scenario, "run_id": card["run_id"],
            "plan_sha256": plan_sha, "status": "succeeded",
            "case_count": SCENARIO_CASES[scenario], "turns_executed": SCENARIO_TURNS[scenario],
            "config_hash": card["config_hash"],
            "hard_evidence_sha256": payload_sha256(card["hard_evidence"]),
            "derived_card_sha256": aggregate,
            "original_identities": {
                "gate_config_hash": FROZEN_CONFIG_HASH,
                "pipeline_version": "synthetic-original-pipeline",
                "index_revision": 11 + index,
                "dataset_version": "synthetic-holdout-v2",
            },
            "derived_scorer": {"tool": "p2-hard-evidence-recompute",
                               "source_sha256": classifier_source_sha256()},
        })
    total_passed = sum(card["passed"] for card in cards)
    total_hard = sum(card["hard_failures"] for card in cards)
    axis_totals = {}
    for name in cards[0]["hard_evidence"]["axes"]:
        axis_totals[name] = {
            key: sum(card["hard_evidence"]["axes"][name][key] for card in cards)
            for key in ("planned", "passed", "not_applicable", "unknown", "violations", "checked")
        }
    unknown_total = sum(item["unknown"] for item in axis_totals.values())
    verified = bool(unknown_total == 0)
    strata = {name: sum(STRATA_ALLOC[scenario][name] for scenario in SCENARIOS) for name in STRATA}
    annotation = {
        "case_count": 30, "total_turns": 36,
        "scenario_counts": {scenario: SCENARIO_CASES[scenario] for scenario in SCENARIOS},
        "axis_counts": {name: dict(annotation_axes[name]) if annotation_axes else
                        dict(ANNOTATION_AXES[name]) for name in ANNOTATION_AXES},
        "fixed_gap_counts": {"unresolved_entity_target": 0, "unresolved_date_anchor": 0,
                             "unresolved_scenario": 0},
        "quality_readiness": "BLOCKED", "runtime_axis_evidence_produced": False,
        "release_ready": False,
    }
    composition = {
        "schema_version": scenarios.HARD_EVIDENCE_COMPOSITION_SCHEMA_VERSION,
        "total": 30, "executed": 30, "errors": 0, "passed": total_passed,
        "failed": 30 - total_passed, "min_pass": 24,
        "threshold_met": bool(total_passed >= 24),
        "hard_failures": total_hard,
        "hard_failures_by_kind": {name: axis_totals[name]["violations"] for name in axis_totals},
        "by_stratum": {name: {"total": strata[name], "passed": strata[name], "failed": 0,
                              "errors": 0} for name in STRATA},
        "status": "complete", "turns_planned": 36, "turns_executed": 36, "not_started": 0,
        "thresholds_approved": False, "blocks": [], "real_calls": 0,
        "execution_mode": "local_mock",
        "manifest_sha256": shared["manifest_sha256"],
        "full_cases_sha256": shared["full_cases_sha256"],
        "assignment_sha256": shared["assignment_sha256"],
        "runs": runs,
        "hard_evidence": {
            "schema_version": cards[0]["hard_evidence"]["schema_version"],
            "axes": axis_totals,
            "hard_failures": total_hard,
            "hard_failures_by_kind": {name: axis_totals[name]["violations"] for name in axis_totals},
            "missing_evidence_cases": 0, "evidence_complete_cases": 30,
            "verified": verified,
        },
        "annotation": annotation,
        "release_ready": False,
    }
    # 失败题要落到具体分层（组合的分层通过数按聚合校验）。
    composition["by_stratum"] = {
        name: {
            "total": strata[name],
            "passed": strata[name] - (30 - total_passed if name == "paraphrase" else 0),
            "failed": 30 - total_passed if name == "paraphrase" else 0,
            "errors": 0,
        } for name in STRATA
    }
    composition["blocks"] = scenarios._composition_blocks(composition, strata)
    scenarios.validate_hard_evidence_composition(composition, total=30, expected_strata=strata)
    composition_path = root / "composition.json"
    composition_path.write_text(
        json.dumps(composition, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    proof = {
        "schema_version": "p2-release-h2-source-proof/v0.1",
        "batch_id": "synthetic-t207-retest-batch",
        "batch_authority": {
            "document": str(H2_AUTHORITY), "sha256": file_sha256(H2_AUTHORITY),
            "section": "本次授权范围/执行与验收 2",
        },
        "batch_binding": {
            "manifest_sha256": shared["manifest_sha256"],
            "full_cases_sha256": shared["full_cases_sha256"],
            "assignment_sha256": shared["assignment_sha256"],
        },
        "scenarios": proof_scenarios,
        "zero_call": {"new_requests": 0, "new_outbound": 0, "replayed": False},
        "c25_non_required_unknown": {
            "case_id": "C25",
            "axes": ["stale_source"],
            "count": int(c25_count if c25_count is not None else unknown_total),
        },
    }
    proof_path = root / "source-proof.json"
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    return {
        "cards": paths, "composition": composition_path, "source_proof": proof_path,
        "card_payloads": cards, "composition_payload": composition,
    }


# --------------------------------------------------------------------------- #
# 合成输入清单
# --------------------------------------------------------------------------- #

N_IDS = tuple(f"N{index:02d}" for index in range(1, 9))
C_IDS = tuple(f"C{index:02d}" for index in range(1, 7))
U_IDS = tuple(f"U{index:02d}" for index in range(1, 11))


def build_public(root: Path, *, failing: Sequence[str] = (), not_executed: Sequence[str] = (),
                 mixed_rows: bool = False, with_binding: bool = False) -> dict[str, Any]:
    """合成 N/C 两个 run + 冻结选题清单 + 文档名映射。"""
    root.mkdir(parents=True, exist_ok=True)
    n_cases = make_cases("N", N_IDS, "negative")
    c_cases = make_cases("C", C_IDS, "boundary")
    n_run = write_run(root, run_id="synthetic-public-n", suite="negative", cases=n_cases,
                      failing=failing, not_executed=not_executed)
    c_run = write_run(root, run_id="synthetic-public-c", suite="boundary", cases=c_cases,
                      failing=failing, not_executed=not_executed)
    if with_binding:
        add_trace_and_rag(n_run, cases=n_cases)
    if mixed_rows:
        # 把 C run 的行塞进 N run：同一目录出现两份计划的逐题行（跨计划合并）。
        merged = (n_run / "cases.jsonl").read_text(encoding="utf-8") + \
                 (c_run / "cases.jsonl").read_text(encoding="utf-8")
        (n_run / "cases.jsonl").write_text(merged, encoding="utf-8")
    codes = document_codes_for(n_cases + c_cases)
    codes_path = root / "document-codes.json"
    codes_path.write_text(json.dumps(codes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assignments = (
        [{"suite": "negative", "case_id": case_id, "run_id": n_run.name} for case_id in N_IDS]
        + [{"suite": "boundary", "case_id": case_id, "run_id": c_run.name} for case_id in C_IDS]
    )
    selection = {
        "schema_version": "p2-release-selection/v0.1",
        "authority": {
            "document": str(SELECTION_AUTHORITY),
            "sha256": file_sha256(SELECTION_AUTHORITY),
            "section": "11-12,24",
        },
        "assignments": assignments,
    }
    selection_path = root / "selection.json"
    selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    negative_ref = run_ref(n_run, suite="negative")
    if with_binding:
        negative_ref["rag_db"] = {"path": str(n_run.parent / "data" / "rag-index.sqlite3"),
                                  "sha256": file_sha256(n_run.parent / "data" / "rag-index.sqlite3")}
    return {
        "runs": [negative_ref, run_ref(c_run, suite="boundary")],
        "document_codes": {"path": str(codes_path), "sha256": file_sha256(codes_path)},
        "selection": {"path": str(selection_path), "sha256": file_sha256(selection_path)},
        "n_run": n_run, "c_run": c_run,
    }


def build_u(root: Path, *, local_controls: bool = False, run_level_cases: Sequence[str] = U_IDS,
            overlap_local: Sequence[str] = (), local_status: str = "pass",
            citation_gap: bool = False, failing_citations: bool = False) -> dict[str, Any]:
    """合成 U：默认 10 题全部 run 级（真实 smoke 覆盖 U01–U10）。"""
    root.mkdir(parents=True, exist_ok=True)
    cases = make_cases("U", run_level_cases, "update_delete")
    run = write_run(root, run_id="synthetic-public-u", suite="update_delete", cases=cases)
    if citation_gap or failing_citations:
        rows = [json.loads(line) for line in
                (run / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            if row["case_id"] != "U01":
                continue
            for turn in row["turns"]:
                if citation_gap:
                    turn["product"]["retrieved"] = []
                if failing_citations:
                    # 引用整段缺失 -> citation_missing（run 级真实门禁失败，不得被口径修订掩盖）
                    turn["product"]["sources"] = []
        (run / "cases.jsonl").write_bytes(
            ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode("utf-8"))
    payload: dict[str, Any] = {
        "real": {**{key: run_ref(run, suite="update_delete")[key]
                    for key in ("suite", "run_id", "run_dir", "artifacts", "original")},
                 "case_ids": list(run_level_cases)},
    }
    if local_controls:
        cases_map = {}
        for case_id in U_IDS:
            cases_map[case_id] = {"case_id": case_id, "status": local_status, "tests": []}
        for case_id in overlap_local:
            cases_map[case_id] = {"case_id": case_id, "status": local_status, "tests": []}
        controls = {
            "schema_version": "p2-u-local-controls/v0.1",
            "source": "backend/tests/acceptance/test_t09_mutation.py",
            "basis": "L",
            "cases": cases_map,
            "exit_code": 0,
        }
        path = root / "u-controls.json"
        path.write_text(json.dumps(controls, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["local_controls"] = {"path": str(path), "sha256": file_sha256(path)}
    return payload


def base_inputs(*, public: Mapping[str, Any] | None, u: Mapping[str, Any] | None,
                h2: Mapping[str, Any] | None, pending: Mapping[str, str] | None = None) -> dict[str, Any]:
    """组装完整输入清单（B0 一律绑定已登记的正式基线）。"""
    payload: dict[str, Any] = {
        "schema_version": "p2-release-gate-inputs/v0.1",
        "gate_config": {"path": str(APPROVED_CONFIG), "sha256": file_sha256(APPROVED_CONFIG)},
        "candidate_pipeline": {
            "pipeline_source_sha256": __import__("mktkb.evaluation.p2_b0", fromlist=["x"]).pipeline_source_sha256(),
            "pipeline_version": "synthetic-candidate",
        },
        "b0": {
            "baseline_root": str(REGISTRY.parent),
            "baseline_id": "7981d4afc2d1",
            "run_id": "p2-t209-b0-20261120-02",
            "baseline_sha256": file_sha256(REGISTRY / "baseline.json"),
            "admission_sha256": file_sha256(REGISTRY / "b0-admission.json"),
            "approval_sha256": file_sha256(REGISTRY / "b0-approval-receipt.json"),
        },
    }
    if public is not None:
        payload["document_codes"] = public["document_codes"]
        payload["public"] = {key: public[key] for key in ("selection", "runs")}
    if u is not None:
        payload["u"] = {key: u[key] for key in ("real", "local_controls") if key in u}
    if h2 is not None:
        payload["h2"] = {key: h2[key] for key in ("composition", "source_proof", "cards")}
    if pending:
        payload["pending"] = dict(pending)
    return payload


def write_inputs(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def add_trace_and_rag(
    run_dir: Path,
    *,
    cases: Sequence[CaseSpec],
    recorded: int = 11,
    attested: int = 12,
    split_at: int = 4,
) -> tuple[Path, Path]:
    """给合成 run 造 trace 库与 rag 索引库：

    * 前 ``split_at`` 题的 trace 记 ``attested``（走过 RAG，沿用 rag_meta.revision）；
    * 其余题记 ``recorded``（未走 RAG，继承了产品计数）——这正是历史 run 的两套计数器。
    """
    import sqlite3

    from mktkb.observability.contracts import SpanRecord, TraceRecord, required_spans
    from mktkb.observability.store import TraceRepository

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    trace_db = run_dir.parent / "data" / "observability" / "qa-traces.sqlite3"
    trace_db.parent.mkdir(parents=True, exist_ok=True)
    if trace_db.exists():
        trace_db.unlink()
    with TraceRepository(trace_db) as repository:
        for index, case in enumerate(cases):
            trace_id = f"trace-{case.case_id}"
            revision = attested if index < split_at else recorded
            repository.write(
                TraceRecord(
                    trace_id=trace_id, case_id=case.case_id, mode="local", scope="end_to_end",
                    path="legacy", outcome_kind="answer",
                    dataset_version=manifest["dataset_version"], run_id=manifest["run_id"],
                    index_revision=str(revision),
                    manifest_sha256=manifest["corpus_manifest_sha256"],
                    pipeline_version=manifest["pipeline_version"],
                    config_hash=manifest["config_hash"], status="ok",
                ),
                [SpanRecord(span_id=f"{trace_id}-{name}", trace_id=trace_id, name=name, status="ok")
                 for name in required_spans("legacy", "answer")],
            )
    manifest["trace_store"] = str(trace_db)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rag_db = run_dir.parent / "data" / "rag-index.sqlite3"
    rag_db.parent.mkdir(parents=True, exist_ok=True)
    if rag_db.exists():
        rag_db.unlink()
    connection = sqlite3.connect(str(rag_db))
    try:
        connection.execute("create table rag_meta (key text primary key, value text)")
        connection.execute("insert into rag_meta values ('revision', ?)", (str(attested),))
        connection.commit()
    finally:
        connection.close()
    return trace_db, rag_db


def attach_binding(payload: dict[str, Any], *, out_dir: Path) -> dict[str, Any]:
    """生成并回填绑定适用性证明（与 rag_db 绑定一起用）。"""
    from mktkb.evaluation.p2_release_gate import emit_binding_proof

    probe = write_inputs(out_dir.parent / "inputs.binding.json", payload)
    emitted = emit_binding_proof(probe, out_dir=out_dir)
    for run in payload.get("public", {}).get("runs", []):
        written = emitted["written"].get(run["run_id"])
        if written:
            run["binding_proof"] = {"path": written["path"], "sha256": written["sha256"]}
    real = payload.get("u", {}).get("real")
    if real is not None:
        written = emitted["written"].get(real["run_id"])
        if written:
            real["binding_proof"] = {"path": written["path"], "sha256": written["sha256"]}
    return payload


def h2_input(h2: Mapping[str, Any]) -> dict[str, Any]:
    """把 :func:`build_h2` 的产物折成输入清单里的 h2 段。"""
    return {
        "composition": {"path": str(h2["composition"]),
                        "sha256": file_sha256(h2["composition"])},
        "source_proof": {"path": str(h2["source_proof"]),
                         "sha256": file_sha256(h2["source_proof"])},
        "cards": [
            {"scenario_id": scenario_id, "path": str(path), "sha256": file_sha256(path)}
            for scenario_id, path in zip(SCENARIOS, h2["cards"])
        ],
    }


def attach_applicability(payload: dict[str, Any], *, out_dir: Path) -> dict[str, Any]:
    """生成并回填旧版本适用性证明（门禁接线后仍需逐字段重算比对）。"""
    from mktkb.evaluation.p2_release_gate import emit_applicability_proof

    probe = write_inputs(out_dir.parent / "inputs.emit.json", payload)
    probe = write_inputs(out_dir.parent / "inputs.emit.json", payload)
    emitted = emit_applicability_proof(probe, out_dir=out_dir)
    for run in payload.get("public", {}).get("runs", []):
        written = emitted["written"].get(run["run_id"])
        if written:
            run["applicability"] = {"path": written["path"], "sha256": written["sha256"]}
    real = payload.get("u", {}).get("real")
    if real is not None:
        written = emitted["written"].get(real["run_id"])
        if written:
            real["applicability"] = {"path": written["path"], "sha256": written["sha256"]}
    return payload


def build_complete_inputs(
    tmp: Path,
    *,
    local_controls: bool = False,
    run_level_cases: Sequence[str] = U_IDS,
    public_kwargs: Mapping[str, Any] | None = None,
    h2_kwargs: Mapping[str, Any] | None = None,
    u_kwargs: Mapping[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """齐备合成证据的输入清单（B0 用已登记基线，其余全合成）。"""
    from mktkb.evaluation.p2_release_gate import emit_applicability_proof

    tmp.mkdir(parents=True, exist_ok=True)
    public = build_public(tmp / "public", **(dict(public_kwargs or {})))
    u = build_u(tmp / "u", local_controls=local_controls, run_level_cases=run_level_cases,
                **(dict(u_kwargs or {})))
    h2 = build_h2(tmp / "h2", **(dict(h2_kwargs or {})))
    payload = base_inputs(public=public, u=u, h2=h2_input(h2))
    path = write_inputs(tmp / "inputs.json", payload)
    if any("rag_db" in run for run in payload["public"]["runs"]):
        attach_binding(payload, out_dir=tmp / "binding-proofs")
        write_inputs(path, payload)
    emitted = emit_applicability_proof(path, out_dir=tmp / "proofs")
    for run in payload["public"]["runs"]:
        written = emitted["written"].get(run["run_id"])
        if written:
            run["applicability"] = {"path": written["path"], "sha256": written["sha256"]}
    written = emitted["written"].get(payload["u"]["real"]["run_id"])
    if written:
        payload["u"]["real"]["applicability"] = {"path": written["path"], "sha256": written["sha256"]}
    write_inputs(path, payload)
    return path, payload
