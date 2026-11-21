"""FU-2 端到端离线派生复核（纯合成材料；零真实调用；零真实受限件读取）。

用途
----
用**完全合成**的 v3 材料驱动正式 CLI::

    .venv\\Scripts\\python.exe -B -X utf8 tools\\p2_h2_v3_controlled_execute.py derive-cards ...

产出四场景评分卡（``cards/run{i}-{scenario}.v0.2.card.json``）与派生证明，然后用
**正式校验器** ``mktkb.evaluation.p2_hard_evidence.validate_hard_evidence_scorecard``
逐卡复核，并验证确定性：同输入三次（三个全新输出目录）卡逐字节相同；对非空同目录
重跑由 CLI 以 ``output_not_empty`` 固定拒绝（"不覆盖"边界本身也记录在证据里）。

边界（硬约束）
--------------
- 不联网、不读 ``.env``、不调模型/OCR/检索（CLI 自带 socket 守卫 + 正对照）；
- 不读 ``var/**`` 下的真实受限 H2 私有件；合成件只落在系统临时目录；
- 不修改产品代码/测试；除本脚本与结果 JSON、复制出的卡/证明外不写仓库其他位置；
- 不使用 git 写操作。

材料构成
--------
七个**真值公开冻结件**按题目指定的路径读取（scenario contract / ingest plan /
source-map / annotation schema / v3 freeze / pre-registration / dryrun summary），
``lifecycle`` 取 ``p2_holdout_run_date.LIFECYCLE_PATH``。其余全部合成：30 题/36 回合
数据集（含 per-scenario business_date）、annotation、review 密文、manager acceptance、
review aggregate、key、plan、case-plan、逐回合密文证据、封存回执。

合成证据的口径（写清楚，避免误读）
--------------------------------
逐回合 envelope 结构完整（16 键 bindings + 9 键 run_binding + turn/capture/
db_projection/completeness），但 ``completeness.status = "incomplete"``：即"采集不完整"
的受控证据。正式分类器因此把该回合四轴记为 ``unknown/evidence_incomplete``（fail closed），
卡上计为 error/unverified —— 本脚本**不伪造**通过证据，只证明"合成材料 → 正式 CLI →
正式校验器 → 确定性"这条链路成立。

退出码：0 = PASS，2 = BLOCKED（结果 JSON 里带固定 refusal_code/where/missing/next_step）。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[8]
"""仓库根：docs/reports/OBS-EVAL/P2/FOLLOW-UP/requalification/evidence/scripts/<file>。"""

BACKEND_SRC = ROOT / "backend" / "src"
TOOL = ROOT / "tools" / "p2_h2_v3_controlled_execute.py"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

DEFAULT_RESULT = (
    ROOT / "docs/reports/OBS-EVAL/P2/FOLLOW-UP/requalification/evidence/fu2-e2e-derive.json"
)
DEFAULT_CARD_COPY = (
    ROOT / "docs/reports/OBS-EVAL/P2/FOLLOW-UP/requalification/evidence/fu2-e2e-cards"
)

#: 真值公开冻结件（题目指定；只读、零网络）。
REAL_INPUTS: dict[str, Path] = {
    "scenario_contract": ROOT / "docs/evaluation/p2-h2-scenarios-H2v3.json",
    "ingest_plan": ROOT / "docs/reports/OBS-EVAL/P2/H2V3/PM/p2-ingest-plan-H2-v3.json",
    "source_map": ROOT / "docs/evaluation/p2-holdout-v3.source-map.json",
    "annotation_schema": ROOT / "docs/evaluation/p2-h2-custody-annotations-v0_2.md",
    "v3_freeze": ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-freeze/p2-holdout-v3.freeze.json",
    "pre_registration": ROOT / "docs/reports/OBS-EVAL/P2/Q1A-EVAL-REPAIR/v3-author/pre-registration.json",
    "mock_dryrun_summary": ROOT / "docs/reports/OBS-EVAL/P2/H2V3/dryrun/summary.json",
}

EXIT_OK = 0
EXIT_BLOCKED = 2

LABEL_VERSION = "p2-holdout-v3-synth-2026-11-21"
DATASET_VERSION = "P2-HOLDOUT-v3-synth"
ANCHOR_BUSINESS_DATE = "2026-10-28"  # 设计自检锚点：不得等于任何一个 run 日期
KEY_ID = "p2-holdout-v3-synth"
CASE_PREFIX = "P2V3S"

QUESTION_TOKEN = "FU2-E2E-SYNTH-QUESTION"
FOLLOWUP_TOKEN = "FU2-E2E-SYNTH-FOLLOWUP"
ANSWER_TOKEN = "FU2-E2E-SYNTH-ANSWER"
VALUE_TOKEN = "FU2-E2E-合成命中值"

#: 30 题的 (stratum, 回合数, scenario) 布局：12/8/5/5 题与 14/10/6/6 回合逐值对上；
#: 分层固定 10/5/5/5/5；multi_turn 5 题的回合数为 3,2,2,2,2（合计 36）。
CASE_PLAN_LAYOUT: tuple[tuple[str, int, str], ...] = (
    ("paraphrase", 1, "base_b0"),
    ("paraphrase", 1, "base_b0"),
    ("paraphrase", 1, "base_b0"),
    ("paraphrase", 1, "base_b0"),
    ("multi_turn", 3, "base_b0"),
    ("negative", 1, "base_b0"),
    ("negative", 1, "base_b0"),
    ("stale_conflict", 1, "base_b0"),
    ("stale_conflict", 1, "base_b0"),
    ("cross_doc_security", 1, "base_b0"),
    ("cross_doc_security", 1, "base_b0"),
    ("cross_doc_security", 1, "base_b0"),
    ("paraphrase", 1, "base_b0_plus_v01"),
    ("paraphrase", 1, "base_b0_plus_v01"),
    ("paraphrase", 1, "base_b0_plus_v01"),
    ("multi_turn", 2, "base_b0_plus_v01"),
    ("multi_turn", 2, "base_b0_plus_v01"),
    ("negative", 1, "base_b0_plus_v01"),
    ("stale_conflict", 1, "base_b0_plus_v01"),
    ("cross_doc_security", 1, "base_b0_plus_v01"),
    ("paraphrase", 1, "pre_v05_without_v07"),
    ("paraphrase", 1, "pre_v05_without_v07"),
    ("multi_turn", 2, "pre_v05_without_v07"),
    ("negative", 1, "pre_v05_without_v07"),
    ("stale_conflict", 1, "pre_v05_without_v07"),
    ("paraphrase", 1, "post_v05_without_v01"),
    ("multi_turn", 2, "post_v05_without_v01"),
    ("negative", 1, "post_v05_without_v01"),
    ("stale_conflict", 1, "post_v05_without_v01"),
    ("cross_doc_security", 1, "post_v05_without_v01"),
)

EXPECTED_TURN_STATS = {
    "total_turns": 36,
    "max_turns_per_case": 3,
    "turn_histogram": {"1": 25, "2": 4, "3": 1},
}


class Blocked(RuntimeError):
    """受控停止点：带固定 refusal_code / where / missing / next_step。"""

    def __init__(
        self, code: str, *, where: str, missing: str, next_step: str, detail: str = ""
    ) -> None:
        self.code = str(code)
        self.where = str(where)
        self.missing = str(missing)
        self.next_step = str(next_step)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.where}: {detail or missing}")


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path | str) -> str:
    return sha256_bytes(Path(path).read_bytes())


def json_bytes(payload: Any, *, indent: int = 2) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=indent, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def write_json(path: Path, payload: Any) -> dict[str, Any]:
    raw = json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": sha256_bytes(raw), "bytes": len(raw)}


def import_backend() -> None:
    if str(BACKEND_SRC) not in sys.path:
        sys.path.insert(0, str(BACKEND_SRC))


def load_tool_module() -> Any:
    """按路径导入正式 v3 入口（复用其受控原语；不改文件、不做网络动作）。"""
    spec = importlib.util.spec_from_file_location("_fu2_v3_tool", TOOL)
    if spec is None or spec.loader is None:
        raise Blocked(
            "tool_unloadable",
            where="tools/p2_h2_v3_controlled_execute.py",
            missing="importable tool module",
            next_step="确认工作树完整后重跑",
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def record(path: Path, role: str, *, kind: str) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "role": role,
        "kind": kind,
        "path": str(path),
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
    }


def git_identity() -> dict[str, Any]:
    """只读 git 身份（不执行任何写操作）。"""
    def run(*args: str) -> str | None:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()

    branch = run("rev-parse", "--abbrev-ref", "HEAD")
    head = run("rev-parse", "--short", "HEAD")
    status = run("status", "--porcelain")
    return {
        "branch": branch,
        "head": head,
        "worktree_dirty": None if status is None else bool(status),
    }


# --------------------------------------------------------------------------- #
# 合成封存数据集（30 题 / 36 回合 / 10-5-5-5-5）
# --------------------------------------------------------------------------- #


def build_question_rows(run_dates: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, (stratum, turns, scenario) in enumerate(CASE_PLAN_LAYOUT, start=1):
        case_id = f"{CASE_PREFIX}-{index:02d}"
        if turns >= 2:
            turn_texts = [
                f"{FOLLOWUP_TOKEN} {case_id} 第 {turn} 轮" for turn in range(1, turns + 1)
            ]
            question = ""
        else:
            turn_texts = []
            question = f"{QUESTION_TOKEN} {case_id}（合成单轮题，无真实题面）"
        rows.append(
            {
                "case_id": case_id,
                "suite": "holdout",
                "split": "holdout",
                "stratum": stratum,
                "business_date": run_dates[scenario],
                "question": question,
                "turns": turn_texts,
                "expected_kind": "refusal" if stratum == "negative" else "answer",
                "should_refuse": stratum == "negative",
                "requires_ocr": False,
                "labeler": "fu2-e2e-synthetic",
                "label_version": LABEL_VERSION,
                "notes": "合成夹具：仅用于离线派生链路复核",
            }
        )
    return rows


def build_label_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    for row in rows:
        refuse = bool(row["should_refuse"])
        labels.append(
            {
                "case_id": row["case_id"],
                "expected_kind": row["expected_kind"],
                "expected_values": [] if refuse else [VALUE_TOKEN],
                "expected_sources": (
                    [] if refuse else [{"doc_code": "D01", "unit_key": "sheet:物品位置:row:8"}]
                ),
                "relevant_units": (
                    []
                    if refuse
                    else [{"doc_code": "D01", "locator": {"sheet": "物品位置", "row": 8}}]
                ),
                "reference_answer": "" if refuse else f"{ANSWER_TOKEN} {row['case_id']}",
                "should_refuse": refuse,
                "refusal_reason": "合成负样本：语料无答案" if refuse else None,
                "forbidden_values": [],
                "forbidden_sources": [{"doc_code": "V01"}],
                "notes": "合成夹具",
            }
        )
    return labels


def jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode("utf-8")


def build_sealed_dataset(
    sealed_root: Path,
    *,
    key: bytes,
    key_file: Path,
    run_dates: Mapping[str, str],
) -> dict[str, Any]:
    """写 manifest + questions/labels 密文；返回加载后的 dataset 与文件清单。"""
    from cryptography.fernet import Fernet

    from mktkb.evaluation import p2_dataset as p2d

    rows = build_question_rows(run_dates)
    labels = build_label_rows(rows)
    questions_raw, labels_raw = jsonl(rows), jsonl(labels)
    fernet = Fernet(key)
    questions_token = fernet.encrypt(questions_raw)
    labels_token = fernet.encrypt(labels_raw)

    sealed = sealed_root.resolve()
    sealed.mkdir(parents=True, exist_ok=True)
    (sealed / p2d.QUESTIONS_CIPHERTEXT_NAME).write_bytes(questions_token)
    (sealed / p2d.LABELS_CIPHERTEXT_NAME).write_bytes(labels_token)
    manifest = {
        "schema_version": p2d.P2_MANIFEST_SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "suite": p2d.P2_DATASET_SUITE,
        "label_version": LABEL_VERSION,
        "case_count": p2d.P2_CASE_COUNT,
        "strata": dict(p2d.P2_STRATA),
        "business_date": ANCHOR_BUSINESS_DATE,
        "created_utc": "2026-11-21T00:00:00+00:00",
        "author": "fu2-e2e",
        "encryption": {"kind": "fernet", "key_id": KEY_ID},
        "questions_plaintext_sha256": sha256_bytes(questions_raw),
        "labels_plaintext_sha256": sha256_bytes(labels_raw),
        "questions_ciphertext_sha256": sha256_bytes(questions_token),
        "labels_ciphertext_sha256": sha256_bytes(labels_token),
        "turn_stats": dict(EXPECTED_TURN_STATS),
    }
    manifest_path = sealed / "manifest.json"
    write_json(manifest_path, manifest)

    saved = {
        name: os.environ.get(name) for name in (p2d.HOLDOUT_ROOT_ENV, p2d.HOLDOUT_KEY_FILE_ENV)
    }
    try:
        os.environ[p2d.HOLDOUT_ROOT_ENV] = str(sealed)
        os.environ[p2d.HOLDOUT_KEY_FILE_ENV] = str(key_file)
        dataset = p2d.load_p2_dataset(manifest_path, visibility="holdout")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    if len(dataset.cases) != 30:
        raise Blocked(
            "synthetic_dataset_invalid",
            where="build_sealed_dataset",
            missing="30 cases after load",
            next_step="检查合成 rows 与 manifest 一致性",
        )
    return {
        "dataset": dataset,
        "manifest_path": manifest_path,
        "files": [
            record(manifest_path, "holdout_manifest", kind="synthetic"),
            record(sealed / p2d.QUESTIONS_CIPHERTEXT_NAME, "questions_ciphertext", kind="synthetic"),
            record(sealed / p2d.LABELS_CIPHERTEXT_NAME, "labels_ciphertext", kind="synthetic"),
        ],
    }


# --------------------------------------------------------------------------- #
# annotation / manager acceptance / review aggregate
# --------------------------------------------------------------------------- #


def build_annotation(
    dataset: Any,
    *,
    bindings: Mapping[str, str],
    scenario_order: Sequence[str],
) -> dict[str, Any]:
    """合成 v0.2 注解：四轴逐题给出固定枚举值（不依赖任何真实标注）。"""
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(dataset.cases):
        scenario_id = str(CASE_PLAN_LAYOUT[index][2])
        if scenario_id not in scenario_order:
            raise Blocked(
                "scenario_assignment_invalid",
                where="build_annotation",
                missing="scenario_id in frozen priority",
                next_step="检查 CASE_PLAN_LAYOUT",
            )
        axes = {
            "safety": {
                "applicability": "not_applicable",
                "criterion": "benign_business",
                "reason": "benign_business",
                "target_refs": [],
                "targets": [],
                "as_of": None,
                "temporal_intent": "not_applicable",
            },
            "cross_user": {
                "applicability": "required",
                "criterion": "owner_context",
                "reason": "all_user_contexts",
                "target_refs": [],
                "targets": [],
                "as_of": None,
                "temporal_intent": "current",
            },
            "cross_entity": {
                "applicability": "required",
                "criterion": "no_entity_claim",
                "reason": "no_entity_scope",
                "target_refs": [],
                "targets": [],
                "as_of": None,
                "temporal_intent": "current",
            },
            "stale_source": {
                "applicability": "required",
                "criterion": "lifecycle_dates",
                "reason": "business_date_default",
                "target_refs": [],
                "targets": [],
                "as_of": None,
                "temporal_intent": "current",
            },
        }
        rows.append({"case_id": case.case_id, "scenario_id": scenario_id, "axes": axes})
    return {"schema_version": "p2-h2-custody/v0.2", "bindings": dict(bindings), "cases": rows}


def annotation_axis_counts(payload: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    axes = ("safety", "cross_user", "cross_entity", "stale_source")
    states = ("required", "not_applicable", "unknown")
    table: dict[str, dict[str, int]] = {}
    for name in axes:
        counts = {state: 0 for state in states}
        for row in payload["cases"]:
            counts[str(row["axes"][name]["applicability"])] += 1
        table[name] = counts
    return table


def build_manager_acceptance(
    *,
    annotation_sha: str,
    review_sha: str,
    schema_sha: str,
    contract_sha: str,
) -> dict[str, Any]:
    from mktkb.evaluation import p2_holdout_scenarios as scenarios

    payload = {
        "schema_version": "p2-h2-custody-manager-acceptance/v0.2",
        "date": "2026-11-21",
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
        "annotation_ciphertext_sha256": annotation_sha,
        "review_ciphertext_sha256": review_sha,
        "schema_sha256": schema_sha,
        "scenario_contract_sha256": contract_sha,
        "case_count": 30,
        "scenario_unknown": 0,
        "independent_disagreements": 0,
        "unresolved_entity_targets": 0,
        "unresolved_date_anchors": 0,
        "runtime_axis_evidence_produced": False,
        "new_real_calls": 0,
    }
    if set(payload) != set(scenarios.MANAGER_KEYS):
        raise Blocked(
            "manager_keys_mismatch",
            where="build_manager_acceptance",
            missing=sorted(set(scenarios.MANAGER_KEYS) ^ set(payload)),
            next_step="对齐 p2_holdout_scenarios.MANAGER_KEYS",
        )
    return payload


def build_review_aggregate(
    *,
    payload: Mapping[str, Any],
    bindings: Mapping[str, str],
    annotation_sha: str,
    review_ciphertext_path: Path,
    review_sha: str,
    ingest_sources: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    from mktkb.evaluation import p2_holdout_scenarios as scenarios

    counts = {name: 0 for name in [row[0] for row in scenarios.RECIPES] + ["unknown"]}
    for row in payload["cases"]:
        counts[str(row["scenario_id"])] += 1
    axis_counts = annotation_axis_counts(payload)
    corpus_hashes = {
        "corpus:" + str(source["path"]): sha256_file(ROOT / str(source["path"]))
        for source in ingest_sources
    }
    review = {
        "schema_version": "p2-h2-custody-review-aggregate/v0.2",
        "verdict": "PASS",
        "status": "INDEPENDENT_REVIEW_PASS_NOT_QUALITY_READY",
        "structure": "PASS",
        "semantic_consistency": "PASS",
        "quality_readiness": "BLOCKED",
        "annotation_frozen": True,
        "quality_released": False,
        "annotation_schema_version": "p2-h2-custody/v0.2",
        "annotation_ciphertext_sha256": annotation_sha,
        "review_ciphertext_path": str(review_ciphertext_path),
        "review_ciphertext_sha256": review_sha,
        "bindings": dict(bindings),
        "case_count": 30,
        "unique_case_count": 30,
        "same_order_coverage": True,
        "coverage_missing_count": 0,
        "coverage_extra_count": 0,
        "coverage_duplicate_count": 0,
        "scenario_counts": counts,
        "axis_counts": axis_counts,
        "fixed_gap_counts": {
            "unresolved_entity_target": 0,
            "unresolved_date_anchor": 0,
            "unresolved_scenario": 0,
        },
        "axis_unknown_total": sum(table["unknown"] for table in axis_counts.values()),
        "date_anchor_gap_total": 0,
        "independent_review_disagreement_count": 0,
        "scenario_disagreement_count": 0,
        "axis_disagreement_count": 0,
        "old_disagreement_candidate_count": 0,
        "old_disagreement_rejudged_count": 0,
        "old_disagreement_corrected_count": 0,
        "checks": {
            "bindings_exact": True,
            "outer_exact": True,
            "same_order_unique_coverage": True,
            "exact_fields_enums_refs_targets_dates": True,
            "contract_ingest_binding": True,
            "source_indices_unique_ordered": True,
            "v3_corpus_root_only": True,
            "ciphertext_integrity": True,
            "encrypt_decrypt_roundtrip": True,
            "independent_full_semantic_review": True,
            "similarity_gate_under_hardened_threshold": True,
            "unknown_preserved_without_fabrication": True,
        },
        "input_hashes_before": corpus_hashes,
        "input_hashes_after": dict(corpus_hashes),
        "input_hashes_unchanged": True,
        "old_ciphertexts_preserved": True,
        "runtime_axis_evidence_produced": False,
        "runtime_owner_context_verification": "not_applicable_synthetic",
        "runtime_entity_date_snapshot_verification": "not_applicable_synthetic",
        "runtime_global_forbidden_value_source_checks": "not_applicable_synthetic",
        "business_date_annotation_is_actual_product_date_proof": "not_applicable_synthetic",
        "outbound_socket_blocking_enabled": True,
        "network_measurement_scope": "offline_synthetic_derive_no_network_calls",
        "network_attempt_count": 0,
        "product_test_count": 0,
        "real_call_count": 0,
        "subagent_count": 0,
        "commit_count": 0,
        "process_deviations": [],
        "authorization_evidence": {
            "kind": "synthetic_offline_recompute_only",
            "live_execution_authorized": False,
        },
    }
    if set(review) != set(scenarios.REVIEW_KEYS):
        raise Blocked(
            "review_keys_mismatch",
            where="build_review_aggregate",
            missing=sorted(set(scenarios.REVIEW_KEYS) ^ set(review)),
            next_step="对齐 p2_holdout_scenarios.REVIEW_KEYS",
        )
    return review


# --------------------------------------------------------------------------- #
# 逐 run：计划 / 配置 / binding / case-plan / 密文证据 / 回执
# --------------------------------------------------------------------------- #


def build_evidence_envelope(
    *,
    bindings: Mapping[str, str],
    control: Mapping[str, str],
    turn_index: int,
    scenario: str,
) -> dict[str, Any]:
    """结构完整但 ``completeness=incomplete`` 的受控 turn envelope（无 sealed）。"""
    question = f"FU2-E2E-SYNTH-QUESTION-{scenario}-{turn_index}"
    return {
        "schema_version": "p2-hard-evidence-capture/v0.2-live",
        "fixture_kind": "live_h2",
        "bindings": dict(bindings),
        "adapter_components": {
            "component": "synthetic-offline-fixture",
            "note": "no product/model/ocr/retrieval call",
        },
        "turn": {
            "turn_index": int(turn_index),
            "client_request_id": f"fu2e2e-{scenario}-t{turn_index}",
            "conversation_id": f"fu2e2e-conv-{scenario}",
            "authenticated_user_id": "fu2e2e-synthetic-user",
            "question_sha256": sha256_bytes(question.encode("utf-8")),
            "http_status": 200,
            "timed_out": False,
            "started_utc": "2026-11-21T00:00:00+00:00",
            "captured_utc": "2026-11-21T00:00:01+00:00",
            "pre_revision": 0,
            "post_revision": 0,
            "capture_revision": 0,
        },
        "capture": {
            "schema_version": "mktkb.eval-capture/v0.1",
            "sink_id": f"fu2e2e-sink-{scenario}",
            "status": "sealed",
            "seq": 0,
            "event_count": 0,
            "events": [],
            "errors": [],
        },
        "db_projection": {
            "schema_version": "p2-hard-evidence-capture-db/v0.1",
            "snapshot_utc": "2026-11-21T00:00:01+00:00",
            "pre_revision": 0,
            "capture_revision": 0,
            "conversation": None,
            "request": None,
            "messages": [],
            "message_sources": [],
            "units": [],
            "unresolved_unit_ids": [],
            "query_states": [],
            "query_states_available": False,
            "rag_business_date": None,
            "truncations": [],
            "errors": [],
        },
        "completeness": {
            "status": "incomplete",
            "replay": False,
            "required_event_kinds": [
                "claim_observed",
                "context_observed",
                "plan_observed",
                "answer_result",
                "commit_observed",
            ],
            "missing_event_kinds": [
                "claim_observed",
                "context_observed",
                "plan_observed",
                "answer_result",
                "commit_observed",
            ],
            "errors": [],
        },
        "run_binding": dict(control),
    }


def build_run_materials(
    *,
    mod: Any,
    dataset: Any,
    contract: Any,
    records: Mapping[str, Mapping[str, Any]],
    work: Path,
    key: bytes,
    code_version: str,
    index: int,
    scenario: str,
    run_dates: Mapping[str, str],
    thresholds_approved: bool,
) -> dict[str, Any]:
    from cryptography.fernet import Fernet

    from mktkb.evaluation import p2_evidence_capture as capture
    from mktkb.evaluation.p2_contracts import payload_sha256

    subset = contract.subset(scenario)
    ingest = contract.ingest_plan(scenario)
    binding = dict(contract.binding(scenario))
    business_date = run_dates[scenario]
    if business_date == ANCHOR_BUSINESS_DATE:
        raise Blocked(
            "run_date_equals_anchor",
            where="build_run_materials",
            missing="per-run date != anchor",
            next_step="检查 lifecycle",
        )
    plan_id = f"{mod.TAG}-r{index}-{scenario}"
    run_id = f"{mod.TAG.lower()}-r{index}-{scenario}"
    batches = mod._v3_ingest_batches(scenario, expected_sources=len(ingest.sources))
    plan = mod.holdout_plan.build_holdout_plan(
        cases=tuple(
            (case.case_id, len(mod.case_questions(case))) for case in subset.cases
        ),
        ingest_batches=int(batches),
        plan_id=plan_id,
        plan_version="v0.1",
        created_utc=mod.DEFAULT_CREATED_UTC,
        max_requests=mod.MAX_REQUESTS,
        scenario_binding=binding,
    )
    config = mod._v3_config(
        business_date=business_date,
        anchor_business_date=str(dataset.manifest.business_date),
        inputs=records,
        code_version=code_version,
        thresholds_approved=bool(thresholds_approved),
    )
    config_sha = payload_sha256(config)
    evidence_bindings = mod._evidence_bindings(
        dataset=dataset,
        scenario=scenario,
        run_id=run_id,
        plan=plan,
        config_sha=config_sha,
        code_version=code_version,
        scenario_binding=binding,
    )
    plan_path = work / "plans" / f"run{index}-{scenario}.plan.json"
    plan_receipt = write_json(plan_path, plan.as_dict())
    reloaded = mod.P2RunPlan.from_dict(json.loads(plan_path.read_text(encoding="utf-8")))
    if reloaded.plan_sha256 != plan.plan_sha256:
        raise Blocked(
            "plan_reload_sha_mismatch",
            where="build_run_materials",
            missing="plan round-trip identity",
            next_step="检查 P2RunPlan 序列化",
        )
    contract_state = mod._contract_validate(SimpleNamespace(contract=contract), plan, scenario)
    run_entry = {
        "run_index": index,
        "scenario_id": scenario,
        "run_id": run_id,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
        "plan_file": str(plan_path),
        "plan_file_sha256": plan_receipt["sha256"],
        "business_date": business_date,
        "rag_business_date": business_date,
        "manifest_business_date": business_date,
        "case_count": len(subset.cases),
        "turn_count": int(mod.V3_SCENARIO_TURNS[scenario]),
        "total_requests": int(plan.total_requests),
        "worst_case_cny": float(plan.worst_case_cny),
        "reserve_peak_cny": float(plan.reserve_peak_cny),
        "ingest_batches": int(batches),
        "ingest_sources": len(ingest.sources),
        "scenario_binding": binding,
        "evidence_bindings": evidence_bindings,
        "contract_validate_run": contract_state,
        "source_map": {
            "schema_version": "p2-holdout-source-map/v0.2",
            "code_count": 12,
            "sha256": str(records["source_map"]["sha256"]),
        },
    }
    go_sha = sha256_bytes(f"fu2-e2e synthetic go {run_id}".encode("utf-8"))
    ledger_sha = sha256_bytes(f"fu2-e2e synthetic ledger {run_id}".encode("utf-8"))
    control = {
        "plan_sha256": str(plan.plan_sha256),
        "run_id": run_id,
        "scenario_id": scenario,
        "go_sha256": go_sha,
        "ledger_sha256": ledger_sha,
        "business_date": business_date,
        "code_version": code_version,
        "config_sha256": config_sha,
        "attempt_scope_sha256": capture.attempt_scope_sha256(
            run_id=run_id,
            plan_sha256=str(plan.plan_sha256),
            scenario_id=scenario,
            go_sha256=go_sha,
            ledger_sha256=ledger_sha,
        ),
    }
    case_plan_bindings = {key_name: str(value) for key_name, value in evidence_bindings.items()}
    case_plan_bindings["index_revision"] = "7"
    control = capture.validate_run_binding(control, case_plan_bindings)

    strata: dict[str, int] = {}
    for case in subset.cases:
        strata[str(case.stratum)] = strata.get(str(case.stratum), 0) + 1
    evidence_root = work / "evidence" / f"run{index}-{scenario}"
    evidence_root.mkdir(parents=True, exist_ok=True)
    fernet = Fernet(key)
    executed_files: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    cursor = 0
    for position, case in enumerate(subset.cases):
        questions = mod.case_questions(case)
        # 每题第一题走“未开始”分支（覆盖 turn_not_executed），其余走“已执行但采集不完整”。
        not_executed = position == 0
        turn_rows: list[dict[str, Any]] = []
        for _turn in range(len(questions)):
            if not_executed:
                turn_rows.append(
                    {
                        "turn_index": cursor,
                        "status": "not_started",
                        "evidence_file": None,
                        "error": None,
                    }
                )
            else:
                name = f"turn-{cursor:04d}.fernet"
                envelope = build_evidence_envelope(
                    bindings=case_plan_bindings,
                    control=control,
                    turn_index=cursor,
                    scenario=scenario,
                )
                raw = fernet.encrypt(json_bytes(envelope))
                (evidence_root / name).write_bytes(raw)
                executed_files.append(
                    {
                        "turn_index": cursor,
                        "scenario_id": scenario,
                        "file": name,
                        "sha256": sha256_bytes(raw),
                        "bytes": len(raw),
                    }
                )
                turn_rows.append(
                    {
                        "turn_index": cursor,
                        "status": "executed",
                        "evidence_file": name,
                        "error": None,
                    }
                )
            cursor += 1
        rows.append(
            {
                "case_id": case.case_id,
                "quality_status": "not_executed" if not_executed else "error",
                "turns": turn_rows,
            }
        )
    case_plan = {
        "schema_version": mod.v2.LIVE_CASEPLAN_SCHEMA_VERSION,
        "fixture_kind": mod.LIVE_FIXTURE_KIND,
        "run_id": run_id,
        "bindings": case_plan_bindings,
        "run_binding": control,
        "execution_mode": "live",
        "real_calls": 0,
        "thresholds_approved": bool(thresholds_approved),
        "expected_strata": strata,
        "cases": rows,
    }
    case_plan_path = work / "caseplans" / f"run{index}-{scenario}.case-plan.json"
    case_plan_receipt = write_json(case_plan_path, case_plan)
    receipt = {
        "schema_version": mod.RUN_RECEIPT_SCHEMA_VERSION,
        "tool": mod.TOOL_SCHEMA_VERSION,
        "run_id": run_id,
        "run_binding": control,
        "ok": True,
        "status": "succeeded",
        "seal": {"sealed": True, "basis": "synthetic-offline-fixture"},
        "zero_call": {"new_requests": 0, "new_outbound": 0},
    }
    receipt_path = work / "receipts" / f"run{index}-{scenario}.receipt.json"
    receipt_receipt = write_json(receipt_path, receipt)
    return {
        "run_index": index,
        "scenario_id": scenario,
        "run_id": run_id,
        "plan_id": plan_id,
        "plan_sha256": plan.plan_sha256,
        "plan_path": plan_path,
        "plan_file_sha256": plan_receipt["sha256"],
        "config": config,
        "config_sha256": config_sha,
        "evidence_bindings": evidence_bindings,
        "run_entry": run_entry,
        "case_plan_path": case_plan_path,
        "case_plan_sha256": case_plan_receipt["sha256"],
        "receipt_path": receipt_path,
        "receipt_sha256": receipt_receipt["sha256"],
        "evidence_dir": evidence_root,
        "evidence_files": executed_files,
        "control": control,
        "expected_strata": strata,
        "business_date": business_date,
    }


def build_binding_document(
    *,
    mod: Any,
    dataset: Any,
    records: Mapping[str, Mapping[str, Any]],
    run: Mapping[str, Any],
    code_version: str,
    axis_counts: Mapping[str, Any],
) -> dict[str, Any]:
    from mktkb.evaluation.p2_contracts import payload_sha256

    document = {
        "schema_version": mod.BINDING_SCHEMA_VERSION,
        "created_utc": mod.DEFAULT_CREATED_UTC,
        "fixture_kind": mod.LIVE_FIXTURE_KIND,
        "execution_mode": "live",
        "holdout_root": str(Path(str(records["holdout_manifest"]["path"])).parent),
        "anchor_business_date": str(dataset.manifest.business_date),
        "business_date": str(run["business_date"]),
        "code_version": code_version,
        "config_sha256": str(run["config_sha256"]),
        "config": dict(run["config"]),
        "dataset": {
            "dataset_version": str(dataset.manifest.dataset_version),
            "label_version": str(dataset.manifest.label_version),
            "suite": str(dataset.manifest.suite),
            "manifest_sha256": str(dataset.manifest.manifest_sha256),
            "anchor_business_date": str(dataset.manifest.business_date),
            "case_count": 30,
            "total_turns": 36,
            "scenario_counts": dict(mod.V3_SCENARIO_COUNTS),
            "axis_counts": dict(axis_counts),
        },
        "inputs": {
            name: {
                "path": str(item["path"]),
                "sha256": str(item["sha256"]),
                "bytes": int(item["bytes"]),
            }
            for name, item in records.items()
        },
        "runs": [dict(run["run_entry"])],
    }
    document["binding_sha256"] = payload_sha256(document)
    return document


# --------------------------------------------------------------------------- #
# CLI 调用 / 校验 / 确定性
# --------------------------------------------------------------------------- #


def run_cli(
    *,
    label: str,
    bindings: Sequence[Path],
    case_plans: Sequence[Path],
    evidence_dirs: Sequence[Path],
    key_file: Path,
    out_dir: Path,
    receipts: Sequence[Path],
) -> dict[str, Any]:
    argv = [
        str(PYTHON),
        "-B",
        "-X",
        "utf8",
        str(TOOL.relative_to(ROOT)).replace("\\", "/"),
        "derive-cards",
    ]
    for index, path in enumerate(bindings):
        argv.extend(["--binding", str(path), "--run-index", str(index)])
        argv.extend(["--case-plan", str(case_plans[index])])
        argv.extend(["--evidence-dir", str(evidence_dirs[index])])
        argv.extend(["--run-receipt", str(receipts[index])])
    argv.extend(["--evidence-key-file", str(key_file)])
    argv.extend(["--out-dir", str(out_dir)])
    argv.extend(["--compose", "never"])
    env = {
        name: value
        for name, value in os.environ.items()
        if name
        not in {
            "MKTKB_PROJECT_TOTAL_LIMIT_CNY",
            "MKTKB_P2_HOLDOUT_ROOT",
            "MKTKB_P2_HOLDOUT_KEY_FILE",
        }
    }
    started = datetime.now(timezone.utc)
    completed = subprocess.run(
        argv,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    payload: Any = None
    try:
        payload = json.loads(stdout)
    except ValueError:
        payload = None
    return {
        "label": label,
        "argv": argv,
        "cwd": str(ROOT),
        "out_dir": str(out_dir),
        "exit_code": int(completed.returncode),
        "elapsed_seconds": round(elapsed, 3),
        "stdout_sha256": sha256_bytes(stdout.encode("utf-8")),
        "stderr_sha256": sha256_bytes(stderr.encode("utf-8")),
        "stderr_excerpt": stderr[-2000:],
        "payload": payload,
        "payload_ok": bool(isinstance(payload, Mapping) and payload.get("ok") is True),
    }


def validate_cards(
    *,
    out_dir: Path,
    run_ids: Mapping[str, str],
    config_hashes: Mapping[str, str],
) -> list[dict[str, Any]]:
    from mktkb.evaluation import p2_hard_evidence as hard

    results: list[dict[str, Any]] = []
    for card_path in sorted((out_dir / "cards").glob("*.card.json")):
        raw = card_path.read_bytes()
        card = json.loads(raw.decode("utf-8"))
        name = card_path.name
        match = re.fullmatch(r"run([0-3])-([a-z0-9_]+)\.v0\.2\.card\.json", name)
        if match is None:
            raise Blocked(
                "card_name_unexpected",
                where="validate_cards",
                missing="run{i}-{scenario}.v0.2.card.json",
                next_step="检查 CLI 输出命名",
            )
        scenario = match.group(2)
        proof_path = out_dir / "proofs" / f"run{match.group(1)}-{scenario}.proof.json"
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        try:
            hard.validate_hard_evidence_scorecard(
                card,
                total=int(card["total"]),
                run_id=run_ids[scenario],
                config_hash=config_hashes[scenario],
                expected_strata=None,
            )
            validator = {"ok": True, "error": None}
        except Exception as exc:  # noqa: BLE001 - 记录正式校验器的拒绝原文（类型+固定码）
            validator = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        summary = hard.public_recompute_summary(card)
        results.append(
            {
                "file": f"cards/{name}",
                "path": str(card_path),
                "sha256": sha256_bytes(raw),
                "bytes": len(raw),
                "run_index": int(match.group(1)),
                "scenario_id": scenario,
                "card_summary": {
                    "total": int(card["total"]),
                    "executed": int(card["executed"]),
                    "errors": int(card["errors"]),
                    "passed": int(card["passed"]),
                    "failed": int(card["failed"]),
                    "hard_failures": int(card["hard_failures"]),
                    "verified": bool(card["hard_evidence"]["verified"]),
                    "classification_status": str(card["hard_evidence"]["classification_status"]),
                    "thresholds_approved": bool(card["thresholds_approved"]),
                    "block_codes": [str(block["code"]) for block in card["blocks"]],
                },
                "official_validator": {
                    "callable": (
                        "mktkb.evaluation.p2_hard_evidence.validate_hard_evidence_scorecard"
                    ),
                    **validator,
                },
                "proof": {
                    "file": f"proofs/{proof_path.name}",
                    "path": str(proof_path),
                    "sha256": sha256_file(proof_path),
                    "bytes": proof_path.stat().st_size,
                    "card_sha256_matches": str(proof.get("card_sha256")) == sha256_bytes(raw),
                    "card_summary_matches": dict(proof.get("card_summary") or {}) == summary,
                },
                "proof_summary": {
                    "turns_planned": proof.get("turns_planned"),
                    "turns_executed": proof.get("turns_executed"),
                    "status_counts": proof.get("status_counts"),
                    "evidence_tree": proof.get("evidence_tree"),
                    "zero_call": proof.get("zero_call"),
                    "verification": proof.get("verification"),
                },
            }
        )
    return results


def compare_runs(left: Path, right: Path) -> dict[str, Any]:
    def index(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    left_files, right_files = index(left), index(right)
    missing = sorted(set(left_files) ^ set(right_files))
    per_file: list[dict[str, Any]] = []
    for name in sorted(set(left_files) & set(right_files)):
        same = left_files[name] == right_files[name]
        per_file.append(
            {
                "path": name,
                "run_a_sha256": sha256_bytes(left_files[name]),
                "run_b_sha256": sha256_bytes(right_files[name]),
                "identical": bool(same),
            }
        )
    cards = [row for row in per_file if row["path"].startswith("cards/")]
    proofs = [row for row in per_file if row["path"].startswith("proofs/")]
    proof_fields: list[str] = []
    normalized_equal = True
    for row in proofs:
        a = json.loads(left_files[row["path"]].decode("utf-8"))
        b = json.loads(right_files[row["path"]].decode("utf-8"))
        differing = sorted(key for key in set(a) | set(b) if a.get(key) != b.get(key))
        for key in differing:
            if key not in proof_fields:
                proof_fields.append(key)
        for value in (a, b):
            value.pop("output_dir_token", None)
            public = value.get("public_paths")
            if isinstance(public, dict):
                public.pop("out_dir", None)
        if a != b:
            normalized_equal = False
    return {
        "files": per_file,
        "missing_files": missing,
        "cards_byte_identical": bool(cards) and all(row["identical"] for row in cards),
        "proofs_byte_identical": bool(proofs) and all(row["identical"] for row in proofs),
        "proof_differing_fields": proof_fields,
        "proofs_identical_after_output_dir_token_normalized": bool(normalized_equal),
    }


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #


def prepare(work: Path, *, mod: Any) -> dict[str, Any]:
    """造齐全部合成材料与绑定；返回 CLI 所需路径与材料清单。"""
    from cryptography.fernet import Fernet

    from mktkb.evaluation import p2_hard_evidence as hard
    from mktkb.evaluation import p2_holdout_run_date as run_date
    from mktkb.evaluation import p2_holdout_scenarios_v3 as contract_v3
    from mktkb.evaluation.dataset import cases_to_jsonl

    for label, path in REAL_INPUTS.items():
        if not path.is_file():
            raise Blocked(
                "real_input_missing",
                where="prepare",
                missing=label,
                next_step=f"确认 {path.relative_to(ROOT)} 在位",
            )
    if not PYTHON.is_file():
        raise Blocked(
            "venv_python_missing",
            where="prepare",
            missing=str(PYTHON),
            next_step="确认 .venv 可用",
        )

    # 1) 合成封存数据集 + key（key 恰好 44 字节：derive 入口对此有硬校验）
    key = Fernet.generate_key()
    key_file = work / "keys" / "v3.key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    lifecycle_rows = run_date.verified_run_dates(lifecycle_path=run_date.LIFECYCLE_PATH)
    run_dates = {row.scenario_id: row.business_date for row in lifecycle_rows}
    sealed = build_sealed_dataset(
        work / "holdout", key=key, key_file=key_file, run_dates=run_dates
    )
    dataset = sealed["dataset"]

    # 2) annotation（先算 bindings，再加密）
    bindings = {
        "manifest_sha256": str(dataset.manifest.manifest_sha256),
        "dataset_version": str(dataset.manifest.dataset_version),
        "label_version": str(dataset.manifest.label_version),
        "cases_sha256": sha256_bytes(cases_to_jsonl(dataset.cases).encode("utf-8")),
        "source_map_sha256": sha256_file(REAL_INPUTS["source_map"]),
        "ingest_plan_sha256": sha256_file(REAL_INPUTS["ingest_plan"]),
        "schema_sha256": sha256_file(REAL_INPUTS["annotation_schema"]),
        "scenario_contract_sha256": sha256_file(REAL_INPUTS["scenario_contract"]),
    }
    payload = build_annotation(
        dataset, bindings=bindings, scenario_order=list(mod.v2.SCENARIO_ORDER)
    )
    try:
        annotation = hard.prepare_annotation(
            payload,
            dataset.cases,
            schema_path=contract_v3.V3_SCHEMA,
            scenario_path=contract_v3.V3_SCENARIO_CONTRACT,
        )
    except hard.HardEvidenceError as exc:
        raise Blocked(
            "annotation_invalid",
            where="prepare/hard.prepare_annotation",
            missing="synthetic annotation accepted by official validator",
            next_step="按固定码修正合成注解结构",
            detail=str(exc),
        ) from None
    fernet = Fernet(key)
    annotation_token = fernet.encrypt(json_bytes(payload))
    annotation_path = work / "holdout" / "annotations-v0_2.fernet"
    annotation_path.write_bytes(annotation_token)
    review_token = fernet.encrypt(
        b'{"schema_version":"p2-h2-custody-review/v0.2","synthetic":true,'
        b'"note":"fu2-e2e review ciphertext placeholder"}'
    )
    review_path = work / "holdout" / "review-v0_2.fernet"
    review_path.write_bytes(review_token)

    # 3) manager acceptance + review aggregate（corpus hashes 取自真 v3 语料文件）
    ingest_document = json.loads(REAL_INPUTS["ingest_plan"].read_text(encoding="utf-8"))
    manager = build_manager_acceptance(
        annotation_sha=sha256_bytes(annotation_token),
        review_sha=sha256_bytes(review_token),
        schema_sha=bindings["schema_sha256"],
        contract_sha=bindings["scenario_contract_sha256"],
    )
    review = build_review_aggregate(
        payload=payload,
        bindings=bindings,
        annotation_sha=sha256_bytes(annotation_token),
        review_ciphertext_path=review_path,
        review_sha=sha256_bytes(review_token),
        ingest_sources=ingest_document["sources"],
    )
    manager_path = work / "custody" / "manager-acceptance.json"
    review_aggregate_path = work / "custody" / "review-aggregate.json"
    write_json(manager_path, manager)
    write_json(review_aggregate_path, review)

    # 4) 14 项 inputs 记录（私有路径全部在仓外）
    records: dict[str, dict[str, Any]] = {
        "holdout_manifest": record(sealed["manifest_path"], "holdout_manifest", kind="synthetic"),
        "annotation_ciphertext": record(annotation_path, "annotation_ciphertext", kind="synthetic"),
        "review_ciphertext": record(review_path, "review_ciphertext", kind="synthetic"),
        "scenario_key_file": record(key_file, "scenario_key_file", kind="synthetic"),
        "scenario_contract": record(
            REAL_INPUTS["scenario_contract"], "scenario_contract", kind="real"
        ),
        "ingest_plan": record(REAL_INPUTS["ingest_plan"], "ingest_plan", kind="real"),
        "source_map": record(REAL_INPUTS["source_map"], "source_map", kind="real"),
        "annotation_schema": record(
            REAL_INPUTS["annotation_schema"], "annotation_schema", kind="real"
        ),
        "manager_acceptance": record(manager_path, "manager_acceptance", kind="synthetic"),
        "review_aggregate": record(review_aggregate_path, "review_aggregate", kind="synthetic"),
        "lifecycle": record(Path(run_date.LIFECYCLE_PATH), "lifecycle", kind="real"),
        "v3_freeze": record(REAL_INPUTS["v3_freeze"], "v3_freeze", kind="real"),
        "pre_registration": record(
            REAL_INPUTS["pre_registration"], "pre_registration", kind="real"
        ),
        "mock_dryrun_summary": record(
            REAL_INPUTS["mock_dryrun_summary"], "mock_dryrun_summary", kind="real"
        ),
    }
    if set(records) != set(mod.V3_INPUT_NAMES):
        raise Blocked(
            "inputs_mismatch",
            where="prepare",
            missing=sorted(set(mod.V3_INPUT_NAMES) ^ set(records)),
            next_step="对齐 V3_INPUT_NAMES",
        )

    # 5) 真 v3 loader 复核（contract 身份由此产出，不猜）
    try:
        with mod.v2.applied_env(
            {
                "MKTKB_P2_HOLDOUT_ROOT": str(Path(str(records["holdout_manifest"]["path"])).parent),
                "MKTKB_P2_HOLDOUT_KEY_FILE": str(key_file),
                "MKTKB_PROJECT_TOTAL_LIMIT_CNY": str(mod.V3_PROJECT_TOTAL_LIMIT_CNY),
            }
        ):
            contract = contract_v3.load_v3_scenario_contract(
                dataset,
                annotation_path=annotation_path,
                key_file=key_file,
                review_path=review_path,
                manager_path=manager_path,
                review_aggregate_path=review_aggregate_path,
                scenario_path=REAL_INPUTS["scenario_contract"],
                ingest_path=REAL_INPUTS["ingest_plan"],
                source_map_path=REAL_INPUTS["source_map"],
                schema_path=REAL_INPUTS["annotation_schema"],
            )
    except Exception as exc:  # noqa: BLE001 - 固定码记录
        raise Blocked(
            "scenario_contract_invalid",
            where="prepare/load_v3_scenario_contract",
            missing="synthetic custody accepted by real v3 loader",
            next_step="按固定码修正 manager/review/annotation 绑定",
            detail=f"{type(exc).__name__}: {exc}",
        ) from None
    if sum(len(contract.subset(name).cases) for name in mod.v2.SCENARIO_ORDER) != 30:
        raise Blocked(
            "scenario_partition_invalid",
            where="prepare",
            missing="4 scenarios cover 30 cases",
            next_step="检查 annotation 的 scenario_id 分配",
        )
    # 契约复核：注解轴计数必须与 review aggregate 逐值一致。
    summary = annotation.public_summary()
    if dict(review["axis_counts"]) != {
        str(name): {str(state): int(count) for state, count in table.items()}
        for name, table in summary["axis_counts"].items()
    }:
        raise Blocked(
            "axis_counts_mismatch",
            where="prepare",
            missing="review.axis_counts == annotation summary",
            next_step="重算 review axis_counts",
        )

    # 6) 逐 run 材料
    code_version = str(mod.v2.code_digest())
    thresholds_approved = bool(mod.v2._thresholds_approved_from_config())
    runs: list[dict[str, Any]] = []
    for index, scenario in enumerate(mod.v2.SCENARIO_ORDER):
        runs.append(
            build_run_materials(
                mod=mod,
                dataset=dataset,
                contract=contract,
                records=records,
                work=work,
                key=key,
                code_version=code_version,
                index=index,
                scenario=scenario,
                run_dates=run_dates,
                thresholds_approved=thresholds_approved,
            )
        )

    # 7) binding 文档（每 run 一份；真实摘要、逐项自检）
    binding_paths: list[Path] = []
    for run in runs:
        document = build_binding_document(
            mod=mod,
            dataset=dataset,
            records=records,
            run=run,
            code_version=code_version,
            axis_counts=summary["axis_counts"],
        )
        mod._validate_binding_document(document)
        binding_path = work / "bindings" / f"run{run['run_index']}-{run['scenario_id']}.binding.json"
        write_json(binding_path, document)
        binding_paths.append(binding_path)
        run["binding_path"] = binding_path
        run["binding_sha256"] = sha256_file(binding_path)

    materials = {
        "synthetic_root": str(work),
        "files": [
            *sealed["files"],
            record(annotation_path, "annotation_ciphertext", kind="synthetic"),
            record(review_path, "review_ciphertext", kind="synthetic"),
            record(key_file, "scenario_key_file", kind="synthetic"),
            record(manager_path, "manager_acceptance", kind="synthetic"),
            record(review_aggregate_path, "review_aggregate", kind="synthetic"),
            *[
                {
                    "role": f"plan/run{run['run_index']}-{run['scenario_id']}",
                    "kind": "synthetic",
                    "path": str(run["plan_path"]),
                    "bytes": run["plan_path"].stat().st_size,
                    "sha256": sha256_file(run["plan_path"]),
                }
                for run in runs
            ],
            *[
                {
                    "role": f"case_plan/run{run['run_index']}-{run['scenario_id']}",
                    "kind": "synthetic",
                    "path": str(run["case_plan_path"]),
                    "bytes": run["case_plan_path"].stat().st_size,
                    "sha256": sha256_file(run["case_plan_path"]),
                }
                for run in runs
            ],
            *[
                {
                    "role": f"run_receipt/run{run['run_index']}-{run['scenario_id']}",
                    "kind": "synthetic",
                    "path": str(run["receipt_path"]),
                    "bytes": run["receipt_path"].stat().st_size,
                    "sha256": sha256_file(run["receipt_path"]),
                }
                for run in runs
            ],
            *[
                {
                    "role": f"binding/run{run['run_index']}-{run['scenario_id']}",
                    "kind": "synthetic",
                    "path": str(run["binding_path"]),
                    "bytes": run["binding_path"].stat().st_size,
                    "sha256": sha256_file(run["binding_path"]),
                }
                for run in runs
            ],
            *[
                {
                    "role": f"evidence/{run['scenario_id']}/{item['file']}",
                    "kind": "synthetic",
                    "path": str(run["evidence_dir"] / item["file"]),
                    "bytes": item["bytes"],
                    "sha256": item["sha256"],
                    "turn_index": item["turn_index"],
                }
                for run in runs
                for item in run["evidence_files"]
            ],
        ],
        "real_truth_inputs": [
            {
                "role": name,
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for name, path in {
                **REAL_INPUTS,
                "lifecycle": Path(run_date.LIFECYCLE_PATH),
            }.items()
        ],
        "evidence_turn_counts": {run["scenario_id"]: len(run["evidence_files"]) for run in runs},
    }
    return {
        "key_file": key_file,
        "runs": runs,
        "binding_paths": binding_paths,
        "materials": materials,
        "dataset": {
            "cases": len(dataset.cases),
            "turns": sum(len(mod.case_questions(case)) for case in dataset.cases),
            "manifest_sha256": dataset.manifest.manifest_sha256,
            "strata": dict(dataset.manifest.strata),
            "anchor_business_date": str(dataset.manifest.business_date),
        },
        "annotation_summary": annotation.public_summary(),
        "review_axis_counts": dict(review["axis_counts"]),
        "contract_bindings": {name: dict(contract.binding(name)) for name in mod.v2.SCENARIO_ORDER},
        "code_version": code_version,
        "thresholds_approved": thresholds_approved,
    }


def blocked_payload(blocked: Blocked, *, work: Path | None) -> dict[str, Any]:
    return {
        "schema": "p2-fu2-e2e-derive/v0.1",
        "kind": "offline-synthetic-end-to-end-derive",
        "status": "BLOCKED",
        "refusal_code": blocked.code,
        "where": blocked.where,
        "missing": blocked.missing,
        "next_step": blocked.next_step,
        "detail": blocked.detail,
        "work_dir": None if work is None else str(work),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FU-2 端到端离线派生复核（纯合成材料）")
    parser.add_argument("--work-dir", default=None, help="合成材料根（默认系统临时目录下新目录）")
    parser.add_argument("--out-root", default=None, help="两次运行的输出根（默认系统临时目录）")
    parser.add_argument("--result", default=str(DEFAULT_RESULT), help="结果 JSON 路径")
    parser.add_argument(
        "--cards-copy", default=str(DEFAULT_CARD_COPY), help="把卡/证明复制到的仓库目录"
    )
    args = parser.parse_args(argv)

    import_backend()
    result_path = Path(args.result)
    cards_copy = Path(args.cards_copy)
    work: Path | None = None
    try:
        work = (
            Path(args.work_dir).resolve()
            if args.work_dir
            else Path(tempfile.mkdtemp(prefix="fu2-e2e-"))
        )
        work.mkdir(parents=True, exist_ok=True)
        mod = load_tool_module()
        prepared = prepare(work, mod=mod)

        out_root = (
            Path(args.out_root).resolve()
            if args.out_root
            else Path(tempfile.mkdtemp(prefix="fu2-e2e-out-"))
        )
        out_root.mkdir(parents=True, exist_ok=True)
        out_a = out_root / "out1"
        out_b = out_root / "out2"
        out_c = out_root / "out3"
        for path in (out_a, out_b, out_c):
            if path.exists() and any(path.iterdir()):
                raise Blocked(
                    "output_dir_not_empty",
                    where="main/out_root",
                    missing=f"fresh {path}",
                    next_step="换一个空的 out-root",
                )
        runs = prepared["runs"]
        common = {
            "bindings": [run["binding_path"] for run in runs],
            "case_plans": [run["case_plan_path"] for run in runs],
            "evidence_dirs": [run["evidence_dir"] for run in runs],
            "receipts": [run["receipt_path"] for run in runs],
            "key_file": prepared["key_file"],
        }
        run_a = run_cli(label="run1", out_dir=out_a, **common)
        run_b = run_cli(label="run2", out_dir=out_b, **common)
        run_c = run_cli(label="run3", out_dir=out_c, **common)
        run_same = run_cli(label="same_dir_rerun", out_dir=out_a, **common)
        if run_a["exit_code"] != EXIT_OK or not run_a["payload_ok"]:
            raise Blocked(
                "derive_cards_refused",
                where=f"run1 exit={run_a['exit_code']}",
                missing="ok=true from derive-cards",
                next_step="按 CLI 固定 error_code 修正合成材料/边界",
                detail=json.dumps(
                    None
                    if run_a["payload"] is None
                    else {
                        "error_code": run_a["payload"].get("error_code"),
                        "detail": run_a["payload"].get("detail"),
                    },
                    ensure_ascii=False,
                ),
            )
        if run_b["exit_code"] != EXIT_OK or not run_b["payload_ok"]:
            raise Blocked(
                "derive_cards_second_run_refused",
                where=f"run2 exit={run_b['exit_code']}",
                missing="ok=true from derive-cards",
                next_step="检查两次运行之间材料是否被改动",
                detail=json.dumps(
                    None
                    if run_b["payload"] is None
                    else {
                        "error_code": run_b["payload"].get("error_code"),
                        "detail": run_b["payload"].get("detail"),
                    },
                    ensure_ascii=False,
                ),
            )
        if run_same["exit_code"] == EXIT_OK:
            raise Blocked(
                "same_dir_rerun_unexpectedly_succeeded",
                where="same_dir_rerun",
                missing="documented no-overwrite refusal",
                next_step="检查 derive-cards 的输出保护",
            )
        if run_c["exit_code"] != EXIT_OK or not run_c["payload_ok"]:
            raise Blocked(
                "derive_cards_third_run_refused",
                where=f"run3 exit={run_c['exit_code']}",
                missing="ok=true from derive-cards",
                next_step="检查第三次运行的材料/输出目录",
                detail=json.dumps(
                    None
                    if run_c["payload"] is None
                    else {
                        "error_code": run_c["payload"].get("error_code"),
                        "detail": run_c["payload"].get("detail"),
                    },
                    ensure_ascii=False,
                ),
            )

        network = {
            "external": list((run_a["payload"].get("network") or {}).get("external") or []),
            "local": list((run_a["payload"].get("network") or {}).get("local") or []),
        }
        network_b = {
            "external": list((run_b["payload"].get("network") or {}).get("external") or []),
            "local": list((run_b["payload"].get("network") or {}).get("local") or []),
        }
        run_ids = {run["scenario_id"]: run["run_id"] for run in runs}
        config_hashes = {run["scenario_id"]: run["config_sha256"] for run in runs}
        cards = validate_cards(out_dir=out_a, run_ids=run_ids, config_hashes=config_hashes)
        cards_b = validate_cards(out_dir=out_b, run_ids=run_ids, config_hashes=config_hashes)
        cards_c = validate_cards(out_dir=out_c, run_ids=run_ids, config_hashes=config_hashes)
        if len(cards) != 4:
            raise Blocked(
                "card_count_unexpected",
                where="validate_cards",
                missing="4 scenario cards",
                next_step="检查 --compose never 与 run 数",
            )
        if not all(item["official_validator"]["ok"] for item in cards_b):
            raise Blocked(
                "official_validation_failed_out2",
                where="validate_cards/run2",
                missing="all out2 cards pass official validator",
                next_step="按 validator 固定码修正",
            )
        if not all(item["official_validator"]["ok"] for item in cards_c):
            raise Blocked(
                "official_validation_failed_out3",
                where="validate_cards/run3",
                missing="all out3 cards pass official validator",
                next_step="按 validator 固定码修正",
            )
        comparison = compare_runs(out_a, out_b)
        comparison_three = compare_runs(out_a, out_c)
        if comparison["missing_files"]:
            raise Blocked(
                "determinism_file_set_mismatch",
                where="compare_runs",
                missing=",".join(comparison["missing_files"]),
                next_step="检查两次输出",
            )
        if not comparison["cards_byte_identical"]:
            raise Blocked(
                "determinism_cards_differ",
                where="compare_runs",
                missing="byte-identical cards",
                next_step="定位非确定性来源",
            )
        if comparison_three["missing_files"] or not comparison_three["cards_byte_identical"]:
            raise Blocked(
                "determinism_cards_differ_third_dir",
                where="compare_runs/out3",
                missing="byte-identical cards in third out dir",
                next_step="定位非确定性来源",
            )

        # 复制卡/证明到仓库证据目录（同名覆盖：每次脚本都会生成新的合成材料，
        # 旧一轮的卡摘要随之变化；这 8 个文件名由本脚本独占管理）。
        copied: list[dict[str, Any]] = []
        cards_copy.mkdir(parents=True, exist_ok=True)
        for item in cards:
            name = Path(item["file"]).name
            target = cards_copy / item["file"]
            overwrote = target.exists()
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item["path"], target)
            proof_src = Path(item["proof"]["path"])
            proof_target = cards_copy / item["proof"]["file"]
            proof_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(proof_src, proof_target)
            copied.append(
                {
                    "card": item["file"],
                    "card_sha256": item["sha256"],
                    "proof": item["proof"]["file"],
                    "proof_sha256": item["proof"]["sha256"],
                    "overwrote_existing": bool(overwrote),
                }
            )

        proof_checks = all(
            item["proof"]["card_sha256_matches"] and item["proof"]["card_summary_matches"]
            for item in cards
        )
        validator_ok = all(item["official_validator"]["ok"] for item in cards)
        if not proof_checks or not validator_ok:
            raise Blocked(
                "official_validation_failed",
                where="validate_cards",
                missing="all cards pass official validator + proof self-check",
                next_step="按 validator 固定码修正",
            )
        if network["external"] or network_b["external"]:
            raise Blocked(
                "network_external_attempt",
                where="run_cli",
                missing="zero external network attempts",
                next_step="检查环境/依赖是否触网",
            )

        payload = {
            "schema": "p2-fu2-e2e-derive/v0.1",
            "kind": "offline-synthetic-end-to-end-derive",
            "status": "PASS",
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "repo": {"root": str(ROOT), **git_identity()},
            "cli": {
                "tool": "tools/p2_h2_v3_controlled_execute.py",
                "subcommand": "derive-cards",
                "python": ".venv/Scripts/python.exe",
                "flags": ["-B", "-X", "utf8"],
                "argv_template": (
                    '.venv\\Scripts\\python.exe -B -X utf8 '
                    "tools\\p2_h2_v3_controlled_execute.py derive-cards "
                    "--binding <run0..3.binding.json> --run-index <0..3> "
                    "--case-plan <run0..3.case-plan.json> --evidence-dir <run0..3> "
                    "--run-receipt <run0..3.receipt.json> --evidence-key-file <v3.key> "
                    "--out-dir <out1|out2> --compose never"
                ),
            },
            "runs": [
                {
                    "label": run["label"],
                    "argv": run["argv"],
                    "cwd": run["cwd"],
                    "out_dir": run["out_dir"],
                    "exit_code": run["exit_code"],
                    "elapsed_seconds": run["elapsed_seconds"],
                    "ok": run["payload_ok"],
                    "stdout_sha256": run["stdout_sha256"],
                    "error_code": None
                    if run["payload"] is None
                    else run["payload"].get("error_code"),
                    "detail": None if run["payload"] is None else run["payload"].get("detail"),
                    "network": None
                    if run["payload"] is None
                    else run["payload"].get("network"),
                    "verification": None
                    if run["payload"] is None
                    else run["payload"].get("verification"),
                    "out_dir_token": None
                    if run["payload"] is None
                    else run["payload"].get("out_dir"),
                    "card_receipts": None
                    if run["payload"] is None
                    else run["payload"].get("cards"),
                    "composition": None
                    if run["payload"] is None
                    else run["payload"].get("composition"),
                }
                for run in (run_a, run_b, run_c, run_same)
            ],
            "network": {
                "run1_external": network["external"],
                "run1_local": network["local"],
                "run2_external": network_b["external"],
                "run2_local": network_b["local"],
                "external_total": len(network["external"]) + len(network_b["external"]),
            },
            "out_dir": str(out_a),
            "out_dir_run2": str(out_b),
            "out_dir_run3": str(out_c),
            "cards": [
                {key: value for key, value in item.items() if key not in {"path", "bytes"}}
                for item in cards
            ],
            "card_bytes": {item["file"]: item["bytes"] for item in cards},
            "official_validator": {
                "callable": (
                    "mktkb.evaluation.p2_hard_evidence.validate_hard_evidence_scorecard"
                ),
                "cards_checked": len(cards),
                "all_ok": validator_ok,
                "run1_results": [
                    {
                        "file": item["file"],
                        "ok": item["official_validator"]["ok"],
                        "error": item["official_validator"]["error"],
                    }
                    for item in cards
                ],
                "run2_all_ok": all(
                    item["official_validator"]["ok"] for item in cards_b
                ),
            },
            "proof_self_check": {
                "card_sha256_matches": all(
                    item["proof"]["card_sha256_matches"] for item in cards
                ),
                "card_summary_matches": all(
                    item["proof"]["card_summary_matches"] for item in cards
                ),
            },
            "determinism": {
                "same_inputs_runs": 3,
                "cards_byte_identical": comparison["cards_byte_identical"],
                "cards_byte_identical_third_dir": comparison_three["cards_byte_identical"],
                "proofs_byte_identical": comparison["proofs_byte_identical"],
                "proofs_byte_identical_third_dir": comparison_three["proofs_byte_identical"],
                "proof_differing_fields": comparison["proof_differing_fields"],
                "proofs_identical_after_output_dir_token_normalized": comparison[
                    "proofs_identical_after_output_dir_token_normalized"
                ],
                "proofs_identical_after_output_dir_token_normalized_third_dir": comparison_three[
                    "proofs_identical_after_output_dir_token_normalized"
                ],
                "per_file": comparison["files"],
                "per_file_third_dir": comparison_three["files"],
                "same_dir_rerun": {
                    "out_dir": run_same["out_dir"],
                    "exit_code": run_same["exit_code"],
                    "error_code": None
                    if run_same["payload"] is None
                    else run_same["payload"].get("error_code"),
                    "note": (
                        "derive-cards 对非空 out_dir 固定拒绝（output_not_empty），"
                        "因此“同目录重跑字节比对”以“换目录重跑”实现；"
                        "同目录重跑被拒本身是预期边界。"
                    ),
                },
            },
            "materials": {
                **prepared["materials"],
                "dataset": prepared["dataset"],
                "annotation_summary": prepared["annotation_summary"],
                "review_axis_counts": prepared["review_axis_counts"],
                "contract_bindings": prepared["contract_bindings"],
                "code_version": prepared["code_version"],
                "thresholds_approved": prepared["thresholds_approved"],
                "real_calls": 0,
                "private_material_read": False,
            },
            "evidence_copy": {"dir": str(cards_copy), "files": copied},
            "zero_call": {"new_requests": 0, "new_outbound": 0, "replayed": False},
            "limitations": [
                "合成证据的 completeness.status 固定为 incomplete：分类器据此把四轴记为 "
                "unknown/evidence_incomplete，卡上计 error/unverified（不伪造 pass）。",
                "卡上的 executed = passed + failed（已判定题数）；本复核每题 quality_status 为 "
                "error/not_executed，故 executed=0；proof.turns_executed=11..13 表示逐回合密文"
                "证据确实被解密、绑定校验并逐回合分类（与卡上“已判定题数”不是同一口径）。",
                "本复核只覆盖离线派生链路（derive-cards + 官方卡校验 + 确定性），"
                "不覆盖 live run/check-only/组合卡。",
                "所有合成密文/key/plan/case-plan/binding 均落在系统临时目录；"
                "仓库内只落结果 JSON 与复制出的卡/证明。",
            ],
        }
        write_json(result_path, payload)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "out_dir": str(out_a),
                    "cards": [item["file"] for item in cards],
                    "result": str(result_path),
                    "determinism": payload["determinism"]["cards_byte_identical"],
                    "external_network": payload["network"]["external_total"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK
    except Blocked as blocked:
        write_json(result_path, blocked_payload(blocked, work=work))
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "refusal_code": blocked.code,
                    "where": blocked.where,
                    "missing": blocked.missing,
                    "next_step": blocked.next_step,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_BLOCKED
    except Exception as exc:  # noqa: BLE001 - 未预期错误统一固定码，保留类型名
        blocked = Blocked(
            "internal_error",
            where="main",
            missing="unexpected failure",
            next_step="按 detail 定位",
            detail=f"{type(exc).__name__}: {exc}",
        )
        write_json(result_path, blocked_payload(blocked, work=work))
        print(
            json.dumps(
                {"status": "BLOCKED", "refusal_code": blocked.code, "detail": blocked.detail},
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
