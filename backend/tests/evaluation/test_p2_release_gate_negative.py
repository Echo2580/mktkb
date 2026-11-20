"""正式门禁的负例：缺证 / 错配 / 伪造 / 跨计划 / 版本冒充 / 绑定造假都必须被拒。"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
for _path in (_TESTS_DIR, _TESTS_DIR.parent.parent / "backend" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401
from evaluation.test_p2_release_gate_fixtures import (  # noqa: E402
    APPROVED_CONFIG,
    FROZEN_CONFIG,
    build_complete_inputs,
    build_h2,
    h2_input,
    write_inputs,
)
from mktkb.evaluation import p2_release_inputs  # noqa: E402
from mktkb.evaluation.p2_release_gate import evaluate_release_gate  # noqa: E402
from mktkb.evaluation.p2_release_model import (  # noqa: E402
    DECISION_BLOCKED,
    DECISION_PASS,
    DECISION_PENDING,
    R_APPLICABILITY_INVALID,
    R_BASELINE_UNREGISTERED,
    R_BINDING_ATTESTATION_INVALID,
    R_BINDING_PROOF_MISSING,
    R_CROSS_PLAN_MERGE,
    R_DIGEST_MISMATCH,
    R_EVIDENCE_MISSING,
    R_HARD_FAILURE,
    R_IDENTITY_MISMATCH,
    R_NOT_EXECUTED,
    R_REQUIRED_UNKNOWN,
    R_ROWS_INCOMPLETE,
    R_HARD_GATE_MIN_SAMPLE_UNMET,
    R_INPUTS_INVALID,
    R_STALE_CONFIG,
    R_VERSION_MISMATCH,
    file_sha256,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
ROOT_APPROVED = ROOT / "docs/evaluation/gate_v0_3_approved.json"


def _codes(result) -> set[str]:  # noqa: ANN001
    return {code for row in result.rows for code in row.reasons}


def _rewrite(tmp_path: Path, payload: dict, name: str) -> Path:
    return write_inputs(tmp_path / name, payload)


def _repin(payload: dict, section: str, key: str, path: Path) -> None:
    if section == "root":
        payload[key] = {"path": str(path), "sha256": file_sha256(path)}
    else:
        payload[section][key] = {"path": str(path), "sha256": file_sha256(path)}


def test_stale_frozen_template_config_is_rejected(tmp_path):
    path, payload = build_complete_inputs(tmp_path)
    payload["gate_config"] = {"path": str(FROZEN_CONFIG), "sha256": file_sha256(FROZEN_CONFIG)}
    result = evaluate_release_gate(_rewrite(tmp_path, payload, "stale.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_STALE_CONFIG in _codes(result)


def test_same_version_wrong_digest_is_rejected(tmp_path):
    path, payload = build_complete_inputs(tmp_path)
    payload["b0"]["admission_sha256"] = payload["b0"]["baseline_sha256"]
    result = evaluate_release_gate(_rewrite(tmp_path, payload, "digest.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_DIGEST_MISMATCH in _codes(result)


def test_fake_b0_registry_is_rejected(tmp_path):
    path, payload = build_complete_inputs(tmp_path)
    fake = tmp_path / "fake-registry" / "7981d4afc2d1"
    fake.mkdir(parents=True)
    for name in ("baseline.json", "b0-admission.json", "b0-approval-receipt.json"):
        shutil.copy2(Path(payload["b0"]["baseline_sha256"] and
                          p2_release_inputs.B0_REGISTRY_ROOT / "7981d4afc2d1" / name), fake / name)
    payload["b0"]["baseline_root"] = str(fake.parent)
    for key, name in (("baseline_sha256", "baseline.json"),
                      ("admission_sha256", "b0-admission.json"),
                      ("approval_sha256", "b0-approval-receipt.json")):
        payload["b0"][key] = file_sha256(fake / name)
    result = evaluate_release_gate(_rewrite(tmp_path, payload, "fake-b0.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_BASELINE_UNREGISTERED in _codes(result)


def test_fake_registry_at_canonical_root_still_rejected_by_pinned_digest(tmp_path, monkeypatch):
    path, payload = build_complete_inputs(tmp_path)
    fake_root = tmp_path / "pinned" / "7981d4afc2d1"
    fake_root.mkdir(parents=True)
    source = p2_release_inputs.B0_REGISTRY_ROOT / "7981d4afc2d1"
    for name in ("baseline.json", "b0-admission.json", "b0-approval-receipt.json"):
        raw = json.loads((source / name).read_text(encoding="utf-8"))
        raw["synthetic_marker"] = "fake"
        (fake_root / name).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    payload["b0"]["baseline_root"] = str(fake_root.parent)
    for key, name in (("baseline_sha256", "baseline.json"),
                      ("admission_sha256", "b0-admission.json"),
                      ("approval_sha256", "b0-approval-receipt.json")):
        payload["b0"][key] = file_sha256(fake_root / name)
    monkeypatch.setattr(p2_release_inputs, "B0_REGISTRY_ROOT", fake_root.parent)
    result = evaluate_release_gate(_rewrite(tmp_path, payload, "pinned.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_DIGEST_MISMATCH in _codes(result)


def test_candidate_pipeline_mismatch_is_rejected(tmp_path):
    path, payload = build_complete_inputs(tmp_path)
    payload["candidate_pipeline"]["pipeline_source_sha256"] = "0" * 64
    result = evaluate_release_gate(_rewrite(tmp_path, payload, "pipeline.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_VERSION_MISMATCH in _codes(result)


def test_cross_plan_merged_run_rows_are_rejected(tmp_path):
    path, _ = build_complete_inputs(tmp_path / "keep")
    merged_path, _ = build_complete_inputs(tmp_path / "merged",
                                           public_kwargs={"mixed_rows": True})
    result = evaluate_release_gate(merged_path)
    assert result.decision == DECISION_BLOCKED
    assert R_CROSS_PLAN_MERGE in _codes(result)


def test_missing_coverage_case_is_rejected(tmp_path):
    path, payload = build_complete_inputs(tmp_path)
    selection_path = Path(payload["public"]["selection"]["path"])
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    selection["assignments"] = [item for item in selection["assignments"]
                                if item["case_id"] != "N08"]
    selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    _repin(payload, "public", "selection", selection_path)
    result = evaluate_release_gate(_rewrite(tmp_path, payload, "coverage.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_EVIDENCE_MISSING in _codes(result)


def test_not_executed_case_is_rejected(tmp_path):
    path, _ = build_complete_inputs(tmp_path, public_kwargs={"not_executed": ("N05",)})
    result = evaluate_release_gate(path)
    assert result.decision == DECISION_BLOCKED
    assert R_NOT_EXECUTED in _codes(result)


def test_h2_v01_card_masquerading_as_v02_is_rejected(tmp_path):
    path, _ = build_complete_inputs(tmp_path, h2_kwargs={"card_schema": "mktkb.p2.scoring.v0.1"})
    result = evaluate_release_gate(path)
    assert result.decision == DECISION_BLOCKED
    assert R_VERSION_MISMATCH in _codes(result)


def test_h2_required_axis_unknown_is_rejected(tmp_path):
    axes = {
        "safety": {"required": 8, "not_applicable": 22, "unknown": 0},
        "cross_user": {"required": 30, "not_applicable": 0, "unknown": 0},
        "cross_entity": {"required": 10, "not_applicable": 20, "unknown": 0},
        "stale_source": {"required": 1, "not_applicable": 28, "unknown": 1},
    }
    path, _ = build_complete_inputs(tmp_path, h2_kwargs={"annotation_axes": axes})
    result = evaluate_release_gate(path)
    assert result.decision == DECISION_BLOCKED
    assert R_REQUIRED_UNKNOWN in _codes(result)


def test_h2_real_hard_failure_is_rejected(tmp_path):
    path, _ = build_complete_inputs(tmp_path, h2_kwargs={"hard_failure": True})
    result = evaluate_release_gate(path)
    assert result.decision == DECISION_BLOCKED
    assert R_HARD_FAILURE in _codes(result)


def test_h2_card_digest_mismatch_is_rejected(tmp_path):
    path, payload = build_complete_inputs(tmp_path)
    card = Path(payload["h2"]["cards"][0]["path"])
    card.write_bytes(card.read_bytes() + b"\n")
    result = evaluate_release_gate(_rewrite(tmp_path, payload, "card-digest.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_DIGEST_MISMATCH in _codes(result)


def test_h2_source_proof_wrong_batch_binding_is_rejected(tmp_path):
    path, payload = build_complete_inputs(tmp_path)
    proof_path = Path(payload["h2"]["source_proof"]["path"])
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["batch_binding"]["manifest_sha256"] = "0" * 64
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    _repin(payload, "h2", "source_proof", proof_path)
    result = evaluate_release_gate(_rewrite(tmp_path, payload, "batch.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_IDENTITY_MISMATCH in _codes(result)


# --------------------------------------------------------------------------- #
# 历史绑定适用性证明的负例
# --------------------------------------------------------------------------- #


@pytest.fixture
def binding_case(tmp_path):
    path, payload = build_complete_inputs(tmp_path, public_kwargs={"with_binding": True})
    proof_path = Path(payload["public"]["runs"][0]["binding_proof"]["path"])
    return path, payload, proof_path


def _binding_variant(tmp_path: Path, payload: dict, proof: dict, name: str) -> Path:
    target = tmp_path / name
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    payload["public"]["runs"][0]["binding_proof"] = {"path": str(target),
                                                    "sha256": file_sha256(target)}
    return write_inputs(tmp_path / f"{name}.inputs.json", payload)


def test_forged_attested_revision_is_rejected(tmp_path, binding_case):
    path, payload, proof_path = binding_case
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["attested_index_revision"] = proof["attested_index_revision"] + 3
    result = evaluate_release_gate(_binding_variant(tmp_path, payload, proof, "forged-attested.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_BINDING_ATTESTATION_INVALID in _codes(result)


def test_proof_digest_mismatch_is_rejected(tmp_path, binding_case):
    path, payload, proof_path = binding_case
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["attestation"]["rag_source"]["db_sha256"] = "0" * 64
    result = evaluate_release_gate(_binding_variant(tmp_path, payload, proof, "rag-hash.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_BINDING_ATTESTATION_INVALID in _codes(result)


def test_binding_proof_from_another_run_is_rejected(tmp_path, binding_case):
    path, payload, proof_path = binding_case
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["run_id"] = "synthetic-public-c"
    result = evaluate_release_gate(_binding_variant(tmp_path, payload, proof, "cross-run.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_IDENTITY_MISMATCH in _codes(result)


def test_no_correction_claimed_is_rejected(tmp_path, binding_case):
    path, payload, proof_path = binding_case
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["attested_index_revision"] = proof["recorded_index_revision"]
    result = evaluate_release_gate(_binding_variant(tmp_path, payload, proof, "no-correction.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_VERSION_MISMATCH in _codes(result)


def test_missing_original_mechanical_result_is_rejected(tmp_path, binding_case):
    path, payload, proof_path = binding_case
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["gate_replay"]["original_binding_failures"] = []
    result = evaluate_release_gate(_binding_variant(tmp_path, payload, proof, "no-original.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_EVIDENCE_MISSING in _codes(result)


def test_missing_binding_proof_is_rejected(tmp_path, binding_case):
    path, payload, _ = binding_case
    del payload["public"]["runs"][0]["binding_proof"]
    result = evaluate_release_gate(_rewrite(tmp_path, payload, "no-proof.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_BINDING_PROOF_MISSING in _codes(result)


def test_zero_rewrite_claim_without_legal_zero_is_rejected(tmp_path, binding_case):
    """T4-R1 缺陷 2 负例：伪造"零改写"（库里仍有非 attested 行）→ 必须拒。"""
    path, payload, proof_path = binding_case
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["gate_replay"]["rewritten_trace_rows"] >= 1
    proof["gate_replay"]["rewritten_trace_rows"] = 0
    proof["gate_replay"]["trace_rows_not_at_attested"] = 0
    proof["gate_replay"]["post_update_not_at_attested"] = 0
    result = evaluate_release_gate(_binding_variant(tmp_path, payload, proof, "fake-zero.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_BINDING_ATTESTATION_INVALID in _codes(result)


def test_missing_binding_row_is_caught_by_completeness_invariant(tmp_path, monkeypatch):
    """T4-R1 缺陷 1 防回归：若某 run 的 binding 行被丢弃，总门必须阻断而非 pending。"""
    from mktkb.evaluation import p2_release_binding, p2_release_gate

    path, _ = build_complete_inputs(tmp_path, public_kwargs={"with_binding": True})
    original = p2_release_binding.assess_binding

    def drop_binding(binding, **kwargs):  # noqa: ANN001
        row, replay = original(binding, **kwargs)
        return None, None

    monkeypatch.setattr(p2_release_binding, "assess_binding", drop_binding)
    monkeypatch.setattr(p2_release_gate, "assess_binding", drop_binding)
    result = p2_release_gate.evaluate_release_gate(path)
    assert result.decision == DECISION_BLOCKED
    assert R_ROWS_INCOMPLETE in _codes(result)
    assert any(row.row_id.startswith("rows.completeness.") for row in result.rows)


def test_gate_never_passes_when_only_correction_is_reported(tmp_path):
    """即使修正视图通过，只要缺原始机械结果就拒（禁止只报修正后）。"""
    path, payload = build_complete_inputs(tmp_path, public_kwargs={"with_binding": True})
    proof_path = Path(payload["public"]["runs"][0]["binding_proof"]["path"])
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["gate_replay"].pop("original_binding_failures")
    target = tmp_path / "trimmed.json"
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    payload["public"]["runs"][0]["binding_proof"] = {"path": str(target),
                                                    "sha256": file_sha256(target)}
    result = evaluate_release_gate(_rewrite(tmp_path, payload, "trimmed-inputs.json"))
    assert result.decision == DECISION_BLOCKED
    assert result.decision != "pass"


def test_two_missing_binding_rows_produce_two_distinct_blocked_rows(tmp_path, monkeypatch):
    """T4-R1 复验 D4：多 run 同时缺 binding 行时，必须产出两条不重复的阻断行。"""
    from mktkb.evaluation import p2_release_binding, p2_release_gate

    path, _ = build_complete_inputs(tmp_path, public_kwargs={"with_binding": True})
    original = p2_release_binding.assess_binding

    def drop_binding(binding, **kwargs):  # noqa: ANN001
        original(binding, **kwargs)
        return None, None

    monkeypatch.setattr(p2_release_binding, "assess_binding", drop_binding)
    monkeypatch.setattr(p2_release_gate, "assess_binding", drop_binding)
    result = p2_release_gate.evaluate_release_gate(path)
    assert result.decision == DECISION_BLOCKED
    completeness = [row for row in result.rows if row.row_id.startswith("rows.completeness.")]
    # 三个 run（N/C/U）同时缺 binding 行 -> 三条独立行，不得共用一个 row_id
    assert len(completeness) == 3, [row.row_id for row in completeness]
    assert len({row.row_id for row in completeness}) == 3
    assert all(row.reasons == (R_ROWS_INCOMPLETE,) for row in completeness)
    assert {row.detail["evidence"]["run_id"] for row in completeness} == {
        "synthetic-public-n", "synthetic-public-c", "synthetic-public-u"}


# --------------------------------------------------------------------------- #
# D-011（主人授权）：min-sample 覆盖按 suite 计划题数计
# --------------------------------------------------------------------------- #


def test_d011_suite_planned_below_min_sample_keeps_u_pending(tmp_path, monkeypatch):
    """负例 1：把 update_delete 的 p2_standards.total 改成 9（< 10）→ 覆盖不成立，仍 pending。"""
    import dataclasses

    from mktkb.evaluation import p2_release_inputs, p2_release_public, p2_release_gate
    from mktkb.evaluation.p2_b0 import load_approved_b0_config

    real_config = load_approved_b0_config(ROOT_APPROVED)
    standards = real_config.standards
    forged_standards = dataclasses.replace(standards, update_delete_total=9)
    forged_config = dataclasses.replace(real_config, standards=forged_standards)
    monkeypatch.setattr(p2_release_inputs, "load_approved_b0_config", lambda path: forged_config)

    path, _ = build_complete_inputs(tmp_path, run_level_cases=("U01",), local_controls=True)
    result = evaluate_release_gate(path)
    assert result.decision == DECISION_PENDING
    coverage = p2_release_public.min_sample_coverage(
        standards=forged_standards, gate_config=forged_config, suite="update_delete",
        run_level_evaluated=1,
    )
    assert coverage["covered"] is False and coverage["suite_planned_cases"] == 9
    rows = {row.row_id: row for row in result.rows}
    assert rows["u.hard_gates"].decision == DECISION_PENDING
    assert rows["hard_gate_min_sample.unmet"].reasons == (R_HARD_GATE_MIN_SAMPLE_UNMET,)


def test_d011_forged_planned_cases_cannot_fake_coverage(tmp_path):
    """负例 2：不能靠调用方自报 run 级/计划数伪造覆盖；计划数只认 p2_standards。"""
    import dataclasses

    from mktkb.evaluation.p2_b0 import load_approved_b0_config
    from mktkb.evaluation.p2_release_public import min_sample_coverage

    config = load_approved_b0_config(ROOT_APPROVED)
    real = min_sample_coverage(standards=config.standards, gate_config=config,
                               suite="update_delete", run_level_evaluated=1)
    assert real["covered"] is True and real["suite_planned_cases"] == 10
    # 自报 run 级评估数再大也不改变"计划题数"这一事实
    inflated = min_sample_coverage(standards=config.standards, gate_config=config,
                                   suite="update_delete", run_level_evaluated=99)
    assert inflated["suite_planned_cases"] == 10 and inflated["covered"] is True
    # 计划数被改成 9 时，即使自报 10 也判不覆盖
    forged_standards = dataclasses.replace(config.standards, update_delete_total=9)
    forged = min_sample_coverage(standards=forged_standards, gate_config=config,
                                 suite="update_delete", run_level_evaluated=10)
    assert forged["covered"] is False
    # 输入契约不接受 suite_planned_cases 之类的自报字段
    path, payload = build_complete_inputs(tmp_path)
    payload["hard_gate_min_sample"] = {"suite_planned_cases": 10}
    result = evaluate_release_gate(_rewrite(tmp_path, payload, "forged-planned.json"))
    assert result.decision == DECISION_BLOCKED
    assert R_INPUTS_INVALID in _codes(result)


def test_d011_run_level_gate_failure_is_not_masked(tmp_path):
    """负例 3：run 级子集里注入引用失败 → u.hard_gates 必须 fail/blocked。"""
    path, _ = build_complete_inputs(
        tmp_path, run_level_cases=("U01",), local_controls=True,
        u_kwargs={"failing_citations": True},
    )
    result = evaluate_release_gate(path)
    rows = {row.row_id: row for row in result.rows}
    assert result.decision != DECISION_PASS
    assert rows["u.hard_gates"].decision == DECISION_BLOCKED
    assert rows["hard_gates"].decision == DECISION_BLOCKED


def test_t4r3_non_disclosure_unknown_blocks_both_u_and_aggregate(tmp_path, monkeypatch):
    """T4-R3：汇总行必须与来源行一致——注入非披露 unknown 后两行都必须 blocked。"""
    import dataclasses

    from mktkb.evaluation import p2_release_gate, p2_release_public

    path, _ = build_complete_inputs(tmp_path, run_level_cases=("U01",), local_controls=True)
    original = p2_release_public.collect_suite

    def patched(suite, *args, **kwargs):  # noqa: ANN001
        evidence = original(suite, *args, **kwargs)
        if suite != "update_delete":
            return evidence
        proof = dict(evidence.gate_proof)
        proof["unknowns"] = list(proof.get("unknowns") or ()) + [{
            "gate_id": "gold", "case_id": "U01", "check_id": "gold_missing",
            "reason": "注入：非 min_sample 披露类 unknown",
        }]
        return dataclasses.replace(evidence, gate_proof=proof)

    monkeypatch.setattr(p2_release_gate, "collect_suite", patched)
    result = evaluate_release_gate(path)
    rows = {row.row_id: row for row in result.rows}
    assert rows["u.hard_gates"].decision == DECISION_BLOCKED
    assert rows["u.hard_gates"].reasons == (R_REQUIRED_UNKNOWN,)
    assert rows["hard_gates"].decision == DECISION_BLOCKED
    assert rows["hard_gates"].reasons == (R_REQUIRED_UNKNOWN,)
    assert result.decision == DECISION_BLOCKED
