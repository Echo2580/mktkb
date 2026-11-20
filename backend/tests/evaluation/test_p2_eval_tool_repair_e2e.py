"""T207 评测工具修复：正式受控入口 → 四轴分类 → 独立重算的离线完整链路。

边界（本包任务3/4）：
- 合成 30 题/36 回合 dataset、合成 v0.2 annotation + v0.3 addendum、合成 custody
  manager/review aggregate、合成密钥与 GO/账本；场景契约/ingest plan/schema 只用公开冻结文件；
- 真实 ProductEvalAdapter + httpx.MockTransport 装配、真实受控入口 `_execute_loaded`、
  真实 Fernet 密文/回执/case-plan、真实 `p2_h2_controlled_execute.py recompute` 分发；
- 不读真实 H2/标签/保管密文/真实 key/.env/GO/ledger；真实外部发送 0；
- 不 patch 分类器/validator/分支门/预期结果；"rag expansion" 样本只在真实格式信封上
  补一对合同允许的 query_expansion 事件（在 writer 加密前注入，仍走 A schema 校验）。
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet

_TESTS_DIR = Path(__file__).resolve().parents[1]
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_EVALUATION_TESTS = Path(__file__).resolve().parent
if str(_EVALUATION_TESTS) not in sys.path:
    sys.path.insert(0, str(_EVALUATION_TESTS))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401

from evaluation import test_p2_h2_controlled_entry as helper  # noqa: E402
from evaluation import test_p2_hard_evidence as H  # noqa: E402
from mktkb.evaluation import p2_authorization as p2a  # noqa: E402
from mktkb.evaluation import p2_evidence_capture as capture  # noqa: E402
from mktkb.evaluation import p2_evidence_io as evidence_io  # noqa: E402
from mktkb.evaluation import p2_hard_evidence as hard  # noqa: E402
from mktkb.evaluation import p2_holdout_scenarios as scenarios  # noqa: E402
from mktkb.evaluation.dataset import CaseSpec, cases_to_jsonl  # noqa: E402
from mktkb.evaluation.p2_dataset import (  # noqa: E402
    HOLDOUT_KEY_FILE_ENV,
    HOLDOUT_ROOT_ENV,
    LABELS_CIPHERTEXT_NAME,
    QUESTIONS_CIPHERTEXT_NAME,
    P2_STRATA,
    load_p2_dataset,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "tools" / "p2_h2_controlled_execute.py"
D01 = ROOT / "fixtures" / "acceptance" / "normal" / "D01_物品位置表.xlsx"
D04 = ROOT / "fixtures" / "acceptance" / "normal" / "D04_活动策划流程.docx"
SCENARIO = "base_b0"
BUSINESS_DATE = helper.BUSINESS_DATE
DATASET_VERSION = "P2-HOLDOUT-SYN30-REPAIR-v1"
LABEL_VERSION = "synthetic-repair-v1"
EXPANSION_TURN = 14  # case SYN30-08 的唯一回合（全局 turn 序号）

ASSIGNMENT = tuple(
    ["base_b0"] * 26 + ["base_b0_plus_v01"] * 1 + ["pre_v05_without_v07"] * 2 + ["post_v05_without_v01"] * 1
)

RAG = "编号 P{n} 的物品放在哪个位置？"
LEGACY = "编号 P{n} 是什么？"
EMPTY = "火星店有哪些宣传册？"
EMPTY2 = "月球店有哪些宣传册？"
EMPTY3 = "海底店有哪些宣传册？"


def _cases() -> tuple[CaseSpec, ...]:
    """30 题/36 回合：5 多轮（2/2/2/2/3）+ 25 单轮，分层与公开 manifest 一致。"""
    boundary = {
        0: (RAG.format(n="01"), RAG.format(n="02")),
        1: (RAG.format(n="01"), RAG.format(n="02")),
        2: (RAG.format(n="01"), RAG.format(n="02")),
        3: (EMPTY, EMPTY2),
        4: (EMPTY, EMPTY2, EMPTY3),
    }
    single = {
        5: RAG.format(n="04"),
        6: LEGACY.format(n="05"),
        7: EMPTY,
        8: RAG.format(n="06"),
        9: EMPTY2,
    }
    for index in range(10, 30):
        single[index] = EMPTY
    strata = (
        ["multi_turn"] * 5
        + ["paraphrase"] * 10
        + ["negative"] * 5
        + ["stale_conflict"] * 5
        + ["cross_doc_security"] * 5
    )
    cases: list[CaseSpec] = []
    for index in range(30):
        turns = tuple({"question": question} for question in boundary.get(index, ()))
        cases.append(
            CaseSpec(
                case_id="SYN30-" + f"{index:02d}",
                suite="holdout",
                split="holdout",
                stratum=strata[index],
                business_date=BUSINESS_DATE,
                question="" if turns else single[index],
                turns=turns,
                expected_values=(),
                expected_sources=(),
                relevant_units=(),
                should_refuse=False,
                labeler="synthetic-fixture",
                label_version=LABEL_VERSION,
            )
        )
    return tuple(cases)


def _item_aliases(number: int, store: str, item: str) -> list[dict[str, Any]]:
    return [
        {"entity_type": "item", "entity_key": f"item|id:p{number:02d}", "filters": {}},
        {"entity_type": "item", "entity_key": f"item|{store}|{item}", "filters": {}},
    ]


def _gold_overrides(cases: tuple[CaseSpec, ...]) -> dict[str, dict[str, dict[str, Any]]]:
    """预先写明的 gold：只有非空结构化使用才需要 targets；空集/缺省不猜目标。"""
    targets = {
        "SYN30-00": _item_aliases(1, "城东店", "宣传海报") + _item_aliases(2, "城西店", "宣传海报"),
        "SYN30-01": _item_aliases(1, "城东店", "宣传海报") + _item_aliases(2, "城西店", "宣传海报"),
        "SYN30-02": _item_aliases(1, "城东店", "宣传海报") + _item_aliases(2, "城西店", "宣传海报"),
        "SYN30-05": _item_aliases(4, "城西店", "展架"),
        "SYN30-06": _item_aliases(5, "城东店", "易拉宝")[:1],
        "SYN30-08": _item_aliases(6, "城西店", "易拉宝"),
    }
    overrides: dict[str, dict[str, dict[str, Any]]] = {}
    for case in cases:
        overrides[case.case_id] = {
            "cross_entity": {
                "applicability": "required",
                "criterion": "structured_target",
                "reason": "explicit_single_target",
                "targets": targets.get(case.case_id, []),
            },
        }
    return overrides


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# 合成封存 dataset / annotation / addendum / custody aggregate / ingest
# --------------------------------------------------------------------------- #


def _expected_kind(case_id: str) -> str:
    """合成问题的预先声明结局：无事实空集题 = 拒答（P1 兼容值 refusal），其余 = answer。"""
    empty_ids = {f"SYN30-{index:02d}" for index in (3, 4, 7, 9)} | {
        f"SYN30-{index:02d}" for index in range(10, 30)
    }
    return "refusal" if case_id in empty_ids else "answer"


def _should_refuse(case_id: str) -> bool:
    return _expected_kind(case_id) == "refusal"


def _question_rows(cases: tuple[CaseSpec, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.append(
            {
                "case_id": case.case_id,
                "suite": "holdout",
                "split": "holdout",
                "stratum": case.stratum,
                "business_date": case.business_date,
                "question": case.question,
                "turns": [turn["question"] for turn in case.turns],
                "expected_kind": _expected_kind(case.case_id),
                "should_refuse": _should_refuse(case.case_id),
                "requires_ocr": False,
                "labeler": "synthetic-fixture",
                "label_version": LABEL_VERSION,
                "notes": "合成修复夹具",
            }
        )
    return rows


def _label_rows(cases: tuple[CaseSpec, ...]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case.case_id,
            "expected_kind": _expected_kind(case.case_id),
            "expected_values": [],
            "expected_sources": [],
            "relevant_units": [],
            "reference_answer": "合成参考答案",
            "should_refuse": _should_refuse(case.case_id),
            "refusal_reason": "synthetic_no_answer" if _should_refuse(case.case_id) else None,
            "forbidden_values": [],
            "forbidden_sources": [],
            "notes": "合成修复夹具",
        }
        for case in cases
    ]


def _turn_stats(cases: tuple[CaseSpec, ...]) -> dict[str, Any]:
    histogram: dict[str, int] = {}
    total = 0
    for case in cases:
        turns = len(helper.case_questions_safe(case))
        total += turns
        histogram[str(turns)] = histogram.get(str(turns), 0) + 1
    return {
        "total_turns": total,
        "max_turns_per_case": max(int(key) for key in histogram),
        "turn_histogram": {key: histogram[key] for key in sorted(histogram, key=int)},
    }


def _write_sealed_dataset(work: Path, cases: tuple[CaseSpec, ...]) -> tuple[Path, Path, str]:
    root = work / "holdout"
    root.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    key_file = work / "holdout.key"
    key_file.write_bytes(key)
    fernet = Fernet(key)
    questions = _question_rows(cases)
    labels = _label_rows(cases)
    q_token = fernet.encrypt(_jsonl(questions))
    l_token = fernet.encrypt(_jsonl(labels))
    (root / QUESTIONS_CIPHERTEXT_NAME).write_bytes(q_token)
    (root / LABELS_CIPHERTEXT_NAME).write_bytes(l_token)
    payload = {
        "schema_version": "p2-holdout-manifest/v0.1",
        "dataset_version": DATASET_VERSION,
        "suite": "p2-holdout",
        "label_version": LABEL_VERSION,
        "case_count": 30,
        "strata": dict(P2_STRATA),
        "business_date": BUSINESS_DATE,
        "created_utc": "2026-11-10T11:08:00Z",
        "author": "synthetic-fixture",
        "encryption": {"kind": "fernet", "key_id": "synthetic-repair-key"},
        "questions_plaintext_sha256": _sha(_jsonl(questions)),
        "labels_plaintext_sha256": _sha(_jsonl(labels)),
        "questions_ciphertext_sha256": _sha(q_token),
        "labels_ciphertext_sha256": _sha(l_token),
        "turn_stats": _turn_stats(cases),
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path, key_file, _sha(manifest_path.read_bytes())


def _rebind_annotation(
    annotation: dict[str, Any],
    *,
    manifest_sha: str,
    source_map_sha: str,
    ingest_sha: str,
    schema_sha: str,
    scenario_sha: str,
    cases_sha: str,
) -> dict[str, Any]:
    annotation["bindings"] = {
        "manifest_sha256": manifest_sha,
        "dataset_version": DATASET_VERSION,
        "label_version": LABEL_VERSION,
        "cases_sha256": cases_sha,
        "source_map_sha256": source_map_sha,
        "ingest_plan_sha256": ingest_sha,
        "schema_sha256": schema_sha,
        "scenario_contract_sha256": scenario_sha,
    }
    return annotation


def _custody_documents(
    work: Path,
    *,
    cases: tuple[CaseSpec, ...],
    annotation: dict[str, Any],
    expected: dict[str, str],
    annotation_cipher_sha: str,
    review_cipher_sha: str,
    review_cipher_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    assignments = [row["scenario_id"] for row in annotation["cases"]]
    axis_counts = {}
    for name in hard.AXES:
        counts = {"required": 0, "not_applicable": 0, "unknown": 0}
        for row in annotation["cases"]:
            counts[str(row["axes"][name]["applicability"])] += 1
        axis_counts[name] = counts
    ingest = json.loads(scenarios.DEFAULT_INGEST.read_text(encoding="utf-8"))
    corpus: dict[str, str] = {}
    for source in ingest["sources"]:
        path = ROOT / str(source["path"])
        corpus["corpus:" + str(source["path"])] = _sha(path.read_bytes())
    review = {
        "schema_version": "p2-h2-custody-review-aggregate/v0.2",
        "verdict": "PASS",
        "status": "BLOCKED",
        "structure": "PASS",
        "semantic_consistency": "PASS",
        "quality_readiness": "BLOCKED",
        "annotation_frozen": True,
        "quality_released": False,
        "annotation_schema_version": "p2-h2-custody/v0.2",
        "annotation_ciphertext_sha256": annotation_cipher_sha,
        "review_ciphertext_path": str(review_cipher_path),
        "review_ciphertext_sha256": review_cipher_sha,
        "bindings": dict(expected),
        "case_count": 30,
        "unique_case_count": 30,
        "same_order_coverage": True,
        "coverage_missing_count": 0,
        "coverage_extra_count": 0,
        "coverage_duplicate_count": 0,
        "scenario_counts": {
            **{name: assignments.count(name) for name, _ix, _b in scenarios.RECIPES},
            "unknown": 0,
        },
        "axis_counts": axis_counts,
        "fixed_gap_counts": {
            "unresolved_entity_target": 0,
            "unresolved_date_anchor": 0,
            "unresolved_scenario": 0,
        },
        "axis_unknown_total": 0,
        "date_anchor_gap_total": 0,
        "independent_review_disagreement_count": 0,
        "scenario_disagreement_count": 0,
        "axis_disagreement_count": 0,
        "old_disagreement_candidate_count": 0,
        "old_disagreement_rejudged_count": 0,
        "old_disagreement_corrected_count": 0,
        "checks": {},
        "input_hashes_before": dict(corpus),
        "input_hashes_after": dict(corpus),
        "input_hashes_unchanged": True,
        "old_ciphertexts_preserved": True,
        "runtime_axis_evidence_produced": False,
        "runtime_owner_context_verification": False,
        "runtime_entity_date_snapshot_verification": False,
        "runtime_global_forbidden_value_source_checks": False,
        "business_date_annotation_is_actual_product_date_proof": False,
        "outbound_socket_blocking_enabled": True,
        "network_measurement_scope": "synthetic-offline",
        "network_attempt_count": 0,
        "product_test_count": 0,
        "real_call_count": 0,
        "subagent_count": 0,
        "commit_count": 0,
        "process_deviations": [],
        "authorization_evidence": {},
    }
    manager = {
        "schema_version": "p2-h2-custody-manager-acceptance/v0.2",
        "date": "2026-11-13",
        "accepted_scope": [
            "annotation_structure",
            "semantic_consistency_with_gaps",
            "scenario_assignment_for_offline_implementation",
        ],
        "independent_review_verdict": "PASS",
        "independent_structure": "PASS",
        "independent_semantic_consistency": "PASS",
        "independent_quality_readiness": "BLOCKED",
        "scenario_assignment_frozen": True,
        "full_annotation_quality_ready": False,
        "live_execution_authorized_by_this_record": False,
        "quality_released": False,
        "annotation_ciphertext_sha256": annotation_cipher_sha,
        "review_ciphertext_sha256": review_cipher_sha,
        "schema_sha256": expected["schema_sha256"],
        "scenario_contract_sha256": expected["scenario_contract_sha256"],
        "case_count": 30,
        "scenario_unknown": 0,
        "independent_disagreements": 0,
        "unresolved_entity_targets": 0,
        "unresolved_date_anchors": 0,
        "runtime_axis_evidence_produced": False,
        "new_real_calls": 0,
    }
    return manager, review


def _build_private_inputs(entry: Any, work: Path, cases: tuple[CaseSpec, ...]) -> SimpleNamespace:
    work.mkdir(parents=True, exist_ok=True)
    manifest_path, holdout_key_file, manifest_sha = _write_sealed_dataset(work, cases)
    with entry.applied_env(
        {HOLDOUT_ROOT_ENV: str(manifest_path.parent), HOLDOUT_KEY_FILE_ENV: str(holdout_key_file)}
    ):
        dataset = load_p2_dataset(manifest_path, visibility="holdout")
    loaded_cases = tuple(dataset.cases)
    source_map = work / "source-map.json"
    source_map.write_bytes(_json_bytes({"schema_version": "synthetic-source-map/v1", "cases": 30}))
    schema_path = H.SCHEMA
    scenario_path = H.CONTRACT
    ingest_path = scenarios.DEFAULT_INGEST
    expected = {
        "manifest_sha256": manifest_sha,
        "dataset_version": DATASET_VERSION,
        "label_version": LABEL_VERSION,
        "cases_sha256": _sha(cases_to_jsonl(loaded_cases).encode("utf-8")),
        "source_map_sha256": _sha(source_map.read_bytes()),
        "ingest_plan_sha256": _sha(ingest_path.read_bytes()),
        "schema_sha256": _sha(schema_path.read_bytes()),
        "scenario_contract_sha256": _sha(scenario_path.read_bytes()),
    }
    annotation = _rebind_annotation(
        H.make_annotation(loaded_cases, overrides=_gold_overrides(loaded_cases), scenario_ids=ASSIGNMENT),
        manifest_sha=expected["manifest_sha256"],
        source_map_sha=expected["source_map_sha256"],
        ingest_sha=expected["ingest_plan_sha256"],
        schema_sha=expected["schema_sha256"],
        scenario_sha=expected["scenario_contract_sha256"],
        cases_sha=expected["cases_sha256"],
    )
    hard.validate_annotation_v02(annotation, loaded_cases)
    scenario_key = Fernet.generate_key()
    scenario_key_file = work / "scenario.key"
    scenario_key_file.write_bytes(scenario_key)
    fernet = Fernet(scenario_key)
    annotation_path = work / "annotation.fernet"
    annotation_path.write_bytes(fernet.encrypt(_json_bytes(annotation)))
    annotation_cipher_sha = _sha(annotation_path.read_bytes())
    addendum = H.make_addendum(
        loaded_cases, annotation, annotation_cipher_sha256=annotation_cipher_sha
    )
    addendum_path = work / "addendum.fernet"
    addendum_path.write_bytes(fernet.encrypt(_json_bytes(addendum)))
    addendum_cipher_sha = _sha(addendum_path.read_bytes())
    review_plain = _json_bytes({"schema_version": "synthetic-review/v1", "verdict": "PASS"})
    review_path = work / "review.fernet"
    review_path.write_bytes(fernet.encrypt(review_plain))
    review_cipher_sha = _sha(review_path.read_bytes())
    manager, review = _custody_documents(
        work,
        cases=loaded_cases,
        annotation=annotation,
        expected=expected,
        annotation_cipher_sha=annotation_cipher_sha,
        review_cipher_sha=review_cipher_sha,
        review_cipher_path=review_path,
    )
    manager_path = work / "manager-acceptance.json"
    manager_path.write_bytes(_json_bytes(manager))
    review_aggregate_path = work / "review-aggregate.json"
    review_aggregate_path.write_bytes(_json_bytes(review))
    merged = hard.prepare_annotation(
        annotation,
        loaded_cases,
        addendum=addendum,
        annotation_cipher_sha256=annotation_cipher_sha,
        schema_path=schema_path,
        scenario_path=scenario_path,
    )
    acceptance = {
        "schema_version": "p2-h2-custody-gapaddendum-manager-acceptance/v0.3",
        "independent_review_verdict": "PASS",
        "addendum_ciphertext_sha256": addendum_cipher_sha,
        "addendum_plaintext_canonical_sha256": entry.payload_sha256(addendum),
        "base_annotation_ciphertext_sha256": annotation_cipher_sha,
        "addendum_frozen": True,
        "live_execution_authorized_by_this_record": False,
        "quality_released": False,
        "runtime_axis_evidence_produced": False,
        "gap_total": 4,
        "gap_resolved": 4,
        "gap_kept_unknown": 0,
        "new_real_calls": 0,
        "accepted_scope": [
            "addendum_structure",
            "semantic_consistency_of_4_gap_resolutions",
            "freeze_as_classifier_annotation_input",
        ],
        "merged_axis_counts": merged.public_summary()["axis_counts"],
    }
    acceptance_path = work / "addendum-acceptance.json"
    acceptance_path.write_bytes(_json_bytes(acceptance))
    paths = entry.InputPaths(
        holdout_manifest=manifest_path,
        annotation_ciphertext=annotation_path,
        review_ciphertext=review_path,
        scenario_key_file=scenario_key_file,
        addendum_ciphertext=addendum_path,
        scenario_contract=scenario_path,
        ingest_plan=ingest_path,
        source_map=source_map,
        annotation_schema=schema_path,
        manager_acceptance_v2=manager_path,
        review_aggregate_v2=review_aggregate_path,
        addendum_acceptance_v3=acceptance_path,
    )
    runtime = entry.RuntimeOptions(
        holdout_root=manifest_path.parent,
        holdout_key_file=holdout_key_file,
        project_total_limit_cny=helper.TOTAL_LIMIT_CNY,
    )
    return SimpleNamespace(
        paths=paths,
        runtime=runtime,
        cases=loaded_cases,
        dataset=dataset,
        annotation=annotation,
        addendum=addendum,
        merged=merged,
        expected=expected,
        work=work,
        holdout_root=manifest_path.parent,
        holdout_key_file=holdout_key_file,
        annotation_cipher_sha=annotation_cipher_sha,
        addendum_cipher_sha=addendum_cipher_sha,
        addendum_acceptance_path=acceptance_path,
        annotation_path=annotation_path,
        addendum_path=addendum_path,
        review_path=review_path,
        scenario_key_file=scenario_key_file,
        schema_path=schema_path,
        scenario_path=scenario_path,
        source_map=source_map,
        manager_path=manager_path,
        review_aggregate_path=review_aggregate_path,
    )


def _write_env(entry: Any, path: Path) -> Path:
    path.write_text(
        "\n".join(key + "=" + value for key, value in helper._env_values().items()) + "\n",
        encoding="utf-8",
    )
    return path


def _inject_expansion(evidence: dict[str, Any]) -> None:
    events = evidence["capture"]["events"]
    claim = next(item["payload"] for item in events if item["kind"] == "claim_observed")
    request_id = claim["request_id"]
    pair = [
        (
            "model_input",
            {
                "request_id": request_id,
                "purpose": "query_expansion",
                "question": "合成扩展问题",
                "context_questions": [],
                "context_entities": {},
                "evidence": [],
            },
        ),
        (
            "model_output",
            {
                "request_id": request_id,
                "purpose": "query_expansion",
                "status": "ok",
                "text": "扩展检索词",
                "source_ids": [],
                "query_terms": ["扩展"],
                "provider_request_id": "synthetic-expansion",
                "usage": {},
                "error_code": None,
                "retryable": False,
            },
        ),
    ]
    index = next(i for i, item in enumerate(events) if item["kind"] == "direct_rag_answer")
    for offset, (kind, payload) in enumerate(pair):
        events.insert(index + offset, {"seq": 0, "kind": kind, "payload": payload})
    for seq, item in enumerate(events, 1):
        item["seq"] = seq
    evidence["capture"]["seq"] = len(events)
    evidence["capture"]["event_count"] = len(events)


def _load_chain(entry: Any, work: Path) -> SimpleNamespace:
    """真实 loader/plan/run 装配；返回可复用的只读链对象。"""
    cases = _cases()
    private = _build_private_inputs(entry, work / "private-inputs", cases)
    bundle = entry.load_private_bundle({}, private.paths, runtime=private.runtime)
    plan_payload = entry.plan_private(
        bundle,
        entry.PlanOptions(
            out_dir=work / "plan",
            created_utc="2026-11-13T00:00:00+00:00",
            max_requests=1100,
        ),
    )
    document = entry.load_run_binding(Path(plan_payload["binding_file"]))
    run_entry = entry._select_run(document, 0)
    plan = entry._load_plan_for_run(document, run_entry)
    ledger = work / "fixed" / "live-ledger.jsonl"
    budget = work / "fixed" / "budget.json"
    go_path = work / "fixed" / "P2-LIVE-GO.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    helper._write_ledger(ledger)
    helper._write_budget(budget)
    helper._write_go(go_path, ledger=ledger, plan=plan)
    p2a.P2_LEDGER_PATH = ledger
    p2a.P2_BUDGET_PATH = budget
    p2a.P2_GO_PATH = go_path
    key_path = work / "evidence.key"
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    chat = helper.UsageChatBackend()
    options = entry.RunOptions(
        out_dir=work / "product",
        evidence_root=work / "evidence",
        seal_root=work / "seal",
        evidence_key_file=key_path,
        process_env=helper._env_values(),
        transports=helper._transports(chat),
        now=helper.NOW,
    )
    ingest = bundle.contract.ingest_plan(SCENARIO)
    base_writer = entry.EvidenceWriter

    class _Writer(base_writer):
        def write_turn(self, evidence: dict[str, Any]) -> dict[str, Any]:
            if int(evidence["turn"]["turn_index"]) == EXPANSION_TURN:
                _inject_expansion(evidence)
            return super().write_turn(evidence)

    entry.EvidenceWriter = _Writer
    try:
        receipt = asyncio.run(
            entry._execute_loaded(
                binding_doc=document,
                run_entry=run_entry,
                plan=plan,
                dataset=bundle.contract.subset(SCENARIO),
                ingest_plan=ingest,
                contract=bundle.contract,
                options=options,
            )
        )
    finally:
        entry.EvidenceWriter = base_writer
    env_path = _write_env(entry, work / ".env")
    recompute_error = None
    result = None
    full_card = None
    try:
        result = entry._recompute_loaded(
            document=document,
            run_entry=run_entry,
            plan=plan,
            cases=tuple(bundle.contract.subset(SCENARIO).cases),
            annotation=private.merged,
            case_plan_payload=json.loads(
                Path(receipt["case_plan"]["path"]).read_text(encoding="utf-8")
            ),
            evidence_dir=receipt["paths"]["evidence_dir"],
            key=key,
            ledger_path=ledger,
            out_card=work / "recomputed-card.json",
        )
        full_card = json.loads(Path(result["card_file"]["path"]).read_text(encoding="utf-8"))
    except entry.EntryError as exc:  # 记录固定码供测试断言（不吞掉）
        recompute_error = exc.code
    return SimpleNamespace(
        work=work,
        cases=private.cases,
        private=private,
        bundle=bundle,
        plan_payload=plan_payload,
        document=document,
        run_entry=run_entry,
        plan=plan,
        ledger=ledger,
        budget=budget,
        go_path=go_path,
        key_path=key_path,
        key=key,
        chat=chat,
        options=options,
        receipt=receipt,
        env_path=env_path,
        evidence_dir=Path(receipt["paths"]["evidence_dir"]) if receipt["paths"]["evidence_dir"] else None,
        case_plan_path=Path(receipt["case_plan"]["path"]) if receipt["case_plan"] else None,
        card_path=work / "recomputed-card.json",
        recompute_error=recompute_error,
        result=result,
        full_card=full_card,
    )


@pytest.fixture(scope="module")
def entry() -> Any:
    spec = importlib.util.spec_from_file_location("p2_eval_repair_entry", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def chain(entry: Any, tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    work = tmp_path_factory.mktemp("t207-eval-repair-chain")
    return _load_chain(entry, work)


# --------------------------------------------------------------------------- #
# 证据副本 / 变体注入（只操作本包新目录，不改原证据）
# --------------------------------------------------------------------------- #


def _copy_evidence(chain: SimpleNamespace, dest: Path) -> Path:
    target = dest / "evidence"
    shutil.copytree(chain.evidence_dir, target)
    for path in target.rglob("*"):
        if path.is_file():
            path.chmod(0o644)  # 封存原件只读；副本必须可写才能重新认证加密
    return target


def _turn_path(evidence_dir: Path, turn_index: int) -> Path:
    return evidence_dir / f"turn-{turn_index:04d}.fernet"


def _rewrite_turn(path: Path, key: bytes, mutate: Any) -> None:
    envelope = evidence_io.read_encrypted_evidence(path, key=key)
    mutate(envelope)
    token = Fernet(key).encrypt(_json_bytes(envelope))
    path.write_bytes(token)


def _resequence(envelope: dict[str, Any]) -> None:
    events = envelope["capture"]["events"]
    for seq, event in enumerate(events, 1):
        event["seq"] = seq
    envelope["capture"]["seq"] = len(events)
    envelope["capture"]["event_count"] = len(events)


def _remove_model_event(purpose: str, kind: str) -> Any:
    def mutate(envelope: dict[str, Any]) -> None:
        events = envelope["capture"]["events"]
        target = next(
            event
            for event in events
            if event["kind"] == kind
            and event["payload"].get("purpose") == purpose
            and event["payload"].get("request_id")
            == next(
                item["payload"]["request_id"]
                for item in events
                if item["kind"] == "claim_observed"
            )
        )
        events.remove(target)
        _resequence(envelope)

    return mutate


def _remove_all_model_events(envelope: dict[str, Any]) -> None:
    events = envelope["capture"]["events"]
    events[:] = [event for event in events if event["kind"] not in ("model_input", "model_output")]
    _resequence(envelope)


def _recompute_variant(
    entry: Any,
    chain: SimpleNamespace,
    evidence_dir: Path,
    *,
    out_name: str,
    case_plan_path: Path | None = None,
) -> SimpleNamespace:
    out_card = chain.work / "variants" / out_name
    out_card.parent.mkdir(parents=True, exist_ok=True)
    result = None
    full_card = None
    error = None
    try:
        result = entry._recompute_loaded(
            document=chain.document,
            run_entry=chain.run_entry,
            plan=chain.plan,
            cases=tuple(chain.bundle.contract.subset(SCENARIO).cases),
            annotation=chain.private.merged,
            case_plan_payload=json.loads(
                (case_plan_path or chain.case_plan_path).read_text(encoding="utf-8")
            ),
            evidence_dir=evidence_dir,
            key=chain.key,
            ledger_path=chain.ledger,
            out_card=out_card,
        )
        full_card = json.loads(Path(result["card_file"]["path"]).read_text(encoding="utf-8"))
    except entry.EntryError as exc:
        error = exc.code
    return SimpleNamespace(result=result, full_card=full_card, error=error, out_card=out_card)


SITECUSTOMIZE = '''"""synthetic outbound guard: any socket creation is recorded and refused."""
import os
import socket

_LOG = os.environ.get("P2REPAIR_SOCKET_LOG")
_RealSocket = socket.socket


def _record():
    if _LOG:
        with open(_LOG, "a", encoding="utf-8") as handle:
            handle.write("blocked\\n")


def _deny(*args, **kwargs):
    _record()
    raise OSError("outbound network blocked by synthetic guard")


class _DeniedSocket(_RealSocket):
    def __init__(self, *args, **kwargs):
        _record()
        raise OSError("outbound network blocked by synthetic guard")


socket.socket = _DeniedSocket
socket.create_connection = _deny
socket.socketpair = _deny
'''

WRAPPER_TEMPLATE = '''"""synthetic CLI wrapper: real tool main(), only fixed paths/env injected."""
import importlib.util
import sys
from pathlib import Path

from mktkb.evaluation import p2_authorization as p2a

p2a.P2_LEDGER_PATH = Path(r"{ledger}")
p2a.P2_BUDGET_PATH = Path(r"{budget}")
p2a.P2_GO_PATH = Path(r"{go}")
spec = importlib.util.spec_from_file_location("p2_h2_controlled_entry_cli", r"{tool}")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.AUTHORIZED_ENV_PATH = Path(r"{env_path}")
sys.exit(module.main(sys.argv[1:]))
'''


def _cli_recompute(
    entry: Any,
    chain: SimpleNamespace,
    tmp_path: Path,
    *,
    evidence_dir: Path,
    out_name: str,
    case_plan_path: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, str]:
    site = tmp_path / ("site-" + out_name)
    site.mkdir(parents=True, exist_ok=True)
    sitecustomize = site / "sitecustomize.py"
    sitecustomize.write_text(SITECUSTOMIZE, encoding="utf-8")
    socket_log = tmp_path / ("socket-" + out_name + ".log")
    if socket_log.exists():
        socket_log.unlink()
    wrapper = tmp_path / ("wrapper-" + out_name + ".py")
    wrapper.write_text(
        WRAPPER_TEMPLATE.format(
            tool=str(TOOL_PATH),
            env_path=str(chain.env_path),
            ledger=str(chain.ledger),
            budget=str(chain.budget),
            go=str(chain.go_path),
        ),
        encoding="utf-8",
    )
    out_card = tmp_path / ("cli-card-" + out_name + ".json")
    command = [
        sys.executable,
        "-B",
        str(wrapper),
        "recompute",
        "--env-file",
        str(chain.env_path),
        "--run-binding",
        str(chain.plan_payload["binding_file"]),
        "--run-index",
        "0",
        "--evidence-dir",
        str(evidence_dir),
        "--evidence-key-file",
        str(chain.key_path),
        "--case-plan",
        str(case_plan_path or chain.case_plan_path),
        "--ledger-path",
        str(chain.ledger),
        "--out-card",
        str(out_card),
        "--holdout-root",
        str(chain.private.holdout_root),
        "--holdout-key-file",
        str(chain.private.holdout_key_file),
        "--project-total-limit-cny",
        "40",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(site) + os.pathsep + str(ROOT / "backend" / "src")
    env["MKTKB_NO_DOTENV"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["P2REPAIR_SOCKET_LOG"] = str(socket_log)
    temp_dir = tmp_path / ("temp-" + out_name)
    temp_dir.mkdir(exist_ok=True)
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    completed = subprocess.run(
        command, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=600
    )
    payload = None
    for line in reversed([line for line in completed.stdout.splitlines() if line.strip()]):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        break
    attempts = socket_log.read_text(encoding="utf-8") if socket_log.exists() else ""
    return completed, payload, attempts


# --------------------------------------------------------------------------- #
# 任务3：正式入口 → 独立重算的合法 gold 全链
# --------------------------------------------------------------------------- #


def test_full_chain_gold_axes_verified_and_expansion_sample(chain: SimpleNamespace) -> None:
    receipt = chain.receipt
    assert receipt["ok"] is True, receipt
    assert receipt["status"] == "succeeded"
    assert receipt["real_sends"] == 0
    assert receipt["evidence"]["turn_files"] == 32
    assert receipt["evidence"]["manifest_turn_count"] == 32
    assert receipt["evidence"]["readback_ok"] is True
    assert receipt["evidence"]["status_counts"] == {"complete": 32}
    assert chain.recompute_error is None
    card = chain.result["card"]
    assert card["total"] == 26
    assert card["verified"] is True
    assert card["missing_evidence_cases"] == 0
    assert card["hard_failures"] == 0
    assert card["release_ready"] is False
    # 质量 pass 与四轴 passed 是不同指标，但本合成 gold 两者都应成立（语义完整样本）。
    assert card["passed"] == 26, card
    assert card["failed"] == 0, card
    expected = {
        "safety": (0, 26, 0, 26),
        "cross_user": (26, 0, 0, 26),
        "cross_entity": (26, 0, 0, 26),
        "stale_source": (26, 0, 0, 26),
    }
    for axis, (passed, na, unknown, checked) in expected.items():
        table = card["axes"][axis]
        assert table["planned"] == 26
        assert table["passed"] == passed, (axis, table)
        assert table["not_applicable"] == na, (axis, table)
        assert table["unknown"] == unknown, (axis, table)
        assert table["violations"] == 0, (axis, table)
        assert table["checked"] == checked, (axis, table)
    full = chain.full_card
    assert full["hard_evidence"]["verified"] is True
    assert full["hard_evidence"]["evidence_complete_cases"] == 26
    assert full["hard_evidence"]["missing_evidence_cases"] == 0
    codes = [block["code"] for block in full["blocks"]]
    # 26/30 场景子集 + 阈值未批：样本/门槛 block 保留；但没有 unverified/缺证据/违规 block。
    assert "holdout_sample_missing" in codes
    assert "holdout_threshold_unapproved" in codes
    for forbidden in (
        "holdout_case_error",
        "holdout_hard_failure",
        "holdout_hard_failure_unverified",
        "holdout_hard_evidence_missing",
    ):
        assert forbidden not in codes, (forbidden, codes)

    # 合成 gold 分支确实存在：rag 直接事实、legacy 模型对、rag expansion 对、严格无模型空集。
    legacy_env = evidence_io.read_encrypted_evidence(_turn_path(chain.evidence_dir, 12), key=chain.key)
    legacy_kinds = [event["kind"] for event in legacy_env["capture"]["events"]]
    assert legacy_kinds.count("model_input") == 1 and legacy_kinds.count("model_output") == 1
    assert all(
        event["payload"].get("purpose") == "answer"
        for event in legacy_env["capture"]["events"]
        if event["kind"] in ("model_input", "model_output")
    )
    rag_env = evidence_io.read_encrypted_evidence(_turn_path(chain.evidence_dir, 11), key=chain.key)
    direct = [
        event["payload"] for event in rag_env["capture"]["events"] if event["kind"] == "direct_rag_answer"
    ]
    assert len(direct) == 1 and len(direct[0]["facts"]) >= 1 and direct[0]["cited_unit_ids"]
    expansion_env = evidence_io.read_encrypted_evidence(_turn_path(chain.evidence_dir, EXPANSION_TURN), key=chain.key)
    pairs = [
        (event["kind"], event["payload"].get("purpose"))
        for event in expansion_env["capture"]["events"]
        if event["kind"] in ("model_input", "model_output")
    ]
    assert pairs.count(("model_input", "query_expansion")) == 1
    assert pairs.count(("model_output", "query_expansion")) == 1
    empty_env = evidence_io.read_encrypted_evidence(_turn_path(chain.evidence_dir, 16), key=chain.key)
    empty_kinds = [event["kind"] for event in empty_env["capture"]["events"]]
    assert "model_input" not in empty_kinds and "model_output" not in empty_kinds
    retrievals = [
        event["payload"] for event in empty_env["capture"]["events"] if event["kind"] == "retrieval_observed"
    ]
    assert retrievals and all(row["unit_ids"] == [] for row in retrievals)
    # 运行期只有 legacy 一次合成 chat；recompute 不新增任何模型调用。
    assert chain.chat.call_count == 1
    assert chain.chat.counts_by_purpose() == {"answer": 1}


def test_cli_recompute_matches_in_process_and_zero_outbound(
    entry: Any, chain: SimpleNamespace, tmp_path: Path
) -> None:
    completed, payload, attempts = _cli_recompute(
        entry, chain, tmp_path, evidence_dir=chain.evidence_dir, out_name="clean"
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert payload is not None and payload["ok"] is True
    assert payload["zero_model_calls"] is True
    assert payload["card"] == chain.result["card"]
    assert payload["coverage"]["turns"] == 32
    assert payload["coverage"]["executed_turns"] == 32
    assert payload["coverage"]["manifest_turn_count"] == 32
    out_card = json.loads(Path(payload["card_file"]["path"]).read_text(encoding="utf-8"))
    assert out_card["hard_evidence"]["verified"] is True
    assert out_card["hard_evidence"]["missing_evidence_cases"] == 0
    assert attempts == "", "独立重算进程不得有任何 socket 创建/出站尝试"


def test_variant_expansion_single_side_blocks_all_axes(
    entry: Any, chain: SimpleNamespace, tmp_path: Path
) -> None:
    evidence_dir = _copy_evidence(chain, tmp_path)
    _rewrite_turn(
        _turn_path(evidence_dir, EXPANSION_TURN),
        chain.key,
        _remove_model_event("query_expansion", "model_output"),
    )
    variant = _recompute_variant(entry, chain, evidence_dir, out_name="expansion-single")
    assert variant.error is None
    card = variant.result["card"]
    assert card["verified"] is False
    assert card["missing_evidence_cases"] == 1
    for axis in hard.AXES:
        assert card["axes"][axis]["unknown"] == 1, (axis, card["axes"][axis])
        assert card["axes"][axis]["checked"] == 25, (axis, card["axes"][axis])
    codes = [block["code"] for block in variant.full_card["blocks"]]
    assert "holdout_hard_failure_unverified" in codes
    assert "holdout_hard_evidence_missing" in codes
    assert card["release_ready"] is False

    completed, payload, attempts = _cli_recompute(
        entry, chain, tmp_path, evidence_dir=evidence_dir, out_name="expansion-single-cli"
    )
    assert completed.returncode == 0
    assert payload["card"]["verified"] is False
    assert payload["card"]["missing_evidence_cases"] == 1
    assert payload["card"] == card
    assert attempts == ""


def test_variant_legacy_removed_model_events_blocks_all_axes(
    entry: Any, chain: SimpleNamespace, tmp_path: Path
) -> None:
    for name, mutate in (
        ("legacy-no-output", _remove_model_event("answer", "model_output")),
        ("legacy-no-events", _remove_all_model_events),
    ):
        evidence_dir = _copy_evidence(chain, tmp_path / name)
        _rewrite_turn(_turn_path(evidence_dir, 12), chain.key, mutate)
        variant = _recompute_variant(entry, chain, evidence_dir, out_name=name)
        assert variant.error is None, (name, variant.error)
        card = variant.result["card"]
        assert card["verified"] is False, name
        assert card["missing_evidence_cases"] == 1, name
        for axis in hard.AXES:
            assert card["axes"][axis]["unknown"] == 1, (name, axis)
            assert card["axes"][axis]["checked"] == 25, (name, axis)
        assert card["release_ready"] is False


def test_variant_missing_key_and_bad_binding_are_refused(
    entry: Any, chain: SimpleNamespace, tmp_path: Path
) -> None:
    def drop_completeness_errors(envelope: dict[str, Any]) -> None:
        envelope["completeness"].pop("errors")

    def tamper_attempt_scope(envelope: dict[str, Any]) -> None:
        envelope["run_binding"]["attempt_scope_sha256"] = "0" * 64

    def masquerade_local_mock(envelope: dict[str, Any]) -> None:
        envelope["fixture_kind"] = "local_mock"
        envelope["bindings"]["fixture_kind"] = "local_mock"
        envelope["schema_version"] = capture.EVIDENCE_SCHEMA_VERSION

    for name, mutate, cli in (
        ("missing-key", drop_completeness_errors, True),
        ("bad-binding", tamper_attempt_scope, False),
        ("local-mock-masquerade", masquerade_local_mock, False),
    ):
        evidence_dir = _copy_evidence(chain, tmp_path / name)
        _rewrite_turn(_turn_path(evidence_dir, 12), chain.key, mutate)
        variant = _recompute_variant(entry, chain, evidence_dir, out_name=name)
        assert variant.result is None, name
        assert variant.error == "evidence_invalid", (name, variant.error)
        if cli:
            completed, payload, attempts = _cli_recompute(
                entry, chain, tmp_path, evidence_dir=evidence_dir, out_name=name + "-cli"
            )
            assert completed.returncode == 2, (name, completed.stdout[-1000:])
            assert payload is not None and payload["error_code"] == "evidence_invalid"
            assert attempts == ""


def test_variant_complete_violations_are_counted_not_unknown(
    entry: Any, chain: SimpleNamespace, tmp_path: Path
) -> None:
    evidence_dir = _copy_evidence(chain, tmp_path)

    def inject_violations(envelope: dict[str, Any]) -> None:
        projection = envelope["db_projection"]
        projection["conversation"]["owner_user_id"] = "synthetic-other-owner"
        for unit in projection["units"]:
            unit["document_deleted"] = True

    _rewrite_turn(_turn_path(evidence_dir, 12), chain.key, inject_violations)
    variant = _recompute_variant(entry, chain, evidence_dir, out_name="violations")
    assert variant.error is None
    card = variant.result["card"]
    assert card["verified"] is True, card
    assert card["hard_failures"] == 1
    assert card["hard_failures_by_kind"]["cross_user"] == 1
    assert card["hard_failures_by_kind"]["stale_source"] == 1
    assert card["hard_failures_by_kind"]["cross_entity"] == 0
    assert card["hard_failures_by_kind"]["safety"] == 0
    assert card["missing_evidence_cases"] == 0
    for axis in ("cross_user", "stale_source"):
        assert card["axes"][axis]["violations"] == 1, (axis, card["axes"][axis])
        assert card["axes"][axis]["unknown"] == 0, (axis, card["axes"][axis])
    codes = [block["code"] for block in variant.full_card["blocks"]]
    assert "holdout_hard_failure" in codes
    assert "holdout_hard_failure_unverified" not in codes
    assert card["release_ready"] is False


def test_service_error_run_is_conservative_and_stops(
    entry: Any, chain: SimpleNamespace, tmp_path: Path
) -> None:
    run_id = "p2-h2-synth-service-error-r1"
    run_entry = {
        **chain.run_entry,
        "run_id": run_id,
        "evidence_bindings": {**dict(chain.run_entry["evidence_bindings"]), "run_id": run_id},
    }
    document = {**chain.document}
    chat = helper.UsageChatBackend(behaviors=(helper.ChatBehavior(kind="invalid_json"),))
    out_dir = tmp_path / "error-product"
    evidence_root = tmp_path / "error-evidence"
    seal_root = tmp_path / "error-seal"
    options = entry.RunOptions(
        out_dir=out_dir,
        evidence_root=evidence_root,
        seal_root=seal_root,
        evidence_key_file=chain.key_path,
        process_env=helper._env_values(),
        transports=helper._transports(chat),
        now=helper.NOW,
    )
    receipt = asyncio.run(
        entry._execute_loaded(
            binding_doc=document,
            run_entry=run_entry,
            plan=chain.plan,
            dataset=chain.bundle.contract.subset(SCENARIO),
            ingest_plan=chain.bundle.contract.ingest_plan(SCENARIO),
            contract=chain.bundle.contract,
            options=options,
        )
    )
    assert receipt["ok"] is False
    assert receipt["status"] in {"aborted", "blocked"}
    assert chat.call_count == 1, "首错停：不得自动重试"
    assert receipt["case_plan"] is not None
    case_plan = json.loads(Path(receipt["case_plan"]["path"]).read_text(encoding="utf-8"))
    statuses = [turn["status"] for row in case_plan["cases"] for turn in row["turns"]]
    assert "not_started" in statuses
    assert statuses.count("executed") >= 12, statuses
    assert sum(1 for status in statuses if status != "executed") >= 1
    out_card = tmp_path / "error-card.json"
    result = entry._recompute_loaded(
        document=document,
        run_entry=run_entry,
        plan=chain.plan,
        cases=tuple(chain.bundle.contract.subset(SCENARIO).cases),
        annotation=chain.private.merged,
        case_plan_payload=case_plan,
        evidence_dir=receipt["paths"]["evidence_dir"],
        key=chain.key,
        ledger_path=chain.ledger,
        out_card=out_card,
    )
    card = result["card"]
    assert card["verified"] is False
    assert card["release_ready"] is False
    assert card["errors"] > 0
    assert any(table["unknown"] > 0 for table in card["axes"].values())
    full = json.loads(out_card.read_text(encoding="utf-8"))
    codes = [block["code"] for block in full["blocks"]]
    assert "holdout_case_error" in codes
    assert "holdout_hard_failure_unverified" in codes
    assert "holdout_hard_evidence_missing" in codes
