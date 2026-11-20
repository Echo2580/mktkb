"""最终装配：任务 3 v3 清单的四档承接、两行 tally、min_sample 未满足固定行。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
for _path in (_TESTS_DIR, _TESTS_DIR.parent.parent / "backend" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from acceptance.support.netguard import t09_network_guard  # noqa: E402,F401
from evaluation.test_p2_release_gate_fixtures import build_complete_inputs  # noqa: E402
from mktkb.evaluation.p2_release_gate import evaluate_release_gate  # noqa: E402
from mktkb.evaluation.p2_release_model import (  # noqa: E402
    DECISION_BLOCKED,
    DECISION_OBSERVED,
    DECISION_PASS,
    DECISION_PENDING,
    R_BINDING_ATTESTATION_INVALID,
    R_BINDING_PROOF_MISSING,
    R_IDENTITY_MISMATCH,
    R_SAMPLE_BELOW_MIN,
    file_sha256,
)

pytestmark = pytest.mark.usefixtures("t09_network_guard")

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "docs/reports/OBS-EVAL/P2/CROSS-SCENARIO-GATE/scripts/wire_real_ncu.py"
RAG_ROOT = Path(r"D:\mktkb-p2-run\t207")
V3_MANIFEST_SHA = "0129cd2ba6abf625c61afaaf958ae2e30e675977ad3045eb381d568ab4ab3fab"
V3_REPORT_SHA = "52c33b1475eec177c017f5855afb6529be4afc89137ae492330ea91f05ca5cd3"
V3_SUMS_SHA = "746fa6633186356c0795583d8dccb84bb0414c94d39d7a5cb4a65f8dbac55b01"


def _rows(result):  # noqa: ANN001
    return {row.row_id: row for row in result.rows}


def test_d011_disclosure_row_present_and_masking_impossible(tmp_path):
    """D-011：min-sample 按 suite 计划题数（10>=10）覆盖；run 级子集只披露。"""
    path, _ = build_complete_inputs(tmp_path, run_level_cases=("U01",), local_controls=True)
    result = evaluate_release_gate(path)
    rows = _rows(result)
    disclosure = rows["hard_gate_min_sample.run_level_subset"]
    assert disclosure.decision == DECISION_OBSERVED
    assert disclosure.detail["suite"] == "update_delete"
    assert disclosure.detail["suite_planned_cases"] == 10
    assert disclosure.detail["required_min_sample"] == 10
    assert disclosure.detail["run_level_evaluated"] == 1
    assert disclosure.detail["scored_count"] == 1
    assert disclosure.detail["basis"] == "suite_planned_cases"
    assert "1 条 run 级样本" in disclosure.detail["disclosed_limit"]
    assert rows["u.hard_gates"].decision == DECISION_PASS
    assert rows["hard_gates"].decision == DECISION_PASS
    assert "hard_gate_min_sample.unmet" not in rows
    assert result.decision == DECISION_PASS
    assert result.to_dict()["release_allowed"] is False


@pytest.mark.skipif(not (RAG_ROOT / "R2").is_dir(),
                    reason="需要本机历史 run 的 rag/trace 库（仓外）")
def test_real_v3_manifest_four_tiers_and_two_tallies(tmp_path, monkeypatch):
    """真实 v3 清单：四档原样承接 + 两行 tally + SHA256SUMS 全命中 + U01 非 FAIL。"""
    out = tmp_path / "real-ncu.json"
    monkeypatch.setenv("P2_RELEASE_NCU_OUT", str(out))
    spec = importlib.util.spec_from_file_location("wire_real_ncu", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.main() == 0  # D-011 后：技术门 pass
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["decision"] == DECISION_PASS
    assert payload["release_allowed"] is False
    assert payload["release_authority"] == "owner"
    assert payload["owner_release_decision"] == "not_decided"
    assert payload["evidence_manifest"]["manifest_sha256"] == V3_MANIFEST_SHA
    assert payload["evidence_manifest"]["report_sha256"] == V3_REPORT_SHA
    assert payload["evidence_manifest"]["sha256sums_sha256"] == V3_SUMS_SHA
    rows = {row["row_id"]: row for row in payload["rows"]}
    manifest_row = rows["evidence_manifest"]
    assert manifest_row["decision"] == DECISION_PASS
    assert manifest_row["detail"]["sha256sums"] == {
        "sha256": V3_SUMS_SHA, "verified": 17, "mismatch": 0, "missing": 0}
    assert manifest_row["detail"]["tiers"] == {
        "ADOPTED": {"N": 7, "C": 2, "U": 9},
        "ADOPTED_WITH_BINDING_PROOF": {"N": 1, "C": 4, "U": 1},
        "FAIL": {"N": 0, "C": 0, "U": 0},
        "UNKNOWN": {"N": 0, "C": 0, "U": 0},
    }
    assert rows["tallies.unconditional"]["decision"] == DECISION_OBSERVED
    assert rows["tallies.unconditional"]["detail"]["counts"] == {"N": 7, "C": 2, "U": 9}
    assert rows["tallies.formal"]["decision"] == DECISION_PASS
    assert rows["tallies.formal"]["detail"]["counts"] == {"N": 8, "C": 6, "U": 10}
    assert rows["tallies.formal"]["detail"]["with_binding_proof"] == {"N": 1, "C": 4, "U": 1}
    disclosure = rows["hard_gate_min_sample.run_level_subset"]["detail"]
    assert disclosure["basis"] == "suite_planned_cases"
    assert disclosure["suite_planned_cases"] == 10 and disclosure["required_min_sample"] == 10
    assert disclosure["run_level_evaluated"] == 1
    assert "hard_gate_min_sample.unmet" not in rows
    # U01 不再是 FAIL；引用口径按 D-004 记 observed
    assert rows["u"]["detail"]["real"]["case_ids"] == ["U01"]
    assert rows["u.citation"]["decision"] == DECISION_OBSERVED
    assert rows["u.hard_gates"]["decision"] == DECISION_PASS


def _load_script_module():
    spec = importlib.util.spec_from_file_location("wire_real_ncu", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write(payload: dict, path: Path) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.mark.skipif(not (RAG_ROOT / "R2").is_dir(),
                    reason="需要本机历史 run 的 rag/trace 库（仓外）")
def test_u01_binding_proof_forgery_delete_and_cross_run_are_rejected(tmp_path):
    """T4-R1 缺陷 3：U01 的 binding_proof 有实际约束力（伪造/删除/跨 run 都改变输出）。"""
    module = _load_script_module()
    base_inputs, base_payload = module.build_inputs(tmp_path / "base")
    baseline = evaluate_release_gate(base_inputs)
    assert baseline.decision == DECISION_PASS  # D-011 后：技术门 pass、0 blocked

    # 1) 伪造内容：改 attested 值
    forged_payload = json.loads(json.dumps(base_payload))
    u_real = forged_payload["u"]["real"]
    proof = json.loads(Path(u_real["binding_proof"]["path"]).read_text(encoding="utf-8"))
    proof["attested_index_revision"] = proof["attested_index_revision"] + 1
    forged = _write(proof, tmp_path / "forged-u01.json")
    u_real["binding_proof"] = {"path": str(forged), "sha256": file_sha256(forged)}
    forged_result = evaluate_release_gate(_write(forged_payload, tmp_path / "inputs-forged.json"))
    assert forged_result.decision == DECISION_BLOCKED
    codes = {code for row in forged_result.rows for code in row.reasons}
    assert R_BINDING_ATTESTATION_INVALID in codes

    # 2) 删除证明
    deleted_payload = json.loads(json.dumps(base_payload))
    del deleted_payload["u"]["real"]["binding_proof"]
    deleted_result = evaluate_release_gate(_write(deleted_payload, tmp_path / "inputs-deleted.json"))
    assert deleted_result.decision == DECISION_BLOCKED
    assert R_BINDING_PROOF_MISSING in {code for row in deleted_result.rows for code in row.reasons}
    assert any(row.row_id == "binding.p2-t207-r2-20261111-01" for row in deleted_result.rows)

    # 3) 指向别的 run 的证明
    other = base_payload["public"]["runs"][0]["binding_proof"]
    cross_payload = json.loads(json.dumps(base_payload))
    cross_payload["u"]["real"]["binding_proof"] = dict(other)
    cross_result = evaluate_release_gate(_write(cross_payload, tmp_path / "inputs-cross.json"))
    assert cross_result.decision == DECISION_BLOCKED
    assert R_IDENTITY_MISMATCH in {code for row in cross_result.rows for code in row.reasons}


@pytest.mark.skipif(not (RAG_ROOT / "R2").is_dir(),
                    reason="需要本机历史 run 的 rag/trace 库（仓外）")
def test_h2_aggregate_is_wired_with_two_hash_kinds(tmp_path):
    """H2 受限聚合接线：四卡/组合/来源证明逐项 pass；两套哈希分列且不相等。"""
    module = _load_script_module()
    inputs, _ = module.build_inputs(tmp_path / "h2")
    result = evaluate_release_gate(inputs)
    rows = _rows(result)
    assert result.decision == DECISION_PASS
    assert result.to_dict()["release_allowed"] is False
    h2_rows = {row_id: row for row_id, row in rows.items() if row_id.startswith("h2.")}
    assert h2_rows, "H2 行必须存在（不得仍为 PENDING-TASK2）"
    assert not any(row.reasons == ("release_pending_input",) for row in h2_rows.values())
    for row_id in ("h2.aggregate", "h2.cards_index", "h2.source_proof", "h2.coverage",
                   "h2.strata", "h2.quality", "h2.hard_failures", "h2.required_axes",
                   "h2.card.base_b0", "h2.card.base_b0_plus_v01",
                   "h2.card.pre_v05_without_v07", "h2.card.post_v05_without_v01"):
        assert h2_rows[row_id].decision == DECISION_PASS, (row_id, h2_rows[row_id].to_dict())
    assert h2_rows["h2.identity.original"].detail["gate_config_hash"].startswith("d1097573")
    assert h2_rows["h2.identity.release"].detail["gate_config_hash"].startswith("7fa6f47a")
    assert h2_rows["h2.non_required_axes"].decision == DECISION_OBSERVED
    assert h2_rows["h2.non_required_axes"].detail["non_required_unknowns"] == 0
    card = h2_rows["h2.card.base_b0"].detail
    assert card["card_file_sha256"] != card["card_aggregate_sha256"]
    assert card["card_file_sha256"].startswith("14888a0f")
    assert card["card_aggregate_sha256"].startswith("6fd2a94c")
    # D-011 后无 pending；U 的 run 级子集以披露行呈现
    assert not [row for row in rows.values() if row.decision == DECISION_PENDING]
    disclosure = rows["hard_gate_min_sample.run_level_subset"]
    assert disclosure.decision == DECISION_OBSERVED
    assert disclosure.detail["run_level_evaluated"] == 1
    assert rows["u.hard_gates"].decision == DECISION_PASS
    assert rows["hard_gates"].decision == DECISION_PASS


def test_h2_card_file_hash_swapped_with_aggregate_is_rejected(tmp_path):
    """两套哈希混用（把聚合摘要填进 file SHA）→ 阻断，固定原因码。"""
    module = _load_script_module()
    inputs, payload = module.build_inputs(tmp_path / "swap")
    index_path = Path(payload["h2"]["cards_index"]["path"])
    index = json.loads(index_path.read_text(encoding="utf-8"))
    aggregate_path = Path(payload["h2"]["composition_aggregate"]["path"])
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    index["cards"][0]["card_sha256"] = aggregate["cards"][0]["aggregate_sha256"]
    mutated = _write(index, tmp_path / "cards-index-swapped.json")
    payload["h2"]["cards_index"] = {"path": str(mutated), "sha256": file_sha256(mutated)}
    result = evaluate_release_gate(_write(payload, tmp_path / "inputs-swap.json"))
    assert result.decision == DECISION_BLOCKED
    codes = {code for row in result.rows for code in row.reasons}
    assert R_IDENTITY_MISMATCH in codes
    assert _rows(result)["h2.cards_index"].decision == DECISION_BLOCKED
